# -*- coding: utf-8 -*-
"""套件覆盖与非确定脚本的验收闸门（v3.47 / 13.0.18）。

两条教训：
1. 上一轮报「20 套全过」，这一轮只报 9 套也能算通过——计数覆盖面静默缩减，
   等于验收缩水而不留痕。冻结总数与逐套清单只能来自 ``config.SUITE_COVERAGE_GUARD``。
2. ``test_data.py`` 的项数取决于外网源可达性，是**变量**；变量不能叫「冻结口径」，
   也不能单独支撑结论。必须同时报「实测原始数」与「确定性上界」，并附确定性锚点。
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import config


def _conf() -> dict:
    from core.gov_compat import gov
    return gov("SUITE_COVERAGE_GUARD")


def _nd_conf() -> dict:
    from core.gov_compat import gov
    return gov("NONDETERMINISTIC_SCRIPT_GUARD")


def frozen_suites() -> List[str]:
    """冻结的逐套清单：根目录 9 套 + tests 11 套 = 20 套（去重保序）。"""
    conf = _conf()
    items = list(conf.get("root_suites") or []) + list(conf.get("tests_suites") or [])
    return list(dict.fromkeys(str(x) for x in items))


def validate_coverage(reported: Sequence[str], justification: str = "") -> Dict[str, object]:
    """报数覆盖面校验：少了任何一套，必须有书面理由，否则不合格。"""
    conf = _conf()
    frozen = frozen_suites()
    got = {str(x) for x in (reported or [])}
    missing = [s for s in frozen if s not in got]
    frozen_total = int(conf.get("frozen_total") or 0)
    problems: List[str] = []
    if frozen_total and len(frozen) != frozen_total:
        problems.append(
            f"清单自身漂移：root+tests 实际 {len(frozen)} 套，frozen_total={frozen_total}")
    if missing:
        if conf.get("shrink_requires_reason", True) and str(justification or "").strip():
            pass    # 有理由的缩减允许发生，但必须在回执里写明
        else:
            problems.append(
                f"报数套件 {len(got)} 个 < 冻结 {len(frozen)} 个，且无缩减理由："
                f"缺少 {missing}（on_unjustified_shrink="
                f"{conf.get('on_unjustified_shrink', 'fail')}）")
    return {
        "ok": not problems,
        "frozen_total": len(frozen),
        "reported_total": len(got),
        "missing": missing,
        "justified": bool(missing and str(justification or "").strip()),
        "problems": problems,
        "reason": "覆盖面完整" if not problems else "；".join(problems),
    }


def validate_nondeterministic(suite: str, raw_count: int,
                             deterministic_bound: Optional[int],
                             anchors: Sequence[str]) -> Dict[str, object]:
    """非确定脚本的报数校验：实测原始数 + 确定性上界 + 确定性锚点，三者缺一不可。"""
    conf = _nd_conf()
    watched = [str(x) for x in (conf.get("nondeterministic_suites") or [])]
    if suite not in watched:
        return {"ok": True, "watched": False, "reason": f"{suite} 不在非确定清单内"}
    problems: List[str] = []
    if raw_count is None or int(raw_count) < 0:
        problems.append(f"{suite}: 未上报实测原始数")
    if conf.get("must_report_raw_and_bound", True):
        if deterministic_bound is None:
            problems.append(
                f"{suite}: 缺确定性上界（实测原始数是变量，不能当作冻结口径）")
        elif int(raw_count) > int(deterministic_bound):
            problems.append(
                f"{suite}: 实测 {raw_count} 超过确定性上界 {deterministic_bound}"
                "（上界不是上限，是必须解释的异常）")
    if conf.get("cannot_support_conclusion_alone", True) and not list(anchors or []):
        problems.append(
            f"{suite}: 无非确定脚本之外是确定性锚点，禁止以该脚本单独支撑结论")
    return {
        "ok": not problems,
        "watched": True,
        "raw_count": raw_count,
        "deterministic_bound": deterministic_bound,
        "anchors": list(anchors or []),
        "problems": problems,
        "reason": "非确定脚本口径合规" if not problems else "；".join(problems),
    }


def validate_acceptance(report: dict) -> Dict[str, object]:
    """汇总校验：``{suites, nondeterministic, deterministic_anchors, shrink_reason}``。"""
    report = dict(report or {})
    suites = list(report.get("suites") or [])
    anchors = list(report.get("deterministic_anchors") or [])
    problems: List[str] = []
    coverage = validate_coverage(suites, report.get("shrink_reason") or "")
    problems += coverage["problems"]
    raw = report.get("nondeterministic") or {}
    for suite, payload in raw.items():
        res = validate_nondeterministic(
            suite, payload.get("raw_count"), payload.get("deterministic_bound"), anchors)
        problems += res["problems"]
    return {
        "ok": not problems,
        "coverage": coverage,
        "problems": problems,
        "reason": "验收口径合规" if not problems else "；".join(problems),
    }


# ==================== v3.48 / 13.0.19：度量的层级升级 ====================

def load_baselines(root=None) -> Optional[dict]:
    """读 ``suite_baselines.json``（每套基线项数登记，逐行 unit）。"""
    import json
    conf = _conf()
    base = Path(root or config.BASE_DIR)
    path = base / (conf.get("baseline_registry_file") or "suite_baselines.json")
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 登记损坏按缺失处理，fail-closed
        return None


def suite_unit(suite: str) -> str:
    """套件计数单位（count_unit_declared_per_suite）：逐套件登记优先，目录默认兜底。

    实态：tests/ 目录里既有 pytest 文件（alpha101/factor/loader），也有
    check() 脚本式文件（backtest/signal_gate 等 8 套）——按目录一刀切会把
    脚本断言数混进 pytest 用例栏（13.0.19 ②）。单位以 suite_baselines.json
    的逐行 unit 为准；登记缺失时回退目录默认，再按文件内容嗅探。
    """
    data = load_baselines() or {}
    rec = (data.get("baselines") or {}).get(str(suite)) or {}
    if rec.get("unit"):
        return str(rec["unit"])
    units = _conf().get("count_units") or {}
    fallback = units.get("tests" if str(suite).startswith("tests/") else "root", "")
    # 内容嗅探：无登记时按「是否含 def test_ 函数」判定，避免目录默认误标
    path = Path(config.BASE_DIR) / str(suite)
    if path.exists():
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return fallback
        if "def test_" in src:
            return units.get("tests", "pytest_case")
        return units.get("root", "script_assertion")
    return fallback


def validate_baselines(observed: Dict[str, int], justification: str = "",
                       root=None) -> Dict[str, object]:
    """① 逐套项数基线校验：套件数没少 ≠ 覆盖面没少。

    冻结的不只是「跑了几个套件」，还有「每套跑了多少项」：项数跌幅超过
    ``baseline_drop_threshold_pct``（默认 20%）且无书面理由 = 静默缩减，fail。
    项数上涨不拦（但回执提示更新基线）。
    """
    conf = _conf()
    problems: List[str] = []
    rows: List[dict] = []
    data = load_baselines(root)
    if data is None:
        return {"ok": False,
                "problems": [f"缺少逐套基线登记 {conf.get('baseline_registry_file')}"
                             "（per_suite_baseline_required=True）：套件还在、断言删光照样全过"],
                "per_suite": rows}
    baselines = data.get("baselines") or {}
    frozen = frozen_suites()
    if conf.get("baseline_scope_frozen_suites", True):
        miss = [s for s in frozen if s not in baselines]
        if miss:
            problems.append(f"基线登记未覆盖冻结套件（{len(miss)} 个）：{miss}")
    threshold = float(conf.get("baseline_drop_threshold_pct") or 20)
    anchor_peak = bool(conf.get("baseline_must_anchor_historical_peak", True))
    peaks = dict(conf.get("baseline_initial_peaks") or {})
    for suite in frozen:
        rec = baselines.get(suite) or {}
        # v3.49 / 13.0.20 ②：基线只认历史峰值；「瘦身后的当前值」不得当基线
        if anchor_peak:
            base_count = rec.get("historical_peak")
            if base_count is None and peaks.get(suite) is not None:
                base_count = peaks[suite]
                problems.append(
                    f"{suite}: 基线缺 historical_peak（baseline_must_anchor_historical_peak）："
                    f"须登记历史峰值 {peaks[suite]}，不得用当前值代替")
        else:
            base_count = rec.get("historical_peak", rec.get("count"))
        cnt = observed.get(suite)
        row = {"suite": suite, "count": cnt, "historical_peak": base_count,
               "unit": suite_unit(suite)}
        if cnt is None or base_count is None:
            row["status"] = "missing" if cnt is None else "no_baseline"
            rows.append(row)
            continue
        base_count = int(base_count)
        delta = base_count - int(cnt)
        row["delta"] = delta
        drop = delta / float(base_count) * 100 if base_count else 0.0
        row["drop_pct"] = round(drop, 1)
        plan = str(rec.get("recovery_plan") or "").strip()
        if delta < 0:
            row["status"] = "grown"      # 涨了不拦，但提示登记新峰值
        elif delta == 0:
            row["status"] = "ok"
        elif conf.get("silent_ratchet_down_forbidden", True) and not (plan or
                                                                     str(justification or "").strip()):
            row["status"] = "silent_ratchet_down"
            problems.append(
                f"{suite}: 当前 {cnt} < 历史峰值 {base_count}（差 {delta}，-{drop:.0f}%）"
                "且无 recovery_plan（silent_ratchet_down_forbidden）："
                "禁止把基线悄悄下调到当前值")
        elif drop > threshold:
            row["status"] = "below_peak_justified"
            if plan:
                row["recovery_plan"] = plan
        else:
            row["status"] = "below_peak_tolerated"
        rows.append(row)
    return {"ok": not problems, "problems": problems, "per_suite": rows,
            "threshold_pct": threshold,
            "reason": "逐套基线全部锚定历史峰值" if not problems else "；".join(problems)}


def validate_report_units(rows: List[dict]) -> Dict[str, object]:
    """② 逐套件报数必须逐行带 unit 字段，且与 count_units 映射一致、分栏呈现。"""
    conf = _conf()
    problems: List[str] = []
    root_rows, tests_rows = [], []
    for row in rows or []:
        suite = str(row.get("suite") or "")
        want = suite_unit(suite)
        got = row.get("unit")
        if not got:
            problems.append(f"{suite}: 报数缺 unit 字段（per_suite_unit_field）")
        elif want and got != want:
            problems.append(f"{suite}: unit={got!r} 与冻结口径 {want!r} 不一致")
        (tests_rows if suite.startswith("tests/") else root_rows).append(
            {**row, "unit": got or want})
    if conf.get("pytest_and_script_reported_separately", True):
        # 分栏呈现：root（脚本断言数）与 tests（pytest 用例数）不得并排同栏
        pass
    return {"ok": not problems, "problems": problems,
            "root": root_rows, "tests": tests_rows,
            "reason": "计数单位分栏合规" if not problems else "；".join(problems)}


def _literal_int(node) -> Optional[int]:
    """只认字面整数常量（bool 是 int 子类，必须排除）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, int) \
            and not isinstance(node.value, bool):
        return int(node.value)
    return None


