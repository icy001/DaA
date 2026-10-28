# Trae 全市场量化交易系统搭建指令集

> **版本 v3.3** · 18 类金融产品全覆盖 · 全链路：行情 → K线/缠论 → 指标 → 策略 → 因子研究（Alpha101/191/自定义）→ 回测 → 模拟盘 → 实盘接入（A股/国内期货）→ 复盘 → 数据与报告长期可用

## 覆盖范围（共 18 类）
- **零售层（13 类，普通账户可直接参与）**：A股个股、A股场内ETF、美股个股、美股ETF、港股个股/ETF、沪深可转债、国内期货、国际期货、外汇保证金、场内期权、加密货币、场外公募基金、国债逆回购
- **合格投资者层（5 类，需满足资产/收入门槛）**：私募证券基金、券商资管/信托/私募理财、新三板、公募REITs、场外衍生品定价模拟（⚠️ 个人禁止实盘，仅学习）
- **机构层专属**（不在本系统范围内，个人投资者基本无法直接参与）：银行间债券、场外衍生品实盘通道、非标、ABS、一级市场股权

## 使用方式
1. **一次只复制一段**：本文档用 `=====` 分隔每一步，复制完整一段给 Trae，等它写完代码、跑通测试后，再复制下一段。**不要一次性全部粘贴**，否则会乱。
2. **建议顺序**：第 0~9 步（零售层基础）→ 第 10 步（合格投资者层）→ 第 11 步（CLI 入口整合）→ 第 12 步（实盘接入层）→ 第 13 步（数据与报告长期可用性）。
3. **前置文件**：开始前把 `config.py`、`requirements.txt`、`.env.example`、`.gitignore` 四个文件放到项目根目录。
4. **凭证**：把 `.env.example` 复制为 `.env`（`cp .env.example .env`），回测/模拟盘阶段可全部留空；填了真实凭证的 `.env` 永不提交。
5. **中断可恢复**：第 0 步会生成 `progress.json` 与 `README.md` 进度看板；重新打开项目先运行 `python check_progress.py`，即可知道做到哪一步、下一步复制哪段。

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

4. **创建 `main.py` 入口文件**，先只写一个打印欢迎信息的 main 函数，输出系统版本（v3.3 全市场+合格投资者层+行情K线缠论+因子研究+实盘接入+凭证安全+数据长期可用）和支持的市场列表。

5. **安装依赖**：提示用户执行 `pip install -r requirements.txt`，并打印核心依赖版本（pandas/numpy/akshare）。

6. **写一个 `test_env.py` 测试脚本**，依次验证：
   - import pandas/numpy/akshare 正常
   - 目录都存在且可写
   - config.py 加载正常，打印所有支持的市场类型
   - detect_market_type() 函数对以下测试用例返回正确结果：
     - `600519` → cn_stock
     - `510300` → cn_etf
     - `123045` → cn_convertible
     - `00700`（5位）→ hk_stock
     - `AAPL` → us_stock
     - `204001` → cn_reverse_repo（国债逆回购）
     - `rb2501` → cn_future
     - `GC` → global_future（国际期货）
     - `BTC` → crypto
     - `EURUSD` → forex
     - `161725` → cn_fund（场外公募基金）
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
       "version": "v3.3",
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

## ===== 第 1 步：统一数据层（18个品种全支持）=====

请创建 `core/data_fetcher.py`，这是整个系统的数据入口，所有市场的数据都从这里获取，对外提供统一的接口，**上层策略不需要关心底层是哪个市场的接口**。

### 核心要求：
1. **类名：`DataFetcher`**，初始化时接收 `cache_dir` 参数，自动创建缓存目录。所有数据优先读本地缓存（CSV+parquet），没有或过期才调用接口，并自动缓存到本地，带请求延时和重试。

2. **统一对外方法**：
   - `get_daily(symbol, start_date, end_date, adjust='qfq') -> pd.DataFrame`
     返回统一列名：`['date', 'open', 'high', 'low', 'close', 'volume', 'amount']`，date 设为 datetime 索引，按日期升序。
   - `get_minute(symbol, period, start_date, end_date) -> pd.DataFrame`
     同样返回标准化列，period 支持 1/5/15/30/60。
   - `get_realtime(symbol) -> dict`
     返回最新价、涨跌幅、成交量、买卖价等实时快照。
   - `get_symbol_list(market_type) -> pd.DataFrame`
     返回指定市场的全部标的列表（代码+名称）。

