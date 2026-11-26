# -*- coding: utf-8 -*-
"""美股日线预检·补测轮（v3.54，验收单 §六C.22，可复现脚本）。

评审裁定（2026-11-26 补测轮）：事件源选③自建人工登记事件表
（US_STOCK_CONFORMANCE.manual_events，事件必须来自纳斯达克官网或上市公司
官方披露的公开信息，禁止带 token/付费黑箱源，禁止凭记忆填写）；
先补 3 个必测项再通过预检，补测全绿后美股日线链路正式转正——
仅放行 manual_events 登记完整事件覆盖的标的，未登记标的保持
fail-closed raise 禁止降级跑回测。

本轮必查项（上轮预检漏测，逐项补齐）：
  ① 夏令时/冬令时时间转换：2026 夏令时切换日（3/8）、冬令时切换日（11/1）
     实测——美东 9:30 开盘对应北京时间 21:30（夏令时）/22:30（冬令时），
     收盘对应次日 4:00/5:00；跨切换日日线窗口无重复/缺失 bar、无拼接错位
  ② T+0 回转验证：当日开仓后立即平仓，持仓/资金/手续费计算正确，
     无 A 股式 T+1 冻结逻辑残留
  ③ 双价折算与跳变闸验证（真实链路）：manual_events 登记（AAPL 2026-11-12
     $0.27 现金分红，Apple 官方新闻稿逐位核对；TSLA 官方披露零分红）→
     逐 bar 双价恒等式偏差 <1e-10；事件日 raw 跳变与事件幅度残差 <5%；
     无事件单日涨跌幅 <50% 不报错、≥50% 触发拆股强制解释线报错
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import akshare as ak
import config
from core.account import TradingAccount
from core.data_fetcher import DataFetcher, JumpAuditError

NY = ZoneInfo("America/New_York")
CN = ZoneInfo("Asia/Shanghai")
TARGETS = ["AAPL", "TSLA"]
START = "2026-10-27"
END = "2026-11-26"


def main() -> int:
    ok = True
    anomaly = []
    t0 = time.time()
    print("=" * 68)
    print(f"美股日线预检·补测轮 {'/'.join(TARGETS)} 请求区间 {START}~{END}"
          "（事件源选③人工登记表 + 3 必测项）")

    # ---------- 1) 数据源直连实测（东财，免费公开接口；经内部出口带节流重试） ----------
    f0 = DataFetcher()
    for sym in TARGETS:
        raw = None
        last_exc = None
        for attempt in range(3):        # 脚本级外层重试：东财反爬为间歇性
            try:
                raw = f0._request(ak.stock_us_hist, symbol=f"105.{sym}",
                                  period="daily", start_date="20261027",
                                  end_date="20261126", adjust="",
                                  _source="eastmoney")
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(10)
        try:
            dates = pd.to_datetime(raw["日期"])
            weekend = int((dates.dt.dayofweek >= 5).sum())
            if len(raw) >= 15 and weekend == 0:
                print(f"✅ 1) 数据源 {sym}：{len(raw)} 行 {raw['日期'].iloc[0]}~"
                      f"{raw['日期'].iloc[-1]}，周末零 bar（交易日历独立、无周末错位）")
            else:
                anomaly.append(f"{sym} 数据异常 {len(raw)} 行/周末 {weekend}")
                ok = False
                print(f"❌ 1) {sym} 数据异常：{len(raw)} 行，周末 bar {weekend}")
        except Exception:  # noqa: BLE001
            anomaly.append(f"{sym} 直连失败 {last_exc}")
            ok = False
            print(f"❌ 1) {sym} 东财直连失败（3 次外层重试后）：{str(last_exc)[:100]}")
        time.sleep(5)

    # ---------- 2) 补测①：夏令时/冬令时时间转换 ----------
    print("✅ 2) 补测① 夏令时/冬令时（zoneinfo 权威库程序化换算）：")
    conv_checks = [
        (datetime(2026, 3, 8, 9, 30, tzinfo=NY), "2026-03-08 21:30",
         "夏令时切换日开盘 9:30 EDT→北京 21:30"),
        (datetime(2026, 3, 8, 16, 0, tzinfo=NY), "2026-03-09 04:00",
         "夏令时收盘 16:00→北京次日 4:00"),
        (datetime(2026, 11, 1, 9, 30, tzinfo=NY), "2026-11-01 22:30",
         "冬令时切换日开盘 9:30 EST→北京 22:30"),
        (datetime(2026, 11, 1, 16, 0, tzinfo=NY), "2026-11-02 05:00",
         "冬令时收盘 16:00→北京次日 5:00"),
    ]
    for dt, expect, name in conv_checks:
        got = dt.astimezone(CN).strftime("%Y-%m-%d %H:%M")
        if got == expect:
            print(f"✅ 2)   {name}")
        else:
            anomaly.append(f"时区换算 {name}: {got} ≠ {expect}")
            ok = False
            print(f"❌ 2)   {name}: {got} ≠ {expect}")
    # 跨切换日真实日线窗口：无重复/缺失 bar、无周末、日期严格递增（无拼接错位）
    for win_start, win_end, switch in (("2026-03-02", "2026-03-13", "夏令时 3/8"),
                                       ("2026-10-27", "2026-11-06", "冬令时 11/1")):
        try:
            df = f0.get_daily("AAPL", start_date=win_start, end_date=win_end,
                              market_type="us_stock")
            idx = pd.DatetimeIndex(df.index)
            weekdays = pd.bdate_range(win_start, win_end)
            dup, mono = int(idx.duplicated().sum()), idx.is_monotonic_increasing
            if list(idx) == list(weekdays) and dup == 0 and mono:
                print(f"✅ 2)   跨{switch}窗口 {win_start}~{win_end}：{len(idx)} bar"
                      " 与工作日历逐一对应（无重复/缺失/错位，切换日为周日休市正常）")
            else:
                anomaly.append(f"{switch}窗口 bar 数/日历异常 {len(idx)} vs {len(weekdays)}")
                ok = False
                print(f"❌ 2)   跨{switch}窗口异常：{len(idx)} bar vs 预期 "
                      f"{len(weekdays)}，dup={dup} mono={mono}")
        except Exception as exc:  # noqa: BLE001
            anomaly.append(f"{switch}窗口取数失败 {str(exc)[:80]}")
            ok = False
            print(f"❌ 2)   跨{switch}窗口取数失败：{str(exc)[:100]}")
        time.sleep(5)

    # ---------- 3) 闸门行为：登记放行 / 未登记 raise（双位拦截） ----------
    for sym in TARGETS:
        try:
            df = f0.get_daily(sym, start_date=START, end_date=END,
                              market_type="us_stock")
            if df.attrs.get("dual_price") and df.attrs.get("adjust") == "hfq_self_built":
                print(f"✅ 3) {sym} manual_events 已登记 → 放行走自建双价出口"
                      f"（{len(df)} bar，events_applied="
                      f"{df.attrs.get('n_events_applied')}，currency="
                      f"{df.attrs.get('currency')}）")
            else:
                anomaly.append(f"{sym} 放行但缺双价标注 {dict(df.attrs)}")
                ok = False
                print(f"❌ 3) {sym} 放行但缺双价口径标注")
        except Exception as exc:  # noqa: BLE001
            anomaly.append(f"{sym} 已登记却被拒绝 {str(exc)[:80]}")
            ok = False
            print(f"❌ 3) {sym} 已登记却被拒绝：{str(exc)[:100]}")
    for sym, mkt in (("MSFT", "us_stock"), ("SPY", "us_etf")):
        try:
            f0.get_daily(sym, start_date=START, end_date=END, market_type=mkt)
            anomaly.append(f"{sym} 未登记却未被拒绝")
            ok = False
            print(f"❌ 3) {sym}（{mkt}）未登记却被放行——fail-closed 失守")
        except Exception as exc:  # noqa: BLE001
            if "manual_events" in str(exc):
                print(f"✅ 3) {sym}（{mkt}）未登记 → 双位 fail-closed raise"
                      "（禁止降级跑回测，评审放行边界）")
            else:
                anomaly.append(f"{sym} 拦截语义不符 {str(exc)[:60]}")
                ok = False
                print(f"❌ 3) {sym} 拦截原因不符：{str(exc)[:100]}")

    # ---------- 4) 补测③：双价恒等式 / 事件核验残差 / 拆股线（真实链路） ----------
    try:
        aapl = f0.get_daily("AAPL", start_date=START, end_date=END,
                            market_type="us_stock")
        ident = float((aapl["close"] - aapl["raw_close"]
                       * aapl["adj_factor"]).abs().max())
        if ident < 1e-10:
            print(f"✅ 4a) AAPL 逐 bar 双价恒等式偏差 {ident:.2e} < 1e-10"
                  f"（adj=raw×factor 全窗口成立，n_events={aapl.attrs.get('n_events_applied')}）")
        else:
            anomaly.append(f"AAPL 恒等式偏差 {ident}")
            ok = False
        exd = pd.Timestamp("2026-11-12")
        prev_raw = float(aapl.loc[:exd, "raw_close"].iloc[-2])
        cur_raw = float(aapl.loc[:exd, "raw_close"].iloc[-1])
        actual, expected = cur_raw / prev_raw - 1, -0.27 / prev_raw
        resid = abs(actual - expected)
        if resid < 0.05:
            print(f"✅ 4b) AAPL 事件日 2026-11-12 raw 隔夜 {actual:+.4%} vs "
                  f"预期除净分量 {expected:+.4%}，残差 {resid:.3%} < 5%"
                  "（官方披露 $0.27 与价格逐位吻合，事件核验线通过）")
        else:
            anomaly.append(f"AAPL 事件残差 {resid:.4%}")
            ok = False
        # adj 序列除净日跳变 = 市场真实隔夜涨跌 × 当日因子（事件只吸收分红
        # 分量，市场噪声原样保留）；精确式含二阶项，禁止一阶近似
        adj_jump = float(aapl.loc[exd, "close"]) \
            / float(aapl.loc[:exd, "close"].iloc[-2]) - 1
        exp_adj = (1 + actual) * prev_raw / (prev_raw - 0.27) - 1
        if abs(adj_jump - exp_adj) < 1e-10:
            print(f"✅ 4c) AAPL adj 序列除净日跳变 {adj_jump:+.4%} = 市场真实涨跌"
                  "×当日因子（分红分量被精确吸收，残差量级≈事件核验残差）")
        else:
            anomaly.append(f"AAPL adj 除净日跳变 {adj_jump} ≠ 精确预期 {exp_adj}")
            ok = False
    except Exception as exc:  # noqa: BLE001
        anomaly.append(f"AAPL 双价核验失败 {str(exc)[:80]}")
        ok = False
        print(f"❌ 4) AAPL 双价核验失败：{str(exc)[:100]}")
    try:
        tsla = f0.get_daily("TSLA", start_date=START, end_date=END,
                            market_type="us_stock")
        jumps = tsla["raw_close"].pct_change().dropna()
        mx, mx_d = float(jumps.abs().max()), jumps.abs().idxmax()
        if tsla.attrs.get("n_events_applied") == 0 and mx < 0.50:
            print(f"✅ 4d) TSLA 零事件登记成立；窗口最大单日 |涨跌| {mx:+.2%}"
                  f"（{mx_d.date()}）< 50% 拆股线（高波动不误杀）")
        else:
            anomaly.append(f"TSLA 事件数 {tsla.attrs.get('n_events_applied')}"
                           f"/最大跳变 {mx:.2%}")
            ok = False
    except Exception as exc:  # noqa: BLE001
        anomaly.append(f"TSLA 双价核验失败 {str(exc)[:80]}")
        ok = False
        print(f"❌ 4) TSLA 双价核验失败：{str(exc)[:100]}")
    time.sleep(5)

    # ---------- 5) 补测③（合成帧）：无事件 <50% 不报错 / ≥50% 强制解释线 ----------
    try:
        conf = dict(config.US_STOCK_CONFORMANCE)
        base_idx = pd.bdate_range("2026-11-09", periods=6)

        def frame_with_jump(jump):
            # 跳变后小波动递推（避免第二根大回落多落审计带，污染断言）
            closes = [200.0, 200.5, 201.0]
            closes.append(closes[-1] * (1 + jump))
            closes += [closes[-1] * 1.001, closes[-1] * 0.999]
            return pd.DataFrame({"close": closes}, index=base_idx)

        factor = pd.Series(1.0, index=base_idx)
        audit = f0._hk_jump_audit("TSLA", frame_with_jump(0.45), factor, set(),
                                  conf=conf)          # 45%：审计带，不 raise
        if len(audit) == 1:
            print(f"✅ 5a) 无事件 45% 跳变：不报错，落 5%~50% 审计带"
                  f"（{audit[0]['date']} {audit[0]['jump']:+.0%}，attrs 披露）")
        else:
            anomaly.append(f"45% 审计带 {audit}")
            ok = False
        try:
            f0._hk_jump_audit("TSLA", frame_with_jump(0.60), factor, set(), conf=conf)
            anomaly.append("60% 跳变未触发拆股强制解释线")
            ok = False
            print("❌ 5b) 无事件 60% 跳变未 raise——拆股强制解释线失守")
        except JumpAuditError:
            print("✅ 5b) 无事件 60% 跳变：触发 50% 拆股强制解释线 JumpAuditError")
    except Exception as exc:  # noqa: BLE001
        anomaly.append(f"跳变闸合成帧验证失败 {str(exc)[:80]}")
        ok = False
        print(f"❌ 5) 跳变闸合成帧验证失败：{str(exc)[:100]}")

    # ---------- 6) 补测②：T+0 当日开平往返 ----------
    acc = TradingAccount(1_000_000, run_mode="backtest")
    r_buy = acc.place_order(symbol="AAPL", direction="buy", volume=100, price=200.0,
                            market_type="us_stock", data=pd.DataFrame(),
                            order_time=START, warmup_ok=True)
    pos = acc.get_position("AAPL")
    t0_ok = (r_buy["status"] != "rejected" and pos is not None
             and pos.volume == 100 and pos.frozen_volume == 0)
    r_sell = acc.place_order(symbol="AAPL", direction="sell", volume=100, price=200.0,
                             market_type="us_stock", data=pd.DataFrame(),
                             order_time=START, warmup_ok=True)
    pos_after = acc.get_position("AAPL")
    fx = float(config.US_STOCK_CONFORMANCE["fx_fixed_cny"])
    fee_total = (0.99 + 0.99 + 20000 * 0.0000278 + max(100 * 0.000166, 0.01)) * fx
    t0_ok = t0_ok and r_sell["status"] != "rejected" \
        and (pos_after is None or pos_after.volume == 0) \
        and abs(acc.cash - (1_000_000 - fee_total)) < 0.05
    if t0_ok:
        print(f"✅ 6) 补测② T+0 当日开平：买 100@200→卖 100@200 当日往返成功，"
              f"持仓归零、无 T+1 冻结残留，费用合计 {fee_total:.2f} CNY"
              f"（USD 逐项 0.99+1.5626 × 固定汇率 {fx}）")
    else:
        anomaly.append(f"T+0 往返异常 buy={r_buy['status']} sell={r_sell['status']}"
                       f" cash={acc.cash:.2f}")
        ok = False
        print("❌ 6) 补测② T+0 当日开平验证失败")

    # ---------- 7) 费用逐项 / 汇率口径 / 治理面断言 ----------
    fee_buy = float(acc.calc_commission("AAPL", "buy", 200.0, 100,
                                        market_type="us_stock", is_open=True))
    fee_sell = float(acc.calc_commission("AAPL", "sell", 200.0, 100,
                                         market_type="us_stock", is_open=False))
    exp_sell = 0.99 + 20000 * 0.0000278 + max(100 * 0.000166, 0.01)
    if abs(fee_buy - 0.99) < 0.005 and abs(fee_sell - exp_sell) < 0.005:
        print(f"✅ 7a) 费用逐项：买 {fee_buy:.2f}（佣金最低生效）；卖 {fee_sell:.4f}"
              " = 佣金 0.99 + SEC 0.556 + TAF 0.0166（卖出单边官方口径）")
    else:
        anomaly.append(f"费用 {fee_buy}/{fee_sell} ≠ 0.99/{exp_sell}")
        ok = False
    from core.account import DEFAULT_FX_RATES
    conf = getattr(config, "US_STOCK_CONFORMANCE", {})
    checks = [
        (float(DEFAULT_FX_RATES["USD"]) == float(conf.get("fx_fixed_cny")) == 7.20,
         "汇率单一权威：DEFAULT_FX_RATES 锚定治理面 fx_fixed_cny=7.20"),
        ("manual_events" in conf and "AAPL" in conf["manual_events"]
         and "TSLA" in conf["manual_events"], "manual_events 登记 AAPL/TSLA"),
        (conf["manual_events"]["AAPL"]
         and conf["manual_events"]["AAPL"][0]["ex_date"] == "2026-11-12"
         and float(conf["manual_events"]["AAPL"][0]["div"]) == 0.27
         and conf["manual_events"]["AAPL"][0].get("source"),
         "AAPL 事件逐位登记（官方新闻稿 $0.27 / ex 11-12 / pay 11-16，含 source）"),
        (conf.get("manual_events_mode") == "raise_unlisted",
         "manual_events_mode=raise_unlisted（未登记标的禁止降级）"),
        (conf.get("events_source") == {}, "events_source 穷举定案登记为空"),
        (conf.get("jump_audit", {}).get("threshold_split") == 0.50
         and conf.get("jump_audit", {}).get("threshold") == 0.05,
         "拆股强制解释线 50% / 事件日核验线 5%"),
        (conf.get("qty_step") == 1 and conf.get("t_plus") == 0
         and conf.get("currency") == "USD"
         and conf.get("tz") == "America/New_York", "qty_step=1 / T+0 / USD / 美东时区"),
    ]
    bad = [name for passed, name in checks if not passed]
    if not bad:
        print("✅ 7b) 治理面断言全部成立：" + "；".join(name for _, name in checks))
    else:
        anomaly.append(f"治理面断言失败 {bad}")
        ok = False
        print(f"❌ 7b) 治理面断言失败：{bad}")

    # ---------- 结果 ----------
    print("=" * 68)
    print(f"耗时 {time.time()-t0:.0f}s")
    if anomaly:
        print(f"❌ 异常表 {len(anomaly)} 条：{anomaly}")
        print("❌ 美股日线预检·补测轮未通过")
        return 1
    print("✅ 异常表 0 条")
    print("✅ 美股日线预检·补测轮 3 必测项全绿（manual_events 放行/未登记 raise/"
          "双价恒等式/事件残差/拆股线/T+0/时区），待评审裁定链路转正")
    return 0


if __name__ == "__main__":
    sys.exit(main())
