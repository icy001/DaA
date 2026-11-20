"""第 6 步：全市场透明回测引擎（core/backtester.py）

逐 K 线驱动、不依赖第三方回测框架，每一笔成交都能在日志/CSV 里追溯。设计要点：

【闸门只调用、不重写（6.0）】
  - `warmup_ok` 由 `core/signal_gate.py::build_bar_dict` 逐标的写入 bar_dict，
    缺列/NaN 直接报错；
  - 开仓（buy/short）在 `place_order` 里过预热闸门，平仓（sell/cover）豁免；
  - 长度门槛 = `max(60, strategy.required_bars())`（`signal_gate.ensure_min_bars`），
    禁止硬编码 60（MACD required_bars≈135，固定 60 会让 60~70 根标的全段预热、静默零成交）；
  - 多标的对齐用 `signal_gate.align_frames`，`data_asof_date` / `price_adjust` /
    `warmup_ok` 三个物化列逐标的保留。

【成交模型 `ExecutionModel`（三引擎共用 `core/execution.py`，通过 account.execution_model 挂载）】
  - 市价单：买入 = 开盘价×(1+滑点)，卖出 = 开盘价×(1-滑点)；
  - 涨停买不进 / 跌停卖不出：当日开盘价触及涨跌停即拒单；
  - 单笔成交量 ≤ 当日成交量 × 市场分档比例（EXECUTION_MODEL.volume_limit_pct_by_market，
    超出按最小交易单位截断，不足一手拒单）；
  - 限价单：当日最高/最低价触及限价才成交，成交价取限价（更不利一方）；
  - T+0/T+1 由 `TradingAccount` 的撮合规则执行（500 现货 T+1、期货/可转债 T+0）；
  - 手续费/印花税/过户费全部走 `config` 真实费率，回测不设 0 手续费。

【数据准备】
  - 取日线 → 校验列 → 未来函数检测（列名 lead/next/future 或与次日收益相关性 >0.9 直接报错）
    → 取交易日交集 → 基准数据（失败只告警）→ 流动性扫描（日均成交额 <500 万告警）。

【结果】
  - `calc_metrics()`：收益/风险/风险调整/交易/杠杆五类指标 + 分市场、分多空统计；
  - `plot_results()`：净值 vs 基准、回撤、月度热力图、每笔盈亏分布、持仓市值饼图，
    杠杆品种额外输出保证金占用与杠杆率曲线；
  - `save_results()`：trades.csv / equity.csv / metrics.json / *.png；
  - `detect_traps()`：未来函数、幸存者偏差、过拟合、流动性、滑点五类陷阱提示。
"""
from __future__ import annotations

import json
import logging
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import config
from core import signal_gate
from core.account import DERIVATIVE_MARKETS, TradingAccount
from core.execution import ExecutionModel  # 三引擎共用：只调用、不重写
from core.strategy import BaseStrategy
from core.utils import setup_logger
from data import pit_index  # 13.0：点内成分股闸门（禁止当前成分股/关闭 PIT 回测）

__all__ = [
    "Backtester",
    "BacktestResult",
    "ExecutionModel",
    "calc_metrics",
    "detect_lookahead",
    "run",
]

# 流动性告警阈值：日均成交额 < 500 万
LIQUIDITY_MIN_AMOUNT = 5_000_000.0
# 滑点过低提示阈值
SLIPPAGE_WARN = 0.001


# ==================== 未来函数检测 ====================

_LEAD_NAME_RE = r"(^|[_\W])(lead|next|future|fwd|shift)([_\W]|$)"


def detect_lookahead(frame: pd.DataFrame, symbol: str = "",
                     corr_threshold: float = 0.9) -> List[str]:
    """检测单标的帧里的未来数据泄漏；返回问题描述（空表示通过）。

    两类信号：
      1) 列名含 lead / next / future / fwd / shift；
      2) 任意数值列与「次日收益」的相关系数绝对值 > 0.9（说明这一列本身就是未来价）。
    """
    problems: List[str] = []
    if frame is None or len(frame) < 30:
        return problems
    for col in frame.columns:
        if pd.api.types.is_numeric_dtype(frame[col]) and re.search(
                _LEAD_NAME_RE, str(col), flags=re.IGNORECASE):
            problems.append(f"{symbol} 列 {col!r} 命名疑似未来数据（lead/next/future）")
    if "close" not in frame.columns:
        return problems
    fwd_ret = frame["close"].pct_change().shift(-1)
    for col in frame.columns:
        if not pd.api.types.is_numeric_dtype(frame[col]):
            continue
        series = frame[col]
        if series.nunique(dropna=True) < 5:
            continue
        try:
            corr = series.pct_change().corr(fwd_ret)
        except (TypeError, ValueError):
            continue
        if corr is not None and np.isfinite(corr) and abs(corr) > corr_threshold:
            problems.append(
                f"{symbol} 列 {col!r} 与次日收益相关性 {corr:.3f} > {corr_threshold}，疑似未来函数")
    return problems


# ==================== 回测结果 ====================

