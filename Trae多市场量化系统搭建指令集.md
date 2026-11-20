# Trae 全市场量化交易系统搭建指令集

<!-- spec_version: v3.53 -->

> **版本 v3.51** · 19 类可交易/可研究市场 + 指数（基准/择时）全覆盖 · 全链路：行情 → K线/缠论 → 指标 → 策略 → 因子研究（Alpha101/191/自定义）→ 回测 → 模拟盘 → 实盘接入（A股/国内期货）→ 复盘 → 数据与报告长期可用
>
> ⚠️ **实现前版本自检（v3.26 新增·v3.33 升级为机器校验·硬要求）**：
> - 动手实现任一步骤的「开工前置」前，**必须先核对本文件顶部版本号**，并确认目标步骤的标题内容与任务书引用一致（例：第 7 步须是 `## ===== 第 7 步：模拟盘交易 =====`）。引用行号与标题对不上、或任务书语句与本文件不一致，一律先停下核对版本、再动手；对着**旧版**自查得到的「逐条核对 ✅」**不作为交付依据**。（注：本文件行号会随版本编辑漂移，**一律以章节标题定位，不引用绝对行号**。）
> - **v3.33 升级**：`config.py` 顶部新增 `SPEC_VERSION` 常量（与本文件版本号完全一致）；启动 / `check-config` 时由加载器读取并与指令集顶部版本头比对，**版本不一致时 fail-closed（`raise RuntimeError`），不允许运行**；这是为了终结「两份规格副本长期不同步、实现照新规格跑、自检照旧版本读」的根因（v3.32 实测：本地指令集标注 v3.3 但代码已含 v3.22+ 内容 = 人肉自检静默失效）。
>
> v3.51 更新：**13.1 回补第六战——「判据可复现了，但『比对基准』没钉死：拿两个不同版本的集合相减，差异不可定性」**——① ✅ 核对：Trae v3.50 落盘六项（`compute_config_surface` 改 cs-v1、黄金向量自证通过、`suite_baselines` 恢复峰值 10/58/20、ledger 46/46 全覆盖 + 旧表迁移、`cli_gate.validate_mode` 白名单先验、`suite_guard` AST 上界、`test_data` 双报），pytest **464/0/0/0**，20 套逐套件齐——方向正确；但有三处「判据钉死了，比对与判据本身却还差一步」：**跨版本比对**（拿本机 v3.49 的 515 键去比沙箱 v3.50 的 586 键）、**白名单「完备但不纯」**（`whitelist_exclusions={}` 未落规则，`UNIVERSE_RESOLUTION_GUARD` 的 12 个股票代码键混进治理面）、**期望计数被当成判据**（`surface_expected_counts` 手填数字直接决定 `--check` 通过与否）。② 🔴 **发现（跨版本比对 = 拿两面颜色不同的墙相减 · 本轮确立）**：沙箱实算 `config.py.v349.bak`（同版本对照物）得 **162 常量 / 541 去重键 / 703 元素**，v3.50 得 **162 / 586 / 748**——**常量零差、v3.50 只增键不删键**；故本机「少 71 键」的真身是 **45（v3.50 合法新增）+ 26（真实结构差）**，与「版本差」混在一起，定不出是哪一个。确立 `compare_requires_same_spec_version` + `compare_requires_same_algo_id` + `compare_requires_same_whitelist` + `cross_version_compare_action="refuse"` + `compare_baseline_dump_per_version_required`。③ 🔴 **发现（白名单「完备」但「不纯」· 本轮确立）**：12 个股票代码键（分挂 `segment_decision_examples` / `known_ambiguous_symbols`）被递归进治理面哈希——**往示例表加一个代码，就改动「治理结构哈希」**。确立 `whitelist_exclusions` 落 `exclude_key_pattern`（剔代码键、保结构键名）+ `business_key_pattern_excluded` + `exclusion_must_cite_reason`。④ 🔴 **发现（期望计数被当成判据 · 本轮确立）**：`surface_expected_counts` 是手填数字，`--check` 用它决定 exit code——**结果是产物，却被当成门槛**，config 一合法增键就红，红得毫无信息量。确立 `frozen_counts_are_outputs_not_criteria=True` + `expected_counts_mismatch_action="warn_not_fail"`（`--check` 只对黄金向量 exit 1）。⑤ 🔴 **发现（黄金向量未覆盖「去重」路径 · 本轮确立）**：原向量 `consts=["GOLDEN","Z"]` 与 block 键 `{b,A,L}` **无交集** → S3 的合并去重从未被执行。确立：`consts` 改为 `["A","GOLDEN","Z"]`（"A" 与 block 内键重名 → 强制走去重；元素/哈希不变但去重被覆盖）+ `golden_vector_must_cover` 六项 + `non_dict_block_action="raise"`。⑥ 🔴 **发现（回退声明靠日志字符串被测试嗅到 · 本轮确立）**：`test_data` 抓出的真实缺口（实时源全灭 + 本地有库 → 当日空缺无声明）靠**读日志文本**发现，不是靠**返回结构里的显式字段**。确立 `local_fallback_must_declare_today_missing` + `missing_today_must_be_structured_field` + `today_missing_field="today_missing_declared"`。⑦ 🔴 **发现（「硬要求 N 条」标签与实际条目数长期不符 · 本轮确立）**：正文标签写「19 条」，而 13.0.1~13.0.22 实为 **22 条**（13.0.19 之后的新增从未回填标签）。**计数标签自身漂移 = 该口径没人执行。** 本轮校准为 22。⑧ **确立（v3.51）**：13.0 硬要求由 **21 条扩为 22 条**（新增 **13.0.22 比对基准先钉版本 / 白名单纯净性 / 期望计数是产物不是判据**）。

> v3.50 更新：**13.1 回补第五战——「v3.49 把判据的输入集合钉成了白名单，但『集合怎么变成哈希』那一步没钉死：期望值不可复现」**——① ✅ 核对：Trae v3.49 落盘六项（`surface_recurse_blocks` 30 块白名单 + 缺块 raise、`suite_baselines.json` 全字段改 `historical_peak` 并恢复 10/58/20 + recovery_plan、`acceptance_scripts.ledger.jsonl` 46 条全覆盖 + 旧表以 `action:"add"` 迁移、`cli_gate.validate_mode` 先验白名单 + `run_live.py` 解析 `--mode` 后即校验、`suite_guard` 上界只认 AST 字面量、`test_data` 双报 + 运行期一致性断言），pytest **461/0/0/0**，20 套逐套件齐、surface / 账本 / baselines 三件治理产物齐——方向正确；但存在五处「判据钉死了，却不可复现 / 或期望值是人手填的」：**登记哈希 `d7df508d…` 用七种自然读法都算不出来**、期望元素数与峰值由人手填、常量集用 `dir()` 采集（跨机不稳）、白名单无完备性校验（漏纳 / 误纳）、账本「只追加」无机械强制 + 迁移可能重拍快照。② 🔴 **发现（元素数可复现、哈希不可复现 · 本轮确立）**：`sorted(set(常量)∪set(键))` 的**并集**能算出 755，但**它的 sha256 不是 `d7df508d…`**——「哪些元素进集合」定了、「集合怎么变成哈希」没定，**连看守者自己都复现不出登记值**。确立 `surface_algo_id="cs-v1"` + `surface_algo_steps`（S1~S5）+ `surface_golden_vector`（固定输入 → `72bc8831…`）+ `golden_vector_must_match_action="raise"` + `surface_dump_file`。③ 🔴 **发现（期望值是手填的、无证据 · 本轮确立）**：峰值与期望计数都是人写下的数字。确立 `historical_peak_must_cite_evidence` + `peak_evidence_schema` + `peak_from_declaration_action="raise"` + `hand_typed_expected_forbidden`。④ 🔴 **发现（常量集用运行期命名空间采集 · 本轮确立）**：`dir()` 会把 `import` 进来的大写名算作顶层常量 → 同配置两种写法两个哈希。确立 `surface_collection_must_be_ast_based` + `dir_based_collection_forbidden`。⑤ 🔴 **发现（白名单自身无完备性校验 · 本轮确立）**：漏纳新 guard 块 → 该块整体不进 surface；误纳业务块 → 业务数据（实测 `UNIVERSE_RESOLUTION_GUARD` 键集含 12 个股票代码键）污染治理面。确立 `whitelist_completeness_required` + `guard_block_name_pattern` + `whitelist_exclusions` + `unlisted_guard_block_action="raise"`。⑥ 🔴 **发现（只追加无机械强制 / 迁移可洗白 · 本轮确立）**：账本「只追加」只是政策，改 / 插 / 删都不会报错；迁移若重算当前哈希 = 洗白。确立 `ledger_hash_chain_required`（链式哈希）+ `chain_break_action="raise"` + `migration_must_verify_old_hash_first` + `rehash_on_migrate_forbidden`。⑦ **确立（v3.50）**：13.0 硬要求由 **20 条扩为 21 条**（新增 **13.0.21 判据可复现：机械算法 + 黄金向量 / 期望值溯源 / AST 采集 / 白名单完备性 / 账本链 / 迁移先验旧哈希**）。

> v3.49 更新：**13.0 回补第十二战——「v3.48 七处口径钉死后，四处『看起来钉死了、但判据本身还没钉死』」**——① ✅ 核对：Trae v3.48 落盘七处（`SUITE_COVERAGE_GUARD` 17 键 / `NONDETERMINISTIC_SCRIPT_GUARD` +AST/边界 / `EMPTY_REASON_PROVENANCE` 独立性 / `SPEC_DRAFT_PERMISSION` 默认拒绝 +矩阵 / `ACCEPTANCE_GOVERNANCE` 追加式账本 / `CONFIG_SURFACE` 跨机哈希），pytest **452/0/0/0**，四类计数 20 套全齐、test_data 双报 34/34、账本与 baselines 建立——方向正确；但存在四处「判据的定义本身是形容词、不是白名单」：surface 算法未给递归白名单（两机哈希不同正是因此）、基线锚在当前值（让已经发生的瘦身合法化）、账本只登记 2 条（其余脚本无人守）、`unknown_mode_action=raise` 靠字典 miss 碰巧拦住。② 🔴 **发现（surface 算法没给白名单 · 本轮确立）**：`surface_scope` 写「每个 guard 块」但**没列清单**——沙箱递归全部字典、本机只递归治理块，算法口径不同 → 哈希永远不一致。确立 `surface_recurse_blocks` 白名单 + `recurse_blocks_exhaustive` + `missing_recurse_block_action`。③ 🔴 **发现（基线锚「当前值」= 让历史瘦身合法化 · 本轮确立）**：v3.48 基线 49/32/19/34/… 锚的是**瘦身之后**的值，alpha101（10→2）/factor（58→6）/loader（20→4）的瘦身已被「合法化」。确立 `baseline_must_anchor_historical_peak=True` + `baseline_initial_peaks`（v3.40 稳定态核定：10/58/20）+ `silent_ratchet_down_forbidden`。④ 🔴 **发现（账本只登记 2 条 = 其余 20+ 脚本无人守 · 本轮确立）**：回执 `acceptance_scripts.ledger.jsonl` 只有 meta+2 register，但 `script_globs` 匹配 20+ 套验收脚本；「登记一个文件 = 守一个文件」，未登记脚本的删改**永远不会被发现**。确立 `ledger_must_cover_all_script_globs=True` + `unregistered_script_action="raise"` + `legacy_manifest_migration_required`。⑤ 🔴 **发现（`unknown_mode_action=raise` 靠字典 miss 碰巧拦住 · 本轮确立）**：矩阵未定义「合法模式全集」，CLI 传任意字符串能否被 raise 完全依赖「字典查不到」——若代码里某处写 `.get(mode, "warn")` 兜底，就会 fail-open。确立 `valid_mode_set_required=True` + `valid_modes` 枚举 + `invalid_mode_action="raise"`（矩阵查询**之前**先验）+ `cli_mode_argument_validated`。⑥ **确立（v3.49）**：13.0 硬要求由 19 条扩为 **20 条**（新增 **13.0.20 算法白名单/基线锚峰值/账本全覆盖/模式集合封闭**）。


> v3.42 更新：**13.0 回补第五战·补丁——「别名单源立了却没接进主链路」+「自家交付物哈希口径未定死」**——① ✅ 核对：Trae v3.41 落盘 `CN_INDEX_ALIASES`（48 条）、`STOCK_PREFIX_RULES`、`INDEX_PREFIX_RULES` 增 BJ 段、`get_index_members_must_call_classify_first`，方向正确。② 🔴 **发现（v3.41 的 `detect_market_type()` 没消费 `CN_INDEX_ALIASES` · 本轮修正）**：汉字与字母都满足 `str.isalpha()`，`沪深300` / `hs300` / `北证50` 一路落进「字母+数字 = `cn_future`」贪心分支 → 被判成国内期货、取新浪主力连续数据（静默错误数据）；**别名单源定义了但主干判定链不用它 = 第五份清单换了个位置继续漂移**。修正：`detect_market_type()` 在 `upper()` 之前插入「`code.lower().replace(" ","") in CN_INDEX_ALIASES` → `cn_index`」，别名归一化置于**所有分支之前**。③ 🔴 **发现（我方交付物 `spec_content.sha256` 与正文不符 · 本轮修正）**：登记值 `a5f048…` ≠ 正文实际哈希，任何机器上 `verify_content_hash` 都判不通过——**闸门自己的输入是坏的**。修正：把 `hash_scope="instruction_doc_body"` 的实现口径**定死为「整文件 UTF-8 字节（LF 行尾、含 version 头行）的 sha256」**，**禁止按行过滤**（行过滤会引入 CRLF / 末尾换行 / BOM 的跨机器差异），并据此重算登记值。④ **确立**：13.0 硬要求 **12 条**（13.0.12 含「别名必须被 `detect_market_type` 消费」与「accessor 入口第一行过 checker」）。⑤ **遗留**：投递通道仍未打通，`check-config` 在本地仍「正确失败」。
>
> v3.41 更新：**13.0 回补第五战——「北交所 .BJ 被全链路当期货静默错判」+「别名单源未定义 = 派生无据」+「get_index_members 入口没先过 checker」**——① ✅ 核对：Trae v3.40 把段位判据由「矛盾即拒」改为「后缀 + 段位联合判定」方向正确；实测 `000001.SH`/`000300.SH`/`sh000300`/`000001.SZ`/`600519.SH` 判定一致；删除了模块内 `_INDEX_ALIASES`/`_INDEX_CODES`/`_STATIC`/`_ak_index`，`factor/universe.py` 第五份清单已清；pytest **356 / 0 / 0 / 0** + 脚本 **20 套 615 项（根目录 9 套 377 + tests 11 套 238）**。② 🔴 **发现（北交所.BJ / bjxxx 全链路被当 cn_future 静默错判 · 本轮修正）**：v3.40 的 `detect_market_type()` 先判「字母+数字混合 = cn_future」，**后判 sh/sz 前缀**；而 `.BJ`（Tushare/Wind/聚宽/AkShare 标准写法，如 `899050.BJ` 北证50、`830799.BJ` 北交所个股）含字母 B/J + 点号 + 数字 → 先命中「期货」分支、返回新浪期货主力连续数据（静默错误数据）；同构地 `bj899050`（小写前缀写法）因前缀判断只认 SH/SZ、不认 BJ → 也进期货分支；北交所涨跌幅 30%、100 股起、T+1 规则与沪/深/期货皆不同，错判会让信号闸门、撮合、风控全部跑在错误规则上。③ 🔴 **发现（CN_INDEX_ALIASES 在注释里被引用、常量未定义 · 本轮修正）**：v3.40 的 `index_alias_single_source` 注释写「CN_INDEX + 新增 CN_INDEX_ALIASES」，但 config.py **根本没有** `CN_INDEX_ALIASES` 常量；`index_aliases()` 若按该注释「从 config 派生」，要么 KeyError、要么模块内另起一份（= 第五份清单回归）→ 别名单源【实际上没立起来】。④ 🔴 **发现（get_index_members 入口没要求「函数第一行必须调 classify_symbol」·本轮修正）**：v3.40 只说「共用同一份 checker」，但未约束 checker 的调用位置；若 `classify_symbol` 只放在「缓存未命中 → 调远端 API」分支里，**直调 `get_index_members("600519.SH")` 在缓存命中/降级路径上仍会绕过检查**，返回把个股当指数成分股解析的结果（fail-open 的典型位置：「缓存路径免校验」）。⑤ **确立（v3.41）**：`INDEX_PREFIX_RULES` 增 BJ 段 `("899",)`（北证系列指数）；`MARKET_CODE_RULES.cn_index` 补 `prefixed_bj/dotted_*`、增 `accepted_dot_suffixes=["SH","SZ","BJ"]`、补 `bj_stock` 段位；新增顶层常量 **`CN_INDEX_ALIASES`**（中文/大小写/英文/带前缀别名统一来源，查表前 `lower_strip` 归一化）；`detect_market_type()` **把「点后缀写法（600519.SH/.SZ/.BJ）」判定提到所有分支之前**，并把 8 位小写前缀判定扩到 `SH/SZ/BJ`（bjxxx 识别）；`UNIVERSE_RESOLUTION_GUARD.code_shape_rule.exchange_segment_rule` 的 SH/SZ/BJ 段位补全为**完整三段前缀**（SH 600/601/603/605/688/689；SZ 000/001/002/003/300/301；BJ 430/830-839/870-873/920）；`index_alias_single_source` 改为精确常量名 `"config.CN_INDEX_ALIASES"`；新增 **`get_index_members_must_call_classify_first=True`** + **`classify_symbol_is_single_source=True`**（`get_index_members` 函数入口第一行必须调 `classify_symbol(symbol)`，缓存/降级/异常各路径都在其后，禁止只在 API 分支里调）。⑥ **确立**：13.0 硬要求由 11 条扩为 **12 条**（新增 13.0.12 北交所段位识别 + 别名常量落地 + **别名必须被 `detect_market_type` 消费（否则中文/英文别名落入 `cn_future`）** + accessor 入口第一行过 checker）。⑦ **遗留**：本地规格仍是 `…-2.md` v3.3、`check-config` 仍「正确失败」；**投递通道**仍未完全打通，本轮增量以可复制代码块在正文中直接给出。
>
> v3.39 更新：**13.0 回补第三战——「闸门触发条件依赖『能识别的名字清单』= fail-open」+「同名字符串既是指数又是个股」**——① ✅ 核对：Trae **删掉了 `factor_engine.compute` 入口的无条件 `assert_pit_enabled("factor")`**（这是 v3.38 的病根：把无幸存者偏差的显式代码列表也拦了），改由 `factor/universe.py::resolve_universe` **按输入形态分层**；两条判据现场复现——`compute(['600519'])` 显式列表 `blocked_by_pit=False` 放行、`compute('hs300')` 指数名 `blocked_by_pit=True` 走 PIT；回归 `pytest 331 / 0 / 0 / 0` + 脚本 615；并**首次给出两集合交集说明**（pytest 只收集 `tests/`，文件级交集 11 个带 `__main__` 的套件、断言级重叠仅 12 条）；② 🔴 **发现（判据是 fail-open · 本轮修正）**：`resolve_universe` 的实现是「字符串 ∈ `_INDEX_CODES` 白名单 → 走 PIT；**否则 → 当代码放行**」——**未命中的字符串一律静默当代码**：别名「沪深300」、大写「HS300」、带前缀「000300.SH」、拼写错误，**既不报错、也不过 PIT**；闸门的触发条件依赖一个**「能识别的名字清单」**，清单漏项即**静默绕过**（与「信号出口清单」「标的池入口清单」**枚举不完**同族）；③ 🔴 **发现（同名字符串既是指数又是个股 · 本轮修正）**：`000001` **同时**是上证指数（`000001.SH`）与平安银行（`000001.SZ`）——裸数字代码**天然有歧义**，白名单命中与否决定它是「指数」还是「个股」，而这是**猜**（与「`_daily_` vs `_daily_none`」「raw vs qfq 同名同格式」同族）；④ **确立（v3.39）**：`UNIVERSE_RESOLUTION_GUARD` 增 **`resolution_default="deny"`**（**默认拒绝，能被判定为「代码」才放行**，翻转 fail-open）、`unrecognized_token_is_not_code=True`、`code_shape_rule`（**要求带交易所前缀** `600519.SH`/`sz000001`；裸 6 位数字必须与指数注册表比对，**命中即非代码**，冲突则**要求带前缀、拒绝猜**）、`index_registry_source`（`CN_INDEX`/`CN_INDEX_BARE_CODES`/`INDEX_PREFIX_RULES` **单一来源**）、`known_ambiguous_symbols`（实测同名清单）；`SNAPSHOT_PIT_GUARD.pit.enforce_scope.unknown_token="pit_or_raise"`；⑤ **确立**：13.0 硬要求由 7 条扩为 **9 条**（新增 13.0.8 按输入形态分层、13.0.9 默认拒绝 + 歧义显式）；⑥ **遗留**：本地规格仍是 `…-2.md` v3.3、`check-config` 仍「正确失败」，**投递通道**仍是最大风险（本轮盘上文件已**真正落盘**，不再只是「说了」）。
>
> v3.38 更新：**13.0 回补第三战之前置——「闸门装成一个『无条件拦截』，把没病的输入也拦了」**——① 🔴 **发现（v3.37 的收口方式是「过度拦截」·本轮修正）**：修完 `factor/universe.py` 绕过之后，闸门一度被写成 `factor_engine.compute` 入口**无条件** `assert_pit_enabled("factor")`，连显式传 `["600519","000001"]` 也拦；但显式代码列表**没有 index、没有成分股、没有幸存者偏差**，属误伤——① 用户传明确标的做研究被挡；② 既有直接调 `compute` 的单测被迫处处 login 式设 `enforce_in_factor=True`（脆弱耦合）；③ 一旦有人为跑通而**关掉该键**，PIT 的真实性**一起被关掉**——**闸门变成了它要防的东西**；② **确立（v3.38）**：PIT 闸门**按输入形态分层**（变量是「是否解析了指数成分股」，不是「是否经过 compute」）——`SNAPSHOT_PIT_GUARD.pit.enforce_scope`：`explicit_code_list_requires_pit=False`、`index_token_requires_pit=True`、`allow_implicit_all_a=False`；判据落在 `resolve_universe` **函数内部**（看输入是代码列表还是指数名），不放在 `compute` 入口。
>
> v3.37 更新：**13.0 回补第二战——「标的池有第六个入口」：闸门装在某一个调用点，而非数据获取的唯一出口**——① ✅ 核对：Trae 逐条回执 **PIT 收口五引擎 grep**（`backtester` L271 唯一入口且 `assert_pit_enabled` 在其前；`runner`/`paper_trader`/`live_trader`/`monitor` 均无旁路）、**补标记判定口径**（`infer_basis_from_path` 按目录 + 文件名周期段判定，判不出进 `unresolved` **不写默认值**；`_daily_none`/`_daily_` → `raw` 是**显式别名表**而非缺标记兜底）、**边车与 parquet 冲突 raise**（`PriceBasisMismatchError`）、**逐套件计数补齐 20 套**（pytest 322 + 脚本 615，0 失败/0 跳过/0 收集错误）；② 🔴 **发现（「标的池」有第六个入口 · 本轮新增 13.0.7）**：Trae 自己发现 `factor/universe.py` 仍用 `index_stock_cons*` 拉**当前**成分股、失败回退**内置静态清单且从不抛错**——它不是五个执行器，但**研究/因子链路**拿它当标的池，PIT 闸门等于没装；**更深的坑**：它污染的是**因子值本身**，「回测 universe 干净」只是表象，**因子是用未来成分股算的** → 幸存者偏差从第二道门进来；**规律**：守卫装在**某个调用点**（`backtester.prepare`）而非**数据获取唯一出口**，就必然随「入口扩散」漏装（「单引擎守卫」在数据层的复制）；③ **确立（v3.37）**：新增 `UNIVERSE_RESOLUTION_GUARD`——标的池**唯一出口** `data/pit_index.py::get_index_members`、`date` 必填（无日期 → `raise`，「当前成分股」语义在回测/研究上下文**不可表达**）、`index_stock_cons*` 仅允许在 `source_adapter` 原始层且必须被 `pit_index` 包装、**静态清单回退全面禁止**、旧便捷函数 `get_hs300/...` 降级为**必填 `date` 的薄封装**、`enforce_at="call_time"`（运行期收口，**不靠一次性 grep**）；`SNAPSHOT_PIT_GUARD.pit` 增 `factor_pool_must_use_pit`；`SYSTEM_CONFORMANCE` 增 `universe_egress_points`（含 `factor/universe`/`research`/`nav_backtest`）；④ **确立**：13.0 硬要求由 6 条扩为 **7 条**（新增 13.0.7）；13.0.6 的「五引擎」更正为「**所有标的池入口**」；⑤ **流程**：`pytest 322` 与脚本 615 存在**同一批 `tests/` 套件被两处计数**的重叠风险，须给出两集合交集说明；⑥ **遗留**：本地规格仍是 `…-2.md` v3.3、`check-config` 仍「正确失败」，投递通道仍是当前最大风险。

> v3.36 更新：**13.0 回补首战——「守卫装进了一个引擎，另外四个没装」+「口径标记自己变成第三份会漂移的副本」**——① ✅ 核对：Trae **首次把守卫装进引擎入口**（`core/backtester.py::prepare()` 强制 PIT 闸门），两条验收判据**现场复现**——半 raw 半 qfq 目录 → `MissingPriceBasisError`（`legacy_qfq_cache=forbid_read`），关 PIT → `PITUnavailableError`；`_read_cache` 不再把 `PriceBasisError` 吞成「无缓存」（fail-closed 正向）；回归 `pytest 321 / 0 / 0 / 0`；② 🔴 **发现（闸门只装了一条引擎 → 本会话「单引擎守卫」第 8 次复发）**：回补清单明列 `core/backtester.py / runner.py / paper_trader.py` 三个引擎入口都要装，本轮只改了 `backtester`；`assert_pit_enabled` 若收口在某个引擎入口 = 新引擎（或直读 `constituents/`）可绕过 → 确立 `PIT.guard_at="accessor"`：闸门必须收口在 `data/pit_index.py::get_index_members`（引擎无关），并 `forbid_direct_constituents_read`；③ 🔴 **发现（口径标记变成第三份会漂移的副本）**：口径现在有**三个载体**——parquet 元数据、边车 `.basis.json`、文件名后缀——**三者各自会失灵**，不给「唯一权威 + 冲突裁决」就与「raw/qfq 同名同格式」是同一个病换层皮 → 确立 `basis_authority="parquet_metadata"`、`filename_basis_is_hint_only`、`sidecar.role="bridge_only"` 且 `may_override_parquet=False`、`on_conflict_with_parquet="raise"`、`on_multi_basis_same_symbol="raise"`；④ 🔴 **发现（补标记工具「缺标记=raw」的默认归一 = 高危）**：给存量文件补标记时若把「无标记」一律归 `raw`，其中**含 qfq 内容的文件会被标成 raw → 复权两次 → 静默错价**（与 13.0.2 要根治的病完全一样）→ 确立 `stamp_legacy.method="filename_and_source_semantics"`、`on_ambiguous="quarantine"`（判不出即隔离，**绝不默认标 raw**）；⑤ 🔴 **发现（PIT 的「时点正确」建立在可变缓存上）**：`data_cache/constituents/{index}.parquet` 是会被**重建**的缓存，一旦用修订后的成分股重建，**过去跑过的回测结论会静默改变** → 确立 `constituents_must_be_snapshotted=True` + `constituents_immutable_per_as_of=True`；⑥ 🔴 **发现（四类计数口径中途漂移 → 跨轮不可比）**：脚本式计数由 `583 / 20 套` 变为 `377 / 9 套`（11 套无说明），总数由 888 变 698，**同一指标两种口径**——「全部通过」因此**不可比** → 确立 `SYSTEM_CONFORMANCE.count_definition_stable=True` + `per_suite_breakdown_required=True`（逐套件给通过数，口径变更须显式声明）；⑦ **确立（v3.36）**：13.0 硬要求由 4 条扩为 **6 条**（新增 13.0.5 口径唯一权威、13.0.6 PIT 收口 + 成分股快照）；13.5「打印警告不中断」更正为**默认 fail-closed**、教学模式放行须打粘性水印；⑧ **遗留**：本地规格仍是 `…-2.md` v3.3、无版本头，`check-config` 仍「正确失败」；v3.34 起的对齐件**多轮未落到本机**——投递通道本身是当前最大风险，须优先解决。
>
> v3.35 更新：**规格自校验闸门（check-config）落地 + 「装在开发期、不装在运行期」裁决**——① ✅ 核对：Trae 已实现 `core/spec_check.py`（glob 找 `*指令集*.md` → 解析 `<!-- spec_version:` 头 → 与 `config.SPEC_VERSION` 比对）、`cli_commands/check_config.py`（exit 0 / 2）、`main.py` 注册、8 项 `test_spec_check.py`，`SPEC_VERSION_CHECK` **第一次有了真实消费者与测试**（此前是死常量）；实测为**「当前正确失败」**（本地规格无版本头 → `[不通过]` exit 2），且 glob 能命中 `…-2.md`；回归 `882 通过 / 0 失败 / 0 跳过 / 0 收集错误`；② 🔴 **发现（装错位置会自锁·本轮修正）**：`enforce_on_startup` 若接进 `main()` 首行对**所有**模式 `raise`，则 stale spec 一旦存在，连 `check-config`（修它的命令）、`report show`、`backtest` 都跑不起来——**闸门锁死了修复它自己的工具**；Trae 未贸然接入是**正确判断**；③ **确立（v3.35）**：`SPEC_VERSION_CHECK` 由「单一 `on_mismatch=raise`」改为**分模式闸门**——`live`/`paper` `raise`（钱路径 fail-closed）、`backtest`/`research` `warn_and_watermark`（放行但报告 meta 打**粘性水印** `spec_version_mismatch`）、`tooling`（含 `check-config` 自身）`warn_only` **永不失败**；新增 `self_lockout_guard`（诊断 / 修复命令永不因版本不符而失败）；④ 🔴 **发现（版本号是字符串 = fail-open）**：只比对 `SPEC_VERSION` 字符串可被手改 / 遗忘 / 「另存为」带走——Trae 本地「config 写 v3.33、指令集是 v3.3、代码却已实现到 v3.22+」正是铁证；⑤ **确立**：新增 `must_contain_markers`（校验规格正文存在 `13.0 开工前置` / `13.13 收尾总检` 锚点），**版本号 + 内容锚点**双重校验，杜绝「改字符串骗过闸门」；⑥ **新增 13.14**「规格自校验闸门：装在开发期，不装在运行期」；⑦ **遗留**：本地规格仍是 `…-2.md` v3.3 / 2010 行，须先注入版本头 + 补 13.0 / 13.13 / 13.14 再开工第 13 步。
>
> v3.34 更新：**第 13 步开工——「规格自身的自洽性缺陷：版本头不存在、出口数对不上」**——① ✅ 核对：Trae 已完成 v3.33 副本合并（`SPEC_VERSION` 落盘、4 处默认复权改引用 `DEFAULT_ADJUST`、验证命令输出与预期一致）、补全 watch-only 第 6 出口闸门（`run_live._WatchOnly._gate` 逐项校验 `warmup_ok` / `fresh_data` / `in_session`，4 个新用例）、回归恢复四类计数（`874 通过 / 0 失败 / 0 跳过 / 0 收集错误`），工程判断正确；② 🔴 **发现（规格自身缺陷·本轮修正）**：`SPEC_VERSION_CHECK['command_file']` 指向 `Trae多市场量化系统搭建指令集.md`，而实际副本是 `…-2.md`、且**本文件此前根本没有 `<!-- spec_version:` 头** → 自校验一启用**必然 `raise`**，把「防副本不同步」的守卫变成故障源（守卫的输入不存在）；③ 🔴 **发现（规格自身缺陷·本轮修正）**：13.13 收尾总检正文仍写「**五出口** / **五个引擎**」，而实盘 watch-only 推送已是 **第 6 个信号出口** —— 正文与 config **出口数对不上**，照 13.13 施工会**漏验第 6 出口**（正是「闸门随出口扩散而漏装」的第 7 次复制的温床）；④ **确立（v3.34）**：指令集顶部**新增机器可读版本头 `<!-- spec_version: v3.34 -->`**；`SPEC_VERSION_CHECK` 改为 **glob 多候选**（`*指令集*.md`）+ `on_file_not_found=raise_with_guidance`，彻底把「文件名会漂移」这一易失载体从校验链里摘掉；`SIGNAL_EGRESS_CONFORMANCE` / `ORDER_PORT_CONFORMANCE` 双双补齐 `watch_only_live_push` 与 `watch_only_push_requirements`；13.13 全文由「五出口」更正为「**六出口 × 表驱动**」；⑤ **遗留裁决**：`strategies/futures_trend_following.py:41` 写死 `"adjust":"qfq"` **必须改**为 `DEFAULT_ADJUST` —— 长期研究默认 `hfq` 的意义就在于区间收益可加、跨除权日不跳变；策略级另选口径 = 回测结论与默认口径**不可比**；若确需 `qfq`，必须走**显式命名参数**并在报告 meta 留下口径标记；⑥ **流程**：采纳「测项 → 守卫」映射下沉到**断言级**，第 13 步 `tests/test_system_conformance.py` 须由脚本从测试收集**自动生成**映射，禁止手写。
>
> v3.33 更新：**副本对齐与版本自校验——「规格本身也是一个副本」**——① 🔴 **发现：v3.32 的指令集与 config.py 虽然已交付，但用户侧工作目录从未真正拿到**（用户本地指令集停在 v3.3 / 2010 行、config.py 仍 1742 行无 v3.32 新块）；前 12 轮的版本号自检是**人肉读版本头**，当副本落后但代码偷偷引用新版常量时，自检完全无法发现（v3.3→v3.32 跨越 29 个版本、662 行新增）；这与第 2 步「提醒 ≠ 拦截」、第 12 步「风险提示只是打印」同族——**提醒机制一旦由人执行，就会静默失效**；② **确立**：`config.py` 顶部增 `SPEC_VERSION = "v3.33"`，指令集与 config.py 版本号**机器断言绑定**；本轮不升第 13 步 spec（避免再次扩大缺口），仅交付对齐机制；对齐完成后再开 v3.34 推进 13.x；③ 本轮交付两份独立命名的文件 `config.v333.py`（完整 config）与本指令集 md，供用户下载后比对差异再合并，**严禁凭描述手抄常量**（手抄 = 同一份规格的第二个手写实现，必分叉）。
>
> v3.32 更新：**第 12 步交付回执缺项 + 第 13 步（本指令集最后一步）开工前置——「守卫的载体被清理器当垃圾删掉」**——① ✅ 核对：本轮首次给出**四类计数**（`870 通过 / 0 失败 / 0 跳过 / 0 收集错误`，pytest 287 + 20 套脚本式 583），覆盖范围从前两轮的「只报 pytest 203」**恢复**；并顺手修了 4 个数据层真实缺陷（残缺末根自愈 / 复权因子 reindex 整段 NaN / `datetime64` 精度 / 「因子恒为 1 = 不支持复权」误判），其中后两条**正好命中第 13 步 13.2 的病根** → 说明第 13 步其实已被部分开工，工程判断正确；② 🔴 **第 12 步回执与 v3.31 的 K2~K8 逐条对不上**：报告只写「`LiveTrader` 报单前**先过风控**」——这正是 v3.31 指出的原文漏项（12.7 原文就只写「先过风控」）；`core/signal_gate.py`（预热期 / 时效 / 开严平宽）**是否在实盘路径被调用，回执零提及**；`client_order_id` 幂等与 `order_ids.json` 落盘、`on_unknown_state=query_broker_first`、**下单前 + 盘中 60s 对账**（`live/` 文件清单里**根本没有** `reconciliation.py`）、`submit_via_gate` 出站收口与 `forbid_sdk_import_outside_broker_dir`、`forbid_silent_mode_fallback`、`mode_change_requires_flat`、`kill_switch_persist`、个人禁止实盘衍生品**硬拦**、首单限仓——**全部无证据**；测试只给聚合 870、**无「测项 → 守卫」映射**，无法确认 `test_live_gate` / `test_idempotency` / `test_reconcile` / `test_kill_switch_persist` 是否存在 → 判定：**第 12 步很可能是「闸门第五次失守」，形态是「实盘只过了风控、没过信号闸门」**；③ 🔴 **本步是最后一步**——前 11 轮用的机制是「给**下一步**正文加 `X.0` 开工前置」，而第 13 步之后**没有第 14 步**；第 13 步的守卫**消费者全在更早的步骤里、且代码已经写完**（第 2/3 步数据出口、第 6/7 步引擎、第 9 步报告、第 12 步实盘）→ 本步的「开工前置」必须写成**回补清单**（哪些**已交付模块**必须回来改），而不是「下一步注意」；④ 🔴 **发现：13.9「磁盘与缓存治理」会删掉前 11 步刚建立的持久化状态**——清理器按「冷 / 旧」判断，而复权因子、完整性清单、快照、PIT 成分股、幂等键、急停状态**恰恰是长期不被读取、但一旦被删就出大事的冷数据**：**「越冷越该删」与「越冷越重要」直接冲突**，且**删除不报错**；`LIVE_SAFETY['idempotency']['persist_path'] = "live_trading/order_ids.json"` 就住在 `live_trading/` 下，而 13.9 明写「`live_trading/` 保留近 3 个月明细」→ **三个月后重启，幂等键已被清 → 去重失效 → 重复下单**，等于**删掉了 K3 的全部意义（「跨重启保留」）**；同构地：删 `data_manifest.json` → 13.3 损坏检测**失去参照、静默失效**；删 `constituents/` → PIT 失效 → **幸存者偏差静默回归**（13.5 只覆盖「数据源拉取失败」，**没覆盖「本地被删」**）；删 `audit_logs/` 任一环 → **哈希链断裂、整链不可验证**；⑤ 🔴 **发现：13.2 的格式迁移是「一次性、不可逆、新旧文件不可区分」**——旧 qfq 缓存「启动时打印一次警告、提示用户删除」= **提醒 ≠ 拦截**（同 10.5 `qi_threshold_check`、12.0「启动风险提示」）；更致命的是 **raw 与 qfq 残留同名、同格式（都是 parquet）、看不出区别** → 读取器只能**猜** → **复权两次或完全不复权 = 静默错价**；迁移中途崩溃 = **半迁移**，若 `migrate_cache_to_raw.py` **就地改名 / 覆盖**则**不可回滚**，且与并发写入相互冲突；⑥ 🔴 **发现：13.3/13.4/13.5 全是「独立 CLI / 一个 API」**——`tools/verify_cache.py` 是**手动命令**、`SnapshotManager.create_snapshot` **靠调用方记得调**、PIT「回测默认启用」只是**文字承诺**；**没人调用就是死代码**（同第 3 步 B1~B5「守卫没有消费者」）；且 13.5 写「数据源失败 → **打印红色警告 → 但不中断（允许学习用）**」，与第 13 步「消除静默数据错误」的目标**自相矛盾**——幸存者偏差会让回测收益系统性高估，是**最该 fail-closed 的错误之一**；⑦ 🔴 **发现：13.4 快照 365 天 < 13.6 月报 / 回测保留 2190 天**（`config.REPORT_LONG_TERM` 实测值）→ **第 366 天起报告里的 `data_version` 成为死引用**，「可复现」**自带过期时间**；且一份报告 = `html` + `json` + `trades.parquet` + `equity.parquet` + **索引记录**，**五份状态之间没有任何一致性机制**（与 12.10「本地账本 vs 券商」同族：**两份状态各自演化**）；13.10 的元数据强校验**只装在「生成入口」**，归档库里的旧报告仍能被 `report list/show` 搜出、被 `stats equity` 统计 → **闸门只单向生效**；⑧ 🔴 **实测三处 spec ↔ `config.py` 打架（本轮已同步修正）**：`DATA_LONG_TERM['data_source_priority']` **缺 `baostock`**（13.1 要求它做免费第一备份源，照 config 实现则**永远切不到**它）；`source_timeout_seconds` / `snapshot_retention_days` / `cache_max_gb` **三个键在 config 里根本不存在**（13.1/13.4/13.9 正文却引用它们 → 照写会 `KeyError` 或**静默回退默认值**）；`BACKTEST_DEFAULTS['adjust']="qfq"` 与 `DATA_LONG_TERM['default_adjust_for_backtest']="qfq"` 与 13.2 正文要求的 `hfq`，**三处口径打架**；⑨ **确立**：`config.py` 新增 `CACHE_GOVERNANCE`（**受保护不可删清单** + 默认 `dry_run` + 删除前查引用 + 删必留痕）、`DATA_VERSIONING`（`price_basis` 标记必读、读不到即 fail-closed、迁移**原子 / 可续跑 / 可回滚** + 维护锁）、`SNAPSHOT_PIT_GUARD`（完整性 / PIT **强制装在读取与回测入口**、快照由**引擎在入口强制生成**、教学放行必须打**粘性水印**）、`REPORT_ARCHIVE_CONFORMANCE`（四份产物**同生共死**、索引 ↔ 文件**双向一致**、`meta_complete` 打标、`stats` 默认只吃可复现报告、**保留期依赖断言**、对外净值曲线落 `investor_disclosure` 且用 `investor_net`）、`SYSTEM_CONFORMANCE`（**收尾总检**：闸门单份实现、五引擎都调用、逐出口**表驱动**验证、报告须给「测项 → 守卫」映射）；并统一 `DEFAULT_ADJUST` 为复权口径**唯一来源**；第 13 步正文新增「**13.0 开工前置：这是最后一步，没有「下一步」可装闸门**」与「**13.13 收尾总检**」；⑩ **流程**：四类计数已恢复（✅），但**「测项 → 守卫」映射仍缺**（870 里哪几项覆盖 K2~K8 看不出来）；本轮上传的 `config.RUN` / `account.py` / `progress.json` **未落到共享工作区**，无法直接核对，请把关键片段贴进对话。

> v3.31 更新：**第 11 步交付复核 + 第 12 步（实盘接入层）开工前置——「本步是系统第一次『指令能真的动到钱』；而第 12 步正文对前置闸门零引用，且『自动重连 + 崩溃重启』会制造重复下单」**——① ✅ 核对第 11 步交付：薄入口（`main.py` 78 行）＋`cli_commands/` 八模块（均 ≤300 行）＋24 子命令；`--data` 缺列 fail-closed；模式提升被拒、降级放行；13 项禁参 grep `exit=1`；README 诚实标注第 12/13 步未开始；Trae 以「AST 按行区间机械抽取 ＋ 短 Edit 追加」解决长写入损坏，**工程判断正确**；② 🔴 **发现：第 12 步正文对前置闸门「零引用」**——12.7 只写「信号产生后**先过风控**」，而 12.6 的风控管的是**仓位/亏损/杠杆**；第 5~11 步建立的 `core/signal_gate.py`（预热期 / 时效 / 开严平宽）在这条路径上**一次都没被调用**；同时 12.2「自动断线重连」与 12.8「崩溃自动重启」**恰恰制造了『同一信号被消费两次』的条件** → 实盘引擎成为**第五个引擎**，闸门**第五次失守**；③ 🔴 **发现：无幂等 → 自动重连 ＋ 崩溃重启 ＝ 重复下单**——报单**超时**（券商其实已受理）→ 判为失败 → 重发 → **成交两笔、仓位翻倍**；要求每笔报单携带唯一 `client_order_id` 并**落盘跨重启保留**，同键重复提交拒绝，**状态未知时先查券商再决定是否重发**；④ 🔴 **发现：对账只在「收盘后」，而全部风控读本地账本**——12.10 把对账放在「收盘后第一件事」，但 12.6 的总资金 / 总杠杆 / 集中度**全部读本地副本**，本地一旦漏记成交，风控就在**错误画面上判断**，且要等到**次日**才拦；与第 2 步「守卫读的是会变味的 `attrs`」**同族**——**权威在券商侧，本地只是可能过期的副本**；要求**下单前 ＋ 盘中定时**对账，不一致即**停开新仓**（不是只写报告）；⑤ 🔴 **发现：「个人禁止实盘衍生品」与「启动风险提示」都只是『打印』**——**提醒 ≠ 拦截**（同 10.5 `qi_threshold_check`、11.0 checklist）；要求真实报单路径上**硬拦**；⑥ 🔴 **发现：12.5 写「三模式一键切换、上层无感」**——恰恰相反：**禁止静默回退**（实盘连不上券商必须报错停机，不得自动退回仿真），每笔报单 / 每份报告**必须标注当前模式**；且**切模式（含降级）前须无持仓、无在途单**（有仓时切回 `backtest` ＝ **放弃实盘风控**）；⑦ **确立**：报单**唯一出站收口**，`SIGNAL_EGRESS_CONFORMANCE['signal_egress_points']` 增 `live_order_submit`；`config.py` 新增 `LIVE_SAFETY` / `ORDER_PORT_CONFORMANCE`，并把 v3.30 的薄入口三键＋禁参结构性校验键并入 `CLI_CONFORMANCE`；⑧ **流程**：本轮回归只报 `pytest tests/` 203 项，**未报脚本式套件**（`test_env`/`test_chan`/`test_chart`/`test_pattern`/`test_export`/`test_data`/`test_account`/`test_indicators` 等共 20 套 583 项）——覆盖范围比前几轮**静默收窄**，要求恢复全量四类计数（通过 / 失败 / 跳过 / 收集错误）。
>
> v3.27 更新：**第 8 步（盯盘推送）交付复核 + 第 9 步（复盘报告）开工前置——「报告只报成交、不报拦截＝替闸门掩盖；而『明日候选』本身就是第三个信号出口」**——① ✅ 核对：第 8 步已交付（`test_monitor` 16/16），8.0「第二信号出口」已落地（喂 `on_tick` 的数据经 `signal_gate` 构建并校验三物化列、缺列/NaN 报错；开仓过闸门、平仓/风控放行；停更只推数据告警；逐市场判时段含夜盘/DST；推送带闸门与新鲜度标注）；② 🔴 **发现：第 9 步（`core/reporter.py`）是「第三个输出口」，而它只报「成交了什么」，会把闸门的拦截静默抹掉**——第 6/7/8 步的闸门会拦下大量信号（预热期 / 停更 / 非交易时段 / 涨跌停 / 量限截断 / 风控），但**报告只呈现结果、不呈现「抑制」（suppression）**→ 用户看到「今天 0 笔交易」时，**无法区分「策略没信号」与「闸门拦掉了 20 个信号」**；这正是第 2 步 fail-closed 锁死、第 6 步「零成交」这类症状**在报告里完全不可见**的根因；且第 6 步刚建立的 `EXECUTION_MODEL['bias_direction']`（偏差归因）在报告里**没有任何落地**；③ 🔴 **发现：「明日计划 / 候选标的」是「未登记的信号出口」**——它是**前瞻性、推给用户看的「建议」**，性质与第 8 步盯盘推送完全相同；但它**不在** `SIGNAL_EGRESS_CONFORMANCE['signal_egress_points']`（原仅 `place_order` / `monitor_push`）里，因此**既可以绕过 `core/signal_gate.py`，也可以不过时效闸门** → 预热期 / 停更标的会被当成「明日买入候选」推给人；这是「闸门随输出口扩散而漏装」的**第五次复制**，形态是**报告里的前瞻建议**；④ **确立**：**报告必须与引擎/闸门同源，并强制披露「被拦掉的信号」**（`config.REPORT_CONFORMANCE['must_report_suppression']`）；**「候选标的」进入信号出口清单**（`signal_egress_points` 增 `report_plan`），过闸门 + 时效 + 标注；⑤ 🔴 **流程问题**：Trae 本轮以「`test_factor.py` 有 5 个收集错误、属因子研究模块既有问题、与本步无关」为由豁免——**收集错误＝该部分测试根本没跑，不能用「既有问题」豁免**（与「报告只报成交、不报拦截」同构：**测试报告只报「通过的」，不报「没跑的」**）；⑥ **未回执项**：上轮指令 A 的 E1（`match_price_basis` 参数化 + `assert_fill_after_signal`）、E4（`test_export` 幂等）、E5（B3/B4/第 4 步回补/两常量是否并入）**仍未逐条回执**；⑦ 🔴 **`config.py`**：`SIGNAL_EGRESS_CONFORMANCE['signal_egress_points']` 增 `report_plan`，新增顶层常量 `REPORT_CONFORMANCE`；**第 9 步正文新增「9.0 开工前置：复盘报告是第三个输出口」**。

> v3.28 更新：**第 9 步（复盘报告）交付过审 + 第 10 步（合格投资者层）开工前置——「本步是系统第一次『对外』：合格投资者是『每个动作的闸门』而非『一次性资格标记』；净值曲线只报产品毛净值、不报投资者费后净值，就是替合规闸门做美容」**——① ✅ 核对：第 9 步已交付（`test_reporter` 15/15），9.0 三条硬断言（被抑信号可见 / 预热·停更不进候选 / 绩效与引擎同源）均落地，并顺手修了 `backtester._trade_stats` 缺列崩溃；本步测试收集错误已清零（`43 passed / 0 failed / 0 skipped / 0 收集错误`）；② 🔴 **发现：第 10 步（`core/qualified_investor.py`）把合格投资者校验写成「尝试加入品种前」的一次性准入**——`check_current_threshold(asset_profile)` 通过之后，**追加申购 / 份额转让 / 代持 / 拆分份额 / 变换持有人**全部绕过；而《**资产管理信托管理办法**》（2026-10-30 发布、2027-01-01 施行）已明确**买入与转让两端都要评**、**单只产品投资者≤200 人**，且**必须穿透核查最终投资者、合并计算人数**；这与第 2 步 `for_trading` 默认放行、第 9 步「报告只报成交」是**同一族错误：守卫活在一个「此后不再触发」的位置上**；③ 🔴 **发现：净值口径「美容」**——`NavBacktester` 有高水位法 carry，但**单一产品净值曲线在数学上算不出「投资者费后净值」**（**carry 是 per-investor 的**：不同申购时点 → 不同高水位 → 不同计提）；若对外展示的「组合净值曲线」用的是**产品毛净值**，业绩**系统性高估**（管理费 1–2%/年 + carry 20%，十年维度可吃掉累计收益 40–50%）；须显式区分「产品层毛净值 / 产品层费后净值 / 投资者层费后净值」，**披露口径固定为 `investor_net`**；④ 🔴 **发现：净值披露滞后＝结构性未来函数**（周频净值次周一/二才披露；月频十年仅约 120 个点，一次未来函数即显著抬高回测收益），与第 7 步 `assert_fill_after_signal` **同族**——须强制 `决策日 >= 披露日 + 滞后期` 并加断言；⑤ **确立**：`10.5` 的 `qi_threshold_check` 只是「**提醒**」——**提醒 ≠ 拦截**，资产缩水到门槛以下须**拦住后续申购**；⑥ **口径更新**：现行三套门槛**不得混用**（私募基金 / 资管产品 / 信托计划），且 2026 年新规须区分「**已发布待施行**」与「**征求意见稿**」，不得笼统写「尚未生效」；⑦ 🔴 **`config.py`**：新增 `QUALIFIED_INVESTOR_RULES` / `NAV_PRODUCT_CONFIG` / `DISCLOSURE_CONFORMANCE`，`SIGNAL_EGRESS_CONFORMANCE['signal_egress_points']` 增 `investor_disclosure`；**第 10 步正文新增「10.0 开工前置」**。
>
> v3.26 更新：**第 7 步（模拟盘）交付复核——「对着旧版自查，得到的是一张假对账单」**——① 🔴 **Trae 引用的「指令集 L1204–1245」实为 5.9.1「Alpha101/Alpha191 因子表达式引擎」段落，与第 7 步无关**（第 7 步正文位于「**第 7 步：模拟盘交易**」标题之后，**不在 L1204 段**）；② 🔴 **其复述的「原文写『每日收盘后用当日收盘价撮合』」已是旧表述**——当前第 7 步 `run_daily` 条**已改为参数化引用** `EXECUTION_MODEL['match_price_basis']`，第 6 步「滑点与成交模拟」条亦已补撮合时点约束，`config.py` 的 `match_price_basis` / `match_price_basis_meta` / `enforce_fill_after_signal` 与 `SIGNAL_EGRESS_CONFORMANCE` **均已就位** → **据此判定：Trae 审的不是最新版**；③ 🔴 **上轮指令 A 的 E1–E5 未执行**（Trae 自述「未改动任何代码，只补两条已知限制」）；④ **确立**：新增**实现前版本自检**硬要求（见文首）——引用与标题对不上时，先核对版本再动手；⑤ **回答 Trae 的请示**：**需要参数化，且 spec 已定**——不是「要不要做」的选择题，而是「按已定 spec 执行」；且**关键不在开盘/收盘，而在「成交 bar 必须严格晚于决策 bar」**。
>
> v3.25 更新：**第 7 步（模拟盘）交付过审 + 第 8 步（盯盘推送）开工前置——「闸门装在了三个引擎上，却漏了第四个出口：人的眼睛」**——① ✅ 核对：第 7 步已交付（`test_paper_trade` 31/31、`test_engine_consistency` 16/16），7.0 三板斧（`signal_gate` / `execution` / `risk`）已下沉为**引擎无关单份实现**，Trae 主动请示口径、纪律正确；② 🔴 **发现：指令集对「撮合价基准」自相矛盾**——第 6 步正文写「市价单按**当日开盘价** + 滑点成交」，第 7 步正文又写「每日收盘后用**当日收盘价**撮合」，同一条还要求「与回测**完全一致**」；Trae 为保一致性两引擎统一按开盘价（**方向正确**），但**未参数化、也未改 spec** → 第 12 步实盘正文会**再次面对同一歧义**、可能再各选各的；③ 🔴 **更严重：撮合价基准是「未来函数」的藏身处**——关键不在「开盘 or 收盘」，而在**成交所用 bar 必须严格晚于决策所用 bar**；若 `on_bar(t)` 用 **t 收盘**决策、却按 **t 开盘价**成交，等于用未来信息在当下成交（系统性乐观）；须参数化 `EXECUTION_MODEL['match_price_basis']`（默认 `next_open`）并强制断言 `fill_bar_index > signal_bar_index`；④ 🔴 **第 8 步盯盘是「第四个信号出口」，且是最危险的一个**——第 8 步正文（`core/monitor.py`）写「每次检查调用 `data_fetcher` 获取实时行情、**传入策略的 `on_tick`**」，**绕开一切引擎的 `bar_dict`** → 不注入 `warmup_ok`、不调 `core/signal_gate.py`、不查时效 → **预热期 / 停更数据的信号会【直接推给人】**；自动下单尚有 `place_order` 兜底，推给人则**无人兜底**，用户据此手动下单＝用有偏信号交易；这是「闸门随引擎替换静默消失」的**第四次复制**，形态是**新增一个信号出口（人的眼睛）**；⑤ 🔴 **盯盘的「交易时段判断」是其主功能**（逐市场时段），Trae 称「未加 09:30–15:00 硬卡点」（对模拟盘补跑的取舍合理）——但盯盘**面向推送给人**，非交易时段误推会直接误导用户，须**逐市场**用 `get_market_config` + 交易日历复核，且**推送前须过时效闸门**；⑥ `config.py`：`EXECUTION_MODEL` 增 `match_price_basis` / `enforce_fill_after_signal`，新增 `SIGNAL_EGRESS_CONFORMANCE`；第 8 步正文新增「**8.0 开工前置：盯盘是第二个信号出口**」，第 6 步「滑点与成交模拟」补撮合时点约束，第 7 步 `run_daily` 口径矛盾修正。
>
> v3.24 更新：**第 7 步（模拟盘）开工前置过审——「第三种引擎：同一个闸门第三次失守；写实成交与风控各住各的家」**——① ✅ 核对：第 6 步已完工（`test_backtest` 28/28、`test_signal_gate` 25/25、全量回归无回归），6.0「闸门随引擎迁移」已落地（`bar_dict` 缺 `warmup_ok` 报错、开仓过闸门/平仓豁免、长度门槛 `max(60, required_bars())`、三物化列逐标的保留；引擎一致性测试：同一「预热期 + `fillna(0)`」帧在 `runner` 与 `Backtester` 下 `buy()` 各 125 次**全拒**、首笔成交下标一致）；② 🔴 **发现：第 7 步是「第三种引擎」，正文对闸门「零引用」**——第 7 步正文（`core/paper_trader.py`）对 `warmup_ok` / `signal_gate` / `required_bars` / 时效 的**引用数 = 0**（已实测核对），与第 5 步「正文零引用」、第 6 步「正文零引用」**同构**，是同一个错误的**第三次复制**：模拟盘引擎不向 `bar_dict` 注入 `warmup_ok` → 闸门**无源**——要么「裸单全拒」（模拟盘一笔都开不出，= 第 2 步 fail-closed 锁死**重现**），要么被绕过；须新增「**7.0 开工前置**」；③ 🔴 **发现：写实成交与风控「各住各的家」→ 三环境两套逻辑，回测—模拟不可比**——Trae 自述成交模型 `ExecutionModel` **「仅挂回测 account」**，而第 6 步正文**从未定义**该模块（全文检索 `ExecutionModel`/`执行模型` = **0**）→ 它是自建组件、第 7 步**无从复用**；同时**风控（单票仓位 / 日内亏损 / 黑天鹅 / 杠杆）只在第 7 步正文出现**、第 6 步回测未引用 `config.RISK` → 回测无风控、模拟盘有风控、再加两套撮合 → 第 7 步那句「偏差超过 5% 打印警告」会被**已知的结构性差异**触发，用户去追一个**幻影**；④ **确立**：**成交模型与风控必须提取为「引擎无关」的共享组件**（`core/execution.py` + `core/risk.py`），`backtest`/`paper`/`live` **三处共用、只调用不重写**，差异**只允许参数化**（如 `slippage_multiplier`）；并写「**三引擎一致性测试**」；⑤ 🔴 **4 项「已知简化」硬编码且未标注乐观/悲观方向**（卖出滑点按开盘统一 / 涨跌停仅判开盘即封板 / 量限固定 1% 未分市场分档 / 基金·逆回购走净值透传）——须进 config（`EXECUTION_MODEL`）并逐项标注 `bias_direction`，否则回测—实盘偏差**无法归因**；「2 倍滑点」也不得硬编码在第 7 步正文；⑥ `config.py` 新增 `EXECUTION_MODEL` 与 `ENGINE_CONFORMANCE`；第 7 步正文新增「**7.0 开工前置：第三种引擎——闸门/成交/风控都不得各住各的家**」，第 6 步「滑点与成交模拟」与「6.0」补引擎无关共享条款。
>
> v3.23 更新：**第 6 步（回测引擎）开工前置过审——「要被替换的引擎里，闸门活不过一次替换」**——① ✅ 核对：第 5 步已落地（5.0 双闸门落在信号入口，`test_strategy` 18/0、`test_loader` 20/0、`test_research` 19/0、`test_factor_strategy` 14/0），四环境同一策略零改动、越权扫描通过；② 🔴 **发现：第 6 步正文对闸门「零引用」，且第 6 步会替换第 5 步的 `core/runner.py`**——Trae 自述「`core/runner.py` 的轻量执行器会被替换，`BaseStrategy` 接口不变」；凡写在 `runner.py` 里的闸门逻辑（`warmup_ok` 逐 bar 注入、末根预热判定、`assert_signal_frame`）会随替换**静默消失**，而第 6 步正文（`core/backtester.py`）对 `warmup_ok`/`required_bars` 的引用数 **= 0** → 与上一轮「第 5 步正文零引用」**同构**，同一个错误正要**再演一次**：新引擎在**没有闸门**的接口上产出信号，预热期 `fillna(0)` 照样把 `RSI` 变成「极度超卖」发买入信号；③ 🔴 **硬编码「少于 60 根拒绝」与 `required_bars` 冲突**：第 6 步写「少于60根K线直接报错」，而 `required_bars`（`MACD` 的 `DEA` 收敛约 70+ 根）**远大于 60** → 60~70 根的标的**通过长度检查后全段落在预热期** → 闸门把每一笔都拦住 → **回测静默零成交**，用户会误判「策略没用」；阈值须改为 `max(60, strategy.required_bars())`，禁止硬编码；④ **未确认项**：上一轮指令 A 的 B3（`price_adjust` 按 `symbol` 分组）、B4（期权 `IV` 无解 fail-closed）、第 4 步「指标预热闸门联动」回补**均未在回执中确认**，须一并核对/落地；⑤ 确立：**闸门必须下沉为「引擎无关」的唯一实现**（`core/signal_gate.py`，与 stale 闸门同在 `place_order` 单一收口），并写**引擎一致性测试**（同一份「预热期 + `fillna(0)`」帧，在轻量 `runner` 与 `Backtester` 下 `buy()` 都被拒）；`config.py` 新增 `GATE_CONFORMANCE`；第 6 步正文新增「6.0 开工前置：闸门随引擎迁移」。
> v3.22 更新：**第 5 步（策略研究）开工前置过审——「守卫没有消费者，就是死代码」**——① ✅ 核对：第 4 步已完工（`test_account.py` 46/46），第 3 步 A1–A5 已落地；② 🔴 **发现：第 5 步正文对本步前置守卫「零引用」**——第 3 步建立的 `warmup_ok` 物化列、`required_bars`、`price_adjust` 分组、期权 `IV` fail-closed，唯一该生效的地方就是本步的**信号入口**（`BaseStrategy.on_bar`），但第 5 步正文一次都没提（引用数 = 0）→ 若照原样开工，策略会在**没有闸门**的情况下产出信号、`warmup_ok` 无人消费 → **B1–B5 全部沦为死代码**，`fillna(0)` 照样把预热期 `RSI` 变成「极度超卖」发买入信号——与第 2 步 `attrs`、第 3 步「守卫装在会失灵的信息源上」同一族，只是这回「没人执行」的原因是**消费者的规格里根本没写**；③ 🔴 **跨步孤儿**：第 3 步 B5 写了「并与第 4 步下单闸门联动」，但第 4 步正文没有该条、且第 4 步**已完工** → 该联动落空，须**回补**（`place_order` 开仓方向在 `warmup_ok=False` 时拒单，平仓/减仓放行）；④ **缺口成因**：第 3 步 B1–B5 与两个常量（`INDICATOR_WARMUP_GUARD`/`OPTION_VALUATION_GUARD`）尚未合并/落地（Trae 正确地未擅自补写，等确认）——已确立：**这些是第 3 步欠账，必须作为第 5 步开工前置完成，而不是塞进第 5 步**；⑤ **第 5 步正文新增「5.0 开工前置：两道闸门必须在信号入口真正生效」**，第 4 步补「指标预热闸门联动」条款。
>
> v3.21 更新：**第 3 步（技术指标）过审 v3——「预热期 NaN 只是哑弹，不是墙」**——① ✅ Trae 本轮 A1–A5 全部落地（复权守卫 fail-closed、`required_bars`+前 N-1 根置 NaN、评估类 `eval_` 前缀物理隔离、`volume` 全 0 返回 NaN、希腊字母单位写死），`test_indicators.py` 63/63；② 🔴 **新发现：预热期的 NaN 挡不住信号**——`fillna(0)`/`ffill`/`bfill`/`rolling(min_periods=1)` 都会把 NaN 抹平，其中 **`fillna(0)` 最阴**：`RSI`/`KDJ` 的预热 NaN 变 0 → 被策略读成「极度超卖」→ **预热期直接发买入信号，且不报错**；预热判定必须**引擎级统一裁决**（指标输出携带 `warmup_ok` 物化布尔列，信号入口强制过滤），不能靠调用方自觉——与第 2 步 `attrs` 丢失、第 3 步「守卫装在会失灵的信息源上」同一族；③ 🔴 **`required_bars` 是「下界表」、没做收敛验证**：`EMA(12)` 初始残差按 `(1-α)^n` 衰减（α=2/13），第 20 根仍有 ~3.5%，`MACD` 的 `DIF→DEA` 递归链更长（等效 ~70 根）——须用**与充分燃烧期长样本比对、相对误差 ≤ 1e-3** 反推「所需最少根数」，而非查表取 `max`；④ 🔴 **`price_adjust` 物化列在多标的帧里会退化成「整列一个值」**，掩盖混合口径（与上轮 `data_asof_date` 同源），须**按 `symbol` 分组填**；⑤ 补：期权 `IV` 二分法在**深虚值 / T→0 / 市价低于内在价值**时无解，须**返回 NaN 并标注**，禁止返回边界值；⑥ `config.py` 新增 `INDICATOR_WARMUP_GUARD` 与 `OPTION_VALUATION_GUARD`。
>
> v3.20 更新：**第 3 步（技术指标）过审 v2——三处「守卫装在会失灵的信息源上」的结构问题**——① 🔴 **复权口径守卫 fail-open**：Trae 的 `check_adjusted()` 读 `attrs['adjust']`，而 `attrs` 会被 `resample`/`concat`/窗口运算清空（第 2 步已确立）→ 清空后**静默按「已复权」处理**，`ATR`/`STD`/`HIST_VOL` 可能在未复权价上计算——**正是 3.0 一.2 说的「最隐蔽错误」**；且它只测了「显式 `none` → 抛错」、**没测「`attrs` 缺失」**。正解：复权口径**物化为普通列**（`INDICATOR_HARDENING['adjust_column']='price_adjust'`）或**显式函数参数**，不读易失 `attrs`，口径未知时按 `on_adjust_unknown='require'` 报错；② 🔴 **递归类指标预热期未定义**：`EMA`/`SMA`(通达信)/`RSI`(Wilder)/`ADX`/`SAR`/`MACD 的 DEA` 早段值依赖初始化、**有偏**（不是未来函数，但同样让信号失真）——须为每个指标定义 `required_bars()` 并要求回测/实盘**跳过预热期**（`INDICATOR_HARDENING['warmup']` 给默认参数下的最小根数）；③ 🔴 **两条跨市场红线是「可选调用」且依赖可缺参数**：`assert_indicator_usable(for_signal=...)` 若策略忘传即静默放行（评估类指标进入信号链=未来函数）；净值型判定依赖 `market` 参数、缺省即放行——须把评估类指标**物理隔离**（统一 `eval_` 前缀 / 独立子模块），并让「实时信号链入口」统一挡；④ 补齐 `volume` 全 0 的处置（须返回空/NaN 并标注，**禁止静默返回 0**——0 会被误读为「极度缩量」）；⑤ `config.py` 新增 `INDICATOR_HARDENING`（复权物化列、口径未知处置、各指标预热根数、评估类前缀、量能全 0 处置）。
>
> v3.19 更新：**时效复核 v2——堵住「物化列」在真实链路失效的三处漏洞**——① ✅ Trae 已修正 fail-closed 误拒：`config.py` 新增 `STALE_INFO_COLUMN`/`STALE_CHECK_MODE`/`FAIL_CLOSED_NOTE`，`data_fetcher` 新增 `_attach_asof()`（各出口写 `data_asof_date`），`assert_fresh_for_trading()` 改为「读物化列 → refetch → 兜底 fail-closed」；② 🔴 **新发现三处漏洞**：(a) 本系统指标库是**纯函数**（只吃 `Series`/返回 `Series`），策略拼决策帧时 **`data_asof_date` 列不会被带过去** → 「读物化列」对策略决策帧常为空，**下单时效复核必须以 `refetch` 为主**（第 4 步闸门须强制按 `market+symbol` 重取）；(b) 数据层出口写列的日期**必须是该帧最后一根 bar 的实际日期**，**不能是「取数时刻/今天」**——尤其**缓存命中、失败回退**两个出口，否则缓存旧数据会被标成新鲜、**防线在最常见路径上失守**；(c) **多标的帧逐行填充会退化成「整列同一日期」**，一个新鲜标的会掩盖同帧内的过期标的——须**按 `symbol` 分组**填各自最新日期；③ `config.py` 新增 `STALE_REFETCH_TTL_SEC`（批次内 refetch 结果复用）与 `STALE_REFETCH_FAIL_POLICY`（refetch 失败：开仓拒、平仓放行）；④ 第 4 步下单闸门补「v2 强化」条款，1.0 节七补「时效复核 v2」小节。
>
> v3.18 更新：**第 2 步 stale 机制「过度保护」风险过审——fail-closed 会让实盘全面拒单**——① 🔴 核对 Trae 测试表时发现，它把「`rolling` 后 `attrs` 丢失 → fail-closed 抛错」当成**正确结果**；但**实盘策略一定是算完指标才下单的**（MA 金叉 / MACD 背离 / ATR 止损都走 `rolling`/`ewm`/`expanding`）→ 时效闸门若「读不到 `attrs` 就 fail-closed」，会导致**每一笔下单都被拒、实盘彻底瘫痪**：这不是安全，是把系统锁死；② 确立正解：时效信息必须**脱离易失的 `attrs`**——`config.py` 新增 `STALE_INFO_COLUMN`（默认 `data_asof_date`，**物化为普通列**，列会随 DataFrame 穿过 `rolling`/`ewm`/`resample`/`concat`）、`STALE_CHECK_MODE`（默认 `refetch`，下单链路**独立重新取数**复核）、`FAIL_CLOSED_NOTE`（fail-closed 仅限「既无时效列、又无法重取」的兜底场景）；③ 第 4 步下单闸门补**实现方式**条款，明确**禁止**写成「`attrs` 读不到就 fail-closed」。
> v3.17 更新：**第 2 步 stale 机制过审——发现「默认放行」缺陷，确立下单链路「双重防线」**——① 🔴 **`for_trading=True` 是「默认放行」（fail-open）**：纸面/实盘模块一旦**忘记传**该参数，过期数据就会静默流入下单链路；**上游少传一个参数是迟早会发生的事，不能靠约定保护实盘**——改为**下单链路必须持有独立的时效闸门**（`config.TRADING_REQUIRE_FRESH=True`），在**每次下单前**独立复核、不信任上游标记；② 🔴 **`df.attrs` 极易丢失**：pandas 的 `concat` / `resample` / `merge` / `groupby` 等运算后 `attrs` 常被丢弃，而**增量库合并、`re_sample_kline` 重采样都要走这些运算**——一旦 attrs 丢失，`stale` 会**静默变回「新鲜」**；要求关键出口统一重新挂载 attrs，且**禁止仅凭 `attrs['stale']` 做交易决策**（这正是第二道防线必须「独立」的原因）；③ `_latest_completed_trading_day()` 必须**按市场分别判定**（A股/港股/美股收盘时刻不同、期货含夜盘、外汇近 24 小时、加密 7×24），不能只用 A股一套时钟；④ `config.py` 新增 `TRADING_REQUIRE_FRESH` 与 `ATTRS_FRAGILE_NOTE`。
>
> v3.16 更新：**第 2 步最终收尾核对——补齐「数据时效（stale）」边界约定，并清理市场数残留**——① 🆕 **1.0 节七新增「数据时效（stale）约定」**：数据源不可达但**有本地库时不得静默返回过期数据**，必须标 `stale=True` + `stale_days` 并告警；**回测/研究允许用 stale 数据，但模拟盘/实盘的下单决策禁止使用 stale 数据**（防止用过期价格成交）；**stale 超上限（日线 5 个交易日、分钟线 2 个交易日）视为不可用、直接报错**；② 清理 `config.py` 中 3 处「18 类 / 11 类」残留注释，统一为 19 类。
>
> v3.15 更新：**第 3 步（技术指标）过审并加固——补齐 3 条「写错不报错」的硬约定与 2 条跨市场红线**——① 🆕 **3.0 节三条硬约定**：**复权口径必须全局统一**（同一组指标不得混用口径；`ATR`/`STD`/`HIST_VOL` 等波动率类**必须用复权价**，否则除权日跳空会被当成真实波动、除权日附近信号全乱）、**量能类指标只用 `volume`、禁用 `amount`**（期货/指数 `amount` 为 NaN；且 `volume` 单位跨市场不可比：股票=股 / 可转债=张 / 期货=手）、**年化基数必须引用 `config.INDICATOR_CONFIG`**（禁止硬编码 252；A股约 244、美股 252）；② 🆕 **两条跨市场红线**：**评估类指标（`MAX_DRAWDOWN`/`SHARPE_RATIO`/`ANNUAL_RETURN`/`VOLATILITY`）是全样本统计量、禁止进入实时信号链**（否则等于未来函数）、**净值型品种（场外基金/逆回购/私募/资管）不适用 K 线类指标**（`open/high/low=close`、`volume=0`，算 `ATR`/`KDJ`/`BOLL` 无意义）；③ 补齐**空表/全 NaN 优雅降级**、**未来函数红线**（禁 `center=True`、禁全样本标准化）、指标口径注明（`SMA` 通达信口径、`ADX`/`RSI` Wilder 平滑、`SAR` 初始方向、`MACD` 柱=2×(DIF-DEA)）；④ 强化 `test_indicators.py`：随机数据必须满足 OHLC 合法性、**必须对少数指标做逐值手算校验**（不能只查 shape）、新增**复权口径校验**与**年化基数校验**；⑤ `config.py` 新增 `INDICATOR_CONFIG`（年化基线、按周期年化因子、默认复权口径、量能口径、评估类指标清单、净值型市场清单）。
>
> v3.14 更新：**第 2 步彻底收口——指数成交量单位完成独立闭环验证，并首次量化「数据源可用性」**——① ✅ **指数单位验证通过（铁律 7 结案）**：以 BaoStock 指数日线（官方同时返回 `volume`/`amount`）与新浪同指数同日 volume 交叉比对，`sh.000300` 与 `sh.000001` 比值 **1.0000**、`sz.399001` 比值 **0.9991**（源修订差异）；BaoStock 侧自检 `amount/volume=22.71 元/股`（成分股均价量级，合理）→ **确认新浪指数 volume=「股」、÷100 转「手」的现有实现正确**，`stock_zh_index_daily` / `baostock_index_daily` 升级为 `verified=True`；② 🆕 **新增「数据源可用性」量化清单（1.0 节七）**：实测 8 个后端，东财 `push2his`（个股/ETF/指数日线+分钟**全线**）本机持续 `RemoteDisconnected`，新浪/BaoStock/腾讯/币安可用；据此列出**「东财挂即完全取不到」的市场**（`forex` / `cn_fund` / `cn_reverse_repo` 的日线）与**「分钟线仅东财」的市场**（`cn_convertible` / `us_stock` / `us_etf` / `hk_stock`）——第 13 步多源切换的必要性被现实印证，且**单源品种「切换也无从切换、必须补源」**；③ 缠论三类点归档（新增可选 `b3_filter_enable`，默认关、不改变默认点数）；④ `config.py` 合并 `stock_zh_index_daily_tx`（标注其 `amount` 列实为成交量(手)的陷阱）与 `CN_INDEX_DAILY_PRIORITY`。

> v3.13 更新：**第 2 步六项收尾落地，并新暴露一处「指数成交量单位无法自检」的隐患**——① `cn_index` 完整接入：裸 6 位 `CN_INDEX_BARE_CODES`（`399001`/`399005`/`399006`/`399673`/`932000` 等**不与深市个股号段冲突**的可裸识别）、带前缀拦截、指数专用取数（东财→新浪→BaoStock），`test_env` 75/75；② 缠论**一/二/三类买卖点全部产出且可溯源**（六年日线 B1=16 / B2=11 / B3=2 / S1=18 / S2=11 / S3=1；22 个二类点全部带 `src_date` 可追溯到前置一类点，孤儿 0），`test_chan` 30/30；③ 基准改回真实指数 `sh000300`；④ ⚠️ **新暴露隐患**：实测**新浪指数日线无成交额**（`amount=NaN`），且**东财 `push2his`（个股/ETF/指数日线+分钟全线）在本机持续 `RemoteDisconnected`**，指数回退新浪；而**指数成交量单位无法用 `amount/(close×volume)` 自检**（指数点位×股数无换算关系，比值必然离谱），当前"新浪指数 volume=股、÷100 转手"只有腾讯接口反推、**缺独立验证**；⑤ 修复：新增 **1.0 铁律 7「指数成交量单位必须跨源交叉验证」**——用 **BaoStock 指数日线**（官方字段**同时含 `volume` 与 `amount`**，实测 `amount/(close×volume)≈1.0`）与新浪**同指数同日** volume 比对：比值≈1 → 新浪=股（须 ÷100 转「手」）、比值≈100 → 新浪已是「手」（**禁止再 ÷100**）；未验证通过前指数 volume 一律标 `unit_uncertain=True`；⑥ 记录**腾讯 `stock_zh_index_daily_tx()` 字段陷阱**：其 `amount` 列实为**成交量(手)**、不是成交额；⑦ 缠论**三类点极稀疏**（六年单标的仅 B3=2 / S3=1）且**对中枢延伸上限高度敏感**（上限 3→B3=4、9→2、∞→0），已记入已知限制，标注为"轻量实现、非严格缠论"。
>
> v3.12 更新：**第 2 步收尾归档，并发现一处指数识别的遗留漏洞**——① 第 2 步收尾完成：`cn_index` 指数接入后**基准改回真实指数**（`sh000300`，不再用 `510300` ETF 代理）；缠论**一/二/三类买卖点全部产出**（六年日线共 50 个信号，六类齐全）；`test_env` 66/66、`test_chart` 19/19、`test_chan` 26/26、`test_pattern` 14/14、`test_export` 11/11；② ⚠️ **遗留漏洞**：上一轮的指数拦截只处理了**带前缀**（`sh000300`）的情况，**裸 6 位指数代码仍被误判为 `cn_stock`**——实测 `000300` / `000905` / `399001` 全部返回 `cn_stock`，数据层会把这些指数当深市个股取数，**不报错但基准是错的**；而第 6 步回测 `benchmark` 默认写的正是裸 `000300`；③ 修复：`config.py` 新增 `CN_INDEX_BARE_CODES`（裸 6 位指数白名单），`detect_market_type` 对白名单内代码（`399001` / `399006` / `399673` / `932000` 等**不与深市个股号段冲突**的）直接返回 `cn_index`；而 `000xxx` 段（`000300` / `000905` / `000016` / `000688` 等）与深市个股号段 000/001/002/003 **完全重合**（如 `000001`=平安银行、`000009`=中国宝安、`000016`=深康佳A），**无法裸识别、必须带前缀**（`sh000300`）——取指数行情一律写带前缀形式最稳；④ 本文件 2.8 节已补入第 2 步「实测结果与已知限制」。
>
> v3.11 更新：**新增 `cn_index` 指数类型，修复 `sh/sz` 前缀代码被误判为国内期货的静默错误**——① 实测 `sh000001` / `sh000300` / `sh000905` 原样返回 `cn_future`，数据层把指数代码当期货主力合约，取回**同一条错误序列（1486 点）**，不报错但数据全错；② `config.py` 新增 `CN_INDEX`（`tradeable=False`，仅用于基准/择时）、`INDEX_PREFIX_RULES`（`SH`：000/950/880/881，`SZ`：399/980/981），`detect_market_type` 新增**带前缀指数拦截**（置于「字母+数字=期货」判定之前），`sh600519→cn_stock`、`sh510300→cn_etf` 等常规写法不受影响；③ 市场类型由 18 → **19**（`cn_index` 为新增的「不可交易」类型）；④ 第 1 步数据层新增 `_fetch_cn_index_daily()`，指数取数必须走**指数专用接口**，禁止复用个股接口；⑤ 第 2 步基准（`000300` 等）接入指数后不必再用 ETF 代理；⑥ 第 2 步补充「实测结果与已知限制」（2.8 节）。
>
> v3.10 更新：**周期定义收敛为全局唯一来源，解决 `plot_periods` 与「8 种周期」的表述冲突**——① `config.py` 新增 `SUPPORTED_PERIODS`（可取数周期全集，8 种）、`PERIOD_TO_MINUTE`（周期→分钟唯一映射）、`DAILY_PERIODS` / `MINUTE_PERIODS`（按数据来源分流）；② `config.CHART_CONFIG['plot_periods']` 明确为**默认批量出图子集**（7 种，**不含 `1min`**），不再是"周期全集"；③ 第 2.3 节与第 1 步的周期约定改为**引用 `SUPPORTED_PERIODS` / `PERIOD_TO_MINUTE`**，禁止在函数内部自建映射表；④ `re_sample_kline()` 位置统一到 `core/utils.py`。
>
> v3.9 更新：**第 2 步与第 1 步对齐修正**——① 路径修正：多周期扩展写在 `core/data_fetcher.py`（原误写 `data/fetcher.py`）；② 接口统一：`get_kline()` 明确定义为对 `get_daily()`/`get_minute()` 的**按周期路由封装**，禁止重复实现取数/复权/缓存；③ **周期字符串全局统一**为 `1d/1w/1M/1min/5min/15min/30min/60min`（与 `config.CHART_CONFIG['plot_periods']` 一致），`get_minute(period=...)` 同步改用带后缀写法；④ 分钟线方案改为引用 1.0 节（BaoStock 长历史 + 自建增量库），删除"AKShare 分钟接口"旧表述；⑤ 第 1 步自检第 4 项由"分钟分页"改为"BaoStock 长历史通道"；⑥ 第 2.1 节批量成分股加**幸存者偏差**提醒（当前成分股≠时点成分股）；⑦ 1.0 节 BaoStock「9 日偏差」由"待确认"**结案为数据源噪声**。
>
> v3.8 更新：**依据第 1 步实测复核，把 BaoStock 相关结论从“待确认”落定为“事实”**——① 复权因子真实字段名是 `dividOperateDate` / `foreAdjustFactor` / `backAdjustFactor`（**不存在 `forwardAdjFactor`**）；字段名不匹配必须**抛错**，严禁退化成“数据源不支持复权”的温和 WARNING（那会把代码 bug 伪装成已知限制）；② 分钟线返回 `date`+`time` **两列**，必须合成唯一 datetime 索引（当日 60 分钟=4 根、15 分钟=16 根、5 分钟=48 根，若塌成 1 根/天即出错）；③ BaoStock **只有盘后数据、无实时行情**，`cn_stock` 分钟线必须按场景分流：**历史回填走 BaoStock、当日/实时走新浪·东财**；④ BaoStock **不覆盖指数、ETF、REITs、可转债、1 分钟线**；⑤ A股**日线与分钟复权因子统一走 BaoStock**（`query_adjust_factor`），避免两源口径不一致导致多周期信号失真；⑥ 自建分钟增量库必须**回填中段缺口**（不能只补末尾，否则失败日会永久留洞）。第 13 步 13.1 新增 **`BaostockSource`** 作为 AKShare 的免费备份源。
>
> v3.7 更新：**修正 1.0 表中最易错的一处**——`ak.stock_zh_a_hist()`（东财历史）成交量经三重实测确认为 **手（必须 ×100）**，此前误标为"股"；同步修正 `fund_etf_hist_em`/`reits_hist_em`（东财系=手）。新增 **「五、分钟线长历史方案」**：新浪/东财分钟线**无游标、无法分页**（A股上限1970、期货外汇1023），改为"A股5/15/30/60走 **BaoStock**（免费长历史、单位=股）+ 其余取最近N根 + 自建增量库"；新浪分钟复权由"存疑"更正为**实测不复权**。`config.py` 同步：`DATA_SOURCE_UNITS` 修正 + 新增 `baostock_daily`/`baostock_minute` + `MINUTE_SOURCE_PRIORITY` / `MINUTE_NO_PAGINATION_SOURCES`；`requirements.txt` 启用 `baostock`。
>
> v3.6 更新：新增 **第 1 步「1.0 数据源单位与复权约定」**——给出各数据源成交量/成交额**原始单位对照表**（含「AKShare 历史接口=股、快照接口=手」「Tushare=手/千元」等最易错点）、对外统一口径、**六条铁律**（禁止自动反推单位、原始价+复权因子分离、期货保留手、可转债 amount 不得补 0、分钟线 1023 分页、新浪分钟线复权存疑）与**单位自检断言**；`config.py` 同步新增 `STANDARD_COLUMNS` / `EXTRA_FLAG_COLUMNS` / `DATA_SOURCE_UNITS` 常量。同时修正第 1 步核心要求中与之一致的条目：取消 ffill（改 NaN + `is_missing`）、缓存改为 raw+因子分离、补齐 `cn_reits` 取数与 `_NO_KLINE_MARKETS` 显式报错。
>
> v3.5 更新：① **修正深市个股被误判为场外基金**——原规则把 00 开头的 6 位代码一律判为 `cn_fund`，导致 `000001`(平安银行)、`000002`(万科A)、`000858`(五粮液)、`002415`(海康威视)、`002594`(比亚迪)、`003816`(中国广核) 等深市主板/中小板个股全部误判；现按号段细分：`000/001/002/003` → `cn_stock`，`004~009` → `cn_fund`，`519` → `cn_fund`；② 3 字母美股白名单拆分为 ETF / 个股两张表，`SPY/QQQ/IWM` 等正确返回 `us_etf`；③ `detect_market_type(code, market_type=None)` 新增可选参数，用于消解 `000001`、`CL` 等天然歧义代码。
> v3.4 更新：① 新增 `config.get_market_config()` 统一市场参数访问函数，18类市场全覆盖，消除直接访问 `MARKETS[...]` 的KeyError隐患；② 修正2~3位纯字母短代码默认兜底为`us_stock`（原默认国际期货易将PG/IVV等误判为期货）；③ 新增全局铁律，所有步骤统一取用市场规则的方式。

## 覆盖范围（共 19 类：18 类可交易/可研究市场 + 指数）
- **零售层（13 类，普通账户可直接参与）**：A股个股、A股场内ETF、美股个股、美股ETF、港股个股/ETF、沪深可转债、国内期货、国际期货、外汇保证金、场内期权、加密货币、场外公募基金、国债逆回购
- **合格投资者层（5 类，需满足资产/收入门槛）**：私募证券基金、券商资管/信托/私募理财、新三板、公募REITs、场外衍生品定价模拟（⚠️ 个人禁止实盘，仅学习）
- **基准层（1 类，不可直接交易）**：**指数（`cn_index`）**——仅用于回测基准、择时信号、宽基/行业强弱对比；`CN_INDEX['tradeable']=False`，**订单层必须拒绝指数下单**
- **机构层专属**（不在本系统范围内，个人投资者基本无法直接参与）：银行间债券、场外衍生品实盘通道、非标、ABS、一级市场股权

## 使用方式
1. **一次只复制一段**：本文档用 `=====` 分隔每一步，复制完整一段给 Trae，等它写完代码、跑通测试后，再复制下一段。**不要一次性全部粘贴**，否则会乱。
2. **建议顺序**：第 0~9 步（零售层基础）→ 第 10 步（合格投资者层）→ 第 11 步（CLI 入口整合）→ 第 12 步（实盘接入层）→ 第 13 步（数据与报告长期可用性）。
3. **前置文件**：开始前把 `config.py`、`requirements.txt`、`.env.example`、`.gitignore` 四个文件放到项目根目录。
4. **凭证**：把 `.env.example` 复制为 `.env`（`cp .env.example .env`），回测/模拟盘阶段可全部留空；填了真实凭证的 `.env` 永不提交。
5. **中断可恢复**：第 0 步会生成 `progress.json` 与 `README.md` 进度看板；重新打开项目先运行 `python check_progress.py`，即可知道做到哪一步、下一步复制哪段。
6. **⚠️ 全局铁律（必须遵守，贯穿所有步骤）**：
   - 取市场交易规则参数时，**必须统一调用 `config.get_market_config(market_type)`**；
   - **禁止直接写 `config.MARKETS[market_type]`**——`MARKETS` 字典只包含7个零售市场（cn_stock/cn_etf/us_stock/us_etf/hk_stock/cn_convertible/cn_future），其余11类市场（global_future/forex/cn_option/crypto/cn_fund/cn_reverse_repo/cn_reits/neeq/private_fund/qii_product/otc_deriv）定义在独立字典中，直接访问会触发 `KeyError`；
   - `detect_market_type()` 返回的所有19个市场类型（含 `cn_index`），`get_market_config()` 都能正确返回对应参数字典，无需做特殊分支处理；
   - 纯字母短代码（2~3位）未在白名单中时默认判定为`us_stock`，如需识别国际期货/外汇/加密品种，请显式传入 `market_type` 参数覆盖。

---

## ===== 第 0 步：环境与项目骨架搭建 =====

请在当前空项目目录下完成以下事情：

1. **检查并创建目录结构**，确保以下目录都存在：
   - `data_cache/` 数据缓存（其下还会自动生成 `factors/`、`snapshots/`、`raw/`、`adj_factors/`、`index_members/`、`constituents/` 子目录）
   - `logs/` 日志
   - `backtest_results/` 回测结果与图表（对应 config 的 `BACKTEST_DIR`）
   - `reports/` 自动复盘报告与报告索引（对应 config 的 `REPORT_DIR`）
   - `paper_trading/` 模拟盘运行数据（对应 config 的 `PAPER_DIR`）
   - `live_trading/` 实盘运行数据（对应 config 的 `LIVE_DIR`，实盘成交/持仓快照落盘于此）
   - `audit_logs/` 实盘合规审计日志（对应 config 的 `AUDIT_DIR`，已被 `.gitignore` 屏蔽，不提交）
   - `strategies/` 用户策略目录（你自己写的每个策略一个 .py 文件）
   - `configs/strategies/` 策略参数配置文件目录（每个策略一个 yaml）
   - `research/` 策略研究模块（参数优化 / 走向前分析 / 稳健性验证 / 实验记录）
   - `tools/` 辅助工具（策略脚手架、上线检查清单等）
   - `tests/` 策略与研究相关的测试脚本
   - `core/` 核心模块目录
   - `factor/` 因子研究模块（表达式引擎 / Alpha101 / Alpha191 / 评估 / 合成 / 适配器 / 自定义因子）
   - `broker/` 券商与期货实盘适配器目录（QMT / PTrade / CTP，第12步填充）
   - `risk/` 实盘风控模块目录（第12步填充）
   - `live/` 实盘代码模块目录（执行器 / 守护 / 告警 / 对账 / 日志模块代码，第12步填充；运行数据落 `live_trading/`、审计日志落 `audit_logs/`，注意区分）
   - `nav_backtest/` 合格投资者层净值型回测目录（第10步填充）
   - `derivatives_pricing/` 场外衍生品定价模拟目录（第10步填充）
   - `research_output/` 因子与研究报告输出目录（因子评估报告、优化热力图等落盘于此）
   - 说明：后面步骤还会按需创建二级目录（如 `factor/adapters/`、`factor/market/`），本步先把一级骨架建好即可

2. **创建文件 `core/__init__.py`**，空文件即可。

3. **生成 `core/utils.py` 工具模块**，包含以下工具函数：
   - `setup_logger(name, log_file)`：配置日志，同时输出到控制台和文件，带时间戳和级别。
   - `retry_request(func, max_retry, delay)`：通用重试装饰器，对网络请求自动重试，捕获异常并等待递增延迟。
   - `is_trading_day(date, market)`：判断是否为交易日（用 chinesecalendar 判断 A 股；美股用自定义节假日表；港股/A股共享中国节假日但加上港股节假日；外汇24h交易周一到周五；加密货币7×24）。
   - `get_trading_sessions(market, date)`：返回指定市场指定日期的交易时段列表（处理夜盘、美股夏令时/冬令时、外汇时段）。
   - `format_number(num, decimals=2)`：数字格式化，大数字用万/亿/万亿表示。
   - `cal_natural_days(start, end)`：计算两个日期之间的自然日（用于国债逆回购计息、基金持有期）。

4. **创建 `main.py` 入口文件**，先只写一个打印欢迎信息的 main 函数，输出系统版本（v3.6 全市场+合格投资者层+行情K线缠论+因子研究+实盘接入+凭证安全+数据长期可用）和支持的市场列表。

5. **安装依赖**：提示用户执行 `pip install -r requirements.txt`，并打印核心依赖版本（pandas/numpy/akshare）。

6. **写一个 `test_env.py` 测试脚本**，依次验证：
   - import pandas/numpy/akshare 正常
   - 目录都存在且可写
   - config.py 加载正常，打印所有支持的市场类型
   - detect_market_type() 函数对以下测试用例返回正确结果：
     - `600519` → cn_stock（沪市个股）
     - `000001` → cn_stock（深市个股，平安银行）★ 重点验证项，防止被误判为场外基金
     - `002415` → cn_stock（深市中小板，海康威视）★
     - `003816` → cn_stock（深市主板，中国广核）★
     - `510300` → cn_etf
     - `123045` → cn_convertible
     - `00700`（5位）→ hk_stock
     - `AAPL` → us_stock
     - `204001` → cn_reverse_repo（国债逆回购）
     - `rb2501` → cn_future
     - `GC` → global_future（国际期货）
     - `BTC` → crypto
     - `EURUSD` → forex
     - `161725` → cn_fund（场外公募基金，16开头LOF）
     - `005827` → cn_fund（场外公募基金，004~009号段）
     - `detect_market_type("000001", market_type="cn_fund")` → cn_fund（显式传参消解歧义）
     - `508000` → cn_reits
     - `430047` → neeq
     - `SPY` → us_etf
     - `10004567`（期权代码8位）→ cn_option
     说明：私募/资管/场外衍生品等非标准代码产品，使用时直接在策略里显式传入 market_type 参数即可，不依赖自动识别。
   运行脚本，确保所有识别正确后再继续下一步。

7. **初始化进度跟踪系统**（很重要，用于中断后恢复搭建）：
   - 创建 `progress.json`，结构如下（`steps` 覆盖第 0~13 步共 14 个步骤，初始第 0 步为"进行中"，其余为"未开始"）：
     ```json
     {
       "project": "多市场量化交易系统",
       "version": "v3.6",
       "last_update": "",
       "next_step": 1,
       "steps": [
         {"id": 0, "name": "环境与项目骨架", "status": "进行中", "start": "", "done": "", "note": ""},
         {"id": 1, "name": "统一数据层", "status": "未开始", "start": "", "done": "", "note": ""},
         {"id": 2, "name": "行情批量下载导出+K线图绘制（含多周期/形态/缠论/多标的对比）", "status": "未开始", "start": "", "done": "", "note": ""},
         {"id": 3, "name": "技术指标计算", "status": "未开始", "start": "", "done": "", "note": ""},
         {"id": 4, "name": "统一账户与订单管理", "status": "未开始", "start": "", "done": "", "note": ""},
         {"id": 5, "name": "策略基类+因子研究+公开策略接入+自定义因子", "status": "未开始", "start": "", "done": "", "note": ""},
         {"id": 6, "name": "全市场回测引擎", "status": "未开始", "start": "", "done": "", "note": ""},
         {"id": 7, "name": "模拟盘交易", "status": "未开始", "start": "", "done": "", "note": ""},
         {"id": 8, "name": "定时盯盘与消息推送", "status": "未开始", "start": "", "done": "", "note": ""},
         {"id": 9, "name": "自动复盘报告", "status": "未开始", "start": "", "done": "", "note": ""},
         {"id": 10, "name": "合格投资者层净值回测+衍生品定价", "status": "未开始", "start": "", "done": "", "note": ""},
         {"id": 11, "name": "一键运行入口+README+测试框架", "status": "未开始", "start": "", "done": "", "note": ""},
         {"id": 12, "name": "实盘接入层（QMT/PTrade/CTP+风控+守护+对账+告警+凭证安全）", "status": "未开始", "start": "", "done": "", "note": ""},
         {"id": 13, "name": "数据与报告长期可用性（多源/原始价/快照/时点成分股/归档）", "status": "未开始", "start": "", "done": "", "note": ""}
       ]
     }
     ```
     `status` 取值固定为四种：`未开始` / `进行中` / `已完成` / `有问题`。
   - 创建 `check_progress.py`：运行后读取 `progress.json`，在终端打印进度看板（✅已完成 / 🔄进行中 / ⬜未开始 / ❌有问题），显示整体完成百分比（已完成步骤数 ÷ 总步骤数）和"下一步建议（该复制哪段指令）"。
   - 创建 `README.md` 初始骨架，**最顶部放「搭建进度看板」表格**（列：步骤、名称、状态、完成时间、备注），下方预留「项目介绍 / 目录结构 / 运行方法 / 常见问题」等章节，留待后续逐步填充。
   - **全局强制规则（从本步起，每一步都必须遵守）**：每完成一段指令后，**必须同步更新 `progress.json` 和 `README.md`**——把本步改为"已完成"并写入完成时间，把下一步改为"进行中"，更新 `next_step`；若本步存在未解决的报错或警告，标记为"有问题"，并在 `note` 和 `issues` 里写清问题及下一步怎么处理。
   - **中断恢复流程**（也写进 README 开头）：重新打开项目时，先运行 `python check_progress.py` 查看做到哪一步，再复制 README"下一步建议"对应的指令继续搭建。

---

## ===== 第 1 步：统一数据层（19类市场全支持）=====

请创建 `core/data_fetcher.py`，这是整个系统的数据入口，所有市场的数据都从这里获取，对外提供统一的接口，**上层策略不需要关心底层是哪个市场的接口**。

---

### 1.0 【先看这个】数据源单位与复权约定（本步最容易出错、且不会报错的地方）

> ⚠️ **这一节是本步的地基，请先读完再写代码。** 成交量单位搞错、复权口径混用，程序**都不会报错**，但会让后面所有回测结果整体偏掉（典型是偏 100 倍、或历史段与新增段出现看不见的断层）。请把下面两张表**原样抄进 `core/data_fetcher.py` 顶部注释**，并在 `config.py` 里落成常量（`STANDARD_COLUMNS` / `DATA_SOURCE_UNITS`）。

#### 一、各数据源「原始单位」对照表（按此硬编码，严禁靠猜）

| 数据源接口 | 用途 | volume 原始单位 | amount 原始单位 | 换算到标准单位 | 原生复权口径 | 单次条数上限 |
|---|---|---|---|---|---|---|
| `ak.stock_zh_a_hist()` | A股日线（东财） | **手** | 元 | **×100** | 不复权（可传参） | 无 |
| `ak.stock_zh_a_daily()` | A股日线（新浪备用） | **股** | 元 | ×1 | 不复权 | 无 |
| `ak.stock_zh_a_spot_em()` | A股实时快照 | **手** | 元 | **×100** | — | 无 |
| `ak.fund_etf_hist_em()` | ETF日线（东财） | **手**（以官方文档为准） | 元 | ×100 | 不复权 | 无 |
| `ak.fund_etf_hist_sina()` | ETF日线（新浪备用） | 份 | 元 | ×1 | 不复权（**不支持复权**） | 无 |
| `ak.reits_hist_em()` | REITs日线 | **手**（待官方确认） | 元 | ×100 | 不复权 | 无 |
| `ak.stock_hk_hist()` / `stock_hk_spot_em()` | 港股 | 股 | 港元 | ×1 | 不复权 | 无 |
| `ak.stock_us_hist()` / `stock_us_spot_em()` | 美股 | 股 | 美元 | ×1 | 不复权 | 无 |
| `ak.bond_zh_hs_cov_daily()` | 可转债日线 | **张** | **无此字段** | ×1 | 不复权 | 无 |
| `ak.futures_main_sina()` | 国内期货主力 | **手** | **无此字段** | **×1（保留手）** | — | 无 |
| `ak.futures_zh_minute_sina()` | 期货分钟 | 手 | 无 | ×1（保留手） | — | 无 |
| `ak.option_sse_daily()` | ETF期权日线 | 张 | 元 | ×1 | — | 无 |
| `ak.fund_open_fund_info_em()` | 场外基金净值 | 无 | 无 | — | 累计净值 | 无 |
| 新浪 `hq.sinajs.cn` | A股实时 | **股**（字段8） | 元（字段9） | ×1 | — | 无 |
| 新浪 `CN_MarketData.getKLineData` | A股/期货/外汇分钟 | 股 | 元 | ×1 | **实测=不复权** | **A股1970 / 期货·外汇1023** |
| **BaoStock** `query_history_k_data_plus()` | A股日线+5/15/30/60分钟 | **股** | 元 | ×1 | 可选（`adjustflag` 3/2/1） | 无 |
| Binance klines | 加密货币 | 币 | 计价货币 | ×1 | — | 1000 |
| Tushare `daily()`（若启用） | A股日线 | **手** | **千元** | **×100 / ×1000** | 不复权 | 无 |

> **记住这句话（本表最容易错的一处，已实测更正）**：`ak.stock_zh_a_hist()`（东财历史）的成交量是 **手（必须 ×100）**，不是"股"。验证方式有三条互相印证：① 同一天 `stock_zh_a_hist` 与 `stock_zh_a_daily`（新浪）的成交量**恰为 ×100 关系**；② AKShare 官方文档示例中 `volume × 100 × close ≈ amount`；③ 接口自带 `amount / (close × volume) ≈ 99.7`。
> 结论：**东财系历史接口（`stock_zh_a_hist` / `fund_etf_hist_em` / `reits_hist_em`）成交量=手，统一 ×100；新浪系（`stock_zh_a_daily`）成交量=股，不换算；BaoStock 官方文档明确=股。**

#### 二、对外强制统一口径

| 项 | 统一标准 |
|---|---|
| `volume` | A股/ETF/基金/港股/美股 = **股(份)**；可转债 = **张**；期货 = **手（保留，不换算）**；加密 = **币**；**指数 = 手（★全局唯一例外；已验证：新浪指数源=股、须 ÷100 转手，见铁律 7）** |
| `amount` | **元 / 港元 / 美元**（原币种，不做汇率换算）；期货与无成交额接口为 **NaN** |
| 复权 | 对外 `adjust` 参数支持 `'qfq'` / `'hfq'` / `''`(不复权)，**默认 `'qfq'`** |
| 列名 | `STANDARD_COLUMNS = ['open','high','low','close','volume','amount']` + 标记列 `is_suspended` / `is_missing` |
| 附加信息 | 一律写入 `DataFrame.attrs`：`source` / `adjust` / `volume_unit` / `amount_estimated` / `unit_uncertain` |

#### 三、七条铁律（写进代码注释）

1. **禁止"自动反推"单位**。必须按接口硬编码映射；确属无法确定的接口，在 `attrs` 里标 `unit_uncertain=True`，**不得静默猜测**。
2. **复权必须「原始价 + 复权因子」分离存储**。`data_cache/raw/` 存不复权原始价、`data_cache/adj_factors/` 存因子，复权价 = 原始价 × 因子**现算**。**严禁缓存"已复权价"再做增量拼接**（前复权价会随每次除权整体重算，拼接必出静默断层）。增量更新时因子**整段重算**。
3. **hfq 因子以最早日为基准归一**（`factor / factor.iloc[0]`），否则 hfq ≡ qfq。
4. **期货保留"手"**：在 `attrs` 标注 `volume_unit="手"`，并在注释里写明**期货的 `amount ≈ close × volume` 不成立**、流动性过滤需单独取成交额。
5. **可转债的 `amount` 不得补 0**（会被流动性过滤全量剔除），应改为 `amount = close × volume` 估算并标 `amount_estimated=True`。
6. **分钟线长历史不能靠"分页"**：新浪/东财分钟线**没有时间游标、物理上无法分页**，只能取"最近 N 根"（新浪 A股 1970、期货/外汇 1023；东财约 1 个月）。超过上限必须写 `minute_history_capped=True` + `minute_available_from` 并告警，**不得静默截断**。A股 5/15/30/60 分钟的长历史请走 **BaoStock**（免费、官方明确单位=股）。详见本节「五、分钟线长历史方案」。
7. **指数成交量单位必须“跨源交叉验证”，不得用比值自检**。指数**不适用** `amount/(close×volume)`（指数点位 × 股数无换算关系，比值必然离谱，不是单位错）。新浪指数日线**不含成交额**（`amount=NaN`）无法自校，只能用 **BaoStock 指数日线**（官方字段**同时返回 `volume` 与 `amount`**，实测 `amount/(close×volume)≈1.0`，可确认其为“股/元”）与新浪**同指数、同一天**的 volume 比对：**比值 ≈ 1 → 新浪指数 volume 也是「股」**（须 ÷100 转「手」）；**比值 ≈ 100 → 新浪指数 volume 本身就是「手」**（**禁止再 ÷100**，否则偏小 100 倍）。指数对外统一单位为**「手」**（全局唯一例外）。
   > ✅ **已验证通过（第 2 步收尾结案）**：以 BaoStock 指数日线（官方字段同时含 `volume`/`amount`）与新浪**同指数同日** volume 交叉比对——`sh.000300` BaoStock=新浪=`16,868,847,400` 股，**比值 1.0000**；`sh.000001` **比值 1.0000**；`sz.399001` **比值 0.9991**（源修订差异，0.09%）。BaoStock 侧自检 `amount/volume = 22.71 元/股`（成分股均价量级，合理）。**结论：新浪指数 volume = 「股」、÷100 转「手」正确**；`stock_zh_index_daily` / `baostock_index_daily` 升级为 `verified=True`（东财指数因本机不可达仍 `verified=False`）。

#### 四、单位自检（写进 `test_data.py`，必做）

对 A股(600519)、ETF(510300)、可转债(113052) 各取最近一个交易日，断言：

```python
ratio = amount / (close * volume)
assert 0.9 < ratio < 1.1   # 按成交均价成交，偏差应 <10%
```

若比值落在 **100 或 1000 附近**，就是单位没换算；若 `close` 与行情软件对不上（差一个复权基准），就是复权口径错了。**这两条必须打印实测比值，不能只写"通过"。**

#### 五、分钟线长历史方案（免费源取不到 3 年，别再纠结"分页"）

**结论先行**：新浪 / 东财分钟线在免费源上**取不到长历史**——只提供"最近 N 根"，且**没有 `end_date` / 时间游标**，物理上无法分页：
- 新浪 `getKLineData`：A股上限 **1970 根**、期货/外汇 **1023 根**（实测期货 60 分钟恰好卡在 1023，即被静默截断）
- 东财分钟：约 **1 个月**
- 所以：**放弃"给新浪分钟分页"这个方向**，改用下面三层。

| 层 | 覆盖范围 | 数据源 | 说明 |
|---|---|---|---|
| ① 长历史主力 | A股个股 5/15/30/60 分钟 | **BaoStock** | 免费、1990 年起、官方明确 volume=**股**、支持前/后复权（`adjustflag` 3/2/1）；**分钟线不含指数** |
| ② 近期 / 无 baostock 覆盖 | 期货、外汇、ETF、1 分钟 | 新浪 / 东财 | 只能取"最近 N 根"；超出必须写 `minute_history_capped=True` + `minute_available_from` 并 WARNING |
| ③ 自建增量库 | 所有需要长历史分钟线的品种 | 本地累积 | 每交易日收盘后把当日分钟线追加到 `data_cache/minute/{market}_{symbol}_{period}.parquet`，日积月累形成长历史（与第 13 步共用同一套落库） |

**自建增量库规则（写进 `core/data_fetcher.py`）：**
1. `get_minute()` 先读本地累积文件 → 取最后一根时间戳 → 只向数据源请求"最近 N 根" → 与本地合并、按时间戳去重、排序后覆盖写回
2. 首次回填尽可能多（BaoStock 可一次拉多年；新浪/东财只能拿最近上限）
3. 落库前做质量检查（去重、排序、OHLC 合法性）
4. `attrs` 必须回报 `available_from` 与 `minute_history_capped`
5. 期货/外汇无免费长历史分钟源 → 靠自建库累积；如需即时长历史，留到第 13 步接付费源（Tushare Pro 分钟需较高积分）

> **A股分钟复权**：BaoStock 可直接返回前/后复权分钟线，也可取不复权 + `query_adjust_factor()` 本地算；为与"raw + 因子分离"架构一致，**优先取不复权 + 因子**。新浪分钟线**实测为不复权**，可直接作 raw 源。

#### 六、BaoStock 实测结论（第 1 步复核已确认，请原样写进代码注释）

> 这几条都是**实测确认过的事实**，不是推测；后续第 2/3/6/13 步用到 BaoStock 时直接照此实现，不要重新猜。

1. **复权因子字段名**：`query_adjust_factor()` 返回 `dividOperateDate` / `foreAdjustFactor` / `backAdjustFactor`；**没有 `forwardAdjFactor`**（网上有说法写错）。取因子时若列名不匹配或返回空，**必须抛错或标 `minute_factor_available=False` + 具体原因**，**严禁**退化成"因子恒为 1 → 标 `adjust='none'`"——那会把"字段名写错"这个真 bug 伪装成"数据源不支持复权"。
2. **分钟线是 `date` + `time` 两列**：必须把 `time`（17 位，取前 14 位）与 `date` 合成唯一 datetime 索引。校验断言：某只股票某日 60 分钟线必须 **4 根**（10:30/11:30/14:00/15:00）、15 分钟 16 根、5 分钟 48 根，跨日严格递增；**若塌成 1 根/天，就是只用了 `date` 做索引**。
3. **仅盘后、无实时**：BaoStock 只在收盘后提供数据，**拿不到当天盘中分钟线**。因此分钟线源必须按场景分流：**`start_date` 早于今天的"历史回填"段 → BaoStock；含今天/盘中的"当日"段 → 新浪/东财**。若盘中取不到当日分钟线，要显式 WARNING，不能静默返回昨天。
4. **覆盖边界**：BaoStock **不覆盖指数、ETF、REITs、可转债、1 分钟线**（分钟线只覆盖 A股个股的 5/15/30/60）。这些品种的分钟线仍走新浪/东财，受 1970/1023 上限约束。
5. **复权因子同源**：A股**日线与分钟必须用同一套复权因子**（统一取 BaoStock `query_adjust_factor`）。若日线因子来自 AKShare、分钟因子来自 BaoStock，两源口径不同 → **同一时刻日线 qfq 收盘价 ≠ 分钟 qfq 收盘价**，第 2.3 节的"日线+60分钟共振"信号就是假的。校验断言：当日 15:00 的 60 分钟 qfq 收盘价，必须等于当日日线 qfq 收盘价。
   > ✅ **已知残差（已复核结案，非 bug）**：实测 725 个交易日中有 9 日偏差 >0.1%，最大 0.2535%，**已定性为数据源噪声**。三条证据：① 9 日中 8 日距最近除权日 **28~154 天**（随机散布），唯一落在除权日当天的 2025-12-19 偏差仅 0.1184%；② 5 个除权日的 `raw × foreAdjustFactor` 与官方 qfq **完全相等（差 0）**，raw/qfq 两口径逐日差 ~1e-14，不存在 off-by-one；③ 偏差日的分钟成交量**系统性偏少**，原因是 BaoStock 分钟线**不含尾盘集合竞价/最新一笔成交**。结论：**0.25% 量级对日频回测可忽略；日内高频需留意**。第 2.3 节做跨周期共振时，应以**日线收盘价为基准对齐**，规避该残差。
6. **自建增量库必须回填中段缺口**：只"取末根时间戳→补最近一段"会让某天失败留下的空洞**永远填不上**。应比对交易日历（用该标的日线索引，可天然排除停牌日），找出缺失日期段一并回填；无法回填时写 `gap_dates` / `gap_count` 并 WARNING，禁止静默留洞。
7. **crypto 回填限速**：币安 K 线单次上限 1000，单次回填 20000 根 = 约 20 次请求，必须加请求间隔（≥0.2s）并标注单次回填上限，避免触发封禁。
8. **指数取数必须走专用接口**：`detect_market_type()` 对 `sh000001` / `sh000300` / `sz399001` 等返回 `cn_index`。指数取数**禁止复用个股/期货接口**，数据源为 `ak.index_zh_a_hist()`（东财日线）、`ak.stock_zh_index_daily()`（新浪日线/长历史）、`ak.index_zh_a_hist_min_em()`（东财分钟）；BaoStock 日线支持指数（`sh.000300` / `sz.399001`）但**分钟线不含指数**。指数 `volume`/`amount` 须按 1.0 表核对单位。**指数不可直接交易**（`CN_INDEX['tradeable']=False`），仅用于基准与择时。**⚠️ 代码写法**：带前缀（`sh000300` / `sz399001`）可稳定识别为 `cn_index`；裸 6 位中 `399xxx`（深证系列）与 `932xxx`（中证2000）**已可直接识别**，但 **`000xxx` 段（`000300` / `000905` / `000852` / `000016` / `000688`）与深市个股号段重合，仍会被判为 `cn_stock`**——取指数行情**必须写带前缀形式**（`sh000300`）。

#### 七、数据源可用性与故障切换（第 2 步实测；第 13 步据此补源）

> **这是「活」的现状、不是设计表**：数据源可达性会随网络环境变化。架构上**必须能自动探测 + 切换**，不能假设某个源永远可用。

**实测 8 个后端（本机）**：东财 `push2his` ❌ 持续 `RemoteDisconnected`；新浪（A股/期权/期货/外汇）✅、BaoStock ✅、腾讯 ✅、币安 ✅。

| 市场 | 当前实际源 | 东财不可达时的影响 |
|---|---|---|
| `cn_stock` / `cn_etf` / `cn_reits` / `cn_index` / `hk_stock` / `us_stock` / `us_etf` | 走新浪回退（东财主源不可达） | 尚可（有新浪备源） |
| `cn_convertible` / `cn_option` / `cn_future` / `global_future` | 只能新浪系（**无东财备源**） | 尚可（本就走新浪） |
| **`forex` / `cn_fund` / `cn_reverse_repo`** | **仅东财** | ⚠️ **东财挂即完全取不到**（单点故障） |
| **`cn_convertible` / `us_stock` / `us_etf` / `hk_stock` 的分钟线** | **仅东财** | ⚠️ **东财挂即分钟线全空** |
| `crypto` | 币安（独立于东财/新浪） | 不受影响 |

**据此对第 13 步的要求**：单点故障市场（`forex` / `cn_fund` / `cn_reverse_repo` 的日线；`cn_convertible` / `us_stock` / `us_etf` / `hk_stock` 的分钟线）**优先级最高**，必须优先补第二数据源——不是「加个切换逻辑」就够了，**只有单源的品种，切换也无从切换**。

**落地要求**：`tools/source_status.py` 打印上述连通性矩阵（哪个源当前可用、各市场实际走哪个源、哪些走了回退），供随时自查。

**数据时效（stale）约定（第 2 步收尾新增）**：数据源不可达时，**若无本地库必须显式报错、不得返回空表**；**若有本地库，可返回缓存数据，但必须标 `attrs["stale"]=True` 与 `attrs["stale_days"]=N` 并打 WARNING**——禁止静默使用过期数据。使用边界如下：

| 场景 | 是否允许用 stale 数据 |
|---|---|
| 回测 / 研究 / 因子计算 | ✅ 允许（历史数据本就固定） |
| 图表展示 | ✅ 允许，但图上须标注「数据截至 X 日」 |
| **模拟盘 / 实盘的下单决策** | ❌ **禁止**——必须报错或拒单，防止用过期价格成交 |

**stale 上限**：日线超过 **5 个交易日**、分钟线超过 **2 个交易日** 未更新，视为不可用，直接报错（不再返回 stale 数据；引用 `config.STALE_LIMIT`，禁止就地写死）。

**🔴 双重防线（下单链路必须独立校验，不依赖上游传参）**：数据层的 `for_trading=True` 是**「默认放行」（fail-open）**式保护——只要纸面/实盘模块**忘记传**这个参数，过期数据就会静默流入下单链路。**上游少传一个参数是迟早会发生的事，不能靠约定保护实盘。** 因此：

1. **第一道防线**（数据层）：`get_daily/get_minute(..., for_trading=True)` 遇 stale 抛错；
2. **第二道防线**（下单链路，第 4 步落地）：订单模块在**每次下单前独立复核**数据时效，引用 `config.TRADING_REQUIRE_FRESH`（默认 `True`）——**不读取、也不信任上游传来的任何 stale 标记，自己在用数那一刻重新校验**，不通过直接拒单。
   ⚠️ **仅对模拟盘/实盘生效；回测模式必须豁免**——回测按定义就是"用历史数据跑过去"，数据相对"今天"永远是过期的，若闸门无条件生效会**把所有回测直接拒掉**。因此闸门须按运行模式开关（`RUN_MODE`）：`backtest` 豁免、`paper`/`live` 强制。
   > 验收判据：**把数据层的 `for_trading` 全部去掉，下单链路仍然拦得住 stale 数据**，才算合格。

**⚠️ `DataFrame.attrs` 会因窗口运算丢失（已实测，pandas 2.3.3）**：实测结论——`concat` / `merge` / `groupby` / `resample().agg()` / `diff` / `pct_change` / `cumsum` / `astype` / 布尔索引 **均保留** attrs；但 **`rolling()` / `ewm()` / `expanding()` 这三类窗口运算会把 attrs 清空（返回 `{}`）**，`to_numpy()` 后重建同样丢失。**而这三类恰好是技术指标（MA/EMA/MACD/RSI/BOLL/ATR）与因子计算的核心手段**——一旦指标帧丢了 attrs，`stale` 会**静默变回「新鲜」**，而下游（策略/下单）看不到任何异常。要求：① 在 `get_daily` / `get_minute` / `get_kline` 等**关键出口统一重新挂载** attrs；② **禁止仅凭 `attrs['stale']` 做交易决策**——指标的中间帧不可信，必须在**用数那一刻**由下单链路独立重新校验（这正是第二道防线必须「独立」的原因）；③ 指标/因子函数无必要不要试图透传 attrs，改为在入口处判定时效。

**🔴 fail-closed 的适用边界（防止「过度保护」导致实盘全面拒单）**：`rolling`/`ewm`/`expanding` 会清空 `attrs`，而**实盘策略一定是算完指标才下单的**（MA 金叉、MACD 背离、ATR 止损都基于窗口运算）。因此时效闸门若写成「**读不到 `attrs` 就 fail-closed**」，后果是——**任何经过指标计算的数据，在下单时都会被判「无法确认时效」而拒单，实盘每一笔都下不出去**。这不是安全，是把系统锁死。
> 正解：时效信息必须**脱离易失的 `attrs`**，二者择一——
> 1. **物化为普通列**（`config.STALE_INFO_COLUMN`，默认 `data_asof_date`）：列会随 DataFrame 一起穿过 `rolling`/`ewm`/`resample`/`concat`，不会被清空；
> 2. **下单链路独立重新取数**复核（`config.STALE_CHECK_MODE="refetch"`，推荐）——不信任上游任何帧，从数据层重新拉「该标的当前最新数据」比对交易日历。
>
> `fail-closed` 只允许用在「**既取不到时效列、又无法重取**」的兜底场景，**不得作为唯一防线**。

**⚠️ 时效复核 v2（物化列在真实链路会失效——下单以 `refetch` 为主）**：
1. **架构事实**：本系统指标库是**纯函数**（只吃 `Series`/`DataFrame`、返回 `Series`/`DataFrame`，见第 3 步）——策略把各指标 `Series` 拼成决策帧时，**`data_asof_date` 列不会自动带过去**，故「读物化列」对策略决策帧常常为空。
2. 因此**下单链路的时效复核必须以 `refetch` 为主**——按 `market + symbol` 从数据层重取「该标的当前最新数据」比对交易日历，**完全不依赖传入帧的任何列/attrs**；物化列只用于数据层出口帧或单标的快速判断。**禁止**把「决策帧无列」当成 fail-closed 的理由。
3. **数据层出口写列的日期，必须是该帧自身最后一根 bar 的实际日期**，**绝不是「取数时刻 / 今天」**——**缓存命中、失败回退**两个出口尤其如此：若按「现在」填充，缓存里的旧数据会被标成新鲜，**防线恰好在最常见路径上失守**（`get_daily`/`get_minute`/`get_kline` 三个出口都要覆盖）。
4. **多标的帧须按 `symbol` 分组**填各自最新日期，**禁止把「整帧最大日期」广播到所有行**——否则一个新鲜标的会掩盖同帧内的过期标的。
5. **`refetch` 失败（网络故障 / 源不可达）按风险优先处置**（`config.STALE_REFETCH_FAIL_POLICY`）：**开仓从严（拒单）、平仓从宽（放行）**——避免因网络抖动无法止损/平仓。同一下单批次内 `refetch` 结果可复用（`config.STALE_REFETCH_TTL_SEC`，默认 60 秒），避免逐单重取打满接口。

**⚠️ 交易日判定必须按市场**：`_latest_completed_trading_day()` 依赖市场收盘时刻，必须**逐市场取用**（A股/港股/美股收盘时刻不同、期货含夜盘、外汇近 24 小时、加密 7×24）——**不能只用 A股一套时钟**，否则跨市场会误判 stale。


---

### 核心要求：
1. **类名：`DataFetcher`**，初始化时接收 `cache_dir` 参数，自动创建缓存目录。所有数据优先读本地缓存（CSV+parquet），没有或过期才调用接口，并自动缓存到本地，带请求延时和重试。

2. **统一对外方法**（返回值的单位与复权口径必须严格遵守 1.0 节，19 类市场一致）：
   - `get_daily(symbol, start_date=None, end_date=None, adjust='qfq', fill_missing=False) -> pd.DataFrame`
     返回统一列名 `['open','high','low','close','volume','amount']`（引用 `config.STANDARD_COLUMNS`），`date` 设为 datetime 索引、升序去重；另含标记列 `is_suspended` / `is_missing`（`config.EXTRA_FLAG_COLUMNS`）。
     `volume` 统一为 股/份/张（期货保留"手"）；`amount` 统一为 元/港元/美元 原币种，**无成交额时填 NaN，严禁补 0**。
   - `get_minute(symbol, period, start_date, end_date) -> pd.DataFrame`
     同样返回标准化列。**`period` 写法全项目统一**为带后缀字符串：`'1min' / '5min' / '15min' / '30min' / '60min'`，以 **`config.SUPPORTED_PERIODS`** 为唯一标准；周期→分钟映射引用 **`config.PERIOD_TO_MINUTE`**，**不要出现 `1` / `60` 这类纯数字写法**（第 2 步的 `get_kline` 用同一套；`plot_periods` 只是「默认出图子集」，与周期全集不是一回事，勿混用）。**分钟线无法分页**（见 1.0 铁律 6 与「五、分钟线长历史方案」）：A股个股 1/5/15/30/60 分钟优先走 **BaoStock** 取长历史（BaoStock 无 1min，1min 走新浪/东财），其余品种走新浪/东财取最近 N 根并落本地增量库；超出上限时必须标注 `minute_history_capped` 与 `minute_available_from`，禁止静默截断。
   - `get_realtime(symbol) -> dict`
     返回最新价、涨跌幅、成交量、买卖价等实时快照（单位同样按 1.0 归一）。
   - `get_symbol_list(market_type) -> pd.DataFrame`
     返回指定市场的全部标的列表（代码+名称）；结果落 `data_cache/lists/` 缓存 7 天。

3. **内部市场路由**：
   在 get_daily/get_minute/get_realtime 内部，先用 `detect_market_type(symbol)` 识别市场类型，然后分发到对应的私有取数方法：
   - `_fetch_cn_stock_daily()` → 调用 `ak.stock_zh_a_hist()`（**成交量=手，必须 ×100**）；分钟线 `_fetch_cn_stock_minute()` 优先走 BaoStock（长历史），失败回退新浪/东财
   - `_fetch_cn_etf_daily()` → 调用 `ak.fund_etf_hist_em()`
   - `_fetch_us_stock_daily()` → 调用 `ak.stock_us_hist()`，自动处理美股代码后缀
   - `_fetch_hk_stock_daily()` → 调用 `ak.stock_hk_hist()`，自动补前导0
   - `_fetch_cn_cb_daily()` → 调用 `ak.bond_zh_hs_cov_daily()`，分钟用 `bond_zh_hs_cov_min()`；成交额缺失时用 close×volume 估算并标 `amount_estimated`（见 1.0 铁律 5）
   - `_fetch_cn_futures_daily()` → 调用 `ak.futures_main_sina()`（主力连续合约），分钟用 `futures_zh_minute_sina()`；额外提供 `get_dominant_contract()` 方法获取当前主力合约代码
   - `_fetch_intl_futures_daily()` → 调用 `ak.futures_foreign_hist()`，实时用 `futures_foreign_commodity_realtime()`
   - `_fetch_forex_daily()` → 调用 `ak.forex_hist_em()`，失败时尝试 `ak.currency_hist()` 作为备选
   - `_fetch_cn_option_daily()` → 调用 `ak.option_sse_daily()`（ETF期权），股指期权用 `option_cffex_daily()`；额外提供 `get_option_chain()` 方法获取期权链（同标的同到期日的全部行权价合约）
   - `_fetch_crypto_daily()` → 调用币安 K 线（limit≤1000，需分页），失败打印警告
   - `_fetch_cn_fund_nav()` → 调用 `ak.fund_open_fund_info_em(indicator="单位净值走势")`，返回列重命名为 date/close（净值），open/high/low 用 close 填充、volume 填0，保持统一格式
   - `_fetch_cn_repo_rate()` → 调用 `ak.bond_repo_rate()` 获取逆回购历史利率，实时用 `bond_sh_buy_back_em()`
   - `_fetch_cn_reits_daily()` → 调用 `ak.reits_hist_em()`（公募REITs，可交易品种，**不能缺**）
   - `_fetch_cn_index_daily()` → **指数专用**：日线优先 `ak.index_zh_a_hist()`（东财）、回退 `ak.stock_zh_index_daily()`（新浪，全历史）；分钟用 `ak.index_zh_a_hist_min_em()`（东财，约 1 个月）；BaoStock 可作日线备份（`sh.000300`）。**严禁复用个股/期货接口**（会把指数代码当股票/期货代码，取回错误序列）

   **19 类市场必须先全部对齐**：可交易的 12 类要有真实取数方法，`cn_index` 走指数专用接口且 `tradeable=False`（不可下单）；`neeq` / `private_fund` / `qii_product` / `otc_deriv` 这 4 类若无公开 K 线源，必须在代码里**显式抛 `ValueError` 并说明"该市场走净值/定价路径"**（列入 `_NO_KLINE_MARKETS`），**不允许静默返回空 DataFrame**。

4. **数据质量自动检查**（非常重要，防垃圾数据进回测）：
   - 高低价异常检查：high < low 或 high < open/close 或 low > open/close 的行删除并打警告日志
   - 缺失值检查：**不做前值填充**。OHLC 为空的行**原样保留 NaN** 并标记 `is_missing=True`；仅当连续 ≥3 行缺失时才丢弃该段。另提供 `fill_missing()` 方法，但**标注"仅供图表展示"**，指标计算与回测必须使用未填充的原始序列
   - 价格为0或负数的行删除
   - 停牌处理：成交量为0的行保留（收盘价沿用前收），但标记 is_suspended=True
   - 涨跌停检查：单日涨跌幅超过市场涨跌停限制的，打印警告（不删除，防止除权除息误判）
   - 去重：按 date 去重，保留最后一条
   - 排序：按 date 升序
   - 单位校验：参考 1.0 节，对可校验的品种断言 `amount ≈ close × volume`（比值应在 [0.9, 1.1]），比值异常直接告警

5. **缓存机制**（复权与非复权必须分开，防"已复权价拼接"断层）：
   - **非复权市场**（期货/外汇/加密等）：`{market_type}_{symbol}_{period}_{adjust}.csv`
   - **复权市场**（A股/ETF/基金等）：**不再缓存已复权价**，改为
     · `data_cache/raw/{market_type}_{symbol}_{period}_raw.csv`（不复权原始价）
     · `data_cache/adj_factors/{market_type}_{symbol}_{period}_factors.csv`（复权因子）
     复权价由 `_apply_adjust()` 用 **原始价 × 因子** 现算（见 1.0 铁律 2）
   - 日线数据缓存有效期7天，分钟线1天，实时数据不缓存
   - 提供 `clear_cache(symbol=None)` 方法手动清除缓存
   - 提供 `update_cache(symbol)` 方法增量更新最新数据；**复权市场只增量更新 raw，并把因子文件强制重算**（不得只追加）

6. **港股特殊处理**：
   - 自动根据股价区间计算最小变动价位（price_tick_map）
   - 自动查询每手股数（调用 `ak.stock_hk_lot_size()`，查不到默认用100）
   - ETF自动免除印花税标记

7. **期货特殊处理**：
   - 自动读取 `config.py` 里的合约乘数、保证金比例、手续费参数
   - 主力换月自动识别：如果新主力合约和旧主力成交量持仓量切换，返回 dominant_roll 标记
   - 夜盘时段自动合并到下一个交易日（比如21:00-23:00的夜盘归属下一个自然日）

8. **期权特殊处理**：
   - 返回字段额外增加：strike（行权价）、expiry_date（到期日）、option_type（call/put）、contract_multiplier
   - 提供 `calc_greeks(S, K, T, r, sigma, option_type)` 静态方法，用BS模型计算Delta/Gamma/Theta/Vega/Rho
   - 提供 `calc_implied_volatility(S, K, T, r, option_price, option_type)` 方法，用二分法计算隐含波动率

9. **基金特殊处理**：
   - 自动识别场内/场外：6位代码如果是51/15开头走cn_etf，否则走cn_fund
   - 净值数据分红再投资默认用累计净值
   - 提供 `calc_holding_period_redemption_fee(hold_days)` 方法，根据持有天数计算对应赎回费率

10. **写 `test_data.py` 测试脚本**，依次获取以下标的的最近30天日线数据，打印前5行、数据形状、是否有空值，确保接口正常：
    - A股：600519（贵州茅台）
    - A股ETF：510300（沪深300ETF）
    - 美股：AAPL
    - 美股ETF：SPY
    - 港股：00700（腾讯）
    - 可转债：113052（若已退市则替换为仍在交易的品种）
    - 国内期货：rb（螺纹钢主力）
    - 国际期货：GC（COMEX黄金）
    - 外汇：EUR/USD
    - 加密货币：BTC/USDT（如果接口失败就打印跳过警告，不影响其他测试）
    - 公募基金：161725（招商中证白酒）
    - 国债逆回购：204001（GC001）
    - 公募REITs：508000
    - ETF期权：510050（上证50ETF期权链，能拿到合约列表就算通过）

    如果某个接口失败，不要崩溃，打印警告继续跑下一个，最后汇总哪些市场可用哪些需要检查网络。

    **另需新增 5 项强制自检（对应 1.0 节，必须打印实测数值）：**
    - **单位校验**：600519 / 510300 / 113052 各取最近一个交易日，打印 `amount/(close*volume)`，断言落在 [0.9, 1.1]
    - **复权校验**：对 600519 断言 `get_daily(adjust='')` 与 `get_daily(adjust='qfq')` 在**除权日之前**价格不同（证明复权真的生效了），并打印两者在最早一天的收盘价
    - **长历史**：取 600519 十年日线，断言行数 > 2300（验证未被静默截断）
    - **分钟长历史**：请求 600519 的 3 年 60 分钟线，断言返回行数 > 1023（验证 **BaoStock 长历史通道**生效；注意 1.0 节已实测确认免费源**无法分页**，长历史只能靠 BaoStock + 自建增量库，不要写成"验证分页生效"）
    - **列名一致性**：对 A股/ETF/可转债/期货/美股 五个市场取数，断言列名集合完全一致

---

## ===== 第 2 步：行情批量下载导出 + K线图绘制（多周期/形态标注/多标的对比/缠论）=====

> 本步做两件事：①把行情数据**批量下载、落盘成文件、随时导出**（不必先跑回测才能取数）；②把行情和交易结果**画成 K 线图**，让形态和买卖点一眼可见。这两个模块后面每一步都会用到。
>
> **本步要交付的文件（缺一不可，建完自查一遍）：**
> - `tools/data_export.py` + `tools/__init__.py`：批量下载与导出
> - `core/chart.py`：K 线绘制（多周期 / 形态标注 / 多标的对比 / 缠论叠加 / 回测复盘）
> - `core/chan.py`：缠论核心计算（分型 / 笔 / 线段 / 中枢 / 买卖点 / 多级别）
> - `core/data_fetcher.py`：**在原有文件上扩展**多周期支持（⚠️ 勿新建 `data/fetcher.py`）
> - `core/utils.py`：**在原有文件上添加** `re_sample_kline()`
> - 测试：更新 `test_chart.py`，新增 `test_pattern.py`、`test_chan.py`
> - 目录：`export/csv|parquet|excel/`、`backtest_results/charts/`（自动创建）

### 2.1 行情批量下载与导出工具 `tools/data_export.py`

创建 `tools/data_export.py`（同时创建空的 `tools/__init__.py`），用于把行情批量拉下来存成文件，**离线可用、可断点续传、可随时导出**。

1. **核心类 `DataExporter`**，初始化接收 `DataFetcher` 实例和 `export_dir` 参数（默认 `export/`），自动创建 `export/csv/`、`export/parquet/`、`export/excel/` 子目录。
2. **自选清单管理 `watchlist.csv`**（列为 `symbol,market_type,name`，`market_type` 可留空自动识别）：
   - 提供 `load_watchlist()`、`add_symbol()`、`remove_symbol()` 方法维护自选池
   - 提供 `add_market_batch(kind)` 批量加入：如 `index_300`（用 `ak.index_stock_cons_csindex(symbol="000300")` 拉沪深300成分股）、`all_etf`（用 `ak.fund_etf_spot_em()` 拉全部ETF）、`all_cb`（全部可转债）
   - ⚠️ **幸存者偏差提醒**：`index_stock_cons_csindex` 返回的是**当前**成分股，只能用于"看当下行情/批量下载"；**做历史回测的股票池必须用「时点成分股 Point-in-Time」**（见第 13 步），否则回测收益会被系统性高估。
3. **批量下载 `download(symbols, start, end, period='daily', adjust='qfq')`**：
   - 逐标的调用 `DataFetcher`，命中缓存且日期范围已覆盖的直接**跳过（断点续传）**
   - 每个标的之间 `time.sleep(cfg.REQUEST_INTERVAL)`，避免被接口限流
   - 用 `tqdm` 显示进度条（未安装时降级为普通打印，不报错）
   - 单个标的失败**不中断整体**，记录到失败清单，全部跑完后统一重试一次
   - 返回统计：成功数 / 跳过数 / 失败数 / 总行数 / 耗时
4. **导出格式**（`format` 参数选择，可多选）：
   - **CSV**：`export/csv/{market_type}_{symbol}_{period}.csv`，用 `encoding='utf-8-sig'` 保证 Excel 打开中文不乱码
   - **parquet**：`export/parquet/{market_type}_{symbol}_{period}.parquet`，体积小、读取快
   - **Excel 汇总**：`export/excel/{日期}_行情汇总.xlsx`，每标的一个 sheet（标的超过20个时自动提示改用 CSV，避免文件过大）
5. **数据概览 `summarize()`**：对已下载数据生成统计表，列出每个标的的：代码、名称、市场、起始日期、结束日期、交易日数、缺失值数、停牌日数、最新收盘价、区间涨跌幅；保存为 `export/数据概览_{日期}.csv` 并打印到控制台。
6. **增量更新 `update_all()`**：对自选池所有标的只拉上次日期之后的增量数据并追加到已有文件。
7. **独立可运行入口**（后续第 11 步再统一并进 `main.py`）：
   ```bash
   python -m tools.data_export --symbols 600519,510300,AAPL,rb --start 2020-01-01 --end 2026-10-27 --period daily --format csv,parquet
   python -m tools.data_export --watchlist --format parquet
   python -m tools.data_export --update      # 只做增量更新
   python -m tools.data_export --summary     # 只生成数据概览
   ```
8. **写 `test_export.py`**：下载 600519、510300、AAPL 三个标的近 1 年日线，导出 CSV + parquet，再读回来校验行数与列名一致（列名必须是 `date, open, high, low, close, volume, amount`），并打印数据概览。

### 2.2 K线图绘制模块 `core/chart.py`

创建 `core/chart.py`，统一负责所有图表绘制，要求**风格统一、中文正常显示、输出到 `backtest_results/charts/`**。

1. **中文字体处理（必做，否则中文全变方块）**：
   - 自动探测系统可用中文字体：Windows 用 `SimHei` / `Microsoft YaHei`；macOS 用 `PingFang SC` / `Arial Unicode MS`；Linux 用 `Noto Sans CJK` / `WenQuanYi`
   - 通过 `matplotlib.font_manager` 定位字体文件并设置 `plt.rcParams['font.sans-serif']`、`plt.rcParams['axes.unicode_minus']=False`
   - 找不到中文字体时打印警告并降级为英文标签，**不崩溃**
2. **K线主图 `plot_kline(df, symbol, name=None, ...)`**，用 **mplfinance** 绘制蜡烛图：
   - 蜡烛图，默认**红涨绿跌**（A股习惯），可通过 `color_scheme='us'` 切换为绿涨红跌（美股/外汇/期货外盘）
   - 叠加均线：MA5 / MA10 / MA20 / MA60（`mav` 参数可自定义）
   - 叠加布林带（可选开关）
   - 下方**成交量副图**（按涨跌染色）
   - **买卖点标注**：传入交易记录 DataFrame（含 `date, direction, price`），在K线对应位置用 ▲（买）/ ▼（卖）标记，并在图下方附交易台账小表
   - 支持 `start` / `end` 区间缩放
3. **指标副图 `plot_indicator(df, indicator)`**：支持 `macd` / `kdj` / `rsi` / `boll` 四个指标单独成图，也可与K线组合成多面板图（subplot 布局，K线在上、指标在下）。
4. **多标的对比 `plot_compare(symbols, start, end, normalize=True, benchmark=None)`**：
   - 归一化为起点=1 的走势曲线对比（不同价格量级的标的一起比）
   - 可叠加基准（默认沪深300）作参照
5. **回测结果K线复现 `plot_backtest_kline(result)`**：读取回测结果里的成交记录，在每个持仓标的的K线上标出全部买卖点，每标的一张图，方便复盘"这笔为什么在这里买/卖"。
6. **交互式版本（可选）**：装了 `plotly` 时额外提供 `plot_kline_interactive()`，生成可缩放、可悬停查看 OHLC 的 HTML，保存到 `backtest_results/charts/{symbol}_kline.html`；未安装 plotly 时自动跳过。
7. **统一出口 `save_fig(fig, name)`**：保存 PNG 到 `backtest_results/charts/`，`dpi=150`、尺寸自适应，文件名格式 `{symbol}_{图表类型}_{日期范围}.png`。
8. **写 `test_chart.py`**：取 600519 和 510300 近 1 年日线，各画一张「蜡烛图+MA+成交量」主图、一张 MACD 副图，再画一张多标的归一化对比图，确认中文正常、图能生成、文件落盘到 `backtest_results/charts/`。

### 2.3 多周期切换（日 / 周 / 月 / 分钟）

在数据层 **`core/data_fetcher.py`**（⚠️ 注意路径：第 1 步创建的是 `core/data_fetcher.py`，**不是** `data/fetcher.py`，别新建错文件）里扩展多周期支持，并在 `core/chart.py` 打通绘图。

1. **周期枚举（全局唯一写法，必须与 config、第 1 步一致）**：统一支持 `1d`（日）、`1w`（周）、`1M`（月）、`1min`、`5min`、`15min`、`30min`、`60min` 八种周期。**周期字符串写法唯一的权威来源是 `config.SUPPORTED_PERIODS`；周期→分钟数的映射必须引用 `config.PERIOD_TO_MINUTE`，禁止在函数内部自建映射表**（第 3/6/8 步也会引用同一份）。
   > ⚠️ **务必区分两个不同概念，别混为一谈**：
   > - `config.SUPPORTED_PERIODS` = **可取数/可支持周期全集**（8 种，含 `1min`）
   > - `config.CHART_CONFIG['plot_periods']` = **默认批量出图子集**（7 种，**不含 `1min`**）
   >
   > `get_kline()` 支持全部 8 种可取数周期；默认批量出图不含 `1min`（1 分钟数据量巨大、BaoStock 也不支持 1min，默认出图没有意义）。**不要出现 `1` / `60` 这类纯数字写法**。
2. **本地重采样函数 `re_sample_kline(df, period)`**（统一放在 **`core/utils.py`**）：
   - 用 pandas `resample` 把日线聚合为周线（`W-FRI`）、月线（`ME`），规则：`open` 取首、`high` 取最大、`low` 取最小、`close` 取末、`volume`/`amount` 取和，并保留 `date` 索引
   - 重采样**不依赖网络**，已有日线数据即可自由切换周期
   - 分钟线无法由日线反推，必须由接口直接获取：**严格遵循 1.0 节「五、分钟线长历史方案」**——A股个股 1/5/15/30/60 分钟走 **BaoStock**（长历史）+ 新浪/东财（当日段），其余品种走新浪/东财并落**自建增量库**。**不要**再写成"用 AKShare 分钟接口"（东财分钟只有约 1 个月，且无时间游标无法分页）。本地重采样（日→周/月）需给出明确提示
3. **数据层接口**：新增便捷方法 `DataFetcher.get_kline(symbol, start, end, period='1d', adjust='qfq')`——**它不是新的一套取数逻辑，而是对第 1 步已有 `get_daily()` / `get_minute()` 的按周期路由封装**（`1d/1w/1M` 走 `get_daily` 后按需重采样；`1min~60min` 走 `get_minute`）。返回**列名统一**（`date, open, high, low, close, volume, amount`）的 DataFrame。**禁止在 `get_kline` 里重复实现取数/复权/缓存逻辑**——那套全局只能有一份，就在 `get_daily`/`get_minute` 里。
4. **绘图支持**：`plot_kline(df, symbol, period='1d', ...)` 增加 `period` 参数，标题自动标注周期（如「600519 周线」），均线参数随周期缩放（周线建议 MA5/10/20/30）。
5. **跨周期数据获取 `get_multi_period(symbol, periods=['1d','1w','60min'])`**：一次返回多周期数据字典，供跨周期共振策略使用（如日线金叉 + 60分钟底背离）。
6. **未来函数红线**：重采样的周线/月线**最后一根K线是未走完的**，回测/信号计算时必须丢弃或标记为"未完成"，禁止用未走完的周线月线做信号。
7. **写测试**：在 `test_chart.py` 增加「同一标的一键切换日/周/月线各画一张图」，验证重采样 OHLC 聚合正确（手工核对一周的开高低收）。

### 2.4 形态标注（金叉死叉 / 突破 / 背离）

新建 `core/pattern_annotate.py`，自动在K线上标注技术形态，**每个标注可独立开关**，默认只开均线金叉死叉，避免图面杂乱。

1. **均线金叉死叉 `mark_ma_cross(df, fast=5, slow=20)`**：`fast` 上穿 `slow` 标"金叉"（▲ 向上箭头），下穿标"死叉"（▼ 向下箭头）。
2. **MACD 金叉死叉 + 顶底背离 `mark_macd_divergence(df)`**：
   - DIF 上穿 DEA 标金叉、下穿标死叉
   - **顶背离**：价格创新高但 MACD 柱/DIF 未创新高 → 红色虚线 + "顶背离"文字警告
   - **底背离**：价格创新低但 MACD 未创新低 → 绿色虚线 + "底背离"文字机会
   - 背离识别用**局部极值点对比**（`scipy.signal.argrelextrema`），并设最小间隔参数避免密集误判
3. **关键位突破 `mark_breakout(df, window=20)`**：自动识别近 N 日最高/最低点作为压力位/支撑位，收盘价有效突破时标"突破压力位"、跌破时标"跌破支撑位"。
4. **标注渲染**：在蜡烛图对应K线位置画箭头/虚线/文字，**自动避让**（上下错开，不重叠遮盖K线）；文字用统一字号，中文正常显示。
5. **开关参数**：`plot_kline(..., patterns={'ma_cross':True,'macd_div':False,'breakout':False})`，按需开启，默认只开 `ma_cross`。
6. **未来函数红线**：所有形态标注**只能使用当根及之前的K线**计算（局部极值确认需要前后K线的，必须在"确认那一刻"才标注，不能提前画到未来K线上）。
7. **写测试**：`test_pattern.py` —— 用构造数据验证金叉死叉点位正确、背离能识别、突破能标注，且标注日期不超出数据范围。

### 2.5 多标的K线并排对比（蜡烛图网格）

在 `core/chart.py` 增加 `plot_kline_grid(symbols, start, end, ncols=2, ...)`，与 2.2 的归一化曲线对比（`plot_compare`）互补：**前者看形态，后者看强弱**。

1. **最多 4 个标的**并排，`ncols` 控制列数（默认 2×2），共享 x 轴时间对齐。
2. 每个子图独立画**蜡烛图 + 均线 + 成交量副图**，各自标注标的名称与市场。
3. **顶部叠加一条归一化累计收益率对比曲线**（起点=1），把"形态"和"强弱"放在同一张图里看。
4. 支持加入**基准**（沪深300 / 纳斯达克等）作为参照线。
5. 时间轴自动对齐（不同市场交易日不同时，取并集并按各自有效交易日绘制，缺失处留空不连线）。
6. 典型用途：同板块个股强弱对比、行业联动分析、AH股对比、指数与成分股对比。
7. **写测试**：`test_chart.py` 增加「4 个标的一键并排」，验证图生成、中文正常、落盘到 `backtest_results/charts/`。

### 2.6 缠论可视化与计算 `core/chan.py`

新建 `core/chan.py`，实现**轻量但完整**的缠论核心结构识别，并在K线上绘制。**算法为主、绘图为辅**，识别结果要能被策略直接调用（`signals()` 输出买卖点），不是只画个图。

1. **核心类 `ChanAnalyzer`**，输入标准 OHLCV DataFrame，输出分型 / 笔 / 线段 / 中枢 / 买卖点五类结构。
2. **K线包含关系处理 `merge_inclusion(df)`**：按缠论规则合并有包含关系的相邻K线（向上处理取高高、向下处理取低低），生成"无包含K线序列"，这是后续所有识别的基础。
3. **分型识别 `find_fractals()`**：在合并后的K线上识别**顶分型**（中间K线高点最高、低点也最高）与**底分型**（中间K线低点最低、高点也最低），记录分型位置、类型、高低点价格。
4. **笔划分 `find_strokes(mode='new')`**：
   - 顶底分型交替连接成笔，中间至少间隔独立K线（**新笔**：≥4根合并K线；**老笔**：≥5根，`mode` 参数切换）
   - 同类型分型之间取更极端者（顶取更高、底取更低），中间未成立的笔被取消
5. **线段识别 `find_segments()`**：至少三笔构成线段，用**特征序列**判断线段被破坏（特征序列有缺口/无缺口两种情况分别处理），输出线段起止点。
6. **中枢识别 `find_centers()`**：连续三笔（或三段）重叠区间构成中枢，计算并记录 `ZG`（中枢上沿）、`ZD`（中枢下沿）、`GG`（最高点）、`DD`（最低点）、进入段/离开段、中枢级别。
7. **买卖点识别 `find_buy_sell_points()`**：按缠论定义标注
   - **一类买/卖点**：趋势末端出现背驰（用 MACD 面积/柱高对比前后同向走势力度）后的转折
   - **二类买/卖点**：一类点后第一次回抽不破前低/前高
   - **三类买/卖点**：中枢突破后回抽不回中枢（买点）、跌破后反抽不回中枢（卖点）
   - 输出统一字段：`date, type(1/2/3), direction(buy/sell), price, level, reason`
8. **级别递归**：日线笔可构成周线段、周线笔可构成月线中枢；提供 `analyze_multi_level(symbol)` 做**多级别联立**（大级别定方向、小级别找买卖点）。
9. **信号输出 `signals()`**：返回买卖点 DataFrame，可直接在策略里 `if chan_signal == 'B3': self.buy()`，实现"缠论策略"。
10. **绘图 `plot_chan(df, chan_result, ...)`**（或作为 `plot_kline` 的叠加层）：
    - 顶/底分型用小三角/小圆点标记
    - **笔**：黄色实线连接顶底分型
    - **线段**：橙色粗线
    - **中枢**：蓝色半透明矩形框，标注 ZG/ZD 数值与级别
    - **买卖点**：彩色大箭头（B1/B2/B3 红色、S1/S2/S3 绿色）标在对应K线旁
11. **显示开关**：分型 / 笔 / 线段 / 中枢 / 买卖点**五个独立开关**，默认只开「分型 + 笔 + 中枢」，避免新手看图太乱。
12. **边界容错**：震荡行情中笔、线段划分本身具有不确定性，对"划分存疑"的区域加灰色提示标记，并在文档中明确**自动识别的笔线段与人工划分可能有出入**，争议处需人工核对K线，不要盲信。
13. **写测试 `test_chan.py`**：用一段构造或真实行情，验证分型数量与位置合理、笔首尾连接正确（顶底交替）、中枢区间 ZG>ZD、买卖点不出现未来函数，绘图能正常落盘。

### 2.7 新增/更新测试脚本汇总（本步）

- **更新 `test_chart.py`**：基础K线、多周期切换（日/周/月）、形态标注、多标的并排对比、回测成交点复盘，全部覆盖。
- **新增 `test_pattern.py`**：形态标注专项（金叉死叉、背离、突破）。
- **新增 `test_chan.py`**：缠论专项（分型 / 笔 / 线段 / 中枢 / 买卖点 / 绘图）。
- 运行全部测试通过后，把进度标记为已完成。

### 2.8 实测结果与已知限制（第 2 步完成记录）

**实测 A（600519 两年日线，基础链路）**：485 根 → 包含处理后 368 → 分型 170（顶 85 / 底 85）→ 笔 49（交替且首尾相接）→ 线段 16 → 中枢 5（ZG>ZD）。

**实测 B（600519 六年日线，收尾版）**：缠论**一/二/三类买卖点全部产出且可溯源**，共 **59** 个点（**B1=16 / B2=11 / B3=2 / S1=18 / S2=11 / S3=1**，六类齐全；22 个二类点全部带 `src_date` 可追溯到前置一类点，**孤儿 0**；`B2≤B1`、`S2≤S1` 成立）；日线 438 根 / 周线 95 / 月线 22；4 标的并排图 447 KB；图表落盘 9 PNG + 1 HTML；导出 735 行（列名严格 `date,open,high,low,close,volume,amount`）。测试：`test_chart` 19/19、`test_pattern` 14/14、`test_chan` **30/30**、`test_export` 11/11、`test_env` **75/75**。

**实测 C（指数与单位，第 2 步收尾新发现）**：`sh000300` 十年日线 **2426** 行（走新浪回退，`amount=NaN` + `amount_missing=True`）；裸 `399001` / `399006` / `399673` / `932000` → `cn_index`，裸 `000300` / `000905` / `000016` / `000688` → `cn_stock`（号段与深市个股重合，维持个股优先），`sh000300` / `sh000905` → `cn_index`；✅ **指数成交量单位已跨源验证结案**：BaoStock 指数日线（同时含 `volume`/`amount`）与新浪同指数同日 volume 比对——`sh.000300` / `sh.000001` 比值 **1.0000**、`sz.399001` 比值 **0.9991**（源修订差异）；BaoStock 自检 `amount/volume = 22.71 元/股`（合理）→ **确认新浪指数 volume=「股」、÷100 转「手」正确**；⚠️ **东财 `push2his` 本机持续不可达**（个股/ETF/指数日线+分钟全线），已量化「数据源可用性」清单（见 1.0 节七）——第 13 步"多源故障切换"的必要性已被现实印证。

**本步修掉的 7 个真 bug**（均属"不报错但算错"类，务必保留这些修复）：
1. 指标副图与成交量抢同一 panel → `panel_ratios` 长度不匹配报错
2. 月线仅 22 根而 MA60 整列 NaN → `nanmax` 空数组崩溃（全 NaN 的 MA/指标须跳过并回退 panel 数）
3. 基准 `000300` 取不到（当时数据层不支持指数）→ 临时用 `510300` ETF 代理并标注；**收尾已接入 `cn_index`，基准改用真实指数 `sh000300`**
4. 缠论同型更极端分型未同步延伸上一笔终点 → 笔不首尾相接
5. 缠论背驰比较相邻笔（方向必然相反）→ 买卖点恒为 0；应改为 `bi[i]` vs `bi[i+2]`
6. 数据概览把 `cn_stock_600519` 误切成 `cn` + `stock_600519` → 须从右往左按已知市场名匹配
7. 缠论一/二/三类买卖点**只有一类产出** → 根因三个：中枢延伸条件被边界触碰误触发（一个中枢吞掉整段行情）、二类点用日期过滤漏笔、三类点列表日期过滤；改为**笔下标定位 + 真重叠延伸 + 单中枢最多 9 笔**

**已知限制（写进 README）**：
- 指数日线已通过 `cn_index` 接入；**指数不可直接交易**（`tradeable=False`，订单层须拒单）
- ✅ **指数成交量单位已交叉验证结案**：以 BaoStock 指数日线（含 `volume`+`amount`）与新浪同指数同日 volume 比对——`sh.000300` / `sh.000001` 比值 **1.0000**、`sz.399001` 比值 **0.9991**；**确认新浪指数 volume=「股」，÷100 转「手」正确**（见 1.0 铁律 7）
- ⚠️ **东财 `push2his` 本机不可达**（个股/ETF/指数日线+分钟全线 `RemoteDisconnected`）→ 已量化“数据源可用性”清单（见 1.0 节七）；**单点故障**：`forex` / `cn_fund` / `cn_reverse_repo` 的日线、`cn_convertible` / `us_stock` / `us_etf` / `hk_stock` 的分钟线**均仅东财一个源**，东财挂即完全取不到
- **缠论三类点极稀疏**（六年单标的 B3=2 / S3=1）且**对中枢延伸上限高度敏感**（上限 3→B3=4、5/9→2、12/20/∞→0）；本实现为**轻量缠论**、非严格缠论，B3/S3 须人工核对
- `1min` 属可取数周期但**不在默认出图列表**（`SUPPORTED_PERIODS` 8 种 vs `plot_periods` 7 种）
- 图表同名文件重复生成会覆盖（建议文件名含日期范围 + 生成时间戳）
- 缠论笔/线段划分具主观性，**自动识别与人工划分可能有出入**，争议处必须人工核对 K 线，不得盲信
- 缠论中枢"**单中枢最多 9 笔**"为防误吞的**启发式限制**，极端行情下可能误切，需人工核对
- Excel 汇总在标的多时体积很大（>20 个自动提示改用 CSV）
- **指数成交额与单位**：新浪源无 `amount`（返回 `NaN` + `amount_missing=True`），东财源有；两源 `volume` 单位分别为**股（新浪）/ 手（东财）**，统一由数据层换算为「手」并写 `attrs.volume_unit` / `source_volume_unit`；⚠️ 换源时数据层须打 WARNING（已实现），下游按 `attrs` 处理
- ⚠️ **指数代码写法**：`sh000300` / `sz399001` 走指数专用接口；裸 6 位中 `399xxx`（深证系列）与 `932xxx`（中证2000）**已可直接识别**，但 **`000xxx` 段（`000300` / `000905` / `000852` / `000016` / `000688`）与深市个股号段重合，仍会被判为 `cn_stock`**——**取指数行情必须写带前缀**（`sh000300`）；取成分股名单则用裸代码（AKShare 要求），两者勿混

---

## ===== 第 3 步：技术指标计算模块 =====

创建 `core/indicators.py`，所有策略要用的技术指标都在这里实现，**所有指标只接受标准化的 OHLCV DataFrame，不依赖任何市场特有字段，保证跨市场通用**。

> **本步要交付的文件**：`core/indicators.py`（指标库）、`test_indicators.py`（测试脚本）。指标是**纯函数**——输入 Series/DataFrame、输出 Series/DataFrame，**不自己取数、不自己绘图**。

---

### 3.0 【先看这个】指标计算的三条硬约定（写错不报错，但结果整体偏掉）

> 这三条与第 1 步 1.0 节一脉相承。技术指标本身不会报错，但**喂进去的数据口径错了，算出来的信号就是假的**。

#### 一、复权口径必须全局统一（最高优先级）

1. **同一组指标必须用同一复权口径的序列**——不允许 `MA(close)` 用前复权价、`ATR(high,low,close)` 用不复权价。
2. **波动率类指标（`ATR` / `STD` / `HIST_VOL`）必须用复权价**：不复权价格在**除权除息日会凭空跳空**，ATR/波动率会把这个"假跳空"当成真实波动，导致除权日附近信号全乱。**这是本步最隐蔽的一类错误**。
3. 默认口径取 `config.INDICATOR_CONFIG['default_adjust']`（`qfq`），与数据层 `get_daily()` 默认一致；若要改用不复权，**整组指标一起改**，不得混用。
4. 指标函数**不自己调用数据层取数**；由调用方负责传入"口径已统一"的 DataFrame。
5. **口径必须「可确认」，且不能只靠 `attrs`**：`attrs` 会被 `resample` / `concat` / 窗口运算清空（见 1.0 节七），一旦清空，守卫若「读不到就当已复权」就是 **fail-open**——而「在未复权价上算波动率」正是本节要防的最隐蔽错误。因此：
   - 复权口径由**显式函数参数**声明（默认 `config.INDICATOR_CONFIG['default_adjust']`），或**物化为普通列**（`config.INDICATOR_HARDENING['adjust_column']`，默认 `price_adjust`）——普通列随帧穿过重采样/拼接，不像 `attrs` 会被清空；
   - 波动率类指标在**无法确认口径**时按 `config.INDICATOR_HARDENING['on_adjust_unknown']` 处置（默认 `"require"`：报错）；**禁止**静默按已复权处理。

#### 二、量能类指标一律用 `volume`，禁止用 `amount`

1. `VOL_MA` / `OBV` / `VR` 等量能指标**只接受 `volume`**，不得接受 `amount`。
2. 原因：**期货、指数的 `amount` 是 NaN**（期货无成交额字段；新浪指数源无成交额）——用 `amount` 算量能会得到一堆 NaN 或错误值。
3. `volume` 单位因市场而异（股票=股、可转债=张、期货=手、加密=币）：量能指标**只能在同一标的内做时间序列比较**（如 `VOL_MA` 偏离度、`VR` 比值），**禁止跨市场直接比绝对成交量**（期货"手"与股票"股"量级不可比）。代码注释中须写明此限制。
4. 若某标的 `volume` 全为 0（如场外基金净值序列），量能指标应返回**空/NaN 并显式标注**，**不得静默返回 0 值序列**（0 会被误读为"极度缩量"）。

#### 三、年化基数必须引用 config 常量（禁止硬编码 252）

1. `HIST_VOL`（历史波动率年化）、`SHARPE_RATIO`、`ANNUAL_RETURN`、`VOLATILITY` 等**必须引用 `config.INDICATOR_CONFIG`**，**不得在函数里硬编码 `252` / `244`**。
2. 原因：**A股一年约 242~244 个交易日、美股约 252 个**；硬编码 252 会让 A股年化波动率系统性偏高。
3. 非日线周期（周/月/分钟）的年化基数由 `config.INDICATOR_CONFIG['annual_factor_by_period']` 提供，不得就地写死。
4. 无风险利率 `rf` 默认取 `config.INDICATOR_CONFIG['risk_free_rate']`（年化），函数内按数据频率换算到对应周期。
5. **跨步骤口径必须一致**：后续第 5.9 节因子评估、第 6 步回测引擎、第 10 步净值回测里的「年化收益 / 年化波动 / 夏普比率」**必须复用同一套年化口径**（引用 `config.INDICATOR_CONFIG`），不得各步各自硬编码——否则同一策略在不同模块里的夏普会对不上，且很难发现。

---

#### 四、指标守卫不能装在会失灵的信息源上（预热期 / 跨市场红线）

> 这是第 2 步 stale 闸门（`attrs` 丢失 → 误拒 / 误放）同一个教训在指标层的复现：**守卫读取的信息源若本身会丢、可缺，守卫就等于没有。**

1. **每个指标必须暴露 `required_bars(**params) -> int`**（默认参数下的最小预热根数），窗口不足返回 NaN；回测 / 实盘**必须跳过预热期**再出信号。
2. 原因：`EMA` / `SMA`(通达信递推) / `RSI`(Wilder) / `ADX` / `SAR` / `MACD` 的 `DEA` 都是**递归**的，早段值由初始化决定、**有偏**——它**不算未来函数**（看不出用了未来数据），但同样让早段信号失真，属于「不报错但结果整体偏掉」的一类，**靠 shape 检查抓不到**。
3. 默认参数下的参考预热根数见 `config.INDICATOR_HARDENING['warmup']`（**是下界**；递归收敛更慢时取 `max(所需, warmup)`）。
4. **跨市场红线不得依赖「调用方自觉」**：
   - 评估类指标（第 7 组）统一加 `eval_` 前缀、或放独立子模块，做到**从命名上就不可能**被误当实时信号；「实时信号链入口」统一挡，而不是靠策略记得调 `assert_indicator_usable(for_signal=True)`；
   - 净值型判定在**缺少 `market` 参数**时**不得默认放行**（要么报错、要么按最高危处理）——缺参数即放行 = 防线形同虚设。
5. 守卫（`check_adjusted` / `assert_indicator_usable` 之类）**不得只在「显式传了错参数」时才触发**——那等于「忘传参数就失效」，与第 2 步 `for_trading` 默认放行是同一类坑。

---

#### 五、预热期是「哑弹」，不是「墙」（NaN 会被下游填掉）

> 第 2 步的教训是「守卫读的信息源会丢」；这一节是它在**数据预处理**层面的翻版：**置 NaN 只是把错误值标记成「哑弹」，它能不能挡住信号，取决于下游怎么处理 NaN。**

1. **`fillna` 会击穿预热保护**：策略 / 回测在把多个指标 `concat` 成决策帧后，普遍会做 `fillna(0)` / `ffill` / `bfill` / `rolling(min_periods=1)`。其中 **`fillna(0)` 最阴**——`RSI` / `KDJ` 预热期的 `NaN` 变成 `0`，会被读成「极度超卖」，**预热期直接发出买入信号，且全程不报错**。
2. **预热判定必须引擎级统一裁决**：
   - 每个指标输出除数值外，**同时携带「该 bar 是否已过预热期」的物化布尔列**（`config.INDICATOR_WARMUP_GUARD['warmup_ok_column']`，默认 `warmup_ok`）；
   - **信号入口强制** `df[df[warmup_ok_column]]` 才允许出信号；**禁止**在掩码为 `False` 的行 `fillna` / `ffill` / `bfill` 后出信号（`forbid_fillna_before_warmup=True` 时入口直接报错）。
3. **`required_bars` 不能用查表值糊弄**：`config.INDICATOR_HARDENING['warmup']` 只是**下界**。递归类（`EMA` / `SMA` / `RSI` / `ADX` / `SAR` / `MACD-dea`）的真实预热根数应由**收敛验证**确定——用**充分燃烧期（如 `10×N` 根）长样本**算出的序列作基准，**反推「相对误差 ≤ `config.INDICATOR_WARMUP_GUARD['convergence_tol']`（默认 `1e-3`）所需的最少根数**：实测 `EMA(12)` 需 ~40+ 根、`MACD` 的 `DEA` 需 ~70+ 根，**远大于表值 20 / 35**。
4. **实盘末根在预热期的处置**：新上市标的 / 刚切换周期时，**最后一根 bar 可能仍处预热期**——此时该标的**拒绝出信号**（`live_reject_if_last_bar_in_warmup=True`），不得给「有偏的早段值」；并与第 4 步下单闸门联动（无有效信号 → 不开仓）。
5. **物化列同样要按标的填**：与 `data_asof_date` 同理，`config.INDICATOR_HARDENING['adjust_column']`（`price_adjust`）在**多标的帧**里若「整列填同一个值」，帧内口径混合就**检测不出来**——须**按 `symbol` 分组填各自口径**，波动率类遇混合口径帧 fail-closed。

#### 六、期权 IV 反解必须 fail-closed

`IV` 二分法在**深度虚值 / 临近到期（T→0）/ 市价低于内在价值（脏数据）**时光滑性变差甚至**无解**——此时按 `config.OPTION_VALUATION_GUARD['on_no_solution']`（默认 `"nan"`）**返回 NaN 并标注 `iv_solved=False`**，**禁止**返回二分区间下界（那会把「没算出来」伪装成「IV 趋近 0」）。希腊字母单位：`THETA` 每**自然日**（`day_count_theta=365`）、`VEGA` / `RHO` 每 **1 个百分点**。

---

### 指标清单（每个指标一个独立函数，返回 pd.Series 或 DataFrame）

**统一约定（所有函数都遵守）：**

- **纯函数**：不修改传入对象，返回新对象。
- **空/异常输入**：传入空 DataFrame 或全 NaN 序列时，**优雅返回空/全 NaN 结果（保持 shape）**，不抛异常、不崩溃；K 线根数不足以计算（如 `MA20` 只有 5 根）时返回**全 NaN**，不报错。
- **NaN 处理**：窗口不足产生的**开头 NaN 保留、不填充**（避免给策略假信号）。
- **未来函数红线**：所有滚动指标**只能使用当根及之前的数据**；**禁止 `center=True`**；**禁止对整列做全样本标准化**（z-score 等会用到未来数据）。窗口参数一律表示"回看长度"。
- **参数默认值**取 `config.INDICATOR_CONFIG`（如年化基数、`rf`），不要在函数签名里写死。

1. **均线类**：
   - `MA(close, n)`：简单移动平均
   - `EMA(close, n)`：指数移动平均
   - `SMA(close, n, m)`：SMA 均线（**通达信口径**：`Y = (M*X + (N-M)*Y_prev) / N`）
   - `MACD(close, fast=12, slow=26, signal=9)`：返回 DIF、DEA、MACD 柱（柱 = `2*(DIF-DEA)`，与国内行情软件一致）
   - `BOLL(close, n=20, k=2)`：返回上轨、中轨、下轨

2. **动量类**：
   - `RSI(close, n=14)`（**Wilder 平滑口径**）
   - `KDJ(high, low, close, n=9, m1=3, m2=3)`：返回 K、D、J
   - `ROC(close, n=12)`：变动率
   - `CCI(high, low, close, n=14)`
   - `WILLR(high, low, close, n=14)`：威廉指标

3. **成交量类**（**只吃 `volume`**，见 3.0 二）：
   - `VOL_MA(volume, n=5, m=10)`：成交量均线
   - `OBV(close, volume)`：能量潮
   - `VR(close, volume, n=26)`：成交量比率

4. **波动率类**（**必须用复权价**，见 3.0 一）：
   - `ATR(high, low, close, n=14)`（**Wilder 平滑**）
   - `STD(close, n=20)`：标准差
   - `HIST_VOL(close, n=20, period='1d')`：历史波动率（年化，年化基数取 config）

5. **趋势类**：
   - `ADX(high, low, close, n=14)`：平均趋向指数（**Wilder 平滑口径**，返回 `+DI` / `-DI` / `ADX`）
   - `SAR(high, low, step=0.02, max_step=0.2)`：抛物线指标（须正确处理**初始方向**与极值点翻转）

6. **期权专属**（给期权策略用）：
   - `IMPLIED_VOL`：对接 `data_fetcher` 里的 IV 计算
   - `DELTA/GAMMA/THETA/VEGA/RHO`：直接封装希腊字母计算
   - `IV_RANK(iv_series, n=252)`：隐含波动率分位数
   - `IV_PERCENTILE(iv_series, n=252)`：IV 百分位
   - ⚠️ IV 序列依赖期权数据可用（`cn_option` **无东财备源**，东财不可达时取不到 → 函数应返回空并标注，**不得崩溃**）

7. **基金/资产配置专属**（⚠️ **评估类指标，见下方红线 1**）：
   - `MAX_DRAWDOWN(nav)`：最大回撤
   - `SHARPE_RATIO(nav, rf=None, period='1d')`：夏普比率（`rf` 默认取 config）
   - `ANNUAL_RETURN(nav, period='1d')`：年化收益
   - `VOLATILITY(nav, period='1d')`：年化波动率

8. **期货专属**：
   - `BASIS(spot_price, futures_price)`：基差
   - `BASIS_RATE(spot_price, futures_price)`：基差率
   - `ROLL_YIELD(near_price, far_price, days_to_expiry)`：展期收益率

---

### 9. 两条跨市场红线（必须写进代码注释）

**红线 1：评估类指标不得进入实时信号链。**
第 7 组（`MAX_DRAWDOWN` / `SHARPE_RATIO` / `ANNUAL_RETURN` / `VOLATILITY`）是**全样本统计量**——它们用到了"整段序列"的信息，属于**回测评估指标**。若被当作实时信号使用，等于**未来函数**（用当天无法知道的全样本统计做决策）。请在代码中把这一组标注为 `# evaluation-only，禁止用于实时信号`，并在每个函数的 docstring 里写明。**（v2 强化）** 光靠注释不够——把这一组统一命名成 `eval_` 前缀（`eval_max_drawdown` / `eval_sharpe_ratio` / …）或放独立子模块，让「实时信号链」在**命名/模块层面**就取不到它们；**禁止**把「策略记得传 `for_signal=True`」当唯一防线（忘传即失效）。

**红线 2：净值型品种不适用 K 线类技术指标。**
`cn_fund`（场外基金）、`cn_reverse_repo`（逆回购）、`private_fund`、`qii_product` 这几类走的是**净值/利率路径**，数据结构与 K 线不同（`open/high/low = close`、`volume = 0`）。对它们只应使用**第 7 组净值类指标**；若对它们计算 `ATR` / `KDJ` / `BOLL` / `SAR` 等需要 high/low 的指标，会得到**无意义结果**。请在需要 high/low 的指标入口按 `config.INDICATOR_CONFIG['nav_only_markets']` 做判断，对不适用品种**打 WARNING 并返回空**。**（v2 强化）** 该判定**不得只在传了 `market` 时才生效**：调用方未提供 `market` 时应**报错或按最高危处理**，**禁止默认放行**（缺参数即放行 = 防线形同虚设）。另：`volume` 全 0 时量能指标须返回**空/NaN 并标注**，**不得静默返回一串 0**（0 会被误读为「极度缩量」）。

---

### 10. 测试 `test_indicators.py`

1. **随机数据必须满足 OHLC 合法性**：先生成 close 随机游走，再由 close 生成 `high ≥ max(open, close)`、`low ≤ min(open, close)`——否则会算出负的 ATR 之类的假结果。
2. **每个指标都要断言**：输出 shape 与输入一致、无全 NaN（除预期的开头窗口段）、不修改原始 DataFrame、对**空表**与**全 NaN 表**不抛异常。
3. **光有 shape 检查不够，必须做数值校验**：对少数可手算的指标（`MA` / `EMA` / `MACD` / `BOLL` / `RSI`），用**手工构造的小样本**（如 10 根固定收盘价）逐值核对，误差 < 1e-6。**不得用"随机数据跑通"当作指标正确**。
4. **复权口径校验**：构造一段含"除权跳空"的数据，断言 `ATR(不复权)` **明显大于** `ATR(复权)`——证明波动率确实受口径影响（这条能抓住"用错口径"的经典错误）。
5. **年化基数校验**：断言 `HIST_VOL` 使用的是 `config.INDICATOR_CONFIG` 的值，而不是硬编码的 `252`。
6. **未来函数校验**：对任意指标，断言"只用前 N 根算出的值" == "用全部数据算出的同位置值"（逐点一致），证明没有用到未来数据。
7. 打印每个指标的实测结果摘要，**不能只写"通过"**。
8. **复权守卫 fail-open 校验**：构造一个 `attrs` 被清空（模拟 `resample`/`concat` 之后）但价格为**不复权**的帧，断言波动率类指标**不会静默算出结果**（按 `on_adjust_unknown='require'` 报错）——证明守卫不依赖易失的 `attrs`。
9. **预热期校验**：对每个递归类指标（`EMA`/`RSI`/`ADX`/`SAR`/`MACD`），断言「前 `required_bars-1` 根为 NaN」，且「第 `required_bars` 根起有值」。
10. **量能全 0 校验**：构造 `volume` 全 0 的净值型序列，断言量能指标返回**空/NaN 并标注**，**不是**一串 0。
11. **红线不可绕过校验**：断言评估类指标在实时信号链入口**无论是否传 `for_signal` 都被隔离**（命名/模块层面）；净值型品种缺 `market` 时**报错而非放行**。
12. **期权希腊字母单位校验**：断言 `THETA` 为「每自然日」、`VEGA`/`RHO` 为「每 1 个波动率点 / 每 1% 利率」，把单位写进 docstring 并逐值核对（这是最容易悄悄错十倍的地方）。
13. **预热掩码校验**：断言指标输出带 `warmup_ok` 列；对预热期行做 `fillna(0)` 后，**信号入口仍拒绝出信号**——证明 NaN 不是唯一防线。
14. **`required_bars` 收敛校验**：用 `10×N` 根长样本作基准，断言递归类指标在 `required_bars` 处的**相对误差 ≤ 1e-3**；并断言「若按表值 20 / 35 取，误差超标」——证明必须收敛反推、不能查表。
15. **多标的口径分组校验**：构造 `A=qfq`、`B=none` 的**多标的帧**，断言波动率类**拦截**（不得因整列填同一个值而放行）。
16. **期权 IV 无解校验**：构造「市价低于内在价值」的脏数据与 `T→0` 数据，断言 IV 返回 **NaN 并标注 `iv_solved=False`**，**不是**二分区间边界值。

---

## ===== 第 4 步：统一账户与订单管理 =====

创建 `core/account.py`，实现一个支持全市场交易规则的账户系统，正确处理股票现货、期货保证金、外汇保证金、期权买卖方、基金申赎、逆回购等不同模式。

### 核心类 `TradingAccount`：

1. **初始化参数**：
   - `initial_capital`：初始资金
   - `base_currency`：基准货币（默认CNY，支持CNY/USD/HKD多币种，简化版先统一汇率换算，后期再加多币种）
   - 自动创建字段：cash（可用资金）、positions（持仓字典）、trades（交易记录列表）、daily_equity（每日权益曲线）、margin_used（保证金占用）、frozen_cash（冻结资金）

2. **下单接口 `place_order(symbol, direction, order_type, volume, price=None, order_time=None)`**：
   - direction: "buy"/"sell"/"short"/"cover"（short/cover用于做空和回补）
   - order_type: "market"/"limit"
   - volume: 下单数量（股/张/手/份，按各市场最小单位）
   - 自动用 detect_market_type(symbol) 获取市场类型，再通过 `config.get_market_config(market_type)` 取对应市场交易规则（**禁止直接写 config.MARKETS[...]**）
   - **交易规则校验**（下单前必须检查，不通过则拒绝并打日志）：
     - **不可交易品种拦截**：`config.get_market_config(market_type).get('tradeable', True)` 为 `False` 时拒绝（如 `cn_index` 指数**不可直接交易**——第 2 步 `CN_INDEX['tradeable']=False` 在此落地）
     - **数据时效闸门（双重防线的第二道，必须独立）**：引用 `config.TRADING_REQUIRE_FRESH`（默认 `True`）；下单前**独立重新校验**该标的行情时效（用交易日历比对"最近已收盘交易日"与"数据最新日期"，按市场分别判定），**不读取、也不信任上游传来的 `attrs['stale']` 标记**——pandas 的 `rolling`/`ewm`/`expanding` 窗口运算会把 `attrs` 清空（详见 1.0 节七）；超 `config.STALE_LIMIT` 直接拒单。**⚠️ 仅 `paper`/`live` 模式生效，`backtest` 模式必须豁免**（回测用的历史数据按定义就"过期"，无条件生效会拒掉全部回测）。
       - **实现方式（关键，不能只依赖 `attrs`）**：时效校验必须**脱离易失的 `attrs`**——二选一：① 读 `config.STALE_INFO_COLUMN`（默认 `data_asof_date`）这个**物化列**（列不会被 `rolling`/`ewm` 清空）；② 走 `config.STALE_CHECK_MODE="refetch"`，**从数据层重新取一次该标的的最新数据**再比对交易日历。**禁止**写成「`attrs` 读不到就 fail-closed」——实盘策略必然经过指标计算、`attrs` 必然丢失，那样会导致**每一笔下单都被拒**（详见 1.0 节七）。
       - **实现方式（v2 强化，必须以 `refetch` 为主）**：`place_order` 已持有 `symbol`（并由 `detect_market_type` 得到市场），因此**默认走 `refetch`**——按 `market + symbol` 从数据层重取「该标的当前最新数据」比对交易日历，**不依赖调用方传入的任何列/attrs**（因为指标库是纯函数，策略决策帧里通常没有 `data_asof_date` 列）。物化列仅作快速短路。**禁止**因「决策帧没有时效列」而 fail-closed。`refetch` 取不到时按 `config.STALE_REFETCH_FAIL_POLICY` 处置（**开仓拒、平仓放行**），同批次结果按 `config.STALE_REFETCH_TTL_SEC` 复用。
     - **指标预热闸门联动（v3.22 回补：预热期不开仓）**：`place_order` 接收策略层随单标记的 `warmup_ok`（该 bar 是否已过预热期）；**开仓方向**（`buy`/`short`）在 `warmup_ok=False` 时**拒绝并打日志**，**平仓/减仓**（`sell`/`cover`）**不受限**（避免因预热期无法止损/平仓，与 `STALE_REFETCH_FAIL_POLICY` 的「开严平宽」同则）。该闸门与第 3 步 `config.INDICATOR_WARMUP_GUARD['live_reject_if_last_bar_in_warmup']` 联动；未带 `warmup_ok` 标记的**裸单**按最保守处置（拒开仓）。
     - 最小交易单位检查
     - 买入整数倍检查（股票/ETF必须100股整数倍）
     - T+1检查：当天买入的不能当天卖出（记录买入日期）
     - 涨跌幅检查：价格超出涨跌停范围拒绝
     - 做空权限检查：不支持做空的市场direction=short拒绝
     - 资金校验：
       - 现货品种：所需资金 = 价格×数量 + 手续费，cash不足拒绝
       - 期货/外汇/期权卖方：所需保证金 = 合约价值×保证金比例，可用资金不足拒绝
       - 期权买方：所需权利金 = 权利金×合约乘数×张数，cash不足拒绝
     - 持仓校验：卖出/回补时持仓数量不足拒绝

3. **手续费计算 `calc_commission(symbol, direction, price, volume, is_close_today=False)`**：
   - 根据市场规则自动计算：佣金、印花税、过户费、交易征费、结算费、点差、平今仓溢价等
   - 支持最低手续费
   - 港股ETF自动免除印花税
   - 可转债免印花税
   - 期货自动区分开仓/平仓/平今仓
   - 期权按张收取固定费用
   - 加密货币按maker/taker费率
   - 基金按持有天数计算赎回费
   - 国债逆回购按期限计算手续费（手续费直接从收益里扣）
   返回总手续费金额。

4. **持仓管理**：
   - 每个标的持仓对象包含：symbol、volume（可用数量）、frozen_volume（冻结数量）、avg_cost（持仓均价）、realized_pnl（已实现盈亏）、unrealized_pnl（浮动盈亏）、open_date（开仓日期）、margin_rate（保证金比例，仅杠杆品种）
   - 支持T+0市场当日开仓当日平仓（区分今仓/昨仓用于期货平今）
   - 期货/外汇持仓支持每日结算：`daily_settlement(settle_price)` 方法，结算后更新持仓成本和已实现盈亏，划转资金
   - 做空持仓：单独记录short_positions，与long_positions分开，借券费按日计提
   - 期权持仓：区分买方持仓（付出权利金）和卖方持仓（收取权利金+缴纳保证金）

5. **账户权益计算 `calc_equity(current_prices: dict)`**：
   - 总权益 = 可用资金 + 冻结资金 + 所有持仓市值 + 浮动盈亏 - 保证金占用
   - 现货持仓市值 = 持仓数量×当前价
   - 期货/外汇：浮动盈亏 = (当前价 - 开仓价)×乘数×方向×手数
   - 期权买方：市值 = 权利金现价×乘数×张数（权利金归零则全部亏损）
   - 期权卖方：浮亏 = (当前权利金 - 开仓权利金)×乘数×张数，保证金重新计算

6. **强平检查 `check_margin_call(current_prices)`**：
   - 期货/外汇/期权卖方：当可用资金<0或保证金比例低于维持保证金线时，自动按亏损最大的顺序逐单强平，直到保证金比例恢复安全线
   - 记录强平日志，触发风险提醒

7. **订单成交后处理 `_fill_order(order)`**：
   - 更新cash：扣减买入金额+手续费，增加卖出金额-手续费
   - 更新持仓数量、成本价、已实现盈亏
   - 记录成交记录：order_id、symbol、direction、price、volume、commission、pnl、timestamp
   - 期货/外汇更新保证金占用
   - 国债逆回购：自动记录到期日和应得利息，到期日本息自动返回cash

8. **每日结束处理 `end_of_day(date, current_prices)`**：
   - 对期货/外汇执行每日无负债结算
   - 计提当日借券费、过夜利息
   - 检查期权到期：到期期权自动行权（实值期权自动行权，虚值期权放弃）
   - 检查国债逆回购到期，本息回款
   - 记录当日总权益到daily_equity
   - 重置今仓/昨仓标记，更新持仓open_date
   - 生成当日账户快照日志

9. **写 `test_account.py` 测试脚本**：
   - 初始化100万账户
   - 测试买入1000股贵州茅台（A股T+1，检查手续费、印花税、持仓成本）
   - 测试买入10手螺纹钢期货（检查保证金占用、当日卖出平今仓手续费）
   - 测试T+1规则：当天买的茅台当天下单卖出应该被拒绝
   - 测试做空：A股做空应该被拒绝，美股/期货/外汇做空应该成功
   - 测试可转债T+0当天买卖
   - 测试期权买入付出权利金、卖出开仓冻结保证金
   - 测试国债逆回购1天期下单，次日资金回款和利息计算
   - 测试基金申购赎回费用按持有天数变化
   - 测试不可交易品种：对 `sh000300`（`cn_index`）下单应被**拒绝**
   - 测试数据时效闸门：伪造"数据停更超过 `STALE_LIMIT`"的行情，下单应被拒绝；**再把数据层的 `for_trading` 参数去掉后重测，仍应被拒**（验证第二道防线独立生效，不依赖上游传参）；**并断言 `backtest` 模式豁免**（同样的过期数据在回测模式下不应被拒，否则回测全跑不动）
   - 所有测试打印断言结果，全部通过后再继续。

---

## ===== 第 5 步：策略研究模块（基类 + 自行接入 + 研究流程 + 示例策略）=====

> **本步是整个系统里"最属于你自己"的部分。** 系统只负责"取数据、把你的信号撮合成交、把结果算给你看"；**买什么、何时买，是你写在策略文件里的逻辑**。
>
> 本步的设计目标就一句话：**一份策略代码、一个字都不改，能在"回测 / 参数优化 / 模拟盘 / 实盘"四种环境里跑通**。切换的只是执行器（runner），不是策略本身——这既是判断量化系统架构好坏的核心标准，也是你"自己有策略时能顺利测试 → 模拟 → 实盘"的关键。

### 本步要交付的文件（请一次建好）

```
core/strategy.py            # ① BaseStrategy 策略基类（所有策略的父类）
core/strategy_loader.py     # ② 策略自动发现 / 注册 / 加载器
research/optimizer.py       # ③ 参数优化器（网格 / 随机 / 遗传）
research/walkforward.py     # ④ 走向前分析
research/validator.py       # ⑤ 稳健性 / 压力测试
research/registry.py        # ⑥ 实验记录与版本管理
tools/new_strategy.py       # ⑦ 策略脚手架生成器
tools/strategy_checklist.py # ⑧ 上线前检查清单
configs/strategies/         # 每个策略一个参数配置文件（yaml）
strategies/                 # 你的全部策略，一个策略一个 .py 文件
tests/                      # 策略信号单测与研究测试
```

### 5.0 开工前置：两道闸门必须在「信号入口」真正生效（v3.22 新增）

> **开工前置**：第 3 步的 B1–B5（`warmup_ok` 物化列、`required_bars` 收敛反推、`price_adjust` 按 `symbol` 分组、期权 `IV` 无解 fail-closed、末根预热期拒单）与两个常量（`config.INDICATOR_WARMUP_GUARD` / `config.OPTION_VALUATION_GUARD`）**必须先落地，再动本步**。否则策略将写在一个**即将改变**的指标接口上，必然返工。

**为什么必须放在本步**：第 3 步建立的预热掩码 `warmup_ok`、`required_bars`、`price_adjust` 分组——**只有在「信号入口」真正裁决时才有意义**，而信号入口就在本步（`BaseStrategy.on_bar` 及驱动它的执行器）。**没有任何消费者执行它，它就是死代码**；`fillna(0)` 照样把预热期 `RSI` 变成「极度超卖」并发出买入信号。这与第 2 步 `attrs` 丢失、第 3 步「守卫装在会失灵的信息源上」是同一族的又一次复现——**守卫的价值不取决于写得多严，而取决于真实链路上有没有人在执行它**。

1. **预热闸门（引擎级裁决，不靠策略自觉）**
   - 引擎喂给 `on_bar(date, bar_dict)` 的行情/指标数据**必须带 `warmup_ok` 列**（来自第 3 步指标输出的物化布尔列）；
   - `buy()` / `short()` 内部**强制**校验当前 bar 的 `warmup_ok`；为 `False` 时**拒绝下单并记日志**（既不静默丢弃、也不放行）；
   - `get_history(symbol, n, field)`：若 `n < 该指标 required_bars()`，**抛错或返回带 `warmup_ok` 的完整序列**——禁止返回「不足预热根数」的序列让策略自行计算；
   - **禁止**在 `warmup_ok=False` 的行做 `fillna(0)` / `ffill` / `bfill` / `rolling(min_periods=1)` 后产出信号（与 `forbid_fillna_before_warmup=True` 一致）。
2. **数据时效闸门**：本步所有信号最终仍经第 4 步 `place_order` 的时效闸门（`refetch` 独立复核）；策略层**不得**为「绕过 stale 拒单」而自建下单通道。
3. **末根在预热期**：实盘/模拟盘若最后可交易 bar 该标的仍在预热期，该标的**当轮不出信号**（`live_reject_if_last_bar_in_warmup=True`），不得用有偏的早段值。
4. **测试**：构造一个**预热期 bar + 已 `fillna(0)`** 的指标帧，断言策略照常 `buy()` 会被**拒单**——证明 NaN 不是唯一防线、闸门确实在信号入口生效。
5. **闸门必须「引擎无关」（v3.23 补充）**：本步四环境的执行器（含 `core/runner.py`）在**第 6 步会被替换**为 `core/backtester.py`。凡写在执行器内部的闸门逻辑（`warmup_ok` 逐 bar 注入、末根预热判定、`assert_signal_frame`）会随替换**静默消失**。因此闸门**只允许有一份实现**，放在**引擎无关**的独立模块（`core/signal_gate.py`），由执行器**调用而非重写**；裁决收口在 `place_order`（与 stale 闸门同处，见第 4 步）。须写**引擎一致性测试**：同一份「预热期 bar + 已 `fillna(0)`」的帧，在轻量 `runner` 与第 6 步 `Backtester` 下 `buy()` **都被拒**。

### 5.1 策略基类 `BaseStrategy`（core/strategy.py）

创建 `core/strategy.py` 策略基类，所有策略都继承这个基类，策略层**完全不需要关心市场是什么**，只看数据和信号。

#### 基类接口定义：
1. **初始化参数**：`account`（账户对象）、`data_fetcher`（数据对象）、`params`（策略参数字典）
2. **生命周期方法**：
   - `init()`：策略初始化，预热指标、设置参数（子类重写）
   - `on_bar(date, bar_dict)`：逐K线回调，bar_dict是当日所有标的的行情数据（子类必须实现，在这里产生交易信号）
   - `on_tick(price_dict)`：实时盯盘逐tick回调（可选重写）
   - `on_end_of_day(date)`：每日收盘后回调（可选重写，用于调仓、风控）
3. **内置便捷方法**：
   - `buy(symbol, volume, price=None)`：买入
   - `sell(symbol, volume, price=None)`：卖出
   - `short(symbol, volume, price=None)`：做空
   - `cover(symbol, volume, price=None)`：回补
   - `get_position(symbol)`：获取当前持仓
   - `get_history(symbol, n, field='close')`：获取最近n根K线数据
4. **内置风控**：
   - 单标的持仓上限自动检查（默认不超过总权益30%）
   - 总杠杆上限检查
   - 止损止盈自动触发（每个持仓可以设置独立止损止盈）
   - 黑名单：退市、停牌、ST、风险警示标的自动拒绝交易

### 5.2 先讲清最重要的一件事：策略的"四个运行环境"

同一个策略类，被四个执行器用**完全相同的接口**驱动，策略代码不用改一个字：

| 环境 | 入口 | 数据源 | 撮合 / 下单 | 用途 |
|------|------|--------|-------------|------|
| **回测** | `main.py backtest` | AKShare 历史数据 | 本地模拟撮合 | 验证想法 |
| **参数优化** | `main.py optimize` | AKShare 历史数据 | 本地模拟撮合 | 找稳健参数 |
| **模拟盘** | `main.py paper` | 实时 / 延迟行情 | 虚拟账户撮合 | 前瞻验证 |
| **实盘仿真** | `run_live.py --mode sim` | 券商仿真行情 | 券商仿真账户 | 全链路演练（第12步） |
| **实盘** | `run_live.py --mode live` | 券商实时行情 | 真实账户（二次确认） | 真金白银（第12步） |

**策略文件里只允许出现这些调用**：`self.buy()` / `self.sell()` / `self.short()` / `self.cover()` / `self.get_position()` / `self.get_history()` / `self.params`。

**策略文件里绝对不允许出现**：直接取数据、直接下单、直接算手续费、直接判断是不是交易日——这些全部由执行器注入。

> 这条"铁律"是整套系统能"一次编写、四处运行"的根基。写策略时如果你忍不住想直接调 akshare 或自己算费率，就说明这段逻辑该放进执行器，而不是放进策略。

### 5.3 策略自动发现与注册（core/strategy_loader.py）

让 `main.py` 能按名字调用你自己的策略，而不用改任何入口代码：

1. `discover()`：扫描 `strategies/` 下所有 `.py`，找出所有继承 `BaseStrategy` 的类，自动注册。
2. 每个策略用类属性 `meta` 声明元信息（报告、列表、优化都会用到）：

```python
class MyMaStrategy(BaseStrategy):
    meta = {
        "name": "my_ma",                      # 命令行调用名：--strategy my_ma
        "display_name": "我的均线策略",        # 中文名，报告里显示
        "markets": ["cn_stock", "cn_etf"],    # 适用市场
        "periods": ["1d"],                    # 适用周期
        "params": {"short": 5, "long": 20},   # 默认参数
        "description": "短均线上穿长均线买入、下穿卖出",
        "author": "me",
        "version": "1.0",
    }

    def init(self):
        ...
    def on_bar(self, date, bars):
        ...
```

3. `get(name)` 按名字取策略类；`list_all()` 列出全部可用策略（名称、中文名、版本、描述、适用市场）。
4. 单个策略文件有语法错误或缺 `on_bar` 时**不崩溃**，把它列入"不可用策略"清单并打印原因，其余策略照常加载。
5. 写 `test_loader.py`：验证能扫描到全部示例策略、能按名字正确取到、坏文件能被隔离。

### 5.4 策略参数配置化（configs/strategies/*.yaml）

把"本次运行参数"和"优化搜索范围"分开写，命令行可临时覆盖：

```yaml
# configs/strategies/my_ma.yaml
params:            # 本次运行使用的参数
  short: 5
  long: 20
symbols: [600519, 510300]
start: "2023-01-01"
end: "2026-01-01"
optimize:          # 参数优化时搜索的范围
  short: [3, 5, 8, 10, 15]
  long: [15, 20, 30, 40, 60]
```

- 命令行覆盖：`--params short=8,long=30`（优先级高于 yaml）
- 支持 `base.yaml` 继承：公共项写在 base，各策略 yaml 只写差异
- 实际使用的参数会被写进实验记录，保证**任何一次结论都能复现**

### 5.5 策略研究工作流（八步法，research/ 模块）

这就是"自己有策略时怎么测"的标准流程，八步里每一步都有对应模块支撑：

**第 1 步 · 生成策略脚手架** `tools/new_strategy.py`
- 命令：`python main.py new-strategy --name my_ma --template ma_cross`
- 生成三个文件：`strategies/my_ma.py`（带完整注释和 TODO 的策略模板）、`configs/strategies/my_ma.yaml`（参数配置）、`tests/test_my_ma.py`（信号单测骨架）
- 内置模板：`ma_cross`（均线）、`breakout`（突破）、`mean_reversion`（均值回归）、`grid`（网格）、`custom`（空白模板）

**第 2 步 · 信号单元测试**（不依赖网络，先证明"信号算得对"）
- 手工构造一小段已知 OHLCV（例如"先跌后涨、必然出现金叉"的假数据），断言：产生信号的**方向对、数量对、时间点对**
- 覆盖边界情况：数据不足、一路横盘、连续涨停、含停牌日、只剩一根K线
- 目标：**先证明逻辑正确，再谈回测收益**；这一步不通过，后面全白搭

**第 3 步 · 单标的快速回测（肉眼验收）**
- 只跑 1 个标的、近 1 年，用第 2 步的 K线图功能把买卖点画出来
- **肉眼看信号位置合不合理**——比任何指标都直观；如果信号画得莫名其妙，直接回去改逻辑

**第 4 步 · 多标的 / 多市场回测**
- 同一策略跑一批标的（如沪深300成分），看是**普遍有效**还是只在个别标的上有效
- 输出分标的绩效对比表（收益、胜率、盈亏比、最大回撤）

**第 5 步 · 参数优化** `research/optimizer.py`
- `GridSearchOptimizer`：参数笛卡尔积遍历，输出绩效热力图（如 short×long 的收益 / 夏普矩阵）
- `RandomSearchOptimizer`：参数多时随机采样 N 组
- `GeneticOptimizer`（可选）：简单遗传算法
- **关键约束：优化目标是找"参数平原"，不是找"收益最高点"。** 只有四周一圈都还不错的参数才可用；孤立的尖峰一律视为过拟合，直接弃用。
- 输出：最优参数、参数敏感性热力图、Top N 参数组合表

**第 6 步 · 样本内外分割 + 走向前分析** `research/walkforward.py`（**防过拟合最关键的一步**）
- **样本内外**：前 70% 数据用来找参数，后 30% **只做验证、绝不调参**
- **走向前分析（Walk-Forward）**：滚动窗口，每段用前 N 个月优化参数、紧接的后 M 个月"模拟真实执行"，首尾拼接成一条完整的**样本外净值曲线**——这是**最接近实盘的表现**
- 输出：各段参数变化、样本外净值曲线、样本内 vs 样本外绩效对比（衰减越小越好，衰减 > 50% 说明过拟合严重）

**第 7 步 · 稳健性与压力测试** `research/validator.py`
- **参数微扰**：在最优参数附近 ±10% 随机扰动 100 次，看绩效分布（一扰就崩 = 脆弱）
- **成本加压**：滑点 ×2、手续费 ×2，仍能盈利才可用
- **成交延迟**：信号延后 1 根 K 线成交（模拟真实下单延迟）
- **数据抖动**：给 OHLC 加微小噪声，看结果是否稳定
- 输出：稳健性评分卡（通过 / 警告 / 不通过）

**第 8 步 · 实验记录与对比** `research/registry.py`
- 每次回测 / 优化自动落一条记录（JSON 或 SQLite）：策略名 + 版本、参数、时间段、标的、全部绩效指标、图表路径、代码版本
- `compare(exp_ids)`：把多次实验拉成横向对比表
- 目的：**任何一次结论都能复现、能追溯**，杜绝"我记得上次那组参数挺好"

### 5.6 策略从研究到实盘的迁移路径

把上面八步串成一张流程图（**每一步不过关就停在原地改逻辑，绝不能靠调参硬凑过关**）：

```
① 写策略（只写信号逻辑，不碰数据 / 下单）
      ↓
② 信号单测通过
      ↓
③ 单标的回测（肉眼验收信号位置）
      ↓
④ 多标的回测（确认普遍有效）
      ↓
⑤ 参数优化（找参数平原，不找尖峰）
      ↓
⑥ 样本外 + 走向前分析          ← 不过关 → 回①改逻辑，禁止回头调参硬凑
      ↓
⑦ 稳健性 / 压力测试            ← 不过关 → 回①
      ↓
⑧ 模拟盘 ≥ 1~3 个月（同一份代码）← 与回测偏差 >5% 必须查原因
      ↓
⑨ 实盘仿真（券商仿真 / SimNow）← 跑通 信号→报单→成交→对账 全链路
      ↓
⑩ 小资金实盘（≤10% 资金，二次确认）
      ↓
⑪ 逐步加仓
```

**越往下判据越严**：回测看收益，模拟看"和回测的一致性"，实盘看"执行质量"（滑点、废单率、成交率）。

### 5.7 策略上线前检查清单（Strategy Go-Live Checklist）

做成 `tools/strategy_checklist.py`，对指定策略自动跑一遍，逐项输出通过 / 不通过：

- [ ] 策略元信息完整（name / markets / params / description / version）
- [ ] 信号单元测试全部通过
- [ ] 回测无未来函数告警
- [ ] 样本外绩效为正，且较样本内衰减 < 50%
- [ ] 走向前分析样本外绩效为正
- [ ] 参数稳健：±10% 微扰后仍盈利
- [ ] 成本加压：滑点 ×2、手续费 ×2 后仍盈利
- [ ] 交易标的日均成交额 > 阈值（默认 1000 万）
- [ ] 最大回撤 < 可承受阈值（默认 20%）
- [ ] 有止损 / 风控逻辑（或在第 12 步风控模块兜底）
- [ ] 模拟盘连续运行 ≥ 约定时长
- [ ] 模拟盘与回测偏差 < 5%
- [ ] 实盘风控参数已配置（第 12 步）
- [ ] 告警渠道连通测试通过（第 12 步）
- [ ] 日志留存与每日对账已开启（第 12 步）
- [ ] 已明确"最坏情况会亏多少"并且能接受

**全部通过，才允许进入小资金实盘。**

### 5.8 示例策略（每个策略都可以单独回测）：

1. **`double_ma_cross.py`：双均线策略（全市场通用，股票/ETF/期货/外汇都能用）**
   - 参数：short_window=5, long_window=20
   - 逻辑：短均线上穿长均线买入/做多，下穿卖出/做空
   - 适用：趋势行情，作为最基础的验证策略

2. **`cb_arbitrage.py`：可转债涨停联动策略（可转债专属）**
   - 逻辑：监测正股涨停且封单金额大于阈值，买入对应可转债，持有到尾盘或涨5%卖出，14:40无条件清仓不过夜
   - 过滤：转股溢价率<20%、剩余规模<50亿、成交额>5000万
   - 利用可转债T+0和无印花税优势

3. **`futures_trend_following.py`：期货海龟交易法则（国内/国际期货通用）**
   - 参数：entry_window=20, exit_window=10, atr_window=20, risk_pct=0.01
   - 逻辑：唐奇安通道突破开仓，ATR仓位管理（每笔风险不超过总资金1%），跌破10日低点平仓
   - 自动支持多空双向

4. **`us_swing_trading.py`：美股波段策略**
   - 逻辑：RSI超卖(30)+MACD金叉买入，RSI超买(70)+MACD死叉卖出
   - 自动跳过PDT限制：如果账户资金<25000，一周内日内交易不超过3次
   - 避开财报日（可选，财报前3天平仓）

5. **`option_sell_strangle.py`：期权卖出宽跨式（期权专属，进阶）**
   - 逻辑：每月初卖出当月虚值看涨+虚值看跌（delta≈0.2），收取权利金
   - 风控：delta超过0.5时平仓移仓，保证金不超过总资金30%
   - IV高的时候（IVR>50）才开仓

6. **`crypto_grid.py`：加密货币网格策略（加密货币专属，24h运行）**
   - 参数：grid_num=20, price_range_pct=0.2
   - 逻辑：在当前价上下20%区间挂20格买卖单，自动高抛低吸
   - 7×24运行，止盈后自动补单

7. **`fund_sip.py`：基金智能定投策略（公募基金专属）**
   - 参数：base_amount=1000, ma_window=250
   - 逻辑：每周四定投，当前价格低于250日均线扣款×1.5倍，高于均线×0.8倍，高于均线20%停止定投
   - 定投收益自动跟踪

8. **`repo_cash_management.py`：国债逆回购自动扫单（现金管理）**
   - 逻辑：每日14:50自动检查账户闲置资金，如果有>1000元闲置，自动买入当日利率最高的逆回购品种
   - 周四优先买1天期赚3天利息，季末/年末/节假日前加杠杆（可用正回购，简化版只做逆回购）
   - 不影响第二天买股票（资金T+1可用）

9. **`hk_ah_arbitrage.py`：港股AH溢价策略（港股专属）**
   - 逻辑：AH溢价指数>130时买对应H股，<110时买回A股，做配对交易
   - 自动处理汇率换算

每个示例策略都要有 `if __name__ == '__main__'` 块，可以单独运行测试信号生成是否正常。

### 5.9 因子研究与公开策略接入（免费+付费全支持）

**⚠️ 最重要的一句话先写清楚：Alpha101/Alpha191 是因子库，不是交易策略。**
因子只回答"今天全市场哪些股票该给高分/低分"，**不回答**什么时候买、买多少、多久调仓、怎么风控。直接把因子当策略实盘一定会亏。必须经过"因子评估→因子合成→组合构建→调仓策略→回测验证"这几步，才能变成可交易的策略。本模块把这整条链路打通，最终因子组合出来的打分直接能喂给你第6步的回测引擎、第7步模拟盘、第12步实盘，不用改一行代码。

### 5.9.0 因子目录结构（请一次建好）
```
factor/
├── __init__.py
├── expression.py          # 因子表达式引擎：字符串公式→pandas计算
├── alpha101.py            # Alpha101 101条公式完整免费复现
├── alpha191.py            # Alpha191 国泰君安191条因子免费复现
├── factor_engine.py       # 因子计算引擎：批量计算+缓存+并行
├── preprocess.py          # 去极值/标准化/中性化/缺失值处理
├── evaluator.py           # 因子评估：IC/IR/IC衰减/分层回测/相关性
├── combiner.py            # 因子合成：等权/IC加权/ICIR/线性/Ridge
├── factor_strategy.py     # 因子打分→交易策略适配器（接入BaseStrategy）
├── universe.py            # 股票池：沪深300/中证500/中证1000/全A/自定义
├── future_detector.py     # 未来函数自动检测器
├── adapters/              # 付费/外部平台因子适配器
│   ├── __init__.py
│   ├── tushare_factor.py  # Tushare Pro 202个官方因子库（含31个Alpha101）
│   ├── joinquant_factor.py # 聚宽jqdata alpha101/alpha191因子接口
│   ├── uqer_factor.py     # 优矿uqer因子库接口
│   └── qlib_factor.py     # 微软Qlib Alpha158/Alpha360因子导入
└── market/                # 公开策略市场
    ├── __init__.py
    ├── browser.py         # GitHub/QuantConnect/聚宽社区策略浏览检索
    ├── importer.py        # 开源策略自动导入适配
    └── validator.py       # 导入策略的安全/未来函数/性能检测
```

### 5.9.1 因子表达式引擎 `factor/expression.py`

实现一个类pandas表达式解释器，支持Alpha101和Alpha191全部算子，输入一行字符串公式、输出全市场面板因子值。

**必须实现的全部算子（覆盖Alpha101+Alpha191）：**

| 算子分类 | 算子名 | 语义说明 |
|---------|--------|---------|
| 基础截面 | `rank(x)` | 截面排名到[0,1] |
| | `zscore(x)` | 截面标准化 |
| | `scale(x, a=1)` | 截面归一化到权重和=a |
| 时间序列 | `ts_mean(x, d)` | d日移动平均 |
| | `ts_std(x, d)` | d日滚动标准差 |
| | `ts_sum(x, d)` | d日滚动求和 |
| | `ts_rank(x, d)` | d日内排名 |
| | `ts_max(x, d)` / `ts_min(x, d)` | d日滚动最大/最小 |
| | `ts_argmax(x, d)` / `ts_argmin(x, d)` | d日最高/最低值的位置 |
| | `ts_corr(x, y, d)` | d日滚动相关系数 |
| | `ts_cov(x, y, d)` | d日滚动协方差 |
| | `ts_delta(x, d)` | x - x.shift(d) |
| | `ts_delay(x, d)` / `shift(x, d)` | x.shift(d)，d日前的值 |
| | `ts_momentum(x, d)` | 过去d日涨跌幅 |
| | `decay_linear(x, d)` | 线性加权衰减（越近权重越大） |
| 截面运算 | `sign(x)` | 符号函数 |
| | `abs(x)` | 绝对值 |
| | `log(x)` | 自然对数 |
| | `signedpower(x, a)` | sign(x)*|x|^a |
| | `max(a,b)` / `min(a,b)` | 逐元素最大/最小 |
| | `product(x, d)` | d日滚动乘积 |
| 逻辑判断 | `if_else(cond, a, b)` | 条件选择 |
| | `group_rank(x, group)` | 行业内排名 |
| | `group_neutralize(x, group)` | 行业中性化（取组内残差） |

**关键约束（防bug，必须实现）：**
- 所有时间序列算子必须严格"只用历史数据"，**严禁把当日数据算进窗口**：`ts_corr(x,y,d)`时窗口是`iloc[i-d:i]`，不包含i当日
- 除零保护：所有除法、相关系数分母为0时返回NaN而不是inf
- NaN传播原则：窗口内NaN超过20%返回NaN，不强行填充
- 性能优化：用numpy向量化，101个因子全市场计算单年数据≤60秒

### 5.9.2 Alpha101 免费完整复现 `factor/alpha101.py`

严格按照 Kakushadze 2016 论文《101 Formulaic Alphas》（arXiv:1601.00991）复现全部101条公式，所有公式内置，不要让用户自己抄。

**字段要求：** 输入必须提供 open/high/low/close/volume/vwap/returns 七列；vwap 用 `(high+low+close)/3` 或 `成交额/成交量` 做fallback，returns = close/close.shift(1)-1。

**每条alpha必须有：**
- `alpha001` ~ `alpha101` 对应函数，返回单期截面打分DataFrame（日期×股票）
- 函数名、论文原公式注释、中文说明
- `get_alpha_list()` 返回全部101个函数列表
- `get_builtin_alpha(n)` 按编号获取单个alpha函数

**⚠️ 特别注意几个高频坑：**
1. `alpha006 = -1 * correlation(open, volume, 10)` 是开盘价和成交量的负相关
2. `alpha023 = sum(high>shift(high,1)?-delta(high,1):0, 20)` 之类的条件逻辑用if_else实现
3. `alpha054 = -1 * (low-ts_delay(close,1)) / (close-ts_delay(close,1)) * rank(volume)` 等复杂公式必须逐段核对论文
4. `alpha094 = rank((ts_rank(close,5)-ts_rank(close,15))*(-1*returns))` 这类多算子嵌套必须注意运算顺序
5. 涉及`group_rank`/`group_neutralize`的alpha，默认用申万一级行业分类，无行业数据时fallback到全市场rank

**配套测试脚本：** 写 `test_alpha101.py`，对随机生成的面板数据计算101个alpha，验证：无inf、没有未来函数（今日因子值与明日收益相关但与昨日收益不显著）、结果在合理范围。

### 5.9.3 Alpha191 国泰君安因子免费复现 `factor/alpha191.py`

按国泰君安《基于短周期量价的Alpha191因子》论文复现191条因子，结构同alpha101。分六大类：
- 001-040：趋势类（均线、动量、通道）
- 041-080：成交量类（量比、放量缩量、量价背离）
- 081-120：波动率类（振幅、ATR、布林带）
- 121-150：反转类（超买超卖、跳空缺口）
- 151-170：资金流类（开盘强弱、尾盘效应）
- 171-191：混合类（多因子组合、形态识别）

同样所有算子用5.9.1的表达式引擎，保证口径一致。

### 5.9.4 因子计算引擎 `factor/factor_engine.py`
- 输入：股票池（universe）、日期范围、因子列表（可以写编号如`['alpha001','alpha023','alpha094']`或传自定义函数）
- 批量拉取所需OHLCV/vwap数据，按因子需要的字段自动补全
- 多进程并行计算，进度条显示
- 结果缓存到本地parquet（`data_cache/factors/`目录），下次相同参数直接读缓存不重算
- 支持增量更新：新增交易日只算新增部分
- 输出dict，key是因子名，value是因子值DataFrame（日期×股票）

### 5.9.5 因子预处理 `factor/preprocess.py`
实盘能赚钱的因子，90%的功夫在预处理，必须实现完整的四步处理流程：
1. **去极值 `winsorize_mad(x, n=3)`**：中位数绝对偏差法，比3σ更稳健，去掉极端值
2. **缺失值处理 `fill_na(x, method='industry_mean')`**：行业均值填充/截面中位数/前值填充可选
3. **标准化 `zscore(x)`**：截面标准化到均值0标准差1
4. **中性化 `neutralize(x, industry_dummies, market_cap=None)`**：
   - 行业中性化：对申万一级行业做回归取残差
   - 市值中性化：对log(流通市值)做回归取残差
   - 行业+市值双中性：两个自变量一起回归取残差（默认推荐）
- 提供 `process_factor(x, winsor=True, neutralize=True, standardize=True)` 一键处理函数

### 5.9.6 未来函数检测器 `factor/future_detector.py`
专门针对因子的未来函数检测（回测好看实盘亏钱的头号原因）：
- `check_lead(factor_values, returns)`：检测因子值是否与次日收益相关过高（未来函数典型特征），与当日收益和昨日收益做对比
- `check_shift(factor_values, close)`：把因子值shift(1)后相关性是否显著下降，显著下降说明用了未来数据
- `check_rolling_window(factor_func, data)`：随机制造一段数据，在某日人工插入未来扰动，看因子值当日是否被影响
- 给出详细诊断报告，指出哪个因子哪一步计算可能引入未来函数

### 5.9.7 因子评估套件 `factor/evaluator.py`
这是判断一个因子"有没有用"的核心工具，必须实现：

1. **IC分析 `calc_ic(factor_values, forward_returns, method='spearman')`**
   - 每期计算因子值与下一期收益的Spearman秩相关系数（IC）
   - 输出：IC均值、IC标准差、**ICIR=IC均值/IC标准差**（>0.5算好因子，>0.3可合成）
   - IC>0比例（胜率）、IC绝对值>0.02的比例
   - IC时间序列、IC分布图

2. **IC衰减 `calc_ic_decay(factor_values, returns, periods=[1,3,5,10,20])`**
   - 因子对未来1/3/5/10/20天收益的IC，判断因子是快还是慢
   - 输出IC衰减曲线：短线因子1-3天IC高、快速衰减；中线因子5-20天IC稳定

3. **分层回测 `quantile_backtest(factor_values, returns, n_groups=5)`**
   - 每期按因子值把股票分成5组（Q1空/最弱~Q5多/最强）
   - 计算每组年化收益、夏普、最大回撤
   - 多空组合（Q5-Q1）净值曲线、年化、夏普、最大回撤
   - **单调性检查**：Q1→Q5收益是否单调递增/递减，不单调说明因子分组能力差

4. **因子相关性 `calc_factor_correlation(factor_dict)`**
   - 计算所有因子两两之间的截面平均相关系数
   - 输出相关性热力图（用seaborn）
   - 自动识别冗余因子（|corr|>0.7提示共线性）

5. **因子换手率 `calc_turnover(factor_values, top_pct=0.2)`**
   - 每期多头组合股票池的换手率（换仓比例）
   - 换手率>30%/天说明交易成本会吃掉收益，提示降低调仓频率

6. **一键生成因子报告 `generate_factor_report(factor_name, save_dir)`**
   - 输出HTML报告：IC统计+IC衰减图+分层净值+分组收益柱状图+相关性热力图
   - 直接保存到research_output/factor_reports/目录

### 5.9.8 因子合成器 `factor/combiner.py`
单因子IC低（通常0.02~0.05），必须多因子合成才实用：
1. **等权合成 `equal_weight(factor_dict, weights=None)`**：所有因子标准化后等权相加
2. **IC加权 `ic_weighted(factor_dict, ic_series, window=60)`**：用滚动IC做权重，IC高的因子权重高
3. **ICIR最大化 `max_icir(factor_dict, returns)`**：用过去N期IC协方差矩阵求最优权重，最大化组合ICIR
4. **线性/Ridge回归 `ridge_combine(factor_dict, returns, alpha=1.0)`**：用Ridge回归做因子收益预测，L2正则防过拟合
5. **去冗余合成**：合成前自动剔除|corr|>0.7的冗余因子，保留ICIR高的那个
- 合成结果是一个综合打分DataFrame，和单个因子格式完全一致，可以直接输入评估套件和策略适配器

### 5.9.9 因子→交易策略适配器 `factor/factor_strategy.py`
**这是最关键的一步：把因子打分转成能直接接入回测/模拟/实盘的BaseStrategy子类。**

实现 `FactorStrategy(BaseStrategy)`，参数全部可配：
- `factor_list`: 参与合成的因子列表（支持字符串alpha编号+自定义因子函数）
- `combine_method`: 合成方法（equal_weight/ic_weighted/max_icir/ridge）
- `universe`: 股票池（hs300/zz500/zz1000/all_a/自定义列表）
- `n_top`: 每期选前N只股票（默认Top50）
- `rebalance_freq`: 调仓频率（weekly/biweekly/monthly）
- `weight_method`: 组合加权方式（equal_weight/rank_weight/market_cap_weight）
- `single_limit`: 单只股票最大权重（默认0.05=5%）
- `industry_limit`: 单个行业最大权重（默认0.3=30%，防行业集中）
- `stop_loss`: 止损线（默认单票跌8%止损）
- `take_profit`: 止盈线（默认单票涨20%止盈）

核心逻辑：
- 调仓日：按因子打分排序，剔除停牌/ST/涨停/跌停/成交额不足的股票，选出Top N
- 按权重分配持仓，不符合单票/行业集中度限制的降权处理
- 非调仓日：只处理止损止盈
- 完全兼容T+1、手续费、涨跌停等市场规则，父类会处理

这样用户只需要配置参数，就能用任意因子组合跑完整回测/模拟/实盘，不用自己写策略代码。

### 5.9.10 股票池管理 `factor/universe.py`
- `get_hs300()` / `get_zz500()` / `get_zz1000()` / `get_zz2000()`：调用AKShare获取指数成分股（**成分股接口需要裸代码如 `000300`；而取指数行情用带前缀 `sh000300`——两者勿混用**），自动更新
- `get_all_a()`：全A，自动剔除ST、*ST、退市、上市不满60天新股
- `filter_liquidity(df, min_amount=5000万)`：成交额过滤
- `filter_pause(df)`：剔除停牌
- `filter_st(df)`：剔除ST
- `filter_limit_up_down(df)`：剔除涨跌停
- 支持自定义股票池：传入code列表即可

---

### 5.9.11 付费/外部平台因子适配器 `factor/adapters/`

所有付费适配器遵循同一接口：`get_factor(factor_name, symbols, start_date, end_date) -> DataFrame(日期×股票)`，和免费alpha接口完全一致，用户换数据源只改一行配置，上层研究/回测/实盘代码不用动。

**适配器1：Tushare Pro 官方因子库 `factor/adapters/tushare_factor.py`**
- 对接tushare pro的`pro_api.fund_daily`和官方因子库
- Tushare Pro 目前提供 **202个因子**，其中包含**31个Alpha101因子**、40+技术因子、40+基本面因子、40+情绪因子
- 数据从2010年起每日更新，已经做了复权、去极值、标准化处理，不用自己清洗
- 接口：`TushareFactor(token).get_factor('alpha001', symbols, start, end)`
- 自动处理接口限速（tushare每分钟请求次数限制）、失败重试、增量缓存
- 注意：高级因子需要2000积分以上，入门因子免费
- 配置项：`config.py`里加`TUSHARE_TOKEN = ''`，用户填自己的token

**适配器2：聚宽 JoinQuant `factor/adapters/joinquant_factor.py`**
- 对接jqdatasdk，聚宽内置了完整的alpha101和alpha191实现
- 直接调用`jq.alpha101(code_list, start_date, end_date, factor_list)`一行返回全部因子值
- 还提供400+聚宽社区因子、基本面因子、资金流因子、龙虎榜因子
- 配置项：`JOINQUANT_USERNAME = ''`、`JOINQUANT_PASSWORD = ''`
- 免费额度每天100万条，足够研究用

**适配器3：优矿 UQER `factor/adapters/uqer_factor.py`**
- 对接优矿DataAPI，优矿有自己的因子库和社区策略
- 接口同上统一规范

**适配器4：微软 Qlib 因子导入 `factor/adapters/qlib_factor.py`**
- Qlib是微软开源的AI量化平台，内置Alpha158（158个量价因子）和Alpha360（360个6日窗口因子）
- 这个适配器不需要在线账号，本地安装qlib后直接导入因子计算结果
- 支持qlib的LightGBM/MLP/XGBoost模型预测结果，直接转成本系统因子打分
- 方便把机器学习模型预测结果接进实盘

**付费适配器的统一使用方式：**
```python
from factor import create_factor_engine
engine = create_factor_engine(source='tushare')  # 或 'joinquant'/'free'（默认免费alpha101/191）
df = engine.get_factor('alpha001', universe='hs300', start='2020-01-01', end='2026-01-01')
```
用户切数据源只改一个参数，下面的评估/合成/回测完全不用改。

---

### 5.9.12 公开策略市场浏览器与导入器 `factor/market/`

**浏览器 `factor/market/browser.py`**：
- 内置多个公开策略源索引（不需要登录就能浏览基本信息）：
  - **GitHub趋势量化仓库**：每日抓取量化相关仓库star增长榜，按语言/策略类型分类
  - **聚宽社区策略**：浏览聚宽社区公开的策略（需要聚宽账号才能看代码）
  - **米筐社区策略**：同理
  - **QuantConnect策略库**：海外公开策略（英文）
  - **vnpy官方策略库**
- 支持按关键词搜索：`search_strategy('双均线'/'机器学习'/'cta趋势')`
- 展示策略：作者、star数、回测收益、夏普、最大回撤、适用市场、最后更新时间
- 注意：只做索引浏览，不自动下载代码（避免版权问题），用户点链接自己去原站看

**导入器 `factor/market/importer.py`**：
用户把下载到本地的第三方策略文件放到`strategies/imported/`目录下，自动适配：
- 自动识别来源：Qlib/backtrader/聚宽/vnpy/手写
- 自动转换策略结构到本系统的`BaseStrategy`子类：
  - backtrader的`next()` → 转成`on_bar()`
  - 聚宽的`initialize()`/`handle_data()` → 转成`init()`/`on_bar()`
  - Qlib的`predict()` → 转成打分型策略
- 转换后自动生成策略yaml配置文件
- 转换后提示用户手工核对（自动转换不能保证100%正确）

**安全校验器 `factor/market/validator.py`**：
导入第三方策略前自动检查：
- 有没有未来函数（调用future_detector扫描）
- 有没有危险操作（直接访问文件系统/网络请求/删除文件）
- 有没有过度拟合迹象（参数过多、回测夏普>5警告）
- 有没有使用不存在的API
- 给出风险评分和警告信息，用户确认后再加载

---

### 5.9.13 因子研究CLI命令（加到main.py入口）
```bash
# 免费Alpha101/191研究
python main.py factor calc --factors alpha001,alpha006,alpha023 --universe hs300 --start 2020-01-01 --end 2026-01-01
python main.py factor eval --factor alpha001 --universe hs300           # 单因子评估，生成HTML报告
python main.py factor eval-all --factors alpha001-alpha101 --universe hs300  # 批量评估全部101个
python main.py factor combine --factors alpha001,alpha006,alpha023 --method ic_weighted  # 因子合成
python main.py factor corr --factors alpha001-alpha020                  # 因子相关性热力图
python main.py factor backtest --factors alpha001,alpha006 --n-top 30 --freq weekly  # 因子组合直接回测

# 用付费数据源
python main.py factor calc --source tushare --factors ...
python main.py factor calc --source joinquant --factors ...

# 公开策略市场
python main.py market search "cta趋势"
python main.py market import ./strategies/imported/some_strategy.py    # 导入本地第三方策略
python main.py market validate ./strategies/imported/some_strategy.py  # 安全校验

# 一键因子研究全流程
python main.py factor research --universe hs300 --factors alpha001-alpha050
# 自动：计算→预处理→评估→筛选ICIR>0.3的因子→去冗余→合成→回测→输出完整研究报告
```

### 5.9.14 写测试脚本 `test_factor.py`
测试以下内容：
1. 表达式引擎各算子计算正确（和手工计算对拍）
2. Alpha101全部101个因子在随机数据上能计算、无inf、无报错
3. 预处理四步（去极值/填充/标准化/中性化）结果正确
4. 未来函数检测器能识别故意插入的未来函数
5. 因子评估套件IC/IR/分层回测结果正确
6. 因子合成输出格式正确
7. FactorStrategy能在回测引擎中运行，不报错
8. 未来函数检测、冗余因子识别能正常工作

### 5.9.15 重要提醒（必须写进注释和文档）
1. **Alpha101/Alpha191是美股/中国市场的学术因子，不是圣杯**：单因子IC普遍很低，A股部分因子失效甚至反向，必须重新评估不能直接用
2. **免费复现和付费平台的因子值可能不一致**：vwap算法、复权口径、行业分类、中性化方法不同都会导致结果差异，**不要混搭用**，选定一个数据源坚持到底
3. **因子回测一定要做样本外测试**：不能用全部数据找参数，必须70%样本内找、30%样本外验证
4. **因子≠策略**：哪怕因子IC很高，没有风控和仓位管理的因子组合实盘依然可能亏大钱
5. **避免因子挖掘过拟合**：101个因子里挑出来的"最优组合"在历史数据上一定好，不代表未来好；因子数量越多越要严格做样本外和走向前测试
6. **开源策略导入后一定要先跑回测+未来函数检查**，不要直接相信回测报告里的高收益
7. **付费平台的免费额度有限**，先用免费Alpha101/191验证思路，再决定要不要付费买高级因子

### 5.9.16 自定义因子：自己写因子的标准接口与脚手架（重要）

**结论先说：完全可以自己写因子，而且自定义因子和 Alpha101/191、付费平台因子在系统里是完全平等的**——注册之后，它一样能进因子引擎计算、进评估套件算 IC/IR、进合成器做多因子合成、进 `FactorStrategy` 跑回测/模拟/实盘，不需要改任何上层代码。

#### 一、因子的本质接口（一句话）
**一个因子 = 一个函数：输入「面板数据对象」，输出「因子值面板（DataFrame，index=日期，columns=股票代码）」**。就这么简单。

1. **接口定义**（写入 `factor/base.py` 或 `factor/__init__.py`）：
   ```python
   def my_factor(data: FactorData) -> pd.DataFrame:
       """
       data: 因子数据对象，按需返回全市场面板字段
       return: 因子值面板，index 为交易日，columns 为股票代码
       """
       ...
   ```
2. **`FactorData` 数据对象**（封装好数据、屏蔽细节、**强制防未来函数**）：
   - 属性：`data.close` / `.open` / `.high` / `.low` / `.volume` / `.amount` / `.vwap`（成交额÷成交量算得）/ `.returns` / `.cap`（市值）/ `.industry`（行业分类），全部是**日期×股票**的面板
   - 方法：`data.close_shift(n)` 取前 n 日收盘（内部就是 `shift(n)`，**禁止负向 shift 导致未来函数**）、`data.pct_change(n)`、`data.rolling(n).mean()` 等
   - **防未来函数机制**：`FactorData` 内部对任何"取未来数据"的操作直接抛异常，从源头杜绝前视
   - 若某字段（如 `.cap` / `.industry`）数据源没有，则对应的中性化开关自动降级并告警，不静默出错
3. **注册方式**：用装饰器登记，系统自动发现
   ```python
   from factor import register_factor

   @register_factor("my_momentum")   # 注册名，之后就用这个名字调用
   def my_momentum(data: FactorData) -> pd.DataFrame:
       return data.close.pct_change(20)          # 20日动量
   ```
   - 也可把自定义因子集中写在 `factor/custom.py` 里，`factor_engine` 启动时自动导入注册
   - 注册后可用名称调用：`['alpha001', 'my_momentum']` 混用，引擎一视同仁
4. **脚手架 `tools/new_factor.py`**：一键生成自定义因子模板
   - `python tools/new_factor.py --name my_alpha --desc "量价背离因子"`
   - 自动产出：`factor/custom.py` 里追加函数骨架（含接口注释和 TODO）、一个 `tests/test_my_alpha.py` 测试骨架、并打印"如何注册、如何评估"的提示
5. **自定义因子必须自带测试**（脚手架会生成骨架）：
   - **未来函数检测**：调用 `factor/future_detector.py` 做 lead/shift/扰动检验，**不通过不允许进入下一步**
   - **IC 评估**：`python main.py factor eval --factor my_alpha`，看 IC/ICIR 是否达标
6. **示例自定义因子**（写进 `factor/custom.py` 作参考）：
   - `my_momentum`：20日动量 `close.pct_change(20)`
   - `my_volume_price_div`：量价背离，价格与成交量 10 日相关系数取负
   - `my_turnover_reversal`：换手率反转，高换手取负分
   - `my_intraday_strength`：日内强度 `(close-low)/(high-low)` 的 N 日均值
7. **性能与规范要求**：
   - **必须向量化**（用 pandas 整体运算，禁止逐股票 for 循环），否则全市场计算会极慢
   - 统一用 `FactorData` 提供的方法取数，**不要自己再去读原始数据**
   - 返回值必须是 `日期×股票` 面板；缺失值保持 NaN，**不要在因子内部做去极值/标准化/中性化**（这些由 `preprocess.py` 统一处理，避免重复且口径不一致）
8. **和现有流程的衔接**：自定义因子写入后，**和内置因子走完全相同的链路**——
   `factor calc → eval → 筛选（ICIR>阈值）→ 去冗余 → combine 合成 → FactorStrategy 回测/模拟/实盘`，无需任何额外适配。
9. **写测试 `test_custom_factor.py`**：注册一个示例自定义因子，验证「能被引擎发现、能算出非空面板、通过未来函数检测、能进评估套件出 IC 报告」全链路通。

> 一句话记忆：**写因子只要管"算分"这一件事，取数、防未来、预处理、评估、合成、回测、实盘，全部是现成的，注册一下就能用。**

---

## ===== 第 6 步：全市场透明回测引擎 =====

创建 `core/backtester.py`，实现一个**简单透明、逐K线驱动、支持所有市场**的回测引擎，不依赖第三方回测框架（如backtrader/vnpy），代码可读性优先，让你能看懂每一笔成交怎么发生的，不会出现黑箱bug。

### 6.0 开工前置：闸门随引擎迁移（v3.23 新增）

> **开工前置**：本步会**替换**第 5 步的轻量执行器 `core/runner.py`。闸门（预热 `warmup_ok`、数据时效、末根预热）**不得**留在被替换的执行器里，必须**引擎无关**。

**为什么必须放在本步**：凡写在 `core/runner.py` 里的闸门逻辑（`warmup_ok` 逐 bar 注入、末根预热不出信号、`assert_signal_frame` 拦截 `fillna`）都会随第 6 步替换**静默消失**——而本步正文（`core/backtester.py`）对此**零引用**，与上一轮「第 5 步正文零引用」是同一个错误的**第二次复制**。新引擎一上线，就在**没有闸门**的接口上产出信号，预热期 `fillna(0)` 照样把 `RSI` 变成「极度超卖」发买入信号，且不报错。

1. **闸门唯一实现、引擎无关**：预热闸门与数据时效闸门的裁决入口统一放在 `core/signal_gate.py`（或 `BaseStrategy` + `place_order`），`Backtester` **只调用、不重写**；`config.GATE_CONFORMANCE['gate_module']` 指定该模块。
2. **引擎必须供给 `warmup_ok`**：`run()` 第 1 步构建 `bar_dict` 时，每个标的数据**必须带** `warmup_ok` 列；**缺列即报错**（不得静默放行）。
3. **下单收口**：本步引擎产生的**开仓方向**订单（含调仓买入）必须过 `place_order` 的预热闸门（`warmup_ok=False` 拒）；**强平 / 到期结算 / 回测结束强制平仓 / 止损**等**平仓方向**豁免（`sell`/`cover` 放行）——与 `STALE_REFETCH_FAIL_POLICY` 的「开严平宽」同则。
4. **长度检查不得硬编码**：数据长度门槛改为 `max(60, strategy.required_bars())`，**禁止**硬编码 60（`MACD` 的 `DEA` 收敛约 70+ 根；60 根会让标的「通过检查后全段落在预热期」→ 回测**静默零成交**）。
5. **引擎一致性测试**：写一个**不依赖具体引擎**的测试——同一份「预热期 bar + 已 `fillna(0)`」的指标帧，在轻量 `runner` 与 `Backtester` 下调用 `buy()` **都被拒单**；并断言 `Backtester` 的 `bar_dict` 确实带 `warmup_ok` 列。
6. **多标的对齐的存续**：第 2 步数据准备「对齐标的日期索引、取交易日交集」时，`data_asof_date` / `price_adjust` / `warmup_ok` 三个物化列**必须逐标的保留**（按 `symbol` 分组），不得因 `concat`/对齐退化成一列一个值。
7. **成交模型与风控也须「引擎无关」（v3.24 补充）**：闸门之外，本步新建的**成交模型**（滑点 / 涨跌停 / 量限 / 撮合）与**风控**（单票仓位 / 日内亏损 / 黑天鹅 / 强平）同样**只允许有一份引擎无关的实现**（`core/execution.py` + `core/risk.py`），`Backtester` **只调用、不重写**，且**不得挂死在「回测 account」上**——第 7 步模拟盘、第 12 步实盘要共用同一份；否则三环境各写一套，回测的「写实性」传不下去，「模拟盘—回测偏差告警」会被**已知的结构性差异**触发。

### 核心类 `Backtester`：
1. **初始化参数**：`strategy_class, strategy_params, symbols, start_date, end_date, initial_capital, benchmark, market_type=None`
   - 如果传了market_type就强制用该市场规则，不传则自动识别每个标的
   - benchmark默认 **`sh000300`**（沪深300，走指数专用接口）；⚠️ **必须带 `sh` 前缀**，裸写 `000300` 会被误判为深市个股（见 1.0 节六·铁律 8）

2. **数据准备**：
   - 调用DataFetcher获取所有symbols指定时间段的日线数据
   - 获取基准数据
   - 对齐所有标的日期索引，取交易日交集（有些标的上市晚要截断）
   - 检查数据长度，少于60根K线直接报错拒绝回测（不够计算指标）
   - **未来函数自动检查**：对所有标的数据，检测close/high/low是否有lead（用shift检查），有问题直接报错

3. **回测主循环 `run()`**：
   - 初始化TradingAccount账户
   - 初始化策略实例，调用strategy.init()预热指标
   - 按日期逐天遍历：
     1. 构建当日bar_dict：所有持仓和候选标的当日OHLCV
     2. 先处理开盘前的订单（限价单成交检查）
     3. 调用strategy.on_bar(date, bar_dict)，让策略产生信号
     4. 市价单按当日开盘价+滑点成交，限价单检查是否在当日高低价范围内成交
     5. 处理当日所有成交后，更新账户所有持仓的浮动盈亏
     6. 处理杠杆品种的保证金检查，触发强平
     7. 处理当日到期的期权、国债逆回购
     8. 调用strategy.on_end_of_day(date)
     9. 调用account.end_of_day()记录当日权益
   - 回测结束后强制全部平仓（回测结果不保留持仓）
   - 返回BacktestResult结果对象

4. **滑点与成交模拟**（非常重要，避免回测过度乐观）：
   - 市价单滑点：买入价=开盘价×(1+slippage)，卖出价=开盘价×(1-slippage)
     - **（v3.25）撮合价基准必须参数化，且成交 bar 必须「严格晚于」信号 bar**：上面的「当根开盘价」只有在**决策发生在上一根收盘**时才合法；若 `on_bar(date)` 用**当根收盘**决策、又用**当根开盘价**成交，等于**用未来信息在当下成交**（未来函数，系统性乐观）。基准取值与语义统一读 `EXECUTION_MODEL['match_price_basis']`（默认 `next_open`），并强制 `assert_fill_after_signal()`（`fill_bar_index > signal_bar_index`）；**禁止**各引擎自行写死「当日开盘价 / 当日收盘价」。
   - 涨停买不进、跌停卖不出：当日涨停且开盘即涨停时买单不成交，跌停卖单不成交
   - 成交量限制：单笔成交量不超过当日总成交量的1%（避免小盘股成交不真实）
   - T+0/T+1严格按照市场规则
   - 交易成本完全用config里的真实费率，不要理想化设置0手续费

   > **引擎无关共享（v3.24 新增）**：以上滑点 / 涨跌停 / 量限 / 撮合的**实现必须放在 `core/execution.py`（引擎无关、单份实现）**，`Backtester` **只调用、不重写**；**禁止**把成交模型挂死在「回测 account」上——否则第 7 步模拟盘、第 12 步实盘只能各自重建一套，三环境逻辑必然漂移。三环境差异**只允许参数化**：`EXECUTION_MODEL['slippage_multiplier']`（回测 1.0 / 模拟盘 2.0 / 实盘 2.0）。
   > **量限须按市场分档**：「单笔不超当日成交量 1%」是**全市场硬编码**，对大盘股形同虚设、对小盘股又过松——须改用 `EXECUTION_MODEL['volume_limit_pct_by_market']`（按市场取档）；净值型（`cn_fund` / `cn_reverse_repo` 等）走净值透传、**不做量限**。
   > **每项简化须标注偏差方向**：`EXECUTION_MODEL['bias_direction']` 记录每项「已知简化」（卖出滑点按开盘统一 / 涨跌停仅判开盘即封板 / 量限分档 / 净值透传）的**乐观或悲观方向**，供回测—模拟—实盘偏差**归因**；未标注方向的简化，在偏差分析里等于**不可解释的噪声**。

5. **绩效指标计算 `calc_metrics()`**，输出以下指标：
   - 收益类：总收益率、年化收益率、基准收益率、超额收益
   - 风险类：最大回撤、最大回撤开始/结束日期、最大回撤天数、年化波动率、下行风险
   - 风险调整：夏普比率、索提诺比率、卡玛比率、信息比率
   - 交易类：总交易次数、胜率、盈亏比、平均每笔收益、平均持仓天数、最大连续亏损次数、最大单笔盈利/亏损
   - 杠杆类（期货/外汇/期权）：平均杠杆、最大杠杆、保证金使用率、爆仓次数
   - 胜率分市场统计、分多空方向统计

6. **结果可视化 `plot_results(save_path)`**，生成以下图保存到results目录：
   - 账户净值曲线 vs 基准曲线（双轴）
   - 回撤曲线图（填充回撤区域）
   - 月度收益率热力图
   - 每笔交易盈亏分布图（柱状）
   - 持仓市值饼图（按市场分类）
   - 期货/杠杆品种额外加：保证金占用曲线、杠杆率变化曲线
   - 期权策略额外加：IV曲线、希腊字母时间序列

7. **结果保存**：
   - 所有交易记录保存到CSV：`backtest_results/{策略名}_{时间}_trades.csv`
   - 每日权益曲线保存到CSV
   - 绩效指标保存到JSON
   - 回测图保存为PNG
   - 生成简洁的文本回测报告打印到控制台

8. **常见回测陷阱自动检测**（回测结束后打印警告）：
   - 未来函数检测（再次确认）
   - 幸存者偏差警告（只用当前上市标的回测会有问题）
   - 过拟合警告：如果参数最优值在非常窄的区间内，提示过拟合风险
   - 流动性警告：交易了日均成交额<500万的标的
   - 盯市滑点警告：滑点设置过低时提示实盘可能滑点更大

9. **写 `test_backtest.py` 测试脚本**：
   - 用双均线策略回测600519近3年数据
   - 用海龟策略回测螺纹钢近3年数据
   - 用基金定投策略回测161725近5年数据
   - 三个回测都能跑完、指标正常、图表生成出来就算通过
   - 特别验证：T+1规则下当天买不能当天卖；期货保证金计算正确；手续费总和符合预期。

---

## ===== 第 7 步：模拟盘交易 =====

### 7.0 开工前置：第三种引擎——闸门/成交/风控都不得各住各的家（v3.24 新增）

> **开工前置**：本步是本项目的**第三种引擎**（回测 `core/backtester.py` → 模拟盘 `core/paper_trader.py` → 实盘 `core/live_trader.py`）。第 5→6 的教训是「闸门随引擎替换静默消失」；本步**同一个错误会第三次复制**，并额外暴露两类「各住各的家」的分裂——**开工前必须先纠正**。

1. **闸门必须由本引擎真正供给**（第三次复现的防线）：`PaperTrader` 喂给 `on_bar(date, bar_dict)` 的每一根 bar **必须带 `warmup_ok` 列**（缺列即**报错**，不得静默放行），并**调用** `core/signal_gate.py`、**不得重写**；开仓方向过 `place_order` 的预热闸门（`warmup_ok=False` 拒），强平 / 止损 / 到期结算等**平仓方向豁免**。**模拟盘末根 bar 仍在预热期时一律不出信号**（对齐 `config.INDICATOR_WARMUP_GUARD['live_reject_if_last_bar_in_warmup']`）。
2. **成交模型引擎无关、单份实现**：`core/execution.py` 是成交模型（滑点 / 涨跌停 / 量限 / 撮合）的**唯一实现**，`backtest` / `paper` / `live` **三处共用、只调用不重写**；三环境差异**只允许通过参数**体现（如 `EXECUTION_MODEL['slippage_multiplier']`：回测 1.0、模拟盘 2.0、实盘 2.0）。**禁止**在本步另写一套撮合；第 6 步的 `ExecutionModel` 若已挂死在回测 account 上，须**抽出来**放进 `core/execution.py`。
3. **风控引擎无关、单份实现**：`core/risk.py` 是风控（单票仓位上限 / 总杠杆上限 / 日内亏损上限 / 黑天鹅保护 / 强平）的**唯一实现**，三环境共用，`config.RISK` 是唯一参数源。**禁止**只在模拟盘加风控、回测不加——否则「模拟盘—回测偏差告警」会被**已知的结构性差异**触发（回测无风控、模拟盘有风控，偏差必然出现）。
4. **三引擎一致性测试**（`test_engine_consistency.py`）：同一份行情 + 同一策略 + 同一初始资金，在 `backtest` 与 `paper` 下**逐笔成交与末值权益必须一致**；差异**仅允许**来自 `slippage_multiplier`，且须可解释。
5. **「偏差超过 5% 告警」的前提**：该告警只有在**闸门 / 成交 / 风控三者共用**的前提下才有意义。实现前先断言 `ENGINE_CONFORMANCE['must_share']` 的三个模块**真的被本引擎 import 且未被重写**；否则告警只会持续误报。
6. **不变量**：本步只接**真实行情**、**不接真实资金/报单**；`place_order` 的时效闸门（第 4 步 `refetch`）与预热闸门（第 3/4 步）**照常生效**，模拟盘**不得**为「跑出成交」而绕过。

创建 `core/paper_trader.py`，对接真实行情，用模拟账户实时/按日撮合，和回测引擎用同一个TradingAccount类，保证回测和模拟逻辑一致。

### 核心类 `PaperTrader`：
1. **初始化参数**：`strategy_class, strategy_params, symbols, initial_capital, data_fetcher`
   - 模拟账户数据持久化到 `data_cache/paper_account.json`，重启不丢失
   - 如果已有账户文件，加载已有持仓和资金，不重新初始化

2. **行情驱动**：
   - `run_daily()`：按日频运行，适合中低频策略；**撮合价基准统一读 `EXECUTION_MODEL['match_price_basis']`（默认 `next_open`，成交落在信号 bar 的下一根）**，**不得在本处写死「当日收盘价撮合」**——原表述与本条第 3 项「与回测引擎保持完全一致的撮合逻辑」自相矛盾（回测按开盘价撮合），已按参数化收敛（见 7.0 与第 6 步「撮合价基准」条款）。
   - `run_intraday(interval_minutes=5)`：分钟级运行，适合可转债、期货、加密货币等日内策略
   - 交易时间自动判断：非交易时段不产生撮合，跳过节假日

3. **订单成交逻辑**：
   - 与回测引擎保持完全一致的撮合逻辑、手续费计算、保证金规则
   - 模拟滑点比回测稍大（用2倍滑点，更贴近实盘）
   - 订单状态：pending → filled/partial/canceled
   - 当日未成交限价单收盘自动撤销

4. **订单管理**：
   - 支持挂单、撤单、改单
   - 支持止损单、止盈单、移动止损单（条件单）
   - 支持一篮子调仓订单（同时买卖多个标的）

5. **风险控制**：
   - 单票仓位上限
   - 总杠杆上限
   - 日内亏损上限：当日亏损超过总资金5%自动停止交易
   - 期货/外汇/期权强平逻辑和回测完全一致
   - 黑天鹅保护：单根K线跌超10%（杠杆品种跌超5%）自动触发保护性止损

6. **记录与对账**：
   - 每笔成交实时写日志
   - 每日收盘后：结算、生成当日账单、记录账户净值
   - 支持手动对账：可以手动校正持仓、资金（比如模拟分红、拆股）
   - 模拟盘和回测结果偏差自动分析：如果偏差超过5%打印警告，可能是滑点/停牌/涨跌停导致

7. **写 `test_paper_trade.py` 简单测试**：
   - 用双均线策略跑最近10个交易日模拟盘
   - 验证账户持久化：中断重启后持仓还在
   - 验证条件单触发：设置一个止损单，价格到位后能自动成交

---

## ===== 第 8 步：定时盯盘与消息推送 =====

### 8.0 开工前置：盯盘是「第二个信号出口」——闸门与时效不得只装在下单上（v3.25 新增）

> **开工前置**：本步**不是**交易引擎，但它**直接调用 `strategy.on_tick()` 取信号并推送给用户**——这是本项目**第二个信号出口**（第一个是 `place_order`）。用户会据此**手动下单**，因此本步的闸门要求与引擎**同等严格**，只不过兜底对象从「账户」变成了「人」。

1. **盯盘喂给策略的数据必须与引擎同源**：`MarketMonitor` 调用 `strategy.on_tick()` 时，传入的数据**必须带三个物化列**（`warmup_ok` / `data_asof_date` / `price_adjust`），**缺列即报错**（`config.SIGNAL_EGRESS_CONFORMANCE['monitor_must_inject_columns']`）；**禁止**把 `data_fetcher` 的裸行情直接喂给 `on_tick`（`forbid_bare_on_tick=True`）——那等于绕开引擎。
2. **任一信号推送前必须过闸门**：调用 `core/signal_gate.py`（**只调用、不重写**）裁决；`warmup_ok=False`（预热期）**不得推送开仓 / 加仓信号**；平仓 / 减仓 / 风控类提醒**可推送**（对齐「开严平宽」）。
3. **推送前必须过时效闸门**：信号所用数据须按第 4 步 `refetch` **独立复核时效**（与 `place_order` 同源）；**停更 / 超限数据不得推送交易信号**，只能推送「数据异常」告警。
4. **交易时段必须逐市场判断**：每个市场用 `config.get_market_config()` + 交易日历判断其交易时段（A股 / 港股 / 美股含夏令时 / 期货含夜盘 / 加密 7×24），**非交易时段不推送交易信号**。本步的「时段判断」是**主功能**，**不得**像模拟盘补跑那样省略。
5. **推送消息必须自带闸门标记**：每条交易信号消息须标注「已过预热闸门 / 数据截至日期 / 是否新鲜」，让用户一眼看出该信号**能否用于实盘**；未过闸门的信号须显式标注「预热期 / 数据存疑，仅供观察」。
6. **不变量**：本步只读行情、只推送消息，**不接真实报单**；`config.SIGNAL_EGRESS_CONFORMANCE` 是本步的守卫清单。
7. **测试 `test_monitor.py`**：除通知渠道外，须含断言——① 构造**预热期 bar**，`on_tick` 产出的开仓信号**不被推送**；② 构造**停更数据**，交易信号**不被推送**（只推数据告警）；③ **非交易时段**触发检查，**不推送**交易信号。

创建 `core/monitor.py` 和 `core/notifier.py`，实现定时盯盘和信号提醒。

### `core/notifier.py` 通知模块：
1. 实现 `Notifier` 基类，支持多个渠道：
   - ConsoleNotifier：控制台打印（默认开启）
   - LogNotifier：写日志文件（默认开启）
   - WeChatWorkNotifier：企业微信机器人推送（webhook方式，可选）
   - DingTalkNotifier：钉钉机器人推送（可选）
   - EmailNotifier：邮件推送（可选）
   - BarkNotifier：iOS Bark推送（可选）
2. 统一接口：`send(title, content, level="info")`，level支持info/warning/error/critical
3. 消息去重：同一条消息10分钟内不重复发
4. 消息限流：每分钟最多发5条，防止刷屏

### `core/monitor.py` 盯盘模块：
1. 核心类 `MarketMonitor`，初始化接收 paper_trader、strategy、notifier 列表
2. 用APScheduler做调度，支持多市场多时段定时任务：
   - A股/可转债/ETF/期权：交易日9:30-11:30、13:00-15:00，每分钟检查
   - 港股：交易日9:30-12:00、13:00-16:00
   - 美股：交易日21:30-04:00（夏令时自动切换）
   - 国债逆回购：交易日9:25-15:30，最后半小时提高频率
   - 国内期货：交易日9:00-10:15、10:30-11:30、13:30-15:00、夜盘按品种
   - 国际期货：24h电子盘，按品种交易时段
   - 加密货币：7×24小时运行，可自定义间隔
3. **监控事件**：
   - 策略信号触发：开仓/平仓信号，推送标的、方向、价格、理由
   - 价格预警：持仓标的涨跌幅超过±5%、创20日新高/新低
   - 成交量异动：成交量是20日均量2倍以上
   - 止损止盈触发
   - 保证金预警：期货/外汇保证金比例低于150%
   - 涨停/跌停：持仓涨跌停
   - 期权到期：持仓期权3天内到期
   - 主力换月：期货主力合约切换提前3天提醒
   - 基金净值更新：当日净值更新，定投扣款日提醒
   - 逆回购利率飙升：GC001利率超过3%、季末年末超过5%提醒
   - 交易日历提醒：节假日、休市、美股夏令时/冬令时切换
4. **盯盘数据**：每次检查时调用data_fetcher获取实时行情，传入策略的on_tick方法
5. **防封IP**：请求严格遵守频率限制，出错自动重试，连续失败5次暂停10分钟
6. **启动方式**：`monitor.start()` 进入事件循环，支持Ctrl+C优雅退出，退出前保存账户状态
7. **后台运行**：提示用户可以用nohup/pm2/systemd在后台常驻运行

### 写 `test_monitor.py`，测试通知渠道能正常发消息（先用console notifier）。

---

## ===== 第 9 步：自动复盘报告生成 =====

### 9.0 开工前置：复盘报告是「第三个输出口」——只报成交、不报拦截，等于替闸门掩盖（v3.27 新增）

> **开工前置**：本步**不是**交易引擎，但它有**两个口子通到用户**：一是把**已发生的结果**总结给人看，二是把**「明日计划 / 候选标的」这类前瞻性建议**推给人。前者若只呈现「成交了什么」，就会**把闸门的拦截静默抹掉**；后者在性质上**就是一份推送信号**——是继 `place_order`、`monitor_push` 之后的**第三个信号出口**。两者都必须与引擎 / 闸门**同源**。

1. **报告的信号 / 成交 / 持仓必须与引擎同源**：一律取自引擎的**同一份记录**（`account.trades`、`signal_gate` 的**裁决日志**、`bills`），**禁止** `Reporter` 自己重跑一遍策略、或另算一套口径——否则报告里的数字与回测 / 实盘对不上账。
2. **「被拦掉的信号」必须可见（本步核心）**：报告**必须**逐项列出并计数**被闸门拦截的信号**及其原因——预热期（`warmup`）/ 停更（`stale`）/ 非交易时段（`off_session`）/ 涨跌停买不进卖不出（`limit_up_down`）/ 量限截断（`volume_limit`）/ 风控拦截（`risk_block`）（`config.REPORT_CONFORMANCE['suppression_reasons']`）。
   - **「0 笔交易」不得笼统显示为 0**，必须拆解为「**策略无信号**」与「**闸门拦截 N 笔**」（`zero_trade_disclosure=True`）——否则第 2 步 fail-closed 锁死、第 6 步「零成交」这类**症状在报告里完全不可见**，用户会误判「我的策略没用」。
3. **「明日计划 / 候选标的」是未登记的信号出口**：它是**前瞻性、推给用户看的「建议」**，性质与第 8 步盯盘推送相同 → **必须列入** `config.SIGNAL_EGRESS_CONFORMANCE['signal_egress_points']`（新增 `report_plan`），并过 `core/signal_gate.py`（只调用、不重写）与**时效闸门**；**预热期 / 停更 / 非交易时段的标的不得进入候选清单**（或显式标注「预热期 / 数据存疑，仅供观察」），且须标注**数据截至日期**。
4. **绩效口径必须同源**：周报 / 月报的胜率、盈亏比、最大回撤、年化收益等，必须复用**引擎或第 3 步 `eval_` 评估类指标的同一实现**，**禁止** `Reporter` 自算一份（否则报告数字与回测 / 实盘不一致，用户无从对账）。
5. **报告自动发送同样受时效闸门约束**：本步第 6 项「生成后自动推送到配置的通知渠道」走的仍是第 8 步 `notifier`，其推送前须过时效闸门（与 `place_order` / `monitor_push` 同源）。
6. **测试 `test_reporter.py`**：须含断言——① 构造「闸门拦掉 N 笔信号」的场景，报告**显式列出 N 笔及其原因**（不是静默 0）；② 构造预热期 / 停更标的，断言其**不进入**「明日候选」清单（或标注为仅供观察）；③ 断言报告绩效数字与引擎**同源**（同一输入下两者一致）。


创建 `core/reporter.py`，自动生成每日/每周/每月复盘报告，HTML格式美观易读。

### 核心类 `Reporter`：
1. 初始化参数：paper_trader/backtester对象、report_dir
2. **日报 `generate_daily_report(date)`**，包含：
   - 账户概览：当日盈亏、总盈亏、总权益、仓位比例、可用资金
   - 持仓明细：每个标的持仓数量、成本、现价、浮盈浮亏、当日涨跌
   - 当日交易：今天所有买卖记录、盈亏
   - 分市场盈亏统计：A股/期货/美股/港股等各市场分别赚了多少
   - 风控检查：保证金比例、仓位上限是否合规
   - 信号汇总：策略今天产生了哪些信号，执行了哪些
   - 明日计划：明日候选标的、需要关注的事件（期权到期、期货换月、美联储议息、财报等）
   - 市场情绪：当日大盘涨跌、涨跌家数、涨停跌停数、两市成交额、北向资金

3. **周报/月报** 在日报基础上增加：
   - 周/月收益率曲线
   - 月度收益热力图
   - 策略绩效统计（胜率、盈亏比、最大回撤）
   - 所有交易盈亏分布
   - 最大盈利/亏损交易复盘
   - 策略参数评估（是否需要调参）

4. **回测专项报告**：生成详细的回测HTML报告，包含：
   - 策略概述与参数
   - 所有绩效指标表格
   - 净值曲线、回撤图、月度热力图等全部图表
   - 交易明细表格（可下载CSV）
   - 分年度收益统计
   - 风险提示和改进建议

5. **报告格式**：
   - 用Jinja2模板渲染HTML，样式简洁美观（内联CSS，单文件，可直接发邮件或在浏览器打开）
   - 图表用plotly生成交互式图（可缩放查看），无plotly时降级为matplotlib静态图
   - 支持导出为PDF（可选，需要额外安装wkhtmltopdf）

6. **报告自动发送**：对接notifier，生成后自动推送到配置的通知渠道。

---

## ===== 第 10 步（合格投资者层）：私募/资管/信托净值型回测模块 =====

> **重要提醒**：以下5个模块属于**合格投资者层**产品，个人需满足资产/收入门槛才能购买。本系统仅做**净值分析、FOF组合回测和资产配置模拟**，不接入任何实盘下单通道。私募/资管产品流动性差、锁定期长、净值披露延迟，仅适合做资产配置和低频择时研究，**不适合短线交易**。
>
> 本模块共覆盖：①私募证券基金、②券商资管/信托/私募理财、③新三板股票、④公募REITs、⑤场外衍生品定价模拟（禁止个人实盘）

### 10.0 开工前置：本步是系统第一次「对外」——合格投资者是「每个动作的闸门」，不是「一次性资格标记」（v3.28 新增）

> **开工前置**：前九步的闸门（时效 / 预热 / 成交 / 风控 / 信号出口）保证的是「**算得对**」——它们失守，亏的是**自己的钱**。第 10 步第一次把系统**对外**：净值曲线、业绩、候选产品都可能被**投资者**看到，合格投资者门槛是**法律红线**——它失守是**违法**（向非合格投资者募集将没收违法所得并处罚款；夸大过往业绩属误导性陈述）。因此本步有两个必须落地的闸门，而它们与前面几轮踩过的坑**同构**。

1. **合格投资者 / 适当性校验必须是「每个申购·受让动作的闸门」，不是「一次性资格标记」（本步核心）**：
   - 现状风险：`QIChecker` 若只在「**尝试加入品种前**」校验一次（`check_current_threshold(asset_profile)`），则此后**追加申购、份额转让、代持、拆分份额、变换持有人**全部绕过——这正是第 2 步 `for_trading` 默认放行、第 9 步「报告只报成交」的**同一族错误：守卫活在一个「此后不再触发」的位置上**。
   - **现行规则明确要求两端都评**：《资产管理信托管理办法》（2026-10-30 发布、2027-01-01 施行）把合格投资者评估**钉在「买入」与「转让份额」两个环节**，且**单只产品投资者不超过 200 人**（`config.QUALIFIED_INVESTOR_RULES['published_2026']`）；
   - **必须穿透核查**：以合伙企业 / 契约等非法人形式汇集资金投资的，须**穿透核查最终投资者是否为合格投资者、并合并计算人数**；**严禁**拼单 / 代持 / 拆分份额 / 借用他人名义（`forbid_pooling_nominee_split=True`）；
   - **校验必须收口在动作闸门、且 fail-closed**：`check_*` 结果不是「返回 `(bool, reason)` 供参考」，而是**不过即拒绝该动作**（`on_fail="reject"`），与 `place_order` / 申购闸门同一收口（`check_actions` 至少含 `subscribe` / `transfer` / `additional_subscribe` / `nominee_change`）；`10.5` 的 `qi_threshold_check` 只是「**提醒**」——**提醒 ≠ 拦截**，资产缩水到门槛以下后，系统必须**拦住后续申购**，而不是只发一条提醒；
   - **每次校验留痕**（`audit_log_required`），供监管与纠纷举证；
   - **三套门槛不得混用**：私募基金（证监会令第105号：个人金融资产≥300万 **或** 近三年年均收入≥50万；单只≥100万）、资管产品（银发〔2018〕106号：2 年以上投资经历 **且** 家庭金融净资产≥300万 / 家庭金融资产≥500万 / 近 3 年年均收入≥40万；单只固收≥30万·混合≥40万·权益及衍生品≥100万）、信托计划（银监会令2007年第3号：单只≥100万；个人或家庭金融资产≥100万 **或** 近三年年均收入≥20万 / 夫妻合计近三年年均≥30万；单只自然人≤50 人）。**2026 年新规须区分「已发布待施行」与「征求意见稿」，不得笼统写「尚未生效」**。

2. **净值口径「美容」是本步特有的合规风险：必须分清「产品层毛净值 / 产品层费后净值 / 投资者层费后净值」，对外披露一律用投资者层费后净值**：
   - `NavBacktester` 已有申购费 / 赎回费 / 管理费 / **业绩报酬（高水位法）**，但**单一产品净值曲线在数学上算不出「投资者费后净值」**——**carry 是 per-investor 的**（不同申购时点 → 不同高水位 → 不同计提），不同投资者看到的费后净值本就不同（`config.NAV_PRODUCT_CONFIG['carry_is_per_investor']=True`）；
   - 若对外展示的「组合净值曲线」用的是**产品毛净值**，则业绩**系统性高估**（管理费 1–2%/年 + carry 20%，十年维度可吃掉累计收益的 40–50%）；
   - 因此必须**显式区分三层净值**（`nav_layers`），**披露口径固定为 `investor_net`**。

3. **净值披露滞后 = 结构性未来函数（与第 7 步 `assert_fill_after_signal` 同族）**：
   - 私募 / 资管 / 信托净值通常是**周频或月频，且披露滞后**（周五净值次周一/二才披露）；
   - 若回测「按净值披露日调仓」而**未建模滞后**（直接用当期净值决策），就是用**尚未披露**的净值交易 = 未来函数；净值型样本本就稀（月频十年仅约 120 个点），一次未来函数即可显著抬高回测收益；
   - 须强制 **`决策日 >= 披露日 + 滞后期`**（`enforce_decision_after_disclosure=True`），并加断言；
   - 净值序列**禁用 K 线类指标**（对接第 3 步 `nav_only_markets` 红线：`forbid_nav_as_kline=True`）。

4. **对外披露是「第四个输出口」**（继 `place_order` / `monitor_push` / `report_plan` 之后，面向**投资者**，具合规效力）：
   - 报告 / 净值材料必须与**引擎同源**、**含费用明细**（申赎费 / 管理费 / 业绩报酬 / 托管费）、**含被抑信号**、**明确标注「回测 / 模拟 / 实盘」**、**附风险揭示**（`config.DISCLOSURE_CONFORMANCE`）；
   - **禁止只报最有利区间**（`forbid_selective_period=True`），**禁止出现「保本 / 保收益 / 零风险」字样**（`forbid_guarantee_wording=True`）——信托办法第八条明文禁止夸大介绍过往业绩、禁止承诺保本保收益；
   - `10.5` 新增的 `notifier` 提醒属**信息 / 风险提醒**（可推，开严平宽），但**须在信号出口清单登记**（`investor_disclosure`）。

5. **测试 `test_qi_check.py` / `test_nav_backtest.py` / `test_qi_monitor.py`** 须含断言：① 合格投资者**不达标者在「追加申购」与「份额转让」两个动作上均被拒**（不只是首次准入）；② 穿透核查——以合伙企业汇集资金时，**最终投资者不达标则整体被拒**；③ 净值披露滞后——构造「披露日之后才有数据」的场景，断言**决策日早于披露日时不出信号 / 不下单**；④ 对外披露材料**含费用明细与被抑信号**、且**不含**「保本保收益」字样。

---

### 10.1 合格投资者门槛校验模块 `core/qualified_investor.py`

实现一个 `QIChecker` 类，在尝试加入这些品种前自动校验：
- `check_current_threshold(asset_profile)` ：校验是否满足**2014年暂行办法**现行门槛（私募基金：金融资产≥300万或年均收入≥50万，单只≥100万）
- `check_amr_threshold(asset_profile, product_type)` ：校验**资管新规**门槛（家庭金融资产≥500万/净资产≥300万/年均收入≥40万，分30/40/100万三档起投）
- `check_neeq_threshold(asset_profile, layer)` ：校验新三板门槛（创新层100万/基础层200万+2年经历）
- `check_otc_institutional_threshold(asset_profile)` ：校验场外衍生品机构门槛（净资产≥5000万/金融资产≥2000万/3年经历），并对个人用户抛出`OTCForbiddenError`
- `check_proposed_2026_rule(asset_profile)` ：按2026年9月征求意见稿口径校验（家庭金融资产≥500万+2年经历，特殊品类1000万+4年），明确标注**该规则尚未正式生效**，仅做预判参考
- 每次校验返回 `(bool, reason)` 元组，True/False + 不通过原因说明
- 门槛数值全部从 `config.py` 读取，不硬编码

写 `test_qi_check.py`，模拟几组不同资产规模的投资者profile，验证门槛校验逻辑正确。

---

### 10.2 净值型资产数据层 `data/fetcher_nav.py`（私募/资管/信托/公募REITs共用）

净值型品种没有高频K线，只有周/月度披露的单位净值，需要单独的数据获取器：
1. **私募证券基金**：
   - 由于私募净值数据不公开，AKShare可获取到的字段有限，实现`fetch_private_fund_nav(code)`：
     - 优先尝试 `ak.fund_private_equity_amac_fund_info()`（基金业协会备案查询）
     - 若公开接口拿不到，设计一个`manual_nav_import(csv_path)`方法，支持导入用户自己收集到的净值CSV文件（格式：date, nav, accum_nav）
     - 返回标准化 DataFrame：`date | nav | accum_nav | source`
     - 自动检测净值披露频率（daily/weekly/monthly），记录元信息
2. **券商资管/信托/私募理财**：
   - 同样走`fetch_qii_product_nav(code)`，优先尝试公开接口，失败则提供CSV导入
   - 按 `product_type`（fixed_income/mixed/equity/derivatives）分类，记录起投金额、锁定期、开放频率
3. **公募REITs**（数据最公开）：
   - `fetch_reits_daily(symbol)`：用 `ak.reits_realtime_em()` 和 `ak.fund_reits_hist_em()` 获取日线行情（场内交易价）
   - `fetch_reits_indicator(symbol)`：用 `ak.fund_reits_indicator_em()` 获取净值、分派率、折溢价率等指标
   - `fetch_reits_dividend(symbol)`：获取历史分红记录
   - 合并成带**折溢价率**字段的DataFrame：`date | open | high | low | close | volume | nav | premium_pct | dividend_accum`
   - REITs普通账户可买，但需要支持强制分红的除权处理
4. **新三板**：
   - `fetch_neeq_daily(symbol, layer)`：优先尝试 `ak.stock_neeq_hist()`，兜底用 `ak.stock_zh_a_hist()`
   - `fetch_neeq_list(layer)`：获取基础层/创新层全部挂牌公司列表
   - 自动过滤`零成交日`（成交量=0的日期），标记为停牌/无成交，回测时跳过
   - 必须包含`delisting_warning`列，标记ST/退市整理期股票
5. 所有净值数据都带缓存，CSV文件存`data_cache/nav/`目录，避免重复请求。
6. 写`test_nav_data.py`，测试：
   - 公募REITs历史行情（拿508000等代码测试）
   - 新三板数据获取（拿430047等老三板代码测试）
   - CSV净值导入功能

---

### 10.3 净值型策略与FOF组合回测引擎 `nav_backtest/`

净值型品种不能用逐K线撮合回测，需要一个专门的**低频净值回测器**：
1. **核心类 `NavBacktester`**（`nav_backtest/nav_backtester.py`）：
   - 输入：多只产品的净值DataFrame列表 + 策略权重/择时信号 + 初始资金
   - 频率：日/周/月频，按净值披露日调仓
   - 费用处理：申购费、赎回费（按持有期自动查表）、管理费（年化逐日计提）、业绩报酬（高水位法，对私募产品）
   - 锁定期处理：买入后锁定期内禁止赎回
   - 流动性约束：赎回T+N到账，资金到账前不可用于再投资
   - 输出：组合净值曲线、现金/各产品持仓比例、每笔申赎记录、绩效指标
2. **FOF资产配置策略模板** `nav_backtest/strategies/`：
   - `equal_weight.py`：等权重配置
   - `risk_parity.py`：风险平价（基于历史波动率加权，可用scipy简单实现，可选cvxpy）
   - `nav_momentum.py`：净值动量轮动（近N月涨幅排名，定期调仓到表现最好的K只）
   - `reits_premium_arbitrage.py`：REITs折溢价套利（深度折价买入、溢价过高卖出）
   - `neeq_value_screen.py`：新三板价值因子选股（低PB/低PE/高ROE组合+流动性过滤）
3. **绩效指标（净值型专属）**：
   - 年化收益、年化波动、夏普比率、最大回撤
   - 卡玛比率、索提诺比率
   - 信息比率（vs沪深300/中证全债基准）
   - 月度胜率、最长锁定期、赎回费占比
   - 业绩报酬计提累计金额（私募特有）
4. 写`test_nav_backtest.py`：
   - 用3-5只公募REITs做风险平价组合回测
   - 用手动构造的模拟私募净值（5只，周频）做等权重FOF回测
   - 验证高水位业绩报酬计算正确

---

### 10.4 场外衍生品定价模拟模块 `derivatives_pricing/`（⚠️ 个人禁止实盘）

> **红线警告**：本模块**仅用于学习衍生品定价原理和做蒙特卡洛模拟**，输出理论价格和希腊字母、模拟损益分布。**绝对不提供下单、不对接任何场外交易渠道、不生成任何可用于实盘交易的信号**。个人投资者直接参与场外期权/收益互换属于违规，本系统代码中必须在显眼位置打印警告。

1. **定价引擎 `derivatives_pricing/pricing.py`**：
   - `black_scholes(S, K, T, r, sigma, option_type)`：BS模型欧式期权定价 + 希腊字母（Delta/Gamma/Theta/Vega/Rho）
   - `monte_carlo_european(S, K, T, r, sigma, n_sims=100000, option_type="call")`：蒙特卡洛法定价
   - `binomial_tree_american(S, K, T, r, sigma, steps=200, option_type="call")`：二叉树美式期权定价
   - 所有计算基于scipy.stats，数值稳定
2. **雪球结构（Autocallable）定价 `derivatives_pricing/snowball.py`**：
   - `snowball_pricing(S0, ko_barrier, ki_barrier, coupon, ko_observe_dates, ki_observe_dates, r, sigma, n_sims=50000, tenor_months=24)`
   - 蒙特卡洛模拟逐日路径，输出：理论价格、敲出概率、敲入概率、未敲入未敲出概率、敲入后亏损期望、期望收益率分布
   - 支持参数：每月敲出观察、每日敲入观察、保证金式、非保证金式
   - 自动生成**损益情景图**：横轴为到期标的涨跌幅，纵轴为投资者损益
3. **收益互换（TRS）模拟 `derivatives_pricing/trs.py`**：
   - `trs_pnl_simulation(underlying_return, notional, margin_rate, financing_rate, term_days)`
   - 计算保证金占用、融资成本、浮动盈亏、强平线
4. **情景分析工具** `derivatives_pricing/scenario.py`：
   - 支持输入标的的多种涨跌路径（大涨/小涨/震荡/小跌/大跌/黑天鹅）
   - 输出每个情景下衍生品的损益和关键希腊字母
   - VaR（风险价值）计算
5. 模块顶部必须打印醒目的红色警告：
   ```
   ⚠️⚠️⚠️ 警告 ⚠️⚠️⚠️
   本模块仅用于衍生品定价理论学习和学术研究。
   中国大陆个人投资者禁止直接参与场外期权/收益互换交易。
   市面上所谓"通道""过桥"参与场外衍生品均属违规灰色业务，风险自担。
   本模块不提供任何实盘下单功能。
   ```
6. 写`test_pricing.py`：
   - 用已知的BS解析解验证蒙特卡洛结果误差<1%
   - 雪球定价：用典型参数（敲出100%、敲入75%、票息20%、24个月）跑10000次模拟，输出敲出/敲入概率
   - 验证希腊字母方向正确（call的Delta为正，put为负等）

---

### 10.5 合格投资者层盯盘提醒 + 报告扩展

1. 在 `core/notifier.py` 新增提醒类型：
   - `private_fund_nav_update`：私募/资管产品新净值披露提醒
   - `reits_dividend_announce`：REITs分红公告与除权日提醒
   - `reits_premium_alert`：REITs折溢价超阈值（如折价>10%/溢价>15%）提醒
   - `neeq_delisting_warning`：新三板持仓股发布退市风险公告提醒
   - `neeq_liquidity_deterioration`：新三板持仓流动性恶化（连续N天零成交）提醒
   - `snowball_knock_in_warning`：模拟雪球标的接近敲入线提醒（仅模拟账户）
   - `snowball_knock_out_observe`：模拟雪球敲出观察日提醒
   - `qi_threshold_check`：资产规模变动后重新校验合格投资者资格提醒
2. 在复盘报告`Reporter`中增加：
   - **FOF/净值组合页**：组合净值曲线、各产品权重变化、业绩报酬计提明细、锁定期分布
   - **REITs页**：REITs持仓折溢价热力图、分红到账记录、分派率vs国债收益率对比
   - **新三板页**：持仓涨跌停情况、成交活跃度、退市风险预警
   - **衍生品模拟页**：模拟持仓希腊字母敞口、敲入/敲出概率变化、情景分析损益表（仅模拟账户）
3. 写`test_qi_monitor.py`，验证各提醒事件能正常触发和发送。

---

## ===== 第 11 步：一键运行入口 + README =====

### 11.0 开工前置：一键入口是「控制平面」——它是全部闸门的「总旁路」；README 是「对外文档」，不得替系统承诺还没有的能力（v3.29 新增）

> **开工前置**：前九步把闸门一个个装到了「信号出口」上（`place_order` / `monitor_push` / `report_plan` / `investor_disclosure`）。第 11 步**不是**再装一个闸门，而是把**所有入口收进一个 `main.py`**——于是它成了**唯一一个「人类可以直接决定跑到哪个模式、用哪份数据、开不开闸门」的地方**。**控制平面上的一个字符串、一个开关，就能把前面所有闸门一起关掉。** 同时，README 是本系统的**对外文档**，用户会把它当规格照抄——它不能替系统承诺**还没有的能力**。

1. **运行模式（`RUN_MODE`）不得由命令行「提升」，只允许「降级」（本步核心）**：
   - 现状风险：`config.py` 末尾写着「运行模式（不要在这里改，**用命令行参数控制**）」——`RUN_MODE` 是**所有闸门的豁免开关**（`backtest` 下 stale 闸门豁免、`live_reject_if_last_bar_in_warmup` 只在 `paper` / `live` 生效）→ **改一个字符串，等于同时关掉一批闸门**；第 12 步的 `run_live.py --mode sim` 也只是一个**模式参数**。
   - 要求：`RUN_MODE` 的**唯一来源**是 `config.py` + `.env`（`run_mode_source`）；CLI 参数**只能把模式降到更安全一侧**（`live → paper → backtest`，`mode_may_only_downgrade=True`）；**提升到 `paper` / `live` 必须满足前置门禁**（`promote_requires`）：上线检查清单 `checklist` 通过 + `paper` 连续 N 个交易日无异常 + 显式确认开关——且 `checklist` 必须能「**拦住**」而不只是「打印一张清单」（**提醒 ≠ 拦截**，与第 10 步 `qi_threshold_check` 同一条）。
   - **禁止 CLI 提供任何旁路开关**：`--no-gate` / `--force` / `--skip-freshness` / `--ignore-warmup` / `--no-risk` / `--disable-gate` / `--skip-check` 一律**不得存在**（`config.CLI_CONFORMANCE['forbidden_flags']`），README 与 `--help` 中同样不得出现——**一旦存在，等于给所有引擎开了后门**；这与第 2 步 `for_trading` 默认放行、第 10 步「一次性资格标记」是**同一族错误：守卫活在一个「人类随口一句就能关掉」的位置上**。
   - `backtest` 的豁免**只允许在「回测语义」下生效**，且**必须把当前模式写进报告与结果文件**（对接第 9 / 10 步的标注要求），避免「以为在实盘、实际在回测」。

2. **参数默认值必须「集中定义、唯一来源」，禁止在 `argparse` 里写死**：
   - 风险：一键入口把十几个模块收进 `main.py`，若各子命令**各自组装参数与默认值**（`--initial-capital` / `--start` / `--for-trading` / 滑点 / 数据路径），就会出现**同一策略、同一数据、不同入口得到不同结果**——与第 7 步「成交与风控各住各的家」同源，也与 v3.10 把周期收敛到 `SUPPORTED_PERIODS` 是**同一条纪律**。
   - 要求：子命令默认值**一律引用 `config`**（`STRATEGY_DEFAULTS` / `BACKTEST_DEFAULTS` / `PAPER_TRADING` / `INDICATOR_CONFIG` / `EXECUTION_MODEL` / `RISK`），**禁止在 `argparse` 里硬编码**。
   - 若支持 `--data` / `--csv` / `--from-file` 导入用户数据：**必须走数据层出口**（挂 `warmup_ok` / `data_asof_date` / `price_adjust` 三物化列，`import_paths_must_use_data_layer=True`），否则**拒绝**——不得让 CLI 成为「裸帧」的入口。

3. **README 是「对外文档」：不得承诺尚未实现的能力，进度必须诚实**：
   - 现状风险：本步要求 README 写整节「**实盘对接指引**」（easytrader / QMT / Ptrade / tqsdk / CTP / ib_insync…），而**第 12 步（实盘接入层）还没做**；且本步「最后完整验证清单」里**已经列了第 12 / 13 步的验证项**（`run_live.py --mode sim`、`test_broker.py`、`test_risk.py`、`test_kill_switch.py`、`test_credentials.py`、`test_long_term.py`）。
   - 后果：① 用户照 README 去接实盘 → 发现根本没有；② **更糟**——为了「让清单跑通」，会**提前拼一个 `run_live.py` 并 fallback 到 `paper` / 回测** → **用户以为在实盘、实际在模拟**（与第 9 步「报告只报成交」、第 10 步「净值口径美容」同族：**标注与实际不符**）。
   - 要求：README 的实盘对接指引**按状态分节**——已实现（第 0~10 步）/ **未实现（第 12~13 步，明确标注「尚未实现，以下为规划」）**；**搭建进度看板的完成百分比必须诚实**（未完成步骤不得计入，`progress_percent_honest=True`）；验证清单**按步骤分组并标注状态**，未实现项**不得打勾**。

4. **验证清单：「未跑」≠「通过」——必须报四类计数**（延续 v3.27 对「收集错误不得豁免」的裁定）：
   - 本步的验证清单有 60+ 项，其中一部分属于第 12 / 13 步。要求：每项都必须报 **已跑 / 未跑 / 跳过 / 失败**（`checklist_mode="four_count"`），**未跑项必须显式列出并说明原因**（未实现 / 依赖缺失 / 网络限制），**严禁静默跳过、严禁把「未实现」写成「与本步无关」**——这与「报告只报成交、不报拦截」是同一种病：**清单只报「通过的」，不报「没跑的」**。
   - 离线环境用 `pytest -q -m "not network"` 跳过的联网测试，须**单独计数并列出**，不能并入「全部通过」。

5. **测试**：本步无新增业务测试，但须补「**入口一致性测试**」：① 断言**不存在** `config.CLI_CONFORMANCE['forbidden_flags']` 中的任何开关（扫描 `argparse` 定义）；② 断言把 `--mode` 由 CLI 提升到 `paper` / `live` 时**被拒绝或要求显式确认**；③ 断言子命令默认值与 `config` 中的对应常量**一致**（禁止 `argparse` 内写死）；④ 断言 `--data` 导入路径下**三物化列齐备**（缺列拒绝）。

---

1. **更新 `main.py`**，用argparse实现命令行入口，支持以下子命令：

```bash
# ==================== 零售层命令 ====================
# 回测
python main.py backtest --strategy double_ma --symbols 600519,510300 --start 2023-01-01 --end 2026-01-01

# 模拟盘
python main.py paper --strategy double_ma --symbols 600519,510300

# 盯盘（前台运行）
python main.py monitor --paper

# 生成报告
python main.py report --type daily --date 2026-10-27

# ==================== 策略研究与开发命令 ====================
# 生成策略脚手架（新建自己的策略）
python main.py new-strategy --name my_ma --template ma_cross
# 列出全部已注册策略
python main.py list-strategies
# 参数优化（输出热力图与最优参数平原）
python main.py optimize --strategy my_ma --symbols 600519 --start 2020-01-01 --end 2026-01-01 --method grid
# 走向前分析（样本外验证）
python main.py walkforward --strategy my_ma --symbols 600519 --start 2020-01-01 --end 2026-01-01 --train 12 --test 3
# 稳健性与压力测试
python main.py validate --strategy my_ma --symbols 600519 --cost-x2 --delay 1 --noise
# 查看实验记录 / 对比多次实验
python main.py experiments
python main.py compare --exp exp_0007,exp_0012
# 策略上线前检查清单
python main.py checklist --strategy my_ma

# 数据更新（手动更新缓存）
python main.py updatedata --symbols all

# 行情批量下载导出
python main.py download --symbols 600519,510300,AAPL,rb --start 2020-01-01 --format csv,parquet
python main.py download --watchlist --format parquet
python main.py download --update

# K线图绘制（单标的/带指标/多标的对比/回测结果复盘）
python main.py chart --symbol 600519 --start 2024-01-01 --indicators ma,macd
python main.py chart --compare 600519,510300,AAPL --start 2024-01-01
python main.py chart --backtest-result backtest_results/latest_result.json

# ==================== 合格投资者层命令 ====================
# 净值型FOF回测
python main.py nav-backtest --strategy risk_parity --symbols 508000,PF_001,AM_001 --start 2023-01-01 --end 2026-01-01

# REITs折溢价监控
python main.py reits-monitor --premium-threshold 0.15 --discount-threshold -0.10

# 新三板选股筛选
python main.py neeq-screen --layer innovation --factors pb,roe,volume --top 20

# 场外衍生品定价模拟（禁止实盘）
python main.py derivatives-sim --product snowball --underlying 510300 --params default

# 合格投资者门槛自检
python main.py qi-check --profile asset_profile.json
```

2. **完善 `README.md`**（第 0 步已创建骨架，本步补全全部内容）：
   - **最顶部「搭建进度看板」表格保持更新**：列出第 0~13 步全部 14 个步骤的状态、完成时间、备注，并在表格上方显示整体完成百分比
   - 项目介绍：支持的18个品种（13个零售层 + 5个合格投资者层），以及行情批量下载导出与K线图绘制能力
   - 环境安装步骤（Python版本、pip install）
   - 目录结构说明
   - 快速开始教程：怎么跑第一个回测、怎么启动模拟盘、怎么开启盯盘
   - 如何编写自己的策略（给出模板）
   - **三层市场说明**（务必写清楚）：
     - 零售层：普通账户直接可玩
     - 合格投资者层：需满足资产门槛，本系统只做净值回测和模拟，不提供实盘下单
     - 机构层（银行间/场外衍生品实盘/非标/一级市场）：本系统不支持，个人基本进不去
   - 各市场注意事项和风险提示（特别要写：外汇/加密货币/国际期货大陆无合规实盘渠道，仅供学习）
   - **合规红线警告**（独立一节，醒目位置）：
     - 外汇保证金、加密货币、国际期货：大陆无合规个人实盘渠道
     - 场外期权/收益互换：个人禁止直接参与，市面上"通道"均属违规
     - 私募/资管产品：100万起投，有锁定期，流动性差，不要用短期资金购买
     - 新三板：流动性极差、退市风险高
   - 常见问题FAQ（数据获取失败怎么办、接口报错怎么办、如何接实盘）
   - 实盘对接指引：
     - A股/ETF/可转债/REITs：easytrader对接券商客户端，或QMT/Ptrade接口（需券商开通）
     - 国内期货：tqsdk对接SimNow模拟/CTP实盘
     - 美股/港股/国际期货：ib_insync对接盈透证券（需要境外账户）
     - 公募基金：对接天天基金/蛋卷基金API（不推荐自动化下单，手动跟投即可）
     - 国债逆回购：普通券商客户端即可，自动化用easytrader
     - 期权：需期权权限，对接QMT/Ptrade
     - 外汇/加密货币：⚠️ 大陆合规风险，**强烈不建议实盘**
     - 私募/资管/信托：只能通过持牌机构渠道购买，**无法自动化下单**，本系统仅做净值跟踪和FOF回测
     - 新三板：需开通合格投资者权限，通过普通券商账户交易
     - 场外衍生品：**不提供实盘对接**，仅定价模拟

3. **最后完整验证清单**，确保以下命令都能跑通：
   - [ ] `python test_env.py` 全部通过
   - [ ] `python test_data.py` 所有可访问市场数据获取正常
   - [ ] `python test_export.py` 行情批量下载、CSV/parquet 导出、断点续传、数据概览正常
   - [ ] `python test_chart.py` K线主图（含买卖点）/指标副图/多周期切换（日周月）/形态标注/多标的并排对比/中文正常、文件落盘
   - [ ] `python test_pattern.py` 金叉死叉、MACD顶底背离、关键位突破标注正确
   - [ ] `python test_chan.py` 缠论分型/笔/线段/中枢/买卖点识别与绘图正常
   - [ ] `python test_indicators.py` 所有指标计算正常（含 OHLC 合法性、空表/全 NaN 优雅降级、少数指标逐值手算校验、复权口径校验、年化基数校验、未来函数校验）
   - [ ] `python test_account.py` 所有交易规则测试通过
   - [ ] `python test_backtest.py` 三个策略回测跑完，结果合理
   - [ ] `python test_paper_trade.py` 模拟盘账户建仓/平仓/资金与持仓更新/记录持久化正常
   - [ ] `python test_monitor.py` 盯盘信号触发与通知推送（console 渠道）正常
   - [ ] `python test_loader.py` 策略自动发现与加载正常，坏文件被隔离
   - [ ] `python test_factor.py` Alpha101/Alpha191 计算、因子预处理、评估（IC/ICIR/分层）、合成、因子回测全流程通过
   - [ ] `python test_custom_factor.py` 自定义因子注册、被引擎发现、通过未来函数检测、能进评估套件出 IC 报告
   - [ ] `python main.py factor research --universe hs300 --factors alpha001-alpha030` 一键因子研究全流程跑通并输出报告
   - [ ] `python main.py list-strategies` 正确列出全部示例策略
   - [ ] `python main.py new-strategy --name test_new --template ma_cross` 生成模板/配置/单测三个文件
   - [ ] `python main.py optimize --strategy double_ma --symbols 600519 --method grid` 参数优化跑通并生成热力图
   - [ ] `python main.py walkforward --strategy double_ma --symbols 600519` 走向前分析跑通并输出样本外净值
   - [ ] `python main.py validate --strategy double_ma --symbols 600519 --cost-x2` 稳健性测试跑通并输出评分卡
   - [ ] `python main.py checklist --strategy double_ma` 输出上线前检查清单
   - [ ] `python test_broker.py` QMT模拟盘/CTP SimNow 连接、查账户、下单、撤单全流程通过（仅仿真）
   - [ ] `python test_risk.py` 各项风控拦截正确并告警
   - [ ] `python test_kill_switch.py` 紧急停止：未成交单全部撤销、策略停止下单、审计日志与告警正常（仿真）
   - [ ] `python run_live.py --mode sim` 仿真模式全链路自检通过（不碰真实资金）
   - [ ] `python test_qi_check.py` 合格投资者门槛校验逻辑正确
   - [ ] `python test_qi_monitor.py` 合格投资者层盯盘提醒与报告扩展正常
   - [ ] `python test_nav_data.py` REITs/新三板数据获取正常，CSV导入正常
   - [ ] `python test_nav_backtest.py` REITs组合和模拟FOF回测跑通
   - [ ] `python test_pricing.py` BS/蒙特卡洛/雪球定价结果正确
   - [ ] `python main.py --help` 命令行帮助正常显示所有子命令
   - [ ] `python main.py download --symbols 600519,510300 --start 2024-01-01 --format csv` 行情下载导出正常
   - [ ] `python main.py chart --symbol 600519 --indicators ma,macd` K线图正常生成
   - [ ] `python check_progress.py` 进度看板正常显示、完成百分比正确
   - [ ] `pytest -q` 统一测试入口全部通过（离线环境可用 `pytest -q -m "not network"` 跳过联网测试）
   - [ ] `python test_credentials.py` 凭证加载/缺失校验/日志脱敏正常（第12.17节）
   - [ ] `python test_long_term.py` 多源切换/原始价与复权因子/快照/时点成分股/报告归档正常（第13步）

---

## ===== 第 12 步：实盘接入层（A股 + 国内期货，可直接实盘运行）=====

> **设计原则：默认永远是安全的。** 你不手动显式开启真实下单，所有操作都走仿真，绝不会出现"代码写错一跑就下单"的事故。
>
> 本步**只针对有境内合规实盘通道的两类**：**A股（含 ETF / 可转债 / REITs）** 与 **国内期货**。美股 / 外汇 / 加密货币 / 国际期货无境内合规个人实盘渠道，**不做实盘对接**，相关模块仅用于研究与回测。
>
> **与第 5 步的关系**：策略代码在实盘环境里**一个字都不用改**——实盘执行器 `LiveTrader` 用与回测、模拟盘完全相同的 `on_bar()/on_tick()` 接口驱动你第 5 步写好的策略，只把"撮合"换成"经风控校验后向券商/期货公司报单"。

### 12.0 开工前置：本步是系统第一次「指令能真的动到钱」；闸门、幂等、对账、急停四件事必须先想清楚（v3.31 新增）

**（1）为什么这一步的坑和前面都不同。**
前 11 步的闸门，本质上都是「对**数据**的事前检查」：数据新不新（时效闸门）、指标过没过预热期（`warmup_ok` 闸门）、这只标合不合格（QI 闸门）、这笔单该不该下（风控）。**它们检查的都是「这一刻的信息」。**
而第 12 步第一次让**一条指令真的离开本机、进入券商 / 期货公司**。从这一步起，系统要面对三类前 11 步从未处理过的问题：
- **身份**：同一条意图，会不会被执行两次？（幂等）
- **时序**：本地账本和券商账本，谁说了算？不一致时怎么办？（对账）
- **存续**：急停之后重启，急停还算数吗？（持久化）
**闸门再多，也挡不住「同一笔单被报两次」，也修不好「本地账本算错仓位」。**

**（2）🔴 必须先补：第 12 步正文对前置闸门「零引用」。**
12.7 只写「信号产生后**先过风控**，再经 `BrokerAdapter` 报单」。**风控 ≠ 闸门**：12.6 的风控管的是「仓位上不上限、亏没亏到熔断」，而第 5~11 步建立的 `core/signal_gate.py`（预热期 / 时效 / 开严平宽）在这里**一次都没被调用**。与此同时，12.2 写「自动断线重连」、12.8 写「崩溃自动重启」——**这两个特性恰恰制造了「同一信号被消费两次」的条件**。要求：
1. 实盘执行器（`live/live_trader.py`）与回测 / 模拟盘**共用同一份** `core/signal_gate.py`，**只调用、不重写**；
2. 喂给 `on_bar`/`on_tick` 的每根 bar 必须带 `warmup_ok` / `data_asof_date` / `price_adjust`（**缺列报错**），与 6.0 / 7.0 / 8.0 同一要求；
3. 报单前必须依次过 `signal_gate`（信号有效性）→ `risk`（仓位 / 亏损）→ `qi`（合格投资者，若涉净值型）→ **时效闸门（refetch 复核）**；
4. 新增「**第 12 步入口一致性测试**」：同一份「预热期 ＋ `fillna(0)`」帧，在 `Backtester` / `PaperTrader` / `LiveTrader(仿真)` 下 `buy()` **都被拒单**。

**（3）🔴 必须补：报单幂等——否则「自动重连 ＋ 崩溃重启」＝ 重复下单。**
经典事故链：
```
报单超时（其实券商已受理）→ 判为失败 → 重连重发 → 成交两笔 → 仓位翻倍
崩溃重启 → 从策略状态重算信号 → 又报一次 → 再翻倍
```
要求：
1. 每笔报单必须携带**唯一幂等键** `client_order_id`（格式见 `LIVE_SAFETY['idempotency']['format']`），并**落盘**（`persist_path`）**跨重启保留**；
2. 同键在 `dedup_window_sec` 内重复提交 → **拒绝**（`on_duplicate="reject"`）；
3. **状态未知（超时 / 断连）时禁止盲目重发**：先向券商查询该 `client_order_id` 是否已存在，确认未受理才允许重发（`on_unknown_state="query_broker_first"`）；
4. 12.14.6「废单不自动重试」保留，但那管的是**被拒**单；本条管的是**状态未知**单，**两者都要有**；
5. 补测试：模拟「报单超时但券商已受理」，断言**不产生第二笔**。

**（4）🔴 必须补：对账不是「收盘后的一件事」，而是「盘中每次下单前的事」。**
12.10 把对账放在「**收盘后**第一件事」。但 12.6 的**全部风控都读本地账本**（总资金 / 总杠杆 / 集中度 / 可用资金）——**本地账本一旦因漏记成交而失真，风控就是在错误画面上做判断**，而这个失真要到当晚收盘才被发现、次日才拦。这与第 2 步「守卫读的是会被清空 / 变味的 `attrs`」是**同一族**：**权威信息在券商侧，本地只是副本**。要求：
1. 权威状态声明为券商（`reconcile.authoritative="broker"`），本地账本视为**可能过期的副本**；
2. **每次报单前 ＋ 盘中定时**（默认 60 秒）对账；不一致 → **立即停止开新仓**并告警，直到**人工确认**（不是只写一份报告）；
3. **启动时必须对账**（`on_start`）；
4. 12.10 的**收盘对账保留**，作为**日终强校验**。

**（5）出站唯一收口：任何真实报单只允许经过一个地方。**
每接一个券商就多一条报单通道，若各适配器各自直连 SDK 报单，闸门就会被绕过。要求：
1. 报单唯一收口在 `live/live_trader.py` 的提交函数（`LIVE_SAFETY['order_port']['choke_point']`），所有适配器**只实现「发单原语」，不实现「决策」**；
2. **禁止** `broker/` 目录之外 `import xtquant` / `ths_ptrade` / CTP SDK（防绕过收口）；
3. 在 `signal_egress_points` 中登记 `live_order_submit`。

**（6）模式与凭据：禁止「静默回退」，禁止「无感」。**
12.5 写「三模式一键切换，**上层策略无感**」——恰恰相反：**用户必须时刻知道现在是哪个模式**。要求：
1. **禁止静默回退**（`forbid_silent_mode_fallback`）：实盘模式连不上券商时**必须报错停机**，**不得**自动退回仿真 / 回测；
2. 每笔报单、每条回报、每份报告都要标注当前模式（`mode_must_be_tagged_on_every_order`）；
3. 急停（Kill Switch）**状态必须持久化**（`kill_switch_persist`）：12.15 已规定「独立线程 ＋ 外部信号 ＋ 启动自检 ＋ 测试」，**补一条**——标志文件跨重启保留，**重启后仍处于停机态**；
4. 切换模式（**含降级**）前须**无持仓、无在途单**（`mode_change_requires_flat`）——降级在实盘语境下**不是「更安全」**：有仓时切回 `backtest` 等于**放弃实盘风控**；
5. 首笔实盘报单**限额**（`first_live_order_max_notional`），确认通道正常后再放开。

**（7）个人禁止实盘红线：不能只是「打印」。**
第 10 步保留了「个人禁止实盘场外衍生品」的红线警告，12.12 又要求「启动强制**打印**风险提示」。**提醒 ≠ 拦截**（同 10.5 的 `qi_threshold_check`、11.0 的 checklist）。要求：场外衍生品（雪球 / TRS / 期权组合等）在任何「真实报单」路径上**硬拦**（`personal_derivatives_live_forbidden=True`），**只允许仿真**；提示语**不得替代**拦截。

**（8）测试（本步硬断言，全部在仿真环境跑，不得触碰真实资金）。**
- `test_idempotency.py`：报单超时但券商已受理 → 不产生第二笔；同 `client_order_id` 重复提交被拒；**重启后幂等键仍在**。
- `test_reconcile.py`：本地少记一笔成交 → **下一次报单前被拦**；不一致后自动停止开新仓，人工确认后恢复。
- `test_live_gate.py`：预热期 / 停更 / 非交易时段的信号在 `LiveTrader(仿真)` 下**不产生报单**；三引擎对同一帧裁决一致。
- `test_kill_switch_persist.py`：触发后重启进程，**仍处于停机态、仍拒绝新单**。
- `test_live_checklist.py`：15 项自检须报**四类计数**（已跑 / 未跑 / 跳过 / 失败），**未跑不得打勾**。

**（9）`config.py` 增量**：新增 `LIVE_SAFETY`（9 键）与 `ORDER_PORT_CONFORMANCE`（11 键），`SIGNAL_EGRESS_CONFORMANCE['signal_egress_points']` 增 `live_order_submit`。


### 本步要交付的文件

```
broker/base_broker.py         # ① 统一券商适配器抽象基类
broker/qmt_broker.py          # ② QMT 本地实盘对接
broker/ptrade_broker.py       # ③ PTrade 云端实盘对接
broker/ctp_broker.py          # ④ CTP 国内期货实盘对接（含 SimNow 仿真）
data/live_data.py             # ⑤ 实盘双源行情引擎
risk/risk_manager.py          # ⑥ 完整实盘风控模块
live/live_trader.py           # ⑦ 实盘执行器（驱动第5步策略）
live/daemon.py                # ⑧ 实盘运行守护
live/notifier.py              # ⑨ 多渠道告警通知
live/reconciliation.py        # ⑩ 每日自动对账
live/audit_log.py             # ⑪ 实盘交易日志（合规留存）
run_live.py                   # ⑫ 实盘启动入口
tools/live_checklist.py       # ⑬ 实盘前 15 项检查
```

### 12.1 统一券商适配器抽象基类 `broker/base_broker.py`
统一接口：`connect()` / `get_account()` / `get_positions()` / `place_order()` / `cancel_order()` / `get_quote()` / `get_orders()` / `get_today_trades()`。上层策略与实盘执行器只依赖这个接口，换券商只换适配器实例。
- 内置实盘总开关 `LIVE_TRADING_ENABLED = False`，默认关闭，开启需在 config 中显式设置并二次确认。
- 所有订单操作强制留痕日志，满足监管留存要求。

### 12.2 QMT 本地实盘对接 `broker/qmt_broker.py`
对接迅投 QMT 的 `xtquant` 官方 Python API，覆盖 A股个股/ETF/可转债/REITs/场内基金。
- 自动处理：最小下单单位、价格笼子（科创板/创业板 ±2% 挂单限制）、涨跌停校验、T+1 可用数量计算。
- 三种连接模式：`mini`（普通投资者极简模式，不需登录QMT终端）/ `standard`（标准客户端全功能）/ `simulation`（QMT自带模拟盘，零风险测试）。
- 自动断线重连、心跳检测、订单状态实时回调。

### 12.3 PTrade 云端实盘对接 `broker/ptrade_broker.py`
对接恒生 PTrade 云端 API，适合不想本地挂机、要 7×24 稳定运行的用户。
- 支持云端定时任务、云端自动盯盘、云端下单（关机也能运行），同样内置模拟盘模式。

### 12.4 CTP 国内期货实盘对接 `broker/ctp_broker.py`
对接 **OpenCTP**（开源兼容 CTP 接口）+ 官方 CTP API，覆盖四大期货交易所 + 广期所全部品种。
- 完整处理：平今/平昨手续费自动区分、保证金实时计算（交易所 + 期货公司加成）、可用资金/保证金占用/风险度实时监控、今昨仓分别记录、涨跌停板判断、夜盘时段自动切换。
- 内置 **SimNow 仿真环境**预设地址（24 小时服务），不用自己找。
- 自带**穿透测试辅助工具**，帮你完成期货公司要求的穿透式监管认证。

### 12.5 实盘双源行情引擎 `data/live_data.py`
- **回测模式**走 AKShare 本地缓存；**仿真模式**走券商/CTP 仿真行情；**实盘模式**走券商/CTP 官方实时行情；三模式一键切换，上层策略无感。
- 支持行情订阅（tick 与分钟 K 线回调）、断线检测与重连、补数据；期货夜盘时段自动识别开启订阅。
- **再次强调：AKShare 不可用于实盘行情**（延迟、限频、接口随时改版），实盘必须用官方行情。

### 12.6 完整实盘风控模块 `risk/risk_manager.py`（实盘最核心）
所有订单**先过风控再报单**，风控不通过绝不发出，哪怕策略写错。
- **账户级**：单笔最大下单金额/手数（默认 ≤ 总资金 10%）、单日最大开仓次数（默认 ≤ 20）、单日最大撤单次数（默认 ≤ 30，防被判频繁报撤单）、单日最大亏损熔断（默认浮亏 ≥ 5% 停机告警）、最大回撤熔断（默认 ≥ 10% 清仓停机）、总杠杆上限（股票 1 倍、期货 ≤ 3 倍）、单标的集中度（默认 ≤ 20%）。
- **订单级**：价格偏离检查（偏离最新价 > 2% 拒单，防乌龙指）、流动性检查（日均成交额 < 1000 万禁开仓）、涨跌停禁反向开仓、T+1 禁卖当日买入、期货保证金不足禁开新仓。
- **合规级**：禁自成交、频繁报撤单预警、异常订单拦截。
- 所有触发即时推送告警，严重情况直接平仓停机。

### 12.7 实盘执行器 `live/live_trader.py`
用与第 6 步回测引擎、第 7 步模拟盘**相同的方式**实例化并驱动你的策略（`init → on_bar/on_tick → on_end_of_day`），差异只在于：信号产生后先过风控，再经 `BrokerAdapter` 报单，成交回报回写账户。**策略代码零改动。**

### 12.8 实盘运行守护 `live/daemon.py`
进程守护（崩溃自动重启）、开盘前自检（行情连接/账户登录/风控参数/持仓核对）、收盘后自动结算与对账、交易日历自动判断（节假日/调休/周末不开盘）、心跳监控（超 10 分钟无心跳告警）、支持 Windows 本地 / Linux 服务器 / 后台运行、优雅退出（自动撤未成交单，不挂单过夜）。

### 12.9 多渠道告警通知 `live/notifier.py`
4 种渠道可独立开关：企业微信机器人（推荐）、钉钉机器人、微信 Server 酱、邮件。
推送事件：开平仓成交回报、订单状态变化、风控触发、每日开盘/收盘报告、行情断线/重连/程序崩溃、盯盘信号。**严重告警重复推送 3 次**确保看到。

### 12.10 每日自动对账 `live/reconciliation.py`
收盘后第一件事自动运行，核对三件事：① 系统持仓 vs 券商真实持仓；② 系统资金 vs 券商真实资金（差 ≥ 1 分即告警）；③ 当日成交明细 vs 系统订单记录（漏单/多单告警）。**对账不通过不允许次日自动开盘**，必须人工确认。自动生成对账报告归档。

### 12.11 实盘交易日志 `live/audit_log.py`（合规要求）
订单、撤单、成交、风控触发、程序启停、登录登出全部永久留存，字段符合证监会程序化交易报备要求（时间/价格/数量/方向/账户/IP/策略ID），按日期归档、不可篡改、**至少保留 2 年**，可导出供券商/交易所检查。

### 12.12 实盘启动入口 `run_live.py`
启动强制打印风险提示 → 跑全套自检（账户/行情/风控/对账）→ 显式确认"仿真"还是"真实实盘"（真实需二次输入 YES 确认）→ 支持指定策略/市场/时段 → 支持"只盯盘不下单"信号推送模式。

### 12.13 实盘前 15 项检查 + 报备指引 `tools/live_checklist.py`
- QMT/PTrade 开户 + 白名单申请流程
- 期货 CTP 开户 + 穿透测试 + 程序化报备流程
- SimNow 仿真环境注册与参数配置
- 实盘前仿真必须跑满的时长与验证项
- 小资金实盘试跑注意事项
- 交易所对程序化交易的监管红线（哪些行为会被限制交易）
- 常见实盘坑：滑点、废单、网络断开、节假日、分红除权、合约换月

### 12.14 实盘安全机制（防误操作亏大钱）
1. **默认永远仿真**：`LIVE_TRADING_ENABLED = False`，代码开关 + config 开关双层防护。
2. **真实下单二次确认**：启动实盘须手动输入 `YES_CONFIRM_LIVE_TRADING`。
3. **初始资金限制**：默认单笔 ≤ 10% 仓位，单日亏 ≥ 5% 熔断停机。
4. **风控先于一切**：订单先过风控，不通过绝不发出。
5. **强制模拟盘**：仿真连续跑满约定时长、指标稳定，才可开实盘。
6. **废单不自动重试**（默认关闭），避免触发频繁报撤单监控。

### 12.15 紧急停止机制（Kill Switch）——实盘必备
实盘必须有**独立于策略进程**的"一键停机"能力，防止策略卡死、行情异常、你临时要退出时来不及处理。

1. **触发方式**（三选一或并存）：
   - 命令行：`python run_live.py --panic`（独立进程，向运行中的实盘进程发停机信号）
   - 键盘中断：运行中 `Ctrl+C` → 不直接强杀，走**优雅停机**流程
   - 监控文件/信号：约定一个 `live/.panic` 标记文件或系统信号，一旦出现立即触发（适合服务器无人值守时用 SSH 创建）
2. **停机动作（按顺序执行，全部记审计日志）**：
   - ① 立即冻结策略：不再产生任何新订单
   - ② **撤销所有未成交委托**（撤单失败要重试并告警）
   - ③ 按配置决定是否**一键清仓**（`PANIC_LIQUIDATE = True/False`，默认只撤单不清仓，清仓需显式开启）
   - ④ 断开行情订阅与交易连接
   - ⑤ 写入 `live/audit_log.py` 审计日志
   - ⑥ 通过 `live/notifier.py` 推送"已紧急停机"告警
3. **独立性要求**：紧急停止逻辑运行在**独立线程**并监听外部信号，**即使主策略线程卡死/死循环也能响应**。
4. **与风控熔断的区别**：风控熔断是**系统自动触发**（超限/超亏自动停），Kill Switch 是**人工或外部信号触发**，两者互不替代，都要有。
5. **开机自检**：`run_live.py` 启动前自检中，必须验证 Kill Switch 可用（能收到信号、能撤单），不可用则拒绝启动实盘。
6. **写测试 `test_kill_switch.py`**：在仿真环境模拟"持仓+挂单"状态下触发 Kill Switch，验证未成交单全部撤销、策略停止下单、审计日志与告警均正常（全程仿真）。

### 12.16 统一测试入口（pytest）
避免"一堆 `test_*.py` 只能一个个手动跑"的麻烦，统一用 pytest 管理。

1. **在项目根目录创建 `conftest.py`**：配置公共 fixture（如临时数据目录、中文字体、仿真环境开关），并统一设置 pytest 运行参数。
2. **创建 `pytest.ini`（或 `pyproject.toml` 的 `[tool.pytest]` 段）**：设置 `testpaths = tests`、日志输出、超时时间；用 `markers` 标记 `slow`（耗时长）、`network`（需联网/需接口）两类测试。
3. **一键运行**：`pytest -q`（全部）、`pytest -q -m "not network"`（跳过需联网的，适合离线复现）、`pytest -q -m "not slow"`（快速回归）。
4. **`requirements.txt` 需包含 `pytest` 与 `pytest-timeout`**（见前置文件）。
5. **CI 友好**：所有测试默认**不依赖真实下单、不碰真实资金**，仿真测试通过环境变量开关（无网络/无券商环境时自动跳过并标记 skipped，而不是失败）。

---

### 12.17 凭证安全管理（账号/密码/Token 如何给系统）

**为什么要做这一节：** 很多量化新手第一步就把 QMT 资金账号、Tushare Token、券商密码直接硬编码在 `config.py` 里，要么误上传 GitHub 被爬虫爬走（真的有人被盗下单）、要么多机器切换时每次改代码容易出错。这一节建立**凭证与代码完全分离**的机制——代码里**永远不出现真实密码**，所有凭证走 `.env` 文件、启动时加载、用完立即从内存擦除，且 `.env` 被 `.gitignore` 强屏蔽，就算 `git add .` 也不会提交出去。

### 12.17.1 前置文件（一次性写入项目根目录）

创建两个文件：`.gitignore` 和 `.env.example`（已随本次更新提供）。

`.gitignore` 必须包含（关键行）：
```
.env
.env.*
!.env.example
secrets/
credentials/
*.key
*.pem
```

`.env.example` 是**无真实值的模板**（所有值留空），提交到仓库供使用者参考；用户真正使用时 `cp .env.example .env` 再填入真实凭证。

### 12.17.2 config.py 的凭证加载段（安全要点）

凭证加载函数必须做到：
```python
def _get(name: str, default: str = "") -> str:
    val = os.environ.get(name, default)
    if name in os.environ:
        del os.environ[name]    # 用完立即从环境变量抹除，减少泄漏窗口
    return val
```
- **从 `.env` 读**：用 `python-dotenv` 的 `load_dotenv()` 加载项目根目录的 `.env`
- **不存长引用**：模块加载完后，真实密码只在配置常量里存一次；全局 `os.environ` 里立刻抹掉，防止第三方库通过 `os.environ` 读到 Token
- **缺凭证不允许静默跑**：`SECURITY.fail_open_when_env_missing = False`——实盘模式下如果某关键字段（如 QMT_ACCOUNT_ID、CTP_PASSWORD）为空，直接报错退出，而不是用空字符串去连接然后失败

需要在 `requirements.txt` 加入：`python-dotenv>=1.0.0`。

### 12.17.3 Broker 适配器登录凭证的传递规范

所有 broker 适配器（QMT/PTrade/CTP/IBKR）在 `connect()` 时统一从 `config.py` 读常量（这些常量本身从 `.env` 来），**禁止在代码里写死任何账号密码/地址**：

```python
from config import QMT_PATH, QMT_ACCOUNT_ID, QMT_PASSWORD, QMT_SESSION_ID, QMT_MODE
def connect(self):
    if not QMT_ACCOUNT_ID or not QMT_PASSWORD:
        raise RuntimeError("QMT 账号/密码未配置，请在 .env 文件中填写 QMT_ACCOUNT_ID / QMT_PASSWORD")
    ...
```

要点：
- **仿真/实盘地址可切换**：CTP 默认填 SimNow 地址，实盘时在 `.env` 里把 `CTP_FRONT_ADDR_TRADE/MARKET` 改成期货公司给的正式前置地址
- **穿透式监管参数**（`CTP_APP_ID / CTP_AUTH_CODE / CTP_PROD_CODE`）：仿真用默认值即可，实盘时换成期货公司在穿透测试后分配的正式值
- **QMT 路径**：`QMT_PATH` 在 `.env` 里填 QMT 客户端安装路径（如 `D:/qmt_mini`），不同机器路径不同，不写死在代码里
- **PTrade 的地址/账号/密码**：完全由券商分配，不硬编码

### 12.17.4 日志脱敏（最容易被忽略的泄漏点）

在 `core/logger.py` 里统一做日志脱敏中间件：
- 任何包含 `token`/`password`/`secret`/`authorization` 字段的日志打印，**只保留前3位 + `***`**，例如 `TUSHARE_TOKEN = "a1b***"`
- 下单回报、撤单回报、成交回报里不打印资金账号全称，只保留后4位（例如 `资金账号 ******1234`）
- 异常栈 traceback 如果带敏感字段，也走同样脱敏
- 审计日志（`audit_log.py`）为满足监管留存要求**必须保留完整账户标识**，但该文件存 `audit_logs/`，已被 `.gitignore` 屏蔽，不提交

### 12.17.5 启动前凭证校验（避免实盘启动失败）

在 `live/daemon.py` 开盘前自检阶段增加凭证检查：
- `check_credentials()` 函数：根据当前 broker 类型，检查对应必填字段是否齐全
  - QMT：`QMT_PATH / QMT_ACCOUNT_ID / QMT_PASSWORD`
  - PTrade：`PTRADE_SERVER / PTRADE_USERNAME / PTRADE_PASSWORD / PTRADE_ACCOUNT_ID`
  - CTP：`CTP_FRONT_ADDR_TRADE / CTP_FRONT_ADDR_MARKET / CTP_BROKER_ID / CTP_USER_ID / CTP_PASSWORD`
  - IBKR：`IBKR_HOST / IBKR_PORT`
- 缺失关键字段时：**立即告警 + 拒绝启动**，并提示"请检查 .env 文件中 XXX 字段"
- 模拟盘/回测模式不校验券商凭证，但数据平台 token 缺失时给出黄色警告（AKShare 免费可不用 Tushare，但若代码里选了 Tushare 源就必须有 token）

### 12.17.6 凭证轮转建议（写进 README 的安全提醒）

- **实盘账号密码定期更换**：建议每季度更换一次券商交易密码
- **Token 泄漏立即吊销**：Tushare/聚宽/企业微信 webhook 一旦怀疑泄漏，立刻在对应平台重新生成
- **不同环境用不同凭证**：本地开发用仿真账号；服务器部署用实盘账号；不要混着用
- **服务器部署**：Linux 服务器上 `.env` 文件权限 `chmod 600 .env`，只允许当前用户读写
- **不要截图分享**：哪怕是 debug 截图，也务必把终端里出现的账号/Token/password 打码
- **`YES_CONFIRM_LIVE_TRADING` 确认串不可关闭**：实盘启动必须手动输入，不能写成自动确认

### 12.17.7 测试用例

创建 `tests/test_credentials.py`：
1. 测试 `.env` 能被正确加载，敏感字段读取后 `os.environ` 中不再存在
2. 测试日志脱敏函数：输入带 password 的字典，输出应为脱敏后的字符串
3. 测试 broker 缺失凭证时 `connect()` 抛明确异常
4. 测试 `.gitignore` 文件存在且包含 `.env` 行（防止被误删）

---

## ===== 第 13 步：数据与报告的长期可用性（让系统三年后还能跑）=====

**为什么要做这一步：** 前12步已经能跑回测/模拟/实盘，但如果不处理，系统在使用半年到一年后会出现"静默数据错误"——前复权缓存和新数据拼接断裂、数据被修订后研究结果不可复现、用当前成分股回测产生幸存者偏差、报告堆满磁盘无法检索。这些问题**不报错**，但会悄悄让回测结果失真，是做长期研究最危险的坑。这一步把数据层升级为"多源备份 + 原始价 + 复权因子分离 + 数据版本快照 + 时点成分股"，把报告层升级为"归档 + 结构化存储 + 离线可看 + 可检索"。

### 13.0 开工前置（v3.32 新增）：这是最后一步，没有「下一步」可装闸门

**本步的特殊性**：这是整套指令集的**最后一步**。前 11 轮我们用的办法是「把闸门写进**下一步**的开工前置」；第 13 步之后**没有第 14 步**了，而本步引入的每一样东西（schema 版本、完整性基准、快照、PIT 成分股、报告索引），**消费者都在更早的步骤里、代码都已经写完**。所以本节不是「开工前读一读」，而是一份**回补清单**——下面点到的每个已交付模块，都必须重新打开来改。

**一句话**：第 13 步不是「加一个新功能」，而是**给前 12 步的全部产物补一道「长期不腐坏」的底层约束**。凡是**长期不被读取、一旦被删就出大事**的东西（复权因子 / 完整性基准 / 快照 / PIT 成分股 / 幂等键 / 急停状态 / 审计链），都要从「顺手可以清掉的普通缓存」升格为**受保护的系统状态**。

**硬要求（23 条，缺一不可）**：

**13.0.1 清理器必须认识它不该删什么**（`config.CACHE_GOVERNANCE`）
- 13.9 的 LRU / 保留期清理，**默认 `dry_run`**，只有显式 `--apply` 才真删。
- 删除前**必须先查引用**：报告引用的快照不可删；快照引用的原始数据不可删。
- 命中 `protected_paths` / `protected_globs` 即 **`skip_and_warn`**，绝不静默删除；每次真删**必须留审计条目**。
- 特别点名，任何策略下都不可删：`live_trading/order_ids.json`（幂等键）、`live_trading/kill_switch.json`（急停态）、`data_cache/data_manifest.json`（完整性基准）、`audit_logs/**`（哈希链）。
- **验收判据**：跑一次 `--apply` 清理后，上述文件仍在；且模拟「一个月后重启」，`order_ids.json` 里的历史键**仍能命中去重**。

**13.0.2 缓存必须自带口径标记，读取器禁止猜**（`config.DATA_VERSIONING`）
- 每个 parquet 写入时带 `price_basis`（`raw` / `qfq` / `hfq` / `nav`）与 `schema_version`；**读不到标记 → 报错**，不得按默认口径读。
- **`forbid_read` 旧 qfq 缓存**：「启动时打印警告、提示用户删除」**不足以拦截**——未迁移完之前，旧文件必须**读不了**。
- 迁移必须**原子**（先写新目录 → 全量校验 → 再切指针，**禁止就地改名 / 覆盖**）、**可续跑**、**可回滚**（旧缓存留 `.bak`）、**迁移期加维护锁**（拉数 / 回测 / 实盘全停）。
- **验收判据**：人为做出「一半 raw、一半 qfq」的缓存目录，读取必须**报错**，而不是安静地算出价格。

**13.0.3 正确性闸门必须装在「读取 / 回测入口」**（`config.SNAPSHOT_PIT_GUARD`）
- 13.3 完整性校验：日常**读取路径**必须校验（哈希 + 行数），不能只在 `tools/verify_cache.py` 里查；不匹配 → 重下 → 仍不匹配 → **报错**。
- 13.4 快照：由**引擎在回测 / 研究入口强制生成**（像第 6 步往 `bar_dict` 注入 `warmup_ok` 那样），不靠调用方记得调；没有快照 → **不允许产出「可复现」结论**；**禁止「不传就跳过」的旁路**。
- 13.5 PIT：`FactorStrategy` 取股票池**必须**走 `get_index_members(index_code, date)`；回测**禁止**读「当前成分股」；拉不到 → **`raise`**。
- 13.5 原文「打印红色警告但不中断」只保留给**教学 / 演示**模式，且报告必须带上 `survivorship_bias_uncontrolled` 水印，该水印**粘性**（随报告进归档库与统计，不得被后续流程抹掉）。
- **验收判据**：关掉 PIT 后跑同一份策略，回测必须**报错**，而不是安静地跑出高收益。

**13.0.4 保留期必须满足依赖关系，四份产物同生共死**（`config.REPORT_ARCHIVE_CONFORMANCE`）
- **`snapshot_retention_days >= max(retention_days_*)`**：快照必须活得比引用它的最长报告久，**启动时断言**（`raise_at_boot`）。
- 一份报告 = `html` + `json` + `trades.parquet` + `equity.parquet` + 索引记录，**删除必须整组删**；索引 ↔ 文件**双向一致**，悬空引用必须能被检出。
- 每条索引记录带 `meta_complete` 真 / 假；历史缺字段报告**打标不隐藏**；`report show` 必须展示「缺哪些字段」。
- `stats equity` **默认只吃 `meta_complete=true`**，`--include-incomplete` 才纳入，且输出必须声明「含 N 份不可复现报告」。
- 若 `stats` 产出的累计净值曲线**对外展示**，它落 `investor_disclosure` 出口：过披露口径（**固定 `investor_net`**）+ 滞后断言 + 合格投资者上下文。

**13.0.5 口径的「唯一权威 + 冲突裁决」：标记自己不得变成第三份会漂移的副本**（`config.DATA_VERSIONING`）
- 口径现在有**三个载体**：parquet 文件内元数据、边车 `.basis.json`、文件名后缀——**三者各自会失灵**。必须定权威：`price_basis` 以 **parquet 元数据为唯一权威**（随数据走、与数据同一次原子写入），文件名里的口径**仅作提示**（`filename_basis_is_hint_only`）。
- **边车只是过渡桥**（`sidecar.role="bridge_only"`），只服务 CSV-only / 无元数据环境；**永不覆盖 parquet 元数据**（`may_override_parquet=False`），两者不一致 → **报错**（`on_conflict_with_parquet="raise"`），不得由边车「兜底」出一个口径。
- 同一标的多口径并存（`raw` 与 `hfq` 同名落地）→ **报错**（`on_multi_basis_same_symbol="raise"`），不得替调用方挑一个。
- 标记与数据**同一次原子写入**（`atomic_write_with_marker`）：先 `.tmp` → 校验 → `rename`，**不留「已写数据、未写标记」窗口**（否则读取器会在窗口内看到无标记文件 → 误报或误判）。
- **给存量文件补标记的红线**：**不得**把「无标记」一律归 `raw`——存量里可能混有 qfq 内容，标成 raw 就是**复权两次、静默错价**。`stamp_legacy.method="filename_and_source_semantics"`，判不出即 `quarantine` 隔离，**绝不默认标 raw**。
- **验收判据**：删掉某个标的的边车文件 → parquet 仍能凭**自身元数据**读出正确口径；把 parquet 元数据改成 `hfq` 而文件名仍是 `_qfq` → 读取**报错**，不得静默采用文件名。

**13.0.6 PIT 闸门收口在访问器，成分股本身必须快照化**（`config.SNAPSHOT_PIT_GUARD.pit`）
- `assert_pit_enabled` 若只装在某一个引擎入口，**下一条新引擎**（或直读 `constituents/`）就能绕过——这已是本会话**第 8 次「单引擎守卫」**。确立 `guard_at="accessor"`：闸门必须收口在 `data/pit_index.py::get_index_members`（引擎无关），并 `forbid_direct_constituents_read`（除 `pit_index.py` 外任何模块不得直读 `data_cache/constituents/**`）。
- `engines_must_resolve_universe_via_pit` 列出**所有**需要解析股票池的引擎（`backtester` / `runner` / `paper_trader` / `live_trader` / `monitor`）；13.13 收尾总检逐引擎 grep 确认，**少一个即未完成**。
- **成分股清单必须进快照**（`constituents_must_be_snapshotted=True`）：`constituents/{index}.parquet` 是会被**重建**的缓存，一旦用修订后的成分股重建，**过去跑过的回测结论会静默改变**；快照必须连成分股一起固化。
- 同一 `as_of` 日期的成分股**一经落地不得被覆写**（`constituents_immutable_per_as_of=True`）；重建走新版本文件，旧版本保留。
- **验收判据**：关 PIT 后跑同一策略 → 回测**报错**；把 `constituents/` 里某个 `as_of` 的成分股改掉 → 已产出快照的**复现结果不变**（证明快照真的固化了成分股）。

**13.0.7 标的池只有一个出口：「当前成分股」在回测 / 研究上下文里不可表达**（`config.UNIVERSE_RESOLUTION_GUARD`）
- **实测发现**：PIT 闸门收口到 `pit_index` 后，核查五引擎时**发现了第六个入口**——`factor/universe.py` 仍用 `index_stock_cons*` 拉**当前**成分股，失败还回退**内置静态清单且从不抛错**。它不在五个执行器里，但研究 / 因子链路一旦拿它当标的池，**PIT 闸门等于没装**。
- **比「漏一个入口」更深的坑**：它污染的是**因子值本身**。回测的 `universe` 走 PIT 看起来很干净，但**因子是用未来成分股算出来的** → 幸存者偏差从第二道门进来。**闸门必须同时守「选股 universe」和「因子计算标的池」。**
- **规律**：守卫装在**某个调用点**（`backtester.prepare`）而非**数据获取的唯一出口**，就必然随「入口扩散」而漏装——这是「单引擎守卫」的病在**数据层**的复制。
- **硬要求**：① 标的池 / 成分股获取**只有 `data/pit_index.py::get_index_members(index_code, date)` 一个出口**，`date` 必填；无日期调用 → **报错**（「当前成分股」语义在回测 / 研究 / 因子构建上下文里**不可表达**）。② `index_stock_cons*` 类 API **仅允许**出现在 `data/source_adapter.py` 的原始拉取层，且必须被 `pit_index` 包装；`core/ factor/ research/ nav_backtest/ cli_commands/ tools/` 中**零出现**。③ **静态清单回退 = fail-open，全面禁止**（改 `raise`）；确需「当前成分股」只允许 `as_of=now AND context=realtime`（实时盯盘），且**不得进入**回测 / 研究产物。
- **旧便捷函数降级**：`factor/universe.py::get_hs300/get_zz500/get_zz1000/get_zz2000` 必须改为薄封装，**新增必填 `date` 参数**，无 `date` → `raise`；只有实时上下文可省。
- **收口方式**：`enforce_at="call_time"`——闸门在**访问器本体运行期**生效，**不靠一次性 grep**（grep 是提醒，新代码再引入就白费，正是本会话「提醒 ≠ 拦截」的又一次）。
- **验收判据**：① 全仓枚举**所有**获取标的池的路径（不止五引擎，含 `factor/` `research/` `nav_backtest/` `cli_commands/` `tools/`），逐个确认走同一访问器；② `factor/universe.py::get_hs300()` **不带日期调用 → 报错**；③ 把 PIT 关闭后，**因子构建路径**也必须报错（不能只有回测报错）。

**13.0.8 闸门按「输入形态」分层，禁止「无条件拦截」（v3.38 新增）**

- **病**：v3.37 修完 `factor/universe.py` 绕过之后，闸门一度被写成 `factor_engine.compute` 入口**无条件** `assert_pit_enabled("factor")`，**连显式传 `["600519","000001"]` 也拦**。
- **为什么错**：显式代码列表**没有 index、没有成分股、没有幸存者偏差**，拦它属**过度拦截**，且带来三重恶果——① 用户传明确标的做研究**被误伤**；② 既有直接调 `compute` 的**单测被迫处处**设 `enforce_in_factor=True`（脆弱耦合）；③ 一旦有人**为跑通而关掉该键**，PIT 的真实性**一起被关掉**——**闸门变成了它要防的东西**。
- **正确边界**：变量是「**是否解析了指数成分股**」，**不是**「是否经过 `compute`」。判据落在 `resolve_universe` **函数内部**（看输入是代码列表还是指数名），**不放在** `compute` 入口。
- **落地**（`SNAPSHOT_PIT_GUARD.pit.enforce_scope`）：`by_universe_kind=True`、`explicit_code_list_requires_pit=False`、`index_token_requires_pit=True`、`allow_implicit_all_a=False`。
- **验收判据**：① `compute(["600519"], start)` **放行**（`blocked_by_pit=False`）；② `compute("hs300", start)` **走 PIT**（`blocked_by_pit=True`）。
- **一句话**：**闸门要拦的是「会引入偏差的输入形态」，不是「经过某个函数」。**

**13.0.9 标的池判据必须「默认拒绝」，禁止「白名单命中指数、否则当代码」（v3.39 新增）**

- **病**：`resolve_universe` 的实现是「**字符串 ∈ `_INDEX_CODES` 白名单 → 走 PIT；否则 → 当代码放行**」。这是 **fail-open**。
- **风险一（漏项即静默绕过）**：**未命中的字符串一律静默当代码**——别名「沪深300」、大写「HS300」、带前缀「000300.SH」、拼写错误——**既不报错、也不过 PIT**。闸门的触发条件依赖一个**「能识别的名字清单」**，**清单漏项即静默绕过**（与「信号出口清单」「标的池入口清单」**枚举不完**同族）。
- **风险二（同名字符串既是指数又是个股）**：`000001` **同时**是上证指数（`000001.SH`）与平安银行（`000001.SZ`）——裸数字代码**天然有歧义**，白名单命中与否决定它是「指数」还是「个股」，而这是**猜**（与「`_daily_` vs `_daily_none`」「raw vs qfq 同名同格式」同族）。
- **正确方向**：把判据从「**白名单命中指数 → PIT**」翻转为「**默认拒绝，能被判定为「代码」才放行；其余一律走 PIT 或 raise**」。
- **落地**（`UNIVERSE_RESOLUTION_GUARD`）：`resolution_default="deny"`、`unrecognized_token_is_not_code=True`、`on_unrecognized_token="raise_with_guidance"`、`code_shape_rule`（**要求带交易所前缀** `600519.SH`/`sz000001`；裸 6 位数字**必须与指数注册表比对，命中即非代码**；冲突则**要求带前缀、拒绝猜**）、`index_registry_source`（`CN_INDEX`/`CN_INDEX_BARE_CODES`/`INDEX_PREFIX_RULES` **单一来源**）、`known_ambiguous_symbols`（实测同名清单）。`SNAPSHOT_PIT_GUARD.pit.enforce_scope.unknown_token="pit_or_raise"`。
- **验收判据**：① 传 `"hs300"` → 走 PIT；② 传 `"沪深300"`/`"HS300"`/`"000300.SH"` → **不被静默当代码**（走 PIT 或明确报错）；③ 传 `"000001"`（歧义）→ **要求带前缀，不替用户猜**；④ 传 `"600519.SH"` → 放行。
- **一句话**：**判据要「默认拒绝」；enumeration 只能用来放行「能确认的」，绝不能用来自动放行「没见过的」。**

**13.0.10 带后缀的输入按「段位」判定，不做「矛盾即拒」（v3.40 新增）**

- **病**：把 `000001.SH` / `000300.SH` 判成「后缀与代码段矛盾」并**拒绝**。
- **事实**：上交所 `000xxx` **本来就是指数段**（上证指数 `000001.SH`、沪深300 `000300.SH`）；深交所 `399xxx` 才是指数段（深证成指 `399001.SZ`）——带后缀的输入**根本没有歧义**，谈不上「矛盾」。
- **三个后果**：① 丢掉交易所标准写法；② 与 `sh000300`（同一实体的另一种写法，却放行）判定**相反**；③ 与 `config.CN_INDEX` / `CN_INDEX_BARE_CODES` 口径**分裂**，同一份规格里两套指数识别标准。
- **正确判据**：**后缀 + 代码段联合判定**——`.SH` + `000xxx` → 指数；`.SZ` + `000xxx` → 个股；`.SH` + `6xxxxx` → 个股；`.SZ` + `399xxx` → 指数；只有**真冲突**（如 `399001.SH`）才报错。
- **落地**：`UNIVERSE_RESOLUTION_GUARD.code_shape_rule.exchange_segment_rule` + `suffixed_input_uses_segment_decision=True` + `on_segment_conflict="raise_with_guidance"`。
- **验收**：`000001.SH` → **走 PIT**（上证指数）；`000001.SZ` → 个股（平安银行）；`000300.SH` → **走 PIT**（沪深300）；`399001.SH` → 报错。

**13.0.11 版本号不得复用；机器验内容哈希（v3.40 新增）**

- **病**：把内容变更「并进上一版号」（本轮把反向白名单并进 `v3.38`，理由是"该版尚未投递"）。
- **后果**：跨副本比对只看**字符串**——两个 `v3.38` 内容不同却**判定相同 = 假绿**；`SPEC_VERSION` 机制在它诞生后的第一个真实场景里就失效。版本号是**人手维护的标签**，会漂移、会复用。
- **正确**：① **改内容必须换号**（即使上一版尚未投递）；② 另存 `spec_content.sha256`（指令集**正文**哈希），机器验哈希、人看版本号。
- **落地**：`SPEC_VERSION_CHECK` 增 `content_hash_required=True` / `content_hash_file="spec_content.sha256"` / `hash_scope="instruction_doc_body"` / `on_content_hash_mismatch="raise"` / `version_number_never_reused=True`。
- **口径定死（v3.42）**：`hash_scope="instruction_doc_body"` = 对指令集文件**全部字节**（UTF-8、LF 行尾、**含 version 头行**）求 `sha256`；**禁止按行过滤**（过滤特定行会引入 CRLF / 末尾换行 / BOM 的跨机器差异，导致同一份规格在不同机器算出不同哈希——重演「看字符串不看内容」的老病）。
- **验收**：**保持版本号不变**、只改动指令集正文 → `check-config` **必须不通过**（证明验的是内容，不是字符串）。

**13.0.12 北交所段位识别 + 别名单源落地 + 别名必须被主链路消费 + accessor 入口先过 checker（v3.41 引入 · v3.42 补病四）**

- **病一（北交所全链路被当期货静默错判）**：`detect_market_type()` 旧版先判「字母+数字混合 = `cn_future`」、后判 `sh/sz` 前缀；`.BJ`（Tushare/Wind/聚宽/AkShare 标准写法 `899050.BJ`、`830799.BJ`）与小写前缀 `bj899050` 都含字母 → **先命中期货分支**，返回新浪期货主力连续数据。北交所涨跌幅 **30%**、**100 股起**、**T+1** 与沪深/期货皆不同，错判会让信号闸门、撮合、风控全跑在错误规则上，且**静默不报错**。
- **病二（别名单源没立起来）**：v3.40 的 `index_alias_single_source` 注释写「`CN_INDEX` + 新增 `CN_INDEX_ALIASES`」，但 `config.py` **根本没有该常量**；`index_aliases()` 要么 `KeyError`、要么模块内另起一份 → 第五份清单回归。
- **病三（accessor 入口未过 checker）**：只说「共用同一份 checker」，未锁定调用位置；若 `classify_symbol` 只在「缓存未命中 → 远端 API」分支里调，**缓存命中 / 降级路径直调 `get_index_members("600519.SH")` 仍绕过检查**（fail-open 的典型位置：缓存路径免校验）。
- **病四（别名没进粗判函数 · 实测新增）**：即便定义了 `CN_INDEX_ALIASES`，`detect_market_type()` **不消费它**——汉字与字母都满足 `str.isalpha()`，「沪深300」「hs300」「北证50」会落进「字母+数字 = `cn_future`」贪心分支，被当期货取数。**别名单源立起来了，但主链路不用它 = 等于没立。**
- **落地**：① `INDEX_PREFIX_RULES` 增 `"BJ": ("899",)`；`MARKET_CODE_RULES.cn_index` 补 `prefixed_bj` / `dotted_bj`，新增 `accepted_dot_suffixes=["SH","SZ","BJ"]`、`bj_stock` 段位；② 新增顶层常量 **`CN_INDEX_ALIASES`**（中文 / 大小写 / 英文 / 带前缀别名唯一来源，key 统一小写无空格），`index_alias_single_source="config.CN_INDEX_ALIASES"`；③ `detect_market_type()` **把「点后缀写法」判定提到所有分支之前**，8 位小写前缀判定扩到 `SH/SZ/BJ`，并在**最前面**插入「`code.lower().replace(" ","") in CN_INDEX_ALIASES` → `cn_index`」的别名归一化分支；④ `UNIVERSE_RESOLUTION_GUARD.code_shape_rule.exchange_segment_rule` 的 SH/SZ/BJ 段位补全为完整三段前缀；⑤ 新增 `get_index_members_must_call_classify_first=True` + `classify_symbol_is_single_source=True`。
- **验收判据**：① `detect_market_type("899050.BJ")=="cn_index"`、`detect_market_type("bj899050")=="cn_index"`；~~`detect_market_type("830799.BJ")=="cn_stock"`~~ **（v3.43 已废止——见 13.0.13：43/83/87 段 2025-10-09 起退出北交所，带 `.BJ` 的旧段是陈旧码）**；② `detect_market_type("沪深300")==detect_market_type("hs300")==detect_market_type("hs 300")=="cn_index"`（**不得为 `cn_future`**）；③ `get_index_members("600519.SH", date=...)` **入口即 `raise`**（不是等到 API 分支才抛）；④ `resolve_universe("北证50", date=...)` 走 PIT、不静默当代码。
- **一句话**：**别名单源与检查器必须被「主链路」真正消费，且消费点落在函数入口；常量定义得再对，没接进判定链就等于没定义。**

**13.0.13 号段本身也有时间轴：北交所 2025-10-09 已全面迁 920，静态号段表必然错一半（v3.43 新增）**

- **事实**：北交所自 **2025-10-09 起为存量上市公司全面启用 920 专属号段**，**43/83/87 三号段退出北交所舞台**（Tushare `bse_mapping` 官方口径：「为了将北交所股票与新三板股票在代码上彻底区分」；2024-04-22 起新上市公司先行启用 920，2025-05-06 六只存量试点切换，2025-10-09 剩余 242 只整体切换）。
- **病一（判据建立在已失效的旧映射上）**：v3.41/v3.42 把 `.BJ` 后缀 + 43/83/87 段判为「北交所个股」并**无条件返回 `cn_stock`**；但该段 2025-10-09 后【只属新三板】——带 `.BJ` 的旧段是**已失效写法**，静默归入 `cn_stock` 或 `neeq` 都是猜。
- **病二（92 段被两表共用 = 把改革成果抹掉）**：v3.41 把 `92` 同时写进 `neeq` 与 `bj_stock` 两份 prefix、靠「后缀消歧」；而 920 段是北交所【专属】、**无需消歧**，裸码 `920309` 因此被判 `neeq`（错）。
- **病三（第三处「定义了无人消费」）**：`MARKET_CODE_RULES["bj_stock"]` 与 `STOCK_PREFIX_RULES["BJ"]` 都在表里，但 `detect_market_type` **从不返回 `bj_stock`**、`MARKET_CONFIG_MAP` **没有 `bj_stock` 条目** → 表、判定、配置**三处分裂**。
- **病四（北交所并入 `cn_stock` = 规则全错）**：北交所涨跌幅 **30%**、**100 股起以 1 股递增**、T+1、个人门槛 **50 万 + 2 年**，与沪深 A 股**没有一条相同**；塞进 `cn_stock` 会让涨跌幅 / 最小申报单位 / 合格投资者闸门**全部跑错规则**。
- **硬要求**：① 北交所**独立成市** `bj_stock`，配置字典 `BSE` 必须注册进 `MARKET_CONFIG_MAP`（否则 `get_market_config("bj_stock")` 直接 `KeyError`）；② `STOCK_PREFIX_RULES["BJ"]=("920",)`；`neeq.prefix` 删 `92`、`bj_stock.prefix=["920"]`；③ `detect_market_type(code, market_type=None, as_of=None)` **新增 `as_of`**：`.BJ`/`bj` 前缀 + 旧段 → **给了 `as_of` 且 `<2025-10-09` 才判北交所**，否则查 `BSE_CODE_MIGRATION`（**全表从 Tushare `bse_mapping` 落盘，禁止手写 248 条**）命中即北交所、未命中 **`raise`**；段位与后缀真冲突（如 `600519.BJ`）→ **`raise`**；④ `.BJ`+920 段、裸码 `920xxx`、`bj920xxx` 一律 `bj_stock`。
- **验收判据**：① `detect_market_type("920309.BJ")==detect_market_type("920309")==detect_market_type("bj920309")=="bj_stock"`；② `get_market_config("bj_stock")["price_limit"]==0.3` 且 `["qty_step"]==1`；③ `detect_market_type("830799.BJ")` **必须 `raise`**（陈旧码，除非 `as_of<2025-10-09` 或命中 `bse_mapping`）；④ `detect_market_type("600519.BJ")` **必须 `raise`**（段位与后缀矛盾）；⑤ `detect_market_type("830799")=="neeq"` 且 `detect_market_type("920309")!="neeq"`。
- **一句话**：**代码号段本身也有 as-of 维度——把「当前号段」写死进判定链，等于把一次已完成的号段改革当成没发生；凡是「名称 / 代码 / 段位 ↔ 市场」的映射，都要能被时间轴裁决。**

**13.0.14 号段的 as-of 是【双边】的：新段有启用日，旧段有退出日（v3.44 新增）**

- **事实**：北交所 920 号段 **2024-04-22 上线启用**（2024-05-30 万达轴承 `920002` 为首只），**2025-10-09 存量全面切换**（43/83/87 退出）。**两个日期都是硬边界。**
- **病一（920 段没做「近端」as-of）**：`_resolve_bse_body` 里 `if body.startswith("920"): return "bj_stock"` **不看 `as_of`**——`detect_market_type("920002", as_of="2024-01-02")` 返回 `bj_stock`，**用了一个当时还不存在的代码** = 未来函数。
- **病二（裸码旧段漏了 as-of 语义）**：裸码 `43/83/87/88` 直接 `return "neeq"`；但这些段 2025-10-09 之前**仍属北交所**，`as_of="2024-01-02"` 时应为 `bj_stock`。否则历史回测把它当新三板，**涨跌幅 / 最小申报单位 / 合格投资者规则全错**。
- **硬要求**：① `BSE_CODE_MIGRATION` 增 `segment_effective_date="2024-04-22"`；② 920 段判 `bj_stock` **前**校验 `as_of >= segment_effective_date`，否则 `raise`（未来函数）；③ 裸码 / 带前缀的旧段分支接 `as_of`：`as_of < 2025-10-09` → `bj_stock`，否则 `neeq` / 查迁移表 / `raise`；④ 三类写法（`920002` / `920002.BJ` / `bj920002`）走**同一条** as-of 判定。
- **验收判据**：① `detect_market_type("920002", as_of="2024-01-02")` **必须 `raise`**（920 未启用）；② `detect_market_type("920002", as_of="2024-04-22")=="bj_stock"`（启用日当天有效）；③ `detect_market_type("920002", as_of="2024-04-21")` **`raise`**（启用前一天）；④ `detect_market_type("830799", as_of="2024-01-02")=="bj_stock"`；⑤ `detect_market_type("830799", as_of=None)=="neeq"`。
- **一句话**：**只要「名字 / 代码 / 段位 ↔ 市场」的映射带时间维度，as-of 就必须是【双边】的——只管旧段的死期、不管新段的生日，等于允许「未来函数」从新段进来。**

**13.0.15 验收脚本不能既是证据、又是可被随手涂改的证物（v3.44 新增）**

- **病一（改断言无锚定）**：本轮 `test_data.py` 的「指数成交额单位」断言被改（原式对指数恒得 ~0.6，因 `close` 是点位不是股价）。**改对了，但机制不安全**——验收脚本是**唯一**的合格证据，施工方红了就能改它，**改错也一样绿**。
- **病二（源不可达 = 静默通过）**：该断言只在**东财可达**时执行；东财不可达走新浪分支（`amount` 全 NaN）→ **静默 skip、计入通过**。它长期「绿」的真实原因是**从未真正执行**——「守卫装在会失灵的信息源上」在**验收层**复现。
- **硬要求**（`ACCEPTANCE_GOVERNANCE`）：① **脚本哈希锁定**（`script_globs=["test_*.py","tests/test_*.py","cli_commands/checklist.py"]`、`hash_manifest="acceptance_scripts.sha256"`），`on_hash_mismatch="require_declaration"`——**未声明的断言改动 = 该轮验收作废**；② **源依赖检查**：不可达时必须显式打标 `skipped_due_to_source`，`skip_counts_as="uncovered"`（计入「未覆盖」，**不计入 passed**），`forbid_silent_pass=True`；③ **核心口径检查必须有离线实现**（用 `data_cache/**.parquet` 复算），`offline_must_agree_with_online=True`；④ **单位不变式按资产类别分设**——个股 `amount/(close*volume)≈100`（强不变式，1 手=100 股），指数 `amount/(volume*100) ∈ [1,500] 元/股`（量级判据），**两者不得混用同一判据**。
- **验收判据**：① 保持 `test_data.py` 不变、故意把某条断言改错 → 验收集自检**报「未声明改动」**；② 模拟源不可达 → 该检查出现在「未覆盖」清单，**不出现在 passed**；③ 断开外部源，核心单位检查**仍能**用本地缓存跑出结论。
- **一句话**：**「测试全绿」只有在「测什么、怎么测、谁能改」都被外部锚定时才是证据；否则它只是一句自述。**

### 13.0.16（v3.45 新增·数据源适配器 fail-closed 闸门）

13.1 正文给了类骨架与四实现，但缺 6 个闸门键，路由器会静默 fail-open：

| 风险 | 闸门键 | 默认 | 触发行为 |
|---|---|---|---|
| 切换不告警 | `DATA_LONG_TERM["failover_log_required"]` | `True` | 每次源切换必须 `logger.warning` + notifier 推送，`max_consecutive_failures` 次失败后标记源 unhealthy |
| 跨源字段口径不一致 | `DATA_LONG_TERM["field_consistency_required"]` | `True` | akshare volume 单位（手/股）与 baostock 不一致时 `raise DataFieldInconsistencyError`，禁止静默拼接 |
| 无 token 源优先 | `DATA_LONG_TERM["tokenless_sources_first"]` | `True` | tushare 未配置 token 时跳过并打 info 日志，不抛错；不影响其他源 |
| 单源连坏 N 次 | `DATA_LONG_TERM["max_consecutive_failures"]` | `3` | 连续失败达阈值写入 `source_health.json` = unhealthy，路由跳过直到次日 health_check 通过 |
| 本地兜底失败 | `DATA_LONG_TERM["local_fallback_must_exist"]` | `True` | 全部远程源失败 + 本地缓存为空 → `raise DataUnavailableError`，禁止返回空 DataFrame |
| 探活结果落盘 | `DATA_LONG_TERM["source_health_file"]` | `"data_cache/source_health.json"` | health_check 每日开盘前跑一次，唯一写入目标 |

**验收判据**（写进 `tests/test_source_adapter.py`，不满足不算完工）：

1. `test_router_failover_logs_and_notifies`：主源 raise → 切备源，notifier mock 收到 1 条告警，日志包含「切换」字样；
2. `test_router_field_unit_conflict_raises`：mock akshare 返回 volume=手、baostock 返回 volume=股 → `DataFieldInconsistencyError`，不得返回拼接结果；
3. `test_router_skips_tushare_when_no_token`：tushare 未配 token → 不抛错、跳过、下一个源被调用；
4. `test_router_local_fallback_empty_raises`：所有远程源失败 + local 空 → `DataUnavailableError`；local 有数据时正常返回；
5. `test_health_check_writes_json`：健康检查跑完后 `source_health_file` 存在且含各源 `status/last_check/consecutive_failures`；
6. `test_unhealthy_source_skipped`：单源连续失败 ≥ `max_consecutive_failures` → 下次路由跳过该源，直接试下一个。

**回补清单（回到已交付模块改，不是「下一步注意」）**：

| 已交付模块 | 必须补什么 | 不改会怎样 |
|---|---|---|
| `data_fetcher.py` 及 `data/` 各出口 | 写盘带 `price_basis` + `schema_version`；读盘先判标记 | 迁移半途 → 静默错价 |
| `data/integrity.py` | 校验从「独立脚本」搬进读取路径 | 损坏检测永不触发 |
| `core/backtester.py` / `runner.py` / `paper_trader.py` | 入口**强制**建快照并绑 `data_version`；取股票池走 PIT | 结论不可复现、幸存者偏差 |
| `reports/report_archive.py` / `core/reporter.py` | 四份产物同生共死 + `meta_complete` 打标 | 索引悬空、统计混入不可复现结论 |
| `tools/cache_usage.py`（13.9 清理器） | 接 `CACHE_GOVERNANCE`，默认 dry-run + 引用检查 | **删掉幂等键 / 急停态 / 审计链** |
| `main.py report show` / `stats` | 展示缺失字段；统计默认过滤 | 闸门只单向生效 |
| `tools/migrate_cache_to_raw.py` | 原子 / 可续 / 可回滚 / 维护锁 | 半迁移 + 不可回滚 |
| `test_*.py` / `tests/test_*.py`（验收集） | 脚本哈希锁定 + 源依赖检查显式打标 + 核心口径离线实现 | 红了改断言照样绿、源挂了静默通过 |

### 13.0.17（v3.46 新增·13.1 回补：四类 fail-open 是「装错位置 / 装错对象」）

v3.45 的 6 个键解决了「有没有闸门」；13.1 实施后的实测暴露出**四类闸门装错位置 / 装错对象**：

**病一：单位口径表被复制成第二份（第五份清单换位置复发）**
- 现象：`config.DATA_SOURCE_UNITS` 按【AKShare 接口名】定义 `volume_unit` / `volume_factor`（如 `stock_zh_a_hist` → 手 / ×100）；适配器内又起一份按【源+市场+周期】索引的三元组表（如 `("akshare","cn_index","daily") → ("手",1,"手")`）。两套表用**不同维度**描述**同一件事实**，必然漂移——同一场景一份说乘 100、另一份说乘 1，于是出现「二次折算 100 倍」（本轮实测污染缓存 `amount/(close*volume)=0.01`）。
- 硬要求：① 单位乘数**只在 `config.DATA_SOURCE_UNITS` 定义**，适配器**不得**含任何硬编码 `×100` / `*100`；② 新增 `config.SOURCE_INTERFACE_MAP`（源+市场+周期 → 接口名）作为唯一索桥；③ `DATA_SOURCE_ADAPTER_GUARD.unknown_unit_combo_must_raise=True`——接口名不在 `DATA_SOURCE_UNITS` 里 → **`raise`**，不得默认乘 1。
- 验收判据：① 适配器源码 grep 不到 `* 100` / `*100`（除 config 引用）；② 传入未登记接口 → `raise`。

**病二：`internal_failover` 是「被守卫对象给自己发豁免」**
- 现象：为修「akshare 单点市场失败被误计为整源连坏」，适配器自加标记 `internal_failover=True`，此后**该源所有失败一律不计数、永不 unhealthy**。但「akshare 被墙 / 被限流」是**源级失效**，此时永不熔断 → 每次路由都去试它 → 反复重连（**正是封 IP 的触发条件**）、每次空耗 `15s × 内部回退级数`。
- 硬要求：① `internal_failover` **不得由适配器自声明**，必须由 `config.INTERNAL_FAILOVER_SOURCES` 白名单登记；② 豁免只对**市场级**失败生效（`counts_market_level_failure=False`），**源级失效必须计数**（`counts_source_level_failure=True`），阈值用 `internal_failover_max_consecutive_failures`。
- 验收判据：① 适配器里写 `internal_failover = True` 但不在白名单 → 启动 `raise`；② 模拟「所有内部回退路径都失败」连续 N 次 → 该源被标 unhealthy。

**病三：`local_fallback_must_exist` 是悬空键（定义了没人消费）**
- 现象：闸门键写进 `DATA_LONG_TERM`，但路由器**没有 LocalSource**，本地兜底甩给外层 `data_fetcher.get_daily`；于是**任何直接调用 `DataRouter.fetch` 的新路径（watch_only / 监控 / 新增引擎）都没有本地兜底保护**——守卫装在被绕过的位置。
- 硬要求：`DATA_SOURCE_ADAPTER_GUARD.router_must_hold_local_source=True`——`DataRouter` **必须自己持有** `LocalSource`，并在所有远程源失败时调用它；本地兜底是**路由器的职责**，不是调用方的。
- 验收判据：直调 `DataRouter.fetch`（不经 `get_daily`）在远程全挂 + 本地有数据时**能返回**；本地空时 `raise DataUnavailableError`。

**病四：`router_all_empty` 把「故障空」当「合法空」**
- 现象：判定「所有源干净返回空 → 标 `router_all_empty` 返回」，但**被限流 / 被墙的源常常返回空而不抛异常**——「净空」与「故障空」在实现上不可区分；后果是标的在数据源侧静默失效被当成「今天没数据」，一路静默到信号层。
- 硬要求：① `router_all_empty_requires_probe_evidence=True`——标 `router_all_empty` 必须附**证据**（探过的源列表 + 每源返回状态）；② `expected_trading_day_empty_must_raise=True`——当前**应为交易日 + 标的在市（PIT 可查）+ 仍净空** → **升级为异常**，不得当合法空。
- 验收判据：① 交易日 + 在市标的 + 全源净空 → `raise`；② 非交易日净空 → 返回空并附 probe 证据。

**已知欠账（本轮登记，未闭环）**：`get_realtime` 仍是单源快照、直连 `_request(ak.*_spot)`，**绕过字段一致性校验与 failover**。硬要求：即便单源、无备源可切，`get_realtime` **仍须过字段一致性校验**（`realtime_must_pass_field_consistency=True`）。

**一句话**：**闸门键只回答「有没有闸门」；13.1 真正暴露的是「闸门被复制成两份、被保护对象给自己发豁免、被甩给会被绕过的调用方、把故障空当合法空」——四类全是「守卫位置 / 守卫对象错了」，不是「守卫不够多」。**

### 13.0.18（v3.47 新增·13.1 回补第二战：七处「自证 / 静默缩减」）

13.0.17 解决的是「闸门装错位置」；本轮暴露的是**七处「判据被交给了被守卫的那一方」或「覆盖面被静默改动」**——**每一次都长得像「修好了」，但把裁判权交给了当事人自己**。

**病一：`empty_reason` 由取数层自证（被守卫对象给自己发退市证明）**
- 现象：为让「应交易日净空 → raise」放过退市标的，改由**数据层**在取到空表后填 `empty_reason="delisted_or_not_listed"`，路由器见该字段即按合法空返回。但判定「退市」的依据正是「取数返回空」——而这恰恰是**被限流 / 被墙源的表现**。于是：某源被限流、返回空表，取数层就把它标成「退市」，净空闸门**反而被绕过**。与 13.0.17 病二（`internal_failover` 自声明）**同族**。
- 硬要求：① `empty_reason` 唯一合法来源是**独立证券主数据**（`securities_master`，上市/退市状态表），由 `config.EMPTY_REASON_PROVENANCE.allowed_sources` 登记；② **禁止由「本次返回空」反推**（`forbid_infer_from_empty_result=True`）、**禁止取数层自行填写**（`forbid_fetch_self_declared=True`）；③ 「是否在市」随时间变化 → 必须带 `as_of` 且**走 `data/pit_index.py` 时点闸门**（`requires_as_of=True` / `must_pass_pit_guard=True`）。
- 验收判据：① 取数层（`data_fetcher` / 适配器）**不得出现** `empty_reason=` 赋值；② 被限流源返回空 + 无主数据证据 → 仍 **`raise`**；③ 退市标的（主数据 + `as_of` 可证）→ 合法空。

**病二：`tried` 漏掉「返回空表的源」= 证据链断裂**
- 现象：净空报错文案改成「已尝试 无」——把「返回空表」的源**排除在 `tried` 之外**，于是证据里看不出**试过谁、谁返回了什么**，正与 13.0.17 病四要求的「探过的源列表 + 每源返回状态」相矛盾。
- 硬要求：`tried` **必须包含所有被调用的源**（含返回空者），每项按 `["source","endpoint","status","rows","elapsed_ms"]` 记录（`config.EMPTY_REASON_PROVENANCE.tried_entry_schema`）。
- 验收判据：构造「A 源抛错 + B 源返回空」→ 报错文案与证据**同时出现 A、B**，且 B 的 `status="empty"`、`rows=0`。

**病三：draft 是「颜色」不是「权限」**
- 现象：`SPEC_PROVENANCE` 把施工方自撰的正文标 `draft`、`check-config` 给黄，但 **draft 仍 `exit=0`** —— 不阻断任何东西。于是 `authority` 只是一行打印，**自撰规格照样解锁实盘**。
- 硬要求：`config.SPEC_DRAFT_PERMISSION` —— `draft` 在 `live` / `live_sim` / `paper` **`raise`**；`backtest` / `research` 放行 + 粘性水印；`tooling`（含 `check-config` 自身）**永不失败**（`self_lockout_guard`，与 `SPEC_VERSION_CHECK` 同构）。
- 验收判据：正文标 `draft` → 启动 `live`/`paper` **报错**、`check-config` **仍能跑**、`backtest` 能跑但报告带 `spec_provenance_draft` 水印。

**病四：计数覆盖面静默缩减**
- 现象：上一轮报「20 套（根目录 9 + tests 11）」，本轮只报「9 套」，**无任何说明**。缩减本身不一定是错，但**静默缩减**一定是错：不可比 = 无法回答「这轮到底跑没跑」。
- 硬要求：`config.SUITE_COVERAGE_GUARD` —— `baseline_suite_count=20`、`must_not_shrink=True`、`shrink_requires_explicit_reason=True`、`shrink_counts_as_regression=True`、`silent_omission_forbidden=True`；根目录 9 套**与** tests 11 套都要**逐套件**报数。
- 验收判据：本轮报数套件数 < 20 且未写明理由 → 该轮验收按**不合格**处理。

**病五：`SOURCE_INTERFACE_MAP` 与 `_SUPPORTED_*_MARKETS` 是同一事实的两份清单**
- 现象：13.0.17 病一确立「单位口径表只能有一份」，但 `SOURCE_INTERFACE_MAP` 的 **key 集合**（源+市场+周期）必须与 `core/data_fetcher.py` 的 `_SUPPORTED_DAILY_MARKETS` / `_SUPPORTED_MINUTE_MARKETS` 完全对齐——本轮实测 23 vs 28 条，靠「**逐个手工补 key**」对齐。加一个市场就必再漂，且 `unknown_unit_combo_must_raise=True` 会让遗漏组合**每次取数都 raise**。
- 硬要求：`config.DATA_SOURCE_ADAPTER_GUARD.map_scope_must_equal_supported_scope=True` + `forbid_manual_map_extension=True` —— 接口映射的 key 集合必须**由 supported scope 派生或校验**（`map_scope_mismatch_action="raise"`），不得靠手工补表对齐。
- 验收判据：从 `_SUPPORTED_*_MARKETS` 生成全部 (源,市场,周期) 组合 → 逐个查 `SOURCE_INTERFACE_MAP`，缺任一即 **`raise`**。

**病六：外部依赖脚本的「项数」是变量，不能叫「冻结口径」**
- 现象：`test_data.py` 的核查项数实测在 **13 / 12 / 19** 之间漂移（随数据源可达性、标的可用性变化）。把一个非确定值叫「冻结口径」自相矛盾：能冻结的只有**上界**，实测值必须**原始上报**。
- 硬要求：`config.NONDETERMINISTIC_SCRIPT_GUARD` —— `must_report_raw_observed=True` + `must_report_fixed_upper_bound=True`（双报）、`cannot_be_sole_evidence=True`（不得作为守卫生效的唯一证据）、`deterministic_anchor_required=True`（须配一份**纯离线、项数固定**的锚点套件，如 `tests/test_source_adapter.py` / `tests/test_spec_check.py`）。
- 验收判据：报数同时给出「本轮实测原始数」与「确定性上界」；无确定性锚点 → 该轮不得以 `test_data` 单独支撑合规结论。

**病七：验收脚本「改完顺手同步哈希」= 运动员改成绩单再自己签字**
- 现象：本轮改了 `tests/test_source_adapter.py` 后，**同一次操作里**把 `ACCEPTANCE_GOVERNANCE.script_hashes` 同步为新值 —— 于是 13.0.15 的「脚本哈希锁定」被自己解开，「未声明的断言改动 = 该轮验收作废」形同虚设。
- 硬要求：`config.ACCEPTANCE_GOVERNANCE` —— `script_hash_self_sync_forbidden=True`（禁止「改脚本 + 同轮同步 manifest」并据此宣告通过）、`script_hash_change_requires_changelog=True`（变更必须留痕：改哪条、为什么改）、`changed_script_excludes_its_own_verdict=True`（被改脚本自身的判定不得作为「本次改动正确」的证据）、`script_hash_authority="reviewer_published"`。
- 验收判据：改了任一 `test_*.py` 的那一轮，其「通过」结论**不得由该脚本自身单独支撑**；哈希变更需在变更记录中列出（改哪条、为什么）。

**一句话**：13.0.17 收的是「闸门装错位置」；13.0.18 收的是**「判据被交给了被守卫的那一方」**——退市证明由取数层自己签、规格权威由施工方自己发、验收成绩由考生自己改、覆盖面由报数人自己缩。凡是「自己证明自己」的地方，闸门都等于没装。

### 13.0.19（v3.48 新增·13.1 回补第三战：七处「看得见的都对了，看不见的没人看」）

13.0.18 收的是「自证」；本轮收的是**「被度量的对象选错了层级」**——闸门数没少、判据没少、名字没少，但**「每套里有多少项」「上界是不是真上界」「两份配置是不是同构」这三处没有人看**。它们共同的特征是：**看起来全对，因为被检查的那一层本来就不会出错。**

**病一：套件数没少 ≠ 覆盖面没少（「单套瘦身」是闸门的盲区）**
- 现象：本轮报「20 套（根 9 + tests 11，无缩减）」，`SUITE_COVERAGE_GUARD.must_not_shrink` **通过**。但同时 `alpha101` 断言 **10→2**、`factor` **58→6**、`loader` **20→4**——**把 58 条断言删到 6 条，套件还在、名字还在、闸门依然通过**。套件数这道闸门对「单套瘦身」完全失明：它数的是**盒子**，不是**盒子里的东西**。
- 硬要求：`config.SUITE_COVERAGE_GUARD` —— `per_suite_baseline_required=True`（每套须登记基线项数）、`per_suite_regression_must_be_declared=True`（单套下降同样须显式说明，理由不足按回归计）、`per_suite_regression_threshold_pct=20`、`baseline_registry_file="suite_baselines.json"`、`missing_baseline_action="raise"`（新套件无基线 → **报错**，禁止「默认 0」= 永远不回归）。
- 验收判据：本轮逐套件表里任一已登记套件的项数跌幅 > 20% 且未写明理由 → 该轮按**静默缩减**计，不合格。

**病二：同一张表里混用两种计数单位（数出来的东西不可比）**
- 现象：逐套件表里，根目录 9 套报的是**脚本自身断言数**，tests 11 套报的是**pytest 收集到的用例数**。两种单位并排放在一栏里对比 / 相加 —— 于是「433（pytest）」与「20 套 / 若干断言」是**两个不可比的数**。这也正是「口径必须冻结」在**表内**的复现：不是跨轮换了口径，是**同一行里就换了**。
- 硬要求：`count_unit_enum=["script_assertion","pytest_case"]`、`count_unit_declared_per_suite=True`（每套必须显式声明本行的计数单位）、`per_suite_count_must_be_comparable=True`（同一张表内混用两种单位 → 该表不合格）。
- 验收判据：逐套件表必须逐行带 `unit` 字段；出现两种单位且未分栏标注 → 不得作为合格证据。

**病三：「确定性上界」与实测值逐字相等（上界是事后反填的）**
- 现象：本轮报「`test_data` **34** 原始项 / 确定性上界 **34**」——**上界与实测逐字相等**。一个「每次都与实测相等」的上界，不是上界，是**把实测抄了一遍**。若上界由本轮**可达标的数**算出，那么数据源被限流的那一轮，上界会**跟着一起缩**——**闸门随被守卫对象一起松**，而「原始 + 上界」双报就退化成「同一个数报了两遍」。
- 硬要求：`config.NONDETERMINISTIC_SCRIPT_GUARD` —— `upper_bound_must_be_offline_computable=True`（上界须为**模块级静态常量** / 静态集合长度，不联网可算）、`upper_bound_must_not_be_derived_from_observation=True`（禁止用本轮实测反填）、`observed_must_not_exceed_bound=True`（实测 > 上界 → **`raise`**，证明上界不是上界）、`bound_equals_observed_must_be_explained=True`（恰相等须说明，否则疑为反填）。
- 验收判据：把 `TARGETS` 静态常量与固定核查项数**离线相乘**得上界；断网跑一轮，上界**不变**。

**病四：证据源的「独立性」只取了名字，没验上游**
- 现象：v3.47 把「退市证据」收口到新建的 `security_master.py`，称其为「独立证券主数据」。但**「独立」是指取数路径不同上游**，没有任何东西约束它：若 `security_master` 底层仍走 akshare / tushare（与**行情同一个被封的出口**），被限流时**主数据与行情会同时返空**——主数据照样把「被限流」翻译成「退市」。这是 13.0.17 病二（**守卫装在会失灵的信息源上**）在**证据源**这一层的复现：把守卫从「取数层」搬到了「另一个更名不改姓的取数层」。
- 硬要求：`config.EMPTY_REASON_PROVENANCE` —— `evidence_source_must_be_independent=True`、`listing_probe_source="securities_master"`、`independent_upstream_required=True`、`forbid_shared_upstream_with_market_data=True`（主数据上游 ∈ `DATA_LONG_TERM.data_source_priority` → **`raise`**）、`forbid_fallback_to_market_source=True` + `listing_probe_unavailable_must_raise=True`（主数据不可用 → **`raise`**，**不得回退行情源反推「是否在市」**）；`config.DATA_SOURCE_ADAPTER_GUARD` 增 `evidence_source_upstream` / `evidence_upstream_must_be_declared` / `evidence_upstream_must_not_be_in_market_source_priority`。
- 验收判据：① 把 `security_master` 的上游改成 `"akshare"` → 启动即 **`raise`**；② 断开主数据源 → 净空判断**报错**，不得改用行情返空反推。

**病五：draft 模式矩阵是「默认放行」的（枚举不完 = fail-open）**
- 现象：`SPEC_DRAFT_PERMISSION.mode_matrix` 只列了 6 个模式（`live`/`live_sim`/`paper`/`backtest`/`research`/`tooling`）——**没被列出的模式怎么办，它没说**。新加一个模式（如 `live_remote` / `sandbox` / `replay`）时，它既不在 `raise` 组、也不在 `warn` 组 → 实现方要么 `KeyError`，要么「**查不到就当放行**」。这与本会话反复出现的「**清单枚举不完 = fail-open**」（信号出口清单、标的池入口清单、能关闸门的开关清单）**同族**，只是这次发生在**权限矩阵**上。
- 硬要求：`config.SPEC_DRAFT_PERMISSION` —— `mode_matrix_default="deny"`（**默认拒绝**，能被明确列出才放行）、`unknown_mode_action="raise"`、`self_lockout_exemption_is_enumerated=True` + `self_lockout_exemption_modes=["tooling"]`（唯一豁免面必须显式登记）。
- 验收判据：构造一个 `RUN_MODE="live_remote"`（矩阵里没有）→ 启动 **`raise`**，**不得**默认放行；`check-config` 自身仍能跑。

**病六：哈希 manifest 可被「删行」（删测试的隐身通道）**
- 现象：`acceptance_scripts.sha256` 是「路径 → 哈希」的**映射表**，它既能**改写**（把某条的值换成新哈希）也能**删行**（把某条整行删掉）。而**删除正是「测试红了 → 删掉它 → 变绿」的隐身通道**：删一个测试文件，manifest 里少一行，哈希校验**照样全过**。13.0.18 病七只堵住了「改」，没堵住「删」。
- 硬要求：`config.ACCEPTANCE_GOVERNANCE` —— `hash_ledger_file="acceptance_scripts.ledger.jsonl"`、`hash_ledger_append_only=True`、`ledger_entries_immutable=True`、`forbid_hash_entry_removal=True`、`script_deletion_counts_as_change=True`、`deleted_script_must_remain_in_ledger=True`、`script_change_requires_spec_bump=True`（改验收脚本须伴随一次规格版本变更 + 变更说明）、`on_ledger_not_append_only="raise"`。
- 验收判据：删掉任一 `test_*.py` 后若不追加 `{"action":"delete",...}` 条目 → 校验 **`raise`**；账本历史条目被改写 / 删除 → **`raise`**。

**病七：两机「配置键集合一致」是口头断言（差 37 行只说了一句"注释"）**
- 现象：沙箱 `config.py` **2341 行** vs 本机 **2304 行**，施工方自述「配置键集合一致（17 键 / 20 套 / 15+10）」——判据只有一句「差异来自沙箱含施工过程注释」。本轮**恰好只差注释**，可下一轮就可能是「**少一个 guard 键**」而没人看得出来：判据、代码、交付物跨机不一致，正是本会话从头到尾的那个病，只是这次发生在**两台机器之间**。「两份 config 是否等价」机器一秒能算，人手一眼看不出来。
- 硬要求：新增 `config.CONFIG_SURFACE` —— `surface_scope`（顶层大写常量名 + 每个 guard 块的键名，**递归排序后**）、`surface_hash_algo="sha256"`、`surface_hash_file="config_surface.sha256"`、`must_be_printed_by_check_config=True`、`ignore_values=True`（只比**结构**不比取值）、`comment_and_blank_lines_excluded=True`（**注释 / 空行差异不得影响 surface**——正是本轮 37 行之差）、`must_report_missing_and_extra_keys=True`（不一致时**打印差在哪几个键**，不得只说「不一致」）。
- 验收判据：两机各跑 `check-config` 打印的 `config_surface.sha256` **必须相同**；在一台机器上删掉 `CONFIG_SURFACE` 里的任一键 → 哈希变化且差异清单点出该键名。

**一句话**：13.0.17/13.0.18 收的是**装错位置**和**自证**；13.0.19 收的是**「度量的层级选低了」**——数套件不数项数、报上界不核上界、验名字不验上游、列白名单不给默认值、比总数不比结构。凡是「**被检查的那一层本来就不会出错**」的地方，闸门都是绿的，而它守的东西没被守。

### 13.0.20（v3.49 新增·13.1 回补第四战：四处「判据本身是形容词，不是白名单」）

13.0.19 收的是「被度量的层级选低了」；本轮收的是**「判据的定义本身选低了」**——表面看每条规则都有键、有动作、有验收判据，但规则的**输入集合**靠形容词描述（「每个 guard 块」「验收脚本」「合法模式」），没给白名单。结果是：**两个不同的实现方，读同一条规则，会算出两份不同的输入集合**——于是「闸门是否通过」本身就取决于实现方怎么理解那个形容词。

**病一：surface 算法没给递归白名单（哈希不一致 = 比了两份不同的东西）**
- 现象：v3.48 回执，沙箱 `config_surface.sha256=d2e91d81…`（162 常量+1235 递归=1397 元素），本机 `99d0a55d…`（167+1043=1210 元素）。沙箱实现递归**全部**顶层字典（含 `CN_INDEX`、`BSE`、`BROKER_DEFAULT` 等业务配置），本机只递归**治理类**字典——**两个算法递归的范围不同，哈希自然不同**。而 `CONFIG_SURFACE.surface_scope` 写的是「顶层大写常量名 + **每个 guard 块**的键名」——「guard 块」是个**形容词**，不是白名单。
- 硬要求：`config.CONFIG_SURFACE` —— `surface_recurse_blocks` 必须是**显式白名单**（30 个治理/守卫/合规字典，见 config 注释清单）；`recurse_blocks_exhaustive=True`（白名单外一律不递归，新增 guard 块须先加白名单+bump 版本）；`missing_recurse_block_action="raise"`（白名单里的块在 config 里找不到 → raise，防止改名漏检）。
- 验收判据：两机用同一白名单跑 `check-config`，`config_surface.sha256` **必须相同**；把白名单里加一个不存在的字典名 → 启动 **raise**；把一个治理字典改名但忘记更新白名单 → **raise**。

**病二：基线锚在「本轮当前值」= 让历史瘦身合法化（基线是棘轮，不是快照）**
- 现象：v3.48 回执 `suite_baselines.json` 登记的基线为 {49,32,19,34,75,11,80,31,14,2,6,4,28,12,16,14,18,19,25,18}，**逐项等于 v3.47 实测**。但 v3.44~v3.47 期间 alpha101（10→2）/factor（58→6）/loader（20→4）已经瘦身，基线锚在「瘦身之后的当前值」= 闸门对**之前发生的瘦身**完全失明；被瘦身的测试永远不会回归。基线是**棘轮**（只能上、不能下），不是每轮快照。
- 硬要求：`config.SUITE_COVERAGE_GUARD` —— `baseline_must_anchor_historical_peak=True`；`baseline_initial_peaks` 以 **v3.40 稳定态**为锚人工核定（`test_alpha101.py=10`、`test_factor.py=58`、`test_loader.py=20`，其余套件与 v3.48 实测一致）；`current_below_peak_must_carry_recovery_plan=True`（当前 < 峰值 → 必须附恢复计划）；`silent_ratchet_down_forbidden=True`（禁止以当前值重设基线，基线棘轮只能上调）。
- 验收判据：① 不登记恢复计划的情况下 alpha101/factor/loader 当前实测 < 基线峰值 → **raise**（回归）；② 施工方试图把 baseline 中任意值往下调（如 factor 58→6）→ 校验 **raise**（棘轮不能下）。

**病三：账本只登记 2 条 = 其余 20+ 脚本无人守（登记即守护、未登记即裸奔）**
- 现象：v3.48 回执 `acceptance_scripts.ledger.jsonl` 仅 3 行（meta+2 register），但 `script_globs=["test_*.py","tests/test_*.py","cli_commands/checklist.py"]` 匹配 **20+ 套**验收脚本。只登记本轮改过的脚本、其余不登记 = 这些脚本的删改**永远不触发 hash 校验**——**登记一个文件 = 守一个文件；没登记的文件 = 没人守。** 这是「清单枚举不完 = fail-open」在**账本覆盖**上的复现。
- 硬要求：`config.ACCEPTANCE_GOVERNANCE` —— `ledger_must_cover_all_script_globs=True`（每轮 `check-config` 扫描 glob，所有命中文件都必须在账本里）；`unregistered_script_action="raise"`（未登记脚本存在 → 验收不合格）；`ledger_must_have_effective_entry_per_script=True`（每个脚本账本里必须有一条**非 delete 的末条**记录）；`legacy_manifest_migration_required=True`（旧 `acceptance_scripts.sha256` 中全部条目须迁移到 ledger 后旧表再冻结）。
- 验收判据：① glob 命中但账本漏登一个 `test_*.py` → 启动 **raise**；② 把某个脚本记成 `action:delete` 作为末条（没有后续 add/modify）→ **raise**（删脚本必须显式声明且仍需在账本里）。

**病四：`unknown_mode_action=raise` 靠字典 miss 碰巧拦住（模式集合必须封闭）**
- 现象：v3.48 给 `SPEC_DRAFT_PERMISSION` 加了 `mode_matrix_default="deny"` + `unknown_mode_action="raise"`。但「unknown」是怎么判定的？——**靠 `mode_matrix.get(run_mode)` miss**。这有两个洞：① CLI `--mode` 参数可以传任意字符串（`"live_but_skip_check"`/`"prod"`/`"realtime"`/拼写错误），如果代码某处用 `.get(mode, matrix_default)` 兜底或先 `.upper()/.lower()` 再查，miss 就不发生；② 矩阵没定义「合法模式全集」是什么，`RUN_MODE` 来自 `.env` 笔误（如 `"liv "` 带空格）能不能被 raise，取决于实现细节。**这是 fail-open 在「模式字符串校验」层的复现**：合法集合没封闭，靠字典 miss 碰巧拦住。
- 硬要求：`config.SPEC_DRAFT_PERMISSION` —— `valid_mode_set_required=True`；`valid_modes=["backtest","research","paper","live","live_sim","tooling"]`（**合法模式全集**，显式枚举）；`invalid_mode_action="raise"`（RUN_MODE ∉ valid_modes → **在查矩阵之前就 raise**，不依赖字典 miss）；`cli_mode_argument_validated=True`（CLI `--mode` 参数必须走此校验）。
- 验收判据：① `RUN_MODE="liv "`（带空格笔误）→ 启动 **raise**（即使矩阵里没有该键，也是靠 valid_modes 先验拦住而非 miss）；② CLI `python main.py --mode prod_live xxx` → **raise**；③ 在代码里把矩阵加一个键 `"prod_live": "allow"` 但不加进 valid_modes → 依然 **raise**（矩阵白名单不得超出合法集合）。

**一句话**：13.0.19 收的是「数错了层级」；13.0.20 收的是**「判据的输入集合没钉死」**——形容词（「每个 guard 块」「所有脚本」「合法模式」）无法机器校验，必须换成**白名单枚举**。凡是判据本身依赖人类理解「这算不算 guard 块/算不算脚本/算不算合法模式」的地方，闸门都会在实现方选择另一种合理解释时静默失效。


### 13.0.21（v3.50 新增·13.1 回补第五战：判据「不可复现」）

13.0.20 收的是「判据的输入集合没钉死」；本轮收得更狠一层——**判据钉死了，但它【不可复现】**：白名单给了、动作给了、验收判据也给了，然而**同一个元素集合变成哈希的那一步没有唯一答案**。于是「闸门是否通过」取决于实现方选哪种序列化；**两个都按规则实现的人，算出两个不同的值，还都算「对」**。

**病一：集合钉死了，序列化 / 算法没钉死（期望值不可复现 = 等于没有期望值）**
- 现象（本轮沙箱实测）：v3.49 登记的 `config_surface.sha256 = d7df508d…`，元素数 755（162 常量 + 593 键）**可复现**，但**哈希算不出来**——把 `sorted(set(常量) ∪ set(键))` 按「各排序后拼接 / 全局去重 / 加尾换行 / 限定路径键 / JSON 序列化」等**七种自然读法**逐个试，没有一种等于 `d7df508d…`。即**「哪些元素进集合」定死了，「集合怎么变成哈希」没定死**——连看守者都复现不出登记值，任何人都不可能独立验证自己算得对不对；两机「不一致」也分不清是**数据差**还是**算法差**。
- 硬要求：`config.CONFIG_SURFACE` —— `surface_algo_id="cs-v1"`；`surface_algo_steps` 给到 S1~S5 每一步（AST 采集 → 只下钻 dict 的键集 → ASCII 升序去重并集 → LF 逐行连接 + 末尾一个 LF → sha256）；`surface_golden_vector`（固定输入 `{"b":1,"A":{"c":2},"L":[{"dropped":9}]}` + 常量 `["GOLDEN","Z"]` → 元素 `["A","GOLDEN","L","Z","b","c"]` → `sha256=72bc8831…`）+ `golden_vector_must_match_action="raise"`；`surface_canonical_text_required=True`；`surface_dump_file="config_surface.elements.txt"` + `dump_required_on_mismatch=True`。
- 验收判据：① 实现方对黄金向量算出的 sha256 ≠ `72bc8831…` → **raise**（**先证算法，再比配置**）；② 两机各自 `check-config` 后导出 `config_surface.elements.txt`，`comm -3` 必须为空；③ 故意把「下钻 list」写进实现 → 黄金向量立刻不等（`L` 内的 `dropped` 被算进来）。

**病二：期望值 / 峰值由人工手填，没有推导与证据（判据又交给了被守卫的一方）**
- 现象：`surface_expected_counts`、`baseline_initial_peaks`、`suite_baselines.json` 的 `historical_peak` 全是**人手写下的数字**。填 58 还是 60、峰值哪一轮达到、元素数 755 从哪来——**没有任何东西能复核**。与本会话从第 11 步起的病同源：**判据（期望值）由被守卫的一方自己填**，只是这次填的是「期望哈希 / 期望元素数 / 期望峰值」。
- 硬要求：`config.SUITE_COVERAGE_GUARD` —— `historical_peak_must_cite_evidence=True` + `peak_evidence_schema=["suite","historical_peak","spec_version","command","output_sha256"]` + `peak_evidence_file="suite_baselines.evidence.jsonl"` + `peak_from_declaration_action="raise"`；`config.CONFIG_SURFACE.hand_typed_expected_forbidden=True`（期望值须可由冻结算法复算）。
- 验收判据：① 任一 `historical_peak` 缺 `spec_version`/`command`/`output_sha256` → **raise**；② 把 `surface_expected_counts.n_elements` 随手改成 999 → 复算不等 → **raise**（证明它是被算出来的，不是被写的）。

**病三：常量集用运行期命名空间（`dir()`）采集 = 跨机不稳**
- 现象：`dir(config)` / `vars(config)` 会返回**从别处 import 进来的**名字。若某台机器的 `config.py` 里写了 `from core.x import SOME_UPPER_NAME`，它会**被算成顶层常量**；换一种写法（`import core.x` + `core.x.SOME_UPPER_NAME`）就又不算——**同一份配置、两种写法、两个哈希**。这正是本轮两机常量数 162 vs 167 那 5 个的可疑来源。
- 硬要求：`config.CONFIG_SURFACE.surface_collection_must_be_ast_based=True` + `dir_based_collection_forbidden=True` —— 常量集必须**从源码 AST 取**「顶层赋值语句的目标名」，不看运行期命名空间。
- 验收判据：① 实现若用 `dir()` → 专项检查失败；② 在 `config.py` 顶部加一行 `from x import FOO_BAR`（只导入、不赋值）→ surface **不得变化**。

**病四：白名单自身没有完备性校验（漏纳新 guard 块 = surface 失明；误纳业务块 = 业务数据污染治理面）**
- 现象：`recurse_blocks_exhaustive=True` 只保证「白名单内的都递归」，**不保证「该进白名单的都在」**。新加一个 `NEW_THING_GUARD` 而忘了加白名单 → 该守卫块**整体不进 surface**，其任何增删都**不会被跨机比对发现**（与 `must_not_shrink` 只数套件数同族）。反向：本轮实测 `UNIVERSE_RESOLUTION_GUARD` 的键集含 **12 个股票代码键**（`known_ambiguous_symbols`），加一个歧义代码就会改动「治理面哈希」——**业务数据与治理结构混在同一张哈希里**。
- 硬要求：`config.CONFIG_SURFACE` —— `whitelist_completeness_required=True` + `guard_block_name_pattern`（块名命中 `_GUARD/_CONFORMANCE/_SAFETY/_GOVERNANCE/_PROVENANCE/_PERMISSION/_LONG_TERM/_HARDENING` 或 `^RISK$`/`^CONFIG_SURFACE$`/`^EXECUTION_MODEL$`/`^SPEC_VERSION_CHECK$` 者必须在白名单或 `whitelist_exclusions` 中）+ `whitelist_exclusions`（显式排除须带理由）+ `unlisted_guard_block_action="raise"`。
- 验收判据：① 新增 `FOO_GUARD = {...}` 但不加进白名单 → 启动 **raise**；② 把 `INDICATOR_HARDENING` 临时改名 → **raise**。

**病五：账本「只追加」是政策不是机制；迁移可能重拍快照洗白改动**
- 现象一：`hash_ledger_append_only=True` 只是 config 里的一句话。`acceptance_scripts.ledger.jsonl` 是普通文本，改一条、插一条、删一行——**没有任何东西会因此报错**。现象二：旧 `acceptance_scripts.sha256` 迁到 ledger 时，若实现是「对**当前**文件重算哈希写进账本」，则 v3.47→v3.49 之间被改动过的脚本会被**合法化**——**迁移成了洗白通道**。
- 硬要求：`config.ACCEPTANCE_GOVERNANCE` —— `ledger_hash_chain_required=True` + `ledger_entry_must_include_prev_sha256=True` + `prev_entry_field="prev_entry_sha256"` + `entry_field="entry_sha256"` + `chain_genesis="GENESIS"` + `chain_break_action="raise"`；`migration_must_verify_old_hash_first=True` + `rehash_on_migrate_forbidden=True` + `migration_entry_requires_old_and_new_hash=True` + `migration_hash_mismatch_requires_declaration=True`。
- 验收判据：① 在第 2 条与第 3 条之间**插入**一条 → 链校验 **raise**；② 把某条 `reason` 文字改掉 → `entry_sha256` 变、后一条 `prev_entry_sha256` 对不上 → **raise**；③ 迁移时「当前文件哈希 ≠ 旧 manifest 哈希」却直接写进账本 → **raise**。

**一句话**：13.0.20 收的是「判据的输入集合没钉死」；13.0.21 收的是**「判据不可复现」**——给了白名单、给了动作、给了验收判据，但**从集合到哈希那一步没有唯一答案**，或者**期望值是人手填的、无证据的**。凡是「两个都按规则实现的人会得出两个不同结果」的地方，闸门都还没真正生效。**先让判据可复现，再谈闸门是否通过。**


### 13.0.22（v3.51 新增·13.1 回补第六战：判据可复现了，但「比对基准」没钉死）

13.0.21 收的是「判据不可复现」——算法给了、黄金向量给了。本轮收的是**再往前一步**：判据可复现了，但你拿它去比的两个东西**不是同一类**，于是「不一致」也读不出结论。

**病一：跨版本比对 = 拿两面颜色不同的墙相减，差异里混着「版本」和「漏合并」**
- 现象（本轮沙箱实测）：Trae 回执「本机 515 去重键 vs 沙箱 586 去重键 → 少 71」。但把沙箱的 **v3.49 快照**（`config.py.v349.bak`，同版本对照物）用同一算法算出来是 **162 常量 / 541 去重键 / 703 元素**，而 v3.50 是 **162 / 586 / 748**——**常量零差、v3.50 相对 v3.49 只增键不删键**。所以那「71」的真身是 **45（v3.50 合法新增）+ 26（真实结构差）**。**拿本机 v3.49 去减沙箱 v3.50，等于拿两面颜色不同的墙相减**：差里既有「版本不同」又有「漏合并」，定不出是哪一个。
- 硬要求：`config.CONFIG_SURFACE` —— `compare_requires_same_spec_version=True`、`compare_requires_same_algo_id=True`、`compare_requires_same_whitelist=True`、`cross_version_compare_action="refuse"`（版本 / 算法 / 白名单任一不同 → **拒绝比对**，先对齐再比）、`compare_baseline_dump_per_version_required=True`（每个版本各留一份 dump，供同版本 comm）。
- 验收判据：① 拿两份 `spec_version` 不同的 `elements.txt` 直接 `comm -3` → **拒绝**（提示先对齐版本）；② 对齐版本后，同一份算法在两机算出的哈希必须相等。

**病二：白名单「完备」但「不纯」——业务样例键混进治理面**
- 现象：`whitelist_completeness_required` 只管「该进的都进了」，不管「进来的干不干净」。本轮实测 `UNIVERSE_RESOLUTION_GUARD` 有 **12 个股票代码键**（分挂 `segment_decision_examples` 与 `known_ambiguous_symbols`），全被递归进治理面哈希——**往示例表里加一个代码，就改动「治理结构哈希」**，是纯噪声（false positive），还会把真正的治理键变化淹没。
- 硬要求：`config.CONFIG_SURFACE.whitelist_exclusions`（逐块给出剔除规则，带 `reason`）+ `business_key_pattern_excluded=True`（业务键按模式剔除）+ `exclusion_must_cite_reason=True`（每条排除必须写理由）。实现须「剔代码键、保留承载它的结构键名」（`keep_container_key`）。
- 验收判据：① 往 `segment_decision_examples` 加一个示例代码 → surface **不得变化**；② 删掉 `known_ambiguous_symbols` 这个**键名本身**（结构变化）→ surface **必须变化**。

**病三：期望计数是【产物】不是【判据】——拿它决定通过与否，红得毫无意义**
- 现象：`surface_expected_counts` 是手填的 `{162,638,586,748}`，而 `--check` 用它决定 exit code。可这个数是「这份 config 此刻长什么样」的**结果**——config 一旦合法增键它就变，于是**闸门天天红、红得没有信息量**；更坏的是，为让它变绿，人会去**改那个数**（= 把判据改成结果）。
- 硬要求：`config.CONFIG_SURFACE.frozen_counts_are_outputs_not_criteria=True` + `expected_counts_mismatch_action="warn_not_fail"`——`--check` **只对黄金向量失败 exit 1**；计数不匹配只 warn + 打印 diff（它是快照，不是门槛）。真正冻结的是**算法 ID + 黄金向量 + 白名单纯净规则**，不是数字。
- 验收判据：① 合法新增一个 guard 键 → 计数变、**不 exit 1**；② 黄金向量被改坏 → **exit 1**。

**病四：黄金向量没覆盖「去重」这条路径**
- 现象：原向量 `consts=["GOLDEN","Z"]` 与 block 键 `{b,A,L}` **无交集**，所以 S3 里 `set(常量) ∪ set(键)` 的**去重那一半从未被执行**——若某实现漏了去重，向量照样通过。
- 硬要求：`golden_vector_must_cover=["ast_const","dict_recurse","list_not_recursed","set_dedup","lf_join","trailing_lf"]`；向量 `consts` 改为 `["A","GOLDEN","Z"]`（"A" 与 block 内键重名 → 强制走合并去重；元素与哈希**不变**，但去重被覆盖）；`non_dict_block_action="raise"`（白名单块不是 dict → raise，不得静默返回空）。
- 验收判据：① 实现里删掉 `set(...)` 去重 → 黄金向量 **不等**；② 白名单块写成 list → **raise**。

**病五：回退声明靠「日志字符串被测试嗅到」，不靠结构化字段**
- 现象：v3.49→v3.50 间抓出的真实缺口——实时源全灭 + 本地有库时，返回本地累计帧 `rows=0`，当日空缺**没有任何结构化声明**，只打了一句「已回退」。它是被 `test_data` **读日志文本**抓到的；若那条测试不在，这个「故障空被当成正常空」就漏了。
- 硬要求：`config.DATA_LONG_TERM` —— `local_fallback_must_declare_today_missing=True` + `missing_today_must_be_structured_field=True` + `today_missing_field="today_missing_declared"`（回退帧必须带显式字段，而不是靠日志字符串）。
- 验收判据：① 强制实时源全灭 → 回退帧的 `today_missing_declared` 必须为真；② 去掉日志行但保留字段 → 检测仍成立（证明验的是字段，不是文本）。

**一句话**：13.0.21 收的是「判据不可复现」；13.0.22 收的是**「判据可复现了，但你拿去比的两个东西不是同一类，而且期望值被当成了门槛」**——凡是「两个不同版本的集合相减」「业务数据混进治理面」「拿快照数字卡通过」的地方，比对都还没真正成立。**先把版本钉平、把面洗净，再谈比对结果。**


### 13.0.23（v3.52 新增·13.1 回补第七战：发布方自己的产物没钉死，比对方的施工问题更致命）

发现（本轮实测·发布方过错）：
① v3.51 交付的 tools/compute_config_surface_cs_v1.py 本身有两个 bug：load_config(path) 声明了
   path 形参却硬编码读 config.py；且不接受位置参数 / --dump → 用户拿老版本 config 跑必报
   KeyError: 'surface_algo_id'；
② v3.51 沙箱给出的 config_surface.v349.elements.txt（703 行）不是用参考实现算法算的（用了错误的
   AST literal_eval 递归，把 tuple/list 也展开了），导致对照表与真实结构差 50+ 键；
③ 「沙箱 v3.49→v3.51 差 12 删除 + 61 新增」是错误归因——v3.49 时期没有 whitelist_exclusions；
④ v3.47 让施工方加的 SUPPORTED_KLINE_MARKETS、v3.45~v3.49 期间施工方自建的
   DATA_SOURCE_META / QI_MONITOR_ALERTS / QI_REITS_PREMIUM_THRESHOLDS / QI_NEEQ_ZERO_VOLUME_DAYS
   五个顶层大写常量，沙箱 config 漏发，导致两机常量集差 5，哈希不可能相等——发布方漏发。


### 13.0.24（v3.53 新增·长周期回测第一轮确立：风控的参数面与口径面必须入守护）

背景（2026-11-20 长周期回测首轮 + 缺陷修复复跑）：回测闸门七类全过后，评审抓出两处
「守卫逻辑对了、但守卫的参数/口径没人看着」——**守卫的强度不只取决于逻辑对不对，还取决于
它的参数有没有人看着**：

① 🔴 **发现（风控安全参数游离在治理面之外）**：熔断自动恢复参数
   `halt_recover_stabilize_days=3`、`halt_recover_enabled=True` 以「模块默认」放
   `core/risk.py`，未进 `config.RISK`——它不在任何哈希守护之下，**改代码即可绕过、
   无对拍、无账本**。风控恢复阈值是安全参数，必须进 config 并接受对拍。
   确立：安全参数一律显式登记到治理白名单内的配置块（本条：`RISK.account`），
   `RISK` 在 surface 白名单内，**加键即改治理面哈希 → 必须走正式版本滚动**
   （bump 版本头 + 重算黄金向量 + 重登记），**禁止在同版本内偷改**。
② 🔴 **发现（同一指标两个口径并列同名）**：胜率 metrics 口径 16.60%（分母 488 全部
   成交）与逐笔明细口径 33.47%（分母 242 平仓笔）并存同名「胜率」——分母错配，
   把 246 笔开仓笔当「未盈利」计入。确立：**胜率 = 已实现结果中盈利的比例，分母 =
   平仓笔（近似交易对，因买卖笔数近似 1:1）；开仓笔没有结果，不得进分母**；
   metrics 与明细必须归一为同一口径，`_win_rate` 的分母定义写进测试断言（计数
   口径冻结位），两个不同的数不得并列同名。
③ **确立（熔断恢复两条口径写进规格正文，不在代码里默会）**：
   - **恢复后峰值基准重置**：解除熔断时把回撤峰值基准重置为解除日权益——恢复后
     须再跌 `max_drawdown_pct_stop` 才二次熔断；不清基准会在解除当天被旧峰值再熔
     （即首轮 2022-02-25 起 4.7 年 175 笔连续拒单死锁的根因）。这直接决定熔断强度。
   - **企稳判据**：解除条件是「连续 N 个交易日权益未再创新低」——**「不创新低」
     接受持平**（弱于「连续上涨」；首轮 #1 即权益持平三天解除）。
   - **熔断状态禁止静默复位**：是否熔断/起始日/企稳天数随回测 result 与实盘状态
     文件落盘；实盘人工复位走 CLI 二次确认并留审计行，回测走自动恢复。

硬要求：`config.RISK.account` 显式登记 `halt_recover_stabilize_days`（默认 3）与
`halt_recover_enabled`（默认 True），作为熔断恢复参数的唯一权威来源；`core/risk.py`
读取之，模块默认仅作防御性 fallback。验收判据（实测背书）：① **键的存在性受哈希
守护**——从 `RISK.account` 移除两键 → 治理面哈希与元素计数立即变化
（实测 3de3377b…/759 → 91a67b37…/757）；② **键值变化由 config.py 版本控制 +
两机对拍守护**——cs-v1 `ignore_values=True` 只比结构不比取值（防业务值抖动污染
治理面，13.0.22 白名单纯净性同源逻辑），故「改值」不走哈希、走 git diff + 登记
对拍，这是设计语义不是漏洞；③ 同一 account.trades 下
`metrics.win_rate == 明细口径`（分母均为平仓笔）；④ 熔断解除日志必须带「企稳天数 /
新基准」两要素。

**一句话**：13.0.21~13.0.23 收的是「判据可复现、可比对、发布方产物钉死」；13.0.24
收的是**「守卫自身的参数与口径必须被守护」**——闸门逻辑正确但阈值在代码里、指标
有两个同名口径，等于守卫的输入端没人看着。**先让参数面和口径面入守护，再谈守卫强度。**


### 13.1 多数据源适配与故障切换 `data/source_adapter.py`

设计统一的数据源抽象基类 `BaseDataSource`：
```python
class BaseDataSource:
    def get_daily(self, symbol, start, end, adjust): ...
    def get_minute(self, symbol, period, start, end): ...
    def get_realtime(self, symbol): ...
    def get_symbol_list(self, market): ...
    def get_adj_factor(self, symbol, start, end): ...
    def get_index_members(self, index_code, date): ...
    def health_check(self) -> bool: ...
```

实现四个实现类：
- **`AkshareSource`**：默认主源（免费、覆盖全）
- **`BaostockSource`**：**免费备份源**（无需 token、无需注册）——A股日线 + 5/15/30/60 分钟**长历史**、1990 年起、官方明确 `volume`=股、支持复权（`adjustflag` 3/2/1）。作为 AKShare 的第一顺位免费备份，尤其适合 A股分钟线长历史。**注意边界**：仅盘后数据（无实时）、不覆盖指数/ETF/REITs/可转债/1分钟；这些仍回退新浪/东财。复权因子字段名为 `dividOperateDate`/`foreAdjustFactor`/`backAdjustFactor`（见 1.0 节六）。
- **`TushareSource`**：Tushare Pro 备用源（需要 token，数据稳定性高、字段规范）
- **`LocalSource`**：本地缓存/快照源（永远可用，作为最后兜底）

**数据源路由器 `DataRouter`**：
- 根据 `config.DATA_LONG_TERM.data_source_priority = ["akshare", "baostock", "tushare", "local"]` 顺序尝试（`baostock` 为免费备份，无需 token）
- 主源抛出异常/返回空/超时（>DATA_LONG_TERM.source_timeout_seconds=15）时，**自动切换到下一个源**，并记录告警日志"AKShare 拉取失败，已切换到 Tushare"
- 所有切换事件推送到告警渠道（让你知道某个源挂了）
- **health_check**：每天开盘前对所有已配置源做一次探活，结果写入 `data_cache/source_health.json`
- 对调用方完全透明：上层 `get_daily()` 调用的永远是 `DataRouter`，不关心底层走哪个源

### 13.2 原始价 + 复权因子分离存储（根治前复权缓存断裂）

**核心原则：永远不缓存"前复权价"，只缓存"不复权原始价 + 独立的复权因子表"，用到时才现算复权价。**

**为什么要这么做**：前复权价在每次除权除息后会**整体重算**，导致历史段和今天新拉的数据基准不一样，简单 `update_cache()` 追加就会拼接出看不见的断层。原始价和复权因子分离后，原始价永远不变，复权因子单独增量更新，每次读数据时用最新复权因子重算，永远不会断。

落地：
- `data_cache/raw/{market}/{symbol}.parquet`：存不复权 OHLCV（open/high/low/close/volume/amount）
- `data_cache/adj_factors/{market}/{symbol}.parquet`：存复权因子（date, adj_factor），每次增量更新
- 读取时：`df['close_qfq'] = df['close'] * adj_factor / latest_adj_factor`
- 增量更新逻辑：`update_cache()` 只拉**不复权日K线 + 复权因子**，两者都按日期去重合并
- **向后兼容**：旧的 qfq 缓存文件**禁止被读取**（`config.DATA_VERSIONING['legacy_qfq_cache'] = "forbid_read"`）——「启动时打印一次警告、提示用户删除」**不足以拦截**：raw 与 qfq 残留**同名、同格式、看不出区别**，读取器只能猜 → **复权两次或完全不复权 = 静默错价**。提供工具 `python tools/migrate_cache_to_raw.py` 自动迁移（需联网拉一次完整复权因子），迁移**原子 / 可续跑 / 可回滚 / 持维护锁**，详见 13.0.2
- **读取时先判口径**：每个 parquet 必须带 `price_basis`（`raw`/`qfq`/`hfq`/`nav`）与 `schema_version`；**读不到标记即报错**，不得按默认口径读
- **回测默认用后复权更精确**：`BACKTEST_DEFAULTS.adjust = "hfq"` 作为长期研究默认，回测区间内收益率连续可加，避免前复权跨除权日的收益率跳变

### 13.3 数据完整性校验 `data/integrity.py`

对每个缓存文件加完整性保护：
- 写入时计算 **SHA256** + 记录行数 + 起止日期 + 写入时间，存入 `data_cache/data_manifest.json`
- 读取时先校验哈希和行数，不匹配则标记为损坏并自动重新下载
- 写入采用"先写临时文件 `.tmp` → 校验通过 → 原子 rename"模式，防止写入一半程序崩溃产生半截文件
- **冷数据压缩归档**：超过 `cold_archive_days=30` 天未被读取的缓存文件，自动用 gzip 压缩存储（读取时自动解压），节省磁盘空间

### 13.4 数据版本快照 `data/snapshot.py`

**痛点**：财务数据会追溯修订、成分股会调整、复权因子会修正。没有版本管理，半年后你无法回答"上次那个回测是跑在哪版数据上的"，研究不可复现。

实现：
- 每次回测/优化/研究任务启动时，`SnapshotManager.create_snapshot(symbols, start, end, data_hash)`
- 把本次使用的**原始数据**完整复制一份到 `data_cache/snapshots/{snapshot_id}/*.parquet`
- 回测结果的 meta 里必须带 `data_version = snapshot_id`，报告里也展示
- 快照保留 `DATA_LONG_TERM.snapshot_retention_days`（默认 **2190 天**）——**必须 ≥ 引用它的最长报告保留期**（`retention_days_monthly` / `retention_days_backtest` = 2190），否则第 366 天起报告里的 `data_version` 成为**死引用**，「可复现」自带过期时间（见 13.0.4）
- 支持"按快照复现"：`python main.py backtest --from-snapshot <id>` 直接使用当时那份数据重跑

### 13.5 时点成分股（Point-in-Time）消除幸存者偏差 `data/pit_index.py`

**痛点**：直接用当前沪深300成分股回测2020年，等于提前知道哪些股票后来被选进了指数，收益被系统性高估。必须用**历史上每个调仓日真实的成分股名单**。

实现：
- 支持指数：沪深300(`000300`)、中证500(`000905`)、中证1000(`000852`)、中证2000(`932000`)、上证50(`000016`)、科创50(`000688`)、创业板50(`399673`)——**成分股/权重接口用裸代码；取指数行情则用带前缀（`sh000300` / `sz399673`）**，两者勿混
- 数据源：Tushare 的 `index_weight` 接口优先，AKShare 为辅；首次拉取全部历史成分股权重数据后，按调仓日（季调：3/6/9/12月第二个周五后第一个交易日）落地到 `data_cache/constituents/{index_code}.parquet`
- 统一API：`get_index_members(index_code, date)` 返回某日真实的成分股+权重列表
- **回测默认启用**：`FactorStrategy` 走沪深300/500股票池时，**自动按时点选股票**，不使用当前成分股
- 若数据源拉取失败：**默认 fail-closed（`on_unavailable="raise"`，直接报错）**——幸存者偏差会让回测收益**系统性高估**，是最该 fail-closed 的错误之一；只有**教学 / 演示**模式（`teaching_mode.allow`）可放行，且报告与索引必须带上**粘性水印** `survivorship_bias_uncontrolled`（随报告进归档库与 `stats`，不得被后续流程抹掉）。详见 13.0.6
- **因子计算的标的池同样走 PIT（v3.37 新增）**：`FactorStrategy` / 因子研究构建标的池时，必须走 `data/pit_index.py::get_index_members(index_code, date)`；`factor/universe.py` 的 `get_hs300/get_zz500/...` 降级为**必填 `date` 的薄封装**，`index_stock_cons*`（当前成分股）在回测 / 研究 / 因子路径**全面禁用**、静态清单回退**全面禁止**——否则**因子值本身**是用未来成分股算出来的，幸存者偏差从「选股 universe」之外的第二道门进来。详见 13.0.7

### 13.6 报告归档与索引 `reports/report_archive.py`

报告归档机制：
- **目录结构按年月归档**：`reports/daily/2026/10/xxx.html`、`reports/backtest/2026/10/xxx.html`、`reports/factor/...`，防止单目录文件数过多
- **报告索引 `reports/report_index.json`**：每份报告生成时追加一条记录
  ```json
  {
    "report_id": "bt_20261027_143052_abc123",
    "type": "backtest",
    "generated_at": "2026-10-27T14:30:52",
    "strategy_name": "ma_cross",
    "strategy_params": {"ma_short":5, "ma_long":20},
    "data_version": "snap_20261027_xxx",
    "data_range": ["2023-01-01", "2026-01-01"],
    "symbols": ["600519"],
    "market": "cn_stock",
    "metrics": {"annual_return":0.15, "sharpe":1.2, "max_drawdown":0.08},
    "file": "reports/backtest/2026/10/bt_...html"
  }
  ```
- **检索命令**：`python main.py report list --strategy ma_cross --year 2026`、`python main.py report show <report_id>` 直接打开对应报告
- **生命周期清理**：按 `REPORT_LONG_TERM.retention_days_*` 自动清理过期报告（日报保留1年、周报3年、月报/回测6年）
- **CLI 入口**：`python main.py report search "关键词"` 跨报告全文检索（先搜索引，再过滤）

### 13.7 结构化数据存储（让报告可统计、可复盘）

**痛点**：只存 HTML 意味着"看得见但算不了"——想把过去100份日报的每日盈亏拉出来画曲线做不到。

实现：
- 每份 HTML 报告**同时输出一份结构化数据文件**：
  - `{report_id}.json`：完整指标、持仓、交易明细（适合快速读）
  - `{report_id}_trades.parquet`：成交明细（适合大数据量回测）
  - `{report_id}_equity.parquet`：每日净值曲线
- 双文件关联：HTML 顶部自动展示"下载结构化数据"链接
- 统计命令：`python main.py stats equity --from 2026-01-01 --to 2026-10-27` 自动把该区间所有日报/回测的净值拼起来，画"全账户真实运行累计净值曲线"

### 13.8 离线可用的HTML（plotly资源本地化）

**痛点**：用 plotly 默认生成的 HTML 会从 CDN 加载 `plotly-latest.min.js`，断网/CDN 挂了/CDN 地址变更后图表全白。

实现：
- 在 `requirements.txt` 里加入 `plotly`，安装后 plotly 自带 `plotly.min.js` 本地副本
- `reporter.py` 生成 HTML 时，使用 `plotly.io.to_html(include_plotlyjs='inline')` 把 plotly.js **内联进 HTML**（文件会增大约 3MB，但单文件完全自包含）
- 所有 CSS 样式也内联（本来就已经这么做）
- **结果**：一份 HTML 可以被拷贝到任何机器、任何时候、无网络情况下打开，图表全部正常显示

### 13.9 长期运行的磁盘与缓存治理

- **缓存容量监控**：`tools/cache_usage.py` 统计 `data_cache/` 各子目录大小，超过 `DATA_LONG_TERM.cache_max_gb=20`（默认 20GB，可改）时按 LRU 清理最冷数据——**默认 `dry_run`，必须显式 `--apply` 才真删**；删除前查引用；命中 `config.CACHE_GOVERNANCE['protected_paths'/'protected_globs']` 即 `skip_and_warn`（**复权因子、完整性基准、快照、PIT 成分股、幂等键、急停态、审计链一律不可删**）。「越冷越该删」与「越冷越重要」在这里直接冲突，且删除**不报错**
- **日志轮转**：`logs/` 使用 `RotatingFileHandler`，单个文件最大 50MB，保留最近 20 个备份
- **审计日志归档**：`audit_logs/` 按月分文件，超过 2 年自动压缩归档
- **实盘运行数据**：`live_trading/` 每月初压缩上月数据为 zip，保留近 3 个月明细——**但 `order_ids.json`（幂等键）与 `kill_switch.json`（急停态）永不清理**（`CACHE_GOVERNANCE['protected_paths']`）；否则「3 个月后重启 → 幂等键已被清 → 去重失效 → **重复下单**」，等于删掉了第 12 步 K3 的全部意义（「跨重启保留」）
- **启动自检**：磁盘剩余空间 < 5GB 时告警，< 1GB 时拒绝启动（防止盘写满崩溃）

### 13.10 报告与数据元数据强校验

生成每份报告前强制校验 `REPORT_LONG_TERM.meta_required_fields` 全部非空：
- 没有 `data_version` 不允许生成（防止回测没绑快照）
- 没有 `strategy_params` 不允许生成（防止参数不知道是什么）
- 没有 `data_range/symbols/market` 不允许生成
- 校验失败直接抛异常中断，不允许生成"不可复现的报告"

### 13.11 测试用例

创建 `tests/test_long_term.py`：
1. 数据源切换测试：mock AKShare 抛异常，验证自动切到 Tushare/local
2. 前复权重算测试：写入一段已知原始价+复权因子，验证现算qfq价格正确，增量更新后拼接不出现断层
3. 完整性校验测试：故意损坏缓存文件，验证能检测并自动修复
4. 快照复现测试：做一次回测后，故意修改原始数据，用 snapshot 重跑结果应完全一致
5. 时点成分股测试：验证某个历史日期的成分股不含后来才加入的股票
6. 报告元数据测试：缺字段时生成报告必须抛异常
7. HTML离线测试：生成的HTML文件不包含任何外部CDN引用（用正则检查 `<script src="http`）

### 13.12 配套CLI命令

```bash
python tools/health_check.py           # 所有数据源健康检查
python tools/migrate_cache_to_raw.py   # 旧qfq缓存迁移为原始价+复权因子
python tools/cache_usage.py            # 缓存容量统计与清理建议
python tools/verify_cache.py           # 全量缓存完整性校验
python tools/build_pit_index.py        # 构建/更新时点成分股库
python main.py report list --type backtest --year 2026
python main.py report show <report_id>
python main.py stats equity --from 2026-01-01
```

### 13.13 收尾总检（v3.32 新增·全系统一致性验收）

**为什么放在这里**：这是最后一步，之后**没有新步骤来补闸门**。收尾总检是整个项目**唯一一次**能机器验证「所有闸门都真的在生效路径上」的机会；不做这一步，「三年后还能跑」就只是一句愿望。

要验的三件事：

**A. 闸门是单份实现，六个入口都只调用不重写**（`config.SYSTEM_CONFORMANCE`）
- 全仓检查：`warmup_ok` / `data_asof_date` / `price_adjust` 三个物化列的**判定逻辑**只允许出现在 `core/signal_gate.py`，其他文件只允许**读取与传递**。
- 逐个确认 `runner` / `backtester` / `paper_trader` / `live_trader` / `monitor` / `notifier` 调用的是同一份闸门。
- **验收**：把 `core/signal_gate.py` 里某条规则临时改成「恒拒」，六个入口在「预热期 + `fillna(0)`」帧上**必须全部零成交**——只要还有一个能成交，那条路径就是被绕过的。

**B. 每个出口都过闸门**（六出口 × 表驱动）
- `place_order` / `monitor_push` / `report_plan` / `investor_disclosure` / `live_order_submit` / `watch_only_live_push`，逐个构造「闸门判定为不合格」的输入，验证**每个出口都拒绝**。
- 补一个**负例测试**：故意给 `place_order` 传一张**看起来正常、但缺物化列**的帧，必须**报错**而不是放行。

**C. 没有残留的旁路开关**
- 全仓检查 `skip_` / `bypass` / `force_` / `disable_gate` / `no_check` / `_test_mode` 一类命名，逐个确认**不存在**能关掉闸门的开关（含「结构性校验」形式）。
- `RUN_MODE` 只允许**降级**：构造 `paper → live` 的提升请求，必须被拒。

**测试文件**：`tests/test_system_conformance.py`，**表驱动**（出口 × 是否过闸门，逐格断言），禁止写成整体冒烟。

**收尾报告要求**（本项目历轮最大的流程缺陷就是「报告只报总数、不报漏项」）：
- 给**四类计数**：通过 / 失败 / 跳过 / 收集错误。
- 给**「测项 → 守卫」映射表**：每一项测的是哪一条闸门（例：`test_live_gate::test_stale_blocked → LIVE_SAFETY/must_call_gate`），**禁止只报 `N passed`**。
- 给**未覆盖清单**：明确写出「哪条闸门本轮没有独立测试」，不许用「既有问题、与本步无关」豁免。

### 13.14 规格自校验闸门：装在开发期，不装在运行期（v3.35 新增）

**为什么单列一节**：`check-config`（`core/spec_check.py`）是本项目第一个**元闸门**——它守的不是数据、不是订单，而是**规格与代码是否同版本**，正对本会话贯穿始终的病根：**连「规格」本身也活在一个会失灵的副本上**。但正因为它守的是规格，装错位置会**自锁**。

**A. 三种装法，只有一种对**

| 装法 | 后果 |
|---|---|
| 接进 `main()` 首行、对**所有**模式 `raise` | ❌ **自锁**：stale spec 存在时，连 `check-config`（修它的命令）、`report show`、`backtest` 都跑不起来——**闸门锁死了修它的工具** |
| 完全不接，只留手动 `check-config` | ⚠️ 退回「提醒 ≠ 拦截」：没人记着跑 = 等于没有 |
| **分模式**：`live`/`paper` 硬拦，其余只警告 | ✅ 唯一正确——**钱路径 fail-closed，研究路径 fail-loud 但可跑** |

**B. 硬要求**
- `enforce_on_startup` 只对 `RUN_MODE in ("live","paper")` **`raise`**；`backtest`/`research` **放行 + 报告 meta 打粘性水印 `spec_version_mismatch`**；`tooling`（含 `check-config` 自身）**只警告，永不失败**。
- **`self_lockout_guard`**：`spec_check` 与 `check-config` **在版本不符时也必须能运行**——它是用来诊断和修复的，不是被诊断对象。
- **版本号是字符串 = fail-open**：`must_contain_markers` 必须校验规格正文存在锚点段落（`13.0 开工前置` / `13.13 收尾总检`）；否则「把版本号字符串一改」就能骗过闸门——这正是本会话所有「易失载体」的通病在元层复现。

**C. 验收判据**
- 把指令集版本头改成 `v0.0` → `live`/`paper` 启动**报错**；`check-config` **仍能运行**（返回非 0 但不崩）；`backtest` 能跑但报告带 `spec_version_mismatch` 水印。
- 版本号保持 `v3.37` 不变、但删掉 `13.0 开工前置` 标题 → 校验必须**警告 / 不通过**（证明验的是内容，不是字符串）。

**D. 本地副本对齐（第 13 步开工前必做）**
- 本地 `…-2.md` 目前 **v3.3 / 2010 行 / 无版本头**，而代码已实现到 v3.22+（`signal_gate` / `warmup_ok` / 物化列 / 幂等）——**规格与代码已错位 12 轮**。
- 对齐动作：① 第 3 行插入 `<!-- spec_version: v3.37 -->`；② 「第 13 步」标题后插入 **13.0**，13.12 之后插入 **13.13 / 13.14**；③ `config.SPEC_VERSION` 同步为 `v3.37`；④ `python main.py check-config` 须返回 `[通过]`。

---

## 🎯 搭好后的进阶建议

### 零售层（先把这套跑通，是基础）
1. **先跑通最简单的双均线策略**，把整个流程（取数→回测→看结果→模拟盘）走通，不要一上来就写复杂策略。
2. **每个市场至少模拟盘跑3个月**，稳定盈利了再考虑实盘，不要急。
3. **免费数据仅供学习**：AKShare有延迟、接口经常改版、历史数据可能有复权错误，实盘一定要换付费数据源（聚宽/Tushare Pro/Wind/iFinD）。
4. **杠杆品种风险极高**：期货/外汇/期权建议先用1-2倍杠杆练手，不要上来就10倍20倍，爆仓只需要一次极端行情。
5. **合规第一**：外汇保证金、加密货币、国际期货在中国大陆均无合规个人实盘交易渠道，这些模块仅用于回测学习和策略研究，请勿用于非法实盘。

### 合格投资者层（等零售层跑稳了再碰）
6. **私募/资管/信托净值回测的核心不是择时，是资产配置**：这类产品流动性差、不能频繁交易，重点是做风险分散和大类资产配置，而不是短线买卖。
7. **新三板回测最大的坑是幸存者偏差**：必须把已经退市/摘牌的品种也纳入回测，否则结果会严重高估收益。实盘参与前务必先用极小仓位试水。
8. **公募REITs的核心是分派率和折溢价**：不是炒价差，而是赚稳定分红+折价回归的钱。注意底层资产运营风险（高速车流下滑、产业园空置率上升等）。
9. **场外衍生品模块只用来学定价，别想着实盘**：雪球这类产品看起来票息高，实际上是"赚有限利息、亏无限本金"的结构，搞懂敲入敲出逻辑再判断要不要买，不要只看销售给你展示的"大概率赚钱"那部分。
10. **合格投资者门槛不代表产品更安全**：100万起投的产品亏起来不比股票温柔，甚至更不透明、流动性更差。看懂合同、搞清底层资产再出手。

### 永远记住
11. **策略迭代**：回测赚钱不代表实盘赚钱，永远保留怀疑，做好风控，永远不满仓，永远加止损。
12. **不懂的品种不要碰**：系统覆盖18类品种不代表你每个都要做，先把自己最懂的1-2个市场做深做透，比分散在十几个市场上半懂不懂强得多。

搭的过程中任何一步Trae生成的代码有问题、跑不通，把错误信息贴回来，我帮你改提示词或者直接修复。祝搭建顺利！
