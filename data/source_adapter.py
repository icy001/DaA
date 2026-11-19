# -*- coding: utf-8 -*-
"""13.1 数据源适配器：统一路由 + 结构性 fail-closed 闸门（v3.46 / 13.0.17）。

教训：多数据源各自 ``requests.get`` 时，下面四类错误都不会自己报出来——
主源挂了悄悄切到备源没人知道；akshare 的 volume 是「手」、baostock 是「股」，
拼接后成交量凭空放大 100 倍；tushare 没 token 直接抛错把整条链路带崩；
所有远程源失败 + 本地空，返回空 DataFrame 被下游当成「今天没成交」。

本模块只做一件事：把「选源 / 切换 / 单位归一 / 探活 / 兜底」收口到唯一入口，
并且每个决策都留痕（日志 / notifier / source_health.json）。

单位口径只能来自 config 的单一索引：``SOURCE_INTERFACE_MAP`` 负责 (源, 市场, 周期) →
接口名，``DATA_SOURCE_UNITS`` 负责接口名 → 单位与折算系数。适配器内部禁止再持有
第二份单位表；未登记组合一律 raise，禁止 auto 反推（与第 1 步「单位必须显式声明」同源）。
"""
from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FutureTimeout
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

import config

logger = logging.getLogger(__name__)


# ==================== 异常：三类失败必须可区分 ====================

class DataFieldInconsistencyError(ValueError):
    """跨源字段口径冲突（典型：volume 手 / 股 未折算），禁止静默拼接。"""


class DataUnavailableError(RuntimeError):
    """所有远程源失败且本地无兜底：必须报错，禁止返回空表当成功。"""


class SourceUnavailableError(RuntimeError):
    """单源不可用（无 token / 未注入适配器 / 探活失败）：路由内部吞掉后切下一个。"""


# ==================== 单位口径唯一索引（config 驱动，禁止第二份表） ====================

def _guard(key: str, default=True):
    from core.gov_compat import gov
    return gov("DATA_SOURCE_ADAPTER_GUARD").get(key, default)


def _norm_day(value) -> str:
    """把 ``2026-11-18`` / ``20261118`` / ``2026/11/18`` 归成 ``YYYYMMDD``。

    时点闸门要比的是「同一天」，不是「同一个字符串写法」——请求侧用
    ``YYYYMMDD``、主数据侧用 ISO 时，字符串直比会把合法空误判成无证据。
    """
    return "".join(ch for ch in str(value or "") if ch.isdigit())[:8]


def interface_names_of(source: str, market: str, kind: str) -> tuple:
    """(源, 市场, 周期) → 接口名元组；索桥只有 ``config.SOURCE_INTERFACE_MAP`` 一份。

    v3.47：``map_scope_missing_must_raise=True`` 时禁止通配回退——通配会把「新增市场
    忘了登记」悄悄吸附到 ``(source, "*", kind)`` 上，等于让缺登记的组合照样过闸。
    精确组合不存在 = 未登记，一律由 ``volume_unit_of`` raise。
    """
    bridge = getattr(config, "SOURCE_INTERFACE_MAP", None) or {}
    exact = (source, market, kind)
    if exact in bridge:
        return tuple(bridge[exact])
    if _guard("map_scope_missing_must_raise", True):
        return ()
    for key in ((source, "*", kind), (source, market, "*"), (source, "*", "*")):
        if key in bridge:
            return tuple(bridge[key])
    return ()


def assert_map_scope_covers_supported_scope() -> None:
    """索引桥覆盖面必须与支持清单同域（v3.47 / 13.0.18）。

    两份表并存时，「支持哪些市场」写在 data_fetcher、「接口名怎么映射」写在 config，
    靠逐个手工补 key 对齐——加一个市场必然再漂。现在支持清单只有
    ``config.SUPPORTED_KLINE_MARKETS`` 一份，本函数双向校验：

    - 支持清单里的每个 (市场, 周期) 必须在桥里有 akshare 登记（缺一组合即 raise）；
    - 桥里的 akshare 条目不得超出支持清单（否则清单又成了第二份事实）。
    """
    if not _guard("map_scope_must_equal_supported_scope", True):
        return
    scope = getattr(config, "SUPPORTED_KLINE_MARKETS", None) or {}
    bridge = getattr(config, "SOURCE_INTERFACE_MAP", None) or {}
    missing, extra = [], []
    for kind in ("daily", "minute"):
        markets = list(scope.get(kind) or [])
        for market in markets:
            if ("akshare", market, kind) not in bridge:
                missing.append(f"akshare/{market}/{kind}")
        for key in bridge:
            if not (isinstance(key, tuple) and len(key) == 3):
                continue
            src, mk, kd = key
            if src == "akshare" and kd == kind and mk not in markets:
                extra.append(f"akshare/{mk}/{kd}")
    if missing or extra:
        raise ValueError(
            "SOURCE_INTERFACE_MAP 与 SUPPORTED_KLINE_MARKETS 覆盖面不一致："
            f"缺登记={missing or '无'}；超范围={extra or '无'}；"
            "map_scope_must_equal_supported_scope=True，新增市场必须同步登记接口名")


