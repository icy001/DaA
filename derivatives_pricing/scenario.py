# -*- coding: utf-8 -*-
"""情景分析与 VaR（derivatives_pricing/scenario.py）——仅模拟，禁止实盘。"""
from __future__ import annotations

from typing import Callable, Dict, Iterable

import numpy as np

__all__ = ["DEFAULT_SCENARIOS", "scenario_analysis", "value_at_risk"]

DEFAULT_SCENARIOS = {
    "大涨": 0.20, "小涨": 0.05, "震荡": 0.0, "小跌": -0.05,
    "大跌": -0.20, "黑天鹅": -0.40,
}


def scenario_analysis(underlying_moves: Dict[str, float],
                      pnl_fn: Callable[[float], float]) -> Dict[str, Dict[str, float]]:
    """对每个情景的标的涨跌幅调用 ``pnl_fn``，输出损益与相对基准的差值。"""
    moves = dict(underlying_moves or DEFAULT_SCENARIOS)
    out: Dict[str, Dict[str, float]] = {}
    for name, move in moves.items():
        pnl = float(pnl_fn(float(move)))
        out[str(name)] = {"underlying_move": float(move), "pnl": pnl,
                          "pnl_pct": pnl if abs(pnl) <= 1.0 else pnl / 100.0}
    return out


def value_at_risk(pnl_samples: Iterable[float], confidence: float = 0.95) -> Dict[str, float]:
    """历史模拟法 VaR（返回正数表示最大预期亏损）。"""
    samples = np.asarray([float(x) for x in pnl_samples], dtype=float)
    if samples.size == 0:
        raise ValueError("VaR 需要至少 1 个损益样本")
    confidence = min(max(float(confidence), 0.0), 1.0)
    var = -float(np.quantile(samples, 1.0 - confidence))
    tail = samples[samples <= np.quantile(samples, 1.0 - confidence)]
    return {"var": max(var, 0.0), "expected_shortfall": max(-float(tail.mean()), 0.0),
            "confidence": confidence, "n_samples": int(samples.size)}
