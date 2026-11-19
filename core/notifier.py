# -*- coding: utf-8 -*-
"""第 8 步 · 通知模块：多渠道消息推送 + 去重 + 限流。

设计要点（对齐 config.SIGNAL_EGRESS_CONFORMANCE["push_must_tag_gated"]）：
    * 统一入口 ``send(title, content, level)``，level ∈ info/warning/error/critical；
    * 渠道可选：Console / Log 默认开启，企业微信 / 钉钉 / 邮件 / Bark 按 webhook 配置自动启用；
    * **去重**：同一消息 10 分钟内不重复发（防告警风暴刷屏）；
    * **限流**：每分钟每渠道最多 5 条（防封号 / 防打扰）；
    * 网络渠道发送失败**只记日志不抛异常**——通知是旁路，绝不能因推送失败打断盯盘主循环。

用法::

    notifiers = create_notifiers()          # 按配置自动装配
    for n in notifiers:
        n.send("止损触发", "510300 多头 5.02→4.71", level="error")
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import smtplib
import time
import urllib.error
import urllib.request
from collections import deque
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import List, Optional

logger = logging.getLogger(__name__)

LEVELS = ("info", "warning", "error", "critical")

DEDUP_WINDOW_SECONDS = 10 * 60      # 同一条消息 10 分钟内不重复发
RATE_LIMIT_MAX = 5                  # 每分钟最多发 5 条
RATE_LIMIT_WINDOW = 60.0

_LEVEL_MARK = {"info": "ℹ️", "warning": "⚠️", "error": "🚨", "critical": "💥"}


def _format_message(title: str, content: str, level: str) -> str:
    return f"{_LEVEL_MARK.get(level, '')} {title}\n{content}"


class BaseNotifier:
    """通知渠道基类：统一 send() + 去重 + 限流；子类只实现 _dispatch。

    去重与限流按**渠道实例**隔离：console 与 webhook 各自计数，避免一个
    渠道的限流把另一个渠道也堵死。
    """

    name = "base"
    # 默认关闭的可选渠道在子类里覆写为 False，且由 create_notifiers 决定最终开关
    enabled = True

    def __init__(self) -> None:
        self._recent_hashes: deque = deque(maxlen=64)   # (hash, ts)
        self._sent_times: deque = deque(maxlen=RATE_LIMIT_MAX * 3)

    # ---------------- 统一入口 ----------------
    def send(self, title: str, content: str, level: str = "info") -> bool:
        """发送一条通知；返回是否真的发出（去重/限流/关闭都返回 False）。"""
        level = str(level).lower()
        if level not in LEVELS:
            level = "info"
        if not self.enabled:
            return False

        text = _format_message(title, content, level)

        # 1) 去重：同一内容 10 分钟内只发一次
        now = time.monotonic()
        key = hashlib.sha1(text.encode("utf-8")).hexdigest()
        if any(k == key and now - ts < DEDUP_WINDOW_SECONDS
               for k, ts in self._recent_hashes):
            logger.debug("[%s] 去重：10 分钟内重复消息不再发送：%s", self.name, title)
            return False

        # 2) 限流：每分钟最多 RATE_LIMIT_MAX 条
        self._sent_times = deque(
            (t for t in self._sent_times if now - t < RATE_LIMIT_WINDOW),
            maxlen=RATE_LIMIT_MAX * 3)
        if len(self._sent_times) >= RATE_LIMIT_MAX:
            logger.warning("[%s] 限流：每分钟最多 %d 条，本条丢弃：%s",
                           self.name, RATE_LIMIT_MAX, title)
            return False

        # 3) 分发；失败不抛（通知是旁路）
        try:
            self._dispatch(text, title, content, level)
        except Exception as exc:                    # noqa: BLE001 —— 旁路必须吞异常
            logger.error("[%s] 发送失败：%s（%s）", self.name, title, exc)
            return False

        self._recent_hashes.append((key, now))
        self._sent_times.append(now)
        return True

    # ---------------- 子类实现 ----------------
    def _dispatch(self, text: str, title: str, content: str, level: str) -> None:
        raise NotImplementedError


class ConsoleNotifier(BaseNotifier):
    """控制台打印（默认开启）。"""
    name = "console"

    def _dispatch(self, text: str, title: str, content: str, level: str) -> None:
        print(text, flush=True)


class LogNotifier(BaseNotifier):
    """写日志文件（默认开启），落在 logs/monitor_notify.log。"""
    name = "log"

    def __init__(self, log_file: str = None) -> None:
        super().__init__()
        self._logger = logging.getLogger("monitor.notify")
        path = log_file or os.path.join("logs", "monitor_notify.log")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if not any(getattr(h, "_monitor_notify", False)
                   for h in self._logger.handlers):
            handler = logging.FileHandler(path, encoding="utf-8")
            handler._monitor_notify = True                     # type: ignore[attr-defined]
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s"))
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.INFO)
            self._logger.propagate = False

    def _dispatch(self, text: str, title: str, content: str, level: str) -> None:
        fn = {"info": self._logger.info, "warning": self._logger.warning,
              "error": self._logger.error, "critical": self._logger.critical}
        fn.get(level, self._logger.info)(text)


class _WebhookNotifier(BaseNotifier):
    """企业微信 / 钉钉等 webhook JSON POST 的公共实现。"""

    name = "webhook"
    endpoint = ""                       # 子类覆写
    payload_builder = None              # 子类覆写为 callable(title, content) -> dict

    def __init__(self, webhook_url: str = "", secret: str = "") -> None:
        super().__init__()
        self.webhook_url = str(webhook_url or "")
        self.secret = str(secret or "")
        # 未配置 webhook 视为未启用，create_notifiers 会跳过
        if not self.webhook_url:
            self.enabled = False

    def _dispatch(self, text: str, title: str, content: str, level: str) -> None:
        body = json.dumps(self._build_payload(text, content),
                          ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.webhook_url, data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        # 短超时：通知不能拖慢盯盘主循环
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8") or "{}")
        err = result.get("errcode", result.get("errCode"))
        if err not in (None, 0, "0"):
            raise RuntimeError(f"webhook 返回异常: {result}")

    def _build_payload(self, text: str, content: str) -> dict:
        raise NotImplementedError


class WeChatWorkNotifier(_WebhookNotifier):
    """企业微信机器人（webhook 方式）。配置键：config/环境变量。"""
    name = "wechat_work"

    def _build_payload(self, text: str, content: str) -> dict:
        return {"msgtype": "text", "text": {"content": text[:2048]}}


class DingTalkNotifier(_WebhookNotifier):
    """钉钉机器人推送。配置键：config/环境变量。"""
    name = "dingtalk"

    def _build_payload(self, text: str, content: str) -> dict:
        payload = {"msgtype": "text", "text": {"content": text[:20000]}}
        if self.secret:
            payload["at"] = {"isAtAll": False}
        return payload


class EmailNotifier(BaseNotifier):
    """邮件推送（SMTP）。配置键齐全才启用。"""
    name = "email"

    def __init__(self, smtp_host: str = "", smtp_port: int = 465,
                 user: str = "", password: str = "",
                 to_addrs: Optional[List[str]] = None) -> None:
        super().__init__()
        self.smtp_host = str(smtp_host or "")
        self.smtp_port = int(smtp_port or 465)
        self.user = str(user or "")
        self.password = str(password or "")
        self.to_addrs = [a for a in (to_addrs or []) if a]
        if not (self.smtp_host and self.user and self.password and self.to_addrs):
            self.enabled = False

    def _dispatch(self, text: str, title: str, content: str, level: str) -> None:
        subject = f"[{self.name}][{level}] {title}"
        msg = MIMEText(content, "plain", "utf-8")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = formataddr((Header("量化盯盘", "utf-8").encode(), self.user))
        msg["To"] = ", ".join(self.to_addrs)
        with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=15) as smtp:
            smtp.login(self.user, self.password)
            smtp.sendmail(self.user, self.to_addrs, msg.as_string())


class BarkNotifier(BaseNotifier):
    """iOS Bark 推送（https://api.day.app/<key>/<title>/<body>）。"""
    name = "bark"

    def __init__(self, bark_key: str = "", server: str = "https://api.day.app") -> None:
        super().__init__()
        self.bark_key = str(bark_key or "")
        self.server = str(server or "https://api.day.app").rstrip("/")
        if not self.bark_key:
            self.enabled = False

    def _dispatch(self, text: str, title: str, content: str, level: str) -> None:
        from urllib.parse import quote
        url = f"{self.server}/{self.bark_key}/{quote(title)}/{quote(content[:200])}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8") or "{}")
        if int(result.get("code", -1)) != 200:
            raise RuntimeError(f"Bark 返回异常: {result}")


