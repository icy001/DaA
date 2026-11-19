# -*- coding: utf-8 -*-
"""第 9 步：自动复盘报告测试（tests/test_reporter.py）。

覆盖 9.0 三条硬断言 + 第 9 步报告本体：
  1) 同源：报告只读 account.trades / rejected_orders / bills / signal_gate 裁决日志；
  2) 拦截披露：逐项列出 warmup/stale/off_session/limit_up_down/volume_limit/risk_block
     并计数；0 笔交易拆解为「策略无信号」/「闸门拦截 N 笔」；
  3) 明日候选（report_plan）必须过 signal_gate + 时效/时段，预热/停更/非时段不得进入；
  4) 绩效与引擎同源（直接取 result.metrics / calc_metrics）；
  5) 自动发送走 notifier 且发送前过时效闸门；
  6) config 登记 report_plan 与 REPORT_CONFORMANCE；
  7) 日报九大板块（账户/持仓/交易/分市场/风控/信号/明日计划/市场情绪/绩效）；
  8) 周报/月报：权益曲线 + 月度热力图 + 盈亏分布 + 极值交易 + 参数评估；
  9) 回测专项：策略参数、全部绩效、分年度收益、交易 CSV、回撤/热力图；
 10) Jinja2 模板渲染与 PDF 可选降级。
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import core.signal_gate as signal_gate
from core.notifier import BaseNotifier
from core.reporter import Reporter

TODAY = date.today()


# ==================== 桩 ====================

class FakeNotifier(BaseNotifier):
    name = "fake"

    def __init__(self):
        self.messages = []
        super().__init__()

    def send(self, title, content, level="info"):
        self.messages.append({"title": title, "content": content, "level": level})
        return True


class FakeAccount:
    def __init__(self, trades=None, rejected_orders=None):
        self.trades = list(trades or [])
        self.rejected_orders = list(rejected_orders or [])
        self.positions = {}
        self.short_positions = {}
        self.daily_equity = []
        self.initial_capital = 100000.0
        self.equity = 100000.0
        self.cash = 100000.0
        self.margin_used = 0.0


class FakeTrader:
    def __init__(self, trades=None, rejected_orders=None, bills=None):
        self.account = FakeAccount(trades, rejected_orders)
        self.bills = list(bills or [])
        self.market_of = {"600519": "cn_stock", "AAPL": "us_stock",
                          "rb": "cn_future", "BTC": "crypto"}


class FakeResult:
    strategy_name = "fake_ma"

    def __init__(self, metrics):
        self.metrics = dict(metrics)
        self.trades = []
        self.traps = []
        self.meta = {}


def make_bar(symbol_warmup=True, asof=None, adjust="qfq", close=10.0) -> dict:
    bar = signal_gate.build_bar({"close": close, "open": close, "high": close,
                                 "low": close, "volume": 1000},
                                1, 1 if symbol_warmup else 120,
                                date=asof or TODAY)
    bar["data_asof_date"] = asof or TODAY
    bar["price_adjust"] = adjust
    return bar


def make_reporter(tmp_path, trades=None, rejected_orders=None, bills=None,
                  result=None, fresh=None, session=None, notifier=None,
                  sentiment=None, embed_js=False):
    trader = FakeTrader(trades, rejected_orders, bills)
    return Reporter(paper_trader=trader, result=result,
                    report_dir=str(tmp_path),
                    notifiers=[notifier] if notifier else [FakeNotifier()],
                    fresh_checker=fresh,
                    in_session_checker=session,
                    sentiment_provider=sentiment,
                    embed_plotly_js=embed_js), trader


def rejected(symbol, direction, code, reason, idx):
    return {"status": "rejected", "symbol": symbol, "direction": direction,
            "code": code, "reason": reason, "reject_id": f"rej_{idx}"}


# ==================== 1. config 登记 ====================

def test_config_registration():
    points = config.SIGNAL_EGRESS_CONFORMANCE["signal_egress_points"]
    assert points == ["place_order", "monitor_push", "report_plan",
                      "investor_disclosure", "live_order_submit",
                      "watch_only_live_push"], points
    conf = config.REPORT_CONFORMANCE
    assert conf["must_report_suppression"] is True
    assert conf["zero_trade_disclosure"] is True
    assert conf["plan_is_signal_egress"] is True
    assert conf["plan_requires_fresh"] is True
    assert conf["metrics_must_share_source"] is True
    assert conf["auto_send_requires_fresh"] is True
    assert conf["suppression_reasons"] == ["warmup", "stale", "off_session",
                                          "limit_up_down", "volume_limit",
                                          "risk_block"]
    assert signal_gate.suppression_reasons() == conf["suppression_reasons"]


# ==================== 2. 拦截披露 ====================

def test_suppression_disclosure(tmp_path):
    signal_gate.clear_decisions()
    rejected_orders = [
        rejected("600519", "buy", "warmup", "指标仍处于预热期（warmup_ok=False）", 0),
        rejected("510300", "buy", "stale", "数据时效复核未通过：超过 5 个交易日", 1),
        rejected("rb", "short", "limit_up_down", "涨停无法买入", 2),
        rejected("AAPL", "buy", "volume_limit", "超过当日成交量 1% 限制", 3),
        rejected("BTC", "buy", "risk_block", "超过单标的仓位上限", 4),
        rejected("000001", "buy", "off_session", "非交易时段", 5),
    ]
    # 再加一条只存在于 signal_gate 裁决日志的盯盘拦截（monitor_push）
    signal_gate.record_decision("600519", "buy", False,
                                reason="指标仍处于预热期",
                                reason_code="warmup", source="monitor_push")

    reporter, _ = make_reporter(tmp_path, rejected_orders=rejected_orders)
    report = reporter.generate_daily_report(TODAY)

    supp = report["suppressions"]
    assert supp["total"] == 7, supp["total"]
    assert supp["counts"]["warmup"] == 2
    assert supp["counts"]["stale"] == 1
    assert supp["counts"]["off_session"] == 1
    assert supp["counts"]["limit_up_down"] == 1
    assert supp["counts"]["volume_limit"] == 1
    assert supp["counts"]["risk_block"] == 1
    assert any(i["source"] == "monitor_push" for i in supp["items"])

    # 0 笔交易必须显式拆解，不能只显示 0
    assert report["trade_count"] == 0
    assert "闸门拦截 7 笔" in report["zero_trade_text"]
    assert "warmup 2 笔" in report["zero_trade_text"]

    html = Path(report["html_path"]).read_text(encoding="utf-8")
    for token in ("warmup", "stale", "off_session", "limit_up_down",
                  "volume_limit", "risk_block", "被拦截信号", "闸门拦截 7 笔"):
        assert token in html, token


def test_zero_trade_without_suppression(tmp_path):
    signal_gate.clear_decisions()
    reporter, _ = make_reporter(tmp_path)
    report = reporter.generate_daily_report(TODAY)
    assert report["suppressions"]["total"] == 0
    assert "策略无信号" in report["zero_trade_text"]
    assert "当日无拦截记录" in report["zero_trade_text"]


# ==================== 3. 明日候选（report_plan） ====================

def test_plan_excludes_warmup_stale_off_session(tmp_path):
    signal_gate.clear_decisions()
    bars = {
        "600519": {"bar": make_bar(True), "market": "cn_stock"},
        "000001": {"bar": make_bar(False), "market": "cn_stock"},      # 预热期
        "AAPL": {"bar": make_bar(True), "market": "us_stock"},         # 停更
        "rb": {"bar": make_bar(True), "market": "cn_future"},          # 非交易时段
    }

    def fresh(_bar, market, _now):
        return market != "us_stock"                     # AAPL 数据停更

    def session(market, _now):
        return market != "cn_future"                    # 期货夜盘外视为非交易时段

    reporter, _ = make_reporter(tmp_path, fresh=fresh, session=session)
    info = reporter.build_plan(bars, now=datetime(2026, 11, 12, 10, 0))

    plan_symbols = [p["symbol"] for p in info["plan"]]
    excluded = {x["symbol"]: x for x in info["excluded"]}
    assert plan_symbols == ["600519"], plan_symbols
    assert "000001" not in plan_symbols and excluded["000001"]["code"] == "warmup"
    assert "AAPL" not in plan_symbols and excluded["AAPL"]["code"] == "stale"
    assert "rb" not in plan_symbols and excluded["rb"]["code"] == "off_session"
    assert "仅供观察" in excluded["000001"]["tag"]
    assert "数据存疑" in excluded["AAPL"]["tag"]
    # 候选必须标注数据截至日期
    assert info["plan"][0]["data_asof_date"] == TODAY.isoformat()


def test_plan_requires_three_columns(tmp_path):
    signal_gate.clear_decisions()
    bare = {"600519": {"close": 10.0}}                  # 裸行情，缺三物化列
    reporter, _ = make_reporter(tmp_path)
    info = reporter.build_plan(bare, now=datetime(2026, 11, 12, 10, 0))
    assert info["plan"] == []
    assert info["excluded"][0]["code"] == "stale"


# ==================== 4. 绩效同源 ====================

def test_metrics_share_engine_source(tmp_path):
    metrics = {"total_return": 0.25, "annual_return": 0.18,
               "max_drawdown": -0.08, "win_rate": 0.6,
               "profit_factor": 1.8, "trade_count": 42}
    result = FakeResult(metrics)
    reporter, _ = make_reporter(tmp_path, result=result)
    assert reporter.metrics() == metrics          # 直接取引擎结果，不另算
    report = reporter.generate_daily_report(TODAY)
    assert report["metrics"] == metrics


# ==================== 5. 自动发送过时效闸门 ====================

def test_auto_send_requires_fresh(tmp_path):
    signal_gate.clear_decisions()
    notifier = FakeNotifier()

    # 数据停更：bills 最后一根是 30 天前 → 只发数据告警，不发报告内容
    stale_bills = [{"date": TODAY - timedelta(days=30), "equity": 100000.0}]
    reporter, _ = make_reporter(tmp_path, bills=stale_bills, notifier=notifier)
    report = reporter.generate_daily_report(TODAY, auto_send=True)
    assert report["sent"] is False
    assert notifier.messages and "数据停更" in notifier.messages[-1]["title"]

    # 数据新鲜：正常发送报告摘要
    fresh_notifier = FakeNotifier()
    fresh_bills = [{"date": TODAY, "equity": 100000.0}]
    reporter2, _ = make_reporter(tmp_path, bills=fresh_bills,
                                notifier=fresh_notifier)
    report2 = reporter2.generate_daily_report(TODAY, auto_send=True)
    assert report2["sent"] is True
    assert fresh_notifier.messages
    assert "每日复盘" in fresh_notifier.messages[-1]["title"]


# ==================== 6. HTML 落盘 ====================

def test_report_html_written(tmp_path):
    signal_gate.clear_decisions()
    result = FakeResult({"win_rate": 0.5, "max_drawdown": -0.1,
                         "trade_count": 3})
    reporter, _ = make_reporter(tmp_path, result=result)
    report = reporter.generate_daily_report(TODAY)
    path = Path(report["html_path"])
    assert path.exists() and path.stat().st_size > 500
    html = path.read_text(encoding="utf-8")
    assert "<html" in html and "明日候选" in html and "绩效指标" in html


# ==================== 7. 日报九大板块 ====================

class _Pos:
    def __init__(self, volume=100.0, avg_cost=10.0, last_price=11.0, prev_close=10.5):
        self.volume = volume
        self.avg_cost = avg_cost
        self.last_price = last_price
        self.prev_close = prev_close


def _bills(days=60, base=100000.0, step=150.0):
    return [{"date": TODAY - timedelta(days=days - 1 - i),
             "equity": base + i * step} for i in range(days)]


def _trades(count=20):
    return [{"timestamp": TODAY - timedelta(days=i),
             "symbol": "600519" if i % 2 else "510300",
             "market": "cn_stock",
             "direction": "sell" if i % 2 else "buy",
             "action": "close" if i % 2 == 0 else "open",
             "price": 10.0 + i * 0.2, "volume": 100.0,
             "pnl": float((i - 10) * 80), "commission": 5.0}
            for i in range(count)]


def test_daily_report_all_sections(tmp_path):
    signal_gate.clear_decisions()
    sentiment = {"index_name": "上证指数", "index_change": 0.012,
                 "up_count": 3000, "down_count": 1800, "limit_up": 45,
                 "limit_down": 6, "turnover": 9.8e11, "northbound": 2.1e9}
    reporter, trader = make_reporter(tmp_path, bills=_bills(), trades=_trades(12),
                                     sentiment=lambda _day: sentiment)
    trader.account.positions = {"600519": _Pos()}

    report = reporter.generate_daily_report(TODAY)
    assert report["daily_pnl"] is not None
    assert report["sentiment"]["available"] is True
    assert len(report["sentiment_rows"]) == 8
    assert report["position_rows"] and report["trade_rows"]
    assert report["market_pnl_rows"]
    assert any("仓位比例" in row[0] for row in report["risk_rows"])
    assert report["executed_rows"]

    html = Path(report["html_path"]).read_text(encoding="utf-8")
    for token in ("账户概览", "持仓明细", "当日交易", "分市场盈亏", "市场情绪",
                  "风控检查", "信号汇总与被拦截信号", "明日候选", "绩效指标"):
        assert token in html, token


def test_sentiment_unavailable_is_explicit(tmp_path):
    signal_gate.clear_decisions()
    reporter, _ = make_reporter(tmp_path)
    report = reporter.generate_daily_report(TODAY)
    assert report["sentiment"]["available"] is False
    html = Path(report["html_path"]).read_text(encoding="utf-8")
    assert "市场情绪数据源未接入" in html


# ==================== 8. 周报 / 月报（图表与复盘板块） ====================

def test_weekly_report_charts_and_review(tmp_path):
    signal_gate.clear_decisions()
    reporter, _ = make_reporter(tmp_path, bills=_bills(), trades=_trades(20))
    report = reporter.generate_weekly_report(TODAY)
    assert Path(report["html_path"]).exists()
    charts = report["charts"]
    assert any(charts.values()), charts
    assert report["trade_stats_rows"]
    assert len(report["extreme_rows"]) >= 1
    assert report["param_review"]
    html = Path(report["html_path"]).read_text(encoding="utf-8")
    for token in ("策略绩效统计", "交易盈亏分布", "最大盈利", "策略参数评估"):
        assert token in html, token


def test_monthly_report_generated(tmp_path):
    signal_gate.clear_decisions()
    reporter, _ = make_reporter(tmp_path, bills=_bills(), trades=_trades(20))
    report = reporter.generate_monthly_report(TODAY)
    path = Path(report["html_path"])
    assert path.exists() and path.name.startswith("monthly_")
    assert report["period"] == "monthly"
    assert "total_return" in report["metrics"]


# ==================== 9. 回测专项报告 ====================

def test_backtest_report_full(tmp_path):
    signal_gate.clear_decisions()
    metrics = {"total_return": 0.2, "annual_return": 0.1,
               "max_drawdown": -0.12, "win_rate": 0.55,
               "profit_factor": 1.4, "trade_count": 20,
               "final_equity": 120000.0, "initial_capital": 100000.0}
    result = FakeResult(metrics)
    result.nav = pd.DataFrame([
        {"date": (TODAY - timedelta(days=400 - i)).isoformat(),
         "equity": 100000.0 + i * 120} for i in range(401)])
    result.trades = pd.DataFrame(_trades(20))
    reporter, _ = make_reporter(tmp_path, result=result)
    report = reporter.generate_backtest_report()

    path = Path(report["html_path"])
    assert path.exists()
    assert report["trade_csv"] and (path.parent / report["trade_csv"]).exists()
    assert len(report["yearly_rows"]) >= 2
    assert any(report["charts"].values())
    html = path.read_text(encoding="utf-8")
    for token in ("策略概述与参数", "分年度收益", "下载 CSV", "交易明细"):
        assert token in html, token


# ==================== 10. 模板 / PDF 可选降级 ====================

def test_jinja2_template_rendered(tmp_path):
    signal_gate.clear_decisions()
    reporter, _ = make_reporter(tmp_path)
    report = reporter.generate_daily_report(TODAY)
    assert reporter._env is not None, "Jinja2 模板环境未建立"
    html = Path(report["html_path"]).read_text(encoding="utf-8")
    assert 'class="wrap"' in html
    assert "多市场量化交易系统自动生成" in html


def test_pdf_optional_degrades(tmp_path, monkeypatch):
    signal_gate.clear_decisions()
    monkeypatch.setattr("core.reporter.shutil.which", lambda _name: None)
    reporter, _ = make_reporter(tmp_path)
    report = reporter.generate_daily_report(TODAY, pdf=True)
    assert report["pdf_path"] is None            # 缺 wkhtmltopdf：跳过，不影响 HTML
    assert Path(report["html_path"]).exists()
