"""第 5 步 · 第 6 步：样本内外分割 + 走向前分析（research/walkforward.py）

防过拟合最关键的一步：
  - **样本内外**：前 `train_ratio`（默认 70%）找参数，后 30% **只验证、绝不调参**；
  - **走向前分析（Walk-Forward）**：把 [start, end] 按交易日切成 `n_splits` 段，
    每段「前段优化 → 后段执行」，首尾拼接成一条完整的样本外净值曲线，
    这是最接近实盘的表现。

实现口径（均为简化，注释写清楚）：
  - 交易日历取各标的实际交易日的**并集**（`calendar_mode="intersection"` 可切交集）；
  - 每段参数复用 `research.optimizer`，优先取「参数平原中心」`recommended`，
    无平原地信息时退回按 `metric` 排序的最优单点；
  - 净值拼接用 `pct_change` 连乘：不同段的初始资金不同，直接拼 level 会出现跳变，
    这里每段内部先转成收益率、再整体累乘，段与段之间收益连续、无资金跳变。
"""
from __future__ import annotations

from typing import Callable, Dict, List

import numpy as np
import pandas as pd

import config
from core.runner import calc_metrics, run_backtest
from core.utils import setup_logger
from research.optimizer import create_optimizer

__all__ = ["split_in_out", "trading_calendar", "evaluate_split", "run_walkforward"]

logger = setup_logger("walkforward", config.LOG_DIR / "walkforward.log")


# ==================== 日期切分工具 ====================

def split_in_out(nav_or_metrics, ratio: float = 0.7):
    """按位置把「净值/序列/列表」切成样本内（前 ratio）与样本外（后 1-ratio）。

    - pd.Series / pd.DataFrame：返回两段切片（索引为日期时即按日期边界切）；
    - list / tuple：返回两个 list；
    - int（序列长度）：返回切分位置下标。
    """
    ratio = float(ratio)
    if not 0.0 < ratio < 1.0:
        raise ValueError(f"ratio 必须在 (0, 1) 内，收到 {ratio}")
    n = int(len(nav_or_metrics))
    if n < 2:
        cut = 0
    else:
        cut = int(round(n * ratio))
        cut = min(max(cut, 1), n - 1)
    if isinstance(nav_or_metrics, (pd.Series, pd.DataFrame)):
        return nav_or_metrics.iloc[:cut], nav_or_metrics.iloc[cut:]
    if isinstance(nav_or_metrics, (list, tuple)):
        return list(nav_or_metrics[:cut]), list(nav_or_metrics[cut:])
    return cut


def _to_ts(value):
    """宽松解析日期："2024-01-02" / "20240102" / Timestamp / None。"""
    if value is None or value == "":
        return None
    try:
        return pd.Timestamp(value)
    except (ValueError, TypeError):
        return pd.Timestamp(str(value).replace("-", "").replace("/", ""))


def _fmt(date) -> str:
    return pd.Timestamp(date).strftime("%Y-%m-%d")


def trading_calendar(symbols: List[str], start: str, end: str,
                     fetcher=None, adjust: str = "qfq",
                     mode: str = "union") -> pd.DatetimeIndex:
    """各标的实际交易日的并集（默认）或交集，用于切分样本段。"""
    if fetcher is None:
        from core.data_fetcher import DataFetcher
        fetcher = DataFetcher()
    slices = []
    for symbol in symbols:
        try:
            frame = fetcher.get_daily(symbol, start_date=start, end_date=end, adjust=adjust)
        except TypeError:  # 兼容只接受 symbol 的简化 fetcher
            frame = fetcher.get_daily(symbol)
        if frame is None or len(frame) == 0:
            continue
        idx = pd.DatetimeIndex(pd.to_datetime(frame.index))
        lo, hi = _to_ts(start), _to_ts(end)
        if lo is not None:
            idx = idx[idx >= lo]
        if hi is not None:
            idx = idx[idx <= hi]
        if len(idx):
            slices.append(set(idx))
    if not slices:
        raise RuntimeError("所有标的在指定区间内均无数据，无法切分交易日")
    dates = set.intersection(*slices) if str(mode) == "intersection" else set.union(*slices)
    return pd.DatetimeIndex(sorted(dates))


