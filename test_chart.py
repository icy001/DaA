"""第 2 步图表测试：基础K线 / 多周期切换 / 形态标注 / 多标的并排 / 回测复盘 / 交互式。"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.chart import (CHARTS_DIR, _load_benchmark, plot_backtest_kline, plot_compare,
                        plot_indicator, plot_kline, plot_kline_grid,
                        plot_kline_interactive, setup_chinese_font)
from core.data_fetcher import DataFetcher

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'✅' if ok else '❌'} {name}" + (f" | {detail}" if detail else ""))


def _size(path) -> int:
    return Path(path).stat().st_size if path and Path(path).exists() else 0


def main() -> int:
    end = date.today()
    start = (end - timedelta(days=365)).strftime("%Y-%m-%d")
    end_s = end.strftime("%Y-%m-%d")
    f = DataFetcher()

    zh = setup_chinese_font()
    check("中文字体探测正常（找不到则降级英文，不崩）", Path(CHARTS_DIR).parent.exists(),
          f"中文字体可用={zh}，输出目录 {CHARTS_DIR}")

    df = f.get_kline("600519", start, end_s, period="1d")
    check("600519 日线取数", len(df) > 200, f"{len(df)} 根 {df.index[0]:%Y-%m-%d} ~ {df.index[-1]:%Y-%m-%d}")

    # 1) 蜡烛图 + MA + 成交量
    p1 = plot_kline(df, "600519", name="贵州茅台", period="1d", mav=(5, 10, 20, 60))
    check("蜡烛图+MA+成交量落盘", _size(p1) > 20_000, f"{p1} ({_size(p1)//1024} KB)")

    # 2) 指标副图（K线+MACD 组合 & 单独副图）
    p2 = plot_kline(df, "600519", period="1d", indicator="macd")
    check("K线+MACD 多面板图落盘", _size(p2) > 20_000, f"{p2} ({_size(p2)//1024} KB)")
    p3 = plot_indicator(df, "rsi", symbol="600519")
    check("指标单独成图（RSI）", _size(p3) > 8_000, f"{p3} ({_size(p3)//1024} KB)")

    # 3) 多周期：日 / 周 / 月各一张 + 重采样 OHLC 手工核对
    paths = {}
    for period, label in (("1d", "日线"), ("1w", "周线"), ("1M", "月线")):
        dfp = f.get_kline("600519", "2025-01-01", end_s, period=period)
        paths[period] = plot_kline(dfp, "600519", period=period)
        check(f"多周期切换 · {label} 出图", _size(paths[period]) > 15_000,
              f"{len(dfp)} 根 → {Path(paths[period]).name}")
    wk = f.get_kline("600519", "2025-01-01", end_s, period="1w")
    daily = f.get_kline("600519", "2025-01-01", end_s, period="1d")
    k = wk.index[10]
    days = daily[(daily.index > wk.index[9]) & (daily.index <= k)]
    ohlc_ok = (abs(float(wk["open"].iloc[10]) - float(days["open"].iloc[0])) < 1e-6 and
               abs(float(wk["high"].iloc[10]) - float(days["high"].max())) < 1e-6 and
               abs(float(wk["low"].iloc[10]) - float(days["low"].min())) < 1e-6 and
               abs(float(wk["close"].iloc[10]) - float(days["close"].iloc[-1])) < 1e-6 and
               int(wk["volume"].iloc[10]) == int(days["volume"].sum()))
    check("周线 OHLCV 聚合正确（手工核对一周）", ohlc_ok,
          f"{k.date()} 含 {len(days)} 个交易日")
    check("未走完的月线已标记", bool(f.get_kline("600519", "2025-01-01", end_s, period="1M").attrs.get("last_bar_incomplete")) is not None)

    # 4) 形态标注（默认只开均线，另测全开）
    p4 = plot_kline(df, "600519", period="1d", patterns={"ma_cross": True})
    p5 = plot_kline(df, "600519", period="1d",
                    patterns={"ma_cross": True, "macd_div": True, "breakout": True})
    check("形态标注图（默认开均线）落盘", _size(p4) > 20_000, f"{Path(p4).name}")
    check("形态标注图（全开）落盘", _size(p5) > 20_000, f"{Path(p5).name}")

    # 5) 多标的归一化对比
    p6 = plot_compare(["600519", "510300", "601318"], start, end_s, benchmark="000300")
    check("多标的归一化对比图落盘", _size(p6) > 30_000, f"{Path(p6).name} ({_size(p6)//1024} KB)")

    # 5.1) 基准必须是真实指数 000300（cn_index 接口），不是 510300 ETF 代理
    bser, blabel = _load_benchmark("000300", start, end_s)
    check("基准改回真实指数 000300（走 cn_index 接口）",
          bser is not None and "000300" in blabel and "ETF" not in blabel,
          f"{blabel} · {0 if bser is None else len(bser)} 根")
    fig = plot_compare(["600519", "601318"], start, end_s, benchmark="000300", save=False)
    legend = [t.get_text() for t in fig.get_axes()[0].get_legend().get_texts()]
    check("以 000300 为基准的对比图图例含指数基准线", any("000300" in t for t in legend), str(legend))
    fig.savefig(Path(CHARTS_DIR) / "compare_benchmark_000300.png", dpi=110, bbox_inches="tight")
    plt.close(fig)

    # 6) 4 标的一键并排
    p7 = plot_kline_grid(["600519", "510300", "601318", "000001"], start, end_s, ncols=2,
                         benchmark="000300")
    check("4 标的并排网格图落盘", _size(p7) > 40_000, f"{Path(p7).name} ({_size(p7)//1024} KB)")

    # 7) 回测成交点复盘
    trades = pd.DataFrame([
        {"symbol": "600519", "date": df.index[30], "direction": "buy", "price": float(df["close"].iloc[30])},
        {"symbol": "600519", "date": df.index[120], "direction": "sell", "price": float(df["close"].iloc[120])},
        {"symbol": "510300", "date": df.index[60], "direction": "buy", "price": 4.0},
    ])
    bt = plot_backtest_kline({"trades": trades}, start, end_s)
    check("回测复盘图（每标的一张）落盘", len(bt) == 2 and all(_size(p) > 15_000 for p in bt),
          f"{[Path(p).name for p in bt]}")

    # 8) 交互式 HTML（plotly 可选）
    html = plot_kline_interactive(df, "600519")
    if html is None:
        check("交互式图表（未装 plotly，已自动跳过）", True, "skipped")
    else:
        check("交互式 HTML 落盘", Path(html).exists() and _size(html) > 5_000,
              f"{Path(html).name} ({_size(html)//1024} KB)")

    # 9) 落盘目录
    check("图表目录为 backtest_results/charts/",
          str(CHARTS_DIR).endswith("backtest_results/charts") and len(list(Path(CHARTS_DIR).glob("*.png"))) >= 8,
          f"共 {len(list(Path(CHARTS_DIR).glob('*.png')))} 张 PNG")

    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
