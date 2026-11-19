# -*- coding: utf-8 -*-
"""市场识别：指数别名 + 北交所号段迁移（v3.42 / v3.43 验收）。

教训一：汉字与字母都满足 ``str.isalpha()``，「沪深300」「hs300」「北证50」原本一路掉进
「字母+数字 = 国内期货」贪心分支——别名表必须真正接进主链路。

教训二：北交所 2025-10-09 起存量公司整体切到 920 专属号段，43/83/87/88 自此只属新三板。
「.BJ + 旧段」是失效写法，既不能判 neeq 也不能判 cn_stock，必须按 as_of/迁移表解析。
"""
from __future__ import annotations

import config
from core.gov_compat import gov
import pytest


@pytest.mark.parametrize("code,expected", [
    # ---- 指数：别名 / 前缀 / 后缀 ----
    ("沪深300", "cn_index"),
    ("hs300", "cn_index"),
    ("HS 300", "cn_index"),
    ("北证50", "cn_index"),
    ("中证500", "cn_index"),
    ("sh000300", "cn_index"),
    ("sz399001", "cn_index"),
    ("000300.SH", "cn_index"),
    ("399001.SZ", "cn_index"),
    ("899050.BJ", "cn_index"),       # 北证50：BJ 指数段 899
    ("bj899050", "cn_index"),
    # ---- 个股 ----
    ("000001", "cn_stock"),          # 裸 000xxx = 深市个股（平安银行），不猜指数
    ("600519.SH", "cn_stock"),
    ("000001.SZ", "cn_stock"),
    ("920309", "bj_stock"),          # 北交所现行号段（裸码）
    ("920309.BJ", "bj_stock"),
    ("bj920309", "bj_stock"),
    # ---- 新三板：43/83/87/88 段（无 .BJ 后缀才是新三板）----
    ("830799", "neeq"),
    ("430047", "neeq"),
])
def test_detect_market_type_anchor_cases(code, expected):
    assert config.detect_market_type(code) == expected


@pytest.mark.parametrize("code", ["830799.BJ", "bj830799", "430047.BJ"])
def test_stale_bse_suffix_raises(code):
    """43/83/87/88 + .BJ 是 2025-10-09 后的失效写法：不猜 neeq / cn_stock，直接 raise。"""
    with pytest.raises(ValueError, match="失效|迁移表|as_of"):
        config.detect_market_type(code)


@pytest.mark.parametrize("code", ["600519.BJ", "000300.BJ", "399001.BJ"])
def test_bse_suffix_with_non_bse_segment_raises(code):
    """后缀与号段矛盾（沪市个股 / 沪市指数 / 深市指数挂 .BJ）必须报错。"""
    with pytest.raises(ValueError, match="矛盾|冲突|既不是"):
        config.detect_market_type(code)


def test_stale_bse_with_historical_as_of():
    """历史回测显式给 as_of < 2025-10-09 时，旧段按北交所判定；切换日当天即失效。"""
    assert config.detect_market_type("830799.BJ", as_of="2024-01-02") == "bj_stock"
    with pytest.raises(ValueError):
        config.detect_market_type("830799.BJ", as_of="2025-10-09")


def test_bse_migration_table_is_fail_closed():
    """迁移表未落盘时禁止猜映射：表为空 + 无 as_of → raise。"""
    assert config.BSE_CODE_MIGRATION["table"] == {}
    assert config.BSE_CODE_MIGRATION["effective_date"] == "2025-10-09"
    with pytest.raises(ValueError, match="迁移表未落盘"):
        config.detect_market_type("830799.BJ")


def test_index_alias_table_derived_from_cn_index():
    """别名表必须由 CN_INDEX 派生，不得手写第二份。"""
    aliases = config.CN_INDEX_ALIASES
    assert aliases["hs300"] == "000300"
    assert aliases["沪深300"] == "000300"
    assert aliases["zz500"] == "000905"
    assert aliases["alla"] == "ALLA"          # all_a 归一化后去下划线
    assert aliases["北证50"] == "899050"
    index_codes = set(config.CN_INDEX["common_codes"]) | set(
        config.CN_INDEX["pool_aliases"].values())
    assert set(aliases.values()) <= index_codes


def test_every_alias_is_consumed_by_detect():
    """别名表里每一条都必须被 detect_market_type 判成 cn_index（接入 ≠ 定义）。"""
    for alias in config.CN_INDEX_ALIASES:
        assert config.detect_market_type(alias) == "cn_index", alias


@pytest.mark.parametrize("as_of", ["2024-01-02", "2024-04-21"])
def test_bse_920_segment_before_launch_raises(as_of):
    """920 号段 2024-04-22 才启用：as_of 早于启用日 = 引用当时不存在的代码（未来函数）。"""
    for code in ("920002", "920002.BJ", "bj920002"):
        with pytest.raises(ValueError, match="未来函数|不存在"):
            config.detect_market_type(code, as_of=as_of)


def test_bse_920_segment_effective_on_launch_day():
    """启用日当天（2024-04-22，首只 920002 万达轴承）起 920 段有效（含当天）。"""
    assert config.detect_market_type("920002", as_of="2024-04-22") == "bj_stock"
    assert config.detect_market_type("920002.BJ", as_of="2024-04-22") == "bj_stock"
    assert config.detect_market_type("bj920002", as_of="2024-04-22") == "bj_stock"
    # 无 as_of = 现在（920 早已启用），既有调用方不受影响
    assert config.detect_market_type("920002") == "bj_stock"


def test_bare_legacy_segment_as_of_semantics():
    """裸码旧段 as-of：2025-10-09 前属北交所；无 as_of / 切换日当天起属新三板。"""
    assert config.detect_market_type("830799", as_of="2024-01-02") == "bj_stock"
    assert config.detect_market_type("830799") == "neeq"
    assert config.detect_market_type("830799", as_of="2025-10-09") == "neeq"


def test_bj_segments_declared_and_registered():
    """BJ 指数 899 / 个股 920 段必须在段位表；bj_stock 必须能在市场配置里取到。"""
    assert "899" in tuple(config.INDEX_PREFIX_RULES["BJ"])
    assert config.STOCK_PREFIX_RULES["BJ"] == ("920",)
    assert config.BSE_CODE_MIGRATION["segment_effective_date"] == "2024-04-22"
    assert config.BSE_CODE_MIGRATION["effective_date"] == "2025-10-09"
    assert config.CN_INDEX_BARE_CODES["899050"] == "北证50"
    bse = config.get_market_config("bj_stock")
    assert bse["price_limit"]["main"] == 0.3
    assert bse["min_qty"] == 100 and bse["qty_step"] == 1
    assert bse["qii_threshold_financial_assets"] == 500_000
    guard = gov("UNIVERSE_RESOLUTION_GUARD")["bse_segment_rule"]
    assert guard["stock_segments"] == ["920"]
    assert guard["legacy_effective_until"] == "2025-10-09"
