# -*- coding: utf-8 -*-
"""实盘多渠道告警（live/notifier.py）—— 12.9。

复用第 8 步 ``core/notifier.py`` 的渠道实现（企业微信 / 钉钉 / Server酱 / 邮件），
本模块只负责**实盘事件语义**：

* 开平仓成交回报、订单状态变化、风控触发、每日开盘/收盘报告、
  行情断线/重连/程序崩溃、盯盘信号；
* **严重告警重复推送 3 次**确保看到（核心 notifier 有 10 分钟去重，
  因此每次追加「第 n/3 次」使其成为不同消息）；
* 推送是旁路：失败只记日志，绝不打断主循环。
"""
from __future__ import annotations

import logging
from typing import List

__all__ = ["LiveNotifier", "LIVE_EVENTS"]

LIVE_EVENTS = ("fill", "order_status", "risk_trigger", "disconnect", "reconnect",
               "crash", "open_report", "close_report", "signal", "kill_switch",
               "reconcile", "info")

_SEVERE = ("error", "critical")


class LiveNotifier:
    def __init__(self, notifiers: List = None, repeat_severe: int = 3,
                 logger=None) -> None:
        self.notifiers = list(notifiers or [])
        self.repeat_severe = max(1, int(repeat_severe))
        self.logger = logger or logging.getLogger("live.notifier")
        self.sent = 0

    def notify(self, event: str, title: str, content: str,
               level: str = "info") -> int:
        """推送一条实盘事件；返回成功发出的次数。"""
        event = str(event or "info")
        level = str(level or "info").lower()
        if event not in LIVE_EVENTS:
            self.logger.debug("未登记实盘事件 %s，按 info 推送", event)
        repeat = self.repeat_severe if level in _SEVERE else 1
        ok = 0
        for idx in range(repeat):
            suffix = f"（第 {idx + 1}/{repeat} 次）" if repeat > 1 else ""
            for notifier in self.notifiers:
                try:
                    if notifier.send(f"{title}{suffix}", content, level=level):
                        ok += 1
                        self.sent += 1
                except Exception as exc:  # noqa: BLE001 - 通知是旁路，不打断主循环
                    self.logger.warning("告警推送失败（%s）：%s", event, exc)
        if not self.notifiers:
            self.logger.info("[%s] %s | %s", level, title, content)
        return ok

    # ==================== 事件便捷方法 ====================
    def on_fill(self, symbol: str, direction: str, volume: float,
                price: float, mode: str = "") -> int:
        return self.notify("fill", "成交回报",
                           f"[{mode}] {symbol} {direction} {volume:g} @ {price:g}")

    def on_order_status(self, client_order_id: str, status: str,
                        mode: str = "") -> int:
        return self.notify("order_status", "订单状态变化",
                           f"[{mode}] {client_order_id} → {status}")

    def on_risk(self, reason: str, mode: str = "") -> int:
        return self.notify("risk_trigger", "风控触发", f"[{mode}] {reason}",
                           level="critical")

    def on_disconnect(self, detail: str = "") -> int:
        return self.notify("disconnect", "行情/交易断线", detail, level="critical")

    def on_reconnect(self, detail: str = "") -> int:
        return self.notify("reconnect", "连接已恢复", detail, level="warning")

    def on_crash(self, detail: str = "") -> int:
        return self.notify("crash", "程序异常", detail, level="critical")

    def on_open_report(self, content: str) -> int:
        return self.notify("open_report", "开盘报告", content)

    def on_close_report(self, content: str) -> int:
        return self.notify("close_report", "收盘报告", content)

    def on_signal(self, content: str) -> int:
        return self.notify("signal", "盯盘信号", content)

    def on_kill_switch(self, reason: str) -> int:
        return self.notify("kill_switch", "已紧急停机", reason, level="critical")

    def on_reconcile(self, content: str, ok: bool = True) -> int:
        return self.notify("reconcile", "对账结果", content,
                           level="info" if ok else "critical")
