"""因子研究核心库（第 5 步 5.9）。

对外入口::

    from factor import FactorData, register_factor, get_factor, list_factors
    from factor import create_factor_engine

    @register_factor("my_momentum")
    def my_momentum(data: FactorData):
        return data.close.pct_change(20)

    engine = create_factor_engine(source="free")
    df = engine.get_factor("alpha001", universe="hs300",
                           start="2020-01-01", end="2026-01-01")

⚠️ Alpha101/Alpha191 是因子库，不是交易策略；单因子 IC 普遍很低，
必须经过评估→合成→组合构建→样本外回测后才能考虑实盘。
"""
from __future__ import annotations

from .base import (
    FACTOR_REGISTRY,
    FactorData,
    build_factor_data,
    get_factor,
    list_factors,
    register_factor,
)
from .factor_engine import FactorEngine, create_factor_engine

__all__ = [
    "FactorData",
    "build_factor_data",
    "register_factor",
    "get_factor",
    "list_factors",
    "FACTOR_REGISTRY",
    "FactorEngine",
    "create_factor_engine",
]
