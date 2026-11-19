"""公开策略源浏览器（第 5 步 5.9.12）。

只维护一份**离线索引**：策略名称、来源、原站链接、简介、标签、star 数、更新时间。
`search_strategy(keyword)` 按中英文关键词（大小写不敏感）过滤，方便用户找到
感兴趣的策略后**自己点链接去原站查看**。

【版权说明】
本模块不抓取、不下载、不缓存任何策略源码，只做链接索引；
策略代码的版权归原作者所有，使用前请遵守原站协议与开源许可证。
"""
from __future__ import annotations

from typing import Dict, List

__all__ = ["search_strategy", "list_sources"]

# 公开策略源清单（source / 主页 / 说明）
_SOURCES: List[Dict] = [
    {"source": "GitHub", "url": "https://github.com/topics/quantitative-trading",
     "description": "GitHub 量化交易主题仓库（含 Alpha 因子、回测框架、机器学习策略）"},
    {"source": "聚宽社区", "url": "https://www.joinquant.com/community",
     "description": "聚宽社区公开策略与研究帖（查看代码需登录聚宽账号）"},
    {"source": "米筐", "url": "https://www.ricequant.com/community",
     "description": "米筐社区公开策略（需登录米筐账号查看完整代码）"},
    {"source": "QuantConnect", "url": "https://www.quantconnect.com/strategies",
     "description": "QuantConnect 海外公开策略库（英文，支持多市场回测）"},
    {"source": "vnpy", "url": "https://www.vnpy.com/",
     "description": "vnpy 官方及社区策略示例（CTA 趋势、价差、网格等）"},
]

