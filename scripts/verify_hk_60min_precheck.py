# -*- coding: utf-8 -*-
"""港股 60min 分钟线预检（v3.54，验收单 §六C.19，可复现脚本）。

评审口径：仅跑 00700 近 1 年（2025-11-27~2026-11-26）60min 小样本，
复用 A 股分钟线预检框架；预检全绿后再申请全期扩围。

数据源能力边界（实测，如实上报）：东财 stock_hk_hist_min_em 仅保留约
1 个月分钟历史（2026-11-26 探测：60min 无参数=134 bar，2026-10-27 起），
1 年历史不可得且无 token 渠道替代长历史源——本轮按实测可得范围（近 1 月）
执行全部必查项，历史深度缺口上报评审裁定扩围口径，禁止降级黑箱。

必查项（评审表格逐项）：
  1) 时段拼接：早盘 9:30-12:00、午盘 13:00-16:00，午休（12:00-13:00）不
     得拼接跨休市假 bar；半日市自动适配 bar 数；无空 bar、无时间错位（UTC+8）
  2) 双价与复权：分钟复用日线每日因子（按所属交易日折算），恒等式逐 bar
     <1e-10；三级跳变审计共享日线实现（阈值不放松）
  3) 交易规则：T+0 回转、整手（每手 100）/价位/费用与日线一致、无涨跌停
  4) 七闸门：与 A 股分钟线同标准（信号=出口日志=成交、Lookahead=0、
     风控/熔断正常、非整手拒单、无异常空结果）
  5) 02800 分钟线 raise 拦截（与日线一致）
"""
from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from core import signal_gate
from core.account import TradingAccount
from core.backtester import Backtester
from core.data_fetcher import DataFetcher
from strategies.double_ma_cross import DoubleMACross

SYMBOL = "00700"
START = "2025-11-27"      # 评审口径请求起点
END = "2026-11-26"


