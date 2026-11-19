"""未来函数检测器（第 5 步 5.9.6）。

回测好看、实盘亏钱的头号原因就是未来函数。本模块提供三种互补检测：

  * check_lead            因子值与「次日收益」相关性是否异常高于当日/昨日；
  * check_shift           把因子值 shift(1) 后 IC 是否显著下降；
  * check_rolling_window  在数据未来区间注入扰动，看历史日期的因子值是否被影响
                          （最可靠，能直接抓住 shift(-1) 型伪因子）。

所有函数返回结构化 dict，并附带中文诊断报告，不抛异常（除参数错误）。
"""
from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from .base import FactorData

logger = logging.getLogger(__name__)

__all__ = ["check_lead", "check_shift", "check_rolling_window"]


def _align_pair(a: pd.DataFrame, b: pd.DataFrame):
    idx = a.index.intersection(b.index)
    cols = a.columns.intersection(b.columns)
    return a.loc[idx, cols], b.loc[idx, cols]


def _mean_row_corr(a: pd.DataFrame, b: pd.DataFrame, method: str = "spearman") -> float:
    a, b = _align_pair(a, b)
    vals = []
    for dt in a.index:
        x, y = a.loc[dt], b.loc[dt]
        valid = x.notna() & y.notna()
        if valid.sum() < 3:
            continue
        try:
            c = x[valid].corr(y[valid], method=method)
            if np.isfinite(c):
                vals.append(float(c))
        except Exception:
            continue
    return float(np.mean(vals)) if vals else np.nan


def _daily_returns(close: pd.DataFrame) -> pd.DataFrame:
    return close.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)


def check_lead(
    factor_values: pd.DataFrame,
    returns: pd.DataFrame,
    high_corr: float = 0.35,
    ratio_threshold: float = 2.5,
) -> Dict[str, object]:
    """检测因子值是否与次日收益相关过高。

    returns 为日收益面板；若传入的已是「次日收益」，结果会偏保守。
    典型未来函数：corr_future 远高于 corr_today 与 corr_past。
    """
    fwd = returns.shift(-1)
    corr_future = _mean_row_corr(factor_values, fwd)
    corr_today = _mean_row_corr(factor_values, returns)
    corr_past = _mean_row_corr(factor_values, returns.shift(1))
    denom = max(abs(corr_today) if np.isfinite(corr_today) else 0.0,
                abs(corr_past) if np.isfinite(corr_past) else 0.0, 1e-6)
    ratio = corr_future / denom if np.isfinite(corr_future) else np.nan
    suspicious = bool(
        np.isfinite(corr_future)
        and (corr_future > high_corr or (np.isfinite(ratio) and ratio > ratio_threshold and corr_future > 0.1))
    )
    report = (
        f"corr(因子_t, 收益_t+1)={corr_future:.4f}, "
        f"corr(因子_t, 收益_t)={corr_today:.4f}, "
        f"corr(因子_t, 收益_t-1)={corr_past:.4f}, 比值={ratio:.2f}"
        + ("；疑似未来函数" if suspicious else "；未发现明显异常")
    )
    return {
        "corr_future": corr_future,
        "corr_today": corr_today,
        "corr_past": corr_past,
        "future_ratio": ratio,
        "suspicious": suspicious,
        "report": report,
    }


def check_shift(
    factor_values: pd.DataFrame,
    close: pd.DataFrame,
    decline_threshold: float = 0.05,
    high_corr: float = 0.2,
) -> Dict[str, object]:
    """把因子值 shift(1) 后，与次日收益的相关性是否显著下降。"""
    returns = _daily_returns(close)
    fwd = returns.shift(-1)
    ic_raw = _mean_row_corr(factor_values, fwd)
    ic_shifted = _mean_row_corr(factor_values.shift(1), fwd)
    decline = ic_raw - ic_shifted if np.isfinite(ic_raw) and np.isfinite(ic_shifted) else np.nan
    suspicious = bool(
        np.isfinite(decline) and decline > decline_threshold and ic_raw > high_corr
    )
    report = (
        f"原始IC={ic_raw:.4f}, shift(1)后IC={ic_shifted:.4f}, 下降={decline:.4f}"
        + ("；shift 后显著下降，疑似使用未来数据" if suspicious else "；正常")
    )
    return {
        "ic_raw": ic_raw,
        "ic_shifted": ic_shifted,
        "ic_decline": decline,
        "suspicious": suspicious,
        "report": report,
    }


