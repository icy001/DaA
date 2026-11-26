"""第 1 步数据层测试（含自证核查用例）

1) 16 个标的的日线/期权链可用性（单个失败不中断）；
2) 单位自检：600519 最近交易日 amount ≈ close × volume（相对误差 <5%）；
3) BaoStock 长历史：600519 60 分钟 3 年应 >1023 行且起点不晚于 3 年前+30 天缓冲；
4) 分钟增量库：attrs 四字段（available_from/minute_history_capped/source/adjust）齐全、落盘、二次调用不重复；
5) 歧义代码：ZN 未显式传 market_type 时带 ambiguous_market 提示；
6) 长历史：600519 取 10 年日线，校验行数（新浪无 1023 条日线上限）；
7) 列名一致性：跨 5 个市场断言 date 索引 + open/high/low/close/volume/amount；
8) 分钟线：A股 / 国内期货 / 外汇 各一条；
9) 新市场覆盖：可转债 113052、公募REITs 508000、新三板 830799（应显式报错说明走净值/定价路径）；
10) 分钟 date+time 双列：单日 60/30/15/5 分钟根数必须为 4/8/16/48，跨日严格递增；
11) 场景分工：取「今天」不得调用 BaoStock（仅盘后数据），且能取到当日已完成分钟线；
12) 增量库中段缺口：人为删除某日数据后，更新必须补回；
13) 复权同源：日线 qfq/raw 比值 ≡ BaoStock foreAdjustFactor，且 15:00 分钟 qfq 收盘 ≈ 日线 qfq 收盘（<0.1%）；
14) crypto 回填：attrs 标注单次上限 backfill_cap_bars=20000 与请求间隔 request_interval>=0.2；
15) 双重日历：日历开市但日线缺该日 → 识别为「日线缺口」(attrs daily_gap_dates + WARNING)；
16) BaoStock 会话失效：模拟「用户未登录」后必须自动重置会话、重登并重试；
17) 指数（cn_index）：裸 399/932 段识别为指数、裸 000 段维持个股优先（歧义）、
    sh000001/sh000300/sz399001 识别为 cn_index、10 年日线行数、指数无复权（adjust=none）、
    attrs.volume_unit 显式标注、东财源成交额非空（不可达则如实记录）、
    新浪分支 amount=NaN + amount_missing=True、分钟线标 capped。
"""
from __future__ import annotations

import logging
import sys
import tempfile
from datetime import date, datetime, timedelta

import pandas as pd

import akshare as ak

import config
from core.data_fetcher import DataFetcher
from core.utils import get_trading_sessions, is_trading_day

END = date.today()
START = END - timedelta(days=30)

REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume", "amount"]

# (说明, 代码, 类型)
TARGETS = [
    ("A股个股", "600519", "daily"),
    ("A股ETF", "510300", "daily"),
    ("美股个股", "AAPL", "daily"),
    ("美股ETF", "SPY", "daily"),
    ("港股个股", "00700", "daily"),
    ("可转债", "123150", "daily"),
    ("可转债2", "113052", "daily"),
    ("公募REITs", "508000", "daily"),
    ("国内期货", "rb", "daily"),
    ("国际期货", "GC", "daily"),
    ("外汇", "EURUSD", "daily"),
    ("加密货币", "BTC", "daily"),
    ("公募基金", "161725", "daily"),
    ("国债逆回购", "204001", "daily"),
    ("ETF期权链", "510050", "option_chain"),
]

# ---- v3.49 / 13.0.20 ③：离线静态上界必须是「字面整数或字面整数相加」----
# v3.48 写成 len(TARGETS) + FIXED_CHECK_COUNT：仍是「从运行期对象取值」，
# 只要 TARGETS 被删一项，上界就跟着缩水 —— 闸门随被守卫对象一起松。
# 现在钉成纯字面量 19 + 15（= FIXED_CHECK_COUNT + len(TARGETS) 的当时取值）：
# 上界是常量，TARGETS 变动不再影响它；两者一致性另由运行期断言兜底（见 main()）。
FIXED_CHECK_COUNT = 19          # main() 内 checks 列表的固定核查项数（静态）
DETERMINISTIC_BOUND = 19 + 15   # 字面整数相加：FIXED_CHECK_COUNT(19) + len(TARGETS)(15)


def show(title: str, symbol: str, df: pd.DataFrame) -> None:
    print("\n" + "-" * 72)
    print(f"【{title}】{symbol}  形状={df.shape}")
    if df is None or df.empty:
        return
    print(df.head(5).to_string())
    print(f"空值统计：\n{df.isna().sum().to_string()}")


# ==================== 自证核查用例 ====================

def check_units(fetcher: DataFetcher) -> tuple[bool, str]:
    """核实1：A股/ETF/可转债 最近交易日 amount/(close×volume) 必须落在 [0.9, 1.1]。

    可转债（新浪日线无成交额字段）amount 为 close×volume(张) 估算，比值恒为 1，
    需同时校验 attrs["amount_estimated"]=True，避免把估算当成实测。
    """
    cases = [("A股", "600519"), ("ETF", "510300"), ("可转债", "113052")]
    problems, details = [], []
    for label, symbol in cases:
        df = fetcher.get_daily(symbol, (START - timedelta(days=60)).strftime("%Y-%m-%d"),
                               END.strftime("%Y-%m-%d"), adjust="")
        if df.empty:
            problems.append(f"{label} {symbol} 无数据")
            continue
        row = df.iloc[-1]
        if min(row["close"], row["volume"], row["amount"]) <= 0:
            problems.append(f"{label} {symbol} 最近交易日 close/volume/amount 存在 0 值")
            continue
        ratio = float(row["amount"] / (row["close"] * row["volume"]))
        ok = 0.9 <= ratio <= 1.1
        estimated = bool(df.attrs.get("amount_estimated", False))
        details.append(f"{label} {symbol} {df.index[-1].date()} ratio={ratio:.4f}"
                       f"{'（amount 估算）' if estimated else ''}")
        if not ok:
            problems.append(f"{label} {symbol} ratio={ratio:.4f} 越界 [0.9,1.1]")
        if symbol == "113052" and not estimated:
            problems.append("可转债 amount 未标注 amount_estimated=True")
    if problems:
        return False, "；".join(details + problems)
    return True, "；".join(details)


def check_minute_long_history(fetcher: DataFetcher) -> tuple[bool, str]:
    """A股分钟线长历史：BaoStock 取 600519 60 分钟 3 年（>1023 行，起点不晚于 3 年前+缓冲）。"""
    start = (END - timedelta(days=365 * 3)).strftime("%Y-%m-%d")
    df = fetcher.get_minute("600519", "60", start, END.strftime("%Y-%m-%d"))
    rows = len(df)
    source = df.attrs.get("source", "unknown")
    capped = bool(df.attrs.get("minute_history_capped", False))
    span = f"{df.index.min()} ~ {df.index.max()}" if rows else "空"
    problems = []
    if rows <= 1023:
        problems.append(f"行数 {rows} 未超过新浪上限 1023")
    if rows and df.index.min() > pd.Timestamp(start) + pd.Timedelta(days=30):
        problems.append(f"起点 {df.index.min()} 晚于请求起点+30天缓冲")
    if source != "baostock_minute":
        problems.append(f"数据源={source}，未走 BaoStock")
    msg = (f"{start} 起请求 60 分钟线 → {rows} 行（阈值 >1023），实际区间 {span}，"
           f"source={source}，minute_history_capped={capped}")
    return (not problems), (msg if not problems else f"{msg}；{'；'.join(problems)}")


