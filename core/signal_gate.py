"""引擎无关的信号闸门（core/signal_gate.py）

第 6 步开工前置（C1–C4）：闸门逻辑只允许有**一份实现**，放在这里；执行器（第 5 步的
`core/runner.py` 与第 6 步的 `core/backtester.py`）**只调用、不重写**。这样替换执行器时
闸门不会随旧引擎一起静默消失。

四道闸门（全部引擎无关）：

1. **bar_dict 预热标记**（`build_bar_dict` / `assert_bar_dict`）
   引擎构建 bar_dict 时必须为每个标的写入物化布尔字段 `warmup_ok`
   （`config.INDICATOR_WARMUP_GUARD["warmup_ok_column"]`）。缺列直接报错——
   禁止「引擎忘了喂 → 策略按默认 True 放行」这种静默放水。

2. **下单预热裁决**（`check_order`）
   开仓方向 `buy` / `short`（含调仓买入）在 `warmup_ok=False` 时拒单；
   平仓方向 `sell` / `cover`（含止损、强平、到期结算、回测结束强平）一律放行
   （「开严平宽」）。最终裁决同时收口在 `core/account.py::place_order`
   （与 stale 闸门同处），因此即使有人绕过策略层直接下单，也拦得住。

3. **信号帧 fillna 泄漏**（`check_signal_frame`）
   策略自拼指标帧必须过 `assert_signal_frame`：缺少 `warmup_ok` 列、掩码含 NaN、
   预热掩码为 False 的行出现非 NaN 指标值（被 fillna/ffill/bfill/rolling(min_periods=1)
   填过）→ 报错。实现复用 `core/indicators.py` 的纯函数（引擎无关）。

4. **回测长度门槛**（`min_backtest_bars` / `ensure_min_bars`）
   `max(60, strategy.required_bars())`，禁止硬编码 60：MACD 的 DEA 收敛约 70+ 根，
   固定 60 会让 60~70 根的标的通过长度检查后全段落在预热期 → 闸门拦掉每一笔 →
   回测静默零成交，容易被误判成「策略没用」。

另含 `align_frames`：多标的对齐/取交易日交集时，`data_asof_date` / `price_adjust` /
`warmup_ok` 三个物化列**逐标的保留**（按 symbol 分组），不得因 concat/reindex
退化成一列一个值或整列广播。
"""
from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional

import pandas as pd

import config
from core import indicators as ind

__all__ = [
    "MIN_BACKTEST_BARS",
    "OPEN_DIRECTIONS",
    "CLOSE_DIRECTIONS",
    "warmup_column",
    "warmup_flag",
    "advance_seen",
    "build_bar",
    "build_bar_dict",
    "assert_bar_dict",
    "assert_tick_bars",
    "tick_columns",
    "suppression_reasons",
    "classify_rejection",
    "record_decision",
    "decision_log",
    "clear_decisions",
    "check_plan_candidate",
    "bar_warmup_ok",
    "check_order",
    "check_signal_frame",
    "min_backtest_bars",
    "ensure_min_bars",
    "preserve_columns",
    "align_frames",
    "config_snapshot",
]

# 回测长度下界（spec：max(60, strategy.required_bars())，60 只作下界）
MIN_BACKTEST_BARS = 60

OPEN_DIRECTIONS = ("buy", "short")
CLOSE_DIRECTIONS = ("sell", "cover")


# ==================== config 读取 ====================

def config_snapshot() -> dict:
    """返回 GATE_CONFORMANCE 的浅拷贝（测试/报告用）。"""
    return dict(getattr(config, "GATE_CONFORMANCE", {}) or {})


def warmup_column() -> str:
    return str(config.INDICATOR_WARMUP_GUARD.get("warmup_ok_column", "warmup_ok"))


def preserve_columns() -> List[str]:
    return list(config_snapshot().get("preserve_columns_on_align") or [])


# ==================== 1. bar_dict 预热标记 ====================

def warmup_flag(seen_bars: int, warmup_bars: int) -> bool:
    """该标的已见 bar 数是否已过预热期（`>=` 与 indicators.warmup_ok_series 同口径）。"""
    return int(seen_bars) >= max(int(warmup_bars), 1)


