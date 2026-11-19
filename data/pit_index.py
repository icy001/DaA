# -*- coding: utf-8 -*-
"""PIT 点内成分股（第 13 步 · 13.0 回补）

教训：回测用「今天的成分股」跑「三年前的池子」= 幸存者偏差，且结果更漂亮、完全看不出错。

- 取股票池只允许 ``get_index_members(index_code, date)``，文件名必须带日期；
- 不带日期 → 视为「当前成分股」直接报错（``forbid_current_constituents``）；
- 本地无该日快照 → ``on_unavailable=raise``，禁止静默用最近日期/当前成分股替代；
- ``assert_pit_enabled('backtest')``：PIT 闸门被关掉时回测入口直接拒跑。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List

import pandas as pd

import config

__all__ = [
    "PITUnavailableError",
    "classify_symbol",
    "resolve_index_code",
    "index_aliases",
    "constituents_dir",
    "member_snapshot_path",
    "save_index_members",
    "get_index_members",
    "assert_pit_enabled",
]


class PITUnavailableError(RuntimeError):
    """点内成分股不可用：回测不允许继续（幸存者偏差会静默污染结果）。"""


def _conf() -> dict:
    from core.gov_compat import gov
    return dict(gov("SNAPSHOT_PIT_GUARD").get("pit") or {})


# ==================== 符号分类（唯一检查器 · v3.40） ====================
# 教训：指数识别一旦在 pit_index 与 factor/universe 各写一份，直调前者即可绕过
# 后者；且「后缀与号段矛盾」必须按 INDEX_PREFIX_RULES 联合判定，不能一律拒。
_PREFIX_RE = re.compile(r"^(SH|SZ|BJ)[.\-]?(\d{6})$", re.IGNORECASE)
_SUFFIX_RE = re.compile(r"^(\d{6})[.\-]?(SH|SZ|BJ)$", re.IGNORECASE)


def _norm_key(value) -> str:
    return re.sub(r"[\s_\-]", "", str(value)).strip().lower()


def index_aliases() -> dict:
    """指数别名表：唯一来源是 ``config.CN_INDEX_ALIASES``（由 CN_INDEX 派生）。"""
    return dict(config.CN_INDEX_ALIASES or {})


def classify_symbol(value) -> tuple:
    """把输入分成 ``("index", 指数代码)`` 或 ``("stock", 个股代码)``。

    判定顺序（fail-closed，未识别一律 raise）：

    1. 别名（中文全名 / pool_aliases 短名）→ 指数；
    2. 带交易所前缀/后缀 → 按「后缀 + 号段」联合判定：
       SH+000/950/880/881、SZ+399/980/981、BJ+899 为指数；SH+600/601/603/605/688、
       SZ+000/001/002/003/300/301、BJ+920 为个股。000xxx 在 SH 是指数段、在 SZ 是个股段，
       两边都合法，不算冲突；只有两边号段都不认（如 399001.SH、600519.SZ）才报错。
       BJ 的 43/83/87/88 已于 2025-10-09 退出北交所，带 .BJ 后缀直接报错；
    3. 裸 6 位：``CN_INDEX_BARE_CODES`` 命中 → 指数（399xxx/932xxx 无歧义）；
       否则按 ``bare_code_is_stock`` 视为个股（000xxx 段与深市个股重合，个股优先）；
    4. 其它字符串 → ValueError，禁止「不认识就当代码」。
    """
    raw = str(value).strip()
    if not raw:
        raise ValueError("股票池出现空项")

    aliases = index_aliases()
    key = _norm_key(raw)
    if key in aliases:
        return ("index", aliases[key])

    m = _SUFFIX_RE.match(raw)
    if m:
        code, exch = m.group(1), m.group(2).upper()
    else:
        m = _PREFIX_RE.match(raw)
        if not m:
            if raw.isdigit() and 1 <= len(raw) <= 6:
                code = raw.zfill(6)
                bare = config.CN_INDEX_BARE_CODES or {}
                if code in bare:
                    return ("index", code)
                return ("stock", code)
            raise ValueError(
                f"无法识别股票池输入 {raw!r}：既不是 6 位代码（可带 .SH/.SZ/.BJ），"
                f"也不是已登记的指数名（hs300/沪深300/zz500/中证500/all_a...）。"
                f"指数请用显式名称或带后缀写法，个股请用代码——禁止把未知字符串默认当代码")
        exch, code = m.group(1).upper(), m.group(2)

    rules = config.INDEX_PREFIX_RULES or {}
    stocks = config.STOCK_PREFIX_RULES or {}
    seg = code[:3]
    idx_segs = tuple(rules.get(exch) or ())
    stock_segs = tuple(stocks.get(exch) or ())
    if seg in idx_segs:
        return ("index", code)
    if seg in stock_segs:
        return ("stock", code)
    # 两边号段都不认 → 真冲突（如 399001.SH、600519.SZ；北交所旧段 43/83/87/88 已失效）
    raise ValueError(
        f"{raw!r} 交易所与号段冲突：{seg}xxx 既不是 {exch} 的指数段"
        f"（{'/'.join(idx_segs)}），也不是 {exch} 的个股段"
        f"（{'/'.join(stock_segs)}）；北交所 2025-10-09 起个股只有 920 段，"
        f"43/83/87/88 已整体退出北交所，请核对后缀")


def resolve_index_code(value) -> str:
    """把任意受支持的写法归一成指数代码；不是指数即 raise（同一检查器）。

    与 ``classify_symbol`` 的差别仅在语境：本函数被显式用于「取指数成分股」，
    因此裸 000xxx 段若登记在 ``CN_INDEX['common_codes']`` 里也接受；
    ``resolve_universe`` 侧仍按「裸代码 = 个股优先」处理，避免歧义。
    """
    raw = str(value).strip()
    kind, code = classify_symbol(raw)
    if kind == "index":
        return code
    common = (config.CN_INDEX or {}).get("common_codes") or {}
    if raw.isdigit() and raw.zfill(6) in common:
        return raw.zfill(6)
    raise ValueError(f"{value!r} 不是指数代码（{code} 被判为个股）")


def constituents_dir(cache_dir=None) -> Path:
    return Path(cache_dir or config.DATA_CACHE_DIR) / "constituents"


def member_snapshot_path(index_code: str, date, cache_dir=None) -> Path:
    """成分股快照路径：文件名必须带 as_of 日期，避免不同时点互相覆盖。

    入参先过 ``resolve_index_code``（与 factor/universe 共用同一检查器），
    因此 ``"000300.SH"``、``"sh000300"``、``"沪深300"`` 落到同一个文件。
    """
    if date is None:
        raise PITUnavailableError(
            "PIT 成分股必须指定 as_of 日期（禁止读取「当前成分股」替代历史成分）")
    day = pd.Timestamp(date).strftime("%Y%m%d")
    code = re.sub(r"[^0-9A-Za-z]", "", resolve_index_code(index_code)).upper()
    return constituents_dir(cache_dir) / f"{code}_{day}.csv"


def _extract_codes(df: pd.DataFrame) -> List[str]:
    for col in ("symbol", "code", "成分券代码", "证券代码"):
        if col in df.columns:
            return [str(v).strip() for v in df[col].dropna() if str(v).strip()]
    if df.shape[1] == 1:
        return [str(v).strip() for v in df.iloc[:, 0].dropna() if str(v).strip()]
    raise PITUnavailableError(
        f"成分股快照列名无法识别（现有列：{list(df.columns)}），禁止猜测代码列")


def save_index_members(index_code: str, date, symbols: Iterable[str],
                       cache_dir=None) -> Path:
    """登记某个时点的成分股（原子写：先 .tmp 再 rename）。"""
    codes = [str(s).strip() for s in symbols if str(s).strip()]
    if date is None:
        raise PITUnavailableError("登记成分股必须带 as_of 日期")
    if not codes:
        raise PITUnavailableError(f"{index_code} 在 {date} 的成分股为空，拒绝登记空快照")
    path = member_snapshot_path(index_code, date, cache_dir=cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    pd.DataFrame({"symbol": codes}).to_csv(tmp, index=False, encoding="utf-8-sig")
    tmp.replace(path)
    return path


def get_index_members(index_code: str, date=None, cache_dir=None) -> List[str]:
    """取某日成分股；不带日期/无快照/快照为空一律报错。"""
    conf = _conf()
    if date is None and conf.get("forbid_current_constituents", True):
        raise PITUnavailableError(
            f"{index_code} 未指定 as_of 日期：回测禁止使用当前成分股（幸存者偏差）")
    path = member_snapshot_path(index_code, date, cache_dir=cache_dir)
    if not path.exists():
        if conf.get("on_unavailable", "raise") == "raise":
            raise PITUnavailableError(
                f"未找到 {index_code} 在 {date} 的点内成分股快照（{path}）；"
                "拉不到即拒绝回测，不得退化为当前成分股")
        return []
    codes = _extract_codes(pd.read_csv(path, dtype=str))
    if not codes:
        raise PITUnavailableError(f"{index_code} 在 {date} 的成分股快照为空（{path.name}）")
    return codes


_ENFORCE_KEYS = {"backtest": "enforce_in_backtest", "factor": "enforce_in_factor"}


def assert_pit_enabled(context: str = "backtest") -> None:
    """入口强制校验：PIT 闸门被关掉时直接拒跑（禁止旁路开关）。

    context：``backtest``（回测引擎）、``factor``（因子构建/股票池解析）。
    两者各有独立开关，但都必须 fail-closed；其它取值（paper/tooling）不在这里拦。
    """
    key = _ENFORCE_KEYS.get(str(context).lower())
    if key is None:
        return
    if not _conf().get(key, True):
        raise PITUnavailableError(
            f"PIT 点内成分股闸门已关闭（SNAPSHOT_PIT_GUARD['pit']['{key}']=False）："
            f"{context} 路径拒绝运行，否则结果含幸存者偏差且不可察觉")
