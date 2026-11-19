# -*- coding: utf-8 -*-
"""第 8 步 · 定时盯盘与消息推送（MarketMonitor）。

**8.0 开工前置：盯盘是第二个信号出口**
================================================================
``config.SIGNAL_EGRESS_CONFORMANCE`` 规定信号出口有三处：``place_order``
（账户层）、``monitor_push``（本模块）与 ``report_plan``（第 9 步报告候选）。
本模块产生的任何下单仍走 ``place_order``，撮合价基准统一读
``config.EXECUTION_MODEL["match_price_basis"]``，不在此另设一套。因此本模块受四条硬约束：

1. ``forbid_bare_on_tick``：**禁止把 data_fetcher 裸行情直接喂给策略**。
   喂给策略的每个 bar 都必须经 ``signal_gate.build_bar_dict()`` 构建，
   并由 ``signal_gate.assert_tick_bars()`` 兜底校验（只调用，不重写）。
2. ``monitor_must_inject_columns``：bar 必带三物化列
   ``warmup_ok / data_asof_date / price_adjust``，缺列/NaN 直接报错。
3. ``must_call_gate``：推送交易信号前必须调用 ``core/signal_gate.py``
   （开仓/加仓预热期拦截，平仓/减仓/风控提醒放行——**开严平宽**）。
4. ``push_requires_fresh`` + ``session_check_per_market``：推送前过时效闸门
   （与第 4 步 refetch 同源）；逐市场判交易时段，**停更/超限数据与
   非交易时段不推交易信号，只推数据告警**。

推送消息自带标注：``预热闸门`` / ``数据截至`` / ``新鲜度``。

防封 IP：同标的拉数有最小间隔；连续失败 5 次暂停 10 分钟（熔断）。

后台常驻::

    nohup python -m core.monitor >/dev/null 2>&1 &      # nohup
    pm2 start "python -m core.monitor" --name monitor   # pm2
    systemd: ExecStart=/usr/bin/python3 -m core.monitor
"""
from __future__ import annotations

import logging
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Set, Tuple

import pandas as pd

import config
import core.signal_gate as signal_gate
from core.data_fetcher import assert_fresh_for_trading
from core.notifier import BaseNotifier, ConsoleNotifier, LogNotifier
from core.utils import is_trading_day

logger = logging.getLogger(__name__)

# 三物化列中的另外两列（warmup_ok 由 signal_gate.build_bar_dict 注入）
ASOF_COLUMN = "data_asof_date"
ADJUST_COLUMN = "price_adjust"

FAIL_THRESHOLD = 5          # 连续失败次数 → 熔断
PAUSE_SECONDS = 10 * 60     # 熔断时长：10 分钟
MIN_FETCH_INTERVAL = 55     # 同标的两次拉数最小间隔（秒），防封 IP

PRICE_ALERT_PCT = 0.05      # 持仓涨跌幅预警阈值
VOLUME_SPIKE_RATIO = 2.0    # 量能异动倍数
NEW_HIGH_LOW_WINDOW = 20    # 新高/新低窗口

# ==================== 监控事件清单 ====================
# implemented=False 的项是后续接入点，登记但不执行，避免「静默缺失」。
MONITOR_EVENTS = (
    {"key": "price_move", "name": "价格/持仓涨跌幅异动", "implemented": True},
    {"key": "new_high_low", "name": "创 N 日新高/新低", "implemented": True},
    {"key": "volume_spike", "name": "成交量异动（≥2× 20 日均量）", "implemented": True},
    {"key": "stop_take", "name": "止损/止盈触发", "implemented": True},
    {"key": "data_stale", "name": "数据停更/超限告警", "implemented": True},
    {"key": "signal", "name": "策略交易信号", "implemented": True},
    {"key": "repo_rate", "name": "国债逆回购利率飙升", "implemented": True},
    {"key": "calendar", "name": "交易日历/夏令时提醒", "implemented": True},
    {"key": "session", "name": "开盘/收盘时段提醒", "implemented": False},
    {"key": "drawdown", "name": "账户回撤预警", "implemented": False},
    {"key": "concentration", "name": "持仓集中度预警", "implemented": False},
    {"key": "heartbeat", "name": "盯盘心跳", "implemented": False},
)


