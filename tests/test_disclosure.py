# -*- coding: utf-8 -*-
"""G4：对外披露是第四个信号出口（tests/test_disclosure.py）。

验收：
  1) 与引擎同源（绩效取 NavResult.metrics，不另算）；
  2) 费用五类齐全（申购/赎回/管理/业绩报酬/托管）；
  3) 含被抑制信号；
  4) 明确标注回测/模拟/实盘；
  5) 附风险揭示；
  6) 禁止「保本/保收益/零风险」措辞；
  7) 禁止只报最有利区间；
  8) 含合格投资者审计留痕；
  9) 自动发送前过时效闸门。
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import core.signal_gate as signal_gate
from core.notifier import BaseNotifier
from core.qualified_investor import QIChecker
from core.reporter import DisclosureConformanceError, Reporter, _assert_no_guarantee
from nav_backtest.nav_backtester import NavBacktester

IND_OK = {"investor_type": "individual", "financial_assets_wan": 350,
          "avg_annual_income_wan_3y": 60, "invest_years": 3}


class FakeNotifier(BaseNotifier):
    name = "fake"

    def __init__(self):
        self.messages = []
        super().__init__()

    def send(self, title, content, level="info"):
        self.messages.append({"title": title, "content": content, "level": level})
        return True


class FakeAccount:
    def __init__(self):
        self.trades = []
        self.rejected_orders = []
        self.positions = {}
        self.short_positions = {}
        self.daily_equity = []
        self.initial_capital = 1_000_000.0
        self.equity = 1_000_000.0
        self.cash = 1_000_000.0
        self.margin_used = 0.0


class FakeTrader:
    def __init__(self):
        self.account = FakeAccount()
        self.bills = []
        self.market_of = {}


def make_reporter(tmp_path):
    notifier = FakeNotifier()
    reporter = Reporter(paper_trader=FakeTrader(), report_dir=str(tmp_path),
                        notifiers=[notifier])
    return reporter, notifier


def build_result():
    idx = pd.date_range("2025-01-03", periods=60, freq="W-FRI")
    nav = pd.Series([1.004 ** i for i in range(60)], index=idx)
    engine = NavBacktester("private_fund")
    engine.set_nav(nav)
    engine.subscribe("A", idx[0], 1_000_000)
    engine.subscribe("B", idx[20], 500_000)
    result = engine.run()
    return engine, result


def test_disclosure_full_conformance(tmp_path):
    signal_gate.clear_decisions()
    engine, result = build_result()
    signal_gate.record_decision("600519", "buy", False, reason="指标仍处于预热期",
                                reason_code="warmup", source="monitor_push")
    qi = QIChecker(audit_log_path=tmp_path / "qi.jsonl")
    qi.check_action("subscribe", IND_OK, product_type="private_fund", amount_wan=100)
    reporter, _ = make_reporter(tmp_path)
    decision = engine._gross.index[-1] + timedelta(days=3)

    report = reporter.generate_investor_disclosure(nav_result=result,
                                                   decision_date=decision,
                                                   qi_checker=qi)
    html = Path(report["html_path"]).read_text(encoding="utf-8")

    # 1) 同源 + 固定 investor_net
    assert report["layer"] == "investor_net"
    assert report["metrics"] == result.metrics()
    assert report["reconcile_ok"] is True
    # 2) 费用五类
    for token in ("申购费", "赎回费", "管理费", "业绩报酬", "托管费", "费用合计"):
        assert token in html, token
    # 3) 被抑制信号
    assert report["suppression_total"] == 1
    assert "被拦截信号" in html and "warmup" in html
    # 4) 标注类型
    assert report["run_mode"] == "backtest"
    assert "回测" in html
    # 5) 风险揭示
    assert "风险揭示" in html and "流动性风险" in html
    # 6) 禁止措辞
    for word in ("保本", "保收益", "保证收益", "零风险"):
        assert word not in html
    # 7) 数据截至 + 完整区间
    assert report["data_asof"]
    assert report["period_rows"][0][1] == str(result.layers.investor_net.index[0].date())
    # 8) 审计留痕
    assert report["qi_audit_ok"] is True
    assert any("subscribe" in row[1] for row in report["qi_audit_rows"])
    # 业绩报酬明细与投资者层净值对账
    assert "业绩报酬计提明细" in html
    assert "对账" in html


def test_selective_period_forbidden(tmp_path):
    engine, result = build_result()
    reporter, _ = make_reporter(tmp_path)
    idx = engine._gross.index
    with pytest.raises(DisclosureConformanceError):
        reporter.generate_investor_disclosure(
            nav_result=result, decision_date=idx[-1] + timedelta(days=3),
            period={"start": idx[-5], "end": idx[-1]})


def test_guarantee_wording_rejected():
    with pytest.raises(DisclosureConformanceError):
        _assert_no_guarantee("<html>本产品保本保收益，零风险</html>")
    _assert_no_guarantee("<html>历史业绩不代表未来，可能出现本金损失</html>")


def test_auto_send_requires_fresh(tmp_path):
    engine, result = build_result()
    reporter, notifier = make_reporter(tmp_path)
    decision = engine._gross.index[-1] + timedelta(days=40)   # 远超一个披露周期
    report = reporter.generate_investor_disclosure(
        nav_result=result, decision_date=decision, auto_send=True)
    assert report["sent"] is False
    assert any("披露未发送" in m["title"] for m in notifier.messages)


def test_disclosure_layer_guard(tmp_path):
    engine, result = build_result()
    reporter, _ = make_reporter(tmp_path)
    old = config.NAV_PRODUCT_CONFIG["disclosure_layer"]
    try:
        config.NAV_PRODUCT_CONFIG["disclosure_layer"] = "product_gross"
        with pytest.raises(DisclosureConformanceError):
            reporter.generate_investor_disclosure(
                nav_result=result,
                decision_date=engine._gross.index[-1] + timedelta(days=3))
    finally:
        config.NAV_PRODUCT_CONFIG["disclosure_layer"] = old
