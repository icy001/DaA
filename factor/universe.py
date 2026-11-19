"""股票池管理（第 5 步 5.9.10；第 13 步 13.0 收口到 PIT；v3.38 按输入形态分层）。

闸门按**输入形态**分层（config.UNIVERSE_RESOLUTION_GUARD['enforce_at']=本模块的
resolve_universe），而不是按「是否调用 compute」：

- 显式代码列表（list/tuple/逗号串/"[...]"串/单代码）→ **没有**幸存者偏差可防，
  直接归一化放行（explicit_symbols_requires_pit=False）；
- 指数名 / universe / 带后缀的指数代码 → 必须走点内成分股
  ``get_index_members(index_code, as_of)``：缺 as_of 报错、无该日快照报错、
  PIT 闸门被关报错（index_name_requires_pit=True）；
- None/隐式全A → 直接报错（allow_implicit_all_a=False）。

指数识别**不在本模块定义**：一律调用 ``data.pit_index.classify_symbol``，
别名表由 ``config.CN_INDEX`` 派生（v3.40 单一检查器）。

禁止再拉「当前成分股」、也禁止断网时回退内置静态清单——那等于用今天的池子跑历史，
结果更漂亮且完全看不出错（幸存者偏差）。
"""
from __future__ import annotations

import logging
import re
from typing import Iterable, List, Sequence, Union

import pandas as pd

from data import pit_index

logger = logging.getLogger(__name__)

__all__ = [
    "get_hs300", "get_zz500", "get_zz1000", "get_zz2000", "get_all_a",
    "filter_liquidity", "filter_pause", "filter_st", "filter_limit_up_down",
    "resolve_universe",
]

_SPLIT_RE = re.compile(r"[\s,;，；\[\]\(\)]+")


def _norm_key(name: str) -> str:
    return re.sub(r"[\s_\-]", "", str(name)).strip().lower()


def _norm_explicit(values: Iterable) -> List[str]:
    """显式声明路径：逐项过同一检查器；出现指数/未知串直接 raise（不静默当代码）。"""
    out = []
    for v in values:
        kind, code = pit_index.classify_symbol(v)
        if kind == "index":
            raise ValueError(
                f"显式代码列表里出现指数 {v!r}：请用 resolve_universe({v!r}, as_of=日期) "
                f"或 get_hs300(日期) 走点内成分股；列表只接受个股代码")
        out.append(code)
    return sorted(set(out))


def _norm_codes(values: Iterable) -> List[str]:
    """可信来源（PIT 快照返回值）的归一化，不做输入校验。"""
    out = []
    for v in values:
        s = str(v).strip().split(".")[0]
        if not s:
            continue
        digits = "".join(ch for ch in s if ch.isdigit())
        out.append(digits.zfill(6) if digits else s)
    return sorted(set(out))


def _pit_universe(name_or_code: str, date=None, cache_dir=None) -> List[str]:
    """指数路径：取某日点内成分股；缺日期/无快照/PIT 闸门被关都直接报错。

    ``name_or_code`` 原样交给 ``pit_index.resolve_index_code``（同一检查器），
    因此 ``"000300.SH"``、``"sh000300"``、``"沪深300"`` 等价。

    仅本路径受 ``enforce_in_factor`` 约束——显式代码列表路径不经过这里，
    永不因 PIT 被拦（v3.38 enforce_scope 分层）。
    """
    if date is None:
        raise pit_index.PITUnavailableError(
            f"{name_or_code} 股票池必须指定 as_of 日期：禁止读取当前成分股（幸存者偏差）")
    pit_index.assert_pit_enabled("factor")
    return _norm_codes(pit_index.get_index_members(
        name_or_code, date, cache_dir=cache_dir))


def get_hs300(date=None, cache_dir=None) -> List[str]:
    """沪深300 在 ``date`` 当日的成分股（PIT）。"""
    return _pit_universe("hs300", date, cache_dir=cache_dir)


def get_zz500(date=None, cache_dir=None) -> List[str]:
    """中证500 在 ``date`` 当日的成分股（PIT）。"""
    return _pit_universe("zz500", date, cache_dir=cache_dir)


def get_zz1000(date=None, cache_dir=None) -> List[str]:
    """中证1000 在 ``date`` 当日的成分股（PIT）。"""
    return _pit_universe("zz1000", date, cache_dir=cache_dir)


def get_zz2000(date=None, cache_dir=None) -> List[str]:
    """中证2000 在 ``date`` 当日的成分股（PIT）。"""
    return _pit_universe("zz2000", date, cache_dir=cache_dir)


