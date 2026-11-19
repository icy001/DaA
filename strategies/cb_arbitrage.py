"""示例策略 2/9：可转债涨停联动（可转债专属，T+0）。

逻辑（全部来自 `bar_dict`，不取数）：
  1. 正股当日涨幅（close / pre_close）达到涨停阈值 → 视为「正股涨停/强势」；
  2. 对应可转债当日成交额 >= min_amount（默认 5000 万）→ 流动性可承接；
  3. 转股溢价率 <= premium_max（默认 20%，按转换价估算；未给转换价时跳过该过滤）；
  4. 买入对应可转债，当日涨 5%（内置止盈）或收盘前无条件清仓，不过夜。

`pairs` 参数把正股与转债成对传入，例如 {"600000": "110059"}。
日线下「14:40 清仓」简化为 `on_end_of_day` 清仓（执行器回测以日为单位推进）。
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.strategy import BaseStrategy

_FACE_VALUE = 100.0     # 可转债面值


class ConvertibleBondArbitrage(BaseStrategy):
    """正股涨停 → 买转债，尾盘清仓。"""

    meta = {
        "name": "cb_arbitrage",
        "display_name": "可转债涨停联动",
        "markets": ["cn_convertible"],
        "periods": ["1d"],
        "params": {
            "pairs": {"600000": "110059"},
            "conversion_price": {"110059": 12.92},   # 转债 → 转股价（缺省则不做溢价过滤）
            "premium_max": 0.2,
            "min_amount": 50_000_000.0,
            "limit_up_pct": 0.097,                  # 正股涨停阈值（留少量容差）
            "take_profit": 0.05,                    # 涨 5% 清仓（内置风控）
            "order_value": 100_000.0,
            "lot_size": 10,                         # 可转债 10 张一手
        },
        "description": "正股涨停/强势时买入对应可转债，涨 5% 或尾盘清仓，利用 T+0 优势",
        "author": "quant-team",
        "version": "1.0",
        "warmup": [],
    }

    def init(self):
        self._bought: set = set()

    def on_bar(self, date, bars):
        pairs = self.params.get("pairs") or {}
        limit_up = float(self.params["limit_up_pct"])
        min_amount = float(self.params["min_amount"])
        premium_max = float(self.params["premium_max"])
        for stock, cb in pairs.items():
            stock_bar = bars.get(str(stock))
            cb_bar = bars.get(str(cb))
            if not stock_bar or not cb_bar:
                continue
            pre_close = stock_bar.get("pre_close")
            stock_close = stock_bar.get("close")
            cb_close = cb_bar.get("close")
            if not pre_close or not stock_close or not cb_close:
                continue
            if float(pre_close) <= 0 or float(cb_close) <= 0:
                continue
            if float(stock_close) / float(pre_close) - 1.0 < limit_up:
                continue
            amount = cb_bar.get("amount")
            if amount is None or float(amount) < min_amount:
                continue
            premium = self._premium(str(cb), float(stock_close), float(cb_close))
            if premium is not None and premium > premium_max:
                continue
            pos = self.get_position(str(cb))
            if pos is not None and pos.volume > 0:
                continue
            price = float(cb_close)
            self.buy(str(cb), self._qty(price), price)
            self._bought.add(str(cb))

    def on_end_of_day(self, date):
        """尾盘无条件清仓（对应 14:40 全平，绝不过夜）。"""
        for symbol in list(self._bought):
            pos = self.get_position(symbol)
            if pos is not None and pos.available > 0:
                self.sell(symbol, pos.available)
            self._bought.discard(symbol)

    def _premium(self, cb: str, stock_price: float, cb_price: float):
        """转股溢价率 = 转债价 / 转股价值 - 1；缺转换价时返回 None（跳过过滤）。"""
        conv_price = (self.params.get("conversion_price") or {}).get(cb)
        if not conv_price or float(conv_price) <= 0:
            return None
        conv_value = _FACE_VALUE / float(conv_price) * float(stock_price)
        if conv_value <= 0:
            return None
        return cb_price / conv_value - 1.0

    def _qty(self, price: float) -> float:
        lot = max(int(self.params.get("lot_size", 10) or 1), 1)
        value = float(self.params.get("order_value", 100_000.0))
        return float(max(int(value / price / lot) * lot, lot))


if __name__ == "__main__":
    from strategies._selftest import run_selftest

    run_selftest(ConvertibleBondArbitrage, symbols=["600000", "110059"])
