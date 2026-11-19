# -*- coding: utf-8 -*-
"""策略研究命令：脚手架 / 列表 / 优化 / 走向前 / 稳健性 / 实验对比。"""
from __future__ import annotations

from core import cli_gate
from cli_commands._common import *  # noqa: F401,F403

GROUP = "策略研究"
DEF = cli_gate.cli_default


def cmd_new_strategy(args) -> int:
    from tools import new_strategy
    argv = ["--name", args.name, "--template", args.template]
    if getattr(args, "overwrite", False):
        argv.append("--force")
    return int(new_strategy.main(argv))


def cmd_list_strategies(_args) -> int:
    from core.strategy_loader import list_all, unavailable

    rows = list_all()
    if not rows:
        print("未发现任何策略（strategies/*.py）。可用 python main.py new-strategy 生成脚手架。")
        return 0
    print(f"{'名称':<24}{'中文名':<18}{'版本':<8}适用市场")
    for row in rows:
        print(f"{row['name']:<24}{row['display_name']:<18}{row['version']:<8}"
              f"{','.join(row['markets'])}")
    bad = unavailable()
    if bad:
        print("\n不可用策略：")
        for item in bad:
            print(f"  - {item['file']} :: {item['class']} → {item['reason']}")
    return 0


def cmd_optimize(args) -> int:
    from core.runner import run_optimize
    from core.strategy_loader import get

    _params, symbols, start, end = _resolve_run_args(args)
    cfg = load_strategy_config(args.strategy)
    grid = dict(cfg.get("optimize") or {})
    if not grid:
        print("错误：yaml 中没有 optimize 搜索范围")
        return 2
    out = run_optimize(get(args.strategy), grid, symbols=symbols, start=start, end=end,
                       method=args.method, n_iter=args.n_iter, top_n=args.top_n)
    print("\nTop 参数（按得分）：")
    for row in out["top"]:
        print(f"  {row['params']}  score={row['score']:.4f}  "
              f"sharpe={row['metrics'].get('sharpe', 0):.3f}")
    rec = out.get("recommended")
    if rec:
        print(f"\n推荐（参数平原中心）：{rec['params']}  平原分={rec['plateau_score']:.4f}")
    if not out["sensitivity"].empty:
        print("\n参数敏感性（前两维）：")
        print(out["sensitivity"].round(3).to_string())
    return 0


