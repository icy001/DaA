"""第 6 步开工前置：闸门一致性测试（core/signal_gate.py）

覆盖 C1–C4：
  C1 闸门只有一份实现（signal_gate），轻量 runner 与 Backtester 都调用它：
     - bar_dict 必须带 warmup_ok，缺列报错；
     - 预热期 + 已 fillna(0) 的帧，在两个引擎下 buy() 都被拒单；
     - 开仓严（buy/short）、平仓宽（sell/cover）；
     - 最终裁决收口 place_order（warmup_ok=False 开仓拒、平仓放行）。
  C2 长度门槛 = max(60, strategy.required_bars())，不是硬编码 60：
     - 普通策略 60 根通过、59 根报错；
     - MACD 策略（required_bars≈135）60 根必须报错，避免全段预热静默零成交。
  C3 上一轮指令 A 欠账核查：
     - config 两个常量存在（INDICATOR_WARMUP_GUARD / OPTION_VALUATION_GUARD）；
     - B3 混合复权口径帧算波动率 fail-closed；
     - B4 期权 IV 无解返回 NaN + iv_solved=False；
     - 第 4 步 place_order 预热联动（开仓拒 / 平仓放行）。
  C4 多标的对齐后三个物化列逐标的保留，不退化成一列一个值。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from core import indicators as ind
from core import signal_gate
from core.account import TradingAccount
from core.backtester import Backtester
from core.runner import run_backtest
from core.strategy import BaseStrategy

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'✅' if ok else '❌'} {name}" + (f" | {detail}" if detail else ""))


def raises(fn, *args, **kwargs) -> bool:
    try:
        fn(*args, **kwargs)
    except Exception:
        return True
    return False


# ==================== 桩数据 ====================

class FakeFetcher:
    """可复现日线（不联网）。"""

    def __init__(self, n: int = 420):
        self.n = int(n)
        idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=self.n)
        # 随机游走（固定种子）：线性无噪声价格会被未来函数检测判为「与次日收益高相关」
        ret = np.random.default_rng(42).normal(0.0003, 0.01, self.n)
        close = 100.0 * np.cumprod(1 + ret)
        self.frame = pd.DataFrame({
            "open": close, "high": close * 1.01, "low": close * 0.99,
            "close": close, "volume": np.full(self.n, 1_000_000.0),
            "amount": close * 1_000_000.0,
        }, index=idx)
        self.frame["price_adjust"] = "qfq"
        self.frame.attrs["adjust"] = "qfq"

    def get_daily(self, symbol, start_date=None, end_date=None, adjust="qfq",
                  market_type=None, **kwargs):
        return self.frame.copy()

    def get_kline(self, symbol, start_date=None, end_date=None, period="1d",
                  adjust="qfq", market_type=None, **kwargs):
        return self.frame.copy()


class CaptureStrategy(BaseStrategy):
    """记录每根 bar 的 warmup_ok，并在预热期也尝试买入（应由闸门拒单）。"""

    meta = {
        "name": "_gate_capture", "display_name": "闸门探针", "markets": ["cn_stock"],
        "periods": ["1d"], "params": {}, "description": "test",
        "warmup": [("RSI", {"n": 14})],
    }

    def init(self):
        self.flags = []
        self.bar_keys = []
        self.attempts = []          # [(warmup_ok, status)]
        self._done = False

    def on_bar(self, date, bars):
        bar = bars["600519"]
        self.flags.append(bool(bar.get("warmup_ok")))
        self.bar_keys.append(set(bar.keys()))
        if self._done:
            return
        res = self.buy("600519", 100)
        self.attempts.append((bool(bar.get("warmup_ok")), res.get("status")))
        if res.get("status") == "filled" and bar.get("warmup_ok"):
            self._done = True


class FillNaGateStrategy(BaseStrategy):
    """预热期把 RSI fillna(0) 后照发买入信号（典型错误写法）。"""

    meta = {
        "name": "_gate_fillna", "display_name": "fillna 探针", "markets": ["cn_stock"],
        "periods": ["1d"], "params": {}, "description": "test",
        "warmup": [("RSI", {"n": 14})],
    }

    def init(self):
        self.attempts = []
        self._done = False

    def on_bar(self, date, bars):
        bar = bars["600519"]
        idx = pd.date_range("2024-01-01", periods=40, freq="B")
        frame = pd.DataFrame({"RSI": [np.nan] * 30 + [45.0] * 10}, index=idx)
        frame = ind.attach_warmup_ok(frame, bars=35)
        frame["RSI"] = frame["RSI"].fillna(0.0)     # 预热期被填成 0（RSI=极度超卖）
        del frame                                  # 帧只用于说明「已 fillna」
        if self._done:
            return
        res = self.buy("600519", 100)
        self.attempts.append((bool(bar.get("warmup_ok")), res.get("status")))
        if res.get("status") == "filled" and bar.get("warmup_ok"):
            self._done = True


class MacdStrategy(BaseStrategy):
    meta = {"name": "_gate_macd", "periods": ["1d"], "params": {},
            "warmup": [("MACD", {})], "description": "test"}

    def on_bar(self, date, bars):
        pass


def main() -> int:
    # ---------- C1 / config：常量存在 ----------
    conf = signal_gate.config_snapshot()
    check("config 已合并 GATE_CONFORMANCE（5 个键齐全）",
          set(conf) == {"gate_module", "enforce_at", "feed_warmup_ok_into",
                        "min_backtest_bars", "preserve_columns_on_align"}, str(conf))
    check("C3 两个常量已在 config.py",
          isinstance(getattr(config, "INDICATOR_WARMUP_GUARD", None), dict)
          and isinstance(getattr(config, "OPTION_VALUATION_GUARD", None), dict))

    # ---------- C1 / bar_dict ----------
    check("warmup_flag 边界（seen=warmup 才算过预热）",
          signal_gate.warmup_flag(4, 5) is False and signal_gate.warmup_flag(5, 5) is True)
    seen = {"600519": 2}
    bars = signal_gate.build_bar_dict({"600519": {"close": 10.0}}, seen, 3,
                                      pd.Timestamp("2024-01-02"))
    check("build_bar_dict 逐标的写入 warmup_ok",
          bars["600519"]["warmup_ok"] is False and bars["600519"]["date"] is not None)
    check("缺 warmup_ok 的 bar_dict 直接报错",
          raises(signal_gate.assert_bar_dict, {"600519": {"close": 10.0}}))
    check("warmup_ok=NaN 直接报错",
          raises(signal_gate.assert_bar_dict, {"600519": {"close": 10.0, "warmup_ok": np.nan}}))
    strat = CaptureStrategy(account=TradingAccount(1_000_000, run_mode="backtest"))
    check("dispatch_bar 缺 warmup_ok 报错（策略入口不默认放行）",
          raises(strat.dispatch_bar, pd.Timestamp("2024-01-02"),
                 {"600519": {"close": 100.0}}))

    # ---------- C1 / check_order 开严平宽 ----------
    check("check_order：buy/short 预热期拒单",
          signal_gate.check_order("buy", False, "600519")["stage"] == "warmup"
          and signal_gate.check_order("short", False, "600519")["stage"] == "warmup")
    check("check_order：sell/cover 预热期放行",
          signal_gate.check_order("sell", False, "600519") is None
          and signal_gate.check_order("cover", False, "600519") is None)
    check("check_order：已过预热开仓放行",
          signal_gate.check_order("buy", True, "600519") is None)

    # ---------- C2 / 长度门槛 ----------
    plain = CaptureStrategy(account=TradingAccount(1_000_000, run_mode="backtest"))
    macd = MacdStrategy(account=TradingAccount(1_000_000, run_mode="backtest"))
    check("C2 普通策略门槛 = max(60, required_bars)",
          signal_gate.min_backtest_bars(plain) == max(60, plain.required_bars()),
          f"need={signal_gate.min_backtest_bars(plain)}")
    check("C2 MACD 策略门槛 > 60（不是硬编码 60）",
          signal_gate.min_backtest_bars(macd) == macd.required_bars()
          and macd.required_bars() > 60,
          f"need={signal_gate.min_backtest_bars(macd)}")
    check("C2 60 根对 MACD 策略必须报错（否则全段预热、静默零成交）",
          raises(signal_gate.ensure_min_bars, 60, None, macd.required_bars())
          and signal_gate.ensure_min_bars(60, None, 30) == 60)

    # ---------- C4 / 多标的对齐 ----------
    d = pd.bdate_range("2024-01-01", periods=7)
    fa = pd.DataFrame({"close": 1.0, "price_adjust": "qfq",
                       "data_asof_date": d[4], "warmup_ok": True}, index=d[:5])
    fb = pd.DataFrame({"close": 2.0, "price_adjust": "none",
                       "data_asof_date": d[6], "warmup_ok": False}, index=d[2:])
    aligned = signal_gate.align_frames({"A": fa, "B": fb})
    ok_align = (len(aligned["A"]) == 3 and len(aligned["B"]) == 3
                and set(aligned["A"].index) == set(aligned["B"].index)
                and (aligned["A"]["price_adjust"] == "qfq").all()
                and (aligned["B"]["price_adjust"] == "none").all()
                and (aligned["A"]["data_asof_date"] == d[4]).all()
                and (aligned["B"]["data_asof_date"] == d[6]).all()
                and (aligned["A"]["warmup_ok"] == True).all()      # noqa: E712
                and (aligned["B"]["warmup_ok"] == False).all())    # noqa: E712
    check("C4 对齐后三个物化列逐标的保留（不广播、不退化）", ok_align,
          f"A={aligned['A']['price_adjust'].unique()} B={aligned['B']['price_adjust'].unique()}")

    # ---------- C1 / 引擎一致性：runner vs Backtester ----------
    fetcher = FakeFetcher(420)
    runner_res = run_backtest(CaptureStrategy, symbols=["600519"], fetcher=fetcher,
                              start="2023-01-01", end="2026-12-31")
    r_strat = runner_res["strategy"]
    warm_attempts = [s for ok, s in r_strat.attempts if not ok]
    first_fill = next((i for i, (ok, s) in enumerate(r_strat.attempts)
                       if ok and s in ("filled", "pending")), None)
    check("runner：bar_dict 带 warmup_ok，且首笔成交在预热期之后",
          all("warmup_ok" in keys for keys in r_strat.bar_keys)
          and first_fill is not None and first_fill >= r_strat.warmup_bars - 1,
          f"warmup_bars={r_strat.warmup_bars} first_fill={first_fill}")
    check("runner：预热期 buy() 全部被拒（stage=warmup）",
          len(warm_attempts) > 0 and all(s == "rejected" for s in warm_attempts)
          and all(r.get("stage") == "warmup" for r in r_strat.rejected_orders),
          f"warm_attempts={len(warm_attempts)}")

    bt = Backtester(CaptureStrategy, symbols=["600519"], start_date="2023-01-01",
                    end_date="2026-12-31", fetcher=FakeFetcher(420))
    bt.run()
    bt_strat = bt.strategy
    bt_warm = [s for ok, s in bt_strat.attempts if not ok]
    # E1（next_open）：Backtester 信号当根返回 pending（下一根成交），runner 为第 5 步
    # 轻量执行器（收盘价即时成交）→ 二者都以「未被闸门拒绝」为放行口径
    bt_first = next((i for i, (ok, s) in enumerate(bt_strat.attempts)
                     if ok and s in ("filled", "pending")), None)
    check("Backtester：bar_dict 确实带 warmup_ok 列",
          bool(bt.last_bar_dict) and all("warmup_ok" in b for b in bt.last_bar_dict.values()))
    check("Backtester：预热期 buy() 全部被拒",
          len(bt_warm) > 0 and all(s == "rejected" for s in bt_warm),
          f"warm_attempts={len(bt_warm)}")
    check("两个引擎行为一致（同一策略同一条拒单边界）",
          bt_first == first_fill and len(bt_warm) == len(warm_attempts),
          f"runner={first_fill} backtester={bt_first}")

    # ---------- C1 / 预热期 + fillna(0)：两引擎都拒 ----------
    fn_runner = run_backtest(FillNaGateStrategy, symbols=["600519"], fetcher=FakeFetcher(420),
                             start="2023-01-01", end="2026-12-31")
    fn_bt = Backtester(FillNaGateStrategy, symbols=["600519"], start_date="2023-01-01",
                       end_date="2026-12-31", fetcher=FakeFetcher(420))
    fn_bt.run()
    r_warm = [s for ok, s in fn_runner["strategy"].attempts if not ok]
    b_warm = [s for ok, s in fn_bt.strategy.attempts if not ok]
    check("预热期 + fillna(0) 的帧：runner 下 buy() 被拒单",
          len(r_warm) > 0 and all(s == "rejected" for s in r_warm), f"{len(r_warm)} 次全拒")
    check("预热期 + fillna(0) 的帧：Backtester 下 buy() 被拒单",
          len(b_warm) > 0 and all(s == "rejected" for s in b_warm), f"{len(b_warm)} 次全拒")

    # ---------- C3 / place_order 最终裁决 ----------
    acct = TradingAccount(1_000_000, run_mode="backtest")
    r_open = acct.place_order("600519", "buy", "market", 100, 100.0, warmup_ok=False)
    check("C3 place_order：warmup_ok=False 开仓拒单",
          r_open["status"] == "rejected" and "预热" in r_open.get("reason", ""))
    ok_open = acct.place_order("600519", "buy", "market", 100, 100.0, warmup_ok=True)
    # 换日到「明天」解除 T+1 冻结，再验证平仓不受预热闸门限制
    acct.roll_to((pd.Timestamp.today().normalize() + pd.Timedelta(days=1)).date())
    r_close = acct.place_order("600519", "sell", "market", 100, 101.0, warmup_ok=False)
    check("C3 place_order：warmup_ok=False 平仓放行",
          ok_open["status"] == "filled" and r_close["status"] == "filled",
          f"open={ok_open['status']} close={r_close['status']}")

    # ---------- C3 / B3 混合口径 fail-closed ----------
    mixed = pd.DataFrame({
        "close": np.linspace(10, 12, 30), "high": np.linspace(10, 12, 30),
        "low": np.linspace(9.8, 11.8, 30), "symbol": ["A"] * 15 + ["B"] * 15,
        "price_adjust": ["qfq"] * 15 + ["none"] * 15,
    }, index=pd.bdate_range("2024-01-01", periods=30))
    check("C3 B3：混合复权口径帧算 ATR 直接报错（fail-closed）",
          raises(ind.ATR, mixed, n=14))

    # ---------- C3 / B4 期权 IV 无解 ----------
    iv, solved = ind.IMPLIED_VOL(0.5, 100.0, 90.0, 0.05, 1.0, return_status=True)
    check("C3 B4：市价低于内在价值 → NaN 且 iv_solved=False",
          np.isnan(iv) and solved is False, f"iv={iv} solved={solved}")

    print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
    if FAIL:
        print("失败项：" + "；".join(FAIL))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
