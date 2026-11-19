"""因子表达式引擎（第 5 步 5.9.1）。

输入一行字符串公式（如 ``rank(ts_corr(close, volume, 10))``）与 FactorData，
输出「日期×股票」面板 DataFrame。覆盖 Alpha101 / Alpha191 的全部算子。

防未来函数硬约束
----------------
所有时间序列算子一律先 ``x.shift(1)`` 再 ``rolling(d)``：
窗口为 ``[i-d, i-1]``，**绝不包含当日 i**。例如::

    ts_corr(x, y, d) -> x.shift(1).rolling(d).corr(y.shift(1))

``ts_delta(x, d)`` 同理写成 ``x.shift(1) - x.shift(1+d)``，
即「昨日 - (d+1)日前」，而不是论文里包含当日的 ``x - x.shift(d)``。

其它约定
--------
* 除零/分母为 0：返回 NaN，绝不返回 inf；
* 窗口内 NaN 超过 20%：返回 NaN，不强行填充；
* 全部用 pandas/numpy 向量化实现。
"""
from __future__ import annotations

import ast
import logging
import math
from functools import lru_cache
from typing import Callable, Dict, Optional, Union

import numpy as np
import pandas as pd

from .base import FactorData

logger = logging.getLogger(__name__)

__all__ = ["evaluate", "OPERATORS", "ExpressionError"]

Panel = pd.DataFrame


class ExpressionError(ValueError):
    """表达式语法/算子错误。"""


# ==================== 通用小工具 ====================
def _to_panel(v, like: Panel) -> Panel:
    """把标量/Series 广播成与 like 同形状的面板。"""
    if isinstance(v, Panel):
        return v.reindex(index=like.index, columns=like.columns)
    if isinstance(v, pd.Series):
        return pd.DataFrame(np.repeat(v.values.reshape(1, -1), len(like), axis=0),
                            index=like.index, columns=like.columns)
    return Panel(float(v), index=like.index, columns=like.columns)


def _clean(v):
    """把 bool 转 float、inf 转 NaN（除零保护的最后一道闸）。"""
    if isinstance(v, Panel):
        if v.dtypes.eq(bool).any():
            v = v.astype(float)
        return v.replace([np.inf, -np.inf], np.nan)
    if isinstance(v, pd.Series):
        return v.replace([np.inf, -np.inf], np.nan)
    if isinstance(v, (float, np.floating)) and not np.isfinite(v):
        return np.nan
    return v


def _min_periods(d: int) -> int:
    """窗口内 NaN 超过 20% 则 NaN：等价于至少 ceil(0.8*d) 个有效值。"""
    return max(1, int(math.ceil(float(d) * 0.8)))


def _check_window(d) -> int:
    d = int(d)
    if d < 1:
        raise ExpressionError(f"时间窗口必须 >=1，收到 {d}")
    return d


def _shifted(x: Panel, n: int = 1) -> Panel:
    """统一的历史位移入口：n>=1，保证不碰当日。"""
    n = int(n)
    if n < 1:
        raise ExpressionError(f"shift/delay 窗口必须 >=1（禁止取当日或未来），收到 {n}")
    return x.shift(n)


# ==================== 截面算子 ====================
def rank(x: Panel) -> Panel:
    """截面排名到 [0,1]。"""
    return x.rank(axis=1, pct=True)


def zscore(x: Panel) -> Panel:
    """截面标准化：(x - 截面均值) / 截面标准差。"""
    mu = x.mean(axis=1)
    sd = x.std(axis=1, ddof=1)
    out = x.sub(mu, axis=0).div(sd.replace(0.0, np.nan), axis=0)
    return _clean(out)


def scale(x: Panel, a: float = 1.0) -> Panel:
    """截面归一化：x * a / sum(|x|)，使截面绝对值之和为 a。"""
    denom = x.abs().sum(axis=1).replace(0.0, np.nan)
    return _clean(x.mul(float(a), axis=0).div(denom, axis=0))