def advance_seen(seen: Dict[str, int], symbols: Iterable[str]) -> Dict[str, int]:
    """已见 bar 计数 +1（就地修改并返回，引擎每根 bar 调用一次）。"""
    for symbol in symbols:
        seen[str(symbol)] = int(seen.get(str(symbol), 0)) + 1
    return seen


def build_bar(row: dict, seen_bars: int, warmup_bars: int,
              date=None, extra: dict = None) -> dict:
    """把一行行情组装成 bar（含物化 warmup_ok / date）。"""
    bar = {k: (None if _is_na(v) else v) for k, v in dict(row or {}).items()}
    bar[warmup_column()] = bool(warmup_flag(seen_bars, warmup_bars))
    if extra:
        bar.update(extra)
    if date is not None:
        bar["date"] = date
    return bar


def build_bar_dict(rows: Dict[str, dict], seen: Dict[str, int], warmup_bars: int,
                   date=None) -> Dict[str, dict]:
    """引擎唯一允许的 bar_dict 构建入口：逐标的写入 warmup_ok。"""
    return {
        str(symbol): build_bar(row, int(seen.get(str(symbol), 0)), warmup_bars, date)
        for symbol, row in dict(rows or {}).items()
    }


def assert_bar_dict(bars: Dict[str, dict]) -> None:
    """引擎喂给 on_bar 的 bar_dict 必须带 warmup_ok；缺列/NaN 直接报错。"""
    col = warmup_column()
    if not bars:
        return
    missing = [str(s) for s, b in bars.items() if not isinstance(b, dict) or col not in b]
    if missing:
        raise ValueError(
            f"bar_dict 缺少物化列 {col}（标的 {missing}）：执行器必须通过 "
            f"signal_gate.build_bar_dict() 构建 bar，禁止省略预热标记")
    bad = [str(s) for s, b in bars.items() if _is_na(b.get(col))]
    if bad:
        raise ValueError(
            f"bar_dict 的 {col} 列存在 NaN（标的 {bad}）：预热状态必须为 True/False")


def bar_warmup_ok(bar: dict) -> bool:
    """读取 bar 的预热标记（缺失即报错，绝不默认放行）。"""
    col = warmup_column()
    if not isinstance(bar, dict) or col not in bar:
        raise ValueError(f"bar 缺少物化列 {col}：禁止让策略/账户在未知预热状态下交易")
    value = bar.get(col)
    if _is_na(value):
        raise ValueError(f"bar 的 {col} 为 NaN：预热状态必须为 True/False")
    return bool(value)


# ==================== 1b. 盯盘 tick bar 三物化列 ====================

def tick_columns() -> List[str]:
    """盯盘 tick bar 必须携带的物化列（唯一事实源 SIGNAL_EGRESS_CONFORMANCE）。"""
    conf = getattr(config, "SIGNAL_EGRESS_CONFORMANCE", {}) or {}
    cols = conf.get("monitor_must_inject_columns") or [
        "warmup_ok", "data_asof_date", "price_adjust"]
    return [str(c) for c in cols]


def assert_tick_bars(bars: Dict[str, dict]) -> None:
    """`strategy.dispatch_tick` / `monitor` 共用的 tick bar 硬校验。

    在 `assert_bar_dict`（只认 warmup_ok）之上，额外要求 `data_asof_date` 与
    `price_adjust`：禁止「用过期或复权口径不明的行情推交易信号」。
    """
    assert_bar_dict(bars)
    missing, invalid = [], []
    for symbol, bar in dict(bars or {}).items():
        for col in tick_columns():
            if col not in bar:
                missing.append(f"{symbol}.{col}")
            elif _is_na(bar.get(col)):
                invalid.append(f"{symbol}.{col}")
    if missing:
        raise ValueError(
            f"tick bar 缺少物化列 {missing}（要求 {tick_columns()}）：必须用 "
            f"signal_gate.build_bar() 注入后再喂 on_tick，禁止把 data_fetcher 裸行情直接喂")
    if invalid:
        raise ValueError(
            f"tick bar 的物化列为 NaN {invalid}（要求 {tick_columns()}）："
            f"预热状态/数据截至日期/复权口径必须明确")


