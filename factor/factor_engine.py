"""因子计算引擎（第 5 步 5.9.4 / 5.9.11）。

功能：
  * 输入股票池、日期范围、因子名列表（'alpha001' / 'alpha191_001' / 自定义注册名 /
    直接传函数），批量拉取 OHLCV + amount 面板；
  * 自动补全 vwap/returns 等字段（FactorData 内完成）；
  * 结果缓存到 data_cache/factors/*.parquet，相同参数直接读缓存；
  * 增量更新：缓存已有历史时，只补算新增交易日（带预热窗口）；
  * workers>1 时用线程池并行计算各因子（默认单进程）。

⚠️ 免费 Alpha101/191 与付费平台因子口径可能不同，不要混搭使用。
"""
from __future__ import annotations

import hashlib
import importlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

import config
from .base import FactorData, FACTOR_REGISTRY, build_factor_data
from .universe import resolve_universe

logger = logging.getLogger(__name__)

__all__ = ["FactorEngine", "create_factor_engine"]

_FIELDS = ("open", "high", "low", "close", "volume", "amount")


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name))


def _warmup_start(start: pd.Timestamp, days: int = 420) -> pd.Timestamp:
    return start - pd.Timedelta(days=days)


class FactorEngine:
    """因子计算引擎（免费内置 Alpha101/191 + 自定义因子）。"""

    def __init__(
        self,
        fetcher=None,
        cache_dir: Optional[Union[str, Path]] = None,
        adjust: str = "qfq",
        auto_import_custom: bool = True,
    ) -> None:
        self._fetcher = fetcher
        self.cache_dir = Path(cache_dir or (Path(config.DATA_CACHE_DIR) / "factors"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.adjust = adjust
        if auto_import_custom:
            try:  # 自定义因子统一写在 factor/custom.py，启动时自动注册
                from . import custom  # noqa: F401
            except Exception as exc:  # pragma: no cover
                logger.warning("导入 factor.custom 失败: %s", exc)

    # ---------------- 数据访问 ----------------
    @property
    def fetcher(self):
        if self._fetcher is None:
            from core.data_fetcher import DataFetcher  # 懒导入，避免无关依赖

            self._fetcher = DataFetcher()
        return self._fetcher

    def _fetch_panels(self, symbols: Sequence[str], start: str, end: str) -> FactorData:
        """批量拉取日线并拼成面板。"""
        buckets: Dict[str, List[pd.Series]] = {k: [] for k in _FIELDS}
        ok = 0
        for i, sym in enumerate(symbols, 1):
            try:
                df = self.fetcher.get_daily(sym, start_date=start, end_date=end,
                                            adjust=self.adjust)
            except Exception as exc:
                logger.warning("取数失败 %s: %s", sym, exc)
                continue
            if df is None or len(df) == 0:
                continue
            df = df.copy()
            df.index = pd.to_datetime(df.index)
            df = df[~df.index.duplicated(keep="last")].sort_index()
            for field in _FIELDS:
                if field in df.columns:
                    s = pd.to_numeric(df[field], errors="coerce").rename(str(sym))
                    buckets[field].append(s)
            ok += 1
            if i % 50 == 0:
                logger.info("因子引擎取数进度 %d/%d", i, len(symbols))
        if ok == 0:
            raise RuntimeError(
                f"股票池 {len(symbols)} 只全部取数失败；请检查网络/数据源/代码格式"
            )
        frames: Dict[str, pd.DataFrame] = {}
        for field, ser_list in buckets.items():
            if not ser_list:
                continue
            panel = pd.concat(ser_list, axis=1).sort_index()
            if panel.notna().sum().sum() == 0:
                continue
            frames[field] = panel
        if "close" not in frames:
            raise RuntimeError("取数结果缺少 close 字段，无法构造因子面板")
        return build_factor_data(frames)

    # ---------------- 因子解析 ----------------
    @staticmethod
    def _resolve_factor(name_or_func) -> Tuple[str, Callable[[FactorData], pd.DataFrame]]:
        if callable(name_or_func):
            return getattr(name_or_func, "__name__", "custom_factor"), name_or_func
        name = str(name_or_func).strip()
        if name in FACTOR_REGISTRY:
            return name, FACTOR_REGISTRY[name]
        m = re.fullmatch(r"alpha191[_-]?(\d{1,3})", name, flags=re.I)
        if m:
            from .alpha191 import get_builtin_alpha191

            return name, get_builtin_alpha191(int(m.group(1)))
        m = re.fullmatch(r"alpha[_-]?(\d{1,3})", name, flags=re.I)
        if m:
            from .alpha101 import get_builtin_alpha

            return name, get_builtin_alpha(int(m.group(1)))
        raise KeyError(
            f"未知因子 {name}；支持 alpha001、alpha191_001、已注册自定义因子或直接传函数"
        )

    # ---------------- 缓存 ----------------
    def _cache_path(self, factor_name: str, universe: Sequence[str]) -> Path:
        uh = hashlib.md5(",".join(sorted(map(str, universe))).encode("utf-8")).hexdigest()[:10]
        return self.cache_dir / f"{_safe_name(factor_name)}_{uh}.parquet"

    def _read_cache(self, path: Path) -> Optional[pd.DataFrame]:
        if not path.exists():
            return None
        try:
            df = pd.read_parquet(path)
            df.index = pd.to_datetime(df.index)
            df.columns = [str(c) for c in df.columns]
            return df.sort_index()
        except Exception as exc:
            logger.warning("读取因子缓存失败 %s: %s", path, exc)
            return None

    def _write_cache(self, path: Path, df: pd.DataFrame) -> None:
        try:
            df = df.sort_index()
            df.to_parquet(path)
        except Exception as exc:
            logger.warning("写入因子缓存失败 %s: %s", path, exc)

    # ---------------- 核心计算 ----------------
    def compute(
        self,
        factor_names: Sequence[Union[str, Callable]],
        universe: Union[str, Sequence[str]] = "all_a",
        start: Optional[str] = None,
        end: Optional[str] = None,
        workers: int = 1,
        force: bool = False,
        use_cache: bool = True,
    ) -> Dict[str, pd.DataFrame]:
        """批量计算因子，返回 {因子名: 日期×股票 DataFrame}。"""
        # v3.38：不在 compute 入口拦 PIT——分层判据在 resolve_universe 内部：
        # 显式代码列表放行（无幸存者偏差可防）；指数名必须 as_of + 点内快照。
        start_ts = pd.Timestamp(start or getattr(config, "DEFAULT_START", "2018-01-01"))
        end_ts = pd.Timestamp(end or pd.Timestamp.today().normalize())
        if end_ts < start_ts:
            raise ValueError(f"end={end_ts.date()} 早于 start={start_ts.date()}")
        # 13.0：股票池按会话起始日取点内成分股，禁止「当前成分股」进因子面板
        symbols = resolve_universe(universe, as_of=start_ts)
        if not symbols:
            raise ValueError("股票池为空")

        resolved = [self._resolve_factor(f) for f in factor_names]
        results: Dict[str, pd.DataFrame] = {}
        tasks_full: List[Tuple[str, Callable]] = []
        tasks_inc: List[Tuple[str, Callable, pd.DataFrame, pd.Timestamp]] = []

        for name, func in resolved:
            path = self._cache_path(name, symbols)
            cached = None if force or not use_cache else self._read_cache(path)
            if cached is not None and not cached.empty and self._cache_compatible(cached, symbols, start_ts):
                if cached.index.max() >= end_ts:
                    results[name] = cached.loc[start_ts:end_ts, symbols]
                    continue
                tasks_inc.append((name, func, cached, cached.index.max()))
            else:
                tasks_full.append((name, func))

        # 全量计算需要的面板
        if tasks_full:
            data_full = self._fetch_panels(symbols, str(_warmup_start(start_ts).date()),
                                           str(end_ts.date()))
            for name, values in self._run_tasks(
                [(n, f, data_full) for n, f in tasks_full], workers
            ).items():
                values = values.loc[values.index >= start_ts, symbols]
                results[name] = values
                if use_cache:
                    self._write_cache(self._cache_path(name, symbols), values)

        # 增量计算：带预热窗口，只追加缓存最后日期之后的新行
        if tasks_inc:
            inc_start = min(last for _, _, _, last in tasks_inc)
            data_inc = self._fetch_panels(symbols, str(_warmup_start(inc_start).date()),
                                          str(end_ts.date()))
            for name, values in self._run_tasks(
                [(n, f, data_inc) for n, f, _, _ in tasks_inc], workers
            ).items():
                cached = next(c for n, _, c, _ in tasks_inc if n == name)
                new = values.loc[values.index > cached.index.max(), symbols]
                merged = pd.concat([cached, new]).sort_index()
                merged = merged.loc[merged.index >= start_ts]
                results[name] = merged.loc[start_ts:end_ts, symbols]
                if use_cache:
                    self._write_cache(self._cache_path(name, symbols), merged)

        return {n: results[n] for n, _ in resolved}

    @staticmethod
    def _cache_compatible(cached: pd.DataFrame, symbols: Sequence[str],
                          start: pd.Timestamp) -> bool:
        if not set(map(str, symbols)).issubset(set(cached.columns)):
            return False
        return cached.index.min() <= start

    def _run_tasks(self, tasks, workers: int) -> Dict[str, pd.DataFrame]:
        out: Dict[str, pd.DataFrame] = {}

        def run(item):
            name, func, data = item
            res = func(data)
            if not isinstance(res, pd.DataFrame):
                raise TypeError(f"因子 {name} 必须返回 DataFrame")
            res = res.replace([np.inf, -np.inf], np.nan)
            return name, res

        if workers and workers > 1:
            with ThreadPoolExecutor(max_workers=int(workers)) as ex:
                futures = {ex.submit(run, t): t[0] for t in tasks}
                for fut in as_completed(futures):
                    name, res = fut.result()
                    out[name] = res
        else:
            for t in tasks:
                name, res = run(t)
                out[name] = res
        return out

    def get_factor(
        self,
        factor_name: Union[str, Callable],
        universe: Union[str, Sequence[str]] = "all_a",
        start: Optional[str] = None,
        end: Optional[str] = None,
        **kwargs,
    ) -> pd.DataFrame:
        """取单个因子面板的便捷方法。"""
        key = factor_name if isinstance(factor_name, str) else getattr(factor_name, "__name__", "custom_factor")
        return self.compute([factor_name], universe=universe, start=start, end=end, **kwargs)[key]


def create_factor_engine(source: str = "free", **kwargs):
    """按数据源创建因子引擎。

    source='free'（默认）返回内置 Alpha101/191 的 FactorEngine；
    其它 source 懒加载 factor/adapters/<source>_factor.py。
    适配器不存在时抛出带安装/配置说明的 ImportError。
    """
    src = (source or "free").lower()
    if src in ("free", "builtin", "alpha", "local"):
        return FactorEngine(**kwargs)
    mod_name = f"factor.adapters.{src}_factor"
    try:
        mod = importlib.import_module(mod_name)
    except ImportError as exc:
        raise ImportError(
            f"未找到 {src} 因子适配器（{mod_name}）。免费因子请用 source='free'；"
            f"付费适配器需要先在 factor/adapters/ 下实现并安装对应 SDK"
            f"（tushare / jqdatasdk / uqer / qlib），原始错误: {exc}"
        ) from exc
    for attr in ("create_adapter", "create_factor_adapter", f"{src.title()}Factor",
                 "TushareFactor", "JoinQuantFactor", "UqerFactor", "QlibFactor"):
        obj = getattr(mod, attr, None)
        if callable(obj):
            try:
                return obj(**kwargs)
            except TypeError:
                return obj()
    raise ImportError(
        f"{mod_name} 存在，但没有找到 create_adapter/适配器类；"
        "请统一实现 get_factor(factor_name, symbols, start_date, end_date) 接口"
    )