# ==================== 时间序列算子（全部不含当日） ====================
def ts_mean(x: Panel, d: int) -> Panel:
    d = _check_window(d)
    return x.shift(1).rolling(d, min_periods=_min_periods(d)).mean()


def ts_std(x: Panel, d: int) -> Panel:
    d = _check_window(d)
    return x.shift(1).rolling(d, min_periods=_min_periods(d)).std(ddof=1)


def ts_sum(x: Panel, d: int) -> Panel:
    d = _check_window(d)
    return x.shift(1).rolling(d, min_periods=_min_periods(d)).sum()


def ts_rank(x: Panel, d: int) -> Panel:
    """d 日窗口内排名（百分位）；窗口为 [i-d, i-1]。"""
    d = _check_window(d)
    return x.shift(1).rolling(d, min_periods=_min_periods(d)).rank(pct=True)


def ts_max(x: Panel, d: int) -> Panel:
    d = _check_window(d)
    return x.shift(1).rolling(d, min_periods=_min_periods(d)).max()


def ts_min(x: Panel, d: int) -> Panel:
    d = _check_window(d)
    return x.shift(1).rolling(d, min_periods=_min_periods(d)).min()


def _rolling_arg(x: Panel, d: int, which: str) -> Panel:
    """d 日窗口内最大值/最小值的位置（1 基，越大越靠后）。

    用 numpy 按日期循环（每次只处理一日全市场），避免 rolling.apply 的 Python 开销。
    """
    d = _check_window(d)
    arr = x.shift(1).to_numpy(dtype=float)
    out = np.full(arr.shape, np.nan, dtype=float)
    mp = _min_periods(d)
    t_len = arr.shape[0]
    for i in range(d - 1, t_len):
        win = arr[i - d + 1: i + 1, :]          # 不含当日 i：已 shift(1)
        cnt = np.sum(~np.isnan(win), axis=0)
        if which == "argmax":
            filled = np.where(np.isnan(win), -np.inf, win)
            pos = np.argmax(filled, axis=0) + 1.0
        else:
            filled = np.where(np.isnan(win), np.inf, win)
            pos = np.argmin(filled, axis=0) + 1.0
        pos[cnt < mp] = np.nan
        out[i, :] = pos
    return Panel(out, index=x.index, columns=x.columns)


def ts_argmax(x: Panel, d: int) -> Panel:
    return _rolling_arg(x, d, "argmax")


def ts_argmin(x: Panel, d: int) -> Panel:
    return _rolling_arg(x, d, "argmin")


def ts_corr(x: Panel, y: Panel, d: int) -> Panel:
    """d 日滚动相关系数；窗口 [i-d, i-1]，不含当日。"""
    d = _check_window(d)
    xs, ys = x.shift(1), y.shift(1)
    out = xs.rolling(d, min_periods=_min_periods(d)).corr(ys)
    return _clean(out)


def ts_cov(x: Panel, y: Panel, d: int) -> Panel:
    d = _check_window(d)
    xs, ys = x.shift(1), y.shift(1)
    out = xs.rolling(d, min_periods=_min_periods(d)).cov(ys)
    return _clean(out)


def ts_delta(x: Panel, d: int) -> Panel:
    """x.shift(1) - x.shift(1+d)：严格使用昨日及更早，不碰当日。"""
    d = _check_window(d)
    return _clean(x.shift(1) - x.shift(1 + d))


def ts_delay(x: Panel, d: int) -> Panel:
    """d 日前的值（d>=1）；shift(x,d) 的别名。"""
    return _shifted(x, d)


def ts_momentum(x: Panel, d: int) -> Panel:
    """过去 d 日涨跌幅：x.shift(1)/x.shift(1+d) - 1（不含当日）。"""
    d = _check_window(d)
    prev = x.shift(1 + d).replace(0.0, np.nan)
    return _clean(x.shift(1) / prev - 1.0)


