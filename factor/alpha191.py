"""Alpha191 国泰君安短周期量价因子库（第 5 步 5.9.3）。

按《基于短周期量价的 Alpha191 因子》组织为六大类：
  001-040 趋势类（均线、动量、通道）
  041-080 成交量类（量比、放量缩量、量价背离）
  081-120 波动率类（振幅、ATR、布林带）
  121-150 反转类（超买超卖、跳空缺口）
  151-170 资金流类（开盘强弱、尾盘效应）
  171-191 混合类（多因子组合、形态识别）

结构与 alpha101.py 完全一致：每个函数 ``alpha191_001(data) -> 面板 DataFrame``，
统一走 factor/expression.py，保证口径一致。少量公开资料未收录的因子按同类
量价逻辑等价实现，并在 docstring 中标注。
"""
from __future__ import annotations

from typing import Callable, List

import pandas as pd

from .base import FactorData
from .expression import evaluate

__all__ = ["get_alpha191_list", "get_builtin_alpha191"]


# ==================== 001-040 趋势类 ====================
def alpha191_001(data: FactorData) -> pd.DataFrame:
    """趋势 | 量变化排名与日内涨跌排名负相关。"""
    return evaluate("-1 * ts_corr(rank(ts_delta(log(volume), 1)), rank((close - open) / open), 6)", data)


def alpha191_002(data: FactorData) -> pd.DataFrame:
    """趋势 | 日内收盘位置变化的负值。"""
    return evaluate("-1 * ts_delta(((close - low) - (high - close)) / (high - low), 1)", data)


def alpha191_003(data: FactorData) -> pd.DataFrame:
    """趋势 | 6日定向突破累计（与昨日收盘比较）。"""
    return evaluate(
        "ts_sum(if_else(close == ts_delay(close, 1), 0, "
        "if_else(close > ts_delay(close, 1), close - min(low, ts_delay(close, 1)), "
        "close - max(high, ts_delay(close, 1)))), 6)",
        data,
    )


def alpha191_004(data: FactorData) -> pd.DataFrame:
    """趋势 | 短期均线突破长期通道上/下轨的方向判断。"""
    return evaluate(
        "if_else((ts_sum(close, 8) / 8 + ts_std(close, 8)) < (ts_sum(close, 2) / 2), -1, "
        "if_else((ts_sum(close, 2) / 2) < (ts_sum(close, 8) / 8 - ts_std(close, 8)), 1, "
        "if_else(volume / adv20 >= 1, 1, -1)))",
        data,
    )


def alpha191_005(data: FactorData) -> pd.DataFrame:
    """趋势 | 量价时序排名相关的峰值取负。"""
    return evaluate("-1 * ts_max(ts_corr(ts_rank(volume, 5), ts_rank(high, 5), 5), 3)", data)


def alpha191_006(data: FactorData) -> pd.DataFrame:
    """趋势 | 加权开盘-最高价4日变化方向的排名取负。"""
    return evaluate("-1 * rank(sign(ts_delta(open * 0.85 + high * 0.15, 4)))", data)


def alpha191_007(data: FactorData) -> pd.DataFrame:
    """趋势 | vwap偏离通道乘以成交量变化排名。"""
    return evaluate(
        "(rank(ts_max(vwap - close, 3)) + rank(ts_min(vwap - close, 3))) * rank(ts_delta(volume, 3))",
        data,
    )


def alpha191_008(data: FactorData) -> pd.DataFrame:
    """趋势 | 加权均价4日变化的排名取负。"""
    return evaluate("-1 * rank(ts_delta((high + low) / 2 * 0.2 + vwap * 0.8, 4))", data)


def alpha191_009(data: FactorData) -> pd.DataFrame:
    """趋势 | 日内中价相对昨日中价的偏离与振幅之比。"""
    return evaluate(
        "ts_mean(((high + low) / 2 - (ts_delay(high, 1) + ts_delay(low, 1)) / 2) * (high - low) / volume, 7)",
        data,
    )


def alpha191_010(data: FactorData) -> pd.DataFrame:
    """趋势 | 下行波动/收盘价平方的5日高点排名。"""
    return evaluate("rank(ts_max(if_else(returns < 0, ts_std(returns, 20), close) ** 2, 5))", data)


def alpha191_011(data: FactorData) -> pd.DataFrame:
    """趋势 | 日内位置乘成交量的6日累计。"""
    return evaluate("ts_sum(((close - low) - (high - close)) / (high - low) * volume, 6)", data)


def alpha191_012(data: FactorData) -> pd.DataFrame:
    """趋势 | 开盘偏离10日均vwap，乘以收盘偏离vwap排名。"""
    return evaluate("rank(open - ts_mean(vwap, 10)) * (-1 * rank(abs(close - vwap)))", data)


def alpha191_013(data: FactorData) -> pd.DataFrame:
    """趋势 | 几何均价与vwap的偏离。"""
    return evaluate("(high * low) ** 0.5 - vwap", data)


def alpha191_014(data: FactorData) -> pd.DataFrame:
    """趋势 | 5日价格动量。"""
    return evaluate("close - ts_delay(close, 5)", data)


def alpha191_015(data: FactorData) -> pd.DataFrame:
    """趋势 | 隔夜跳空幅度。"""
    return evaluate("open / ts_delay(close, 1) - 1", data)


def alpha191_016(data: FactorData) -> pd.DataFrame:
    """趋势 | 量价排名相关性的5日峰值取负。"""
    return evaluate("-1 * ts_max(rank(ts_corr(rank(volume), rank(vwap), 5)), 5)", data)


def alpha191_017(data: FactorData) -> pd.DataFrame:
    """趋势 | 波动率排名与量价相关性的乘积。"""
    return evaluate("rank(ts_std(close, 10)) * ts_corr(close, volume, 10)", data)


