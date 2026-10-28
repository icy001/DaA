"""通用工具模块

提供日志、网络重试、交易日判断、交易时段、数字格式化、自然日计算等基础能力，
供数据层、策略层、回测与实盘模块复用。

【重要约定】后续所有代码取用某个市场的交易规则参数时，必须统一调用
config.get_market_config(market_type)，禁止直接写 config.MARKETS[market_type]：
MARKETS 只包含 7 个零售市场，其余 11 类市场（国际期货/外汇/期权/加密/公募基金/
逆回购/REITs/新三板/私募/资管/场外衍生品）在独立字典中，直接下标访问会 KeyError。
"""
from __future__ import annotations

import functools
import logging
import math
import time
from datetime import date as _date
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple, Union

try:  # 中国节假日（A股/港股/期货日历的基础）
    from chinese_calendar import is_holiday as _cn_is_holiday
except ImportError:  # 依赖未安装时退化为仅按周末判断
    _cn_is_holiday = None

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None  # type: ignore

DateLike = Union[str, _date, datetime]

# ==================== 市场分组 ====================
CN_MARKETS = {
    "cn_stock", "cn_etf", "cn_convertible", "cn_future", "cn_option",
    "cn_fund", "cn_reits", "neeq", "cn_reverse_repo", "cn_index",
}
HK_MARKETS = {"hk_stock", "hk_etf"}
US_MARKETS = {"us_stock", "us_etf"}
FX_MARKETS = {"forex"}
CRYPTO_MARKETS = {"crypto"}
GLOBAL_FUTURE_MARKETS = {"global_future"}
# 净值型/非标准化产品：没有盘中交易，只按工作日更新净值
NAV_MARKETS = {"private_fund", "asset_management", "otc_deriv", "trust"}

MARKET_NAMES = {
    "cn_stock": "A股个股",
    "cn_etf": "A股场内ETF",
    "us_stock": "美股个股",
    "us_etf": "美股ETF",
    "hk_stock": "港股个股/ETF",
    "cn_convertible": "沪深可转债",
    "cn_future": "国内期货",
    "global_future": "国际期货",
    "forex": "外汇保证金",
    "cn_option": "场内期权",
    "crypto": "加密货币",
    "cn_fund": "场外公募基金",
    "cn_reverse_repo": "国债逆回购",
    "private_fund": "私募证券基金",
    "asset_management": "券商资管/信托/私募理财",
    "neeq": "新三板",
    "cn_reits": "公募REITs",
    "otc_deriv": "场外衍生品",
}

# ==================== 日期与节假日 ====================

# 港股相对 A 股额外的休市日（农历节日无法用公历规则推导，按年维护；未覆盖年份退回 A 股日历）
HK_EXTRA_HOLIDAYS = {
    2025: {
        "2025-01-01", "2025-01-29", "2025-01-30", "2025-01-31",
        "2025-04-04", "2025-04-18", "2025-04-21", "2025-05-01",
        "2025-05-05", "2025-07-01", "2025-10-01", "2025-10-07",
        "2025-10-29", "2025-12-25", "2025-12-26",
    },
    2026: {
        "2026-01-01", "2026-02-17", "2026-02-18", "2026-02-19",
        "2026-04-03", "2026-04-06", "2026-04-07", "2026-05-01",
        "2026-05-25", "2026-07-01", "2026-10-01", "2026-10-19",
        "2026-10-20", "2026-12-25",
    },
    2027: {
        "2027-01-01", "2027-02-06", "2027-02-08", "2027-02-09",
        "2027-03-26", "2027-03-29", "2027-05-01", "2027-05-13",
        "2027-06-09", "2027-07-01", "2027-10-01", "2027-10-08",
        "2027-12-25", "2027-12-27",
    },
}


