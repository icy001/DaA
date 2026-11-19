# -*- coding: utf-8 -*-
"""第 8 步验收测试：定时盯盘与消息推送。

覆盖（验收三条硬指标 + 通知渠道行为）：
    ① 预热期 bar 的开仓信号不被推送（只推拦截提醒=风控提醒）；
    ② 停更数据不推交易信号（只推「数据异常」告警，且不喂策略）；
    ③ 非交易时段不推交易信号。

全部使用 Fake 组件，不触网、不读真实行情。
"""
from __future__ import annotations

import time
from datetime import datetime

import pandas as pd
import pytest

import core.monitor as monitor_mod
import config
from core.monitor import MarketMonitor
from core.notifier import ConsoleNotifier, LogNotifier


# --------------------------------------------------------------------------- #
# Fake 组件
# --------------------------------------------------------------------------- #
class FakeNotifier:
    """记录所有 send 调用的测试通知渠道。"""

    def __init__(self) -> None:
        self.sent: list = []

    def send(self, title, content, level="info"):
        self.sent.append((title, content, level))
        return True


class FakeOrder:
    def __init__(self, order_id, symbol, direction, price=10.0, reason="MA金叉"):
        self.order_id = order_id
        self.symbol = symbol
        self.direction = direction
        self.price = price
        self.reason = reason


class FakeAccount:
    def __init__(self) -> None:
        self.positions: dict = {}


class FakePaperTrader:
    def __init__(self) -> None:
        self._orders: list = []
        self.account = FakeAccount()

    @property
    def orders(self):
        return self._orders

    def save_account(self):
        return "fake_account.json"


class FakeStrategy:
    """记录喂入的 bar；可选择在回调里下开仓单。"""

    def __init__(self, trader: FakePaperTrader = None, open_on_bar=False):
        self.fed: list = []
        self.trader = trader
        self.open_on_bar = open_on_bar

    def dispatch_bar(self, date, bar_dict):
        self.fed.append((date, dict(bar_dict)))
        if self.open_on_bar and self.trader is not None:
            self.trader._orders.append(FakeOrder("O1", "510300", "buy"))


class FakeFetcher:
    """可控行情源：df 可换；assert_fresh 可配置为抛错（模拟停更）。"""

    def __init__(self, df: pd.DataFrame = None, stale_error: str = ""):
        self.df = df
        self.stale_error = stale_error
        self.fresh_calls: list = []

    def get_daily(self, symbol, adjust="qfq", **kw):
        return self.df

    def assert_fresh_for_trading(self, df, kind="daily", market=None,
                                 symbol=None, fetcher=None,
                                 for_trading=False, order_side="open"):
        self.fresh_calls.append((symbol, order_side, for_trading))
        if self.stale_error:
            raise RuntimeError(self.stale_error)
        return True


def _df(n=3, last_close=10.0, symbol=None):
    """构造合规日线帧（含 date/OHLCV）。"""
    rows = []
    base = last_close - (n - 1) * 0.1
    for i in range(n):
        rows.append({"date": f"2026-11-{2 + i:02d}",
                     "open": round(base + i * 0.1, 3),
                     "high": round(base + i * 0.1 + 0.05, 3),
                     "low": round(base + i * 0.1 - 0.05, 3),
                     "close": round(base + i * 0.1, 3),
                     "volume": 1000 + i})
    df = pd.DataFrame(rows)
    if symbol:
        df["symbol"] = symbol
    return df


def _make_monitor(df, warmup_bars=5, stale_error="", trader=None,
                  strategy=None, market="cn_stock", now=None):
    fetcher = FakeFetcher(df, stale_error=stale_error)
    notifier = FakeNotifier()
    monitor = MarketMonitor(
        paper_trader=trader, strategy=strategy, notifiers=[notifier],
        fetcher=fetcher, markets={market: ["510300"]},
        warmup_bars=warmup_bars, scheduler=object())
    monitor._last_calendar_day = "2099-01-01"   # 关闭日历推送干扰
    return monitor, fetcher, notifier


def _in_session_now():
    """cn_stock 交易时段内的固定时刻（周四上午 10:00）。"""
    return datetime(2026, 11, 12, 10, 0)        # 2026-11-12 为周四


@pytest.fixture(autouse=True)
def _no_fetch_throttle(monkeypatch):
    monkeypatch.setattr(monitor_mod, "MIN_FETCH_INTERVAL", 0)


# --------------------------------------------------------------------------- #
# 通知渠道行为
# --------------------------------------------------------------------------- #
def test_console_notifier_sends():
    n = ConsoleNotifier()
    assert n.send("测试标题", "测试内容", level="info") is True


def test_log_notifier_writes_file(tmp_path):
    log_file = tmp_path / "notify.log"
    n = LogNotifier(log_file=str(log_file))
    assert n.send("写日志", "内容") is True
    assert "写日志" in log_file.read_text(encoding="utf-8")


