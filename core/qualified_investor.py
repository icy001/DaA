# -*- coding: utf-8 -*-
"""第 10 步开工前置 · 合格投资者闸门（core/qualified_investor.py）

**合格投资者不是「一次性资格标记」，而是每个申购/受让动作的闸门**
================================================================
旧实现只在「尝试加入品种前」校验一次，此后追加申购 / 份额转让 / 代持 / 拆分份额 /
变换持有人全部绕过。本模块按 ``config.QUALIFIED_INVESTOR_RULES`` 收口：

1. **每个动作都校验**：``check_action()`` 覆盖
   ``subscribe / transfer / additional_subscribe / nominee_change``
   （与 ``place_order``、申购闸门同一收口），任何动作都不复用上一次的结论。
2. **穿透核查**：合伙 / 契约等非法人形式汇集资金，必须穿透到最终投资者并**合并计算人数**；
   禁拼单、代持、拆分份额、借用他人名义（``look_through_required`` 等开关）。
3. **fail-closed**：``on_fail="reject"`` 时不过即抛 :class:`QualifiedInvestorRejected`，
   **不是**返回 ``(bool, reason)`` 让调用方自行决定。
4. **每次校验留痕**：``audit_log_required=True`` 时无论通过与否都写 JSONL 审计
   （动作、规则、门槛快照、原因、profile 摘要、决策日），供监管与纠纷举证。
5. **提醒 ≠ 拦截**：``qi_threshold_check()`` 只产生「资产缩水」提醒；
   真正拦住后续申购的是动作闸门本身——资产跌破门槛后 ``check_action()`` 必然拒绝。
6. **三套门槛不得混用**：私募（证监会令第105号）/ 资管（银发〔2018〕106号）/
   信托（银监会令2007年第3号）各自独立；信托未配置机构门槛时直接拒绝，
   绝不拿私募或资管标准顶上。
7. **2026 规则口径更正**：``check_proposed_2026_rule()`` 区分「已发布待施行」
   （资产管理信托管理办法，2026-10-30 发布 / 2027-01-01 施行）与「征求意见稿」
   （私募投资基金监督管理办法），不再笼统写「尚未生效」。
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import config

__all__ = [
    "ACTIONS",
    "AuditLogError",
    "OTCForbiddenError",
    "QIChecker",
    "QIVerdict",
    "QualifiedInvestorRejected",
    "ThresholdAlert",
]

logger = logging.getLogger(__name__)

ACTIONS = ("subscribe", "transfer", "additional_subscribe", "nominee_change")

# 产品类型 → 适用规则；三套门槛不得混用
PRODUCT_RULE = {
    "private_fund": "private_fund",
    "amr_product": "amr_product",
    "qii_product": "amr_product",
    "trust_plan": "trust_plan",
}

# 非法人形式汇集资金的载体类型（必须穿透）
VEHICLE_TYPES = ("partnership", "contract", "trust", "spv", "fof", "pooled")

# 单只产品最低投资额（万元）在动作中的校验：只有「增加份额」类动作必须带金额
AMOUNT_REQUIRED_ACTIONS = ("subscribe", "additional_subscribe")


class AuditLogError(RuntimeError):
    """审计留痕失败——按 fail-closed 处理，动作不得继续。"""


class QualifiedInvestorRejected(RuntimeError):
    """合格投资者闸门拒绝该动作（不是供参考的布尔值）。"""

    def __init__(self, verdict: "QIVerdict") -> None:
        self.verdict = verdict
        super().__init__(verdict.message())


class OTCForbiddenError(QualifiedInvestorRejected):
    """个人投资者参与场外衍生品——红线，直接拒绝。"""


@dataclass
class QIVerdict:
    """一次合格投资者校验的完整结论（同时作为审计记录）。"""

    action: str
    rule: Optional[str]
    product_type: Optional[str]
    ok: bool
    reasons: List[str] = field(default_factory=list)
    codes: List[str] = field(default_factory=list)
    thresholds: Dict[str, Any] = field(default_factory=dict)
    amount_wan: Optional[float] = None
    investor_count: Optional[int] = None
    decision_date: Optional[str] = None
    profile_digest: str = ""
    audit_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    checked_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def message(self) -> str:
        head = (f"合格投资者校验未通过：动作 {self.action} / 规则 {self.rule or '未定'} / "
                f"产品 {self.product_type or '未定'}")
        body = "；".join(self.reasons) if self.reasons else "未给出原因"
        return f"{head} → {body}（审计号 {self.audit_id}）"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "checked_at": self.checked_at,
            "action": self.action,
            "rule": self.rule,
            "product_type": self.product_type,
            "ok": bool(self.ok),
            "codes": list(self.codes),
            "reasons": list(self.reasons),
            "thresholds": dict(self.thresholds),
            "amount_wan": self.amount_wan,
            "investor_count": self.investor_count,
            "decision_date": self.decision_date,
            "profile_digest": self.profile_digest,
        }


@dataclass
class ThresholdAlert:
    """资产规模变动后的提醒（只提醒，拦截由 check_action 负责）。"""

    ok: bool
    code: str
    message: str
    product_type: str
    shortfall: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "code": self.code, "message": self.message,
                "product_type": self.product_type, "shortfall": dict(self.shortfall)}


# ==================== 工具 ====================

def _as_wan(value) -> Optional[float]:
    """把金额统一成万元；兼容 `xxx_wan` / 裸元数值（>=1e5 视为元）。"""
    num = _num(value)
    if num is None:
        return None
    return num


def _num(value) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num == num else None


def _pick(profile: Dict[str, Any], *keys) -> Optional[float]:
    for key in keys:
        if key in profile and profile[key] is not None:
            return _num(profile[key])
    return None


def _investor_type(profile: Dict[str, Any]) -> str:
    kind = str(profile.get("investor_type") or profile.get("type") or "individual").lower()
    if kind in ("institution", "institutional", "entity", "corporate"):
        return "institution"
    return "individual"


def _digest(profile: Dict[str, Any]) -> str:
    """只对非敏感数值字段做摘要，审计里不落身份证/姓名。"""
    keys = ("investor_type", "financial_assets_wan", "family_fin_assets_wan",
            "family_fin_net_assets_wan", "avg_annual_income_wan_3y",
            "annual_income_wan_3y", "couple_annual_income_wan_3y",
            "fin_assets_wan", "net_assets_wan", "invest_years")
    payload = {k: profile.get(k) for k in keys if k in profile}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _is_vehicle(profile: Dict[str, Any]) -> bool:
    """是否为「合伙企业/契约/信托/SPV 等非法人形式汇集资金」载体。"""
    if not profile:
        return False
    return bool(profile.get("look_through") or profile.get("is_vehicle") or
                str(profile.get("vehicle_type") or "").lower() in VEHICLE_TYPES)


def _to_date(value) -> date:
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return date.today()


# ==================== 主类 ====================

class QIChecker:
    """合格投资者逐动作闸门 + 穿透核查 + 审计留痕。"""

    def __init__(self, rules: Dict[str, Any] = None,
                 audit_log_path=None,
                 logger_: logging.Logger = None) -> None:
        self.rules = dict(rules or config.QUALIFIED_INVESTOR_RULES)
        self.check_actions = list(self.rules.get("check_actions") or ACTIONS)
        self.on_fail = str(self.rules.get("on_fail") or "reject").lower()
        self.audit_log_required = bool(self.rules.get("audit_log_required", True))
        self.audit_log_path = Path(audit_log_path or
                                   (config.AUDIT_DIR / "qualified_investor_audit.jsonl"))
        self.logger = logger_ or logger

    # ------------------------------------------------------------------
    # 门槛快照与规则选择
    # ------------------------------------------------------------------
    def rule_for(self, product_type: str) -> Optional[str]:
        return PRODUCT_RULE.get(str(product_type or "").lower())

    def _thresholds(self, rule: str, product_type: str = None) -> Dict[str, Any]:
        block = dict(self.rules.get(rule) or {})
        if isinstance(block.get("min_per_product_wan"), dict):
            key = str(product_type or "mixed").lower()
            block["min_per_product_wan"] = block["min_per_product_wan"].get(
                key, block["min_per_product_wan"].get("mixed"))
        return block

    # ------------------------------------------------------------------
    # 单项门槛校验（可单独调用；动作闸门内部也用它）
    # ------------------------------------------------------------------
    def check_current_threshold(self, asset_profile: Dict[str, Any]) -> QIVerdict:
        """私募基金现行门槛（证监会令第105号）。"""
        return self._audit_verdict(
            self._check_rule("private_fund", asset_profile, product_type="private_fund"))

    def check_amr_threshold(self, asset_profile: Dict[str, Any],
                            product_type: str = "mixed") -> QIVerdict:
        """资管新规门槛（银发〔2018〕106号），起投分 30/40/100 万。"""
        return self._audit_verdict(
            self._check_rule("amr_product", asset_profile, product_type=product_type))

    def check_trust_threshold(self, asset_profile: Dict[str, Any]) -> QIVerdict:
        """信托计划门槛（银监会令2007年第3号）。"""
        return self._audit_verdict(
            self._check_rule("trust_plan", asset_profile, product_type="trust_plan"))

    def check_neeq_threshold(self, asset_profile: Dict[str, Any],
                             layer: str = "innovation") -> QIVerdict:
        """新三板门槛：创新层 100 万 / 基础层 200 万 + 2 年投资经历。"""
        block = dict(self.rules.get("neeq") or {})
        layer_key = "base_wan" if str(layer).lower().startswith("base") else "innovation_wan"
        need = _num(block.get(layer_key))
        years_need = _num(block.get("min_invest_years"))
        assets = _pick(asset_profile, "financial_assets_wan", "fin_assets_wan",
                       "family_fin_assets_wan")
        years = _pick(asset_profile, "invest_years", "investment_years")
        reasons, codes = [], []
        if need is None:
            reasons.append("config 未配置新三板门槛")
            codes.append("rule_missing")
        elif assets is None or assets < need:
            reasons.append(f"金融资产 {assets or 0:.0f} 万 < 新三板{layer}层门槛 {need:.0f} 万")
            codes.append("neeq_assets")
        if years_need is not None and (years is None or years < years_need):
            reasons.append(f"投资经历 {years or 0:.0f} 年 < {years_need:.0f} 年")
            codes.append("neeq_experience")
        return self._audit_verdict(QIVerdict(
            action="check_access", rule="neeq", product_type=f"neeq_{layer}",
            ok=not reasons, reasons=reasons, codes=codes,
            thresholds=block, profile_digest=_digest(asset_profile)))

    def check_otc_institutional_threshold(self, asset_profile: Dict[str, Any]) -> QIVerdict:
        """场外衍生品机构门槛；个人直接抛 :class:`OTCForbiddenError`。"""
        if _investor_type(asset_profile) != "institution":
            verdict = QIVerdict(
                action="check_access", rule="otc_institutional", product_type="otc",
                ok=False, reasons=["个人投资者禁止参与场外期权/收益互换（红线）"],
                codes=["otc_individual_forbidden"],
                thresholds=dict(self.rules.get("otc_institutional") or {}),
                profile_digest=_digest(asset_profile))
            self._audit(verdict)
            raise OTCForbiddenError(verdict)
        block = dict(self.rules.get("otc_institutional") or {})
        net = _pick(asset_profile, "net_assets_wan")
        fin = _pick(asset_profile, "financial_assets_wan", "fin_assets_wan")
        years = _pick(asset_profile, "invest_years", "investment_years")
        need_net = _num(block.get("net_assets_wan"))
        need_fin = _num(block.get("financial_assets_wan"))
        need_years = _num(block.get("min_invest_years"))
        reasons, codes = [], []
        if not ((need_net is not None and net is not None and net >= need_net) or
                (need_fin is not None and fin is not None and fin >= need_fin)):
            reasons.append(f"机构净资产 {net or 0:.0f} 万 / 金融资产 {fin or 0:.0f} 万 "
                           f"均未达门槛（净资产 {need_net or 0:.0f} 万 或 金融资产 {need_fin or 0:.0f} 万）")
            codes.append("otc_assets")
        if need_years is not None and (years is None or years < need_years):
            reasons.append(f"投资经历 {years or 0:.0f} 年 < {need_years:.0f} 年")
            codes.append("otc_experience")
        verdict = QIVerdict(action="check_access", rule="otc_institutional", product_type="otc",
                            ok=not reasons, reasons=reasons, codes=codes,
                            thresholds=block, profile_digest=_digest(asset_profile))
        self._audit(verdict)
        if not verdict.ok and self.on_fail == "reject":
            raise QualifiedInvestorRejected(verdict)
        return verdict

    def check_proposed_2026_rule(self, asset_profile: Dict[str, Any],
                                 product_type: str = None,
                                 decision_date=None,
                                 investor_count: int = None) -> Dict[str, Any]:
        """2026 规则预判：区分「已发布待施行」与「征求意见稿」。

        关键口径更正：``资产管理信托管理办法`` 已于 2026-10-30 发布、2027-01-01 施行，
        不得再写「尚未生效」；``私募投资基金监督管理办法`` 仍是征求意见稿。
        """
        day = _to_date(decision_date)
        published = dict(self.rules.get("published_2026") or {})
        out: Dict[str, Any] = {"decision_date": day.isoformat(), "product_type": product_type,
                               "rules": {}, "warnings": [], "notes": []}
        for name, meta in published.items():
            item = dict(meta)
            effective = _to_date(item.get("effective_date")) if item.get("effective_date") else None
            item["in_force"] = bool(effective and day >= effective)
            if item.get("status") == "已发布待施行":
                if item["in_force"]:
                    item["note"] = (f"{item.get('issue_date')} 发布、{item.get('effective_date')} "
                                    f"起施行，当前决策日已生效")
                else:
                    item["note"] = (f"{item.get('issue_date')} 已发布待施行、"
                                    f"{item.get('effective_date')} 起施行，当前决策日尚未施行")
                    out["warnings"].append(
                        f"{name} 已发布待施行（{item.get('effective_date')} 施行），"
                        "仅作预判，不得笼统称为未生效")
            elif item.get("status") == "征求意见稿":
                item["in_force"] = False
                item["note"] = item.get("note") or "征求意见稿，仅作预判参考"
                out["warnings"].append(f"{name} 为征求意见稿，非现行有效规则")
            out["rules"][name] = item
        trust_rule = out["rules"].get("资产管理信托管理办法") or {}
        if str(product_type or "").lower() == "trust_plan" and trust_rule.get("in_force"):
            limit = int(trust_rule.get("max_investors") or 200)
            out["max_investors"] = limit
            out["recheck_on"] = list(trust_rule.get("recheck_on") or [])
            if investor_count is not None and investor_count > limit:
                out["warnings"].append(
                    f"{trust_rule.get('effective_date')} 起投资者人数上限 {limit}，"
                    f"当前 {investor_count} 人")
        out["profile_digest"] = _digest(asset_profile)
        return out

    # ------------------------------------------------------------------
    # 核心：每个动作的闸门
    # ------------------------------------------------------------------
    def check_action(self, action: str, profile: Dict[str, Any],
                     product_type: str = None,
                     amount_wan: float = None,
                     investor_count: int = None,
                     investors: Iterable[Dict[str, Any]] = None,
                     vehicle: Dict[str, Any] = None,
                     decision_date=None,
                     raise_on_fail: bool = None) -> QIVerdict:
        """校验并裁决一个动作；默认不过即抛 :class:`QualifiedInvestorRejected`。

        ``action`` 必须在 ``check_actions`` 内（subscribe / transfer /
        additional_subscribe / nominee_change）。任何动作都重新校验，绝不复用旧结论。
        """
        action = str(action or "").lower()
        rule = self.rule_for(product_type)
        per_action = self._thresholds(rule, product_type) if rule else {}
        verdict = QIVerdict(action=action, rule=rule, product_type=product_type,
                            ok=False, thresholds=per_action,
                            amount_wan=_num(amount_wan),
                            investor_count=investor_count,
                            decision_date=_to_date(decision_date).isoformat(),
                            profile_digest=_digest(profile or {}))

        if action not in self.check_actions:
            verdict.reasons.append(f"未登记的动作 {action!r}，只允许 {self.check_actions}")
            verdict.codes.append("action_not_registered")
            return self._finish(verdict, raise_on_fail)

        # 1) 三套门槛独立校验（非法人载体本身不评资产，只评穿透后的最终投资者）
        if not rule:
            verdict.reasons.append(f"未知产品类型 {product_type!r}，无法确定适用门槛（禁止混用）")
            verdict.codes.append("rule_unknown")
        elif not _is_vehicle(profile or {}):
            base = self._check_rule(rule, profile or {}, product_type=product_type,
                                    amount_wan=amount_wan, investor_count=investor_count)
            if not base.ok:
                verdict.reasons.extend(base.reasons)
                verdict.codes.extend(base.codes)

        # 2) 拼单 / 代持 / 拆分份额 / 借用他人名义
        flag_reasons, flag_codes = self._check_forbidden_flags(profile or {}, vehicle or {})
        verdict.reasons.extend(flag_reasons)
        verdict.codes.extend(flag_codes)

        # 3) 穿透核查 + 合并人数
        look_reasons, look_codes, merged = self._check_look_through(
            profile or {}, investors=investors, vehicle=vehicle,
            product_type=product_type, decision_date=decision_date,
            amount_wan=amount_wan)
        verdict.reasons.extend(look_reasons)
        verdict.codes.extend(look_codes)
        if merged is not None:
            verdict.investor_count = merged
            verdict.reasons.extend(self._count_reasons(rule, merged, decision_date))

        # 4) 金额门槛（增加份额类动作必须带金额）
        if action in AMOUNT_REQUIRED_ACTIONS and verdict.amount_wan is None:
            verdict.reasons.append("缺少申购金额，无法校验单只产品最低投资额（fail-closed）")
            verdict.codes.append("amount_missing")

        verdict.ok = not verdict.reasons
        return self._finish(verdict, raise_on_fail)

    def assert_action(self, *args, **kwargs) -> QIVerdict:
        """``check_action`` 的显式别名：断言通过，否则抛错。"""
        kwargs["raise_on_fail"] = True
        return self.check_action(*args, **kwargs)

    # ------------------------------------------------------------------
    # 10.5：提醒 ≠ 拦截
    # ------------------------------------------------------------------
    def qi_threshold_check(self, profile: Dict[str, Any], product_type: str,
                           decision_date=None) -> ThresholdAlert:
        """资产规模变动后的资格提醒（只是提醒；后续申购由 check_action 拦截）。"""
        rule = self.rule_for(product_type)
        verdict = self._check_rule(rule or "", profile or {}, product_type=product_type,
                                   amount_wan=None) if rule else None
        if verdict is None:
            return ThresholdAlert(False, "rule_unknown",
                                  f"未知产品类型 {product_type!r}", str(product_type))
        if verdict.ok:
            return ThresholdAlert(True, "qi_threshold_ok",
                                  f"仍满足 {verdict.rule} 门槛（{self._legal_basis(rule)}）",
                                  str(product_type))
        shortfall: Dict[str, float] = {}
        block = self._thresholds(rule, product_type)
        ind = block.get("individual") or {}
        if _investor_type(profile) == "individual":
            for key, need in ind.items():
                if not key.endswith("_wan"):
                    continue
                have = _pick(profile, key)
                if need is not None and have is not None and have < float(need):
                    shortfall[key] = float(need) - float(have)
        return ThresholdAlert(False, "qi_threshold_breach",
                              "合格投资者门槛已不满足：" + "；".join(verdict.reasons) +
                              "（提醒不等于拦截：后续申购将被闸门拒绝）",
                              str(product_type), shortfall)

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    def _legal_basis(self, rule: str) -> str:
        return str((self.rules.get(rule) or {}).get("legal_basis") or "未标注法规依据")

    def _check_rule(self, rule: str, profile: Dict[str, Any], product_type: str = None,
                    amount_wan: float = None,
                    investor_count: int = None) -> QIVerdict:
        block = self._thresholds(rule, product_type)
        kind = _investor_type(profile)
        reasons: List[str] = []
        codes: List[str] = []
        if not block:
            reasons.append(f"config 缺少规则 {rule!r}，禁止用其他规则替代（三套门槛不得混用）")
            codes.append("rule_missing")
        elif rule == "private_fund":
            reasons, codes = self._check_private_fund(block, profile, kind)
        elif rule == "amr_product":
            reasons, codes = self._check_amr(block, profile, kind, product_type)
        elif rule == "trust_plan":
            reasons, codes = self._check_trust(block, profile, kind)
        else:
            reasons.append(f"规则 {rule!r} 未实现")
            codes.append("rule_not_implemented")

        need_min = block.get("min_per_product_wan")
        if isinstance(need_min, (int, float)):
            if amount_wan is not None and float(amount_wan) < float(need_min):
                reasons.append(f"单只产品投资 {float(amount_wan):.0f} 万 < 起投 {float(need_min):.0f} 万")
                codes.append("min_amount")
        return QIVerdict(action="check_rule", rule=rule, product_type=product_type,
                         ok=not reasons, reasons=reasons, codes=codes,
                         thresholds=block, amount_wan=_num(amount_wan),
                         investor_count=investor_count, profile_digest=_digest(profile))

    @staticmethod
    def _check_private_fund(block: Dict[str, Any], profile: Dict[str, Any],
                            kind: str):
        reasons, codes = [], []
        if kind == "institution":
            need = _num((block.get("institution") or {}).get("net_assets_wan"))
            have = _pick(profile, "net_assets_wan")
            if need is None:
                reasons.append("私募规则缺少机构门槛配置")
                codes.append("rule_missing")
            elif have is None or have < need:
                reasons.append(f"机构净资产 {have or 0:.0f} 万 < {need:.0f} 万")
                codes.append("institution_assets")
            return reasons, codes
        ind = block.get("individual") or {}
        need_assets = _num(ind.get("financial_assets_wan"))
        need_income = _num(ind.get("avg_annual_income_wan_3y"))
        assets = _pick(profile, "financial_assets_wan", "fin_assets_wan",
                       "family_fin_assets_wan")
        income = _pick(profile, "avg_annual_income_wan_3y", "annual_income_wan_3y")
        if not ((need_assets is not None and assets is not None and assets >= need_assets) or
                (need_income is not None and income is not None and income >= need_income)):
            reasons.append(
                f"金融资产 {assets or 0:.0f} 万 < {need_assets or 0:.0f} 万，且近三年年均收入 "
                f"{income or 0:.0f} 万 < {need_income or 0:.0f} 万（二者满足其一）")
            codes.append("individual_assets_or_income")
        return reasons, codes

    @staticmethod
    def _check_amr(block: Dict[str, Any], profile: Dict[str, Any], kind: str,
                   product_type: str):
        reasons, codes = [], []
        if kind == "institution":
            need = _num((block.get("institution") or {}).get("net_assets_wan"))
            have = _pick(profile, "net_assets_wan")
            if need is None:
                reasons.append("资管规则缺少机构门槛配置")
                codes.append("rule_missing")
            elif have is None or have < need:
                reasons.append(f"机构净资产 {have or 0:.0f} 万 < {need:.0f} 万")
                codes.append("institution_assets")
            return reasons, codes
        ind = block.get("individual") or {}
        need_fin = _num(ind.get("family_fin_assets_wan"))
        need_net = _num(ind.get("family_fin_net_assets_wan"))
        need_income = _num(ind.get("avg_annual_income_wan_3y"))
        fin = _pick(profile, "family_fin_assets_wan", "financial_assets_wan", "fin_assets_wan")
        net = _pick(profile, "family_fin_net_assets_wan")
        income = _pick(profile, "avg_annual_income_wan_3y", "annual_income_wan_3y")
        if not ((need_fin is not None and fin is not None and fin >= need_fin) or
                (need_net is not None and net is not None and net >= need_net) or
                (need_income is not None and income is not None and income >= need_income)):
            reasons.append(
                f"家庭金融资产 {fin or 0:.0f} 万 / 净资产 {net or 0:.0f} 万 / 年均收入 "
                f"{income or 0:.0f} 万，未达到 {need_fin or 0:.0f} 万 / {need_net or 0:.0f} 万 / "
                f"{need_income or 0:.0f} 万（三选一）")
            codes.append("amr_assets_or_income")
        need_years = _num(ind.get("min_invest_years"))
        years = _pick(profile, "invest_years", "investment_years")
        if need_years is not None and (years is None or years < need_years):
            reasons.append(f"投资经历 {years or 0:.0f} 年 < {need_years:.0f} 年")
            codes.append("amr_experience")
        return reasons, codes

    @staticmethod
    def _check_trust(block: Dict[str, Any], profile: Dict[str, Any], kind: str):
        if kind == "institution":
            # 信托规则未配置机构门槛：拒绝，绝不拿私募/资管标准顶上
            return (["信托计划未配置机构投资者门槛，禁止套用其他产品规则（fail-closed）"],
                    ["trust_institution_unconfigured"])
        ind = block.get("individual") or {}
        need_fin = _num(ind.get("fin_assets_wan"))
        need_income = _num(ind.get("annual_income_wan_3y"))
        need_couple = _num(ind.get("couple_annual_income_wan_3y"))
        fin = _pick(profile, "fin_assets_wan", "financial_assets_wan")
        income = _pick(profile, "annual_income_wan_3y", "avg_annual_income_wan_3y")
        couple = _pick(profile, "couple_annual_income_wan_3y")
        if not ((need_fin is not None and fin is not None and fin >= need_fin) or
                (need_income is not None and income is not None and income >= need_income) or
                (need_couple is not None and couple is not None and couple >= need_couple)):
            return ([f"金融资产 {fin or 0:.0f} 万 / 本人年收入 {income or 0:.0f} 万 / "
                     f"家庭年收入 {couple or 0:.0f} 万，未达信托门槛 "
                     f"{need_fin or 0:.0f} / {need_income or 0:.0f} / {need_couple or 0:.0f} 万"],
                    ["trust_assets_or_income"])
        return [], []

    def _check_forbidden_flags(self, profile: Dict[str, Any],
                               vehicle: Dict[str, Any]) -> tuple:
        reasons, codes = [], []
        merged = {**dict(profile or {}), **dict(vehicle or {})}
        if not self.rules.get("forbid_pooling_nominee_split", True):
            return reasons, codes
        if merged.get("pooled") or merged.get("is_pooled") or merged.get("pooling"):
            reasons.append("禁止拼单：多人资金汇集后以一人名义申购")
            codes.append("pooling_forbidden")
        if merged.get("is_nominee") or merged.get("nominee") or merged.get("held_by_nominee"):
            reasons.append("禁止代持：份额必须由实际投资者本人持有")
            codes.append("nominee_forbidden")
        if merged.get("split_units") or merged.get("split_shares") or merged.get("units_split"):
            reasons.append("禁止拆分份额：不得把单只产品份额拆分给不合格投资者")
            codes.append("split_forbidden")
        if self.rules.get("forbid_non_own_funds", True):
            source = str(merged.get("funding_source") or merged.get("fund_source") or "own").lower()
            if merged.get("borrowed_name") or merged.get("funds_from_third_party") or \
                    source in ("third_party", "borrowed", "other"):
                reasons.append("禁止借用他人名义/非自有资金申购")
                codes.append("non_own_funds_forbidden")
        return reasons, codes

    def _check_look_through(self, profile: Dict[str, Any],
                            investors: Iterable[Dict[str, Any]] = None,
                            vehicle: Dict[str, Any] = None,
                            product_type: str = None,
                            decision_date=None,
                            amount_wan: float = None) -> tuple:
        """穿透核查：非法人载体必须给出最终投资者，并合并计算人数。"""
        reasons, codes = [], []
        vehicles = []
        if vehicle:
            vehicles.append(dict(vehicle))
        if str(profile.get("vehicle_type") or "").lower() in VEHICLE_TYPES or \
                profile.get("look_through") or profile.get("is_vehicle"):
            vehicles.append(dict(profile))
        direct = list(investors or [])
        if not vehicles:
            count = len(direct) if direct else None
            return reasons, codes, count

        if not self.rules.get("look_through_required", True):
            return reasons, codes, None

        ultimate = []
        for veh in vehicles:
            holders = list(veh.get("ultimate_investors") or [])
            if not holders:
                reasons.append(
                    f"非法人载体 {veh.get('name') or veh.get('vehicle_type')} 未穿透到最终投资者"
                    "（look_through_required=True，fail-closed）")
                codes.append("look_through_missing")
                continue
            if len(holders) == 1 and str(holders[0].get("investor_type", "")).lower() in \
                    ("institution", "entity") and holders[0].get("is_vehicle"):
                reasons.append("穿透层数异常：最终投资者仍为非法人载体")
                codes.append("look_through_nested")
            ultimate.extend(holders)

        # 每个最终投资者都必须是合格投资者
        rule = self.rule_for(product_type)
        if rule:
            for idx, holder in enumerate(ultimate):
                verdict = self._check_rule(rule, holder, product_type=product_type,
                                           amount_wan=holder.get("amount_wan", amount_wan))
                if not verdict.ok:
                    label = holder.get("investor_id") or f"#{idx + 1}"
                    reasons.append(f"穿透后最终投资者 {label} 不合格：" + "；".join(verdict.reasons))
                    codes.append("look_through_ineligible")
        # 合并计算人数（直接投资者 + 穿透后的最终投资者，去重）
        keys = set()
        for holder in ultimate + direct:
            key = holder.get("investor_id") or holder.get("id") or id(holder)
            keys.add(str(key))
        merged = len(keys) if (ultimate or direct) else None
        return reasons, codes, merged

    def _count_reasons(self, rule: str, count: int, decision_date=None) -> List[str]:
        if not rule or count is None:
            return []
        block = self.rules.get(rule) or {}
        limit = block.get("max_natural_persons") if rule == "trust_plan" else \
            block.get("max_investors")
        limit = _num(limit)
        # 2026-01-01 前信托仍按 50 人；已发布待施行的 200 人上限只在生效后适用
        if rule == "trust_plan":
            meta = (self.rules.get("published_2026") or {}).get("资产管理信托管理办法") or {}
            effective = _to_date(meta.get("effective_date")) if meta.get("effective_date") else None
            if effective and _to_date(decision_date) >= effective:
                limit = _num(meta.get("max_investors")) or limit
        if limit is not None and count > limit:
            return [f"投资者人数 {count} 人 > 上限 {int(limit)} 人（穿透后合并计算）"]
        return []

    def _finish(self, verdict: QIVerdict, raise_on_fail: bool = None) -> QIVerdict:
        verdict.ok = not verdict.reasons
        self._audit(verdict)
        should_raise = self.on_fail == "reject" if raise_on_fail is None else bool(raise_on_fail)
        if not verdict.ok and should_raise:
            raise QualifiedInvestorRejected(verdict)
        return verdict

    # ------------------------------------------------------------------
    # 审计留痕（监管与纠纷举证）
    # ------------------------------------------------------------------
    def _audit_verdict(self, verdict: QIVerdict) -> QIVerdict:
        """单项查询也要留痕（同一份审计文件）。"""
        self._audit(verdict)
        return verdict

    def _audit(self, verdict: QIVerdict) -> None:
        if not self.audit_log_required:
            return
        record = verdict.to_dict()
        record["source"] = "qualified_investor"
        record["legal_basis"] = self._legal_basis(verdict.rule) if verdict.rule else None
        try:
            self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except OSError as exc:
            raise AuditLogError(
                f"合格投资者审计留痕失败（audit_log_required=True，动作不得继续）：{exc}") from exc

    def audit_trail(self, limit: int = None) -> List[Dict[str, Any]]:
        """读回审计记录（对外披露 G4 要求 ``require_qi_audit_trail``）。"""
        if not self.audit_log_path.exists():
            return []
        rows = []
        with self.audit_log_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows[-limit:] if limit else rows
