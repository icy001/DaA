"""第 7 步：模拟盘交易测试（test_paper_trade.py）

覆盖：
  1) 双均线跑最近 10 个交易日：跑通、有成交、每日账单、账户落盘；
  2) 预热期 bar 在模拟盘不产生开仓；bar_dict 缺 warmup_ok 直接报错；
  3) 账户持久化：中断重启后持仓/资金/挂单还在；
  4) 条件单：止损单价格到位后自动成交（复用 account.place_order）；
  5) 订单管理：挂单 / 改单 / 撤单 / 一篮子调仓；
  6) 记录与对账：手动校正现金与持仓、对账留档；
  7) 偏差分析：相同滑点下模拟盘与回测偏差≈0，超阈值时告警并给出归因线索；
  8) 非交易日跳过；成交/风控/闸门均复用共享模块（不另写）。
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from core.account import TradingAccount
from core.backtester import Backtester
from core.execution import ExecutionModel
from core.paper_trader import PaperTrader
from core.strategy import BaseStrategy
from strategies.double_ma_cross import DoubleMACross
from tests.test_backtest import BuyEveryBar, FakeFetcher

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'✅' if ok else '❌'} {name}" + (f" | {detail}" if detail else ""))


def raises(fn) -> bool:
    try:
        fn()
    except Exception:  # noqa: BLE001
        return True
    return False


# ==================== 离线行情 ====================

def _window(fetcher, symbol: str = "600519"):
    frame = fetcher.get_daily(symbol)
    return (frame.index[0].strftime("%Y-%m-%d"),
            frame.index[-1].strftime("%Y-%m-%d"))


class StepFetcher:
    """前 70 根横盘 100，交易窗口最后阶段跌到 93（用于确定性触发止损单）。"""

    def __init__(self, flat: int = 70, window: int = 10):
        n = flat + window
        idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
        close = np.array([100.0] * (n - 8) + [93.0] * 8)
        self.frame = pd.DataFrame({
            "open": close, "high": close * 1.001, "low": close * 0.999,
            "close": close, "volume": 1_000_000.0, "amount": close * 1_000_000.0,
        }, index=idx)
        self.frame["price_adjust"] = "qfq"

    def get_daily(self, symbol, start_date=None, end_date=None, adjust="qfq",
                  market_type=None, **kwargs):
        if str(symbol) != "600519":
            return pd.DataFrame()
        frame = self.frame
        if start_date:
            frame = frame[frame.index >= pd.Timestamp(start_date)]
        if end_date:
            frame = frame[frame.index <= pd.Timestamp(end_date)]
        return frame.copy()

    def get_kline(self, symbol, **kwargs):
        return self.get_daily(symbol, **kwargs)


class BuyOnceProbe(BaseStrategy):
    """预热结束后买一次并持有（后面靠条件单平仓）。"""

    meta = {"name": "_paper_buy_once", "periods": ["1d"], "params": {},
            "warmup": [("MA", {"n": 20})], "description": "test"}

    def init(self):
        self.done = False

    def on_bar(self, date, bars):
        if self.done:
            return
        for symbol in bars:
            if not self.is_warmup_ok(symbol):
                continue
            # match_price_basis=next_open：信号当根返回 pending（已排队），下一根才成交
            if self.buy(symbol, 100).get("status") in ("filled", "pending"):
                self.done = True


# ==================== 主测试 ====================

def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="paper_test_"))
    try:
        _run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
    return 0 if not FAIL else 1


def _run(tmp: Path) -> None:
    # ---------- 1. 双均线：最近 10 个交易日 ----------
    fetcher = FakeFetcher(years=2)
    start, end = _window(fetcher)
    pt = PaperTrader(DoubleMACross, symbols=["600519"], start_date=start, end_date=end,
                     initial_capital=1_000_000.0, benchmark=None, fetcher=fetcher,
                     account_file=tmp / "daily.json")
    res = pt.run_daily(last_n_bars=10)
    check("双均线模拟盘：最近 10 个交易日跑通（净值/指标 10 天）",
          len(res.nav) == 10 and res.metrics.get("days") == 10,
          f"bars={len(res.nav)} days={res.metrics.get('days')}")
    check("双均线模拟盘：窗口内有成交且手续费非 0",
          len(pt.account.trades) > 0 and res.metrics.get("total_commission", 0) > 0,
          f"trades={len(pt.account.trades)} "
          f"fee={res.metrics.get('total_commission')}")
    check("双均线模拟盘：每个交易日生成账单",
          len(pt.bills) == 10 and all("equity" in b and "fill_count" in b
                                      for b in pt.bills))
    check("双均线模拟盘：账户自动落盘", pt.account_file.exists(), pt.account_file.name)
    check("模拟盘滑点 = 基础 × 2.0（读 config，不硬编码）",
          abs(pt.execution.slippage
              - config.EXECUTION_MODEL["slippage_base_pct"]
              * config.EXECUTION_MODEL["slippage_multiplier"]["paper"]) < 1e-12,
          f"slippage={pt.execution.slippage}")
    check("成交模型为 core/execution.py 同一实现（不另写撮合）",
          isinstance(pt.execution, ExecutionModel))
    check("成交记录来自 account.place_order（order_id 齐全）",
          all(t.get("order_id") for t in pt.account.trades))
    check("风控复用 core/risk.py（参数源 config.RISK）",
          pt.strategy.risk_manager.max_single_symbol_pct
          == float(config.RISK["account"]["max_single_symbol_pct"]))

    # ---------- 2. 预热期不产生开仓 ----------
    gate_pt = PaperTrader(BuyEveryBar, symbols=["600519"], start_date=start, end_date=end,
                          initial_capital=1_000_000.0, benchmark=None,
                          fetcher=FakeFetcher(years=1), account_file=tmp / "warm.json")
    gate_pt.run()
    attempts = gate_pt.strategy.attempts
    warm = [status for _, ok, status in attempts if not ok]
    check("预热期 bar 在模拟盘不产生开仓",
          bool(warm) and all(s != "filled" for s in warm),
          f"预热期尝试 {len(warm)} 次，成交 {sum(1 for s in warm if s == 'filled')} 次")

    missing = False
    try:
        pt._dispatch(pd.Timestamp("2026-01-05"), {"600519": {"close": 1.0}})
    except ValueError:
        missing = True
    check("bar_dict 缺 warmup_ok 直接报错（闸门有源，禁止静默放行）", missing)

    # ---------- 3. 账户持久化 ----------
    hold_fetcher = FakeFetcher(years=2)
    hs, he = _window(hold_fetcher)
    hold = PaperTrader(BuyOnceProbe, symbols=["600519"], start_date=hs, end_date=he,
                       initial_capital=1_000_000.0, benchmark=None, fetcher=hold_fetcher,
                       account_file=tmp / "persist.json")
    hold.submit_order("600519", "buy", 100, order_type="limit", price=1.0,
                      expire="gtc", tag="far-limit")
    hold.run_daily(last_n_bars=10)
    held = {s: p.volume for s, p in hold.account.positions.items()}
    cash = float(hold.account.cash)
    check("持久化前：模拟盘确实持有仓位", bool(held), f"{held}")

    reloaded = PaperTrader(BuyOnceProbe, symbols=["600519"], start_date=hs, end_date=he,
                           initial_capital=1_000_000.0, benchmark=None,
                           fetcher=hold_fetcher, account_file=tmp / "persist.json",
                           auto_save=False)
    reloaded.account = TradingAccount(1_000_000.0, run_mode="paper", fetcher=hold_fetcher)
    loaded = reloaded.load_account()
    check("账户持久化：中断重启后持仓还在",
          loaded and {s: p.volume for s, p in reloaded.account.positions.items()} == held,
          f"重载 {{s: p.volume}} = {held}")
    check("账户持久化：资金一致", abs(reloaded.account.cash - cash) < 1e-6,
          f"{reloaded.account.cash:.2f} vs {cash:.2f}")
    far = reloaded.find_order(tag="far-limit")
    check("挂单持久化：未成交挂单重启后仍在",
          len(far) == 1 and far[0].status == "pending")

    # ---------- 4. 条件单：止损单触发 ----------
    step = StepFetcher()
    ss = step.frame.index[0].strftime("%Y-%m-%d")
    se = step.frame.index[-1].strftime("%Y-%m-%d")
    cond = PaperTrader(BuyOnceProbe, symbols=["600519"], start_date=ss, end_date=se,
                       initial_capital=1_000_000.0, benchmark=None, fetcher=step,
                       account_file=tmp / "cond.json")
    stop = cond.stop_loss_order("600519", 100, trigger_price=95.0)
    cond.run_daily(last_n_bars=10)
    check("条件单：止损单价格到位后自动成交",
          stop.status == "filled" and stop.filled_price is not None
          and stop.filled_price < 95.0 and stop.condition == "stop",
          f"status={stop.status} fill={stop.filled_price}")
    check("条件单：止损后持仓归零",
          "600519" not in cond.account.positions and len(cond.account.trades) == 2)

    # ---------- 5. 订单管理 ----------
    om = PaperTrader(DoubleMACross, symbols=["600519"], start_date=hs, end_date=he,
                     benchmark=None, fetcher=hold_fetcher, auto_save=False,
                     account_file=tmp / "orders.json")
    order = om.submit_order("600519", "buy", 100, order_type="limit",
                            price=1000.0, tag="挂单")
    check("挂单：pending 且进入挂单列表",
          order.status == "pending" and order in om.pending_orders())
    check("改单：限价与数量生效",
          om.modify_order(order.order_id, price=900.0, volume=200)
          and order.price == 900.0 and order.volume == 200)
    check("撤单：canceled 且移出挂单列表",
          om.cancel_order(order.order_id) and order.status == "canceled"
          and order not in om.pending_orders())
    check("非法委托被拒绝（限价单缺价格）",
          raises(lambda: om.submit_order("600519", "buy", 100, order_type="limit")))
    basket = hold.rebalance({"600519": 0})
    check("一篮子调仓：按 delta 生成卖单",
          len(basket) == 1 and basket[0].direction == "sell"
          and abs(basket[0].volume - held["600519"]) < 1e-9,
          f"{[(o.symbol, o.direction, o.volume) for o in basket]}")
    add = hold.rebalance({"600519": held["600519"] + 200})
    check("一篮子调仓：加仓生成买单",
          len(add) == 1 and add[0].direction == "buy" and abs(add[0].volume - 200) < 1e-9)

    # ---------- 6. 记录与对账 ----------
    before_cash = float(hold.account.cash)
    rec = hold.reconcile(cash=before_cash + 5000.0, note="模拟分红")
    check("手动对账：现金可校正（模拟分红）",
          rec["status"] == "ok" and abs(hold.account.cash - (before_cash + 5000.0)) < 1e-6)
    hold.reconcile(positions={"600519": 300}, note="模拟拆股")
    check("手动对账：持仓可校正（模拟拆股）",
          abs(hold.account.positions["600519"].volume - 300) < 1e-9)
    check("对账留档：每笔校正都有 before/after",
          len(hold.recon_log) == 2
          and all("before" in r and "after" in r for r in hold.recon_log))

    # ---------- 7. 模拟盘—回测偏差 ----------
    cmp_fetcher = FakeFetcher(years=2)
    cs, ce = _window(cmp_fetcher)
    paper_cmp = PaperTrader(DoubleMACross, symbols=["600519"], start_date=cs, end_date=ce,
                            initial_capital=1_000_000.0, benchmark=None,
                            fetcher=cmp_fetcher, account_file=tmp / "cmp.json")
    paper_cmp.run()
    ref_same = Backtester(DoubleMACross, symbols=["600519"], start_date=cs, end_date=ce,
                          initial_capital=1_000_000.0, benchmark=None,
                          fetcher=cmp_fetcher, slippage=paper_cmp.execution.slippage,
                          liquidate_at_end=False).run()
    same = paper_cmp.compare_with_backtest(reference=ref_same)
    check("偏差分析：相同滑点/行情/策略下偏差≈0 且不告警",
          abs(same["deviation_pct"]) < 1e-9 and not same["warned"],
          f"{same['deviation_pct']:.2e}")

    ref_default = Backtester(DoubleMACross, symbols=["600519"], start_date=cs, end_date=ce,
                             initial_capital=1_000_000.0, benchmark=None,
                             fetcher=cmp_fetcher, liquidate_at_end=False).run()
    diff = paper_cmp.compare_with_backtest(reference=ref_default, warn_pct=1e-9)
    check("偏差分析：偏差超阈值时告警（差异来自 2 倍滑点）",
          diff["warned"] and abs(diff["deviation_pct"]) > 0,
          f"{diff['deviation_pct']:.4%}")
    check("偏差归因：给出滑点与成交笔数线索",
          diff["drivers"]["slippage_paper"] > diff["drivers"]["slippage_backtest"]
          and "paper_fills" in diff["drivers"]
          and bool(diff["drivers"]["known_simplifications"]))
    auto = paper_cmp.compare_with_backtest()
    check("偏差分析：不传 reference 时自动跑同参回测",
          auto["backtest_equity"] > 0 and isinstance(auto["deviation_pct"], float))

    # ---------- 8. 非交易日 ----------
    skipped = pt.run_daily(at="2026-11-07")          # 周六
    check("非交易日（周六）不产生撮合",
          len(skipped.nav) == 0 and bool(skipped.meta.get("skipped")))
    intraday = pt.run_intraday(interval_minutes=5, at="2026-11-07")
    check("分钟模拟盘：非交易日同样跳过，周期口径正确",
          len(intraday.nav) == 0 and pt.period == "5min")


if __name__ == "__main__":
    raise SystemExit(main())
