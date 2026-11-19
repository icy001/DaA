# 多市场量化交易系统（v3.19）

> 全市场量化交易系统 · 19 类金融产品（含指数）· 行情 → K线/缠论 → 指标 → 策略 → 因子研究 → 回测 → 模拟盘 → 实盘接入 → 复盘

## 搭建进度看板

| 步骤 | 名称 | 状态 | 完成时间 | 备注 |
|:---:|:---|:---:|:---|:---|
| 0 | 环境与项目骨架 | ✅ 已完成 | 2026-10-27 16:45 | test_env.py 58 项全过；已修正深市个股/场外基金号段误判；已补丁 get_market_config、3字母代码默认 us_stock、全依赖已安装 |
| 1 | 统一数据层 | ✅ 已完成 | 2026-10-28 23:10 | core/data_fetcher.py（19 类市场路由 + 质量检查 + CSV/parquet 缓存 + 港股/期货/期权/基金特殊处理）。**单位三重实测**：东财系历史接口（`stock_zh_a_hist`/`fund_etf_hist_em`/`reits_hist_em`）=手×100，新浪系（`stock_zh_a_daily`/`fund_etf_hist_sina`）=股/份不换算，BaoStock=股不换算，统一写入 `config.DATA_SOURCE_UNITS` 并由 `INTERFACE_UNITS` 派生。**分钟线**：接入 BaoStock（5/15/30/60 分钟、1990 年起、不复权+独立复权因子）作为 A股长历史源，新浪/东财补近期与当日，落自建增量库 `data_cache/minute/{market}_{symbol}_{period}.parquet`（读库→补末尾+中段缺口→去重升序→质量检查→写回，attrs 含 `available_from`/`minute_history_capped`/`source`/`adjust`/`gap_count`/`gap_dates`/`daily_gap_dates`）。实测 600519 60 分钟 3 年 2904 行（新浪上限 1970），3 年 gap_count=0。A股日线与分钟统一 BaoStock 因子源（实测 15:00 分钟 qfq 与日线 qfq 误差 0.00000%）；9/725 日 >0.1%（最大 0.2535%）已定性为 BaoStock 分钟缺尾盘集合竞价的数据源噪声，非复权 bug。交易日历双重校验（日线索引 + 节假日日历）；BaoStock 会话失效自动重登。逆回购 204001 加历史重试+快照备用源；`config.AMBIGUOUS_CODES` 拦截 ZN/GC 歧义代码。test_data.py 15 标的 + 15 项核查全通过；已知限制见下文小节 |
| 2 | 行情批量下载导出+K线图绘制（含多周期/形态/缠论/多标的对比） | ✅ 已完成 | 2026-10-28 16:20 | `tools/data_export.py`（下载/断点续传/CSV+parquet+Excel/概览/增量/自选池/CLI）、`core/chart.py`（中文字体探测、K线+MA+布林+成交量+买卖点、指标副图、归一化对比、4 标的并排网格、回测复盘、plotly 交互式）、`core/pattern_annotate.py`（均线金叉死叉 / MACD 背离 / 突破，默认只开 ma_cross）、`core/chan.py`（包含合并→分型→笔→线段→中枢→买卖点 + 多级别 + 绘图）；`get_kline()` 按周期路由、`re_sample_kline()` 周/月聚合（末根未走完标 `last_bar_incomplete`）。**收尾**：接入指数市场 `cn_index`（市场 18→19，`SH/SZ`+6 位前缀识别，日线东财→新浪→BaoStock、分钟东财→新浪并标 `minute_history_capped`，`tradeable=False`）；缠论一/二/三类买卖点全部产出（6 年日线 B1×16/B2×11/B3×2/S1×18/S2×11/S3×1）；基准改回真实指数 `sh000300`（失败才回退 510300 ETF 并 WARNING）。**2026-10-30 关闭**：新增 `SOURCE_AVAILABILITY`/`SINGLE_SOURCE_MARKETS`/`CN_INDEX_UNIT_VERIFIED`；单点市场（forex/cn_fund/cn_reverse_repo 日线、cn_convertible/us_stock/us_etf/hk_stock → 失败一律显式报错，有备源市场正常回退；`tools/source_status.py` 加入 5s 超时 + 缓存 + 延迟输出。**stale 收敛（实盘安全）**：以「交易日数差」判定 `stale_days`，超过 `config.STALE_LIMIT`（日线 5 / 分钟 2）直接报错，`for_trading=True` 一律拒绝过期数据。**本轮加固**：双重防线（paper/live 按 `RUN_MODE` 强制拦截，不依赖传参）+ `assert_fresh_for_trading()` 下单前独立复核 + 市场时钟逐市场 + backtest 豁免。**后续修正**：时效物化为 `data_asof_date` 普通列（穿透 rolling/ewm），复核优先读列、其次 refetch，仅「无列且无法重取」才 fail-closed。测试：test_chart 19/19、test_pattern 14/14、test_chan 32/32、test_export 11/11、test_env 75/75 |
| 3 | 技术指标计算 | ✅ 已完成 | 2026-10-30 23:20 | `core/indicators.py` + `test_indicators.py`（80 项全过）。8 组指标：均线 MA/EMA/SMA/MACD/BOLL；动量 RSI/KDJ/ROC/CCI/WILLR；量能 VOL_MA/OBV/VR；波动率 ATR/STD/HIST_VOL；趋势 ADX/SAR；期权 BS+IV+希腊字母+IV_RANK/PERCENTILE；净值 `eval_` 评估类；期货 BASIS/BASIS_RATE/ROLL_YIELD。三条硬约定：**复权口径**（ATR/STD/HIST_VOL 口径不明即报错）、**量能只用 volume**、**年化基数一律读 config**。**守卫加固**：`price_adjust` 物化列优先于易失 attrs（fail-closed，口径丢失直接报错）、`required_bars()` 预热期前 N-1 根置 NaN、评估类 `eval_` 前缀物理隔离、`assert_indicator_usable` 的 market 必填、成交量全 0 返回 NaN 并标注、希腊字母单位写死并逐值核对。**收尾补漏（B1–B5 + 两个常量）**：`warmup_ok` 物化布尔列 + `assert_signal_frame()` 信号入口（预热期被 fillna/ffill 直接报错）、`required_bars()` 改由长样本扰动反推（EMA=38 / MACD=135 / RSI=126 / ADX=155，表值 20/35 只作下界）、`price_adjust` 多标的按 symbol 分组填（混合口径 fail-closed）、期权 IV 无解返回 NaN + `iv_solved=False`、paper/live 末根仍在预热期拒绝出信号 |
| 4 | 统一账户与订单管理 | ✅ 已完成 | 2026-10-30 23:20 | `core/account.py` + `test_account.py`（49 项全过）。一个 `TradingAccount` 覆盖 6 种模式：股票现货（T+1 冻结 / 可转债 T+0）、期货保证金（国内品种级参数 + 国际期货、平今费率）、外汇杠杆、期权买卖方（卖方冻结保证金）、基金申赎（按持有天数递减赎回费）、国债逆回购（到期本息回款）。`place_order` 校验链：方向/类型 → 市场可交易（cn_index 与净值型市场拒单）→ 做空权限 → 整手/数量 → T+1 可用 → 涨跌停 → **数据时效闸门（stale v2 独立 refetch，不依赖传入帧）** → 资金/保证金 → 入账。市场规则一律 `config.get_market_config()`。`calc_commission` 覆盖 A股/美股/港股（ETF 免印花税）/期货（平今）/期权/加密 maker-taker/基金/逆回购。**预热闸门联动**：开仓必须携带 `warmup_ok=True`（False 或裸单拒单），平仓/减仓不受限（开严平宽） |
| 5 | 策略基类+因子研究+公开策略接入+自定义因子 | ✅ 已完成 | 2026-10-31 00:45 | `core/strategy.py`（`BaseStrategy`）+ `core/runner.py`（四环境执行器）+ `core/strategy_loader.py` + `research/{optimizer,walkforward,validator,registry}.py` + `factor/` 全模块 + 9 个示例策略 + 10 个 yaml + 3 个工具脚本。**5.0 双闸门落在信号入口**：执行器逐 bar 注入 `warmup_ok` 物化字段，`buy()/short()` 内部校验 False 即拒单（`sell()/cover()` 放行）；策略自拼指标帧必须过 `assert_signal_frame()`（预热期被 fillna/ffill 直接报错）；`get_history(n < required_bars)` 抛错；paper/live 末根预热不出信号。**5.1 基类**：`init/on_bar/on_tick/on_end_of_day` + `buy/sell/short/cover/get_position/get_history` + 内置风控（单标的 30%、品种总杠杆、逐仓止损止盈、黑名单）。**5.2 四环境**：`StrategyRunner` 以同一策略类跑通 backtest/optimize/paper/live_sim。**5.3 loader**：坏文件（语法错/缺 on_bar/非法周期/重名）隔离进 `unavailable` 不崩溃。**5.4–5.8**：yaml 参数化、五模板脚手架、16 项上线清单、参数平原、走向前 70/30、稳健性评分卡、JSON 实验记录。**5.9 因子**：表达式引擎 + Alpha101/191（101+191 条）+ 预处理/评估/合成/未来函数检测 + `FactorStrategy`。测试：test_strategy 18/18、test_loader 20/20、test_research 19/19、test_factor 58/58、test_alpha101 10/10、test_custom_factor 12/12、test_factor_strategy 14/14 |
| 6 | 全市场回测引擎 | ✅ 已完成 | 2026-11-05 10:18 | `core/backtester.py` + `tests/test_backtest.py`（28/28）。**6.0 闸门随引擎迁移**：逐日 `signal_gate.build_bar_dict()` 写 `warmup_ok`（缺列报错），开仓过 `place_order` 预热闸门、平仓豁免，长度门槛 `max(60, required_bars())`，多标的对齐逐标的保留三个物化列；引擎一致性测试（runner vs Backtester 拒绝边界一致）。**主体**：`prepare`（列校验→未来函数检测→交集对齐→流动性扫描→基准）→ `run()` 逐 K（`build_bar_dict`→`execution.set_context`→`dispatch_bar`→爆仓统计→日终市值/杠杆/保证金快照）→ 收盘强平 → `BacktestResult`。**写实成交**：滑点、开盘涨停买不进/跌停卖不出、单笔 ≤ 当日量 1%（截断/拒单）、限价按高低区间、T+1 由账户执行、`config` 真实费率（实测 A股买 31.29 / 卖 94.76 含印花税）。**指标**：收益/回撤/风险/风险调整/交易/杠杆六类 + `by_market`/`by_direction` + `margin_calls`（爆仓）。**陷阱检测**：未来函数/幸存者偏差/过拟合/流动性/滑点。**实测**：双均线 600519（784 bars、16 笔、+20.33%）、海龟 RB2510（18 笔多空、保证金 5180.01）、基金定投 161725（183 笔）、预热期 125 次拒单首仓第 126 根 bar |
| 7 | 模拟盘交易 | ✅ 已完成 | 2026-11-05 13:30 | `core/paper_trader.py` + `test_paper_trade.py`（31/31）。**闸门有源**：每根 bar 走 `signal_gate.build_bar_dict` 写 `warmup_ok`（缺列报错），开仓过 `place_order` 预热闸门、平仓豁免，末根预热不出信号；**成交同源**：挂单/条件单最终仍进 `TradingAccount.place_order`，滑点 = `EXECUTION_MODEL.slippage_base_pct × slippage_multiplier["paper"](2.0)`，涨跌停/量限（按市场分档）/手续费/T+1 与回测完全一致；**风控同源** `core/risk.py`（`config.RISK` 唯一参数源）。`run_daily(at, last_n_bars)` / `run_intraday(interval_minutes, at, last_n_bars)` 复用回测主循环，`last_n_bars` 只交易最近 N 根（更早历史仅预热，`_initial_seen` 播种已见 bar、长度门槛仍按全量历史判定），非交易日 `is_trading_day` 直接跳过。订单管理：挂/撤/改 + 止损/止盈/移动止损条件单（触发后走 `place_order`）+ `rebalance` 一篮子调仓（按 delta 先卖后买）+ 当日未成交收盘自动撤销（gtc/条件单保留）。记录与对账：逐笔成交日志、每日账单 `self.bills`（权益/现金/持仓/成交/费用）、`reconcile(cash, positions)` 手动对账留档。偏差分析 `compare_with_backtest(reference=None, warn_pct=None)` 读 `ENGINE_CONFORMANCE["divergence_warn_pct"]=0.05`，超阈值 WARNING 并给出滑点/成交笔数/已知简化归因（实测同滑点偏差 0.00e+00，2 倍滑点 -0.1738%）。账户持久化 `data_cache/paper_account.json`（持仓/资金/挂单）。`Backtester` 仅新增引擎中性钩子 `_initial_seen` / `_bar_count_for_gate` / `_after_bar`。**E1（2026-11-12）**：撮合价基准参数化 `EXECUTION_MODEL["match_price_basis"]`（默认 `next_open`），策略当根返回 `pending`、下一根成交；`assert_fill_after_signal` 强制「成交 bar 严格晚于决策 bar」，`same_*` 同根成交抛 `LookaheadError`（test_match_price_basis 18/18） |
| 8 | 定时盯盘与消息推送 | ✅ 已完成 | 2026-11-12 13:37 | `core/monitor.py` + `core/notifier.py` + `tests/test_monitor.py`（pytest 16/16）。**8.0 第二个信号出口**：信号出口收口为 `place_order` 与 `monitor_push`；Monitor 用 `signal_gate.build_bar` 构建 bar，`signal_gate.assert_tick_bars`（唯一实现，monitor/strategy 只调用）校验 `warmup_ok / data_asof_date / price_adjust` 三物化列，缺列/NaN 直接报错，禁止裸行情喂 `on_tick`。**闸门只调用不重写**：开仓走 `signal_gate.check_order`（开严平宽，预热期开仓不推、平仓/减仓/风控提醒放行），时效走 `data_fetcher.assert_fresh_for_trading`（refetch 同源），停更/超限只推「数据异常」且不喂策略。**逐市场时段**：`is_in_session` = 市场 tz + `utils.is_trading_day` + `config.get_market_config` 的 `trading_hours`（含夜盘），美股 DST 自动、加密/外汇 always。**推送标注**：预热闸门 / 数据截至 / 新鲜度。**notifier**：Console/Log/企业微信/钉钉/邮件/Bark 统一 `send()`，10 分钟去重 + 5 条/分钟限流。**monitor**：`MONITOR_EVENTS` 事件清单、±5%/新高新低/量能 2 倍/止损止盈/逆回购、连续 5 次失败熔断 10 分钟防封 IP、APScheduler 多市场调度、Ctrl+C 优雅退出保存账户、nohup/pm2/systemd 后台常驻 |
| 9 | 自动复盘报告 | ✅ 已完成 | 2026-11-12 14:35 | `core/reporter.py` + `templates/`（base/daily/period/backtest/_macros）+ `tests/test_reporter.py`（pytest 15/15）。**9.0 报告=第三个信号出口**：`signal_egress_points` 三出口 + `REPORT_CONFORMANCE`；报告同源读 `account.trades / rejected_orders / bills / signal_gate` 裁决日志，按 `reject_id` 去重披露六类拦截，0 笔拆解为「策略无信号 + 闸门拦截 N 笔」；候选走 `check_plan_candidate`，预热/停更/非时段默认排除并标「仅供观察」+ 数据截至日期；绩效复用引擎 `calc_metrics`；自动发送前过时效闸门。**日报**：账户概览、持仓（含当日涨跌）、当日交易、分市场盈亏、风控检查、信号汇总、明日候选/关注事件、市场情绪。**周报/月报**：权益曲线、月度热力图、盈亏分布、极值交易复盘、参数评估。**回测专项**：策略参数、全部绩效、净值/回撤/热力图、分年度收益、交易明细 + CSV 下载、改进建议。**格式**：Jinja2 单文件 HTML（CSS 内联）、plotly 交互图（缺失降级 matplotlib）、PDF 可选（缺 wkhtmltopdf 跳过）。顺带修复 `backtester._trade_stats` 缺列时 `to_numeric(标量).fillna` 崩溃 |
| 10 | 合格投资者层净值回测+衍生品定价 | ✅ 已完成 | 2026-11-12 15:15 | `core/qualified_investor.py` + `data/fetcher_nav.py` + `nav_backtest/`（`nav_backtester.py` / `fof.py` / `strategies/`）+ `derivatives_pricing/`（`pricing.py` / `snowball.py` / `trs.py` / `scenario.py`）+ `core/qi_monitor.py` + `templates/qi.html`，测试 5 套 **75 项**。**10.1 QIChecker**：subscribe/transfer/additional_subscribe/nominee_change 逐动作重校验，非法人载体穿透到最终投资者并合并人数，禁拼单/代持/拆分/借名，`on_fail=reject` 抛 `QualifiedInvestorRejected`，通过/拒绝均写 JSONL 审计（写失败 fail-closed），三套门槛不混用（私募 300 万 / 资管 500 万且起投 30/40/100 万 / 信托未配机构门槛即拒），2026 规则区分「已发布待施行」与「征求意见稿」。**10.2 净值数据层**：频率按披露间隔中位数判定，每帧写 `frequency` / `disclosure_lag_days`；空表/缺列/净值全无效抛 `NavDataUnavailableError`；唯一出网出口 `_call_source`（≥0.3s + 重试 + 来源标识）；缓存名 `{market}_{code}[_{freq}].csv`；私募/资管无公开净值时走 `manual_nav_import`，禁止静默空表；REITs 折溢价缺失置 NaN 并标 `premium_missing`，新三板过滤零成交并标退市风险。**10.3 三层净值 + FOF**：`product_gross → product_net → investor_net`，carry 逐投资者高水位（不同申购时点不同 HWM），披露固定 `investor_net` 并与业绩报酬明细对账；开放日=净值披露日、锁定期（私募/信托 180 天、资管 90 天）、赎回 T+3 到账；FOF 决策帧按 `day - lag` 截断、下一净值日执行、先卖后买、锁定期内卖出记 `sell_blocked_lockup`、在途赎回款不可再投资；`decision_date >= nav_date + lag` 违反抛 `DisclosureLagError`，净值禁转 K 线。**10.4 场外衍生品**：BS / 蒙特卡洛 / CRR 二叉树、雪球敲入敲出、TRS 保证金与强平、情景分析与 VaR；`LIVE_TRADING_FORBIDDEN=True`、`ORDER_CHANNELS=()`、导入即打印「个人禁止实盘」红色警告、不导出任何下单通道。**10.5 提醒与披露**：8 类提醒全部登记 `SIGNAL_EGRESS_CONFORMANCE["alert_types"]`（未登记拒发），`qi_threshold_check` 只提醒、后续申购仍被动作闸门拒绝；`generate_qi_report()` + `qi.html` 作为第四个出口：固定 investor_net、五类费用、业绩报酬计提明细、FOF 权重/锁定期、REITs/新三板/衍生品模拟页（声明不下单不出实盘信号）、被抑信号、QI 审计、完整区间、禁保本/保收益/零风险。实测 pytest tests **149 passed / 0 failed / 0 skipped / 0 收集错误**，根目录 9 套脚本测试无回归 |
| 11 | 一键运行入口+README+测试框架 | ✅ 已完成 | 2026-11-12 17:05 | **薄入口（78 行）+ `cli_commands/` 八模块**：`main.py` 只做「顶层 argparse 注册 / `core/cli_gate` 控制平面校验 / 按 handler 分发」，全部业务在 `cli_commands/{retail,research,checklist,factor,data,qi,derivatives}.py`（每文件 ≤300 行，暴露 `add_subparser(sp)` + `handler(args)`）；`CLI_CONFORMANCE` 新增 `thin_entry / max_entry_lines / command_modules_dir / mode_may_only_downgrade` 四键。**11.0 控制平面**：① 旁路开关黑名单 13 个旗标（`--no-gate/--no-risk/--force/--skip-check/--skip-freshness/--ignore-warmup/--disable-gate/--force-live/--force-trade/--bypass-gate/--no-fresh/--ignore-stale/--ignore-risk`，含 `--flag=value` 变体）在 argv 层抛 `BypassFlagError`，`assert_no_bypass_registration` 审计 argparse 注册面；② RUN_MODE 阶梯只允许降级，提升需「上线清单无 FAIL + `--confirm`」双门禁；③ 子命令默认值全部经 `cli_gate.cli_default()` 取 `config.CLI_CONFORMANCE['cli_defaults']`。**--data 数据层出口**：`--data/--csv/--from-file` 三别名统一到 `data/data_import`，三物化列（`warmup_ok` / `data_asof_date` / `price_adjust`）缺列或 NaN 一律 fail-closed。**24 个子命令**全部 `--help` 通过；`tests/test_entry.py` **54 项**锁定「无旁路开关 / 模式不可提升 / 默认值同源 / --data 三物化列齐备 / 薄入口行数上限 / checklist 四类计数」 |
| 12 | 实盘接入层（QMT/PTrade/CTP+风控+守护+对账+告警+凭证安全） | ✅ 已完成 | 2026-11-13 09:50 | `broker/`：抽象基类 + QMT（mini/standard/simulation）/PTrade/CTP 三适配器，SimNow 预设、`PenetrationTestHelper` 穿透参数自检、价格笼子/T+1/保证金/平今费/涨跌停原语，SDK 只在 `broker/` 内惰性导入。`data/live_data.py`：回测走缓存、仿真/实盘强制官方行情源（无 broker 直接 `SilentFallbackError`）、断线有限次重连。`risk/risk_manager.py`：账户级/订单级/合规级三层，报单前先过风控。`live/`：执行器生命周期、守护（盘前检查/心跳/结算对账/优雅退出）、多渠道告警（严重告警 3 次重试）、审计日志（按日 JSONL + 哈希链，保留 2 年）、`PanicController` 六步急停。`run_live.py` 启动入口 + `tools/live_checklist.py` 15 项检查。`core/logger.py` 日志脱敏（密钥前 3 位、资金账号后 4 位）。测试 test_broker/test_live_checklist/test_credentials/test_idempotency/test_reconcile/test_live_gate/test_kill_switch_persist 全绿；全量 870 项（pytest 287 + 脚本 583）通过/失败/跳过/收集错误 = 870/0/0/0 |
| 13 | 数据与报告长期可用性（多源/原始价/快照/时点成分股/归档） | ⬜ 未开始 | - | - |

**下一步**：第 13 步「数据与报告长期可用性（多源/原始价/快照/时点成分股/归档）」（`next_step=13`）——第 12 步 **已完成**（`progress.json` v3.19）：`broker/` 抽象基类 + QMT/PTrade/CTP 三适配器（SimNow 预设 + 穿透测试辅助）、`data/live_data.py` 三模式行情、`risk/risk_manager.py` 三层风控、`live/` 执行器/守护/告警/审计/急停、`run_live.py` 启动入口、`tools/live_checklist.py` 15 项检查、凭证与日志脱敏；全量 870 项测试（pytest 287 + 脚本 583）0 失败 / 0 跳过 / 0 收集错误。本轮同时修复日线缓存「盘中残缺末根永不重取」与复权因子短窗口 reindex 全 NaN 两个数据层缺陷。第 11 步已交付 `main.py` 78 行薄入口与 `cli_commands/` 八个命令模块（`tests/test_entry.py` 59 项锁定控制平面）。从《Trae多市场量化系统搭建指令集》复制 `===== 第 13 步：...=====` 整段指令继续。第 10 步已交付：10.1 逐动作合格投资者闸门、10.2 净值数据层、10.3 三层净值 + FOF、10.4 场外衍生品定价（个人禁止实盘红线）、10.5 盯盘提醒登记与第四出口 `investor_disclosure`，5 套测试 75 项通过。第 9 步已交付 `core/reporter.py` + `templates/` 与 `tests/test_reporter.py`（15/15），报告作为第三个信号出口：同源、拦截披露、0 笔拆解、候选过闸门与时效、绩效同源、发送过时效。第 8 步已交付 `core/monitor.py` + `core/notifier.py` + `tests/test_monitor.py`（16/16），盯盘作为第二个信号出口接入 `SIGNAL_EGRESS_CONFORMANCE`。第 7 步已把三引擎统一到 `core/signal_gate.py`（闸门）、`core/execution.py`（成交）、`core/risk.py`（风控）三个唯一实现。策略侧接口不变——同一策略类零改动即可在回测/模拟盘/实盘仿真间切换；策略文件仍只允许出现 `buy/sell/short/cover/get_position/get_history/params`。

