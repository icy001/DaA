# -*- coding: utf-8 -*-
"""因子研究流水线与市场检索命令。"""
from __future__ import annotations

import json
from pathlib import Path

import config
from core import cli_gate
from cli_commands._common import *  # noqa: F401,F403

GROUP = "策略研究"
DEF = cli_gate.cli_default

def _factor_list(text: str) -> list:
    if not text:
        return []
    out = []
    for item in str(text).split(","):
        item = item.strip()
        if not item:
            continue
        if "-" in item and item.split("-")[0].startswith("alpha"):
            head, tail = item.split("-", 1)
            prefix = "alpha" if head.startswith("alpha") else "alpha191_"
            try:
                start, end = int(head.replace("alpha191_", "").replace("alpha", "")), \
                    int(tail.replace("alpha", ""))
            except ValueError:
                out.append(item)
                continue
            width = 3 if prefix == "alpha191_" else 3
            out += [f"{prefix}{i:0{width}d}" for i in range(start, end + 1)]
        else:
            out.append(item)
    return out


def cmd_factor(args) -> int:
    action = args.factor_action
    if action == "calc":
        return _factor_calc(args)
    if action == "eval":
        return _factor_eval(args, all_factors=False)
    if action == "eval-all":
        return _factor_eval(args, all_factors=True)
    if action == "combine":
        return _factor_combine(args)
    if action == "corr":
        return _factor_corr(args)
    if action == "backtest":
        return _factor_backtest(args)
    if action == "research":
        return _factor_research(args)
    print(f"未知 factor 子命令 {action!r}")
    return 2


def _engine(source: str = "free"):
    from factor import create_factor_engine
    return create_factor_engine(source=source)


def _factor_calc(args) -> int:
    engine = _engine(args.source)
    factors = _factor_list(args.factors)
    panels = engine.compute(factors, universe=args.universe, start=args.start, end=args.end)
    for name, panel in panels.items():
        print(f"{name}: shape={panel.shape} 非空={panel.notna().sum().sum()}")
    return 0


def _factor_eval(args, all_factors: bool) -> int:
    from factor import evaluator

    engine = _engine(args.source)
    factors = (["alpha%03d" % i for i in range(1, 102)] if all_factors
               else _factor_list(args.factors or args.factor))
    if not factors:
        print("错误：请用 --factor/--factors 指定因子")
        return 2
    panels = engine.compute(factors, universe=args.universe, start=args.start, end=args.end)
    symbols = list(next(iter(panels.values())).columns) if panels else []
    data = engine._fetch_panels(symbols, args.start or config.DEFAULT_START,
                                args.end or str(config.DEFAULT_END))
    returns = data.close.pct_change()
    for name, panel in panels.items():
        ic = evaluator.calc_ic(panel, returns)
        print(f"\n[{name}] IC均值={ic['ic_mean']:.4f} ICIR={ic['icir']:.3f} "
              f"胜率={ic['ic_win_rate']:.1%}")
        report = evaluator.generate_factor_report(name, panel, returns)
        print(f"  报告：{report}")
    return 0


def _factor_combine(args) -> int:
    from factor import combiner

    engine = _engine(args.source)
    factors = _factor_list(args.factors)
    panels = engine.compute(factors, universe=args.universe, start=args.start, end=args.end)
    symbols = list(next(iter(panels.values())).columns) if panels else []
    data = engine._fetch_panels(symbols, args.start or config.DEFAULT_START,
                                args.end or str(config.DEFAULT_END))
    score = combiner.combine(args.method, panels, returns=data.close.pct_change())
    print(f"合成打分：shape={score.shape} 非空={score.notna().sum().sum()}")
    if args.save:
        out = Path(args.save)
        out.parent.mkdir(parents=True, exist_ok=True)
        score.to_parquet(out)
        print(f"已保存：{out}")
    return 0


def _factor_corr(args) -> int:
    from factor import evaluator

    engine = _engine(args.source)
    panels = engine.compute(_factor_list(args.factors), universe=args.universe,
                            start=args.start, end=args.end)
    result = evaluator.calc_factor_correlation(panels)
    print(result["matrix"].round(3).to_string())
    if result["redundant"]:
        print("\n冗余因子对（|corr|>0.7）：")
        for pair in result["redundant"]:
            print("  -", pair)
    return 0


def _factor_backtest(args) -> int:
    from core.runner import run_backtest
    from factor.factor_strategy import FactorStrategy

    params = {
        "factor_list": _factor_list(args.factors),
        "combine_method": args.method,
        "universe": args.universe,
        "n_top": args.n_top,
        "rebalance_freq": args.freq,
    }
    symbols = args.symbols.split(",") if args.symbols else None
    if symbols is None:
        print("提示：FactorStrategy 需要 --symbols（从股票池选 Top N 时也要给候选池）")
        return 2
    result = run_backtest(FactorStrategy, params=params, symbols=symbols,
                          start=args.start, end=args.end)
    print_metrics(result["metrics"])
    return 0


