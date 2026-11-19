# -*- coding: utf-8 -*-
"""QMT 本地实盘对接（broker/qmt_broker.py）—— 12.2。

对接迅投 QMT 的 ``xtquant`` 官方 API，覆盖 A股个股 / ETF / 可转债 / REITs / 场内基金。

**边界（K5）**：本文件只实现发单原语（connect / 账户 / 持仓 / 行情 / 报单 / 撤单 /
查单），不做任何闸门、风控、对账、幂等决策——那些只在
``live/live_trader.py::submit_order`` 一处实现。SDK 只允许在 ``broker/`` 内 import。

三种连接模式
============
* ``mini``       ：普通投资者极简模式；
* ``standard``   ：标准客户端全功能；
* ``simulation`` ：QMT 自带模拟盘（零风险，允许在代码层总开关关闭时发单）。

真实报单（mini/standard）要求 **代码层 ``LIVE_TRADING_ENABLED`` 与 config 层
``LIVE_TRADING_ENABLED`` 同时为 True**，否则抛 :class:`LiveTradingDisabled`。
"""
from __future__ import annotations

from typing import Dict, List, Optional

import config
from broker.base_broker import (ACCEPTED, FILLED, LIVE_TRADING_ENABLED,
                                 REJECTED, UNKNOWN, BrokerAdapter,
                                 BrokerCredentialError, BrokerOrder,
                                 LiveTradingDisabled)

__all__ = ["QMTBroker", "QMT_MODES"]

QMT_MODES = ("mini", "standard", "simulation")
_STATUS_MAP = {"accepted": ACCEPTED, "submitted": ACCEPTED, "reported": ACCEPTED,
               "filled": FILLED, "rejected": REJECTED, "canceled": "canceled",
               "cancelled": "canceled", "unknown": UNKNOWN}