class BacktestResult:
    """回测结果容器（策略名、净值、交易、指标、陷阱提示）。"""

    def __init__(self, strategy_name: str, nav: pd.DataFrame, trades: pd.DataFrame,
                 metrics: dict, traps: List[dict], benchmark: pd.DataFrame = None,
                 meta: dict = None):
        self.strategy_name = strategy_name
        self.nav = nav
        self.trades = trades
        self.metrics = metrics
        self.traps = traps
        self.benchmark = benchmark if benchmark is not None else pd.DataFrame()
        self.meta = dict(meta or {})
        # v3.53 扩围前置（D-1）：拒单与熔断状态随正式引擎结果落盘
        self.rejected: List[dict] = []
        self.halt_state: dict = {}
        self.run_mode: str = "backtest"
        self.symbols: List[str] = []
        self.params: dict = {}
        # 引擎标识护栏（评审裁定六）：正式引擎结果必须携带 engine 标识，
        # CLI 留痕快照落盘——「哪台引擎跑的」从此可审计
        self.engine: str = "backtester"

    def to_cli_dict(self) -> dict:
        """CLI 留痕/打印所需的 dict 形态（与 core/runner.StrategyRunner._result 键兼容）。"""
        nav = self.nav
        trades = self.trades.to_dict("records") if isinstance(self.trades, pd.DataFrame) \
            else list(self.trades or [])
        return {
            "strategy": self.strategy_name,
            "run_mode": self.run_mode,
            "engine": self.engine,
            "symbols": list(self.symbols),
            "params": dict(self.params),
            "nav": nav,
            "metrics": dict(self.metrics),
            "trades": trades,
            "rejected": list(self.rejected),
            "halt_state": dict(self.halt_state or {}),
        }

    def to_dict(self) -> dict:
        return {"strategy": self.strategy_name, "metrics": self.metrics,
                "traps": self.traps, "meta": self.meta}

    def report(self) -> str:
        m = self.metrics
        lines = [
            f"===== 回测报告：{self.strategy_name} =====",
            f"总收益率 {_pct(m.get('total_return'))} | 年化 {_pct(m.get('annual_return'))} "
            f"| 基准 {_pct(m.get('benchmark_return'))} | 超额 {_pct(m.get('excess_return'))}",
            f"最大回撤 {_pct(m.get('max_drawdown'))}（{m.get('max_drawdown_days')} 天）"
            f" | 夏普 {_num(m.get('sharpe'))} | 索提诺 {_num(m.get('sortino'))}"
            f" | 卡玛 {_num(m.get('calmar'))}",
            f"交易 {m.get('trade_count')} 笔 | 胜率 {_pct(m.get('win_rate'))}"
            f" | 盈亏比 {_num(m.get('profit_factor'))} | 平均持仓 {_num(m.get('avg_holding_days'))} 天",
            # 期货口径披露（v3.54 终验裁定）：收益率分母=初始权益（与股票一致可横向
            # 对比）；保证金占用率与名义敞口杠杆倍数单独披露，避免高杠杆下收益歧义
            f"手续费合计 {_num(m.get('total_commission'))} | 保证金占用率 "
            f"{_pct(m.get('avg_margin_utilization'))}（峰 {_pct(m.get('max_margin_utilization'))}）"
            f" | 名义杠杆 {_num(m.get('avg_leverage'))}（峰 {_num(m.get('max_leverage'))}）"
            f" | 爆仓次数 {m.get('margin_call_count')}",
            "收益率分母 = 初始权益（INITIAL_CASH 口径，与股票回测一致可横向对比）",
        ]
        if self.traps:
            lines.append("陷阱提示：")
            lines.extend(f"  [{t['level']}] {t['message']}" for t in self.traps)
        return "\n".join(lines)

    # -- 落盘 --
    def save(self, output_dir=None, plot: bool = True) -> Dict[str, str]:
        out = Path(output_dir or config.BACKTEST_DIR)
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"{self.strategy_name}_{stamp}"
        paths = {}
        trade_path = out / f"{base}_trades.csv"
        self.trades.to_csv(trade_path, index=False, encoding="utf-8-sig")
        paths["trades"] = str(trade_path)
        nav_path = out / f"{base}_equity.csv"
        self.nav.to_csv(nav_path, index=False, encoding="utf-8-sig")
        paths["equity"] = str(nav_path)
        metric_path = out / f"{base}_metrics.json"
        metric_path.write_text(json.dumps({"metrics": self.metrics, "traps": self.traps,
                                           "meta": self.meta}, ensure_ascii=False,
                                          indent=2, default=str), encoding="utf-8")
        paths["metrics"] = str(metric_path)
        if plot:
            # 基准曲线必须传 benchmark_frame（DataFrame：date + benchmark_equity）；
            # 原传 self.benchmark（str 代码）导致绘图基准线从未画出（x2 排查整改）
            fig_path = plot_results(self.nav, self.trades, self.metrics,
                                    self.benchmark_frame,
                                    strategy_name=self.strategy_name, save_path=out / f"{base}.png")
            if fig_path:
                paths["figure"] = str(fig_path)
        return paths


# ==================== 主引擎 ====================

def warn_derivative_research(deriv_markets, logger=None) -> None:
    """闸门7（v3.53 评审五轮）：衍生品回测启动提示——放行但明确打印。

    实盘路径硬拦在 core/account.py::place_order（三引擎必经）与
    live/live_trader.py::_precheck（实盘收口，直接 raise 穿透拒单捕获）。
    """
    notice = ("衍生品回测仅用于研究，实盘路径硬拦：市场 " + ",".join(deriv_markets)
              + " 在 live 模式下报单直接 raise（DerivativeMarketLiveForbidden）；"
                "本回测结果不得作为实盘依据")
    print(f"⚠ {notice}")
    if logger is not None:
        logger.warning("%s", notice)


