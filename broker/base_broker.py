# -*- coding: utf-8 -*-
"""统一券商适配器基类（broker/base_broker.py）。

第 12 步开工前置 K5：**适配器只实现发单原语，不实现决策**。
闸门（预热/时效）、风控、对账、幂等、首单限额全部只允许在
``live/live_trader.py::submit_order`` 一处实现；否则每接一个券商就多一条
绕过闸门的报单通道。

硬约束
======
1. ``LIVE_TRADING_ENABLED = False``：代码层总开关，默认关闭；
   真实下单还需 config 层与 ``YES_CONFIRM_LIVE_TRADING`` 二次确认。
2. ``place_order`` 只接受已带 ``client_order_id`` 的 :class:`BrokerOrder`，
   不做任何合法性/风控判断——那是上层的事。
3. 状态未知（超时/断连）必须原样返回 ``status="unknown"``，
   由上层 ``query_order`` 复核后再决定是否重发（K3）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

__all__ = ["LIVE_TRADING_ENABLED", "BrokerOrder", "BrokerAdapter",
           "ACCEPTED", "REJECTED", "UNKNOWN", "FILLED", "CANCELED",
           "BrokerCredentialError", "LiveTradingDisabled"]

# 代码层实盘总开关：默认 False，禁止在适配器内部翻成 True
LIVE_TRADING_ENABLED = False


class BrokerCredentialError(RuntimeError):
    """关键凭证缺失：拒绝连接（12.17.5，fail-closed）。"""


class LiveTradingDisabled(ConnectionError):
    """真实报单通道未开启：代码层 LIVE_TRADING_ENABLED=False 时一律拒发。"""


ACCEPTED = "accepted"
REJECTED = "rejected"
UNKNOWN = "unknown"
FILLED = "filled"
CANCELED = "canceled"


@dataclass
class BrokerOrder:
    """跨层传递的报单原语（client_order_id 由上层幂等模块生成并落盘）。"""

    client_order_id: str
    symbol: str
    direction: str
    volume: float
    price: float
    order_type: str = "market"
    status: str = UNKNOWN
    broker_order_id: str = ""
    message: str = ""
    mode: str = ""

    def to_dict(self) -> dict:
        return {
            "client_order_id": self.client_order_id, "symbol": self.symbol,
            "direction": self.direction, "volume": float(self.volume),
            "price": float(self.price), "order_type": self.order_type,
            "status": self.status, "broker_order_id": self.broker_order_id,
            "message": self.message, "mode": self.mode,
        }


class BrokerAdapter:
    """统一接口：换券商只换适配器实例，上层决策层零改动。"""

    name = "base"

    def connect(self) -> bool:
        raise NotImplementedError

    def disconnect(self) -> None:
        raise NotImplementedError

    def get_account(self) -> Dict[str, float]:
        """返回 {cash, equity, available}（券商会话口径）。"""
        raise NotImplementedError

    def get_positions(self) -> Dict[str, dict]:
        """返回 {symbol: {"volume": float, ...}}（券商权威持仓）。"""
        raise NotImplementedError

    def get_quote(self, symbol: str) -> Dict[str, float]:
        """返回 {price/last/close, bid, ask, ...}（官方实时行情，12.5）。"""
        raise NotImplementedError

    def place_order(self, order: BrokerOrder) -> BrokerOrder:
        """发单原语：受理/拒绝/状态未知三选一，不做决策。"""
        raise NotImplementedError

    def cancel_order(self, client_order_id: str) -> dict:
        raise NotImplementedError

    def query_order(self, client_order_id: str) -> Optional[BrokerOrder]:
        """按 client_order_id 查单：K3 状态未知时先查这里再决定是否重发。"""
        raise NotImplementedError

    def get_orders(self) -> List[BrokerOrder]:
        raise NotImplementedError

    def get_today_trades(self) -> List[dict]:
        raise NotImplementedError