class QMTBroker(BrokerAdapter):
    """client 契约（可注入假客户端做离线测试）::

        client.account() -> {"cash":..., "equity":..., "available":...}
        client.positions() -> {symbol: {"volume":..., "available":..., "avg_cost":...}}
        client.quote(symbol) -> {"price":..., "bid":..., "ask":...}
        client.order(client_order_id, symbol, direction, volume, price, order_type)
            -> {"status": "accepted"|"rejected"|"unknown", "order_id": ..., "message": ...}
        client.cancel(client_order_id) -> {"ok": bool, "message": str}
        client.orders() -> [dict]        client.trades() -> [dict]
    """

    name = "qmt"

    def __init__(self, account_id: str = None, password: str = None,
                 path: str = None, mode: str = None, session_id: int = None,
                 broker_type: str = None, client=None) -> None:
        self.path = str(config.QMT_PATH if path is None else path)
        self.account_id = str(config.QMT_ACCOUNT_ID if account_id is None else account_id)
        self.password = str(config.QMT_PASSWORD if password is None else password)
        self.session_id = int(config.QMT_SESSION_ID if session_id is None else session_id)
        self.mode = str(config.QMT_MODE if mode is None else mode).lower()
        self.broker_type = str(config.QMT_BROKER_TYPE if broker_type is None else broker_type)
        self.client = client
        self.connected = False
        self.live_ready = self.mode == "simulation" or LIVE_TRADING_ENABLED

    # ==================== 连接 ====================
    @staticmethod
    def _load_sdk():
        try:  # 只允许 broker/ 内 import 券商 SDK
            import xtquant.xttrader as xttrader
            import xtquant.xttype as xttype
            return xttrader, xttype
        except ImportError as exc:
            raise RuntimeError(
                "未安装 QMT SDK（xtquant）：请先安装 QMT 客户端并在其 Python 环境运行"
            ) from exc

    def require_credentials(self) -> None:
        """12.17.5：关键字段缺失直接拒绝启动，禁止用空字符串去连接。"""
        missing = [n for n, v in (("QMT_PATH", self.path),
                                  ("QMT_ACCOUNT_ID", self.account_id),
                                  ("QMT_PASSWORD", self.password))
                   if not str(v or "").strip()]
        if missing:
            raise BrokerCredentialError(
                f"QMT 凭证缺失：{', '.join(missing)}——请在 .env 文件中填写后重启")

    def connect(self) -> bool:
        self.require_credentials()
        if self.mode not in QMT_MODES:
            raise ValueError(f"QMT_MODE 只允许 {list(QMT_MODES)}，收到 {self.mode!r}")
        if self.client is None:
            self._load_sdk()
            raise RuntimeError(
                "QMT 会话需在安装 QMT 客户端的机器上建立（xtquant 只提供本地会话）；"
                "禁止在无会话时静默退回仿真/回测")
        self.connected = True
        self.live_ready = self.mode == "simulation" or LIVE_TRADING_ENABLED
        return True

    def disconnect(self) -> None:
        self.connected = False

    # ==================== 查询 ====================
    def _client(self):
        if not self.connected or self.client is None:
            raise ConnectionError("QMT 未连接：先 connect()，禁止在断线状态取数/报单")
        return self.client

    def get_account(self) -> Dict[str, float]:
        return dict(self._client().account())

    def get_positions(self) -> Dict[str, dict]:
        return {str(s): dict(p) for s, p in dict(self._client().positions()).items()}

    def get_quote(self, symbol: str) -> Dict[str, float]:
        return dict(self._client().quote(str(symbol)))

    def get_orders(self) -> List[BrokerOrder]:
        return [self._to_order(dict(o)) for o in (self._client().orders() or [])]

    def get_today_trades(self) -> List[dict]:
        return [dict(t) for t in (self._client().trades() or [])]

    def query_order(self, client_order_id: str) -> Optional[BrokerOrder]:
        for raw in self._client().orders() or []:
            if str(raw.get("client_order_id")) == str(client_order_id):
                return self._to_order(dict(raw))
        return None

    # ==================== 发单原语 ====================
    def place_order(self, order: BrokerOrder) -> BrokerOrder:
        client = self._client()
        if self.mode != "simulation" and not (LIVE_TRADING_ENABLED
                                              and bool(config.LIVE_TRADING_ENABLED)):
            raise LiveTradingDisabled(
                "QMT 真实报单被拒：代码层 LIVE_TRADING_ENABLED=False / "
                "config.LIVE_TRADING_ENABLED=False（双层防护，需显式开启并二次确认）")
        try:
            raw = client.order(client_order_id=order.client_order_id,
                               symbol=order.symbol, direction=order.direction,
                               volume=float(order.volume), price=float(order.price),
                               order_type=order.order_type) or {}
        except TimeoutError as exc:  # 状态未知：原样上交，由上层先查券商
            order.status = UNKNOWN
            order.message = f"QMT 报单超时（状态未知，禁止盲目重发）：{exc}"
            return order
        order.status = _STATUS_MAP.get(str(raw.get("status", "")).lower(), UNKNOWN)
        order.broker_order_id = str(raw.get("order_id") or "")
        order.message = str(raw.get("message") or "")
        order.mode = order.mode or self.mode
        return order

    def cancel_order(self, client_order_id: str) -> dict:
        return dict(self._client().cancel(str(client_order_id)) or {})

    # ==================== A股报单规则原语（不做决策） ====================
    @staticmethod
    def min_order_volume(symbol: str) -> int:
        code = str(symbol)
        if code.startswith("11") or code.startswith("113") or code.startswith("12"):
            return 10          # 可转债：10 张
        if code.startswith("688"):
            return 200         # 科创板：200 股起、1 股递增
        return 100             # 主板/创业板/ETF：100 股（份）

    @staticmethod
    def price_cage(symbol: str, price: float, last: float) -> float:
        """科创板/创业板限价单 ±2% 价格笼子（超出则夹到边界）。"""
        if str(symbol).startswith(("688", "300")) and last and last > 0:
            low, high = last * 0.98, last * 1.02
            return round(min(max(float(price), low), high), 3)
        return float(price)

    @staticmethod
    def available_volume(position: dict) -> float:
        """T+1 可用数量：优先券商可用，其次 volume - frozen。"""
        pos = dict(position or {})
        if pos.get("available") is not None:
            return float(pos.get("available") or 0.0)
        return max(float(pos.get("volume", 0.0) or 0.0)
                   - float(pos.get("frozen_volume", 0.0) or 0.0), 0.0)

    @staticmethod
    def _to_order(raw: dict) -> BrokerOrder:
        return BrokerOrder(
            client_order_id=str(raw.get("client_order_id", "")),
            symbol=str(raw.get("symbol", "")), direction=str(raw.get("direction", "")),
            volume=float(raw.get("volume", 0.0) or 0.0),
            price=float(raw.get("price", 0.0) or 0.0),
            status=_STATUS_MAP.get(str(raw.get("status", "")).lower(), UNKNOWN),
            broker_order_id=str(raw.get("order_id") or raw.get("broker_order_id") or ""),
            message=str(raw.get("message") or ""))