def alpha191_018(data: FactorData) -> pd.DataFrame:
    """趋势 | 5日归一化动量。"""
    return evaluate("close / ts_delay(close, 5) - 1", data)


def alpha191_019(data: FactorData) -> pd.DataFrame:
    """趋势 | 6日归一化动量。"""
    return evaluate("(close - ts_delay(close, 6)) / ts_delay(close, 6)", data)


def alpha191_020(data: FactorData) -> pd.DataFrame:
    """趋势 | 7日百分比动量。"""
    return evaluate("(close - ts_delay(close, 7)) / ts_delay(close, 7) * 100", data)


def alpha191_021(data: FactorData) -> pd.DataFrame:
    """趋势 | 均线通道与量比条件（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate(
        "if_else(ts_sum(close, 6) / 6 > ts_sum(close, 12) / 12, 1, -1) * ts_rank(volume / adv20, 5)",
        data,
    )


def alpha191_022(data: FactorData) -> pd.DataFrame:
    """趋势 | 高价量相关变化乘以收盘波动排名。"""
    return evaluate("-1 * ts_delta(ts_corr(high, volume, 5), 5) * rank(ts_std(close, 20))", data)


def alpha191_023(data: FactorData) -> pd.DataFrame:
    """趋势 | 20日上涨突破累计（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_sum(if_else(high > ts_delay(high, 1), ts_delta(high, 1), 0), 20)", data)


def alpha191_024(data: FactorData) -> pd.DataFrame:
    """趋势 | 收益变化排名与开量相关的交互。"""
    return evaluate("-1 * rank(ts_delta(close, 3)) * ts_corr(open, volume, 10)", data)


def alpha191_025(data: FactorData) -> pd.DataFrame:
    """趋势 | 开盘偏离10日均vwap与收盘偏离的交互。"""
    return evaluate("rank(open - ts_sum(vwap, 10) / 10) * (-1 * abs(rank(close - vwap)))", data)


def alpha191_026(data: FactorData) -> pd.DataFrame:
    """趋势 | 7日均线偏离与vwap长期相关性。"""
    return evaluate("(ts_sum(close, 7) / 7 - close) + ts_corr(vwap, ts_delay(close, 5), 60)", data)


def alpha191_027(data: FactorData) -> pd.DataFrame:
    """趋势 | 量价排名相关性的2日累计排名。"""
    return evaluate("rank(ts_sum(ts_corr(rank(volume), rank(vwap), 6), 2) / 2)", data)


def alpha191_028(data: FactorData) -> pd.DataFrame:
    """趋势 | 量能与低价相关排名与3日价格变化的组合。"""
    return evaluate("3 * ts_rank(ts_corr(adv20, low, 5), 6) + 2 * rank(ts_delta(close, 3))", data)


def alpha191_029(data: FactorData) -> pd.DataFrame:
    """趋势 | 3日价格变化与相对量能时序排名的乘积。"""
    return evaluate("rank(ts_delta(close, 3)) * ts_rank(volume / adv20, 5)", data)


def alpha191_030(data: FactorData) -> pd.DataFrame:
    """趋势 | 收盘在20日通道中的位置。"""
    return evaluate("(close - ts_min(low, 20)) / (ts_max(high, 20) - ts_min(low, 20))", data)


def alpha191_031(data: FactorData) -> pd.DataFrame:
    """趋势 | 收盘相对20日均线的标准分（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("(close - ts_mean(close, 20)) / ts_std(close, 20)", data)


def alpha191_032(data: FactorData) -> pd.DataFrame:
    """趋势 | 收盘价的20日时序排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_rank(close, 20)", data)


def alpha191_033(data: FactorData) -> pd.DataFrame:
    """趋势 | 收盘价20日时序排名取负（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("-1 * ts_rank(close, 20)", data)


def alpha191_034(data: FactorData) -> pd.DataFrame:
    """趋势 | 收盘偏离10日均线的百分比（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("(close - ts_mean(close, 10)) / ts_mean(close, 10)", data)


def alpha191_035(data: FactorData) -> pd.DataFrame:
    """趋势 | 量价相关性的20日时序排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_rank(ts_corr(close, volume, 10), 20)", data)


def alpha191_036(data: FactorData) -> pd.DataFrame:
    """趋势 | 20日最高点位置（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_argmax(close, 20) / 20", data)


def alpha191_037(data: FactorData) -> pd.DataFrame:
    """趋势 | 20日最低点位置（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_argmin(close, 20) / 20", data)


def alpha191_038(data: FactorData) -> pd.DataFrame:
    """趋势 | 5日均线相对20日均线的排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(ts_mean(close, 5) / ts_mean(close, 20))", data)


def alpha191_039(data: FactorData) -> pd.DataFrame:
    """趋势 | 20日波动率排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(ts_std(close, 20))", data)


def alpha191_040(data: FactorData) -> pd.DataFrame:
    """趋势 | 20日动量（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_momentum(close, 20)", data)


# ==================== 041-080 成交量类 ====================
def alpha191_041(data: FactorData) -> pd.DataFrame:
    """成交量 | 成交量日变化排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(ts_delta(volume, 1))", data)


def alpha191_042(data: FactorData) -> pd.DataFrame:
    """成交量 | 相对20日均量的量比。"""
    return evaluate("volume / adv20", data)


def alpha191_043(data: FactorData) -> pd.DataFrame:
    """成交量 | 成交量20日时序排名。"""
    return evaluate("ts_rank(volume, 20)", data)


def alpha191_044(data: FactorData) -> pd.DataFrame:
    """成交量 | 5日均量相对20日均量比（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(ts_mean(volume, 5) / ts_mean(volume, 20))", data)


