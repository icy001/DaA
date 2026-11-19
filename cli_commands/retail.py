# -*- coding: utf-8 -*-
"""零售层命令：回测 / 模拟盘 / 盯盘 / 复盘报告。"""
from __future__ import annotations

import config
from core import cli_gate
from cli_commands._common import *  # noqa: F401,F403

GROUP = "零售层"
DEF = cli_gate.cli_default

# --data 本地导入参数（backtest / paper 共用；三物化列校验走 data.data_import）
_LOCAL_DATA_HELP = ("本地数据文件（--data/--csv/--from-file 三别名同义；"
                    "多文件逗号分隔，走数据层出口强制校验三物化列）")


def _add_local_data_args(p) -> None:
    p.add_argument("--data", "--csv", "--from-file", dest="data",
                   help=_LOCAL_DATA_HELP)

def cmd_backtest(args) -> int:
    from core.runner import run_backtest
    from core.strategy_loader import get

    params, symbols, start, end = _resolve_run_args(args)
    fetcher = _local_fetcher_from_args(args, symbols)
    if not symbols:
        print("错误：未提供 symbols（命令行 --symbols 或 yaml 中 symbols）")
        return 2
    result = run_backtest(get(args.strategy), params=params, symbols=symbols,
                          start=start, end=end,
                          initial_cash=getattr(args, "initial_cash", None),
                          fetcher=fetcher,
                          adjust=getattr(args, "adjust", None) or DEF("adjust"))
    print_metrics(result["metrics"])
    if result["rejected"]:
        print(f"\n拒单 {len(result['rejected'])} 笔（前 5 条）：")
        for item in result["rejected"][:5]:
            print(f"  - {item.get('symbol')} {item.get('direction')}：{item.get('reason')}")
    return 0


def cmd_paper(args) -> int:
    from core import spec_check
    from core.runner import run_paper
    from core.strategy_loader import get

    try:
        spec_check.enforce_on_startup("paper")
    except (RuntimeError, ValueError) as exc:
        print(f"[拒绝] 规格版本自校验未通过：{exc}")
        return 2

    params, symbols, start, end = _resolve_run_args(args)
    fetcher = _local_fetcher_from_args(args, symbols)
    if not symbols:
        print("错误：未提供 symbols（命令行 --symbols 或 yaml 中 symbols）")
        return 2
    result = run_paper(get(args.strategy), params=params, symbols=symbols,
                       start=start, end=end if args.end else None,
                       initial_cash=getattr(args, "initial_cash", None),
                       fetcher=fetcher,
                       adjust=getattr(args, "adjust", None) or DEF("adjust"))
    print(f"\n模拟盘运行完成：{len(result['nav'])} 个交易日")
    print_metrics(result["metrics"])
    return 0


def cmd_monitor(_args) -> int:
    """前台定时盯盘（Ctrl+C 优雅退出；账户状态自动保存）。"""
    from core.monitor import run_forever

    print("启动盯盘（当前仅支持模拟盘账户；--paper 为默认行为）。"
          "Ctrl+C 优雅退出。")
    run_forever()
    return 0


def cmd_report(args) -> int:
    """生成复盘报告（同源取数：account.trades + bills + signal_gate 裁决日志）。"""
    from core.paper_trader import PaperTrader
    from core.reporter import Reporter
    from core.strategy_loader import get

    if not args.symbols:
        print("错误：report 需要 --symbols（与模拟盘同一批标的）")
        return 2
    trader = PaperTrader(get(args.strategy), params=None, symbols=[
        s.strip() for s in args.symbols.split(",") if s.strip()],
        start_date=args.start, end_date=args.end)
    if trader.account_file and trader.account_file.exists():
        trader.load_account()
        print(f"已加载模拟盘账户：{trader.account_file}")
    reporter = Reporter(paper_trader=trader, report_dir=str(
        config.BASE_DIR / "backtest_results" / "reports"))
    kind = str(args.report_type)
    if kind == "daily":
        report = reporter.generate_daily_report(args.date, auto_send=args.send)
    elif kind == "weekly":
        report = reporter.generate_weekly_report(args.date, auto_send=args.send)
    elif kind == "monthly":
        report = reporter.generate_monthly_report(args.date, auto_send=args.send)
    else:
        print(f"未知报告类型 {kind!r}（daily / weekly / monthly）")
        return 2
    print(f"报告已生成：{report.get('html_path')}")
    print(f"成交 {report.get('trade_count', 0)} 笔；"
          f"拦截披露 {report.get('suppressions', {}).get('total', 0)} 笔")
    return 0


def add_subparser(sp) -> None:
    """注册零售层四件套（回测 / 模拟盘 / 盯盘 / 报告）。"""
    p = sp.add_parser("backtest", help=f"[{GROUP}] 策略回测")
    p.add_argument("--strategy", required=True, help="策略名（list-strategies 查看）")
    p.add_argument("--symbols", help="逗号分隔标的（缺省读 yaml）")
    p.add_argument("--params", help="策略参数 k=v,k=v（覆盖 yaml）")
    _add_local_data_args(p)
    p.add_argument("--adjust", default=DEF("adjust"))
    p.add_argument("--initial-cash", dest="initial_cash", type=float,
                   default=DEF("initial_cash"))
    p.add_argument("--start", default=DEF("start"))
    p.add_argument("--end", default=DEF("end"))
    p.set_defaults(handler=cmd_backtest)

    p = sp.add_parser("paper", help=f"[{GROUP}] 模拟盘（paper trading）")
    p.add_argument("--strategy", required=True)
    p.add_argument("--symbols", help="逗号分隔标的（缺省读 yaml）")
    p.add_argument("--params", help="策略参数 k=v,k=v")
    _add_local_data_args(p)
    p.add_argument("--adjust", default=DEF("adjust"))
    p.add_argument("--initial-cash", dest="initial_cash", type=float,
                   default=DEF("initial_cash"))
    p.add_argument("--start", default=DEF("start"))
    p.add_argument("--end", default=DEF("end"))
    p.set_defaults(handler=cmd_paper)

    p = sp.add_parser("monitor", help=f"[{GROUP}] 定时盯盘与消息推送")
    p.set_defaults(handler=cmd_monitor)

    p = sp.add_parser("report", help=f"[{GROUP}] 复盘报告（日/周/月）")
    p.add_argument("--strategy", required=True, help="与模拟盘同名的策略")
    p.add_argument("--symbols", help="与模拟盘同一批标的（逗号分隔）")
    p.add_argument("--type", dest="report_type", default=DEF("report_type"),
                   choices=["daily", "weekly", "monthly"])
    p.add_argument("--date", help="报告日期 YYYY-MM-DD（默认今天）")
    p.add_argument("--start", default=DEF("start"))
    p.add_argument("--end", default=DEF("end"))
    p.add_argument("--send", action="store_true", help="自动发送（走 notifier）")
    p.set_defaults(handler=cmd_report)


def handler(args) -> int:
    """retail 模块统一分发（各子命令自带 handler）。"""
    return int((getattr(args, "handler", None) or cmd_backtest)(args))
