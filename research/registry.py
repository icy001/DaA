"""第 5 步 · 第 8 步：实验记录与对比（research/registry.py）

每次回测 / 优化落一条 JSON 记录，目的是「任何一次结论都能复现、能追溯」。

- 纯 JSON、不依赖数据库：一个实验一个文件
  `<时间戳>_<策略名>_<短id>.json`，并发写靠唯一 exp_id 避免覆盖；
- 原子写：先写 `.tmp` 再 `os.replace`，进程中断不会留下半截文件；
- `data_hash` = sha1(params + symbols + start + end)，用于「同参数同区间」复现校验；
- JSON 用 `ensure_ascii=False`，中文直接可读。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import config

__all__ = ["ExperimentRegistry", "data_hash"]

# 一次进程内只查一次 git 版本
_CODE_VERSION: Optional[str] = None


def _code_version() -> str:
    """当前代码版本；git 不可用时返回 "unknown"，绝不抛错。"""
    global _CODE_VERSION
    if _CODE_VERSION is not None:
        return _CODE_VERSION
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(config.BASE_DIR),
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            _CODE_VERSION = out.stdout.strip()
        else:
            _CODE_VERSION = "unknown"
    except Exception:
        _CODE_VERSION = "unknown"
    return _CODE_VERSION


# ==================== 序列化 / 哈希 ====================

def _json_default(obj):
    """numpy / 时间 / 集合等统一转成可序列化类型，保证哈希与落盘口径一致。"""
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(obj, key=str)
    if isinstance(obj, (pd.Timestamp,)):
        return obj.strftime("%Y-%m-%d")
    return str(obj)


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      default=_json_default, separators=(",", ":"))


def _norm_time(value) -> str:
    """日期统一成 YYYY-MM-DD（无法解析时保留原字符串）。"""
    if value is None or value == "":
        return ""
    try:
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return str(value)


def data_hash(params: Dict, symbols: List[str], start, end) -> str:
    """参数 + 标的 + 区间的指纹，用于复现校验。"""
    payload = {
        "params": params or {},
        "symbols": sorted(str(s) for s in (symbols or [])),
        "start": _norm_time(start),
        "end": _norm_time(end),
    }
    return hashlib.sha1(_canonical(payload).encode("utf-8")).hexdigest()


# ==================== 注册表 ====================

class ExperimentRegistry:
    """实验记录（纯 JSON，一个实验一个文件）。"""

    def __init__(self, root=None):
        self.root = Path(root) if root is not None else (
            config.BASE_DIR / "research_output" / "experiments")
        self.root.mkdir(parents=True, exist_ok=True)

    # ---------- 写 ----------

    def log(self, result: dict, strategy_name: str = None, tags: List[str] = None) -> str:
        """记录一次实验，返回 exp_id。result 为 run_backtest 返回 dict（或含 metrics 的 dict）。"""
        result = dict(result or {})
        strategy = result.get("strategy")
        meta = dict(getattr(strategy, "meta", {}) or {}) if strategy is not None else {}

        name = (strategy_name or result.get("strategy_name")
                or meta.get("name") or (type(strategy).__name__ if strategy is not None else "")
                or "unknown")
        version = (result.get("strategy_version") or meta.get("version") or "unknown")
        params = dict(result.get("params") or getattr(strategy, "params", {}) or {})
        symbols = [str(s) for s in (result.get("symbols")
                                    or getattr(strategy, "symbols", None)
                                    or params.get("symbols") or [])]

        nav = result.get("nav")
        if isinstance(nav, pd.Series) and len(nav):
            nav_start = pd.Timestamp(nav.index.min()).strftime("%Y-%m-%d")
            nav_end = pd.Timestamp(nav.index.max()).strftime("%Y-%m-%d")
        else:
            nav_start = nav_end = ""
        start = _norm_time(result.get("start") or params.get("start") or nav_start)
        end = _norm_time(result.get("end") or params.get("end") or nav_end)

        metrics = dict(result.get("metrics") or {})
        if not metrics:  # 兼容直接传指标字典
            metrics = {k: v for k, v in result.items()
                       if isinstance(v, (int, float, np.integer, np.floating))
                       and not isinstance(v, bool)}

        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        stamp = time.strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r"[^\w\-]+", "_", str(name)).strip("_") or "exp"
        exp_id = f"{stamp}_{safe_name}_{uuid.uuid4().hex[:6]}"

        record = {
            "exp_id": exp_id,
            "time": now,
            "strategy": str(name),
            "strategy_version": version,
            "params": params,
            "symbols": symbols,
            "start": start,
            "end": end,
            "metrics": metrics,
            "run_mode": str(result.get("run_mode") or "backtest"),
            "code_version": _code_version(),
            "data_hash": data_hash(params, symbols, start, end),
            "charts": list(result.get("charts") or []),
            "tags": list(tags or []),
        }
        self._write(record)
        return exp_id

    def _write(self, record: dict) -> Path:
        """原子写：先写 .tmp，再 rename，避免读到半截 JSON。"""
        path = self.root / f"{record['exp_id']}.json"
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2,
                                  default=_json_default), encoding="utf-8")
        os.replace(tmp, path)
        return path

    # ---------- 读 ----------

    def list(self, limit: int = 50) -> List[dict]:
        """按时间倒序列出最近的实验记录。"""
        records = []
        for path in self.root.glob("*.json"):
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        records.sort(key=lambda r: str(r.get("time", "")), reverse=True)
        return records[:int(limit)]

    def load(self, exp_id: str) -> Optional[dict]:
        """按 exp_id（或文件名片段）加载一条记录；不存在返回 None。"""
        if not exp_id:
            return None
        direct = self.root / f"{exp_id}.json"
        if direct.exists():
            try:
                return json.loads(direct.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
        for path in self.root.glob(f"*{exp_id}*.json"):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
        return None

    def compare(self, exp_ids: List[str]) -> pd.DataFrame:
        """横向对比：每行一个实验，列 = 元信息 + 全部绩效指标。"""
        rows, index = [], []
        for exp_id in (exp_ids or []):
            record = self.load(exp_id)
            if not record:
                continue
            row = {
                "strategy": record.get("strategy"),
                "strategy_version": record.get("strategy_version"),
                "start": record.get("start"),
                "end": record.get("end"),
                "params": json.dumps(record.get("params") or {}, ensure_ascii=False,
                                     default=_json_default),
                "run_mode": record.get("run_mode"),
                "code_version": record.get("code_version"),
            }
            row.update(record.get("metrics") or {})
            rows.append(row)
            index.append(record.get("exp_id", exp_id))
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, index=pd.Index(index, name="exp_id"))

    def find_reproducible(self, params: Dict, symbols: List[str],
                          start, end) -> List[dict]:
        """按 data_hash 查历史记录：同参数 + 同标的 + 同区间即为可复现实验。"""
        target = data_hash(params, symbols, start, end)
        hits = [r for r in self.list(limit=10_000) if r.get("data_hash") == target]
        hits.sort(key=lambda r: str(r.get("time", "")), reverse=True)
        return hits
