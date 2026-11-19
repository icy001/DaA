"""公开策略市场索引（第 5 步 5.9.12）。

本包只做「索引 + 静态检查 + 本地导入」，不联网、不下载任何第三方代码。
版权原因：策略代码归原作者所有，用户需自行到原站阅读/下载后再用
`factor.market.importer` 导入本地副本。
"""
from __future__ import annotations

from .browser import list_sources, search_strategy
from .importer import import_strategy
from .validator import validate_strategy_file

__all__ = ["search_strategy", "list_sources", "import_strategy",
           "validate_strategy_file"]