# ==================== 三物化列（只调用 signal_gate） ====================

def required_tick_columns() -> List[str]:
    """喂策略的 bar 必须携带的物化列（唯一事实源 signal_gate/config）。"""
    return signal_gate.tick_columns()


def assert_tick_bars(bars: Dict[str, dict]) -> None:
    """三物化列硬校验：缺列/NaN 直接报错（实现只在 signal_gate）。"""
    signal_gate.assert_tick_bars(bars)


# ==================== 逐市场交易时段 ====================

@dataclass
class MarketSession:
    tz: str
    sessions: Tuple[Tuple[int, int], ...] = ()
    calendar: str = "weekend"       # chinese / weekend / always
    interval_minutes: int = 1


_DEFAULT_SESSIONS: Dict[str, MarketSession] = {
    "cn_stock": MarketSession("Asia/Shanghai", ((570, 690), (780, 900)), "chinese"),
    "cn_etf": MarketSession("Asia/Shanghai", ((570, 690), (780, 900)), "chinese"),
    "cn_convertible": MarketSession("Asia/Shanghai", ((570, 690), (780, 900)), "chinese"),
    "cn_option": MarketSession("Asia/Shanghai", ((570, 690), (780, 900)), "chinese"),
    "cn_index": MarketSession("Asia/Shanghai", ((570, 690), (780, 900)), "chinese"),
    "cn_reits": MarketSession("Asia/Shanghai", ((570, 690), (780, 900)), "chinese"),
    "cn_fund": MarketSession("Asia/Shanghai", ((570, 900),), "chinese", 15),
    "hk_stock": MarketSession("Asia/Hong_Kong", ((570, 720), (780, 960)), "weekend"),
    "us_stock": MarketSession("America/New_York", ((570, 960),), "weekend"),
    "us_etf": MarketSession("America/New_York", ((570, 960),), "weekend"),
    "cn_future": MarketSession("Asia/Shanghai",
                               ((540, 615), (630, 690), (810, 900),
                                (1260, 1380), (1380, 1440)), "chinese"),
    "global_future": MarketSession("Asia/Shanghai", ((1260, 1440),), "weekend", 5),
    "cn_reverse_repo": MarketSession("Asia/Shanghai", ((565, 930),), "chinese"),
    "forex": MarketSession("Asia/Shanghai", ((0, 1440),), "always", 5),
    "crypto": MarketSession("UTC", ((0, 1440),), "always", 5),
}


def _config_hours(market: str) -> Tuple[Tuple[int, int], ...]:
    """读 config.get_market_config 的 trading_hours（+night_session 夜盘）。"""
    cfg = config.get_market_config(market)
    hours = tuple(tuple(map(int, seg)) for seg in cfg.get("trading_hours") or ())
    night = tuple(tuple(map(int, seg)) for seg in cfg.get("night_session") or ())
    return hours + night


