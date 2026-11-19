"""技术指标计算（第 3 步）：跨市场通用的纯函数指标库。

设计约定（对应指令集 3.0 的三条硬约定 + 守卫加固）
------------------------------------------------
1. **复权口径全局统一**：`ATR` / `STD` / `HIST_VOL` 必须吃**复权价**。
   口径判定【不依赖易失的 attrs】（`resample`/`concat`/`rolling` 会清空 attrs），
   而是按 `resolve_adjust()` 的顺序：
   ① 调用方显式传 `adjust="qfq"`；
   ② `DataFrame` 里的普通列 `config.INDICATOR_HARDENING["adjust_column"]`（默认
      `price_adjust`，由数据层出口写入，值 qfq/hfq/none，能穿透窗口运算）；
   ③ 兼容读取 `attrs["adjust"]`（数据层老帧）；
   ④ **都读不到 = 口径未知** → 按 `on_adjust_unknown="require"` 直接抛错（fail-closed）。
   三处都失败时绝不「静默按已复权处理」——2:1 拆股缺口会让 ATR 差 4 倍。
   复权由数据层 `get_daily(adjust="qfq")` 保证，指标层不做也不缓存复权因子。
2. **量能类只用 volume**：`VOL_MA` / `OBV` / `VR` 统一读
   `config.INDICATOR_CONFIG["volume_metrics_use"]`（默认 `"volume"`），**禁止用 amount**。
   成交量**全 0**（净值型序列）时返回 NaN 并标注 `attrs["volume_all_zero"]=True`，
   绝不返回一串 0（0 会被误读成「极度缩量」）。
3. **年化基数一律引用 config**：`annual_factor()` 统一读
   `config.INDICATOR_CONFIG["annual_factor_by_period"]`，美股日线用
   `annual_trading_days_us`（252），其余用 `annual_trading_days`（244）；
   **禁止在指标里硬编码 252**。

预热期（递归指标早段有偏，必须跳过）
----------------------------------
`required_bars(name, **params)` 返回最小预热根数（`config.INDICATOR_HARDENING["warmup"]`
是下界，递归收敛慢的取 max），所有递归类指标（EMA/SMA/MACD/RSI/KDJ/ATR/ADX/SAR）
返回的前 `required_bars()-1` 根一律为 NaN。回测/实盘必须跳过预热期再出信号。

跨市场红线
----------
- **评估类指标物理隔离**：`eval_max_drawdown` / `eval_sharpe_ratio` /
  `eval_annual_return` / `eval_volatility` 统一 `eval_` 前缀（`eval_prefix`），
  实时信号链在命名层面就取不到，不能只靠注释约束。
- **净值型品种不适用 K 线类指标**：`assert_indicator_usable(name, market=...)`
  的 `market` 是**必填参数**，缺省直接报错，禁止默认放行；净值型市场
  （公募基金 / 逆回购 / 私募 / QII）遇 K 线类指标一律抛错。

通用约定
--------
- 所有函数**不修改传入对象**，返回新对象；
- 开头的 NaN 一律保留（`keep_nan=True`），不 fillna、不 bfill；
- 所有窗口运算固定 `center=False`（`forbid_center=True`），居中窗口=偷看未来。

期权希腊字母单位（写死，测试逐值核对）
----------------------------------
- `DELTA`：标的变动 1.0 对应的期权价格变动；
- `GAMMA`：标的变动 1.0 对应的 Delta 变动；
- `VEGA`：波动率变动 **1 个点（σ+0.01）** 对应的价格变动；
- `THETA`：每 **1 个自然日**（年化 Theta / 365）的价格变动；
- `RHO`：利率变动 **1 个百分点（r+0.01）** 对应的价格变动。
"""
from __future__ import annotations

import logging
import math
from typing import Optional

import numpy as np
import pandas as pd

import config

logger = logging.getLogger("quant.indicators")

__all__ = [
    # 均线
    "MA", "EMA", "SMA", "MACD", "BOLL",
    # 动量
    "RSI", "KDJ", "ROC", "CCI", "WILLR",
    # 量能
    "VOL_MA", "OBV", "VR",
    # 波动率
    "ATR", "STD", "HIST_VOL",
    # 趋势
    "ADX", "SAR",
    # 期权
    "IMPLIED_VOL", "DELTA", "GAMMA", "THETA", "VEGA", "RHO",
    "IV_RANK", "IV_PERCENTILE",
    # 基金 / 资产配置（评估类，物理隔离）
    "eval_max_drawdown", "eval_sharpe_ratio", "eval_annual_return", "eval_volatility",
    # 期货
    "BASIS", "BASIS_RATE", "ROLL_YIELD",
    # 工具
    "annual_factor", "check_adjusted", "resolve_adjust", "assert_indicator_usable",
    "required_bars", "rolling_window", "volume_series",
    # 预热闸门（B1/B5）
    "warmup_ok_series", "attach_warmup_ok", "assert_signal_frame",
    "last_bar_ready", "assert_last_bar_ready",
    "ADJUSTED_ONLY", "KLINE_INDICATORS",
]

# 必须使用复权价的指标（3.0 硬约定 1）
ADJUSTED_ONLY = ("ATR", "STD", "HIST_VOL")

# 依赖 K 线（high/low/close/volume）的指标：净值型品种不可用
KLINE_INDICATORS = {
    "MA", "EMA", "SMA", "MACD", "BOLL", "RSI", "KDJ", "ROC", "CCI", "WILLR",
    "VOL_MA", "OBV", "VR", "ATR", "STD", "HIST_VOL", "ADX", "SAR",
}


# ==================== 配置读取（每次现读，支持测试临时覆盖） ====================

def _cfg_set(key: str) -> set:
    return {str(x).upper() for x in config.INDICATOR_CONFIG.get(key, [])}


def _hardening(key: str, default=None):
    return config.INDICATOR_HARDENING.get(key, default)


def annual_factor(period: str = "1d", market: Optional[str] = None) -> float:
    """年化基数：日线按市场区分（美股 252 / 其余 244），其余周期读配置表。

    禁止在指标里硬编码 252；A 股/港股/期货/加密统一用 annual_trading_days（244）。
    """
    period = str(period)
    if period not in config.INDICATOR_CONFIG["annual_factor_by_period"]:
        raise ValueError(f"未知周期 {period}，可选 {list(config.INDICATOR_CONFIG['annual_factor_by_period'])}")
    if period == "1d" and str(market or "").lower() in ("us_stock", "us_etf"):
        return float(config.INDICATOR_CONFIG["annual_trading_days_us"])
    return float(config.INDICATOR_CONFIG["annual_factor_by_period"][period])


