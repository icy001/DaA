"""第 5 步 · 第 7 步：稳健性与压力测试（research/validator.py）

四项检查（5.5 第 7 步）：
  1. 参数微扰：最优参数 ±10% 随机扰动 N 次，看绩效分布（一扰就崩 = 脆弱）；
  2. 成本加压：滑点 ×2、手续费 ×2 后仍能盈利才可用；
  3. 成交延迟：信号延后 1 根 K 线成交；
  4. 数据抖动：给 close 加 ±0.1% 噪声。

统一注入点：所有测试都接受 `objective(params) -> metrics`，默认由
`core.runner.run_backtest` 构造（见 `validate_robustness` 的 run_fn 参数），便于离线测试。

⚠️ 简化口径（重要）：
  当前账户层（core/account.py）**尚未读取** `cost_multiplier` / `slippage_multiplier`，
  执行器也不支持 `delay` / `noise_pct`。因此：
    - 仍先把这些参数注入 params，若策略层自行实现（或未来执行器支持），就能拿到真实结果
      （返回 `method="params"`）；
    - 若注入后指标毫无变化（说明没人读），退回**近似口径**（`method="approx"`）：
        * 成本：`总收益 - (成本倍数-1)*2*单边费率*交易次数 - (滑点倍数-1)*2*单边滑点*交易次数`，
          即每次买卖往返各承担一次成本/滑点；
        * 延迟：每笔交易近似损失「1 根 K 线的平均绝对日波动」（由总收益/交易日数估算）；
        * 噪声：每笔交易近似损失「2×噪声幅度」（买、卖各被扰动一次）。
      近似口径只改收益口径（年化按剩余天数重算），不改夏普/回撤，属于保守粗估。
"""
from __future__ import annotations

import random
from typing import Callable, Dict, List, Optional

import numpy as np

import config
from core.runner import run_backtest
from core.utils import setup_logger

__all__ = ["perturb_params", "cost_stress", "delay_test", "noise_test",
           "validate_robustness"]

logger = setup_logger("validator", config.LOG_DIR / "validator.log")

# 近似口径默认值：单边手续费 5bp、单边滑点 5bp（A 股佣金刚性下限 + 印花税摊薄的粗估）
DEFAULT_COST_PER_SIDE = 0.0005
DEFAULT_SLIP_PER_SIDE = 0.0005


# ==================== 参数微扰 ====================

def _is_number(value) -> bool:
    return (isinstance(value, (int, float, np.integer, np.floating))
            and not isinstance(value, bool))


def perturb_params(params: Dict, param_grid: Optional[Dict] = None, n: int = 100,
                   pct: float = 0.10, seed: int = 42) -> List[dict]:
    """对数值参数做 ±pct 随机扰动，生成最多 n 组（重复组自动去重）。

    - 只在 `param_grid` 给出的键上扰动（未给则扰动全部数值参数）；
    - 整数参数四舍五入取整并保证 > 0（因此整数参数的可取组数受限于邻近整数，
      小整数可能出现「凑不满 n 组」，此时返回实际去重后的组数）；
    - 非数值参数原样保留。
    """
    params = dict(params or {})
    keys = [k for k, v in params.items() if _is_number(v)]
    if param_grid:
        grid_keys = [k for k in keys if k in param_grid]
        keys = grid_keys or keys
    if not keys:
        return []

    rng = random.Random(int(seed))
    pct = abs(float(pct))
    seen, out = set(), []
    attempts, limit = 0, max(int(n) * 30, 100)
    while len(out) < int(n) and attempts < limit:
        attempts += 1
        candidate = dict(params)
        for key in keys:
            base = params[key]
            value = float(base) * (1.0 + rng.uniform(-pct, pct))
            if isinstance(base, (int, np.integer)):
                candidate[key] = max(1, int(round(value)))
            else:
                candidate[key] = round(float(value), 10)
        sig = tuple(sorted(candidate.items(), key=lambda kv: str(kv[0])))
        if sig in seen:
            continue
        seen.add(sig)
        out.append(candidate)
    return out


# ==================== 单项压力测试 ====================

def _annual_days() -> float:
    return float(config.INDICATOR_CONFIG["annual_trading_days"])


def _with_return(metrics: dict, total_return: float) -> dict:
    """只替换收益口径（年化按原天数重算），夏普/回撤沿用基线（简化口径）。"""
    out = dict(metrics or {})
    out["total_return"] = float(total_return)
    days = int(out.get("days", 0) or 0)
    if days > 0:
        years = max(days / _annual_days(), 1.0 / _annual_days())
        out["annual_return"] = (float((1.0 + total_return) ** (1.0 / years) - 1.0)
                                if total_return > -1 else -1.0)
    return out


