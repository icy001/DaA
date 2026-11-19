# -*- coding: utf-8 -*-
"""日志脱敏中间件（core/logger.py）—— 12.17.4。

最容易被忽略的泄漏点：日志里打印了 Token / 密码 / 资金账号。
本模块提供统一的脱敏函数 + ``logging.Filter``，由 ``core.utils.setup_logger``
自动挂到每个 handler 上：

* 敏感字段（token/password/secret/authorization/...）只保留前 3 位 + ``***``；
* 资金账号只保留后 4 位（``资金账号 ******1234``）；
* 异常栈里的敏感字段同样走脱敏（Filter 作用于最终 message）。

注意：**审计日志（live/audit_log.py）必须保留完整账户标识**以满足监管留存，
它不经过本脱敏中间件，且写在已被 .gitignore 屏蔽的 audit_logs/。
"""
from __future__ import annotations

import logging
import re
from typing import Mapping

import config

__all__ = ["mask_secret", "mask_account", "mask_text", "mask_mapping",
           "RedactionFilter", "install_redaction"]

SECRET_KEYS = ("token", "password", "passwd", "secret", "authorization",
               "auth_code", "api_key", "api_secret", "passphrase", "webhook",
               "sendkey")

_KEEP = int((getattr(config, "SECURITY", {}) or {}).get("mask_keep_chars", 3))

# 允许键名带前缀（如 TUSHARE_TOKEN / QMT_PASSWORD），前缀原样保留只脱敏值
_SECRET_RE = re.compile(
    r"(?i)([A-Za-z0-9_]*(?:" + "|".join(SECRET_KEYS) + r"))"
    r"(\s*[=:]\s*)(['\"]?)([^\s,'\"&}]+)")
_ACCOUNT_RE = re.compile(
    r"(资金账号|资金账户|交易账号|account[_ ]?id|account_id)(\s*[=:]\s*)(['\"]?)"
    r"([0-9A-Za-z_-]{5,})", re.I)


def mask_secret(value, keep: int = None) -> str:
    """保留前 N 位 + ***；空值返回空串。"""
    keep = _KEEP if keep is None else int(keep)
    text = str(value or "")
    if not text:
        return ""
    return f"{text[:keep]}***" if len(text) > keep else "***"


def mask_account(value) -> str:
    """资金账号只保留后 4 位。"""
    text = str(value or "")
    if not text:
        return ""
    return f"******{text[-4:]}" if len(text) > 4 else "***"


def _mask_secret_match(match: re.Match) -> str:
    return f"{match.group(1)}{match.group(2)}{match.group(3)}{mask_secret(match.group(4))}"


def _mask_account_match(match: re.Match) -> str:
    return f"{match.group(1)}{match.group(2)}{match.group(3)}{mask_account(match.group(4))}"


def mask_text(text) -> str:
    """对任意文本做脱敏（日志、异常栈、报告摘要）。"""
    out = _SECRET_RE.sub(_mask_secret_match, str(text))
    return _ACCOUNT_RE.sub(_mask_account_match, out)


def mask_mapping(data: Mapping) -> dict:
    """字段名命中敏感清单时值脱敏，其余原样。"""
    out = {}
    for key, value in dict(data or {}).items():
        low = str(key).lower()
        if any(name in low for name in SECRET_KEYS):
            out[key] = mask_secret(value)
        elif "account" in low:
            out[key] = mask_account(value)
        else:
            out[key] = value
    return out


class RedactionFilter(logging.Filter):
    """挂到 handler 上：输出前统一脱敏（含 msg 与 args）。"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = mask_text(record.getMessage())
            record.args = ()
        except Exception:  # noqa: BLE001 - 脱敏失败不能影响日志本身
            pass
        return True


def install_redaction(logger: logging.Logger) -> logging.Logger:
    """给 logger 的每个 handler 挂一次脱敏 Filter（幂等）。"""
    if not (getattr(config, "SECURITY", {}) or {}).get("mask_secret_logs", True):
        return logger
    for handler in logger.handlers:
        if not any(isinstance(f, RedactionFilter) for f in handler.filters):
            handler.addFilter(RedactionFilter())
    return logger
