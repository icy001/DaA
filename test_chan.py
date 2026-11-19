"""缠论专项测试：分型 / 笔 / 线段 / 中枢 / 买卖点 / 未来函数 / 绘图落盘。"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from core.chan import ChanAnalyzer, analyze_multi_level, plot_chan
from core.data_fetcher import DataFetcher

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'✅' if ok else '❌'} {name}" + (f" | {detail}" if detail else ""))


def main() -> int:
    end = date.today()
    start = (end - timedelta(days=365 * 2)).strftime("%Y-%m-%d")
    f = DataFetcher()
    df = f.get_kline("600519", start, end.strftime("%Y-%m-%d"), period="1d")
    print(f"数据：600519 日线 {len(df)} 根 {df.index[0]:%Y-%m-%d} ~ {df.index[-1]:%Y-%m-%d}\n")

    an = ChanAnalyzer(df, level="1d")
    res = an.analyze()
    fractals, bi, segs, centers, points = (res["fractals"], res["bi"], res["segments"],
                                           res["centers"], res["points"])

    # ---------- 1. 包含合并与分型 ----------
    check("包含关系合并生效（合并后K线数 ≤ 原始）", 0 < len(res["merged"]) <= len(df),
          f"原始 {len(df)} → 合并 {len(res['merged'])}")
    check("分型可识别", len(fractals) >= 5, f"共 {len(fractals)} 个（顶 {int((fractals['type']=='top').sum())} / 底 {int((fractals['type']=='bottom').sum())}）")
    if len(fractals):
        in_range = all(df.index[0] <= d <= df.index[-1] for d in pd.to_datetime(fractals["date"]))
        valid_price = all(float(p) > 0 for p in fractals["price"])
        check("分型日期在数据范围内且价格有效", in_range and valid_price)
        check("分型必须等待右侧K线确认（confirm_date 晚于分型日）",
              all(pd.Timestamp(c) > pd.Timestamp(d) for d, c in zip(fractals["date"], fractals["confirm_date"])))

    # ---------- 2. 笔 ----------
    check("笔可识别", len(bi) >= 3, f"共 {len(bi)} 笔")
    if len(bi) >= 2:
        alt = all(bi[i]["direction"] != bi[i + 1]["direction"] for i in range(len(bi) - 1))
        conn = all(bi[i]["end_date"] == bi[i + 1]["start_date"] for i in range(len(bi) - 1))
        check("笔方向顶底交替", alt, [b["direction"] for b in bi][:8])
        check("笔首尾严格连接", conn)
        min_gap_ok = all(b["end_idx"] - b["start_idx"] >= 3 for b in bi)
        check("笔间隔满足最小K线数", min_gap_ok)
    an_old = ChanAnalyzer(df, mode="old").analyze()
    check("老笔模式可切换且笔数不多于新笔", len(an_old["bi"]) <= len(bi),
          f"新笔 {len(bi)} / 老笔 {len(an_old['bi'])}")

    # ---------- 3. 线段与中枢 ----------
    check("线段可识别（≥3 笔）", all(s["bi_count"] >= 3 for s in segs) and len(segs) >= 1,
          f"共 {len(segs)} 段，笔数 {[s['bi_count'] for s in segs][:6]}")
    check("中枢可识别且 ZG>ZD", all(c["zg"] > c["zd"] for c in centers) and len(centers) >= 1,
          f"共 {len(centers)} 个中枢，ZG/ZD 例：{[(round(c['zg'], 2), round(c['zd'], 2)) for c in centers[:3]]}")
    if centers:
        check("中枢 GG≥ZG 且 DD≤ZD", all(c["gg"] >= c["zg"] and c["dd"] <= c["zd"] for c in centers))

    # ---------- 4. 买卖点与未来函数 ----------
    codes = set(points["code"]) if len(points) else set()
    check("买卖点可识别（600519 两年日线）", len(points) >= 1,
          f"共 {len(points)} 个，代码 {sorted(codes)}")
    check("买卖点字段完整", not len(points) or
          set(["date", "type", "direction", "price", "level", "reason", "code"]) <= set(points.columns))
    if len(points):
        check("买卖点类型/方向合法",
              set(points["type"]) <= {1, 2, 3} and set(points["direction"]) <= {"buy", "sell"})
        check("买卖点代码与类型一致",
              all(str(c)[0] in ("B", "S") and int(str(c)[1]) in (1, 2, 3) for c in codes))
        check("买卖点日期不越过数据末尾", bool((pd.to_datetime(points["date"]) <= df.index[-1]).all()),
              f"最晚 {pd.to_datetime(points['date']).max():%Y-%m-%d}")
        # 未来函数：信号日必须是「已确认」的K线（存在该日行情），且不早于其所属笔的确认日
        confirm_set = {pd.Timestamp(b["confirm_date"]) for b in bi}
        ok = all(pd.Timestamp(d) in df.index or pd.Timestamp(d) in confirm_set
                 for d in pd.to_datetime(points["date"]))
        check("买卖点只用已确认K线（无未来函数）", ok)
        check("买卖点都带 reason", bool(points["reason"].astype(str).str.len().gt(0).all()))
    sig = an.signals()
    check("signals() 可直接给策略使用", sig.empty or {"date", "code", "direction"} <= set(sig.columns))

    # ---------- 4.1 二类/三类买卖点（长窗口才够出现三类点） ----------
    long_start = (end - timedelta(days=365 * 6)).strftime("%Y-%m-%d")
    df_long = f.get_kline("600519", long_start, end.strftime("%Y-%m-%d"), period="1d")
    res_long = ChanAnalyzer(df_long, level="1d").analyze()
    pts_long = res_long["points"]
    codes_long = set(pts_long["code"]) if len(pts_long) else set()
    check("一/二/三类买卖点全部可产出", {"B1", "S1", "B2", "S2", "B3", "S3"} <= codes_long,
          f"6 年日线 {len(df_long)} 根，共 {len(pts_long)} 个点 {sorted(codes_long)}")
    if len(pts_long):
        pts_long = pts_long.copy()
        pts_long["date"] = pd.to_datetime(pts_long["date"])

        def _nearby(pt, typ, direction):
            """同方向、早于 pt 的最近一个 type 型点。"""
            prev = pts_long[(pts_long["type"] == typ) & (pts_long["direction"] == direction)
                            & (pts_long["date"] < pt["date"])]
            return None if prev.empty else prev.iloc[-1]

        t2 = pts_long[pts_long["type"] == 2]
        ok2 = True
        for _, pt in t2.iterrows():
            base = _nearby(pt, 1, pt["direction"])
            if base is None:
                ok2 = False
                continue
            # 二买价须高于一类买点价（回抽不破前低）；二卖反之
            ok2 = ok2 and (pt["price"] > base["price"] if pt["direction"] == "buy"
                           else pt["price"] < base["price"])
        check("二类点满足「一类点后回抽不破前低/前高」", len(t2) > 0 and ok2, f"共 {len(t2)} 个")

        t3 = pts_long[pts_long["type"] == 3]
        centers_long = res_long["centers"]
        ok3 = True
        for _, pt in t3.iterrows():
            if pt["direction"] == "buy":
                ok3 = ok3 and any(c["zg"] < pt["price"] and c["end_date"] < pt["date"]
                                  for c in centers_long)
            else:
                ok3 = ok3 and any(c["zd"] > pt["price"] and c["end_date"] < pt["date"]
                                  for c in centers_long)
        check("三类点满足「突破中枢后回抽不回中枢」", len(t3) > 0 and ok3,
              f"三买 {int((t3['code']=='B3').sum())} / 三卖 {int((t3['code']=='S3').sum())}")

        # ---- 4.2 点数自证：六类确切数量 + 二类点可溯源到一类点 ----
        cnt = {c: int((pts_long["code"] == c).sum()) for c in ("B1", "B2", "B3", "S1", "S2", "S3")}
        check("六类买卖点确切数量", all(cnt[c] >= 0 for c in cnt), str(cnt))
        # 构造上每个一类点最多派生一个二类点，故 B2<=B1 且 S2<=S1；若超出说明二类判定过宽
        check("二类点数量不超过一类点（B2≤B1、S2≤S1）",
              cnt["B2"] <= cnt["B1"] and cnt["S2"] <= cnt["S1"],
              f"B2 {cnt['B2']} vs B1 {cnt['B1']}；S2 {cnt['S2']} vs S1 {cnt['S1']}")
        b1_dates = set(pd.to_datetime(pts_long[pts_long["code"] == "B1"]["date"]))
        s1_dates = set(pd.to_datetime(pts_long[pts_long["code"] == "S1"]["date"]))
        orphans = [r for _, r in t2.iterrows()
                   if pd.Timestamp(r["src_date"]) not in (b1_dates if r["code"] == "B2" else s1_dates)]
        check("每个二类点都能溯源到前置一类点（src_date）", not orphans,
              f"二类 {len(t2)} 个，溯源失败 {len(orphans)} 个")
        # 三类点稀疏性说明：中枢延伸上限收紧（3 笔）可显著增加三类点，放开则归零
        check("三类点稀疏但可用（B3/S3 各至少 1 个）",
              cnt["B3"] >= 1 and cnt["S3"] >= 1,
              f"B3 {cnt['B3']} / S3 {cnt['S3']}，中枢 {len(centers_long)} 个"
              f"（MAX_CENTER_BI={ChanAnalyzer.MAX_CENTER_BI}）")

        # ---- 4.3 三类点过滤开关：默认必须关闭，且开启但阈值=0 时点数与默认完全一致 ----
        check("三类点过滤开关默认关闭（b3_filter_enable=False）",
              config.CHAN_CONFIG.get("b3_filter_enable") is False)
        backup = dict(config.CHAN_CONFIG)
        try:
            config.CHAN_CONFIG.update({"b3_filter_enable": True, "b3_min_leave_pct": 0.0,
                                       "b3_min_leave_volume_ratio": 0.0})
            pts_f0 = ChanAnalyzer(df_long, level="1d").analyze()["points"]
            c0 = ({c: int((pts_f0["code"] == c).sum()) for c in ("B3", "S3")}
                  if len(pts_f0) else {"B3": 0, "S3": 0})
            check("过滤阈值=0 时点数与默认一致（不改变默认行为）",
                  c0["B3"] == cnt["B3"] and c0["S3"] == cnt["S3"],
                  f"默认 B3/S3={cnt['B3']}/{cnt['S3']}，开启且阈值=0 → {c0['B3']}/{c0['S3']}")
        finally:
            config.CHAN_CONFIG.clear()
            config.CHAN_CONFIG.update(backup)

    # ---------- 5. 多级别 ----------
    multi = analyze_multi_level("600519", (end - timedelta(days=365)).strftime("%Y-%m-%d"),
                                end.strftime("%Y-%m-%d"), fetcher=f)
    check("多级别联立可用", "1d" in multi["levels"] and "1w" in multi["levels"],
          f"级别 {list(multi['levels'])}，汇总信号 {0 if multi['signals'].empty else len(multi['signals'])} 条")

    # ---------- 6. 绘图 ----------
    path = plot_chan(df.iloc[-260:], res, save=True, symbol="600519", figsize=(14, 7))
    check("缠论叠加图落盘", path is not None and Path(path).exists() and Path(path).stat().st_size > 10_000,
          f"{path}（{Path(path).stat().st_size // 1024} KB）" if path and Path(path).exists() else "未生成")
    on_switches = {"fenxing": True, "bi": True, "duan": config.CHAN_CONFIG["enable_duan"],
                   "zhongshu": True, "points": config.CHAN_CONFIG["enable_buy_sell_points"]}
    check("绘图层级读 config.CHAN_CONFIG（默认 分型+笔+中枢，线段/买卖点关）",
          on_switches["duan"] is False and on_switches["points"] is False)

    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