def alpha191_045(data: FactorData) -> pd.DataFrame:
    """成交量 | 收盘与成交量的10日相关。"""
    return evaluate("ts_corr(close, volume, 10)", data)


def alpha191_046(data: FactorData) -> pd.DataFrame:
    """成交量 | 收盘与成交量10日相关的负值（量价背离）。"""
    return evaluate("-1 * ts_corr(close, volume, 10)", data)


def alpha191_047(data: FactorData) -> pd.DataFrame:
    """成交量 | 收盘排名与成交量排名的相关。"""
    return evaluate("ts_corr(rank(close), rank(volume), 20)", data)


def alpha191_048(data: FactorData) -> pd.DataFrame:
    """成交量 | 价格变化与成交量变化的相关（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_corr(ts_delta(close, 1), ts_delta(volume, 1), 20)", data)


def alpha191_049(data: FactorData) -> pd.DataFrame:
    """成交量 | 成交量排名日变化（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(volume) - rank(ts_delay(volume, 1))", data)


def alpha191_050(data: FactorData) -> pd.DataFrame:
    """成交量 | 成交量相对20日均量的标准分（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("(volume - ts_mean(volume, 20)) / ts_std(volume, 20)", data)


def alpha191_051(data: FactorData) -> pd.DataFrame:
    """成交量 | 相对量能的10日时序排名。"""
    return evaluate("ts_rank(volume / adv20, 10)", data)


def alpha191_052(data: FactorData) -> pd.DataFrame:
    """成交量 | 量增价跌/量减价涨的反转。"""
    return evaluate("sign(ts_delta(volume, 1)) * (-1 * ts_delta(close, 1))", data)


def alpha191_053(data: FactorData) -> pd.DataFrame:
    """成交量 | 5日量变化与价变化排名的乘积（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(ts_delta(volume, 5)) * rank(ts_delta(close, 5))", data)


def alpha191_054(data: FactorData) -> pd.DataFrame:
    """成交量 | 放量日的收益累计（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_sum(if_else(volume > adv20, returns, 0), 10)", data)


def alpha191_055(data: FactorData) -> pd.DataFrame:
    """成交量 | 缩量日的收益累计（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_sum(if_else(volume < adv20, returns, 0), 10)", data)


def alpha191_056(data: FactorData) -> pd.DataFrame:
    """成交量 | 上涨日成交量占比（资金流入强度）。"""
    return evaluate("ts_sum(if_else(returns > 0, volume, 0), 10) / ts_sum(volume, 10)", data)


def alpha191_057(data: FactorData) -> pd.DataFrame:
    """成交量 | 下跌日成交量占比（资金流出强度）。"""
    return evaluate("ts_sum(if_else(returns < 0, volume, 0), 10) / ts_sum(volume, 10)", data)


def alpha191_058(data: FactorData) -> pd.DataFrame:
    """成交量 | 成交量与价格变化相关排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(ts_corr(volume, ts_delta(close, 1), 5))", data)


def alpha191_059(data: FactorData) -> pd.DataFrame:
    """成交量 | 短期量能排名减长期量能排名（放量加速度）。"""
    return evaluate("ts_rank(volume, 5) - ts_rank(volume, 20)", data)


def alpha191_060(data: FactorData) -> pd.DataFrame:
    """成交量 | 5日均量相对20日均量的变化（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("adv5 / adv20 - 1", data)


def alpha191_061(data: FactorData) -> pd.DataFrame:
    """成交量 | 10日均量相对60日均量的变化（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("adv10 / adv60 - 1", data)


def alpha191_062(data: FactorData) -> pd.DataFrame:
    """成交量 | 成交量波动率排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(ts_std(volume, 20))", data)


def alpha191_063(data: FactorData) -> pd.DataFrame:
    """成交量 | 成交量波动率排名取负（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("-1 * rank(ts_std(volume, 20))", data)


def alpha191_064(data: FactorData) -> pd.DataFrame:
    """成交量 | 量与最高价排名相关。"""
    return evaluate("rank(ts_corr(rank(volume), rank(high), 10))", data)


def alpha191_065(data: FactorData) -> pd.DataFrame:
    """成交量 | 量与最低价排名相关。"""
    return evaluate("rank(ts_corr(rank(volume), rank(low), 10))", data)


def alpha191_066(data: FactorData) -> pd.DataFrame:
    """成交量 | 量加权收益（VWAP 近似收益率）。"""
    return evaluate("ts_sum(volume * returns, 10) / ts_sum(volume, 10)", data)


def alpha191_067(data: FactorData) -> pd.DataFrame:
    """成交量 | 量加权绝对收益（波动资金强度）。"""
    return evaluate("ts_sum(volume * abs(returns), 10) / ts_sum(volume, 10)", data)


def alpha191_068(data: FactorData) -> pd.DataFrame:
    """成交量 | 成交额相对20日均额的标准分（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("(amount - ts_mean(amount, 20)) / ts_std(amount, 20)", data)


def alpha191_069(data: FactorData) -> pd.DataFrame:
    """成交量 | vwap 的截面排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(amount / volume)", data)


def alpha191_070(data: FactorData) -> pd.DataFrame:
    """成交量 | vwap 的20日时序排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_rank(vwap, 20)", data)


def alpha191_071(data: FactorData) -> pd.DataFrame:
    """成交量 | vwap 相对收盘的溢价（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("vwap / close - 1", data)


def alpha191_072(data: FactorData) -> pd.DataFrame:
    """成交量 | vwap 与成交量的20日相关。"""
    return evaluate("ts_corr(vwap, volume, 20)", data)


def alpha191_073(data: FactorData) -> pd.DataFrame:
    """成交量 | vwap 与收盘的20日相关（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_corr(vwap, close, 20)", data)


