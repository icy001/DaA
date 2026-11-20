# -*- coding: utf-8 -*-
"""完整实盘风控（risk/risk_manager.py）—— 12.6。

**所有订单先过风控再报单**：``live/live_trader.py::submit_order`` 在
``core/signal_gate.py`` 之后、发单之前调用 :meth:`LiveRiskManager.pre_order`，
不通过直接拒单，绝不把订单发到券商。

与 ``core/risk.py`` 的分工
==========================
* ``core/risk.py``     ：三引擎共用（回测/模拟盘/实盘）的仓位上限、总杠杆、
  日内亏损、最大回撤、黑天鹅、止损止盈——回测也必须有，否则结果不可比；
* ``risk/risk_manager.py``（本文件）：**仅实盘增量**的账户级/订单级/合规级风控，
  例如价格偏离、流动性、涨跌停、T+1、保证金、自成交、报撤频率。

参数唯一来源 ``config.RISK``（account / order / compliance 三段），
禁止在调用处硬编码阈值。
"""
from __future__ import annotations

import time
from collections import deque
from typing import Callable, Dict, List

import config
from core.risk import RiskManager, kind_of_market

__all__ = ["LiveRiskManager", "RiskVerdict"]

_OPEN = ("buy", "short")


class RiskVerdict(dict):
    """风控裁决结果；``ok=False`` 时附 layer/reason，调用处必须拒单。"""

    def __init__(self, ok: bool, layer: str = "", reason: str = "",
                 warnings: List[str] = None) -> None:
        super().__init__(ok=bool(ok), layer=str(layer), reason=str(reason),
                         warnings=list(warnings or []))

    def __bool__(self) -> bool:  # 兼容 if verdict 写法
        return bool(self["ok"])