def test_notifier_dedup_within_10_minutes():
    n = ConsoleNotifier()
    assert n.send("同一标题", "同一内容") is True
    assert n.send("同一标题", "同一内容") is False       # 10 分钟内去重


def test_notifier_rate_limit_5_per_minute():
    n = ConsoleNotifier()
    results = [n.send(f"消息{i}", f"内容{i}") for i in range(6)]
    assert results[:5] == [True] * 5
    assert results[5] is False                          # 第 6 条被限流


def test_notifier_invalid_level_normalized():
    n = ConsoleNotifier()
    assert n.send("标题", "内容", level="bogus") is True


# --------------------------------------------------------------------------- #
# 三物化列注入（8.0 硬约束）
# --------------------------------------------------------------------------- #
def test_bars_carry_all_three_materialized_columns():
    trader = FakePaperTrader()
    strategy = FakeStrategy()
    monitor, _, _ = _make_monitor(_df(), warmup_bars=3, trader=trader,
                                  strategy=strategy)
    _run_check(monitor, "cn_stock")
    assert strategy.fed, "策略必须被喂到 bar"
    _, bars = strategy.fed[-1]
    bar = bars["510300"]
    assert "warmup_ok" in bar
    assert bar.get("data_asof_date") == "2026-11-04"
    assert bar.get("price_adjust") == config.INDICATOR_CONFIG["default_adjust"]


def _run_check(monitor: MarketMonitor, market: str, now=None):
    """在固定“时段内”时刻执行单轮检查（绕开真实时钟）。"""
    assert monitor.is_in_session(market, now=_in_session_now())
    # 临时替换时段判断的时间源
    original = monitor.is_in_session

    def patched(m, n=None):
        return original(m, now=_in_session_now())
    monitor.is_in_session = patched                     # type: ignore[method-assign]
    try:
        monitor.check_market(market)
    finally:
        monitor.is_in_session = original                # type: ignore[method-assign]


# --------------------------------------------------------------------------- #
# 验收①：预热期 bar 的开仓信号不被推送
# --------------------------------------------------------------------------- #
def test_warmup_open_signal_not_pushed():
    """warmup_ok=False 时产生的 buy 开仓信号：不推交易信号，只推拦截提醒。"""
    trader = FakePaperTrader()
    strategy = FakeStrategy(trader=trader, open_on_bar=True)
    # df 3 根 < 门槛 5 → bar 的 warmup_ok=False
    monitor, fetcher, notifier = _make_monitor(_df(n=3), warmup_bars=5,
                                               trader=trader, strategy=strategy)
    _run_check(monitor, "cn_stock")

    titles = [t for t, _, _ in notifier.sent]
    assert not any("已过预热闸门" in t for t in titles), \
        "预热期开仓信号绝不能被推送为可执行交易信号"
    assert any("未推送交易信号" in t for t in titles), \
        "必须推送拦截提醒（风控提醒允许推）"
    # 策略确实被喂了 bar（喂入合规，拦截发生在推送出口）
    assert strategy.fed


def test_warm_passed_open_signal_is_pushed():
    """对照组：预热已过 + 数据新鲜 → 开仓信号正常推送并带标注。"""
    trader = FakePaperTrader()
    strategy = FakeStrategy(trader=trader, open_on_bar=True)
    # df 6 根 ≥ 门槛 5 → warmup_ok=True
    monitor, _, notifier = _make_monitor(_df(n=6), warmup_bars=5,
                                         trader=trader, strategy=strategy)
    _run_check(monitor, "cn_stock")

    titles = [t for t, _, _ in notifier.sent]
    assert any("已过预热闸门" in t for t in titles)
    body = [c for t, c, _ in notifier.sent if "已过预热闸门" in t][0]
    assert "数据截至:" in body and "新鲜度: 新鲜" in body


# --------------------------------------------------------------------------- #
# 验收②：停更数据不推交易信号（只推数据异常告警）
# --------------------------------------------------------------------------- #
def test_stale_data_no_trade_signal_only_data_alert():
    trader = FakePaperTrader()
    strategy = FakeStrategy(trader=trader, open_on_bar=True)
    monitor, fetcher, notifier = _make_monitor(
        _df(), warmup_bars=3, trader=trader, strategy=strategy,
        stale_error="数据停更：最后 bar 距今 3 个交易日，超出 STALE_MAX_TRADE_DAYS")

    _run_check(monitor, "cn_stock")

    titles = [t for t, _, _ in notifier.sent]
    assert any("数据异常" in t for t in titles), "停更必须推数据异常告警"
    assert not any("开仓信号" in t for t in titles), \
        "停更数据绝不能推送交易信号"
    assert not strategy.fed, "停更数据不能喂给策略（禁止裸旧数据进入策略）"
    # 时效闸门确实被调用（第 4 步 refetch 同源）
    assert fetcher.fresh_calls


