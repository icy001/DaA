# -*- coding: utf-8 -*-
"""美股治理面专项测试（v3.54 美股日线预检轮 + 补测轮，2026-11-26）。

评审裁定口径钉死：
  - 事件源选③：自建人工登记事件表（manual_events），事件必须来自官方披露，
    禁止带 token/付费黑箱源；已登记标的（AAPL/TSLA）放行走自建双价出口，
    未登记标的（含后续新增）保持 fail-closed raise 禁止降级跑回测
    （闸必须挡在路由之前——DataRouter 适配器路径曾绕过出口闸，实测 AAPL
    经 router 直连成功、TSLA 失败才落老链路）
  - 拆股强制解释线 50%（适配美股高波动）、事件日核验线 5% 不变
  - 补测①夏令时/冬令时：美东 9:30 开盘对应北京时间 21:30（夏令时）/22:30
    （冬令时），收盘对应次日 4:00/5:00（zoneinfo 权威库程序化换算）
  - 补测② T+0 回转：当日开仓后立即平仓不报错，无 A 股式 T+1 冻结残留
  - 补测③ 双价恒等式 <1e-10、事件日残差 <5%、无事件 <50% 不报错/≥50% raise
  - qty_step=1 无整手限制、费用逐项（佣金 0.0049/股 最低 0.99 双边
    + SEC 卖出 0.00278% + TAF 卖出 0.000166/股 最低 0.01）
  - USD 计价、固定汇率 7.20 折人民币

缓存纪律：合成帧测试一律禁写缓存（_read_cache→None / _save_cache→no-op），
禁止污染真实 data_cache（此前已有 mock 帧污染分钟缓存的事故）。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from core.account import TradingAccount
from core.data_fetcher import DataFetcher, JumpAuditError

NY = ZoneInfo("America/New_York")
CN = ZoneInfo("Asia/Shanghai")


# ==================== 治理面断言 ====================

def test_us_conformance_governance_block():
    """治理面断言：manual_events 登记 + 拆股线 50% + 核验线 5% + qty_step + 汇率。"""
    conf = getattr(config, "US_STOCK_CONFORMANCE")
    assert conf["events_source"] == {}, "事件源穷举无果必须显式登记为空（非缺省漏登）"
    assert conf["events_unavailable_action"] == "raise"
    # 选③：人工登记事件表（官方披露、逐位核对；AAPL 除净 2026-11-12 $0.27）
    assert conf["manual_events_mode"] == "raise_unlisted"
    assert "AAPL" in conf["manual_events"] and "TSLA" in conf["manual_events"]
    aapl_ev = conf["manual_events"]["AAPL"]
    assert aapl_ev and aapl_ev[0]["ex_date"] == "2026-11-12"
    assert float(aapl_ev[0]["div"]) == 0.27
    assert aapl_ev[0]["type"] == "cash_dividend"
    assert aapl_ev[0].get("source"), "manual_events 每条必须带官方披露 source 标注"
    ja = conf["jump_audit"]
    assert float(ja["threshold"]) == 0.05            # 事件日核验线不变
    assert float(ja["threshold_split"]) == 0.50      # 拆股线放宽（评审裁定）
    assert conf["qty_step"] == 1 and conf["t_plus"] == 0
    assert conf["currency"] == "USD" and float(conf["fx_fixed_cny"]) == 7.20
    # MARKETS 基础配置同口径
    rule = config.get_market_config("us_stock")
    assert int(rule["qty_step"]) == 1 and int(rule["t_plus"]) == 0
    assert float(rule["commission_per_share"]) == 0.0049
    assert float(rule["commission_min"]) == 0.99
    assert float(rule["sec_fee_sell"]) == 0.0000278
    assert float(rule["taf_fee_sell"]) == 0.000166 and float(rule["taf_min"]) == 0.01
    assert rule.get("price_limit") is None            # 无涨跌停


def test_us_commission_itemized():
    """费用逐项对账（评审要求全部实测对账）：
    买入仅佣金（单笔最低生效）；卖出 = 佣金 + SEC + TAF（单边、含最低）。"""
    acc = TradingAccount(1_000_000, run_mode="backtest")
    fee_buy = float(acc.calc_commission("AAPL", "buy", 200.0, 100,
                                        market_type="us_stock", is_open=True))
    assert fee_buy == pytest.approx(0.99, abs=0.005)   # max(100×0.0049, 0.99)
    fee_sell = float(acc.calc_commission("AAPL", "sell", 200.0, 100,
                                         market_type="us_stock", is_open=False))
    assert fee_sell == pytest.approx(0.99 + 20000 * 0.0000278
                                     + max(100 * 0.000166, 0.01), abs=0.005)
    # 买 1 股佣金触发最低 0.99；qty_step=1 放行
    res = acc.place_order(symbol="AAPL", direction="buy", volume=1, price=200.0,
                          market_type="us_stock", data=pd.DataFrame(),
                          order_time="2026-11-20", warmup_ok=True)
    assert res["status"] != "rejected", res


# ==================== 补测①：夏令时/冬令时换算（zoneinfo 权威库） ====================

def test_us_dst_winter_conversions():
    """补测①（离线换算权威）：2026 夏令时切换日 3/8、冬令时切换日 11/1。

    美东 9:30 开盘 → 北京 21:30（夏令时）/22:30（冬令时）；
    16:00 收盘 → 北京次日 4:00（夏令时）/5:00（冬令时）。
    """
    # 切换日本体：3/8 9:30 已在 EDT（UTC-4，切换发生在当地 2:00）
    open_edt = datetime(2026, 3, 8, 9, 30, tzinfo=NY)
    assert open_edt.utcoffset().total_seconds() == -4 * 3600
    assert open_edt.astimezone(CN).strftime("%Y-%m-%d %H:%M") == "2026-03-08 21:30"
    close_edt = datetime(2026, 3, 8, 16, 0, tzinfo=NY)
    assert close_edt.astimezone(CN).strftime("%Y-%m-%d %H:%M") == "2026-03-09 04:00"
    # 11/1 9:30 已回落 EST（UTC-5，切换发生在当地 2:00）
    open_est = datetime(2026, 11, 1, 9, 30, tzinfo=NY)
    assert open_est.utcoffset().total_seconds() == -5 * 3600
    assert open_est.astimezone(CN).strftime("%Y-%m-%d %H:%M") == "2026-11-01 22:30"
    close_est = datetime(2026, 11, 1, 16, 0, tzinfo=NY)
    assert close_est.astimezone(CN).strftime("%Y-%m-%d %H:%M") == "2026-11-02 05:00"
    # 治理面 tz 登记与权威库一致
    assert str(config.US_STOCK_CONFORMANCE["tz"]) == "America/New_York"


# ==================== 补测②：T+0 当日开平 ====================

def test_us_t0_roundtrip_same_day():
    """补测②：当日开仓后立即平仓——不触发持仓不足/T+1 冻结报错，
    持仓归零、资金与逐项手续费计算正确（买入 0.99 + 卖出 1.5626）。"""
    acc = TradingAccount(1_000_000, run_mode="backtest")
    px, qty = 200.0, 100
    r_buy = acc.place_order(symbol="AAPL", direction="buy", volume=qty, price=px,
                            market_type="us_stock", data=pd.DataFrame(),
                            order_time="2026-11-20", warmup_ok=True)
    assert r_buy["status"] != "rejected", r_buy
    pos = acc.get_position("AAPL")
    assert pos is not None and pos.volume == qty
    assert pos.frozen_volume == 0, "T+0 市场不得有 T+1 冻结残留"
    r_sell = acc.place_order(symbol="AAPL", direction="sell", volume=qty, price=px,
                             market_type="us_stock", data=pd.DataFrame(),
                             order_time="2026-11-20", warmup_ok=True)
    assert r_sell["status"] != "rejected", f"T+0 当日平仓被拒: {r_sell}"
    pos_after = acc.get_position("AAPL")
    assert pos_after is None or pos_after.volume == 0
    # 费用以 USD 逐项计、按治理面固定汇率 7.20 折 CNY 入账（账户基础货币 CNY；
    # 账户入账时费用按分位四舍五入，容差 5 分）
    fx = float(config.US_STOCK_CONFORMANCE["fx_fixed_cny"])
    fee_buy = 0.99
    fee_sell = 0.99 + px * qty * 0.0000278 + max(qty * 0.000166, 0.01)
    assert acc.cash == pytest.approx(1_000_000 - (fee_buy + fee_sell) * fx, abs=0.05)


# ==================== 补测③：双价恒等式 / 事件核验残差 / 拆股线 ====================

def _synthetic_raw(dates, closes, volume=1_000_000):
    """构造 akshare 原始返回形态的日线帧（英文标准列，_standardize 可直接消化）。"""
    n = len(dates)
    return pd.DataFrame({
        "date": list(dates),
        "open": [c * 1.001 for c in closes],
        "high": [c * 1.005 for c in closes],
        "low": [c * 0.995 for c in closes],
        "close": list(closes),
        "volume": [volume] * n,
        "amount": [c * volume for c in closes],
    })


@pytest.fixture()
def offline_fetcher(monkeypatch):
    """合成帧隔离：禁读/禁写真实缓存，_request 直接返回注入的合成原始帧。"""
    f = DataFetcher()
    holder = {"raw": None}
    monkeypatch.setattr(f, "_read_cache", lambda *a, **k: None)
    monkeypatch.setattr(f, "_save_cache", lambda *a, **k: None)
    monkeypatch.setattr(f, "_request", lambda func, *a, **k: holder["raw"])
    f._inject_raw = holder            # 测试体通过它注入合成帧
    return f


def _aapl_closes_with_div(prev_close=355.90, div=0.27):
    """2026-11-09~11-20 十个交易日；除净日 11-12 raw 精确连续（跳变=-div/prev）。"""
    closes = {d: prev_close for d in
              ("2026-11-09", "2026-11-10", "2026-11-11")}
    closes["2026-11-12"] = prev_close - div
    for d, c in (("2026-11-13", 357.1), ("2026-11-16", 358.2),
                 ("2026-11-17", 357.5), ("2026-11-18", 359.0),
                 ("2026-11-19", 360.2), ("2026-11-20", 359.4)):
        closes[d] = c
    return closes


def test_us_manual_events_gate_raise_unlisted(offline_fetcher):
    """选③放行边界：未登记标的（MSFT，含后续新增）双位 fail-closed raise——
    get_daily 顶层闸（挡 DataRouter 绕行）+ _fetch_us_stock_daily 出口闸。"""
    f = offline_fetcher
    with pytest.raises(RuntimeError, match="manual_events"):
        f.get_daily("MSFT", start_date="2026-11-09", end_date="2026-11-20",
                    market_type="us_stock")
    with pytest.raises(RuntimeError, match="manual_events"):
        f._fetch_us_stock_daily("MSFT", "2026-11-09", "2026-11-20", "")
    # us_etf（未登记事件的美股 ETF）同闸拒绝
    with pytest.raises(RuntimeError, match="manual_events"):
        f.get_daily("SPY", start_date="2026-11-09", end_date="2026-11-20",
                    market_type="us_etf")


def test_us_registered_dual_price_identity_and_event(offline_fetcher):
    """补测③（AAPL 真实登记事件回放）：已登记标的放行走自建双价——
    ① 逐 bar 恒等式 adj = raw × factor 偏差 <1e-10；② 除净日 raw 精确连续
    时事件核验通过、n_events_applied=1；③ attrs 双价/口径/币种标注齐全。"""
    f = offline_fetcher
    closes = _aapl_closes_with_div()
    dates = pd.to_datetime(list(closes.keys()))
    f._inject_raw["raw"] = _synthetic_raw(dates, list(closes.values()))
    df = f._fetch_us_stock_daily("AAPL", "2026-11-09", "2026-11-20", "")
    # 双价列与恒等式（逐 bar <1e-10）
    for c in ("open", "high", "low", "close"):
        assert f"raw_{c}" in df.columns
    assert "adj_factor" in df.columns
    ident = (df["close"] - df["raw_close"] * df["adj_factor"]).abs().max()
    assert ident < 1e-10, f"双价恒等式偏差 {ident}"
    # 除净日之后 factor>1（hfq 累计），之前=1；事件计数与标注
    assert float(df.loc["2026-11-11", "adj_factor"]) == pytest.approx(1.0)
    assert float(df.loc["2026-11-12", "adj_factor"]) > 1.0
    assert df.attrs["n_events_applied"] == 1
    assert df.attrs["dual_price"] is True
    assert df.attrs["adjust"] == "hfq_self_built"
    assert df.attrs["price_adjust"] == "hfq_self_built"
    assert df.attrs["currency"] == "USD"
    assert df.attrs["events_source"] == "manual_events"
    # adj 序列除净日连续（事件被因子完全吸收）
    adj_jump = float(df.loc["2026-11-12", "close"]) / float(df.loc["2026-11-11", "close"]) - 1
    assert abs(adj_jump) < 1e-10
    # raw 序列保留真实除净跳变（-0.27/355.90）
    raw_jump = float(df.loc["2026-11-12", "raw_close"]) / float(df.loc["2026-11-11", "raw_close"]) - 1
    assert raw_jump == pytest.approx(-0.27 / 355.90, abs=1e-12)


def test_us_event_residual_mismatch_raises(offline_fetcher):
    """补测③②反向：事件日 raw 跳变与登记事件幅度残差 ≥5% → JumpAuditError
    （漏登/错登被抓出，禁止生成被污染的 adj 序列）。"""
    f = offline_fetcher
    closes = _aapl_closes_with_div()
    closes["2026-11-12"] = 334.5        # 实际隔夜 -6.0%，预期 -0.0759%，残差≈5.9%
    f._inject_raw["raw"] = _synthetic_raw(pd.to_datetime(list(closes.keys())),
                                          list(closes.values()))
    with pytest.raises(JumpAuditError, match="核验失败"):
        f._fetch_us_stock_daily("AAPL", "2026-11-09", "2026-11-20", "")


def test_us_split_event_factor_and_verify(offline_fetcher, monkeypatch):
    """拆股事件路径（1拆4 合成回放）：raw 隔夜 -75% 与登记比例核验通过，
    factor=4、恒等式成立；比例与价格矛盾（残差≥5%）→ JumpAuditError。"""
    f = offline_fetcher
    us_conf = {**getattr(config, "US_STOCK_CONFORMANCE"),
               "manual_events": {"TEST": [{"ex_date": "2026-11-12",
                                           "type": "split", "ratio": 4.0,
                                           "source": "合成帧测试"}]}}
    monkeypatch.setattr(config, "US_STOCK_CONFORMANCE", us_conf)
    closes = {d: 400.0 for d in ("2026-11-09", "2026-11-10", "2026-11-11")}
    closes["2026-11-12"] = 100.0        # 精确 1拆4：-75%
    for d, c in (("2026-11-13", 100.5), ("2026-11-16", 101.0),
                 ("2026-11-17", 100.8), ("2026-11-18", 101.5),
                 ("2026-11-19", 102.0), ("2026-11-20", 101.2)):
        closes[d] = c
    f._inject_raw["raw"] = _synthetic_raw(pd.to_datetime(list(closes.keys())),
                                          list(closes.values()))
    df = f._fetch_us_stock_daily("TEST", "2026-11-09", "2026-11-20", "")
    assert df.attrs["n_events_applied"] == 1
    assert float(df.loc["2026-11-12", "adj_factor"]) == pytest.approx(4.0)
    assert float(df.loc["2026-11-12", "close"]) == pytest.approx(400.0, rel=1e-10)
    ident = (df["close"] - df["raw_close"] * df["adj_factor"]).abs().max()
    assert ident < 1e-10
    # 反向：登记 1拆4 但实际只跌 40% → 残差 35% ≥5% 核验线 → raise
    us_conf_bad = {**us_conf}
    monkeypatch.setattr(config, "US_STOCK_CONFORMANCE", us_conf_bad)
    closes["2026-11-12"] = 240.0        # -40%
    f._inject_raw["raw"] = _synthetic_raw(pd.to_datetime(list(closes.keys())),
                                          list(closes.values()))
    with pytest.raises(JumpAuditError, match="拆股事件日"):
        f._fetch_us_stock_daily("TEST", "2026-11-09", "2026-11-20", "")


def test_us_no_event_jump_band_vs_split_line(offline_fetcher, monkeypatch):
    """补测③③：无事件时单日涨跌幅 <50% 不报错（45% 落审计带、attrs 披露）；
    ≥50% 触发拆股强制解释线 JumpAuditError。"""
    f = offline_fetcher
    us_conf = {**getattr(config, "US_STOCK_CONFORMANCE"),
               "manual_events": {"TSLA": []}}     # TSLA 零事件登记
    monkeypatch.setattr(config, "US_STOCK_CONFORMANCE", us_conf)

    def frame_with_jump(jump):
        closes = [200.0, 200.5, 201.0]
        closes.append(closes[-1] * (1 + jump))
        closes += [closes[-1] * 1.001, closes[-1] * 0.999]
        return _synthetic_raw(pd.bdate_range("2026-11-09", periods=len(closes)), closes)

    # 45%：不 raise，落 5%~50% 审计带并写 attrs.audit_warnings
    f._inject_raw["raw"] = frame_with_jump(0.45)
    df = f._fetch_us_stock_daily("TSLA", "2026-11-09", "2026-11-20", "")
    assert len(df.attrs.get("audit_warnings") or []) == 1
    assert df.attrs["n_events_applied"] == 0
    # 60%：≥50% 拆股强制解释线 → JumpAuditError
    f._inject_raw["raw"] = frame_with_jump(0.60)
    with pytest.raises(JumpAuditError, match="50% 以上跳变"):
        f._fetch_us_stock_daily("TSLA", "2026-11-09", "2026-11-20", "")


def test_us_get_daily_registered_passes_top_gate(offline_fetcher):
    """顶层闸放行路径：已登记标的经 get_daily 走 dispatch 出口（不经 router），
    返回帧带双价标注；缓存名统一 none 口径（强制 raw 取数 + 自建因子）。"""
    f = offline_fetcher
    closes = _aapl_closes_with_div()
    f._inject_raw["raw"] = _synthetic_raw(pd.to_datetime(list(closes.keys())),
                                          list(closes.values()))
    monkey_call = {"n": 0}

    def _fake_fetch_daily(market, symbol, start, end, adjust):
        monkey_call["n"] += 1
        assert adjust == "none", "美股日线必须强制 raw 口径（缓存名统一 none）"
        return f._dispatch_daily(market, symbol, start, end, adjust)

    f._fetch_daily = _fake_fetch_daily
    df = f.get_daily("AAPL", start_date="2026-11-09", end_date="2026-11-20",
                     market_type="us_stock")
    assert monkey_call["n"] == 1
    assert df.attrs.get("dual_price") is True
    assert df.attrs.get("adjust") == "hfq_self_built"
    ident = (df["close"] - df["raw_close"] * df["adj_factor"]).abs().max()
    assert ident < 1e-10


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
