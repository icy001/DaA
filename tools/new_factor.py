"""自定义因子脚手架（第 5 步 5.9.16）。

用法::

    python tools/new_factor.py --name my_alpha --desc "量价背离因子"

自动完成：
  1. 在 factor/custom.py 末尾追加 @register_factor 函数骨架（含接口注释/TODO）；
  2. 生成 tests/test_my_alpha.py 测试骨架；
  3. 打印如何注册、计算、评估的提示。
重名（factor/custom.py 已有同名函数或注册名）时直接报错退出。
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CUSTOM = ROOT / "factor" / "custom.py"
TESTS = ROOT / "tests"


def _valid_name(name: str) -> bool:
    return re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is not None


def _exists(name: str, text: str) -> bool:
    return bool(
        re.search(rf"def\s+{re.escape(name)}\s*\(", text)
        or re.search(rf"register_factor\(\s*['\"]{re.escape(name)}['\"]", text)
    )


CUSTOM_TEMPLATE = '''

# ==================== 自动生成: {name} ====================
@register_factor("{name}")
def {name}(data: FactorData) -> pd.DataFrame:
    """{desc}

    TODO: 在此实现因子逻辑，返回「日期×股票」面板 DataFrame。
    可以：
      * 用 FactorData 字段：data.close / data.volume / data.vwap / data.returns ...
      * 用表达式引擎：evaluate("rank(ts_delta(close, 5))", data)
    禁止：负向 shift、逐股票 for 循环、在因子内做去极值/标准化。
    """
    # TODO: 替换为真实因子逻辑
    return evaluate("rank(ts_delta(close, 5))", data)
'''

TEST_TEMPLATE = '''"""{name} 自定义因子测试骨架（{desc}）。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import factor.custom  # noqa: F401  确保自定义因子已注册
from factor import FactorData, get_factor
from factor.evaluator import calc_ic
from factor.future_detector import check_lead, check_rolling_window

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{{'PASS' if ok else 'FAIL'}} {{name}}" + (f" | {{detail}}" if detail else ""))


def make_data(n: int = 120, m: int = 30):
    rng = np.random.default_rng(7)
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    cols = [f"{{i:06d}}" for i in range(m)]
    close = pd.DataFrame(100 * np.cumprod(1 + rng.normal(0, 0.02, (n, m)), axis=0),
                         index=idx, columns=cols)
    ret = close.pct_change(fill_method=None).fillna(0.0)
    volume = pd.DataFrame(rng.lognormal(10, 0.5, (n, m)), index=idx, columns=cols)
    return FactorData(close=close, open=close * (1 + rng.normal(0, 0.005, (n, m))),
                      high=close * 1.01, low=close * 0.99, volume=volume), ret


def main() -> int:
    data, returns = make_data()
    fn = get_factor("{name}")
    values = fn(data)
    check("因子能算出面板", isinstance(values, pd.DataFrame) and values.notna().sum().sum() > 0)
    check("面板维度正确", values.shape == data.close.shape)

    perturb = check_rolling_window(fn, data)
    check("未来函数扰动检测通过", not perturb["has_future_leak"], perturb["detail"])
    lead = check_lead(values, returns)
    check("lead 检测可运行", "suspicious" in lead, lead["report"])

    ic = calc_ic(values, returns)
    check("IC 报告格式正确", "ic_mean" in ic and "icir" in ic and "ic_series" in ic,
          f"IC={{ic['ic_mean']:.4f}}")
    # TODO: 根据 IC/ICIR 判断因子是否达标（ICIR>0.3 可进入合成）
    print(f"\\n通过 {{len(PASS)}} / 失败 {{len(FAIL)}}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


def main() -> int:
    parser = argparse.ArgumentParser(description="生成自定义因子骨架")
    parser.add_argument("--name", required=True, help="因子函数名/注册名，如 my_alpha")
    parser.add_argument("--desc", default="自定义因子", help="因子中文说明")
    args = parser.parse_args()

    name = args.name.strip()
    if not _valid_name(name):
        print(f"错误：因子名 {name!r} 不是合法 Python 标识符")
        return 1
    if not CUSTOM.exists():
        print(f"错误：找不到 {CUSTOM}")
        return 1

    text = CUSTOM.read_text(encoding="utf-8")
    if _exists(name, text):
        print(f"错误：factor/custom.py 中已存在因子 {name}，请换一个名字")
        return 1

    CUSTOM.write_text(text.rstrip() + CUSTOM_TEMPLATE.format(name=name, desc=args.desc),
                      encoding="utf-8")
    print(f"[1/3] 已追加因子骨架到 {CUSTOM.relative_to(ROOT)}")

    TESTS.mkdir(parents=True, exist_ok=True)
    test_file = TESTS / f"test_{name}.py"
    if test_file.exists():
        print(f"[2/3] 测试文件已存在，跳过生成: {test_file.relative_to(ROOT)}")
    else:
        test_file.write_text(TEST_TEMPLATE.format(name=name, desc=args.desc), encoding="utf-8")
        print(f"[2/3] 已生成测试骨架: {test_file.relative_to(ROOT)}")

    print("[3/3] 下一步：")
    print(f"  1) 编辑 factor/custom.py 实现 {name}() 的 TODO；")
    print(f"  2) 运行 python tests/test_{name}.py 做未来函数与 IC 初筛；")
    print(f"  3) 计算: python main.py factor calc --factors {name} --universe hs300")
    print(f"  4) 评估: python main.py factor eval --factor {name} --universe hs300")
    print("  5) 达标后再进入 combine 合成与样本外回测（ICIR>0.3 可合成）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