# ==================== 单段执行 ====================

def _invoke(run_fn, strategy_cls, params, symbols, start, end,
            fetcher, initial_cash, adjust) -> dict:
    """统一调用执行器；run_fn 可注入（默认 core.runner.run_backtest）。"""
    fn = run_fn or run_backtest
    try:
        return fn(strategy_cls, params=params, symbols=symbols, start=start, end=end,
                  fetcher=fetcher, initial_cash=initial_cash, adjust=adjust) or {}
    except TypeError:
        # 离线测试桩可能用位置参数签名
        return fn(strategy_cls, params, symbols, start, end,
                  fetcher, initial_cash) or {}


def evaluate_split(strategy_cls, best_params: dict, symbols: List[str],
                   start: str, end: str, fetcher=None, initial_cash: float = None,
                   adjust: str = "qfq", run_fn: Callable = None) -> dict:
    """用固定参数在 [start, end] 上回测一段，供走向前分析/测试单独调用。"""
    result = _invoke(run_fn, strategy_cls, dict(best_params or {}), symbols,
                     start, end, fetcher, initial_cash, adjust)
    nav = result.get("nav")
    if nav is None:
        nav = pd.Series(dtype=float)
    metrics = dict(result.get("metrics") or {})
    if not metrics and len(nav):
        metrics = calc_metrics(nav)
    return {"nav": nav, "metrics": metrics, "trades": list(result.get("trades") or []),
            "result": result}


# ==================== 走向前分析 ====================

def _pick_params(out: dict, metric: str) -> dict:
    """优先「参数平原中心」，没有平原地信息时按 metric 取最优单点。"""
    recommended = out.get("recommended") or {}
    params = recommended.get("params") if isinstance(recommended, dict) else None
    if params:
        return dict(params)
    results = [r for r in (out.get("results") or []) if r.get("params")]
    if not results:
        return {}
    metric = str(metric or "sharpe")

    def _key(row):
        value = (row.get("metrics") or {}).get(metric)
        if value is None or not np.isfinite(float(value or 0)):
            value = row.get("score", -np.inf)
        return float(value)

    return dict(max(results, key=_key)["params"])


def _chain_nav(navs: List[pd.Series]) -> pd.Series:
    """把多段净值用 pct_change 连乘成一条曲线（首点=1，段间无资金跳变）。"""
    rets = []
    for nav in navs:
        if nav is None or len(nav) == 0:
            continue
        nav = nav.dropna().astype(float)
        if len(nav) == 0:
            continue
        rets.append(nav.pct_change().fillna(0.0))
    if not rets:
        return pd.Series(dtype=float)
    all_rets = pd.concat(rets)
    all_rets = all_rets[~all_rets.index.duplicated(keep="last")].sort_index()
    return (1.0 + all_rets).cumprod()