def _to_date(value: DateLike) -> _date:
    """把 str / date / datetime 统一成 date。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, _date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"无法解析日期: {value!r}")


def _tz(name: str):
    """获取时区对象；环境缺少 tzdata 时返回 None（使用 naive datetime）。"""
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(name)
    except Exception:
        return None


def _at(day: _date, hour: int, minute: int = 0, tz_name: str = "Asia/Shanghai") -> datetime:
    """构造带时区的 datetime；分钟数超过 60 时自动进位。"""
    dt = datetime(day.year, day.month, day.day) + timedelta(hours=hour, minutes=minute)
    tz = _tz(tz_name)
    return dt.replace(tzinfo=tz) if tz else dt


def _easter_sunday(year: int) -> _date:
    """计算复活节（用于美股 Good Friday、港股复活节假期）。"""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return _date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> _date:
    """某月第 n 个星期 weekday（weekday: 0=周一 … 6=周日）。"""
    first = _date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> _date:
    """某月最后一个星期 weekday。"""
    if month == 12:
        last = _date(year, 12, 31)
    else:
        last = _date(year, month + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: _date) -> _date:
    """美国节假日遇周末的顺延/提前规则（周六→周五，周日→周一）。"""
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _us_holidays(year: int) -> set:
    """美股（NYSE/Nasdaq）休市日。"""
    return {
        _observed(_date(year, 1, 1)),                    # 元旦
        _nth_weekday(year, 1, 0, 3),                     # 马丁·路德·金日
        _nth_weekday(year, 2, 0, 3),                     # 总统日
        _easter_sunday(year) - timedelta(days=2),        # 耶稣受难日
        _last_weekday(year, 5, 0),                       # 阵亡将士纪念日
        _observed(_date(year, 6, 19)),                   # 六月节
        _observed(_date(year, 7, 4)),                    # 独立日
        _nth_weekday(year, 9, 0, 1),                     # 劳动节
        _nth_weekday(year, 11, 3, 4),                    # 感恩节
        _observed(_date(year, 12, 25)),                  # 圣诞节
    }


def _is_cn_trading_day(day: _date) -> bool:
    """A 股交易日：周一至周五且不是中国法定节假日（调休上班日也不开市）。"""
    if day.weekday() >= 5:
        return False
    if _cn_is_holiday is None:
        return True
    try:
        return not _cn_is_holiday(day)
    except Exception:  # chinesecalendar 未覆盖的年份
        return True


def is_trading_day(date: DateLike, market: str = "cn_stock") -> bool:
    """判断指定市场在给定日期是否开市。

    - A 股/期货/期权/可转债/基金/REITs/新三板/逆回购：中国节假日
    - 港股：中国节假日 + 港股额外休市日
    - 美股/美股 ETF：NYSE 节假日规则
    - 外汇：周一至周五 24 小时
    - 加密货币：7×24
    - 国际期货：周一至周五（CME Globex 仅圣诞/元旦全天休市）
    - 私募/资管/信托/场外衍生品：按工作日更新净值
    """
    day = _to_date(date)
    market = (market or "cn_stock").lower()

    if market in CRYPTO_MARKETS:
        return True
    if market in FX_MARKETS:
        return day.weekday() < 5
    if market in US_MARKETS:
        return day.weekday() < 5 and day not in _us_holidays(day.year)
    if market in HK_MARKETS:
        if day.weekday() >= 5:
            return False
        if str(day) in HK_EXTRA_HOLIDAYS.get(day.year, set()):
            return False
        return _is_cn_trading_day(day)
    if market in GLOBAL_FUTURE_MARKETS:
        if day.weekday() >= 5:
            return False
        return day not in {_date(day.year, 1, 1), _date(day.year, 12, 25)}
    if market in NAV_MARKETS:
        return day.weekday() < 5
    # 中国品种（含未知市场默认按 A 股处理）
    return _is_cn_trading_day(day)


# ==================== 交易时段 ====================

def get_trading_sessions(market: str = "cn_stock", date: DateLike = None) -> List[Tuple[datetime, datetime]]:
    """返回指定市场指定日期的交易时段列表 [(开始, 结束), ...]。

    - A 股股票/ETF/可转债/期权/逆回购/REITs：09:30-11:30、13:00-15:00
    - 国内期货：09:00-11:30、13:30-15:00，另有夜盘 21:00-23:00（夜盘归属下一交易日）
    - 港股：09:30-12:00、13:00-16:00
    - 美股：09:30-16:00（America/New_York，自动处理夏令时/冬令时）
    - 国际期货：CME 近全天（前一日 17:00 至当日 16:00，America/Chicago）
    - 外汇/加密货币：24 小时连续
    - 私募/资管等净值型产品：无盘中时段，返回空列表
    返回的 datetime 均带市场所在时区；非交易日返回空列表。
    """
    day = _to_date(date) if date is not None else _date.today()
    market = (market or "cn_stock").lower()

    if market in NAV_MARKETS:
        return []
    if market in CRYPTO_MARKETS:
        return [(_at(day, 0, 0, "UTC"), _at(day + timedelta(days=1), 0, 0, "UTC"))]

    if not is_trading_day(day, market):
        return []

    if market in FX_MARKETS:
        return [(_at(day, 0, 0, "UTC"), _at(day + timedelta(days=1), 0, 0, "UTC"))]

    if market in US_MARKETS:
        return [(_at(day, 9, 30, "America/New_York"), _at(day, 16, 0, "America/New_York"))]

    if market in HK_MARKETS:
        return [
            (_at(day, 9, 30, "Asia/Hong_Kong"), _at(day, 12, 0, "Asia/Hong_Kong")),
            (_at(day, 13, 0, "Asia/Hong_Kong"), _at(day, 16, 0, "Asia/Hong_Kong")),
        ]

    if market in GLOBAL_FUTURE_MARKETS:
        # CME Globex：前一日 17:00 开盘，当日 16:00 收盘（含跨日）
        return [
            (_at(day, 0, 0, "America/Chicago"), _at(day, 16, 0, "America/Chicago")),
            (_at(day, 17, 0, "America/Chicago"), _at(day + timedelta(days=1), 0, 0, "America/Chicago")),
        ]

    if market == "cn_future":
        return [
            (_at(day, 9, 0, "Asia/Shanghai"), _at(day, 11, 30, "Asia/Shanghai")),
            (_at(day, 13, 30, "Asia/Shanghai"), _at(day, 15, 0, "Asia/Shanghai")),
            # 夜盘：品种不同收盘时间不同（23:00/01:00/02:30），这里给出通用 21:00-23:00
            (_at(day, 21, 0, "Asia/Shanghai"), _at(day, 23, 0, "Asia/Shanghai")),
        ]

    # A 股及其衍生品种
    return [
        (_at(day, 9, 30, "Asia/Shanghai"), _at(day, 11, 30, "Asia/Shanghai")),
        (_at(day, 13, 0, "Asia/Shanghai"), _at(day, 15, 0, "Asia/Shanghai")),
    ]


# ==================== 日志 ====================

def setup_logger(name: str = "quant", log_file: Optional[Union[str, Path]] = None,
                 level: int = logging.INFO) -> logging.Logger:
    """配置日志：同时输出到控制台与文件，带时间戳和级别。

    未指定 log_file 时默认写入 logs/{name}.log；重复调用不会重复添加 handler。
    """
    if log_file is None:
        try:
            import config
            log_file = Path(config.LOG_DIR) / f"{name}.log"
        except Exception:
            log_file = Path("logs") / f"{name}.log"
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    target = str(log_file.resolve())
    for handler in list(logger.handlers):
        if isinstance(handler, logging.FileHandler) and handler.baseFilename == target:
            return logger  # 已配置过同一个日志文件

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


# ==================== 网络重试 ====================

def retry_request(func=None, max_retry: int = 3, delay: float = 1.0):
    """通用重试装饰器：网络请求失败时按递增延迟重试。

    用法：
        @retry_request
        def fetch(): ...

        @retry_request(max_retry=5, delay=0.5)
        def fetch(): ...
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            logger = logging.getLogger(fn.__module__)
            last_error = None
            for attempt in range(1, max_retry + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001 - 重试需要捕获所有异常
                    last_error = exc
                    if attempt >= max_retry:
                        logger.error("%s 重试 %d 次仍失败: %s", fn.__name__, max_retry, exc)
                        break
                    wait = delay * attempt  # 递增延迟：delay, 2*delay, 3*delay ...
                    logger.warning("%s 第 %d 次失败: %s，%.2fs 后重试",
                                   fn.__name__, attempt, exc, wait)
                    time.sleep(wait)
            raise last_error
        return wrapper

    if func is not None and callable(func):
        return decorator(func)
    return decorator


# ==================== 数字与日期计算 ====================

def format_number(num: Optional[float], decimals: int = 2) -> str:
    """数字格式化：大数字用 万 / 亿 / 万亿 表示。"""
    if num is None:
        return "-"
    try:
        value = float(num)
    except (TypeError, ValueError):
        return str(num)
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "∞" if value > 0 else "-∞"

    sign = "-" if value < 0 else ""
    abs_value = abs(value)
    for base, unit in ((1e12, "万亿"), (1e8, "亿"), (1e4, "万")):
        if abs_value >= base:
            return f"{sign}{abs_value / base:,.{decimals}f}{unit}"
    return f"{sign}{abs_value:,.{decimals}f}"


def cal_natural_days(start: DateLike, end: DateLike) -> int:
    """计算两个日期之间的自然日天数（end - start）。

    包含起始日还是结束日由调用方决定，本函数只返回差值：
    如 2024-01-01 到 2024-01-02 返回 1；国债逆回购计息、基金持有期可在此基础上 +1。
    """
    return (_to_date(end) - _to_date(start)).days


def market_name(market: str) -> str:
    """返回市场类型的中文名称。"""
    return MARKET_NAMES.get((market or "").lower(), market)


__all__ = [
    "setup_logger",
    "retry_request",
    "is_trading_day",
    "get_trading_sessions",
    "format_number",
    "cal_natural_days",
    "market_name",
    "MARKET_NAMES",
]
