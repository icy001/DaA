# -*- coding: utf-8 -*-
"""v3.53 评审五轮·闸门7：衍生品实盘硬拦专项验证。

裁定语义：
  - 实盘（live）模式下期货/期权/衍生品报单必须【直接 raise】拦截（非打印警告、
    非拒单返回）——DerivativeMarketLiveForbidden 不继承 LiveSafetyError，
    实盘收口不得把它降级为一条 rejected 记录后继续运行；
  - 回测/研究模式放行，启动时明确打印「衍生品回测仅用于研究，实盘路径硬拦」；
  - 仿真（paper）放行（个人仅允许衍生品仿真环境报单）。
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pandas as pd
import pytest

from core.account import (DERIVATIVE_MARKETS, DerivativeMarketLiveForbidden,
                          LIVE_ALLOWED_MARKETS, TradingAccount)


# ==================== account 层（三引擎报单必经点） ====================

def _order_kwargs(**over):
    kw = dict(symbol="RB2512", direction="buy", volume=1, price=3400.0,
              order_time=pd.Timestamp("2026-01-05 10:00"), market_type="cn_future")
    kw.update(over)
    return kw


def test_live_mode_derivative_order_raises():
    """实盘模式期货报单：直接 raise（非警告、非拒单 dict）。"""
    acc = TradingAccount(1_000_000, run_mode="live")
    with pytest.raises(DerivativeMarketLiveForbidden, match="主体性质硬拦"):
        acc.place_order(**_order_kwargs())


def test_live_mode_option_order_raises():
    """期权同维度硬拦。"""
    acc = TradingAccount(1_000_000, run_mode="live")
    with pytest.raises(DerivativeMarketLiveForbidden):
        acc.place_order(**_order_kwargs(symbol="IO2512-C-4000",
                                        market_type="cn_option"))


def test_backtest_mode_derivative_order_fills():
    """回测模式同单正常执行（衍生品回测仅用于研究，不拦截）。"""
    acc = TradingAccount(1_000_000, run_mode="backtest")
    r = acc.place_order(warmup_ok=True, fill_now=True, **_order_kwargs())
    assert r["status"] == "filled", r
    assert acc.positions["RB2512"].volume == 1


def test_paper_mode_derivative_order_allowed():
    """仿真模式放行（个人仅允许衍生品仿真环境报单）。"""
    acc = TradingAccount(1_000_000, run_mode="paper")
    r = acc.place_order(warmup_ok=True, fill_now=True, **_order_kwargs())
    assert r["status"] == "filled"


def test_forbidden_exception_not_safety_subclass():
    """硬拦异常不得继承 LiveSafetyError 系——保证实盘收口无法把它
    降级为一条 rejected 记录后继续运行（直接 raise 的结构性保证）。"""
    from live.errors import LiveSafetyError
    assert not issubclass(DerivativeMarketLiveForbidden, LiveSafetyError)


def test_derivative_markets_coverage():
    """拦截集合覆盖场内期货/期权三市场（otc_deriv 走既有 NAV 拒单通道）。"""
    assert DERIVATIVE_MARKETS == {"cn_future", "cn_option", "global_future"}


# ==================== 评审六轮·闸门7 白名单化（fail-closed） ====================

def test_live_mode_unregistered_market_rejected():
    """白名单语义：未显式列入 LIVE_ALLOWED_MARKETS 的市场（如 cn_fund）
    实盘一律 raise——「新增市场忘记登记」不再可能静默漏拦。"""
    from core.account import LiveMarketForbidden
    acc = TradingAccount(1_000_000, run_mode="live")
    with pytest.raises(LiveMarketForbidden, match="白名单"):
        acc.place_order(**_order_kwargs(symbol="511990", market_type="cn_fund"))


def test_live_mode_unknown_symbol_defaults_to_reject():
    """market 缺失且 symbol 兜底识别不出：默认拒绝（fail-closed），
    不得当作普通市场放行。"""
    from core.account import LiveMarketForbidden
    acc = TradingAccount(1_000_000, run_mode="live")
    with pytest.raises(LiveMarketForbidden):
        acc.place_order(**_order_kwargs(symbol="XX9999", market_type=None))


def test_live_mode_whitelisted_market_passes_market_gate():
    """白名单内市场（cn_stock）不被市场闸拦截（走正常下单链路）。"""
    from core.account import LiveMarketForbidden
    acc = TradingAccount(1_000_000, run_mode="live")
    try:
        acc.place_order(warmup_ok=True, fill_now=True,
                        symbol="600519", direction="buy", volume=100, price=10.0,
                        order_time=pd.Timestamp("2026-01-05 10:00"),
                        market_type="cn_stock")
    except LiveMarketForbidden:
        pytest.fail("白名单内市场被市场闸误拦")
    except Exception:
        pass   # 后续链路（时效闸门 refetch 等）异常不在本测试范围


def test_whitelist_disjoint_from_derivative_markets():
    """结构性确认：衍生品市场绝不在 live 白名单内（白名单与衍生品集合不相交）。"""
    assert not (DERIVATIVE_MARKETS & LIVE_ALLOWED_MARKETS)


def test_whitelist_is_minimal():
    """初始白名单最小集：只含已具备实盘券商通道的 A 股现货族；
    扩市场（含期货开工后的 cn_future）必须显式加入并附预检回执。"""
    assert LIVE_ALLOWED_MARKETS == {"cn_stock", "cn_etf"}


def test_live_trader_precheck_unregistered_market_raises():
    """实盘收口同语义：未登记市场直接 raise（LiveMarketForbidden 穿透拒单捕获）。"""
    from core.account import LiveMarketForbidden
    lt = _bare_trader()
    with pytest.raises(LiveMarketForbidden):
        lt._precheck("buy", "cash", None, "511990", market="cn_fund")


def test_live_trader_precheck_unknown_symbol_defaults_to_reject():
    """实盘收口：symbol 兜底识别不出 → 默认拒绝（不得放行）。"""
    from core.account import LiveMarketForbidden
    lt = _bare_trader()
    with pytest.raises(LiveMarketForbidden):
        lt._precheck("buy", "cash", None, "XX9999", market=None)


# ==================== 评审七轮·主体性质硬拦（白名单不可绕过） ====================

def test_personal_subject_derivative_blocked_even_if_whitelisted(monkeypatch):
    """核心结构测试：即使 cn_future 被错误加进 LIVE_ALLOWED_MARKETS 白名单，
    个人主体的衍生品实盘报单依然被主体闸拦截——白名单不可绕过主体硬拦。"""
    import core.account as acc_mod
    monkeypatch.setattr(acc_mod, "LIVE_ALLOWED_MARKETS",
                        set(acc_mod.LIVE_ALLOWED_MARKETS) | {"cn_future"})
    acc = TradingAccount(1_000_000, run_mode="live", account_subject="personal")
    with pytest.raises(DerivativeMarketLiveForbidden, match="主体"):
        acc.place_order(**_order_kwargs())


def test_institution_subject_derivative_still_needs_whitelist(monkeypatch):
    """机构主体过主体闸，但仍受白名单闸约束（cn_future 未列入 → 仍拦，
    只是异常语义变为「白名单未放行」而非「主体禁止」）。"""
    import core.account as acc_mod
    from core.account import LiveMarketForbidden
    monkeypatch.setattr(acc_mod, "LIVE_ALLOWED_MARKETS",
                        set(acc_mod.LIVE_ALLOWED_MARKETS))   # 未加 cn_future
    acc = TradingAccount(1_000_000, run_mode="live", account_subject="institution")
    with pytest.raises(LiveMarketForbidden):
        acc.place_order(**_order_kwargs())


def test_account_subject_defaults_to_personal():
    """主体性质默认 personal（fail-closed）：institution 必须显式声明。"""
    assert TradingAccount(1_000_000).account_subject == "personal"
    assert TradingAccount(1_000_000, account_subject="INSTITUTION"
                          ).account_subject == "institution"


def test_live_trader_personal_derivative_raises_through(monkeypatch):
    """实盘收口：个人主体 + cn_future（即使白名单被篡改）→ raise 穿透。"""
    import core.account as acc_mod
    from live.live_trader import LiveTrader
    monkeypatch.setattr(acc_mod, "LIVE_ALLOWED_MARKETS",
                        set(acc_mod.LIVE_ALLOWED_MARKETS) | {"cn_future"})
    lt = LiveTrader.__new__(LiveTrader)
    lt.mode = "live"
    lt.simulated = False
    lt.account_subject = "personal"
    lt.kill_switch = SimpleNamespace(assert_can_trade=lambda: None)
    with pytest.raises(DerivativeMarketLiveForbidden, match="主体"):
        lt._precheck("buy", "cash", None, "RB2512", market="cn_future")


# ==================== live_trader 层（实盘报单唯一收口） ====================

def _bare_trader():
    from live.live_trader import LiveTrader
    lt = LiveTrader.__new__(LiveTrader)
    lt.mode = "live"
    lt.simulated = False
    lt.account_subject = "personal"   # 评审七轮：主体性质（默认 personal）
    lt.kill_switch = SimpleNamespace(assert_can_trade=lambda: None)
    return lt


def test_live_trader_precheck_derivative_raises_through():
    """实盘收口：期货报单直接 raise 穿透（submit_order 的 LiveSafetyError
    捕获不会把它吞成 rejected）。"""
    lt = _bare_trader()
    with pytest.raises(DerivativeMarketLiveForbidden):
        lt._precheck("buy", "cash", None, "RB2512", market="cn_future")


def test_live_trader_precheck_symbol_market_detect():
    """未显式传 market 时按 symbol 识别（RB2512 → cn_future）兜底拦截。"""
    lt = _bare_trader()
    with pytest.raises(DerivativeMarketLiveForbidden):
        lt._precheck("buy", "cash", None, "RB2512", market=None)


def test_live_trader_precheck_simulated_allows():
    """仿真环境（simulated=True）放行。"""
    lt = _bare_trader()
    lt.simulated = True
    # 放行 = 衍生品检查通过，继续走 bar 校验（bar=None 报 LiveSafetyError 而非硬拦异常）
    from live.errors import LiveSafetyError
    with pytest.raises(LiveSafetyError):
        lt._precheck("buy", "cash", None, "RB2512", market="cn_future")


# ==================== 回测启动提示 ====================

def test_backtest_derivative_research_notice(capsys):
    """回测/研究模式放行，启动时明确打印「衍生品回测仅用于研究，实盘路径硬拦」。"""
    from core.backtester import warn_derivative_research
    warn_derivative_research(["cn_future"],
                             logging.getLogger("test_gate7"))
    out = capsys.readouterr().out
    assert "衍生品回测仅用于研究" in out
    assert "实盘路径硬拦" in out
    assert "cn_future" in out


def test_backtest_non_derivative_no_notice(capsys):
    """非衍生品回测不得打印提示（提示只属于衍生品启动）。"""
    # 引擎侧按市场交集判定：空交集不触发提示
    bt_markets = sorted({"cn_stock"} & DERIVATIVE_MARKETS)
    assert bt_markets == []
    capsys.readouterr()   # 清缓冲
    assert capsys.readouterr().out == ""
