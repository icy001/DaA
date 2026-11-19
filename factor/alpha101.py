"""Alpha101 因子库（Kakushadze 2016, arXiv:1601.00991）。

⚠️ Alpha101 是「因子库」，不是交易策略。它只回答「今天全市场哪些股票该给
高分/低分」，不回答何时买卖、仓位、调仓频率与风控。单因子 IC 普遍很低，
A 股部分因子会失效甚至反向，必须经过评估→合成→组合构建→样本外回测后才能
考虑实盘。

本文件严格复现论文 101 条公式：
  * 每条函数 ``alpha001(data) -> DataFrame``，index=日期，columns=股票；
  * 函数 docstring 保留论文原公式 + 中文说明；
  * 全部通过 factor/expression.py 计算，口径统一；
  * 无 vwap 时用 (high+low+close)/3 或 amount/volume 兜底；
  * 无行业数据时 group_rank/group_neutralize 自动降级为全市场截面；
  * 无市值 cap 时 alpha056 降级为 rank(returns)。

注意：表达式引擎中所有时序算子都不含当日（窗口为 [i-d, i-1]），
这是本系统的强制防未来函数口径，与论文原始口径略有差异。
"""
from __future__ import annotations

from typing import Callable, List

import pandas as pd

from .base import FactorData
from .expression import evaluate

__all__ = ["get_alpha_list", "get_builtin_alpha", "alpha001"]


def alpha001(data: FactorData) -> pd.DataFrame:
    """原式: rank(Ts_ArgMax(SignedPower((returns<0?stddev(returns,20):close),2),5))-0.5
    中文: 收益为负时用20日波动率、否则用收盘价，取5日最高点位置的排名。
    """
    return evaluate("rank(ts_argmax(signedpower(if_else(returns < 0, ts_std(returns, 20), close), 2), 5)) - 0.5", data)


def alpha002(data: FactorData) -> pd.DataFrame:
    """原式: -1*correlation(rank(delta(log(volume),2)),rank((close-open)/open),6)
    中文: 成交量变化排名与日内涨跌幅排名的负相关。
    """
    return evaluate("-1 * ts_corr(rank(ts_delta(log(volume), 2)), rank((close - open) / open), 6)", data)


def alpha003(data: FactorData) -> pd.DataFrame:
    """原式: -1*correlation(rank(open),rank(volume),10)
    中文: 开盘价排名与成交量排名的负相关。
    """
    return evaluate("-1 * ts_corr(rank(open), rank(volume), 10)", data)


def alpha004(data: FactorData) -> pd.DataFrame:
    """原式: -1*Ts_Rank(rank(low),9)
    中文: 最低价截面排名的9日时序排名取负。
    """
    return evaluate("-1 * ts_rank(rank(low), 9)", data)


def alpha005(data: FactorData) -> pd.DataFrame:
    """原式: rank(open-sum(vwap,10)/10)*-1*abs(rank(close-vwap))
    中文: 开盘价偏离10日均vwap的排名，乘以收盘偏离vwap的排名绝对值。
    """
    return evaluate("rank(open - ts_sum(vwap, 10) / 10) * (-1 * abs(rank(close - vwap)))", data)


def alpha006(data: FactorData) -> pd.DataFrame:
    """原式: -1*correlation(open,volume,10)
    中文: 开盘价与成交量的10日负相关（论文高频坑之一）。
    """
    return evaluate("-1 * ts_corr(open, volume, 10)", data)


def alpha007(data: FactorData) -> pd.DataFrame:
    """原式: adv20<volume ? -1*ts_rank(abs(delta(close,7)),60)*sign(delta(close,7)) : -1
    中文: 放量时按7日价格变化方向做反转。
    """
    return evaluate(
        "if_else(adv20 < volume, -1 * ts_rank(abs(ts_delta(close, 7)), 60) * sign(ts_delta(close, 7)), -1)",
        data,
    )


def alpha008(data: FactorData) -> pd.DataFrame:
    """原式: -1*rank((sum(open,5)*sum(returns,5))-delay(sum(open,5)*sum(returns,5),10))
    中文: 开盘价与收益5日乘积相对10日前的负变化。
    """
    return evaluate(
        "-1 * rank((ts_sum(open, 5) * ts_sum(returns, 5)) - ts_delay(ts_sum(open, 5) * ts_sum(returns, 5), 10))",
        data,
    )


def alpha009(data: FactorData) -> pd.DataFrame:
    """原式: 0<ts_min(delta(close,1),5)?delta(close,1):(ts_max(delta(close,1),5)<0?delta(close,1):-delta(close,1))
    中文: 连续同向变化时跟随，否则反转。
    """
    return evaluate(
        "if_else(0 < ts_min(ts_delta(close, 1), 5), ts_delta(close, 1), "
        "if_else(ts_max(ts_delta(close, 1), 5) < 0, ts_delta(close, 1), -1 * ts_delta(close, 1)))",
        data,
    )


def alpha010(data: FactorData) -> pd.DataFrame:
    """原式: rank(0<ts_min(delta(close,1),4)?delta(close,1):(ts_max(delta(close,1),4)<0?delta(close,1):-delta(close,1)))
    中文: alpha009 的4日窗口版本并做截面排名。
    """
    return evaluate(
        "rank(if_else(0 < ts_min(ts_delta(close, 1), 4), ts_delta(close, 1), "
        "if_else(ts_max(ts_delta(close, 1), 4) < 0, ts_delta(close, 1), -1 * ts_delta(close, 1))))",
        data,
    )


def alpha011(data: FactorData) -> pd.DataFrame:
    """原式: (rank(ts_max(vwap-close,3))+rank(ts_min(vwap-close,3)))*rank(delta(volume,3))
    中文: vwap偏离的通道位置乘以成交量变化排名。
    """
    return evaluate(
        "(rank(ts_max(vwap - close, 3)) + rank(ts_min(vwap - close, 3))) * rank(ts_delta(volume, 3))",
        data,
    )


def alpha012(data: FactorData) -> pd.DataFrame:
    """原式: sign(delta(volume,1))*(-1*delta(close,1))
    中文: 量增价跌/量减价涨的反转。
    """
    return evaluate("sign(ts_delta(volume, 1)) * (-1 * ts_delta(close, 1))", data)


def alpha013(data: FactorData) -> pd.DataFrame:
    """原式: -1*rank(covariance(rank(close),rank(volume),5))
    中文: 收盘与成交量排名协方差的负值。
    """
    return evaluate("-1 * rank(ts_cov(rank(close), rank(volume), 5))", data)