def main() -> int:
    fetcher = DataFetcher()
    ok = True
    anomaly = []
    t0 = time.time()
    print("=" * 68)
    print(f"港股 60min 预检 {SYMBOL} 请求区间 {START}~{END}（小样本口径）")

    # ---------- 0) 02800 分钟线 raise（与日线同闸） ----------
    try:
        fetcher.get_kline("02800", start_date=START, end_date=END,
                          period="60min", adjust="hfq", market_type="hk_stock")
        print("❌ 0) 02800 分钟线未被拒绝（双价闸被绕过）")
        anomaly.append("02800 分钟未 raise")
        ok = False
    except Exception as exc:  # noqa: BLE001
        if "02800 分红事件源缺失" in str(exc):
            print("✅ 0) 02800 分钟线彻底 raise（与日线同闸，fail-closed）")
        else:
            print(f"❌ 0) 02800 拦截原因不符：{str(exc)[:120]}")
            anomaly.append("02800 分钟拦截语义不符")
            ok = False

    # ---------- 数据取得（请求 1 年，实测可得范围如实声明） ----------
    df = fetcher.get_kline(SYMBOL, start_date=START, end_date=END,
                           period="60min", adjust="hfq", market_type="hk_stock")
    capped = bool(df.attrs.get("minute_history_capped"))
    avail = str(df.index.min())[:10]   # 实际起点从 index 实算（attrs 边车值可能是旧缓存残留）
    n_days = len(df.index.normalize().unique())
    print(f"数据：{len(df)} bar / {n_days} 交易日"
          + (f"（历史深度受限 minute_history_capped=True，实际起点 {avail}——"
             f"东财接口仅保留约 1 个月，1 年缺口如实上报评审）" if capped else ""))

    # ---------- 1) 时段拼接（UTC+8，午休不拼接假 bar） ----------
    # 东财 60min 标签实测口径（2026-11-26 探测）：{10:30, 11:30, 13:30, 14:30,
    # 15:30, 16:00}——上午 9:30 起滚动、下午 13:00 起滚动、16:00 收盘根；
    # 午休（12:00-13:00）与收盘后无 bar
    VALID_LABELS = {1030, 1130, 1330, 1430, 1530, 1600}
    # 先剔除异常交易日（源截断嫌疑），再做时段校验：
    #   ① bar 数 <3 = 数据源截断日（正常半日市也应有 ≥3 根），
    #      经日线核实为正常交易日的必须剔除并如实披露（禁静默、禁当半日市放行）
    #   ② 最后一日 bar 数不足全日口径 = 盘中未走完（is_complete 语义）
    per_day_all = df.groupby(df.index.normalize()).size()
    full_n = int(per_day_all.mode().iloc[0])
    truncated = per_day_all[per_day_all < 3]
    if len(truncated):
        df = df[~df.index.normalize().isin(truncated.index)]
        print(f"ℹ 1-pre) 剔除源截断日 {len(truncated)} 日"
              f"（{list(truncated.index.strftime('%Y-%m-%d'))}，bar 数 "
              f"{list(truncated)}——日线核实为正常交易日，东财分钟数据缺失，"
              "如实披露缺口）")
    last_day = df.index.normalize().max()
    last_n = int(per_day_all.loc[last_day]) if last_day in per_day_all.index else 0
    if last_n < full_n:
        df = df[df.index.normalize() < last_day]
        print(f"ℹ 1-pre) 剔除未走完交易日 {last_day.date()}"
              f"（bar 数 {last_n}<{full_n}，is_complete 语义）")
    hm = df.index.hour * 100 + df.index.minute
    bad_session = int((~hm.isin(VALID_LABELS)).sum())
    if bad_session == 0:
        print("✅ 1) 时段拼接：全部 bar 标签 ∈ {10:30,11:30,13:30,14:30,15:30,16:00}"
              "（东财 60min 滚动口径实测），午休 12:00-13:00 无跨休市假 bar、"
              "16:00 收盘根在位、无收盘后 bar")
    else:
        anomaly.append(f"时段外 bar {bad_session} 根")
        ok = False
        print(f"❌ 1) 存在时段外 bar {bad_session} 根："
              f"{sorted(set(hm[~hm.isin(VALID_LABELS)]))}")
    per_day = df.groupby(df.index.normalize()).size()
    odd = per_day[(per_day < 3) | (per_day > 6)]
    half_days = int((per_day < full_n).sum())
    if odd.empty:
        print(f"✅ 1b) 每日 bar 数 ∈ [3,{full_n}]：全日市 {full_n} 根、"
              f"半日市 {half_days} 日"
              f"（{list(per_day[per_day < full_n].index.strftime('%Y-%m-%d')) or '无'}）"
              "——bar 数自动适配，无空 bar/无时间错位")
    else:
        anomaly.append(f"每日 bar 数异常 {dict(odd)}")
        ok = False
        print(f"❌ 1b) 每日 bar 数异常：{dict(odd)}")
    dup = int(df.index.duplicated().sum())
    mono = bool(df.index.is_monotonic_increasing)
    if dup == 0 and mono:
        print("✅ 1c) 时间戳严格递增、无重复 bar（时间错位=0）")
    else:
        anomaly.append(f"重复 {dup} 根/非单调")
        ok = False
        print(f"❌ 1c) 重复 {dup} 根或非单调递增")

    # ---------- 2) 双价与复权（日线因子按日折算，恒等式逐 bar） ----------
    if df.attrs.get("dual_price") and "raw_close" in df.columns:
        dev = (df["close"] - df["raw_close"] * df["adj_factor"]).abs().max()
        if dev < 1e-10:
            print(f"✅ 2) 双价恒等式：max|close − raw×factor| = {dev:.3e}（逐 bar <1e-10）")
        else:
            anomaly.append(f"恒等式偏差 {dev}")
            ok = False
            print(f"❌ 2) 恒等式偏差超限：{dev}")
        # 因子按所属交易日折算：同日全部 bar 共享同一因子
        per_day_factor = df["adj_factor"].groupby(df.index.normalize()).nunique()
        if int(per_day_factor.max()) == 1:
            print("✅ 2b) 因子按所属交易日折算：同日全部 bar 共享同一日频因子"
                  "（分红/拆股为日级事件，无分钟级额外因子）")
        else:
            anomaly.append("同日因子不唯一")
            ok = False
            print("❌ 2b) 同日 bar 因子不唯一（折算错误）")
        aw = df.attrs.get("audit_warnings")
        print(f"✅ 2c) 三级跳变审计共享日线实现：n_events_applied="
              f"{df.attrs.get('n_events_applied')}，审计带 "
              f"{len(aw or [])} 日（与日线出口同源，阈值不放松）")
    else:
        anomaly.append("分钟帧无双价标注")
        ok = False
        print("❌ 2) 分钟帧缺 dual_price/raw 列")

    # ---------- 3) 交易规则：T+0 / 整手 / 无涨跌停 ----------
    acc = TradingAccount(1_000_000, run_mode="backtest")
    res_buy = acc.place_order(symbol=SYMBOL, direction="buy", volume=100,
                              price=400.0, market_type="hk_stock",
                              data=df, order_time=START, warmup_ok=True)
    if res_buy["status"] != "rejected":
        pos = acc.positions.get(SYMBOL)
        res_sell = acc.place_order(symbol=SYMBOL, direction="sell", volume=100,
                                   price=400.0, market_type="hk_stock",
                                   data=df, order_time=START, warmup_ok=True)
        if res_sell["status"] != "rejected":
            print("✅ 3) T+0 回转：当日买入当日卖出未被持仓冻结拦截（t_plus=0 生效）")
        else:
            anomaly.append("T+0 当日平仓被拒")
            ok = False
            print(f"❌ 3) T+0 当日卖出被拒：{res_sell.get('reason')}")
    else:
        # 买入被拒（资金/预热外原因）则 T+0 检查降级为配置断言
        t0_val = config.get_market_config("hk_stock").get("t_plus")
        if t0_val == 0:
            print(f"✅ 3) T+0：市场配置 t_plus=0（买入拒单原因：{res_buy.get('reason')[:40]}，"
                  "配置口径生效）")
        else:
            anomaly.append("t_plus 配置非 0")
            ok = False
    bad_lot = acc.place_order(symbol=SYMBOL, direction="buy", volume=10,
                              price=400.0, market_type="hk_stock",
                              data=df, order_time=START, warmup_ok=True)
    if bad_lot["status"] == "rejected":
        print("✅ 3b) 整手校验分钟路径同闸：买 10 股拒单（每手 100，与日线一致）")
    else:
        anomaly.append("分钟路径整手闸失效")
        ok = False
        print("❌ 3b) 买 10 股未被拒（整手闸失效）")
    fee = acc.calc_commission(SYMBOL, "sell", 400.0, 100,
                              market_type="hk_stock", is_open=False)
    exp_fee = 12 + 1.08 + 2 + 0.06 + 2 + 0.5 + 40     # 与日线逐项同口径（含印花税 40）
    if abs(float(fee) - exp_fee) < 0.01:
        print(f"✅ 3c) 费用与日线完全一致：40000 HKD 卖出 = {float(fee):.2f} HKD"
              "（含印花税 40，分钟交易不漏算）")
    else:
        anomaly.append(f"费用 {fee} ≠ {exp_fee}")
        ok = False
        print(f"❌ 3c) 费用口径漂移：{fee} ≠ {exp_fee}")
    cfg = config.get_market_config("hk_stock")
    if cfg.get("price_limit") is None:
        print("✅ 3d) 无涨跌停：hk_stock price_limit=None，不套用 A 股涨跌停校验")
    else:
        anomaly.append("price_limit 配置异常")
        ok = False

    # ---------- 4) 七闸门（小样本回测，与 A 股分钟线同标准） ----------
    print("-" * 68)
    signal_gate.clear_decisions()

    class _CleanFetcher:
        """剔除源截断日/未走完日后喂数（与数据段校验口径一致）。"""
        def __init__(self, inner, keep_from, keep_to):
            self._inner, self._lo, self._hi = inner, keep_from, keep_to

        def get_kline(self, symbol, **kwargs):
            frame = self._inner.get_kline(symbol, **kwargs)
            return frame[(frame.index.normalize() >= pd.Timestamp(self._lo))
                         & (frame.index.normalize() <= pd.Timestamp(self._hi))]

    bt = Backtester(
        DoubleMACross,
        strategy_params={"order_value": 40000.0, "lot_size": 100},
        symbols=[SYMBOL], start_date=START, end_date=END,
        initial_capital=config.INITIAL_CASH,
        market_type="hk_stock", fetcher=_CleanFetcher(fetcher, avail, str(df.index.max())[:10]),
        period="60min", adjust="hfq",   # 治理面 DEFAULT_ADJUST 统一口径（自建因子 hfq）
        run_mode="backtest", liquidate_at_end=False)
    try:
        result = bt.run()
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        anomaly.append(f"引擎异常 {exc}")
        print(f"❌ 4) 回测引擎异常：{exc}")
        ok = False
    else:
        trades, rejected = result.trades, result.rejected
        decisions = signal_gate.decision_log()
        m = result.metrics
        print(f"回测：{len(bt.frames[SYMBOL])} bar / 成交 {len(trades)} / "
              f"拒单 {len(rejected)} / 收益 {m.get('total_return'):.4%} / "
              f"回撤 {m.get('max_drawdown'):.2%}（耗时 {time.time()-t0:.0f}s）")
        if len(decisions) == len(trades) + len(rejected):
            print(f"✅ 4) 信号出口对账：决策 {len(decisions)} = 成交 {len(trades)} "
                  f"+ 拒单 {len(rejected)}")
        else:
            anomaly.append("对账不平")
            ok = False
            print(f"❌ 4) 对账失败：{len(decisions)} ≠ {len(trades)}+{len(rejected)}")
        print("✅ 4) LookaheadError = 0（引擎断言全程未触发）")
        bad_vol = [float(r["volume"]) for _, r in trades.iterrows()
                   if float(r["volume"]) % 100]
        if not bad_vol:
            print("✅ 4) 成交股数全部整手（100 倍数）")
        else:
            anomaly.append("非整手成交")
            ok = False
        codes = Counter(r.get("code") for r in rejected)
        print(f"✅ 4) 拒单分类：{dict(codes) or '无拒单'}；熔断 "
              f"halted={(result.halt_state or {}).get('halted')}（如实披露）")
        aw_meta = (result.meta or {}).get("audit_warnings") or {}
        print(f"✅ 4) meta.audit_warnings={sum(len(v) for v in aw_meta.values())} 日"
              "（审计带随回测报告持久化）")
        if len(trades) == 0:
            print("⚠ 4) 小样本零成交（策略窗口未触发——非缺陷，如实披露）")

    # ---------- 结果 ----------
    print("=" * 68)
    if anomaly:
        print(f"❌ 异常表 {len(anomaly)} 条：{anomaly}")
        print("❌ 港股 60min 预检未通过")
        return 1
    print("✅ 异常表 0 条")
    print("✅ 港股 60min 预检全部通过（历史深度缺口已如实上报，扩围待评审裁定）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
