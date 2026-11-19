"""策略上线前检查清单（第 5 步 · 5.7 十六项）。

用法：
    python tools/strategy_checklist.py --strategy double_ma_cross
    python tools/strategy_checklist.py --strategy my_ma --record backtest_results/my_ma.json

逐项输出「通过 / 警告 / 不通过 / 不适用」：

  可自动检查的（本工具直接判定）
    1  策略元信息完整 + 实现 on_bar
    2  tests/test_<name>.py 存在且语法正确
    3  无未来函数可疑调用（shift(-N)、requests/akshare 直接取数）+ 合成数据回测跑通
    9  最大回撤（从 --record 实验 JSON 读取，默认阈值 20%）
   10  有止损/风控逻辑（策略级参数，或账户层内置风控兜底）
   4/8  若 --record 提供样本内/外绩效与日均成交额，则一并校验

  依赖后续步骤、当前只能标「不适用」的
    5  走向前分析样本外绩效为正            → 第 6 步
    6  参数 ±10% 微扰后仍盈利              → 第 7 步
    7  成本加压（滑点×2、手续费×2）后仍盈利 → 第 7 步
    11 模拟盘连续运行 ≥ 约定时长            → 第 12 步
    12 模拟盘与回测偏差 < 5%               → 第 12 步
    13 实盘风控参数已配置                  → 第 12 步
    14 告警渠道连通测试通过                → 第 12 步
    15 日志留存与每日对账已开启            → 第 12 步
    16 「最坏情况会亏多少」已明确并接受     → 人工确认

退出码：存在「不通过」返回 1，否则返回 0。

【--record 实验 JSON 结构（尽量宽松，缺项自动跳过）】
    {
      "metrics": {"total_return": 0.18, "max_drawdown": -0.12},
      "in_sample":  {"total_return": 0.30},
      "out_sample": {"total_return": 0.16},
      "avg_amount": 25000000
    }
    metrics 也可直接平铺在顶层；max_drawdown 允许写成正数或负数。
"""
from __future__ import annotations

import argparse
import json
import logging
import py_compile
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.strategy import BaseStrategy                       # noqa: E402
from core.strategy_loader import load_class_from_file        # noqa: E402

STRATEGY_DIR = BASE_DIR / "strategies"
TEST_DIR = BASE_DIR / "tests"

# 未来函数 / 越权取数的可疑关键字（命中即不通过）
SUSPICIOUS_TOKENS = (
    ("shift(-", "shift(负数) 取未来值"),
    ("requests.", "直接发 HTTP 请求（应在数据层做）"),
    ("akshare", "直接调用 akshare（应在数据层做）"),
    ("import ak", "直接调用 akshare（应在数据层做）"),
    (".get_daily(", "策略层直接取数（应走 get_history）"),
    (".get_kline(", "策略层直接取数（应走 get_history）"),
)

META_KEYS = ("name", "display_name", "markets", "params", "description", "version")

PASS, WARN, FAIL, NA = "通过", "警告", "不通过", "不适用"
_SYMBOL = {PASS: "✅", WARN: "⚠️ ", FAIL: "❌", NA: "—"}


def _w(text: str, width: int) -> str:
    """按显示宽度左对齐（中文按 2 计）。"""
    shown = sum(2 if ord(c) > 0x2E80 else 1 for c in str(text))
    return str(text) + " " * max(1, width - shown)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


# ==================== 实验记录读取 ====================

def _metric(record, key: str):
    """在 record 的常见层级里找指标；找不到返回 None。"""
    if not isinstance(record, dict):
        return None
    layers = [record, record.get("metrics") or {}, record.get("out_sample") or {},
              record.get("in_sample") or {}]
    for layer in layers:
        if isinstance(layer, dict) and layer.get(key) is not None:
            return layer.get(key)
    return None


def _load_record(path) -> tuple:
    if not path:
        return {}, "未提供 --record"
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {}, f"读取失败：{type(exc).__name__}: {exc}"
    if not isinstance(data, dict):
        return {}, "JSON 顶层不是对象"
    return data, ""


# ==================== 各项检查 ====================

def check_meta(cls) -> tuple:
    meta = dict(getattr(cls, "meta", {}) or {})
    missing = [k for k in META_KEYS if not meta.get(k)]
    if getattr(cls, "on_bar", None) is BaseStrategy.on_bar:
        missing.append("on_bar()")
    if missing:
        return FAIL, "缺少：" + ", ".join(missing)
    return PASS, (f"name={meta.get('name')} markets={len(meta.get('markets') or [])} "
                  f"params={len(meta.get('params') or {})} v{meta.get('version')}")