def volume_unit_of(source: str, market: str, kind: str) -> Optional[tuple]:
    """按 config 单一索引取 (源单位名, 乘数, 统一单位)。

    v3.46：适配器不再持有第二份 (源, 市场, 周期) 单位表。先查 ``SOURCE_INTERFACE_MAP``
    拿接口名，再查 ``DATA_SOURCE_UNITS`` 拿该接口的单位定义——两套维度只由一座桥连接，
    改一处不会漂移出第二套事实。未登记组合直接 raise，禁止默认 ×1 静默猜。
    """
    if source == "local":
        # 本地缓存落盘前已由数据层归一到统一口径，这里只声明统一单位，不再乘系数。
        unified = (getattr(config, "UNIFIED_VOLUME_UNIT", None) or {}).get(market)
        return ("统一口径", 1.0, unified) if unified else None
    names = interface_names_of(source, market, kind)
    if not names:
        if _guard("unknown_unit_combo_must_raise", True):
            raise ValueError(
                f"未登记的单位口径组合 (source={source!r}, market={market!r}, kind={kind!r})："
                "必须在 config.SOURCE_INTERFACE_MAP 登记接口名；禁止默认按 ×1 处理")
        return None
    units = getattr(config, "DATA_SOURCE_UNITS", None) or {}
    if _guard("unit_table_interface_names_verified", True):
        missing = [n for n in names if n not in units]
        if missing:
            raise ValueError(
                f"SOURCE_INTERFACE_MAP({source},{market},{kind}) 引用了 "
                f"DATA_SOURCE_UNITS 中不存在的接口：{missing}")
    spec = units.get(names[0])
    if spec is None:
        return None
    return (spec.get("volume"), float(spec.get("volume_factor", 1.0)),
            spec.get("unified_volume"))


def stamp_unified_units(df: Optional[pd.DataFrame], source: str, market: str,
                        kind: str) -> Optional[pd.DataFrame]:
    """适配器已返回统一口径时只补 attrs，禁止再乘系数。

    为什么不能靠 ``df.attrs`` 判断：parquet/csv 缓存不保留 attrs，命中缓存后
    「已归一」的信息会丢，再按源原始单位乘一次就会把 A 股成交量放大 100 倍。
    因此由适配器显式声明 ``returns_unified_units=True``，不依赖帧上的痕迹。
    """
    if df is None:
        return df
    spec = volume_unit_of(source, market, kind)
    unit = spec[2] if spec else None
    if unit is None:
        df.attrs.setdefault("volume_unit_declared", False)
        return df
    df.attrs.setdefault("volume_unit", unit)
    df.attrs["volume_unit_source"] = df.attrs.get("volume_unit") or unit
    df.attrs["volume_unit_multiplier"] = 1.0
    df.attrs["volume_unit_normalized"] = True
    df.attrs["volume_unit_declared"] = True
    df.attrs["unit_pre_normalized_by_data_layer"] = True
    return df


def normalize_frame_units(df: Optional[pd.DataFrame], source: str, market: str,
                          kind: str) -> Optional[pd.DataFrame]:
    """把 volume 归一到项目统一口径并写 attrs。

    两条路径必须分清（否则量会被放大 100 倍）：
    - 帧上已有 ``attrs['volume_unit']``：数据层 ``_normalize_units`` 已按
      ``config.DATA_SOURCE_UNITS`` 折算过，这里只复核留痕，**绝不重复乘系数**；
    - 帧上没有声明：按 ``SOURCE_INTERFACE_MAP`` → ``DATA_SOURCE_UNITS`` 折算一次。

    未登记的组合由 ``volume_unit_of`` 直接 raise（unknown_unit_combo_must_raise），
    宁可不取数，也不许按「股」猜。
    """
    if df is None:
        return df
    declared = df.attrs.get("volume_unit")
    if declared:
        df.attrs.setdefault("volume_unit_source",
                            df.attrs.get("source_volume_unit") or declared)
        df.attrs["volume_unit_normalized"] = True
        df.attrs["volume_unit_multiplier"] = 1.0
        df.attrs["volume_unit_declared"] = True
        df.attrs["unit_pre_normalized_by_data_layer"] = True
        return df
    spec = volume_unit_of(source, market, kind)
    if spec is None or spec[2] is None:
        df.attrs["volume_unit_declared"] = False
        return df
    unit, mult, unified = spec
    df.attrs["volume_unit"] = unified
    df.attrs["volume_unit_source"] = unit
    df.attrs["volume_unit_multiplier"] = mult
    df.attrs["volume_unit_normalized"] = True
    df.attrs["volume_unit_declared"] = True
    if not df.empty and "volume" in df.columns and mult != 1:
        out = df.copy()
        out["volume"] = pd.to_numeric(out["volume"], errors="coerce") * mult
        out.attrs.update(df.attrs)
        return out
    return df


