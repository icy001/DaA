# -*- coding: utf-8 -*-
"""13.0 回补验收：PIT 点内成分股闸门（关闭 PIT → 回测入口必须报错）。

对应 config.SNAPSHOT_PIT_GUARD['pit']：
  - 取股票池只允许 get_index_members(code, date)；
  - 不带日期 = 当前成分股 → 报错；
  - 无该日快照 → 报错；
  - enforce_in_backtest=False → 回测入口直接拒跑。
"""
from __future__ import annotations

import config
from core.gov_compat import gov
import pytest

from core.backtester import Backtester
from core.strategy import BaseStrategy
from data import pit_index


class _NoopStrategy(BaseStrategy):
    meta = {"name": "noop_pit", "periods": ["1d"]}

    def on_bar(self, bar):  # noqa: ANN001 - 测试桩
        return None


def test_members_require_as_of_date(tmp_path):
    with pytest.raises(pit_index.PITUnavailableError, match="当前成分股"):
        pit_index.get_index_members("000300", cache_dir=tmp_path)


def test_missing_snapshot_raises(tmp_path):
    with pytest.raises(pit_index.PITUnavailableError, match="未找到"):
        pit_index.get_index_members("000300", "2024-01-02", cache_dir=tmp_path)


def test_snapshot_is_date_scoped(tmp_path):
    pit_index.save_index_members("000300", "2024-01-02", ["600519", "000001"],
                                 cache_dir=tmp_path)
    pit_index.save_index_members("000300", "2024-06-03", ["600519", "300750"],
                                 cache_dir=tmp_path)
    assert pit_index.get_index_members("000300", "2024-01-02", cache_dir=tmp_path) == \
        ["600519", "000001"]
    assert pit_index.get_index_members("000300", "2024-06-03", cache_dir=tmp_path) == \
        ["600519", "300750"]
    # 不同日期不同文件，禁止用最近快照顶替
    with pytest.raises(pit_index.PITUnavailableError):
        pit_index.get_index_members("000300", "2024-03-01", cache_dir=tmp_path)


def test_empty_snapshot_rejected(tmp_path):
    with pytest.raises(pit_index.PITUnavailableError):
        pit_index.save_index_members("000300", "2024-01-02", [], cache_dir=tmp_path)


# ==================== 判据：关 PIT → 回测报错 ====================

def test_assert_pit_enabled_raises_when_disabled(monkeypatch):
    monkeypatch.setitem(config.SNAPSHOT_PIT_GUARD["pit"], "enforce_in_backtest", False)
    with pytest.raises(pit_index.PITUnavailableError, match="已关闭"):
        pit_index.assert_pit_enabled("backtest")
    pit_index.assert_pit_enabled("paper")      # 非回测不拦


def test_backtest_entry_rejects_when_pit_disabled(monkeypatch):
    monkeypatch.setitem(config.SNAPSHOT_PIT_GUARD["pit"], "enforce_in_backtest", False)
    engine = Backtester(_NoopStrategy, symbols=["600519"], start_date="2024-01-01",
                        end_date="2024-03-01", fetcher=object())
    with pytest.raises(pit_index.PITUnavailableError, match="幸存者偏差"):
        engine.prepare()


def test_backtest_entry_accepts_when_pit_enabled():
    # 未关闭 PIT：闸门放行（后续取数因 stub fetcher 缺方法而失败，不属于本用例范围）
    assert config.SNAPSHOT_PIT_GUARD["pit"]["enforce_in_backtest"] is True
    pit_index.assert_pit_enabled("backtest")


def test_universe_resolved_from_dated_snapshot(tmp_path):
    """给 universe 时股票池必须来自带日期的点内快照，而不是 symbols/当前成分股。"""
    pit_index.save_index_members("000300", "2024-01-02", ["600519"], cache_dir=tmp_path)
    engine = Backtester(_NoopStrategy, start_date="2024-01-02", end_date="2024-03-01",
                        fetcher=object(), universe="000300")
    assert engine.symbols == []
    members = pit_index.get_index_members(engine.universe, engine.start_date,
                                          cache_dir=tmp_path)
    assert members == ["600519"]


# ==================== 因子构建路径不得绕过 PIT ====================

def test_get_hs300_without_date_raises():
    from factor import universe as u
    with pytest.raises(pit_index.PITUnavailableError, match="必须指定 as_of 日期"):
        u.get_hs300()


def test_get_hs300_reads_dated_snapshot(tmp_path):
    from factor import universe as u
    pit_index.save_index_members("000300", "2024-01-02", ["600519", "000001"],
                                 cache_dir=tmp_path)
    assert u.get_hs300("2024-01-02", cache_dir=tmp_path) == ["000001", "600519"]
    with pytest.raises(pit_index.PITUnavailableError, match="未找到"):
        u.get_hs300("2024-06-03", cache_dir=tmp_path)


