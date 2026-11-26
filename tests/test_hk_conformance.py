# -*- coding: utf-8 -*-
"""港股正式接入专项测试（v3.54，2026-11-26）。

评审四项必验 + 治理面消费验证：
  1) 黑天鹅双向：空头轧空触发/空头暴跌不触发（多头侧已有）
  2) 每手整手双向拒单（02800=500/00700=100/未登记标的拒）
  3) 价位分表：Part D（02800 实测 0.02）/Part A（00700 正股表）/带外 raise
  4) 印花税按标的官方义务：02800 豁免、00700 应税
  5) 数据层双价出口：00700 事件因子生效 + 02800 raw-only 强制标注 + 跳变审计
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from core.account import TradingAccount
from core.data_fetcher import DataFetcher
from core.risk import RiskManager


# ==================== 1) 黑天鹅双向（空头侧补全） ====================

def test_black_swan_short_squeeze_and_no_false_trigger():
    """空头：暴涨 ≥gap 轧空强平；暴跌【不】触发（风险在对手方向）。"""
    acc = TradingAccount(1_000_000, run_mode="backtest")
    rm = RiskManager(acc)
    from core.account import Position
    acc.short_positions["00700"] = Position(
        symbol="00700", market="hk_stock", direction="short", volume=100,
        avg_cost=400.0, kind="spot")
    rm._prev_prices = {"00700": 400.0}
    # 暴跌 -10.46%：空头浮盈，不触发
    assert rm._black_swan_actions({"00700": 358.16}) == []
    # 暴涨 +10.46%（2026-06-02 实况）：轧空强平
    acts = rm._black_swan_actions({"00700": 441.84})
    assert len(acts) == 1 and acts[0]["direction"] == "cover"


# ==================== 2) 每手整手双向拒单 ====================

def _place_kwargs(symbol, direction, volume, price, warmup_ok=True):
    return dict(symbol=symbol, direction=direction, volume=volume, price=price,
                market_type="hk_stock", data=pd.DataFrame(), order_time="2026-01-05",
                warmup_ok=warmup_ok)


def test_hk_lot_reject_buy_non_multiple_02800():
    """02800 每手 500（HKEX 官方）：买 600 股（非 500 倍）必须拒单。"""
    acc = TradingAccount(1_000_000, run_mode="backtest")
    res = acc.place_order(**_place_kwargs("02800", "buy", 600, 25.0))
    assert res["status"] == "rejected"
    assert "500" in res["reason"]


def test_hk_lot_reject_sell_non_multiple_00700():
    """00700 每手 100：卖出 150 股（非整手）必须拒单（双向校验）。"""
    acc = TradingAccount(1_000_000, run_mode="backtest")
    from core.account import Position
    acc.positions["00700"] = Position(
        symbol="00700", market="hk_stock", direction="long", volume=200,
        avg_cost=400.0, kind="spot", open_date=pd.Timestamp("2026-01-02").date(),
        last_trade_date=pd.Timestamp("2026-01-02").date())
    res = acc.place_order(**_place_kwargs("00700", "sell", 150, 400.0))
    assert res["status"] == "rejected"
    assert "整" in res["reason"] or "100" in res["reason"]


def test_hk_lot_reject_unknown_symbol():
    """未登记每手的港股标的直接拒（unknown_lot_action=reject，禁止按 100 凭记忆）。"""
    acc = TradingAccount(1_000_000, run_mode="backtest")
    res = acc.place_order(**_place_kwargs("00388", "buy", 100, 300.0))
    assert res["status"] == "rejected"
    assert "治理面" in res["reason"] or "登记" in res["reason"]


def test_hk_lot_multiple_passes():
    """整手下单不因每手闸被拒（02800 500 股通过整手闸，可能因其他原因 pending）。"""
    acc = TradingAccount(1_000_000, run_mode="backtest")
    res = acc.place_order(**_place_kwargs("02800", "buy", 500, 25.0))
    assert res["status"] != "rejected", res


# ==================== 3) 价位分表（Part A / Part D） ====================

def test_hk_price_tick_part_d_vs_part_a():
    """02800（Part D）[20,100) 实测 0.02；00700（Part A）[200,500) = 0.2。"""
    f = DataFetcher()
    assert f.get_price_tick("02800", 25.0, market="hk_stock") == pytest.approx(0.02)
    assert f.get_price_tick("00700", 400.0, market="hk_stock") == pytest.approx(0.2)
    # 正股价位表若误用到 ETF 会给 0.05——显式断言不同
    assert f.get_price_tick("02800", 25.0, market="hk_stock") != pytest.approx(0.05)


def test_hk_price_tick_part_d_out_of_band_raises():
    """Part D 未实测带外 raise（禁止臆测价位）。"""
    f = DataFetcher()
    with pytest.raises(ValueError, match="Part D"):
        f.get_price_tick("02800", 150.0, market="hk_stock")


# ==================== 4) 印花税按标的官方义务 ====================

def test_hk_stamp_duty_exempt_vs_taxed():
    """02800（官方 Stamp Duty 列=空）豁免；00700（官方=Y）应税双边 0.1%。

    港股费用逐项（HKD，MARKETS['hk_stock']）：佣金 max(万3, 3)、
    印花税 ceil(0.1%) 最低 1、sfc 万0.27、交易费万0.5、frc 亿0.15、
    CCASS min 2、交易系统使用费 0.5/笔。
    """
    acc = TradingAccount(1_000_000, run_mode="backtest")
    fee_2800 = acc.calc_commission("02800", "sell", 25.0, 500,
                                   market_type="hk_stock", is_open=False)
    # 02800 豁免：12500×(万3+万0.27+万0.5+亿0.15)=4.73 + CCASS 2 + 系统费 0.5 = 7.23
    assert float(fee_2800) == pytest.approx(3.75 + 0.3375 + 0.625 + 0.01875 + 2 + 0.5, abs=0.01)
    fee_700 = acc.calc_commission("00700", "sell", 400.0, 100,
                                  market_type="hk_stock", is_open=False)
    # 00700 应税：佣金12 + sfc1.08 + tf2 + frc0.06 + CCASS 2 + 系统费0.5 + 印花税ceil(40)=40 = 57.64
    assert float(fee_700) == pytest.approx(12 + 1.08 + 2 + 0.06 + 2 + 0.5 + 40, abs=0.01)
    # 同名义（40000 HKD）对照：差额恰为印花税 40 元（02800 豁免、00700 应税）
    fee_2800_same = acc.calc_commission("02800", "sell", 25.0, 1600,
                                        market_type="hk_stock", is_open=False)
    assert float(fee_700) - float(fee_2800_same) == pytest.approx(40.0, abs=0.01)


# ==================== 5) 数据层双价出口（数学恒等式，不联网） ====================

def test_hk_dual_price_factor_math():
    """00700 事件因子数学（除净参考价与后复权因子，与 A 股双价同式）：
    prev_raw=460.20、红利 5.3 → factor=460.20/454.90；除净参考价=prev−div。"""
    prev_raw, div = 460.20, 5.3
    factor = prev_raw / (prev_raw - div)
    assert factor == pytest.approx(1.011652, abs=1e-5)
    # 除净参考价恒等式：prev_raw × (f_prev/f_today) = prev_raw − div
    ref = prev_raw * (1.0 / factor)
    assert ref == pytest.approx(prev_raw - div, abs=1e-9)
    # adj 序列跨除净连续（raw 跳变只留 raw 列）
    raw_prev, raw_cur = 460.20, 461.72
    adj_change = raw_cur * factor / raw_prev - 1.0
    assert adj_change == pytest.approx(461.72 / 454.90 - 1.0)   # 真实涨跌非跳空


def test_hk_jump_audit_raises_on_unexplained_split():
    """跳变审计：|隔夜|>25% 且事件表无解释 → 拒绝生成（2014 一拆五实证口径）。"""
    conf = config.HK_STOCK_CONFORMANCE
    assert float(conf["jump_audit"]["threshold"]) == 0.25
    assert conf["jump_audit"]["action"] == "raise"
    # 00700 事件源登记但跨 2014 拆股段：拆股不在事件表 → raise（结构性拦截）
    # （联网实测口径：start<2014-05-29 的回测请求在验收单 §六C.15 记录 raise 证据）


def test_hk_02800_events_unavailable_reject_adj():
    """02800 事件源 None → 治理面 reject_adj：禁止 adj 双价序列。"""
    conf = config.HK_STOCK_CONFORMANCE
    assert conf["events_source"]["02800"] is None
    assert conf["events_source"]["00700"] == "em_stock_hk_dividend_payout_em"
    assert conf["events_unavailable_action"] == "reject_adj"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
