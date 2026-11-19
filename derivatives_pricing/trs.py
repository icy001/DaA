# -*- coding: utf-8 -*-
"""收益互换（TRS）保证金与损益模拟（derivatives_pricing/trs.py）——仅模拟。"""
from __future__ import annotations

from typing import Dict

__all__ = ["trs_pnl_simulation"]


def trs_pnl_simulation(underlying_return: float, notional: float, margin_rate: float,
                       financing_rate: float, term_days: int,
                       maintenance_margin: float = 0.25) -> Dict[str, float]:
    """TRS 模拟：保证金占用、融资成本、浮动盈亏、强平线与杠杆。

    ``underlying_return`` 为区间累计收益率（0.10 表示 +10%）。
    """
    notional = float(notional)
    margin = notional * float(margin_rate)
    cost = notional * float(financing_rate) * int(term_days) / 365.0
    pnl = notional * float(underlying_return) - cost
    equity = margin + pnl
    leverage = notional / margin if margin > 0 else float("inf")
    # 强平线：权益跌破维持保证金比例
    liquidation_return = (float(maintenance_margin) * margin - margin + cost) / notional
    return {"notional": notional, "margin": margin, "financing_cost": cost,
            "pnl": pnl, "equity": equity, "leverage": leverage,
            "return_on_margin": pnl / margin if margin > 0 else 0.0,
            "liquidation_return": liquidation_return,
            "liquidated": bool(equity <= float(maintenance_margin) * margin),
            "term_days": int(term_days)}