def assert_field_consistency(frames: Dict[str, pd.DataFrame], market: str = "",
                            tolerance: float = 0.25) -> None:
    """跨源同一标的的 volume 必须同口径（已归一为「股」）。

    不同源的成交量本身会有小幅差异（集合竞价口径、尾盘撮合），故给 ±25% 容忍；
    但「手 / 股」差 100 倍会直接越界并被点名。禁止把两份不同口径拼在一起。
    """
    from core.gov_compat import gov
    if not gov("DATA_SOURCE_ADAPTER_GUARD").get("field_consistency_required", True):
        return
    items = [(name, df) for name, df in frames.items()
             if df is not None and not df.empty and "volume" in getattr(df, "columns", [])]
    if len(items) < 2:
        return
    base_name, base = items[0]
    for name, df in items[1:]:
        idx = base.index.intersection(df.index)
        if len(idx) == 0:
            continue
        a = pd.to_numeric(base.loc[idx, "volume"], errors="coerce")
        b = pd.to_numeric(df.loc[idx, "volume"], errors="coerce")
        mask = (a > 0) & (b > 0)
        if not mask.any():
            continue
        ratio = float(a[mask].sum() / b[mask].sum())
        if (1 - tolerance) <= ratio <= (1 + tolerance):
            continue
        hint = ""
        if 50 <= ratio <= 200 or 0.005 <= ratio <= 0.02:
            hint = "（疑似「手 / 股」未折算：1 手 = 100 股）"
        raise DataFieldInconsistencyError(
            f"[{market}] {base_name} 与 {name} 的 volume 口径冲突：合计比 {ratio:.4f}，"
            f"容忍区间 [{1 - tolerance:.2f}, {1 + tolerance:.2f}]{hint}；"
            "禁止静默拼接，先按 config.SOURCE_INTERFACE_MAP + DATA_SOURCE_UNITS 归一到统一口径")


# ==================== 数据源基类与四个实现 ====================

class BaseDataSource(ABC):
    """数据源适配器：只实现「怎么取」，不决定「取哪个」。"""

    name: str = "base"
    kinds: tuple = ("daily",)
    markets: tuple = ("*",)
    # 只有纯 HTTP 适配器允许放进线程做超时控制；BaoStock 会话绑定线程，禁止
    thread_safe_timeout: bool = False
    # dispatch 是否已按项目统一口径返回（data_fetcher._normalize_units 已折算）。
    # True → 路由只补 attrs，绝不再乘系数；False → 路由当作源原始单位折算一次。
    returns_unified_units: bool = False
    # 注意（v3.46）：这里【故意不提供】internal_failover 属性。是否「内部已有多级回退链」
    # 只能由 config.INTERNAL_FAILOVER_SOURCES 白名单决定；适配器自声明 = 被守卫对象给
    # 自己发豁免，被限流也会永不熔断，反复重连正是封 IP 的触发条件（13.0.17）。

    def supports(self, market: str, kind: str) -> bool:
        if kind not in self.kinds:
            return False
        return "*" in self.markets or market in self.markets

    def is_configured(self) -> bool:
        return True

    def unavailable_reason(self) -> str:
        return ""

    @abstractmethod
    def fetch(self, kind: str, symbol: str, market: str, start: str, end: str,
              **kwargs) -> pd.DataFrame:
        """取数；失败抛异常，空数据返回空表（空 ≠ 坏，由路由区分）。"""

    def health_check(self) -> bool:
        return self.is_configured()


class AkshareSource(BaseDataSource):
    """akshare 适配器：dispatch 由上层注入（本模块不直接依赖 akshare）。"""

    name = "akshare"
    kinds = ("daily", "minute")
    thread_safe_timeout = True

    def __init__(self, dispatch: Optional[Callable[..., pd.DataFrame]] = None):
        self._dispatch = dispatch

    def is_configured(self) -> bool:
        return self._dispatch is not None

    def unavailable_reason(self) -> str:
        return "akshare dispatch 未注入" if self._dispatch is None else ""

    def fetch(self, kind, symbol, market, start, end, **kwargs) -> pd.DataFrame:
        if self._dispatch is None:
            raise SourceUnavailableError("akshare dispatch 未注入")
        return self._dispatch(kind=kind, symbol=symbol, market=market,
                              start=start, end=end, **kwargs)

    def health_check(self) -> bool:
        return self._dispatch is not None