def cmd_walkforward(args) -> int:
    """走向前分析：--train/--test 为月数（换算为滚动段数与训练占比）。"""
    from core.strategy_loader import get
    from research.walkforward import run_walkforward

    _params, symbols, start, end = _resolve_run_args(args)
    cfg = load_strategy_config(args.strategy)
    grid = dict(cfg.get("optimize") or {})
    if not symbols:
        print("错误：未提供 symbols")
        return 2
    train_m, test_m = int(args.train), int(args.test)
    total_m = _month_span(start, end)
    n_splits = max(1, min(int(args.splits) or total_m // (train_m + test_m) or 1,
                          total_m // max(1, train_m + test_m)))
    ratio = round(train_m / float(train_m + test_m), 4)
    out = run_walkforward(get(args.strategy), grid, symbols, start, end,
                          n_splits=n_splits, train_ratio=ratio,
                          optimizer=args.method, metric=args.metric)
    segs = out.get("segments") or []
    print(f"走向前分析：{len(segs)} 段（训练 {train_m} 月 / 检验 {test_m} 月）")
    for seg in segs:
        oos = (seg.get("oos_metrics") or {}).get("total_return")
        print(f"  {seg.get('test_start')} → {seg.get('test_end')}"
              f"  样本外收益 {oos if oos is None else format(oos, '+.2%')}"
              f"  参数 {seg.get('best_params')}")
    oos_nav = out.get("oos_nav")
    if oos_nav is not None and len(oos_nav):
        print(f"样本外拼接净值：{len(oos_nav)} 个点，末值 "
              f"{float(oos_nav.iloc[-1]):.4f}")
    deg = out.get("degradation")
    print(f"样本内→样本外夏普衰减：{'' if deg is None else format(deg, '.0%')}")
    return 0


def cmd_validate(args) -> int:
    """稳健性评分卡（validate_robustness 唯一实现，四项压力全开）。"""
    from core.strategy_loader import get
    from research.validator import validate_robustness

    params, symbols, start, end = _resolve_run_args(args)
    if not symbols:
        print("错误：未提供 symbols")
        return 2
    cfg = load_strategy_config(args.strategy)
    grid = dict(cfg.get("optimize") or {})
    picked = [args.cost_x2, args.delay > 0, args.noise]
    print(f"稳健性压力（--cost-x2/--delay/--noise 为显式声明；评分卡四项全跑）："
          f"成本×2={'开' if picked[0] else '默认开'}，延迟={args.delay} 根，"
          f"噪声={'开' if picked[2] else '默认开'}")
    out = validate_robustness(get(args.strategy), params, grid, symbols,
                               start, end, n_perturb=args.n_perturb, seed=args.seed)
    print("\n稳健性评分卡：")
    for chk in out.get("checks") or []:
        print(f"  [{chk['status']}] {chk['name']} —— {chk['detail']}")
    print(f"\n总体：评分 {out.get('score', 0)}/100，全部通过="
          f"{out.get('passed', False)}")
    return 0


def cmd_experiments(args) -> int:
    from research.registry import ExperimentRegistry

    reg = ExperimentRegistry()
    rows = reg.list(limit=int(args.limit))
    if not rows:
        print("暂无实验记录（回测结果会自动写入 research_output/experiments/）。")
        return 0
    print(f"{'实验ID':<34}{'时间':<20}{'策略':<18}总收益     夏普")
    for rec in rows:
        m = rec.get("metrics") or {}
        tr = m.get("total_return")
        sh = m.get("sharpe")
        print(f"{rec.get('exp_id', ''):<34}{str(rec.get('time', ''))[:19]:<20}"
              f"{str(rec.get('strategy', '')):<18}"
              f"{'' if tr is None else format(tr, '+.2%'):>10}"
              f"{'' if sh is None else format(sh, '.3f'):>8}")
    return 0


def cmd_compare(args) -> int:
    from research.registry import ExperimentRegistry

    ids = [s.strip() for s in str(args.exp).split(",") if s.strip()]
    if not ids:
        print("错误：--exp 需要逗号分隔的实验 ID")
        return 2
    table = ExperimentRegistry().compare(ids)
    if table.empty:
        print(f"找不到实验记录：{ids}")
        return 1
    print(table.to_string())
    return 0


def add_subparser(sp) -> None:
    """注册策略研究全部子命令（默认值一律经 DEF 引用 config）。"""
    p = sp.add_parser("new-strategy", help=f"[{GROUP}] 生成策略脚手架")
    p.add_argument("--name", required=True, help="策略名（蛇形命名）")
    p.add_argument("--template", default="trend", help="模板：trend / grid 等")
    p.add_argument("--overwrite", action="store_true", help="覆盖已存在文件")
    p.set_defaults(handler=cmd_new_strategy)

    p = sp.add_parser("list-strategies", help=f"[{GROUP}] 列出全部已注册策略")
    p.set_defaults(handler=cmd_list_strategies)

    p = sp.add_parser("optimize", help=f"[{GROUP}] 参数寻优（网格/随机/贝叶斯）")
    p.add_argument("--strategy", required=True)
    p.add_argument("--symbols", help="逗号分隔标的（缺省读 yaml）")
    p.add_argument("--method", default=DEF("optimize_method"),
                   choices=["grid", "random", "bayes"])
    p.add_argument("--n-iter", dest="n_iter", type=int, default=DEF("n_iter"))
    p.add_argument("--top-n", dest="top_n", type=int, default=DEF("top_n"))
    p.add_argument("--start", default=DEF("start"))
    p.add_argument("--end", default=DEF("end"))
    p.set_defaults(handler=cmd_optimize)

    p = sp.add_parser("walkforward", help=f"[{GROUP}] 走向前分析（样本外检验）")
    p.add_argument("--strategy", required=True)
    p.add_argument("--symbols", help="逗号分隔标的（缺省读 yaml）")
    p.add_argument("--train", type=int, default=24, help="训练窗口（月）")
    p.add_argument("--test", type=int, default=6, help="检验窗口（月）")
    p.add_argument("--splits", type=int, default=0, help="滚动段数（0=自动）")
    p.add_argument("--method", default=DEF("optimize_method"))
    p.add_argument("--metric", default="sharpe")
    p.add_argument("--start", default=DEF("start"))
    p.add_argument("--end", default=DEF("end"))
    p.set_defaults(handler=cmd_walkforward)

    p = sp.add_parser("validate", help=f"[{GROUP}] 稳健性与压力测试（四项）")
    p.add_argument("--strategy", required=True)
    p.add_argument("--symbols", help="逗号分隔标的（缺省读 yaml）")
    p.add_argument("--params", help="最优参数 k=v,k=v")
    p.add_argument("--cost-x2", dest="cost_x2", action="store_true",
                   help="显式声明成本×2（评分卡默认四项全跑）")
    p.add_argument("--delay", type=int, default=1, help="成交延迟根数")
    p.add_argument("--noise", action="store_true", help="显式声明数据噪声")
    p.add_argument("--n-perturb", dest="n_perturb", type=int, default=100)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--start", default=DEF("start"))
    p.add_argument("--end", default=DEF("end"))
    p.set_defaults(handler=cmd_validate)

    p = sp.add_parser("experiments", help=f"[{GROUP}] 实验登记清单")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(handler=cmd_experiments)

    p = sp.add_parser("compare", help=f"[{GROUP}] 实验对比")
    p.add_argument("--exp", required=True, help="实验 ID 逗号分隔")
    p.set_defaults(handler=cmd_compare)


def handler(args) -> int:
    """research 模块统一分发（各子命令自带 handler）。"""
    return int((getattr(args, "handler", None) or cmd_list_strategies)(args))