class Backtester:
    """逐日驱动的透明回测引擎。"""

    def __init__(self, strategy_class, strategy_params: dict = None, symbols: List[str] = None,
                 start_date: str = None, end_date: str = None, initial_capital: float = None,
                 benchmark: str = None, market_type: str = None, fetcher=None,
                 slippage: float = None, max_volume_pct: float = None,
                 run_mode: str = "backtest", adjust: str = "qfq",
                 logger: logging.Logger = None, output_dir=None,
                 liquidate_at_end: bool = True, universe: str = None,
                 period: str = "1d"):
        if not isinstance(strategy_class, type) or not issubclass(strategy_class, BaseStrategy):
            raise TypeError("strategy_class 必须是 BaseStrategy 的子类")
        self.strategy_class = strategy_class
        self.meta = dict(getattr(strategy_class, "meta", {}) or {})
        self.params = dict(strategy_params or {})
        self.universe = str(universe or self.params.get("universe") or "")
        self.symbols = [str(s) for s in (symbols or self.params.get("symbols") or [])]
        if not self.symbols and not self.universe:
            raise ValueError("必须提供 symbols 或 universe")
        self.start_date = str(start_date or self.params.get("start") or config.DEFAULT_START)
        self.end_date = str(end_date or self.params.get("end")
                            or pd.Timestamp.today().strftime("%Y-%m-%d"))
        self.initial_capital = float(config.INITIAL_CASH if initial_capital is None
                                      else initial_capital)
        # 基准默认集中引用 config.BENCHMARK（v3.53 评审四轮：换 H00300 全收益指数，
        # 与策略含息记账同口径；禁止硬编码 000300 导致含息超额被系统性高估）
        self.benchmark = str(benchmark or config.BENCHMARK)
        self.market_type = market_type
        # 期货基准规则（v3.54 终验裁定）：禁止跨资产混用——期货池永不套股票基准。
        # 股指期货按 config.FUTURE_BENCHMARK_MAP 映射全收益指数（映射 None=仅绝对
        # 收益）；商品期货基准置空，prepare 后自动构建「同品种连续合约 buy&hold」；
        # 期货+非期货混合池直接 raise（基准口径不可混合，请分开回测）
        self._explicit_benchmark = benchmark
        self.future_benchmark_mode, self.benchmark = self._resolve_future_benchmark(
            symbols, benchmark)
        self.run_mode = str(run_mode)
        self.adjust = str(adjust or "qfq")
        # v3.53 扩围：行情周期（config.SUPPORTED_PERIODS 8 种取值；"1d" 行为不变）
        self.period = str(period or "1d")
        # 分钟级量限分母：{symbol: 最近已完结交易日的全天成交量}（防「单分钟 1%」
        # 过度宽松；日线不启用，行为与既有验收一致）
        self._intraday = self.period != "1d"
        self._day_volume_hist: Dict[str, pd.Series] = {}
        self._day_volume_base: Dict[str, float] = {}
        self._current_day = None
        self.logger = logger or setup_logger("backtester", config.LOG_DIR / "backtester.log")
        self.output_dir = Path(output_dir or config.BACKTEST_DIR)
        self.liquidate_at_end = bool(liquidate_at_end)

        if fetcher is None:
            from core.data_fetcher import DataFetcher
            fetcher = DataFetcher()
        self.fetcher = fetcher

        self.execution = ExecutionModel(slippage=slippage, max_volume_pct=max_volume_pct,
                                        run_mode=self.run_mode, logger=self.logger)

        # 运行时状态
        self.frames: Dict[str, pd.DataFrame] = {}
        self.market_of: Dict[str, str] = {}
        self.dates: List[pd.Timestamp] = []
        self.benchmark_frame: Optional[pd.DataFrame] = None
        self.last_bar_dict: Dict[str, dict] = {}
        self.min_bars: Optional[int] = None
        self.strategy: Optional[BaseStrategy] = None
        self.account: Optional[TradingAccount] = None
        self.margin_calls = 0
        # 期货换月平开成交对数（v3.53 评审七轮④：换月日必须平旧开新）
        self.roll_count = 0
        self.state = {"date": None}
        self._prev_close: Dict[str, float] = {}
        # 双价体系：各标的「上一根 bar 的 adj_factor」——除权日涨跌停参考价
        # = 昨收 × (昨日因子/当日因子)（交易所除权参考价：昨收减现金红利/配股调整，
        # 与因子比在因子表精度内等价；非除权日比值=1，行为不变）
        self._prev_adj_factor: Dict[str, float] = {}
        self._lookahead_problems: List[str] = []
        # match_price_basis=next_*：决策 bar 与成交 bar 分离（订单排队到下一根撮合）
        self._bar_index = -1
        self._pending_orders: List[dict] = []

    # ==================== 数据准备 ====================

    def _fetch(self, symbol: str) -> pd.DataFrame:
        kwargs = dict(start_date=self.start_date, end_date=self.end_date, adjust=self.adjust)
        market = self.market_of.get(symbol)
        if market:
            kwargs["market_type"] = market
        if self._intraday:
            # 分钟线：按 config.SUPPORTED_PERIODS 周期取数（历史回填/当日源路由
            # 由数据层 get_kline 决定，引擎不重复实现）
            kwargs["period"] = self.period
            try:
                return self.fetcher.get_kline(symbol, **kwargs)
            except TypeError:
                kwargs.pop("market_type", None)
                return self.fetcher.get_kline(symbol, **kwargs)
        try:
            return self.fetcher.get_daily(symbol, **kwargs)
        except TypeError:
            kwargs.pop("market_type", None)
            return self.fetcher.get_daily(symbol, **kwargs)

    def _prepare_symbol(self, symbol: str) -> Optional[pd.DataFrame]:
        frame = self._fetch(symbol)
        if frame is None or len(frame) == 0:
            self.logger.warning("标的 %s 无数据，已跳过", symbol)
            return None
        frame = frame.copy()
        frame.index = pd.to_datetime(frame.index)
        frame = frame.sort_index()
        frame = frame[~frame.index.duplicated(keep="last")]
        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"{symbol} 缺少必要列 {sorted(missing)}，无法回测")
        # 物化列：三引擎必须喂 warmup_ok / data_asof_date / price_adjust
        if "price_adjust" not in frame.columns:
            frame["price_adjust"] = self.adjust
        if "data_asof_date" not in frame.columns:
            frame["data_asof_date"] = frame.index
        return frame

    def prepare(self) -> Dict[str, pd.DataFrame]:
        # 13.0：回测入口强制 PIT 闸门；股票池只允许走带日期的点内成分股
        pit_index.assert_pit_enabled(self.run_mode)
        if self.universe:
            self.symbols = pit_index.get_index_members(self.universe, self.start_date)
        raw: Dict[str, pd.DataFrame] = {}
        for symbol in self.symbols:
            market = self.market_type or config.detect_market_type(symbol)
            self.market_of[symbol] = market
            frame = self._prepare_symbol(symbol)
            if frame is None:
                continue
            # 未来函数检测：有问题直接报错，不进入回测
            problems = detect_lookahead(frame, symbol)
            if problems:
                raise ValueError("未来函数检测未通过：" + "；".join(problems))
            raw[symbol] = frame
        if not raw:
            raise RuntimeError("所有标的均无数据，无法回测")

        self._lookahead_problems = []
        # 对齐交易日交集；三个物化列逐标的保留
        self.frames = signal_gate.align_frames(raw, how="intersection")
        self.dates = sorted({d for frame in self.frames.values() for d in frame.index})
        if self._intraday:
            # 分钟级量限分母预计算：每 symbol 按日聚合全天成交量
            # （撮合时用「最近已完结交易日」的全天量，无未来函数）
            for symbol, frame in self.frames.items():
                vol = pd.to_numeric(frame.get("volume"), errors="coerce").fillna(0.0)
                self._day_volume_hist[symbol] = vol.groupby(vol.index.date).sum()
        self._warn_liquidity()
        self.benchmark_frame = self._fetch_benchmark()
        return self.frames

    # ---- 期货基准规则（v3.54 终验裁定：禁止跨资产混用） ----

    @staticmethod
    def _variety_of(symbol: str) -> str:
        return "".join(c for c in str(symbol).upper() if c.isalpha())

    def _resolve_future_benchmark(self, symbols, explicit_benchmark):
        """期货池基准解析：返回 (mode, benchmark)。

        mode=None  非期货池 → 沿用股票基准（行为不变）；
        mode="stock_index"  股指期货 → config.FUTURE_BENCHMARK_MAP 映射的全收益指数
                 （映射 None / 多品种映射不一致 → benchmark=None 仅绝对收益 + 告警）；
        mode="commodity_buyhold"  商品期货 → benchmark=None，prepare 后构建
                 同品种连续合约 buy&hold 基准并标注；
        期货+非期货混合池 → raise（基准口径不可混合）。
        显式传入 benchmark 时仅当与规则解析结果一致才放行，否则 raise（禁止
        跨资产混用，如给 RB 传 H00300）。
        """
        mkts = {config.detect_market_type(s) for s in (symbols or [])}
        if not (mkts & DERIVATIVE_MARKETS):
            return None, explicit_benchmark or config.BENCHMARK
        if not mkts <= DERIVATIVE_MARKETS:
            raise ValueError(
                f"回测池混含期货与非期货标的 {sorted(symbols)}：基准口径不可混合"
                "（禁止跨资产混用基准），请分开回测")
        stock_index = set(config.FUTURE_BENCHMARK_MAP)
        varieties = {self._variety_of(s) for s in symbols}
        if varieties <= stock_index:                       # 股指期货池
            codes = {config.FUTURE_BENCHMARK_MAP[v] for v in varieties}
            if len(codes) == 1 and None not in codes:
                bench = codes.pop()
            else:
                bench = None                               # None 映射/多品种不一致
                missing = sorted(v for v in varieties
                                 if not config.FUTURE_BENCHMARK_MAP.get(v))
                self._pending_bench_note = (
                    f"股指期货品种 {missing} 无已登记的全收益指数映射（禁止猜测代码），"
                    "仅披露绝对收益与风险指标")
            if explicit_benchmark and explicit_benchmark != (bench or ""):
                raise ValueError(
                    f"股指期货回测基准必须用治理面映射 {bench}，收到 {explicit_benchmark!r}"
                    "（禁止跨资产混用基准）")
            return "stock_index", bench
        # 商品期货（含外盘期货）池：无公开现货指数基准
        if explicit_benchmark:
            raise ValueError(
                f"商品期货回测无对应外部基准（禁止跨资产混用），收到 {explicit_benchmark!r}；"
                "引擎将自动以同品种连续合约 buy&hold 作参照并明确标注")
        return "commodity_buyhold", None

    def _build_buyhold_benchmark(self) -> Optional[pd.DataFrame]:
        """商品期货 buy&hold 基准：同品种连续合约（调整序列）首日买入持有权益。"""
        for symbol, frame in self.frames.items():
            if "close" not in frame.columns or not len(frame):
                continue
            close = pd.to_numeric(frame["close"], errors="coerce").dropna()
            if len(close) < 2:
                continue
            bench = pd.DataFrame({
                "benchmark_equity": self.initial_capital
                * close / float(close.iloc[0])},
                index=close.index)
            bench.attrs.update({
                "future_benchmark": "self_continuous_buy_hold",
                "note": "商品期货无对应公开基准，参照=同品种连续合约调整序列买入持有；"
                        "仅披露绝对收益与风险指标，禁止与股票基准混用",
            })
            self.logger.info(
                "期货基准：%s 无对应公开基准，采用同品种连续合约 buy&hold 参照"
                "（仅披露绝对收益与风险指标）", symbol)
            return bench
        return None

    def _fetch_benchmark(self) -> Optional[pd.DataFrame]:
        if not self.benchmark:
            if self.future_benchmark_mode == "commodity_buyhold":
                return self._build_buyhold_benchmark()
            note = getattr(self, "_pending_bench_note", None)
            if note:
                self.logger.warning("%s", note)
            return None
        try:
            frame = self.fetcher.get_daily(
                self.benchmark, start_date=self.start_date, end_date=self.end_date,
                adjust="none", market_type="cn_index")
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("基准 %s 取数失败（%s），基准指标将留空", self.benchmark, exc)
            return None
        if frame is None or len(frame) == 0:
            self.logger.warning("基准 %s 无数据，基准指标将留空", self.benchmark)
            return None
        frame = frame.copy()
        frame.index = pd.to_datetime(frame.index)
        return frame.sort_index()

    def _warn_liquidity(self) -> None:
        for symbol, frame in self.frames.items():
            if "amount" not in frame.columns:
                continue
            avg = float(frame["amount"].tail(250).mean() or 0)
            if 0 < avg < LIQUIDITY_MIN_AMOUNT:
                self.logger.warning("%s 日均成交额 %.0f 元 < %.0f（流动性风险）",
                                    symbol, avg, LIQUIDITY_MIN_AMOUNT)

    # ==================== 主循环 ====================

    def _history_provider(self, symbol: str, n: int) -> pd.DataFrame:
        frame = self.frames.get(str(symbol))
        if frame is None:
            raise KeyError(f"策略请求了未加载的标的 {symbol}")
        asof = self.state["date"]
        window = frame if asof is None else frame.loc[:asof]
        return window.tail(int(n)).copy()

    def run(self) -> BacktestResult:
        if not self.frames:
            self.prepare()

        # 闸门7（v3.53 评审五轮）：衍生品回测仅用于研究——放行但启动时明确打印；
        # 实盘路径硬拦在 core/account.py::place_order 与 live/live_trader.py::_precheck
        deriv_markets = sorted({self.market_of.get(s) or config.detect_market_type(s)
                                for s in self.symbols} & DERIVATIVE_MARKETS)
        if deriv_markets:
            warn_derivative_research(deriv_markets, self.logger)

        self.account = TradingAccount(self.initial_capital, fetcher=self.fetcher,
                                      run_mode=self.run_mode, logger=self.logger)
        self.account.execution_model = self.execution
        self._on_account_ready()
        strategy = self.strategy_class(
            account=self.account, data_fetcher=self.fetcher, params=self.params,
            logger=self.logger, run_mode=self.run_mode,
            history_provider=self._history_provider)
        self.strategy = strategy
        # 6.0 C2：长度门槛 = max(60, strategy.required_bars())，禁止硬编码 60
        self.min_bars = signal_gate.ensure_min_bars(
            self._bar_count_for_gate(), strategy=strategy, label="回测")
        self.logger.info("回测启动：%s symbols=%s %s→%s bars=%d min_bars=%d slippage=%.4f",
                         self.meta.get("name") or type(strategy).__name__,
                         self.symbols, self.start_date, self.end_date,
                         len(self.dates), self.min_bars, self.execution.slippage)

        seen: Dict[str, int] = dict(self._initial_seen())
        self._pending_orders = []
        # 撮合时点基准：next_* → 订单排队到下一根 bar；same_* → 同根撮合（unsafe）
        self.account.deferred_executor = (
            self._queue_order if self.execution.bar_offset >= 1 else None)
        for bar_index, date in enumerate(self.dates):
            self._bar_index = bar_index
            self.account.current_bar_index = bar_index
            self.state["date"] = date
            rows: Dict[str, dict] = {}
            prices: Dict[str, float] = {}
            for symbol, frame in self.frames.items():
                if date not in frame.index:
                    continue
                row = frame.loc[date]
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[-1]
                rows[symbol] = row.to_dict()
                # 期货结算价口径（v3.53 评审七轮）：涨跌停/保证金/强平以【昨结算价】
                # 为准——bar 带 settle 列时盯市价优先取结算价（收盘价仅作回退），
                # 结算价口径错会让强平阈值整体偏移（9% 保证金 ≈ 11 倍杠杆）
                px = row.get("settle")
                if px is None or not (np.isfinite(float(px)) and float(px) > 0):
                    px = row.get("close")
                if px is not None and np.isfinite(float(px)) and float(px) > 0:
                    prices[symbol] = float(px)
            if not rows:
                continue
            signal_gate.advance_seen(seen, rows.keys())
            bars = signal_gate.build_bar_dict(rows, seen, strategy.warmup_bars, date)
            self.last_bar_dict = bars

            # 分钟级量限分母：换日时更新为「最近已完结交易日」的全天成交量
            # （当日量在 bar 开始时不可知，用昨日全天量 = 无未来函数；
            #   日线不启用——日线 bar 的 volume 即当日全天量，行为不变）
            if self._intraday:
                d = pd.Timestamp(date).date()
                if d != self._current_day:
                    self._current_day = d
                    base = {}
                    for sym, hist in self._day_volume_hist.items():
                        prior = hist[hist.index < d]
                        if len(prior) and float(prior.iloc[-1]) > 0:
                            base[sym] = float(prior.iloc[-1])
                    self._day_volume_base = base
            self.execution.set_context(bars, self._prev_close, bar_index=bar_index,
                                       day_volume_base=(self._day_volume_base
                                                        if self._intraday else None))
            # 0：先撮合上一根 bar 排队的订单（决策 bar#t → 成交 bar#t+1）
            self._fill_pending_orders(date)
            # 1-4：策略出信号 → 成交模型撮合（same_* 时同根，next_* 时入队）
            self._dispatch(date, bars)
            # 4.5：期货换月日平旧开新（评审七轮④：持仓跨换月不动 = 每轮换月 P&L 全是假的）
            self._handle_contract_rolls(date, bars)
            # 6：保证金检查/强平
            closed = self.account.check_margin_call(prices)
            self.margin_calls += len(closed)
            # 5+7+9：盯市、到期结算、权益快照
            snapshot = self.account.end_of_day(date, prices)
            self._enrich_snapshot(snapshot, prices)
            # 8：日终回调
            strategy.dispatch_end_of_day(date)
            self._after_bar(date, prices)
            # 前收与撮合同空间（v3.53 双价体系）：bar 带 raw_close 时取原始价前收，
            # 涨跌停校验在 raw 空间做（除权日 adj 前收跨因子跳变，比例失真）。
            # 除权日涨跌停参考价（v3.53 评审四轮核实 b）：交易所按「昨收减现金红利、
            # 配股调整后」的除权参考价定 ±10% 带，不是直接昨收——数学上
            # 参考价 = 昨收 × (昨日因子/当日因子)，与交易所公式在因子表精度内等价
            # （600519 2025-06-26 实测：昨收 1435.86 × 0.98078 = 1408.27 ≈ 1435.86 − 27.624）。
            # 非除权日因子比值 = 1，行为与昨收完全一致。
            self._prev_close = self._build_prev_close(bars)
            self._prev_adj_factor = {
                s: float(b.get("adj_factor") or 1.0)
                for s, b in bars.items() if b.get("adj_factor")}

        if self._pending_orders:
            self.logger.warning("回测结束仍有 %d 笔排队订单未撮合（最后一根 bar 的信号无法"
                                "在下一根成交），已丢弃：%s", len(self._pending_orders),
                                [o.get("symbol") for o in self._pending_orders])
            self._pending_orders = []
        if self.liquidate_at_end:
            self._liquidate_all()
        return self._build_result(strategy)

    # ---------- 撮合时点（E1） ----------

    def _build_prev_close(self, bars: Dict[str, dict]) -> Dict[str, float]:
        """下一根 bar 的涨跌停/风控前收（v3.53 评审四/六/七轮）。

        - 期货帧（带 settle）：前收 = 昨【结算价】（交易所涨跌停/强平口径，
          评审七轮：昨收口径会让强平阈值整体偏移，9% 保证金 ≈ 11 倍杠杆）；
        - 双价帧（带 raw_close，股票）：除权参考价 = raw 昨收 × (昨日因子/当日因子)，
          与交易所「昨收减现金红利/配股调整」公式在因子表精度内等价；
          非除权日比值 = 1 → 行为与昨收完全一致；
        - 日线帧（无上述列）：沿用主列 close（既有行为不变）。
        """
        out = {}
        for s, b in bars.items():
            if b.get("settle") is not None:
                out[s] = float(b.get("settle"))          # 期货：昨结算价口径
            elif b.get("raw_close"):
                f_today = float(b.get("adj_factor") or 1.0)
                f_prev = self._prev_adj_factor.get(s, f_today)
                out[s] = float(b.get("raw_close")) * (f_prev / f_today)
            else:
                out[s] = float(b.get("close") or 0)
        return out

    def _handle_contract_rolls(self, date, bars: Dict[str, dict]) -> None:
        """期货换月日平旧开新（v3.53 评审七轮④）。

        持仓跨换月不动 = 成本停留在旧合约绝对价位、盯市切到新合约绝对价位，
        月差会被记成虚构盈亏——评审裁定「每轮换月的 P&L 都是假的」。
        时点：量交叉当日收盘确认 → 双腿均按当日收盘价【机械】成交（收盘后
        无再决策，与序列「当日量交叉切换」口径一致，无未来函数）；
          - 平旧 @ 旧合约当日实际收盘（bar["roll_exit_price"]，真实旧合约盈亏，
            手续费按平仓费率如实入账）；
          - 开新 @ 新合约当日实际收盘（bar["raw_close"]，成本切换到新合约
            raw 空间，与后续盯市/结算价口径对齐），保证金按新合约价格重估。
        换月是机制性调仓而非策略信号：直连 _execute（与强平同级，不受
        涨跌停/量限约束），回测口径假设换月双腿必然成交；实盘换月由
        live_trader 报单链路处理，不走此路径。
        """
        day = pd.Timestamp(date).date()
        for s, b in bars.items():
            if not b.get("roll"):
                continue
            entry_px = b.get("raw_close")
            exit_px = b.get("roll_exit_price")
            if not entry_px or entry_px <= 0 or not exit_px or exit_px <= 0:
                self.logger.warning(
                    "换月日 %s %s 缺双腿价格（raw_close=%s roll_exit_price=%s），"
                    "持仓跨月未滚动——月差将计入盯市盈亏", date, s, entry_px, exit_px)
                continue
            for book, side, close_dir, open_dir in (
                    (self.account.positions, "long", "sell", "buy"),
                    (self.account.short_positions, "short", "cover", "short")):
                pos = book.get(s)
                if pos is None or pos.volume <= 0:
                    continue
                market = pos.market or config.detect_market_type(s)
                rule = self.account._rule_of(market, s)
                vol = pos.volume
                res_close = self.account._execute(
                    symbol=s, market=market, rule=rule, kind=pos.kind,
                    action="close", side=side, direction=close_dir, volume=vol,
                    price=float(exit_px), day=day, order_time=date, is_etf=None,
                    underlying_price=None, hold_days=None, option_type=None,
                    strike=None, expiry=None)
                if res_close.get("status") != "filled":
                    self.logger.warning("换月平旧失败 %s：%s", s, res_close.get("reason"))
                    continue
                res_open = self.account._execute(
                    symbol=s, market=market, rule=rule, kind=pos.kind,
                    action="open", side=side, direction=open_dir, volume=vol,
                    price=float(entry_px), day=day, order_time=date, is_etf=None,
                    underlying_price=None, hold_days=None, option_type=None,
                    strike=None, expiry=None)
                if res_open.get("status") != "filled":
                    # 平旧已成交、开新被拒：敞口空档如实暴露（资金不足等），
                    # 禁止静默当作滚动成功
                    self.logger.warning("换月开新失败 %s（已平旧未开新，敞口空档）：%s",
                                        s, res_open.get("reason"))
                    continue
                self.roll_count += 1
                self.logger.info(
                    "换月平开 %s %s：平旧 %d 手 @ %.2f（前合约 %s）→ 开新 %d 手 @ %.2f"
                    "（现合约 %s），手续费 %.2f+%.2f",
                    date, s, vol, float(exit_px), b.get("roll_prev_contract"),
                    vol, float(entry_px), b.get("contract"),
                    float(res_close.get("commission") or 0),
                    float(res_open.get("commission") or 0))

    def _queue_order(self, kwargs: dict) -> bool:
        """账户把订单交给引擎排队：记下决策 bar 下标，下一根 bar 以 fill_now 撮合。"""
        kwargs = dict(kwargs)
        kwargs["signal_bar_index"] = self._bar_index
        self._pending_orders.append(kwargs)
        return True

    def _fill_pending_orders(self, date) -> None:
        """用当前 bar 撮合上一根 bar 排队的订单（严禁回填决策当根价格）。"""
        if not self._pending_orders:
            return
        queue, self._pending_orders = self._pending_orders, []
        for kwargs in queue:
            symbol = kwargs.get("symbol")
            kwargs["order_time"] = date
            frame = self.frames.get(str(symbol))
            if frame is not None:
                kwargs["data"] = frame
            result = self.account.place_order(fill_now=True, **kwargs)
            if result.get("status") != "filled":
                self.logger.warning("排队订单 %s %s 未成交：%s", symbol,
                                    kwargs.get("direction"), result.get("reason"))

    def _on_account_ready(self) -> None:
        """账户创建完成、策略实例化之前的钩子（模拟盘用它恢复持久化账户）。"""

    def _initial_seen(self) -> Dict[str, int]:
        """逐标的已见 bar 数初值（模拟盘只跑最近 N 根时用历史根数预热指标）。"""
        return {}

    def _bar_count_for_gate(self) -> int:
        """长度门槛使用的 bar 数（模拟盘只交易最近 N 根时仍按全量历史判定）。"""
        return len(self.dates)

    def _after_bar(self, date, prices: Dict[str, float]) -> None:
        """日终钩子（模拟盘用它撤当日未成交单、记当日账单）。"""

    def _dispatch(self, date, bars: Dict[str, dict]) -> None:
        """引擎→策略的唯一入口（子类可加环境差异，但不得绕过 signal_gate）。"""
        self.strategy.dispatch_bar(date, bars)

    def _enrich_snapshot(self, snapshot: dict, prices: Dict[str, float]) -> None:
        equity = max(float(snapshot.get("equity") or 0), 1e-9)
        notional = 0.0
        for book, sign in ((self.account.positions, 1.0), (self.account.short_positions, 1.0)):
            for symbol, pos in book.items():
                px = float(prices.get(symbol, pos.last_price or pos.avg_cost) or 0)
                notional += abs(pos.volume * px * pos.multiplier) * sign
        snapshot["notional"] = round(notional, 2)
        snapshot["margin_utilization"] = round(self.account.margin_used / equity, 6)
        snapshot["leverage"] = round(notional / equity, 6)

    def _liquidate_all(self) -> None:
        """回测结束强制平仓（不保留隔夜/过夜持仓）。"""
        if not self.dates:
            return
        day = pd.Timestamp(self.dates[-1]).date()
        last: Dict[str, float] = {}
        for symbol, frame in self.frames.items():
            if len(frame):
                px = frame["close"].iloc[-1]
                if pd.notna(px):
                    last[symbol] = float(px)
        books = [(self.account.positions, "long"), (self.account.short_positions, "short")]
        for book, side in books:
            for symbol, pos in list(book.items()):
                px = last.get(symbol, pos.last_price or pos.avg_cost)
                if not px or px <= 0:
                    continue
                direction = "sell" if side == "long" else "cover"
                # 强平直连 _execute：收盘价成交，不受涨跌停/成交量上限阻挡（结果不留持仓）
                res = self.account._execute(
                    symbol=symbol, market=pos.market,
                    rule=self.account._rule_of(pos.market, symbol), kind=pos.kind,
                    action="close", side=side, direction=direction, volume=pos.volume,
                    price=float(px), day=day, order_time=None, is_etf=None,
                    underlying_price=None, hold_days=None, option_type=None,
                    strike=None, expiry=None)
                if res.get("status") != "filled":
                    self.logger.warning("回测结束强平失败 %s：%s", symbol, res.get("reason"))
        if self.account.daily_equity:
            self.account.daily_equity[-1]["equity"] = round(
                self.account.calc_equity(last), 2)

    # ==================== 结果 ====================

    def _build_result(self, strategy: BaseStrategy) -> BacktestResult:
        nav = pd.DataFrame(self.account.daily_equity)
        if len(nav):
            nav["date"] = pd.to_datetime(nav["date"])
        trades = pd.DataFrame(self.account.trades)
        benchmark = self._benchmark_nav(nav)
        metrics = calc_metrics(nav, trades, benchmark=benchmark,
                               initial_capital=self.initial_capital,
                               margin_call_count=self.margin_calls)
        name = self.meta.get("name") or type(strategy).__name__
        result = BacktestResult(name, nav, trades, metrics, [],
                                benchmark=benchmark,
                                meta={"symbols": self.symbols,
                                      "start": self.start_date, "end": self.end_date,
                                      "params": dict(strategy.params),
                                      "min_bars": self.min_bars,
                                      "period": self.period,
                                      "slippage": self.execution.slippage})
        result.traps = self.detect_traps(result)
        # D-1：拒单与熔断状态随正式引擎结果落盘（CLI 留痕/验收对账同源）
        # 拒单双来源合并（v3.54 终验）：策略闸拒单（warmup/熔断/风控）+ 撮合层
        # 拒单（资金不足/涨跌停/量限）——只收一层会漏披策略层拦截（对账发现：
        # 决策日志 544 = 成交 543 + 熔断拒单 1）。⚠ strategy.rejected_orders
        # 混收 pending 排队回执（stage=account，非拒单），必须按 status 过滤；
        # 策略层记录缺 code 字段，统一走 classify_rejection 兜底补齐
        from core import signal_gate as _gate
        merged = []
        for r in (list(getattr(self.strategy, "rejected_orders", []) or [])
                  + list(getattr(self.account, "rejected_orders", []) or [])):
            if str(r.get("status")) != "rejected":
                continue
            if not r.get("code"):
                r = dict(r)
                r["code"] = _gate.classify_rejection(r.get("reason"))
            merged.append(r)
        result.rejected = merged
        result.halt_state = (strategy.risk_manager.halt_state()
                             if getattr(strategy, "risk_manager", None) else {})
        result.run_mode = self.run_mode
        result.symbols = list(self.symbols)
        result.params = dict(strategy.params)
        return result

    def _benchmark_nav(self, nav: pd.DataFrame) -> pd.DataFrame:
        if self.benchmark_frame is None or not len(nav) or "date" not in nav.columns:
            return pd.DataFrame()
        frame = self.benchmark_frame.loc[
            (self.benchmark_frame.index >= nav["date"].iloc[0])
            & (self.benchmark_frame.index <= nav["date"].iloc[-1])]
        if not len(frame):
            return pd.DataFrame()
        # 基准帧两种形态：指数取数帧（close 列，归一化）｜期货 buy&hold 帧
        # （已带 benchmark_equity，直接切片——商品期货无对应外部基准，禁止
        # 再造一层「close」伪装）
        if "benchmark_equity" in frame.columns:
            return pd.DataFrame({
                "date": frame.index,
                "benchmark_equity": pd.to_numeric(frame["benchmark_equity"],
                                                  errors="coerce").values,
            })
        base = float(frame["close"].iloc[0]) or 1.0
        out = pd.DataFrame({
            "date": frame.index,
            "benchmark_equity": frame["close"].values / base * self.initial_capital,
        })
        return out

    # ==================== 陷阱检测 ====================

    def detect_traps(self, result: BacktestResult) -> List[dict]:
        traps: List[dict] = []

        # 1) 未来函数（数据准备已硬校验，这里再确认一次）
        again = []
        for symbol, frame in self.frames.items():
            again.extend(detect_lookahead(frame, symbol))
        if again:
            traps.append({"code": "lookahead", "level": "ERROR", "message": "；".join(again)})

        # 2) 幸存者偏差
        traps.append({
            "code": "survivorship", "level": "WARN",
            "message": "仅用当前 symbols 列表回测，已退市/停牌标的未纳入，结果存在幸存者偏差",
        })

        # 3) 过拟合
        params = result.meta.get("params") or {}
        n_trades = int(result.metrics.get("trade_count") or 0)
        if len(params) >= 6 and n_trades < 30:
            traps.append({
                "code": "overfit", "level": "WARN",
                "message": f"参数 {len(params)} 个但仅 {n_trades} 笔交易，过拟合风险高；"
                           f"建议做参数平原/走向前验证",
            })

        # 4) 流动性
        thin = []
        for symbol, frame in self.frames.items():
            if "amount" not in frame.columns:
                continue
            avg = float(frame["amount"].tail(250).mean() or 0)
            if 0 < avg < LIQUIDITY_MIN_AMOUNT:
                thin.append(f"{symbol}({avg / 1e4:.0f}万)")
        if thin:
            traps.append({"code": "liquidity", "level": "WARN",
                          "message": "日均成交额 <500 万：" + "、".join(thin)})

        # 5) 滑点
        if self.execution.slippage < SLIPPAGE_WARN:
            traps.append({
                "code": "slippage", "level": "WARN",
                "message": f"滑点 {self.execution.slippage:.4%} 偏低，实盘可能更大",
            })

        # 附：成交模型统计（便于判断是否过度乐观）
        if self.execution.capped_orders:
            traps.append({
                "code": "volume_cap", "level": "INFO",
                "message": f"{self.execution.capped_orders} 笔委托按当日成交量 1% 截断",
            })
        if self.execution.limit_rejects:
            traps.append({
                "code": "price_limit", "level": "INFO",
                "message": f"{self.execution.limit_rejects} 笔委托因涨跌停未能成交",
            })
        return traps