class BaostockSource(BaseDataSource):
    """BaoStock 适配器：会话绑定线程，超时控制走调用侧而非线程池。"""

    name = "baostock"
    kinds = ("daily", "minute")
    thread_safe_timeout = False

    def __init__(self, dispatch: Optional[Callable[..., pd.DataFrame]] = None,
                 probe: Optional[Callable[[], bool]] = None):
        self._dispatch = dispatch
        self._probe = probe

    def is_configured(self) -> bool:
        return self._dispatch is not None

    def unavailable_reason(self) -> str:
        return "baostock dispatch 未注入" if self._dispatch is None else ""

    def supports(self, market: str, kind: str) -> bool:
        # BaoStock 只有 A 股（含指数）日线/分钟线
        return super().supports(market, kind) and market in ("cn_stock", "cn_index")

    def fetch(self, kind, symbol, market, start, end, **kwargs) -> pd.DataFrame:
        if self._dispatch is None:
            raise SourceUnavailableError("baostock dispatch 未注入")
        return self._dispatch(kind=kind, symbol=symbol, market=market,
                              start=start, end=end, **kwargs)

    def health_check(self) -> bool:
        if self._probe is not None:
            try:
                return bool(self._probe())
            except Exception:  # noqa: BLE001 - 探活失败即不可用
                return False
        return self._dispatch is not None


class TushareSource(BaseDataSource):
    """Tushare：无 token 时不是「坏源」，而是「未配置」——必须跳过而非报错阻断。"""

    name = "tushare"
    kinds = ("daily",)
    markets = ("cn_stock",)

    def __init__(self, token: str = None,
                 dispatch: Optional[Callable[..., pd.DataFrame]] = None):
        self.token = config.TUSHARE_TOKEN if token is None else token
        self._dispatch = dispatch

    def is_configured(self) -> bool:
        return bool(str(self.token or "").strip()) and self._dispatch is not None

    def unavailable_reason(self) -> str:
        if not str(self.token or "").strip():
            return "未配置 TUSHARE_TOKEN（tokenless_sources_first=True → 跳过，不阻断链路）"
        return "tushare dispatch 未注入"

    def fetch(self, kind, symbol, market, start, end, **kwargs) -> pd.DataFrame:
        if not str(self.token or "").strip():
            raise SourceUnavailableError(self.unavailable_reason())
        if self._dispatch is None:
            raise SourceUnavailableError("tushare dispatch 未注入")
        return self._dispatch(kind=kind, symbol=symbol, market=market,
                              start=start, end=end, **kwargs)

    def health_check(self) -> bool:
        return self.is_configured()


class LocalSource(BaseDataSource):
    """本地兜底：读本地缓存。reader 返回空表即「本地无数据」。"""

    name = "local"
    kinds = ("daily", "minute")
    markets = ("*",)

    def __init__(self, reader: Optional[Callable[..., pd.DataFrame]] = None):
        self._reader = reader

    def is_configured(self) -> bool:
        return self._reader is not None

    def fetch(self, kind, symbol, market, start, end, **kwargs) -> pd.DataFrame:
        if self._reader is None:
            return pd.DataFrame()
        return self._reader(kind=kind, symbol=symbol, market=market,
                            start=start, end=end, **kwargs)


# ==================== 路由器 ====================

def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