def _warmup_guard(key: str, default=None):
    return getattr(config, "INDICATOR_WARMUP_GUARD", {}).get(key, default)


# 需要「初始条件扰动收敛」反推的递归指标（窗口类指标只需 n 根，表值足够）
_RECURSIVE_INDICATORS = {"EMA", "SMA", "MACD", "RSI", "ATR", "ADX", "KDJ"}
_WARMUP_DEFAULT_PARAMS = {"EMA": {"n": 12}, "SMA": {"n": 5, "m": 1}, "MACD": {"slow": 26, "signal": 9},
                          "RSI": {"n": 14}, "ATR": {"n": 14}, "ADX": {"n": 14},
                          "KDJ": {"n": 9, "m1": 3, "m2": 3}}
_BURNIN_CACHE: dict = {}


def _burnin_sample(n: int) -> np.ndarray:
    """确定性长样本（趋势+波动），用于 B2 预热根数反推；不得依赖随机真实数据。"""
    rng = np.random.default_rng(20261030)
    return 100.0 + np.cumsum(rng.normal(0.03, 0.8, int(n)))


def _burnin_raw(name: str, x: np.ndarray, p: dict):
    """反推用的原始递推实现（不调用 public 指标，避免 required_bars 递归）。"""
    key = str(name).upper()
    if key == "EMA":
        return _ema_raw(pd.Series(x), int(p["n"])).to_numpy()
    if key == "SMA":
        return _sma_raw(x, int(p["n"]), int(p["m"]), None)
    if key == "MACD":
        c = pd.Series(x)
        dif = _ema_raw(c, int(p.get("fast", 12))) - _ema_raw(c, int(p["slow"]))
        dea = _ema_raw(dif, int(p["signal"]))
        return np.vstack([dif.to_numpy(), dea.to_numpy()])
    if key == "RSI":
        n = int(p["n"])
        d = np.diff(x, prepend=x[0])
        ag = _wilder_smooth(pd.Series(np.clip(d, 0, None)), n).to_numpy()
        al = _wilder_smooth(pd.Series(np.clip(-d, 0, None)), n).to_numpy()
        with np.errstate(divide="ignore", invalid="ignore"):
            rs = 100.0 - 100.0 / (1.0 + ag / np.where(al == 0, np.nan, al))
        return rs
    if key in ("ATR", "ADX"):
        n = int(p["n"])
        h, l, c = x + 0.8, x - 0.8, x
        prev_c = np.roll(c, 1)
        prev_c[0] = c[0]
        tr = np.maximum.reduce([h - l, np.abs(h - prev_c), np.abs(l - prev_c)])
        if key == "ATR":
            return _wilder_smooth(pd.Series(tr), n).to_numpy()
        up = np.diff(h, prepend=h[0])
        dn = -np.diff(l, prepend=l[0])
        pdm = np.where((up > dn) & (up > 0), up, 0.0)
        mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
        atr = _wilder_smooth(pd.Series(tr), n).to_numpy()
        with np.errstate(divide="ignore", invalid="ignore"):
            pdi = 100.0 * _wilder_smooth(pd.Series(pdm), n).to_numpy() / atr
            mdi = 100.0 * _wilder_smooth(pd.Series(mdm), n).to_numpy() / atr
            dx = 100.0 * np.abs(pdi - mdi) / np.where((pdi + mdi) == 0, np.nan, pdi + mdi)
        return _wilder_smooth(pd.Series(dx), n).to_numpy()
    if key == "KDJ":
        n, m1, m2 = int(p["n"]), int(p.get("m1", 3)), int(p.get("m2", 3))
        h, l = x + 0.8, x - 0.8
        rsv = np.full(len(x), np.nan)
        for i in range(n - 1, len(x)):
            hh, ll = h[i - n + 1:i + 1].max(), l[i - n + 1:i + 1].min()
            if hh != ll:
                rsv[i] = (x[i] - ll) / (hh - ll) * 100.0
        k = _sma_raw(rsv, m1, 1, 50.0)
        d = _sma_raw(k, m2, 1, 50.0)
        return np.vstack([k, d])
    return np.array([])


def _burnin_required_bars(name: str, params: dict, tol: float) -> int:
    """B2：反推「初始条件扰动影响收敛到 tol 相对误差」所需的最少根数。

    做法：用同一长样本，把首根价格放大 50% 后重算指标，比较两条递推轨迹，
    找到从某根起「相对误差（以序列量级归一）恒 <= tol」的位置即为预热根数。
    表值只是下界，递归指标的真实预热期远大于表值（EMA12 约 37 根、MACD.DEA 约 116 根）。
    """
    key = str(name).upper()
    if key not in _RECURSIVE_INDICATORS:
        return 0
    if str(_warmup_guard("required_bars_method", "burnin_compare")) != "burnin_compare":
        return 0
    p = dict(_WARMUP_DEFAULT_PARAMS.get(key, {}))
    p.update({k: v for k, v in params.items() if v is not None})
    cache_key = (key, tuple(sorted(p.items())), round(float(tol), 12))
    if cache_key in _BURNIN_CACHE:
        return _BURNIN_CACHE[cache_key]
    span = int(p.get("n") or p.get("slow") or 14)
    length = max(10 * span, 400)
    x = _burnin_sample(length)
    x_perturbed = x.copy()
    x_perturbed[0] *= 1.5
    base = np.atleast_2d(_burnin_raw(key, x, p))
    pert = np.atleast_2d(_burnin_raw(key, x_perturbed, p))
    scale = float(np.nanmax(np.abs(base))) if np.isfinite(base).any() else 1.0
    scale = max(scale, 1e-12)
    with np.errstate(invalid="ignore"):
        err = np.abs(base - pert) / scale
    err = np.where(np.isnan(err), 0.0, err)
    # 找到「从该根起之后所有误差都 <= tol」的最小下标（+2 根安全余量）
    required = length
    for i in range(err.shape[1] - 1, -1, -1):
        if np.any(err[:, i] > tol):
            required = i + 2
            break
    else:
        required = 1
    required = int(min(max(required, 1), length))
    _BURNIN_CACHE[cache_key] = required
    return required


