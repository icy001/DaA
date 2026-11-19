# -*- coding: utf-8 -*-
"""K3 验收：报单幂等（超时/重连/崩溃重启不得重复下单）。"""
from __future__ import annotations

import copy

import pytest

import config
from core.gov_compat import gov
from broker.base_broker import UNKNOWN, BrokerOrder
from broker.sim_broker import SimBroker
from core.account import TradingAccount
from live.errors import IdempotencyError
from live.idempotency import IdempotencyStore
from live.kill_switch import KillSwitch
from live.live_trader import LiveTrader
from live.reconciliation import Reconciler


def _bar(warmup=True):
    return {"close": 10.0, "warmup_ok": warmup, "data_asof_date": "2026-11-12",
            "price_adjust": "qfq", "date": "2026-11-12"}


def _trader(tmp_path, broker, store=None, **kwargs):
    account = TradingAccount(initial_capital=1_000_000, run_mode="live_sim")
    kwargs.setdefault("freshness_fn", lambda **_: True)
    kwargs.setdefault("first_order_confirmed", True)
    return LiveTrader(
        broker, account=account, mode="live_sim", simulated=True,
        store=store or IdempotencyStore(path=tmp_path / "ids.json"),
        kill_switch=KillSwitch(flag_file=tmp_path / "KILL"),
        reconciler=Reconciler(account, broker, state_file=tmp_path / "recon.json"),
        **kwargs)


class _TimeoutNoRecordBroker(SimBroker):
    """首次超时且查无记录（券商确认未受理）→ 允许重发一次。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.calls = 0

    def place_order(self, order: BrokerOrder) -> BrokerOrder:
        self.calls += 1
        if self.calls == 1:
            out = copy.copy(order)
            out.status = UNKNOWN
            out.message = "报单超时（券商查无记录）"
            return out
        return super().place_order(order)

    def query_order(self, client_order_id):
        return None if self.calls == 1 else super().query_order(client_order_id)


def test_config_registered():
    conf = gov("LIVE_SAFETY")["idempotency"]
    assert conf["on_duplicate"] == "reject"
    assert conf["on_unknown_state"] == "query_broker_first"
    assert "{symbol}" in conf["format"] and "{seq}" in conf["format"]
    assert conf["dedup_window_sec"] > 0


def test_timeout_but_accepted_does_not_resubmit(tmp_path):
    """事故链：报单超时但券商已受理 → 只允许一笔，不得重发。"""
    broker = SimBroker(cash=1_000_000, timeout_but_accept=True)
    out = _trader(tmp_path, broker).buy("600519", 100, 10.0, _bar())
    assert out["status"] == "accepted" and out["ok"] is True
    assert len(broker.orders) == 1, "状态未知但已受理，重发会导致仓位翻倍"
    assert len(broker.trades) == 1
    assert "禁止重发" in out["reason"]


def test_unknown_without_broker_record_resubmits_once(tmp_path):
    broker = _TimeoutNoRecordBroker(cash=1_000_000)
    out = _trader(tmp_path, broker).buy("600519", 100, 10.0, _bar())
    assert broker.calls == 2 and out["ok"] is True and len(broker.orders) == 1


def test_duplicate_same_client_order_id_rejected(tmp_path):
    broker = SimBroker(cash=1_000_000)
    trader = _trader(tmp_path, broker)
    first = trader.buy("600519", 100, 10.0, _bar(), client_order_id="STRAT-600519-buy-20261112-1")
    assert first["status"] == "accepted"
    second = trader.buy("600519", 100, 10.0, _bar(), client_order_id="STRAT-600519-buy-20261112-1")
    assert second["status"] == "rejected" and second["stage"] == "idempotency"
    assert len(broker.orders) == 1


def test_idempotency_key_survives_restart(tmp_path):
    broker = SimBroker(cash=1_000_000)
    key = "STRAT-600519-buy-20261112-1"
    _trader(tmp_path, broker).buy("600519", 100, 10.0, _bar(), client_order_id=key)
    # 模拟崩溃重启：新进程重新加载同一份落盘文件
    restarted = IdempotencyStore(path=tmp_path / "ids.json")
    assert restarted.has(key) and restarted.get(key)["status"] == "accepted"
    out = _trader(tmp_path, broker, store=restarted).buy(
        "600519", 100, 10.0, _bar(), client_order_id=key)
    assert out["status"] == "rejected" and out["stage"] == "idempotency"
    assert len(broker.orders) == 1


def test_rejected_order_not_retried(tmp_path):
    """12.14.6：被拒单（废单）不自动重试，与状态未知单区分。"""
    broker = SimBroker(cash=1_000_000)
    broker.reject_next = True
    out = _trader(tmp_path, broker).buy("600519", 100, 10.0, _bar())
    assert out["status"] == "rejected" and len(broker.orders) == 1
    assert "废单" in out["reason"]


def test_store_duplicate_raises_directly(tmp_path):
    store = IdempotencyStore(path=tmp_path / "ids.json", now_fn=lambda: 1000.0)
    store.register("K-1")
    with pytest.raises(IdempotencyError):
        store.register("K-1")