class DataRouter:
    """按 data_source_priority 顺序取数，并执行 6 个 fail-closed 闸门。"""

    def __init__(self, sources: List[BaseDataSource], *,
                 priority: List[str] = None,
                 timeout: float = None,
                 health_file: str = None,
                 notifier: Callable[[str, str, str], object] = None,
                 local_name: str = "local",
                 trading_day_probe: Callable[..., bool] = None,
                 listing_probe: Callable[..., Optional[dict]] = None):
        # v3.47：索引桥覆盖面必须等于支持清单（缺一个组合就 raise，不等到运行时才发现）
        assert_map_scope_covers_supported_scope()
        from core.gov_compat import gov
        guard = gov("DATA_SOURCE_ADAPTER_GUARD")
        whitelist = tuple(getattr(config, "INTERNAL_FAILOVER_SOURCES", None) or ())
        for src in sources:
            # v3.46：被守卫对象不得自声明「内部已有回退链」。自声明 = 自己给自己发豁免，
            # 会让被墙/被限流的源永不熔断，反复重连 → 封 IP。
            if getattr(src, "internal_failover", False) and src.name not in whitelist:
                raise ValueError(
                    f"数据源 {src.name!r} 自声明 internal_failover=True，但不在 "
                    f"config.INTERNAL_FAILOVER_SOURCES{whitelist} 白名单内；"
                    "该标记只能由 config 决定，适配器不得自声明")
        self.sources: Dict[str, BaseDataSource] = {s.name: s for s in sources}
        # v3.46：本地兜底是路由器的职责，不是调用方的。缺 LocalSource 直接拒绝构造，
        # 否则直调 DataRouter.fetch 的新路径（watch_only / 监控）会没有兜底。
        if guard.get("router_must_hold_local_source", True) and local_name not in self.sources:
            raise ValueError(
                f"DataRouter 缺少本地兜底源 {local_name!r}："
                "router_must_hold_local_source=True，兜底必须由路由器持有，不得甩给调用方")
        from core.gov_compat import gov
        conf = gov("DATA_LONG_TERM")
        self.priority = list(priority or conf.get("data_source_priority")
                             or ["akshare", "baostock", "tushare", "local"])
        # 未登记的源追加到尾部：宁可多试一个，也不要因配置漏写而整条链路消失
        self.priority += [n for n in self.sources if n not in self.priority]
        self.timeout = float(timeout if timeout is not None
                             else conf.get("source_timeout_seconds", 15) or 0)
        self.local_name = local_name
        self.trading_day_probe = trading_day_probe
        # v3.47：合法空的唯一证据源（独立证券主数据），取数层不得自证
        self.listing_probe = listing_probe
        self.health_file = Path(health_file or conf.get("source_health_file")
                                or "data_cache/source_health.json")
        if not self.health_file.is_absolute():
            self.health_file = Path(getattr(config, "BASE_DIR", Path.cwd())) / self.health_file
        self._notifier = notifier
        self._skip_logged: set = set()
        self._state = self._load_state()

    # ---------- 闸门配置 ----------

    @staticmethod
    def _conf(key: str, default=None):
        from core.gov_compat import gov
        return gov("DATA_LONG_TERM").get(key, default)

    # ---------- 状态持久化 ----------

    def _load_state(self) -> dict:
        state = {"updated_at": None, "sources": {}}
        try:
            if self.health_file.exists():
                raw = json.loads(self.health_file.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and isinstance(raw.get("sources"), dict):
                    state = {"updated_at": raw.get("updated_at"),
                             "sources": raw["sources"]}
        except Exception as exc:  # noqa: BLE001 - 健康档案损坏按「全新鲜」重建，不阻断取数
            logger.warning("[router] 健康档案 %s 读取失败(%s)，按全新状态处理",
                           self.health_file, exc)
        return state

    def _save_state(self) -> None:
        try:
            self.health_file.parent.mkdir(parents=True, exist_ok=True)
            self._state["updated_at"] = _now_iso()
            self.health_file.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - 落盘失败不能阻断取数
            logger.warning("[router] 健康档案落盘失败 %s: %s", self.health_file, exc)

    def _src_state(self, name: str) -> dict:
        st = self._state["sources"].setdefault(name, {})
        st.setdefault("consecutive_failures", 0)
        st.setdefault("unhealthy", False)
        st.setdefault("last_error", "")
        st.setdefault("last_success", "")
        st.setdefault("last_check", "")
        return st

    def load_health(self) -> dict:
        return self._load_state()

    def is_unhealthy(self, name: str) -> bool:
        return bool(self._src_state(name).get("unhealthy"))

    # ---------- 失败计数 / 恢复 ----------

    def _is_internal_failover(self, name: str) -> bool:
        """是否「内部已有多级回退链」——只认 config 白名单，不认适配器自声明。"""
        return name in tuple(getattr(config, "INTERNAL_FAILOVER_SOURCES", None) or ())

    @staticmethod
    def _is_declared_single_source(market: str, kind: str) -> bool:
        """该市场是否被 config 声明为单点故障市场（只有一个源，失败即市场级不可用）。"""
        conf = getattr(config, "SINGLE_SOURCE_MARKETS", None) or {}
        return market in (conf.get(kind) or [])

    def _record_failure(self, name: str, exc: Exception) -> None:
        st = self._src_state(name)
        st["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
        # v3.46 分层计数：市场级不可用由调用处豁免（不进本函数）；凡是进到这里的
        # 都是【源级失效】（被墙/被限流/超时/协议错），必须计数——哪怕该源内部还有
        # 多级回退链。永不熔断 = 反复重连 = 封 IP 的触发条件。
        st["consecutive_failures"] = int(st.get("consecutive_failures", 0)) + 1
        limit = int(self._conf("max_consecutive_failures", 3) or 3)
        if st["consecutive_failures"] >= limit and not st["unhealthy"]:
            st["unhealthy"] = True
            logger.error("[router] %s 连续失败 %d 次（阈值 %d），标记 unhealthy，"
                         "后续路由跳过；待 health_check() 探活通过后恢复",
                         name, st["consecutive_failures"], limit)
        elif self._is_internal_failover(name):
            logger.info("[router] %s 内部回退链仍失败（源级失效，已计数 %d/%d）",
                        name, st["consecutive_failures"], limit)
        self._save_state()

    def _record_success(self, name: str) -> None:
        st = self._src_state(name)
        changed = st.get("consecutive_failures") or st.get("unhealthy")
        st["consecutive_failures"] = 0
        st["unhealthy"] = False
        st["last_success"] = _now_iso()
        if changed:
            self._save_state()

    def _notify_failover(self, failed: str, succeeded: str, exc: Exception) -> None:
        if not self._conf("failover_log_required", True):
            return
        msg = (f"主源 {failed} 不可用（{type(exc).__name__}: {exc}）→ 已切换到 {succeeded}")
        logger.warning("[router] 数据源切换：%s", msg)
        try:
            if self._notifier is not None:
                self._notifier("数据源切换", msg, "warning")
            else:
                from core import notifier as _notifier_mod
                for n in _notifier_mod.create_notifiers():
                    n.send("数据源切换", msg, level="warning")
        except Exception as notify_exc:  # noqa: BLE001 - 通知失败不能阻断取数
            logger.warning("[router] 切换告警推送失败：%s", notify_exc)

    # ---------- 主入口 ----------

    def fetch(self, kind: str, symbol: str, market: str, start: str, end: str,
              **kwargs) -> pd.DataFrame:
        """按优先级取数；失败/空/超时自动切换；全部失败后走本地兜底。"""
        order = [n for n in self.priority if n in self.sources]
        remote = [n for n in order if n != self.local_name]
        errors: List[tuple] = []
        empties: List[str] = []
        primary = None
        tokenless_skipped: List[str] = []
        skipped_unhealthy: List[str] = []

        for name in remote:
            src = self.sources[name]
            if not src.supports(market, kind):
                continue
            if not src.is_configured():
                reason = src.unavailable_reason() or "未配置"
                if self._conf("tokenless_sources_first", True) and name not in self._skip_logged:
                    # 未配置是常态（无 token），只在首次提示，避免每次取数刷日志
                    logger.info("[router] 跳过 %s：%s", name, reason)
                    self._skip_logged.add(name)
                tokenless_skipped.append(name)
                continue
            if self.is_unhealthy(name):
                logger.warning("[router] %s 处于 unhealthy，本次跳过（待探活恢复）", name)
                skipped_unhealthy.append(name)
                continue
            try:
                df = self._call_with_timeout(src, kind, symbol, market, start, end, **kwargs)
            except SourceUnavailableError as exc:
                logger.info("[router] 跳过 %s：%s", name, exc)
                tokenless_skipped.append(name)
                continue
            except DataUnavailableError as exc:
                # 市场级不可用（单点故障市场内部已判定无源）：不是「这个源坏了」，
                # 不得累计到 akshare 的连续失败上，否则会把整条 A 股链路一起拖死。
                logger.warning("[router] %s 对 [%s] 判定市场不可用：%s", name, market, exc)
                errors.append((name, exc))
                continue
            except Exception as exc:  # noqa: BLE001 - 单源失败必须切换
                if "该市场当前无可用数据源" in str(exc):
                    # 老链路抛的是 RuntimeError，文案同义：同样按市场级不可用处理
                    logger.warning("[router] %s 对 [%s] 判定市场不可用：%s", name, market, exc)
                    errors.append((name, exc))
                    continue
                if self._is_declared_single_source(market, kind):
                    # 分层计数第二层：单点故障市场（config.SINGLE_SOURCE_MARKETS）只声明了
                    # 这一个源，失败即「该市场不可用」，属市场级失效；若记到源级健康上，
                    # 会把同源的其它市场（A 股日线）整条链路一起拖死。
                    logger.warning("[router] %s 对单点市场 [%s] 失败（市场级，不计源健康）：%s",
                                   name, market, exc)
                    errors.append((name, exc))
                    continue
                errors.append((name, exc))
                self._record_failure(name, exc)
                continue
            if df is None or df.empty:
                # 空 ≠ 坏，但「空」无权自证合法（v3.47）：被限流的源正是「返回空」的表形，
                # 采信取数层写的 empty_reason 等于让被守卫者自己签退市证明。
                empties.append(name)
                if (getattr(df, "attrs", None) or {}).get("empty_reason"):
                    logger.warning(
                        "[router] %s 对 [%s] %s 返回自带 empty_reason，已忽略："
                        "空因只能由独立证券主数据出具（empty_evidence_only_from_security_master）",
                        name, market, symbol)
                continue
            df = (stamp_unified_units(df, name, market, kind)
                  if src.returns_unified_units
                  else normalize_frame_units(df, name, market, kind))
            df.attrs.setdefault("source_adapter", name)
            if primary is not None or errors:
                failed = primary or errors[0][0]
                self._notify_failover(failed, name, errors[0][1] if errors else RuntimeError("返回空表"))
            primary = name
            self._record_success(name)
            return df

        # 远程全挂 → 本地兜底（local_fallback_must_exist）
        local = self.sources.get(self.local_name)
        if local is not None and local.supports(market, kind) and local.is_configured():
            try:
                df = local.fetch(kind=kind, symbol=symbol, market=market, start=start, end=end)
            except Exception as exc:  # noqa: BLE001 - 本地读失败按无兜底处理
                logger.warning("[router] 本地兜底读取失败：%s", exc)
                df = None
            if df is not None and not df.empty:
                df = (stamp_unified_units(df, self.local_name, market, kind)
                      if local.returns_unified_units
                      else normalize_frame_units(df, self.local_name, market, kind))
                df.attrs.setdefault("source_adapter", self.local_name)
                df.attrs["router_local_fallback"] = True
                logger.warning("[router] [%s] %s %s 全部远程源不可用，已回退本地缓存",
                               market, symbol, kind)
                return df

        # 「已尝试」必须含「返回空表」的源，否则净空报错会显示「已尝试 无」误导排查
        tried = "、".join(dict.fromkeys(
            [n for n, _ in errors] + tokenless_skipped + skipped_unhealthy + empties)) or "无"
        if (errors or skipped_unhealthy) and self._conf("local_fallback_must_exist", True):
            detail = "；".join(f"{n}: {type(e).__name__}: {e}" for n, e in errors)
            unhealthy_note = (f"；{len(skipped_unhealthy)} 个源处于 unhealthy（"
                              f"{'、'.join(skipped_unhealthy)}）" if skipped_unhealthy else "")
            raise DataUnavailableError(
                f"[{market}] {symbol} {kind} 全部远程源失败（已尝试 {tried}），"
                f"且本地无兜底数据：该市场当前无可用数据源{unhealthy_note}。明细：{detail}")
        if errors or skipped_unhealthy:
            # 不强制本地兜底时保留最后一个异常语义，禁止降级成空表
            raise DataUnavailableError(
                f"[{market}] {symbol} {kind} 全部远程源失败（{tried}）："
                f"该市场当前无可用数据源")
        # ---------- 全远程净空：合法空只能由独立证券主数据证明 ----------
        # 病态：「在不在市」若从「取数返回空」反推，被限流的源只要被标成退市，
        # 净空闸门就被绕过。因此证据必须来自 security_master，且带 as_of 过时点闸门。
        evidence = self._listing_evidence(market, symbol, end)
        if evidence is not None and not evidence.get("listed", True):
            out = pd.DataFrame()
            out.attrs["router_all_empty"] = empties
            out.attrs["empty_evidence"] = evidence
            out.attrs["empty_reason"] = evidence.get("reason") or ""
            out.attrs["empty_reason_source"] = evidence.get("source") or ""
            out.attrs["source_adapter"] = "none"
            logger.info("[router] [%s] %s %s 全部源为空，证券主数据判定不在市"
                        "（as_of=%s，provider=%s），按合法无数据返回",
                        market, symbol, kind, evidence.get("as_of"),
                        evidence.get("provider") or evidence.get("source"))
            return out
        # ---------- 在市或取证失败 + 净空：必须带探活证据，禁止把「故障空」当「合法空」----
        # 被限流的源常常返回空表而不抛异常，与「今天真的没数据」在实现上不可区分；
        # 没有证据就放行 = 标的静默失效。应交易日净空必须升级为异常。
        evidence = self._probe_trading_day(market, end)
        if self._conf("router_all_empty_requires_probe_evidence", True):
            if evidence is None:
                raise DataUnavailableError(
                    f"[{market}] {symbol} {kind} 全部源返回空表，且无交易日探活证据"
                    f"（trading_day_probe 未注入或异常）：无法区分「非交易日」与"
                    f"「被限流返回空」，禁止当作合法空返回。已尝试 {tried}")
            if evidence and self._conf("expected_trading_day_empty_must_raise", True):
                raise DataUnavailableError(
                    f"[{market}] {symbol} {kind} 在应交易日 {end} 全部源净空"
                    f"（已尝试 {tried}）：标的疑似静默失效或被限流，"
                    "禁止当作「今天没数据」放行")
        # 有证据证明非交易日：合法无数据，返回空表但标注证据
        out = pd.DataFrame()
        out.attrs["router_all_empty"] = empties
        out.attrs["probe_evidence"] = "non_trading_day"
        out.attrs["source_adapter"] = "none"
        return out

    def _listing_evidence(self, market: str, symbol: str, as_of) -> Optional[dict]:
        """向独立证券主数据取证：唯一可判定「合法空」的来源（v3.47）。

        三条硬约束（config.EMPTY_REASON_PROVENANCE）：来源必须在 ``allowed_sources``
        白名单内；必须带 ``as_of``；``as_of`` 必须等于本次决策时点（时点闸门），
        否则拿「今天在市」去判「历史区间为空」就是结构性未来函数。
        任何一条不满足都返回 ``None`` = 无证据，由调用方走探活/raise，禁止猜。
        """
        if not _guard("empty_evidence_only_from_security_master", True):
            return None
        probe = self.listing_probe
        if probe is None:
            return None
        from core.gov_compat import gov
        conf = gov("EMPTY_REASON_PROVENANCE")
        # v3.48：日期归一是闸门入口硬前置（as_of_normalization_required）——
        # "20261118" 与 "2026-11-18" 字符串直比不等的真缺陷不许靠调用方自觉规避。
        if _guard("as_of_normalization_required", True):
            as_of = _norm_day(as_of)
        try:
            evidence = probe(market, symbol, as_of)
        except Exception as exc:  # noqa: BLE001 - 主数据不可达 = 无证据；禁止回退行情源反推
            logger.warning("[router] [%s] %s 证券主数据探针不可达（%s）：按无证据处理，"
                           "listing_probe_unavailable_must_raise 链路接管，"
                           "禁止回退行情源（forbid_fallback_to_market_source）",
                           market, symbol, exc)
            return None
        if not isinstance(evidence, dict):
            return None
        allowed = tuple(conf.get("allowed_sources") or ())
        if allowed and evidence.get("source") not in allowed:
            logger.warning("[router] [%s] %s 空证据来源 %r 不在白名单 %s，按无证据处理",
                           market, symbol, evidence.get("source"), list(allowed))
            return None
        if conf.get("must_carry_as_of", True) and not evidence.get("as_of"):
            logger.warning("[router] [%s] %s 空证据缺 as_of，按无证据处理", market, symbol)
            return None
        if conf.get("pit_gate_required", True):
            want, got = _norm_day(as_of), _norm_day(evidence.get("as_of"))
            if want and got != want:
                logger.warning("[router] [%s] %s 空证据 as_of=%s 与决策时点 %s 不一致，"
                               "按无证据处理", market, symbol, got, want)
                return None
        return evidence

    def _probe_trading_day(self, market: str, end) -> Optional[bool]:
        """交易日探活：True=应开市 / False=休市 / None=拿不到证据。"""
        probe = self.trading_day_probe
        if probe is None:
            return None
        try:
            return bool(probe(end, market))
        except TypeError:
            try:
                return bool(probe(end))
            except Exception:  # noqa: BLE001 - 探活异常按「无证据」处理
                return None
        except Exception:  # noqa: BLE001
            return None

    def _call_with_timeout(self, src: BaseDataSource, kind: str, symbol: str,
                           market: str, start: str, end: str, **kwargs) -> pd.DataFrame:
        if self.timeout <= 0 or not src.thread_safe_timeout:
            return src.fetch(kind=kind, symbol=symbol, market=market,
                             start=start, end=end, **kwargs)
        pool = ThreadPoolExecutor(max_workers=1)
        fut = pool.submit(src.fetch, kind, symbol, market, start, end, **kwargs)
        try:
            return fut.result(timeout=self.timeout)
        except _FutureTimeout as exc:
            fut.cancel()
            raise TimeoutError(
                f"{src.name} 超过 source_timeout_seconds={self.timeout:g}s 未返回") from exc
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    # ---------- 探活 ----------

    def health_check(self, names: List[str] = None) -> dict:
        """每日开盘前探活：结果写入 source_health_file；通过即解除 unhealthy。"""
        targets = names or list(self.sources)
        results = {}
        for name in targets:
            src = self.sources.get(name)
            if src is None:
                continue
            t0 = time.time()
            note = ""
            try:
                ok = bool(src.health_check())
            except Exception as exc:  # noqa: BLE001
                ok, note = False, f"{type(exc).__name__}: {exc}"
            st = self._src_state(name)
            st["last_check"] = _now_iso()
            st["healthy"] = ok
            if ok:
                st["unhealthy"] = False
                st["consecutive_failures"] = 0
            else:
                note = note or (src.unavailable_reason() or "探活失败")
            st["note"] = note
            results[name] = {"healthy": ok, "elapsed_sec": round(time.time() - t0, 3),
                             "note": note,
                             "consecutive_failures": st.get("consecutive_failures", 0)}
        self._save_state()
        return {"checked_at": _now_iso(), "file": str(self.health_file), "results": results}
