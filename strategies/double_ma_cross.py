"""示例策略 1/9：双均线交叉（全市场通用基线）。

逻辑：短均线上穿长均线买入，下穿卖出。
只用 `self.get_history()` 拿收盘序列 + `core.indicators.MA()` 纯函数，
不直接取数、不下单到账户、不判断交易日。
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):       # 支持 `python strategies/double_ma_cross.py` 直接运行
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from core import indicators as ind
from core.strategy import BaseStrategy


class DoubleMACross(BaseStrategy):
    """短均线 / 长均线金叉死叉。"""

    meta = {
        "name": "double_ma_cross",
        "display_name": "双均线交叉",
        "markets": ["cn_stock", "cn_etf", "cn_convertible", "cn_future",
                    "us_stock", "hk_stock", "crypto", "forex"],
        "periods": ["1d"],
        "params": {
            "short_window": 5,
            "long_window": 20,
            "order_value": 100_000.0,   # 每次开仓的名义金额
            "lot_size": 100,            # 下单数量取整（A股 100、美股 1、期货 1）
        },
        "description": "短均线上穿长均线买入、下穿卖出（趋势行情基线策略）",
        "author": "quant-team",
        "version": "1.0",
        "warmup": [("MA", {"n": 20})],
    }

    def on_bar(self, date, bars):
        short_n = int(self.params["short_window"])
        long_n = int(self.params["long_window"])
        if long_n <= short_n:
            return
        for symbol, bar in bars.items():
            if not self.is_warmup_ok(symbol):
                continue
            close = self.get_history(symbol, long_n + 2, "close")
            fast = ind.MA(close, short_n)
            slow = ind.MA(close, long_n)
            if len(fast) < 2 or not np.isfinite(fast.iloc[-2]) or not np.isfinite(slow.iloc[-2]):
                continue
            prev_diff = float(fast.iloc[-2] - slow.iloc[-2])
            cur_diff = float(fast.iloc[-1] - slow.iloc[-1])
            if not np.isfinite(cur_diff):
                continue
            price = float(bar.get("close") or 0.0)
            if price <= 0:
                continue
            pos = self.get_position(symbol)
            if prev_diff <= 0.0 < cur_diff and pos is None:
                self.buy(symbol, self._qty(price), price)
            elif prev_diff >= 0.0 > cur_diff and pos is not None and pos.available > 0:
                self.sell(symbol, pos.available, price)

    def _qty(self, price: float) -> float:
        lot = max(int(self.params.get("lot_size", 100) or 1), 1)
        value = float(self.params.get("order_value", 100_000.0))
        return float(max(int(value / price / lot) * lot, lot))


if __name__ == "__main__":
    from strategies._selftest import run_selftest

    run_selftest(DoubleMACross, symbols=["600519"])
