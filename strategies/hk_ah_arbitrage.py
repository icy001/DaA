"""示例策略 9/9：港股 AH 溢价配对（港股专属）。

逻辑：
  - `pairs` 把 A 股与对应 H 股成对传入（如 {"600519": "00700"}）；
  - AH 溢价 = A 股价格 /（H 股价格 × 汇率 fx）× 100；
  - 溢价 > 130 → H 股便宜，买 H（同时平掉 A 仓）；溢价 < 110 → A 股便宜，买回 A；
  - 汇率 fx 走参数（默认 0.92，即 1 HKD ≈ 0.92 CNY）。

价格来自 `self.get_history()`，不直接取数、不做汇率 API 调用。
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from core.strategy import BaseStrategy


class HKAHPremium(BaseStrategy):
    """AH 溢价配对交易。"""

    meta = {
        "name": "hk_ah_arbitrage",
        "display_name": "AH 溢价配对",
        "markets": ["hk_stock", "cn_stock"],
        "periods": ["1d"],
        "params": {
            "pairs": {"600519": "00700"},
            "fx": 0.92,                  # HKD → CNY
            "premium_buy_h": 130.0,      # 溢价高于此 → H 股便宜
            "premium_buy_a": 110.0,      # 溢价低于此 → A 股便宜
            "order_value": 100_000.0,
            "lot_size": 100,
        },
        "description": "AH 溢价 >130 买 H、<110 买回 A 的配对交易（含汇率换算）",
        "author": "quant-team",
        "version": "1.0",
        "warmup": [("MA", {"n": 5})],
    }

    def on_bar(self, date, bars):
        fx = float(self.params["fx"])
        if fx <= 0:
            return
        for a_symbol, h_symbol in (self.params.get("pairs") or {}).items():
            a_symbol, h_symbol = str(a_symbol), str(h_symbol)
            if a_symbol not in bars or h_symbol not in bars:
                continue
            if not self.is_warmup_ok(a_symbol) or not self.is_warmup_ok(h_symbol):
                continue
            a_close = float(self.get_history(a_symbol, 2, "close").iloc[-1])
            h_close = float(self.get_history(h_symbol, 2, "close").iloc[-1])
            if not np.isfinite(a_close) or not np.isfinite(h_close) or h_close <= 0:
                continue
            premium = a_close / (h_close * fx) * 100.0

            pos_a = self.get_position(a_symbol)
            pos_h = self.get_position(h_symbol)

            if premium > float(self.params["premium_buy_h"]) and pos_h is None:
                if pos_a is not None and pos_a.available > 0:
                    self.sell(a_symbol, pos_a.available, a_close)
                qty = self._qty(h_close)
                if qty > 0:
                    self.buy(h_symbol, qty, h_close)
            elif premium < float(self.params["premium_buy_a"]) and pos_a is None:
                if pos_h is not None and pos_h.available > 0:
                    self.sell(h_symbol, pos_h.available, h_close)
                qty = self._qty(a_close)
                if qty > 0:
                    self.buy(a_symbol, qty, a_close)

    def _qty(self, price: float) -> float:
        lot = max(int(self.params.get("lot_size", 100) or 1), 1)
        value = float(self.params.get("order_value", 100_000.0))
        if price <= 0:
            return 0.0
        return float(max(int(value / price / lot) * lot, lot))


if __name__ == "__main__":
    from strategies._selftest import run_selftest

    run_selftest(HKAHPremium, symbols=["600519", "00700"])
