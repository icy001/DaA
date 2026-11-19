"""因子合成器（第 5 步 5.9.8）。

单因子 IC 通常只有 0.02~0.05，必须多因子合成。本模块提供：
  * equal_weight   等权（先截面标准化）；
  * ic_weighted    滚动 IC 加权（权重滞后一期，避免未来函数）；
  * max_icir       用 IC 协方差矩阵求 ICIR 最优权重；
  * ridge_combine  纯 numpy Ridge（不依赖 sklearn）；
  * dedupe         剔除 |corr|>threshold 的冗余因子（保留 ICIR/覆盖度更高者）；
  * combine        统一入口。

输出统一是「日期×股票」综合打分，可直接喂给 evaluator / FactorStrategy。
"""
from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from .preprocess import zscore

logger = logging.getLogger(__name__)

__all__ = ["equal_weight", "ic_weighted", "max_icir", "ridge_combine",
           "dedupe", "combine"]


def _align(factor_dict: Dict[str, pd.DataFrame]) -> Tuple[List[str], pd.Index, pd.Index]:
    names = [k for k, v in factor_dict.items() if isinstance(v, pd.DataFrame) and not v.empty]
    if not names:
        raise ValueError("factor_dict 为空或没有有效面板")
    idx = factor_dict[names[0]].index
    cols = factor_dict[names[0]].columns
    for n in names[1:]:
        idx = idx.intersection(factor_dict[n].index)
        cols = cols.union(factor_dict[n].columns)
    return names, idx.sort_values(), cols


def _z(factor_dict: Dict[str, pd.DataFrame], names: List[str],
       idx: pd.Index, cols: pd.Index) -> Dict[str, pd.DataFrame]:
    return {n: zscore(factor_dict[n].reindex(index=idx, columns=cols)) for n in names}


