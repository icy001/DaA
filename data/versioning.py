# -*- coding: utf-8 -*-
"""缓存口径标记（第 13 步 · 13.0 回补）

教训：一次迁移「中途崩溃 = 半迁移」，而 raw 与 qfq 残留【同名、同格式、看不出区别】
→ 读取器只能猜 → 复权两次或完全不复权 = 静默错价。

本模块给每个缓存文件写入 ``price_basis`` 标记（parquet 元数据 + ``.basis.json`` 边车），
并在读取时与「文件名声明的口径」逐一对拍：

- 标记缺失 → ``on_missing_tag``（默认 raise），旧缓存禁止被当成任意口径读取；
- 标记未知 → ``on_unknown_basis``（默认 raise）；
- 标记与请求口径不一致 → 直接报错（半迁移留下的错位文件）；
- 同一 (market, symbol, period) 存在多个口径且调用方没显式指明 → 拒绝替调用方猜。

``stamp_cache_root()`` 用于把历史缓存一次性补标记（幂等、保留 mtime，避免改变过期判定）。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

import config

__all__ = [
    "PriceBasisError",
    "MissingPriceBasisError",
    "PriceBasisMismatchError",
    "AmbiguousPriceBasisError",
    "normalize_basis",
    "infer_basis_from_path",
    "read_stored_basis",
    "write_with_basis",
    "read_sidecar_attrs",
    "stamp_file",
    "verify_basis",
    "find_cache_variants",
    "resolve_unique_cache",
    "stamp_cache_root",
]

# config.DATA_VERSIONING['version_tag_field'] 允许的取值 + 因子表专用标签
KNOWN_BASES = {"raw", "qfq", "hfq", "nav", "factor"}
# 文件名里的口径写法 → 统一标签（'' / none / bfq 都是不复权）
_BASIS_ALIASES = {"": "raw", "none": "raw", "raw": "raw", "bfq": "raw", "no": "raw",
                  "qfq": "qfq", "hfq": "hfq", "nav": "nav",
                  "factor": "factor", "factors": "factor"}
# 缓存文件名里的周期段（_daily_ / _5min_ ...）
_PERIOD_TOKENS = ("daily", "1min", "5min", "15min", "30min", "60min")
_BASIS_KEY = "price_basis"

# 随缓存落盘的数据本体标注白名单：只存「关于这份数据本身」的事实
# （来源/单位/质量旗标），不存每次调用重算的时效标记（stale/last_bar/asof 等）。
# CSV/parquet 往返会丢 DataFrame.attrs，不在边车持久化则缓存命中后
# source/volume_unit/amount_missing 等标注全部蒸发（核实7 曾因此失败）。
_PERSIST_ATTR_KEYS = frozenset({
    "source", "sources", "source_fallback", "raw_source", "local_fallback_cache",
    "adjust", "adjust_flag", "adjust_note", "adjust_fallback", "adjust_by_symbol",
    "volume_unit", "source_volume_unit", "unit_uncertain",
    "unit_ratio", "unit_ratio_note", "unit_evidence",
    "amount_missing", "amount_note", "amount_estimated",
    "minute_history_capped", "minute_available_from", "available_from",
    "snapshot_only", "backfill_cap_bars",
    "gap_dates", "gap_count", "daily_gap_dates", "daily_gap_count",
    "today_missing_declared",
    "minute_factor_available", "minute_factor_source",
    "minute_factor_error", "minute_factor_rows",
    "dominant_contract", "dominant_roll",
    "lot_size", "stamp_duty_exempt",
})


def _jsonable_attrs(attrs: dict) -> dict:
    """过滤出白名单内且 JSON 可序列化的标注；不可序列化的降级为 str。"""
    out = {}
    for key in _PERSIST_ATTR_KEYS:
        if key not in attrs:
            continue
        value = attrs[key]
        try:
            json.dumps(value)
            out[key] = value
        except (TypeError, ValueError):
            out[key] = str(value)
    return out


class PriceBasisError(ValueError):
    """复权口径不可信：fail-closed，禁止继续读取。"""


class MissingPriceBasisError(PriceBasisError):
    """缓存缺少口径标记（旧缓存 / 半迁移残留）。"""


class PriceBasisMismatchError(PriceBasisError):
    """缓存内标记与文件名声明/调用方请求的口径不一致。"""


class AmbiguousPriceBasisError(PriceBasisError):
    """同一序列存在多个口径文件而调用方未显式指定。"""


def _conf() -> dict:
    return dict(config.DATA_VERSIONING or {})


def normalize_basis(basis) -> Optional[str]:
    """把 ''/none/bfq/raw 等写法归一为 raw/qfq/hfq/nav/factor；未知返回 None。"""
    if basis is None:
        return None
    return _BASIS_ALIASES.get(str(basis).strip().lower())


def _sidecar(path: Path) -> Path:
    return path.with_suffix(".basis.json")


def infer_basis_from_path(path: Path) -> Optional[str]:
    """从缓存路径推断口径：raw/、adj_factors/、minute/ 目录 + 文件名周期段后缀。"""
    path = Path(path)
    parent = path.parent.name
    if parent == "raw":
        return "raw"
    if parent in ("adj_factors", "factors"):
        return "factor"
    if parent == "minute":
        return "raw"                     # 分钟增量库存原始价，复权在出口现算
    stem = path.stem
    for token in _PERIOD_TOKENS:
        marker = f"_{token}_"
        if marker in stem:
            return normalize_basis(stem.split(marker, 1)[1])
    return None


def read_stored_basis(path: Path) -> Optional[str]:
    """读取缓存内的口径标记：parquet 元数据优先，CSV 走 ``.basis.json`` 边车。"""
    path = Path(path)
    values = []
    if path.suffix == ".parquet" and path.exists():
        try:
            import pyarrow.parquet as pq
            meta = pq.read_schema(path).metadata or {}
            raw = meta.get(_BASIS_KEY.encode()) or meta.get(_BASIS_KEY)
            if raw:
                values.append(raw.decode() if isinstance(raw, bytes) else str(raw))
        except Exception:  # noqa: BLE001 - 元数据不可读按「无标记」处理
            pass
    sidecar = _sidecar(path)
    if sidecar.exists():
        try:
            values.append(str(json.loads(sidecar.read_text(encoding="utf-8"))[_BASIS_KEY]))
        except Exception:  # noqa: BLE001
            pass
    if not values:
        return None
    # 元数据与边车必须一致，否则视为损坏
    normalized = {normalize_basis(v) or str(v).lower() for v in values}
    if len(normalized) > 1:
        raise PriceBasisMismatchError(
            f"{path.name} 的口径标记自相矛盾：parquet={values[0]}，边车={values[-1]}")
    return normalized.pop()


def _write_parquet_with_basis(df: pd.DataFrame, file: Path, basis: str) -> bool:
    """写 parquet 并把 price_basis 写入 schema 元数据；无 pyarrow 返回 False。"""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except Exception:  # noqa: BLE001
        return False
    table = pa.Table.from_pandas(df)
    meta = dict(table.schema.metadata or {})
    meta[_BASIS_KEY.encode()] = basis.encode()
    meta[b"schema_version"] = str(_conf().get("schema_version", 1)).encode()
    table = table.replace_schema_metadata(meta)
    tmp = file.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp)
    os.replace(tmp, file)
    return True


def _write_sidecar(path: Path, basis: str, attrs: Optional[dict] = None) -> None:
    payload = {_BASIS_KEY: basis,
               "schema_version": _conf().get("schema_version", 1),
               "file": path.name}
    if attrs:
        payload["attrs"] = _jsonable_attrs(attrs)
    sidecar = _sidecar(path)
    tmp = sidecar.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, sidecar)


def read_sidecar_attrs(path: Path) -> dict:
    """读取边车里持久化的数据本体标注（source/单位/质量旗标）；无则返回空 dict。"""
    sidecar = _sidecar(Path(path))
    if not sidecar.exists():
        return {}
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        attrs = data.get("attrs")
        return dict(attrs) if isinstance(attrs, dict) else {}
    except Exception:  # noqa: BLE001 - 边车损坏按「无标注」处理，不阻断读数
        return {}


def write_with_basis(df: pd.DataFrame, path: Path, basis: str = None,
                     attrs: Optional[dict] = None) -> None:
    """带口径标记落盘（CSV + parquet + 边车），parquet 元数据是主标记。

    attrs 缺省取 ``df.attrs``：数据本体标注（来源/单位/质量旗标）随边车持久化，
    缓存命中后由 ``read_sidecar_attrs`` 恢复，避免 CSV/parquet 往返丢标注。
    """
    path = Path(path)
    basis = normalize_basis(basis) or infer_basis_from_path(path)
    if basis is None:
        raise PriceBasisError(
            f"无法为 {path.name} 推断复权口径；写入缓存必须显式传 basis（raw/qfq/hfq/nav）")
    out = df.copy()
    out.index.name = out.index.name or "date"
    _write_sidecar(path, basis, attrs=df.attrs if attrs is None else attrs)
    out.to_csv(path, encoding="utf-8")
    parquet = path.with_suffix(".parquet")
    if not _write_parquet_with_basis(out, parquet, basis):
        # pyarrow 缺失时至少保证 CSV + 边车可读；不能静默退回无标记
        out.to_parquet(parquet)
        _write_sidecar(parquet, basis, attrs=df.attrs if attrs is None else attrs)


def stamp_file(path: Path, basis: str = None) -> Optional[str]:
    """给已存在的缓存补标记（幂等，保留 mtime）；返回最终口径，无法推断返回 None。"""
    path = Path(path)
    basis = normalize_basis(basis) or infer_basis_from_path(path)
    if basis is None:
        return None
    old_meta = None
    try:
        old_meta = path.stat()
    except OSError:
        return None
    if path.suffix == ".parquet" and path.exists():
        stored = read_stored_basis(path)
        if stored != basis:
            df = pd.read_parquet(path)
            if not _write_parquet_with_basis(df, path, basis):
                return None
    _write_sidecar(path, basis, attrs=read_sidecar_attrs(path))
    # 补标记不是「拿到新数据」：恢复 mtime，避免 _cache_expired 被意外刷新
    try:
        os.utime(path, (old_meta.st_atime, old_meta.st_mtime))
        if _sidecar(path).exists():
            os.utime(_sidecar(path), (old_meta.st_atime, old_meta.st_mtime))
    except OSError:
        pass
    return basis


def verify_basis(path: Path, expected: str = None) -> str:
    """读取前校验口径；缺标记/未知/不一致都直接报错。"""
    path = Path(path)
    conf = _conf()
    expected = normalize_basis(expected) if expected is not None else infer_basis_from_path(path)
    stored = read_stored_basis(path)
    if stored is None:
        if conf.get("on_missing_tag", "raise") == "raise":
            mode = conf.get("legacy_qfq_cache", "forbid_read")
            raise MissingPriceBasisError(
                f"{path.name} 缺少复权口径标记 price_basis（旧缓存 / 半迁移残留，"
                f"legacy_qfq_cache={mode}）：禁止按默认口径读取；请先运行 "
                f"`python -m data.versioning --apply` 补标记或删除后重取")
        return expected or ""
    if stored not in KNOWN_BASES:
        if conf.get("on_unknown_basis", "raise") == "raise":
            raise PriceBasisError(
                f"{path.name} 口径标记 {stored!r} 未知（允许：{sorted(KNOWN_BASES)}）")
    if expected is not None and stored != expected:
        raise PriceBasisMismatchError(
            f"{path.name} 实际口径={stored}，但文件名/请求口径={expected}；"
            "疑似迁移中断残留，禁止继续读取")
    return stored


def find_cache_variants(market: str, symbol: str, period: str,
                        cache_dir=None) -> Dict[str, Path]:
    """列出同一 (market, symbol, period) 下的不同口径文件。"""
    base = Path(cache_dir or config.DATA_CACHE_DIR)
    import re
    clean = re.sub(r"[^0-9A-Za-z]", "", str(symbol)).upper()
    prefix = f"{market}_{clean}_{period}_"
    out: Dict[str, Path] = {}
    for file in sorted(base.glob(f"{prefix}*.parquet")) + sorted(base.glob(f"{prefix}*.csv")):
        basis = normalize_basis(file.stem.split(prefix, 1)[1]) or "unknown"
        out.setdefault(basis, file)
    return out


def resolve_unique_cache(market: str, symbol: str, period: str, cache_dir=None) -> Path:
    """调用方只说「哪个标的哪个周期」时，多口径并存必须报错，不许替它挑。"""
    variants = find_cache_variants(market, symbol, period, cache_dir=cache_dir)
    if not variants:
        raise FileNotFoundError(f"未找到 {market} {symbol} {period} 的本地缓存")
    if len(variants) > 1:
        detail = "、".join(f"{basis}={p.name}" for basis, p in variants.items())
        raise AmbiguousPriceBasisError(
            f"{market} {symbol} {period} 同时存在多个复权口径（{detail}）："
            "必须显式指定 adjust，禁止按默认口径读取")
    basis, path = next(iter(variants.items()))
    verify_basis(path, expected=basis)
    return path


def _cache_files(root: Path) -> list:
    files = []
    for sub in ("", "raw", "factors", "adj_factors", "minute"):
        folder = root / sub if sub else root
        if not folder.is_dir():
            continue
        files.extend(sorted(folder.glob("*.parquet")))
        files.extend(sorted(folder.glob("*.csv")))
    return [f for f in files if not f.name.endswith(".tmp")
            and not f.name.endswith(".basis.json")]


def stamp_cache_root(root=None, apply: bool = False) -> Dict[str, object]:
    """为历史缓存补 price_basis 标记（默认 dry-run）。幂等：已打标的跳过。"""
    root = Path(root or config.DATA_CACHE_DIR)
    report = {"root": str(root), "apply": bool(apply),
              "stamped": [], "skipped_tagged": [], "unresolved": []}
    for file in _cache_files(root):
        basis = infer_basis_from_path(file)
        if basis is None:
            report["unresolved"].append(file.name)
            continue
        stored = None
        try:
            stored = read_stored_basis(file)
        except PriceBasisError:
            stored = "conflict"
        if stored == basis:
            report["skipped_tagged"].append(file.name)
            continue
        if apply:
            stamp_file(file, basis)
        report["stamped"].append(file.name)
    return report


if __name__ == "__main__":  # python -m data.versioning [--apply]
    dry = "--apply" not in sys.argv[1:]
    result = stamp_cache_root(apply=not dry)
    print(f"[{'dry-run' if dry else 'apply'}] {result['root']}")
    print(f"  待补/已补 {len(result['stamped'])} 个，已带标记 {len(result['skipped_tagged'])} 个，"
          f"无法推断 {len(result['unresolved'])} 个")
    for name in result["unresolved"]:
        print(f"  ⚠️  无法推断口径：{name}")
