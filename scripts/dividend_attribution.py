# -*- coding: utf-8 -*-
"""v3.53 评审四轮·事1：持仓期股息统计与收益口径拆分（可复现脚本）。

背景：双价版 +5.83%（含息，qfq 记账）与降级版 -2.37%（不含息 raw 价差）口径不同，
总差 +8.2pp 不能直接归因「假信号消除」。本脚本统计回测区间内【持仓期】股息总额，
拆分「股息内含贡献」与「信号效应残差」。

方法：每股现金红利 ≈ 昨收 raw × (1 − 昨日因子/当日因子)（因子比近似，税前口径）。
抽样验证：600519 2025-06-26 推得 27.60 元/股 vs 真实分红 27.624 元/股（精度 0.1%）。

用法：python scripts/dividend_attribution.py [run_id]
     默认 run_id = bt_double_ma_cross_60min_2020-01-01_2026-11-18_20261120_153133
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.data_fetcher import DataFetcher  # noqa: E402

SYMBOLS = ["600519", "000001", "600036", "000858", "601318"]
CAPITAL = 1_000_000.0
LEGACY_RETURN, DUAL_RETURN = -2.37, 5.83   # §八 降级版（不含息价差）/ §六C.7 双价版（含息）


def main(run_id: str) -> None:
    tr = pd.read_csv(BASE / "backtest_results" / f"{run_id}_trades.csv",
                     dtype={"symbol": str})
    tr["timestamp"] = pd.to_datetime(tr["timestamp"], format="mixed")
    f = DataFetcher()
    total, rows = 0.0, []
    for sym in SYMBOLS:
        fs = f._fetch_baostock_adjust_factor(sym)["qfq_factor"].sort_index()
        jumps = fs[fs.diff().fillna(0).abs() > 1e-6]
        jumps = jumps[(jumps.index >= "2020-01-01") & (jumps.index <= "2026-11-18")]
        g = tr[tr["symbol"] == sym].sort_values("timestamp")
        store = pd.read_parquet(f.cache_dir / "minute" / f"cn_stock_{sym}_60.parquet")
        store["date"] = pd.to_datetime(store["date"])
        for ex_day, f_new in jumps.items():
            prev = g[g["timestamp"] < ex_day]
            # 除权日前净持仓（open=+ / close=−；T+1 下当日买入亦在登记日在手）
            held = sum(r["volume"] if r["action"] == "open" else -r["volume"]
                       for _, r in prev.iterrows())
            if held <= 0:
                continue
            idx_prior = fs.index[fs.index < ex_day]
            f_prev = float(fs.loc[idx_prior[-1]]) if len(idx_prior) else 1.0
            day_rows = store[store["date"].dt.date < ex_day.date()]
            if not len(day_rows):
                continue
            raw_prev_close = float(day_rows.iloc[-1]["close"])
            div_ps = raw_prev_close * (1 - f_prev / float(f_new))
            total += held * div_ps
            rows.append((sym, str(ex_day.date()), int(held), raw_prev_close,
                         round(div_ps, 4), round(held * div_ps)))

    df = pd.DataFrame(rows, columns=["symbol", "ex_day", "股数", "昨收raw",
                                     "每股红利", "股息"])
    print(f"=== 持仓期股息明细（{len(df)} 次除权日命中持仓）===")
    print(df.to_string(index=False))
    div_pp = total / CAPITAL * 100
    gap = DUAL_RETURN - LEGACY_RETURN
    print(f"\n股息总额: {total:,.0f} 元 / 初始资金 {CAPITAL:,.0f}")
    print(f"股息内含贡献: {div_pp:+.2f}pp（一阶近似，未复合再投资）")
    print(f"总差 {gap:+.2f}pp = 股息内含 {div_pp:+.2f}pp + 信号效应残差 {gap - div_pp:+.2f}pp"
          "（含再投资复合与交互项）")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else
         "bt_double_ma_cross_60min_2020-01-01_2026-11-18_20261120_153133")
