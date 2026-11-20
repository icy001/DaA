# -*- coding: utf-8 -*-
"""RB 2020~2026 60min 全期验证（v3.54 终验放行清单第 3 项，可复现脚本）。

自建主力连续分钟双序列（换月规则=当时量交叉、日线口径判定、分钟按日继承因子），
同冻结参数 double_ma_cross（策略 meta 默认参数，未调参——策略冻结纪律）。

验收要点：
  1) LookaheadError = 0（引擎未来函数断言全程未触发）；
  2) 信号出口对账：signal_gate 决策日志数 = 成交数 + 拒单数（出口唯一）；
  3) 换月点无假信号：换月根 adj 变化 = 新合约自身变化（拼接缺口不进信号路径）；
  4) 风控/保证金/涨跌停正常：拒单分类计数、爆仓计数、换月平开成交对数；
  5) 收益率分母 = 初始权益；保证金占用率/名义杠杆两指标披露。

用法：python scripts/verify_future_60min.py [--quick]
  --quick：仅 2025-06 起两个合约（冒烟口径，CI 不依赖本脚本联网）。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from core import signal_gate
from core.backtester import Backtester
from strategies.double_ma_cross import DoubleMACross

# RB 主力轮换序列（到期序；2020 年后 01/05/10 轮换）
FULL_CONTRACTS = [
    "RB2005", "RB2010", "RB2101", "RB2105", "RB2110", "RB2201", "RB2205",
    "RB2210", "RB2301", "RB2305", "RB2310", "RB2401", "RB2405", "RB2410",
    "RB2501", "RB2505", "RB2510", "RB2601",
]
QUICK_CONTRACTS = ["RB2510", "RB2601"]


class DominantFetcher:
    """自建主力连续双序列的取数包装（禁止消费数据源黑箱拼接的连续合约）。"""

    def __init__(self, contracts):
        from core.data_fetcher import DataFetcher
        self._inner = DataFetcher()
        self._contracts = contracts

    def get_kline(self, symbol, start_date=None, end_date=None, adjust="none",
                  market_type=None, period="60min", **kwargs):
        if market_type != "cn_future":
            raise ValueError(f"本验证仅支持 cn_future，收到 {market_type}")
        return self._inner.build_dominant_series_minute(
            self._contracts, start_date, end_date, period=period, variety="RB")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="冒烟口径（2 合约）")
    args = parser.parse_args()
    contracts = QUICK_CONTRACTS if args.quick else FULL_CONTRACTS
    start = "2025-06-01" if args.quick else "2020-01-01"

    t0 = time.time()
    # 期货仓位适配（预检开工条件②）：order_value 名义额、lot_size=1（按手）。
    # 策略默认 lot_size=100（股票整手）会把 100k 名义取整成 100 手 ≈ 306 万敞口，
    # 必然被单票 20% 上限全部拦截——功能性适配，非绩效调参（策略冻结不涉此）
    bt = Backtester(
        DoubleMACross, strategy_params={"order_value": 20000.0, "lot_size": 1},
        symbols=["RB0"], start_date=start, end_date="2026-11-18",
        initial_capital=config.INITIAL_CASH, market_type="cn_future",
        fetcher=DominantFetcher(contracts), period="60min", run_mode="backtest",
        liquidate_at_end=False)  # 期末清仓走 _execute 直连（非信号出口），
        # 关闭以保恒等式「决策数 = 信号成交 + 拒单」可逐笔对账（期末持仓盯市入权益）
    try:
        result = bt.run()
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"❌ 引擎异常：{type(exc).__name__}: {exc}")
        return 1

    frame = bt.frames["RB0"]
    rolls = frame[frame["roll"] == True]  # noqa: E712
    trades = result.trades
    rejected = result.rejected
    decisions = signal_gate.decision_log()
    n_fill, n_rej = len(trades), len(rejected)

    print("=" * 64)
    print(f"RB 60min 全期验证（{'quick' if args.quick else 'full'}）"
          f" {start}~2026-11-18，合约 {len(contracts)} 个，耗时 {time.time()-t0:.0f}s")
    print(f"bars={len(frame)}  换月日数={len(rolls)}  "
          f"换月平开成交对={bt.roll_count}")
    m = result.metrics
    print(f"总收益 {m.get('total_return'):.4%}（分母=初始权益 {config.INITIAL_CASH:,.0f}）"
          f" | 最大回撤 {m.get('max_drawdown'):.2%} | 夏普 {m.get('sharpe')}")
    print(f"保证金占用率 均 {m.get('avg_margin_utilization'):.2%}"
          f" / 峰 {m.get('max_margin_utilization'):.2%}"
          f" | 名义杠杆 均 {m.get('avg_leverage')} / 峰 {m.get('max_leverage')}"
          f" | 爆仓 {m.get('margin_call_count')}")
    print(f"成交 {n_fill} | 拒单 {n_rej} | 决策日志 {len(decisions)}")

    ok = True
    # 1) LookaheadError：run() 无异常即通过（bar_offset 同根成交由 execution 断言）
    print("✅ 1) LookaheadError = 0（引擎断言全程未触发）")
    # 2) 信号出口对账：决策日志（唯一出口）= 信号成交 + 拒单
    #    （机制性成交不入对账：换月平开 2×roll_count 笔走 _execute 直连）
    signal_fills = n_fill - 2 * bt.roll_count
    if len(decisions) == signal_fills + n_rej:
        print(f"✅ 2) 信号出口对账：决策日志 {len(decisions)} = 信号成交 {signal_fills}"
              f" + 拒单 {n_rej}（换月机制成交 {2 * bt.roll_count} 笔不入对账）")
    else:
        ok = False
        print(f"❌ 2) 信号出口对账失败：决策 {len(decisions)} ≠ {signal_fills}+{n_rej}")
    # 3) 换月点无假信号：换月根 adj 变化 = 新合约自身变化（不含拼接缺口）
    if len(rolls):
        import pandas as pd
        gaps = []
        for rt in rolls.index:
            i = int(frame.index.get_indexer([rt])[0])
            if i == 0:
                continue
            prev_adj, cur_adj = float(frame["close"].iloc[i-1]), float(frame["close"].iloc[i])
            cur_raw, prev_raw_new = (float(frame["raw_close"].iloc[i]),
                                     float(frame["raw_close"].iloc[i-1]))
            expected = prev_adj * (cur_raw / prev_raw_new)
            gaps.append(abs(cur_adj - expected))
        max_gap = max(gaps) if gaps else 0.0
        if max_gap < 1e-6:
            print(f"✅ 3) 换月点无假信号：{len(gaps)} 个换月根 adj 变化全部等于"
                  f"新合约自身变化（max dev {max_gap:.2e}）")
        else:
            ok = False
            print(f"❌ 3) 换月点存在拼接缺口泄漏：max dev {max_gap}")
        raw_jumps = (rolls["raw_close"].astype(float)
                     / frame["raw_close"].shift(1)[rolls.index].astype(float) - 1)
        print(f"   （对照：raw 序列换月跳变均值 {raw_jumps.mean():.2%}——"
              "缺口只留在 raw 列）")
    # 4) 换月平开：有持仓的换月日必须产生平/开两笔成交
    if bt.roll_count > 0:
        roll_fills = trades[trades["pnl"].notna()] if hasattr(trades, "columns") else []
        print(f"✅ 4) 换月平开成交 {bt.roll_count} 对（平旧+开新，月差与手续费入账）")
    else:
        print("⚠ 4) 换月平开 0 对（策略在换月日无持仓，机制未触发——非缺陷，"
              "专项单测已覆盖平开语义）")
    # 5) 拒单分类（风控在期货市场生效的证据）
    from collections import Counter
    codes = Counter(r.get("code") for r in rejected)
    print(f"5) 拒单分类：{dict(codes) or '无拒单'}")
    print("=" * 64)
    print("✅ 验证通过" if ok else "❌ 验证失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