def alpha014(data: FactorData) -> pd.DataFrame:
    """原式: -1*rank(delta(returns,3))*correlation(open,volume,10)
    中文: 收益变化与开量相关的交互反转。
    """
    return evaluate("-1 * rank(ts_delta(returns, 3)) * ts_corr(open, volume, 10)", data)


def alpha015(data: FactorData) -> pd.DataFrame:
    """原式: -1*sum(rank(correlation(rank(high),rank(volume),3)),3)
    中文: 高价与高量相关性的3日累计取负。
    """
    return evaluate("-1 * ts_sum(rank(ts_corr(rank(high), rank(volume), 3)), 3)", data)


def alpha016(data: FactorData) -> pd.DataFrame:
    """原式: -1*rank(covariance(rank(high),rank(volume),5))
    中文: 最高价与成交量排名协方差的负值。
    """
    return evaluate("-1 * rank(ts_cov(rank(high), rank(volume), 5))", data)


def alpha017(data: FactorData) -> pd.DataFrame:
    """原式: -1*rank(ts_rank(close,10))*rank(delta(delta(close,1),1))*rank(ts_rank(volume/adv20,5))
    中文: 价格趋势、加速度、相对量能三者的交互。
    """
    return evaluate(
        "-1 * rank(ts_rank(close, 10)) * rank(ts_delta(ts_delta(close, 1), 1)) "
        "* rank(ts_rank(volume / adv20, 5))",
        data,
    )


def alpha018(data: FactorData) -> pd.DataFrame:
    """原式: -1*rank(stddev(abs(close-open),5)+(close-open)+correlation(close,open,10))
    中文: 日内实体波动与开收盘相关性的组合反转。
    """
    return evaluate(
        "-1 * rank((ts_std(abs(close - open), 5) + (close - open)) + ts_corr(close, open, 10))", data
    )


def alpha019(data: FactorData) -> pd.DataFrame:
    """原式: -1*sign((close-delay(close,7))+delta(close,7))*(1+rank(1+sum(returns,250)))
    中文: 7日价格方向乘以长期收益排名。
    """
    return evaluate(
        "-1 * sign((close - ts_delay(close, 7)) + ts_delta(close, 7)) "
        "* (1 + rank(1 + ts_sum(returns, 250)))",
        data,
    )


def alpha020(data: FactorData) -> pd.DataFrame:
    """原式: -1*rank(open-delay(high,1))*rank(open-delay(close,1))*rank(open-delay(low,1))
    中文: 开盘价相对昨日高/收/低的跳空强度。
    """
    return evaluate(
        "-1 * rank(open - ts_delay(high, 1)) * rank(open - ts_delay(close, 1)) "
        "* rank(open - ts_delay(low, 1))",
        data,
    )


def alpha021(data: FactorData) -> pd.DataFrame:
    """原式: 均线通道+量比的复合条件因子。
    中文: 短期均线突破长期通道上/下轨时给方向，否则看量比。
    """
    return evaluate(
        "if_else((ts_sum(close, 8) / 8 + ts_std(close, 8)) < (ts_sum(close, 2) / 2), -1, "
        "if_else((ts_sum(close, 2) / 2) < (ts_sum(close, 8) / 8 - ts_std(close, 8)), 1, "
        "if_else(volume / adv20 >= 1, 1, -1)))",
        data,
    )


def alpha022(data: FactorData) -> pd.DataFrame:
    """原式: -1*(delta(correlation(high,volume,5),5)*rank(stddev(close,20)))
    中文: 高价量相关性的变化乘以波动率排名。
    """
    return evaluate("-1 * (ts_delta(ts_corr(high, volume, 5), 5) * rank(ts_std(close, 20)))", data)


def alpha023(data: FactorData) -> pd.DataFrame:
    """原式: sum(high,20)/20<high ? -1*delta(high,2) : 0
    中文: 突破20日均高时做2日反转。
    """
    return evaluate("if_else(ts_sum(high, 20) / 20 < high, -1 * ts_delta(high, 2), 0)", data)


def alpha024(data: FactorData) -> pd.DataFrame:
    """原式: (delta(sum(close,100)/100,100)/delay(close,100)<=0.05)?-1*(close-ts_min(close,100)):-1*delta(close,3)
    中文: 长期趋势弱时做均值回复，否则短期反转。
    """
    return evaluate(
        "if_else((ts_delta(ts_sum(close, 100) / 100, 100) / ts_delay(close, 100)) <= 0.05, "
        "-1 * (close - ts_min(close, 100)), -1 * ts_delta(close, 3))",
        data,
    )


def alpha025(data: FactorData) -> pd.DataFrame:
    """原式: rank((-1*returns)*adv20*vwap*(high-close))
    中文: 收益、量能、vwap与上影线的组合反转。
    """
    return evaluate("rank((-1 * returns) * adv20 * vwap * (high - close))", data)


def alpha026(data: FactorData) -> pd.DataFrame:
    """原式: -1*ts_max(correlation(ts_rank(volume,5),ts_rank(high,5),5),3)
    中文: 量价时序排名相关性的3日峰值取负。
    """
    return evaluate("-1 * ts_max(ts_corr(ts_rank(volume, 5), ts_rank(high, 5), 5), 3)", data)


def alpha027(data: FactorData) -> pd.DataFrame:
    """原式: (0.5<rank(sum(correlation(rank(volume),rank(vwap),6),2)/2))?-1:1
    中文: 量价相关性高时看空，否则看多。
    """
    return evaluate(
        "if_else(0.5 < rank(ts_sum(ts_corr(rank(volume), rank(vwap), 6), 2) / 2), -1, 1)", data
    )


def alpha028(data: FactorData) -> pd.DataFrame:
    """原式: scale(correlation(adv20,low,5)+((high+low)/2)-close)
    中文: 量能与低价相关性叠加收盘位置。
    """
    return evaluate("scale(ts_corr(adv20, low, 5) + ((high + low) / 2) - close)", data)


def alpha029(data: FactorData) -> pd.DataFrame:
    """原式: min(product(rank(rank(scale(log(sum(ts_min(rank(rank(-1*rank(delta(close-1,5)))),2),1))))),1),5)
            + ts_rank(delay(-1*returns,6),5)
    中文: 深层价格变化排名与6日前反转收益的时序排名。
    """
    return evaluate(
        "ts_min(ts_product(rank(rank(scale(log(ts_sum(ts_min(rank(rank(-1 * rank(ts_delta(close - 1, 5)))), 2), 1))))), 1), 5) "
        "+ ts_rank(ts_delay(-1 * returns, 6), 5)",
        data,
    )


