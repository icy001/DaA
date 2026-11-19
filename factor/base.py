"""因子基础数据对象与注册表（第 5 步 5.9.16）。

设计要点：
  1) 一个因子 = 一个函数：输入 FactorData，输出「日期×股票」面板 DataFrame；
  2) FactorData 统一封装 OHLCV/vwap/returns/cap/industry，屏蔽取数细节；
  3) FactorData 从源头禁止负向位移：shift(-n)/lead 等直接抛 ValueError，
     避免「未来函数」悄悄混入因子计算；
  4) 全局注册表 + @register_factor 装饰器，自定义因子与内置 Alpha 完全平等。

注意：FactorData 只提供数据，不做去极值/标准化/中性化，这些统一交给
preprocess.py，避免多个因子口径不一致。
"""
from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

__all__ = [
    "FactorData",
    "build_factor_data",
    "register_factor",
    "get_factor",
    "list_factors",
    "FACTOR_REGISTRY",
]

# 全局因子注册表：name -> 因子函数
FACTOR_REGISTRY: Dict[str, Callable[["FactorData"], pd.DataFrame]] = {}

# 匹配动态位移属性（用于 __getattr__ 拦截未来函数）
_SHIFT_ATTR = re.compile(r"^(?:(close)_)?(shift|lag|lead|delay)_(neg|minus|m)?(-?\d+)$", re.I)


def _as_panel(x: Optional[pd.DataFrame], index, columns) -> Optional[pd.DataFrame]:
    """把输入对齐到统一面板；None 原样返回。"""
    if x is None:
        return None
    if not isinstance(x, pd.DataFrame):
        raise TypeError("FactorData 的每个字段必须是 pandas.DataFrame 面板")
    out = x.reindex(index=index, columns=columns)
    return out.astype(float) if out.dtypes.apply(lambda d: d != object).all() else out


class FactorData:
    """因子数据对象：所有属性都是「日期×股票」面板。

    参数
    ----
    close/open/high/low/volume/amount : DataFrame
        标准 OHLCV 面板，index=交易日，columns=股票代码。
    cap : DataFrame, optional
        市值面板（中性化用），缺失时相关中性化自动降级。
    industry : DataFrame, optional
        行业分类面板（字符串），缺失时 group_rank/group_neutralize 降级为全市场。
    """

    def __init__(
        self,
        close: pd.DataFrame,
        open: Optional[pd.DataFrame] = None,
        high: Optional[pd.DataFrame] = None,
        low: Optional[pd.DataFrame] = None,
        volume: Optional[pd.DataFrame] = None,
        amount: Optional[pd.DataFrame] = None,
        cap: Optional[pd.DataFrame] = None,
        industry: Optional[pd.DataFrame] = None,
    ) -> None:
        if not isinstance(close, pd.DataFrame) or close.empty:
            raise ValueError("close 必须是非空 DataFrame 面板")
        # 统一按交易日排序、日期索引、股票列
        close = close.sort_index() if isinstance(close.index, pd.DatetimeIndex) else close
        idx, cols = close.index, close.columns

        self._close = _as_panel(close, idx, cols)
        self._open = _as_panel(open, idx, cols)
        self._high = _as_panel(high, idx, cols)
        self._low = _as_panel(low, idx, cols)
        self._volume = _as_panel(volume, idx, cols)
        self._amount = _as_panel(amount, idx, cols)

        # 开高低缺失时用收盘价兜底（保持面板可计算，但语义上退化为收盘价）
        if self._open is None:
            self._open = self._close.copy()
        if self._high is None:
            self._high = self._close.copy()
        if self._low is None:
            self._low = self._close.copy()

        # 成交量 0 视为无效（停牌/净值型序列），置 NaN，避免 vwap 出现 inf
        if self._volume is not None:
            self._volume = self._volume.replace(0.0, np.nan)

        self._cap = _as_panel(cap, idx, cols) if cap is not None else None
        if industry is not None:
            self._industry = industry.reindex(index=idx, columns=cols)
        else:
            self._industry = None

    # ---------------- 基础面板属性 ----------------
    @property
    def close(self) -> pd.DataFrame:
        return self._close

    @property
    def open(self) -> pd.DataFrame:
        return self._open

    @property
    def high(self) -> pd.DataFrame:
        return self._high

    @property
    def low(self) -> pd.DataFrame:
        return self._low

    @property
    def volume(self) -> pd.DataFrame:
        """成交量面板；0 已按无效值置 NaN。"""
        if self._volume is None:
            return pd.DataFrame(np.nan, index=self._close.index, columns=self._close.columns)
        return self._volume

    @property
    def amount(self) -> pd.DataFrame:
        """成交额面板；缺失时用 volume × 典型价估算（仅作 vwap 兜底）。"""
        if self._amount is not None:
            return self._amount
        typical = (self.high + self.low + self._close) / 3.0
        return self.volume * typical

    @property
    def vwap(self) -> pd.DataFrame:
        """VWAP：优先 amount/volume，量缺失时退化为 (high+low+close)/3。"""
        typical = (self.high + self.low + self._close) / 3.0
        with np.errstate(divide="ignore", invalid="ignore"):
            vwap = self.amount / self.volume
        vwap = vwap.replace([np.inf, -np.inf], np.nan)
        return vwap.where(vwap.notna(), typical)

    @property
    def returns(self) -> pd.DataFrame:
        """日收益率面板：close/close.shift(1)-1（当日收益，不含未来）。"""
        r = self._close.pct_change(fill_method=None)
        return r.replace([np.inf, -np.inf], np.nan)

    @property
    def cap(self) -> Optional[pd.DataFrame]:
        return self._cap

    @property
    def industry(self) -> Optional[pd.DataFrame]:
        return self._industry

    # ---------------- 防未来函数 ----------------
    def shift(self, n: int = 1) -> "FactorData":
        """整体向前取 n 日历史数据；n<0 直接抛错（禁止未来数据）。"""
        n = int(n)
        if n < 0:
            raise ValueError(
                f"FactorData.shift({n}) 试图取未来数据，属于未来函数；"
                "因子计算只允许 n>=0 的历史位移"
            )
        return FactorData(
            close=self._close.shift(n),
            open=self._open.shift(n),
            high=self._high.shift(n),
            low=self._low.shift(n),
            volume=self._volume.shift(n) if self._volume is not None else None,
            amount=self._amount.shift(n) if self._amount is not None else None,
            cap=self._cap.shift(n) if self._cap is not None else None,
            industry=self._industry.shift(n) if self._industry is not None else None,
        )

    def close_shift(self, n: int = 1) -> pd.DataFrame:
        """取前 n 日收盘价（n>=0）；等价于 close.shift(n)，但禁止负向。"""
        if int(n) < 0:
            raise ValueError(f"close_shift({n}) 试图取未来数据，禁止")
        return self._close.shift(int(n))

    def pct_change(self, n: int = 1) -> pd.DataFrame:
        """n 日收益率（基于当日及 n 日前收盘，不引入未来）。"""
        if int(n) < 0:
            raise ValueError(f"pct_change({n}) 参数必须 >=0")
        return self._close.pct_change(int(n), fill_method=None).replace([np.inf, -np.inf], np.nan)

    def rolling(self, window: int, **kwargs):
        """透传到 close.rolling，方便自定义因子直接写 data.rolling(20).mean()。"""
        return self._close.rolling(window, **kwargs)

    def __getattr__(self, name: str):
        """拦截 shift_neg_1 / lead_1 / future_close 这类未来函数写法。

        属性名里没有面板字段时才进入这里；一旦识别为「取未来」立即抛错，
        识别为「取历史」则返回 close 的对应位移，避免用户误以为不支持。
        """
        if name.startswith("_"):
            raise AttributeError(name)
        low = name.lower()
        if low.startswith("future") or low.startswith("next_"):
            raise ValueError(f"属性 {name} 表示未来数据，因子中禁止使用")
        m = _SHIFT_ATTR.match(name)
        if m:
            kind = m.group(2).lower()
            neg = (m.group(3) is not None) or (int(m.group(4)) < 0)
            if kind == "lead" or neg:
                raise ValueError(f"属性 {name} 试图取未来数据，属于未来函数，禁止")
            return self._close.shift(abs(int(m.group(4))))
        raise AttributeError(f"FactorData 没有属性 {name}")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return (
            f"FactorData(dates={len(self._close)}, stocks={len(self._close.columns)}, "
            f"cap={'yes' if self._cap is not None else 'no'}, "
            f"industry={'yes' if self._industry is not None else 'no'})"
        )


