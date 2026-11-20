# -*- coding: utf-8 -*-
"""实盘执行器（live/live_trader.py）——第 12 步开工前置 K2–K8。

**本文件是系统唯一允许「决策后真的把单发出去」的地方**（K5）：
券商适配器只实现发单原语；闸门/风控/对账/幂等/限额全部收口在
:meth:`LiveTrader.submit_order`，换券商不会多出一条绕过闸门的通道。

报单前顺序（fail-closed，任何一环拒绝即不发出）
================================================
1. 急停（落盘标志，跨重启保留）
2. 场外衍生品真实报单硬拦（只允许仿真）
3. 模式解析（连不上券商禁止静默回退）+ 模式标注
4. bar 三物化列（warmup_ok / data_asof_date / price_adjust，缺列报错）
5. **对账前移**（pre_order；权威在券商侧，不一致停开新仓）
6. ``core/signal_gate.py`` 预热裁决（开严平宽）
7. ``core/risk.py`` 风控（仓位/杠杆/熔断）
8. 合格投资者（净值型产品）
9. 时效闸门（refetch 复核，开仓严/平仓宽）
10. 首笔实盘限额
11. 幂等（client_order_id 落盘、窗口去重、状态未知先查券商）
12. 经适配器发单（唯一出口）
"""
from __future__ import annotations

from typing import Callable, Dict

import pandas as pd

import config
from core.gov_compat import gov
from core import signal_gate
from core.account import (DERIVATIVE_MARKETS, DerivativeMarketLiveForbidden,
                          LIVE_ALLOWED_MARKETS, LiveMarketForbidden, TradingAccount)
from core.utils import setup_logger
from broker.base_broker import ACCEPTED, FILLED, REJECTED, UNKNOWN, BrokerOrder
from live import mode_guard
from live.errors import (DerivativeLiveForbidden, FirstOrderLimitError,
                         LiveSafetyError, OrderPortError)
from live.idempotency import IdempotencyStore
from live.kill_switch import KillSwitch
from live.reconciliation import Reconciler
from risk.risk_manager import LiveRiskManager

__all__ = ["LiveTrader", "DERIVATIVE_PRODUCTS"]

DERIVATIVE_PRODUCTS = ("snowball", "trs", "option_combo", "derivative", "otc")
_OPEN = ("buy", "short")


def _conf() -> dict:
    return dict(gov("LIVE_SAFETY"))


