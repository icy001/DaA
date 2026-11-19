# -*- coding: utf-8 -*-
"""独立证券主数据：``empty_reason`` 的唯一合法来源（v3.47 / 13.0.18）。

教训：用「取数返回空」反推退市，恰好就是被限流源的表形——被限流只要被标成退市，
净空闸门反而被绕过。因此「在不在市」只能来自独立证券主数据（上市/退市日期），
必须带 ``as_of`` 判定时点并过时点闸门；没有证据一律返回 ``None``，
由调用方 fail-closed（禁止猜「退市」）。
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Dict, Optional

import config

SOURCE_NAME = "security_master"
# v3.48 / 13.0.19 ④：上游接口登记——「独立」不能只取名字，必须验到接口级。
UPSTREAM_INTERFACE = "akshare.bond_zh_cov_info"

logger = logging.getLogger(__name__)


def assert_upstream_independent() -> None:
    """④ 证据源独立性：上游接口不得出现在行情接口映射（SOURCE_INTERFACE_MAP）值中。

    「security_master 名字独立、上游仍走 akshare 同一出口」= 被限流源换个名字
    给自己出退市证明。判据是接口级的：主数据接口（bond_zh_cov_info）与行情接口
    （bond_zh_hs_cov_daily 等）不同通道才算独立；共享接口直接 raise，
    不得回退行情源反推（forbid_fallback_to_market_source）。
    """
    conf = _conf()
    if not conf.get("forbid_shared_upstream_with_market_data", True):
        return
    registered = (conf.get("upstream_registry") or {}).get(SOURCE_NAME)
    upstream = registered or UPSTREAM_INTERFACE
    market_ifaces = {n for names in
                     (getattr(config, "SOURCE_INTERFACE_MAP", None) or {}).values()
                     for n in names}
    clash = [seg for seg in str(upstream).split(".") if seg in market_ifaces]
    if clash:
        raise ValueError(
            f"证券主数据上游 {upstream!r} 与行情接口共享 {clash}："
            "forbid_shared_upstream_with_market_data=True（接口级独立），"
            "被守卫源不得为自己的退市证明出证；找不到独立上游时按 "
            "listing_probe_unavailable_must_raise 报错，禁止回退行情源")


def _conf() -> dict:
    from core.gov_compat import gov
    return gov("EMPTY_REASON_PROVENANCE")


def _master_dir() -> Path:
    rel = _conf().get("master_cache_dir") or "data_cache/security_master"
    base = Path(getattr(config, "BASE_DIR", Path.cwd()))
    return base / rel


def _cache_path(market: str, symbol: str) -> Path:
    return _master_dir() / f"{market}_{str(symbol).lower()}.json"


def _parse_date(value) -> Optional[dt.date]:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = str(value or "").strip()[:10].replace("/", "-")
    if not text or text.lower() in ("nat", "none", "nan"):
        return None
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


def _fetch_master(market: str, symbol: str) -> Optional[dict]:
    """从独立主数据源取上市/退市日期；目前只有可转债有该主数据。"""
    if market != "cn_convertible":
        return None
    code = str(symbol).strip().lower()
    for prefix in ("sh", "sz"):
        if code.startswith(prefix):
            code = code[len(prefix):]
            break
    try:
        import akshare as ak
        df = ak.bond_zh_cov_info(symbol=code)
    except Exception as exc:  # noqa: BLE001 - 主数据不可达 = 无证据，交给调用方 fail-closed
        logger.warning("[security_master] %s 上游 %s 不可达（%s）：按无证据处理，"
                       "禁止回退行情源反推退市（forbid_fallback_to_market_source）",
                       symbol, UPSTREAM_INTERFACE, exc)
        return None
    if df is None or getattr(df, "empty", True):
        return None
    row = df.iloc[0]
    return {
        "listing_date": _parse_date(row.get("LISTING_DATE")),
        "delist_date": _parse_date(row.get("DELIST_DATE")),
        "retrieved_at": dt.date.today(),
        "provider": "akshare.bond_zh_cov_info",
    }


def _load_master(market: str, symbol: str) -> Optional[dict]:
    path = _cache_path(market, symbol)
    max_age = int(_conf().get("master_max_age_days") or 30)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            retrieved = _parse_date(raw.get("retrieved_at"))
            if retrieved and (dt.date.today() - retrieved).days <= max_age:
                return {
                    "listing_date": _parse_date(raw.get("listing_date")),
                    "delist_date": _parse_date(raw.get("delist_date")),
                    "retrieved_at": retrieved,
                    "provider": raw.get("provider") or "",
                }
        except Exception:  # noqa: BLE001 - 缓存损坏按「需重取」处理
            pass
    fresh = _fetch_master(market, symbol)
    if fresh is None:
        return None          # 拿不到主数据就是无证据，绝不拿旧缓存或空表去猜
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            k: (v.isoformat() if hasattr(v, "isoformat") else v)
            for k, v in fresh.items()
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass                 # 落盘失败不影响本次判定
    return fresh


def listing_status(market: str, symbol: str, as_of) -> Optional[Dict]:
    """上市状态证据；无证据返回 ``None``（调用方必须 raise，禁止反推退市）。

    判定口径：``上市日 ≤ as_of`` 且（未退市 或 ``as_of ≤ 退市日``）→ ``listed=True``。
    """
    conf = _conf()
    decision = _parse_date(as_of)
    if decision is None:
        if conf.get("must_carry_as_of", True):
            return None
        decision = dt.date.today()
    master = _load_master(market, symbol)
    if master is None:
        return None
    listing = master.get("listing_date")
    delist = master.get("delist_date")
    listed = bool(listing and decision >= listing
                  and (delist is None or decision <= delist))
    return {
        "listed": listed,
        "as_of": decision.isoformat(),
        "source": SOURCE_NAME,
        "reason": "" if listed else "delisted_or_not_listed",
        "market": market,
        "symbol": str(symbol),
        "listing_date": listing.isoformat() if listing else None,
        "delist_date": delist.isoformat() if delist else None,
        "provider": master.get("provider") or "",
    }
