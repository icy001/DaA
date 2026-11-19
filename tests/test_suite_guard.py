# -*- coding: utf-8 -*-
"""13.0.18/13.0.19 套件覆盖与非确定脚本口径验收（v3.47/v3.48）。

④ 报数套件 < 冻结 20 套且无理由 → 不合格；有理由则允许但必须留痕。
⑥ 非确定脚本（test_data.py）不得以单一原始数支撑结论：必须同时给确定性上界与锚点。
v3.48 追加：① 逐套项数基线 ② 逐行 unit 分栏 ③ 离线静态上界 + 超界 raise。
"""
from __future__ import annotations

from pathlib import Path

import pytest

import config
from core.gov_compat import gov
from core import suite_guard


def test_frozen_suites_are_twenty():
    frozen = suite_guard.frozen_suites()
    assert len(frozen) == gov("SUITE_COVERAGE_GUARD")["frozen_total"] == 20
    assert len(gov("SUITE_COVERAGE_GUARD")["root_suites"]) == 9
    assert len(gov("SUITE_COVERAGE_GUARD")["tests_suites"]) == 11
    assert len(frozen) == len(set(frozen)), "冻结清单不得有重复项"


def test_full_coverage_passes():
    out = suite_guard.validate_coverage(suite_guard.frozen_suites())
    assert out["ok"] is True, out["reason"]
    assert out["reported_total"] == out["frozen_total"] == 20


def test_unjustified_shrink_fails():
    """④ 只报 9 套且无理由 → 不合格（静默缩减 = 验收缩水）。"""
    reported = list(gov("SUITE_COVERAGE_GUARD")["root_suites"])
    out = suite_guard.validate_coverage(reported)
    assert out["ok"] is False
    assert out["reported_total"] == 9 and out["frozen_total"] == 20
    assert "无缩减理由" in out["reason"]
    assert len(out["missing"]) == 11


def test_justified_shrink_is_allowed_but_recorded():
    """④ 有书面理由的缩减允许发生，但必须留痕（justified=True + missing 列全）。"""
    reported = list(gov("SUITE_COVERAGE_GUARD")["root_suites"])
    out = suite_guard.validate_coverage(reported, justification="tests/ 正在重构，本轮豁免")
    assert out["ok"] is True
    assert out["justified"] is True and len(out["missing"]) == 11


def test_nondeterministic_needs_raw_and_bound():
    """⑥ test_data 只报原始数、没有确定性上界 → 不得单独支撑结论。"""
    out = suite_guard.validate_nondeterministic(
        "test_data.py", raw_count=34, deterministic_bound=None, anchors=["pytest:tests"])
    assert out["ok"] is False and "确定性上界" in out["reason"]

    out = suite_guard.validate_nondeterministic(
        "test_data.py", raw_count=34, deterministic_bound=34, anchors=["pytest:tests"])
    assert out["ok"] is True

    # 没有确定性锚点时，非确定脚本不得单独支撑结论
    out = suite_guard.validate_nondeterministic(
        "test_data.py", raw_count=34, deterministic_bound=34, anchors=[])
    assert out["ok"] is False and "单独支撑结论" in out["reason"]


def test_validate_acceptance_aggregates_both_gates():
    report = {
        "suites": list(gov("SUITE_COVERAGE_GUARD")["root_suites"]),
        "nondeterministic": {"test_data.py": {"raw_count": 34,
                                             "deterministic_bound": None}},
        "deterministic_anchors": ["pytest:tests"],
    }
    out = suite_guard.validate_acceptance(report)
    assert out["ok"] is False
    assert len(out["problems"]) == 2          # 覆盖不足 + 缺确定性上界


# ==================== v3.48 / 13.0.19：逐套基线 + 分栏单位 + 离线上界 ====================

def test_per_suite_baseline_registry_exists_and_covers_frozen():
    """① 逐套基线登记必须存在且覆盖冻结 20 套（数盒子 → 数盒中物）。"""
    data = suite_guard.load_baselines()
    assert data is not None, "suite_baselines.json 缺失：套件还在、断言删光也全过"
    assert set(data["baselines"]) == set(suite_guard.frozen_suites())