def alpha030(data: FactorData) -> pd.DataFrame:
    """原式: ((1-rank((sign(close-delay(close,1))+sign(delay(close,1)-delay(close,2)))+sign(delay(close,2)-delay(close,3))))*sum(volume,5))/sum(volume,20)
    中文: 连续价格方向反向时放量。
    """
    return evaluate(
        "((1.0 - rank(((sign((close - ts_delay(close, 1))) + sign((ts_delay(close, 1) - ts_delay(close, 2)))) "
        "+ sign((ts_delay(close, 2) - ts_delay(close, 3)))))) * ts_sum(volume, 5)) / ts_sum(volume, 20)",
        data,
    )


def alpha031(data: FactorData) -> pd.DataFrame:
    """原式: rank(rank(rank(decay_linear(-1*rank(rank(delta(close,10))),10))))+rank(-1*delta(close,3))+sign(scale(correlation(adv20,low,12)))
    中文: 长短期价格变化与量价相关性的组合。
    """
    return evaluate(
        "(rank(rank(rank(decay_linear((-1 * rank(rank(ts_delta(close, 10)))), 10)))) "
        "+ rank((-1 * ts_delta(close, 3)))) + sign(scale(ts_corr(adv20, low, 12)))",
        data,
    )


def alpha032(data: FactorData) -> pd.DataFrame:
    """原式: scale(sum(close,7)/7-close)+20*scale(correlation(vwap,delay(close,5),230))
    中文: 均线偏离与vwap长期相关性。
    """
    return evaluate(
        "scale((ts_sum(close, 7) / 7) - close) + (20 * scale(ts_corr(vwap, ts_delay(close, 5), 230)))",
        data,
    )


def alpha033(data: FactorData) -> pd.DataFrame:
    """原式: rank(-1*(1-(open/close)))
    中文: 日内开盘相对收盘的折价。
    """
    return evaluate("rank(-1 * (1 - (open / close)))", data)


def alpha034(data: FactorData) -> pd.DataFrame:
    """原式: rank((1-rank(stddev(returns,2)/stddev(returns,5)))+(1-rank(delta(close,1))))
    中文: 短长期波动比与价格变化的反向排名。
    """
    return evaluate(
        "rank((1 - rank((ts_std(returns, 2) / ts_std(returns, 5)))) + (1 - rank(ts_delta(close, 1))))",
        data,
    )


def alpha035(data: FactorData) -> pd.DataFrame:
    """原式: ts_rank(volume,32)*(1-ts_rank(close+high-low,16))*(1-ts_rank(returns,32))
    中文: 量能高位、价格位置低位、收益低位的组合。
    """
    return evaluate(
        "ts_rank(volume, 32) * (1 - ts_rank((close + high) - low, 16)) * (1 - ts_rank(returns, 32))",
        data,
    )


def alpha036(data: FactorData) -> pd.DataFrame:
    """原式: 2.21*rank(corr(close-open,delay(volume,1),15))+0.7*rank(open-close)+0.73*rank(ts_rank(delay(-returns,6),5))+rank(abs(corr(vwap,adv20,6)))+0.6*rank((sum(close,200)/200-open)*(close-open))
    中文: 价量背离、日内反转、长期均线偏离的加权组合。
    """
    return evaluate(
        "2.21 * rank(ts_corr((close - open), ts_delay(volume, 1), 15)) "
        "+ 0.7 * rank((open - close)) "
        "+ 0.73 * rank(ts_rank(ts_delay(-1 * returns, 6), 5)) "
        "+ rank(abs(ts_corr(vwap, adv20, 6))) "
        "+ 0.6 * rank((((ts_sum(close, 200) / 200) - open) * (close - open)))",
        data,
    )


def alpha037(data: FactorData) -> pd.DataFrame:
    """原式: rank(correlation(delay(open-close,1),close,200))+rank(open-close)
    中文: 昨日日内收益与收盘的长期相关性叠加今日日内收益。
    """
    return evaluate(
        "rank(ts_corr(ts_delay(open - close, 1), close, 200)) + rank(open - close)", data
    )


def alpha038(data: FactorData) -> pd.DataFrame:
    """原式: -1*rank(ts_rank(close,10))*rank(close/open)
    中文: 收盘趋势排名与日内涨幅的负向组合。
    """
    return evaluate("(-1 * rank(ts_rank(close, 10))) * rank(close / open)", data)


def alpha039(data: FactorData) -> pd.DataFrame:
    """原式: -1*rank(delta(close,7)*(1-rank(decay_linear(volume/adv20,9))))*(1+rank(sum(returns,250)))
    中文: 价格变化与相对量能的衰减排名交互。
    """
    return evaluate(
        "(-1 * rank(ts_delta(close, 7) * (1 - rank(decay_linear(volume / adv20, 9))))) "
        "* (1 + rank(ts_sum(returns, 250)))",
        data,
    )


def alpha040(data: FactorData) -> pd.DataFrame:
    """原式: -1*rank(stddev(high,10))*correlation(high,volume,10)
    中文: 高价波动率排名与量价相关性的组合。
    """
    return evaluate("(-1 * rank(ts_std(high, 10))) * ts_corr(high, volume, 10)", data)


def alpha041(data: FactorData) -> pd.DataFrame:
    """原式: ((high*low)^0.5)-vwap
    中文: 几何均价与vwap的偏离。
    """
    return evaluate("(high * low) ** 0.5 - vwap", data)


def alpha042(data: FactorData) -> pd.DataFrame:
    """原式: rank(vwap-close)/rank(vwap+close)
    中文: 收盘相对vwap偏离的归一化。
    """
    return evaluate("rank(vwap - close) / rank(vwap + close)", data)


def alpha043(data: FactorData) -> pd.DataFrame:
    """原式: ts_rank(volume/adv20,20)*ts_rank(-1*delta(close,7),8)
    中文: 相对量能时序排名与价格反转的乘积。
    """
    return evaluate("ts_rank(volume / adv20, 20) * ts_rank(-1 * ts_delta(close, 7), 8)", data)


def alpha044(data: FactorData) -> pd.DataFrame:
    """原式: -1*correlation(high,rank(volume),5)
    中文: 最高价与成交量排名的负相关。
    """
    return evaluate("-1 * ts_corr(high, rank(volume), 5)", data)


