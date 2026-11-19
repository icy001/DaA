# -*- coding: utf-8 -*-
"""实盘运行守护（live/daemon.py）—— 12.8。

职责：开盘前自检、交易日历判断、心跳监控、收盘结算与对账、优雅退出
（自动撤未成交单，不挂单过夜），并把急停监听放到**独立线程**。

自检项（任一 mandatory 失败即拒绝开盘）：
  行情连接 / 账户登录 / 风控参数 / 持仓核对 / 凭证校验 / 急停可用。
"""
from __future__ import annotations

import threading
import time
from datetime import date as _date
from typing import Callable, Dict, Optional

import config
from core.utils import is_trading_day
from live.kill_switch import PanicController, kill_switch_config

__all__ = ["LiveDaemon", "check_credentials", "CREDENTIAL_FIELDS"]

# 12.17.5：按券商类型检查必填字段（字段名 → config 属性名）
CREDENTIAL_FIELDS = {
    "qmt": [("QMT_PATH", "QMT_PATH"), ("QMT_ACCOUNT_ID", "QMT_ACCOUNT_ID"),
            ("QMT_PASSWORD", "QMT_PASSWORD")],
    "ptrade": [("PTRADE_SERVER", "PTRADE_SERVER"), ("PTRADE_USERNAME", "PTRADE_USERNAME"),
               ("PTRADE_PASSWORD", "PTRADE_PASSWORD"),
               ("PTRADE_ACCOUNT_ID", "PTRADE_ACCOUNT_ID")],
    "ctp": [("CTP_FRONT_ADDR_TRADE", "CTP_FRONT_ADDR_TRADE"),
            ("CTP_FRONT_ADDR_MARKET", "CTP_FRONT_ADDR_MARKET"),
            ("CTP_BROKER_ID", "CTP_BROKER_ID"), ("CTP_USER_ID", "CTP_USER_ID"),
            ("CTP_PASSWORD", "CTP_PASSWORD")],
    "ibkr": [("IBKR_HOST", "IBKR_HOST"), ("IBKR_PORT", "IBKR_PORT")],
}


def check_credentials(broker_type: str, cfg=None) -> dict:
    """启动前凭证校验：缺失关键字段 → 立即告警 + 拒绝启动。"""
    cfg = cfg or config
    kind = str(broker_type or "").lower()
    fields = CREDENTIAL_FIELDS.get(kind)
    if not fields:
        return {"ok": True, "broker": kind, "missing": [],
                "hint": f"未知券商类型 {kind!r}：本系统只对接 A股/期货合规通道"}
    missing = [name for name, attr in fields
               if not str(getattr(cfg, attr, "") or "").strip()]
    return {"ok": not missing, "broker": kind, "missing": missing,
            "hint": (f"请检查 .env 文件中的 {' / '.join(missing)} 字段"
                     if missing else "凭证齐全")}


