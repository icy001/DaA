"""三引擎一致性测试（D5）

验证第 7 步开工前置的核心约束：
  1) `config.ENGINE_CONFORMANCE["must_share"]` 三个模块（signal_gate / execution / risk）
     真实存在且被回测、模拟盘 import；引擎文件里不得重新定义 `ExecutionModel` / `RiskManager`；
  2) 每根 bar 必须带 `warmup_ok` / `data_asof_date` / `price_adjust` 三个物化列；
  3) 同一份行情 + 同一策略 + 同一初始资金：回测与模拟盘在**相同滑点**下逐笔成交与末值权益一致；
     默认参数下差异只来自 `EXECUTION_MODEL["slippage_multiplier"]`（paper=2.0）；
  4) 模拟盘同样受预热闸门约束：预热期 buy() 被拒（含 fillna(0) 的帧），末根预热不出信号；
  5) 风控只有一份实现：`BaseStrategy` 委托 `core/risk.py`，参数源为 config.RISK。
"""
from __future__ import annotations

import inspect
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from core import backtester as bt_mod
from core import execution as exec_mod
from core import paper_trader as pt_mod
from core import risk as risk_mod
from core import signal_gate
from core.account import TradingAccount
from core.backtester import Backtester
from core.paper_trader import PaperTrader
from core.strategy import BaseStrategy
from strategies.double_ma_cross import DoubleMACross
from tests.test_backtest import BuyEveryBar, FakeFetcher
from tests.test_signal_gate import FakeFetcher as GateFetcher
from tests.test_signal_gate import FillNaGateStrategy

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'✅' if ok else '❌'} {name}" + (f" | {detail}" if detail else ""))


