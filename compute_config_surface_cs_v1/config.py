"""
统一配置文件（v3.51）
——交易规则、默认参数、风控阈值、行情/图表/缠论配置集中在这里
——**所有账号/密码/Token 放在 .env 文件，不要写到本文件**
"""
import os
import sys
from pathlib import Path

# ============================================================
# 规格版本自校验（v3.33 新增，硬要求）
# —— config.py 与指令集《Trae多市场量化系统搭建指令集.md》必须同版本
# —— 启动 / check-config 时由 core/loader 读取并与指令集顶部版本头比对
# —— 版本不一致时 fail-closed，不允许运行（避免"副本不同步"导致的静默偏差）
# ============================================================
SPEC_VERSION = "v3.51"

# ---------- 规格版本自校验（v3.35：分模式闸门 + 内容锚点） ----------
# v3.33 教训：把校验文件【钉死】单名 → 副本「另存为」即必然 raise（守卫的输入不存在）。
# v3.34 修正：改 glob 多候选（*指令集*.md），把「文件名会漂移」这个易失载体从校验链摘掉。
# v3.35 修正（本轮，两处结构缺陷）：
#   ① 【装错位置会自锁】——若对所有模式 raise，则 stale spec 一旦存在，连 check-config
#      （修它的命令）、report show、backtest 都跑不起来 → 闸门锁死了修复它自己的工具。
#      改为【分模式】：钱路径（live/paper）fail-closed；研究路径放行 + 粘性水印；
#      工具路径（含 check-config 自身）永不失败。
#   ② 【版本号是字符串 = fail-open】——只比版本号可被手改 / 遗忘 / 被「另存为」带走；
#      必须同时校验规格正文存在内容锚点（13.0 / 13.13）。
SPEC_VERSION_CHECK = {
    "enforce_on_startup": True,
    "enforce_in_check_config": True,
    "enforce_modes_strict": ["live", "paper"],       # 对不上 → raise（钱路径 fail-closed）
    "enforce_modes_warn": ["backtest", "research", "tooling"],
    "on_mismatch": {
        "live": "raise",
        "paper": "raise",
        "backtest": "warn_and_watermark",            # 放行，但报告 meta 打粘性水印
        "research": "warn_and_watermark",
        "tooling": "warn_only",                      # 含 check-config / report / stats：只警告，绝不砖掉
    },
    "self_lockout_guard": True,                      # spec_check 自身与 check-config 永不因版本不符而失败
    "command_file_globs": ["*指令集*.md"],           # v3.34：不再钉死单一文件名
    "version_header_marker": "<!-- spec_version:",   # 指令集顶部机器可读版本头
    "must_contain_markers": ["13.0 开工前置", "13.0.13", "13.0.14", "13.0.15", "13.0.16", "13.0.17", "13.0.18", "13.0.19", "13.0.20", "13.0.21", "13.0.22", "13.13 收尾总检"],  # v3.35 立；v3.43 增 13.0.13；v3.44 增 13.0.14/13.0.15；v3.45 增 13.0.16（数据源适配器 fail-closed）；v3.46 增 13.0.17（13.1 守卫位置/对象错位）；v3.47 增 13.0.18（自证/静默缩减）；v3.48 增 13.0.19（逐套件计数/证据源独立性/draft 默认拒绝）；v3.49 增 13.0.20（surface 算法钉死/基线锚峰值/账本全覆盖/模式矩阵枚举）；v3.50 增 13.0.21（算法机械化+黄金向量/AST 采集/白名单完备性/峰值证据/迁移校验/账本链）
    "on_marker_missing": "warn",
    "on_file_not_found": "raise_with_guidance",      # 找不到规格文件 → 报错并提示「去哪取最新规格」
    "allow_suffix": ["-draft"],
    "watermark_field": "spec_version_mismatch",
    "watermark_is_sticky": True,                     # 随报告进归档库与 stats，不得被后续流程抹掉
    # ---- v3.40：【版本号是字符串】这条缝，glob + 内容锚点仍不够 ----
    #   教训：Trae 本轮把「反向白名单」这类内容变更【并进 v3.38】，理由是该版尚未投递。
    #   一旦 v3.38 同时对应两份不同内容，跨副本比对【字符串相同 -> 判定通过 = 假绿】：
    #   SPEC_VERSION 机制在它诞生后的第一个真实场景里就失效了。
    #   根因：版本号是【人手维护的标签】，会漂移、会复用；机器要验的必须是【内容】。
    "content_hash_required": True,                   # 机器验内容哈希（人看版本号，机器看哈希）
    "content_hash_file": "spec_content.sha256",      # 与指令集同目录；内容 = 指令集正文 sha256
    "content_hash_algo": "sha256",
    "hash_scope": "instruction_doc_body",            # 对正文计算，避免自引用
    "on_content_hash_mismatch": "raise",             # 内容变而哈希未更新 -> 报错（即使版本号相同）
    "on_content_hash_missing": "warn",               # 尚未生成哈希时只警告（便于首轮落地）
    "version_number_never_reused": True,             # 同一版本号【不得】对应两份不同内容；改内容必须换号
}

# ---------- 规格出处治理（v3.46 新增）：哈希闸门不能「自证」 ----------
#   病（本轮实测）：施工方在自己机器上【自撰】了 13.0.16 节正文，再【自己重算并登记】哈希，
#       于是 check-config 转绿。但哈希闸门原本防的是「正文被偷改 / 旧副本混用」——一旦
#       「作者」与「登记者」是同一个人，它只能证明「这个文件没被人改过」，不能证明
#       「这个文件是权威规格」。闸门自证。
#   一句话：规格正文必须【单源发布】——施工方可以施工，但不能自撰规格并自己登记哈希。
SPEC_PROVENANCE = {
    "authority": "reviewer",                      # 规格正文的唯一权威来源（看守者）
    "local_selfauthored_is_draft": True,          # 施工方自撰的正文只能算 draft
    "draft_hash_file": "spec_drafts.sha256",      # draft 哈希登记在【与权威哈希不同的】文件
    "draft_check_result": "warn_yellow",          # draft 通过 check-config 只给黄，不给绿
    "forbid_draft_as_authority": True,            # 禁止把 draft 冒充权威正文
    "on_draft_and_authority_both_present": "raise",
    "must_report_delivery_gap": True,             # 交付缺口必须显式上报，不得以自撰正文掩盖
}

# ---------- 规格草稿权限（v3.47 新增）：draft 必须是【权限】，不是【颜色】 ----------
#   病（v3.46 实施后暴露）：SPEC_PROVENANCE 把施工方自撰的正文标成 draft、check-config 给黄，
#       但 draft 仍 exit=0 —— 也就【不阻断任何东西】。于是 authority 只是一行打印，自撰规格
#       照样能解锁实盘。这与 SPEC_VERSION_CHECK 的分模式闸门是同一件事：规格的「权威性」必须
#       落到【能不能启动钱路径】上，而不是落到控制台颜色上。
SPEC_DRAFT_PERMISSION = {
    "enabled": True,
    "draft_authority": "draft_self_authored",     # 与 SPEC_PROVENANCE.draft_hash_file 配套
    "draft_never_unlocks_live": True,             # 自撰规格【永不】解锁实盘类模式
    "mode_matrix": {                              # 与 SPEC_VERSION_CHECK.enforce_modes_* 同构
        "live": "raise",
        "live_sim": "raise",
        "paper": "raise",
        "backtest": "warn_and_watermark",
        "research": "warn_and_watermark",
        "tooling": "warn_only",                   # 含 check-config 自身：永不因 draft 而失败
    },
    "self_lockout_guard": True,                   # draft 判定不得锁死修复它自己的工具
    "banner_sticky": True,
    "watermark_field": "spec_provenance_draft",
    "watermark_is_sticky": True,
    # ---- v3.48：模式矩阵本身是【会漂移的白名单】 ----
    #   病：mode_matrix 是「逐模式列举」的白名单——只列了 6 个模式。**没被列出的模式怎么办，
    #       它没说**：新加一个模式（如 live_remote / sandbox / replay），它既不在 raise 组、
    #       也不在 warn 组 → 实现方要么 KeyError，要么「查不到就当放行」。
    #       这与本会话反复出现的「清单枚举不完 = fail-open」同族（信号出口清单 / 标的池清单 /
    #       允许关闭闸门的开关清单，全都是这个形状）。默认行为必须是【拒绝】，不是【放行】。
    #   一句话：**权限矩阵的默认值是 deny，不是 allow。**
    "mode_matrix_default": "deny",                # v3.48：未在 mode_matrix 列出的模式一律拒绝
    "unknown_mode_action": "raise",               # 未登记模式 → raise（不静默当 tooling 放行）
    # ---- v3.49：「模式」集合必须封闭；CLI 任意字符串都必须被 valid_modes 先验接住 ----
    #   病：unknown_mode_action="raise" 只在【查矩阵 miss】时触发；但 RUN_MODE 可来自 CLI --mode / .env 笔误，
    #     若代码某处做 .get(mode, matrix_default) 兜底、或 .strip()/.lower() 后再查，miss 可能不发生；
    #     矩阵没定义「合法模式全集」，"unknown" 的判定完全依赖实现细节。
    #   一句话：**必须显式登记【合法模式全集】；不在全集里的任何字符串 → 在查矩阵之前就 raise。**
    "valid_mode_set_required": True,               # 合法模式必须显式列举，不得靠矩阵键集隐式定义
    "valid_modes": ["backtest", "research", "paper", "live", "live_sim", "tooling"],
    "invalid_mode_action": "raise",                # RUN_MODE ∉ valid_modes → raise（矩阵查询之前先验）
    "cli_mode_argument_validated": True,           # CLI --mode 参数必须走 valid_modes 校验
    "self_lockout_exemption_is_enumerated": True,  # 唯一豁免面（check-config 自身）必须显式登记
    "self_lockout_exemption_modes": ["tooling"],
}

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

# ==================== 数据层标准约定（第1步核心，务必遵守） ====================
# 所有 get_daily / get_minute 返回的 DataFrame：
#   - 索引：date（datetime，升序，去重）
#   - 标准列：STANDARD_COLUMNS
#   - 标记列：EXTRA_FLAG_COLUMNS
#   - 附加信息：DataFrame.attrs（含 source / adjust / volume_unit / amount_estimated 等）
STANDARD_COLUMNS = ["open", "high", "low", "close", "volume", "amount"]
EXTRA_FLAG_COLUMNS = ["is_suspended", "is_missing"]
DATE_INDEX_NAME = "date"

# ---------- 对外强制统一单位 ----------
# volume：A股/ETF/港股/美股 = 股(份)；可转债 = 张；期货 = 手（保留，不换算）
# amount：元/港元/美元（原币种，不做汇率换算）；期货与部分接口无成交额时为 NaN
UNIFIED_VOLUME_UNIT = {
    "cn_stock": "股", "cn_etf": "份", "cn_fund": "份", "cn_convertible": "张",
    "cn_reits": "份", "hk_stock": "股", "us_stock": "股", "us_etf": "股",
    "cn_future": "手", "global_future": "手", "crypto": "币",
    "cn_index": "手",
}
UNIFIED_AMOUNT_UNIT = "native_currency"  # 元 / 港元 / 美元，原币种

# ---------- 数据源原始单位与复权约定表 ----------
# 结构：接口名 -> {volume_unit, amount_unit, volume_factor, native_adjust, kline_limit, note}
#   volume_unit   : 该接口「原始返回」的成交量单位
#   amount_unit   : 该接口「原始返回」的成交额单位（None 表示无此字段）
#   volume_factor : 换算到标准 volume 单位需要乘的系数（期货保留手，固定 1）
#   native_adjust : 该接口原生返回的复权口径（none/qfq/hfq/nav）
#   kline_limit   : 单次可取的最大 K 线条数（None 表示无限制）
#
# ⚠️ 铁律一：单位必须「按接口硬编码」，禁止用 amount/(close*volume) 自动反推后再改口径。
# ⚠️ 铁律二：不要凭记忆写单位。AKShare 内部同市场不同接口的单位就不一样（历史=股、快照=手）。
DATA_SOURCE_UNITS = {
    # ---------- A股 ----------
    "stock_zh_a_hist":      {"volume_unit": "手",  "amount_unit": "元", "volume_factor": 100, "native_adjust": "none", "kline_limit": None, "note": "东财·历史：成交量=【手】，必须×100。实测与新浪同日成交量恰为×100关系；AKShare官方示例 volume×100×close≈amount"},
    "stock_zh_a_daily":     {"volume_unit": "股",  "amount_unit": "元", "volume_factor": 1,   "native_adjust": "none", "kline_limit": None, "note": "新浪·历史（备用源）：成交量=股"},
    "stock_zh_a_spot_em":   {"volume_unit": "手",  "amount_unit": "元", "volume_factor": 100, "native_adjust": "none", "kline_limit": None, "note": "东财·实时快照（注意是手）"},
    # ---------- 指数（基准/择时，不可直接交易） ----------
    "index_zh_a_hist":      {"volume_unit": "手",  "amount_unit": "元",  "volume_factor": 100, "native_adjust": "none", "kline_limit": None, "note": "东财·A股指数日线：取数走专用接口，禁止复用个股接口"}, 
    "stock_zh_index_daily": {"volume_unit": "股",  "amount_unit": None,  "volume_factor": 1,   "native_adjust": "none", "kline_limit": None, "note": "新浪·指数日线（全历史备用源）"}, 
    "index_zh_a_hist_min_em": {"volume_unit": "手", "amount_unit": "元", "volume_factor": 100, "native_adjust": "none", "kline_limit": None, "note": "东财·指数分钟线（约 1 个月上限）"}, 
    "baostock_index_daily": {"volume_unit": "股",  "amount_unit": "元",  "volume_factor": 1,   "native_adjust": "optional", "kline_limit": None, "note": "BaoStock·指数日线（sh.000300 / sz.399001），仅日线，分钟线不含指数"}, 
    # ⚠️ 指数成交量单位必须交叉验证：指数【不适用】 amount/(close×volume) 自检
    #    （指数点位 × 股数 没有换算关系，比值必然离谱，不是单位错）。
    #    验证方法：用 BaoStock 指数日线（volume=股、amount=元，官方字段，实测 amount/(close×volume)≈1.0）
    #    与新浪【同指数、同一天】的 volume 比对：
    #      比值 ≈ 1   → 新浪指数 volume 也是「股」，须 ÷100 转「手」
    #      比值 ≈ 100 → 新浪指数 volume 本身就是「手」，【不得再 ÷100】（否则偏小 100 倍）
    #    未验证通过前，指数 volume 必须标 attrs["unit_uncertain"]=True，禁止默认假定。
    "stock_zh_index_daily_tx": {"volume_unit": "股", "amount_unit": None, "volume_factor": 1, "native_adjust": "none", "kline_limit": None, "note": "腾讯·指数日线（备用源）。⚠️字段陷阱：该接口 amount 列实为【成交量(手)】，不是成交额，禁止当 amount 使用（实测 == 新浪 volume÷100）"},
    # ---------- ETF / 基金 ----------
    "fund_etf_hist_em":     {"volume_unit": "手",  "amount_unit": "元", "volume_factor": 100, "native_adjust": "none", "kline_limit": None, "note": "东财·ETF历史（单位以官方文档为准，勿猜）"},
    "fund_etf_hist_sina":   {"volume_unit": "份",  "amount_unit": "元", "volume_factor": 1,   "native_adjust": "none", "kline_limit": None, "note": "新浪·ETF历史（备用源，不支持复权）"},
    "reits_hist_em":        {"volume_unit": "手",  "amount_unit": "元", "volume_factor": 100, "native_adjust": "none", "kline_limit": None, "note": "东财·REITs历史（单位待官方确认）"},
    "fund_open_fund_info_em": {"volume_unit": None, "amount_unit": None, "volume_factor": 0,  "native_adjust": "nav",  "kline_limit": None, "note": "场外基金净值，无成交量/成交额"},
    # ---------- 港美股 ----------
    "stock_hk_hist":        {"volume_unit": "股",  "amount_unit": "港元", "volume_factor": 1, "native_adjust": "none", "kline_limit": None, "note": "港股日线"},
    "stock_hk_spot_em":     {"volume_unit": "股",  "amount_unit": "港元", "volume_factor": 1, "native_adjust": "none", "kline_limit": None, "note": "港股实时"},
    "stock_us_hist":        {"volume_unit": "股",  "amount_unit": "美元", "volume_factor": 1, "native_adjust": "none", "kline_limit": None, "note": "美股日线"},
    "stock_us_spot_em":     {"volume_unit": "股",  "amount_unit": "美元", "volume_factor": 1, "native_adjust": "none", "kline_limit": None, "note": "美股实时"},
    # ---------- 可转债 ----------
    "bond_zh_hs_cov_daily": {"volume_unit": "张",  "amount_unit": None,  "volume_factor": 1, "native_adjust": "none", "kline_limit": None, "note": "可转债日线，无成交额字段→用 close×volume 估算并标注"},
    # ---------- 期货 ----------
    "futures_main_sina":    {"volume_unit": "手",  "amount_unit": None,  "volume_factor": 1, "native_adjust": "none", "kline_limit": None, "note": "国内期货主力，保留手不换算"},
    "futures_zh_minute_sina": {"volume_unit": "手", "amount_unit": None, "volume_factor": 1, "native_adjust": "none", "kline_limit": None, "note": "期货分钟，保留手"},
    # ---------- 期权 ----------
    "option_sse_daily":     {"volume_unit": "张",  "amount_unit": "元",  "volume_factor": 1, "native_adjust": "none", "kline_limit": None, "note": "ETF期权日线"},
    # ---------- 实时 / 分钟 ----------
    "sina_hq_realtime":     {"volume_unit": "股",  "amount_unit": "元",  "volume_factor": 1, "native_adjust": "none", "kline_limit": None, "note": "新浪 hq.sinajs.cn 实时，字段8=股、字段9=元"},
    "sina_kline_minute":    {"volume_unit": "股",  "amount_unit": "元",  "volume_factor": 1, "native_adjust": "none", "kline_limit": 1970, "note": "新浪 getKLineData：实测为【不复权】（分钟收盘==不复权日线收盘）；A股上限1970根、期货/外汇1023根，且无时间游标→无法分页，只能取『最近N根』并标注 capped"},
    # ---------- BaoStock（免费，分钟线长历史主力源） ----------
    "baostock_daily":       {"volume_unit": "股",  "amount_unit": "元",  "volume_factor": 1, "native_adjust": "optional", "kline_limit": None, "note": "BaoStock·日线：volume=股、amount=元（官方文档明确）；adjustflag 1=后复权/2=前复权/3=不复权"},
    "baostock_minute":      {"volume_unit": "股",  "amount_unit": "元",  "volume_factor": 1, "native_adjust": "optional", "kline_limit": None, "note": "BaoStock·5/15/30/60分钟：免费、长历史（1990起）、支持前/后复权；【分钟线不含指数】"},
    # ---------- 加密货币 ----------
    "binance_klines":       {"volume_unit": "币",  "amount_unit": "计价货币", "volume_factor": 1, "native_adjust": "none", "kline_limit": 1000, "note": "币安K线，limit≤1000 需分页"},
    # ---------- 备用（若启用 Tushare） ----------
    "tushare_daily":        {"volume_unit": "手",  "amount_unit": "千元", "volume_factor": 100, "native_adjust": "none", "kline_limit": None, "note": "Tushare daily：成交量手、成交额千元（注意与 AKShare 不同）"},
}

