# -*- coding: utf-8 -*-
"""雪球（Autocallable）结构蒙特卡洛定价（derivatives_pricing/snowball.py）——仅模拟。"""
from __future__ import annotations

from typing import Dict, Sequence

import numpy as np

__all__ = ["snowball_pricing"]


def snowball_pricing(S0: float, ko_barrier: float, ki_barrier: float, coupon: float,
                     ko_observe_dates: Sequence[float], ki_observe_dates: Sequence[float],
                     r: float, sigma: float, n_sims: int = 50_000,
                     tenor_months: int = 24, barrier_mode: str = "price",
                     notional: float = 1.0, seed: int = 20261112) -> Dict:
    """雪球定价：逐日敲入观察 + 每月敲出观察。

    ``ko_barrier`` / ``ki_barrier`` 为**比例**（1.00 / 0.75 表示 100% / 75% 期初价）；
    ``coupon`` 为年化票息。返回理论价格、敲出/敲入概率、敲入后亏损期望与损益分布。
    """
    S0 = float(S0)
    ko = float(ko_barrier) * S0 if barrier_mode == "ratio" else float(ko_barrier)
    ki = float(ki_barrier) * S0 if barrier_mode == "ratio" else float(ki_barrier)
    months = max(int(tenor_months), 1)
    steps = months * 21                      # 每月 21 个交易日
    dt = 1.0 / 252.0
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((int(n_sims), steps))
    log_paths = np.cumsum((float(r) - 0.5 * float(sigma) ** 2) * dt
                          + float(sigma) * np.sqrt(dt) * z, axis=1)
    paths = S0 * np.exp(log_paths)
    paths = np.concatenate([np.full((int(n_sims), 1), S0), paths], axis=1)

    ko_months = [int(m) for m in ko_observe_dates] or list(range(1, months + 1))
    ko_steps = [min(m * 21, steps) for m in ko_months]
    ki_steps = [int(s) for s in ki_observe_dates] or list(range(1, steps + 1))

    ki_hit = np.zeros(int(n_sims), dtype=bool)
    for step in ki_steps:
        step = min(int(step), steps)
        ki_hit |= paths[:, step] <= ki

    knock_out_month = np.zeros(int(n_sims), dtype=int)
    for month, step in zip(ko_months, ko_steps):
        alive = (knock_out_month == 0)
        hit = alive & (paths[:, step] >= ko)
        knock_out_month[hit] = month

    coupon = float(coupon)
    payoff = np.zeros(int(n_sims))
    # 敲出：票息按持有月份计（年化 × 月数/12）
    out_mask = knock_out_month > 0
    payoff[out_mask] = float(notional) * (1.0 + coupon * knock_out_month[out_mask] / 12.0)
    # 未敲出：到期看是否敲入
    remain = ~out_mask
    end_price = paths[:, -1]
    no_ki = remain & ~ki_hit
    payoff[no_ki] = float(notional) * (1.0 + coupon * months / 12.0)
    ki_no_out = remain & ki_hit
    payoff[ki_no_out] = float(notional) * (end_price[ki_no_out] / S0)

    disc = np.exp(-float(r) * months / 12.0)
    price = float(disc * payoff.mean())
    pnl = payoff - float(notional)
    loss_after_ki = pnl[ki_no_out]
    n = int(n_sims)
    return {
        "price": price,
        "price_per_notional": price / float(notional),
        "p_knock_out": float(out_mask.sum() / n),
        "p_knock_in": float(ki_hit.sum() / n),
        "p_ki_no_ko": float(ki_no_out.sum() / n),
        "p_no_ki_no_ko": float(no_ki.sum() / n),
        "expected_loss_after_ki": float(loss_after_ki.mean()) if len(loss_after_ki) else 0.0,
        "expected_pnl": float(pnl.mean()),
        "pnl_std": float(pnl.std(ddof=1)),
        "pnl_quantiles": {str(q): float(np.quantile(pnl, q / 100.0))
                          for q in (1, 5, 25, 50, 75, 95, 99)},
        "n_sims": n, "tenor_months": months,
        "ko_barrier": ko, "ki_barrier": ki, "coupon": coupon,
    }