# ==================== 绩效指标 ====================

def calc_metrics(nav: pd.DataFrame, trades: pd.DataFrame, benchmark: pd.DataFrame = None,
                 initial_capital: float = None, annual_days: int = 252,
                 margin_call_count: int = 0) -> dict:
    """收益/风险/风险调整/交易/杠杆五类指标 + 分市场、分多空统计。"""
    metrics: dict = {}
    if nav is None or not len(nav):
        return metrics
    nav = nav.copy()
    if "date" in nav.columns:
        nav["date"] = pd.to_datetime(nav["date"])
    equity = pd.to_numeric(nav["equity"], errors="coerce").ffill().dropna()
    if not len(equity):
        return metrics
    start_equity = float(initial_capital or equity.iloc[0])
    total_return = float(equity.iloc[-1] / start_equity - 1.0)
    days = max(len(equity), 1)
    years = days / float(annual_days)
    annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0.0
    rets = equity.pct_change().dropna()

    metrics.update({
        "total_return": total_return,
        "annual_return": float(annual_return),
        "days": days,
        "final_equity": float(equity.iloc[-1]),
    })

    # ---- 基准 / 超额 / 信息比率 ----
    if benchmark is not None and len(benchmark):
        bench = pd.to_numeric(benchmark["benchmark_equity"], errors="coerce").dropna()
        if len(bench) >= 2:
            bench_return = float(bench.iloc[-1] / benchmark["benchmark_equity"].iloc[0] - 1.0)
            metrics["benchmark_return"] = bench_return
            metrics["excess_return"] = total_return - bench_return
            aligned = pd.concat([equity.reset_index(drop=True),
                                 bench.reset_index(drop=True)], axis=1).dropna()
            if len(aligned) > 2:
                diff = aligned.iloc[:, 0].pct_change().dropna() - \
                    aligned.iloc[:, 1].pct_change().dropna()
                std = float(diff.std(ddof=1))
                metrics["information_ratio"] = (float(diff.mean()) / std * math.sqrt(annual_days)
                                                if std > 0 else None)
    else:
        metrics["benchmark_return"] = None
        metrics["excess_return"] = None

    # ---- 回撤 ----
    peak = equity.cummax()
    dd = equity / peak - 1.0
    max_dd = float(dd.min())
    metrics["max_drawdown"] = max_dd
    if max_dd < 0:
        end_idx = int(dd.idxmin())
        start_idx = int(equity.loc[:end_idx].idxmax()) if end_idx > 0 else 0
        dates = nav["date"] if "date" in nav.columns else pd.Series(range(len(equity)))
        metrics["max_drawdown_start"] = str(dates.iloc[start_idx].date()
                                            if hasattr(dates.iloc[start_idx], "date")
                                            else dates.iloc[start_idx])
        metrics["max_drawdown_end"] = str(dates.iloc[end_idx].date()
                                          if hasattr(dates.iloc[end_idx], "date")
                                          else dates.iloc[end_idx])
        metrics["max_drawdown_days"] = max(end_idx - start_idx, 0)
    else:
        metrics["max_drawdown_start"] = metrics["max_drawdown_end"] = None
        metrics["max_drawdown_days"] = 0

    # ---- 风险 / 风险调整 ----
    std = float(rets.std(ddof=1)) if len(rets) > 1 else 0.0
    metrics["annual_volatility"] = std * math.sqrt(annual_days)
    downside = rets[rets < 0]
    down_std = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    metrics["downside_risk"] = down_std * math.sqrt(annual_days)
    metrics["sharpe"] = (float(rets.mean()) / std * math.sqrt(annual_days)
                         if std > 0 else None)
    metrics["sortino"] = (float(rets.mean()) / down_std * math.sqrt(annual_days)
                          if down_std > 0 else None)
    metrics["calmar"] = (annual_return / abs(max_dd) if max_dd < 0 else None)

    # ---- 交易统计 ----
    metrics.update(_trade_stats(trades, initial_capital=start_equity))
    metrics["margin_call_count"] = int(margin_call_count or 0)

    # ---- 杠杆 ----
    if "leverage" in nav.columns:
        lev = pd.to_numeric(nav["leverage"], errors="coerce").dropna()
        metrics["avg_leverage"] = float(lev.mean()) if len(lev) else None
        metrics["max_leverage"] = float(lev.max()) if len(lev) else None
    else:
        metrics["avg_leverage"] = metrics["max_leverage"] = None
    if "margin_utilization" in nav.columns:
        mu = pd.to_numeric(nav["margin_utilization"], errors="coerce").dropna()
        metrics["avg_margin_utilization"] = float(mu.mean()) if len(mu) else 0.0
        metrics["max_margin_utilization"] = float(mu.max()) if len(mu) else 0.0
    else:
        metrics["avg_margin_utilization"] = metrics["max_margin_utilization"] = 0.0

    return metrics


