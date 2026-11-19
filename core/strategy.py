"""第 5 步：策略基类（core/strategy.py）

一份策略代码、一个字都不改，在「回测 / 参数优化 / 模拟盘 / 实盘仿真」四种环境里跑通：
执行器（runner）负责取数、撮合、费用、交易日历；策略只负责「买什么、何时买」。

策略文件里只允许出现：
    self.buy() / self.sell() / self.short() / self.cover()
    self.get_position() / self.get_history() / self.params
绝对不允许直接取数、直接下单、直接算手续费、直接判断交易日。

【开工前置：两道闸门必须在信号入口真正生效（5.0）】
1. 预热闸门（第 3 步 B1/B5）：
   - 执行器喂给 `on_bar` 的每根 bar 都带物化布尔字段 `warmup_ok`；
   - `buy()` / `short()` 内部强制校验，`warmup_ok=False`（或缺失）**直接拒单**，
     不进入账户层；`sell()` / `cover()` 放行（预热期也必须能止损/平仓）；
   - 策略若自己拼指标帧，必须调 `self.assert_signal_frame(df)`：预热掩码为 False 的行
     一旦出现非 NaN 指标值（fillna/ffill/bfill/rolling(min_periods=1) 填过）就报错；
   - `get_history(symbol, n, indicator=...)`：n < `required_bars(indicator)` 抛错，
     否则返回带 `attrs["warmup_ok"]` 的完整序列；
   - 末根 bar 仍在预热期（新上市/刚切周期）时，paper/live 下不出信号。
2. 数据时效闸门（第 4 步 stale v2）：由 `core/account.py::place_order` 独立 refetch 复核，
   策略层不重复实现。

【内置风控】
   - 单标的持仓上限（默认总权益 30%，可用 params 覆盖）；
   - 总杠杆上限（按 config.RISK["account"]["max_leverage"] 分品种）；
   - 止损 / 止盈（params["stop_loss"] / ["take_profit"]，按持仓成本触发）；
   - 黑名单（退市 / 停牌 / ST / 风险警示，来自 bar 标记或 params["blacklist"]）。
"""
from __future__ import annotations

import inspect
import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

import config
from core import indicators as ind
from core import risk as risk_mod
from core import signal_gate
from core.account import TradingAccount
from core.utils import setup_logger

__all__ = ["BaseStrategy", "OrderRejected"]


class OrderRejected(Exception):
    """策略层拦截（预热期 / 黑名单 / 风控上限）时抛出，执行器可选择捕获继续跑。"""


