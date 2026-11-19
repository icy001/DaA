# -*- coding: utf-8 -*-
"""策略上线检查清单命令（四类计数：通过 / 警告 / 不通过 / 不适用）。"""
from __future__ import annotations

from core import cli_gate
from cli_commands._common import *  # noqa: F401,F403

GROUP = "策略研究"
DEF = cli_gate.cli_default

def cmd_checklist(args) -> int:
    from tools import strategy_checklist
    argv = ["--strategy", args.strategy]
    if args.record:
        argv += ["--record", args.record]
    return int(strategy_checklist.main(argv))


def add_subparser(sp) -> None:
    """注册 checklist 子命令（四类计数：通过 / 警告 / 不通过 / 不适用）。"""
    p = sp.add_parser("checklist", help=f"[{GROUP}] 策略上线检查清单（四类计数）")
    p.add_argument("--strategy", required=True, help="策略名（strategies/<name>.py）")
    p.add_argument("--record", help="实验记录 JSON（默认取最新）")
    p.set_defaults(handler=handler)


def handler(args) -> int:
    """跑 16 项上线清单，并显式给出口径对照的四类计数。"""
    from tools import strategy_checklist
    from tools.strategy_checklist import FAIL, NA, PASS, WARN, build_rows

    argv = ["--strategy", args.strategy]
    if getattr(args, "record", None):
        argv += ["--record", args.record]
    code = int(strategy_checklist.main(argv))
    if code == 2:
        return code

    try:
        rows = build_rows(str(args.strategy), {}, 0.2, 1e7)
    except Exception:  # noqa: BLE001 - 计数失败不影响主流程结论
        return code
    counts = {s: sum(1 for r in rows if len(r) >= 3 and r[2] == s)
              for s in (PASS, WARN, FAIL, NA)}
    ran = counts[PASS] + counts[WARN] + counts[FAIL]
    print(f"口径对照：已跑 {ran} 项 · 未跑 {counts[NA]} 项（不适用/未实现，"
          f"已在上表逐项列出）· 跳过 0 项 · 失败 {counts[FAIL]} 项")
    return code