def _trade_stats(trades: pd.DataFrame, initial_capital: float = None) -> dict:
    empty = {
        "trade_count": 0, "closed_trade_count": 0, "win_rate": 0.0,
        "profit_factor": None, "avg_trade_pnl": 0.0, "avg_trade_return": 0.0,
        "avg_holding_days": 0.0, "max_consecutive_losses": 0,
        "max_win": 0.0, "max_loss": 0.0, "total_commission": 0.0,
        "by_market": {}, "by_direction": {},
    }
    if trades is None or not len(trades):
        return empty
    df = trades.copy()
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    for col in ("pnl", "commission"):
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    if "action" not in df.columns:
        df["action"] = ""

    closed = df[df.get("action").astype(str).str.lower() == "close"].copy()
    wins = closed[closed["pnl"] > 0]
    losses = closed[closed["pnl"] < 0]
    gross_win = float(wins["pnl"].sum())
    gross_loss = float(losses["pnl"].sum())

    stats = {
        "trade_count": int(len(df[df.get("action").astype(str).str.lower() == "open"])),
        "closed_trade_count": int(len(closed)),
        "win_rate": float(len(wins) / len(closed)) if len(closed) else 0.0,
        "profit_factor": (gross_win / abs(gross_loss)) if gross_loss < 0 else None,
        "avg_trade_pnl": float(closed["pnl"].mean()) if len(closed) else 0.0,
        "avg_trade_return": (float(closed["pnl"].mean()) / initial_capital
                             if len(closed) and initial_capital else 0.0),
        "avg_holding_days": _avg_holding_days(df),
        "max_consecutive_losses": _max_consecutive_losses(closed["pnl"].tolist()),
        "max_win": float(closed["pnl"].max()) if len(closed) else 0.0,
        "max_loss": float(closed["pnl"].min()) if len(closed) else 0.0,
        "total_commission": float(df["commission"].sum()),
        "by_market": _group_stats(closed, "market"),
        "by_direction": _group_stats(closed, "direction"),
    }
    return stats


