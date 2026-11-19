"""引擎无关的风控（core/risk.py）

第 7 步开工前置 D3：单票仓位上限、总杠杆上限、日内亏损上限、最大回撤熔断、
黑天鹅保护、止损/止盈这些规则只允许有**一份实现**。回测（core/backtester.py）、
模拟盘（core/paper_trader.py）、实盘引擎共用，`config.RISK` 为唯一参数源，
策略 params 只做显式覆盖。

为什么必须共用：回测没有风控、模拟盘有风控，两者结果天然不可比，
第 7 步「模拟盘—回测偏差 > 5% 告警」会被已知结构性差异反复触发（追幻影）。

规则：
  1) 单票仓位上限：单标的敞口 ≤ equity × max_single_symbol_pct；
  2) 总杠杆上限：按品种（stock/future/forex/crypto）取 max_leverage；
  3) 日内亏损上限：当日权益较日初回撤 ≥ daily_loss_pct_stop → 停止开仓；
  4) 最大回撤熔断：权益较历史峰值回撤 ≥ max_drawdown_pct_stop → 停止开仓；
  5) 黑天鹅保护：单根 bar 相对前收跳空 ≥ black_swan_gap_pct → 强制平掉该标的；
  6) 止损/止盈：按持仓成本触发，交由执行器发平仓单（开严平宽，平仓不过预热闸门）。

本模块只产出「拒单原因 / 强制平仓指令」，不直接改账户；下单仍统一收口
`TradingAccount.place_order`，保证风控与 T+1 / 涨跌停 / 预热闸门的执行顺序一致。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

import config

__all__ = ["RiskManager", "risk_config", "kind_of_market"]


def risk_config() -> dict:
    """config.RISK["account"] 的浅拷贝（唯一参数源）。"""
    return dict((getattr(config, "RISK", {}) or {}).get("account", {}) or {})


def kind_of_market(market: str) -> str:
    if market in ("cn_future", "global_future"):
        return "future"
    if market == "forex":
        return "forex"
    if market == "crypto":
        return "crypto"
    return "stock"


class RiskManager:
    """三引擎共用的风控裁决器。"""

    def __init__(self, account, params: dict = None, logger: logging.Logger = None):
        base = risk_config()
        params = dict(params or {})
        self.account = account
        self.logger = logger or getattr(account, "logger", None) or logging.getLogger("risk")

        self.max_single_symbol_pct = float(params.get(
            "max_single_symbol_pct", base.get("max_single_symbol_pct", 0.20)))
        self.max_single_industry_pct = float(params.get(
            "max_single_industry_pct", base.get("max_single_industry_pct", 0.30)))
        self.max_leverage = dict(params.get("max_leverage")
                                 or base.get("max_leverage") or {"stock": 1.0})
        self.daily_loss_pct_stop = float(params.get(
            "daily_loss_pct_stop", base.get("daily_loss_pct_stop", 0.05)))
        self.max_drawdown_pct_stop = float(params.get(
            "max_drawdown_pct_stop", base.get("max_drawdown_pct_stop", 0.10)))
        self.black_swan_gap_pct = float(params.get(
            "black_swan_gap_pct", base.get("black_swan_gap_pct", 0.10)))
        self.stop_loss = params.get("stop_loss")
        self.take_profit = params.get("take_profit")
        self.blacklist = {str(x) for x in (params.get("blacklist") or ())}

        self._day = None
        self._day_start_equity: Optional[float] = None
        self._peak_equity: Optional[float] = None
        self._prev_prices: Dict[str, float] = {}
        self.halted = False
        self.halt_reason = ""

    # ==================== 权益与熔断 ====================

    def on_bar(self, date, prices: Dict[str, float]) -> List[dict]:
        """每根 bar 开始调用：更新日初权益/峰值，返回需要强制平仓的指令列表。"""
        prices = {str(s): float(p) for s, p in dict(prices or {}).items()
                  if p is not None and float(p) > 0}
        equity = float(self.account.calc_equity(prices))
        if self._day != date:
            self._day = date
            self._day_start_equity = equity
        self._peak_equity = max(self._peak_equity or equity, equity)
        self._update_halt(equity)

        actions = self._black_swan_actions(prices)
        actions.extend(self._stop_loss_actions(prices))
        self._prev_prices = dict(prices)
        return actions

    def _update_halt(self, equity: float) -> None:
        if self.halted:
            return
        if self._day_start_equity and self._day_start_equity > 0:
            loss = equity / self._day_start_equity - 1.0
            if loss <= -abs(self.daily_loss_pct_stop):
                self._halt(f"日内亏损 {loss:.2%} 触及上限 {self.daily_loss_pct_stop:.2%}，停止开仓")
                return
        if self._peak_equity and self._peak_equity > 0:
            drawdown = equity / self._peak_equity - 1.0
            if drawdown <= -abs(self.max_drawdown_pct_stop):
                self._halt(f"权益回撤 {drawdown:.2%} 触及熔断线 "
                           f"{self.max_drawdown_pct_stop:.2%}，停止开仓")

    def _halt(self, reason: str) -> None:
        self.halted = True
        self.halt_reason = reason
        self.logger.warning("风控熔断：%s", reason)

    def reset_halt(self) -> None:
        """换日/人工复位后允许重新开仓（回测结束/新交易日由引擎决定是否调用）。"""
        self.halted = False
        self.halt_reason = ""

    def new_day(self, date, equity: float = None, prices: Dict[str, float] = None) -> None:
        """显式换日：重置日内亏损基准并解除前一日熔断（回撤熔断仍按峰值重算）。"""
        self._day = date
        if equity is None:
            equity = float(self.account.calc_equity(prices or {}))
        self._day_start_equity = float(equity)
        self.reset_halt()

    # ==================== 开仓裁决 ====================

    def check_open(self, symbol: str, volume: float, price: float = None,
                   market: str = None) -> Optional[str]:
        """开仓前风控；返回拒单原因，放行返回 None。"""
        if self.halted:
            return self.halt_reason or "风控熔断中，禁止开仓"
        volume = float(volume)
        if volume <= 0:
            return f"下单数量必须为正，收到 {volume}"
        px = price
        if px is None or float(px) <= 0:
            return "无法确定成交价，拒绝开仓（禁止用 0 或空价估算仓位）"
        px = float(px)

        market = market or config.detect_market_type(str(symbol))
        rule = config.get_market_config(market)
        multiplier = float(rule.get("multiplier", 1) or 1)
        notional = volume * px * multiplier
        equity = float(self.account.calc_equity({}))
        if equity <= 0:
            return "账户权益 <= 0，拒绝开仓"

        exposure = self.symbol_exposure(symbol) + notional
        cap = self.max_single_symbol_pct * equity
        if exposure > cap + 1e-6:
            return (f"单标的持仓超限：{symbol} 敞口 {exposure:,.0f} > "
                    f"总权益 {equity:,.0f}×{self.max_single_symbol_pct:.0%}")

        kind = kind_of_market(market)
        max_lev = float(self.max_leverage.get(kind, 1.0))
        total_exposure = self.total_exposure() + notional
        if total_exposure > max_lev * equity + 1e-6:
            return (f"总杠杆超限：{kind} 敞口 {total_exposure:,.0f} > "
                    f"权益 {equity:,.0f}×{max_lev:.1f}")
        return None

    def is_blacklisted(self, symbol: str, bar: dict = None) -> bool:
        if str(symbol) in self.blacklist:
            return True
        bar = bar or {}
        return bool(bar.get("is_delisted") or bar.get("is_st") or bar.get("is_suspended"))

    # ==================== 强制平仓 ====================

    def _black_swan_actions(self, prices: Dict[str, float]) -> List[dict]:
        actions = []
        gap = abs(float(self.black_swan_gap_pct))
        if gap <= 0:
            return actions
        for symbol, px in prices.items():
            prev = self._prev_prices.get(symbol)
            if not prev or prev <= 0:
                continue
            change = px / prev - 1.0
            if abs(change) < gap:
                continue
            self.logger.warning("黑天鹅保护：%s 单根跳空 %.2f%% ≥ %.0f%%，强制平仓",
                                symbol, change * 100, gap * 100)
            for book, direction in ((self.account.positions, "sell"),
                                    (self.account.short_positions, "cover")):
                pos = book.get(symbol)
                if pos is not None and pos.volume > 0:
                    actions.append({"symbol": symbol, "direction": direction,
                                    "volume": pos.available, "price": px,
                                    "reason": f"黑天鹅跳空 {change:.2%}"})
        return actions

    def _stop_loss_actions(self, prices: Dict[str, float]) -> List[dict]:
        actions = []
        sl = abs(float(self.stop_loss)) if self.stop_loss else None
        tp = abs(float(self.take_profit)) if self.take_profit else None
        if not sl and not tp:
            return actions
        for symbol, pos in list(self.account.positions.items()):
            px = prices.get(symbol)
            if px is None or pos.volume <= 0 or pos.avg_cost <= 0:
                continue
            ret = px / pos.avg_cost - 1.0
            if (sl and ret <= -sl) or (tp and ret >= tp):
                actions.append({"symbol": symbol, "direction": "sell",
                                "volume": pos.available, "price": px,
                                "reason": "止损" if sl and ret <= -sl else "止盈"})
        for symbol, pos in list(self.account.short_positions.items()):
            px = prices.get(symbol)
            if px is None or pos.volume <= 0 or pos.avg_cost <= 0:
                continue
            ret = pos.avg_cost / px - 1.0
            if (sl and ret <= -sl) or (tp and ret >= tp):
                actions.append({"symbol": symbol, "direction": "cover",
                                "volume": pos.available, "price": px,
                                "reason": "止损" if sl and ret <= -sl else "止盈"})
        return actions

    # ==================== 敞口 ====================

    def symbol_exposure(self, symbol: str) -> float:
        total = 0.0
        for book in (self.account.positions, self.account.short_positions):
            pos = book.get(str(symbol))
            if pos is None:
                continue
            total += abs(float(pos.volume) * float(pos.price) * float(pos.multiplier))
        return total

    def total_exposure(self) -> float:
        total = 0.0
        for book in (self.account.positions, self.account.short_positions):
            for pos in book.values():
                total += abs(float(pos.volume) * float(pos.price) * float(pos.multiplier))
        return total
