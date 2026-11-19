"""数据源可用性矩阵：打印每个市场「当前实际用哪个源、主源是否可用、回退到哪」。

用法：
    python -m tools.source_status           # 探测 + 打印矩阵
    python -m tools.source_status --json    # 输出 JSON（便于第 13 步多源切换做健康检查）

背景：东财 push2his（`stock_zh_a_hist` / `fund_etf_hist_em` / `index_zh_a_hist` /
`*_hist_min_em` 全线）在本机会周期性 `RemoteDisconnected`，此时大量品种实际走新浪/
BaoStock 回退。**回退不是静默的**：`DataFetcher` 每次切换都会打 WARNING，本工具把
「哪个市场靠哪个源」一次性摊开。

⚠️ 第 13 步会在此挂多源自动切换与健康度打分；当前只是「探测 + 如实呈现」，
不做自动改优先级。

本文件的 DAILY_ROUTE 必须与 `core/data_fetcher._fetch_daily` 各 `_fetch_*_daily`
实现逐一对应；改动取数源时请同步这里，否则矩阵会撒谎。
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import date as _date

import akshare as ak
import requests

import config

PROBE_TIMEOUT = 5.0          # 单个后端探测超时（秒），东财挂时不会卡住整体
_PROBE_CACHE: dict = {}      # 同一次运行内不重复探测（backend → (ok, detail, latency)）

BINANCE_HOSTS = ("https://data-api.binance.vision", "https://api.binance.com",
                 "https://api1.binance.com")

# 每个后端探测用的具体接口（打印在连通性表里，便于对照）
BACKEND_DESC = {
    "eastmoney": "stock_zh_a_hist（东财 push2his 统一后端）",
    "sina": "stock_zh_a_daily（新浪 A股日线）",
    "sina_option": "option_sse_daily_sina（新浪期权通道）",
    "sina_futures": "futures_main_sina（新浪期货主力）",
    "sina_forex": "NewForexService.getMinKline（新浪外汇分钟）",
    "baostock": "query_history_k_data_plus（BaoStock 日线）",
    "tencent": "stock_zh_index_daily_tx（腾讯指数日线）",
    "binance": "GET /api/v3/ping（币安公共行情）",
}


def _probe(fn) -> tuple[bool, str, float]:
    """执行一次轻量探测，返回 (是否可用, 说明, 延迟秒数)。

    直连不走 DataFetcher 重试，避免久等；超过 PROBE_TIMEOUT 直接判定不可用
    （探测线程为 daemon，不会阻塞进程退出）。
    """
    box, err = {}, {}

    def run():
        try:
            box["v"] = fn()
        except Exception as exc:  # noqa: BLE001
            err["e"] = exc

    t0 = time.perf_counter()
    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(PROBE_TIMEOUT)
    latency = time.perf_counter() - t0
    if th.is_alive():
        return False, f"超时 >{PROBE_TIMEOUT:.0f}s", latency
    if "e" in err:
        exc = err["e"]
        return False, f"{type(exc).__name__}: {str(exc)[:60]}", latency
    out = box.get("v")
    empty = out is None or len(out) == 0
    return (not empty), ("空返回" if empty else f"{len(out)} 行"), latency


def _probe_baostock():
    import baostock as bs
    login = bs.login()
    try:
        if login.error_code != "0":
            raise RuntimeError(f"{login.error_code} {login.error_msg}")
        rs = bs.query_history_k_data_plus(
            "sh.600519", "date,close",
            start_date=_date.today().replace(day=1).strftime("%Y-%m-%d"),
            end_date=_date.today().strftime("%Y-%m-%d"),
            frequency="d", adjustflag="3")
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        return rows
    finally:
        bs.logout()


def _probe_binance():
    last = None
    for host in BINANCE_HOSTS:
        try:
            resp = requests.get(f"{host}/api/v3/ping", timeout=min(4.0, PROBE_TIMEOUT - 1))
            resp.raise_for_status()
            return [host]
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise last


def _probe_sina_forex():
    # 与 core.data_fetcher._fetch_forex_minute 相同的 JSONP 入口（取最近 60 分钟根）
    url = ("https://vip.stock.finance.sina.com.cn/forex/api/jsonp.php/"
           "var%20_fx_seurusd_60=/NewForexService.getMinKline"
           "?symbol=fx_seurusd&scale=60&datalen=100")
    text = requests.get(url, headers={"Referer": "https://finance.sina.com.cn",
                                      "User-Agent": "Mozilla/5.0"},
                        timeout=min(4.0, PROBE_TIMEOUT - 1)).text
    lo, hi = text.find("["), text.rfind("]")
    if lo < 0 or hi <= lo:
        raise RuntimeError(f"返回格式异常: {text[:60]}")
    return [text[lo:hi + 1]]


def probe_backends() -> dict:
    """探测各共享后端的连通性（每个后端只打一次请求，结果在同一次运行内缓存）。"""
    if _PROBE_CACHE:
        return _PROBE_CACHE
    today = _date.today().strftime("%Y%m%d")
    start = _date.today().replace(day=1).strftime("%Y%m%d")
    probes = {
        "eastmoney": lambda: ak.stock_zh_a_hist(symbol="600519", period="daily",
                                                start_date=start, end_date=today),
        "sina": lambda: ak.stock_zh_a_daily(symbol="sh600519", start_date=start, end_date=today),
        # 新浪期权日线：用一个已到期合约也能取到历史，足以判断通道连通
        "sina_option": lambda: ak.option_sse_daily_sina(symbol="10002513"),
        "sina_futures": lambda: ak.futures_main_sina(symbol="RB0"),
        "sina_forex": _probe_sina_forex,
        "baostock": _probe_baostock,
        "tencent": lambda: ak.stock_zh_index_daily_tx(symbol="sh000300"),
        "binance": _probe_binance,
    }
    for name, fn in probes.items():
        _PROBE_CACHE[name] = _probe(fn)
    return _PROBE_CACHE


# 各市场日线：主源 / 回退链 / 实际链路 / 备注
# ⚠️ 必须与 core/data_fetcher.py 的 _fetch_*_daily 保持一致
DAILY_ROUTE = {
    "cn_stock": ("eastmoney", ["sina"],
                 "stock_zh_a_hist → stock_zh_a_daily", "新浪源 volume=股/amount=元"),
    "cn_etf": ("eastmoney", ["sina"],
               "fund_etf_hist_em → fund_etf_hist_sina", "回退新浪时无法复权（adjust=none）"),
    "cn_convertible": ("sina", [],
                       "bond_zh_hs_cov_daily（仅新浪）", "无成交额，amount=close×volume(张) 估算"),
    "cn_reits": ("eastmoney", ["sina"],
                 "reits_hist_em → fund_etf_hist_sina", "回退新浪时无法复权（adjust=none）"),
    "cn_index": ("eastmoney", ["sina", "baostock"],
                 "index_zh_a_hist → stock_zh_index_daily → BaoStock",
                 "新浪无成交额；tencent 已登记但未接入（其 amount 实为成交量(手)）"),
    "cn_future": ("sina_futures", [], "futures_main_sina（仅新浪期货）", "无成交额，volume=手"),
    "global_future": ("sina_futures", [], "futures_foreign_hist（仅新浪外盘）",
                      "无成交额、无分钟线"),
    "forex": ("eastmoney", [], "forex_hist_em（东财，无日线备源）",
              "分钟走新浪 NewForexService"),
    "cn_option": ("sina_option", [], "option_sse_daily_sina（仅新浪期权通道）",
                  "无成交额；东财无期权日线备源"),
    "crypto": ("binance", [], "Binance /api/v3/klines（多主机轮询）", "不依赖东财/新浪"),
    "hk_stock": ("eastmoney", ["sina"], "stock_hk_hist → stock_hk_daily",
                 "新浪源无成交额（amount=NaN）"),
    "us_stock": ("eastmoney", ["sina"], "stock_us_hist → stock_us_daily",
                 "新浪源无成交额（amount=NaN）"),
    "us_etf": ("eastmoney", ["sina"],
               "同 us_stock（stock_us_hist → stock_us_daily）", "新浪源无成交额"),
    "cn_fund": ("eastmoney", [], "fund_open_fund_info_em（净值曲线，非 K 线）", "无成交量/成交额"),
    "cn_reverse_repo": ("eastmoney", [], "bond_buy_back_hist_em + 东财快照（同一后端）",
                        "收盘价是年化利率，非价格"),
}

# 无公开 K 线的市场（与 core.data_fetcher._NO_KLINE_MARKETS 一致）
NO_KLINE = {
    "private_fund": "净值型，走第 10 步 nav_backtest",
    "qii_product": "净值型，走第 10 步 nav_backtest",
    "otc_deriv": "定价模拟，走第 10 步 derivatives_pricing",
    "neeq": "无公开日线，需第 12 步券商源",
}

SINA_FAMILY = ("sina", "sina_option", "sina_futures", "sina_forex")


def build_matrix(backends: dict) -> list[dict]:
    rows = []
    for market, (primary, fallbacks, chain, note) in DAILY_ROUTE.items():
        ok, detail, latency = backends.get(primary, (None, "未探测", 0.0))
        if ok:
            used, effective = primary, primary
        elif ok is None:  # 后端未探测到，不做结论
            used, effective = primary, "未探测"
        else:
            eff = next((fb for fb in fallbacks if backends.get(fb, (False, "", 0.0))[0]), None)
            if eff:
                used, effective = eff, eff
            elif fallbacks:
                used, effective = "回退链全挂", "无可用"
            else:
                used, effective = "❌ 取不到", "无可用"
        rows.append({
            "market": market,
            "name": config.get_market_config(market).get("name", market),
            "primary": primary,
            "primary_ok": ok,
            "primary_detail": detail,
            "primary_latency": round(latency, 2),
            "fallbacks": fallbacks,
            "used_now": used,
            "effective": effective,
            "daily_chain": chain,
            "minute_priority": config.MINUTE_SOURCE_PRIORITY.get(market, []),
            "note": note,
        })
    for market, why in NO_KLINE.items():
        rows.append({
            "market": market,
            "name": config.get_market_config(market).get("name", market),
            "primary": "-", "primary_ok": None, "primary_detail": why,
            "fallbacks": [], "used_now": "无 K 线", "effective": "无 K 线",
            "daily_chain": why, "minute_priority": [], "note": "",
        })
    return rows


def _w(text: str, width: int) -> str:
    """按显示宽度左对齐（中文按 2 计）。"""
    shown = sum(2 if ord(c) > 0x2E80 else 1 for c in text)
    return text + " " * max(1, width - shown)


def print_matrix(backends: dict, rows: list[dict]) -> None:
    print("\n=== 后端连通性（可用性 / 延迟 / 备注；每后端一次轻量请求，超时 %.0fs） ==="
          % PROBE_TIMEOUT)
    for name, (ok, detail, latency) in backends.items():
        print(f"  {'✅' if ok else '❌'} {_w(name, 14)} {latency:5.2f}s  {detail}   "
              f"← {BACKEND_DESC.get(name, '')}")

    print("\n=== 各市场日线取数源（当前实际情况） ===")
    print(_w("市场", 18) + _w("主源", 14) + _w("主源", 8) + _w("回退链", 20)
          + _w("当前实际", 14) + "备注")
    print("-" * 118)
    for r in rows:
        if r["primary_ok"] is None:
            print(_w(r["market"], 18) + _w("-", 14) + _w("无K线", 8) + _w("-", 20)
                  + _w("净值/定价路径", 14) + r["primary_detail"])
            continue
        fb = ",".join(r["fallbacks"]) or "无"
        print(_w(r["market"], 18) + _w(r["primary"], 14)
              + _w("可用" if r["primary_ok"] else "不可用", 8)
              + _w(fb, 20) + _w(str(r["used_now"]), 14) + r["note"])

    print("\n=== 东财不可达时的影响 ===")
    em_down = not backends.get("eastmoney", (True, "", 0.0))[0]
    print("  东财当前状态：" + ("❌ 不可达（下列即为实际发生的情况）" if em_down else "✅ 可用（下列为预案）"))
    live = [r for r in rows if r["primary_ok"] is not None]

    only_sina = [r["market"] for r in live if r["primary"] in SINA_FAMILY and not r["fallbacks"]]
    sina_fallback = [r["market"] for r in live
                     if r["primary"] not in SINA_FAMILY and "sina" in r["fallbacks"]]
    hard_fail = [r["market"] for r in live
                 if not r["primary_ok"] and not r["fallbacks"]]
    independent = [r["market"] for r in live if r["primary"] == "binance"]

    print(f"  · 只能走新浪系（无其他备源）：{', '.join(only_sina) or '无'}")
    print(f"  · 东财挂时自动回退新浪：{', '.join(sina_fallback) or '无'}")
    print(f"  · 东财挂则直接取不到（无回退）：{', '.join(hard_fail) or '无'}")
    print(f"  · 不依赖东财/新浪：{', '.join(independent) or '无'}")

    em_only_minute = [m for m, v in config.MINUTE_SOURCE_PRIORITY.items()
                      if v and set(v) <= {"eastmoney"}]
    em_first_minute = [m for m, v in config.MINUTE_SOURCE_PRIORITY.items()
                       if v and v[0] == "eastmoney" and len(v) > 1]
    print(f"  · 分钟线仅东财、东财挂则取不到：{', '.join(em_only_minute) or '无'}")
    print(f"  · 分钟线东财优先、可回退：{', '.join(em_first_minute) or '无'}")
    print("  · 回退均打 WARNING：新浪 ETF/REITs 复权因子退化为 1（adjust=none）；"
          "港股/美股/期权新浪源无成交额（amount=NaN + amount_missing）。")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="数据源可用性矩阵")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    print(f"探测中（每后端一次请求，单后端超时 {PROBE_TIMEOUT:.0f}s）…")
    backends = probe_backends()
    rows = build_matrix(backends)
    if args.json:
        print(json.dumps({
            "probed_at": _date.today().isoformat(),
            "probe_timeout_s": PROBE_TIMEOUT,
            "backends": {k: {"ok": v[0], "detail": v[1], "latency_s": round(v[2], 2),
                             "endpoint": BACKEND_DESC.get(k, "")}
                         for k, v in backends.items()},
            "markets": rows,
        }, ensure_ascii=False, indent=2))
        return 0
    print_matrix(backends, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