def _avg_holding_days(df: pd.DataFrame) -> float:
    if "timestamp" not in df.columns:
        return 0.0
    held: List[float] = []
    opened: Dict[str, list] = defaultdict(list)
    for _, row in df.sort_values("timestamp").iterrows():
        symbol = str(row.get("symbol"))
        action = str(row.get("action")).lower()
        ts = row.get("timestamp")
        if pd.isna(ts):
            continue
        if action == "open":
            opened[symbol].append(ts)
        elif action == "close" and opened[symbol]:
            start = opened[symbol].pop(0)
            held.append(max((ts - start).total_seconds() / 86400.0, 0.0))
    return float(np.mean(held)) if held else 0.0


def _max_consecutive_losses(pnls: List[float]) -> int:
    best = cur = 0
    for pnl in pnls:
        if pnl < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _group_stats(closed: pd.DataFrame, key: str) -> dict:
    if closed is None or not len(closed) or key not in closed.columns:
        return {}
    out = {}
    for name, group in closed.groupby(key):
        wins = group[group["pnl"] > 0]
        out[str(name)] = {
            "count": int(len(group)),
            "win_rate": float(len(wins) / len(group)) if len(group) else 0.0,
            "pnl": float(group["pnl"].sum()),
            "commission": float(group["commission"].sum()),
        }
    return out