def required_bars(indicator: str, **params) -> int:
    """最小预热根数（含首根有效值）：前 `required_bars()-1` 根应视为无效信号。

    B2：表值（`config.INDICATOR_HARDENING["warmup"]`）**只作下界**，递归指标用
    `_burnin_required_bars()` 以长样本扰动反推收敛根数（tol 读
    `config.INDICATOR_WARMUP_GUARD["convergence_tol"]`），因此 EMA12 实际约 37 根、
    MACD.DEA 约 116 根，远大于表值 20/35——按表值取会带着初始化偏差出信号。
    """
    key = str(indicator).upper()
    base = int(_hardening("warmup", {}).get(key, 1))
    n = int(params.get("n") or 0)
    if key in ("MA", "BOLL", "CCI", "WILLR", "EMA", "SMA", "KDJ", "STD"):
        need = max(base, n)
    elif key in ("RSI", "ROC", "ATR", "HIST_VOL", "VR"):
        need = max(base, n + 1)
    elif key == "MACD":
        need = max(base, int(params.get("slow", 26)) + int(params.get("signal", 9)))
    elif key == "ADX":
        need = max(base, 2 * n)
    elif key == "VOL_MA":
        need = max(base, n, int(params.get("m") or 0))
    elif key == "OBV":
        need = 1
    elif key == "SAR":
        need = max(base, 2)
    else:
        need = base
    tol = float(_warmup_guard("convergence_tol", 1e-3))
    need = max(need, _burnin_required_bars(key, params, tol))
    return int(max(need, 1))


# ==================== 通用工具 ====================

def resolve_adjust(obj, adjust: Optional[str] = None) -> Optional[str]:
    """解析价格复权口径：显式参数 → 普通列 → attrs → None（未知）。

    返回 "qfq" / "hfq" / "none" / None；None 表示【无法确认】，调用方必须按 fail-closed 处理。
    普通列（`price_adjust`）能穿过 resample/concat/rolling，是首选信息源。
    """
    def _norm(value) -> str:
        v = str(value).strip().lower()
        return "none" if v in ("", "none", "raw", "bfq", "no") else v

    if adjust is not None:
        return _norm(adjust)
    if isinstance(obj, pd.DataFrame):
        col = str(_hardening("adjust_column", "price_adjust"))
        if col in obj.columns:
            vals = {_norm(x) for x in obj[col].dropna().unique()}
            if len(vals) == 1:
                return vals.pop()
            if len(vals) > 1:
                raise ValueError(
                    f"帧内 {col} 列口径不一致 {sorted(vals)}（多标的/多口径拼接），"
                    f"禁止用混合口径计算 ATR/STD/HIST_VOL")
    attrs = getattr(obj, "attrs", None) or {}
    if "adjust" in attrs:
        return _norm(attrs.get("adjust"))
    return None


def check_adjusted(obj, indicator: str, adjust: Optional[str] = None) -> bool:
    """复权口径校验（fail-closed）：ATR/STD/HIST_VOL 口径不明或为不复权时直接报错。

    优先级见 `resolve_adjust()`：显式参数 → `price_adjust` 列 → attrs。
    **读不到口径不再默认放行**：按 `on_adjust_unknown`（默认 require）抛错，
    因为「在未复权价上算波动率」会把拆股缺口算成 4 倍波动。
    """
    name = str(indicator).upper()
    if name not in ADJUSTED_ONLY:
        return True
    if obj is None or len(obj) == 0:  # 空表无价格可算，交给调用方返回空结果
        return True
    resolved = resolve_adjust(obj, adjust)
    if resolved in ("qfq", "hfq"):
        return True
    if resolved == "none":
        raise ValueError(
            f"{name} 必须使用复权价（config.INDICATOR_CONFIG['default_adjust']="
            f"{config.INDICATOR_CONFIG['default_adjust']}），当前口径=none（不复权）；"
            f"请先 get_daily(..., adjust='qfq')，复权价与不复权价的缺口会污染 ATR/STD/HIST_VOL")
    policy = str(_hardening("on_adjust_unknown", "require")).lower()
    if policy == "require":
        raise ValueError(
            f"{name} 无法确认复权口径（{_hardening('adjust_column', 'price_adjust')} 列与 attrs 均缺失），"
            f"按 config.INDICATOR_HARDENING['on_adjust_unknown']='require' 拒绝计算；"
            f"请传 adjust='qfq' 或使用数据层出口帧（带 {_hardening('adjust_column', 'price_adjust')} 列）")
    logger.warning("[%s] 无法确认复权口径，按配置 on_adjust_unknown=%s 继续计算", name, policy)
    return True


def assert_indicator_usable(name: str, market: str, for_signal: bool = True) -> bool:
    """跨市场红线闸门（`market` 必填，禁止缺省放行）。

    - 评估类（`eval_` 前缀或 evaluation_only）在 `for_signal=True` 时一律拒绝；
    - 净值型市场（nav_only_markets）拒绝所有 K 线类指标（这些品种只有净值序列）。
    """
    if market is None or not str(market).strip():
        raise ValueError(
            "assert_indicator_usable 必须显式传入 market（禁止缺省放行）："
            "净值型市场判定依赖它，缺省即放行等于没有守卫")
    key = str(name).upper()
    prefix = str(_hardening("eval_prefix", "eval_")).upper()
    if for_signal and (key.startswith(prefix) or key in _cfg_set("evaluation_only")):
        raise ValueError(
            f"{key} 属评估类指标（全样本统计量，config.INDICATOR_CONFIG['evaluation_only']），"
            f"只能用于回测/绩效评估，禁止进入实时信号链")
    mkt = str(market).strip().lower()
    if mkt in {str(x).lower() for x in config.INDICATOR_CONFIG.get("nav_only_markets", [])} \
            and key in KLINE_INDICATORS:
        raise ValueError(
            f"[{mkt}] 是净值型品种（只有净值，没有 high/low/volume），"
            f"不适用 K 线类指标 {key}；请改用净值类指标（eval_annual_return / "
            f"eval_volatility / eval_sharpe_ratio / eval_max_drawdown）")
    return True


def rolling_window(series: pd.Series, n: int, center: bool = False) -> "pd.core.window.rolling.Rolling":
    """统一窗口入口：`forbid_center=True` 时禁止居中窗口（居中=偷看未来数据）。"""
    if center and bool(config.INDICATOR_CONFIG.get("forbid_center", True)):
        raise ValueError(
            f"禁止 center=True 窗口（config.INDICATOR_CONFIG['forbid_center']=True）："
            f"居中窗口会把未来数据带进当根指标，形成未来函数")
    return series.rolling(int(n), min_periods=int(n), center=bool(center))


def _series(obj) -> pd.Series:
    """把 Series / 单列 DataFrame / 数组统一成 float Series（不改原对象、不填 NaN）。"""
    if isinstance(obj, pd.DataFrame):
        if "close" not in obj.columns:
            raise KeyError("传入 DataFrame 时必须包含 close 列")
        return obj["close"].astype(float)
    if isinstance(obj, pd.Series):
        return obj.astype(float)
    return pd.Series(obj, dtype=float)


