"""第三方策略导入器（第 5 步 5.9.12）。

用户把从公开策略市场下载的 `.py` 放到本地后，调用::

    import_strategy("~/Downloads/some_strategy.py")

本模块会：
  1. **只读取文本**，静态识别来源（backtrader / 聚宽 / Qlib / vnpy / 原生 BaseStrategy）；
  2. 把文件复制到 `strategies/imported/`（默认），不覆盖原文件；
  3. 非原生策略额外生成同名 yaml 配置，标注来源与「需人工核对」；
  4. 返回 {"path", "source", "yaml", "notes"}。

⚠️ 自动转换不能保证 100% 正确：第三方框架的对象模型、成交与风控语义都与本系统
不同，导入后必须逐行人工核对并跑通回测。本模块**不执行**任何第三方代码。
"""
from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional

__all__ = ["import_strategy", "detect_source"]

logger = logging.getLogger(__name__)

_REVIEW_NOTE = "自动转换不能保证 100% 正确，请逐行人工核对（尤其是下单、仓位与风控逻辑）后再回测。"

_HINTS: Dict[str, str] = {
    "backtrader": (
        "backtrader 的 next() 需改写成 on_bar(date, bar_dict)；"
        "self.buy()/self.sell() 需换成 self.buy(symbol, volume, price)；"
        "self.data.close[0] 等指标线需用 core/indicators 或 get_history() 重写。"
    ),
    "joinquant": (
        "聚宽的 initialize()/handle_data() 需改成 init()/on_bar()；"
        "g.security_universe 换成 params['symbols']；order_target_value 需换算成"
        "整手股数后调用 self.buy/self.sell；聚宽的按金额下单本系统不直接支持。"
    ),
    "qlib": (
        "Qlib 的 predict() 输出需要转成「日期×股票」打分，再在 on_bar 里做横截面选股；"
        "注意 Qlib 数据是 (instrument, datetime) MultiIndex，且代码格式通常为 SH600519。"
    ),
    "vnpy": (
        "vnpy 的 CtaTemplate/on_bar/on_tick 需改成本系统 BaseStrategy 接口；"
        "去掉引擎、合约、委托等对象，只保留信号逻辑并改用 self.buy/self.sell。"
    ),
    "unknown": (
        "未能识别第三方框架，文件已按原样复制；请手动改写成 BaseStrategy 子类"
        "（实现 init() 与 on_bar()）。"
    ),
}


def _read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def detect_source(code: str) -> str:
    """按代码特征识别来源，返回 native/backtrader/joinquant/qlib/vnpy/unknown。"""
    text = str(code or "")
    if re.search(r"BaseStrategy", text) and re.search(r"def\s+on_bar\s*\(", text):
        return "native"
    if re.search(r"\b(?:import|from)\s+backtrader\b", text) or re.search(r"def\s+next\s*\(\s*self", text):
        return "backtrader"
    if (re.search(r"\bdef\s+initialize\s*\(", text) and re.search(r"\bdef\s+handle_data\s*\(", text)) \
            or re.search(r"\b(?:from|import)\s+jqdata", text) or "jqdatasdk" in text:
        return "joinquant"
    if re.search(r"\b(?:from|import)\s+qlib\b", text) or re.search(r"\bdef\s+predict\s*\(", text):
        return "qlib"
    if "CtaTemplate" in text or re.search(r"\b(?:from|import)\s+vnpy\b", text):
        return "vnpy"
    return "unknown"


def import_strategy(path, target_dir: str = "strategies/imported") -> dict:
    """把本地第三方策略复制到 target_dir，并按来源生成配置骨架。

    返回 {"path": 复制后路径, "source": 来源, "yaml": 配置路径或 None, "notes": [说明]}。
    不执行第三方代码；原生 BaseStrategy 只复制、不生成 yaml。
    """
    src = Path(path).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"策略文件不存在：{src}")
    if src.suffix.lower() != ".py":
        raise ValueError(f"只支持 .py 策略文件，收到 {src.suffix}")

    code = _read_text(src)
    source = detect_source(code)
    notes: List[str] = []

    target = Path(target_dir).expanduser()
    if not target.is_absolute():
        target = (Path.cwd() / target).resolve()
    target.mkdir(parents=True, exist_ok=True)
    dst = target / src.name
    if dst.resolve() != src:
        shutil.copy2(src, dst)
        notes.append(f"已复制到 {dst}")
    else:
        notes.append(f"文件已位于目标目录，跳过复制：{dst}")

    yaml_path: Optional[Path] = None
    if source == "native":
        notes.append("识别为原生 BaseStrategy 子类，仅复制文件，未生成 yaml 配置。")
    else:
        import yaml

        yaml_path = target / f"{src.stem}.yaml"
        payload = {
            "strategy": src.stem,
            "source": source,
            "source_file": src.name,
            "params": {},
            "needs_manual_review": True,
            "notes": "自动转换不能保证 100% 正确，请人工核对后再用于回测/实盘。",
        }
        yaml_path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        notes.append(f"已生成配置骨架：{yaml_path}")
        notes.append(_HINTS.get(source, _HINTS["unknown"]))

    notes.append(_REVIEW_NOTE)
    logger.info("导入第三方策略 %s：来源=%s", src.name, source)
    return {
        "path": str(dst),
        "source": source,
        "yaml": str(yaml_path) if yaml_path else None,
        "notes": notes,
    }
