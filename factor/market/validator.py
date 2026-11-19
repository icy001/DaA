"""第三方策略静态安全校验器（第 5 步 5.9.12）。

导入第三方策略前做**纯静态扫描**（不执行任何代码）：
  * 直接网络请求：requests / urllib / akshare / tushare / socket → 直接拦截；
  * 文件系统删除：os.remove / os.unlink / shutil.rmtree / Path.unlink → 直接拦截；
  * 未来函数可疑写法：shift(-n)、iloc[i+n]、lookahead、future_* 等；
  * 过拟合迹象：meta.params 数量或函数默认参数 > 12、夏普声明 > 5；
  * 语法错误（无法解析）也会提示。

返回::

    {"risk_score": 0-100, "level": "low"/"medium"/"high",
     "warnings": ["..."], "blocked": bool}

`blocked=True` 只用于「删除文件 / 网络请求」这类危险操作；其它问题只给风险分。
"""
from __future__ import annotations

import ast
import logging
import re
from pathlib import Path
from typing import Dict, List, Tuple

__all__ = ["validate_strategy_file"]

logger = logging.getLogger(__name__)

# (说明, 正则, 风险分, 是否直接拦截)
_NETWORK_RULES: List[Tuple[str, str]] = [
    ("检测到网络请求 requests", r"\brequests\s*\.\s*(?:get|post|put|delete|head|patch|Session)\b"),
    ("检测到网络请求 urllib/httpx/aiohttp", r"\b(?:urllib3?|httpx|aiohttp)\b"),
    ("检测到行情/数据接口 akshare", r"\bakshare\b"),
    ("检测到行情/数据接口 tushare", r"\btushare\b"),
    ("检测到原始 socket 网络调用", r"\bsocket\s*\."),
]

_DELETE_RULES: List[Tuple[str, str]] = [
    ("检测到删除文件 os.remove/os.unlink/os.rmdir",
     r"\bos\s*\.\s*(?:remove|unlink|rmdir)\b"),
    ("检测到递归删除目录 shutil.rmtree", r"\bshutil\s*\.\s*rmtree\b"),
    ("检测到 Path.unlink/Path.rmdir", r"\.(?:unlink|rmdir)\s*\("),
]

_FUTURE_RULES: List[Tuple[str, str]] = [
    ("检测到未来函数写法 .shift(-n)", r"\.shift\s*\(\s*-"),
    ("检测到未来函数写法 .iloc[i + n]", r"\.iloc\s*\[[^\]]*\+\s*\d"),
    ("检测到 lookahead/future_* 可疑引用", r"\b(?:lookahead|future_[A-Za-z_]+|shift_neg)\b"),
]


def _read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def _scan_meta_params(tree: ast.AST) -> int:
    """统计类属性 meta 中 params 字典的键数量（取最大值）。"""
    counts: List[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == "meta" for t in stmt.targets):
                continue
            if not isinstance(stmt.value, ast.Dict):
                continue
            for key, value in zip(stmt.value.keys, stmt.value.values):
                if isinstance(key, ast.Constant) and key.value == "params" \
                        and isinstance(value, ast.Dict):
                    counts.append(len(value.keys))
    return max(counts) if counts else 0


def _max_function_defaults(tree: ast.AST) -> int:
    """统计函数默认参数个数（不含 self）。"""
    maximum = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        kw_defaults = [x for x in node.args.kw_defaults if x is not None]
        maximum = max(maximum, len(node.args.defaults) + len(kw_defaults))
    return maximum


def _sharpe_warnings(text: str) -> List[str]:
    warnings: List[str] = []
    seen = set()
    pattern = re.compile(r"(?:sharpe|夏普)[^\n]{0,40}?([0-9]+(?:\.[0-9]+)?)", re.I)
    for match in pattern.finditer(text):
        value = float(match.group(1))
        if value > 5:
            key = round(value, 4)
            if key in seen:
                continue
            seen.add(key)
            warnings.append(f"可疑高夏普声明 {value:g}（>5 通常意味着过拟合或未来函数）")
    return warnings


def validate_strategy_file(path) -> Dict:
    """静态扫描一个第三方策略文件，返回风险评分与警告（不执行代码）。"""
    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise FileNotFoundError(f"策略文件不存在：{file_path}")

    text = _read_text(file_path)
    warnings: List[str] = []
    score = 0
    blocked = False

    # 1) 网络请求 / 删除文件：直接拦截
    for rule in _NETWORK_RULES:
        message, pattern = rule
        if re.search(pattern, text, re.I):
            warnings.append(message)
            score += 45
            blocked = True
    for message, pattern in _DELETE_RULES:
        if re.search(pattern, text, re.I):
            warnings.append(message)
            score += 50
            blocked = True

    # 2) 未来函数可疑写法
    future_hits = 0
    for message, pattern in _FUTURE_RULES:
        if re.search(pattern, text, re.I):
            warnings.append(message)
            score += 15
            future_hits += 1
            if future_hits >= 3:
                break

    # 3) 过拟合：参数过多 / 语法错误
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        warnings.append(f"语法错误，无法解析：{exc}")
        score += 10
        tree = None
    if tree is not None:
        meta_params = _scan_meta_params(tree)
        if meta_params > 12:
            warnings.append(f"meta.params 参数过多（{meta_params} 个 > 12），疑似过拟合")
            score += 15
        defaults = _max_function_defaults(tree)
        if defaults > 12:
            warnings.append(f"函数默认参数过多（{defaults} 个 > 12），疑似过拟合")
            score += 15

    # 4) 可疑高夏普声明
    sharpe_messages = _sharpe_warnings(text)
    for message in sharpe_messages:
        warnings.append(message)
        score += 10

    score = int(min(100, score if not blocked else max(score, 70)))
    if blocked or score >= 60:
        level = "high"
    elif score >= 30:
        level = "medium"
    else:
        level = "low"

    return {
        "risk_score": score,
        "level": level,
        "warnings": warnings,
        "blocked": blocked,
    }
