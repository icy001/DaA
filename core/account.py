"""第 4 步：统一账户与订单管理（core/account.py）

一个账户同时支持 6 种交易模式：
  1) 股票现货（A股/美股/港股/ETF/REITs/新三板/可转债）：全额现金、T+1/T+0、印花税；
  2) 期货保证金（国内商品/金融期货 + 国际期货）：合约价值×保证金率，平今仓差异化费率；
  3) 外汇保证金：名义本金/杠杆，点差成本；
  4) 期权买卖方：买方付权利金、卖方收权利金并冻结保证金；
  5) 基金申赎：申购费（打折）+ 按持有天数递减的赎回费；
  6) 国债逆回购：按期限收手续费，到期本息自动回款。

【下单前校验链】（任一不通过即拒单并写日志，返回 status="rejected"）
  方向/类型合法 → 市场可交易（cn_index 等拒单）→ 最小单位/整数倍 → 做空权限
  → T+1 可用数量 → 涨跌停（提供 pre_close 时）→ 【数据时效闸门】→ 资金/保证金
  → 持仓可用数量 → 成交入账。

【数据时效闸门（stale v2，第三道防线）】
  - 本模块在 place_order 内【独立】调用 data_fetcher.assert_fresh_for_trading()，
    默认按 market+symbol 走 refetch 重取最新数据比对交易日历，完全不依赖调用方传入的
    DataFrame/attrs/物化列；物化列只作为 data 层内部的快速短路。
  - backtest 模式默认豁免（回测按定义跑历史数据）；显式 for_trading=True 时仍拦。
  - refetch 失败（网络/源不可达）按 config.STALE_REFETCH_FAIL_POLICY 处置：
    开仓拒单、平仓放行（不能因为取不到行情就下不出止损/平仓单）。
  - 同批次结果在 config.STALE_REFETCH_TTL_SEC 内复用（由 data_fetcher 内部缓存实现）。

【指标预热闸门（与第 3 步 B5 联动）】
  - 开仓（buy/short）：必须携带 warmup_ok=True；未带标记或 False → 拒单并打 WARNING。
  - 平仓/减仓（sell/cover）：不受限（预热期也必须能止损/平仓，与「开严平宽」同则）。
  - 基金申赎/逆回购走净值/资金路径，不参与该闸门。

【市场规则获取】
  一律走 config.get_market_config(market_type)，禁止 config.MARKETS[...]；
  国内期货的品种级参数（乘数/保证金/手续费）在此之上用 config.CN_FUTURES_VARIETY 覆盖。

【简化说明（实盘前必须替换）】
  - 多币种用固定汇率表 DEFAULT_FX_RATES 换算成 base_currency，未接实时汇率；
  - 期货/外汇/加密按“保证金从 cash 划入 margin_used”记账，平仓时退回；
  - 港股按 config 的 min_lot 粗略校验（真实每手股数因股而异，需券商接口）；
  - 期权卖方保证金 = 权利金市值 + 标的合约市值×seller_margin_rate；未传 underlying_price
    时按权利金市值估算并打 WARNING（禁止静默当成精确值）；
  - 期权到期行权需要标的价格（current_prices 里的 "{symbol}_underlying"），缺失时只记
    WARNING，不臆造行权结果。
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

import config
from core.data_fetcher import assert_fresh_for_trading
from core.utils import is_trading_day, setup_logger

# 简化固定汇率（→CNY）；实盘必须替换为实时汇率
DEFAULT_FX_RATES = {
    "CNY": 1.0, "USD": 7.10, "HKD": 0.92, "JPY": 0.047, "EUR": 7.80,
    "GBP": 9.10, "CHF": 8.05, "AUD": 4.70, "CAD": 5.20, "NZD": 4.30,
}

# 常见港股 ETF（免印花税）；代码无法从 5 位数字中可靠区分 ETF/个股，故用清单 + is_etf 覆盖
HK_ETF_CODES = {
    "02800", "02801", "02823", "02828", "02833", "02836", "02837", "02840",
    "03033", "03067", "03070", "03074", "03110", "03188", "03191", "03199",
    "07200", "07226", "07234", "07500", "07552", "08226",
}

# 国债逆回购代码 → 期限（天）
REPO_TERM_DAYS = {
    "204001": 1, "204002": 2, "204003": 3, "204004": 4, "204007": 7,
    "204014": 14, "204028": 28, "204091": 91, "204182": 182,
    "131810": 1, "131811": 2, "131800": 3, "131801": 4, "131802": 7,
    "131803": 14, "131805": 28, "131806": 91, "131807": 182,
}

# 外汇/贵金属合约规模覆盖（config 的 lot_size=100000 仅适用于货币对）
FOREX_LOT_SIZE_OVERRIDE = {"XAUUSD": 100.0, "XAGUSD": 5000.0}

# 只做净值/定价、不接受二级市场订单的市场
_NO_ORDER_MARKETS = {
    "private_fund": "私募证券基金走净值申赎路径，不支持二级市场下单",
    "qii_product": "券商资管/信托/私募理财走净值路径，不支持二级市场下单",
    "asset_management": "资管产品走净值路径，不支持二级市场下单",
    "otc_deriv": "场外衍生品走定价模拟路径，禁止走撮合下单",
    "trust": "信托产品走净值路径，不支持二级市场下单",
}

# v3.53 评审五轮·闸门7：场内衍生品市场标识（黑名单已退役，仅供回测启动提示等
# 展示逻辑使用——报单拦截由「主体性质硬拦 + LIVE_ALLOWED_MARKETS 白名单」接管）
DERIVATIVE_MARKETS = {"cn_future", "cn_option", "global_future"}

# v3.53 评审六轮·闸门7 白名单化（fail-closed）：实盘允许交易的市场集合。
# v3.53 评审七轮·语义修正：白名单只管「非衍生品市场」的实盘扩展；【衍生品实盘
# 禁令由账户主体性质决定，不由本集合决定】——个人主体对衍生品市场永久硬拦，
# 把衍生品市场错误加进白名单也绕不过（先查主体闸再查白名单闸）。
# v3.54 / 13.0.25（评审七轮）：集合入治理面 config.LIVE_SAFETY["live_allowed_markets"]
# （唯一参数源，模块常量仅为兼容引用派生）；扩市场 = 治理面显式加入 + 预检回执。
LIVE_ALLOWED_MARKETS = {str(m) for m in config.LIVE_SAFETY.get("live_allowed_markets")
                        or []} or {"cn_stock", "cn_etf"}


class LiveMarketForbidden(RuntimeError):
    """实盘模式下市场未列入 LIVE_ALLOWED_MARKETS 白名单——直接 raise 硬拦。

    刻意【不继承】LiveSafetyError 系拒单异常：实盘收口不得把它降级为
    一条 rejected 记录后继续运行，必须让调用方进程级感知并停机。
    """


class DerivativeMarketLiveForbidden(LiveMarketForbidden):
    """个人主体实盘衍生品报单——主体性质永久硬拦（白名单不可绕过）。"""


# 手续费计价货币（calc_commission 的返回值单位）
_MARKET_CCY = {
    "cn_stock": "CNY", "cn_etf": "CNY", "cn_convertible": "CNY", "cn_reits": "CNY",
    "neeq": "CNY", "cn_future": "CNY", "cn_option": "CNY", "cn_fund": "CNY",
    "cn_reverse_repo": "CNY", "cn_index": "CNY",
    "us_stock": "USD", "us_etf": "USD", "global_future": "USD", "forex": "USD",
    "crypto": "USD", "hk_stock": "HKD",
}

_LEVERAGED_KINDS = {"future", "forex", "crypto"}


@dataclass
class Position:
    """单个标的持仓。多头/买方放 positions，空头/卖方放 short_positions。"""

    symbol: str
    market: str
    direction: str = "long"            # long / short
    volume: float = 0.0                # 持仓总量
    frozen_volume: float = 0.0         # T+1 冻结（当日买入不可卖）
    today_volume: float = 0.0          # 今仓（期货平今判定）
    avg_cost: float = 0.0              # 持仓均价（现货含买入费用）
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    open_date: Optional[_date] = None
    last_trade_date: Optional[_date] = None
    margin_rate: float = 1.0
    margin: float = 0.0                # 该持仓占用的保证金
    multiplier: float = 1.0            # 合约乘数（期货/期权）
    leverage: bool = False
    kind: str = "spot"                 # spot/future/forex/crypto/option/fund/repo
    option_side: str = ""              # buyer / seller
    option_type: str = "call"
    strike: float = 0.0
    expiry: Optional[_date] = None
    last_price: float = 0.0
    borrow_fee: float = 0.0            # 累计借券费
    repo_days: int = 0
    repo_rate: float = 0.0             # 年化利率（%）
    repo_principal: float = 0.0
    repo_interest: float = 0.0
    mature_date: Optional[_date] = None
    ccy: str = "CNY"                   # 该持仓的计价货币（换算 base_currency 用）

    @property
    def available(self) -> float:
        """可卖/可平数量（扣除 T+1 冻结）。"""
        return max(self.volume - self.frozen_volume, 0.0)

    @property
    def price(self) -> float:
        return self.last_price or self.avg_cost


class TradingAccount:
    """全市场统一账户（现货/期货/外汇/期权/基金/逆回购）。"""

    def __init__(self, initial_capital: float = None, base_currency: str = "CNY",
                 fetcher=None, run_mode: str = None, logger: logging.Logger = None,
                 fx_rates: Dict[str, float] = None,
                 account_subject: str = "personal"):
        self.initial_capital = float(config.INITIAL_CASH if initial_capital is None
                                      else initial_capital)
        self.base_currency = str(base_currency or "CNY").upper()
        # 账户主体性质（v3.53 评审七轮·闸门7）：personal（默认）/institution。
        # 个人主体对衍生品市场【永久硬拦】——即使衍生品市场被错误加入
        # LIVE_ALLOWED_MARKETS 白名单也绕不过（先查主体闸再查白名单闸）。
        # 默认 personal = fail-closed：institution 必须显式声明。
        self.account_subject = str(account_subject or "personal").lower()
        self.cash = self.initial_capital
        self.frozen_cash = 0.0
        self.margin_used = 0.0
        self.positions: Dict[str, Position] = {}
        self.short_positions: Dict[str, Position] = {}
        self.trades: List[dict] = []
        self.rejected_orders: List[dict] = []
        self.daily_equity: List[dict] = []
        self.fetcher = fetcher
        self.run_mode = str(run_mode or config.RUN_MODE)
        self.logger = logger or setup_logger("account", config.LOG_DIR / "account.log")
        self.fx_rates = dict(DEFAULT_FX_RATES)
        self.fx_rates.update(fx_rates or {})
        self.fx_rates.setdefault(self.base_currency, 1.0)
        self._order_seq = 0
        self._current_date: Optional[_date] = None
        # 成交模型（仅回测挂载；实盘/模拟盘为 None，见 core/backtester.py::ExecutionModel）
        self.execution_model = None
        # 订单延迟撮合钩子（match_price_basis=next_* 时由引擎注入，返回 True 表示已入队）
        self.deferred_executor = None
        # 引擎当前 bar 下标（same_* 同根撮合时交给未来函数断言）
        self.current_bar_index = None
        # 双价体系（v3.53 评审三轮）：成交模型返回的 raw 实际成交价，
        # 仅用于成交记录披露（raw_price 列）；记账价始终是复权口径 price
        self._last_raw_fill = None

    # ==================== 基础工具 ====================

    @staticmethod
    def _to_date(value) -> _date:
        if value is None:
            return _date.today()
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, _date):
            return value
        return pd.Timestamp(value).date()

    def _fx(self, ccy: str) -> float:
        """某计价货币 → base_currency 的汇率。"""
        ccy = str(ccy or self.base_currency).upper()
        rate = float(self.fx_rates.get(ccy, 1.0))
        base = float(self.fx_rates.get(self.base_currency, 1.0))
        return rate / base if base else rate

    def _next_order_id(self) -> str:
        self._order_seq += 1
        return f"{datetime.now():%Y%m%d%H%M%S}-{self._order_seq:05d}"

    def _market_of(self, symbol: str, market_type: str = None) -> str:
        return config.detect_market_type(symbol, market_type)

    def _rule_of(self, market: str, symbol: str = "") -> dict:
        """市场规则统一入口（国内期货叠加品种级参数）。"""
        if market == "cn_future":
            rule = dict(config.get_market_config("cn_future"))
            variety = "".join(c for c in str(symbol).upper() if c.isalpha())
            rule.update(config.CN_FUTURES_VARIETY.get(variety, {}))
            return rule
        if market == "global_future":
            contracts = config.get_market_config("global_future")
            variety = "".join(c for c in str(symbol).upper() if c.isalpha())
            return dict(contracts.get(variety) or {})
        return config.get_market_config(market)

    def _reject(self, symbol, direction, reason, **extra) -> dict:
        from core import signal_gate
        code = signal_gate.classify_rejection(reason)
        reject_id = f"rej_{len(self.rejected_orders)}"
        rec = {"status": "rejected", "symbol": str(symbol), "direction": str(direction),
               "reason": str(reason), "code": code, "reject_id": reject_id}
        rec.update(extra)
        self.rejected_orders.append(rec)
        # 唯一裁决日志（报告第三出口读取同源）：禁止报告另行统计拦截数
        signal_gate.record_decision(
            symbol, direction, False, reason=reason, reason_code=code,
            source="place_order", reject_id=reject_id)
        self.logger.warning("拒单 %s %s：%s", symbol, direction, reason)
        return rec

    def _roll_to(self, day: _date) -> None:
        """换日：解除 T+1 冻结、清空今仓标记。"""
        for pos in list(self.positions.values()) + list(self.short_positions.values()):
            if pos.last_trade_date is None or day > pos.last_trade_date:
                pos.frozen_volume = 0.0
                pos.today_volume = 0.0
                pos.last_trade_date = day
        self._current_date = day

    def roll_to(self, day) -> None:
        """公开的换日入口：执行器在每根 bar 开始前调用（策略层不直接调）。"""
        self._roll_to(self._to_date(day))

    @staticmethod
    def _add_trading_days(start: _date, n: int, market: str = "cn_stock") -> _date:
        day, added = start, 0
        while added < n:
            day += timedelta(days=1)
            if is_trading_day(day, market):
                added += 1
        return day

    def _is_t0(self, market: str, symbol: str, rule: dict) -> bool:
        if market == "cn_etf":
            return any(str(symbol).startswith(str(p)) for p in rule.get("t0_prefixes", []))
        return int(rule.get("t_plus", 0) or 0) == 0

    # ==================== 手续费 ====================

    def calc_commission(self, symbol: str, direction: str, price: float, volume: float,
                        is_close_today: bool = False, market_type: str = None,
                        hold_days: int = None, is_etf: bool = None,
                        order_type: str = "market", is_open: bool = None,
                        is_maker: bool = False) -> float:
        """计算单笔总手续费（单位＝该标的计价货币，见 _MARKET_CCY）。

        is_open: 显式声明开/平仓（期货 sell 既可能开空也可能平多，必须由调用方给定）；
                 None 时按 direction 推断：buy/short→开仓，sell/cover→平仓。
        is_close_today: 期货平今仓（费率通常更高，如 IF 0.0345% vs 0.0023%）。
        hold_days: 基金赎回费按持有天数分档。
        """
        symbol = str(symbol).strip()
        market = self._market_of(symbol, market_type)
        price, volume = float(price or 0), float(volume or 0)
        if price <= 0 or volume <= 0:
            return 0.0
        if market == "cn_index":
            raise ValueError("指数不可直接交易，无手续费口径（请用 ETF/股指期货代替）")
        rule = self._rule_of(market, symbol)
        direction = str(direction or "").lower()
        if is_open is None:
            is_open = direction in ("buy", "short")

        def r2(x):
            return round(float(x), 2)

        if market in ("cn_stock", "cn_etf", "cn_convertible", "cn_reits", "neeq"):
            amount = price * volume
            comm = max(amount * float(rule.get("commission_rate", 0)),
                       float(rule.get("commission_min", 0)))
            if market == "neeq":
                comm = max(comm, 0)
            stamp = 0.0
            if not is_open:
                stamp = amount * float(rule.get("stamp_tax_rate_sell", 0) or 0)
            transfer = amount * float(rule.get("transfer_fee", 0) or 0)
            return r2(comm + stamp + transfer)

        if market in ("us_stock", "us_etf"):
            amount = price * volume
            # SEC/TAF 只在「卖出」时收：开空卖出收，买入回补（buy/cover）不收
            if direction in ("sell", "short"):
                sec = amount * float(rule.get("sec_fee_sell", 0) or 0)
                taf = volume * float(rule.get("taf_fee_sell", 0) or 0)
                return r2(sec + taf)
            return 0.0

        if market == "hk_stock":
            amount = price * volume
            etf = HK_ETF_CODES.__contains__(str(symbol)) if is_etf is None else bool(is_etf)
            comm = max(amount * float(rule.get("commission_rate", 0.0003)),
                       float(rule.get("commission_min_hkd", 3)))
            stamp = 0.0 if etf else max(math.ceil(amount * float(rule.get("stamp_tax_rate_buy", 0.001))),
                                        float(rule.get("stamp_tax_min", 1)))
            sfc = amount * float(rule.get("sfc_levy", 0) or 0)
            tf = amount * float(rule.get("trading_fee", 0) or 0)
            frc = amount * float(rule.get("frc_levy", 0) or 0)
            ccass = min(max(amount * float(rule.get("ccass_fee", 0) or 0),
                            float(rule.get("ccass_min", 2))),
                        float(rule.get("ccass_max", 100)))
            sys_fee = float(rule.get("trading_system_fee", 0) or 0)
            return r2(comm + stamp + sfc + tf + frc + ccass + sys_fee)

        if market == "cn_future":
            multiplier = float(rule.get("multiplier", 1) or 1)
            notional = price * multiplier * volume
            mode = str(rule.get("commission_type", "per_value"))
            if mode == "per_lot":
                key = ("commission_per_lot_open" if is_open else
                       ("commission_per_lot_close_today" if is_close_today
                        else "commission_per_lot_close"))
                return r2(float(rule.get(key, 0) or 0) * volume)
            key = ("commission_rate_open" if is_open else
                   ("commission_rate_close_today" if is_close_today
                    else "commission_rate_close"))
            return r2(notional * float(rule.get(key, 0) or 0))

        if market == "global_future":
            return r2(float(rule.get("commission", 0) or 0) * volume)

        if market == "forex":
            pair = symbol.upper()
            cfg = dict(rule.get("ccy_pairs", {}) or {}).get(pair, {})
            lot = FOREX_LOT_SIZE_OVERRIDE.get(pair, float(rule.get("lot_size", 100000)))
            pip = 10 ** (-int(cfg.get("pip_pos", 4)))
            pip_value = lot * pip
            spread = float(cfg.get("spread_pips", rule.get("spread_pips_default", 1.5)))
            spread_cost = spread * pip_value * volume
            comm = float(cfg.get("commission_per_lot", 0) or 0) * volume
            return r2(spread_cost + comm)

        if market == "cn_option":
            per = float(rule.get("commission_per_contract", 3))
            return r2(max(per * volume, float(rule.get("min_commission", 5))))

        if market == "crypto":
            notional = price * volume
            rate = float(rule.get("maker_fee" if is_maker else "taker_fee", 0.001))
            return r2(notional * rate)

        if market == "cn_fund":
            amount = price * volume
            if is_open:
                rate = float(rule.get("subscribe_fee_rate", 0.0015)) * \
                    float(rule.get("subscribe_fee_discount", 0.1))
                return r2(amount * rate)
            days = 0 if hold_days is None else int(hold_days)
            for limit, rate in rule.get("redeem_fee_by_days", []):
                if days < int(limit):
                    return r2(amount * float(rate))
            return 0.0

        if market == "cn_reverse_repo":
            # 逆回购：price 是年化利率（%），volume 是本金（元），手续费按本金×期限费率
            days = REPO_TERM_DAYS.get(str(symbol), 1)
            rate = float((rule.get("commission_rate", {}) or {}).get(days, 0.00001))
            return r2(float(volume) * rate)

        return 0.0

    # ==================== 下单 ====================

    def place_order(self, symbol: str, direction: str, order_type: str = "market",
                    volume: float = 0.0, price: float = None, order_time=None,
                    market_type: str = None, data: pd.DataFrame = None,
                    pre_close: float = None, underlying_price: float = None,
                    hold_days: int = None, is_etf: bool = None,
                    option_type: str = None, strike: float = None, expiry=None,
                    for_trading: bool = False, data_kind: str = "daily",
                    period: str = "60", warmup_ok: bool = None,
                    fill_now: bool = False, signal_bar_index: int = None) -> dict:
        """下单主入口，返回 {"status": "filled"/"pending"/"rejected", ...}。

        `fill_now=False` 且已注入 `deferred_executor` 时（match_price_basis=next_*），
        订单入队并返回 pending，由引擎在后续 bar 以 fill_now=True 重新撮合；
        `signal_bar_index` 用于强制「成交 bar 严格晚于决策 bar」的未来函数断言。
        """
        symbol = str(symbol).strip()
        direction = str(direction or "").lower()
        order_type = str(order_type or "market").lower()
        # 双价体系：上一单残留的 raw 成交价必须清除（防中途异常残留串单）
        self._last_raw_fill = None
        day = self._to_date(order_time)
        self._roll_to(day)

        if direction not in ("buy", "sell", "short", "cover"):
            return self._reject(symbol, direction, f"非法方向 {direction!r}")
        if order_type not in ("market", "limit"):
            return self._reject(symbol, direction, f"非法订单类型 {order_type!r}")
        try:
            volume = float(volume)
        except (TypeError, ValueError):
            return self._reject(symbol, direction, f"非法数量 {volume!r}")
        if volume <= 0:
            return self._reject(symbol, direction, "下单数量必须为正")
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            return self._reject(symbol, direction, f"非法价格 {price!r}")
        if price is None or price <= 0:
            return self._reject(symbol, direction, "缺少有效价格（下单必须给出 price）")

        market = self._market_of(symbol, market_type)
        # 闸门7（v3.53 评审七轮）：实盘两道闸，【主体闸优先于白名单闸】——
        # ① 主体闸：个人主体对衍生品市场永久硬拦，即使衍生品市场被错误加进
        #    LIVE_ALLOWED_MARKETS 也绕不过（实盘放行与回测/研究扩围解耦）；
        # ② 白名单闸：非衍生品市场必须显式列入 LIVE_ALLOWED_MARKETS。
        # 两者均直接 raise（非打印警告、非拒单返回）。
        if self.run_mode == "live":
            if (market in DERIVATIVE_MARKETS
                    and self.account_subject == "personal"):
                raise DerivativeMarketLiveForbidden(
                    f"[live] 账户主体=个人，衍生品市场 {market} 永久禁止实盘报单"
                    "（主体性质硬拦，白名单不可绕过）；期货/期权仅限回测/研究/仿真")
            if market not in LIVE_ALLOWED_MARKETS:
                raise LiveMarketForbidden(
                    f"[live] 市场 {market!r} 未列入 LIVE_ALLOWED_MARKETS 白名单"
                    f"（当前={sorted(LIVE_ALLOWED_MARKETS)}），直接 raise 硬拦；"
                    "扩市场必须显式放行并附预检回执")
        if market in _NO_ORDER_MARKETS:
            return self._reject(symbol, direction, _NO_ORDER_MARKETS[market], market=market)
        if market == "cn_index":
            rule = config.get_market_config("cn_index")
            return self._reject(symbol, direction,
                                rule.get("not_tradeable_reason", "指数不可直接交易"),
                                market=market)
        rule = self._rule_of(market, symbol)
        if not rule:
            return self._reject(symbol, direction, f"未找到 {market} 的合约规则", market=market)

        long_pos = self.positions.get(symbol)
        short_pos = self.short_positions.get(symbol)

        # ---------- 品种类别 ----------
        if market in ("cn_stock", "cn_etf", "cn_convertible", "cn_reits", "neeq",
                      "us_stock", "us_etf", "hk_stock"):
            kind = "spot"
        elif market in ("cn_future", "global_future"):
            kind = "future"
        elif market == "forex":
            kind = "forex"
        elif market == "crypto":
            kind = "crypto"
        elif market == "cn_option":
            kind = "option"
        elif market == "cn_fund":
            kind = "fund"
        else:  # cn_reverse_repo
            kind = "repo"

        # ---------- 动作判定 ----------
        can_short = bool(rule.get("can_short")) or "short" in (rule.get("trade_direction") or [])
        if kind == "option":
            can_short = True  # 期权卖方开仓是标准业务，不受标的市场 can_short 限制
        action, side = "open", "long"
        if kind == "repo":
            if direction != "sell":
                return self._reject(symbol, direction,
                                    "国债逆回购只能以 direction='sell' 融出资金", market=market)
            action, side = "open", "long"
        elif kind == "fund":
            if direction not in ("buy", "sell"):
                return self._reject(symbol, direction, "基金只支持 buy(申购)/sell(赎回)", market=market)
            action = "open" if direction == "buy" else "close"
        elif kind == "option":
            if direction == "buy":
                action = "close" if (short_pos and short_pos.volume > 0) else "open"
                side = "long" if action == "open" else "short"
            elif direction == "sell":
                action = "close" if (long_pos and long_pos.volume > 0) else "open"
                side = "short" if action == "open" else "long"
            elif direction == "short":
                action, side = "open", "short"
            else:  # cover
                action, side = "close", "short"
        elif kind in _LEVERAGED_KINDS:
            if direction == "buy":
                action = "close" if (short_pos and short_pos.volume > 0) else "open"
                side = "short" if action == "close" else "long"
            elif direction == "sell":
                action = "close" if (long_pos and long_pos.volume > 0) else "open"
                side = "long" if action == "close" else "short"
            elif direction == "short":
                action, side = "open", "short"
            else:  # cover
                action, side = "close", "short"
        else:  # spot
            if direction == "buy":
                action = "close" if (short_pos and short_pos.volume > 0) else "open"
                side = "short" if action == "close" else "long"
            elif direction == "sell":
                action, side = "close", "long"
            elif direction == "short":
                action, side = "open", "short"
            else:  # cover
                action, side = "close", "short"

        if side == "short" and not can_short:
            return self._reject(symbol, direction,
                                f"{rule.get('name', market)} 不支持做空（can_short=False）",
                                market=market)

        # ---------- 指标预热闸门（与第 3 步 B5 联动，开严平宽） ----------
        # 开仓：必须由策略层随单标记 warmup_ok=True；缺失或 False 一律拒单（最保守）；
        # 平仓/减仓：不受限——预热期也必须能止损/平仓（与 STALE_REFETCH_FAIL_POLICY 同则）。
        # 基金申赎/逆回购走净值/资金路径，不使用 K 线指标，不参与该闸门。
        # 该闸门放在撮合之前：排队成交（next_open）时拒单必须在信号当根就返回。
        if action == "open" and kind not in ("fund", "repo"):
            if warmup_ok is None:
                return self._reject(
                    symbol, direction,
                    "开仓单未携带 warmup_ok 标记（指标预热状态未知），按最保守处置拒单",
                    market=market)
            if not bool(warmup_ok):
                return self._reject(
                    symbol, direction,
                    "指标仍处于预热期（warmup_ok=False），禁止开仓；平仓/减仓不受限",
                    market=market)

        # ---------- 平仓可卖 / 整手 / 涨跌停（不依赖成交价，排队前就要给出结论） ----------

        if action == "close":
            pos = short_pos if side == "short" else long_pos
            if pos is None or pos.volume <= 0:
                return self._reject(symbol, direction, "无对应持仓可平/可卖", market=market)
            if volume > pos.available + 1e-9:
                t1 = "（T+1：当日买入数量不可卖出）" if pos.frozen_volume > 0 else ""
                return self._reject(
                    symbol, direction,
                    f"可用持仓不足：可卖 {pos.available:g} / 请求 {volume:g}{t1}", market=market)
        elif kind == "spot" and side == "long":
            step = float(rule.get("qty_step") or rule.get("min_qty") or 1)
            if abs(volume / step - round(volume / step)) > 1e-9:
                return self._reject(symbol, direction,
                                    f"{rule.get('name', market)} 买入数量必须是 {step:g} 的整数倍"
                                    f"（当前 {volume:g}）", market=market)
        elif kind == "future":
            lot_step = float(rule.get("lot_step", 1) or 1)
            if abs(volume / lot_step - round(volume / lot_step)) > 1e-9:
                return self._reject(symbol, direction, f"期货手数必须是 {lot_step:g} 的整数倍",
                                    market=market)
            min_lot = float(rule.get("min_lot", 1) or 1)
            if volume < min_lot:
                return self._reject(symbol, direction, f"低于最小手数 {min_lot:g}", market=market)
        elif kind == "forex":
            min_lot = float(rule.get("min_lot", 0.01))
            if volume < min_lot:
                return self._reject(symbol, direction, f"低于最小交易手数 {min_lot:g}", market=market)
        elif kind == "crypto":
            assets = rule.get("assets", {}) or {}
            base = "".join(c for c in symbol.upper() if c.isalpha()) or symbol.upper()
            min_qty = float((assets.get(base) or {}).get("min_qty", 0) or 0)
            if min_qty and volume < min_qty:
                return self._reject(symbol, direction, f"低于最小下单量 {min_qty:g}", market=market)
            if price * volume < float(rule.get("min_order_usd", 10)):
                return self._reject(symbol, direction, "订单名义金额低于最小下单额 (10 USD)",
                                    market=market)
        elif kind == "option":
            if abs(volume - round(volume)) > 1e-9:
                return self._reject(symbol, direction, "期权张数必须为整数", market=market)
        elif kind == "repo":
            if not self._check_repo_lot(symbol, volume):
                return self._reject(symbol, direction,
                                    "逆回购金额不满足起点/整数倍（沪 10 万、深 1000 元）",
                                    market=market)

        # ---------- 涨跌停 ----------
        if action == "open" and pre_close:
            msg = self._check_price_limit(market, symbol, rule, price, float(pre_close))
            if msg:
                return self._reject(symbol, direction, msg, market=market)

        # ---------- 数据时效闸门（独立复核，不依赖传入帧） ----------
        try:
            self._check_freshness(symbol, market, order_side=action, data=data,
                                  for_trading=for_trading, data_kind=data_kind, period=period)
        except Exception as exc:  # noqa: BLE001
            return self._reject(symbol, direction, f"数据时效复核未通过：{exc}", market=market)

        # ---------- 撮合时点：match_price_basis=next_* 时挂起到后续 bar 成交 ----------
        # 决策 bar 与成交 bar 必须分离（禁止用同根 bar 的开盘/收盘成交 = 未来函数）。
        # 排队点放在「不依赖成交价」的校验（方向/整手/可平数量/涨跌停/时效）之后，
        # 这样预热期、T+1 冻结、无持仓等拒单仍在信号当根立即返回。
        if self.deferred_executor is not None and not fill_now:
            queued = self.deferred_executor(dict(
                symbol=symbol, direction=direction, order_type=order_type,
                volume=volume, price=price, order_time=order_time,
                market_type=market_type, data=data, pre_close=pre_close,
                underlying_price=underlying_price, hold_days=hold_days,
                is_etf=is_etf, option_type=option_type, strike=strike,
                expiry=expiry, for_trading=for_trading, data_kind=data_kind,
                period=period, warmup_ok=warmup_ok,
                signal_bar_index=signal_bar_index))
            if queued:
                return {"status": "pending", "symbol": symbol, "direction": direction,
                        "volume": volume, "price": price, "deferred": True,
                        "reason": "已排队：按 EXECUTION_MODEL['match_price_basis'] "
                                  "在后续 bar 撮合"}

        # ---------- 成交模型（滑点/涨跌停/成交量上限/基准价，唯一实现在 core/execution.py） ----------
        if self.execution_model is not None:
            # same_* 基准没有延迟撮合：本根 bar 既是决策 bar 又是成交 bar，
            # 必须交给 assert_fill_after_signal 判定（enforce=True 时直接报错）。
            if (signal_bar_index is None
                    and int(getattr(self.execution_model, "bar_offset", 1)) == 0):
                signal_bar_index = self.current_bar_index
            try:
                decision = self.execution_model.check(
                    symbol=symbol, direction=direction, action=action,
                    order_type=order_type, volume=volume, price=price,
                    market=market, rule=rule, day=day,
                    signal_bar_index=signal_bar_index)
            except Exception as exc:  # noqa: BLE001
                from core.execution import LookaheadError
                if isinstance(exc, LookaheadError):
                    raise                      # 未来函数是硬错误，不得降级为普通拒单
                return self._reject(symbol, direction, f"成交模型异常：{exc}", market=market)
            if decision.get("reject"):
                return self._reject(symbol, direction, decision["reject"], market=market)
            price = float(decision.get("price", price) or price)
            volume = float(decision.get("volume", volume) or volume)
            # 双价体系：暂存 raw 实际成交价（_trade_record 落盘 raw_price 列）；
            # 记账 price 已是复权口径（成交模型内 raw_fill × adj_factor 换算）
            self._last_raw_fill = decision.get("raw_price")

        # ---------- 资金 / 保证金 / 成交 ----------
        try:
            return self._execute(symbol, market, rule, kind, action, side, direction,
                                 volume, price, day, order_time, is_etf,
                                 underlying_price, hold_days, option_type, strike, expiry)
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("下单执行异常 %s %s", symbol, direction)
            return self._reject(symbol, direction, f"下单执行异常：{exc}", market=market)

    # ---------- 时效闸门 ----------

    def _check_freshness(self, symbol, market, order_side, data, for_trading,
                         data_kind="daily", period="60"):
        """第三道防线：refetch 为主；没有决策帧也能独立复核。"""
        frame = data
        if frame is None or getattr(frame, "empty", True):
            # 不依赖调用方帧：给 data 层一个只含 symbol 的占位帧，
            # 真正的时效来自 refetch（market+symbol 已在闸门手上）。
            frame = pd.DataFrame({"symbol": [str(symbol)]})
        return assert_fresh_for_trading(
            frame, kind=data_kind, market=market, symbol=symbol,
            fetcher=self.fetcher, period=period, run_mode=self.run_mode,
            for_trading=bool(for_trading), order_side=str(order_side))

    # ---------- 涨跌停 ----------

    @staticmethod
    def price_limit_pct(market, symbol, rule) -> Optional[float]:
        """该标的的涨跌停比例（None 表示无涨跌停限制）。回测成交模型复用同一口径。"""
        limit = rule.get("price_limit")
        pct = None
        if market == "cn_stock":
            table = limit or {}
            pct = float(table.get("main", 0.1))
            if str(symbol).startswith("688"):
                pct = float(table.get("kcb", 0.2))
            elif str(symbol)[:3] in ("300", "301"):
                pct = float(table.get("cyb", 0.2))
            elif str(symbol)[:1] in ("4", "8"):
                pct = float(table.get("bj", 0.3))
        elif market == "cn_etf":
            table = limit or {}
            pct = 0.2 if str(symbol)[:3] in ("513", "518") else float(table.get("default", 0.1))
        elif market in ("cn_convertible", "cn_reits", "neeq"):
            pct = float(limit or 0) or None
        elif market == "cn_future":
            pct = float(limit or 0) or None
        elif isinstance(limit, (int, float)):
            pct = float(limit)
        return pct or None

    @staticmethod
    def _check_price_limit(market, symbol, rule, price, pre_close):
        if pre_close <= 0:
            return None
        pct = TradingAccount.price_limit_pct(market, symbol, rule)
        if not pct:
            return None
        hi, lo = pre_close * (1 + pct), pre_close * (1 - pct)
        if not (lo - 1e-9 <= price <= hi + 1e-9):
            return f"价格 {price:g} 超出涨跌停区间 [{lo:.4f}, {hi:.4f}]（前收 {pre_close:g}）"
        return None

    @staticmethod
    def _check_repo_lot(symbol: str, amount: float) -> bool:
        sh = str(symbol).startswith("204")
        base = 100000.0 if sh else 1000.0
        return amount >= base - 1e-6 and abs(amount / base - round(amount / base)) < 1e-9

    # ---------- 成交执行 ----------

    def _execute(self, symbol, market, rule, kind, action, side, direction,
                 volume, price, day, order_time, is_etf, underlying_price,
                 hold_days, option_type, strike, expiry) -> dict:
        ccy = _MARKET_CCY.get(market, "CNY")
        # 合约参数
        multiplier = 1.0
        if kind == "option":
            multiplier = float(rule.get("contract_multiplier", 1) or 1)
        elif kind == "future":
            multiplier = float(rule.get("multiplier", 1) or 1)
        elif kind == "forex":
            pair = symbol.upper()
            multiplier = FOREX_LOT_SIZE_OVERRIDE.get(pair, float(rule.get("lot_size", 100000)))
            ccy = pair[3:6] if len(pair) >= 6 else "USD"
        fx = self._fx(ccy)   # 标的计价货币 → base_currency

        is_future_close = (kind in _LEVERAGED_KINDS and action == "close")
        pos_ref = self.positions.get(symbol) if side == "long" else self.short_positions.get(symbol)
        close_today = bool(is_future_close and pos_ref is not None and pos_ref.today_volume > 0)

        hold = hold_days
        if kind == "fund" and action == "close" and hold is None and pos_ref is not None:
            open_day = pos_ref.open_date or day
            hold = max((day - open_day).days, 0)

        fee_local = self.calc_commission(
            symbol, direction, price, volume,
            is_close_today=close_today, market_type=market, hold_days=hold,
            is_etf=is_etf, is_open=(action == "open"), is_maker=False)
        fee = fee_local * fx

        order_id = self._next_order_id()
        realized = 0.0

        # ---------- 开仓 ----------
        if action == "open":
            if kind == "repo":
                days = REPO_TERM_DAYS.get(str(symbol), 1)
                principal = volume
                need = principal + fee
                if self.cash < need:
                    return self._reject(symbol, direction,
                                        f"可用资金不足：需 {need:.2f}，可用 {self.cash:.2f}",
                                        market=market)
                self.cash -= need
                rate = float(price)  # 年化利率 %
                interest = round(principal * (rate / 100.0) * days / 365.0, 2)
                pos = Position(symbol=symbol, market=market, direction="long",
                               volume=principal, avg_cost=1.0,
                               open_date=day, last_trade_date=day, kind="repo",
                               repo_days=days, repo_rate=rate,
                               repo_principal=principal, repo_interest=interest,
                               mature_date=self._add_trading_days(day, days, "cn_stock"))
                self.positions[symbol] = pos
                self.trades.append(self._trade_record(order_id, symbol, market, direction,
                                                      "open", price, volume, fee, 0.0,
                                                      order_time))
                self.logger.info("逆回购 %s 本金 %.2f 利率 %.3f%% %d 天，到期 %s 利息 %.2f",
                                 symbol, principal, rate, days, pos.mature_date, interest)
                return {"status": "filled", "order_id": order_id, "symbol": symbol,
                        "market": market, "action": "open", "price": price,
                        "volume": volume, "commission": round(fee, 2),
                        "cash_after": round(self.cash, 2),
                        "mature_date": str(pos.mature_date),
                        "interest": interest}

            local_notional = price * volume * (1.0 if kind == "fund" else multiplier)
            notional = local_notional * fx
            margin_req = self._margin_required(kind, rule, symbol, price, volume,
                                               multiplier, notional, side,
                                               underlying_price, option_type, fx)
            if kind == "option" and side == "short" and not underlying_price:
                self.logger.warning(
                    "期权卖方 %s 未提供 underlying_price，保证金按权利金市值估算（偏低）", symbol)

            # 资金/保证金校验
            if kind == "spot" and side == "long":
                need = notional + fee
            elif kind == "spot" and side == "short":
                need = margin_req + fee
            elif kind in _LEVERAGED_KINDS:
                need = margin_req + fee
            elif kind == "option" and side == "long":
                need = notional + fee
            elif kind == "option" and side == "short":
                need = margin_req + fee - notional  # 收权利金后再冻结保证金
            elif kind == "fund":
                need = notional + fee
            else:
                need = notional + fee
            if self.cash + 1e-9 < need:
                return self._reject(symbol, direction,
                                    f"可用资金不足：需 {need:.2f}，可用 {self.cash:.2f}",
                                    market=market)

            # 记账
            if kind == "spot" and side == "long":
                self.cash -= (notional + fee)
                pos = self.positions.get(symbol) or Position(
                    symbol=symbol, market=market, direction="long", kind="spot")
                new_vol = pos.volume + volume
                pos.avg_cost = (pos.avg_cost * pos.volume + local_notional + fee_local) / new_vol
                pos.volume = new_vol
                pos.multiplier = 1.0
                pos.open_date = pos.open_date or day
                pos.last_trade_date = day
                if not self._is_t0(market, symbol, rule):
                    pos.frozen_volume += volume
                self.positions[symbol] = pos
            elif kind == "spot" and side == "short":
                self.cash += (notional - fee)
                pos = self.short_positions.get(symbol) or Position(
                    symbol=symbol, market=market, direction="short", kind="spot")
                new_vol = pos.volume + volume
                pos.avg_cost = (pos.avg_cost * pos.volume + local_notional - fee_local) / new_vol
                pos.volume = new_vol
                pos.margin_rate = float(rule.get("margin_rate", 0.5))
                pos.margin += margin_req
                pos.leverage = False
                pos.open_date = pos.open_date or day
                pos.last_trade_date = day
                self.margin_used += margin_req
                self.short_positions[symbol] = pos
            elif kind in _LEVERAGED_KINDS:
                self.cash -= (margin_req + fee)
                book = self.positions if side == "long" else self.short_positions
                pos = book.get(symbol) or Position(
                    symbol=symbol, market=market, direction=side, kind=kind)
                new_vol = pos.volume + volume
                pos.avg_cost = (pos.avg_cost * pos.volume + price * volume) / new_vol
                pos.volume = new_vol
                pos.multiplier = multiplier
                pos.margin_rate = (float(rule.get("margin_rate", 0)) if market == "cn_future"
                                   else (1.0 / float(rule.get("leverage", 100))
                                         if market == "forex" else 1.0))
                pos.margin += margin_req
                pos.leverage = True
                pos.today_volume += volume
                pos.open_date = pos.open_date or day
                pos.last_trade_date = day
                self.margin_used += margin_req
                book[symbol] = pos
            elif kind == "option" and side == "long":
                self.cash -= (notional + fee)
                pos = self.positions.get(symbol) or Position(
                    symbol=symbol, market=market, direction="long", kind="option",
                    option_side="buyer", option_type=str(option_type or "call").lower())
                new_vol = pos.volume + volume
                pos.avg_cost = (pos.avg_cost * pos.volume + local_notional) / new_vol
                pos.volume = new_vol
                pos.multiplier = multiplier
                pos.strike = float(strike or pos.strike or 0.0)
                pos.expiry = self._to_date(expiry) if expiry else pos.expiry
                pos.open_date = pos.open_date or day
                pos.last_trade_date = day
                self.positions[symbol] = pos
            elif kind == "option" and side == "short":
                self.cash += (notional - fee)
                self.cash -= margin_req
                self.margin_used += margin_req
                pos = self.short_positions.get(symbol) or Position(
                    symbol=symbol, market=market, direction="short", kind="option",
                    option_side="seller", option_type=str(option_type or "call").lower())
                new_vol = pos.volume + volume
                pos.avg_cost = (pos.avg_cost * pos.volume + local_notional) / new_vol
                pos.volume = new_vol
                pos.multiplier = multiplier
                pos.margin += margin_req
                pos.strike = float(strike or pos.strike or 0.0)
                pos.expiry = self._to_date(expiry) if expiry else pos.expiry
                pos.open_date = pos.open_date or day
                pos.last_trade_date = day
                self.short_positions[symbol] = pos
            elif kind == "fund":
                self.cash -= (notional + fee)
                pos = self.positions.get(symbol) or Position(
                    symbol=symbol, market=market, direction="long", kind="fund")
                new_vol = pos.volume + volume
                pos.avg_cost = (pos.avg_cost * pos.volume + local_notional + fee_local) / new_vol
                pos.volume = new_vol
                pos.open_date = pos.open_date or day
                pos.last_trade_date = day
                self.positions[symbol] = pos

            pos.ccy = ccy
            pos.last_price = price
            self.trades.append(self._trade_record(order_id, symbol, market, direction,
                                                  "open", price, volume, fee, 0.0,
                                                  order_time))
            self.logger.info("成交 %s %s %s %g @ %.4f 手续费 %.2f 剩余资金 %.2f",
                             market, symbol, direction, volume, price, fee, self.cash)
            return {"status": "filled", "order_id": order_id, "symbol": symbol,
                    "market": market, "direction": direction, "action": "open",
                    "price": price, "volume": volume,
                    "commission": round(fee, 2),
                    "margin": round(margin_req, 2),
                    "cash_after": round(self.cash, 2),
                    "margin_used": round(self.margin_used, 2)}

        # ---------- 平仓 ----------
        pos = self.short_positions.get(symbol) if side == "short" else self.positions.get(symbol)
        if pos is None or pos.volume < volume - 1e-9:
            return self._reject(symbol, direction, "持仓数量不足", market=market)
        local_notional = price * volume * (1.0 if kind == "fund" else multiplier)
        notional = local_notional * fx
        rel_margin = pos.margin * (volume / pos.volume) if pos.volume else 0.0

        if kind == "spot" and side == "long":
            self.cash += (notional - fee)
            realized = (price - pos.avg_cost) * volume * fx - fee
        elif kind == "spot" and side == "short":
            self.cash -= (notional + fee)
            realized = (pos.avg_cost - price) * volume * fx - fee
            self.margin_used -= rel_margin
            pos.margin -= rel_margin
        elif kind in _LEVERAGED_KINDS:
            sign = 1.0 if side == "long" else -1.0
            pnl = (price - pos.avg_cost) * multiplier * volume * sign * fx
            self.cash += (rel_margin + pnl - fee)
            self.margin_used -= rel_margin
            pos.margin -= rel_margin
            realized = pnl - fee
        elif kind == "option" and pos.option_side == "buyer":
            self.cash += (notional - fee)
            realized = (price - pos.avg_cost) * multiplier * volume * fx - fee
        elif kind == "option" and pos.option_side == "seller":
            self.cash -= (notional + fee)
            self.cash += rel_margin
            self.margin_used -= rel_margin
            pos.margin -= rel_margin
            realized = (pos.avg_cost - price) * multiplier * volume * fx - fee
        elif kind == "fund":
            self.cash += (notional - fee)
            realized = (price - pos.avg_cost) * volume * fx - fee
        elif kind == "repo":
            return self._reject(symbol, direction, "国债逆回购不能提前卖出，持有至到期回款",
                                market=market)
        else:
            self.cash += (notional - fee)
            realized = (price - pos.avg_cost) * volume - fee

        pos.volume -= volume
        pos.realized_pnl += realized
        pos.last_price = price
        if pos.volume <= 1e-9:
            book = self.short_positions if side == "short" else self.positions
            book.pop(symbol, None)

        self.trades.append(self._trade_record(order_id, symbol, market, direction, "close",
                                              price, volume, fee, realized, order_time))
        self.logger.info("平仓 %s %s %s %g @ %.4f 盈亏 %.2f 手续费 %.2f 剩余资金 %.2f",
                         market, symbol, direction, volume, price, realized, fee, self.cash)
        return {"status": "filled", "order_id": order_id, "symbol": symbol,
                "market": market, "direction": direction, "action": "close",
                "price": price, "volume": volume, "commission": round(fee, 2),
                "realized_pnl": round(realized, 2),
                "cash_after": round(self.cash, 2),
                "margin_used": round(self.margin_used, 2)}

    @staticmethod
    def _margin_required(kind, rule, symbol, price, volume, multiplier, notional, side,
                         underlying_price=None, option_type="call",
                         fx: float = 1.0) -> float:
        """开仓所需保证金（现货买入返回 0，由调用方按 notional 全额校验）。"""
        if kind == "spot":
            if side == "long":
                return 0.0
            return notional * float(rule.get("margin_rate", 0.5) or 0.5)
        if kind == "future":
            if "margin" in rule and rule.get("ccy"):  # 国际期货：每手固定保证金（USD→base）
                return float(rule.get("margin", 0) or 0) * volume * fx
            return notional * float(rule.get("margin_rate", 0.1) or 0.1)
        if kind == "forex":
            return notional / float(rule.get("leverage", 100) or 100)
        if kind == "crypto":
            return notional  # 现货全额；杠杆合约请显式扩展
        if kind == "option":
            if side == "long":
                return 0.0
            rates = rule.get("seller_margin_rate", {}) or {}
            rate = float(rates.get(str(option_type or "call").lower(),
                                    rates.get("call", 0.12)))
            if underlying_price and underlying_price > 0:
                base_value = float(underlying_price) * multiplier * volume * fx
            else:
                base_value = notional  # 无标的价格时退化：按权利金市值估算（调用方需 WARNING）
            return notional + base_value * rate
        return 0.0

    def _trade_record(self, order_id, symbol, market, direction, action, price, volume,
                      fee, realized, order_time) -> dict:
        # 双价体系：raw_price = 交易所实际成交价（撮合/披露口径）；
        # price = 复权口径记账价（现金/pnl/权益）。未挂成交模型时两者一致（None）
        raw_fill = self._last_raw_fill
        self._last_raw_fill = None
        return {
            "order_id": order_id, "symbol": symbol, "market": market,
            "direction": direction, "action": action, "price": round(float(price), 6),
            "volume": float(volume), "commission": round(float(fee), 2),
            "pnl": round(float(realized), 2),
            "raw_price": (round(float(raw_fill), 6)
                          if raw_fill is not None else None),
            "timestamp": order_time or datetime.now(),
            "cash_after": round(self.cash, 2),
            "margin_used": round(self.margin_used, 2),
        }

    # ==================== 权益 / 保证金 ====================

    def _mark_value(self, pos: Position, px: float) -> float:
        """单个持仓计入总权益的市值（保证金已从 cash 划出，这里加回）。"""
        fx = self._fx(pos.ccy)
        if pos.kind == "repo":
            return pos.volume  # 本金待到期回款
        if pos.kind == "spot":
            return pos.volume * px * fx if pos.direction == "long" else -pos.volume * px * fx
        if pos.kind == "option":
            if pos.option_side == "buyer":
                return pos.volume * px * pos.multiplier * fx
            return pos.margin + (pos.avg_cost - px) * pos.multiplier * pos.volume * fx
        if pos.kind in _LEVERAGED_KINDS:
            sign = 1.0 if pos.direction == "long" else -1.0
            pnl = (px - pos.avg_cost) * pos.multiplier * pos.volume * sign * fx
            return pos.margin + pnl
        return pos.volume * px * fx

    def calc_equity(self, current_prices: dict = None) -> float:
        """总权益 = 可用资金 + 冻结资金 + Σ 各持仓市值/保证金+浮盈。

        口径说明：期货/外汇/期权卖方的保证金是从 cash 划入 margin_used 的「自己的钱」，
        因此这里把 margin 加回，只额外计入浮动盈亏；现货空头按负市值计（卖空所得已入 cash）。
        """
        prices = current_prices or {}
        equity = self.cash + self.frozen_cash
        for pos in list(self.positions.values()) + list(self.short_positions.values()):
            px = float(prices.get(pos.symbol, pos.last_price or pos.avg_cost) or pos.avg_cost)
            pos.last_price = px
            pos.unrealized_pnl = self._unrealized(pos, px)
            equity += self._mark_value(pos, px)
        return equity

    def _unrealized(self, pos: Position, px: float) -> float:
        fx = self._fx(pos.ccy)
        if pos.kind == "spot":
            sign = 1.0 if pos.direction == "long" else -1.0
            return (px - pos.avg_cost) * pos.volume * sign * fx
        if pos.kind == "option":
            sign = 1.0 if pos.option_side == "buyer" else -1.0
            return (px - pos.avg_cost) * pos.multiplier * pos.volume * sign * fx
        if pos.kind in _LEVERAGED_KINDS:
            sign = 1.0 if pos.direction == "long" else -1.0
            return (px - pos.avg_cost) * pos.multiplier * pos.volume * sign * fx
        return 0.0

    def check_margin_call(self, current_prices: dict = None) -> List[str]:
        """维持保证金不足（可用资金<0 或 权益<保证金）时，按浮亏从大到小强平。"""
        prices = current_prices or {}
        closed: List[str] = []
        if self.margin_used <= 0:
            if self.cash >= 0:
                return closed
        safety = 1.2
        while True:
            equity = self.calc_equity(prices)
            need_force = self.cash < 0 or (self.margin_used > 0 and
                                           equity < self.margin_used * safety)
            if not need_force:
                return closed
            candidates = [(p, self._unrealized(
                p, float(prices.get(p.symbol, p.last_price or p.avg_cost))))
                for p in list(self.short_positions.values()) + list(self.positions.values())
                if p.leverage or p.kind == "option"]
            if not candidates:
                self.logger.warning("保证金不足但无可强平持仓（cash=%.2f, margin=%.2f）",
                                    self.cash, self.margin_used)
                return closed
            pos = min(candidates, key=lambda item: item[1])[0]
            px = float(prices.get(pos.symbol, pos.last_price or pos.avg_cost))
            direction = "cover" if pos.direction == "short" and pos.kind == "spot" else (
                "buy" if pos.direction == "short" else "sell")
            res = self._execute(pos.symbol, pos.market, self._rule_of(pos.market, pos.symbol),
                                pos.kind, "close", pos.direction, direction,
                                pos.volume, px, self._current_date or _date.today(), None,
                                None, None, None, None, None)
            closed.append(pos.symbol)
            self.logger.warning("强制平仓 %s（浮亏 %.2f），结果 %s",
                                pos.symbol, pos.unrealized_pnl, res.get("status"))
            if res.get("status") != "filled":
                return closed

    # ==================== 每日结算 ====================

    def daily_settlement(self, settle_prices: dict = None, date=None) -> float:
        """期货/外汇每日无负债结算：按结算价划转盈亏、重算保证金、重置今仓。"""
        prices = settle_prices or {}
        day = self._to_date(date)
        total_pnl = 0.0
        for book in (self.positions, self.short_positions):
            for symbol, pos in list(book.items()):
                if not pos.leverage or pos.kind not in _LEVERAGED_KINDS:
                    continue
                px = float(prices.get(symbol, pos.last_price or pos.avg_cost) or pos.avg_cost)
                sign = 1.0 if pos.direction == "long" else -1.0
                fx = self._fx(pos.ccy)
                pnl = (px - pos.avg_cost) * pos.multiplier * pos.volume * sign * fx
                if abs(pnl) > 1e-12:
                    self.cash += pnl
                    pos.realized_pnl += pnl
                    total_pnl += pnl
                pos.avg_cost = px
                fx = self._fx(pos.ccy)
                new_margin = self._margin_required(
                    pos.kind, self._rule_of(pos.market, symbol), symbol, px, pos.volume,
                    pos.multiplier, px * pos.multiplier * pos.volume * fx, pos.direction,
                    None, "call", fx)
                delta = new_margin - pos.margin
                if abs(delta) > 1e-12:
                    self.cash -= delta
                    self.margin_used += delta
                    pos.margin = new_margin
                pos.today_volume = 0.0
                pos.last_price = px
        if abs(total_pnl) > 1e-12:
            self.logger.info("每日结算 %s 划转盈亏 %.2f", day, total_pnl)
        return total_pnl

    def end_of_day(self, date=None, current_prices: dict = None) -> dict:
        """日终处理：结算 → 借券费 → 逆回购到期 → 期权到期 → 记录权益。"""
        day = self._to_date(date)
        prices = dict(current_prices or {})
        self._roll_to(day)

        # 1) 期货/外汇每日无负债结算
        self.daily_settlement(prices, day)

        # 2) 借券费（美股/港股空头，按年化短借费率/365 计提）
        for symbol, pos in list(self.short_positions.items()):
            if pos.kind != "spot" or pos.market not in ("us_stock", "hk_stock"):
                continue
            rule = self._rule_of(pos.market, symbol)
            rate = float(rule.get("short_borrow_fee", 0) or 0)
            if rate <= 0:
                continue
            px = float(prices.get(symbol, pos.last_price or pos.avg_cost) or pos.avg_cost)
            fee = pos.volume * px * rate / 365.0 * self._fx(_MARKET_CCY.get(pos.market, "USD"))
            if fee > 0:
                self.cash -= fee
                pos.borrow_fee += fee

        # 3) 国债逆回购到期回款
        for symbol, pos in list(self.positions.items()):
            if pos.kind != "repo" or pos.mature_date is None:
                continue
            if day >= pos.mature_date:
                self.cash += pos.repo_principal + pos.repo_interest
                self.trades.append({
                    "order_id": self._next_order_id(), "symbol": symbol,
                    "market": pos.market, "direction": "mature", "action": "close",
                    "price": 0.0, "volume": pos.repo_principal, "commission": 0.0,
                    "pnl": pos.repo_interest, "timestamp": datetime.now(),
                    "cash_after": round(self.cash, 2),
                    "margin_used": round(self.margin_used, 2),
                })
                self.logger.info("逆回购到期 %s 回款本金 %.2f + 利息 %.2f",
                                 symbol, pos.repo_principal, pos.repo_interest)
                self.positions.pop(symbol, None)

        # 4) 期权到期：有标的价格才判实值，否则只告警不臆造行权
        for book, is_short in ((self.positions, False), (self.short_positions, True)):
            for symbol, pos in list(book.items()):
                if pos.kind != "option" or pos.expiry is None or day < pos.expiry:
                    continue
                underlying = prices.get(f"{symbol}_underlying")
                if underlying is None:
                    self.logger.warning(
                        "期权 %s 已到到期日 %s，但未提供标的价格（%s_underlying），"
                        "无法判定实值/虚值，跳过自动行权", symbol, pos.expiry, symbol)
                    continue
                intrinsic = (max(0.0, float(underlying) - pos.strike)
                             if pos.option_type == "call"
                             else max(0.0, pos.strike - float(underlying)))
                payoff = intrinsic * pos.multiplier * pos.volume
                if is_short:
                    payoff = -payoff
                self.cash += payoff
                pos.realized_pnl += payoff
                self.logger.info("期权到期 %s 行权收益 %.2f", symbol, payoff)
                book.pop(symbol, None)

        # 5) 快照（分钟级保留完整 bar 时间戳：日期部分用于换日记账，快照
        # date 保留原始精度，防 equity.csv 同日多行无法区分（v3.53 评审二轮）
        equity = self.calc_equity(prices)
        snap_date = date if date is not None and not isinstance(date, str) else day
        snapshot = {
            "date": snap_date, "equity": round(equity, 2), "cash": round(self.cash, 2),
            "frozen_cash": round(self.frozen_cash, 2),
            "margin_used": round(self.margin_used, 2),
            "position_count": len(self.positions) + len(self.short_positions),
        }
        self.daily_equity.append(snapshot)
        self.logger.info("日终 %s 权益 %.2f（现金 %.2f 保证金 %.2f 持仓 %d）",
                         day, equity, self.cash, self.margin_used,
                         len(self.positions) + len(self.short_positions))
        return snapshot

    # ==================== 查询辅助 ====================

    def get_position(self, symbol: str, side: str = "long") -> Optional[Position]:
        book = self.short_positions if str(side).lower() == "short" else self.positions
        return book.get(str(symbol))

    def summary(self, current_prices: dict = None) -> dict:
        equity = self.calc_equity(current_prices)
        return {
            "initial_capital": round(self.initial_capital, 2),
            "cash": round(self.cash, 2),
            "frozen_cash": round(self.frozen_cash, 2),
            "margin_used": round(self.margin_used, 2),
            "equity": round(equity, 2),
            "return_pct": round((equity / self.initial_capital - 1) * 100, 4)
            if self.initial_capital else 0.0,
            "long_positions": len(self.positions),
            "short_positions": len(self.short_positions),
            "trades": len(self.trades),
            "rejected": len(self.rejected_orders),
        }