def volume_series(obj) -> pd.Series:
    """量能指标统一取数：只读 config 指定的列（默认 volume），禁止用 amount。"""
    col = str(config.INDICATOR_CONFIG.get("volume_metrics_use", "volume"))
    if isinstance(obj, pd.DataFrame):
        if col not in obj.columns:
            raise KeyError(
                f"量能指标只允许使用 {col} 列（config.INDICATOR_CONFIG['volume_metrics_use']），"
                f"当前列={list(obj.columns)}；禁止用 amount 代替（跨市场单位不一致）")
        return obj[col].astype(float)
    return obj.astype(float) if isinstance(obj, pd.Series) else pd.Series(obj, dtype=float)


def _volume_all_zero(v: pd.Series) -> bool:
    """成交量是否「全 0」（非全 NaN 且所有有效值都是 0）→ 净值型序列，量能指标不适用。"""
    s = v.dropna()
    return len(s) > 0 and bool((s == 0).all())


def _mark_volume_zero(obj):
    """给全 0 成交量的量能指标结果打标注（禁止静默返回一串 0）。"""
    obj.attrs["volume_all_zero"] = True
    obj.attrs["volume_note"] = "成交量全 0（疑似净值型/无成交量序列），量能指标不适用，返回 NaN"
    return obj


def _nan_like(obj, columns=None):
    """生成与输入同形状的全 NaN 结果。"""
    if isinstance(obj, pd.DataFrame):
        cols = columns or list(obj.columns)
        return pd.DataFrame(np.nan, index=obj.index, columns=cols)
    return pd.Series(np.nan, index=obj.index, dtype=float)


def _mask_warmup(obj, bars: int):
    """把前 `bars-1` 根置为 NaN（预热期不产信号）；返回新对象，不改入参。"""
    if bars <= 1 or len(obj) == 0:
        return obj.copy()
    out = obj.copy()
    k = min(int(bars) - 1, len(out))
    if isinstance(out, pd.DataFrame):
        out.iloc[:k, :] = np.nan
    else:
        out.iloc[:k] = np.nan
    return out


# ==================== 预热闸门（B1 / B5）：NaN 只是哑弹，必须物化为布尔列 ====================

# 信号帧里不属于「指标值」的列（检查 fillna 时跳过）
_NON_SIGNAL_COLUMNS = {
    "symbol", "date", "datetime", "time", "open", "high", "low", "close", "volume", "amount",
    "is_suspended", "last_bar_incomplete", "price_adjust", "data_asof_date",
}


def _warmup_col() -> str:
    return str(_warmup_guard("warmup_ok_column", "warmup_ok"))


def warmup_ok_series(index_or_len, bars: int) -> pd.Series:
    """B1：生成物化布尔序列（True=该根已过预热期）。

    数值 NaN 会被策略 `fillna(0)` 抹平（RSI=0 被误读成「极度超卖」），
    所以预热状态必须是**独立布尔列**，不能只靠「值是不是 NaN」判断。
    """
    if isinstance(index_or_len, pd.Index):
        index = index_or_len
    else:
        index = pd.RangeIndex(int(index_or_len))
    arr = np.arange(len(index)) >= max(int(bars) - 1, 0)
    return pd.Series(arr, index=index, dtype=bool, name=_warmup_col())


def attach_warmup_ok(result, bars: int, column: str = None) -> pd.DataFrame:
    """B1：给指标结果挂上物化布尔列 `warmup_ok`（Series → 单列 DataFrame）。

    这是策略层拼决策帧时唯一可靠的预热信息源：普通列能穿透 concat/rolling，
    而 attrs 会被窗口运算清空。
    """
    col = column or _warmup_col()
    if isinstance(result, pd.Series):
        name = result.name or "value"
        out = result.to_frame(name=name)
    elif isinstance(result, pd.DataFrame):
        out = result.copy()
    else:
        raise TypeError(f"attach_warmup_ok 只接受 Series/DataFrame，收到 {type(result).__name__}")
    out[col] = warmup_ok_series(out.index, bars)
    out.attrs.update(getattr(result, "attrs", {}) or {})
    return out


def last_bar_ready(df) -> bool:
    """B5：末根 bar 是否已过预热期（新上市/刚切周期时为 False）。"""
    col = _warmup_col()
    if isinstance(df, pd.DataFrame) and col in df.columns and len(df) > 0:
        return bool(df[col].iloc[-1])
    return False


def assert_last_bar_ready(df, run_mode: str = None) -> bool:
    """B5：paper/live 下末根 bar 仍在预热期 → 该标的拒绝出信号。

    回测默认豁免（与 stale 闸门同则：回测按定义跑历史，不会「刚上市」）；
    但显式 `run_mode="live"` 时即使回测也拦，便于预演上实盘。
    """
    if not bool(_warmup_guard("live_reject_if_last_bar_in_warmup", True)):
        return True
    mode = str(run_mode or config.RUN_MODE).lower()
    if mode not in ("paper", "live"):
        return True
    if not last_bar_ready(df):
        raise ValueError(
            f"末根 bar 仍在指标预热期（{_warmup_col()}=False），{mode} 模式下禁止出信号："
            f"新上市/刚切周期时递归指标由初始化决定，信号不可信")
    return True


def assert_signal_frame(df, indicator_columns=None, require_last_bar_ready: bool = False,
                        run_mode: str = None) -> bool:
    """信号入口闸门（B1）：强制读取物化 `warmup_ok`，并拦截预热期被 fillna 的行。

    - 缺少 `warmup_ok` 列 → 直接报错（禁止策略绕过预热检查）；
    - 预热掩码为 False 的行出现非 NaN 指标值（fillna/ffill/bfill/rolling(min_periods=1)
      填过）→ 按 `forbid_fillna_before_warmup=True` 直接报错；
    - `require_last_bar_ready=True` 时再执行 B5 的末根检查。
    """
    col = _warmup_col()
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"信号帧必须是 DataFrame，收到 {type(df).__name__}")
    if col not in df.columns:
        raise ValueError(
            f"信号帧缺少物化列 {col}（config.INDICATOR_WARMUP_GUARD['warmup_ok_column']）："
            f"禁止只靠数值 NaN 判断预热期，请用 attach_warmup_ok() 挂列后再进信号入口")
    mask = df[col]
    if mask.isna().any():
        raise ValueError(f"信号帧 {col} 列存在 NaN，无法判断预热状态（必须为 True/False）")
    ready = mask.astype(bool)
    if bool(_warmup_guard("forbid_fillna_before_warmup", True)) and not bool(ready.all()):
        if indicator_columns is None:
            cols = [c for c in df.columns
                    if c not in _NON_SIGNAL_COLUMNS and c != col
                    and pd.api.types.is_numeric_dtype(df[c])]
        else:
            cols = list(indicator_columns)
        leaked = [c for c in cols if df.loc[~ready, c].notna().any()]
        if leaked:
            raise ValueError(
                f"预热期（{col}=False）出现非 NaN 指标值 {leaked}："
                f"禁止在预热掩码为 False 的行做 fillna/ffill/bfill/rolling(min_periods=1)，"
                f"否则 RSI=0 会被误读成「极度超卖」并照发买入信号")
    if require_last_bar_ready:
        assert_last_bar_ready(df, run_mode)
    return True


