# -*- coding: utf-8 -*-
"""CLI 控制平面闸门（core/cli_gate.py）——第 11 步 11.0 唯一实现。

**一键入口是「控制平面」，不是随便一组脚本**
================================================
``main.py`` 是整个系统的总开关：运行模式、数据导入、子命令默认值都从这里进来。
控制平面失守的典型形态有三类，本模块逐一封死：

1. **旁路开关**：出现 ``--no-risk`` / ``--skip-check`` / ``--force-live`` 之类
   一键关掉闸门/风控/时效的旗标。``forbid_bypass_flags`` 黑名单在
   ``config.CLI_CONFORMANCE`` 中登记，``assert_no_bypass_flags()`` 在 argv 层
   直接拒收；``assert_no_bypass_registration()`` 同时审计 argparse 注册面，
   防止有人把旁路旗标注册进某个子命令。

2. **静默提升运行模式**：``backtest → paper → live`` 是风险递增的阶梯。
   运行期**只允许降级**（live→paper→backtest 随时可以）；提升必须同时满足：
   - ``promote_requires_checklist``：策略上线检查清单（16 项）无「不通过」；
   - ``promote_requires_confirm``：调用方显式确认（CLI 的 ``--confirm``）。
   二者缺一即抛 :class:`RunModePromotionError`——「提升被拒或需显式确认」。

3. **默认值口径漂移**：子命令默认值必须集中引用
   ``config.CLI_CONFORMANCE['cli_defaults']``（与 ``INITIAL_CASH`` /
   ``DEFAULT_START`` 等同源）。本模块提供 ``cli_default()`` 供 ``main.py``
   取值，禁止在 argparse 里再写一份硬编码。

实现约束（与平台其余闸门一致）：
* 本模块是运行模式闸门的**唯一实现**；``main.py`` 只调用，不重复实现；
* 闸门判定 fail-closed：任何无法确认安全的状态一律拒绝，绝不默认放行；
* checklist 拦截走 ``tools.strategy_checklist.build_rows``（四类计数：
  通过 / 警告 / 不通过 / 不适用），存在「不通过」即视为不可提升。
"""
from __future__ import annotations

import argparse
import sys
from typing import Callable, Dict, List, Optional

import config

__all__ = [
    "BypassFlagError",
    "RunModeError",
    "RunModePromotionError",
    "assert_no_bypass_flags",
    "assert_no_bypass_registration",
    "assert_no_structural_bypass",
    "capability_violations",
    "bypass_flags",
    "cli_default",
    "current_mode",
    "enter_mode",
    "mode_rank",
    "validate_mode",
]

# ==================== 异常 ====================


class RunModeError(RuntimeError):
    """运行模式非法（未知模式 / 越级操作）。"""


class RunModePromotionError(RunModeError):
    """运行模式提升被门禁拒绝——提升被拒，或需显式确认。"""


class BypassFlagError(RuntimeError):
    """检测到旁路开关——控制平面拒绝执行。"""


# ==================== 事实源读取 ====================

def _conf() -> Dict:
    return dict(getattr(config, "CLI_CONFORMANCE", {}) or {})


def ladder() -> List[str]:
    """运行模式阶梯：backtest < paper < live（config 唯一事实源）。"""
    return [str(m) for m in _conf().get("mode_order")
            or ["backtest", "paper", "live"]]


def bypass_flags() -> List[str]:
    """旁路开关黑名单（config 唯一事实源）。"""
    return [str(f) for f in _conf().get("forbidden_flags") or []]


def validate_mode(mode: str) -> str:
    """运行模式封闭白名单（v3.49 / 13.0.20 ④）：查阶梯/矩阵**之前**先验。

    v3.48 靠「阶梯 miss 或矩阵 miss + default=deny」碰巧拦住；只要实现写成
    ``.get(mode, default)``、或矩阵/阶梯里多一条宽松项，未登记模式就会 fail-open。
    现在统一走 :func:`core.spec_check.validate_mode`：``"liv "``（带空格笔误）、
    ``"prod_live"``（CLI 自定义串）一律拒，不做 strip/纠正——纠正本身就是猜。
    异常转成 :class:`RunModeError`，保持调用方（含测试）原有契约。
    """
    from core.spec_check import validate_mode as _validate
    try:
        return _validate(mode)
    except ValueError as exc:
        raise RunModeError(str(exc)) from exc


def mode_rank(mode: str) -> int:
    """模式在阶梯中的序（越大风险越高）；未登记 / 不在阶梯的模式直接报错。"""
    mode = validate_mode(mode)
    lad = ladder()
    if mode not in lad:
        raise RunModeError(f"未知运行模式 {mode!r}，只允许 {lad}")
    return lad.index(mode)


def current_mode() -> str:
    """当前全局运行模式（config.RUN_MODE）；越界值同样白名单先行并报错。"""
    return validate_mode(getattr(config, "RUN_MODE", "backtest"))


