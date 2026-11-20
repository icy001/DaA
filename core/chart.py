"""K 线绘制：多周期 / 形态标注 / 多标的对比 / 缠论叠加 / 回测复盘。

统一约定：
- 所有图输出到 `backtest_results/charts/`（`save_fig()` 统一落盘，dpi=150）；
- 中文字体从 `config.CHART_CONFIG["font_candidates"]` 探测，找不到就整体降级英文标签并 WARNING，绝不崩；
- 取数一律走 `DataFetcher.get_kline()`（内部再走 get_daily/get_minute），绘图模块不直接调行情接口；
- 涨跌配色读 `config.CHART_CONFIG`，美股/外盘可用 `color_scheme="us"` 切换。
"""
from __future__ import annotations

import logging
from datetime import date as _date
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

import matplotlib

matplotlib.use("Agg")  # 无显示环境（脚本/服务器）也能出图
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

import config  # noqa: E402

logger = logging.getLogger("quant.chart")

CHARTS_DIR = Path(getattr(config, "BACKTEST_DIR", Path("backtest_results"))) / "charts"

_FONT_NAME: Optional[str] = None
_ZH_OK: bool = False


# ==================== 中文字体 ====================

def setup_chinese_font(force: bool = False) -> bool:
    """探测中文字体并设置 rcParams；返回是否可用中文（False 表示已降级英文）。"""
    global _FONT_NAME, _ZH_OK
    if _FONT_NAME is not None and not force:
        return _ZH_OK
    from matplotlib import font_manager

    installed = {f.name for f in font_manager.fontManager.ttflist}
    _FONT_NAME = next((c for c in config.CHART_CONFIG.get("font_candidates", [])
                       if c in installed), None)
    _ZH_OK = _FONT_NAME is not None
    if _ZH_OK:
        plt.rcParams["font.sans-serif"] = [_FONT_NAME, "DejaVu Sans"]
    else:
        plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial"]
        logger.warning("未找到中文字体（候选 %s），图表标签降级为英文",
                       config.CHART_CONFIG.get("font_candidates"))
    plt.rcParams["axes.unicode_minus"] = False
    return _ZH_OK


def _t(zh: str, en: str) -> str:
    """中文可用时返回中文标签，否则英文。"""
    setup_chinese_font()
    return zh if _ZH_OK else en


# ==================== 工具 ====================

def _ensure_dirs() -> None:
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)


def save_fig(fig, name: str, close: bool = True, dpi: int = 150) -> Path:
    """保存 PNG 到 backtest_results/charts/，返回路径。"""
    _ensure_dirs()
    path = Path(name)
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        path = CHARTS_DIR / f"{path.name}.png"
    elif not path.is_absolute():
        path = CHARTS_DIR / path.name
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white")
    if close:
        plt.close(fig)
    return path


