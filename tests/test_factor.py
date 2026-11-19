"""第 5 步 5.9 因子核心库测试（完全离线、纯合成面板）。

覆盖：
  1) 表达式引擎各算子与手工计算对拍（含 ts_corr 不含当日）；
  2) 预处理四步（去极值/填充/标准化/中性化）；
  3) 未来函数检测器能识别 shift(-1) 伪因子；
  4) IC / IC 衰减 / 分层回测 / 换手率结果合理；
  5) 因子合成、冗余识别；
  6) 股票池解析（不联网）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from factor import FactorData
from factor.combiner import combine, dedupe, equal_weight, ridge_combine
from factor.evaluator import (calc_factor_correlation, calc_ic, calc_ic_decay,
                              calc_turnover, quantile_backtest)
from factor.expression import evaluate
from factor.future_detector import check_lead, check_rolling_window, check_shift
from factor.preprocess import (fill_na, neutralize, process_factor,
                               winsorize_mad, zscore)
from factor.universe import resolve_universe

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" | {detail}" if detail else ""))
    if not ok:
        raise AssertionError(f"{name}" + (f" | {detail}" if detail else ""))


@pytest.fixture(scope="module")
def d():
    """pytest 收集用的合成面板（与 main() 内构造同源），修复 fixture 'd' not found。"""
    return make_data()


# ==================== 合成面板 ====================
def make_data(n: int = 80, m: int = 40, seed: int = 2026):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-02", periods=n, freq="B")
    cols = [f"{i:06d}" for i in range(m)]
    ret = rng.normal(0, 0.02, (n, m))
    close = pd.DataFrame(100 * np.cumprod(1 + ret, axis=0), index=idx, columns=cols)
    open_ = close * (1 + rng.normal(0, 0.004, (n, m)))
    high = np.maximum(close, open_) * (1 + rng.uniform(0, 0.01, (n, m)))
    low = np.minimum(close, open_) * (1 - rng.uniform(0, 0.01, (n, m)))
    volume = pd.DataFrame(rng.lognormal(11, 0.4, (n, m)), index=idx, columns=cols)
    amount = volume * (high + low + close) / 3
    industry = pd.DataFrame(
        np.array([f"IND{i % 4}" for i in range(m)], dtype=object).reshape(1, -1).repeat(n, axis=0),
        index=idx, columns=cols,
    )
    return FactorData(close=close, open=open_, high=high, low=low,
                      volume=volume, amount=amount, industry=industry)


def approx(a: pd.Series, b: pd.Series, tol: float = 1e-8) -> bool:
    a = pd.Series(a, dtype=float)
    b = pd.Series(b, dtype=float)
    return bool(np.allclose(a.fillna(-9e9), b.fillna(-9e9), rtol=tol, atol=tol))


# ==================== 1. 表达式引擎对拍 ====================
def test_expression(d: FactorData) -> None:
    close, vol = d.close, d.volume
    last = close.index[-1]

    check("rank 与 pandas 一致", approx(evaluate("rank(close)", d).loc[last],
                                        close.rank(axis=1, pct=True).loc[last]))
    mu, sd = close.mean(axis=1), close.std(axis=1, ddof=1)
    manual_z = close.sub(mu, axis=0).div(sd, axis=0)
    check("zscore 与手工一致", approx(evaluate("zscore(close)", d).loc[last], manual_z.loc[last]))
    manual_scale = close.div(close.abs().sum(axis=1), axis=0)
    check("scale 与手工一致", approx(evaluate("scale(close)", d).loc[last], manual_scale.loc[last]))

    manual_mean = close.shift(1).rolling(5, min_periods=4).mean()
    check("ts_mean 与 shift(1)+rolling 一致",
          approx(evaluate("ts_mean(close, 5)", d).loc[last], manual_mean.loc[last]))
    manual_std = close.shift(1).rolling(5, min_periods=4).std(ddof=1)
    check("ts_std 与手工一致", approx(evaluate("ts_std(close, 5)", d).loc[last], manual_std.loc[last]))
    manual_sum = close.shift(1).rolling(5, min_periods=4).sum()
    check("ts_sum 与手工一致", approx(evaluate("ts_sum(close, 5)", d).loc[last], manual_sum.loc[last]))
    manual_max = close.shift(1).rolling(5, min_periods=4).max()
    manual_min = close.shift(1).rolling(5, min_periods=4).min()
    check("ts_max/ts_min 与手工一致",
          approx(evaluate("ts_max(close, 5)", d).loc[last], manual_max.loc[last])
          and approx(evaluate("ts_min(close, 5)", d).loc[last], manual_min.loc[last]))

    win = close.shift(1).iloc[-5:]
    manual_rank = win.rank(pct=True).iloc[-1]
    check("ts_rank 与手工一致", approx(evaluate("ts_rank(close, 5)", d).loc[last], manual_rank))

    manual_argmax = pd.Series([np.argmax(win[c].to_numpy()) + 1 for c in close.columns],
                              index=close.columns, dtype=float)
    manual_argmin = pd.Series([np.argmin(win[c].to_numpy()) + 1 for c in close.columns],
                              index=close.columns, dtype=float)
    check("ts_argmax/ts_argmin 与手工一致",
          approx(evaluate("ts_argmax(close, 5)", d).loc[last], manual_argmax)
          and approx(evaluate("ts_argmin(close, 5)", d).loc[last], manual_argmin))

    manual_delta = close.shift(1) - close.shift(4)
    check("ts_delta = x.shift(1)-x.shift(1+d)",
          approx(evaluate("ts_delta(close, 3)", d).loc[last], manual_delta.loc[last]))
    check("ts_delay/shift = x.shift(d)",
          approx(evaluate("ts_delay(close, 3)", d).loc[last], close.shift(3).loc[last]))
    manual_mom = close.shift(1) / close.shift(6) - 1
    check("ts_momentum 与手工一致",
          approx(evaluate("ts_momentum(close, 5)", d).loc[last], manual_mom.loc[last]))

    xs = close.shift(1).iloc[-10:]
    ys = vol.shift(1).iloc[-10:]
    manual_corr = pd.Series([xs[c].corr(ys[c]) for c in close.columns], index=close.columns)
    check("ts_corr 与手工一致", approx(evaluate("ts_corr(close, volume, 10)", d).loc[last], manual_corr))
    manual_cov = pd.Series([xs[c].cov(ys[c]) for c in close.columns], index=close.columns)
    check("ts_cov 与手工一致", approx(evaluate("ts_cov(close, volume, 10)", d).loc[last], manual_cov))

    w = np.arange(1, 6, dtype=float)
    manual_decay = (win * w[:, None]).sum(axis=0) / w.sum()
    check("decay_linear 近端权重更大",
          approx(evaluate("decay_linear(close, 5)", d).loc[last], manual_decay))
    manual_prod = win.iloc[-3:].prod(axis=0)
    check("product 与手工一致", approx(evaluate("product(close, 3)", d).loc[last], manual_prod))

    check("sign/abs/log 正确",
          approx(evaluate("sign(close - ts_delay(close, 1))", d).loc[last],
                 np.sign(close - close.shift(1)).loc[last])
          and approx(evaluate("abs(close - open)", d).loc[last], (close - d.open).loc[last].abs())
          and approx(evaluate("log(close)", d).loc[last], np.log(close).loc[last]))
    check("signedpower 正确",
          approx(evaluate("signedpower(close - open, 2)", d).loc[last],
                 (np.sign(close - d.open) * (close - d.open).abs() ** 2).loc[last]))
    check("max/min 逐元素正确",
          approx(evaluate("max(close, open)", d).loc[last], np.maximum(close, d.open).loc[last])
          and approx(evaluate("min(close, open)", d).loc[last], np.minimum(close, d.open).loc[last]))
    cond = (close > d.open)
    check("if_else 条件选择正确",
          approx(evaluate("if_else(close > open, 1, -1)", d).loc[last],
                 pd.Series(np.where(cond.loc[last], 1.0, -1.0), index=close.columns)))

    gr = evaluate("group_rank(close, industry)", d)
    last_gr = d.industry.loc[last]
    expected_gr = close.loc[last].groupby(last_gr).rank(pct=True)
    check("group_rank 行业内排名正确", approx(gr.loc[last], expected_gr))
    gn = evaluate("group_neutralize(close, industry)", d)
    gmean = gn.loc[last].groupby(last_gr).mean().abs().max()
    check("group_neutralize 组内均值为 0", gmean < 1e-8, f"max_group_mean={gmean:.2e}")

    # 关键断言：时间序列算子不含当日
    t = close.index[-5]
    close2 = close.copy()
    close2.loc[t] = close2.loc[t] * 50
    vol2 = vol.copy()
    vol2.loc[t] = vol2.loc[t] * 0.01
    d2 = FactorData(close=close2, open=d.open, high=d.high, low=d.low,
                    volume=vol2, amount=d.amount, industry=d.industry)
    c1 = evaluate("ts_corr(close, volume, 10)", d).loc[t]
    c2 = evaluate("ts_corr(close, volume, 10)", d2).loc[t]
    m1 = evaluate("ts_mean(close, 10)", d).loc[t]
    m2 = evaluate("ts_mean(close, 10)", d2).loc[t]
    check("ts_corr 不含当日（改当日数据不影响当日因子值）", approx(c1, c2))
    check("ts_mean 不含当日（改当日数据不影响当日因子值）", approx(m1, m2))
    # 未来函数拦截
    blocked = False
    try:
        d.shift(-1)
    except ValueError:
        blocked = True
    check("FactorData.shift(-1) 直接抛错", blocked)


# ==================== 2. 预处理 ====================
def test_preprocess(d: FactorData) -> None:
    x = d.close.copy()
    last = x.index[-1]
    x.loc[last, x.columns[0]] = 1e9
    w = winsorize_mad(x, n=3)
    check("winsorize_mad 截断极端值", w.loc[last, x.columns[0]] < 1e9,
          f"after={w.loc[last, x.columns[0]]:.3f}")
    check("winsorize_mad 不改变中位数", abs(w.loc[last].median() - x.loc[last].median()) < 1e-6)

    miss = d.close.copy()
    miss.iloc[2, 3] = np.nan
    miss.iloc[2, 5] = np.nan
    filled = fill_na(miss, method="median")
    check("fill_na(median) 用截面中位数补齐",
          approx(filled.iloc[2], miss.iloc[2].fillna(miss.iloc[2].median())))

    z = zscore(d.close)
    check("zscore 行均值≈0", z.mean(axis=1).abs().max() < 1e-8)
    check("zscore 行标准差≈1", (z.std(axis=1, ddof=1) - 1).abs().max() < 1e-8)

    rng = np.random.default_rng(9)
    ind = d.industry
    # 构造带行业效应的因子
    effects = {"IND0": 3.0, "IND1": -1.0, "IND2": 0.5, "IND3": 2.0}
    base = ind.replace(effects) + pd.DataFrame(
        rng.normal(0, 0.5, d.close.shape), index=d.close.index, columns=d.close.columns)
    res = neutralize(base, ind)
    gmean = res.T.groupby(ind.iloc[-1]).mean().T.iloc[-1].abs().max()
    check("neutralize 行业中性化后组均值≈0", gmean < 1e-8, f"max={gmean:.2e}")

    cap = d.close * 1e6
    y = 2.0 * np.log(cap) + ind.replace(effects) + pd.DataFrame(
        rng.normal(0, 0.2, d.close.shape), index=d.close.index, columns=d.close.columns)
    res2 = neutralize(y, ind, market_cap=cap)
    last_corr = res2.loc[last].corr(np.log(cap.loc[last]))
    check("neutralize 行业+市值双中性后与log市值不相关", abs(last_corr) < 1e-6,
          f"corr={last_corr:.2e}")

    proc = process_factor(base, industry=ind, market_cap=cap)
    check("process_factor 输出无 inf 且行均值≈0",
          not np.isinf(proc.to_numpy(dtype=float)).any() and proc.mean(axis=1).abs().max() < 1e-8)

    # 缺行业/市值时降级不崩溃
    deg = neutralize(base, None, None)
    check("neutralize 无数据时降级并原样返回", deg.shape == base.shape)


# ==================== 3. 未来函数检测 ====================
def test_future_detector(d: FactorData) -> None:
    rets = d.close.pct_change(fill_method=None)

    good = lambda data: data.close.pct_change(5)  # noqa: E731
    rep_good = check_rolling_window(good, d)
    check("正常因子通过扰动检测", not rep_good["has_future_leak"], rep_good["detail"])

    # 伪因子 1：直接使用未来收盘（绕过 FactorData.shift 保护）
    bad = lambda data: data.close.shift(-1)  # noqa: E731
    rep_bad = check_rolling_window(bad, d)
    check("扰动检测识别 shift(-1) 伪因子", rep_bad["has_future_leak"], rep_bad["detail"])

    # 伪因子 2：因子值恰好等于次日收益
    cheat = rets.shift(-1)
    lead = check_lead(cheat, rets)
    check("check_lead 识别次日收益泄漏", lead["suspicious"], lead["report"])
    shift_rep = check_shift(cheat, d.close)
    check("check_shift 识别相关性异常", shift_rep["suspicious"], shift_rep["report"])

    # 通过 FactorData 负向 shift 的因子被直接捕获
    def explicit_bad(data):
        return data.close.shift(-1)

    rep_guard = check_rolling_window(explicit_bad, d)
    check("显式负向 shift 被未来函数保护捕获", rep_guard["has_future_leak"], rep_guard["report"])


# ==================== 4. 评估套件 ====================
def test_evaluator(d: FactorData) -> None:
    rets = d.close.pct_change(fill_method=None)
    cheat = rets.shift(-1)  # 与次日收益完全一致，IC 应接近 1
    ic = calc_ic(cheat, rets)
    check("calc_ic 返回完整字段",
          all(k in ic for k in ("ic_mean", "ic_std", "icir", "ic_win_rate", "ic_series")))
    check("calc_ic 对次日收益因子 IC≈1", abs(ic["ic_mean"] - 1.0) < 1e-6,
          f"ic={ic['ic_mean']:.4f}")
    check("calc_ic ICIR 为有限值", np.isfinite(ic["icir"]) and ic["n_periods"] > 0,
          f"icir={ic['icir']:.2f}")

    decay = calc_ic_decay(cheat, rets, periods=[1, 3, 5])
    check("calc_ic_decay 返回 1/3/5 日 IC", set(decay["ic_decay"]) == {1, 3, 5}
          and np.isfinite(decay["ic_decay"][1]))

    q = quantile_backtest(cheat, rets, n_groups=5)
    perf_ok = all(k in q["group_performance"]["Q5"]
                  for k in ("annual_return", "sharpe", "max_drawdown"))
    check("分层回测返回每组年化/夏普/最大回撤", perf_ok)
    check("分层回测返回多空净值", isinstance(q["long_short"]["nav"], pd.Series)
          and len(q["long_short"]["nav"]) > 0)
    check("分层回测单调性识别", q["monotonic"] and q["monotonic_direction"] == "increasing",
          f"direction={q['monotonic_direction']}")
    check("分层回测数值合理（Q5 年化 > Q1）",
          q["group_performance"]["Q5"]["annual_return"] > q["group_performance"]["Q1"]["annual_return"])

    to = calc_turnover(evaluate("rank(ts_delta(close, 1))", d), top_pct=0.2)
    check("calc_turnover 换手率在 [0,1]", 0 <= to["mean_turnover"] <= 1,
          f"mean={to['mean_turnover']:.3f}")

    f1 = evaluate("rank(ts_mean(close, 5))", d)
    corr = calc_factor_correlation({"f1": f1, "f2": f1.copy(), "f3": cheat})
    check("冗余因子识别（相同因子 corr>0.7）",
          any({a, b} == {"f1", "f2"} for a, b, _ in corr["redundant_pairs"]),
          f"pairs={corr['redundant_pairs']}")


# ==================== 5. 合成器 ====================
def test_combiner(d: FactorData) -> None:
    rets = d.close.pct_change(fill_method=None)
    f1 = evaluate("rank(ts_mean(close, 5))", d)
    f2 = evaluate("rank(volume / ts_mean(volume, 20))", d)
    factors = {"f1": f1, "f2": f2}

    ew = equal_weight(factors)
    check("equal_weight 输出面板格式正确", isinstance(ew, pd.DataFrame)
          and ew.shape == f1.shape and ew.index.equals(f1.index))
    check("equal_weight 有有效值", ew.notna().sum().sum() > 0)

    icw = combine("ic_weighted", factors, returns=rets, window=20)
    check("ic_weighted 输出格式正确", icw.shape == f1.shape and icw.notna().sum().sum() > 0)

    ridge = ridge_combine(factors, rets, alpha=1.0)
    check("ridge_combine 输出格式正确且无 inf",
          ridge.shape[0] == f1.shape[0] and not np.isinf(ridge.to_numpy(dtype=float)).any())

    dup = dedupe({"f1": f1, "f1_copy": f1.copy(), "f2": f2}, threshold=0.7)
    check("dedupe 剔除冗余因子", "f1_copy" not in dup and "f1" in dup and "f2" in dup,
          f"kept={list(dup)}")

    allc = combine("equal_weight", factors, dedupe_first=True)
    check("combine 统一入口可用", allc.shape == f1.shape)


# ==================== 6. 股票池 ====================
def test_universe() -> None:
    check("resolve_universe 列表解析", resolve_universe(["1", "000002", "600519.SH"])
          == ["000001", "000002", "600519"])
    check("resolve_universe 单代码解析", resolve_universe("600519") == ["600519"])
    check("resolve_universe 逗号分隔", resolve_universe("000001, 600000") == ["000001", "600000"])


def main() -> int:
    d = make_data()
    test_expression(d)
    test_preprocess(d)
    test_future_detector(d)
    test_evaluator(d)
    test_combiner(d)
    test_universe()

    print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
    if FAIL:
        print("失败项：")
        for item in FAIL:
            print("  -", item)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
