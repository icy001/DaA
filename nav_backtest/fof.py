# -*- coding: utf-8 -*-
"""FOF 组合净值回测（nav_backtest/fof.py）

第 10 步 10.3：多只净值型产品 + 配置权重/择时信号 → 组合净值曲线。

与 ``NavBacktester`` 的分工
==========================
* ``NavBacktester``：单只产品 + 多投资者，专注三层净值与逐投资者 carry；
* ``FOFBacktester``：多只产品 + 一个组合账户，专注权重、调仓、锁定期与 T+N 到账。

硬约束
======
1. **决策只用已披露净值**：决策日 ``t`` 只取 ``nav_date <= t - disclosure_lag_days``
   的数据；违反抛 :class:`DisclosureLagError`。执行发生在**下一个净值日**，
   不存在「用当根净值决策并当根成交」。
2. **锁定期**：各产品 ``lockup_days`` 内禁止赎回（调仓需卖出时跳过并留痕）。
3. **T+N 到账**：赎回款在 ``settlement_date`` 之后才能再投资，在途资金计入
   ``pending_cash``，不参与买入。
4. **三层净值**：``product_gross``（持仓市值 + 现金）→ ``product_net``（扣管理费 +
   托管费）→ ``investor_net``（再扣业绩报酬，组合账户按高水位计提）。
5. 净值序列禁止转 K 线（复用 ``NavAsKlineError``）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

import config
from nav_backtest.nav_backtester import (DisclosureLagError, NavAsKlineError, NavLayers,
                                         NAV_ONLY_MARKETS)
from nav_backtest.strategies import equal_weight

__all__ = ["FOFBacktester", "FOFResult", "LockupError"]


class LockupError(RuntimeError):
    """锁定期内赎回——直接拒绝，不允许静默降级。"""


@dataclass
class _Lot:
    code: str
    units: float = 0.0
    first_date: Optional[pd.Timestamp] = None


class FOFBacktester:
    """多产品组合回测：按披露日调仓，锁定期 + T+N 到账 + 三层净值。"""

    def __init__(self, product_type: str = "private_fund",
                 product_config: Dict = None,
                 fee_model: Dict = None,
                 initial_capital: float = 1_000_000.0,
                 rebalance: str = "monthly",
                 annual_days: int = 365) -> None:
        self.cfg = dict(product_config or config.NAV_PRODUCT_CONFIG)
        self.product_type = str(product_type)
        self.fee_model = dict(fee_model or self.cfg.get("fee_model") or {})
        self.initial_capital = float(initial_capital)
        self.rebalance = str(rebalance)
        self.annual_days = int(annual_days)
        self.lag_days = int((self.cfg.get("disclosure_lag_days") or {}).get(
            self.product_type, 2))
        self.settle_days = int((self.cfg.get("redemption_settlement_days") or {}).get(
            self.product_type, 3))
        self.lockup_days = dict(self.cfg.get("lockup_days") or {})

        self._navs: Dict[str, pd.Series] = {}
        self._frame: Optional[pd.DataFrame] = None
        self._lots: Dict[str, _Lot] = {}
        self._cash = self.initial_capital
        self._pending: List[dict] = []
        self._trades: List[dict] = []
        self._weights_history: List[dict] = []
        self._fee_breakdown = {k: 0.0 for k in
                               ("subscription", "redemption", "management",
                                "performance", "custodian")}
        self._ran = False
        self._result: Optional[FOFResult] = None

    # ------------------------------------------------------------------
    # 输入
    # ------------------------------------------------------------------
    def set_navs(self, navs: Dict[str, pd.DataFrame]) -> "FOFBacktester":
        """输入 {code: DataFrame(date|nav|...)}；缺失 nav 列直接报错。"""
        if not navs:
            raise ValueError("FOF 至少需要 1 只产品的净值序列")
        series_map: Dict[str, pd.Series] = {}
        for code, frame in dict(navs).items():
            df = pd.DataFrame(frame)
            date_col = "date" if "date" in df.columns else df.index.name or "date"
            nav_col = "nav" if "nav" in df.columns else (
                "investor_net" if "investor_net" in df.columns else None)
            if nav_col is None:
                raise ValueError(f"{code} 缺少净值列（需 nav / investor_net）")
            s = pd.Series(pd.to_numeric(df[nav_col], errors="coerce").values,
                          index=pd.to_datetime(df[date_col] if date_col in df.columns
                                               else df.index))
            s = s.dropna().sort_index()
            s = s[s > 0]
            if len(s) < 2:
                raise ValueError(f"{code} 有效净值不足 2 个点")
            series_map[str(code)] = s
        self._navs = series_map
        self._frame = pd.DataFrame(series_map).sort_index()
        return self

    # ------------------------------------------------------------------
    # 回测
    # ------------------------------------------------------------------
    def run(self, strategy: Callable = None, strategy_params: Dict = None,
            rebalance_dates: List = None) -> "FOFResult":
        if self._frame is None or self._frame.empty:
            raise ValueError("请先 set_navs() 设置多只产品净值")
        if self._ran and self._result is not None:
            return self._result
        strategy = strategy or equal_weight
        params = dict(strategy_params or {})
        frame = self._frame
        valuation = frame.ffill()                 # 估值沿用最近一次已披露净值
        dates = list(frame.index)
        schedule = self._schedule(dates, rebalance_dates)
        layers_rows: List[dict] = []

        for idx, day in enumerate(dates):
            # 1) T+N 到账
            self._settle(day)
            # 2) 调仓：决策日只看到「day - lag」之前的净值
            if day in schedule and idx + 1 < len(dates):
                disclosed_cutoff = day - timedelta(days=self.lag_days)
                disclosed = frame.loc[frame.index <= disclosed_cutoff].dropna(axis=1, how="all")
                if not disclosed.empty:
                    weights = strategy(disclosed, asof=day, **params) or {}
                    self._rebalance(weights, dates[idx + 1], valuation.iloc[idx + 1], day)
            # 3) 估值
            gross = self._cash + sum(p["amount"] for p in self._pending) + \
                sum(lot.units * float(valuation.loc[day, code])
                    for code, lot in self._lots.items() if lot.units > 0)
            layers_rows.append({"date": day, "product_gross": gross})
        if not layers_rows:
            raise ValueError("净值序列为空，无法估值")

        gross_series = pd.DataFrame(layers_rows).set_index("date")["product_gross"]
        net_series = self._apply_product_fees(gross_series)
        investor_series = self._apply_carry(net_series)
        layers = NavLayers(gross_series, net_series, investor_series)
        self._result = FOFResult(self, layers)
        self._ran = True
        return self._result

    # ------------------------------------------------------------------
    # 调仓
    # ------------------------------------------------------------------
    def _schedule(self, dates: List[pd.Timestamp], explicit: List = None) -> set:
        if explicit:
            return set(pd.Timestamp(d).normalize() for d in explicit) & set(dates)
        stamps = pd.DatetimeIndex(dates)
        if self.rebalance == "daily":
            return set(dates)
        if self.rebalance == "weekly":
            key = stamps.isocalendar()
            seen, out = set(), set()
            for day, (year, week, _) in zip(dates, key.itertuples(index=False)):
                if (year, week) not in seen:
                    seen.add((year, week))
                    out.add(day)
            return out
        # monthly（默认）
        seen, out = set(), set()
        for day in dates:
            key = (day.year, day.month)
            if key not in seen:
                seen.add(key)
                out.add(day)
        return out

    def _rebalance(self, weights: Dict[str, float], execute_on, nav_row: pd.Series,
                   decision_day) -> None:
        # 组合总资产 = 可用现金 + 在途赎回款 + 持仓市值；权重必须按总资产计算，
        # 否则调仓会把持仓当作零，导致每次都触发无谓卖出。
        holdings = sum(lot.units * float(nav_row.get(code, 0.0) or 0.0)
                       for code, lot in self._lots.items() if lot.units > 0)
        total = self._cash + sum(p["amount"] for p in self._pending) + holdings
        if total <= 0:
            return
        targets = {str(code): float(w) for code, w in dict(weights or {}).items()
                   if code in self._lots or code in self._navs}
        current_value = {code: lot.units * float(nav_row.get(code, 0.0) or 0.0)
                         for code, lot in self._lots.items()}
        # 先卖后买，卖出款 T+N 到账，当次不可用
        for code, value in current_value.items():
            target = targets.get(code, 0.0) * total
            if target >= value - 1e-9:
                continue
            lot = self._lots[code]
            lock = int(self.lockup_days.get(code, self.lockup_days.get(self.product_type, 0)))
            held = (pd.Timestamp(execute_on) - lot.first_date).days if lot.first_date else 0
            if lock and held < lock:
                self._trades.append({"date": pd.Timestamp(execute_on), "code": code,
                                     "action": "sell_blocked_lockup", "units": 0.0,
                                     "amount": 0.0, "fee": 0.0,
                                     "holding_days": held, "lockup_days": lock})
                continue
            nav = float(nav_row.get(code) or 0.0)
            if nav <= 0:
                continue
            sell_value = value - target
            units = min(sell_value / nav, lot.units)
            gross = units * nav
            rate = self._redemption_rate(held)
            fee = gross * rate
            lot.units -= units
            self._fee_breakdown["redemption"] += fee
            settle_on = pd.Timestamp(execute_on) + timedelta(days=self.settle_days)
            self._pending.append({"amount": gross - fee, "settle_on": settle_on})
            self._trades.append({"date": pd.Timestamp(execute_on), "code": code,
                                 "action": "sell", "units": units, "amount": gross,
                                 "fee": fee, "holding_days": held})
        # 买入只用当前可用现金（在途赎回款不可再投资）
        buy_budget = max(self._cash, 0.0)
        planned = []
        for code, weight in targets.items():
            target = weight * total
            have = self._lots.get(code, _Lot(code)).units * float(nav_row.get(code, 0.0) or 0.0)
            gap = target - have
            if gap > 1e-6:
                planned.append((code, gap))
        need = sum(gap for _, gap in planned)
        if need <= 0:
            return
        budget = min(buy_budget, need)
        for code, gap in planned:
            nav = float(nav_row.get(code) or 0.0)
            if nav <= 0:
                continue
            amount = gap * budget / need
            rate = float(self.fee_model.get("subscription_fee_pct", 0.0))
            fee = amount * rate
            if amount <= fee:
                continue
            units = (amount - fee) / nav
            lot = self._lots.setdefault(code, _Lot(code))
            lot.units += units
            lot.first_date = lot.first_date or pd.Timestamp(execute_on)
            self._cash -= amount
            self._fee_breakdown["subscription"] += fee
            self._trades.append({"date": pd.Timestamp(execute_on), "code": code,
                                 "action": "buy", "units": units,
                                 "amount": amount, "fee": fee})
        self._weights_history.append({"decision_date": pd.Timestamp(decision_day),
                                      "execute_date": pd.Timestamp(execute_on),
                                      "weights": dict(targets), "total_value": total})

    def _settle(self, day) -> None:
        keep = []
        for item in self._pending:
            if item["settle_on"] <= day:
                self._cash += item["amount"]
            else:
                keep.append(item)
        self._pending = keep

    # ------------------------------------------------------------------
    # 费用与净值层
    # ------------------------------------------------------------------
    def _apply_product_fees(self, gross: pd.Series) -> pd.Series:
        mgmt = float(self.fee_model.get("management_fee_annual_pct", 0.0))
        cust = float(self.fee_model.get("custodian_fee_annual_pct", 0.0))
        rate = (mgmt + cust) / self.annual_days
        values, prev, prev_day = [], None, None
        for day, value in gross.items():
            if prev is None:
                values.append(float(value))
            else:
                days = max((day - prev_day).days, 1)
                fees = prev * rate * days
                self._fee_breakdown["management"] += prev * mgmt * days / self.annual_days
                self._fee_breakdown["custodian"] += prev * cust * days / self.annual_days
                values.append(float(value) - fees)
            prev, prev_day = float(value), day
        return pd.Series(values, index=gross.index, name="product_net")

    def _apply_carry(self, net: pd.Series) -> pd.Series:
        perf = float(self.fee_model.get("performance_fee_pct", 0.0))
        hwm, accrued = None, 0.0
        values = []
        for day, value in net.items():
            value = float(value)
            if hwm is None:
                hwm = value
            if value > hwm + 1e-12:
                fee = (value - hwm) * perf
                accrued += fee
                self._fee_breakdown["performance"] += fee
                hwm = value
            values.append(value - accrued)
        return pd.Series(values, index=net.index, name="investor_net")

    def _redemption_rate(self, holding_days: int) -> float:
        table = self.fee_model.get("redemption_fee_by_holding_days") or {}
        key = "<7" if holding_days < 7 else ("<30" if holding_days < 30 else ">=30")
        return float(table.get(key, 0.0))

    # ------------------------------------------------------------------
    # 对外披露辅助
    # ------------------------------------------------------------------
    def assert_decision_after_disclosure(self, decision_date, nav_date=None) -> date:
        day = pd.Timestamp(decision_date).normalize()
        base = pd.Timestamp(nav_date).normalize() if nav_date is not None else \
            max(ts for ts in self._frame.index if ts <= day)
        available = base + timedelta(days=self.lag_days)
        if day < available:
            raise DisclosureLagError(
                f"决策日 {day.date()} 早于净值披露日 {available.date()}（净值日 "
                f"{base.date()} + 滞后 {self.lag_days} 天）")
        return day.date()

    def to_kline(self, *args, **kwargs):
        raise NavAsKlineError(
            f"FOF 组合净值为净值型（nav_only_markets={list(NAV_ONLY_MARKETS)}），"
            "禁止转 K 线或使用 K 线类指标")


class FOFResult:
    """组合回测结果：三层净值 + 权重历史 + 交易记录 + 指标。"""

    def __init__(self, engine: FOFBacktester, layers: NavLayers) -> None:
        self.engine = engine
        self.layers = layers

    @property
    def nav(self) -> pd.Series:
        return self.layers.get("investor_net")

    @property
    def trades(self) -> pd.DataFrame:
        return pd.DataFrame(self.engine._trades)

    @property
    def weights_history(self) -> pd.DataFrame:
        return pd.DataFrame(self.engine._weights_history)

    @property
    def fee_breakdown(self) -> Dict[str, float]:
        return dict(self.engine._fee_breakdown)

    def metrics(self, benchmark: pd.Series = None) -> Dict[str, float]:
        nav = self.nav.astype(float).dropna()
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
        downside = float(ret[ret < 0].std(ddof=1) * np.sqrt(252)) \
            if len(ret[ret < 0]) > 1 else 0.0
        monthly = nav.resample("ME").last().pct_change().dropna()
        out = {"total_return": total, "annual_return": annual, "volatility": vol,
               "sharpe": sharpe, "calmar": annual / abs(drawdown) if drawdown < 0 else 0.0,
               "sortino": annual / downside if downside > 0 else 0.0,
               "max_drawdown": drawdown,
               "monthly_win_rate": float((monthly > 0).mean()) if len(monthly) else 0.0,
               "performance_fee_total": float(self.fee_breakdown.get("performance", 0.0))}
        if benchmark is not None:
            bench = pd.Series(benchmark).astype(float).dropna()
            bench.index = pd.to_datetime(bench.index)
            bench = bench.reindex(nav.index).ffill().pct_change().dropna()
            excess = (ret - bench).dropna()
            out["information_ratio"] = float(excess.mean() / excess.std(ddof=1) * np.sqrt(252)) \
                if len(excess) > 2 and float(excess.std(ddof=1)) > 0 else 0.0
        return out

    def disclosure(self, decision_date) -> Dict:
        """对外披露只给 investor_net 与已披露区间。"""
        day = pd.Timestamp(decision_date).normalize()
        cutoff = day - timedelta(days=self.engine.lag_days)
        asof = max(ts for ts in self.layers.investor_net.index if ts <= cutoff)
        series = self.layers.investor_net[self.layers.investor_net.index <= asof]
        return {"layer": str(self.engine.cfg.get("disclosure_layer") or "investor_net"),
                "data_asof_date": asof.date().isoformat(), "series": series,
                "disclosure_lag_days": self.engine.lag_days,
                "disclosure_frequency": self.engine.cfg.get("disclosure_frequency", {}).get(
                    self.engine.product_type, "weekly"),
                "metrics": self.metrics(), "fee_breakdown": self.fee_breakdown}
