# -*- coding: utf-8 -*-
"""12.13 验收：实盘前 15 项检查（离线可跑，人工项不冒充通过）。"""
from __future__ import annotations

import json

from tools import live_checklist as checklist


def test_exactly_fifteen_items():
    assert len(checklist.ITEMS) == 15
    assert [item["id"] for item in checklist.ITEMS] == list(range(1, 16))
    for item in checklist.ITEMS:
        assert item["category"] and item["title"] and item["hint"]


def test_run_checks_returns_four_categories():
    result = checklist.run_checks()
    summary = result["summary"]
    assert summary["total"] == 15
    assert set(summary) == {"pass", "fail", "skip", "manual", "total"}
    assert summary["pass"] + summary["fail"] + summary["skip"] + summary["manual"] == 15
    assert result["ok"] is True          # 自动项应全部通过（离线/仿真）
    assert summary["manual"] >= 5        # 开户/报备/实盘试跑等必须人工确认


def test_manual_items_never_count_as_pass():
    result = checklist.run_checks()
    manual = [i for i in result["items"] if i["status"] == "manual"]
    assert manual and all("需人工确认" in i["detail"] for i in manual)
    assert result["summary"]["pass"] == 15 - result["summary"]["manual"] \
        - result["summary"]["fail"] - result["summary"]["skip"]


def test_render_contains_guides():
    text = checklist.render()
    for keyword in ("穿透", "SimNow", "程序化交易报备", "滑点", "急停", "人工确认"):
        assert keyword in text
    assert "真实实盘" in text or "开实盘" in text


def test_json_mode_is_machine_readable(capsys):
    code = checklist.main(["--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload["summary"]["total"] == 15
    assert payload["env_example"]["ok"] is True


def test_gitignore_and_env_template_checked():
    assert checklist._check_env_example()["ok"] is True
    assert checklist._check_gitignore()["ok"] is True
    assert checklist._check_switch_off()["ok"] is True
    assert checklist._check_simnow()["ok"] is True
