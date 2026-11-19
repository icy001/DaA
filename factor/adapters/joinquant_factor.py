"""聚宽 JoinQuant 因子适配器（第 5 步 5.9.11 适配器 2）。

依赖
----
* 第三方包：``jqdatasdk``（``pip install jqdatasdk``）
* 配置项：``config.JOINQUANT_USERNAME`` / ``config.JOINQUANT_PASSWORD``
  （推荐写在 .env：``JOINQUANT_USERNAME=手机号``、``JOINQUANT_PASSWORD=密码``）
* 免费额度：每天约 100 万条数据，足够研究使用。

说明
----
聚宽内置完整 alpha101/alpha191 与社区因子，本适配器直接调用
``jqdatasdk.get_factor_values`` 取因子值面板；因子名必须是聚宽因子库支持的
名称（如 ``alpha001`` 可能需写成聚宽口径名称），否则聚宽会抛接口错误。
"""
from __future__ import annotations

import logging
import time
from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd

import config

logger = logging.getLogger(__name__)

__all__ = ["JoinQuantFactor", "create_adapter"]


def _install_hint() -> str:
    return (
        "未安装 jqdatasdk。请执行：pip install jqdatasdk\n"
        "并在 .env 配置 JOINQUANT_USERNAME / JOINQUANT_PASSWORD（聚宽账号）"
    )


def _credential_hint() -> str:
    return (
        "未配置聚宽账号。请在项目根目录 .env 写入：\n"
        "JOINQUANT_USERNAME=你的手机号\n"
        "JOINQUANT_PASSWORD=你的密码"
    )


class JoinQuantFactor:
    """聚宽因子适配器（get_factor_values 接口）。"""

    MIN_INTERVAL = 0.35

    def __init__(self, username: Optional[str] = None, password: Optional[str] = None,
                 dry_run: bool = False):
        self.username = str(username or getattr(config, "JOINQUANT_USERNAME", "") or "")
        self.password = str(password or getattr(config, "JOINQUANT_PASSWORD", "") or "")
        self.dry_run = bool(dry_run)
        self._jq = None
        self._last_request = 0.0
        self._cache: Dict[tuple, pd.DataFrame] = {}

    def _login(self):
        if self._jq is not None:
            return self._jq
        try:
            import jqdatasdk as jq
        except ImportError as exc:
            raise ImportError(_install_hint()) from exc
        if not self.username or not self.password:
            raise ImportError(_credential_hint())
        jq.auth(self.username, self.password)
        self._jq = jq
        return jq

    def _throttle(self) -> None:
        wait = self.MIN_INTERVAL - (time.time() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.time()

    def get_factor(self, factor_name: str, symbols: Iterable[str],
                   start_date: str, end_date: str) -> pd.DataFrame:
        symbols = [str(s) for s in (symbols or [])]
        if not symbols:
            raise ValueError("symbols 不能为空")
        if self.dry_run:
            logger.warning(
                "JoinQuantFactor 处于 dry_run 模式：不联网、返回空面板。"
                "真实使用请去掉 dry_run 并配置聚宽账号"
            )
            return pd.DataFrame()

        key = (str(factor_name), tuple(sorted(symbols)), str(start_date), str(end_date))
        if key in self._cache:
            return self._cache[key].copy()

        jq = self._login()
        self._throttle()
        result = jq.get_factor_values(
            securities=symbols,
            factors=[str(factor_name)],
            start_date=str(start_date),
            end_date=str(end_date),
        )
        df = result.get(factor_name) if isinstance(result, dict) else result
        if df is None:
            raise RuntimeError(
                f"聚宽未返回因子 {factor_name}；请确认因子名在 get_factor_values "
                "支持的聚宽因子库中"
            )
        panel = pd.DataFrame(df).copy()
        panel.index = pd.to_datetime(panel.index)
        panel.columns = [str(c) for c in panel.columns]
        panel = panel.replace([np.inf, -np.inf], np.nan).sort_index()
        self._cache[key] = panel
        return panel.copy()


def create_adapter(**kwargs) -> JoinQuantFactor:
    """工厂函数：供 create_factor_engine(source='joinquant') 调用。"""
    return JoinQuantFactor(**kwargs)