def check_minute_store(fetcher: DataFetcher) -> tuple[bool, str]:
    """分钟增量库：attrs 四字段齐全、落盘存在、二次调用不重复/不丢历史。"""
    start = (END - timedelta(days=365 * 3)).strftime("%Y-%m-%d")
    first = fetcher.get_minute("600519", "60", start, END.strftime("%Y-%m-%d"))
    second = fetcher.get_minute("600519", "60", start, END.strftime("%Y-%m-%d"))
    store = fetcher._minute_store_path("cn_stock", "600519", "60")
    problems = []
    for key in ("available_from", "minute_history_capped", "source", "adjust"):
        if key not in first.attrs:
            problems.append(f"attrs 缺 {key}")
    if not isinstance(first.attrs.get("minute_history_capped"), bool):
        problems.append("minute_history_capped 不是 bool")
    if not store.exists():
        problems.append(f"未落盘 {store}")
    if len(second) != len(first):
        problems.append(f"二次调用行数变化 {len(first)} → {len(second)}")
    if len(second) and second.index.duplicated().any():
        problems.append("增量库存在重复时间戳")
    msg = (f"增量库 {store.name} 行数 {len(first)}，available_from={first.attrs.get('available_from')}，"
           f"capped={first.attrs.get('minute_history_capped')}，source={first.attrs.get('source')}，"
           f"adjust={first.attrs.get('adjust')}，二次调用 {len(second)} 行")
    return (not problems), (msg if not problems else f"{msg}；{'；'.join(problems)}")


def check_ambiguous_codes(fetcher: DataFetcher) -> tuple[bool, str]:
    """歧义代码：ZN 未显式传 market_type 时必须带 ambiguous_market 提示，显式传入则不提示。"""
    market, hint = fetcher._detect_market("ZN")
    market2, hint2 = fetcher._detect_market("ZN", "cn_future")
    problems = []
    if not hint.get("ambiguous_market"):
        problems.append("ZN 未标注 ambiguous_market")
    if "cn_future" not in (hint.get("market_candidates") or []):
        problems.append("market_candidates 缺少 cn_future")
    if hint2:
        problems.append("显式传 market_type 后仍带歧义提示")
    if market2 != "cn_future":
        problems.append(f"显式 market_type 未生效（得到 {market2}）")
    msg = (f"ZN 默认={market}，候选={hint.get('market_candidates')}；"
           f"显式 cn_future={market2}，提示={bool(hint2)}")
    return (not problems), (msg if not problems else f"{msg}；{'；'.join(problems)}")



def check_long_history(fetcher: DataFetcher) -> tuple[bool, str]:
    """核查3：600519 取 10 年日线，行数应接近 2400 条（>1023 说明无分页截断）。"""
    start = (END - timedelta(days=365 * 10)).strftime("%Y-%m-%d")
    df = fetcher.get_daily("600519", start, END.strftime("%Y-%m-%d"), adjust="")
    rows = len(df)
    ok = rows >= 2300
    return ok, f"{start} ~ {END} 共 {rows} 行（10 年约 2430 个交易日，阈值 2300）"


def check_columns(fetcher: DataFetcher) -> tuple[bool, str]:
    """核查6：跨 5 个市场的列名一致性。"""
    cases = [("cn_stock", "600519"), ("cn_etf", "510300"), ("cn_convertible", "113052"),
             ("cn_reits", "508000"), ("cn_future", "rb")]
    problems = []
    for market, symbol in cases:
        try:
            df = fetcher.get_daily(symbol, (END - timedelta(days=15)).strftime("%Y-%m-%d"),
                                   END.strftime("%Y-%m-%d"))
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{market}/{symbol} 失败: {exc}")
            continue
        if df.empty:
            problems.append(f"{market}/{symbol} 空数据")
            continue
        if df.index.name != "date":
            problems.append(f"{market}/{symbol} 索引名={df.index.name}，应为 date")
        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            problems.append(f"{market}/{symbol} 缺列 {missing}")
    if problems:
        return False, "；".join(problems)
    return True, "5 个市场列名一致（date 索引 + open/high/low/close/volume/amount）"


def check_minute(fetcher: DataFetcher) -> tuple[bool, str]:
    """核查6-3：分钟线独立用例（A股 / 国内期货 / 外汇）。"""
    cases = [("A股", "600519"), ("期货", "rb"), ("外汇", "EURUSD")]
    problems = []
    details = []
    for label, symbol in cases:
        try:
            df = fetcher.get_minute(symbol, "5", (END - timedelta(days=10)).strftime("%Y-%m-%d"),
                                    END.strftime("%Y-%m-%d"))
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{label}/{symbol}: {exc}")
            continue
        if df.empty:
            problems.append(f"{label}/{symbol} 空数据")
            continue
        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            problems.append(f"{label}/{symbol} 缺列 {missing}")
        details.append(f"{label} {len(df)} 行")
    if problems:
        return False, "；".join(problems)
    return True, "、".join(details)


def check_new_markets(fetcher: DataFetcher) -> tuple[bool, str]:
    """核查4：可转债/REITs 可交易，新三板必须显式说明走净值/定价路径。"""
    problems = []
    for symbol, label in (("113052", "可转债"), ("508000", "REITs")):
        try:
            df = fetcher.get_daily(symbol, (END - timedelta(days=30)).strftime("%Y-%m-%d"),
                                   END.strftime("%Y-%m-%d"))
            if df.empty:
                problems.append(f"{label} {symbol} 空数据")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{label} {symbol}: {exc}")
    try:
        fetcher.get_daily("830799", (END - timedelta(days=30)).strftime("%Y-%m-%d"),
                          END.strftime("%Y-%m-%d"))
        problems.append("neeq 830799 未报错（应显式说明走净值/定价路径）")
    except ValueError as exc:
        if "新三板" not in str(exc):
            problems.append(f"neeq 报错信息不明确: {exc}")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"neeq 830799 抛出非预期异常: {exc}")
    if problems:
        return False, "；".join(problems)
    return True, "113052/508000 可取数；830799 显式说明「新三板走券商数据源」"