def cli_default(key: str):
    """子命令默认值统一取数口：main.py 的 argparse 只从这里拿默认值。"""
    # v3.52：cli_defaults 属业务配置（_USER_CLI_DEFAULTS），不在治理块（13.0.23 读点适配）
    table = dict(getattr(config, "_USER_CLI_DEFAULTS", {}).get("cli_defaults") or {})
    if key not in table:
        raise KeyError(f"CLI 默认值 {key!r} 未在 _USER_CLI_DEFAULTS['cli_defaults'] 登记")
    return table[key]


# ==================== 1) 旁路开关审计 ====================

def assert_no_bypass_flags(argv: List[str]) -> None:
    """argv 级旁路开关审计：黑名单旗标出现即拒（含 ``--flag=value`` 变体）。"""
    if not _conf().get("forbid_bypass_flags", True):
        return
    blacklist = bypass_flags()
    for raw in [str(a) for a in (argv or [])]:
        token = raw.split("=", 1)[0].strip().lower()
        for bad in blacklist:
            if token == bad.lower():
                raise BypassFlagError(
                    f"检测到旁路开关 {raw!r}（黑名单 {blacklist}）：禁止通过命令行"
                    "绕过闸门/风控/时效校验，请改走对应合规流程")


def assert_no_bypass_registration(parser) -> None:
    """argparse 注册面审计：任何子命令都不得注册旁路旗标。"""
    if not _conf().get("forbid_bypass_flags", True):
        return
    blacklist = {b.lower() for b in bypass_flags()}
    registered: List[str] = []
    for action in getattr(parser, "_actions", []):
        registered.extend(str(o) for o in getattr(action, "option_strings", []))
        sub = getattr(action, "choices", None)
        if sub and all(hasattr(c, "_actions") for c in sub):
            for sub_parser in sub:
                for act in getattr(sub_parser, "_actions", []):
                    registered.extend(str(o) for o in
                                      getattr(act, "option_strings", []))
    hits = sorted({o for o in registered if o.lower() in blacklist})
    if hits:
        raise BypassFlagError(
            f"argparse 注册了旁路开关 {hits}（黑名单 {sorted(blacklist)}）："
            "控制平面禁止提供任何绕过闸门的旗标")


# ==================== 1b) 结构化禁参审计（K1） ====================
# 黑名单比的是参数名，而参数名由写代码的人自己起（--no-gate 改成 --gate-off 就绕过）。
# 因此这里审计的是「能力」而非「字符串」：任何 action 只要可能
#   (a) 接受一个能提升 RUN_MODE 的值，或
#   (b) 引用闸门/风控/时效/预热能力（布尔开关尤其危险），
# 就违规——与参数叫什么无关。唯一豁免是 config 登记、经 enter_mode 双门禁的
# set-mode --to（audited_mode_actions）。

_CAPABILITY_TOKENS = ("gate", "risk", "fresh", "stale", "warmup", "bypass")
# 非布尔参数里也不该出现「闸门/旁路/风控/时效」字样（预热根数是数值配置，允许）
_HARD_TOKENS = ("gate", "risk", "fresh", "stale", "bypass")
_MODE_DESTS = ("mode", "runmode")


def _norm(text) -> str:
    return str(text or "").lower().replace("_", "").replace("-", "")


def _audited_mode_actions() -> set:
    conf = dict(getattr(config, "CLI_CONFORMANCE", {}) or {})
    return {(str(a.get("command")), str(a.get("dest")))
            for a in (getattr(config, "_USER_CLI_DEFAULTS", {}).get("audited_mode_actions") or [])}


def _iter_parsers(parser, name: str = ""):
    yield name, parser
    for action in getattr(parser, "_actions", []):
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            for sub_name, sub in choices.items():
                yield from _iter_parsers(sub, f"{name} {sub_name}".strip())


def capability_violations(parser) -> List[str]:
    """返回结构化违规清单（空 = 通过）；测试与入口共用同一判定。"""
    issues: List[str] = []
    audited = _audited_mode_actions()
    ladder = {str(m).lower() for m in (dict(getattr(config, "CLI_CONFORMANCE", {}) or {})
                                       .get("mode_order") or [])}
    for name, sub in _iter_parsers(parser):
        label = name or "<root>"
        for action in getattr(sub, "_actions", []):
            if isinstance(action, argparse._SubParsersAction):
                continue                 # 子命令表本身不是可配置能力
            flags = [str(o).lower() for o in getattr(action, "option_strings", [])]
            dest = str(getattr(action, "dest", "") or "")
            tokens = [_norm(dest)] + [_norm(f) for f in flags]
            is_toggle = isinstance(action, (argparse._StoreTrueAction,
                                            argparse._StoreFalseAction,
                                            argparse._CountAction))
            # (b) 引用闸门能力：布尔开关一律违规（开关只能用来关闸门）；
            #     非布尔参数只要出现 gate/risk/fresh/stale/bypass 也违规
            hit = ([t for t in tokens if any(tok in t for tok in _CAPABILITY_TOKENS)]
                   if is_toggle else
                   [t for t in tokens if any(tok in t for tok in _HARD_TOKENS)])
            if hit:
                issues.append(f"{label}: 参数 {flags or dest} 触及闸门能力 {hit}")
                continue
            # (a0) 布尔开关名里出现阶梯模式（--live / --paper）：开关只能用于提升模式
            if is_toggle:
                mode_hit = [t for t in tokens if any(m in t for m in ladder)]
                if mode_hit:
                    issues.append(f"{label}: 参数 {flags or dest} 可为提升运行模式"
                                  f"（命中 {mode_hit}），未登记为受控路径")
                    continue
            # (a) 能写 RUN_MODE：dest/旗标名像模式，或 choices 含阶梯里的模式
            writes_mode = (any(t in _MODE_DESTS for t in tokens)
                           or any(t in ("--mode", "--runmode") for t in tokens))
            choices = {str(c).lower() for c in (getattr(action, "choices", None) or [])}
            promotes = bool(choices & ladder)
            if (writes_mode or promotes) and (name, dest) not in audited:
                issues.append(f"{label}: 参数 {flags or dest} 可写/提升运行模式"
                              f"（choices={sorted(choices)}），未登记为受控路径")
        if name and " " not in name and not callable(sub.get_default("handler")):
            issues.append(f"{label}: 未注册 handler，绕过统一分发")
    return issues


