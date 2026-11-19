# -*- coding: utf-8 -*-
"""K6③ 验收：急停必须持久化（跨进程重启仍处于停机态）。"""
from __future__ import annotations

import pytest

import config
from core.gov_compat import gov
from broker.sim_broker import SimBroker
from core.account import TradingAccount
from live.errors import KillSwitchActive
from live.idempotency import IdempotencyStore
from live.kill_switch import KillSwitch
from live.live_trader import LiveTrader
from live.reconciliation import Reconciler


def _bar():
    return {"close": 10.0, "warmup_ok": True, "data_asof_date": "2026-11-12",
            "price_adjust": "qfq", "date": "2026-11-12"}


def _trader(tmp_path, flag_file, account=None, broker=None):
    account = account or TradingAccount(1_000_000.0, run_mode="live_sim")
    broker = broker or SimBroker(cash=1_000_000.0)
    return LiveTrader(
        broker, account=account, mode="live_sim", simulated=True,
        store=IdempotencyStore(path=tmp_path / "ids.json"),
        kill_switch=KillSwitch(flag_file=flag_file),
        reconciler=Reconciler(account, broker, state_file=tmp_path / "recon.json"),
        freshness_fn=lambda **_: True, first_order_confirmed=True)


def test_kill_switch_config_persists():
    conf = gov("LIVE_SAFETY")["kill_switch"]
    assert conf["persist"] is True
    assert conf["manual_clear_token"]                 # 解除需要人工口令


def test_flag_file_survives_restart(tmp_path):
    flag = tmp_path / "KILL_SWITCH"
    first = KillSwitch(flag_file=flag)
    assert first.is_active() is False
    first.trigger("回撤超限")
    assert first.is_active() and flag.exists()
    # 「重启」：新实例读同一标志文件，仍是停机态
    restarted = KillSwitch(flag_file=flag)
    assert restarted.is_active() is True
    assert "回撤超限" in (restarted.state() or {}).get("reason", "")


def test_live_trader_rejects_all_orders_after_restart(tmp_path):
    flag = tmp_path / "KILL_SWITCH"
    KillSwitch(flag_file=flag).trigger("manual")
    trader = _trader(tmp_path, flag)              # 模拟崩溃重启后的新执行器
    for direction in ("buy", "sell", "short", "cover"):
        out = trader.submit_order("600519", direction, 100, 10.0, _bar())
        assert out["status"] == "rejected" and out["stage"] == "kill_switch"
    assert len(trader.broker.orders) == 0


def test_clear_requires_manual_token(tmp_path):
    flag = tmp_path / "KILL_SWITCH"
    ks = KillSwitch(flag_file=flag)
    ks.trigger("manual")
    with pytest.raises(KillSwitchActive):
        ks.clear("随便写")
    assert ks.is_active()
    assert ks.clear("MANUAL_CONFIRM") is True
    assert not ks.is_active()
    trader = _trader(tmp_path, flag)              # 解除后恢复正常
    assert trader.buy("600519", 100, 10.0, _bar())["status"] == "accepted"


# ==================== 12.15 急停执行序列（仿真） ====================
class _CaptureNotifier:
    def __init__(self):
        self.sent = []

    def on_kill_switch(self, reason):
        self.sent.append(reason)
        return 1


def test_panic_cancels_open_orders_and_audits(tmp_path):
    from broker.base_broker import BrokerOrder
    from live.audit_log import AuditLog
    from live.kill_switch import PanicController

    broker = SimBroker(cash=1_000_000.0)
    broker.connect()
    broker.place_order(BrokerOrder(client_order_id="open-1", symbol="600519",
                                   direction="buy", volume=100, price=10.0))
    flag = tmp_path / "KILL_SWITCH"
    ks = KillSwitch(flag_file=flag)
    audit = AuditLog(dir_path=tmp_path / "audit_logs", account_id="6222021234",
                     strategy_id="s1")
    notifier = _CaptureNotifier()
    panic = PanicController(ks, broker, notifier, audit)

    out = panic.panic("模拟急停测试")
    assert "open-1" in out["cancelled"]
    assert broker.query_order("open-1").status == "canceled"
    assert ks.is_active() and flag.exists()          # 冻结并落盘
    assert notifier.sent and "模拟急停测试" in notifier.sent[0]
    events = [r["event"] for r in audit.export()]
    assert "kill_switch" in events and audit.verify_chain() is True
    assert broker.connected is False                 # ④ 断开连接

    # ① 冻结策略：急停后任何新报单都被拒
    trader = _trader(tmp_path, flag)
    assert trader.buy("600519", 100, 10.0, _bar())["stage"] == "kill_switch"


def test_panic_liquidate_is_opt_in(tmp_path):
    from live.kill_switch import PanicController

    broker = SimBroker(cash=1_000_000.0)
    broker.connect()
    calls = []
    panic = PanicController(KillSwitch(flag_file=tmp_path / "K"),
                            broker, liquidate_fn=lambda: calls.append("liq") or [])
    panic.execute(reason="default")                  # panic_liquidate 默认 False
    assert calls == []
    panic.execute(reason="explicit", liquidate=True)
    assert calls == ["liq"]
