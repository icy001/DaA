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


# ==================== 终验 z5：期货基准规则 + 平今平昨费率区分 ====================

def _resolve_shell(symbols, explicit=None):
    """基准解析壳：仅 _resolve_future_benchmark 依赖的最小属性。"""
    bt = Backtester.__new__(Backtester)
    bt._pending_bench_note = None
    return bt._resolve_future_benchmark(symbols, explicit)


def test_future_benchmark_commodity_buyhold():
    """商品期货无对应外部基准：默认同品种连续合约 buy&hold，绝不套 H00300。"""
    mode, bench = _resolve_shell(["RB0"])
    assert mode == "commodity_buyhold"
    assert bench is None
    mode, bench = _resolve_shell(["RB2510", "HC2510"])
    assert mode == "commodity_buyhold" and bench is None
    # 显式传股票基准给商品期货 → raise（禁止跨资产混用）
    with pytest.raises(ValueError, match="禁止跨资产混用"):
        _resolve_shell(["RB0"], "H00300")


def test_future_benchmark_stock_index_map():
    """股指期货映射全收益指数：IF→H00300、IC→H00905；IH/IM 代码未登记→None+告警。"""
    assert _resolve_shell(["IF2512"]) == ("stock_index", "H00300")
    assert _resolve_shell(["IC2512"]) == ("stock_index", "H00905")
    mode, bench = _resolve_shell(["IH2512"])
    assert mode == "stock_index" and bench is None
    # IF 池显式传映射值放行；传其它基准 raise
    assert _resolve_shell(["IF2512"], "H00300") == ("stock_index", "H00300")
    with pytest.raises(ValueError, match="禁止跨资产混用"):
        _resolve_shell(["IF2512"], "000300")


def test_future_benchmark_mixed_pool_raises():
    """期货+非期货混合池直接 raise（基准口径不可混合，fail-closed）。"""
    with pytest.raises(ValueError, match="基准口径不可混合"):
        _resolve_shell(["RB0", "600519"])


def test_stock_pool_benchmark_unchanged():
    """非期货池沿用股票基准（行为不变）。"""
    mode, bench = _resolve_shell(["600519"])
    assert mode is None
    assert bench == config.BENCHMARK


def test_buyhold_benchmark_frame():
    """buy&hold 基准帧：首日=初始权益、比例跟随调整序列、attrs 明确标注口径。"""
    bt = Backtester.__new__(Backtester)
    bt.initial_capital = 1_000_000.0
    bt.logger = logging.getLogger("test_future_roll")
    idx = pd.bdate_range("2026-01-05", periods=4)
    bt.frames = {"RB0": pd.DataFrame(
        {"close": [3100.0, 3200.0, 3150.0, 3250.0]}, index=idx)}
    bench = bt._build_buyhold_benchmark()
    assert bench is not None
    assert float(bench["benchmark_equity"].iloc[0]) == pytest.approx(1_000_000.0)
    assert float(bench["benchmark_equity"].iloc[-1]) == pytest.approx(
        1_000_000.0 * 3250.0 / 3100.0)
    assert bench.attrs["future_benchmark"] == "self_continuous_buy_hold"
    assert "禁止与股票基准混用" in bench.attrs["note"]


def test_close_today_fee_distinct_from_close():
    """平今/平昨费率区分（IF：平今 0.000345 vs 平昨 0.000023，15 倍）——
    未区分则默认同费率属静默口径错误，禁止。"""
    acc = TradingAccount(1_000_000, run_mode="backtest")
    fee_close = acc.calc_commission("IF2512", "sell", 4000.0, 1,
                                    is_close_today=False, market_type="cn_future",
                                    is_open=False)
    fee_today = acc.calc_commission("IF2512", "sell", 4000.0, 1,
                                    is_close_today=True, market_type="cn_future",
                                    is_open=False)
    assert fee_close == pytest.approx(4000.0 * 300 * 0.000023, abs=0.01)
    assert fee_today == pytest.approx(4000.0 * 300 * 0.000345, abs=0.01)
    assert fee_today > fee_close * 10


def test_variety_spec_five_keys_complete():
    """治理面合约规格五件套完整性：全部品种必须带乘数/保证金率/tick/涨跌停/开平平今费率。"""
    required = {"multiplier", "margin_rate", "tick", "price_limit"}
    for variety, spec in config.CN_FUTURES_VARIETY.items():
        missing = required - set(spec)
        assert not missing, f"{variety} 缺规格键 {missing}"
        assert {"commission_type"} <= set(spec)
        if spec.get("commission_type") == "per_lot":
            keys = {"commission_per_lot_open", "commission_per_lot_close",
                    "commission_per_lot_close_today"}
        else:
            keys = {"commission_rate_open", "commission_rate_close",
                    "commission_rate_close_today"}
        miss_fee = keys - set(spec)
        assert not miss_fee, f"{variety} 缺费率键 {miss_fee}"


