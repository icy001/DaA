"""Alpha101 全量测试（离线、纯合成面板）。

覆盖：
  1) 101 个 alpha 全部可计算、无异常、无 inf；
  2) 至少 90% 的 alpha 在最后一期有 >50% 非 NaN 截面值；
  3) 用刻意构造的动量环境验证「今日因子值 vs 次日收益」显著正相关，
     且因子通过未来扰动检测（说明预测力来自真实信号而非未来函数）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from factor import FactorData
from factor.alpha101 import get_alpha_list, get_builtin_alpha
from factor.expression import evaluate
from factor.future_detector import check_rolling_window

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" | {detail}" if detail else ""))


def make_panel(n: int = 320, m: int = 40, seed: int = 101) -> FactorData:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2021-01-04", periods=n, freq="B")
    cols = [f"{i:06d}" for i in range(m)]
    ret = rng.normal(0, 0.02, (n, m))
    close = pd.DataFrame(100 * np.cumprod(1 + ret, axis=0), index=idx, columns=cols)
    open_ = close * (1 + rng.normal(0, 0.004, (n, m)))
    high = np.maximum(close, open_) * (1 + rng.uniform(0, 0.012, (n, m)))
    low = np.minimum(close, open_) * (1 - rng.uniform(0, 0.012, (n, m)))
    volume = pd.DataFrame(rng.lognormal(11, 0.5, (n, m)), index=idx, columns=cols)
    amount = volume * (high + low + close) / 3
    return FactorData(close=close, open=open_, high=high, low=low,
                      volume=volume, amount=amount)


def avg_row_corr(a: pd.DataFrame, b: pd.DataFrame) -> float:
    idx = a.index.intersection(b.index)
    cols = a.columns.intersection(b.columns)
    vals = []
    for dt in idx:
        x, y = a.loc[dt, cols], b.loc[dt, cols]
        valid = x.notna() & y.notna()
        if valid.sum() >= 5:
            c = x[valid].corr(y[valid], method="spearman")
            if np.isfinite(c):
                vals.append(float(c))
    return float(np.mean(vals)) if vals else np.nan


def test_all_alphas() -> None:
    funcs = get_alpha_list()
    check("get_alpha_list 返回 101 个函数", len(funcs) == 101, f"n={len(funcs)}")
    check("alpha 函数名不重复", len({f.__name__ for f in funcs}) == 101)

    d = make_panel()
    errors, infs = [], []
    last_ratio = []
    for i, fn in enumerate(funcs, 1):
        try:
            x = fn(d)
            arr = x.to_numpy(dtype=float)
            if np.isinf(arr).any():
                infs.append((i, int(np.isinf(arr).sum())))
            last_ratio.append((i, float(x.iloc[-1].notna().mean())))
        except Exception as exc:  # noqa: BLE001
            errors.append((i, type(exc).__name__, str(exc)[:120]))

    check("101 个 alpha 全部无异常", not errors, str(errors[:5]))
    check("101 个 alpha 全部无 inf", not infs, str(infs[:5]))
    good = sum(1 for _, v in last_ratio if v > 0.5)
    check("至少 90% 的 alpha 最后一期非 NaN>50%", good >= 91,
          f"{good}/101 达标，最低: {sorted(last_ratio, key=lambda x: x[1])[:5]}")

    check("get_builtin_alpha(1) 取到 alpha001", get_builtin_alpha(1).__name__ == "alpha001")
    raised = False
    try:
        get_builtin_alpha(102)
    except ValueError:
        raised = True
    check("get_builtin_alpha 越界报错", raised)


def test_momentum_predicts_future() -> None:
    """构造 r_t = 0.5*mean(r_{t-6..t-2}) + noise，使 5 日动量预测次日收益。"""
    n, m = 240, 60
    rng = np.random.default_rng(777)
    idx = pd.date_range("2020-01-02", periods=n, freq="B")
    cols = [f"{i:06d}" for i in range(m)]
    eps = rng.normal(0, 0.02, (n, m))
    ret = eps.copy()
    for t in range(7, n):
        ret[t] = 0.5 * ret[t - 6:t - 1].mean(axis=0) + 0.5 * eps[t]
    close = pd.DataFrame(100 * np.cumprod(1 + ret, axis=0), index=idx, columns=cols)
    volume = pd.DataFrame(rng.lognormal(11, 0.3, (n, m)), index=idx, columns=cols)
    d = FactorData(close=close, volume=volume)
    returns = d.close.pct_change(fill_method=None)

    mom = evaluate("ts_mean(returns, 5)", d)
    corr_future = avg_row_corr(mom, returns.shift(-1))
    corr_today = avg_row_corr(mom, returns)
    check("动量因子与次日收益显著正相关", np.isfinite(corr_future) and corr_future > 0.1,
          f"future={corr_future:.3f}")
    check("今日因子 vs 次日收益 高于 vs 今日收益",
          corr_future > corr_today + 0.02,
          f"future={corr_future:.3f} today={corr_today:.3f}")
    # 动量窗口含昨日收益，与昨日收益的相关性天然更高（重叠窗口），
    # 因此「未来 > 过去」不是有效断言；改用未来扰动检测确认未使用未来数据。
    rep = check_rolling_window(lambda data: evaluate("ts_mean(returns, 5)", data), d)
    check("动量因子通过未来扰动检测（未使用未来数据）",
          not rep["has_future_leak"], rep["detail"])


def main() -> int:
    test_all_alphas()
    test_momentum_predicts_future()

    print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
    if FAIL:
        print("失败项：")
        for item in FAIL:
            print("  -", item)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
