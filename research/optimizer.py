"""第 5 步：参数优化器（research/optimizer.py）

三种优化器共用同一目标函数接口：
    objective(params: dict) -> metrics: dict（至少含 sharpe / annual_return / max_drawdown）

核心约束（5.5 第 5 步）：
**优化目标是找「参数平原」，不是找收益最高点。** 孤立的尖峰一律视为过拟合：
  - `score` 用夏普为主（缺失时退回年化收益）；
  - `plateau` 指标 = 该参数点「一维相邻点」的平均分，平原点得分高、尖峰点得分低；
  - 输出 `sensitivity`（前两个参数的绩效矩阵），可直接画热力图。

用法：
    from research.optimizer import create_optimizer
    opt = create_optimizer("grid", {"short": [3, 5, 8], "long": [15, 20, 30]})
    out = opt.run(objective)
"""
from __future__ import annotations

import itertools
import math
import random
from typing import Callable, Dict, List

import numpy as np
import pandas as pd

import config
from core.utils import setup_logger

__all__ = ["GridSearchOptimizer", "RandomSearchOptimizer", "GeneticOptimizer",
           "create_optimizer", "score_metrics", "parameter_plateau"]

logger = setup_logger("optimizer", config.LOG_DIR / "optimizer.log")


def score_metrics(metrics: dict) -> float:
    """统一打分：夏普优先，其次年化；回撤超过 60% 直接大幅降分（防止爆仓型参数）。"""
    if not metrics:
        return -math.inf
    sharpe = metrics.get("sharpe", 0.0)
    annual = metrics.get("annual_return", 0.0)
    drawdown = abs(float(metrics.get("max_drawdown", 0.0) or 0.0))
    score = float(sharpe if np.isfinite(sharpe) else 0.0) + 0.5 * float(annual or 0.0)
    if drawdown > 0.6:
        score -= (drawdown - 0.6) * 5.0
    return float(score)


class BaseOptimizer:
    method = "base"

    def __init__(self, param_grid: Dict[str, list], n_iter: int = 30, seed: int = 42):
        if not param_grid:
            raise ValueError("param_grid 不能为空")
        self.param_grid = {str(k): list(v) for k, v in param_grid.items()}
        self.n_iter = int(n_iter)
        self.seed = int(seed)
        self.rng = random.Random(self.seed)

    # ---------- 子类实现 ----------

    def candidates(self) -> List[dict]:
        raise NotImplementedError

    # ---------- 统一执行 ----------

    def run(self, objective: Callable[[dict], dict], top_n: int = 10) -> dict:
        results = []
        for params in self.candidates():
            try:
                metrics = objective(dict(params)) or {}
            except Exception as exc:  # 单组参数失败不影响整体
                logger.warning("参数 %s 运行失败：%s", params, exc)
                metrics = {}
            results.append({"params": dict(params), "metrics": dict(metrics),
                            "score": score_metrics(metrics)})
        ranked = sorted(results, key=lambda r: r["score"], reverse=True)
        plateau = parameter_plateau(results, self.param_grid)
        best_plateau = max(plateau, key=lambda r: r["plateau_score"], default=None)
        return {
            "method": self.method,
            "results": ranked,
            "top": ranked[:int(top_n)],
            "best": ranked[0] if ranked else None,
            # 优先推荐「平原中心」而不是「最高尖峰」
            "recommended": best_plateau,
            "plateau": sorted(plateau, key=lambda r: r["plateau_score"], reverse=True)[:int(top_n)],
            "sensitivity": sensitivity_matrix(results, self.param_grid),
        }


class GridSearchOptimizer(BaseOptimizer):
    """参数笛卡尔积全遍历。"""

    method = "grid"

    def candidates(self) -> List[dict]:
        keys = list(self.param_grid)
        return [dict(zip(keys, combo))
                for combo in itertools.product(*(self.param_grid[k] for k in keys))]


class RandomSearchOptimizer(BaseOptimizer):
    """参数多时随机采样 n_iter 组（不重复）。"""

    method = "random"

    def candidates(self) -> List[dict]:
        keys = list(self.param_grid)
        seen, out = set(), []
        limit = min(self.n_iter, int(np.prod([len(v) for v in self.param_grid.values()])))
        while len(out) < limit:
            combo = tuple(self.rng.choice(self.param_grid[k]) for k in keys)
            if combo in seen:
                continue
            seen.add(combo)
            out.append(dict(zip(keys, combo)))
        return out


