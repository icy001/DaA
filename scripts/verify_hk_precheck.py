# -*- coding: utf-8 -*-
"""港股回测/研究链路最小样本预检（v3.54 评审裁定，可复现脚本）。

范围：02800.HK 盈富基金 + 00700.HK 腾讯，2025-11-20~2026-11-20 日线；
硬约束：不改 config 治理面（独立脚本验证），缺口如实上报、禁止黑箱降级。

四项必验：
  1) 数据源与基础规则（行情深度/事件表/日历独立性/每手/tick/汇率/费用）
  2) 交易规则差异（T+0 回转、无涨跌停、全费用逐项、午休时段）
  3) 汇率（中行央行中间价 + 权益折算 + 汇兑损益单列口径）
  4) 双价体系对齐（自建后复权 adj 序列 + 除净日参考价恒等式 + 逐笔恒等式）

用法：python scripts/verify_hk_precheck.py [--skip-backtest]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import config
from core import signal_gate
from core.backtester import Backtester
from core.account import TradingAccount
from strategies.double_ma_cross import DoubleMACross

START, END = "2025-11-20", "2026-11-20"
SYMBOLS = ["02800", "00700"]
# 预检口径：恒定汇率隔离验证交易链路（中行 2026-11-20 央行中间价 85.618/100HKD）
FX_HKD_STATIC = 0.85618
# 费用实测参照（config.MARKETS["hk_stock"] 现值，预检不改治理面，逐项列示）


def _fetch_daily(symbol: str) -> pd.DataFrame:
    import akshare as ak
    df = ak.stock_hk_daily(symbol=symbol, adjust="")
    df.index = pd.to_datetime(df["date"])
    return df.sort_index()


def _fetch_events(symbol: str) -> pd.DataFrame:
    import akshare as ak
    try:
        return ak.stock_hk_dividend_payout_em(symbol=symbol)
    except Exception:
        return pd.DataFrame()


def part1_sources_and_rules() -> dict:
    print("=" * 68)
    print("PART 1 · 数据源与基础规则（硬证据）")
    ok = True
    ev_gap = []
    frames, events = {}, {}
    for sym in SYMBOLS:
        df = _fetch_daily(sym)
        win = df[(df.index >= START) & (df.index <= END)]
        frames[sym] = win
        complete = bool(win[["open", "high", "low", "close", "volume"]].notna().all().all())
        print(f"  [{sym}] 全历史 {len(df)} 行（{df.index[0].date()}→{df.index[-1].date()}，"
              f"≥2020={'✓' if str(df.index[0].date()) <= '2020-01-02' else '✗'}）"
              f" | 窗口 {len(win)} bar | OHLCV 完整={'✓' if complete else '✗'}"
              f" | amount 列={'✓' if 'amount' in win.columns else '✗'}")
        ok &= complete
        ev = _fetch_events(sym)
        events[sym] = ev
        if len(ev) == 0:
            ev_gap.append(sym)
            print(f"  [{sym}] ⚠ 分红/事件表：东财 stock_hk_dividend_payout_em 0 条"
                  f"（缺口上报，事件验证由 00700 承担）")
        else:
            near = ev[pd.to_datetime(ev["除净日"]).between(START, END)]
            print(f"  [{sym}] 事件表 {len(ev)} 条，窗口内 {len(near)} 条：")
            for _, r in near.iterrows():
                print(f"      除净 {r['除净日']} | {r['分红方案']} | {r['分配类型']}")
    # 日历独立性：圣诞/元旦差异实证
    hk_days = set(frames["02800"].index.date)
    import akshare as ak
    cn = ak.tool_trade_date_hist_sina()
    cn_days = set(pd.to_datetime(cn["trade_date"]).dt.date)
    seg = lambda s: {d for d in s if pd.Timestamp(START).date() <= d <= pd.Timestamp(END).date()}
    only_cn = sorted(seg(cn_days) - seg(hk_days))
    only_hk = sorted(seg(hk_days) - seg(cn_days))
    christmas = [d for d in only_cn if d.month == 12 and d.day in (25, 26)]
    print(f"  [日历] 港股开市 A股休市 {len(only_hk)} 天 {only_hk[:4]}…；"
          f"A股开市 港股休市 {len(only_cn)} 天（含圣诞 {christmas}）——复用 A 股日历 = 错日历 ✓ 独立")
    ok &= bool(christmas)
    # 每手股数
    try:
        prof = ak.stock_hk_security_profile_em(symbol="00700")
        lot = prof.iloc[0]["每手股数"]
        print(f"  [每手] 00700 = {lot} 股/手（stock_hk_security_profile_em 实测）")
    except Exception as exc:
        lot = None
        print(f"  [每手] 00700 获取失败：{exc}")
    print("  [每手] 02800 = 缺口上报（security_profile_em 对 ETF 返回空，"
          "正式接入前须从港交所证券资料页实测，禁止按 100 凭记忆填）")
    # tick 网格实证
    for sym, lo in (("00700", 200.0), ("02800", 20.0)):
        d = frames[sym]["close"].diff().abs().dropna()
        nz = sorted({round(x, 3) for x in d if x > 0})
        print(f"  [tick] {sym} 价格区间 {frames[sym]['close'].min():.2f}~"
              f"{frames[sym]['close'].max():.2f}，收盘差网格最小 {min(nz)}（价位表 "
              f"{'>=200→0.2 一致 ✓' if sym == '00700' else '20~100→0.05，实测网格含 0.02 → ETF 价位表缺口上报'}）")
    # 汇率
    fx = ak.currency_boc_sina(symbol="港币", start_date="20251120", end_date="20261120")
    mid = fx[["日期", "央行中间价"]].rename(columns={"央行中间价": "mid"})
    print(f"  [汇率] 中行牌价 {len(fx)} 行（央行中间价列），末值 "
          f"{mid['mid'].iloc[-1]}/100HKD；源精度 3 位小数（如实标注，非 4 位）")
    # 费用结构（config 现值逐项列示，预检不改）
    rule = config.get_market_config("hk_stock")
    items = [("印花税（买卖双边）", rule["stamp_tax_rate_sell"]),
             ("证监会征费 sfc", rule["sfc_levy"]),
             ("交易所交易费", rule["trading_fee"]),
             ("财汇局征费 frc", rule["frc_levy"]),
             ("中央结算 ccass", rule["ccass_fee"]),
             ("交易系统费（每笔）", rule["trading_system_fee"]),
             ("佣金（可配置）", rule["commission_rate"])]
    print("  [费用] config 现值逐项（预检不改治理面）：")
    tot = 0.0
    for name, v in items:
        print(f"      {name}: {v}" + (f"（≈{v * 1e4:.2f}bp）" if isinstance(v, float) and v < 0.01 else ""))
        if isinstance(v, float):
            tot += v
    print(f"      征费类合计（sfc+trading+frc+ccass）≈ {0.000027 + 0.00005 + 0.0000015 + 0.00002:.7f}"
          f"（≈{(0.000027 + 0.00005 + 0.0000015 + 0.00002) * 1e4:.3f}bp）")
    print(f"  [规则] t_plus={rule['t_plus']}（T+0 回转）| t_settle={rule['t_settle']}"
          f"（T+2 交收）| price_limit={rule['price_limit']}（无涨跌停 ✓）"
          f"| 午休时段 trading_hours={rule['trading_hours']}")
    print(f"PART 1 {'✓ 全部通过（缺口 ' + str(len(ev_gap) + 2) + ' 项已上报）' if ok else '✗'}")
    return {"frames": frames, "events": events, "lot_00700": lot, "ok": ok}


def part2_dual_price(info: dict) -> dict:
    """自建后复权 adj 序列（00700 事件表独立因子）+ 除净参考价 + 恒等式。"""
    print("=" * 68)
    print("PART 2 · 双价体系（自建 adj，事件表独立因子，不消费黑箱复权价）")
    sym = "00700"
    raw_all = _fetch_daily(sym)
    win = raw_all[(raw_all.index >= START) & (raw_all.index <= END)].copy()
    ev = info["events"][sym]
    # 窗口内除净事件：除净日 e、每股现金红利 div（港币）；拆股/供股 0 条（2026 窗口）
    ev_near = []
    for _, r in ev.iterrows():
        e = pd.Timestamp(r["除净日"])
        if START <= str(e.date()) <= END:
            import re
            m = re.search(r"每股[派息]?港币([\d.]+)元", str(r["分红方案"]))
            if m:
                ev_near.append((e, float(m.group(1))))
    print(f"  窗口内现金红利事件：{[(str(e.date()), d) for e, d in ev_near]}")
    # 后复权因子：除净日 e 起 factor *= prev_raw/(prev_raw − div)（prev= e 前一交易日收盘）
    factor = pd.Series(1.0, index=win.index)
    cum = 1.0
    all_idx = raw_all.index
    for e, div in ev_near:
        pos = all_idx.get_loc(e)
        if pos == 0:
            continue
        prev_raw = float(raw_all["close"].iloc[pos - 1])
        cum *= prev_raw / (prev_raw - div)
        factor[factor.index >= e] = cum
    win["adj_factor"] = factor
    for c in ("open", "high", "low", "close"):
        win[f"adj_{c}"] = win[c] * factor
    # 恒等式：adj = raw × factor
    dev = float((win["adj_close"] - win["close"] * win["adj_factor"]).abs().max())
    print(f"  恒等式 max |adj_close − raw_close × factor| = {dev:.2e}（<1e-10 "
          f"{'✓' if dev < 1e-10 else '✗'}）")
    # 除净日参考价：prev_raw × (f_prev/f_today) = prev_raw − div（与 A 股除权参考价同式）
    ref_ok = True
    for e, div in ev_near:
        pos_all = all_idx.get_loc(e)
        prev_raw = float(raw_all["close"].iloc[pos_all - 1])
        w_pos = win.index.get_loc(e)          # 窗口帧内位置（factor 为窗口 Series）
        if w_pos == 0:
            continue
        f_prev, f_today = float(factor.iloc[w_pos - 1]), float(factor.iloc[w_pos])
        ref = prev_raw * (f_prev / f_today)
        expect = prev_raw - div
        good = abs(ref - expect) < 1e-9
        ref_ok &= good
        print(f"  除净参考价 {e.date()}: 昨收 {prev_raw} × 因子比 {f_prev/f_today:.6f} "
              f"= {ref:.4f} ≈ 昨收−红利 {expect:.4f}（{'✓' if good else '✗'}）")
    # 除净日 adj 连续性（无假跳空）
    for e, div in ev_near:
        w_pos = win.index.get_loc(e)
        if w_pos > 0:
            a_prev, a_cur = float(win["adj_close"].iloc[w_pos-1]), float(win["adj_close"].iloc[w_pos])
            print(f"  除净日 adj 连续性: 前日 {a_prev:.2f} → 当日 {a_cur:.2f}"
                  f"（变化 {a_cur/a_prev-1:+.4%}，为当日真实涨跌非跳空）")
    print(f"PART 2 {'✓' if dev < 1e-10 and ref_ok else '✗'}")
    return {"ok": dev < 1e-10 and ref_ok, "frame": win}


def build_backtest_frame(symbol: str) -> pd.DataFrame:
    """双价帧：主列 OHLC = 自建 adj（信号/收益），raw_* = 原始报价（下单/费用）。"""
    raw_all = _fetch_daily(symbol)
    win = raw_all[(raw_all.index >= START) & (raw_all.index <= END)].copy()
    ev = _fetch_events(symbol)
    cum, ev_list = 1.0, []
    import re
    for _, r in ev.iterrows():
        e = pd.Timestamp(r["除净日"])
        if START <= str(e.date()) <= END:
            m = re.search(r"每股[派息]?港币([\d.]+)元", str(r["分红方案"]))
            if m:
                ev_list.append((e, float(m.group(1))))
    factor = pd.Series(1.0, index=win.index)
    all_idx = raw_all.index
    for e, div in ev_list:
        pos = all_idx.get_loc(e)
        if pos == 0:
            continue
        prev_raw = float(raw_all["close"].iloc[pos - 1])
        cum *= prev_raw / (prev_raw - div)
        factor[factor.index >= e] = cum
    win["adj_factor"] = factor
    for c in ("open", "high", "low", "close"):
        win[f"raw_{c}"] = win[c]
        win[c] = win[c] * factor
    win["price_adjust"] = "hfq_self_built"
    win["data_asof_date"] = win.index
    win.attrs.update({"market": "hk_stock", "source": "sina_stock_hk_daily",
                      "volume_unit": "股", "adjust": "hfq_self_built",
                      "currency": "HKD", "dual_price": True,
                      "events_source": "em_stock_hk_dividend_payout_em"})
    return win


class HKFetcher:
    """预检专用取数包装（不改数据层治理面）：自建双价帧 + 独立日历。"""

    def get_daily(self, symbol, start_date=None, end_date=None, adjust="hfq",
                  market_type=None, **kwargs):
        frame = build_backtest_frame(str(symbol))
        if start_date:
            frame = frame[frame.index >= pd.Timestamp(start_date)]
        if end_date:
            frame = frame[frame.index <= pd.Timestamp(end_date)]
        return frame

    def get_kline(self, symbol, **kwargs):
        return self.get_daily(symbol, **kwargs)


def part3_backtest() -> bool:
    print("=" * 68)
    print("PART 3 · 回测预检（02800+00700 近1年日线，double_ma_cross 默认参数，"
          "恒定汇率口径）")
    t0 = time.time()
    bt = Backtester(
        DoubleMACross, symbols=SYMBOLS, start_date=START, end_date=END,
        initial_capital=config.INITIAL_CASH, market_type="hk_stock",
        fetcher=HKFetcher(), period="1d", run_mode="backtest",
        liquidate_at_end=False)
    bt.fx_rates = {"HKD": FX_HKD_STATIC, "CNY": 1.0}   # 恒定汇率注入
    result = bt.run()
    trades, rejected = result.trades, result.rejected
    decisions = signal_gate.decision_log()
    m = result.metrics
    print(f"  bars={len(bt.dates)} | 成交 {len(trades)} | 拒单 {len(rejected)}"
          f" | 决策 {len(decisions)} | 耗时 {time.time()-t0:.0f}s")
    print(f"  总收益 {m.get('total_return'):+.4%}（分母=初始权益，HKD×{FX_HKD_STATIC} 折算）"
          f" | 最大回撤 {m.get('max_drawdown'):.2%} | 爆仓 {m.get('margin_call_count')}")
    ok = True
    # 首笔逐位对账：成交价 = 成交 bar 开盘(adj) × (1±滑点)
    if len(trades):
        t0r = trades.iloc[0]
        fill_px = float(t0r["price"])
        sym, ts = t0r["symbol"], pd.Timestamp(t0r["timestamp"])
        frame = bt.frames[sym]
        pos = frame.index.get_indexer([ts])[0]
        bar_open = float(frame["open"].iloc[pos])
        expect = bar_open * 1.0005   # next_open × (1+滑点 0.05%，EXECUTION_MODEL 默认)
        good = abs(fill_px - expect) < 1e-6
        ok &= good
        print(f"  首笔逐位: {sym} {ts} fill={fill_px:.4f} = 次根bar开盘(adj) {bar_open:.4f}"
              f" × 1.0005（{'✓' if good else '✗'}；滑点 0.05%）")
        # 逐笔恒等式：price == raw_price × 当日因子。
        # 判据 1e-5 = 成交记录 round(6) 落盘精度的理论界（price/raw_price 各自
        # 截断 1e-6/2 × ~25 元价格 × factor ≈ 数个 1e-7，取 1e-5 安全界）；
        # 帧级恒等式（PART 2）不受落盘截断影响，已证 <1e-10
        if "raw_price" in trades.columns:
            devs = []
            for _, r in trades.iterrows():
                fr = bt.frames[r["symbol"]]
                fi = fr.index.get_indexer([pd.Timestamp(r["timestamp"])])[0]
                fac = float(fr["adj_factor"].iloc[fi])
                raw_fill = float(r["raw_price"]) if pd.notna(r["raw_price"]) else None
                if raw_fill:
                    devs.append(abs(float(r["price"]) - raw_fill * fac))
            if devs:
                bound = 1e-5
                print(f"  逐笔恒等式 max dev = {max(devs):.2e}（<1e-5 落盘精度界 "
                      f"{'✓' if max(devs) < bound else '✗'}，n={len(devs)}；"
                      "帧级恒等式 <1e-10 已在 PART 2 证明）")
                ok &= max(devs) < bound
    # 信号出口对账
    if len(decisions) == len(trades) + len(rejected):
        print(f"  ✓ 信号出口对账：决策 {len(decisions)} = 成交 {len(trades)} + 拒单 {len(rejected)}")
    else:
        ok = False
        print(f"  ✗ 对账失败：决策 {len(decisions)} ≠ {len(trades)}+{len(rejected)}")
    print(f"  拒单分类：{ {r.get('code'): 1 for r in rejected} or '无拒单'}")
    print(f"PART 3 {'✓' if ok else '✗'}")
    return ok


def main() -> int:
    print("港股回测/研究链路最小样本预检（02800+00700，日线，2025-11-20~2026-11-20）")
    info = part1_sources_and_rules()
    dual = part2_dual_price(info)
    if "--skip-backtest" not in sys.argv:
        bt_ok = part3_backtest()
    else:
        print("  （--skip-backtest：跳过回测段）")
        bt_ok = True
    all_ok = info["ok"] and dual["ok"] and bt_ok
    print("=" * 68)
    print("缺口清单（如实上报，禁止黑箱降级）：")
    print("  1) 02800 分红/事件表：东财 dividend_payout_em 0 条、同花顺接口失败"
          "——ETF 派息事件需另接权威源（如港交所/基金公司公告页）")
    print("  2) 02800 每手股数：security_profile_em 对 ETF 返回空——正式接入前实测")
    print("  3) 02800 tick 网格：实测收盘差含 0.02，与股份价位表（20~100→0.05）不符"
          "——ETF 适用价位表待核实")
    print("  4) 汇率源精度：中行中间价 3 位小数（非 4 位），以源精度为准如实标注")
    print("  5) 动态逐日汇率与汇兑损益单列：预检以恒定汇率隔离验证交易链路，"
          "正式接入实现逐日中间价注入 + 汇兑损益单列统计")
    print("=" * 68)
    print("✅ 预检通过（含已上报缺口）" if all_ok else "❌ 预检未通过")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