def _factor_research(args) -> int:
    from factor import combiner, evaluator

    engine = _engine(args.source)
    factors = _factor_list(args.factors)
    panels = engine.compute(factors, universe=args.universe, start=args.start, end=args.end)
    symbols = list(next(iter(panels.values())).columns) if panels else []
    data = engine._fetch_panels(symbols, args.start or config.DEFAULT_START,
                                args.end or str(config.DEFAULT_END))
    returns = data.close.pct_change()
    scores = {}
    for name, panel in panels.items():
        ic = evaluator.calc_ic(panel, returns)
        scores[name] = ic["icir"]
    keep = [k for k, v in scores.items() if v is not None and abs(v) >= args.min_icir]
    print(f"通过 ICIR>={args.min_icir} 的因子：{keep}")
    if not keep:
        print("没有因子达标，请先扩大样本或更换因子。")
        return 0
    kept = {k: panels[k] for k in keep}
    kept, dropped = combiner.dedupe(kept)
    print(f"去冗余剔除：{dropped}")
    score = combiner.combine(args.method, kept, returns=returns)
    print(f"合成打分：shape={score.shape}")
    out = Path(config.BASE_DIR / "research_output" / "factor_reports" / "combined_score.parquet")
    out.parent.mkdir(parents=True, exist_ok=True)
    score.to_parquet(out)
    print(f"已保存：{out}")
    return 0


def cmd_market(args) -> int:
    from factor.market import browser, importer, validator

    if args.market_action == "search":
        rows = browser.search_strategy(args.keyword)
        for row in rows:
            print(f"- [{row.get('source')}] {row.get('name')}  星级 {row.get('stars', 0)}")
            print(f"  {row.get('url')}")
            print(f"  {row.get('description')}")
        if not rows:
            print("没有匹配的策略源。")
        return 0
    if args.market_action == "import":
        result = importer.import_strategy(args.path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.market_action == "validate":
        result = validator.validate_strategy_file(args.path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not result.get("blocked") else 1
    return 2


def add_subparser(sp) -> None:
    """注册因子流水线与市场检索子命令。"""
    p = sp.add_parser("factor", help=f"[{GROUP}] 因子流水线")
    p.set_defaults(handler=cmd_factor)
    fs = p.add_subparsers(dest="factor_action", metavar="操作", required=True)

    def _common(sub):
        sub.add_argument("--factors", help="因子名逗号分隔（如 alpha001-alpha010）")
        sub.add_argument("--factor", help="单个因子名（eval 用）")
        sub.add_argument("--source", default="free", help="因子数据源/引擎")
        sub.add_argument("--universe", help="股票池（逗号分隔）")
        sub.add_argument("--start", default=DEF("start"))
        sub.add_argument("--end", default=DEF("end"))
        sub.set_defaults(handler=cmd_factor)

    _common(fs.add_parser("calc", help="计算因子面板"))
    _common(fs.add_parser("eval", help="单因子 IC 评估"))
    _common(fs.add_parser("eval-all", help="全量因子评估"))
    q = fs.add_parser("combine", help="因子合成打分")
    _common(q)
    q.add_argument("--method", default="equal", help="合成方法")
    q.add_argument("--save", help="保存 parquet 路径")
    _common(fs.add_parser("corr", help="因子相关性/冗余"))
    q = fs.add_parser("backtest", help="因子组合回测")
    _common(q)
    q.add_argument("--symbols", help="候选池（逗号分隔）")
    q.add_argument("--method", default="equal")
    q.add_argument("--n-top", dest="n_top", type=int, default=10)
    q.add_argument("--freq", default="M", help="调仓频率")
    q = fs.add_parser("research", help="因子研究全流程（ICIR 筛选+去冗余+合成）")
    _common(q)
    q.add_argument("--method", default="equal")
    q.add_argument("--min-icir", dest="min_icir", type=float, default=0.3)

    p = sp.add_parser("market", help=f"[{GROUP}] 策略市场检索/导入/校验")
    p.add_argument("market_action", choices=["search", "import", "validate"],
                   metavar="操作")
    p.add_argument("--keyword", help="检索关键词")
    p.add_argument("--path", dest="path", help="导入/校验的文件路径")
    p.set_defaults(handler=cmd_market)


def handler(args) -> int:
    """factor 模块统一分发（factor / market）。"""
    if getattr(args, "factor_action", None):
        return int(cmd_factor(args))
    return int(cmd_market(args))