def decay_linear(x: Panel, d: int) -> Panel:
    """线性衰减加权平均，越近权重越大（权重 1..d，作用于 shift(1) 后窗口）。"""
    d = _check_window(d)
    arr = x.shift(1).to_numpy(dtype=float)
    out = np.full(arr.shape, np.nan, dtype=float)
    w = np.arange(1, d + 1, dtype=float)
    mp = _min_periods(d)
    for i in range(d - 1, arr.shape[0]):
        win = arr[i - d + 1: i + 1, :]
        mask = ~np.isnan(win)
        cnt = mask.sum(axis=0)
        wsum = (w[:, None] * mask).sum(axis=0)
        vals = np.where(mask, win, 0.0)
        res = (vals * w[:, None]).sum(axis=0) / np.where(wsum == 0, np.nan, wsum)
        res[cnt < mp] = np.nan
        out[i, :] = res
    return Panel(out, index=x.index, columns=x.columns)


def product(x: Panel, d: int) -> Panel:
    """d 日滚动乘积（不含当日），NaN 超过 20% 返回 NaN。"""
    d = _check_window(d)
    arr = x.shift(1).to_numpy(dtype=float)
    out = np.full(arr.shape, np.nan, dtype=float)
    mp = _min_periods(d)
    for i in range(d - 1, arr.shape[0]):
        win = arr[i - d + 1: i + 1, :]
        cnt = np.sum(~np.isnan(win), axis=0)
        res = np.nanprod(win, axis=0)
        res[cnt < mp] = np.nan
        out[i, :] = res
    return Panel(out, index=x.index, columns=x.columns)


# ==================== 截面逐元素算子 ====================
def sign(x: Panel) -> Panel:
    return _clean(np.sign(x))


def abs_(x: Panel) -> Panel:
    return x.abs()


def log(x: Panel) -> Panel:
    """自然对数；<=0 返回 NaN。"""
    return _clean(np.log(x.where(x > 0)))


def signedpower(x: Panel, a=1.0) -> Panel:
    """sign(x) * |x|^a；a 可以是标量或同形面板，负底数不会产生复数。"""
    expo = a.reindex(index=x.index, columns=x.columns) if isinstance(a, Panel) else float(a)
    return _clean(np.sign(x) * np.power(np.abs(x), expo))


def max_(a, b) -> Panel:
    if isinstance(a, Panel) or isinstance(b, Panel):
        like = a if isinstance(a, Panel) else b
        aa, bb = _to_panel(a, like), _to_panel(b, like)
        return _clean(np.maximum(aa, bb))
    return max(a, b)


def min_(a, b) -> Panel:
    if isinstance(a, Panel) or isinstance(b, Panel):
        like = a if isinstance(a, Panel) else b
        aa, bb = _to_panel(a, like), _to_panel(b, like)
        return _clean(np.minimum(aa, bb))
    return min(a, b)


def if_else(cond, a, b) -> Panel:
    """条件选择；cond 为 NaN 时按 False 处理。"""
    if isinstance(cond, Panel):
        like = cond
        cond_bool = cond.fillna(False).astype(bool)
    else:
        like = a if isinstance(a, Panel) else b
        cond_bool = _to_panel(bool(cond), like).astype(bool)
    aa = _to_panel(a, like)
    bb = _to_panel(b, like)
    return _clean(aa.where(cond_bool, bb))


# ==================== 分组算子 ====================
def _group_rows(x: Panel, group: Optional[Panel], func: str) -> Panel:
    """按日按行业分组；group 缺失时降级为全市场截面。"""
    if group is None:
        if func == "rank":
            return rank(x)
        # 无行业：全市场去均值（中性化降级）
        return _clean(x.sub(x.mean(axis=1), axis=0))
    out = Panel(np.nan, index=x.index, columns=x.columns)
    for dt in x.index:
        row = x.loc[dt]
        if dt not in group.index:
            continue
        grp = group.loc[dt].reindex(x.columns)
        if func == "rank":
            out.loc[dt] = row.groupby(grp).rank(pct=True)
        else:
            gm = row.groupby(grp).transform("mean")
            out.loc[dt] = row - gm
    return _clean(out)