def alpha045(data: FactorData) -> pd.DataFrame:
    """原式: -1*(rank(sum(delay(close,5),20)/20)*correlation(close,volume,2)*rank(correlation(sum(close,5),sum(close,20),2)))
    中文: 长期均线位置、短量价相关、长短均线相关的三重交互。
    """
    return evaluate(
        "-1 * ((rank(ts_sum(ts_delay(close, 5), 20) / 20) * ts_corr(close, volume, 2)) "
        "* rank(ts_corr(ts_sum(close, 5), ts_sum(close, 20), 2)))",
        data,
    )


def alpha046(data: FactorData) -> pd.DataFrame:
    """原式: (0.25<((delay(close,20)-delay(close,10))/10-(delay(close,10)-close)/10))?-1:((...)<0?1:-1*(close-delay(close,1)))
    中文: 价格趋势加速度的条件反转。
    """
    return evaluate(
        "if_else(0.25 < (((ts_delay(close, 20) - ts_delay(close, 10)) / 10) - ((ts_delay(close, 10) - close) / 10)), -1, "
        "if_else((((ts_delay(close, 20) - ts_delay(close, 10)) / 10) - ((ts_delay(close, 10) - close) / 10)) < 0, 1, "
        "-1 * (close - ts_delay(close, 1))))",
        data,
    )


def alpha047(data: FactorData) -> pd.DataFrame:
    """原式: ((rank(1/close)*volume)/adv20)*((high*rank(high-close))/(sum(high,5)/5))-rank(vwap-delay(vwap,5))
    中文: 量能、上影线与vwap变化的组合。
    """
    return evaluate(
        "((rank(1 / close) * volume) / adv20) * ((high * rank(high - close)) / (ts_sum(high, 5) / 5)) "
        "- rank(vwap - ts_delay(vwap, 5))",
        data,
    )


def alpha048(data: FactorData) -> pd.DataFrame:
    """原式: IndNeutralize(correlation(delta(close,1),delta(delay(close,1),1),250)*delta(close,1)/close,industry)/sum(volume,5)
    中文: 收益自相关的行业中性值除以5日成交量。
    """
    return evaluate(
        "group_neutralize(((ts_corr(ts_delta(close, 1), ts_delta(ts_delay(close, 1), 1), 250) "
        "* ts_delta(close, 1)) / close), industry) / ts_sum(volume, 5)",
        data,
    )


def alpha049(data: FactorData) -> pd.DataFrame:
    """原式: ((((delay(close,20)-delay(close,10))/10-(delay(close,10)-close)/10))<-0.10)?1:-1)*(-1*(close-delay(close,1)))
    中文: 趋势加速度弱时做反转。
    """
    return evaluate(
        "if_else((((ts_delay(close, 20) - ts_delay(close, 10)) / 10) - ((ts_delay(close, 10) - close) / 10)) < -0.1, 1, -1) "
        "* (-1 * (close - ts_delay(close, 1)))",
        data,
    )


def alpha050(data: FactorData) -> pd.DataFrame:
    """原式: -1*ts_max(rank(correlation(rank(volume),rank(vwap),5)),5)
    中文: 量价排名相关性的5日峰值取负。
    """
    return evaluate("-1 * ts_max(rank(ts_corr(rank(volume), rank(vwap), 5)), 5)", data)


def alpha051(data: FactorData) -> pd.DataFrame:
    """原式: ((((delay(close,20)-delay(close,10))/10-(delay(close,10)-close)/10))<-0.05)?1:-1)*(-1*(close-delay(close,1)))
    中文: alpha049 的 0.05 阈值版本。
    """
    return evaluate(
        "if_else((((ts_delay(close, 20) - ts_delay(close, 10)) / 10) - ((ts_delay(close, 10) - close) / 10)) < -0.05, 1, -1) "
        "* (-1 * (close - ts_delay(close, 1)))",
        data,
    )


def alpha052(data: FactorData) -> pd.DataFrame:
    """原式: ((-1*ts_min(low,5)+delay(ts_min(low,5),5))*rank((sum(returns,240)-sum(returns,20))/220))*ts_rank(volume,5)
    中文: 低价通道变化、长期收益差与量能排名的组合。
    """
    return evaluate(
        "(((-1 * ts_min(low, 5)) + ts_delay(ts_min(low, 5), 5)) "
        "* rank((ts_sum(returns, 240) - ts_sum(returns, 20)) / 220)) * ts_rank(volume, 5)",
        data,
    )


def alpha053(data: FactorData) -> pd.DataFrame:
    """原式: -1*delta((((close-low)-(high-close))/(close-low)),9)
    中文: 收盘在日内区间位置变化的负值。
    """
    return evaluate("-1 * ts_delta(((close - low) - (high - close)) / (close - low), 9)", data)


def alpha054(data: FactorData) -> pd.DataFrame:
    """原式: -1*((low-close)*open^5)/((low-high)*close^5)
    中文: 日内位置与开收盘比的组合（论文高频坑，注意分母）。
    """
    return evaluate("-1 * ((low - close) * (open ** 5)) / ((low - high) * (close ** 5))", data)


def alpha055(data: FactorData) -> pd.DataFrame:
    """原式: -1*correlation(rank((close-ts_min(low,12))/(ts_max(high,12)-ts_min(low,12))),rank(volume),6)
    中文: 价格通道位置与成交量排名的负相关。
    """
    return evaluate(
        "-1 * ts_corr(rank((close - ts_min(low, 12)) / (ts_max(high, 12) - ts_min(low, 12))), rank(volume), 6)",
        data,
    )


def alpha056(data: FactorData) -> pd.DataFrame:
    """原式: 0-(1*(rank(sum(returns,10)/sum(sum(returns,2),3))*rank(returns*cap)))
    中文: 收益结构排名与市值调整收益排名的负值；无 cap 时降级为 rank(returns)。
    """
    if data.cap is None:
        return evaluate("rank(returns)", data)
    return evaluate(
        "0 - (1 * (rank((ts_sum(returns, 10) / ts_sum(ts_sum(returns, 2), 3))) * rank((returns * cap))))",
        data,
    )


def alpha057(data: FactorData) -> pd.DataFrame:
    """原式: 0-(1*((close-vwap)/decay_linear(rank(ts_argmax(close,30)),2)))
    中文: 收盘偏离vwap，用30日高点位置的衰减排名归一化。
    """
    return evaluate("0 - (1 * ((close - vwap) / decay_linear(rank(ts_argmax(close, 30)), 2)))", data)


