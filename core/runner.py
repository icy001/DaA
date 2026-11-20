"""第 5 步：策略执行器（core/runner.py）

同一份策略代码，被四种环境用完全相同的接口驱动：
    backtest（回测）/ optimize（参数优化，复用 run_backtest）/
    paper（模拟盘）/ live_sim（实盘仿真）。

执行器只做四件事：
  1. 取数并组装 `bar_dict`（每根 bar 带物化字段 `warmup_ok`，供策略层闸门使用）；
  2. 按交易日顺序调用 `strategy.dispatch_bar()` / `dispatch_end_of_day()`；
  3. 每个 bar 结束后按最新价给账户估值，形成净值曲线；
  4. 统计绩效指标（收益 / 年化 / 夏普 / 最大回撤 / 胜率）。

⚠️ 这是第 5 步的**轻量执行器**：单周期、整手撮合、收盘价成交。第 6 步的
「全市场透明回测引擎」会替换它（同样的策略接口），策略代码不需要改。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import config
from core import signal_gate
from core.account import TradingAccount
from core.strategy import BaseStrategy
from core.utils import setup_logger

__all__ = ["StrategyRunner", "run_backtest", "run_paper", "run_optimize"]


class StrategyRunner:
    """按日推进的策略执行器（四种环境共用）。"""

    def __init__(self, strategy_cls, params: dict = None, symbols: List[str] = None,
                 start: str = None, end: str = None, fetcher=None,
                 account: TradingAccount = None, run_mode: str = "backtest",
                 initial_cash: float = None, period: str = "1d",
                 adjust: str = "qfq", logger: logging.Logger = None):
        if not isinstance(strategy_cls, type) or not issubclass(strategy_cls, BaseStrategy):
            raise TypeError("strategy_cls 必须是 BaseStrategy 的子类")
        self.strategy_cls = strategy_cls
        self.params = dict(params or {})
        self.meta = dict(getattr(strategy_cls, "meta", {}) or {})
        self.symbols = [str(s) for s in (symbols or self.params.get("symbols") or [])]
        if not self.symbols:
            raise ValueError("必须提供 symbols（策略参数或调用参数）")
        self.start = str(start or self.params.get("start") or config.DEFAULT_START)
        self.end = str(end or self.params.get("end") or config.DEFAULT_END
                       or pd.Timestamp.today().strftime("%Y-%m-%d"))
        self.run_mode = str(run_mode)
        self.period = str(period)
        self.adjust = str(adjust or "qfq")
        self.logger = logger or setup_logger("runner", config.LOG_DIR / "runner.log")

        if fetcher is None:
            from core.data_fetcher import DataFetcher
            fetcher = DataFetcher()
        self.fetcher = fetcher

        self.account = account or TradingAccount(
            initial_cash if initial_cash is not None else config.INITIAL_CASH,
            fetcher=self.fetcher, run_mode=self.run_mode, logger=self.logger)

        self.frames: Dict[str, pd.DataFrame] = {}
        self.state = {"date": None}
        self.strategy: Optional[BaseStrategy] = None

    # ==================== 取数 ====================

    def load(self) -> Dict[str, pd.DataFrame]:
        for symbol in self.symbols:
            if self.period == "1d":
                frame = self.fetcher.get_daily(symbol, start_date=self.start,
                                               end_date=self.end, adjust=self.adjust)
            else:
                frame = self.fetcher.get_kline(symbol, start_date=self.start,
                                               end_date=self.end, period=self.period,
                                               adjust=self.adjust)
            if frame is None or len(frame) == 0:
                self.logger.warning("标的 %s 无数据，已跳过", symbol)
                continue
            frame = frame.copy()
            frame.index = pd.to_datetime(frame.index)
            self.frames[symbol] = frame.sort_index()
        if not self.frames:
            raise RuntimeError("所有标的均无数据，无法运行策略")
        return self.frames

    def _history_provider(self, symbol: str, n: int) -> pd.DataFrame:
        frame = self.frames.get(str(symbol))
        if frame is None:
            raise KeyError(f"策略请求了未加载的标的 {symbol}")
        asof = self.state["date"]
        window = frame if asof is None else frame.loc[:asof]
        return window.tail(int(n)).copy()

    # ==================== 主循环 ====================

    def run(self) -> dict:
        if not self.frames:
            self.load()
        dates = sorted({d for frame in self.frames.values() for d in frame.index})
        if self.run_mode in ("paper", "live", "live_sim"):
            today = pd.Timestamp.today().normalize()
            dates = [d for d in dates if d <= today]

        strategy = self.strategy_cls(
            account=self.account, data_fetcher=self.fetcher, params=self.params,
            logger=self.logger, run_mode=self.run_mode,
            history_provider=self._history_provider)
        self.strategy = strategy
        # 长度门槛 = max(60, strategy.required_bars())：禁止硬编码 60（见 signal_gate）。
        # 轻量执行器会被走向前/参数优化用短样本反复调用，故只告警不中断；
        # 严格拒绝在第 6 步 Backtester 里执行（那里才是「正式回测」入口）。
        need = signal_gate.min_backtest_bars(strategy=strategy)
        if len(dates) < need:
            self.logger.warning(
                "回测数据仅 %d 根 < 长度门槛 %d 根（max(60, required_bars)）："
                "前 %d 根处于预热期，开仓会被闸门拒绝",
                len(dates), need, strategy.required_bars())
        self.logger.info("策略 %s 启动：mode=%s symbols=%s %s→%s",
                         self.meta.get("name") or type(strategy).__name__,
                         self.run_mode, self.symbols, self.start, self.end)

        seen: Dict[str, int] = {}
        for date in dates:
            self.state["date"] = date
            rows = {}
            for symbol, frame in self.frames.items():
                if date not in frame.index:
                    continue
                row = frame.loc[date]
                if isinstance(row, pd.DataFrame):  # 重复索引取最后一根
                    row = row.iloc[-1]
                rows[symbol] = row.to_dict()
            if not rows:
                continue
            signal_gate.advance_seen(seen, rows.keys())
            bars = signal_gate.build_bar_dict(rows, seen, strategy.warmup_bars, date)
            strategy.dispatch_bar(date, bars)
            strategy.dispatch_end_of_day(date)

        return self._result(strategy)

    def _result(self, strategy: BaseStrategy) -> dict:
        nav = strategy.equity_curve
        metrics = calc_metrics(nav, self.account.trades)
        # 熔断状态随 result 落盘（B-1 裁定：禁止静默复位，回测报告必须携带）
        halt_state = (strategy.risk_manager.halt_state()
                      if getattr(strategy, "risk_manager", None) else None)
        return {
            "strategy": strategy,
            "run_mode": self.run_mode,
            "symbols": self.symbols,
            "params": dict(strategy.params),
            "nav": nav,
            "metrics": metrics,
            "trades": list(strategy.orders),
            "rejected": list(strategy.rejected_orders),
            "halt_state": halt_state,
        }


# ==================== 绩效指标 ====================

def calc_metrics(nav: pd.Series, trades: list = None,
                 annual_days: float = None) -> dict:
    """由净值曲线算绩效。空曲线返回全 0（不抛出，方便优化器批量跑）。"""
    trades = trades or []
    annual_days = float(annual_days or config.INDICATOR_CONFIG["annual_trading_days"])
    if nav is None or len(nav) == 0:
        return {"total_return": 0.0, "annual_return": 0.0, "sharpe": 0.0,
                "max_drawdown": 0.0, "win_rate": 0.0, "trade_count": len(trades),
                "days": 0}
    nav = nav.dropna().astype(float)
    if len(nav) < 2 or nav.iloc[0] <= 0:
        return {"total_return": 0.0, "annual_return": 0.0, "sharpe": 0.0,
                "max_drawdown": 0.0, "win_rate": _win_rate(trades),
                "trade_count": len(trades), "days": int(len(nav))}
    rets = nav.pct_change().dropna()
    total = float(nav.iloc[-1] / nav.iloc[0] - 1.0)
    years = max(len(nav) / annual_days, 1.0 / annual_days)
    annual = float((1.0 + total) ** (1.0 / years) - 1.0) if total > -1 else -1.0
    std = float(rets.std(ddof=1)) if len(rets) > 1 else 0.0
    sharpe = float(rets.mean() / std * np.sqrt(annual_days)) if std > 0 else 0.0
    drawdown = float((nav / nav.cummax() - 1.0).min())
    return {"total_return": total, "annual_return": annual, "sharpe": sharpe,
            "max_drawdown": drawdown, "win_rate": _win_rate(trades),
            "trade_count": len(trades), "days": int(len(nav))}


def _win_rate(trades: list) -> float:
    # 胜率口径归一（v3.53 评审裁定）：胜率 = 已实现结果中盈利的比例，分母只算
    # 平仓笔（action=="close"，即有已实现盈亏结果的近似交易对）。开仓笔没有
    # 结果，不得进分母——首轮 16.60%（分母 488 全部成交）vs 明细 33.47%
    # （分母 242 平仓笔）的分母错配即此教训，两个数不得并列同名「胜率」。
    # 两本账（account.trades 与 place_order 返回）成交记录统一携带 action
    # 字段；缺 action 的历史记录回退按「携带已实现盈亏字段」判定。
    closed = [t for t in trades
              if t.get("status", "filled") == "filled"
              and (t.get("action") == "close"
                   or (t.get("action") is None
                       and ("pnl" in t or "realized_pnl" in t)))]
    pnls = [float(t.get("pnl", t.get("realized_pnl", 0)) or 0) for t in closed]
    if not pnls:
        return 0.0
    return float(sum(1 for p in pnls if p > 0) / len(pnls))


# ==================== 四种环境入口 ====================

def run_backtest(strategy_cls, params: dict = None, symbols: List[str] = None,
                 start: str = None, end: str = None, fetcher=None,
                 initial_cash: float = None, account=None, adjust: str = "qfq") -> dict:
    """回测：本地模拟撮合，用于验证想法。"""
    runner = StrategyRunner(strategy_cls, params=params, symbols=symbols, start=start,
                            end=end, fetcher=fetcher, account=account,
                            run_mode="backtest", initial_cash=initial_cash, adjust=adjust)
    return runner.run()


def run_paper(strategy_cls, params: dict = None, symbols: List[str] = None,
              start: str = None, end: str = None, fetcher=None,
              initial_cash: float = None, account=None, adjust: str = "qfq") -> dict:
    """模拟盘：实时/延迟行情 + 虚拟账户撮合（数据时效闸门生效）。"""
    runner = StrategyRunner(strategy_cls, params=params, symbols=symbols, start=start,
                            end=end, fetcher=fetcher, account=account,
                            run_mode="paper", initial_cash=initial_cash, adjust=adjust)
    return runner.run()


def run_optimize(strategy_cls, param_grid: dict, symbols: List[str] = None,
                 start: str = None, end: str = None, fetcher=None,
                 method: str = "grid", n_iter: int = 30, seed: int = 42,
                 initial_cash: float = None, top_n: int = 10) -> dict:
    """参数优化：复用回测执行器，按目标函数找「参数平原」。"""
    from research.optimizer import create_optimizer
    optimizer = create_optimizer(method, param_grid, n_iter=n_iter, seed=seed)

    def objective(params: dict) -> dict:
        result = run_backtest(strategy_cls, params=params, symbols=symbols,
                              start=start, end=end, fetcher=fetcher,
                              initial_cash=initial_cash)
        return result["metrics"]

    return optimizer.run(objective, top_n=top_n)