def _same_metrics(a: dict, b: dict) -> bool:
    """注入参数后指标完全没变 → 说明策略/执行器没读这些参数。"""
    for key in ("total_return", "sharpe", "trade_count"):
        av, bv = a.get(key), b.get(key)
        try:
            if abs(float(av or 0) - float(bv or 0)) > 1e-12:
                return False
        except (TypeError, ValueError):
            if av != bv:
                return False
    return True


def _stress_result(base: dict, stressed: dict, method: str,
                   stressed_return: float) -> dict:
    base_return = float(base.get("total_return", 0.0) or 0.0)
    return {"base": base, "stressed": _with_return(base, stressed_return),
            "base_return": base_return, "stressed_return": float(stressed_return),
            "delta_return": float(stressed_return - base_return),
            "survives": bool(stressed_return > 0), "method": method}


def cost_stress(objective: Callable[[dict], dict], multipliers=(2.0, 2.0),
                base_metrics: Optional[dict] = None,
                cost_per_side: float = DEFAULT_COST_PER_SIDE,
                slippage_per_side: float = DEFAULT_SLIP_PER_SIDE) -> dict:
    """成本加压：滑点/手续费同时乘倍数，仍盈利才算过关。

    `objective(extra_params) -> metrics`：extra_params 里带 `cost_multiplier` /
    `slippage_multiplier`；策略不读时按模块头的近似口径估算。
    """
    cost_mul, slip_mul = float(multipliers[0]), float(multipliers[1])
    base = dict(base_metrics if base_metrics is not None else (objective({}) or {}))
    stressed = dict(objective({"cost_multiplier": cost_mul,
                               "slippage_multiplier": slip_mul}) or {})
    if not _same_metrics(base, stressed):
        return _stress_result(base, stressed, "params",
                              float(stressed.get("total_return", 0.0) or 0.0))

    trades = max(int(base.get("trade_count", 0) or 0), 0)
    extra = ((cost_mul - 1.0) * 2.0 * float(cost_per_side) * trades
             + (slip_mul - 1.0) * 2.0 * float(slippage_per_side) * trades)
    stressed_return = float(base.get("total_return", 0.0) or 0.0) - extra
    return _stress_result(base, stressed, "approx", stressed_return)


def delay_test(objective: Callable[[dict], dict], delay: int = 1,
               base_metrics: Optional[dict] = None) -> dict:
    """成交延迟：信号延后 `delay` 根 K 线成交的近似。

    注入 `delay` 参数给策略；不读时按「每笔交易损失 delay 根 K 线的平均绝对日收益」估算：
    平均日波动 = |总收益| / 交易日数（保守取绝对值，横盘时再兜底 0.2%）。
    """
    delay = max(int(delay), 1)
    base = dict(base_metrics if base_metrics is not None else (objective({}) or {}))
    stressed = dict(objective({"delay": delay}) or {})
    if not _same_metrics(base, stressed):
        return _stress_result(base, stressed, "params",
                              float(stressed.get("total_return", 0.0) or 0.0))

    trades = max(int(base.get("trade_count", 0) or 0), 0)
    days = max(int(base.get("days", 0) or 0), 1)
    daily_move = max(abs(float(base.get("total_return", 0.0) or 0.0)) / days, 0.002)
    stressed_return = (float(base.get("total_return", 0.0) or 0.0)
                       - daily_move * delay * trades)
    return _stress_result(base, stressed, "approx", stressed_return)


def noise_test(objective: Callable[[dict], dict], noise_pct: float = 0.001,
               base_metrics: Optional[dict] = None) -> dict:
    """数据抖动：close 加 ±`noise_pct` 噪声（默认 0.1%）。

    注入 `noise_pct` 给策略；不读时按「每笔交易买、卖各被扰动一次」估算：
    额外损失 = 2 × noise_pct × 交易次数。
    """
    noise_pct = abs(float(noise_pct))
    base = dict(base_metrics if base_metrics is not None else (objective({}) or {}))
    stressed = dict(objective({"noise_pct": noise_pct}) or {})
    if not _same_metrics(base, stressed):
        return _stress_result(base, stressed, "params",
                              float(stressed.get("total_return", 0.0) or 0.0))

    trades = max(int(base.get("trade_count", 0) or 0), 0)
    stressed_return = (float(base.get("total_return", 0.0) or 0.0)
                       - 2.0 * noise_pct * trades)
    return _stress_result(base, stressed, "approx", stressed_return)


# ==================== 汇总评分卡 ====================

