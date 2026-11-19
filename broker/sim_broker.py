# -*- coding: utf-8 -*-
"""仿真券商适配器（broker/sim_broker.py）。

只用于测试与仿真盘：内存账本，无任何真实通道。支持两种异常注入：
* ``timeout_but_accept=True``：报单实际已受理，但返回 ``unknown``（K3 事故链）；
* ``reject_next``：下一次报单返回被拒（用于废单不重试）。
"""
from __future__ import annotations

import copy
from typing import Dict, List, Optional

from broker.base_broker import (ACCEPTED, FILLED, REJECTED, UNKNOWN,
                                 BrokerAdapter, BrokerOrder)

__all__ = ["SimBroker"]


class SimBroker(BrokerAdapter):
    name = "sim"

    def __init__(self, cash: float = 1_000_000.0,
                 positions: Dict[str, dict] = None,
                 timeout_but_accept: bool = False,
                 connected: bool = True) -> None:
        self.cash = float(cash)
        self.positions = {str(s): dict(p) for s, p in dict(positions or {}).items()}
        self.timeout_but_accept = bool(timeout_but_accept)
        self.connected = bool(connected)
        self.reject_next = False
        self.orders: List[BrokerOrder] = []
        self._by_id: Dict[str, BrokerOrder] = {}
        self.trades: List[dict] = []

    # ---------- 连接 ----------
    def connect(self) -> bool:
        self.connected = True
        return True

    def disconnect(self) -> None:
        self.connected = False

    def get_account(self) -> Dict[str, float]:
        return {"cash": self.cash, "equity": self.cash, "available": self.cash}

    def get_positions(self) -> Dict[str, dict]:
        return {s: dict(p) for s, p in self.positions.items()}

    def get_quote(self, symbol: str) -> Dict[str, float]:
        pos = self.positions.get(str(symbol)) or {}
        price = float(pos.get("last_price") or pos.get("avg_cost") or 10.0)
        return {"price": price, "last": price, "close": price,
                "bid": price, "ask": price}

    def set_positions(self, positions: Dict[str, dict]) -> None:
        self.positions = {str(s): dict(p) for s, p in dict(positions or {}).items()}

    # ---------- 发单原语 ----------
    def place_order(self, order: BrokerOrder) -> BrokerOrder:
        if self.reject_next:
            self.reject_next = False
            order.status = REJECTED
            order.message = "废单（仿真注入）"
            self.orders.append(order)
            self._by_id[order.client_order_id] = order
            return order
        stored = copy.copy(order)
        stored.status = ACCEPTED
        stored.broker_order_id = f"SIM{len(self._by_id) + 1:06d}"
        stored.message = "已受理"
        self.orders.append(stored)
        self._by_id[stored.client_order_id] = stored
        self.trades.append({"client_order_id": stored.client_order_id,
                            "symbol": stored.symbol, "direction": stored.direction,
                            "volume": float(stored.volume), "price": float(stored.price)})
        if self.timeout_but_accept:
            timeout = copy.copy(stored)
            timeout.status = UNKNOWN
            timeout.message = "报单超时（券商实际已受理，仿真注入）"
            return timeout
        return stored

    def cancel_order(self, client_order_id: str) -> dict:
        order = self._by_id.get(str(client_order_id))
        if order is None:
            return {"ok": False, "reason": "未找到委托"}
        order.status = "canceled"
        return {"ok": True, "client_order_id": client_order_id}

    def query_order(self, client_order_id: str) -> Optional[BrokerOrder]:
        return self._by_id.get(str(client_order_id))

    def get_orders(self) -> List[BrokerOrder]:
        return list(self.orders)

    def get_today_trades(self) -> List[dict]:
        return list(self.trades)

    # ---------- 测试辅助 ----------
    def mark_filled(self, client_order_id: str, volume: float = None,
                    price: float = None) -> BrokerOrder:
        order = self._by_id[str(client_order_id)]
        order.status = FILLED
        if volume is not None:
            order.volume = float(volume)
        if price is not None:
            order.price = float(price)
        return order
