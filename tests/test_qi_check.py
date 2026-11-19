# -*- coding: utf-8 -*-
"""test_qi_check.py —— 第 10 步 10.1 合格投资者门槛校验。

覆盖 10.0 四条硬断言中的三条：
  ① 每个动作都校验（subscribe / transfer / additional_subscribe / nominee_change）；
  ② 穿透核查（非法人载体必须给最终投资者并合并人数）；
  ③ fail-closed（不过即抛错，不是 (bool, reason)）+ 每次校验审计留痕。
另验证三套门槛不混用、2026 规则口径、新三板/OTC 门槛、提醒≠拦截。
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

ACTIONS = ["subscribe", "transfer", "additional_subscribe", "nominee_change"]
IND_OK = {"investor_type": "individual", "financial_assets_wan": 350,
          "avg_annual_income_wan_3y": 20, "invest_years": 3}
IND_LOW = {"investor_type": "individual", "financial_assets_wan": 100,
           "avg_annual_income_wan_3y": 10, "invest_years": 1}
INST_OK = {"investor_type": "institution", "net_assets_wan": 1200}


def checker(tmp_path) -> QIChecker:
    return QIChecker(audit_log_path=tmp_path / "qi.jsonl")


# ==================== 门槛配置 ====================

def test_thresholds_are_config_driven():
    rules = config.QUALIFIED_INVESTOR_RULES
    assert rules["private_fund"]["legal_basis"] == "证监会令第105号"
    assert rules["private_fund"]["individual"]["financial_assets_wan"] == 300
    assert rules["private_fund"]["min_per_product_wan"] == 100
    assert rules["amr_product"]["legal_basis"] == "银发〔2018〕106号"
    assert rules["amr_product"]["min_per_product_wan"] == {
        "fixed_income": 30, "mixed": 40, "equity": 100, "derivatives": 100}
    assert rules["trust_plan"]["legal_basis"] == "银监会令2007年第3号"
    assert rules["trust_plan"]["max_natural_persons"] == 50
    assert rules["check_at_every_action"] is True
    assert rules["on_fail"] == "reject"


def test_private_fund_independent_of_amr(tmp_path):
    qi = checker(tmp_path)
    # 350 万金融资产：满足私募 300 万，但不满足资管家庭金融资产 500 万
    assert qi.check_current_threshold(IND_OK).ok is True
    assert qi.check_amr_threshold(IND_OK, "equity").ok is False
    # 机构门槛也不同：资管/私募均 1000 万净资产，信托未配置机构门槛必须拒绝
    assert qi.check_current_threshold(INST_OK).ok is True
    verdict = qi.check_trust_threshold(INST_OK)
    assert verdict.ok is False and "trust_institution_unconfigured" in verdict.codes


@pytest.mark.parametrize("product_type,profile", [
    ("private_fund", IND_LOW), ("amr_product", IND_LOW),
    ("trust_plan", dict(IND_LOW, financial_assets_wan=50,
                        avg_annual_income_wan_3y=5, couple_annual_income_wan_3y=8)),
])
def test_amr_start_amount_tiers(tmp_path, product_type, profile):
    qi = checker(tmp_path)
    with pytest.raises(QualifiedInvestorRejected):
        qi.check_action("subscribe", profile, product_type=product_type, amount_wan=150)


def test_amr_amount_tiers_are_separate_from_private_fund(tmp_path):
    qi = checker(tmp_path)
    amr_ok = dict(IND_OK, financial_assets_wan=600)     # 资管要求家庭金融资产 ≥500 万
    with pytest.raises(QualifiedInvestorRejected) as info:
        qi.check_action("subscribe", amr_ok, product_type="amr_product", amount_wan=35)
    assert "min_amount" in info.value.verdict.codes      # 混合类起投 40 万
    assert qi.check_action("subscribe", amr_ok, product_type="amr_product",
                           amount_wan=50).ok is True
    assert qi.check_amr_threshold(amr_ok, "fixed_income").ok is True
    assert qi.check_amr_threshold(amr_ok, "equity").ok is True


# ==================== 硬断言 ①：每个动作都校验 ====================

@pytest.mark.parametrize("action", ACTIONS)
def test_every_action_is_rechecked(tmp_path, action):
    qi = checker(tmp_path)
    with pytest.raises(QualifiedInvestorRejected) as info:
        qi.check_action(action, IND_LOW, product_type="private_fund", amount_wan=150)
    assert info.value.verdict.action == action
    assert info.value.verdict.ok is False


def test_first_pass_does_not_grant_later_actions(tmp_path):
    """首次申购通过 ≠ 后续追加申购通过：资产缩水后同一投资者追加被拒。"""
    qi = checker(tmp_path)
    assert qi.check_action("subscribe", IND_OK, product_type="private_fund",
                           amount_wan=150).ok is True
    degraded = dict(IND_OK, financial_assets_wan=120, avg_annual_income_wan_3y=10)
    with pytest.raises(QualifiedInvestorRejected):
        qi.check_action("additional_subscribe", degraded,
                        product_type="private_fund", amount_wan=150)


def test_unknown_action_rejected(tmp_path):
    qi = checker(tmp_path)
    with pytest.raises(QualifiedInvestorRejected) as info:
        qi.check_action("redeem_without_check", IND_OK, product_type="private_fund")
    assert "action_not_registered" in info.value.verdict.codes


# ==================== 硬断言 ②：穿透核查 ====================

def test_look_through_required_for_vehicle(tmp_path):
    qi = checker(tmp_path)
    vehicle = {"name": "某某合伙", "vehicle_type": "partnership"}
    with pytest.raises(QualifiedInvestorRejected) as info:
        qi.check_action("subscribe", vehicle, product_type="private_fund", amount_wan=150)
    assert "look_through_missing" in info.value.verdict.codes


def test_look_through_merges_count_and_checks_each(tmp_path):
    qi = checker(tmp_path)
    vehicle = {"name": "某某契约型", "vehicle_type": "contract",
               "ultimate_investors": [dict(IND_OK, investor_id="U1"),
                                      dict(IND_OK, investor_id="U2")]}
    verdict = qi.check_action("subscribe", vehicle, product_type="private_fund",
                              amount_wan=150)
    assert verdict.ok is True and verdict.investor_count == 2
    bad = {"vehicle_type": "partnership",
           "ultimate_investors": [dict(IND_OK, investor_id="U1"),
                                  dict(IND_LOW, investor_id="U2")]}
    with pytest.raises(QualifiedInvestorRejected) as info:
        qi.check_action("subscribe", bad, product_type="private_fund", amount_wan=150)
    assert "look_through_ineligible" in info.value.verdict.codes


@pytest.mark.parametrize("flag", ["pooled", "is_nominee", "split_units", "borrowed_name"])
def test_pooling_nominee_split_borrow_forbidden(tmp_path, flag):
    qi = checker(tmp_path)
    profile = dict(IND_OK, **{flag: True})
    with pytest.raises(QualifiedInvestorRejected) as info:
        qi.check_action("subscribe", profile, product_type="private_fund", amount_wan=150)
    assert any(code in info.value.verdict.codes for code in
               ("pooling_forbidden", "nominee_forbidden", "split_forbidden",
                "non_own_funds_forbidden"))


def test_non_own_funds_forbidden(tmp_path):
    qi = checker(tmp_path)
    with pytest.raises(QualifiedInvestorRejected) as info:
        qi.check_action("subscribe", dict(IND_OK, funding_source="third_party"),
                        product_type="private_fund", amount_wan=150)
    assert "non_own_funds_forbidden" in info.value.verdict.codes


# ==================== 硬断言 ③：fail-closed + 审计留痕 ====================

def test_fail_closed_raises_and_audits(tmp_path):
    audit = tmp_path / "qi.jsonl"
    qi = QIChecker(audit_log_path=audit)
    with pytest.raises(QualifiedInvestorRejected):
        qi.assert_action("nominee_change", IND_LOW, product_type="private_fund")
    lines = [json.loads(x) for x in audit.read_text(encoding="utf-8").splitlines() if x]
    assert lines and lines[-1]["ok"] is False
    assert lines[-1]["action"] == "nominee_change"
    assert lines[-1]["legal_basis"] == "证监会令第105号"
    # 通过的动作同样留痕
    qi.check_action("subscribe", IND_OK, product_type="private_fund", amount_wan=150)
    lines = [json.loads(x) for x in audit.read_text(encoding="utf-8").splitlines() if x]
    assert lines[-1]["ok"] is True


def test_audit_write_failure_is_fail_closed(tmp_path):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    qi = QIChecker(audit_log_path=blocker / "qi.jsonl")
    with pytest.raises(Exception) as info:
        qi.check_action("subscribe", IND_OK, product_type="private_fund", amount_wan=150)
    assert "审计留痕失败" in str(info.value)


# ==================== 其他门槛 ====================

def test_neeq_threshold(tmp_path):
    qi = checker(tmp_path)
    assert qi.check_neeq_threshold(IND_OK, "innovation").ok is True
    assert qi.check_neeq_threshold(dict(IND_OK, financial_assets_wan=80),
                                   "innovation").ok is False
    assert qi.check_neeq_threshold(dict(IND_OK, financial_assets_wan=150),
                                   "base").ok is False
    base_ok = dict(IND_OK, financial_assets_wan=250)
    assert qi.check_neeq_threshold(base_ok, "base").ok is True


def test_otc_individual_forbidden(tmp_path):
    qi = checker(tmp_path)
    with pytest.raises(OTCForbiddenError):
        qi.check_otc_institutional_threshold(IND_OK)
    with pytest.raises(QualifiedInvestorRejected):
        qi.check_otc_institutional_threshold({"investor_type": "institution",
                                             "net_assets_wan": 1000,
                                             "invest_years": 3})


def test_2026_rules_status_wording(tmp_path):
    qi = checker(tmp_path)
    out = qi.check_proposed_2026_rule(IND_OK, product_type="trust_plan",
                                      decision_date=date(2026, 11, 12))
    trust = out["rules"]["资产管理信托管理办法"]
    assert trust["status"] == "已发布待施行"
    assert trust["issue_date"] == "2026-10-30" and trust["effective_date"] == "2027-01-01"
    assert trust["in_force"] is False
    assert out["rules"]["私募投资基金监督管理办法"]["status"] == "征求意见稿"
    text = json.dumps(out, ensure_ascii=False)
    assert "尚未生效" not in text
    after = qi.check_proposed_2026_rule(IND_OK, product_type="trust_plan",
                                        decision_date=date(2027, 2, 1))
    assert after["rules"]["资产管理信托管理办法"]["in_force"] is True
    assert after["max_investors"] == 200


# ==================== 提醒 ≠ 拦截 ====================

def test_alert_is_not_blocking_but_next_action_is(tmp_path):
    qi = checker(tmp_path)
    assert qi.qi_threshold_check(IND_OK, "private_fund").ok is True
    degraded = dict(IND_OK, financial_assets_wan=100, avg_annual_income_wan_3y=10)
    alert = qi.qi_threshold_check(degraded, "private_fund")
    assert alert.ok is False and "提醒不等于拦截" in alert.message
    # 提醒本身不抛错，但后续申购必须被拦
    with pytest.raises(QualifiedInvestorRejected):
        qi.check_action("subscribe", degraded, product_type="private_fund", amount_wan=150)
