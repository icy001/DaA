# -*- coding: utf-8 -*-
"""G1：合格投资者「每个动作的闸门」验收（tests/test_qualified_investor.py）。

覆盖 10.0 全部硬约束：
  1) 校验收口在每个动作：subscribe / transfer / additional_subscribe / nominee_change；
  2) 穿透核查：非法人载体必须给出最终投资者并合并人数；
  3) fail-closed：不过即抛 QualifiedInvestorRejected，且写审计留痕；
  4) 提醒 ≠ 拦截：资产缩水提醒后，后续申购仍被闸门拦住；
  5) 三套门槛不得混用（私募 / 资管 / 信托各自独立）；
  6) 2026 规则区分「已发布待施行」与「征求意见稿」。
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from core.qualified_investor import (OTCForbiddenError, QIChecker,
                                     QualifiedInvestorRejected)

ACTIONABLE = ["subscribe", "transfer", "additional_subscribe", "nominee_change"]

IND_OK = {"investor_type": "individual", "financial_assets_wan": 350,
          "avg_annual_income_wan_3y": 20, "invest_years": 3}
IND_LOW = {"investor_type": "individual", "financial_assets_wan": 100,
           "avg_annual_income_wan_3y": 10, "invest_years": 1}


def checker(tmp_path) -> QIChecker:
    return QIChecker(audit_log_path=tmp_path / "qi_audit.jsonl")


# ==================== 1. config ====================

def test_config_registration():
    rules = config.QUALIFIED_INVESTOR_RULES
    assert rules["check_at_every_action"] is True
    assert rules["check_actions"] == ["subscribe", "transfer",
                                      "additional_subscribe", "nominee_change"]
    assert rules["look_through_required"] is True
    assert rules["forbid_pooling_nominee_split"] is True
    assert rules["forbid_non_own_funds"] is True
    assert rules["on_fail"] == "reject"
    assert rules["audit_log_required"] is True
    assert rules["private_fund"]["legal_basis"] == "证监会令第105号"
    assert rules["amr_product"]["legal_basis"] == "银发〔2018〕106号"
    assert rules["trust_plan"]["legal_basis"] == "银监会令2007年第3号"
    assert rules["amr_product"]["min_per_product_wan"] == {
        "fixed_income": 30, "mixed": 40, "equity": 100, "derivatives": 100}
    nav = config.NAV_PRODUCT_CONFIG
    assert nav["nav_layers"] == ["product_gross", "product_net", "investor_net"]
    assert nav["disclosure_layer"] == "investor_net"
    assert nav["enforce_decision_after_disclosure"] is True
    assert nav["forbid_nav_as_kline"] is True
    assert config.DISCLOSURE_CONFORMANCE["must_include_fee_breakdown"] == [
        "subscription", "redemption", "management", "performance", "custodian"]
    points = config.SIGNAL_EGRESS_CONFORMANCE["signal_egress_points"]
    assert "investor_disclosure" in points
    assert "live_order_submit" in points and "watch_only_live_push" in points


# ==================== 2. 每个动作都校验 ====================

@pytest.mark.parametrize("action", ACTIONABLE)
def test_every_action_rejected_for_ineligible(tmp_path, action):
    qi = checker(tmp_path)
    with pytest.raises(QualifiedInvestorRejected) as info:
        qi.check_action(action, IND_LOW, product_type="private_fund", amount_wan=150)
    verdict = info.value.verdict
    assert verdict.ok is False
    assert verdict.action == action
    assert verdict.reasons
    assert verdict.thresholds["legal_basis"] == "证监会令第105号"


def test_additional_subscribe_does_not_reuse_previous_pass(tmp_path):
    """首次申购通过 ≠ 后续追加申购通过：资产缩水后必须重新拦截。"""
    qi = checker(tmp_path)
    first = qi.check_action("subscribe", IND_OK, product_type="private_fund", amount_wan=150)
    assert first.ok is True
    degraded = dict(IND_OK, financial_assets_wan=80, avg_annual_income_wan_3y=10)
    with pytest.raises(QualifiedInvestorRejected):
        qi.check_action("additional_subscribe", degraded,
                        product_type="private_fund", amount_wan=150)


def test_fail_closed_raises_not_returns_tuple(tmp_path):
    qi = checker(tmp_path)
    # 信托门槛为「金融资产 100 万 / 本人年收入 20 万 / 家庭年收入 30 万」三选一，
    # 因此这里三条全部不达标才构成 fail-closed 场景。
    trust_low = dict(IND_LOW, financial_assets_wan=50,
                     avg_annual_income_wan_3y=5, couple_annual_income_wan_3y=8)
    with pytest.raises(QualifiedInvestorRejected):
        qi.assert_action("nominee_change", trust_low, product_type="trust_plan")


# ==================== 3. 穿透核查 ====================

def test_look_through_requires_ultimate_investors(tmp_path):
    qi = checker(tmp_path)
    vehicle = {"name": "某某合伙", "vehicle_type": "partnership"}
    with pytest.raises(QualifiedInvestorRejected) as info:
        qi.check_action("subscribe", vehicle, product_type="private_fund", amount_wan=150)
    assert "look_through_missing" in info.value.verdict.codes


def test_look_through_merges_count_and_checks_each(tmp_path):
    qi = checker(tmp_path)
    vehicle = {"name": "某某合伙", "vehicle_type": "partnership",
               "ultimate_investors": [dict(IND_OK, investor_id="U1"),
                                      dict(IND_OK, investor_id="U2")]}
    verdict = qi.check_action("subscribe", vehicle, product_type="private_fund",
                              amount_wan=150)
    assert verdict.ok is True
    assert verdict.investor_count == 2

    bad = {"name": "某某契约", "vehicle_type": "contract",
           "ultimate_investors": [dict(IND_OK, investor_id="U1"),
                                  dict(IND_LOW, investor_id="U2")]}
    with pytest.raises(QualifiedInvestorRejected) as info:
        qi.check_action("subscribe", bad, product_type="private_fund", amount_wan=150)
    assert "look_through_ineligible" in info.value.verdict.codes


def test_forbidden_pooling_nominee_split_and_borrowed_funds(tmp_path):
    qi = checker(tmp_path)
    for flag in ("pooled", "is_nominee", "split_units"):
        with pytest.raises(QualifiedInvestorRejected) as info:
            qi.check_action("subscribe", dict(IND_OK, **{flag: True}),
                            product_type="private_fund", amount_wan=150)
        assert any(code.endswith("_forbidden") for code in info.value.verdict.codes)
    with pytest.raises(QualifiedInvestorRejected) as info:
        qi.check_action("subscribe", dict(IND_OK, funding_source="third_party"),
                        product_type="private_fund", amount_wan=150)
    assert "non_own_funds_forbidden" in info.value.verdict.codes


def test_investor_count_limit_after_look_through(tmp_path):
    qi = checker(tmp_path)
    holders = [dict(IND_OK, investor_id=f"U{i}") for i in range(201)]
    vehicle = {"name": "超限合伙", "vehicle_type": "partnership",
               "ultimate_investors": holders}
    with pytest.raises(QualifiedInvestorRejected) as info:
        qi.check_action("subscribe", vehicle, product_type="private_fund", amount_wan=150)
    assert any("201" in r and "上限 200" in r for r in info.value.verdict.reasons)


# ==================== 4. 三套门槛不得混用 ====================

def test_three_rule_sets_are_independent(tmp_path):
    qi = checker(tmp_path)
    # 私募 300 万：资管家庭金融资产 600 万可过，私募同一个人也过；信托 100 万也能过
    assert qi.check_current_threshold(IND_OK).ok is True
    assert qi.check_amr_threshold({"family_fin_assets_wan": 600,
                                   "invest_years": 3}, "mixed").ok is True
    # 资管 500 万门槛下，只有 350 万私募合格者不能过
    amr = qi.check_amr_threshold(IND_OK, "mixed")
    assert amr.ok is False and "amr_assets_or_income" in amr.codes
    # 资管起投分档：固收 30 / 混合 40 / 权益 100（同一 profile 下 29 万被拒）
    profile = {"family_fin_assets_wan": 600, "invest_years": 3}
    with pytest.raises(QualifiedInvestorRejected) as info:
        qi.check_action("subscribe", profile, product_type="qii_product",
                        amount_wan=29)
    assert "min_amount" in info.value.verdict.codes
    # 信托未配置机构门槛：拒绝，不得拿私募 1000 万顶上
    trust_inst = qi.check_trust_threshold({"investor_type": "institution",
                                           "net_assets_wan": 5000})
    assert trust_inst.ok is False
    assert "trust_institution_unconfigured" in trust_inst.codes


def test_neeq_and_otc_thresholds(tmp_path):
    qi = checker(tmp_path)
    assert qi.check_neeq_threshold({"financial_assets_wan": 150, "invest_years": 3},
                                   "innovation").ok is True
    base = qi.check_neeq_threshold({"financial_assets_wan": 150, "invest_years": 3},
                                   "base")
    assert base.ok is False and "neeq_assets" in base.codes
    with pytest.raises(OTCForbiddenError):
        qi.check_otc_institutional_threshold({"investor_type": "individual",
                                              "financial_assets_wan": 9999})
    assert qi.check_otc_institutional_threshold(
        {"investor_type": "institution", "net_assets_wan": 6000,
         "invest_years": 4}).ok is True


# ==================== 5. 2026 规则口径 ====================

def test_2026_rules_distinguish_published_and_draft(tmp_path):
    qi = checker(tmp_path)
    before = qi.check_proposed_2026_rule(IND_OK, product_type="trust_plan",
                                         decision_date=date(2026, 11, 12))
    trust = before["rules"]["资产管理信托管理办法"]
    assert trust["status"] == "已发布待施行"
    assert trust["issue_date"] == "2026-10-30"
    assert trust["effective_date"] == "2027-01-01"
    assert trust["in_force"] is False
    draft = before["rules"]["私募投资基金监督管理办法"]
    assert draft["status"] == "征求意见稿"
    text = json.dumps(before, ensure_ascii=False)
    assert "尚未生效" not in text
    assert "已发布待施行" in text

    after = qi.check_proposed_2026_rule(IND_OK, product_type="trust_plan",
                                        decision_date=date(2027, 2, 1))
    assert after["rules"]["资产管理信托管理办法"]["in_force"] is True
    assert after["max_investors"] == 200


# ==================== 6. 提醒 ≠ 拦截 ====================

def test_threshold_alert_does_not_replace_blocking(tmp_path):
    qi = checker(tmp_path)
    assert qi.qi_threshold_check(IND_OK, "private_fund").ok is True
    degraded = dict(IND_OK, financial_assets_wan=80, avg_annual_income_wan_3y=10)
    alert = qi.qi_threshold_check(degraded, "private_fund")
    assert alert.ok is False and alert.code == "qi_threshold_breach"
    assert "提醒不等于拦截" in alert.message
    with pytest.raises(QualifiedInvestorRejected):
        qi.check_action("additional_subscribe", degraded,
                        product_type="private_fund", amount_wan=150)


# ==================== 7. 审计留痕 ====================

def test_audit_log_written_for_pass_and_reject(tmp_path):
    qi = checker(tmp_path)
    qi.check_action("subscribe", IND_OK, product_type="private_fund", amount_wan=150)
    with pytest.raises(QualifiedInvestorRejected):
        qi.check_action("subscribe", IND_LOW, product_type="private_fund", amount_wan=150)
    rows = qi.audit_trail()
    assert len(rows) >= 2
    assert any(r["ok"] is True for r in rows)
    assert any(r["ok"] is False and r["reasons"] for r in rows)
    for row in rows:
        assert row["audit_id"] and row["checked_at"] and row["action"]
        assert "profile_digest" in row and "thresholds" in row
        assert row["legal_basis"] == "证监会令第105号"


def test_audit_failure_fails_closed(tmp_path):
    blocked = tmp_path / "qi_audit.jsonl"
    qi = QIChecker(audit_log_path=blocked)
    qi.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    qi.audit_log_path.mkdir()                  # 目录占位 → 写入必然失败
    with pytest.raises(Exception) as info:
        qi.check_action("subscribe", IND_OK, product_type="private_fund", amount_wan=150)
    assert "审计留痕失败" in str(info.value)