def test_silent_baseline_drop_fails_but_justified_passes():
    """① 基线锚历史峰值：跌破峰值且无 recovery_plan = 静默缩减 fail；有说明放行但留痕。

    v3.49：基线字段是 historical_peak，不是「瘦身后的当前值」——把 28→10 写成新
    baseline 等于给旧缩减发合格证，必须被拦。
    """
    data = suite_guard.load_baselines()
    observed = {k: v.get("historical_peak", v.get("count"))
                for k, v in data["baselines"].items()}
    shrunk = dict(observed, **{"tests/test_backtest.py": 10})     # 峰值 28 → 10 = -64%
    out = suite_guard.validate_baselines(shrunk)
    assert out["ok"] is False
    assert any(r["status"] == "silent_ratchet_down" for r in out["per_suite"]
               if r["suite"] == "tests/test_backtest.py")
    assert "test_backtest" in out["reason"] and "recovery_plan" in out["reason"]

    ok = suite_guard.validate_baselines(
        shrunk, justification="外部源不可达，断言以 skipped_due_to_source 计")
    assert ok["ok"] is True
    assert any(r["status"] == "below_peak_justified" for r in ok["per_suite"]
               if r["suite"] == "tests/test_backtest.py")


def test_baseline_anchored_to_historical_peak_not_current():
    """② 峰值为 alpha101=10 / factor=58 / loader=20；当前实测 2/6/4 必须显式披露差距。"""
    data = suite_guard.load_baselines()
    peaks = {k: v["historical_peak"] for k, v in data["baselines"].items()}
    assert peaks["tests/test_alpha101.py"] == 10
    assert peaks["tests/test_factor.py"] == 58
    assert peaks["tests/test_loader.py"] == 20
    for rel in ("tests/test_alpha101.py", "tests/test_factor.py", "tests/test_loader.py"):
        assert data["baselines"][rel].get("recovery_plan"), f"{rel} 必须带 recovery_plan"
    current = {"tests/test_alpha101.py": 2, "tests/test_factor.py": 6,
               "tests/test_loader.py": 4}
    out = suite_guard.validate_baselines({**peaks, **current})
    assert out["ok"] is True, out["reason"]          # 有 recovery_plan → 允许，但必须披露
    rows = {r["suite"]: r for r in out["per_suite"]}
    assert rows["tests/test_factor.py"]["delta"] == 52
    assert rows["tests/test_factor.py"]["status"] == "below_peak_justified"
    assert rows["tests/test_factor.py"]["recovery_plan"]


def test_baseline_growth_not_blocked_but_flagged():
    """① 项数上涨不拦（但必须提示登记新峰值，防止基线永远停在旧口径）。"""
    data = suite_guard.load_baselines()
    observed = {k: v.get("historical_peak", v.get("count"))
                for k, v in data["baselines"].items()}
    grown = dict(observed, **{"tests/test_backtest.py": 40})     # 28→40
    out = suite_guard.validate_baselines(grown)
    assert out["ok"] is True
    row = next(r for r in out["per_suite"] if r["suite"] == "tests/test_backtest.py")
    assert row["status"] == "grown"


