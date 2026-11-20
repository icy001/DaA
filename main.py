# -*- coding: utf-8 -*-
"""多市场量化交易系统入口（main.py）——第 11 步：薄入口 / 控制平面。

**main.py 只做三件事（CLI_CONFORMANCE['thin_entry']，硬约束 ≤300 行）**
==============================================================
1. 顶层 argparse 解析器与子命令注册：每个子命令模块（``cli_commands/*.py``）
   暴露 ``add_subparser(sp)`` / ``handler(args)``，本文件只 import 并注册；
2. 调用 ``core.cli_gate`` 做控制平面校验：旁路开关黑名单、RUN_MODE 只允许降级、
   子命令默认值统一取 ``config.CLI_CONFORMANCE['cli_defaults']``；
3. 按 ``args.handler`` 分发到对应 ``cli_commands`` 子模块。

业务代码一律不进本文件：新增子命令只改 ``cli_commands/`` 对应模块，
不改 main.py（避免长文件写入损坏与口径漂移）。
"""
from __future__ import annotations

import argparse
import sys

import config  # noqa: F401 - 供子模块与测试经 main 访问统一配置入口
from core import cli_gate
from core.utils import MARKET_NAMES

VERSION = config.SPEC_VERSION  # 版本号单一事实来源 = 治理块，禁止在此硬编码（曾脱节到 v3.17）
VERSION_DESC = "全市场+合格投资者层+行情K线+因子研究+一键入口（控制平面）"

# 命令模块（顺序即 --help 显示顺序）；每个模块提供 add_subparser(sp) / handler(args)
MODULES = ("retail", "research", "checklist", "factor", "data", "qi",
           "derivatives", "check_config")


def welcome() -> None:
    """无参数运行时的欢迎页：版本 / 市场 / 当前运行模式。"""
    markets = "、".join(sorted(MARKET_NAMES.values()))
    print(f"多市场量化交易系统 {VERSION} —— {VERSION_DESC}")
    print(f"运行模式：{cli_gate.current_mode()}（阶梯 {cli_gate.ladder()}，"
          "只允许降级；提升需上线检查清单 + 显式确认）")
    print(f"覆盖市场：{markets}")
    print("快速上手：python main.py --help 查看全部子命令；"
          "python main.py backtest --help 查看单个命令。")


def build_parser() -> argparse.ArgumentParser:
    """顶层解析器：只注册子命令，默认值全部由子模块经 cli_gate.cli_default 取值。"""
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="多市场量化交易系统一键入口（控制平面：模式只允许降级、"
                    "禁止旁路开关、默认值单一事实源 config）",
        epilog=f"版本 {VERSION}。运行模式阶梯：{cli_gate.ladder()}"
               "（降级放行、提升需清单+确认）。")
    sp = parser.add_subparsers(dest="command", metavar="子命令")

    import importlib

    for name in MODULES:
        module = importlib.import_module(f"cli_commands.{name}")
        module.add_subparser(sp)
    return parser


def main(argv=None) -> int:
    """控制平面入口：旁路闸门 → 解析 → 注册面审计 → 分发。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    cli_gate.guard_argv(argv)          # 第一道防线：旁路开关黑名单
    parser = build_parser()
    args = parser.parse_args(argv)
    cli_gate.assert_no_bypass_registration(parser)   # 字符串黑名单：注册面审计
    cli_gate.assert_no_structural_bypass(parser)     # 结构化审计：只看能力不看名字
    if not getattr(args, "command", None):
        welcome()
        return 0
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    return int(handler(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
