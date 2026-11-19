"""技术形态标注：均线金叉死叉 / MACD 金叉死叉与顶底背离 / 关键位突破。

设计要点：
1. 每个标注可独立开关，默认只开均线金叉死叉（`DEFAULT_PATTERNS`），避免图面杂乱；
2. **未来函数红线**：所有标注只使用「当根及之前」的K线。
   - 局部极值（背离用）必须等右侧 `confirm_right` 根K线走完才算成立，
     因此背离的标注日期是「确认日」而不是极值日；
   - 确认日若超出当前数据末尾，则直接跳过该极值（不能提前画到未来K线上）；
3. 所有函数返回统一的标注表：index=该根K线的时间，columns=kind/sub/label/price/direction/detail，
   其中 price 是画箭头用的 y 坐标（上沿标注取 high，下沿标注取 low）。
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

# 默认只开均线金叉死叉
DEFAULT_PATTERNS = {"ma_cross": True, "macd_div": False, "breakout": False}

_ANNOTATION_COLUMNS = ["kind", "sub", "label", "price", "direction", "detail"]


def _empty_annotations() -> pd.DataFrame:
    df = pd.DataFrame(columns=_ANNOTATION_COLUMNS)
    df.index = pd.DatetimeIndex([], name="date")
    return df


def _annotations(rows: list) -> pd.DataFrame:
    """把 [{date, kind, sub, label, price, direction, detail}] 转成标准标注表。"""
    if not rows:
        return _empty_annotations()
    out = pd.DataFrame(rows)
    out["date"] = pd.to_datetime(out["date"])
    out = out.set_index("date").sort_index()
    out = out[~out.index.duplicated(keep="first")]
    return out[_ANNOTATION_COLUMNS]


def _require_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame()
    need = {"high", "low", "close"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"形态标注需要列 {sorted(need)}，缺少 {sorted(missing)}")
    return df


def mark_ma_cross(df: pd.DataFrame, fast: int = 5, slow: int = 20) -> pd.DataFrame:
    """均线金叉/死叉标注（fast 上穿 slow=金叉，下穿=死叉）。"""
    df = _require_ohlc(df)
    if df.empty or len(df) < slow + 2:
        return _empty_annotations()
    ma_fast = df["close"].rolling(fast).mean()
    ma_slow = df["close"].rolling(slow).mean()
    above = (ma_fast > ma_slow).to_numpy()
    rows = []
    for i in range(1, len(df)):
        if np.isnan(ma_slow.iloc[i]) or np.isnan(ma_slow.iloc[i - 1]):
            continue
        if above[i] and not above[i - 1]:
            rows.append({"date": df.index[i], "kind": "ma_cross", "sub": "golden",
                         "label": f"金叉{fast}/{slow}", "price": float(df["low"].iloc[i]),
                         "direction": "up", "detail": f"MA{fast} 上穿 MA{slow}"})
        elif not above[i] and above[i - 1]:
            rows.append({"date": df.index[i], "kind": "ma_cross", "sub": "death",
                         "label": f"死叉{fast}/{slow}", "price": float(df["high"].iloc[i]),
                         "direction": "down", "detail": f"MA{fast} 下穿 MA{slow}"})
    return _annotations(rows)


def macd_series(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9):
    """返回 (dif, dea, hist)，供标注与指标副图复用。"""
    close = df["close"].astype(float)
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2
    return dif, dea, hist


def mark_macd_divergence(df: pd.DataFrame, min_gap: int = 5, confirm_right: int = 2,
                         order: int = 3) -> pd.DataFrame:
    """MACD 金叉/死叉 + 顶底背离（背离用局部极值点对比，最小间隔 min_gap 避免密集误判）。

    顶背离：价格创新高、DIF 未创新高 → 红色虚线（direction=down）；
    底背离：价格创新低、DIF 未创新低 → 绿色虚线（direction=up）。
    标注日期取「极值右移 confirm_right 根后的确认日」，绝不早于可确认时点。
    """
    df = _require_ohlc(df)
    if df.empty or len(df) < 40:
        return _empty_annotations()
    dif, dea, _ = macd_series(df)
    rows = []
    # ---- MACD 金叉 / 死叉 ----
    above = (dif > dea).to_numpy()
    for i in range(1, len(df)):
        if above[i] and not above[i - 1]:
            rows.append({"date": df.index[i], "kind": "macd_cross", "sub": "golden",
                         "label": "MACD金叉", "price": float(df["low"].iloc[i]),
                         "direction": "up", "detail": "DIF 上穿 DEA"})
        elif not above[i] and above[i - 1]:
            rows.append({"date": df.index[i], "kind": "macd_cross", "sub": "death",
                         "label": "MACD死叉", "price": float(df["high"].iloc[i]),
                         "direction": "down", "detail": "DIF 下穿 DEA"})
    # ---- 顶/底背离 ----
    try:
        from scipy.signal import argrelextrema
    except ImportError:  # 无 scipy 时退化为简单局部极值
        argrelextrema = None
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    dif_v = dif.to_numpy(dtype=float)
    if argrelextrema is not None:
        highs = argrelextrema(high, np.greater_equal, order=order)[0]
        lows = argrelextrema(low, np.less_equal, order=order)[0]
    else:
        highs = np.array([i for i in range(order, len(high) - order)
                          if high[i] == max(high[i - order:i + order + 1])])
        lows = np.array([i for i in range(order, len(low) - order)
                         if low[i] == min(low[i - order:i + order + 1])])
    last = len(df) - 1
    for peaks, cmp_price, cmp_dif, kind_label, direction, sub in (
            (highs, np.greater, np.less, "顶背离", "down", "top"),
            (lows, np.less, np.greater, "底背离", "up", "bottom")):
        for a, b in zip(peaks[:-1], peaks[1:]):
            if b - a < min_gap:  # 间隔太近，不判背离
                continue
            confirm = b + confirm_right
            if confirm > last:  # 尚未确认 → 不标注，避免未来函数
                continue
            price_col = high if sub == "top" else low
            if cmp_price(price_col[b], price_col[a]) and cmp_dif(dif_v[b], dif_v[a]):
                y = float(df["high"].iloc[confirm]) if sub == "top" else float(df["low"].iloc[confirm])
                rows.append({"date": df.index[confirm], "kind": "macd_div", "sub": sub,
                             "label": kind_label, "price": y, "direction": direction,
                             "detail": f"极值日 {df.index[b].strftime('%Y-%m-%d')} 确认于"
                                       f" {df.index[confirm].strftime('%Y-%m-%d')}"})
    return _annotations(rows)


def mark_breakout(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """关键位突破：近 N 日（不含当根）最高价=压力位、最低价=支撑位。"""
    df = _require_ohlc(df)
    if df.empty or len(df) < window + 2:
        return _empty_annotations()
    resistance = df["high"].rolling(window).max().shift(1)
    support = df["low"].rolling(window).min().shift(1)
    rows = []
    for i in range(len(df)):
        if np.isnan(resistance.iloc[i]):
            continue
        close = float(df["close"].iloc[i])
        if close > float(resistance.iloc[i]):
            rows.append({"date": df.index[i], "kind": "breakout", "sub": "up",
                         "label": "突破压力位", "price": float(df["high"].iloc[i]),
                         "direction": "up", "detail": f"收盘 {close:.2f} > 前{window}日压力位 {resistance.iloc[i]:.2f}"})
        elif close < float(support.iloc[i]):
            rows.append({"date": df.index[i], "kind": "breakdown", "sub": "down",
                         "label": "跌破支撑位", "price": float(df["low"].iloc[i]),
                         "direction": "down", "detail": f"收盘 {close:.2f} < 前{window}日支撑位 {support.iloc[i]:.2f}"})
    return _annotations(rows)


def annotate_all(df: pd.DataFrame, patterns: Optional[Dict[str, bool]] = None,
                 fast: int = 5, slow: int = 20, window: int = 20) -> pd.DataFrame:
    """按开关汇总标注，默认只开 ma_cross。"""
    patterns = {**DEFAULT_PATTERNS, **(patterns or {})}
    frames = []
    if patterns.get("ma_cross"):
        frames.append(mark_ma_cross(df, fast=fast, slow=slow))
    if patterns.get("macd_div"):
        frames.append(mark_macd_divergence(df))
    if patterns.get("breakout"):
        frames.append(mark_breakout(df, window=window))
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return _empty_annotations()
    out = pd.concat(frames)
    return out.sort_index()


__all__ = ["DEFAULT_PATTERNS", "mark_ma_cross", "mark_macd_divergence",
           "mark_breakout", "annotate_all", "macd_series"]
