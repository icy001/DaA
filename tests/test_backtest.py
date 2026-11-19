"""第 6 步：全市场透明回测引擎测试（tests/test_backtest.py）

覆盖：
  1) 双均线回测 600519 近 3 年：跑通、指标正常、图表/CSV/JSON 落盘；
  2) 海龟策略回测螺纹钢 RB2510 近 3 年：多空双向、保证金/杠杆指标；
  3) 基金定投回测 161725 近 5 年：cn_fund 路径；
  4) T+1：当天买不能当天卖；
  5) 期货保证金 = 成交价 × 乘数 × 手数 × 保证金率；
  6) 手续费 = config 真实费率（佣金 + 过户费 + 印花税），不是 0；
  7) 预热期 bar 进回测不产生开仓（闸门来自 signal_gate / place_order）；
  8) 成交模型：涨停买不进、跌停卖不出、单笔 ≤ 当日成交量 1%、市价滑点、
     限价单未触发不成交；
  9) 未来函数检测：带 lead 列的帧直接报错；
 10) 长度门槛 = max(60, required_bars())：数据不足必须拒绝。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from core import signal_gate
from core.backtester import Backtester, ExecutionModel, detect_lookahead
from core.strategy import BaseStrategy
from strategies.double_ma_cross import DoubleMACross
from strategies.fund_sip import FundSIP
from strategies.futures_trend_following import FuturesTrendFollowing

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


# ==================== 离线行情 ====================

class FakeFetcher:
    """确定性合成日线（不联网），按标的生成不同波动/趋势。"""

    SPEC = {
        "600519": dict(price=1500.0, drift=0.0004, vol=0.016, volume=2_000_000.0,
                       mult=1.0, period=11),
        "RB2510": dict(price=3500.0, drift=0.0002, vol=0.014, volume=200_000.0,
                       mult=10.0, period=17),
        "161725": dict(price=1.000, drift=0.0003, vol=0.008, volume=100_000_000.0,
                       mult=1.0, period=23),
        "000300": dict(price=3800.0, drift=0.0002, vol=0.010, volume=500_000_000.0,
                       mult=1.0, period=29),
    }

    def __init__(self, years: int = 6, n_bars: int = None):
        self.n = int(n_bars or years * 244)
        self.frames = {}

    def _frame(self, symbol: str) -> pd.DataFrame:
        spec = self.SPEC.get(symbol, dict(price=100.0, drift=0.0002, vol=0.012,
                                          volume=1_000_000.0, mult=1.0, period=13))
        seed = sum(ord(c) for c in symbol) % (2 ** 31)
        rng = np.random.default_rng(seed)
        n = self.n
        idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
        cycle = 0.006 * np.sin(np.arange(n) / spec["period"])
        ret = spec["drift"] + rng.normal(0, spec["vol"], n) + cycle
        close = spec["price"] * np.cumprod(1.0 + ret)
        open_ = close * (1.0 + rng.normal(0, 0.002, n))
        high = np.maximum(open_, close) * (1.0 + np.abs(rng.normal(0, 0.004, n)))
        low = np.minimum(open_, close) * (1.0 - np.abs(rng.normal(0, 0.004, n)))
        volume = spec["volume"] * (1.0 + np.abs(rng.normal(0, 0.2, n)))
        frame = pd.DataFrame({
            "open": open_, "high": high, "low": low, "close": close,
            "volume": volume, "amount": close * volume * spec["mult"],
        }, index=idx)
        frame["price_adjust"] = "qfq"
        return frame

    def get_daily(self, symbol, start_date=None, end_date=None, adjust="qfq",
                  market_type=None, **kwargs):
        symbol = str(symbol)
        if symbol not in self.frames:
            self.frames[symbol] = self._frame(symbol)
        frame = self.frames[symbol]
        if start_date:
            frame = frame[frame.index >= pd.Timestamp(start_date)]
        if end_date:
            frame = frame[frame.index <= pd.Timestamp(end_date)]
        return frame.copy()

    def get_kline(self, symbol, **kwargs):
        return self.get_daily(symbol, **kwargs)


def _window(years: int = 6):
    end = pd.Timestamp.today().normalize()
    start = end - pd.Timedelta(days=int(years * 365.25))
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


# ==================== 探针策略 ====================

class BuyEveryBar(BaseStrategy):
    """预热期也照买（用于验证回测闸门确实拦住了）。"""

    meta = {"name": "_bt_buy_every", "periods": ["1d"], "params": {},
            "warmup": [("RSI", {"n": 14})], "description": "test"}

    def init(self):
        self.attempts = []

    def on_bar(self, date, bars):
        for symbol, bar in bars.items():
            pos = self.get_position(symbol)
            if pos is not None:
                continue
            res = self.buy(symbol, 100)
            self.attempts.append((pd.Timestamp(date), bool(bar["warmup_ok"]),
                                  res.get("status")))


class T1Probe(BaseStrategy):
    """t 根信号买入（t+1 开盘成交）→ t+1 立即卖出，验证 T+1 拒单。"""

    meta = {"name": "_bt_t1", "periods": ["1d"], "params": {},
            "warmup": [("MA", {"n": 4})], "description": "test"}

    def init(self):
        self.submitted = False
        self.done = False
        self.sell_result = None

    def on_bar(self, date, bars):
        if self.done or not self.is_warmup_ok("600519"):
            return
        pos = self.get_position("600519")
        if pos is not None and pos.volume > 0:
            # 成交当根（t+1）立刻卖：T+1 冻结应拒单
            self.sell_result = self.sell("600519", 100)
            self.done = True
        elif not self.submitted:
            self.submitted = True
            self.buy("600519", 100)


class MarginProbe(BaseStrategy):
    """买 1 手螺纹钢，成交后记录保证金占用（next_open 下成交在下一根 bar）。"""

    meta = {"name": "_bt_margin", "periods": ["1d"], "params": {},
            "warmup": [("MA", {"n": 4})], "description": "test"}

    def init(self):
        self.submitted = False
        self.observed = None

    def on_bar(self, date, bars):
        if self.observed is not None:
            return
        pos = self.get_position("RB2510")
        if pos is not None and pos.volume > 0:
            self.observed = {"margin": float(self.account.margin_used),
                             "price": float(pos.avg_cost),
                             "status": "filled"}
            return
        if self.submitted or "RB2510" not in bars or not self.is_warmup_ok("RB2510"):
            return
        self.submitted = True
        self.buy("RB2510", 1)


# ==================== 主测试 ====================

def main() -> int:
    fetcher = FakeFetcher(years=6)
    start, end = _window(3)
    tmp = Path(tempfile.mkdtemp(prefix="bt_test_"))

    # ---------- 1. 双均线 600519 近 3 年 ----------
    bt = Backtester(DoubleMACross, symbols=["600519"], start_date=start, end_date=end,
                    initial_capital=1_000_000.0, fetcher=fetcher)
    res = bt.run()
    m = res.metrics
    check("双均线 600519：回测跑通且净值完整", len(res.nav) > 600 and m.get("days", 0) > 600,
          f"bars={len(res.nav)} days={m.get('days')}")
    check("双均线 600519：有成交且指标正常",
          m.get("trade_count", 0) > 0
          and m.get("total_return") is not None
          and np.isfinite(m.get("sharpe") if m.get("sharpe") is not None else 0.0),
          f"trades={m.get('trade_count')} total_return={m.get('total_return'):.4f}"
          if m.get("total_return") is not None else "no trade")
    check("双均线 600519：分市场/分多空统计存在",
          "cn_stock" in m.get("by_market", {}) and len(m.get("by_direction", {})) > 0)
    check("双均线 600519：回测结束无残留持仓",
          len(bt.account.positions) == 0 and len(bt.account.short_positions) == 0)
    paths = res.save(output_dir=tmp)
    check("双均线 600519：图表与 CSV/JSON 落盘",
          Path(paths["figure"]).exists() and Path(paths["trades"]).exists()
          and Path(paths["equity"]).exists() and Path(paths["metrics"]).exists(),
          Path(paths["figure"]).name)
    check("回测报告文本可生成", "回测报告" in res.report())

    # 手续费：A股买入 = max(成交额×0.00025, 5) + 成交额×0.00001
    opens = res.trades[res.trades["action"] == "open"] if len(res.trades) else res.trades
    if not len(opens):
        check("手续费按 config 真实费率（非 0，佣金+过户费）", False, "无开仓交易")
        check("市价买单按开盘价 + 滑点成交", False, "无开仓交易")
        buy = None
    else:
        buy = opens.iloc[0]
        notional = float(buy["price"]) * float(buy["volume"])
        expected_fee = round(max(notional * 0.00025, 5.0) + notional * 0.00001, 2)
        check("手续费按 config 真实费率（非 0，佣金+过户费）",
              abs(float(buy["commission"]) - expected_fee) <= 0.02
              and float(buy["commission"]) > 0,
              f"actual={buy['commission']} expected={expected_fee}")
        # 滑点：买单成交价 = 当日开盘价 × (1 + slippage)
        first_ts = pd.Timestamp(buy["timestamp"]).normalize()
        open_px = float(fetcher.get_daily("600519").loc[first_ts, "open"])
        check("市价买单按开盘价 + 滑点成交",
              abs(float(buy["price"]) - open_px * (1 + bt.execution.slippage)) < 1e-6,
              f"fill={buy['price']:.4f} open={open_px:.4f}")
    sell = res.trades[(res.trades["action"] == "close") & (res.trades["direction"] == "sell")]
    if len(sell):
        s = sell.iloc[0]
        amt = float(s["price"]) * float(s["volume"])
        exp_sell = round(max(amt * 0.00025, 5.0) + amt * 0.0005 + amt * 0.00001, 2)
        check("A股卖出含印花税 0.05%",
              abs(float(s["commission"]) - exp_sell) <= 0.02,
              f"actual={s['commission']} expected={exp_sell}")

    # ---------- 2. 海龟 RB2510 近 3 年 ----------
    rb = Backtester(FuturesTrendFollowing, symbols=["RB2510"], start_date=start, end_date=end,
                    initial_capital=1_000_000.0, fetcher=FakeFetcher(years=6))
    rb_res = rb.run()
    rb_m = rb_res.metrics
    check("海龟 RB2510：跑通且有交易",
          rb_m.get("trade_count", 0) > 0 and rb_m.get("days", 0) > 600,
          f"trades={rb_m.get('trade_count')}")
    check("海龟 RB2510：多空双向都有成交",
          len([k for k in rb_m.get("by_direction", {}) if k in ("sell", "cover")]) > 0,
          str(list(rb_m.get("by_direction", {}).keys())))
    check("海龟 RB2510：杠杆/保证金指标已输出",
          (rb_m.get("avg_leverage") or 0) > 0
          and (rb_m.get("avg_margin_utilization") or 0) >= 0
          and rb_m.get("margin_call_count") is not None,
          f"avg_lev={rb_m.get('avg_leverage')} margin_util={rb_m.get('avg_margin_utilization')}")

    # 期货保证金 = 成交价 × 乘数 × 手数 × 保证金率（RB 9%）
    bt_mg = Backtester(MarginProbe, symbols=["RB2510"], start_date=start, end_date=end,
                       initial_capital=1_000_000.0, fetcher=FakeFetcher(years=6))
    bt_mg.run()
    probe = bt_mg.strategy.observed
    expected_margin = float(probe["price"]) * 10 * 1 * 0.09 if probe else 0.0
    check("期货保证金 = 成交价 × 乘数 × 手数 × 保证金率",
          probe is not None and probe["status"] == "filled"
          and abs(probe["margin"] - expected_margin) <= max(expected_margin * 0.01, 1.0),
          f"actual={probe['margin']:.2f} expected={expected_margin:.2f}" if probe else "no fill")

    # ---------- 3. 基金定投 161725 近 5 年 ----------
    five_start, five_end = _window(5)
    fund = Backtester(FundSIP, symbols=["161725"], start_date=five_start, end_date=five_end,
                      initial_capital=1_000_000.0, fetcher=FakeFetcher(years=6))
    fund_res = fund.run()
    fund_m = fund_res.metrics
    check("基金定投 161725：跑通且有申购",
          fund_m.get("trade_count", 0) > 0
          and set(fund_res.trades["market"]) == {"cn_fund"},
          f"trades={fund_m.get('trade_count')} markets={set(fund_res.trades['market'])}")
    check("基金定投：净值 > 0 且无做空交易",
          float(fund_res.nav["equity"].iloc[-1]) > 0
          and not fund_res.trades["direction"].isin(["short", "cover"]).any())

    # ---------- 4. T+1 ----------
    t1 = Backtester(T1Probe, symbols=["600519"], start_date=start, end_date=end,
                    initial_capital=1_000_000.0, fetcher=FakeFetcher(years=6))
    t1_res = t1.run()
    sell_rej = t1.strategy.sell_result or {}
    check("T+1：当天买不能当天卖（拒单理由含 T+1）",
          sell_rej.get("status") == "rejected" and "T+1" in str(sell_rej.get("reason")),
          str(sell_rej.get("reason")))

    # ---------- 5. 预热期不产生开仓 ----------
    warm = Backtester(BuyEveryBar, symbols=["600519"], start_date=start, end_date=end,
                      initial_capital=1_000_000.0, fetcher=FakeFetcher(years=6))
    warm_res = warm.run()
    attempts = warm.strategy.attempts
    warm_attempts = [a for a in attempts if not a[1]]
    first_fill_idx = next((i for i, a in enumerate(attempts)
                           if a[2] in ("filled", "pending")), None)
    check("预热期 bar 进回测不产生开仓（全部被闸门拒单）",
          len(warm_attempts) > 0 and all(a[2] == "rejected" for a in warm_attempts),
          f"warm_bars={warm.strategy.required_bars()} rejected={len(warm_attempts)}")
    check("首笔开仓信号发生在预热期之后（next_open：信号排队、下一根成交）",
          first_fill_idx is not None
          and first_fill_idx >= warm.strategy.required_bars() - 1,
          f"first_order={first_fill_idx} required={warm.strategy.required_bars()}")
    check("bar_dict 带 warmup_ok（回测引擎不绕过闸门）",
          bool(warm.last_bar_dict)
          and all("warmup_ok" in b for b in warm.last_bar_dict.values()))

    # ---------- 6. 成交模型细节 ----------
    em = ExecutionModel(slippage=0.001)
    rule = config.get_market_config("cn_stock")
    em.set_context({"600519": {"open": 11.0, "high": 11.0, "low": 11.0,
                               "close": 11.0, "volume": 1_000_000.0}},
                   {"600519": 10.0})
    up = em.check(symbol="600519", direction="buy", action="open", order_type="market",
                  volume=100, price=11.0, market="cn_stock", rule=rule)
    check("涨停买不进", "涨停" in str(up.get("reject")), str(up.get("reject")))
    em.set_context({"600519": {"open": 9.0, "high": 9.0, "low": 9.0,
                               "close": 9.0, "volume": 1_000_000.0}},
                   {"600519": 10.0})
    down = em.check(symbol="600519", direction="sell", action="close", order_type="market",
                    volume=100, price=9.0, market="cn_stock", rule=rule)
    check("跌停卖不出", "跌停" in str(down.get("reject")), str(down.get("reject")))

    em.set_context({"600519": {"open": 100.0, "high": 101.0, "low": 99.0,
                               "close": 100.0, "volume": 10_000.0}},
                   {"600519": 100.0})
    cap = em.check(symbol="600519", direction="buy", action="open", order_type="market",
                   volume=1_000, price=100.0, market="cn_stock", rule=rule)
    check("单笔成交量 ≤ 当日成交量 1%", cap.get("volume") == 100.0,
          f"volume={cap.get('volume')} (10_000 × 1% = 100)")
    check("市价买入价 = 开盘价 × (1+滑点)",
          abs(float(cap["price"]) - 100.0 * 1.001) < 1e-9, str(cap["price"]))
    limit = em.check(symbol="600519", direction="buy", action="open", order_type="limit",
                     volume=100, price=95.0, market="cn_stock", rule=rule)
    check("限价单未触发不成交", "未触发" in str(limit.get("reject")), str(limit.get("reject")))

    # ---------- 7. 未来函数 / 长度门槛 ----------
    leak = FakeFetcher(years=3).get_daily("600519")
    leak["close_lead"] = leak["close"].shift(-1)
    check("未来函数检测：lead 列被识别", len(detect_lookahead(leak, "600519")) > 0,
          str(detect_lookahead(leak, "600519")[:1]))

    class _LeakFetcher(FakeFetcher):
        def get_daily(self, symbol, **kwargs):
            frame = super().get_daily(symbol, **kwargs)
            if symbol == "600519":
                frame = frame.copy()
                frame["close_lead"] = frame["close"].shift(-1)
            return frame

    check("回测数据准备遇到未来列直接拒绝",
          raises(Backtester(DoubleMACross, symbols=["600519"], start_date=start,
                            end_date=end, fetcher=_LeakFetcher(years=3)).run))

    short_fetcher = FakeFetcher(years=1)
    short_start = (pd.Timestamp.today().normalize()
                   - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
    short_end = pd.Timestamp.today().normalize().strftime("%Y-%m-%d")
    check("长度门槛 max(60, required_bars())：数据不足直接报错",
          raises(Backtester(FundSIP, symbols=["161725"], start_date=short_start,
                            end_date=short_end, fetcher=short_fetcher).run))
    check("长度门槛口径与 signal_gate 一致",
          signal_gate.min_backtest_bars(warm.strategy)
          == max(60, warm.strategy.required_bars()))

    print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
    if FAIL:
        print("失败项：" + "；".join(FAIL))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
