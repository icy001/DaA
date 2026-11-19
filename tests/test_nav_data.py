# -*- coding: utf-8 -*-
"""test_nav_data.py —— 第 10 步 10.2 净值型资产数据层（data/fetcher_nav.py）。

硬约束：
  ① 每份净值帧必须带 frequency + disclosure_lag_days 元信息；
  ② 取不到就抛 NavDataUnavailableError，禁止静默返回空表；
  ③ 出网唯一出口 _call_source（限速 + 重试 + 来源标识）；
  ④ 缓存文件名含市场与代码，避免互相覆盖。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from data.fetcher_nav import (NavDataUnavailableError, NavFetcher,
                              detect_frequency, normalize_nav_frame)


def write_nav_csv(path: Path, dates, navs) -> Path:
    pd.DataFrame({"date": dates, "nav": navs}).to_csv(path, index=False)
    return path


# ==================== 频率与元信息 ====================

def test_detect_frequency_buckets():
    daily = pd.date_range("2024-01-01", periods=10, freq="D")
    weekly = pd.date_range("2024-01-01", periods=10, freq="7D")
    monthly = pd.date_range("2024-01-01", periods=10, freq="30D")
    assert detect_frequency(daily) == "daily"
    assert detect_frequency(weekly) == "weekly"
    assert detect_frequency(monthly) == "monthly"
    assert detect_frequency(pd.DatetimeIndex(["2024-01-01", "2024-01-08"])) == "weekly"


def test_normalize_writes_frequency_and_lag():
    n = 12
    frame = pd.DataFrame({"date": pd.date_range("2024-01-05", periods=n, freq="7D"),
                          "nav": [1.0 + 0.01 * i for i in range(n)]})
    out = normalize_nav_frame(frame, source="unit-test", product_type="private_fund")
    assert list(out.columns) == ["date", "nav", "accum_nav", "source"]
    assert out.attrs["frequency"] == "weekly"
    assert out.attrs["disclosure_lag_days"] == \
        config.NAV_PRODUCT_CONFIG["disclosure_lag_days"]["private_fund"]
    assert out.attrs["source"] == "unit-test"
    assert out.attrs["product_type"] == "private_fund"
    # 累计净值缺省时回落到单位净值
    assert (out["accum_nav"] == out["nav"]).all()


def test_normalize_accepts_chinese_columns():
    frame = pd.DataFrame({"日期": pd.date_range("2024-01-01", periods=5, freq="D"),
                          "单位净值": [1, 1.01, 1.02, 1.03, 1.04]})
    out = normalize_nav_frame(frame, product_type="cn_reits")
    assert len(out) == 5
    assert out.attrs["disclosure_lag_days"] == \
        config.NAV_PRODUCT_CONFIG["disclosure_lag_days"]["cn_reits"] == 1


# ==================== 取不到就报错 ====================

@pytest.mark.parametrize("frame", [
    None,
    pd.DataFrame(),
    pd.DataFrame({"date": ["2024-01-01"], "nav": [1.0]}).iloc[0:0],
])
def test_empty_frame_raises(frame):
    with pytest.raises(NavDataUnavailableError):
        normalize_nav_frame(frame, product_type="private_fund")


def test_missing_columns_raises():
    with pytest.raises(NavDataUnavailableError) as info:
        normalize_nav_frame(pd.DataFrame({"foo": [1], "bar": [2]}),
                            product_type="private_fund")
    assert "缺少日期或净值列" in str(info.value)


def test_all_invalid_nav_raises():
    frame = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=3, freq="D"),
                          "nav": [0.0, -1.0, float("nan")]})
    with pytest.raises(NavDataUnavailableError) as info:
        normalize_nav_frame(frame, product_type="private_fund")
    assert "全部无效" in str(info.value)


def test_qii_without_csv_raises_not_silent(tmp_path):
    fetcher = NavFetcher(cache_dir=tmp_path, min_interval=0.0)
    with pytest.raises(NavDataUnavailableError) as info:
        fetcher.fetch_qii_product_nav("QII001", product_type="equity")
    assert "禁止返回空表" in str(info.value)


# ==================== 统一出网出口 ====================

def test_call_source_retries_then_raises(tmp_path):
    fetcher = NavFetcher(cache_dir=tmp_path, min_interval=0.0, retries=1)
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise ConnectionError("网络断开")

    with pytest.raises(NavDataUnavailableError) as info:
        fetcher._call_source("unit-source", boom)
    assert calls["n"] == 2                      # 1 次原始 + 1 次重试
    assert "unit-source" in str(info.value)


def test_call_source_returns_after_retry(tmp_path):
    fetcher = NavFetcher(cache_dir=tmp_path, min_interval=0.0, retries=2)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise TimeoutError("超时")
        return pd.DataFrame({"ok": [1]})

    out = fetcher._call_source("unit-source", flaky)
    assert len(out) == 1 and calls["n"] == 2


# ==================== CSV 导入与缓存 ====================

def test_manual_import_writes_cache_with_market_and_code(tmp_path):
    csv = write_nav_csv(tmp_path / "my_nav.csv",
                        pd.date_range("2024-01-05", periods=8, freq="7D"),
                        [1.0 + 0.02 * i for i in range(8)])
    cache_dir = tmp_path / "cache"
    fetcher = NavFetcher(cache_dir=cache_dir, min_interval=0.0)
    frame = fetcher.manual_nav_import(csv, product_type="private_fund", code="P001")
    assert frame.attrs["frequency"] == "weekly"
    cache_file = cache_dir / "private_fund_P001.csv"
    assert cache_file.exists()


def test_private_fund_prefers_cache(tmp_path):
    csv = write_nav_csv(tmp_path / "my_nav.csv",
                        pd.date_range("2024-01-05", periods=8, freq="7D"),
                        [1.0 + 0.02 * i for i in range(8)])
    cache_dir = tmp_path / "cache"
    fetcher = NavFetcher(cache_dir=cache_dir, min_interval=0.0)
    fetcher.manual_nav_import(csv, product_type="private_fund", code="P002")
    out = fetcher.fetch_private_fund_nav("P002")
    assert out.attrs["source"].startswith("cache:")
    assert out.attrs["disclosure_lag_days"] == 2


def test_manual_import_missing_file_raises(tmp_path):
    fetcher = NavFetcher(cache_dir=tmp_path, min_interval=0.0)
    with pytest.raises(NavDataUnavailableError):
        fetcher.manual_nav_import(tmp_path / "nope.csv", product_type="private_fund")


def test_cache_path_contains_market_and_code(tmp_path):
    fetcher = NavFetcher(cache_dir=tmp_path, min_interval=0.0)
    name = fetcher._cache_path("cn_reits", "508000", "daily").name
    assert name == "cn_reits_508000_daily.csv"
