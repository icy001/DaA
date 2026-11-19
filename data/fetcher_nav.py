# -*- coding: utf-8 -*-
"""净值型资产数据层（data/fetcher_nav.py）

覆盖第 10 步 10.2：私募证券基金 / 券商资管·信托 / 公募 REITs / 新三板。

硬约束
======
1. **净值频率与披露滞后必须显式返回**：每份净值帧都带
   ``attrs["frequency"]``（daily/weekly/monthly）与
   ``attrs["disclosure_lag_days"]``（读 ``config.NAV_PRODUCT_CONFIG``），
   下游 NavBacktester 用它在 ``decision_date >= nav_date + lag`` 上做闸门。
2. **取不到就报错**：公开接口不可用 / 无数据时抛 :class:`NavDataUnavailableError`，
   禁止静默返回空 DataFrame（沿用第 1 步「单点故障市场不得静默留空」的规则）。
3. **出网统一出口**：所有外部调用经 :meth:`NavFetcher._call_source` 单一函数，
   带来源标识、超时、重试与 ≥0.3s 间隔限速，禁止在多处各自 requests。
4. **缓存**：CSV 落 ``data_cache/nav/{market}_{code}_{freq}.csv``，文件名含市场与代码，
   避免不同产品互相覆盖。
5. **单位/口径如实标注**：REITs 场内价来自东财（价格单位元），新三板成交量为股；
   无法确认时在 ``attrs["unit_uncertain"]`` 标注。
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

import config

__all__ = [
    "NavDataUnavailableError",
    "NavFetcher",
    "detect_frequency",
    "normalize_nav_frame",
]

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data_cache") / "nav"

# 频率判定：相邻披露间隔（自然日）中位数
_FREQUENCY_BUCKETS = ((2.5, "daily"), (10.0, "weekly"), (45.0, "monthly"))

# 各市场默认披露滞后（天）；未被 NAV_PRODUCT_CONFIG 覆盖时兜底
_DEFAULT_LAG = {"private_fund": 2, "qii_product": 2, "trust_plan": 2,
                "cn_reits": 1, "neeq": 1}


class NavDataUnavailableError(RuntimeError):
    """净值型数据不可用——显式报错，禁止静默返回空表。"""


def detect_frequency(index) -> str:
    """按相邻披露日间隔中位数判定 daily / weekly / monthly。"""
    stamps = pd.to_datetime(pd.Index(index)).sort_values()
    if len(stamps) < 3:
        return "weekly"
    gaps = pd.Series(stamps[1:] - stamps[:-1]).dt.days.median()
    for threshold, label in _FREQUENCY_BUCKETS:
        if gaps <= threshold:
            return label
    return "monthly"


def normalize_nav_frame(frame: pd.DataFrame, source: str = "manual",
                        product_type: str = None) -> pd.DataFrame:
    """标准化为 ``date | nav | accum_nav | source``，并写入频率/滞后元信息。"""
    if frame is None or len(frame) == 0:
        raise NavDataUnavailableError("净值数据为空：拒绝返回空表（禁止静默留空）")
    df = pd.DataFrame(frame).copy()
    date_col = next((c for c in ("date", "日期", "Date") if c in df.columns), None)
    nav_col = next((c for c in ("nav", "单位净值", "unit_nav", "close") if c in df.columns), None)
    if date_col is None or nav_col is None:
        raise NavDataUnavailableError(
            f"净值表缺少日期或净值列（需 date/nav），实际列：{list(df.columns)}")
    out = pd.DataFrame({
        "date": pd.to_datetime(df[date_col]).dt.normalize(),
        "nav": pd.to_numeric(df[nav_col], errors="coerce"),
        "accum_nav": pd.to_numeric(
            df.get("accum_nav", df.get("累计净值", df.get("accumulated_nav", df[nav_col]))),
            errors="coerce"),
        "source": str(source),
    }).dropna(subset=["nav"])
    out = out[out["nav"] > 0].sort_values("date").drop_duplicates("date").reset_index(drop=True)
    if out.empty:
        raise NavDataUnavailableError("净值列全部无效（<=0 或非数值）")
    frequency = detect_frequency(out["date"])
    lag = int((config.NAV_PRODUCT_CONFIG.get("disclosure_lag_days") or {}).get(
        str(product_type or ""), _DEFAULT_LAG.get(str(product_type or ""), 2)))
    out.attrs["frequency"] = frequency
    out.attrs["disclosure_lag_days"] = lag
    out.attrs["product_type"] = product_type
    out.attrs["source"] = str(source)
    return out


class NavFetcher:
    """净值型资产取数器（单点失败显式报错 + CSV 缓存 + 统一出网）。"""

    def __init__(self, cache_dir=None, min_interval: float = 0.3,
                 timeout: float = 15.0, retries: int = 2,
                 logger_: logging.Logger = None) -> None:
        self.cache_dir = Path(cache_dir or CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = float(min_interval)
        self.timeout = float(timeout)
        self.retries = int(retries)
        self.logger = logger_ or logger
        self._last_call = 0.0

    # ------------------------------------------------------------------
    # 统一出网出口（全模块唯一）
    # ------------------------------------------------------------------
    def _call_source(self, source: str, fn, *args, **kwargs):
        """所有外部取数的唯一出口：限速 + 超时 + 重试 + 来源标识。"""
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        last_exc = None
        for attempt in range(self.retries + 1):
            try:
                result = fn(*args, **kwargs)
                self._last_call = time.monotonic()
                return result
            except Exception as exc:          # noqa: BLE001 - 统一转换为显式错误
                last_exc = exc
                self.logger.warning("[%s] 第 %d 次取数失败：%s", source, attempt + 1, exc)
                time.sleep(min(self.min_interval * (attempt + 1), 2.0))
        raise NavDataUnavailableError(
            f"数据源 {source} 不可用（已重试 {self.retries} 次）：{last_exc}")

    # ------------------------------------------------------------------
    # 缓存
    # ------------------------------------------------------------------
    def _cache_path(self, market: str, code: str, freq: str = None) -> Path:
        suffix = f"_{freq}" if freq else ""
        return self.cache_dir / f"{market}_{code}{suffix}.csv"

    def _read_cache(self, market: str, code: str, freq: str = None) -> Optional[pd.DataFrame]:
        path = self._cache_path(market, code, freq)
        if not path.exists():
            return None
        frame = pd.read_csv(path)
        return normalize_nav_frame(frame, source=f"cache:{path.name}", product_type=market)

    def _write_cache(self, market: str, code: str, frame: pd.DataFrame,
                     freq: str = None) -> None:
        path = self._cache_path(market, code, freq)
        frame[["date", "nav", "accum_nav", "source"]].to_csv(path, index=False)

    # ------------------------------------------------------------------
    # 1) 私募证券基金 / 2) 资管·信托
    # ------------------------------------------------------------------
    def manual_nav_import(self, csv_path, product_type: str = "private_fund",
                          code: str = None, write_cache: bool = True) -> pd.DataFrame:
        """导入用户自建净值 CSV（date, nav, accum_nav）；私募净值不公开时的唯一合法入口。"""
        path = Path(csv_path)
        if not path.exists():
            raise NavDataUnavailableError(f"净值 CSV 不存在：{path}")
        frame = normalize_nav_frame(pd.read_csv(path), source=f"manual:{path.name}",
                                    product_type=product_type)
        if write_cache and code:
            self._write_cache(product_type, str(code), frame)
        return frame

    def fetch_private_fund_nav(self, code: str, csv_path=None) -> pd.DataFrame:
        """私募净值：公开接口失败时必须显式报错并提示改用 CSV 导入。"""
        cached = self._read_cache("private_fund", str(code))
        if cached is not None:
            return cached
        if csv_path:
            return self.manual_nav_import(csv_path, product_type="private_fund", code=code)
        try:
            import akshare as ak
        except ImportError as exc:
            raise NavDataUnavailableError(
                "未安装 akshare，无法查询私募备案净值；请使用 manual_nav_import(csv_path) 导入"
            ) from exc
        frame = self._call_source("akshare:fund_private_equity_amac_fund_info",
                                  ak.fund_private_equity_amac_fund_info)
        if frame is None or getattr(frame, "empty", True):
            raise NavDataUnavailableError(
                f"私募基金 {code} 公开接口无净值（私募净值不强制披露），"
                "请使用 manual_nav_import(csv_path) 导入自建净值 CSV")
        out = normalize_nav_frame(frame, source="akshare:amac", product_type="private_fund")
        self._write_cache("private_fund", str(code), out)
        return out

    def fetch_qii_product_nav(self, code: str, product_type: str = "mixed",
                              csv_path=None) -> pd.DataFrame:
        """券商资管/信托/私募理财净值：公开接口不可用即报错，不静默留空。"""
        cached = self._read_cache("qii_product", str(code))
        if cached is not None:
            cached.attrs["product_category"] = product_type
            return cached
        if csv_path:
            frame = self.manual_nav_import(csv_path, product_type="qii_product", code=code)
            frame.attrs["product_category"] = product_type
            return frame
        raise NavDataUnavailableError(
            f"资管/信托产品 {code}（{product_type}）无公开净值接口，"
            "请使用 manual_nav_import(csv_path) 导入；禁止返回空表")

    # ------------------------------------------------------------------
    # 3) 公募 REITs
    # ------------------------------------------------------------------
    def fetch_reits_daily(self, symbol: str) -> pd.DataFrame:
        """REITs 场内行情（日频），列：date|open|high|low|close|volume。"""
        cached = self._read_cache("cn_reits", str(symbol), "daily")
        if cached is not None:
            return cached
        try:
            import akshare as ak
        except ImportError as exc:
            raise NavDataUnavailableError("未安装 akshare，无法获取 REITs 行情") from exc
        frame = self._call_source("akshare:fund_reits_hist_em",
                                  ak.fund_reits_hist_em, symbol=str(symbol))
        if frame is None or getattr(frame, "empty", True):
            raise NavDataUnavailableError(f"REITs {symbol} 无行情数据（数据源返回空）")
        out = pd.DataFrame({
            "date": pd.to_datetime(frame["日期"]).dt.normalize(),
            "open": pd.to_numeric(frame["开盘"], errors="coerce"),
            "high": pd.to_numeric(frame["最高"], errors="coerce"),
            "low": pd.to_numeric(frame["最低"], errors="coerce"),
            "close": pd.to_numeric(frame["收盘"], errors="coerce"),
            "volume": pd.to_numeric(frame["成交量"], errors="coerce"),
        }).dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
        self._write_cache("cn_reits", str(symbol), out, "daily")
        return out

    def fetch_reits_indicator(self, symbol: str) -> pd.DataFrame:
        """REITs 净值 / 分派率 / 折溢价率指标。"""
        try:
            import akshare as ak
        except ImportError as exc:
            raise NavDataUnavailableError("未安装 akshare，无法获取 REITs 指标") from exc
        frame = self._call_source("akshare:fund_reits_indicator_em",
                                  ak.fund_reits_indicator_em, symbol=str(symbol))
        if frame is None or getattr(frame, "empty", True):
            raise NavDataUnavailableError(f"REITs {symbol} 无净值指标数据")
        return pd.DataFrame(frame).copy()

    def fetch_reits_dividend(self, symbol: str) -> pd.DataFrame:
        """REITs 历史分红（用于强制分红除权处理）。"""
        try:
            import akshare as ak
        except ImportError as exc:
            raise NavDataUnavailableError("未安装 akshare，无法获取 REITs 分红") from exc
        frame = self._call_source("akshare:fund_reits_dividend_em",
                                  getattr(ak, "fund_reits_dividend_em", None) or
                                  getattr(ak, "fund_reits_hist_em"), symbol=str(symbol))
        if frame is None or getattr(frame, "empty", True):
            raise NavDataUnavailableError(f"REITs {symbol} 无分红记录")
        return pd.DataFrame(frame).copy()

    def fetch_reits_merged(self, symbol: str) -> pd.DataFrame:
        """合并行情与净值指标，输出含折溢价率的 DataFrame；缺失字段置 NaN 并标注。"""
        daily = self.fetch_reits_daily(symbol)
        try:
            ind = self.fetch_reits_indicator(symbol)
        except NavDataUnavailableError as exc:
            self.logger.warning("REITs %s 指标不可用，折溢价率置 NaN：%s", symbol, exc)
            ind = pd.DataFrame()
        out = daily.copy()
        if not ind.empty:
            nav_col = next((c for c in ind.columns if "净值" in str(c)), None)
            if nav_col and "date" in ind.columns:
                tmp = pd.DataFrame({"date": pd.to_datetime(ind["date"]).dt.normalize(),
                                    "nav": pd.to_numeric(ind[nav_col], errors="coerce")})
                out = out.merge(tmp, on="date", how="left")
        if "nav" not in out.columns:
            out["nav"] = float("nan")
        out["premium_pct"] = out["close"] / out["nav"] - 1.0
        out["dividend_accum"] = float("nan")
        out.attrs["frequency"] = "daily"
        out.attrs["disclosure_lag_days"] = int(
            (config.NAV_PRODUCT_CONFIG.get("disclosure_lag_days") or {}).get("cn_reits", 1))
        out.attrs["premium_missing"] = bool(out["nav"].isna().all())
        return out

    # ------------------------------------------------------------------
    # 4) 新三板
    # ------------------------------------------------------------------
    def fetch_neeq_daily(self, symbol: str, layer: str = "innovation") -> pd.DataFrame:
        """新三板日线：过滤零成交日（停牌/无成交），并标注退市风险。"""
        cached = self._read_cache("neeq", str(symbol))
        if cached is not None:
            return cached
        try:
            import akshare as ak
        except ImportError as exc:
            raise NavDataUnavailableError("未安装 akshare，无法获取新三板行情") from exc
        fn = getattr(ak, "stock_neeq_hist", None) or getattr(ak, "stock_zh_a_hist", None)
        if fn is None:
            raise NavDataUnavailableError("akshare 无新三板接口（stock_neeq_hist 缺失）")
        frame = self._call_source("akshare:stock_neeq_hist", fn, symbol=str(symbol))
        if frame is None or getattr(frame, "empty", True):
            raise NavDataUnavailableError(f"新三板 {symbol} 无行情数据")
        out = pd.DataFrame({
            "date": pd.to_datetime(frame["日期"]).dt.normalize(),
            "open": pd.to_numeric(frame["开盘"], errors="coerce"),
            "high": pd.to_numeric(frame["最高"], errors="coerce"),
            "low": pd.to_numeric(frame["最低"], errors="coerce"),
            "close": pd.to_numeric(frame["收盘"], errors="coerce"),
            "volume": pd.to_numeric(frame["成交量"], errors="coerce"),
        }).dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
        out["zero_volume"] = out["volume"].fillna(0) <= 0
        out["delisting_warning"] = out["close"].pct_change().abs().fillna(0) > 0.5
        out.attrs["layer"] = str(layer)
        out.attrs["frequency"] = "daily"
        out.attrs["volume_unit"] = "股"
        self._write_cache("neeq", str(symbol), out)
        return out

    def fetch_neeq_list(self, layer: str = "innovation") -> pd.DataFrame:
        """新三板基础层/创新层挂牌公司列表。"""
        try:
            import akshare as ak
        except ImportError as exc:
            raise NavDataUnavailableError("未安装 akshare，无法获取新三板列表") from exc
        fn = getattr(ak, "stock_neeq_list", None)
        if fn is None:
            raise NavDataUnavailableError("akshare 无新三板列表接口（stock_neeq_list 缺失）")
        frame = self._call_source("akshare:stock_neeq_list", fn)
        if frame is None or getattr(frame, "empty", True):
            raise NavDataUnavailableError(f"新三板 {layer} 层列表为空")
        out = pd.DataFrame(frame).copy()
        out.attrs["layer"] = str(layer)
        return out

    # ------------------------------------------------------------------
    # 通用：从净值 CSV 目录批量装配（FOF 输入）
    # ------------------------------------------------------------------
    def load_nav_dir(self, product_type: str = "private_fund") -> Dict[str, pd.DataFrame]:
        """读取缓存目录内某市场全部净值，返回 {code: DataFrame}，供 FOF 回测。"""
        prefix = f"{product_type}_"
        out: Dict[str, pd.DataFrame] = {}
        for path in sorted(self.cache_dir.glob(f"{prefix}*.csv")):
            code = path.stem[len(prefix):].split("_")[0]
            try:
                out[code] = normalize_nav_frame(pd.read_csv(path),
                                                source=f"cache:{path.name}",
                                                product_type=product_type)
            except NavDataUnavailableError as exc:
                self.logger.warning("跳过无效净值文件 %s：%s", path.name, exc)
        if not out:
            raise NavDataUnavailableError(
                f"{self.cache_dir} 内没有 {product_type} 净值 CSV，无法装配 FOF 输入")
        return out
