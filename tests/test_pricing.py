# -*- coding: utf-8 -*-
"""test_pricing.py —— 第 10 步 10.4 场外衍生品定价（仅模拟，个人禁止实盘）。

覆盖：BS / MC / 二叉树美式、雪球敲入敲出蒙特卡洛、TRS 保证金与强平、
情景分析与 VaR，以及「本包不提供任何下单通道」的红线断言。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import derivatives_pricing as dp
from derivatives_pricing.pricing import (binomial_tree_american, black_scholes,
                                         monte_carlo_european)
from derivatives_pricing.scenario import (DEFAULT_SCENARIOS, scenario_analysis,
                                          value_at_risk)
from derivatives_pricing.snowball import snowball_pricing
from derivatives_pricing.trs import trs_pnl_simulation

S, K, T, R, SIGMA = 100.0, 100.0, 1.0, 0.05, 0.2


# ==================== 红线：个人禁止实盘 ====================

def test_no_order_channel_red_line():
    assert dp.LIVE_TRADING_FORBIDDEN is True
    assert dp.ORDER_CHANNELS == ()
    dp.assert_no_order_channel()
    for name in ("place_order", "submit_order", "send_order", "place", "order"):
        assert not hasattr(dp, name)


def test_red_warning_is_visible(capsys):
    text = dp.print_red_warning()
    assert "个人投资者禁止" in text and "不提供任何实盘下单功能" in text
    assert "警告" in capsys.readouterr().out


# ==================== BS / MC / 二叉树 ====================

def test_black_scholes_reference_and_parity():
    call = black_scholes(S, K, T, R, SIGMA, "call")
    put = black_scholes(S, K, T, R, SIGMA, "put")
    assert call["price"] == pytest.approx(10.4506, abs=1e-3)
    assert put["price"] == pytest.approx(5.5735, abs=1e-3)
    assert call["price"] - put["price"] == pytest.approx(S - K * np.exp(-R * T), abs=1e-8)
    assert 0.0 < call["delta"] < 1.0
    assert call["gamma"] > 0 and call["vega"] > 0 and call["theta"] < 0
    assert call["d2"] == pytest.approx(call["d1"] - SIGMA * np.sqrt(T))


def test_black_scholes_intrinsic_at_expiry_and_bad_type():
    assert black_scholes(S, K, 0.0, R, SIGMA, "call")["price"] == 0.0
    assert black_scholes(S + 5, K, 0.0, R, SIGMA, "put")["price"] == 0.0
    with pytest.raises(ValueError):
        black_scholes(S, K, T, R, SIGMA, "straddle")


def test_monte_carlo_matches_bs():
    bs = black_scholes(S, K, T, R, SIGMA, "call")["price"]
    mc = monte_carlo_european(S, K, T, R, SIGMA, n_sims=200_000)
    assert mc["price"] == pytest.approx(bs, abs=0.5)
    assert mc["stderr"] > 0 and mc["n_sims"] == 200_000
    put_bs = black_scholes(S, K, T, R, SIGMA, "put")["price"]
    put_mc = monte_carlo_european(S, K, T, R, SIGMA, n_sims=200_000, option_type="put")
    assert put_mc["price"] == pytest.approx(put_bs, abs=0.5)


def test_american_put_not_below_european():
    european = black_scholes(S, K, T, R, SIGMA, "put")["price"]
    american = binomial_tree_american(S, K, T, R, SIGMA, steps=200, option_type="put")
    assert american["price"] >= european - 1e-6
    assert american["price"] < K


# ==================== 雪球 ====================

def snowball(**kwargs):
    params = dict(S0=100.0, ko_barrier=1.03, ki_barrier=0.75, coupon=0.15,
                  ko_observe_dates=list(range(3, 25, 3)),
                  ki_observe_dates=list(range(1, 505)),
                  r=0.02, sigma=0.2, n_sims=4_000, tenor_months=24,
                  barrier_mode="ratio", notional=1.0)
    params.update(kwargs)
    return snowball_pricing(**params)


def test_snowball_probabilities_cover_all_paths():
    out = snowball()
    for key in ("p_knock_out", "p_knock_in", "p_ki_no_ko", "p_no_ki_no_ko"):
        assert 0.0 <= out[key] <= 1.0
    total = out["p_knock_out"] + out["p_ki_no_ko"] + out["p_no_ki_no_ko"]
    assert total == pytest.approx(1.0, abs=1e-9)
    assert out["price"] > 0
    assert out["price_per_notional"] == pytest.approx(out["price"])
    assert set(out["pnl_quantiles"]) >= {"1", "5", "50", "95", "99"}


def test_snowball_ratio_and_price_barriers_equivalent():
    ratio = snowball(barrier_mode="ratio")
    price = snowball(barrier_mode="price", ko_barrier=103.0, ki_barrier=75.0)
    assert price["price"] == pytest.approx(ratio["price"], rel=1e-12)
    assert price["p_knock_out"] == ratio["p_knock_out"]


# ==================== TRS / 情景 / VaR ====================

def test_trs_margin_and_liquidation():
    out = trs_pnl_simulation(underlying_return=0.10, notional=1_000_000.0,
                             margin_rate=0.20, financing_rate=0.05, term_days=90)
    assert out["margin"] == pytest.approx(200_000.0)
    assert out["leverage"] == pytest.approx(5.0)
    cost = 1_000_000.0 * 0.05 * 90 / 365.0
    assert out["financing_cost"] == pytest.approx(cost)
    assert out["pnl"] == pytest.approx(100_000.0 - cost)
    assert out["liquidated"] is False
    crash = trs_pnl_simulation(underlying_return=-0.30, notional=1_000_000.0,
                               margin_rate=0.20, financing_rate=0.05, term_days=90)
    assert crash["liquidated"] is True


def test_scenario_analysis_and_var():
    rows = scenario_analysis(DEFAULT_SCENARIOS, lambda move: 1_000_000.0 * move)
    assert rows["大涨"]["pnl"] == pytest.approx(200_000.0)
    assert rows["黑天鹅"]["pnl"] == pytest.approx(-400_000.0)
    assert len(rows) == len(DEFAULT_SCENARIOS)
    var = value_at_risk([-0.20, -0.10, 0.0, 0.10, 0.20], confidence=0.95)
    assert 0.0 < var["var"] <= 0.20
    assert var["expected_shortfall"] >= var["var"]
    assert var["n_samples"] == 5
    with pytest.raises(ValueError):
        value_at_risk([])
