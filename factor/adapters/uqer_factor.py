"""优矿 UQER 因子适配器（第 5 步 5.9.11 适配器 3）。

依赖
----
* 第三方包：``uqer``（优矿官方 DataAPI SDK，``pip install uqer``）
* 配置项：``config.UQER_USERNAME`` / ``config.UQER_PASSWORD``
  （也可用 ``config.UQER_TOKEN`` 作为用户名兜底；推荐写在 .env）
* 说明：优矿的因子接口随 SDK 版本不同略有差异，本适配器调用
  ``DataAPI.Factor.get_factor(factor_name, symbols, start, end)``；
  若你的 SDK 未提供该接口，会在 ImportError 中给出可执行的替代方案。

统一接口：``get_factor(factor_name, symbols, start_date, end_date)``
返回 DataFrame(index=交易日, columns=股票代码)。
"""
from __future__ import annotations

import logging
from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd

import config

logger = logging.getLogger(__name__)

__all__ = ["UqerFactor", "create_adapter"]


def _install_hint() -> str:
    return (
        "未安装 uqer。请执行：pip install uqer\n"
        "并在 .env 配置 UQER_USERNAME / UQER_PASSWORD（优矿账号；\n"
        "若使用 token 登录，可配置 UQER_TOKEN）"
    )


def _credential_hint() -> str:
    return (
        "未配置优矿账号。请在项目根目录 .env 写入：\n"
        "UQER_USERNAME=你的账号\n"
        "UQER_PASSWORD=你的密码\n"
        "（或 UQER_TOKEN=你的token）"
    )


def _api_hint() -> str:
    return (
        "当前 uqer SDK 未提供 DataAPI.Factor.get_factor 接口。\n"
        "可执行方案：\n"
        "  1) 升级 SDK：pip install -U uqer\n"
        "  2) 或改用聚宽/ Tushare 适配器（source='joinquant' / 'tushare'）\n"
        "  3) 或在 factor/adapters/uqer_factor.py 中按你的 SDK 版本补 _fetch_panel"
    )


class UqerFactor:
    """优矿因子适配器。"""

    def __init__(self, username: Optional[str] = None, password: Optional[str] = None,
                 dry_run: bool = False):
        self.username = str(
            username or getattr(config, "UQER_USERNAME", "")
            or getattr(config, "UQER_TOKEN", "") or ""
        )
        self.password = str(password or getattr(config, "UQER_PASSWORD", "") or "")
        self.dry_run = bool(dry_run)
        self._api = None
        self._cache: Dict[tuple, pd.DataFrame] = {}

    def _login(self):
        if self._api is not None:
            return self._api
        try:
            import uqer
        except ImportError as exc:
            raise ImportError(_install_hint()) from exc
        if not self.username:
            raise ImportError(_credential_hint())
        login = getattr(uqer, "login", None)
        if callable(login):
            login(self.username, self.password)
        factor_api = getattr(getattr(uqer, "DataAPI", None), "Factor", None)
        func = getattr(factor_api, "get_factor", None)
        if not callable(func):
            raise ImportError(_api_hint())
        self._api = func
        return func

    def get_factor(self, factor_name: str, symbols: Iterable[str],
                   start_date: str, end_date: str) -> pd.DataFrame:
        symbols = [str(s) for s in (symbols or [])]
        if not symbols:
            raise ValueError("symbols 不能为空")
        if self.dry_run:
            logger.warning(
                "UqerFactor 处于 dry_run 模式：不联网、返回空面板。"
                "真实使用请去掉 dry_run 并配置优矿账号"
            )
            return pd.DataFrame()

        key = (str(factor_name), tuple(sorted(symbols)), str(start_date), str(end_date))
        if key in self._cache:
            return self._cache[key].copy()

        func = self._login()
        result = func(str(factor_name), symbols, str(start_date), str(end_date))
        df = result.get(factor_name) if isinstance(result, dict) else result
        if df is None:
            raise RuntimeError(f"优矿未返回因子 {factor_name}，请检查因子名与账号权限")
        panel = pd.DataFrame(df).copy()
        panel.index = pd.to_datetime(panel.index)
        panel.columns = [str(c) for c in panel.columns]
        panel = panel.replace([np.inf, -np.inf], np.nan).sort_index()
        self._cache[key] = panel
        return panel.copy()


def create_adapter(**kwargs) -> UqerFactor:
    """工厂函数：供 create_factor_engine(source='uqer') 调用。"""
    return UqerFactor(**kwargs)