## 中断恢复流程（重要）

1. 重新打开项目后，先运行：

   ```bash
   python check_progress.py
   ```

   看板会显示每一步状态、整体完成百分比，以及"下一步建议"（提示复制哪一段指令）。
2. 按提示从指令集复制对应整段的 `===== 第 N 步：... =====` 继续搭建。
3. 每一步完成后，Trae 会同步更新 `progress.json` 与本文档的进度看板；若出现未解决的报错/警告，该步骤会标记为「有问题」，并在 `note` 与 `issues` 中写明原因和处理方式。

## 项目介绍

- 目标：一套个人可用的多市场量化交易系统，覆盖零售层 13 类与合格投资者层 5 类品种。
- 零售层：A股个股/ETF、美股个股/ETF、港股、可转债、国内期货、国际期货、外汇、场内期权、加密货币、场外公募基金、国债逆回购。
- 合格投资者层：私募证券基金、券商资管/信托/私募理财、新三板、公募REITs、场外衍生品定价模拟（仅学习，个人禁止实盘）。
- 全链路：统一数据层 → 行情/K线/缠论 → 技术指标 → 策略与因子研究（Alpha101/191/自定义）→ 回测 → 模拟盘 → 实盘接入 → 自动复盘 → 数据长期可用。

## 目录结构

```text
DaA/
├── config.py               # 统一配置（交易规则/参数/风控/路径，凭证从 .env 读取）
├── .env.example            # 凭证模板（复制为 .env 后填写，.env 不提交）
├── main.py                 # 薄入口 78 行（argparse 注册 + cli_gate 控制平面 + handler 分发）
├── cli_commands/           # 子命令模块（每文件 ≤300 行，暴露 add_subparser + handler）
│   ├── _common.py          # 公共：参数解析 / 策略 yaml / 指标打印 / --data 注入
│   ├── retail.py           # 零售层：backtest / paper / monitor / report
│   ├── research.py         # 策略研究：new-strategy / list / optimize / walkforward / validate / experiments / compare
│   ├── checklist.py        # 上线检查清单（四类计数）
│   ├── factor.py           # 因子流水线 + market
│   ├── data.py             # updatedata / download / chart / import
│   ├── qi.py               # 合格投资者层：nav-backtest / reits-monitor / neeq-screen / qi-check / set-mode
│   └── derivatives.py      # derivatives-sim（个人禁止实盘红警）
├── test_env.py             # 第 0 步环境自检脚本
├── test_data.py            # 第 1 步数据层验证（15 个标的 + 19 项核查）
├── test_chart.py           # 第 2 步图表验证（K线/多周期/形态/并排/复盘/交互式）
├── test_pattern.py         # 第 2 步形态标注专项（金叉死叉/背离/突破）
├── test_chan.py            # 第 2 步缠论专项（分型/笔/线段/中枢/买卖点/绘图）
├── test_export.py          # 第 2 步导出专项（下载/CSV+parquet 回读/概览/增量/CLI）
├── check_progress.py       # 搭建进度看板
├── progress.json           # 步骤进度数据（中断恢复依赖）
├── requirements.txt        # 依赖清单
├── core/                   # 核心模块
│   ├── utils.py            #   日志/重试/交易日历/re_sample_kline 周期重采样
│   ├── data_fetcher.py     #   统一数据层（19 类市场含 cn_index + get_kline 周期路由）
│   ├── chart.py            #   绘图（K线/指标副图/归一化对比/并排网格/回测复盘/plotly）
│   ├── pattern_annotate.py #   形态标注（均线金叉死叉 / MACD 背离 / 突破）
│   └── chan.py             #   缠论（包含合并→分型→笔→线段→中枢→买卖点 + 多级别）
├── tools/                  # 工具（data_export.py 批量下载导出 / source_status.py 数据源可用性矩阵）
├── factor/                 # 因子研究（表达式引擎/Alpha101/Alpha191/评估/合成/适配器）
├── strategies/             # 用户策略（每个策略一个 .py）
├── configs/strategies/     # 策略参数 yaml
├── research/               # 参数优化/走向前分析/稳健性验证/实验记录
├── tests/                  # 策略与研究测试
├── broker/                 # 券商/期货实盘适配器（QMT/PTrade/CTP，第12步）
├── risk/                   # 实盘风控（第12步）
├── live/                   # 实盘执行/守护/告警/对账/日志代码（第12步）
├── nav_backtest/           # 合格投资者层净值型回测（第10步）
├── derivatives_pricing/    # 场外衍生品定价模拟（第10步）
├── data_cache/             # 数据缓存（raw/adj_factors/minute/factors/snapshots/index_members/constituents）
├── export/                 # 行情导出（csv/parquet/excel + watchlist.csv + 数据概览_日期.csv）
├── logs/                   # 日志
├── backtest_results/       # 回测结果与图表（BACKTEST_DIR，图表在 charts/）
├── reports/                # 自动复盘报告与索引（REPORT_DIR）
├── paper_trading/          # 模拟盘运行数据（PAPER_DIR）
├── live_trading/           # 实盘运行数据：成交/持仓快照（LIVE_DIR）
├── audit_logs/             # 实盘合规审计日志（AUDIT_DIR，.gitignore 屏蔽）
└── research_output/        # 因子/研究报告输出（RESEARCH_DIR）
```

## 运行方法

```bash
# 1) 安装依赖
pip install -r requirements.txt

# 2) 配置凭证（回测/模拟盘阶段可留空）
cp .env.example .env

# 3) 环境自检（依赖 / 目录 / config / 市场识别）
python test_env.py

# 4) 查看搭建进度与下一步
python check_progress.py

# 5) 数据层自检（15 个标的 + 19 项核查：单位/分钟根数/长历史/列名/缺口回填/因子同源/会话恢复/指数/单点故障/stale 边界/回测豁免/市场时钟等）
python test_data.py

# 6) 第 2 步：图表 / 形态 / 缠论 / 导出四个自检
python test_chart.py      # K线、多周期、形态标注、4 标的并排、回测复盘、plotly、000300 基准（19 项）
python test_pattern.py    # 金叉死叉 / MACD 背离 / 突破，含未来函数红线（14 项）
python test_chan.py       # 分型/笔/线段/中枢/一~三类买卖点 + 点数自证 + 过滤开关 + 绘图（32 项）
python test_export.py     # 下载 600519/510300/AAPL → CSV+parquet 回读校验 + 概览（11 项）

# 7) 数据源可用性矩阵（后端连通性 + 逐市场取数源与回退，东财挂没挂一眼看清）
python -m tools.source_status
python -m tools.source_status --json

# 8) 批量下载导出（断点续传，重复执行会自动跳过已覆盖区间）
python -m tools.data_export --symbols 600519,510300,AAPL --start 2020-01-01 --format csv,parquet
python -m tools.data_export --add 600519            # 加入自选池 export/watchlist.csv
python -m tools.data_export --batch index_300       # 批量加入当前沪深300成分（注意幸存者偏差）
python -m tools.data_export --watchlist --format parquet
python -m tools.data_export --update                # 只做增量更新
python -m tools.data_export --summary               # 只生成数据概览

# 9) 一键运行入口（控制平面：模式只允许降级、禁止旁路开关、默认值单一事实源 config）
python main.py --help                 # 全部 24 个子命令（按 [零售层]/[策略研究]/[数据与图表]/[合格投资者层] 分组）
python main.py                        # 欢迎页：版本 / 市场清单 / 当前运行模式

# 零售层（回测 / 模拟盘 / 盯盘 / 报告）
python main.py backtest --strategy ma_cross --symbols 600519,510300
python main.py backtest --strategy ma_cross --symbols 600519 --data mydata.csv   # --data 走数据层出口
python main.py paper --strategy ma_cross --symbols 600519
python main.py monitor                # 模拟盘盯盘（Ctrl+C 优雅退出）
python main.py report --strategy ma_cross --symbols 600519 --type daily

# 策略研究（脚手架 / 清单 / 优化 / 走向前 / 稳健性 / 实验对比 / 上线清单）
python main.py new-strategy --name my_trend --template trend
python main.py list-strategies
python main.py optimize --strategy ma_cross
python main.py walkforward --strategy ma_cross --train 24 --test 6
python main.py validate --strategy ma_cross --params short=8,long=30
python main.py experiments
python main.py compare --exp exp_001,exp_002
python main.py checklist --strategy ma_cross

# 因子流水线 / 市场工具
python main.py factor calc --factors alpha001 --universe 600519,510300
python main.py market search --keyword 茅台

# 数据与图表
python main.py updatedata --symbols 600519
python main.py download --symbols 600519,510300 --start 2020-01-01 --format csv
python main.py chart --symbol 600519

# 合格投资者层（净值回测 / REITs 折溢价 / 新三板筛选 / 衍生品模拟 / QI 自检 / 模式切换）
python main.py nav-backtest --strategy equal_weight --symbols 508000
python main.py reits-monitor --symbols 508000
python main.py neeq-screen --layer innovation --fundamentals neeq.csv --top 5
python main.py derivatives-sim --product snowball --s0 100 --ko 1.03 --ki 0.75
python main.py qi-check --profile '{"financial_assets_wan": 500}' --product_type private_fund
python main.py set-mode --to paper --strategy ma_cross --confirm           # 提升需清单+确认
```

当前环境实测版本：Python 3.9.6、pandas 2.3.3、numpy 2.0.2、akshare 1.18.88。

## 实盘对接指引（按状态分节）

> 状态口径与 `progress.json` 看板一致：**第 12 步已完成**（`broker/` QMT/PTrade/CTP 适配器、`data/live_data.py` 三模式行情、`risk/risk_manager.py` 三层风控、`live/` 执行器/守护/告警/审计/急停、`run_live.py` + 15 项上线检查）。**默认仍不可实盘**：三层开关（代码 `LIVE_TRADING_ENABLED=False` / `config.RUN_MODE` / `YES_CONFIRM_LIVE_TRADING` 输入确认）必须同时打开，且上线清单无 FAIL；实盘模式连不上券商直接停机，不静默退回仿真。以下通道代码已实现，但**实盘开通前必须完成券商开户、穿透式监管报备与仿真验证**（`python run_live.py --checklist`）。

### ✅ 可回测 / 可模拟盘（当前已可用）

- 零售层 13 类品种的日线/分钟回测、模拟盘、盯盘、复盘报告全部可用（`python main.py backtest|paper|monitor|report`）。
- 本地数据导入（`--data` 数据层出口，三物化列强制校验）。

### ✅ 已实现通道（第 12 步，默认关闭）

| 市场 | 通道 | 说明 |
|:---|:---|:---|
| A股 | QMT（xtquant）/ PTrade | 券商柜台；需要机构或个人量化权限；QMT 支持 mini/standard/simulation 三模式 |
| 国内期货 | CTP（tqsdk / openctp） | `ctp_broker.SIMNOW_PRESET` 可直接连 SimNow 仿真；实盘需期货公司 CTP 账号并通过 `PenetrationTestHelper` 穿透参数自检（app_id/auth_code 不得用 SimNow 默认值） |
| 美股/港股 | 暂未实现（预留 ib_insync） | 需常驻 TWS/IB Gateway；当前仅 `SimBroker` 仿真 |
| 加密货币 | 暂未实现 | 仅合规辖区研究用途，系统不提供实盘支持 |

通道代码只实现发单原语（不决策）：`broker/` 之外 import `xtquant / ths_ptrade / ctp` 视为违规（`ORDER_PORT_CONFORMANCE['forbid_sdk_import_outside_broker']`）。真实报单唯一收口 `live/live_trader.py::submit_order`，依次过 `signal_gate → risk → qi → 时效 refetch → 首单限额 → 幂等`。`config.RUN_MODE` 提升至 `live` 需「上线清单无 FAIL + `--confirm` + `YES_CONFIRM_LIVE_TRADING`」。

### ❌ 无法自动化（人工流程）

- 私募证券基金、券商资管、信托计划：申赎只能走基金销售/管理人人工流程；本系统仅提供净值型回测、合格投资者资格自检（`qi-check`）与披露材料生成，**不下单**。
- 新三板：流动性差，筛选结果仅供研究，实盘下单前必须人工复核。

### 🚫 永不提供实盘（红线）

- 场外衍生品（雪球 / TRS / 期权 OTC）：`derivatives_pricing/` 仅理论定价模拟，`LIVE_TRADING_FORBIDDEN=True`、无任何下单通道（`ORDER_CHANNELS=()`），**个人禁止实盘场外衍生品**。

### ⚠️ 强烈不建议

- 外汇保证金、加密货币杠杆：监管与对手风险高，系统不提供实盘支持。

## 未实现能力（诚实标注，未完成不计入进度）

- **第 13 步（数据与报告长期可用性）**：多源冗余、原始价快照、时点成分股、长期归档——全部未开始。
- 上述未实现步骤**不计入完成百分比**（`python check_progress.py` 的百分比只统计已完成步骤）。

## 常见问题

- **`ModuleNotFoundError: No module named 'akshare'`**：未安装依赖，执行 `pip install -r requirements.txt`。
- **`detect_market_type` 识别不符合预期**：6 位数字段的 A股/ETF/基金/转债，以及 2-3 位纯字母的美股/期货/加密存在天然歧义；可在调用处显式传入 `market_type` 覆盖。
- **港股/美股节假日判断**：A股用 `chinesecalendar`，美股按 NYSE 规则计算，港股使用 `core/utils.py` 内的 `HK_EXTRA_HOLIDAYS`（按年维护，未覆盖年份退回 A 股日历）。
- **代理/网络导致行情接口失败**：所有出网请求都经 `DataFetcher._request`（节流 ≥0.3s + 指数退避重试 + 数据源标识），并内置多源回退（东财→新浪、币安多主机）；接口不可达时优先返回本地过期缓存并告警。
- **实盘凭证安全**：所有账号/密码/Token 只写在 `.env`，`config.py` 通过环境变量读取，`.env` 与 `audit_logs/` 均已被 `.gitignore` 屏蔽。

## 数据源可用性（运行时探测，非硬编码）

> ⚠️ 本节是**运行时探测结果**，不是写死的配置：`config.SOURCE_AVAILABILITY` 只记录「最近一次实测现状」，
> 会随本机网络环境/数据源限流变化。**东财不可达大概率是本机到 push2his 的网络问题，不是永久下线**——
> 2026-10-30 复测时东财已恢复（0.64s / 17 行），2026-10-28 曾持续 `RemoteDisconnected`。
> 架构上必须走「自动探测 + 切换」（第 13 步），禁止用 `available` 静态决定取数路径。

一键打印当前矩阵（**取数源改动后必须同步** `tools/source_status.py` 的 `DAILY_ROUTE`）：

```bash
python -m tools.source_status          # 人读表格：后端连通性(可用性/延迟/备注) + 逐市场取数源 + 东财挂时影响
python -m tools.source_status --json   # 机器读：后端健康状态 + 延迟 + 各市场主源/回退/备注（第 13 步用）
```

探测实现：每个后端一次轻量请求，**单后端超时 5s**（daemon 线程，不会卡住进程），结果在同一次运行内缓存不重复探测。

### 后端连通性（2026-10-30 实测）

| 后端 | 状态 | 延迟 | 探测接口 |
|:---|:---:|:---:|:---|
| 东财 push2his | ✅（2026-10-28 曾 ❌） | 0.64s | `stock_zh_a_hist`（个股/ETF/指数/分钟共用此后端） |
| 新浪 A股 | ✅ | 1.61s | `stock_zh_a_daily` |
| 新浪期权 | ✅ | 0.30s | `option_sse_daily_sina` |
| 新浪期货 | ✅ | 0.40s | `futures_main_sina` |
| 新浪外汇分钟 | ✅ | 0.30s | `NewForexService.getMinKline` |
| BaoStock | ✅ | 0.27s | `query_history_k_data_plus` |
| 腾讯指数 | ⚠️ 超时 | >5s | `stock_zh_index_daily_tx`（**amount 列实为成交量(手)**，未接入） |
| 币安 | ⚠️ 超时 | >5s | `GET /api/v3/ping` |

### 逐市场日线取数源

| 市场 | 主源 | 回退链 | 东财挂时 | 说明 |
|:---|:---|:---|:---|:---|
| cn_stock | 东财 `stock_zh_a_hist` | 新浪 `stock_zh_a_daily` | 新浪 | 新浪 volume=股/amount=元 |
| cn_etf | 东财 `fund_etf_hist_em` | 新浪 `fund_etf_hist_sina` | 新浪 | 回退时**无法复权**（`adjust=none`） |
| cn_convertible | 新浪 `bond_zh_hs_cov_daily` | 无 | 新浪（不变） | 仅此一源；无成交额 → `close×volume(张)` 估算 |
| cn_reits | 东财 `reits_hist_em` | 新浪 `fund_etf_hist_sina` | 新浪 | 回退时**无法复权** |
| cn_index | 东财 `index_zh_a_hist` | 新浪 → BaoStock | 新浪 | 新浪无成交额（`amount=NaN`）；tencent 未接入 |
| cn_future | 新浪 `futures_main_sina` | 无 | 新浪期货（不变） | 无成交额，volume=手 |
| global_future | 新浪 `futures_foreign_hist` | 无 | 新浪外盘（不变） | 无成交额、无分钟线 |
| forex | 东财 `forex_hist_em` | 无 | **❌ 报错** | 日线单点；分钟走新浪 NewForexService |
| cn_option | 新浪 `option_sse_daily_sina` | 无 | 新浪期权（不变） | 仅此一源；无成交额 |
| crypto | 币安 `/api/v3/klines` | 无 | 币安（不变） | 不依赖东财/新浪 |
| hk_stock | 东财 `stock_hk_hist` | 新浪 `stock_hk_daily` | 新浪 | 新浪**含成交额**（ratio≈1.007，已验证） |
| us_stock / us_etf | 东财 `stock_us_hist` | 新浪 `stock_us_daily` | 新浪 | 新浪无成交额 → `amount=NaN` + `amount_missing` |
| cn_fund | 东财 `fund_open_fund_info_em` | 无 | **❌ 报错** | 净值曲线，非 K 线 |
| cn_reverse_repo | 东财 `bond_buy_back_hist_em` + 快照 | 无（同一后端） | **❌ 报错** | 收盘价是年化利率 |
| private_fund / qii_product / otc_deriv / neeq | - | - | 无 K 线 | 净值/定价路径（第 10 / 12 步） |

### 单点故障市场（`config.SINGLE_SOURCE_MARKETS`）

- **日线单点**：`forex`、`cn_fund`、`cn_reverse_repo` —— 只有东财一个源，源挂即彻底取不到。
- **分钟单点**：`cn_convertible`、`us_stock`、`us_etf`、`hk_stock` —— 分钟线只有东财；
  注意这是**不对称**的：这四家的**日线有新浪备源**，分钟线没有。
- **失败行为（硬约束）**：这些市场取数失败时**必须显式抛 `RuntimeError`，文案含「该市场当前无可用数据源」**，
  禁止静默返回空 DataFrame——否则第 3 步拿它算指标会得到一堆 NaN 而不自知。有本地增量库时返回过期数据
  并标 `attrs["stale"]=True`（不是空表），且受下面的 stale 上限约束。有备源的市场（如 cn_stock / cn_index 日线）正常回退并打 WARNING，不报错。
- 第 13 步**补源优先级最高**的就是这批市场。

### stale（过期）数据的使用边界（实盘安全）

| 项目 | 约定 |
|:---|:---|
| 判定口径 | `attrs["stale_days"]` = 本地最后一根 K 线日期 与「最近一个**已收盘**交易日」之间的**交易日数差**（交易日历计算，不是自然日）；差 > 0 → `attrs["stale"]=True` 并打 WARNING |
| 市场时钟 | 「最近已收盘交易日」**逐市场**判定，不共用 A 股 15:00：A股 15:00 CST / 港股 16:00 HKT / 美股 16:00 美东（含夏令时，`America/New_York`）/ 期货含夜盘 / 外汇近 24h / 加密 7×24（最近已完成日线＝昨天）。避免凌晨取美股被误判过期 |
| 上限 | `config.STALE_LIMIT = {"daily": 5, "minute": 2}`（交易日）；`stale_days > 上限` → 视为不可用，**直接抛错** |
| 回测 / 研究 / 因子 | **允许**使用 stale 数据（调用方自行决定是否继续，需读 `attrs` 判断） |
| 图表展示 | **允许**，但图上必须标注「数据截至 X 日」（`core/chart.py` 已自动在右上角红字标注，含过期交易日数） |
| 模拟盘 / 实盘下单 | **禁止**。两道防线见下 |

**双重防线（下单时效保护不得依赖上游是否传参）**

| 防线 | 机制 | 适用 |
|:---|:---|:---|
| 第一道（数据层，显式声明） | `get_daily/get_minute(..., for_trading=True)` 遇 stale 抛 `RuntimeError`（含「禁止用于…下单决策」） | 任何模式 |
| 第二道（数据层，按运行模式） | `config.RUN_MODE ∈ {paper, live}` 且 `config.TRADING_REQUIRE_FRESH=True` 时，**即使忘记传 `for_trading`**，stale 或超 `STALE_LIMIT` 也一律抛错 | paper / live；**backtest 豁免** |
| 第三道（第 4 步订单模块，必做） | `core/account.py` 下单前**独立**调用 `data_fetcher.assert_fresh_for_trading()` 复核；下单闸门已持有 `market+symbol`，**默认直接 refetch 最新数据**，不依赖传入帧的列/attrs（决策帧由纯函数指标拼成，时效列带不过来） | paper / live |

> **验收判据**：把数据层的 `for_trading` 全部去掉，paper/live 下单链路仍须拦得住 stale 数据。
> **回测豁免**：`backtest` 模式按定义就用历史数据跑过去，相对今天永远「过期」，闸门不生效（否则全部回测被拒）。

**attrs 易失（pandas 2.3.3 实测，`config.ATTRS_FRAGILE_NOTE`）**

- **保留** attrs：`concat` / `merge` / `groupby` / `resample().agg()` / `diff` / `pct_change` / `cumsum` / `astype` / 布尔索引；
- **清空** attrs：`rolling()` / `ewm()` / `expanding()`（返回 `{}`），`to_numpy()` 重建也丢失；
- 后果：MA/EMA/MACD/RSI/BOLL/ATR 全走窗口运算，**指标算完 stale 标记就没了**。

**时效物化列（关键修正：不把 fail-closed 装在读不到信息的位置）**

| 项目 | 约定 |
|:---|:---|
| 物化列 | `config.STALE_INFO_COLUMN = "data_asof_date"`：`get_daily` / `get_minute` / `get_kline` 出口把「本帧数据最新日期」逐行写入**普通列**。普通列能穿过 `rolling/ewm/expanding/resample/concat`，指标计算后仍可判时效 |
| 写入口径（A2） | 必须是**该帧最后一根 bar 的实际日期**（`df.index[-1]`；周/月线取底层日线最后一根，避免 W-FRI/ME 标签把日期推后），**绝不是取数时刻/今天**。缓存命中填缓存数据自身最后日期，失败回退帧同理。否则缓存里 7 天前的数据会被标成新鲜，防线在最常见的缓存路径上失效 |
| 多标的帧（A3） | 按 `symbol` 分组填各自最新日期，**禁止整帧广播同一日期**；下单某标的时只读该标的自己的行，否则组合里 B 停更 7 天也会被判新鲜 |
| 复核优先级（A1） | `assert_fresh_for_trading()`：① 有 `market+symbol` → **默认 refetch 最新数据**（TTL 内复用）→ ② 拿不到 `market+symbol` 才退回读物化列（多标的按 symbol 取行）→ ③ 再读 `attrs["last_bar"]` → ④ 只有「既无时效列、又无法重取」才 fail-closed |
| refetch 失败（A4） | 网络抖动/源不可达时按 `config.STALE_REFETCH_FAIL_POLICY = {"open": "reject", "close": "allow"}`：**开仓拒单、平仓放行**（不能因为取不到行情就下不出止损/平仓单）；同批次结果复用 `config.STALE_REFETCH_TTL_SEC = 60` 秒，避免组合调仓逐单打满接口 |
| 回测边界（A5） | `backtest` 默认放行（调用方未显式要求时）；**显式传 `for_trading=True` 时回测里仍拦**（用于预演「上实盘会怎样」） |
| fail-closed 边界 | 见 `config.FAIL_CLOSED_NOTE`：**禁止仅因 attrs 为空或决策帧没有时效列就 fail-closed**，否则指标计算后的每一笔下单都会被拒，实盘瘫痪 |
| 其他约定 | ① 指标/因子函数不要在内部透传 attrs，在入口处判定时效并存局部变量；② 下单/策略在**用数那一刻**重新校验时效，禁止读中间帧的 `attrs["stale"]`；③ 物化列是 datetime，`df.rolling()` 请按列算（整帧 rolling 会因 datetime 列报错） |