def test_report_rows_require_unit_field_and_split_columns():
    """② 逐套件报数逐行带 unit 字段：unit 逐套件登记，不以目录一刀切。

    实态：tests/ 里 alpha101/factor/loader 是 pytest 文件（pytest_case），
    backtest/signal_gate 等 8 套是 check() 脚本式文件（script_assertion）。
    """
    # 基线登记的三种单位必须能被 suite_unit 正确读出
    assert suite_guard.suite_unit("test_data.py") == "script_assertion"
    assert suite_guard.suite_unit("tests/test_alpha101.py") == "pytest_case"
    assert suite_guard.suite_unit("tests/test_backtest.py") == "script_assertion"

    good = [{"suite": "test_data.py", "count": 34, "unit": "script_assertion"},
            {"suite": "tests/test_alpha101.py", "count": 2, "unit": "pytest_case"},
            {"suite": "tests/test_backtest.py", "count": 28, "unit": "script_assertion"}]
    out = suite_guard.validate_report_units(good)
    assert out["ok"] is True, out["problems"]
    assert [r["suite"] for r in out["root"]] == ["test_data.py"]
    assert [r["suite"] for r in out["tests"]] == ["tests/test_alpha101.py",
                                                  "tests/test_backtest.py"]

    # 缺 unit / unit 与登记口径不一致 → fail（同表并排两种计数单位即口径污染）
    bad = [{"suite": "test_data.py", "count": 34},
           {"suite": "tests/test_backtest.py", "count": 28, "unit": "pytest_case"}]
    out = suite_guard.validate_report_units(bad)
    assert out["ok"] is False and len(out["problems"]) == 2
    assert "缺 unit 字段" in out["problems"][0]
    assert "不一致" in out["problems"][1]


def test_offline_bound_static_and_offline_survives():
    """③ 上界必须是离线静态常量：AST 解析得 34，与运行期 import 的值一致（断网不变）。"""
    bound = suite_guard.offline_bound()
    assert bound is not None, "DETERMINISTIC_BOUND 必须是字面整数或字面整数相加"
    import test_data
    assert bound == test_data.DETERMINISTIC_BOUND == 34
    assert test_data.DETERMINISTIC_BOUND == len(test_data.TARGETS) + \
        test_data.FIXED_CHECK_COUNT

    # 静态形态被破坏（上界改成运行期变量）→ 不得再当上界用
    bad = ("TARGETS = [1, 2]\nFIXED_CHECK_COUNT = 3\n"
           "DETERMINISTIC_BOUND = some_runtime_value()\n")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "test_data.py"
        p.write_text(bad, encoding="utf-8")
        assert suite_guard.offline_bound(script=str(p)) is None


def test_bound_is_literal_or_literal_sum():
    """③ 上界只认字面整数/字面整数相加：len(TARGETS)+FIXED 这一形态必须被拒。"""
    import tempfile
    good = suite_guard.bound_consistency()
    assert good["ok"] is True, good["reason"]
    assert good["bound"] == good["expected"] == 34

    cases = {
        # 纯字面量
        "TARGETS = [1, 2]\nFIXED_CHECK_COUNT = 3\nDETERMINISTIC_BOUND = 5\n":
            (5, True),
        # 字面整数相加
        "TARGETS = [1, 2]\nFIXED_CHECK_COUNT = 3\nDETERMINISTIC_BOUND = 3 + 2\n":
            (5, True),
        # v3.48 形态（len 调用）→ 不再算字面量
        "TARGETS = [1, 2]\nFIXED_CHECK_COUNT = 3\n"
        "DETERMINISTIC_BOUND = len(TARGETS) + FIXED_CHECK_COUNT\n":
            (None, False),
        # 字面量与标的表对不上 → 上界可读但一致性 fail
        "TARGETS = [1, 2]\nFIXED_CHECK_COUNT = 3\nDETERMINISTIC_BOUND = 9\n":
            (9, False),
    }
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "test_data.py"
        for src, (want_bound, want_ok) in cases.items():
            p.write_text(src, encoding="utf-8")
            assert suite_guard.offline_bound(script=str(p)) == want_bound, src
            assert suite_guard.bound_consistency(script=str(p))["ok"] is want_ok, src


def test_observed_exceeding_static_bound_raises():
    """③ 实测 > 离线上界 → raise（上界随可达性缩水 = 闸门随被守卫对象松）。"""
    out = suite_guard.validate_observed_against_bound("test_data.py", 34, 34)
    assert out["ok"] is True
    with pytest.raises(ValueError, match="超过离线静态上界"):
        suite_guard.validate_observed_against_bound("test_data.py", 35, 34)
    with pytest.raises(ValueError, match="不可得"):
        suite_guard.validate_observed_against_bound("test_data.py", 34, None)