class LiveRiskManager(RiskManager):
    """账户级 / 订单级 / 合规级三层实盘风控。"""

    def __init__(self, account, params: dict = None, logger=None,
                 now_fn: Callable[[], float] = None, state_file=None) -> None:
        super().__init__(account, params=params, logger=logger, state_file=state_file)
        raw = dict(getattr(config, "RISK", {}) or {})
        self.account_cfg = dict(raw.get("account") or {})
        self.order_cfg = dict(raw.get("order") or {})
        self.compliance_cfg = dict(raw.get("compliance") or {})
        self._now = now_fn or time.time
        self._day = None
        self._open_count = 0
        self._cancel_count = 0
        self._recent: deque = deque(maxlen=100)   # (ts, symbol, direction)

    # ==================== 换日 / 计数 ====================
    def new_day(self, date, equity: float = None, prices: Dict[str, float] = None) -> None:
        super().new_day(date, equity=equity, prices=prices)
        self._day = str(date)
        self._open_count = 0
        self._cancel_count = 0

    def record_order(self, symbol: str, direction: str) -> None:
        """报单被受理后登记（用于单日开仓次数与自成交判定）。"""
        if direction in _OPEN:
            self._open_count += 1
        self._recent.append((float(self._now()), str(symbol), str(direction)))

    def record_cancel(self) -> RiskVerdict:
        """撤单计数：超过单日上限（防被判频繁报撤单）直接拒。"""
        self._cancel_count += 1
        cap = int(self.account_cfg.get("max_cancel_count_per_day", 30) or 0)
        if cap and self._cancel_count > cap:
            return RiskVerdict(False, "account",
                               f"单日撤单次数 {self._cancel_count} > 上限 {cap}，"
                               "禁止继续报撤单（频繁报撤单会被交易所限制交易）")
        return RiskVerdict(True)

    # ==================== 主入口 ====================
    def pre_order(self, symbol: str, direction: str, volume: float,
                  price: float, market: str = None, bar: dict = None,
                  product_type: str = "cash") -> RiskVerdict:
        """报单前唯一裁决：账户级 → 订单级 → 合规级，任一层拒绝即拒单。"""
        symbol, direction = str(symbol), str(direction).lower()
        volume, price = float(volume or 0.0), float(price or 0.0)
        bar = dict(bar or {})
        market = str(market or config.detect_market_type(symbol))
        kind = kind_of_market(market)
        rule = config.get_market_config(market)
        multiplier = float(rule.get("multiplier", 1) or 1)
        notional = volume * price * multiplier
        warnings: List[str] = []

        checks = (
            self._check_account(symbol, direction, volume, price, notional, market),
            self._check_order(symbol, direction, volume, price, market, kind, rule, bar),
            self._check_compliance(symbol, direction, volume),
        )
        for verdict in checks:
            warnings.extend(verdict["warnings"])
            if not verdict["ok"]:
                verdict["warnings"] = warnings
                return verdict
        return RiskVerdict(True, warnings=warnings)

    # ==================== 账户级 ====================
    def _check_account(self, symbol, direction, volume, price, notional,
                       market) -> RiskVerdict:
        if direction in _OPEN:
            reason = self.check_open(symbol, volume, price, market=market)
            if reason:
                return RiskVerdict(False, "account", reason)
            equity = float(self.account.calc_equity({}) or 0.0)
            pct = float(self.account_cfg.get("max_position_pct_per_trade", 0.10))
            if equity > 0 and notional > equity * pct + 1e-6:
                return RiskVerdict(
                    False, "account",
                    f"单笔下单金额 {notional:,.0f} > 总资金 {equity:,.0f}×{pct:.0%}"
                    "（max_position_pct_per_trade）")
            cap = int(self.account_cfg.get("max_open_count_per_day", 20) or 0)
            if cap and self._open_count >= cap:
                return RiskVerdict(
                    False, "account",
                    f"单日开仓次数 {self._open_count} 已达上限 {cap}，禁止继续开仓")
        return RiskVerdict(True)

    # ==================== 订单级 ====================
    def _check_order(self, symbol, direction, volume, price, market,
                     kind, rule, bar) -> RiskVerdict:
        warnings: List[str] = []
        ref = float(bar.get("close") or bar.get("price") or 0.0)
        dev = float(self.order_cfg.get("price_deviation_pct_reject", 0.02))
        if ref > 0 and price > 0 and abs(price / ref - 1.0) > dev:
            return RiskVerdict(
                False, "order",
                f"价格偏离最新价 {abs(price / ref - 1.0):.2%} > {dev:.0%}"
                f"（{price} vs {ref}，防乌龙指）")

        amount = bar.get("amount")
        if direction in _OPEN and amount is not None:
            floor = float(self.order_cfg.get("liquidity_min_amount", 10_000_000) or 0)
            if floor and abs(float(amount)) < floor:
                return RiskVerdict(
                    False, "order",
                    f"流动性不足：成交额 {float(amount):,.0f} < {floor:,.0f}，禁止开仓")
        elif direction in _OPEN and amount is None:
            warnings.append("流动性未知：bar 无 amount 字段，未做流动性过滤")

        if self.order_cfg.get("block_zdt_reverse_open", True) and direction in _OPEN:
            if direction == "buy" and (bar.get("limit_up") or bar.get("at_limit_up")):
                return RiskVerdict(False, "order", "涨停板禁止买入（买不进且易被套）")
            if direction in ("sell", "short") and (
                    bar.get("limit_down") or bar.get("at_limit_down")):
                return RiskVerdict(False, "order", "跌停板禁止卖出/开空（卖不出）")

        if (direction in ("sell", "cover")
                and self.order_cfg.get("t_plus_one_enforce", True)
                and not self._is_t0(market, symbol, rule)):
            pos = self._position_of(symbol, direction)
            if pos is not None and float(pos.available) + 1e-9 < volume:
                return RiskVerdict(
                    False, "order",
                    f"T+1 限制：{symbol} 可卖 {float(pos.available):g} < 报单 {volume:g}"
                    "（当日买入不可卖）")

        if kind == "future" and direction in _OPEN and self.order_cfg.get("margin_check", True):
            required = notional * float(rule.get("margin_rate", 0.10) or 0.10)
            available = float(getattr(self.account, "cash", 0.0) or 0.0)
            if required > available + 1e-6:
                return RiskVerdict(
                    False, "order",
                    f"期货保证金不足：需 {required:,.0f} > 可用 {available:,.0f}，禁止开新仓")
        return RiskVerdict(True, warnings=warnings)

    # ==================== 合规级 ====================
    def _check_compliance(self, symbol, direction, volume) -> RiskVerdict:
        warnings: List[str] = []
        if self.compliance_cfg.get("block_self_trade", True):
            opposite = {"buy": {"sell"}, "sell": {"buy"},
                        "short": {"cover"}, "cover": {"short"}}.get(direction, set())
            now = float(self._now())
            for ts, sym, side in reversed(self._recent):
                if now - ts > 60:
                    break
                if sym == symbol and side in opposite:
                    return RiskVerdict(
                        False, "compliance",
                        f"疑似自成交：{symbol} 60 秒内已有反向委托 {side}，禁止同标的反向开平")
        cap = int(self.account_cfg.get("max_cancel_count_per_day", 30) or 0)
        ratio = float(self.compliance_cfg.get("frequent_order_warning_ratio", 0.8))
        if cap and self._cancel_count >= cap * ratio:
            warnings.append(
                f"频繁报撤单预警：撤单 {self._cancel_count}/{cap}（≥{ratio:.0%}）")
        if self.compliance_cfg.get("abnormal_order_reject", True) and volume <= 0:
            return RiskVerdict(False, "compliance", f"异常订单：数量 {volume:g} 非正")
        return RiskVerdict(True, warnings=warnings)

    # ==================== 工具 ====================
    def _position_of(self, symbol: str, direction: str):
        book = (self.account.positions if direction == "sell"
                else self.account.short_positions)
        return book.get(str(symbol))

    @staticmethod
    def _is_t0(market: str, symbol: str, rule: dict) -> bool:
        if market in ("cn_future", "global_future", "crypto", "forex"):
            return True
        explicit = rule.get("t_plus_0") or rule.get("t0")
        if explicit is not None:
            return bool(explicit)
        return False