def group_rank(x: Panel, group: Optional[Panel] = None) -> Panel:
    """行业内截面排名；无行业数据时 fallback 到全市场 rank。"""
    return _group_rows(x, group, "rank")


def group_neutralize(x: Panel, group: Optional[Panel] = None) -> Panel:
    """行业内去均值取残差；无行业数据时降级为全市场去均值。"""
    return _group_rows(x, group, "neutralize")


# ==================== 算子注册表 ====================
OPERATORS: Dict[str, Callable] = {
    # 截面
    "rank": rank,
    "zscore": zscore,
    "scale": scale,
    # 时序（全部不含当日）
    "ts_mean": ts_mean,
    "ts_std": ts_std,
    "ts_sum": ts_sum,
    "ts_rank": ts_rank,
    "ts_max": ts_max,
    "ts_min": ts_min,
    "ts_argmax": ts_argmax,
    "ts_argmin": ts_argmin,
    "ts_corr": ts_corr,
    "ts_cov": ts_cov,
    "ts_delta": ts_delta,
    "ts_delay": ts_delay,
    "shift": ts_delay,
    "ts_momentum": ts_momentum,
    "decay_linear": decay_linear,
    "product": product,
    "ts_product": product,
    # 逐元素
    "sign": sign,
    "abs": abs_,
    "log": log,
    "signedpower": signedpower,
    "max": max_,
    "min": min_,
    "if_else": if_else,
    # 分组
    "group_rank": group_rank,
    "group_neutralize": group_neutralize,
    # ---- Alpha101/191 论文里的别名（统一映射到上面实现，不另写分支）----
    "correlation": ts_corr,
    "corr": ts_corr,
    "covariance": ts_cov,
    "cov": ts_cov,
    "delta": ts_delta,
    "delay": ts_delay,
    "stddev": ts_std,
    "std": ts_std,
    "mean": ts_mean,
    "sum": ts_sum,
    "ts_maximum": ts_max,
    "ts_minimum": ts_min,
    "wma": decay_linear,
    "decaylinear": decay_linear,
    "indneutralize": group_neutralize,
    "power": signedpower,
}

# 可直接作为变量名读取的面板字段
_BASE_FIELDS = {"close", "open", "high", "low", "volume", "amount", "vwap",
                "returns", "cap", "industry"}


@lru_cache(maxsize=512)
def _parse(expr: str) -> ast.Expression:
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"表达式语法错误: {expr!r} -> {exc}") from exc
    return tree


