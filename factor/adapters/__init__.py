"""外部平台因子适配器（第 5 步 5.9.11）。

统一接口::

    get_factor(factor_name, symbols, start_date, end_date)
        -> DataFrame(index=交易日, columns=股票代码)

各厂商 SDK 全部**懒导入**：只有真正调用 get_factor 时才 import。依赖缺失或
凭证未配置时抛出带「安装 / 配置」提示的 ImportError，绝不静默返回空表。

可用的因子数据源：
  * tushare     Tushare Pro（需 TUSHARE_TOKEN，安装 pip install tushare）
  * joinquant   聚宽（需 JOINQUANT_USERNAME / JOINQUANT_PASSWORD，安装 jqdatasdk）
  * uqer        优矿（需 UQER_USERNAME / UQER_PASSWORD，安装 uqer）
  * qlib        微软 Qlib（本地数据，无需账号，安装 pyqlib）
"""
from __future__ import annotations

__all__ = [
    "TushareFactor",
    "JoinQuantFactor",
    "UqerFactor",
    "QlibFactor",
    "create_adapter",
]

from .joinquant_factor import JoinQuantFactor
from .qlib_factor import QlibFactor
from .tushare_factor import TushareFactor
from .uqer_factor import UqerFactor

_ADAPTERS = {
    "tushare": TushareFactor,
    "joinquant": JoinQuantFactor,
    "jq": JoinQuantFactor,
    "uqer": UqerFactor,
    "qlib": QlibFactor,
}


def create_adapter(source: str = "tushare", **kwargs):
    """按数据源名创建适配器实例（供 create_factor_engine 统一调用）。"""
    key = str(source or "").lower()
    cls = _ADAPTERS.get(key)
    if cls is None:
        raise ImportError(
            f"未知因子数据源 {source!r}；可选：{', '.join(sorted(set(_ADAPTERS)))}"
        )
    return cls(**kwargs)
