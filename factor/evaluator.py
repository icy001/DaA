"""因子评估套件（第 5 步 5.9.7）。

包含：
  * calc_ic            单因子 IC/ICIR/胜率/IC 序列；
  * calc_ic_decay      1/3/5/10/20 日 IC 衰减；
  * quantile_backtest  分层回测 + 多空净值 + 单调性；
  * calc_factor_correlation 因子相关性矩阵与冗余对；
  * calc_turnover      多头组合换手率；
  * generate_factor_report 一键 HTML/PNG 报告（matplotlib Agg，无中文字体自动英文）。

约定：传入的 ``returns`` 是「日收益」面板，内部统一 shift(-1) 得到次日收益；
``factor_values`` 是「日期×股票」因子面板。
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:  # 项目统一年化口径，导入失败时退回 244
    from config import INDICATOR_CONFIG

    ANNUAL_DAYS = int(INDICATOR_CONFIG.get("annual_trading_days", 244))
except Exception:  # pragma: no cover
    ANNUAL_DAYS = 244

__all__ = [
    "calc_ic",
    "calc_ic_decay",
    "quantile_backtest",
    "calc_factor_correlation",
    "calc_turnover",
    "generate_factor_report",
]


def _spearman(a: pd.Series, b: pd.Series) -> float:
    valid = a.notna() & b.notna()
    if valid.sum() < 3:
        return np.nan
    try:
        return float(a[valid].corr(b[valid], method="spearman"))
    except Exception:
        return np.nan


def _forward_return(returns: pd.DataFrame, period: int = 1) -> pd.DataFrame:
    """未来 period 日收益：t 日 -> (t+1 ... t+period) 的复利收益。"""
    if period <= 1:
        return returns.shift(-1)
    gross = (1.0 + returns).rolling(period).apply(np.prod, raw=True)
    return gross.shift(-period) - 1.0


def _ic_series(factor_values: pd.DataFrame, fwd: pd.DataFrame) -> pd.Series:
    idx = factor_values.index.intersection(fwd.index)
    cols = factor_values.columns.intersection(fwd.columns)
    f = factor_values.loc[idx, cols]
    r = fwd.loc[idx, cols]
    vals = {}
    for dt in idx:
        ic = _spearman(f.loc[dt], r.loc[dt])
        if np.isfinite(ic):
            vals[dt] = ic
    return pd.Series(vals, dtype=float).sort_index()


def calc_ic(
    factor_values: pd.DataFrame,
    forward_returns: pd.DataFrame,
    method: str = "spearman",
) -> Dict[str, object]:
    """单因子 IC 分析（默认 Spearman 秩相关）。

    返回 dict：ic_mean / ic_std / icir / ic_win_rate / ic_series /
    ic_abs_gt_002 / n_periods。
    """
    method = (method or "spearman").lower()
    if method != "spearman":
        # 仍用 spearman 计算，保留参数兼容；Pearson 对极端值敏感，不推荐
        logger.warning("calc_ic 目前固定使用 spearman，忽略 method=%s", method)
    ic = _ic_series(factor_values, _forward_return(forward_returns, 1))
    if ic.empty:
        return {
            "ic_mean": np.nan, "ic_std": np.nan, "icir": np.nan, "ic_win_rate": np.nan,
            "ic_series": ic, "ic_abs_gt_002": np.nan, "n_periods": 0,
        }
    mean = float(ic.mean())
    std = float(ic.std(ddof=1)) if len(ic) > 1 else 0.0
    # IC 序列无波动（如因子恰好等于次日收益，IC 恒为 1）时 ICIR 数学上无定义，
    # 统一置 0 以便下游排序/绘图，不返回 inf/nan。
    icir = mean / std if std and np.isfinite(std) and std > 1e-12 else 0.0
    return {
        "ic_mean": mean,
        "ic_std": std,
        "icir": float(icir),
        "ic_win_rate": float((ic > 0).mean()),
        "ic_series": ic,
        "ic_abs_gt_002": float((ic.abs() > 0.02).mean()),
        "n_periods": int(len(ic)),
    }


def calc_ic_decay(
    factor_values: pd.DataFrame,
    returns: pd.DataFrame,
    periods: Sequence[int] = (1, 3, 5, 10, 20),
) -> Dict[str, object]:
    """因子对未来 1/3/5/10/20 日收益的 IC 衰减。"""
    curve = {}
    series = {}
    for p in periods:
        fwd = _forward_return(returns, int(p))
        ic = _ic_series(factor_values, fwd)
        curve[int(p)] = float(ic.mean()) if not ic.empty else np.nan
        series[int(p)] = ic
    valid = {k: v for k, v in curve.items() if np.isfinite(v)}
    best = max(valid, key=lambda k: abs(valid[k])) if valid else None
    return {"ic_decay": curve, "ic_series": series, "best_period": best}


def _max_drawdown(nav: pd.Series) -> float:
    if nav.empty:
        return np.nan
    peak = nav.cummax()
    return float((nav / peak - 1.0).min())


def _perf(nav: pd.Series) -> Dict[str, float]:
    nav = nav.dropna()
    if len(nav) < 2:
        return {"annual_return": np.nan, "sharpe": np.nan, "max_drawdown": np.nan}
    rets = nav.pct_change().dropna()
    periods = max(len(nav) - 1, 1)
    annual = float(nav.iloc[-1] ** (ANNUAL_DAYS / periods) - 1.0) if nav.iloc[-1] > 0 else np.nan
    sd = float(rets.std(ddof=1)) if len(rets) > 1 else 0.0
    sharpe = float(rets.mean() / sd * math.sqrt(ANNUAL_DAYS)) if sd > 0 else np.nan
    return {"annual_return": annual, "sharpe": sharpe,
            "max_drawdown": _max_drawdown(nav)}


def quantile_backtest(
    factor_values: pd.DataFrame,
    returns: pd.DataFrame,
    n_groups: int = 5,
) -> Dict[str, object]:
    """按因子值分 n_groups 组，计算每组年化/夏普/最大回撤 + 多空净值 + 单调性。"""
    n_groups = int(n_groups)
    if n_groups < 2:
        raise ValueError("n_groups 必须 >=2")
    idx = factor_values.index.intersection(returns.index)
    cols = factor_values.columns.intersection(returns.columns)
    f = factor_values.loc[idx, cols]
    fwd = returns.loc[idx, cols].shift(-1)

    rows = {}
    for dt in idx:
        fv = f.loc[dt].dropna()
        if fv.empty:
            continue
        fv = fv[~fv.duplicated()]
        if len(fv) < n_groups * 2:
            continue
        rv = fwd.loc[dt].reindex(fv.index)
        valid = rv.notna()
        if valid.sum() < n_groups * 2:
            continue
        ranks = fv[valid].rank(method="first")
        try:
            groups = pd.qcut(ranks, n_groups, labels=False)
        except ValueError:
            continue
        gret = rv[valid].groupby(groups).mean()
        rows[dt] = gret
    group_returns = pd.DataFrame.from_dict(rows, orient="index").sort_index()
    group_returns.columns = [f"Q{int(c) + 1}" for c in group_returns.columns]

    perf = {}
    navs = {}
    for col in group_returns.columns:
        gr = group_returns[col].fillna(0.0)
        nav = (1.0 + gr).cumprod()
        navs[col] = nav
        perf[col] = _perf(nav)
        perf[col]["mean_return"] = float(gr.mean()) if len(gr) else np.nan

    if group_returns.shape[1] >= 2:
        ls = group_returns.iloc[:, -1].fillna(0.0) - group_returns.iloc[:, 0].fillna(0.0)
    else:
        ls = pd.Series(dtype=float)
    ls_nav = (1.0 + ls).cumprod() if len(ls) else pd.Series(dtype=float)
    ls_perf = _perf(ls_nav)

    # 单调性：组序号与组年化收益的秩相关
    annuals = [perf[c]["annual_return"] for c in group_returns.columns]
    valid = [(i, v) for i, v in enumerate(annuals) if np.isfinite(v)]
    mono_flag = False
    direction = "none"
    if len(valid) >= 3:
        xs = pd.Series([i for i, _ in valid])
        ys = pd.Series([v for _, v in valid])
        rho = xs.corr(ys, method="spearman")
        if np.isfinite(rho) and abs(rho) >= 0.8:
            mono_flag = True
            direction = "increasing" if rho > 0 else "decreasing"

    return {
        "group_returns": group_returns,
        "group_nav": pd.DataFrame(navs),
        "group_performance": perf,
        "long_short": {"nav": ls_nav, **ls_perf},
        "long_short_nav": ls_nav,
        "monotonic": mono_flag,
        "monotonic_direction": direction,
        "n_periods": int(len(group_returns)),
    }


def calc_factor_correlation(
    factor_dict: Dict[str, pd.DataFrame],
    threshold: float = 0.7,
) -> Dict[str, object]:
    """两两因子的截面平均相关系数矩阵 + 冗余对（|corr|>threshold）。"""
    names = list(factor_dict)
    mat = pd.DataFrame(np.eye(len(names)), index=names, columns=names, dtype=float)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            fa, fb = factor_dict[a], factor_dict[b]
            idx = fa.index.intersection(fb.index)
            cols = fa.columns.intersection(fb.columns)
            if len(idx) == 0 or len(cols) == 0:
                corr = np.nan
            else:
                try:
                    corr = fa.loc[idx, cols].corrwith(fb.loc[idx, cols], axis=1).mean()
                except Exception:
                    corr = np.nan
            mat.loc[a, b] = mat.loc[b, a] = float(corr) if np.isfinite(corr) else np.nan

    redundant: List[Tuple[str, str, float]] = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            c = mat.loc[a, b]
            if np.isfinite(c) and abs(c) > threshold:
                redundant.append((a, b, float(c)))
    redundant.sort(key=lambda x: abs(x[2]), reverse=True)
    return {"corr_matrix": mat, "redundant_pairs": redundant, "threshold": threshold}


def calc_turnover(
    factor_values: pd.DataFrame,
    top_pct: float = 0.2,
) -> Dict[str, object]:
    """多头（因子最高 top_pct）组合的每日换手率。"""
    if not 0 < top_pct <= 1:
        raise ValueError("top_pct 必须在 (0,1]")
    prev = None
    turnovers = {}
    for dt in factor_values.index:
        row = factor_values.loc[dt].dropna()
        if len(row) < 3:
            continue
        k = max(1, int(math.ceil(len(row) * top_pct)))
        top = set(row.nlargest(k).index)
        if prev is not None:
            turnovers[dt] = 1.0 - len(top & prev) / max(len(top), 1)
        prev = top
    ts = pd.Series(turnovers, dtype=float).sort_index()
    mean_to = float(ts.mean()) if len(ts) else np.nan
    return {
        "turnover_series": ts,
        "mean_turnover": mean_to,
        "high_turnover_warning": bool(np.isfinite(mean_to) and mean_to > 0.3),
    }


# ==================== 报告生成 ====================
def _has_cjk_font() -> bool:
    try:
        from matplotlib import font_manager

        names = {f.name for f in font_manager.fontManager.ttflist}
        return any(n in names for n in ("SimHei", "Microsoft YaHei", "PingFang SC",
                                        "Arial Unicode MS", "Heiti SC", "Noto Sans CJK SC"))
    except Exception:
        return False


def generate_factor_report(
    factor_name: str,
    save_dir: str = "research_output/factor_reports",
    factor_values: Optional[pd.DataFrame] = None,
    returns: Optional[pd.DataFrame] = None,
    factor_dict: Optional[Dict[str, pd.DataFrame]] = None,
) -> Path:
    """生成 HTML + PNG 因子报告；无数据时也生成占位报告，不崩溃。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir = Path(save_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cjk = _has_cjk_font()
    if not cjk:
        plt.rcParams["font.family"] = "DejaVu Sans"
    plt.rcParams["axes.unicode_minus"] = False

    L = (lambda zh, en: zh) if cjk else (lambda zh, en: en)

    ic_res = ic_decay = qres = corr_res = None
    if factor_values is not None and returns is not None:
        ic_res = calc_ic(factor_values, returns)
        ic_decay = calc_ic_decay(factor_values, returns)
        qres = quantile_backtest(factor_values, returns)
    if factor_dict is not None:
        corr_res = calc_factor_correlation(factor_dict)

    images = []

    def save(fig, name):
        path = out_dir / f"{factor_name}_{name}.png"
        fig.tight_layout()
        fig.savefig(path, dpi=120)
        plt.close(fig)
        images.append(path.name)

    # IC 序列
    fig, ax = plt.subplots(figsize=(8, 3))
    if ic_res is not None and len(ic_res["ic_series"]):
        s = ic_res["ic_series"]
        ax.bar(range(len(s)), s.values)
        ax.axhline(0, color="black", lw=0.8)
    else:
        ax.text(0.5, 0.5, "No IC data", ha="center", va="center")
    ax.set_title(L("IC 时间序列", "IC Series"))
    save(fig, "ic")

    # IC 分布
    fig, ax = plt.subplots(figsize=(5, 3))
    if ic_res is not None and len(ic_res["ic_series"]):
        ax.hist(ic_res["ic_series"].values, bins=20)
    else:
        ax.text(0.5, 0.5, "No IC data", ha="center", va="center")
    ax.set_title(L("IC 分布", "IC Distribution"))
    save(fig, "ic_hist")

    # IC 衰减
    fig, ax = plt.subplots(figsize=(5, 3))
    if ic_decay is not None:
        curve = ic_decay["ic_decay"]
        ax.plot(list(curve), list(curve.values()), marker="o")
    else:
        ax.text(0.5, 0.5, "No decay data", ha="center", va="center")
    ax.set_title(L("IC 衰减", "IC Decay"))
    ax.set_xlabel(L("持有期(天)", "Horizon (days)"))
    save(fig, "ic_decay")

    # 分层净值
    fig, ax = plt.subplots(figsize=(8, 3))
    if qres is not None and not qres["group_nav"].empty:
        qres["group_nav"].plot(ax=ax)
        ax.set_title(L("分层净值", "Quantile NAV"))
    else:
        ax.text(0.5, 0.5, "No backtest data", ha="center", va="center")
        ax.set_title(L("分层净值", "Quantile NAV"))
    save(fig, "quantile_nav")

    # 分组年化收益
    fig, ax = plt.subplots(figsize=(5, 3))
    if qres is not None:
        ann = [qres["group_performance"][c]["annual_return"] for c in qres["group_performance"]]
        ax.bar(range(len(ann)), ann)
    else:
        ax.text(0.5, 0.5, "No backtest data", ha="center", va="center")
    ax.set_title(L("分组年化收益", "Group Annual Return"))
    save(fig, "group_return")

    # 相关性热力图
    fig, ax = plt.subplots(figsize=(6, 5))
    if corr_res is not None and not corr_res["corr_matrix"].empty:
        im = ax.imshow(corr_res["corr_matrix"].to_numpy(dtype=float), cmap="RdBu_r", vmin=-1, vmax=1)
        ax.set_xticks(range(len(corr_res["corr_matrix"].columns)))
        ax.set_xticklabels(corr_res["corr_matrix"].columns, rotation=90, fontsize=7)
        ax.set_yticks(range(len(corr_res["corr_matrix"].index)))
        ax.set_yticklabels(corr_res["corr_matrix"].index, fontsize=7)
        fig.colorbar(im, ax=ax)
    else:
        ax.text(0.5, 0.5, "No correlation data", ha="center", va="center")
    ax.set_title(L("因子相关性", "Factor Correlation"))
    save(fig, "corr")

    def fmt(v):
        return "N/A" if v is None or (isinstance(v, float) and not np.isfinite(v)) else f"{v:.4f}"

    stats = {
        "IC 均值": fmt(ic_res["ic_mean"]) if ic_res else "N/A",
        "IC 标准差": fmt(ic_res["ic_std"]) if ic_res else "N/A",
        "ICIR": fmt(ic_res["icir"]) if ic_res else "N/A",
        "IC 胜率": fmt(ic_res["ic_win_rate"]) if ic_res else "N/A",
        "单调性": str(qres["monotonic_direction"]) if qres else "N/A",
    }
    rows = "\n".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in stats.items())
    imgs = "\n".join(f'<div><img src="{name}" style="max-width:900px"></div>' for name in images)
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>{factor_name} Factor Report</title>
<style>body{{font-family:Arial,sans-serif;margin:24px}}th{{text-align:left;padding:4px 12px}}
td{{padding:4px 12px}}</style></head><body>
<h1>{factor_name} 因子研究报告</h1>
<p>⚠️ Alpha101/191 是因子库不是策略；单因子 IC 通常很低，必须做样本外验证。</p>
<table>{rows}</table>
<h2>图表</h2>{imgs}
<hr><p>Generated by factor.evaluator.generate_factor_report</p></body></html>"""
    html_path = out_dir / f"{factor_name}_report.html"
    html_path.write_text(html, encoding="utf-8")
    return html_path
