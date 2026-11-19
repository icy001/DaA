"""Tushare Pro 因子适配器（第 5 步 5.9.11 适配器 1）。

依赖
----
* 第三方包：``tushare``（``pip install tushare``）
* 配置项：``config.TUSHARE_TOKEN``（推荐写在项目根目录 ``.env``：
  ``TUSHARE_TOKEN=xxxxxxxx``）
* 权限：Tushare Pro 的行情/因子接口按积分开放，高级因子通常需要 2000 积分以上。

说明
----
Tushare Pro 主要提供行情与基础数据接口，本适配器用 ``pro.daily`` 拉取
OHLCV 面板，再复用本系统统一因子函数（alpha001/alpha101 系列或已注册自定义
因子）计算「日期×股票」因子值，保证与免费引擎口径一致。若你已购买 Tushare
官方因子表，可在 :meth:`TushareFactor._fetch_official` 中扩展对应接口。

* 内存缓存：同一 (因子, 股票池, 区间) 只算一次；单标的行情也按区间缓存；
* 限速：每次真实请求前后保证间隔 >= 0.35 秒（Tushare 分钟级调用限制）；
* ``dry_run=True`` 时不联网，返回空面板并记录 WARNING，便于离线跑通流程。
"""
from __future__ import annotations

import logging
import time
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

import config

logger = logging.getLogger(__name__)

__all__ = ["TushareFactor", "create_adapter"]

_FIELDS = ("open", "high", "low", "close", "volume", "amount")


def _install_hint() -> str:
    return (
        "未安装 tushare。请执行：pip install tushare\n"
        "并在项目 .env（或 config.py）中配置 TUSHARE_TOKEN=你的token；\n"
        "Tushare Pro 因子/行情接口需要积分权限，详见 https://tushare.pro/"
    )


def _token_hint() -> str:
    return (
        "未配置 TUSHARE_TOKEN。请在项目根目录 .env 写入：\n"
        "TUSHARE_TOKEN=你的token\n"
        "（token 在 https://tushare.pro/user/token 获取，不要提交到 git）"
    )


def _ts_code(symbol: str) -> str:
    """把 6 位代码转成 Tushare 的 ts_code（600519 → 600519.SH）。"""
    code = str(symbol).strip().upper()
    if "." in code:
        return code
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    if code.startswith(("6", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"


class TushareFactor:
    """Tushare Pro 因子适配器。"""

    MIN_INTERVAL = 0.35  # 秒，Tushare 限速保护

    def __init__(self, token: Optional[str] = None, dry_run: bool = False):
        self.token = str(token or getattr(config, "TUSHARE_TOKEN", "") or "")
        self.dry_run = bool(dry_run)
        self._pro = None
        self._last_request = 0.0
        self._raw_cache: Dict[tuple, pd.DataFrame] = {}
        self._result_cache: Dict[tuple, pd.DataFrame] = {}

    # ---------------- 连接 / 限速 ----------------
    def _api(self):
        if self._pro is not None:
            return self._pro
        try:
            import tushare as ts
        except ImportError as exc:  # 依赖缺失必须明确提示，不能静默
            raise ImportError(_install_hint()) from exc
        if not self.token:
            raise ImportError(_token_hint())
        ts.set_token(self.token)
        self._pro = ts.pro_api()
        return self._pro

    def _throttle(self) -> None:
        wait = self.MIN_INTERVAL - (time.time() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.time()

    # ---------------- 取数 ----------------
    def _fetch_official(self, factor_name: str, symbols: Sequence[str],
                        start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """预留：若账号已购买官方因子表，可在此接入对应接口并返回面板。"""
        logger.debug("Tushare 官方因子接口未启用：%s %s→%s，股票数 %d",
                     factor_name, start_date, end_date, len(symbols))
        return None

    def _fetch_symbol(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        key = (symbol, start_date, end_date)
        if key in self._raw_cache:
            return self._raw_cache[key]
        api = self._api()
        self._throttle()
        df = api.daily(ts_code=_ts_code(symbol),
                       start_date=pd.Timestamp(start_date).strftime("%Y%m%d"),
                       end_date=pd.Timestamp(end_date).strftime("%Y%m%d"))
        if df is None or len(df) == 0:
            logger.warning("Tushare 未返回 %s 的行情", symbol)
            return None
        df = df.copy()
        df.index = pd.to_datetime(df["trade_date"], format="%Y%m%d")
        df = df.sort_index()
        # Tushare 的 vol 单位是「手」，amount 单位是「千元」，统一换算成股/元
        if "vol" in df.columns:
            df["volume"] = pd.to_numeric(df["vol"], errors="coerce") * 100.0
        if "amount" in df.columns:
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce") * 1000.0
        for field in _FIELDS:
            if field in df.columns:
                df[field] = pd.to_numeric(df[field], errors="coerce")
        self._raw_cache[key] = df
        return df

    def _build_panels(self, symbols: Sequence[str], start_date: str,
                      end_date: str) -> Dict[str, pd.DataFrame]:
        buckets: Dict[str, List[pd.Series]] = {f: [] for f in _FIELDS}
        for symbol in symbols:
            df = self._fetch_symbol(str(symbol), start_date, end_date)
            if df is None:
                continue
            for field in _FIELDS:
                if field in df.columns:
                    buckets[field].append(df[field].rename(str(symbol)))
        panels: Dict[str, pd.DataFrame] = {}
        for field, series_list in buckets.items():
            if not series_list:
                continue
            panel = pd.concat(series_list, axis=1).sort_index()
            if panel.notna().any().any():
                panels[field] = panel
        if "close" not in panels:
            raise RuntimeError(
                "Tushare 未取到任何 close 数据；请检查 token 积分、代码格式与日期区间"
            )
        return panels

    # ---------------- 统一接口 ----------------
    def get_factor(self, factor_name: str, symbols: Iterable[str],
                   start_date: str, end_date: str) -> pd.DataFrame:
        """返回「日期×股票」因子面板。依赖/凭证缺失时抛 ImportError。"""
        symbols = [str(s) for s in (symbols or [])]
        if not symbols:
            raise ValueError("symbols 不能为空")
        if self.dry_run:
            logger.warning(
                "TushareFactor 处于 dry_run 模式：不联网、返回空面板。"
                "真实使用请去掉 dry_run 并配置 TUSHARE_TOKEN"
            )
            return pd.DataFrame()

        key = (str(factor_name), tuple(sorted(symbols)), str(start_date), str(end_date))
        if key in self._result_cache:
            return self._result_cache[key].copy()

        official = self._fetch_official(factor_name, symbols, start_date, end_date)
        if official is not None:
            result = official.sort_index()
        else:
            from ..base import build_factor_data
            from ..factor_engine import FactorEngine

            panels = self._build_panels(symbols, start_date, end_date)
            data = build_factor_data(panels)
            _, func = FactorEngine._resolve_factor(factor_name)
            result = func(data)
            if not isinstance(result, pd.DataFrame):
                raise TypeError(f"因子 {factor_name} 必须返回 DataFrame")
            result = result.replace([np.inf, -np.inf], np.nan)

        result = result.sort_index()
        self._result_cache[key] = result
        return result.copy()


def create_adapter(**kwargs) -> TushareFactor:
    """工厂函数：供 create_factor_engine(source='tushare') 调用。"""
    return TushareFactor(**kwargs)