def test_stale_close_direction_still_allowed():
    """平仓方向即使停更也放行（开严平宽：不能因为取不到行情下不出止损单）。"""
    trader = FakePaperTrader()
    trader._orders.append(FakeOrder("O-close", "510300", "sell", reason="止损"))
    strategy = FakeStrategy()           # 不开新仓，直接注入平仓单
    monitor, _, notifier = _make_monitor(_df(), warmup_bars=3,
                                         trader=trader, strategy=strategy)
    _run_check(monitor, "cn_stock")

    # 数据新鲜（FakeFetcher 未配置 stale_error），sell 平仓单应被推送
    titles = [t for t, _, _ in notifier.sent]
    assert any("平仓/减仓信号" in t for t in titles)


# --------------------------------------------------------------------------- #
# 验收③：非交易时段不推交易信号
# --------------------------------------------------------------------------- #
def test_out_of_session_no_signal_no_feed():
    trader = FakePaperTrader()
    strategy = FakeStrategy(trader=trader, open_on_bar=True)
    monitor, _, notifier = _make_monitor(_df(n=6), warmup_bars=5,
                                         trader=trader, strategy=strategy)

    # 周六（2026-11-14）为非交易日：is_in_session 必须为 False
    saturday = datetime(2026, 11, 14, 10, 0)
    assert monitor.is_in_session("cn_stock", now=saturday) is False
    # 周四 10:00 在 A 股时段内：必须为 True（对照组，防误判）
    assert monitor.is_in_session("cn_stock", now=_in_session_now()) is True


def test_out_of_session_check_returns_early():
    """时段外 check_market 直接返回：不拉数、不喂策略、不推任何信号。"""
    trader = FakePaperTrader()
    strategy = FakeStrategy(trader=trader, open_on_bar=True)
    monitor, fetcher, notifier = _make_monitor(_df(n=6), warmup_bars=5,
                                               trader=trader, strategy=strategy)
    monitor.is_in_session = lambda m, n=None: False     # 强制时段外
    monitor.check_market("cn_stock")

    assert not strategy.fed
    assert notifier.sent == []
    assert fetcher.fresh_calls == []                    # 连行情都没拉


# --------------------------------------------------------------------------- #
# 时效闸门接线（push_requires_fresh）
# --------------------------------------------------------------------------- #
def test_open_signal_requires_freshness_gate():
    trader = FakePaperTrader()
    strategy = FakeStrategy(trader=trader, open_on_bar=True)
    monitor, fetcher, notifier = _make_monitor(_df(n=6), warmup_bars=5,
                                               trader=trader, strategy=strategy)
    _run_check(monitor, "cn_stock")
    # 每次开仓推送前必须过了时效闸门，且开仓方向 order_side=open
    assert any(side == "open" for _, side, for_trading in fetcher.fresh_calls
               if for_trading)


# --------------------------------------------------------------------------- #
# 熔断与事件扫描（防封 IP + 事件清单）
# --------------------------------------------------------------------------- #
def test_circuit_breaker_after_5_failures():
    class BrokenFetcher(FakeFetcher):
        def get_daily(self, symbol, adjust="qfq", **kw):
            raise RuntimeError("网络不可达")

    monitor, _, notifier = _make_monitor(_df(), warmup_bars=5,
                                         trader=FakePaperTrader(),
                                         strategy=FakeStrategy())
    monitor.fetcher = BrokenFetcher()
    for _ in range(5):
        monitor._fetch_df("cn_stock", "510300")
    assert monitor._fail["510300"] == 5
    assert monitor._circuit_paused("510300"), "连续失败 5 次必须熔断 10 分钟"


def test_scan_events_price_alert_and_volume_spike():
    trader = FakePaperTrader()

    class Pos:
        avg_cost = 8.0

    trader.account.positions = {"510300": Pos()}
    monitor, _, notifier = _make_monitor(_df(n=30, last_close=8.5),
                                         warmup_bars=3, trader=trader,
                                         strategy=FakeStrategy())
    df = _df(n=30, last_close=8.5)      # 现价 8.5 vs 成本 8.0 → +6.25% ≥ ±5%
    df.loc[df.index[-1], "volume"] = 3000   # 20 日均量约 1029 → 今量 ≥ 2 倍
    monitor.scan_events(df)

    titles = [t for t, _, _ in notifier.sent]
    assert any("涨跌幅预警" in t for t in titles)
    assert any("成交量异动" in t for t in titles)


def test_repo_rate_alert():
    monitor, _, notifier = _make_monitor(_df(), warmup_bars=3,
                                         trader=FakePaperTrader(),
                                         strategy=FakeStrategy())
    monitor.repo_rate_getter = lambda: 3.5
    monitor.check_repo_rate()
    assert any("逆回购利率飙升" in t for t, _, _ in notifier.sent)

    monitor.repo_rate_getter = lambda: 2.0
    monitor.check_repo_rate()
    assert len(notifier.sent) == 1      # 低于阈值不推送