实现位置：`DataFetcher._latest_completed_trading_day` / `_stale_trading_days` / `_mark_stale` / `_enforce_stale` / `_attach_asof`；
模块级 `_stale_gate_enabled()`（按 `RUN_MODE`）与 `assert_fresh_for_trading()`（第三道防线）。
调用入口 `get_daily(..., for_trading=False)` 与 `get_minute(..., for_trading=False)`。

### 新浪美股/港股日线历史深度（实测）

| 标的 | 源 | 起始 | 行数 | 成交额 |
|:---|:---|:---|:---:|:---|
| AAPL | 新浪 `stock_us_daily` | 1984-09-07 | 10,064 | 无（`amount=NaN`） |
| SPY | 新浪 `stock_us_daily` | 2001-01-02 | 6,494 | 无（`amount=NaN`） |
| 00700 | 新浪 `stock_hk_daily` | 2004-06-16 | 5,503 | 有（港元，ratio≈1.007） |

即日线历史深度足够长（20~40 年），真正的短板是**分钟线**：东财不可达时这四家分钟线会显式报错。

### 东财不可达时的影响（不得静默）

- **只能走新浪系（无其他备源）**：`cn_convertible`、`cn_future`、`global_future`、`cn_option`（期权只有新浪期权通道，该通道挂则取不到，东财无期权日线备源）。
- **自动回退新浪**：`cn_stock`、`cn_etf`、`cn_reits`、`cn_index`、`hk_stock`、`us_stock`、`us_etf`。
- **东财挂则直接报错（无回退）**：`forex`、`cn_fund`、`cn_reverse_repo`。
- **不依赖东财/新浪**：`crypto`。
- **分钟线仅东财、东财挂则报错**：`cn_convertible`、`us_stock`、`us_etf`、`hk_stock`；`cn_index` 东财优先但可回退新浪（1970 根上限）。
- 所有回退都由 `DataFetcher` 打 WARNING，不静默；新浪 ETF/REITs 复权因子退化为 1（`adjust=none`），美股/期权新浪源无成交额（`amount=NaN` + `amount_missing`）。

> **第 13 步会在此挂多源自动切换与健康度打分**：以 `python -m tools.source_status --json` 作为健康检查输入，按市场维护候选源、失败计数与冷却时间。当前只做「探测 + 如实呈现」，不改优先级、不做自动切换。

## 已知限制

### 单位未确证（`DataFrame.attrs["unit_uncertain"] = True`）的接口

登记在 `config.DATA_SOURCE_UNITS` 的 `verified=False` 条目，返回时原值透传并打标，禁止静默猜测：

| 接口 | 覆盖市场 | 未确证原因 |
|:---|:---|:---|
| `reits_hist_em` | 公募 REITs 日线 | 东财 REITs 本机不可达，未实测 |
| `stock_us_hist` / `stock_us_daily` | 美股日线 | 东财美股本机不可达；新浪无成交额（已显式置 NaN） |
| `stock_hk_hist_min_em` / `stock_us_hist_min_em` | 港股/美股分钟 | 东财分钟本机不可达 |
| `option_sse_daily_sina` | 场内期权日线 | 无成交额字段 |
| `forex_hist_em` / `sina_forex_min` | 外汇日线/分钟 | 接口无成交量或单位未说明 |
| `bond_buy_back_hist_em` / `bond_buy_back_snapshot` | 国债逆回购 | 收盘价是年化利率，`amount/(close×volume)` 无经济含义 |

运行时动态打标的场景：**指数分钟**（`index_zh_a_hist_min_em` / `stock_zh_a_minute` 用于 `cn_index` 时单位未实测，仍标 `unit_uncertain=True`）；以及任何未在 `DATA_SOURCE_UNITS` 登记的接口。**指数日线已不再标 uncertain**：新浪 `stock_zh_index_daily` 与 BaoStock `baostock_index_daily` 均已置 `verified=True`（跨源验证见下），东财 `index_zh_a_hist` 因本机不可达仍为 `verified=False`，一旦实际用上会继续标 `unit_uncertain`。指数不做 `amount/(close×volume)` 自检——点位×成分股股数 与成交额无换算关系，实测比值 ≈0.0057 属正常，`attrs["unit_ratio_note"]` 会说明；量级判断改用 `amount/volume`（≈成分股均价）。

### 其他数据边界

- **期货/外汇无免费长历史分钟源**：新浪期货 1023 根、外汇约 974 根且接口无时间游标，不能分页；只能靠自建分钟增量库逐日累积。国际期货仍不提供分钟线。
- **BaoStock 仅盘后数据（无实时）**：请求区间含「今天」时自动跳过 BaoStock，改走新浪/东财；若盘中/数据源未更新仍取不到当日，打印 WARNING 说明，不静默返回空。
- **BaoStock 分钟线不含指数、无 1 分钟周期**：指数分钟自动转新浪（上限 1970 根）；1 分钟仅新浪/东财近期数据。
- **BaoStock 分钟线不覆盖 ETF/REITs/可转债**：`cn_etf` 走新浪（1970 根上限）→ 东财（约 1 个月），`cn_convertible` 走东财。
- **BaoStock 60 分钟 15:00 根与官方日线收盘偶有偏差（已定性为源噪声，不是复权 bug）**：725 个可比交易日中 9 日相对偏差 >0.1%（最大 0.2535%，中位 0.0000%）。9 天里 **8 天距最近除权日 28~154 天**，仅 1 天（2025-12-19）落在除权日当天且偏差仅 0.1184%；按距除权日分组（±5 天 24 日仅 1 日 >0.1%、6~20 天 62 日 0 日、21~60 天 154 日 2 日、>60 天 485 日 6 日）呈**随机散布**。全部 5 个除权日的 `日线raw × foreAdjustFactor` 与 `日线qfq` **完全相等（差 0.000000）**，且原始价口径与 qfq 口径的偏差完全一致（差 ~1e-14），证明因子日期对齐无 off-by-one。偏差日的分钟量合计比日线量少 1.1%~4.9%，属 BaoStock 分钟线缺尾盘集合竞价/最新一笔成交。**结论：0.25% 量级偏差对日线级/日频回测可忽略，对日内高频需留意**；需要严格收盘价时请用日线，不要用分钟 15:00 根替代。
- **ETF/REITs/可转债的分钟线仍受上游上限**：新浪 1970 根、东财约 1 个月；超出部分标 `minute_history_capped=True` 并由自建增量库逐日累积，不回填已复权价。
- **A股日线与分钟线统一使用 BaoStock `query_adjust_factor` 因子源**（`adj_factors/cn_stock_{symbol}_bs_factors.csv`，字段实测为 `dividOperateDate` / `foreAdjustFactor` / `backAdjustFactor`）；日线 qfq/raw 比值与 `foreAdjustFactor` 实测最大差 1.1e-16。字段名不匹配或返回空会直接抛错，不会退化成「数据源不支持复权」的温和告警。
- **crypto 分钟单次回填上限 20000 根**（`limit=1000` × 最多 20 次请求），每次请求间隔 ≥0.3s；超过上限标 `minute_history_capped=True`，`attrs` 同时记录 `backfill_cap_bars` / `request_interval`。
- **东财 push2his 间歇 `RemoteDisconnected`**：已加重试与多源回退（逆回购回退东财快照）；回退新浪时 ETF/REITs 复权因子退化为 1，标 `adjust=none` 并告警。
- **逆回购 204001 行数取决于请求区间**：`bond_buy_back_hist_em(symbol)` 原始返回 4949 行（2006-05-08 起），`get_daily` 的近 30 天请求只有约 18 行是日期过滤所致，不是接口截断。
- **部分市场走净值/定价路径**：新三板、私募基金、券商资管/信托、场外衍生品无公开 K 线，`get_daily` 显式报错说明路径，不返回空表。
- **复权因子取不到时**：分钟线仍返回不复权原价（`adjust=none`、`minute_factor_available=False` + 具体原因），**不会**把前复权价写入增量库（违反 raw+因子分离约定）。
- **分钟增量库缺口（双重日历校验）**：`get_minute` 以「该标的日线索引」为主（可排除停牌日与除夕等调休休市日）、`chinesecalendar`/`is_trading_day` 为兜底比对缺口，中段缺口会主动回填；仍补不回的（超出数据源上限）写入 `attrs["gap_dates"]` / `gap_count` 并 WARNING。当日历说开市、日线却缺该日时视为「**日线缺口**」而非休市，写入 `attrs["daily_gap_dates"]` / `daily_gap_count` 并 WARNING（停牌或调休休市同样会命中，需人工复核），避免日线缺失造成分钟缺口检测盲区。
- **BaoStock 会话自动恢复**：模块级单例登录在长时间运行/盘中可能被服务端断开；命中「未登录 / 登录过期」（`error_code` 10001001/10002001/10002007 或对应 error_msg）时自动 `logout → login → 重试一次`，仍失败才向上抛错。

### 图表与导出边界（第 2 步）

- **基准默认是真实指数**：`plot_compare` / `plot_kline_grid` 传 `000300` 时走 `cn_index` 专用接口（`sh000300`），图例显示「沪深300(000300)」；只有指数三源全部取数失败才回退场内 ETF 代理（`000300→510300`、`000905→510500`、`000016→510050`、`399006→159915`）并打印 WARNING，此时图例写「沪深300(510300 ETF)」——回退时**不要**把 ETF 曲线当成指数本身。
- **指数代码带不带前缀要分清**：`detect_market_type` 在「国内期货：字母+数字」判定**之前**插入 `SH/SZ + 6 位` 拦截，命中 `INDEX_PREFIX_RULES`（SH: 000/950/880/881，SZ: 399/980/981）即判 `cn_index`，否则剥前缀按标准 6 位规则重判。实测 `sh600519→cn_stock`、`sh510300→cn_etf`、`sz000001→cn_stock`、`sh000001/sh000300/sz399001/sh880001→cn_index`，不再被误判为 `cn_future`。**裸 6 位分两类**：`399001/399005/399006/399673/932000` 不与个股号段冲突，按 `config.CN_INDEX_BARE_CODES` **可裸识别为 `cn_index`**；而深市个股号段 `000/001/002/003` 与沪市指数 `000xxx` 段**完全重合**（000001=平安银行、000009=中国宝安、000016=深康佳A、000688=国城矿业），故裸 `000300/000905/000016/000688` 一律**维持个股优先**，取这些指数必须带前缀（`sh000300`）。传裸 `000xxx` 且命中 `CN_INDEX.common_codes` 时，`_detect_market` 会打 WARNING「检测到疑似指数代码 000300（沪深300），已按深市个股处理；如需取该指数请传 sh000300」——**只引导不改判定**。
- **指数不可交易**：`config.CN_INDEX["tradeable"]=False` 且带 `not_tradeable_reason`，订单层（第 4 步）遇到 `cn_index` 必须直接拒单并提示用对应 ETF/股指期货代替。
- **指数无复权、无成交额要看源**：`get_daily` 对 `cn_index` 强制 `adjust="none"`（缓存名带 `none` 标识）；东财 `index_zh_a_hist` **必须传裸代码**（`000300`，传 `sh000300` 会失败）且有成交额（`volume=手`、`amount=元`，ratio≈100）。新浪 `stock_zh_index_daily` 认带前缀形式、无成交额 → `amount` 置 **NaN** 并标 `attrs["amount_missing"]=True`，**不补 0**。两源成交量差 100 倍（东财=手、新浪=股），一律按 `config.DATA_SOURCE_UNITS` 折算为**手**，并在 `attrs["volume_unit"]`（统一后单位）/ `attrs["source_volume_unit"]`（源单位）显式标注；跨源切换时打 WARNING「源已切换：东财（手、含成交额）→ 新浪（股、无成交额），单位不同但已按 100 股=1 手统一」。
- **新浪指数 volume=股 已独立跨源验证（不是靠腾讯反推）**：2026-10-27 同日对比 BaoStock `sh.000300`（`volume=16,868,847,400` 股、`amount=383,125,564,549` 元、`amount/volume=22.71` 元/股 量级合理）与新浪 `sh000300`（`volume=16,868,847,400`），**r = volume_sina/volume_bs = 1.0000** → 新浪为「股」，×0.01 转「手」的当前实现**正确**；`sh.000001`（41,778,953,200，r=1.0000）、`sz.399001`（52,144,802,840 vs 52,191,734,816，r=0.9991，差异源于源修订）一致。腾讯 `stock_zh_index_daily_tx` 只有一个数量列且名为 `amount`，其值精确等于新浪 volume÷100，即「手」不是成交额，故**未接入**（`_cn_index_daily_one("tencent")` 显式抛 `NotImplementedError`）。`CN_INDEX_DAILY_PRIORITY = ["eastmoney","sina","baostock","tencent"]` 已登记，接入腾讯前必须按「手」处理，否则偏小 100 倍。
- **周/月线最后一根可能未走完**：`re_sample_kline()` 会把当前周/月的最后一根标 `is_complete=False`、`attrs["last_bar_incomplete"]=True`；**做信号时必须丢弃或显式标记**，否则等于用未来数据。
- **图表文件名会互相覆盖**：静态图命名为 `{symbol}_{period}_{起}_{止}_kline.png`，同标的同区间但换了 MA/指标/开关再跑一次会覆盖上一张；需要保留多版本请自行改 `save_fig()` 的 `name`。
- **1 分钟周期不在默认出图清单**：`config.CHART_CONFIG["plot_periods"]` 是「默认出图子集」（7 种，去掉 1min），`config.SUPPORTED_PERIODS` 才是「可取数全集」（8 种）；要看 1 分钟需显式 `plot_kline(df, symbol, period="1min")`。
- **形态标注全部等确认才画**：MACD 背离用 `scipy.signal.argrelextrema` 找局部极值，且必须右侧再走 `confirm_right` 根 K 线才判定；确认日未到的极值一律不标（`test_pattern.py` 有断言）。突破用的是 `rolling(window).max().shift(1)`，不含当根。
- **缠论笔/线段本身有主观性**：自动识别与人工划分可能有出入（尤其震荡市），图与结果仅供参考，争议区间请人工核对 K 线；`ChanAnalyzer._doubt_ranges()` 可给出存疑区间。
- **Excel 导出只适合少量标的**：`--format excel` 会把所有标的写进同一个工作簿，超过 20 个只打 WARNING 不阻止（文件会很大）。
- **自选池批量加入有幸存者偏差**：`--batch index_300` 拉的是**当前**成分股，仅适合看当下行情；历史回测股票池必须用第 13 步的时点成分股（Point-in-Time）。
- **缠论一/二/三类买卖点均已实现，三类点天然稀疏**：`find_buy_sell_points()` 输出 B1/S1（背驰）、B2/S2（一类点后第一次回抽不破前低/前高）、B3/S3（突破中枢 ZG/ZD 后回抽不回中枢）。所有二类点带 `src_date` 字段可**溯源到其前置一类点**。实测 600519 `2020-01-01~2026-10-27`（1650 根 / 笔 172 / 中枢 27）：**B1=16、B2=11、B3=2、S1=18、S2=11、S3=1**（共 59）；6 年窗口（1453 根 / 中枢 24）：B1=14、B2=9、B3=1、S1=15、S2=10、S3=1。**B2≤B1、S2≤S1** 是构造性约束（每个一类点最多派生一个二类点），若出现 B2>B1 说明二类判定过宽。三类点要求离开笔真突破且回抽不回中枢，震荡市可能长时间没有 B3/S3，策略里不要假设每段都有。
- **中枢延伸上限 9 笔是工程折中，不是缠论原文约束**：`ChanAnalyzer.MAX_CENTER_BI = 9`（≈3 个线段，恰好容纳「进入段 + 中枢震荡 + 离开段」）。缠论原文对延伸笔数无上限，但全放开会让一个中枢顺着趋势吞掉整段行情——实测 600519 六年日线在无上限时中枢只剩 19 个且 **B3/S3 归零**；上限 12/20/∞ → B3=0/S3=0，上限 5 → B3=2/S3=1，上限 3 → B3=4/S3=2（中枢 55 个，切分过碎易出假信号）。取 9 是「三类点可用 + 中枢不过碎」的折中；**极端单边或超长横盘下可能误切/多切中枢，三类点请人工核对 K 线**。
- **本实现是「轻量缠论」，三类点必须人工核对**：包含合并/分型/笔/线段/中枢/买卖点均为工程近似，**不修复**已知的三类点稀疏问题，但如实标注——实测六年日线 B3+S3 合计仅 3 个，且对 `MAX_CENTER_BI` 高度敏感（见上一条敏感性表）。实盘接入前须人工核对 K 线，不要直接拿 B3/S3 当交易信号。若想要「放量突破」的更严格口径，可打开 `config.CHAN_CONFIG["b3_filter_enable"]=True` 并设置 `b3_min_leave_pct`（离开笔相对 ZG/ZD 的最小幅度）与 `b3_min_leave_volume_ratio`（离开段均量 / 中枢期均量的最小倍数）——**默认关闭**，开启后三类点只会更少。
- **撮合价基准已参数化，且强制「成交 bar 严格晚于决策 bar」**：指令集第 7 步原文写「每日收盘后用当日收盘价撮合」，但同一条又要求「与回测引擎保持完全一致的撮合逻辑」。两者冲突时以**时点正确性**为准：`ExecutionModel` 统一读 `config.EXECUTION_MODEL["match_price_basis"]`（唯一参数源，默认 `next_open`），四档取值 `next_open` / `next_close` / `same_open` / `same_close` 由 `match_price_basis_meta` 声明 `price` / `bar_offset` / `lookahead_safe`。`next_*`（`bar_offset=1`）下引擎把订单排队到下一根 bar、以 `fill_now=True` 重跑完整校验链后成交；`same_*`（`bar_offset=0`）属于同根撮合，会触发 `core/execution.py::assert_fill_after_signal` 抛 `LookaheadError`（`enforce_fill_after_signal=True` 时是硬错误，不得降级为普通拒单；置 False 仅告警，用于对照实验）。回测、模拟盘共用同一常量，且策略当根返回 `pending` 而非 `filled`——**禁止用决策当根的开盘/收盘价成交**。想改成收盘价口径必须切换常量让两引擎同时生效，不允许只改模拟盘。
- **模拟盘的时段判定只用交易日历，不按时钟卡点**：`run_daily` / `run_intraday` 用 `is_trading_day()` 跳过周末与节假日；分钟线本身只返回盘中 bar，因此不存在「非交易时段产生撮合」。刻意不加「当前时刻必须在 09:30–15:00」的硬卡点——否则收盘后（如 15:05）补跑当日分钟模拟盘会被误拦。

## 变更记录

### 2026-11-13 · 第 12 步：实盘接入层（A股 + 国内期货）

> 状态：第 11 步维持已完成；第 12 步 **已完成**（`next_step=13`，`progress.json` v3.19）。全部测试在仿真环境运行，未触碰真实资金，未提交 GitHub。

- **12.0 开工前置延续**：实盘引擎只调用 `core/signal_gate.py`（缺 `warmup_ok / data_asof_date / price_adjust` 报错）；报单唯一收口 `live/live_trader.py::submit_order`；幂等 `client_order_id` 落盘、状态未知先查券商；对账权威在券商侧并前移到「报单前 + 启动 + 盘中 60s + 日终」；禁止静默回退、报单/回报/报告标 `mode`、急停标志持久化、切模式（含降级）须无仓；个人场外衍生品硬拦；首笔限额 10000。
- **12.1–12.4 适配器**：`broker/base_broker.py`（`get_quote`、`BrokerCredentialError`、`LiveTradingDisabled`）+ `qmt_broker.py`（mini/standard/simulation，价格笼子、可转债/科创板最小手数、T+1 可卖量）+ `ptrade_broker.py`（云端定时任务原语）+ `ctp_broker.py`（SimNow 预设、`PenetrationTestHelper` 穿透参数自检、今昨仓、保证金、平今费、涨跌停）。SDK 惰性导入且仅限 `broker/`。
- **12.5 行情**：`data/live_data.py` 三模式——回测走 `get_kline` 缓存，仿真/实盘必须由 broker 提供官方行情（否则 `SilentFallbackError`，禁止用 AKShare 代替实盘行情），断线有限次重连 + 补数。
- **12.6 风控**：`risk/risk_manager.py` 账户级（熔断、集中度、杠杆、单笔 ≤10% 权益、单日 ≤20 次）、订单级（价格偏离 >2%、流动性 <1000 万、涨跌停、T+1、期货保证金）、合规级（60 秒反向单疑似自成交、频繁报撤单）。`LiveTrader` 报单前先过风控，失败 `stage="risk_block"`。
- **12.7–12.11 运行层**：`live/live_trader.py` 生命周期（`start` / `on_end_of_day`）、`live/daemon.py`（盘前 6 项检查、心跳、结算对账、优雅退出）、`live/notifier.py`（严重告警 3 次重试绕过去重）、`live/audit_log.py`（按日 JSONL 哈希链、2 年保留、`verify_chain`）、`live/kill_switch.py::PanicController`（冻结→撤单→可选清仓→断连→审计→告警，独立监听线程）。
- **12.12–12.15 启动与检查**：`run_live.py`（`--watch-only / --panic / --clear-kill-switch / --checklist`，双层开关 + `YES_CONFIRM_LIVE_TRADING`）；`tools/live_checklist.py` 15 项检查（自动项与人工项分开计数，人工项不冒充通过）；默认关闭三层防护、模式标注、禁止静默回退、切模式须无仓、衍生品硬拦、首笔限额、急停持久化。
- **12.16–12.17 测试与凭证**：`conftest.py` + `pytest.ini` 统一入口（`QUANT_OFFLINE=1` 自动跳过 network 用例）；`core/logger.py` 脱敏（密钥保留前 3 位 + `***`，资金账号只留后 4 位）并接入 `setup_logger`；凭证 `.env` + `python-dotenv`，`_get()` 用完即从环境抹除，缺失 fail-closed；`.gitignore` 补 `secrets/`、`credentials/`、`*.key`、`*.pem`。
- **数据层附带修复**：① 日线缓存「盘中抓取的残缺末根」永不重取——新增 `_last_bar_incomplete()`，按「缓存 mtime < 该 bar 收盘时刻」判定并整段重取（`update_cache` 同步重叠最后一日）；② 复权因子短窗口 `reindex` 全 NaN——因子只记录除权日，改为「原始价 ∪ 因子」排序后 `ffill` 再裁剪；③ Parquet 缓存 `datetime64[ms]` 与因子 CSV `datetime64[ns]` 精度不匹配导致对不齐，统一为 ns；④ 「因子恒为 1 = 源不支持复权」改为看全历史，避免无除权事件的短窗口被误标 `adjust=none`。
- **测试**：新增 `tests/test_broker.py`、`test_live_checklist.py`、`test_credentials.py`，扩展 `test_kill_switch_persist.py`（PanicController）；全量 **pytest 287 项 + 20 套脚本式 583 项 = 870 项，通过 / 失败 / 跳过 / 收集错误 = 870 / 0 / 0 / 0**。

### 2026-11-12 · 第 11 步复核补正 + 第 12 步开工前置（K0–K9）