def check_index_market(fetcher: DataFetcher) -> tuple[bool, str]:
    """核查7（指数）：识别（含裸 6 位）→ 10 年日线行数 → 源与单位 → 分钟 capped。

    指数代码带前缀（sh000300 / sz399001）才能取沪市 000xxx 段指数；裸 399xxx/932xxx
    无歧义可裸判，裸 000xxx 与深市个股完全重合，维持个股优先。指数无复权，
    attrs.adjust 必须为 none；volume 统一为手（新浪来源为股，÷100 折算）。
    """
    problems, details = [], []

    # 1) 市场识别：带前缀的指数必须判为 cn_index（且不被国内期货分支抢走）
    wrong = [(c, config.detect_market_type(c))
             for c in ("sh000001", "sh000300", "sz399001")
             if config.detect_market_type(c) != "cn_index"]
    if wrong:
        problems.append(f"指数识别错误: {wrong}")
    else:
        details.append("sh000001/sh000300/sz399001 → cn_index")

    # 2) 裸 6 位识别：399xxx/932xxx 无歧义可裸判；000xxx 与深市个股完全重合必须个股优先
    bare_index = ("399001", "399006", "399673", "932000")
    bare_stock = ("000300", "000905", "000016", "000688")
    bad = [c for c in bare_index if config.detect_market_type(c) != "cn_index"]
    bad += [c for c in bare_stock if config.detect_market_type(c) != "cn_stock"]
    if bad:
        problems.append(f"裸 6 位识别错误: {[(c, config.detect_market_type(c)) for c in bad]}")
    else:
        details.append("裸 399/932 段 → cn_index；裸 000 段 → cn_stock（歧义，需带前缀）")

    # 3) 10 年日线行数（约 2400 个交易日，>1500 即合理）
    start10 = (END - timedelta(days=365 * 10)).strftime("%Y-%m-%d")
    try:
        df = fetcher.get_daily("sh000300", start10, END.strftime("%Y-%m-%d"))
        if df is None or df.empty:
            problems.append("sh000300 10 年日线为空")
        else:
            details.append(f"sh000300 10 年日线 {len(df)} 行")
            if len(df) < 1500:
                problems.append(f"sh000300 10 年日线仅 {len(df)} 行，少于 1500")
            if df.attrs.get("adjust") != "none":
                problems.append(f"指数 adjust 标注应为 none，实际 {df.attrs.get('adjust')}")
            # 成交量单位必须显式标注（东财=手 / 新浪=股，统一为手）
            if not df.attrs.get("volume_unit"):
                problems.append("指数日线缺少 attrs.volume_unit 标注")
            else:
                details.append(f"source={df.attrs.get('source')} volume_unit="
                               f"{df.attrs.get('volume_unit')}（源单位 {df.attrs.get('source_volume_unit')}）")
            if df.attrs.get("amount_missing"):
                # 新浪指数日线无成交额：必须置 NaN 并标注，禁止补 0 冒充零成交
                details.append("新浪源无成交额 → amount=NaN 且标 amount_missing")
                if df["amount"].notna().any():
                    problems.append("无成交额源却出现非空 amount（疑似补 0）")
            else:
                last = df.iloc[-1]
                shares = float(last["volume"]) * 100.0      # volume 口径为「手」= 100 股
                avg_price = float(last["amount"]) / shares if shares > 0 else 0.0
                details.append(f"最新日 隐含成分股均价=amount/(volume×100)={avg_price:.2f} 元/股")
                # 指数 close 是指数点位、不是股价，不能拿 close×volume 反推单位（会恒得 ~0.6）；
                # 用「成交额 ÷ 成交股数」得到隐含均价，落在合理区间才说明「手 / 元」口径自洽。
                # 若 volume 实为股则均价会缩到 1/100，若 amount 实为千元也会缩到 1/1000，均会被拦下。
                if not 1.0 <= avg_price <= 500.0:
                    problems.append(
                        f"指数成交额单位异常 隐含均价={avg_price:.2f} 元/股（volume=手, amount=元）")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"sh000300 日线异常: {exc}")

    # 4) 东财源直连探测（裸代码 000300）：可达则断言含成交额；不可达如实记录，不假装通过
    try:
        em = ak.index_zh_a_hist(symbol="000300", period="daily",
                                start_date="20260101", end_date=END.strftime("%Y%m%d"))
        amt_col = "成交额" if "成交额" in em.columns else ("amount" if "amount" in em.columns else None)
        if amt_col is None:
            problems.append(f"东财指数日线无成交额字段，实际列 {list(em.columns)}")
        elif not pd.to_numeric(em[amt_col], errors="coerce").notna().any():
            problems.append("东财指数日线成交额全空")
        else:
            details.append(f"东财 index_zh_a_hist(裸代码 000300) {len(em)} 行，成交额非空，"
                           f"列 {[c for c in em.columns if c in ('成交量', '成交额', 'volume', 'amount')]}")
    except Exception as exc:  # noqa: BLE001
        details.append(f"东财指数源本机不可达（{type(exc).__name__}），"
                       f"已走新浪回退分支，成交额断言改用新浪分支验证")

    # 5) 强制走新浪分支：必须 amount=NaN + amount_missing=True + volume_unit 标注
    orig_request = fetcher._request

    def _skip_eastmoney(func, *a, **kw):
        if kw.get("_source") == "eastmoney":
            raise ConnectionError("测试强制跳过东财以验证新浪分支")
        return orig_request(func, *a, **kw)

    fetcher._request = _skip_eastmoney
    try:
        sina_df = fetcher._fetch_cn_index_daily("sh000300", start10, END.strftime("%Y-%m-%d"), "none")
        if not sina_df.attrs.get("amount_missing"):
            problems.append("新浪分支未标 amount_missing=True")
        elif sina_df["amount"].notna().any():
            problems.append("新浪分支 amount 出现非空值（禁止补 0）")
        elif sina_df.attrs.get("volume_unit") != "手":
            problems.append(f"新浪分支 volume_unit 应为「手」，实际 {sina_df.attrs.get('volume_unit')}")
        else:
            details.append(f"新浪分支校验：{len(sina_df)} 行，amount 全 NaN、"
                           f"amount_missing=True、volume_unit=手（源为股，已÷100 折算）")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"新浪分支校验异常: {exc}")
    finally:
        fetcher._request = orig_request

    # 6) 分钟线：请求 6 个月必然超出东财约 1 个月/新浪 1970 根上限 → 必须标 capped
    try:
        m0 = (END - timedelta(days=180)).strftime("%Y-%m-%d")
        m = fetcher.get_minute("sh000300", "5", start_date=m0, end_date=END.strftime("%Y-%m-%d"))
        if m is None or m.empty:
            problems.append("sh000300 5 分钟线为空")
        else:
            capped = bool(m.attrs.get("minute_history_capped"))
            details.append(f"sh000300 5 分钟 {len(m)} 行，capped={capped}，"
                           f"source={m.attrs.get('source')}")
            if not capped:
                problems.append("指数分钟线请求 6 个月但未标 minute_history_capped")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"sh000300 分钟线异常: {exc}")

    return (not problems), "；".join(details if not problems else problems)


def check_single_source_behavior(fetcher: DataFetcher = None) -> tuple[bool, str]:
    """核实8 单点故障：模拟东财不可达 → 单点市场必须显式报错，有备源市场必须正常回退。

    单点市场（config.SINGLE_SOURCE_MARKETS）：日线 forex/cn_fund/cn_reverse_repo；
    分钟 cn_convertible/us_stock/us_etf/hk_stock。失败时必须抛 RuntimeError 且文案含
    「该市场当前无可用数据源」，禁止静默返回空表（否则第 3 步算指标全是 NaN 而不自知）。
    有备源市场（cn_stock 日线、cn_index 日线）必须回退新浪并正常返回。
    """
    import tempfile
    tmp = tempfile.mkdtemp(prefix="datalayer_src_")
    sim = DataFetcher(cache_dir=tmp, request_delay=0, max_retry=1)
    orig = sim._request

    def _fake(func, *a, **kw):
        if kw.get("_source") == "eastmoney":
            raise ConnectionError("测试模拟东财 push2his 不可达")
        return orig(func, *a, **kw)

    sim._request = _fake
    end = END.strftime("%Y-%m-%d")
    start = (END - timedelta(days=10)).strftime("%Y-%m-%d")
    problems, details = [], []

    daily_cases = [("forex", "EURUSD", lambda: sim.get_daily("EURUSD", start, end)),
                   ("cn_fund", "161725", lambda: sim.get_daily("161725", start, end)),
                   ("cn_reverse_repo", "204001", lambda: sim.get_daily("204001", start, end))]
    for market, symbol, fn in daily_cases:
        try:
            df = fn()
            problems.append(f"{market} {symbol} 东财挂时未抛错，返回 {len(df)} 行（违反禁止静默空表）")
        except RuntimeError as exc:
            if "无可用数据源" not in str(exc):
                problems.append(f"{market} {symbol} 报错未含「无可用数据源」：{exc}")
            else:
                details.append(f"{market} 抛错 ✅")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{market} {symbol} 抛出非 RuntimeError：{type(exc).__name__}: {exc}")

    minute_cases = [("cn_convertible", "123045"), ("us_stock", "AAPL"),
                    ("us_etf", "SPY"), ("hk_stock", "00700")]
    for market, symbol in minute_cases:
        try:
            df = sim.get_minute(symbol, "60", start, end)
            problems.append(f"{market} {symbol} 分钟线东财挂时未抛错，返回 {len(df)} 行")
        except RuntimeError as exc:
            if "无可用数据源" not in str(exc):
                problems.append(f"{market} {symbol} 分钟报错未含「无可用数据源」：{exc}")
            else:
                details.append(f"{market} 分钟抛错 ✅")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{market} {symbol} 分钟抛非 RuntimeError：{type(exc).__name__}: {exc}")

    # 有备源：日线必须回退新浪并正常返回（不报错）
    for symbol, expect_source in (("600519", "stock_zh_a_daily"), ("sh000300", "stock_zh_index_daily")):
        try:
            df = sim.get_daily(symbol, start, end, adjust="")
            src = df.attrs.get("source")
            if df.empty:
                problems.append(f"{symbol} 有备源却返回空表")
            elif src != expect_source:
                problems.append(f"{symbol} 未回退到 {expect_source}，实际 source={src}")
            else:
                details.append(f"{symbol} 回退 {src} ✅（{len(df)} 行）")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{symbol} 有备源却报错：{type(exc).__name__}: {exc}")

    if not problems:
        details.append("单点市场全部显式报错、有备源市场全部正常回退")
    return (not problems), "；".join(details if not problems else problems)


