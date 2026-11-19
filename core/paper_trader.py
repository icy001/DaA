"""模拟盘引擎（core/paper_trader.py）——第三种引擎，不另起炉灶

第 7 步开工前置（D1–D5）约束，本文件**只调用、不重写**：
  - **闸门** `core/signal_gate.py`：每根 bar 均带 `warmup_ok`（缺列直接报错），
    开仓 `buy/short` 走 `place_order` 预热闸门，平仓 `sell/cover` 豁免，
    末根 bar 仍处预热期时不出信号；
  - **成交** `core/execution.py`：挂单/条件单最终仍进 `TradingAccount.place_order`，
    滑点 = 基础滑点 × `config.EXECUTION_MODEL["slippage_multiplier"]["paper"]`（2.0）；
  - **风控** `core/risk.py`：由 `BaseStrategy.risk_manager` 统一调用，
    `config.RISK` 为唯一参数源；
  - **数据时效闸门**照常生效：`run_mode="paper"` 使 `place_order` 走 refetch 复核，
    不为「跑出成交」而绕过。

第 7 步本体（与回测的差异**只允许参数化**）：
  1) 账户持久化 `data_cache/paper_account.json`（含持仓、资金、挂单），重启不丢；
  2) `run_daily()` / `run_intraday()` 复用回测主循环，只换数据周期；
     `last_n_bars` 可只交易最近 N 根，前面的历史仅用于指标预热；
  3) 订单管理：挂单、撤单、改单、止损/止盈/移动止损条件单、一篮子调仓；
  4) 记录与对账：逐笔成交日志、每日账单与净值、手动对账、模拟盘—回测偏差分析；
  5) 默认不强制平仓（`liquidate_at_end=False`），持仓跨日保留。

偏差告警 `ENGINE_CONFORMANCE["divergence_warn_pct"] = 0.05` 只在
「同一行情 + 同一策略 + 同一初始资金 + 三板斧共用」的前提下有意义，否则是追幻影。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

import config
from core import signal_gate
from core.account import Position
from core.backtester import Backtester, BacktestResult
from core.utils import is_trading_day

__all__ = ["PaperTrader", "PaperOrder"]

_DATE_FIELDS = ("open_date", "last_trade_date", "expiry", "mature_date")
_POSITION_FIELDS = {f.name: f for f in fields(Position)}

OPEN_DIRECTIONS = ("buy", "short")
CLOSE_DIRECTIONS = ("sell", "cover")
CONDITIONS = ("", "stop", "take_profit", "trailing_stop")


# ==================== 委托单 ====================

@dataclass
class PaperOrder:
    """模拟盘委托单：pending → partial / filled / canceled / rejected。"""

    order_id: str
    symbol: str
    direction: str
    volume: float
    order_type: str = "market"          # market / limit
    price: Optional[float] = None       # 限价单限价
    condition: str = ""                 # "" / stop / take_profit / trailing_stop
    trigger_price: Optional[float] = None
    trail_pct: Optional[float] = None
    expire: str = "day"                 # day = 当日未成交收盘撤销；gtc = 一直有效
    status: str = "pending"
    filled_volume: float = 0.0
    filled_price: Optional[float] = None
    created_at: str = ""
    updated_at: str = ""
    tag: str = ""
    reason: str = ""
    peak_price: float = 0.0             # 移动止损的峰值跟踪

    @property
    def remaining(self) -> float:
        return max(float(self.volume) - float(self.filled_volume), 0.0)

    @property
    def active(self) -> bool:
        return self.status in ("pending", "partial")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PaperOrder":
        payload = {k: v for k, v in dict(data or {}).items()
                   if k in cls.__dataclass_fields__}
        return cls(**payload)


class PaperTrader(Backtester):
    """模拟盘：复用回测主循环 + 环境参数化 + 账户/挂单持久化 + 订单管理。"""

    def __init__(self, *args, account_file=None, period: str = "1d",
                 auto_save: bool = True, trade_days: int = None,
                 data_fetcher=None, **kwargs):
        # 兼容指令集的 data_fetcher 命名
        if data_fetcher is not None and kwargs.get("fetcher") is None:
            kwargs["fetcher"] = data_fetcher
        kwargs.setdefault("run_mode", "paper")
        kwargs.setdefault("liquidate_at_end", False)
        super().__init__(*args, **kwargs)
        self.period = str(period or "1d")
        self.account_file = Path(
            account_file or (config.DATA_CACHE_DIR / "paper_account.json"))
        self.auto_save = bool(auto_save)
        self.trade_days = int(trade_days) if trade_days else None

        self._orders: List[PaperOrder] = []
        self._order_seq = 0
        self._seen_seed: Dict[str, int] = {}
        self._history_bars = 0
        self.bills: List[dict] = []
        self.recon_log: List[dict] = []

    # ==================== 数据 ====================

    def _fetch(self, symbol: str) -> pd.DataFrame:
        if self.period == "1d":
            return super()._fetch(symbol)
        # 分钟线：period 归一化为 data 层口径（"5min" → "5"），且 data 层不接受 adjust
        period = self.period.replace("min", "") if "min" in self.period else self.period
        kwargs = dict(start_date=self.start_date, end_date=self.end_date, period=period)
        market = self.market_of.get(symbol)
        if market:
            kwargs["market_type"] = market
        try:
            return self.fetcher.get_minute(symbol, **kwargs)
        except TypeError:
            kwargs.pop("market_type", None)
            return self.fetcher.get_minute(symbol, **kwargs)

    # ==================== 闸门 + 挂单 ====================

    def _dispatch(self, date, bars: Dict[str, dict]) -> None:
        """挂单撮合 → 末根预热拦信号 → 策略。闸门实现全部来自 signal_gate。"""
        signal_gate.assert_bar_dict(bars)          # 缺列/NaN 直接报错
        self._process_pending(date, bars)
        if self.dates and date == self.dates[-1]:
            cold = [s for s, b in bars.items() if not signal_gate.bar_warmup_ok(b)]
            if cold:
                self.logger.warning("模拟盘末根 bar 仍处预热期，不出信号：%s", cold)
                return
        super()._dispatch(date, bars)

    def _initial_seen(self) -> Dict[str, int]:
        return dict(self._seen_seed)

    def _bar_count_for_gate(self) -> int:
        """长度门槛按全量历史判定（交易窗口可以只取最近 N 根）。"""
        return int(self._history_bars or len(self.dates))

    def _after_bar(self, date, prices: Dict[str, float]) -> None:
        self._cancel_expired_orders(date)
        self._record_daily_bill(date, prices)

    # ==================== 运行入口 ====================

    def run_daily(self, at=None, last_n_bars: int = None) -> BacktestResult:
        """按日频运行；`at` 为非交易日时跳过（不产生撮合）。"""
        self.period = "1d"
        if at is not None and not is_trading_day(at, market=self._primary_market()):
            self.logger.warning("模拟盘：%s 非交易日，跳过本次运行", at)
            return self._empty_result(f"{at} 非交易日")
        return self._run_window(last_n_bars)

    def run_intraday(self, interval_minutes: int = 5, period: str = None,
                     at=None, last_n_bars: int = None) -> BacktestResult:
        """分钟级运行（同一主循环，仅数据周期不同）。`at` 非交易日时跳过。"""
        self.period = str(period or f"{int(interval_minutes)}min")
        if at is not None and not is_trading_day(at, market=self._primary_market()):
            self.logger.warning("模拟盘：%s 非交易日，跳过本次运行", at)
            return self._empty_result(f"{at} 非交易日")
        return self._run_window(last_n_bars)

    def _run_window(self, last_n_bars: int = None) -> BacktestResult:
        if last_n_bars:
            self.trade_days = int(last_n_bars)
        return self.run()

    def run(self) -> BacktestResult:
        if self.trade_days:
            if not self.frames:
                self.prepare()
            self._trim_to_trade_days(self.trade_days)
        result = super().run()
        if self.auto_save:
            self.save_account()
        return result

    def _trim_to_trade_days(self, n: int) -> None:
        """只交易最近 n 根；更早的历史仍参与指标预热（不当作已交易）。"""
        n = int(n)
        if n <= 0 or len(self.dates) <= n:
            return
        window = list(self.dates[-n:])
        cutoff = window[0]
        self._history_bars = len(self.dates)
        self._seen_seed = {
            symbol: int((frame.index < cutoff).sum())
            for symbol, frame in self.frames.items()}
        self.dates = window
        self.logger.info("模拟盘交易窗口：最近 %d 根（%s → %s），此前历史仅用于预热",
                         n, window[0].date(), window[-1].date())

    def _primary_market(self) -> str:
        for symbol in self.symbols:
            market = self.market_of.get(symbol)
            if market:
                return market
        return "cn_stock"

    def _empty_result(self, reason: str = "") -> BacktestResult:
        return BacktestResult(self.meta.get("name") or self.strategy_class.__name__,
                              pd.DataFrame(), pd.DataFrame(), {}, [],
                              meta={"symbols": self.symbols, "skipped": reason})

    # ==================== 订单管理 ====================

    @property
    def orders(self) -> List[PaperOrder]:
        return list(self._orders)

    def pending_orders(self) -> List[PaperOrder]:
        return [o for o in self._orders if o.active]

    def find_order(self, order_id: str = None, tag: str = None) -> List[PaperOrder]:
        out = self._orders
        if order_id is not None:
            out = [o for o in out if o.order_id == str(order_id)]
        if tag is not None:
            out = [o for o in out if o.tag == str(tag)]
        return list(out)

    def submit_order(self, symbol: str, direction: str, volume: float,
                     order_type: str = "market", price: float = None,
                     condition: str = "", trigger_price: float = None,
                     trail_pct: float = None, expire: str = "day",
                     tag: str = "") -> PaperOrder:
        """挂单入口（不直接成交，下一根 bar 由 `_process_pending` 撮合）。

        条件单：`condition="stop"`（跌到/涨过触发价）、`"take_profit"`、
        `"trailing_stop"`（回撤 trail_pct 触发）。平仓类条件单默认 gtc，
        无持仓时保持等待，不产生拒单噪声。
        """
        symbol = str(symbol).strip()
        direction = str(direction or "").lower()
        order_type = str(order_type or "market").lower()
        condition = str(condition or "").lower()
        if direction not in OPEN_DIRECTIONS + CLOSE_DIRECTIONS:
            raise ValueError(f"非法方向 {direction!r}，仅支持 buy/sell/short/cover")
        if order_type not in ("market", "limit"):
            raise ValueError(f"非法订单类型 {order_type!r}")
        if condition not in CONDITIONS:
            raise ValueError(f"非法条件单类型 {condition!r}")
        try:
            volume = float(volume)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"非法数量 {volume!r}") from exc
        if volume <= 0:
            raise ValueError("下单数量必须为正")
        if order_type == "limit" and (price is None or float(price) <= 0):
            raise ValueError("限价单必须给出有效 price")
        if condition in ("stop", "take_profit") and (
                trigger_price is None or float(trigger_price) <= 0):
            raise ValueError(f"{condition} 条件单必须给出有效 trigger_price")
        if condition == "trailing_stop" and (trail_pct is None or float(trail_pct) <= 0):
            raise ValueError("trailing_stop 条件单必须给出有效 trail_pct")

        self._order_seq += 1
        now = pd.Timestamp.now().isoformat()
        if condition and expire == "day" and direction in CLOSE_DIRECTIONS:
            expire = "gtc"          # 止损/止盈平仓单默认跨日有效
        order = PaperOrder(
            order_id=f"PO{self._order_seq:06d}", symbol=symbol, direction=direction,
            volume=volume, order_type=order_type,
            price=None if price is None else float(price),
            condition=condition,
            trigger_price=None if trigger_price is None else float(trigger_price),
            trail_pct=None if trail_pct is None else float(trail_pct),
            expire=str(expire or "day"), created_at=now, updated_at=now, tag=str(tag or ""))
        self._orders.append(order)
        self.logger.info("模拟盘挂单 %s %s %s %g（%s%s）", order.order_id, symbol,
                         direction, volume, order_type,
                         f"/{condition}" if condition else "")
        return order

    def cancel_order(self, order_id: str, reason: str = "手动撤单") -> bool:
        for order in self.find_order(order_id=order_id):
            if not order.active:
                return False
            order.status = "canceled"
            order.reason = str(reason)
            order.updated_at = pd.Timestamp.now().isoformat()
            self.logger.info("模拟盘撤单 %s：%s", order_id, reason)
            return True
        return False

    def modify_order(self, order_id: str, volume: float = None, price: float = None,
                     trigger_price: float = None, trail_pct: float = None) -> bool:
        for order in self.find_order(order_id=order_id):
            if not order.active:
                return False
            if volume is not None:
                order.volume = float(volume)
                if order.volume <= 0:
                    raise ValueError("改单后数量必须为正")
            if price is not None:
                order.price = float(price)
            if trigger_price is not None:
                order.trigger_price = float(trigger_price)
            if trail_pct is not None:
                order.trail_pct = float(trail_pct)
            order.updated_at = pd.Timestamp.now().isoformat()
            self.logger.info("模拟盘改单 %s → volume=%s price=%s trigger=%s",
                             order_id, order.volume, order.price, order.trigger_price)
            return True
        return False

    # ---- 条件单便捷入口（一律走 submit_order）----

    def stop_loss_order(self, symbol: str, volume: float, trigger_price: float,
                        expire: str = "gtc", tag: str = "stop_loss") -> PaperOrder:
        return self.submit_order(symbol, "sell", volume, condition="stop",
                                 trigger_price=trigger_price, expire=expire, tag=tag)

    def take_profit_order(self, symbol: str, volume: float, trigger_price: float,
                          expire: str = "gtc", tag: str = "take_profit") -> PaperOrder:
        return self.submit_order(symbol, "sell", volume, condition="take_profit",
                                 trigger_price=trigger_price, expire=expire, tag=tag)

    def trailing_stop_order(self, symbol: str, volume: float, trail_pct: float,
                            expire: str = "gtc", tag: str = "trailing_stop") -> PaperOrder:
        return self.submit_order(symbol, "sell", volume, condition="trailing_stop",
                                 trail_pct=trail_pct, expire=expire, tag=tag)

    def rebalance(self, targets: Dict[str, float], tag: str = "rebalance") -> List[PaperOrder]:
        """一篮子调仓：按「目标持仓 - 当前持仓」生成订单，先卖后买。"""
        sells: List[PaperOrder] = []
        buys: List[PaperOrder] = []
        for symbol, target in dict(targets or {}).items():
            symbol = str(symbol)
            pos = self.account.get_position(symbol, "long") if self.account else None
            current = float(pos.volume) if pos is not None else 0.0
            delta = float(target) - current
            if abs(delta) < 1e-9:
                continue
            if delta > 0:
                buys.append(self.submit_order(symbol, "buy", delta, tag=tag))
            else:
                sells.append(self.submit_order(symbol, "sell", -delta, tag=tag))
        return sells + buys

    # ---- 撮合 ----

    def _process_pending(self, date, bars: Dict[str, dict]) -> None:
        """挂单撮合：条件判定 → 预热闸门（开仓）→ `place_order`（成交同源）。"""
        if self.account is None:
            return
        for order in self._orders:
            if not order.active:
                continue
            bar = bars.get(order.symbol)
            if bar is None:
                continue
            if order.condition and not self._condition_triggered(order, bar):
                continue
            if order.direction in CLOSE_DIRECTIONS:
                book = "short" if order.direction == "cover" else "long"
                pos = self.account.get_position(order.symbol, book)
                if pos is None or pos.available <= 0:
                    order.reason = "等待可平持仓（未持仓 / T+1 冻结）"
                    continue
            warmup_ok = signal_gate.bar_warmup_ok(bar)
            if order.direction in OPEN_DIRECTIONS:
                rejection = signal_gate.check_order(
                    order.direction, warmup_ok, symbol=order.symbol, logger=self.logger)
                if rejection is not None:
                    order.reason = "预热期不开仓，挂单继续等待"
                    continue

            volume = order.remaining
            if order.order_type == "limit":
                price = float(order.price)
            else:
                price = float(bar.get("open") or bar.get("close") or 0)
            if price <= 0:
                continue
            res = self.account.place_order(
                order.symbol, order.direction, order.order_type, volume, price,
                order_time=date, market_type=self.market_of.get(order.symbol),
                data=self.frames.get(order.symbol), for_trading=True,
                warmup_ok=warmup_ok,
                # 挂单在更早的 bar 就已提交，本根 bar 是它的成交 bar（不再二次排队）
                fill_now=True)
            if res.get("status") == "filled":
                filled = float(res.get("volume") or volume)
                order.filled_volume += filled
                order.filled_price = float(res.get("price") or price)
                order.status = "filled" if order.remaining <= 1e-9 else "partial"
                order.reason = ""
                order.updated_at = pd.Timestamp.now().isoformat()
                self.logger.info("模拟盘成交 %s %s %s %g @ %.4f（%s）",
                                 order.order_id, order.symbol, order.direction,
                                 filled, order.filled_price,
                                 order.condition or order.order_type)
            else:
                order.reason = str(res.get("reason") or "")
                order.updated_at = pd.Timestamp.now().isoformat()

    def _condition_triggered(self, order: PaperOrder, bar: dict) -> bool:
        high = float(bar.get("high") or bar.get("close") or 0)
        low = float(bar.get("low") or bar.get("close") or 0)
        close = float(bar.get("close") or 0)
        buy_side = order.direction in ("buy", "cover")
        if order.condition == "stop":
            trigger = float(order.trigger_price or 0)
            return high >= trigger if buy_side else low <= trigger
        if order.condition == "take_profit":
            trigger = float(order.trigger_price or 0)
            return low <= trigger if buy_side else high >= trigger
        if order.condition == "trailing_stop":
            order.peak_price = max(float(order.peak_price or 0), high)
            if order.peak_price <= 0:
                return False
            drop = order.peak_price * (1.0 - abs(float(order.trail_pct or 0)))
            return close <= drop
        return True

    def _cancel_expired_orders(self, date) -> None:
        """当日未成交委托收盘自动撤销（条件单/gtc 除外）。"""
        for order in self._orders:
            if order.active and order.expire == "day":
                order.status = "canceled"
                order.reason = f"{pd.Timestamp(date).date()} 收盘未成交，自动撤销"
                order.updated_at = pd.Timestamp.now().isoformat()
                self.logger.info("模拟盘收盘撤单 %s：%s", order.order_id, order.reason)

    # ==================== 账户持久化 ====================

    def _on_account_ready(self) -> None:
        self.load_account()

    def save_account(self) -> Optional[str]:
        if self.account is None:
            return None
        self.account_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "initial_capital": self.account.initial_capital,
            "cash": self.account.cash,
            "frozen_cash": self.account.frozen_cash,
            "margin_used": self.account.margin_used,
            "base_currency": self.account.base_currency,
            "saved_at": pd.Timestamp.now().isoformat(),
            "period": self.period,
            "positions": [self._position_dict(p) for p in self.account.positions.values()],
            "short_positions": [self._position_dict(p)
                                for p in self.account.short_positions.values()],
            "orders": [o.to_dict() for o in self.pending_orders()],
        }
        self.account_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8")
        self.logger.info("模拟盘账户已保存：%s", self.account_file)
        return str(self.account_file)

    def load_account(self) -> bool:
        if self.account is None or not self.account_file.exists():
            return False
        try:
            payload = json.loads(self.account_file.read_text(encoding="utf-8"))
            self.account.cash = float(payload.get("cash", self.account.cash))
            self.account.frozen_cash = float(payload.get("frozen_cash", 0.0) or 0.0)
            self.account.margin_used = float(payload.get("margin_used", 0.0) or 0.0)
            self.account.initial_capital = float(
                payload.get("initial_capital", self.account.initial_capital))
            self.account.positions = {
                p["symbol"]: self._position_obj(p)
                for p in payload.get("positions", [])}
            self.account.short_positions = {
                p["symbol"]: self._position_obj(p)
                for p in payload.get("short_positions", [])}
            restored = [PaperOrder.from_dict(o) for o in payload.get("orders", [])]
            self._orders = [o for o in restored if o.active]
            self._order_seq = max(
                [self._order_seq] + [
                    int(o.order_id.replace("PO", "") or 0)
                    for o in restored if str(o.order_id).startswith("PO")])
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("模拟盘账户恢复失败（%s），按初始资金重新开始", exc)
            return False
        self.logger.info("模拟盘账户已恢复：%s（持仓 %d 个 / 挂单 %d 笔）",
                         self.account_file, len(self.account.positions), len(self._orders))
        return True

    @staticmethod
    def _position_dict(pos: Position) -> dict:
        data = asdict(pos)
        for key in _DATE_FIELDS:
            value = data.get(key)
            data[key] = pd.Timestamp(value).strftime("%Y-%m-%d") if value else None
        return data

    @staticmethod
    def _position_obj(data: dict) -> Position:
        payload = {k: v for k, v in dict(data or {}).items() if k in _POSITION_FIELDS}
        for key in _DATE_FIELDS:
            value = payload.get(key)
            payload[key] = pd.Timestamp(value).date() if value else None
        return Position(**payload)

    # ==================== 记录与对账 ====================

    def _record_daily_bill(self, date, prices: Dict[str, float]) -> None:
        """每日账单：结算后的权益、现金、持仓、当日成交与费用。"""
        if self.account is None:
            return
        day = pd.Timestamp(date).date()
        day_trades = [
            t for t in self.account.trades
            if pd.Timestamp(t.get("timestamp")).date() == day]
        positions = {s: float(p.volume) for s, p in self.account.positions.items()}
        positions.update({s: -float(p.volume)
                          for s, p in self.account.short_positions.items()})
        bill = {
            "date": day,
            "equity": round(float(self.account.calc_equity(prices)), 2),
            "cash": round(float(self.account.cash), 2),
            "margin_used": round(float(self.account.margin_used), 2),
            "positions": positions,
            "fill_count": len(day_trades),
            "commission": round(sum(float(t.get("commission") or 0)
                                    for t in day_trades), 2),
        }
        self.bills.append(bill)
        self.logger.info("模拟盘日结 %s 权益 %.2f 成交 %d 笔 手续费 %.2f",
                         day, bill["equity"], bill["fill_count"], bill["commission"])

    def reconcile(self, cash: float = None, positions: Dict[str, float] = None,
                  note: str = "") -> dict:
        """手动对账（模拟分红/拆股/数据修正）：校正现金与持仓数量。"""
        if self.account is None:
            return {"status": "rejected", "reason": "账户尚未初始化"}
        before = {
            "cash": float(self.account.cash),
            "positions": {s: float(p.volume) for s, p in self.account.positions.items()},
        }
        if cash is not None:
            self.account.cash = float(cash)
        for symbol, target in dict(positions or {}).items():
            symbol, target = str(symbol), float(target)
            pos = self.account.positions.get(symbol)
            if target <= 0:
                self.account.positions.pop(symbol, None)
                continue
            if pos is None:
                market = self.market_of.get(symbol) or config.detect_market_type(symbol)
                px = self._last_close(symbol)
                day = self.account._current_date
                self.account.positions[symbol] = Position(
                    symbol=symbol, market=market, direction="long", volume=target,
                    avg_cost=px, open_date=day, last_trade_date=day, last_price=px)
            else:
                pos.volume = target
                pos.frozen_volume = min(float(pos.frozen_volume), target)
        after = {
            "cash": float(self.account.cash),
            "positions": {s: float(p.volume) for s, p in self.account.positions.items()},
        }
        record = {"note": str(note), "before": before, "after": after}
        self.recon_log.append(record)
        self.logger.info("模拟盘手动对账 %s：现金 %.2f → %.2f，持仓 %s",
                         note or "-", before["cash"], after["cash"], after["positions"])
        return {"status": "ok", **record}

    def _last_close(self, symbol: str) -> float:
        frame = self.frames.get(str(symbol))
        if frame is not None and len(frame) and "close" in frame.columns:
            value = frame["close"].dropna()
            if len(value):
                return float(value.iloc[-1])
        return 0.0

    def _final_equity(self) -> float:
        if self.account is None:
            return 0.0
        if self.account.daily_equity:
            return float(self.account.daily_equity[-1].get("equity") or 0.0)
        return float(self.account.calc_equity({}))

    def compare_with_backtest(self, reference: BacktestResult = None,
                              warn_pct: float = None) -> dict:
        """模拟盘—回测偏差分析：同一行情/策略/资金下才有归因意义。"""
        if warn_pct is None:
            warn_pct = float((getattr(config, "ENGINE_CONFORMANCE", {}) or {})
                             .get("divergence_warn_pct", 0.05))
        if reference is None:
            reference = Backtester(
                self.strategy_class, strategy_params=self.params, symbols=self.symbols,
                start_date=self.start_date, end_date=self.end_date,
                initial_capital=self.initial_capital, benchmark=None,
                market_type=self.market_type, fetcher=self.fetcher, adjust=self.adjust,
                liquidate_at_end=False, logger=self.logger).run()
        paper_equity = self._final_equity()
        bt_equity = (float(pd.to_numeric(reference.nav["equity"], errors="coerce")
                           .dropna().iloc[-1]) if len(reference.nav) else 0.0)
        deviation = (paper_equity / bt_equity - 1.0) if bt_equity else 0.0
        drivers = self._divergence_drivers(reference)
        warned = abs(deviation) > abs(float(warn_pct))
        message = (
            f"模拟盘 {paper_equity:,.2f} vs 回测 {bt_equity:,.2f}，偏差 {deviation:.2%}"
            f"（阈值 {float(warn_pct):.2%}）")
        if warned:
            message += ("，可能由滑点/停牌/涨跌停导致；仅当两环境共用 "
                        "signal_gate/execution/risk 且行情与策略一致时才可归因")
            self.logger.warning("模拟盘—回测偏差超阈值：%s", message)
        else:
            self.logger.info("模拟盘—回测偏差正常：%s", message)
        return {"paper_equity": round(paper_equity, 2),
                "backtest_equity": round(bt_equity, 2),
                "deviation_pct": float(deviation), "warn_pct": float(warn_pct),
                "warned": bool(warned), "drivers": drivers, "message": message}

    def _divergence_drivers(self, reference: BacktestResult) -> dict:
        """偏差归因线索：成交笔数、价格差、滑点倍数。"""
        paper_fills = len(self.account.trades) if self.account else 0
        bt_trades = reference.trades
        bt_fills = int(len(bt_trades)) if bt_trades is not None else 0
        paper_px = [float(t.get("price") or 0) for t in (self.account.trades if self.account else [])]
        bt_px = ([float(x) for x in pd.to_numeric(bt_trades.get("price"), errors="coerce")
                  .dropna()] if bt_fills else [])
        worse = sum(1 for a, b in zip(paper_px, bt_px) if a > b)
        bt_slippage = float((reference.meta or {}).get("slippage")
                            or config.EXECUTION_MODEL["slippage_base_pct"]
                            * config.EXECUTION_MODEL["slippage_multiplier"]["backtest"])
        return {
            "paper_fills": paper_fills,
            "backtest_fills": bt_fills,
            "fill_count_diff": paper_fills - bt_fills,
            "higher_fill_prices": worse,
            "slippage_paper": round(float(self.execution.slippage), 8),
            "slippage_backtest": round(bt_slippage, 8),
            "known_simplifications": list(
                config.EXECUTION_MODEL.get("known_simplifications") or []),
        }
