"""第 5 步：策略自动发现 / 注册 / 加载测试（不依赖网络）。

覆盖：
  1) discover() 能扫到全部示例策略（至少 9 个），且以下划线开头的 _selftest.py 被跳过；
  2) get(name) 按名字取到正确的策略类，meta 一致；
  3) 坏文件隔离：语法错误文件 + 缺 on_bar 的类都不让注册表崩溃，进入 unavailable()；
  4) list_all() 每项都含 name/display_name/version/description/markets。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.strategy import BaseStrategy
from core.strategy_loader import StrategyRegistry, discover, get

PASS, FAIL = [], []

# 9 个示例策略（与 strategies/ 下的文件名一致）
EXPECTED = [
    "double_ma_cross", "cb_arbitrage", "futures_trend_following",
    "us_swing_trading", "option_sell_strangle", "crypto_grid",
    "fund_sip", "repo_cash_management", "hk_ah_arbitrage",
]


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'✅' if ok else '❌'} {name}" + (f" | {detail}" if detail else ""))


# ==================== 1) 发现 ====================

def test_discover() -> None:
    reg = discover(force=True)
    rows = reg.list_all()
    names = [row["name"] for row in rows]
    check("discover 至少扫到 9 个策略", len(rows) >= 9, f"实际 {len(rows)} 个")
    missing = [n for n in EXPECTED if n not in names]
    check("9 个示例策略全部注册", not missing, f"缺少 {missing}" if missing else "全部命中")
    check("下划线文件被跳过", not any(n.startswith("_") for n in names),
          f"names={names}")
    check("可用策略无不可用项", not reg.unavailable(), str(reg.unavailable())[:200])


# ==================== 2) 按名字取 ====================

def test_get() -> None:
    for name in EXPECTED:
        try:
            cls = get(name)
        except Exception as exc:  # noqa: BLE001
            check(f"get({name})", False, f"{type(exc).__name__}: {exc}")
            continue
        meta = dict(getattr(cls, "meta", {}) or {})
        ok = (meta.get("name") == name
              and issubclass(cls, BaseStrategy)
              and cls.on_bar is not BaseStrategy.on_bar
              and bool(meta.get("markets"))
              and bool(meta.get("version")))
        check(f"get({name}) 返回正确的策略类", ok,
              f"class={cls.__name__} markets={meta.get('markets')}")

    try:
        get("no_such_strategy")
        check("get(未知名字) 抛 KeyError", False, "未抛错")
    except KeyError:
        check("get(未知名字) 抛 KeyError", True)
    except Exception as exc:  # noqa: BLE001
        check("get(未知名字) 抛 KeyError", False, f"抛了 {type(exc).__name__}")


# ==================== 3) 坏文件隔离 ====================

BROKEN_SYNTAX = "def oops(:\n    pass\n"

NO_ON_BAR = '''from core.strategy import BaseStrategy


class NoOnBar(BaseStrategy):
    """缺少 on_bar 实现，应被 loader 列入不可用清单。"""

    meta = {"name": "no_on_bar_strategy", "periods": ["1d"]}
'''


def test_bad_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        (tmp_dir / "broken_syntax.py").write_text(BROKEN_SYNTAX, encoding="utf-8")
        (tmp_dir / "no_on_bar.py").write_text(NO_ON_BAR, encoding="utf-8")
        # 正常文件混入，验证坏文件不会影响好文件
        (tmp_dir / "good.py").write_text(
            "from core.strategy import BaseStrategy\n\n\n"
            "class Good(BaseStrategy):\n"
            "    meta = {'name': 'good_one', 'periods': ['1d']}\n\n"
            "    def on_bar(self, date, bars):\n"
            "        return None\n", encoding="utf-8")

        try:
            reg = StrategyRegistry(directory=tmp_dir).discover()
        except Exception as exc:  # noqa: BLE001
            check("坏文件不导致注册表崩溃", False, f"{type(exc).__name__}: {exc}")
            return

        check("坏文件不导致注册表崩溃", True)
        unavailable = reg.unavailable()
        check("unavailable() 记录两条原因", len(unavailable) == 2,
              f"实际 {len(unavailable)} 条：{unavailable}")
        reasons = " | ".join(str(row.get("reason", "")) for row in unavailable)
        check("语法错误文件被隔离", "SyntaxError" in reasons or "Syntax" in reasons, reasons[:160])
        check("缺 on_bar 被识别", "on_bar" in reasons, reasons[:160])
        check("好文件仍能加载", [r["name"] for r in reg.list_all()] == ["good_one"],
              str(reg.list_all()))


# ==================== 4) list_all 字段 ====================

def test_list_all_fields() -> None:
    rows = discover(force=True).list_all()
    required = ("name", "display_name", "version", "description", "markets")
    bad = []
    for row in rows:
        for key in required:
            value = row.get(key)
            if key == "markets":
                if not isinstance(value, list):
                    bad.append(f"{row.get('name')}.markets 不是 list")
            elif not value:
                bad.append(f"{row.get('name')}.{key} 为空")
    check("list_all 每项字段完整", not bad, "; ".join(bad[:5]))


def main() -> int:
    test_discover()
    test_get()
    test_bad_files()
    test_list_all_fields()
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
