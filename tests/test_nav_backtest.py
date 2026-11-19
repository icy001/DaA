# -*- coding: utf-8 -*-
"""test_nav_backtest.py —— 第 10 步 10.3 净值型回测。

三条硬约束：
  G2 三层净值 product_gross → product_net → investor_net，carry per-investor，
     对外披露固定 investor_net；
  G3 decision_date >= nav_date + disclosure_lag_days，违反抛 DisclosureLagError，
     净值序列禁用 K 线；
  10.3 开放日申赎 + 锁定期 + 赎回款 T+N 到账。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from nav_backtest.fof import FOFBacktester
from nav_backtest.nav_backtester import (DisclosureLagError, NavAsKlineError,
                                         NavBacktester)

WEEKLY = pd.date_range("2023-01-06", periods=160, freq="W-FRI")


def rising_nav(step: float = 0.004, dates=None) -> pd.Series:
    dates = dates if dates is not None else WEEKLY
    return pd.Series([1.0 * (1.0 + step) ** i for i in range(len(dates))],
                     index=dates, name="nav")


def build_engine(product_type: str = "private_fund", two_investors: bool = True):
    engine = NavBacktester(product_type=product_type)
    engine.set_nav(rising_nav())
    engine.subscribe("A", WEEKLY[0], 1_000_000.0)
    if two_investors:
        engine.subscribe("B", WEEKLY[40], 500_000.0)
    return engine


# ==================== G2：三层净值 ====================

def test_config_declares_three_layers():
    cfg = config.NAV_PRODUCT_CONFIG
    assert cfg["nav_layers"] == ["product_gross", "product_net", "investor_net"]
    assert cfg["disclosure_layer"] == "investor_net"
    assert cfg["carry_is_per_investor"] is True


def test_layers_are_ordered_and_distinct():
    result = build_engine().run()
    gross = result.layers.product_gross.iloc[-1]
    net = result.layers.product_net.iloc[-1]
    investor = result.layers.investor_net.iloc[-1]
    assert gross > net > investor
    # 毛净值就是原始输入
    assert gross == pytest.approx(rising_nav().iloc[-1])


def test_carry_is_per_investor():
    result = build_engine().run()
    ledger = result.performance_fees
    assert set(ledger["investor_id"]) >= {"A", "B"}
    first_a = ledger[ledger["investor_id"] == "A"]["date"].min()
    first_b = ledger[ledger["investor_id"] == "B"]["date"].min()
    # 不同申购时点 → 不同高水位 → 不同计提起点
    assert first_a < first_b
    booked = result.fee_breakdown["performance"]
    accrued = float(ledger[ledger["kind"] == "accrued"]["fee"].sum())
    assert accrued == pytest.approx(booked, rel=1e-9)


def test_reconcile_performance_fee_with_investor_nav():
    result = build_engine().run()
    check = result.reconcile()
    assert check["ok"] is True
    assert check["diff"] < 1e-6


def test_disclosure_uses_investor_net_only():
    result = build_engine().run()
    decision = WEEKLY[-1] + pd.Timedelta(days=2)
    view = result.disclosure(decision)
    assert view["layer"] == "investor_net"
    assert view["data_asof_date"] == WEEKLY[-1].date().isoformat()
    assert view["series"].iloc[-1] == pytest.approx(
        result.layers.investor_net.iloc[-1])
    assert view["disclosure_lag_days"] == 2


# ==================== G3：披露滞后闸门 ====================

def test_decision_before_disclosure_raises():
    engine = build_engine()
    last = WEEKLY[-1]
    # 指定净值日时，决策日必须 >= 净值日 + 滞后 2 天
    with pytest.raises(DisclosureLagError):
        engine.assert_decision_after_disclosure(last + pd.Timedelta(days=1), nav_date=last)
    assert engine.assert_decision_after_disclosure(
        last + pd.Timedelta(days=2), nav_date=last) == (last + pd.Timedelta(days=2)).date()


def test_latest_disclosed_excludes_unpublished_nav():
    engine = build_engine()
    assert engine.latest_disclosed(WEEKLY[-1] + pd.Timedelta(days=1)) == \
        WEEKLY[-2].date()
    assert engine.latest_disclosed(WEEKLY[-1] + pd.Timedelta(days=2)) == \
        WEEKLY[-1].date()


def test_enforce_flag_can_be_disabled_explicitly():
    cfg = dict(config.NAV_PRODUCT_CONFIG)
    cfg["enforce_decision_after_disclosure"] = False
    engine = NavBacktester(product_config=cfg)
    engine.set_nav(rising_nav())
    out = engine.assert_decision_after_disclosure(WEEKLY[-1] + pd.Timedelta(days=1))
    assert out == (WEEKLY[-1] + pd.Timedelta(days=1)).date()


def test_nav_series_forbidden_as_kline():
    engine = build_engine()
    with pytest.raises(NavAsKlineError):
        engine.to_kline()
    with pytest.raises(NavAsKlineError):
        engine.assert_not_kline("private_fund")
    # 非净值型市场不触发（仅校验净值产品）
    engine.assert_not_kline("cn_stock")


# ==================== 10.3：开放日 / 锁定期 / T+N ====================

def test_only_open_day_allows_subscribe():
    engine = NavBacktester(product_type="private_fund")
    engine.set_nav(rising_nav())
    assert engine.is_open_day(WEEKLY[0]) is True
    assert engine.is_open_day(WEEKLY[0] + pd.Timedelta(days=1)) is False
    with pytest.raises(ValueError) as info:
        engine.subscribe("A", WEEKLY[0] + pd.Timedelta(days=1), 100_000.0)
    assert "非开放日" in str(info.value)


def test_lockup_blocks_early_redemption():
    engine = build_engine(two_investors=False)
    with pytest.raises(ValueError) as info:
        engine.redeem("A", WEEKLY[5], units=100.0)
    assert "锁定期" in str(info.value)
    record = engine.redeem("A", WEEKLY[-1], units=100.0, lockup_days=0)
    assert record["holding_days"] > 180


def test_redemption_settles_after_t_plus_n():
    engine = build_engine(two_investors=False)
    engine.run()
    on = WEEKLY[-1]
    record = engine.redeem("A", on, units=100.0)
    assert record["settlement_days"] == config.NAV_PRODUCT_CONFIG[
        "redemption_settlement_days"]["private_fund"] == 3
    assert record["settlement_date"] == on + pd.Timedelta(days=3)
    # T+N 到账前只挂在途，不得当可用资金
    assert engine.pending_settlement(on) == pytest.approx(record["net"])
    assert engine.settled_amount(on) == 0.0
    assert engine.settled_amount(on + pd.Timedelta(days=3)) == pytest.approx(record["net"])
    assert engine.pending_settlement(on + pd.Timedelta(days=3)) == 0.0


# ==================== FOF：多产品组合 ====================

def make_fof(strategy=None, rebalance: str = "monthly"):
    fof = FOFBacktester(product_type="private_fund", rebalance=rebalance)
    navs = {
        "P1": rising_nav(0.004).to_frame("nav").rename_axis("date").reset_index(),
        "P2": rising_nav(0.002).to_frame("nav").rename_axis("date").reset_index(),
    }
    fof.set_navs(navs)
    return fof, fof.run(strategy=strategy)


def test_fof_executes_on_next_nav_day():
    _, res = make_fof()
    weights = res.weights_history
    assert len(weights) > 0
    for _, row in weights.iterrows():
        assert pd.Timestamp(row["execute_date"]) > pd.Timestamp(row["decision_date"])
    trades = res.trades
    assert (trades["action"] == "buy").any()


def test_fof_three_layers_ordered():
    _, res = make_fof()
    gross = res.layers.product_gross.iloc[-1]
    net = res.layers.product_net.iloc[-1]
    investor = res.layers.investor_net.iloc[-1]
    assert gross > net >= investor
    assert res.fee_breakdown["management"] > 0
    assert res.fee_breakdown["performance"] > 0


def test_fof_disclosure_lag_and_kline_ban():
    fof, res = make_fof()
    last = max(res.layers.investor_net.index)
    view = res.disclosure(last + pd.Timedelta(days=2))
    assert view["layer"] == "investor_net"
    assert pd.Timestamp(view["data_asof_date"]) <= last
    with pytest.raises(DisclosureLagError):
        fof.assert_decision_after_disclosure(last)
    with pytest.raises(NavAsKlineError):
        fof.to_kline()


def test_fof_lockup_blocks_sell_within_lock_period():
    calls = {"n": 0}

    def switch_after_first(_nav_frame, asof=None, **_ignored):
        calls["n"] += 1
        return {"P2": 1.0} if calls["n"] == 1 else {"P1": 1.0}

    _, res = make_fof(strategy=switch_after_first)
    trades = res.trades
    blocked = trades[trades.get("action") == "sell_blocked_lockup"]
    assert len(blocked) > 0
    # 锁定期内不得出现真实卖出
    sells = trades[trades.get("action") == "sell"]
    for _, row in sells.iterrows():
        assert row["holding_days"] >= 180
