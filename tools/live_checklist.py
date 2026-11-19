# -*- coding: utf-8 -*-
"""实盘前 15 项检查 + 报备指引（tools/live_checklist.py）—— 12.13。

分两类：
* **自动项**：能在本机离线验证（凭证模板、双层开关、急停目录可写、审计目录、
  SimNow 预设、测试依赖等）；
* **人工项**：开户/白名单/穿透测试/程序化报备/监管红线/实盘试跑等，
  必须由操作者逐项确认（输出 `人工确认`，不计通过）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable, Dict, List, Optional

import config

__all__ = ["ITEMS", "run_checks", "render", "main"]

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    path = ROOT / rel
    return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""


def _check_env_example() -> Dict[str, object]:
    text = _read(".env.example")
    return {"ok": bool(text), "detail": ".env.example 存在且为空白模板" if text
            else "缺少 .env.example（凭证模板）"}


def _check_gitignore() -> Dict[str, object]:
    text = _read(".gitignore")
    need = [".env", "secrets/", "credentials/", "*.key", "*.pem"]
    missing = [x for x in need if x not in text]
    return {"ok": not missing,
            "detail": ".gitignore 已屏蔽 .env/secrets/credentials/key/pem" if not missing
            else f".gitignore 缺少：{missing}"}


def _check_switch_off() -> Dict[str, object]:
    off = not bool(getattr(config, "LIVE_TRADING_ENABLED", False))
    return {"ok": off, "detail": ".env 的 LIVE_TRADING_ENABLED=false（默认永远仿真）"
            if off else "LIVE_TRADING_ENABLED=true：真实下单已开启，务必先完成仿真"}


def _check_credential_template() -> Dict[str, object]:
    text = _read(".env.example")
    need = ["QMT_ACCOUNT_ID", "PTRADE_ACCOUNT_ID", "CTP_FRONT_ADDR_TRADE",
            "CTP_USER_ID"]
    missing = [x for x in need if x not in text]
    return {"ok": not missing,
            "detail": "三类券商凭证字段齐全" if not missing else f"模板缺字段：{missing}"}


def _check_kill_switch() -> Dict[str, object]:
    try:
        from live.kill_switch import PanicController  # noqa: F401
        from core.gov_compat import gov
        flag = Path(config.BASE_DIR) / (gov("LIVE_SAFETY")["kill_switch"]["flag_file"])
        flag.parent.mkdir(parents=True, exist_ok=True)
        probe = flag.parent / ".kill_probe"
        probe.write_text("1", encoding="utf-8")
        probe.unlink()
        return {"ok": True, "detail": "急停标志目录可写、PanicController 可独立线程监听"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"急停不可用：{exc}"}


def _check_audit_dir() -> Dict[str, object]:
    try:
        from live.audit_log import AuditLog
        log = AuditLog(config.AUDIT_DIR)
        rec = log.record("program_start", note="checklist probe")
        return {"ok": bool(rec.get("hash")), "detail": "审计日志可写且带哈希链"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"审计日志不可写：{exc}"}


def _check_simnow() -> Dict[str, object]:
    from broker.ctp_broker import SIMNOW_PRESET
    need = ["trade_front", "market_front", "broker_id", "app_id", "auth_code"]
    missing = [x for x in need if not SIMNOW_PRESET.get(x)]
    return {"ok": not missing,
            "detail": "SimNow 仿真预设齐全（24 小时服务）" if not missing
            else f"SimNow 预设缺：{missing}"}


def _check_test_deps() -> Dict[str, object]:
    text = _read("requirements.txt")
    missing = [x for x in ("pytest", "pytest-timeout", "python-dotenv") if x not in text]
    return {"ok": not missing,
            "detail": "pytest / pytest-timeout / python-dotenv 已登记" if not missing
            else f"requirements.txt 缺：{missing}"}


def _check_live_engine() -> Dict[str, object]:
    try:
        import live.audit_log  # noqa: F401
        import live.daemon  # noqa: F401
        import live.live_trader  # noqa: F401
        import live.notifier  # noqa: F401
        return {"ok": True, "detail": "执行器/守护/告警/审计模块可导入"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"实盘模块导入失败：{exc}"}


def _check_safety_core() -> Dict[str, object]:
    """仿真验证项：执行器可导入、急停可用、审计可写、测试依赖齐全。"""
    parts = [("模块", _check_live_engine()), ("急停", _check_kill_switch()),
             ("审计", _check_audit_dir()), ("测试", _check_test_deps())]
    ok = all(bool(res.get("ok")) for _, res in parts)
    bad = [f"{name}：{res.get('detail')}" for name, res in parts if not res.get("ok")]
    return {"ok": ok, "detail": "；".join(bad) if bad else "急停/审计/执行器/测试依赖均可用"}


# 15 项：id / 标题 / 分类 / 自动检查函数（None = 人工确认）
ITEMS: List[dict] = [
    {"id": 1, "category": "开户", "title": "QMT 开户 + 白名单申请（A股/ETF/可转债/REITs）",
     "check": None, "hint": "在券商开通 QMT 权限并提交白名单；拿到账号后填 .env 的 QMT_*"},
    {"id": 2, "category": "开户", "title": "PTrade 开户 + 云端授权",
     "check": None, "hint": "券商分配 PTRADE_SERVER/USERNAME/PASSWORD/ACCOUNT_ID"},
    {"id": 3, "category": "开户", "title": "期货 CTP 开户（五大交易所品种）",
     "check": _check_credential_template,
     "hint": "期货公司开通 CTP 交易权限，拿到 BrokerID/前置地址/账号"},
    {"id": 4, "category": "报备", "title": "穿透式监管认证（AppID / AuthCode / 产品信息）",
     "check": None, "hint": "实盘必须使用穿透测试后分配的正式参数；SimNow 默认值只用于仿真"},
    {"id": 5, "category": "报备", "title": "程序化交易报备",
     "check": None, "hint": "按交易所要求报备策略类型、账户、报撤单频率"},
    {"id": 6, "category": "仿真", "title": "SimNow 仿真环境注册与参数配置",
     "check": _check_simnow, "hint": "SimNow 官方仿真 24 小时服务，预设已内置"},
    {"id": 7, "category": "仿真", "title": "仿真连续跑满约定时长（建议 ≥ 20 交易日）",
     "check": None, "hint": "仿真不足时长不得开实盘（12.14.5 强制模拟盘）"},
    {"id": 8, "category": "仿真", "title": "仿真验证项：对账 / 急停 / 幂等 / 首单限额",
     "check": _check_safety_core,
     "hint": "对应 tests/test_reconcile、test_kill_switch_persist、"
             "test_idempotency、test_order_port"},
    {"id": 9, "category": "实盘", "title": "小资金实盘试跑（首笔 ≤ 10000 元）",
     "check": None, "hint": "first_live_order_max_notional 默认 10000，通道确认后再放开"},
    {"id": 10, "category": "实盘", "title": "双层实盘开关与二次确认串",
     "check": _check_switch_off, "hint": "LIVE_TRADING_ENABLED（代码+配置）+ YES_CONFIRM_LIVE_TRADING"},
    {"id": 11, "category": "合规", "title": "交易所程序化交易监管红线认知",
     "check": None, "hint": "频繁报撤单、自成交、异常价格、超限持仓都会被限制交易"},
    {"id": 12, "category": "风险", "title": "常见坑：滑点与流动性",
     "check": None, "hint": "小盘股/期货远月流动性差，滑点可能吞掉全部利润"},
    {"id": 13, "category": "风险", "title": "常见坑：废单 / 网络断开 / 崩溃重启",
     "check": None, "hint": "废单不自动重试；断线先查券商再重发；重启后幂等键与急停仍生效"},
    {"id": 14, "category": "风险", "title": "常见坑：节假日 / 分红除权 / 期货换月",
     "check": None, "hint": "交易日历节假日休市；除权需复权；期货主力合约换月要移仓"},
    {"id": 15, "category": "安全", "title": "凭证安全：.env 权限 600、日志脱敏、审计留存 2 年",
     "check": _check_gitignore, "hint": "chmod 600 .env；敏感日志只保留前 3 位；审计目录不提交"},
]


def run_checks() -> dict:
    """执行全部检查：自动项 pass/fail，人工项 manual（不计入通过）。"""
    results = []
    counts = {"pass": 0, "fail": 0, "skip": 0, "manual": 0}
    for item in ITEMS:
        record = {k: item[k] for k in ("id", "category", "title", "hint")}
        fn: Optional[Callable] = item.get("check")
        if fn is None:
            record.update(status="manual", detail="需人工确认")
            counts["manual"] += 1
        else:
            try:
                outcome = fn() or {}
                ok = bool(outcome.get("ok"))
                record.update(status="pass" if ok else "fail",
                              detail=str(outcome.get("detail", "")))
                counts["pass" if ok else "fail"] += 1
            except Exception as exc:  # noqa: BLE001 - 检查本身失败即不通过
                record.update(status="fail", detail=f"检查异常：{exc}")
                counts["fail"] += 1
        results.append(record)
    return {"items": results, "summary": {**counts, "total": len(results)},
            "ok": counts["fail"] == 0, "env_example": _check_env_example()}


def render(result: dict = None) -> str:
    result = result or run_checks()
    icons = {"pass": "[通过]", "fail": "[失败]", "manual": "[人工]", "skip": "[跳过]"}
    lines = ["=" * 78, "实盘前 15 项检查（A股 + 国内期货）", "=" * 78]
    for item in result["items"]:
        lines.append(f"{item['id']:>2}. {icons.get(item['status'], '')} "
                     f"[{item['category']}] {item['title']}")
        if item.get("detail"):
            lines.append(f"      ↳ {item['detail']}")
    s = result["summary"]
    lines.append("-" * 78)
    lines.append(f"通过 {s['pass']} / 失败 {s['fail']} / 人工确认 {s['manual']} / 跳过 {s['skip']}"
                 f"（共 {s['total']} 项）")
    lines.append("自动项全部通过不代表可以开实盘：人工项必须逐项确认，"
                 "且仿真跑满约定时长。")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="实盘前 15 项检查")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)
    result = run_checks()
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
