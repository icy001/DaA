# -*- coding: utf-8 -*-
"""合格投资者层命令：净值回测 / REITs 折溢价 / 新三板 / QI 自检 / 模式切换。"""
from __future__ import annotations

import json
from pathlib import Path

import config
from core.gov_compat import gov
from core import cli_gate
from cli_commands._common import *  # noqa: F401,F403

GROUP = "合格投资者层"
DEF = cli_gate.cli_default

def _nav_frame_for(symbol: str, fetcher):
    """按代码形态路由净值取数：纯数字→REITs，其余→私募/资管净值（需本
    地 CSV）。"""
    code = str(symbol).strip()
    if code.isdigit():
        return fetcher.fetch_reits_merged(code)
    return fetcher.fetch_private_fund_nav(code)


def cmd_nav_backtest(args) -> int:
    """净值型 FOF 组合回测（三层净值 / 锁定期 / T+N / 披露滞后）。"""
    from data.fetcher_nav import NavDataUnavailableError, NavFetcher
    from nav_backtest.fof import FOFBacktester
    from nav_backtest.strategies import (equal_weight, nav_momentum,
                                         risk_parity)

    strategies = {"equal_weight": equal_weight, "risk_parity": risk_parity,
                  "nav_momentum": nav_momentum}
    strategy = strategies.get(str(args.strategy))
    if strategy is None:
        print(f"未知净值策略 {args.strategy!r}（{sorted(strategies)}）")
        return 2
    symbols = [s.strip() for s in str(args.symbols or "").split(",") if s.strip()]
    if not symbols:
        print("错误：nav-backtest 需要 --symbols（如 5089000,PF_001,AM_001）")
        return 2
    fetcher = NavFetcher()
    navs, missing = {}, []
    for symbol in symbols:
        try:
            navs[symbol] = _nav_frame_for(symbol, fetcher)
        except NavDataUnavailableError as exc:
            missing.append((symbol, str(exc)))
    if missing:
        for symbol, why in missing:
            print(f"  [缺失] {symbol}：{why}")
        print("私募/资管净值需先用 manual_nav_import 导入 CSV；"
              "组合缺一只会让权重失真，fail-closed 拒绝运行。")
        return 2
    engine = FOFBacktester(product_type=args.product_type,
                           initial_capital=args.initial_cash)
    result = engine.set_navs(navs).run(
        strategy, strategy_params=parse_params(args.params))
    print_metrics(result.metrics())
    print(f"费用拆解：{result.fee_breakdown}")
    print(f"交易记录 {len(result.trades)} 笔；调仓 "
          f"{len(result.weights_history)} 次")
    return 0


def cmd_reits_monitor(args) -> int:
    """REITs 折溢价监控（提醒≠拦截；阈值默认读 config，CLI 可覆盖）。"""
    from data.fetcher_nav import NavDataUnavailableError, NavFetcher
    from core.notifier import ConsoleNotifier
    from core.qi_monitor import detect_reits_premium

    fetcher = NavFetcher()
    symbols = [s.strip() for s in str(args.symbols or "").split(",") if s.strip()]
    if not symbols:
        print("错误：reits-monitor 需要 --symbols（如 508000）")
        return 2
    backup = dict(config.QI_REITS_PREMIUM_THRESHOLDS)
    try:
        thresholds = dict(backup)
        if args.premium_threshold is not None:
            thresholds["premium"] = float(args.premium_threshold)
        if args.discount_threshold is not None:
            thresholds["discount"] = float(args.discount_threshold)
        config.QI_REITS_PREMIUM_THRESHOLDS.clear()
        config.QI_REITS_PREMIUM_THRESHOLDS.update(thresholds)
        notifier = ConsoleNotifier()
        alerted = 0
        for symbol in symbols:
            try:
                merged = fetcher.fetch_reits_merged(symbol)
            except NavDataUnavailableError as exc:
                print(f"  [数据不可用] {symbol}：{exc}")
                continue
            premium = merged.get("premium_pct")
            if premium is None or len(premium) == 0:
                continue
            last = float(premium.iloc[-1])
            alert = detect_reits_premium(symbol, last, notifier=notifier)
            if alert:
                alerted += 1
                print(f"  [提醒] {symbol} {alert['kind']} {last:.2%}")
            else:
                print(f"  [正常] {symbol} 折溢价 {last:.2%}（阈值内）")
        print(f"共 {len(symbols)} 只，触发提醒 {alerted} 只（提醒不等于拦截）。")
        return 0
    finally:
        config.QI_REITS_PREMIUM_THRESHOLDS.clear()
        config.QI_REITS_PREMIUM_THRESHOLDS.update(backup)


