# -*- coding: utf-8 -*-
"""实盘安全异常（live/errors.py）。"""
from __future__ import annotations

__all__ = ["LiveSafetyError", "IdempotencyError", "ReconcileHaltError",
           "KillSwitchActive", "ModeGuardError", "SilentFallbackError",
           "DerivativeLiveForbidden", "FirstOrderLimitError", "OrderPortError"]


class LiveSafetyError(RuntimeError):
    """实盘安全闸门拒绝执行（fail-closed，绝不静默放行）。"""

    stage = "safety"

    def __init__(self, message: str, stage: str = None) -> None:
        super().__init__(message)
        self.stage = str(stage or self.stage)


class IdempotencyError(LiveSafetyError):
    stage = "idempotency"


class ReconcileHaltError(LiveSafetyError):
    stage = "reconcile"


class KillSwitchActive(LiveSafetyError):
    stage = "kill_switch"


class ModeGuardError(LiveSafetyError):
    stage = "mode"


class SilentFallbackError(ModeGuardError):
    """实盘连不上券商时禁止静默退回仿真/回测（K6）。"""
    stage = "silent_fallback"


class DerivativeLiveForbidden(LiveSafetyError):
    stage = "derivatives_forbidden"


class FirstOrderLimitError(LiveSafetyError):
    stage = "first_order_limit"


class OrderPortError(LiveSafetyError):
    stage = "order_port"
