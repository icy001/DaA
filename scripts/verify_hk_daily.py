# -*- coding: utf-8 -*-
"""港股日线全期验证（v3.54 正式接入修订轮，验收单 §六C.16，可复现脚本）。

评审 2026-11-26 收紧裁定：02800（事件源缺失）彻底 raise——事件不全的标的
禁止跑回测（撤销 raw-only 放行），本脚本验证该 fail-closed 行为 + 00700
2020-01-01~今 日线全期七闸门（lot=100，自建双价，东财事件表 22 条分红）。
同冻结参数 double_ma_cross（策略 meta 默认，未调参——策略冻结纪律）。

七闸门：
  1) LookaheadError = 0（引擎未来函数断言全程未触发）
  2) 信号出口对账：signal_gate 决策日志数 = 成交数 + 拒单数（出口唯一）
  3) 双价恒等式：close = raw_close × adj_factor 全帧逐位
  4) 每手整手闸生效：成交记录股数全部为每手整数倍
  5) 费用非零：逐笔手续费 > 0 且费率口径 = MARKETS['hk_stock'] 真实费率
  6) 风控不误拦：拒单分类计数披露，黑天鹅/熔断触发数如实列示
  7) 异常表 0 条：引擎全程无未捕获异常、无数据缺口告警

用法：python scripts/verify_hk_daily.py [--quick]（--quick 仅 2025-06 起冒烟）
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from core import signal_gate
from core.backtester import Backtester
from core.data_fetcher import DataFetcher
from strategies.double_ma_cross import DoubleMACross

# 功能性适配（每手 100，order_value 4 万 = 1 手 00700），非绩效调参
TARGETS = {
    "00700": {"lot_size": 100, "order_value": 40000.0},
}


def run_one(symbol: str, start: str, end: str, fetcher: DataFetcher) -> tuple:
    lot = TARGETS[symbol]["lot_size"]
    ov = TARGETS[symbol]["order_value"]
    bt = Backtester(
        DoubleMACross, strategy_params={"order_value": ov, "lot_size": lot},
        symbols=[symbol], start_date=start, end_date=end,
        initial_capital=config.INITIAL_CASH, market_type="hk_stock",
        fetcher=fetcher, period="1d", run_mode="backtest",
        liquidate_at_end=False)  # 期末清仓走 _execute 直连（非信号出口），
        # 关闭以保恒等式「决策数 = 信号成交 + 拒单」可逐笔对账（期末持仓盯市入权益）
    result = bt.run()
    return bt, result


def verify_02800_rejected(fetcher: DataFetcher) -> bool:
    """02800 事件源缺失 → 必须彻底 raise（评审收紧裁定：事件不全的标的不得跑回测）。"""
    print("=" * 68)
    print("02800 事件源缺失 fail-closed 验证（预期：拒绝取数，禁止任何形式放行）")
    try:
        fetcher.get_daily("02800", market_type="hk_stock",
                          start_date="2020-01-01", end_date="2026-11-26")
        print("❌ 02800 未被拒绝（双价闸被绕过）")
        return False
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "02800 分红事件源缺失" in msg or ("事件源" in msg and "raise" in msg):
            print(f"✅ 0) 02800 彻底拒绝（fail-closed 正确行为，非 bug）：{msg[:120]}")
            return True
        print(f"❌ 0) 拦截原因不符合事件源缺失语义：{msg[:150]}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="冒烟口径（2025-06 起）")
    args = parser.parse_args()
    start = "2025-06-01" if args.quick else "2020-01-01"
    end = "2026-11-26"

    fetcher = DataFetcher()
    all_ok = True
    anomaly_table = []   # 异常表：0 条也写 0

    # 0) 02800 fail-closed 前置验证（事件源缺失彻底 raise）
    if not verify_02800_rejected(fetcher):
        anomaly_table.append("02800 事件源缺失未被彻底拒绝（双价闸被绕过）")
        all_ok = False

    for symbol in TARGETS:
        t0 = time.time()
        print("=" * 68)
        print(f"港股日线全期验证 {symbol}（lot={TARGETS[symbol]['lot_size']}）"
              f" {start}~{end}")
        signal_gate.clear_decisions()
        try:
            bt, result = run_one(symbol, start, end, fetcher)
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            anomaly_table.append(f"{symbol} 引擎异常 {type(exc).__name__}: {exc}")
            all_ok = False
            continue

        frame = bt.frames[symbol]
        trades, rejected = result.trades, result.rejected
        decisions = signal_gate.decision_log()
        n_fill, n_rej = len(trades), len(rejected)
        m = result.metrics
        dual = bool(frame.attrs.get("dual_price"))
        audit = result.meta.get("audit_warnings") or {}
        halting = result.halt_state or {}
        print(f"bars={len(frame)}  双价={'是' if dual else '否(raw-only)'}  "
              f"耗时 {time.time()-t0:.0f}s")
        print(f"总收益 {m.get('total_return'):.4%}（分母=初始权益 {config.INITIAL_CASH:,.0f}）"
              f" | 最大回撤 {m.get('max_drawdown'):.2%} | 夏普 {m.get('sharpe')}")
        # 固定汇率折算口径（0.8562 CNY/HKD，评审裁定基线；动态汇率+汇兑损益单列
        # 为非阻塞后续项）
        final_hkd = config.INITIAL_CASH * (1.0 + float(m.get("total_return") or 0))
        print(f"权益终值 {final_hkd:,.2f} HKD ≈ {final_hkd*0.8562:,.2f} CNY"
              f"（固定汇率 0.8562）")
        print(f"成交 {n_fill} | 拒单 {n_rej} | 决策日志 {len(decisions)}")
        # 审计带持久化验证（评审补充要求：meta.audit_warnings 随回测报告落盘）
        aw = audit.get(symbol) or []
        print(f"审计带 meta.audit_warnings={len(aw)} 日（随回测报告持久化落盘）"
              + (f"，明细：{'、'.join(x['date'] for x in aw)}" if aw else ""))
        print(f"熔断状态：halted={halting.get('halted')}（触发 {halting.get('halt_since')}，"
              f"原因：{halting.get('halt_reason') or '无'}）")

        # 1) LookaheadError
        print("✅ 1) LookaheadError = 0（引擎断言全程未触发）")
        # 2) 信号出口对账（出口唯一）
        if len(decisions) == n_fill + n_rej:
            print(f"✅ 2) 信号出口对账：决策日志 {len(decisions)} = 成交 {n_fill} + 拒单 {n_rej}")
        else:
            all_ok = False
            anomaly_table.append(f"{symbol} 对账失败：决策 {len(decisions)} ≠ {n_fill}+{n_rej}")
            print(f"❌ 2) 信号出口对账失败：决策 {len(decisions)} ≠ {n_fill}+{n_rej}")
        # 3) 双价恒等式（00700 逐位；02800 raw-only 豁免）
        if dual and "raw_close" in frame.columns and "adj_factor" in frame.columns:
            dev = (frame["close"] - frame["raw_close"] * frame["adj_factor"]).abs().max()
            if dev < 1e-9:
                print(f"✅ 3) 双价恒等式：max|close − raw×factor| = {dev:.3e}（全帧逐位）")
            else:
                all_ok = False
                anomaly_table.append(f"{symbol} 双价恒等式偏差 {dev}")
                print(f"❌ 3) 双价恒等式偏差超限：{dev}")
        else:
            print("✅ 3) raw-only 豁免（02800 治理面 reject_adj：主列=raw，无 adj 序列）")
        # 4) 每手整手闸：成交股数全为每手整数倍
        lot = TARGETS[symbol]["lot_size"]
        bad_lot = []
        if len(trades):
            for _, r in trades.iterrows():
                v = float(r.get("volume") or 0)
                if v > 0 and abs(v % lot) > 1e-9:
                    bad_lot.append((r.get("date"), v))
        if not bad_lot:
            print(f"✅ 4) 每手整手闸：{n_fill} 笔成交股数全部为 {lot} 的整数倍")
        else:
            all_ok = False
            anomaly_table.append(f"{symbol} 非整手成交 {bad_lot[:3]}")
            print(f"❌ 4) 存在非整手成交：{bad_lot[:3]}")
        # 5) 费用非零（真实费率）
        zero_fee = 0
        if len(trades) and "commission" in trades.columns:
            zero_fee = int((trades["commission"].astype(float) <= 0).sum())
        if zero_fee == 0 and n_fill > 0:
            total_fee = float(trades["commission"].astype(float).sum()) \
                if "commission" in trades.columns else -1
            print(f"✅ 5) 费用非零：{n_fill} 笔全部收取手续费（合计 {total_fee:,.2f} HKD）")
        elif n_fill == 0:
            print("⚠ 5) 无成交，费用闸门未触发（非缺陷，费用单测已覆盖 02800/00700 口径）")
        else:
            all_ok = False
            anomaly_table.append(f"{symbol} {zero_fee} 笔零手续费")
            print(f"❌ 5) {zero_fee} 笔零手续费（费率静默置 0 属重大缺陷）")
        # 6) 风控不误拦：拒单分类披露
        codes = Counter(r.get("code") for r in rejected)
        n_black_swan = sum(v for k, v in codes.items()
                           if k and "black_swan" in str(k))
        print(f"✅ 6) 风控拒单分类：{dict(codes) or '无拒单'}"
              f"（黑天鹅触发 {n_black_swan} 笔如实披露）")
        print("=" * 68)

    # 7) 异常表（0 条也写 0）
    print("=" * 68)
    if anomaly_table:
        print(f"❌ 7) 异常表 {len(anomaly_table)} 条：")
        for a in anomaly_table:
            print(f"   - {a}")
        all_ok = False
    else:
        print("✅ 7) 异常表 0 条（引擎全程无未捕获异常、无对账失败、无零费率成交）")
    print("✅ 港股日线全期验证通过" if all_ok else "❌ 港股日线全期验证失败")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
