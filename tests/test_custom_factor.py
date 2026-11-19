"""自定义因子全链路测试（离线）。

验证自定义因子与内置 Alpha 完全平等：
  * @register_factor 能被 get_factor / list_factors 发现；
  * 能算出非空「日期×股票」面板；
  * 能通过未来函数检测器（扰动检验 + lead 检查）；
  * 能进评估套件得到 IC 报告；
  * 能进预处理与合成流程。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import factor.custom  # noqa: F401  导入即注册示例自定义因子
from factor import FactorData, get_factor, list_factors
from factor.combiner import equal_weight
from factor.evaluator import calc_ic, quantile_backtest
from factor.future_detector import check_lead, check_rolling_window
from factor.preprocess import process_factor

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" | {detail}" if detail else ""))


def make_data(n: int = 120, m: int = 30, seed: int = 66) -> FactorData:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-03", periods=n, freq="B")
    cols = [f"{i:06d}" for i in range(m)]
    ret = rng.normal(0, 0.02, (n, m))
    close = pd.DataFrame(100 * np.cumprod(1 + ret, axis=0), index=idx, columns=cols)
    open_ = close * (1 + rng.normal(0, 0.004, (n, m)))
    high = np.maximum(close, open_) * 1.01
    low = np.minimum(close, open_) * 0.99
    volume = pd.DataFrame(rng.lognormal(11, 0.4, (n, m)), index=idx, columns=cols)
    amount = volume * (high + low + close) / 3
    return FactorData(close=close, open=open_, high=high, low=low,
                      volume=volume, amount=amount)


def main() -> int:
    d = make_data()
    returns = d.close.pct_change(fill_method=None)

    names = list_factors()
    expected = {"my_momentum", "my_volume_price_div", "my_turnover_reversal", "my_intraday_strength"}
    check("自定义因子已注册", expected.issubset(set(names)), f"registered={expected & set(names)}")

    fn = get_factor("my_momentum")
    check("get_factor 能发现自定义因子", callable(fn) and fn.__name__ == "my_momentum")

    values = fn(d)
    check("自定义因子输出非空面板", isinstance(values, pd.DataFrame)
          and values.shape == d.close.shape and values.notna().sum().sum() > 0,
          f"valid={int(values.notna().sum().sum())}")
    check("自定义因子无 inf", not np.isinf(values.to_numpy(dtype=float)).any())

    dup = False
    try:
        from factor import register_factor

        @register_factor("my_momentum")
        def _dup(data):  # pragma: no cover - 必须抛错
            return data.close
    except ValueError:
        dup = True
    check("重复注册同名因子会抛错", dup)

    missing = False
    try:
        get_factor("not_exist_factor_xyz")
    except KeyError:
        missing = True
    check("get_factor 未知因子抛 KeyError", missing)

    rep = check_rolling_window(fn, d)
    check("自定义因子通过未来函数扰动检测", not rep["has_future_leak"], rep["detail"])
    lead = check_lead(values, returns)
    check("自定义因子 lead 检测可运行", "suspicious" in lead and "report" in lead, lead["report"])

    ic = calc_ic(values, returns)
    check("自定义因子能进 evaluator 出 IC 报告",
          "ic_mean" in ic and "icir" in ic and len(ic["ic_series"]) > 0,
          f"IC={ic['ic_mean']:.4f} ICIR={ic['icir']:.3f}")

    q = quantile_backtest(values, returns, n_groups=5)
    check("自定义因子能进分层回测", "long_short" in q and "group_performance" in q,
          f"direction={q['monotonic_direction']}")

    proc = process_factor(values)
    check("自定义因子能进预处理", proc.shape == values.shape
          and abs(proc.mean(axis=1)).max() < 1e-8)

    combo = equal_weight({"my_momentum": values, "my_div": get_factor("my_volume_price_div")(d)})
    check("自定义因子能进合成器", combo.shape == values.shape and combo.notna().sum().sum() > 0)

    print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
    if FAIL:
        print("失败项：")
        for item in FAIL:
            print("  -", item)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