def test_resolve_universe_none_raises():
    from factor import universe as u
    with pytest.raises(pit_index.PITUnavailableError, match="禁止默认全A"):
        u.resolve_universe(None)


def test_resolve_universe_index_requires_date():
    from factor import universe as u
    with pytest.raises(pit_index.PITUnavailableError, match="as_of"):
        u.resolve_universe("hs300")


def test_factor_build_rejects_when_pit_disabled(monkeypatch, tmp_path):
    """关 PIT 后：**指数名**路径拒绝出因子（v3.38 enforce_in_factor 仅约束指数解析）。"""
    monkeypatch.setitem(config.SNAPSHOT_PIT_GUARD["pit"], "enforce_in_factor", False)
    from factor.factor_engine import FactorEngine
    engine = FactorEngine(fetcher=object(), cache_dir=tmp_path)
    with pytest.raises(pit_index.PITUnavailableError, match="enforce_in_factor"):
        engine.compute(["alpha001"], universe="hs300",
                       start="2024-01-02", end="2024-02-01")


def test_factor_explicit_symbols_bypass_pit_gate(monkeypatch, tmp_path):
    """v3.38 分层：显式代码列表没有幸存者偏差可防，关掉 PIT 也不得被拦。"""
    monkeypatch.setitem(config.SNAPSHOT_PIT_GUARD["pit"], "enforce_in_factor", False)
    monkeypatch.setitem(config.SNAPSHOT_PIT_GUARD["pit"], "enforce_in_backtest", False)
    from factor.factor_engine import FactorEngine
    engine = FactorEngine(fetcher=object(), cache_dir=tmp_path)
    with pytest.raises(RuntimeError) as excinfo:          # 放行后的正常失败：stub fetcher 取不到数
        engine.compute(["alpha001"], universe=["600519"],
                       start="2024-01-02", end="2024-02-01")
    assert not isinstance(excinfo.value, pit_index.PITUnavailableError)


def test_factor_index_name_walks_pit(tmp_path):
    """v3.38 分层：compute("hs300") 仍走 PIT——有 as_of 但无该日快照 → raise。"""
    from factor.factor_engine import FactorEngine
    engine = FactorEngine(fetcher=object(), cache_dir=tmp_path)
    with pytest.raises(pit_index.PITUnavailableError, match="未找到"):
        engine.compute(["alpha001"], universe="hs300",
                       start="2024-01-02", end="2024-02-01")


def test_explicit_list_forms_all_bypass():
    """四种显式列表写法都不触发 PIT（None 仍拒）。"""
    from factor import universe as u
    assert u.resolve_universe(["600519", "000001"]) == ["000001", "600519"]
    assert u.resolve_universe("600519, 000001") == ["000001", "600519"]
    assert u.resolve_universe("[600519 000001]") == ["000001", "600519"]
    assert u.resolve_universe("600519") == ["600519"]


def test_v38_scope_keys_declared():
    """v3.40 契约键必须在 config 声明：分层开关 + 单一检查器 + 反向白名单。"""
    from core.gov_compat import gov
    g = gov("SNAPSHOT_PIT_GUARD")
    scope = g["pit"]["enforce_scope"]
    assert scope["by_universe_kind"] is True
    assert scope["allow_implicit_all_a"] is False
    # v3.52：三个旧操作键在业务区 compat（发布方 pit 子树不含）
    assert scope["explicit_symbols_requires_pit"] is False
    assert scope["index_name_requires_pit"] is True
    guard = gov("UNIVERSE_RESOLUTION_GUARD")
    assert guard["explicit_list_is_not_survivorship_bias"] is True
    assert guard["enforce_at"] == "call_time"   # v3.52：发布方把强制点移到 classify_symbol 调用时
    assert guard["resolution_default"] == "deny"
    assert "fail_closed_unknown_input" not in guard      # 与 resolution_default 只留一个
    assert guard["bare_code_is_stock"] is True
    # v3.52：发布方以 code_shape_rule/universe_resolution_* 承载号段判定
    # v3.52：发布方 code_shape_rule 是结构化规则（accepted_patterns/bare_numeric_conflict…）
    assert isinstance(guard["code_shape_rule"], dict)
    assert "accepted_patterns" in guard["code_shape_rule"]
    assert guard["stock_segment_rule"] == "config.STOCK_PREFIX_RULES"
    assert config.STOCK_PREFIX_RULES["SZ"][0] == "000"      # 000xxx 在深市是个股段
    assert gov('UNIVERSE_RESOLUTION_GUARD')['index_alias_single_source'] == 'config.CN_INDEX_ALIASES'   # v3.52 别名源改 CN_INDEX_ALIASES
    assert guard["get_index_members_must_share_checker"] is True


