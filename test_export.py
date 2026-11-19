"""第 2 步导出测试：批量下载 / CSV+parquet 导出回读 / 数据概览 / 自选池 / 增量更新 / CLI。"""
from __future__ import annotations

import sys
import shutil
import tempfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tools.data_export import EXPORT_COLUMNS, DataExporter, main as export_main

PASS, FAIL = [], []
# 每次运行使用独立临时目录：避免上次导出的缓存命中导致 download 被 skip（测试必须幂等）
EXPORT_DIR = Path(tempfile.mkdtemp(prefix="dda_export_"))
SYMBOLS = ["600519", "510300", "AAPL"]


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'✅' if ok else '❌'} {name}" + (f" | {detail}" if detail else ""))


def main() -> int:
    end = date.today()
    start = (end - timedelta(days=365)).strftime("%Y-%m-%d")
    end_s = end.strftime("%Y-%m-%d")

    exp = DataExporter(export_dir=str(EXPORT_DIR))

    # 1) 批量下载并导出 CSV + parquet
    stats = exp.download(SYMBOLS, start, end_s, period="daily", adjust="qfq",
                         fmt=("csv", "parquet"))
    check("批量下载 600519/510300/AAPL 近一年日线", stats["success"] == 3 and stats["failed"] == 0,
          f"成功 {stats['success']} / 跳过 {stats['skipped']} / 失败 {stats['failed']} / "
          f"{stats['rows']} 行 / {stats['elapsed']}s")

    # 2) 回读校验：行数一致、列名严格为 date,open,high,low,close,volume,amount
    rows_ok, cols_ok, values_ok = True, True, True
    detail = []
    for symbol in SYMBOLS:
        market, _ = exp.fetcher._detect_market(symbol, None)
        paths = exp._paths(symbol, market, "1d")
        if not (paths["csv"].exists() and paths["parquet"].exists()):
            rows_ok = cols_ok = values_ok = False
            detail.append(f"{symbol}=文件缺失")
            continue
        csv_df = pd.read_csv(paths["csv"])
        pq_df = pd.read_parquet(paths["parquet"])
        cols_ok &= list(csv_df.columns) == EXPORT_COLUMNS and list(pq_df.columns) == EXPORT_COLUMNS
        rows_ok &= len(csv_df) == len(pq_df) and len(csv_df) > 200
        close_diff = float(np.nanmax(np.abs(
            pd.to_numeric(csv_df["close"]).to_numpy() - pd.to_numeric(pq_df["close"]).to_numpy())))
        values_ok &= close_diff < 1e-6
        detail.append(f"{symbol}:{len(csv_df)}行/close差{close_diff:.1e}")
    check("CSV 与 parquet 行数一致且 > 200", rows_ok, "，".join(detail))
    check(f"回读列名严格为 {','.join(EXPORT_COLUMNS)}", cols_ok)
    check("CSV 与 parquet 收盘价数值一致", values_ok)

    # 3) 日期连续性与导出区间
    market, _ = exp.fetcher._detect_market("600519", None)
    out = pd.read_csv(exp._paths("600519", market, "1d")["csv"])
    dates = pd.to_datetime(out["date"])
    check("导出日期升序且落在请求区间内",
          bool(dates.is_monotonic_increasing) and dates.min() >= pd.Timestamp(start)
          and dates.max() <= pd.Timestamp(end_s),
          f"{dates.min():%Y-%m-%d} ~ {dates.max():%Y-%m-%d}")

    # 4) 数据概览
    summary = exp.summarize()
    overview = EXPORT_DIR / f"数据概览_{date.today():%Y-%m-%d}.csv"
    check("数据概览生成（CSV/parquet 去重后每标的一行）",
          not summary.empty and overview.exists()
          and set(summary["代码"]) == set(SYMBOLS) and len(summary) == len(SYMBOLS)
          and {"起始日期", "结束日期", "交易日数", "最新收盘价"} <= set(summary.columns),
          f"{len(summary)} 行 → {overview.name}")

    # 5) 自选池增删
    exp.add_symbol("600519", "cn_stock", "贵州茅台")
    watched = exp.load_watchlist()
    check("自选池加入标的", "600519" in set(watched["symbol"]), f"共 {len(watched)} 个")
    exp.add_symbol("999999", "cn_stock", "临时标的")
    exp.remove_symbol("999999")
    check("自选池删除标的", "999999" not in set(exp.load_watchlist()["symbol"]))

    # 6) 增量更新（已覆盖到昨日，正常应无可补数据或只补最新一天）
    upd = exp.update_all(period="1d")
    check("增量更新可执行且无失败", upd["failed"] == 0,
          f"更新 {upd['updated']} / 无新数据 {upd['no_data']} / 失败 {upd['failed']}")

    # 7) CLI 入口（单标的 + 概览）
    rc = export_main(["--symbols", "600519", "--start", start, "--end", end_s,
                      "--format", "csv", "--export-dir", str(EXPORT_DIR)])
    check("CLI 下载入口可用", rc == 0, f"返回码 {rc}")
    rc2 = export_main(["--summary", "--export-dir", str(EXPORT_DIR)])
    check("CLI 概览入口可用", rc2 == 0, f"返回码 {rc2}")

    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    shutil.rmtree(EXPORT_DIR, ignore_errors=True)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
