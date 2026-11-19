# -*- coding: utf-8 -*-
"""K2 验收：第 12 步入口一致性——实盘/回测/模拟盘共用同一份 signal_gate。

核心断言：同一份「预热期 + fillna(0)」帧，在 Backtester / PaperTrader /
LiveTrader(仿真) 下 buy() 都被拒单；三个引擎 import 的是同一个
``core.signal_gate`` 模块（只调用、不重写）。
"""
from __future__ import annotations

import pandas as pd
import pytest

import core.backtester as bt_mod
import core.paper_trader as pt_mod
import core.signal_gate as signal_gate
import live.live_trader as lt_mod
from broker.sim_broker import SimBroker
from core.account import TradingAccount
from core.strategy import BaseStrategy
from live.idempotency import IdempotencyStore
from live.kill_switch import KillSwitch
from live.live_trader import LiveTrader
from live.reconciliation import Reconciler

DATE = pd.Timestamp("2026-11-12")


def _cold_bar(symbol="600519"):
    return {symbol: {"open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0,
                     "volume": 1000.0, "warmup_ok": False,
                     "data_asof_date": "2026-11-12", "price_adjust": "qfq",
                     "date": "2026-11-12"}}


def _cold_frame(n: int = 80) -> pd.DataFrame:
    """预热期 + fillna(0)：末根 warmup_ok=False，但 RSI 已被 0 填充。"""
    idx = pd.bdate_range(end="2026-11-12", periods=n)
    frame = pd.DataFrame({"open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0,
                          "volume": 1000.0, "RSI": 0.0}, index=idx)
    frame["warmup_ok"] = False
    frame["data_asof_date"] = idx
    frame["price_adjust"] = "qfq"
    return frame


class ColdProbe(BaseStrategy):
    """预热期也照买（用于验证三引擎的闸门确实拦住了）。"""

    meta = {"name": "_cold_probe", "periods": ["1d"], "params": {},
            "warmup": [("RSI", {"n": 14})], "description": "test"}

    def init(self):
        self.results = []

    def on_bar(self, date, bars):
        for symbol in bars:
            self.results.append(self.buy(symbol, 100))


def test_three_engines_share_one_signal_gate():
    assert bt_mod.signal_gate is signal_gate
    assert pt_mod.signal_gate is signal_gate
    assert lt_mod.signal_gate is signal_gate


def test_fillna_cold_frame_blocked_at_signal_entry():
    frame = _cold_frame()
    with pytest.raises(ValueError, match="预热期|fillna"):
        signal_gate.check_signal_frame(frame, indicator_columns=["RSI"],
                                       run_mode="live")


def test_backtest_and_paper_strategy_buy_rejected():
    """Backtester / PaperTrader 的 _dispatch 都走 strategy.dispatch_bar → buy。"""
    account = TradingAccount(1_000_000.0, run_mode="paper")
    strategy = ColdProbe(account=account, run_mode="paper")
    strategy.dispatch_bar(DATE, _cold_bar())
    assert strategy.results and strategy.results[0]["status"] == "rejected"
    assert strategy.results[0]["stage"] == "warmup"
    assert strategy.rejected_orders[-1]["stage"] == "warmup"
    # 账户层最终收口同样拒开仓（策略层被绕过时仍生效）
    assert account.place_order("600519", "buy", volume=100, price=10.0,
                               warmup_ok=False)["status"] == "rejected"
    assert account.place_order("600519", "buy", volume=100, price=10.0,
                               warmup_ok=None)["status"] == "rejected"


def test_live_trader_buy_rejected_on_same_cold_bar(tmp_path):
    account = TradingAccount(1_000_000.0, run_mode="live_sim")
    broker = SimBroker(cash=1_000_000.0)
    trader = LiveTrader(
        broker, account=account, mode="live_sim", simulated=True,
        store=IdempotencyStore(path=tmp_path / "ids.json"),
        kill_switch=KillSwitch(flag_file=tmp_path / "KILL"),
        reconciler=Reconciler(account, broker, state_file=tmp_path / "recon.json"),
        freshness_fn=lambda **_: True, first_order_confirmed=True)
    out = trader.buy("600519", 100, 10.0, _cold_bar()["600519"])
    assert out["status"] == "rejected" and out["stage"] == "warmup"
    assert len(broker.orders) == 0
    assert out["mode"] == "live_sim"           # 报单必须带模式标注