def check_stale_policy(fetcher: DataFetcher = None) -> tuple[bool, str]:
    """核实9：stale 收敛 —— 交易日差标注、STALE_LIMIT、回测豁免、下单独立复核。

    构造「本地库停更 N 个交易日」：backtest 模式一律放行（只标注 stale）；
    paper/live 模式超限或 stale 直接报错（不依赖调用方传 for_trading）；
    for_trading=True 在任何模式遇 stale 都拒绝。

    下单复核（assert_fresh_for_trading）按真实链路验收：
    - A1 决策帧由纯函数指标拼成，物化列带不过来 → 有 market+symbol 时默认 refetch，
         禁止因「帧里没有时效列」fail-closed；
    - A2 asof 必须是帧内最后一根 bar 的实际日期（缓存命中/回退路径尤其），不能按取数时刻填今天；
    - A3 多标的帧按 symbol 分组填各自日期，下单只读该标的的行，B 停更仍要拦；
    - A4 refetch 失败：开仓拒单、平仓放行；同批次 TTL 内复用结果；
    - A5 backtest 默认放行，但显式 for_trading=True 仍拦。
    """
    import os
    import tempfile
    import time as _time

    from core.data_fetcher import assert_fresh_for_trading

    tmp = tempfile.mkdtemp(prefix="datalayer_stale_")
    sim = DataFetcher(cache_dir=tmp, request_delay=0, max_retry=1)
    market = "cn_future"
    ref = sim._latest_completed_trading_day(market)
    limit_d = int(config.STALE_LIMIT["daily"])
    limit_m = int(config.STALE_LIMIT["minute"])

    def back_trading_days(n: int):
        day, left = ref, n
        while left > 0:
            day -= timedelta(days=1)
            if is_trading_day(day, market):
                left -= 1
        return day

    def fail_fetch(*_a, **_kw):
        raise ConnectionError("测试模拟数据源不可达")

    sim._fetch_daily = fail_fetch
    sim._fetch_minute = fail_fetch
    end = END.strftime("%Y-%m-%d")
    start = (END - timedelta(days=40)).strftime("%Y-%m-%d")
    problems, details = [], []

    def seed_daily(n: int):
        idx = pd.bdate_range(end=pd.Timestamp(back_trading_days(n)), periods=30)
        df = pd.DataFrame({"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0,
                           "volume": 100.0, "amount": 100.0}, index=idx)
        df.index.name = "date"
        path = sim._cache_path(market, "rb", "daily", "")
        sim._save_cache(df, path)
        old = _time.time() - 30 * 86400  # 让 _cache_expired 判过期 → 走「请求失败→回退缓存」分支
        os.utime(path, (old, old))

    def seed_minute(n: int):
        last = pd.Timestamp(back_trading_days(n)) + pd.Timedelta(hours=14)
        idx = pd.DatetimeIndex([last - pd.Timedelta(minutes=60 * i) for i in range(8)][::-1])
        df = pd.DataFrame({"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0,
                           "volume": 10.0, "amount": 10.0}, index=idx)
        df.index.name = "date"
        sim._save_minute_store(df, sim._minute_store_path(market, "rb", "60"))

    mode_backup = config.RUN_MODE
    try:
        # 1) backtest 豁免：停更 上限+2 仍返回（标注 stale）
        config.RUN_MODE = "backtest"
        seed_daily(limit_d + 2)
        df = sim.get_daily("rb", start, end, adjust="")
        if not df.empty and df.attrs.get("stale") and df.attrs.get("stale_days") == limit_d + 2:
            details.append(f"backtest 豁免（stale_days={limit_d + 2} 放行）✅")
        else:
            problems.append(f"backtest 未放行：stale={df.attrs.get('stale')} "
                            f"stale_days={df.attrs.get('stale_days')}")

        # 2) paper 模式：同样数据必须拒绝（不传 for_trading 也要拦）
        config.RUN_MODE = "paper"
        try:
            sim.get_daily("rb", start, end, adjust="")
            problems.append(f"paper 模式停更 {limit_d + 2} 日未拦截")
        except RuntimeError as exc:
            if "超过上限" in str(exc):
                details.append("paper 超限拦截 ✅")
            else:
                problems.append(f"paper 超限报错文案不符：{exc}")

        # 3) paper 模式：停更 = 上限 → 仍拒绝（闸门禁止 paper/live 用 stale）
        seed_daily(limit_d)
        try:
            sim.get_daily("rb", start, end, adjust="")
            problems.append("paper 模式 stale（未超限）未拦截")
        except RuntimeError as exc:
            if "时效闸门" in str(exc) or "禁止把过期数据" in str(exc):
                details.append("paper stale 拦截 ✅")
            else:
                problems.append(f"paper stale 报错文案不符：{exc}")

        # 4) live 模式同样拦截（停更 1 日）
        config.RUN_MODE = "live"
        seed_daily(1)
        try:
            sim.get_daily("rb", start, end, adjust="")
            problems.append("live 模式 stale 未拦截")
        except RuntimeError:
            details.append("live stale 拦截 ✅")

        # 5) 第一道防线不变：backtest 下 for_trading=True 遇 stale 也要拒绝
        config.RUN_MODE = "backtest"
        seed_daily(1)
        try:
            sim.get_daily("rb", start, end, adjust="", for_trading=True)
            problems.append("backtest + for_trading 遇 stale 未拒绝")
        except RuntimeError as exc:
            if "禁止用于" in str(exc) and "下单" in str(exc):
                details.append("for_trading 拒绝 ✅")
            else:
                problems.append(f"for_trading 报错文案不符：{exc}")

        # 6) 分钟线：backtest 停更 上限+2 放行；paper 停更 上限 拦截
        seed_minute(limit_m + 2)
        mdf = sim.get_minute("rb", "60", start, end)
        if not mdf.empty and mdf.attrs.get("stale") and mdf.attrs.get("stale_days") == limit_m + 2:
            details.append(f"分钟 backtest 豁免（stale_days={limit_m + 2}）✅")
        else:
            problems.append(f"分钟 backtest 未放行：stale_days={mdf.attrs.get('stale_days')}")
        config.RUN_MODE = "paper"
        seed_minute(limit_m)
        try:
            sim.get_minute("rb", "60", start, end)
            problems.append("paper 分钟 stale 未拦截")
        except RuntimeError:
            details.append("分钟 paper 拦截 ✅")

        # 7) 下单前独立复核（A1-A5）：refetch 为主、物化列兜底、多标的按 symbol 分组
        from core import data_fetcher as _dl

        col = config.STALE_INFO_COLUMN
        ref_ts = pd.Timestamp(ref)
        idx = pd.bdate_range(end=ref_ts, periods=30)
        fresh = pd.DataFrame({"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0,
                              "volume": 100.0, "amount": 100.0}, index=idx)
        fresh.index.name = "date"
        fresh[col] = ref_ts
        fresh.attrs.update({"stale": False, "stale_days": 0, "last_bar": str(ref)})
        # 先验证前提：rolling 确实清空 attrs（pandas 2.3.3）；指标一般按列算，故用数值子集
        if fresh.drop(columns=[col]).rolling(3).mean().attrs:
            problems.append("rolling 后 attrs 未清空（与实测口径不符）")

        old_ts = pd.Timestamp(back_trading_days(7))  # 停更 7 个交易日的旧数据
        old_idx = pd.bdate_range(end=old_ts, periods=30)
        old_df = pd.DataFrame({"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0,
                               "volume": 100.0, "amount": 100.0}, index=old_idx)
        old_df.index.name = "date"

        class _StubFetcher:
            """取数桩：returns 指定帧（默认最新=ref），避免测试打真实网络。"""

            def __init__(self, df=None, error=None):
                self.df = df if df is not None else fresh
                self.error = error
                self.calls = 0

            def get_daily(self, *_a, **_kw):
                self.calls += 1
                if self.error is not None:
                    raise self.error
                return self.df.copy()

            def get_minute(self, *_a, **_kw):
                return self.get_daily()

        # ---- A2：缓存命中路径的 asof 必须是缓存数据自身最后一根 bar 日期（≠ 今天）----
        sim._save_cache(old_df, sim._cache_path(market, "rb", "daily", ""))
        hit = sim.get_daily("rb", (old_ts - pd.Timedelta(days=20)).strftime("%Y-%m-%d"),
                            old_ts.strftime("%Y-%m-%d"), adjust="")
        hit_asof = pd.to_datetime(hit[col]) if col in hit.columns else pd.Series(dtype="datetime64[ns]")
        if len(hit_asof) and hit_asof.nunique() == 1 and hit_asof.iloc[-1] == old_ts \
                and hit_asof.iloc[-1].date() != date.today():
            details.append(f"缓存命中 asof={hit_asof.iloc[-1]:%Y-%m-%d}（最后一根 bar，非今天）✅")
        else:
            problems.append(f"缓存命中 asof 口径错误：{list(hit_asof.unique())[:3]}，应为 {old_ts.date()}")

        # ---- A3：多标的帧按 symbol 分组填各自最新日期 ----
        frame_a = fresh.copy()
        frame_a["symbol"] = "A"
        frame_b = old_df.copy()
        frame_b["symbol"] = "B"
        multi = sim._attach_asof(pd.concat([frame_a, frame_b]))
        a_asof = pd.Timestamp(multi.loc[multi["symbol"] == "A", col].iloc[-1])
        b_asof = pd.Timestamp(multi.loc[multi["symbol"] == "B", col].iloc[-1])
        if a_asof == ref_ts and b_asof == old_ts:
            details.append(f"多标的 asof 分组（A={a_asof:%Y-%m-%d} / B={b_asof:%Y-%m-%d}）✅")
        else:
            problems.append(f"多标的 asof 未分组：A={a_asof.date()} B={b_asof.date()}")

        mode_bak = config.STALE_CHECK_MODE
        try:
            # 隔离 refetch，专门验证「按 symbol 只读该标的行」的兜底逻辑
            config.STALE_CHECK_MODE = "column"
            try:
                assert_fresh_for_trading(multi, "daily", market, "A", run_mode="paper")
                details.append("多标的 A（新鲜）放行 ✅")
            except Exception as exc:  # noqa: BLE001
                problems.append(f"多标的 A 新鲜却被拒：{exc}")
            try:
                assert_fresh_for_trading(multi, "daily", market, "B", run_mode="paper")
                problems.append("多标的 B（停更 7 日）未拦截 —— 被整列广播掩盖")
            except RuntimeError as exc:
                if "数据已过期" in str(exc):
                    details.append("多标的 B（停更）仍被拦截 ✅")
                else:
                    problems.append(f"多标的 B 报错文案不符：{exc}")

            # 过期指标帧（带列、attrs 空）同样必须拒绝
            stale_ind = fresh.copy()
            stale_ind[col] = old_ts
            stale_ind.attrs = {}
            try:
                assert_fresh_for_trading(stale_ind, "daily", market, "C", run_mode="paper")
                problems.append("过期指标帧（带列、attrs 空）未拒绝")
            except RuntimeError as exc:
                if "数据已过期" in str(exc):
                    details.append("指标帧过期拒绝 ✅")
                else:
                    problems.append(f"过期指标帧报错文案不符：{exc}")
        finally:
            config.STALE_CHECK_MODE = mode_bak

        # ---- A1：决策帧丢了时效列也必须能下单（refetch 为主，禁止 fail-closed）----
        ind = fresh.drop(columns=[col]).copy()
        ind.attrs = {}
        _dl._REFETCH_CACHE.clear()
        try:
            assert_fresh_for_trading(ind, "daily", market, "A1", fetcher=_StubFetcher(), run_mode="paper")
            details.append("A1 决策帧无时效列 → refetch 放行 ✅")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"A1 决策帧被 fail-closed 锁死：{exc}")
        # refetch 优先：帧内列显示过期，但重取到最新 → 以 refetch 为准放行
        stale_col_frame = fresh.copy()
        stale_col_frame[col] = old_ts
        stale_col_frame.attrs = {}
        _dl._REFETCH_CACHE.clear()
        try:
            assert_fresh_for_trading(stale_col_frame, "daily", market, "A2r",
                                     fetcher=_StubFetcher(), run_mode="paper")
            details.append("refetch 为主（覆盖帧内过期列）✅")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"refetch 未主导判定：{exc}")

        # 裸帧：既无时效列、又无法重取（未传 market/symbol）→ 兜底 fail-closed
        bare = fresh.drop(columns=[col]).copy()
        bare.attrs = {}
        try:
            assert_fresh_for_trading(bare, "daily", run_mode="paper")
            problems.append("既无列又无法重取的裸帧未 fail-closed")
        except RuntimeError as exc:
            if "无法确认数据时效" in str(exc):
                details.append("裸帧兜底 fail-closed ✅")
            else:
                problems.append(f"裸帧 fail-closed 文案不符：{exc}")

        # ---- A4：refetch 失败 → 开仓拒单、平仓放行 ----
        _dl._REFETCH_CACHE.clear()
        bad = _StubFetcher(error=ConnectionError("测试模拟数据源不可达"))
        try:
            assert_fresh_for_trading(ind, "daily", market, "A4o", fetcher=bad,
                                     run_mode="paper", order_side="open")
            problems.append("refetch 失败仍放行开仓单")
        except RuntimeError as exc:
            if "按策略拒绝" in str(exc):
                details.append("refetch 失败 → 开仓拒单 ✅")
            else:
                problems.append(f"refetch 失败开仓文案不符：{exc}")
        try:
            assert_fresh_for_trading(ind, "daily", market, "A4c", fetcher=bad,
                                     run_mode="paper", order_side="close")
            details.append("refetch 失败 → 平仓放行 ✅")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"refetch 失败把平仓单也拒了（持仓无法退出）：{exc}")
        # 同批次 TTL 内复用（组合调仓不逐单打满接口）
        _dl._REFETCH_CACHE.clear()
        counter = _StubFetcher()
        for _ in range(3):
            assert_fresh_for_trading(ind, "daily", market, "TTL", fetcher=counter, run_mode="paper")
        if counter.calls == 1:
            details.append(f"refetch TTL {config.STALE_REFETCH_TTL_SEC}s 内复用（3 次复核取数 1 次）✅")
        else:
            problems.append(f"TTL 复用失效：3 次复核取数 {counter.calls} 次")

        # ---- A5：backtest 默认放行；显式 for_trading=True 仍要拦 ----
        try:
            if assert_fresh_for_trading(stale_col_frame, "daily", market, "A5",
                                        run_mode="backtest"):
                details.append("assert_fresh backtest 默认豁免 ✅")
            else:
                problems.append("assert_fresh 在 backtest 未返回 True")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"assert_fresh 破坏 backtest 豁免：{exc}")
        _dl._REFETCH_CACHE.clear()
        try:
            assert_fresh_for_trading(stale_col_frame, "daily", market, "A5",
                                     fetcher=_StubFetcher(df=old_df),
                                     run_mode="backtest", for_trading=True)
            problems.append("backtest + for_trading=True + stale 未拦截")
        except RuntimeError as exc:
            if "数据已过期" in str(exc):
                details.append("backtest 显式 for_trading 仍拦截 stale ✅")
            else:
                problems.append(f"backtest for_trading 报错文案不符：{exc}")
        _dl._REFETCH_CACHE.clear()

    finally:
        config.RUN_MODE = mode_backup

    if not problems:
        details.append(f"STALE_LIMIT daily={limit_d}/minute={limit_m}；"
                       f"闸门按 RUN_MODE（paper/live 生效、backtest 豁免）")
    return (not problems), "；".join(details if not problems else problems)