# 内置索引条目：name / source / url / description / tags / stars / updated
_INDEX: List[Dict] = [
    {
        "name": "qlib",
        "source": "GitHub",
        "url": "https://github.com/microsoft/qlib",
        "description": "微软开源 AI 量化平台，内置 Alpha158/Alpha360 因子与 LightGBM/MLP 模型示例",
        "tags": ["量化平台", "机器学习", "alpha158", "alpha360", "ai"],
        "stars": 22000,
        "updated": "2026-09",
    },
    {
        "name": "vnpy",
        "source": "GitHub",
        "url": "https://github.com/vnpy/vnpy",
        "description": "国内主流 Python 量化交易平台，含 CTA 策略模板与事件驱动引擎",
        "tags": ["cta", "趋势", "事件驱动", "期货", "trading"],
        "stars": 26000,
        "updated": "2026-10",
    },
    {
        "name": "backtrader",
        "source": "GitHub",
        "url": "https://github.com/mementum/backtrader",
        "description": "经典 Python 回测框架，策略以 next() 逐 bar 编写，示例覆盖均线/海龟等",
        "tags": ["回测框架", "双均线", "海龟", "backtest", "next"],
        "stars": 15000,
        "updated": "2026-06",
    },
    {
        "name": "freqtrade",
        "source": "GitHub",
        "url": "https://github.com/freqtrade/freqtrade",
        "description": "开源加密货币交易机器人，内置双均线、网格、机器学习策略示例",
        "tags": ["crypto", "grid", "双均线", "machine-learning", "bot"],
        "stars": 32000,
        "updated": "2026-10",
    },
    {
        "name": "rqalpha",
        "source": "GitHub",
        "url": "https://github.com/ricequant/rqalpha",
        "description": "米筐开源回测引擎，支持股票/期货多品种与事件驱动策略",
        "tags": ["回测引擎", "多因子", "股票", "期货"],
        "stars": 5500,
        "updated": "2026-05",
    },
    {
        "name": "QUANTAXIS",
        "source": "GitHub",
        "url": "https://github.com/QUANTAXIS/QUANTAXIS",
        "description": "量化数据/回测/交易一体化框架，含多因子与 CTA 示例",
        "tags": ["多因子", "回测", "cta", "数据平台"],
        "stars": 8500,
        "updated": "2026-08",
    },
    {
        "name": "alphalens",
        "source": "GitHub",
        "url": "https://github.com/quantopian/alphalens",
        "description": "因子绩效分析工具，IC/分层收益/换手率分析（研究参考实现）",
        "tags": ["因子分析", "ic", "分层回测", "alpha"],
        "stars": 4800,
        "updated": "2026-03",
    },
    {
        "name": "聚宽-双均线策略",
        "source": "聚宽社区",
        "url": "https://www.joinquant.com/community",
        "description": "聚宽社区经典双均线交叉示例（initialize + handle_data 结构）",
        "tags": ["双均线", "均线", "趋势", "入门", "joinquant"],
        "stars": 0,
        "updated": "2026-07",
    },
    {
        "name": "聚宽-小市值轮动",
        "source": "聚宽社区",
        "url": "https://www.joinquant.com/community",
        "description": "小市值因子轮动选股教程，含调仓与止损止盈框架",
        "tags": ["小市值", "轮动", "多因子", "选股"],
        "stars": 0,
        "updated": "2026-08",
    },
    {
        "name": "聚宽-机器学习选股",
        "source": "聚宽社区",
        "url": "https://www.joinquant.com/community",
        "description": "用 LightGBM/XGBoost 做横截面收益预测的公开教程与策略骨架",
        "tags": ["机器学习", "选股", "lightgbm", "xgboost", "预测"],
        "stars": 0,
        "updated": "2026-09",
    },
    {
        "name": "米筐-多因子选股",
        "source": "米筐",
        "url": "https://www.ricequant.com/community",
        "description": "米筐社区多因子打分选股策略（含因子中性化与行业约束）",
        "tags": ["多因子", "选股", "行业中性", "ricequant"],
        "stars": 0,
        "updated": "2026-07",
    },
    {
        "name": "QuantConnect-双均线趋势",
        "source": "QuantConnect",
        "url": "https://www.quantconnect.com/strategies",
        "description": "英文双均线趋势跟随策略示例，支持美股/期货/外汇多市场",
        "tags": ["双均线", "moving-average", "trend", "双均线策略"],
        "stars": 0,
        "updated": "2026-06",
    },
    {
        "name": "QuantConnect-ML 预测策略",
        "source": "QuantConnect",
        "url": "https://www.quantconnect.com/strategies",
        "description": "基于机器学习分类器的择时与选股策略示例（英文）",
        "tags": ["machine-learning", "预测", "classification", "ai"],
        "stars": 0,
        "updated": "2026-09",
    },
    {
        "name": "vnpy-CTA 双均线策略",
        "source": "vnpy",
        "url": "https://www.vnpy.com/",
        "description": "vnpy CtaTemplate 结构的双均线策略示例，可直接接 CTA 引擎",
        "tags": ["cta", "双均线", "期货", "趋势", "CtaTemplate"],
        "stars": 0,
        "updated": "2026-08",
    },
    {
        "name": "vnpy-网格交易策略",
        "source": "vnpy",
        "url": "https://www.vnpy.com/",
        "description": "震荡市场网格交易示例，含挂单管理与风控",
        "tags": ["网格", "震荡", "grid", "cta"],
        "stars": 0,
        "updated": "2026-05",
    },
]


def search_strategy(keyword: str = "") -> List[dict]:
    """按关键词过滤内置策略索引（中英文、大小写不敏感）。

    关键词为空时返回全部条目。只返回本地索引，不发起任何网络请求。
    """
    kw = str(keyword or "").strip().casefold()
    if not kw:
        return [dict(item) for item in _INDEX]
    result: List[dict] = []
    for item in _INDEX:
        haystack = " ".join([
            str(item.get("name", "")),
            str(item.get("source", "")),
            str(item.get("url", "")),
            str(item.get("description", "")),
            " ".join(str(t) for t in item.get("tags", [])),
        ]).casefold()
        if kw in haystack:
            result.append(dict(item))
    return result


def list_sources() -> List[Dict]:
    """返回公开策略源清单（source / url / description）。"""
    return [dict(item) for item in _SOURCES]