# ==================== 可视化 ====================

def plot_results(nav: pd.DataFrame, trades: pd.DataFrame, metrics: dict,
                 benchmark: pd.DataFrame = None, strategy_name: str = "strategy",
                 save_path=None):
    """生成回测图；matplotlib 缺失时返回 None 并告警，不中断回测。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("backtester").warning("matplotlib 不可用（%s），跳过绘图", exc)
        return None
    if nav is None or not len(nav):
        return None
    from core.chart import setup_chinese_font
    setup_chinese_font()

    df = nav.copy()
    df["date"] = pd.to_datetime(df["date"])
    equity = pd.to_numeric(df["equity"], errors="coerce")
    dd = equity / equity.cummax() - 1.0
    leveraged = bool(df.get("margin_utilization", pd.Series(dtype=float)).fillna(0).max() > 0)

    n_rows = 4
    fig, axes = plt.subplots(n_rows, 1, figsize=(12, 3.2 * n_rows), sharex=False)
    # 1) 净值 vs 基准
    axes[0].plot(df["date"], equity, label="策略净值", color="#1f77b4")
    if benchmark is not None and len(benchmark):
        bench = benchmark.copy()
        bench["date"] = pd.to_datetime(bench["date"])
        axes[0].plot(bench["date"], bench["benchmark_equity"], label="基准", color="#999999",
                     linestyle="--")
    axes[0].set_title(f"{strategy_name} 净值曲线")
    axes[0].legend()
    # 2) 回撤
    axes[1].fill_between(df["date"], dd.values, 0, color="#d62728", alpha=0.35)
    axes[1].set_title(f"回撤（最大 {metrics.get('max_drawdown', 0):.2%}）")
    # 3) 月度收益热力图
    monthly = equity.pct_change().groupby(df["date"].dt.to_period("M")).apply(
        lambda s: (1 + s).prod() - 1)
    if len(monthly):
        axes[2].bar(monthly.index.astype(str), monthly.values,
                    color=["#2ca02c" if v >= 0 else "#d62728" for v in monthly.values])
        axes[2].set_title("月度收益")
        axes[2].tick_params(axis="x", rotation=90, labelsize=7)
    # 4) 每笔交易盈亏
    if trades is not None and len(trades):
        closed = trades[trades.get("action").astype(str).str.lower() == "close"]
        if len(closed):
            axes[3].bar(range(len(closed)), pd.to_numeric(closed["pnl"], errors="coerce").fillna(0),
                        color=["#2ca02c" if v >= 0 else "#d62728"
                               for v in pd.to_numeric(closed["pnl"], errors="coerce").fillna(0)])
        axes[3].set_title("每笔平仓盈亏")
    else:
        axes[3].set_title("每笔平仓盈亏（无交易）")

    fig.tight_layout()
    path = Path(save_path) if save_path else (
        Path(config.BACKTEST_DIR) / "charts" / f"{strategy_name}.png")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=140)
    plt.close(fig)

    if leveraged:
        _plot_leverage(df, strategy_name, path)
    return path


def _plot_leverage(df: pd.DataFrame, strategy_name: str, path: Path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # noqa: BLE001
        return
    fig, ax1 = plt.subplots(figsize=(12, 3.2))
    ax1.plot(df["date"], df["margin_utilization"], color="#ff7f0e", label="保证金使用率")
    ax1.set_ylabel("保证金使用率")
    ax2 = ax1.twinx()
    ax2.plot(df["date"], df["leverage"], color="#1f77b4", linestyle="--", label="杠杆率")
    ax2.set_ylabel("杠杆率")
    ax1.set_title(f"{strategy_name} 保证金/杠杆")
    fig.tight_layout()
    fig.savefig(path.with_name(path.stem + "_leverage.png"), dpi=140)
    plt.close(fig)


# ==================== 工具 ====================

def _pct(value) -> str:
    return f"{value:.2%}" if isinstance(value, (int, float)) and np.isfinite(value) else "—"


def _num(value) -> str:
    return f"{value:.3f}" if isinstance(value, (int, float)) and np.isfinite(value) else "—"


def run(strategy_class, **kwargs) -> BacktestResult:
    """便捷入口：`run(MyStrategy, symbols=[...], start_date=..., end_date=...)`。"""
    return Backtester(strategy_class, **kwargs).run()
