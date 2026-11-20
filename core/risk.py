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
from datetime import date as _date
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

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
    """三引擎共用的风控裁决器。

    v3.52 回测验收裁定（B-1）：熔断的目的是「暂停开仓等待风险释放」，
    不是永久锁死。触发条件不变；恢复走两条路：
    ① 连续 ``halt_recover_stabilize_days``（默认 3）个交易日权益未再创新低
       （企稳）自动解除，并以解除日权益为新的回撤峰值基准（旧峰值不清除
       会导致「解除当天即再熔断」的死锁，即 2022-02-25 起 175 笔连续拒单
       4.7 年的根因）；
    ② 人工复位：实盘 CLI ``risk-reset --confirm yes``（二次确认），回测走自动恢复。
    熔断状态（是否熔断/起始日/企稳天数）必须随回测 result 与实盘状态文件落盘，
    禁止静默复位。
    """

    def __init__(self, account, params: dict = None, logger: logging.Logger = None,
                 state_file=None):
        base = risk_config()
        params = dict(params or {})
        self.account = account
        self.logger = logger or getattr(account, "logger", None) or logging.getLogger("risk")
        # 熔断自动恢复参数：模块默认 3 日企稳（config.RISK 未登记该键，新增键
        # 会改变 cs-v1 配置面，须走版本流程；params 显式覆盖优先）
        self.halt_recover_stabilize_days = int(params.get(
            "halt_recover_stabilize_days",
            base.get("halt_recover_stabilize_days", 3)))
        self.halt_recover_enabled = bool(params.get(
            "halt_recover_enabled", base.get("halt_recover_enabled", True)))
        # 实盘状态文件（可选）：回测 None（状态随 result 落盘），实盘传路径跨进程同步
        self.state_file = state_file

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
        self.halt_since = None          # 熔断起始日（随 halt_state 落盘）
        self._stabilize_days = 0        # 熔断观察期：连续企稳【交易日】数
        self._halt_low: Optional[float] = None   # 触发以来最低日终权益（创新低判据基准）
        self._last_day_close: Optional[float] = None  # 最近一根 bar 的权益（日终=最后一根）

    # ==================== 权益与熔断 ====================

    def on_bar(self, date, prices: Dict[str, float]) -> List[dict]:
        """每根 bar 开始调用：更新日初权益/峰值，返回需要强制平仓的指令列表。"""
        prices = {str(s): float(p) for s, p in dict(prices or {}).items()
                  if p is not None and float(p) > 0}
        equity = float(self.account.calc_equity(prices))
        # 换日判定按「日期部分」比较：分钟线下 date 是 timestamp，直接比较
        # 会让日初权益每根 bar 都被重置（日内亏损上限失效）（v3.53 扩围修复）
        day = self._as_day(date)
        if self._day != day:
            self._day = day
            self._day_start_equity = equity
            # 熔断观察期推进按【交易日】计数（v3.53 裁定修正）：分钟级每根 bar
            # 递增会把「3 日企稳」稀释成 3 bar（0.75 交易日），熔断强度随采样
            # 频率漂移——观察值固定为上一交易日日终权益（_last_day_close 此时
            # 尚未被当日 bar 覆盖），换日才推进；_day 先更新使解除日志记「生效日」
            if self.halted:
                self._advance_halt_observation()
        self._last_day_close = equity   # 当根权益；日终（最后一根 bar）即日终权益
        self._peak_equity = max(self._peak_equity or equity, equity)
        self._update_halt(equity)

        actions = self._black_swan_actions(prices)
        actions.extend(self._stop_loss_actions(prices))
        self._prev_prices = dict(prices)
        return actions

    @staticmethod
    def _as_day(date):
        """任意日期输入 → date（datetime/Timestamp 取日期部分）。

        无法解析的合成标签（测试用 "d1" 等）原样返回，保持旧「相等比较」
        行为；真实行情输入（Timestamp/datetime/str-date）一律归一为 date，
        保证分钟级换日判定按日期部分比较。
        """
        if date is None:
            return None
        if isinstance(date, _date) and not isinstance(date, datetime):
            return date
        try:
            return pd.Timestamp(date).date()
        except (ValueError, TypeError):
            return date

    def _update_halt(self, equity: float) -> None:
        if self.halted:
            # 熔断观察期：推进只在换日（_advance_halt_observation），
            # 不再逐 bar 判定——逐 bar 会把「3 日企稳」按 bar 稀释（B-1 死锁
            # 修复后评审二轮抓出的强度漂移），日内也不重复触发
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

    def _advance_halt_observation(self) -> None:
        """换日推进熔断观察期（企稳单位 = 交易日，双频等强）。

        观察值 = 上一交易日日终权益（_last_day_close 在换日时尚未被当日 bar
        覆盖，即上一日最后一根 bar 的权益）。判据 = 未跌破触发以来最低日终
        权益（「不创新低」，接受持平）；创新低即归零。连续
        ``halt_recover_stabilize_days`` 个交易日未创新低 → 解除，解除时把
        回撤峰值基准重置为解除日权益（不清基准会在解除当天被旧峰值再熔，
        即首轮 2022-02-25 起 4.7 年 175 笔连续拒单死锁的根因）。
        """
        if not self.halt_recover_enabled:
            return
        obs = self._last_day_close
        if obs is None or obs <= 0:
            return
        new_low = self._halt_low is None or obs < self._halt_low
        if new_low:
            self._halt_low = float(obs)
            self._stabilize_days = 0
        else:
            self._stabilize_days += 1
        released = self._stabilize_days >= self.halt_recover_stabilize_days
        # 状态机逐日日志（评审要求：每日权益是否创新低/企稳计数/状态转移可自证）
        self.logger.info(
            "[HALT_OBS] day=%s obs=%.2f halt_low=%.2f stabilize=%d/%d action=%s",
            self._day, obs, self._halt_low, self._stabilize_days,
            self.halt_recover_stabilize_days,
            "released" if released else ("reset(创新低)" if new_low else "hold"))
        if self._stabilize_days >= self.halt_recover_stabilize_days:
            reason = self.halt_reason
            released_at = self._day
            self.reset_halt()
            self._peak_equity = float(obs)   # 解除日权益为新回撤基准
            self._halt_low = None
            self.logger.warning(
                "风控熔断自动恢复：连续 %d 个交易日权益未创新低（企稳），解除熔断"
                "（触发日 %s，原因：%s），回撤基准重置为 %.2f，恢复开仓",
                self.halt_recover_stabilize_days, released_at, reason, obs)
        else:
            self._write_state_file()

    def _halt(self, reason: str) -> None:
        self.halted = True
        self.halt_reason = reason
        self.halt_since = self._day
        self._stabilize_days = 0
        self._halt_low = None   # 观察期从次日开始：首次 advance 以触发日日终为基准
        self.logger.warning("风控熔断：%s", reason)
        self._write_state_file()

    def reset_halt(self, manual: bool = False) -> None:
        """解除熔断。manual=True 为人工复位（CLI risk-reset，需二次确认），打审计日志。"""
        self.halted = False
        self.halt_reason = ""
        self.halt_since = None
        self._stabilize_days = 0
        self._halt_low = None
        if manual:
            self.logger.warning("风控熔断人工复位：由操作者经 CLI 显式解除（需二次确认），恢复开仓")
        self._write_state_file()

    def halt_state(self) -> dict:
        """熔断状态快照（禁止静默复位：随回测 result / 实盘状态文件落盘）。"""
        return {
            "halted": bool(self.halted),
            "halt_reason": self.halt_reason,
            "halt_since": str(self.halt_since) if self.halt_since is not None else None,
            "stabilize_days": int(self._stabilize_days),
            "recover_stabilize_days": int(self.halt_recover_stabilize_days),
            "recover_enabled": bool(self.halt_recover_enabled),
        }

    def _write_state_file(self) -> None:
        """实盘状态文件（可选）：halt/恢复/复位时落盘，跨进程（CLI risk-reset）可读。"""
        if not self.state_file:
            return
        try:
            from pathlib import Path
            import json
            path = Path(self.state_file)
            if not path.is_absolute():
                path = config.BASE_DIR / path
            if self.halted:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(self.halt_state(), ensure_ascii=False),
                                encoding="utf-8")
            elif path.exists():
                path.unlink()   # 解除即删标志文件（CLI 复位协议：文件不存在=未熔断）
        except OSError as exc:
            self.logger.warning("熔断状态文件写入失败 %s: %s", self.state_file, exc)

    def sync_state_file(self) -> None:
        """实盘换日时同步：状态文件被 CLI risk-reset 删除 → 内存熔断同步解除（人工复位生效点）。"""
        if not self.state_file:
            return
        from pathlib import Path
        path = Path(self.state_file)
        if not path.is_absolute():
            path = config.BASE_DIR / path
        if self.halted and not path.exists():
            self.reset_halt(manual=True)

    def new_day(self, date, equity: float = None, prices: Dict[str, float] = None) -> None:
        """显式换日：重置日内亏损基准。

        v3.52 裁定：不再无条件解除熔断（旧逻辑「每日复位→每日重熔」正是 B-1
        死锁形态）。熔断解除只走两条路：①连续 N 日企稳自动恢复；②人工复位
        （reset_halt(manual=True)）。实盘模式下先 sync_state_file() 让 CLI 复位生效。
        """
        self.sync_state_file()
        self._day = date
        if equity is None:
            equity = float(self.account.calc_equity(prices or {}))
        self._day_start_equity = float(equity)

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
