"""微软 Qlib 因子适配器（第 5 步 5.9.11 适配器 4）。

依赖
----
* 第三方包：``pyqlib``（``pip install pyqlib``）
* 配置项：``config.QLIB_PROVIDER_URI``（本地 qlib 数据目录），默认
  ``~/.qlib/qlib_data/cn_data``；也可在构造时传 ``provider_uri=...``
* **不需要账号**：数据完全来自本地 qlib 数据集。

说明
----
本适配器把 Qlib 内置的 Alpha158（158 个量价因子）/ Alpha360（360 个 6 日窗口
因子）计算结果转成「日期×股票」面板，供本系统评估 / 合成 / 回测。

因子名写法：
  * ``alpha158:KMID``   取 Alpha158 的 KMID 列
  * ``alpha360:CLOSE0`` 取 Alpha360 的 CLOSE0 列
  * ``alpha158``        未指定列时取该因子集的第一列，并打 WARNING

依赖缺失或本地 qlib 数据不存在时抛带可执行提示的 ImportError。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd

import config

logger = logging.getLogger(__name__)

__all__ = ["QlibFactor", "create_adapter"]

_DEFAULT_URI = "~/.qlib/qlib_data/cn_data"


def _install_hint() -> str:
    return (
        "未安装 qlib。请执行：pip install pyqlib\n"
        "然后准备本地数据：python -m qlib.run.get_data qlib_data "
        "--target_dir ~/.qlib/qlib_data/cn_data --region cn\n"
        "或在 .env 配置 QLIB_PROVIDER_URI 指向已有的 qlib 数据目录"
    )


def _data_hint(uri: str) -> str:
    return (
        f"qlib 本地数据目录不存在：{uri}\n"
        "请先下载数据（python -m qlib.run.get_data ...），\n"
        "或设置 config.QLIB_PROVIDER_URI / 构造参数 provider_uri 指向正确目录"
    )


class QlibFactor:
    """Qlib 本地因子适配器（Alpha158 / Alpha360）。"""

    def __init__(self, provider_uri: Optional[str] = None, dry_run: bool = False):
        self.provider_uri = str(
            provider_uri or getattr(config, "QLIB_PROVIDER_URI", "") or _DEFAULT_URI
        )
        self.dry_run = bool(dry_run)
        self._inited = False
        self._cache: Dict[tuple, pd.DataFrame] = {}

    def _init_qlib(self):
        try:
            import qlib
            from qlib.constant import REG_CN
        except ImportError as exc:
            raise ImportError(_install_hint()) from exc

        uri = Path(self.provider_uri).expanduser()
        if not uri.exists():
            raise ImportError(_data_hint(str(uri)))
        if not self._inited:
            qlib.init(provider_uri=str(uri), region=REG_CN)
            self._inited = True
        return qlib

    def _handler_cls(self, factor_name: str):
        try:
            from qlib.contrib.data.handler import Alpha158, Alpha360
        except ImportError as exc:
            raise ImportError(_install_hint()) from exc
        name = str(factor_name).lower()
        if name.startswith("alpha158"):
            return Alpha158, 158
        if name.startswith("alpha360"):
            return Alpha360, 360
        raise ValueError(
            f"QlibFactor 目前只支持 alpha158 / alpha360，收到 {factor_name!r}；"
            "如需单个字段请写成 alpha158:字段名"
        )

    def get_factor(self, factor_name: str, symbols: Iterable[str],
                   start_date: str, end_date: str) -> pd.DataFrame:
        symbols = [str(s) for s in (symbols or [])]
        if not symbols:
            raise ValueError("symbols 不能为空")
        if self.dry_run:
            logger.warning(
                "QlibFactor 处于 dry_run 模式：不读取本地数据、返回空面板。"
                "真实使用请去掉 dry_run 并准备好 qlib 本地数据"
            )
            return pd.DataFrame()

        key = (str(factor_name), tuple(sorted(symbols)), str(start_date), str(end_date))
        if key in self._cache:
            return self._cache[key].copy()

        self._init_qlib()
        handler_cls, _ = self._handler_cls(factor_name)
        name = str(factor_name)
        field = name.split(":", 1)[1].strip() if ":" in name else None

        try:
            handler = handler_cls(
                instruments=symbols,
                start_time=str(start_date),
                end_time=str(end_date),
                fit_start_time=str(start_date),
                fit_end_time=str(end_date),
                infer_processors=[],
                learn_processors=[],
            )
            handler.setup_data()
            features = handler.fetch(col_set="feature")
        except ImportError as exc:
            raise ImportError(_install_hint()) from exc
        except Exception as exc:
            raise RuntimeError(
                f"Qlib 计算 {name} 失败：{exc}\n"
                "请检查 instruments 代码格式（qlib 通常用 SH600519/SZ000001 形式）、"
                "日期区间与本地数据覆盖范围"
            ) from exc

        if features is None or len(features) == 0:
            raise RuntimeError(f"Qlib 未返回 {name} 的特征数据，请检查本地数据")
        if field is None:
            field = str(features.columns[0])
            logger.warning("未指定 %s 的具体字段，默认取第一列 %s", name, field)
        if field not in features.columns:
            raise ValueError(
                f"{name} 中不存在字段 {field!r}；可用示例：{list(features.columns[:10])}"
            )

        series = features[field]
        if isinstance(series.index, pd.MultiIndex):
            panel = series.unstack(level="instrument")
        else:
            panel = series.to_frame()
        panel.index = pd.to_datetime(panel.index)
        panel.columns = [str(c) for c in panel.columns]
        panel = panel.replace([np.inf, -np.inf], np.nan).sort_index()
        self._cache[key] = panel
        return panel.copy()


def create_adapter(**kwargs) -> QlibFactor:
    """工厂函数：供 create_factor_engine(source='qlib') 调用。"""
    return QlibFactor(**kwargs)