def build_factor_data(frames: Dict[str, pd.DataFrame], **kwargs) -> FactorData:
    """从字段字典构造 FactorData（引擎内部用）。

    frames 的 key 支持 close/open/high/low/volume/amount/cap/industry。
    """
    if "close" not in frames:
        raise ValueError("构造 FactorData 至少需要 close 面板")
    return FactorData(
        close=frames["close"],
        open=frames.get("open"),
        high=frames.get("high"),
        low=frames.get("low"),
        volume=frames.get("volume"),
        amount=frames.get("amount"),
        cap=frames.get("cap"),
        industry=frames.get("industry"),
    )


# ---------------- 因子注册表 ----------------
def register_factor(name: str) -> Callable:
    """因子注册装饰器：同名重复注册直接抛错，避免静默覆盖。"""

    def deco(func: Callable[["FactorData"], pd.DataFrame]):
        if not callable(func):
            raise TypeError("register_factor 只能装饰函数")
        if name in FACTOR_REGISTRY:
            raise ValueError(f"因子 {name} 已注册，禁止重复注册")
        if not name or not isinstance(name, str):
            raise ValueError("因子名必须是非空字符串")
        FACTOR_REGISTRY[name] = func
        return func

    return deco


def get_factor(name: str) -> Callable[["FactorData"], pd.DataFrame]:
    """按注册名取因子函数；不存在时给出可用名称提示。"""
    # 懒加载自定义因子，保证用户直接 get_factor('my_momentum') 也能命中
    if name not in FACTOR_REGISTRY:
        try:  # pragma: no cover - 循环导入保护
            from . import custom  # noqa: F401
        except Exception:
            pass
    if name not in FACTOR_REGISTRY:
        available = ", ".join(sorted(FACTOR_REGISTRY)[:30]) or "（空）"
        raise KeyError(f"因子 {name} 未注册；可用因子示例：{available}")
    return FACTOR_REGISTRY[name]


def list_factors() -> List[str]:
    """列出全部已注册因子名（排序）。"""
    if not FACTOR_REGISTRY:
        try:  # pragma: no cover
            from . import custom  # noqa: F401
        except Exception:
            pass
    return sorted(FACTOR_REGISTRY)
