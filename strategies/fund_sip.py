"""示例策略 7/9：基金智能定投（公募基金专属）。

逻辑（每周四定投）：
  - 收盘价低于 MA250 → 定投金额 × 1.5（越跌越买）；
  - 收盘价高于 MA250 → 定投金额 × 0.8；
  - 收盘价高于 MA250 的 120% → 停止定投（贵了不追）。

「每周四」用日期星期判断（执行器已经只喂交易日），不查交易日历。
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from core import indicators as ind
from core.strategy import BaseStrategy


class FundSIP(BaseStrategy):
    """周四定投 + 均线偏离加权。"""

    meta = {
        "name": "fund_sip",
        "display_name": "基金智能定投",
        "markets": ["cn_fund"],
        "periods": ["1d"],
        "params": {
            "base_amount": 1_000.0,
            "ma_window": 250,
            "below_ma_multiplier": 1.5,     # 低于均线 → 多买
            "above_ma_multiplier": 0.8,     # 高于均线 → 少买
            "stop_above_pct": 0.2,          # 高于均线 20% 停止定投
            "weekday": 3,                   # 0=周一 … 3=周四
        },
        "description": "每周四定投，跌破 MA250 加码 1.5 倍、高于均线 0.8 倍，高于均线 20% 停止",
        "author": "quant-team",
        "version": "1.0",
        "warmup": [("MA", {"n": 250})],
    }

    def init(self):
        self._invested = 0.0
        self._shares = 0.0

    def on_bar(self, date, bars):
        if pd.Timestamp(date).weekday() != int(self.params["weekday"]):
            return
        ma_n = int(self.params["ma_window"])
        for symbol, bar in bars.items():
            if not self.is_warmup_ok(symbol):
                continue
            close = self.get_history(symbol, ma_n + 1, "close")
            ma = ind.MA(close, ma_n)
            if len(ma) == 0 or not np.isfinite(ma.iloc[-1]):
                continue
            price = float(bar.get("close") or 0.0)
            if price <= 0:
                continue
            ma_now = float(ma.iloc[-1])
            if price > ma_now * (1.0 + float(self.params["stop_above_pct"])):
                continue
            if price < ma_now:
                amount = float(self.params["base_amount"]) * float(
                    self.params["below_ma_multiplier"])
            else:
                amount = float(self.params["base_amount"]) * float(
                    self.params["above_ma_multiplier"])
            qty = round(amount / price, 4)
            if qty <= 0:
                continue
            if self.buy(symbol, qty, price).get("status") == "filled":
                self._invested += amount
                self._shares += qty


if __name__ == "__main__":
    from strategies._selftest import run_selftest

    run_selftest(FundSIP, symbols=["519066"])
