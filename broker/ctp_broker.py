# -*- coding: utf-8 -*-
"""CTP 国内期货实盘对接（broker/ctp_broker.py）—— 12.4。

对接 OpenCTP（开源兼容 CTP 接口）+ 官方 CTP API，覆盖四大期货交易所 + 广期所。

* **SimNow 仿真预设**内置在 :data:`SIMNOW_PRESET`（24 小时服务，不用自己找地址）；
* **穿透测试辅助**见 :class:`PenetrationTestHelper`（AppID/AuthCode/产品信息自检）；
* 完整处理平今/平昨、保证金实时计算、今昨仓分别记录、涨跌停判断；
* 边界仍是 K5：只实现发单原语，决策全部在 ``live/live_trader.py::submit_order``。
"""
from __future__ import annotations

from typing import Dict, List, Optional

import config
from broker.base_broker import (ACCEPTED, FILLED, LIVE_TRADING_ENABLED,
                                 REJECTED, UNKNOWN, BrokerAdapter,
                                 BrokerCredentialError, BrokerOrder,
                                 LiveTradingDisabled)

__all__ = ["CTPBroker", "SIMNOW_PRESET", "PenetrationTestHelper"]

# SimNow 官方仿真前置（BrokerID 9999 / simnow_client_test / 全 0 AuthCode）
SIMNOW_PRESET = {
    "trade_front": "tcp://180.168.146.187:10130",
    "market_front": "tcp://180.168.146.187:10131",
    "broker_id": "9999",
    "app_id": "simnow_client_test",
    "auth_code": "0000000000000000",
    "product_info": "",
    "prod_code": "",
    "note": "SimNow 仿真环境 24 小时服务；实盘需替换为期货公司分配的前置与穿透参数",
}

_STATUS_MAP = {"accepted": ACCEPTED, "submitted": ACCEPTED, "reported": ACCEPTED,
               "filled": FILLED, "rejected": REJECTED, "canceled": "canceled",
               "cancelled": "canceled", "unknown": UNKNOWN}


class PenetrationTestHelper:
    """穿透式监管认证自检（AppID / AuthCode / 产品信息）。

    期货公司要求的三项参数：仿真可用默认值，**实盘必须是穿透测试后分配的正式值**。
    """

    REQUIRED_LIVE = ("app_id", "auth_code", "prod_code")

    def __init__(self, app_id: str, auth_code: str, prod_code: str = "",
                 product_info: str = "") -> None:
        self.params = {"app_id": str(app_id or ""), "auth_code": str(auth_code or ""),
                       "prod_code": str(prod_code or ""),
                       "product_info": str(product_info or "")}

    def check(self, live: bool = False) -> Dict[str, str]:
        """逐项返回 ok / missing / default（仿真默认值在实盘不可用）。"""
        out: Dict[str, str] = {}
        for key in ("app_id", "auth_code"):
            val = self.params.get(key, "")
            if not val:
                out[key] = "missing"
            elif live and (val == SIMNOW_PRESET[key]):
                out[key] = "default"
            else:
                out[key] = "ok"
        if live:
            out["prod_code"] = "ok" if self.params.get("prod_code") else "missing"
            out["product_info"] = "ok" if self.params.get("product_info") else "missing"
        return out

    def report(self, live: bool = False) -> dict:
        checks = self.check(live=live)
        bad = {k: v for k, v in checks.items() if v != "ok"}
        return {"ok": not bad, "checks": checks, "problems": bad,
                "hint": ("实盘穿透参数必须是期货公司穿透测试后分配的正式值；"
                         "SimNow 默认值只允许用于仿真")}


