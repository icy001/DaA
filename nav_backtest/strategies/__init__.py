# -*- coding: utf-8 -*-
"""FOF 资产配置策略模板（nav_backtest/strategies/）

统一接口：``generate_weights(nav_frame, asof, **params) -> Dict[str, float]``。

硬约束（第 10 步 10.3）：
* ``nav_frame`` 只包含 ``asof`` 及之前的**已披露**净值（调用方负责先过
  ``decision_date >= nav_date + disclosure_lag_days`` 闸门），策略内部不得再回看未来；
* 返回权重之和必须归一到 1（全空仓时返回 ``{}``，由引擎持币）；
* 单个权重不得超过 ``max_weight``（默认 0.40），防止伪分散。
"""
from __future__ import annotations

from typing import Dict

import pandas as pd

__all__ = ["apply_weight_caps", "equal_weight", "risk_parity",
           "nav_momentum", "reits_premium_arbitrage", "neeq_value_screen"]


def apply_weight_caps(weights: Dict[str, float], max_weight: float = 0.40,
                      cash_buffer: float = 0.0) -> Dict[str, float]:
    """权重归一 + 单标的上限 + 现金缓冲（迭代截断，避免一次性截断后再次超限）。"""
    clean = {str(k): max(float(v), 0.0) for k, v in dict(weights or {}).items() if v and v > 0}
    total = sum(clean.values())
    if total <= 0:
        return {}
    target = max(1.0 - float(cash_buffer), 0.0)
    clean = {k: v / total * target for k, v in clean.items()}
    for _ in range(20):
        over = {k: v for k, v in clean.items() if v > max_weight + 1e-12}
        if not over:
            break
        excess = 0.0
        for key in over:
            excess += clean[key] - max_weight
            clean[key] = max_weight
        rest = {k: v for k, v in clean.items() if v < max_weight - 1e-12}
        base = sum(rest.values())
        if base <= 0:
            break
        for key in rest:
            clean[key] += excess * clean[key] / base
    return clean


def _window(nav_frame: pd.DataFrame, window: int) -> pd.DataFrame:
    frame = pd.DataFrame(nav_frame).sort_index()
    frame.index = pd.to_datetime(frame.index)
    return frame.tail(int(window)) if window else frame


def equal_weight(nav_frame: pd.DataFrame, asof=None, max_weight: float = 0.40,
                 **_ignored) -> Dict[str, float]:
    """等权重：对窗口内有有效净值的全部产品等权。"""
    frame = _window(nav_frame, 0)
    codes = [c for c in frame.columns if frame[c].dropna().shape[0] >= 2]
    if not codes:
        return {}
    return apply_weight_caps({c: 1.0 for c in codes}, max_weight=max_weight)


def risk_parity(nav_frame: pd.DataFrame, asof=None, window: int = 60,
                max_weight: float = 0.40, **_ignored) -> Dict[str, float]:
    """风险平价（逆波动率近似）：波动越低权重越高；无波动数据时退化为等权。"""
    frame = _window(nav_frame, window)
    vols = {}
    for code in frame.columns:
        ret = frame[code].pct_change().dropna()
        if len(ret) >= 5 and float(ret.std(ddof=1)) > 0:
            vols[code] = float(ret.std(ddof=1))
    if not vols:
        return equal_weight(frame, max_weight=max_weight)
    inv = {code: 1.0 / vol for code, vol in vols.items()}
    total = sum(inv.values())
    return apply_weight_caps({k: v / total for k, v in inv.items()}, max_weight=max_weight)


def nav_momentum(nav_frame: pd.DataFrame, asof=None, window: int = 60, top_k: int = 2,
                 max_weight: float = 0.40, **_ignored) -> Dict[str, float]:
    """净值动量轮动：按窗口累计涨幅排序，持有前 K 名（等权）。"""
    frame = _window(nav_frame, window + 1)
    scores = {}
    for code in frame.columns:
        series = frame[code].dropna()
        if len(series) >= 3 and float(series.iloc[0]) > 0:
            scores[code] = float(series.iloc[-1] / series.iloc[0] - 1.0)
    if not scores:
        return {}
    picked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:max(int(top_k), 1)]
    picked = [(code, score) for code, score in picked if score > 0]   # 负动量持币
    if not picked:
        return {}
    return apply_weight_caps({code: 1.0 for code, _ in picked}, max_weight=max_weight)


def reits_premium_arbitrage(premium_pct: Dict[str, float], asof=None,
                            buy_below: float = -0.10, sell_above: float = 0.15,
                            max_weight: float = 0.40, **_ignored) -> Dict[str, float]:
    """REITs 折溢价套利：折价 >10% 买入，溢价 >15% 清仓，其余持币。"""
    picks = {str(code): 1.0 for code, prem in dict(premium_pct or {}).items()
             if prem is not None and prem == prem and float(prem) <= float(buy_below)}
    if not picks:
        return {}
    return apply_weight_caps(picks, max_weight=max_weight)


def neeq_value_screen(fundamentals: pd.DataFrame, asof=None, top_k: int = 5,
                      max_pb: float = 2.0, min_roe: float = 0.08,
                      min_amount: float = 1_000_000.0, max_weight: float = 0.40,
                      **_ignored) -> Dict[str, float]:
    """新三板价值选股：低 PB + 高 ROE，叠加流动性过滤（成交额下限）。"""
    frame = pd.DataFrame(fundamentals)
    if frame.empty:
        return {}
    needed = {"pb", "roe"}
    if not needed.issubset(set(frame.columns)):
        raise ValueError(f"新三板价值选股缺少字段 {sorted(needed - set(frame.columns))}")
    code_col = "symbol" if "symbol" in frame.columns else frame.index.name or "index"
    work = frame.reset_index() if code_col == "index" else frame.copy()
    if code_col == "index":
        work = work.rename(columns={"index": "symbol"})
    work = work[pd.to_numeric(work["pb"], errors="coerce") <= float(max_pb)]
    work = work[pd.to_numeric(work["roe"], errors="coerce") >= float(min_roe)]
    if "amount" in work.columns:
        work = work[pd.to_numeric(work["amount"], errors="coerce") >= float(min_amount)]
    if work.empty:
        return {}
    work = work.sort_values(["pb", "roe"], ascending=[True, False]).head(max(int(top_k), 1))
    return apply_weight_caps({str(code): 1.0 for code in work["symbol"]}, max_weight=max_weight)
