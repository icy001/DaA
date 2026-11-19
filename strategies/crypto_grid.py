"""示例策略 6/9：加密货币网格（7×24 高抛低吸）。

逻辑：
  - 以首次见到价格为中心，在上下 `price_range_pct`（默认 ±20%）挂 `grid_num` 格；
  - 价格向下穿越网格 → 买入一格，向上穿越 → 卖出一格（止盈后自动补单）；
  - 价格跌出区间 → 重建网格（相当于重新定价，避免网格彻底失效）；
  - `self._grid_state` 记录每档位置，防止同一格重复挂单。

简化：按「穿越了几格就补几笔」成交，不模拟真正的挂单队列。
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.strategy import BaseStrategy


class CryptoGrid(BaseStrategy):
    """区间网格：跌一格买、涨一格卖。"""

    meta = {
        "name": "crypto_grid",
        "display_name": "加密货币网格",
        "markets": ["crypto"],
        "periods": ["1d"],
        "params": {
            "grid_num": 20,
            "price_range_pct": 0.2,
            "order_value": 3_000.0,        # 每格名义金额（USD）
            "max_position_value": 60_000.0,
            "qty_decimals": 6,
        },
        "description": "当前价上下 20% 分 20 格，价格穿越网格买卖，自动高抛低吸",
        "author": "quant-team",
        "version": "1.0",
        "warmup": [("MA", {"n": 20})],
    }

    def init(self):
        self._grid_state: dict = {}    # symbol → {lower, upper, step, last_index}
        self._invested: dict = {}      # symbol → 已投入名义金额

    def on_bar(self, date, bars):
        grid_num = max(int(self.params["grid_num"]), 2)
        rng = float(self.params["price_range_pct"])
        for symbol, bar in bars.items():
            if not self.is_warmup_ok(symbol):
                continue
            price = float(bar.get("close") or 0.0)
            if price <= 0:
                continue
            state = self._grid_state.get(symbol)
            if state is None:
                self._grid_state[symbol] = self._build_grid(price, grid_num, rng)
                continue

            lower, step = state["lower"], state["step"]
            if step <= 0:
                continue
            if price < lower or price > state["upper"]:
                self._grid_state[symbol] = self._build_grid(price, grid_num, rng)
                continue

            index = self._index_of(price, lower, step, grid_num)
            prev = state["last_index"]
            pos = self.get_position(symbol)

            if index < prev:                       # 向下穿越 → 补仓
                for _ in range(min(prev - index, grid_num)):
                    if not self._can_buy(symbol):
                        break
                    qty = self._qty(price)
                    if self.buy(symbol, qty, price).get("status") == "filled":
                        self._invested[symbol] = self._invested.get(symbol, 0.0) + qty * price
            elif index > prev and pos is not None and pos.available > 0:   # 向上穿越 → 止盈
                for _ in range(min(index - prev, grid_num)):
                    qty = min(self._qty(price), pos.available)
                    if qty <= 0:
                        break
                    if self.sell(symbol, qty, price).get("status") != "filled":
                        break
                    self._invested[symbol] = max(
                        self._invested.get(symbol, 0.0) - qty * price, 0.0)
                    pos = self.get_position(symbol)
                    if pos is None or pos.available <= 0:
                        break
            state["last_index"] = index

    # ---------- 内部工具 ----------
    def _build_grid(self, price: float, grid_num: int, rng: float) -> dict:
        lower = price * (1.0 - rng)
        upper = price * (1.0 + rng)
        step = (upper - lower) / grid_num
        return {"lower": lower, "upper": upper, "step": step,
                "last_index": self._index_of(price, lower, step, grid_num)}

    @staticmethod
    def _index_of(price: float, lower: float, step: float, grid_num: int) -> int:
        index = int((price - lower) // step)
        return max(min(index, grid_num - 1), 0)

    def _qty(self, price: float) -> float:
        decimals = int(self.params["qty_decimals"])
        qty = round(float(self.params["order_value"]) / price, decimals)
        return max(qty, 10.0 ** (-decimals))

    def _can_buy(self, symbol: str) -> bool:
        invested = self._invested.get(symbol, 0.0)
        return invested + float(self.params["order_value"]) <= float(
            self.params["max_position_value"])


if __name__ == "__main__":
    from strategies._selftest import run_selftest

    run_selftest(CryptoGrid, symbols=["BTC"])