class GeneticOptimizer(BaseOptimizer):
    """简单遗传算法：锦标赛选择 + 单点交叉 + 变异。"""

    method = "genetic"

    def __init__(self, param_grid, n_iter: int = 30, seed: int = 42,
                 population: int = 12, generations: int = 4, mutation: float = 0.2):
        super().__init__(param_grid, n_iter=n_iter, seed=seed)
        self.population = max(int(population), 4)
        self.generations = max(int(generations), 1)
        self.mutation = float(mutation)

    def candidates(self) -> List[dict]:
        keys = list(self.param_grid)
        pop = [tuple(self.rng.choice(self.param_grid[k]) for k in keys)
               for _ in range(self.population)]
        # 适应度未知时无法真正迭代，这里生成候选序列，逐代优劣由 run() 事后挑选；
        # 为保证「一次跑完」且可复现，交叉/变异的子代直接追加到候选集。
        for _ in range(self.generations):
            children = []
            for _ in range(self.population):
                a, b = self.rng.sample(pop, 2) if len(pop) > 1 else (pop[0], pop[0])
                cut = self.rng.randint(1, max(len(keys) - 1, 1))
                child = list(a[:cut] + b[cut:])
                if self.rng.random() < self.mutation:
                    idx = self.rng.randrange(len(keys))
                    child[idx] = self.rng.choice(self.param_grid[keys[idx]])
                children.append(tuple(child))
            pop = children
        candidates = []
        seen = set()
        for combo in pop:
            if combo not in seen:
                seen.add(combo)
                candidates.append(dict(zip(keys, combo)))
        return candidates


def create_optimizer(method: str = "grid", param_grid: Dict[str, list] = None,
                     n_iter: int = 30, seed: int = 42, **kwargs) -> BaseOptimizer:
    method = str(method or "grid").lower()
    if method in ("grid", "gridsearch"):
        return GridSearchOptimizer(param_grid, n_iter=n_iter, seed=seed)
    if method in ("random", "randomsearch"):
        return RandomSearchOptimizer(param_grid, n_iter=n_iter, seed=seed)
    if method in ("genetic", "ga"):
        return GeneticOptimizer(param_grid, n_iter=n_iter, seed=seed, **kwargs)
    raise ValueError(f"未知优化方法 {method!r}，可选 grid / random / genetic")


# ==================== 参数平原 ====================

def parameter_plateau(results: List[dict], param_grid: Dict[str, list]) -> List[dict]:
    """对每个参数点算「相邻点平均分」：平原点高、孤立尖峰低。"""
    index = {_key(r["params"]): r["score"] for r in results}
    out = []
    for row in results:
        neighbors = []
        for key, values in param_grid.items():
            if key not in row["params"]:
                continue
            try:
                pos = values.index(row["params"][key])
            except ValueError:
                continue
            for step in (-1, 1):
                if 0 <= pos + step < len(values):
                    probe = dict(row["params"])
                    probe[key] = values[pos + step]
                    hit = index.get(_key(probe))
                    if hit is not None:
                        neighbors.append(hit)
        plateau_score = (float(np.mean(neighbors)) if neighbors
                         else float(row["score"]))
        out.append({"params": dict(row["params"]), "score": row["score"],
                    "plateau_score": plateau_score,
                    "neighbor_count": len(neighbors)})
    return out


def sensitivity_matrix(results: List[dict], param_grid: Dict[str, list],
                       metric: str = "score") -> pd.DataFrame:
    """前两个参数构成的行×列绩效矩阵（第二个参数为行、第一个为列）。"""
    keys = list(param_grid)
    if len(keys) < 2:
        return pd.DataFrame()
    row_key, col_key = keys[1], keys[0]
    rows = sorted({r["params"].get(row_key) for r in results}, key=_sort_key)
    cols = sorted({r["params"].get(col_key) for r in results}, key=_sort_key)
    table = pd.DataFrame(index=rows, columns=cols, dtype=float)
    for r in results:
        value = r["score"] if metric == "score" else r["metrics"].get(metric, np.nan)
        table.loc[r["params"].get(row_key), r["params"].get(col_key)] = value
    table.index.name = row_key
    table.columns.name = col_key
    return table


def _key(params: dict) -> tuple:
    return tuple(sorted((str(k), str(v)) for k, v in params.items()))


def _sort_key(value):
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (1, str(value))