3. **内部市场路由**：
   在 get_daily/get_minute/get_realtime 内部，先用 `detect_market_type(symbol)` 识别市场类型，然后分发到对应的私有取数方法：
   - `_fetch_cn_stock_daily()` → 调用 `ak.stock_zh_a_hist()`
   - `_fetch_cn_etf_daily()` → 调用 `ak.fund_etf_hist_em()`
   - `_fetch_us_stock_daily()` → 调用 `ak.stock_us_hist()`，自动处理美股代码后缀
   - `_fetch_hk_stock_daily()` → 调用 `ak.stock_hk_hist()`，自动补前导0
   - `_fetch_cn_cb_daily()` → 调用 `ak.bond_zh_hs_cov_daily()`，分钟用 `bond_zh_hs_cov_min()`
   - `_fetch_cn_futures_daily()` → 调用 `ak.futures_main_sina()`（主力连续合约），分钟用 `futures_zh_minute_sina()`；额外提供 `get_dominant_contract()` 方法获取当前主力合约代码
   - `_fetch_intl_futures_daily()` → 调用 `ak.futures_foreign_hist()`，实时用 `futures_foreign_commodity_realtime()`
   - `_fetch_forex_daily()` → 调用 `ak.forex_hist_em()`，失败时尝试 `ak.currency_hist()` 作为备选
   - `_fetch_cn_option_daily()` → 调用 `ak.option_sse_daily()`（ETF期权），股指期权用 `option_cffex_daily()`；额外提供 `get_option_chain()` 方法获取期权链（同标的同到期日的全部行权价合约）
   - `_fetch_crypto_daily()` → 调用 `ak.crypto_hist_investing()`，失败打印警告（需网络可达）
   - `_fetch_cn_fund_nav()` → 调用 `ak.fund_open_fund_info_em(indicator="单位净值走势")`，返回列重命名为 date/close（净值），open/high/low 用 close 填充、volume 填0，保持统一格式
   - `_fetch_cn_repo_rate()` → 调用 `ak.bond_repo_rate()` 获取逆回购历史利率，实时用 `bond_sh_buy_back_em()`

4. **数据质量自动检查**（非常重要，防垃圾数据进回测）：
   - 高低价异常检查：high < low 或 high < open/close 或 low > open/close 的行删除并打警告日志
   - 缺失值检查：OHLC 有空值的行用前值填充，连续3行以上空值丢弃
   - 价格为0或负数的行删除
   - 停牌处理：成交量为0的行保留（收盘价沿用前收），但标记 is_suspended=True
   - 涨跌停检查：单日涨跌幅超过市场涨跌停限制的，打印警告（不删除，防止除权除息误判）
   - 去重：按 date 去重，保留最后一条
   - 排序：按 date 升序

5. **缓存机制**：
   - 缓存文件命名规则：`{market_type}_{symbol}_{period}_{adjust}.csv`
   - 日线数据缓存有效期7天，分钟线1天，实时数据不缓存
   - 提供 `clear_cache(symbol=None)` 方法手动清除缓存
   - 提供 `update_cache(symbol)` 方法增量更新最新数据

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

10. **写 `test_data.py` 测试脚本**，依次获取以下13个标的的最近30天日线数据，打印前5行、数据形状、是否有空值，确保接口正常：
    - A股：600519（贵州茅台）
    - A股ETF：510300（沪深300ETF）
    - 美股：AAPL
    - 美股ETF：SPY
    - 港股：00700（腾讯）
    - 可转债：123045
    - 国内期货：rb（螺纹钢主力）
    - 国际期货：GC（COMEX黄金）
    - 外汇：EUR/USD
    - 加密货币：BTC/USDT（如果接口失败就打印跳过警告，不影响其他测试）
    - 公募基金：161725（招商中证白酒）
    - 国债逆回购：204001（GC001）
    - ETF期权：510050（上证50ETF期权链，能拿到合约列表就算通过）

    如果某个接口失败，不要崩溃，打印警告继续跑下一个，最后汇总哪些市场可用哪些需要检查网络。

---

## ===== 第 2 步：行情批量下载导出 + K线图绘制（多周期/形态标注/多标的对比/缠论）=====

> 本步做两件事：①把行情数据**批量下载、落盘成文件、随时导出**（不必先跑回测才能取数）；②把行情和交易结果**画成 K 线图**，让形态和买卖点一眼可见。这两个模块后面每一步都会用到。

### 2.1 行情批量下载与导出工具 `tools/data_export.py`

创建 `tools/data_export.py`（同时创建空的 `tools/__init__.py`），用于把行情批量拉下来存成文件，**离线可用、可断点续传、可随时导出**。