class BaseStrategy:
    """所有策略的父类。子类只需实现 `on_bar`。"""

    # 子类用类属性声明元信息（loader / 报告 / 优化都会读）
    meta = {
        "name": "",
        "display_name": "",
        "markets": [],
        "periods": ["1d"],
        "params": {},
        "description": "",
        "author": "",
        "version": "1.0",
        # 预热指标声明：[("RSI", {"n": 14}), ("EMA", {"n": 20})]，用于反推 warmup_bars
        "warmup": [],
    }

    # 默认风控参数（可被 params 覆盖）；None = 读 config.RISK（唯一参数源）
    DEFAULT_RISK = {
        "max_single_symbol_pct": None,   # None = config.RISK["account"]["max_single_symbol_pct"]
        "max_leverage": None,            # None = 读 config.RISK["account"]["max_leverage"]
        "stop_loss": None,               # 例 0.08 = 亏 8% 止损
        "take_profit": None,             # 例 0.20 = 盈 20% 止盈
        "blacklist": (),                 # 显式黑名单
    }

    def __init__(self, account: TradingAccount = None, data_fetcher=None,
                 params: dict = None, logger: logging.Logger = None,
                 run_mode: str = None, history_provider=None):
        self.account = account if account is not None else TradingAccount(run_mode=run_mode)
        self.fetcher = data_fetcher
        self.logger = logger or setup_logger("strategy", config.LOG_DIR / "strategy.log")
        self.run_mode = str(run_mode or getattr(self.account, "run_mode", config.RUN_MODE))

        merged = dict(self.meta.get("params") or {})
        merged.update(dict(params or {}))
        for key, value in self.DEFAULT_RISK.items():
            merged.setdefault(key, value)
        self.params: Dict = merged

        # 执行器注入的运行时状态
        self._history_provider = history_provider   # callable(symbol, n) -> DataFrame
        self._current_date = None
        self._bars: Dict[str, dict] = {}
        self._warmup_ok: Dict[str, bool] = {}
        self._bar_count: Dict[str, int] = {}
        self._prices: Dict[str, float] = {}
        self._equity_curve: list = []
        self.orders: list = []
        self.rejected_orders: list = []

        self.warmup_bars = self._resolve_warmup_bars()
        self.risk = self._resolve_risk()
        # 风控唯一实现（三引擎共用，config.RISK 为唯一参数源）
        self.risk_manager = risk_mod.RiskManager(
            self.account, params=self.risk, logger=self.logger)
        self._blacklist = {str(x) for x in (self.params.get("blacklist") or ())}
        self.init()

    # ==================== 生命周期 ====================

    def init(self) -> None:
        """策略初始化：预热指标、设置参数。子类重写。"""

    def on_bar(self, date, bar_dict: Dict[str, dict]) -> None:
        """逐 K 线回调。子类必须实现。"""
        raise NotImplementedError(f"{type(self).__name__}.on_bar() 必须实现")

    def on_tick(self, price_dict: Dict[str, float], bars: Dict[str, dict] = None) -> None:
        """实时逐 tick 回调（可选重写；`bars` 为带三物化列的 tick bar）。"""

    def on_end_of_day(self, date) -> None:
        """每日收盘后回调（可选重写，用于调仓 / 风控）。"""

    # ==================== 执行器调用（策略不直接调） ====================

    def dispatch_bar(self, date, bar_dict: Dict[str, dict]) -> None:
        """执行器每个 bar 调用一次：写状态 → 内置风控 → on_bar。

        闸门实现全部在 `core/signal_gate.py`（引擎无关），此处只调用：
        缺 `warmup_ok` 的 bar_dict 直接报错，禁止执行器漏喂标记。
        """
        self._current_date = date
        self._bars = dict(bar_dict or {})
        signal_gate.assert_bar_dict(self._bars)
        # 换日：先解除 T+1 冻结，风控止损/平仓才拿得到可用数量
        self.account.roll_to(date)
        self._warmup_ok = {}
        for symbol, bar in self._bars.items():
            self._bar_count[symbol] = self._bar_count.get(symbol, 0) + 1
            price = _bar_price(bar)
            if price is not None:
                self._prices[symbol] = float(price)
            self._warmup_ok[symbol] = signal_gate.bar_warmup_ok(bar)

        self._run_risk_controls()
        self.on_bar(date, self._bars)

    def dispatch_end_of_day(self, date) -> None:
        self._current_date = date
        self.on_end_of_day(date)
        equity = self.account.calc_equity(self._prices)
        self._equity_curve.append({"date": date, "equity": float(equity)})

    def dispatch_tick(self, tick_bars: Dict[str, dict], date=None) -> None:
        """盯盘唯一允许的 on_tick 喂入口（第二个信号出口，第 8 步 8.0）。

        `core/monitor.py` 必须先通过 `signal_gate.build_bar` 注入三物化列
        （`warmup_ok` / `data_asof_date` / `price_adjust`），此处再用
        `signal_gate.assert_tick_bars` 兜底校验：缺列/NaN 直接报错，
        **禁止把 data_fetcher 裸行情直接喂 on_tick**。
        """
        self._bars = dict(tick_bars or {})
        signal_gate.assert_tick_bars(self._bars)
        self._current_date = date if date is not None else self._bars_date()
        prices: Dict[str, float] = {}
        self._warmup_ok = {}
        for symbol, bar in self._bars.items():
            price = _bar_price(bar)
            if price is not None:
                prices[symbol] = float(price)
            self._warmup_ok[symbol] = signal_gate.bar_warmup_ok(bar)
        self._prices.update(prices)

        if _accepts_bars(self.on_tick):
            self.on_tick(prices, bars=self._bars)
        else:  # 兼容旧子类的 on_tick(price_dict) 签名
            self.on_tick(prices)

    def _bars_date(self):
        for bar in self._bars.values():
            if isinstance(bar, dict) and bar.get("date") is not None:
                return bar["date"]
        return None

    def set_history_provider(self, provider) -> None:
        self._history_provider = provider

    # ==================== 便捷下单 ====================

    def buy(self, symbol: str, volume: float, price: float = None, **kwargs) -> dict:
        return self._order("buy", symbol, volume, price, **kwargs)

    def sell(self, symbol: str, volume: float, price: float = None, **kwargs) -> dict:
        return self._order("sell", symbol, volume, price, **kwargs)

    def short(self, symbol: str, volume: float, price: float = None, **kwargs) -> dict:
        return self._order("short", symbol, volume, price, **kwargs)

    def cover(self, symbol: str, volume: float, price: float = None, **kwargs) -> dict:
        return self._order("cover", symbol, volume, price, **kwargs)

    def _order(self, direction: str, symbol: str, volume: float,
               price: float = None, **kwargs) -> dict:
        symbol = str(symbol).strip()
        action = "open" if direction in ("buy", "short") else "close"

        # ---- 闸门 1：指标预热（开仓严、平仓宽；实现见 core/signal_gate.py）----
        rejection = signal_gate.check_order(
            direction, self.is_warmup_ok(symbol), symbol=symbol, logger=self.logger)
        if rejection is not None:
            rejection.setdefault("reject_id", f"strategy_{len(self.rejected_orders)}")
            self.rejected_orders.append(rejection)
            signal_gate.record_decision(
                symbol, direction, False, reason=rejection.get("reason", ""),
                reason_code="warmup", source="strategy",
                reject_id=rejection["reject_id"])
            return rejection

        # ---- 闸门 2：黑名单（退市/停牌/ST/风险警示）----
        if self._is_blacklisted(symbol):
            reason = "标的存在黑名单标记（退市/停牌/ST/风险警示），拒绝交易"
            self.logger.warning("策略拒单 %s %s：%s", symbol, direction, reason)
            rec = {"status": "rejected", "symbol": symbol, "direction": direction,
                   "reason": reason, "stage": "blacklist",
                   "reject_id": f"strategy_{len(self.rejected_orders)}"}
            self.rejected_orders.append(rec)
            signal_gate.record_decision(
                symbol, direction, False, reason=reason,
                reason_code=signal_gate.classify_rejection(reason),
                source="strategy", reject_id=rec["reject_id"])
            return rec

        # ---- 风控 3：单标的上限 / 总杠杆（只拦开仓）----
        if action == "open":
            limit_reason = self._check_position_limits(symbol, float(volume), price)
            if limit_reason:
                self.logger.warning("策略拒单 %s %s：%s", symbol, direction, limit_reason)
                rec = {"status": "rejected", "symbol": symbol, "direction": direction,
                       "reason": limit_reason, "stage": "risk",
                       "reject_id": f"strategy_{len(self.rejected_orders)}"}
                self.rejected_orders.append(rec)
                signal_gate.record_decision(
                    symbol, direction, False, reason=limit_reason,
                    reason_code="risk_block", source="strategy",
                    reject_id=rec["reject_id"])
                return rec

        px = price if price is not None else self._prices.get(symbol)
        result = self.account.place_order(
            symbol, direction, "market", float(volume), px,
            order_time=self._current_date,
            market_type=kwargs.pop("market_type", None),
            data=kwargs.pop("data", None),
            pre_close=kwargs.pop("pre_close", None),
            underlying_price=kwargs.pop("underlying_price", None),
            option_type=kwargs.pop("option_type", None),
            strike=kwargs.pop("strike", None),
            expiry=kwargs.pop("expiry", None),
            for_trading=self.run_mode in ("paper", "live", "live_sim"),
            warmup_ok=self._warmup_ok.get(symbol, False),
        )
        result.update({"stage": "account", "date": self._current_date})
        self.orders.append(result)
        if result.get("status") != "filled":
            self.rejected_orders.append(result)
        return result

    # ==================== 查询 ====================

    def get_position(self, symbol: str):
        pos = self.account.get_position(str(symbol), "long")
        if pos is not None:
            return pos
        return self.account.get_position(str(symbol), "short")

    def get_history(self, symbol: str, n: int, field: str = "close",
                    indicator: str = None, **ind_params) -> pd.Series:
        """最近 n 根 K 线的某字段。

        - 传 `indicator`（如 "RSI"）时，若 n < required_bars(indicator) 直接抛错——
          禁止用不足预热期的样本算递归指标；
        - 返回 Series.attrs["warmup_ok"] 标记「这 n 根是否已过预热期」（False 时禁止出信号）。
        """
        symbol = str(symbol)
        n = int(n)
        if n <= 0:
            raise ValueError(f"get_history 的 n 必须为正整数，收到 {n}")
        frame = self._history_frame(symbol, n)
        if indicator:
            need = ind.required_bars(indicator, **ind_params)
            if n < need:
                raise ValueError(
                    f"get_history({symbol}, {n}) 少于 {indicator} 的预热根数 {need}，"
                    f"算出来的指标带初始化偏差；请把 n 提高到 >= {need}")
        if field not in frame.columns:
            raise ValueError(f"get_history 字段 {field!r} 不存在，可选 {list(frame.columns)}")
        series = frame[field].copy()
        series.attrs["warmup_ok"] = bool(self._warmup_ok.get(symbol, False))
        series.attrs["rows"] = len(frame)
        return series

    def get_history_frame(self, symbol: str, n: int) -> pd.DataFrame:
        return self._history_frame(str(symbol), int(n))

    def _history_frame(self, symbol: str, n: int) -> pd.DataFrame:
        if self._history_provider is not None:
            frame = self._history_provider(symbol, n)
        else:
            if self.fetcher is None:
                raise RuntimeError("策略未注入 history_provider / data_fetcher，无法取历史")
            frame = self.fetcher.get_daily(symbol, end_date=_fmt_date(self._current_date),
                                           adjust="qfq")
        frame = frame.tail(n)
        # 口径信息必须保留（rolling/切片后 attrs 会丢，这里重新标注）
        return frame

    def assert_signal_frame(self, df: pd.DataFrame, indicator_columns=None) -> None:
        """信号入口硬校验：必须带 warmup_ok、预热期不得有被填充的指标值。"""
        signal_gate.check_signal_frame(df, indicator_columns=indicator_columns,
                                       run_mode=self.run_mode)

    def required_bars(self) -> int:
        """本策略所需的最少 K 线根数（引擎长度门槛用，见 config.GATE_CONFORMANCE）。"""
        return int(max(int(self.warmup_bars), 1))

    # ==================== 状态 ====================

    @property
    def current_date(self):
        return self._current_date

    @property
    def prices(self) -> Dict[str, float]:
        return dict(self._prices)

    @property
    def equity(self) -> float:
        return float(self.account.calc_equity(self._prices))

    @property
    def equity_curve(self) -> pd.Series:
        if not self._equity_curve:
            return pd.Series(dtype=float)
        s = pd.Series({pd.Timestamp(r["date"]): r["equity"] for r in self._equity_curve})
        return s.sort_index()

    def is_warmup_ok(self, symbol: str) -> bool:
        return bool(self._warmup_ok.get(str(symbol), False))

    # ==================== 风控 ====================

    def _resolve_warmup_bars(self) -> int:
        if "warmup_bars" in self.params and self.params["warmup_bars"] is not None:
            return max(int(self.params["warmup_bars"]), 1)
        declared = self.meta.get("warmup") or []
        need = 1
        for item in declared:
            if isinstance(item, (tuple, list)) and item:
                name, kw = item[0], (item[1] if len(item) > 1 else {})
                need = max(need, ind.required_bars(name, **(kw or {})))
            else:
                need = max(need, ind.required_bars(str(item)))
        if len(declared) == 0:
            # 从 *_window / *_period 类参数粗推（只作下界，宁可早一点放行由策略自查）
            windows = [int(v) for k, v in self.params.items()
                       if isinstance(v, (int, float)) and str(k).endswith(("window", "period"))
                       and 0 < int(v) < 5000]
            if windows:
                need = max(need, max(windows))
        return max(int(need), 1)

    def _resolve_risk(self) -> dict:
        risk = dict(self.DEFAULT_RISK)
        risk.update({k: self.params[k] for k in self.DEFAULT_RISK if k in self.params})
        if risk.get("max_leverage") is None:
            risk["max_leverage"] = dict(config.RISK["account"]["max_leverage"])
        if risk.get("max_single_symbol_pct") is None:
            risk["max_single_symbol_pct"] = float(
                config.RISK["account"].get("max_single_symbol_pct", 0.20))
        return risk

    def _run_risk_controls(self) -> None:
        """止损/止盈/黑天鹅/熔断：实现见 core/risk.py，策略只执行其产出的平仓指令。"""
        for action in self.risk_manager.on_bar(self._current_date, self._prices):
            volume = float(action.get("volume") or 0)
            if volume <= 0:
                continue
            price = action.get("price")
            if action.get("direction") == "sell":
                result = self.sell(action["symbol"], volume, price)
            else:
                result = self.cover(action["symbol"], volume, price)
            if result.get("status") != "filled":
                self.logger.warning("风控平仓未成交 %s（%s）：%s",
                                    action.get("symbol"), action.get("reason"),
                                    result.get("reason"))

    def _check_position_limits(self, symbol: str, volume: float,
                               price: float = None) -> Optional[str]:
        """单票上限/总杠杆/熔断：实现见 core/risk.py（三引擎共用）。"""
        px = price if price is not None else self._prices.get(symbol)
        return self.risk_manager.check_open(str(symbol), float(volume), px)

    def _is_blacklisted(self, symbol: str) -> bool:
        return self.risk_manager.is_blacklisted(str(symbol), self._bars.get(str(symbol)))


# ==================== 模块级小工具 ====================

def _accepts_bars(func) -> bool:
    """子类 on_tick 是否接受 `bars` 参数（兼容旧签名 on_tick(price_dict)）。"""
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False
    if "bars" in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def _bar_price(bar) -> Optional[float]:
    if isinstance(bar, dict):
        for key in ("close", "price", "last_price"):
            value = bar.get(key)
            if value is not None and np.isfinite(float(value)):
                return float(value)
        return None
    try:
        return float(bar)
    except (TypeError, ValueError):
        return None


def _fmt_date(value) -> Optional[str]:
    if value is None:
        return None
    return pd.Timestamp(value).strftime("%Y%m%d")
