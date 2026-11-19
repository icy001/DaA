# -*- coding: utf-8 -*-
"""实盘启动入口（run_live.py）—— 12.12。

流程：**强制打印风险提示** → 选择模式/券商 → 真实实盘二次输入
``YES_CONFIRM_LIVE_TRADING`` → 凭证/行情/风控/对账/急停全套自检 →
（可用 ``--watch-only`` 只盯盘不下单）→ 启动守护 + 急停监听线程。

安全默认
========
* ``LIVE_TRADING_ENABLED=False`` 时 ``--mode live`` 直接拒绝；
* ``--panic`` 是独立进程：只写急停标志文件，由运行中的进程独立线程执行撤单/断线/告警；
* ``--checklist`` 复用 ``tools/live_checklist.py`` 的 15 项检查。
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime

import config
from core.gov_compat import gov
from broker.base_broker import LIVE_TRADING_ENABLED
from broker.sim_broker import SimBroker
from data.live_data import LiveDataEngine
from live.audit_log import AuditLog
from live.daemon import LiveDaemon, check_credentials
from live.kill_switch import KillSwitch, PanicController
from live.live_trader import LiveTrader
from live.notifier import LiveNotifier

RISK_BANNER = """
============================================================
  实盘交易风险提示（请务必阅读）
------------------------------------------------------------
  * 程序化交易可能因代码缺陷、网络中断、行情异常导致亏损；
  * 本系统默认关闭真实下单（LIVE_TRADING_ENABLED=False）；
  * 真实实盘需手动输入 YES_CONFIRM_LIVE_TRADING 二次确认；
  * 场外衍生品（雪球/TRS/期权组合）个人禁止实盘，只允许仿真；
  * 首笔实盘限额 10000 元，确认通道正常后才放开；
  * 急停：python run_live.py --panic（独立进程，立即撤单停机）。
============================================================
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="实盘启动入口（A股 + 国内期货）")
    parser.add_argument("--broker", default=config.BROKER_DEFAULT,
                        choices=["qmt", "ptrade", "ctp", "sim"],
                        help="券商/期货通道；sim 为内存仿真")
    parser.add_argument("--mode", default="live_sim",
                        choices=["backtest", "paper", "live_sim", "live"],
                        help="运行模式；live 需双层开关 + 二次确认")
    parser.add_argument("--strategy", default="", help="策略名或策略文件路径")
    parser.add_argument("--symbols", default="", help="逗号分隔标的")
    parser.add_argument("--market", default="cn_stock", help="市场类型")
    parser.add_argument("--interval", type=float, default=3.0, help="轮询间隔秒")
    parser.add_argument("--watch-only", action="store_true",
                        help="只盯盘不下单：信号只推送，不发任何委托")
    parser.add_argument("--panic", action="store_true",
                        help="独立进程急停：写标志文件并退出")
    parser.add_argument("--clear-kill-switch", default="",
                        help="人工解除急停（需确认口令）")
    parser.add_argument("--confirm", action="store_true",
                        help="已阅读风险提示（真实实盘仍需输入确认串）")
    parser.add_argument("--confirm-first-order", action="store_true",
                        help="确认通道正常，放开首笔限额")
    parser.add_argument("--checklist", action="store_true", help="只跑实盘前 15 项检查")
    return parser


def build_broker(name: str, simulated: bool):
    if name == "sim":
        return SimBroker()
    if name == "qmt":
        from broker.qmt_broker import QMTBroker
        return QMTBroker()
    if name == "ptrade":
        from broker.ptrade_broker import PTradeBroker
        return PTradeBroker(simulated=simulated)
    from broker.ctp_broker import CTPBroker
    return CTPBroker(simulated=simulated)


def _confirm_live() -> bool:
    if not LIVE_TRADING_ENABLED or not config.LIVE_TRADING_ENABLED:
        print("[拒绝] 真实实盘未开启：代码层与 config 层 LIVE_TRADING_ENABLED 必须同时为 true")
        return False
    try:
        answer = input(f"真实资金报单，请输入 {config.CONFIRM_LIVE_KEYWORD} 确认：")
    except (EOFError, KeyboardInterrupt):
        print("\n[拒绝] 未获得二次确认，已退出")
        return False
    return answer.strip() == config.CONFIRM_LIVE_KEYWORD