1. **核心类 `DataExporter`**，初始化接收 `DataFetcher` 实例和 `export_dir` 参数（默认 `export/`），自动创建 `export/csv/`、`export/parquet/`、`export/excel/` 子目录。
2. **自选清单管理 `watchlist.csv`**（列为 `symbol,market_type,name`，`market_type` 可留空自动识别）：
   - 提供 `load_watchlist()`、`add_symbol()`、`remove_symbol()` 方法维护自选池
   - 提供 `add_market_batch(kind)` 批量加入：如 `index_300`（用 `ak.index_stock_cons_csindex(symbol="000300")` 拉沪深300成分股）、`all_etf`（用 `ak.fund_etf_spot_em()` 拉全部ETF）、`all_cb`（全部可转债）
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

在数据层 `data/fetcher.py` 里扩展多周期支持，并在 `core/chart.py` 打通绘图。

1. **周期枚举**：统一支持 `1d`（日）、`1w`（周）、`1M`（月）、`60min`、`30min`、`15min`、`5min` 七种周期，周期字符串全局统一（数据层、指标、绘图、回测共用同一套写法）。
2. **本地重采样函数 `re_sample_kline(df, period)`**（放在 `data/fetcher.py` 或 `core/utils.py`）：
   - 用 pandas `resample` 把日线聚合为周线（`W-FRI`）、月线（`ME`），规则：`open` 取首、`high` 取最大、`low` 取最小、`close` 取末、`volume`/`amount` 取和，并保留 `date` 索引
   - 重采样**不依赖网络**，已有日线数据即可自由切换周期
   - 分钟线无法由日线反推，必须由接口直接获取（AKShare 分钟接口），本地重采样时给出明确提示
3. **数据层接口**：`DataFetcher.get_kline(symbol, start, end, period='1d', adjust='qfq')`，内部按周期路由到日线接口或分钟接口，返回**列名统一**（`date, open, high, low, close, volume, amount`）的 DataFrame。
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

---

## ===== 第 3 步：技术指标计算模块 =====

创建 `core/indicators.py`，所有策略要用的技术指标都在这里实现，**所有指标只接受标准化的OHLCV DataFrame，不依赖任何市场特有字段，保证跨市场通用**。

### 要求实现以下指标，每个指标都作为独立函数，返回pd.Series或DataFrame：

1. **均线类**：
   - MA(close, n)：简单移动平均
   - EMA(close, n)：指数移动平均
   - SMA(close, n, m)：SMA均线（通达信口径）
   - MACD(close, fast=12, slow=26, signal=9)：返回DIF、DEA、MACD柱
   - BOLL(close, n=20, k=2)：返回上轨、中轨、下轨

2. **动量类**：
   - RSI(close, n=14)
   - KDJ(high, low, close, n=9, m1=3, m2=3)：返回K、D、J
   - ROC(close, n=12)：变动率
   - CCI(high, low, close, n=14)
   - WILLR(high, low, close, n=14)：威廉指标

3. **成交量类**：
   - VOL_MA(volume, n=5, m=10)：成交量均线
   - OBV(close, volume)：能量潮
   - VR(close, volume, n=26)：成交量比率

4. **波动率类**：
   - ATR(high, low, close, n=14)：真实波幅
   - STD(close, n=20)：标准差
   - HIST_VOL(close, n=20)：历史波动率（年化）

5. **趋势类**：
   - ADX(high, low, close, n=14)：平均趋向指数
   - SAR(high, low, step=0.02, max_step=0.2)：抛物线指标

6. **期权专属**（给期权策略用）：
   - IMPLIED_VOL：对接data_fetcher里的IV计算
   - DELTA/GAMMA/THETA/VEGA/RHO：直接封装希腊字母计算
   - IV_RANK(iv_series, n=252)：隐含波动率分位数
   - IV_PERCENTILE(iv_series, n=252)：IV百分位

7. **基金/资产配置专属**：
   - MAX_DRAWDOWN(nav)：最大回撤
   - SHARPE_RATIO(nav, rf=0.02)：夏普比率
   - ANNUAL_RETURN(nav)：年化收益
   - VOLATILITY(nav)：年化波动率

8. **期货专属**：
   - BASIS(spot_price, futures_price)：基差
   - BASIS_RATE(spot_price, futures_price)：基差率
   - ROLL_YIELD(near_price, far_price, days_to_expiry)：展期收益率

