"""统一数据层（18 个品种全支持）

对外统一接口：get_daily / get_minute / get_realtime / get_symbol_list。
内部先用 config.detect_market_type 识别市场，再路由到各市场取数方法，
所有数据统一为 ['date','open','high','low','close','volume','amount']（date 为索引）。

【复权约定（重要）】
  - cn_stock / cn_etf / cn_fund 采用「原始价 + 复权因子」分离存储：
      data_cache/raw/{market}_{symbol}_daily_raw.csv        不复权原始价
      data_cache/adj_factors/{market}_{symbol}_daily_factors.csv  qfq_factor / hfq_factor
    复权价 = 原始价 × 因子（现算），绝不缓存"已复权"价格，避免增量拼接时复权基准漂移。
  - 其他市场（期货/外汇/加密等）本身无复权概念，adjust 参数被忽略。

【数据源与单位约定（实测见 INTERFACE_UNITS 表，禁止按成交额反推）】
  接口                                      volume 单位   amount 单位   复权
  ak.stock_zh_a_hist（东财·A股历史）           手           元            qfq/hfq
  ak.stock_zh_a_daily（新浪·A股历史）          股           元            qfq/hfq（本地因子）
  ak.fund_etf_hist_em（东财·ETF历史）          手           元            qfq/hfq
  ak.fund_etf_hist_sina（新浪·ETF/REITs回退）   份           元            qfq/hfq（本地因子）
  ak.stock_hk_hist / stock_hk_daily          股           元(港元)       支持
  ak.stock_us_hist                           股           美元          支持
  ak.bond_zh_hs_cov_daily（新浪）             张           无（估算）     不支持
  ak.bond_zh_hs_cov_min（东财）               手(10张)      元            不支持
  ak.futures_main_sina / futures_foreign_hist  手          无（不估算）   不支持
  ak.reits_hist_em                           手           元            支持
  ak.fund_open_fund_info_em                  0（净值）    0（净值）      累计净值
  Binance /api/v3/klines                     币           计价货币       不支持
  注 1：新浪历史K线接口（klc_kl.js / hq.sinajs.cn）与新浪分钟线（CN_MarketData.getKLineData）
      均原生返回**不复权**价（2026-10-28 实测：600519 共 492 个交易日，分钟收盘/不复权日线收盘 = 1.0000），
      复权一律由本地因子计算。
  注 2：对外统一口径 volume=股（转债=张、REITs=份、加密=币）、amount=元（或计价货币）。
      期货是唯一例外：volume 保留「手」，因为 1 手对应品种特定的合约乘数（吨/桶/克），
      统一 ×100 会失真；需要「吨/桶」时请乘 config.get_market_config()["multiplier"]。
      ⚠️ 期货的 amount≈close×volume **不成立**（无成交额字段），流动性过滤必须单独取「成交额(元)」，
      禁止用 volume×close 估算。
  注 3：新浪接口反爬强、易封 IP，所有全市场扫描类方法（标的列表/批量因子取数）
      必须经 _request 节流（>=0.3s）并带指数退避——勿高频调用。
  注 4：A股分钟线分两种场景选源：
      历史回填（end_date 早于今天）→ BaoStock（5/15/30/60 分钟、1990 年起、volume=股、adjustflag=3）；
      当日/盘中（end_date >= 今天）→ 新浪/东财（BaoStock 只有盘后数据、无实时行情）。
      新浪（A股/ETF 单次最多 1970 根、期货 1023 根、外汇约 974 根）与东财（约 1 个月）作为近期补充；
      BaoStock 分钟线不含指数，指数分钟直接走新浪。超出源上限时 attrs 标注 minute_history_capped=True。
  注 5：分钟线落自建增量库 data_cache/minute/{market}_{symbol}_{period}.parquet，
      每次读库 → 补末尾增量 → 按「日线索引 + 节假日日历」双重校验找中段缺口并回填 →
      合并去重写回；无法回填的缺口写 attrs gap_dates / gap_count 并 WARNING，
      「日历开市但日线缺该日」写 attrs daily_gap_dates / daily_gap_count 并 WARNING（疑似日线缺口）；
      返回 attrs 含 available_from / minute_history_capped / source / adjust。
  注 6：A股复权因子统一取 BaoStock query_adjust_factor（日线与分钟线同源）：
      字段实测为 code/dividOperateDate/foreAdjustFactor/backAdjustFactor/adjustFactor；
      取不到时回退 AKShare 口径并显式告警，字段名不匹配直接抛错（不得退化成"不支持复权"）。
  注 7：BaoStock 会话由 _bs_execute 统一管理，命中「未登录/登录过期」自动 logout→login→
      重试一次（模块级单例可能在长时间运行或盘中失效）。

【stale（过期）数据的使用边界 —— 实盘安全，禁止放宽】
  - 判定：本地库最后一根 K 线日期 与「最近一个已收盘交易日」之间的【交易日数差】（交易日历计算），
    差 > 0 即 attrs["stale"]=True、attrs["stale_days"]=N，并打 WARNING。
    最近已收盘交易日按【各市场自己的时钟】判定（A股15:00 / 港股16:00 / 美股美东16:00含夏令时 /
    期货含夜盘 / 外汇近24h / 加密7×24），见 _latest_completed_trading_day。
  - 上限：config.STALE_LIMIT（日线 5 / 分钟 2 个交易日），禁止就地写死。
  - 允许：回测 / 研究 / 因子计算；图表展示（必须标注「数据截至 X 日」，见 core/chart.py）。
  - 禁止：模拟盘 / 实盘的下单决策。

【双重防线 —— 下单时效保护不得依赖上游是否传参】
  第一道防线：本文件 for_trading=True 时遇 stale 直接报错（调用方显式声明用途）。
  第二道防线：config.RUN_MODE ∈ {paper, live} 时，即使调用方【忘记传 for_trading】，
              stale（或超过 STALE_LIMIT）也一律报错；backtest 模式豁免（回测按定义就跑历史数据）。
  第三道防线（第 4 步必做）：core/account.py 的订单模块必须【独立】调用
              assert_fresh_for_trading() 做下单前时效复核，不得依赖数据层是否已经拦过。
  验收判据：把数据层的 for_trading 全部去掉，paper/live 下单链路仍须拦得住 stale 数据。
  ⚠️ attrs 易失：rolling/ewm/expanding 会清空 attrs（config.ATTRS_FRAGILE_NOTE），
     指标计算后 stale 标记就没了 —— 因此出口统一把时效物化为普通列
     config.STALE_INFO_COLUMN（data_asof_date，逐行＝本帧最新日期，能穿透窗口运算），
     下单前用 assert_fresh_for_trading 优先读该列，其次 refetch，仅「无列且无法重取」才 fail-closed。
  ⚠️ 指标/因子函数不要在内部透传 attrs，应在入口处判定时效并存到局部变量。

【重要约定】市场交易规则参数一律通过 config.get_market_config(market_type) 获取，
禁止直接写 config.MARKETS[...]。
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import re
import time
from datetime import date as _date
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Sequence, Union

import akshare as ak
import numpy as np
import pandas as pd
import requests

try:  # BaoStock 为可选依赖：未安装时自动回退新浪/东财
    import baostock as bs
except Exception:  # noqa: BLE001
    bs = None

import config
from core.utils import (CN_CALENDAR_AVAILABLE, CN_MARKETS, get_trading_sessions,
                        is_trading_day, re_sample_kline, setup_logger)
from data import versioning  # 13.0：缓存口径标记（读前校验，缺标记 fail-closed）

STANDARD_COLUMNS = list(config.STANDARD_COLUMNS)
_PRICE_COLUMNS = ["open", "high", "low", "close"]

# 需要「原始价 + 复权因子」分离存储的市场
_ADJ_MARKETS = {"cn_stock", "cn_etf", "cn_fund", "cn_reits"}
# 不走 K 线接口、只走净值/定价路径的市场（显式声明，避免静默留空）
_NO_KLINE_MARKETS = {
    "private_fund": "私募证券基金：净值型产品，走净值回测路径（第 10 步 nav_backtest），无公开 K 线",
    "qii_product": "券商资管/信托/私募理财：净值型产品，走净值回测路径（第 10 步），无公开 K 线",
    "otc_deriv": "场外衍生品：走定价模拟路径（第 10 步 derivatives_pricing），无 K 线",
    "neeq": "新三板：akshare 无公开日线接口，需券商数据源（第 12 步 broker 适配层）",
}

# 路由前先显式校验市场是否支持，避免「不支持」被 DataRouter 误判成「源故障」后转成
# DataUnavailableError（会改写既有报错文案）。仅列真正走取数实现的市场。
# v3.47：支持清单唯一来源是 config.SUPPORTED_KLINE_MARKETS，本模块不得另写一份。
# 两份清单并存时，加一个市场就必然在「支持清单」和「接口索引桥」之间漂开。
_SUPPORTED_DAILY_MARKETS = frozenset(
    (getattr(config, "SUPPORTED_KLINE_MARKETS", None) or {}).get("daily") or ())
# 分钟线：只列真正取数的市场；按设计直接抛错的市场（期权/场外基金/国际期货等）
# 不进路由，保持原有报错文案不变。
_SUPPORTED_MINUTE_MARKETS = frozenset(
    (getattr(config, "SUPPORTED_KLINE_MARKETS", None) or {}).get("minute") or ())

# 单点故障市场的「为什么」——配合 config.SINGLE_SOURCE_MARKETS 生成显式报错。
# 这些市场失败时绝不静默返回空表，否则第 3 步算指标会得到一堆 NaN 而不自知。
_SINGLE_SOURCE_REASON = {
    "forex": "日线仅东财 forex_hist_em，无备源",
    "cn_fund": "场外基金净值仅东财 fund_open_fund_info_em，无备源",
    "cn_reverse_repo": "历史与快照都走东财（同一 push2his 后端）",
    "cn_convertible": "分钟线仅东财 bond_zh_hs_cov_min（日线走新浪）",
    "us_stock": "分钟线仅东财 stock_us_hist_min_em（日线可回退新浪）",
    "us_etf": "分钟线仅东财 stock_us_hist_min_em（日线可回退新浪）",
    "hk_stock": "分钟线仅东财 stock_hk_hist_min_em（日线可回退新浪）",
}


def _single_source_error(market: str, symbol: str, kind: str, detail) -> RuntimeError:
    return RuntimeError(
        f"[{market}] {symbol} {kind}获取失败：该市场当前无可用数据源"
        f"（{_SINGLE_SOURCE_REASON.get(market, '仅单一数据源')}）。原因：{detail}")


def _stale_gate_enabled(mode: str = None) -> bool:
    """时效闸门是否生效：仅在 paper/live 且 config.TRADING_REQUIRE_FRESH=True 时生效。

    backtest 必须豁免——回测按定义就用历史数据跑过去，相对今天永远「过期」。
    """
    return bool(config.TRADING_REQUIRE_FRESH) and \
        str(mode or config.RUN_MODE or "backtest").strip().lower() in ("paper", "live")


def _trading_days_after(asof, market: str) -> int:
    """asof（date/Timestamp）之后、到「最近已收盘交易日」之间隔了几个交易日。"""
    if asof is None:
        return 0
    last = pd.Timestamp(asof).normalize()
    ref = pd.Timestamp(DataFetcher._latest_completed_trading_day(market))
    if last >= ref:
        return 0
    days, day = 0, (last + pd.Timedelta(days=1)).date()
    while pd.Timestamp(day) <= ref:
        if is_trading_day(day, market):
            days += 1
        day += timedelta(days=1)
    return days


_DEFAULT_FETCHER = None
_REFETCH_CACHE: dict = {}  # (market, symbol, kind, period) → {"ts", "asof", "error"}，TTL 内复用


def _default_fetcher() -> "DataFetcher":
    global _DEFAULT_FETCHER
    if _DEFAULT_FETCHER is None:
        _DEFAULT_FETCHER = DataFetcher()
    return _DEFAULT_FETCHER


def _refetch_latest_asof(market: str, symbol: str, kind: str,
                         fetcher: "DataFetcher" = None, period: str = "60"):
    """从数据层重取该标的最新数据，返回最后一根 bar 的日期（TTL 内复用）。

    组合调仓会对几十上百个标的重复校验，同批次结果复用 config.STALE_REFETCH_TTL_SEC 秒，
    避免逐单打满数据源。失败结果也会缓存，避免同一批里对同一个坏标的反复重试。
    """
    key = (market, str(symbol), kind, period if kind != "daily" else "")
    ttl = float(config.STALE_REFETCH_TTL_SEC)
    now = time.time()
    hit = _REFETCH_CACHE.get(key)
    if hit and (now - hit["ts"]) <= ttl:
        if hit["error"] is not None:
            raise hit["error"]
        return hit["asof"]
    try:
        f = fetcher or _default_fetcher()
        start = (pd.Timestamp.today() - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        end = pd.Timestamp.today().strftime("%Y-%m-%d")
        probe = (f.get_daily(symbol, start, end, adjust="", market_type=market)
                 if kind == "daily"
                 else f.get_minute(symbol, period, start, end, market_type=market))
        if probe is None or len(probe) == 0:
            raise RuntimeError("refetch 返回空表")
        asof = pd.Timestamp(probe.index.max()).normalize()
        _REFETCH_CACHE[key] = {"ts": now, "asof": asof, "error": None}
        return asof
    except Exception as exc:  # noqa: BLE001
        _REFETCH_CACHE[key] = {"ts": now, "asof": None, "error": exc}
        raise


def assert_fresh_for_trading(df: pd.DataFrame, kind: str = "daily",
                             market: str = None, symbol: str = None,
                             fetcher: "DataFetcher" = None, period: str = "60",
                             run_mode: str = None, for_trading: bool = False,
                             order_side: str = "open") -> bool:
    """下单前【独立】时效复核（第 4 步 core/account.py 必须调用，不依赖上游 for_trading）。

    判读顺序（按真实链路修正，禁止因「决策帧没有时效列」就 fail-closed）：
      1) 下单闸门本来就有 market+symbol → **默认直接 refetch 最新数据**比对交易日历，
         完全不依赖传入帧（策略的决策帧由 MA/RSI 等纯函数 Series 拼成，物化列根本带不过来）；
      2) 拿不到 market+symbol（或 refetch 模式关闭）时，退回读物化列
         config.STALE_INFO_COLUMN（多标的帧按 symbol 只读该标的自己的行）；
      3) 实在没有列时再读 attrs["last_bar"]；
      4) 以上都没有才 fail-closed（config.FAIL_CLOSED_NOTE）。
    refetch 失败（网络/源不可达）按 config.STALE_REFETCH_FAIL_POLICY 处置：
    order_side="open" 拒单、"close" 放行（不能因为取不到行情下不出止损/平仓单）。
    回测（RUN_MODE=backtest）默认放行，但显式 for_trading=True 时仍拦（预演「上实盘会怎样」）。
    """
    tag = f"[{market or '-'}] {symbol or '-'} {kind}"
    if not (_stale_gate_enabled(run_mode) or for_trading):
        return True  # 回测按定义就跑历史数据；仅显式 for_trading 时才预演拦截
    if df is None or len(df) == 0:
        raise RuntimeError(f"{tag} 无数据，拒绝下单")

    col = config.STALE_INFO_COLUMN
    mode = str(config.STALE_CHECK_MODE).lower()
    asof, source, refetch_err = None, "", None

    # 1) 下单闸门持有标的与市场 → 以 refetch 为主，不依赖决策帧
    if mode == "refetch" and market and symbol:
        try:
            asof = _refetch_latest_asof(market, symbol, kind, fetcher, period)
            source = "refetch 重取"
        except Exception as exc:  # noqa: BLE001
            refetch_err = exc

    # 2) 退回物化列：多标的帧只读该标的自己的行（禁止整列广播掩盖过期标的）
    if asof is None:
        sub = df
        if "symbol" in getattr(df, "columns", []) and symbol:
            sub = df[df["symbol"].astype(str) == str(symbol)]
            if len(sub) == 0:
                sub = df
        if col in getattr(sub, "columns", []):
            try:
                asof = pd.to_datetime(sub[col], errors="coerce").max()
                source = f"物化列 {col}"
            except Exception:  # noqa: BLE001
                asof = None

    # 3) 最后才看 attrs
    if asof is None or pd.isna(asof):
        asof = None
        attrs = getattr(df, "attrs", {}) or {}
        if attrs.get("last_bar"):
            asof = pd.Timestamp(attrs["last_bar"]).normalize()
            source = "attrs.last_bar"

    # 4) 都没有：refetch 失败按开/平仓策略处置，否则 fail-closed
    if asof is None:
        if refetch_err is not None:
            policy = str(config.STALE_REFETCH_FAIL_POLICY.get(order_side, "reject")).lower()
            if policy == "allow":
                return True  # 平仓放行：不能因为取不到数据就下不出止损/平仓单
            raise RuntimeError(
                f"{tag} 无法确认数据时效：refetch 失败（{type(refetch_err).__name__}: "
                f"{refetch_err}），{order_side} 单按策略拒绝") from refetch_err
        raise RuntimeError(
            f"{tag} 无法确认数据时效：既无 {col} 列，也无法重取（需传 market+symbol）；"
            f"{config.FAIL_CLOSED_NOTE}")

    if not market:
        raise RuntimeError(f"{tag} 无法确认数据时效：未提供 market，无法按交易日历判定；"
                           f"{config.FAIL_CLOSED_NOTE}")
    n = _trading_days_after(asof, market)
    limit = int(config.STALE_LIMIT.get(kind, 0))
    if n > 0:
        raise RuntimeError(
            f"{tag} 数据已过期（最后数据日 {pd.Timestamp(asof):%Y-%m-%d}，距最近已收盘交易日 "
            f"{n} 个交易日，上限 {limit}；来源：{source}），禁止用于模拟盘/实盘下单决策")
    return True


# 各接口返回的中英文列名统一映射
_COLUMN_MAP = {
    "日期": "date", "时间": "date", "datetime": "date", "date": "date", "day": "date",
    "净值日期": "date",
    "开盘": "open", "今开": "open", "开盘价": "open", "open": "open",
    "最高": "high", "最高价": "high", "high": "high",
    "最低": "low", "最低价": "low", "low": "low",
    "收盘": "close", "最新价": "close", "收盘价": "close", "close": "close",
    "成交量": "volume", "volume": "volume",
    "成交额": "amount", "amount": "amount",
    "单位净值": "close", "累计净值": "close",
}

_HK_TICK_MAP = [
    (0.25, 0.001), (0.5, 0.005), (10, 0.01), (20, 0.02), (100, 0.05),
    (200, 0.1), (500, 0.2), (1000, 0.5), (2000, 1), (5000, 2), (math.inf, 5),
]

# 场内期权标的名称映射（akshare option_finance_board 使用中文全称）
_OPTION_UNDERLYING_MAP = {
    "510050": "华夏上证50ETF期权", "510300": "华泰柏瑞沪深300ETF期权",
    "510500": "南方中证500ETF期权", "588000": "华夏上证科创板50ETF期权",
    "159915": "易方达创业板ETF期权", "159919": "嘉实沪深300ETF期权",
}
_OPTION_SYMBOL_SHORT = {
    "510050": "50ETF", "510300": "300ETF", "510500": "500ETF",
    "588000": "科创板50ETF", "159915": "创业板ETF", "159919": "300ETF",
}

# ==================== 接口单位约定表（由 config.DATA_SOURCE_UNITS 派生） ====================
# 字段顺序：
#   (源 volume 单位, 源 amount 单位, volume 换算系数, amount 换算系数,
#    统一后 volume 单位, 统一后 amount 单位, 是否已确证, 证据)
# 说明：
#   - 换算系数用于把源单位换到统一口径：volume=股/张/份/币、amount=元（期货例外保留「手」）；
#   - 未确证的接口在返回 DataFrame.attrs 里写 unit_uncertain=True，绝不静默反推；
#   - 口径的唯一事实源是 config.DATA_SOURCE_UNITS，本表只做格式转换，禁止在此另写一套。
INTERFACE_UNITS: Dict[str, tuple] = {
    name: (spec["volume"], spec["amount"], float(spec["volume_factor"]),
           float(spec["amount_factor"]), spec["unified_volume"], spec["unified_amount"],
           bool(spec["verified"]), spec["evidence"])
    for name, spec in config.DATA_SOURCE_UNITS.items()
}

# A股指数代码（BaoStock 分钟线不含指数 → 直接走新浪）
_CN_INDEX_CODES = {
    "000016", "000300", "000688", "000852", "000905", "000985",
    "399001", "399005", "399006", "399300", "399905",
}

# BaoStock 会话（模块级单例；SDK 自带 socket，登录一次可复用）
_BS_STATE = {"logged_in": False}

# 会话失效特征：error_code 或 error_msg 命中即判定「未登录/登录过期」，需重置会话重登
_BS_SESSION_CODES = {"10001001", "10002001", "10002007"}
_BS_SESSION_HINTS = ("未登录", "登录已过期", "登录失效", "session", "logout")


class _BsSessionExpired(RuntimeError):
    """BaoStock 会话失效（未登录 / 登录过期），由 _bs_execute 重置会话后重试。"""


class JumpAuditError(RuntimeError):
    """港股跳变审计拦截（|隔夜|>阈值且事件表无解释）。

    属口径结构性拒绝而非网络失败：get_daily 的「返回过期缓存」兜底必须
    放行本异常向上传播，禁止用子集缓存帧冒充全区间帧（fail-open）。
    """




class DataFetcher:
    """统一数据入口：本地缓存优先，缺失/过期才请求接口，带延时与重试。"""

    def __init__(self, cache_dir: Union[str, Path] = None,
                 request_delay: float = None, max_retry: int = None):
        self.cache_dir = Path(cache_dir or config.DATA_CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        for sub in ("raw", "factors", "snapshots", "adj_factors", "index_members",
                    "constituents", "lists", "minute"):
            (self.cache_dir / sub).mkdir(parents=True, exist_ok=True)

        self.request_delay = float(config.REQUEST_DELAY if request_delay is None else request_delay)
        self.max_retry = int(max(config.MAX_RETRY, 4) if max_retry is None else max_retry)
        self.expire_days = dict(config.DATA_CACHE_EXPIRE_DAYS)

        self.logger = setup_logger("data_fetcher", config.LOG_DIR / "data_fetcher.log")
        self._last_request = 0.0
        self._us_code_map: Optional[Dict[str, str]] = None
        self._hk_lot_cache: Dict[str, int] = {}
        self._dominant_cache: Dict[str, str] = {}

    # ==================== 对外统一接口 ====================

    def get_daily(self, symbol: str, start_date: str = None, end_date: str = None,
                  adjust: str = "qfq", fill_missing: bool = False,
                  market_type: str = None, for_trading: bool = False) -> pd.DataFrame:
        """获取日线，返回索引为 date 的标准 DataFrame。

        adjust: 'qfq' 前复权（默认）/ 'hfq' 后复权 / '' 或 'none' 不复权。
        fill_missing: 仅图表展示用，True 时对 OHLC 做前值填充；指标/回测必须保持 False。
        market_type: 显式指定市场，用于 ZN/GC 这类歧义代码（不传则按默认并告警）。
        for_trading: 声明该数据用于模拟盘/实盘下单；此时遇到 stale 数据直接抛错，
                     禁止把过期价格喂进下单链路（回测/研究保持默认 False）。
        """
        symbol = self._normalize_symbol(symbol)
        market, hint = self._detect_market(symbol, market_type)
        if market in _NO_KLINE_MARKETS:
            raise ValueError(f"[{market}] {_NO_KLINE_MARKETS[market]}")
        start = self._to_date_str(start_date or config.DEFAULT_START)
        end = self._to_date_str(end_date or config.DEFAULT_END or _date.today().strftime("%Y%m%d"))
        adjust = self._normalize_adjust(adjust)
        if market == "cn_index":
            # 指数无复权概念：缓存名显式标 none，避免把不复权价存成 qfq 误导下游
            adjust = "none"
        if market == "hk_stock":
            # 港股日线走自建双价出口（_fetch_hk_stock_daily）：fetch 固定 raw 取数、
            # 双价在出口内构建，请求口径对出口帧无影响——缓存名统一标 none，
            # 避免 qfq 文件名装 hfq_self_built/raw-only 内容造成口径错位
            # （与 cn_index 同构处理，v3.54 港股正式接入）
            adjust = "none"
        if market in ("us_stock", "us_etf"):
            # 美股事件闸（评审 2026-11-26 裁定选③人工事件表）必须挡在【路由之前】：
            # DataRouter 适配器路径会绕过 _fetch_us_stock_daily 的出口闸
            # （实测 AAPL 经 router 直连成功、TSLA 失败才落老链路——同一闸门
            # 两种行为不可接受）。manual_events 已登记标的放行走自建双价出口；
            # 未登记标的（含后续新增）保持 fail-closed raise，禁止降级跑回测
            us_conf = getattr(config, "US_STOCK_CONFORMANCE", {}) or {}
            us_registry = {str(k).upper() for k in (us_conf.get("manual_events") or {})}
            if str(symbol).upper() not in us_registry and str(
                    us_conf.get("manual_events_mode") or "raise_unlisted") == "raise_unlisted":
                raise RuntimeError(
                    f"美股 {symbol} 未在治理面 manual_events 登记分红/拆股事件覆盖"
                    f"（manual_events_mode=raise_unlisted）：fail-closed 禁止取数/"
                    "回测——仅放行已逐位核对官方披露数据并登记完整事件的标的，"
                    "禁止降级")
            # 与港股同构：缓存名统一标 none（出口固定 raw 取数、双价自建，
            # 请求口径对出口帧无影响，qfq/hfq 文件名装黑箱复权价会造成口径错位）
            adjust = "none"

        if market in _ADJ_MARKETS:
            raw = self._get_raw_daily(market, symbol, start, end)
            if adjust == "":
                df = raw
            else:
                factor = self._get_adj_factor(market, symbol, raw.index.min() if not raw.empty else None)
                df = self._apply_adjust(raw, factor, adjust, market, symbol)
            df = self._finalize(df, market, start, end, fill_missing)
            df.attrs["raw_source"] = raw.attrs.get("source", "unknown")
            df.attrs.update(hint)
            # 原始价走 stale 兜底时，stale 标记由 _get_raw_daily 写入并随 attrs 传下来
            for key in ("stale", "stale_days", "stale_limit", "last_bar"):
                if key in raw.attrs:
                    df.attrs[key] = raw.attrs[key]
            df = self._attach_asof(df)
            return self._enforce_stale(df, market, symbol, "daily", for_trading)

        cache_file = self._cache_path(market, symbol, "daily", adjust)
        cached = self._read_cache(cache_file)
        if market in ("hk_stock", "us_stock", "us_etf") and cached is not None and (
                "dual_price" not in cached.attrs or "adjust" not in cached.attrs):
            # 自建双价出口启用前的旧缓存缺双价标注：口径不明，fail-closed 拒读
            # （00700 曾出现 21 行旧毒缓存被静默喂给下游；美股 precheck 期旧缓存
            # 同为无事件 raw 帧），必须删除后重取
            raise RuntimeError(
                f"[{market}] {symbol} 日线缓存缺双价口径标注"
                f"（dual_price/adjust，{cache_file.name}）："
                "旧版缓存禁止静默读取，请删除该缓存文件后重取")
        if cached is not None and not self._cache_expired(cache_file, "daily") \
                and self._covers(cached, start, end) \
                and not self._last_bar_incomplete(cache_file, cached, market):
            out = cached.loc[start:end].copy()
            out.attrs.update(cached.attrs)
            out.attrs.update(hint)
            return self._attach_asof(out)

        try:
            df = self._fetch_daily(market, symbol, start, end, adjust)
            if (df is None or df.empty) and market in config.SINGLE_SOURCE_MARKETS["daily"]:
                # 单点市场返回空表＝数据源实质不可用，必须抛错而不是让下游拿到空表
                raise _single_source_error(market, symbol, "日线", "数据源返回空表")
            df = self._quality_check(df, market, symbol)
            self._save_cache(df, cache_file)
            out = self._finalize(df, market, start, end, fill_missing)
            out.attrs.update(hint)
            return self._attach_asof(out)
        except JumpAuditError:
            raise    # 口径结构性拒绝：禁止被「返回过期缓存」兜底吞成 fail-open
        except Exception as exc:  # noqa: BLE001 - 接口失败不阻断，优先返回旧缓存
            if cached is not None:
                stale = cached.loc[start:end].copy()
                if not stale.empty:
                    self.logger.warning("[%s] %s 日线拉取失败(%s)，返回过期缓存", market, symbol, exc)
                    stale.attrs.update(cached.attrs)
                    stale.attrs.update(hint)
                    stale.attrs["stale"] = True
                    stale = self._mark_stale(stale, market, "daily")
                    stale = self._attach_asof(stale)
                    return self._enforce_stale(stale, market, symbol, "daily", for_trading)
                raise RuntimeError(
                    f"[{market}] {symbol} 拉取失败({exc})，且本地缓存不覆盖 {start}-{end}") from exc
            if market in config.SINGLE_SOURCE_MARKETS["daily"]:
                self.logger.error("[%s] %s 日线无可用数据源：%s", market, symbol, exc)
                raise _single_source_error(market, symbol, "日线", exc) from exc
            raise

    def _finalize(self, df: pd.DataFrame, market: str, start: str, end: str,
                  fill_missing: bool = False) -> pd.DataFrame:
        """裁剪区间 + 统一列顺序；fill_missing 仅供图表使用。"""
        if df is None or df.empty:
            return self._empty_frame()
        out = df.loc[start:end]
        if fill_missing:
            out = self.fill_missing(out)
        cols = [c for c in STANDARD_COLUMNS[1:] if c in out.columns]
        extra = [c for c in out.columns if c not in STANDARD_COLUMNS]
        out = out[cols + extra]
        out.attrs.update({k: v for k, v in df.attrs.items() if k not in out.attrs})
        return out

    # ==================== 原始价 / 复权因子（分离存储） ====================

    def _raw_path(self, market: str, symbol: str) -> Path:
        return self.cache_dir / "raw" / f"{market}_{self._sanitize(symbol)}_daily_raw.csv"

    def _factor_path(self, market: str, symbol: str) -> Path:
        return self.cache_dir / "adj_factors" / f"{market}_{self._sanitize(symbol)}_daily_factors.csv"

    def _get_raw_daily(self, market: str, symbol: str, start: str, end: str) -> pd.DataFrame:
        """不复权原始价（data_cache/raw/）：复权完全由因子现算，见模块说明。"""
        path = self._raw_path(market, symbol)
        cached = self._read_cache(path)
        if cached is not None and not self._cache_expired(path, "daily") \
                and self._covers(cached, start, end) \
                and not self._last_bar_incomplete(path, cached, market):
            return cached
        try:
            df = self._quality_check(self._fetch_daily(market, symbol, start, end, ""), market, symbol)
            self._save_cache(df, path)
            return df
        except Exception as exc:  # noqa: BLE001
            if cached is not None and not cached.empty:
                self.logger.warning("[%s] %s 原始价拉取失败(%s)，返回过期缓存", market, symbol, exc)
                cached.attrs["stale"] = True
                self._mark_stale(cached, market, "daily")
                return self._enforce_stale(cached, market, symbol, "daily")
            if market in config.SINGLE_SOURCE_MARKETS["daily"]:
                self.logger.error("[%s] %s 原始价无可用数据源：%s", market, symbol, exc)
                raise _single_source_error(market, symbol, "日线(原始价)", exc) from exc
            raise RuntimeError(f"[{market}] {symbol} 原始价拉取失败: {exc}") from exc

    def _get_adj_factor(self, market: str, symbol: str,
                        start=None) -> Optional[pd.DataFrame]:
        """复权因子（data_cache/adj_factors/）：qfq_factor = 前复权价 / 原始价，hfq 由 qfq 归一化推出。

        start：原始价的最早日期。因子必须覆盖到原始价的起点，否则长历史的前段会被
        bfill 成错误的常数因子（早期价格失真），因此缓存不足时会整段重算。
        """
        path = self._factor_path(market, symbol)
        # A股日线与分钟线统一使用 BaoStock query_adjust_factor（单一因子源，避免两源口径冲突）
        if market == "cn_stock" and bs is not None:
            try:
                if not self._cache_expired(path, "daily"):
                    cached_bs = self._read_cache(path)
                    # factor_source 标记用于识别旧版 AKShare 口径缓存（缺失则重新计算）
                    if cached_bs is not None and not cached_bs.empty and \
                            "factor_source" in cached_bs.columns:
                        return cached_bs
                    if cached_bs is not None and not cached_bs.empty:
                        self.logger.info("[复权] %s 旧 AKShare 口径因子缓存已作废，改用 BaoStock 口径",
                                         symbol)
                factors = self._fetch_baostock_adjust_factor(symbol).copy()
                self._save_cache(factors, path)
                return factors
            except Exception as exc:  # noqa: BLE001 - 回退 AKShare 口径并明确告警
                self.logger.warning("[复权] %s BaoStock 因子不可用（%s），回退 AKShare 口径；"
                                    "此时分钟线与日线因子可能不同源", symbol, exc)
        cached = None
        if not self._cache_expired(path, "daily"):
            cached = self._read_cache(path)
        need_from = pd.Timestamp(start) if start is not None else \
            pd.Timestamp(self._to_date_str(config.DEFAULT_START))
        if cached is not None and not cached.empty and cached.index.min() <= need_from:
            return cached
        try:
            first = min(need_from, pd.Timestamp(self._to_date_str(config.DEFAULT_START)))
            fetch_start = first.strftime("%Y%m%d")
            last = _date.today().strftime("%Y%m%d")
            raw = self._fetch_daily(market, symbol, fetch_start, last, "")
            adj = self._fetch_daily(market, symbol, fetch_start, last, "qfq")
            if raw is None or raw.empty or adj is None or adj.empty:
                raise RuntimeError("复权因子源数据为空")
            base = pd.to_numeric(raw["close"], errors="coerce")
            qfq = pd.to_numeric(adj["close"], errors="coerce").reindex(base.index).ffill()
            factor = (qfq / base).replace([np.inf, -np.inf], np.nan).ffill().bfill()
            if factor.isna().all():
                raise RuntimeError("复权因子计算结果为空")
            out = pd.DataFrame({"qfq_factor": factor})
            # hfq 归一化到「首个交易日 = 原始价」：factor / factor.iloc[0]
            # （若除以 factor.iloc[-1] 会让 hfq 与 qfq 完全相同，历史价格仍是前复权口径）
            out["hfq_factor"] = factor / float(factor.dropna().iloc[0])
            out.index.name = "date"
            self._save_cache(out, path)
            return out
        except Exception as exc:  # noqa: BLE001 - 因子缺失时降级为不复权，但必须告警
            self.logger.warning("[%s] %s 复权因子获取失败(%s)，本次返回不复权价", market, symbol, exc)
            return None

    def _apply_adjust(self, raw: pd.DataFrame, factor: Optional[pd.DataFrame],
                      adjust: str, market: str = None, symbol: str = None,
                      keep_raw: bool = False) -> pd.DataFrame:
        """复权价 = 原始价 × 因子（成交量/成交额不随复权变化）。

        keep_raw=True（双价体系）：主列 OHLC 为复权价的同时保留 raw_open/high/low/close
        原始价列与 adj_factor 因子列。价权边界（评审三轮裁定）：
          - 信号生成/收益计算/回撤熔断判定 → 主列复权价（消除除权跳空假信号）；
          - 下单股数/涨跌停校验/滑点/成交记录 → raw_* 列（与交易所实际报价一致）。
        同一交易日内 adj = raw × adj_factor（因子按所属交易日折算），撮合在 raw
        空间做比例运算、记账换算回复权空间做金额运算。
        """
        if factor is None or factor.empty:
            out = raw.copy()
            if keep_raw:
                # 双价声明仍然成立：adj 退化为 raw 恒等（无可用因子），
                # 下游撮合消费 raw_* 列的行为不受影响
                for _c in _PRICE_COLUMNS:
                    out[f"raw_{_c}"] = raw[_c]
                out["adj_factor"] = 1.0
                out.attrs["dual_price"] = True
            out.attrs["adjust_fallback"] = True
            out.attrs["adjust"] = "none"
            self.logger.warning("[复权] %s %s 无复权因子，本次返回不复权价（adjust=none）",
                                market or "-", symbol or "-")
            return out
        if factor.index.min() > raw.index.min():
            self.logger.warning("[复权] 因子起点(%s)晚于原始价起点(%s)，该段价格将沿用最早因子，请检查数据源",
                                factor.index.min().date(), raw.index.min().date())
        col = "qfq_factor" if adjust == "qfq" else "hfq_factor"
        # 原始价可能来自 parquet 缓存（datetime64[ms]），因子来自 CSV（ns），先统一精度；
        # 且因子只记录除权日，请求窗口若不含任何除权日，直接 reindex 会整段 NaN，
        # 必须先按「原始价 ∪ 因子」的完整索引排序再 ffill，最后裁回原始价索引。
        target_index = raw.index.astype("datetime64[ns]") \
            if isinstance(raw.index, pd.DatetimeIndex) else raw.index
        factor_series = factor[col]
        if isinstance(factor_series.index, pd.DatetimeIndex):
            factor_series = factor_series.copy()
            factor_series.index = factor_series.index.astype("datetime64[ns]")
        series = factor_series.reindex(factor_series.index.union(target_index)) \
            .sort_index().ffill().bfill().reindex(target_index)
        series.index = raw.index
        out = raw.copy()
        if keep_raw:
            # 双价体系：在乘因子【之前】保存原始价（乘后主列已是复权口径）
            for _c in _PRICE_COLUMNS:
                out[f"raw_{_c}"] = raw[_c]
        # 判定「源不支持复权」必须看因子全历史是否恒为 1；只看请求窗口会误伤
        # 无除权事件的短窗口（如近 30 天窗口因子合法地全为 1.0）
        factor_history = pd.to_numeric(factor[col], errors="coerce").dropna()
        factor_all_one = (not factor_history.empty
                          and np.allclose(factor_history.to_numpy(dtype=float), 1.0))
        if factor_all_one:
            # 因子恒为 1 = 该源不支持复权（如新浪 ETF 回退源），不能伪装成 qfq 成功
            out.attrs["adjust"] = "none"
            self.logger.warning("[复权] %s %s 复权因子恒为 1（数据源不支持复权），本次返回不复权价（adjust=none）",
                                market or "-", symbol or "-")
        for price_col in _PRICE_COLUMNS:
            out[price_col] = out[price_col] * series
        if keep_raw:
            # adj_factor 列：每根 bar 所属交易日的折算因子（分钟 bar 同日共享该日因子）
            out["adj_factor"] = series
            out.attrs["dual_price"] = True
        out.attrs.update(raw.attrs)
        # 成功应用因子：以实际口径覆盖 raw 的标注；恒1降级保持 none（禁止伪装 qfq 成功）
        if not factor_all_one:
            out.attrs["adjust"] = str(adjust)
        return out

    def _normalize_adjust(self, adjust: str) -> str:
        value = str(adjust or "").strip().lower()
        if value in ("qfq", "hfq"):
            return value
        if value in ("", "none", "raw", "bfq", "no"):
            return ""
        raise ValueError(f"不支持的复权方式: {adjust}（仅支持 qfq/hfq/none）")

    @staticmethod
    def fill_missing(df: pd.DataFrame) -> pd.DataFrame:
        """仅图表展示用：OHLC 前值填充。指标/回测请使用未填充的原始序列。"""
        out = df.copy()
        out[_PRICE_COLUMNS] = out[_PRICE_COLUMNS].ffill()
        return out

    def get_minute(self, symbol: str, period: str = "5", start_date: str = None,
                   end_date: str = None, market_type: str = None,
                   for_trading: bool = False) -> pd.DataFrame:
        """获取分钟线（period 支持 1/5/15/30/60），带自建分钟增量库。

        流程：读本地累积 → 取最后一根时间戳 → 只向数据源请求最近一段 →
              与本地合并、去重、升序、质量检查 → 覆盖写回 → 返回全量。
        首次回填按 config.MINUTE_SOURCE_PRIORITY 选源（A股优先 BaoStock，可一次拉多年）；
        新浪/东财受单次上限约束时 attrs["minute_history_capped"]=True 并打 WARNING。
        for_trading: 声明用于模拟盘/实盘下单，遇到 stale 数据直接抛错（同 get_daily）。
        """
        period = str(period)
        if period not in {"1", "5", "15", "30", "60"}:
            raise ValueError(f"不支持的分钟周期: {period}，仅支持 1/5/15/30/60")

        symbol = self._normalize_symbol(symbol)
        market, hint = self._detect_market(symbol, market_type)
        start = self._to_date_str(start_date or config.DEFAULT_START)
        end = self._to_date_str(end_date or _date.today().strftime("%Y-%m-%d"))

        store_path = self._minute_store_path(market, symbol, period)
        store = self._read_minute_store(store_path)

        # 拉取计划：首次全量 / 向前扩展 / 末尾增量 / 中段缺口回填（不只补末尾）
        plan: list = []
        if store is None or store.empty:
            plan.append((start, end))
        else:
            lo = store.index.min()
            if pd.Timestamp(start) < lo - pd.Timedelta(days=3):
                plan.append((start, (lo - pd.Timedelta(days=1)).strftime("%Y-%m-%d")))
            tail_start = max(pd.Timestamp(start), store.index.max() - pd.Timedelta(days=1))
            plan.append((tail_start.strftime("%Y-%m-%d"), end))
            plan.extend(self._minute_gap_ranges(store, start, end, market, symbol))
        # 场景拆段：含「今天」的段单独走新浪/东财，其余历史段走 BaoStock（长历史回填）
        plan = self._split_minute_plan(plan)

        frames, errors = [], []
        for seg_start, seg_end in plan:
            if pd.Timestamp(seg_start) > pd.Timestamp(seg_end):
                continue
            try:
                part = self._fetch_minute(market, symbol, period, seg_start, seg_end)
                if market == "cn_future" and part is not None and not part.empty:
                    part = self._merge_night_session(part)
                if part is not None and not part.empty:
                    part.attrs["fetch_window"] = f"{seg_start}~{seg_end}"
                    frames.append(part)
            except Exception as exc:  # noqa: BLE001 - 单段失败不影响其他段
                errors.append(f"{seg_start}~{seg_end}: {exc}")

        if not frames:
            if store is not None and not store.empty:
                self.logger.warning("[%s] %s 分钟线增量拉取失败(%s)，返回本地累计",
                                    market, symbol, "; ".join(errors))
                stale = store.loc[pd.Timestamp(start): pd.Timestamp(end) + pd.Timedelta(days=1)].copy()
                # 当日请求且回退后仍无今日数据 → 必须显式告警「未取到今日分钟线」，
                # 不能只报「返回本地累计」让当日空缺静默混进结果（盘中/未开盘均适用）。
                today = _date.today()
                if market == "cn_stock" and pd.Timestamp(end).date() >= today \
                        and is_trading_day(today, market) and datetime.now().hour >= 9 \
                        and int((stale.index.normalize().date == today).sum()) == 0:
                    self.logger.warning("[cn_stock] %s 当日（%s）请求未取到今日分钟线：实时源全部失败（%s），"
                                        "已回退本地累计（可能尚未开盘或数据源未更新）",
                                        symbol, today.strftime("%Y-%m-%d"), "; ".join(errors) or "无")
                stale.attrs.update(store.attrs)
                stale.attrs.update(hint)
                stale = self._finish_minute_attrs(stale, store, start,
                                                  source=store.attrs.get("source"))
                stale = self._mark_stale(stale, market, "minute")
                stale = self._attach_asof(stale)
                # v3.51 / 13.0.22 ⑤：回退帧同样必须带结构化声明（不依赖日志文本）
                if market == "cn_stock" and pd.Timestamp(end).date() >= _date.today():
                    self._declare_today_missing(stale)
                return self._enforce_stale(stale, market, symbol, "minute", for_trading)
            detail = "; ".join(errors) or "数据源返回空表"
            if market in config.SINGLE_SOURCE_MARKETS["minute"]:
                self.logger.error("[%s] %s 分钟线无可用数据源：%s", market, symbol, detail)
                raise _single_source_error(market, symbol, "分钟线", detail)
            raise RuntimeError(f"[{market}] {symbol} 分钟线获取失败: {detail}")

        fresh = pd.concat(frames)
        fresh = fresh[~fresh.index.duplicated(keep="last")].sort_index()
        primary = max(frames, key=len)  # 覆盖行数最多的段为主源（通常是长历史回填段）
        fresh.attrs.update(primary.attrs)
        fresh.attrs["sources"] = sorted({str(f.attrs.get("source")) for f in frames
                                         if f.attrs.get("source")})

        merged = self._merge_minute_store(store, fresh, market, symbol)
        merged.attrs.update(store.attrs if store is not None else {})
        merged.attrs.update(fresh.attrs)
        self._save_minute_store(merged, store_path)

        out = merged.loc[pd.Timestamp(start): pd.Timestamp(end) + pd.Timedelta(days=1)].copy()
        out.attrs.update(merged.attrs)
        out.attrs.update(hint)
        out = self._finish_minute_attrs(out, merged, start,
                                        source=fresh.attrs.get("source") or merged.attrs.get("source"))
        out.attrs["sources"] = merged.attrs.get("sources", [])

        # 缺口复核：回填后仍有缺失（停牌 / 超出数据源上限）→ 明示，禁止静默留洞
        gap_dates, daily_gap_dates = self._trading_calendar_check(merged, start, end, market, symbol)
        out.attrs["gap_count"] = len(gap_dates)
        out.attrs["gap_dates"] = [d.strftime("%Y-%m-%d") for d in gap_dates[:60]]
        out.attrs["daily_gap_count"] = len(daily_gap_dates)
        out.attrs["daily_gap_dates"] = [d.strftime("%Y-%m-%d") for d in daily_gap_dates[:60]]
        if gap_dates:
            self.logger.warning("[%s] %s 分钟线仍有 %d 个交易日缺口%s（可能是停牌或超出数据源上限）：%s",
                                market, symbol, len(gap_dates),
                                "（列表仅前 60 个）" if len(gap_dates) > 60 else "",
                                ", ".join(out.attrs["gap_dates"][:10]))
        if daily_gap_dates:
            # 日历开市但日线缺该日：可能是日线缺口（网络失败没拉到），也可能是停牌/调休休市
            self.logger.warning("[%s] %s 日历开市但日线缺 %d 个交易日（疑似日线缺口，"
                                "也可能为停牌或调休休市）：%s%s",
                                market, symbol, len(daily_gap_dates),
                                ", ".join(out.attrs["daily_gap_dates"][:10]),
                                " ..." if len(daily_gap_dates) > 10 else "")
        if pd.Timestamp(start) < merged.index.min() - pd.Timedelta(days=3):
            self.logger.warning("[%s] %s 首次回填未覆盖请求起点 %s（实际 %s），已标 minute_history_capped=True",
                                market, symbol, start, merged.index.min())
        out = self._attach_asof(out)
        # v3.51 / 13.0.22 ⑤：当日空缺的结构化声明（字段无条件、告警有门控）
        if market == "cn_stock" and pd.Timestamp(end).date() >= _date.today():
            self._declare_today_missing(out)
        return out

    def _declare_today_missing(self, frame: pd.DataFrame) -> None:
        """v3.51 / 13.0.22 ⑤：当日空缺的结构化声明（字段无条件、告警有门控）。

        请求区间含今天且返回帧没有今日 bar 时，在 attrs 写
        today_missing_declared=True。检测依据是字段而非日志文本——
        去掉 WARNING 日志行，字段仍在（禁止靠「读日志」抓当日空缺）。
        """
        if frame is None:
            return
        today = _date.today()
        if len(frame) == 0 or not (frame.index.normalize().date == today).any():
            frame.attrs["today_missing_declared"] = True

    # ==================== 自建分钟增量库（与第 13 步共用落库机制） ====================

    def _minute_store_path(self, market: str, symbol: str, period: str) -> Path:
        return self.cache_dir / "minute" / f"{market}_{self._sanitize(symbol)}_{period}.parquet"

    def _read_minute_store(self, path: Path) -> Optional[pd.DataFrame]:
        if not path.exists():
            return None
        try:
            versioning.verify_basis(path, expected="raw")
            df = pd.read_parquet(path)
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date")
            df.index = pd.to_datetime(df.index)
            return df.sort_index()
        except versioning.PriceBasisError:
            raise                      # 口径不可信：fail-closed
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("读取分钟增量库失败 %s: %s", path, exc)
            return None

    def _save_minute_store(self, df: pd.DataFrame, path: Path) -> None:
        if df is None or df.empty:
            return
        try:
            out = df.copy()
            out.index.name = "date"
            out.reset_index().to_parquet(path, index=False)
            versioning.stamp_file(path, basis="raw")   # 分钟库只存原始价，复权在出口现算
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("写入分钟增量库失败 %s: %s", path, exc)

    def _split_minute_plan(self, plan: list) -> list:
        """把跨「今天」的拉取段拆成两段：历史段到昨天，今天段单独取。

        BaoStock 只有盘后数据 → 历史段走 BaoStock 长历史回填；今天段走新浪/东财实时。
        """
        today = _date.today()
        yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        today_str = today.strftime("%Y-%m-%d")
        out = []
        for seg_start, seg_end in plan:
            if pd.Timestamp(seg_end).date() >= today and pd.Timestamp(seg_start).date() < today:
                out.append((seg_start, yesterday))
                out.append((today_str, seg_end))
            else:
                out.append((seg_start, seg_end))
        return out

    def _trading_calendar_check(self, df: pd.DataFrame, start, end, market: str,
                                symbol: str = None) -> tuple:
        """双重校验交易日，返回 (分钟缺口日, 日线缺口日)。

        - 主：该标的「日线索引」——能自动排除停牌日与除夕等调休休市日；
        - 兜底：交易所/节假日日历（`is_trading_day`）——日线不可用或日线缺日时判断市场是否开市；
        - 日历说开市、却查不到该日线 → 视为「日线缺口」（也可能是停牌/调休休市），
          记入 daily_gap_dates 并 WARNING，避免「日线缺失导致分钟缺口检测出现盲区」。
        """
        if df is None or df.empty:
            return [], []
        if market in CN_MARKETS and not CN_CALENDAR_AVAILABLE:
            # 缺少中国节假日日历时无法区分法定节假日，宁可不报缺口也不批量误抓
            return [], []
        lo = max(pd.Timestamp(start).date(), df.index.min().date())
        hi = min(pd.Timestamp(end).date(), _date.today() - timedelta(days=1))
        if lo > hi:
            return [], []
        trading_days = None
        if symbol:
            try:
                daily = self.get_daily(symbol, lo.strftime("%Y-%m-%d"),
                                       hi.strftime("%Y-%m-%d"), adjust="")
                if daily is not None and not daily.empty:
                    trading_days = set(pd.DatetimeIndex(daily.index.normalize().unique()).date)
            except Exception as exc:  # noqa: BLE001 - 退化为节假日日历
                self.logger.debug("[%s] %s 日线日历不可用(%s)，缺口检测退回 is_trading_day",
                                  market, symbol, exc)
        present = set(pd.DatetimeIndex(df.index.normalize().unique()).date)
        minute_gaps, daily_gaps, day = [], [], lo
        while day <= hi:
            open_by_calendar = is_trading_day(day, market)
            if trading_days is not None and day in trading_days:
                # 日线确认开市 → 分钟缺失才是真缺口
                if day not in present:
                    minute_gaps.append(day)
            elif trading_days is not None:
                # 日线没有该日：日历说开市 → 疑似日线缺口（停牌/调休休市也会命中，需人工复核）
                if open_by_calendar:
                    daily_gaps.append(day)
            elif open_by_calendar and day not in present:
                # 无日线可参照，只能按节假日日历判断
                minute_gaps.append(day)
            day += timedelta(days=1)
        return minute_gaps, daily_gaps

    def _minute_missing_dates(self, df: pd.DataFrame, start, end, market: str,
                              symbol: str = None) -> list:
        """本地库在 [start, end] 内缺失的交易日（今天及以后不算缺口，数据未完成）。"""
        return self._trading_calendar_check(df, start, end, market, symbol)[0]

    def _minute_gap_ranges(self, df: pd.DataFrame, start, end, market: str,
                           symbol: str = None, limit: int = 8) -> list:
        """把缺失交易日合并成连续区间（最多 limit 段，避免一次发起过多请求）。"""
        ranges = []
        for day in self._minute_missing_dates(df, start, end, market, symbol):
            if ranges and day - ranges[-1][1] == timedelta(days=1):
                ranges[-1][1] = day
            else:
                ranges.append([day, day])
        if len(ranges) > limit:
            self.logger.warning("[%s] 分钟库缺口段 %d 个，本次仅回填前 %d 段，其余记入 attrs gap_dates",
                                market, len(ranges), limit)
            ranges = ranges[:limit]
        return [(a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d")) for a, b in ranges]

    def _merge_minute_store(self, store: Optional[pd.DataFrame], fresh: pd.DataFrame,
                            market: str, symbol: str) -> pd.DataFrame:
        """合并本地与新增分钟线：按时间戳去重（新数据优先）、升序、质量检查。"""
        frames = [f for f in (store, fresh) if f is not None and not f.empty]
        if not frames:
            return self._empty_frame()
        merged = pd.concat(frames)
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        return self._quality_check(merged, market, symbol)

    def _finish_minute_attrs(self, out: pd.DataFrame, merged: pd.DataFrame,
                             start: str, source: str = None) -> pd.DataFrame:
        """补齐分钟线元信息：available_from / minute_history_capped / source / adjust。"""
        if merged is None or merged.empty:
            out.attrs["available_from"] = None
            out.attrs["minute_history_capped"] = True
            out.attrs["source"] = source or "unknown"
            out.attrs.setdefault("adjust", "none")
            return out
        available_from = merged.index.min()
        capped = bool(pd.Timestamp(start) < available_from - pd.Timedelta(days=3))
        out.attrs["available_from"] = available_from.strftime("%Y-%m-%d %H:%M")
        out.attrs["minute_history_capped"] = capped
        out.attrs["source"] = source or merged.attrs.get("source") or "local"
        out.attrs.setdefault("adjust", merged.attrs.get("adjust", "none"))
        return out

    def get_kline(self, symbol: str, start_date: str = None, end_date: str = None,
                  period: str = "1d", adjust: str = "qfq",
                  market_type: str = None) -> pd.DataFrame:
        """按周期取 K 线（1d/1w/1M/1min/5min/15min/30min/60min）。

        本方法**只做路由**，不重复实现取数/复权/缓存：
        - 1d：直接 get_daily；
        - 1w / 1M：get_daily 后本地 re_sample_kline（不依赖网络）；
        - 1min~60min：get_minute（BaoStock 长历史 + 新浪/东财当日 + 自建增量库）。
        周期字符串以 config.SUPPORTED_PERIODS 为准，分钟映射只引用 config.PERIOD_TO_MINUTE。
        """
        period = str(period)
        if period not in config.SUPPORTED_PERIODS:
            raise ValueError(f"不支持的周期: {period}，仅支持 {config.SUPPORTED_PERIODS}")
        asof = None
        if period in config.DAILY_PERIODS:
            daily = self.get_daily(symbol, start_date, end_date, adjust=adjust,
                                   market_type=market_type)
            out = daily if period == "1d" else re_sample_kline(daily, period)
            # 重采样走 resample/agg，attrs 与附加列可能被丢弃：出口统一重新挂载数据层元信息
            out.attrs.update({k: v for k, v in daily.attrs.items()})
            # A2：周/月线的 W-FRI/ME 标签可能落在最后一根 bar 之后（如未走完的一周），
            # asof 必须取底层日线最后一根 bar 的实际日期，不能用重采样标签
            if len(daily):
                asof = daily.index[-1]
        else:
            out = self.get_minute(symbol, str(config.PERIOD_TO_MINUTE[period]),
                                  start_date, end_date, market_type=market_type)
            adj_norm = self._normalize_adjust(adjust)
            market, _ = self._detect_market(symbol, market_type)
            if adj_norm and market == "cn_stock":
                # v3.53 评审三轮（双价体系）：cn_stock 分钟线复权走 BaoStock 因子折算，
                # 不再降级 adjust=none。主列 = 复权价（信号/收益/回撤/熔断消费），
                # raw_* 列 = 原始价（撮合/股数/涨跌停/滑点/成交记录消费），
                # 因子按 bar 所属交易日折算（日频因子 ffill 到分钟索引）。
                factor = self._get_adj_factor(market, symbol, start_date)
                out = self._apply_adjust(out, factor, adj_norm, market, symbol,
                                         keep_raw=True)
            elif adj_norm and market == "hk_stock":
                # v3.54 港股分钟线预检（双价体系）：分钟复用日线级每日复权因子
                # （分红/拆股为日级事件，无需分钟级额外因子），因子来自自建
                # 事件表（_hk_daily_factor：02800 分钟与日线同闸 raise，三级
                # 跳变审计共享实现不放松阈值），_apply_adjust 按 bar 所属
                # 交易日 ffill 折算（与 cn_stock 分钟双价完全同构）
                factor_df, audit_band = self._hk_daily_factor(
                    str(symbol).zfill(5), start_date or out.index.min().strftime("%Y-%m-%d"),
                    end_date or out.index.max().strftime("%Y-%m-%d"))
                out = self._apply_adjust(out, factor_df, adj_norm, market, symbol,
                                         keep_raw=True)
                out.attrs.update({
                    "adjust": "hfq_self_built",
                    "price_adjust": "hfq_self_built",
                    "events_source": "em_stock_hk_dividend_payout_em",
                    "n_events_applied": factor_df.attrs.get("n_events_applied"),
                    "lot_size": self.get_hk_lot_size(str(symbol).zfill(5)),
                    "currency": "HKD",
                })
                if audit_band:
                    out.attrs["audit_warnings"] = audit_band
            else:
                # 非 cn_stock/hk_stock 分钟线暂无已验证因子源：显式降级标注（禁止伪装复权成功）
                out.attrs.setdefault("adjust", "none")
        out.attrs["period"] = period
        return self._attach_asof(out, asof=asof)

    def get_multi_period(self, symbol: str, periods=None, start_date: str = None,
                         end_date: str = None, adjust: str = "qfq",
                         market_type: str = None) -> dict:
        """一次取多个周期，返回 {period: DataFrame}（供跨周期共振策略使用）。

        单个周期失败不中断其它周期，失败原因写入 self.logger 并从返回字典中略去。
        """
        periods = list(periods or ["1d", "1w", "60min"])
        out = {}
        for p in periods:
            try:
                out[p] = self.get_kline(symbol, start_date, end_date, period=p,
                                        adjust=adjust, market_type=market_type)
            except Exception as exc:  # noqa: BLE001 - 单周期失败不影响其它周期
                self.logger.warning("[多周期] %s 取 %s 失败：%s", symbol, p, exc)
        return out

    def get_realtime(self, symbol: str, market_type: str = None) -> dict:
        """获取实时快照（不缓存）。"""
        symbol = self._normalize_symbol(symbol)
        market, hint = self._detect_market(symbol, market_type)
        result = {
            "symbol": symbol, "market": market, "name": "",
            "price": None, "change_pct": None, "volume": None,
            "bid": None, "ask": None, "open": None, "high": None, "low": None,
            "prev_close": None, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        result.update(hint)
        try:
            row = self._fetch_realtime(market, symbol)
            result.update({k: v for k, v in (row or {}).items() if v is not None})
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("[%s] %s 实时行情失败: %s", market, symbol, exc)
            result["error"] = str(exc)
        return result

    def get_symbol_list(self, market_type: str) -> pd.DataFrame:
        """返回指定市场的全部标的列表（code + name），结果本地缓存 7 天。"""
        market_type = (market_type or "").lower()
        config.get_market_config(market_type)  # 校验市场合法

        cache_file = self.cache_dir / "lists" / f"{market_type}.csv"
        if not self._cache_expired(cache_file, "daily"):
            try:
                cached = pd.read_csv(cache_file, dtype=str)
                if not cached.empty:
                    return cached
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("读取 %s 标的列表缓存失败: %s", market_type, exc)

        df = self._build_symbol_list(market_type)
        if not df.empty:
            try:
                df.to_csv(cache_file, index=False, encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("写入 %s 标的列表缓存失败: %s", market_type, exc)
        return df

    def _build_symbol_list(self, market_type: str) -> pd.DataFrame:
        """全市场标的扫描（勿高频调用）。

        新浪/东财对全量扫描极敏感，本方法全部请求都必须经 `_request`（节流 >=0.3s +
        指数退避），且调用方应自行控制频率（结果会缓存 7 天，见 get_symbol_list）。
        批量因子取数同理：一次只取少量标的，并在两次请求间保留间隔，避免封 IP。
        """
        empty = pd.DataFrame(columns=["code", "name"])
        try:
            if market_type == "cn_stock":
                try:
                    raw = self._request(ak.stock_info_a_code_name)
                    return self._standard_list(raw, ["code", "name"])
                except Exception:  # noqa: BLE001 - 东财失败改用新浪全量快照
                    raw = self._request(ak.stock_zh_a_spot)
                    return self._standard_list(raw, ["代码", "名称"])
            if market_type == "cn_etf":
                try:
                    raw = self._request(ak.fund_etf_spot_em)
                except Exception:  # noqa: BLE001 - 东财失败改用新浪
                    raw = self._request(ak.fund_etf_category_sina, symbol="ETF基金")
                return self._standard_list(raw, ["代码", "名称"])
            if market_type in ("us_stock", "us_etf"):
                raw = self._request(ak.stock_us_spot_em)
                return self._standard_list(raw, ["代码", "名称"])
            if market_type == "hk_stock":
                raw = self._request(ak.stock_hk_spot_em)
                return self._standard_list(raw, ["代码", "名称"])
            if market_type == "cn_convertible":
                raw = self._request(ak.bond_zh_cov)
                return self._standard_list(raw, ["债券代码", "债券简称"])
            if market_type == "cn_fund":
                raw = self._request(ak.fund_open_fund_daily_em)
                return self._standard_list(raw, ["基金代码", "基金简称"])
            if market_type == "cn_future":
                raw = self._request(ak.futures_display_main_sina)
                cols = list(raw.columns)
                code_col = next((c for c in cols if "合约" in str(c) or str(c).lower() == "symbol"), cols[0])
                name_col = next((c for c in cols if "名称" in str(c) or str(c).lower() == "name"), cols[1])
                return self._standard_list(raw, [code_col, name_col])
            if market_type == "global_future":
                return pd.DataFrame(
                    [{"code": k, "name": v.get("name", k)} for k, v in config.GLOBAL_FUTURES.items()])
            if market_type == "forex":
                return pd.DataFrame(
                    [{"code": k, "name": v.get("name", k)} for k, v in config.FOREX["ccy_pairs"].items()])
            if market_type == "crypto":
                return pd.DataFrame(
                    [{"code": k, "name": k} for k in config.CRYPTO["assets"]])
            if market_type == "cn_reverse_repo":
                rows = [{"code": f"204{i:03d}", "name": f"GC{i:03d}"}
                        for i in (1, 2, 3, 4, 7, 14, 28, 91, 182)]
                rows.append({"code": "131810", "name": "R-001"})
                return pd.DataFrame(rows)
            if market_type == "cn_option":
                return pd.DataFrame([{"code": k, "name": v} for k, v in _OPTION_SYMBOL_SHORT.items()])
            if market_type in ("cn_reits", "neeq"):
                func = getattr(ak, "reits_spot_em" if market_type == "cn_reits" else "stock_neeq_spot_em", None)
                if func is None:
                    raise RuntimeError(f"当前 akshare 版本无 {market_type} 标的列表接口")
                raw = self._request(func)
                return self._standard_list(raw, ["代码", "名称"])
            return empty
        except Exception as exc:  # noqa: BLE001
            hint = "（东财接口不可达，稍后重试或检查网络/代理）" if market_type in (
                "us_stock", "us_etf", "hk_stock") else ""
            self.logger.warning("获取 %s 标的列表失败%s: %s", market_type, hint, exc)
            return empty

    # ==================== 缓存 ====================

    def clear_cache(self, symbol: str = None) -> int:
        """清除缓存（含 minute/ 增量库子目录）；symbol 为空时清空全部。返回删除文件数。"""
        pattern = "*" if symbol is None else f"*_{self._sanitize(symbol)}_*"
        candidates = [p for p in self.cache_dir.glob(pattern) if p.is_file()]
        candidates += [p for p in (self.cache_dir / "minute").glob(pattern) if p.is_file()]
        removed = 0
        for path in candidates:
            if path.suffix in (".csv", ".parquet"):
                try:
                    path.unlink()
                    removed += 1
                except OSError as exc:
                    self.logger.warning("删除缓存失败 %s: %s", path, exc)
        return removed

    def update_cache(self, symbol: str, adjust: str = "qfq") -> int:
        """增量更新日线缓存，返回新增行数。

        复权市场只增量更新「原始价」缓存，并让复权因子缓存失效（下次自动重算），
        避免用新复权基准去拼接旧复权价导致历史价格错位。
        """
        symbol = self._normalize_symbol(symbol)
        market = config.detect_market_type(symbol)
        adjust = self._normalize_adjust(adjust)
        cache_file = self._raw_path(market, symbol) if market in _ADJ_MARKETS \
            else self._cache_path(market, symbol, "daily", adjust)
        cached = self._read_cache(cache_file)
        if cached is None or cached.empty:
            self.get_daily(symbol, adjust=adjust)
            return len(self._read_cache(cache_file) or [])

        last = cached.index.max()
        # 最后一根若是盘中抓取的残缺 bar，必须重叠重取该日并覆盖，不能只追加新日期
        overlap = self._last_bar_incomplete(cache_file, cached, market)
        start = (last if overlap else last + timedelta(days=1)).strftime("%Y%m%d")
        end = _date.today().strftime("%Y%m%d")
        if start > end:
            return 0
        try:
            fresh = self._fetch_daily(market, symbol, start, end,
                                      "" if market in _ADJ_MARKETS else adjust)
            fresh = self._quality_check(fresh, market, symbol)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("增量更新 %s 失败: %s", symbol, exc)
            return 0
        if fresh.empty:
            return 0
        # v3.45 / 13.0.16：拼接前必须校验口径——缓存可能来自 A 源、增量来自 B 源，
        # 「手 / 股」混拼会静默放大 100 倍；不一致直接抛 DataFieldInconsistencyError。
        from data.source_adapter import assert_field_consistency
        assert_field_consistency({"cache": cached, "fresh": fresh}, market)
        merged = pd.concat([cached, fresh])
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        self._save_cache(merged, cache_file)
        if market in _ADJ_MARKETS:
            self._factor_path(market, symbol).unlink(missing_ok=True)
            self._factor_path(market, symbol).with_suffix(".parquet").unlink(missing_ok=True)
            if market == "cn_stock":
                # BaoStock 因子缓存同步失效，避免新增分红后日线/分钟线仍用旧因子
                bs_factor = self.cache_dir / "adj_factors" / \
                    f"cn_stock_{self._sanitize(symbol)}_bs_factors.csv"
                bs_factor.unlink(missing_ok=True)
                bs_factor.with_suffix(".parquet").unlink(missing_ok=True)
        return len(fresh)

    def _cache_path(self, market: str, symbol: str, period: str, adjust: str) -> Path:
        return self.cache_dir / f"{market}_{self._sanitize(symbol)}_{period}_{adjust}.csv"

    def _sanitize(self, symbol: str) -> str:
        return re.sub(r"[^0-9A-Za-z]", "", str(symbol)).upper()

    def _normalize_symbol(self, symbol: str) -> str:
        """统一代码格式：去空格/斜杠，字母代码转大写，加密交易对取基础币。"""
        text = str(symbol).strip()
        upper = text.upper().replace("/", "").replace("-", "")
        if upper.endswith("USDT") and upper[:-4] in config.CRYPTO["assets"]:
            return upper[:-4]
        return upper

    def _detect_market(self, symbol: str, market_type: str = None):
        """识别市场；命中 config.AMBIGUOUS_CODES 且未显式传 market_type 时告警并打标。

        返回 (market, attrs_hint)。hint 会写入返回 DataFrame.attrs / 实时 dict，
        避免 ZN（沪锌 vs 10 年期美债）这类代码被静默二选一。
        """
        market = config.detect_market_type(symbol, market_type)
        if market_type:
            return market, {}
        key = str(symbol).strip().upper()
        candidates = config.AMBIGUOUS_CODES.get(key)
        if not candidates:
            # 无前缀的指数代码（000300/000905…）与深市个股号段（000/001/002/003）完全重合，
            # 会被当成 A 股个股，静默取回完全不同标的的数据 → 只引导不改判定
            index_name = config.CN_INDEX["common_codes"].get(key)
            if market == "cn_stock" and index_name:
                prefix = "sz" if key.startswith(("399", "980", "981")) else "sh"
                self.logger.warning("[指数代码] 检测到疑似指数代码 %s（%s），已按深市个股处理；"
                                    "如需取该指数请传 %s%s", key, index_name, prefix, key)
            return market, {}
        hint = {"ambiguous_market": True, "market_candidates": list(candidates),
                "market_note": f"{symbol} 可能是 {' / '.join(candidates)}，本次按 {market} 处理；"
                               f"如有误请显式传 market_type"}
        self.logger.warning("[歧义代码] %s", hint["market_note"])
        return market, hint

    def _cache_expired(self, path: Path, kind: str) -> bool:
        if not path.exists():
            return True
        days = self.expire_days.get(kind, 0)
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        return age > timedelta(days=days)

    def _read_cache(self, path: Path, basis: str = None) -> Optional[pd.DataFrame]:
        """读缓存前必须过口径闸门（DATA_VERSIONING）：缺标记/口径错位直接报错。

        旧缓存没有 price_basis 标记时按 ``legacy_qfq_cache=forbid_read`` 拒绝读取，
        必须先跑 ``python -m data.versioning --apply`` 补标记或删除后重取；
        绝不能按文件名/default 口径猜。
        """
        parquet = path.with_suffix(".parquet")
        for file in (parquet, path):
            if not file.exists():
                continue
            try:
                versioning.verify_basis(file, expected=basis or
                                        versioning.infer_basis_from_path(path))
                if file.suffix == ".parquet":
                    df = pd.read_parquet(file)
                    if "date" in df.columns:
                        df["date"] = pd.to_datetime(df["date"])
                        df = df.set_index("date")
                else:
                    df = pd.read_csv(file, parse_dates=["date"], index_col="date")
                df.index = pd.to_datetime(df.index)
                # CSV/parquet 往返会丢 attrs：从边车恢复数据本体标注
                # （source/volume_unit/amount_missing 等），缓存命中不再蒸发
                df.attrs.update(versioning.read_sidecar_attrs(file))
                return df.sort_index()
            except versioning.PriceBasisError:
                raise                      # 口径不可信：fail-closed，不能吞成「无缓存」
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("读取缓存失败 %s: %s", file, exc)
        return None

    def _save_cache(self, df: pd.DataFrame, path: Path, basis: str = None) -> None:
        if df is None or df.empty:
            return
        try:
            versioning.write_with_basis(df, path, basis=basis)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("写入缓存失败 %s: %s", path, exc)

    def _covers(self, df: pd.DataFrame, start: str, end: str) -> bool:
        if df is None or df.empty:
            return False
        return df.index.min() <= pd.Timestamp(start) and df.index.max() >= pd.Timestamp(end) - timedelta(days=3)

    def _last_bar_incomplete(self, path: Path, df: pd.DataFrame, market: str) -> bool:
        """缓存最后一根日线是否可能是盘中抓取的残缺 bar。

        _covers 允许末尾缺 3 个自然日，若最后一根是当天盘中抓取的半截数据
        （收盘价/成交量尚未定稿），只向后追加新日期永远补不回来。这里按
        「缓存写入时刻 < 该 bar 所属交易日的收盘时刻」判定可疑并触发整段重取；
        重取成功后 mtime 晚于收盘时刻，不会反复触发。
        """
        if df is None or df.empty:
            return False
        try:
            last_day = df.index.max().date()
            sessions = get_trading_sessions(market, last_day)
            if not sessions:
                return False
            close_dt = sessions[-1][1]
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
        except Exception:  # noqa: BLE001 - 判定失败按「完整」处理，避免无谓重取
            return False
        if close_dt.tzinfo is not None:
            if datetime.now(close_dt.tzinfo) < close_dt:
                return False  # 该交易日尚未收盘，本来就不完整，无需重取
            mtime = mtime.replace(tzinfo=close_dt.tzinfo)
        elif datetime.now() < close_dt:
            return False
        return mtime < close_dt

    # ==================== stale（过期数据）收敛 ====================

    @staticmethod
    def _latest_completed_trading_day(market: str) -> _date:
        """最近一个【已收盘】的交易日（今天若还在盘中则退回上一交易日）。

        用 get_trading_sessions 的市场收盘时刻判断，避免盘中把「今天的日线还没生成」
        误判成 stale，也避免用自然日跨周末/节假日算错天数。
        """
        today = _date.today()
        sessions = get_trading_sessions(market, today)
        if sessions:
            close_dt = sessions[-1][1]
            tz = close_dt.tzinfo
            if datetime.now(tz) >= close_dt:
                return today
        day = today - timedelta(days=1)
        for _ in range(30):
            if is_trading_day(day, market):
                return day
            day -= timedelta(days=1)
        return day

    def _stale_trading_days(self, last_ts, market: str) -> int:
        """最后一根 K 线之后、到「最近已收盘交易日」之间隔了几个交易日（含目标日）。"""
        if last_ts is None:
            return 0
        last = pd.Timestamp(last_ts).date()
        ref = self._latest_completed_trading_day(market)
        if last >= ref:
            return 0
        days, day = 0, last + timedelta(days=1)
        while day <= ref:
            if is_trading_day(day, market):
                days += 1
            day += timedelta(days=1)
        return days

    def _mark_stale(self, df: pd.DataFrame, market: str, kind: str) -> pd.DataFrame:
        """按交易日差标注 stale / stale_days，并打 WARNING（差为 0 时不标）。"""
        n = self._stale_trading_days(df.index.max() if not df.empty else None, market)
        df.attrs["stale_days"] = n
        df.attrs["stale_limit"] = int(config.STALE_LIMIT.get(kind, 0))
        df.attrs["last_bar"] = (str(pd.Timestamp(df.index.max()))[:10]) if not df.empty else None
        if n > 0:
            df.attrs["stale"] = True
            self.logger.warning("[stale] %s 本地数据最后一根 %s，已停更 %d 个交易日（上限 %s）",
                                market, df.attrs["last_bar"], n, df.attrs["stale_limit"])
        return df

    def _attach_asof(self, df: pd.DataFrame, asof=None) -> pd.DataFrame:
        """把时效物化为普通列 config.STALE_INFO_COLUMN（值为本帧**最后一根 bar 的实际日期**）。

        口径（A2）：绝不能用「取数时刻/今天」——缓存命中或失败回退时，数据可能是几天前的，
        按取数时刻填会把旧数据标成新鲜，防线会在最常见的缓存路径上直接失效。
        - 单标的：填 asof（调用方显式传入，如周/月线用日线最后一根 bar，避免周五标签把日期推后），
          未传则填 df.index[-1]；
        - 多标的（A3）：按 symbol 分组填各组自己的最新日期，禁止整帧广播同一日期，
          否则组合里 B 停更 7 天也会被判新鲜。

        普通列能穿过 rolling/ewm/expanding/resample/concat（不像 attrs 会被窗口运算清空），
        下游指标计算后仍能读到时效，供 assert_fresh_for_trading 在下单前复核。
        """
        if df is None or len(df) == 0:
            return df
        col = config.STALE_INFO_COLUMN
        out = df.copy()
        idx = pd.DatetimeIndex(out.index)
        if idx.tz is not None:  # 与交易日历（naive）比较前统一去掉时区
            idx = idx.tz_localize(None)
        symbols = None
        if "symbol" in out.columns:
            syms = out["symbol"].astype(str)
            if syms.nunique() > 1:
                symbols = syms
        if symbols is not None:
            # 多标的帧：逐 symbol 取各自最后一根 bar 的日期
            per_symbol = pd.Series(idx).groupby(symbols.values).max()
            out[col] = symbols.map(per_symbol).values
            last = pd.Timestamp(pd.to_datetime(out[col]).max()).normalize()
        else:
            last = pd.Timestamp(asof if asof is not None else idx[-1]).normalize()
            if last.tzinfo is not None:
                last = last.tz_localize(None)
            out[col] = last
        out.attrs["last_bar"] = str(last)[:10]
        out.attrs["asof_column"] = col
        # 复权口径物化为普通列（attrs 会被 resample/concat/rolling 清空，指标入口优先读此列）
        # B3：多标的帧必须逐 symbol 填各自口径，否则「帧内口径混合就报错」的守卫触发不了：
        #   ① 已有 price_adjust 列（如两次 get_daily(adjust=...) 结果 concat）→ 原样保留；
        #   ② 多标的 + attrs["adjust_by_symbol"]={symbol: "qfq"/"none"} → 按 symbol 分组填；
        #   ③ 否则退回单一口径 attrs["adjust"]（单标的帧的常规路径）。
        adj_col = str(getattr(config, "INDICATOR_HARDENING", {}).get("adjust_column", "price_adjust"))
        if adj_col not in out.columns:
            def _norm_adj(value) -> str:
                v = str(value or "").strip().lower()
                return v if v in ("qfq", "hfq", "none") else "none"

            per_symbol_adj = out.attrs.get("adjust_by_symbol")
            if symbols is not None and isinstance(per_symbol_adj, dict):
                out[adj_col] = symbols.map(
                    lambda s: _norm_adj(per_symbol_adj.get(str(s)))).values
            else:
                out[adj_col] = _norm_adj(out.attrs.get("adjust"))
        out.attrs["adjust_column"] = adj_col
        return out

    def _enforce_stale(self, df: pd.DataFrame, market: str, symbol: str, kind: str,
                       for_trading: bool = False, mode: str = None) -> pd.DataFrame:
        """时效闸门：paper/live 下超限或 stale 一律报错；backtest 豁免；for_trading 永远生效。"""
        n = int(df.attrs.get("stale_days") or 0)
        limit = int(config.STALE_LIMIT.get(kind, 0))
        gate = _stale_gate_enabled(mode)
        if gate and n > limit:
            raise RuntimeError(
                f"[{market}] {symbol} {kind}数据已停更 {n} 个交易日，超过上限 {limit}"
                f"（config.STALE_LIMIT），视为不可用；最后一根 {df.attrs.get('last_bar')}")
        if for_trading and df.attrs.get("stale"):
            raise RuntimeError(
                f"[{market}] {symbol} {kind}数据为过期数据（stale_days={n}，最后一根 "
                f"{df.attrs.get('last_bar')}），禁止用于模拟盘/实盘下单决策")
        if gate and df.attrs.get("stale"):
            raise RuntimeError(
                f"[{market}] {symbol} {kind}数据为过期数据（stale_days={n}，最后一根 "
                f"{df.attrs.get('last_bar')}）；运行模式 {config.RUN_MODE} 下时效闸门生效，"
                f"禁止把过期数据用于交易链路（回测请把 config.RUN_MODE 设为 backtest）")
        return df

    # ==================== 请求控制 ====================

    def _throttle(self) -> None:
        gap = time.time() - self._last_request
        if gap < self.request_delay:
            time.sleep(self.request_delay - gap)
        self._last_request = time.time()

    def _request(self, func, *args, _source: str = None, _timeout: float = None, **kwargs):
        """唯一出网出口：所有接口/HTTP 请求都必须走这里。

        - _source：数据源标识（如 eastmoney/sina/binance），写入日志，便于第 13 步做多源故障切换；
        - _timeout：超时秒数（仅对支持 timeout 的调用生效）；
        - 统一节流（>=REQUEST_DELAY，防新浪/东财封 IP）+ 指数退避重试（self.max_retry 次）。
        """
        label = _source or getattr(func, "__name__", "api")
        if _timeout is not None and "timeout" not in kwargs:
            kwargs["timeout"] = _timeout
        last_error = None
        for attempt in range(1, self.max_retry + 1):
            try:
                self._throttle()
                return func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= self.max_retry:
                    break
                wait = attempt * 1.5
                self.logger.warning("[%s] %s 第 %d 次失败: %s，%.1fs 后重试",
                                    label, label, attempt, exc, wait)
                time.sleep(wait)
        self.logger.error("[%s] 重试 %d 次后仍失败: %s", label, self.max_retry, last_error)
        raise last_error

    def _http_get(self, url: str, params: dict = None, headers: dict = None,
                  source: str = "http", encoding: str = None) -> str:
        """HTTP 出网站统一入口（经 _request 节流/重试），返回响应文本。"""
        resp = self._request(requests.get, url, params=params, headers=headers,
                             _source=source, _timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        if encoding:
            resp.encoding = encoding
        return resp.text

    # ==================== 数据源路由（v3.45 / 13.1） ====================

    def _build_source_router(self):
        """懒构建 DataRouter；返回 None 表示不路由（直连既有实现）。"""
        if getattr(self, "_router_ready", False):
            return self._router
        self._router_ready = True
        self._router = None
        from core.gov_compat import gov
        conf = gov("DATA_LONG_TERM")
        if not conf.get("data_source_failover", True):
            return None
        # v3.48 / 13.0.19 ④：探针上游接口级独立性（在 try 之外，结构性配置错误 fail-closed）
        from data import security_master as _security_master
        _security_master.assert_upstream_independent()
        try:
            from data.source_adapter import (AkshareSource, BaostockSource,
                                             DataRouter, LocalSource, TushareSource)
            from core.utils import is_trading_day
            ak_src = AkshareSource(dispatch=self._router_akshare)
            # 显式关掉线程级超时：dispatch 内部可能走 BaoStock，会话绑定线程不允许强杀
            ak_src.thread_safe_timeout = False
            # _dispatch_* 已按 config.DATA_SOURCE_UNITS 归一到统一口径（股/手/张/份），
            # 路由只补 attrs，不能再乘一次——否则缓存命中（attrs 丢失）时 A 股量 ×100
            ak_src.returns_unified_units = True
            bs_src = BaostockSource(dispatch=self._router_baostock)
            bs_src.kinds = ("minute",)
            bs_src.markets = ("cn_stock",)
            bs_src.returns_unified_units = True
            # v3.46：不再自声明 internal_failover——「内部回退链」只由
            # config.INTERNAL_FAILOVER_SOURCES 白名单决定（自声明 = 自己给自己发豁免）
            local_src = LocalSource(reader=self._router_local)
            local_src.returns_unified_units = True
            from data import security_master
            self._router = DataRouter(
                [ak_src, bs_src, TushareSource(), local_src],
                health_file=self._source_health_path(conf),
                timeout=0,   # 超时由 _request 的 requests timeout + 重试负责
                # v3.46：净空必须有交易日证据；没有探针就不能把「故障空」当「合法空」
                trading_day_probe=is_trading_day,
                # v3.47：合法空的唯一证据来自独立证券主数据（禁止取数层自证退市）
                listing_probe=security_master.listing_status,
            )
        except Exception as exc:  # noqa: BLE001 - 路由器不可用不能阻断取数
            self.logger.warning("数据源路由器初始化失败，回退直连：%s", exc)
            self._router = None
        return self._router

    def _router_local(self, *, kind, symbol, market, start, end, **kwargs) -> pd.DataFrame:
        """本地兜底（路由器职责）：只认覆盖请求区间的原始价缓存，半段数据充不了数。

        v3.46：兜底从「外层 get_daily 的善意」变成路由器强制持有的 LocalSource，
        直调 DataRouter.fetch 的新路径（watch_only / 监控）因此同样有兜底。
        """
        if kind != "daily":
            return pd.DataFrame()
        try:
            cached = self._read_cache(self._raw_path(market, symbol))
        except Exception as exc:  # noqa: BLE001 - 口径不可信等一律按「无兜底」处理
            self.logger.warning("[local] %s %s 本地兜底读取失败：%s", market, symbol, exc)
            return pd.DataFrame()
        if cached is None or cached.empty or not self._covers(cached, start, end):
            return pd.DataFrame()
        df = cached.loc[start:end]
        if df.empty:
            return pd.DataFrame()
        df.attrs["stale"] = True          # 缓存兜底必然不是最新，交给时效闸门裁决
        df.attrs["local_fallback_cache"] = True
        return self._enforce_stale(df, market, symbol, "daily")

    def _source_health_path(self, conf: dict) -> Path:
        rel = Path(conf.get("source_health_file") or "data_cache/source_health.json")
        if rel.is_absolute():
            return rel
        cache = Path(self.cache_dir)
        try:
            isolated = cache.resolve() != Path(config.DATA_CACHE_DIR).resolve()
        except OSError:
            isolated = True
        # 自定义缓存目录（测试/多实例）时健康档案一并隔离，避免污染真实档案
        return cache / rel.name if isolated else Path(config.BASE_DIR) / rel

    def _router_akshare(self, *, kind, symbol, market, start, end, **kwargs):
        if kind == "daily":
            return self._dispatch_daily(market, symbol, start, end, kwargs.get("adjust") or "")
        return self._dispatch_minute(market, symbol, str(kwargs.get("period") or "5"),
                                     start, end)

    def _router_baostock(self, *, kind, symbol, market, start, end, **kwargs):
        # 只承接 A 股分钟；当日/实时走新浪/东财的规则仍在 _fetch_cn_minute 内。
        # 路由器兜底同样必须守这条：end >= 今天时 BaoStock 只有盘后数据，
        # 拿它兜底会把「今日无数据」变成「拿到昨天的」，必须显式判为不可用。
        if str(end) >= _date.today().strftime("%Y%m%d"):
            from data.source_adapter import SourceUnavailableError
            raise SourceUnavailableError("当日/实时分钟线不走 BaoStock（仅盘后历史）")
        return self._fetch_cn_stock_minute_baostock(symbol, str(kwargs.get("period") or "5"),
                                                    start, end)

    # ==================== 日线路由 ====================

    def _fetch_daily(self, market: str, symbol: str, start: str, end: str, adjust: str) -> pd.DataFrame:
        """日线取数入口：先校验市场，再交给 DataRouter 选源（v3.45 / 13.1）。"""
        if market in _NO_KLINE_MARKETS:
            raise ValueError(f"[{market}] {_NO_KLINE_MARKETS[market]}")
        if market not in _SUPPORTED_DAILY_MARKETS:
            raise ValueError(f"{market} 暂不支持日线接口，请在策略中显式指定 market_type")
        router = self._build_source_router()
        if router is not None:
            return router.fetch("daily", symbol, market, start, end, adjust=adjust)
        return self._dispatch_daily(market, symbol, start, end, adjust)

    def _dispatch_daily(self, market: str, symbol: str, start: str, end: str, adjust: str) -> pd.DataFrame:
        """按市场分发到具体 akshare 解析实现（作为 AkshareSource 的 dispatch）。"""
        route = {
            "cn_stock": self._fetch_cn_stock_daily,
            "cn_etf": self._fetch_cn_etf_daily,
            "us_stock": self._fetch_us_stock_daily,
            "us_etf": self._fetch_us_stock_daily,
            "hk_stock": self._fetch_hk_stock_daily,
            "cn_convertible": self._fetch_cn_cb_daily,
            "cn_reits": self._fetch_cn_reits_daily,
            "cn_future": self._fetch_cn_futures_daily,
            "global_future": self._fetch_intl_futures_daily,
            "forex": self._fetch_forex_daily,
            "cn_option": self._fetch_cn_option_daily,
            "crypto": self._fetch_crypto_daily,
            "cn_fund": self._fetch_cn_fund_nav,
            "cn_reverse_repo": self._fetch_cn_repo_rate,
            "cn_index": self._fetch_cn_index_daily,
        }
        handler = route.get(market)
        if handler is None:
            raise ValueError(f"{market} 暂不支持日线接口，请在策略中显式指定 market_type")
        return handler(symbol, start, end, adjust)

    def _fetch_cn_stock_daily(self, symbol, start, end, adjust):
        try:
            raw = self._request(ak.stock_zh_a_hist, symbol=symbol, period="daily",
                                start_date=start, end_date=end, adjust=adjust or "",
                                _source="eastmoney")
            # 东财 stock_zh_a_hist 成交量单位=【手】（实测 600519 比值 99.69）→ ×100 统一为股
            return self._standardize(raw, interface="stock_zh_a_hist",
                                     market="cn_stock", symbol=symbol)
        except Exception as exc:  # noqa: BLE001 - 东财失败时改用新浪源
            self.logger.warning("stock_zh_a_hist 失败(%s)，改用 stock_zh_a_daily", exc)
            prefix = "sh" if str(symbol).startswith(("6", "9")) else "sz"
            raw = self._request(ak.stock_zh_a_daily, symbol=f"{prefix}{symbol}",
                                start_date=start, end_date=end, adjust=adjust or "",
                                _source="sina")
            # 新浪 stock_zh_a_daily 成交量单位=【股】、成交额=【元】（实测比值 1.0000）
            return self._standardize(raw, interface="stock_zh_a_daily",
                                     market="cn_stock", symbol=symbol)

    def _fetch_cn_etf_daily(self, symbol, start, end, adjust):
        try:
            raw = self._request(ak.fund_etf_hist_em, symbol=symbol, period="daily",
                                start_date=start, end_date=end, adjust=adjust or "",
                                _source="eastmoney")
            # 东财 ETF 成交量单位=【手】（实测 510300 比值 100.0071）→ ×100 统一为股
            return self._standardize(raw, interface="fund_etf_hist_em",
                                     market="cn_etf", symbol=symbol)
        except Exception as exc:  # noqa: BLE001 - 东财失败时改用新浪源
            self.logger.warning("fund_etf_hist_em 失败(%s)，改用 fund_etf_hist_sina", exc)
            prefix = "sh" if str(symbol).startswith(("5", "6")) else "sz"
            raw = self._request(ak.fund_etf_hist_sina, symbol=f"{prefix}{symbol}",
                                _source="sina")
            # 新浪 ETF 接口不支持复权：此处返回不复权价，复权因子会退化为 1，必须显式标注
            self.logger.warning("[cn_etf] 新浪回退源不支持复权，%s 本次返回不复权价（adjust=none）", symbol)
            df = self._standardize(raw, interface="fund_etf_hist_sina",
                                   market="cn_etf", symbol=symbol).loc[start:end]
            df.attrs["adjust"] = "none"
            df.attrs["adjust_note"] = "新浪 ETF 源不支持复权，返回不复权价"
            return df


    def _fetch_us_stock_daily(self, symbol, start, end, adjust):
        """美股日线自建双价出口（评审 2026-11-26 裁定选③：人工登记事件表）。

        - 仅放行治理面 ``US_STOCK_CONFORMANCE.manual_events`` 已登记的标的
          （事件须逐位核对纳斯达克官网/上市公司官方披露，禁止凭记忆填写）；
          未登记标的 fail-closed raise，禁止降级以 raw/无事件 adj 放行
        - raw 固定 adjust="" 取数（禁止消费数据源黑箱复权价，与港股同构），
          双价由 manual_events 自建因子现算：adj = raw × factor（信号/收益），
          raw_* 列（撮合/费用/成交记录）
        - 事件核验/三级跳变审计复用港股共享实现（conf=US_STOCK_CONFORMANCE，
          拆股强制解释线 50%、事件日核验线 5%），逻辑零拷贝
        """
        conf = getattr(config, "US_STOCK_CONFORMANCE", {}) or {}
        sym = str(symbol).upper()
        registry = {str(k).upper(): v for k, v in
                    (conf.get("manual_events") or {}).items()}
        events_spec = registry.get(sym)
        # 评审裁定（选③）：未登记事件覆盖的标的禁止取数/回测（含后续新增
        # 标的），保持 raise 不放松；登记标的（含零事件登记如 TSLA）放行
        if events_spec is None:
            mode = str(conf.get("manual_events_mode") or "raise_unlisted")
            if mode == "raise_unlisted":
                raise RuntimeError(
                    f"美股 {sym} 未在治理面 manual_events 登记分红/拆股事件覆盖"
                    f"（manual_events_mode=raise_unlisted）：fail-closed 禁止取数/"
                    "回测——raw 序列带未解释除净/拆股跳变会污染信号；仅放行已逐位"
                    "核对官方披露数据并登记完整事件的标的，禁止降级")
            raise ValueError(f"未知 manual_events_mode: {mode}")
        code = self._resolve_us_symbol(sym)
        last_error = None
        df = None
        # 原始价固定 adjust=""（禁止黑箱复权价；请求口径对出口帧无影响）
        for candidate in ([code] if code else []) + [f"{p}.{sym}" for p in ("105", "106", "107")]:
            if not candidate:
                continue
            try:
                raw = self._request(ak.stock_us_hist, symbol=candidate, period="daily",
                                    start_date=start, end_date=end, adjust="",
                                    _source="eastmoney")
                cand_df = self._standardize(raw, interface="stock_us_hist",
                                            market="us_stock", symbol=sym)
                if not cand_df.empty:
                    cand_df.attrs["resolved_symbol"] = candidate
                    df = cand_df
                    break
            except Exception as exc:  # noqa: BLE001 - 东财失败时改用新浪源
                last_error = exc
        if df is None:
            try:
                raw = self._request(ak.stock_us_daily, symbol=sym, adjust="",
                                    _source="sina")
                df = self._standardize(raw, interface="stock_us_daily",
                                       market="us_stock", symbol=sym).loc[start:end]
                if not df.empty:
                    # 新浪美股日线只有 OHLCV，没有成交额：明确置 NaN，禁止补 0 混进流动性过滤
                    df = df.copy()
                    df["amount"] = np.nan
                    df.attrs["amount_missing"] = True
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        if df is None or df.empty:
            raise RuntimeError(f"美股 {sym} 日线获取失败: {last_error}")
        # ---- manual_events 自建双价（与港股 _fetch_hk_stock_daily 同构） ----
        factor = pd.Series(1.0, index=df.index)
        n_events = 0
        cum = 1.0
        event_days = set()
        for ev in events_spec:
            exd = pd.Timestamp(ev["ex_date"])
            etype = str(ev.get("type") or "")
            if exd not in df.index:
                continue
            pos = df.index.get_loc(exd)
            if pos == 0:
                continue
            prev_raw = float(df["close"].iloc[pos - 1])
            cur_raw = float(df["close"].iloc[pos])
            if etype == "cash_dividend":
                div = float(ev.get("div") or 0.0)
                if prev_raw <= div:
                    continue
                cum *= prev_raw / (prev_raw - div)
                # ① 事件日核验线（5%）：manual_events 与价格矛盾即拒绝（共享实现）
                self._hk_event_verify(sym, exd, prev_raw, cur_raw, div, conf=conf)
            elif etype == "split":
                ratio = float(ev.get("ratio") or 0.0)
                if ratio <= 0:
                    raise ValueError(f"美股 {sym} manual_events 拆股比例非法: {ratio}")
                cum *= ratio
                # 拆股核验（残差同 5% 核验线）：raw 隔夜跳变应≈1/ratio - 1
                actual = cur_raw / prev_raw - 1.0
                expected = 1.0 / ratio - 1.0
                thr = float((conf.get("jump_audit") or {}).get("threshold") or 0.05)
                if abs(actual - expected) >= thr:
                    raise JumpAuditError(
                        f"美股 {sym} 拆股事件日 {exd.date()} 核验失败：manual_events "
                        f"登记比例 1:{ratio:g}（预期 raw 跳变 {expected:+.2%}），"
                        f"实际 {actual:+.2%}，残差 {abs(actual - expected):.2%} ≥ "
                        f"{thr:.0%}——事件表与价格矛盾，禁止生成 adj 序列")
            else:
                raise ValueError(
                    f"美股 {sym} manual_events 未知事件类型 {etype!r}："
                    "仅支持 cash_dividend/split（治理面 schema）")
            factor[factor.index >= exd] = cum
            event_days.add(exd)
            n_events += 1
        # ②③ 拆股强制解释线（50%）+ 无事件审计带（5%~50%，共享实现，conf=US）
        audit_band = self._hk_jump_audit(sym, df, factor, event_days, conf=conf)
        # 双价构建（adj 主列 + raw_* 列 + 因子列，与港股同构）
        for c in ("open", "high", "low", "close"):
            df[f"raw_{c}"] = df[c]
            df[c] = df[c] * factor
        df["adj_factor"] = factor
        df.attrs.update({
            "events_source": "manual_events",
            "n_events_applied": n_events,
            "dual_price": True,
            "adjust": "hfq_self_built",
            "price_adjust": "hfq_self_built",
            "currency": str(conf.get("currency") or "USD"),
            "fx_fixed_cny": float(conf.get("fx_fixed_cny") or 7.20),
        })
        if len(audit_band):
            # 无事件审计带（5%~50%）：与港股同构强制持久化——WARNING 日志 +
            # attrs["audit_warnings"]（回测引擎收集进 result.meta 落盘）
            df.attrs["audit_warnings"] = audit_band
            conf_audit = conf.get("jump_audit") or {}
            self.logger.warning(
                "[us_stock] %s 无事件审计带 %d 日（%.0f%%~%.0f%%，未拦截，"
                "与真实波动不可分——明细已写入 attrs.audit_warnings 随回测报告"
                "落盘）：%s",
                sym, len(audit_band),
                float(conf_audit.get("threshold") or 0.05),
                float(conf_audit.get("threshold_split") or 0.50),
                "、".join(f"{x['date']} {x['jump']:+.2%}" for x in audit_band))
        return df

    def _hk_event_table(self, code: str, src_name: str):
        """港股事件表拉取与解析（日线/分钟共用单一实现）。

        返回 [(除净日 Timestamp, 每股派息 HKD float)]；事件源获取失败直接
        raise（治理面 events_unavailable_action=raise，禁止按零事件生成 adj）。
        """
        if src_name != "em_stock_hk_dividend_payout_em":
            raise ValueError(f"未知港股事件源: {src_name}")
        try:
            ev = self._request(ak.stock_hk_dividend_payout_em, symbol=code,
                               _source="eastmoney")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"港股 {code} 事件源 em_stock_hk_dividend_payout_em 获取失败："
                f"{exc}（治理面 events_unavailable_action=raise，"
                "禁止静默按零事件生成 adj 序列）") from exc
        # 修复记录（v3.54 港股接入冒烟）：原写法 (ev or pd.DataFrame()) 对
        # 非空 DataFrame 触发真值判断 ValueError，事件源可达时 00700 必崩
        ev = ev if ev is not None and len(ev) > 0 else None
        out = []
        for _, r in (ev.iterrows() if ev is not None else []):
            exd = pd.Timestamp(r.get("除净日"))
            if pd.isna(exd):
                continue
            m = re.search(r"每股[派息]?港币([\d.]+)元|港币([\d.]+)元",
                          str(r.get("分红方案") or ""))
            div = float(m.group(1) or m.group(2)) if m else 0.0
            if div > 0:
                out.append((exd, div))
        return out

    def _hk_jump_audit(self, code, df, factor, event_days, adj_close=None, conf=None):
        """港股三级跳变审计（日线/分钟共用单一实现，阈值完全复用不放松）。

        ① 事件日核验线（裁定 5%）：事件日 raw 隔夜跳变与事件幅度残差 ≥5% → raise；
        ② 拆股强制解释线（25%）：adj 序列无事件解释跳变 → JumpAuditError；
        ③ 无事件审计带（5%~25%）：逐日明细列表返回（attrs/回测 meta 持久化）。
        返回审计带 list[{date, jump}]。conf 形参供美股（US_STOCK_CONFORMANCE，
        拆股线 50%）复用同一实现——阈值来自各自治理面，逻辑零拷贝。
        """
        conf = conf if conf is not None else getattr(
            config, "HK_STOCK_CONFORMANCE", {}) or {}
        audit = conf.get("jump_audit") or {}
        thr_split = float(audit.get("threshold_split") or 0.25)
        thr_audit = float(audit.get("threshold") or 0.05)
        adj = (df["close"] * factor) if adj_close is None else adj_close
        jumps = adj.pct_change().abs()
        not_event = pd.Series([i not in event_days for i in jumps.index],
                              index=jumps.index)
        unexplained_split = jumps[(jumps >= thr_split) & not_event]
        if len(unexplained_split) and str(audit.get("action") or "raise") == "raise":
            first = unexplained_split.index[0]
            raise JumpAuditError(
                f"港股 {code} 序列存在无事件解释的 {thr_split:.0%} 以上跳变"
                f"（首例 {first.date()} {float(jumps.loc[first]):+.2%}）："
                "事件表不含对应拆股/分派记录，禁止生成被污染的 adj 序列"
                f"（jump_audit.threshold_split={thr_split}）")
        band = jumps[(jumps >= thr_audit) & (jumps < thr_split) & not_event]
        return [{"date": str(d.date()), "jump": round(float(v), 6)}
                for d, v in band.items()]

    def _hk_event_verify(self, code, exd, prev_raw, cur_raw, div, conf=None):
        """① 事件日核验线（裁定 5%，日线/分钟共用）：事件表登记幅度与实际
        raw 隔夜跳变残差 ≥5% → JumpAuditError（漏登/错登/日期错位被抓出）。"""
        conf = conf if conf is not None else getattr(
            config, "HK_STOCK_CONFORMANCE", {}) or {}
        audit_thr = float((conf.get("jump_audit") or {}).get("threshold") or 0.05)
        actual = float(cur_raw) / float(prev_raw) - 1.0
        expected = -float(div) / float(prev_raw)
        if abs(actual - expected) >= audit_thr:
            raise JumpAuditError(
                f"港股 {code} 事件日 {exd.date()} 核验失败：事件表登记派息 "
                f"{div} HKD（预期除净幅度 {expected:+.2%}），"
                f"实际 raw 隔夜跳变 {actual:+.2%}，残差 "
                f"{abs(actual - expected):.2%} ≥ {audit_thr:.0%}"
                "——事件表与价格矛盾，禁止生成 adj 序列（jump_audit.threshold）")

    def _hk_daily_factor(self, code: str, start: str, end: str):
        """港股日频自建因子（00700 事件表；02800 彻底 raise）——分钟线折算用。

        返回 (factor_df, audit_band)：factor_df.index=交易日、列 hfq_factor
        （稀疏表：序列首日 1.0 + 各除净日累计因子），供 _apply_adjust 按所属
        交易日 ffill 折算（与 A 股分钟双价同构）。日线 raw 经 akshare 独立
        拉取（不经 get_daily 缓存，避免递归），事件解析与三级审计与日线
        共用同一实现。
        """
        conf = getattr(config, "HK_STOCK_CONFORMANCE", {}) or {}
        events_registry = {str(k).zfill(5): v for k, v in
                           (conf.get("events_source") or {}).items()}
        src_name = events_registry.get(str(code).zfill(5))
        # 评审 2026-11-26 裁定（收紧）：事件源缺失标的【彻底拒绝取数】——
        # 分钟线与日线同闸，raw 序列带除净跳变同样污染信号
        if src_name is None:
            action = str(conf.get("events_unavailable_action") or "raise")
            if action == "raise":
                raise RuntimeError(
                    f"港股 {code} 分红事件源缺失（治理面 events_source 未登记），"
                    f"无法构建双价序列：events_unavailable_action=raise，"
                    "禁止以 raw 或无事件 adj 任何形式放行；"
                    "待补权威 ETF 事件源后按治理面登记放行")
            raise ValueError(f"未知 events_unavailable_action: {action}")
        # 日线 raw（独立取数防递归；起始前移 30 天保证首 bar 有因子基准）
        pre_start = (pd.Timestamp(start) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        try:
            raw = self._request(ak.stock_hk_hist, symbol=str(code).zfill(5),
                                period="daily", start_date=pre_start,
                                end_date=end, adjust="", _source="eastmoney")
            df = self._standardize(raw, interface="stock_hk_hist",
                                   market="hk_stock", symbol=str(code).zfill(5))
        except Exception as exc:  # noqa: BLE001 - 东财失败时改用新浪源
            self.logger.warning("stock_hk_hist 失败(%s)，改用 stock_hk_daily", exc)
            raw = self._request(ak.stock_hk_daily, symbol=str(code).zfill(5),
                                adjust="", _source="sina")
            df = self._standardize(raw, interface="stock_hk_daily",
                                   market="hk_stock", symbol=str(code).zfill(5))
            df = df.loc[pre_start:end]
        events = self._hk_event_table(str(code).zfill(5), src_name)
        cum = 1.0
        rows = []
        n_events = 0
        event_days = set()
        for exd, div in events:
            if exd not in df.index:
                continue
            pos = df.index.get_loc(exd)
            if pos == 0:
                continue
            prev_raw = float(df["close"].iloc[pos - 1])
            if prev_raw <= div:
                continue
            cum *= prev_raw / (prev_raw - div)
            rows.append((exd, cum))
            event_days.add(exd)
            n_events += 1
            # ① 事件日核验线（裁定 5%）：事件表与价格矛盾即拒绝
            self._hk_event_verify(str(code).zfill(5), exd, prev_raw,
                                  float(df["close"].iloc[pos]), div)
        factor = pd.Series(1.0, index=df.index)
        for exd, c in rows:
            factor[factor.index >= exd] = c
        audit_band = self._hk_jump_audit(str(code).zfill(5), df, factor, event_days)
        # 双口径因子表：hfq 为主（后复权累计）；qfq = hfq / 最新累计（常数归一，
        # 收益率/信号不变，仅绝对价基准不同）——防止调用方 adjust="qfq" 时
        # _apply_adjust 找不到列名崩掉
        last_cum = float(factor.iloc[-1]) if len(factor) else 1.0
        factor_df = pd.DataFrame({
            "hfq_factor": factor,
            "qfq_factor": factor / (last_cum if last_cum > 0 else 1.0),
        })
        factor_df.attrs["n_events_applied"] = n_events
        return factor_df, audit_band

    def _fetch_hk_stock_daily(self, symbol, start, end, adjust):
        code = str(symbol).zfill(5)
        conf = getattr(config, "HK_STOCK_CONFORMANCE", {}) or {}
        events_registry = {str(k).zfill(5): v for k, v in
                           (conf.get("events_source") or {}).items()}
        stamp_exempt = {str(x).zfill(5) for x in (conf.get("stamp_duty_exempt") or [])}
        src_name = events_registry.get(code)
        # 评审 2026-11-26 裁定（收紧）：事件源缺失的标的【彻底拒绝取数】——
        # raw 序列带除净跳变同样污染信号，事件不全的标的禁止跑回测，
        # 待补 ETF 分红事件源后再放行（fail-closed，不是 bug）
        if src_name is None:
            action = str(conf.get("events_unavailable_action") or "raise")
            if action == "raise":
                raise RuntimeError(
                    f"港股 {code} 分红事件源缺失（治理面 events_source 未登记），"
                    f"无法构建双价序列：events_unavailable_action=raise，"
                    "禁止以 raw 或无事件 adj 任何形式放行；"
                    "待补权威 ETF 事件源后按治理面登记放行")
            raise ValueError(f"未知 events_unavailable_action: {action}")
        # 原始价固定 adjust=""（禁止消费数据源黑箱复权价；v3.54 港股接入）
        try:
            raw = self._request(ak.stock_hk_hist, symbol=code, period="daily",
                                start_date=start, end_date=end, adjust="",
                                _source="eastmoney")
            df = self._standardize(raw, interface="stock_hk_hist",
                                   market="hk_stock", symbol=code)
        except Exception as exc:  # noqa: BLE001 - 东财失败时改用新浪源
            self.logger.warning("stock_hk_hist 失败(%s)，改用 stock_hk_daily", exc)
            raw = self._request(ak.stock_hk_daily, symbol=code, adjust="",
                                _source="sina")
            df = self._standardize(raw, interface="stock_hk_daily",
                                   market="hk_stock", symbol=code).loc[start:end]
        # 自建双价（事件表独立因子，与 A 股/期货双价体系同构）：
        #   adj = raw × factor（信号/收益/权益），raw_* 列（撮合/费用/成交记录）
        # 事件解析/核验/审计全部走共享方法（与分钟线 _hk_daily_factor 单一实现，
        # 2026-11-26 分钟线预检重构）
        factor = pd.Series(1.0, index=df.index)
        n_events = 0
        cum = 1.0
        event_days = set()
        for exd, div in self._hk_event_table(code, src_name):
            if exd not in df.index:
                continue
            pos = df.index.get_loc(exd)
            if pos == 0:
                continue
            prev_raw = float(df["close"].iloc[pos - 1])
            if prev_raw <= div:
                continue
            cum *= prev_raw / (prev_raw - div)
            factor[factor.index >= exd] = cum
            event_days.add(exd)
            n_events += 1
            # ① 事件日核验线（裁定阈值 5%，共享实现）
            self._hk_event_verify(code, exd, prev_raw,
                                  float(df["close"].iloc[pos]), div)
        # ②③ 拆股强制解释线（25%）+ 无事件审计带（5%~25%，共享实现）
        audit_band = self._hk_jump_audit(code, df, factor, event_days)
        # 双价构建（adj 主列 + raw_* 列 + 因子列；修复记录：上轮重写时误删此段
        # 致 KeyError raw_close，已补回）
        for c in ("open", "high", "low", "close"):
            df[f"raw_{c}"] = df[c]
            df[c] = df[c] * factor
        df["adj_factor"] = factor
        df.attrs.update({
            "events_source": src_name,
            "n_events_applied": n_events,
            "dual_price": True,
            "adjust": "hfq_self_built",
            "price_adjust": "hfq_self_built",
            "lot_size": self.get_hk_lot_size(code),
            "stamp_duty_exempt": code in stamp_exempt,
            "currency": "HKD",
        })
        if len(audit_band):
            # 无事件审计带（5%~25%）：评审裁定要求强制持久化——既落 WARNING 日志，
            # 也写入 attrs["audit_warnings"]（随边车持久化，回测引擎收集进
            # result.meta.audit_warnings 随回测报告落盘），禁止仅控制台打印
            df.attrs["audit_warnings"] = audit_band
            conf_audit = conf.get("jump_audit") or {}
            self.logger.warning(
                "[hk_stock] %s 无事件审计带 %d 日（%.0f%%~%.0f%%，未拦截，"
                "与真实波动不可分——明细已写入 attrs.audit_warnings 随回测报告"
                "落盘）：%s",
                code, len(audit_band),
                float(conf_audit.get("threshold") or 0.05),
                float(conf_audit.get("threshold_split") or 0.25),
                "、".join(f"{x['date']} {x['jump']:+.2%}" for x in audit_band))
        return df

    def _fetch_cn_cb_daily(self, symbol, start, end, adjust):
        # 新浪可转债日线：volume 单位=张（与东财 1 手=10 张 核对一致），无 amount 列、不支持复权
        code = self._cb_symbol(symbol)
        raw = self._request(ak.bond_zh_hs_cov_daily, symbol=code, _source="sina")
        full = self._standardize(raw, interface="bond_zh_hs_cov_daily",
                                 market="cn_convertible", symbol=code)
        df = full.loc[start:end]
        if df.empty and not full.empty:
            # v3.47：取数层禁止给空表写 empty_reason——「返回空」正是被限流源的表形，
            # 自证会把净空闸门绕过去。这里只保留事实（最后一根 bar 日期），
            # 是否「不在市」由路由器向 security_master 取证。
            df.attrs["last_bar_date"] = str(full.index.max())[:10]
        if not df.empty:
            amount = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
            if float(amount.abs().sum()) == 0.0:
                # 无成交额字段时**不能补 0**（会被流动性过滤全量剔除），按 张 × 元/张 估算
                df = df.copy()
                df["amount"] = pd.to_numeric(df["close"], errors="coerce") * \
                    pd.to_numeric(df["volume"], errors="coerce")
                df.attrs["amount_estimated"] = True
                df.attrs["amount_note"] = "新浪可转债日线无成交额，amount=close×volume(张) 估算"
                self.logger.info("[cn_convertible] %s 无成交额字段，amount=close×volume 估算", code)
        return df


    def _fetch_cn_reits_daily(self, symbol, start, end, adjust):
        """公募REITs 日线。复权市场：raw 存不复权价，因子单独缓存，复权价现算。

        主源东财 reits_hist_em（仅返回全量历史、无可选参数）；失败时回退新浪
        fund_etf_hist_sina（REITs 与 ETF 同通道，实测 volume=份、amount=元）。
        """
        func = getattr(ak, "reits_hist_em", None)
        try:
            if func is None:
                raise RuntimeError("当前 akshare 版本无 reits_hist_em")
            raw = self._request(func, symbol=str(symbol), _source="eastmoney_reits")
            df = self._standardize(raw, interface="reits_hist_em",
                                   market="cn_reits", symbol=symbol)
        except Exception as exc:  # noqa: BLE001 - 东财失败时改用新浪
            self.logger.warning("reits_hist_em 失败(%s)，改用 fund_etf_hist_sina", exc)
            prefix = "sh" if str(symbol).startswith(("5", "6")) else "sz"
            raw = self._request(ak.fund_etf_hist_sina, symbol=f"{prefix}{symbol}",
                                _source="sina")
            df = self._standardize(raw, interface="fund_etf_hist_sina",
                                   market="cn_reits", symbol=symbol)
            df.attrs["adjust"] = "none"
            df.attrs["adjust_note"] = "新浪 REITs 源不支持复权，返回不复权价"
            self.logger.warning("[cn_reits] 新浪回退源不支持复权，%s 本次返回不复权价", symbol)
        return df.loc[start:end]

    # ==================== 指数（cn_index，仅基准/择时，不可交易） ====================

    @staticmethod
    def _index_parts(symbol) -> tuple:
        """指数代码拆成 (前缀 sh/sz, 6 位数字)。

        sh000300 → ('sh','000300')；000300（无前缀）按 config.CN_INDEX.common_codes
        与 399/980/981 段推断交易所，推断不出时抛错而不是静默取个股数据。
        """
        text = str(symbol).strip().upper()
        if len(text) == 8 and text[:2] in ("SH", "SZ") and text[2:].isdigit():
            return text[:2].lower(), text[2:]
        digits = re.sub(r"\D", "", text)
        if len(digits) != 6:
            raise ValueError(f"无法识别为指数代码: {symbol}（请传 sh000300 / sz399001 形式）")
        if digits.startswith(("399", "980", "981")):
            return "sz", digits
        if digits.startswith(("000", "950", "880", "881")):
            return "sh", digits
        raise ValueError(f"{symbol} 不属于 A 股指数号段，请显式传 market_type='cn_index' 或检查代码")

    def _fetch_cn_index_daily(self, symbol, start, end, adjust):
        """指数日线：按 config.CN_INDEX_DAILY_PRIORITY 依次尝试（东财→新浪→BaoStock→腾讯）。

        代码格式：东财指数接口只认【裸 6 位】（000300），传 sh000300 会失败；
        新浪/BaoStock 认带前缀形式（sh000300 / sh.000300），格式在 _index_parts 里拆分。
        成交量单位：东财=手、新浪/BaoStock=股，差 100 倍，由 INTERFACE_UNITS 折算到统一「手」；
        该换算已用 BaoStock 交叉验证（2026-10-27 r=volume_sina/volume_bs=1.0000），
        attrs 显式标注 volume_unit / source_volume_unit，跨源切换打 WARNING。
        指数没有复权概念（adjust 一律视为 none）；禁止复用个股/期货接口。
        """
        # 中证官网专用指数（全收益 Hxxxxx / 净收益 Nxxxxx，v3.53 评审四轮·基准对齐）：
        # 东财/新浪/BaoStock 均不提供全收益指数，唯一源是中证指数官网（权威发布方），
        # 不走通用优先级链（其余源对 H00300 直接返回空，实测 2026-11-20）
        text = str(symbol).strip().upper()
        if len(text) == 6 and text[0] in ("H", "N") and text[1:].isdigit():
            return self._fetch_csindex_ex_return(text, start, end)

        prefix, digits = self._index_parts(symbol)
        errors = []
        for src in config.CN_INDEX_DAILY_PRIORITY:
            try:
                df = self._cn_index_daily_one(src, prefix, digits, start, end, symbol)
            except Exception as exc:  # noqa: BLE001 - 逐源回退
                errors.append(f"{src}={exc}")
                continue
            if errors:
                desc = self._CN_INDEX_SRC_DESC.get(src, src)
                self.logger.warning("[cn_index] %s 源已切换 → %s；成交量单位不同但已统一折算为「手」"
                                   "（%s）", symbol, desc, "；".join(errors))
            return df
        raise RuntimeError(f"[cn_index] {symbol} 日线全部源不可用：{'；'.join(errors)}")

    # 指数各源的成交量口径说明（跨源切换告警用）
    _CN_INDEX_SRC_DESC = {
        "eastmoney": "东财（volume=手、含成交额）",
        "sina": "新浪（volume=股、无成交额）",
        "baostock": "BaoStock（volume=股、含成交额）",
        "tencent": "腾讯（未接入：唯一数量列实测为成交量(手)）",
    }

    def _fetch_csindex_ex_return(self, code: str, start: str, end: str) -> pd.DataFrame:
        """中证官网全收益（H）/净收益（N）指数日线（v3.53 评审四轮·基准对齐）。

        全收益指数 = 价格指数 + 样本股分红再投资；净收益指数再扣 10% 红利税。
        基准含息对齐专用：策略按前复权（含息再投资）记账时，若仍用价格指数
        （不含股息）作基准，超额收益被系统性高估。
        """
        kind = {"H": "total_return", "N": "net_return"}[code[0]]
        # 接口只认紧凑日期（带连字符会少返回 ~200 行，实测 2026-11-20）
        s_compact = pd.Timestamp(start).strftime("%Y%m%d")
        e_compact = pd.Timestamp(end).strftime("%Y%m%d")
        raw = self._request(ak.stock_zh_index_hist_csindex, symbol=code,
                            start_date=s_compact, end_date=e_compact, _source="csindex")
        if raw is None or raw.empty:
            raise RuntimeError(f"[cn_index] 中证官网 {code} 返回空表")
        # 全收益/净收益指数仅保证收盘价（中证官网对早期区间不提供开盘/最高/最低，
        # 实测开盘列 1300+ 行 NaN）：OHLC 缺失用同行收盘价占位，避免质量检查把
        # 完整 close 序列误丢（基准曲线只消费 close）；attrs 显式标注占位事实
        for col in ("开盘", "最高", "最低"):
            if col in raw.columns:
                raw[col] = raw[col].fillna(raw["收盘"])
        ohlc_filled = True
        # 部分返回防护（2026-11-20 实测该接口偶发只返回 ~345 行且被静默缓存）：
        # 交易日数按工作日近似，返回行数不足期望的 75% 视为接口部分返回，直接报错
        # 禁止落缓存（fail-closed，防止残缺指数基准被当作完整数据用于超额计算）
        s_d = str(pd.Timestamp(start).date())
        e_d = str(pd.Timestamp(end).date())
        expected = max(int(np.busday_count(s_d, e_d)) + 1, 1)
        if len(raw) < expected * 0.75:
            raise RuntimeError(
                f"[cn_index] 中证官网 {code} 返回 {len(raw)} 行，显著少于期望约 {expected} 个"
                f"交易日（疑似接口部分返回），拒绝提供残缺指数数据；请重试")
        df = self._standardize(raw, interface="stock_zh_index_hist_csindex",
                               market="cn_index", symbol=code)
        df = df.loc[start:end]
        df.attrs.update({
            "adjust": "none", "market": "cn_index", "source": "csindex",
            "index_kind": kind,
            "amount_missing": True,      # 中证官网接口无实际成交额语义（字段为指数成交额汇总）
            "ohlc_filled_with_close": ohlc_filled,   # 全收益指数无盘价语义，OHLC 用 close 占位
            "basis_note": ("全收益指数（含样本股分红再投资）" if kind == "total_return"
                           else "净收益指数（全收益再扣 10% 红利税）"),
        })
        if df.empty:
            raise RuntimeError(f"[cn_index] 中证官网 {code} 区间 {start}~{end} 无数据")
        return df

    def _cn_index_daily_one(self, src, prefix, digits, start, end, symbol) -> pd.DataFrame:
        """单个指数日线源，返回已标准化 + 单位归一 + attrs 标注的 DataFrame。"""
        attrs_note = {"adjust": "none", "market": "cn_index"}
        if src == "eastmoney":
            # 东财指数接口要求裸代码（000300），带前缀会 404/空返回
            self.logger.info("[cn_index] %s 东财 index_zh_a_hist 使用裸代码 %s", symbol, digits)
            raw = self._request(ak.index_zh_a_hist, symbol=digits, period="daily",
                                start_date=start, end_date=end, _source="eastmoney")
            df = self._standardize(raw, interface="index_zh_a_hist",
                                   market="cn_index", symbol=symbol)
            df.attrs.update(attrs_note)
            return df.loc[start:end]

        if src == "sina":
            raw = self._request(ak.stock_zh_index_daily, symbol=f"{prefix}{digits}",
                                _source="sina")
            df = self._standardize(raw, interface="stock_zh_index_daily",
                                   market="cn_index", symbol=symbol)
            df.attrs.update(attrs_note)
            df.attrs["amount_note"] = "新浪指数日线无成交额字段"
            # 新浪源无成交额：不得补 0 冒充「零成交」，统一置 NaN 并显式标注
            if "amount" in df.columns:
                df["amount"] = np.nan
            df.attrs["amount_missing"] = True
            return df.loc[start:end]

        if src == "baostock":
            if bs is None:
                raise RuntimeError("未安装 baostock")
            code = f"{prefix}.{digits}"
            fields = "date,open,high,low,close,volume,amount"

            def _query():
                rs = self._bs_execute(
                    lambda client: client.query_history_k_data_plus(
                        code, fields, start_date=start, end_date=end,
                        frequency="d", adjustflag="3"),
                    "BaoStock 指数日线")
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                return pd.DataFrame(rows, columns=rs.fields)

            raw = self._request(_query, _source="baostock")
            if raw.empty:
                raise RuntimeError(f"BaoStock 指数日线为空（{start}~{end}）")
            df = self._standardize(raw, interface="baostock_index_daily",
                                  market="cn_index", symbol=symbol)
            df.attrs.update(attrs_note)
            return df.loc[start:end]

        if src == "tencent":
            # 腾讯只返回一个名为 amount 的数量列，实测为成交量(手)而非成交额，
            # 直接用会把「手」当「元」、且丢 volume → 明确报未接入，避免静默错单位
            raise NotImplementedError("腾讯指数源未接入（其 amount 列实为成交量(手)）")

        raise ValueError(f"未知的指数日线源: {src}")

    def _fetch_cn_index_minute(self, symbol, period, start, end) -> pd.DataFrame:
        """指数分钟线：东财 index_zh_a_hist_min_em（约 1 个月上限），超出显式标 capped。

        BaoStock 分钟线不含指数，禁止走 BaoStock；新浪指数分钟无时间游标，仅在东财失败时兜底。
        """
        prefix, digits = self._index_parts(symbol)
        errors = []
        try:
            raw = self._request(ak.index_zh_a_hist_min_em, symbol=digits, period=str(period),
                                start_date=f"{start} 09:30:00", end_date=f"{end} 15:00:00",
                                _source="eastmoney")
            df = self._standardize(raw, interface="index_zh_a_hist_min_em",
                                   market="cn_index", symbol=symbol)
            out = self._slice_minute(df, start, end, "cn_index", symbol)
            out.attrs["adjust"] = "none"
            # 东财指数分钟只返回最近约 1 个月：请求起点早于实际最早日即视为被截断
            first = pd.Timestamp(df.index.min()).date() if len(df) else None
            if first is not None and first > pd.Timestamp(start).date():
                out.attrs["minute_history_capped"] = True
                out.attrs["minute_available_from"] = str(first)
                self.logger.warning("[cn_index] %s %s 分钟线仅回溯到 %s（东财约 1 个月上限）",
                                    symbol, period, first)
            return out
        except Exception as exc:  # noqa: BLE001
            errors.append(f"eastmoney={exc}")
            self.logger.warning("[cn_index] %s 东财指数分钟失败，改用新浪；"
                               "源已切换，成交量单位不同（东财=手 / 新浪未实测，已标 unit_uncertain）",
                                symbol)

        try:
            raw = self._request(ak.stock_zh_a_minute, symbol=f"{prefix}{digits}",
                                period=str(period), adjust="", _source="sina")
            df = self._standardize(raw, interface="stock_zh_a_minute",
                                   market="cn_index", symbol=symbol)
            out = self._slice_minute(df, start, end, "cn_index", symbol)
            out.attrs["adjust"] = "none"
            out.attrs["unit_uncertain"] = True
            out.attrs["unit_evidence"] = "指数分钟线 volume/amount 源单位未实测，原值透传"
            if len(df) >= 1970:
                out.attrs["minute_history_capped"] = True
                self.logger.warning("[cn_index] %s 新浪指数分钟已达 1970 根上限且无时间游标", symbol)
            return out
        except Exception as exc:  # noqa: BLE001
            errors.append(f"sina={exc}")

        raise RuntimeError(f"[cn_index] {symbol} 指数分钟线取数失败：{'；'.join(errors)}")

    def _fetch_cn_futures_daily(self, symbol, start, end, adjust):
        variety = re.sub(r"\d", "", str(symbol)).upper() or str(symbol).upper()
        # 新浪期货主力连续：volume 单位=手（合约张数，因乘数而异不做 ×100），无 amount 字段
        # ⚠️ amount≈close×volume **不成立**：流动性过滤需按「成交额(元)」单独取，不得用 volume×close 估算
        df = self._standardize(self._request(ak.futures_main_sina, symbol=f"{variety}0",
                                             start_date=start, end_date=end,
                                             _source="sina_futures"),
                               interface="futures_main_sina",
                               market="cn_future", symbol=symbol)
        if df.empty:
            return df
        dominant = self.get_dominant_contract(variety)
        previous = self._load_dominant(variety)
        df.attrs["dominant_contract"] = dominant
        df.attrs["dominant_roll"] = bool(previous and dominant and previous != dominant)
        df.attrs["amount_missing"] = True  # 期货无成交额；禁止用 close×volume 估算
        if df.attrs["dominant_roll"]:
            self.logger.info("%s 主力合约换月: %s -> %s", variety, previous, dominant)
        if dominant:
            self._save_dominant(variety, dominant)
        return df

    # ---- v3.53 评审七轮：期货自建主力连续双序列（换月规则可控可对拍） ----

    def build_dominant_series(self, contracts: List[str], start: str, end: str,
                              variety: str = None) -> pd.DataFrame:
        """自建主力连续【双序列】：不消费数据源黑箱拼接（换月规则不可控不可对拍）。

        换月规则（声明口径）：合约按传入顺序视为到期序；某日「后一合约成交量
        首次超过当前合约」即换月日（当日量数据收盘后可知 → 无未来信息），
        当日起主力切换为后一合约。
        输出（与股票双价体系对齐的期货版）：
          - 主列 OHLC = 换月【回溯调整】连续价（信号/收益/回撤/熔断消费，
            消除换月缺口假信号）；
          - raw_open/high/low/close = 当日实际主力合约价（保证金/结算/报单消费）；
          - settle 列 = 当日实际主力结算价（涨跌停/强平/逐日盯市口径）；
          - contract 列 = 当日主力合约代码；roll 列 = 是否换月日（True/False）；
          - adj_factor 列 = 累计换月调整因子（adj = raw × adj_factor）。
        未平滑口径下换月缺口 = 新旧合约月差（虚构盈亏源），调整序列已消除；
        实际可成交价永远只在 raw 列。
        """
        variety = variety or re.sub(r"\d", "", str(contracts[-1])).upper()
        frames = {}
        for c in contracts:
            raw = self._request(ak.futures_zh_daily_sina, symbol=str(c).upper(),
                                _source="sina_futures")
            df = raw.rename(columns={"date": "date"})
            df["date"] = pd.to_datetime(df["date"])
            frames[str(c).upper()] = df.set_index("date").sort_index().astype(float)
        merged = pd.concat(
            {c: f[["open", "high", "low", "close", "volume", "settle"]]
             for c, f in frames.items()}, axis=1)
        rows, current, cum_factor = [], None, 1.0
        all_days = sorted({d for c in frames for d in frames[c].index})
        prev_close_of = {c: None for c in frames}
        for day in all_days:
            if current is None:
                current = str(contracts[0]).upper()
            # 【先】更新全部合约当日收盘（新合约切换前的前收必须可得，
            # 否则换月调整因子恒 1、缺口照旧——首轮实测踩坑点）
            self._update_prev(prev_close_of, merged, day)
            if current is not None:
                idx = [str(c).upper() for c in contracts].index(current)
                nxt = str(contracts[idx + 1]).upper() if idx + 1 < len(contracts) else None
                if (nxt and day in merged.index
                        and not pd.isna(merged.loc[day, (nxt, "volume")])
                        and not pd.isna(merged.loc[day, (current, "volume")])
                        and float(merged.loc[day, (nxt, "volume")])
                        > float(merged.loc[day, (current, "volume")])):
                    old = current
                    old_prev = prev_close_of.get(old)
                    new_prev = prev_close_of.get(nxt)
                    if old_prev and new_prev and new_prev > 0:
                        # 后复权式回溯调整：切换日按「旧主力前收 / 新主力前收」放大
                        # 历史因子，使调整序列跨换月连续（缺口只留在 raw 列）
                        cum_factor *= float(old_prev) / float(new_prev)
                    current = nxt
                    # 旧合约当日实际收盘（换月平旧腿的可成交价，评审七轮④：
                    # 换月日必须平旧开新两笔成交，月差与手续费如实入账）
                    old_close = None
                    if day in merged.index and not pd.isna(merged.loc[day, (old, "close")]):
                        old_close = float(merged.loc[day, (old, "close")])
                    rows.append(self._dominant_row(merged, frames, current, day,
                                                   cum_factor, roll=True,
                                                   roll_exit_price=old_close,
                                                   roll_prev_contract=old))
                    continue
            rows.append(self._dominant_row(merged, frames, current, day,
                                           cum_factor, roll=False))
        out = pd.DataFrame([r for r in rows if r is not None]).set_index("date")
        out = out.loc[(out.index >= pd.Timestamp(start))
                      & (out.index <= pd.Timestamp(end))]
        out.attrs.update({
            "market": "cn_future", "adjust": "none", "source": "self_built_dominant",
            "roll_rule": "volume_cross_same_day",
            "contracts": [str(c).upper() for c in contracts],
            "volume_unit": "手", "amount_missing": True,
            "dual_price": True,
            "basis_note": "主列=换月回溯调整连续价（信号）；raw_*=实际合约价（保证金/结算/报单）；"
                          "settle=结算价（涨跌停/强平/盯市口径）",
        })
        return out

    @staticmethod
    def _dominant_row(merged, frames, current, day, cum_factor, roll,
                      roll_exit_price=None, roll_prev_contract=None):
        if day not in merged.index or pd.isna(merged.loc[day, (current, "close")]):
            return None
        row = merged.loc[day, current]
        raw_o, raw_h = float(row["open"]), float(row["high"])
        raw_l, raw_c = float(row["low"]), float(row["close"])
        return {"date": day, "open": raw_o * cum_factor, "high": raw_h * cum_factor,
                "low": raw_l * cum_factor, "close": raw_c * cum_factor,
                "volume": float(row["volume"]), "settle": float(row["settle"]),
                "raw_open": raw_o, "raw_high": raw_h, "raw_low": raw_l,
                "raw_close": raw_c, "adj_factor": cum_factor,
                "contract": current, "roll": roll,
                # 换月平旧腿：旧合约当日实际收盘价 + 旧合约代码（引擎换月平开用）
                "roll_exit_price": roll_exit_price,
                "roll_prev_contract": roll_prev_contract}

    @staticmethod
    def _update_prev(prev_close_of, merged, day):
        """更新全部合约当日收盘（切换前新合约的前收是换月因子的必要输入）。"""
        for c in prev_close_of:
            if day in merged.index and c in merged.columns.get_level_values(0) \
                    and not pd.isna(merged.loc[day, (c, "close")]):
                prev_close_of[c] = float(merged.loc[day, (c, "close")])

    def build_dominant_series_minute(self, contracts, start, end, period="60min",
                                     variety=None):
        """自建主力连续【分钟双序列】（v3.54 终验：RB 2020~2026 60min 全期验证）。

        换月事件复用日线口径（build_dominant_series 的「当时量交叉」判定），
        分钟 bar 按所属交易日继承 contract/adj_factor（评审纪律：因子按日缓存、
        分钟价按所属交易日折算——与股票分钟复权同款）；换月标记只落在换月日
        【最后一根分钟 bar】（收盘确认量交叉 → 当日收盘机械平开一次，禁止日内
        每根 bar 重复触发换月成交）。平旧腿价 = 旧合约当日最后一根分钟收盘。
        settle 结算价分钟级不可得（新浪分钟无该字段）→ 不造列（禁止补 0/伪装），
        引擎按 settle 缺失回退 close 盯市；raw_* 列仍是实际合约价（报单/保证金口径）。
        """
        period_num = str((config.PERIOD_TO_MINUTE or {}).get(period, period))
        # 品种适用边界 fail-closed（v3.54 评审终验后补）：夜盘跨午夜品种（凌晨
        # 01:00/02:30 收盘）的分钟 bar 交易日归属未处理，序列会静默污染——
        # 边界由治理面白名单表达（CN_FUTURES_VARIETY.minute_series_supported），
        # 不由注释表达；未置位品种分钟序列显式拒绝（日线序列不受此限）
        variety = variety or re.sub(r"\d", "", str(contracts[-1])).upper()
        spec = config.CN_FUTURES_VARIETY.get(variety) or {}
        if not spec.get("minute_series_supported"):
            raise ValueError(
                f"品种 {variety} 未开启分钟序列支持（minute_series_supported 未置位）："
                "夜盘跨午夜品种的 bar 归属未处理，禁止生成会静默污染的分钟序列；"
                "支持边界见 config.CN_FUTURES_VARIETY（当前仅 23:00 前收盘及无夜盘品种）")
        daily = self.build_dominant_series(contracts, start, end, variety=variety)
        frames = {}
        for c in contracts:
            code = str(c).upper()
            raw = self._request(ak.futures_zh_minute_sina, symbol=code,
                                period=period_num, _source="sina_futures")
            time.sleep(0.3)  # 批量取数限速（勿高频调用）
            df = raw.copy()
            df["datetime"] = pd.to_datetime(df["datetime"])
            frames[code] = df.set_index("datetime").sort_index()
        day_factor = daily["adj_factor"]
        day_contract = daily["contract"]
        day_roll = daily["roll"]
        day_prev = daily["roll_prev_contract"]
        # 按日线交易日循环：每个交易日只取【当日主力合约】的分钟 bar（重叠期
        # 旧合约 bar 不得入序列——同窗口两条合约价 = 价格污染源）；交易日归属：
        # 日盘（物理 03:00~20:00 当日）+ 前一交易日夜盘（物理 ≥20:00）。
        # ⚠️ 限制声明：凌晨收盘品种（CU/AU/SC 夜盘至 01:00）的午夜后段归属未
        # 处理，本方法当前适用于 23:00 前收盘品种（RB/HC 等），扩展需交易日历。
        # 换月标记只落该交易日【最后一根】bar：量交叉以当日全天量判定，收盘后
        # 才确认——日内任何 bar 提前标记 = 未来函数（首轮踩坑：首根 bar 被标，
        # 等于用量交叉前的盘中数据做了收盘决策）。
        dates = list(daily.index)
        rows, idx = [], []
        for i, d in enumerate(dates):
            c = str(day_contract.loc[d])
            f = float(day_factor.loc[d])
            sub = frames.get(c)
            if sub is None or not len(sub):
                continue
            night_phys = dates[i - 1] if i else None
            day_part = sub[(sub.index.normalize() == d)
                           & (sub.index.hour >= 3) & (sub.index.hour < 20)]
            night_part = (sub[(sub.index.normalize() == night_phys)
                              & (sub.index.hour >= 20)]
                          if night_phys is not None else day_part.iloc[0:0])
            bars = pd.concat([night_part, day_part]).sort_index()
            if not len(bars):
                continue
            is_roll_day = bool(day_roll.loc[d])
            last_pos = len(bars) - 1
            old = day_prev.loc[d] if is_roll_day else None
            old_bars = (frames.get(str(old)) if old and str(old) in frames else None)
            old_day_bars = None
            if old_bars is not None and len(old_bars):
                ob_night = old_bars[(old_bars.index.normalize() == night_phys)
                                    & (old_bars.index.hour >= 20)] \
                    if night_phys is not None else old_bars.iloc[0:0]
                ob_day = old_bars[(old_bars.index.normalize() == d)
                                  & (old_bars.index.hour >= 3)
                                  & (old_bars.index.hour < 20)]
                old_day_bars = pd.concat([ob_night, ob_day]).sort_index()
            for pos, (dt, row) in enumerate(bars.iterrows()):
                raw_o, raw_h = float(row["open"]), float(row["high"])
                raw_l, raw_c = float(row["low"]), float(row["close"])
                is_roll = is_roll_day and pos == last_pos
                rec = {
                    "open": raw_o * f, "high": raw_h * f, "low": raw_l * f,
                    "close": raw_c * f, "volume": float(row["volume"]),
                    "raw_open": raw_o, "raw_high": raw_h, "raw_low": raw_l,
                    "raw_close": raw_c, "adj_factor": f,
                    "contract": c, "roll": is_roll,
                }
                if is_roll and old_day_bars is not None and len(old_day_bars):
                    rec["roll_exit_price"] = float(old_day_bars["close"].iloc[-1])
                    rec["roll_prev_contract"] = str(old)
                rows.append(rec)
                idx.append(dt)
        out = pd.DataFrame(rows, index=pd.DatetimeIndex(idx))
        out.attrs.update({
            "market": "cn_future", "adjust": "none", "source": "self_built_dominant",
            "roll_rule": "volume_cross_same_day_daily_basis",
            "contracts": [str(c).upper() for c in contracts],
            "period": period, "volume_unit": "手", "amount_missing": True,
            "dual_price": True, "settle_minute_missing": True,
            "basis_note": "主列=换月回溯调整连续分钟价（信号）；raw_*=实际合约价"
                          "（保证金/报单）；settle 分钟级不可得→引擎回退 close 盯市",
        })
        return out

    def _fetch_intl_futures_daily(self, symbol, start, end, adjust):
        # ⚠️ 外盘期货同样只有 volume（单位=手），无成交额；禁止用 close×volume 估算成交额
        df = self._standardize(self._request(ak.futures_foreign_hist,
                                             symbol=str(symbol).upper(),
                                             _source="sina_futures"),
                               interface="futures_foreign_hist",
                               market="global_future", symbol=symbol)
        df.attrs["volume_unit"] = "手"
        df.attrs["amount_missing"] = True
        return df.loc[start:end]

    def _fetch_forex_daily(self, symbol, start, end, adjust):
        code = str(symbol).replace("/", "").replace("-", "").upper()
        raw = self._request(ak.forex_hist_em, symbol=code, _source="eastmoney")
        return self._standardize(raw, interface="forex_hist_em",
                                 market="forex", symbol=code).loc[start:end]

    def _fetch_cn_option_daily(self, symbol, start, end, adjust):
        # 新浪期权日线：volume 单位=张（无成交额字段，单位未实测 → unit_uncertain）
        func = getattr(ak, "option_sse_daily_sina", None)
        if func is None:
            raise RuntimeError("当前 akshare 版本无 option_sse_daily_sina，请使用 get_option_chain() 获取期权链")
        code = re.sub(r"\D", "", str(symbol))
        raw = self._request(func, symbol=code, _source="sina_option")
        return self._standardize(raw, interface="option_sse_daily_sina",
                                 market="cn_option", symbol=code).loc[start:end]

    def _fetch_crypto_daily(self, symbol, start, end, adjust):
        """币安公共 K 线（分页，limit 上限 1000 → 循环拉取）。volume=币，amount=计价货币成交额。"""
        pair = f"{str(symbol).upper().replace('/USDT', '')}USDT"
        cursor = int(pd.Timestamp(start).timestamp() * 1000)
        end_ms = int((pd.Timestamp(end) + timedelta(days=1)).timestamp() * 1000)
        frames = []
        last_error = None
        for host in ("https://data-api.binance.vision", "https://api.binance.com",
                     "https://api1.binance.com"):
            try:
                frames = []
                cursor = int(pd.Timestamp(start).timestamp() * 1000)
                while cursor < end_ms:
                    text = self._http_get(
                        f"{host}/api/v3/klines",
                        params={"symbol": pair, "interval": "1d", "limit": 1000,
                                "startTime": cursor, "endTime": end_ms},
                        source="binance")
                    rows = json.loads(text)
                    if not rows:
                        break
                    frames.append(pd.DataFrame(rows, columns=[
                        "open_time", "open", "high", "low", "close", "volume", "close_time",
                        "amount", "trades", "taker_base", "taker_quote", "ignore"]))
                    if len(rows) < 1000:
                        break
                    cursor = int(rows[-1][6]) + 1
                if frames:
                    df = pd.concat(frames, ignore_index=True)
                    df["date"] = pd.to_datetime(df["open_time"], unit="ms")
                    return self._standardize(df, interface="binance_klines",
                                             market="crypto", symbol=symbol)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        raise RuntimeError(f"加密货币 {symbol} 日线获取失败（需网络可达）: {last_error}")

    def _fetch_cn_fund_nav(self, symbol, start, end, adjust):
        indicator = "累计净值走势" if adjust in ("hfq", "cumulative") else "单位净值走势"
        raw = self._request(ak.fund_open_fund_info_em, symbol=str(symbol),
                            indicator=indicator, _source="eastmoney")
        df = self._standardize(raw, interface="fund_open_fund_info_em",
                               market="cn_fund", symbol=symbol)
        if df.empty:
            return df
        df["open"] = df["close"]
        df["high"] = df["close"]
        df["low"] = df["close"]
        df["volume"] = 0.0
        df["amount"] = 0.0
        df["is_suspended"] = False
        return df.loc[start:end]

    def _fetch_cn_repo_rate(self, symbol, start, end, adjust):
        """国债逆回购日线：东财历史接口失败 → 东财快照备用源 → 仍失败则显式报错。

        逆回购收盘价是年化利率，amount/(close×volume) 无经济含义 → 接口标记 unit_uncertain；
        任何路径都不允许返回空表冒充成功（东财偶发 RemoteDisconnected）。
        """
        code = str(symbol)
        func = getattr(ak, "bond_buy_back_hist_em", None)
        errors = []
        if func is not None:
            try:
                raw = self._request(func, symbol=code, _source="eastmoney")
                df = self._standardize(raw, interface="bond_buy_back_hist_em",
                                       market="cn_reverse_repo", symbol=code)
                if not df.empty:
                    return df.loc[start:end]
                errors.append("bond_buy_back_hist_em 返回空数据")
            except Exception as exc:  # noqa: BLE001 - 换备用源继续
                errors.append(f"bond_buy_back_hist_em: {exc}")
                self.logger.warning("[cn_reverse_repo] %s 历史接口失败(%s)，改用快照备用源",
                                    code, exc)
        else:
            errors.append("当前 akshare 版本无 bond_buy_back_hist_em")

        # 备用源：东财回购快照（仅当日一根）；沪市 204xxx / 深市 1318xx
        snap_func = getattr(ak, "bond_sh_buy_back_em", None) if code.startswith("204") \
            else getattr(ak, "bond_sz_buy_back_em", None)
        if snap_func is not None:
            try:
                snap = self._request(snap_func, _source="eastmoney")
                hit = snap[snap["代码"].astype(str) == code] if "代码" in snap.columns else snap.iloc[0:0]
                if not hit.empty:
                    row = hit.iloc[[0]].copy()
                    row["date"] = pd.Timestamp(_date.today())
                    df = self._standardize(row, interface="bond_buy_back_snapshot",
                                           market="cn_reverse_repo", symbol=code)
                    if not df.empty:
                        df.attrs["snapshot_only"] = True
                        df.attrs["source_fallback"] = True
                        self.logger.warning("[cn_reverse_repo] %s 仅取到当日快照（无历史），"
                                            "已标 snapshot_only=True", code)
                        return df.loc[start:end]
                errors.append(f"{snap_func.__name__} 未找到 {code}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{snap_func.__name__}: {exc}")
        raise RuntimeError(f"[cn_reverse_repo] {code} 日线获取失败（已尝试历史接口+快照备用源）: "
                           f"{'; '.join(errors)}")

    # ==================== 分钟线路由 ====================

    def _slice_minute(self, df: pd.DataFrame, start: str, end: str,
                      market: str, symbol: str) -> pd.DataFrame:
        """按 [start, end] 裁剪分钟线（end 补到当天 23:59:59），并标注历史是否被源上限截断。"""
        out = df.loc[pd.Timestamp(start): pd.Timestamp(end) + pd.Timedelta(days=1)].copy()
        out.attrs.update(df.attrs)
        if out.empty:
            return out
        if pd.Timestamp(start) < out.index.min() - pd.Timedelta(days=3):
            out.attrs["minute_history_capped"] = True
            out.attrs["minute_available_from"] = out.index.min().strftime("%Y-%m-%d %H:%M")
            self.logger.warning("[%s] %s 分钟线受数据源上限限制：请求起点 %s，实际起点 %s（接口无时间游标，无法分页）",
                                market, symbol, start, out.index.min())
        return out

    def _fetch_cn_minute(self, market, symbol, period, start, end) -> pd.DataFrame:
        """A股/ETF 分钟线：按 config.MINUTE_SOURCE_PRIORITY 依次尝试各数据源。

        cn_stock 默认 BaoStock（5/15/30/60 分钟、1990 年起、不复权、volume=股），
        失败回退新浪（单次最多 1970 根、无时间游标），再回退东财（仅约 1 个月）；
        cn_etf 走新浪 → 东财。BaoStock 不含指数，指数代码直接走新浪。
        """
        if market == "cn_etf":
            order = ["sina", "eastmoney"]
        else:
            order = list(config.MINUTE_SOURCE_PRIORITY.get(market, ["sina", "eastmoney"]))

        # 场景分工：BaoStock 只有盘后数据、无实时行情 → 请求区间含今天时改走新浪/东财
        today = _date.today()
        session_today = market == "cn_stock" and pd.Timestamp(end).date() >= today
        if session_today:
            skipped = [s for s in order if s == "baostock"]
            order = [s for s in order if s != "baostock"] or ["sina", "eastmoney"]
            if skipped:
                self.logger.info("[cn_stock] %s 请求区间含当日（end=%s），跳过 BaoStock（仅盘后数据），"
                                 "改走 %s", symbol, end, "/".join(order))

        errors = []
        for source in order:
            try:
                if source == "baostock":
                    return self._fetch_cn_stock_minute_baostock(symbol, period, start, end)
                if source == "sina":
                    out = self._fetch_cn_minute_sina(market, symbol, period, start, end)
                elif source == "eastmoney":
                    out = self._fetch_cn_minute_em(market, symbol, period, start, end)
                else:
                    continue
                if not out.empty:
                    if session_today and is_trading_day(today, market) and \
                            out.index.max().date() < today and datetime.now().hour >= 9:
                        self.logger.warning("[cn_stock] %s 当日（%s）请求未取到今日分钟线（最新 %s）："
                                            "可能尚未开盘或数据源未更新", symbol, today, out.index.max())
                    return out
                raise RuntimeError("返回空数据")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{source}: {exc}")
                self.logger.warning("[%s] %s 分钟线源 %s 失败(%s)，尝试下一个源",
                                    market, symbol, source, exc)
        raise RuntimeError(f"[{market}] {symbol} 分钟线全部数据源失败: {'; '.join(errors)}")

    def _fetch_cn_minute_sina(self, market, symbol, period, start, end) -> pd.DataFrame:
        """新浪分钟线（不复权；A股/ETF 单次最多 1970 根，无时间游标）。"""
        digits = re.sub(r"\D", "", str(symbol))
        # 沪市指数（000016/000300/000905…）必须走 sh 前缀；000001 既是上证指数也是平安银行，
        # 不放入指数清单，仍按个股 sz 处理
        if digits in _CN_INDEX_CODES and digits.startswith("000"):
            prefix = "sh"
        else:
            prefix = "sh" if digits.startswith(("5", "6", "9")) else \
                ("bj" if digits.startswith(("4", "8")) else "sz")
        raw = self._request(ak.stock_zh_a_minute, symbol=f"{prefix}{digits}",
                            period=str(period), adjust="", _source="sina")
        df = self._standardize(raw, interface="stock_zh_a_minute",
                               market=market, symbol=symbol)
        out = self._slice_minute(df, start, end, market, symbol)
        out.attrs["adjust"] = "none"  # 分钟线只提供不复权价
        if prefix == "sh" and digits in _CN_INDEX_CODES:
            # 指数分钟线的 volume/amount 口径与个股不同（实测 amount/(close×volume)≈0.0053）
            out.attrs["unit_uncertain"] = True
            out.attrs["unit_evidence"] = "指数分钟线 volume/amount 源单位未实测，原值透传"
        return out

    def _fetch_cn_minute_em(self, market, symbol, period, start, end) -> pd.DataFrame:
        """东财分钟线（成交量=手→×100；无论起始日期仅返回约 1 个月）。"""
        func = ak.stock_zh_a_hist_min_em if market == "cn_stock" else ak.fund_etf_hist_min_em
        interface = "stock_zh_a_hist_min_em" if market == "cn_stock" else "fund_etf_hist_min_em"
        raw = self._request(func, symbol=symbol, period=str(period),
                            start_date=f"{start} 09:30:00", end_date=f"{end} 15:00:00",
                            adjust="", _source="eastmoney")
        df = self._standardize(raw, interface=interface, market=market, symbol=symbol)
        out = self._slice_minute(df, start, end, market, symbol)
        out.attrs["adjust"] = "none"
        return out

    # ==================== BaoStock（A股分钟线长历史） ====================

    def _bs_login(self):
        """模块级单例登录；失败/异常时重置状态，下次调用重新登录。"""
        if bs is None:
            raise RuntimeError("未安装 baostock，请 pip install baostock")
        if _BS_STATE["logged_in"]:
            return bs
        with contextlib.redirect_stdout(io.StringIO()):  # baostock 会直接 print("login success!")
            result = bs.login()
        if getattr(result, "error_code", "1") != "0":
            _BS_STATE["logged_in"] = False
            raise RuntimeError(f"BaoStock 登录失败: {getattr(result, 'error_msg', 'unknown')}")
        _BS_STATE["logged_in"] = True
        self.logger.info("BaoStock 登录成功（模块级单例会复用）")
        return bs

    def _bs_reset(self) -> None:
        _BS_STATE["logged_in"] = False
        if bs is not None:
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    bs.logout()
            except Exception:  # noqa: BLE001
                pass

    def _bs_check(self, rs, what: str) -> None:
        """校验 BaoStock 返回码；会话类错误抛 _BsSessionExpired 以触发重登。"""
        code = str(getattr(rs, "error_code", "0"))
        if code == "0":
            return
        msg = str(getattr(rs, "error_msg", ""))
        if code in _BS_SESSION_CODES or any(h in msg.lower() for h in _BS_SESSION_HINTS):
            raise _BsSessionExpired(f"{what} 会话失效({code}): {msg}")
        raise RuntimeError(f"{what} 查询失败({code}): {msg}")

    def _bs_execute(self, build, what: str):
        """执行 BaoStock 查询；会话过期/未登录时重置会话、重登一次后重试。

        模块级单例登录在长时间运行或盘中可能被服务端断开，这里做一次
        「检测 → logout → login → 重试」的兜底，仍失败才向上抛错。
        """
        if bs is None:
            raise RuntimeError("未安装 baostock，请 pip install baostock")
        last = None
        for attempt in (1, 2):
            client = self._bs_login()
            try:
                rs = build(client)
                self._bs_check(rs, what)
                return rs
            except _BsSessionExpired as exc:
                last = exc
                self._bs_reset()
                self.logger.warning("%s（第 %d 次），已重置会话准备重登后重试", exc, attempt)
        raise RuntimeError(f"{what}：重登后仍失败（{last}）")

    def _bs_code(self, symbol: str) -> str:
        """600519 → sh.600519；000001 → sz.000001。"""
        digits = re.sub(r"\D", "", str(symbol))
        if digits.startswith(("5", "6", "9")):
            return f"sh.{digits}"
        return f"sz.{digits}"

    def _fetch_cn_stock_minute_baostock(self, symbol, period, start, end) -> pd.DataFrame:
        """BaoStock A股分钟线：5/15/30/60 分钟，1990 年起，adjustflag=3（不复权）。

        复权因子由 query_adjust_factor() 单独落盘（与 raw+因子分离架构一致），
        分钟价始终保存不复权原值，绝不在增量库里缓存已复权价。
        """
        if bs is None:
            raise RuntimeError("未安装 baostock")
        if str(period) not in {"5", "15", "30", "60"}:
            raise RuntimeError(f"BaoStock 不支持 {period} 分钟线（仅 5/15/30/60）")
        digits = re.sub(r"\D", "", str(symbol))
        if digits in _CN_INDEX_CODES:
            raise RuntimeError("BaoStock 分钟线不含指数，改走新浪")
        code = self._bs_code(symbol)
        fields = "date,time,open,high,low,close,volume,amount"

        def _query():
            rs = self._bs_execute(
                lambda client: client.query_history_k_data_plus(
                    code, fields, start_date=pd.Timestamp(start).strftime("%Y-%m-%d"),
                    end_date=pd.Timestamp(end).strftime("%Y-%m-%d"),
                    frequency=str(period), adjustflag="3"),
                "BaoStock 分钟线")
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            # 空结果 = 该区间确无数据（停牌/非交易日/代码不支持），属正常结果，
            # 不能抛异常触发 _request 的指数退避重试（否则每个缺口日白等 10 秒）
            return pd.DataFrame(rows, columns=rs.fields)

        raw = self._request(_query, _source="baostock")
        raw = raw.copy()
        if raw.empty:
            self.logger.info("[cn_stock] %s %s 分钟线 %s~%s 无数据（停牌/非交易日），返回空表",
                             symbol, period, start, end)
            out = self._empty_frame()
            out.attrs["source"] = "baostock_minute"
            out.attrs["adjust"] = "none"
            return out
        # time = yyyyMMddHHmmssSSS → datetime；date 列会被 _standardize 识别为索引
        raw["date"] = pd.to_datetime(raw["time"].astype(str).str.slice(0, 14),
                                     format="%Y%m%d%H%M%S", errors="coerce")
        raw = raw.drop(columns=[c for c in ("time", "code") if c in raw.columns])
        df = self._standardize(raw, interface="baostock_minute",
                               market="cn_stock", symbol=symbol)
        out = self._slice_minute(df, start, end, "cn_stock", symbol)
        out.attrs["adjust"] = "none"
        out.attrs["adjust_flag"] = "3"  # BaoStock adjustflag 3 = 不复权

        # 复权因子单独取（失败不影响原始价，只在 attrs 标注具体原因）
        try:
            factors = self._fetch_baostock_adjust_factor(symbol)
            out.attrs["minute_factor_available"] = True
            out.attrs["minute_factor_source"] = "baostock.query_adjust_factor"
            out.attrs["minute_factor_rows"] = int(len(factors))
        except Exception as exc:  # noqa: BLE001 - 必须保留具体原因，不能只说"不支持复权"
            out.attrs["minute_factor_available"] = False
            out.attrs["minute_factor_error"] = str(exc)
            self.logger.warning("[cn_stock] %s BaoStock 复权因子获取失败（原因：%s），"
                                "本次返回不复权价（adjust=none），不缓存已复权价", symbol, exc)
        return out

    def _fetch_baostock_adjust_factor(self, symbol: str) -> pd.DataFrame:
        """BaoStock 复权因子（A股日线与分钟线共用，唯一因子源）。

        实测字段（2026-10-28，sh.600519）：['code', 'dividOperateDate',
        'foreAdjustFactor', 'backAdjustFactor', 'adjustFactor']；
        列：qfq_factor（foreAdjustFactor）/ hfq_factor（backAdjustFactor），索引为除权日。
        一律取全历史（1990 起），保证长历史前段不会因覆盖不足被 bfill 成错误常数。
        """
        if bs is None:
            raise RuntimeError("未安装 baostock，无法取 A股复权因子")
        path = self.cache_dir / "adj_factors" / \
            f"cn_stock_{self._sanitize(symbol)}_bs_factors.csv"
        if path.exists() and not self._cache_expired(path, "daily"):
            cached = self._read_cache(path)
            if cached is not None and not cached.empty:
                return cached

        def _query():
            rs = self._bs_execute(
                lambda client: client.query_adjust_factor(
                    code=self._bs_code(symbol), start_date="1990-01-01",
                    end_date=_date.today().strftime("%Y-%m-%d")),
                "BaoStock 复权因子")
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            return pd.DataFrame(rows, columns=rs.fields)

        raw = self._request(_query, _source="baostock")
        if raw.empty:
            raise RuntimeError(f"BaoStock 复权因子为空（{symbol}，可能无分红或代码不支持）")
        required = {"dividOperateDate", "foreAdjustFactor", "backAdjustFactor"}
        missing = required - set(raw.columns)
        if missing:
            # 字段名写错绝不能退化成「数据源不支持复权」的温和告警，必须显式报错
            raise RuntimeError(
                f"BaoStock 复权因子字段名不匹配：缺少 {sorted(missing)}，实际 fields={list(raw.columns)}")
        factors = pd.DataFrame({
            "date": pd.to_datetime(raw["dividOperateDate"], errors="coerce"),
            "qfq_factor": pd.to_numeric(raw["foreAdjustFactor"], errors="coerce"),
            "hfq_factor": pd.to_numeric(raw["backAdjustFactor"], errors="coerce"),
        })
        factors = factors.dropna(subset=["date", "qfq_factor", "hfq_factor"])
        if factors.empty:
            raise RuntimeError(f"BaoStock 复权因子解析后为空（{symbol}），字段值可能非数值")
        factors = factors.set_index("date").sort_index()
        factors["factor_source"] = "baostock"
        self._save_cache(factors, path)
        return factors

    def _hk_minute_day_gate(self, out: pd.DataFrame, period: str) -> pd.DataFrame:
        """港股分钟线日 bar 数完整性闸（评审 2026-11-26 裁定，链路转正前置）。

        逐交易日校验：
          ① 标签合法性——60min 合法标签集 = {10:30, 11:30, 13:30, 14:30,
             15:30, 16:00}（东财滚动口径实测，全日市必须 6 根）；其他周期
             降级为时段窗口校验（bar 结束时刻 ∈ (9:30,12:00]∪(13:00,16:00]）；
          ② 每日 bar 数 ≥2（半日市下限，评审口径）；
          ③ 末端日 bar 数 < 全日标准根数 = 盘中未走完（is_complete 语义）剔除。
        违规日自动剔除，日期列表写入 attrs["dropped_trading_days"] 持久化披露
        （versioning 边车白名单），禁止静默喂入截断数据。
        """
        if out is None or out.empty:
            return out
        mins = int(period)
        if mins == 60:
            valid_labels = {1030, 1130, 1330, 1430, 1530, 1600}
            full_n = 6
        else:
            valid_labels = None          # 未实测周期：降级为时段窗口校验
            full_n = max(1, 270 // mins)  # 270 分钟交易时长理论根数
        hm = out.index.hour * 100 + out.index.minute
        if valid_labels is not None:
            bad_label = ~hm.isin(valid_labels)
        else:
            in_window = ((hm > 930) & (hm <= 1200)) | ((hm > 1300) & (hm <= 1600))
            bad_label = ~in_window
        day = out.index.normalize()
        drop_days = {d for d, bad in zip(day, bad_label) if bad}
        counts = pd.Series(1, index=out.index).groupby(day).sum()
        drop_days |= set(counts[counts < 2].index)          # 半日市下限 ≥2
        last_day = day.max()
        # 末端未走完（is_complete）仅判定「今天」：盘中拉取当日 bar 必然不足
        # 全日根数；历史末端日 bar 数 <full_n 按半日市口径保留（截断由标签
        # 合法性校验拦截——误剔历史日会把合成/短窗样本唯一交易日清空，
        # 触发应交易日净空闸 raise，2026-11-26 预检合成帧实测）
        if last_day == pd.Timestamp.now().normalize() \
                and int(counts.loc[last_day]) < full_n:
            drop_days.add(last_day)
        if not drop_days:
            return out
        dropped = [str(d.date()) for d in sorted(drop_days)]
        out = out[~day.isin(drop_days)].copy()
        out.attrs["dropped_trading_days"] = dropped
        self.logger.warning(
            "[hk_stock] 分钟线日完整性闸剔除 %d 个交易日（截断标签/bar 数不足/"
            "未走完）：%s（已写入 attrs.dropped_trading_days 持久化披露）",
            len(dropped), "、".join(dropped))
        return out

    def _fetch_minute(self, market, symbol, period, start, end) -> pd.DataFrame:
        """分钟线取数入口：可路由市场交给 DataRouter，其余保持原报错文案。"""
        if market in _SUPPORTED_MINUTE_MARKETS:
            router = self._build_source_router()
            if router is not None:
                return router.fetch("minute", symbol, market, start, end, period=str(period))
        return self._dispatch_minute(market, symbol, period, start, end)

    def _dispatch_minute(self, market, symbol, period, start, end) -> pd.DataFrame:
        if market in ("cn_stock", "cn_etf"):
            return self._fetch_cn_minute(market, symbol, period, start, end)
        if market == "cn_index":
            return self._fetch_cn_index_minute(symbol, period, start, end)
        if market in ("us_stock", "us_etf"):
            code = self._resolve_us_symbol(symbol) or f"105.{symbol.upper()}"
            raw = self._request(ak.stock_us_hist_min_em, symbol=code, period=period,
                                start_date=f"{start} 09:30:00", end_date=f"{end} 16:00:00",
                                adjust="", _source="eastmoney")
            df = self._standardize(raw, interface="stock_us_hist_min_em",
                                   market=market, symbol=symbol)
            out = self._slice_minute(df, start, end, market, symbol)
            out.attrs["adjust"] = "none"
            return out
        if market == "hk_stock":
            # 东财该接口带 start_date/end_date 参数时返回范围反而错误
            # （2026-11-26 预检实测：无参数=134 bar 全量近 1 月历史，
            # 带 1 年区间参数=仅 2~8 根），必须无参拉全量后本地裁剪
            raw = self._request(ak.stock_hk_hist_min_em, symbol=str(symbol).zfill(5),
                                period=period, adjust="", _source="eastmoney")
            df = self._standardize(raw, interface="stock_hk_hist_min_em",
                                   market=market, symbol=symbol)
            out = self._slice_minute(df, start, end, market, symbol)
            out.attrs["adjust"] = "none"
            # 历史深度缺口显式标注（禁静默留洞）：东财 stock_hk_hist_min_em
            # 实测仅保留约 1 个月分钟历史（2026-11-26 探测：60min=134 bar），
            # 请求起点早于实际返回起点时必须声明覆盖范围，禁止让下游误以为
            # 请求区间已完整覆盖
            if not out.empty and out.index.min() > pd.Timestamp(start):
                avail = out.index.min().strftime("%Y-%m-%d %H:%M")
                out.attrs["minute_history_capped"] = True
                out.attrs["minute_available_from"] = avail
                self.logger.warning(
                    "[hk_stock] %s %s 分钟历史深度受限：请求起点 %s，实际可用起点 %s"
                    "（东财接口仅保留约 1 个月分钟历史，缺口已标注 minute_history_capped）",
                    symbol, period, start, avail)
            # 日 bar 数完整性闸（评审 2026-11-26 裁定：链路转正前置强制闸）
            out = self._hk_minute_day_gate(out, str(period))
            return out
        if market == "cn_convertible":
            # akshare bond_zh_hs_cov_min 实走东财 K 线：成交量=手（1 手=10 张，实测比值 10.0）
            raw = self._request(ak.bond_zh_hs_cov_min, symbol=self._cb_symbol(symbol),
                                period=period, adjust="", start_date=start, end_date=end,
                                _source="eastmoney")
            df = self._standardize(raw, interface="bond_zh_hs_cov_min",
                                   market=market, symbol=symbol)
            out = self._slice_minute(df, start, end, market, symbol)
            out.attrs["adjust"] = "none"
            return out
        if market == "cn_future":
            # 新浪期货分钟：成交量=手；单次上限 1023 根，接口无时间游标 → 无法分页
            raw = self._request(ak.futures_zh_minute_sina,
                                symbol=self._futures_continuous(symbol), period=period,
                                _source="sina_futures")
            df = self._standardize(raw, interface="futures_zh_minute_sina",
                                   market=market, symbol=symbol)
            out = self._slice_minute(df, start, end, market, symbol)
            out.attrs["adjust"] = "none"
            if len(df) >= 1023:
                out.attrs["minute_history_capped"] = True
                self.logger.warning("[cn_future] %s 新浪期货分钟线单次上限 1023 根且无时间游标，无法分页",
                                    symbol)
            return out
        if market == "forex":
            return self._fetch_forex_minute(symbol, period, start, end)
        if market == "global_future":
            raise RuntimeError("国际期货暂不提供分钟线")
        if market == "crypto":
            return self._fetch_crypto_minute(symbol, period, start, end)
        if market == "cn_option":
            raise RuntimeError("期权暂不提供分钟线")
        if market == "cn_fund":
            raise RuntimeError("场外基金无分钟线，仅提供日净值")
        if market in _NO_KLINE_MARKETS:
            raise ValueError(f"[{market}] {_NO_KLINE_MARKETS[market]}")
        raise ValueError(f"{market} 暂不支持分钟线")

    def _fetch_crypto_minute(self, symbol, period, start, end) -> pd.DataFrame:
        """币安分钟 K 线（1/5/15/30/60 → 1m/5m/15m/30m/1h，limit=1000 分页）。

        单次回填最多 MAX_PAGES×1000 = 20000 根（约 20 次请求），超过则标 minute_history_capped=True；
        每次请求都经 _throttle 间隔 >=0.3s（config.REQUEST_DELAY），避免触发币安限频封禁。
        """
        interval_map = {"1": "1m", "5": "5m", "15": "15m", "30": "30m", "60": "1h"}
        interval = interval_map.get(str(period))
        if interval is None:
            raise RuntimeError(f"加密货币不支持 {period} 分钟线（仅 1/5/15/30/60）")
        pair = f"{str(symbol).upper().replace('/USDT', '')}USDT"
        start_ms = int(pd.Timestamp(start).timestamp() * 1000)
        end_ms = int((pd.Timestamp(end) + pd.Timedelta(days=1)).timestamp() * 1000)
        max_pages = 20
        frames, last_error = [], None
        for host in ("https://data-api.binance.vision", "https://api.binance.com",
                     "https://api1.binance.com"):
            try:
                frames = []
                cursor = start_ms
                for _ in range(max_pages):
                    text = self._http_get(
                        f"{host}/api/v3/klines",
                        params={"symbol": pair, "interval": interval, "limit": 1000,
                                "startTime": cursor, "endTime": end_ms},
                        source="binance")
                    rows = json.loads(text)
                    if not rows:
                        break
                    frames.append(pd.DataFrame(rows, columns=[
                        "open_time", "open", "high", "low", "close", "volume", "close_time",
                        "amount", "trades", "taker_base", "taker_quote", "ignore"]))
                    if len(rows) < 1000:
                        break
                    cursor = int(rows[-1][6]) + 1
                    if cursor >= end_ms:
                        break
                if frames:
                    df = pd.concat(frames, ignore_index=True)
                    df["date"] = pd.to_datetime(df["open_time"], unit="ms")
                    out = self._standardize(df, interface="binance_klines",
                                            market="crypto", symbol=symbol)
                    out = out.loc[pd.Timestamp(start): pd.Timestamp(end) + pd.Timedelta(days=1)].copy()
                    out.attrs["adjust"] = "none"
                    out.attrs["backfill_cap_bars"] = max_pages * 1000
                    out.attrs["request_interval"] = float(self.request_delay)
                    if len(out) and pd.Timestamp(start) < out.index.min() - pd.Timedelta(days=1):
                        out.attrs["minute_history_capped"] = True
                        self.logger.warning("[crypto] %s %s 分钟线单次回填上限 %d 根，"
                                            "实际起点 %s（请求 %s）", symbol, interval,
                                            max_pages * 1000, out.index.min(), start)
                    return out
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        raise RuntimeError(f"加密货币 {symbol} 分钟线获取失败（需网络可达）: {last_error}")

    def _fetch_forex_minute(self, symbol, period, start, end) -> pd.DataFrame:
        """新浪外汇分钟线（NewForexService.getMinKline）。勿高频调用。

        实测 datalen 参数无效：1023/3000/6000 均只返回约 974 根（≈2 个月 60 分钟），
        接口无时间游标 → 无法分页，历史不足时在 attrs 标注 minute_history_capped。
        """
        if str(period) not in {"5", "15", "30", "60"}:
            raise RuntimeError("新浪外汇分钟线仅支持 5/15/30/60 分钟")
        code = str(symbol).replace("/", "").replace("-", "").lower()
        # 新浪外汇代码前缀是 fx_s（spot）：EURUSD → fx_seurusd（写成 fx_eurusd 会返回 ticktime is null）
        sina_code = f"fx_s{code}"
        # 注意：JSONP 回调名里的 %20 必须原样保留，因此 query 直接拼进 URL，不走 params 编码
        url = (f"https://vip.stock.finance.sina.com.cn/forex/api/jsonp.php/"
               f"var%20_{sina_code}_{period}=/NewForexService.getMinKline"
               f"?symbol={sina_code}&scale={period}&datalen=1023")
        text = self._http_get(url,
                              headers={"Referer": "https://finance.sina.com.cn",
                                       "User-Agent": "Mozilla/5.0"},
                              source="sina_forex")
        lo, hi = text.find("["), text.rfind("]")
        if lo < 0 or hi <= lo:
            raise RuntimeError(f"新浪外汇分钟线返回格式异常: {text[:120]}")
        rows = json.loads(text[lo:hi + 1])
        if not rows:
            return self._empty_frame()
        df = pd.DataFrame(rows).rename(columns={
            "d": "date", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        df["amount"] = 0.0
        out = self._standardize(df, interface="sina_forex_min",
                                market="forex", symbol=symbol)
        out = self._slice_minute(out, start, end, "forex", symbol)
        out.attrs["adjust"] = "none"
        if len(out) < 1023 and pd.Timestamp(start) < out.index.min() - pd.Timedelta(days=3):
            out.attrs["minute_history_capped"] = True
        return out



    # ==================== 实时路由 ====================

    def _sina_symbol(self, market: str, symbol: str) -> Optional[str]:
        """把统一代码转成新浪行情代码：sh600519 / rt_hk00700 / gb_aapl / nf_RB0 / hf_GC / fx_seurusd。"""
        s = str(symbol).strip()
        if market in ("cn_stock", "cn_etf"):
            digits = re.sub(r"\D", "", s)
            if not digits:
                return None
            if digits.startswith(("5", "6", "9")):
                return f"sh{digits}"
            if digits.startswith(("4", "8")):
                return f"bj{digits}"
            return f"sz{digits}"
        if market == "hk_stock":
            digits = re.sub(r"\D", "", s).zfill(5)
            return f"rt_hk{digits}" if digits else None
        if market in ("us_stock", "us_etf"):
            return f"gb_{s.lower()}" if s else None
        if market == "cn_future":
            variety = re.sub(r"\d", "", s).upper()
            return f"nf_{variety}0" if variety else None
        if market == "global_future":
            return f"hf_{s.upper()}" if s else None
        if market == "forex":
            code = s.replace("/", "").upper()
            return f"fx_s{code.lower()}" if code else None
        return None

    def _sina_quote(self, market: str, symbol: str) -> dict:
        """新浪直连单只行情（一次 HTTP，毫秒级返回，避免拉全市场快照）。"""
        code = self._sina_symbol(market, symbol)
        if not code:
            raise RuntimeError(f"{market} 无新浪直连行情")
        text = self._http_get(f"https://hq.sinajs.cn/list={code}",
                              headers={"Referer": "https://finance.sina.com.cn",
                                       "User-Agent": "Mozilla/5.0"},
                              source="sina_hq", encoding="gbk")
        matched = re.search(r'="(.*)"', text)
        fields = matched.group(1).split(",") if matched else []

        def num(idx: int) -> Optional[float]:
            try:
                return float(fields[idx])
            except (IndexError, ValueError):
                return None

        def changed(price: float, base: float) -> Optional[float]:
            return (price / base - 1) * 100 if price and base else None

        if market in ("cn_stock", "cn_etf"):
            if len(fields) < 10 or not fields[0].strip():
                raise RuntimeError(f"新浪行情返回空: {code}")
            price, prev_close = num(3), num(2)
            return {"name": fields[0], "open": num(1), "prev_close": prev_close,
                    "price": price, "high": num(4), "low": num(5),
                    "bid": num(6), "ask": num(7), "volume": num(8), "amount": num(9),
                    "change_pct": changed(price, prev_close)}
        if market == "hk_stock":
            if len(fields) < 13 or not fields[1].strip():
                raise RuntimeError(f"新浪行情返回空: {code}")
            return {"name": fields[1], "open": num(2), "prev_close": num(3),
                    "high": num(4), "low": num(5), "price": num(6),
                    "change_pct": num(8), "bid": num(9), "ask": num(10),
                    "amount": num(11), "volume": num(12)}
        if market in ("us_stock", "us_etf"):
            if len(fields) < 11 or not fields[0].strip():
                raise RuntimeError(f"新浪行情返回空: {code}")
            # name,price,change_pct,datetime,change,open,high,low,...
            price, change = num(1), num(4)
            return {"name": fields[0], "price": price, "change_pct": num(2),
                    "timestamp": fields[3],
                    "prev_close": price - change if price is not None and change is not None else None,
                    "open": num(5), "high": num(6), "low": num(7), "volume": num(10)}
        if market == "cn_future":
            if len(fields) < 15 or not fields[0].strip():
                raise RuntimeError(f"新浪行情返回空: {code}")
            # 0名称 2开 3高 4低 6买 7卖 8最新 10昨结 13成交量 14持仓量
            price, prev_settle = num(8), num(10)
            return {"name": fields[0], "open": num(2), "high": num(3), "low": num(4),
                    "bid": num(6), "ask": num(7), "price": price, "prev_close": prev_settle,
                    "volume": num(13), "open_interest": num(14),
                    "change_pct": changed(price, prev_settle)}
        if market == "global_future":
            if len(fields) < 9 or not num(0):
                raise RuntimeError(f"新浪行情返回空: {code}")
            # 0最新 2买 3卖 4高 5低 6时间 7昨结 8开
            price, prev_settle = num(0), num(7)
            return {"name": fields[13] if len(fields) > 13 else code,
                    "price": price, "bid": num(2), "ask": num(3),
                    "high": num(4), "low": num(5), "timestamp": fields[6],
                    "prev_close": prev_settle, "open": num(8),
                    "change_pct": changed(price, prev_settle)}
        # 外汇：0时间 1买 2卖 3昨收 5开 6高 7低 8最新 9名称 10涨跌幅
        if len(fields) < 11 or not num(8):
            raise RuntimeError(f"新浪行情返回空: {code}")
        return {"name": fields[9], "bid": num(1), "ask": num(2),
                "prev_close": num(3), "open": num(5), "high": num(6), "low": num(7),
                "price": num(8), "change_pct": num(10), "timestamp": fields[0]}

    def _binance_ticker(self, symbol: str) -> dict:
        """币安 24h 行情（多主机回退）。"""
        pair = str(symbol).upper()
        if not pair.endswith("USDT"):
            pair = f"{pair}USDT"
        last_error = None
        for host in ("data-api.binance.vision", "api.binance.com", "api1.binance.com"):
            try:
                text = self._http_get(f"https://{host}/api/v3/ticker/24hr",
                                      params={"symbol": pair}, source="binance")
                data = json.loads(text)
                price = float(data["lastPrice"])
                return {"name": pair, "price": price,
                        "change_pct": float(data["priceChangePercent"]),
                        "volume": float(data["volume"]),
                        "bid": float(data["bidPrice"]), "ask": float(data["askPrice"]),
                        "high": float(data["highPrice"]), "low": float(data["lowPrice"]),
                        "open": float(data["openPrice"])}
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        raise RuntimeError(f"币安行情接口全部失败: {last_error}")

    def _fetch_realtime(self, market: str, symbol: str) -> dict:
        if market == "crypto":
            return self._binance_ticker(symbol)
        if market in ("cn_stock", "cn_etf", "us_stock", "us_etf", "hk_stock",
                      "cn_future", "global_future", "forex"):
            try:
                return self._sina_quote(market, symbol)
            except Exception as exc:  # noqa: BLE001 - 直连失败再回退全量快照
                self.logger.warning("[%s] %s 新浪直连行情失败(%s)，回退全量快照", market, symbol, exc)
        if market == "cn_stock":
            raw = self._request(ak.stock_zh_a_spot_em)
            return self._extract_realtime(raw, symbol, ["代码", "code"], match_suffix=True)
        if market == "cn_etf":
            raw = self._request(ak.fund_etf_spot_em)
            return self._extract_realtime(raw, symbol, ["代码", "code"], match_suffix=True)
        if market in ("us_stock", "us_etf"):
            raw = self._request(ak.stock_us_spot_em)
            return self._extract_realtime(raw, symbol, ["代码", "symbol"], match_suffix=True)
        if market == "hk_stock":
            raw = self._request(ak.stock_hk_spot_em)
            return self._extract_realtime(raw, str(symbol).zfill(5), ["代码", "symbol"], match_suffix=True)
        if market == "cn_convertible":
            func = getattr(ak, "bond_zh_hs_cov_spot", None)
            if func is None:
                raise RuntimeError("当前 akshare 版本无可转债实时接口")
            return self._extract_realtime(self._request(func), symbol, ["symbol", "代码"])
        if market == "cn_future":
            func = getattr(ak, "futures_zh_realtime", None)
            if func is None:
                raise RuntimeError("当前 akshare 版本无期货实时接口")
            raw = self._request(func, symbol=self._futures_continuous(symbol))
            return self._extract_realtime(raw, symbol, ["symbol", "代码"])
        if market == "global_future":
            raw = self._request(ak.futures_foreign_commodity_realtime, symbol=[str(symbol).upper()])
            return self._extract_realtime(raw, symbol, ["代码", "symbol"], match_suffix=True)
        if market == "forex":
            code = str(symbol).replace("/", "").upper()
            return self._extract_realtime(self._request(ak.forex_spot_em), code, ["代码", "名称"],
                                          match_suffix=True)
        if market == "crypto":
            raw = self._request(ak.crypto_js_spot)
            base = str(symbol).split("/")[0].upper()
            return self._extract_realtime(raw, base, ["代码", "symbol"], match_suffix=True)
        if market == "cn_fund":
            nav = self._fetch_cn_fund_nav(symbol, "20000101", "21001231", "hfq")
            price = float(nav["close"].iloc[-1]) if not nav.empty else None
            return {"name": str(symbol), "price": price, "timestamp": "净值（T+1 披露）"}
        if market == "cn_reverse_repo":
            raw = self._request(ak.bond_sh_buy_back_em)
            return self._extract_realtime(raw, symbol, ["代码", "symbol"])
        if market == "cn_option":
            func = getattr(ak, "option_current_em", None)
            if func is None:
                raise RuntimeError("当前 akshare 版本无期权实时接口")
            return self._extract_realtime(self._request(func), symbol, ["代码", "合约代码"])
        raise ValueError(f"{market} 暂不支持实时行情")

    # ==================== 期货 / 期权 / 基金 专用 ====================

    def get_dominant_contract(self, variety: str) -> str:
        """获取当前主力合约代码（如 RB0 / rb2501），失败时返回连续合约代码。"""
        variety = re.sub(r"\d", "", str(variety)).upper()
        try:
            raw = self._request(ak.futures_display_main_sina)
            cols = {str(c): c for c in raw.columns}
            code_col = next((c for k, c in cols.items() if "合约" in k or k.lower() == "symbol"), None)
            if code_col is None:
                return f"{variety}0"
            hit = raw[raw[code_col].astype(str).str.upper().str.contains(variety, na=False)]
            if not hit.empty:
                return str(hit.iloc[0][code_col])
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("获取 %s 主力合约失败: %s", variety, exc)
        return f"{variety}0"

    def get_option_chain(self, underlying: str = "510050", end_month: str = None) -> pd.DataFrame:
        """获取同标的、同到期日的全部行权价合约（ETF 期权）。

        akshare 的 option_finance_board 返回的合约交易代码形如
        510050C2610M02800（标的 + C/P + 到期年月 + 行权价），据此解析类型/到期日/行权价。
        """
        full_name = _OPTION_UNDERLYING_MAP.get(str(underlying), underlying)
        short_name = _OPTION_SYMBOL_SHORT.get(str(underlying), str(underlying))
        months = []
        if end_month:
            months = [end_month]
        else:
            try:
                months = list(self._request(ak.option_sse_list_sina, symbol=short_name, exchange="null"))
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("获取 %s 期权月份失败: %s", underlying, exc)

        frames = []
        for month in months:
            end_m = str(month)[-4:]
            try:
                raw = self._request(ak.option_finance_board, symbol=full_name, end_month=end_m)
                if raw is not None and not raw.empty:
                    frames.append(raw)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("期权链 %s %s 获取失败: %s", underlying, end_m, exc)

        columns = ["code", "name", "strike", "expiry_date", "option_type",
                   "contract_multiplier", "close", "volume"]
        if not frames:
            return pd.DataFrame(columns=columns)

        raw = pd.concat(frames, ignore_index=True)
        code_col = next((c for c in raw.columns if "合约交易代码" in str(c) or "合约编码" in str(c)),
                        raw.columns[0])
        price_col = next((c for c in raw.columns if "当前价" in str(c) or "收盘价" in str(c)), None)
        records = []
        for _, row in raw.iterrows():
            code = str(row[code_col]).strip().upper()
            match = re.match(r"^(\d{6})([CP])(\d{4})M(\d+)$", code)
            if not match:
                continue
            _, cp, yymm, strike_raw = match.groups()
            year, month = 2000 + int(yymm[:2]), int(yymm[2:])
            expiry = self._option_expiry(year, month)
            records.append({
                "code": code,
                "name": code,
                "strike": int(strike_raw) / 10000.0,
                "expiry_date": expiry,
                "option_type": "call" if cp == "C" else "put",
                "contract_multiplier": config.OPTION["contract_multiplier"],
                "close": pd.to_numeric(row.get(price_col), errors="coerce") if price_col else None,
                "volume": 0.0,
            })
        return pd.DataFrame(records, columns=columns)

    @staticmethod
    def _option_expiry(year: int, month: int) -> pd.Timestamp:
        """期权到期日：到期月份第四个星期三。"""
        first = pd.Timestamp(year=year, month=month, day=1)
        offset = (2 - first.dayofweek) % 7  # 周三 = 2
        return first + pd.Timedelta(days=offset + 21)

    @staticmethod
    def calc_greeks(S: float, K: float, T: float, r: float, sigma: float,
                    option_type: str = "call") -> dict:
        """Black-Scholes 计算 Delta/Gamma/Theta/Vega/Rho。"""
        from scipy.stats import norm

        option_type = (option_type or "call").lower()
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        pdf = norm.pdf(d1)
        if option_type == "call":
            delta = norm.cdf(d1)
            theta = (-S * pdf * sigma / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * norm.cdf(d2)) / 365
            rho = K * T * math.exp(-r * T) * norm.cdf(d2) / 100
        else:
            delta = norm.cdf(d1) - 1
            theta = (-S * pdf * sigma / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * norm.cdf(-d2)) / 365
            rho = -K * T * math.exp(-r * T) * norm.cdf(-d2) / 100
        return {
            "delta": delta,
            "gamma": pdf / (S * sigma * math.sqrt(T)),
            "theta": theta,
            "vega": S * pdf * math.sqrt(T) / 100,
            "rho": rho,
        }

    @staticmethod
    def calc_implied_volatility(S: float, K: float, T: float, r: float,
                                option_price: float, option_type: str = "call") -> float:
        """二分法计算隐含波动率。"""
        if S <= 0 or K <= 0 or T <= 0 or option_price <= 0:
            raise ValueError("参数非法：S/K/T/option_price 必须为正")
        intrinsic = max(0.0, S - K) if option_type.lower() == "call" else max(0.0, K - S)
        if option_price < intrinsic:
            raise ValueError(f"期权价格 {option_price} 低于内在价值 {intrinsic:.4f}")

        low, high = 1e-6, 5.0
        for _ in range(200):
            mid = (low + high) / 2
            price = DataFetcher._bs_price(S, K, T, r, mid, option_type)
            if abs(price - option_price) < 1e-8:
                return mid
            if price > option_price:
                high = mid
            else:
                low = mid
        return (low + high) / 2

    @staticmethod
    def _bs_price(S, K, T, r, sigma, option_type="call") -> float:
        from scipy.stats import norm

        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        if (option_type or "call").lower() == "call":
            return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
        return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

    def calc_holding_period_redemption_fee(self, hold_days: int) -> float:
        """按持有天数返回场外公募基金赎回费率。"""
        for days, rate in config.PUBLIC_FUND["redeem_fee_by_days"]:
            if hold_days < days:
                return rate
        return 0.0

    def get_hk_lot_size(self, symbol: str):
        """港股每手股数：治理面标的属性优先（HKEX 官方实测登记）。

        未登记标的返回 None（unknown）——由下单层按 HK_STOCK_CONFORMANCE.
        unknown_lot_action 处置（当前=reject）；禁止按 100 凭记忆回退
        （02800=500 官方实测证明标的差异真实存在）。
        """
        code = str(symbol).zfill(5)
        if code in self._hk_lot_cache:
            return self._hk_lot_cache[code]
        conf = getattr(config, "HK_STOCK_CONFORMANCE", {}) or {}
        registered = conf.get("lot_sizes") or {}
        lot = None
        if code in registered:
            lot = int(registered[code])
        else:
            func = getattr(ak, "stock_hk_lot_size", None)
            if func is not None:
                try:
                    raw = self._request(func, symbol=code)
                    if isinstance(raw, pd.DataFrame) and not raw.empty:
                        for col in raw.columns:
                            if "每手" in str(col):
                                lot = int(pd.to_numeric(
                                    raw.iloc[0][col], errors="coerce") or 0) or None
                                break
                except Exception as exc:  # noqa: BLE001
                    self.logger.debug("查询港股每手失败 %s: %s", code, exc)
        self._hk_lot_cache[code] = lot
        return lot

    def get_price_tick(self, symbol: str, price: float = None, market: str = None) -> float:
        """按市场/价格区间返回最小变动价位。"""
        market = market or config.detect_market_type(symbol)
        if market == "hk_stock":
            price = float(price or 0)
            # 港股价位分表（v3.54 港股接入）：按 HKEX Spread Table 官方分类
            # （spread_parts：700=Part A 正股表、02800=Part D ETF 分表——
            # [20,100) 实测 0.02 vs 正股 0.05）；Part D 仅登记实测覆盖带，
            # 带外 raise 禁止臆测
            conf = getattr(config, "HK_STOCK_CONFORMANCE", {}) or {}
            parts = {str(k).zfill(5): str(v) for k, v in
                     (conf.get("spread_parts") or {}).items()}
            part = parts.get(str(symbol).zfill(5),
                             str(conf.get("unknown_spread_part_action") or "part_a"))
            if part == "part_d":
                part_d = ((conf.get("spread_tables") or {}).get("part_d_measured") or {})
                for lo, hi, tick in part_d.get("bands") or []:
                    if lo <= price < hi:
                        return float(tick)
                action = str(part_d.get("unmeasured_action") or "raise")
                if action == "raise":
                    raise ValueError(
                        f"{symbol} 价格 {price} 不在 Part D 实测覆盖带内"
                        f"（{part_d.get('bands')}）：价位未实测，禁止臆测"
                        "（unmeasured_action=raise）")
                return 0.05
            for upper, tick in _HK_TICK_MAP:            # Part A 正股表
                if price < upper:
                    return tick
            return 5.0
        if market in ("cn_stock",):
            return float(config.get_market_config(market)["price_step"])
        if market == "cn_etf":
            return float(config.get_market_config(market)["price_step"])
        if market == "cn_future":
            variety = re.sub(r"\d", "", str(symbol)).upper()
            return float(config.CN_FUTURES_VARIETY.get(variety, {}).get("tick", 1))
        if market == "global_future":
            return float(config.GLOBAL_FUTURES.get(str(symbol).upper(), {}).get("tick", 0.01))
        if market == "crypto":
            return float(config.CRYPTO["assets"].get(str(symbol).upper(), {}).get("tick", 0.01))
        if market == "forex":
            pair = config.FOREX["ccy_pairs"].get(str(symbol).replace("/", "").upper(), {})
            return 10 ** (-pair.get("pip_pos", 4))
        return float(config.get_market_config(market).get("price_step", 0.01))

    def is_stamp_duty_exempt(self, symbol: str, market: str = None) -> bool:
        """印花税豁免：cn/us 品种类豁免；港股按 HKEX 官方 Stamp Duty 列
        （治理面 stamp_duty_exempt：02800 ETF 豁免、00700 正股应税——
        旧版对 hk_stock 全市场一刀切豁免与官方口径矛盾，v3.54 修正）。"""
        market = market or config.detect_market_type(symbol)
        if market in ("cn_etf", "us_stock", "us_etf", "cn_fund"):
            return True
        if market == "hk_stock":
            conf = getattr(config, "HK_STOCK_CONFORMANCE", {}) or {}
            return str(symbol).zfill(5) in {str(x).zfill(5) for x in
                                            (conf.get("stamp_duty_exempt") or [])}
        return False

    # ==================== 数据质量 ====================

    def _quality_check(self, df: pd.DataFrame, market: str, symbol: str) -> pd.DataFrame:
        if df is None or df.empty:
            return self._empty_frame()
        out = df.copy()
        for col in _PRICE_COLUMNS + ["volume", "amount"]:
            if col not in out.columns:
                out[col] = 0.0
            out[col] = pd.to_numeric(out[col], errors="coerce")

        # 1) 高低价异常
        bad = (out["high"] < out["low"]) | (out["high"] < out[["open", "close"]].max(axis=1)) \
            | (out["low"] > out[["open", "close"]].min(axis=1))
        if bad.any():
            self.logger.warning("[%s] %s 删除 %d 行高低价异常数据", market, symbol, int(bad.sum()))
            out = out[~bad]

        # 2) OHLC 缺失：连续 >=3 行缺失丢弃，其余**保留缺失值**并打 is_missing 标记。
        #    禁止在此 ffill：指标/回测必须使用未填充的原始序列，前值填充只在 fill_missing()（图表）里做。
        missing = out[_PRICE_COLUMNS].isna().any(axis=1)
        out["is_missing"] = missing
        if missing.any():
            run_id = (~missing).cumsum()
            run_len = missing.groupby(run_id).transform("sum")
            drop = missing & (run_len >= 3)
            if drop.any():
                self.logger.warning("[%s] %s 丢弃 %d 行连续缺失数据", market, symbol, int(drop.sum()))
                out = out[~drop]
                out["is_missing"] = out[_PRICE_COLUMNS].isna().any(axis=1)

        # 3) 价格为 0 / 负数
        invalid = (out[_PRICE_COLUMNS] <= 0).any(axis=1)
        if invalid.any():
            self.logger.warning("[%s] %s 删除 %d 行非正价格数据", market, symbol, int(invalid.sum()))
            out = out[~invalid]

        # 4) 停牌标记（成交量为 0 但保留）
        out["is_suspended"] = out["volume"].fillna(0) <= 0

        # 5) 涨跌停检查（只告警，不删除）
        self._check_price_limit(out, market, symbol)

        # 6) 去重 + 排序
        out = out[~out.index.duplicated(keep="last")].sort_index()
        out.index.name = "date"
        cols = STANDARD_COLUMNS[1:]
        for extra in ("is_suspended", "is_missing"):
            if extra in out.columns:
                cols = cols + [extra]
        # 出口物化列随帧保留（v3.54 港股自建双价：raw_* 列 + adj_factor 列；
        # 数据本体口径列禁止在质量检查中蒸发，attrs 只存标注、列才是数据）
        extra_cols = [c for c in out.columns if c not in cols]
        res = out[cols + extra_cols]
        res.attrs.update(df.attrs)  # 保留 source / unit_ratio 等溯源信息
        return res

    def _check_price_limit(self, df: pd.DataFrame, market: str, symbol: str) -> None:
        try:
            cfg = config.get_market_config(market)
        except KeyError:
            return
        limit_cfg = cfg.get("price_limit")
        if not limit_cfg:
            return
        if not isinstance(limit_cfg, dict):
            limit = float(limit_cfg)
            pct = df["close"].pct_change()
            exceed = pct.abs() > limit + 0.01
            if exceed.any():
                self.logger.warning("[%s] %s 有 %d 行涨跌幅超过 %.0f%%（仅告警）",
                                    market, symbol, int(exceed.sum()), limit * 100)
            return
        if market == "cn_stock":
            code = str(symbol)
            if code.startswith(("300", "301", "688")):
                limit = limit_cfg.get("cyb", limit_cfg.get("kcb", 0.2))
            elif code.startswith(("8", "4")):
                limit = limit_cfg.get("bj", 0.3)
            else:
                limit = limit_cfg.get("main", 0.1)
        else:
            limit = limit_cfg.get("default", max(v for v in limit_cfg.values() if isinstance(v, (int, float))))
        pct = df["close"].pct_change()
        exceed = pct.abs() > limit + 0.01
        if exceed.any():
            self.logger.warning("[%s] %s 有 %d 行涨跌幅超过 %.0f%%（可能是除权除息，仅告警）",
                                market, symbol, int(exceed.sum()), limit * 100)

    def _merge_night_session(self, df: pd.DataFrame) -> pd.DataFrame:
        """期货夜盘（21:00 之后）归属下一个交易日。"""
        if df.empty:
            return df
        out = df.copy()
        trade_days = []
        for ts in out.index:
            if ts.hour >= 21:
                nxt = ts.date() + timedelta(days=1)
                while not is_trading_day(nxt, "cn_future"):
                    nxt += timedelta(days=1)
                trade_days.append(pd.Timestamp(nxt))
            else:
                trade_days.append(pd.Timestamp(ts.date()))
        out["trade_date"] = trade_days
        return out

    # ==================== 辅助 ====================

    def _standardize(self, raw: pd.DataFrame, interface: str,
                     market: str = None, symbol: str = None) -> pd.DataFrame:
        """把任意接口返回整理成标准列，并按 INTERFACE_UNITS 里该接口的硬编码单位归一。

        interface: 接口名（akshare 函数名或自定义源标识），单位与换算系数一律查表，
                   不做任何「按成交额反推」；查不到的接口标注 attrs["unit_uncertain"]=True。
        """
        if raw is None or len(raw) == 0:
            return self._empty_frame()
        df = raw.copy()
        # 部分接口把日期放在索引上（如可转债日线）
        if not isinstance(df.index, pd.RangeIndex):
            index_name = str(df.index.name).lower()
            if "date" in index_name or "日期" in index_name:
                df = df.reset_index()
        df.columns = [str(c).strip() for c in df.columns]
        rename = {c: _COLUMN_MAP[c] for c in df.columns if c in _COLUMN_MAP}
        df = df.rename(columns=rename)

        # 日期列可能叫 时间 / datetime / trade_date
        if "date" not in df.columns:
            for cand in ("时间", "datetime", "trade_date", "日期"):
                if cand in raw.columns:
                    df["date"] = raw[cand]
                    break
        if "date" not in df.columns:
            raise ValueError(f"接口返回缺少日期列: {list(raw.columns)}")

        if "amount" not in df.columns:
            df["amount"] = 0.0
        if "volume" not in df.columns:
            df["volume"] = 0.0

        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        for col in _PRICE_COLUMNS + ["volume", "amount"]:
            if col not in df.columns:
                df[col] = np.nan
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.set_index("date").sort_index()
        cols = STANDARD_COLUMNS[1:] + [c for c in df.columns if c not in STANDARD_COLUMNS]
        out = df[cols]
        return self._normalize_units(out, interface, market, symbol)

    def _normalize_units(self, df: pd.DataFrame, interface: str,
                         market: str = None, symbol: str = None) -> pd.DataFrame:
        """按 INTERFACE_UNITS 的硬编码映射把源单位换成统一口径，并做成交额一致性自检。

        映射字段：接口 → (源 volume 单位, 源 amount 单位, volume 系数, amount 系数,
                          统一 volume 单位, 统一 amount 单位, 是否确证, 证据)
        """
        out = df.copy()
        spec = INTERFACE_UNITS.get(interface)
        if spec is None:
            out.attrs.update({"source": interface, "unit_uncertain": True,
                              "unit_evidence": f"接口 {interface} 未登记单位约定，原值透传"})
            self.logger.warning("[%s] %s 接口 %s 未登记单位，已标注 unit_uncertain=True",
                                market or "-", symbol or "-", interface)
            self._verify_units(out, market, symbol)
            return out

        v_unit, a_unit, vf, af, u_vol, u_amt, certain, evidence = spec
        if vf != 1.0:
            out["volume"] = pd.to_numeric(out["volume"], errors="coerce") * float(vf)
        if af != 1.0:
            out["amount"] = pd.to_numeric(out["amount"], errors="coerce") * float(af)

        out.attrs.update({
            "source": interface,
            "source_volume_unit": v_unit,
            "source_amount_unit": a_unit,
            "volume_unit": u_vol,
            "amount_unit": u_amt,
            "unit_evidence": evidence,
        })
        if not certain:
            out.attrs["unit_uncertain"] = True
        self._verify_units(out, market, symbol)
        return out

    def _verify_units(self, df: pd.DataFrame, market: str = None,
                      symbol: str = None) -> None:
        """成交额一致性自检：amount/(close×volume) 应 ≈1（<0.9 或 >1.1 即告警，不修正）。"""
        if df is None or df.empty:
            return
        if market == "cn_index":
            # 指数点位×成分股股数 与成交额没有换算关系，自检恒不成立，跳过并说明
            df.attrs["unit_ratio_note"] = "指数不适用 amount/(close×volume) 自检"
            return
        mask = (df["close"] > 0) & (df["volume"] > 0) & (df["amount"] > 0)
        if mask.sum() < 3:
            return
        ratio = float((df.loc[mask, "amount"] /
                       (df.loc[mask, "close"] * df.loc[mask, "volume"])).median())
        df.attrs["unit_ratio"] = round(ratio, 4)
        if 0.9 <= ratio <= 1.1:
            return
        hint = ""
        if 20 <= ratio <= 500:
            hint = "（volume 疑似仍为「手」未换算）"
        elif 5 <= ratio < 20:
            hint = "（volume 疑似「手」，如可转债 1 手=10 张）"
        elif ratio < 0.02:
            hint = "（amount 疑似仍为「千元」，应 ×1000）"
        self.logger.warning("[%s] %s 单位自检异常 amount/(close×volume)=%.4f%s source=%s",
                            market or "-", symbol or "-", ratio, hint,
                            df.attrs.get("source", "unknown"))



    def _empty_frame(self) -> pd.DataFrame:
        df = pd.DataFrame(columns=STANDARD_COLUMNS[1:])
        df.index = pd.DatetimeIndex([], name="date")
        return df

    def _extract_realtime(self, raw: pd.DataFrame, symbol: str,
                          code_cols: Sequence[str], match_suffix: bool = False) -> dict:
        if raw is None or raw.empty:
            raise RuntimeError("实时行情返回为空")
        code_col = next((c for c in code_cols if c in raw.columns),
                        next((c for c in raw.columns if "代码" in str(c) or str(c).lower() in ("symbol", "code")), None))
        if code_col is None:
            raise RuntimeError(f"实时行情缺少代码列: {list(raw.columns)}")
        codes = raw[code_col].astype(str).str.upper()
        target = str(symbol).upper()
        mask = codes.str.endswith(target) if match_suffix else (codes == target)
        hit = raw[mask]
        if hit.empty:
            hit = raw[codes.str.contains(target, na=False)]
        if hit.empty:
            raise RuntimeError(f"实时行情中未找到 {symbol}")
        row = hit.iloc[0]

        def pick(*names):
            for name in names:
                # 先精确匹配，再按子串匹配，避免 price 命中 pricechangepercent
                for col in raw.columns:
                    if str(col).lower() == str(name).lower():
                        value = row[col]
                        return None if pd.isna(value) else value
                for col in raw.columns:
                    if name in str(col):
                        value = row[col]
                        return None if pd.isna(value) else value
            return None

        def num(*names):
            value = pick(*names)
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        return {
            "name": pick("名称", "name") or "",
            "price": num("最新价", "最新", "trade", "price"),
            "change_pct": num("涨跌幅", "pricechangepercent"),
            "volume": num("成交量", "volume"),
            "bid": num("买一价", "买一", "buy", "bid"),
            "ask": num("卖一价", "卖一", "sell", "ask"),
            "open": num("今开", "开盘价", "open"),
            "high": num("最高价", "high"),
            "low": num("最低价", "low"),
            "prev_close": num("昨收", "昨收价", "settlement", "pre_close"),
        }

    def _standard_list(self, raw: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
        if raw is None or raw.empty:
            return pd.DataFrame(columns=["code", "name"])
        code_col, name_col = columns
        if code_col not in raw.columns:
            code_col = next((c for c in raw.columns
                             if "代码" in str(c) or str(c).lower() in ("code", "symbol")), None)
        if name_col not in raw.columns:
            name_col = next((c for c in raw.columns
                             if "名称" in str(c) or str(c).lower() in ("name", "简称")), None)
        if code_col is None or name_col is None:
            return pd.DataFrame(columns=["code", "name"])
        out = raw[[code_col, name_col]].copy()
        out.columns = ["code", "name"]
        out["code"] = out["code"].astype(str).str.strip()
        out["name"] = out["name"].astype(str).str.strip()
        return out.drop_duplicates("code").reset_index(drop=True)

    def _resolve_us_symbol(self, symbol: str) -> Optional[str]:
        symbol = str(symbol).upper()
        if "." in symbol:
            return symbol
        if self._us_code_map is None:
            try:
                raw = self._request(ak.stock_us_spot_em)
                code_col = next((c for c in raw.columns if "代码" in str(c)), "代码")
                self._us_code_map = {
                    str(code).split(".")[-1].upper(): str(code)
                    for code in raw[code_col].astype(str)
                }
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("美股代码映射构建失败: %s", exc)
                self._us_code_map = {}
        return self._us_code_map.get(symbol)

    def _cb_symbol(self, symbol: str) -> str:
        code = str(symbol).strip().lower()
        if code.startswith(("sh", "sz")):
            return code
        return ("sz" if code.startswith(("12", "128", "123", "127")) else "sh") + code

    def _futures_continuous(self, symbol: str) -> str:
        variety = re.sub(r"\d", "", str(symbol)).upper()
        return f"{variety}0" if variety else str(symbol).upper()

    def _to_date_str(self, value: str) -> str:
        return pd.Timestamp(value).strftime("%Y%m%d")

    def _load_dominant(self, variety: str) -> Optional[str]:
        path = self.cache_dir / f"_dominant_{variety}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("contract")
        except Exception:  # noqa: BLE001
            return None

    def _save_dominant(self, variety: str, contract: str) -> None:
        path = self.cache_dir / f"_dominant_{variety}.json"
        try:
            path.write_text(json.dumps({"contract": contract, "updated": datetime.now().isoformat()},
                                       ensure_ascii=False), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("主力合约标记写入失败: %s", exc)


__all__ = ["DataFetcher", "STANDARD_COLUMNS"]