def equal_weight(
    factor_dict: Dict[str, pd.DataFrame],
    weights: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """等权合成：每个因子先截面标准化，再按权重（默认 1/n）相加。"""
    names, idx, cols = _align(factor_dict)
    z = _z(factor_dict, names, idx, cols)
    if weights is None:
        w = {n: 1.0 / len(names) for n in names}
    else:
        w = {n: float(weights.get(n, 0.0)) for n in names}
        total = sum(abs(v) for v in w.values())
        if total <= 0:
            raise ValueError("weights 绝对值之和必须 >0")
        w = {n: v / total for n, v in w.items()}
    out = sum(z[n] * w[n] for n in names)
    return out.reindex(index=idx, columns=cols)


def _ic_series(factor: pd.DataFrame, returns: pd.DataFrame) -> pd.Series:
    idx = factor.index.intersection(returns.index)
    cols = factor.columns.intersection(returns.columns)
    f = factor.loc[idx, cols]
    r = returns.loc[idx, cols].shift(-1)
    vals = {}
    for dt in idx:
        a, b = f.loc[dt], r.loc[dt]
        valid = a.notna() & b.notna()
        if valid.sum() >= 3:
            ic = a[valid].corr(b[valid], method="spearman")
            if np.isfinite(ic):
                vals[dt] = ic
    return pd.Series(vals, dtype=float).sort_index()


def ic_weighted(
    factor_dict: Dict[str, pd.DataFrame],
    ic_series,
    window: int = 60,
) -> pd.DataFrame:
    """滚动 IC 加权：权重 = 过去 window 期平均 IC（滞后一期，防未来函数）。"""
    names, idx, cols = _align(factor_dict)
    if ic_series is None:
        logger.warning("ic_weighted 缺少 IC 序列，降级为等权")
        return equal_weight(factor_dict)
    if isinstance(ic_series, pd.DataFrame):
        ics = {n: ic_series[n] for n in names if n in ic_series.columns}
    else:
        ics = {n: ic_series[n] for n in names if n in ic_series}
    if not ics:
        logger.warning("ic_weighted 中没有与因子匹配的 IC 序列，降级为等权")
        return equal_weight(factor_dict)

    # 每个因子的滚动平均 IC，并 shift(1) 保证 t 日只用 t-1 及之前的 IC
    wr = pd.DataFrame(index=idx)
    for n in names:
        s = ics.get(n)
        if s is None:
            wr[n] = 0.0
        else:
            wr[n] = s.reindex(idx).rolling(window, min_periods=1).mean().shift(1).fillna(0.0)
    denom = wr.abs().sum(axis=1).replace(0.0, np.nan)
    weights = wr.div(denom, axis=0).fillna(0.0)

    z = _z(factor_dict, names, idx, cols)
    # 注意：weights[n] 是「按日期」的 Series，必须按行（axis=0）对齐，
    # 否则 pandas 会按列名（股票代码）对齐导致整表 NaN。
    out = sum(z[n].mul(weights[n], axis=0) for n in names)
    return out.reindex(index=idx, columns=cols)


def max_icir(
    factor_dict: Dict[str, pd.DataFrame],
    returns: pd.DataFrame,
) -> pd.DataFrame:
    """用 IC 均值与 IC 协方差矩阵求 ICIR 最优权重：w ∝ Σ^-1 μ。"""
    names, idx, cols = _align(factor_dict)
    ic_map = {n: _ic_series(factor_dict[n], returns) for n in names}
    ic_df = pd.DataFrame(ic_map).dropna(how="all").fillna(0.0)
    if ic_df.empty:
        logger.warning("max_icir 无法计算 IC，降级为等权")
        return equal_weight(factor_dict)
    mu = ic_df.mean().to_numpy(dtype=float)
    cov = ic_df.cov().to_numpy(dtype=float)
    cov = np.nan_to_num(cov, nan=0.0)
    # L2 正则保证可逆
    cov = cov + np.eye(len(names)) * 1e-6
    try:
        raw = np.linalg.solve(cov, mu)
    except np.linalg.LinAlgError:
        raw = np.linalg.pinv(cov) @ mu
    if not np.isfinite(raw).all() or np.abs(raw).sum() <= 0:
        w = np.ones(len(names)) / len(names)
    else:
        w = raw / np.abs(raw).sum()
    return equal_weight(factor_dict, {n: float(v) for n, v in zip(names, w)}).reindex(index=idx, columns=cols)


def ridge_combine(
    factor_dict: Dict[str, pd.DataFrame],
    returns: pd.DataFrame,
    alpha: float = 1.0,
) -> pd.DataFrame:
    """Ridge 回归合成：y=次日收益，X=截面标准化因子，闭式解 (X'X+αI)^-1X'y。"""
    names, idx, cols = _align(factor_dict)
    z = _z(factor_dict, names, idx, cols)
    fwd = returns.reindex(index=idx, columns=cols).shift(-1)

    X_rows, y_rows = [], []
    preds = {}
    for dt in idx:
        row_X = np.column_stack([z[n].loc[dt].to_numpy(dtype=float) for n in names])
        row_y = fwd.loc[dt].to_numpy(dtype=float)
        valid = np.isfinite(row_X).all(axis=1) & np.isfinite(row_y)
        if valid.sum() >= len(names) + 2:
            X_rows.append(row_X[valid])
            y_rows.append(row_y[valid])
    if not X_rows:
        logger.warning("ridge_combine 有效样本不足，降级为等权")
        return equal_weight(factor_dict)

    X = np.vstack(X_rows)
    y = np.concatenate(y_rows)
    gram = X.T @ X + float(alpha) * np.eye(len(names))
    try:
        beta = np.linalg.solve(gram, X.T @ y)
    except np.linalg.LinAlgError:
        beta = np.linalg.pinv(gram) @ (X.T @ y)
    for dt in idx:
        row_X = np.column_stack([z[n].loc[dt].to_numpy(dtype=float) for n in names])
        preds[dt] = np.nansum(row_X * beta, axis=1)
    out = pd.DataFrame.from_dict(preds, orient="index", columns=cols).sort_index()
    return out


def dedupe(
    df_dict: Dict[str, pd.DataFrame],
    threshold: float = 0.7,
    returns: Optional[pd.DataFrame] = None,
) -> Dict[str, pd.DataFrame]:
    """剔除高度冗余因子：按 ICIR（无收益时按覆盖度×波动）从高到低保留。"""
    names = [k for k, v in df_dict.items() if isinstance(v, pd.DataFrame) and not v.empty]
    if len(names) <= 1:
        return {k: df_dict[k] for k in names}

    quality = {}
    for n in names:
        f = df_dict[n]
        if returns is not None:
            ic = _ic_series(f, returns)
            sd = ic.std(ddof=1) if len(ic) > 1 else 0.0
            quality[n] = abs(ic.mean() / sd) if sd and np.isfinite(sd) else 0.0
        else:
            quality[n] = float(f.notna().mean().mean() * (f.std(axis=1).mean() or 0.0))
    order = sorted(names, key=lambda n: quality[n], reverse=True)

    kept: List[str] = []
    for n in order:
        redundant = False
        for k in kept:
            fa, fb = df_dict[n], df_dict[k]
            idx = fa.index.intersection(fb.index)
            cols = fa.columns.intersection(fb.columns)
            if len(idx) == 0 or len(cols) == 0:
                continue
            c = fa.loc[idx, cols].corrwith(fb.loc[idx, cols], axis=1).mean()
            if np.isfinite(c) and abs(c) > threshold:
                redundant = True
                break
        if not redundant:
            kept.append(n)
    return {n: df_dict[n] for n in names if n in kept}


def combine(
    name: str,
    factors: Dict[str, pd.DataFrame],
    returns: Optional[pd.DataFrame] = None,
    **kwargs,
) -> pd.DataFrame:
    """统一合成入口。

    name: equal_weight / ic_weighted / max_icir / ridge / ridge_combine
    其他参数：weights、ic_series、window、alpha、dedupe_first、threshold。
    """
    method = (name or "equal_weight").lower()
    method = {"ridge": "ridge_combine", "equal": "equal_weight",
              "ic": "ic_weighted", "icir": "max_icir"}.get(method, method)
    if kwargs.pop("dedupe_first", False):
        factors = dedupe(factors, threshold=kwargs.pop("threshold", 0.7), returns=returns)

    if method == "equal_weight":
        return equal_weight(factors, weights=kwargs.get("weights"))
    if method == "ic_weighted":
        ic = kwargs.get("ic_series")
        if ic is None and returns is not None:
            ic = {n: _ic_series(f, returns) for n, f in factors.items()}
        return ic_weighted(factors, ic, window=int(kwargs.get("window", 60)))
    if method == "max_icir":
        if returns is None:
            logger.warning("max_icir 需要 returns，缺失时降级为等权")
            return equal_weight(factors)
        return max_icir(factors, returns)
    if method == "ridge_combine":
        if returns is None:
            logger.warning("ridge_combine 需要 returns，缺失时降级为等权")
            return equal_weight(factors)
        return ridge_combine(factors, returns, alpha=float(kwargs.get("alpha", 1.0)))
    raise ValueError(f"未知合成方法: {name}")