def _cfg(name: str, default: str = "") -> str:
    """config → 环境变量 依次取值（凭证放 .env，代码里不落密钥）。"""
    try:
        import config as cfg
        value = getattr(cfg, name, None)
        if value:
            return str(value)
    except Exception:                       # noqa: BLE001 —— 配置缺失不阻断
        pass
    return os.environ.get(name, default)


def create_notifiers() -> List[BaseNotifier]:
    """按配置装配渠道列表：Console/Log 默认开启，其余按 webhook/凭证自动启用。

    这是 monitor 拿到 notifier 列表的唯一推荐入口；测试里直接手工构造
    ConsoleNotifier() 即可。
    """
    notifiers: List[BaseNotifier] = [ConsoleNotifier(), LogNotifier()]

    if str(_cfg("MONITOR_ENABLE_WECHAT_WORK", "")).lower() in ("1", "true", "yes"):
        notifiers.append(WeChatWorkNotifier(
            webhook_url=_cfg("MONITOR_WECHAT_WORK_WEBHOOK")))
    if str(_cfg("MONITOR_ENABLE_DINGTALK", "")).lower() in ("1", "true", "yes"):
        notifiers.append(DingTalkNotifier(
            webhook_url=_cfg("MONITOR_DINGTALK_WEBHOOK")))
    email_to = [a for a in _cfg("MONITOR_EMAIL_TO", "").split(",") if a]
    if _cfg("MONITOR_EMAIL_SMTP_HOST") and email_to:
        notifiers.append(EmailNotifier(
            smtp_host=_cfg("MONITOR_EMAIL_SMTP_HOST"),
            smtp_port=int(_cfg("MONITOR_EMAIL_SMTP_PORT", "465") or 465),
            user=_cfg("MONITOR_EMAIL_USER"), password=_cfg("MONITOR_EMAIL_PASSWORD"),
            to_addrs=email_to))
    if _cfg("MONITOR_BARK_KEY"):
        notifiers.append(BarkNotifier(bark_key=_cfg("MONITOR_BARK_KEY")))
    return notifiers