> 状态：第 11 步 **维持已完成**；第 12 步正文 **未开始**，本轮只做「能真的动到钱」之前的前置闸门（`progress.json` v3.18）。

- **K0 回归口径恢复**：**20 套脚本式测试 = 583 项**（根目录 9 套：test_env 75 / test_data 34 / test_indicators 80 / test_account 49 / test_export 11 / test_chart 19 / test_pattern 14 / test_chan 32 / test_paper_trade 31；`tests/` 下 11 套：test_backtest 28 / test_engine_consistency 16 / test_match_price_basis 18 / test_research 19 / test_signal_gate 25 / test_strategy 18 / test_custom_factor 12 / test_factor_strategy 14 / test_loader 20 / test_factor 58 / test_alpha101 10），pytest `tests/` = **247 项**，合并 **830 项，0 失败 / 0 跳过 / 0 收集错误**。`main.py.broken` 已加入 `.gitignore`（`*.broken`），本地保留但不进仓库。
- **K1 结构化禁参审计**：`core/cli_gate.py` 新增 `capability_violations()` / `assert_no_structural_bypass()`，按「能力」而非参数名判定——布尔开关命中 `gate/risk/fresh/stale/warmup/bypass` 或阶梯模式名即违规；非布尔命中 `gate/risk/fresh/stale/bypass` 即违规；dest/旗标像 `mode` 或 choices 含阶梯模式且未登记 `audited_mode_actions` 即违规。`main.py` 解析后强制执行；`--data/--csv` 只有 `cli_commands/_common.py` 一个数据层出口。
- **K2 实盘与回测/模拟盘共用闸门**：`live/live_trader.py` 只调用 `core/signal_gate.py`（不重写），`on_bar/on_tick` 先过 `assert_tick_bars`（三物化列缺列报错），报单前依次过 `signal_gate → risk → qi → 时效 refetch`。
- **K3 报单幂等**：`client_order_id` 按 `LIVE_SAFETY['idempotency']['format']` 生成并 JSON 原子落盘；窗口内同键拒绝；状态未知先 `query_order` 确认已受理则禁止重发；废单不重试。
- **K4 对账前移**：权威在券商侧（`authoritative="broker"`），`pre_order / startup / intraday 60s / eod` 四处对账；不一致立即停开新仓，只有人工确认可恢复。
- **K5 出站唯一收口**：`broker/` 只实现发单原语（不 import `core.signal_gate` / `core.risk`），报单唯一收口 `live/live_trader.py::submit_order`，`broker/` 之外禁止 import `xtquant/ths_ptrade/ctp/openctp`；`signal_egress_points` 增至 5 项含 `live_order_submit`。
- **K6 模式安全**：禁止静默回退（连不上券商直接 `SilentFallbackError` 停机）、切模式（含降级）前须无持仓无在途单（CLI `set-mode` 先读模拟盘账本 + 实盘幂等账本，读不出直接拒）、报单/回报/报告带 `mode` 标注、急停标志文件跨重启保留且解除需 `MANUAL_CONFIRM`。
- **K7/K8**：场外衍生品在任何真实报单路径硬拦（`DerivativeLiveForbidden`，仅仿真放行）；首笔实盘限额 `first_live_order_max_notional=10000`，确认通道正常后 `confirm_first_order()` 放开。
- **K9 config 增量合并**：`CLI_CONFORMANCE` 追加 `forbidden_flags_check_mode="structural"` 与 `audited_mode_actions`；`signal_egress_points` 改为 5 项；运行模式注释块前新增 `LIVE_SAFETY`（9 键）与 `ORDER_PORT_CONFORMANCE`（11 键）。
- **测试**：新增 `tests/test_live_gate.py`（5）、`test_idempotency.py`（7）、`test_reconcile.py`（7）、`test_kill_switch_persist.py`（4）、`test_order_port.py`（16），`test_entry.py` 扩到 **59 项**；同步修正三处 5 出口断言。

### 2026-11-12 · 第 11 步（重启版）：薄入口 + `cli_commands/` 子模块拆分

> 状态：第 10 步 **维持已完成**；第 11 步 **已完成**（`next_step=12`，`progress.json` v3.17）。上一版把全部 1122 行业务塞在 `main.py` 内，长文本写入多次损坏；本版按「薄入口 + 子模块」重建：`main.py` **78 行**，业务全部下沉到 `cli_commands/` 七个命令模块（每个 ≤300 行，暴露 `add_subparser(sp)` / `handler(args)`）。

- **I0/I1 拆分**：旧文件备份为 `main.py.broken`；`main.py` 只保留三职责（argparse 注册 → `cli_gate` 校验 → handler 分发），命令模块为 `retail.py` / `research.py` / `checklist.py` / `factor.py` / `data.py` / `qi.py` / `derivatives.py` + 公共 `_common.py`；新增子命令只改对应模块，不再动 `main.py`。
- **I2 小步实施**：每加一个模块即跑 `python main.py <子命令> --help`，最后统一 `--help` 与全量回归；机械抽取（AST 按行区间切函数）替代手写长文本，避免再次写入损坏。
- **I3 控制平面**：① 旁路黑名单扩到 13 个（新增 `--force` / `--skip-freshness` / `--ignore-warmup` / `--disable-gate`），`new-strategy` 的覆盖参数改名 `--overwrite` 以让出 `--force`；② RUN_MODE 只允许降级，提升需「清单无 FAIL + `--confirm`」双门禁；③ 默认值全部经 `cli_gate.cli_default()`；④ `--data/--csv/--from-file` 统一走 `data.data_import` 三物化列校验；⑤ checklist 输出「通过/警告/不通过/不适用」四类计数，并补「已跑/未跑/跳过/失败」口径对照。
- **I4 config 增量**：`CLI_CONFORMANCE` 追加 `thin_entry=True` / `max_entry_lines=300` / `command_modules_dir="cli_commands"`（另加 `mode_may_only_downgrade=True` 显式声明阶梯方向），其余键值保持不变。
- **测试与验证**：`tests/test_entry.py` 由 37 项扩到 **54 项**（新增薄入口行数上限、模块接口、13 个禁参、三别名、checklist 四类计数、set-mode 提升被拒）；24 个子命令 `--help` 全通过；`python -m pytest tests/ -q` **203 passed / 0 failed / 0 skipped / 0 收集错误**。

#### 上一版（已被本版取代，保留以备追溯）

- **11.0 控制平面**：一键入口是控制平面而非一组脚本——① 旁路开关黑名单在 `guard_argv` argv 层直接抛 `BypassFlagError`，`assert_no_bypass_registration` 审计 argparse 注册面；② `RUN_MODE` 阶梯只允许降级，提升必须「上线检查清单无 FAIL + `--confirm` 显式确认」双门禁；③ 子命令默认值单一事实源 `CLI_CONFORMANCE['cli_defaults']`。
- **--data 数据层出口**：`data/data_import.py` 的 `import_local_frame/import_local_fetcher` 统一导入（CSV/Parquet/Excel，中文列名兼容），物化 `warmup_ok` / `data_asof_date` / `price_adjust` 三物化列；缺列或含 NaN 一律 fail-closed；`LocalDataFetcher` 供 `run_backtest/run_paper` 注入（分钟线不支持，显式报错）。
- **README**：新增「实盘对接指引（按状态分节）」与「未实现能力」小节（第 12/13 步全部未开始、不计入完成百分比）。

### 2026-11-12 · 第 10 步：净值型产品数据层 + FOF/三层净值 + 场外衍生品定价 + 盯盘提醒

