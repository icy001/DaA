# -*- coding: utf-8 -*-
"""欧式/美式期权定价（derivatives_pricing/pricing.py）——仅理论定价，禁止实盘。"""
from __future__ import annotations

from typing import Dict

import numpy as np
from scipy.stats import norm

__all__ = ["black_scholes", "binomial_tree_american", "monte_carlo_european"]


def black_scholes(S: float, K: float, T: float, r: float, sigma: float,
                  option_type: str = "call") -> Dict[str, float]:
    """BS 欧式期权价格 + 希腊字母；T<=0 返回内在价值。"""
    kind = str(option_type).lower()
    if kind not in ("call", "put"):
        raise ValueError("option_type 只能是 call / put")
    S, K, T, r, sigma = map(float, (S, K, T, r, sigma))
    if T <= 0 or sigma <= 0:
        intrinsic = max(S - K, 0.0) if kind == "call" else max(K - S, 0.0)
        return {"price": intrinsic, "delta": float(kind == "call"), "gamma": 0.0,
                "theta": 0.0, "vega": 0.0, "rho": 0.0}
    sqrt_t = np.sqrt(T)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    disc = np.exp(-r * T)
    if kind == "call":
        price = S * norm.cdf(d1) - K * disc * norm.cdf(d2)
        delta = norm.cdf(d1)
        rho = K * T * disc * norm.cdf(d2) / 100.0
        theta = (-S * norm.pdf(d1) * sigma / (2 * sqrt_t) - r * K * disc * norm.cdf(d2)) / 365.0
    else:
        price = K * disc * norm.cdf(-d2) - S * norm.cdf(-d1)
        delta = norm.cdf(d1) - 1.0
        rho = -K * T * disc * norm.cdf(-d2) / 100.0
        theta = (-S * norm.pdf(d1) * sigma / (2 * sqrt_t) + r * K * disc * norm.cdf(-d2)) / 365.0
    gamma = norm.pdf(d1) / (S * sigma * sqrt_t)
    vega = S * norm.pdf(d1) * sqrt_t / 100.0
    return {"price": float(price), "delta": float(delta), "gamma": float(gamma),
            "theta": float(theta), "vega": float(vega), "rho": float(rho),
            "d1": float(d1), "d2": float(d2)}


def monte_carlo_european(S: float, K: float, T: float, r: float, sigma: float,
                         n_sims: int = 100_000, option_type: str = "call",
                         seed: int = 20261112) -> Dict[str, float]:
    """蒙特卡洛欧式期权定价（GBM），返回价格与标准误。"""
    kind = str(option_type).lower()
    if kind not in ("call", "put"):
        raise ValueError("option_type 只能是 call / put")
    rng = np.random.default_rng(seed)
    z = rng.standard_normal(int(n_sims))
    ST = float(S) * np.exp((float(r) - 0.5 * float(sigma) ** 2) * float(T)
                           + float(sigma) * np.sqrt(float(T)) * z)
    payoff = np.maximum(ST - float(K), 0.0) if kind == "call" else \
        np.maximum(float(K) - ST, 0.0)
    disc = np.exp(-float(r) * float(T))
    price = disc * float(payoff.mean())
    stderr = float(disc * payoff.std(ddof=1) / np.sqrt(len(payoff)))
    return {"price": price, "stderr": stderr, "n_sims": int(n_sims),
            "option_type": kind}


def binomial_tree_american(S: float, K: float, T: float, r: float, sigma: float,
                           steps: int = 200, option_type: str = "call") -> Dict[str, float]:
    """CRR 二叉树美式期权定价（含提前行权价值）。"""
    kind = str(option_type).lower()
    if kind not in ("call", "put"):
        raise ValueError("option_type 只能是 call / put")
    steps = max(int(steps), 1)
    dt = float(T) / steps
    u = np.exp(float(sigma) * np.sqrt(dt))
    d = 1.0 / u
    p = (np.exp(float(r) * dt) - d) / (u - d)
    disc = np.exp(-float(r) * dt)
    j = np.arange(steps + 1)
    ST = float(S) * u ** (steps - j) * d ** j
    values = np.maximum(ST - float(K), 0.0) if kind == "call" else \
        np.maximum(float(K) - ST, 0.0)
    for level in range(steps - 1, -1, -1):
        j = np.arange(level + 1)
        node = float(S) * u ** (level - j) * d ** j
        values = disc * (p * values[:-1] + (1 - p) * values[1:])
        intrinsic = np.maximum(node - float(K), 0.0) if kind == "call" else \
            np.maximum(float(K) - node, 0.0)
        values = np.maximum(values, intrinsic)
    return {"price": float(values[0]), "steps": steps, "option_type": kind,
            "early_exercise": bool(kind == "put")}
