# -*- coding: utf-8 -*-
"""合格投资者层盯盘提醒（core/qi_monitor.py）——第 10 步 10.5

「提醒 ≠ 拦截」
==============
本模块只负责**发现事件并推送提醒**。合格投资者资格真正被拦住，靠
``core/qualified_investor.py::check_action`` 在每个申购/转让动作上重新校验；
``qi_threshold_check`` 资产缩水提醒发出后，后续申购仍会被动作闸门拒绝。

出口登记
========
所有提醒类型必须在 ``config.SIGNAL_EGRESS_CONFORMANCE["alert_types"]`` 登记，
未登记的类型 :func:`send_qi_alert` 直接拒发（ValueError），防止绕过出口清单。
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Dict, Optional

import pandas as pd

import config
from core.qualified_investor import QIChecker

__all__ = [
    "ALERT_TYPES",
    "build_qi_alerts",
    "detect_neeq_delisting",
    "detect_neeq_liquidity",
    "detect_reits_premium",
    "detect_snowball",
    "send_qi_alert",
]

logger = logging.getLogger(__name__)

ALERT_TYPES = tuple(config.QI_MONITOR_ALERTS)


def send_qi_alert(notifier, alert_type: str, title: str, content: str) -> bool:
    """发送合格投资者层提醒；未登记类型直接拒发（出口清单强约束）。"""
    from core.gov_compat import gov
    if alert_type not in (gov("SIGNAL_EGRESS_CONFORMANCE").get("alert_types") or ()):
        raise ValueError(
            f"提醒类型 {alert_type!r} 未在 SIGNAL_EGRESS_CONFORMANCE['alert_types'] 登记，"
            "禁止绕过出口清单发送")
    meta = dict(config.QI_MONITOR_ALERTS.get(alert_type) or {})
    level = str(meta.get("level") or "info")
    body = f"[{alert_type}] {content}\n（提醒不等于拦截：交易动作仍逐笔过合格投资者闸门）"
    return bool(notifier.send(title, body, level=level))


def detect_reits_premium(symbol: str, premium_pct: float,
                         notifier=None) -> Optional[dict]:
    """REITs 折溢价超阈值（默认折价 >10% / 溢价 >15%）。"""
    thresholds = dict(config.QI_REITS_PREMIUM_THRESHOLDS)
    premium = float(premium_pct)
    if premium <= float(thresholds["discount"]):
        kind, level = "折价", "discount"
    elif premium >= float(thresholds["premium"]):
        kind, level = "溢价", "premium"
    else:
        return None
    alert = {"alert_type": "reits_premium_alert", "symbol": symbol,
             "premium_pct": premium, "kind": level,
             "content": f"{symbol} 当前{kind} {premium:.2%}，超过阈值"}
    if notifier is not None:
        alert["sent"] = send_qi_alert(notifier, "reits_premium_alert",
                                      f"REITs {kind}提醒 {symbol}", alert["content"])
    return alert


def detect_neeq_delisting(symbol: str, frame: pd.DataFrame,
                          notifier=None) -> Optional[dict]:
    """新三板退市风险：最近一行 ``delisting_warning`` 为 True。"""
    if frame is None or len(frame) == 0 or "delisting_warning" not in frame.columns:
        return None
    if not bool(frame["delisting_warning"].iloc[-1]):
        return None
    alert = {"alert_type": "neeq_delisting_warning", "symbol": symbol,
             "content": f"{symbol} 最新交易日触发退市风险标记（ST/退市整理期）"}
    if notifier is not None:
        alert["sent"] = send_qi_alert(notifier, "neeq_delisting_warning",
                                      f"新三板退市风险 {symbol}", alert["content"])
    return alert


def detect_neeq_liquidity(symbol: str, frame: pd.DataFrame, days: int = None,
                          notifier=None) -> Optional[dict]:
    """新三板流动性恶化：最近 N 个交易日成交量全为 0。"""
    n = int(days or config.QI_NEEQ_ZERO_VOLUME_DAYS)
    if frame is None or len(frame) < n or "volume" not in frame.columns:
        return None
    recent = pd.to_numeric(frame["volume"].tail(n), errors="coerce").fillna(0)
    if (recent > 0).any():
        return None
    alert = {"alert_type": "neeq_liquidity_deterioration", "symbol": symbol,
             "zero_days": n, "content": f"{symbol} 连续 {n} 个交易日零成交，流动性恶化"}
    if notifier is not None:
        alert["sent"] = send_qi_alert(notifier, "neeq_liquidity_deterioration",
                                      f"新三板流动性恶化 {symbol}", alert["content"])
    return alert


def detect_snowball(symbol: str, spot: float, ki_level: float, ko_level: float = None,
                    observe_date: date = None, today: date = None,
                    warn_ratio: float = 0.05, notifier=None) -> Optional[dict]:
    """模拟雪球：接近敲入线（默认 5%）或到达敲出观察日。仅模拟账户。"""
    spot, ki_level = float(spot), float(ki_level)
    if ki_level > 0 and spot <= ki_level * (1.0 + float(warn_ratio)):
        alert = {"alert_type": "snowball_knock_in_warning", "symbol": symbol,
                 "spot": spot, "ki_level": ki_level,
                 "content": f"{symbol} 现价 {spot:.4f} 接近敲入线 {ki_level:.4f}（仅模拟账户）"}
        if notifier is not None:
            alert["sent"] = send_qi_alert(notifier, "snowball_knock_in_warning",
                                          f"雪球接近敲入 {symbol}", alert["content"])
        return alert
    if observe_date is not None and today is not None and \
            pd.Timestamp(observe_date).date() == pd.Timestamp(today).date():
        alert = {"alert_type": "snowball_knock_out_observe", "symbol": symbol,
                 "observe_date": str(observe_date),
                 "content": f"{symbol} 今日为敲出观察日，敲出线 {ko_level}（仅模拟账户）"}
        if notifier is not None:
            alert["sent"] = send_qi_alert(notifier, "snowball_knock_out_observe",
                                          f"雪球敲出观察 {symbol}", alert["content"])
        return alert
    return None


def build_qi_alerts(qi_checker: QIChecker, profile: dict, product_type: str,
                    decision_date=None, notifier=None) -> list:
    """资产规模变动后的资格提醒（qi_threshold_check），仍不构成拦截。"""
    alert = qi_checker.qi_threshold_check(profile, product_type, decision_date=decision_date)
    if alert.ok:
        return []
    item = {"alert_type": "qi_threshold_check", "product_type": product_type,
            "content": alert.message, "shortfall": alert.shortfall}
    if notifier is not None:
        item["sent"] = send_qi_alert(notifier, "qi_threshold_check",
                                     f"合格投资者门槛提醒 {product_type}", alert.message)
    return [item]