> 状态：第 9 步 **维持已完成**；第 10 步 **已完成**（`next_step=11`，`progress.json` v3.15）。新增
> [fetcher_nav.py](file:///Users/xuehairong/CodeBuddy/DaA/data/fetcher_nav.py)、
> [fof.py](file:///Users/xuehairong/CodeBuddy/DaA/nav_backtest/fof.py)、
> [strategies/](file:///Users/xuehairong/CodeBuddy/DaA/nav_backtest/strategies)、
> [derivatives_pricing/](file:///Users/xuehairong/CodeBuddy/DaA/derivatives_pricing)、
> [qi_monitor.py](file:///Users/xuehairong/CodeBuddy/DaA/core/qi_monitor.py)、
> [qi.html](file:///Users/xuehairong/CodeBuddy/DaA/templates/qi.html) 与 5 个 pytest 套件
> [test_qi_check.py](file:///Users/xuehairong/CodeBuddy/DaA/tests/test_qi_check.py) /
> [test_nav_data.py](file:///Users/xuehairong/CodeBuddy/DaA/tests/test_nav_data.py) /
> [test_nav_backtest.py](file:///Users/xuehairong/CodeBuddy/DaA/tests/test_nav_backtest.py) /
> [test_pricing.py](file:///Users/xuehairong/CodeBuddy/DaA/tests/test_pricing.py) /
> [test_qi_monitor.py](file:///Users/xuehairong/CodeBuddy/DaA/tests/test_qi_monitor.py)。

- **10.1 每个动作都是闸门**：`QIChecker.check_action()` 对 `subscribe / transfer / additional_subscribe / nominee_change` 逐次重校验，首次通过不授予后续动作；非法人载体必须给 `ultimate_investors` 逐个校验并合并人数（缺穿透 `look_through_missing`、有不合格 `look_through_ineligible`）；`pooled / is_nominee / split_units / borrowed_name / 非自有资金` 直接拒绝；`on_fail="reject"` 抛 `QualifiedInvestorRejected`，通过/拒绝均写 JSONL 审计，写失败按 fail-closed 抛错。三套门槛不混用：私募 300 万 / 资管家庭金融资产 500 万且起投 30/40/100 万 / 信托未配机构门槛即拒。
- **10.2 净值数据层**：`detect_frequency()` 按相邻披露间隔中位数判定 daily/weekly/monthly；`normalize_nav_frame()` 统一为 `date|nav|accum_nav|source` 并写 `attrs["frequency"]`、`attrs["disclosure_lag_days"]`；空表、缺列、净值全无效一律抛 `NavDataUnavailableError`（禁止静默空表）。`NavFetcher._call_source()` 是唯一出网出口（≥0.3s 限速 + 重试 + 来源标识）；缓存 `data_cache/nav/{market}_{code}[_{freq}].csv`；私募/资管/信托无公开净值时走 `manual_nav_import()`，`fetch_qii_product_nav()` 无 CSV 直接报错。REITs 合并行情与净值指标、折溢价率缺失置 NaN 并标 `premium_missing`；新三板过滤零成交、标退市风险、`volume_unit="股"`。
- **10.3 三层净值 + FOF**：`product_gross → product_net（管理费 1.5% + 托管费 0.2% 逐日计提）→ investor_net（申赎费 + 逐投资者高水位 carry 20%）`；对外披露固定 `investor_net`，`reconcile()` 用 `investor_net × units` 与逐户权益对账。开放日 = 净值披露日；锁定期私募/信托 180 天、资管 90 天；赎回款 T+3 到账，`pending_settlement()` 在途款不可再投资。FOF 决策帧严格按 `day - lag` 截断、下一净值日执行、先卖后买、锁定期内卖出记 `sell_blocked_lockup`；`assert_decision_after_disclosure()` 违反抛 `DisclosureLagError`，`to_kline()` 抛 `NavAsKlineError`。
- **10.4 场外衍生品（仅模拟）**：BS / 蒙特卡洛 / CRR 二叉树、雪球敲入敲出蒙特卡洛、TRS 保证金与强平、情景分析与 VaR。包级 `LIVE_TRADING_FORBIDDEN=True`、`ORDER_CHANNELS=()`、导入即打印「个人禁止实盘」红色 5 行警告、`assert_no_order_channel()` 审计，不导出任何下单/通道函数。
- **10.5 提醒 ≠ 拦截 + 第四出口**：`core/qi_monitor.py` 的 8 类提醒全部登记 `SIGNAL_EGRESS_CONFORMANCE["alert_types"]`，未登记类型 `send_qi_alert()` 直接 `ValueError` 拒发，正文统一附「提醒不等于拦截」；`qi_threshold_check` 资产缩水只提醒，后续申购仍被动作闸门拒绝。`Reporter.generate_qi_report()` + `qi.html`：固定 `investor_net`、五类费用、业绩报酬计提明细、FOF 权重/锁定期分布、REITs/新三板/衍生品模拟页（明示不下单、不对接渠道、不生成实盘信号）、被抑信号、QI 审计、`data_asof` 与完整区间断言、禁「保本/保收益/零风险」。
- **config 增量合并**：`NAV_PRODUCT_CONFIG` 增 `enforce_open_day` / `lockup_days` / `rebalance_frequency`；新增 `QI_MONITOR_ALERTS` / `QI_REITS_PREMIUM_THRESHOLDS` / `QI_NEEQ_ZERO_VOLUME_DAYS`，并把提醒类型并入 `alert_types`。
- **测试四类计数**：`pytest tests` → **149 passed / 0 failed / 0 skipped / 0 收集错误**（新增 5 套 75 项）；根目录 9 套脚本测试（account 49、chan 32、chart 19、data 全部通过、env 75、export 11、indicators 80、paper_trade 31、pattern 14）无回归。**未提交 GitHub。**

### 2026-11-12 · 第 10 步开工前置：合格投资者逐动作闸门 + 三层净值 + 披露滞后闸门 + 第四出口

> 状态：第 9 步 **维持已完成**；第 10 步 **开工前置已完成（进行中）**（`next_step=10`，`progress.json` v3.14）。新增
> [qualified_investor.py](file:///Users/xuehairong/CodeBuddy/DaA/core/qualified_investor.py)、
> [nav_backtester.py](file:///Users/xuehairong/CodeBuddy/DaA/nav_backtest/nav_backtester.py)、
> [disclosure.html](file:///Users/xuehairong/CodeBuddy/DaA/templates/disclosure.html) 与
> [test_qualified_investor.py](file:///Users/xuehairong/CodeBuddy/DaA/tests/test_qualified_investor.py) /
> [test_nav_layers.py](file:///Users/xuehairong/CodeBuddy/DaA/tests/test_nav_layers.py) /
> [test_disclosure.py](file:///Users/xuehairong/CodeBuddy/DaA/tests/test_disclosure.py)；
> [reporter.py](file:///Users/xuehairong/CodeBuddy/DaA/core/reporter.py) 新增 `generate_investor_disclosure()`；
> [config.py](file:///Users/xuehairong/CodeBuddy/DaA/config.py) 增量合并三个顶层常量与第四出口。

- **G0 欠账逐条核查**：E1 `core/execution.py` 已有 `match_price_basis()` / `match_price_basis_meta()` / `assert_fill_after_signal()` / `LookaheadError`，回测与账户经 `deferred_executor` 在 `next_open` 下 t 决策 t+1 成交、`same_open` / `same_close` 同根撮合直接抛错（`test_match_price_basis` 18/18）；E4 `tests/test_export.py` 已用 `tempfile.mkdtemp()` 独立目录，运行幂等；E5 B3 `signal_gate.align_frames` 按 symbol 逐帧保留三个物化列，B4 期权 IV 二分无解返回 NaN 且 `iv_solved=False`，`place_order` 开仓校验 `warmup_ok`（平仓豁免），`INDICATOR_WARMUP_GUARD` / `OPTION_VALUATION_GUARD` 已在 config。
- **G1 合格投资者是「每个动作的闸门」**：`QIChecker.check_action()` 覆盖 `subscribe / transfer / additional_subscribe / nominee_change`，每次都重新评估、绝不复用旧结论；非法人载体（合伙/契约/信托/SPV 等）必须给出 `ultimate_investors` 并逐个校验、去重合并人数，缺穿透即 `look_through_missing` 拒绝；`pooled / is_nominee / split_units / 非自有资金` 直接拒（禁拼单/代持/拆分/借名）。`on_fail="reject"` 下不过即抛 `QualifiedInvestorRejected`（**不是** `(bool, reason)`）；每次校验追加 JSONL 审计，审计写失败按 fail-closed 抛 `AuditLogError`。`qi_threshold_check()` 只产生提醒（文案明示「提醒不等于拦截」），资产缩水后真正拦住后续申购的是动作闸门。三套门槛独立：信托未配置机构门槛时直接拒绝，绝不套用私募/资管标准。
- **G1 口径更正**：`check_proposed_2026_rule()` 区分「已发布待施行」（《资产管理信托管理办法》2026-10-30 发布 / 2027-01-01 施行，生效后 `max_investors=200`、`recheck_on=[buy, transfer]`）与「征求意见稿」（《私募投资基金监督管理办法》），全程不再笼统写「未生效」。
- **G2 三层净值不得美容**：`NavBacktester` 产出 `product_gross`（毛）→ `product_net`（扣管理费 1.5% + 托管费 0.2%，按日计提并记金额）→ `investor_net`（再扣申赎费与**逐投资者**高水位 carry）；`carry_is_per_investor=True`，不同申购时点对应不同 HWM。`NAV_PRODUCT_CONFIG["disclosure_layer"]="investor_net"` 为强制披露层，报告「组合净值曲线」只画投资者费后净值；`NavResult.performance_fees` 列业绩报酬计提明细，`reconcile()` 用 `investor_net × units` 与逐户权益对账（实测 diff=0）。
- **G3 披露滞后＝结构性未来函数**：`assert_decision_after_disclosure()` 强制 `decision_date >= 净值日 + disclosure_lag_days`（私募/资管/信托 2 天、REITs 1 天），违反抛 `DisclosureLagError`；`latest_disclosed()` / `disclosure_view()` 只暴露已披露区间并写 `data_asof_date`；`to_kline()` / `assert_not_kline()` 对 `nav_only_markets` 抛 `NavAsKlineError`（净值序列禁用 K 线类指标）。
- **G4 对外披露是第四个输出口**：`SIGNAL_EGRESS_CONFORMANCE["signal_egress_points"]` 扩为 `["place_order", "monitor_push", "report_plan", "investor_disclosure"]`；`reporter.generate_investor_disclosure()` 硬校验：同源引擎、五类费用明细（申购/赎回/管理/业绩报酬/托管）、被抑信号逐条、`RUN_MODE` 类型标注（回测/模拟/实盘）、六条风险揭示、`data_asof` 与完整区间（禁选择性区间）、禁「保本/保收益/零风险」字样、QI 审计留痕；`_auto_send_disclosure()` 发送前过披露滞后闸门，停更/超限只发「披露未发送」告警。
- **config 增量合并**：`QUALIFIED_INVESTOR_RULES`（三套门槛 + 四动作 + 穿透 + fail-closed + 审计 + 2026 状态）、`NAV_PRODUCT_CONFIG`（三层/披露层/频率/滞后/费用/结算天数/禁 K 线）、`DISCLOSURE_CONFORMANCE`（费用五类/抑信号/类型标注/禁选择性区间/禁保本/风险揭示/QI 审计）三个顶层常量置于「运行模式」段之前；未整文件覆盖。
- **实测**：`pytest tests` → **74 passed / 0 failed / 0 skipped / 0 收集错误**（新增 qualified_investor 17 + nav_layers 9 + disclosure 5）；根目录 9 套脚本测试全通过。**未提交 GitHub。**

### 2026-11-12 · 第 9 步：自动复盘报告生成（`core/reporter.py` + `templates/`）

> 状态：第 8 步 **维持已完成**；第 9 步 **已完成**（`next_step=10`，`progress.json` v3.13）。新增
> [reporter.py](file:///Users/xuehairong/CodeBuddy/DaA/core/reporter.py)、
> [test_reporter.py](file:///Users/xuehairong/CodeBuddy/DaA/tests/test_reporter.py)（pytest **15/15**）与
> [templates/](file:///Users/xuehairong/CodeBuddy/DaA/templates)（`base.html` / `_macros.html` /
> `daily.html` / `period.html` / `backtest.html`）；
> 闸门唯一实现仍在 [signal_gate.py](file:///Users/xuehairong/CodeBuddy/DaA/core/signal_gate.py)。

- **报告只做汇总，不另算一套**：信号/成交/持仓全部同源读取 `account.trades`、`account.rejected_orders`、`paper_trader.bills`、`signal_gate.decision_log()`；Reporter 不重跑策略、不重新撮合。绩效数字优先取 `BacktestResult.metrics`，模拟盘场景复用引擎 `calc_metrics`，禁止自算第二份。
- **必须披露被拦掉的信号**（`REPORT_CONFORMANCE["must_report_suppression"]`）：`collect_suppressions()` 合并订单拒单与裁决日志并按 `reject_id` 去重，逐项计数 `warmup / stale / off_session / limit_up_down / volume_limit / risk_block`；`zero_trade_disclosure=True` 时「0 笔交易」拆成「策略无信号 0 笔 + 闸门拦截 N 笔（逐原因）」，避免 fail-closed 锁死与零成交在报告里隐形。
- **明日候选 = 新登记的信号出口 `report_plan`**：`config.SIGNAL_EGRESS_CONFORMANCE["signal_egress_points"]` 已扩为 `["place_order", "monitor_push", "report_plan"]`。`build_plan()` 只调用 `signal_gate.check_plan_candidate()`，预热期 / 停更 / 非交易时段默认排除（显式标注「预热期，仅供观察」「数据存疑，仅供观察」「非交易时段，已排除」），通过者带 `data_asof_date`。
- **自动发送过时效闸门**：`auto_send_requires_fresh=True` 时，`_auto_send` 先查数据截至日期与交易日数差，超 `STALE_LIMIT["daily"]` 只推「报告未发送：数据停更/超限」告警，不推送交易内容。
- **F0 流程补正**：`tests/test_factor.py` 5 个 `fixture 'd' not found` 收集错误已修（新增 module 级 `d` fixture），`check()` 失败改为立即 `raise AssertionError`，pytest 收集 0 错误。
- **四类报告齐全**：`generate_daily_report()` 覆盖九大板块（账户概览 / 持仓明细含当日涨跌 / 当日交易 / 分市场盈亏 / 风控检查 / 信号汇总 / 明日计划 / 市场情绪 / 绩效指标）；`generate_weekly_report()` / `generate_monthly_report()` 走同一 `_generate_period()`，额外给交易盈亏分布、最大盈利 / 最大亏损交易复盘、策略参数评估；`generate_backtest_report()` 给策略参数、全部绩效、分年度收益、交易 CSV 与回撤曲线。
- **格式按 9.5 落地**：Jinja2 模板继承（`base.html` + `_macros.html`）渲染单文件 HTML，CSS 内联；图表优先 plotly 交互图（默认 `include_plotlyjs="cdn"` 保持邮件体积友好，`embed_plotly_js=True` 才内联约 5MB 自包含），plotly 缺失自动降级 matplotlib（`Agg` + base64 PNG）；PDF 需 `wkhtmltopdf` + `pdfkit`，缺失只打 WARNING 并返回 `None`，不影响 HTML 落盘。
- **测试 15 项**：除报告生成外，三条 9.0 硬断言独立成例——`test_suppression_disclosure`（7 笔逐类可见 + HTML token）、`test_plan_excludes_warmup_stale_off_session`（预热 / 停更 / 非时段全部排除并标注）、`test_metrics_share_engine_source`（`metrics()` 直接等于 `result.metrics`）；另有 0 笔拆解、三物化列缺失、自动发送过时效、九板块、情绪显式不可用、周报 / 月报 / 回测专项、Jinja2 渲染、PDF 降级。
- **顺带修复**：`core/backtester.py::_trade_stats` 在 trades 缺 `pnl` / `commission` / `action` 列时 `pd.to_numeric(df.get(...))` 返回标量导致 `AttributeError`，改为先补列再转换（报告复用 `calc_metrics` 的路径依赖它）。
- **实测**：`pytest tests` → **43 passed / 0 failed / 0 skipped / 0 收集错误**（alpha101 2 + factor 6 + loader 4 + monitor 16 + reporter 15）；脚本式 20 套共 **583 项**全过（tests/ 11 套 238 项 + 根目录 9 套 345 项）。
- **未提交 GitHub。**

### 2026-11-12 · 第 8 步：定时盯盘与消息推送（`core/monitor.py` / `core/notifier.py`）

> 状态：第 8 步 **已完成**（`next_step=9`，`progress.json` v3.11）。新增
> [monitor.py](file:///Users/xuehairong/CodeBuddy/DaA/core/monitor.py)、
> [notifier.py](file:///Users/xuehairong/CodeBuddy/DaA/core/notifier.py)、
> [test_monitor.py](file:///Users/xuehairong/CodeBuddy/DaA/tests/test_monitor.py)（pytest **16/16**）；
> 闸门唯一实现仍在 [signal_gate.py](file:///Users/xuehairong/CodeBuddy/DaA/core/signal_gate.py)。

- **8.0 盯盘是第二个信号出口**：信号出口收口为 `place_order` 与 `monitor_push`。Monitor 一律用 `signal_gate.build_bar` 构建 bar，再由 `signal_gate.assert_tick_bars`（唯一实现，monitor 只调用）校验三物化列 `warmup_ok / data_asof_date / price_adjust`，缺列或 NaN 直接 `ValueError`；禁止把 `data_fetcher` 裸行情直接喂 `on_tick`。
- **闸门只调用不重写**：开仓/加仓裁决调 `signal_gate.check_order`（开严平宽：`warmup_ok=False` 的开仓信号只推拦截提醒、不推可执行信号；平仓/减仓/风控提醒放行）；推送前过时效闸门 `assert_fresh_for_trading`（与第 4 步 refetch 同源，`for_trading=True`、`order_side=open`），停更/超限只推「数据异常」告警且不喂策略。
- **逐市场时段**：`is_in_session` = 市场时区 + `utils.is_trading_day` 交易日历 + `config.get_market_config` 的 `trading_hours`（含 `night_session` 夜盘）分钟段；A股 09:30–11:30 / 13:00–15:00、港股、美股 `America/New_York`（夏令时自动）、国内期货含 21:00–23:00 夜盘、加密/外汇 `always`。非交易时段直接跳过，不拉数、不喂策略、不推交易信号。
- **推送标注**：交易信号与数据告警统一带「预热闸门 / 数据截至 / 新鲜度」，数据截至日期取该帧最后一根 bar（优先物化列，禁止用取数时刻）。
- **notifier 多渠道**：`BaseNotifier.send(title, content, level)` 统一入口 + Console/Log 默认开启 + 企业微信/钉钉/邮件/Bark 按凭证启用，`create_notifiers()` 统一装配；每渠道 **10 分钟去重**（`DEDUP_WINDOW_SECONDS=600`）+ **5 条/分钟限流**（`RATE_LIMIT_MAX=5`），渠道异常只记日志，绝不打断盯盘主循环。
- **monitor 调度**：`MONITOR_EVENTS` 事件清单（策略信号、价格/持仓 ±5%、20 日新高新低、量能 2 倍、止损止盈、数据停更、逆回购、日历已实现；开盘收盘/回撤/集中度/心跳登记为待接入）；同标的拉数最小间隔 + 连续 5 次失败熔断 10 分钟（防封 IP）；APScheduler 多市场 interval 调度，`Ctrl+C` 优雅退出并 `save_account()`；支持 `nohup` / `pm2` / `systemd` 后台常驻。
- **实测（贴原文）**：`tests/test_monitor.py` → `16 passed`；`test_signal_gate 通过 25 / 失败 0`、`test_strategy 通过 18 / 失败 0`、`test_backtest 通过 28 / 失败 0`、`test_engine_consistency 通过 16 / 失败 0`、`test_match_price_basis 通过 18 / 失败 0`。
- **未提交 GitHub。**



### 2026-11-12 · E1–E5：撮合时点参数化 + 未来函数强制断言（step7 维持已完成）

> 状态：第 7 步维持 **已完成**（`next_step=8`）。新增
> [test_match_price_basis.py](file:///Users/xuehairong/CodeBuddy/DaA/tests/test_match_price_basis.py)（**18/18**）；
> 改动 [execution.py](file:///Users/xuehairong/CodeBuddy/DaA/core/execution.py)、
> [account.py](file:///Users/xuehairong/CodeBuddy/DaA/core/account.py)、
> [backtester.py](file:///Users/xuehairong/CodeBuddy/DaA/core/backtester.py)、
> [paper_trader.py](file:///Users/xuehairong/CodeBuddy/DaA/core/paper_trader.py) 与 [config.py](file:///Users/xuehairong/CodeBuddy/DaA/config.py)。

- **E1 撮合价基准参数化**：`config.EXECUTION_MODEL["match_price_basis"]="next_open"` 为唯一参数源，`match_price_basis_meta` 声明四档取值的 `price` / `bar_offset` / `lookahead_safe`；`ExecutionModel` 不再写死开盘价，市价成交价读 `self.price_field`（open / close）。
- **E1 延迟撮合**：`next_*`（`bar_offset=1`）时引擎注入 `account.deferred_executor`，`place_order` 把订单入队并返回 `status="pending"`，下一根 bar 以 `fill_now=True` 重跑完整校验链（方向/预热/T+1/整手/涨跌停/时效/成交模型）后成交。不依赖成交价的校验全部前置到排队之前，因此「预热期、T+1 冻结、无持仓」的拒单仍在信号当根返回。
- **E1 未来函数硬断言**：`core/execution.py::assert_fill_after_signal(signal_bar_index, fill_bar_index)` —— `earliest = signal + max(bar_offset, 1)`，违反即抛 `LookaheadError`；`place_order` 捕获后**重新抛出**（不降级为普通拒单）。`same_open` / `same_close` 的 `bar_offset=0` 只表示「基准价字段取当根」，同根成交一律报错。`enforce_fill_after_signal=False` 时降为 WARNING，仅用于对照实验。
- **实测（贴原文）**：`端到端 next_open：信号当根返回 pending（不立即成交） | status=pending`、`成交 bar = 决策 bar 的下一根 | 决策 2026-03-05 → 成交 2026-03-06`、`成交价 = 下一根开盘价 × (1+滑点) | fill=101.2920 expected=101.2920`、`未回填决策当根开盘价 | 若用当根会得到 101.7608`；`端到端 same_open：同根撮合抛 LookaheadError（不降级为拒单） | 未来函数：决策 bar#19 → 成交 bar#19（基准 same_open，要求 fill >= 20）`。
- **E2 / E3 记入下一轮**：第 8 步盯盘是「第二个信号出口」，`config.SIGNAL_EGRESS_CONFORMANCE` 已先落常量（`signal_egress_points=["place_order","monitor_push"]`、`must_call_gate="core/signal_gate.py"`、`monitor_must_inject_columns=["warmup_ok","data_asof_date","price_adjust"]`、`forbid_bare_on_tick` / `push_requires_fresh` / `session_check_per_market` / `push_must_tag_gated` 全 True）；逐市场盯盘时段表同样在第 8 步实现，本轮不写 `core/monitor.py`。
- **E4 test_export 幂等**：`EXPORT_DIR = Path(tempfile.mkdtemp(prefix="dda_export_"))`，每次运行独立临时目录。连续两次执行均为 `通过 11 项，失败 0 项`。
- **E5 欠账回执**：B3 `price_adjust` 按 symbol 分组保留（`signal_gate.align_frames` 返回逐标的分组帧，不 concat）+ 混合口径 fail-closed（`indicators.resolve_adjust` 遇帧内多口径直接 `ValueError`）；B4 `IMPLIED_VOL` 无解返回 `NaN` 且 `iv_solved=False`（`on_no_solution="nan"`，禁止返回二分下界）；`place_order` 预热闸门联动在 `core/account.py`（开仓缺 `warmup_ok` 或 False → 拒单，`sell/cover` 豁免）；`INDICATOR_WARMUP_GUARD` / `OPTION_VALUATION_GUARD` 均已在 `config.py`。
- **config 增量合并（非整文件覆盖）**：`EXECUTION_MODEL` 的 `known_simplifications` 之后新增 `match_price_basis` / `match_price_basis_meta` / `enforce_fill_after_signal`；`ENGINE_CONFORMANCE` 之后新增顶层 `SIGNAL_EGRESS_CONFORMANCE`。
- **版本自检（如实回执）**：本工作区指令集顶部为 **`> **版本 v3.3**`**（`Trae多市场量化系统搭建指令集-2.md`，mtime 10-27 16:07；`~/Downloads/` 同名副本完全一致，sha 级同大小 139232 字节）。按【章节标题】核对：`## ===== 第 6 步：全市场透明回测引擎 =====` → `## ===== 第 7 步：模拟盘交易 =====`（正文为 `PaperTrader` 七项要求）→ `## ===== 第 8 步：定时盯盘与消息推送 =====`。**未找到 v3.26**，故未声称审过 v3.26；E1 按任务书给出的明确规格落地。
- **回归**：test_match_price_basis 18/18、test_backtest 28/28、test_engine_consistency 16/16、test_signal_gate 25/25、test_paper_trade 31/31、test_strategy 18/18、test_loader 20/20、test_research 19/19、test_account 49/49、test_indicators 80/80、test_env 75/75、test_data 全通过、test_chan 32/32、test_chart 19/19、test_pattern 14/14、test_factor 58/58、test_alpha101 10/10、test_custom_factor 12/12、test_factor_strategy 14/14、test_export 11/11（连续两次）。未提交 GitHub。

### 2026-11-05 · 第 7 步：模拟盘交易 `core/paper_trader.py`

> 状态：第 7 步 **已完成**（`next_step=8`）。交付
> [paper_trader.py](file:///Users/xuehairong/CodeBuddy/DaA/core/paper_trader.py)、
> [test_paper_trade.py](file:///Users/xuehairong/CodeBuddy/DaA/test_paper_trade.py)（**31/31**）；
> 前置已交付 [execution.py](file:///Users/xuehairong/CodeBuddy/DaA/core/execution.py)、
> [risk.py](file:///Users/xuehairong/CodeBuddy/DaA/core/risk.py)、
> [test_engine_consistency.py](file:///Users/xuehairong/CodeBuddy/DaA/tests/test_engine_consistency.py)（**16/16**）。

- **7.0 闸门有源（不重写）**：`PaperTrader._dispatch()` 先 `signal_gate.assert_bar_dict()` 校验 `warmup_ok` / `data_asof_date` / `price_adjust` 三列（缺失或 NaN 直接 `ValueError`），再交给父类主循环；开仓经 `place_order` 预热闸门（`warmup_ok=True` 才放行）、平仓 `sell/cover` 豁免；末根 bar 仍处预热期时打 WARNING 并不出信号。实测：预热期 125 次开仓尝试 0 成交，`_dispatch` 缺 `warmup_ok` 抛错，最后一根 warmup 帧无信号。
- **成交与风控同源**：挂单/条件单触发后统一走 `TradingAccount.place_order`，滑点 = `EXECUTION_MODEL["slippage_base_pct"]=0.0005 × slippage_multiplier["paper"]=2.0`（实测 0.001），涨跌停/量限（按市场分档）/手续费/T+1/数据时效闸门全部继承回测实现；风控统一 `core/risk.py`，参数源 `config.RISK`。模拟盘**不新增**任何撮合或风控代码。
- **运行入口**：`run_daily(at=None, last_n_bars=None)`（先置 `period="1d"`，非交易日按 `is_trading_day` 直接返回空结果）、`run_intraday(interval_minutes=5, at=None, last_n_bars=None)`（`period="5min"`，分钟线周期归一化 `"5min"→"5"` 且不传 `adjust`）、`_run_window` → `run()`（先 `_trim_to_trade_days`、后复跑主循环、末尾 `save_account`）。
- **只交易最近 N 根但预热用全量**：`last_n_bars=10` 时 `self.dates` 裁到最近 10 根，`_history_bars` 保留裁剪前全量用于长度门槛，`_seen_seed` 按「cutoff 之前的 bar 数」逐标的播种，因此窗口首根即已预热、不会整段零成交。`Backtester` 为此只新增三个引擎中性钩子 `_initial_seen` / `_bar_count_for_gate` / `_after_bar`，闸门/成交/风控逻辑零改动。
- **订单管理**：`submit_order`（方向/类型/条件/数量/限价/触发价/`trail_pct` 全量校验）→ `cancel_order` → `modify_order`；条件单 `stop_loss_order` / `take_profit_order` / `trailing_stop_order`（`stop` 买方向 `high>=trigger`、卖方向 `low<=trigger`，`take_profit` 反向，`trailing_stop` 以 `peak_price` 跟踪）；`expire=day` 未成交单日终自动撤销、`gtc` 与平仓类条件单保留；`rebalance(targets)` 按 delta 先卖后买。平仓单在无可用持仓（T+1 冻结）时保持 pending，不产生拒单噪声。
- **记录与对账**：逐笔成交日志、每日账单 `self.bills`（date / equity / cash / margin_used / positions / fill_count / commission）、`reconcile(cash, positions, note)` 手动对账并留档 `recon_log`。
- **持久化**：`data_cache/paper_account.json` 存现金 / 保证金 / 持仓 / 未成交挂单 / `initial_capital` / `period`；`_position_obj` 用 `_POSITION_FIELDS` 白名单还原 `Position`，日期字段统一走 `_DATE_FIELDS`。实测中断重启后持仓 `{'600519': 100.0}`、现金 858375.13、gtc 挂单全部还在。
- **偏差告警（仅三板斧共用时有效）**：`compare_with_backtest(reference=None, warn_pct=None)` 读 `ENGINE_CONFORMANCE["divergence_warn_pct"]=0.05`，`reference=None` 时用同参 `Backtester(liquidate_at_end=False)` 自动跑对照，输出 `paper_equity / backtest_equity / deviation_pct / warned / drivers / message`。实测同滑点偏差 **0.00e+00**（证明共用生效）、2 倍滑点 **-0.1738%** 且归因到滑点与成交价差（未超 5% 阈值故不告警）。
- **数据时效闸门照常生效**：`_process_pending` 调 `account.place_order(..., data=self.frames.get(symbol), for_trading=True, warmup_ok=warmup_ok)`，paper 模式强制 refetch 复核，模拟盘不为「跑出成交」绕过。
- **测试覆盖（31 项）**：双均线跑最近 10 个交易日（nav 10 行、2 笔成交、费用 142.17、10 张账单、账户落盘、滑点 0.001、`ExecutionModel` 同一实现、order_id 齐全、`config.RISK` 参数源）；预热期 125 次尝试 0 成交 + 缺 `warmup_ok` 抛错；持久化重启；条件单止损成交 @92.907 且持仓归零；挂/改/撤/非法委托/一篮子调仓；对账（现金 +5000、持仓改 300、`recon_log` 2 条）；偏差（同滑点 0.00e+00 不告警、2 倍滑点 -0.1738% 告警、归因线索、自动跑对照）；非交易日 `2026-11-07`（周六）跳过且 `run_intraday` 同样跳过并置 `period="5min"`。
- **回归**：test_paper_trade 31/31、test_engine_consistency 16/16、test_backtest 28/28、test_signal_gate 25/25、test_strategy 18/18、test_account 49/49、test_export 11/11、test_loader 20/20、test_research 19/19、test_indicators 80/80、test_factor 58/58、test_alpha101 10/10、test_custom_factor 12/12、test_factor_strategy 14/14、test_chan 32/32、test_chart 19/19、test_pattern 14/14。未提交 GitHub。

### 2026-11-05 · 第 7 步开工前置：闸门/成交/风控三引擎共用（D1–D6）

> 状态：第 6 步维持 **已完成**；第 7 步正文待执行（`next_step=7`）。新增
> [execution.py](file:///Users/xuehairong/CodeBuddy/DaA/core/execution.py)、
> [risk.py](file:///Users/xuehairong/CodeBuddy/DaA/core/risk.py)、
> [paper_trader.py](file:///Users/xuehairong/CodeBuddy/DaA/core/paper_trader.py)、
> [test_engine_consistency.py](file:///Users/xuehairong/CodeBuddy/DaA/tests/test_engine_consistency.py)（**16/16**）。

- **D1 闸门有源**：`PaperTrader` 复用 `signal_gate.build_bar_dict()` 逐根写 `warmup_ok`，`assert_bar_dict()` 缺列/NaN 直接报错；开仓过 `place_order` 预热闸门、平仓豁免；末根 bar 仍在预热期时不出信号。实测：预热期 + `fillna(0)` 帧在模拟盘 125 次开仓尝试全部被拒，首笔成交落在第 126 根 bar。
- **D2 成交模型单份实现**：滑点/涨跌停/量限/限价撮合抽到 `core/execution.py`，回测与模拟盘只调用不重写；环境差异只参数化——`EXECUTION_MODEL["slippage_multiplier"]` 回测 1.0 / 模拟盘 2.0 / 实盘 2.0，模拟盘默认滑点实测 0.001（=0.0005×2）。
- **D3 风控单份实现**：单票上限、总杠杆、日内亏损上限、最大回撤熔断、黑天鹅保护、止损/止盈抽到 `core/risk.py`，`BaseStrategy` 改为委托 `risk_manager`，`config.RISK` 为唯一参数源；回测与模拟盘结果从此可比。
- **D4 已知简化入配置**：四项简化写入 `EXECUTION_MODEL["known_simplifications"]`，偏差方向写入 `bias_direction`；量限改为按市场分档 `volume_limit_pct_by_market`（cn_stock 1%、cn_etf 2%、cn_convertible 0.5%、cn_future 2%、基金/逆回购 None）。
- **D5 三引擎一致性**：同一行情 + 策略 + 初始资金，相同滑点下回测与模拟盘逐笔成交（24 笔）与末值权益完全一致；默认参数下差异仅来自滑点倍数（模拟盘买入价 1709.8038 > 回测 1708.9497）。测试先断言 `must_share` 三模块真实存在且 `backtester`/`paper_trader` 未重新定义 `ExecutionModel`/`RiskManager`。
- **D6 上轮欠账核查**：B3（`price_adjust` 按 symbol 分组、混合口径 fail-closed）、B4（IV 无解返回 NaN + `iv_solved=False`）、`place_order` 预热联动（开仓拒/平仓放行）、`INDICATOR_WARMUP_GUARD` / `OPTION_VALUATION_GUARD` 两常量均已落地，由 test_signal_gate / test_account / test_indicators 覆盖。
- **测试幂等**：`test_export.py` 改用 `tempfile.mkdtemp()` 独立目录，每次运行都重新下载，不再因缓存命中 `skip` 导致 CI 结果漂移。
- **回归**：test_engine_consistency 16/16、test_backtest 28/28、test_signal_gate 25/25、test_strategy 18/18、test_loader 20/20、test_research 19/19、test_account 49/49、test_indicators 80/80、test_factor 58/58、test_alpha101 10/10、test_custom_factor 12/12、test_factor_strategy 14/14、test_env 全过、test_chan 32/32、test_chart 19/19、test_pattern 14/14、test_export 11/11。未提交 GitHub。

### 2026-11-05 · 第 6 步：全市场透明回测引擎 `core/backtester.py`

> 状态：第 6 步 **已完成**（`next_step=7`）。交付 [backtester.py](file:///Users/xuehairong/CodeBuddy/DaA/core/backtester.py)、
> [test_backtest.py](file:///Users/xuehairong/CodeBuddy/DaA/tests/test_backtest.py)（**28/28**）与
> [signal_gate.py](file:///Users/xuehairong/CodeBuddy/DaA/core/signal_gate.py)（闸门唯一实现，引擎只调用不重写）。

- **6.0 闸门随引擎迁移**：逐日 `signal_gate.build_bar_dict()` 写入 `warmup_ok`（缺列/NaN 直接报错）；开仓 `buy`/`short` 在 `place_order` 过预热闸门、平仓 `sell`/`cover` 豁免；长度门槛 `signal_gate.ensure_min_bars() = max(60, strategy.required_bars())` 严格报错；多标的 `align_frames()` 逐标的保留 `data_asof_date` / `price_adjust` / `warmup_ok`。引擎一致性测试：同一份「预热期 + `fillna(0)`」帧在 `StrategyRunner` 与 `Backtester` 下 `buy()` 均被拒（各 125 次），首笔成交下标完全一致。
- **Backtester 主体**：初始化 → `prepare()`（取日线 → 列校验 → 未来函数检测 → 交易日交集对齐 → 流动性扫描 → 基准）→ `run()` 逐 K（`advance_seen` → `build_bar_dict` → `execution.set_context` → `dispatch_bar` → `check_margin_call` 统计爆仓 → 日终快照：市值/杠杆/保证金使用率）→ 收盘强平 → `BacktestResult`（nav/trades/metrics/benchmark/traps）。
- **写实成交模型 `ExecutionModel`**（仅回测挂载到 `account.execution_model`，实盘为 `None`）：市价买 = 开盘 ×(1+滑点)、卖 = 开盘 ×(1−滑点)；**开盘即涨停买不进 / 跌停卖不出**（复用 `TradingAccount.price_limit_pct`）；**单笔 ≤ 当日成交量 1%**（超出按最小交易单位截断，不足一步拒单）；限价单按当日高低区间撮合；**T+1 由 `TradingAccount` 执行**（实测当天买当天卖拒单「可卖 0 / 请求 100（T+1）」）；**费率全部走 `config` 真实费率**（A股买入 31.29 = 佣金+过户费；卖出 94.76 含印花税 0.05%），不设 0 手续费。
- **绩效指标 `calc_metrics()`**：收益（total/annual/benchmark/excess）、回撤（max/区间/持续天数）、风险（年化波动/下行风险）、风险调整（Sharpe/Sortino/Calmar/信息比率）、交易统计（笔数/胜率/盈亏比/平均持仓天数/最大连续亏损/总手续费）、**分市场 `by_market`**、**分多空 `by_direction`**；杠杆类输出 `avg/max_leverage`、`avg/max_margin_utilization`、`margin_calls`（爆仓次数）。
- **回测陷阱自动检测 `detect_traps()`**：未来函数（列名 `lead/next/future/fwd/shift` 或与次日收益相关性 > 0.9，`prepare()` 直接 `ValueError`）、幸存者偏差、过拟合（参数 ≥ 6 且交易 < 30）、流动性（日均成交额 < 500 万）、滑点（< 0.001）、量限截断与涨跌停拒单统计。
- **可视化与落盘**：4 子图（净值 vs 基准 / 回撤 / 月度收益 / 每笔平仓盈亏），杠杆品种另存 `_leverage.png`（保证金使用率 + 杠杆率）；`save()` 写 `{策略}_{时间戳}_trades.csv` / `_equity.csv` / `_metrics.json` / `.png`。
- **实测**：双均线 600519（bars=784、16 笔、total_return=0.2033）；海龟 RB2510（18 笔、多空双向、avg_leverage=0.2612、保证金 5180.01 = 成交价×乘数×手数×保证金率）；基金定投 161725（183 笔、全 cn_fund）；预热期拒绝 125 次、首笔开仓在第 126 根 bar；涨停/跌停/1% 量限/滑点/限价未触发/未来函数拒绝/长度门槛不足报错全部断言通过。
- **回归**：test_signal_gate 25/25、test_strategy 18/18、test_loader 20/20、test_research 19/19、test_account 49/49、test_indicators 80/80、test_factor 58/58、test_alpha101 10/10、test_custom_factor 12/12、test_factor_strategy 14/14、test_env 75/75、test_data 全过、test_chan 32/32、test_chart 19/19、test_pattern 14/14、test_export 11/11（清 `export/` 缓存后复跑；缓存命中会按设计 skip，属测试非幂等，非回归）。未提交 GitHub。
- **已知简化**：卖出滑点同样按开盘价计算（未区分盘中不同时点）；涨跌停只判「开盘即封板」，未模拟盘中反复开板；成交量上限按 1% 固定比例，未按市场/流动性分档；基金/逆回购走净值透传不参与撮合量限。

### 2026-10-31 · 第 6 步开工前置：闸门下沉 `core/signal_gate.py`（C1–C4）

> 上一轮「执行器会被替换、策略接口不变」暴露了交接洞：闸门若住在 `core/runner.py`，
> 第 6 步换成 `core/backtester.py` 后会**静默消失**——预热期 `fillna(0)` 的 RSI=0 会被读成
> 「极度超卖」并发买入，且不报错。本轮把闸门抽成**唯一实现**并补引擎一致性测试。

- **C1 闸门只允许一份实现**：新增引擎无关的 [signal_gate.py](file:///Users/xuehairong/CodeBuddy/DaA/core/signal_gate.py)，`core/strategy.py` 与 `core/runner.py` 改为**只调用不重写**：
  - `build_bar_dict()` 逐标的写入物化字段 `warmup_ok`；`assert_bar_dict()` 对缺列/NaN **直接报错**（执行器漏喂标记不再默认放行）；
  - `check_order()` 开仓严（`buy`/`short` 预热期拒单、`stage="warmup"`）、平仓宽（`sell`/`cover` 放行，止损/强平/到期结算不受限）；
  - `check_signal_frame()` 委托 `core/indicators.py` 的纯函数，拦截「预热掩码 False 行被 fillna/ffill/bfill/rolling(min_periods=1) 填过」；
  - 最终裁决仍收口在 [account.py](file:///Users/xuehairong/CodeBuddy/DaA/core/account.py) 的 `place_order(warmup_ok=...)`（与 stale 闸门同处，随引擎替换存活）。
- **C2 长度门槛不再是硬编码 60**：`min_backtest_bars() = max(60, strategy.required_bars())`。MACD 的 `required_bars=135`，固定 60 会让 60~70 根的标的通过检查后**全段落在预热期** → 闸门拦掉每一笔 → 回测静默零成交。`Backtester` 严格拒绝（`ensure_min_bars`），轻量 `StrategyRunner` 因被走向前/优化用短样本反复调用，只告警不中断。
- **C3 指令 A 欠账逐条核查并补测**：`config.INDICATOR_WARMUP_GUARD` / `OPTION_VALUATION_GUARD` 均已在 [config.py](file:///Users/xuehairong/CodeBuddy/DaA/config.py)；B3 混合复权口径帧算 ATR **fail-closed**；B4 期权 IV 无解返回 `NaN` 且 `iv_solved=False`；第 4 步 `place_order` 预热联动（开仓拒 / 平仓放行）实测通过。
- **C4 对齐时物化列存续**：`align_frames()` 取交易日交集后返回**逐标的分组**帧，`data_asof_date` / `price_adjust` / `warmup_ok` 按 symbol 保留原值，不因 concat/reindex 退化成一列一个值或整列广播。
- **config 增量新增**：`GATE_CONFORMANCE`（`gate_module` / `enforce_at` / `feed_warmup_ok_into` / `min_backtest_bars` / `preserve_columns_on_align`），插在 `OPTION_VALUATION_GUARD` 之后，未整文件覆盖。
- **新增 `core/backtester.py` 骨架**：取数 → `align_frames` → 长度门槛 → 逐日 `build_bar_dict`（带 `warmup_ok`）→ `dispatch_bar`，下单仍走 `place_order`。滑点/涨跌停/成交量限制/分市场绩效/图表与结果落盘在第 6 步正文补齐。
- **引擎一致性测试** [test_signal_gate.py](file:///Users/xuehairong/CodeBuddy/DaA/tests/test_signal_gate.py) **25/25**：同一份「预热期 bar + 已 `fillna(0)`」的帧，在轻量 runner 与 `Backtester` 下 `buy()` **都被拒单**；断言 `Backtester.last_bar_dict` 确实带 `warmup_ok`；两个引擎的拒单边界与首笔成交位置完全一致。
- **回归**：test_strategy 18/18、test_loader 20/20、test_research 19/19、test_account 49/49、test_indicators 80/80、test_factor 58/58、test_alpha101 10/10、test_custom_factor 12/12、test_factor_strategy 14/14、test_env 75/75、test_data 全过、test_chan 32/32、test_chart 19/19、test_pattern 14/14、test_export 11/11。未提交 GitHub，step5 维持「已完成」。

### 2026-10-31 · 第 5 步：策略研究模块（基类 + 四环境 + 研究流程 + 因子库 + 示例策略）

> 状态：第 5 步 **已完成**（`next_step=6`）。交付 `core/strategy.py`、`core/runner.py`、
> `core/strategy_loader.py`、`research/{optimizer,walkforward,validator,registry}.py`、
> `factor/` 全模块、`strategies/` 9 个示例策略、`configs/strategies/` 10 个 yaml、
> `tools/{new_strategy,strategy_checklist,new_factor}.py` 与 7 个测试文件。
> 本轮**未新增 config 常量**，全部复用已就位的 `INDICATOR_WARMUP_GUARD` / `RISK` / `STALE_*` / `get_market_config()`。

- **5.0 开工前置：两道闸门必须在信号入口真正生效**（本轮第一件事）
  - **预热闸门**：执行器逐 bar 向 `on_bar` 传入的 bar 注入物化字段 `warmup_ok`（该标的已见 bar 数 < `warmup_bars` 时为 `False`）。`buy()` / `short()` 内部**强制校验**，`warmup_ok=False` 或缺失时在策略层直接拒单（`stage="warmup"`），不进入账户层；`sell()` / `cover()` 放行——预热期也必须能止损/平仓（「开严平宽」）。
  - **get_history 长度闸门**：`get_history(symbol, n, indicator=...)` 在 `n < required_bars(indicator)` 时**抛 ValueError**（提示所需最少根数），否则返回完整序列并挂 `attrs["warmup_ok"]` / `attrs["rows"]`。
  - **fillna 泄漏拦截**：策略自拼指标帧必须过 `assert_signal_frame(df)`——缺 `warmup_ok` 列报错、掩码含 NaN 报错、预热掩码为 `False` 的行一旦出现非 NaN 指标值（`fillna/ffill/bfill/rolling(min_periods=1)` 填过）**立即报错**。
  - **末根闸门**：`paper/live` 下末根仍处预热期（`assert_last_bar_ready`）拒绝出信号，`backtest` 默认豁免。
  - **测试实证**：「预热期 + `fillna(0)` 的帧 → 策略 `buy()` 被拒单」；首笔成交必然发生在 `warmup_bars` 之后。
- **5.1 BaseStrategy 基类**：`init` / `on_bar` / `on_tick` / `on_end_of_day` + `buy` / `sell` / `short` / `cover` + `get_position` / `get_history` + 内置风控。`dispatch_bar` 顺序为「写状态 → `account.roll_to(date)` 换日（解除 T+1 冻结）→ 内置风控 → `on_bar`」，避免风控止损时 `pos.available==0` 被拒单。内置风控：单标的仓位上限 30%、分品种总杠杆（读 `config.RISK["account"]["max_leverage"]`）、逐持仓止损/止盈、黑名单（`is_delisted`/`is_st`/`is_suspended`/风险警示 + `params.blacklist`）。
- **5.2 四个运行环境零改动**：`StrategyRunner(strategy_cls, ..., run_mode=)` 以完全相同的接口驱动 `backtest` / `optimize` / `paper` / `live_sim`；下单统一走 `core/account.py` 的 `place_order()`（内含独立 stale refetch 复核 + 预热闸门），`for_trading` 仅 paper/live/live_sim 开启。实测同一策略类四环境全部跑通。
- **5.3 strategy_loader**：`StrategyRegistry.discover()` 扫描 `strategies/*.py`（`_` 开头跳过），任意文件加载失败（语法错误/导入异常）或校验不过（`meta["name"]` 为空、未实现 `on_bar`、`periods` 不在 `config.SUPPORTED_PERIODS`、重名）一律**隔离进 `unavailable`** 并记录原因，不影响其余策略。实测 9 个示例策略可用、坏文件被隔离。
- **5.4–5.8 研究流程**：`configs/strategies/base.yaml` + `<name>.yaml`（`params`/`symbols`/`start`/`end`/`optimize` 分离，命令行 `--params k=v` 优先级最高）；`tools/new_strategy.py` 五模板（`ma_cross`/`breakout`/`mean_reversion`/`grid`/`custom`）一次生成策略 + yaml + 测试三件套；`tools/strategy_checklist.py` 16 项上线检查（通过/警告/不通过/不适用，硬失败退出码 1）；`optimizer`（grid/random/genetic + **参数平原优先于收益尖峰** + 敏感性矩阵）；`walkforward`（70/30 + 滚动走向前，样本外净值用 `pct_change` 连乘拼接并输出 `degradation`）；`validator`（±10% 参数微扰、成本×2、延迟 1 根、数据抖动，评分卡 0–100）；`registry`（JSON 原子写、`exp_id`、`data_hash` 复现校验、`compare`/`load`/`find_reproducible`）。
- **5.9 因子研究全链路**：`factor/expression.py` 表达式引擎（`rank`/`zscore`/`scale`/`ts_*` 等，`ts` 窗口不含当日、除零返回 NaN、NaN 占比 >20% 传播）；`alpha101`（101 条）与 `alpha191`（191 条，六类；公开资料缺失者按同类等价实现并注释）；`preprocess` 四步；`evaluator`（IC/ICIR/IC 衰减/分层/相关性/换手/HTML 报告）；`combiner`（等权/IC 加权/ICIR/Ridge/去冗余）；`universe`（hs300/zz500/zz1000/zz2000/all_a + 流动性/停牌/ST/涨跌停过滤，联网失败降级静态样例）；`future_detector`（lead/shift/扰动三重检测）；`factor_engine`（批量 + parquet 缓存 + 增量）；`FactorStrategy` 接入 `BaseStrategy`（可注入桩面板离线测试）；`custom.py` 四个示例自定义因子 + `tools/new_factor.py`；`adapters/` 四个付费源适配器（缺依赖抛 `ImportError`，不静默空表）；`market/` 浏览/导入/安全校验。
- **9 个示例策略**（均含离线 `__main__` 自检）：`double_ma_cross`、`cb_arbitrage`、`futures_trend_following`、`us_swing_trading`、`option_sell_strangle`、`crypto_grid`、`fund_sip`、`repo_cash_management`、`hk_ah_arbitrage`。已扫描确认策略文件内**无** `akshare`/`requests`/`get_daily`/`get_kline`/`place_order`/`calc_commission`/`is_trading_day` 等越权调用。
- **CLI（`main.py` v3.6）**：`list-strategies` / `backtest` / `optimize` / `paper` / `new-strategy` / `checklist` / `factor`（`calc`/`eval`/`eval-all`/`combine`/`corr`/`backtest`/`research`）/ `market`（`search`/`import`/`validate`）。
- **测试**：`test_strategy.py` **18/18**（预热期 buy/short 拒单、预热期 sell 放行、预热后成交、fillna 帧被拒、`get_history` 抛错与 attrs、单标的上限、黑名单、止损、四环境跑通、`warmup_ok` 逐 bar 注入、首笔成交在 `warmup_bars` 之后）、`test_loader.py` **20/20**、`test_research.py` **19/19**、`test_factor.py` **58/58**、`test_alpha101.py` **10/10**、`test_custom_factor.py` **12/12**、`test_factor_strategy.py` **14/14**。回归：test_env 75/75、test_data 全部检查通过、test_indicators 80/80、test_chan 32/32、test_chart 19/19、test_pattern 14/14、test_export 11/11、test_account 49/49。未提交 GitHub。
- **已知简化（第 6/12 步替换）**：`core/runner.py` 为轻量执行器（单周期、收盘价撮合，无逐笔滑点/停牌撮合/涨跌停排队细节），第 6 步替换为全市场透明回测引擎而策略接口不变；示例策略未逐个配信号单测（`checklist` 标警告）；成本/延迟/噪声压力测试在策略不读注入参数时用收益近似；`alpha191` 部分公开资料缺失的公式按同类等价实现；股票池联网失败降级静态样例；因子引擎目前仅实现 free 源。

### 2026-10-30 · 第 3 步收尾补漏：B1–B5 + 两个常量（第 5 步开工前置）

> 状态：第 3 步维持 **已完成**（`next_step=5`）。本轮把第 3 步欠账一次补齐，因为 `warmup_ok` /
> `required_bars` / `price_adjust` / 期权 IV fail-closed 唯一该生效的地方是**第 5 步的信号入口**
> （`BaseStrategy.on_bar`），先做第 5 步会让这些守卫变成死代码：策略 `fillna(0)` 后 RSI=0 会被
> 读成「极度超卖」，预热期照发买入信号且不报错。

- **config 增量合并**（未整文件覆盖，置于 `INDICATOR_HARDENING` 之后）：`INDICATOR_WARMUP_GUARD`（`warmup_ok_column="warmup_ok"`、`convergence_tol=1e-3`、`required_bars_method="burnin_compare"`、`forbid_fillna_before_warmup=True`、`live_reject_if_last_bar_in_warmup=True`）与 `OPTION_VALUATION_GUARD`（`iv_solver="bisection"`、`iv_bounds=[1e-4,5.0]`、`iv_tol=1e-6`、`iv_max_iter=200`、`on_no_solution="nan"`、`day_count_theta=365`、`vega_per/rho_per="1_pct"`、`risk_free_rate_ref`、`dividend_yield_default=0.0`）。
- **B1 预热 NaN 只是哑弹**：指标输出除数值外必须携带物化布尔列 `warmup_ok`——新增 `warmup_ok_series()` / `attach_warmup_ok()`（Series → 单列 DataFrame），信号入口 `assert_signal_frame(df)` 强制读取该列：缺列报错、掩码含 NaN 报错、`forbid_fillna_before_warmup=True` 时**预热掩码为 False 的行出现非 NaN 指标值（fillna/ffill/bfill/rolling(min_periods=1) 填过）直接报错**。实测：未 fillna 的预热帧放行；同一帧 `RSI.fillna(0)` 后被拒；去掉 `warmup_ok` 列被拒。
- **B2 `required_bars` 不再查表**：新增 `_burnin_sample()`（seed 20261030 确定性长样本）、`_burnin_raw()`（EMA/SMA/MACD/RSI/ATR/ADX/KDJ 原始递推，不调 public 指标避免递归）、`_burnin_required_bars()`（首根 ×1.5 扰动、按序列量级归一相对误差、从后往前找首个超 `tol` 的位置 +2 根安全余量，模块级缓存），`required_bars = max(表值下界, 反推值)`。实测 **EMA=38（表 20）、MACD=135（表 35）、RSI=126、ADX=155、SAR=5**；硬校验：`required_bars` 处扰动相对误差 EMA 6.89e-4 / MACD 1.86e-4（≤1e-3），而按表值 20/35 取为 **EMA@20=1.39e-2、MACD@35=3.65e-1（均超标）**。
- **B3 `price_adjust` 多标的分组**：`data_fetcher._attach_asof` 按 symbol 填 `price_adjust`（已有列原样保留 → 多标的 + `attrs["adjust_by_symbol"]` 用 `symbols.map` 逐 symbol 填 → 否则退回单一 `attrs["adjust"]`）；指标入口 `resolve_adjust()` 遇帧内多口径直接报错，波动率类 fail-closed。实测 A=`qfq` + B=`none` 的多标的帧 ATR/STD/HIST_VOL 全部拦截 3/3。
- **B4 期权 IV 无解**：`IMPLIED_VOL()` 改为读 `OPTION_VALUATION_GUARD`；无解场景（非有限/价格≤0/T≤0、市价低于内在价值、超出 `[σ_lo, σ_hi]` 端点理论价、迭代耗尽）一律返回 **NaN** 并置 `iv_solved=False`（`return_status=True` 返回 `(iv, solved)`），**禁止返回二分区间下界**；`on_no_solution="raise"` 时抛 `ValueError`。实测市价 0.5 < 内在价值（K=90、S=100）与 T=0 均 `NaN + solved=False`，正常报价 `solved=True` 且 IV=0.3。
- **B5 实盘末根预热**：`assert_last_bar_ready(df, run_mode)` 在 `paper/live` 下末根 `warmup_ok=False`（新上市/刚切周期）**拒绝出信号**，`backtest` 默认豁免；`assert_signal_frame(..., require_last_bar_ready=True)` 可一并联拦。
- **第 4 步回补（预热闸门联动）**：`place_order()` 新增 `warmup_ok: bool = None`——**开仓（buy/short，且非基金申赎/逆回购）必须携带 `warmup_ok=True`**，`False` 或未带标记的裸单一律拒单并打 WARNING；**平仓/减仓（sell/cover）不受限**（与 `STALE_REFETCH_FAIL_POLICY` 的「开严平宽」同则，预热期也必须能止损/平仓）。
- **测试**：`test_indicators.py` 由 63 项扩到 **80/80**（新增 B1 五项、B2 反推与表值超标双断言、B3 混合口径、B4 三assert、B5 五项；`wave()` 默认长度 120→420 以容纳 ADX/MACD/RSI 100~150 根的预热期）；`test_account.py` 由 46 项增至 **49/49**（warmup_ok=False 开仓拒、裸单拒、预热期平仓放行）。回归：test_env 75/75、test_chan 32/32、test_chart 19/19、test_pattern 14/14、test_export 11/11、test_data 全部检查通过。未提交 GitHub。

### 2026-10-30 · 第 4 步：统一账户与订单管理

> 状态：第 4 步 **已完成**（`next_step=5`）。交付 `core/account.py` + `test_account.py`，46 项全过。
> 本轮未新增任何 config 常量，全部复用已就位的 `STALE_*` / `RISK` / `get_market_config()`。

- **全市场账户**：`TradingAccount` 内 `positions`（多头/买方/基金/逆回购）与 `short_positions`（空头/卖方）分离，`Position.kind` 区分 `spot|future|forex|crypto|option|fund|repo`；保证金从 `cash` 划入 `margin_used`、平仓退回，权益计算时加回保证金只计浮盈。
- **交易规则**：现货全额现金 + T+1 `frozen_volume`（换日 `_roll_to()` 解冻）；ETF 按 `t0_prefixes` 支持 T+0；可转债 `t_plus=0` 当日可平；期货 `today_volume` 判定平今并走差异化费率；外汇按 `notional/leverage`；期权买方付权利金、卖方收权利金并冻结 `notional + 标的市值×seller_margin_rate`；基金申赎按 `subscribe_fee×discount` 与 `redeem_fee_by_days`；逆回购按期限费率收手续费、`mature_date` 到期本息自动回款。实测：100 万买茅台 100 股@1600（费 41.6、`avg_cost=1600.416`）、RB2601 10 手@3800（保证金 34200、费 10、平今 4 手费 4、`realized=1996`）、AAPL 做空/回补（fx 7.1、SEC/TAF 仅卖出侧）、期权卖方保证金 4100、204001 本金 10 万 2.5% 到期回款 100006.85、基金持有 5/8/400 天赎回费 225/112.5/37.5。
- **下单校验链**：方向/类型 → 市场可交易（`cn_index` 的 `tradeable=False` 与净值型市场直接拒单）→ 动作判定 → 做空权限（期权卖方例外）→ 整手/数量 → T+1 可用 → 涨跌停（传 `pre_close`）→ **数据时效闸门** → 资金/保证金 → 持仓可用 → 入账。规则一律走 `config.get_market_config()`，国内期货在其上叠加 `config.CN_FUTURES_VARIETY`，无 `config.MARKETS[...]` 直取。
- **数据时效闸门（stale v2 第三道防线）**：`place_order` 内**独立**调用 `data_fetcher.assert_fresh_for_trading()`；`data` 为空时构造 `pd.DataFrame({"symbol":[symbol]})` 占位帧，仍按 `market+symbol` 走 refetch 重取最新数据比对交易日历，**完全不依赖调用方传入的列/attrs**，禁止因「决策帧没有时效列」fail-closed；refetch 失败按 `config.STALE_REFETCH_FAIL_POLICY` **开仓拒单、平仓放行**；同批次结果按 `config.STALE_REFETCH_TTL_SEC=60` 秒复用；`backtest` 默认豁免，显式 `for_trading=True` 时仍拦。实测 5 项：live 过期拒、backtest 豁免、显式 `for_trading` 拦、refetch 失败开拒平放、TTL 内重复下单仅取数 1 次。
- **手续费口径**：A股佣金/印花税（仅卖出）/过户费；美股 SEC/TAF 仅 `sell/short` 侧收取、按 USD 返回；港股多项征费且 22 只常见 ETF 免印花税；期货 `per_lot`/`per_value` 含平今差异（IF 平今 414 vs 开仓 27.6）；期权按张 + 最低收费；加密 maker/taker 双档；基金申购费打折、赎回费按持有天数；逆回购按期限。多币种按 `DEFAULT_FX_RATES` 固定汇率换算 `base_currency`。
- **测试**：`test_account.py` 46/46；回归 test_env 75/75、test_indicators 63/63、test_chan 32/32、test_chart 19/19、test_pattern 14/14、test_export 11/11、test_data 全部检查通过。
- **回补（同日）**：第 3 步 B1–B5 守卫与 `INDICATOR_WARMUP_GUARD` / `OPTION_VALUATION_GUARD` 两个常量已在「第 3 步收尾补漏」中全部落地；`place_order()` 同步新增 `warmup_ok` 预热闸门（开仓严、平仓宽），`test_account.py` 46 → 49 项。

### 2026-10-30 · 指标守卫加固：守卫不能装在会失灵的信息源上

> 状态：第 3 步维持 **已完成**。三处与第 2 步 stale 闸门同源的坑——守卫读的信息源会丢/可缺，
> 守卫就等于没有——本轮全部改为「读不到即失败」或「物理隔离」。

- **A1 复权守卫 fail-open → fail-closed**：数据层出口（`_attach_asof`）把复权口径物化为普通列 `config.INDICATOR_HARDENING["adjust_column"]`（默认 `price_adjust`，值 qfq/hfq/none，能穿透 `resample`/`concat`/`rolling`）；`resolve_adjust()` 的优先级为「显式 `adjust=` 参数 → `price_adjust` 列 → 兼容 `attrs["adjust"]` → **未知**」；`check_adjusted()` 在口径未知时按 `on_adjust_unknown="require"` **直接报错**，不再默认按已复权处理。实测：600519 qfq 帧 `price_adjust=qfq` → ATR=23.624；同帧 `drop(columns=['price_adjust'])` 且 `attrs={}` → `ValueError`；`adjust=''` 帧 `price_adjust=none` → `ValueError`。
- **A2 预热期显式化**：新增 `required_bars(name, **params)`（下界取 `config.INDICATOR_HARDENING["warmup"]`，递归收敛慢的按 max 抬高）；EMA/SMA/MACD/RSI/KDJ/ATR/ADX/SAR 的前 `required_bars()-1` 根统一置 NaN。实测：EMA 前 19 根、RSI 前 14 根、ADX 前 27 根、SAR 前 4 根、MACD.DEA 前 34 根均为 NaN。回测/实盘必须跳过预热期再出信号。
- **A3 跨市场红线物理隔离**：评估类改为 `eval_max_drawdown` / `eval_sharpe_ratio` / `eval_annual_return` / `eval_volatility`（`eval_prefix`），旧大写名已移除，实时信号链在命名层面取不到；`assert_indicator_usable(name, market, ...)` 的 `market` 改为**必填**，缺省直接报错，净值型市场仍拒绝 K 线类指标。
- **A4 成交量全 0**：`VOL_MA`/`OBV`/`VR` 遇全 0 成交量返回 NaN 并标注 `attrs["volume_all_zero"]=True`（`volume_all_zero_returns_empty`），不再返回一串 0 被误读为「极度缩量」。
- **A5 希腊字母单位写死**：`DELTA`=标的变动 1.0；`GAMMA`=标的变动 1.0；`VEGA`=波动率每 **1 个百分点**（÷100，本轮修正）；`THETA`=每 **1 个自然日**（÷365）；`RHO`=利率每 **1 个百分点**（÷100）。测试用 BS 重定价逐值核对（`vega 0.278803 vs 0.278803`、`theta -0.025500 vs -0.025533`）。
- **测试**：`test_indicators.py` 63 项全过，含「口径丢失（attrs 清空且无列）→ 3/3 fail-closed」「预热期 NaN」「eval_ 物理隔离」「volume 全 0」「希腊字母 BS 重定价」。回归 test_env 75/75、test_chan 32/32、test_chart 19/19、test_pattern 14/14、test_export 11/11、test_data 全部检查通过。

### 2026-10-30 · stale 复核 v2：refetch 为主 + asof 口径 + 多标的按 symbol 分组

> 状态：第 2 步维持 **已完成**。上一轮「读物化列」的防线在真实链路上仍然失守——本系统指标库
> 是纯函数（吃 `Series`、返回 `Series`），策略把指标 Series 拼成决策帧时 `data_asof_date` 列
> 根本带不过来，读物化列必然为空。本轮把下单闸门的判定主路径换成 refetch。

- **A1 refetch 为主**：`assert_fresh_for_trading()` 判读顺序改为「① 有 `market+symbol` → 默认直接 refetch 最新数据（TTL 内复用）→ ② 拿不到 `market+symbol` 才退回读物化列 → ③ 再读 `attrs["last_bar"]` → ④ 才 fail-closed」；**明确禁止因「决策帧没有时效列」拒单**（`config.FAIL_CLOSED_NOTE`）。
- **A2 asof 口径**：`_attach_asof()` 一律填**该帧最后一根 bar 的实际日期**（`df.index[-1]`），绝不按取数时刻/今天；`get_kline` 周/月线显式传底层日线的最后一根 bar，避免 `W-FRI`/`ME` 标签把日期推后。缓存命中与失败回退帧同理。实测 600519 周线标签 `2026-10-30` 而 asof 正确为 `2026-10-27`。
- **A3 多标的按 symbol 分组**：多标的帧（含 `symbol` 列且多值）逐 symbol 填各自最新日期，禁止整帧广播；复核时只读该标的自己的行，组合里 B 停更仍会被拦。
- **A4 refetch 失败处置 + 批量性能**：新增 `config.STALE_REFETCH_TTL_SEC=60` 与 `config.STALE_REFETCH_FAIL_POLICY={"open":"reject","close":"allow"}` —— 取不到行情时**开仓拒单、平仓放行**（否则止损/平仓单下不出去）；同批次结果（含失败结果）TTL 内复用，组合调仓不逐单打满接口。
- **A5 回测边界**：`backtest` 仅「调用方未显式要求」时放行；显式 `for_trading=True` 时回测里仍拦，用于预演「上实盘会怎样」。
- **测试**：核实9 扩展到 20 条断言（缓存命中 asof、多标的 A/B 分组、A1 无列 refetch 放行、refetch 覆盖帧内过期列、开仓拒/平仓放、TTL 内只取数 1 次、backtest 显式 for_trading 仍拦），全部通过。

### 2026-10-30 · stale 修正：时效物化列 + refetch（禁止把 fail-closed 装在读不到信息的位置）

> 状态：第 2 步维持 **已完成**。上一轮把「rolling 后 attrs 丢失 → fail-closed」当正确行为是错的：
> 实盘策略必然先算指标（MA/MACD/ATR/BOLL 全走 rolling/ewm/expanding），attrs 必被清空，
> 下单复核读不到 attrs 就拒单 → **每一笔都被拒，实盘瘫痪**。

- **时效物化为普通列**：`config.STALE_INFO_COLUMN="data_asof_date"`，`get_daily`/`get_minute`/`get_kline` 出口逐行写入本帧最新日期；普通列能穿过窗口运算/重采样/concat（`DataFetcher._attach_asof`）。
- **复核逻辑修正**：`assert_fresh_for_trading()` 优先读物化列；`config.STALE_CHECK_MODE="refetch"` 时无列则从数据层重取最新数据比对交易日历；**只有既无列又无法重取才 fail-closed**（`config.FAIL_CLOSED_NOTE`），禁止仅因 attrs 为空拒单。
- **测试**：新增「指标帧（attrs 为空、带物化列）新鲜放行 / 过期拒绝」「refetch 补取放行」「裸帧兜底 fail-closed」「assert_fresh 回测豁免」断言；backtest 豁免、paper/live 拦截均无回归。

### 2026-10-30 · stale 机制加固（双重防线 / attrs 实测 / 市场时钟 / 回测豁免）

> 状态：第 2 步维持 **已完成**；本轮补齐四个「不报错但会失去保护」的隐蔽缺口。

- **双重防线**：新增 `config.TRADING_REQUIRE_FRESH=True`；`_stale_gate_enabled()` 按 `config.RUN_MODE` 判断，paper/live 下即使忘记传 `for_trading` 也拦截 stale，backtest 豁免。新增模块级 `assert_fresh_for_trading()` 供第 4 步 `core/account.py` 做**独立**下单前复核（其 fail-closed 边界已在下一轮修正为「优先读物化列 / refetch」，不再仅因 attrs 为空拒单）。
- **attrs 实测结论**：pandas 2.3.3 下 `rolling/ewm/expanding` 会清空 attrs（其余 concat/merge/groupby/resample().agg()/diff/pct_change/cumsum/astype/布尔索引均保留），新增 `config.ATTRS_FRAGILE_NOTE`；`get_kline` 重采样后显式回填数据层 attrs，出口统一重新挂载。
- **市场时钟**：`_latest_completed_trading_day()` 逐市场取用 `get_trading_sessions` 的收盘时刻（A股15:00 / 港股16:00 / 美股美东16:00含夏令时 / 期货夜盘 / 外汇24h / 加密7×24），新增测试断言 A股、美股、crypto 三种时钟结果。
- **回测豁免**：时效闸门仅对 paper/live 生效；同一份停更数据在 backtest 放行（仅标 stale）、paper/live 拒绝，已加测试。
- **测试**：test_data 新增核实9（stale/回测豁免/下单复核/fail-closed）与核实10（市场时钟），共 19 项核查。

### 2026-10-30 · stale 数据使用边界收敛（实盘安全）

> 状态：第 2 步维持 **已完成**；在「失败返回过期缓存」的降级机制上补齐上限与下单禁令。

- **判定改为交易日差**：`attrs["stale_days"]` = 本地最后一根 K 线与「最近一个已收盘交易日」之间隔了几个**交易日**（`is_trading_day` 计算，不用自然日），差 > 0 即 `stale=True` 并 WARNING。「最近已收盘交易日」由 `get_trading_sessions` 的收盘时刻判断，盘中不会把今天的日线未生成误判为过期。
- **上限引用 `config.STALE_LIMIT`**（日线 5 / 分钟 2，禁止就地写死）：超限直接抛 `RuntimeError(...超过上限...视为不可用...)`。
- **下单链路禁用**：`get_daily` / `get_minute` 新增 `for_trading=False` 参数；声明用于模拟盘/实盘后遇 stale 直接抛 `RuntimeError(...禁止用于模拟盘/实盘下单决策)`。
- **图表标注**：`plot_kline` 检测到 stale 时在右上角红字标注「数据截至 X 日（过期 N 个交易日）」。
- **测试**：`test_data.check_stale_policy`（核实9）构造本地库停更 N 个交易日 —— 日线 5 日可用+标记、7 日抛错、`for_trading=True` 拒绝；分钟线 2 日可用+标记、4 日抛错。全部按交易日口径断言。

### 2026-10-30 · 第 2 步最终收尾（数据源常量 + 单点故障行为 + 关闭第 2 步）

> 状态：**第 2 步关闭**，下一步进入第 3 步「技术指标计算」。

- **`config.py` 新增三组常量（增量合并，未整文件覆盖）**：`SOURCE_AVAILABILITY`（当前实测现状，注明会随网络变化、禁止静态决定取数路径）、`SINGLE_SOURCE_MARKETS`（日线单点 forex/cn_fund/cn_reverse_repo；分钟单点 cn_convertible/us_stock/us_etf/hk_stock，第 13 步补源优先）、`CN_INDEX_UNIT_VERIFIED = True`。
- **单点市场失败必须显式报错（实证）**：`get_daily` / `_get_raw_daily` / `get_minute` 在单点市场失败且无本地数据时抛
  `RuntimeError(...该市场当前无可用数据源...)`，不再返回空表；有本地增量库时返回过期数据并标 `attrs["stale"]`。新增
  `test_data.check_single_source_behavior`：模拟东财不可达后实测——forex/cn_fund/cn_reverse_repo 日线与
  cn_convertible/us_stock/us_etf/hk_stock 分钟线全部抛错（文案含「无可用数据源」），而 600519 日线回退
  `stock_zh_a_daily`、sh000300 日线回退 `stock_zh_index_daily` 正常返回。
- **核实「日线有备源、分钟线单点」的不对称**：新浪美股/港股日线历史足够长（AAPL 自 1984-09-07、10,064 行；SPY 自 2001-01-02、6,494 行；00700 自 2004-06-16、5,503 行），短板只在分钟线。顺带修正两处单位事实：新浪港股日线**含成交额**（00700 2026-10-29 ratio≈1.0074 → `verified=True`），新浪美股日线无成交额但此前被 `_standardize` 补成 0，现显式置 `NaN` + `amount_missing=True`。
- **`tools/source_status.py` 健壮性**：单后端探测超时 **5s**（daemon 线程，东财卡住不会拖死整体）、同一次运行内结果缓存不重复探测、输出统一为「可用性 / 延迟(s) / 备注」；`--json` 增加 `latency_s` 与 `probe_timeout_s`。实测 2026-10-30：东财已恢复（0.64s / 17 行），腾讯与币安本轮探测超时（网络抖动，非代码问题）。
- **test_chan 确认默认行为不变**：新增断言 `b3_filter_enable` 默认 `False`，且「开启过滤但阈值=0」时 B3/S3 数量与默认完全一致（证明新增开关不改默认点数）。
- README「数据源可用性」注明**这是运行时探测结果、非硬编码**，东财不可达可能是本机网络问题而非永久；补「单点故障市场」与「美股/港股日线深度」表。

### 2026-10-28 · 第 2 步收尾：指数单位交叉验证 + 数据源可用性矩阵 + 三类点归档

> 状态：第 2 步维持 **已完成**。指数成交量单位经 BaoStock 独立交叉验证（r=1.0000），当前 ÷100 折算**正确无需修正**；新增 `tools/source_status.py`；缠论三类点如实归档。

- **指数成交量单位交叉验证（`config.py` / README）**：不再依赖腾讯反推，改用 BaoStock 指数日线（同时返回 volume=股、amount=元）与新浪同日对比。2026-10-27 `sh.000300`：BaoStock `volume=16,868,847,400` 股、`amount=383,125,564,549` 元（`amount/volume=22.71` 元/股，成分股均价量级合理），新浪 `volume=16,868,847,400` → **r = 1.0000**，确认新浪为「股」，`×0.01` 转「手」正确；`sh.000001` r=1.0000、`sz.399001` r=0.9991（源修订差异）。`DATA_SOURCE_UNITS` 的 `stock_zh_index_daily` / `baostock_index_daily` 均升为 `verified=True`（输出不再标 `unit_uncertain`），东财指数仍 `verified=False`。清缓存后实测 `sh000300`：`source=stock_zh_index_daily`、`volume=168,688,474 手`（=16,868,847,400 股）、`source_volume_unit=股`、`amount=NaN` + `amount_missing=True`。
- **腾讯指数条目（按用户要求登记但明确不接入）**：新增 `DATA_SOURCE_UNITS["stock_zh_index_daily_tx"]`，`volume_unit=股`（占位）、`amount_unit=None`，`verified=False`，evidence 写明「**amount 列实为成交量(手)，不是成交额**（2026-10-27 值 168,688,474 = 新浪 volume÷100），接入前必须按手处理」。新增 `CN_INDEX_DAILY_PRIORITY = ["eastmoney","sina","baostock","tencent"]`；`UNIFIED_VOLUME_UNIT["cn_index"]="手"` 补注「全局唯一例外，须跨源验证」。
- **`_fetch_cn_index_daily` 按优先级循环**：抽 `_cn_index_daily_one(src, ...)` 分源实现，tencent 显式 `raise NotImplementedError`；切换源打 WARNING 说明单位差异已统一。
- **`tools/source_status.py`（新增）**：一次探测 8 个后端（东财/新浪 A股/新浪期权/新浪期货/新浪外汇/ BaoStock/腾讯/币安），打印「后端连通性 + 逐市场日线取数源（主源是否可用、回退链、当前实际、备注）+ 东财不可达影响」；`--json` 供第 13 步健康检查。矩阵与 `_fetch_*_daily` 实现逐一校准（如 `cn_convertible`/`cn_option` 仅新浪、`forex`/`cn_fund`/`cn_reverse_repo` 东财挂即取不到）。实测：东财 ❌ RemoteDisconnected，其余 7 个后端 ✅。
- **缠论三类点归档（不修复、如实标注）**：`ChanAnalyzer` 类注释标注「轻量缠论」；新增可选过滤 `_third_point_ok()`，读 `config.CHAN_CONFIG["b3_filter_enable"]`（**默认 False**）/ `b3_min_leave_pct` / `b3_min_leave_volume_ratio`，开启后要求离开笔幅度与放量达标，三类点只会更少。
- **README**：新增「数据源可用性」小节（后端连通性表、逐市场取数源表、东财不可达影响、第 13 步多源切换规划）；「已知限制」补指数单位跨源验证结论、「轻量缠论/三类点须人工核对」条目。
- **测试**：test_env 75/75、test_chan 30/30、test_chart 19/19、test_pattern 14/14、test_export 11/11、test_data「全部检查通过」复跑无回归（`b3_filter_enable=False` 时点数与上轮一致）。**未提交 GitHub**。

### 2026-10-28 · 第 2 步遗留修复：裸 6 位指数识别 + 指数源与单位核查 + 缠论点数自证

> 状态：第 2 步 **已完成**。复跑自检：test_env **75/75**、test_chan **30/30**、test_chart 19/19、test_pattern 14/14、test_export 11/11、test_data「全部检查通过」（含扩充后的「核实7 指数市场接入」6 段）。过程中 BaoStock 服务端曾报「网络接收错误」，重连后复跑通过，属环境抖动非代码回归。

- **裸 6 位指数识别（`config.py` / `detect_market_type`）**：新增 `CN_INDEX_BARE_CODES = {399001, 399005, 399006, 399673, 932000}`，并置于 6 位分支**最开头**（先于深市个股 `000/001/002/003` 判定）。关键事实：深市个股号段与沪市指数 `000xxx` 段**完全重合**，故 `000xxx` 不纳入裸识别，维持个股优先。实测：`399001/399006/399673/932000 → cn_index`；`000300/000905/000016/000688 → cn_stock`；`sh000300/sh000905 → cn_index`；`sh600519→cn_stock`、`sz000001→cn_stock`、`510300→cn_etf` 回归不变。
- **裸 `000xxx` 引导告警（`core/data_fetcher._detect_market`）**：命中 `CN_INDEX.common_codes` 且被判为 `cn_stock` 时打 WARNING「检测到疑似指数代码 000300（沪深300），已按深市个股处理；如需取该指数请传 sh000300」——**只引导不改判定**，并按号段给出正确前缀（399/980/981→`sz`，其余→`sh`）。
- **指数源与单位核查（`_fetch_cn_index_daily`）**：实测东财 `index_zh_a_hist` **只认裸代码**（`symbol="000300"`），带前缀会失败；本机东财 push2his 持续 `RemoteDisconnected`，实际走新浪 `stock_zh_index_daily`（认 `sh000300`）→ 日线 2426 行。两源成交量差 100 倍（东财=手 / 新浪=股），已由 `INTERFACE_UNITS` 统一为**手**，`attrs` 显式输出 `volume_unit`（统一后）与 `source_volume_unit`（源单位），跨源切换打 WARNING「源已切换…成交量单位不同但已按 100 股=1 手统一」。新浪分支 `amount=NaN` + `amount_missing=True`（**不补 0**）。另实测腾讯 `stock_zh_index_daily_tx` 的 `amount` 列实为**成交量（手）**（数值精确等于新浪 volume÷100），不可当成交额使用，未接入。
- **`core/chan.py` 点数自证与可溯源**：二类点新增 `src_date` 字段（前置一类点的信号日），三类点新增 `src_date`（来源中枢 `end_date`），可逐点回溯；`MAX_CENTER_BI` 提为类属性（默认 9）便于敏感性验证。实测六年日线（1650 根）：B1=16、B2=11、B3=2、S1=18、S2=11、S3=1；二类 22 个**全部可溯源、0 个孤儿**，B2≤B1、S2≤S1 成立。中枢延伸上限敏感性：3→B3=4/S3=2、5→2/1、9→2/1、12/20/∞→0/0，说明**限制是三类点成立的必要条件**（非漏检原因），无上限才会全部漏检。
- **测试**：`test_env.py` 新增 8 条裸 6 位用例（75 项）；`test_chan.py` 新增「六类确切数量」「二类点数量不超过一类点」「每个二类点都能溯源（src_date）」「三类点稀疏但可用」4 条断言（30 项）；`test_data.py` 的「核实7」扩为 6 段——裸 6 位识别、`attrs.volume_unit` 标注、东财直连成交额探测（不可达则如实记录不假装通过）、**强制跳过东财**验证新浪分支 `amount` 全 NaN + `amount_missing=True`、分钟 `capped`。
- **README**：`CN_INDEX_BARE_CODES` 两类裸代码规则、指数源代码格式与 100 倍单位差异、缠论六类点数与 `MAX_CENTER_BI=9` 的设计依据/敏感性表/人工核对提示同步更新；`progress.json` 记录本轮修复与遗留。

### 2026-10-28 · 第 2 步收尾：指数接入 + 缠论买卖点补齐 + 基准改回真实指数

> 状态：第 2 步 **已完成**。新增/复跑自检：test_env 66/66、test_chart 19/19、test_chan 26/26；test_pattern 14/14、test_export 11/11 无回归。

- **`config.py` 指数支持（增量合并，未整文件覆盖）**：新增 `CN_INDEX`（`tradeable=False` + `not_tradeable_reason` + 12 个常用指数 `common_codes`）与 `INDEX_PREFIX_RULES = {"SH": ("000","950","880","881"), "SZ": ("399","980","981")}`；`MARKET_CONFIG_MAP` 增 `"cn_index": ("CN_INDEX", None)`（市场 18→19，`core/utils.MARKET_NAMES` 同步 19 条）；`UNIFIED_VOLUME_UNIT["cn_index"]="手"`、`MINUTE_SOURCE_PRIORITY["cn_index"]=["eastmoney","sina"]`；`DATA_SOURCE_UNITS` / `DATA_SOURCE_META` 各补 4 条指数接口（`index_zh_a_hist` 手/元、`stock_zh_index_daily` 股/无、`index_zh_a_hist_min_em` 手/元、`baostock_index_daily` 股/元）。
- **`detect_market_type` 指数拦截**：在「国内期货：字母+数字混合」判定**之前**插入 `SH/SZ + 6 位数字` 分支——命中指数号段返回 `cn_index`，否则剥前缀递归按 6 位规则重判。修复了此前 `sh000300` 被当成 `cn_future` 并返回**期货数据**的静默错误；`sh600519/sh510300/sz000001` 回归用例全部不变。
- **`core/data_fetcher.py` 指数取数**：新增 `_index_parts()`（无前缀指数代码直接抛错并提示传 `sh000300` 形式）、`_fetch_cn_index_daily()`（东财 `index_zh_a_hist` → 新浪 `stock_zh_index_daily` → BaoStock `sh.000300` 备份）、`_fetch_cn_index_minute()`（东财 `index_zh_a_hist_min_em` 约 1 个月，超出标 `minute_history_capped` + `minute_available_from`；失败回退新浪 1970 根并标 `unit_uncertain`；**禁止走 BaoStock**，其分钟不含指数）；`_fetch_daily` / `_fetch_minute` 加 `cn_index` 路由；`get_daily` 对 `cn_index` 强制 `adjust="none"`（缓存名带 `none`）；新浪日线无成交额 → `amount=NaN` + `attrs["amount_missing"]=True`（**不补 0**）。实测 `sh000001` 680 行、`sz399001` 680 行（东财本机不可达 → 新浪回退）、`sh000300` 5 分钟 1056 行。
- **`core/chan.py` 一/二/三类买卖点全部可用**：修 3 个根因——①`find_centers` 延伸条件由 `lo > zg or hi < zd` 改为 `lo >= zg or hi <= zd`（碰到边界即中止）并限制单中枢最多 9 笔，此前一个中枢从 2024-10 吞到 2026-05（50 笔只剩 1 个中枢），三类点永不成立；②二类点改用笔下标定位（`bi_idx + 2`）替代日期过滤，避免漏掉紧邻反弹笔；③三类点改用 `leave_idx = 首个 start_date >= 中枢 end_date 的笔`。实测 600519 六年日线买卖点 59 个（B1×16 / B2×11 / B3×2 / S1×18 / S2×11 / S3×1）。
- **`core/chart.py` 基准改回真实指数**：`BENCHMARK_ALIASES` 改为三元组（真实指数代码, 图例标签, ETF 回退），`000300→sh000300`、`000905→sh000905`、`000016→sh000016`、`399006→sz399006`；新增 `_resolve_benchmark()` / `_load_benchmark()` 按优先级取数，**指数接口取不到才**回退 `510300/510500/510050/159915` 并 WARNING；实测基准线为「沪深300(000300)」242 根，未触发回退。
- **测试**：`test_env.py` 新增「市场类型共 19 类（含 cn_index）」断言 + 7 条带前缀指数/回归用例（66 项）；`test_chart.py` 新增「基准改回真实指数 000300」「以 000300 为基准的对比图图例含指数基准线」（19 项）；`test_chan.py` 新增长窗口断言「一/二/三类买卖点全部可产出」「二类点回抽不破前低/前高」「三类点突破后回抽不回中枢」（26 项）；`test_data.py` 新增「核实7 指数市场接入」（前缀识别 + 10 年日线 2427 行 + `adjust=none` + 成交额单位/缺失标注 + 分钟 `capped`）。

### 2026-10-28 · 第 2 步：批量导出 + K 线绘制（多周期 / 形态标注 / 多标的对比 / 缠论）

> 状态：第 2 步 **已完成**。四个自检脚本全过：test_chart 17/17、test_pattern 14/14、test_chan 23/23、test_export 11/11，test_env 复跑 58/58。

- **`tools/data_export.py` + `tools/__init__.py`（2.1）**：`DataExporter` 支持 `load_watchlist / add_symbol / remove_symbol / add_market_batch(index_300|all_etf|all_cb)`（批量加入时打印幸存者偏差提醒）、`download()`（断点续传：已覆盖区间直接跳过；失败清单最后统一重试一次；`tqdm` 进度条 + ≥0.3s 间隔）、CSV（`utf-8-sig`）/ parquet / Excel 导出、`summarize()` 数据概览（CSV/parquet 自动去重，市场名从右往左按已知市场匹配，修掉了 `cn_stock_600519` 被切成 `cn`+`stock_600519` 的解析 bug）、`update_all()` 增量、CLI（`--symbols/--watchlist/--update/--summary/--add/--batch/--format/--export-dir`）。
- **`core/chart.py`（2.2 / 2.5）**：`setup_chinese_font()` 从 `config.CHART_CONFIG["font_candidates"]` 探测（本机命中 Arial Unicode MS，找不到降级英文 + WARNING 不崩）；`plot_kline()`（mplfinance 蜡烛 + MA + 布林 + 成交量 + 买卖点 + 形态标注 + 指标副图 + 缠论叠加 + 区间缩放 + `color_scheme` 切换）；`plot_indicator()`（macd/kdj/rsi/boll）；`plot_compare()`（归一化起点=1 + 基准）；`plot_kline_grid()`（≤4 标的、`ncols` 控制、共享时间轴、各自蜡烛+均线+成交量、顶部归一化收益对比）；`plot_backtest_kline()`（按标的各出一张成交复盘图）；`plot_kline_interactive()`（plotly→HTML，未装返回 None）；`save_fig()` 统一落 `backtest_results/charts/`。修了三处坑：指标副图必须放在成交量之后的 panel、数据太短导致整列全 NaN 的 MA/指标要跳过、基准指数改为 ETF 代理并在图例标注。
- **`core/pattern_annotate.py`（2.4）**：`mark_ma_cross()`、`mark_macd_divergence()`（金叉/死叉 + 顶/底背离，用 `scipy.signal.argrelextrema` 找极值 + `min_gap` 最小间隔 + `confirm_right` 右侧确认）、`mark_breakout(window=20)`、`annotate_all()`；`DEFAULT_PATTERNS = {"ma_cross": True, "macd_div": False, "breakout": False}`。未来函数红线：极值必须等右侧 K 线确认后才标注，确认日未到的极值一律不画。
- **`core/chan.py`（2.6）**：`ChanAnalyzer` 完整链路 `merge_inclusion → find_fractals → find_strokes(mode="new"/"old") → find_segments → find_centers → find_buy_sell_points`，`signals()` 直接给策略用，`analyze_multi_level()` 做日/周联立；`plot_chan()` 分型小三角、笔黄线、线段橙粗线、中枢蓝色半透明矩形（标 ZG/ZD/级别）、买卖点彩色箭头，开关读 `config.CHAN_CONFIG`（默认只开 分型+笔+中枢）。修了两处逻辑 bug：同型更极端分型替换时必须同步延伸上一笔终点（否则笔不首尾相接）、背驰必须比较隔一笔的同向笔（`bi[i]` vs `bi[i+2]`，相邻笔方向必然相反）。
- **多周期（2.3）**：`DataFetcher.get_kline()` 只做周期路由（`1d/1w/1M` 走 `get_daily` + `re_sample_kline`，分钟走 `get_minute`），`get_multi_period()` 支持一次取多周期；`utils.re_sample_kline()` 用 `W-FRI`/`ME`，open 取首、high 最大、low 最小、close 取末、volume/amount 求和、`is_suspended` 取 any，末根未走完标 `is_complete=False`；非法周期（如纯数字 `60`）直接抛 `ValueError`。
- **实测数据**：600519 两年日线 485 根 → 包含合并 368 → 分型 170（顶 85/底 85）→ 笔 49（顶底交替、首尾相接）→ 线段 16 → 中枢 5（ZG>ZD）→ 买卖点 7（B1/S1）；日线 438 根 / 周线 95 / 月线 22；4 标的并排图 447 KB；导出 600519/510300/AAPL 一年日线共 735 行，CSV 与 parquet 收盘价差 ≤2.3e-13。

### 2026-10-28 · 第 1 步收尾（9 天偏差定性 / 双重交易日历 / BaoStock 会话自愈）

> 状态：第 1 步维持 **已完成**。9 天偏差定性为**数据源噪声（非复权 bug）**；两个健壮性缺口已补。

- **60 分钟 15:00 vs 日线 qfq 的 9 天偏差 → 源噪声**：725 个可比交易日中 9 日 >0.1%（最大 0.2535%：2025-04-17 分钟 1573.98 / 日线 1570.00）。9 天的「距最近除权日」为 118/112/28/81/154/61/**0**/42/96 天，仅 2025-12-19 落在除权日当天（偏差 0.1184%）；按距离分组 ±5 天(24) 1 日、6~20 天(62) 0 日、21~60 天(154) 2 日、>60 天(485) 6 日，呈随机散布。5 个除权日 `日线raw × foreAdjustFactor − 日线qfq` 全部为 **0.000000**，且 raw 口径与 qfq 口径偏差逐日差值 ~1e-14（因子完全抵消），排除 off-by-one 与「除权日既用未复权价又用新因子」。偏差日分钟量合计少 1.1%~4.9% → BaoStock 分钟线缺尾盘集合竞价成交。**结论：日频回测可忽略，日内高频需留意**。
- **交易日历改为双重校验（消除盲区）**：新增 `_trading_calendar_check()` —— 主用「该标的日线索引」（排除停牌/调休休市），兜底用 `chinesecalendar`/`is_trading_day`。当日历说开市、日线却没有该日 → 记为**日线缺口**（`attrs["daily_gap_dates"]` / `daily_gap_count` + WARNING），不再当成休市静默放过；日线整个不可用时退回纯节假日日历判定分钟缺口。
- **BaoStock 会话自愈**：新增 `_bs_check()` / `_bs_execute()`，命中会话失效特征（`error_code` ∈ {10001001, 10002001, 10002007} 或 error_msg 含「未登录/登录过期/session」）时自动 `logout → login → 重试一次`，仍失败才抛错；分钟线与复权因子两条链路都走该出口。
- **测试**：`test_data.py` 由 13 项核查扩到 **15 项**，新增「日线缺口识别」（包装 `get_daily` 删掉 2025-10-22 → `daily_gap_count=1`、WARNING 命中）与「BaoStock 会话自动恢复」（首次伪造「用户未登录」→ 实测调用 2 次并取到 31 行因子，日志出现「已重置会话准备重登后重试」）。

### 2026-10-28 · 第 1 步复核实证（因子字段名 / 分钟时间列 / 场景分工 / 缺口回填 / 因子同源）

> 状态：7 项核实全部通过，第 1 步维持 **已完成**（高危项 1/2/3/5 均实测通过）。

- **核实1 · 复权因子真实字段名（实测为准）**：`query_adjust_factor("sh.600519","2024-01-01","2024-12-31")` 的 `rs.fields` = `['code','dividOperateDate','foreAdjustFactor','backAdjustFactor','adjustFactor']`（不是公开资料里的 `adjustFactor/forwardAdjFactor` 那套）；前 5 行实测 `2024-06-19 fore=0.927559 back=7.113689`、`2024-12-20 fore=0.942063 back=7.224927`。取因子代码用的正是这三个列名。**兜底逻辑已改**：字段缺失直接抛 `BaoStock 复权因子字段名不匹配：缺少 [...]，实际 fields=[...]`，空结果也抛错；分钟侧只写 `minute_factor_available=False` + `minute_factor_error`（含具体原因），不再退化成「数据源不支持复权」的温和 WARNING。因子取全历史（1990 起，600519 共 31 行，首行 2001-08-27 fore=0.130391）。
- **核实2 · 分钟线 date+time 双列（PASS）**：BaoStock 返回的 17 位 `time` 取前 14 位生成 datetime 索引，`date` 列被替换，不会塌成 1 根/天。实测 600519 2026-10-27：60 分钟 4 根（10:30/11:30/14:00/15:00）、30 分钟 8 根、15 分钟 16 根、5 分钟 48 根，均严格递增；跨 3 个交易日连续递增。
- **核实3 · 历史回填 vs 当日实时（PASS）**：`_split_minute_plan` 把跨「今天」的拉取段拆成「历史段（到昨天）」与「今天段」，`_fetch_cn_minute` 对含当日的请求跳过 BaoStock 改走新浪/东财。实测取今天：`rows=4`、今日 4 根、`source=stock_zh_a_minute`、**BaoStock 调用 0 次**。盘中若取不到当日且已过 9 点，打印「未取到今日分钟线」WARNING。
- **核实4 · 增量库中段缺口（PASS）**：`get_minute` 不再只补末尾，新增 `_minute_gap_ranges` 比对交易日历找出缺失日期段并回填；交易日历优先用该标的日线索引（可排除停牌日与 2024-02-09 除夕这类调休休市日），`chinesecalendar` 缺失时降级为不报缺口（`CN_CALENDAR_AVAILABLE`）。回填后仍有缺口写 `attrs["gap_dates"]` / `gap_count` + WARNING。实测 3 年 60 分钟 2904 行、`gap_count=0`；人为删除 2026-10-22 的 4 根后更新即补回 4 根。BaoStock 空结果改为返回空表（不再抛错触发 4 次退避，避免每个缺口日白等约 10 秒）。
- **核实5 · 分钟与日线复权同源（PASS）**：A股日线与分钟统一走 BaoStock `query_adjust_factor`（`adj_factors/cn_stock_{symbol}_bs_factors.csv`），旧 AKShare 口径缓存按 `factor_source` 列识别后作废。实测日线 `qfq/raw` 收盘比值与 `foreAdjustFactor` 最大绝对差 **1.11e-16**；最近完成交易日 15:00 的 60 分钟 qfq 收盘与日线 qfq 收盘相对误差 **0.00000%**（近 60 个交易日全部 <0.1%）。
- **核实6 · 逆回购与 crypto**：`bond_buy_back_hist_em(symbol="204001")` 原始返回 **4949 行**（2006-05-08 起，字段 日期/开盘/收盘/最高/最低/成交量/成交额），近 30 天请求只有约 18 行是 `get_daily` 日期过滤所致，**不是接口截断**。crypto 单次回填上限 20000 根（20×1000）、间隔 ≥0.3s，`attrs` 写 `backfill_cap_bars=20000` / `request_interval=0.3`。
- **核实7 · 既有用例**：`python test_env.py` **58/58 通过**，`GC → global_future` 在加入 `AMBIGUOUS_CODES` 后默认值未变（仅打 WARNING 并在 attrs/dict 回传 `ambiguous_market` / `market_candidates`），用例无需改动；`ZN` 默认仍为 `global_future`，显式传 `cn_future` 生效且不提示。
- **测试**：`test_data.py` 由 8 项核查扩到 **13 项**（新增：分钟 date+time 根数、取今天不走 BaoStock、增量库缺口补回、分钟/日线因子同源、crypto 回填上限与间隔），实测标的 **15/15**、核查 **13/13** 全部通过。

### 2026-10-28 · 第 1 步收尾（单位对齐 / BaoStock / 分钟增量库）

> 状态：第 1 步从「有问题」改回 **已完成**，遗留边界详见上文「已知限制」。

- **单位口径（三重实测确认）**：东财系历史接口 = 手×100（`stock_zh_a_hist` 600519 比值 99.69 → 归一 0.9969；`fund_etf_hist_em` 100.0071 → 0.9993）；新浪系 = 股/份不换算（`stock_zh_a_daily` 1.0000）；BaoStock = 股不换算（官方文档 + 实测 15:00 根 `amount/(close×volume)≈1`）。统一登记到 `config.DATA_SOURCE_UNITS`（28 条），`data_fetcher.INTERFACE_UNITS` 由此派生，不再两处维护；新增 `baostock_daily` / `baostock_minute` 两条。`unit_uncertain=True` 机制保留，清单见「已知限制」。
- **接入 BaoStock（A股分钟线长历史）**：新增 `_fetch_cn_stock_minute_baostock`——支持 5/15/30/60 分钟、1990 年起；代码转换 `600519→sh.600519`、`000001→sz.000001`；优先 `adjustflag="3"`（不复权），复权因子由 `query_adjust_factor()` 单独落盘 `adj_factors/cn_stock_{symbol}_minute_factors.csv`（`qfq_factor`/`hfq_factor`），与 raw+因子分离架构一致（因子取不到时只标 `minute_factor_available=False` + WARNING，**不回退 adjustflag=2**，否则会把已复权价写进增量库）；`bs.login()` 模块级单例、失败重置后重新登录；指数代码显式拦截转新浪；失败按 `config.MINUTE_SOURCE_PRIORITY` 回退新浪/东财并打印原因。
- **分钟线源选择**：`config.MINUTE_SOURCE_PRIORITY` —— `cn_stock: baostock→sina→eastmoney`；`cn_etf/cn_future/global_future/forex: sina`；`cn_convertible/us/hk: eastmoney`；`crypto: binance`（1/5/15/30/60 → 1m/5m/15m/30m/1h，limit=1000 分页，单次回填上限 20 页并标 `minute_history_capped`）。
- **自建分钟增量库**：`data_cache/minute/{market}_{symbol}_{period}.parquet`。`get_minute()` 流程改为「读本地累积 → 取最后一根时间戳 → 只向数据源请求最近 N 根 → 合并/按时间戳去重/升序 → 质量检查（去重、排序、OHLC 合法性、非正价格剔除）→ 覆盖写回 → 返回全量」。`attrs` 必含 `available_from` / `minute_history_capped` / `source` / `adjust`；首次回填不足请求起点时 `minute_history_capped=True` + WARNING，禁止静默截断。`clear_cache()` 同时覆盖 `minute/` 子目录。
- **其他收尾**：逆回购 204001 改为「历史接口重试 → 东财快照备用源 → 仍失败显式抛错」，不再返回空表（本轮 15/15 通过）；新增 `config.AMBIGUOUS_CODES`（`ZN` 沪锌 vs 10 年期美债、`GC` COMEX 黄金 vs 美股代码），未显式传 `market_type` 时打 WARNING 并在 `attrs`/实时 dict 返回 `ambiguous_market` + `market_candidates`，显式传入则不提示。
- **测试**：`test_data.py` 新增 BaoStock 3 年 60 分钟用例（断言 >1023 行、起点不晚于请求起点+30 天、source=baostock_minute）、分钟增量库 attrs/落盘/二次调用用例、ZN 歧义代码用例；实测标的 15/15、核查 8/8 全部通过（600519 60 分钟 3 年 = 2900 行，2023-10-30 ~ 2026-10-27）。

### 2026-10-28 · 第 1 步数据层「事实自证」第二轮（单位 / 复权 / 分钟线）

> 状态：第 1 步标记为 **有问题**——单位与复权两项已核实并修好，分钟线分页受上游硬限制未达成。

- **核实1 · 单位（已改）**：删除 `auto` 反推与 `_guess_volume_unit`，改为模块级 `INTERFACE_UNITS` 硬编码表（接口 → 源 volume/amount 单位 → 换算系数 → 统一单位 → 是否确证 → 实测证据）。`_normalize_units` 只查表换算，未登记或未确证的接口在 `DataFrame.attrs` 标 `unit_uncertain=True`，不再静默猜测。
  - **东财 `stock_zh_a_hist` 实测为「手」而非「股」**：600519 末日 38669 手 × 1355.90 ≈ 5.227e9 元，`amount/(close×volume)=99.69`；×100 换股后为 `0.9969`。同一天新浪 `stock_zh_a_daily` 为 3,866,914 股（二者恰为 100 倍关系）。
  - 其他实测：`fund_etf_hist_em`=手（510300 比值 100.0071）、`stock_hk_hist`=股（1.0016）、`bond_zh_hs_cov_daily`=张（与东财成交量恰为 ×10）、`bond_zh_hs_cov_min`=手×10（113052 比值 10.0）、`stock_zh_a_minute`=股、`stock_zh_a_hist_min_em`/`fund_etf_hist_min_em`=手×100。
  - 断言（最近交易日，归一后 `amount/(close×volume)`）：600519 **0.9969**、510300 **0.9993**、113052 **1.0000**（含估算），均落在 [0.9, 1.1]。
- **核实2 · 新浪分钟线复权（已核实）**：`stock_zh_a_minute`（`CN_MarketData.getKLineData`）实测**不复权**——600519 共 492 个交易日、1970 根 60 分钟线，逐日「当日最后一根分钟收盘 / 当日不复权日线收盘」= **1.0000**（min=1.0、median=1.0、max=1.0，偏离>0.5% 的天数为 0）；同期 qfq 因子在 1.0000~1.0615 之间变动（确有分红除权）。akshare 源码也显示 `adjust=""` 时直接返回原始 K 线，qfq/hfq 是由日线因子本地乘算得出。因此可作 raw 源，`attrs["adjust"]="none"`。
- **核实3 · 分钟线分页（未达成）**：实测新浪 A股 datalen 上限 1970（>1970 返回 null）、期货固定 1023、外汇 datalen=1023/3000/6000 均返回 974，接口**无时间游标**，无法分页；东财分钟仅约 1 个月。已实现 `_slice_minute` 正确裁剪 + `minute_history_capped` / `minute_available_from` 标注 + WARNING（请求 3 年 60 分钟实测返回 1970 行，虽 >1023 但不足 3 年）。
- **核实4 · 可转债 amount（已改）**：`bond_zh_hs_cov_daily` 无成交额时不再补 0，改为 `amount = close × volume`（张）估算，并在 `attrs` 标 `amount_estimated=True` + `amount_note`。
- **核实5 · 期货单位告知（已改）**：期货 `attrs["volume_unit"]="手"`、`attrs["amount_missing"]=True`；代码注释与本文档注明**期货 `amount ≈ close × volume` 不成立**，流动性过滤必须单独取「成交额(元)」，禁止用 volume×close 估算。
- **核实6 · ETF/REITs 回退复权退化（已改）**：走新浪回退源时 `attrs["adjust"]="none"` + `adjust_note`，并打 `WARNING: 该源不支持复权，本次返回不复权价`；`_apply_adjust` 对因子全 1 的情形同样降级为 `adjust="none"` 并告警，不再伪装成 qfq 成功。
- **核实7 · config.py 遗留改动（已确认无破坏）**：`detect_market_type` 内新增 3 行分支——
  ```python
  # 国内期货品种优先（如 RB 螺纹钢、AU 沪金）；ZN 同时是沪锌与美债，保留国际期货判定
  if code in CN_FUTURES_VARIETY and code != "ZN":
      return "cn_future"
  ```
  位置在 `known_crypto` 之后、`known_futures` 之前；仅新增分支，既有判定顺序（crypto → cn_future → global_future → us_etf → us_stock → …）与 `get_market_config` 均未改动，`test_env.py` 58 项用例仍全过。
- **测试**：`test_data.py` 新增 `check_units`（三标的比值断言）与 `check_minute_long_history`（3 年 60 分钟 >1023 行），共 6 项核实；实测 6/6 通过，标的 14/15（国债逆回购 204001 因东财不可达失败）。

### 2026-10-28 · 第 1 步数据层「自证核查」修复

- **复权（核查1）**：`get_daily(symbol, start_date, end_date, adjust="qfq", fill_missing=False)`；A股/ETF/场外基金/REITs 改为**原始价 + 复权因子分离存储**——`data_cache/raw/` 只存不复权价，`data_cache/adj_factors/` 存 `qfq_factor`/`hfq_factor`，复权价 = 原始价 × 因子现算；删除并停用旧的「已复权价」缓存（增量拼接会导致复权基准漂移）。因子覆盖不足时整段重算（长历史前段不再被 bfill 成常数）。修正 `hfq_factor` 归一化基准：以最早因子日为基准（此前除以最后一天会与 qfq 完全相同）。
- **单位（核查2）**：`_standardize(..., source, volume_unit, amount_unit)` 统一口径为 volume=股/张/份/币、amount=元；东财 A股 `手→×100`、千元→`×1000`，ETF/REITs 用 `auto` 模式按 `amount/(close×volume)` 反推（≈100 判为手）**——该 auto 逻辑已在下一轮「事实自证」中删除，改为 `INTERFACE_UNITS` 硬编码表**；新增 `_verify_units` 自检，比值偏离 [0.02, 50] 时告警。期货例外：volume 保留「手」（合约乘数因品种而异），在 `df.attrs["volume_unit"]` 显式标注。
- **长历史（核查3）**：确认新浪日线走 `klc_kl.js` 全量历史、无 1023 上限，无需分页；币安 K 线按 `limit=1000` 循环分页。600519 十年实测 2426 行。
- **市场覆盖（核查4）**：新增 `cn_reits` 日线（东财 `reits_hist_em`，失败回退新浪 ETF 通道，实测 508000 可用）；`neeq`/`private_fund`/`qii_product`/`otc_deriv` 在 `_NO_KLINE_MARKETS` 中显式说明「走净值/定价路径，不走 K 线接口」并抛 `ValueError`，不再静默留空。修正期权日线为 `option_sse_daily_sina`。
- **ffill（核查5）**：`_quality_check` 不再对 OHLC 前值填充，保留缺失值并新增 `is_missing` 列（与原 `is_suspended` 并列）；`fill_missing()` 仅供图表展示，指标/回测使用未填充序列。
- **统一出口（核查6/7）**：所有出网请求收敛到 `_request`（`_source` 数据源标识 + 节流 ≥0.3s + 指数退避重试）与 `_http_get`，删除了 crypto/新浪直连/币安里的裸 `requests.get`；`_build_symbol_list` 加「勿高频调用」注释。对外 4 个方法列名统一，跨 5 个市场断言一致；分钟线补 A股/期货/外汇三条用例（外汇走新浪 `NewForexService.getMinKline`，代码前缀 `fx_s`）。
- **config.py**：仅新增 `STANDARD_COLUMNS`（+2 行）；`detect_market_type` 的白名单与 `get_market_config` 未改动（已有的 `CN_FUTURES_VARIETY` 优先判定为上一轮遗留改动，本次未触碰）。
- **测试**：`test_data.py` 15 个标的（新增 113052 可转债、508000 REITs）+ 5 项自证核查，全部通过；任一核查失败时脚本返回非 0。

### 2026-10-28 · 第 1 步统一数据层

- 新增 `core/data_fetcher.py`：`DataFetcher` 统一 `get_daily / get_minute / get_realtime / get_symbol_list`，内部按 `detect_market_type` 路由到各市场私有取数方法（A股/ETF/美股/港股/可转债/国内期货/国际期货/外汇/期权/加密/场外基金/逆回购）。
- 数据质量检查：高低价异常删除、OHLC 缺失前值填充且连续 ≥3 行丢弃、非正价格删除、停牌 `is_suspended` 标记、涨跌停仅告警、按 date 去重保留最后、升序返回。
- 缓存：`{market_type}_{symbol}_{period}_{adjust}.csv`（另有 parquet），日线 7 天 / 分钟 1 天 / 实时不缓存；`clear_cache(symbol=None)`、`update_cache(symbol)`；标的列表落 `data_cache/lists/` 缓存 7 天。
- 港股：价格区间最小变动价位、每手股数（查不到默认 100）、ETF 免印花税标记。
- 期货：合约乘数/保证金/手续费读 `config.get_market_config()`；主力换月 `dominant_roll` 标记与 `get_dominant_contract()`；夜盘 21:00 后归属下一交易日。
- 期权：`get_option_chain()` 返回 strike/expiry_date/option_type/contract_multiplier；`calc_greeks()`（BS）与 `calc_implied_volatility()`（二分法）。
- 基金：场内/场外自动识别、默认累计净值、`calc_holding_period_redemption_fee(hold_days)` 分档赎回费。
- 实时行情改造：因东财 push2 全量快照接口在本机网络下频繁 `RemoteDisconnected`（且美股/港股全量快照需分页 900+ 次，耗时 20 分钟以上），改为**新浪单只直连**（`sh600519`/`rt_hk00700`/`gb_aapl`/`nf_RB0`/`hf_GC`/`fx_seurusd`，0.1~0.5s）+ **币安 24h ticker**（BTC），并保留东财快照作为回退。
- `test_data.py`：13 个标的全部可用（13/13），期权链 102 条合约。已知限制：可转债 123045 已于 2022-08 退市（脚本自动回退历史区间验证）；美股/港股标的列表依赖东财 push2，网络波动时返回空表并告警。

### 2026-10-27 · 修正深市个股/场外基金号段误判（严重 bug）

- **问题**：`detect_market_type("000001")`、`000002`、`000858`、`002415`、`002594`、`003816` 等深市个股全部返回 `cn_fund`。旧规则把 `00` 开头一律归入场外基金（`if p2 in ("00", "16") or p3 in ("519",): return "cn_fund"`），而深市个股号段 000/001/002/003 恰好都以 `00` 开头。
- **后果**：数据层遇到深市股票会调用场外基金净值接口，取回的不是 K 线且不报错。
- **修复**：按号段细分，并把 `519` 规则提前到 ETF 判断之前（否则 `51` 的 ETF 规则会先命中 `519xxx`）：
  1. `519` 开头 → `cn_fund`（沪市场内基金段，如 519066）
  2. `51/52/56/58`、`15/18` 开头 → `cn_etf`
  3. `000/001/002/003` 开头 → `cn_stock`（深市主板 + 原中小板）
  4. `004~009`、`16` 开头 → `cn_fund`（场外号段 + LOF）
  5. 其余（30/60/68 等）→ `cn_stock`
- **验证**：`test_env.py` 新增 13 条号段回归用例（深市个股、场外基金、ETF、显式传参），共 58 项全部通过；全号段扫描 000/001/002/003 共 4000 个代码，误判 `cn_fund` 数量为 0。

### 2026-10-27 · 第 0 步环境与骨架

- 建立 25 个一级目录与 `data_cache/` 六个子目录，新增 `core/utils.py`（日志/重试/交易日/时段/格式化）、`main.py`、`test_env.py`、`check_progress.py`、`progress.json`。
- 修正 `SPY` 识别为 `us_etf`（原误判 `us_stock`）。
- 新增 `config.get_market_config()` 统一访问 18 类市场参数（禁止直接写 `config.MARKETS[...]`），并让 `detect_market_type` 支持显式 `market_type` 覆盖。
- 2~3 位纯字母代码默认兜底由 `global_future` 改为 `us_stock`（国际期货需显式传参）；GC 仍按白名单识别为 `global_future`。
