"""第 3 步技术指标测试（不依赖网络，纯构造数据）。

覆盖（含第 3 步守卫加固修正）：
1) MA / EMA / MACD / BOLL / RSI 逐值手算校验（误差 < 1e-6，手算用独立 numpy 循环）；
2) 空表 / 全 NaN 不崩，开头 NaN 保留；
3) 不修改传入对象；
4) A1 复权守卫 fail-closed：price_adjust 列优先；attrs 被清空（模拟 resample/concat）且无列时
   ATR/STD/HIST_VOL【必须报错】，绝不静默按已复权处理；不复权 ATR > 复权 ATR；
5) A2 预热期：EMA/RSI/ADX/SAR/MACD 前 required_bars-1 根必须为 NaN，required_bars 读 config；
6) A3 跨市场红线：eval_ 前缀物理隔离、assert_indicator_usable 缺 market 直接报错、净值型拦截；
7) A4 成交量全 0 → 量能指标返回 NaN 并标注 volume_all_zero；
8) A5 期权希腊字母单位逐值核对（Delta/Gamma/Vega/Theta/Rho 用 BS 重定价验证）；
9) 年化基数、未来函数、其余指标形状与取值合理性。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from core import indicators as ind

PASS, FAIL = [], []
EPS = 1e-6


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'✅' if ok else '❌'} {name}" + (f" | {detail}" if detail else ""))


def make_df(closes, adjust: str = "qfq") -> pd.DataFrame:
    """构造标准日线帧：带 price_adjust 普通列（模拟数据层出口），attrs 故意留空。"""
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="B")
    close = pd.Series(closes, index=idx, dtype=float)
    df = pd.DataFrame({"open": close.shift(1).fillna(close.iloc[0]),
                       "high": close + 0.8, "low": close - 0.8,
                       "close": close, "volume": 1_000_000.0,
                       "amount": close * 1_000_000}, index=idx)
    df["price_adjust"] = adjust
    return df


def wave(n: int = 420, seed: int = 7) -> list:
    """确定性价格序列（含趋势+波动+小幅回调），便于手算与未来函数校验。

    长度 420：B2 预热反推后 ADX/MACD/RSI 的真实预热期可达 100~150 根，
    样本太短会让「预热期后应有有效值」的断言无法成立。
    """
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.05, 0.9, n)
    return list(100 + np.cumsum(steps))


# ==================== 独立手算（不复用被测实现） ====================

def hand_ma(vals, n):
    return float(np.mean(vals[-n:]))


def hand_ema(vals, n):
    alpha = 2.0 / (n + 1.0)
    out, prev = [], None
    for v in vals:
        prev = v if prev is None else alpha * v + (1 - alpha) * prev
        out.append(prev)
    return out


def hand_rsi(vals, n):
    delta = np.diff(np.asarray(vals, dtype=float))
    gain = np.clip(delta, 0, None)
    loss = np.clip(-delta, 0, None)
    if len(gain) < n:
        return float("nan")
    ag, al = float(gain[:n].mean()), float(loss[:n].mean())
    for i in range(n, len(gain)):
        ag = (ag * (n - 1) + gain[i]) / n
        al = (al * (n - 1) + loss[i]) / n
    if al == 0:
        return 100.0
    return float(100.0 - 100.0 / (1.0 + ag / al))


def close_enough(a, b, tol: float = EPS) -> bool:
    if a is None or b is None:
        return False
    if np.isnan(a) and np.isnan(b):
        return True
    return abs(float(a) - float(b)) < tol


def raises(fn, *args, **kwargs) -> bool:
    try:
        fn(*args, **kwargs)
        return False
    except Exception:  # noqa: BLE001
        return True


def main() -> int:
    closes = wave()
    df = make_df(closes)
    n = len(closes)

    # ---------- 1. 数值手算校验（MA/EMA/MACD/BOLL/RSI） ----------
    ma5 = ind.MA(df, 5)
    check("MA(5) 末值与手算一致", close_enough(ma5.iloc[-1], hand_ma(closes, 5)),
          f"{ma5.iloc[-1]:.10f} vs {hand_ma(closes, 5):.10f}")

    ema12 = ind.EMA(df["close"], 12)
    hand_e = hand_ema(closes, 12)
    start = ind.required_bars("EMA", n=12) - 1
    err_e = max(abs(ema12.iloc[i] - hand_e[i]) for i in range(start, n))
    check("EMA(12) 预热后全序列与手算一致（<1e-6）", err_e < EPS,
          f"从第 {start + 1} 根起最大误差 {err_e:.3e}")

    macd = ind.MACD(df["close"])
    fast_e, slow_e = hand_ema(closes, 12), hand_ema(closes, 26)
    dif_h = [fast_e[i] - slow_e[i] for i in range(n)]
    dea_h = hand_ema(dif_h, 9)
    s2 = ind.required_bars("MACD", slow=26, signal=9) - 1
    err_m = max(max(abs(macd["DIF"].iloc[i] - dif_h[i]),
                    abs(macd["DEA"].iloc[i] - dea_h[i]),
                    abs(macd["MACD"].iloc[i] - 2 * (dif_h[i] - dea_h[i]))) for i in range(s2, n))
    check("MACD DIF/DEA/柱 预热后与手算一致（<1e-6）", err_m < EPS, f"最大误差 {err_m:.3e}")

    boll = ind.BOLL(df["close"], 20, 2.0)
    win = np.array(closes[-20:])
    mid_h, std_h = win.mean(), win.std(ddof=0)
    check("BOLL 上/中/下轨与手算一致（<1e-6）",
          close_enough(boll["MID"].iloc[-1], mid_h)
          and close_enough(boll["UPPER"].iloc[-1], mid_h + 2 * std_h)
          and close_enough(boll["LOWER"].iloc[-1], mid_h - 2 * std_h),
          f"MID={boll['MID'].iloc[-1]:.10f} UPPER={boll['UPPER'].iloc[-1]:.10f}")

    rsi = ind.RSI(df["close"], 14)
    rsi_h = hand_rsi(closes, 14)
    prev14 = hand_rsi(closes[:-3], 14)
    check("RSI(14) 末值与手算一致（<1e-6）", close_enough(rsi.iloc[-1], rsi_h),
          f"{rsi.iloc[-1]:.10f} vs {rsi_h:.10f}")
    check("RSI(14) 历史值同样与手算一致（Wilder 递推正确）",
          close_enough(rsi.iloc[-4], prev14), f"{rsi.iloc[-4]:.10f} vs {prev14:.10f}")
    check("RSI 取值落在 [0,100]", float(rsi.dropna().between(0, 100).all()) == 1.0)

    # ---------- 2. 空表 / 全 NaN ----------
    empty = pd.DataFrame({c: pd.Series(dtype=float) for c in
                          ["open", "high", "low", "close", "volume", "amount"]})
    nan_df = make_df([np.nan] * 40)
    ok_empty = True
    try:
        for fn, args in [
            (ind.MA, (empty, 5)), (ind.EMA, (empty, 12)), (ind.MACD, (empty,)),
            (ind.BOLL, (empty,)), (ind.RSI, (empty,)), (ind.KDJ, (empty,)),
            (ind.ROC, (empty,)), (ind.CCI, (empty,)), (ind.WILLR, (empty,)),
            (ind.VOL_MA, (empty,)), (ind.OBV, (empty, empty)),
            (ind.VR, (empty, empty)), (ind.ATR, (empty,)), (ind.STD, (empty,)),
            (ind.HIST_VOL, (empty,)), (ind.ADX, (empty,)), (ind.SAR, (empty,)),
            (ind.eval_max_drawdown, (empty,)), (ind.IV_RANK, (empty, 5)),
            (ind.IV_PERCENTILE, (empty, 5)),
        ]:
            fn(*args)
        for v in (ind.eval_sharpe_ratio(empty), ind.eval_annual_return(empty),
                  ind.eval_volatility(empty)):
            assert isinstance(v, float)
    except Exception as exc:  # noqa: BLE001
        ok_empty = False
        check("空表不崩", False, f"{type(exc).__name__}: {exc}")
    if ok_empty:
        check("空表不崩（20 个指标全部返回空结果）", True)

    ok_nan = True
    try:
        assert ind.MA(nan_df, 5).isna().all()
        assert ind.EMA(nan_df, 12).isna().all()
        assert ind.RSI(nan_df, 14).isna().all()
        assert ind.ATR(nan_df, 14).isna().all()
        assert ind.MACD(nan_df)["DIF"].isna().all()
        assert ind.KDJ(nan_df)["K"].isna().all()
        assert ind.OBV(nan_df["close"], nan_df["volume"]).fillna(0).eq(0).all()
    except Exception as exc:  # noqa: BLE001
        ok_nan = False
        check("全 NaN 不崩", False, f"{type(exc).__name__}: {exc}")
    if ok_nan:
        check("全 NaN 不崩且开头 NaN 保留（不 fillna）", True)

    # ---------- 3. 不修改原对象 ----------
    df2 = make_df(closes[::2] if len(closes) > 60 else closes)
    before = df2.copy(deep=True)
    before_attrs = dict(df2.attrs)
    series_before = df2["close"].copy(deep=True)
    for fn in (ind.MA, ind.EMA, ind.SMA, ind.MACD, ind.BOLL, ind.RSI, ind.KDJ,
               ind.ROC, ind.CCI, ind.WILLR, ind.VOL_MA, ind.ATR, ind.STD,
               ind.HIST_VOL, ind.ADX, ind.SAR):
        fn(df2)
    ind.OBV(df2["close"], df2["volume"])
    ind.VR(df2["close"], df2["volume"])
    ind.eval_max_drawdown(df2["close"])
    unchanged = df2.equals(before) and df2.attrs == before_attrs \
        and df2["close"].equals(series_before)
    check("所有指标不修改传入对象（值/attrs/列均不变）", unchanged)

    # ---------- 4. A1 复权守卫 fail-closed ----------
    raw_vals = wave(seed=21)
    # 4.1 price_adjust 列 = none → 波动率类全部报错
    raw_df = make_df(raw_vals, adjust="none")
    raised = sum(raises(fn, raw_df) for fn in (ind.ATR, ind.STD, ind.HIST_VOL))
    check("price_adjust=none 时 ATR/STD/HIST_VOL 全部报错", raised == 3, f"拦截 {raised}/3")

    # 4.2 attrs 被清空（模拟 resample/concat 之后）+ 无 price_adjust 列 + 价格是不复权 → 必须报错
    no_info = make_df(raw_vals, adjust="qfq").drop(columns=["price_adjust"])
    no_info.attrs = {}
    raised = sum(raises(fn, no_info) for fn in (ind.ATR, ind.STD, ind.HIST_VOL))
    check("口径丢失（attrs 清空且无 price_adjust 列）时禁止静默计算", raised == 3,
          f"fail-closed 拦截 {raised}/3")

    # 4.3 attrs 残留 adjust=none（老帧）仍被拦
    legacy = make_df(raw_vals).drop(columns=["price_adjust"])
    legacy.attrs["adjust"] = "none"
    check("老帧 attrs['adjust']=none 仍被拦截", raises(ind.ATR, legacy))

    # 4.4 price_adjust 列优先于 attrs：列=qfq、attrs=none → 放行（列是权威源）
    prio = make_df(closes, adjust="qfq")
    prio.attrs["adjust"] = "none"
    ok_prio = not raises(ind.ATR, prio)
    check("price_adjust 列优先于易失 attrs", ok_prio)

    # 4.5 显式 adjust 参数
    check("显式 adjust='qfq' 可绕过缺失的列/attrs",
          not raises(ind.STD, df["close"], 20, "qfq"))

    # 4.6 列内口径不一致 → 报错
    mixed = make_df(closes).copy()
    mixed.loc[mixed.index[:5], "price_adjust"] = "none"
    check("帧内复权口径混合时直接报错", raises(ind.ATR, mixed))

    # 4.7 B3 多标的帧按 symbol 分组口径：A=qfq + B=none → 波动率类必须全部拦截
    multi = pd.concat([make_df(closes).assign(symbol="600519"),
                       make_df(raw_vals, adjust="none").assign(symbol="000001")])
    raised = sum(raises(fn, multi) for fn in (ind.ATR, ind.STD, ind.HIST_VOL))
    check("B3 多标的帧 A=qfq + B=none 时波动率类全部报错", raised == 3, f"拦截 {raised}/3")

    # 4.8 2:1 拆股缺口：不复权 ATR 明显大于复权
    raw_split = list(np.array(closes, dtype=float))
    adj_split = list(np.array(closes, dtype=float))
    cut = len(raw_split) // 2
    raw_split[cut:] = [v / 2.0 for v in raw_split[cut:]]
    atr_raw = ind.ATR(make_df(raw_split, "none").assign(price_adjust="qfq"), 14).dropna()
    atr_adj = ind.ATR(make_df(adj_split, "qfq"), 14).dropna()
    check("ATR 不复权 > 复权（除权缺口会放大波动率）",
          float(atr_raw.max()) > float(atr_adj.max()) * 1.5,
          f"raw_max={atr_raw.max():.4f} adj_max={atr_adj.max():.4f}")

    # ---------- 5. A2 预热期 + B2 反推 ----------
    req = {k: ind.required_bars(k, **({"n": 14} if k in ("RSI", "ATR", "ADX") else {}))
           for k in ("EMA", "RSI", "ADX", "SAR", "MACD")}
    ema_req, macd_req = ind.required_bars("EMA", n=12), ind.required_bars("MACD")
    table_lower = (ema_req >= config.INDICATOR_HARDENING["warmup"]["EMA"]
                   and macd_req >= config.INDICATOR_HARDENING["warmup"]["MACD"]
                   and ind.required_bars("OBV") == 1)
    check("required_bars 以表值为下界、由预热收敛反推抬高（不再查表）", table_lower,
          f"EMA={ema_req}(表{config.INDICATOR_HARDENING['warmup']['EMA']}) "
          f"MACD={macd_req}(表{config.INDICATOR_HARDENING['warmup']['MACD']}) "
          f"ADX={ind.required_bars('ADX', n=14)} SAR={ind.required_bars('SAR')} "
          f"RSI={ind.required_bars('RSI', n=14)}")

    # B2 硬校验：在 required_bars 处初始条件扰动影响 <= 1e-3；按表值 20/35 取会超标
    sample = ind._burnin_sample(900)
    perturbed = sample.copy()
    perturbed[0] *= 1.5

    def _rel_err(a, b):
        scale = max(float(np.nanmax(np.abs(b))), 1e-12)
        with np.errstate(invalid="ignore"):
            e = np.abs(np.asarray(a) - np.asarray(b)) / scale
        return np.where(np.isnan(e), 0.0, e)

    ema_a = ind._ema_raw(pd.Series(sample), 12).to_numpy()
    ema_b = ind._ema_raw(pd.Series(perturbed), 12).to_numpy()
    err_ema = _rel_err(ema_a, ema_b)
    ema_at_req = float(err_ema[ema_req - 1:].max())
    ema_at_table = float(err_ema[config.INDICATOR_HARDENING["warmup"]["EMA"] - 1])
    macd_a = np.atleast_2d(ind._burnin_raw("MACD", sample, {"slow": 26, "signal": 9}))
    macd_b = np.atleast_2d(ind._burnin_raw("MACD", perturbed, {"slow": 26, "signal": 9}))
    err_macd = _rel_err(macd_a, macd_b)
    macd_at_req = float(err_macd[:, macd_req - 1:].max())
    macd_at_table = float(err_macd[:, config.INDICATOR_HARDENING["warmup"]["MACD"] - 1].max())
    check("B2 递归指标在 required_bars 处扰动相对误差 <= 1e-3",
          ema_at_req <= 1e-3 and macd_at_req <= 1e-3,
          f"EMA@{ema_req}={ema_at_req:.2e} MACD@{macd_req}={macd_at_req:.2e}")
    check("B2 按表值 20/35 取预热会超标（证明表值不可直接使用）",
          ema_at_table > 1e-3 and macd_at_table > 1e-3,
          f"EMA@20={ema_at_table:.2e} MACD@35={macd_at_table:.2e}")

    warm_ok = True
    details = []
    for label, series, bars in [
        ("EMA", ind.EMA(df, 12), req["EMA"]),
        ("RSI", ind.RSI(df, 14), req["RSI"]),
        ("ADX", ind.ADX(df)["ADX"], req["ADX"]),
        ("SAR", ind.SAR(df), req["SAR"]),
        ("MACD.DEA", ind.MACD(df)["DEA"], req["MACD"]),
    ]:
        head = series.iloc[:bars - 1]
        tail_valid = series.iloc[bars - 1]
        ok = bool(head.isna().all()) and not pd.isna(tail_valid)
        warm_ok &= ok
        details.append(f"{label}: 前{bars - 1}根NaN={bool(head.isna().all())}")
    check("递归指标预热期前 required_bars-1 根为 NaN", warm_ok, "；".join(details))

    # ---------- 5b. B1/B5 预热闸门（物化 warmup_ok，NaN 只是哑弹） ----------
    rsi_bars = ind.required_bars("RSI", n=14)
    idx80 = pd.date_range("2024-01-01", periods=80, freq="B")
    sr = pd.Series(np.linspace(50, 60, 80), index=idx80, name="RSI")
    sr.iloc[:rsi_bars - 1] = np.nan  # 真实指标输出：预热期为 NaN
    frame = ind.attach_warmup_ok(sr, bars=rsi_bars)
    wcol = ind._warmup_col()
    check("B1 attach_warmup_ok 物化布尔列（前 bars-1 根 False、其后 True）",
          wcol in frame.columns and frame[wcol].dtype == bool
          and bool(frame[wcol].iloc[:rsi_bars - 1].eq(False).all())
          and bool(frame[wcol].iloc[rsi_bars - 1:].eq(True).all()),
          f"bars={rsi_bars} 列={wcol}")

    check("B1 未 fillna 的预热帧可通过信号入口", not raises(ind.assert_signal_frame, frame))

    dirty = frame.copy()
    dirty["RSI"] = dirty["RSI"].fillna(0.0)
    check("B1 预热期 bar 已 fillna(0) 后信号入口仍拒绝出信号",
          raises(ind.assert_signal_frame, dirty))

    check("B1 缺 warmup_ok 列的帧被信号入口拒绝（禁止只看数值 NaN）",
          raises(ind.assert_signal_frame, frame.drop(columns=[wcol])))

    nan_mask = frame.astype({wcol: object}).copy()
    nan_mask.loc[nan_mask.index[0], wcol] = np.nan
    check("B1 warmup_ok 列含 NaN 时拒绝（必须为 True/False）",
          raises(ind.assert_signal_frame, nan_mask))

    # B5：末根 bar 仍在预热期（新上市/刚切周期）→ live 拒绝、backtest 豁免
    lastframe = ind.attach_warmup_ok(sr, bars=len(sr) + 10)
    ready_frame = ind.attach_warmup_ok(sr, bars=10)  # 末根已过预热
    check("B5 末根仍在预热期时 last_bar_ready=False", ind.last_bar_ready(lastframe) is False)
    check("B5 live 模式下末根预热拒绝对该标的出信号",
          raises(ind.assert_last_bar_ready, lastframe, "live"))
    check("B5 paper 模式同样拒绝",
          raises(ind.assert_last_bar_ready, lastframe, "paper"))
    check("B5 backtest 模式默认豁免", not raises(ind.assert_last_bar_ready, lastframe, "backtest"))
    check("B5 已过预热期的帧 live 放行",
          ind.last_bar_ready(ready_frame) is True
          and not raises(ind.assert_last_bar_ready, ready_frame, "live"))
    check("B1 require_last_bar_ready=True 时信号入口一并联拦末根预热",
          raises(ind.assert_signal_frame, lastframe, None, True, "live"))

    # ---------- 6. 年化基数 ----------
    factors = [ind.annual_factor("1d"), ind.annual_factor("1d", "us_stock"),
               ind.annual_factor("1w"), ind.annual_factor("1M"),
               ind.annual_factor("5min"), ind.annual_factor("60min"),
               ind.annual_factor("1min")]
    check("年化基数全部引用 config.INDICATOR_CONFIG（244/252/52/12/分钟）",
          factors == [244.0, 252.0, 52.0, 12.0, 244 * 48, 244 * 4, 244 * 240],
          f"1d={factors[0]} us={factors[1]} 5min={factors[4]}")
    check("未知周期年化基数直接报错（不静默取默认值）", raises(ind.annual_factor, "3d"))

    hv_d = ind.HIST_VOL(df["close"], 20, "1d", adjust="qfq").dropna()
    hv_m = ind.HIST_VOL(df["close"], 20, "5min", adjust="qfq").dropna()
    check("HIST_VOL 年化按周期缩放（5min/1d = √48）",
          abs(float(hv_m.iloc[-1] / hv_d.iloc[-1]) - (48 ** 0.5)) < 1e-9,
          f"ratio={hv_m.iloc[-1] / hv_d.iloc[-1]:.10f}")

    # ---------- 7. 未来函数校验 ----------
    cut_n = 8
    truncated = df.iloc[:-cut_n]
    future_checks = {
        "MA": lambda d: ind.MA(d, 5),
        "EMA": lambda d: ind.EMA(d, 12),
        "MACD.DIF": lambda d: ind.MACD(d)["DIF"],
        "BOLL.UPPER": lambda d: ind.BOLL(d)["UPPER"],
        "RSI": lambda d: ind.RSI(d, 14),
        "KDJ.K": lambda d: ind.KDJ(d)["K"],
        "ATR": lambda d: ind.ATR(d, 14),
        "STD": lambda d: ind.STD(d, 20),
        "HIST_VOL": lambda d: ind.HIST_VOL(d, 20),
        "ADX": lambda d: ind.ADX(d)["ADX"],
        "SAR": lambda d: ind.SAR(d),
        "OBV": lambda d: ind.OBV(d["close"], d["volume"]),
        "VR": lambda d: ind.VR(d["close"], d["volume"]),
    }
    bad = []
    for name, fn in future_checks.items():
        full = fn(df).iloc[:-cut_n]
        part = fn(truncated)
        same = np.allclose(full.to_numpy(dtype=float), part.to_numpy(dtype=float), equal_nan=True)
        if not same:
            bad.append(name)
    check("未来函数校验：截断尾部后重叠区间指标值不变", not bad,
          f"通过 {len(future_checks) - len(bad)}/{len(future_checks)}" + (f"；异常 {bad}" if bad else ""))

    # ---------- 8. A3 跨市场红线 ----------
    check("evaluation 旧名已物理移除（SHARPE_RATIO 不存在）", not hasattr(ind, "SHARPE_RATIO"))
    check("评估类统一 eval_ 前缀（4 个）",
          all(hasattr(ind, f"eval_{x}") for x in
              ("max_drawdown", "sharpe_ratio", "annual_return", "volatility")))
    check("assert_indicator_usable 缺 market 直接报错（禁止默认放行）",
          raises(ind.assert_indicator_usable, "MA"))
    check("评估类指标禁入实时信号链（eval_sharpe_ratio 抛错）",
          raises(ind.assert_indicator_usable, "eval_sharpe_ratio", "cn_stock", True))
    check("评估类指标允许用于评估（for_signal=False）",
          ind.assert_indicator_usable("eval_sharpe_ratio", "cn_stock", False) is True)
    check("净值型市场禁用 K 线类指标（cn_fund + MA 抛错）",
          raises(ind.assert_indicator_usable, "MA", "cn_fund"))
    check("净值型市场允许净值类指标（cn_fund + eval_annual_return）",
          ind.assert_indicator_usable("eval_annual_return", "cn_fund", False) is True)
    check("交易型市场不受影响（cn_stock + MA）",
          ind.assert_indicator_usable("MA", "cn_stock") is True)
    check("禁止 center=True 窗口（forbid_center 未来函数红线）",
          raises(ind.rolling_window, df["close"], 5, True))

    # ---------- 9. A4 量能只用 volume / 全 0 处置 ----------
    check("缺 volume 列时量能指标直接报错（不回退 amount）",
          raises(ind.VOL_MA, df.drop(columns=["volume"])))
    check("量能默认列读 config.volume_metrics_use=volume",
          config.INDICATOR_CONFIG["volume_metrics_use"] == "volume")

    zero_df = make_df(closes)
    zero_df["volume"] = 0.0
    vm = ind.VOL_MA(zero_df)
    obv = ind.OBV(zero_df["close"], zero_df["volume"])
    vr = ind.VR(zero_df["close"], zero_df["volume"])
    zero_ok = (bool(vm.isna().all().all()) and bool(obv.isna().all()) and bool(vr.isna().all())
               and vm.attrs.get("volume_all_zero") is True
               and obv.attrs.get("volume_all_zero") is True
               and vr.attrs.get("volume_all_zero") is True)
    check("成交量全 0 → 量能指标返回 NaN 并标注（不静默返回 0）", zero_ok)

    # ---------- 10. 其余指标 ----------
    checks_more = []
    kdj = ind.KDJ(df)
    checks_more.append(("KDJ 形状/关系",
                        list(kdj.columns) == ["K", "D", "J"]
                        and bool((kdj.dropna()["J"] - 3 * kdj.dropna()["K"]
                                  + 2 * kdj.dropna()["D"]).abs().max() < 1e-9)))
    vma = ind.VOL_MA(df)
    checks_more.append(("VOL_MA 双线形状", list(vma.columns) == ["VOL_MA5", "VOL_MA10"]))
    roc = ind.ROC(df["close"], 5).dropna()
    manual = (df["close"].iloc[-1] / df["close"].iloc[-6] - 1) * 100
    checks_more.append(("ROC 与 pct_change 一致", close_enough(roc.iloc[-1], manual)))
    willr = ind.WILLR(df).dropna()
    checks_more.append(("WILLR 取值 [-100,0]", bool(willr.between(-100, 0).all())))
    cci = ind.CCI(df).dropna()
    checks_more.append(("CCI 有限值", bool(np.isfinite(cci).all())))
    obv_ok = ind.OBV(df["close"], df["volume"]).diff().dropna()
    expect = np.sign(df["close"].diff().dropna()) * df["volume"].iloc[1:]
    checks_more.append(("OBV 逐日增量=±volume", bool(np.allclose(obv_ok, expect))))
    checks_more.append(("VR > 0", bool((ind.VR(df["close"], df["volume"]).dropna() > 0).all())))
    adx = ind.ADX(df).dropna()
    checks_more.append(("ADX/DI 列齐全且 ADX∈[0,100]",
                        list(adx.columns) == ["ADX", "PLUS_DI", "MINUS_DI"]
                        and bool(adx["ADX"].between(0, 100).all())))
    sar = ind.SAR(df).dropna()
    checks_more.append(("SAR 无异常值且有值",
                        len(sar) > 0 and bool(np.isfinite(sar).all())))
    checks_more.append(("ATR 恒为正", bool((ind.ATR(df, 14).dropna() > 0).all())))
    sma_tdx = ind.SMA(df["close"], 5, 2, init=50.0)
    k0 = ind.required_bars("SMA", n=5) - 1
    manual_sma = 50.0
    for v in closes[:k0 + 1]:
        manual_sma = (2 * v + 3 * manual_sma) / 5
    checks_more.append(("通达信 SMA 预热后末值等于手算递推",
                        close_enough(sma_tdx.iloc[k0], manual_sma)))
    for label, ok in checks_more:
        check(label, bool(ok))

    # ---------- 11. 期权 ----------
    sigma_true, S0, K, T0, r0 = 0.3, 100.0, 100.0, 0.5, 0.02
    price = float(np.asarray(ind._bs_price(S0, K, T0, r0, sigma_true, "call")))
    iv = ind.IMPLIED_VOL(price, S0, K, T0, r0, "call")
    check("IV 反解可还原真实波动率（0.3）", abs(iv - sigma_true) < 1e-6, f"iv={iv:.8f}")
    put_price = float(np.asarray(ind._bs_price(S0, K, T0, r0, sigma_true, "put")))
    iv_put = ind.IMPLIED_VOL(put_price, S0, K, T0, r0, "put")
    check("看跌 IV 反解同样成立", abs(iv_put - sigma_true) < 1e-6, f"iv_put={iv_put:.8f}")

    # B4：脏数据（市价低于内在价值 / 已到期）→ NaN + iv_solved=False，禁止返回二分区间下界
    iv_dirty, solved_dirty = ind.IMPLIED_VOL(0.5, S0, 90.0, T0, r0, "call", return_status=True)
    check("B4 市价低于内在价值 → IV=NaN 且 iv_solved=False（不返回区间下界）",
          bool(np.isnan(iv_dirty)) and solved_dirty is False,
          f"iv={iv_dirty} solved={solved_dirty}")
    iv_expired, solved_expired = ind.IMPLIED_VOL(12.0, S0, 90.0, 0.0, r0, "call", return_status=True)
    check("B4 T=0 已到期 → IV=NaN 且 iv_solved=False",
          bool(np.isnan(iv_expired)) and solved_expired is False,
          f"iv={iv_expired} solved={solved_expired}")
    iv_ok, solved_ok = ind.IMPLIED_VOL(price, S0, K, T0, r0, "call", return_status=True)
    check("B4 正常报价仍能解出 IV 且 iv_solved=True",
          solved_ok is True and abs(iv_ok - sigma_true) < 1e-6, f"iv={iv_ok:.8f}")

    def bs(s: float = sigma_true, S: float = S0, T: float = T0, r: float = r0) -> float:
        return float(np.asarray(ind._bs_price(S, K, T, r, s, "call")))

    num_delta = (bs(S=S0 + 0.01) - bs(S=S0 - 0.01)) / 0.02
    num_gamma = (bs(S=S0 + 0.01) + bs(S=S0 - 0.01) - 2 * bs(S=S0)) / 0.0001
    num_vega = (bs(s=sigma_true + 0.01) - bs(s=sigma_true - 0.01)) / 2.0
    num_theta = bs(T=T0 - 1.0 / 365.0) - bs(T=T0)
    num_rho = (bs(r=r0 + 0.01) - bs(r=r0 - 0.01)) / 2.0

    delta = float(np.asarray(ind.DELTA(S0, K, T0, r0, sigma_true, "call")))
    gamma = float(np.asarray(ind.GAMMA(S0, K, T0, r0, sigma_true)))
    vega = float(np.asarray(ind.VEGA(S0, K, T0, r0, sigma_true)))
    theta = float(np.asarray(ind.THETA(S0, K, T0, r0, sigma_true, "call")))
    rho = float(np.asarray(ind.RHO(S0, K, T0, r0, sigma_true, "call")))
    check("DELTA 单位=标的每变动 1.0（BS 重定价核对）", abs(delta - num_delta) < 1e-3,
          f"{delta:.6f} vs {num_delta:.6f}")
    check("GAMMA 单位=标的每变动 1.0（BS 重定价核对）", abs(gamma - num_gamma) < 1e-3,
          f"{gamma:.6f} vs {num_gamma:.6f}")
    check("VEGA 单位=波动率每 1 个百分点（BS 重定价核对）", abs(vega - num_vega) < 1e-3,
          f"{vega:.6f} vs {num_vega:.6f}")
    check("THETA 单位=每 1 个自然日（BS 重定价核对）", abs(theta - num_theta) < 1e-3,
          f"{theta:.6f} vs {num_theta:.6f}")
    check("RHO 单位=利率每 1 个百分点（BS 重定价核对）", abs(rho - num_rho) < 1e-3,
          f"{rho:.6f} vs {num_rho:.6f}")
    check("看涨 Delta ∈ (0,1)、看跌 ∈ (-1,0)",
          bool(0 < delta < 1)
          and bool(-1 < float(np.asarray(ind.DELTA(S0, K, T0, r0, sigma_true, "put"))) < 0))
    check("Gamma/Vega 为正、Theta 为负、看涨 Rho 为正、看跌 Rho 为负",
          gamma > 0 and vega > 0 and theta < 0 and rho > 0
          and float(np.asarray(ind.RHO(S0, K, T0, r0, sigma_true, "put"))) < 0)

    ivs = pd.Series(np.linspace(0.15, 0.45, 60))
    rank = ind.IV_RANK(ivs, 20).dropna()
    pct = ind.IV_PERCENTILE(ivs, 20).dropna()
    check("IV_RANK / IV_PERCENTILE ∈ [0,100]，末值=100",
          bool(rank.between(0, 100).all()) and bool(pct.between(0, 100).all())
          and close_enough(rank.iloc[-1], 100.0) and close_enough(pct.iloc[-1], 100.0),
          f"rank末值={rank.iloc[-1]:.2f} pct末值={pct.iloc[-1]:.2f}")

    # ---------- 12. 净值评估类 ----------
    nav = pd.Series([1.0, 1.05, 1.10, 1.05, 1.08])
    mdd = ind.eval_max_drawdown(nav)
    check("eval_max_drawdown 计算正确（1.10→1.05 = -4.5454%）",
          close_enough(mdd.min(), -0.05 / 1.10, 1e-9), f"min={mdd.min():.6f} 预期={-0.05 / 1.10:.6f}")

    nav2 = pd.Series(np.linspace(1.0, 1.2, 245))
    ar = ind.eval_annual_return(nav2)
    expect_ar = (1.2 / 1.0) ** (244 / 244) - 1
    check("eval_annual_return 口径正确（按年化基数复利）", close_enough(ar, expect_ar, 1e-9),
          f"{ar:.6f} vs {expect_ar:.6f}")

    ret = nav2.pct_change().dropna()
    vol = ind.eval_volatility(nav2)
    check("eval_volatility = 收益率标准差 × √244",
          close_enough(vol, float(ret.std(ddof=1) * np.sqrt(244)), 1e-9), f"{vol:.6f}")

    rf = config.INDICATOR_CONFIG["risk_free_rate"]
    excess = ret - rf / 244
    sharpe = ind.eval_sharpe_ratio(nav2)
    check("eval_sharpe_ratio 口径正确（超额收益/波动 × √244）",
          close_enough(sharpe, float(excess.mean() / excess.std(ddof=1) * np.sqrt(244)), 1e-9),
          f"{sharpe:.6f}")

    # ---------- 13. 期货 ----------
    spot, fut = pd.Series([100.0, 101.0]), pd.Series([102.0, 100.0])
    check("BASIS = 现货 - 期货", list(ind.BASIS(spot, fut)) == [-2.0, 1.0])
    check("BASIS_RATE = 基差/期货",
          np.allclose(ind.BASIS_RATE(spot, fut), [-2 / 102, 1 / 100]))
    ry = ind.ROLL_YIELD(pd.Series([100.0]), pd.Series([105.0]), 30)
    check("ROLL_YIELD 年化口径正确",
          close_enough(float(ry.iloc[0]), (100 / 105 - 1) * 365 / 30, 1e-12),
          f"{float(ry.iloc[0]):.6f}")

    print("\n" + "=" * 62)
    print(f"  通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("  失败项：", FAIL)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