def assert_no_structural_bypass(parser) -> None:
    """结构化禁参审计（fail-closed）：与参数命名无关，只看能力。"""
    issues = capability_violations(parser)
    if issues:
        raise BypassFlagError(
            "结构化禁参审计失败（CLI_CONFORMANCE['forbidden_flags_check_mode']="
            f"{dict(getattr(config, 'CLI_CONFORMANCE', {}) or {}).get('forbidden_flags_check_mode')}）："
            + "；".join(issues))


# ==================== 2) 运行模式闸门 ====================

def _run_checklist_rows(strategy: str) -> List[tuple]:
    """跑真实上线检查清单（tools.strategy_checklist.build_rows，四类计数）。"""
    from tools.strategy_checklist import build_rows
    return build_rows(str(strategy), {}, drawdown_threshold=0.2, min_amount=1e7)


def enter_mode(target: str, strategy: Optional[str] = None,
               confirm: bool = False,
               checklist_fn: Optional[Callable[[str], List[tuple]]] = None,
               _current: Optional[str] = None) -> Dict:
    """运行模式唯一闸门：降级直接放行；提升必须过清单门禁 + 显式确认。

    参数
    ----
    target:  目标模式（backtest / paper / live）
    strategy: 提升时参与上线检查清单的策略名（降级不需要）
    confirm:  显式确认（CLI ``--confirm``）；``promote_requires_confirm`` 开启时
              缺省即拒
    checklist_fn: 清单函数注入缝（测试用；生产默认走 tools.strategy_checklist）

    返回 {ok, from, to, mode, checklist}；拒绝时抛 :class:`RunModePromotionError`。
    """
    conf = _conf()
    target = validate_mode(target)      # v3.49 / 13.0.20 ④：阶梯之前先过封闭白名单
    cur = validate_mode(_current if _current is not None else current_mode())
    rank_target, rank_cur = mode_rank(target), mode_rank(cur)

    if rank_target <= rank_cur:
        # 降级 / 同级：安全方向，直接放行
        config.RUN_MODE = target
        return {"ok": True, "from": cur, "to": target, "mode": target,
                "checklist": None, "direction": "downgrade" if rank_target < rank_cur
                else "same"}

    # ---- 提升（风险递增方向）----
    # v3.52：发布方键为 promote_requires 列表（checklist_pass / explicit_confirm_flag 等）
    if "checklist_pass" not in (conf.get("promote_requires") or []):
        raise RunModePromotionError(
            f"禁止提升运行模式 {cur} → {target}：CLI_CONFORMANCE 未开启提升门禁，"
            "fail-closed 拒绝（请在 config 显式配置后重试）")

    if strategy is None or not str(strategy).strip():
        raise RunModePromotionError(
            f"提升运行模式 {cur} → {target} 需要指定策略并过上线检查清单："
            "未提供 strategy，拒绝提升（提升被拒）")

    rows = list((checklist_fn or _run_checklist_rows)(str(strategy)))
    fails = [r for r in rows if len(r) >= 3 and str(r[2]) == "FAIL"]
    if fails:
        detail = "；".join(f"第{r[0]}项 {r[1]}" for r in fails[:3])
        raise RunModePromotionError(
            f"提升运行模式 {cur} → {target} 被上线检查清单拦截：存在「不通过」"
            f"{len(fails)} 项（{detail}）——禁止带病上模拟盘/实盘")

    if "explicit_confirm_flag" in (conf.get("promote_requires") or []) and not bool(confirm):
        raise RunModePromotionError(
            f"提升运行模式 {cur} → {target} 需显式确认（--confirm）："
            "清单已通过，但未获显式确认前拒绝提升（提升被拒/需显式确认）")

    config.RUN_MODE = target
    return {"ok": True, "from": cur, "to": target, "mode": target,
            "checklist": rows, "direction": "promote"}


def guard_argv(argv: Optional[List[str]] = None) -> List[str]:
    """main() 入口第一道防线：旁路开关审计（fail-closed）。"""
    args = list(sys.argv[1:] if argv is None else argv)
    assert_no_bypass_flags(args)
    return args
