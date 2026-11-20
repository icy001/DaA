# -*- coding: utf-8 -*-
"""cli_commands 公共工具（参数解析 / 策略 yaml / 指标打印 / --data 注入）。"""
from __future__ import annotations

import config

__all__ = ["_coerce", "parse_params", "load_strategy_config", "_resolve_run_args",
           "print_metrics", "_local_fetcher_from_args", "_month_span"]

def _coerce(text: str):
    low = str(text).strip().lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(text)
    except (TypeError, ValueError):
        pass
    try:
        return float(text)
    except (TypeError, ValueError):
        return str(text).strip()


def parse_params(text: str = None) -> dict:
    """`--params short=8,long=30` → {"short": 8, "long": 30}。"""
    if not text:
        return {}
    out = {}
    for item in str(text).split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"参数格式应为 key=value，收到 {item!r}")
        key, value = item.split("=", 1)
        out[key.strip()] = _coerce(value)
    return out


def load_strategy_config(name: str) -> dict:
    """读取 configs/strategies/base.yaml + <name>.yaml（后者覆盖前者）。"""
    import yaml

    root = config.BASE_DIR / "configs" / "strategies"
    merged = {}
    for path in (root / "base.yaml", root / f"{name}.yaml"):
        if not path.exists():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path} 必须是 YAML 映射")
        params = dict(data.pop("params", {}) or {})
        merged.update(data)
        merged.setdefault("params", {})
        merged["params"].update(params)
    return merged


def _resolve_run_args(args) -> tuple:
    """合并 yaml 配置与命令行参数，返回 (params, symbols, start, end)。"""
    cfg = load_strategy_config(args.strategy)
    params = dict(cfg.get("params") or {})
    params.update(parse_params(getattr(args, "params", None)))
    symbols = ([s.strip() for s in args.symbols.split(",") if s.strip()]
               if getattr(args, "symbols", None) else list(cfg.get("symbols") or []))
    start = getattr(args, "start", None) or cfg.get("start") or config.DEFAULT_START
    end = getattr(args, "end", None) or cfg.get("end") or config.DEFAULT_END
    params.setdefault("symbols", symbols)
    params.setdefault("start", start)
    params.setdefault("end", end)
    return params, symbols, start, end


def print_metrics(metrics: dict) -> None:
    def _f(key, fmt):
        v = metrics.get(key)
        try:
            return format(float(v), fmt)
        except (TypeError, ValueError):
            return "—"   # 样本不足等场景指标可为 None，展示占位不崩
    print("\n绩效：")
    print(f"  总收益     {_f('total_return', '+.2%')}")
    print(f"  年化收益   {_f('annual_return', '+.2%')}")
    print(f"  夏普       {_f('sharpe', '.3f')}")
    print(f"  最大回撤   {_f('max_drawdown', '.2%')}")
    print(f"  胜率（平仓口径） {_f('win_rate', '.2%')}")
    print(f"  成交笔数   {metrics.get('trade_count', 0)}")


def _local_fetcher_from_args(args, symbols):
    """--data 本地数据导入：必须走数据层出口 data/data_import，缺列即拒。"""
    data = getattr(args, "data", None)
    if not data:
        return None
    from data.data_import import LocalDataImportError, import_local_fetcher
    try:
        fetcher = import_local_fetcher(data, symbols=symbols,
                                       adjust=getattr(args, "adjust", None)
                                       or DEF("adjust"))
    except LocalDataImportError as exc:
        print(f"错误（--data 导入被数据层拒绝）：{exc}")
        raise SystemExit(2)
    print(f"--data 本地导入 {len(fetcher.frames)} 个标的（数据层出口，"
          "三物化列已校验）")
    return fetcher


def _month_span(start, end) -> int:
    """起止日期跨度（月数，至少 1）。"""
    import pandas as pd

    begin = pd.Timestamp(str(start or config.DEFAULT_START))
    stop = pd.Timestamp(str(end) if str(end or "").strip()
                        else pd.Timestamp.today().strftime("%Y-%m-%d"))
    return max(1, (stop.year - begin.year) * 12 + stop.month - begin.month + 1)