class MarketMonitor:
    """定时盯盘：多市场调度 → 合规喂策略 → 闸门后推送。"""

    def __init__(self,
                 paper_trader=None,
                 strategy=None,
                 notifiers: Optional[List[BaseNotifier]] = None,
                 fetcher=None,
                 markets: Optional[Dict[str, List[str]]] = None,
                 warmup_bars: Optional[int] = None,
                 price_adjust: str = None,
                 repo_rate_getter: Optional[Callable[[], float]] = None,
                 scheduler=None) -> None:
        """notifiers 为空时默认 Console+Log；markets: {market: [symbols]}，
        未传时从 paper_trader 持仓推导。"""
        self.paper_trader = paper_trader
        self.strategy = strategy
        self.fetcher = fetcher
        self.repo_rate_getter = repo_rate_getter
        self.notifiers = list(notifiers) if notifiers else [
            ConsoleNotifier(), LogNotifier()]
        self.warmup_bars = int(warmup_bars or
                               signal_gate.min_backtest_bars(strategy) or 20)
        self.price_adjust = str(price_adjust or
                                config.INDICATOR_CONFIG.get("default_adjust",
                                                            "qfq"))
        self.markets: Dict[str, List[str]] = markets or self._infer_markets()
        self._sessions = {m: self._make_session(m) for m in self.markets}

        self._seen: Dict[str, int] = {}             # symbol → 累计 bar 数（预热计数）
        self._fail: Dict[str, int] = {}             # symbol → 连续拉数失败次数
        self._paused_until: Dict[str, float] = {}   # symbol → 熔断截止时间戳
        self._last_fetch: Dict[str, float] = {}     # market:symbol → 上次拉数时间戳
        self._known_order_ids: Set[str] = set()
        self._last_bars: Dict[str, dict] = {}
        self._scheduler = scheduler
        self._last_calendar_day: Optional[str] = None

    # ------------------------------------------------------------------
    # 逐市场交易时段
    # ------------------------------------------------------------------
    def _make_session(self, market: str) -> MarketSession:
        base = _DEFAULT_SESSIONS.get(market) or MarketSession(
            "Asia/Shanghai", ((570, 690), (780, 900)), "chinese")
        if market in ("crypto", "forex", "us_stock", "us_etf", "hk_stock",
                      "global_future", "cn_future", "cn_reverse_repo", "cn_fund"):
            # 非标准 A 股时段（含夜盘/DST/7×24）以默认表为准
            return base
        try:
            hours = _config_hours(market)
            if hours:
                return MarketSession(base.tz, hours, base.calendar,
                                     base.interval_minutes)
        except Exception:                       # noqa: BLE001 —— 缺配置回退默认表
            pass
        return base

    @staticmethod
    def _now_in(tz_name: str) -> datetime:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz_name))

    def is_in_session(self, market: str, now: Optional[datetime] = None) -> bool:
        """逐市场交易时段判断：tz + 交易日历 + 分钟段。"""
        sess = self._sessions.get(market) or self._make_session(market)
        now = now or self._now_in(sess.tz)
        if sess.calendar == "always":
            return True
        try:
            if not is_trading_day(now.date(), market=market):
                return False
        except Exception:                       # noqa: BLE001 —— 日历缺失退化周末判断
            if now.weekday() >= 5:
                return False
        minute = now.hour * 60 + now.minute
        return any(s <= minute < e for s, e in sess.sessions)

    # ------------------------------------------------------------------
    # 行情获取（防封 IP：节流 + 熔断）
    # ------------------------------------------------------------------
    def _circuit_paused(self, symbol: str) -> bool:
        return time.monotonic() < self._paused_until.get(symbol, 0.0)

    def _fetch_df(self, market: str, symbol: str) -> Optional[pd.DataFrame]:
        """带节流与熔断的拉数；失败返回 None，绝不拿旧数据顶上。"""
        if self._circuit_paused(symbol):
            logger.warning("[盯盘] %s 熔断中（连续失败≥%d），暂停至 %s",
                           symbol, FAIL_THRESHOLD,
                           datetime.fromtimestamp(self._paused_until[symbol]))
            return None
        key = f"{market}:{symbol}"
        wait = MIN_FETCH_INTERVAL - (time.monotonic() - self._last_fetch.get(key, 0.0))
        if wait > 0:
            time.sleep(wait)
        try:
            df = self.fetcher.get_daily(symbol, adjust=self.price_adjust)
            self._fail[symbol] = 0
            self._last_fetch[key] = time.monotonic()
            return df
        except Exception as exc:                # noqa: BLE001
            self._fail[symbol] = self._fail.get(symbol, 0) + 1
            self._last_fetch[key] = time.monotonic()
            logger.error("[盯盘] %s 拉数失败（%d/%d）：%s",
                         symbol, self._fail[symbol], FAIL_THRESHOLD, exc)
            if self._fail[symbol] >= FAIL_THRESHOLD:
                self._paused_until[symbol] = time.monotonic() + PAUSE_SECONDS
                self.notify("盯盘拉数连续失败，已熔断 10 分钟",
                            f"{market} {symbol} 连续失败 {self._fail[symbol]} 次",
                            level="error")
            return None

    # ------------------------------------------------------------------
    # 合规喂策略（三物化列注入；禁止裸行情）
    # ------------------------------------------------------------------
    def _build_bars_one(self, symbol: str, df: pd.DataFrame) -> Dict[str, dict]:
        sub = (df[df["symbol"] == symbol] if "symbol" in df.columns else df)
        sub = sub.dropna(subset=["close"])
        if len(sub) == 0:
            raise ValueError(f"{symbol} 无有效收盘数据，拒绝构建 bar")
        asof = str(pd.to_datetime(sub["date"].iloc[-1]).date())
        last = sub.iloc[-1]
        row = {"date": asof, "open": float(last["open"]), "high": float(last["high"]),
               "low": float(last["low"]), "close": float(last["close"]),
               "volume": float(last["volume"] if pd.notna(last["volume"]) else 0)}
        bars = signal_gate.build_bar_dict(
            {symbol: row}, {symbol: self._seen.get(symbol, len(sub))},
            self.warmup_bars, date=asof)
        bars[symbol][ASOF_COLUMN] = asof                # 物化列 2：数据截至日期
        bars[symbol][ADJUST_COLUMN] = self.price_adjust  # 物化列 3：复权口径
        self._seen[symbol] = self._seen.get(symbol, len(sub)) + 1
        assert_tick_bars(bars)                          # 缺列/NaN 直接报错
        return bars

    def _feed_strategy(self, date, bars: Dict[str, dict]) -> None:
        """唯一合规喂入口：优先 dispatch_tick（tick bar 带三物化列），
        退化到 dispatch_bar/on_bar；绝不直接喂 data_fetcher 裸行情。"""
        if self.strategy is None:
            return
        if hasattr(self.strategy, "dispatch_tick"):
            self.strategy.dispatch_tick(bars, date=date)
        elif hasattr(self.strategy, "dispatch_bar"):
            self.strategy.dispatch_bar(date, bars)
        elif hasattr(self.strategy, "on_bar"):
            self.strategy.on_bar(date, bars)
        else:                                       # pragma: no cover
            raise TypeError("strategy 缺少 dispatch_tick/dispatch_bar/on_bar，"
                            "无法合规喂行情")

    # ------------------------------------------------------------------
    # 信号捕获与推送（monitor_push 出口：闸门 + 时效 + 标注）
    # ------------------------------------------------------------------
    def _diff_new_orders(self) -> list:
        try:
            orders = list(self.paper_trader.orders or [])
        except Exception:                       # noqa: BLE001 —— 未接模拟盘跳过
            return []
        fresh = [o for o in orders
                 if str(getattr(o, "order_id", id(o))) not in self._known_order_ids]
        for o in fresh:
            self._known_order_ids.add(str(getattr(o, "order_id", id(o))))
        return fresh

    def _freshness(self, df: pd.DataFrame, market: str, symbol: str,
                   direction: str) -> Dict:
        """时效闸门（与第 4 步 refetch 同源）：open 停更拒 / close 放。"""
        side = "open" if str(direction).lower() in signal_gate.OPEN_DIRECTIONS \
            else "close"
        kind = "daily"
        method = getattr(self.fetcher, "assert_fresh_for_trading", None)
        try:
            if callable(method):
                ok = method(df, kind=kind, market=market, symbol=symbol,
                            fetcher=self.fetcher, for_trading=True,
                            order_side=side)
            else:
                ok = assert_fresh_for_trading(
                    df, kind=kind, market=market, symbol=symbol,
                    fetcher=self.fetcher, for_trading=True, order_side=side)
            return {"fresh": ok is not False, "blocked": False}
        except RuntimeError as exc:
            return {"fresh": False, "blocked": side == "open", "reason": str(exc)}

    def _push_trade_signal(self, market, symbol, direction, price, reason,
                           warmup_ok, asof, fresh, is_open) -> None:
        """推送交易信号，自带标注；开严平宽（开仓被闸门拦只推拦截提醒）。"""
        freshness_tag = "新鲜" if fresh.get("fresh") else "停更/超限 ⚠"
        tags = [f"预热闸门: {'已过 ✓' if warmup_ok else '未过 ✗'}",
                f"数据截至: {asof}", f"新鲜度: {freshness_tag}"]
        if not is_open:
            # 平仓/减仓/风控提醒：一律放行（开严平宽）
            self.notify(f"{symbol} 平仓/减仓信号",
                        f"市场 {market} | 方向 {direction} | 价格 {price}\n"
                        f"理由: {reason}\n" + " | ".join(tags), level="warning")
            return

        # 开仓：唯一裁决走 signal_gate（只调用不重写）
        rejection = signal_gate.check_order(direction, warmup_ok, symbol,
                                            logger=logger)
        blocked = rejection is not None or bool(fresh.get("blocked"))
        if blocked:
            code = "warmup" if rejection is not None else "stale"
            signal_gate.record_decision(
                symbol, direction, False,
                reason=(rejection or {}).get("reason")
                or fresh.get("reason") or "数据不新鲜，开仓信号不推送",
                reason_code=code, source="monitor_push")
        title = (f"{symbol} 开仓信号（已过预热闸门）" if not blocked
                 else f"{symbol} 开仓信号（未推送交易信号）")
        body = (f"市场 {market} | 方向 {direction} | 价格 {price}\n"
                f"理由: {reason}\n" + " | ".join(tags))
        self.notify(title, body, level="info" if not blocked else "warning")

    def _handle_new_orders(self, bars: Dict[str, dict],
                           dfs: Dict[str, pd.DataFrame], market: str) -> None:
        for order in self._diff_new_orders():
            symbol = str(getattr(order, "symbol", "") or "")
            direction = str(getattr(order, "direction", "") or "")
            bar = bars.get(symbol)
            if bar is None:
                continue
            warmup_ok = signal_gate.bar_warmup_ok(bar)  # 缺列抛错，绝不默认放行
            asof = str(bar.get(ASOF_COLUMN, ""))
            df = dfs.get(symbol)
            fresh = (self._freshness(df, market, symbol, direction)
                     if df is not None else
                     {"fresh": False, "blocked": True, "reason": "无行情帧"})
            self._push_trade_signal(
                market, symbol, direction, getattr(order, "price", None),
                getattr(order, "reason", "") or getattr(order, "tag", ""),
                warmup_ok, asof, fresh,
                direction.lower() in signal_gate.OPEN_DIRECTIONS)

    # ------------------------------------------------------------------
    # 监控事件清单（风控提醒：不受预热限制，开严平宽的「平」）
    # ------------------------------------------------------------------
    def scan_events(self, df: pd.DataFrame) -> None:
        """持仓事件扫描：±5% 预警 / 20日新高新低 / 量能 2 倍 / 止损止盈。"""
        if df is None or len(df) == 0:
            return
        try:
            positions = dict(getattr(self.paper_trader.account, "positions", {}) or {})
        except Exception:                       # noqa: BLE001 —— 无账户跳过
            return
        if not positions:
            return
        frames = ({"*": df} if "symbol" not in df.columns
                  else {s: g for s, g in df.groupby("symbol")})
        for symbol, pos in positions.items():
            sub = frames.get(symbol) or frames.get("*")
            if sub is None or len(sub) < NEW_HIGH_LOW_WINDOW + 1:
                continue
            c = sub["close"].reset_index(drop=True)
            last = float(c.iloc[-1])
            base = getattr(pos, "avg_cost", None) or getattr(pos, "cost", None)
            if base:
                pct = (last / float(base) - 1.0) * 100
                if abs(pct) >= PRICE_ALERT_PCT * 100:
                    self.notify(f"{symbol} 持仓涨跌幅预警",
                                f"现价 {last}，成本 {base}，涨跌 {pct:+.1f}%"
                                f"（≥±{PRICE_ALERT_PCT:.0%}）",
                                level="warning")
            if last >= float(c.iloc[-NEW_HIGH_LOW_WINDOW:].max()):
                self.notify(f"{symbol} 创 {NEW_HIGH_LOW_WINDOW} 日新高",
                            f"现价 {last}", level="info")
            if last <= float(c.iloc[-NEW_HIGH_LOW_WINDOW:].min()):
                self.notify(f"{symbol} 创 {NEW_HIGH_LOW_WINDOW} 日新低",
                            f"现价 {last}", level="warning")
            if "volume" in sub.columns:
                v = sub["volume"].reset_index(drop=True)
                avg20 = float(v.iloc[-(NEW_HIGH_LOW_WINDOW + 1):-1].mean())
                if avg20 > 0 and float(v.iloc[-1]) >= VOLUME_SPIKE_RATIO * avg20:
                    self.notify(f"{symbol} 成交量异动",
                                f"今量 {float(v.iloc[-1]):.0f} ≥ "
                                f"{VOLUME_SPIKE_RATIO:g}×{NEW_HIGH_LOW_WINDOW}"
                                f"日均量 {avg20:.0f}", level="info")
            self._check_stop_take(symbol, pos, last)

    def _check_stop_take(self, symbol: str, pos, last: float) -> None:
        """止损止盈触发（持仓带 stop_price/take_price 字段时生效）。"""
        stop = getattr(pos, "stop_price", None)
        take = getattr(pos, "take_price", None)
        if stop and last <= float(stop):
            self.notify(f"{symbol} 止损触发", f"现价 {last} ≤ 止损价 {stop}",
                        level="critical")
        elif take and last >= float(take):
            self.notify(f"{symbol} 止盈触发", f"现价 {last} ≥ 止盈价 {take}",
                        level="info")

    def check_repo_rate(self) -> None:
        """国债逆回购利率飙升：GC001 > 3%（季末/年末 > 5%）。"""
        if self.repo_rate_getter is None:
            return
        try:
            rate = float(self.repo_rate_getter())
        except Exception as exc:                # noqa: BLE001
            logger.debug("逆回购利率获取失败：%s", exc)
            return
        now = datetime.now()
        quarter_end = (now.month in (3, 6, 9, 12) and now.day >= 25)
        threshold = 5.0 if quarter_end else 3.0
        if rate >= threshold:
            self.notify("逆回购利率飙升",
                        f"GC001 年化 {rate:.2f}% ≥ {threshold}%"
                        + ("（季末/年末阈值）" if quarter_end else ""),
                        level="warning")

    def push_calendar_reminder(self, force: bool = False) -> None:
        """交易日历提醒：休市/美股夏令时切换（每日一次）。"""
        today = datetime.now().strftime("%Y-%m-%d")
        if not force and self._last_calendar_day == today:
            return
        self._last_calendar_day = today
        lines: List[str] = []
        for market, sess in self._sessions.items():
            try:
                open_today = is_trading_day(datetime.now().date(), market=market)
            except Exception:                   # noqa: BLE001
                open_today = datetime.now().weekday() < 5
            if not open_today:
                lines.append(f"{market} 今日休市")
            if sess.tz == "America/New_York":
                days = self._days_to_dst_switch()
                if days is not None and days <= 7:
                    lines.append(f"美股 {days} 天后切换夏/冬令时")
        if lines:
            self.notify("交易日历提醒", "\n".join(lines), level="info")

    @staticmethod
    def _days_to_dst_switch() -> Optional[int]:
        try:
            import pytz
            tz = pytz.timezone("America/New_York")
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            future = [t for t in tz._utc_transition_times if t > now]   # noqa: SLF001
            return (future[0] - now).days if future else None
        except Exception:                       # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # 单轮检查
    # ------------------------------------------------------------------
    def check_market(self, market: str) -> None:
        """单轮检查：非交易时段直接返回；停更只推告警、不喂策略。"""
        if not self.is_in_session(market):
            logger.debug("[盯盘] %s 非交易时段，跳过", market)
            return
        dfs: Dict[str, pd.DataFrame] = {}
        for symbol in self.markets.get(market) or []:
            df = self._fetch_df(market, symbol)
            if df is None or len(df) == 0:
                continue
            # 时效预检（refetch 同源）：停更不喂策略、不推交易信号，只推告警
            fresh = self._freshness(df, market, symbol, "open")
            if not fresh.get("fresh"):
                self.notify("数据异常告警（停更/超限）",
                            f"{market} {symbol}：{fresh.get('reason', '数据不新鲜')}\n"
                            f"已停止喂策略，不推送任何交易信号",
                            level="error")
                continue
            dfs[symbol] = df

        if not dfs:
            return                              # 全部停更：只告警，不喂不推

        bars: Dict[str, dict] = {}
        for symbol, df in dfs.items():
            bars.update(self._build_bars_one(symbol, df))
        self._last_bars = dict(bars)
        asof = max(str(b.get(ASOF_COLUMN, "")) for b in bars.values())
        self._feed_strategy(asof, bars)
        self._handle_new_orders(bars, dfs, market)
        for df in dfs.values():
            self.scan_events(df)

    def check_once(self) -> Dict[str, dict]:
        """一轮检查全部市场，返回各市场结果（便于测试/巡检）。"""
        results: Dict[str, dict] = {}
        for market in list(self.markets):
            before = len(self._known_order_ids)
            self.check_market(market)
            results[market] = {
                "bars": list(self._last_bars),
                "new_orders": len(self._known_order_ids) - before,
            }
        return results

    # ------------------------------------------------------------------
    # 通知入口
    # ------------------------------------------------------------------
    def notify(self, title: str, content: str,
               level: str = "info") -> List[str]:
        """扇出全部渠道，返回实际送达的渠道名（去重/限流由渠道内部处理）。"""
        delivered = []
        for n in self.notifiers:
            try:
                if n.send(title, content, level=level):
                    delivered.append(getattr(n, "name", type(n).__name__))
            except Exception as exc:            # noqa: BLE001 —— 通知是旁路
                logger.error("[盯盘] 渠道 %s 发送异常：%s",
                             getattr(n, "name", "?"), exc)
        return delivered

    # ------------------------------------------------------------------
    # 调度与生命周期
    # ------------------------------------------------------------------
    def _infer_markets(self) -> Dict[str, List[str]]:
        markets: Dict[str, List[str]] = {}
        try:
            for market, book in (getattr(self.paper_trader.account, "markets", {})
                                 or {}).items():
                markets.setdefault(market, list(book))
        except Exception:                       # noqa: BLE001
            pass
        return markets

    def start(self) -> None:
        """进入事件循环（Ctrl+C 优雅退出，退出前保存账户状态）。"""
        from apscheduler.schedulers.blocking import BlockingScheduler
        sched = self._scheduler or BlockingScheduler()
        self._scheduler = sched
        for market, sess in self._sessions.items():
            sched.add_job(self.check_market, "interval",
                          minutes=max(1, sess.interval_minutes),
                          args=[market], id=f"check:{market}",
                          max_instances=1, coalesce=True)
        sched.add_job(self.push_calendar_reminder, "cron", hour=8, minute=30,
                      id="calendar", coalesce=True)
        self._install_signal_handlers()
        logger.info("[盯盘] 启动：市场=%s；预热门槛=%d 根；时段=%s",
                    list(self.markets), self.warmup_bars,
                    {m: s.sessions for m, s in self._sessions.items()})
        self.push_calendar_reminder(force=True)
        try:
            sched.start()
        except (KeyboardInterrupt, SystemExit):
            self.shutdown()

    def _install_signal_handlers(self) -> None:
        def _graceful(signum, _frame):          # noqa: ARG001
            logger.info("[盯盘] 收到信号 %s，优雅退出……", signum)
            self.shutdown()
            sys.exit(0)
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _graceful)
            except (ValueError, OSError):       # 非主线程环境
                pass

    def shutdown(self) -> None:
        """退出前保存账户状态。"""
        saved = None
        try:
            if self.paper_trader is not None and hasattr(self.paper_trader,
                                                         "save_account"):
                saved = self.paper_trader.save_account()
                logger.info("[盯盘] 已保存账户状态：%s", saved)
        except Exception as exc:                # noqa: BLE001
            logger.error("[盯盘] 保存账户状态失败：%s", exc)
        try:
            if self._scheduler is not None and hasattr(self._scheduler,
                                                       "shutdown"):
                self._scheduler.shutdown(wait=False)
        except Exception:                       # noqa: BLE001
            pass
        self.notify("盯盘退出", f"账户状态：{saved or '未保存'}", level="info")

    # 兼容命名
    stop = shutdown


def run_forever() -> None:
    """命令行后台常驻入口（nohup / pm2 / systemd 参见模块 docstring）。"""
    from core.paper_trader import PaperTrader
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    trader = PaperTrader()
    monitor = MarketMonitor(paper_trader=trader,
                            strategy=getattr(trader, "strategy", None))
    monitor.start()


if __name__ == "__main__":                      # pragma: no cover
    run_forever()
