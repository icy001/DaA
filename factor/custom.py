"""自定义因子示例（第 5 步 5.9.16）。

一个因子 = 一个函数：输入 FactorData，输出「日期×股票」面板 DataFrame。
注册后即可用名称调用，与 Alpha101/191、付费因子完全平等：
    ['alpha001', 'my_momentum'] 混用，引擎一视同仁。

规范：
  * 必须向量化（不要逐股票 for 循环）；
  * 只负责「算分」，不要做去极值/标准化/中性化（交给 preprocess.py）；
  * 统一用 FactorData 提供的方法取数，禁止自己读原始数据；
  * 缺失值保持 NaN。
"""
from __future__ import annotations

import pandas as pd

from .base import FactorData, register_factor
from .expression import evaluate


@register_factor("my_momentum")
def my_momentum(data: FactorData) -> pd.DataFrame:
    """20 日动量：过去 20 个交易日收益率。"""
    return data.close.pct_change(20)


@register_factor("my_volume_price_div")
def my_volume_price_div(data: FactorData) -> pd.DataFrame:
    """量价背离：价格与成交量 10 日相关系数取负。"""
    return evaluate("-1 * ts_corr(close, volume, 10)", data)


@register_factor("my_turnover_reversal")
def my_turnover_reversal(data: FactorData) -> pd.DataFrame:
    """换手率反转：相对量能（量比）越高，得分越低。"""
    return evaluate("-1 * rank(volume / ts_mean(volume, 20))", data)


@register_factor("my_intraday_strength")
def my_intraday_strength(data: FactorData) -> pd.DataFrame:
    """日内强度：(close-low)/(high-low) 的 10 日均值。"""
    return evaluate("ts_mean((close - low) / (high - low), 10)", data)


# ==================== 自定义因子请写在这里 ====================
# TODO: 用 @register_factor("因子名") 注册你的因子，示例：
#
# @register_factor("my_new_factor")
# def my_new_factor(data: FactorData) -> pd.DataFrame:
#     """一句话说明因子逻辑。"""
#     return evaluate("rank(ts_delta(close, 5))", data)
#
# 或运行脚手架自动生成：
#     python tools/new_factor.py --name my_new_factor --desc "因子说明"