def check_market_clock(_fetcher: DataFetcher = None) -> tuple[bool, str]:
    """核实10：最近已收盘交易日必须逐市场取时钟（A股15:00 / 美股美东16:00 / 加密7×24）。"""
    import tempfile

    tmp = tempfile.mkdtemp(prefix="datalayer_clock_")
    sim = DataFetcher(cache_dir=tmp, request_delay=0, max_retry=1)
    today = date.today()
    problems, details = [], []
    for market, label in (("cn_stock", "A股"), ("us_stock", "美股"), ("crypto", "加密")):
        ref = sim._latest_completed_trading_day(market)
        if ref > today:
            problems.append(f"{label} ref={ref} 超过今天")
            continue
        if market == "crypto":
            # 7×24：今天那根日线还没走完，最近已完成日线应为昨天
            if ref != today - timedelta(days=1):
                problems.append(f"{label}(7×24) ref={ref}，应为 {today - timedelta(days=1)}")
            else:
                details.append(f"{label} 7×24 → {ref} ✅")
            continue
        if not is_trading_day(ref, market):
            problems.append(f"{label} ref={ref} 不是该市场交易日")
            continue
        sessions = get_trading_sessions(market, today)
        if sessions and is_trading_day(today, market):
            close_dt = sessions[-1][1]
            closed = datetime.now(close_dt.tzinfo) >= close_dt
            if closed and ref != today:
                problems.append(f"{label} 今日已收盘({close_dt:%H:%M})，ref={ref} 却非今天")
            elif not closed and ref >= today:
                problems.append(f"{label} 今日未收盘({close_dt:%H:%M})，ref={ref} 不应为今天")
            else:
                details.append(f"{label} 收盘 {close_dt:%H:%M}{close_dt.tzname()} "
                               f"{'已收盘→今天' if closed else '未收盘→上一交易日'} ref={ref} ✅")
        else:
            details.append(f"{label} 今日休市 → 上一交易日 {ref} ✅")
    if not problems:
        details.append("各市场时钟独立（非统一 A 股 15:00）")
    return (not problems), "；".join(details if not problems else problems)