# ==================== 1c. 裁决日志 / 第三出口 report_plan ====================

_DECISION_LOG: List[dict] = []

_DEFAULT_SUPPRESSION_REASONS = ["warmup", "stale", "off_session",
                                "limit_up_down", "volume_limit", "risk_block"]

_REASON_RULES = (
    ("warmup", ("预热", "warmup")),
    ("stale", ("时效", "停更", "不新鲜", "stale", "过期")),
    ("off_session", ("非交易时段", "休市", "session")),
    ("limit_up_down", ("涨停", "跌停", "涨跌停", "limit_up", "limit_down")),
    ("volume_limit", ("成交量", "量限", "流动性", "volume", "成交上限")),
    ("risk_block", ("风控", "保证金", "仓位上限", "risk", "集中度", "熔断")),
)


def suppression_reasons() -> List[str]:
    """报告必须披露的拦截原因（唯一事实源 config.REPORT_CONFORMANCE）。"""
    conf = getattr(config, "REPORT_CONFORMANCE", {}) or {}
    return [str(r) for r in (conf.get("suppression_reasons")
                             or _DEFAULT_SUPPRESSION_REASONS)]


def classify_rejection(reason) -> str:
    """把拒单文案归一到固定拦截原因，供报告逐项计数。"""
    text = str(reason or "")
    for code, keys in _REASON_RULES:
        if any(k in text for k in keys):
            return code
    return "other"