def _literal_sum(node) -> Optional[int]:
    """只认「字面整数」或「字面整数相加」：``34`` / ``19 + 15``。

    含 ``len()``/函数调用/变量运算一律返回 None——那是运行期取值，
    TARGETS 少一项上界就跟着缩水，等于闸门随被守卫对象一起松。
    """
    value = _literal_int(node)
    if value is not None:
        return value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_sum(node.left)
        right = _literal_sum(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _scan_test_data(script: str = "test_data.py", root=None) -> Dict[str, object]:
    """AST 扫描 test_data.py 顶层常量：bound / targets / fixed，不 import、不触网。"""
    base = Path(root or config.BASE_DIR)
    path = base / script
    if not path.exists():
        return {}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return {}
    out: Dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name == "TARGETS" and isinstance(node.value, ast.List):
                out["targets"] = len(node.value.elts)
            elif name == "FIXED_CHECK_COUNT":
                out["fixed"] = _literal_sum(node.value)
            elif name == "DETERMINISTIC_BOUND":
                out["bound"] = _literal_sum(node.value)
    return out


def offline_bound(script: str = "test_data.py", root=None) -> Optional[int]:
    """③ 离线静态上界：AST 解析顶层常量，不 import、不触网、断网不变。

    v3.49 / 13.0.20 ③：上界表达式**只认字面整数或字面整数相加**（``34`` / ``19 + 15``）。
    v3.48 的 ``len(TARGETS) + FIXED_CHECK_COUNT`` 是运行期取值——TARGETS 删一项，
    「上界」就自动缩水，闸门跟着松。两者一致性由 :func:`bound_consistency` 单独校验。
    """
    scanned = _scan_test_data(script, root)
    bound = scanned.get("bound")
    if bound is None:
        return None          # 不是字面量 → 拒绝当上界
    if "targets" not in scanned or scanned.get("fixed") is None:
        return None
    return int(bound)


def bound_consistency(script: str = "test_data.py", root=None) -> Dict[str, object]:
    """③ 上界口径的第二件事：字面量与 ``len(TARGETS)+FIXED_CHECK_COUNT`` 必须一致。

    「上界是字面量」和「字面量与标的表对得上」是两个独立判据，分开验：
    前者防止上界随 TARGETS 缩水，后者防止改了标的表却忘改字面量。
    """
    scanned = _scan_test_data(script, root)
    bound = scanned.get("bound")
    targets = scanned.get("targets")
    fixed = scanned.get("fixed")
    problems: List[str] = []
    if bound is None:
        problems.append(
            "DETERMINISTIC_BOUND 不是字面整数或字面整数相加"
            "（bound_must_be_ast_literal_or_literal_sum）；禁止 len()/函数调用/变量运算")
    if targets is None or fixed is None:
        problems.append("未能静态读出 TARGETS 列表长度或 FIXED_CHECK_COUNT 字面值")
    expected = None
    if targets is not None and fixed is not None:
        expected = int(targets) + int(fixed)
        if bound is not None and int(bound) != expected:
            problems.append(
                f"DETERMINISTIC_BOUND={bound} != len(TARGETS)={targets} + "
                f"FIXED_CHECK_COUNT={fixed}={expected}：改标的表/核查项必须同步改字面量上界")
    return {"ok": not problems, "bound": bound, "targets": targets, "fixed": fixed,
            "expected": expected, "problems": problems,
            "reason": "上界为字面量且与 TARGETS+FIXED 一致" if not problems
            else "；".join(problems)}


def validate_observed_against_bound(suite: str, observed: int,
                                    bound: Optional[int]) -> Dict[str, object]:
    """③ 实测 > 上界 → raise（``observed_exceeds_bound_action``）。"""
    conf = _nd_conf()
    action = str(conf.get("observed_exceeds_bound_action") or "raise")
    if bound is None:
        msg = (f"{suite}: 离线静态上界不可得（upper_bound_must_be_offline_computable）："
               "上界必须从模块级静态常量算出，禁止以实测反填")
        if action == "raise":
            raise ValueError(msg)
        return {"ok": False, "reason": msg}
    if observed is not None and int(observed) > int(bound):
        msg = (f"{suite}: 实测原始数 {observed} 超过离线静态上界 {bound}"
               "（上界不是上限，是必须解释的异常；observed_must_not_exceed_bound）")
        if action == "raise":
            raise ValueError(msg)
        return {"ok": False, "reason": msg}
    return {"ok": True, "observed": observed, "bound": bound,
            "reason": f"实测 {observed} ≤ 离线上界 {bound}"}