def check_minute_bar_counts(fetcher: DataFetcher) -> tuple[bool, str]:
    """核实2：date+time 双列必须合成唯一 datetime 索引，单日根数 60/30/15/5=4/8/16/48。

    若只用 date 做索引会塌成 1 根/天；这里逐周期断言根数与 60 分钟时间戳，
    并用连续 3 个交易日验证跨日严格递增。
    """
    expect = {"60": 4, "30": 8, "15": 16, "5": 48}
    problems, details = [], []
    day = None
    # 往前找最近一个有数据的交易日（自动跳过周末/节假日）
    for back in range(1, 12):
        cand = (END - timedelta(days=back)).strftime("%Y-%m-%d")
        try:
            probe = fetcher._fetch_cn_minute("cn_stock", "600519", "60", cand, cand)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{cand} 探测失败: {exc}")
            break
        if probe is not None and not probe.empty:
            day = cand
            break
    if day is None:
        return False, "；".join(problems + ["最近 11 天未找到有分钟数据的交易日"])

    for period, want in expect.items():
        try:
            df = fetcher._fetch_cn_minute("cn_stock", "600519", period, day, day)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{period}分钟 {day} 失败: {exc}")
            continue
        times = [t.strftime("%H:%M") for t in df.index]
        if len(df) != want:
            problems.append(f"{period}分钟 {day} 根数={len(df)}，期望 {want}（疑似只用 date 做索引）")
        if not df.index.is_monotonic_increasing:
            problems.append(f"{period}分钟 {day} 时间戳非严格递增")
        if period == "60" and times != ["10:30", "11:30", "14:00", "15:00"]:
            problems.append(f"60分钟时间戳={times}，期望 10:30/11:30/14:00/15:00")
        details.append(f"{period}分钟 {len(df)} 根")

    # 跨日严格递增（连续 5 个自然日窗口）
    try:
        span = fetcher._fetch_cn_minute("cn_stock", "600519", "60",
                                        (pd.Timestamp(day) - pd.Timedelta(days=4)).strftime("%Y-%m-%d"),
                                        day)
        days = sorted(set(span.index.normalize().date))
        if not span.index.is_monotonic_increasing or len(days) < 2:
            problems.append(f"跨日序列非严格递增或跨日不足 2 天（{len(days)} 天）")
        else:
            details.append(f"跨 {len(days)} 个交易日严格递增")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"跨日校验失败: {exc}")

    msg = f"{day}：" + "、".join(details)
    return (not problems), (msg if not problems else f"{msg}；{'；'.join(problems)}")


def _simulate_today_fallback_field() -> tuple[bool, str]:
    """v3.51 / 13.0.22 ⑤：离线模拟「实时源全灭 → 回退本地累计」。

    隔离缓存目录 + 仅前两日的分钟库 + sina/东财强制失败；
    不挂任何日志 handler——检测只认结构化字段 today_missing_declared，
    验证「去掉日志行但保留字段」仍能检出。返回 (ok, note)。
    """
    with tempfile.TemporaryDirectory() as tmp:
        sim = DataFetcher(cache_dir=tmp)
        idx = pd.DatetimeIndex([f"{END - timedelta(days=2)} 10:30:00",
                                f"{END - timedelta(days=1)} 10:30:00"])
        store = pd.DataFrame({"open": [1.0, 1.0], "high": [1.0, 1.0], "low": [1.0, 1.0],
                              "close": [1.0, 1.0], "volume": [100.0, 100.0],
                              "amount": [100.0, 100.0]}, index=idx)
        store.attrs["source"] = "baostock_minute"
        sim._save_minute_store(store, sim._minute_store_path("cn_stock", "600519", "60"))
        sim._fetch_cn_minute_sina = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("模拟sina失败"))
        sim._fetch_cn_minute_em = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("模拟eastmoney失败"))
        df2 = sim.get_minute("600519", "60", END.strftime("%Y-%m-%d"),
                             END.strftime("%Y-%m-%d"))
        ok = df2.attrs.get("today_missing_declared") is True
        return ok, (f"rows={len(df2)} today_missing_declared="
                    f"{df2.attrs.get('today_missing_declared')}")


def check_minute_today_no_baostock(fetcher: DataFetcher) -> tuple[bool, str]:
    """核实3：取「今天」必须走新浪/东财，不得调用 BaoStock（仅盘后数据）。

    v3.51 / 13.0.22 ⑤：当日空缺的检测依据从「读日志文本」升级为结构化字段
    today_missing_declared（日志仅作辅助显示）。另含离线模拟子验证：
    实时源全灭回退本地累计时，回退帧必须带该字段，且判定不依赖日志。
    """
    today = END.strftime("%Y-%m-%d")
    called = {"n": 0}
    orig = fetcher._fetch_cn_stock_minute_baostock

    def _spy(*args, **kwargs):
        called["n"] += 1
        return orig(*args, **kwargs)

    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture(level=logging.WARNING)
    fetcher.logger.addHandler(handler)
    fetcher._fetch_cn_stock_minute_baostock = _spy
    try:
        df = fetcher.get_minute("600519", "60", today, today)
    finally:
        fetcher._fetch_cn_stock_minute_baostock = orig
        fetcher.logger.removeHandler(handler)

    problems = []
    if called["n"]:
        problems.append(f"取今天仍调用了 BaoStock {called['n']} 次")
    source = str(df.attrs.get("source", ""))
    if "baostock" in source or "baostock" in str(df.attrs.get("sources", [])):
        problems.append(f"数据源含 BaoStock（source={source}）")
    today_rows = int((df.index.normalize().date == END).sum())
    declared = df.attrs.get("today_missing_declared") is True
    warned = any("未取到今日分钟线" in r.getMessage() for r in records)
    now = datetime.now()
    if today_rows == 0 and is_trading_day(END, "cn_stock") and now.hour >= 9 and not declared:
        problems.append("未取到今日分钟线且未声明 today_missing_declared（禁止静默）")
    # 模拟回退子验证：字段是唯一判据（本段不读日志）
    sim_ok, sim_note = _simulate_today_fallback_field()
    if not sim_ok:
        problems.append(f"模拟回退帧未带 today_missing_declared（{sim_note}）")
    msg = (f"取 {today}: rows={len(df)} 今日根数={today_rows} source={source} "
           f"baostock调用={called['n']} 最新={df.index.max() if len(df) else '空'}"
           f" today_missing_declared={declared}"
           f"{'（已告警）' if warned else ''}"
           f"；模拟回退子验证[{sim_note}]"
           f"{'' if is_trading_day(END, 'cn_stock') else '（今天非交易日，仅验证未走 BaoStock）'}")
    return (not problems), (msg if not problems else f"{msg}；{'；'.join(problems)}")