def cmd_neeq_screen(args) -> int:
    """新三板价值筛选：低 PB + 高 ROE + 流动性过滤（基本面需本地 CSV）。"""
    from data.fetcher_nav import NavDataUnavailableError, NavFetcher
    from nav_backtest.strategies import neeq_value_screen

    try:
        listing = NavFetcher().fetch_neeq_list(str(args.layer))
    except NavDataUnavailableError as exc:
        print(f"新三板挂牌列表获取失败：{exc}")
        return 2
    print(f"新三板 {args.layer} 层挂牌 {len(listing)} 家。")
    if not args.fundamentals:
        print("未提供 --fundamentals（本地 CSV，列：symbol,pb,roe,volume），"
              "仅列出挂牌清单，不做价值筛选。")
        return 0
    import pandas as pd

    frame = pd.read_csv(args.fundamentals)
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    weights = neeq_value_screen(frame, top_k=int(args.top),
                                 max_pb=float(args.max_pb),
                                 min_roe=float(args.min_roe))
    if not weights:
        print("筛选后无标的（放宽 --max-pb/--min-roe 或检查 CSV 数据）。")
        return 0
    print(f"\n价值筛选 Top {len(weights)}（低 PB + 高 ROE + 流动性）：")
    for symbol, weight in weights.items():
        print(f"  {symbol}  权重 {weight:.1%}")
    print("注：新三板流动性差，实盘下单前必须人工复核，权重仅供研究。")
    return 0


def cmd_qi_check(args) -> int:
    """合格投资者资格自检（三套门槛不混用，fail-closed）。"""
    from core.qualified_investor import QIChecker

    raw = str(args.profile or "").strip()
    if not raw:
        print("错误：qi-check 需要 --profile（JSON 文件路径或内联 JSON）")
        return 2
    text = Path(raw).read_text(encoding="utf-8") if Path(raw).exists() else raw
    profile = json.loads(text)
    checker = QIChecker()
    verdict = checker.check_action(str(args.action), profile,
                                   product_type=str(args.product_type),
                                   amount_wan=float(args.amount) if args.amount else None,
                                   raise_on_fail=False)
    status = "通过" if verdict.ok else "不通过（fail-closed，该动作将被拒绝）"
    print(f"合格投资者校验（动作 {args.action} / 产品 {args.product_type}）：{status}")
    if verdict.rule:
        print(f"  规则：{verdict.rule}")
    else:
        print("  规则：未知产品类型（三套门槛不混用：private_fund / amr / trust）")
    if verdict.reasons:
        print("  原因：")
        for reason in verdict.reasons:
            print(f"    - {reason}")
    print(f"  留痕：{len(checker.audit_trail())} 条（audit_log_required）。")
    return 0 if verdict.ok else 1


_TERMINAL_ORDER_STATUS = {"filled", "rejected", "canceled", "cancelled",
                          "expired", "closed"}


