"""行情批量下载与导出工具（离线可用、断点续传、随时导出）。

用法（后续第 11 步再并进 main.py）：
    python -m tools.data_export --symbols 600519,510300,AAPL,rb --start 2020-01-01 \
        --end 2026-10-27 --period daily --format csv,parquet
    python -m tools.data_export --watchlist --format parquet
    python -m tools.data_export --update      # 只做增量更新
    python -m tools.data_export --summary     # 只生成数据概览

⚠️ 幸存者偏差提醒：`add_market_batch("index_300")` 拉的是**当前**成分股，
只能用于「看当下行情/批量下载」；历史回测的股票池必须用「时点成分股 Point-in-Time」
（第 13 步），否则回测收益会被系统性高估。
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import date as _date
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd

import config

logger = logging.getLogger("quant.export")

# 周期别名 → 全局周期字符串（唯一权威来源是 config.SUPPORTED_PERIODS）
PERIOD_ALIAS = {"daily": "1d", "1d": "1d", "day": "1d", "weekly": "1w", "1w": "1w",
                "monthly": "1M", "1M": "1M", "1min": "1min", "5min": "5min",
                "15min": "15min", "30min": "30min", "60min": "60min"}

# 导出列（与 config.STANDARD_COLUMNS 对齐，date 落盘为列而不是索引）
EXPORT_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount"]

REQUEST_INTERVAL = float(getattr(config, "REQUEST_INTERVAL",
                                getattr(config, "REQUEST_DELAY", 0.3)))


def _progress(items: Sequence, desc: str = ""):
    """有 tqdm 用进度条，否则退化为普通迭代（不报错）。"""
    try:
        from tqdm import tqdm
        return tqdm(items, desc=desc, ncols=80)
    except ImportError:
        return items


class DataExporter:
    """批量下载 / 导出 / 概览 / 增量更新。"""

    def __init__(self, fetcher=None, export_dir: str = "export"):
        if fetcher is None:
            from core.data_fetcher import DataFetcher
            fetcher = DataFetcher()
        self.fetcher = fetcher
        self.export_dir = Path(export_dir)
        self.csv_dir = self.export_dir / "csv"
        self.parquet_dir = self.export_dir / "parquet"
        self.excel_dir = self.export_dir / "excel"
        for d in (self.csv_dir, self.parquet_dir, self.excel_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.watchlist_path = self.export_dir / "watchlist.csv"
        self.failures: List[dict] = []

    # ---------- 自选清单 ----------
    def load_watchlist(self) -> pd.DataFrame:
        if not self.watchlist_path.exists():
            df = pd.DataFrame(columns=["symbol", "market_type", "name"])
            df.to_csv(self.watchlist_path, index=False, encoding="utf-8-sig")
            return df
        df = pd.read_csv(self.watchlist_path, dtype=str).fillna("")
        return df

    def _save_watchlist(self, df: pd.DataFrame) -> None:
        df.to_csv(self.watchlist_path, index=False, encoding="utf-8-sig")

    def add_symbol(self, symbol: str, market_type: str = "", name: str = "") -> pd.DataFrame:
        df = self.load_watchlist()
        if symbol not in set(df["symbol"]):
            df.loc[len(df)] = [symbol, market_type, name]
            self._save_watchlist(df)
        return df

    def remove_symbol(self, symbol: str) -> pd.DataFrame:
        df = self.load_watchlist()
        df = df[df["symbol"] != symbol]
        self._save_watchlist(df)
        return df

    def add_market_batch(self, kind: str) -> pd.DataFrame:
        """批量加入自选：index_300 / all_etf / all_cb（返回更新后的自选表）。"""
        import akshare as ak

        kind = str(kind).lower()
        if kind == "index_300":
            cons = ak.index_stock_cons_csindex(symbol="000300")
            col = next((c for c in ("成分券代码", "品种代码", "证券代码") if c in cons.columns), cons.columns[0])
            name_col = next((c for c in ("成分券名称", "品种名称", "证券简称") if c in cons.columns), None)
            for _, r in cons.iterrows():
                self.add_symbol(str(r[col]).zfill(6), "cn_stock", str(r[name_col]) if name_col else "")
        elif kind == "all_etf":
            etf = ak.fund_etf_spot_em()
            for _, r in etf.iterrows():
                self.add_symbol(str(r["代码"]), "cn_etf", str(r["名称"]))
        elif kind == "all_cb":
            cb = ak.bond_zh_cov()
            for _, r in cb.iterrows():
                self.add_symbol(str(r["债券代码"]), "cn_convertible", str(r["债券简称"]))
        else:
            raise ValueError(f"未知批量类型: {kind}（index_300/all_etf/all_cb）")
        logger.info("已批量加入自选：%s，当前共 %d 个", kind, len(self.load_watchlist()))
        return self.load_watchlist()

    # ---------- 路径与断点续传 ----------
    def _paths(self, symbol: str, market: str, period: str) -> Dict[str, Path]:
        stem = f"{market}_{symbol}_{period}"
        return {"csv": self.csv_dir / f"{stem}.csv", "parquet": self.parquet_dir / f"{stem}.parquet"}

    def _coverage(self, symbol: str, market: str, period: str):
        """读已导出文件的首末日期（优先 parquet，其次 csv），用于断点续传。"""
        paths = self._paths(symbol, market, period)
        for key in ("parquet", "csv"):
            path = paths[key]
            if not path.exists():
                continue
            try:
                df = pd.read_parquet(path) if key == "parquet" else pd.read_csv(path, usecols=["date"])
                if df.empty:
                    continue
                dates = pd.to_datetime(df["date"])
                return dates.min().date(), dates.max().date()
            except Exception:  # noqa: BLE001 - 坏文件视为未导出
                continue
        return None

    # ---------- 下载 ----------
    def download(self, symbols: Sequence[str], start: str = None, end: str = None,
                 period: str = "daily", adjust: str = "qfq", fmt: Sequence[str] = ("csv",),
                 force: bool = False) -> dict:
        """逐标的下载并导出；命中已覆盖区间直接跳过；失败清单最后统一重试一次。"""
        period = PERIOD_ALIAS.get(str(period).lower(), str(period))
        start = start or getattr(config, "DEFAULT_START", "2020-01-01")
        end = end or _date.today().strftime("%Y-%m-%d")
        fmts = [str(f).lower() for f in ([fmt] if isinstance(fmt, str) else fmt)]
        stats = {"success": 0, "skipped": 0, "failed": 0, "rows": 0, "t0": time.time()}
        frames: Dict[str, pd.DataFrame] = {}
        self.failures = []

        for symbol in _progress(list(symbols), desc="下载行情"):
            symbol = str(symbol).strip()
            if not symbol:
                continue
            try:
                market, _ = self.fetcher._detect_market(symbol, None)
            except Exception:  # noqa: BLE001
                market = "unknown"
            cov = None if force else self._coverage(symbol, market, period)
            if cov and cov[0] <= pd.Timestamp(start).date() and cov[1] >= pd.Timestamp(end).date():
                stats["skipped"] += 1
                continue
            try:
                df = self.fetcher.get_kline(symbol, start, end, period=period, adjust=adjust)
                if df is None or df.empty:
                    raise ValueError("返回空数据")
                self._export(df, symbol, market, period, fmts)
                frames[symbol] = df
                stats["success"] += 1
                stats["rows"] += len(df)
            except Exception as exc:  # noqa: BLE001 - 单标的失败不中断
                logger.warning("下载 %s 失败：%s", symbol, exc)
                self.failures.append({"symbol": symbol, "start": start, "end": end,
                                      "period": period, "error": str(exc)})
            time.sleep(REQUEST_INTERVAL)  # 勿高频调用，避免接口限流

        # 失败清单统一重试一次
        if self.failures:
            retry, self.failures = list(self.failures), []
            for item in retry:
                try:
                    df = self.fetcher.get_kline(item["symbol"], item["start"], item["end"],
                                                period=period, adjust=adjust)
                    if df is None or df.empty:
                        raise ValueError("返回空数据")
                    market, _ = self.fetcher._detect_market(item["symbol"], None)
                    self._export(df, item["symbol"], market, period, fmts)
                    frames[item["symbol"]] = df
                    stats["success"] += 1
                    stats["rows"] += len(df)
                except Exception as exc:  # noqa: BLE001
                    self.failures.append({**item, "error": str(exc)})
                time.sleep(REQUEST_INTERVAL)
        stats["failed"] = len(self.failures)
        stats["elapsed"] = round(time.time() - stats.pop("t0"), 2)
        if "excel" in fmts:
            self._export_excel(frames)
        logger.info("下载完成：成功 %d / 跳过 %d / 失败 %d / 总行数 %d / 耗时 %.2fs",
                    stats["success"], stats["skipped"], stats["failed"],
                    stats["rows"], stats["elapsed"])
        return stats

    # ---------- 导出 ----------
    def _standardize(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out.index = pd.DatetimeIndex(out.index)
        out = out.reset_index()
        out = out.rename(columns={out.columns[0]: "date"})
        out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
        for col in EXPORT_COLUMNS:
            if col not in out.columns:
                out[col] = None
        return out[EXPORT_COLUMNS]

    def _export(self, df: pd.DataFrame, symbol: str, market: str, period: str,
                fmts: Iterable[str]) -> None:
        data = self._standardize(df)
        paths = self._paths(symbol, market, period)
        for fmt in fmts:
            if fmt == "csv":
                data.to_csv(paths["csv"], index=False, encoding="utf-8-sig")
            elif fmt == "parquet":
                data.to_parquet(paths["parquet"], index=False)
            elif fmt == "excel":
                continue  # Excel 走汇总
            else:
                raise ValueError(f"不支持的导出格式: {fmt}")

    def _export_excel(self, frames: Dict[str, pd.DataFrame]) -> Optional[Path]:
        if not frames:
            return None
        if len(frames) > 20:
            logger.warning("标的超过 20 个（%d），Excel 会很大，建议改用 CSV/parquet", len(frames))
        path = self.excel_dir / f"{_date.today():%Y-%m-%d}_行情汇总.xlsx"
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            for symbol, df in frames.items():
                sheet = str(symbol)[:31].replace("/", "_")
                self._standardize(df).to_excel(writer, sheet_name=sheet, index=False)
        return path

    def export_existing(self, symbols: Sequence[str], period: str = "1d",
                        fmt: Sequence[str] = ("csv", "parquet")) -> int:
        """把已落盘的导出文件重新导出为其它格式（不重新取数）。"""
        fmts = [str(f).lower() for f in ([fmt] if isinstance(fmt, str) else fmt)]
        count = 0
        for symbol in symbols:
            market, _ = self.fetcher._detect_market(str(symbol), None)
            cov = self._coverage(str(symbol), market, period)
            if not cov:
                continue
            paths = self._paths(str(symbol), market, period)
            src = paths["parquet"] if paths["parquet"].exists() else paths["csv"]
            df = pd.read_parquet(src) if src.suffix == ".parquet" else pd.read_csv(src)
            df = df[EXPORT_COLUMNS]
            if "csv" in fmts:
                df.to_csv(paths["csv"], index=False, encoding="utf-8-sig")
            if "parquet" in fmts:
                df.to_parquet(paths["parquet"], index=False)
            count += 1
        return count

    # ---------- 概览 ----------
    def summarize(self) -> pd.DataFrame:
        """对已导出数据生成统计表并落盘 export/数据概览_{日期}.csv。"""
        from core.utils import MARKET_NAMES

        rows = []
        watch = self.load_watchlist()
        names = dict(zip(watch["symbol"], watch["name"])) if not watch.empty else {}
        files = sorted(list(self.parquet_dir.glob("*.parquet")) + list(self.csv_dir.glob("*.csv")))
        seen = set()
        for path in files:
            if path.stem in seen:  # 同一标的的 CSV/parquet 只统计一次
                continue
            try:
                df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
            except Exception:  # noqa: BLE001
                continue
            if df.empty or "date" not in df.columns:
                continue
            seen.add(path.stem)
            df["date"] = pd.to_datetime(df["date"])
            # 文件名格式 {market}_{symbol}_{period}，market 自身可能含下划线（cn_stock），
            # 必须从右往左按已知市场名匹配，不能简单按 "_" 切三段
            parts = path.stem.split("_")
            period, market, symbol = parts[-1], None, None
            for i in range(len(parts) - 1, 0, -1):
                cand = "_".join(parts[:i])
                if cand in MARKET_NAMES:
                    market, symbol = cand, "_".join(parts[i:-1])
                    break
            if market is None:
                market, symbol = parts[0], "_".join(parts[1:-1])
            close = pd.to_numeric(df["close"], errors="coerce")
            rows.append({
                "代码": symbol, "名称": names.get(symbol, ""), "市场": market,
                "周期": period,
                "起始日期": df["date"].min().strftime("%Y-%m-%d"),
                "结束日期": df["date"].max().strftime("%Y-%m-%d"),
                "交易日数": len(df),
                "缺失值数": int(df[EXPORT_COLUMNS].isna().sum().sum()),
                "停牌日数": int(df["volume"].fillna(0).eq(0).sum()),
                "最新收盘价": round(float(close.dropna().iloc[-1]), 4) if close.notna().any() else None,
                "区间涨跌幅%": round(float(close.dropna().iloc[-1] / close.dropna().iloc[0] - 1) * 100, 2)
                if close.notna().sum() > 1 else None,
            })
        out = pd.DataFrame(rows)
        path = self.export_dir / f"数据概览_{_date.today():%Y-%m-%d}.csv"
        if not out.empty:
            out.to_csv(path, index=False, encoding="utf-8-sig")
        print(out.to_string(index=False) if not out.empty else "暂无可概览的导出数据")
        logger.info("数据概览已保存：%s", path)
        return out

    # ---------- 增量更新 ----------
    def update_all(self, period: str = "1d", adjust: str = "qfq",
                   fmt: Sequence[str] = ("csv", "parquet")) -> dict:
        """对自选池所有标的只拉上次日期之后的增量并追加到已有文件。"""
        watch = self.load_watchlist()
        stats = {"updated": 0, "no_data": 0, "failed": 0}
        for _, r in _progress(watch.iterrows(), desc="增量更新"):
            symbol = str(r["symbol"]).strip()
            if not symbol:
                continue
            market = str(r.get("market_type") or "").strip() or None
            try:
                if not market:
                    market, _ = self.fetcher._detect_market(symbol, None)
                paths = self._paths(symbol, market, period)
                src = paths["parquet"] if paths["parquet"].exists() else paths["csv"]
                if not src.exists():
                    new = self.fetcher.get_kline(symbol, None, None, period=period, adjust=adjust)
                    if new is None or new.empty:
                        stats["no_data"] += 1
                        continue
                    combined = new
                else:
                    old = pd.read_parquet(src) if src.suffix == ".parquet" else pd.read_csv(src)
                    old["date"] = pd.to_datetime(old["date"])
                    last = old["date"].max()
                    new = self.fetcher.get_kline(symbol, (last + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                                                 None, period=period, adjust=adjust)
                    if new is None or new.empty:
                        stats["no_data"] += 1
                        continue
                    new_std = self._standardize(new)
                    combined = pd.concat([old, new_std], ignore_index=True)
                combined = combined.drop_duplicates(subset=["date"]).sort_values("date")
                std = self._standardize(combined.set_index(pd.to_datetime(combined["date"])))
                if "csv" in [str(f).lower() for f in ([fmt] if isinstance(fmt, str) else fmt)]:
                    std.to_csv(paths["csv"], index=False, encoding="utf-8-sig")
                if "parquet" in [str(f).lower() for f in ([fmt] if isinstance(fmt, str) else fmt)]:
                    std.to_parquet(paths["parquet"], index=False)
                stats["updated"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("增量更新 %s 失败：%s", symbol, exc)
                stats["failed"] += 1
            time.sleep(REQUEST_INTERVAL)
        logger.info("增量更新完成：%s", stats)
        return stats


# ==================== CLI ====================

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="行情批量下载与导出")
    parser.add_argument("--symbols", help="逗号分隔的标的，如 600519,510300,AAPL,rb")
    parser.add_argument("--watchlist", action="store_true", help="使用 export/watchlist.csv 自选池")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--period", default="daily")
    parser.add_argument("--adjust", default="qfq")
    parser.add_argument("--format", default="csv")
    parser.add_argument("--update", action="store_true", help="只做增量更新")
    parser.add_argument("--summary", action="store_true", help="只生成数据概览")
    parser.add_argument("--add", help="加入自选，如 --add 600519")
    parser.add_argument("--batch", help="批量加入自选：index_300/all_etf/all_cb")
    parser.add_argument("--export-dir", default="export")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    exp = DataExporter(export_dir=args.export_dir)

    if args.add:
        print(exp.add_symbol(args.add).to_string(index=False))
        return 0
    if args.batch:
        print(exp.add_market_batch(args.batch).head(20).to_string(index=False))
        return 0
    if args.summary:
        exp.summarize()
        return 0
    if args.update:
        print(exp.update_all(period=PERIOD_ALIAS.get(args.period, args.period),
                             adjust=args.adjust, fmt=args.format.split(",")))
        return 0

    if args.watchlist:
        symbols = [s for s in exp.load_watchlist()["symbol"].tolist() if s]
    elif args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        parser.error("请提供 --symbols 或 --watchlist（或 --update / --summary）")
    stats = exp.download(symbols, args.start, args.end, args.period, args.adjust,
                         fmt=args.format.split(","))
    print(json.dumps(stats, ensure_ascii=False))
    if exp.failures:
        print("失败清单：")
        for f in exp.failures:
            print(" ", f["symbol"], f["error"])
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