def _trades(account) -> list:
    return [(t.get("symbol"), t.get("direction"), float(t.get("volume") or 0),
             round(float(t.get("price") or 0), 6)) for t in account.trades]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="engine_consistency_"))

    # ---------- 1. config 与共享模块 ----------
    ex_cfg = config.EXECUTION_MODEL
    ec_cfg = config.ENGINE_CONFORMANCE
    check("config.EXECUTION_MODEL：滑点倍数 回测1.0 / 模拟盘2.0 / 实盘2.0",
          ex_cfg["slippage_multiplier"] == {"backtest": 1.0, "paper": 2.0, "live": 2.0}
          and ex_cfg["slippage_base_pct"] == 0.0005)
    check("config.EXECUTION_MODEL：量限按市场分档且四项简化均标注偏差方向",
          ex_cfg["volume_limit_pct_by_market"]["cn_stock"] == 0.01
          and ex_cfg["volume_limit_pct_by_market"]["cn_etf"] == 0.02
          and ex_cfg["volume_limit_pct_by_market"]["cn_fund"] is None
          and set(ex_cfg["bias_direction"]) >= {"sell_slippage_at_open", "zdt_open_only",
                                                "volume_limit_fixed", "nav_pass_through"}
          and len(ex_cfg["known_simplifications"]) == 4)
    check("config.ENGINE_CONFORMANCE：三引擎与 must_share 三模块",
          ec_cfg["must_share"] == ["core/signal_gate.py", "core/execution.py", "core/risk.py"]
          and ec_cfg["engines"]["paper"] == "core/paper_trader.py"
          and ec_cfg["divergence_warn_pct"] == 0.05)

    root = Path(__file__).resolve().parent.parent
    files_ok = all((root / p).exists() for p in ec_cfg["must_share"])
    check("must_share 三个模块文件真实存在", files_ok,
          "、".join(p for p in ec_cfg["must_share"] if not (root / p).exists()) or "全部存在")

    bt_src = inspect.getsource(bt_mod)
    pt_src = inspect.getsource(pt_mod)
    check("成交模型只有一份：backtester/paper_trader 不重新定义 ExecutionModel",
          bt_mod.ExecutionModel is exec_mod.ExecutionModel
          and "class ExecutionModel" not in bt_src
          and "class ExecutionModel" not in pt_src)
    check("风控只有一份：两引擎不重新定义 RiskManager，策略委托 core/risk.py",
          "class RiskManager" not in bt_src
          and "class RiskManager" not in pt_src
          and "risk_manager.check_open" in inspect.getsource(
              sys.modules["core.strategy"]))
    check("闸门只有一份：两引擎 import signal_gate 且不重写 build_bar_dict",
          bt_mod.signal_gate is signal_gate and pt_mod.signal_gate is signal_gate
          and "def build_bar_dict" not in bt_src
          and "def build_bar_dict" not in pt_src)

    # ---------- 2. 风控参数源 ----------
    acct = TradingAccount(1_000_000, run_mode="backtest")
    rm = risk_mod.RiskManager(acct)
    check("风控参数来自 config.RISK（唯一参数源）",
          rm.max_single_symbol_pct == float(config.RISK["account"]["max_single_symbol_pct"])
          and rm.max_leverage == dict(config.RISK["account"]["max_leverage"])
          and BaseStrategy.DEFAULT_RISK["max_single_symbol_pct"] is None)

    # ---------- 3. 模拟盘：预热闸门有源 ----------
    gate_fetcher = GateFetcher(420)
    paper_fillna = PaperTrader(FillNaGateStrategy, symbols=["600519"],
                               start_date="2023-01-01", end_date="2026-12-31",
                               fetcher=gate_fetcher, account_file=tmp / "fillna.json")
    paper_fillna.prepare()
    paper_fillna.run()
    attempts = paper_fillna.strategy.attempts
    warm_attempts = [s for ok, s in attempts if not ok]
    check("PaperTrader：预热期 + fillna(0) 的帧 buy() 全部被拒",
          bool(warm_attempts) and all(s != "filled" for s in warm_attempts),
          f"预热期尝试 {len(warm_attempts)} 次，成交 "
          f"{sum(1 for s in warm_attempts if s == 'filled')} 次")

    bt_fetcher = FakeFetcher(years=2)
    paper_probe = PaperTrader(BuyEveryBar, symbols=["600519"],
                              start_date=bt_fetcher.get_daily("600519").index[0].strftime("%Y-%m-%d"),
                              end_date=bt_fetcher.get_daily("600519").index[-1].strftime("%Y-%m-%d"),
                              fetcher=bt_fetcher, account_file=tmp / "probe.json")
    paper_probe.prepare()
    paper_probe.run()
    probe_attempts = paper_probe.strategy.attempts
    warm_idx = [s for _, ok, s in probe_attempts if not ok]
    # next_open：信号当根返回 pending、下一根成交，故 pending 也算"已放行"
    first_fill = next((i for i, (_, ok, s) in enumerate(probe_attempts)
                       if ok and s in ("filled", "pending")), None)
    last_bar = paper_probe.last_bar_dict.get("600519") or {}
    check("PaperTrader：预热期 bar 不产生开仓（首笔成交在预热期之后）",
          bool(warm_idx) and all(s != "filled" for s in warm_idx)
          and first_fill is not None
          and first_fill >= paper_probe.strategy.warmup_bars - 1,
          f"warmup_bars={paper_probe.strategy.warmup_bars} first_fill={first_fill}")
    check("PaperTrader：bar_dict 带 warmup_ok / data_asof_date / price_adjust",
          all(col in last_bar for col in ec_cfg["must_feed_columns"]),
          f"缺失 {[c for c in ec_cfg['must_feed_columns'] if c not in last_bar]}")

    check("模拟盘默认滑点 = 基础 × 2.0（读 config，不硬编码）",
          abs(paper_probe.execution.slippage
              - config.EXECUTION_MODEL["slippage_base_pct"] * 2.0) < 1e-12,
          f"slippage={paper_probe.execution.slippage}")

    # ---------- 4. 回测 vs 模拟盘：成交与权益一致 ----------
    start = bt_fetcher.get_daily("600519").index[0].strftime("%Y-%m-%d")
    end = bt_fetcher.get_daily("600519").index[-1].strftime("%Y-%m-%d")
    common = dict(strategy_class=None, symbols=["600519"], start_date=start, end_date=end,
                  initial_capital=1_000_000, benchmark=None, fetcher=bt_fetcher)

    bt = Backtester(DoubleMACross, slippage=0.0005, run_mode="backtest",
                    liquidate_at_end=False, **{k: v for k, v in common.items()
                                               if k != "strategy_class"})
    bt_res = bt.run()
    paper_same = PaperTrader(DoubleMACross, slippage=0.0005, liquidate_at_end=False,
                             account_file=tmp / "same.json",
                             **{k: v for k, v in common.items() if k != "strategy_class"})
    paper_same_res = paper_same.run()

    same_trades = _trades(bt.account) == _trades(paper_same.account)
    bt_eq = float(bt_res.nav["equity"].iloc[-1])
    paper_eq = float(paper_same_res.nav["equity"].iloc[-1])
    check("同一行情/策略/资金：回测与模拟盘逐笔成交一致（相同滑点）",
          same_trades and len(bt.account.trades) > 0,
          f"回测 {len(bt.account.trades)} 笔 / 模拟盘 {len(paper_same.account.trades)} 笔")
    check("同一行情/策略/资金：回测与模拟盘末值权益一致",
          abs(bt_eq - paper_eq) <= max(1e-6, abs(bt_eq) * 1e-9),
          f"回测 {bt_eq:,.2f} / 模拟盘 {paper_eq:,.2f}")

    # 默认倍数下（paper 2 倍滑点）成交价更差、权益不同，差异可归因
    paper_fast = PaperTrader(DoubleMACross, account_file=tmp / "fast.json",
                             **{k: v for k, v in common.items() if k != "strategy_class"})
    paper_fast_res = paper_fast.run()
    bt_first_buy = next((t for t in bt.account.trades if t.get("direction") == "buy"), None)
    pf_first_buy = next((t for t in paper_fast.account.trades
                         if t.get("direction") == "buy"), None)
    check("默认参数下差异仅来自 slippage_multiplier（模拟盘买入价更高）",
          bt_first_buy is not None and pf_first_buy is not None
          and float(pf_first_buy["price"]) > float(bt_first_buy["price"])
          and abs(float(paper_fast_res.nav["equity"].iloc[-1]) - bt_eq) > 0,
          f"回测 {float(bt_first_buy['price']):.4f} / 模拟盘 "
          f"{float(pf_first_buy['price']):.4f}")

    # ---------- 5. 模拟盘账户持久化 ----------
    reloaded = PaperTrader(BuyEveryBar, account_file=tmp / "probe.json",
                           **{k: v for k, v in common.items() if k != "strategy_class"})
    reloaded.account = TradingAccount(1_000_000, run_mode="paper")
    loaded = reloaded.load_account()
    held = {s: p.volume for s, p in reloaded.account.positions.items()}
    original = {s: p.volume for s, p in paper_probe.account.positions.items()}
    check("模拟盘账户持久化：中断重启后持仓还在",
          loaded and bool(held) and held == original,
          f"重载 {held} / 原持仓 {original}")

    print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