class LiveDaemon:
    def __init__(self, trader, broker=None, data_engine=None, notifier=None,
                 audit=None, strategy=None, broker_type: str = None,
                 heartbeat_timeout_sec: float = 600, now_fn: Callable = None,
                 panic: PanicController = None) -> None:
        self.trader = trader
        self.broker = broker or getattr(trader, "broker", None)
        self.data_engine = data_engine
        self.notifier = notifier
        self.audit = audit
        self.strategy = strategy
        self.broker_type = str(broker_type or getattr(self.broker, "name", "") or "")
        self.heartbeat_timeout_sec = float(heartbeat_timeout_sec)
        self._now = now_fn or time.time
        self._last_heartbeat = float(self._now())
        self._stop_event = threading.Event()
        self.panic = panic or PanicController(
            kill_switch=getattr(trader, "kill_switch", None), broker=self.broker,
            notifier=notifier, audit=audit, logger=getattr(trader, "logger", None))

    # ==================== 开盘前自检 ====================
    def pre_open_check(self) -> dict:
        checks: Dict[str, dict] = {}

        conn = bool(self.data_engine.is_connected()) if self.data_engine is not None \
            else bool(getattr(self.broker, "connected", False))
        checks["quote_connection"] = {"ok": conn, "mandatory": True,
                                      "detail": "官方行情已连接" if conn else "行情未连接"}

        try:
            account = dict(self.broker.get_account() or {})
            ok_acc = bool(account)
        except Exception as exc:  # noqa: BLE001
            account, ok_acc = {}, False
            checks.setdefault("_account_error", {"detail": str(exc)})
        checks["account_login"] = {"ok": ok_acc, "mandatory": True,
                                   "detail": "账户可查询" if ok_acc else "账户登录失败"}

        risk = getattr(self.trader, "risk", None)
        ok_risk = risk is not None and all(
            float(getattr(risk, name, 0.0) or 0.0) > 0
            for name in ("daily_loss_pct_stop", "max_drawdown_pct_stop",
                         "max_single_symbol_pct"))
        checks["risk_params"] = {"ok": ok_risk, "mandatory": True,
                                 "detail": "风控参数齐全" if ok_risk else "风控参数缺失/为 0"}

        reconciler = getattr(self.trader, "reconciler", None)
        if reconciler is not None:
            result = reconciler.compare()
            ok_rec, detail = bool(result["ok"]), ("持仓/资金一致" if result["ok"]
                                                  else f"不一致：{result['diffs'][:3]}")
        else:
            ok_rec, detail = False, "未配置对账器"
        checks["position_reconcile"] = {"ok": ok_rec, "mandatory": True, "detail": detail}

        creds = check_credentials(self.broker_type) if self.broker_type else \
            {"ok": True, "missing": [], "hint": "未指定券商类型（仿真）"}
        checks["credentials"] = {"ok": bool(creds["ok"]), "mandatory": True,
                                 "detail": creds["hint"]}

        flag_file = getattr(getattr(self.trader, "kill_switch", None), "path", None)
        ok_ks = flag_file is not None
        if ok_ks:
            try:
                flag_file.parent.mkdir(parents=True, exist_ok=True)
                probe = flag_file.parent / ".kill_probe"
                probe.write_text("1", encoding="utf-8")
                probe.unlink()
            except OSError:
                ok_ks = False
        checks["kill_switch_ready"] = {
            "ok": ok_ks, "mandatory": True,
            "detail": "急停信号可写入/可监听" if ok_ks else "急停标志目录不可写"}

        failed = [k for k, v in checks.items()
                  if v.get("mandatory", True) and not v.get("ok")]
        return {"ok": not failed, "failed": failed, "checks": checks,
                "at": time.strftime("%Y-%m-%d %H:%M:%S")}

    # ==================== 交易日历 / 心跳 ====================
    def is_trading_day(self, day=None, market: str = "cn_stock") -> bool:
        return bool(is_trading_day(day or _date.today(), market=market))

    def heartbeat(self) -> float:
        self._last_heartbeat = float(self._now())
        return self._last_heartbeat

    def check_heartbeat(self) -> bool:
        """超时（默认 10 分钟）无心跳 → 告警并返回 False。"""
        gap = float(self._now()) - self._last_heartbeat
        if gap > self.heartbeat_timeout_sec:
            if self.notifier is not None:
                self.notifier.notify("crash", "心跳超时",
                                     f"{gap:.0f}s 无心跳（上限 "
                                     f"{self.heartbeat_timeout_sec:.0f}s）",
                                     level="critical")
            return False
        return True

    # ==================== 运行期 ====================
    def start(self) -> Optional[threading.Thread]:
        """启动急停监听线程（independent_thread=True 时）。"""
        if self.audit is not None:
            self.audit.start(broker=self.broker_type,
                             mode=getattr(self.trader, "mode", config.RUN_MODE))
        self.heartbeat()
        if kill_switch_config().get("independent_thread", True):
            return self.panic.start_watcher(self._stop_event)
        return None

    def settle_and_reconcile(self) -> dict:
        """收盘后自动结算 + 对账（12.8/12.10）。"""
        result = {"reconcile": None, "settlement": None}
        reconciler = getattr(self.trader, "reconciler", None)
        if reconciler is not None:
            result["reconcile"] = reconciler.eod()
        account = getattr(self.trader, "account", None)
        if account is not None and hasattr(account, "end_of_day"):
            result["settlement"] = account.end_of_day()
        if self.notifier is not None:
            ok = bool((result["reconcile"] or {}).get("ok", True))
            self.notifier.on_reconcile(str(result["reconcile"]), ok=ok)
        return result

    def graceful_exit(self, cancel_open: bool = True) -> dict:
        """优雅退出：先撤未成交单（不挂单过夜），再断连、写审计。"""
        self._stop_event.set()
        cancelled, failed = [], []
        if cancel_open and self.broker is not None:
            for order in list(getattr(self.broker, "get_orders", lambda: [])() or []):
                status = getattr(order, "status", None)
                oid = getattr(order, "client_order_id", None)
                if isinstance(order, dict):
                    status, oid = order.get("status"), order.get("client_order_id")
                if not oid or str(status) in PanicController.TERMINAL:
                    continue
                try:
                    if (self.broker.cancel_order(str(oid)) or {}).get("ok", True):
                        cancelled.append(str(oid))
                        continue
                except Exception:  # noqa: BLE001 - 记录失败
                    pass
                failed.append(str(oid))
        if self.broker is not None:
            try:
                self.broker.disconnect()
            except Exception:  # noqa: BLE001 - 退出流程不中断
                pass
        if self.audit is not None:
            self.audit.stop(cancelled=cancelled, cancel_failed=failed)
        if self.notifier is not None and failed:
            self.notifier.notify("crash", "撤单失败告警",
                                 f"优雅退出仍有 {len(failed)} 笔未撤销：{failed[:5]}",
                                 level="error")
        return {"cancelled": cancelled, "cancel_failed": failed}