def alpha058(data: FactorData) -> pd.DataFrame:
    """原式: -1*ts_rank(decay_linear(correlation(vwap,volume,4),8),6)
    中文: vwap与成交量相关性的衰减平滑时序排名。
    """
    return evaluate("-1 * ts_rank(decay_linear(ts_corr(vwap, volume, 4), 8), 6)", data)


def alpha059(data: FactorData) -> pd.DataFrame:
    """原式: -1*ts_rank(decay_linear(correlation(ts_rank(vwap,4),ts_rank(volume,4),4),16),8)
    中文: 量价时序排名相关性的衰减平滑。
    """
    return evaluate(
        "-1 * ts_rank(decay_linear(ts_corr(ts_rank(vwap, 4), ts_rank(volume, 4), 4), 16), 8)", data
    )


def alpha060(data: FactorData) -> pd.DataFrame:
    """原式: 0-(1*((2*scale(rank((((close-low)-(high-close))/(high-low))*volume)))-scale(rank(ts_argmax(close,10)))))
    中文: 日内位置量能与价格高点位置的截面归一化之差。
    """
    return evaluate(
        "0 - (1 * ((2 * scale(rank((((close - low) - (high - close)) / (high - low)) * volume))) "
        "- scale(rank(ts_argmax(close, 10)))))",
        data,
    )


def alpha061(data: FactorData) -> pd.DataFrame:
    """原式: rank(vwap-ts_min(vwap,16))<rank(correlation(vwap,adv180,18))
    中文: vwap通道位置与其长期量能相关性的比较。
    """
    return evaluate("rank(vwap - ts_min(vwap, 16)) < rank(ts_corr(vwap, adv180, 18))", data)


def alpha062(data: FactorData) -> pd.DataFrame:
    """原式: (rank(correlation(vwap,sum(adv20,22),10))<rank((rank(open)+rank(open))<(rank((high+low)/2)+rank(high))))*-1
    中文: vwap量能相关性与开盘/均价排名的比较。
    """
    return evaluate(
        "(rank(ts_corr(vwap, ts_sum(adv20, 22), 10)) "
        "< rank((rank(open) + rank(open)) < (rank((high + low) / 2) + rank(high)))) * -1",
        data,
    )


def alpha063(data: FactorData) -> pd.DataFrame:
    """原式: (rank(decay_linear(delta(IndNeutralize(close,industry),2),8))-rank(decay_linear(correlation(vwap*0.318+open*0.682,sum(adv180,37),13),12)))*-1
    中文: 行业中性收盘变化与量价相关的衰减排名之差。
    """
    return evaluate(
        "(rank(decay_linear(ts_delta(group_neutralize(close, industry), 2), 8)) "
        "- rank(decay_linear(ts_corr((vwap * 0.318108) + (open * (1 - 0.318108)), ts_sum(adv180, 37), 13), 12))) * -1",
        data,
    )


def alpha064(data: FactorData) -> pd.DataFrame:
    """原式: (rank(correlation(sum(open*0.178+low*0.822,12),sum(adv120,12),16))<rank(delta((high+low)/2*0.178+vwap*0.822,3)))*-1
    中文: 加权开低均价与长期量能相关性同价格变化的比较。
    """
    return evaluate(
        "(rank(ts_corr(ts_sum((open * 0.178404) + (low * (1 - 0.178404)), 12), ts_sum(adv120, 12), 16)) "
        "< rank(ts_delta((((high + low) / 2) * 0.178404) + (vwap * (1 - 0.178404)), 3))) * -1",
        data,
    )


def alpha065(data: FactorData) -> pd.DataFrame:
    """原式: (rank(correlation(open*0.008+vwap*0.992,sum(adv60,8),6))<rank(open-ts_min(open,13)))*-1
    中文: 开盘与vwap加权价的量能相关性同开盘通道位置的比较。
    """
    return evaluate(
        "(rank(ts_corr((open * 0.00817205) + (vwap * (1 - 0.00817205)), ts_sum(adv60, 8), 6)) "
        "< rank(open - ts_min(open, 13))) * -1",
        data,
    )


def alpha066(data: FactorData) -> pd.DataFrame:
    """原式: (rank(decay_linear(delta(vwap,3),7))+ts_rank(decay_linear((low-vwap)/(open-(high+low)/2),11),6))*-1
    中文: vwap变化与日内偏离的衰减排名组合。
    """
    return evaluate(
        "(rank(decay_linear(ts_delta(vwap, 3), 7)) "
        "+ ts_rank(decay_linear((((low * 0.96633) + (low * (1 - 0.96633))) - vwap) "
        "/ (open - ((high + low) / 2)), 11), 6)) * -1",
        data,
    )


def alpha067(data: FactorData) -> pd.DataFrame:
    """原式: (rank(high-ts_min(high,2))^rank(correlation(IndNeutralize(vwap,industry),IndNeutralize(adv20,industry),6)))*-1
    中文: 高价通道位置的行业中性量价相关次幂。
    """
    return evaluate(
        "(rank(high - ts_min(high, 2)) ** rank(ts_corr(group_neutralize(vwap, industry), "
        "group_neutralize(adv20, industry), 6))) * -1",
        data,
    )


def alpha068(data: FactorData) -> pd.DataFrame:
    """原式: (ts_rank(correlation(rank(high),rank(adv15),8),5)<rank(delta(close*0.518+low*0.482,1)))*-1
    中文: 高价与量能相关性的时序排名同加权价格变化比较。
    """
    return evaluate(
        "(ts_rank(ts_corr(rank(high), rank(adv15), 8), 5) "
        "< rank(ts_delta((close * 0.518371) + (low * (1 - 0.518371)), 1))) * -1",
        data,
    )


def alpha069(data: FactorData) -> pd.DataFrame:
    """原式: (rank(ts_max(delta(IndNeutralize(vwap,industry),2),4))^ts_rank(correlation(close*0.49+vwap*0.51,adv20,4),9))*-1
    中文: 行业中性vwap变化峰值与量价相关性的次幂。
    """
    return evaluate(
        "(rank(ts_max(ts_delta(group_neutralize(vwap, industry), 2), 4)) "
        "** ts_rank(ts_corr((close * 0.490655) + (vwap * (1 - 0.490655)), adv20, 4), 9)) * -1",
        data,
    )


def alpha070(data: FactorData) -> pd.DataFrame:
    """原式: (rank(delta(vwap,1))^ts_rank(correlation(IndNeutralize(close,industry),adv50,17),17))*-1
    中文: vwap日变化与行业中性收盘量价相关的次幂。
    """
    return evaluate(
        "(rank(ts_delta(vwap, 1)) ** ts_rank(ts_corr(group_neutralize(close, industry), adv50, 17), 17)) * -1",
        data,
    )


