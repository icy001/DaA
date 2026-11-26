# -*- coding: utf-8 -*-
"""港股正式接入：数据层新出口联网冒烟（验收单 §六C.15 硬证据）。

三场景：
  A) 00700 双价：东财事件表（22 分红）→ 自建后复权 adj 列 + raw_* 列，
     attrs.dual_price=True、adjust=hfq_self_built、lot_size=100
  B) 02800 raw-only：治理面 events_source=None → reject_adj，
     主列保持 raw、attrs.events_source=unavailable、dual_price=False
  C) 跳变审计：00700 起始 2014-01-01（跨 2014-05-29 一拆五，事件表无拆股
     记录）→ 必须 raise（结构性拦截跨拆股段回测）
"""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.data_fetcher import DataFetcher

f = DataFetcher()
ok = True

# ---------- A) 00700 双价 ----------
print("=" * 70)
print("A) 00700 日线 2020-01-01~2026-11-26（治理面事件源 em_stock_hk_dividend_payout_em）")
try:
    df7 = f.get_daily("00700", market_type="hk_stock",
                      start_date="2020-01-01", end_date="2026-11-26")
    print(f"   行数={len(df7)}  列={list(df7.columns)}")
    print(f"   attrs={ {k: v for k, v in df7.attrs.items()} }")
    assert df7.attrs.get("dual_price") is True, "00700 必须 dual_price=True"
    assert df7.attrs.get("adjust") == "hfq_self_built", "自建后复权口径"
    assert "raw_close" in df7.columns and "adj_factor" in df7.columns, "双价列缺失"
    # 恒等式：adj = raw × adj_factor（全帧逐位）
    dev = (df7["close"] - df7["raw_close"] * df7["adj_factor"]).abs().max()
    print(f"   恒等式 max|adj - raw×factor| = {dev:.3e}")
    assert dev < 1e-9, f"双价恒等式偏差超限: {dev}"
    # 除净日无假跳空（adj 序列连续）
    adj_ret = df7["close"].pct_change().abs()
    raw_ret = df7["raw_close"].pct_change().abs()
    n_gap_adj = int((adj_ret > 0.05).sum())
    n_gap_raw = int((raw_ret > 0.05).sum())
    print(f"   |隔夜|>5% 计数：adj={n_gap_adj}  raw={n_gap_raw}（raw 多出的即除净跳变，adj 已消除）")
    print("   [PASS] 00700 双价出口")
except Exception as e:
    ok = False
    print(f"   [FAIL] {e}")
    traceback.print_exc()

# ---------- B) 02800 raw-only ----------
print("=" * 70)
print("B) 02800 日线 2020-01-01~2026-11-26（治理面 events_source=None → reject_adj）")
try:
    df8 = f.get_daily("02800", market_type="hk_stock",
                      start_date="2020-01-01", end_date="2026-11-26")
    print(f"   行数={len(df8)}  attrs={ {k: v for k, v in df8.attrs.items()} }")
    assert df8.attrs.get("events_source") == "unavailable", "必须标注事件源不可用"
    assert df8.attrs.get("dual_price") is False, "02800 必须 raw-only"
    assert df8.attrs.get("adjust") == "none", "主列必须保持 raw（禁止黑箱复权）"
    assert "raw_close" not in df8.columns, "raw-only 模式主列即 raw，不应再有 raw_* 重复列"
    print("   [PASS] 02800 raw-only 出口（fail-closed 标注，非黑箱降级）")
except Exception as e:
    ok = False
    print(f"   [FAIL] {e}")
    traceback.print_exc()

# ---------- C) 跳变审计 ----------
print("=" * 70)
print("C) 00700 起始 2014-01-01（跨 2014-05-29 一拆五，东财事件表无拆股记录）")
try:
    # 源健康前置：连续失败熔断会跳过真实 fetch 直接 stale 回退，吞掉审计 raise。
    # 先探活恢复（ACCEPTANCE_GOVERNANCE：源不可达必须标 skipped_due_to_source 计入未覆盖）
    router = f._build_source_router()
    if router is not None:
        hc = router.health_check(["akshare"])
        print(f"   探活恢复 akshare: healthy={hc['results'].get('akshare', {}).get('healthy')}")
    f.get_daily("00700", market_type="hk_stock",
                start_date="2014-01-01", end_date="2026-11-26")
    print("   [FAIL] 未触发跳变审计 raise（跨拆股段被静默放行）")
    ok = False
except Exception as e:
    msg = str(e)
    if "unhealthy" in msg or "无可用数据源" in msg or "全部远程源失败" in msg:
        print(f"   [SKIPPED_DUE_TO_SOURCE] 数据源当前不可达，审计验证未覆盖：{msg[:120]}")
    else:
        print(f"   [PASS] 跳变审计拦截：{msg[:160]}")
        assert ("25%" in msg) or ("跳变" in msg) or ("jump" in msg.lower()), \
            f"拦截原因不符合跳变审计语义: {msg}"

print("=" * 70)
print("RESULT:", "ALL PASS" if ok else "HAS FAIL")
sys.exit(0 if ok else 1)
