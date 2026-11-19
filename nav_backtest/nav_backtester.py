# -*- coding: utf-8 -*-
"""第 10 步开工前置 · 净值型产品回测与三层净值（nav_backtest/nav_backtester.py）

**G2：净值口径不得「美容」——三层净值必须分清**
================================================================
单一产品净值曲线算不出投资者费后净值：业绩报酬（carry）是 per-investor 的，
不同申购时点 → 不同高水位 → 不同计提。本模块显式输出三层：

* ``product_gross``：产品毛净值，只含投资损益；
* ``product_net``  ：产品费后净值，扣管理费 + 托管费（产品级）；
* ``investor_net`` ：投资者费后净值，再扣申购费 / 赎回费 / 按投资者高水位计提的
  业绩报酬。**对外披露固定用 ``investor_net``**（``config.NAV_PRODUCT_CONFIG
  ["disclosure_layer"]``），报告里的「组合净值曲线」禁止拿产品毛净值充数。

同时给出「业绩报酬计提明细」（``NavResult.performance_fees``），并与投资者层净值
对账（``NavResult.reconcile()``）。

**G3：净值披露滞后 = 结构性未来函数**
================================================================
周频净值次周一/二才披露，月频十年仅约 120 点。``enforce_decision_after_disclosure``
为 True 时，任何 ``decision_date`` 必须满足
``decision_date >= nav_date + disclosure_lag_days``；违反直接抛
:class:`DisclosureLagError`（不是告警）。净值序列**禁用 K 线类指标**：
``to_kline()`` / ``assert_not_kline()`` 对 ``forbid_nav_as_kline=True`` 直接报错。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

import config

__all__ = [
    "DisclosureLagError",
    "NavAsKlineError",
    "NavBacktester",
    "NavLayers",
    "NavResult",
]

logger = logging.getLogger(__name__)

NAV_ONLY_MARKETS = tuple(config.INDICATOR_CONFIG.get("nav_only_markets") or ())


class DisclosureLagError(RuntimeError):
    """决策日早于「净值披露日 + 披露滞后」——结构性未来函数，直接拒绝。"""


class NavAsKlineError(RuntimeError):
    """净值序列被当作 K 线使用（禁用 K 线类指标）。"""


# ==================== 数据结构 ====================

@dataclass
class NavLayers:
    product_gross: pd.Series
    product_net: pd.Series
    investor_net: pd.Series

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame({"product_gross": self.product_gross,
                             "product_net": self.product_net,
                             "investor_net": self.investor_net}).sort_index()

    def get(self, layer: str) -> pd.Series:
        layer = str(layer or "investor_net")
        if layer not in ("product_gross", "product_net", "investor_net"):
            raise ValueError(f"未知净值层 {layer!r}")
        return getattr(self, layer)


@dataclass
class _Investor:
    investor_id: str
    units: float = 0.0
    hwm: float = 0.0                 # 每份高水位（product_net 口径）
    carry_accrued: float = 0.0       # 已计提未支付的业绩报酬
    carry_paid: float = 0.0
    subscribed: float = 0.0
    first_date: Optional[pd.Timestamp] = None

    def equity(self, unit_nav: float) -> float:
        return self.units * unit_nav - self.carry_accrued


# ==================== 引擎 ====================

class NavBacktester:
    """净值型产品回测：三层净值 + 逐投资者高水位 + 披露滞后闸门。"""

    def __init__(self, product_type: str = "private_fund",
                 product_config: Dict = None,
                 fee_model: Dict = None,
                 initial_capital: float = 1_000_000.0,
                 annual_days: int = 365,
                 logger_: logging.Logger = None) -> None:
        self.cfg = dict(product_config or config.NAV_PRODUCT_CONFIG)
        self.product_type = str(product_type)
        self.fee_model = dict(fee_model or self.cfg.get("fee_model") or {})
        self.initial_capital = float(initial_capital)
        self.annual_days = int(annual_days)
        self.logger = logger_ or logger
        self.freq = str((self.cfg.get("disclosure_frequency") or {}).get(self.product_type,
                                                                       "weekly"))
        self.lag_days = int((self.cfg.get("disclosure_lag_days") or {}).get(self.product_type, 2))
        self.enforce_decision_after_disclosure = bool(
            self.cfg.get("enforce_decision_after_disclosure", True))
        self.forbid_nav_as_kline = bool(self.cfg.get("forbid_nav_as_kline", True))
        # 10.3：开放日 = 净值披露日（私募/资管只能按开放日申购赎回）；
        # 锁定期按产品类型配置，赎回款 T+N 到账前不得再投资。
        self.enforce_open_day = bool(self.cfg.get("enforce_open_day", True))
        self.lockup_days = dict(self.cfg.get("lockup_days") or {})
        self.settlement_days = dict(self.cfg.get("redemption_settlement_days") or {})

        self._gross: Optional[pd.Series] = None
        self._investors: Dict[str, _Investor] = {}
        self._subscriptions: List[dict] = []
        self._redemptions: List[dict] = []
        self._fee_ledger: List[dict] = []
        self._fee_breakdown = {k: 0.0 for k in
                               ("subscription", "redemption", "management",
                                "performance", "custodian")}
        self._product_units: float = 0.0     # 产品总份额（投资者持有）
        self._result: Optional[NavResult] = None
        self._ran = False

    # ------------------------------------------------------------------
    # 输入
    # ------------------------------------------------------------------
    def set_nav(self, nav: pd.Series) -> "NavBacktester":
        """设置产品毛净值序列（index 为披露/估值日，values 为单位净值）。"""
        if isinstance(nav, pd.DataFrame):
            col = "nav" if "nav" in nav.columns else nav.columns[0]
            nav = nav[col]
        series = pd.Series(nav).astype(float).dropna()
        series.index = pd.to_datetime(series.index)
        series = series.sort_index()
        series = series[series > 0]
        if len(series) < 2:
            raise ValueError("净值序列至少需要 2 个有效点")
        self._gross = series
        return self

    def load_nav_csv(self, path, date_col: str = "date", nav_col: str = "nav") -> "NavBacktester":
        frame = pd.read_csv(path)
        frame[date_col] = pd.to_datetime(frame[date_col])
        return self.set_nav(frame.set_index(date_col)[nav_col])

    # ------------------------------------------------------------------
    # 申赎（与合格投资者闸门同一收口）
    # ------------------------------------------------------------------
    def subscribe(self, investor_id: str, on, amount: float, *,
                  qi_checker=None, profile: Dict = None, product_type: str = None,
                  action: str = "subscribe", amount_wan: float = None,
                  decision_date=None, investor_count: int = None,
                  investors: Iterable[dict] = None, vehicle: Dict = None) -> dict:
        """申购 / 追加申购：先过 QI 动作闸门，再按当日净值确认份额。"""
        self._assert_ready()
        self._assert_open_day(on)
        product_type = product_type or self.product_type
        if qi_checker is not None:
            qi_checker.check_action(
                action, profile or {}, product_type=product_type,
                amount_wan=amount_wan if amount_wan is not None else amount / 10_000.0,
                investor_count=investor_count, investors=investors, vehicle=vehicle,
                decision_date=decision_date or on)
        return self._do_subscribe(investor_id, on, amount, action=action)

    def additional_subscribe(self, investor_id: str, on, amount: float, **kwargs) -> dict:
        """追加申购——同样逐动作重校验（补齐旧实现「只校验一次」的漏洞）。"""
        kwargs.setdefault("action", "additional_subscribe")
        return self.subscribe(investor_id, on, amount, **kwargs)

    def transfer(self, from_investor: str, to_investor: str, on, units: float, *,
                 qi_checker=None, profile: Dict = None, product_type: str = None,
                 decision_date=None, amount_wan: float = None, **kwargs) -> dict:
        """份额转让：受让方必须逐动作重校验（禁止代持/借用他人名义）。"""
        self._assert_ready()
        if qi_checker is not None:
            qi_checker.check_action(
                "transfer", profile or {}, product_type=product_type or self.product_type,
                amount_wan=amount_wan, decision_date=decision_date or on, **kwargs)
        seller = self._investors.get(str(from_investor))
        if seller is None or seller.units < float(units):
            raise ValueError(f"转让方 {from_investor!r} 可转让份额不足")
        buyer = self._investors.setdefault(str(to_investor), _Investor(str(to_investor)))
        buyer.units += float(units)
        buyer.hwm = max(buyer.hwm, self._nav_at(on))
        buyer.first_date = buyer.first_date or self._stamp(on)
        seller.units -= float(units)
        record = {"date": self._stamp(on), "from": str(from_investor),
                  "to": str(to_investor), "units": float(units),
                  "nav": self._nav_at(on)}
        self._subscriptions.append({**record, "action": "transfer", "amount": 0.0,
                                    "fee": 0.0, "investor_id": str(to_investor)})
        return record

    def nominee_change(self, investor_id: str, on, *, qi_checker=None,
                       profile: Dict = None, product_type: str = None,
                       new_holder: str = None, decision_date=None, **kwargs) -> dict:
        """变换持有人：必须重新校验新持有人资格（禁止借名/代持）。"""
        self._assert_ready()
        if qi_checker is not None:
            qi_checker.check_action(
                "nominee_change", profile or {},
                product_type=product_type or self.product_type,
                decision_date=decision_date or on, **kwargs)
        holder = str(new_holder or investor_id)
        record = {"date": self._stamp(on), "investor_id": str(investor_id),
                  "new_holder": holder, "action": "nominee_change"}
        self._subscriptions.append({**record, "amount": 0.0, "units": 0.0, "fee": 0.0})
        return record

    def redeem(self, investor_id: str, on, units: float = None, *,
               redeem_all: bool = False, lockup_days: int = None) -> dict:
        self._assert_ready()
        self._assert_open_day(on)
        lockup_days = int(self.lockup_days.get(self.product_type, 0)
                          if lockup_days is None else lockup_days)
        pos = self._investors.get(str(investor_id))
        if pos is None or pos.units <= 0:
            raise ValueError(f"投资者 {investor_id!r} 无持仓")
        stamp = self._stamp(on)
        days = (stamp - pos.first_date).days if pos.first_date is not None else 0
        if lockup_days and days < int(lockup_days):
            raise ValueError(f"锁定期内禁止赎回：已持有 {days} 天 < 锁定 {lockup_days} 天")
        qty = pos.units if redeem_all else float(units or 0)
        if qty <= 0 or qty > pos.units + 1e-9:
            raise ValueError("赎回份额非法")
        nav = self._nav_at(on)
        gross = qty * nav
        rate = self._redemption_rate(days)
        fee = gross * rate
        # 赎回时 crystallize 未付业绩报酬
        carry = pos.carry_accrued * (qty / pos.units) if pos.units else 0.0
        pos.carry_accrued -= carry
        pos.carry_paid += carry
        net = gross - fee - carry
        pos.units -= qty
        self._product_units -= qty
        self._fee_breakdown["redemption"] += fee
        if carry:
            # 只记录 crystallize 事件，fee 计 0，避免与已计提条目重复计数
            self._fee_ledger.append({"date": stamp, "investor_id": pos.investor_id,
                                     "kind": "crystallized", "fee": 0.0,
                                     "crystallized": carry,
                                     "hwm": pos.hwm, "nav": nav})
        record = {"date": stamp, "investor_id": pos.investor_id, "units": qty,
                  "nav": nav, "gross": gross, "redemption_fee": fee,
                  "performance_fee": carry, "net": net,
                  "holding_days": days,
                  "settlement_days": int((self.cfg.get("redemption_settlement_days")
                                          or {}).get(self.product_type, 3)),
                  "settlement_date": stamp + timedelta(days=int(
                      (self.cfg.get("redemption_settlement_days")
                       or {}).get(self.product_type, 3)))}
        self._redemptions.append(record)
        return record

    # ------------------------------------------------------------------
    # 回测
    # ------------------------------------------------------------------
    def run(self) -> "NavResult":
        self._assert_ready()
        if self._ran and self._result is not None:
            return self._result
        gross = self._gross
        net = self._build_product_net(gross)
        investor_net = self._build_investor_net(gross, net)
        layers = NavLayers(gross, net, investor_net)
        self._result = NavResult(self, layers)
        self._ran = True
        return self._result

    def _build_product_net(self, gross: pd.Series) -> pd.Series:
        mgmt = float(self.fee_model.get("management_fee_annual_pct", 0.0))
        cust = float(self.fee_model.get("custodian_fee_annual_pct", 0.0))
        daily_rate = (mgmt + cust) / self.annual_days
        values, prev_nav = [], None
        prev_date = None
        for day, nav in gross.items():
            if prev_nav is None:
                values.append(float(nav))
            else:
                step = float(nav) / prev_nav - 1.0
                days = max((day - prev_date).days, 1)
                factor = max(1.0 - daily_rate * days, 0.0)
                values.append(values[-1] * (1.0 + step) * factor)
                # 费用按 AUM 计金额（用于披露）
                aum = self._product_units * values[-1]
                self._fee_breakdown["management"] += aum * mgmt * days / self.annual_days
                self._fee_breakdown["custodian"] += aum * cust * days / self.annual_days
            prev_nav, prev_date = float(nav), day
        return pd.Series(values, index=gross.index, name="product_net")

    def _build_investor_net(self, gross: pd.Series,
                            net: pd.Series) -> pd.Series:
        perf = float(self.fee_model.get("performance_fee_pct", 0.0))
        out = []
        for day, unit_nav in net.items():
            total_equity, total_units = 0.0, 0.0
            for pos in self._investors.values():
                if pos.units <= 0:
                    continue
                if pos.first_date is not None and day < pos.first_date:
                    continue                      # 申购日之前不参与估值
                if pos.hwm <= 0:
                    pos.hwm = float(unit_nav)
                if unit_nav > pos.hwm + 1e-12:
                    # 逐投资者高水位计提（未 crystallize，作为投资者层负债）
                    fee = pos.units * (unit_nav - pos.hwm) * perf
                    pos.carry_accrued += fee
                    self._fee_ledger.append({
                        "date": day, "investor_id": pos.investor_id, "kind": "accrued",
                        "fee": fee, "hwm": pos.hwm, "nav": float(unit_nav)})
                    self._fee_breakdown["performance"] += fee
                    pos.hwm = float(unit_nav)
                total_equity += pos.equity(float(unit_nav))
                total_units += pos.units
            if total_units <= 0:
                out.append(float(unit_nav))
            else:
                out.append(total_equity / total_units)
        return pd.Series(out, index=net.index, name="investor_net")

    # ------------------------------------------------------------------
    # G3：披露滞后与禁 K 线
    # ------------------------------------------------------------------
    def disclosure_date(self, nav_date, lag_days: int = None) -> date:
        lag = self.lag_days if lag_days is None else int(lag_days)
        return (self._stamp(nav_date) + timedelta(days=lag)).date()

    def assert_decision_after_disclosure(self, decision_date, nav_date=None) -> date:
        """决策日必须 >= 净值日 + 披露滞后；否则抛 DisclosureLagError。"""
        if not self.enforce_decision_after_disclosure:
            return self._stamp(decision_date).date()
        day = self._stamp(decision_date)
        base = self._stamp(nav_date) if nav_date is not None else self.latest_disclosed(day)
        available = self._stamp(base) + timedelta(days=self.lag_days)
        if day < available:
            raise DisclosureLagError(
                f"决策日 {day.date()} 早于净值披露日 {available.date()}（净值日 {base} + 滞后 "
                f"{self.lag_days} 天），属于结构性未来函数")
        return day.date()

    def latest_disclosed(self, decision_date) -> date:
        """返回决策日当天「已披露」的最后一根净值日期（考虑披露滞后）。"""
        self._assert_ready()
        day = self._stamp(decision_date)
        cutoff = pd.Timestamp(day - timedelta(days=self.lag_days))
        usable = [ts for ts in self._gross.index if ts <= cutoff]
        if not usable:
            raise DisclosureLagError(
                f"决策日 {day} 之前没有已披露净值（滞后 {self.lag_days} 天），禁止用未披露数据决策")
        return usable[-1].date()

    def disclosure_view(self, decision_date) -> dict:
        """对外披露视图：只取已披露区间，并标注 data_asof_date。"""
        asof = self.latest_disclosed(decision_date)
        result = self._result or self.run()
        series = result.layers.get(str(self.cfg.get("disclosure_layer") or "investor_net"))
        series = series[series.index.date <= asof]
        return {"layer": str(self.cfg.get("disclosure_layer") or "investor_net"),
                "data_asof_date": asof.isoformat(), "series": series,
                "disclosure_lag_days": self.lag_days,
                "disclosure_frequency": self.freq}

    def assert_not_kline(self, market: str = None) -> None:
        if not self.forbid_nav_as_kline:
            return
        if market and market not in NAV_ONLY_MARKETS:
            return
        raise NavAsKlineError(
            f"{market or self.product_type} 为净值型市场（nav_only_markets="
            f"{list(NAV_ONLY_MARKETS)}），禁止使用 K 线类指标（MA/MACD/ATR 等）")

    def to_kline(self, *args, **kwargs):
        """净值序列不得转成 K 线（OHLC）；调用即报错。"""
        self.assert_not_kline()
        raise NavAsKlineError("净值序列禁止转 K 线：没有开高低收，也不存在盘中撮合")

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _do_subscribe(self, investor_id: str, on, amount: float,
                      action: str = "subscribe") -> dict:
        stamp = self._stamp(on)
        nav = self._nav_at(on)
        fee_rate = float(self.fee_model.get("subscription_fee_pct", 0.0))
        fee = float(amount) * fee_rate
        units = (float(amount) - fee) / nav
        pos = self._investors.setdefault(str(investor_id), _Investor(str(investor_id)))
        pos.units += units
        pos.subscribed += float(amount)
        pos.hwm = max(pos.hwm, nav)
        pos.first_date = pos.first_date or stamp
        self._product_units += units
        self._fee_breakdown["subscription"] += fee
        record = {"date": stamp, "investor_id": str(investor_id), "action": action,
                  "amount": float(amount), "fee": fee, "nav": nav, "units": units}
        self._subscriptions.append(record)
        return record

    def _redemption_rate(self, holding_days: int) -> float:
        table = self.fee_model.get("redemption_fee_by_holding_days") or {}
        if holding_days < 7:
            key = "<7"
        elif holding_days < 30:
            key = "<30"
        else:
            key = ">=30"
        return float(table.get(key, 0.0))

    def _nav_at(self, on) -> float:
        stamp = self._stamp(on)
        usable = self._gross.loc[:stamp]
        if usable.empty:
            raise ValueError(f"{stamp.date()} 之前没有可用净值")
        return float(usable.iloc[-1])

    @staticmethod
    def _stamp(value) -> pd.Timestamp:
        if isinstance(value, pd.Timestamp):
            return value
        if isinstance(value, datetime):
            return pd.Timestamp(value)
        if isinstance(value, date):
            return pd.Timestamp(value)
        return pd.Timestamp(str(value)[:10])

    def _assert_ready(self) -> None:
        if self._gross is None or len(self._gross) < 2:
            raise ValueError("请先 set_nav() 设置产品净值序列")

    # ------------------------------------------------------------------
    # 开放日 / 锁定期 / T+N 到账
    # ------------------------------------------------------------------
    def is_open_day(self, on) -> bool:
        """净值披露日即开放日；非披露日不可申购/赎回。"""
        if not self.enforce_open_day:
            return True
        day = self._stamp(on).normalize()
        return bool((self._gross.index.normalize() == day).any())

    def _assert_open_day(self, on) -> None:
        if not self.is_open_day(on):
            raise ValueError(
                f"{self._stamp(on).date()} 非开放日（只有净值披露日可申赎），"
                "禁止在任意日期确认份额")

    def settlements(self) -> List[dict]:
        """赎回款到账台账（T+N）。"""
        return [{"date": pd.Timestamp(item["date"]), "investor_id": item["investor_id"],
                 "amount": float(item["net"]),
                 "settlement_date": pd.Timestamp(item["settlement_date"]),
                 "settled": False} for item in self._redemptions]

    def settled_amount(self, on) -> float:
        """截至 ``on`` 已到账的赎回款（可用于再投资）。"""
        day = self._stamp(on)
        return float(sum(item["net"] for item in self._redemptions
                         if pd.Timestamp(item["settlement_date"]) <= day))

    def pending_settlement(self, on) -> float:
        """截至 ``on`` 仍在途（未到账）的赎回款，禁止用于再投资。"""
        day = self._stamp(on)
        return float(sum(item["net"] for item in self._redemptions
                         if pd.Timestamp(item["settlement_date"]) > day))


# ==================== 结果 ====================

class NavResult:
    """三层净值 + 申赎 + 业绩报酬明细 + 对账。"""

    def __init__(self, engine: NavBacktester, layers: NavLayers) -> None:
        self.engine = engine
        self.layers = layers
        self.product_type = engine.product_type

    # -- 数据表 --
    @property
    def subscriptions(self) -> pd.DataFrame:
        return pd.DataFrame(self.engine._subscriptions)

    @property
    def redemptions(self) -> pd.DataFrame:
        return pd.DataFrame(self.engine._redemptions)

    @property
    def performance_fees(self) -> pd.DataFrame:
        """业绩报酬计提明细（逐投资者、逐高水位）。"""
        return pd.DataFrame(self.engine._fee_ledger)

    @property
    def fee_breakdown(self) -> Dict[str, float]:
        return dict(self.engine._fee_breakdown)

    @property
    def nav(self) -> pd.Series:
        return self.layers.get("investor_net")

    def positions(self) -> pd.DataFrame:
        last_nav = float(self.layers.product_net.iloc[-1])
        rows = []
        for pos in self.engine._investors.values():
            rows.append({"investor_id": pos.investor_id, "units": pos.units,
                         "hwm": pos.hwm, "carry_accrued": pos.carry_accrued,
                         "carry_paid": pos.carry_paid,
                         "equity": pos.equity(last_nav)})
        return pd.DataFrame(rows)

    # -- 对账 --
    def reconcile(self, tol: float = 1e-6) -> Dict[str, float]:
        """业绩报酬明细与投资者层净值对账。"""
        nav_series = self.layers.investor_net
        positions = self.positions()
        if positions.empty:
            return {"ok": True, "units": 0.0, "equity": 0.0,
                    "nav_times_units": 0.0, "diff": 0.0}
        units = float(positions["units"].sum())
        equity = float(positions["equity"].sum())
        # investor_net 本身已是「投资者权益 / 份额」，直接乘份额即为权益
        implied = float(nav_series.iloc[-1]) * units
        diff = abs(equity - implied)
        ledger = self.performance_fees
        accrued = float(ledger["fee"].sum()) if len(ledger) else 0.0
        booked = float(self.fee_breakdown.get("performance", 0.0))
        return {"ok": bool(diff <= max(tol, abs(equity) * 1e-9)
                           and abs(accrued - booked) <= 1e-6),
                "units": units, "equity": equity, "nav_times_units": implied,
                "diff": diff, "performance_fee_ledger": accrued,
                "performance_fee_booked": booked}

    # -- 指标（净值型：复用同一序列计算，供披露）--
    def metrics(self, benchmark: pd.Series = None) -> Dict[str, float]:
        nav = self.layers.investor_net.astype(float).dropna()
        if len(nav) < 2:
            return {}
        ret = nav.pct_change().dropna()
        days = max((nav.index[-1] - nav.index[0]).days, 1)
        years = days / 365.0
        total = float(nav.iloc[-1] / nav.iloc[0] - 1.0)
        annual = (1.0 + total) ** (1.0 / years) - 1.0 if years > 0 else 0.0
        vol = float(ret.std(ddof=1) * np.sqrt(252)) if len(ret) > 1 else 0.0
        sharpe = (annual - float(config.INDICATOR_CONFIG.get("risk_free_rate", 0.0))) / vol \
            if vol > 0 else 0.0
        drawdown = float((nav / nav.cummax() - 1.0).min())
        downside = float(ret[ret < 0].std(ddof=1) * np.sqrt(252)) if len(ret[ret < 0]) > 1 else 0.0
        sortino = annual / downside if downside > 0 else 0.0
        calmar = annual / abs(drawdown) if drawdown < 0 else 0.0
        monthly = nav.resample("ME").last().pct_change().dropna()
        monthly_win = float((monthly > 0).mean()) if len(monthly) else 0.0
        redemptions = self.redemptions
        gross_redeem = float(redemptions["gross"].sum()) if len(redemptions) else 0.0
        redeem_fee = float(redemptions["redemption_fee"].sum()) if len(redemptions) else 0.0
        last_day = nav.index[-1]
        max_lockup = 0
        for pos in self.engine._investors.values():
            if pos.units > 0 and pos.first_date is not None:
                max_lockup = max(max_lockup, int((last_day - pos.first_date).days))
        out = {"total_return": total, "annual_return": annual, "volatility": vol,
               "sharpe": sharpe, "sortino": sortino, "calmar": calmar,
               "max_drawdown": drawdown,
               "monthly_win_rate": monthly_win,
               "max_lockup_days": float(max_lockup),
               "redemption_fee_ratio": (redeem_fee / gross_redeem) if gross_redeem > 0 else 0.0,
               "performance_fee_total": float(self.fee_breakdown.get("performance", 0.0))}
        if benchmark is not None:
            bench = pd.Series(benchmark).astype(float).dropna()
            bench.index = pd.to_datetime(bench.index)
            bench = bench.reindex(nav.index).ffill().pct_change().dropna()
            excess = (ret - bench).dropna()
            if len(excess) > 2 and float(excess.std(ddof=1)) > 0:
                out["information_ratio"] = float(
                    excess.mean() / excess.std(ddof=1) * np.sqrt(252))
            else:
                out["information_ratio"] = 0.0
        return out

    def disclosure(self, decision_date) -> Dict:
        """对外披露视图（固定 investor_net，禁止毛净值）。"""
        view = self.engine.disclosure_view(decision_date)
        view["metrics"] = self.metrics()
        view["fee_breakdown"] = self.fee_breakdown
        view["performance_fees"] = self.performance_fees
        return view
