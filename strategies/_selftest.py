"""策略离线自检脚手架（文件名以下划线开头，strategy_loader 会跳过本文件）。

所有示例策略的 `if __name__ == "__main__":` 都调用这里的 `run_selftest()`：

  1. `FakeFetcher` 生成 260 根**确定性合成日线**（含 pre_close / amount /
     price_adjust / volume），完全不联网；
  2. 用 `core.runner.run_backtest` 把策略完整跑一遍——预热闸门、内置风控、
     账户撮合、手续费全部走真实链路，只是行情是假的；
  3. 打印 meta 与信号（成交）条数，供人工快速判断「策略有没有跑起来」。

这里只做「能跑通 + 有信号」的冒烟检查；收益好坏、参数稳健性属于第 6/7 步。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# 允许 `python strategies/xxx.py` 直接运行时找到项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from core.runner import run_backtest

__all__ = ["FakeFetcher", "run_selftest", "BARS"]

BARS = 260

# 各市场合成行情的基准价（按代码识别市场后取用；只为让量级合理，不追求真实）
_BASE_PRICE = {
    "cn_stock": 30.0,
    "cn_etf": 4.0,
    "cn_convertible": 120.0,
    "cn_fund": 2.0,
    "cn_reverse_repo": 2.5,      # 逆回购的 close 被当作「年化利率 %」
    "hk_stock": 400.0,
    "us_stock": 180.0,
    "us_etf": 450.0,
    "cn_future": 3500.0,
    "crypto": 30000.0,
    "cn_option": 0.05,           # 期权权利金
    "cn_index": 3800.0,
}

# markets 字段 → 默认演示标的（策略 __main__ 不显式传 symbols 时使用）
_MARKET_SYMBOLS = {
    "cn_stock": "600519",
    "cn_etf": "510300",
    "cn_convertible": "110059",
    "cn_fund": "519066",
    "cn_reverse_repo": "131810",
    "hk_stock": "00700",
    "us_stock": "AAPL",
    "us_etf": "SPY",
    "cn_future": "rb2510",
    "crypto": "BTC",
    "cn_option": "10004567",
}


class FakeFetcher:
    """确定性合成行情：同一标的永远返回同一段 260 根日线，不联网。

    走势 = 基准价 ×（正弦波动 + 缓慢漂移），每 37 根有一根 +10% 的「涨停日」，
    这样均线交叉、突破、RSI 极值、涨停联动、网格穿越都能在自检里出现。
    """

    def __init__(self, n: int = BARS, end=None):
        self.n = int(n)
        self.end = pd.Timestamp(end or pd.Timestamp.today().normalize())
        self.index = pd.bdate_range(end=self.end, periods=self.n)
        self.calls = 0
        self._frames: dict = {}

    def get_daily(self, symbol, start_date=None, end_date=None, adjust="qfq", **kwargs):
        self.calls += 1
        return self._frame(str(symbol))

    def get_kline(self, symbol, start_date=None, end_date=None, period="1d",
                  adjust="qfq", **kwargs):
        return self.get_daily(symbol, start_date, end_date, adjust=adjust)

    # ---------- 内部 ----------
    def _frame(self, symbol: str) -> pd.DataFrame:
        if symbol not in self._frames:
            self._frames[symbol] = self._build(symbol)
        return self._frames[symbol].copy()

    def _build(self, symbol: str) -> pd.DataFrame:
        base = float(_BASE_PRICE.get(config.detect_market_type(symbol), 30.0))
        k = np.arange(self.n, dtype=float)
        phase = (sum(map(ord, symbol)) % 60) / 60.0 * 2.0 * np.pi
        wave = 1.0 + 0.12 * np.sin(2.0 * np.pi * k / 40.0 + phase) + 0.0006 * k
        close = base * wave
        close[(np.arange(self.n) % 37) == 20] *= 1.10     # 制造单日「涨停」，不改变长期水平
        frame = pd.DataFrame({
            "open": close * 0.998,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000.0 * (1.0 + 0.3 * np.sin(2.0 * np.pi * k / 17.0)),
            "amount": close * 1_000_000.0,
        }, index=self.index)
        frame["pre_close"] = frame["close"].shift(1).fillna(frame["close"].iloc[0])
        frame["price_adjust"] = "qfq"                    # 复权口径物化列（ATR/STD 需要）
        frame.attrs["adjust"] = "qfq"
        return frame


def default_symbols(markets) -> list:
    """按 meta['markets'] 推一组演示标的（没有匹配项时退回 A 股）。"""
    out = []
    for market in markets or []:
        symbol = _MARKET_SYMBOLS.get(str(market))
        if symbol and symbol not in out:
            out.append(symbol)
    return out or ["600519"]


def run_selftest(strategy_cls, symbols=None, params: dict = None, bars: int = BARS,
                 initial_cash: float = None, verbose: bool = True) -> dict:
    """用合成行情跑一遍回测并打印 meta / 信号条数（离线，不联网）。"""
    meta = dict(getattr(strategy_cls, "meta", {}) or {})
    syms = [str(s) for s in (symbols or default_symbols(meta.get("markets")))]
    fetcher = FakeFetcher(n=int(bars))
    start = fetcher.index[0].strftime("%Y-%m-%d")
    end = fetcher.index[-1].strftime("%Y-%m-%d")

    result = run_backtest(strategy_cls, params=params, symbols=syms, start=start,
                          end=end, fetcher=fetcher,
                          initial_cash=initial_cash if initial_cash is not None else 1_000_000)
    if verbose:
        _report(result, meta, syms, bars, start, end)
    return result


def _report(result: dict, meta: dict, syms: list, bars: int, start: str, end: str) -> None:
    strategy = result.get("strategy")
    filled = [o for o in result.get("trades", []) if o.get("status") == "filled"]
    rejected = result.get("rejected", [])
    metrics = result.get("metrics") or {}
    print("=" * 64)
    print(f"策略自检：{meta.get('name')}（{meta.get('display_name')}）"
          f" v{meta.get('version')}  markets={meta.get('markets')}")
    print(f"标的 {syms}  周期 {meta.get('periods')}  "
          f"预热 {getattr(strategy, 'warmup_bars', '?')} 根  author={meta.get('author')}")
    print(f"参数：{result.get('params')}")
    print("-" * 64)
    print(f"合成日线 {bars} 根：{start} → {end}（不联网）")
    print(f"信号（成交）{len(filled)} 笔；拒单 {len(rejected)} 笔")
    for direction in ("buy", "sell", "short", "cover"):
        count = sum(1 for o in filled if o.get("direction") == direction)
        if count:
            print(f"  {direction:<5} {count} 笔")
    print(f"总收益 {metrics.get('total_return', 0.0):+.2%}  "
          f"最大回撤 {metrics.get('max_drawdown', 0.0):.2%}  "
          f"夏普 {metrics.get('sharpe', 0.0):.2f}")
    if rejected:
        print(f"首条拒单原因：{rejected[0].get('reason')}")
    print("=" * 64)