class _WatchOnly:
    """只盯盘模式：所有下单入口都被拒绝，信号只推送。

    watch-only 推送是第六个信号出口（config.SIGNAL_EGRESS_CONFORMANCE），
    必须与 place_order 一样过同一份 core/signal_gate.py：预热 / 时效 / 时段缺一不推。
    """

    def __init__(self, trader: LiveTrader, notifier: LiveNotifier) -> None:
        self._trader = trader
        self._notifier = notifier

    def _gate(self, symbol: str, direction: str, bar: dict, market: str = None) -> str:
        """返回拦截原因；空串表示放行。"""
        from core import signal_gate
        from core.utils import get_trading_sessions

        if not bar:
            return "缺少行情快照，无法校验预热/时效"
        missed = signal_gate.check_order(
            direction, signal_gate.bar_warmup_ok(bar), symbol=symbol)
        if missed is not None:
            return missed.get("reason", "指标预热期，禁止推送开仓信号")
        try:
            self._trader._freshness(symbol, direction, bar, market)
        except Exception as exc:                       # 时效不通过：只报数据异常，不推信号
            return f"数据时效不通过：{exc}"
        now = datetime.now()
        sessions = get_trading_sessions(
            market or config.detect_market_type(symbol), now)
        if not any(start <= now <= end for start, end in sessions):
            return "非交易时段，不推送交易信号"
        return ""

    def _reject(self, symbol, volume, direction="", **kwargs) -> dict:
        bar = kwargs.get("bar") or {}
        market = kwargs.get("market") or kwargs.get("market_type")
        blocked = self._gate(symbol, direction, bar, market)
        rec = {"symbol": symbol, "volume": volume, "direction": direction,
               "ok": False, "status": "rejected",
               "stage": "watch_only_blocked" if blocked else "watch_only",
               "reason": blocked or "只盯盘模式：不下单，仅推送信号"}
        if blocked:
            self._notifier.on_risk(f"{symbol} {direction} 信号未推送：{blocked}")
            return rec
        self._notifier.on_signal(f"{symbol} 触发信号（watch-only，未下单）")
        return rec

    def buy(self, symbol, volume, **kwargs):
        return self._reject(symbol, volume, "buy", **kwargs)

    def sell(self, symbol, volume, **kwargs):
        return self._reject(symbol, volume, "sell", **kwargs)

    def short(self, symbol, volume, **kwargs):
        return self._reject(symbol, volume, "short", **kwargs)

    def cover(self, symbol, volume, **kwargs):
        return self._reject(symbol, volume, "cover", **kwargs)

    def __getattr__(self, item):
        return getattr(self._trader, item)


def _load_strategy(spec: str):
    if not spec:
        return None
    from core import strategy_loader
    from pathlib import Path
    if Path(spec).suffix == ".py" and Path(spec).exists():
        return strategy_loader.load_class_from_file(Path(spec))()
    return strategy_loader.get(spec)()