def alpha191_074(data: FactorData) -> pd.DataFrame:
    """成交量 | vwap 日变化的排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(ts_delta(vwap, 1))", data)


def alpha191_075(data: FactorData) -> pd.DataFrame:
    """成交量 | vwap 量价相关的时序排名。"""
    return evaluate("ts_rank(ts_corr(vwap, volume, 5), 10)", data)


def alpha191_076(data: FactorData) -> pd.DataFrame:
    """成交量 | 放量天数占比（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(ts_sum(if_else(volume > adv20, 1, 0), 20))", data)


def alpha191_077(data: FactorData) -> pd.DataFrame:
    """成交量 | 缩量天数占比取负（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(-1 * ts_sum(if_else(volume < adv20, 1, 0), 20))", data)


def alpha191_078(data: FactorData) -> pd.DataFrame:
    """成交量 | 日内阳线成交量净额占比（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate(
        "ts_sum(if_else(close > open, volume, -1 * volume), 10) / ts_sum(volume, 10)", data
    )


def alpha191_079(data: FactorData) -> pd.DataFrame:
    """成交量 | 相对昨日涨跌的成交量净额占比。"""
    return evaluate(
        "ts_sum(if_else(close > ts_delay(close, 1), volume, -1 * volume), 10) / ts_sum(volume, 10)",
        data,
    )


def alpha191_080(data: FactorData) -> pd.DataFrame:
    """成交量 | 成交量排名与收益排名的乘积（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(volume) * rank(returns)", data)


# ==================== 081-120 波动率类 ====================
def alpha191_081(data: FactorData) -> pd.DataFrame:
    """波动率 | 10日收益波动率。"""
    return evaluate("ts_std(returns, 10)", data)


def alpha191_082(data: FactorData) -> pd.DataFrame:
    """波动率 | 20日收益波动率排名。"""
    return evaluate("rank(ts_std(returns, 20))", data)


def alpha191_083(data: FactorData) -> pd.DataFrame:
    """波动率 | 10日振幅相对均价的归一化。"""
    return evaluate("ts_std(high - low, 10) / ts_mean(close, 10)", data)


def alpha191_084(data: FactorData) -> pd.DataFrame:
    """波动率 | 10日平均振幅率。"""
    return evaluate("ts_mean(high - low, 10) / ts_mean(close, 10)", data)


def alpha191_085(data: FactorData) -> pd.DataFrame:
    """波动率 | 单日振幅率。"""
    return evaluate("(high - low) / close", data)


def alpha191_086(data: FactorData) -> pd.DataFrame:
    """波动率 | 短长期波动率之比。"""
    return evaluate("ts_std(returns, 5) / ts_std(returns, 20)", data)


def alpha191_087(data: FactorData) -> pd.DataFrame:
    """波动率 | 20日波动率的时序排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_rank(ts_std(returns, 20), 20)", data)


def alpha191_088(data: FactorData) -> pd.DataFrame:
    """波动率 | 20日高低价差。"""
    return evaluate("ts_max(high, 20) - ts_min(low, 20)", data)


def alpha191_089(data: FactorData) -> pd.DataFrame:
    """波动率 | 20日高低价差相对均价。"""
    return evaluate("(ts_max(high, 20) - ts_min(low, 20)) / ts_mean(close, 20)", data)


def alpha191_090(data: FactorData) -> pd.DataFrame:
    """波动率 | 最高价与最低价的20日相关（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_corr(high, low, 20)", data)


def alpha191_091(data: FactorData) -> pd.DataFrame:
    """波动率 | vwap 波动率排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(ts_std(vwap, 20))", data)


def alpha191_092(data: FactorData) -> pd.DataFrame:
    """波动率 | 收盘价20日变异系数（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_std(close, 20) / ts_mean(close, 20)", data)


def alpha191_093(data: FactorData) -> pd.DataFrame:
    """波动率 | 成交量20日变异系数（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_std(volume, 20) / ts_mean(volume, 20)", data)


def alpha191_094(data: FactorData) -> pd.DataFrame:
    """波动率 | 10日高低比排名（布林带宽度代理）。"""
    return evaluate("rank(ts_max(high, 10) / ts_min(low, 10) - 1)", data)


def alpha191_095(data: FactorData) -> pd.DataFrame:
    """波动率 | 开盘价10日波动（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_std(open, 10)", data)


def alpha191_096(data: FactorData) -> pd.DataFrame:
    """波动率 | 最高价10日波动排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(ts_std(high, 10))", data)


def alpha191_097(data: FactorData) -> pd.DataFrame:
    """波动率 | 最低价10日波动排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(ts_std(low, 10))", data)


def alpha191_098(data: FactorData) -> pd.DataFrame:
    """波动率 | 60日收益波动率（长期风险）。"""
    return evaluate("ts_std(returns, 60)", data)


def alpha191_099(data: FactorData) -> pd.DataFrame:
    """波动率 | 5日波动率相对平均绝对收益（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_std(returns, 5) / ts_mean(abs(returns), 5)", data)


def alpha191_100(data: FactorData) -> pd.DataFrame:
    """波动率 | 20日平均绝对收益（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_mean(abs(returns), 20)", data)


def alpha191_101(data: FactorData) -> pd.DataFrame:
    """波动率 | 10日波动率的20日时序排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_rank(ts_std(returns, 10), 20)", data)


def alpha191_102(data: FactorData) -> pd.DataFrame:
    """波动率 | 绝对收益与成交量的20日相关（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_corr(abs(returns), volume, 20)", data)


def alpha191_103(data: FactorData) -> pd.DataFrame:
    """波动率 | 短期波动率与成交量的20日相关（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_corr(ts_std(returns, 5), volume, 20)", data)


