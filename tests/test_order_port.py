# -*- coding: utf-8 -*-
"""K5/K6/K7/K8 验收：出站唯一收口、模式守卫、衍生品硬拦、首单限额。"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

import config
from core.gov_compat import gov
from broker.sim_broker import SimBroker
from core.account import Position, TradingAccount
from live import mode_guard
from live.errors import (DerivativeLiveForbidden, FirstOrderLimitError,
                         ModeGuardError, SilentFallbackError)
from live.idempotency import IdempotencyStore
from live.kill_switch import KillSwitch
from live.live_trader import LiveTrader
from live.reconciliation import Reconciler

ROOT = Path(__file__).resolve().parent.parent


def _bar():
    return {"close": 10.0, "warmup_ok": True, "data_asof_date": "2026-11-12",
            "price_adjust": "qfq", "date": "2026-11-12"}


def _trader(tmp_path, broker=None, simulated=True, mode="live_sim",
            first_order_confirmed=True, account=None):
    account = account or TradingAccount(1_000_000.0, run_mode=mode)
    broker = broker or SimBroker(cash=1_000_000.0)
    return LiveTrader(
        broker, account=account, mode=mode, simulated=simulated,
        store=IdempotencyStore(path=tmp_path / "ids.json"),
        kill_switch=KillSwitch(flag_file=tmp_path / "KILL"),
        reconciler=Reconciler(account, broker, state_file=tmp_path / "recon.json"),
        freshness_fn=lambda **_: True, first_order_confirmed=first_order_confirmed)


# ==================== K9 / K5 配置面 ====================

def test_live_safety_and_order_port_keys():
    assert len(gov("LIVE_SAFETY")) >= 9
    assert len(gov("ORDER_PORT_CONFORMANCE")) >= 12
    assert gov("ORDER_PORT_CONFORMANCE")["single_submit_port"] == \
        "live/live_trader.py::submit_order"
    points = gov("SIGNAL_EGRESS_CONFORMANCE")["signal_egress_points"]
    assert points == ["place_order", "monitor_push", "report_plan",
                      "investor_disclosure", "live_order_submit",
                      "watch_only_live_push"]
    assert gov("ORDER_PORT_CONFORMANCE")["egress_points"] == \
        ["live_order_submit", "watch_only_live_push"]


def test_no_sdk_import_outside_broker_dir():
    """K5②：broker/ 之外禁止 import xtquant / ths_ptrade / CTP SDK。"""
    sdk = set(gov("ORDER_PORT_CONFORMANCE")["sdk_modules"])
    offenders = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if rel.parts[0] in ("broker", ".venv", "venv") or "site-packages" in rel.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            hit = sorted(set(names) & sdk)
            if hit:
                offenders.append(f"{rel}: {hit}")
    assert offenders == []


def test_broker_adapter_has_no_decision_layers():
    """K5①：适配器只实现发单原语，不得 import 闸门/风控/对账决策层。"""
    for name in ("base_broker.py", "sim_broker.py"):
        tree = ast.parse((ROOT / "broker" / name).read_text(encoding="utf-8"))
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(a.name for a in node.names)
        assert not [m for m in modules if m.startswith(("core.signal_gate",
                                                        "core.risk",
                                                        "live.reconciliation"))]


def test_only_live_trader_calls_broker_place_order():
    """K5①：报单唯一收口在 live/live_trader.py。"""
    hits = []
    for path in ROOT.rglob("*.py"):
        parts = path.relative_to(ROOT).parts
        if "site-packages" in parts or parts[0] == "tests":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "broker.place_order(" in text:
            hits.append(str(path.relative_to(ROOT)))
    assert hits == ["live/live_trader.py"]


# ==================== K7 衍生品实盘硬拦 ====================

def test_derivative_live_order_hard_blocked(tmp_path):
    live_broker = SimBroker(cash=1_000_000.0)          # connected / live_ready
    trader = _trader(tmp_path, broker=live_broker, simulated=False, mode="live")
    out = trader.submit_order("600519", "buy", 10, 10.0, _bar(),
                              product_type="snowball")
    assert out["status"] == "rejected" and out["stage"] == "derivatives_forbidden"
    assert len(live_broker.orders) == 0
    with pytest.raises(DerivativeLiveForbidden):
        trader._precheck("buy", "trs", _bar(), "600519")


def test_derivative_simulation_allowed(tmp_path):
    trader = _trader(tmp_path, simulated=True)          # 仿真放行
    out = trader.submit_order("600519", "buy", 10, 10.0, _bar(),
                              product_type="snowball")
    assert out["status"] == "accepted"


# ==================== K8 首笔实盘限额 ====================

def test_first_order_notional_limit(tmp_path):
    trader = _trader(tmp_path, first_order_confirmed=False)
    big = trader.buy("600519", 2000, 10.0, _bar())      # 20,000 > 10,000
    assert big["status"] == "rejected" and big["stage"] == "first_order_limit"
    small = trader.buy("600519", 100, 10.0, _bar())     # 1,000 放行
    assert small["status"] == "accepted"
    assert gov("LIVE_SAFETY")["first_live_order_max_notional"] == 10000.0


def test_first_order_limit_raises_type():
    with pytest.raises(FirstOrderLimitError):
        raise FirstOrderLimitError("首单超限")


# ==================== K6 模式守卫 ====================

def test_silent_mode_fallback_forbidden():
    broker = SimBroker(cash=1_000_000.0, connected=False)
    with pytest.raises(SilentFallbackError):
        LiveTrader(broker, mode="live", simulated=False)
    assert gov("LIVE_SAFETY")["forbid_silent_mode_fallback"] is True


def test_mode_change_requires_flat():
    pos = Position(symbol="600519", market="cn_stock", volume=100,
                   avg_cost=10.0, last_price=10.0)
    with pytest.raises(ModeGuardError):
        mode_guard.assert_mode_change_allowed("backtest",
                                              positions={"600519": pos},
                                              current="live")
    with pytest.raises(ModeGuardError):
        mode_guard.assert_mode_change_allowed("paper", open_orders=[{"client_order_id": "x"}])
    mode_guard.assert_mode_change_allowed("backtest", positions={}, open_orders=[])
    assert gov("LIVE_SAFETY")["mode_change_requires_flat"] is True


def test_mode_label_written_on_order_and_reports():
    assert mode_guard.mode_label("live") == "[LIVE]"
    mode_guard.assert_mode_labeled({"mode": "live"})
    with pytest.raises(ModeGuardError):
        mode_guard.assert_mode_labeled({"symbol": "600519"})
    assert gov("LIVE_SAFETY")["mode_label_required"] is True
    assert gov("ORDER_PORT_CONFORMANCE")["mode_label_on_order"] is True


def test_order_record_carries_mode(tmp_path):
    trader = _trader(tmp_path)
    out = trader.buy("600519", 100, 10.0, _bar())
    assert out["mode"] == "live_sim"
    assert "mode" in trader.orders[-1]


# ==================== K6④ CLI 切模式须无仓（含降级） ====================

def _isolate_ledgers(monkeypatch, tmp_path):
    """把账本读路径圈到临时目录，避免读到本机运行态。"""
    monkeypatch.setattr(config, "DATA_CACHE_DIR", tmp_path)
    safety = gov("LIVE_SAFETY")
    safety["idempotency"] = dict(safety["idempotency"],
                                 persist_path=str(tmp_path / "order_ids.json"))
    monkeypatch.setattr(config, "LIVE_SAFETY", safety)
    return tmp_path


def _set_mode_args(to="backtest"):
    from types import SimpleNamespace
    return SimpleNamespace(to=to, strategy=None, confirm=True)


def test_cli_set_mode_blocked_by_open_position(tmp_path, monkeypatch):
    from cli_commands import qi
    root = _isolate_ledgers(monkeypatch, tmp_path)
    (root / "paper_account.json").write_text(
        json.dumps({"positions": [{"symbol": "600519", "volume": 100}],
                    "short_positions": [], "orders": []}, ensure_ascii=False),
        encoding="utf-8")
    assert qi.cmd_set_mode(_set_mode_args("backtest")) == 2


def test_cli_set_mode_blocked_by_pending_order(tmp_path, monkeypatch):
    from cli_commands import qi
    root = _isolate_ledgers(monkeypatch, tmp_path)
    (root / "paper_account.json").write_text(
        json.dumps({"positions": [], "short_positions": [],
                    "orders": [{"order_id": "P1", "symbol": "600519",
                                "status": "pending"}]}, ensure_ascii=False),
        encoding="utf-8")
    assert qi.cmd_set_mode(_set_mode_args("paper")) == 2


def test_cli_set_mode_fails_closed_on_broken_ledger(tmp_path, monkeypatch):
    from cli_commands import qi
    root = _isolate_ledgers(monkeypatch, tmp_path)
    (root / "paper_account.json").write_text("{broken", encoding="utf-8")
    assert qi.cmd_set_mode(_set_mode_args("backtest")) == 2


def test_cli_set_mode_flat_passes(tmp_path, monkeypatch):
    from cli_commands import qi
    from core import cli_gate
    root = _isolate_ledgers(monkeypatch, tmp_path)
    (root / "paper_account.json").write_text(
        json.dumps({"positions": [], "short_positions": [],
                    "orders": []}), encoding="utf-8")
    monkeypatch.setattr(cli_gate, "enter_mode",
                        lambda *a, **k: {"ok": True, "to": "backtest"})
    assert qi.cmd_set_mode(_set_mode_args("backtest")) == 0
