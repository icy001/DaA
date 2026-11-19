# -*- coding: utf-8 -*-
"""13.0 回补验收：缓存必须自带复权口径标记，缺标记/口径错位/多口径并存一律报错。

对应 config.DATA_VERSIONING 与 SNAPSHOT_PIT_GUARD['integrity']['enforce_on_read']。
"""
from __future__ import annotations

import pandas as pd
import pytest

from core.data_fetcher import DataFetcher
from data import versioning


def _frame(rows: int = 5) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-02", periods=rows, name="date")
    return pd.DataFrame({"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0,
                         "volume": 100.0, "amount": 100.0}, index=idx)


def _fetcher(tmp_path) -> DataFetcher:
    return DataFetcher(cache_dir=tmp_path, request_delay=0, max_retry=1)


# ==================== 写入即打标 ====================

def test_save_tags_parquet_and_sidecar(tmp_path):
    f = _fetcher(tmp_path)
    path = f._cache_path("cn_etf", "510300", "daily", "qfq")
    f._save_cache(_frame(), path)
    assert versioning.read_stored_basis(path.with_suffix(".parquet")) == "qfq"
    assert path.with_suffix(".basis.json").exists()
    assert len(f._read_cache(path)) == 5


def test_raw_and_none_both_tagged_as_raw(tmp_path):
    f = _fetcher(tmp_path)
    for adjust, name in (("", "daily_"), ("none", "daily_none")):
        path = f._cache_path("cn_index", "000300", "daily", adjust)
        f._save_cache(_frame(), path)
        assert versioning.read_stored_basis(path.with_suffix(".parquet")) == "raw", name


# ==================== 判据：半 raw 半 qfq 目录 → 读取报错 ====================

def test_half_raw_half_qfq_untagged_read_raises(tmp_path):
    """半迁移目录：同名同周期同时存在 raw/qfq 两个文件，且都没有口径标记。"""
    f = _fetcher(tmp_path)
    for adjust in ("", "qfq"):
        path = f._cache_path("cn_etf", "510300", "daily", adjust)
        _frame().to_parquet(path.with_suffix(".parquet"))   # 绕过 _save_cache：无标记

    variants = versioning.find_cache_variants("cn_etf", "510300", "daily", cache_dir=tmp_path)
    assert set(variants) == {"raw", "qfq"}

    # ① 依赖「文件名声明的口径」去读，缺标记必须 fail-closed
    with pytest.raises(versioning.MissingPriceBasisError, match="缺少复权口径标记"):
        f._read_cache(f._cache_path("cn_etf", "510300", "daily", "qfq"))

    # ② 调用方只说标的+周期时，多口径并存必须拒绝替它挑
    with pytest.raises(versioning.AmbiguousPriceBasisError, match="多个复权口径"):
        versioning.resolve_unique_cache("cn_etf", "510300", "daily", cache_dir=tmp_path)


def test_mismatch_between_filename_and_tag_raises(tmp_path):
    """迁移中断残留：qfq 内容落在 raw 文件名下 → 直接报错，不得当 raw 用。"""
    f = _fetcher(tmp_path)
    path = f._cache_path("cn_etf", "510300", "daily", "")
    f._save_cache(_frame(), path, basis="qfq")
    with pytest.raises(versioning.PriceBasisMismatchError, match="实际口径=qfq"):
        f._read_cache(path)


def test_unknown_basis_raises(tmp_path):
    f = _fetcher(tmp_path)
    path = f._cache_path("cn_etf", "510300", "daily", "")
    _frame().to_csv(path, encoding="utf-8")
    versioning._write_sidecar(path, "bogus")
    with pytest.raises(versioning.PriceBasisError, match="未知"):
        f._read_cache(path)


def test_csv_only_sidecar_is_readable(tmp_path):
    f = _fetcher(tmp_path)
    path = f._cache_path("cn_etf", "510300", "daily", "qfq")
    _frame().to_csv(path, encoding="utf-8")
    versioning._write_sidecar(path, "qfq")
    assert len(f._read_cache(path)) == 5


def test_sidecar_and_metadata_conflict_raises(tmp_path):
    """边车与 parquet 元数据不一致 = 标记损坏，读前直接报错（不是择一）。"""
    f = _fetcher(tmp_path)
    path = f._cache_path("cn_etf", "510300", "daily", "qfq")
    versioning.write_with_basis(_frame(), path, basis="qfq")
    versioning._write_sidecar(path.with_suffix(".parquet"), "raw")
    with pytest.raises(versioning.PriceBasisMismatchError, match="自相矛盾"):
        f._read_cache(path)


# ==================== 旧缓存补标记（幂等） ====================

def test_stamp_migrates_legacy_cache(tmp_path):
    f = _fetcher(tmp_path)
    path = f._cache_path("cn_etf", "510300", "daily", "qfq")
    _frame().to_parquet(path.with_suffix(".parquet"))
    with pytest.raises(versioning.MissingPriceBasisError):
        f._read_cache(path)

    report = versioning.stamp_cache_root(tmp_path, apply=True)
    assert "cn_etf_510300_daily_qfq.parquet" in report["stamped"]
    assert len(f._read_cache(path)) == 5

    again = versioning.stamp_cache_root(tmp_path, apply=True)
    assert again["stamped"] == []
    assert "cn_etf_510300_daily_qfq.parquet" in again["skipped_tagged"]


def test_stamp_keeps_mtime(tmp_path):
    f = _fetcher(tmp_path)
    path = f._cache_path("cn_etf", "510300", "daily", "hfq")
    parquet = path.with_suffix(".parquet")
    _frame().to_parquet(parquet)
    before = parquet.stat().st_mtime
    versioning.stamp_file(parquet)
    assert parquet.stat().st_mtime == pytest.approx(before)
