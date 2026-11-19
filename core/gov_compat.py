# -*- coding: utf-8 -*-
"""治理块读取的唯一入口（v3.52 / 13.0.23 读点适配）。

发布方血统件的 30 个治理块是 surface 权威；我方代码运行必需、但发布方块里
没有的操作键放在业务区 ``config._GOV_RUNTIME_COMPAT``（不进 surface）。
``gov(block)`` = 发布方标准键优先 + 业务区操作键【深合并】补位：
嵌套 dict 逐键合并（操作子树整体来自 compat），标量 compat 覆盖。
禁止再往治理块里塞键。
"""
from __future__ import annotations

from typing import Any, Dict

import config


def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def gov(block: str) -> dict:
    base = dict(getattr(config, block, None) or {})
    compat_all = dict((getattr(config, "_GOV_RUNTIME_COMPAT", {}) or {}) or {})
    overlay = dict(compat_all.get(block, {}) or {})
    # 显式操作值覆盖最优先（已报备的值级差异，如 allowed_sources 拼写、authority 状态）
    op = dict(compat_all.get("OPERATIONAL_OVERRIDES", {}) or {}).get(block, {})
    merged = _deep_merge(base, overlay)
    return _deep_merge(merged, op) if op else merged
