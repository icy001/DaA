"""第 5 步：策略基类与执行器测试（不依赖网络）。

覆盖：
  1) 5.0 预热闸门：预热期 buy() 直接被策略层拒单，不进入账户层；
  2) 预热期 + 已 fillna(0) 的指标帧 → 信号入口仍拒绝（不会把 RSI=0 当极度超卖）；
  3) get_history(n) 少于 required_bars(indicator) 抛错；否则带 attrs["warmup_ok"]；
  4) 预热期 sell() 不受限（能止损/平仓）；
  5) 内置风控：单标的上限、黑名单、止损自动触发；
  6) 四个环境跑通：回测 / 参数优化 / 模拟盘 / 实盘仿真（同一策略零改动）；
  7) 执行器逐 bar 注入 warmup_ok（前 N 根 False、之后 True）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import indicators as ind
from core.account import Position, TradingAccount
from core.runner import StrategyRunner, run_backtest, run_optimize, run_paper
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
    """返回一段可复现的日线；不联网。"""

    def __init__(self, n: int = 420, end=None, start_price: float = 100.0,
                 slope: float = 0.05, drop_at: int = None, drop_pct: float = 0.0):
        self.n = int(n)
        self.end = pd.Timestamp(end or pd.Timestamp.today().normalize())
        idx = pd.bdate_range(end=self.end, periods=self.n)
        close = start_price + slope * np.arange(self.n)
        if drop_at is not None:
            close[drop_at:] *= (1.0 - drop_pct)
        self.frame = pd.DataFrame({
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(self.n, 1_000_000.0),
            "amount": close * 1_000_000.0,
        }, index=idx)
        self.frame.attrs["adjust"] = "qfq"
        self.frame.attrs["price_adjust"] = "qfq"
        self.frame["price_adjust"] = "qfq"
        self.calls = 0

    def get_daily(self, symbol, start_date=None, end_date=None, adjust="qfq",
                  fill_missing=False, market_type=None, for_trading=False, **kwargs):
        self.calls += 1
        return self.frame.copy()

    def get_kline(self, symbol, start_date=None, end_date=None, period="1d",
                  adjust="qfq", market_type=None, **kwargs):
        return self.frame.copy()


class ProbeStrategy(BaseStrategy):
    """只记录 warmup_ok，并在预热结束后买一次。"""

    meta = {
        "name": "_probe", "display_name": "测试探针", "markets": ["cn_stock"],
        "periods": ["1d"], "params": {"buy_after": 1}, "description": "test",
        "warmup": [("RSI", {"n": 14})],
    }

    def init(self):
        self.flags = []
        self._bought = False

    def on_bar(self, date, bars):
        bar = bars.get("600519") or next(iter(bars.values()))
        self.flags.append(bool(bar.get("warmup_ok")))
        if not self.flags or len(self.flags) < self.params["buy_after"]:
            return
        if not self._bought and self.get_position("600519") is None:
            if self.buy("600519", 100).get("status") == "filled":
                self._bought = True


class FillNaLeakStrategy(BaseStrategy):
    """模拟「策略自己 fillna(0) 后出信号」的错误写法。"""

    meta = {"name": "_leak", "display_name": "泄漏测试", "markets": ["cn_stock"],
            "periods": ["1d"], "params": {}, "description": "test",
            "warmup": [("RSI", {"n": 14})]}

    def on_bar(self, date, bars):
        idx = pd.date_range("2024-01-01", periods=40, freq="B")
        frame = pd.DataFrame({"RSI": [np.nan] * 30 + [45.0] * 10}, index=idx)
        frame = ind.attach_warmup_ok(frame, bars=35)   # 前 34 根预热期
        frame["RSI"] = frame["RSI"].fillna(0.0)         # 典型错误：预热期填 0
        self.assert_signal_frame(frame)                 # 必须在这里报错
        self.buy("600519", 100)


def main() -> int:
    # ---------- 1. 直接构造策略：预热闸门 ----------
    acct = TradingAccount(1_000_000, run_mode="backtest")
    strat = ProbeStrategy(account=acct, params={"buy_after": 1})
    rsi_need = ind.required_bars("RSI", n=14)
    check("warmup_bars 由 meta['warmup'] 反推（>= RSI 预热根数）",
          strat.warmup_bars >= rsi_need, f"warmup_bars={strat.warmup_bars} need={rsi_need}")

    strat.dispatch_bar(pd.Timestamp("2024-01-02"),
                       {"600519": {"close": 100.0, "warmup_ok": False}})
    r_buy = strat.buy("600519", 100)
    check("预热期 buy() 被策略层拒单（不进入账户层）",
          r_buy["status"] == "rejected" and r_buy.get("stage") == "warmup"
          and not acct.positions and not acct.trades,
          r_buy.get("reason", ""))

    r_short = strat.short("600519", 100)
    check("预热期 short() 同样被拒", r_short["status"] == "rejected"
          and r_short.get("stage") == "warmup")

    # 预热期平仓放行：手工塞一个可用持仓
    acct.positions["600519"] = Position(symbol="600519", market="cn_stock",
                                        volume=100, avg_cost=90.0, last_price=100.0)
    r_sell = strat.sell("600519", 100)
    check("预热期 sell() 放行（能止损/平仓）",
          r_sell["status"] == "filled", r_sell.get("reason", ""))

    # 过了预热期：开仓可成交
    strat2 = ProbeStrategy(account=TradingAccount(1_000_000, run_mode="backtest"),
                           params={"buy_after": 1})
    strat2.dispatch_bar(pd.Timestamp("2024-06-03"),
                        {"600519": {"close": 100.0, "warmup_ok": True}})
    r_ok = strat2.buy("600519", 100)
    check("预热期结束后 buy() 正常成交", r_ok["status"] == "filled",
          r_ok.get("reason", ""))

    # ---------- 2. 预热期 + fillna(0) 的指标帧 ----------
    leak = FillNaLeakStrategy(account=TradingAccount(1_000_000, run_mode="backtest"))
    check("预热期 fillna(0) 的指标帧被信号入口拒绝（不会当成极度超卖）",
          raises(leak.dispatch_bar, pd.Timestamp("2024-06-03"),
                 {"600519": {"close": 100.0, "warmup_ok": True}}))

    # 正常帧（预热期保持 NaN）可以通过
    good = ind.attach_warmup_ok(
        pd.DataFrame({"RSI": [np.nan] * 34 + [45.0] * 6},
                     index=pd.date_range("2024-01-01", periods=40, freq="B")), bars=35)
    check("预热期保持 NaN 的帧可通过信号入口",
          not raises(leak.assert_signal_frame, good))

    # ---------- 3. get_history ----------
    strat3 = ProbeStrategy(account=TradingAccount(1_000_000, run_mode="backtest"))
    fake = FakeFetcher(n=200)
    strat3.set_history_provider(lambda s, n: fake.frame.tail(n))
    strat3.dispatch_bar(pd.Timestamp("2024-06-03"),
                        {"600519": {"close": 100.0, "warmup_ok": True}})
    check("get_history(n < required_bars(RSI)) 直接抛错",
          raises(strat3.get_history, "600519", rsi_need - 1, "close", "RSI"))
    series = strat3.get_history("600519", rsi_need + 10, "close", "RSI")
    check("get_history 足够长时返回完整序列并带 attrs['warmup_ok']",
          len(series) == rsi_need + 10 and series.attrs.get("warmup_ok") is True,
          f"len={len(series)}")

    # ---------- 4. 内置风控 ----------
    tight = ProbeStrategy(account=TradingAccount(1_000_000, run_mode="backtest"),
                          params={"buy_after": 1, "max_single_symbol_pct": 0.001})
    tight.dispatch_bar(pd.Timestamp("2024-06-03"),
                       {"600519": {"close": 100.0, "warmup_ok": True}})
    r_lim = tight.buy("600519", 100)
    check("单标的持仓超过上限被拒", r_lim["status"] == "rejected"
          and r_lim.get("stage") == "risk", r_lim.get("reason", ""))

    black = ProbeStrategy(account=TradingAccount(1_000_000, run_mode="backtest"),
                          params={"buy_after": 1, "blacklist": ["600519"]})
    black.dispatch_bar(pd.Timestamp("2024-06-03"),
                       {"600519": {"close": 100.0, "warmup_ok": True}})
    r_blk = black.buy("600519", 100)
    check("黑名单标的被拒", r_blk["status"] == "rejected"
          and r_blk.get("stage") == "blacklist")

    stop_acct = TradingAccount(1_000_000, run_mode="backtest")
    stop = ProbeStrategy(account=stop_acct, params={"buy_after": 1, "stop_loss": 0.05})
    stop.dispatch_bar(pd.Timestamp("2024-06-03"),
                      {"600519": {"close": 100.0, "warmup_ok": True}})
    stop.dispatch_bar(pd.Timestamp("2024-06-04"),
                      {"600519": {"close": 90.0, "warmup_ok": True}})
    pos = stop_acct.positions.get("600519")
    check("止损线 -5% 触发自动平仓", pos is None or pos.volume == 0,
          f"volume={getattr(pos, 'volume', 0)}")

    # ---------- 5. 四个环境跑通（同一策略零改动） ----------
    fetcher = FakeFetcher(n=420)
    bt = run_backtest(ProbeStrategy, params={"buy_after": 200}, symbols=["600519"],
                      start="2024-01-01", end="2025-12-31", fetcher=fetcher)
    nav = bt["nav"]
    flags = bt["strategy"].flags
    check("回测跑通并产出现金曲线/绩效", len(nav) > 200 and "sharpe" in bt["metrics"],
          f"bars={len(nav)} trades={bt['metrics']['trade_count']}")
    check("执行器逐 bar 注入 warmup_ok（前 False 后 True）",
          flags and flags[0] is False and flags[-1] is True
          and flags.index(True) >= bt["strategy"].warmup_bars - 1,
          f"first_true={flags.index(True) if True in flags else -1} "
          f"warmup={bt['strategy'].warmup_bars}")
    filled_buys = [t for t in bt["trades"]
                   if t.get("status") == "filled" and t.get("direction") == "buy"]
    first_buy_idx = int(nav.index.get_loc(filled_buys[0]["date"])) if filled_buys else -1
    check("预热期内没有成交开仓（首笔成交在 warmup_bars 之后）",
          bool(filled_buys) and first_buy_idx >= bt["strategy"].warmup_bars - 1,
          f"first_buy_idx={first_buy_idx} warmup={bt['strategy'].warmup_bars}")

    paper = run_paper(ProbeStrategy, params={"buy_after": 200}, symbols=["600519"],
                      start="2024-01-01", fetcher=fetcher)
    check("模拟盘环境跑通（同一策略代码）",
          isinstance(paper["nav"], pd.Series) and len(paper["nav"]) > 0,
          f"mode={paper['run_mode']} bars={len(paper['nav'])}")

    sim = StrategyRunner(ProbeStrategy, params={"buy_after": 200},
                         symbols=["600519"], start="2024-01-01", end="2025-12-31",
                         fetcher=fetcher, run_mode="live_sim").run()
    check("实盘仿真环境跑通（同一策略代码）",
          sim["run_mode"] == "live_sim" and len(sim["nav"]) > 0,
          f"bars={len(sim['nav'])}")

    opt = run_optimize(ProbeStrategy, {"buy_after": [150, 200, 250]},
                       symbols=["600519"], start="2024-01-01", end="2025-12-31",
                       fetcher=fetcher, method="grid", top_n=3)
    check("参数优化环境跑通（复用回测执行器）",
          opt.get("best") is not None and len(opt.get("results", [])) == 3,
          f"best={opt.get('best', {}).get('params')}")

    # ---------- 汇总 ----------
    print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
    if FAIL:
        print("失败项：")
        for item in FAIL:
            print("  -", item)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
