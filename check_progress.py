"""搭建进度看板

运行：python check_progress.py
读取 progress.json，打印各步骤状态、整体完成百分比与下一步建议。
"""
from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROGRESS_FILE = ROOT / "progress.json"

STATUS_ICON = {
    "已完成": "✅",
    "进行中": "🔄",
    "未开始": "⬜",
    "有问题": "❌",
}


def _width(text: str) -> int:
    """按终端显示宽度计算（中文按 2 列）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _width(text))


def _load() -> dict:
    if not PROGRESS_FILE.exists():
        print(f"未找到 {PROGRESS_FILE}，请先完成第 0 步。")
        sys.exit(1)
    with PROGRESS_FILE.open(encoding="utf-8") as fh:
        return json.load(fh)


def _print_dashboard(data: dict) -> None:
    steps = data.get("steps", [])
    total = len(steps) or 1
    done = sum(1 for s in steps if s.get("status") == "已完成")
    problem = [s for s in steps if s.get("status") == "有问题"]

    print("=" * 78)
    print(f"  {data.get('project', '量化交易系统')}  {data.get('version', '')}  搭建进度看板")
    print(f"  最近更新：{data.get('last_update') or '-'}")
    print("=" * 78)

    header = f"  {_pad('步骤', 6)}{_pad('状态', 12)}{_pad('名称', 60)}完成时间"
    print(header)
    print("  " + "-" * 74)
    for step in steps:
        status = step.get("status", "未开始")
        icon = STATUS_ICON.get(status, "⬜")
        sid = str(step.get("id", ""))
        name = step.get("name", "")
        done_at = step.get("done") or "-"
        print(f"  {_pad(sid, 6)}{_pad(icon + status, 12)}{_pad(name, 60)}{done_at}")
        note = step.get("note")
        if note and status in ("有问题", "已完成"):
            print(f"        备注：{note}")

    percent = done / total * 100
    bar_len = 40
    filled = int(bar_len * done / total)
    bar = "█" * filled + "░" * (bar_len - filled)
    print("\n  " + bar + f"  {percent:.1f}%（{done}/{total}）")

    issues = data.get("issues") or []
    if problem or issues:
        print("\n  ❌ 待处理问题：")
        for step in problem:
            print(f"    - 第 {step.get('id')} 步 {step.get('name')}：{step.get('note') or '未填写原因'}")
        for issue in issues:
            print(f"    - {issue}")
    else:
        print("\n  ✅ 当前无遗留问题")

    next_id = data.get("next_step")
    next_step = next((s for s in steps if s.get("id") == next_id), None)
    if next_step is None:
        print("\n  🎉 所有步骤已完成")
        return
    print("\n  下一步建议：")
    print(f"    第 {next_step['id']} 步 · {next_step['name']}（当前状态：{next_step.get('status')}）")
    print("    从《Trae多市场量化系统搭建指令集》复制以下整段继续：")
    print(f"    ===== 第 {next_step['id']} 步：{next_step['name']} =====")


def main() -> int:
    _print_dashboard(_load())
    return 0


if __name__ == "__main__":
    sys.exit(main())