# 期货的 amount 不适用（各品种合约乘数不同，不能用 close×volume 估算成交额）
FUTURES_AMOUNT_NOT_APPLICABLE = True

# 分钟线数据源优先级（长历史优先 baostock；无 baostock 覆盖的品种走新浪 + 自建增量库）
MINUTE_SOURCE_PRIORITY = {
    # baostock 仅提供【盘后】数据、且不覆盖指数/ETF/REITs/可转债；
    # 因此 cn_stock 仅在"历史回填"场景优先 baostock，"当日/实时"必须回落 sina/eastmoney
    "cn_stock":      ["baostock", "sina", "eastmoney"],   # baostock: 5/15/30/60分钟、长历史、免费；当日/实时回落 sina/eastmoney
    "cn_etf":        ["sina", "eastmoney"],               # baostock 分钟线不覆盖ETF（官方确认），已移除
    "cn_future":     ["sina", "eastmoney"],               # 期货无 baostock 分钟源 → 依赖自建增量库
    "global_future": ["sina"],
    "forex":         ["sina"],
    "crypto":        ["binance"],
    "cn_index":      ["eastmoney", "sina"],              # 指数分钟走东财 index_zh_a_hist_min_em；baostock 分钟线不含指数
}
# 无时间游标、无法分页的数据源：只能取『最近N根』，超出部分必须显式标注
MINUTE_NO_PAGINATION_SOURCES = ["sina", "eastmoney"]

# 指数日线数据源优先级：东财（含成交额）→ 新浪（全历史，无成交额）→ BaoStock（含成交额，可交叉验证单位）→ 腾讯（备用）
# 注意：新浪指数日线不含成交额（amount=NaN），且指数成交量单位无法用 amount/(close×volume) 自检，
#      必须用 BaoStock 指数日线（含 volume+amount）做交叉验证，详见 config 指数数据源段落注释与文档 1.0 铁律 7。
CN_INDEX_DAILY_PRIORITY = ["eastmoney", "sina", "baostock", "tencent"]

# ==================== 数据源可用性（第2步实测；第13步据此补源） ====================
# ⚠️ 这是「当前实测现状」，会随网络环境变化；架构上必须支持自动探测 + 切换，不能假设某个源永远可用。
SOURCE_AVAILABILITY = {
    "eastmoney": {"available": False, "note": "push2his 本机持续 RemoteDisconnected（个股/ETF/指数 日线+分钟 全线）"},
    "sina":      {"available": True,  "note": "A股/期权/期货/外汇 可用"},
    "baostock":  {"available": True,  "note": "A股日线 + 5/15/30/60 分钟；不含指数分钟"},
    "tencent":   {"available": True,  "note": "指数日线备用；amount 列实为成交量(手)"},
    "binance":   {"available": True,  "note": "加密；独立于东财/新浪"},
}

# 单点故障：这些市场在指定周期【只有东财一个源】，东财挂即完全取不到
# → 第13步补源优先级最高（不是「加切换逻辑」就够——单源品种切换也无从切换）
SINGLE_SOURCE_MARKETS = {
    "daily":  ["forex", "cn_fund", "cn_reverse_repo"],
    "minute": ["cn_convertible", "us_stock", "us_etf", "hk_stock"],
}

# 指数成交量单位：已跨源验证（BaoStock 指数日线同时含 volume/amount vs 新浪同指数同日）
# 结论：新浪指数 volume=股（÷100 转手）；sh.000300 / sh.000001 比值 1.0000、sz.399001 比值 0.9991
CN_INDEX_UNIT_VERIFIED = True

# 数据时效（stale）上限：本地库停更超过该交易日数即视为不可用、直接报错（详见文档 1.0 节七）
# 回测/研究可用 stale 数据；【模拟盘/实盘的下单决策禁止使用 stale 数据】
STALE_LIMIT = {"daily": 5, "minute": 2}

# 下单链路时效闸门（双重防线的第二道，默认开启）：
# ⚠️ 数据层的 for_trading=True 是「默认放行」——上游忘记传参就失去保护，不能靠约定保护实盘。
#    订单模块必须在「每次下单前」独立重新校验数据时效，不读取也不信任上游的 attrs['stale']。
# ⚠️ 仅对 paper/live 模式生效；backtest 模式必须豁免——回测用历史数据，相对「今天」永远过期，
#    闸门无条件生效会把全部回测拒掉。闸门须按 RUN_MODE 开关。
#    验收判据：把数据层的 for_trading 全部去掉，下单链路仍须拦得住 stale 数据。
TRADING_REQUIRE_FRESH = True

# ⚠️ DataFrame.attrs 会因窗口运算丢失（pandas 2.3.3 实测）：
#    concat / merge / groupby / resample().agg() / diff / pct_change / cumsum / astype / 布尔索引 均【保留】attrs；
#    但 rolling() / ewm() / expanding() 三类窗口运算会把 attrs 清空（返回 {}），to_numpy() 重建也丢失。
#    这三类恰是技术指标（MA/EMA/MACD/RSI/BOLL/ATR）与因子计算的核心手段 → 指标帧的 attrs 不可信。
#    要求：① 关键出口统一重新挂载 attrs；② 禁止仅凭 attrs['stale'] 做交易决策，须在用数那一刻重新校验。
ATTRS_FRAGILE_NOTE = "DataFrame.attrs 经 rolling/ewm/expanding 窗口运算及 to_numpy 重建后会丢失，禁止仅凭 attrs['stale'] 做交易决策"

# ⚠️ fail-closed 的适用边界（关键：防止「过度保护」导致实盘全面拒单）：
#    attrs 在 rolling/ewm/expanding 后必然丢失 —— 而实盘策略【一定】是算完指标才下单的
#    （MA 金叉、MACD 背离、ATR 止损都基于窗口运算）。若时效闸门写成「读不到 attrs 就 fail-closed」，
#    后果是：任何经过指标计算的数据都会在下单时被判「无法确认时效」而拒单 → 实盘每一笔都下不出去。
#    正解：时效信息必须【脱离 attrs】，二选一 ——
#      ① 物化为【普通列】（列不会被窗口运算清空）：STALE_INFO_COLUMN 指定的日期列随数据一起流转；
#      ② 下单链路【独立重新取数】复核（不信任上游任何帧）。
#    fail-closed 只允许用在「既无时效列、又无法重取」的兜底场景，不得作为唯一防线。
STALE_INFO_COLUMN = "data_asof_date"   # 时效物化列：随 DataFrame 穿过 rolling/ewm/resample/concat，不被清空
STALE_CHECK_MODE = "refetch"           # 下单时效复核方式：'refetch'（独立重取，推荐）或 'column'（读物化列）
FAIL_CLOSED_NOTE = "fail-closed 仅在「既无时效列、又无法重取」时使用；不得作为唯一防线，否则指标计算后的数据会在下单时被全部拒单"

# ⚠️ 时效复核 v2（防止「物化列」在真实链路失效——配合上面三个常量）：
#    1. 架构事实：本系统指标库是【纯函数】（只吃 Series/DataFrame、返回 Series/DataFrame，见第 3 步）——
#       策略把各指标 Series 拼成决策帧时，data_asof_date 列【不会自动带过去】，故「读物化列」对策略
#       决策帧常常为空。因此【下单链路的时效复核必须以 refetch 为主】（按 market+symbol 重取最新数据
#       比对交易日历）；物化列只用于数据层出口帧或单标的快速判断。禁止把「决策帧无列」当成 fail-closed 的理由。
#    2. 数据层出口挂 data_asof_date 时，值必须是【该帧自身最后一根 bar 的实际日期】，绝不是「取数时刻/今天」；
#       缓存命中、失败回退出口同样按被返回数据的真实日期填写——否则缓存里的旧数据会被标成新鲜，防线在最常见路径上失守。
#    3. 多标的帧：【按 symbol 分组】填各自最新日期，禁止把「整帧最大日期」广播到所有行（否则一个新鲜标的会掩盖同帧内的过期标的）。
#    4. refetch 失败（网络故障/源不可达）的处置见 STALE_REFETCH_FAIL_POLICY：开仓从严、平仓从宽。
STALE_REFETCH_TTL_SEC = 60             # 同一下单批次内 refetch 结果复用窗口（秒），避免逐单重取打满接口/拖慢下单
STALE_REFETCH_FAIL_POLICY = {"open": "reject", "close": "allow"}  # refetch 取不到时：开仓拒单、平仓放行（风险优先，避免因网络抖动无法止损/平仓）



# ==================== 19类市场交易规则（含指数基准层） ====================
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