def alpha071(data: FactorData) -> pd.DataFrame:
    """原式: max(ts_rank(decay_linear(correlation(ts_rank(close,3),ts_rank(adv180,12),18),4),15),ts_rank(decay_linear(rank((low+open)-(vwap+vwap))^2,16),4))
    中文: 两套衰减量价因子的较大者。
    """
    return evaluate(
        "max(ts_rank(decay_linear(ts_corr(ts_rank(close, 3), ts_rank(adv180, 12), 18), 4), 15), "
        "ts_rank(decay_linear(rank(((low + open) - (vwap + vwap))) ** 2, 16), 4))",
        data,
    )


def alpha072(data: FactorData) -> pd.DataFrame:
    """原式: rank(decay_linear(correlation((high+low)/2,adv40,9),10))/rank(decay_linear(correlation(ts_rank(vwap,4),ts_rank(volume,19),7),3))
    中文: 两条衰减量价相关性的比值。
    """
    return evaluate(
        "rank(decay_linear(ts_corr((high + low) / 2, adv40, 9), 10)) "
        "/ rank(decay_linear(ts_corr(ts_rank(vwap, 4), ts_rank(volume, 19), 7), 3))",
        data,
    )


def alpha073(data: FactorData) -> pd.DataFrame:
    """原式: -max(rank(decay_linear(delta(vwap,4),2)),ts_rank(decay_linear(delta(open*0.147+low*0.853,2)/(open*0.147+low*0.853)*-1,3),16))
    中文: vwap变化与加权开低价格变化的衰减排名。
    """
    return evaluate(
        "-1 * max(rank(decay_linear(ts_delta(vwap, 4), 2)), "
        "ts_rank(decay_linear(ts_delta((open * 0.147155) + (low * (1 - 0.147155)), 2) "
        "/ ((open * 0.147155) + (low * (1 - 0.147155))) * -1, 3), 16))",
        data,
    )


def alpha074(data: FactorData) -> pd.DataFrame:
    """原式: (rank(correlation(close,sum(adv30,37),15))<rank(correlation(rank(high*0.026+vwap*0.974),rank(volume),11)))*-1
    中文: 收盘长期量能相关性与高价加权量价相关的比较。
    """
    return evaluate(
        "(rank(ts_corr(close, ts_sum(adv30, 37), 15)) "
        "< rank(ts_corr(rank((high * 0.0261661) + (vwap * (1 - 0.0261661))), rank(volume), 11))) * -1",
        data,
    )


def alpha075(data: FactorData) -> pd.DataFrame:
    """原式: rank(correlation(vwap,volume,4))<rank(correlation(rank(low),rank(adv50),12))
    中文: vwap量价相关与低价量能相关的比较。
    """
    return evaluate(
        "rank(ts_corr(vwap, volume, 4)) < rank(ts_corr(rank(low), rank(adv50), 12))", data
    )


def alpha076(data: FactorData) -> pd.DataFrame:
    """原式: -max(rank(decay_linear(delta(vwap,1),12)),ts_rank(decay_linear(ts_rank(correlation(low,adv81,8),20),17),19))
    中文: vwap日变化与低价量能相关的衰减排名。
    """
    return evaluate(
        "-1 * max(rank(decay_linear(ts_delta(vwap, 1), 12)), "
        "ts_rank(decay_linear(ts_rank(ts_corr(low, adv81, 8), 20), 17), 19))",
        data,
    )


def alpha077(data: FactorData) -> pd.DataFrame:
    """原式: min(rank(decay_linear(((high+low)/2+high)-(vwap+high),20)),rank(decay_linear(correlation((high+low)/2,adv40,3),6)))
    中文: 均价上影与量价相关的衰减排名取小。
    """
    return evaluate(
        "min(rank(decay_linear((((high + low) / 2) + high) - (vwap + high), 20)), "
        "rank(decay_linear(ts_corr((high + low) / 2, adv40, 3), 6)))",
        data,
    )


def alpha078(data: FactorData) -> pd.DataFrame:
    """原式: rank(correlation(sum(low*0.352+vwap*0.648,20),sum(adv40,20),7))*rank(correlation(rank(vwap),rank(volume),6))
    中文: 加权低vwap价的长期量能相关与短量价相关的乘积。
    """
    return evaluate(
        "rank(ts_corr(ts_sum((low * 0.352233) + (vwap * (1 - 0.352233)), 20), ts_sum(adv40, 20), 7)) "
        "* rank(ts_corr(rank(vwap), rank(volume), 6))",
        data,
    )


def alpha079(data: FactorData) -> pd.DataFrame:
    """原式: rank(correlation(IndNeutralize(close*0.607+open*0.393,industry),adv150,9))<rank(correlation(IndNeutralize(ts_rank(vwap,4),industry),ts_rank(volume,4),13))
    中文: 行业中性加权价量相关与vwap量能时序相关的比较。
    """
    return evaluate(
        "rank(ts_corr(group_neutralize((close * 0.60733) + (open * (1 - 0.60733)), industry), adv150, 9)) "
        "< rank(ts_corr(group_neutralize(ts_rank(vwap, 4), industry), ts_rank(volume, 4), 13))",
        data,
    )


def alpha080(data: FactorData) -> pd.DataFrame:
    """原式: (rank(correlation(ts_rank(open,5),ts_rank(adv60,17),19))<rank(correlation(ts_rank(high,5),ts_rank(volume,17),19)))*-1
    中文: 开盘/最高价时序排名与量能相关的比较。
    """
    return evaluate(
        "(rank(ts_corr(ts_rank(open, 5), ts_rank(adv60, 17), 19)) "
        "< rank(ts_corr(ts_rank(high, 5), ts_rank(volume, 17), 19))) * -1",
        data,
    )


def alpha081(data: FactorData) -> pd.DataFrame:
    """原式: (rank(log(product(rank(rank(correlation(vwap,sum(adv10,49),8))^4),15)))<rank(correlation(rank(vwap),rank(volume),5)))*-1
    中文: 长期vwap量能相关的幂次累积排名与短量价相关比较。
    """
    return evaluate(
        "(rank(log(ts_product(rank(rank(ts_corr(vwap, ts_sum(adv10, 49), 8)) ** 4), 15))) "
        "< rank(ts_corr(rank(vwap), rank(volume), 5))) * -1",
        data,
    )


