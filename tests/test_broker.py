# -*- coding: utf-8 -*-
"""12.1–12.4 验收：BrokerAdapter 抽象 + QMT/PTrade/CTP 适配器（全程仿真/假客户端）。"""
from __future__ import annotations

import pytest

from broker.base_broker import (ACCEPTED, BrokerAdapter, BrokerCredentialError,
                                 BrokerOrder, LIVE_TRADING_ENABLED,
                                 LiveTradingDisabled)
from broker.ctp_broker import CTPBroker, PenetrationTestHelper, SIMNOW_PRESET
from broker.ptrade_broker import PTradeBroker
from broker.qmt_broker import QMTBroker


class FakeClient:
    """三段适配器共用的假客户端（不触网、不触真实资金）。"""

    def __init__(self, login_ok: bool = True, timeout: bool = False):
        self.login_ok = login_ok
        self.timeout = timeout
        self._orders = []
        self._trades = []
        self._positions = {"600519": {"volume": 100.0, "available": 100.0,
                                      "avg_cost": 10.0}}

    def login(self):
        return self.login_ok

    def logout(self):
        return True

    def account(self):
        return {"cash": 1_000_000.0, "equity": 1_000_000.0, "available": 900_000.0}

    def positions(self):
        return {k: dict(v) for k, v in self._positions.items()}

    def quote(self, symbol):
        return {"price": 10.0, "last": 10.0, "bid": 9.99, "ask": 10.01}

    def order(self, client_order_id, symbol, direction, volume, price,
              order_type="market", offset=None):
        if self.timeout:
            raise TimeoutError("注入超时（券商可能已受理）")
        rec = {"client_order_id": client_order_id, "symbol": symbol,
               "direction": direction, "volume": volume, "price": price,
               "status": "accepted", "order_id": f"F{len(self._orders) + 1}"}
        self._orders.append(rec)
        self._trades.append({"client_order_id": client_order_id, "symbol": symbol,
                             "direction": direction, "volume": volume, "price": price})
        return rec

    def cancel(self, client_order_id):
        for rec in self._orders:
            if rec["client_order_id"] == client_order_id:
                rec["status"] = "canceled"
                return {"ok": True, "client_order_id": client_order_id}
        return {"ok": False, "reason": "未找到委托"}

    def orders(self):
        return [dict(r) for r in self._orders]

    def trades(self):
        return list(self._trades)


def _order(cid="c1"):
    return BrokerOrder(client_order_id=cid, symbol="600519", direction="buy",
                       volume=100.0, price=10.0)


# ==================== 抽象边界（K5） ====================
def test_adapters_are_primitives_only():
    for cls in (QMTBroker, PTradeBroker, CTPBroker):
        assert issubclass(cls, BrokerAdapter)
        for decision in ("submit_order", "check_open", "on_bar", "on_tick",
                         "place_order_or_decision"):
            assert not hasattr(cls, decision), f"{cls.__name__} 不得实现决策方法 {decision}"
        # 发单原语必须齐全
        for primitive in ("connect", "get_account", "get_positions", "get_quote",
                          "place_order", "cancel_order", "query_order"):
            assert callable(getattr(cls, primitive))


def test_code_level_live_switch_defaults_false():
    assert LIVE_TRADING_ENABLED is False


# ==================== QMT ====================
def test_qmt_missing_credentials_rejected():
    broker = QMTBroker(account_id="", password="", path="")
    with pytest.raises(BrokerCredentialError) as exc:
        broker.connect()
    assert "QMT_ACCOUNT_ID" in str(exc.value) and "QMT_PATH" in str(exc.value)


def test_qmt_without_sdk_or_session_fails_closed():
    broker = QMTBroker(account_id="123", password="pw", path="/tmp/qmt",
                       mode="simulation")
    with pytest.raises(RuntimeError):
        broker.connect()


def test_qmt_simulation_order_and_query():
    client = FakeClient()
    broker = QMTBroker(account_id="123", password="pw", path="/tmp/qmt",
                       mode="simulation", client=client)
    assert broker.connect() is True
    sent = broker.place_order(_order())
    assert sent.status == ACCEPTED and sent.broker_order_id == "F1"
    assert broker.query_order("c1").status == ACCEPTED
    assert broker.get_today_trades()[0]["client_order_id"] == "c1"
    assert broker.get_quote("600519")["price"] == 10.0