def _ohlc(obj, low=None, close=None):
    """支持 ATR/KDJ/CCI/WILLR/ADX/SAR 既传 DataFrame 也传 (high, low, close) 三列。"""
    if isinstance(obj, pd.DataFrame):
        for c in ("high", "low", "close"):
            if c not in obj.columns:
                raise KeyError(f"传入 DataFrame 时必须包含 {c} 列")
        return obj["high"].astype(float), obj["low"].astype(float), obj["close"].astype(float)
    if low is None or close is None:
        raise TypeError("请传 DataFrame，或同时传 high/low/close 三个序列")
    return _series(obj), _series(low), _series(close)


def _wilder_smooth(series, n: int) -> pd.Series:
    """Wilder 平滑（RSI/ATR/ADX 口径）：首值取前 n 个有效值的均值，之后递推。"""
    s = pd.Series(series, dtype=float)
    out = pd.Series(np.nan, index=s.index, dtype=float)
    vals = s.to_numpy(dtype=float)
    valid = np.flatnonzero(~np.isnan(vals))
    n = int(n)
    if len(valid) < n:
        return out
    start = int(valid[n - 1])
    prev = float(np.mean(vals[valid[:n]]))
    out.iloc[start] = prev
    for i in range(start + 1, len(vals)):
        v = vals[i]
        if np.isnan(v):
            out.iloc[i] = prev
            continue
        prev = (prev * (n - 1) + v) / n
        out.iloc[i] = prev
    return out


def _ema_raw(s: pd.Series, n: int) -> pd.Series:
    """EMA 递推本体（不做预热掩码，供 MACD 内部串接）。"""
    return s.astype(float).ewm(span=int(n), adjust=False).mean()


def _sma_raw(vals: np.ndarray, n: int, m: int, init: Optional[float]) -> np.ndarray:
    """通达信 SMA 递推本体（不做预热掩码）。

    init 只作第一个有效值出现时的种子：首个有效值之前一律 NaN（keep_nan，不凭空造值）；
    首个有效值之后遇 NaN 沿用上一值。
    """
    out = np.full(len(vals), np.nan)
    prev = init
    started = False
    for i, v in enumerate(vals):
        if np.isnan(v):
            out[i] = prev if started else np.nan
            continue
        prev = v if prev is None else (m * v + (n - m) * prev) / n
        started = True
        out[i] = prev
    return out


# ==================== 1. 均线类 ====================

def MA(close, n: int = 5) -> pd.Series:
    """简单移动平均 MA(n)。"""
    return rolling_window(_series(close), n).mean()


def EMA(close, n: int = 12) -> pd.Series:
    """指数移动平均 EMA(n)（pandas ewm，span=n，adjust=False，与通达信一致）。

    前 `required_bars("EMA", n=n)-1` 根由初始化决定、有偏，直接置 NaN。
    """
    s = _series(close)
    return _mask_warmup(_ema_raw(s, n), required_bars("EMA", n=n))


def SMA(close, n: int = 5, m: int = 1, init: Optional[float] = None) -> pd.Series:
    """通达信口径 SMA(X,N,M)：Y = (M*X + (N-M)*Y_prev) / N。

    init 为初始前值（KDJ 里传 50 复现通达信行为）；前 `required_bars()-1` 根置 NaN。
    """
    s = _series(close)
    out = _sma_raw(s.to_numpy(dtype=float), int(n), int(m), init)
    return _mask_warmup(pd.Series(out, index=s.index, name=getattr(s, "name", None)),
                        required_bars("SMA", n=n))