def test_variety_key_family_matches_commission_type_exhaustive():
    """常驻穷举守卫（评审裁定：不得停在一次性脚本）：键名族 × commission_type
    一致性全品种校验——per_lot ↔ commission_per_lot_*、per_value ↔
    commission_rate_*，且另一族键不得混入品种级 spec（终验 14 品种误标 bug
    正是键名族错位，五件套测试与值指纹都看不见）。"""
    for variety, spec in config.CN_FUTURES_VARIETY.items():
        ct = spec.get("commission_type")
        if ct == "per_lot":
            assert not ({"commission_rate_open", "commission_rate_close",
                         "commission_rate_close_today"} & set(spec)), \
                f"{variety} per_lot 却混入 commission_rate_* 键"
        elif ct == "per_value":
            assert not ({"commission_per_lot_open", "commission_per_lot_close",
                         "commission_per_lot_close_today"} & set(spec)), \
                f"{variety} per_value 却混入 commission_per_lot_* 键"
        else:
            pytest.fail(f"{variety} commission_type 非法：{ct!r}")


def test_engine_reads_nonzero_fee_for_every_variety():
    """常驻穷举守卫（消费侧）：31 品种 × 开/平/平今三类动作，引擎
    calc_commission 必须读到非零费率——「登记了没被消费」在运行路径即失败。"""
    acc = TradingAccount(1_000_000, run_mode="backtest")
    for variety, spec in config.CN_FUTURES_VARIETY.items():
        symbol = f"{variety}2601"
        price = 10_000.0
        for is_open, is_close_today in ((True, False), (False, False), (False, True)):
            fee = acc.calc_commission(symbol, "sell" if not is_open else "buy",
                                      price, 1, is_close_today=is_close_today,
                                      market_type="cn_future", is_open=is_open)
            assert fee > 0, (f"{variety} {'开仓' if is_open else '平今' if is_close_today else '平昨'}"
                             f"费率被解析为 0（登记与消费不一致）")


def test_minute_series_supported_boundary_fail_closed():
    """品种适用边界 fail-closed（评审裁定：边界由白名单表达，不由注释表达）：
    夜盘跨午夜品种（SC/CU/AU 等 9 个）分钟序列显式拒绝；支持品种标志齐全。"""
    supported = {v for v, s in config.CN_FUTURES_VARIETY.items()
                 if s.get("minute_series_supported")}
    unsupported = set(config.CN_FUTURES_VARIETY) - supported
    # 跨午夜品种全部未置位
    assert {"SC", "CU", "AL", "ZN", "AU", "AG", "NI", "SS", "SI"} <= unsupported, \
        f"跨午夜品种必须全部 False，实际 {unsupported}"
    # 全部 31 品种标志显式登记（不许缺省）
    assert len(supported) + len(unsupported) == len(config.CN_FUTURES_VARIETY) == 31


def test_minute_series_gate_raises_for_unsupported():
    """未置位品种调用分钟序列直接 raise（不联网——闸在入口先于任何请求）。"""
    import pytest as _pytest
    from core.data_fetcher import DataFetcher
    f = DataFetcher()
    with _pytest.raises(ValueError, match="minute_series_supported"):
        f.build_dominant_series_minute(["SC2509", "SC2510"], "2025-01-01",
                                       "2025-06-30", period="60min", variety="SC")


def test_minute_series_gate_passes_for_supported():
    """支持品种（RB）通过边界闸且不误拦：monkeypatch 取数抛网络 stub——
    若闸误拦会先报 minute_series_supported ValueError，报 network-stub 即闸放行。"""
    import pytest as _pytest
    import unittest.mock as mock
    from core.data_fetcher import DataFetcher
    f = DataFetcher()
    with mock.patch.object(f, "_request", side_effect=RuntimeError("network-stub")):
        with _pytest.raises(RuntimeError, match="network-stub"):
            f.build_dominant_series_minute(["RB2510", "RB2601"], "2025-06-01",
                                           "2025-09-30", period="60min", variety="RB")


def test_black_swan_direction_semantics():
    """黑天鹅保护方向语义（港股预检发现）：多头防暴跌、空头防轧空——
    旧 abs(change) 把暴涨也强平多头（00700 2026-06-02 +10.46% 卖飞实证）。"""
    from core.risk import RiskManager
    acc = TradingAccount(1_000_000, run_mode="backtest")
    rm = RiskManager(acc)
    pos = Position(symbol="00700", market="hk_stock", direction="long",
                   volume=100, avg_cost=400.0, kind="spot")
    acc.positions["00700"] = pos
    rm._prev_prices = {"00700": 400.0}
    # 暴涨 +10.46%（2026-06-02 实况）：多头不平仓
    acts = rm._black_swan_actions({"00700": 441.84})
    assert acts == [], "暴涨不应强平多头"
    assert float(acc.positions["00700"].volume) == 100.0
    # 暴跌 -10.46%：多头强平
    acts = rm._black_swan_actions({"00700": 358.16})
    assert len(acts) == 1 and acts[0]["direction"] == "sell"
    # 空头轧空：暴涨强平空头
    acc.positions.pop("00700")
    acc.short_positions["00700"] = Position(
        symbol="00700", market="hk_stock", direction="short", volume=100,
        avg_cost=400.0, kind="spot")
    acts = rm._black_swan_actions({"00700": 441.84})
    assert len(acts) == 1 and acts[0]["direction"] == "cover"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