def alpha082(data: FactorData) -> pd.DataFrame:
    """原式: min(rank(decay_linear(delta(open,1),15)),ts_rank(decay_linear(correlation(IndNeutralize(volume,industry),open,17),7),13))
    中文: 开盘变化与行业中性量能相关的衰减排名。
    """
    return evaluate(
        "min(rank(decay_linear(ts_delta(open, 1), 15)), "
        "ts_rank(decay_linear(ts_corr(group_neutralize(volume, industry), "
        "(open * 0.634196) + (open * (1 - 0.634196)), 17), 7), 13))",
        data,
    )


def alpha083(data: FactorData) -> pd.DataFrame:
    """原式: (rank(delay((high-low)/(sum(close,5)/5),2))*rank(rank(volume)))/(((high-low)/(sum(close,5)/5))/(vwap-close))
    中文: 振幅位置与成交量的组合，用vwap偏离归一化。
    """
    return evaluate(
        "(rank(ts_delay((high - low) / (ts_sum(close, 5) / 5), 2)) * rank(rank(volume))) "
        "/ (((high - low) / (ts_sum(close, 5) / 5)) / (vwap - close))",
        data,
    )


def alpha084(data: FactorData) -> pd.DataFrame:
    """原式: SignedPower(Ts_Rank(vwap-ts_max(vwap,15),20),delta(close,4))
    中文: vwap相对高点的时序排名，用价格变化做指数。
    """
    return evaluate("signedpower(ts_rank(vwap - ts_max(vwap, 15), 20), ts_delta(close, 5))", data)


def alpha085(data: FactorData) -> pd.DataFrame:
    """原式: rank(correlation(high*0.876+close*0.124,adv30,10))^rank(correlation(ts_rank((high+low)/2,4),ts_rank(volume,10),7))
    中文: 高价加权量能相关与均价量能相关的次幂。
    """
    return evaluate(
        "rank(ts_corr((high * 0.876703) + (close * (1 - 0.876703)), adv30, 10)) "
        "** rank(ts_corr(ts_rank((high + low) / 2, 4), ts_rank(volume, 10), 7))",
        data,
    )


def alpha086(data: FactorData) -> pd.DataFrame:
    """原式: (ts_rank(correlation(close,sum(adv20,15),6),20)<rank((open+close)-(vwap+open)))*-1
    中文: 收盘量能相关时序排名与日内位置的比较。
    """
    return evaluate(
        "(ts_rank(ts_corr(close, ts_sum(adv20, 15), 6), 20) "
        "< rank((open + close) - (vwap + open))) * -1",
        data,
    )


def alpha087(data: FactorData) -> pd.DataFrame:
    """原式: -max(rank(decay_linear(delta(close*0.369+vwap*0.631,2),3)),ts_rank(decay_linear(abs(correlation(IndNeutralize(adv81,industry),close,13)),5),14))
    中文: 加权收vwap变化与行业中性量价相关的衰减排名。
    """
    return evaluate(
        "-1 * max(rank(decay_linear(ts_delta((close * 0.369701) + (vwap * (1 - 0.369701)), 2), 3)), "
        "ts_rank(decay_linear(abs(ts_corr(group_neutralize(adv81, industry), close, 13)), 5), 14))",
        data,
    )


def alpha088(data: FactorData) -> pd.DataFrame:
    """原式: min(rank(decay_linear((rank(open)+rank(low))-(rank(high)+rank(close)),8)),ts_rank(decay_linear(correlation(ts_rank(close,8),ts_rank(adv60,20),8),7),3))
    中文: OHLC排名结构与收盘量能相关衰减排名的组合。
    """
    return evaluate(
        "min(rank(decay_linear((rank(open) + rank(low)) - (rank(high) + rank(close)), 8)), "
        "ts_rank(decay_linear(ts_corr(ts_rank(close, 8), ts_rank(adv60, 20), 8), 7), 3))",
        data,
    )


def alpha089(data: FactorData) -> pd.DataFrame:
    """原式: ts_rank(decay_linear(correlation(low,adv10,7),6),4)-ts_rank(decay_linear(correlation(IndNeutralize(vwap,industry),adv30,10),4),7)
    中文: 两条低价/vwap量能相关的衰减排名之差。
    """
    return evaluate(
        "ts_rank(decay_linear(ts_corr(low, adv10, 7), 6), 4) "
        "- ts_rank(decay_linear(ts_corr(group_neutralize(vwap, industry), adv30, 10), 4), 7)",
        data,
    )


def alpha090(data: FactorData) -> pd.DataFrame:
    """原式: (rank(close-ts_max(close,5))^ts_rank(correlation(IndNeutralize(adv40,industry),low,5),3))*-1
    中文: 收盘距5日高点的距离，用量价相关的次幂放大。
    """
    return evaluate(
        "(rank(close - ts_max(close, 5)) "
        "** ts_rank(ts_corr(group_neutralize(adv40, industry), low, 5), 3)) * -1",
        data,
    )


def alpha091(data: FactorData) -> pd.DataFrame:
    """原式: (ts_rank(decay_linear(decay_linear(correlation(IndNeutralize(close,industry),volume,10),17),4),5)<rank(decay_linear(correlation(vwap,sum(adv30,30),5),15)))*-1
    中文: 行业中性收盘量能相关与vwap长期量能相关的衰减排名比较。
    """
    return evaluate(
        "(ts_rank(decay_linear(decay_linear(ts_corr(group_neutralize(close, industry), volume, 10), 17), 4), 5) "
        "< rank(decay_linear(ts_corr(vwap, ts_sum(adv30, 30), 5), 15))) * -1",
        data,
    )


def alpha092(data: FactorData) -> pd.DataFrame:
    """原式: min(ts_rank(decay_linear((((high+low)/2+close)<(low+open)),15),19),ts_rank(decay_linear(correlation(rank(low),rank(adv30),8),7),7))
    中文: 日内位置条件与低价量能相关的衰减排名。
    """
    return evaluate(
        "min(ts_rank(decay_linear((((high + low) / 2) + close) < (low + open), 15), 19), "
        "ts_rank(decay_linear(ts_corr(rank(low), rank(adv30), 8), 7), 7))",
        data,
    )


def alpha093(data: FactorData) -> pd.DataFrame:
    """原式: ts_rank(decay_linear(correlation(IndNeutralize(vwap,industry),adv81,17),20),8)/rank(decay_linear(delta(close*0.524+vwap*0.476,2),17))
    中文: 行业中性vwap量能相关与加权价变化的衰减排名之比。
    """
    return evaluate(
        "ts_rank(decay_linear(ts_corr(group_neutralize(vwap, industry), adv81, 17), 20), 8) "
        "/ rank(decay_linear(ts_delta((close * 0.524434) + (vwap * (1 - 0.524434)), 2), 17))",
        data,
    )


