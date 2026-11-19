# -*- coding: utf-8 -*-
"""规格版本自校验命令（check-config）。

只做一件事：把指令集头部的 ``<!-- spec_version: vX.Y -->`` 与
``config.SPEC_VERSION`` 做机器比对，不一致即返回非零（fail-closed）。
"""
from __future__ import annotations

from cli_commands._common import *  # noqa: F401,F403

GROUP = "系统"


def add_subparser(sp) -> None:
    p = sp.add_parser("check-config", help=f"[{GROUP}] 校验规格版本与配置版本一致")
    p.set_defaults(handler=handler)


def _print_surface() -> None:
    """v3.48 / 13.0.19 ⑦：打印配置面哈希（两机各跑一次即可对齐）。

    surface 是对齐工具不是防篡改工具：结构漂移只提示不置 exit（keep_self_lockout_guard，
    诊断命令不得因提示性检查失败）。打印失败也不得阻断 check-config。
    """
    try:
        from core import spec_check
        out = spec_check.verify_config_surface()
        if not out.get("checked"):
            return
        note = "" if out["ok"] else f" ⚠️ {out['reason']}"
        print(f"[config_surface/{out.get('algo', 'cs-v1')}] {out['sha256']}  "
              f"（常量 {out['constants']} + 递归键 {out['keys']} = {out['elements']} 元素，"
              f"黄金向量自证={'通过' if out.get('golden_ok') else '失败'}；"
              f"两机对齐用 config_surface.elements.txt 做 comm -3）{note}")
    except Exception as exc:  # noqa: BLE001 - 打印失败不得阻断诊断命令
        print(f"[config_surface] 打印失败：{exc}")


def handler(args) -> int:
    from core import spec_check

    try:
        result = spec_check.check_spec_version()
    except (RuntimeError, ValueError) as exc:
        print(f"[不通过] {exc}")
        _print_surface()
        return 2
    if result.get("status") == "warn" and not result.get("ok"):
        # v3.52 裁定：版本不匹配 → warn（提示升级，不阻塞）
        print(f"[警告] {result['reason']}")
        _print_surface()
        return 0
    if result.get("draft"):
        # v3.46：草稿只给黄灯。哈希一致只能证明「文件没被改过」，不能证明「是权威规格」。
        print(f"[草稿/黄] 指令集={result['file']} 版本={result['header']} "
              f"config.SPEC_VERSION={result['spec_version']} "
              f"authority={result.get('authority')} 哈希文件={result.get('hash_file')}；"
              f"{result.get('reason')}")
        _print_surface()
        return 0
    print(f"[通过] 指令集={result['file']} 版本={result['header']} "
          f"config.SPEC_VERSION={result['spec_version']}")
    _print_surface()
    return 0
