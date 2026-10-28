"""第 0 步环境自检脚本

依次验证：依赖导入 → 目录可写 → config 加载 → 市场代码自动识别。
全部通过返回 0，存在失败项返回 1。
"""
from __future__ import annotations

import importlib
import sys
import traceback

ROOT = __import__("pathlib").Path(__file__).resolve().parent

# 需要存在且可写的目录（与第 0 步骨架一致）
REQUIRED_DIRS = [
    "data_cache", "data_cache/factors", "data_cache/snapshots", "data_cache/raw",
    "data_cache/adj_factors", "data_cache/index_members", "data_cache/constituents",
    "logs", "backtest_results", "reports", "paper_trading", "live_trading",
    "audit_logs", "strategies", "configs/strategies", "research", "tools", "tests",
    "core", "factor", "broker", "risk", "live", "nav_backtest",
    "derivatives_pricing", "research_output",
]

# 市场识别用例：(代码, 期望结果, 说明)
MARKET_CASES = [
    ("600519", "cn_stock", "A股个股"),
    ("510300", "cn_etf", "A股场内ETF"),
    ("123045", "cn_convertible", "沪深可转债"),
    ("00700", "hk_stock", "港股个股"),
    ("AAPL", "us_stock", "美股个股"),
    ("204001", "cn_reverse_repo", "国债逆回购"),
    ("rb2501", "cn_future", "国内期货"),
    ("GC", "global_future", "国际期货"),
    ("BTC", "crypto", "加密货币"),
    ("EURUSD", "forex", "外汇"),
    ("161725", "cn_fund", "场外公募基金"),
    ("508000", "cn_reits", "公募REITs"),
    ("430047", "neeq", "新三板"),
    ("SPY", "us_etf", "美股ETF"),
    ("10004567", "cn_option", "场内期权（8位）"),
    # ---- 深市个股号段回归（曾误判为 cn_fund）----
    ("000001", "cn_stock", "深市主板 平安银行"),
    ("000002", "cn_stock", "深市主板 万科A"),
    ("000858", "cn_stock", "深市主板 五粮液"),
    ("002415", "cn_stock", "原中小板 海康威视"),
    ("002594", "cn_stock", "原中小板 比亚迪"),
    ("003816", "cn_stock", "深市主板 中国广核"),
    ("300750", "cn_stock", "创业板 宁德时代"),
    # ---- 基金/ETF 号段回归 ----
    ("005827", "cn_fund", "场外基金 004~009 号段"),
    ("519066", "cn_fund", "沪市场内基金段 519"),
    ("512880", "cn_etf", "沪市 ETF"),
    ("588000", "cn_etf", "科创 ETF"),
    ("159915", "cn_etf", "深市 ETF"),
    # ---- 显式传参覆盖（第 4 项为 market_type 覆盖值）----
    ("000001", "cn_fund", "显式传参消解歧义", "cn_fund"),
]

RESULTS = []  # [(是否通过, 描述, 详情)]


def check(ok: bool, title: str, detail: str = "") -> None:
    RESULTS.append((ok, title, detail))
    print(f"  {'✓' if ok else '✗'} {title}" + (f"  {detail}" if detail else ""))


def check_imports() -> None:
    print("\n[1/4] 核心依赖导入")
    versions = {}
    for name in ("pandas", "numpy", "akshare"):
        try:
            module = importlib.import_module(name)
            versions[name] = getattr(module, "__version__", "unknown")
            check(True, f"import {name}", f"版本 {versions[name]}")
        except Exception as exc:  # noqa: BLE001
            check(False, f"import {name}", f"{type(exc).__name__}: {exc}")
    if versions:
        print("      核心版本：" + "  ".join(f"{k}={v}" for k, v in versions.items()))


def check_dirs() -> None:
    print("\n[2/4] 目录存在性与可写性")
    for rel in REQUIRED_DIRS:
        path = ROOT / rel
        if not path.is_dir():
            check(False, rel, "目录不存在")
            continue
        probe = path / ".write_test"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            check(True, rel, "存在且可写")
        except Exception as exc:  # noqa: BLE001
            check(False, rel, f"不可写: {exc}")


def check_config() -> None:
    print("\n[3/4] config.py 加载与市场类型")
    try:
        import config
    except Exception:  # noqa: BLE001
        check(False, "import config", traceback.format_exc(limit=2))
        return
    check(True, "import config", f"RUN_MODE={config.RUN_MODE}")

    try:
        from core.utils import MARKET_NAMES
        print(f"      支持的市场类型（共 {len(MARKET_NAMES)} 类）：")
        for key, name in MARKET_NAMES.items():
            print(f"        - {key:<16} {name}")
    except Exception as exc:  # noqa: BLE001
        check(False, "core.utils.MARKET_NAMES", str(exc))


def check_detect_market() -> None:
    print("\n[4/4] detect_market_type() 自动识别")
    try:
        import config
    except Exception:  # noqa: BLE001
        check(False, "detect_market_type", "config 未加载")
        return

    for case in MARKET_CASES:
        code, expected, note = case[:3]
        override = case[3] if len(case) > 3 else None
        title = f"{code} → {expected}" + (f"（market_type={override}）" if override else "")
        try:
            actual = config.detect_market_type(code, market_type=override)
        except Exception as exc:  # noqa: BLE001
            check(False, title, f"异常: {exc}")
            continue
        check(actual == expected, title, f"[{note}] 实际: {actual}")


def main() -> int:
    print("=" * 62)
    print("  第 0 步环境自检  Environment Self-Check")
    print("=" * 62)
    check_imports()
    check_dirs()
    check_config()
    check_detect_market()

    passed = sum(1 for ok, _, _ in RESULTS if ok)
    failed = len(RESULTS) - passed
    print("\n" + "=" * 62)
    print(f"  结果：通过 {passed} 项，失败 {failed} 项")
    if failed:
        print("  失败明细：")
        for ok, title, detail in RESULTS:
            if not ok:
                print(f"    ✗ {title}  {detail}")
        print("  请先修复失败项，再进入第 1 步。")
    else:
        print("  全部通过，可以进入下一步。")
    print("=" * 62)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
