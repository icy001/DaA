"""缠论核心计算：包含关系合并 → 分型 → 笔 → 线段 → 中枢 → 买卖点 → 多级别。

全部结构都带「确认时点」（confirm_date）：
分型/笔必须等右侧K线走完才成立，买卖点只在确认后给出，
因此 `signals()` 可直接用于策略而不会引入未来函数。

⚠️ 边界说明：震荡行情中笔、线段的自动划分本身存在多种学派与歧义，
本实现为工程化近似（新笔/老笔可切换、线段用特征序列简化判定），
与人工划分可能有出入；争议区域请人工核对K线，不要盲信自动结果。
"""
from __future__ import annotations

from typing import List, Optional

import pandas as pd

import config

CHAN = config.CHAN_CONFIG


# ==================== 基础工具 ====================

def _bars(df: pd.DataFrame) -> List[dict]:
    return [{"date": pd.Timestamp(idx), "open": float(r["open"]), "high": float(r["high"]),
             "low": float(r["low"]), "close": float(r["close"]), "start": pd.Timestamp(idx),
             "end": pd.Timestamp(idx), "n": 1}
            for idx, r in df.iterrows()]


class ChanAnalyzer:
    """输入标准 OHLCV DataFrame（date 索引），输出分型/笔/线段/中枢/买卖点。

    ⚠️ 本实现为「轻量缠论」：包含合并/分型/笔/线段/中枢/买卖点按工程近似实现，
    三类点（B3/S3）天然稀疏且对 `MAX_CENTER_BI` 高度敏感（无上限时实测归零）。
    实盘前必须人工核对 K 线，不要直接拿三类点当交易信号。
    """

    # 单个中枢最多覆盖的笔数（工程折中，非缠论原文约束；见 find_centers 注释）
    MAX_CENTER_BI = 9

    def __init__(self, df: pd.DataFrame, level: str = "1d", mode: str = None,
                 min_k: int = None):
        need = {"open", "high", "low", "close"}
        missing = need - set(df.columns)
        if missing:
            raise ValueError(f"缠论需要列 {sorted(need)}，缺少 {sorted(missing)}")
        self.df = df.copy()
        self.df.index = pd.DatetimeIndex(self.df.index)
        self.level = level
        self.mode = mode or CHAN.get("bi_type", "new")
        self.min_k = int(min_k or CHAN.get("bi_min_k", 5))
        self.merged: List[dict] = []
        self.fractals: pd.DataFrame = pd.DataFrame()
        self.bi: List[dict] = []
        self.segments: List[dict] = []
        self.centers: List[dict] = []
        self.points: pd.DataFrame = pd.DataFrame()
        self.doubt_ranges: List[dict] = []

    # ---------- 1. 包含关系合并 ----------
    def merge_inclusion(self) -> List[dict]:
        """按缠论规则合并有包含关系的相邻K线（向上取高高、向下取低低）。"""
        merged: List[dict] = []
        direction = 1
        for bar in _bars(self.df):
            if not merged:
                merged.append(dict(bar))
                continue
            last = merged[-1]
            inside = bar["high"] <= last["high"] and bar["low"] >= last["low"]
            outside = bar["high"] >= last["high"] and bar["low"] <= last["low"]
            if inside or outside:
                if direction > 0:
                    last["high"] = max(last["high"], bar["high"])
                    last["low"] = max(last["low"], bar["low"])
                else:
                    last["high"] = min(last["high"], bar["high"])
                    last["low"] = min(last["low"], bar["low"])
                last["close"] = bar["close"]
                last["end"] = bar["end"]
                last["n"] += bar["n"]
            else:
                direction = 1 if bar["high"] > last["high"] else -1
                merged.append(dict(bar))
        self.merged = merged
        return merged

    # ---------- 2. 分型 ----------
    def find_fractals(self) -> pd.DataFrame:
        """顶分型：中间K线高点最高且低点也最高；底分型反之。"""
        if not self.merged:
            self.merge_inclusion()
        m = self.merged
        rows = []
        for i in range(1, len(m) - 1):
            a, b, c = m[i - 1], m[i], m[i + 1]
            if b["high"] > a["high"] and b["high"] > c["high"] and \
                    b["low"] > a["low"] and b["low"] > c["low"]:
                rows.append({"idx": i, "date": b["date"], "type": "top",
                             "price": b["high"], "confirm_date": c["end"], "confirm_idx": i + 1})
            elif b["low"] < a["low"] and b["low"] < c["low"] and \
                    b["high"] < a["high"] and b["high"] < c["high"]:
                rows.append({"idx": i, "date": b["date"], "type": "bottom",
                             "price": b["low"], "confirm_date": c["end"], "confirm_idx": i + 1})
        self.fractals = pd.DataFrame(rows)
        return self.fractals

    # ---------- 3. 笔 ----------
    def find_strokes(self, mode: str = None) -> List[dict]:
        """顶底分型交替连成笔；同类型分型取更极端者。新笔≥4根合并K线、老笔≥5根。"""
        mode = mode or self.mode
        min_gap = 3 if str(mode).lower().startswith("new") else 4
        if self.fractals.empty:
            self.find_fractals()
        if self.fractals.empty:
            self.bi = []
            return self.bi
        strokes, last = [], None
        for _, f in self.fractals.iterrows():
            if last is None:
                last = f
                continue
            if f["type"] == last["type"]:
                more = f["price"] > last["price"] if f["type"] == "top" else f["price"] < last["price"]
                if more:
                    # 同类型取更极端者：若它正是上一笔的终点，则笔的终点随之延伸（保证笔首尾相连）
                    if strokes and strokes[-1]["end_date"] == last["date"]:
                        strokes[-1].update({"end_date": f["date"], "end_price": float(f["price"]),
                                            "end_idx": int(f["idx"]),
                                            "confirm_date": f["confirm_date"]})
                    last = f
                continue
            if f["idx"] - last["idx"] >= min_gap:
                strokes.append({"start_date": last["date"], "start_price": float(last["price"]),
                                "end_date": f["date"], "end_price": float(f["price"]),
                                "direction": "up" if f["type"] == "top" else "down",
                                "confirm_date": f["confirm_date"],
                                "start_idx": int(last["idx"]), "end_idx": int(f["idx"])})
                last = f
        self.bi = strokes
        return strokes

    # ---------- 4. 线段 ----------
    def find_segments(self, min_bi: int = None) -> List[dict]:
        """至少三笔成段；用「后续笔是否创出同向新极值」近似特征序列破坏判定。"""
        min_bi = int(min_bi or CHAN.get("duan_min_bi", 3))
        if not self.bi:
            self.find_strokes()
        segs, i = [], 0
        while i + min_bi - 1 < len(self.bi):
            start = self.bi[i]
            end = self.bi[i + min_bi - 1]
            direction = 1 if end["end_price"] > start["start_price"] else -1
            j = i + min_bi - 1
            while j + 1 < len(self.bi):
                nxt = self.bi[j + 1]
                if (direction > 0 and nxt["end_price"] > end["end_price"]) or \
                        (direction < 0 and nxt["end_price"] < end["end_price"]):
                    end, j = nxt, j + 1
                else:
                    break
            segs.append({"start_date": start["start_date"], "start_price": start["start_price"],
                         "end_date": end["end_date"], "end_price": end["end_price"],
                         "direction": "up" if direction > 0 else "down",
                         "bi_count": j - i + 1, "confirm_date": end["confirm_date"]})
            i = j + 1
        self.segments = segs
        return segs

    # ---------- 5. 中枢 ----------
    def find_centers(self, use: str = "bi") -> List[dict]:
        """连续三笔（或三段）重叠区间构成中枢：ZG=min(高点)、ZD=max(低点)。"""
        items = self.bi if use == "bi" else self.segments
        if not items:
            items = self.find_strokes() if use == "bi" else self.find_segments()
        centers = []
        i = 0
        while i + 2 < len(items):
            trio = items[i:i + 3]
            highs = [max(x["start_price"], x["end_price"]) for x in trio]
            lows = [min(x["start_price"], x["end_price"]) for x in trio]
            zg, zd = min(highs), max(lows)
            if zg <= zd:  # 无重叠，不成中枢
                i += 1
                continue
            gg, dd = max(highs), min(lows)
            end = trio[-1]
            j = i + 2
            # 延伸条件必须是「真重叠」：碰到 ZG/ZD 边界不算（否则一个中枢会顺着趋势
            # 无限吞掉后面几十笔，2 年日线只剩 1 个中枢，三买/三卖永远无法成立）。
            # 单中枢最多 9 笔的来由（工程折中，非缠论原文约束）：
            #   · 缠论原文对中枢延伸笔数没有上限，理论上可无限延伸；
            #   · 但全放开会让一个中枢吞掉整段趋势行情，三类点永不成立；
            #   · 9 笔 ≈ 3 个线段（线段最少 3 笔），恰好容纳「进入段 + 中枢震荡 + 离开段」；
            #   · 属工程近似：极端单边/超长横盘下可能误切或多切中枢，需人工核对（见 README 已知限制）。
            while j + 1 < len(items) and (j - i + 1) < self.MAX_CENTER_BI:
                nxt = items[j + 1]
                hi, lo = max(nxt["start_price"], nxt["end_price"]), min(nxt["start_price"], nxt["end_price"])
                if lo >= zg or hi <= zd:
                    break
                gg, dd = max(gg, hi), min(dd, lo)  # 延伸只扩展 GG/DD，ZG/ZD 保持前三笔确定
                end, j = nxt, j + 1
            centers.append({"start_date": trio[0]["start_date"], "end_date": end["end_date"],
                            "zg": float(zg), "zd": float(zd), "gg": float(gg), "dd": float(dd),
                            "level": self.level, "bi_count": j - i + 1,
                            "enter_date": trio[0]["start_date"], "leave_date": end["end_date"]})
            i = j + 1
        self.centers = centers
        return centers

    # ---------- 6. 买卖点 ----------
    def _macd_area(self, start: pd.Timestamp, end: pd.Timestamp) -> float:
        from core.pattern_annotate import macd_series
        _, _, hist = macd_series(self.df)
        seg = hist[(hist.index >= start) & (hist.index <= end)]
        return float(seg.sum()) if len(seg) else 0.0

    def _third_point_ok(self, center: dict, leave: dict, direction: str) -> bool:
        """三类点可选的「离开段幅度/放量」过滤（默认关闭，开关见 config.CHAN_CONFIG）。

        本实现是轻量缠论，三类点本就稀疏；该过滤只用于想要「放量突破」的更严格口径，
        默认不启用，保持与历史统计口径一致。
        """
        if not CHAN.get("b3_filter_enable", False):
            return True
        boundary = float(center["zg"] if direction == "buy" else center["zd"])
        move = abs(float(leave["end_price"]) - float(leave["start_price"])) / max(abs(boundary), 1e-9)
        leave_vol = self.df.loc[leave["start_date"]:leave["end_date"], "volume"]
        center_vol = self.df.loc[center["start_date"]:center["end_date"], "volume"]
        base = float(center_vol.mean()) if len(center_vol) else 0.0
        ratio = float(leave_vol.mean()) / base if len(leave_vol) and base > 0 else 0.0
        return (move >= float(CHAN.get("b3_min_leave_pct", 0.0))
                and ratio >= float(CHAN.get("b3_min_leave_volume_ratio", 0.0)))

    def find_buy_sell_points(self) -> pd.DataFrame:
        """一类（背驰）/二类（回抽不破）/三类（中枢突破回抽）。

        三类点可选开启「离开段幅度/放量」过滤（`config.CHAN_CONFIG["b3_filter_enable"]`，
        默认关闭）。

        所有信号日取「笔的确认日」（confirm_date，已在极值点右侧），不得用未来K线。
        笔的下标在同一份 self.bi 上是稳定的，因此二/三类点直接按下标定位后续笔，
        不靠日期过滤（日期过滤会把紧邻的反弹笔漏掉，导致 B2/B3 永远不成立）。
        """
        if not self.bi:
            self.find_strokes()
        if not self.centers:
            self.find_centers()
        points = []
        # ---- 一类买卖点：同向笔创新低/新高但 MACD 面积缩小（背驰）----
        # 相邻笔方向必然相反，同向笔要隔一笔比较：bi[i] 与 bi[i+2]
        for i in range(len(self.bi) - 2):
            a, b = self.bi[i], self.bi[i + 2]
            if a["direction"] != b["direction"]:
                continue
            area_a = self._macd_area(a["start_date"], a["end_date"])
            area_b = self._macd_area(b["start_date"], b["end_date"])
            if b["direction"] == "down" and b["end_price"] < a["end_price"] and abs(area_b) < abs(area_a):
                points.append({"date": b["confirm_date"], "type": 1, "direction": "buy",
                               "price": b["end_price"], "level": self.level, "bi_idx": i + 2,
                               "reason": f"下跌背驰（MACD面积 {area_b:.3f} < {area_a:.3f}）"})
            if b["direction"] == "up" and b["end_price"] > a["end_price"] and abs(area_b) < abs(area_a):
                points.append({"date": b["confirm_date"], "type": 1, "direction": "sell",
                               "price": b["end_price"], "level": self.level, "bi_idx": i + 2,
                               "reason": f"上涨背驰（MACD面积 {area_b:.3f} < {area_a:.3f}）"})
        # ---- 二类买卖点：一类点后第一次回抽不破前低/前高 ----
        # 一类点在第 k 笔末端 → 第 k+1 笔是反弹，第 k+2 笔是回抽
        for p in list(points):
            if p["type"] != 1:
                continue
            pull_idx = p["bi_idx"] + 2
            if pull_idx >= len(self.bi):
                continue
            pull = self.bi[pull_idx]
            if p["direction"] == "buy" and pull["direction"] == "down" and pull["end_price"] > p["price"]:
                points.append({"date": pull["confirm_date"], "type": 2, "direction": "buy",
                               "price": pull["end_price"], "level": self.level,
                               "src_date": p["date"],
                               "reason": f"二买：回抽 {pull['end_price']:.2f} 不破前低 {p['price']:.2f}"})
            if p["direction"] == "sell" and pull["direction"] == "up" and pull["end_price"] < p["price"]:
                points.append({"date": pull["confirm_date"], "type": 2, "direction": "sell",
                               "price": pull["end_price"], "level": self.level,
                               "src_date": p["date"],
                               "reason": f"二卖：反抽 {pull['end_price']:.2f} 不破前高 {p['price']:.2f}"})
        # ---- 三类买卖点：突破中枢后回抽不回中枢 ----
        for c in self.centers:
            leave_idx = next((k for k, b in enumerate(self.bi)
                              if b["start_date"] >= c["end_date"]), None)
            if leave_idx is None or leave_idx + 1 >= len(self.bi):
                continue
            leave, pull = self.bi[leave_idx], self.bi[leave_idx + 1]
            if leave["direction"] == "up" and leave["end_price"] > c["zg"] \
                    and pull["direction"] == "down" and pull["end_price"] > c["zg"] \
                    and self._third_point_ok(c, leave, "buy"):
                points.append({"date": pull["confirm_date"], "type": 3, "direction": "buy",
                               "price": pull["end_price"], "level": self.level,
                               "src_date": c["end_date"],
                               "reason": f"三买：突破 ZG={c['zg']:.2f} 后回抽 {pull['end_price']:.2f} 不回中枢"})
            if leave["direction"] == "down" and leave["end_price"] < c["zd"] \
                    and pull["direction"] == "up" and pull["end_price"] < c["zd"] \
                    and self._third_point_ok(c, leave, "sell"):
                points.append({"date": pull["confirm_date"], "type": 3, "direction": "sell",
                               "price": pull["end_price"], "level": self.level,
                               "src_date": c["end_date"],
                               "reason": f"三卖：跌破 ZD={c['zd']:.2f} 后反抽 {pull['end_price']:.2f} 不回中枢"})
        df = pd.DataFrame(points)
        if not df.empty:
            df = df.drop(columns=["bi_idx"])
            df["code"] = df.apply(lambda r: ("B" if r["direction"] == "buy" else "S") + str(r["type"]), axis=1)
            df = df.sort_values("date").drop_duplicates(subset=["date", "type", "direction"])
        self.points = df
        return df

    # ---------- 7. 汇总 ----------
    def analyze(self) -> dict:
        self.merge_inclusion()
        self.find_fractals()
        self.find_strokes()
        self.find_segments()
        self.find_centers()
        self.find_buy_sell_points()
        self.doubt_ranges = self._doubt_ranges()
        return {"fractals": self.fractals, "bi": self.bi, "segments": self.segments,
                "centers": self.centers, "points": self.points,
                "merged": self.merged, "level": self.level,
                "doubt_ranges": self.doubt_ranges}

    def _doubt_ranges(self) -> List[dict]:
        """震荡区提示：连续 3 笔以上振幅不足 2% 视为划分存疑。"""
        out = []
        for i in range(len(self.bi) - 2):
            trio = self.bi[i:i + 3]
            hi = max(max(b["start_price"], b["end_price"]) for b in trio)
            lo = min(min(b["start_price"], b["end_price"]) for b in trio)
            if hi > 0 and (hi - lo) / hi < 0.02:
                out.append({"start_date": trio[0]["start_date"], "end_date": trio[-1]["end_date"],
                            "note": "震荡区间，笔/线段划分存疑，需人工核对"})
        return out

    def signals(self) -> pd.DataFrame:
        """返回买卖点信号表（date/type/direction/price/level/reason/code），可直接给策略用。"""
        if self.points.empty:
            self.analyze()
        return self.points.copy()