# ==================== fail-closed：未识别的字符串不得静默当代码 ====================

@pytest.mark.parametrize("alias", ["hs300", "HS300", "沪深300", "hs 300", "sh000300",
                                   "000300.SH", "000300.sh", "399001.SZ", "399001"])
def test_index_inputs_all_walk_pit(alias, tmp_path):
    """别名/大小写/空格/前后缀/裸无歧义指数码都归一到指数分支：缺日期即 PIT raise。"""
    from factor import universe as u
    with pytest.raises(pit_index.PITUnavailableError, match="as_of"):
        u.resolve_universe(alias, cache_dir=tmp_path)


def test_index_alias_resolves_dated_snapshot(tmp_path):
    from factor import universe as u
    pit_index.save_index_members("000300", "2024-01-02", ["600519"], cache_dir=tmp_path)
    assert u.resolve_universe("沪深300", as_of="2024-01-02", cache_dir=tmp_path) == ["600519"]
    assert u.resolve_universe("000300.SH", as_of="2024-01-02", cache_dir=tmp_path) == ["600519"]
    assert u.resolve_universe("sh000300", as_of="2024-01-02", cache_dir=tmp_path) == ["600519"]


@pytest.mark.parametrize("bad", ["中证500指数", "沪深三百", "hs3000", "hs300号"])
def test_unknown_string_never_treated_as_code(bad, tmp_path):
    """未命中别名且不是 6 位代码 → ValueError，不允许 fail-open 静默当代码。"""
    from factor import universe as u
    with pytest.raises(ValueError, match="无法识别股票池输入"):
        u.resolve_universe(bad, cache_dir=tmp_path)


def test_true_exchange_segment_conflict_raises():
    """只有真冲突才报错：399001 属深市指数段，不能挂 .SH。"""
    from factor import universe as u
    with pytest.raises(ValueError, match="冲突"):
        u.resolve_universe("399001.SH")


def test_explicit_list_with_index_name_raises():
    """列表里混指数不得被当作代码。"""
    from factor import universe as u
    with pytest.raises(ValueError, match="指数"):
        u.resolve_universe(["hs300", "600519"])


def test_bare_code_means_stock():
    """裸 000xxx 段个股优先（与 guard.bare_code_is_stock 一致），不猜指数。"""
    from factor import universe as u
    assert u.resolve_universe("000001") == ["000001"]
    assert u.resolve_universe("sz000001") == ["000001"]
    assert u.resolve_universe("600519.SH") == ["600519"]


def test_suffixed_index_and_stock_split_by_segment():
    """后缀+号段联合判定：同一段位按交易所区分指数/个股（不再一律拒）。"""
    assert pit_index.classify_symbol("000001.SH") == ("index", "000001")
    assert pit_index.classify_symbol("000001.SZ") == ("stock", "000001")
    assert pit_index.classify_symbol("000300.SH") == ("index", "000300")
    assert pit_index.classify_symbol("399001.SZ") == ("index", "399001")
    assert pit_index.classify_symbol("600519.SH") == ("stock", "600519")


def test_bse_segments_after_migration():
    """v3.43：北交所个股只有 920 段；43/83/87/88 带 .BJ 是失效写法，必须报错。"""
    assert pit_index.classify_symbol("920309.BJ") == ("stock", "920309")
    assert pit_index.classify_symbol("bj920309") == ("stock", "920309")
    assert pit_index.classify_symbol("899050.BJ") == ("index", "899050")
    for stale in ("830799.BJ", "430047.BJ", "600519.BJ"):
        with pytest.raises(ValueError):
            pit_index.classify_symbol(stale)


def test_alias_table_derived_from_config():
    """别名唯一来源是 config.CN_INDEX，模块内不得自建清单。"""
    from factor import universe as u
    aliases = pit_index.index_aliases()
    assert aliases["hs300"] == "000300"
    assert aliases["沪深300"] == "000300"
    assert aliases["中证2000"] == "932000"
    assert aliases["alla"] == "ALLA"
    assert not hasattr(u, "_INDEX_ALIASES") and not hasattr(u, "_INDEX_CODES")


def test_get_index_members_shares_checker(tmp_path):
    """两条路径同一检查器：000300.SH / sh000300 / 沪深300 落到同一个快照文件。"""
    from factor import universe as u
    paths = {pit_index.member_snapshot_path(x, "2024-01-02", cache_dir=tmp_path)
             for x in ("000300.SH", "sh000300", "沪深300")}
    assert len(paths) == 1
    pit_index.save_index_members("000300.SH", "2024-01-02", ["600519"], cache_dir=tmp_path)
    assert u.resolve_universe("sh000300", as_of="2024-01-02", cache_dir=tmp_path) == ["600519"]
