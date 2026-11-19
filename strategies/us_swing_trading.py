"""示例策略 4/9：美股波段（RSI + MACD 双确认）。

逻辑：
  - 买入：最近 `oversold_lookback` 根内 RSI(14) 曾 < 30（超卖），且当日 MACD 金叉；
  - 卖出：最近 `oversold_lookback` 根内 RSI(14) 曾 > 70（超买），且当日 MACD 死叉；
  - PDT：账户权益 < 25000 美元时，一周内日内回转交易不超过 3 次
    （策略层不查账户，权益由 `equity_hint` 参数注入；回测/模拟盘保持一致）。

说明：MACD 金叉天然滞后于 RSI 超卖，要求「同一天既超卖又金叉」几乎不会出现，
因此用最近 N 根的回看窗口（默认 10）表示「超卖后的金叉确认」。

指标全部来自 `core.indicators`，输入只吃 `self.get_history()` 的收盘序列。
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


class USSwingTrading(BaseStrategy):
    """RSI 超卖 + MACD 金叉买入，超买 + 死叉卖出。"""

    meta = {
        "name": "us_swing_trading",
        "display_name": "美股波段（RSI+MACD）",
        "markets": ["us_stock", "us_etf"],
        "periods": ["1d"],
        "params": {
            "rsi_n": 14,
            "rsi_buy": 30,
            "rsi_sell": 70,
            "oversold_lookback": 10,
            "macd_fast": 12,
            "macd_slow": 26,
            "macd_signal": 9,
            "order_qty": 100,
            "pdt_enabled": True,
            "pdt_max_day_trades": 3,
            "pdt_min_equity": 25_000.0,
            "equity_hint": 10_000.0,     # 策略层不查账户，用参数注入权益估计
        },
        "description": "RSI 超卖且 MACD 金叉买入、超买且死叉卖出，含 PDT 日内交易次数限制",
        "author": "quant-team",
        "version": "1.0",
        "warmup": [("RSI", {"n": 14}), ("MACD", {"slow": 26, "signal": 9})],
    }

    def init(self):
        self._day_trades: list = []      # 日内回转日期（用于 PDT 计数）
        self._open_date: dict = {}       # symbol → 开仓日

    def on_bar(self, date, bars):
        today = pd.Timestamp(date).normalize()
        self._day_trades = [d for d in self._day_trades if (today - d).days <= 7]

        need = max(ind.required_bars("RSI", n=int(self.params["rsi_n"])),
                   ind.required_bars("MACD", slow=int(self.params["macd_slow"]),
                                     signal=int(self.params["macd_signal"]))) + 2
        for symbol, bar in bars.items():
            if not self.is_warmup_ok(symbol):
                continue
            close = self.get_history(symbol, need, "close")
            rsi = ind.RSI(close, int(self.params["rsi_n"]))
            macd = ind.MACD(close, int(self.params["macd_fast"]),
                            int(self.params["macd_slow"]), int(self.params["macd_signal"]))
            if len(close) < 3 or not np.isfinite(macd["DIF"].iloc[-2]) \
                    or not np.isfinite(macd["DEA"].iloc[-2]) or not np.isfinite(rsi.iloc[-1]):
                continue
            dif_prev, dea_prev = float(macd["DIF"].iloc[-2]), float(macd["DEA"].iloc[-2])
            dif_now, dea_now = float(macd["DIF"].iloc[-1]), float(macd["DEA"].iloc[-1])
            price = float(bar.get("close") or 0.0)
            if price <= 0:
                continue

            pos = self.get_position(symbol)
            golden = dif_prev <= dea_prev and dif_now > dea_now
            death = dif_prev >= dea_prev and dif_now < dea_now
            lookback = max(int(self.params.get("oversold_lookback", 10)), 1)
            oversold = bool((rsi.iloc[-lookback:] < float(self.params["rsi_buy"])).any())
            overbought = bool((rsi.iloc[-lookback:] > float(self.params["rsi_sell"])).any())

            if golden and oversold and pos is None:
                if not self._pdt_blocked(today):
                    self.buy(symbol, float(self.params["order_qty"]), price)
                    self._open_date[symbol] = today
            elif death and overbought and pos is not None and pos.available > 0:
                self.sell(symbol, pos.available, price)
                if self._open_date.get(symbol) == today:
                    self._day_trades.append(today)

    def _pdt_blocked(self, today) -> bool:
        """资金 < 25000 且本周日内交易已达上限时，禁止再开仓。"""
        if not bool(self.params.get("pdt_enabled", True)):
            return False
        if float(self.params.get("equity_hint", 0.0)) >= float(self.params["pdt_min_equity"]):
            return False
        return len(self._day_trades) >= int(self.params["pdt_max_day_trades"])


if __name__ == "__main__":
    from strategies._selftest import run_selftest

    run_selftest(USSwingTrading, symbols=["AAPL"])
