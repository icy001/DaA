"""
统一配置文件（v3.3）
——交易规则、默认参数、风控阈值、行情/图表/缠论配置集中在这里
——**所有账号/密码/Token 放在 .env 文件，不要写到本文件**

【2026-10-28 增量合并 config-3】只吸收元信息字段与常量，不改动既有结构（data_fetcher 依赖原 schema）：
  - DATA_SOURCE_UNITS 每条新增 native_adjust / kline_limit / note（由 DATA_SOURCE_META 合并追加）
  - 新增 UNIFIED_VOLUME_UNIT / UNIFIED_AMOUNT_UNIT / FUTURES_AMOUNT_NOT_APPLICABLE /
    DATE_INDEX_NAME / EXTRA_FLAG_COLUMNS / MINUTE_NO_PAGINATION_SOURCES
  - AMBIGUOUS_CODES 补 000001（平安银行 vs 华夏成长），仍为 list 结构
  - detect_market_type 保持原样（保留国内期货品种优先分支）
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

# ==================== 规格版本自校验（v3.33 新增） ====================
# 教训：连「规格」本身都活在副本上，人肉版本号核对会失效；必须机器校验 fail-closed。
SPEC_VERSION = "v3.49"
SPEC_VERSION_CHECK = {
    "enforce_on_startup": True,
    "enforce_in_check_config": True,
    "command_file_glob": "*指令集*.md",   # v3.34：glob 多候选，兼容 ...-2.md 之类副本命名
    "version_header_marker": "<!-- spec_version:",
    "on_mismatch": "raise",          # 版本对不上直接停机，禁止静默降级
    "on_file_not_found": "raise_with_guidance",
    "enforce_modes": ["live", "live_sim", "paper"],   # 只有真实资金/模拟盘路径拦截；tooling/backtest 不拦
    "allow_suffix": ["-draft"],
    # v3.40：版本号是人手维护的标签，会漂移、会被复用（同一版本号两份内容 → 字符串比对假绿）。
    # 因此「机器验内容哈希、人看版本号」：正文哈希不符即不通过，版本号永不复用。
    "content_hash_required": True,
    "content_hash_file": "spec_content.sha256",
    "on_content_hash_mismatch": "raise",
    "version_number_never_reused": True,
    # v3.44：版本头一致但正文缺关键章节时同样不通过——防止正文被裁剪后版本号不变
    "must_contain_markers": ["13.0.14", "13.0.15", "13.0.16", "13.0.17", "13.0.18",
                             "13.0.19", "13.0.20"],
}

# ==================== 规格来源（v3.46 / 13.0.17）====================
# 教训：check-config 转绿时，被校验的正文与登记的哈希是同一个人写的——哈希闸门只能证明
# 「这个文件没被人改过」，证明不了「这个文件是权威规格」。规格正文必须单源发布，施工方
# 自撰只能算 draft，draft 的哈希必须写进 spec_drafts.sha256，绝不能拿去填 spec_content.sha256。
SPEC_PROVENANCE = {
    "authority": "draft_self_authored",      # reviewer_published=权威正文 / draft_self_authored=施工方自撰
    "authority_values": ["reviewer_published", "draft_self_authored"],
    "draft_hash_file": "spec_drafts.sha256",        # draft 正文哈希单独登记，不得污染发布哈希
    "published_hash_file": "spec_content.sha256",
    "block_live_on_draft": True,             # draft 正文禁止进入 live/paper 链路
    "draft_status_in_check_config": "yellow",  # draft 只给黄灯，不得转绿
    "single_source_of_truth": True,          # 正文只能有一份权威副本
}

# ==================== 规格草稿权限（v3.47 / 13.0.18）====================
# 教训：draft 只打印一行「[草稿/黄]」= 只有颜色没有权限，自撰规格照样能解锁实盘。
# draft 必须在钱路径上直接拒绝；研究/工具路径放行，否则 check-config 会锁死自己。
SPEC_DRAFT_PERMISSION = {
    "blocked_modes": ["live", "live_sim", "paper"],
    "allowed_modes": ["backtest", "research", "tooling"],
    "on_blocked_mode": "raise",
    "keep_self_lockout_guard": True,        # 诊断/修复命令不得因 draft 而失败
    "check_config_runs_under_draft": True,
    "draft_must_not_unlock_money_paths": True,
    # ---- v3.48 / 13.0.19 ⑤：模式矩阵默认拒绝，未登记模式必须 raise ----
    "mode_matrix": {"live": "raise", "live_sim": "raise", "paper": "raise",
                    "backtest": "allow", "research": "allow", "tooling": "allow"},
    "mode_matrix_default": "deny",            # 查不到的模式默认拒绝，禁止「查不到就放行」
    "unknown_mode_action": "raise",
    "mode_matrix_single_source": True,        # blocked/allowed 一律由矩阵派生，禁止另写一份
    "blocked_modes_derive_from_matrix": True,
    "allowed_modes_derive_from_matrix": True,
    # ---- v3.49 / 13.0.20 ④：先验白名单，再查矩阵 ----
    # v3.48 靠「字典 miss + default=deny」碰巧拦住；只要代码写成 .get(mode, default)
    # 或矩阵里多一个宽松条目，未登记模式就会 fail-open。现改为查矩阵之前先过封闭白名单。
    "valid_mode_set_required": True,
    "valid_modes": ["backtest", "research", "paper", "live", "live_sim", "tooling"],
    "invalid_mode_action": "raise",
    "cli_mode_argument_validated": True,       # CLI --mode / .env RUN_MODE 同一条校验
}

# ==================== empty_reason 证据来源（v3.47 / 13.0.18）====================
# 教训：用「取数返回空」反推退市，恰好就是被限流源的表形——被限流只要被标成退市，
# 净空闸门反而被绕过。empty_reason 只能来自独立证券主数据，必须带 as_of 并过时点闸门。
EMPTY_REASON_PROVENANCE = {
    "allowed_sources": ["security_master"],          # 唯一合法来源：独立证券主数据
    "fetcher_must_not_assign_empty_reason": True,    # 取数层/适配器禁止写 empty_reason
    "must_carry_as_of": True,                        # 证据必须带判定时点
    "pit_gate_required": True,                       # 必须过时点闸门（不得用今天的名单判历史）
    "on_missing_evidence": "raise",
    "master_cache_dir": "data_cache/security_master",
    "master_max_age_days": 30,
    # ---- v3.48 / 13.0.19 ④：证据源「独立性」不能只取名字；格式归一是闸门入口硬前置 ----
    "forbid_shared_upstream_with_market_data": True,   # 上游接口不得出现在行情接口映射里
    "forbid_fallback_to_market_source": True,          # 主数据不可达不得回退行情源反推
    "listing_probe_unavailable_must_raise": True,      # 找不到独立上游时必须报错，不得静默
    "independent_upstream_required": True,
    "upstream_registry": {"security_master": "akshare.bond_zh_cov_info"},  # 主数据上游接口登记
    "upstream_independence_basis": "接口级：上游接口名不得出现在 SOURCE_INTERFACE_MAP 任何值中",
    "as_of_must_normalize_before_compare": True,       # 时点闸门前必须先归一日期格式（YYYYMMDD）
    "as_of_canonical_format": "YYYYMMDD",
    "no_evidence_means_raise": True,                   # 无证据 ≠ 退市，必须走 fail-closed
    "probe_failure_is_not_delisting": True,            # 探针失败更不等于退市
    "evidence_must_carry_provider": True,
}

# ==================== 支持清单 ↔ 单位索引 同域（v3.47 / 13.0.18）====================
# 教训：SOURCE_INTERFACE_MAP 按「源+市场+周期」索引接口名，而「支持哪些市场」另有一份
# 清单在 data_fetcher.py，两者靠逐个手工补 key 对齐——加一个市场必然再漂。
# 本块是唯一支持清单，data_fetcher 的 _SUPPORTED_*_MARKETS 必须由它派生。
SUPPORTED_KLINE_MARKETS = {
    "daily": ["cn_stock", "cn_etf", "us_stock", "us_etf", "hk_stock", "cn_convertible",
              "cn_reits", "cn_future", "global_future", "forex", "cn_option", "crypto",
              "cn_fund", "cn_reverse_repo", "cn_index"],
    "minute": ["cn_stock", "cn_etf", "cn_index", "us_stock", "us_etf", "hk_stock",
               "cn_convertible", "cn_future", "forex", "crypto"],
}

# ==================== 配置面核验（v3.48 / 13.0.19 ⑦）====================
# 教训：两机「键集合一致」若只靠一句口头断言（沙箱 2341 行 vs 本机 2304 行「差在注释」），
# 漏一个键没人知道。配置面哈希只比结构、不比取值：多写几行施工注释哈希不变；
# 哈希变了 = 真的漏/多了一个键。由 check-config 打印，两机各跑一次即可对齐。
CONFIG_SURFACE = {
    "enabled": True,
    "scope": "structure_only",               # 只比结构（常量名+键名），不比取值
    "algorithm": "top_level_constants_plus_whitelisted_block_keys",
    "include_top_level_constants": True,     # 源码定义的顶层大写常量名参与
    "include_recursive_bare_keys": True,     # 白名单块内的 dict 键名（含嵌套，去重）参与
    "values_excluded": True,                 # 取值不参与；注释与空行天然不参与
    "sorted_before_hash": True,              # 排序后逐行 join 再 sha256
    "surface_hash_file": "config_surface.sha256",
    "printed_by_check_config": True,
    # ---- v3.49 / 13.0.20 ①：递归范围必须是白名单，不是形容词 ----
    # v3.48 写的是「每个 guard 块」——「guard 块」是形容词：什么算 guard 没有唯一定义，
    # 于是两机一个递归了全部字典（业务配置也进来）、一个只递归部分，哈希永远不同。
    # 现在把集合逐名列出：递归集合严格等于本列表，缺块 → raise，多块 → 不在集合内即忽略。
    "surface_recurse_blocks": [
        "ACCEPTANCE_GOVERNANCE", "CACHE_GOVERNANCE", "CLI_CONFORMANCE", "CONFIG_SURFACE",
        "DATA_LONG_TERM", "DATA_SOURCE_ADAPTER_GUARD", "DATA_VERSIONING",
        "DISCLOSURE_CONFORMANCE", "EMPTY_REASON_PROVENANCE", "ENGINE_CONFORMANCE",
        "GATE_CONFORMANCE", "INDICATOR_HARDENING", "INDICATOR_WARMUP_GUARD",
        "LIVE_SAFETY", "NONDETERMINISTIC_SCRIPT_GUARD", "OPTION_VALUATION_GUARD",
        "ORDER_PORT_CONFORMANCE", "QUALIFIED_INVESTOR_RULES",
        "REPORT_ARCHIVE_CONFORMANCE", "REPORT_CONFORMANCE", "REPORT_LONG_TERM",
        "SIGNAL_EGRESS_CONFORMANCE", "SNAPSHOT_PIT_GUARD", "SOURCE_INTERFACE_MAP",
        "SPEC_DRAFT_PERMISSION", "SPEC_PROVENANCE", "SPEC_VERSION_CHECK",
        "SUITE_COVERAGE_GUARD", "SYSTEM_CONFORMANCE", "UNIVERSE_RESOLUTION_GUARD",
    ],
    "recurse_blocks_exhaustive": True,       # 白名单即全集：不在表内的块不参与
    "missing_recurse_block_action": "raise",  # 白名单里的块在 config 中不存在 → raise
    "list_elements_not_recursed": True,      # 只递归 dict 键；列表元素（如市场名单）不展开
}

# ==================== 套件覆盖冻结（v3.47 / 13.0.18）====================
# 教训：上一轮报「20 套」、下一轮只报 9 套而无说明——计数覆盖面静默缩减，等于验收缩水。
SUITE_COVERAGE_GUARD = {
    "frozen_total": 20,
    "root_suites": ["test_account.py", "test_chan.py", "test_chart.py", "test_data.py",
                    "test_env.py", "test_export.py", "test_indicators.py",
                    "test_paper_trade.py", "test_pattern.py"],
    "tests_suites": ["tests/test_alpha101.py", "tests/test_backtest.py",
                     "tests/test_custom_factor.py", "tests/test_engine_consistency.py",
                     "tests/test_factor_strategy.py", "tests/test_factor.py",
                     "tests/test_loader.py", "tests/test_match_price_basis.py",
                     "tests/test_research.py", "tests/test_signal_gate.py",
                     "tests/test_strategy.py"],
    "shrink_requires_reason": True,
    "on_unjustified_shrink": "fail",
    "per_suite_breakdown_required": True,
    # ---- v3.48 / 13.0.19 ①②：套件数没少 ≠ 覆盖面没少；计数单位必须分栏 ----
    "per_suite_baseline_required": True,       # 冻结的不只是套件个数，还有每套的项数
    "baseline_registry_file": "suite_baselines.json",
    "baseline_drop_threshold_pct": 20,         # 项数跌幅 >20% 且无说明 = 静默缩减
    "baseline_drop_requires_reason": True,
    "on_unjustified_baseline_drop": "fail",
    "baseline_scope_frozen_suites": True,      # 基线登记必须覆盖冻结的 20 套
    "count_unit_declared_per_suite": True,     # 同一张表不得混用两种计数单位
    "per_suite_count_must_be_comparable": True,
    "count_units": {"root": "script_assertion", "tests": "pytest_case"},
    "per_suite_unit_field": "unit",            # 逐套件报数逐行带 unit 字段
    "pytest_and_script_reported_separately": True,   # pytest 侧与脚本侧分栏呈现
    # ---- v3.49 / 13.0.20 ②：基线必须锚历史峰值，不得锚「瘦身后的当前值」----
    # 把已发生的静默缩减（alpha101 10→2、factor 58→6、loader 20→4）写进基线，
    # 等于用「新基线」给旧缩减发合格证。基线只记历史峰值；当前 < 峰值必须带 recovery_plan。
    "baseline_must_anchor_historical_peak": True,
    "baseline_initial_peaks": {
        "tests/test_alpha101.py": 10,
        "tests/test_factor.py": 58,
        "tests/test_loader.py": 20,
    },
    "silent_ratchet_down_forbidden": True,     # 禁止把基线悄悄下调到当前值
}

# ==================== 非确定脚本口径（v3.47 / 13.0.18）====================
# 教训：test_data 的项数取决于外网源可达性，是变量；变量不能叫「冻结口径」。
NONDETERMINISTIC_SCRIPT_GUARD = {
    "nondeterministic_suites": ["test_data.py"],
    "must_report_raw_and_bound": True,        # 必须同时报「实测原始数」与「确定性上界」
    "cannot_support_conclusion_alone": True,  # 不得只凭非确定脚本下结论
    "deterministic_anchors": ["pytest:tests"],
    # ---- v3.48 / 13.0.19 ③：「确定性上界」必须离线可算，不得事后反填 ----
    "upper_bound_must_be_offline_computable": True,    # 上界 = 模块级静态常量，从 TARGETS 离线算出
    "observed_must_not_exceed_bound": True,            # 实测 > 上界 → raise（上界不是上限，是异常）
    "upper_bound_source": "static_constant",
    "upper_bound_computed_from": "TARGETS",
    "upper_bound_must_survive_offline_run": True,      # 断网跑一轮上界必须不变
    "observed_exceeds_bound_action": "raise",
    "raw_count_field": "raw_count",
    "bound_field": "deterministic_bound",
    "per_suite_unit_required": True,                   # 非确定脚本报数同样要带 unit
    "offline_verification_command": "python -m pytest tests/test_suite_guard.py -k bound",
    # ---- v3.49 / 13.0.20 ③：上界表达式必须是字面整数或字面整数相加 ----
    # len(TARGETS) 仍是「从运行期对象取值」；严格口径只认 34 或 19 + 15，
    # 与 len(TARGETS)+FIXED_CHECK_COUNT 的一致性另用运行期断言兜底（两件事分开验）。
    "bound_must_be_ast_literal_or_literal_sum": True,
}

# ==================== 验收集治理（v3.44 新增）====================
# 教训：① 改断言可以改对，也可以改错——机制上没人拦；② 依赖外网源的断言在源不可达时
# 长期「绿」的真实原因是【从未执行】（核实7 的 ratio 断言潜伏数轮才暴露）。
# 验收脚本本身必须被治理：
#   - 脚本哈希锁定：改断言必须同步登记新哈希（core/spec_check.verify_acceptance_scripts 消费）；
#   - 源不可达必须标 skipped_due_to_source 并计入「未覆盖」，禁止当作通过；
#   - 核心口径检查（单位/复权/涨跌幅）必须有离线实现，不得只依赖外网源可达；
#   - 单位不变式按资产类别分设：指数 close 是点位不是股价，禁止用 close×volume 反推单位。
ACCEPTANCE_GOVERNANCE = {
    "script_hash_locked": True,
    "script_hashes": {               # 相对路径 → sha256；改脚本必须重算并同步本表
        "test_data.py": "f95ac4ac81774131fe5bbb92d97b22841d8da0c8de535452f957a85d500ac75f",
        # v3.45：13.0.16 六条判据的验收脚本，改断言必须同步登记
        "tests/test_source_adapter.py": "e7e40baeffe3c53857cf5003eb7a28cf3c3b2ad070b081465de8ee77d3e432fe",
    },
    "on_script_hash_mismatch": "fail",
    "source_unreachable_must_mark": "skipped_due_to_source",
    "skipped_counts_as": "uncovered",
    "core_check_offline_impl_required": True,
    "offline_impl_map": {            # 核心口径的离线实现落点（pytest，不依赖外网）
        "单位/口径标记": "tests/test_data_versioning.py",
        "市场识别/号段": "tests/test_market_detect.py",
        "复权因子": "tests/test_data.py::核实5",
    },
    # v3.46：哈希只能证明「文件没被改过」，证明不了「这是权威规格」。作者=登记者时
    # 自撰正文 + 自登记哈希不能转绿；draft 必须走 spec_drafts.sha256 且 check-config 只给黄。
    "spec_hash_authority": "reviewer_published",
    # v3.47：改脚本的人顺手同步哈希 = 运动员改成绩单再签字；哈希来源必须与施工方分离。
    "script_hash_provenance_file": "acceptance_scripts.sha256",
    "script_hash_authority": "draft_self_authored",   # 评审方发布后才可改 reviewer_published
    "script_hash_self_sync_forbidden": True,
    "script_hash_draft_status": "yellow",
    "unit_invariants_by_asset_class": {
        "cn_stock": "amount ≈ close × volume × 100（volume 口径=手）",
        "cn_index": "隐含均价 = amount/(volume×100) ∈ [1,500] 元/股（close 是点位，禁用 close×volume）",
        "cn_future": "volume=手，amount 与 close×volume 无必然关系（禁止用该不变式估成交额）",
    },
    # ---- v3.48 / 13.0.19 ⑥⑦：账本只追加（删也是变更）；两机键集合机器核验 ----
    "hash_ledger_append_only": True,                 # 追加式账本，禁止改行/删行
    "script_deletion_counts_as_change": True,        # 删测试 = 变更，须追 {"action":"delete"} 条目
    "hash_ledger_file": "acceptance_scripts.ledger.jsonl",
    "ledger_entry_schema": ["path", "sha256", "action", "spec_version", "reason"],
    "ledger_action_values": ["register", "update", "delete", "add"],
    "delete_requires_reason": True,
    "ledger_must_cover_all_registered_scripts": True,  # config 登记的脚本必须在账本有记录
    "ledger_path_missing_action": "fail",
    "ledger_meta_authority_required": True,          # 账本首行 meta.authority 须与 config 声明一致
    "legacy_manifest_frozen": "acceptance_scripts.sha256",  # 旧映射表冻结，不再更新
    "config_surface_hash_required": True,            # 两机各跑一次 check-config 对齐 surface
    "config_surface_hash_file": "config_surface.sha256",
    # ---- v3.49 / 13.0.20 ③：账本必须覆盖 glob 命中的全部验收脚本 ----
    # v3.48 只登记 2 条，而 glob 命中 40+ 个文件：未登记的脚本改了没人知道。
    "script_globs": ["test_*.py", "tests/test_*.py", "cli_commands/checklist.py"],
    "ledger_must_cover_all_script_globs": True,
    "unregistered_script_action": "fail",
    "legacy_manifest_migration_required": True,   # 旧 sha256 表的条目必须迁入账本后冻结
}

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
# 数据层统一列名（date 为索引）：volume 统一为「股/张/币」最小单位，amount 统一为「元/计价货币」
STANDARD_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount"]
# date 是索引名而不是普通列（STANDARD_COLUMNS[0]），代码里用 STANDARD_COLUMNS[1:] 取数据列
DATE_INDEX_NAME = STANDARD_COLUMNS[0]
# 除标准列外可能出现的标记列（停牌/缺失），消费方不得把它们当成行情数据
EXTRA_FLAG_COLUMNS = ["is_suspended", "is_missing"]

# ---------- 数据源单位约定（唯一事实源，data_fetcher.INTERFACE_UNITS 由此派生） ----------
# volume / amount：该接口原始单位；volume_factor / amount_factor：换算到统一口径的乘数；
# verified：是否已用本机实测确证（False → 返回时标 attrs["unit_uncertain"]=True）。
DATA_SOURCE_UNITS = {
    # 东财系历史接口：成交量=手，×100；成交额=元
    "stock_zh_a_hist": dict(volume="手", amount="元", volume_factor=100.0, amount_factor=1.0,
                            unified_volume="股", unified_amount="元", verified=True,
                            evidence="实测 600519 amount/(close×volume)=99.69"),
    "fund_etf_hist_em": dict(volume="手", amount="元", volume_factor=100.0, amount_factor=1.0,
                             unified_volume="股", unified_amount="元", verified=True,
                             evidence="实测 510300 比值=100.0071"),
    "reits_hist_em": dict(volume="手", amount="元", volume_factor=100.0, amount_factor=1.0,
                          unified_volume="份", unified_amount="元", verified=False,
                          evidence="东财 REITs 与 ETF 同源，本机不可达未实测"),
    # 新浪系：成交量=股/份，不换算
    "stock_zh_a_daily": dict(volume="股", amount="元", volume_factor=1.0, amount_factor=1.0,
                             unified_volume="股", unified_amount="元", verified=True,
                             evidence="实测 600519 比值=1.0000"),
    "fund_etf_hist_sina": dict(volume="份", amount="元", volume_factor=1.0, amount_factor=1.0,
                               unified_volume="份", unified_amount="元", verified=True,
                               evidence="实测 508000 比值≈1"),
    # BaoStock：成交量=股、成交额=元（官方文档明确），不换算
    "baostock_daily": dict(volume="股", amount="元", volume_factor=1.0, amount_factor=1.0,
                           unified_volume="股", unified_amount="元", verified=True,
                           evidence="官方文档 volume=股、amount=元；实测 ratio≈1"),
    "baostock_minute": dict(volume="股", amount="元", volume_factor=1.0, amount_factor=1.0,
                            unified_volume="股", unified_amount="元", verified=True,
                            evidence="实测 600519 60 分钟 15:00 根 amount/(close×volume)≈1"),
    # 港美股
    "stock_hk_hist": dict(volume="股", amount="港元", volume_factor=1.0, amount_factor=1.0,
                          unified_volume="股", unified_amount="港元", verified=True,
                          evidence="实测 00700 比值=1.0016"),
    "stock_hk_daily": dict(volume="股", amount="港元", volume_factor=1.0, amount_factor=1.0,
                           unified_volume="股", unified_amount="港元", verified=True,
                           evidence="新浪港股日线【含】成交额字段：2026-10-29 00700 "
                                    "amount=7,981,520,000 港元、amount/(close×volume)=1.0074 "
                                    "→ volume=股、amount=港元，均不换算"),
    "stock_us_hist": dict(volume="股", amount="美元", volume_factor=1.0, amount_factor=1.0,
                          unified_volume="股", unified_amount="美元", verified=False,
                          evidence="东财美股本机不可达，未实测（运行时自检兜底）"),
    "stock_us_daily": dict(volume="股", amount="美元", volume_factor=1.0, amount_factor=1.0,
                           unified_volume="股", unified_amount="美元", verified=False,
                           evidence="新浪美股日线无成交额，未实测"),
    # 可转债：新浪日线=张（无成交额）；东财分钟=手（1 手=10 张）
    "bond_zh_hs_cov_daily": dict(volume="张", amount="无", volume_factor=1.0, amount_factor=1.0,
                                 unified_volume="张", unified_amount="元(估算)", verified=True,
                                 evidence="与东财成交量核对恰为 ×10（东财手=10张）"),
    "bond_zh_hs_cov_min": dict(volume="手", amount="元", volume_factor=10.0, amount_factor=1.0,
                               unified_volume="张", unified_amount="元", verified=True,
                               evidence="实测 113052 5 分钟比值=10.0（1手=10张）"),
    # 期货：保留「手」，无成交额
    "futures_main_sina": dict(volume="手", amount="无", volume_factor=1.0, amount_factor=1.0,
                              unified_volume="手", unified_amount="无", verified=True,
                              evidence="新浪主力连续成交量为手（无成交额）"),
    "futures_foreign_hist": dict(volume="手", amount="无", volume_factor=1.0, amount_factor=1.0,
                                 unified_volume="手", unified_amount="无", verified=True,
                                 evidence="新浪外盘期货成交量为手（无成交额）"),
    "futures_zh_minute_sina": dict(volume="手", amount="无", volume_factor=1.0, amount_factor=1.0,
                                   unified_volume="手", unified_amount="无", verified=True,
                                   evidence="新浪期货分钟成交量为手（无成交额）"),
    # 期权 / 外汇 / 基金 / 逆回购
    "option_sse_daily_sina": dict(volume="张", amount="无", volume_factor=1.0, amount_factor=1.0,
                                  unified_volume="张", unified_amount="无", verified=False,
                                  evidence="新浪期权日线无成交额，单位未实测"),
    "forex_hist_em": dict(volume="无", amount="无", volume_factor=1.0, amount_factor=1.0,
                          unified_volume="无", unified_amount="无", verified=False,
                          evidence="东财外汇历史无成交量/成交额列"),
    "sina_forex_min": dict(volume="未知", amount="无", volume_factor=1.0, amount_factor=1.0,
                           unified_volume="未知", unified_amount="无", verified=False,
                           evidence="新浪外汇分钟线无成交量单位说明"),
    "fund_open_fund_info_em": dict(volume="净值", amount="净值", volume_factor=1.0, amount_factor=1.0,
                                   unified_volume="净值", unified_amount="净值", verified=True,
                                   evidence="净值序列，volume/amount 置 0"),
    "bond_buy_back_hist_em": dict(volume="手", amount="元", volume_factor=1.0, amount_factor=1.0,
                                  unified_volume="手", unified_amount="元", verified=False,
                                  evidence="逆回购收盘价为年化利率，比值无经济含义；1手=1000元面值"),
    "bond_buy_back_snapshot": dict(volume="手", amount="元", volume_factor=1.0, amount_factor=1.0,
                                   unified_volume="手", unified_amount="元", verified=False,
                                   evidence="东财回购快照（备用源，仅当日一根），与历史接口同口径"),
    # 加密货币
    "binance_klines": dict(volume="币", amount="计价货币", volume_factor=1.0, amount_factor=1.0,
                           unified_volume="币", unified_amount="计价货币", verified=True,
                           evidence="币安 klines 原始字段"),
    # 分钟线
    "stock_zh_a_minute": dict(volume="股", amount="元", volume_factor=1.0, amount_factor=1.0,
                              unified_volume="股", unified_amount="元", verified=True,
                              evidence="实测 600519 60 分钟与不复权日线比值=1.0000"),
    "stock_zh_a_hist_min_em": dict(volume="手", amount="元", volume_factor=100.0, amount_factor=1.0,
                                   unified_volume="股", unified_amount="元", verified=True,
                                   evidence="实测 600519 60 分钟比值=100.03"),
    "fund_etf_hist_min_em": dict(volume="手", amount="元", volume_factor=100.0, amount_factor=1.0,
                                 unified_volume="股", unified_amount="元", verified=True,
                                 evidence="实测 510300 60 分钟比值=100.03"),
    "stock_us_hist_min_em": dict(volume="股", amount="美元", volume_factor=1.0, amount_factor=1.0,
                                 unified_volume="股", unified_amount="美元", verified=False,
                                 evidence="东财美股分钟本机不可达，未实测"),
    "stock_hk_hist_min_em": dict(volume="股", amount="港元", volume_factor=1.0, amount_factor=1.0,
                                 unified_volume="股", unified_amount="港元", verified=False,
                                 evidence="东财港股分钟本机不可达，未实测"),
    # 指数（基准/择时用，不可直接交易）：统一口径 volume=手
    "index_zh_a_hist": dict(volume="手", amount="元", volume_factor=1.0, amount_factor=1.0,
                            unified_volume="手", unified_amount="元", verified=False,
                            evidence="东财指数历史，成交量原始单位为手，不做换算（待实测复核）"),
    "stock_zh_index_daily": dict(volume="股", amount="无", volume_factor=0.01, amount_factor=1.0,
                                 unified_volume="手", unified_amount="无", verified=True,
                                 evidence="新浪指数日线无成交额字段；volume 单位经跨源验证："
                                          "2026-10-27 r=volume_sina/volume_bs=1.0000"
                                          "（sh.000300 16,868,847,400 股；sh.000001、sz.399001 均≈1），"
                                          "确认 volume=股，×0.01 折算为手"),
    "index_zh_a_hist_min_em": dict(volume="手", amount="元", volume_factor=1.0, amount_factor=1.0,
                                   unified_volume="手", unified_amount="元", verified=False,
                                   evidence="东财指数分钟，成交量原始单位为手；仅约 1 个月，未实测"),
    "baostock_index_daily": dict(volume="股", amount="元", volume_factor=0.01, amount_factor=1.0,
                                 unified_volume="手", unified_amount="元", verified=True,
                                 evidence="BaoStock 指数日线（sh.000300）官方字段 volume=股、amount=元；"
                                          "2026-10-27 amount/volume=22.71 元/股 量级合理（成分股均价），"
                                          "amount/(close×volume)=0.0056 属正常（点位×股数无换算关系），"
                                          "据此确认 volume=股，×0.01 折算为手"),
    # 腾讯指数日线：只有一个数量列且名为 amount，实测其值 = 新浪 volume(股)÷100（即「手」），
    # 不是成交额；登记为「股」仅为占位说明，真正接入时必须按「手」处理，否则会偏小 100 倍
    "stock_zh_index_daily_tx": dict(volume="股", amount="无", volume_factor=0.01, amount_factor=1.0,
                                    unified_volume="手", unified_amount="无", verified=False,
                                    evidence="腾讯 stock_zh_index_daily_tx 无独立 volume 列；"
                                             "其 amount 列实为成交量(手)、不是成交额"
                                             "（2026-10-27 值 168,688,474 = 新浪 volume 16,868,847,400÷100）；"
                                             "接入前必须按手处理，本表「股」仅为占位，当前未接入"),
}

# ---------- 数据源附加元信息（增量吸收自 config-3，纯说明性字段，data_fetcher 不读） ----------
# native_adjust：该接口原生返回的复权口径（none=不复权 / optional=接口自带 adjustflag / nav=净值）
# kline_limit  ：单次请求可取的最大 K 线条数（None=无限制；超限必须分页或标注 capped）
DATA_SOURCE_META = {
    "stock_zh_a_hist":          {"native_adjust": "none",     "kline_limit": None, "note": "东财A股历史，adjust 参数由调用方传入"},
    "stock_zh_a_daily":         {"native_adjust": "none",     "kline_limit": None, "note": "新浪A股历史（备用源），不支持复权"},
    "fund_etf_hist_em":         {"native_adjust": "none",     "kline_limit": None, "note": "东财ETF历史"},
    "fund_etf_hist_sina":       {"native_adjust": "none",     "kline_limit": None, "note": "新浪ETF历史（备用源），不支持复权"},
    "reits_hist_em":            {"native_adjust": "none",     "kline_limit": None, "note": "东财REITs历史"},
    "stock_hk_hist":            {"native_adjust": "none",     "kline_limit": None, "note": "东财港股日线"},
    "stock_hk_daily":           {"native_adjust": "none",     "kline_limit": None, "note": "新浪港股日线，含成交额（amount/(close×volume)≈1.007）"},
    "stock_us_hist":            {"native_adjust": "none",     "kline_limit": None, "note": "东财美股日线"},
    "stock_us_daily":           {"native_adjust": "none",     "kline_limit": None, "note": "新浪美股日线，无成交额字段"},
    "bond_zh_hs_cov_daily":     {"native_adjust": "none",     "kline_limit": None, "note": "可转债日线，无成交额→close×volume 估算并标注"},
    "bond_zh_hs_cov_min":       {"native_adjust": "none",     "kline_limit": None, "note": "东财可转债分钟，1手=10张"},
    "futures_main_sina":        {"native_adjust": "none",     "kline_limit": 1023, "note": "国内期货主力连续，保留「手」"},
    "futures_foreign_hist":     {"native_adjust": "none",     "kline_limit": None, "note": "外盘期货日线，保留「手」"},
    "futures_zh_minute_sina":   {"native_adjust": "none",     "kline_limit": 1023, "note": "期货分钟，保留「手」"},
    "option_sse_daily_sina":    {"native_adjust": "none",     "kline_limit": None, "note": "ETF 期权日线，无成交额"},
    "forex_hist_em":            {"native_adjust": "none",     "kline_limit": None, "note": "东财外汇历史，无成交量/成交额"},
    "sina_forex_min":           {"native_adjust": "none",     "kline_limit": 974,  "note": "新浪外汇分钟，无成交量单位说明"},
    "fund_open_fund_info_em":   {"native_adjust": "nav",      "kline_limit": None, "note": "场外基金净值，无成交量/成交额"},
    "bond_buy_back_hist_em":    {"native_adjust": "none",     "kline_limit": None, "note": "逆回购，收盘价为年化利率"},
    "bond_buy_back_snapshot":   {"native_adjust": "none",     "kline_limit": None, "note": "逆回购快照，仅当日一根"},
    "binance_klines":           {"native_adjust": "none",     "kline_limit": 1000, "note": "币安K线，limit≤1000 需分页；本项目单次回填上限 20000 根"},
    "stock_zh_a_minute":        {"native_adjust": "none",     "kline_limit": 1970, "note": "新浪A股分钟，实测不复权、datalen 上限 1970、无时间游标"},
    "stock_zh_a_hist_min_em":   {"native_adjust": "none",     "kline_limit": None, "note": "东财A股分钟，仅约 1 个月"},
    "fund_etf_hist_min_em":     {"native_adjust": "none",     "kline_limit": None, "note": "东财ETF分钟，仅约 1 个月"},
    "stock_us_hist_min_em":     {"native_adjust": "none",     "kline_limit": None, "note": "东财美股分钟，仅约 1 个月"},
    "stock_hk_hist_min_em":     {"native_adjust": "none",     "kline_limit": None, "note": "东财港股分钟，仅约 1 个月"},
    "baostock_daily":           {"native_adjust": "optional", "kline_limit": None, "note": "adjustflag 1=后复权/2=前复权/3=不复权"},
    "baostock_minute":          {"native_adjust": "optional", "kline_limit": None, "note": "5/15/30/60 分钟，长历史；不含指数、无 1 分钟线"},
    "index_zh_a_hist":          {"native_adjust": "none",     "kline_limit": None, "note": "东财指数历史（首选）"},
    "stock_zh_index_daily":     {"native_adjust": "none",     "kline_limit": None, "note": "新浪指数全历史（备用），无成交额"},
    "index_zh_a_hist_min_em":   {"native_adjust": "none",     "kline_limit": None, "note": "东财指数分钟，仅约 1 个月"},
    "baostock_index_daily":     {"native_adjust": "none",     "kline_limit": None, "note": "BaoStock 指数日线，代码格式 sh.000300 / sz.399001"},
}
for _meta_name, _meta in DATA_SOURCE_META.items():
    if _meta_name in DATA_SOURCE_UNITS:  # 只补元信息，绝不新增缺 8 个必填键的条目
        DATA_SOURCE_UNITS[_meta_name].update(_meta)
del _meta_name, _meta

# ---------- 对外强制统一单位（与 DATA_SOURCE_UNITS.unified_* 保持一致的口径声明） ----------
UNIFIED_VOLUME_UNIT = {
    "cn_stock": "股", "cn_etf": "份", "cn_fund": "份", "cn_convertible": "张",
    "cn_reits": "份", "hk_stock": "股", "us_stock": "股", "us_etf": "股",
    # 指数是全局唯一「统一用 手」的例外：东财/腾讯本源为手、新浪/BaoStock 本源为股，
    # 必须靠跨源验证（2026-10-27 r=volume_sina/volume_bs=1.0000）确认后再折算，未验证前标 unit_uncertain
    "cn_future": "手", "global_future": "手", "crypto": "币", "cn_index": "手",
}
UNIFIED_AMOUNT_UNIT = "native_currency"  # 元 / 港元 / 美元，原币种，不做汇率换算
# 期货各品种合约乘数不同，amount≈close×volume 不成立，禁止用其估算成交额
FUTURES_AMOUNT_NOT_APPLICABLE = True
# 无时间游标、无法分页的分钟源：只能取「最近 N 根」，超出必须显式标注 capped
MINUTE_NO_PAGINATION_SOURCES = ["sina", "eastmoney"]

# ---------- 分钟线数据源优先级 ----------
# 说明：BaoStock 支持 5/15/30/60 分钟、1990 年起、免费、volume=股，但不含指数；
#      新浪分钟无时间游标（A股 1970 / 期货 1023 / 外汇 974）；东财分钟仅约 1 个月。
MINUTE_SOURCE_PRIORITY = {
    "cn_stock": ["baostock", "sina", "eastmoney"],
    "cn_index": ["eastmoney", "sina"],   # BaoStock 分钟线不含指数；东财约 1 个月，新浪无时间游标
    "cn_etf": ["sina", "eastmoney"],
    "cn_convertible": ["eastmoney"],
    "cn_future": ["sina"],
    "global_future": ["sina"],
    "forex": ["sina"],
    "us_stock": ["eastmoney"],
    "us_etf": ["eastmoney"],
    "hk_stock": ["eastmoney"],
    "crypto": ["binance"],
}

# ---------- 代码歧义清单（未显式传 market_type 时不得静默二选一） ----------
AMBIGUOUS_CODES = {
    "ZN": ["cn_future", "global_future"],   # 沪锌（上期所）vs CBOT 10 年期美债
    "GC": ["global_future", "us_stock"],    # COMEX 黄金 vs 美股代码（默认走国际期货）
    "000001": ["cn_stock", "cn_fund"],      # 平安银行（深市个股）vs 华夏成长（场外公募，默认走个股）
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

# ---------- 16.5 北交所 ----------
# 与沪深 A 股没有一条相同：30% 涨跌幅、100 股起以 1 股递增、50 万资产 + 2 年经验门槛。
# commission_rate 未核实，置 None 并标 fee_verified=False——执行层必须显式配置后才可下单，
# 禁止按 cn_stock 费率静默套用。
BSE = {
    "name": "北交所个股",
    "min_qty": 100,
    "qty_step": 1,
    "price_step": 0.01,
    "t_plus": 1,
    "trade_direction": ["long"],
    "commission_rate": None,
    "commission_min": None,
    "stamp_tax_rate_sell": 0.0005,
    "stamp_tax_rate_buy": 0,
    "price_limit": {"main": 0.3},
    "qii_threshold_financial_assets": 500_000,
    "qii_min_invest_years": 2,
    "trading_hours": [(9*60+30, 11*60+30), (13*60, 15*60)],
    "can_short": False,
    "fee_verified": False,
    "requires_fee_config": True,
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

# ---------- 19. 指数（基准 / 择时；不可直接交易） ----------
CN_INDEX = {
    "name": "指数（基准/择时）",
    "tradeable": False,                      # 订单层遇到 cn_index 必须拒绝下单
    "trade_min_qty": 1,
    "qty_step": 1,
    "price_step": 0.01,
    "t_plus": 0,
    "commission_rate": 0.0,
    "stamp_tax_rate_sell": 0.0,
    "price_limit": None,
    "trading_hours": [(9 * 60 + 30, 11 * 60 + 30), (13 * 60, 15 * 60)],
    "not_tradeable_reason": "指数不可直接交易，请用对应 ETF/股指期货代替",
    "common_codes": {
        "000001": "上证指数", "000300": "沪深300", "000905": "中证500",
        "000852": "中证1000", "932000": "中证2000", "000016": "上证50",
        "000688": "科创50", "399001": "深证成指", "399006": "创业板指",
        "399673": "创业板50", "000010": "上证180", "000009": "上证380",
        "899050": "北证50",
    },
    # v3.40：股票池短名 → 指数代码，是「别名唯一来源」。
    # data/pit_index.py 与 factor/universe.py 一律从本表派生，模块内禁止自建清单。
    "pool_aliases": {
        "hs300": "000300", "zz500": "000905", "zz1000": "000852",
        "zz2000": "932000", "all_a": "ALLA",
    },
}

# 带交易所前缀的指数代码规则：SH/SZ/BJ + 6 位，前 3 位命中即视为指数
INDEX_PREFIX_RULES = {
    "SH": ("000", "950", "880", "881"),
    "SZ": ("399", "980", "981"),
    "BJ": ("899",),                      # 北证50（899050）等北交所指数段
}

# 个股号段规则：后缀 + 代码段【联合】判定用。
# 关键：000xxx 既是上交所指数段，也是深交所个股段（000001=平安银行），
# 所以「SZ + 000」不是冲突，「SH + 000」才是指数。只有两边的号段都不认，
# 才是真冲突（如 399001.SH、600519.SZ）。
# BJ：2025-10-09 起北交所个股只有 920 段（43/83/87/88 已整体退出北交所，只属新三板）。
STOCK_PREFIX_RULES = {
    "SH": ("600", "601", "603", "605", "688"),
    "SZ": ("000", "001", "002", "003", "300", "301"),
    "BJ": ("920",),
}

# 可「裸识别」为指数的 6 位代码（不带 sh/sz 前缀也能无歧义判定）
# 关键事实：深市个股号段为 000/001/002/003，与沪市指数 000xxx 段【完全重合】
#   （000001=平安银行、000009=中国宝安、000016=深康佳A、000688=国城矿业），
#   因此 000xxx 段必须维持「个股优先」，取指数务必带前缀（sh000300）。
# 而 399xxx（深证系列）、932xxx（中证2000）不与深市个股冲突，可裸识别。
CN_INDEX_BARE_CODES = {
    "399001": "深证成指",
    "399005": "中小板指",
    "399006": "创业板指",
    "399673": "创业板50",
    "932000": "中证2000",
    "899050": "北证50",
}


def _alias_key(text) -> str:
    """别名归一化键：去空格/下划线/连字符 + 小写（「HS 300」「hs_300」等价）。"""
    out = str(text).strip().lower()
    for ch in (" ", "\t", "_", "-"):
        out = out.replace(ch, "")
    return out


# 指数别名表：唯一来源是上面的 CN_INDEX（common_codes 中文全名 + pool_aliases 短名）。
# 教训：别名单源定义了却没人消费 = 清单换个位置继续漂移；detect_market_type 与
# data.pit_index 都必须读这张表，禁止各写一份。
CN_INDEX_ALIASES = {
    **{_alias_key(name): code
       for code, name in (CN_INDEX.get("common_codes") or {}).items()},
    **{_alias_key(alias): code
       for alias, code in (CN_INDEX.get("pool_aliases") or {}).items()},
}

# 指数日线取数优先级（东财含成交额首选；新浪全历史；BaoStock 备份；腾讯未接入）
# 注意：tencent 源仅有一个名为 amount 的数量列，实测为「成交量(手)」而非成交额，
#       接入前必须改造，当前 data_fetcher 会显式报「未接入」而不是静默取到错误单位。
CN_INDEX_DAILY_PRIORITY = ["eastmoney", "sina", "baostock", "tencent"]

# 指数成交量单位已用 BaoStock 独立交叉验证（2026-10-27 sh.000300 r=volume_sina/volume_bs=1.0000
# → 新浪 volume=股、×0.01 转手正确）。置 True 后指数日线不再标 attrs["unit_uncertain"]；
# 指数分钟单位仍未实测，仍会标 unit_uncertain。
CN_INDEX_UNIT_VERIFIED = True

# 过期（stale）数据的容忍上限，单位＝「交易日差」（用交易日历计算，不是自然日）：
# 本地库最后一根 K 线距最近已收盘交易日相差的天数超过该值 → 视为不可用，取数直接报错。
# 使用边界：回测/研究/因子可用 stale；图表可用但必须标注「数据截至 X 日」；
#           模拟盘/实盘的下单决策【禁止】使用 stale（调用方声明 for_trading=True 时直接报错）。
STALE_LIMIT = {"daily": 5, "minute": 2}

# 时效闸门总开关：仅在 paper/live 运行模式下生效（backtest 必须豁免——回测本来就跑历史数据，
# 相对今天永远「过期」，无条件拦截会把所有回测拒掉）。闸门按 config.RUN_MODE 判断，见
# data_fetcher._stale_gate_enabled。
TRADING_REQUIRE_FRESH = True

# attrs 易失性（pandas 2.3.3 实测）：concat/merge/groupby/resample().agg()/diff/pct_change/
# cumsum/astype/布尔索引均保留 attrs；但 rolling()/ewm()/expanding() 会把 attrs 清空，
# to_numpy() 重建也会丢。指标（MA/EMA/MACD/RSI/BOLL/ATR）全走窗口运算 → 经过指标计算后
# 数据层标的 stale 标记就没了。因此下单/策略必须在「用数那一刻」重新校验时效，禁止只读
# 中间帧的 attrs["stale"]。
ATTRS_FRAGILE_NOTE = ("DataFrame.attrs 经 rolling/ewm/expanding 窗口运算及 to_numpy 重建后会丢失，"
                      "禁止仅凭 attrs['stale'] 做交易决策")

# 时效信息物化列：数据层出口除了 attrs，还会把「本帧数据最新日期」逐行写入该普通列。
# 普通列能穿过 rolling/ewm/expanding/resample/concat，不会像 attrs 被清空，
# 所以指标计算完仍能读到时效，供下单前复核使用。
STALE_INFO_COLUMN = "data_asof_date"

# 时效复核模式："refetch" = 下单前从数据层重新取一次该标的最新数据比对交易日历
# （完全不依赖传入帧的 attrs）。可选 "attrs"（只读物化列/attrs，不重取）。
STALE_CHECK_MODE = "refetch"

# fail-closed 的适用边界：只有「既没有时效列、又无法重取」时才可以拒绝；
# 不得把 fail-closed 当唯一防线，否则指标计算（rolling/ewm/expanding 清空 attrs）后的
# 数据会在下单时被全部拒单，实盘直接瘫痪。
FAIL_CLOSED_NOTE = ("fail-closed 仅在「既无时效列、又无法重取」时使用；不得作为唯一防线，"
                    "否则指标计算后的数据会在下单时被全部拒单")

# 下单前 refetch 的复用窗口（秒）：组合调仓一次验几十上百个标的，同一批次内复用结果，
# 避免逐单打满数据源接口、拖慢下单。
STALE_REFETCH_TTL_SEC = 60

# refetch 失败（网络抖动/数据源不可达）时的处置：开仓拒单、平仓放行。
# 不能因为取不到行情就下不出止损/平仓单，否则持仓无法退出。
STALE_REFETCH_FAIL_POLICY = {"open": "reject", "close": "allow"}

# 数据源当前可用性 —— 这是「当前实测现状」，不是永久事实：
# 会随本机网络环境/数据源限流变化（东财 push2his 目前 RemoteDisconnected）。
# 架构上必须支持自动探测 + 切换（tools/source_status.py 探测 → 第 13 步据此做多源切换），
# 禁止把 available 当硬编码开关去静态决定取数路径。
SOURCE_AVAILABILITY = {
    "eastmoney": {"available": False, "note": "push2his 本机持续 RemoteDisconnected（个股/ETF/指数 日线+分钟 全线）"},
    "sina":      {"available": True,  "note": "A股/期权/期货/外汇 可用"},
    "baostock":  {"available": True,  "note": "A股日线 + 5/15/30/60 分钟；不含指数分钟"},
    "tencent":   {"available": True,  "note": "指数日线备用；amount 列实为成交量(手)"},
    "binance":   {"available": True,  "note": "加密；独立于东财/新浪"},
}

# 单点故障市场（只有一个可用源，源挂即彻底取不到）：
# daily  = 日线无备源；minute = 分钟线仅东财（日线有备源，属「日线可回退、分钟单点」的不对称）。
# 第 13 步补源优先级最高：先给这些市场补第二源，再接多源自动切换。
# 取数失败时必须显式抛错（RuntimeError 含「该市场当前无可用数据源」），禁止静默返回空表。
SINGLE_SOURCE_MARKETS = {
    "daily":  ["forex", "cn_fund", "cn_reverse_repo"],
    "minute": ["cn_convertible", "us_stock", "us_etf", "hk_stock"],
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

# 复权口径全局默认（v3.33 统一：默认后复权，所有默认值从这里取，禁止多处硬编码qfq）
DEFAULT_ADJUST = "hfq"

# ==================== 回测默认参数 ====================
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

# ==================== K 线周期（全局唯一事实源） ====================
# 周期字符串全系统统一，禁止再用 1 / 60 这类纯数字；取数路由见 DataFetcher.get_kline()
SUPPORTED_PERIODS = ["1d", "1w", "1M", "1min", "5min", "15min", "30min", "60min"]  # 周期全集
PERIOD_TO_MINUTE = {"1min": 1, "5min": 5, "15min": 15, "30min": 30, "60min": 60}  # 唯一映射
DAILY_PERIODS = ["1d", "1w", "1M"]                                              # 走 get_daily
MINUTE_PERIODS = ["1min", "5min", "15min", "30min", "60min"]                     # 走 get_minute

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
    # 出图周期：SUPPORTED_PERIODS 去掉 1min（1min 可取数但不默认出图）
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
    # 三类点（B3/S3）可选的「离开段强度」过滤，默认关闭：
    # 本实现是轻量缠论，三类点天然稀疏且对 MAX_CENTER_BI 敏感；开启后要求离开笔
    # 相对中枢边界 ZG/ZD 的幅度 ≥ b3_min_leave_pct，且离开段均量 ≥ 中枢期均量 × 放量倍数。
    "b3_filter_enable": False,
    "b3_min_leave_pct": 0.0,
    "b3_min_leave_volume_ratio": 0.0,
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
    "data_source_priority": ["akshare", "baostock", "tushare", "local"],  # v3.32 补 baostock 免费备份源
    "source_timeout_seconds": 15,          # v3.32 补：13.1 正文引用本键，此前缺失
    # ---- v3.45 / 13.0.16：数据源适配器 6 个 fail-closed 闸门（默认全开）----
    "failover_log_required": True,         # 主源挂了悄悄切换 → 必须 warning + notifier
    "field_consistency_required": True,    # akshare 手 / baostock 股 静默拼接 → 必须先归一
    "tokenless_sources_first": True,       # tushare 无 token 时跳过 info，不阻断全链路
    "max_consecutive_failures": 3,         # 单源连坏 N 次 → 标记 unhealthy，下次跳过
    "local_fallback_must_exist": True,     # 全远程失败且本地空 → 必须报错，禁止空表当成功
    "source_health_file": "data_cache/source_health.json",  # 探活结果落盘位置
    "cache_max_gb": 20,                # v3.32 补：13.9 正文引用本键，此前缺失
    "snapshot_retention_days": 2190,   # v3.32 补：13.4 引用本键；必须 >= 最长报告保留期（6年）
    "data_source_failover": True,
    "save_raw": True,                  # 原始不复权价落盘
    "save_adj_factor": True,           # 复权因子单独落盘
    "default_adjust_for_backtest": DEFAULT_ADJUST,
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

# ==================== 数据源适配器结构性守卫（v3.46 / 13.0.17）====================
# 13.1 实测暴露的六类结构性缺口（现象修了、结构没修）：
#   ① 单位口径表被复制成第二份：DATA_SOURCE_UNITS 按【接口名】定义，适配器又按
#      【源+市场+周期】三元组起一份 → 两套维度描述同一事实，必然漂移（实测出现 ×100 重复折算）；
#   ② internal_failover 由「被守卫对象自己声明」= 自己给自己发豁免，被限流也永不熔断 → 封 IP；
#   ③ local_fallback_must_exist 是悬空键：兜底甩给外层 get_daily，直调 DataRouter.fetch 的路径没有兜底；
#   ④ router_all_empty 把「故障空」当「合法空」：被限流常返回空而不抛异常，标的静默失效；
#   ⑤ 哈希闸门自证：作者与登记者同一人（见 SPEC_PROVENANCE）；
#   ⑥ 冻结口径漂移：test_data 固定 13 项被报成「12 组」，必须报原始计数。
DATA_SOURCE_ADAPTER_GUARD = {
    "unknown_unit_combo_must_raise": True,           # 未登记组合 → raise，禁止默认乘 1
    "source_interface_map_is_single_source": True,   # 单位口径唯一索引：接口名 → DATA_SOURCE_UNITS
    "adapter_must_not_duplicate_unit_table": True,   # 适配器内禁止再定义第二份 (源,市场,周期) 单位表
    "internal_failover_whitelist_only": True,        # 「内部已有回退链」只能由 INTERNAL_FAILOVER_SOURCES 决定
    "failure_counting_layered": True,                # 市场级豁免 / 源级必计，两层不得混淆
    "market_level_failure_exempt": True,
    "source_level_failure_must_count": True,
    "router_must_hold_local_source": True,           # 本地兜底是路由器职责，缺 LocalSource → 构造即 raise
    "router_all_empty_requires_probe_evidence": True,  # 全远程净空必须带交易日探活证据
    "expected_trading_day_empty_must_raise": True,   # 应交易日 + 在市 + 净空 → 升级为异常
    "adapter_health_probe_writes_file": True,        # 探活结果必须落盘（source_health_file）
    "unit_table_interface_names_verified": True,     # SOURCE_INTERFACE_MAP 的值必须逐个存在于 DATA_SOURCE_UNITS
    # ---- F 段（v3.47 / 13.0.18）----
    "map_scope_must_equal_supported_scope": True,     # 索引桥 key 集合 == config.SUPPORTED_KLINE_MARKETS
    "supported_scope_single_source": True,            # 支持清单只有 config 一份，data_fetcher 派生
    "map_scope_missing_must_raise": True,             # 缺一个组合 → 构造即 raise，不得通配兜底
    "empty_evidence_only_from_security_master": True,  # empty 证据只能来自证券主数据
    "tried_must_include_empty_sources": True,         # 报错「已尝试」必须含返回空表的源
    # ---- v3.48 / 13.0.19 ④：探针上游独立性与日期归一在路由侧的镜像键 ----
    "listing_probe_required": True,                  # 净空判定路径必须能向证券主数据取证
    "as_of_normalization_required": True,            # 时点闸门入口必须先归一日期格式（硬前置）
    "probe_upstream_must_be_independent": True,      # 探针上游不得与行情源共享接口
}

# ---------- 单位口径唯一索引桥：(源, 市场, 周期) → 接口名元组 ----------
# 适配器只查这张桥 + DATA_SOURCE_UNITS，禁止再自建按 (源, 市场, 周期) 索引的单位表。
# 取值规则：以元组首个接口（主源）的 volume / volume_factor / unified_volume 为准；
# 同一组合内的备源必须与主源的 unified_volume 一致，否则跨源拼接会触发 field_consistency_required。
SOURCE_INTERFACE_MAP = {
    # ---- akshare 日线（15 个走取数实现的市场，含各自内部回退链）----
    ("akshare", "cn_stock", "daily"): ("stock_zh_a_hist", "stock_zh_a_daily"),
    ("akshare", "cn_etf", "daily"): ("fund_etf_hist_em", "fund_etf_hist_sina"),
    ("akshare", "us_stock", "daily"): ("stock_us_hist", "stock_us_daily"),
    ("akshare", "us_etf", "daily"): ("stock_us_hist", "stock_us_daily"),
    ("akshare", "hk_stock", "daily"): ("stock_hk_hist", "stock_hk_daily"),
    ("akshare", "cn_convertible", "daily"): ("bond_zh_hs_cov_daily",),
    ("akshare", "cn_reits", "daily"): ("reits_hist_em", "fund_etf_hist_sina"),
    ("akshare", "cn_future", "daily"): ("futures_main_sina",),
    ("akshare", "global_future", "daily"): ("futures_foreign_hist",),
    ("akshare", "forex", "daily"): ("forex_hist_em",),
    ("akshare", "cn_option", "daily"): ("option_sse_daily_sina",),
    ("akshare", "crypto", "daily"): ("binance_klines",),
    ("akshare", "cn_fund", "daily"): ("fund_open_fund_info_em",),
    ("akshare", "cn_reverse_repo", "daily"): ("bond_buy_back_hist_em", "bond_buy_back_snapshot"),
    ("akshare", "cn_index", "daily"): ("index_zh_a_hist", "stock_zh_index_daily", "baostock_index_daily"),
    # ---- akshare 分钟线（10 个走取数实现的市场）----
    ("akshare", "cn_stock", "minute"): ("stock_zh_a_hist_min_em", "stock_zh_a_minute"),
    ("akshare", "cn_etf", "minute"): ("fund_etf_hist_min_em", "stock_zh_a_minute"),
    ("akshare", "cn_index", "minute"): ("index_zh_a_hist_min_em", "stock_zh_a_minute"),
    ("akshare", "us_stock", "minute"): ("stock_us_hist_min_em",),
    ("akshare", "us_etf", "minute"): ("stock_us_hist_min_em",),
    ("akshare", "hk_stock", "minute"): ("stock_hk_hist_min_em",),
    ("akshare", "cn_convertible", "minute"): ("bond_zh_hs_cov_min",),
    ("akshare", "cn_future", "minute"): ("futures_zh_minute_sina",),
    ("akshare", "forex", "minute"): ("sina_forex_min",),
    ("akshare", "crypto", "minute"): ("binance_klines",),
    # ---- baostock（会话绑定线程；分钟线不含指数）----
    ("baostock", "cn_stock", "daily"): ("baostock_daily",),
    ("baostock", "cn_stock", "minute"): ("baostock_minute",),
    ("baostock", "cn_index", "daily"): ("baostock_index_daily",),
}

# ---------- 「适配器内部已有多级回退链」白名单（不得由适配器自声明）----------
# 只有这里列出的源，才允许在日志里标注「单市场报错 ≠ 整源已死」；但【源级失败仍然计数】，
# 因为被墙/被限流是源级失效，永不熔断会变成反复重连 —— 那正是封 IP 的触发条件。
INTERNAL_FAILOVER_SOURCES = ("akshare",)

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

# ==================== 北交所号段迁移（2025-10-09）====================
# 事实（监管/数据源口径）：北交所 2024-04-22 起新上市公司启用 920 段（首只 920002 万达轴承），
#   2025-10-09 存量公司整体切换到 920；自此 43/83/87/88 只属新三板，.BJ 后缀仅对北交所有意义。
# 因此「.BJ + 43/83/87/88」是【已失效写法】，不是 neeq、也不是 cn_stock：
#   给了 as_of 且早于切换日 → 按北交所历史判定；否则查迁移表，查不到直接 raise。
# 全表（约 248 条）必须从数据源落盘，禁止手写；anchors 只登记已核实的锚点。
BSE_CODE_MIGRATION = {
    "effective_date": "2025-10-09",
    # v3.44：号段的 as-of 是【双边】的——旧段有退出日（2025-10-09），新段也有启用日
    # （2024-04-22 首只 920002 万达轴承）。as_of 早于启用日 = 引用当时不存在的代码。
    # 注意：消费方用强制下标 conf["segment_effective_date"]，键缺失即 KeyError，
    # 禁止 .get() 静默跳过校验（本键曾因编辑覆盖丢失而未被察觉，教训已写入 13.0.14）。
    "segment_effective_date": "2024-04-22",
    "current_segment": "920",
    "legacy_segments": ("43", "83", "87", "88"),
    "table_source": "tushare.bse_mapping",
    "table_required_for_backtest": True,
    "table": {},                     # 运行时由数据源落盘填充；空表 = 查不到即 raise
    "anchors": {                     # 仅已核实锚点，禁止用猜测值扩充
        "920002": {"name": "万达轴承", "listed": "2024-04-22", "kind": "new_listing"},
    },
}


def _as_of_date_str(as_of) -> str:
    """把 as_of 归一成 ``YYYY-MM-DD`` 字符串（ISO 日期可直接字典序比较）。"""
    if as_of is None:
        return ""
    text = str(as_of).strip()[:10]
    parts = text.split("-")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"as_of 必须是 YYYY-MM-DD 或日期对象，收到 {as_of!r}")
    return text


def _resolve_bse_body(code: str, as_of=None) -> str:
    """解析北交所个股代码：920 段为现行唯一号段，43/83/87/88 为 2025-10-09 前旧段。

    「.BJ + 旧段」是已失效写法——给 as_of 早于切换日才判北交所历史，否则查迁移表，
    查不到 raise，禁止静默归入 neeq / cn_stock（两者费率、涨跌幅、门槛完全不同）。
    """
    digits = str(code).strip()
    if len(digits) != 6 or not digits.isdigit():
        raise ValueError(f"北交所代码必须是 6 位数字，收到 {code!r}")
    conf = BSE_CODE_MIGRATION
    day = _as_of_date_str(as_of)
    if digits.startswith(conf["current_segment"]):
        # 920 段启用日校验（v3.44）：早于 2024-04-22 该代码不存在，提前引用即未来函数；
        # as_of 缺省视为「现在」（920 早已启用，既有调用方不受影响）。
        # 强制下标取键：segment_effective_date 缺失直接 KeyError，禁止 .get() 静默跳过。
        seg_day = conf["segment_effective_date"]
        if day and seg_day and day < seg_day:
            raise ValueError(
                f"{digits}.BJ 未来函数：920 号段 {seg_day} 才启用（首只 920002 万达轴承），"
                f"as_of={day} 早于启用日，该代码当时不存在")
        return "bj_stock"
    legacy = tuple(conf.get("legacy_segments") or ())
    if digits[:2] not in legacy:
        raise ValueError(
            f"{digits}.BJ 段位与后缀矛盾：{digits[:3]}xxx 既不是北交所现行 "
            f"{conf['current_segment']} 段，也不是 2025-10-09 前的旧段"
            f"（{'/'.join(legacy)}）")
    day = _as_of_date_str(as_of)
    if day and day < conf["effective_date"]:
        return "bj_stock"
    if (conf.get("table") or {}).get(digits):
        return "bj_stock"
    raise ValueError(
        f"{digits}.BJ 是 2025-10-09 起失效的北交所旧代码（43/83/87/88 段已整体迁至 920，"
        f"该段此后只属新三板）；历史回测请显式传 as_of<={conf['effective_date']}，"
        f"或按 {conf['table_source']} 迁移表改写为新代码（迁移表未落盘时禁止猜测映射）")


# ==================== 代码自动识别市场 ====================
MARKET_CODE_RULES = {
    "us_stock":     {"prefix": [], "suffix": [], "alphas_6_only": False, "numeric": False},
    "hk_stock":     {"prefix": ["0"], "numeric_5": True},
    "cn_reits":     {"prefix": ["508", "180"]},
    "cn_convertible":{"prefix": ["11", "123", "127", "128", "113", "110", "111", "123"]},
    "cn_etf":       {"prefix": ["51", "52", "56", "58", "15", "16", "18"]},
    "neeq":         {"prefix": ["43", "83", "87", "88"]},
    "bj_stock":     {"prefix": ["920"]},
    "cn_future":    {"letter_digit_mix": True},
    "global_future":{"letter_only": True, "max_len": 3},
    "forex":        {"6_letter_ccy": True},
    "crypto":       {"letter_only": True, "min_len": 2, "max_len": 5},
    "option":       {"suffix_pattern": True},
}

def detect_market_type(code: str, market_type: str = None, as_of=None) -> str:
    """根据代码前缀/格式自动识别市场类型，返回 config.MARKETS 的 key。

    显式传入 market_type 时直接返回该值（用于私募/资管/场外衍生品等非标准代码，
    以及 GC 这类美股/国际期货存在歧义的品种）。

    ``as_of``：仅在「.BJ + 2025-10-09 前的北交所旧代码（43/83/87/88 段）」时需要，
    用于历史回测判定；不传则查 BSE_CODE_MIGRATION 迁移表，查不到直接 raise。

    注意：6位A股/ETF/基金/转债的代码段本身存在歧义（如00开头既可能是深市个股也可能是基金），
    纯字母短代码（2-3位）在美股/期货/加密之间也存在歧义。本函数按"最常见场景"给出默认值，
    遇到歧义时请在调用处显式传入 market_type 参数覆盖。
    """
    if market_type:
        return str(market_type).strip().lower()

    code = str(code).strip()

    # ===== 指数别名（必须先于「字母+数字 = 国内期货」贪心分支）=====
    # 教训：汉字与字母都满足 isalpha()，沪深300 / hs300 / 北证50 原本一路落进
    # cn_future，被当成期货主力连续取数——静默错数据。别名表只认 CN_INDEX_ALIASES。
    if _alias_key(code) in CN_INDEX_ALIASES:
        return "cn_index"

    code = code.upper()
    # 交易所后缀（000300.SH / sz399001 / 920309.BJ）先剥离，再按号段判定；
    # .BJ 是权威交易所标记，不能剥完就当裸码——否则旧段会被下面的号段表覆盖成 neeq。
    suffix = ""
    for item in (".SH", ".SZ", ".BJ", "-SH", "-SZ", "-BJ"):
        if code.endswith(item):
            suffix, code = item[1:], code[:-len(item)]
            break

    # ===== 北交所：.BJ 后缀 / bj 前缀都走同一条解析 =====
    # 先判 BJ 指数段（899xxx，如北证50），再判北交所个股（920 现行段 / 43·83·87·88 旧段）
    if suffix == "BJ" or (len(code) == 8 and code.startswith("BJ") and code[2:].isdigit()):
        digits = code if suffix == "BJ" else code[2:]
        if digits[:3] in tuple(INDEX_PREFIX_RULES.get("BJ") or ()):
            return "cn_index"
        return _resolve_bse_body(digits, as_of)
    if suffix:
        code = suffix + code

    # ===== A股6位数字 =====
    if len(code) == 6 and code.isdigit():
        p3, p2 = code[:3], code[:2]
        # 裸 6 位指数（无歧义段：399xxx 深证系列 / 932xxx 中证2000）
        # 必须置于深市个股 000/001/002/003 判断之前；000xxx 段与深市个股完全重合，
        # 不在此列，取沪市指数请传 sh000300。
        if code in CN_INDEX_BARE_CODES:
            return "cn_index"
        # 国债逆回购：204开头（沪）、1318开头（深）
        if p3.startswith("204") or p3.startswith("131"):
            return "cn_reverse_repo"
        # 公募REITs：508/180开头
        if p3 in ("508",) or p3.startswith("180"):
            return "cn_reits"
        # 北交所个股：920 段（2024-04-22 启用、2025-10-09 起唯一号段）。
        # 启用日 as-of 校验统一在 _resolve_bse_body，禁止在此另写一份。
        if p3 == "920":
            return _resolve_bse_body(code, as_of)
        # 新三板：43/83/87/88 开头；2025-10-09 之前这些段属北交所（历史回测接 as_of，
        # 否则旧时段的北交所股票会被当新三板处理，撮合/涨跌幅规则全错）
        if p2 in ("43", "83", "87", "88"):
            day = _as_of_date_str(as_of)
            if day and day < BSE_CODE_MIGRATION["effective_date"]:
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

    # ===== 带交易所前缀的指数：SH/SZ + 6 位（如 sh000300、sz399001）=====
    # 必须【先于】下面「字母+数字混合 → cn_future」判定，否则 sh000001/sh000300 会被当成期货；
    # 非指数段（sh600519/sz000001 等）剥前缀后按标准 6 位规则重判，不影响个股/ETF。
    if len(code) == 8 and code[:2] in INDEX_PREFIX_RULES and code[2:].isdigit():
        prefix, digits = code[:2], code[2:]
        if digits.startswith(INDEX_PREFIX_RULES[prefix]):
            return "cn_index"
        return detect_market_type(digits)

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
        # 国内期货品种优先（如 RB 螺纹钢、AU 沪金）；ZN 同时是沪锌与美债，保留国际期货判定
        if code in CN_FUTURES_VARIETY and code != "ZN":
            return "cn_future"
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
    "bj_stock":        ("BSE", None),
    "private_fund":    ("PRIVATE_FUND", None),
    "qii_product":     ("QII_PRODUCT", None),
    "otc_deriv":       ("OTC_DERIV", None),
}
ALL_MARKET_TYPES = list(MARKET_CONFIG_MAP)

def get_market_config(market_type: str) -> dict:
    """统一获取19类市场中任一市场的交易规则参数，禁止后续代码直接写 config.MARKETS[...]。"""
    entry = MARKET_CONFIG_MAP.get(market_type)
    if entry is None:
        raise KeyError(f"未知市场类型: {market_type}，可用市场: {ALL_MARKET_TYPES}")
    dict_name, sub_key = entry
    d = globals()[dict_name]
    return d if sub_key is None else d[sub_key]

# ==================== 合格投资者层（第 10 步开工前置 · G1）====================
# 合格投资者不是「一次性资格标记」，而是【每个申购/受让动作的闸门】：
#   check_actions 覆盖 subscribe / transfer / additional_subscribe / nominee_change，
#   与 place_order / 申购闸门同一收口；on_fail="reject" 表示不过即拒绝该动作，
#   禁止返回 (bool, reason) 让调用方自行决定；audit_log_required=True 每次校验留痕。
# 三套门槛各自独立、不得混用：私募（证监会令第105号）/ 资管（银发〔2018〕106号）/
#   信托（银监会令2007年第3号）。金额单位统一为「万元」。
# look_through_required：合伙/契约等非法人形式汇集资金必须穿透至最终投资者并合并人数；
#   forbid_pooling_nominee_split / forbid_non_own_funds：禁拼单、代持、拆分份额、借用他人名义。
# published_2026：区分「已发布待施行」（资产管理信托管理办法，2027-01-01 施行）
#   与「征求意见稿」（私募投资基金监督管理办法），不得笼统写「尚未生效」。
QUALIFIED_INVESTOR_RULES = {
    "private_fund": {"legal_basis": "证监会令第105号",
        "individual": {"financial_assets_wan": 300, "avg_annual_income_wan_3y": 50},
        "institution": {"net_assets_wan": 1000}, "min_per_product_wan": 100, "max_investors": 200},
    "amr_product": {"legal_basis": "银发〔2018〕106号",
        "individual": {"family_fin_net_assets_wan": 300, "family_fin_assets_wan": 500,
                       "avg_annual_income_wan_3y": 40, "min_invest_years": 2},
        "institution": {"net_assets_wan": 1000},
        "min_per_product_wan": {"fixed_income": 30, "mixed": 40, "equity": 100, "derivatives": 100},
        "max_investors": 200},
    "trust_plan": {"legal_basis": "银监会令2007年第3号",
        "individual": {"fin_assets_wan": 100, "annual_income_wan_3y": 20,
                       "couple_annual_income_wan_3y": 30},
        "min_per_product_wan": 100, "max_natural_persons": 50},
    "check_at_every_action": True,
    "check_actions": ["subscribe", "transfer", "additional_subscribe", "nominee_change"],
    "look_through_required": True, "forbid_pooling_nominee_split": True, "forbid_non_own_funds": True,
    "on_fail": "reject", "audit_log_required": True,
    "published_2026": {
        "资产管理信托管理办法": {"status": "已发布待施行", "issue_date": "2026-10-30",
                                  "effective_date": "2027-01-01", "max_investors": 200,
                                  "recheck_on": ["buy", "transfer"]},
        "私募投资基金监督管理办法": {"status": "征求意见稿",
                                      "note": "自然人LP投向单一标的专项基金门槛拟提至1000万"},
    },
    # 10.1 另含新三板/场外衍生品门槛（指令集 10.1 要求，数值同样不得硬编码）
    "neeq": {"innovation_wan": 100, "base_wan": 200, "min_invest_years": 2},
    "otc_institutional": {"net_assets_wan": 5000, "financial_assets_wan": 2000,
                          "min_invest_years": 3},
}

# ==================== 净值三层口径（第 10 步开工前置 · G2）====================
# 单一产品净值曲线算不出投资者费后净值：业绩报酬 carry 是 per-investor 的，
# 不同申购时点 → 不同高水位 → 不同计提。因此必须显式区分三层：
#   product_gross  产品毛净值（仅扣投资损益，未扣任何费用）
#   product_net    产品费后净值（扣管理费 + 托管费，仍为产品级）
#   investor_net   投资者费后净值（再扣申赎费 + 按投资者高水位计提的业绩报酬）
# 对外披露固定用 investor_net（disclosure_layer），禁止拿产品毛净值当「组合净值曲线」。
NAV_PRODUCT_CONFIG = {
    "nav_layers": ["product_gross", "product_net", "investor_net"],
    "disclosure_layer": "investor_net",
    "disclosure_frequency": {"private_fund": "weekly", "qii_product": "weekly",
                             "trust_plan": "weekly", "cn_reits": "daily"},
    "disclosure_lag_days": {"private_fund": 2, "qii_product": 2, "trust_plan": 2, "cn_reits": 1},
    "enforce_decision_after_disclosure": True,
    "fee_model": {"management_fee_annual_pct": 0.015, "performance_fee_pct": 0.20,
                  "custodian_fee_annual_pct": 0.002, "subscription_fee_pct": 0.01,
                  "redemption_fee_by_holding_days": {"<7": 0.015, "<30": 0.005, ">=30": 0.0}},
    "carry_is_per_investor": True,
    "redemption_settlement_days": {"private_fund": 3, "qii_product": 3, "trust_plan": 3},
    "forbid_nav_as_kline": True,
    # 10.3：只有净值披露日（开放日）可申赎；锁定期内禁止赎回（天）
    "enforce_open_day": True,
    "lockup_days": {"private_fund": 180, "qii_product": 90,
                    "trust_plan": 180, "cn_reits": 0},
    "rebalance_frequency": {"private_fund": "monthly", "qii_product": "monthly",
                            "trust_plan": "monthly", "cn_reits": "monthly"},
}

# ==================== 对外披露一致性（第 10 步开工前置 · G4）====================
# 对外披露是【第四个输出口 investor_disclosure】：必须与引擎同源、含费用明细、
# 含被抑制信号、明确标注「回测/模拟/实盘」、附风险揭示；禁止只报最有利区间；
# 禁止出现「保本 / 保收益 / 零风险」字样（信托办法第八条明文禁止）。
DISCLOSURE_CONFORMANCE = {
    "is_output_port": True, "must_share_engine_source": True,
    "must_include_fee_breakdown": ["subscription", "redemption", "management", "performance", "custodian"],
    "must_include_suppression": True, "must_label_type": ["backtest", "paper", "live"],
    "forbid_selective_period": True, "forbid_guarantee_wording": True,
    "require_risk_disclosure": True, "require_qi_audit_trail": True,
}

# ==================== 合格投资者层盯盘提醒（第 10 步 10.5）====================
# 「提醒 ≠ 拦截」：这些事件只做通知；真正的动作拦截仍由 core/qualified_investor.py
# 的逐动作闸门负责。提醒类型必须在 SIGNAL_EGRESS_CONFORMANCE["alert_types"] 登记，
# 未登记的类型 notifier 拒绝发送（防止绕过出口清单）。
QI_MONITOR_ALERTS = {
    "private_fund_nav_update": {"level": "info", "dedup_minutes": 720,
                                "desc": "私募/资管产品新净值披露提醒"},
    "reits_dividend_announce": {"level": "info", "dedup_minutes": 720,
                                "desc": "REITs 分红公告与除权日提醒"},
    "reits_premium_alert": {"level": "warning", "dedup_minutes": 240,
                            "desc": "REITs 折溢价超阈值（折价>10% / 溢价>15%）"},
    "neeq_delisting_warning": {"level": "error", "dedup_minutes": 720,
                               "desc": "新三板持仓退市风险公告"},
    "neeq_liquidity_deterioration": {"level": "warning", "dedup_minutes": 720,
                                     "desc": "新三板连续 N 天零成交"},
    "snowball_knock_in_warning": {"level": "warning", "dedup_minutes": 240,
                                  "desc": "模拟雪球接近敲入线（仅模拟账户）"},
    "snowball_knock_out_observe": {"level": "info", "dedup_minutes": 720,
                                   "desc": "模拟雪球敲出观察日"},
    "qi_threshold_check": {"level": "warning", "dedup_minutes": 1440,
                           "desc": "资产规模变动后重新校验合格投资者资格（仅提醒）"},
}
QI_REITS_PREMIUM_THRESHOLDS = {"discount": -0.10, "premium": 0.15}
QI_NEEQ_ZERO_VOLUME_DAYS = 5

# ==================== 实盘安全（第 12 步开工前置 K2–K8） ====================
# 本步是系统第一次「指令能真的动到钱」，默认永远是安全的：
#   authoritative：对账权威在券商侧，本地账本只是可能过期的副本；
#   reconcile：报单前 + 盘中定时（60s）+ 启动 + 日终四处对账，
#              不一致立即停开新仓，只有人工确认才能恢复；
#   idempotency：每笔报单带唯一 client_order_id 并落盘，跨重启保留；
#              同键窗口内重复提交拒绝；状态未知（超时/断连）先查券商再决定是否重发；
#   kill_switch：急停标志落盘，重启后仍处于停机态；
#   mode_change_requires_flat：切换模式（含降级）前必须无持仓、无在途单；
#   forbid_silent_mode_fallback：实盘连不上券商必须报错停机，不得静默退回仿真/回测；
#   first_live_order_max_notional：首笔实盘限额，确认通道正常后才放开；
#   personal_derivatives_live_forbidden：场外衍生品在真实报单路径硬拦，只允许仿真。
LIVE_SAFETY = {
    "authoritative": "broker",
    "reconcile": {
        "pre_order": True,
        "startup": True,
        "interval_sec": 60,
        "eod": True,
        "on_mismatch": "halt_new_orders",
        "resume_requires": "manual_confirm",
        "tolerance": 0.01,
        "state_file": "live_trading/reconcile_state.json",
    },
    "idempotency": {
        "format": "{strategy}-{symbol}-{direction}-{bar_date}-{seq}",
        "persist_path": "live_trading/order_ids.json",
        "dedup_window_sec": 600,
        "on_duplicate": "reject",
        "on_unknown_state": "query_broker_first",
    },
    "kill_switch": {
        "persist": True,
        "flag_file": "live_trading/KILL_SWITCH",
        "panic_liquidate": False,
        "check_interval_sec": 1.0,
        "independent_thread": True,
        "manual_clear_token": "MANUAL_CONFIRM",
    },
    "mode_change_requires_flat": True,
    "forbid_silent_mode_fallback": True,
    "mode_label_required": True,
    "first_live_order_max_notional": 10000.0,
    "personal_derivatives_live_forbidden": True,
}

# ==================== 报单唯一收口（第 12 步开工前置 K5） ====================
# 每接一个券商就多一条报单通道：适配器只实现「发单原语」，决策（闸门/风控/对账/
# 幂等/限额）只允许在 live/live_trader.py::submit_order 一处实现；broker/ 之外
# 禁止 import 券商 SDK，否则闸门会被新适配器绕过。
ORDER_PORT_CONFORMANCE = {
    "single_submit_port": "live/live_trader.py::submit_order",
    "brokers_dir": "broker",
    "adapter_scope": "primitive_only",
    "decision_layers": ["core/signal_gate.py", "core/risk.py", "live/reconciliation.py"],
    "forbid_sdk_import_outside_broker": True,
    "sdk_modules": ["xtquant", "ths_ptrade", "ctp", "openctp"],
    "signal_egress_point": "live_order_submit",
    "egress_points": ["live_order_submit", "watch_only_live_push"],  # v3.33 补：notifier的watch-only信号推送是第六出口
    "watch_only_push_requirements": ["warmup_ok", "fresh_data", "in_session"],  # 仅看盘推送也要过闸门：预热/时效/交易时段
    "audit_log": "live/audit_log.py",
    "mode_label_on_order": True,
    "forbid_direct_broker_place_order": True,
    "test": "tests/test_order_port.py",
}

# ==================== 运行模式（不要在这里改，用命令行参数控制） ====================
# 模式分层 backtest → paper → live：运行期只允许降级；提升（backtest→paper→live）
# 必须过 CLI_CONFORMANCE['promote_requires_checklist'] 门禁——上线检查清单存在
# 「不通过」项即拦下。任何试图绕过闸门/风控/时效的旁路开关都在
# CLI_CONFORMANCE['bypass_flag_blacklist'] 黑名单内，见 core/cli_gate.py 唯一实现。
RUN_MODE = "backtest"

# ==================== CLI 入口合规（第 11 步 11.0：一键入口是控制平面） ====================
# 事实源常量：main.py 子命令默认值、运行模式闸门、--data 导入出口全部引用本常量，
# 禁止在 argparse 里另写一份硬编码默认值导致口径漂移。
CLI_CONFORMANCE = {
    # 薄入口硬约束（第 11 步 I1）：main.py 只做解析/闸门/分发，业务进 cli_commands/
    "thin_entry": True,
    "max_entry_lines": 300,
    "command_modules_dir": "cli_commands",
    # 禁参校验模式：structural = 按「能力」审计（能否提升模式/关闭闸门），
    # 与参数名叫什么无关；字符串黑名单（bypass_flag_blacklist）只作第一道粗筛
    "forbidden_flags_check_mode": "structural",
    # 运行模式阶梯：backtest < paper < live（只允许降级）
    "run_mode_ladder": ["backtest", "paper", "live"],
    # 阶梯只允许降级（提升必须走 promote 双门禁，不存在任何「原地提升」旁路）
    "mode_may_only_downgrade": True,
    # 提升运行模式必须过策略上线检查清单（checklist 有「不通过」即拦）
    "promote_requires_checklist": True,
    # 提升运行模式除清单外还需显式确认（--confirm），二者缺一即拒
    "promote_requires_confirm": True,
    # 一键入口禁止任何绕过闸门/风控/时效的旁路开关
    "forbid_bypass_flags": True,
    # 旁路开关黑名单：出现在 argv 或 argparse 注册项中即违规
    "bypass_flag_blacklist": ["--no-gate", "--no-risk", "--no-fresh",
                              "--skip-check", "--ignore-stale", "--ignore-risk",
                              "--force-live", "--force-trade", "--bypass-gate",
                              "--force", "--skip-freshness", "--ignore-warmup",
                              "--disable-gate"],
    # 子命令默认值必须集中引用 config（默认值单一事实源，防止 argparse 硬编码第二份）
    "defaults_from_config": True,
    # 子命令默认值登记表（main.py build_parser 逐项引用；tests/test_entry.py 逐项核对）
    "cli_defaults": {
        "initial_cash": 1_000_000,     # 与 INITIAL_CASH 同源（回测/模拟盘初始资金）
        "start": "2020-01-01",          # 与 DEFAULT_START 同源
        "end": "",                       # 与 DEFAULT_END 同源（空 = 至今）
        "optimize_method": "grid",      # 参数优化默认方法
        "n_iter": 30,                   # 随机/遗传优化默认迭代数
        "top_n": 10,                    # 优化默认保留 Top 数
        "adjust": DEFAULT_ADJUST,       # 与 INDICATOR_CONFIG['default_adjust'] 同源
        "chart_period": "1d",           # K线图默认周期（SUPPORTED_PERIODS 之一）
        "export_format": "csv",         # 行情导出默认格式
        "report_type": "daily",         # 报告默认类型
    },
    # --data 本地数据导入必须走数据层出口（data/data_import.import_local_frame），
    # 禁止在 main.py 里裸 pd.read_csv 绕过校验
    "data_import_via_data_layer": True,
    # --data 导入帧必须带三物化列，缺列/NaN 直接拒绝（fail-closed）
    "data_import_requires_columns": ["warmup_ok", "data_asof_date", "price_adjust"],
    # --data 导入默认预热根数（与信号闸门最小样本门槛下界 60 同源）
    "data_import_warmup_bars": 60,
    # 结构化审计的豁免项：只有这条经 cli_gate.enter_mode 双门禁的路径允许写模式值
    "audited_mode_actions": [{"command": "set-mode", "dest": "to"}],
}

# ==================== 技术指标配置（第 3 步） ====================
INDICATOR_CONFIG = {
    "annual_trading_days": 244,
    "annual_trading_days_us": 252,
    "annual_factor_by_period": {
        "1d": 244, "1w": 52, "1M": 12,
        "1min": 244 * 240, "5min": 244 * 48, "15min": 244 * 16,
        "30min": 244 * 8, "60min": 244 * 4,
    },
    "default_adjust": DEFAULT_ADJUST,
    "risk_free_rate": 0.02,
    "volume_metrics_use": "volume",
    "keep_nan": True,
    "forbid_center": True,
    "evaluation_only": ["MAX_DRAWDOWN", "SHARPE_RATIO", "ANNUAL_RETURN", "VOLATILITY"],
    "nav_only_markets": ["cn_fund", "cn_reverse_repo", "private_fund", "qii_product"],
}

# ==================== 指标守卫加固（第 3 步修正） ====================
# adjust_column：复权口径物化为普通列（数据层出口写），指标入口优先读列而非易失 attrs；
# on_adjust_unknown：ATR/STD/HIST_VOL 无法确认口径时的处置，"require"=直接报错（禁止 fail-open）；
# warmup：各指标最小预热根数（下界，递归收敛慢的取 max），前 warmup-1 根必须为 NaN，回测/实盘须跳过；
# eval_prefix：评估类指标的物理隔离前缀（eval_max_drawdown 等），实时信号链在命名层面取不到；
# volume_all_zero_returns_empty：成交量全 0（净值型序列）时量能指标返回 NaN 并标注，禁止返回一串 0。
INDICATOR_HARDENING = {
    "adjust_column": "price_adjust",
    "on_adjust_unknown": "require",
    "warmup": {"MA": 20, "EMA": 20, "SMA": 20, "MACD": 35, "BOLL": 20, "RSI": 15, "KDJ": 9,
               "ROC": 13, "CCI": 14, "WILLR": 14, "VOL_MA": 10, "OBV": 1, "VR": 26,
               "ATR": 14, "STD": 20, "HIST_VOL": 21, "ADX": 28, "SAR": 5,
               "IV_RANK": 252, "IV_PERCENTILE": 252},
    "eval_prefix": "eval_",
    "volume_all_zero_returns_empty": True,
}

# ==================== 指标预热闸门（第 3 步 B1/B2/B5） ====================
# warmup_ok_column：指标/信号帧必须携带的物化布尔列（True=已过预热期），
#   信号入口强制读取；禁止只靠数值 NaN（fillna(0) 会把预热期伪装成"极度超卖"）。
# convergence_tol：required_bars 反推口径——初始条件扰动对输出的影响收敛到该相对误差所需根数；
# required_bars_method："burnin_compare"=长样本扰动对比反推（表值只作下界），"table"=退化为查表；
# forbid_fillna_before_warmup：预热掩码为 False 的行出现非 NaN 值（被 fillna/ffill/bfill/
#   rolling(min_periods=1) 填过）时，信号入口直接报错；
# live_reject_if_last_bar_in_warmup：paper/live 模式下末根 bar 仍在预热期（新上市/刚切周期）拒出信号。
INDICATOR_WARMUP_GUARD = {
    "warmup_ok_column": "warmup_ok",
    "convergence_tol": 1e-3,
    "required_bars_method": "burnin_compare",
    "forbid_fillna_before_warmup": True,
    "live_reject_if_last_bar_in_warmup": True,
}

# ==================== 期权估值守卫（第 3 步 B4） ====================
# iv_bounds：二分法搜索区间；无解（深虚值/T→0/市价低于内在价值）时按 on_no_solution
#   返回 NaN 并置 iv_solved=False，禁止返回二分区间下界冒充有效 IV。
# day_count_theta：THETA 按每 1 个自然日折算（年化 ÷ 365）；vega_per/rho_per 为 1 个百分点。
OPTION_VALUATION_GUARD = {
    "iv_solver": "bisection",
    "iv_bounds": [1e-4, 5.0],
    "iv_tol": 1e-6,
    "iv_max_iter": 200,
    "on_no_solution": "nan",
    "day_count_theta": 365,
    "vega_per": "1_pct",
    "rho_per": "1_pct",
    "risk_free_rate_ref": "INDICATOR_CONFIG['risk_free_rate']",
    "dividend_yield_default": 0.0,
}

# ==================== 引擎一致性 / 闸门归属（第 6 步开工前置 · C1–C4） ====================
# 闸门实现只允许存在一份，放在引擎无关的 core/signal_gate.py；执行器（core/runner.py、
# core/backtester.py）只调用、不重写。最终裁决收口在 core/account.py::place_order（与 stale
# 闸门同处），这样第 6 步替换执行器时闸门不会静默消失。
# min_backtest_bars：回测长度门槛 = max(60, strategy.required_bars())，禁止硬编码 60——
#   MACD 的 DEA 收敛约 70+ 根，固定 60 会让 60~70 根的标的通过检查后全段落在预热期，
#   闸门拦掉每一笔 → 回测静默零成交，易被误判成「策略没用」。
# preserve_columns_on_align：多标的对齐/取交集时这三个物化列必须逐标的保留（按 symbol 分组），
#   不得因 concat/reindex 退化成一列一个值或整列广播。
GATE_CONFORMANCE = {
    "gate_module": "core/signal_gate.py",
    "enforce_at": "place_order",
    "feed_warmup_ok_into": "bar_dict",
    "min_backtest_bars": "max(60, strategy.required_bars())",
    "preserve_columns_on_align": ["data_asof_date", "price_adjust", "warmup_ok"],
}

# ==================== 第7步开工前置：三引擎共享的成交/风控（D2–D4）====================
# 成交模型只有一份实现（core/execution.py），backtest/paper/live 只调用不重写；
# 三环境差异只允许参数化：slippage_multiplier 回测 1.0 / 模拟盘 2.0 / 实盘 2.0。
# 风控只有一份实现（core/risk.py），以 config.RISK 为唯一参数源。
# volume_limit_pct_by_market：单笔成交量上限按市场分档（None = 走净值/定价路径，不参与撮合量限）。
# bias_direction：已知简化对回测结果相对实盘的系统性偏差方向，用于偏差归因，禁止不标注。
EXECUTION_MODEL = {
    "module": "core/execution.py",
    "risk_module": "core/risk.py",
    "shared_by": ["backtest", "paper", "live"],
    "slippage_base_pct": 0.0005,
    "slippage_multiplier": {"backtest": 1.0, "paper": 2.0, "live": 2.0},
    "volume_limit_pct_by_market": {
        "cn_stock": 0.01, "cn_etf": 0.02, "cn_convertible": 0.005,
        "cn_future": 0.02, "cn_reits": 0.01, "us_stock": 0.01, "us_etf": 0.02,
        "hk_stock": 0.01, "crypto": 0.005, "forex": None,
        "cn_fund": None, "cn_reverse_repo": None,
        "private_fund": None, "qii_product": None,
    },
    "zdt_reject_on_open": True,
    "bias_direction": {
        "sell_slippage_at_open": "中性偏乐观",
        "zdt_open_only": "偏悲观（过度拒单）",
        "volume_limit_fixed": "修正后收敛（分档）",
        "nav_pass_through": "中性",
    },
    "known_simplifications": [
        "卖出滑点按开盘价统一计算",
        "涨跌停仅判开盘即封板，未模拟盘中反复开板",
        "量限按市场分档（原为固定 1%）",
        "基金/逆回购走净值透传，不参与撮合量限",
    ],
    # ---- E1：撮合价基准（三引擎与盯盘唯一参数源，禁止写死开盘/收盘价）----
    # 核心约束：成交所用 bar 必须严格晚于决策所用 bar。on_bar(t) 用 t 的收盘做决策，
    # 若按 t 的开盘/收盘成交 = 用未来信息在当下成交（系统性乐观）。
    #   next_open  ：t 决策 → t+1 开盘价成交（默认，lookahead-safe）
    #   next_close ：t 决策 → t+1 收盘价成交（lookahead-safe）
    #   same_open  ：t 决策 → t 开盘价成交（仅用于复现历史口径/对照实验，lookahead-unsafe）
    #   same_close ：t 决策 → t 收盘价成交（同上，lookahead-unsafe）
    "match_price_basis": "next_open",
    "match_price_basis_meta": {
        "next_open":  {"price": "open",  "bar_offset": 1, "lookahead_safe": True},
        "next_close": {"price": "close", "bar_offset": 1, "lookahead_safe": True},
        "same_open":  {"price": "open",  "bar_offset": 0, "lookahead_safe": False},
        "same_close": {"price": "close", "bar_offset": 0, "lookahead_safe": False},
    },
    # True：assert_fill_after_signal 强制「fill_index >= signal_index + bar_offset」，
    # same_* 基准同根成交直接抛 LookaheadError。
    "enforce_fill_after_signal": True,
}

# 三引擎一致性约束：backtest/paper/live 必须 import 同一份 signal_gate/execution/risk，
# 且每根 bar 必须带 warmup_ok / data_asof_date / price_adjust 三个物化列。
ENGINE_CONFORMANCE = {
    "engines": {"backtest": "core/backtester.py", "paper": "core/paper_trader.py",
                "live": "core/live_trader.py"},
    "must_share": ["core/signal_gate.py", "core/execution.py", "core/risk.py"],
    "must_feed_columns": ["warmup_ok", "data_asof_date", "price_adjust"],
    "consistency_test": "test_engine_consistency.py",
    "divergence_warn_pct": 0.05,
}

# 信号出口一致性：信号只能从以下六个出口离开系统（下单 / 盯盘推送 / 报告候选 /
# 对外披露 / 实盘报单 / 仅看盘推送），且都必须过同一份 core/signal_gate.py；盯盘推送还必须带三个物化列
# 并做时效/时段校验，对外披露还必须过 DISCLOSURE_CONFORMANCE，实盘报单必须走
# live/live_trader.py::submit_order 唯一收口（ORDER_PORT_CONFORMANCE）。
SIGNAL_EGRESS_CONFORMANCE = {
    "signal_egress_points": ["place_order", "monitor_push", "report_plan",
                             "investor_disclosure", "live_order_submit",
                             "watch_only_live_push"],
    "must_call_gate": "core/signal_gate.py",
    "monitor_must_inject_columns": ["warmup_ok", "data_asof_date", "price_adjust"],
    "forbid_bare_on_tick": True,
    "push_requires_fresh": True,
    "session_check_per_market": True,
    "push_must_tag_gated": True,
    # 10.5：盯盘提醒类型必须在出口清单登记，未登记的类型 notifier 拒发
    "alert_types": list(QI_MONITOR_ALERTS),
}

# 复盘报告一致性：报告是第三个输出口（report_plan），必须与引擎同源，
# 且必须披露被闸门拦掉的信号——否则「0 笔交易」会掩盖 fail-closed 锁死。
REPORT_CONFORMANCE = {
    "must_share_signal_source": True,
    "must_report_suppression": True,
    "suppression_reasons": ["warmup", "stale", "off_session",
                            "limit_up_down", "volume_limit", "risk_block"],
    "plan_is_signal_egress": True,
    "plan_requires_fresh": True,
    "plan_must_tag_gated": True,
    "metrics_must_share_source": True,
    "auto_send_requires_fresh": True,
    "zero_trade_disclosure": True,
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
        # v3.38：enforce_in_factor 语义收窄——仅当「解析指数成分股」时生效；
        # 显式代码列表不存在幸存者偏差，不得被本闸门拦截（防闸门自身变成干扰项）。
        "enforce_in_factor": True,           # 指数名解析路径禁止当前成分股；关掉即拒绝出因子
        "enforce_scope": {                        # v3.38：按「输入形态」分层，不按「是否调用 compute」
            "by_universe_kind": True,             # 判据看输入是代码列表还是指数名
            "explicit_symbols_requires_pit": False,  # 显式代码列表：无偏差可防，放行
            "index_name_requires_pit": True,        # 指数名：必须 as_of + 点内快照，缺即 raise
            "allow_implicit_all_a": False,          # None/隐式全A：拒绝（会静默引入偏差）
        },
        "forbid_current_constituents": True, # 回测禁止读「当前成分股」
        "on_unavailable": "raise",           # 拉不到就报错
        "teaching_mode": {
            "allow": True,                   # 仅教学/演示可放行
            "watermark_field": "survivorship_bias_uncontrolled",
            "require_watermark_in_report": True,
            "watermark_is_sticky": True,     # 水印随报告进归档库与 stats，不得被后续流程抹掉
        },
    },
}

# ==================== 股票池解析分层（第 13 步 · v3.38 新增） ====================
# 教训：把 PIT 闸门挂在「调用 compute」这个路径上，会把「防幸存者偏差」变成
# 「强制所有人走指数成分股」——显式代码列表根本没有那类偏差，拦它是误伤；
# 一旦有人为跑通而关掉闸门键，PIT 真实性一起被关，闸门就变成了它要防的东西。
# 判据必须落在 resolve_universe 内部、按输入形态分层（enforce_at）。
UNIVERSE_RESOLUTION_GUARD = {
    "explicit_list_is_not_survivorship_bias": True,  # 显式代码列表无偏差可防，永不拦
    "enforce_at": "resolve_universe",                # 判据位置：解析函数内部，不是 compute 入口
    "resolution_default": "deny",                     # 未识别的字符串一律拒绝，绝不当代码（反向白名单）
    "bare_code_is_stock": True,                       # 裸 000xxx 段个股优先；指数必须带后缀/前缀或中文名
    "exchange_segment_rule": "config.INDEX_PREFIX_RULES",  # 后缀+号段联合判定，只有真冲突才报错
    "stock_segment_rule": "config.STOCK_PREFIX_RULES",     # 000xxx 在 SZ 是个股段，不算冲突
    # 北交所号段（v3.43）：2025-10-09 起只有 920 段；43/83/87/88 已退出北交所，
    # 「.BJ + 旧段」是失效写法，必须按 as_of / 迁移表解析，查不到即 raise。
    "bse_segment_rule": {
        "stock_segments": ["920"],
        "legacy_stock_segments": ["43", "83", "87", "88"],
        "legacy_effective_until": "2025-10-09",
        "stale_suffix_must_raise": True,
    },
    "index_alias_single_source": "config.CN_INDEX",        # 别名从 CN_INDEX 派生，模块内不自定义
    "forbid_local_index_lists": True,
    "get_index_members_must_share_checker": True,     # 与 resolve_universe 共用 pit_index.classify_symbol
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
    "engines_must_call_gate": ["backtester", "paper_trader", "live_trader", "runner", "monitor", "notifier"],
    "egress_points_must_all_pass_gate": True,       # 逐个出口验证：place_order/monitor_push/
                                                    # report_plan/investor_disclosure/live_order_submit/watch_only_live_push
    "no_hardcoded_safety_value_outside_config": True,   # 阈值/上限/保留期不得硬编码在业务代码里
    "system_test": "tests/test_system_conformance.py",
    "test_must_be_table_driven": True,               # 按「出口 × 是否过闸门」逐格断言，不做整体冒烟
    "checklist_mode": "four_count",                  # 通过/失败/跳过/收集错误四类计数，缺一不可
    "report_must_map_tests_to_guards": True,         # 报告须给出「测项 → 守卫」映射，禁止只报总数
    "spec_authority_single_source": True,   # v3.46：规格正文单源发布（draft 不得冒绿，见 SPEC_PROVENANCE）
    "test_data_count_must_be_reported_raw": True,  # v3.46：test_data 必须报原始计数（固定 13 项不得报 12 组）
    "empty_reason_provenance_required": True,   # v3.47：empty_reason 只能来自证券主数据
    "suite_coverage_frozen_total_must_match": True,  # v3.47：套件数须与 SUITE_COVERAGE_GUARD 对账
    "script_hash_self_sync_forbidden": True,    # v3.47：施工方不得自行登记验收脚本哈希
    "final_acceptance": [
        "same_prewarm_frame_all_engines_reject",
        "stale_frame_all_engines_reject",
        "every_egress_point_rejects_when_gate_fails",
        "no_remaining_bypass_switch",
    ],
    # ---- v3.48 / 13.0.19：度量的层级升级（盒子→盒中物；上界→真上界；名字→上游）----
    "config_surface_structure_only": True,     # ⑦ 两机键集合核验：只比结构、不比取值
    "config_surface_two_machine_check": True,  # 两机各跑一次，差异键清单必须披露
    "per_suite_baseline_frozen": True,         # ① 逐套项数基线冻结，防「套件还在、断言删光」
    "count_unit_declared_in_report": True,     # ② 回执逐行带单位，pytest/脚本分栏
    # ---- v3.49 / 13.0.20：判据从「形容词」改为「白名单」----
    "surface_recurse_scope_is_whitelist": True,     # ① 递归集合逐名列出，不靠「guard 块」语义
    "baseline_anchored_to_historical_peak": True,   # ② 基线锚历史峰值，不锚当前值
    "ledger_covers_all_script_globs": True,         # ③ 账本覆盖 glob 全集，未登记即 fail
    "valid_mode_whitelist_enforced": True,          # ④ 查矩阵前先验封闭模式白名单
}