def check_minute_gap_refill(fetcher: DataFetcher) -> tuple[bool, str]:
    """核实4：人为删除库中某一天的分钟数据，调用更新后该日缺口必须被补回。"""
    start = (END - timedelta(days=365 * 3)).strftime("%Y-%m-%d")
    first = fetcher.get_minute("600519", "60", start, END.strftime("%Y-%m-%d"))
    store_path = fetcher._minute_store_path("cn_stock", "600519", "60")
    store = fetcher._read_minute_store(store_path)
    if store is None or store.empty:
        return False, f"分钟库为空：{store_path}"

    days = sorted({d.date() for d in store.index.normalize().unique()
                   if d.date() < END - timedelta(days=5)})
    if not days:
        return False, "库内没有 5 天前的交易日可用于删除测试"
    victim = days[-1]
    before = int((store.index.normalize().date == victim).sum())
    fetcher._save_minute_store(store[store.index.normalize().date != victim], store_path)
    leftover = int((fetcher._read_minute_store(store_path).index.normalize().date == victim).sum())

    second = fetcher.get_minute("600519", "60", start, END.strftime("%Y-%m-%d"))
    after = int((second.index.normalize().date == victim).sum())
    gap_count = second.attrs.get("gap_count")
    gap_dates = second.attrs.get("gap_dates") or []

    problems = []
    if leftover:
        problems.append(f"删除失败，仍剩 {leftover} 根")
    if after != before:
        problems.append(f"{victim} 未补回（删除前 {before} 根，补回后 {after} 根）")
    if "gap_count" not in second.attrs or not isinstance(gap_dates, list):
        problems.append("attrs 缺 gap_count/gap_dates")
    msg = (f"库首次 {len(first)} 行；删除 {victim} 的 {before} 根 → 更新后 {after} 根，"
           f"gap_count={gap_count} gap_dates={gap_dates[:5]}")
    return (not problems), (msg if not problems else f"{msg}；{'；'.join(problems)}")


def check_factor_same_source(fetcher: DataFetcher) -> tuple[bool, str]:
    """核实5：A股日线与分钟线必须用同一因子源（BaoStock query_adjust_factor）。

    断言 1：日线 qfq/raw 收盘比值 ≡ foreAdjustFactor（最大绝对差 <1e-4）；
    断言 2：最近完成交易日 15:00 的 60 分钟 qfq 收盘 ≈ 当日日线 qfq 收盘（<0.1%）。
    """
    start = (END - timedelta(days=365 * 2)).strftime("%Y-%m-%d")
    end = END.strftime("%Y-%m-%d")
    qfq = fetcher.get_daily("600519", start, end, adjust="qfq")
    raw = fetcher.get_daily("600519", start, end, adjust="")
    factors = fetcher._fetch_baostock_adjust_factor("600519")
    if qfq.empty or raw.empty or factors.empty:
        return False, "日线或因子为空，无法比对"

    idx = qfq.index.intersection(raw.index)
    ratio = (qfq.loc[idx, "close"] / raw.loc[idx, "close"]).dropna()
    expect = {}
    for day in ratio.index:
        pos = factors.index[factors.index <= day]
        if len(pos):
            expect[day] = float(factors.loc[pos[-1], "qfq_factor"])
    common = [d for d in ratio.index if d in expect]
    max_diff = max((abs(float(ratio[d]) - expect[d]) for d in common), default=float("inf"))

    # 分钟 15:00 收盘 vs 日线 qfq 收盘（取最近完成交易日）
    minute = fetcher.get_minute("600519", "60", start, end)
    problems = []
    if max_diff >= 1e-4:
        problems.append(f"日线 qfq/raw 比值与 foreAdjustFactor 最大差 {max_diff:.3e}（>1e-4）")
    close1500 = minute[minute.index.strftime("%H:%M") == "15:00"]["close"]
    minute_days = [d for d in close1500.index.normalize().unique()
                   if d.date() < END and d in qfq.index]
    if not minute_days:
        problems.append("60 分钟线没有可用的 15:00 完成根")
        rel = None
    else:
        latest = max(minute_days)
        mc = float(close1500[close1500.index.normalize() == latest].iloc[-1])
        dc = float(qfq.loc[latest, "close"])
        rel = abs(mc - dc) / dc
        if rel >= 0.001:
            problems.append(f"{latest.date()} 15:00 分钟收盘 {mc} vs 日线 qfq {dc} 相对误差 {rel*100:.4f}%（>0.1%）")

    fsrc = factors["factor_source"].iloc[0] if "factor_source" in factors.columns else "unknown"
    msg = (f"因子源={fsrc}（行数 {len(factors)}）；"
           f"日线 qfq/raw 与 foreAdjustFactor 最大差 {max_diff:.2e}；"
           f"15:00 分钟 qfq 与日线 qfq 相对误差 "
           f"{'N/A' if rel is None else f'{rel*100:.5f}%'}")
    return (not problems), (msg if not problems else f"{msg}；{'；'.join(problems)}")


def check_crypto_backfill_attrs(fetcher: DataFetcher) -> tuple[bool, str]:
    """核实6：crypto 分钟单次回填上限与请求间隔必须写入 attrs（避免触发币安封禁）。"""
    df = fetcher.get_minute("BTC", "60", (END - timedelta(days=3)).strftime("%Y-%m-%d"),
                            END.strftime("%Y-%m-%d"))
    cap = df.attrs.get("backfill_cap_bars")
    interval = df.attrs.get("request_interval")
    problems = []
    if df.empty:
        problems.append("crypto 分钟线为空")
    if cap != 20000:
        problems.append(f"backfill_cap_bars={cap}，应为 20000")
    if not isinstance(interval, (int, float)) or float(interval) < 0.2:
        problems.append(f"request_interval={interval}，应 >=0.2s")
    msg = f"BTC 60分钟 {len(df)} 行，source={df.attrs.get('source')}，上限={cap} 根，间隔={interval}s"
    return (not problems), (msg if not problems else f"{msg}；{'；'.join(problems)}")


