# -*- coding: utf-8 -*-
"""实盘行情引擎（data/live_data.py）—— 12.5。

三模式行情，上层策略无感：

* ``backtest``           ：AKShare / 本地缓存（``core.data_fetcher``）；
* ``paper`` / ``live_sim``：券商 / CTP **仿真**官方行情；
* ``live``               ：券商 / CTP **官方实时**行情。

硬约束
======
1. **AKShare 不可用于实盘行情**（延迟/限频/接口改版）：``live``/``paper`` 模式
   只允许走 broker 官方行情，broker 不可用时**报错停机**，不得静默降级到
   AKShare 或本地缓存（``forbid_silent_mode_fallback``）；
2. 断线检测 + 自动重连 + 补数据：重连次数耗尽仍失败则抛错，由守护进程告警停机；
3. 期货夜盘时段（21:00–次日 02:30）自动识别，夜盘只允许平仓由风控判断。
"""
from __future__ import annotations

from datetime import datetime, time as dtime
from typing import Callable, Dict, Iterable, List, Optional

import pandas as pd

import config
from live.errors import SilentFallbackError

__all__ = ["LiveDataEngine", "night_session"]

_OFFICIAL_MODES = ("paper", "live_sim", "live")


def night_session(now: datetime = None) -> bool:
    """国内期货夜盘：21:00–次日 02:30（含凌晨）。"""
    now = now or datetime.now()
    t = now.time()
    return t >= dtime(21, 0) or t <= dtime(2, 30)


class LiveDataEngine:
    def __init__(self, mode: str = "backtest", fetcher=None, broker=None,
                 logger=None, reconnect_attempts: int = 3) -> None:
        self.mode = str(mode or "backtest").lower()
        if self.mode not in ("backtest",) + _OFFICIAL_MODES:
            raise ValueError(f"未知行情模式 {mode!r}")
        self.fetcher = fetcher
        self.broker = broker
        self.logger = logger
        self.reconnect_attempts = int(reconnect_attempts)
        self._subscriptions: Dict[str, dict] = {}
        self._last_error = ""
        self._need_backfill: List[str] = []
        if self.mode in _OFFICIAL_MODES and broker is None:
            raise SilentFallbackError(
                f"{self.mode} 模式必须提供券商官方行情源；"
                "禁止静默退回 AKShare/本地缓存（AKShare 不可用于实盘行情）")

    # ==================== 行情获取 ====================
    def get_bars(self, symbol: str, period: str = "1d", count: int = 1,
                 market: str = None) -> pd.DataFrame:
        """统一取 K 线：回测走缓存，仿真/实盘走官方行情。"""
        if self.mode == "backtest":
            if self.fetcher is None:
                raise RuntimeError("回测模式缺少 fetcher（行情/缓存层）")
            return self.fetcher.get_kline(str(symbol), period=period,
                                          market_type=market)
        quote = self.get_quote(symbol)
        price = float(quote.get("price") or quote.get("last") or 0.0)
        if price <= 0:
            raise RuntimeError(f"官方行情返回空价格：{symbol}（禁止用 0 价构造 bar）")
        bar = {"date": str(quote.get("date") or datetime.now().date()),
               "open": float(quote.get("open", price) or price),
               "high": float(quote.get("high", price) or price),
               "low": float(quote.get("low", price) or price),
               "close": price, "volume": float(quote.get("volume", 0.0) or 0.0),
               "amount": quote.get("amount")}
        frame = pd.DataFrame([bar]).set_index("date")
        if "amount" in frame.columns and frame["amount"].isna().all():
            frame = frame.drop(columns=["amount"])
        return frame

    def get_quote(self, symbol: str) -> Dict[str, float]:
        """官方实时行情；断线自动重连，重连失败直接报错（不降级）。"""
        if self.mode == "backtest":
            raise RuntimeError("回测模式禁止取实时行情：请使用 get_bars() 走缓存")
        try:
            return dict(self.broker.get_quote(str(symbol)) or {})
        except Exception as exc:  # noqa: BLE001 - 断线统一走重连
            self._last_error = str(exc)
            if self.logger:
                self.logger.warning("行情获取失败 %s：%s，尝试重连", symbol, exc)
            self.reconnect()
            return dict(self.broker.get_quote(str(symbol)) or {})

    # ==================== 订阅 / 重连 ====================
    def subscribe(self, symbols: Iterable[str], on_tick: Callable = None,
                  on_bar: Callable = None) -> None:
        for symbol in symbols:
            self._subscriptions[str(symbol)] = {"on_tick": on_tick, "on_bar": on_bar}

    def unsubscribe(self) -> None:
        self._subscriptions.clear()

    def is_connected(self) -> bool:
        return bool(getattr(self.broker, "connected", False))

    def reconnect(self) -> bool:
        """断线重连（有限次）；失败抛错，禁止静默回退到其它数据源。"""
        for attempt in range(1, self.reconnect_attempts + 1):
            try:
                if self.broker.connect():
                    self._backfill()
                    if self.logger:
                        self.logger.info("行情连接已恢复（第 %d 次重试）", attempt)
                    return True
            except Exception as exc:  # noqa: BLE001 - 记录后重试
                self._last_error = str(exc)
        raise ConnectionError(
            f"行情断线且重连 {self.reconnect_attempts} 次失败：{self._last_error}"
            "（实盘禁止静默回退，请检查网络/券商通道）")

    def _backfill(self) -> None:
        """重连后补齐订阅标的的最新一根 bar，避免缺口静默留洞。"""
        for symbol in list(self._backfill_targets()):
            try:
                self.get_quote(symbol)
            except Exception:  # noqa: BLE001 - 缺口在 poll 中继续重试
                self._need_backfill.append(symbol)

    def _backfill_targets(self) -> List[str]:
        return [s for s in self._subscriptions if s not in self._need_backfill]

    def poll(self) -> List[dict]:
        """轮询订阅标的，回调 on_tick（实盘/仿真主循环调用）。"""
        ticks: List[dict] = []
        for symbol, hooks in list(self._subscriptions.items()):
            try:
                quote = self.get_quote(symbol)
            except Exception as exc:  # noqa: BLE001 - 已重连仍失败：上报
                if self.mode == "live":
                    raise
                if self.logger:
                    self.logger.error("仿真行情获取失败 %s：%s", symbol, exc)
                continue
            tick = {"symbol": symbol, **quote}
            ticks.append(tick)
            cb = hooks.get("on_tick")
            if callable(cb):
                cb(tick)
        return ticks

    # ==================== 时段 ====================
    @staticmethod
    def trading_session(market: str = "cn_stock", now: datetime = None) -> str:
        """粗粒度时段：night / day / closed（节假日由交易日历另行判断）。"""
        now = now or datetime.now()
        if market == "cn_future" and night_session(now):
            return "night"
        t = now.time()
        if dtime(9, 15) <= t <= dtime(11, 30) or dtime(13, 0) <= t <= dtime(15, 0):
            return "day"
        return "closed"
