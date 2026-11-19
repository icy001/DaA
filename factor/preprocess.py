"""因子预处理（第 5 步 5.9.5）。

标准四步流程（顺序固定，避免口径不一致）：
  1. winsorize_mad  中位数绝对偏差去极值（比 3σ 稳健）；
  2. fill_na        缺失值填充（行业均值 / 截面中位数 / 前值）；
  3. neutralize     行业/市值中性化（最小二乘取残差）；
  4. zscore         截面标准化到均值 0、标准差 1。

所有函数输入输出都是「日期×股票」面板。中性化缺行业/市值数据时自动降级
并打 WARNING，绝不静默当成精确值。
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

__all__ = ["winsorize_mad", "fill_na", "zscore", "neutralize", "process_factor"]


def winsorize_mad(x: pd.DataFrame, n: float = 3.0) -> pd.DataFrame:
    """MAD 去极值：截断到 median ± n*1.4826*MAD（逐日截面）。"""
    if x.empty:
        return x.copy()
    med = x.median(axis=1)
    mad = x.sub(med, axis=0).abs().median(axis=1)
    scale = 1.4826 * mad
    # MAD=0 表示截面高度一致，不做截断（否则会把所有值压成中位数）
    lower = (med - n * scale).where(scale > 0, -np.inf)
    upper = (med + n * scale).where(scale > 0, np.inf)
    return x.clip(lower=lower, upper=upper, axis=0)


def fill_na(
    x: pd.DataFrame,
    method: str = "industry_mean",
    industry: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """缺失值填充。

    method:
      - 'industry_mean'：行业内均值（需 industry 面板；缺失时降级为截面中位数）
      - 'median'：截面中位数
      - 'ffill'：按时间前值填充
    """
    method = (method or "industry_mean").lower()
    out = x.copy()
    if method == "ffill":
        out = out.ffill()
        return out
    if method == "median":
        return out.apply(lambda row: row.fillna(row.median()), axis=1)
    if method != "industry_mean":
        raise ValueError(f"未知填充方法: {method}")
    if industry is None:
        logger.warning("fill_na(industry_mean) 缺少行业数据，降级为截面中位数填充")
        return out.apply(lambda row: row.fillna(row.median()), axis=1)

    filled = out.copy()
    for dt in out.index:
        if dt not in industry.index:
            filled.loc[dt] = out.loc[dt].fillna(out.loc[dt].median())
            continue
        row = out.loc[dt]
        grp = industry.loc[dt].reindex(out.columns)
        means = row.groupby(grp).transform("mean")
        filled.loc[dt] = row.fillna(means).fillna(row.median())
    return filled


def zscore(x: pd.DataFrame) -> pd.DataFrame:
    """截面标准化：(x-均值)/标准差；标准差为 0 时该截面置 0。"""
    mu = x.mean(axis=1)
    sd = x.std(axis=1, ddof=1)
    out = x.sub(mu, axis=0).div(sd.where(sd > 0), axis=0)
    out = out.replace([np.inf, -np.inf], np.nan)
    zero_rows = sd.fillna(0) <= 0
    if zero_rows.any():
        out.loc[zero_rows] = 0.0
    return out


def _industry_matrix(industry_dummies, dt, columns) -> Optional[np.ndarray]:
    """把行业标签/哑变量转成当日 N×K 哑变量矩阵。"""
    if industry_dummies is None:
        return None
    # 静态哑变量矩阵：index=股票，columns=行业哑变量名
    if (
        isinstance(industry_dummies, pd.DataFrame)
        and industry_dummies.shape[0] == len(columns)
        and isinstance(industry_dummies.index, pd.Index)
        and industry_dummies.index.equals(pd.Index(columns))
        and industry_dummies.shape[1] > 1
        and not isinstance(industry_dummies.columns, pd.DatetimeIndex)
    ):
        return industry_dummies.reindex(columns).to_numpy(dtype=float)
    # 面板行业标签：index=日期，columns=股票
    if isinstance(industry_dummies, pd.DataFrame):
        if dt not in industry_dummies.index:
            return None
        labels = industry_dummies.loc[dt].reindex(columns)
        if labels.dropna().empty:
            return None
        dummies = pd.get_dummies(labels, dtype=float)
        # 去掉一类避免与截距完全共线
        if dummies.shape[1] > 1:
            dummies = dummies.iloc[:, 1:]
        return dummies.to_numpy(dtype=float)
    return None


def neutralize(
    x: pd.DataFrame,
    industry_dummies: Optional[pd.DataFrame] = None,
    market_cap: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """行业/市值中性化：逐日最小二乘回归取残差。

    industry_dummies 支持两种形式：
      * 行业标签面板（index=日期、columns=股票，值为行业名）；
      * 静态行业哑变量矩阵（index=股票，columns=行业名）。
    market_cap 支持面板或静态 Series（按股票对齐）。
    两者都没有时打 WARNING 并原样返回。
    """
    if industry_dummies is None and market_cap is None:
        logger.warning("neutralize 缺少行业与市值数据，跳过中性化（结果未中性）")
        return x.copy()

    out = x.copy()
    for dt in x.index:
        y = x.loc[dt].to_numpy(dtype=float)
        parts = [np.ones((len(x.columns), 1))]
        ind_mat = _industry_matrix(industry_dummies, dt, x.columns)
        if ind_mat is not None:
            parts.append(ind_mat)
        if market_cap is not None:
            if isinstance(market_cap, pd.DataFrame):
                cap = market_cap.loc[dt].reindex(x.columns).to_numpy(dtype=float) if dt in market_cap.index else np.full(len(x.columns), np.nan)
            else:
                cap = pd.Series(market_cap).reindex(x.columns).to_numpy(dtype=float)
            with np.errstate(divide="ignore", invalid="ignore"):
                log_cap = np.log(np.where(cap > 0, cap, np.nan))
            parts.append(log_cap.reshape(-1, 1))
        X = np.column_stack(parts)
        valid = np.isfinite(y) & np.isfinite(X).all(axis=1)
        if valid.sum() < X.shape[1] + 1:
            out.loc[dt] = np.nan
            continue
        beta, *_ = np.linalg.lstsq(X[valid], y[valid], rcond=None)
        resid = np.full(len(y), np.nan)
        resid[valid] = y[valid] - X[valid] @ beta
        out.loc[dt] = resid
    return out


def process_factor(
    x: pd.DataFrame,
    winsor: bool = True,
    fillna: bool = True,
    do_neutralize: bool = True,
    standardize: bool = True,
    industry: Optional[pd.DataFrame] = None,
    market_cap: Optional[pd.DataFrame] = None,
    mad_n: float = 3.0,
    fill_method: str = "industry_mean",
) -> pd.DataFrame:
    """一键四步预处理：去极值 → 填充 → 中性化 → 标准化。"""
    out = x.copy()
    if winsor:
        out = winsorize_mad(out, n=mad_n)
    if fillna:
        out = fill_na(out, method=fill_method, industry=industry)
    if do_neutralize:
        out = neutralize(out, industry, market_cap)
    if standardize:
        out = zscore(out)
    return out
