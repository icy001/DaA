"""
统一配置文件（v3.3）
——交易规则、默认参数、风控阈值、行情/图表/缠论配置集中在这里
——**所有账号/密码/Token 放在 .env 文件，不要写到本文件**
"""
# ============================================================================
# 【重要约定】后续所有代码取用某个市场的交易规则参数时，必须统一调用
#   config.get_market_config(market_type)
# 禁止直接写 config.MARKETS[market_type]：
#   MARKETS 只包含 7 个零售市场（A股/ETF/美股/港股/可转债/国内期货），
#   其余 11 类市场存放在 GLOBAL_FUTURES / FOREX / OPTION / CRYPTO / PUBLIC_FUND /
#   REVERSE_REPO / CN_REITS / NEEQ / PRIVATE_FUND / QII_PRODUCT / OTC_DERIV 等独立字典中，
#   直接下标访问会触发 KeyError。
# ============================================================================
import os
from pathlib import Path

# ---------- 凭证加载（从 .env 读，不进代码仓库） ----------
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

def _get(name: str, default: str = "") -> str:
    val = os.environ.get(name, default)
    if name in os.environ:
        del os.environ[name]
    return val

# ==================== 路径 ====================
BASE_DIR = Path(__file__).parent
DATA_CACHE_DIR = BASE_DIR / "data_cache"
LOG_DIR = BASE_DIR / "logs"
REPORT_DIR = BASE_DIR / "reports"
BACKTEST_DIR = BASE_DIR / "backtest_results"
PAPER_DIR = BASE_DIR / "paper_trading"
LIVE_DIR = BASE_DIR / "live_trading"
RESEARCH_DIR = BASE_DIR / "research_output"
AUDIT_DIR = BASE_DIR / "audit_logs"
FACTOR_CACHE_DIR = DATA_CACHE_DIR / "factors"
SNAPSHOT_DIR = DATA_CACHE_DIR / "snapshots"
RAW_DATA_DIR = DATA_CACHE_DIR / "raw"
ADJ_FACTOR_DIR = DATA_CACHE_DIR / "adj_factors"
INDEX_MEMBER_DIR = DATA_CACHE_DIR / "index_members"
CONST_DATA_DIR = DATA_CACHE_DIR / "constituents"
for d in [DATA_CACHE_DIR, LOG_DIR, REPORT_DIR, BACKTEST_DIR, PAPER_DIR, LIVE_DIR,
          RESEARCH_DIR, AUDIT_DIR, FACTOR_CACHE_DIR, SNAPSHOT_DIR, RAW_DATA_DIR,
          ADJ_FACTOR_DIR, INDEX_MEMBER_DIR, CONST_DATA_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ==================== 凭证（从 .env 读取） ====================
TUSHARE_TOKEN       = _get("TUSHARE_TOKEN", "")
JOINQUANT_USERNAME  = _get("JOINQUANT_USERNAME", "")
JOINQUANT_PASSWORD  = _get("JOINQUANT_PASSWORD", "")
UQER_TOKEN          = _get("UQER_TOKEN", "")
WIND_ACCOUNT        = _get("WIND_ACCOUNT", "")
CHOICE_ACCOUNT      = _get("CHOICE_ACCOUNT", "")

WECHAT_WEBHOOK_KEY  = _get("WECHAT_WEBHOOK_KEY", "")
DINGTALK_WEBHOOK    = _get("DINGTALK_WEBHOOK", "")
DINGTALK_SECRET     = _get("DINGTALK_SECRET", "")
SERVERCHAN_SENDKEY  = _get("SERVERCHAN_SENDKEY", "")
EMAIL_HOST_USER     = _get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = _get("EMAIL_HOST_PASSWORD", "")
SMTP_HOST           = _get("SMTP_HOST", "smtp.qq.com")
SMTP_PORT           = int(_get("SMTP_PORT", "465"))
ALERT_EMAIL_TO      = _get("ALERT_EMAIL_TO", "")

QMT_PATH            = _get("QMT_PATH", "C:/qmt_mini")
QMT_ACCOUNT_ID      = _get("QMT_ACCOUNT_ID", "")
QMT_PASSWORD        = _get("QMT_PASSWORD", "")
QMT_SESSION_ID      = int(_get("QMT_SESSION_ID", "123456"))
QMT_MODE            = _get("QMT_MODE", "simulation")
QMT_BROKER_TYPE     = _get("QMT_BROKER_TYPE", "stock")

PTRADE_SERVER       = _get("PTRADE_SERVER", "")
PTRADE_USERNAME     = _get("PTRADE_USERNAME", "")
PTRADE_PASSWORD     = _get("PTRADE_PASSWORD", "")
PTRADE_ACCOUNT_ID   = _get("PTRADE_ACCOUNT_ID", "")

CTP_FRONT_ADDR_TRADE  = _get("CTP_FRONT_ADDR_TRADE", "tcp://180.168.146.187:10130")
CTP_FRONT_ADDR_MARKET = _get("CTP_FRONT_ADDR_MARKET", "tcp://180.168.146.187:10131")
CTP_BROKER_ID       = _get("CTP_BROKER_ID", "9999")
CTP_USER_ID         = _get("CTP_USER_ID", "")
CTP_PASSWORD        = _get("CTP_PASSWORD", "")
CTP_APP_ID          = _get("CTP_APP_ID", "simnow_client_test")
CTP_AUTH_CODE       = _get("CTP_AUTH_CODE", "0000000000000000")
CTP_PRODUCT_INFO    = _get("CTP_PRODUCT_INFO", "")
CTP_PROD_CODE       = _get("CTP_PROD_CODE", "")

IBKR_HOST           = _get("IBKR_HOST", "127.0.0.1")
IBKR_PORT           = int(_get("IBKR_PORT", "7497"))
IBKR_CLIENT_ID      = int(_get("IBKR_CLIENT_ID", "1"))

BINANCE_API_KEY     = _get("BINANCE_API_KEY", "")
BINANCE_API_SECRET  = _get("BINANCE_API_SECRET", "")
OKX_API_KEY         = _get("OKX_API_KEY", "")
OKX_API_SECRET      = _get("OKX_API_SECRET", "")
OKX_API_PASSPHRASE  = _get("OKX_API_PASSPHRASE", "")

LIVE_TRADING_ENABLED = _get("LIVE_TRADING_ENABLED", "false").lower() == "true"
BROKER_DEFAULT      = _get("BROKER_DEFAULT", "qmt")
CONFIRM_LIVE_KEYWORD = "YES_CONFIRM_LIVE_TRADING"

# ==================== 基础参数 ====================
INITIAL_CASH = 1_000_000
DEFAULT_START = "2020-01-01"
DEFAULT_END = ""
BENCHMARK = "000300"  # 沪深300作为默认基准

DATA_CACHE_EXPIRE_DAYS = {
    "daily": 7,
    "minute": 1,
    "realtime": 0,
}
REQUEST_DELAY = 0.3
REQUEST_TIMEOUT = 15
MAX_RETRY = 3

# ==================== 18类市场交易规则 ====================
MARKETS = {
    # 1. A股个股
    "cn_stock": {
        "name": "A股个股",
        "min_qty": 100,
        "qty_step": 100,
        "price_step": 0.01,
        "t_plus": 1,
        "trade_direction": ["long"],
        "commission_rate": 0.00025,
        "commission_min": 5,
        "stamp_tax_rate_sell": 0.0005,
        "stamp_tax_rate_buy": 0,
        "transfer_fee": 0.00001,
        "margin_rate": 1.0,
        "leverage": 1.0,
        "price_limit": {"main": 0.1, "st": 0.05, "kcb": 0.2, "cyb": 0.2, "bj": 0.3, "ipo": 0.44},
        "trading_hours": [(9*60+30, 11*60+30), (13*60, 15*60)],
        "can_short": False,
        "liquidity_min": 10_000_000,
    },
    # 2. A股场内ETF
    "cn_etf": {
        "name": "A股场内ETF",
        "min_qty": 100,
        "qty_step": 100,
        "price_step": 0.001,
        "t_plus": 1,
        "t0_prefixes": ["513", "518", "159920", "159941"],  # 跨境/黄金/部分商品T+0
        "trade_direction": ["long"],
        "commission_rate": 0.00005,
        "commission_min": 0,
        "stamp_tax_rate_sell": 0,
        "stamp_tax_rate_buy": 0,
        "transfer_fee": 0,
        "margin_rate": 1.0,
        "leverage": 1.0,
        "price_limit": {"default": 0.1, "cross_border": 0.2},
        "trading_hours": [(9*60+30, 11*60+30), (13*60, 15*60)],
        "can_short": False,
        "liquidity_min": 10_000_000,
    },
    # 3. 美股个股
    "us_stock": {
        "name": "美股个股",
        "min_qty": 1,
        "qty_step": 1,
        "price_step": 0.01,
        "t_plus": 0,
        "trade_direction": ["long", "short"],
        "commission_rate": 0,
        "commission_min": 0,
        "stamp_tax_rate_sell": 0,
        "stamp_tax_rate_buy": 0,
        "sec_fee_sell": 0.0000278,
        "taf_fee_sell": 0.000166,
        "margin_rate": 0.5,
        "leverage": 2.0,
        "pdt_min_equity": 25000,
        "pdt_max_day_trades": 3,
        "price_limit": None,
        "trading_hours": [(9*60+30, 16*60)],
        "can_short": True,
        "short_borrow_fee": 0.0003,
        "liquidity_min": 1_000_000,
    },
    # 4. 美股ETF
    "us_etf": {
        "name": "美股ETF",
        "min_qty": 1,
        "qty_step": 1,
        "price_step": 0.01,
        "t_plus": 0,
        "trade_direction": ["long", "short"],
        "commission_rate": 0,
        "commission_min": 0,
        "stamp_tax_rate_sell": 0,
        "margin_rate": 0.5,
        "leverage": 2.0,
        "price_limit": None,
        "trading_hours": [(9*60+30, 16*60)],
        "can_short": True,
        "liquidity_min": 1_000_000,
    },
    # 5. 港股
    "hk_stock": {
        "name": "港股个股/ETF",
        "min_lot": 100,
        "price_step_table": [(0.25, 0.001), (0.5, 0.005), (10, 0.01), (20, 0.02),
                             (100, 0.05), (200, 0.1), (500, 0.2), (1000, 0.5),
                             (2000, 1.0), (5000, 2.0), (9999, 5.0)],
        "t_plus": 0,
        "t_settle": 2,
        "trade_direction": ["long", "short"],
        "commission_rate": 0.0003,
        "commission_min_hkd": 3,
        "stamp_tax_rate_buy": 0.001,
        "stamp_tax_rate_sell": 0.001,
        "stamp_tax_min": 1,
        "sfc_levy": 0.000027,
        "trading_fee": 0.00005,
        "frc_levy": 0.0000015,
        "ccass_fee": 0.00002,
        "ccass_min": 2,
        "ccass_max": 100,
        "trading_system_fee": 0.5,
        "margin_rate": 0.5,
        "leverage": 2.0,
        "vcm_band": 0.1,
        "price_limit": None,
        "trading_hours": [(9*60+30, 12*60), (13*60, 16*60)],
        "can_short": True,
        "liquidity_min": 5_000_000,
    },
    # 6. 沪深可转债
    "cn_convertible": {
        "name": "沪深可转债",
        "min_qty": 10,
        "qty_step": 10,
        "price_step": 0.001,
        "t_plus": 0,
        "trade_direction": ["long"],
        "commission_rate": 0.00005,
        "commission_min": 0,
        "stamp_tax_rate_sell": 0,
        "transfer_fee": 0,
        "margin_rate": 1.0,
        "leverage": 1.0,
        "price_limit": 0.2,
        "first_day_limit": {"ceiling": 0.573, "floor": -0.433},
        "intraday_halt": {"first": 0.2, "first_minutes": 30, "second": 0.3, "second_close": True},
        "trading_hours": [(9*60+30, 11*60+30), (13*60, 15*60)],
        "convert_trigger": 0.3,
        "put_trigger": 0.3,
        "can_short": False,
    },
    # 7. 国内期货（品种级参数按品种覆盖）
    "cn_future": {
        "name": "国内期货",
        "min_lot": 1,
        "lot_step": 1,
        "t_plus": 0,
        "trade_direction": ["long", "short"],
        "open_close_mode": True,  # 区分开仓/平仓/平今
        "commission_type": "per_lot",  # per_lot 或 per_value
        "commission_per_lot_open": 0,
        "commission_per_lot_close": 0,
        "commission_per_lot_close_today": 0,
        "commission_rate_open": 0.000023,
        "commission_rate_close": 0.000023,
        "commission_rate_close_today": 0.00023,
        "settlement": True,
        "margin_rate": 0.10,
        "leverage": 10,
        "price_limit": 0.06,
        "force_close_line": 0.0,
        "can_hold_delivery_month": False,
        "roll_advance_days": 3,
        "trading_hours": [(9*60, 10*60+15), (10*60+30, 11*60+30), (13*60+30, 15*60)],
        "night_session": [],
        "can_short": True,
        "liquidity_min": 50_000_000,
    },
}

# ---------- 国内期货品种级参数 ----------
CN_FUTURES_VARIETY = {
    "RB": {"exchange": "SHFE", "multiplier": 10, "tick": 1, "margin_rate": 0.09,
           "commission_per_lot_open": 1, "commission_per_lot_close": 1,
           "commission_per_lot_close_today": 1, "commission_type": "per_lot",
           "price_limit": 0.07, "night_session": [(21*60, 23*60)]},
    "HC": {"exchange": "SHFE", "multiplier": 10, "tick": 1, "margin_rate": 0.09,
           "commission_per_lot_open": 1, "commission_per_lot_close": 1,
           "commission_per_lot_close_today": 1, "commission_type": "per_lot",
           "price_limit": 0.07, "night_session": [(21*60, 23*60)]},
    "CU": {"exchange": "SHFE", "multiplier": 5, "tick": 10, "margin_rate": 0.10,
           "commission_rate_open": 0.00005, "commission_rate_close": 0.00005,
           "commission_rate_close_today": 0.00005, "commission_type": "per_value",
           "price_limit": 0.06, "night_session": [(21*60, 1*60)]},
    "AL": {"exchange": "SHFE", "multiplier": 5, "tick": 5, "margin_rate": 0.10,
           "commission_rate_open": 0.00003, "commission_rate_close": 0.00003,
           "commission_rate_close_today": 0.00003, "commission_type": "per_value",
           "price_limit": 0.06, "night_session": [(21*60, 1*60)]},
    "ZN": {"exchange": "SHFE", "multiplier": 5, "tick": 5, "margin_rate": 0.10,
           "commission_rate_open": 3, "commission_rate_close": 3,
           "commission_rate_close_today": 3, "commission_type": "per_lot",
           "price_limit": 0.06, "night_session": [(21*60, 1*60)]},
    "AU": {"exchange": "SHFE", "multiplier": 1000, "tick": 0.02, "margin_rate": 0.08,
           "commission_rate_open": 0.00002, "commission_rate_close": 0.00002,
           "commission_rate_close_today": 0.00002, "commission_type": "per_value",
           "price_limit": 0.08, "night_session": [(21*60, 2*60+30)]},
    "AG": {"exchange": "SHFE", "multiplier": 15, "tick": 1, "margin_rate": 0.10,
           "commission_rate_open": 0.00005, "commission_rate_close": 0.00005,
           "commission_rate_close_today": 0.00005, "commission_type": "per_value",
           "price_limit": 0.08, "night_session": [(21*60, 2*60+30)]},
    "SC": {"exchange": "INE",  "multiplier": 1000, "tick": 0.1, "margin_rate": 0.10,
           "commission_rate_open": 20, "commission_rate_close": 20,
           "commission_rate_close_today": 20, "commission_type": "per_lot",
           "price_limit": 0.08, "night_session": [(21*60, 2*60+30)]},
    "FU": {"exchange": "SHFE", "multiplier": 10, "tick": 1, "margin_rate": 0.10,
           "commission_rate_open": 0.00005, "commission_rate_close": 0.00005,
           "commission_rate_close_today": 0.00005, "commission_type": "per_value",
           "price_limit": 0.10, "night_session": [(21*60, 23*60)]},
    "RU": {"exchange": "SHFE", "multiplier": 10, "tick": 5, "margin_rate": 0.10,
           "commission_rate_open": 3, "commission_rate_close": 3,
           "commission_rate_close_today": 3, "commission_type": "per_lot",
           "price_limit": 0.07, "night_session": [(21*60, 23*60)]},
    "NI": {"exchange": "SHFE", "multiplier": 1, "tick": 10, "margin_rate": 0.10,
           "commission_rate_open": 6, "commission_rate_close": 6,
           "commission_rate_close_today": 6, "commission_type": "per_lot",
           "price_limit": 0.08, "night_session": [(21*60, 1*60)]},
    "SS": {"exchange": "SHFE", "multiplier": 5, "tick": 5, "margin_rate": 0.10,
           "commission_rate_open": 3, "commission_rate_close": 3,
           "commission_rate_close_today": 3, "commission_type": "per_lot",
           "price_limit": 0.07, "night_session": [(21*60, 1*60)]},
    "A": {"exchange": "DCE",  "multiplier": 10, "tick": 1, "margin_rate": 0.08,
          "commission_rate_open": 2, "commission_rate_close": 2,
          "commission_rate_close_today": 2, "commission_type": "per_lot",
          "price_limit": 0.07, "night_session": [(21*60, 23*60)]},
    "M": {"exchange": "DCE",  "multiplier": 10, "tick": 1, "margin_rate": 0.08,
          "commission_rate_open": 1.5, "commission_rate_close": 1.5,
          "commission_rate_close_today": 1.5, "commission_type": "per_lot",
          "price_limit": 0.07, "night_session": [(21*60, 23*60)]},
    "Y": {"exchange": "DCE",  "multiplier": 10, "tick": 2, "margin_rate": 0.08,
          "commission_rate_open": 2.5, "commission_rate_close": 2.5,
          "commission_rate_close_today": 2.5, "commission_type": "per_lot",
          "price_limit": 0.07, "night_session": [(21*60, 23*60)]},
    "P": {"exchange": "DCE",  "multiplier": 10, "tick": 2, "margin_rate": 0.08,
          "commission_rate_open": 2.5, "commission_rate_close": 2.5,
          "commission_rate_close_today": 2.5, "commission_type": "per_lot",
          "price_limit": 0.07, "night_session": [(21*60, 23*60)]},
    "C": {"exchange": "DCE",  "multiplier": 10, "tick": 1, "margin_rate": 0.08,
          "commission_rate_open": 1.2, "commission_rate_close": 1.2,
          "commission_rate_close_today": 1.2, "commission_type": "per_lot",
          "price_limit": 0.07, "night_session": [(21*60, 23*60)]},
    "I": {"exchange": "DCE",  "multiplier": 100, "tick": 0.5, "margin_rate": 0.12,
          "commission_rate_open": 0.0001, "commission_rate_close": 0.0001,
          "commission_rate_close_today": 0.0001, "commission_type": "per_value",
          "price_limit": 0.10, "night_session": [(21*60, 23*60)]},
    "J": {"exchange": "DCE",  "multiplier": 100, "tick": 0.5, "margin_rate": 0.12,
          "commission_rate_open": 0.00006, "commission_rate_close": 0.00006,
          "commission_rate_close_today": 0.00006, "commission_type": "per_value",
          "price_limit": 0.10, "night_session": [(21*60, 23*60)]},
    "JM": {"exchange": "DCE", "multiplier": 60, "tick": 0.5, "margin_rate": 0.12,
           "commission_rate_open": 0.00006, "commission_rate_close": 0.00006,
           "commission_rate_close_today": 0.00006, "commission_type": "per_value",
           "price_limit": 0.10, "night_session": [(21*60, 23*60)]},
    "SR": {"exchange": "CZCE", "multiplier": 10, "tick": 1, "margin_rate": 0.07,
           "commission_rate_open": 3, "commission_rate_close": 3,
           "commission_rate_close_today": 3, "commission_type": "per_lot",
           "price_limit": 0.07, "night_session": [(21*60, 23*60)]},
    "CF": {"exchange": "CZCE", "multiplier": 5, "tick": 5, "margin_rate": 0.07,
           "commission_rate_open": 4.3, "commission_rate_close": 4.3,
           "commission_rate_close_today": 4.3, "commission_type": "per_lot",
           "price_limit": 0.07, "night_session": [(21*60, 23*60)]},
    "MA": {"exchange": "CZCE", "multiplier": 10, "tick": 1, "margin_rate": 0.08,
           "commission_rate_open": 1.4, "commission_rate_close": 1.4,
           "commission_rate_close_today": 1.4, "commission_type": "per_lot",
           "price_limit": 0.07, "night_session": [(21*60, 23*60)]},
    "TA": {"exchange": "CZCE", "multiplier": 5, "tick": 2, "margin_rate": 0.07,
           "commission_rate_open": 3, "commission_rate_close": 3,
           "commission_rate_close_today": 3, "commission_type": "per_lot",
           "price_limit": 0.07, "night_session": [(21*60, 23*60)]},
    "IF": {"exchange": "CFFEX","multiplier": 300, "tick": 0.2, "margin_rate": 0.10,
           "commission_rate_open": 0.000023, "commission_rate_close": 0.000023,
           "commission_rate_close_today": 0.000345, "commission_type": "per_value",
           "price_limit": 0.10, "trading_hours": [(9*60+30, 11*60+30), (13*60, 15*60)],
           "night_session": []},
    "IC": {"exchange": "CFFEX","multiplier": 200, "tick": 0.2, "margin_rate": 0.12,
           "commission_rate_open": 0.000023, "commission_rate_close": 0.000023,
           "commission_rate_close_today": 0.000345, "commission_type": "per_value",
           "price_limit": 0.10, "night_session": []},
    "IH": {"exchange": "CFFEX","multiplier": 300, "tick": 0.2, "margin_rate": 0.10,
           "commission_rate_open": 0.000023, "commission_rate_close": 0.000023,
           "commission_rate_close_today": 0.000345, "commission_type": "per_value",
           "price_limit": 0.10, "night_session": []},
    "IM": {"exchange": "CFFEX","multiplier": 200, "tick": 0.2, "margin_rate": 0.12,
           "commission_rate_open": 0.000023, "commission_rate_close": 0.000023,
           "commission_rate_close_today": 0.000345, "commission_type": "per_value",
           "price_limit": 0.10, "night_session": []},
    "T": {"exchange": "CFFEX","multiplier": 10000, "tick": 0.005, "margin_rate": 0.02,
           "commission_per_lot_open": 3, "commission_per_lot_close": 3,
           "commission_per_lot_close_today": 3, "commission_type": "per_lot",
           "price_limit": 0.02, "night_session": []},
    "SI": {"exchange": "GFEX", "multiplier": 15, "tick": 1, "margin_rate": 0.12,
           "commission_rate_open": 0.00005, "commission_rate_close": 0.00005,
           "commission_rate_close_today": 0.00005, "commission_type": "per_value",
           "price_limit": 0.08, "night_session": [(21*60, 2*60+30)]},
    "LC": {"exchange": "GFEX", "multiplier": 1, "tick": 1, "margin_rate": 0.12,
           "commission_per_lot_open": 1, "commission_per_lot_close": 1,
           "commission_per_lot_close_today": 1, "commission_type": "per_lot",
           "price_limit": 0.08, "night_session": [(21*60, 23*60)]},
}

def get_future_variety_params(symbol: str):
    variety = ''.join([c for c in symbol if c.isalpha()]).upper()
    p = MARKETS["cn_future"].copy()
    if variety in CN_FUTURES_VARIETY:
        p.update(CN_FUTURES_VARIETY[variety])
    return p

# ---------- 8. 国际期货 ----------
GLOBAL_FUTURES = {
    "GC": {"exchange": "COMEX", "name": "黄金", "multiplier": 100, "tick": 0.1, "margin": 10890, "ccy": "USD",
           "commission": 2.5, "night_session": True, "trading_hours_24h": True},
    "SI": {"exchange": "COMEX", "name": "白银", "multiplier": 5000, "tick": 0.005, "margin": 11550, "ccy": "USD"},
    "CL": {"exchange": "NYMEX", "name": "WTI原油", "multiplier": 1000, "tick": 0.01, "margin": 5940, "ccy": "USD"},
    "NG": {"exchange": "NYMEX", "name": "天然气", "multiplier": 10000, "tick": 0.001, "margin": 2750, "ccy": "USD"},
    "HG": {"exchange": "COMEX", "name": "铜", "multiplier": 25000, "tick": 0.0005, "margin": 6600, "ccy": "USD"},
    "ES": {"exchange": "CME",  "name": "标普500", "multiplier": 50, "tick": 0.25, "margin": 13200, "ccy": "USD"},
    "NQ": {"exchange": "CME",  "name": "纳指100", "multiplier": 20, "tick": 0.25, "margin": 17600, "ccy": "USD"},
    "YM": {"exchange": "CBOT", "name": "道指", "multiplier": 5, "tick": 1, "margin": 13200, "ccy": "USD"},
    "RTY": {"exchange": "CME", "name": "罗素2000", "multiplier": 50, "tick": 0.1, "margin": 7150, "ccy": "USD"},
    "ZB": {"exchange": "CBOT", "name": "30年美债", "multiplier": 1000, "tick": 0.03125, "margin": 4620, "ccy": "USD"},
    "ZN": {"exchange": "CBOT", "name": "10年美债", "multiplier": 1000, "tick": 0.015625, "margin": 2420, "ccy": "USD"},
    "ZC": {"exchange": "CBOT", "name": "玉米", "multiplier": 50, "tick": 0.25, "margin": 1320, "ccy": "USD"},
    "ZW": {"exchange": "CBOT", "name": "小麦", "multiplier": 50, "tick": 0.25, "margin": 2310, "ccy": "USD"},
    "ZS": {"exchange": "CBOT", "name": "大豆", "multiplier": 50, "tick": 0.25, "margin": 3300, "ccy": "USD"},
    "CT": {"exchange": "ICE",  "name": "棉花", "multiplier": 500, "tick": 0.01, "margin": 2200, "ccy": "USD"},
    "SB": {"exchange": "ICE",  "name": "11号糖", "multiplier": 112000, "tick": 0.01, "margin": 1760, "ccy": "USD"},
    "CC": {"exchange": "ICE",  "name": "可可", "multiplier": 10, "tick": 1, "margin": 3300, "ccy": "USD"},
    "KC": {"exchange": "ICE",  "name": "咖啡", "multiplier": 375, "tick": 0.05, "margin": 4950, "ccy": "USD"},
}

# ---------- 9. 外汇保证金 ----------
FOREX = {
    "leverage": 100,
    "margin_call": 0.8,
    "stop_out": 0.5,
    "spread_pips_default": 1.5,
    "swap_rate": {"long": -0.5, "short": 0.3},  # 隔夜利息（按日，单位：点）
    "trading_hours_24h": True,
    "min_lot": 0.01,
    "lot_size": 100_000,
    "tick_per_pip": 10,
    "ccy_pairs": {
        "EURUSD": {"pip_pos": 4, "spread_pips": 1.2, "commission_per_lot": 0},
        "GBPUSD": {"pip_pos": 4, "spread_pips": 1.5, "commission_per_lot": 0},
        "USDJPY": {"pip_pos": 2, "spread_pips": 1.3, "commission_per_lot": 0},
        "USDCHF": {"pip_pos": 4, "spread_pips": 1.8, "commission_per_lot": 0},
        "AUDUSD": {"pip_pos": 4, "spread_pips": 1.3, "commission_per_lot": 0},
        "USDCAD": {"pip_pos": 4, "spread_pips": 1.5, "commission_per_lot": 0},
        "NZDUSD": {"pip_pos": 4, "spread_pips": 1.6, "commission_per_lot": 0},
        "XAUUSD": {"pip_pos": 2, "spread_pips": 30, "commission_per_lot": 0, "name": "黄金"},
        "XAGUSD": {"pip_pos": 3, "spread_pips": 30, "commission_per_lot": 0, "name": "白银"},
    },
}

# ---------- 10. 场内期权 ----------
OPTION = {
    "contract_multiplier": 10000,
    "option_types": ["call", "put"],
    "exercise_style": "european",
    "risk_free_rate": 0.025,
    "buyer_max_loss": "premium_paid",
    "seller_margin_rate": {"call": 0.12, "put": 0.07},
    "commission_per_contract": 3,
    "min_commission": 5,
    "price_limit": {"etf_option": 0.5, "index_option": 0.1},
    "circuit_breaker": True,
    "expiration_days_reminder": 5,
    "auto_exercise_profit_threshold": 100,
}

# ---------- 11. 加密货币 ----------
CRYPTO = {
    "trading_hours_24h": True,
    "min_order_usd": 10,
    "maker_fee": 0.001,
    "taker_fee": 0.001,
    "futures_leverage_max": 125,
    "funding_rate_interval_hours": 8,
    "margin_call": 0.8,
    "stop_out": 0.5,
    "assets": {
        "BTC": {"min_qty": 0.00001, "tick": 0.01},
        "ETH": {"min_qty": 0.001, "tick": 0.01},
        "BNB": {"min_qty": 0.01, "tick": 0.001},
        "SOL": {"min_qty": 0.01, "tick": 0.001},
    },
}

# ---------- 12. 场外公募基金 ----------
PUBLIC_FUND = {
    "subscribe_fee_rate": 0.0015,
    "subscribe_fee_discount": 0.1,
    "redeem_fee_by_days": [
        (7, 0.015), (30, 0.0075), (365, 0.005), (730, 0.0025), (99999, 0)
    ],
    "management_fee_rate": 0.015,
    "custodian_fee_rate": 0.0025,
    "sales_service_fee_rate": 0.004,
    "nav_cutoff_time": (15, 0),
    "t_plus_confirm": 1,
    "t_plus_redeem": {
        "stock": 3, "bond": 2, "money": 1, "qdii": 7
    },
    "fund_type_default": "stock",
}

# ---------- 13. 国债逆回购 ----------
REVERSE_REPO = {
    "threshold_sh": 100000,
    "threshold_sz": 1000,
    "multiple_sh": 100000,
    "multiple_sz": 1000,
    "commission_rate": {
        1: 0.00001, 2: 0.00002, 3: 0.00003, 4: 0.00004, 7: 0.00005,
        14: 0.0001, 28: 0.0002, 28: 0.0002, 91: 0.0003, 182: 0.0003
    },
    "high_yield_threshold": 0.03,
    "auto_scan_default": True,
}

# ---------- 14. 私募证券基金 ----------
PRIVATE_FUND = {
    "qii_threshold_current_individual_financial_assets": 3_000_000,
    "qii_threshold_current_individual_income": 500_000,
    "qii_threshold_draft_individual_family_assets": 5_000_000,
    "qii_threshold_draft_individual_family_net_assets": 3_000_000,
    "qii_threshold_draft_individual_income": 500_000,
    "qii_threshold_draft_experience_years": 2,
    "qii_threshold_draft_special_family_assets": 10_000_000,
    "qii_threshold_draft_special_family_net_assets": 6_000_000,
    "qii_threshold_draft_special_experience_years": 4,
    "qii_threshold_institution": 10_000_000,
    "min_investment": 1_000_000,
    "management_fee_rate": 0.02,
    "performance_fee_rate": 0.20,
    "high_water_mark": True,
    "lockup_period_days": 180,
    "redemption_fee_by_days": [(365, 0.03), (730, 0.02), (99999, 0)],
    "nav_update_freq_days": 7,
}

# ---------- 15. 资管/信托/私募理财 ----------
QII_PRODUCT = {
    "qii_threshold_amr_family_financial_assets": 5_000_000,
    "qii_threshold_amr_family_net_assets": 3_000_000,
    "qii_threshold_amr_income": 400_000,
    "min_investment": {"fixed_income": 300_000, "mixed": 400_000, "equity": 1_000_000, "derivatives": 1_000_000},
    "trust_natural_persons_below_3m_cap": 50,
    "trust_term_years": (1, 5),
}

# ---------- 16. 新三板 ----------
NEEQ = {
    "min_qty": 100,
    "qty_step": 100,
    "price_step": 0.01,
    "t_plus": 1,
    "qii_threshold_base": 2_000_000,
    "qii_threshold_innovation": 1_000_000,
    "price_limit": {"base": 0.5, "innovation": 0.3},
    "commission_rate": 0.001,
    "stamp_tax_rate_sell": 0.0005,
    "trading_hours": [(9*60+30, 11*60+30), (13*60, 15*60)],
    "call_auction_times": [(9*60+30, 9*60+30+10), (11*60+30, 13*60), (14*60+50, 15*60)],
    "survivorship_bias_warning": True,
    "liquidity_min": 1_000_000,
}

# ---------- 17. 公募REITs ----------
CN_REITS = {
    "min_qty": 100,
    "qty_step": 100,
    "price_step": 0.001,
    "t_plus": 1,
    "commission_rate": 0.0002,
    "stamp_tax_rate_sell": 0,
    "price_limit": 0.3,
    "first_day_limit": 0.3,
    "mandatory_dividend_payout_ratio": 0.9,
    "dividend_frequency": "quarterly",
    "premium_discount_warning": 0.2,
    "trading_hours": [(9*60+30, 11*60+30), (13*60, 15*60)],
}

# ---------- 18. 场外衍生品（仅定价模拟，禁止个人实盘） ----------
OTC_DERIV = {
    "forbidden_for_individual_live_trading": True,
    "rule_effective_date": "2026-11-16",
    "qualified_threshold_net_asset": 50_000_000,
    "qualified_threshold_experience_years": 3,
    "qualified_threshold_financial_assets": 20_000_000,
    "bs_model": True,
    "monte_carlo_paths": 50000,
    "binomial_steps": 200,
    "snowball_pricing_engine": "monte_carlo",
    "greeks": ["delta", "gamma", "vega", "theta", "rho"],
    "primary_otc_dealers": [
        "中信证券", "中信建投", "中金公司", "华泰证券", "申万宏源", "国泰君安", "招商证券", "广发证券"
    ],
    "futures_otc_risk_subsidiaries": [
        "中信中证资本", "永安资本", "国泰君安风险管理", "海通资源", "浙商惠风", "华泰长城资本", "东证润和"
    ],
}

# ==================== 策略默认参数 ====================
STRATEGY_DEFAULTS = {
    "ma_short": 5,
    "ma_long": 20,
    "rsi_period": 14,
    "rsi_overbought": 70,
    "rsi_oversold": 30,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "bollinger_period": 20,
    "bollinger_std": 2.0,
    "atr_period": 14,
    "atr_stop": 2.0,
    "kdj_n": 9,
    "kdj_m1": 3,
    "kdj_m2": 3,
    "position_pct": 0.2,
    "stop_loss_pct": 0.08,
    "take_profit_pct": 0.20,
    "trailing_stop_pct": 0.0,
    "rebalance_freq": "weekly",
}

# ==================== 回测默认参数 ====================
BACKTEST_DEFAULTS = {
    "initial_cash": INITIAL_CASH,
    "benchmark": BENCHMARK,
    "slippage_pct": 0.0005,
    "adjust": "qfq",
    "enable_fee": True,
    "plot_result": True,
    "save_html": True,
    "save_trades_csv": True,
}

# ==================== 模拟盘参数 ====================
PAPER_TRADING = {
    "data_freq": "1min",
    "bar_delay_seconds": 0,
    "initial_cash": INITIAL_CASH,
    "reconcile_eod": True,
    "auto_log_daily": True,
}

# ==================== 盯盘/推送 ====================
MONITOR = {
    "check_interval_seconds": 30,
    "pre_market_check_minutes": 15,
    "post_market_settle": True,
    "push_channels": ["console"],  # wechat/dingtalk/serverchan/email 按需加入
    "heartbeat_interval_minutes": 10,
}

# ==================== 图表 / K线 ====================
CHART_CONFIG = {
    "up_color": "#ef4444",        # 红涨（A股习惯）
    "down_color": "#22c55e",      # 绿跌
    "up_color_us": "#22c55e",
    "down_color_us": "#ef4444",
    "ma_colors": ["#f59e0b", "#8b5cf6", "#06b6d4", "#64748b"],
    "volume_alpha": 0.3,
    "default_ma": [5, 10, 20, 60],
    "enable_bollinger": False,
    "enable_volume": True,
    "enable_pattern": True,
    "pattern_golden_cross": True,
    "pattern_death_cross": True,
    "pattern_breakout": True,
    "pattern_divergence": True,
    "annotation_offset_pct": 0.005,
    "multi_plot_max": 4,
    "indicator_subplot": "macd",   # macd / kdj / rsi / boll / none
    "use_plotly_if_available": True,
    "font_candidates": [
        "Noto Sans CJK SC", "Microsoft YaHei", "SimHei", "PingFang SC",
        "WenQuanYi Zen Hei", "Arial Unicode MS"
    ],
    "plot_periods": ["1d", "1w", "1M", "60min", "30min", "15min", "5min"],
}

# ==================== 缠论配置 ====================
CHAN_CONFIG = {
    "enable_fenxing": True,
    "enable_bi": True,
    "enable_duan": False,
    "enable_zhongshu": True,
    "enable_buy_sell_points": False,
    "bi_type": "new",              # new=新笔(允许顶底之间一根K线)  old=老笔
    "bi_min_k": 5,
    "duan_min_bi": 3,
    "zhongshu_overlap_ratio": 0.5,
    "color_bi": "#facc15",
    "color_duan": "#fb923c",
    "color_zs": "#3b82f6",
    "color_b1": "#22c55e",
    "color_b2": "#16a34a",
    "color_b3": "#15803d",
    "color_s1": "#ef4444",
    "color_s2": "#dc2626",
    "color_s3": "#b91c1c",
}

# ==================== 风控参数（实盘核心） ====================
RISK = {
    "account": {
        "max_position_pct_per_trade": 0.10,
        "max_open_count_per_day": 20,
        "max_cancel_count_per_day": 30,
        "daily_loss_pct_stop": 0.05,
        "max_drawdown_pct_stop": 0.10,
        "max_leverage": {"stock": 1.0, "future": 3.0, "forex": 5.0, "crypto": 3.0},
        "max_single_symbol_pct": 0.20,
        "max_single_industry_pct": 0.30,
    },
    "order": {
        "price_deviation_pct_reject": 0.02,
        "liquidity_min_amount": 10_000_000,
        "t_plus_one_enforce": True,
        "margin_check": True,
        "block_zdt_reverse_open": True,
        "night_session_only_close": False,
    },
    "compliance": {
        "block_self_trade": True,
        "abnormal_order_reject": True,
        "frequent_order_warning_ratio": 0.8,
    },
}

# ==================== 第13步 数据/报告长期可用性配置 ====================
DATA_LONG_TERM = {
    "data_source_priority": ["akshare", "tushare", "local"],
    "data_source_failover": True,
    "save_raw": True,                  # 原始不复权价落盘
    "save_adj_factor": True,           # 复权因子单独落盘
    "default_adjust_for_backtest": "qfq",
    "cache_format": "parquet",
    "cache_compression": "snappy",
    "enable_data_version": True,
    "data_manifest_file": "data_cache/data_manifest.json",
    "integrity_check": True,           # 文件MD5/行数校验
    "cache_retention_days": 365,
    "cold_archive_days": 30,
    "cold_compress": True,
    "snapshot_every_run": True,        # 每次回测保存数据快照
    "snapshot_format": "parquet",
    "point_in_time_index": True,       # 时点成分股（防幸存者偏差）
    "pit_index_update_days": ["03-01", "06-01", "09-01", "12-01"],  # 季度调整
    "reconcile_reports_daily": True,
}

REPORT_LONG_TERM = {
    "index_file": "reports/report_index.json",
    "archive_by_month": True,
    "store_structured_data": True,     # 同时存 JSON/parquet
    "inline_plotly_js": True,          # 不依赖CDN，离线可用
    "pdf_export_optional": True,
    "retention_days_daily": 365,
    "retention_days_weekly": 1095,
    "retention_days_monthly": 2190,
    "retention_days_backtest": 2190,
    "push_after_generate": False,
    "meta_required_fields": [
        "report_id", "type", "generated_at", "strategy_name", "strategy_params",
        "data_version", "data_range", "symbols", "market"
    ],
}

# ==================== 第13步 凭证与安全 ====================
SECURITY = {
    "env_file": ".env",
    "dotenv_required": True,
    "mask_secret_logs": True,
    "mask_keep_chars": 3,
    "audit_log_retention_days": 365 * 2,
    "fail_open_when_env_missing": False,  # 缺凭证直接报错，不允许默认空字符串跑实盘
    "live_trading_double_confirm": True,
}

# ==================== 代码自动识别市场 ====================
MARKET_CODE_RULES = {
    "us_stock":     {"prefix": [], "suffix": [], "alphas_6_only": False, "numeric": False},
    "hk_stock":     {"prefix": ["0"], "numeric_5": True},
    "cn_reits":     {"prefix": ["508", "180"]},
    "cn_convertible":{"prefix": ["11", "123", "127", "128", "113", "110", "111", "123"]},
    "cn_etf":       {"prefix": ["51", "52", "56", "58", "15", "16", "18"]},
    "neeq":         {"prefix": ["43", "83", "87", "88", "92"]},
    "cn_future":    {"letter_digit_mix": True},
    "global_future":{"letter_only": True, "max_len": 3},
    "forex":        {"6_letter_ccy": True},
    "crypto":       {"letter_only": True, "min_len": 2, "max_len": 5},
    "option":       {"suffix_pattern": True},
}

def detect_market_type(code: str, market_type: str = None) -> str:
    """根据代码前缀/格式自动识别市场类型，返回 config.MARKETS 的 key。

    显式传入 market_type 时直接返回该值（用于私募/资管/场外衍生品等非标准代码，
    以及 GC 这类美股/国际期货存在歧义的品种）。

    注意：6位A股/ETF/基金/转债的代码段本身存在歧义（如00开头既可能是深市个股也可能是基金），
    纯字母短代码（2-3位）在美股/期货/加密之间也存在歧义。本函数按"最常见场景"给出默认值，
    遇到歧义时请在调用处显式传入 market_type 参数覆盖。
    """
    if market_type:
        return str(market_type).strip().lower()

    code = str(code).strip().upper()

    # ===== A股6位数字 =====
    if len(code) == 6 and code.isdigit():
        p3, p2 = code[:3], code[:2]
        # 国债逆回购：204开头（沪）、1318开头（深）
        if p3.startswith("204") or p3.startswith("131"):
            return "cn_reverse_repo"
        # 公募REITs：508/180开头
        if p3 in ("508",) or p3.startswith("180"):
            return "cn_reits"
        # 新三板：43/83/87/88/92开头
        if p2 in ("43", "83", "87", "88") or p2.startswith("92"):
            return "neeq"
        # 可转债：11开头/123/127/128/113/110/111开头
        if p2 in ("11",) or p3 in ("123", "127", "128", "113", "110", "111"):
            return "cn_convertible"
        # 场内/场外基金：519开头（沪市场内基金段，非ETF，如519066汇添富蓝筹稳健）
        if p3 == "519":
            return "cn_fund"
        # 场内ETF：51/52/56/58开头（沪市段），15/18开头（深市段）
        # 注意：16开头是LOF基金段，不是ETF
        if p2 in ("51", "52", "56", "58") or p2 in ("15", "18"):
            return "cn_etf"
        # 深市个股：000/001/002/003开头（深市主板+原中小板）
        if p3 in ("000", "001", "002", "003"):
            return "cn_stock"
        # 场外公募基金：004~009开头（场外号段）、16开头（LOF）
        if p3 in ("004", "005", "006", "007", "008", "009") or p2 == "16":
            return "cn_fund"
        # 其余（30/60/68开头等）默认A股个股
        return "cn_stock"

    # ===== A股期权：8位数字（如上交所期权 1000xxxx）=====
    if len(code) == 8 and code.isdigit() and code.startswith("1"):
        return "cn_option"
    if len(code) >= 8 and code.isalpha() is False and any(c.isalpha() for c in code) and code[-1].upper() in ('C', 'P'):
        return "cn_option"

    # 港股：5位纯数字，0开头
    if len(code) == 5 and code.isdigit() and code.startswith("0"):
        return "hk_stock"

    # 国内期货：字母+数字混合（如 rb2501、IF2512）
    if any(ch.isalpha() for ch in code) and any(ch.isdigit() for ch in code):
        return "cn_future"

    # ===== 纯字母品种：按长度+白名单区分 =====
    if code.isalpha():
        L = len(code)
        # 外汇：6位且前3/后3都是货币代码
        if L == 6:
            fx_pairs = {"EUR", "GBP", "USD", "JPY", "CHF", "AUD", "CAD", "NZD",
                        "XAU", "XAG", "XPT", "XPD", "HKD", "SGD", "CNH"}
            if code[:3] in fx_pairs and code[3:] in fx_pairs:
                return "forex"
        # 国际期货白名单（最常见品种）
        known_futures = {
            "GC", "SI", "CL", "NG", "HG", "ES", "NQ", "YM", "RTY",
            "ZB", "ZN", "ZC", "ZW", "ZS", "CT", "SB", "CC", "KC",
            "PL", "PA", "HO", "BZ", "HE", "LE", "DX", "RB", "GF"
        }
        # 加密货币主流币白名单（避免和期货代码冲突）
        known_crypto = {
            "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "DOT",
            "AVAX", "MATIC", "LINK", "LTC", "UNI", "ATOM", "FIL",
            "TRX", "ETC", "XLM", "XMR", "EOS", "BCH", "NEAR", "APT",
            "ARB", "OP", "SUI", "SEI", "TON"
        }
        # 常见3字母美股ETF（3位段歧义最大：美股/期货/加密都有3字母，这里显式列出最常见的）
        known_us_etf = {
            "SPY", "QQQ", "DIA", "IWM", "GLD", "SLV", "USO", "TLT",
            "HYG", "LQD", "XLF", "XLK", "XLE", "XLV", "XLI", "XLP",
            "XLU", "XLB", "XLY", "XLC", "XLRE", "VXX", "UVXY", "ARKK",
        }
        # 常见3字母美股个股
        known_us_stock = {
            "F", "GM", "GE", "IBM", "JPM", "BAC", "WFC", "C", "GS",
            "MS", "USB", "AXP", "V", "MA", "KO", "PEP", "MCD", "NKE",
            "SBUX", "T", "VZ", "DIS", "NFLX", "WMT", "TGT", "COST",
            "HD", "LOW", "CVX", "XOM", "COP", "BA", "CAT", "DE",
            "MRK", "PFE", "JNJ", "UNH", "ABBV", "LLY", "BMY", "AMD",
            "INTC", "NVDA",  # 注：NVDA其实是4位，这里只是保险
        }
        if code in known_crypto:
            return "crypto"
        if code in known_futures:
            return "global_future"
        if code in known_us_etf:
            return "us_etf"
        if code in known_us_stock:
            return "us_stock"
        # 4位及以上纯字母：默认美股个股（A股/港股/期货/外汇都已在上面规则处理）
        if L >= 4:
            return "us_stock"
        # 2-3位纯字母：美股代码数量远大于国际期货品种，默认按美股个股处理；
        # 国际期货品种请调用方显式传入 market_type="global_future" 覆盖。
        return "us_stock"

    # 带连字符/点的代码，默认美股（如 BRK.B）
    if "." in code or "-" in code:
        return "us_stock"

    # 兜底归入场外公募基金（建议显式指定 market_type）
    return "cn_fund"

# ==================== 统一市场参数访问（18类全覆盖） ====================
MARKET_CONFIG_MAP = {
    "cn_stock":        ("MARKETS", "cn_stock"),
    "cn_etf":          ("MARKETS", "cn_etf"),
    "us_stock":        ("MARKETS", "us_stock"),
    "us_etf":          ("MARKETS", "us_etf"),
    "hk_stock":        ("MARKETS", "hk_stock"),
    "cn_convertible":  ("MARKETS", "cn_convertible"),
    "cn_future":       ("MARKETS", "cn_future"),
    "global_future":   ("GLOBAL_FUTURES", None),
    "forex":           ("FOREX", None),
    "cn_option":       ("OPTION", None),
    "crypto":          ("CRYPTO", None),
    "cn_fund":         ("PUBLIC_FUND", None),
    "cn_reverse_repo": ("REVERSE_REPO", None),
    "cn_reits":        ("CN_REITS", None),
    "neeq":            ("NEEQ", None),
    "private_fund":    ("PRIVATE_FUND", None),
    "qii_product":     ("QII_PRODUCT", None),
    "otc_deriv":       ("OTC_DERIV", None),
}
ALL_MARKET_TYPES = list(MARKET_CONFIG_MAP)

def get_market_config(market_type: str) -> dict:
    """统一获取18类市场中任一市场的交易规则参数，禁止后续代码直接写 config.MARKETS[...]。"""
    entry = MARKET_CONFIG_MAP.get(market_type)
    if entry is None:
        raise KeyError(f"未知市场类型: {market_type}，可用市场: {ALL_MARKET_TYPES}")
    dict_name, sub_key = entry
    d = globals()[dict_name]
    return d if sub_key is None else d[sub_key]

# ==================== 运行模式（不要在这里改，用命令行参数控制） ====================
RUN_MODE = "backtest"
