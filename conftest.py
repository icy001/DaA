# -*- coding: utf-8 -*-
"""pytest 公共配置（12.16）：公共 fixture + 网络测试自动跳过。

所有测试默认**不依赖真实下单、不碰真实资金**：券商/CTP 适配器一律用注入的假
客户端，缺 SDK / 缺网络时自动 skip 而不是 fail。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def sim_env(monkeypatch, tmp_path):
    """仿真环境 fixture：强制关闭真实下单，所有状态文件落到临时目录。"""
    import config
    monkeypatch.setattr(config, "LIVE_TRADING_ENABLED", False, raising=False)
    return {"base_dir": tmp_path,
            "order_ids": tmp_path / "order_ids.json",
            "reconcile": tmp_path / "reconcile_state.json",
            "kill_switch": tmp_path / "KILL_SWITCH",
            "audit_dir": tmp_path / "audit_logs"}


def pytest_collection_modifyitems(config, items):
    """离线环境（QUANT_OFFLINE=1）自动跳过 network 标记的用例。"""
    if os.environ.get("QUANT_OFFLINE", "") != "1":
        return
    skip = pytest.mark.skip(reason="QUANT_OFFLINE=1：跳过需要联网的测试")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)
