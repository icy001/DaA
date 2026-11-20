# -*- coding: utf-8 -*-
"""13.0.18 数据源适配器结构性验收（v3.47）。

v3.45 / v3.46 的 12 条判据全部保留（切换告警 / 单位冲突 / 无 token 跳过 /
本地兜底空报错 / 探活落盘 / unhealthy 恢复 / 无第二份单位表 / 未登记组合 raise /
自声明 failover 拒绝 / 源级失败必计 / 路由器持本地兜底 / 应交易日净空 raise）。
v3.47 追加「自证族」3 条：
① 取数层源码不得出现 empty_reason 赋值；取数层自填的 empty_reason 运行时被忽略；
② 被限流返空 + 无证券主数据证据 → raise；③ 索引桥缺支持清单组合 / 超范围 → raise。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd
import pytest

import config
from core.gov_compat import gov
from data import source_adapter as sa
from data.source_adapter import (
    DataFieldInconsistencyError,
    DataRouter,
    DataUnavailableError,
    LocalSource,
    TushareSource,
)


def _frame(volume: float = 100.0) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-02", periods=3)
    df = pd.DataFrame({"open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0,
                       "volume": volume, "amount": volume * 10.0}, index=idx)
    df.index.name = "date"
    return df


def _local(frame: pd.DataFrame = None) -> LocalSource:
    """路由器强制持有的本地兜底源（router_must_hold_local_source=True）。"""
    empty = pd.DataFrame() if frame is None else frame
    return LocalSource(reader=lambda **_kw: empty)


class _Dummy(sa.BaseDataSource):
    """可控数据源桩：出错 / 空表 / 正常三态，并统计调用次数。"""

    kinds = ("daily", "minute")
    markets = ("*",)
    thread_safe_timeout = False

    def __init__(self, name: str, *, error: Exception = None,
                 frame: pd.DataFrame = None, healthy: bool = True):
        self.name = name
        self.error = error
        self.frame = frame if frame is not None else _frame()
        self.healthy = healthy
        self.calls = 0

    def fetch(self, kind, symbol, market, start, end, **kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.frame

    def health_check(self) -> bool:
        return self.healthy


# ---------- 判据 1：主源挂了必须切换 + 告警 ----------

def test_failover_logs_warning_and_notifies(tmp_path, caplog):
    alerts = []
    primary = _Dummy("akshare", error=ConnectionError("东财不可达"))
    backup = _Dummy("baostock")
    router = DataRouter([primary, backup, _local()], priority=["akshare", "baostock"],
                        health_file=tmp_path / "source_health.json",
                        notifier=lambda title, content, level: alerts.append(
                            (title, content, level)))

    with caplog.at_level(logging.WARNING, logger="data.source_adapter"):
        df = router.fetch("daily", "600519", "cn_stock", "2024-01-01", "2024-02-01")

    assert df.attrs["source_adapter"] == "baostock"
    assert primary.calls == 1 and backup.calls == 1
    assert any("已切换到 baostock" in r.getMessage() for r in caplog.records), \
        [r.getMessage() for r in caplog.records]
    assert alerts and alerts[0][2] == "warning" and "baostock" in alerts[0][1]


# ---------- 判据 2：手 / 股 单位冲突必须报错（且能先归一） ----------

def test_volume_unit_normalized_and_conflict_detected():
    hand = _frame(volume=100.0)
    shares = _frame(volume=10_000.0)

    normalized = sa.normalize_frame_units(hand, "akshare", "cn_stock", "daily")
    assert normalized["volume"].iloc[0] == 10_000.0          # 手 → 股 ×100
    assert normalized.attrs["volume_unit"] == "股"
    assert normalized.attrs["volume_unit_source"] == "手"
    assert normalized.attrs["volume_unit_multiplier"] == 100

    # 未归一的 akshare(手) 与 baostock(股) 混在一起 → 必须报错
    with pytest.raises(DataFieldInconsistencyError, match="口径冲突"):
        sa.assert_field_consistency({"akshare": _frame(volume=100.0),
                                     "baostock": shares}, "cn_stock")

    # 归一后两者一致 → 放行
    sa.assert_field_consistency({"akshare": normalized, "baostock": shares}, "cn_stock")

    # 期货保留「手」，不做折算
    fut = sa.normalize_frame_units(_frame(volume=100.0), "akshare", "cn_future", "daily")
    assert fut.attrs["volume_unit"] == "手" and fut["volume"].iloc[0] == 100.0


def test_pre_normalized_frame_is_not_scaled_twice():
    """数据层已归一（attrs.volume_unit）的帧，路由器不得再乘 100。

    真实链路是 DataRouter → data_fetcher._dispatch_* → _normalize_units，
    到路由器手里时 volume 已是「股」；此时若再按「源原始单位=手」折算，
    A 股成交量会凭空放大 100 倍。attrs 声明必须优先于硬编码表。
    """
    df = _frame(volume=1000.0)
    df.attrs.update({"volume_unit": "股", "source_volume_unit": "手"})
    out = sa.normalize_frame_units(df, "akshare", "cn_stock", "daily")
    assert out["volume"].iloc[0] == 1000.0
    assert out.attrs["volume_unit"] == "股"
    assert out.attrs["volume_unit_multiplier"] == 1.0
    assert out.attrs["unit_pre_normalized_by_data_layer"] is True


def test_index_volume_kept_as_lot():
    """指数统一口径是「手」，不得折成「股」（与 test_data 的指数断言同源）。"""
    idx = sa.normalize_frame_units(_frame(volume=3.0), "akshare", "cn_index", "daily")
    assert idx.attrs["volume_unit"] == "手" and idx["volume"].iloc[0] == 3.0


def test_unified_source_flag_never_rescales_even_without_attrs(tmp_path):
    """缓存命中后 attrs 丢失时，returns_unified_units 仍必须阻止二次折算。

    实测依据：data_cache/raw/cn_stock_600519_daily_raw.csv 被放大到
    amount/(close×volume)≈0.01（volume ×100），正是 attrs 丢失后重复折算造成。
    """
    src = _Dummy("akshare")
    src.returns_unified_units = True
    router = DataRouter([src, _local()], health_file=tmp_path / "source_health.json")
    df = router.fetch("daily", "600519", "cn_stock", "2024-01-01", "2024-02-01")
    assert df["volume"].iloc[0] == 100.0                 # 不乘 100
    assert df.attrs["volume_unit"] == "股"
    assert df.attrs["volume_unit_multiplier"] == 1.0
    assert df.attrs["unit_pre_normalized_by_data_layer"] is True


def test_market_unavailable_does_not_poison_source_health(tmp_path):
    """市场级不可用不得累计到源健康计数（否则单点市场会把 A 股整条链路拖死）。

    实测依据：test_data 核实8 模拟东财挂掉时，forex/cn_fund/转债等单点市场
    各抛一次「无可用数据源」，把 akshare 连坏计数顶到阈值，随后 600519 本应
    回退新浪却因 akshare 被标 unhealthy 而整体报错。
    """
    src = _Dummy("akshare", error=sa.DataUnavailableError("该市场当前无可用数据源"))
    router = DataRouter([src, _local()], health_file=tmp_path / "source_health.json")
    for _ in range(4):
        with pytest.raises(DataUnavailableError, match="无可用数据源"):
            router.fetch("daily", "EURUSD", "forex", "2024-01-01", "2024-02-01")
    assert src.calls == 4                  # 每次都要真去试，不能被 unhealthy 跳过
    assert not router.is_unhealthy("akshare")

    # 单点故障市场抛普通连接错误（文案不是固定的「无可用数据源」）同样算市场级：
    # 该市场在 config.SINGLE_SOURCE_MARKETS 里只声明了 akshare，失败即市场不可用。
    busy = _Dummy("akshare", error=ConnectionError("push2his 不可达"))
    router2 = DataRouter([busy, _local()], health_file=tmp_path / "h2.json")
    for _ in range(4):
        with pytest.raises(DataUnavailableError):
            router2.fetch("daily", "EURUSD", "forex", "2024-01-01", "2024-02-01")
    assert busy.calls == 4
    assert not router2.is_unhealthy("akshare")


def test_self_declared_internal_failover_rejected(tmp_path):
    """③ 非白名单自标 internal_failover → 构造即 raise（被守卫对象不得给自己发豁免）。

    白名单只由 config.INTERNAL_FAILOVER_SOURCES 决定；白名单内的源可以标注，但
    标注不再换来「失败不计数」的豁免（见下一条判据）。
    """
    outsider = _Dummy("baostock")
    outsider.internal_failover = True
    with pytest.raises(ValueError, match="不得自声明"):
        DataRouter([outsider, _local()], health_file=tmp_path / "h.json")

    insider = _Dummy("akshare")
    insider.internal_failover = True
    DataRouter([insider, _local()], health_file=tmp_path / "h2.json")   # 白名单内允许


def test_source_level_failures_still_count_for_internal_failover_source(tmp_path):
    """④ 内部回退链的源，源级失败仍必须计数并最终熔断（否则反复重连 → 封 IP）。"""
    src = _Dummy("akshare", error=ConnectionError("被限流"))
    router = DataRouter([src, _local()], priority=["akshare", "local"],
                        health_file=tmp_path / "source_health.json")
    args = ("daily", "600519", "cn_stock", "2024-01-01", "2024-02-01")
    limit = int(config.DATA_LONG_TERM["max_consecutive_failures"])

    for _ in range(limit):
        with pytest.raises(DataUnavailableError):
            router.fetch(*args)
    assert router.is_unhealthy("akshare") is True
    assert src.calls == limit

    with pytest.raises(DataUnavailableError, match="unhealthy"):
        router.fetch(*args)
    assert src.calls == limit          # 熔断后不再打接口

    state = json.loads((tmp_path / "source_health.json").read_text(encoding="utf-8"))
    assert state["sources"]["akshare"]["consecutive_failures"] == limit


# ---------- 判据 3：tushare 无 token 必须跳过而非阻断 ----------

def test_tokenless_tushare_is_skipped_not_fatal(tmp_path, caplog):
    def _boom(**_kwargs):
        raise AssertionError("无 token 时不得调用 tushare 取数")

    tushare = TushareSource(token="", dispatch=_boom)
    akshare = _Dummy("akshare")
    router = DataRouter([tushare, akshare, _local()], priority=["tushare", "akshare"],
                        health_file=tmp_path / "source_health.json")

    with caplog.at_level(logging.INFO, logger="data.source_adapter"):
        df = router.fetch("daily", "600519", "cn_stock", "2024-01-01", "2024-02-01")

    assert df.attrs["source_adapter"] == "akshare"
    assert any("跳过 tushare" in r.getMessage() for r in caplog.records)
    # 「未配置」不是「坏」，不得记成 unhealthy，也不该写健康档案
    assert router.is_unhealthy("tushare") is False
    assert not (tmp_path / "source_health.json").exists()


# ---------- 判据 4：全远程失败 + 本地空 → 必须报错 ----------

def test_local_fallback_empty_raises_and_nonempty_returns(tmp_path):
    empty_local = LocalSource(reader=lambda **_kw: pd.DataFrame())
    router = DataRouter([_Dummy("akshare", error=ConnectionError("全挂")), empty_local],
                        priority=["akshare", "local"],
                        health_file=tmp_path / "h1.json")
    with pytest.raises(DataUnavailableError, match="无可用数据源"):
        router.fetch("daily", "600519", "cn_stock", "2024-01-01", "2024-02-01")

    good_local = LocalSource(reader=lambda **_kw: _frame())
    router2 = DataRouter([_Dummy("akshare", error=ConnectionError("全挂")), good_local],
                         priority=["akshare", "local"],
                         health_file=tmp_path / "h2.json")
    df = router2.fetch("daily", "600519", "cn_stock", "2024-01-01", "2024-02-01")
    assert df.attrs["router_local_fallback"] is True
    assert df.attrs["source_adapter"] == "local"


# ---------- 判据 5：health_check 必须落盘 ----------

def test_health_check_writes_json(tmp_path):
    router = DataRouter([_Dummy("akshare"), _Dummy("baostock", healthy=False), _local()],
                        priority=["akshare", "baostock"],
                        health_file=tmp_path / "source_health.json")
    out = router.health_check()

    path = tmp_path / "source_health.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["sources"]["akshare"]["healthy"] is True
    assert data["sources"]["baostock"]["healthy"] is False
    assert data["sources"]["baostock"]["note"] == "探活失败"
    assert out["results"]["baostock"]["healthy"] is False
    assert data["updated_at"] and data["sources"]["akshare"]["last_check"]


# ---------- 判据 6：连坏 N 次 → unhealthy 跳过，探活通过后恢复 ----------

def test_consecutive_failures_mark_unhealthy_then_recover(tmp_path):
    bad = _Dummy("akshare", error=ConnectionError("连续坏"))
    router = DataRouter([bad, _local()], priority=["akshare"],
                        health_file=tmp_path / "source_health.json")
    args = ("daily", "600519", "cn_stock", "2024-01-01", "2024-02-01")

    limit = int(config.DATA_LONG_TERM["max_consecutive_failures"])
    for _ in range(limit):
        with pytest.raises(DataUnavailableError):
            router.fetch(*args)
    assert bad.calls == limit

    state = json.loads((tmp_path / "source_health.json").read_text(encoding="utf-8"))
    assert state["sources"]["akshare"]["unhealthy"] is True
    assert state["sources"]["akshare"]["consecutive_failures"] == limit

    # 已 unhealthy：本次路由直接跳过，不再打接口
    with pytest.raises(DataUnavailableError, match="unhealthy"):
        router.fetch(*args)
    assert bad.calls == limit

    # 探活通过 → 解除 unhealthy，恢复取数
    bad.error, bad.healthy = None, True
    router.health_check()
    assert router.is_unhealthy("akshare") is False
    df = router.fetch(*args)
    assert df.attrs["source_adapter"] == "akshare"


# ---------- 配置锚点：6 个闸门键 + 规格版本 ----------

def test_config_gates_declared():
    conf = gov("DATA_LONG_TERM")
    assert conf["failover_log_required"] is True
    assert conf["field_consistency_required"] is True
    assert conf["tokenless_sources_first"] is True
    assert conf["max_consecutive_failures"] == 3
    assert conf["local_fallback_must_exist"] is True
    assert conf["source_health_file"] == "data_cache/source_health.json"
    assert config.SPEC_VERSION >= "v3.52"   # v3.53 起随版本滚动，只钉不倒退
    assert "13.0.19" in config.SPEC_VERSION_CHECK["must_contain_markers"]
    assert "13.0.20" in config.SPEC_VERSION_CHECK["must_contain_markers"]
    guard = gov("DATA_SOURCE_ADAPTER_GUARD")
    assert guard["map_scope_must_equal_supported_scope"] is True
    assert guard["map_scope_missing_must_raise"] is True
    assert guard["empty_evidence_only_from_security_master"] is True
    assert guard["tried_must_include_empty_sources"] is True
    # v3.48 / 13.0.19 ④：探针上游独立 + as_of 归一硬前置
    assert guard["listing_probe_required"] is True
    assert guard["as_of_normalization_required"] is True
    assert guard["probe_upstream_must_be_independent"] is True
    prov = gov("EMPTY_REASON_PROVENANCE")
    # v3.52：发布方血统值为 securities_master（复数）；本机模块名单数由 compat 并收
    assert config.EMPTY_REASON_PROVENANCE["allowed_sources"] == ["securities_master"]   # 发布方原值
    assert set(gov("EMPTY_REASON_PROVENANCE")["allowed_sources"]) == {"security_master", "securities_master"}
    assert gov("EMPTY_REASON_PROVENANCE")["fetcher_must_not_assign_empty_reason"] is True
    assert prov["must_carry_as_of"] is True and prov["pit_gate_required"] is True
    # v3.48 / 13.0.19 ④：上游独立性是接口级判据，不是名字级
    assert prov["forbid_shared_upstream_with_market_data"] is True
    assert prov["forbid_fallback_to_market_source"] is True
    assert prov["listing_probe_unavailable_must_raise"] is True
    assert prov["independent_upstream_required"] is True
    assert "bond_zh_cov_info" in str(prov["upstream_registry"]["security_master"])
    assert prov["as_of_must_normalize_before_compare"] is True
    assert prov["as_of_canonical_format"] == "YYYYMMDD"


# ---------- 判据 ①：适配器不得持有第二份单位表 ----------

def test_adapter_has_no_second_unit_table():
    """① 单位口径只允许 config 一条链：SOURCE_INTERFACE_MAP → DATA_SOURCE_UNITS。

    13.1 的 (源, 市场, 周期) 硬编码表与 DATA_SOURCE_UNITS 是两套维度描述同一事实，
    必然漂移（实测表现为 amount/(close×volume)=0.01，即 volume 被 ×100 两次）。
    """
    assert not hasattr(sa, "SOURCE_VOLUME_UNITS")
    assert not hasattr(sa, "VOLUME_UNIT_AS_LOT_MARKETS")

    # 派生值与 config 完全同源，不是模块内另写一份
    assert sa.interface_names_of("akshare", "cn_stock", "daily")[0] == "stock_zh_a_hist"
    unit, mult, unified = sa.volume_unit_of("akshare", "cn_stock", "daily")
    spec = config.DATA_SOURCE_UNITS["stock_zh_a_hist"]
    assert (mult, unified) == (float(spec["volume_factor"]), spec["unified_volume"])
    assert (unit, mult, unified) == ("手", 100.0, "股")

    # 源码里不得再出现三元组硬编码（形如 ("akshare", "cn_stock", "daily"): ("手", 100）
    src = Path(sa.__file__).read_text(encoding="utf-8")
    assert '("akshare", "cn_stock", "daily"): ("手", 100' not in src
    assert "SOURCE_VOLUME_UNITS: Dict" not in src


# ---------- 判据 ②：未登记组合必须 raise ----------

def test_unregistered_unit_combo_raises():
    """② 未登记接口 → raise，不得默认乘 1 静默放行。"""
    with pytest.raises(ValueError, match="未登记的单位口径组合"):
        sa.volume_unit_of("unknown_source", "cn_stock", "daily")
    with pytest.raises(ValueError, match="未登记的单位口径组合"):
        sa.normalize_frame_units(_frame(), "akshare", "cn_stock", "tick")


def test_source_interface_map_is_valid():
    """索引桥的每个值都必须真实存在于 DATA_SOURCE_UNITS（防手写漂移）。"""
    bridge = config.SOURCE_INTERFACE_MAP
    assert bridge, "SOURCE_INTERFACE_MAP 不得为空"
    missing = [n for names in bridge.values() for n in names
               if n not in config.DATA_SOURCE_UNITS]
    assert not missing, f"引用了不存在的接口：{missing}"
    # 覆盖全部走取数实现的市场：日线 15 个 + 分钟 10 个（缺一个就会在运行时 raise）
    daily = {m for (s, m, k) in bridge if s == "akshare" and k == "daily"}
    minute = {m for (s, m, k) in bridge if s == "akshare" and k == "minute"}
    assert daily == {"cn_stock", "cn_etf", "us_stock", "us_etf", "hk_stock",
                     "cn_convertible", "cn_reits", "cn_future", "global_future",
                     "forex", "cn_option", "crypto", "cn_fund", "cn_reverse_repo",
                     "cn_index"}
    assert minute == {"cn_stock", "cn_etf", "cn_index", "us_stock", "us_etf",
                      "hk_stock", "cn_convertible", "cn_future", "forex", "crypto"}


# ---------- 判据 ⑤：本地兜底是路由器职责 ----------

def test_router_requires_local_source_and_direct_fetch_falls_back(tmp_path):
    """⑤ 缺 LocalSource 拒绝构造；直调 DataRouter.fetch 也必须走本地兜底。"""
    with pytest.raises(ValueError, match="缺少本地兜底源"):
        DataRouter([_Dummy("akshare")], health_file=tmp_path / "h0.json")

    router = DataRouter([_Dummy("akshare", error=ConnectionError("全挂")),
                         _local(_frame(volume=7.0))],
                        priority=["akshare", "local"],
                        health_file=tmp_path / "h1.json")
    df = router.fetch("daily", "600519", "cn_stock", "2024-01-01", "2024-02-01")
    assert df.attrs["router_local_fallback"] is True
    assert df.attrs["source_adapter"] == "local"
    assert df.attrs["volume_unit"] == "股"
    assert df["volume"].iloc[0] == 7.0        # 已归一的本地缓存不得再乘 100


# ---------- 判据 ⑥：应交易日净空必须 raise ----------

def test_expected_trading_day_all_empty_raises(tmp_path):
    """⑥ 应交易日 + 全源净空 → raise；休市 → 返回空表并带探活证据；无探针 → raise。"""
    def _router(probe, name):
        return DataRouter([_Dummy("akshare", frame=pd.DataFrame()), _local()],
                          priority=["akshare", "local"],
                          health_file=tmp_path / name,
                          trading_day_probe=probe)

    args = ("daily", "600519", "cn_stock", "2024-01-01", "2024-02-01")
    with pytest.raises(DataUnavailableError, match="应交易日"):
        _router(lambda _d, _m="cn_stock": True, "h1.json").fetch(*args)

    df = _router(lambda _d, _m="cn_stock": False, "h2.json").fetch(*args)
    assert df.empty
    assert df.attrs["router_all_empty"] == ["akshare"]
    assert df.attrs["probe_evidence"] == "non_trading_day"

    with pytest.raises(DataUnavailableError, match="无交易日探活证据"):
        _router(None, "h3.json").fetch(*args)

    # 合法空只能由证券主数据出具：有证据 → 返回空表并带证据与 as_of
    def _master(market, symbol, as_of):
        return {"listed": False, "as_of": str(as_of)[:10], "source": "security_master",
                "reason": "delisted_or_not_listed", "provider": "fake_master"}

    router4 = DataRouter([_Dummy("akshare", frame=pd.DataFrame()), _local()],
                         priority=["akshare", "local"], health_file=tmp_path / "h4.json",
                         trading_day_probe=lambda _d, _m="cn_stock": True,
                         listing_probe=_master)
    out = router4.fetch(*args)
    assert out.empty
    assert out.attrs["empty_reason"] == "delisted_or_not_listed"
    assert out.attrs["empty_reason_source"] == "security_master"
    # v3.48：闸门入口归一后 as_of 为规范 YYYYMMDD（as_of_canonical_format）
    assert out.attrs["empty_evidence"]["as_of"] == "20240201"


# ---------- 判据 ①（v3.47）：取数层不得自证合法空 ----------

def test_fetch_layer_has_no_empty_reason_assignment():
    """① 取数层源码不得出现 empty_reason 赋值：自证 = 自己签退市证明。"""
    root = Path(sa.__file__).resolve().parent.parent
    src = (root / "core" / "data_fetcher.py").read_text(encoding="utf-8")
    hits = [ln for ln in src.splitlines()
            if "empty_reason" in ln and "=" in ln.split("empty_reason", 1)[1][:4]]
    assert not hits, f"取数层仍在自证 empty_reason：{hits}"


def test_self_attested_empty_reason_is_ignored(tmp_path):
    """① 运行时：取数层写死的 empty_reason 一律不采信，仍按「无证据」fail-closed。"""
    stamped = pd.DataFrame()
    stamped.attrs["empty_reason"] = "delisted_or_not_listed"
    router = DataRouter([_Dummy("akshare", frame=stamped), _local()],
                        priority=["akshare", "local"],
                        health_file=tmp_path / "h_self.json",
                        trading_day_probe=lambda _d, _m="cn_stock": True)
    with pytest.raises(DataUnavailableError, match="应交易日"):
        router.fetch("daily", "123045", "cn_convertible", "2024-01-01", "2024-02-01")


# ---------- 判据 ②（v3.47）：无主数据证据的净空必须 raise ----------

def test_empty_without_master_evidence_raises(tmp_path):
    """② 被限流返空 + 无证券主数据证据 → raise（不得反推为退市）。"""
    def _no_evidence(_market, _symbol, _as_of):
        return None

    router = DataRouter([_Dummy("akshare", frame=pd.DataFrame()), _local()],
                        priority=["akshare", "local"],
                        health_file=tmp_path / "h_none.json",
                        trading_day_probe=lambda _d, _m="cn_convertible": True,
                        listing_probe=_no_evidence)
    with pytest.raises(DataUnavailableError, match="应交易日"):
        router.fetch("daily", "113052", "cn_convertible", "2024-01-01", "2024-02-01")

    # as_of 与决策时点不一致 → 时点闸门拦截（拿今天的在市状态判历史区间=未来函数）
    def _wrong_pit(_market, _symbol, _as_of):
        return {"listed": False, "as_of": "2099-01-01", "source": "security_master"}

    router2 = DataRouter([_Dummy("akshare", frame=pd.DataFrame()), _local()],
                         priority=["akshare", "local"],
                         health_file=tmp_path / "h_pit.json",
                         trading_day_probe=lambda _d, _m="cn_convertible": True,
                         listing_probe=_wrong_pit)
    with pytest.raises(DataUnavailableError, match="应交易日"):
        router2.fetch("daily", "113052", "cn_convertible", "2024-01-01", "2024-02-01")

    # 证据来源不在白名单（取数层伪造）→ 同样按无证据处理
    def _fake_source(_market, _symbol, as_of):
        return {"listed": False, "as_of": str(as_of), "source": "akshare_daily"}

    router3 = DataRouter([_Dummy("akshare", frame=pd.DataFrame()), _local()],
                         priority=["akshare", "local"],
                         health_file=tmp_path / "h_src.json",
                         trading_day_probe=lambda _d, _m="cn_convertible": True,
                         listing_probe=_fake_source)
    with pytest.raises(DataUnavailableError, match="应交易日"):
        router3.fetch("daily", "113052", "cn_convertible", "2024-01-01", "2024-02-01")


# ---------- 判据 ③（v3.47）：索引桥必须与支持清单同域 ----------

def test_map_scope_must_equal_supported_scope(monkeypatch, tmp_path):
    """③ 支持清单缺一组合 / 桥里超范围 → raise，禁止两表靠手工补 key 对齐。"""
    scope = {k: list(v) for k, v in config.SUPPORTED_KLINE_MARKETS.items()}
    scope["daily"] = scope["daily"] + ["mars_stock"]
    monkeypatch.setattr(config, "SUPPORTED_KLINE_MARKETS", scope, raising=False)
    with pytest.raises(ValueError, match="覆盖面不一致"):
        sa.assert_map_scope_covers_supported_scope()
    with pytest.raises(ValueError, match="覆盖面不一致"):
        DataRouter([_Dummy("akshare"), _local()], health_file=tmp_path / "h.json")


def test_interface_names_of_rejects_wildcard_fallback():
    """③ 精确组合未登记时不得被通配 key 吸附（缺登记 = 未登记）。"""
    assert sa.interface_names_of("akshare", "cn_stock", "daily")
    assert sa.interface_names_of("akshare", "mars_stock", "daily") == ()
    with pytest.raises(ValueError, match="未登记的单位口径组合"):
        sa.volume_unit_of("akshare", "mars_stock", "daily")


# ---------- 判据 ④（v3.48 / 13.0.19）：探针上游独立 + as_of 归一硬前置 ----------

def test_security_master_upstream_is_independent():
    """④ 上游独立性是接口级判据：主数据接口不得出现在行情单位索引桥里。

    名字独立（模块叫 security_master）不等于上游独立：若主数据探针仍走
    akshare 同一行情出口，「独立证据源」只是换个名字的行情源自证。
    """
    from data import security_master as sm

    # 当前登记的上游接口必须真实独立于行情映射
    assert sm.UPSTREAM_INTERFACE == gov("EMPTY_REASON_PROVENANCE")[
        "upstream_registry"]["security_master"]
    sm.assert_upstream_independent()                    # 现状必须通过

    # 上游落进行情接口映射 → 接口级共享，直接 raise
    iface = sm.UPSTREAM_INTERFACE.split(".")[-1]
    polluted = {**config.SOURCE_INTERFACE_MAP, "akshare": ["stock_zh_a_hist", iface]}
    orig = config.SOURCE_INTERFACE_MAP
    try:
        config.SOURCE_INTERFACE_MAP = polluted
        with pytest.raises(ValueError, match="上游"):
            sm.assert_upstream_independent()
    finally:
        config.SOURCE_INTERFACE_MAP = orig


def test_listing_probe_unavailable_raises_without_fallback(tmp_path):
    """④ 探针不可达 → raise，不得回退行情源反推退市（listing_probe_unavailable_must_raise）。"""
    def _probe_error(_market, _symbol, _as_of):
        raise ConnectionError("主数据上游不可达")

    router = DataRouter([_Dummy("akshare", frame=pd.DataFrame()), _local()],
                        priority=["akshare", "local"],
                        health_file=tmp_path / "h_probe.json",
                        trading_day_probe=lambda _d, _m="cn_convertible": True,
                        listing_probe=_probe_error)
    with pytest.raises(DataUnavailableError, match="应交易日"):
        router.fetch("daily", "113052", "cn_convertible", "2024-01-01", "2024-02-01")


def test_as_of_normalized_at_gate_entry(tmp_path):
    """④ as_of 归一是闸门入口的硬前置：调用方传什么格式都先归一成 YYYYMMDD。

    实测教训（v3.47）：路由器把 end="20261118" 传进时点闸门、主数据回 ISO
    日期，字符串直比不等 → 已退市标的 123045 被误判「无证据」而 raise。
    同一件事换个方向就是黑洞，必须前置归一而不是靠调用方自觉。
    """
    seen = {}

    def _master(_market, symbol, as_of):
        seen[symbol] = str(as_of)
        return {"listed": symbol != "123045", "as_of": str(as_of)[:10],
                "source": "security_master", "provider": "fake_master",
                "reason": "delisted_or_not_listed"}

    router = DataRouter([_Dummy("akshare", frame=pd.DataFrame()), _local()],
                        priority=["akshare", "local"],
                        health_file=tmp_path / "h_norm.json",
                        trading_day_probe=lambda _d, _m="cn_convertible": True,
                        listing_probe=_master)
    # 123045 = 已退市标的：主数据出具证据 → 合法空（v3.47 曾因格式不归一误杀）
    out = router.fetch("daily", "123045", "cn_convertible",
                       "2024-01-01", "2024-02-01")
    assert out.empty and out.attrs["empty_reason_source"] == "security_master"
    # 闸门收到的 as_of 必须已归一（YYYYMMDD，不得 ISO/紧凑格式直传导致直比不等）
    assert seen["123045"] == "20240201"
