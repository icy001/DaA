# -*- coding: utf-8 -*-
"""实盘合规审计日志（live/audit_log.py）—— 12.11。

订单 / 撤单 / 成交 / 风控触发 / 程序启停 / 登录登出全部**永久留存**，
字段覆盖证监会程序化交易报备要求：时间 / 价格 / 数量 / 方向 / 账户 / IP / 策略ID。

* 按日期归档到 ``audit_logs/live_YYYYMMDD.jsonl``，追加写；
* 每条记录带前一条的哈希（哈希链），任何篡改都会在 ``verify_chain`` 暴露；
* 保留期 ``config.SECURITY['audit_log_retention_days']``（默认 2 年），
  该目录已被 ``.gitignore`` 屏蔽，不提交仓库；
* 可 ``export()`` 导出给券商/交易所检查。
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Callable, List, Optional

import config

__all__ = ["AuditLog", "EVENTS"]

EVENTS = ("order_submit", "order_cancel", "fill", "risk_trigger", "program_start",
          "program_stop", "login", "logout", "kill_switch", "reconcile",
          "mode_change", "error")


class AuditLog:
    def __init__(self, dir_path=None, account_id: str = "", strategy_id: str = "",
                 ip: str = "", now_fn: Callable[[], float] = None) -> None:
        raw = Path(dir_path or getattr(config, "AUDIT_DIR", "audit_logs"))
        self.dir = raw if raw.is_absolute() else Path(config.BASE_DIR) / raw
        self.dir.mkdir(parents=True, exist_ok=True)
        self.account_id = str(account_id or "")
        self.strategy_id = str(strategy_id or "")
        self.ip = str(ip or "")
        self.retention_days = int((getattr(config, "SECURITY", {}) or {}).get(
            "audit_log_retention_days", 365 * 2))
        self._now = now_fn or time.time
        self._prev_hash = self._tail_hash()

    # ==================== 写入 ====================
    def _file(self, day: str = None) -> Path:
        day = day or time.strftime("%Y%m%d", time.localtime(float(self._now())))
        return self.dir / f"live_{day}.jsonl"

    def _tail_hash(self) -> str:
        path = self._file()
        if not path.exists():
            return ""
        last = ""
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                last = line
        if not last:
            return ""
        try:
            return str(json.loads(last).get("hash", ""))
        except json.JSONDecodeError:
            return "CORRUPTED"

    def record(self, event: str, **fields) -> dict:
        """追加一条不可篡改记录（哈希链 + 完整账户标识）。"""
        payload = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(self._now()))),
            "event": str(event), "account": self.account_id, "ip": self.ip,
            "strategy_id": self.strategy_id,
            "mode": str(fields.pop("mode", "") or ""),
        }
        payload.update({str(k): v for k, v in fields.items()})
        digest = hashlib.sha256(
            (self._prev_hash + json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                          default=str)).encode("utf-8")).hexdigest()
        payload["prev_hash"] = self._prev_hash
        payload["hash"] = digest
        path = self._file()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        self._prev_hash = digest
        return dict(payload)

    # ==================== 导出 / 校验 ====================
    def export(self, start: str = None, end: str = None) -> List[dict]:
        """按日期（YYYYMMDD）区间导出，供券商/交易所检查。"""
        start = str(start or "00000000")
        end = str(end or "99999999")
        out: List[dict] = []
        for path in sorted(self.dir.glob("live_*.jsonl")):
            day = path.stem.split("_")[-1]
            if not (start <= day <= end):
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.append(json.loads(line))
        return out

    def verify_chain(self) -> bool:
        """逐条校验哈希链：任何字段被改都会失败（不可篡改）。"""
        prev = ""
        for path in sorted(self.dir.glob("live_*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                expect = hashlib.sha256(
                    (prev + json.dumps({k: v for k, v in rec.items()
                                        if k not in ("prev_hash", "hash")},
                                       ensure_ascii=False, sort_keys=True,
                                       default=str)).encode("utf-8")).hexdigest()
                if rec.get("prev_hash", "") != prev or rec.get("hash") != expect:
                    return False
                prev = rec["hash"]
        return True

    # ==================== 便捷事件 ====================
    def order(self, action: str, **fields) -> dict:
        return self.record(action, **fields)

    def cancel(self, **fields) -> dict:
        return self.record("order_cancel", **fields)

    def fill(self, **fields) -> dict:
        return self.record("fill", **fields)

    def risk(self, reason: str, **fields) -> dict:
        return self.record("risk_trigger", reason=str(reason), **fields)

    def start(self, **fields) -> dict:
        return self.record("program_start", **fields)

    def stop(self, **fields) -> dict:
        return self.record("program_stop", **fields)

    def login(self, **fields) -> dict:
        return self.record("login", **fields)

    def logout(self, **fields) -> dict:
        return self.record("logout", **fields)

    def kill_switch(self, reason: str, **fields) -> dict:
        return self.record("kill_switch", reason=str(reason), **fields)

    def prune(self) -> Optional[List[Path]]:
        """删除超过保留期（默认 2 年）的审计文件；返回被删列表。"""
        cutoff = time.localtime(float(self._now()) - self.retention_days * 86400)
        limit = time.strftime("%Y%m%d", cutoff)
        removed: List[Path] = []
        for path in self.dir.glob("live_*.jsonl"):
            if path.stem.split("_")[-1] < limit:
                path.unlink()
                removed.append(path)
        return removed or None