def _eval_node(node: ast.AST, env: Dict[str, object]):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, env)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, bool)):
            return node.value
        raise ExpressionError(f"不支持的常量: {node.value!r}")
    if isinstance(node, ast.Name):
        key = node.id.lower()
        if key in env:
            return env[key]
        raise ExpressionError(f"未知字段: {node.id}")
    if isinstance(node, ast.UnaryOp):
        val = _eval_node(node.operand, env)
        if isinstance(node.op, ast.USub):
            return _clean(-val)
        if isinstance(node.op, ast.UAdd):
            return val
        if isinstance(node.op, ast.Invert):
            return ~_to_panel(val, _like(env)) if not isinstance(val, Panel) else ~val.astype(bool)
        if isinstance(node.op, ast.Not):
            return ~val
        raise ExpressionError("不支持的一元运算")
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, env)
        right = _eval_node(node.right, env)
        op = node.op
        if isinstance(left, Panel) or isinstance(right, Panel):
            like = left if isinstance(left, Panel) else right
            left = _to_panel(left, like)
            right = _to_panel(right, like)
        if isinstance(op, ast.Add):
            return _clean(left + right)
        if isinstance(op, ast.Sub):
            return _clean(left - right)
        if isinstance(op, ast.Mult):
            return _clean(left * right)
        if isinstance(op, ast.Div):
            return _clean(left / right.replace(0.0, np.nan) if isinstance(right, Panel) else left / right)
        if isinstance(op, ast.Pow):
            return _clean(np.power(left, right))
        if isinstance(op, ast.Mod):
            return _clean(left % right)
        if isinstance(op, ast.BitAnd):
            return left.astype(bool) & right.astype(bool)
        if isinstance(op, ast.BitOr):
            return left.astype(bool) | right.astype(bool)
        raise ExpressionError("不支持的二元运算")
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, env)
        result = None
        for op, comp in zip(node.ops, node.comparators):
            right = _eval_node(comp, env)
            if isinstance(left, Panel) or isinstance(right, Panel):
                like = left if isinstance(left, Panel) else right
                l, r = _to_panel(left, like), _to_panel(right, like)
            else:
                l, r = left, right
            if isinstance(op, ast.Gt):
                cur = l > r
            elif isinstance(op, ast.GtE):
                cur = l >= r
            elif isinstance(op, ast.Lt):
                cur = l < r
            elif isinstance(op, ast.LtE):
                cur = l <= r
            elif isinstance(op, ast.Eq):
                cur = l == r
            elif isinstance(op, ast.NotEq):
                cur = l != r
            else:
                raise ExpressionError("不支持的比较运算")
            result = cur if result is None else (result & cur)
            left = right
        return result
    if isinstance(node, ast.IfExp):
        cond = _eval_node(node.test, env)
        a = _eval_node(node.body, env)
        b = _eval_node(node.orelse, env)
        return if_else(cond, a, b)
    if isinstance(node, ast.BoolOp):
        vals = [_eval_node(v, env) for v in node.values]
        out = vals[0]
        for v in vals[1:]:
            out = (out & v) if isinstance(node.op, ast.And) else (out | v)
        return out
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ExpressionError("只允许调用白名单算子")
        fname = node.func.id.lower()
        func = OPERATORS.get(fname)
        if func is None:
            raise ExpressionError(f"未知算子: {node.func.id}")
        args = [_eval_node(a, env) for a in node.args]
        if any(isinstance(a, ast.Starred) for a in node.args):
            raise ExpressionError("不支持 *args")
        return _clean(func(*args))
    raise ExpressionError(f"不支持的表达式节点: {type(node).__name__}")


def _like(env: Dict[str, object]) -> Panel:
    for key in ("close", "open", "high", "low", "volume"):
        if isinstance(env.get(key), Panel):
            return env[key]
    raise ExpressionError("缺少基础面板字段")


def _build_env(data: FactorData, expr: str) -> Dict[str, object]:
    env: Dict[str, object] = {
        "close": data.close,
        "open": data.open,
        "high": data.high,
        "low": data.low,
        "volume": data.volume,
        "amount": data.amount,
        "vwap": data.vwap,
        "returns": data.returns,
        "cap": data.cap,
        "industry": data.industry,
    }
    # adv{d} 自动展开为 d 日平均成交量（不含当日）
    import re

    for token in set(re.findall(r"\badv(\d+)\b", expr, flags=re.I)):
        d = int(token)
        env[f"adv{token}"] = ts_mean(data.volume, d)
    return env


def evaluate(expr: str, data: FactorData) -> Panel:
    """计算因子表达式，返回「日期×股票」面板。

    示例::

        evaluate("rank(ts_corr(close, volume, 10))", data)
    """
    if not isinstance(expr, str) or not expr.strip():
        raise ExpressionError("表达式必须是非空字符串")
    tree = _parse(expr.strip())
    env = _build_env(data, expr)
    # 把大写函数名/字段名统一成小写（Alpha191 公开公式常全大写）
    result = _eval_node(tree, env)
    if not isinstance(result, Panel):
        result = _to_panel(result, data.close)
    if result.dtypes.eq(bool).any():
        result = result.astype(float)
    result = _clean(result)
    # 对齐到 close 面板，避免广播产生的额外行列
    return result.reindex(index=data.close.index, columns=data.close.columns)
