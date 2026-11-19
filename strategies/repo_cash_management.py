"""示例策略 8/9：国债逆回购自动扫单（现金管理）。

逻辑：
  - 每日收盘前（参数 trade_time="14:50"，日线上对应当日最后一根 bar）
    检查账户闲置资金，> 1000 元就买入当日利率最高的逆回购；
  - 周四优先买 1 天期（吃 3 天利息）；
  - bar 的 close 当作该品种的**年化利率（%）**近似 —— 逆回购没有 K 线涨跌，
    这里不取数、只用执行器喂进来的 bar；
  - 闲置资金用 `self.account.cash` 判断（允许的账户查询，不是下单）。

简化：轻量执行器不结算逆回购到期本息，因此可用资金只减不增，
买入到闲置资金不足 1000 元后自然停止；实盘由账户层按到期日回款。
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from core.strategy import BaseStrategy


class RepoCashManagement(BaseStrategy):
    """闲置资金买逆回购。"""

    meta = {
        "name": "repo_cash_management",
        "display_name": "国债逆回购扫单",
        "markets": ["cn_reverse_repo"],
        "periods": ["1d"],
        "params": {
            "min_idle": 1_000.0,
            "reserve_pct": 0.2,          # 预留比例，避免把明天要买股票的钱锁死
            "repo_symbols": ["131810", "131811", "131800"],   # 深市 1/2/3 天期
            "prefer_1day_symbol": "131810",
            "trade_time": "14:50",
        },
        "description": "每日尾盘把闲置资金买入利率最高的逆回购，周四优先 1 天期",
        "author": "quant-team",
        "version": "1.0",
        "warmup": [],
    }

    def on_bar(self, date, bars):
        # 已完成/持有中的品种不再买（轻量执行器不结算到期，避免同一代码仓位被覆盖）
        candidates = [s for s in self.params["repo_symbols"]
                      if s in bars and self.get_position(s) is None]
        if not candidates:
            return
        rates = {}
        for symbol in candidates:
            close = bars[symbol].get("close")
            if close is not None and float(close) > 0:
                rates[symbol] = float(close)
        if not rates:
            return

        cash = float(self.account.cash)
        reserve = max(float(self.params["min_idle"]), cash * float(self.params["reserve_pct"]))
        idle = cash - reserve
        if idle < float(self.params["min_idle"]):
            return

        prefer = str(self.params["prefer_1day_symbol"])
        is_thursday = pd.Timestamp(date).weekday() == 3
        if is_thursday and prefer in rates:
            symbol = prefer
        else:
            symbol = max(rates, key=rates.get)

        lot = 100_000 if symbol.startswith("204") else 1_000   # 沪市 10 万起、深市 1000 起
        amount = int(idle // lot) * lot
        if amount < lot:
            return
        self.sell(symbol, float(amount), rates[symbol])


if __name__ == "__main__":
    from strategies._selftest import run_selftest

    run_selftest(RepoCashManagement, symbols=["131810", "131811", "131800"])
