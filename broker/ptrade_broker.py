# -*- coding: utf-8 -*-
"""PTrade 云端实盘对接（broker/ptrade_broker.py）—— 12.3。

对接恒生 PTrade 云端 API（适合不想本地挂机、要 7×24 稳定运行的用户：
云端定时任务 / 云端盯盘 / 云端下单）。

边界与 QMT 相同：**只实现发单原语**，闸门/风控/对账/幂等只在
``live/live_trader.py::submit_order``；SDK 只允许在 ``broker/`` 内 import。
真实报单需代码层与 config 层总开关同时开启。
"""
from __future__ import annotations

from typing import Dict, List, Optional

import config
from broker.base_broker import (ACCEPTED, FILLED, LIVE_TRADING_ENABLED,
                                 REJECTED, UNKNOWN, BrokerAdapter,
                                 BrokerCredentialError, BrokerOrder,
                                 LiveTradingDisabled)

__all__ = ["PTradeBroker"]

_STATUS_MAP = {"accepted": ACCEPTED, "submitted": ACCEPTED, "reported": ACCEPTED,
               "filled": FILLED, "rejected": REJECTED, "canceled": "canceled",
               "cancelled": "canceled", "unknown": UNKNOWN}


class PTradeBroker(BrokerAdapter):
    """client 契约（云端 SDK 或注入假客户端）::

        client.login() -> bool
        client.account() / client.positions() / client.quote(symbol)
        client.order(client_order_id, symbol, direction, volume, price, order_type)
        client.cancel(client_order_id) / client.orders() / client.trades()
        client.schedule(task, cron) -> dict   # 云端定时任务（可选）
    """

    name = "ptrade"

    def __init__(self, server: str = None, username: str = None,
                 password: str = None, account_id: str = None,
                 simulated: bool = True, client=None) -> None:
        self.server = str(config.PTRADE_SERVER if server is None else server)
        self.username = str(config.PTRADE_USERNAME if username is None else username)
        self.password = str(config.PTRADE_PASSWORD if password is None else password)
        self.account_id = str(config.PTRADE_ACCOUNT_ID if account_id is None else account_id)
        self.simulated = bool(simulated)
        self.client = client
        self.connected = False
        self.live_ready = self.simulated or LIVE_TRADING_ENABLED

    # ==================== 连接 ====================
    @staticmethod
    def _load_sdk():
        try:  # 只允许 broker/ 内 import 券商 SDK
            import ths_ptrade  # type: ignore  # noqa: F401
            return ths_ptrade
        except ImportError as exc:
            raise RuntimeError(
                "未安装 PTrade SDK（ths_ptrade）：请使用券商分配的 PTrade 云端环境"
            ) from exc

    def require_credentials(self) -> None:
        missing = [n for n, v in (("PTRADE_SERVER", self.server),
                                  ("PTRADE_USERNAME", self.username),
                                  ("PTRADE_PASSWORD", self.password),
                                  ("PTRADE_ACCOUNT_ID", self.account_id))
                   if not str(v or "").strip()]
        if missing:
            raise BrokerCredentialError(
                f"PTrade 凭证缺失：{', '.join(missing)}——请在 .env 文件中填写后重启")

    def connect(self) -> bool:
        self.require_credentials()
        if self.client is None:
            self._load_sdk()
            raise RuntimeError(
                "PTrade 云端会话需由券商分配的运行环境建立；"
                "禁止在无会话时静默退回本地仿真/回测")
        ok = self.client.login()
        self.connected = bool(ok)
        if not self.connected:
            raise ConnectionError("PTrade 云端登录失败：检查网络/账号/券商授权")
        self.live_ready = self.simulated or LIVE_TRADING_ENABLED
        return True

    def disconnect(self) -> None:
        logger_out = getattr(self.client, "logout", None)
        if callable(logger_out):
            logger_out()
        self.connected = False

    # ==================== 查询 ====================
    def _client(self):
        if not self.connected or self.client is None:
            raise ConnectionError("PTrade 未连接：先 connect()，禁止在断线状态取数/报单")
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
        if not self.simulated and not (LIVE_TRADING_ENABLED
                                      and bool(config.LIVE_TRADING_ENABLED)):
            raise LiveTradingDisabled(
                "PTrade 真实报单被拒：代码层/config 层 LIVE_TRADING_ENABLED 未同时开启")
        try:
            raw = client.order(client_order_id=order.client_order_id,
                               symbol=order.symbol, direction=order.direction,
                               volume=float(order.volume), price=float(order.price),
                               order_type=order.order_type) or {}
        except TimeoutError as exc:
            order.status = UNKNOWN
            order.message = f"PTrade 报单超时（状态未知，禁止盲目重发）：{exc}"
            return order
        order.status = _STATUS_MAP.get(str(raw.get("status", "")).lower(), UNKNOWN)
        order.broker_order_id = str(raw.get("order_id") or "")
        order.message = str(raw.get("message") or "")
        order.mode = order.mode or ("ptrade_sim" if self.simulated else "live")
        return order

    def cancel_order(self, client_order_id: str) -> dict:
        return dict(self._client().cancel(str(client_order_id)) or {})

    # ==================== 云端能力（原语） ====================
    def schedule(self, task: str, cron: str) -> dict:
        """注册云端定时任务（云端盯盘/定时下单），不做任何策略决策。"""
        fn = getattr(self._client(), "schedule", None)
        if not callable(fn):
            return {"ok": False, "reason": "该 PTrade 会话不支持云端定时任务"}
        return dict(fn(task, cron) or {})

    @staticmethod
    def _to_order(raw: dict) -> BrokerOrder:
        return BrokerOrder(
            client_order_id=str(raw.get("client_order_id", "")),
            symbol=str(raw.get("symbol", "")), direction=str(raw.get("direction", "")),
            volume=float(raw.get("volume", 0.0) or 0.0),
            price=float(raw.get("price", 0.0) or 0.0),
            status=_STATUS_MAP.get(str(raw.get("status", "")).lower(), UNKNOWN),
            broker_order_id=str(raw.get("order_id") or ""),
            message=str(raw.get("message") or ""))
