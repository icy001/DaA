# -*- coding: utf-8 -*-
"""模式守卫（live/mode_guard.py）——K6。

与 12.5「三模式一键切换、上层无感」相反，这里明确禁止两件事：

1. **静默回退**：请求 live 但券商连不上时必须报错停机，
   不得自动退回仿真/回测（``forbid_silent_mode_fallback``）；
2. **带仓切模式**：切换模式（含降级）前必须无持仓、无在途单
   （``mode_change_requires_flat``）——有仓时切回 backtest 等于放弃实盘风控。

模式必须显式标注：每笔报单、每条回报都带 ``mode`` 字段（``mode_label_required``）。
"""
from __future__ import annotations

from typing import Dict, Iterable

import config
from core.gov_compat import gov
from live.errors import ModeGuardError, SilentFallbackError

__all__ = ["resolve_mode", "assert_mode_change_allowed", "mode_label",
           "assert_mode_labeled"]

_MODES = ("backtest", "paper", "live", "live_sim")


def resolve_mode(requested: str, broker_connected: bool = True,
                 broker_live_ready: bool = True) -> str:
    """解析实际运行模式；live 不可用禁止静默降级。"""
    mode = str(requested or "").lower()
    if mode not in _MODES:
        raise ModeGuardError(f"未知运行模式 {requested!r}，只允许 {list(_MODES)}")
    if mode == "live" and not (broker_connected and broker_live_ready):
        if (gov("LIVE_SAFETY")).get(
                "forbid_silent_mode_fallback", True):
            raise SilentFallbackError(
                "实盘模式启动失败：券商未连接或实盘通道未就绪，"
                "禁止静默退回仿真/回测——请修复连接后重试（fail-closed 停机）")
    return mode


def assert_mode_change_allowed(target: str, positions: Dict = None,
                               open_orders: Iterable = None,
                               current: str = None) -> None:
    """切模式（含降级）前必须无持仓、无在途单。"""
    conf = gov("LIVE_SAFETY")
    if not conf.get("mode_change_requires_flat", True):
        return

    def _volume(pos) -> float:
        raw = pos.get("volume", 0.0) if isinstance(pos, dict) else getattr(pos, "volume", 0.0)
        return abs(float(raw or 0.0))

    held = [str(s) for s, p in dict(positions or {}).items() if _volume(p) > 1e-9]

    def _oid(order) -> str:
        if isinstance(order, dict):
            return str(order.get("client_order_id") or order.get("order_id") or "")
        return str(getattr(order, "client_order_id", "") or order)

    pending = [oid for oid in (_oid(o) for o in (open_orders or [])) if oid]
    if held or pending:
        raise ModeGuardError(
            f"禁止从 {current or config.RUN_MODE} 切到 {target}："
            f"仍有持仓 {held[:5]} / 在途单 {pending[:5]}——先清仓并撤销未成交单")


def mode_label(mode: str = None) -> str:
    """统一模式标注（报单/回报/报告必须带）。"""
    return f"[{str(mode or getattr(config, 'RUN_MODE', 'backtest')).upper()}]"


def assert_mode_labeled(payload: dict) -> dict:
    payload = dict(payload or {})
    if not str(payload.get("mode") or "").strip():
        raise ModeGuardError("实盘报单/回报缺少 mode 标注（mode_label_required）")
    return payload
