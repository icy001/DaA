# -*- coding: utf-8 -*-
"""G2/G3：三层净值与披露滞后验收（tests/test_nav_layers.py）。

  1) 三层口径 product_gross / product_net / investor_net 必须同时存在且满足
     gross >= net >= investor（上涨行情），对外披露固定 investor_net；
  2) carry 是 per-investor：不同申购时点 → 不同高水位 → 不同计提，
     业绩报酬明细必须能与投资者层净值对账；
  3) 决策日必须 >= 净值日 + disclosure_lag_days，违反直接抛 DisclosureLagError；
  4) 净值序列禁用 K 线类指标（to_kline / nav_only_markets）；
  5) 申购/追加/转让/变换持有人必须过合格投资者动作闸门（G1 联动）。
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from core.qualified_investor import QIChecker, QualifiedInvestorRejected
from nav_backtest.nav_backtester import (DisclosureLagError, NavAsKlineError,
                                         NavBacktester)

IND_OK = {"investor_type": "individual", "financial_assets_wan": 350,
          "avg_annual_income_wan_3y": 60, "invest_years": 3}
IND_LOW = {"investor_type": "individual", "financial_assets_wan": 50,
           "avg_annual_income_wan_3y": 10, "invest_years": 1}


def build_engine(periods: int = 60, growth: float = 1.004) -> NavBacktester:
    idx = pd.date_range("2025-01-03", periods=periods, freq="W-FRI")
    nav = pd.Series([growth ** i for i in range(periods)], index=idx)
    engine = NavBacktester("private_fund")
    engine.set_nav(nav)
    return engine


def run_with_two_investors() -> tuple:
    engine = build_engine()
    idx = engine._gross.index
    engine.subscribe("A", idx[0], 1_000_000)
    engine.subscribe("B", idx[30], 1_000_000)
    return engine, engine.run()


# ==================== 1. 三层净值 ====================

def test_three_layers_exist_and_ordered():
    _, result = run_with_two_investors()
    frame = result.layers.frame()
    assert list(frame.columns) == ["product_gross", "product_net", "investor_net"]
    last = frame.iloc[-1]
    assert last["product_gross"] > last["product_net"] > last["investor_net"]
    # 对外披露固定 investor_net
    view = result.disclosure(result.layers.product_gross.index[-1] + timedelta(days=2))
    assert view["layer"] == config.NAV_PRODUCT_CONFIG["disclosure_layer"] == "investor_net"
    assert abs(view["series"].iloc[-1] - last["investor_net"]) < 1e-9


def test_performance_fee_is_per_investor_and_reconciled():
    _, result = run_with_two_investors()
    ledger = result.performance_fees
    assert len(ledger) > 0
    assert set(ledger["investor_id"]) == {"A", "B"}
    # 不同申购时点 → 高水位不同 → 计提不同
    carry = ledger.groupby("investor_id")["fee"].sum()
    assert carry["A"] > carry["B"] > 0
    recon = result.reconcile()
    assert recon["ok"] is True, recon
    assert recon["diff"] < 1e-6
    assert abs(recon["performance_fee_ledger"] -
               recon["performance_fee_booked"]) < 1e-6
    # 业绩报酬明细必须能列出来（披露对账要求）
    assert {"date", "investor_id", "fee", "hwm", "nav"}.issubset(ledger.columns)


def test_fee_breakdown_five_categories():
    engine, result = run_with_two_investors()
    idx = engine._gross.index
    engine.redeem("A", idx[-1], units=1000)
    fee = result.fee_breakdown
    for key in ("subscription", "redemption", "management", "performance", "custodian"):
        assert key in fee
        assert fee[key] >= 0
    assert fee["subscription"] > 0 and fee["management"] > 0
    assert fee["custodian"] > 0 and fee["performance"] > 0


# ==================== 2. G3 披露滞后 ====================

def test_decision_before_disclosure_raises():
    engine = build_engine()
    last = engine._gross.index[-1]
    decision = last + timedelta(days=1)          # 滞后 2 天，第 1 天不可用
    with pytest.raises(DisclosureLagError):
        engine.assert_decision_after_disclosure(decision, nav_date=last)
    # 满 2 天后可用
    assert engine.assert_decision_after_disclosure(
        last + timedelta(days=2), nav_date=last) == (last + timedelta(days=2)).date()


def test_latest_disclosed_respects_lag():
    engine = build_engine()
    idx = engine._gross.index
    asof = engine.latest_disclosed(idx[10] + timedelta(days=1))
    assert asof <= (idx[10] + timedelta(days=1) - timedelta(days=2)).date()
    assert asof < idx[10].date()


def test_disclosure_view_marks_data_asof():
    engine, result = run_with_two_investors()
    decision = engine._gross.index[-1] + timedelta(days=3)
    view = result.disclosure(decision)
    asof = date.fromisoformat(view["data_asof_date"])
    assert decision.date() >= asof + timedelta(days=2)
    assert view["disclosure_frequency"] == "weekly"
    assert view["disclosure_lag_days"] == 2


def test_nav_cannot_be_used_as_kline():
    engine = build_engine()
    with pytest.raises(NavAsKlineError):
        engine.to_kline()
    with pytest.raises(NavAsKlineError):
        engine.assert_not_kline("private_fund")
    engine.assert_not_kline("cn_stock")          # 股票市场不受净值禁令影响


# ==================== 3. 与合格投资者闸门联动 ====================

def test_subscribe_goes_through_qi_gate(tmp_path):
    engine = build_engine()
    qi = QIChecker(audit_log_path=tmp_path / "qi.jsonl")
    idx = engine._gross.index
    with pytest.raises(QualifiedInvestorRejected):
        engine.subscribe("X", idx[0], 1_000_000, qi_checker=qi,
                         profile=IND_LOW, amount_wan=100)
    assert qi.audit_trail()[-1]["ok"] is False

    engine.subscribe("A", idx[0], 1_000_000, qi_checker=qi,
                     profile=IND_OK, amount_wan=100)
    # 资产缩水后追加申购必须被拦（不复用首次通过结论）
    with pytest.raises(QualifiedInvestorRejected):
        engine.additional_subscribe("A", idx[10], 500_000, qi_checker=qi,
                                    profile=IND_LOW, amount_wan=50)


def test_transfer_and_nominee_change_require_qi_check(tmp_path):
    engine = build_engine()
    qi = QIChecker(audit_log_path=tmp_path / "qi.jsonl")
    idx = engine._gross.index
    engine.subscribe("A", idx[0], 1_000_000)
    with pytest.raises(QualifiedInvestorRejected):
        engine.transfer("A", "B", idx[5], 1000, qi_checker=qi,
                        profile=IND_LOW, product_type="private_fund")
    with pytest.raises(QualifiedInvestorRejected):
        engine.nominee_change("A", idx[5], qi_checker=qi, profile=IND_LOW,
                              product_type="private_fund", new_holder="C")