class LiveTrader:
    def __init__(self, broker, account=None, strategy_id: str = "live",
                 mode: str = "live_sim", simulated: bool = True,
                 risk_params: dict = None, fetcher=None, logger=None,
                 qi_verified: bool = False, store: IdempotencyStore = None,
                 kill_switch: KillSwitch = None, reconciler: Reconciler = None,
                 freshness_fn: Callable = None,
                 first_order_confirmed: bool = False,
                 audit=None, notifier=None,
                 account_subject: str = "personal") -> None:
        self.simulated = bool(simulated)
        self.mode = mode_guard.resolve_mode(
            mode, broker_connected=bool(getattr(broker, "connected", True)),
            broker_live_ready=bool(getattr(broker, "live_ready", True)) or self.simulated)
        self.broker = broker
        self.strategy_id = str(strategy_id)
        self.logger = logger or setup_logger("live", config.LOG_DIR / "live_trader.log")
        self.account = account or TradingAccount(run_mode=self.mode, fetcher=fetcher,
                                                 logger=self.logger,
                                                 account_subject=account_subject)
        # 账户主体性质（v3.53 评审七轮·闸门7）：personal（默认）/institution——
        # 个人主体衍生品实盘永久硬拦（主体闸优先于白名单闸，白名单不可绕过）
        self.account_subject = str(getattr(self.account, "account_subject",
                                           account_subject) or "personal").lower()
        self.fetcher = fetcher
        # B-1：实盘熔断状态落盘（跨进程：CLI risk-reset 删标志文件 → 换日同步解除）
        self.risk = LiveRiskManager(self.account, params=risk_params, logger=self.logger,
                                    state_file="live_trading/RISK_HALT.json")
        self.qi_verified = bool(qi_verified)
        self.store = store or IdempotencyStore()
        self.kill_switch = kill_switch or KillSwitch()
        self.reconciler = reconciler or Reconciler(self.account, broker, now_fn=None)
        self.audit = audit
        self.notifier = notifier
        self.strategy = None
        self._freshness_fn = freshness_fn
        self.first_order_confirmed = bool(first_order_confirmed)
        self.orders: list = []
        if (gov("LIVE_SAFETY")).get("reconcile", {}).get(
                "startup", True) and reconciler is None:
            self.reconciler.startup()

    # ==================== 行情入口（三物化列硬校验） ====================
    def on_bar(self, date, bars: Dict[str, dict], strategy=None) -> list:
        signal_gate.assert_tick_bars(bars)
        prices = {s: float(b.get("close") or b.get("price") or 0.0)
                  for s, b in dict(bars).items()}
        actions = self.risk.on_bar(date, prices)
        if strategy is not None and hasattr(strategy, "on_bar"):
            strategy.on_bar(date, bars)
        self.reconciler.tick()
        return actions

    def on_tick(self, bars: Dict[str, dict], strategy=None) -> None:
        signal_gate.assert_tick_bars(bars)
        if strategy is not None and hasattr(strategy, "on_tick"):
            strategy.on_tick(bars)

    # ==================== 报单唯一收口 ====================
    def submit_order(self, symbol: str, direction: str, volume: float,
                     price: float = None, bar: dict = None,
                     product_type: str = "cash", market: str = None,
                     bar_date=None, client_order_id: str = None) -> dict:
        symbol, direction = str(symbol), str(direction).lower()
        rec = {"symbol": symbol, "direction": direction,
               "volume": float(volume or 0.0), "price": price,
               "mode": self.mode, "status": "rejected", "ok": False,
               "client_order_id": None, "stage": "", "reason": ""}
        try:
            self._precheck(direction, product_type, bar, symbol, market=market)
            self.reconciler.require_clean(before_order=True)
            self._gate_and_risk(symbol, direction, volume, price, bar, market,
                                product_type)
            self._first_order_limit(symbol, direction, volume, price, market)
            key = client_order_id or self.store.new_client_order_id(
                self.strategy_id, symbol, direction, bar_date or bar.get("date"))
            self.store.register(key)
            rec["client_order_id"] = key
            rec.update(self._send(key, symbol, direction, volume, price))
        except LiveSafetyError as exc:
            rec.update(self.store_status(client_order_id), stage=exc.stage,
                       reason=str(exc), ok=False, status="rejected")
            self.logger.warning("拒单 %s %s：%s", symbol, direction, exc)
        if rec.get("ok"):
            self.risk.record_order(symbol, direction)
        self._flush_events(rec)
        self.orders.append(rec)
        return rec

    # ==================== 策略生命周期（12.7：策略代码零改动） ====================
    def start(self, strategy) -> None:
        """与回测/模拟盘相同的三步：init → on_bar/on_tick → on_end_of_day。"""
        self.strategy = strategy
        init = getattr(strategy, "init", None)
        if callable(init):
            init()

    def on_end_of_day(self, date, prices: Dict[str, float] = None) -> dict:
        result: dict = {}
        hook = getattr(self.strategy, "on_end_of_day", None)
        if callable(hook):
            result["strategy"] = hook(date)
        if hasattr(self.account, "end_of_day"):
            result["account"] = self.account.end_of_day(date, prices or {})
        self.risk.new_day(date, prices=prices or {})
        return result

    def buy(self, symbol, volume, price=None, bar=None, **kwargs):
        return self.submit_order(symbol, "buy", volume, price, bar, **kwargs)

    def sell(self, symbol, volume, price=None, bar=None, **kwargs):
        return self.submit_order(symbol, "sell", volume, price, bar, **kwargs)

    def short(self, symbol, volume, price=None, bar=None, **kwargs):
        return self.submit_order(symbol, "short", volume, price, bar, **kwargs)

    def cover(self, symbol, volume, price=None, bar=None, **kwargs):
        return self.submit_order(symbol, "cover", volume, price, bar, **kwargs)

    def confirm_first_order(self) -> None:
        """确认通道正常后放开首笔限额（人工动作）。"""
        self.first_order_confirmed = True

    def store_status(self, client_order_id) -> dict:
        rec = self.store.get(client_order_id) if client_order_id else None
        return {"idempotency": rec} if rec else {}

    def _flush_events(self, rec: dict) -> None:
        """审计留痕 + 事件告警（12.9/12.11）：旁路失败不打断报单主流程。"""
        if self.audit is not None:
            try:
                event = "fill" if rec.get("status") == FILLED else "order_submit"
                self.audit.record(event, symbol=rec.get("symbol"),
                                  direction=rec.get("direction"),
                                  volume=rec.get("volume"), price=rec.get("price"),
                                  mode=self.mode, status=rec.get("status"),
                                  client_order_id=rec.get("client_order_id"),
                                  broker_order_id=rec.get("broker_order_id", ""),
                                  reason=rec.get("reason", ""))
            except Exception as exc:  # noqa: BLE001 - 审计旁路
                self.logger.error("审计写入失败：%s", exc)
        if self.notifier is not None:
            try:
                if rec.get("status") == FILLED:
                    self.notifier.on_fill(rec.get("symbol"), rec.get("direction"),
                                          rec.get("volume"), rec.get("price", 0.0),
                                          mode=self.mode)
                else:
                    self.notifier.on_order_status(rec.get("client_order_id") or "-",
                                                  rec.get("status"), mode=self.mode)
            except Exception as exc:  # noqa: BLE001 - 通知旁路
                self.logger.warning("告警推送失败：%s", exc)

    # ==================== 内部：各道闸门 ====================
    def _precheck(self, direction, product_type, bar, symbol,
                  market: str = None) -> None:
        if direction not in ("buy", "sell", "short", "cover"):
            raise OrderPortError(f"非法方向 {direction!r}", stage="direction")
        self.kill_switch.assert_can_trade()
        # 闸门7（v3.53 评审七轮）：实盘两道闸，【主体闸优先于白名单闸】——
        # ① 主体闸：个人主体对衍生品市场永久硬拦，即使衍生品市场被错误加进
        #    LIVE_ALLOWED_MARKETS 也绕不过（实盘放行与回测/研究扩围解耦）；
        # ② 白名单闸：非衍生品市场必须显式列入白名单；market 缺失按 symbol 兜底
        #    识别，【识别不出必须默认拒绝】，不得当作普通市场放行。
        # 两异常均不继承 LiveSafetyError，submit_order 的拒单捕获无法吞掉，
        # 必须穿透到调用方进程级停机（直接 raise 非打印警告）。
        if self.mode == "live" and not self.simulated:
            try:
                dmarket = str(market or "").lower() or \
                    config.detect_market_type(symbol)
            except Exception:  # noqa: BLE001 - 识别不出=未知市场：默认拒绝（fail-closed）
                dmarket = ""
            if (dmarket in DERIVATIVE_MARKETS
                    and self.account_subject == "personal"):
                raise DerivativeMarketLiveForbidden(
                    f"[live] 账户主体=个人，{symbol}（{dmarket}）衍生品市场永久禁止"
                    "实盘报单（主体性质硬拦，白名单不可绕过）；期货/期权仅限回测/研究/仿真")
            if dmarket not in LIVE_ALLOWED_MARKETS:
                raise LiveMarketForbidden(
                    f"[live] {symbol} 市场 {dmarket!r} 未列入 LIVE_ALLOWED_MARKETS "
                    f"白名单（当前={sorted(LIVE_ALLOWED_MARKETS)}），直接 raise 硬拦；"
                    "扩市场必须显式放行并附预检回执")
        if (str(product_type).lower() in DERIVATIVE_PRODUCTS
                and not self.simulated and self.mode == "live"):
            raise DerivativeLiveForbidden(
                "个人实盘禁止场外衍生品真实报单（雪球/TRS/期权组合）："
                "personal_derivatives_live_forbidden=True，仅允许仿真")
        if bar is None:
            raise LiveSafetyError("报单缺少决策 bar：禁止在没有三物化列的帧上下单",
                                  stage="materialized_columns")
        signal_gate.assert_tick_bars({symbol: bar})

    def _gate_and_risk(self, symbol, direction, volume, price, bar, market,
                       product_type: str = "cash") -> None:
        verdict = signal_gate.check_order(
            direction, signal_gate.bar_warmup_ok(bar), symbol=symbol,
            logger=self.logger)
        if verdict:
            raise LiveSafetyError(verdict["reason"], stage="warmup")
        px = float(price or bar.get("close") or 0.0)
        verdict = self.risk.pre_order(symbol, direction, volume, px, market=market,
                                      bar=bar, product_type=product_type)
        if not verdict["ok"]:
            raise LiveSafetyError(
                f"[{verdict['layer']}] {verdict['reason']}", stage="risk_block")
        for warning in verdict["warnings"]:
            self.logger.warning("风控预警：%s", warning)
        self._qi_check(symbol, market, product_type)
        self._freshness(symbol, direction, bar, market)

    def _qi_check(self, symbol, market, product_type: str = "cash") -> None:
        nav_markets = set((config.INDICATOR_CONFIG or {}).get("nav_only_markets") or [])
        market = str(market or config.detect_market_type(symbol))
        if (str(product_type).lower() in ("private_fund", "qii_product", "trust")
                or market in nav_markets) and not self.qi_verified:
            raise LiveSafetyError(
                "净值型产品报单需先通过合格投资者校验（qi_verified=False）",
                stage="qualified_investor")

    def _freshness(self, symbol, direction, bar, market) -> None:
        if self._freshness_fn is not None:
            ok = self._freshness_fn(symbol=symbol, direction=direction, bar=bar)
            if ok is False:
                raise LiveSafetyError("时效复核未通过（注入判定）", stage="stale")
            return
        from core import data_fetcher
        df = pd.DataFrame({"symbol": [symbol],
                           config.STALE_INFO_COLUMN: [bar.get("data_asof_date")]})
        try:
            data_fetcher.assert_fresh_for_trading(
                df, kind="daily",
                market=str(market or config.detect_market_type(symbol)),
                symbol=symbol, fetcher=self.fetcher, for_trading=True,
                order_side="open" if direction in _OPEN else "close")
        except Exception as exc:  # noqa: BLE001 - 闸门异常即拒（开仓严）
            raise LiveSafetyError(f"时效复核失败（refetch）：{exc}", stage="stale")

    def _first_order_limit(self, symbol, direction, volume, price, market) -> None:
        if not direction in _OPEN or self.first_order_confirmed:
            return
        cap = float(_conf().get("first_live_order_max_notional", 10000.0) or 0.0)
        if cap <= 0:
            return
        rule = config.get_market_config(
            str(market or config.detect_market_type(symbol)))
        notional = float(volume) * float(price or 0.0) * float(rule.get("multiplier", 1) or 1)
        if notional > cap:
            raise FirstOrderLimitError(
                f"首笔实盘限额：单笔名义 {notional:,.0f} > {cap:,.0f}"
                f"（first_live_order_max_notional）；确认通道正常后 confirm_first_order() 放开")

    # ==================== 内部：发单 + 状态未知处置 ====================
    def _send(self, key, symbol, direction, volume, price) -> dict:
        order = BrokerOrder(client_order_id=key, symbol=symbol, direction=direction,
                            volume=float(volume), price=float(price or 0.0),
                            mode=self.mode)
        sent = self.broker.place_order(order)
        self.store.mark(key, sent.status, sent.broker_order_id)
        if sent.status == REJECTED:
            return {"status": "rejected", "reason": sent.message or "券商拒单（废单不重试）",
                    "broker_order_id": sent.broker_order_id or "", "ok": False}
        if sent.status == UNKNOWN:
            return self._resolve_unknown(key, order, sent)
        return {"status": sent.status, "broker_order_id": sent.broker_order_id or "",
                "ok": True, "reason": sent.message}

    def _resolve_unknown(self, key, order, sent) -> dict:
        """状态未知：先查券商，确认未受理才允许重发一次（K3 ③）。"""
        existing = self.broker.query_order(key)
        if existing is not None and existing.status in (ACCEPTED, FILLED):
            self.store.mark(key, existing.status, existing.broker_order_id)
            return {"status": existing.status, "ok": True,
                    "broker_order_id": existing.broker_order_id or "",
                    "reason": "状态未知但券商已受理，禁止重发（已确认原单）"}
        if existing is not None and existing.status == REJECTED:
            self.store.mark(key, REJECTED, existing.broker_order_id)
            return {"status": "rejected", "ok": False,
                    "reason": "状态未知但券商记录为废单，不重试"}
        retry = self.broker.place_order(order)
        self.store.mark(key, retry.status, retry.broker_order_id)
        return {"status": retry.status, "ok": retry.status != REJECTED,
                "broker_order_id": retry.broker_order_id or "",
                "reason": f"券商确认未受理后重发一次：{sent.message}"}
