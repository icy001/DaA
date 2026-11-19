# -*- coding: utf-8 -*-
"""K4 验收：对账前移（权威在券商侧，不一致立即停开新仓）。"""
from __future__ import annotations

import pytest

import config
from core.gov_compat import gov
from broker.sim_broker import SimBroker
from core.account import Position, TradingAccount
from live.errors import ReconcileHaltError
from live.idempotency import IdempotencyStore
from live.kill_switch import KillSwitch
from live.live_trader import LiveTrader
from live.reconciliation import Reconciler


def _bar():
    return {"close": 10.0, "warmup_ok": True, "data_asof_date": "2026-11-12",
            "price_adjust": "qfq", "date": "2026-11-12"}


def _account(cash=1_000_000.0):
    return TradingAccount(initial_capital=cash, run_mode="live_sim")


def _trader(tmp_path, account, broker, reconciler=None):
    return LiveTrader(
        broker, account=account, mode="live_sim", simulated=True,
        store=IdempotencyStore(path=tmp_path / "ids.json"),
        kill_switch=KillSwitch(flag_file=tmp_path / "KILL"),
        reconciler=reconciler,
        freshness_fn=lambda **_: True, first_order_confirmed=True)


def test_config_authority_is_broker():
    conf = gov("LIVE_SAFETY")["reconcile"]
    assert gov("LIVE_SAFETY")["authoritative"] == "broker"
    assert conf["pre_order"] is True and conf["startup"] is True and conf["eod"] is True
    assert conf["on_mismatch"] == "halt_new_orders"
    assert conf["resume_requires"] == "manual_confirm"
    assert conf["interval_sec"] <= 60


def test_local_missing_fill_blocks_next_order(tmp_path):
    """本地少记一笔成交（券商已有 200 股，本地 0）→ 下一次报单前被拦。"""
    account = _account()
    broker = SimBroker(cash=1_000_000, positions={"600519": {"volume": 200}})
    trader = _trader(tmp_path, account, broker,
                     Reconciler(account, broker, state_file=tmp_path / "recon.json"))
    out = trader.buy("600519", 100, 10.0, _bar())
    assert out["status"] == "rejected" and out["stage"] == "reconcile"
    assert len(broker.orders) == 0
    assert (tmp_path / "recon.json").exists()


def test_halt_survives_restart_and_needs_manual_confirm(tmp_path):
    account = _account()
    broker = SimBroker(cash=1_000_000, positions={"600519": {"volume": 200}})
    state = tmp_path / "recon.json"
    reconciler = Reconciler(account, broker, state_file=state)
    reconciler.reconcile(reason="startup")
    assert reconciler.is_halted()
    # 重启：新 Reconciler 读同一状态文件，仍是停机态
    restarted = Reconciler(account, broker, state_file=state)
    assert restarted.is_halted()
    with pytest.raises(ReconcileHaltError):
        restarted.require_clean()
    restarted.manual_confirm(operator="tester")
    restarted.require_clean()               # 人工确认后放行


def test_manual_confirm_allows_next_order(tmp_path):
    account = _account()
    broker = SimBroker(cash=1_000_000, positions={"600519": {"volume": 200}})
    reconciler = Reconciler(account, broker, state_file=tmp_path / "recon.json")
    trader = _trader(tmp_path, account, broker, reconciler)
    assert trader.buy("600519", 100, 10.0, _bar())["status"] == "rejected"
    # 人工把本地账本补齐，再显式确认（停机态不会因一次对账通过就自动恢复）
    account.positions["600519"] = Position(symbol="600519", market="cn_stock",
                                           volume=200, avg_cost=10.0,
                                           last_price=10.0, multiplier=1)
    assert reconciler.reconcile(reason="post_fix")["ok"] is True
    assert reconciler.is_halted()              # 仍需人工确认
    reconciler.manual_confirm(operator="tester")
    assert not reconciler.is_halted()
    out = trader.buy("600519", 100, 10.0, _bar())
    assert out["status"] == "accepted"


def test_clean_books_pass_and_cash_mismatch_detected(tmp_path):
    account = _account()
    broker = SimBroker(cash=1_000_000)
    reconciler = Reconciler(account, broker, state_file=tmp_path / "recon.json")
    assert reconciler.reconcile()["ok"] is True
    broker.cash = 999_000.0                   # 差 1000 元 ≥ 1 分
    result = reconciler.reconcile()
    assert result["ok"] is False
    assert any(d["kind"] == "cash" for d in result["diffs"])


def test_startup_reconcile_runs_on_init(tmp_path):
    account = _account()
    broker = SimBroker(cash=1_000_000, positions={"600519": {"volume": 100}})
    trader = _trader(tmp_path, account, broker, reconciler=None)  # 初始化即 startup 对账
    assert trader.reconciler.is_halted()
    assert trader.buy("600519", 100, 10.0, _bar())["stage"] == "reconcile"


def test_intraday_tick_respects_interval(tmp_path):
    clock = {"now": 1000.0}
    account = _account()
    broker = SimBroker(cash=1_000_000)
    reconciler = Reconciler(account, broker, state_file=tmp_path / "recon.json",
                            now_fn=lambda: clock["now"])
    assert reconciler.tick() is not None      # 首次（last_at=0）执行
    clock["now"] += 10
    assert reconciler.tick() is None          # 未到 60s
    clock["now"] += 60
    assert reconciler.tick() is not None