def _run_loop(trader, engine, symbols, interval: float) -> None:
    """轮询行情；缺三物化列的 tick 一律跳过（fail-closed，不生成信号）。"""
    required = ("warmup_ok", "data_asof_date", "price_adjust")
    engine.subscribe(symbols)
    while True:
        ticks = engine.poll()
        bars = {}
        for tick in ticks:
            missing = [c for c in required if c not in tick]
            if missing:
                if getattr(engine, "logger", None):
                    engine.logger.warning("行情缺少三物化列 %s，跳过 %s 的信号",
                                          missing, tick.get("symbol"))
                continue
            bars[str(tick["symbol"])] = tick
        if bars:
            trader.on_tick(bars)
        time.sleep(interval)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    # v3.49 / 13.0.20 ④：--mode 解析后立刻过封闭白名单（查矩阵/分支之前）。
    # argparse choices 只是「当前这份代码」的枚举；.env RUN_MODE 或自定义串
    # 仍要同一条校验，且不做 strip/纠正——"liv " 这类带空格笔误必须直接拒。
    from core import cli_gate
    try:
        args.mode = cli_gate.validate_mode(args.mode)
    except cli_gate.RunModeError as exc:
        print(f"[拒绝] 运行模式非法：{exc}")
        return 2

    if args.checklist:
        from tools.live_checklist import main as checklist_main
        return checklist_main([])

    if args.panic:
        flag = KillSwitch().trigger("cli --panic（独立进程急停）")
        print(f"[急停] 已写入标志文件并退出：{flag}")
        print("运行中的实盘进程会在独立线程内撤单/断线/告警；"
              f"恢复需人工确认口令 {gov('LIVE_SAFETY')['kill_switch']['manual_clear_token']}")
        return 0

    if args.clear_kill_switch:
        try:
            KillSwitch().clear(args.clear_kill_switch)
            print("[急停] 已人工确认解除")
            return 0
        except Exception as exc:  # noqa: BLE001 - 口令不符即拒
            print(f"[急停] 解除失败：{exc}")
            return 2

    print(RISK_BANNER)
    if not args.confirm:
        print("请先阅读风险提示并加 --confirm 再启动；急停用 python run_live.py --panic")
        return 2

    simulated = args.mode != "live"
    if args.mode == "live" and not _confirm_live():
        return 2

    from core import spec_check
    try:
        spec_check.enforce_on_startup(args.mode)
    except (RuntimeError, ValueError) as exc:
        print(f"[拒绝] 规格版本自校验未通过：{exc}")
        return 2

    broker = build_broker(args.broker, simulated=simulated)
    if args.broker != "sim":
        creds = check_credentials(args.broker)
        if not creds["ok"]:
            print(f"[拒绝] 凭证缺失：{creds['missing']}——{creds['hint']}")
            return 2
    try:
        broker.connect()
    except Exception as exc:  # noqa: BLE001 - 实盘连不上必须停机
        print(f"[拒绝] 券商连接失败：{exc}（禁止静默退回仿真/回测）")
        return 2

    audit = AuditLog(account_id=getattr(broker, "account_id", ""),
                     strategy_id=args.strategy or "live")
    notifier = LiveNotifier(logger=None)
    trader = LiveTrader(broker, mode=args.mode, simulated=simulated,
                        strategy_id=args.strategy or "live", audit=audit,
                        notifier=notifier,
                        first_order_confirmed=args.confirm_first_order)
    engine = LiveDataEngine(args.mode, broker=broker, logger=trader.logger)
    strategy = _load_strategy(args.strategy)
    daemon = LiveDaemon(trader, broker=broker, data_engine=engine,
                        notifier=notifier, audit=audit, strategy=strategy,
                        broker_type=args.broker,
                        panic=PanicController(trader.kill_switch, broker, notifier, audit))
    check = daemon.pre_open_check()
    if not check["ok"]:
        print(f"[拒绝] 开盘前自检失败：{check['failed']}")
        for name in check["failed"]:
            print(f"  - {name}: {check['checks'][name]['detail']}")
        return 2
    print(f"[自检] 通过：{sorted(check['checks'])}")

    target = _WatchOnly(trader, notifier) if args.watch_only else trader
    if strategy is not None:
        target.start(strategy)
    daemon.start()
    symbols = [s for s in args.symbols.split(",") if s.strip()]
    mode_label = f"[{args.mode.upper()}]" + (" 只盯盘" if args.watch_only else "")
    print(f"{mode_label} 启动：{args.broker} / {args.market} / {len(symbols)} 个标的")
    try:
        if symbols:
            _run_loop(target, engine, symbols, max(0.5, args.interval))
        else:
            print("未指定 --symbols：自检完成，不启动行情循环")
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C：走优雅停机（先撤未成交单，不挂单过夜）")
        daemon.graceful_exit()
        trader.kill_switch.trigger("Ctrl+C 人工中断")
    return 0


if __name__ == "__main__":
    sys.exit(main())
