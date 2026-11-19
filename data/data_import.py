# -*- coding: utf-8 -*-
"""本地数据导入出口（data/data_import.py）——第 11 步 11.0「--data 导入走数据层出口」。

**为什么必须有这一层**
======================
``main.py backtest --data my_bars.csv`` 不能在入口里裸 ``pd.read_csv`` 就开跑：
入口一旦绕过数据层，三物化列（warmup_ok / data_asof_date / price_adjust）就没人
负责物化，下游的预热闸门、时效闸门、复权口径守卫全部形同虚设。本模块是
``--data`` 的唯一合规出口：

1. **读文件**：支持 CSV / Parquet，必含 ``date``（或「日期」）与 OHLCV 列；
2. **物化三列**（与 ``DataFetcher._attach_asof`` 同一口径）：
   - ``warmup_ok``：逐 symbol 按 bar 序号 >= warmup_bars 才为 True；
   - ``data_asof_date``：逐 symbol 取**各自最后一根 bar 的实际日期**——多标的帧
     禁止整帧广播同一日期（B 标的停更会被 A 标的的日期掩盖）；
   - ``price_adjust``：导入口径统一归一为 qfq / hfq / none；
3. **fail-closed 校验**：三列缺列或含 NaN 直接抛 :class:`LocalDataImportError`，
   绝不静默放行；
4. **供给引擎**：:class:`LocalDataFetcher` 包装为 fetcher 注入 ``run_backtest`` /
   ``run_paper``——引擎照常走 ``signal_gate.build_bar`` 组装 bar，闸门不打折。

配置事实源：``config.CLI_CONFORMANCE``（``data_import_via_data_layer`` /
``data_import_requires_columns`` / ``data_import_warmup_bars``）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

import config

__all__ = [
    "LocalDataFetcher",
    "LocalDataImportError",
    "import_local_frame",
    "import_local_fetcher",
]

# 列名兼容（中文导出文件常见表头）
_DATE_ALIASES = ("date", "日期", "trade_date", "datetime", "交易日")
_OHLCV_ALIASES = {
    "open": ("open", "开盘", "开盘价"),
    "high": ("high", "最高", "最高价"),
    "low": ("low", "最低", "最低价"),
    "close": ("close", "收盘", "收盘价"),
    "volume": ("volume", "成交量", "vol"),
}

_ADJUST_VALUES = ("qfq", "hfq", "none")


class LocalDataImportError(RuntimeError):
    """本地数据导入失败——缺列 / 空 / 三物化列不齐，一律 fail-closed 拒绝。"""


def _conf() -> dict:
    return dict(getattr(config, "CLI_CONFORMANCE", {}) or {})


def required_columns() -> List[str]:
    """--data 导入必须物化的三列（config 唯一事实源）。"""
    return [str(c) for c in _conf().get("must_feed_columns")
            or ["warmup_ok", "data_asof_date", "price_adjust"]]


def default_warmup_bars() -> int:
    return int((getattr(config, "_USER_CLI_DEFAULTS", {}).get("data_import_warmup_bars")) or 60)


def _norm_adjust(value) -> str:
    v = str(value or "").strip().lower()
    return v if v in _ADJUST_VALUES else "none"


def _pick_column(columns, aliases) -> Optional[str]:
    lower = {str(c).lower(): c for c in columns}
    for alias in aliases:
        if alias in lower:
            return lower[alias]
    return None


def _read_any(path) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise LocalDataImportError(f"数据文件不存在：{p}")
    suffix = p.suffix.lower()
    try:
        if suffix in (".parquet", ".pq"):
            return pd.read_parquet(p)
        if suffix in (".csv", ".txt"):
            return pd.read_csv(p)
        if suffix in (".xlsx", ".xls"):
            return pd.read_excel(p)
    except LocalDataImportError:
        raise
    except Exception as exc:                     # noqa: BLE001 —— 任何读取失败都归一
        raise LocalDataImportError(f"读取 {p} 失败：{exc}") from exc
    raise LocalDataImportError(f"不支持的文件类型 {suffix!r}（支持 csv/parquet/excel）：{p}")


def import_local_frame(path, symbol: str = None, adjust: str = "qfq",
                       warmup_bars: int = None) -> pd.DataFrame:
    """导入一份本地行情 → 物化三列 → 校验齐备后返回（数据层唯一出口）。

    - 单标的文件（无 symbol 列）：``symbol`` 用于日志与多帧装配，可省；
    - 帧内含 ``symbol`` 列的多标的文件：逐 symbol 物化（warmup / asof 各自算）；
    - 三物化列缺列 / NaN → :class:`LocalDataImportError`（缺列拒绝，fail-closed）。
    """
    conf = _conf()
    if not conf.get("import_paths_must_use_data_layer", True):
        raise LocalDataImportError(
            "CLI_CONFORMANCE['import_paths_must_use_data_layer'] 被关闭：--data 导入出口"
            "必须走数据层，fail-closed 拒绝裸导入")
    warmup = int(warmup_bars if warmup_bars is not None else default_warmup_bars())
    adjust_col = _norm_adjust(adjust or config.INDICATOR_CONFIG.get(
        "default_adjust", "qfq"))

    frame = _read_any(path)
    if frame is None or len(frame) == 0:
        raise LocalDataImportError(f"数据文件为空：{path}")

    date_col = _pick_column(frame.columns, _DATE_ALIASES)
    if date_col is None:
        raise LocalDataImportError(
            f"缺列拒绝：{path} 没有日期列（{'/'.join(_DATE_ALIASES)}）")
    missing_price = [k for k in ("close",) if _pick_column(frame.columns,
                                                           _OHLCV_ALIASES[k]) is None]
    if missing_price:
        raise LocalDataImportError(
            f"缺列拒绝：{path} 缺少必要行情列 {missing_price}（close/open/high/"
            "low/volume 至少要有 close）")

    out = frame.copy()
    out[date_col] = pd.to_datetime(out[date_col], errors="coerce")
    out = out.dropna(subset=[date_col]).sort_values(date_col)
    if len(out) == 0:
        raise LocalDataImportError(f"日期列全部无效：{path}")
    out.index = pd.DatetimeIndex(out[date_col])

    # symbol 分组（无 symbol 列 → 单标的）
    sym_col = _pick_column(out.columns, ("symbol", "代码", "sec_code"))
    if sym_col is not None:
        # fail-closed：symbol 列含缺失值会使 data_asof_date 逐标的物化失效
        # （NaN 会被 astype(str) 洗成合法分组键），必须在此显式拒绝
        if out[sym_col].isna().any():
            raise LocalDataImportError(
                "缺列拒绝：--data 导入帧 symbol 列含缺失值（会使 data_asof_date "
                "物化失效），fail-closed 拒绝导入")
        syms = out[sym_col].astype(str)
    else:
        tag = str(symbol or Path(path).stem)
        syms = pd.Series([tag] * len(out), index=out.index)
        out = out.copy()
        out["symbol"] = syms.values

    # ---- 物化 warmup_ok：逐 symbol 按 bar 序号 ----
    seq = syms.groupby(syms).cumcount()
    out["warmup_ok"] = (seq >= warmup).values

    # ---- 物化 data_asof_date：逐 symbol 取各自最后一根 bar 的实际日期 ----
    per_symbol = pd.Series(out.index).groupby(syms.values).max()
    out["data_asof_date"] = syms.map(per_symbol).values

    # ---- 物化 price_adjust：单一导入口径（归一 qfq/hfq/none）----
    if "price_adjust" in out.columns:
        out["price_adjust"] = out["price_adjust"].map(_norm_adjust)
    else:
        out["price_adjust"] = adjust_col

    # ---- fail-closed 校验：三列齐备且无 NaN ----
    lack = [c for c in required_columns() if c not in out.columns]
    if lack:
        raise LocalDataImportError(
            f"缺列拒绝：--data 导入帧缺少三物化列 {lack}（要求 "
            f"{required_columns()}），禁止绕过数据层出口导入")
    bad = [c for c in required_columns() if out[c].isna().any()]
    if bad:
        raise LocalDataImportError(
            f"--data 导入帧的三物化列含 NaN：{bad}（要求 "
            f"{required_columns()} 全部为有效值，fail-closed）")

    out.attrs["imported_from"] = str(Path(path))
    # 口径标注：导入来源
    out.attrs["adjust"] = adjust_col            # attrs 备份（列才是事实源）
    out.attrs["warmup_bars"] = warmup
    return out


def import_local_fetcher(paths, symbols: List[str] = None,
                         adjust: str = "qfq",
                         warmup_bars: int = None) -> "LocalDataFetcher":
    """把若干本地文件导入并装配成 fetcher（供 run_backtest / run_paper 注入）。

    ``paths`` 为逗号分隔字符串或路径列表；``symbols`` 与之一一对应（缺省取文件名
    主名）。任一文件导入失败即整体拒绝——禁止「部分成功静默继续」。
    """
    if isinstance(paths, str):
        items = [p.strip() for p in paths.split(",") if p.strip()]
    else:
        items = [str(p) for p in (paths or [])]
    if not items:
        raise LocalDataImportError("--data 未提供任何文件路径")
    if symbols is None:
        names = [Path(p).stem for p in items]
    else:
        names = [str(s) for s in symbols]
        if len(names) != len(items):
            raise LocalDataImportError(
                f"--data 文件数 {len(items)} 与 --symbols 数 {len(names)} 不一致")
    frames: Dict[str, pd.DataFrame] = {}
    for tag, path in zip(names, items):
        frame = import_local_frame(path, symbol=tag, adjust=adjust,
                                    warmup_bars=warmup_bars)
        frame = frame.copy()
        frame["symbol"] = tag          # 单文件强制单标的标签
        frames[tag] = frame.set_axis(pd.DatetimeIndex(frame.index))
    return LocalDataFetcher(frames, adjust=adjust)


class LocalDataFetcher:
    """本地帧 fetcher：get_daily / get_kline 直接供给导入帧（离线回测）。

    引擎后续仍会走 ``signal_gate.build_bar`` 组装 bar 并重算 warmup 标记，
    本类只负责「把数据层出口的帧喂给引擎」，不重复实现闸门逻辑。
    """

    def __init__(self, frames: Dict[str, pd.DataFrame], adjust: str = "qfq"):
        self.frames = {str(k): v for k, v in dict(frames or {}).items()}
        self.adjust = _norm_adjust(adjust)

    # ------------------------------------------------------------------
    def get_daily(self, symbol: str, start_date: str = None,
                  end_date: str = None, adjust: str = None, **_kw) -> pd.DataFrame:
        frame = self._frame(symbol)
        out = self._slice(frame, start_date, end_date)
        out.attrs["adjust"] = _norm_adjust(adjust or self.adjust)
        out.attrs["source"] = "local_import"
        return out

    def get_kline(self, symbol: str, start_date: str = None,
                  end_date: str = None, period: str = "1d",
                  adjust: str = None, **_kw) -> pd.DataFrame:
        if str(period) not in ("1d", "daily", "day"):
            raise LocalDataImportError(
                f"本地导入仅支持日线（收到 period={period!r}）：分钟/周月线请走"
                " DataFetcher 在线取数")
        return self.get_daily(symbol, start_date, end_date, adjust)

    def get_minute(self, *_args, **_kwargs):
        raise LocalDataImportError(
            "本地导入不提供分钟线：--data 仅支持日线 CSV/Parquet")

    # ------------------------------------------------------------------
    def _frame(self, symbol: str) -> pd.DataFrame:
        key = str(symbol)
        if key not in self.frames:
            raise LocalDataImportError(
                f"本地导入数据中没有标的 {key}（已导入：{list(self.frames)}）")
        return self.frames[key]

    @staticmethod
    def _slice(frame: pd.DataFrame, start, end) -> pd.DataFrame:
        out = frame
        if start is not None and str(start).strip():
            out = out[out.index >= pd.Timestamp(str(start))]
        if end is not None and str(end).strip():
            out = out[out.index <= pd.Timestamp(str(end))]
        return out.copy() if len(out) else out.copy()
