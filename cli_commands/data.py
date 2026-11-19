# -*- coding: utf-8 -*-
"""数据与图表命令：缓存更新 / 批量导出 / K 线图。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import config
from core import cli_gate
from cli_commands._common import *  # noqa: F401,F403

GROUP = "数据与图表"
DEF = cli_gate.cli_default

def cmd_updatedata(args) -> int:
    """手动增量更新本地缓存（行情批量取数有内置限速，勿高频调用）。"""
    from core.data_fetcher import DataFetcher

    fetcher = DataFetcher()
    text = str(args.symbols or "").strip()
    if text.lower() == "all":
        from tools.data_export import DataExporter
        watchlist = DataExporter().load_watchlist()
        symbols = [str(s) for s in watchlist["symbol"].tolist() if str(s).strip()]
        if not symbols:
            print("自选池为空：--symbols all 需要 export/watchlist.csv 非空")
            return 2
    else:
        symbols = [s.strip() for s in text.split(",") if s.strip()]
    if not symbols:
        print("错误：--symbols 需要 all 或逗号分隔标的")
        return 2
    print(f"增量更新 {len(symbols)} 个标的（勿高频调用）……")
    for symbol in symbols:
        rows = fetcher.update_cache(symbol, adjust=DEF("adjust"))
        print(f"  {symbol}：{rows}")
    return 0


def cmd_download(args) -> int:
    """行情批量下载导出（转发 tools/data_export 唯一实现）。"""
    from tools import data_export

    argv = ["--period", args.period, "--adjust", args.adjust,
            "--format", args.format, "--export-dir", args.export_dir]
    if args.start:
        argv += ["--start", args.start]
    if args.end:
        argv += ["--end", args.end]
    if args.watchlist:
        argv.append("--watchlist")
    elif args.symbols:
        argv += ["--symbols", args.symbols]
    elif args.update:
        argv.append("--update")
    else:
        print("错误：请提供 --symbols 或 --watchlist（或 --update）")
        return 2
    return int(data_export.main(argv))


def cmd_chart(args) -> int:
    """K线图：单标的 / 多标的对比 / 回测复盘三模式。"""
    from core.chart import plot_backtest_kline, plot_compare, plot_kline

    if args.backtest_result:
        path = Path(args.backtest_result)
        if not path.exists():
            print(f"错误：回测结果文件不存在 {path}")
            return 2
        result = json.loads(path.read_text(encoding="utf-8"))
        fig = plot_backtest_kline(result, start=args.start, end=args.end)
        print(f"回测复盘图已生成：{fig}")
        return 0
    if args.compare:
        symbols = [s.strip() for s in str(args.compare).split(",") if s.strip()]
        if not symbols:
            print("错误：--compare 需要逗号分隔标的")
            return 2
        fig = plot_compare(symbols, start=args.start, end=args.end)
        print(f"多标的对比图已生成：{fig}")
        return 0
    if not args.symbol:
        print("错误：需要 --symbol / --compare / --backtest-result 之一")
        return 2
    from core.data_fetcher import DataFetcher
    frame = DataFetcher().get_daily(args.symbol, start_date=args.start,
                                     end_date=args.end, adjust=DEF("adjust"))
    if frame is None or len(frame) == 0:
        print(f"错误：{args.symbol} 无数据")
        return 2
    indicators = [x.strip() for x in str(args.indicators or "").split(",") if x.strip()]
    indicator = "macd" if "macd" in indicators else None
    fig = plot_kline(frame, args.symbol, period=args.period, indicator=indicator)
    print(f"K线图已生成：{fig}")
    return 0


def cmd_import(args) -> int:
    """本地数据导入（--file/--csv/--from-file 统一走数据层出口，三物化列校验）。"""
    from data.data_import import (LocalDataImportError, import_local_frame,
                                  required_columns)

    path = str(getattr(args, "file", "") or "").strip()
    if not path:
        print("错误：需要 --file/--csv/--from-file 指定本地数据文件")
        return 2
    try:
        frame = import_local_frame(path, symbol=args.symbol,
                                   adjust=args.adjust, warmup_bars=args.warmup)
    except LocalDataImportError as exc:
        print(f"导入被数据层拒绝（fail-closed）：{exc}")
        return 2
    print(f"导入成功：{path}  {len(frame)} 根 K 线")
    print(f"  三物化列：{', '.join(required_columns())}（逐 symbol 各自物化）")
    print(f"  数据截至：{frame['data_asof_date'].iloc[-1]}")
    print(f"  复权方式：{frame['price_adjust'].iloc[-1]}")
    print(f"  预热就绪：{bool(frame['warmup_ok'].iloc[-1])}")
    return 0


def add_subparser(sp) -> None:
    """注册数据/图表/导入子命令。"""
    p = sp.add_parser("updatedata", help=f"[{GROUP}] 增量更新本地行情缓存（勿高频调用）")
    p.add_argument("--symbols", help="标的列表；'all' 表示整个 watchlist")
    p.add_argument("--adjust", default=DEF("adjust"))
    p.set_defaults(handler=cmd_updatedata)

    p = sp.add_parser("download", help=f"[{GROUP}] 批量下载/导出行情")
    p.add_argument("--symbols", help="逗号分隔标的")
    p.add_argument("--watchlist", action="store_true", help="按 watchlist 批量")
    p.add_argument("--update", action="store_true", help="增量更新模式")
    p.add_argument("--period", default=DEF("chart_period"), help="K 线周期")
    p.add_argument("--adjust", default=DEF("adjust"))
    p.add_argument("--format", default=DEF("export_format"),
                   choices=["csv", "parquet", "excel"], help="导出格式")
    p.add_argument("--export-dir", dest="export_dir", default="export",
                   help="导出根目录")
    p.add_argument("--start", default=DEF("start"))
    p.add_argument("--end", default=DEF("end"))
    p.set_defaults(handler=cmd_download)

    p = sp.add_parser("chart", help=f"[{GROUP}] K 线图（单标的/对比/回测叠加）")
    p.add_argument("--symbol", help="单标的（如 600519）")
    p.add_argument("--compare", help="多标的对比（逗号分隔）")
    p.add_argument("--backtest-result", dest="backtest_result",
                   help="回测结果 JSON（复盘叠加）")
    p.add_argument("--period", default=DEF("chart_period"))
    p.add_argument("--start", default=DEF("start"))
    p.add_argument("--end", default=DEF("end"))
    p.add_argument("--indicators", help="指标（如 macd）")
    p.set_defaults(handler=cmd_chart)

    p = sp.add_parser("import", help=f"[{GROUP}] 本地数据导入（三物化列强制校验）")
    p.add_argument("--file", "--csv", "--from-file", dest="file",
                   help="本地数据文件（CSV/Parquet/Excel）")
    p.add_argument("--symbol", help="标的代码（缺省取文件名）")
    p.add_argument("--adjust", default=DEF("adjust"))
    p.add_argument("--warmup", type=int,
                   default=config._USER_CLI_DEFAULTS["data_import_warmup_bars"],
                   help="预热根数（默认取 CLI_CONFORMANCE）")
    p.set_defaults(handler=cmd_import)


def handler(args) -> int:
    """data 模块统一分发（子命令各自 handler，本函数仅兜底）。"""
    return int((getattr(args, "handler", None) or cmd_import)(args))