def check_daily_gap_detection(fetcher: DataFetcher) -> tuple[bool, str]:
    """核实二：日历开市但日线缺该日，必须识别为「日线缺口」（attrs daily_gap_dates + WARNING）。

    做法：用包装后的 get_daily 人为删掉某个交易日，再调用增量库更新，
    断言该日出现在 daily_gap_dates 且打印「疑似日线缺口」告警（不能当成休市静默跳过）。
    """
    start = (END - timedelta(days=365 * 2)).strftime("%Y-%m-%d")
    end = END.strftime("%Y-%m-%d")
    real_daily = fetcher.get_daily
    full = real_daily("600519", start, end, adjust="")
    if full is None or full.empty:
        return False, "日线为空，无法做删除测试"
    days = [d.date() for d in full.index if d.date() < END - timedelta(days=10)]
    if not days:
        return False, "日线没有足够早的交易日"
    victim = days[len(days) // 2]

    def _fake(symbol, s=None, e=None, *args, **kwargs):
        df = real_daily(symbol, s, e, *args, **kwargs)
        if str(symbol) in ("600519", "sh.600519") and df is not None and not df.empty:
            df = df[df.index.normalize().date != victim]
        return df

    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture(level=logging.WARNING)
    fetcher.logger.addHandler(handler)
    fetcher.get_daily = _fake
    try:
        out = fetcher.get_minute("600519", "60", start, end)
    finally:
        fetcher.get_daily = real_daily
        fetcher.logger.removeHandler(handler)

    gaps = out.attrs.get("daily_gap_dates") or []
    victim_s = victim.strftime("%Y-%m-%d")
    warned = any("疑似日线缺口" in r.getMessage() for r in records)
    problems = []
    if victim_s not in gaps:
        problems.append(f"未识别出日线缺口 {victim_s}（daily_gap_dates 前 5={gaps[:5]}）")
    if not warned:
        problems.append("未打印「疑似日线缺口」WARNING")
    if "daily_gap_count" not in out.attrs:
        problems.append("attrs 缺 daily_gap_count")
    msg = (f"人为删除日线 {victim_s} → daily_gap_count={out.attrs.get('daily_gap_count')} "
           f"命中={victim_s in gaps} 告警={warned}")
    return (not problems), (msg if not problems else f"{msg}；{'；'.join(problems)}")


def check_baostock_session_recovery(fetcher: DataFetcher) -> tuple[bool, str]:
    """核实三：BaoStock 会话失效（未登录/过期）必须自动重置会话、重登并重试一次。"""
    import core.data_fetcher as dfmod

    client = dfmod.bs
    if client is None:
        return False, "未安装 baostock"

    class _Expired:
        error_code = "10001001"
        error_msg = "用户未登录"
        fields: list = []

        def next(self):
            return False

    real_qaf = client.query_adjust_factor
    calls = {"n": 0}

    def _fake_qaf(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:  # 第一次模拟服务端会话过期
            return _Expired()
        return real_qaf(*args, **kwargs)

    real_cache_expired = fetcher._cache_expired
    client.query_adjust_factor = _fake_qaf
    fetcher._cache_expired = lambda path, kind: True  # 绕过因子缓存，强制真正查询
    try:
        factors = fetcher._fetch_baostock_adjust_factor("600519")
    finally:
        client.query_adjust_factor = real_qaf
        fetcher._cache_expired = real_cache_expired

    problems = []
    if calls["n"] < 2:
        problems.append(f"未触发重登重试（query_adjust_factor 调用 {calls['n']} 次）")
    if factors is None or factors.empty:
        problems.append("重登后仍未取到复权因子")
    msg = (f"首次返回「用户未登录」→ 重登重试，query_adjust_factor 调用 {calls['n']} 次，"
           f"因子 {0 if factors is None else len(factors)} 行")
    return (not problems), (msg if not problems else f"{msg}；{'；'.join(problems)}")


def main() -> int:
    print("=" * 72)
    print(f"第 1 步数据层测试  区间：{START} ~ {END}")
    print("=" * 72)
    fetcher = DataFetcher()

    results = []
    for title, symbol, kind in TARGETS:
        try:
            if kind == "option_chain":
                df = fetcher.get_option_chain(symbol)
            else:
                df = fetcher.get_daily(symbol, START.strftime("%Y-%m-%d"),
                                       END.strftime("%Y-%m-%d"))
            ok = df is not None and not df.empty
            results.append((title, symbol, ok, "" if ok else "返回空数据"))
            if ok:
                show(title, symbol, df)
            else:
                print(f"\n⚠️  【{title}】{symbol} 返回空数据")
        except Exception as exc:  # noqa: BLE001
            # v3.54 美股补测轮（评审裁定原文「未登记事件的美股标的保持
            # fail-closed raise，禁止降级跑回测」）：美股未登记 manual_events
            # 的标的被闸拦截属【预期正确行为】，按通过计数并标注，不再列待检查项
            if "manual_events" in str(exc):
                results.append((title, symbol, True,
                                "预期 fail-closed raise（manual_events 未登记，评审裁定）"))
                print(f"\n✅ 【{title}】{symbol} 预期 fail-closed raise（manual_events 未登记）")
                continue
            results.append((title, symbol, False, str(exc)))
            print(f"\n⚠️  【{title}】{symbol} 获取失败，跳过：{exc}")

    print("\n" + "=" * 72)
    print("汇总")
    print("=" * 72)
    ok_count = 0
    for title, symbol, ok, reason in results:
        ok_count += int(ok)
        flag = "✅" if ok else "❌"
        print(f"  {flag} {title:<10} {symbol:<10} {reason}")
    print(f"\n可用 {ok_count}/{len(results)}，缓存目录：{config.DATA_CACHE_DIR}")

    print("\n" + "=" * 72)
    print("自证核查（单位 / BaoStock 长历史 / 增量库 / 歧义代码 / 10年日线 / 列名 / 分钟线 / 市场覆盖）")
    print("=" * 72)
    checks = [
        ("核实1 单位(A股/ETF/转债)", check_units),
        ("BaoStock 3年60分钟长历史", check_minute_long_history),
        ("分钟增量库 attrs/落盘", check_minute_store),
        ("歧义代码 ZN", check_ambiguous_codes),
        ("核查3 10年日线", check_long_history),
        ("核查6 列名一致性", check_columns),
        ("核查6 分钟线", check_minute),
        ("核查4 市场覆盖", check_new_markets),
        ("核实2 分钟date+time根数", check_minute_bar_counts),
        ("核实3 取今天不走BaoStock", check_minute_today_no_baostock),
        ("核实4 增量库缺口补回", check_minute_gap_refill),
        ("核实5 分钟/日线因子同源", check_factor_same_source),
        ("核实6 crypto回填上限/间隔", check_crypto_backfill_attrs),
        ("核实二 日线缺口识别", check_daily_gap_detection),
        ("核实三 BaoStock会话自动恢复", check_baostock_session_recovery),
        ("核实7 指数市场接入", check_index_market),
        ("核实8 单点市场报错/备源回退", check_single_source_behavior),
        ("核实9 stale 交易日差/上限/回测豁免/下单复核", check_stale_policy),
        ("核实10 最近已收盘交易日按市场时钟", check_market_clock),
    ]
    failed_checks = []
    for name, func in checks:
        try:
            ok, msg = func(fetcher)
        except Exception as exc:  # noqa: BLE001
            ok, msg = False, f"{type(exc).__name__}: {exc}"
        print(f"  {'✅' if ok else '❌'} {name}: {msg}")
        if not ok:
            failed_checks.append(name)

    # v3.48 / 13.0.19 ③：实测原始数 vs 离线静态上界双报；实测超上界 = 口径异常
    passed = ok_count + (len(checks) - len(failed_checks))
    assert len(checks) == FIXED_CHECK_COUNT, (
        f"checks 列表 {len(checks)} 项 != FIXED_CHECK_COUNT={FIXED_CHECK_COUNT}："
        "增删核查项必须同步改静态常量，禁止上界漂移")
    # v3.49 / 13.0.20 ③：上界已钉成字面量，TARGETS 变动不再自动跟着缩水；
    # 两者一致性必须显式对齐，否则「TARGETS 删了一项」会静默把口径改小。
    assert len(TARGETS) + FIXED_CHECK_COUNT == DETERMINISTIC_BOUND, (
        f"len(TARGETS)={len(TARGETS)} + FIXED_CHECK_COUNT={FIXED_CHECK_COUNT} != "
        f"DETERMINISTIC_BOUND={DETERMINISTIC_BOUND}：改动标的表/核查项时必须同步改字面量上界")
    if passed > DETERMINISTIC_BOUND:
        print(f"\n❌ 实测原始数 {passed} 超过离线静态上界 DETERMINISTIC_BOUND="
              f"{DETERMINISTIC_BOUND}（observed_must_not_exceed_bound）：口径异常，视为不通过")
        return 1
    print(f"\n计数口径：实测原始数 {passed}（标的 {ok_count}/{len(results)} + 核查 "
          f"{len(checks) - len(failed_checks)}/{len(checks)}），"
          f"离线静态上界 DETERMINISTIC_BOUND={DETERMINISTIC_BOUND}"
          f"（字面量 19 + 15；等价于 FIXED_CHECK_COUNT={FIXED_CHECK_COUNT} + "
          f"len(TARGETS)={len(TARGETS)}）")

    failed = [r for r in results if not r[2]]
    if failed or failed_checks:
        print("\n需要检查的项目：")
        for title, symbol, _, reason in failed:
            print(f"  - 标的 {title} {symbol}: {reason}")
        for name in failed_checks:
            print(f"  - {name}")
        return 1
    print("\n全部检查通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
