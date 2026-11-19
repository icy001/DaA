# -*- coding: utf-8 -*-
"""急停（Kill Switch，live/kill_switch.py）——K6③。

急停状态必须**跨进程重启保留**：标志文件写在磁盘上，重启后仍处于停机态，
直到人工输入确认口令清除。原因很直接——崩溃重启是常态，若急停只在内存里，
重启即「自动复活」，等于没有急停。
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import config
from core.gov_compat import gov
from live.errors import KillSwitchActive

__all__ = ["KillSwitch", "PanicController", "kill_switch_config"]


def kill_switch_config() -> dict:
    return dict((gov("LIVE_SAFETY")).get("kill_switch") or {})


class KillSwitch:
    def __init__(self, flag_file=None, persist: bool = None,
                 clear_token: str = None) -> None:
        conf = kill_switch_config()
        raw = flag_file or conf.get("flag_file") or "live_trading/KILL_SWITCH"
        path = Path(raw)
        self.path = path if path.is_absolute() else Path(config.BASE_DIR) / path
        self.persist = bool(conf.get("persist", True) if persist is None else persist)
        self.clear_token = str(clear_token or conf.get("manual_clear_token")
                               or "MANUAL_CONFIRM")
        self._memory: Optional[dict] = None

    # ---------- 状态 ----------
    def is_active(self) -> bool:
        if self.persist:
            return self.path.exists()
        return self._memory is not None

    def state(self) -> Optional[dict]:
        if not self.is_active():
            return None
        if not self.persist:
            return dict(self._memory or {})
        try:
            return json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except (json.JSONDecodeError, OSError):
            return {"reason": "标志文件存在但不可解析（仍按停机处置）"}

    def trigger(self, reason: str = "manual") -> dict:
        payload = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "reason": str(reason)}
        if self.persist:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        else:
            self._memory = payload
        return payload

    def clear(self, token: str) -> bool:
        """人工确认后才允许解除；口令不符直接拒。"""
        if str(token) != self.clear_token:
            raise KillSwitchActive(
                f"急停解除被拒：需人工确认口令 {self.clear_token!r}，收到 {token!r}")
        if self.persist and self.path.exists():
            self.path.unlink()
        self._memory = None
        return True

    def assert_can_trade(self) -> None:
        """报单前唯一裁决：停机态一律拒单（平仓也不放行，先人工处理）。"""
        if self.is_active():
            st = self.state() or {}
            raise KillSwitchActive(
                f"急停激活中（{st.get('at', '?')} 触发：{st.get('reason', '')}），"
                "禁止任何新报单；需人工确认后解除")


class PanicController:
    """急停执行序列（12.15）：独立于策略进程，主线程卡死也能响应。

    动作顺序（全部记审计日志）：① 冻结策略（标志文件）→ ② 撤销所有未成交委托
    （失败重试 + 告警）→ ③ 按配置决定是否一键清仓（默认只撤单）→
    ④ 断开行情/交易连接 → ⑤ 写审计 → ⑥ 推送「已紧急停机」。

    三种触发方式共用同一实现：``run_live.py --panic``（独立进程写标志文件）、
    ``Ctrl+C``（优雅停机调用 :meth:`panic`）、标志文件/系统信号（:meth:`watch`）。
    """

    TERMINAL = ("rejected", "canceled", "cancelled", "filled")

    def __init__(self, kill_switch: KillSwitch = None, broker=None, notifier=None,
                 audit=None, liquidate_fn: Callable = None, logger=None,
                 now_fn: Callable[[], float] = None) -> None:
        self.kill_switch = kill_switch or KillSwitch()
        self.broker = broker
        self.notifier = notifier
        self.audit = audit
        self.liquidate_fn = liquidate_fn
        self.logger = logger
        self._now = now_fn or time.time
        self._handled_at: Optional[float] = None

    # ---------- 触发 ----------
    def panic(self, reason: str = "manual", liquidate: bool = None) -> dict:
        """人工/Ctrl+C/命令行触发：先落盘标志，再执行停机动作。"""
        self.kill_switch.trigger(reason)
        return self.execute(reason=reason, liquidate=liquidate)

    def execute(self, reason: str = "kill_switch", liquidate: bool = None,
                disconnect: bool = True) -> dict:
        out = {"reason": str(reason), "cancelled": [], "cancel_failed": [],
               "liquidated": [], "errors": [],
               "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        # ① 冻结：标志文件已存在，报单入口 assert_can_trade 一律拒绝
        # ② 撤销所有未成交委托（失败重试 3 次并告警）
        if self.broker is not None:
            try:
                orders = list(self.broker.get_orders() or [])
            except Exception as exc:  # noqa: BLE001 - 断线也算停机结果
                orders = []
                out["errors"].append(f"查询委托失败：{exc}")
            for order in orders:
                status = getattr(order, "status", None)
                oid = getattr(order, "client_order_id", None)
                if isinstance(order, dict):
                    status, oid = order.get("status"), order.get("client_order_id")
                if not oid or str(status) in self.TERMINAL:
                    continue
                if self._cancel_with_retry(str(oid)):
                    out["cancelled"].append(str(oid))
                else:
                    out["cancel_failed"].append(str(oid))
        # ③ 一键清仓（默认只撤单不清仓，清仓需显式开启）
        do_liquidate = (bool(kill_switch_config().get("panic_liquidate", False))
                        if liquidate is None else bool(liquidate))
        if do_liquidate and callable(self.liquidate_fn):
            try:
                out["liquidated"] = list(self.liquidate_fn() or [])
            except Exception as exc:  # noqa: BLE001
                out["errors"].append(f"清仓失败：{exc}")
        # ④ 断开连接
        if disconnect and self.broker is not None:
            try:
                self.broker.disconnect()
            except Exception as exc:  # noqa: BLE001
                out["errors"].append(f"断开连接失败：{exc}")
        # ⑤ 审计
        if self.audit is not None:
            try:
                self.audit.kill_switch(reason, **{k: out[k] for k in
                                                  ("cancelled", "cancel_failed",
                                                   "liquidated", "errors")})
            except Exception as exc:  # noqa: BLE001
                out["errors"].append(f"审计写入失败：{exc}")
        # ⑥ 告警（严重告警重复 3 次）
        if self.notifier is not None:
            try:
                self.notifier.on_kill_switch(
                    f"{reason}｜已撤 {len(out['cancelled'])} 单，"
                    f"失败 {len(out['cancel_failed'])} 单")
            except Exception as exc:  # noqa: BLE001
                out["errors"].append(f"告警推送失败：{exc}")
        self._handled_at = float(self._now())
        return out

    def _cancel_with_retry(self, client_order_id: str, retries: int = 3) -> bool:
        for _ in range(max(1, retries)):
            try:
                res = self.broker.cancel_order(client_order_id) or {}
                if isinstance(res, dict) and res.get("ok", True):
                    return True
            except Exception:  # noqa: BLE001 - 重试
                continue
        return False

    # ---------- 独立线程监听外部信号 ----------
    def watch(self, stop_event: threading.Event = None,
              interval: float = None) -> Optional[dict]:
        """阻塞循环：外部（SSH / --panic）写入标志文件后立即执行停机动作。

        运行在**独立线程**，即使主策略线程卡死/死循环也能响应。
        """
        stop_event = stop_event or threading.Event()
        interval = float(interval or kill_switch_config().get("check_interval_sec", 1.0))
        while not stop_event.is_set():
            if self.kill_switch.is_active() and self._handled_at is None:
                st = self.kill_switch.state() or {}
                return self.execute(reason=str(st.get("reason") or "external"))
            stop_event.wait(interval)
        return None

    def start_watcher(self, stop_event: threading.Event = None) -> threading.Thread:
        thread = threading.Thread(target=self.watch, args=(stop_event,),
                                  name="kill-switch-watcher", daemon=True)
        thread.start()
        return thread
