# -*- coding: utf-8 -*-
"""期货换月平旧开新专项测试（v3.53 评审七轮④）。

验收裁定：若只是拼接两条合约价、持仓跨换月不动，每轮换月的 P&L 都是假的。
要求：换月日产生平/开两笔成交，手续费与月差如实入账。

覆盖：
  1) 多头持仓换月日 → 平旧 @旧合约收盘 + 开新 @新合约收盘 两笔成交，
     月差如实体现在平旧 realized pnl 与开新成本中；
  2) 空头持仓换月 → cover 平旧 + short 开新；
  3) 无持仓 → 不产生成交；
  4) 缺旧合约平仓价 → warning 且不成交（禁止静默当作滚动成功）；
  5) build_dominant_series 的 roll 行携带 roll_exit_price / roll_prev_contract；
  6) RB 规格来自 config 治理面：per_lot 1 元/手、乘数 10。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from core.account import Position, TradingAccount
from core.backtester import Backtester
from core.data_fetcher import DataFetcher

RB_MULT = float(config.CN_FUTURES_VARIETY["RB"]["multiplier"])
RB_FEE_LOT = float(config.CN_FUTURES_VARIETY["RB"]["commission_per_lot_close"])


def _bare_bt() -> Backtester:
    """最小化引擎壳：仅 _handle_contract_rolls 依赖的 account/logger/roll_count。"""
    bt = Backtester.__new__(Backtester)
    bt.account = TradingAccount(1_000_000, run_mode="backtest")
    bt.logger = logging.getLogger("test_future_roll")
    bt.roll_count = 0
    return bt


def _long_pos(bt: Backtester, symbol: str = "RB0", avg: float = 3129.0,
              vol: float = 2.0) -> None:
    bt.account.positions[symbol] = Position(
        symbol=symbol, market="cn_future", direction="long", volume=vol,
        avg_cost=avg, kind="future", multiplier=RB_MULT, margin_rate=0.09,
        open_date=pd.Timestamp("2026-01-04").date(),
        last_trade_date=pd.Timestamp("2026-01-04").date())


def _short_pos(bt: Backtester, symbol: str = "RB0", avg: float = 3129.0,
               vol: float = 2.0) -> None:
    bt.account.short_positions[symbol] = Position(
        symbol=symbol, market="cn_future", direction="short", volume=vol,
        avg_cost=avg, kind="future", multiplier=RB_MULT, margin_rate=0.09,
        open_date=pd.Timestamp("2026-01-04").date(),
        last_trade_date=pd.Timestamp("2026-01-04").date())


def _roll_bar(entry: float = 3100.0, exit_px=None, prev="RB2510",
              cur="RB2601") -> dict:
    return {"roll": True, "raw_close": entry, "raw_open": entry,
            "roll_exit_price": exit_px if exit_px is not None else 3200.0,
            "roll_prev_contract": prev, "contract": cur,
            "settle": entry + 5.0, "close": entry}


def test_roll_long_two_fills_with_basis_and_fees():
    """多头换月：平/开两笔成交、月差入账、手续费两笔、成本切到新合约。"""
    bt = _bare_bt()
    _long_pos(bt, avg=3129.0, vol=2.0)
    bt._handle_contract_rolls(pd.Timestamp("2026-01-05"), {"RB0": _roll_bar()})
    trades = bt.account.trades
    assert len(trades) == 2, f"换月日必须平/开两笔成交，实得 {len(trades)}"
    t_close, t_open = trades[0], trades[1]
    # 平旧：旧合约当日实际收盘 3200（月差如实入账；引擎 realized 为净额口径
    # = 价差毛额 − 平仓手续费，手续费同时在 commission 字段单列）
    assert t_close["action"] == "close" and t_close["direction"] == "sell"
    assert float(t_close["price"]) == pytest.approx(3200.0)
    gross = (3200.0 - 3129.0) * 2.0 * RB_MULT
    assert float(t_close["pnl"]) == pytest.approx(gross - 2.0 * RB_FEE_LOT)
    assert float(t_close["commission"]) == pytest.approx(2.0 * RB_FEE_LOT)
    # 开新：新合约当日实际收盘 3100，成本切到新合约 raw 空间
    assert t_open["action"] == "open" and t_open["direction"] == "buy"
    assert float(t_open["price"]) == pytest.approx(3100.0)
    assert float(t_open["commission"]) == pytest.approx(2.0 * RB_FEE_LOT)
    pos = bt.account.positions["RB0"]
    assert float(pos.volume) == pytest.approx(2.0)
    assert float(pos.avg_cost) == pytest.approx(3100.0)
    assert bt.roll_count == 1


def test_roll_short_two_fills():
    """空头换月：cover 平旧 + short 开新，月差反向入账。"""
    bt = _bare_bt()
    _short_pos(bt, avg=3129.0, vol=1.0)
    bt._handle_contract_rolls(pd.Timestamp("2026-01-05"), {"RB0": _roll_bar()})
    trades = bt.account.trades
    assert len(trades) == 2
    t_close, t_open = trades[0], trades[1]
    assert t_close["action"] == "close" and t_close["direction"] == "cover"
    assert float(t_close["price"]) == pytest.approx(3200.0)
    # 空头平旧盈亏 = (开仓均价 − 平仓价) × 手数 × 乘数 − 平仓手续费（净额口径）
    gross = (3129.0 - 3200.0) * 1.0 * RB_MULT
    assert float(t_close["pnl"]) == pytest.approx(gross - 1.0 * RB_FEE_LOT)
    assert t_open["action"] == "open" and t_open["direction"] == "short"
    assert float(bt.account.short_positions["RB0"].avg_cost) == pytest.approx(3100.0)
    assert bt.roll_count == 1


def test_roll_no_position_no_fill():
    """无持仓的换月日不产生任何成交。"""
    bt = _bare_bt()
    bt._handle_contract_rolls(pd.Timestamp("2026-01-05"), {"RB0": _roll_bar()})
    assert bt.account.trades == []
    assert bt.roll_count == 0


def test_roll_missing_exit_price_warns_and_skips():
    """缺旧合约平仓价：warning + 不成交，禁止静默当作滚动成功。"""
    bt = _bare_bt()
    _long_pos(bt)
    bar = _roll_bar(exit_px=None)
    bar["roll_exit_price"] = None
    bt._handle_contract_rolls(pd.Timestamp("2026-01-05"), {"RB0": bar})
    assert bt.account.trades == []
    assert bt.roll_count == 0
    assert float(bt.account.positions["RB0"].volume) == pytest.approx(2.0)


def test_non_roll_bar_ignored():
    """roll=False 的普通 bar 不触发换月成交。"""
    bt = _bare_bt()
    _long_pos(bt)
    bar = _roll_bar()
    bar["roll"] = False
    bt._handle_contract_rolls(pd.Timestamp("2026-01-05"), {"RB0": bar})
    assert bt.account.trades == []


def test_dominant_row_carries_roll_legs():
    """自建双序列的换月行必须携带平旧腿价格与旧合约代码。"""
    cols = pd.MultiIndex.from_product(
        [["RB2601"], ["open", "high", "low", "close", "volume", "settle"]])
    day = pd.Timestamp("2026-01-05")
    merged = pd.DataFrame([[3100.0, 3110.0, 3090.0, 3105.0, 100.0, 3102.0]],
                          columns=cols, index=[day])
    row = DataFetcher._dominant_row(
        merged=merged, frames=None, current="RB2601", day=day, cum_factor=0.98,
        roll=True, roll_exit_price=3200.0, roll_prev_contract="RB2510")
    assert row["roll"] is True
    assert row["roll_exit_price"] == pytest.approx(3200.0)
    assert row["roll_prev_contract"] == "RB2510"
    assert row["contract"] == "RB2601"
    # 恒等式：主列 = raw × adj_factor（信号价空间一致性）
    assert row["close"] == pytest.approx(row["raw_close"] * row["adj_factor"])
    cols0 = pd.MultiIndex.from_product(
        [["RB2510"], ["open", "high", "low", "close", "volume", "settle"]])
    merged0 = pd.DataFrame([[3200.0, 3210.0, 3190.0, 3200.0, 100.0, 3202.0]],
                           columns=cols0, index=[day])
    plain = DataFetcher._dominant_row(
        merged=merged0, frames=None, current="RB2510", day=day, cum_factor=1.0,
        roll=False)
    assert plain["roll"] is False
    assert plain["roll_exit_price"] is None
    assert plain["roll_prev_contract"] is None


def test_prev_close_uses_settle_for_futures():
    """结算价口径（评审七轮③）：期货帧前收 = 昨【结算价】，非昨收——
    涨跌停/保证金/强平基准若用昨收，9% 保证金（≈11 倍杠杆）下强平阈值整体偏移。"""
    bt = _bare_bt()
    bar = {"settle": 3102.0, "close": 3105.0, "raw_close": 3105.0}
    out = bt._build_prev_close({"RB0": bar})
    assert out["RB0"] == pytest.approx(3102.0)
    assert out["RB0"] != pytest.approx(3105.0)


def test_prev_close_daily_frame_unchanged():
    """无 settle / raw_close 的日线帧沿用主列 close（既有行为不变）。"""
    bt = _bare_bt()
    out = bt._build_prev_close({"600519": {"close": 1400.0}})
    assert out["600519"] == pytest.approx(1400.0)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
