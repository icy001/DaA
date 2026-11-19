"""第 5 步：策略自动发现 / 注册 / 加载（core/strategy_loader.py）

`main.py` 按名字调用策略，不用改入口代码：
    from core.strategy_loader import discover, get, list_all
    cls = get("double_ma_cross")

规则：
  1. `discover()` 扫描 `strategies/` 下所有 `.py`，找出所有 `BaseStrategy` 子类并注册；
  2. 每个策略用类属性 `meta` 声明元信息（name/display_name/markets/periods/params/...）；
  3. 单个文件语法错误 / 缺 `on_bar` / 缺 `meta.name` 时**不崩溃**，列入不可用清单并打印原因；
  4. 同名策略以「先发现者」为准，重复的进不可用清单，避免静默覆盖。
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Type

import config
from core.strategy import BaseStrategy
from core.utils import setup_logger

__all__ = ["StrategyRegistry", "discover", "get", "list_all", "unavailable",
           "load_class_from_file"]

STRATEGY_DIR = config.BASE_DIR / "strategies"
_logger: Optional[logging.Logger] = None


def _logger_of() -> logging.Logger:
    global _logger
    if _logger is None:
        _logger = setup_logger("strategy_loader", config.LOG_DIR / "strategy_loader.log")
    return _logger


class StrategyRegistry:
    """策略注册表：name → 策略类。"""

    def __init__(self, directory: Path = None):
        self.directory = Path(directory or STRATEGY_DIR)
        self._registry: Dict[str, Type[BaseStrategy]] = {}
        self._unavailable: List[dict] = []
        self._loaded = False

    # ---------- 发现 ----------

    def discover(self, force: bool = False) -> "StrategyRegistry":
        if self._loaded and not force:
            return self
        self._registry.clear()
        self._unavailable.clear()
        if not self.directory.exists():
            _logger_of().warning("策略目录不存在：%s", self.directory)
            self._loaded = True
            return self
        for path in sorted(self.directory.glob("*.py")):
            if path.name.startswith("_"):
                continue
            self._load_file(path)
        self._loaded = True
        _logger_of().info("策略发现完成：可用 %d 个，不可用 %d 个",
                          len(self._registry), len(self._unavailable))
        return self

    def _load_file(self, path: Path) -> None:
        try:
            classes = _classes_in_file(path)
        except Exception as exc:  # 语法错误 / 导入期异常：隔离，不影响其他策略
            self._unavailable.append({"file": path.name, "class": "", "reason":
                                      f"{type(exc).__name__}: {exc}"})
            _logger_of().warning("策略文件 %s 加载失败，已隔离：%s", path.name, exc)
            return

        if not classes:
            self._unavailable.append({"file": path.name, "class": "",
                                      "reason": "未找到 BaseStrategy 子类"})
            return
        for cls in classes:
            name = str((getattr(cls, "meta", {}) or {}).get("name") or "").strip()
            reason = self._validate(cls, name)
            if reason:
                self._unavailable.append({"file": path.name,
                                          "class": cls.__name__, "reason": reason})
                _logger_of().warning("策略 %s（%s）不可用：%s", cls.__name__,
                                     path.name, reason)
                continue
            if name in self._registry:
                self._unavailable.append({
                    "file": path.name, "class": cls.__name__,
                    "reason": f"策略名 {name!r} 重复，已保留先发现的 "
                              f"{self._registry[name].__name__}"})
                continue
            self._registry[name] = cls

    @staticmethod
    def _validate(cls: Type[BaseStrategy], name: str) -> str:
        if not name:
            return "meta['name'] 为空（命令行无法按名字调用）"
        if getattr(cls, "on_bar", None) is BaseStrategy.on_bar:
            return "未实现 on_bar()"
        periods = (getattr(cls, "meta", {}) or {}).get("periods")
        if periods:
            bad = [p for p in periods if p not in config.SUPPORTED_PERIODS]
            if bad:
                return f"meta['periods'] 含非法周期 {bad}，可选 {config.SUPPORTED_PERIODS}"
        return ""

    # ---------- 查询 ----------

    def get(self, name: str) -> Type[BaseStrategy]:
        self.discover()
        key = str(name).strip()
        if key not in self._registry:
            available = ", ".join(sorted(self._registry)) or "（无）"
            raise KeyError(f"策略 {key!r} 未注册；可用策略：{available}")
        return self._registry[key]

    def list_all(self) -> List[dict]:
        self.discover()
        rows = []
        for name, cls in sorted(self._registry.items()):
            meta = dict(getattr(cls, "meta", {}) or {})
            rows.append({
                "name": name,
                "display_name": meta.get("display_name", name),
                "version": meta.get("version", ""),
                "description": meta.get("description", ""),
                "markets": list(meta.get("markets") or []),
                "periods": list(meta.get("periods") or []),
                "params": dict(meta.get("params") or {}),
                "class": cls.__name__,
            })
        return rows

    def unavailable(self) -> List[dict]:
        self.discover()
        return list(self._unavailable)


def _classes_in_file(path: Path) -> List[Type[BaseStrategy]]:
    """导入单个策略文件，返回其中「本文件定义」的 BaseStrategy 子类。"""
    module_name = f"quant_strategy_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法为 {path} 创建 import spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    found = []
    for obj in vars(module).values():
        if (isinstance(obj, type) and issubclass(obj, BaseStrategy)
                and obj is not BaseStrategy and obj.__module__ == module_name):
            found.append(obj)
    return found


_registry: Optional[StrategyRegistry] = None


def _default() -> StrategyRegistry:
    global _registry
    if _registry is None:
        _registry = StrategyRegistry()
    return _registry


def discover(directory: Path = None, force: bool = False) -> StrategyRegistry:
    if directory is not None:
        return StrategyRegistry(directory).discover(force=force)
    return _default().discover(force=force)


def get(name: str) -> Type[BaseStrategy]:
    return _default().get(name)


def list_all() -> List[dict]:
    return _default().list_all()


def unavailable() -> List[dict]:
    return _default().unavailable()


def load_class_from_file(path) -> Type[BaseStrategy]:
    """按文件路径直接加载策略类（第三方导入 / 上线检查用）。"""
    classes = _classes_in_file(Path(path))
    if not classes:
        raise ValueError(f"{path} 中没有 BaseStrategy 子类")
    return classes[0]
