# -*- coding: utf-8 -*-
"""12.17 验收：凭证加载 / 缺失校验 / 日志脱敏（全程不读真实凭证）。"""
from __future__ import annotations

import logging
import os
from io import StringIO
from pathlib import Path

import pytest

import config
from broker.base_broker import BrokerCredentialError
from broker.ctp_broker import CTPBroker
from broker.ptrade_broker import PTradeBroker
from broker.qmt_broker import QMTBroker
from core.logger import (RedactionFilter, mask_account, mask_mapping,
                         mask_secret, mask_text)

ROOT = Path(__file__).resolve().parent.parent


# ==================== 日志脱敏 ====================
def test_mask_secret_keeps_prefix_only():
    assert mask_secret("a1b2c3d4e5") == "a1b***"
    assert mask_secret("ab") == "***"
    assert mask_secret("") == ""


def test_mask_account_keeps_suffix_only():
    assert mask_account("6222021234567890") == "******7890"
    assert mask_account("123") == "***"


def test_mask_text_masks_tokens_and_accounts():
    text = mask_text("TUSHARE_TOKEN = 'a1b2c3d4e5' password: hunter2 "
                     "资金账号=6222021234567890")
    assert "a1b***" in text and "a1b2c3d4e5" not in text
    assert "hunter2" not in text
    assert "******7890" in text and "6222021234567890" not in text


def test_mask_mapping_masks_sensitive_values():
    masked = mask_mapping({"token": "abcdefgh", "password": "p@ssword",
                           "account_id": "1234567890", "symbol": "600519"})
    assert masked["token"] == "abc***"
    assert masked["password"] == "p@s***"
    assert masked["account_id"] == "******7890"
    assert masked["symbol"] == "600519"


def test_redaction_filter_on_log_handler():
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactionFilter())
    logger = logging.getLogger("test_redaction")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.info("QMT_ACCOUNT_ID=%s", "6222021234567890")
    out = stream.getvalue()
    assert "6222021234567890" not in out and "******7890" in out


def test_setup_logger_installs_redaction(tmp_path):
    from core.utils import setup_logger
    logger = setup_logger("redaction_probe", tmp_path / "probe.log")
    assert any(isinstance(f, RedactionFilter)
               for h in logger.handlers for f in h.filters)


# ==================== 凭证加载 ====================
def test_get_reads_then_scrubs_environment(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "abc123456")
    assert config._get("TUSHARE_TOKEN") == "abc123456"
    assert "TUSHARE_TOKEN" not in os.environ     # 用完立即从环境变量抹除


def test_dotenv_loads_and_leaves_no_env(tmp_path, monkeypatch):
    dotenv = pytest.importorskip("dotenv")
    env_file = tmp_path / ".env"
    env_file.write_text("QMT_ACCOUNT_ID=test_account_001\n", encoding="utf-8")
    monkeypatch.delenv("QMT_ACCOUNT_ID", raising=False)
    dotenv.load_dotenv(env_file, override=True)
    assert os.environ.get("QMT_ACCOUNT_ID") == "test_account_001"
    assert config._get("QMT_ACCOUNT_ID") == "test_account_001"
    assert "QMT_ACCOUNT_ID" not in os.environ


def test_security_config_fail_closed():
    assert config.SECURITY["fail_open_when_env_missing"] is False
    assert config.SECURITY["live_trading_double_confirm"] is True
    assert config.CONFIRM_LIVE_KEYWORD == "YES_CONFIRM_LIVE_TRADING"


# ==================== 适配器缺凭证必须拒绝 ====================
def test_qmt_connect_without_credentials_raises():
    with pytest.raises(BrokerCredentialError):
        QMTBroker(account_id="", password="", path="").connect()


def test_ptrade_connect_without_credentials_raises():
    with pytest.raises(BrokerCredentialError):
        PTradeBroker(server="", username="", password="", account_id="").connect()


def test_ctp_connect_without_credentials_raises():
    with pytest.raises(BrokerCredentialError):
        CTPBroker(user_id="", password="").connect()


# ==================== 仓库卫生 ====================
def test_gitignore_blocks_env_and_secrets():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for line in (".env", ".env.*", "!.env.example", "secrets/", "credentials/",
                 "*.key", "*.pem"):
        assert line in text


def test_env_example_has_no_real_values():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for key in ("TUSHARE_TOKEN", "QMT_ACCOUNT_ID", "QMT_PASSWORD", "PTRADE_PASSWORD",
                "CTP_USER_ID", "CTP_PASSWORD", "BINANCE_API_SECRET"):
        assert f"{key}=" in text
        for line in text.splitlines():
            if line.startswith(f"{key}="):
                assert line.split("=", 1)[1].strip() in ("",), f"{key} 模板必须留空"
