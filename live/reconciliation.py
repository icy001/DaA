# -*- coding: utf-8 -*-
"""对账前移（live/reconciliation.py）——K4。

12.10 把对账放在「收盘后第一件事」，但 12.6 的全部风控读的是**本地账本**：
本地漏记一笔成交，风控就在错误画面上判断，而且要等到次日才拦。
因此权威必须在券商侧（``authoritative="broker"``），本地只是可能过期的副本。

四处对账
========
1. **每次报单前**（``pre_order``）：不一致 → 立即停开新仓；
2. **盘中定时**（``interval_sec``，默认 60s）：由守护/主循环调用 ``tick()``；
3. **启动时**：``startup()``，禁止带着错误账本开盘；
4. **日终强校验**（``eod()``）：12.10 原要求保留。

不一致处置：``halt_new_orders`` + 告警，且**只有人工确认**能恢复
（``resume_requires="manual_confirm"``）——不是只写一份报告。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import config
from core.gov_compat import gov
from live.errors import ReconcileHaltError

__all__ = ["Reconciler", "reconcile_config"]


def reconcile_config() -> dict:
    return dict((gov("LIVE_SAFETY")).get("reconcile") or {})


class Reconciler:
    def __init__(self, account, broker, state_file=None, tolerance: float = None,
                 now_fn: Callable[[], float] = None) -> None:
        conf = reconcile_config()
        raw = state_file or conf.get("state_file") or "live_trading/reconcile_state.json"
        path = Path(raw)
        self.state_path = path if path.is_absolute() else Path(config.BASE_DIR) / path
        self.account = account
        self.broker = broker
        self.tolerance = float(conf.get("tolerance", 0.01)
                               if tolerance is None else tolerance)
        self._now = now_fn or time.time
        self._last_at = 0.0
        self._state: Optional[dict] = None
        self._load()

    # ---------- 状态持久化 ----------
    def _load(self) -> None:
        if self.state_path.exists():
            try:
                self._state = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._state = {"halted": True, "reason": "对账状态文件损坏，按停机处置"}

    def _save(self, state: Optional[dict]) -> None:
        self._state = state
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        if state is None:
            if self.state_path.exists():
                self.state_path.unlink()
            return
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                                   encoding="utf-8")

    # ---------- 比对 ----------
    def _local_positions(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for book in (getattr(self.account, "positions", {}) or {},
                     getattr(self.account, "short_positions", {}) or {}):
            for symbol, pos in book.items():
                volume = float(getattr(pos, "volume", 0.0) or 0.0)
                if abs(volume) > 1e-9:
                    out[str(symbol)] = out.get(str(symbol), 0.0) + volume
        return out

    def _remote_positions(self) -> Dict[str, float]:
        raw = self.broker.get_positions() or {}
        out = {}
        for symbol, pos in dict(raw).items():
            volume = float((pos or {}).get("volume", 0.0) or 0.0)
            if abs(volume) > 1e-9:
                out[str(symbol)] = volume
        return out

    def compare(self) -> dict:
        """权威在券商侧：差异清单逐项给出，不做任何「自动修正」。"""
        local_pos = self._local_positions()
        remote_pos = self._remote_positions()
        diffs: List[dict] = []
        for symbol in sorted(set(local_pos) | set(remote_pos)):
            lv, rv = local_pos.get(symbol, 0.0), remote_pos.get(symbol, 0.0)
            if abs(lv - rv) > self.tolerance:
                diffs.append({"kind": "position", "symbol": symbol,
                              "local": lv, "broker": rv})
        acct = self.broker.get_account() or {}
        local_cash = float(getattr(self.account, "cash", 0.0) or 0.0)
        remote_cash = float(acct.get("cash", local_cash) or 0.0)
        if abs(local_cash - remote_cash) > self.tolerance:
            diffs.append({"kind": "cash", "local": local_cash, "broker": remote_cash})
        return {"ok": not diffs, "diffs": diffs,
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "local_positions": local_pos, "broker_positions": remote_pos}

    # ---------- 对账入口 ----------
    def reconcile(self, reason: str = "periodic") -> dict:
        result = self.compare()
        self._last_at = float(self._now())
        result["reason"] = str(reason)
        if not result["ok"]:
            payload = {"halted": True, "at": result["at"], "reason": str(reason),
                       "diffs": result["diffs"]}
            self._save(payload)
            if self._logger():
                self._logger().error("对账不一致（%s），停止开新仓，等待人工确认：%s",
                                     reason, result["diffs"][:5])
        return result

    def _logger(self):
        return getattr(self.account, "logger", None)

    # ---------- 停机裁决 ----------
    def is_halted(self) -> bool:
        return bool((self._state or {}).get("halted"))

    def halt_state(self) -> Optional[dict]:
        return dict(self._state) if self._state else None

    def require_clean(self, before_order: bool = False) -> None:
        """报单前唯一裁决：停机态直接拒；before_order 时先做一次实时对账。"""
        if before_order and reconcile_config().get("pre_order", True):
            self.reconcile(reason="pre_order")
        if self.is_halted():
            st = self.halt_state() or {}
            raise ReconcileHaltError(
                f"对账不一致已停机（{st.get('at', '?')} · {st.get('reason', '')}）："
                f"{st.get('diffs', [])[:3]}——禁止开新仓，需人工确认后恢复")

    def manual_confirm(self, operator: str = "manual") -> bool:
        """人工确认恢复（resume_requires="manual_confirm"）。"""
        self._save(None)
        self._last_at = float(self._now())
        if self._logger():
            self._logger().warning("对账停机已由人工确认恢复（operator=%s）", operator)
        return True

    # ---------- 定时 / 启动 / 日终 ----------
    def tick(self) -> Optional[dict]:
        conf = reconcile_config()
        interval = float(conf.get("interval_sec", 60) or 60)
        if float(self._now()) - self._last_at < interval:
            return None
        return self.reconcile(reason="intraday")

    def startup(self) -> Optional[dict]:
        if not reconcile_config().get("startup", True):
            return None
        return self.reconcile(reason="startup")

    def eod(self) -> Optional[dict]:
        if not reconcile_config().get("eod", True):
            return None
        return self.reconcile(reason="eod")
