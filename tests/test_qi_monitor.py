# -*- coding: utf-8 -*-
"""test_qi_monitor.py —— 第 10 步 10.5 盯盘提醒 + 对外披露出口。

硬约束：
  ① 所有提醒类型必须在 SIGNAL_EGRESS_CONFORMANCE["alert_types"] 登记，未登记拒发；
  ② 「提醒 ≠ 拦截」：提醒发出后，后续申购仍被动作闸门拒绝；
  ③ 对外披露材料满足 DISCLOSURE_CONFORMANCE（五类费用、风险揭示、类型标注、
     完整区间、禁保本措辞、与引擎同源且固定 investor_net）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from core.gov_compat import gov
from core.qi_monitor import (ALERT_TYPES, build_qi_alerts, detect_neeq_delisting,
                             detect_neeq_liquidity, detect_reits_premium,
                             detect_snowball, send_qi_alert)
from core.qualified_investor import QIChecker, QualifiedInvestorRejected
from core.reporter import DisclosureConformanceError, Reporter
from nav_backtest.nav_backtester import NavBacktester

DATES = pd.date_range("2023-01-06", periods=120, freq="W-FRI")
IND_OK = {"investor_type": "individual", "financial_assets_wan": 350,
          "avg_annual_income_wan_3y": 20, "invest_years": 3}
IND_LOW = {"investor_type": "individual", "financial_assets_wan": 100,
           "avg_annual_income_wan_3y": 10, "invest_years": 1}


class FakeNotifier:
    def __init__(self) -> None:
        self.calls = []

    def send(self, title, content, level="info"):
        self.calls.append({"title": title, "content": content, "level": level})
        return True


# ==================== 出口登记 ====================

def test_all_alert_types_registered():
    registered = gov("SIGNAL_EGRESS_CONFORMANCE")["alert_types"]
    assert set(ALERT_TYPES) <= set(registered)
    assert "qi_threshold_check" in registered
    for alert_type in ALERT_TYPES:
        assert alert_type in config.QI_MONITOR_ALERTS


def test_unregistered_alert_refused():
    with pytest.raises(ValueError) as info:
        send_qi_alert(FakeNotifier(), "free_form_alert", "标题", "正文")
    assert "未在 SIGNAL_EGRESS_CONFORMANCE" in str(info.value)


def test_alert_carries_level_and_disclaimer():
    notifier = FakeNotifier()
    assert send_qi_alert(notifier, "reits_premium_alert", "REITs 提醒", "折价 12%")
    call = notifier.calls[-1]
    assert call["level"] == config.QI_MONITOR_ALERTS["reits_premium_alert"]["level"]
    assert "提醒不等于拦截" in call["content"]


# ==================== 各类事件识别 ====================

def test_detect_reits_premium_thresholds():
    notifier = FakeNotifier()
    assert detect_reits_premium("508000", -0.05) is None
    discount = detect_reits_premium("508000", -0.12, notifier=notifier)
    assert discount["kind"] == "discount"
    premium = detect_reits_premium("508000", 0.20, notifier=notifier)
    assert premium["kind"] == "premium"
    assert len(notifier.calls) == 2


def test_detect_neeq_delisting_and_liquidity():
    flagged = pd.DataFrame({"close": [10.0, 11.0], "delisting_warning": [False, True],
                            "volume": [1000, 0]})
    assert detect_neeq_delisting("830001", flagged)["alert_type"] == "neeq_delisting_warning"
    calm = pd.DataFrame({"close": [10.0, 10.1], "delisting_warning": [False, False],
                         "volume": [1000, 900]})
    assert detect_neeq_delisting("830001", calm) is None
    dry = pd.DataFrame({"volume": [0] * config.QI_NEEQ_ZERO_VOLUME_DAYS})
    assert detect_neeq_liquidity("830001", dry)["zero_days"] == \
        config.QI_NEEQ_ZERO_VOLUME_DAYS
    assert detect_neeq_liquidity("830001", calm) is None


def test_detect_snowball_knock_in_and_observe():
    assert detect_snowball("SNOW1", spot=76.0, ki_level=75.0)["alert_type"] == \
        "snowball_knock_in_warning"
    assert detect_snowball("SNOW1", spot=120.0, ki_level=75.0) is None
    observe = detect_snowball("SNOW1", spot=120.0, ki_level=75.0,
                              observe_date="2026-11-12", today="2026-11-12")
    assert observe["alert_type"] == "snowball_knock_out_observe"
    assert "仅模拟账户" in observe["content"]


# ==================== 提醒 ≠ 拦截 ====================

def test_alert_does_not_block_but_next_action_does(tmp_path):
    qi = QIChecker(audit_log_path=tmp_path / "qi.jsonl")
    notifier = FakeNotifier()
    alerts = build_qi_alerts(qi, IND_LOW, "private_fund", notifier=notifier)
    assert alerts and alerts[0]["alert_type"] == "qi_threshold_check"
    assert alerts[0]["sent"] is True
    assert "提醒不等于拦截" in notifier.calls[-1]["content"]
    with pytest.raises(QualifiedInvestorRejected):
        qi.check_action("subscribe", IND_LOW, product_type="private_fund",
                        amount_wan=150)


# ==================== 对外披露材料（第四个出口） ====================

def make_nav_result(tmp_path):
    engine = NavBacktester(product_type="private_fund")
    nav = pd.Series([1.0 * (1.004 ** i) for i in range(len(DATES))], index=DATES)
    engine.set_nav(nav)
    qi = QIChecker(audit_log_path=tmp_path / "nav_qi.jsonl")
    engine.subscribe("A", DATES[0], 1_000_000.0,
                     qi_checker=qi, profile=IND_OK, amount_wan=100)
    return engine.run()


def test_disclosure_report_conformance(tmp_path):
    result = make_nav_result(tmp_path)
    qi = QIChecker(audit_log_path=tmp_path / "qi.jsonl")
    qi.check_action("subscribe", IND_OK, product_type="private_fund", amount_wan=100)
    reporter = Reporter(notifiers=[FakeNotifier()], report_dir=str(tmp_path / "reports"))
    decision = DATES[-1] + pd.Timedelta(days=2)
    report = reporter.generate_qi_report(nav_result=result, decision_date=decision,
                                         qi_checker=qi, title="披露测试")
    assert report["kind"] == "qi"
    assert report["layer"] == config.NAV_PRODUCT_CONFIG["disclosure_layer"] == "investor_net"
    assert report["data_asof"] == DATES[-1].date().isoformat()
    assert report["run_mode"] == "backtest" and report["run_mode_label"] == "回测"
    labels = [row[0] for row in report["fee_rows"]]
    for label in ("申购费", "赎回费", "管理费", "业绩报酬", "托管费"):
        assert label in labels
    assert report["performance_fee_rows"]
    assert report["risk_rows"]
    assert report["qi_audit_ok"] is True
    html = Path(report["html_path"]).read_text(encoding="utf-8")
    for word in ("保本", "保收益", "零风险"):
        assert word not in html


def test_disclosure_rejects_selective_period(tmp_path):
    result = make_nav_result(tmp_path)
    reporter = Reporter(notifiers=[FakeNotifier()], report_dir=str(tmp_path / "reports"))
    decision = DATES[-1] + pd.Timedelta(days=2)
    with pytest.raises(DisclosureConformanceError) as info:
        reporter.generate_qi_report(
            nav_result=result, decision_date=decision,
            period={"start": DATES[-10].date(), "end": DATES[-1].date()})
    assert "禁止只报最有利区间" in str(info.value)