def alpha094(data: FactorData) -> pd.DataFrame:
    """原式: rank((ts_rank(close,5)-ts_rank(close,15))*(-1*returns))
    中文: 短期与长期趋势差乘以负收益（多算子嵌套，注意顺序）。
    """
    return evaluate("rank((ts_rank(close, 5) - ts_rank(close, 15)) * (-1 * returns))", data)


def alpha095(data: FactorData) -> pd.DataFrame:
    """原式: rank(open-ts_min(open,12))<ts_rank(rank(correlation(sum((high+low)/2,19),sum(adv40,19),13))^5,12)
    中文: 开盘通道位置与均价长期量能相关幂次排名的比较。
    """
    return evaluate(
        "rank(open - ts_min(open, 12)) "
        "< ts_rank(rank(ts_corr(ts_sum((high + low) / 2, 19), ts_sum(adv40, 19), 13)) ** 5, 12)",
        data,
    )


def alpha096(data: FactorData) -> pd.DataFrame:
    """原式: -max(ts_rank(decay_linear(correlation(rank(vwap),rank(volume),4),4),8),ts_rank(decay_linear(ts_argmax(correlation(ts_rank(close,7),ts_rank(adv60,4),4),13),14),13))
    中文: vwap量价相关与收盘量能相关峰值的衰减排名。
    """
    return evaluate(
        "-1 * max(ts_rank(decay_linear(ts_corr(rank(vwap), rank(volume), 4), 4), 8), "
        "ts_rank(decay_linear(ts_argmax(ts_corr(ts_rank(close, 7), ts_rank(adv60, 4), 4), 13), 14), 13))",
        data,
    )


def alpha097(data: FactorData) -> pd.DataFrame:
    """原式: -rank(decay_linear(delta(IndNeutralize(low*0.721+vwap*0.279,industry),3),20))
    中文: 行业中性加权低vwap价变化的衰减排名。
    """
    return evaluate(
        "-1 * rank(decay_linear(ts_delta(group_neutralize((low * 0.721001) + (vwap * (1 - 0.721001)), industry), 3), 20))",
        data,
    )


def alpha098(data: FactorData) -> pd.DataFrame:
    """原式: rank(decay_linear(correlation(vwap,sum(adv5,26),5),7))-rank(decay_linear(ts_argmin(correlation(open,sum(adv15,21),9),7),8))
    中文: vwap量能相关与开盘量能相关低点位置的衰减排名差。
    """
    return evaluate(
        "rank(decay_linear(ts_corr(vwap, ts_sum(adv5, 26), 5), 7)) "
        "- rank(decay_linear(ts_argmin(ts_corr(open, ts_sum(adv15, 21), 9), 7), 8))",
        data,
    )


def alpha099(data: FactorData) -> pd.DataFrame:
    """原式: (rank(correlation(sum((high+low)/2,20),sum(adv60,20),9))<rank(correlation(low,volume,6)))*-1
    中文: 均价长期量能相关与低价量价相关的比较。
    """
    return evaluate(
        "(rank(ts_corr(ts_sum((high + low) / 2, 20), ts_sum(adv60, 20), 9)) "
        "< rank(ts_corr(low, volume, 6))) * -1",
        data,
    )


def alpha100(data: FactorData) -> pd.DataFrame:
    """原式: 0-(1*(((1.5*scale(IndNeutralize(IndNeutralize(rank(日内位置*volume),industry),industry)))-scale(IndNeutralize(correlation(close,rank(adv20),5)-rank(ts_argmin(close,30)),industry)))*(volume/adv20)))
    中文: 日内位置量能与价格低点位置的双中性化组合。
    """
    return evaluate(
        "0 - (1 * (((1.5 * scale(group_neutralize(group_neutralize(rank((((close - low) - (high - close)) "
        "/ (high - low)) * volume), industry), industry))) "
        "- scale(group_neutralize(ts_corr(close, rank(adv20), 5) - rank(ts_argmin(close, 30)), industry))) "
        "* (volume / adv20)))",
        data,
    )


def alpha101(data: FactorData) -> pd.DataFrame:
    """原式: (close-open)/((high-low)+0.001)
    中文: 日内实体占振幅的比例。
    """
    return evaluate("(close - open) / ((high - low) + 0.001)", data)


# ==================== 统一入口 ====================
ALPHA_FUNCS: List[Callable[[FactorData], pd.DataFrame]] = [
    alpha001, alpha002, alpha003, alpha004, alpha005, alpha006, alpha007, alpha008, alpha009, alpha010,
    alpha011, alpha012, alpha013, alpha014, alpha015, alpha016, alpha017, alpha018, alpha019, alpha020,
    alpha021, alpha022, alpha023, alpha024, alpha025, alpha026, alpha027, alpha028, alpha029, alpha030,
    alpha031, alpha032, alpha033, alpha034, alpha035, alpha036, alpha037, alpha038, alpha039, alpha040,
    alpha041, alpha042, alpha043, alpha044, alpha045, alpha046, alpha047, alpha048, alpha049, alpha050,
    alpha051, alpha052, alpha053, alpha054, alpha055, alpha056, alpha057, alpha058, alpha059, alpha060,
    alpha061, alpha062, alpha063, alpha064, alpha065, alpha066, alpha067, alpha068, alpha069, alpha070,
    alpha071, alpha072, alpha073, alpha074, alpha075, alpha076, alpha077, alpha078, alpha079, alpha080,
    alpha081, alpha082, alpha083, alpha084, alpha085, alpha086, alpha087, alpha088, alpha089, alpha090,
    alpha091, alpha092, alpha093, alpha094, alpha095, alpha096, alpha097, alpha098, alpha099, alpha100,
    alpha101,
]


def get_alpha_list() -> List[Callable[[FactorData], pd.DataFrame]]:
    """返回全部 101 个 alpha 函数（顺序即编号）。"""
    return list(ALPHA_FUNCS)


def get_builtin_alpha(n: int) -> Callable[[FactorData], pd.DataFrame]:
    """按编号 1~101 取单个 alpha 函数。"""
    n = int(n)
    if not 1 <= n <= 101:
        raise ValueError(f"alpha 编号必须在 1~101 之间，收到 {n}")
    return ALPHA_FUNCS[n - 1]