def check_signal_test(name: str) -> tuple:
    path = TEST_DIR / f"test_{name}.py"
    if not path.exists():
        return WARN, f"未找到 {path.relative_to(BASE_DIR)}（可用 tools/new_strategy.py 生成）"
    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as exc:
        return FAIL, f"语法错误：{exc.msg if hasattr(exc, 'msg') else exc}"
    return PASS, str(path.relative_to(BASE_DIR))


def check_no_lookahead(source: str) -> tuple:
    hits = [f"{token}（{why}）" for token, why in SUSPICIOUS_TOKENS if token in source]
    if hits:
        return FAIL, "命中可疑调用：" + "；".join(hits)
    return PASS, "未发现 shift(-N)/requests/akshare/直接取数"


def run_synthetic_backtest(cls) -> tuple:
    """用合成 260 根日线跑一遍回测：只验证「能跑通、有成交」，不评价收益。"""
    try:
        from strategies._selftest import run_selftest

        logging.disable(logging.INFO)          # 屏蔽 runner 的逐笔成交日志，保持清单干净
        try:
            result = run_selftest(cls, verbose=False)
        finally:
            logging.disable(logging.NOTSET)
    except Exception as exc:  # noqa: BLE001
        return FAIL, f"{type(exc).__name__}: {exc}"
    filled = [o for o in result.get("trades", []) if o.get("status") == "filled"]
    metrics = result.get("metrics") or {}
    if not filled:
        return WARN, "回测跑通但 0 笔成交（检查信号条件/数据长度）"
    return PASS, (f"{len(filled)} 笔成交；总收益 {metrics.get('total_return', 0.0):+.2%} "
                  f"回撤 {metrics.get('max_drawdown', 0.0):.2%}")


def check_sample_split(record: dict) -> tuple:
    ins = record.get("in_sample") if isinstance(record.get("in_sample"), dict) else {}
    out = record.get("out_sample") if isinstance(record.get("out_sample"), dict) else {}
    in_ret = ins.get("total_return")
    out_ret = out.get("total_return")
    if in_ret is None or out_ret is None:
        return NA, "需第 6 步走向前分析的样本内/外绩效"
    decay = (float(in_ret) - float(out_ret)) / abs(float(in_ret)) if float(in_ret) else 1.0
    ok = float(out_ret) > 0 and decay < 0.5
    detail = f"样本内 {float(in_ret):+.2%} → 样本外 {float(out_ret):+.2%}，衰减 {decay:.0%}"
    return (PASS if ok else FAIL), detail


def check_avg_amount(record: dict, threshold: float) -> tuple:
    value = _metric(record, "avg_amount")
    if value is None:
        return NA, "需真实行情统计日均成交额（第 4/9 步）"
    ok = float(value) >= float(threshold)
    return (PASS if ok else FAIL), f"日均成交额 {float(value):,.0f}（阈值 {threshold:,.0f}）"


def check_drawdown(record: dict, threshold: float) -> tuple:
    value = _metric(record, "max_drawdown")
    if value is None:
        return NA, "未提供 --record 实验记录（回测指标）"
    dd = abs(float(value))
    ok = dd <= float(threshold)
    return (PASS if ok else FAIL), f"最大回撤 {dd:.2%}（阈值 {float(threshold):.0%}）"


def check_risk(cls, source: str) -> tuple:
    params = dict(getattr(cls, "meta", {}).get("params") or {})
    explicit = [k for k in ("stop_loss", "take_profit", "blacklist") if params.get(k)]
    if explicit:
        return PASS, "策略级风控参数：" + ", ".join(explicit)
    if "stop_loss" in source or "take_profit" in source:
        return PASS, "策略代码中显式引用了止损/止盈"
    return WARN, "仅依赖账户层内置风控（单标的上限/杠杆），建议显式配置 stop_loss"


# ==================== 主流程 ====================

def _resolve_path(name: str) -> Path:
    return STRATEGY_DIR / f"{name}.py"