def MACD(close, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD：DIF=EMA(fast)-EMA(slow)，DEA=EMA(DIF,signal)，柱=(DIF-DEA)*2（国内惯例）。

    预热：DIF 前 slow-1 根 NaN，DEA/柱前 required_bars("MACD")-1=34 根 NaN。
    """
    c = _series(close)
    dif_full = _ema_raw(c, fast) - _ema_raw(c, slow)
    dea_full = _ema_raw(dif_full, signal)  # 用未掩码的 DIF 递推，避免预热 NaN 改变 DEA 初值
    bars = required_bars("MACD", slow=slow, signal=signal)
    dif = _mask_warmup(dif_full, max(required_bars("EMA", n=slow), slow))
    dea = _mask_warmup(dea_full, bars)
    return pd.DataFrame({"DIF": dif, "DEA": dea, "MACD": _mask_warmup((dif_full - dea_full) * 2.0, bars)})


def BOLL(close, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    """布林带：中轨=MA(n)，上下轨=中轨±k×总体标准差（ddof=0，通达信口径）。"""
    c = _series(close)
    mid = rolling_window(c, n).mean()
    std = rolling_window(c, n).std(ddof=0)
    return pd.DataFrame({"UPPER": mid + k * std, "MID": mid, "LOWER": mid - k * std})


# ==================== 2. 动量类 ====================

def RSI(close, n: int = 14) -> pd.Series:
    """RSI（Wilder 平滑）：100 - 100/(1+RS)，RS=平均涨幅/平均跌幅。"""
    c = _series(close)
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = _wilder_smooth(gain, n)
    avg_loss = _wilder_smooth(loss, n)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    # 区间内只涨不跌 → avg_loss=0，RSI 定义为 100
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    return _mask_warmup(rsi, required_bars("RSI", n=n))


def KDJ(high, low=None, close=None, n: int = 9, m1: int = 3, m2: int = 3) -> pd.DataFrame:
    """KDJ：RSV=(C-LLV)/(HHV-LLV)*100，K=SMA(RSV,m1,1) 初值 50，D=SMA(K,m2,1)，J=3K-2D。"""
    h, l, c = _ohlc(high, low, close)
    llv = rolling_window(l, n).min()
    hhv = rolling_window(h, n).max()
    rsv = (c - llv) / (hhv - llv).replace(0, np.nan) * 100.0
    k = pd.Series(_sma_raw(rsv.to_numpy(dtype=float), int(m1), 1, 50.0), index=rsv.index)
    d = pd.Series(_sma_raw(k.to_numpy(dtype=float), int(m2), 1, 50.0), index=rsv.index)
    frame = pd.DataFrame({"K": k, "D": d, "J": 3.0 * k - 2.0 * d})
    return _mask_warmup(frame, required_bars("KDJ", n=n))


def ROC(close, n: int = 12) -> pd.Series:
    """变动率 ROC = (C_t / C_{t-n} - 1) × 100。"""
    return _series(close).pct_change(int(n)) * 100.0


def CCI(high, low=None, close=None, n: int = 14) -> pd.Series:
    """CCI = (TP - MA(TP,n)) / (0.015 × 平均绝对偏差)。"""
    h, l, c = _ohlc(high, low, close)
    tp = (h + l + c) / 3.0
    ma = rolling_window(tp, n).mean()
    md = rolling_window(tp, n).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - ma) / (0.015 * md)


def WILLR(high, low=None, close=None, n: int = 14) -> pd.Series:
    """威廉指标 = -100 × (HHV - C) / (HHV - LLV)。"""
    h, l, c = _ohlc(high, low, close)
    hhv = rolling_window(h, n).max()
    llv = rolling_window(l, n).min()
    return -100.0 * (hhv - c) / (hhv - llv).replace(0, np.nan)


# ==================== 3. 成交量类（只用 volume，禁用 amount） ====================

def VOL_MA(volume, n: int = 5, m: int = 10) -> pd.DataFrame:
    """成交量均线：两条不同周期的量能均线；成交量全 0 时返回 NaN 并标注。"""
    v = volume_series(volume)
    cols = [f"VOL_MA{n}", f"VOL_MA{m}"]
    if _volume_all_zero(v) and bool(_hardening("volume_all_zero_returns_empty", True)):
        return _mark_volume_zero(_nan_like(v, cols))
    return pd.DataFrame({cols[0]: rolling_window(v, n).mean(),
                         cols[1]: rolling_window(v, m).mean()})


def OBV(close, volume) -> pd.Series:
    """能量潮 OBV：涨日累加成交量、跌日累减、平盘不变；成交量全 0 时返回 NaN 并标注。"""
    c = _series(close)
    v = volume_series(volume)
    if _volume_all_zero(v) and bool(_hardening("volume_all_zero_returns_empty", True)):
        return _mark_volume_zero(_nan_like(c))
    sign = np.sign(c.diff().fillna(0.0))
    return (sign * v).cumsum()


def VR(close, volume, n: int = 26) -> pd.Series:
    """成交量比率 VR = (上涨量 + 平盘量/2) / (下跌量 + 平盘量/2) × 100。"""
    c = _series(close)
    v = volume_series(volume)
    if _volume_all_zero(v) and bool(_hardening("volume_all_zero_returns_empty", True)):
        return _mark_volume_zero(_nan_like(c))
    delta = c.diff()
    up = v.where(delta > 0, 0.0)
    down = v.where(delta < 0, 0.0)
    flat = v.where(delta == 0, 0.0)
    up_s = rolling_window(up, n).sum()
    down_s = rolling_window(down, n).sum()
    flat_s = rolling_window(flat, n).sum()
    return (up_s + flat_s / 2.0) / (down_s + flat_s / 2.0).replace(0, np.nan) * 100.0


# ==================== 4. 波动率类（必须用复权价） ====================

def _true_range(h: pd.Series, l: pd.Series, c: pd.Series) -> pd.Series:
    prev_close = c.shift(1)
    return pd.concat([h - l, (h - prev_close).abs(), (l - prev_close).abs()], axis=1).max(axis=1)


def ATR(high, low=None, close=None, n: int = 14, adjust: Optional[str] = None) -> pd.Series:
    """真实波幅 ATR（Wilder 平滑）：必须先确认复权口径，无法确认直接报错（fail-closed）。

    前 `required_bars("ATR", n=n)-1` 根由初始 ATR 决定、有偏，置 NaN（B2 反推，非表值）。
    """
    check_adjusted(high, "ATR", adjust)
    h, l, c = _ohlc(high, low, close)
    return _mask_warmup(_wilder_smooth(_true_range(h, l, c), n), required_bars("ATR", n=n))


def STD(close, n: int = 20, adjust: Optional[str] = None) -> pd.Series:
    """收盘价标准差（样本标准差 ddof=1）：必须先确认复权口径。"""
    check_adjusted(close, "STD", adjust)
    return rolling_window(_series(close), n).std(ddof=1)


def HIST_VOL(close, n: int = 20, period: str = "1d", market: Optional[str] = None,
             adjust: Optional[str] = None) -> pd.Series:
    """历史波动率（年化）：对数收益标准差 × sqrt(年化基数)；必须先确认复权口径。

    年化基数由 annual_factor(period, market) 读取 config，禁止硬编码；
    返回值是小数（0.25 表示 25%）。
    """
    check_adjusted(close, "HIST_VOL", adjust)
    c = _series(close)
    log_ret = np.log(c / c.shift(1))
    return rolling_window(log_ret, n).std(ddof=1) * math.sqrt(annual_factor(period, market))


# ==================== 5. 趋势类 ====================

def ADX(high, low=None, close=None, n: int = 14) -> pd.DataFrame:
    """ADX / +DI / -DI（Wilder）：DX=100×|+DI - -DI|/(+DI + -DI)，ADX=DX 的 Wilder 平滑。

    预热：DI 前 required_bars("ATR")-1 根 NaN，ADX 前 required_bars("ADX")-1=27 根 NaN。
    """
    h, l, c = _ohlc(high, low, close)
    up = h.diff()
    down = -l.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    atr = _wilder_smooth(_true_range(h, l, c), n).replace(0, np.nan)
    plus_di = 100.0 * _wilder_smooth(plus_dm, n) / atr
    minus_di = 100.0 * _wilder_smooth(minus_dm, n) / atr
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    di_bars = required_bars("ATR", n=n)
    return pd.DataFrame({"ADX": _mask_warmup(_wilder_smooth(dx, n), required_bars("ADX", n=n)),
                         "PLUS_DI": _mask_warmup(plus_di, di_bars),
                         "MINUS_DI": _mask_warmup(minus_di, di_bars)})


def SAR(high, low=None, close=None, step: float = 0.02, max_step: float = 0.2) -> pd.Series:
    """抛物线 SAR（经典实现，逐根递推，不使用未来数据）。

    前 required_bars("SAR")-1=4 根由初始极值决定、有偏，置 NaN。
    """
    h, l, _ = _ohlc(high, low, close)
    hv = h.to_numpy(dtype=float)
    lv = l.to_numpy(dtype=float)
    n = len(hv)
    out = np.full(n, np.nan)
    if n == 0:
        return pd.Series(out, index=h.index)
    out[0] = lv[0]
    if n < 2:
        return pd.Series(out, index=h.index)
    bull = hv[1] >= hv[0]
    af = float(step)
    ep = hv[0] if bull else lv[0]
    for i in range(1, n):
        prev = out[i - 1]
        cur = prev + af * (ep - prev)
        if bull:
            cur = min(cur, lv[i - 1])
            if lv[i] < cur:                      # 多转空
                bull, cur, ep, af = False, ep, lv[i], float(step)
            elif hv[i] > ep:
                ep, af = hv[i], min(af + step, max_step)
        else:
            cur = max(cur, hv[i - 1])
            if hv[i] > cur:                      # 空转多
                bull, cur, ep, af = True, ep, hv[i], float(step)
            elif lv[i] < ep:
                ep, af = lv[i], min(af + step, max_step)
        out[i] = cur
    return _mask_warmup(pd.Series(out, index=h.index), required_bars("SAR"))


# ==================== 6. 期权专属 ====================

def _norm_cdf(x):
    return 0.5 * (1.0 + np.vectorize(math.erf)(np.asarray(x) / math.sqrt(2.0)))


def _norm_pdf(x):
    arr = np.asarray(x, dtype=float)
    return np.exp(-0.5 * arr ** 2) / math.sqrt(2.0 * math.pi)


def _d1_d2(S, K, T, r, sigma):
    S, K, T, r, sigma = (np.asarray(x, dtype=float) for x in (S, K, T, r, sigma))
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    return d1, d1 - sigma * np.sqrt(T)


def _bs_price(S, K, T, r, sigma, kind: str = "call"):
    """Black-Scholes 理论价；T<=0 或 sigma<=0 时退化为内在价值。"""
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    disc = np.exp(-np.asarray(r, dtype=float) * np.asarray(T, dtype=float))
    call = np.asarray(S) * _norm_cdf(d1) - np.asarray(K) * disc * _norm_cdf(d2)
    intrinsic = np.maximum(np.asarray(S) - np.asarray(K), 0.0)
    price = call if str(kind).lower() in ("call", "c") else call - np.asarray(S) + np.asarray(K) * disc
    price = np.where(np.asarray(T) > 0, price, intrinsic if str(kind).lower() in ("call", "c")
                     else np.maximum(np.asarray(K) - np.asarray(S), 0.0))
    return price


def _option_guard(key: str, default=None):
    return getattr(config, "OPTION_VALUATION_GUARD", {}).get(key, default)


def _bs_intrinsic(S, K, T, r, kind: str = "call"):
    """期权内在价值（连续复利贴现后的下界）：买方可立即行权所得。"""
    disc = np.exp(-np.asarray(r, dtype=float) * np.asarray(T, dtype=float))
    if str(kind).lower() in ("call", "c"):
        return np.maximum(np.asarray(S, dtype=float) - np.asarray(K, dtype=float) * disc, 0.0)
    return np.maximum(np.asarray(K, dtype=float) * disc - np.asarray(S, dtype=float), 0.0)


def IMPLIED_VOL(price, S, K, T, r: float = None, kind: str = "call",
                tol: float = None, max_iter: int = None, return_status: bool = False):
    """由期权价格反解隐含波动率（二分法，参数读 config.OPTION_VALUATION_GUARD）。

    B4：无解场景（深虚值 / T→0 / 市价低于内在价值 / 超出 [σ_lo, σ_hi] 的理论价区间）
    **必须返回 NaN**（按 `on_no_solution="nan"`）并置 `iv_solved=False`，
    禁止把二分区间下界（1e-4）当成有效 IV 返回——那会伪装成「波动率极低」的买入信号。

    返回：默认返回 float；`return_status=True` 时返回 `(iv, solved)` 二元组。
    """
    guard = getattr(config, "OPTION_VALUATION_GUARD", {})
    solver = str(guard.get("iv_solver", "bisection"))
    if solver != "bisection":
        raise NotImplementedError(f"OPTION_VALUATION_GUARD['iv_solver']={solver} 未实现（仅支持 bisection）")
    tol = float(guard.get("iv_tol", 1e-6) if tol is None else tol)
    max_iter = int(guard.get("iv_max_iter", 200) if max_iter is None else max_iter)
    lo, hi = (float(x) for x in guard.get("iv_bounds", [1e-4, 5.0]))
    r = float(config.INDICATOR_CONFIG["risk_free_rate"] if r is None else r)
    target = float(price)

    def _fail():
        mode = str(guard.get("on_no_solution", "nan")).lower()
        if mode == "raise":
            raise ValueError(
                f"IMPLIED_VOL 无解：price={target} S={S} K={K} T={T} kind={kind}，"
                f"搜索区间 [{lo}, {hi}] 内无匹配波动率（深虚值/到期/价格低于内在价值）")
        return float("nan")

    def _out(iv: float, solved: bool):
        return (iv, solved) if return_status else iv

    # 1) 非有限输入 / 已到期 / 价格非正 → 无解
    if not np.isfinite(target) or target <= 0 or not np.isfinite(float(T)) or float(T) <= 0:
        return _out(_fail(), False)
    # 2) 市价低于内在价值（套利价差）→ BS 无解
    intrinsic = float(np.asarray(_bs_intrinsic(S, K, T, r, kind)))
    if target < intrinsic - 1e-12:
        return _out(_fail(), False)
    # 3) 超出区间端点理论价 → 无解（禁止返回端点）
    price_lo = float(np.asarray(_bs_price(S, K, T, r, lo, kind)))
    price_hi = float(np.asarray(_bs_price(S, K, T, r, hi, kind)))
    if target < price_lo - tol or target > price_hi + tol:
        return _out(_fail(), False)
    for _ in range(int(max_iter)):
        mid = (lo + hi) / 2.0
        val = float(np.asarray(_bs_price(S, K, T, r, mid, kind)))
        if abs(val - target) < tol:
            return _out(mid, True)
        if val < target:
            lo = mid
        else:
            hi = mid
    # 迭代耗尽仍未达容差 → 视为无解（不返回区间中点冒充结果）
    return _out(_fail(), False)


def DELTA(S, K, T, r: float = None, sigma: float = 0.2, kind: str = "call"):
    """Delta（标的每变动 1.0）：看涨 N(d1)，看跌 N(d1)-1。"""
    r = float(config.INDICATOR_CONFIG["risk_free_rate"] if r is None else r)
    d1, _ = _d1_d2(S, K, T, r, sigma)
    return _norm_cdf(d1) if str(kind).lower() in ("call", "c") else _norm_cdf(d1) - 1.0


def GAMMA(S, K, T, r: float = None, sigma: float = 0.2):
    """Gamma（标的每变动 1.0）：φ(d1) / (S σ √T)。"""
    r = float(config.INDICATOR_CONFIG["risk_free_rate"] if r is None else r)
    d1, _ = _d1_d2(S, K, T, r, sigma)
    with np.errstate(divide="ignore", invalid="ignore"):
        return _norm_pdf(d1) / (np.asarray(S, dtype=float) * sigma * np.sqrt(np.asarray(T, dtype=float)))


def THETA(S, K, T, r: float = None, sigma: float = 0.2, kind: str = "call"):
    """Theta：**每 1 个自然日**的价格变动（年化 Theta ÷ `day_count_theta`，默认 365）。"""
    r = float(config.INDICATOR_CONFIG["risk_free_rate"] if r is None else r)
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    S = np.asarray(S, dtype=float)
    K = np.asarray(K, dtype=float)
    T = np.asarray(T, dtype=float)
    disc = np.exp(-r * T)
    base = -S * _norm_pdf(d1) * sigma / (2.0 * np.sqrt(T))
    if str(kind).lower() in ("call", "c"):
        val = base - r * K * disc * _norm_cdf(d2)
    else:
        val = base + r * K * disc * _norm_cdf(-d2)
    days = float(_option_guard("day_count_theta", 365))
    return val / days


def VEGA(S, K, T, r: float = None, sigma: float = 0.2):
    """Vega：波动率变动 **1 个百分点（σ+0.01）** 对应的价格变动 = S φ(d1) √T / 100。"""
    d1, _ = _d1_d2(S, K, T, r, sigma)
    return np.asarray(S, dtype=float) * _norm_pdf(d1) * np.sqrt(np.asarray(T, dtype=float)) / 100.0


def RHO(S, K, T, r: float = None, sigma: float = 0.2, kind: str = "call"):
    """Rho：利率变动 **1 个百分点（r+0.01）** 对应的价格变动 = K T e^{-rT} N(±d2) / 100。"""
    r = float(config.INDICATOR_CONFIG["risk_free_rate"] if r is None else r)
    _, d2 = _d1_d2(S, K, T, r, sigma)
    val = np.asarray(K, dtype=float) * np.asarray(T, dtype=float) * np.exp(-r * np.asarray(T, dtype=float))
    return (val * _norm_cdf(d2) / 100.0) if str(kind).lower() in ("call", "c") \
        else (-val * _norm_cdf(-d2) / 100.0)


def IV_RANK(iv_series, n: int = 252) -> pd.Series:
    """IV 分位数排名（0~100）：当前 IV 在最近 n 个样本中的排名百分位。"""
    s = _series(iv_series)
    return rolling_window(s, n).apply(lambda x: float((x <= x[-1]).mean()) * 100.0, raw=True)


def IV_PERCENTILE(iv_series, n: int = 252) -> pd.Series:
    """IV 百分位（0~100）：(当前 - 区间最小) / (区间最大 - 区间最小)。"""
    s = _series(iv_series)
    lo = rolling_window(s, n).min()
    hi = rolling_window(s, n).max()
    return (s - lo) / (hi - lo).replace(0, np.nan) * 100.0


# ==================== 7. 基金 / 资产配置（评估类，eval_ 前缀物理隔离） ====================

def eval_max_drawdown(nav) -> pd.Series:
    """【评估类，禁止进信号链】最大回撤曲线（负数，单位=小数）：nav / 历史最高点 - 1。

    回撤是逐点比值，与周期/年化基数无关，故无 period/market 参数。
    取 `.min()` 得最大回撤值。
    """
    s = _series(nav)
    return s / s.cummax() - 1.0


def eval_sharpe_ratio(nav, rf: float = None, period: str = "1d", market: Optional[str] = None) -> float:
    """【评估类，禁止进信号链】年化夏普比率：(E[r] - rf/N) / σ(r) × √N，N 取 annual_factor。"""
    s = _series(nav).dropna()
    if len(s) < 3:
        return float("nan")
    rf = float(config.INDICATOR_CONFIG["risk_free_rate"] if rf is None else rf)
    af = annual_factor(period, market)
    ret = s.pct_change().dropna()
    excess = ret - rf / af
    sd = float(excess.std(ddof=1))
    if sd == 0 or math.isnan(sd):
        return float("nan")
    return float(excess.mean() / sd * math.sqrt(af))


def eval_annual_return(nav, period: str = "1d", market: Optional[str] = None) -> float:
    """【评估类，禁止进信号链】年化收益率：(末值/首值)^(1/年数) - 1，年数=(点数-1)/annual_factor。"""
    s = _series(nav).dropna()
    if len(s) < 2 or s.iloc[0] <= 0:
        return float("nan")
    af = annual_factor(period, market)
    years = (len(s) - 1) / af
    if years <= 0:
        return float("nan")
    return float((s.iloc[-1] / s.iloc[0]) ** (1.0 / years) - 1.0)


def eval_volatility(nav, period: str = "1d", market: Optional[str] = None) -> float:
    """【评估类，禁止进信号链】年化波动率：收益率样本标准差 × √N。"""
    s = _series(nav).dropna()
    ret = s.pct_change().dropna()
    if len(ret) < 2:
        return float("nan")
    return float(ret.std(ddof=1) * math.sqrt(annual_factor(period, market)))


# ==================== 8. 期货专属 ====================

def BASIS(spot_price, futures_price) -> pd.Series:
    """基差 = 现货 - 期货。"""
    return _series(spot_price) - _series(futures_price)


def BASIS_RATE(spot_price, futures_price) -> pd.Series:
    """基差率 = (现货 - 期货) / 期货。"""
    f = _series(futures_price)
    return (_series(spot_price) - f) / f.replace(0, np.nan)


def ROLL_YIELD(near_price, far_price, days_to_expiry) -> pd.Series:
    """展期收益率 = (近月/远月 - 1) × 365 / 剩余天数（年化）。"""
    near = _series(near_price)
    far = _series(far_price)
    days = days_to_expiry if isinstance(days_to_expiry, pd.Series) \
        else pd.Series(float(days_to_expiry), index=near.index)
    days = days.astype(float)
    return (near / far.replace(0, np.nan) - 1.0) * (365.0 / days.replace(0, np.nan))
