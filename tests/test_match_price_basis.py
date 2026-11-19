"""E1：撮合价基准参数化 + 未来函数强制断言（tests/test_match_price_basis.py）

验证的唯一原则：**成交所用 bar 必须严格晚于决策所用 bar**。

覆盖：
  1) config.EXECUTION_MODEL 的 match_price_basis / meta / enforce_fill_after_signal
     与顶层 SIGNAL_EGRESS_CONFORMANCE 已按规格合并；
  2) assert_fill_after_signal：
     - next_open：t 决策 → t+1 成交通过；
     - next_open：t 决策 → t 成交抛 LookaheadError；
     - same_open / same_close（bar_offset=0）：同根成交一律抛 LookaheadError；
     - 缺任一下标（无法判定）时不误报；
  3) 端到端回测：next_open 下成交落在 t+1，成交价 = t+1 开盘价 × (1+滑点)；
  4) 端到端回测：same_open 下同根撮合直接抛 LookaheadError（不得降级为普通拒单）；
  5) enforce_fill_after_signal=False 时仅告警（对照实验开关），不抛错。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from core.backtester import Backtester
from core.execution import (ExecutionModel, LookaheadError, assert_fill_after_signal,
                            match_price_basis, match_price_basis_meta)
from core.strategy import BaseStrategy

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'✅' if ok else '❌'} {name}" + (f" | {detail}" if detail else ""))


def catches(fn, *args, **kwargs):
    """返回异常实例；没抛错返回 None。"""
    try:
        fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        return exc
    return None


# ==================== 确定性行情（open_i = 100 + i） ====================

class MarkerFetcher:
    """确定性随机游走（固定种子），成交价一律从本帧反查，便于断言「用了哪一根 bar」。"""

    def __init__(self, n: int = 200):
        idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
        rng = np.random.default_rng(20261112)
        ret = 0.0003 + rng.normal(0, 0.012, n)   # 带噪声，避免被未来函数检测误判为直线
        close = 100.0 * np.cumprod(1.0 + ret)
        open_ = close * (1.0 + rng.normal(0, 0.002, n))
        self.frame = pd.DataFrame({
            "open": open_,
            "high": np.maximum(open_, close) * 1.002,
            "low": np.minimum(open_, close) * 0.998,
            "close": close,
            "volume": np.full(n, 5_000_000.0),
            "amount": close * 5_000_000.0,
        }, index=idx)
        self.frame["price_adjust"] = "qfq"

    def get_daily(self, symbol, start_date=None, end_date=None, adjust="qfq",
                  market_type=None, **kwargs):
        frame = self.frame
        if start_date:
            frame = frame[frame.index >= pd.Timestamp(start_date)]
        if end_date:
            frame = frame[frame.index <= pd.Timestamp(end_date)]
        return frame.copy()

    def get_kline(self, symbol, **kwargs):
        return self.get_daily(symbol, **kwargs)


class BuyOnceProbe(BaseStrategy):
    """预热结束后买一次；记录决策 bar 的日期与返回状态。"""

    meta = {"name": "_mpb_buy_once", "periods": ["1d"], "params": {},
            "warmup": [("MA", {"n": 4})], "description": "test"}

    def init(self):
        self.signal_date = None
        self.status = None

    def on_bar(self, date, bars):
        if self.signal_date is not None:
            return
        if not self.is_warmup_ok("600519"):
            return
        res = self.buy("600519", 100)
        self.signal_date = pd.Timestamp(date)
        self.status = res.get("status")


def _run(fetcher, **kwargs):
    frame = fetcher.frame
    bt = Backtester(BuyOnceProbe, symbols=["600519"],
                    start_date=frame.index[0].strftime("%Y-%m-%d"),
                    end_date=frame.index[-1].strftime("%Y-%m-%d"),
                    initial_capital=1_000_000.0, benchmark=None,
                    fetcher=fetcher, liquidate_at_end=False, **kwargs)
    return bt, bt.run()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="mpb_test_"))
    _ = tmp

    # ---------- 1. config 合并检查 ----------
    cfg = config.EXECUTION_MODEL
    meta = cfg.get("match_price_basis_meta") or {}
    check("config：match_price_basis 默认 next_open",
          cfg.get("match_price_basis") == "next_open" and match_price_basis() == "next_open",
          f"basis={match_price_basis()}")
    check("config：四种基准的 price/bar_offset/lookahead_safe 已声明",
          meta.get("next_open", {}).get("bar_offset") == 1
          and meta.get("next_close", {}).get("price") == "close"
          and meta.get("same_open", {}).get("bar_offset") == 0
          and meta.get("same_close", {}).get("lookahead_safe") is False
          and meta.get("next_open", {}).get("lookahead_safe") is True,
          str(meta))
    check("config：enforce_fill_after_signal=True", cfg.get("enforce_fill_after_signal") is True)
    egress = getattr(config, "SIGNAL_EGRESS_CONFORMANCE", {})
    check("config：SIGNAL_EGRESS_CONFORMANCE 六个信号出口 + 盯盘三列",
          egress.get("signal_egress_points")
          == ["place_order", "monitor_push", "report_plan", "investor_disclosure",
              "live_order_submit", "watch_only_live_push"]
          and egress.get("must_call_gate") == "core/signal_gate.py"
          and egress.get("monitor_must_inject_columns")
          == ["warmup_ok", "data_asof_date", "price_adjust"]
          and egress.get("forbid_bare_on_tick") is True,
          str(egress.get("signal_egress_points")))

    # ---------- 2. assert_fill_after_signal 单元断言 ----------
    check("next_open：t 决策 → t+1 成交 通过",
          catches(assert_fill_after_signal, 10, 11) is None)
    exc = catches(assert_fill_after_signal, 10, 10)
    check("next_open：t 决策 → t 成交 抛 LookaheadError",
          isinstance(exc, LookaheadError), str(exc))
    for basis in ("same_open", "same_close"):
        meta_b = match_price_basis_meta(basis)
        exc_b = catches(assert_fill_after_signal, 10, 10, basis)
        check(f"{basis}（bar_offset=0）：同根成交直接报错",
              meta_b["bar_offset"] == 0 and meta_b["lookahead_safe"] is False
              and isinstance(exc_b, LookaheadError), str(exc_b))
        check(f"{basis}：成交滞后到 t+1 仍通过",
              catches(assert_fill_after_signal, 10, 11, basis) is None)
    check("下标缺失（无法判定时点）不误报",
          catches(assert_fill_after_signal, None, 10) is None
          and catches(assert_fill_after_signal, 10, None) is None)

    # ---------- 3. 端到端：next_open 成交落在 t+1 ----------
    fetcher = MarkerFetcher(200)
    bt, _ = _run(fetcher)
    signal_date = bt.strategy.signal_date
    trade = next((t for t in bt.account.trades if t.get("direction") == "buy"), None)
    dates = list(fetcher.frame.index)
    next_date = dates[dates.index(signal_date) + 1] if signal_date in dates else None
    expected_px = float(fetcher.frame.loc[next_date, "open"]) * (1 + bt.execution.slippage)
    check("端到端 next_open：信号当根返回 pending（不立即成交）",
          bt.strategy.status == "pending", f"status={bt.strategy.status}")
    check("端到端 next_open：成交 bar = 决策 bar 的下一根",
          trade is not None and pd.Timestamp(trade["timestamp"]) == next_date,
          f"决策 {signal_date.date()} → 成交 {trade and pd.Timestamp(trade['timestamp']).date()}")
    check("端到端 next_open：成交价 = 下一根开盘价 × (1+滑点)",
          trade is not None and abs(float(trade["price"]) - expected_px) < 1e-6,
          f"fill={trade and float(trade['price']):.4f} expected={expected_px:.4f}")
    if trade is not None and signal_date is not None:
        same_bar_px = float(fetcher.frame.loc[signal_date, "open"]) * (1 + bt.execution.slippage)
        check("端到端 next_open：未回填决策当根开盘价",
              abs(float(trade["price"]) - same_bar_px) > 1e-6,
              f"若用当根会得到 {same_bar_px:.4f}")

    # ---------- 4. 端到端：same_open 同根撮合直接报错 ----------
    old_basis = config.EXECUTION_MODEL.get("match_price_basis")
    old_enforce = config.EXECUTION_MODEL.get("enforce_fill_after_signal")
    try:
        config.EXECUTION_MODEL["match_price_basis"] = "same_open"
        exc = catches(_run, MarkerFetcher(200))
        check("端到端 same_open：同根撮合抛 LookaheadError（不降级为拒单）",
              isinstance(exc, LookaheadError), f"{type(exc).__name__}: {exc}")

        # ---------- 5. 对照实验开关：仅告警不抛 ----------
        config.EXECUTION_MODEL["enforce_fill_after_signal"] = False
        exc_soft = catches(_run, MarkerFetcher(200))
        check("enforce_fill_after_signal=False：降级为告警、不抛错（对照实验）",
              exc_soft is None, f"{type(exc_soft).__name__ if exc_soft else 'no exception'}")
        check("same_close：ExecutionModel 解析为 close 基准且标记 unsafe",
              ExecutionModel(basis="same_close").price_field == "close"
              and ExecutionModel(basis="same_close").lookahead_safe is False)
    finally:
        config.EXECUTION_MODEL["match_price_basis"] = old_basis
        config.EXECUTION_MODEL["enforce_fill_after_signal"] = old_enforce

    print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
