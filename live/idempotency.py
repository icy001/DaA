# -*- coding: utf-8 -*-
"""报单幂等（live/idempotency.py）——K3。

事故链：报单超时（券商其实已受理）→ 判失败 → 重连重发 → 成交两笔 → 仓位翻倍；
崩溃重启 → 从策略状态重算信号 → 又报一次 → 再翻倍。

三道防线
========
1. 每笔报单带唯一 ``client_order_id``（格式见 ``LIVE_SAFETY['idempotency']['format']``），
   并**落盘**到 ``persist_path``，跨进程重启保留；
2. 同键在 ``dedup_window_sec`` 内重复提交 → 直接拒绝（``on_duplicate="reject"``）；
3. 状态未知（超时/断连）**禁止盲目重发**：先 ``query_order`` 确认券商未受理，
   才允许重发（``on_unknown_state="query_broker_first"``，判定在 live_trader）。

注意与 12.14.6「废单不自动重试」的区别：那条管**被拒**单，本模块管**状态未知**单。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable, Dict, Optional

import config
from core.gov_compat import gov
from live.errors import IdempotencyError

__all__ = ["IdempotencyStore", "idempotency_config", "persist_path"]


def idempotency_config() -> dict:
    return dict((gov("LIVE_SAFETY")).get("idempotency") or {})


def persist_path() -> Path:
    raw = str(idempotency_config().get("persist_path") or "live_trading/order_ids.json")
    path = Path(raw)
    return path if path.is_absolute() else Path(config.BASE_DIR) / path


class IdempotencyStore:
    """client_order_id 生成 + 窗口去重 + 落盘（JSON，原子替换写入）。"""

    def __init__(self, path=None, dedup_window_sec: float = None,
                 fmt: str = None, now_fn: Callable[[], float] = None) -> None:
        conf = idempotency_config()
        self.path = Path(path) if path is not None else persist_path()
        self.window = float(conf.get("dedup_window_sec", 600)
                            if dedup_window_sec is None else dedup_window_sec)
        self.fmt = str(fmt or conf.get("format")
                       or "{strategy}-{symbol}-{direction}-{bar_date}-{seq}")
        self._now = now_fn or time.time
        self._records: Dict[str, dict] = {}
        self._load()

    # ---------- 持久化 ----------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except (json.JSONDecodeError, OSError):
            raise IdempotencyError(
                f"幂等文件损坏或不可读：{self.path}——拒绝启动（禁止当作空账本重发）")
        self._records = {str(k): dict(v or {}) for k, v in dict(data).items()}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._records, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(self.path)

    # ---------- 键生成 ----------
    def new_client_order_id(self, strategy: str, symbol: str, direction: str,
                            bar_date, seq: Optional[int] = None) -> str:
        """生成唯一键；seq 缺省取「同键已有条数+1」，保证重启后不重复。"""
        raw = self.fmt.format(strategy=strategy or "s", symbol=symbol,
                              direction=direction,
                              bar_date=str(bar_date)[:10].replace("-", ""),
                              seq="" if seq is None else seq)
        if seq is None:
            base = re.sub(r"-+$", "", raw)
            used = sum(1 for k in self._records if k.startswith(base))
            raw = self.fmt.format(strategy=strategy or "s", symbol=symbol,
                                  direction=direction,
                                  bar_date=str(bar_date)[:10].replace("-", ""),
                                  seq=used + 1)
        return re.sub(r"[^0-9A-Za-z_.:-]", "-", raw)

    # ---------- 去重 ----------
    def register(self, client_order_id: str) -> dict:
        """登记新单；窗口内同键重复 → 抛 IdempotencyError（on_duplicate=reject）。"""
        key = str(client_order_id)
        now = float(self._now())
        prev = self._records.get(key)
        if prev is not None and now - float(prev.get("at", 0)) <= self.window:
            raise IdempotencyError(
                f"重复报单被拒：client_order_id={key} 在 {self.window:.0f}s 窗口内已提交"
                f"（状态 {prev.get('status')}）——自动重连/崩溃重启不得重复下单")
        self._records[key] = {"at": now, "status": "submitted", "broker_order_id": ""}
        self._save()
        return dict(self._records[key])

    def mark(self, client_order_id: str, status: str,
             broker_order_id: str = "") -> None:
        key = str(client_order_id)
        rec = self._records.setdefault(key, {"at": float(self._now())})
        rec["status"] = str(status)
        if broker_order_id:
            rec["broker_order_id"] = str(broker_order_id)
        self._save()

    def get(self, client_order_id: str) -> Optional[dict]:
        rec = self._records.get(str(client_order_id))
        return dict(rec) if rec else None

    def has(self, client_order_id: str) -> bool:
        return str(client_order_id) in self._records