def _build_data(data: FactorData, frames: Dict[str, pd.DataFrame]) -> FactorData:
    return FactorData(
        close=frames["close"], open=frames["open"], high=frames["high"],
        low=frames["low"], volume=frames["volume"], amount=frames["amount"],
        cap=frames.get("cap"), industry=frames.get("industry"),
    )


def check_rolling_window(
    factor_func: Callable[[FactorData], pd.DataFrame],
    data: FactorData,
    perturb_start_idx: Optional[int] = None,
    n_future: int = 5,
) -> Dict[str, object]:
    """在未来区间人工注入扰动，检查历史日期因子值是否变化。

    原理：t 日因子只能依赖 <=t 的数据。若扰动 t+2..t+5 的行情后，t 日及
    更早的因子值发生变化，说明因子偷看了未来。
    """
    n = len(data.close)
    if n < n_future + 20:
        return {
            "has_future_leak": False, "affected_dates": [], "detail": "样本太短，无法检测",
            "report": "样本太短（<25 日），跳过扰动检测",
        }
    t = perturb_start_idx if perturb_start_idx is not None else n - n_future - 5
    t = int(max(5, min(t, n - n_future - 1)))

    frames = {
        "close": data.close.copy(), "open": data.open.copy(),
        "high": data.high.copy(), "low": data.low.copy(),
        "volume": data.volume.copy(), "amount": data.amount.copy(),
        "cap": data.cap.copy() if data.cap is not None else None,
        "industry": data.industry.copy() if data.industry is not None else None,
    }
    try:
        base = factor_func(data)
        if not isinstance(base, pd.DataFrame):
            raise TypeError("因子函数必须返回 DataFrame")
        base = base.astype(float)
    except ValueError as exc:
        # FactorData.shift(-1) 会直接抛错，这本身就是未来函数
        if "未来" in str(exc) or "shift" in str(exc):
            return {
                "has_future_leak": True, "affected_dates": [], "suspicious": True,
                "detail": str(exc), "report": f"因子计算触发未来函数保护：{exc}",
            }
        raise

    # 扰动 t+1 .. t+n_future 的行情：shift(-1) 型伪因子在 t 日就会受影响
    start = min(t + 1, n - 1)
    end = min(t + n_future, n - 1)
    for name in ("close", "open", "high", "low"):
        frames[name].iloc[start:end + 1] *= 1.5
    frames["volume"].iloc[start:end + 1] *= 3.0
    frames["amount"].iloc[start:end + 1] *= 4.5

    try:
        perturbed = factor_func(_build_data(data, frames))
        if not isinstance(perturbed, pd.DataFrame):
            raise TypeError("因子函数必须返回 DataFrame")
        perturbed = perturbed.astype(float)
    except ValueError as exc:
        return {
            "has_future_leak": True, "affected_dates": [], "suspicious": True,
            "detail": str(exc), "report": f"扰动后因子计算触发未来保护：{exc}",
        }

    base, perturbed = _align_pair(base, perturbed)
    hist = base.index[base.index <= data.close.index[t]]
    affected: List[pd.Timestamp] = []
    for dt in hist:
        a = base.loc[dt].to_numpy(dtype=float)
        b = perturbed.loc[dt].to_numpy(dtype=float)
        same = (np.isnan(a) & np.isnan(b)) | np.isclose(a, b, rtol=1e-8, atol=1e-10, equal_nan=True)
        if not np.all(same):
            affected.append(dt)

    leak = len(affected) > 0
    report = (
        f"扰动区间 {frames['close'].index[start].date()}~{frames['close'].index[end].date()}，"
        f"受影响历史日期数={len(affected)}" + ("；存在未来函数" if leak else "；未发现未来函数")
    )
    return {
        "has_future_leak": leak,
        "suspicious": leak,
        "affected_dates": affected,
        "perturb_range": (frames["close"].index[start], frames["close"].index[end]),
        "detail": report,
        "report": report,
    }