def build_rows(name: str, record: dict,
               drawdown_threshold: float, min_amount: float) -> list:
    path = _resolve_path(name)
    source = _read(path)
    cls = load_class_from_file(path)

    rows = []

    def add(no, item, result):
        status, detail = result
        rows.append((no, item, status, detail))

    add(1, "策略元信息完整（name/markets/params/description/version）", check_meta(cls))
    add(2, "信号单元测试存在且语法正确", check_signal_test(name))
    lookahead = check_no_lookahead(source)
    backtest = run_synthetic_backtest(cls)
    if lookahead[0] == FAIL:
        add(3, "回测无未来函数告警", lookahead)
    elif backtest[0] == FAIL:
        add(3, "回测无未来函数告警", (FAIL, "合成数据回测失败：" + backtest[1]))
    else:
        detail = lookahead[1]
        if backtest[0] == WARN:
            detail += "；" + backtest[1]
        add(3, "回测无未来函数告警", (backtest[0] if backtest[0] == WARN else PASS, detail))
    add(4, "样本外绩效为正且较样本内衰减 < 50%", check_sample_split(record))
    add(5, "走向前分析样本外绩效为正", (NA, "第 6 步 research/walkforward.py"))
    add(6, "参数稳健：±10% 微扰后仍盈利", (NA, "第 7 步 research/validator.py"))
    add(7, "成本加压：滑点×2、手续费×2 后仍盈利", (NA, "第 7 步 research/validator.py"))
    add(8, "交易标的日均成交额 > 阈值", check_avg_amount(record, min_amount))
    add(9, "最大回撤 < 可承受阈值", check_drawdown(record, drawdown_threshold))
    add(10, "有止损 / 风控逻辑", check_risk(cls, source))
    add(11, "模拟盘连续运行 ≥ 约定时长", (NA, "第 12 步"))
    add(12, "模拟盘与回测偏差 < 5%", (NA, "第 12 步"))
    add(13, "实盘风控参数已配置", (NA, "第 12 步"))
    add(14, "告警渠道连通测试通过", (NA, "第 12 步"))
    add(15, "日志留存与每日对账已开启", (NA, "第 12 步"))
    add(16, "「最坏情况会亏多少」已明确并接受", (NA, "人工确认"))
    return rows


def print_rows(name: str, rows: list, record_err: str) -> None:
    print(f"\n=== 策略上线检查清单：{name} ===")
    if record_err:
        print(f"（实验记录：{record_err}）")
    print(_w("序号", 6) + _w("状态", 10) + _w("检查项", 46) + "说明")
    print("-" * 100)
    for no, item, status, detail in rows:
        print(_w(f"{no:02d}", 6) + _w(f"{_SYMBOL[status]}{status}", 10)
              + _w(item, 46) + str(detail))
    counts = {s: sum(1 for r in rows if r[2] == s) for s in (PASS, WARN, FAIL, NA)}
    print("-" * 100)
    print(f"汇总：通过 {counts[PASS]} · 警告 {counts[WARN]} · "
          f"不通过 {counts[FAIL]} · 不适用 {counts[NA]}（共 {len(rows)} 项）")
    if counts[FAIL]:
        print("结论：存在「不通过」项，禁止进入小资金实盘。")
    elif counts[WARN]:
        print("结论：无硬性失败项，但请先处理警告项。")
    else:
        print("结论：自动检查项全部通过；第 5/6/7/11–16 项仍需按后续步骤补齐。")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="策略上线前检查清单（16 项）")
    parser.add_argument("--strategy", required=True, help="策略名（strategies/<name>.py）")
    parser.add_argument("--record", default=None, help="可选的实验记录 JSON（回测指标）")
    parser.add_argument("--drawdown-threshold", type=float, default=0.2,
                        help="最大回撤阈值（默认 0.2 = 20%）")
    parser.add_argument("--min-amount", type=float, default=1e7,
                        help="日均成交额阈值（默认 1000 万）")
    args = parser.parse_args(argv)

    path = _resolve_path(args.strategy)
    if not path.exists():
        print(f"[错误] 找不到策略文件：{path}")
        print("可用策略：", ", ".join(sorted(p.stem for p in STRATEGY_DIR.glob("*.py")
                                             if not p.name.startswith("_"))))
        return 2

    record, record_err = _load_record(args.record)
    if record_err and args.record:
        print(f"[警告] --record {record_err}，相关检查将标记为不适用")

    try:
        rows = build_rows(args.strategy, record,
                          args.drawdown_threshold, args.min_amount)
    except Exception as exc:  # noqa: BLE001
        print(f"[错误] 检查过程异常：{type(exc).__name__}: {exc}")
        return 2

    print_rows(args.strategy, rows, record_err)
    return 1 if any(r[2] == FAIL for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