# ==================== 多级别 ====================

def analyze_multi_level(symbol: str, start: str = None, end: str = None,
                        fetcher=None, levels=("1d", "1w")) -> dict:
    """多级别联立：大级别定方向、小级别找买卖点。返回 {level: chan_result} + 汇总信号。"""
    if fetcher is None:
        from core.data_fetcher import DataFetcher
        fetcher = DataFetcher()
    results, all_signals = {}, []
    for lv in levels:
        try:
            df = fetcher.get_kline(symbol, start, end, period=lv)
            if df is None or df.empty:
                continue
            res = ChanAnalyzer(df, level=lv).analyze()
            results[lv] = res
            sig = res["points"]
            if sig is not None and not sig.empty:
                sig = sig.copy()
                sig["level"] = lv
                all_signals.append(sig)
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger("quant.chan").warning("%s %s 级别分析失败：%s", symbol, lv, exc)
    merged = pd.concat(all_signals) if all_signals else pd.DataFrame()
    if not merged.empty:
        merged = merged.sort_values("date")
    return {"symbol": symbol, "levels": results, "signals": merged}


# ==================== 绘图 ====================

def plot_chan(df: pd.DataFrame, chan_result: dict, ax=None, save: bool = False,
              symbol: str = "", show: Optional[dict] = None, figsize=(14, 7)):
    """在K线上叠加缠论结构；开关默认读 config.CHAN_CONFIG（分型+笔+中枢）。"""
    import matplotlib.pyplot as plt

    switches = {"fenxing": CHAN.get("enable_fenxing", True),
                "bi": CHAN.get("enable_bi", True),
                "duan": CHAN.get("enable_duan", False),
                "zhongshu": CHAN.get("enable_zhongshu", True),
                "points": CHAN.get("enable_buy_sell_points", False)}
    switches.update(show or {})
    own = ax is None
    if own:
        from core.chart import _draw_candles, setup_chinese_font
        zh = setup_chinese_font()
        fig, ax = plt.subplots(figsize=figsize)
        up, down = config.CHART_CONFIG["up_color"], config.CHART_CONFIG["down_color"]
        _draw_candles(ax, df, up, down)
        ax.set_title(f"{symbol} 缠论结构" if zh else f"{symbol} Chan structure",
                     fontsize=12, loc="left")
    pos = {d: i for i, d in enumerate(df.index)}
    x_of = lambda d: pos.get(pd.Timestamp(d), int(df.index.searchsorted(pd.Timestamp(d))))

    if switches["fenxing"] and chan_result.get("fractals") is not None:
        fr = chan_result["fractals"]
        for _, f in fr.iterrows():
            ax.scatter([x_of(f["date"])], [f["price"]], marker="o" if f["type"] == "top" else "o",
                       s=28, c="#dc2626" if f["type"] == "top" else "#16a34a", zorder=6)
        ax.legend([], [], frameon=False)
    if switches["bi"]:
        for b in chan_result.get("bi", []):
            ax.plot([x_of(b["start_date"]), x_of(b["end_date"])],
                    [b["start_price"], b["end_price"]],
                    color=CHAN.get("color_bi", "#facc15"), lw=1.6, zorder=5)
    if switches["duan"]:
        for s in chan_result.get("segments", []):
            ax.plot([x_of(s["start_date"]), x_of(s["end_date"])],
                    [s["start_price"], s["end_price"]],
                    color=CHAN.get("color_duan", "#fb923c"), lw=2.6, zorder=5)
    if switches["zhongshu"]:
        from matplotlib.patches import Rectangle
        for c in chan_result.get("centers", []):
            x0, x1 = x_of(c["start_date"]), x_of(c["end_date"])
            ax.add_patch(Rectangle((x0, c["zd"]), max(x1 - x0, 1), c["zg"] - c["zd"],
                                   facecolor=CHAN.get("color_zs", "#3b82f6"), alpha=0.15,
                                   edgecolor=CHAN.get("color_zs", "#3b82f6"), lw=0.8, zorder=4))
            ax.annotate(f"ZG={c['zg']:.2f}\nZD={c['zd']:.2f} ({c['level']})",
                        xy=(x0, c["zg"]), fontsize=7, color="#1d4ed8", va="bottom")
    if switches["points"] and chan_result.get("points") is not None:
        pts = chan_result["points"]
        for _, p in pts.iterrows():
            key = f"color_{str(p['code']).lower()}"
            color = CHAN.get(key, "#111827")
            ax.annotate(str(p["code"]), xy=(x_of(p["date"]), p["price"]),
                        xytext=(0, -18 if p["direction"] == "buy" else 18),
                        textcoords="offset points", ha="center", fontsize=9, color=color,
                        arrowprops=dict(arrowstyle="->", color=color, lw=1.2))
    if chan_result.get("doubt_ranges"):
        for d in chan_result["doubt_ranges"]:
            x0, x1 = x_of(d["start_date"]), x_of(d["end_date"])
            ax.axvspan(x0, x1, color="#9ca3af", alpha=0.12, zorder=1)
    if own:
        if not save:
            return fig
        from core.chart import save_fig
        return save_fig(fig, f"{symbol or 'chan'}_chan")
    return ax


__all__ = ["ChanAnalyzer", "analyze_multi_level", "plot_chan"]
