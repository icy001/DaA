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
    _dump_backtest_artifacts(args, result, symbols, start, end)
    return 0


def _dump_backtest_artifacts(args, result, symbols, start, end) -> None:
    """C-2：回测留痕三件自动落盘（backtest_results/），无落盘 = 不可复现 = 不可验收。

    {run_id}_trades.csv  逐笔成交明细
    {run_id}_equity.csv  每日权益
    {run_id}_config.json 冻结配置（参数 / 版本 / 治理面哈希 / 区间 / 熔断状态）
    """
    import csv
    import json
    from datetime import datetime as _dt
    from pathlib import Path

    trades = result.get("trades") or []
    nav = result.get("nav")
    out_dir = Path(config.BASE_DIR) / "backtest_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = (f"bt_{args.strategy}_{start}_{end}_"
              f"{_dt.now():%Y%m%d_%H%M%S}")
    try:
        with open(out_dir / f"{run_id}_trades.csv", "w", newline="",
                  encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            keys = sorted({k for t in trades for k in t})
            w.writerow(keys)
            for t in trades:
                w.writerow([t.get(k, "") for k in keys])
        if nav is not None and len(nav):
            nav.to_csv(out_dir / f"{run_id}_equity.csv", encoding="utf-8-sig")
        surface = ""
        surface_file = Path(config.BASE_DIR) / "config_surface.sha256"
        if surface_file.exists():
            surface = surface_file.read_text(encoding="utf-8").split()[0]
        snapshot = {
            "run_id": run_id,
            "spec_version": config.SPEC_VERSION,
            "surface_sha256": surface,
            "strategy": args.strategy,
            "symbols": list(symbols),
            "start": str(start), "end": str(end),
            "adjust": getattr(args, "adjust", None),
            "initial_cash": getattr(args, "initial_cash", None),
            "run_mode": result.get("run_mode"),
            "params": result.get("params"),
            "halt_state": result.get("halt_state"),
            "metrics": {k: (float(v) if hasattr(v, "__float__") else v)
                        for k, v in (result.get("metrics") or {}).items()},
            "execution": {
                "match_price_basis": config.EXECUTION_MODEL["match_price_basis"],
                "slippage_base_pct": config.EXECUTION_MODEL["slippage_base_pct"],
                "slippage_multiplier": config.EXECUTION_MODEL["slippage_multiplier"],
            },
        }
        (out_dir / f"{run_id}_config.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8")
        print(f"\n留痕三件已落盘：{out_dir}/{run_id}_{{trades.csv,equity.csv,config.json}}")
        if result.get("halt_state"):
            print(f"熔断状态：{json.dumps(result['halt_state'], ensure_ascii=False)}")
    except OSError as exc:
        print(f"[警告] 回测留痕落盘失败（不影响回测结果）：{exc}")


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


def cmd_risk_reset(args) -> int:
    """B-1：实盘熔断人工复位（需 --confirm yes 二次确认）。

    协议：熔断状态文件 live_trading/RISK_HALT.json 由运行中的实盘/模拟盘
    RiskManager 落盘；本命令做二次确认后删除标志文件并写审计行，运行中进程
    在下一次换日（new_day → sync_state_file）检测到文件消失即同步解除。
    """
    from pathlib import Path
    if str(getattr(args, "confirm", "")) != "yes":
        print("[拒绝] 人工复位熔断需二次确认：追加 --confirm yes 后重试")
        return 2
    flag = Path(config.BASE_DIR) / "live_trading" / "RISK_HALT.json"
    if not flag.exists():
        print("当前无熔断状态文件（未熔断），无需复位")
        return 0
    import json as _json
    from datetime import datetime as _dt
    try:
        state = _json.loads(flag.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    flag.unlink()
    audit = flag.parent / "RISK_HALT_RESETS.log"
    line = (f"{_dt.now():%Y-%m-%d %H:%M:%S} manual_reset by={getattr(args, 'operator', 'unknown')} "
            f"halted_since={state.get('halt_since')} reason={state.get('halt_reason')}\n")
    try:
        with open(audit, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError as exc:
        print(f"[警告] 审计行写入失败：{exc}")
    print(f"熔断已人工复位：原状态 {state.get('halt_since')} 起「{state.get('halt_reason', '')}」；"
          f"运行中进程将在下一次换日同步解除。审计：{audit.name}")
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

    p = sp.add_parser("risk-reset", help=f"[{GROUP}] 风控熔断人工复位（需二次确认）")
    p.add_argument("--confirm", help="二次确认：必须显式传 yes")
    p.add_argument("--operator", help="操作人（写入审计行）")
    p.set_defaults(handler=cmd_risk_reset)

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