def _ledger_exposure():
    """读取持久化账本，供切模式前的「无仓无在途单」校验（fail-closed）。

    账本来源：模拟盘 `paper_account.json`（持仓 + 挂单）与实盘幂等账本
    `live_trading/order_ids.json`（未终结状态视为在途单）。任何账本读不出来
    都按拒绝处置——切模式时看不到仓，等于给「带仓降级」开后门。
    """
    positions, open_orders = {}, []
    paper_file = Path(config.DATA_CACHE_DIR) / "paper_account.json"
    if paper_file.exists():
        try:
            data = json.loads(paper_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise cli_gate.RunModeError(
                f"模拟盘账本损坏或不可读：{paper_file}（{exc}）——拒绝切模式")
        for key in ("positions", "short_positions"):
            for rec in data.get(key) or []:
                symbol = str((rec or {}).get("symbol") or "")
                if symbol:
                    positions[symbol] = (positions.get(symbol, 0.0)
                                         + float(rec.get("volume", 0) or 0))
        open_orders.extend(data.get("orders") or [])

    live_file = Path(gov("LIVE_SAFETY")["idempotency"]["persist_path"])
    live_file = live_file if live_file.is_absolute() else Path(config.BASE_DIR) / live_file
    if live_file.exists():
        try:
            records = json.loads(live_file.read_text(encoding="utf-8") or "{}")
        except (json.JSONDecodeError, OSError) as exc:
            raise cli_gate.RunModeError(
                f"实盘幂等账本损坏或不可读：{live_file}（{exc}）——拒绝切模式")
        for key, rec in dict(records or {}).items():
            status = str((rec or {}).get("status") or "").lower()
            if status not in _TERMINAL_ORDER_STATUS:
                open_orders.append({"client_order_id": key})
    return positions, open_orders


def cmd_set_mode(args) -> int:
    """运行模式切换：只允许降级；提升需 checklist 无 FAIL + --confirm。

    K6④：切换模式（**含降级**）前必须无持仓、无在途单——有仓时切回 backtest
    等于放弃实盘风控，因此该闸门先于 enter_mode 执行。
    """
    from live import mode_guard
    from live.errors import ModeGuardError

    target = str(args.to)
    try:
        positions, open_orders = _ledger_exposure()
        mode_guard.assert_mode_change_allowed(
            target, positions={s: {"volume": v} for s, v in positions.items()},
            open_orders=open_orders, current=cli_gate.current_mode())
    except ModeGuardError as exc:
        print(f"切模式被拒：{exc}")
        return 2
    except cli_gate.RunModeError as exc:
        print(f"模式错误：{exc}")
        return 2

    try:
        cli_gate.enter_mode(target, strategy=args.strategy, confirm=bool(args.confirm))
    except cli_gate.RunModePromotionError as exc:
        print(f"提升被拒：{exc}")
        print("（模式阶梯只允许降级；提升需 --strategy 过上线检查清单且 --confirm 显式确认）")
        return 2
    except cli_gate.RunModeError as exc:
        print(f"模式错误：{exc}")
        return 2
    print(f"运行模式已切换：{cli_gate.current_mode()}")
    return 0


def add_subparser(sp) -> None:
    """注册合格投资者层子命令（含 set-mode 控制平面入口）。"""
    p = sp.add_parser("nav-backtest", help=f"[{GROUP}] 净值型 FOF 组合回测")
    p.add_argument("--strategy", default="equal_weight",
                   choices=["equal_weight", "risk_parity", "nav_momentum"])
    p.add_argument("--symbols", required=True,
                   help="净值标的（REITs 代码或私募登记号，逗号分隔）")
    p.add_argument("--product-type", dest="product_type", default="private_fund",
                   help="产品类型：private_fund / amr / trust")
    p.add_argument("--params", help="策略参数 k=v,k=v")
    p.add_argument("--initial-cash", dest="initial_cash", type=float,
                   default=DEF("initial_cash"))
    p.set_defaults(handler=cmd_nav_backtest)

    p = sp.add_parser("reits-monitor", help=f"[{GROUP}] REITs 折溢价监控（提醒≠拦截）")
    p.add_argument("--symbols", required=True, help="REITs 代码逗号分隔")
    p.add_argument("--premium-threshold", dest="premium_threshold", type=float,
                   help="溢价提醒阈值（默认读 config）")
    p.add_argument("--discount-threshold", dest="discount_threshold", type=float,
                   help="折价提醒阈值（默认读 config）")
    p.set_defaults(handler=cmd_reits_monitor)

    p = sp.add_parser("neeq-screen", help=f"[{GROUP}] 新三板价值筛选")
    p.add_argument("--layer", default="innovation",
                   choices=["innovation", "basic"])
    p.add_argument("--fundamentals", help="基本面 CSV（symbol,pb,roe,volume）")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--max-pb", dest="max_pb", type=float, default=2.0)
    p.add_argument("--min-roe", dest="min_roe", type=float, default=0.08)
    p.set_defaults(handler=cmd_neeq_screen)

    p = sp.add_parser("qi-check", help=f"[{GROUP}] 合格投资者资格自检（三套门槛）")
    p.add_argument("--profile", required=True, help="投资者画像 JSON（文件或内联）")
    p.add_argument("--action", default="subscribe",
                   choices=["subscribe", "transfer", "additional_subscribe",
                            "nominee_change"])
    p.add_argument("--product-type", dest="product_type", default="private_fund",
                   help="产品类型：private_fund / amr / trust")
    p.add_argument("--amount", type=float, help="申购金额（万元）")
    p.set_defaults(handler=cmd_qi_check)

    p = sp.add_parser("set-mode", help=f"[{GROUP}] 运行模式切换（只允许降级）")
    p.add_argument("--to", required=True, choices=cli_gate.ladder(),
                   help="目标模式（提升需清单+确认）")
    p.add_argument("--strategy", help="提升时过上线检查清单的策略名")
    p.add_argument("--confirm", action="store_true", help="提升时的显式确认")
    p.set_defaults(handler=cmd_set_mode)


def handler(args) -> int:
    """qi 模块统一分发（各子命令自带 handler）。"""
    return int((getattr(args, "handler", None) or cmd_qi_check)(args))