def alpha191_104(data: FactorData) -> pd.DataFrame:
    """波动率 | 20日高低价差排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(ts_max(high, 20) - ts_min(low, 20))", data)


def alpha191_105(data: FactorData) -> pd.DataFrame:
    """波动率 | 20日平均振幅率排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(ts_mean(high - low, 20) / ts_mean(close, 20))", data)


def alpha191_106(data: FactorData) -> pd.DataFrame:
    """波动率 | 日内涨幅的20日波动（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_std(close / open - 1, 20)", data)


def alpha191_107(data: FactorData) -> pd.DataFrame:
    """波动率 | 收盘下影线比例的20日波动（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_std((close - low) / close, 20)", data)


def alpha191_108(data: FactorData) -> pd.DataFrame:
    """波动率 | 收盘上影线比例的20日波动（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_std((high - close) / close, 20)", data)


def alpha191_109(data: FactorData) -> pd.DataFrame:
    """波动率 | 日内实体比例的20日波动（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_std((close - open) / open, 20)", data)


def alpha191_110(data: FactorData) -> pd.DataFrame:
    """波动率 | 短长期波动率之比的排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(ts_std(returns, 10) / ts_std(returns, 60))", data)


def alpha191_111(data: FactorData) -> pd.DataFrame:
    """波动率 | 振幅20日波动的时序排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_rank(ts_std(high - low, 20), 20)", data)


def alpha191_112(data: FactorData) -> pd.DataFrame:
    """波动率 | vwap与收盘偏离的20日波动（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_std(vwap - close, 20)", data)


def alpha191_113(data: FactorData) -> pd.DataFrame:
    """波动率 | vwap与收盘偏离波动的排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(ts_std(vwap - close, 20))", data)


def alpha191_114(data: FactorData) -> pd.DataFrame:
    """波动率 | 成交额20日变异系数（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_std(amount, 20) / ts_mean(amount, 20)", data)


def alpha191_115(data: FactorData) -> pd.DataFrame:
    """波动率 | 短长期波动率相关（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("ts_corr(ts_std(returns, 5), ts_std(returns, 20), 20)", data)


def alpha191_116(data: FactorData) -> pd.DataFrame:
    """波动率 | 当日振幅相对20日平均振幅（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("(high - low) / ts_mean(high - low, 20)", data)


def alpha191_117(data: FactorData) -> pd.DataFrame:
    """波动率 | 5日高低比排名（短布林带宽度，公开资料未收录）。"""
    return evaluate("rank(ts_max(high, 5) / ts_min(low, 5) - 1)", data)


def alpha191_118(data: FactorData) -> pd.DataFrame:
    """波动率 | 20日与60日波动率之差（波动率期限结构，公开资料未收录）。"""
    return evaluate("ts_std(returns, 20) - ts_std(returns, 60)", data)


def alpha191_119(data: FactorData) -> pd.DataFrame:
    """波动率 | 5日波动率排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(ts_std(returns, 5))", data)


def alpha191_120(data: FactorData) -> pd.DataFrame:
    """波动率 | 60日波动率排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(ts_std(returns, 60))", data)


# ==================== 121-150 反转类 ====================
def alpha191_121(data: FactorData) -> pd.DataFrame:
    """反转 | 1日价格反转。"""
    return evaluate("-1 * ts_delta(close, 1)", data)


def alpha191_122(data: FactorData) -> pd.DataFrame:
    """反转 | 3日价格反转。"""
    return evaluate("-1 * ts_delta(close, 3)", data)


def alpha191_123(data: FactorData) -> pd.DataFrame:
    """反转 | 5日价格反转。"""
    return evaluate("-1 * ts_delta(close, 5)", data)


def alpha191_124(data: FactorData) -> pd.DataFrame:
    """反转 | 10日价格变化排名取负。"""
    return evaluate("-1 * rank(ts_delta(close, 10))", data)


def alpha191_125(data: FactorData) -> pd.DataFrame:
    """反转 | 5日平均收益反转。"""
    return evaluate("-1 * ts_mean(returns, 5)", data)


def alpha191_126(data: FactorData) -> pd.DataFrame:
    """反转 | 20日平均收益反转。"""
    return evaluate("-1 * ts_mean(returns, 20)", data)


def alpha191_127(data: FactorData) -> pd.DataFrame:
    """反转 | 收盘相对20日均线的负标准分。"""
    return evaluate("-1 * (close - ts_mean(close, 20)) / ts_std(close, 20)", data)


def alpha191_128(data: FactorData) -> pd.DataFrame:
    """反转 | 20日收盘时序排名取负。"""
    return evaluate("-1 * ts_rank(close, 20)", data)


def alpha191_129(data: FactorData) -> pd.DataFrame:
    """反转 | 收益20日时序排名取负。"""
    return evaluate("-1 * ts_rank(returns, 20)", data)


def alpha191_130(data: FactorData) -> pd.DataFrame:
    """反转 | 10日收盘时序排名取负。"""
    return evaluate("-1 * rank(ts_rank(close, 10))", data)


def alpha191_131(data: FactorData) -> pd.DataFrame:
    """反转 | 隔夜跳空（开盘/昨收）。"""
    return evaluate("open / ts_delay(close, 1) - 1", data)


def alpha191_132(data: FactorData) -> pd.DataFrame:
    """反转 | 隔夜跳空反转。"""
    return evaluate("-1 * (open / ts_delay(close, 1) - 1)", data)


def alpha191_133(data: FactorData) -> pd.DataFrame:
    """反转 | 1日收盘收益（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("close / ts_delay(close, 1) - 1", data)


def alpha191_134(data: FactorData) -> pd.DataFrame:
    """反转 | 昨日开盘相对今日收盘的缺口排名（公开资料未收录）。"""
    return evaluate("rank(ts_delay(open, 1) / close - 1)", data)