def test_live_trader_on_bar_requires_materialized_columns(tmp_path):
    account = TradingAccount(1_000_000.0, run_mode="live_sim")
    broker = SimBroker(cash=1_000_000.0)
    trader = LiveTrader(
        broker, account=account, mode="live_sim", simulated=True,
        store=IdempotencyStore(path=tmp_path / "ids.json"),
        kill_switch=KillSwitch(flag_file=tmp_path / "KILL"),
        reconciler=Reconciler(account, broker, state_file=tmp_path / "recon.json"),
        freshness_fn=lambda **_: True, first_order_confirmed=True)
    with pytest.raises(ValueError, match="物化列|warmup_ok"):
        trader.on_bar(DATE, {"600519": {"close": 10.0}})      # 裸行情直接喂
    with pytest.raises(ValueError, match="物化列"):
        trader.on_tick({"600519": {"close": 10.0, "warmup_ok": True}})


# ==================== watch-only 是第六个信号出口（必须过同一份闸门） ====================

class _FakeTrader:
    def __init__(self, stale: bool = False):
        self.stale = stale

    def _freshness(self, symbol, direction, bar, market):
        if self.stale:
            raise RuntimeError("数据已停更")


class _FakeNotifier:
    def __init__(self):
        self.signals, self.risks = [], []

    def on_signal(self, msg):
        self.signals.append(msg)

    def on_risk(self, msg):
        self.risks.append(msg)


def _wo_bar(warmup=True):
    return {"close": 10.0, "warmup_ok": warmup, "data_asof_date": DATE,
            "price_adjust": "hfq", "date": DATE}


def _session_open(monkeypatch):
    from datetime import datetime, timedelta
    import core.utils as utils
    now = datetime.now()
    monkeypatch.setattr(utils, "get_trading_sessions",
                        lambda market, date=None: [(now - timedelta(hours=1),
                                                    now + timedelta(hours=1))])


def test_watch_only_blocks_signal_in_warmup(monkeypatch):
    from run_live import _WatchOnly
    _session_open(monkeypatch)
    note = _FakeNotifier()
    out = _WatchOnly(_FakeTrader(), note).buy("600519", 100, bar=_wo_bar(False))
    assert out["stage"] == "watch_only_blocked" and note.signals == []
    assert note.risks and "预热" in note.risks[0]


def test_watch_only_blocks_stale_signal(monkeypatch):
    from run_live import _WatchOnly
    _session_open(monkeypatch)
    note = _FakeNotifier()
    out = _WatchOnly(_FakeTrader(stale=True), note).sell("600519", 100, bar=_wo_bar())
    assert out["stage"] == "watch_only_blocked" and note.signals == []
    assert "时效" in note.risks[0]


def test_watch_only_blocks_off_session(monkeypatch):
    from run_live import _WatchOnly
    import core.utils as utils
    monkeypatch.setattr(utils, "get_trading_sessions", lambda market, date=None: [])
    note = _FakeNotifier()
    out = _WatchOnly(_FakeTrader(), note).buy("600519", 100, bar=_wo_bar())
    assert out["stage"] == "watch_only_blocked" and "非交易时段" in out["reason"]
    assert note.signals == []


def test_watch_only_pushes_only_after_all_gates(monkeypatch):
    from run_live import _WatchOnly
    _session_open(monkeypatch)
    note = _FakeNotifier()
    out = _WatchOnly(_FakeTrader(), note).buy("600519", 100, bar=_wo_bar())
    assert out["stage"] == "watch_only" and out["ok"] is False
    assert note.signals and note.signals[0].startswith("600519")
    assert note.risks == []