def _decay(base_return: float, stressed_return: float) -> float:
    """收益衰减比例；基线本身不盈利时返回 1.0（视为衰减 100%）。"""
    base_return = float(base_return or 0.0)
    if base_return <= 0:
        return 0.0 if stressed_return > base_return else 1.0
    return float(1.0 - stressed_return / base_return)


def _status(ok: bool, warn: bool) -> str:
    return "pass" if ok else ("warn" if warn else "fail")


def validate_robustness(strategy_cls, best_params: dict, param_grid: Dict[str, list],
                        symbols: List[str], start: str, end: str, fetcher=None,
                        n_perturb: int = 100, seed: int = 42,
                        run_fn: Callable = None, initial_cash: float = None,
                        adjust: str = "qfq", profit_ratio_pass: float = 0.60,
                        decay_pass: float = 0.30, decay_warn: float = 0.50) -> dict:
    """跑四项稳健性检查，输出评分卡。

    判据（5.5 / 5.7）：
      - 微扰后盈利比例 >= 60% 才 pass（>= 40% warn，否则 fail）；
      - 成本 ×2 仍盈利才 pass（亏损 < 2% warn，否则 fail）；
      - 延迟 / 噪声后收益衰减 < 30% pass（< 50% warn，否则 fail）。
    `run_fn` 默认 core.runner.run_backtest，可注入离线桩。
    """
    run_fn = run_fn or run_backtest
    best_params = dict(best_params or {})
    symbols = [str(s) for s in (symbols or [])]

    def objective(extra: Optional[dict] = None) -> dict:
        params = dict(best_params)
        params.update(extra or {})
        try:
            result = run_fn(strategy_cls, params=params, symbols=symbols,
                            start=start, end=end, fetcher=fetcher,
                            initial_cash=initial_cash, adjust=adjust) or {}
        except TypeError:
            result = run_fn(strategy_cls, params, symbols, start, end,
                            fetcher, initial_cash) or {}
        return dict(result.get("metrics") or {})

    base = objective(None)
    checks = []

    # ---- 1. 参数微扰 ----
    samples = perturb_params(best_params, param_grid=param_grid, n=n_perturb,
                             pct=0.10, seed=seed)
    returns = [float(objective(p).get("total_return", 0.0) or 0.0) for p in samples]
    if returns:
        mean = float(np.mean(returns))
        std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
        win = float(np.mean([r > 0 for r in returns]))
        checks.append({
            "name": "参数微扰 ±10%",
            "status": _status(win >= profit_ratio_pass, win >= profit_ratio_pass * 0.7),
            "detail": (f"{len(returns)} 组：均值 {mean:.2%}，标准差 {std:.2%}，"
                       f"盈利比例 {win:.0%}"),
        })
    else:
        checks.append({"name": "参数微扰 ±10%", "status": "fail",
                       "detail": "没有可扰动的数值参数"})

    # ---- 2. 成本加压（滑点 ×2、手续费 ×2）----
    cost = cost_stress(objective, multipliers=(2.0, 2.0), base_metrics=base)
    checks.append({
        "name": "成本加压 ×2",
        "status": _status(cost["stressed_return"] > 0, cost["stressed_return"] > -0.02),
        "detail": (f"基线 {cost['base_return']:.2%} → 加压后 "
                   f"{cost['stressed_return']:.2%}（{cost['method']}）"),
    })

    # ---- 3. 成交延迟 1 根 K 线 ----
    delayed = delay_test(objective, delay=1, base_metrics=base)
    decay_delay = _decay(delayed["base_return"], delayed["stressed_return"])
    checks.append({
        "name": "成交延迟 1 根",
        "status": _status(decay_delay < decay_pass, decay_delay < decay_warn),
        "detail": (f"延迟后 {delayed['stressed_return']:.2%}，衰减 {decay_delay:.0%}"
                   f"（{delayed['method']}）"),
    })

    # ---- 4. 数据抖动 ±0.1% ----
    noisy = noise_test(objective, noise_pct=0.001, base_metrics=base)
    decay_noise = _decay(noisy["base_return"], noisy["stressed_return"])
    checks.append({
        "name": "数据抖动 ±0.1%",
        "status": _status(decay_noise < decay_pass, decay_noise < decay_warn),
        "detail": (f"抖动后 {noisy['stressed_return']:.2%}，衰减 {decay_noise:.0%}"
                   f"（{noisy['method']}）"),
    })

    weight = {"pass": 1.0, "warn": 0.5, "fail": 0.0}
    score = round(100.0 * sum(weight[c["status"]] for c in checks) / len(checks), 1)
    passed = all(c["status"] == "pass" for c in checks)
    logger.info("稳健性评分 %s/100，通过=%s", score, passed)
    return {"checks": checks, "score": score, "passed": passed}