def alpha191_135(data: FactorData) -> pd.DataFrame:
    """反转 | 开盘日变化反转（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("-1 * ts_delta(open, 1)", data)


def alpha191_136(data: FactorData) -> pd.DataFrame:
    """反转 | 最高价日变化反转（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("-1 * ts_delta(high, 1)", data)


def alpha191_137(data: FactorData) -> pd.DataFrame:
    """反转 | 最低价日变化反转（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("-1 * ts_delta(low, 1)", data)


def alpha191_138(data: FactorData) -> pd.DataFrame:
    """反转 | 1日收益率取负（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("-1 * (close - ts_delay(close, 1)) / ts_delay(close, 1)", data)


def alpha191_139(data: FactorData) -> pd.DataFrame:
    """反转 | 1日价格反转的10日时序排名（公开资料未收录）。"""
    return evaluate("ts_rank(-1 * ts_delta(close, 1), 10)", data)


def alpha191_140(data: FactorData) -> pd.DataFrame:
    """反转 | 价格加速度排名（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("rank(ts_delta(ts_delta(close, 1), 1))", data)


def alpha191_141(data: FactorData) -> pd.DataFrame:
    """反转 | 价格加速度反转（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("-1 * ts_delta(ts_delta(close, 1), 1)", data)


def alpha191_142(data: FactorData) -> pd.DataFrame:
    """反转 | 5日累计收益反转（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("-1 * ts_sum(returns, 5)", data)


def alpha191_143(data: FactorData) -> pd.DataFrame:
    """反转 | 10日累计收益反转（公开资料未收录，按同类逻辑等价实现）。"""
    return evaluate("-1 * ts_sum(returns, 10)", data)


def alpha191_144(data: FactorData) -> pd.DataFrame:
    """反转 | 负收益的5日时序排名（公开资料未收录）。"""
    return evaluate("ts_rank(-1 * returns, 5)", data)


def alpha191_145(data: FactorData) -> pd.DataFrame:
    """反转 | 5日最低价相对收盘的排名（超卖，公开资料未收录）。"""
    return evaluate("rank(ts_min(low, 5) / close - 1)", data)


def alpha191_146(data: FactorData) -> pd.DataFrame:
    """反转 | 5日最高价相对收盘的排名（超买，公开资料未收录）。"""
    return evaluate("rank(ts_max(high, 5) / close - 1)", data)


def alpha191_147(data: FactorData) -> pd.DataFrame:
    """反转 | 收盘相对5日最低价的溢价反转（公开资料未收录）。"""
    return evaluate("-1 * (ts_min(low, 5) - close) / close", data)


def alpha191_148(data: FactorData) -> pd.DataFrame:
    """反转 | 收盘距5日最高价的回撤（公开资料未收录）。"""
    return evaluate("-1 * (close - ts_max(high, 5)) / close", data)


def alpha191_149(data: FactorData) -> pd.DataFrame:
    """反转 | 收盘位置5日变化的负值（公开资料未收录）。"""
    return evaluate("-1 * ts_delta((close - low) / high, 5)", data)


def alpha191_150(data: FactorData) -> pd.DataFrame:
    """反转 | 上影线比例5日变化的负值（公开资料未收录）。"""
    return evaluate("-1 * ts_delta((high - close) / high, 5)", data)


# ==================== 151-170 资金流类 ====================
def alpha191_151(data: FactorData) -> pd.DataFrame:
    """资金流 | 日内收盘位置（开盘强弱）。"""
    return evaluate("(close - open) / (high - low + 0.001)", data)


def alpha191_152(data: FactorData) -> pd.DataFrame:
    """资金流 | 5日平均日内收盘位置。"""
    return evaluate("ts_mean((close - open) / (high - low + 0.001), 5)", data)


def alpha191_153(data: FactorData) -> pd.DataFrame:
    """资金流 | 20日平均日内收盘位置。"""
    return evaluate("ts_mean((close - open) / (high - low + 0.001), 20)", data)


def alpha191_154(data: FactorData) -> pd.DataFrame:
    """资金流 | 10日量加权日内收益（资金净流入）。"""
    return evaluate("ts_sum((close - open) * volume, 10) / ts_sum(volume, 10)", data)


def alpha191_155(data: FactorData) -> pd.DataFrame:
    """资金流 | 20日量加权日内收益（资金净流入）。"""
    return evaluate("ts_sum((close - open) * volume, 20) / ts_sum(volume, 20)", data)


def alpha191_156(data: FactorData) -> pd.DataFrame:
    """资金流 | 10日收盘位置成交额净额（尾盘效应代理）。"""
    return evaluate("ts_sum(((close - low) - (high - close)) / (high - low) * volume, 10)", data)


def alpha191_157(data: FactorData) -> pd.DataFrame:
    """资金流 | 20日收盘位置成交额净额。"""
    return evaluate("ts_sum(((close - low) - (high - close)) / (high - low) * volume, 20)", data)


def alpha191_158(data: FactorData) -> pd.DataFrame:
    """资金流 | 当日收盘在日内区间的位置（资金强度）。"""
    return evaluate("(close - low) / (high - low + 0.001)", data)


def alpha191_159(data: FactorData) -> pd.DataFrame:
    """资金流 | 当日上影线占比（抛压强度）。"""
    return evaluate("(high - close) / (high - low + 0.001)", data)


def alpha191_160(data: FactorData) -> pd.DataFrame:
    """资金流 | 10日平均资金强度。"""
    return evaluate("ts_mean((close - low) / (high - low + 0.001), 10)", data)


def alpha191_161(data: FactorData) -> pd.DataFrame:
    """资金流 | 10日平均抛压强度。"""
    return evaluate("ts_mean((high - close) / (high - low + 0.001), 10)", data)


def alpha191_162(data: FactorData) -> pd.DataFrame:
    """资金流 | 10日量加权日内收益排名（公开资料未收录）。"""
    return evaluate("rank(ts_sum((close - open) * volume, 10))", data)


def alpha191_163(data: FactorData) -> pd.DataFrame:
    """资金流 | 20日量加权日内收益排名（公开资料未收录）。"""
    return evaluate("rank(ts_sum((close - open) * volume, 20))", data)


def alpha191_164(data: FactorData) -> pd.DataFrame:
    """资金流 | 日内收益与成交量的10日相关（公开资料未收录）。"""
    return evaluate("ts_corr((close - open) / (high - low + 0.001), volume, 10)", data)


def alpha191_165(data: FactorData) -> pd.DataFrame:
    """资金流 | 资金强度与成交量的10日相关（公开资料未收录）。"""
    return evaluate("ts_corr((close - low) / (high - low + 0.001), volume, 10)", data)


def alpha191_166(data: FactorData) -> pd.DataFrame:
    """资金流 | 抛压强度与成交量的10日相关（公开资料未收录）。"""
    return evaluate("ts_corr((high - close) / (high - low + 0.001), volume, 10)", data)


def alpha191_167(data: FactorData) -> pd.DataFrame:
    """资金流 | 5日 vwap 相对收盘的溢价（公开资料未收录）。"""
    return evaluate("ts_sum(amount, 5) / ts_sum(volume, 5) / close - 1", data)


def alpha191_168(data: FactorData) -> pd.DataFrame:
    """资金流 | 20日 vwap 相对均价（公开资料未收录）。"""
    return evaluate("ts_sum(amount, 20) / ts_sum(volume, 20) / ts_mean(close, 20) - 1", data)


def alpha191_169(data: FactorData) -> pd.DataFrame:
    """资金流 | vwap 相对收盘溢价的20日波动（公开资料未收录）。"""
    return evaluate("ts_std(amount / volume / close - 1, 20)", data)


def alpha191_170(data: FactorData) -> pd.DataFrame:
    """资金流 | 成交额与收盘的20日相关排名（公开资料未收录）。"""
    return evaluate("rank(ts_corr(amount, close, 20))", data)


# ==================== 171-191 混合类 ====================
def alpha191_171(data: FactorData) -> pd.DataFrame:
    """混合 | 短期与长期动量排名之和。"""
    return evaluate("rank(ts_mean(returns, 5)) + rank(ts_mean(returns, 20))", data)


def alpha191_172(data: FactorData) -> pd.DataFrame:
    """混合 | 波动率与量价相关的排名组合。"""
    return evaluate("rank(ts_std(returns, 10)) + rank(ts_corr(close, volume, 10))", data)


def alpha191_173(data: FactorData) -> pd.DataFrame:
    """混合 | 5日动量排名减量比排名。"""
    return evaluate("rank(ts_momentum(close, 5)) - rank(volume / adv20)", data)


def alpha191_174(data: FactorData) -> pd.DataFrame:
    """混合 | 量价相关排名乘20日动量排名。"""
    return evaluate("rank(ts_corr(close, volume, 10)) * rank(ts_momentum(close, 20))", data)


def alpha191_175(data: FactorData) -> pd.DataFrame:
    """混合 | 5日/20日均线比的截面标准分。"""
    return evaluate("zscore(ts_mean(close, 5) / ts_mean(close, 20))", data)


def alpha191_176(data: FactorData) -> pd.DataFrame:
    """混合 | 20日波动率的截面标准分。"""
    return evaluate("zscore(ts_std(returns, 20))", data)


def alpha191_177(data: FactorData) -> pd.DataFrame:
    """混合 | 量比的截面标准分。"""
    return evaluate("zscore(volume / adv20)", data)


def alpha191_178(data: FactorData) -> pd.DataFrame:
    """混合 | 量价相关的截面标准分。"""
    return evaluate("zscore(ts_corr(close, volume, 10))", data)


def alpha191_179(data: FactorData) -> pd.DataFrame:
    """混合 | 动量与短期收益排名的截面归一化组合。"""
    return evaluate("scale(rank(ts_momentum(close, 10)) + rank(ts_mean(returns, 5)))", data)


def alpha191_180(data: FactorData) -> pd.DataFrame:
    """混合 | 日内实体收益均值排名加量比均值排名。"""
    return evaluate("rank(ts_mean((close - open) / close, 10)) + rank(ts_mean(volume / adv20, 10))", data)


def alpha191_181(data: FactorData) -> pd.DataFrame:
    """混合 | 振幅率排名乘量价相关排名。"""
    return evaluate("rank(ts_std(high - low, 10) / ts_mean(close, 10)) * rank(ts_corr(close, volume, 10))", data)


def alpha191_182(data: FactorData) -> pd.DataFrame:
    """混合 | 量加权日内收益排名减成交量排名。"""
    return evaluate("rank(ts_sum((close - open) * volume, 10)) - rank(ts_sum(volume, 10))", data)


def alpha191_183(data: FactorData) -> pd.DataFrame:
    """混合 | 短期与长期动量排名之和（公开资料未收录）。"""
    return evaluate("rank(ts_momentum(close, 3)) + rank(ts_momentum(close, 20))", data)


def alpha191_184(data: FactorData) -> pd.DataFrame:
    """混合 | 低波动加长期收益的排名组合（公开资料未收录）。"""
    return evaluate("rank(-1 * ts_std(returns, 5)) + rank(ts_mean(returns, 20))", data)


def alpha191_185(data: FactorData) -> pd.DataFrame:
    """混合 | vwap量价相关加vwap动量排名（公开资料未收录）。"""
    return evaluate("rank(ts_corr(vwap, volume, 10)) + rank(ts_momentum(vwap, 10))", data)


def alpha191_186(data: FactorData) -> pd.DataFrame:
    """混合 | 短期与长期收盘时序排名差。"""
    return evaluate("rank(ts_rank(close, 10) - ts_rank(close, 20))", data)


def alpha191_187(data: FactorData) -> pd.DataFrame:
    """混合 | 10日最高点与最低点位置排名之和（形态识别）。"""
    return evaluate("rank(ts_argmax(close, 10)) + rank(ts_argmin(close, 10))", data)


def alpha191_188(data: FactorData) -> pd.DataFrame:
    """混合 | 价格变化排名与量变化排名乘积（量价共振）。"""
    return evaluate("rank(ts_delta(close, 1)) * rank(ts_delta(volume, 1))", data)


def alpha191_189(data: FactorData) -> pd.DataFrame:
    """混合 | 短长期波动率排名之比（公开资料未收录）。"""
    return evaluate("rank(ts_std(returns, 10)) / rank(ts_std(returns, 60))", data)


def alpha191_190(data: FactorData) -> pd.DataFrame:
    """混合 | 5日动量与量价相关的截面归一化乘积。"""
    return evaluate("scale(rank(ts_momentum(close, 5)) * rank(ts_corr(close, volume, 10)))", data)


def alpha191_191(data: FactorData) -> pd.DataFrame:
    """混合 | 10日收益排名与量比排名乘积（形态识别）。"""
    return evaluate("rank(ts_mean(returns, 10)) * rank(volume / adv20)", data)


# ==================== 统一入口 ====================
ALPHA191_FUNCS: List[Callable[[FactorData], pd.DataFrame]] = [
    alpha191_001, alpha191_002, alpha191_003, alpha191_004, alpha191_005,
    alpha191_006, alpha191_007, alpha191_008, alpha191_009, alpha191_010,
    alpha191_011, alpha191_012, alpha191_013, alpha191_014, alpha191_015,
    alpha191_016, alpha191_017, alpha191_018, alpha191_019, alpha191_020,
    alpha191_021, alpha191_022, alpha191_023, alpha191_024, alpha191_025,
    alpha191_026, alpha191_027, alpha191_028, alpha191_029, alpha191_030,
    alpha191_031, alpha191_032, alpha191_033, alpha191_034, alpha191_035,
    alpha191_036, alpha191_037, alpha191_038, alpha191_039, alpha191_040,
    alpha191_041, alpha191_042, alpha191_043, alpha191_044, alpha191_045,
    alpha191_046, alpha191_047, alpha191_048, alpha191_049, alpha191_050,
    alpha191_051, alpha191_052, alpha191_053, alpha191_054, alpha191_055,
    alpha191_056, alpha191_057, alpha191_058, alpha191_059, alpha191_060,
    alpha191_061, alpha191_062, alpha191_063, alpha191_064, alpha191_065,
    alpha191_066, alpha191_067, alpha191_068, alpha191_069, alpha191_070,
    alpha191_071, alpha191_072, alpha191_073, alpha191_074, alpha191_075,
    alpha191_076, alpha191_077, alpha191_078, alpha191_079, alpha191_080,
    alpha191_081, alpha191_082, alpha191_083, alpha191_084, alpha191_085,
    alpha191_086, alpha191_087, alpha191_088, alpha191_089, alpha191_090,
    alpha191_091, alpha191_092, alpha191_093, alpha191_094, alpha191_095,
    alpha191_096, alpha191_097, alpha191_098, alpha191_099, alpha191_100,
    alpha191_101, alpha191_102, alpha191_103, alpha191_104, alpha191_105,
    alpha191_106, alpha191_107, alpha191_108, alpha191_109, alpha191_110,
    alpha191_111, alpha191_112, alpha191_113, alpha191_114, alpha191_115,
    alpha191_116, alpha191_117, alpha191_118, alpha191_119, alpha191_120,
    alpha191_121, alpha191_122, alpha191_123, alpha191_124, alpha191_125,
    alpha191_126, alpha191_127, alpha191_128, alpha191_129, alpha191_130,
    alpha191_131, alpha191_132, alpha191_133, alpha191_134, alpha191_135,
    alpha191_136, alpha191_137, alpha191_138, alpha191_139, alpha191_140,
    alpha191_141, alpha191_142, alpha191_143, alpha191_144, alpha191_145,
    alpha191_146, alpha191_147, alpha191_148, alpha191_149, alpha191_150,
    alpha191_151, alpha191_152, alpha191_153, alpha191_154, alpha191_155,
    alpha191_156, alpha191_157, alpha191_158, alpha191_159, alpha191_160,
    alpha191_161, alpha191_162, alpha191_163, alpha191_164, alpha191_165,
    alpha191_166, alpha191_167, alpha191_168, alpha191_169, alpha191_170,
    alpha191_171, alpha191_172, alpha191_173, alpha191_174, alpha191_175,
    alpha191_176, alpha191_177, alpha191_178, alpha191_179, alpha191_180,
    alpha191_181, alpha191_182, alpha191_183, alpha191_184, alpha191_185,
    alpha191_186, alpha191_187, alpha191_188, alpha191_189, alpha191_190,
    alpha191_191,
]


def get_alpha191_list() -> List[Callable[[FactorData], pd.DataFrame]]:
    """返回全部 191 个 alpha191 函数（顺序即编号）。"""
    return list(ALPHA191_FUNCS)


def get_builtin_alpha191(n: int) -> Callable[[FactorData], pd.DataFrame]:
    """按编号 1~191 取单个 alpha191 函数。"""
    n = int(n)
    if not 1 <= n <= 191:
        raise ValueError(f"alpha191 编号必须在 1~191 之间，收到 {n}")
    return ALPHA191_FUNCS[n - 1]