def run_walkforward(strategy_cls, param_grid: Dict[str, list], symbols: List[str],
                    start: str, end: str, n_splits: int = 4,
                    train_ratio: float = 0.7, optimizer: str = "grid",
                    metric: str = "sharpe", fetcher=None,
                    initial_cash: float = None, adjust: str = "qfq",
                    run_fn: Callable = None, seed: int = 42, top_n: int = 10,
                    calendar_mode: str = "union") -> dict:
    """滚动窗口走向前分析：逐段调参 → 紧接的后段执行 → 拼接样本外净值。

    返回：
        segments: [{train_start, train_end, test_start, test_end, best_params,
                    is_metrics, oos_metrics}]
        oos_nav: 拼接后的样本外净值（首点 = 1）
        is_metrics / oos_metrics: 拼接样本内 / 样本外绩效
        degradation: 1 - oos_sharpe / is_sharpe（is_sharpe <= 0 时为 None）
        params_history: 每段选出的参数（含段号与训练区间，便于追踪参数漂移）
    """
    symbols = [str(s) for s in (symbols or [])]
    if not symbols:
        raise ValueError("必须提供 symbols")
    n_splits = int(n_splits)
    if n_splits < 1:
        raise ValueError("n_splits 必须 >= 1")

    dates = trading_calendar(symbols, start, end, fetcher=fetcher,
                             adjust=adjust, mode=calendar_mode)
    if len(dates) < n_splits * 2 + 2:
        raise ValueError(f"交易日不足（{len(dates)} 天），无法切 {n_splits} 段")

    edges = [int(round(i * len(dates) / n_splits)) for i in range(n_splits + 1)]
    edges[0], edges[-1] = 0, len(dates)

    segments: List[dict] = []
    params_history: List[dict] = []
    oos_navs: List[pd.Series] = []
    is_navs: List[pd.Series] = []

    for i in range(n_splits):
        chunk = dates[edges[i]:edges[i + 1]]
        if len(chunk) < 3:
            continue
        cut = int(round(len(chunk) * float(train_ratio)))
        cut = min(max(cut, 1), len(chunk) - 1)
        train_dates, test_dates = chunk[:cut], chunk[cut:]
        train_start, train_end = _fmt(train_dates[0]), _fmt(train_dates[-1])
        test_start, test_end = _fmt(test_dates[0]), _fmt(test_dates[-1])

        opt = create_optimizer(optimizer, param_grid, n_iter=30, seed=seed)

        def objective(params, _ts=train_start, _te=train_end):
            res = _invoke(run_fn, strategy_cls, dict(params), symbols,
                          _ts, _te, fetcher, initial_cash, adjust)
            return dict(res.get("metrics") or {})

        out = opt.run(objective, top_n=top_n)
        best_params = _pick_params(out, metric)
        if not best_params:  # 优化器完全无候选时退回参数网格首组
            first = {k: list(v)[0] for k, v in (param_grid or {}).items() if v}
            best_params = first

        is_part = evaluate_split(strategy_cls, best_params, symbols, train_start,
                                 train_end, fetcher=fetcher,
                                 initial_cash=initial_cash, adjust=adjust, run_fn=run_fn)
        oos_part = evaluate_split(strategy_cls, best_params, symbols, test_start,
                                  test_end, fetcher=fetcher,
                                  initial_cash=initial_cash, adjust=adjust, run_fn=run_fn)

        is_navs.append(is_part["nav"])
        oos_navs.append(oos_part["nav"])
        segments.append({
            "train_start": train_start, "train_end": train_end,
            "test_start": test_start, "test_end": test_end,
            "best_params": best_params,
            "is_metrics": is_part["metrics"],
            "oos_metrics": oos_part["metrics"],
        })
        params_history.append({"segment": i, "train_start": train_start,
                               "train_end": train_end, "params": dict(best_params)})
        logger.info("走向前第 %d 段 %s→%s 调参，%s→%s 验证，参数 %s", i + 1,
                    train_start, train_end, test_start, test_end, best_params)

    oos_nav = _chain_nav(oos_navs)
    is_nav = _chain_nav(is_navs)
    is_metrics = calc_metrics(is_nav)
    oos_metrics = calc_metrics(oos_nav)
    is_sharpe = float(is_metrics.get("sharpe", 0.0) or 0.0)
    oos_sharpe = float(oos_metrics.get("sharpe", 0.0) or 0.0)
    degradation = None if is_sharpe <= 0 else float(1.0 - oos_sharpe / is_sharpe)

    return {"segments": segments, "oos_nav": oos_nav,
            "is_metrics": is_metrics, "oos_metrics": oos_metrics,
            "degradation": degradation, "params_history": params_history}