class CTPBroker(BrokerAdapter):
    """client 契约（CTP API 封装或注入假客户端）::

        client.login() -> bool
        client.account() / client.positions() / client.quote(symbol)
        client.order(client_order_id, symbol, direction, volume, price,
                     offset, order_type) -> {...}
        client.cancel(client_order_id) / client.orders() / client.trades()
    """

    name = "ctp"

    def __init__(self, trade_front: str = None, market_front: str = None,
                 broker_id: str = None, user_id: str = None, password: str = None,
                 app_id: str = None, auth_code: str = None, prod_code: str = None,
                 product_info: str = None, simnow: bool = True,
                 simulated: bool = None, client=None) -> None:
        preset = SIMNOW_PRESET if simnow else {}
        self.trade_front = str(trade_front if trade_front is not None
                               else (config.CTP_FRONT_ADDR_TRADE or preset.get("trade_front", "")))
        self.market_front = str(market_front if market_front is not None
                                else (config.CTP_FRONT_ADDR_MARKET
                                      or preset.get("market_front", "")))
        self.broker_id = str(broker_id if broker_id is not None
                             else (config.CTP_BROKER_ID or preset.get("broker_id", "")))
        self.user_id = str(config.CTP_USER_ID if user_id is None else user_id)
        self.password = str(config.CTP_PASSWORD if password is None else password)
        self.app_id = str(app_id if app_id is not None
                          else (config.CTP_APP_ID or preset.get("app_id", "")))
        self.auth_code = str(auth_code if auth_code is not None
                             else (config.CTP_AUTH_CODE or preset.get("auth_code", "")))
        self.prod_code = str(prod_code if prod_code is not None
                             else (config.CTP_PROD_CODE or preset.get("prod_code", "")))
        self.product_info = str(product_info if product_info is not None
                                else (config.CTP_PRODUCT_INFO
                                      or preset.get("product_info", "")))
        self.simnow = bool(simnow)
        self.simulated = bool(simnow if simulated is None else simulated)
        self.client = client
        self.connected = False
        self.live_ready = self.simulated or LIVE_TRADING_ENABLED

    # ==================== 连接 ====================
    @staticmethod
    def _load_sdk():
        for name in ("openctp", "ctp"):
            try:
                return __import__(name)  # 只允许 broker/ 内 import 期货 SDK
            except ImportError:
                continue
        raise RuntimeError("未安装 CTP SDK（openctp / ctp）：请先安装官方 API 或 OpenCTP")

    def require_credentials(self) -> None:
        missing = [n for n, v in (("CTP_FRONT_ADDR_TRADE", self.trade_front),
                                  ("CTP_FRONT_ADDR_MARKET", self.market_front),
                                  ("CTP_BROKER_ID", self.broker_id),
                                  ("CTP_USER_ID", self.user_id),
                                  ("CTP_PASSWORD", self.password))
                   if not str(v or "").strip()]
        if missing:
            raise BrokerCredentialError(
                f"CTP 凭证缺失：{', '.join(missing)}——请在 .env 文件中填写后重启")

    def connect(self) -> bool:
        self.require_credentials()
        if not self.simulated:
            report = PenetrationTestHelper(self.app_id, self.auth_code, self.prod_code,
                                           self.product_info).report(live=True)
            if not report["ok"]:
                raise BrokerCredentialError(
                    f"CTP 实盘穿透参数不合格：{report['problems']}——{report['hint']}")
        if self.client is None:
            self._load_sdk()
            raise RuntimeError("CTP 交易会话需在装有 CTP 前置网络的环境建立；"
                               "禁止在无会话时静默退回仿真/回测")
        if not self.client.login():
            raise ConnectionError("CTP 登录失败：检查前置地址/经纪商代码/账号密码")
        self.connected = True
        self.live_ready = self.simulated or LIVE_TRADING_ENABLED
        return True

    def disconnect(self) -> None:
        logout = getattr(self.client, "logout", None)
        if callable(logout):
            logout()
        self.connected = False

    # ==================== 查询 ====================
    def _client(self):
        if not self.connected or self.client is None:
            raise ConnectionError("CTP 未连接：先 connect()，禁止在断线状态取数/报单")
        return self.client

    def get_account(self) -> Dict[str, float]:
        acct = dict(self._client().account())
        acct.setdefault("margin_used", acct.get("margin", 0.0))
        return acct

    def get_positions(self) -> Dict[str, dict]:
        out = {}
        for symbol, pos in dict(self._client().positions()).items():
            data = dict(pos)
            today = float(data.get("today_volume", 0.0) or 0.0)
            yesterday = float(data.get("yesterday_volume", 0.0) or 0.0)
            data.setdefault("today_volume", today)
            data.setdefault("yesterday_volume", yesterday)
            data.setdefault("volume", today + yesterday)
            out[str(symbol)] = data
        return out

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
                "CTP 真实报单被拒：代码层/config 层 LIVE_TRADING_ENABLED 未同时开启")
        offset = self.offset_for(order.symbol, order.direction)
        try:
            raw = client.order(client_order_id=order.client_order_id,
                               symbol=order.symbol, direction=order.direction,
                               volume=float(order.volume), price=float(order.price),
                               offset=offset, order_type=order.order_type) or {}
        except TimeoutError as exc:
            order.status = UNKNOWN
            order.message = f"CTP 报单超时（状态未知，禁止盲目重发）：{exc}"
            return order
        order.status = _STATUS_MAP.get(str(raw.get("status", "")).lower(), UNKNOWN)
        order.broker_order_id = str(raw.get("order_id") or "")
        order.message = str(raw.get("message") or "")
        order.mode = order.mode or ("ctp_sim" if self.simulated else "live")
        return order

    def cancel_order(self, client_order_id: str) -> dict:
        return dict(self._client().cancel(str(client_order_id)) or {})

    # ==================== 期货规则原语 ====================
    def offset_for(self, symbol: str, direction: str) -> str:
        """根据今昨仓决定开平/平今/平昨（只做映射，不做决策）。"""
        if str(direction) in ("buy", "short"):
            return "open"
        pos = self.get_positions().get(str(symbol)) or {}
        today = float(pos.get("today_volume", 0.0) or 0.0)
        if today > 0:
            return "close_today"
        if float(pos.get("yesterday_volume", 0.0) or 0.0) > 0:
            return "close_yesterday"
        return "close"

    @staticmethod
    def margin_required(price: float, volume: float, multiplier: float = 1.0,
                        margin_rate: float = 0.10) -> float:
        """保证金实时计算：价格 × 手数 × 合约乘数 × 保证金率。"""
        return float(price) * float(volume) * float(multiplier) * float(margin_rate)

    @staticmethod
    def commission(price: float, volume: float, multiplier: float = 1.0,
                   open_fee: float = 0.0, close_fee: float = 0.0,
                   close_today_fee: float = 0.0,
                   close_today: bool = False, fee_rate: float = 0.0) -> float:
        """平今/平昨手续费自动区分：按手费率 + 按成交额费率（万分比）。"""
        rate = (close_today_fee if close_today
                else (close_fee if close_fee else open_fee))
        notional = abs(float(price) * float(volume) * float(multiplier))
        return abs(float(volume)) * float(rate) + notional * float(fee_rate)

    @staticmethod
    def at_price_limit(quote: dict, direction: str) -> bool:
        """涨跌停板判断：涨停买不进、跌停卖不出。"""
        q = dict(quote or {})
        last, up, down = q.get("last"), q.get("limit_up"), q.get("limit_down")
        if last is None:
            return False
        if direction in ("buy", "short") and up is not None:
            return float(last) >= float(up) - 1e-9
        if direction in ("sell", "cover") and down is not None:
            return float(last) <= float(down) + 1e-9
        return False

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