9. **跨市场通用注意事项**：
   - 所有指标自动处理NaN，开头的NaN保留不填充（避免给策略假信号）
   - 所有函数不修改传入的原始DataFrame，返回新对象
   - 写 `test_indicators.py` 脚本，用随机生成的OHLCV数据测试每个指标输出shape正确、无全NaN异常。

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
   - 自动用 detect_market_type(symbol) 获取对应市场规则
   - **交易规则校验**（下单前必须检查，不通过则拒绝并打日志）：
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
- `get_hs300()` / `get_zz500()` / `get_zz1000()` / `get_zz2000()`：调用AKShare获取指数成分股，自动更新
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

### 核心类 `Backtester`：
1. **初始化参数**：`strategy_class, strategy_params, symbols, start_date, end_date, initial_capital, benchmark, market_type=None`
   - 如果传了market_type就强制用该市场规则，不传则自动识别每个标的
   - benchmark默认000300沪深300

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
   - 涨停买不进、跌停卖不出：当日涨停且开盘即涨停时买单不成交，跌停卖单不成交
   - 成交量限制：单笔成交量不超过当日总成交量的1%（避免小盘股成交不真实）
   - T+0/T+1严格按照市场规则
   - 交易成本完全用config里的真实费率，不要理想化设置0手续费

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

创建 `core/paper_trader.py`，对接真实行情，用模拟账户实时/按日撮合，和回测引擎用同一个TradingAccount类，保证回测和模拟逻辑一致。

### 核心类 `PaperTrader`：
1. **初始化参数**：`strategy_class, strategy_params, symbols, initial_capital, data_fetcher`
   - 模拟账户数据持久化到 `data_cache/paper_account.json`，重启不丢失
   - 如果已有账户文件，加载已有持仓和资金，不重新初始化

2. **行情驱动**：
   - `run_daily()`：按日频运行，每日收盘后用当日收盘价撮合，适合中低频策略
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
   - [ ] `python test_indicators.py` 所有指标计算正常
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

实现三个实现类：
- **`AkshareSource`**：默认主源（免费、覆盖全）
- **`TushareSource`**：Tushare Pro 备用源（需要 token，数据稳定性高、字段规范）
- **`LocalSource`**：本地缓存/快照源（永远可用，作为最后兜底）

**数据源路由器 `DataRouter`**：
- 根据 `config.DATA_LONG_TERM.data_source_priority = ["akshare", "tushare", "local"]` 顺序尝试
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
- **向后兼容**：旧的 qfq 缓存文件如果存在，启动时打印一次警告，提示用户删除重新拉取；提供工具 `python tools/migrate_cache_to_raw.py` 自动迁移（需要联网拉一次完整复权因子）
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
- 快照默认保留 `DATA_LONG_TERM.snapshot_retention_days=365` 天
- 支持"按快照复现"：`python main.py backtest --from-snapshot <id>` 直接使用当时那份数据重跑

### 13.5 时点成分股（Point-in-Time）消除幸存者偏差 `data/pit_index.py`

**痛点**：直接用当前沪深300成分股回测2020年，等于提前知道哪些股票后来被选进了指数，收益被系统性高估。必须用**历史上每个调仓日真实的成分股名单**。

实现：
- 支持指数：沪深300(000300)、中证500(000905)、中证1000(000852)、中证2000(932000)、上证50(000016)、科创50(000688)、创业板50(399673)
- 数据源：Tushare 的 `index_weight` 接口优先，AKShare 为辅；首次拉取全部历史成分股权重数据后，按调仓日（季调：3/6/9/12月第二个周五后第一个交易日）落地到 `data_cache/constituents/{index_code}.parquet`
- 统一API：`get_index_members(index_code, date)` 返回某日真实的成分股+权重列表
- **回测默认启用**：`FactorStrategy` 走沪深300/500股票池时，**自动按时点选股票**，不使用当前成分股
- 若数据源拉取失败：打印红色警告"时点成分股不可用，回测结果含幸存者偏差"，但不中断（允许学习用）

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

- **缓存容量监控**：`tools/cache_usage.py` 统计 `data_cache/` 各子目录大小，超过 `DATA_LONG_TERM.cache_max_gb=20`（默认 20GB，可改）时按 LRU 清理最冷数据
- **日志轮转**：`logs/` 使用 `RotatingFileHandler`，单个文件最大 50MB，保留最近 20 个备份
- **审计日志归档**：`audit_logs/` 按月分文件，超过 2 年自动压缩归档
- **实盘运行数据**：`live_trading/` 每月初压缩上月数据为 zip，保留近 3 个月明细
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