def record_decision(symbol, direction, allowed: bool, reason: str = "",
                    reason_code: str = None, source: str = "place_order",
                    reject_id: str = None, **meta) -> dict:
    """登记一次信号裁决（放行/拦截），报告唯一读取来源。

    引擎（account._reject / strategy._order / monitor_push）只调用本函数，
    禁止各自维护一份拦截计数——否则报告与引擎不同源。
    """
    from datetime import datetime
    rec = {
        "symbol": str(symbol), "direction": str(direction).lower(),
        "allowed": bool(allowed),
        "reason_code": str(reason_code if reason_code is not None
                           else ("" if allowed else classify_rejection(reason))),
        "reason": str(reason or ""), "source": str(source),
        "reject_id": reject_id,
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    rec.update(meta)
    _DECISION_LOG.append(rec)
    return rec


def decision_log(clear: bool = False) -> List[dict]:
    """读取裁决日志快照；clear=True 时读完清空（测试隔离用）。"""
    items = [dict(r) for r in _DECISION_LOG]
    if clear:
        _DECISION_LOG.clear()
    return items


def clear_decisions() -> None:
    """清空裁决日志（测试幂等用）。"""
    _DECISION_LOG.clear()


def check_plan_candidate(bar: dict, fresh_ok: bool = True,
                         in_session: bool = True,
                         symbol: str = "") -> Optional[dict]:
    """「明日候选」第三出口（report_plan）的唯一裁决。

    预热期 / 停更 / 非交易时段一律不得进入候选清单；三物化列缺失同样拒绝。
    放行返回 None，拦截返回带 ``stage`` 的拒单记录。
    """
    try:
        assert_tick_bars({symbol or "candidate": bar})
    except ValueError as exc:
        return {"status": "rejected", "stage": "stale",
                "reason": f"三物化列不完整，数据存疑：{exc}"}
    if not in_session:
        return {"status": "rejected", "stage": "off_session",
                "reason": "非交易时段，不得进入明日候选"}
    if not bar_warmup_ok(bar):
        return {"status": "rejected", "stage": "warmup",
                "reason": "指标仍处预热期（warmup_ok=False），不得进入明日候选"}
    if not fresh_ok:
        return {"status": "rejected", "stage": "stale",
                "reason": "数据停更/超限，不得进入明日候选"}
    return None


# ==================== 2. 下单预热裁决 ====================

def check_order(direction: str, warmup_ok, symbol: str = "",
                logger: logging.Logger = None) -> Optional[dict]:
    """开仓方向预热期拒单；平仓方向放行。返回拒单记录，放行返回 None。

    这是策略层与账户层共用的**唯一**裁决函数：`core/strategy.py::_order` 调它做前置拦截，
    `core/account.py::place_order` 的 `warmup_ok` 参数做最终收口（引擎替换后仍生效）。
    """
    direction = str(direction).lower()
    if direction not in OPEN_DIRECTIONS:
        return None                      # sell / cover：强平、止损、到期结算一律放行
    if bool(warmup_ok):
        return None
    reason = (f"指标仍处于预热期（{warmup_column()}=False），禁止开仓；"
              f"平仓/减仓不受限")
    if logger is not None:
        logger.warning("策略拒单 %s %s：%s", symbol, direction, reason)
    return {
        "status": "rejected", "symbol": str(symbol), "direction": direction,
        "reason": reason, "stage": "warmup",
    }


# ==================== 3. 信号帧 fillna 泄漏 ====================

def check_signal_frame(df, indicator_columns=None, run_mode: str = None,
                       require_last_bar_ready: bool = None) -> bool:
    """信号入口硬校验（单一实现，委托 indicators 的纯函数）。"""
    mode = str(run_mode or config.RUN_MODE).lower()
    if require_last_bar_ready is None:
        require_last_bar_ready = mode in ("paper", "live", "live_sim")
    return ind.assert_signal_frame(
        df, indicator_columns=indicator_columns,
        require_last_bar_ready=bool(require_last_bar_ready),
        run_mode=run_mode)


# ==================== 4. 回测长度门槛 ====================

def min_backtest_bars(strategy=None, warmup_bars: int = None) -> int:
    """长度门槛 = max(60, strategy.required_bars())，禁止硬编码 60。"""
    need = 0
    if strategy is not None:
        if hasattr(strategy, "required_bars"):
            need = int(strategy.required_bars())
        else:
            need = int(getattr(strategy, "warmup_bars", 0) or 0)
    elif warmup_bars is not None:
        need = int(warmup_bars)
    return int(max(MIN_BACKTEST_BARS, need))


def ensure_min_bars(n_bars: int, strategy=None, warmup_bars: int = None,
                    label: str = "回测") -> int:
    """数据长度不足则报错；返回实际门槛（供日志/结果记录）。"""
    need = min_backtest_bars(strategy=strategy, warmup_bars=warmup_bars)
    if int(n_bars) < need:
        raise ValueError(
            f"{label}数据仅 {int(n_bars)} 根 < 长度门槛 {need} 根"
            f"（max({MIN_BACKTEST_BARS}, required_bars)，config.GATE_CONFORMANCE）："
            f"继续跑会全段落在预热期、闸门拦掉每一笔而静默零成交")
    return need


# ==================== C4 多标的对齐 ====================

def align_frames(frames: Dict[str, pd.DataFrame], how: str = "intersection",
                 preserve: Iterable[str] = None) -> Dict[str, pd.DataFrame]:
    """对齐多标的日期索引，返回**逐标的分组**的帧（不 concat 成一张平表）。

    - `how="intersection"`：取交易日交集（上市晚的标的自然截断）；
    - `how="union"`：取并集；
    - `data_asof_date` / `price_adjust` / `warmup_ok` 三个物化列按 symbol 逐帧保留，
      不会被对齐退化成「一列一个值」或整列广播。
    """
    cols = list(preserve if preserve is not None else preserve_columns())
    cleaned: Dict[str, pd.DataFrame] = {}
    for symbol, frame in dict(frames or {}).items():
        if frame is None or len(frame) == 0:
            continue
        cleaned[str(symbol)] = frame
    if not cleaned:
        return {}

    index = None
    for frame in cleaned.values():
        frame.index = pd.to_datetime(frame.index)
        index = frame.index if index is None else (
            index.intersection(frame.index) if how == "intersection"
            else index.union(frame.index))
    index = pd.DatetimeIndex(sorted(index))

    aligned: Dict[str, pd.DataFrame] = {}
    for symbol, frame in cleaned.items():
        out = frame.reindex(index)
        # reindex 会丢 attrs，但物化列本身就是普通列：显式按原帧逐标的回填，绝不广播
        for col in cols:
            if col in frame.columns:
                out[col] = frame[col].reindex(index)
        aligned[symbol] = out
    return aligned


def _is_na(value) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False
