"""示例策略 3/9：期货海龟趋势跟踪（国内/国际期货通用，多空双向）。

逻辑：
  - 20 日唐奇安通道：收盘价突破上轨开多、跌破下轨开空；
  - 10 日反向通道：跌破 10 日低点平多、突破 10 日高点平空；
  - ATR(20) 定仓位：单手风险 = ATR × 合约乘数，手数使单笔风险 <= 总权益 × risk_pct。

简化：单笔风险按 `capital`（默认与初始资金一致）估算，不随净值滚动；
合约乘数走参数，复权口径默认取全局 config.DEFAULT_ADJUST，
策略本身不判断交易日。
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from config import DEFAULT_ADJUST
from core import indicators as ind
from core.strategy import BaseStrategy


class FuturesTrendFollowing(BaseStrategy):
    """唐奇安通道突破 + ATR 仓位管理。"""

    meta = {
        "name": "futures_trend_following",
        "display_name": "期货海龟趋势跟踪",
        "markets": ["cn_future", "global_future"],
        "periods": ["1d"],
        "params": {
            "entry_window": 20,
            "exit_window": 10,
            "atr_window": 20,
            "risk_pct": 0.01,           # 单笔风险占总权益上限
            "multiplier": 10,           # 合约乘数（rb=10；其他品种按合约调整）
            "capital": 1_000_000.0,     # 权益基准（简化：不随净值滚动）
            "adjust": DEFAULT_ADJUST,   # 与全局默认口径一致；确需 qfq 请显式传参
            "max_lots": 100,
        },
        "description": "20 日唐奇安突破开多/开空，10 日反向突破平仓，ATR 仓位控制单笔风险 1%",
        "author": "quant-team",
        "version": "1.0",
        "warmup": [("ATR", {"n": 20})],
    }

    def on_bar(self, date, bars):
        entry = int(self.params["entry_window"])
        exit_n = int(self.params["exit_window"])
        atr_n = int(self.params["atr_window"])
        # ATR 是递归指标：序列前 required_bars-1 根会被置 NaN，
        # 所以必须请求「预热根数 + 通道窗口」，否则最后一个 ATR 也是 NaN。
        need = ind.required_bars("ATR", n=atr_n) + max(entry, exit_n) + 2
        for symbol in bars:
            if not self.is_warmup_ok(symbol):
                continue
            high = self.get_history(symbol, need, "high")
            low = self.get_history(symbol, need, "low")
            close = self.get_history(symbol, need, "close")
            frame = pd.DataFrame({"high": high, "low": low, "close": close})
            atr = ind.ATR(frame, n=atr_n, adjust=str(self.params.get("adjust", "qfq")))
            if not np.isfinite(atr.iloc[-1]) or float(atr.iloc[-1]) <= 0:
                continue
            price = float(close.iloc[-1])
            upper = float(high.iloc[-entry - 1:-1].max())
            lower = float(low.iloc[-entry - 1:-1].min())
            exit_high = float(high.iloc[-exit_n - 1:-1].max())
            exit_low = float(low.iloc[-exit_n - 1:-1].min())
            if not np.isfinite([upper, lower, exit_high, exit_low]).all():
                continue

            pos = self.get_position(symbol)
            if pos is None:
                lots = self._lots(float(atr.iloc[-1]))
                if lots <= 0:
                    continue
                if price > upper:
                    self.buy(symbol, lots, price)
                elif price < lower:
                    self.short(symbol, lots, price)
            elif pos.direction == "short":
                if price > exit_high and pos.available > 0:
                    self.cover(symbol, pos.available, price)
            elif pos.direction == "long":
                if price < exit_low and pos.available > 0:
                    self.sell(symbol, pos.available, price)

    def _lots(self, atr: float) -> int:
        multiplier = float(self.params.get("multiplier", 10) or 1)
        capital = float(self.params.get("capital", 1_000_000.0))
        risk = capital * float(self.params["risk_pct"])
        per_lot = atr * multiplier
        if per_lot <= 0:
            return 0
        lots = int(risk / per_lot)
        return max(min(lots, int(self.params.get("max_lots", 100))), 0)


if __name__ == "__main__":
    from strategies._selftest import run_selftest

    run_selftest(FuturesTrendFollowing, symbols=["rb2510"])
