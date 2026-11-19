"""形态标注专项测试：均线金叉死叉 / MACD 背离 / 关键位突破（含未来函数红线）。

用构造数据验证点位的正确性，不依赖网络。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.pattern_annotate import (DEFAULT_PATTERNS, annotate_all, mark_breakout,
                                   mark_ma_cross, mark_macd_divergence)

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'✅' if ok else '❌'} {name}" + (f" | {detail}" if detail else ""))


def make_df(closes, start="2024-01-01", freq="B") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(closes), freq=freq)
    close = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"open": close.shift(1).fillna(close.iloc[0]),
                         "high": close + 0.6, "low": close - 0.6,
                         "close": close, "volume": 1_000_000.0, "amount": close * 1_000_000}, index=idx)


def main() -> int:
    # ---------- 1. 均线金叉死叉 ----------
    seg = [100 - i * 0.5 for i in range(40)]          # 下跌
    seg += [80 + i * 0.8 for i in range(40)]          # 上涨 → 金叉
    seg += [112 - i * 0.8 for i in range(40)]         # 下跌 → 死叉
    df = make_df(seg)
    ma = mark_ma_cross(df, fast=5, slow=20)
    golden = ma[ma["sub"] == "golden"]
    death = ma[ma["sub"] == "death"]
    check("均线金叉可识别", len(golden) >= 1, f"金叉 {len(golden)} 个：{[d.date().isoformat() for d in golden.index]}")
    check("均线死叉可识别", len(death) >= 1, f"死叉 {len(death)} 个：{[d.date().isoformat() for d in death.index]}")
    ma5, ma20 = df["close"].rolling(5).mean(), df["close"].rolling(20).mean()
    ok_cross = all(ma5.loc[d] > ma20.loc[d] for d in golden.index) and \
        all(ma5.loc[d] < ma20.loc[d] for d in death.index)
    check("金叉/死叉点位方向正确", ok_cross)

    # ---------- 2. MACD 金叉死叉 + 顶背离 ----------
    p1 = [100 + i * 1.25 for i in range(16)]          # 急涨到 120（峰1，动能大）
    p2 = [120 - i * 1.0 for i in range(15)]           # 回调到 105
    p3 = [105 + i * 0.7 for i in range(24)]           # 缓涨到 121（峰2，价格更高、动能更小）
    p4 = [121 - i * 1.2 for i in range(18)]
    p5 = [100 - i * 0.4 for i in range(10)]
    close = [98] * 6 + p1 + p2 + p3 + p4 + p5
    df2 = make_df(close)
    md = mark_macd_divergence(df2, min_gap=5, confirm_right=2, order=3)
    crosses = md[md["kind"] == "macd_cross"]
    divs = md[md["kind"] == "macd_div"]
    check("MACD 金叉/死叉可识别", len(crosses) >= 2, f"共 {len(crosses)} 个")
    check("顶背离可识别", (divs["sub"] == "top").any(),
          f"背离 {len(divs)} 个：{[(d.date().isoformat(), v['sub']) for d, v in divs.iterrows()]}")

    # 背离标注必须晚于极值、且不越过数据末尾（未来函数红线）
    no_future = all(d <= df2.index[-1] for d in md.index)
    lagged = all("极值日" in str(v["detail"]) and
                 pd.Timestamp(str(v["detail"]).split("确认于")[0].replace("极值日 ", "").strip()) < d
                 for d, v in divs.iterrows()) if len(divs) else False
    check("背离标注不越过数据末尾", no_future)
    check("背离标注晚于极值日（确认后才标）", lagged)

    # 末尾未确认的极值不得标注
    df3 = df2.iloc[:-1]
    md3 = mark_macd_divergence(df3)
    check("末根未走完不产生未来标注", all(d <= df3.index[-1] for d in md3.index))

    # ---------- 3. 突破/跌破 ----------
    base = [100 + (1 if i % 2 == 0 else -1) * 1.0 for i in range(40)]
    base += [103, 108, 112, 115, 118]                  # 向上突破前 20 日高点
    base += [110, 104, 98, 92, 88]                     # 向下跌破前 20 日低点
    df4 = make_df(base)
    br = mark_breakout(df4, window=20)
    ups, downs = br[br["kind"] == "breakout"], br[br["kind"] == "breakdown"]
    check("突破压力位可标注", len(ups) >= 1, f"{[d.date().isoformat() for d in ups.index]}")
    check("跌破支撑位可标注", len(downs) >= 1, f"{[d.date().isoformat() for d in downs.index]}")

    # ---------- 4. 开关与范围 ----------
    default_on = annotate_all(df)
    all_on = annotate_all(df, {"ma_cross": True, "macd_div": True, "breakout": True})
    check("默认只开均线标注", set(default_on["kind"]) <= {"ma_cross"},
          f"默认 kinds={sorted(set(default_on['kind']))}")
    check("全开后标注种类增加", len(set(all_on["kind"])) >= len(set(default_on["kind"])))
    in_range = all(df.index[0] <= d <= df.index[-1] for d in all_on.index)
    check("标注日期都在数据范围内", in_range,
          f"{all_on.index.min()} ~ {all_on.index.max()} ⊆ {df.index[0]} ~ {df.index[-1]}")
    check("DEFAULT_PATTERNS 默认值正确", DEFAULT_PATTERNS ==
          {"ma_cross": True, "macd_div": False, "breakout": False})

    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：", FAIL)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