# ---------- 16B. 北京证券交易所（BSE，v3.43 新增，独立成市） ----------
# 为什么必须独立成市而非塞进 cn_stock：北交所涨跌幅 30%、100 股起【以 1 股递增】、T+1、
#   个人门槛 50 万 + 2 年经验、专属 920 号段——任一规则都与沪深 A 股不同。
#   塞进 cn_stock 会让涨跌幅 / 最小申报单位 / 合格投资者闸门【全部跑错规则】。
BSE = {
    "code_segment": "920",                 # 2025-10-09 起专属号段
    "min_qty": 100,                        # 竞价单笔申报 100 股起
    "qty_step": 1,                         # 以 1 股为单位递增（≠沪深 100 股整数倍）
    "price_step": 0.01,
    "t_plus": 1,
    "price_limit": 0.3,                    # 首日后涨跌幅 30%
    "first_day_no_price_limit": True,      # 新股上市首日不设涨跌幅
    "delisting_first_day_no_limit": True,  # 退市整理期首日不设涨跌幅
    "commission_rate": 0.0005,
    "stamp_tax_rate_sell": 0.0005,
    "qii_threshold_financial_assets": 500_000,   # 开通前 20 个交易日日均资产 >= 50 万
    "qii_experience_months": 24,                 # >= 2 年证券交易经验
    "trading_hours": [(9*60+30, 11*60+30), (13*60, 15*60)],
    "call_auction_times": [(9*60+15, 9*60+25), (14*60+57, 15*60)],
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
# v3.32：复权默认口径【唯一来源】。此前 BACKTEST_DEFAULTS["adjust"] 与
# DATA_LONG_TERM["default_adjust_for_backtest"] 两处各写一个字面量，第 13 步 13.2 正文
# 又要求长期研究默认走 hfq → 三处口径互相打架（实测矛盾）。统一为单一常量，两处都引用它。
DEFAULT_ADJUST = "hfq"          # 长期研究默认后复权：区间内收益率连续可加，避免前复权跨除权日跳变
BACKTEST_DEFAULTS = {
    "initial_cash": INITIAL_CASH,
    "benchmark": BENCHMARK,
    "slippage_pct": 0.0005,
    "adjust": DEFAULT_ADJUST,
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

# ==================== 周期定义（全局唯一，禁止各处自建映射） ====================
# 1) SUPPORTED_PERIODS：全项目「可取数/可支持」的周期全集，字符串写法唯一标准。
#    数据层、指标、绘图、回测、盯盘一律用这套字符串，禁止出现 "1" / "60" 这类纯数字写法。
SUPPORTED_PERIODS = ["1d", "1w", "1M", "1min", "5min", "15min", "30min", "60min"]

# 2) PERIOD_TO_MINUTE：周期字符串 → 数据层分钟数（仅分钟周期有值）。
#    这是全项目唯一的一份映射，第 2/3/6/8 步都必须引用它，不要在函数内部另建映射表。
PERIOD_TO_MINUTE = {
    "1min": 1,
    "5min": 5,
    "15min": 15,
    "30min": 30,
    "60min": 60,
}

# 3) DAILY_PERIODS / MINUTE_PERIODS：按数据来源分流用。
DAILY_PERIODS = ["1d", "1w", "1M"]     # 走 get_daily()，周/月由日线本地重采样
MINUTE_PERIODS = ["1min", "5min", "15min", "30min", "60min"]  # 走 get_minute()

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
    # 默认批量出图的周期集合（不含 1min：1分钟数据量巨大、BaoStock 也不支持 1min，
    # 默认出图无意义）。注意：它是 SUPPORTED_PERIODS 的「默认出图子集」，
    # 不是周期全集；get_kline() 仍支持 SUPPORTED_PERIODS 全部 8 种周期。
    "plot_periods": ["1d", "1w", "1M", "5min", "15min", "30min", "60min"],
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

# ==================== 技术指标配置（第 3 步） ====================
# 说明：指标函数禁止硬编码年化基数（252/244），一律引用本配置。
INDICATOR_CONFIG = {
    # 年化基线（A股一年约 242~244 个交易日；美股约 252）
    "annual_trading_days": 244,
    "annual_trading_days_us": 252,
    # 按周期换算的年化因子（非日线周期年化用，禁止就地写死）
    "annual_factor_by_period": {
        "1d": 244, "1w": 52, "1M": 12,
        "1min": 244 * 240, "5min": 244 * 48, "15min": 244 * 16,
        "30min": 244 * 8, "60min": 244 * 4,
    },
    # 默认复权口径（须与数据层 get_daily 默认一致；同一组指标不得混用口径）
    "default_adjust": "qfq",
    # 年化无风险利率（夏普等使用）
    "risk_free_rate": 0.02,
    # 量能类指标口径：只用 volume，禁止 amount（期货/指数 amount 为 NaN）
    "volume_metrics_use": "volume",
    # 计算行为
    "keep_nan": True,          # 窗口不足的 NaN 保留、不填充
    "forbid_center": True,     # 禁止 center=True / 全样本标准化（未来函数）
    # 评估类指标（全样本统计量，禁止进入实时信号链）
    "evaluation_only": ["MAX_DRAWDOWN", "SHARPE_RATIO", "ANNUAL_RETURN", "VOLATILITY"],
    # 净值型品种（不走 K 线，不适用 ATR/KDJ/BOLL/SAR 等需要 high/low 的指标）
    "nav_only_markets": ["cn_fund", "cn_reverse_repo", "private_fund", "qii_product"],
}

# ==================== 技术指标加固（第 3 步 v2） ====================
# 说明：见指令集 3.0 节四「指标守卫不能装在会失灵的信息源上」。
# 核心教训：守卫读的信息源若会丢/可缺，守卫本身就等于没有——这与第 2 步 stale 闸门同一道理。
INDICATOR_HARDENING = {
    # ① 复权口径【物化列】：与易失的 attrs 不同，普通列能穿过 resample/concat/窗口运算。
    #    数据层出口除挂 attrs 外，再写一列该值（qfq/hfq/none）；指标入口优先读此列。
    "adjust_column": "price_adjust",
    # ② 波动率类指标（ATR/STD/HIST_VOL）【无法确认复权口径】时的处置：
    #    "require" -> 抛错（推荐：宁可拦住，也不在未复权价上算波动率）
    #    "assume"  -> 按 config.INDICATOR_CONFIG['default_adjust'] 处理（fail-open，仅在数据层已保证口径时可用）
    #    ⚠️ 禁止「attrs 读不到就静默按已复权处理」——那正是本项要防的最隐蔽错误。
    "on_adjust_unknown": "require",
    # ③ 各指标【默认参数】下的最小预热根数（下界，递归类取 max(所需, 本值)）。
    #    不足则返回 NaN；回测/实盘【必须】跳过预热期再出信号：
    #    EMA/SMA(通达信)/RSI(Wilder)/ADX/SAR/MACD 的 DEA 都是递归的，早段值由初始化决定、有偏，
    #    不算未来函数（看不出超前），但同样让早段信号失真——属于「不报错但结果整体偏掉」。
    "warmup": {
        "MA": 20, "EMA": 20, "SMA": 20, "MACD": 35, "BOLL": 20,
        "RSI": 15, "KDJ": 9, "ROC": 13, "CCI": 14, "WILLR": 14,
        "VOL_MA": 10, "OBV": 1, "VR": 26,
        "ATR": 14, "STD": 20, "HIST_VOL": 21,
        "ADX": 28, "SAR": 5,
        "IV_RANK": 252, "IV_PERCENTILE": 252,
    },
    # ④ 评估类指标统一前缀：物理隔离，从命名上就不可能被误当实时信号（见 3.0 红线 1）。
    #    evaluation_only 里的 MAX_DRAWDOWN/SHARPE_RATIO/ANNUAL_RETURN/VOLATILITY 一律实现为
    #    eval_ 前缀（eval_max_drawdown / eval_sharpe_ratio / ...），并由「实时信号链入口」统一挡。
    "eval_prefix": "eval_",
    # ⑤ 量能类指标遇 volume 全 0（如净值型序列）时的处置：返回空/NaN 并置 labeled_empty=True，
    #    严禁静默返回 0 值序列（0 会被误读为「极度缩量」）。
    "volume_all_zero_returns_empty": True,
}


# ==================== 指标预热防击穿（第 3 步 v3） ====================
# 教训：预热期置 NaN 只是「哑弹」——能不能挡住信号，取决于【下游怎么处理 NaN】。
#   fillna(0) / ffill / bfill / rolling(min_periods=1) 都会把 NaN 抹平；其中 fillna(0) 最阴：
#   RSI/KDJ 的预热 NaN 变成 0 → 被策略读成「极度超卖」→ 预热期直接发买入信号，且【不报错】。
# 正解：预热判定必须由【信号入口】引擎级统一裁决，不能靠调用方自觉；指标输出须携带
#   「该 bar 是否已过预热期」的物化布尔列，信号入口强制按此列过滤。
INDICATOR_WARMUP_GUARD = {
    # ① 指标输出携带的「可出信号」物化布尔列：True = 该 bar 已过预热期。
    #    信号入口强制 df[warmup_ok_column]；禁止在掩码为 False 的行上 fillna 后出信号。
    "warmup_ok_column": "warmup_ok",
    # ② required_bars 的确定方式：禁止查表拍脑袋（表值只是下界）。
    #    递归类（EMA/SMA/RSI/ADX/SAR/MACD-DEA）以「与充分燃烧期长样本结果比对、相对误差 <= tol」
    #    反推所需最少根数；实测该值才可作为可用下界。
    "convergence_tol": 1e-3,                    # 逐值相对误差容差（与 burn-in 长样本比对）
    "required_bars_method": "burnin_compare",   # 'burnin_compare'（推荐）/ 'table'（仅非递归类可单独用）
    # ③ 明确禁止：在预热掩码为 False 的行做 fillna / ffill / bfill / rolling(min_periods=1) 后出信号。
    "forbid_fillna_before_warmup": True,
    # ④ 实盘：最后一根 bar 仍处预热期（新上市 / 刚切周期）时，该标的【拒绝出信号】，
    #    不得给「有偏的早段值」；并与第 4 步下单闸门联动（无有效信号 → 不开仓）。
    "live_reject_if_last_bar_in_warmup": True,
}

# ==================== 期权估值加固（第 3 步 v3） ====================
# 说明：IV 反解用二分法，但在【深度虚值 / 临近到期(T→0) / 市价低于内在价值(脏数据)】时会【无解】，
#   必须 fail-closed（返回 NaN 并标注），禁止返回边界值冒充「IV 收敛到 0.0001」。
#   希腊字母单位（最容易悄悄错十倍）：THETA=每自然日、VEGA/RHO=每 1 个百分点。
OPTION_VALUATION_GUARD = {
    "iv_solver": "bisection",
    "iv_bounds": [1e-4, 5.0],       # 二分区间（年化波动率）
    "iv_tol": 1e-6,                 # 价格收敛容差
    "iv_max_iter": 200,
    # 无解处置："nan" -> 返回 NaN 并置 iv_solved=False（推荐，禁止返回边界值）
    "on_no_solution": "nan",
    "day_count_theta": 365,         # THETA 按自然日
    "vega_per": "1_pct",            # VEGA 每 1 个百分点
    "rho_per": "1_pct",             # RHO 每 1 个百分点
    "risk_free_rate_ref": "INDICATOR_CONFIG['risk_free_rate']",
    "dividend_yield_default": 0.0,  # BS 的 q（暂默认 0，期权标的多为不付息指数/个股）
}


# ==================== 闸门一致性 / 引擎无关（第 6 步 v3.23） ====================
# 说明：第 6 步会替换第 5 步的轻量执行器 core/runner.py。凡写在执行器内部的闸门逻辑
#   （warmup_ok 逐 bar 注入、末根预热判定、assert_signal_frame）都会随替换【静默消失】。
#   闸门只允许有【一份】引擎无关的实现，并写【引擎一致性测试】防止替换时丢失。
GATE_CONFORMANCE = {
    "gate_module": "core/signal_gate.py",   # 闸门唯一实现（引擎无关）；backtester 只调用、不重写
    "enforce_at": "place_order",            # 裁决收口：与 stale 闸门同处（随引擎替换存活）
    "feed_warmup_ok_into": "bar_dict",      # 引擎必须把 warmup_ok 列注入每根 bar，缺列即报错
    "min_backtest_bars": "max(60, strategy.required_bars())",  # 禁止硬编码 60（MACD 收敛 ~70+）
    "preserve_columns_on_align": ["data_asof_date", "price_adjust", "warmup_ok"],  # 多标的对齐须逐标的保留
}


# ==================== 成交模型 / 引擎无关共享（第 7 步 v3.24） ====================
# 说明：第 6 步把「写实成交」做成了仅挂回测 account 的 ExecutionModel；第 7 步模拟盘、第 12 步实盘
#   若各自再建一套撮合/风控，则回测—模拟—实盘【三套逻辑必然漂移】，第 7 步「偏差超 5% 告警」会被
#   已知的结构性差异触发。成交模型与风控必须【引擎无关、单份实现】，三处只调用、不重写。
EXECUTION_MODEL = {
    "module": "core/execution.py",           # 成交模型唯一实现（引擎无关）；backtester/paper/live 只调用
    "risk_module": "core/risk.py",           # 风控唯一实现（引擎无关）：单票仓位/日内亏损/黑天鹅/强平
    "shared_by": ["backtest", "paper", "live"],
    "slippage_base_pct": 0.0005,             # 与 BACKTEST_DEFAULTS['slippage_pct'] 对齐
    "slippage_multiplier": {"backtest": 1.0, "paper": 2.0, "live": 2.0},  # 三环境差异【只允许】在此参数化
    "volume_limit_pct_by_market": {          # 单笔量限【按市场分档】，禁止全市场硬编码 1%
        "cn_stock": 0.01, "cn_etf": 0.02, "cn_convertible": 0.005,
        "cn_future": 0.02, "cn_reits": 0.01, "us_stock": 0.01, "us_etf": 0.02,
        "hk_stock": 0.01, "crypto": 0.005, "forex": None,   # forex 近 24h，量限按流动性另定
        "cn_fund": None, "cn_reverse_repo": None,           # 净值型/逆回购走净值透传，不做量限
        "private_fund": None, "qii_product": None,
    },
    "zdt_reject_on_open": True,              # 涨跌停：仅判开盘即封板（盘中反复开板未模拟）
    "bias_direction": {                      # 每项「已知简化」的偏差方向（供回测—实盘偏差归因）
        "sell_slippage_at_open": "中性偏乐观",       # 卖出滑点按开盘价统一计算
        "zdt_open_only": "偏悲观（过度拒单）",        # 涨跌停仅判开盘即封板
        "volume_limit_fixed": "修正后收敛（分档）",   # 量限固定 1% → 按市场分档
        "nav_pass_through": "中性",                  # 基金/逆回购走净值透传
    },
    "known_simplifications": [
        "卖出滑点按开盘价统一计算",
        "涨跌停仅判开盘即封板，未模拟盘中反复开板",
        "量限按市场分档（原为固定 1%）",
        "基金/逆回购走净值透传，不参与撮合量限",
    ],
    # ---- v3.25：撮合价基准（未来函数的藏身处） ----
    # 关键不在「开盘 or 收盘」，而在【成交所用 bar 必须严格晚于决策所用 bar】。
    # 若 on_bar(t) 用 t 收盘决策、却按 t 开盘价成交 ⇒ 用未来信息在当下成交（系统性乐观）。
    "match_price_basis": "next_open",        # 成交落在【信号 bar 的下一根】（默认）；全项目统一，禁止各引擎写死
    "match_price_basis_meta": {              # 基准语义：bar_offset 相对信号 bar 的偏移
        "next_open":  {"price": "open",  "bar_offset": 1, "lookahead_safe": True},
        "next_close": {"price": "close", "bar_offset": 1, "lookahead_safe": True},
        "same_open":  {"price": "open",  "bar_offset": 0, "lookahead_safe": False},  # 仅当决策已滞后一根才可用
        "same_close": {"price": "close", "bar_offset": 0, "lookahead_safe": False},  # 仅当决策已滞后一根才可用
    },
    "enforce_fill_after_signal": True,       # 强制断言 fill_bar_index > signal_bar_index（同根 bar 成交＝未来函数）
}

# ==================== 引擎一致性 / 三引擎共用（第 7 步 v3.24） ====================
# 说明：本项目有三种引擎——回测 core/backtester.py、模拟盘 core/paper_trader.py、实盘 core/live_trader.py。
#   三者【必须共用】闸门/成交/风控三板斧，且每个引擎都必须把三个物化列注入 bar_dict，
#   否则「同一策略四环境零改动」只是口号，回测—模拟—实盘结果不可比。
ENGINE_CONFORMANCE = {
    "engines": {
        "backtest": "core/backtester.py",
        "paper": "core/paper_trader.py",
        "live": "core/live_trader.py",
    },
    "must_share": ["core/signal_gate.py", "core/execution.py", "core/risk.py"],  # 三引擎必须共用、禁止重写
    "must_feed_columns": ["warmup_ok", "data_asof_date", "price_adjust"],        # 每个引擎都必须注入 bar_dict，缺列即报错
    "consistency_test": "test_engine_consistency.py",                            # 三引擎同帧同策略，结果必须一致
    "divergence_warn_pct": 0.05,             # 模拟盘—回测偏差告警阈值（仅在共用三板斧前提下有意义）
}


# ==================== 信号出口一致性（第 8 步 v3.25） ====================
# 说明：闸门/时效此前只装在「下单」这一个出口上（place_order）；但「盯盘推送」是【第二个出口】——
#   它把信号推给【人】，人据此手动下单。若盯盘直接调用 strategy.on_tick 取信号、不经过
#   core/signal_gate.py 与时效闸门，则预热期/停更数据的信号会【直接推给人】，
#   比自动下单更危险（自动下单还有 place_order 兜底，推给人则无人兜底）。
SIGNAL_EGRESS_CONFORMANCE = {
    "signal_egress_points": ["place_order", "monitor_push", "report_plan", "investor_disclosure", "live_order_submit", "watch_only_live_push"],   # v3.34 增 watch_only_live_push：实盘 watch-only 盯盘推送（第 6 出口，与 monitor_push 同族，此前未登记）   # 任一出口产出的信号都必须先过闸门（v3.28 增 investor_disclosure：对外披露）
    "must_call_gate": "core/signal_gate.py",                   # 盯盘只调用、不重写闸门
    "monitor_must_inject_columns": ["warmup_ok", "data_asof_date", "price_adjust"],  # 喂给 on_tick 的数据缺列即报错
    "forbid_bare_on_tick": True,                               # 禁止把 data_fetcher 的裸行情直接喂 on_tick
    "push_requires_fresh": True,                               # 推送前过时效闸门（与第 4 步 refetch 同源）
    "session_check_per_market": True,                          # 逐市场用 get_market_config + 交易日历判时段
    "push_must_tag_gated": True,                               # 推送消息须标注「已过闸门 / 数据截至日期 / 是否新鲜」
}


# ==================== 复盘报告一致性（第 9 步 · v3.27 新增） ====================
# 核心：复盘报告是「第三个输出口」——它既把结果总结给人看，又把「明日计划/候选标的」这种
# 前瞻性建议推给人。它若只报成交，就会把闸门的拦截静默抹掉；它的「候选标的」在性质上就是
# 一份推送信号，却长期不在 SIGNAL_EGRESS_CONFORMANCE 的出口清单里。
REPORT_CONFORMANCE = {
    "must_share_signal_source": True,   # 报告的信号/成交/持仓必须取自引擎同一份记录（account.trades + signal_gate 裁决日志 + bills），禁止 reporter 重跑策略或另算一套
    "must_report_suppression": True,    # 必须展示「被闸门拦掉的信号」——只报成交=替闸门掩盖
    "suppression_reasons": ["warmup", "stale", "off_session", "limit_up_down", "volume_limit", "risk_block"],
    "plan_is_signal_egress": True,      # 「明日计划/候选标的」= 第三个信号出口，须过闸门+时效
    "plan_requires_fresh": True,        # 候选标的所用数据须过时效闸门（与第 4 步 refetch 同源）
    "plan_must_tag_gated": True,        # 候选标的须标注闸门状态与数据截至日期
    "metrics_must_share_source": True,  # 胜率/盈亏比/最大回撤等须复用引擎或第 3 步 eval_ 的同源实现，禁止自算一套
    "auto_send_requires_fresh": True,   # 报告自动发送走 notifier，同样受时效闸门约束
    "zero_trade_disclosure": True,      # 「0 笔交易」必须拆解为「策略无信号」/「闸门拦截 N 笔」，禁止笼统显示 0
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
    # v3.32：13.1 正文要求 Baostock 作为「免费第一备份源」（无需 token），此处原为
    # ["akshare","tushare","local"] → 照 config 实现则永远不会切到 Baostock。已按 13.1 补齐。
    "data_source_priority": ["akshare", "baostock", "tushare", "local"],
    "data_source_failover": True,
    "source_timeout_seconds": 15,          # v3.32 补：13.1 正文引用本键，此前缺失（KeyError / 静默默认）
    "save_raw": True,                  # 原始不复权价落盘
    "save_adj_factor": True,           # 复权因子单独落盘
    "default_adjust_for_backtest": DEFAULT_ADJUST,   # v3.32：改为引用唯一来源（13.2 要求长期研究默认 hfq）
    "cache_format": "parquet",
    "cache_compression": "snappy",
    "enable_data_version": True,
    "data_manifest_file": "data_cache/data_manifest.json",
    "integrity_check": True,           # 完整性校验开关（口径统一为 SHA256，见 integrity_hash_algo）
    "integrity_hash_algo": "sha256",   # v3.32：13.3 用 SHA256，原注释写 MD5 → 统一为 SHA256
    "raw_dir": "data_cache/raw",               # v3.32：13.2 分离存储路径（显式化，勿散落硬编码）
    "adj_factors_dir": "data_cache/adj_factors",
    "snapshots_dir": "data_cache/snapshots",
    "constituents_dir": "data_cache/constituents",
    "cache_retention_days": 365,
    "cold_archive_days": 30,
    "cache_max_gb": 20,                # v3.32 补：13.9 正文引用本键，此前缺失
    "cold_compress": True,
    "snapshot_every_run": True,        # 每次回测保存数据快照
    "snapshot_format": "parquet",
    "snapshot_retention_days": 2190,   # v3.32 补：13.4 引用本键但此前缺失；且必须 >= 最长报告保留期
                                       # （retention_days_monthly/backtest = 2190），否则第 366 天起
                                       # 报告里的 data_version 成为死引用，「可复现」自带过期时间
    "point_in_time_index": True,       # 时点成分股（防幸存者偏差）
    "pit_index_update_days": ["03-01", "06-01", "09-01", "12-01"],  # 季度调整
    "source_health_file": "data_cache/source_health.json",  # v3.45: 13.1 探活结果落盘位置（health_check 唯一写入目标）
    "failover_log_required": True,            # v3.45: 每次源切换必须打告警日志+推 notifier；fail_closed
    "field_consistency_required": True,        # v3.45: 跨源字段单位/口径不一致（如 akshare volume=手、baostock volume=股）必须 raise，禁止静默拼接
    "tokenless_sources_first": True,           # v3.45: 无 token 的源（akshare/baostock）优先，tushare 无 token 时静默跳过不报错
    "max_consecutive_failures": 3,             # v3.45: 单源连续失败 N 次后标记 unhealthy，下次路由跳过直到 health_check 恢复
    "local_fallback_must_exist": True,         # v3.45: 所有远程源都失败且本地缓存也为空时 raise，禁止返回空 DataFrame 当成功
    "reconcile_reports_daily": True,
    # ---- v3.51：回退到本地累计时，当日空缺必须【显式声明】（不能靠日志字符串被测试嗅到）----
    #   病（本轮实测）：实时源全灭 + 本地有库 → 返回本地累计帧 rows=0，只打了一句「已回退」，
    #   当日空缺没有任何【结构化】声明；缺了它，回退在语义上就等价于「今天有数据」。
    "local_fallback_must_declare_today_missing": True,
    "missing_today_must_be_structured_field": True,
    "today_missing_field": "today_missing_declared",
}

# ==================== 数据源适配器闸门（v3.46 新增·13.0.17） ====================
#   13.1 实施后暴露「守卫位置 / 守卫对象错位」四类（不是「守卫不够多」）：
#     ① 单位口径表被复制成第二份（config 按接口名 vs 适配器按源+市场+周期）→ 必然漂移；
#     ② internal_failover 由适配器【自声明】，等于被守卫对象给自己发永久豁免；
#     ③ local_fallback_must_exist 是悬空键（路由器没有 LocalSource，兜底甩给外层调用方）；
#     ④ router_all_empty 把「故障空」（被限流源返回空不抛异常）当「合法空」（退市/非交易日）。
DATA_SOURCE_ADAPTER_GUARD = {
    # A. 单位口径表必须单一权威（禁止适配器内再起一份）
    "volume_unit_table_source": "config.DATA_SOURCE_UNITS",
    "source_interface_map": "config.SOURCE_INTERFACE_MAP",
    "unknown_unit_combo_must_raise": True,            # 未登记组合 -> raise，不得默认为 1
    "forbid_hardcoded_unit_factor_in_adapter": True,  # 适配器内不得出现 *100 / ×100 之类字面量
    # B. internal_failover 不得由适配器自声明给自己发豁免
    "internal_failover_allowlist": "config.INTERNAL_FAILOVER_SOURCES",
    "internal_failover_selfdeclared_forbidden": True,
    "internal_failover_max_consecutive_failures": 5,  # 高于默认 3：市场级宽限，源级仍熔断
    "source_level_failure_counts_regardless": True,   # 所有内部回退都失败 = 源级失效，必须计数
    # C. 本地兜底必须由路由器持有（不是甩给外层调用方）
    "router_must_hold_local_source": True,
    # D. 净空必须带证据；应交易日净空升级为异常
    "router_all_empty_requires_probe_evidence": True,
    "expected_trading_day_empty_must_raise": True,
    # E. 实时快照虽单源，仍须过字段一致性校验（已知欠账，登记）
    "realtime_must_pass_field_consistency": True,
    # F. v3.47：SOURCE_INTERFACE_MAP 与 _SUPPORTED_*_MARKETS 是【同一事实的两份清单】
    #    （v3.46 想根治「两表并存」，结果在 config 内部又长出一处：本次实测 23 vs 28 条，
    #     靠「逐个手工补 key」对齐 → 下次加市场必再漂）
    "map_scope_must_equal_supported_scope": True,
    "supported_scope_source": "core/data_fetcher.py::_SUPPORTED_DAILY_MARKETS/_SUPPORTED_MINUTE_MARKETS",
    "supported_scope_must_be_declared_once": True,
    "map_scope_mismatch_action": "raise",
    "forbid_manual_map_extension": True,          # 不得靠逐个手工补 map key 对齐；须由 scope 派生或校验
    # G. v3.48：独立证据源（上市/退市主数据）的【上游】必须登记，且不得与行情源同源
    "evidence_source_upstream": "securities_master",
    "evidence_upstream_must_not_be_in_market_source_priority": True,   # 上游 ∈ data_source_priority → raise
    "evidence_upstream_must_be_declared": True,   # 未登记上游 → raise（禁止「说不清从哪来的独立源」）
}

# ---------- 净空证据来源（v3.47 新增）：empty_reason 不得由「取数返空」反推 ----------
#   病（v3.46 实施后暴露）：为让「应交易日净空」闸门放过退市标的，改由【数据层】在取到空表后
#       填 empty_reason="delisted_or_not_listed" 作为证据。但判定「退市」的依据是「取数返回空」——
#       而这正是被限流源的表现。于是「被限流」只要被标成 empty_reason，就能绕过净空闸门。
#       与 v3.46 的 internal_failover 自声明同族：【被守卫对象给自己发豁免】。
#   一句话：标的【是否在市】是【独立事实】（证券主数据 + as_of），不能由「这次取数空不空」反推。
EMPTY_REASON_PROVENANCE = {
    "enabled": True,
    "allowed_sources": ["securities_master"],        # 唯一合法来源：独立证券主数据（上市/退市状态表）
    "forbid_fetch_self_declared": True,              # 取数层【不得】自行判定并填写 empty_reason
    "forbid_infer_from_empty_result": True,          # 禁止由「本次返回空」反推「退市」
    "requires_as_of": True,                          # 「是否在市」随时间变化 → 必须带 as_of
    "must_pass_pit_guard": True,                     # 走 data/pit_index.py 的时点闸门
    "unknown_empty_reason_must_raise": True,
    "empty_reason_must_be_logged": True,
    # 探针证据完整性：「已尝试 无」说明证据链断了（把返回空表也判成「没试过」）
    "tried_must_include_empty_sources": True,        # tried 必须含【所有被调用的源】，含返回空者
    "tried_entry_schema": ["source", "endpoint", "status", "rows", "elapsed_ms"],
    "probe_evidence_required": True,
    # ---- v3.48：证据源的「独立性」必须被验证，不能只靠【取名字】 ----
    #   病：v3.47 要求 empty_reason 只来自「独立证券主数据」，并新建了 security_master.py。
    #       但「独立」是指【取数路径不同上游】，没有任何东西约束它：若 security_master 底层
    #       仍走 akshare / tushare（与行情同一个被封的出口），那么被限流时【主数据与行情会同时
    #       返空】——主数据照样会把「被限流」翻译成「退市」。这是 13.0.17 病二（守卫装在会失灵的
    #       信息源上）在【证据源】这一层的复现：把守卫从「取数层」搬到「另一个更名不改姓的取数层」。
    #   一句话：**证据源必须与被守卫的事实【不同上游】；且主数据取不到时必须 raise，不得回退行情源。**
    "evidence_source_must_be_independent": True,
    "listing_probe_source": "securities_master",
    "independent_upstream_required": True,           # 主数据上游 ≠ 行情上游（不得共用限流出口）
    "forbid_shared_upstream_with_market_data": True,
    "forbid_fallback_to_market_source": True,        # 主数据不可用 → raise，禁止用行情源反推「是否在市」
    "listing_probe_unavailable_must_raise": True,
    "upstream_declared_in": "config.DATA_SOURCE_ADAPTER_GUARD.evidence_source_upstream",
}

# 源 + 市场 + 周期 → AKShare 接口名（单位口径表的【唯一索引桥】；单位乘数仍 per-interface）
#   ⚠️ 适配器不得自带单位乘数表；一律经本表查到接口名，再去 DATA_SOURCE_UNITS 取乘数。
SOURCE_INTERFACE_MAP = {
    ("akshare", "cn_stock", "daily"): "stock_zh_a_hist",
    ("akshare", "cn_stock", "daily_backup"): "stock_zh_a_daily",
    ("akshare", "cn_stock", "realtime"): "stock_zh_a_spot_em",
    ("akshare", "cn_stock", "minute"): "sina_kline_minute",
    ("akshare", "cn_index", "daily"): "index_zh_a_hist",
    ("akshare", "cn_index", "daily_backup"): "stock_zh_index_daily",
    ("akshare", "cn_index", "minute"): "index_zh_a_hist_min_em",
    ("akshare", "cn_etf", "daily"): "fund_etf_hist_em",
    ("akshare", "cn_etf", "daily_backup"): "fund_etf_hist_sina",
    ("akshare", "cn_reits", "daily"): "reits_hist_em",
    ("akshare", "cn_fund", "nav"): "fund_open_fund_info_em",
    ("akshare", "hk_stock", "daily"): "stock_hk_hist",
    ("akshare", "hk_stock", "realtime"): "stock_hk_spot_em",
    ("akshare", "us_stock", "daily"): "stock_us_hist",
    ("akshare", "us_stock", "realtime"): "stock_us_spot_em",
    ("akshare", "cn_bond", "daily"): "bond_zh_hs_cov_daily",
    ("akshare", "cn_future", "daily"): "futures_main_sina",
    ("akshare", "cn_future", "minute"): "futures_zh_minute_sina",
    ("akshare", "cn_option", "daily"): "option_sse_daily",
    ("baostock", "cn_stock", "daily"): "baostock_daily",
    ("baostock", "cn_stock", "minute"): "baostock_minute",
    ("baostock", "cn_index", "daily"): "baostock_index_daily",
    ("binance", "crypto", "daily"): "binance_klines",
}

# 具备「内部多级回退」的源：豁免【市场级】失败计数，但【源级】失效仍须熔断。
INTERNAL_FAILOVER_SOURCES = {
    "akshare": {
        "internal_failover": True,
        "max_consecutive_failures": 5,       # 高于默认 3：单点市场失败宽限，源级失效仍熔断
        "counts_market_level_failure": False,
        "counts_source_level_failure": True,
        "why": "akshare 内部已是 东财→新浪→BaoStock 多级回退；单个市场接口挂了不应整源熔断，"
               "但所有内部路径连续失败 = 源级失效，必须熔断（否则反复重连 = 封 IP 触发条件）",
    },
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

# ==================== 指数（基准 / 择时用，不可直接交易） ====================
# 指数本身不可买卖，仅用于：回测基准、择时信号、指数增强、宽基/行业强弱对比。
# 取数必须走【指数专用接口】（AKShare index_zh_a_hist / stock_zh_index_daily、
# BaoStock sh.000300、东财 index_zh_a_hist_min_em），
# 禁止复用个股接口——否则指数代码会被当股票代码，取回错误序列或空表（静默错误）。
CN_INDEX = {
    "name": "指数（基准/择时）",
    "tradeable": False,                 # 不可直接交易，订单层必须拒绝
    "min_qty": 1,
    "qty_step": 1,
    "price_step": 0.01,
    "t_plus": 0,
    "trade_direction": [],              # 空 = 不允许下单
    "commission_rate": 0,
    "commission_min": 0,
    "stamp_tax_rate_sell": 0,
    "stamp_tax_rate_buy": 0,
    "transfer_fee": 0,
    "margin_rate": 1.0,
    "leverage": 1.0,
    "price_limit": {},
    "trading_hours": [(9 * 60 + 30, 11 * 60 + 30), (13 * 60, 15 * 60)],
    "can_short": False,
    "liquidity_min": 0,
    "common_codes": {                   # 常用宽基/行业指数（标准 6 位代码）
        "000001": "上证指数", "000300": "沪深300", "000905": "中证500",
        "000852": "中证1000", "932000": "中证2000", "000016": "上证50",
        "000688": "科创50", "399001": "深证成指", "399006": "创业板指",
        "399673": "创业板50", "000010": "上证180", "000009": "上证380",
    },
}

# 带 sh/sz/bj 前缀的指数识别规则：先剥前缀，再看是否落在指数号段。
# 注意 sh600519->cn_stock、sh510300->cn_etf 是常规写法，绝不能一律判为指数。
# v3.41 补 BJ：北交所指数号段为 899xxx（北证 50 = 899050.BJ 等国证/中证北交所系列）。
INDEX_PREFIX_RULES = {
    "SH": ("000", "950", "880", "881"),   # 上证 / 中证系列指数
    "SZ": ("399", "980", "981"),          # 深证 / 国证系列指数
    "BJ": ("899",),                       # 北证系列指数（北证50 899050.BJ 等）
}

# 裸 6 位指数代码识别白名单（不带 sh/sz/bj 前缀时使用）。
# ⚠️ 深市个股号段为 000/001/002/003，与沪市指数（000300 沪深300、000905 中证500、
#    000016 上证50、000688 科创50、000010 上证180、000009 上证380、000001 上证指数）
#    【完全重合】，裸写无法可靠区分——例如 000001 既是上证指数也是平安银行、
#    000009 既指上证380 又是中国宝安、000016 既是上证50 也是深康佳A。
# 因此本白名单【只收录确定不与深市个股号段冲突的代码】：
#   - 399xxx：深证系列指数（深市个股不在 399 段）
#   - 932xxx：中证 2000 等特殊号段
# 000xxx 段的指数【必须带前缀】（sh000300 / sh000905 / sh000016 / sh000688），
# 否则会被判为深市个股。取指数行情推荐一律写带前缀形式，最稳。
CN_INDEX_BARE_CODES = {
    "399001": "深证成指",
    "399005": "中小板指",
    "399006": "创业板指",
    "399673": "创业板50",
    "932000": "中证2000",
}

# v3.41：指数别名【单一来源】——所有中文别名、大小写别名、英文别名统一在这里维护，
# data/pit_index.py::index_aliases() 必须从本常量派生，模块内严禁自定义 _INDEX_ALIASES。
# 规则：key 统一为小写无空格；value 为标准 6 位代码（不带前缀）。
# 别名识别时先做 lower+去空格再查表，避免「沪深300」/「hs300」/「HS300」漏判。
CN_INDEX_ALIASES = {
    # 宽基/主流指数
    "上证指数": "000001", "上证综指": "000001", "sh000001": "000001", "sse composite": "000001",
    "深证成指": "399001", "sz399001": "399001", "szse component": "399001",
    "沪深300": "000300", "hs300": "000300", "csi300": "000300", "sh000300": "000300",
    "中证500": "000905", "zz500": "000905", "csi500": "000905", "sh000905": "000905",
    "中证1000": "000852", "zz1000": "000852", "csi1000": "000852", "sh000852": "000852",
    "中证2000": "932000", "zz2000": "932000", "csi2000": "932000",
    "上证50": "000016", "sz50": "000016", "sse50": "000016", "sh000016": "000016",
    "上证180": "000010", "sse180": "000010", "sh000010": "000010",
    "上证380": "000009", "sse380": "000009", "sh000009": "000009",
    "科创50": "000688", "kc50": "000688", "star50": "000688", "sh000688": "000688",
    "创业板指": "399006", "cyb": "399006", "cybz": "399006", "chinext": "399006", "sz399006": "399006",
    "创业板50": "399673", "cyb50": "399673", "sz399673": "399673",
    # 北交所指数
    "北证50": "899050", "bz50": "899050", "bj899050": "899050", "bjse50": "899050",
}

# 个股号段表（v3.41：与 INDEX_PREFIX_RULES 配对，用于后缀 + 段位联合判定；
# 与 detect_market_type 内的 6 位数字判定保持一致）
STOCK_PREFIX_RULES = {
    "SH": ("600", "601", "603", "605", "688", "689"),   # 沪市主板 + 科创板
    "SZ": ("000", "001", "002", "003", "300", "301"),   # 深市主板 + 创业板
    # v3.43 修正：北交所自 2025-10-09 起【全面启用 920 专属号段】，43/83/87 三号段
    #   已【退出北交所舞台】（Tushare bse_mapping 官方口径：此举「为了将北交所股票与
    #   新三板股票在代码上彻底区分」）。因此 BJ 段【只能是 920】；
    #   43/83/87/88 + .BJ 后缀 = 陈旧写法，见 BSE_CODE_MIGRATION，不得再判为北交所。
    "BJ": ("920",),
}

# 北交所代码迁移（v3.43 新增）
#   2025-10-09 起北交所存量股【全面切换 920 专属号段】，43/83/87 三号段退出北交所。
#   Tushare 官方 bse_mapping 接口：全表 248 条，「理论上以后也不会再更新」，可整表落盘。
#   ⚠️ 全表【必须从数据源落盘】，禁止在 config 里手写 248 条（手抄 = 第二份实现 = 必分叉）。
#   anchors 仅放【已核实的少量锚点】（官方接口文档示例）用于自检；查不到 = raise，绝不猜归属。
BSE_CODE_MIGRATION = {
    "mapping_source": "tushare:bse_mapping",
    "local_file": "data_cache/bse_mapping.csv",
    "effective_date": "2025-10-09",          # 旧段（43/83/87/88）退出北交所之日
    # v3.44 增：920 段自身的【生效日】——北交所 2024-04-22 上线启用 920 号段功能
    #   （2024-05-30 万达轴承 920002 为首只）。as_of 早于该日时 920 段尚不存在，
    #   判 bj_stock 即「引用当时不存在的代码」= 未来函数，必须 raise。
    "segment_effective_date": "2024-04-22",
    "columns": {"old": "o_code", "new": "n_code", "name": "name"},
    "on_missing_local_table": "raise_with_guidance",
    "anchors": {   # 官方接口文档示例（10 条，非全表）
        "839729": "920729", "839167": "920167", "838163": "920163",
        "837242": "920242", "836433": "920433", "430476": "920476",
        "430425": "920425", "430300": "920300", "430139": "920139",
        "430017": "920017",
    },
}

# ==================== 代码自动识别市场 ====================
MARKET_CODE_RULES = {
    "us_stock":     {"prefix": [], "suffix": [], "alphas_6_only": False, "numeric": False},
    "hk_stock":     {"prefix": ["0"], "numeric_5": True},
    "cn_index":     {"prefixed_sh": ["000", "950", "880", "881"],
                     "prefixed_sz": ["399", "980", "981"],
                     "prefixed_bj": ["899"],          # v3.41：北证系列指数（北证50 等）
                     "dotted_sh": ["000", "950", "880", "881"],
                     "dotted_sz": ["399", "980", "981"],
                     "dotted_bj": ["899"]},
    "cn_reits":     {"prefix": ["508", "180"]},
    "cn_convertible":{"prefix": ["11", "123", "127", "128", "113", "110", "111", "123"]},
    "cn_etf":       {"prefix": ["51", "52", "56", "58", "15", "16", "18"]},
    # v3.43 修正：920 段是北交所【专属】号段（与新三板「彻底区分」），不得再放进 neeq；
    #   43/83/87/88 段自 2025-10-09 起【只属新三板】。
    "neeq":         {"prefix": ["43", "83", "87", "88"]},
    "bj_stock":     {"prefix": ["920"]},   # v3.43：北交所个股【专属】920 段（无歧义，无需后缀消歧）
    "cn_future":    {"letter_digit_mix": True},
    "global_future":{"letter_only": True, "max_len": 3},
    "forex":        {"6_letter_ccy": True},
    "crypto":       {"letter_only": True, "min_len": 2, "max_len": 5},
    "option":       {"suffix_pattern": True},
    # v3.41：接受的点后缀清单（Tushare/Wind/聚宽/AkShare 标准写法：600519.SH / 000001.SZ / 899050.BJ）
    "accepted_dot_suffixes": ["SH", "SZ", "BJ"],
}

def _resolve_bse_body(body: str, as_of: str = None) -> str:
    """判定「带北交所标记的 6 位号码」属于北交所还是陈旧码（v3.43 新增）。

    - 920 段：北交所【专属】号段，2024-04-22 上线启用。
        · 给了 as_of 且 as_of < 2024-04-22 -> 当时尚无此号段 -> raise（未来函数）；
        · 否则 -> "bj_stock"。
    - 43/83/87/88 段：2025-10-09 之前为北交所（精选层平移），之后该段【只属新三板】。
        · 给了 as_of 且 as_of < 2025-10-09 -> 当时确为北交所 -> "bj_stock"（历史可复现）；
        · 否则 = 陈旧写法：查 BSE_CODE_MIGRATION，命中则仍归北交所（码已迁 920）；
          未命中 -> raise（绝不静默归入 neeq / cn_stock 任一市场）。
    - 其它段位 -> 段位与北交所标记真冲突 -> raise。
    """
    if body.startswith("920"):
        # v3.44：920 段本身有生效日（2024-04-22 启用）。as_of 早于该日 -> 当时 920 段尚未存在，
        #   此处判 bj_stock 就是「把未来的代码用在过去」= 未来函数，必须 raise（禁止静默放行）。
        if as_of and str(as_of) < BSE_CODE_MIGRATION["segment_effective_date"]:
            raise ValueError(
                f"代码 {body} 属北交所 920 段，该号段自 "
                f"{BSE_CODE_MIGRATION['segment_effective_date']} 才上线启用；"
                f"as_of={as_of} 时该代码尚不存在（未来函数），请核对数据日期。"
            )
        return "bj_stock"
    if body[:2] in ("43", "83", "87", "88"):
        if as_of and str(as_of) < BSE_CODE_MIGRATION["effective_date"]:
            return "bj_stock"
        if body in BSE_CODE_MIGRATION["anchors"]:
            return "bj_stock"   # 已迁 920，市场归属不变；规范化新码由 data/pit_index.normalize_symbol 产出
        raise ValueError(
            f"北交所代码 {body} 属 2025-10-09 前旧号段（43/83/87/88），已迁至 920 专属号段，"
            f"该写法已失效。请改用 920 新码；或把 bse_mapping 全表落盘到 "
            f"{BSE_CODE_MIGRATION['local_file']} 后重试（禁止猜测市场归属）。"
        )
    raise ValueError(
        f"代码 {body} 与 .BJ 后缀冲突：北交所只有 920 段个股与 899 段指数，"
        f"{body} 不属任一（如 600519.BJ = 段位与后缀矛盾）。"
    )

def detect_market_type(code: str, market_type: str = None, as_of: str = None) -> str:
    """根据代码前缀/格式自动识别市场类型，返回 MARKET_CONFIG_MAP 中的 market_type 键之一。

    注意：
    - 6位A股/ETF/基金/转债的代码段本身存在歧义（如00开头既可能是深市个股也可能是基金），
      纯字母短代码（2-3位）在美股/期货/加密之间也存在歧义。本函数按"最常见场景"给出默认值，
      遇到歧义时请显式传入 market_type 参数覆盖（取数/回测/下单函数都支持该参数）。
    - 2~3位纯字母（未在已知白名单中）默认判定为 us_stock，因为美股代码量远大于国际期货品种；
      国际期货/外汇/加密等2~3字母品种请显式传入 market_type 参数。
    - 取市场规则参数必须通过 config.get_market_config(market_type) 统一访问，
      禁止直接写 config.MARKETS[market_type]——MARKETS 字典只包含7个零售市场，
      其余12类市场（含 cn_index 指数基准层）在独立字典中，直接访问会触发 KeyError。
    """
    # 显式传入 market_type 时以调用方为准（用于消解 000001、CL 等天然歧义代码）
    if market_type:
        return market_type

    code = str(code).strip()

    # ===== 指数别名（v3.41）：中文 / 大小写 / 英文 / 带前缀写法统一来自 CN_INDEX_ALIASES =====
    # v3.41 必须【先于所有其它分支】：汉字与字母都满足 str.isalpha()，若不在此拦截，
    # 「沪深300」「hs300」「北证50」会命中下方「字母+数字 = cn_future」的贪心分支，
    # 被当作国内期货去取新浪主力连续数据（静默错误数据）。
    # 规则：key 统一小写无空格；查表前 lower + 去空格归一化。
    if code.lower().replace(" ", "") in CN_INDEX_ALIASES:
        return "cn_index"

    code = code.upper()

    # ===== 点后缀写法（600519.SH / 000001.SZ / 899050.BJ · Tushare/Wind/聚宽/AkShare 标准）=====
    # v3.41：必须先于其他判定，否则 899050.BJ 会被当「字母+数字=cn_future」静默错判。
    _dot_suffixes = MARKET_CODE_RULES.get("accepted_dot_suffixes", ["SH", "SZ", "BJ"])
    if "." in code:
        body, dot_suffix = code.rsplit(".", 1)
        if dot_suffix in _dot_suffixes and len(body) == 6 and body.isdigit():
            # 指数优先：body 落在该后缀对应指数号段 → cn_index
            idx_segs = MARKET_CODE_RULES["cn_index"].get(f"dotted_{dot_suffix.lower()}", ())
            if any(body.startswith(seg) for seg in idx_segs):
                return "cn_index"
            # v3.43 修正：.BJ 后缀【只对北交所有意义】，而 2025-10-09 起北交所只有 920 段。
            #   body 是 899 段 → 已在上面判为 cn_index（北证系列指数）。
            #   body 是 920 段 → 北交所个股（bj_stock）。
            #   body 是 43/83/87/88 段 → 【陈旧写法】：该码 2025-10-09 前是北交所、之后已迁移。
            #     旧段 + .BJ 后缀 = 段位与后缀真冲突，绝不静默归入任一市场（原来静默返回 cn_stock）。
            if dot_suffix == "BJ":
                return _resolve_bse_body(body, as_of)
            return detect_market_type(body, as_of=as_of)

    # ===== A股6位数字 =====
    if len(code) == 6 and code.isdigit():
        p3, p2, p1 = code[:3], code[:2], code[:1]
        # 裸 6 位指数（仅白名单内的无歧义号段：399xxx / 932xxx）
        if code in CN_INDEX_BARE_CODES:
            return "cn_index"
        # 国债逆回购：204开头（沪）、1318开头（深）
        if p3.startswith("204") or p3.startswith("131"):
            return "cn_reverse_repo"
        # 公募REITs：508/180开头
        if p3 in ("508",) or p3.startswith("180"):
            return "cn_reits"
        # v3.43：920 段是北交所【专属】号段（无歧义、无需后缀），优先判 bj_stock。
        # v3.44：920 段有生效日（2024-04-22）；as_of 早于该日时该代码尚不存在 -> 未来函数 raise。
        if p3 == "920":
            if as_of and str(as_of) < BSE_CODE_MIGRATION["segment_effective_date"]:
                raise ValueError(
                    f"代码 {code} 属北交所 920 段，该号段自 "
                    f"{BSE_CODE_MIGRATION['segment_effective_date']} 才上线启用；"
                    f"as_of={as_of} 时该代码尚不存在（未来函数）。"
                )
            return "bj_stock"
        # 新三板：43/83/87/88 开头（裸码默认 neeq）
        # v3.44：as_of 早于 2025-10-09 时，该段【当时仍属北交所】（2025-10-09 才迁出）-> bj_stock。
        if p2 in ("43", "83", "87", "88"):
            if as_of and str(as_of) < BSE_CODE_MIGRATION["effective_date"]:
                return "bj_stock"
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
        # 例：000001平安银行、000002万科A、000858五粮液、002415海康威视、003816中国广核
        if p3 in ("000", "001", "002", "003"):
            return "cn_stock"
        # 场外公募基金：004~009开头（场外号段）、16开头（LOF）
        # 例：005827易方达蓝筹精选、161725招商中证白酒(LOF)
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

    # ===== 带 sh/sz/bj 小写前缀（8 位，如 bj899050）：指数优先，其余剥前缀后按 6 位规则继续判定 =====
    # 必须先于"字母+数字=国内期货"判定，否则 sh000001 / sh000300 / bj899050
    # 会被误判为 cn_future，进而返回新浪期货主力连续数据（静默错误数据）。
    # 注意：sh600519->cn_stock、sh510300->cn_etf 属常规写法，只有落在指数号段才算指数；
    # v3.43：bj920xxx -> bj_stock（北交所），bj830xxx 等旧段 -> 陈旧码（见 _resolve_bse_body）。
    if len(code) == 8 and code[:2] in ("SH", "SZ", "BJ") and code[2:].isdigit():
        prefix, digits = code[:2], code[2:]
        if digits.startswith(INDEX_PREFIX_RULES[prefix]):
            return "cn_index"
        if prefix == "BJ":
            return _resolve_bse_body(digits, as_of)
        return detect_market_type(digits, as_of=as_of)   # 剥前缀后按标准 6 位规则重判

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
        # 3字母美股ETF白名单（与个股分开，避免 SPY/QQQ 等被误判为个股）
        known_us_etf3 = {
            "SPY", "QQQ", "DIA", "IWM", "GLD", "SLV", "USO", "TLT",
            "HYG", "LQD", "XLF", "XLK", "XLE", "XLV", "XLI", "XLP",
            "XLU", "XLB", "XLY", "XLC", "XLRE", "VXX", "UVXY", "ARKK",
        }
        # 3字母美股个股白名单
        known_us_stock3 = {
            "F", "GM", "GE", "IBM", "JPM", "BAC", "WFC", "C", "GS",
            "MS", "USB", "AXP", "V", "MA", "KO", "PEP", "MCD", "NKE",
            "SBUX", "T", "VZ", "DIS", "NFLX", "WMT", "TGT", "COST",
            "HD", "LOW", "CVX", "XOM", "COP", "BA", "CAT", "DE",
            "MRK", "PFE", "JNJ", "UNH", "ABBV", "LLY", "BMY", "AMD",
            "INTC",
        }
        if code in known_crypto:
            return "crypto"
        if code in known_futures:
            return "global_future"
        if code in known_us_etf3:
            return "us_etf"
        if code in known_us_stock3:
            return "us_stock"
        # 4位及以上纯字母：默认美股个股（A股/港股/期货/外汇都已在上面规则处理）
        if L >= 4:
            return "us_stock"
        # 2-3位纯字母兜底：默认美股个股（美股代码量远大于国际期货品种，国际期货/外汇/加密请显式传market_type参数覆盖）
        return "us_stock"

    # 带连字符/点的代码，默认美股（如 BRK.B）
    if "." in code or "-" in code:
        return "us_stock"

    # 兜底归入场外公募基金（建议显式指定 market_type）
    return "cn_fund"

# ==================== 天然歧义代码（短代码天生二义，调用方须显式传 market_type） ====================
# 命中这些代码时，detect_market_type 若未收到显式 market_type，
# 不应静默二选一，而应返回 primary + 在 attrs/日志中标注 ambiguous_market / market_candidates
AMBIGUOUS_CODES = {
    "ZN": {"primary": "global_future", "candidates": ["cn_future", "global_future"],
           "note": "ZN 既是沪锌(国内期货)也是10年期美债(国际期货)"},
    "GC": {"primary": "global_future", "candidates": ["global_future", "us_stock"],
           "note": "GC 既是COMEX黄金(国际期货)也是高露洁(美股)"},
    "000001": {"primary": "cn_stock", "candidates": ["cn_stock", "cn_fund"],
               "note": "000001 既是平安银行(深市个股)也是华夏成长(场外公募)"},
}

# ==================== 统一市场参数访问（19类全覆盖） ====================
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
    "cn_index":        ("CN_INDEX", None),
    "neeq":            ("NEEQ", None),
    "bj_stock":        ("BSE", None),           # v3.43：北交所独立成市（此前误并入 cn_stock，规则全错）
    "private_fund":    ("PRIVATE_FUND", None),
    "qii_product":     ("QII_PRODUCT", None),
    "otc_deriv":       ("OTC_DERIV", None),
}
ALL_MARKET_TYPES = list(MARKET_CONFIG_MAP)

def get_market_config(market_type: str) -> dict:
    """统一获取19类市场中任一市场的交易规则参数，禁止直接写 config.MARKETS[...]。
    原因：MARKETS字典只包含7个零售市场，其余12类市场（含 cn_index 指数基准层）在独立字典中，
    直接访问会触发KeyError。
    """
    entry = MARKET_CONFIG_MAP.get(market_type)
    if entry is None:
        raise KeyError(f"未知市场类型: {market_type}，可用市场: {ALL_MARKET_TYPES}")
    dict_name, sub_key = entry
    d = globals()[dict_name]
    return d if sub_key is None else d[sub_key]

# ==================== 第 10 步：合格投资者层（合规闸门，v3.28 新增） ====================
# 合规红线：三套门槛并行、不得混用；校验是「每个动作的闸门」而非「一次性资格标记」；必须穿透核查。
QUALIFIED_INVESTOR_RULES = {
    # —— 三套法定门槛并行（不同产品适用不同法规，禁止混用/取交集以外的宽松解释）——
    "private_fund": {                      # 《私募投资基金监督管理暂行办法》第12条
        "legal_basis": "证监会令第105号",
        "individual": {"financial_assets_wan": 300, "avg_annual_income_wan_3y": 50},
        "institution": {"net_assets_wan": 1000},
        "min_per_product_wan": 100,
        "max_investors": 200,
    },
    "amr_product": {                       # 资管新规《关于规范金融机构资产管理业务的指导意见》第5条
        "legal_basis": "银发〔2018〕106号",
        "individual": {"family_fin_net_assets_wan": 300, "family_fin_assets_wan": 500,
                       "avg_annual_income_wan_3y": 40, "min_invest_years": 2},
        "institution": {"net_assets_wan": 1000},
        "min_per_product_wan": {"fixed_income": 30, "mixed": 40, "equity": 100, "derivatives": 100},
        "max_investors": 200,
    },
    "trust_plan": {                        # 《信托公司集合资金信托计划管理办法》第6条
        "legal_basis": "银监会令2007年第3号",
        "individual": {"fin_assets_wan": 100, "annual_income_wan_3y": 20,
                       "couple_annual_income_wan_3y": 30},
        "min_per_product_wan": 100,
        "max_natural_persons": 50,         # 单笔委托≥300万的自然人不受此限
    },
    # —— 判定与执行（关键：闸门收口、逐动作校验、fail-closed）——
    "check_at_every_action": True,         # 每个申购/受让动作都校验，非一次性资格标记
    "check_actions": ["subscribe", "transfer", "additional_subscribe", "nominee_change"],
    "look_through_required": True,         # 穿透核查最终投资者，合并计算人数（防凑人头）
    "forbid_pooling_nominee_split": True,  # 禁拼单/代持/拆分份额/借用他人名义
    "forbid_non_own_funds": True,          # 禁用贷款、发行债券等非自有资金投资
    "on_fail": "reject",                   # 校验不过→拒绝该动作（不是"提醒"）
    "audit_log_required": True,            # 每次校验留痕，供监管与纠纷举证
    # —— 2026 年新规：须区分「已发布待施行」与「征求意见稿」，不得笼统写"尚未生效" ——
    "published_2026": {
        "资产管理信托管理办法": {"status": "已发布待施行", "issue_date": "2026-10-30",
                                 "effective_date": "2027-01-01", "max_investors": 200,
                                 "recheck_on": ["buy", "transfer"]},
        "私募投资基金监督管理办法": {"status": "征求意见稿",
                                     "note": "自然人LP投向单一标的专项基金门槛拟提至1000万"},
    },
}

# 净值型产品口径与费用（关键：三层净值不得混用；披露只用投资者层费后净值）
NAV_PRODUCT_CONFIG = {
    "nav_layers": ["product_gross", "product_net", "investor_net"],  # 三层口径
    "disclosure_layer": "investor_net",          # 对外披露固定用投资者层费后净值
    "disclosure_frequency": {"private_fund": "weekly", "qii_product": "weekly",
                             "trust_plan": "weekly", "cn_reits": "daily"},
    "disclosure_lag_days": {"private_fund": 2, "qii_product": 2, "trust_plan": 2, "cn_reits": 1},
    "enforce_decision_after_disclosure": True,   # 断言 decision_date >= disclosure_date + lag
    "fee_model": {
        "management_fee_annual_pct": 0.015,      # 年化，逐日计提
        "performance_fee_pct": 0.20,             # carry，高水位法
        "custodian_fee_annual_pct": 0.002,
        "subscription_fee_pct": 0.01,
        "redemption_fee_by_holding_days": {"<7": 0.015, "<30": 0.005, ">=30": 0.0},
    },
    "carry_is_per_investor": True,               # 业绩报酬 per-investor；单一产品净值曲线算不出
    "redemption_settlement_days": {"private_fund": 3, "qii_product": 3, "trust_plan": 3},
    "forbid_nav_as_kline": True,                 # 净值序列禁用 K 线类指标（对接第3步 nav_only_markets）
}

# 对外披露口径（第四个输出口：面向投资者，合规效力）
DISCLOSURE_CONFORMANCE = {
    "is_output_port": True,
    "must_share_engine_source": True,
    "must_include_fee_breakdown": ["subscription", "redemption", "management",
                                   "performance", "custodian"],
    "must_include_suppression": True,            # 须披露被闸门拦截的信号
    "must_label_type": ["backtest", "paper", "live"],   # 须标注回测/模拟/实盘
    "forbid_selective_period": True,             # 禁只报最有利区间
    "forbid_guarantee_wording": True,            # 禁"保本/保收益/零风险"字样
    "require_risk_disclosure": True,             # 须附风险揭示
    "require_qi_audit_trail": True,
}

# ==================== CLI 控制平面一致性（第 11 步） ====================
# 一键入口（main.py）是「控制平面」：它是唯一由人直接决定「跑到哪个模式 / 用哪份数据 /
# 开不开闸门」的地方，因此也是全部闸门的「总旁路」——控制平面上的一个开关，就能把
# 前面所有闸门一起关掉。RUN_MODE 是所有闸门的豁免开关（backtest 下 stale 闸门豁免等）。
CLI_CONFORMANCE = {
    "entry": "main.py",
    "run_mode_source": ["config.py", ".env"],          # RUN_MODE 唯一来源，禁止 CLI 提升
    "mode_may_only_downgrade": True,                   # CLI 只允许降到更安全一侧
    "mode_order": ["backtest", "paper", "live"],       # 安全 → 风险
    "promote_requires": ["checklist_pass", "paper_days_no_incident", "explicit_confirm_flag"],
    "forbidden_flags": ["--no-gate", "--force", "--skip-freshness", "--ignore-warmup",
                        "--no-risk", "--disable-gate", "--skip-check"],
    "defaults_source": "config",                       # 子命令默认值必须引用 config，禁 argparse 写死
    "import_paths_must_use_data_layer": True,          # --data/--csv/--from-file 须挂三物化列
    "must_feed_columns": ["warmup_ok", "data_asof_date", "price_adjust"],
    "checklist_mode": "four_count",                    # 清单须报 已跑/未跑/跳过/失败
    "readme_must_mark_unimplemented": True,            # README 须标注尚未实现的能力
    "progress_percent_honest": True,                   # 看板完成百分比不得含未完成步骤
    "thin_entry": True,                                # v3.30：main.py 必须是薄分发器，子命令进 cli_commands/
    "max_entry_lines": 300,                            # 入口与各子模块行数硬上限（长文件写入会损坏）
    "command_modules_dir": "cli_commands",
    "forbidden_flags_check_mode": "structural",        # v3.31：禁参须「结构性」校验——不能只比字符串（改个名就绕过）
}

# ==================== 实盘安全（第 12 步 · v3.31 新增） ====================
# 核心：第 12 步是系统第一次「指令能真的动到钱」。前 11 步的闸门都是「对数据的事前检查」
# （数据新不新 / 指标过没过预热 / 标的合不合格 / 这笔单该不该下），检查的是「这一刻的信息」；
# 而实盘第一次要面对三类前 11 步从未处理的问题——身份（同一意图会不会被执行两次）、
# 时序（本地账本与券商账本谁说了算）、存续（急停之后重启，急停还算不算数）。
# 闸门再多，也挡不住「同一笔单被报两次」，也修不好「本地账本算错仓位」。
LIVE_SAFETY = {
    # ① 幂等：自动断线重连（12.2）+ 崩溃自动重启（12.8）会制造「同一信号被消费两次」的条件
    "idempotency": {
        "key": "client_order_id",
        "format": "{strategy_id}-{symbol}-{yyyymmdd}-{seq}",
        "dedup_window_sec": 900,              # 同键在此窗口内重复提交 → 拒绝
        "persist_path": "live_trading/order_ids.json",   # 必须落盘、跨重启保留
        "on_duplicate": "reject",
        "on_unknown_state": "query_broker_first",        # 超时/断连时先查券商是否已受理，禁止盲目重发
    },
    # ② 对账：权威在券商侧，本地账本只是「可能过期的副本」（同第 2 步 attrs 之教训）
    "reconcile": {
        "authoritative": "broker",
        "on_start": True,
        "before_order": True,                 # 每次报单前核对
        "interval_sec": 60,                   # 盘中定时核对（12.10 的收盘对账保留为日终强校验）
        "on_mismatch": "halt_new_orders",     # 不一致 → 立即停开新仓并告警（不是只写一份报告）
        "resume_requires": "manual_confirm",
    },
    # ③ 出站唯一收口：任何真实报单只允许经过一个地方
    "order_port": {
        "choke_point": "live/live_trader.py:submit_via_gate",
        "adapters_implement_primitives_only": True,      # 适配器只实现「发单原语」，不实现「决策」
        "forbid_direct_broker_call": True,
        "forbid_sdk_import_outside_broker_dir": ["xtquant", "ths_ptrade", "ctp"],  # 防绕过收口
    },
    "forbid_silent_mode_fallback": True,      # 12.5「上层无感」的反面：模式必须显式，实盘连不上就停机
    "mode_must_be_tagged_on_every_order": True,          # 每笔报单/回报/报告都标 backtest/paper/live
    "mode_change_requires_flat": True,        # 切模式（含降级）前须无持仓、无在途单
    "first_live_order_max_notional": 10000,   # 首笔实盘小额，确认通道正常后再放开
    "personal_derivatives_live_forbidden": True,  # 个人禁止实盘场外衍生品：硬拦，不得只打印提示
    "kill_switch_persist": True,              # 12.15 急停：状态持久化，重启后仍处于停机态
}

# ==================== 报单出站一致性（第 12 步 · v3.31 新增） ====================
ORDER_PORT_CONFORMANCE = {
    "egress_points": ["live_order_submit", "watch_only_live_push"],  # v3.34 补：notifier/run_live 的 watch-only 推送是第 6 出口，同样要过闸门
    "watch_only_push_requirements": ["warmup_ok", "fresh_data", "in_session"],  # v3.34：仅看盘推送也要过三关；任一不过只推风险提醒、不推交易信号
    "choke_point": "live/live_trader.py:submit_via_gate",
    "must_call_gate": "core/signal_gate.py",      # 信号有效性（预热期/时效/开严平宽）——12.7 原文只写了「先过风控」，漏了本闸门
    "must_call_risk": "core/risk.py",             # 仓位/亏损/杠杆
    "must_call_qi": "core/qualified_investor.py",  # 净值型合规（若涉）
    "must_feed_columns": ["warmup_ok", "data_asof_date", "price_adjust"],  # 缺列报错
    "require_client_order_id": True,              # 无幂等键不得出站
    "require_reconcile_ok": True,                 # 未对账通过不得出站
    "block_when_kill_switch_on": True,
    "forbid_direct_broker_call": True,
    "all_adapters_register_here": True,
}

# ==================== 长期可用性：缓存治理（第 13 步 · v3.32 新增） ====================
# 教训：13.9 的「按 LRU / 按保留期清理」与第 11~13 步刚建立的「必须跨重启保留」的持久化状态
#       住在同一目录树下，而清理器根本不认识它们——「越冷越该删」与「越冷越重要」直接冲突，
#       而且删除不报错。守卫的载体被清理器当垃圾删掉 = 守卫静默消失。
CACHE_GOVERNANCE = {
    "enabled": True,
    "dry_run_default": True,            # 默认只报告不删除；必须显式 --apply 才真删
    "require_reference_check": True,    # 删除前先查引用（报告引用的快照、快照引用的原始数据）
    "protected_paths": [                # 任何容量/保留期策略下都永不删除
        "live_trading/order_ids.json",       # 幂等键：删掉 = 跨重启幂等失效 = 重复下单
        "live_trading/kill_switch.json",     # 急停状态：删掉 = 重启后自动恢复交易
        "live_trading/positions_snapshot.json",
        "data_cache/data_manifest.json",     # 完整性基准：删掉 = 损坏检测失去参照、静默失效
        "data_cache/source_health.json",
        "reports/report_index.json",         # 报告索引：删掉 = 全部报告失联
    ],
    "protected_globs": [
        "audit_logs/**",                     # 哈希链：断一环则整链不可验证
        "data_cache/constituents/**",        # PIT 成分股：删掉 = 幸存者偏差静默回归
        "data_cache/adj_factors/**",         # 复权因子：删掉 = 复权价现算失败或静默退化成不复权
    ],
    "snapshot_evict_requires_no_refs": True,  # 快照仅在「无任何报告/结果引用」时才可清
    "deletion_must_be_logged": True,          # 每次真删留审计条目（删了什么/为什么/引用检查结果）
    "on_protected_hit": "skip_and_warn",      # 命中受保护项 → 跳过并告警，绝不静默删除
    "log_rotation_must_not_drop_live_records": True,   # logs/ 轮转不得波及 live_trading/ 与 audit_logs/
}

# ==================== 长期可用性：数据格式版本（第 13 步 · v3.32 新增） ====================
# 教训：13.2 的一次性迁移「中途崩溃 = 半迁移」，而 raw 与 qfq 残留【同名、同格式、看不出区别】
#       → 读取器只能猜 → 复权两次或完全不复权 = 静默错价。缓存必须自带口径标记，禁止猜。
DATA_VERSIONING = {
    "schema_version": 2,                 # 每次存储布局变更 +1
    "version_tag_field": "price_basis",  # 写入 parquet 元数据：raw / qfq / hfq / nav
    "version_tag_required": True,
    "on_missing_tag": "raise",           # 读不到标记 → fail-closed 报错，禁止按默认口径读取
    "on_unknown_basis": "raise",         # 不认识的口径 → 报错，不得静默回退
    # ---- v3.36：口径的「唯一权威 + 冲突裁决」——防止「标记本身」又变成会漂移的副本 ----
    "basis_authority": "parquet_metadata",       # 唯一权威：parquet 文件内元数据（随数据走、与数据同一次原子写入）
    "filename_basis_is_hint_only": True,         # 文件名里的口径仅作提示，不得作为判定依据
    "sidecar": {                                 # 边车文件只是过渡桥，不是第二权威
        "suffix": ".basis.json",
        "role": "bridge_only",                   # 仅服务 CSV-only / 无元数据环境
        "may_override_parquet": False,           # 边车永不覆盖 parquet 元数据
        "on_conflict_with_parquet": "raise",     # 两者不一致 → 报错，不猜
        "deprecate_after_all_migrated": True,
    },
    "on_multi_basis_same_symbol": "raise",       # 同一标的多口径并存（raw 与 hfq 同名）→ 报错
    "on_filename_tag_conflict": "raise",         # 文件名与元数据口径冲突 → 报错
    "stamp_legacy": {                            # 给存量无标记文件补标记的工具行为
        "method": "filename_and_source_semantics",   # 依据文件名与来源语义判定，不得仅凭「缺标记」就归 raw
        "on_ambiguous": "quarantine",            # 判不出 → 隔离待人工确认，绝不默认标 raw（qfq 内容标 raw = 复权两次）
        "quarantine_dir": "data_cache/_quarantine/",
        "idempotent": True,                      # 重复执行结果一致
        "preserve_mtime": True,                  # 不改 mtime，避免打乱 _cache_expired 判定
    },
    "atomic_write_with_marker": True,            # 标记与数据同一次原子写入，不留「已写数据、未写标记」窗口
    "legacy_qfq_cache": "forbid_read",   # 旧 qfq 缓存不得被读取：「启动时打印警告」不足以拦截
    "maintenance_lock_file": "data_cache/.maintenance.lock",
    "migration": {
        "script": "tools/migrate_cache_to_raw.py",
        "atomic": True,                  # 先写新目录 → 全量校验 → 再切指针；禁止就地改名/覆盖
        "resumable": True,               # 中断后可续跑，且能识别已完成分片
        "rollback_kept": True,           # 旧缓存保留为 .bak，新缓存校验通过后才清理
        "requires_maintenance_lock": True,   # 迁移期间禁止写入（拉数/回测/实盘全部停）
        "verify_before_switch": True,    # 切换前逐标的重算复权价并与旧缓存对拍
    },
}

# ==================== 长期可用性：正确性闸门必须装在入口（第 13 步 · v3.32 新增） ====================
# 教训：13.3/13.4/13.5 都只给了「独立 CLI / 一个 API」——没人调用就是死代码（同第 3 步 B1~B5）。
#       数据正确性类闸门必须在【读取/回测入口】强制生效；不能确认即 fail-closed。
SNAPSHOT_PIT_GUARD = {
    "integrity": {
        "enforce_on_read": True,             # 日常读取路径必须校验，不能只在 tools/verify_cache.py 里查
        "manifest": "data_cache/data_manifest.json",
        "hash_algo": "sha256",               # 统一口径（勿与 MD5 混用）
        "on_mismatch": "refetch_then_raise", # 自动重下仍不匹配 → 报错，禁止带伤继续
        "atomic_write": True,                # 先写 .tmp → 校验 → 原子 rename
    },
    "snapshot": {
        "create_at": "engine_entry",         # 由引擎在回测/研究入口强制生成，不靠调用方记得调
        "bind_to_result_meta": True,         # 结果 meta 必带 data_version=snapshot_id
        "missing_snapshot": "raise",         # 没有快照不允许产出「可复现」结论
        "forbid_skip_flag": True,            # 禁止「不传就跳过」的旁路
    },
    "pit": {
        "enforce_in_backtest": True,         # 取股票池必须走 get_index_members(index_code, date)
        "forbid_current_constituents": True, # 回测禁止读「当前成分股」
        "on_unavailable": "raise",           # 拉不到就报错
        # ---- v3.36：PIT 闸门收口在访问器（引擎无关），且成分股本身必须版本化 ----
        "guard_at": "accessor",                      # 闸门装在 data/pit_index.py::get_index_members，不只在某个引擎入口
        "universe_resolution_single_source": "data/pit_index.py::get_index_members",
        "engines_must_resolve_universe_via_pit": ["backtester", "runner", "paper_trader", "live_trader", "monitor"],
        "forbid_direct_constituents_read": True,     # 除 pit_index.py 外，任何模块不得直读 data_cache/constituents/**
        "factor_pool_must_use_pit": True,            # v3.37：因子计算的标的池也必须走 PIT，不只是选股 universe
        # ---- v3.38：PIT 闸门「按输入形态分层」，而不是「按是否调用 compute」无条件拦 ----
        #   教训：v3.37 修完 factor/universe 绕过后，闸门一度被写成 compute() 入口【无条件】断言，
        #   连显式传 ["600519","000001"] 也拦——但显式代码列表没有 index、没有成分股、没有幸存者偏差，
        #   属【过度拦截】：误伤传明确标的做研究的人；既有单测被迫处处设 enforce_in_factor=True（脆弱耦合）；
        #   一旦有人为跑通而关掉该键，PIT 的真实性一起被关掉——闸门变成了它要防的东西。
        #   正确边界：变量是「是否解析了指数成分股」，不是「是否经过 compute」。
        "enforce_scope": {
            "by_universe_kind": True,                 # 按输入形态分层，不按调用栈
            "explicit_code_list_requires_pit": False, # 显式代码列表无幸存者偏差 → 放行
            "index_token_requires_pit": True,         # 指数名/别名 → 必须走 PIT + as_of
            "allow_implicit_all_a": False,            # None 不得默认全A（隐式全A = 静默偏差）
            "unknown_token": "pit_or_raise",          # v3.39：未知形态不静默放行（见 UNIVERSE_RESOLUTION_GUARD.resolution_default）
        },
        "constituents_must_be_snapshotted": True,    # 成分股清单必须进快照，否则「时点正确」建立在可变缓存上、回测不可复现
        "constituents_immutable_per_as_of": True,    # 同一 as_of 日期的成分股一经落地不得被覆写
        "teaching_mode": {
            "allow": True,                   # 仅教学/演示可放行
            "watermark_field": "survivorship_bias_uncontrolled",
            "require_watermark_in_report": True,
            "watermark_is_sticky": True,     # 水印随报告进归档库与 stats，不得被后续流程抹掉
        },
    },
}

# ==================== 标的池解析唯一出口（第 13 步 · v3.37 新增） ====================
# 教训：v3.36 把 PIT 闸门收口到 data/pit_index.py::get_index_members；Trae 在核查五引擎时
#       自己发现了「第六个入口」factor/universe.py —— 它用 index_stock_cons* 拉【当前】成分股、
#       失败还回退内置静态清单且从不抛错。它不在五个执行器里，但研究/因子链路一旦拿它当标的池，
#       PIT 闸门等于没装；更要命的是【因子值本身】是用未来成分股算出来的 → 幸存者偏差从
#       「选股 universe」之外的第二道门进来，而回测的 universe 看起来是干净的。
#       规律：守卫装在【某个调用点】（backtester.prepare）而非【数据获取的唯一出口】，
#       就必然随「入口扩散」而漏装——本会话「单引擎守卫」的病在数据层的复制。
UNIVERSE_RESOLUTION_GUARD = {
    "single_accessor": "data/pit_index.py::get_index_members",   # 标的池/成分股的唯一出口
    "date_required": True,                       # 必带 as_of 日期参数
    "no_implicit_current": True,                 # 禁止「不传日期就取当前成分股」的隐式语义
    "on_missing_date": "raise",                  # 缺日期 → 报错；「当前成分股」语义在回测/研究上下文不可表达
    "forbidden_apis": [                          # 「当前成分股」类 API 在回测/研究/因子路径全面禁用
        "index_stock_cons", "index_stock_cons_csindex",
        "index_stock_cons_sina", "index_stock_cons_weight_csindex",
    ],
    "forbidden_api_scan_scope": ["core/", "factor/", "research/", "nav_backtest/", "cli_commands/", "tools/"],
    "forbidden_api_allowed_only_in": ["data/source_adapter.py"],   # 仅原始拉取层可用，且必须被 pit_index 包装
    "static_fallback": "forbid",                 # 拉不到就回退内置静态清单 = fail-open，全面禁止（改 raise）
    "on_static_fallback_attempt": "raise",
    "enumerate_all_universe_callers": True,      # 必须枚举全仓所有获取标的池的路径（不止 5 引擎）
    "callers_must_resolve_via_accessor": [
        "core/backtester.py", "core/runner.py", "core/paper_trader.py",
        "factor/universe.py", "research/", "nav_backtest/",
    ],
    "legacy_wrappers": {                         # 旧便捷函数必须降级为薄封装
        "module": "factor/universe.py",
        "functions": ["get_hs300", "get_zz500", "get_zz1000", "get_zz2000"],
        "require_date_param": True,              # 新增必填 date；无 date 调用 → raise
        "on_missing_date": "raise",
        "may_return_current_only_if": "as_of=now AND context=realtime",   # 只有实时盯盘上下文才可要「当前」
        "forbid_in_contexts": ["backtest", "research", "factor_build"],
    },
    "enforce_at": "call_time",                   # 收口在访问器本体（运行期），不靠一次性 grep
    # ---- v3.39：判据必须【默认拒绝】，禁止「白名单命中指数 -> PIT，否则当代码」的 fail-open ----
    #   教训：Trae 的实现是「字符串 ∈ _INDEX_CODES -> 走 PIT；否则 -> 当代码放行」。这是 fail-open：
    #   未命中的字符串（别名「沪深300」/ 大写「HS300」/ 带前缀「000300.SH」/ 拼写错误）被【静默当代码】，
    #   既不报错、也不过 PIT —— 闸门的触发条件依赖一个「能识别的名字清单」，清单漏项即静默绕过
    #   （与「信号出口清单」「标的池入口清单」枚举不完同族）。翻转：默认拒绝，能被判定为「代码」才放行。
    "resolution_default": "deny",                # 默认拒绝；只有确认是「代码」的输入才放行
    "unrecognized_token_is_not_code": True,      # 白名单未命中的字符串 != 代码 -> PIT 或 raise，绝不静默当代码
    "on_unrecognized_token": "raise_with_guidance",
    "code_shape_rule": {                         # 「是代码」必须是明确形态，禁止猜
        "require_market_prefix": True,           # 必须带交易所前缀：600519.SH / 000001.SZ / 830799.BJ / sh600519 / sz000001 / bj830799
        "accepted_patterns": [
            r"^\d{6}\.(SH|SZ|BJ)$", r"^[a-z]{2}\d{6}$",
        ],
        "bare_numeric_disambiguated_by": "index_registry",   # 裸 6 位数字必须与指数注册表比对
        "bare_numeric_conflict": "require_prefix",           # 与指数同名 -> 要求带前缀，拒绝替用户猜
        # ---- v3.40：【后缀与代码段「矛盾」即拒】是误判 —— .SH 的 000 段本来就是指数段 ----
        #   教训：把 000001.SH / 000300.SH 当成「看起来像指数」的写法【拒绝掉】，会同时:
        #   (a) 丢掉交易所标准写法；(b) 与 sh000300（同一实体的另一种写法，却放行）判定相反；
        #   (c) 与 config.CN_INDEX / CN_INDEX_BARE_CODES 口径分裂；(d) 逼用户改用别名，让别名表继续手写扩张。
        #   正确判据：后缀 + 代码段【联合】判定，无歧义输入直接放行，不搞「矛盾即拒」。
        "suffixed_input_uses_segment_decision": True,        # 带后缀的输入按段位判定，不做「矛盾即拒」
        "exchange_segment_rule": {
            # v3.41：段位表与 STOCK_PREFIX_RULES / INDEX_PREFIX_RULES 保持一致，BJ 段补齐
            "SH": {"index_segments": ["000", "950", "880", "881"],
                   "stock_segments": ["600", "601", "603", "605", "688", "689"]},
            "SZ": {"index_segments": ["399", "980", "981"],
                   "stock_segments": ["000", "001", "002", "003", "300", "301"]},
            "BJ": {"index_segments": ["899"],
                   "stock_segments": ["920"],               # v3.43：现行专属号段
                   "legacy_stock_segments": ["430", "830", "831", "832", "833", "834", "835",
                                             "836", "837", "838", "839", "870", "871", "872", "873"],
                   "legacy_effective_until": "2025-10-09",  # 之后旧段属新三板，不再属北交所
                   "legacy_on_suffix_bj": "resolve_via_bse_mapping_or_raise"},
        },
        "segment_decision_examples": {
            "000001.SH": "指数（上交所 000 段 = 上证指数）",
            "000300.SH": "指数（上交所 000 段 = 沪深300）",
            "000001.SZ": "个股（深交所 000 段 = 平安银行）",
            "399001.SZ": "指数（深交所 399 段 = 深证成指）",
            "600519.SH": "个股（上交所 600 段）",
            "899050.BJ": "指数（北交所 899 段 = 北证50）",
            "920309.BJ": "个股（北交所 920 专属段）",
            "920309": "个股（北交所 920 专属段，裸码无歧义）",
            "830799.BJ": "陈旧码（43/83/87 段已于 2025-10-09 迁 920，须查 bse_mapping 或 raise）",
        },
        "on_segment_conflict": "raise_with_guidance",        # 段位与后缀真冲突（如 399001.SH、600519.BJ）才报错
    },
    "index_registry_source": ["config.CN_INDEX", "config.CN_INDEX_BARE_CODES", "config.INDEX_PREFIX_RULES", "config.CN_INDEX_ALIASES"],
    # ---- v3.40：别名表必须【由 config 派生】，不得在模块内另起一份清单 ----
    #   项目里已有四份指数相关常量（CN_INDEX / CN_INDEX_BARE_CODES / INDEX_PREFIX_RULES / INDEX_MEMBER_DIR），
    #   factor/universe.py 再写一个 _INDEX_ALIASES 就是【第五份】：漏项即漏项，加项要改两处。
    #   v3.41：已在 config 顶层定义 CN_INDEX_ALIASES（中文/大小写/英文/带前缀别名统一来源）；
    #         index_aliases() 必须直接返回该常量派生后的结构，禁止模块内自定义。
    "index_alias_single_source": "config.CN_INDEX_ALIASES",   # 别名唯一来源
    "alias_normalize": "lower_strip",                          # 查表前 lower + 去空格
    "forbid_local_index_lists": True,             # 禁止在 core/ factor/ data/ 等模块内自定义 _INDEX_* 清单
    "forbid_local_index_lists_scan_scope": ["core/", "factor/", "data/", "research/", "nav_backtest/"],
    # ---- v3.41：get_index_members 是标的池唯一出口，直调必须先过 classify_symbol，否则直调即绕过 ----
    #   上一轮回执只要求「共用同一份 checker」，但没规定 checker 必须在【函数入口第一行】被调用；
    #   若 classify_symbol 只在「未命中缓存 → 调 API」分支里出现，直调 get_index_members("600519.SH")
    #   仍可能在缓存/降级路径里绕过检查 → fail-open。
    "get_index_members_must_share_checker": True,
    "get_index_members_must_call_classify_first": True,        # 函数入口第一行必须 classify_symbol(symbol)
    "classify_symbol_is_single_source": True,                  # classify_symbol 是唯一判定函数，resolve_universe / get_index_members 都必须调用它
    "known_ambiguous_symbols": {                 # 实测同名清单：同一字符串既可能是指数、也可能是个股
        "000001": "上证指数(000001.SH) vs 平安银行(000001.SZ) —— 必须带前缀",
        "000300": "沪深300指数(000300.SH)",
        "399001": "深证成指(399001.SZ)",
    },
    "current_constituents_audit": {              # 任何「当前成分股」调用必须留痕
        "record_as_of": True,
        "tag_research_use": True,                # 标记是否进入研究/回测产物，进入即拒
    },
}

# ==================== 长期可用性：报告归档一致性（第 13 步 · v3.32 新增） ====================
# 教训：① 保留期互相打架——报告活 2190 天、快照只活 365 天 → 第 366 天起 data_version 成死引用；
#       ② 一份报告 = HTML + JSON + parquet + 索引四份状态，删其一即悬空引用或统计漏项；
#       ③ 13.10 的元数据强校验只装在「生成入口」，归档库里的旧报告仍可被检索/统计 → 闸门只单向生效。
REPORT_ARCHIVE_CONFORMANCE = {
    "artifact_group": ["html", "json", "trades_parquet", "equity_parquet"],  # 四份同生共死
    "index_must_match_files": True,          # 索引 ↔ 文件双向一致；悬空引用必须可检出并报错
    "index_record_required_fields": ["meta_complete", "artifact_paths", "snapshot_id", "schema_version"],
    "meta_complete_flag": True,              # 每条索引记录标 meta_complete 真/假
    "legacy_reports": "flag_not_hide",       # 历史缺字段报告：打标，不隐藏、不删除
    "show_must_report_missing": True,        # report show 必须展示「缺哪些字段」
    "stats_default_filter": "meta_complete_only",   # 统计默认只吃可复现报告
    "stats_include_incomplete_flag": "--include-incomplete",
    "stats_must_declare_coverage": True,     # 输出须标明「含 N 份不可复现报告」
    "retention_dependency": {                # 保留期依赖：快照必须活得比引用它的报告久
        "rule": "snapshot_retention_days >= max(retention_days_daily, weekly, monthly, backtest)",
        "on_violation": "raise_at_boot",
    },
    "curve_is_disclosure_if_external": True, # stats 累计净值曲线若对外展示 → 落 investor_disclosure 出口
    "curve_must_use_layer": "investor_net",  # 且必须用投资者费后口径，不得用产品毛净值
}

# ==================== 全系统收尾一致性（第 13 步是最后一步 · v3.32 新增） ====================
# 第 13 步之后没有「下一步」可以装开工前置，因此本步的验收必须是【全系统】的，
# 且必须能机器验证——这是「三年后还能跑」唯一可执行的收尾。
SYSTEM_CONFORMANCE = {
    "gate_single_source": "core/signal_gate.py",   # 闸门只有一份实现，引擎只调用不重写
    "engines_must_call_gate": ["backtester", "paper_trader", "live_trader", "runner", "monitor", "notifier"],   # v3.34 补 notifier：与 13.13「六个入口」对齐
    "egress_points_must_all_pass_gate": True,       # 逐个出口验证：place_order/monitor_push/
                                                    # report_plan/investor_disclosure/live_order_submit
    "no_hardcoded_safety_value_outside_config": True,   # 阈值/上限/保留期不得硬编码在业务代码里
    "system_test": "tests/test_system_conformance.py",
    "test_must_be_table_driven": True,               # 按「出口 × 是否过闸门」逐格断言，不做整体冒烟
    "checklist_mode": "four_count",                  # 通过/失败/跳过/收集错误四类计数，缺一不可
    "universe_egress_points": ["backtester", "runner", "paper_trader", "live_trader", "monitor", "factor/universe", "research", "nav_backtest"],   # v3.37：标的池出口清单（不止引擎）
    "count_definition_stable": True,                 # v3.36：四类计数口径跨轮冻结；变更口径须显式声明，否则跨轮不可比
    "spec_authority_single_source": True,            # v3.46：规格正文单源发布；施工方自撰正文只能算 draft
    "test_data_count_must_be_reported_raw": True,    # v3.46：test_data 须报【原始】计数（本轮出现「12 组 vs 固定 13」不一致）
    "suite_coverage_must_not_shrink": True,          # v3.47：脚本侧套件【不得悄悄缩减】（本轮由 20 套缩为 9 套且无说明）
    "both_suite_sets_required": True,                # v3.47：根目录 9 套【与】tests 11 套都要逐套件报数
    "nondeterministic_script_cannot_be_sole_evidence": True,  # v3.47：项数会变的外部依赖脚本不得作为唯一合格证据
    "per_suite_breakdown_required": True,            # v3.36：必须逐套件给通过数（套件名 + 通过数），禁止只报合并总数或中途换口径
    "report_must_map_tests_to_guards": True,         # 报告须给出「测项 → 守卫」映射，禁止只报总数
    # ---- v3.48 ----
    "per_suite_count_must_be_comparable": True,       # 逐套件计数单位须统一，禁止脚本断言数 / pytest 用例数混用
    "config_surface_hash_required": True,             # 「两份配置一致」须由 surface 哈希证明，不得口头断言
    "evidence_source_independence_required": True,    # 独立证据源须验证【上游不同源】，不是取个名字
    "draft_mode_matrix_default_deny": True,           # draft 模式矩阵未列出的模式一律拒绝（default deny）
    # ---- v3.49：四项判据口径钉死 ----
    "suite_baseline_anchor_peak_required": True,      # 基线须锚历史峰值，不得取当前值
    "config_surface_algorithm_whitelisted": True,     # surface 递归范围由白名单钉死
    "acceptance_ledger_must_cover_all_globs": True,   # 账本全覆盖 glob 命中文件
    "valid_run_mode_set_closed": True,                # RUN_MODE 合法集合封闭
    # ---- v3.50：五项「可复现」钉死 ----
    "config_surface_must_be_reproducible": True,      # 期望值须可由冻结算法复算（黄金向量自证）
    "expected_value_provenance_required": True,       # 期望值 / 峰值不得人工手填，须带可复核证据
    "ledger_append_only_mechanically_enforced": True, # 只追加由链式哈希强制，非政策声明
    "whitelist_completeness_enforced": True,          # 白名单须完整（漏纳 / 误纳都 raise）
    "final_acceptance": [
        "same_prewarm_frame_all_engines_reject",
        "stale_frame_all_engines_reject",
        "every_egress_point_rejects_when_gate_fails",
        "no_remaining_bypass_switch",
        "per_suite_counts_comparable_across_rounds",
        "config_surface_hash_matches_across_machines",
        "surface_golden_vector_matches_across_machines",
        "config_surface_dump_diff_is_empty",
    ],
}

# ==================== 计数覆盖面与脚本确定性（v3.47 新增） ====================
#   病一（覆盖面悄悄缩减）：上一轮报「20 套（根目录 9 + tests 11）」，本轮只报「9 套」，未作任何说明——
#       与 v3.36 的 count_definition_stable、per_suite_breakdown_required 直接冲突。
#       缩减本身不一定是错，但【静默缩减】一定是错：不可比 = 无法回答「这轮到底跑没跑」。
SUITE_COVERAGE_GUARD = {
    "enabled": True,
    "baseline_suite_count": 20,                    # 根目录 9 套 + tests 11 套（v3.41 起冻结）
    "must_report_all_suites": True,
    "must_not_shrink": True,
    "shrink_requires_explicit_reason": True,       # 缩减必须显式说明（哪套、为什么、何时恢复）
    "shrink_counts_as_regression": True,           # 未说明的缩减按「回归」计，不得算作合格轮
    "silent_omission_forbidden": True,
    "pytest_side_and_script_side_both_required": True,
    "per_suite_breakdown_required": True,
    # ---- v3.48：「20 套没少」≠「覆盖面没少」 ----
    #   病（本轮实测）：套件数仍是 20（must_not_shrink 通过），但【单套内的项数】在缩——
    #     alpha101 10→2、factor 58→6、loader 20→4。套件数这道闸门对「单套瘦身」完全失明：
    #     把 58 条断言删到 6 条，套件还在、名字还在、`must_not_shrink` 依然通过。
    #   且同一张表里【两种计数单位混用】：根目录 9 套报「脚本断言数」，tests 11 套报
    #     「pytest 收集到的用例数」——两种单位的数并排放在一栏里对比/相加，本身不可比。
    #   一句话：**要冻结的不只是「跑了几个套件」，还有「每套跑了多少项」和「这一栏数的是什么单位」。**
    "count_unit_enum": ["script_assertion", "pytest_case"],
    "count_unit_declared_per_suite": True,         # 每套必须显式声明本行的计数单位
    "per_suite_count_must_be_comparable": True,    # 同一张表内不得混用两种单位（混用即该表不合格）
    "per_suite_baseline_required": True,           # 每套须登记基线项数
    "per_suite_regression_must_be_declared": True, # 单套项数下降同样须显式说明，理由不足按回归计
    "per_suite_regression_threshold_pct": 20,      # 单套项数跌幅 > 20% 且无说明 → 视为静默缩减
    "baseline_registry_file": "suite_baselines.json",
    "missing_baseline_action": "raise",            # 新套件无基线 → raise（禁止「默认 0」= 永远不回归）
    # ---- v3.49：基线不能是「本轮当前值」——否则等于把已经发生的静默缩减合法化 ----
    #   病：施工方以 v3.47 的 433 项为基线登记，而 alpha101/factor/loader 的瘦身早在 v3.44~v3.47
    #     之间就发生过（10→2、58→6、20→4）。基线锚在「瘦身之后的当前值」= 闸门对【之前的瘦身】
    #     完全失明，而被瘦身的测试永远不会回归。
    #   一句话：**基线必须锚定【历史合理峰值】（v3.40 左右稳定态），不是上一轮的当前值。**
    "baseline_must_anchor_historical_peak": True,     # 基线值 = 该套历史上曾达到的合理最大值，不得取上一轮实测
    "historical_peak_registry": "suite_baselines.json",  # 与 baseline_registry_file 共用，字段加 historical_peak
    "current_below_peak_must_carry_recovery_plan": True,  # 当前实测 < 历史峰值 → 必须附恢复计划（何时、如何补回）
    "silent_ratchet_down_forbidden": True,            # 禁止以「当前跑的是多少」作为基线（棘轮只能向上）
    "baseline_initial_peaks": {                       # v3.49 起以 v3.40 稳定态为锚（人工核定）；施工方可声明式上调、不得下调
        "test_alpha101.py": 10, "test_factor.py": 58, "test_loader.py": 20,
        # 其余套件基线与 v3.48 实测一致（本轮未发现瘦身），仍由 baseline_registry 登记
    },
    # ---- v3.50：峰值是【人工核定的裸数字】= 又一个「自己给自己定判据」 ----
    #   病：baseline_initial_peaks 与 suite_baselines.json 的 historical_peak 都是【数字】，
    #     由看守者/施工方【填写】。填 58 还是 60、峰值是哪一轮达到的、依据是什么——谁也复核不了。
    #     基线闸门（「不得低于峰值」）于是建立在一个【无法核验的断言】上。
    #   一句话：**峰值必须带证据（哪一版规格、什么命令、输出哈希），不是一个人写下的数字。**
    "historical_peak_must_cite_evidence": True,       # 每个 historical_peak 须附一条可复核证据记录
    "peak_evidence_schema": ["suite", "historical_peak", "spec_version", "command", "output_sha256"],
    "peak_from_declaration_action": "raise",          # 只有裸数字、无证据 → raise
    "peak_evidence_file": "suite_baselines.evidence.jsonl",
}

#   病二（外部依赖脚本的项数是变量）：test_data.py 的「核查项数」实测在 13 / 12 / 19 之间漂移——
#       它随数据源可达性、标的可用性变化。把一个非确定值叫「冻结口径」是自相矛盾：
#       能冻结的只有【上界】，实测值必须【原始上报】。
NONDETERMINISTIC_SCRIPT_GUARD = {
    "enabled": True,
    "scripts": ["test_data.py"],
    "reason": "核查项数随数据源可达性 / 标的可用性变化（实测 13→12→19），非确定值",
    "must_report_raw_observed": True,              # 报本轮实测原始数
    "must_report_fixed_upper_bound": True,         # 同时报确定性上界（TARGETS 数 + 固定核查项）
    "cannot_be_sole_evidence": True,               # 不得作为守卫生效的唯一证据
    "deterministic_anchor_required": True,         # 必须配一份【纯离线、项数固定】的锚点套件
    "deterministic_anchor_examples": ["tests/test_source_adapter.py", "tests/test_spec_check.py"],
    "count_change_must_be_explained": True,        # 项数变化必须解释（新增了什么 / 丢了什么）
    # ---- v3.48：上界本身若是变量，或【事后反填】，就等于没有上界 ----
    #   病（本轮实测）：施工方报「34 原始项 / 确定性上界 34」——**上界与实测值逐字相等**。
    #       一个「每次都与实测相等」的上界，不是上界，是【把实测抄了一遍】。若上界由本轮
    #       可达标的数算出，那么数据源被限流的那一轮，上界会跟着一起缩——**闸门随被守卫对象一起松**。
    #   一句话：**上界必须是【离线可算的静态量】，且实测不得超过它；否则「双报」只是报了两遍同一个数。**
    "upper_bound_must_be_offline_computable": True,       # 静态常量 / 静态集合长度，不联网可算
    "upper_bound_source": "模块级静态常量（如 len(TARGETS) × 固定核查项数），禁止运行时按可达性计算",
    "upper_bound_must_not_be_derived_from_observation": True,  # 禁止用本轮实测值反填上界
    "observed_must_not_exceed_bound": True,               # 实测 > 上界 → raise（证明上界不是上界）
    "bound_equals_observed_must_be_explained": True,      # 上界恰等于实测 → 须说明（否则疑为事后反填）
    # ---- v3.49：上界必须是 AST 可见的「字面常量/字面常量的算术」，禁止运行时计算 ----
    #   病：施工方以 len(TARGETS) + FIXED_CHECK_COUNT 作为上界——若 TARGETS 本身被动态 append/过滤，
    #     或 FIXED_CHECK_COUNT 在运行时按可达性减，「静态常量」也会变成变量。
    "bound_must_be_ast_literal_or_literal_sum": True,   # 上界 = 字面整数 或 字面整数相加；不得含 len()/函数调用/变量运算
    "bound_ast_check_action": "raise",                  # AST 形态不符 → raise
}

# ==================== 配置面（surface）机器比对（v3.48 新增） ====================
#   病（本轮实测）：沙箱 config.py 2341 行 vs 本机 2304 行，施工方自述「配置键集合一致
#       （17 键 / 20 套 / 15+10）」。可这两台机器**差了 37 行**，判据只有一句
#       「差异来自沙箱含施工过程注释」——这是**口头断言**，不是证据。本轮恰好只差注释，
#       下一轮就可能是「少一个 guard 键」而没人看得出来：判据、代码、交付物三者跨机不一致，
#       正是本会话从头到尾的那个病，只是这次发生在【两台机器之间】。
#   一句话：**把「两份 config 是否同构」变成一个哈希——让『一致』不再靠嘴说。**
CONFIG_SURFACE = {
    "enabled": True,
    # ---- v3.49：surface_scope 精确钉死，禁止实现方自由选择递归范围（否则两机算法不同 → 哈希自然不同）----
    #   病：v3.48 把 surface_scope 写为「每个 guard 块的键名」——但什么是「guard 块」没列清单。
    #     沙箱实现递归【全部】字典（162+1235=1397），本机实现递归【治理类字典】（167+1043=1210），
    #     算法口径不同 → 哈希不同 → 「跨机比对」退化成「每机算各的」，失去意义。
    #   一句话：**哈希算法的输入必须是一份【白名单】，而不是一个形容词。**
    "surface_scope": "顶层大写常量名 + surface_recurse_blocks 白名单中的字典递归键名（排序后）",
    "surface_recurse_blocks": [                    # 【白名单】——只有这些字典的键名进入 surface，业务配置一律不进
        "SYSTEM_CONFORMANCE", "CLI_CONFORMANCE", "SPEC_VERSION_CHECK", "GATE_CONFORMANCE",
        "SIGNAL_EGRESS_CONFORMANCE", "ENGINE_CONFORMANCE", "LIVE_SAFETY", "EXECUTION_MODEL",
        "ORDER_PORT_CONFORMANCE", "DATA_LONG_TERM", "DATA_SOURCE_ADAPTER_GUARD", "CACHE_GOVERNANCE",
        "OPTION_VALUATION_GUARD", "REPORT_CONFORMANCE", "REPORT_ARCHIVE_CONFORMANCE",
        "REPORT_LONG_TERM", "DISCLOSURE_CONFORMANCE", "UNIVERSE_RESOLUTION_GUARD",
        "INDICATOR_HARDENING", "INDICATOR_WARMUP_GUARD", "SNAPSHOT_PIT_GUARD",
        "EMPTY_REASON_PROVENANCE", "SPEC_DRAFT_PERMISSION", "SUITE_COVERAGE_GUARD",
        "NONDETERMINISTIC_SCRIPT_GUARD", "ACCEPTANCE_GOVERNANCE", "SPEC_PROVENANCE",
        "CONFIG_SURFACE", "BACKTEST_DEFAULTS", "RISK",
    ],
    "surface_hash_algo": "sha256",
    "surface_hash_file": "config_surface.sha256",
    "must_be_printed_by_check_config": True,
    "ignore_values": True,
    "comment_and_blank_lines_excluded": True,
    "mismatch_action": "warn_and_report_diff",
    "must_report_missing_and_extra_keys": True,
    "recurse_blocks_exhaustive": True,             # 白名单外的字典一律不递归（新增 guard 块须先加白名单 + bump 版本）
    "missing_recurse_block_action": "raise",       # 白名单里的块在 config 里找不到 → raise（防止改名漏检）
    # ---- v3.50：集合钉死了，【序列化 / 算法】还没钉死 → 期望值不可复现 ----
    #   病（本轮实测）：沙箱登记元素数 755（162 常量 + 593 键）能复现，但登记哈希 d7df508d…
    #     用任何自然读法（排序合并 / 去重 / 尾换行 / 限定路径 / JSON …）都算不出来。
    #     即「哪些元素进集合」钉死了、「集合怎么变成哈希」没钉死 → 任何人都无法独立验证自己
    #     算得对不对；两机「不一致」也分不清是数据差还是算法差。
    #   一句话：**算法必须给到「输入 → 哈希」的每一步，并配一个固定输入的黄金向量。**
    "surface_algo_id": "cs-v1",
    "surface_algo_steps": [
        "S1 常量集 = 源码 AST 顶层赋值目标名中匹配 [A-Z][A-Z0-9_]* 者（不看运行期命名空间）",
        "S2 键集 = surface_recurse_blocks 中每块递归其 dict（只下钻 dict，不下钻 list/tuple），取 str(键名)",
        "S3 元素集 = sorted(set(常量集) | set(键集))，ASCII 升序",
        "S4 规范化串 = 元素集以 LF 逐行连接 + 末尾一个 LF（UTF-8）",
        "S5 sha256(规范化串)",
    ],
    "surface_canonical_text_required": True,
    "surface_golden_vector": {
        "consts": ["A", "GOLDEN", "Z"],   # v3.51：让 "A" 与 block 内键重名 → 强制走 set 去重路径（元素/哈希不变，但去重被覆盖）
        "block": {"b": 1, "A": {"c": 2}, "L": [{"dropped": 9}]},
        "expected_elements": ["A", "GOLDEN", "L", "Z", "b", "c"],
        "expected_sha256": "72bc8831bd7d585a256c74b123d952715841e4a5ed117addc179db183ef756b2",
    },
    "golden_vector_must_match_action": "raise",
    "surface_collection_must_be_ast_based": True,
    "dir_based_collection_forbidden": True,
    "surface_expected_counts": {
        "n_consts": 162, "n_keys_raw": 644, "n_keys_uniq": 591, "n_elements": 752,
    },
    "hand_typed_expected_forbidden": True,
    "surface_dump_file": "config_surface.elements.txt",
    "dump_required_on_mismatch": True,
    "whitelist_completeness_required": True,
    "guard_block_name_pattern": "(_GUARD|_CONFORMANCE|_SAFETY|_GOVERNANCE|_PROVENANCE|_PERMISSION|_LONG_TERM|_HARDENING)$|^RISK$|^CONFIG_SURFACE$|^EXECUTION_MODEL$|^SPEC_VERSION_CHECK$",
    "whitelist_exclusions": {
        "UNIVERSE_RESOLUTION_GUARD": {
            # v3.51：块内【业务样例键】是股票代码（分挂 segment_decision_examples / known_ambiguous_symbols 之下），
            #   它们不是治理结构——加一个示例代码不应改动「治理面哈希」。剔除代码键本身，保留承载它的结构键名。
            "exclude_key_pattern": "^\\d{6}(\\.(SH|SZ|BJ))?$",
            "keep_container_key": True,
            "reason": "业务样例的键是股票代码；治理面哈希只应随治理结构变化，不随示例代码增减而变",
        },
    },
    "unlisted_guard_block_action": "raise",
    # ---- v3.51 病一：跨版本比对 = 拿两个不同版本的集合相减，差异不可定性 ----
    #   本轮实测（沙箱）：把 v3.50 的 586 去重键直接减本机 v3.49 的 515，得「少 71」；
    #   而同版本对照（沙箱 v3.49 = 541 键）显示真实结构差只有 26，另 45 是 v3.50 的合法新增。
    #   一句话：**颜色不同的两面墙相减，差里混着「版本」和「漏合并」，必须先把版本钉平再比。**
    "compare_requires_same_spec_version": True,
    "compare_requires_same_algo_id": True,
    "compare_requires_same_whitelist": True,
    "cross_version_compare_action": "refuse",
    "compare_baseline_dump_per_version_required": True,
    # ---- v3.51 病二：白名单「完备」但「不纯」——业务样例键混进治理面 ----
    "business_key_pattern_excluded": True,
    "exclusion_must_cite_reason": True,
    # ---- v3.51 病三：期望数量被【当成判据】——它是产物，不是门槛 ----
    "frozen_counts_are_outputs_not_criteria": True,
    "expected_counts_mismatch_action": "warn_not_fail",
    # ---- v3.51 病四：黄金向量未覆盖「去重」与「非 dict 块」两条路径 ----
    "golden_vector_must_cover": ["ast_const", "dict_recurse", "list_not_recursed", "set_dedup", "lf_join", "trailing_lf"],
    "non_dict_block_action": "raise",
}

# ==================== 验收集治理（v3.44 新增）：施工方不得单方面修改「判自己合格」的脚本 ====================
#   病：验收脚本由施工方自己维护，测试红了可以「改断言」让它变绿——本轮实测就有一次
#       （test_data.py 的「指数成交额单位」断言被改）。改对了不代表机制安全：没有任何东西
#       能阻止下一次「改错」。更隐蔽的是：该断言只在【东财可达】时执行（新浪分支 amount 全 NaN
#       → 静默 skip），所以它长期「绿」的真实原因是【从未真正执行】。
#   一句话：验收脚本不能既是「证据」、又是「可被被告随手涂改的证物」。
ACCEPTANCE_GOVERNANCE = {
    # ① 验收脚本哈希锁定：改动必须显式声明（改一条、留一条），禁止静默改断言
    "script_hash_locked": True,
    "spec_hash_authority": "reviewer_published",  # v3.46：权威哈希只认看守者发布的正文；自撰正文的哈希进 spec_drafts.sha256
    "script_globs": ["test_*.py", "tests/test_*.py", "cli_commands/checklist.py"],
    "hash_manifest": "acceptance_scripts.sha256",
    "on_hash_mismatch": "require_declaration",   # 未声明的断言改动 = 该轮验收作废
    "declared_changes_must_be_reported": True,
    # ①-b v3.47：改了验收脚本后「顺手同步哈希」= 运动员改完成绩单再自己签字
    "script_hash_self_sync_forbidden": True,        # 禁止「改脚本 + 同一次操作里同步 manifest 哈希」并据此宣告通过
    "script_hash_change_requires_changelog": True,  # 哈希变更必须留痕（改哪条、为什么改）
    "changed_script_excludes_its_own_verdict": True,  # 被改脚本自身的判定不得作为「本次改动正确」的证据
    "script_hash_authority": "reviewer_published",  # 验收脚本权威版本由看守者发布；施工方改动须待复核确认
    # ①-c v3.48：哈希 manifest 是【一份可被整段重写的表】——改完脚本把它一起改掉即可
    #   病：`acceptance_scripts.sha256` 是「路径 → 哈希」的**映射表**。它既能被**改写**
    #       （把某条的值换成新哈希），也能被**删行**（把某条整行删掉）——而删除正是
    #       「测试红了 → 删掉它 → 变绿」的隐身通道：**删一个测试文件，manifest 里少一行，
    #       哈希校验照样全过**。被改脚本自身的判定不得作为证据（①-b）只管到了「改」，
    #       没管到「删」。
    #   一句话：**哈希登记必须是【只追加的账本】，改要留痕、删也要留痕。**
    "hash_ledger_file": "acceptance_scripts.ledger.jsonl",
    "hash_ledger_append_only": True,             # 只追加，不得改写 / 删除历史条目
    "ledger_entries_immutable": True,
    "forbid_hash_entry_removal": True,           # 禁止靠删行让哈希校验通过
    "script_change_requires_spec_bump": True,    # 改验收脚本须伴随一次规格版本变更 + 变更说明
    "script_deletion_counts_as_change": True,    # 删测试 = 改测试的隐身版本，同样须声明
    "deleted_script_must_remain_in_ledger": True,  # 已删脚本的历史哈希与删除事由必须留在账本里
    "ledger_entry_schema": ["path", "sha256", "action", "spec_version", "reason", "recorded_at"],
    "ledger_action_enum": ["add", "modify", "delete"],
    "on_ledger_not_append_only": "raise",        # 检测到历史条目被改写 / 删除 → raise
    # ---- v3.49：账本必须【全覆盖】script_globs 匹配到的文件；不登记 = 没在监管范围内 ----
    #   病：施工方回执账本只有 3 行（meta + 2 register），但 script_globs 匹配的文件有 20+ 套。
    #     只登记被改过的脚本、其余脚本不登记 → 这些脚本的任何删改都不会触发 hash 校验——
    #     「登记一个文件 = 守一个文件」，没登记的文件 = 没人守。
    #   一句话：**账本必须在每轮 check-config 时扫描 glob，所有命中文件都必须在账本最后一条有效记录里。**
    "ledger_must_cover_all_script_globs": True,    # glob 命中但账本没登记 → raise（不得只登记被改过的）
    "unregistered_script_action": "raise",         # 未登记脚本存在 → 视为未受控，验收不合格
    "ledger_must_have_effective_entry_per_script": True,  # 每个脚本在账本里必须至少有一条非 delete 的末条记录
    "legacy_manifest_migration_required": True,    # 旧 acceptance_scripts.sha256 中的条目必须迁到 ledger 后再冻结
    # ---- v3.50：账本「只追加」是【政策】不是【机制】；迁移可能把改动洗白 ----
    #   病一：hash_ledger_append_only=True 只是 config 里的一句话。JSONL 是普通文本，改一条、
    #     插一条、删一行——没有任何东西会因此报错。「只追加」必须有【机械强制】，否则它仍是
    #     一个「靠自觉」的闸门。
    #   病二：旧 manifest 迁到 ledger 时，若实现是「对当前文件重算哈希写进账本」，则 v3.47→v3.49
    #     之间被改动过的脚本会被【合法化】——迁移成了洗白通道。迁移必须【先验证旧哈希成立】。
    #   一句话：**只追加要用链式哈希强制；迁移要先证明「旧账对得上」。**
    "ledger_hash_chain_required": True,           # 每条含上一条的哈希，链式串联
    "ledger_entry_must_include_prev_sha256": True,
    "prev_entry_field": "prev_entry_sha256",
    "entry_field": "entry_sha256",
    "chain_genesis": "GENESIS",
    "chain_break_action": "raise",                # 插入 / 改写 / 删行 → 链断 → raise
    "migration_must_verify_old_hash_first": True, # 迁移前先按旧 manifest 验哈希仍成立
    "rehash_on_migrate_forbidden": True,          # 禁止「对当前文件重算哈希」充当迁移
    "migration_entry_requires_old_and_new_hash": True,
    "migration_hash_mismatch_requires_declaration": True,

    # ② 依赖外部数据源的检查：源不可达时【不得静默计入通过】
    "source_dependent_checks": {
        "must_mark_skip_explicitly": True,
        "skip_marker": "skipped_due_to_source",
        "skip_counts_as": "uncovered",           # 计入「未覆盖」，不计入 passed
        "forbid_silent_pass": True,              # 禁止「源不可达 -> 直接算过」
        "report_must_list_uncovered": True,
    },
    # ③ 核心口径 / 单位检查必须有【离线实现】（不依赖实时源）
    "core_checks_must_have_offline_impl": True,
    "offline_source": "data_cache/**.parquet",   # 用本地缓存复算，源挂了也能验
    "offline_must_agree_with_online": True,      # 在线版与离线版结论不一致 -> raise
    # ④ 单位不变式按【资产类别】分设（个股=强不变式；指数=量级合理性，两者不可混用同一判据）
    "unit_invariant_by_asset_class": {
        "stock": {"expr": "amount/(close*volume)", "expect": 100, "tolerance": [95, 105],
                  "why": "A 股 1 手 = 100 股，volume 单位为手时该比值恒为 100（强不变式）"},
        "index": {"expr": "amount/(volume*100)", "unit": "元/股", "range": [1, 500],
                  "why": "指数 close 是【点位】不是股价，原式恒得 ~0.6 无判别力；改为反推隐含成分股均价（量级判据，非单位不变式）"},
    },
}

# ==================== 运行模式（唯一来源：本文件 + .env；CLI 只能「降级」，不得「提升」） ====================
RUN_MODE = "backtest"
