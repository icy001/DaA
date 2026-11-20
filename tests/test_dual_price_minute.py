# -*- coding: utf-8 -*-
"""v3.53 评审三轮：分钟线复权双价体系专项测试（除权日）。

价权边界（评审裁定，验收单 §六C.4）：
  - 信号生成/收益计算/回撤熔断判定 → 主列复权价（消除除权跳空假信号）；
  - 下单股数/涨跌停校验/滑点/成交记录 → raw_* 列（与交易所实际报价一致）。

样本语义（10 送 10 除权，除权日 2025-06-10）：
  raw 价：06-09 close 20 → 06-10 close 10（-50% 跳空）；
  BaoStock fore 因子：06-10 起 0.5 → 1.0（qfq = raw × fore）；
  复权价：06-09 close 20×0.5=10 → 06-10 close 10×1.0=10（连续，无假跳空）。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from core.account import TradingAccount
from core.data_fetcher import DataFetcher
from core.execution import ExecutionModel


# ==================== 样本构造 ====================

def _raw_frame() -> pd.DataFrame:
    """3 个交易日 × 每日 2 根分钟 bar 的原始价帧（不复权）。"""
    idx = pd.DatetimeIndex([
        "2025-06-06 10:30", "2025-06-06 14:59",   # d1
        "2025-06-09 10:30", "2025-06-09 14:59",   # d2（除权前末日）
        "2025-06-10 10:30", "2025-06-10 14:59",   # d3（除权日）
    ])
    close = [20.0, 20.0, 20.0, 20.0, 10.0, 10.0]
    return pd.DataFrame({
        "open": close, "high": close, "low": close, "close": close,
        "volume": [10000.0] * len(idx), "amount": [c * v for c, v in zip(close, [10000.0] * 6)],
    }, index=idx)


def _factor_df() -> pd.DataFrame:
    """BaoStock query_adjust_factor 形态：索引为除权日，qfq=fore/hfq=back。

    语义：dividOperateDate 当日起生效新因子——2025-06-10 除权（10送10）当日
    fore 跳为 1.0；此前的日期 ffill 沿用上一次除权（2024-06-10）的 0.5。
    """
    return pd.DataFrame({
        "qfq_factor": [0.5, 1.0],
        "hfq_factor": [1.0, 2.0],
        "factor_source": ["baostock", "baostock"],
    }, index=pd.DatetimeIndex(["2024-06-10", "2025-06-10"], name="date"))


def _fetcher(tmp_path: Path) -> DataFetcher:
    """独立临时缓存目录（测试幂等：不依赖全局缓存命中）。"""
    return DataFetcher(cache_dir=tmp_path)


# ==================== 数据出口：双价列 ====================

def test_apply_adjust_keep_raw_emits_dual_price_columns(tmp_path):
    """keep_raw=True：主列=复权价、raw_* 保留原始价、adj_factor 按所属交易日折算。"""
    out = _fetcher(tmp_path)._apply_adjust(_raw_frame(), _factor_df(), "qfq",
                                           "cn_stock", "600519", keep_raw=True)
    assert out.attrs["dual_price"] is True
    assert out.attrs["adjust"] == "qfq"
    for col in ("raw_open", "raw_high", "raw_low", "raw_close", "adj_factor"):
        assert col in out.columns, f"双价体系缺少 {col} 列"
    # 同一交易日的分钟 bar 共享该日因子（d1 两根 bar 都 ffill 自上次除权 2024-06-10 的 0.5）
    d1 = out.loc["2025-06-06"]
    assert d1["adj_factor"].nunique() == 1
    assert float(d1["adj_factor"].iloc[0]) == pytest.approx(0.5)
    # 除权日当日起生效新因子 1.0
    d3 = out.loc["2025-06-10"]
    assert float(d3["adj_factor"].iloc[0]) == pytest.approx(1.0)
    # 主列 = raw × 当日因子
    assert out.loc["2025-06-06 10:30", "close"] == pytest.approx(20.0 * 0.5)
    assert out.loc["2025-06-10 10:30", "close"] == pytest.approx(10.0 * 1.0)
    # raw 列保留交易所原始价（未被因子污染）
    assert out.loc["2025-06-06 10:30", "raw_close"] == pytest.approx(20.0)
    assert out.loc["2025-06-10 10:30", "raw_close"] == pytest.approx(10.0)
    # 量额不随复权变化
    assert out["volume"].equals(_raw_frame()["volume"])


def test_ex_div_day_adj_continuous_raw_gaps(tmp_path):
    """除权日核心断言：复权价连续（无假跳空）、raw 价跳空（-50%，真实除权缺口）。"""
    out = _fetcher(tmp_path)._apply_adjust(_raw_frame(), _factor_df(), "qfq",
                                           "cn_stock", "600519", keep_raw=True)
    adj_prev = float(out.loc["2025-06-09 14:59", "close"])
    adj_ex = float(out.loc["2025-06-10 10:30", "close"])
    raw_prev = float(out.loc["2025-06-09 14:59", "raw_close"])
    raw_ex = float(out.loc["2025-06-10 10:30", "raw_close"])
    # 复权价连续：|变化| < 0.1%（信号/回撤/熔断消费空间无假跳空）
    assert abs(adj_ex / adj_prev - 1.0) < 1e-3
    # raw 价跳空 -50%（除权缺口在原始价空间真实存在）
    assert raw_ex / raw_prev == pytest.approx(0.5)


def test_get_kline_minute_branch_wires_dual_price(tmp_path, monkeypatch):
    """get_kline 分钟分支（cn_stock + adjust）必须接线因子折算，不再降级 adjust=none。"""
    fetcher = _fetcher(tmp_path)
    monkeypatch.setattr(fetcher, "get_minute", lambda *a, **k: _raw_frame())
    monkeypatch.setattr(fetcher, "_get_adj_factor", lambda *a, **k: _factor_df())
    out = fetcher.get_kline("600519", "2025-06-06", "2025-06-10", period="5min",
                            adjust="qfq", market_type="cn_stock")
    assert out.attrs["dual_price"] is True
    assert out.attrs["adjust"] == "qfq"
    assert "raw_close" in out.columns and "adj_factor" in out.columns
    # 非 cn_stock 分钟线保持显式降级（无已验证因子源，禁止伪装复权成功）
    monkeypatch.setattr(fetcher, "get_minute", lambda *a, **k: _raw_frame())
    out_us = fetcher.get_kline("AAPL", "2025-06-06", "2025-06-10", period="5min",
                               adjust="qfq", market_type="us_stock")
    assert out_us.attrs.get("adjust") == "none"
    assert "adj_factor" not in out_us.columns


def test_apply_adjust_without_factor_keeps_raw_identity(tmp_path):
    """因子缺失降级：raw 列照附（adj=raw 恒等），下游撮合行为不受影响。"""
    fetcher = _fetcher(tmp_path)
    out = fetcher._apply_adjust(_raw_frame(), None, "qfq",
                                "cn_stock", "600519", keep_raw=True)
    assert out.attrs["adjust"] == "none"
    assert out.attrs["dual_price"] is True
    assert (out["close"] == out["raw_close"]).all()
    assert (out["adj_factor"] == 1.0).all()


# ==================== 撮合：raw 空间 ====================

def _dual_bar(raw_px: float, factor: float, prev_raw: float) -> dict:
    adj = raw_px * factor
    return {"open": adj, "high": adj, "low": adj, "close": adj,
            "raw_open": raw_px, "raw_high": raw_px, "raw_low": raw_px,
            "raw_close": raw_px, "adj_factor": factor, "volume": 1_000_000.0,
            "_prev_raw": prev_raw}


def test_ex_div_open_not_misread_as_limit_up():
    """除权日假拒绝回归：raw 前收 10 → raw open 10.5（+5% 正常开盘）必须放行。

    若误用 adj 空间前收（10×0.5=5），会判 10.5 ≥ 5×1.1=5.5 → 假涨停止损。
    这是「涨跌停校验必须用 raw 价」的固证（防未来回退）。
    """
    model = ExecutionModel(slippage=0.0, run_mode="backtest")
    bar = _dual_bar(10.5, factor=1.0, prev_raw=10.0)
    # 前收 = raw 前收 10.0（引擎 _prev_close 取 raw_close）
    model.set_context({"600519": bar}, {"600519": 10.0})
    d = model.check(symbol="600519", direction="buy", action="open",
                    order_type="market", volume=100, price=10.5,
                    market="cn_stock", rule={})
    assert "reject" not in d, f"除权日正常开盘被假拒：{d}"
    assert d["raw_price"] == pytest.approx(10.5)      # raw 成交价（交易所口径）
    assert d["price"] == pytest.approx(10.5 * 1.0)    # 记账价 = raw × 当日因子


def test_adj_space_prev_close_would_false_reject():
    """对照实验：同样的 bar 若误用 adj 前收（5.0）确实会假拒——固化差异来源。"""
    model = ExecutionModel(slippage=0.0, run_mode="backtest")
    bar = _dual_bar(10.5, factor=1.0, prev_raw=10.0)
    model.set_context({"600519": bar}, {"600519": 5.0})   # 误用 adj 前收
    d = model.check(symbol="600519", direction="buy", action="open",
                    order_type="market", volume=100, price=10.5,
                    market="cn_stock", rule={})
    assert "reject" in d   # 误用 adj 前收 → 假涨停拒绝（本测试锁定该错误路径存在过）


def test_limit_up_down_judged_in_raw_space():
    """开盘即涨停买不进 / 跌停卖不出：判定锚定 raw 报价（涨跌停由交易所按 raw 前收钉死）。"""
    model = ExecutionModel(slippage=0.0, run_mode="backtest")
    # raw 前收 10 → 涨停 11.0：买单拒绝
    model.set_context({"600519": _dual_bar(11.0, 1.0, 10.0)}, {"600519": 10.0})
    d = model.check(symbol="600519", direction="buy", action="open",
                    order_type="market", volume=100, price=11.0,
                    market="cn_stock", rule={})
    assert "reject" in d and "涨停" in d["reject"]
    # raw 前收 10 → 跌停 9.0：卖单拒绝
    model.set_context({"600519": _dual_bar(9.0, 1.0, 10.0)}, {"600519": 10.0})
    d = model.check(symbol="600519", direction="sell", action="close",
                    order_type="market", volume=100, price=9.0,
                    market="cn_stock", rule={})
    assert "reject" in d and "跌停" in d["reject"]


def test_slippage_applied_in_raw_space():
    """滑点在 raw 空间计算（0.1% 买向上偏）：raw 成交价 = raw 基准 × (1+滑点)。"""
    model = ExecutionModel(slippage=0.001, run_mode="backtest")
    bar = _dual_bar(20.0, factor=0.5, prev_raw=20.0)   # 除权前：raw 20 / adj 10
    model.set_context({"600519": bar}, {"600519": 20.0})
    d = model.check(symbol="600519", direction="buy", action="open",
                    order_type="market", volume=100, price=10.0,
                    market="cn_stock", rule={})
    assert d["raw_price"] == pytest.approx(20.0 * 1.001)   # raw 空间滑点
    assert d["price"] == pytest.approx(20.0 * 1.001 * 0.5)  # 记账换算回 adj


def test_no_raw_columns_keeps_legacy_behavior():
    """日线帧（无 raw_* 列）行为完全不变：price 即记账价、无 raw_price 输出。"""
    model = ExecutionModel(slippage=0.0, run_mode="backtest")
    bar = {"open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1_000_000.0}
    model.set_context({"600519": bar}, {"600519": 10.0})
    d = model.check(symbol="600519", direction="buy", action="open",
                    order_type="market", volume=100, price=10.0,
                    market="cn_stock", rule={})
    assert d["price"] == pytest.approx(10.0)
    assert "raw_price" not in d


# ==================== 账户：raw 披露 + adj 记账 ====================

def test_account_dual_price_fill_and_pnl():
    """全链路：成交记录 raw_price=交易所口径、记账价=adj 口径；跨除权日 pnl 无假亏损。

    06-09 raw 20（factor 0.5 → adj 10）买入 100 股；
    06-10 除权日 raw 10（factor 1.0 → adj 10）卖出 100 股。
    adj 口径 pnl ≈ 0（仅费用损耗）；若误用 raw 记账会算出 (10-20)×100=-1000 假亏。
    """
    account = TradingAccount(1_000_000, run_mode="backtest")
    model = ExecutionModel(slippage=0.0, run_mode="backtest")
    account.execution_model = model

    # d2（除权前）：raw 20 / adj 10
    model.set_context({"600519": _dual_bar(20.0, 0.5, 20.0)}, {"600519": 20.0})
    r = account.place_order("600519", "buy", volume=100, price=10.0,
                            order_time=pd.Timestamp("2025-06-09 10:30"),
                            warmup_ok=True, fill_now=True)
    assert r["status"] == "filled"
    t_open = account.trades[-1]
    assert t_open["raw_price"] == pytest.approx(20.0)   # 成交记录披露 raw 价
    assert t_open["price"] == pytest.approx(10.0)       # 记账价 = 20 × 0.5
    # 现金按 adj 扣（100×10=1000，另加 cn_stock 最低佣金 5 元）
    assert account.cash == pytest.approx(1_000_000 - 100 * 10.0 - 5.0, abs=1.5)

    # d3（除权日）：raw 10 / adj 10（T+1 可卖）
    model.set_context({"600519": _dual_bar(10.0, 1.0, 10.0)}, {"600519": 10.0})
    r2 = account.place_order("600519", "sell", volume=100, price=10.0,
                             order_time=pd.Timestamp("2025-06-10 10:30"),
                             fill_now=True)
    assert r2["status"] == "filled"
    t_close = account.trades[-1]
    assert t_close["raw_price"] == pytest.approx(10.0)
    # pnl 在 adj 空间：10 → 10 仅费用损耗（|pnl| < 100）；
    # raw 假亏 = (10-20)×100 = -1000 必须不出现
    assert -100.0 < t_close["pnl"] < 0.0
    # 权益无假跳空：卖出现金 ≈ 本金（费用除外）
    assert account.cash == pytest.approx(1_000_000, abs=100.0)


def test_account_no_execution_model_raw_price_none():
    """未挂成交模型（实盘/模拟盘形态）：raw_price=None，不伪造。"""
    account = TradingAccount(1_000_000, run_mode="backtest")
    r = account.place_order("600519", "buy", volume=100, price=10.0,
                            order_time=pd.Timestamp("2025-06-09 10:30"),
                            warmup_ok=True, fill_now=True)
    assert r["status"] == "filled"
    assert account.trades[-1]["raw_price"] is None


# ==================== 评审四轮·核实 b：除权日涨跌停参考价 ====================

def _bare_backtester():
    """不 run() 的引擎壳：只为调用 _build_prev_close 等纯逻辑。"""
    from core.backtester import Backtester
    return Backtester.__new__(Backtester)


def test_ex_div_prev_close_uses_exchange_reference_price():
    """除权日涨跌停前收 = 昨收 × (昨日因子/当日因子)——交易所除权参考价，
    非直接昨收。600519 2025-06-26 实测：昨收 1435.86、因子比 0.98078
    → 参考价 1408.27 ≈ 1435.86 − 27.624（每股现金红利）。"""
    bt = _bare_backtester()
    bt._prev_adj_factor = {"600519": 0.942063}
    bars = {"600519": {"raw_close": 1435.86, "adj_factor": 0.960527,
                       "close": 1435.86 * 0.960527}}
    pc = bt._build_prev_close(bars)
    assert pc["600519"] == pytest.approx(1435.86 * 0.942063 / 0.960527)
    assert pc["600519"] == pytest.approx(1408.27, abs=0.5)   # ≈ 昨收 − 27.624


def test_no_ex_div_prev_close_equals_raw_close():
    """非除权日（因子比值=1）：前收就是昨收，行为不变。"""
    bt = _bare_backtester()
    bt._prev_adj_factor = {"600519": 0.960527}
    bars = {"600519": {"raw_close": 1435.86, "adj_factor": 0.960527}}
    assert bt._build_prev_close(bars)["600519"] == pytest.approx(1435.86)


def test_daily_frame_prev_close_legacy():
    """日线帧（无 raw 列）：前收沿用主列 close，既有行为不变。"""
    bt = _bare_backtester()
    bt._prev_adj_factor = {}
    bars = {"600519": {"close": 42.38}}
    assert bt._build_prev_close(bars)["600519"] == pytest.approx(42.38)


# ==================== 评审四轮·事2：基准对齐（全收益指数） ====================

def test_backtester_default_benchmark_follows_config():
    """引擎基准默认集中引用 config.BENCHMARK（已换 H00300 全收益），
    禁止硬编码 000300（价格指数不含股息，会系统性高估含息策略超额）。"""
    from core.backtester import Backtester
    from core.strategy import BaseStrategy

    class _StubStrategy(BaseStrategy):   # 仅用于通过构造校验（不 run）
        meta = {}

        def on_bar(self, bars, date=None):
            return []

    bt = Backtester(_StubStrategy, symbols=["600519"])
    assert bt.benchmark == "H00300"


def test_csindex_partial_return_rejected(tmp_path, monkeypatch):
    """中证官网接口部分返回（实测偶发 ~345 行）必须 raise，禁止残缺基准落缓存。"""
    fetcher = _fetcher(tmp_path)
    import pandas as _pd
    short = _pd.DataFrame({
        "日期": _pd.date_range("2025-01-01", periods=100).strftime("%Y-%m-%d"),
        "收盘": [5000.0] * 100,
    })
    monkeypatch.setattr(fetcher, "_request", lambda *a, **k: short)
    with pytest.raises(RuntimeError, match="部分返回"):
        fetcher._fetch_csindex_ex_return("H00300", "2020-01-01", "2026-11-18")


def test_csindex_ohlc_filled_with_close_not_dropped(tmp_path, monkeypatch):
    """全收益指数无盘价（开盘列大面积 NaN）：用收盘价占位后不得被质量检查丢行，
    且 attrs 必须标注 ohlc_filled_with_close=True（诚实披露，禁止静默）。"""
    fetcher = _fetcher(tmp_path)
    import numpy as _np
    import pandas as _pd
    dates = _pd.date_range("2020-01-01", periods=1600, freq="B")
    raw = _pd.DataFrame({
        "日期": dates.strftime("%Y-%m-%d"),
        "开盘": _np.where(_np.arange(1600) < 300, 5000.0, _np.nan),   # 前段有盘价、后段缺
        "最高": _np.where(_np.arange(1600) < 300, 5010.0, _np.nan),
        "最低": _np.where(_np.arange(1600) < 300, 4990.0, _np.nan),
        "收盘": 5000.0 + _np.arange(1600),
    })
    monkeypatch.setattr(fetcher, "_request", lambda *a, **k: raw)
    out = fetcher._fetch_csindex_ex_return("H00300", "2020-01-01", "2026-11-18")
    assert len(out) == 1600                                    # 一行不丢
    assert out["close"].notna().all()
    assert out.attrs["ohlc_filled_with_close"] is True
    assert out.attrs["index_kind"] == "total_return"
    assert out.attrs["basis_note"] == "全收益指数（含样本股分红再投资）"