def _slice(df: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame()
    out = df
    if start is not None:
        out = out[out.index >= pd.Timestamp(start)]
    if end is not None:
        out = out[out.index <= pd.Timestamp(end)]
    return out


def _colors(color_scheme: str = "cn"):
    cc = config.CHART_CONFIG
    if str(color_scheme).lower() == "us":
        return cc["up_color_us"], cc["down_color_us"]
    return cc["up_color"], cc["down_color"]


def _ma_colors(n: int) -> List[str]:
    base = list(config.CHART_CONFIG.get("ma_colors", []))
    while len(base) < n:
        base.append("#94a3b8")
    return base[:n]


def _default_fetcher():
    from core.data_fetcher import DataFetcher
    return DataFetcher()


def _period_label(period: str) -> str:
    return {"1d": _t("日线", "Daily"), "1w": _t("周线", "Weekly"), "1M": _t("月线", "Monthly"),
            "1min": "1min", "5min": "5min", "15min": "15min",
            "30min": "30min", "60min": "60min"}.get(period, period)


def _default_mav(period: str) -> Sequence[int]:
    if period in ("1w", "1M"):
        return (5, 10, 20, 30)
    if period.endswith("min"):
        return (5, 10, 20, 60)
    return tuple(config.CHART_CONFIG.get("default_ma", (5, 10, 20, 60)))


def _bollinger(close: pd.Series, window: int = 20, k: float = 2.0):
    mid = close.rolling(window).mean()
    std = close.rolling(window).std()
    return mid + k * std, mid, mid - k * std


def _draw_candles(ax, df: pd.DataFrame, up: str, down: str, width: float = 0.6,
                  x: Optional[np.ndarray] = None) -> None:
    """纯 matplotlib 蜡烛图（用于网格布局/对比图等 mplfinance 不好嵌套的场景）。"""
    x = np.arange(len(df)) if x is None else np.asarray(x)
    for i, (_, row) in enumerate(df.iterrows()):
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        color = up if c >= o else down
        ax.vlines(x[i], l, h, color=color, linewidth=0.8, zorder=2)
        bottom, height = min(o, c), max(abs(c - o), 1e-9)
        ax.add_patch(Rectangle((x[i] - width / 2, bottom), width, height,
                               facecolor=color, edgecolor=color, alpha=0.9, zorder=3))
    ax.set_xlim(-1, len(df))


# ==================== 主图：K 线 ====================

def plot_kline(df: pd.DataFrame, symbol: str, name: str = None, period: str = "1d",
               color_scheme: str = "cn", mav: Sequence[int] = None, bollinger: bool = False,
               volume: bool = True, trades: pd.DataFrame = None, patterns: Dict[str, bool] = None,
               start=None, end=None, indicator: str = None, chan_result: dict = None,
               figsize=(14, 8), save: bool = True, show: bool = False):
    """画 K 线主图（蜡烛 + 均线 + 成交量 + 买卖点 + 形态标注 + 可选指标副图/缠论叠加）。"""
    setup_chinese_font()
    # stale 数据允许出图，但必须在图上标注「数据截至 X 日」（见 data_fetcher 模块 stale 约定）
    stale = bool(df.attrs.get("stale")) if df is not None else False
    stale_days = int(df.attrs.get("stale_days") or 0) if df is not None else 0
    data = _slice(df, start, end)
    if data is None or len(data) == 0:
        raise ValueError(f"{symbol} 在指定区间无 K 线数据")
    data = data.copy()
    data.index = pd.DatetimeIndex(data.index)
    up, down = _colors(color_scheme)
    title = f"{symbol} {name or ''} {_period_label(period)}".strip()

    import mplfinance as mpf

    ohlc = data.rename(columns={"open": "Open", "high": "High", "low": "Low",
                                "close": "Close", "volume": "Volume"})
    ma_list = list(mav or _default_mav(period))
    ma_colors = _ma_colors(len(ma_list))
    # mplfinance 固定 panel0=K线；volume=True 时成交量固定占 panel1；
    # 指标副图必须放到成交量之后的下一个 panel，否则会叠在成交量上并把 panel 数量算错
    vol_panel = 1 if volume else 0
    ind_panel = vol_panel + 1 if volume else 1
    ratios = [6] + ([1.6] if volume else []) + ([2] if indicator else [])
    addplots = []
    for i, n in enumerate(ma_list):
        ma = data["close"].rolling(int(n)).mean()
        # 数据太短时（如月线只有 20 根而 MA60）整列全 NaN，mplfinance 会崩，直接跳过
        if not ma.notna().any():
            continue
        addplots.append(mpf.make_addplot(ma, color=ma_colors[i], width=0.9, label=f"MA{n}"))
    if bollinger:
        upper, _mid, lower = _bollinger(data["close"])
        if lower.notna().any():
            addplots += [mpf.make_addplot(lower, color="#94a3b8", width=0.7, linestyle="--"),
                         mpf.make_addplot(upper, color="#94a3b8", width=0.7, linestyle="--")]
    if indicator:
        ind_plots = _indicator_addplots(data, indicator, ind_panel)
        if ind_plots:
            addplots += ind_plots
        else:  # 数据不足以算出指标副图 → 退回单 panel，避免 panel_ratios 数量不匹配
            indicator = None
            ratios = [6] + ([1.6] if volume else [])

    mc = mpf.make_marketcolors(up=up, down=down, edge="inherit", wick="inherit",
                               volume={"up": up, "down": down})
    style = mpf.make_mpf_style(marketcolors=mc, gridstyle="--", gridcolor="#e5e7eb",
                               rc={"font.sans-serif": plt.rcParams["font.sans-serif"],
                                   "axes.unicode_minus": False})
    fig, axlist = mpf.plot(ohlc, type="candle", style=style, addplot=addplots or None,
                           volume=volume, panel_ratios=tuple(ratios), returnfig=True,
                           figsize=figsize, title=("" if _ZH_OK else f"{symbol} {period}"),
                           ylabel=_t("价格", "Price"), warn_too_much_data=99999)
    ax = axlist[0]
    if _ZH_OK:
        ax.set_title(title, fontsize=13, loc="left")
    if stale:
        data_end = f"{data.index[-1]:%Y-%m-%d}"
        ax.text(0.995, 0.995,
                _t(f"数据截至 {data_end}（过期 {stale_days} 个交易日）",
                   f"Data as of {data_end} (stale {stale_days}d)"),
                transform=ax.transAxes, ha="right", va="top",
                fontsize=9, color="#dc2626")

    _annotate_patterns(ax, data, patterns)
    _annotate_trades(ax, data, trades, up, down)
    if chan_result:
        try:
            from core.chan import plot_chan
            plot_chan(data, chan_result, ax=ax)
        except Exception as exc:  # noqa: BLE001 - 缠论叠加失败不影响主图
            logger.warning("缠论叠加失败：%s", exc)

    if not save:
        return fig
    tag = f"{symbol}_{period}_{data.index[0]:%Y%m%d}_{data.index[-1]:%Y%m%d}"
    path = save_fig(fig, f"{tag}_kline")
    logger.info("[图表] 已保存 %s", path)
    if show:
        print(f"图表已保存：{path}")
    return path


def _indicator_addplots(data: pd.DataFrame, indicator: str, panel: int):
    """构造指标副图的 addplot 列表；数据太短导致整列为空时返回 []（调用方据此跳过副图）。"""
    import mplfinance as mpf
    ind = indicator.lower()
    if ind == "macd":
        from core.pattern_annotate import macd_series
        dif, dea, hist = macd_series(data)
        if not dif.notna().any():
            return []
        colors = [config.CHART_CONFIG["up_color"] if v >= 0 else config.CHART_CONFIG["down_color"]
                  for v in hist.fillna(0)]
        return [mpf.make_addplot(dif, panel=panel, color="#f59e0b", width=0.9, ylabel="MACD"),
                mpf.make_addplot(dea, panel=panel, color="#3b82f6", width=0.9),
                mpf.make_addplot(hist, panel=panel, type="bar", color=colors, alpha=0.6)]
    if ind == "kdj":
        low_n = data["low"].rolling(9).min()
        high_n = data["high"].rolling(9).max()
        rsv = (data["close"] - low_n) / (high_n - low_n).replace(0, np.nan) * 100
        k = rsv.ewm(com=2, adjust=False).mean()
        d = k.ewm(com=2, adjust=False).mean()
        j = 3 * k - 2 * d
        if not k.notna().any():
            return []
        return [mpf.make_addplot(k, panel=panel, color="#f59e0b", ylabel="KDJ"),
                mpf.make_addplot(d, panel=panel, color="#3b82f6"),
                mpf.make_addplot(j, panel=panel, color="#8b5cf6")]
    if ind == "rsi":
        delta = data["close"].diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
        if not rsi.notna().any():
            return []
        return [mpf.make_addplot(rsi, panel=panel, color="#8b5cf6", ylabel="RSI")]
    if ind == "boll":
        upper, mid, lower = _bollinger(data["close"])
        if not upper.notna().any():
            return []
        return [mpf.make_addplot(upper, panel=panel, color="#94a3b8", ylabel="BOLL"),
                mpf.make_addplot(mid, panel=panel, color="#f59e0b"),
                mpf.make_addplot(lower, panel=panel, color="#94a3b8")]
    raise ValueError(f"不支持的指标: {indicator}（macd/kdj/rsi/boll）")


def _annotate_patterns(ax, data: pd.DataFrame, patterns: Dict[str, bool]) -> None:
    from core.pattern_annotate import annotate_all
    ann = annotate_all(data, patterns)
    if ann is None or ann.empty:
        return
    span = float(data["high"].max() - data["low"].min()) or 1.0
    for dt, row in ann.iterrows():
        x = int(data.index.searchsorted(pd.Timestamp(dt)))
        if x >= len(data):
            continue
        is_up = row["direction"] == "up"
        y = float(data["low"].iloc[x]) - span * 0.02 if is_up else float(data["high"].iloc[x]) + span * 0.02
        ax.annotate(str(row["label"]), xy=(x, y), xytext=(x, y + (-span * 0.06 if is_up else span * 0.06)),
                    ha="center", va="top" if is_up else "bottom", fontsize=8,
                    color="#16a34a" if is_up else "#dc2626",
                    arrowprops=dict(arrowstyle="->", color="#16a34a" if is_up else "#dc2626",
                                    lw=0.8, linestyle="--" if row["kind"] == "macd_div" else "-"))


def _annotate_trades(ax, data: pd.DataFrame, trades: pd.DataFrame, up: str, down: str) -> None:
    if trades is None or len(trades) == 0:
        return
    t = trades.copy()
    date_col = "date" if "date" in t.columns else t.columns[0]
    t[date_col] = pd.to_datetime(t[date_col])
    t = t[(t[date_col] >= data.index[0]) & (t[date_col] <= data.index[-1])]
    if t.empty:
        return
    span = float(data["high"].max() - data["low"].min()) or 1.0
    for _, r in t.iterrows():
        x = int(data.index.searchsorted(pd.Timestamp(r[date_col])))
        x = min(x, len(data) - 1)
        side = str(r.get("direction", r.get("side", ""))).lower()
        is_buy = side in ("buy", "b", "1", "买入", "买")
        y = float(data["low"].iloc[x]) - span * 0.03 if is_buy else float(data["high"].iloc[x]) + span * 0.03
        ax.scatter([x], [y], marker="^" if is_buy else "v", s=90,
                   color=up if is_buy else down, edgecolors="black", linewidths=0.5, zorder=6)
        price = r.get("price")
        if price is not None and not pd.isna(price):
            ax.annotate(f"{float(price):.2f}", xy=(x, y), xytext=(0, -10 if is_buy else 10),
                        textcoords="offset points", ha="center",
                        fontsize=7, color="#111827")


def plot_indicator(df: pd.DataFrame, indicator: str, symbol: str = "", period: str = "1d",
                   save: bool = True):
    """单独画指标副图（macd / kdj / rsi / boll）。"""
    setup_chinese_font()
    if df is None or df.empty:
        raise ValueError("指标副图需要非空 K 线数据")
    fig, ax = plt.subplots(figsize=(13, 3.6))
    ind = indicator.lower()
    if ind == "macd":
        from core.pattern_annotate import macd_series
        dif, dea, hist = macd_series(df)
        ax.bar(range(len(df)), hist.values,
               color=[config.CHART_CONFIG["up_color"] if v >= 0 else config.CHART_CONFIG["down_color"]
                      for v in hist.fillna(0)], alpha=0.6, label="MACD")
        ax.plot(dif.values, color="#f59e0b", lw=0.9, label="DIF")
        ax.plot(dea.values, color="#3b82f6", lw=0.9, label="DEA")
        ax.axhline(0, color="#9ca3af", lw=0.6)
    elif ind == "rsi":
        delta = df["close"].diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
        ax.plot(rsi.values, color="#8b5cf6", lw=1.0, label="RSI14")
        ax.axhline(70, color="#dc2626", ls="--", lw=0.6)
        ax.axhline(30, color="#16a34a", ls="--", lw=0.6)
    elif ind == "kdj":
        low_n = df["low"].rolling(9).min()
        high_n = df["high"].rolling(9).max()
        rsv = (df["close"] - low_n) / (high_n - low_n).replace(0, np.nan) * 100
        k = rsv.ewm(com=2, adjust=False).mean()
        d = k.ewm(com=2, adjust=False).mean()
        ax.plot(k.values, color="#f59e0b", lw=0.9, label="K")
        ax.plot(d.values, color="#3b82f6", lw=0.9, label="D")
        ax.plot((3 * k - 2 * d).values, color="#8b5cf6", lw=0.9, label="J")
    elif ind == "boll":
        upper, mid, lower = _bollinger(df["close"])
        ax.plot(df["close"].values, color="#111827", lw=0.9, label=_t("收盘", "Close"))
        ax.plot(upper.values, color="#94a3b8", lw=0.8, ls="--", label="UPPER")
        ax.plot(mid.values, color="#f59e0b", lw=0.8, label="MID")
        ax.plot(lower.values, color="#94a3b8", lw=0.8, ls="--", label="LOWER")
    else:
        plt.close(fig)
        raise ValueError(f"不支持的指标: {indicator}（macd/kdj/rsi/boll）")
    ax.set_title(f"{symbol} {ind.upper()} {_period_label(period)}".strip(), fontsize=11, loc="left")
    ax.grid(alpha=0.25, ls="--")
    ax.legend(fontsize=8, loc="upper left")
    if not save:
        return fig
    return save_fig(fig, f"{symbol or 'indicator'}_{ind}_{period}_indicator")


# ==================== 多标的对比 ====================

# 基准优先用真实指数（cn_index 专用接口），指数取不到时才回退到场内 ETF 代理，
# 图例里会写明实际用的代码，回退时打印 WARNING。
BENCHMARK_ALIASES = {
    # 主用真实指数（走 cn_index 专用接口，必须带 sh/sz 前缀）；
    # 指数接口取不到数据时才回退到对应 ETF 代理，并打 WARNING。
    "000300": ("sh000300", "沪深300(000300)", ("510300", "沪深300(510300 ETF)")),
    "000905": ("sh000905", "中证500(000905)", ("510500", "中证500(510500 ETF)")),
    "000016": ("sh000016", "上证50(000016)", ("510050", "上证50(510050 ETF)")),
    "399006": ("sz399006", "创业板指(399006)", ("159915", "创业板指(159915 ETF)")),
}


def _resolve_benchmark(benchmark: str):
    """返回候选列表 [(代码, 图例标签), ...]：真实指数在前，ETF 回退代理在后。"""
    key = str(benchmark).strip().upper()
    if key in BENCHMARK_ALIASES:
        code, label, fallback = BENCHMARK_ALIASES[key]
        return [(code, label), fallback]
    return [(benchmark, f"{benchmark}({_t('基准', 'BM')})")]


def _load_benchmark(benchmark: str, start=None, end=None, period: str = "1d", fetcher=None):
    """按优先级取基准序列，返回 (Series, 图例标签)；全部失败返回 (None, None)。"""
    for i, (code, label) in enumerate(_resolve_benchmark(benchmark)):
        got = _load_series([code], start, end, period, fetcher)
        if got:
            if i > 0:
                logger.warning("指数基准 %s 取数失败，已回退到 %s（非指数）", benchmark, label)
            return next(iter(got.values())), label
    logger.warning("基准 %s 及其回退代理都取不到数据，图中不画基准线", benchmark)
    return None, None


def _load_series(symbols: Sequence[str], start=None, end=None, period: str = "1d",
                 fetcher=None, adjust: str = "qfq") -> Dict[str, pd.Series]:
    f = fetcher or _default_fetcher()
    out = {}
    for s in symbols:
        try:
            df = f.get_kline(s, start, end, period=period, adjust=adjust)
            if df is not None and not df.empty:
                out[s] = df["close"].astype(float)
        except Exception as exc:  # noqa: BLE001
            logger.warning("取 %s %s 失败：%s", s, period, exc)
    return out


def plot_compare(symbols: Sequence[str], start=None, end=None, normalize: bool = True,
                 benchmark: str = None, period: str = "1d", save: bool = True,
                 fetcher=None):
    """多标的走势对比（归一化起点=1），可叠加基准（默认 config.BENCHMARK）。"""
    if benchmark is None:
        import config
        benchmark = config.BENCHMARK
    setup_chinese_font()
    syms = list(symbols)[:8]
    series = _load_series(syms, start, end, period, fetcher)
    if not series:
        raise ValueError("对比图没有取到任何标的数据")
    if benchmark:
        bser, label = _load_benchmark(benchmark, start, end, period, fetcher)
        if bser is not None:
            series[label] = bser
    fig, ax = plt.subplots(figsize=(14, 6.5))
    for label, s in series.items():
        s = s.dropna()
        if s.empty:
            continue
        y = s / s.iloc[0] if normalize else s
        ax.plot(range(len(y)), y.values, lw=1.2, label=label)
    ax.set_title(_t("多标的走势对比（归一化起点=1）", "Multi-symbol comparison (normalized=1)")
                 + f" · {_period_label(period)}", fontsize=12, loc="left")
    ax.set_ylabel(_t("归一化净值", "Normalized") if normalize else _t("价格", "Price"))
    ax.grid(alpha=0.25, ls="--")
    ax.legend(fontsize=8, ncol=2)
    if not save:
        return fig
    tag = f"compare_{period}_{_date.today():%Y%m%d}"
    return save_fig(fig, tag)


def plot_kline_grid(symbols: Sequence[str], start=None, end=None, ncols: int = 2,
                    period: str = "1d", benchmark: str = None, mav: Sequence[int] = None,
                    color_scheme: str = "cn", save: bool = True, fetcher=None):
    """多标的蜡烛图并排（≤4 个）+ 顶部归一化收益对比；共享时间轴、各自成交量副图。"""
    setup_chinese_font()
    syms = list(symbols)[:4]
    if not syms:
        raise ValueError("plot_kline_grid 至少需要 1 个标的")
    f = fetcher or _default_fetcher()
    frames: Dict[str, pd.DataFrame] = {}
    for s in syms:
        try:
            df = f.get_kline(s, start, end, period=period)
            if df is not None and not df.empty:
                frames[s] = df
        except Exception as exc:  # noqa: BLE001
            logger.warning("取 %s %s 失败：%s", s, period, exc)
    if not frames:
        raise ValueError("并排图没有取到任何标的的数据")
    up, down = _colors(color_scheme)
    ncols = max(1, min(int(ncols), 4))
    nrows = int(np.ceil(len(frames) / ncols))
    fig = plt.figure(figsize=(7 * ncols, 3.6 * nrows + 3.2))
    gs = fig.add_gridspec(nrows * 2 + 1, ncols, height_ratios=[1.6] + [3, 1] * nrows)
    ax_top = fig.add_subplot(gs[0, :])
    for label, df in frames.items():
        y = df["close"].astype(float)
        ax_top.plot(range(len(y)), (y / y.iloc[0]).values, lw=1.1, label=label)
    if benchmark:
        bser, label = _load_benchmark(benchmark, start, end, period, fetcher)
        if bser is not None:
            bser = bser.dropna()
            if not bser.empty:
                ax_top.plot(range(len(bser)), (bser / bser.iloc[0]).values, lw=1.0, ls="--",
                            color="#6b7280", label=label)
    ax_top.set_title(_t("归一化累计收益对比（起点=1）", "Normalized cumulative return"),
                     fontsize=11, loc="left")
    ax_top.grid(alpha=0.25, ls="--")
    ax_top.legend(fontsize=8, ncol=4)

    for idx, (label, df) in enumerate(frames.items()):
        r, c = divmod(idx, ncols)
        ax = fig.add_subplot(gs[1 + r * 2, c])
        axv = fig.add_subplot(gs[2 + r * 2, c], sharex=ax)
        _draw_candles(ax, df, up, down)
        for i, n in enumerate(mav or _default_mav(period)):
            if len(df) >= n:
                ax.plot(range(len(df)), df["close"].rolling(int(n)).mean().values,
                        color=_ma_colors(len(mav or _default_mav(period)))[i], lw=0.8,
                        label=f"MA{n}")
        ax.set_title(f"{label} {_period_label(period)}", fontsize=10, loc="left")
        ax.grid(alpha=0.2, ls="--")
        ax.legend(fontsize=7, loc="upper left")
        vol_colors = [up if c2 >= o else down
                      for o, c2 in zip(df["open"], df["close"])]
        axv.bar(range(len(df)), df["volume"].values, color=vol_colors, alpha=0.55, width=0.7)
        axv.grid(alpha=0.2, ls="--")
        ticks = np.linspace(0, max(len(df) - 1, 0), 6).astype(int)
        axv.set_xticks(ticks)
        axv.set_xticklabels([df.index[i].strftime("%m-%d") for i in ticks], fontsize=7)
    for j in range(len(frames), nrows * ncols):
        r, c = divmod(j, ncols)
        fig.add_subplot(gs[1 + r * 2, c]).axis("off")
        fig.add_subplot(gs[2 + r * 2, c]).axis("off")
    fig.suptitle(_t("多标的 K 线并排 + 强弱对比", "K-line grid & relative strength"),
                 fontsize=13, x=0.01, ha="left")
    fig.tight_layout()
    if not save:
        return fig
    tag = f"grid_{period}_{'_'.join(frames)}_{_date.today():%Y%m%d}"
    return save_fig(fig, tag)


# ==================== 回测复盘 ====================

def plot_backtest_kline(result, start=None, end=None, period: str = "1d", fetcher=None):
    """回测复盘：在成交记录涉及的每个标的 K 线上标出全部买卖点，每标的一张图。"""
    setup_chinese_font()
    trades = result.get("trades") if isinstance(result, dict) else result
    if trades is None or len(trades) == 0:
        raise ValueError("回测结果里没有成交记录（trades）")
    trades = pd.DataFrame(trades).copy()
    if "symbol" not in trades.columns:
        raise ValueError("成交记录缺少 symbol 列")
    if "date" not in trades.columns and isinstance(trades.index, pd.DatetimeIndex):
        trades = trades.reset_index().rename(columns={"index": "date"})
    f = fetcher or _default_fetcher()
    paths = []
    for symbol, g in trades.groupby("symbol"):
        try:
            df = f.get_kline(symbol, start, end, period=period)
            paths.append(plot_kline(df, str(symbol), period=period, trades=g))
        except Exception as exc:  # noqa: BLE001
            logger.warning("复盘 %s 失败：%s", symbol, exc)
    return paths


def plot_kline_interactive(df: pd.DataFrame, symbol: str, period: str = "1d",
                           name: str = None) -> Optional[Path]:
    """plotly 交互式 K 线（可缩放/悬停看 OHLC），未安装 plotly 时返回 None。"""
    try:
        import plotly.graph_objects as go
    except ImportError:
        logger.info("未安装 plotly，跳过交互式图表")
        return None
    _ensure_dirs()
    data = df.copy()
    data.index = pd.DatetimeIndex(data.index)
    fig = go.Figure(go.Candlestick(x=data.index, open=data["open"], high=data["high"],
                                   low=data["low"], close=data["close"], name=symbol))
    fig.update_layout(title=f"{symbol} {name or ''} {period}".strip(),
                      xaxis_rangeslider_visible=False, height=720,
                      template="plotly_white")
    path = CHARTS_DIR / f"{symbol}_{period}_kline.html"
    fig.write_html(str(path), include_plotlyjs="cdn")
    return path


__all__ = ["CHARTS_DIR", "setup_chinese_font", "save_fig", "plot_kline", "plot_indicator",
           "plot_compare", "plot_kline_grid", "plot_backtest_kline", "plot_kline_interactive"]