def test_qmt_timeout_returns_unknown_not_failure():
    broker = QMTBroker(account_id="123", password="pw", path="/tmp/qmt",
                       mode="simulation", client=FakeClient(timeout=True))
    broker.connect()
    sent = broker.place_order(_order())
    assert sent.status == "unknown" and "禁止盲目重发" in sent.message


def test_qmt_real_order_disabled_by_default():
    broker = QMTBroker(account_id="123", password="pw", path="/tmp/qmt",
                       mode="mini", client=FakeClient())
    broker.connected = True
    with pytest.raises(LiveTradingDisabled):
        broker.place_order(_order())


def test_qmt_a_share_rules():
    assert QMTBroker.min_order_volume("600519") == 100
    assert QMTBroker.min_order_volume("113001") == 10
    assert QMTBroker.min_order_volume("688001") == 200
    assert QMTBroker.price_cage("688001", 10.5, 10.0) == 10.2   # +2% 上限
    assert QMTBroker.price_cage("600519", 10.5, 10.0) == 10.5   # 主板无笼子
    assert QMTBroker.available_volume({"volume": 100, "frozen_volume": 40}) == 60


# ==================== PTrade ====================
def test_ptrade_missing_credentials_rejected():
    broker = PTradeBroker(server="", username="", password="", account_id="")
    with pytest.raises(BrokerCredentialError) as exc:
        broker.connect()
    assert "PTRADE_SERVER" in str(exc.value)


def test_ptrade_cloud_login_failure_is_error():
    broker = PTradeBroker(server="https://cloud", username="u", password="p",
                          account_id="a", client=FakeClient(login_ok=False))
    with pytest.raises(ConnectionError):
        broker.connect()


def test_ptrade_simulated_order():
    broker = PTradeBroker(server="https://cloud", username="u", password="p",
                          account_id="a", simulated=True, client=FakeClient())
    broker.connect()
    assert broker.place_order(_order()).status == ACCEPTED
    assert broker.schedule("monitor", "*/5 * * * *")["ok"] is False  # 假客户端不支持


# ==================== CTP ====================
def test_simnow_preset_is_complete():
    for key in ("trade_front", "market_front", "broker_id", "app_id", "auth_code"):
        assert SIMNOW_PRESET[key]


def test_ctp_uses_simnow_preset_by_default():
    broker = CTPBroker()
    assert broker.trade_front == SIMNOW_PRESET["trade_front"]
    assert broker.market_front == SIMNOW_PRESET["market_front"]
    assert broker.simulated is True and broker.live_ready is True


def test_ctp_missing_user_password_rejected():
    broker = CTPBroker(user_id="", password="")
    with pytest.raises(BrokerCredentialError) as exc:
        broker.connect()
    assert "CTP_USER_ID" in str(exc.value)


def test_penetration_helper_flags_simnow_defaults_for_live():
    helper = PenetrationTestHelper(SIMNOW_PRESET["app_id"], SIMNOW_PRESET["auth_code"],
                                   prod_code="", product_info="")
    report = helper.report(live=True)
    assert report["ok"] is False
    assert report["checks"]["app_id"] == "default"
    assert report["checks"]["prod_code"] == "missing"
    assert helper.report(live=False)["ok"] is True          # 仿真允许默认值


def test_ctp_live_with_default_penetration_params_refused():
    broker = CTPBroker(user_id="u", password="p", simnow=False, simulated=False,
                       client=FakeClient())
    with pytest.raises(BrokerCredentialError):
        broker.connect()


def test_ctp_simulation_order_and_offset():
    client = FakeClient()
    broker = CTPBroker(user_id="u", password="p", client=client)
    broker.connect()
    sent = broker.place_order(BrokerOrder(client_order_id="f1", symbol="rb2601",
                                          direction="buy", volume=1, price=3500))
    assert sent.status == ACCEPTED and sent.mode == "ctp_sim"
    assert broker.offset_for("rb2601", "buy") == "open"
    pos = broker.get_positions()["600519"]
    assert pos["today_volume"] == 0.0 and pos["yesterday_volume"] == 0.0


def test_ctp_margin_and_fee_rules():
    assert CTPBroker.margin_required(3500, 2, 10, 0.12) == 8400.0
    normal = CTPBroker.commission(3500, 2, 10, close_fee=3.0)
    today = CTPBroker.commission(3500, 2, 10, close_fee=3.0, close_today_fee=9.0,
                                 close_today=True)
    assert normal == 6.0 and today == 18.0
    assert CTPBroker.at_price_limit({"last": 110, "limit_up": 110}, "buy") is True
    assert CTPBroker.at_price_limit({"last": 90, "limit_down": 90}, "sell") is True