def get_all_a(date=None, cache_dir=None) -> List[str]:
    """全A 在 ``date`` 当日的快照（PIT 伪指数 ALLA）；ST 过滤以快照为准。"""
    return _pit_universe("all_a", date, cache_dir=cache_dir)


# ==================== 过滤器（兼容长表与宽表） ====================
def filter_liquidity(df: pd.DataFrame, min_amount: float = 5e7) -> pd.DataFrame:
    """成交额过滤。

    * 长表（含 amount 列）：直接按行过滤；
    * 宽表（本身就是成交额面板）：低于阈值的单元置 NaN。
    """
    if "amount" in df.columns:
        return df[df["amount"].fillna(0) >= min_amount].copy()
    return df.where(df >= min_amount)


def filter_pause(df: pd.DataFrame) -> pd.DataFrame:
    """停牌过滤：成交量为 0/NaN 视为停牌。"""
    if "volume" in df.columns:
        return df[df["volume"].fillna(0) > 0].copy()
    if "is_pause" in df.columns:
        return df[~df["is_pause"].astype(bool)].copy()
    logger.warning("filter_pause 未找到 volume/is_pause 字段，原样返回")
    return df.copy()


def filter_st(df: pd.DataFrame) -> pd.DataFrame:
    """ST/*ST 过滤。"""
    if "name" in df.columns:
        bad = df["name"].astype(str).str.upper().str.contains("ST", na=False)
        return df[~bad].copy()
    if "is_st" in df.columns:
        return df[~df["is_st"].astype(bool)].copy()
    logger.warning("filter_st 未找到 name/is_st 字段，原样返回")
    return df.copy()


def filter_limit_up_down(df: pd.DataFrame, pct: float = 9.8) -> pd.DataFrame:
    """涨跌停过滤（默认 |涨跌幅|>=9.8% 视为涨跌停）。"""
    if "pct_chg" in df.columns:
        return df[df["pct_chg"].abs() < pct].copy()
    if "limit_up" in df.columns and "limit_down" in df.columns:
        return df[~(df["limit_up"].astype(bool) | df["limit_down"].astype(bool))].copy()
    logger.warning("filter_limit_up_down 未找到 pct_chg/limit 字段，原样返回")
    return df.copy()


def resolve_universe(name_or_list: Union[str, Sequence[str], None],
                     as_of=None, cache_dir=None) -> List[str]:
    """把股票池名称/代码列表解析成代码列表（v3.40 分层判据的唯一落点）。

    分支点（**fail-closed**：无法 100% 确认是代码的输入一律报错，绝不静默当代码）：

    - 显式代码列表（list/tuple/set/Index、逗号串、"[...]"串、单代码）→ 逐项过
      ``pit_index.classify_symbol`` 后归一化，**不经过任何 PIT 调用**
      （explicit_symbols_requires_pit=False）；
    - 指数（别名 'hs300'/'沪深300'/'hs 300'，或 000300.SH / sh000300 / 399001 等）
      → 必须带 ``as_of``，走点内快照（index_name_requires_pit=True）；
    - ``None`` → 直接报错（allow_implicit_all_a=False，隐式全A会静默引入偏差）；
    - 其它字符串 → ValueError（resolution_default=deny），不存在
      "未命中白名单就当代码"的 fail-open 缝隙。
    """
    if name_or_list is None:
        raise pit_index.PITUnavailableError(
            "resolve_universe 收到 None：股票池必须显式指定，禁止默认全A（会引入幸存者偏差）")
    if isinstance(name_or_list, (list, tuple, set, pd.Index)):
        return _norm_explicit(name_or_list)

    name = str(name_or_list).strip()
    if not name:
        raise ValueError("股票池输入为空")
    # 别名先归一（"hs 300" 这类带空格的写法不能被空格拆成两个 token）
    alias = pit_index.index_aliases().get(_norm_key(name))
    if alias is not None:
        return _pit_universe(alias, as_of, cache_dir=cache_dir)
    if name.startswith(("[", "(")):
        return _norm_explicit([t for t in _SPLIT_RE.split(name.strip("[]()")) if t])

    tokens = [t for t in _SPLIT_RE.split(name) if t]
    if len(tokens) > 1:
        return _norm_explicit(tokens)

    kind, code = pit_index.classify_symbol(name)   # 与 get_index_members 同一检查器
    if kind == "index":
        return _pit_universe(code, as_of, cache_dir=cache_dir)
    return [code]
