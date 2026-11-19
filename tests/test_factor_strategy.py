"""第 5 步 5.9 因子策略适配器 / 付费适配器 / 策略市场 离线测试。

覆盖：
  1) FactorStrategy 通过 factor_panel_provider 注入桩数据，用 StrategyRunner 跑通回测；
  2) Top N 与单票权重上限生效；
  3) 付费适配器依赖缺失时抛 ImportError（绝不静默返回空表）；
  4) 公开策略市场搜索可用；安全校验器能拦截网络请求。
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.runner import StrategyRunner
from factor.adapters import JoinQuantFactor, QlibFactor, TushareFactor, UqerFactor
from factor.factor_strategy import FactorStrategy
from factor.market.browser import list_sources, search_strategy
from factor.market.validator import validate_strategy_file

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'✅' if ok else '❌'} {name}" + (f" | {detail}" if detail else ""))


# ==================== 桩数据 ====================
SYMBOLS = ["600001", "600002", "600003", "600004",
           "600005", "600006", "600007", "600008"]
N_DAYS = 120
END = pd.Timestamp("2026-10-30")
DATES = pd.bdate_range(end=END, periods=N_DAYS)


class FakeFetcher:
    """按股票代码生成可复现的日线，不联网。"""

    def __init__(self):
        self.frames = {}
        for i, symbol in enumerate(SYMBOLS):
            rng = np.random.default_rng(1000 + i)
            base = 20.0 + i * 5
            rets = rng.normal(0.0002, 0.015, N_DAYS)
            close = base * np.cumprod(1.0 + rets)
            self.frames[symbol] = pd.DataFrame({
                "open": close * (1 + rng.normal(0, 0.002, N_DAYS)),
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": np.full(N_DAYS, 2_000_000.0),
                "amount": close * 2_000_000.0,
                "price_adjust": "qfq",
            }, index=DATES)

    def get_daily(self, symbol, start_date=None, end_date=None, adjust="qfq", **kwargs):
        frame = self.frames.get(str(symbol))
        return frame.copy() if frame is not None else pd.DataFrame()

    def get_kline(self, symbol, start_date=None, end_date=None, period="1d",
                  adjust="qfq", **kwargs):
        return self.get_daily(symbol)


def make_provider(params, symbols):
    """3 个因子 × 120 交易日 × 8 只股票的随机面板。"""
    rng = np.random.default_rng(42)
    panels = {}
    for name in ("alpha001", "alpha006", "alpha023"):
        panels[name] = pd.DataFrame(
            rng.normal(0, 1, size=(N_DAYS, len(symbols))),
            index=DATES, columns=list(symbols),
        )
    return panels


def expect_import_error(adapter_cls, package: str) -> None:
    label = f"{adapter_cls.__name__} 依赖缺失时抛 ImportError 而不是空表"
    if importlib.util.find_spec(package) is not None:
        print(f"➖ {label} | N/A（环境已安装 {package}）")
        return
    try:
        adapter_cls().get_factor("alpha001", SYMBOLS[:2], "2024-01-01", "2024-02-01")
    except ImportError:
        check(label, True)
    except Exception as exc:  # 抛错类型不对
        check(label, False, f"{type(exc).__name__}: {exc}")
    else:
        check(label, False, "既没抛 ImportError，也没有返回数据")


def main() -> int:
    # ---------- 1. 回测跑通 ----------
    params = {
        "symbols": SYMBOLS,
        "factor_list": ["alpha001", "alpha006", "alpha023"],
        "combine_method": "equal_weight",
        "universe": "hs300",
        "n_top": 5,
        "rebalance_freq": "weekly",
        "weight_method": "equal_weight",
        "single_limit": 0.05,
        "industry_limit": 0.30,
        "min_amount": 0.0,
        "factor_panel_provider": make_provider,
    }
    bt = StrategyRunner(
        FactorStrategy, params=params, symbols=SYMBOLS,
        start=str(DATES[0].date()), end=str(DATES[-1].date()),
        fetcher=FakeFetcher(), initial_cash=1_000_000, run_mode="backtest",
    ).run()
    strategy = bt["strategy"]
    nav = bt["nav"]
    filled = [t for t in bt["trades"] if t.get("status") == "filled"]

    check("FactorStrategy 回测跑通（净值曲线非空）",
          isinstance(nav, pd.Series) and len(nav) == N_DAYS, f"bars={len(nav)}")
    check("回测产生成交（有买入/卖出）", len(filled) > 0, f"filled={len(filled)}")
    check("调仓至少执行一次", len(strategy._last_target_weights) > 0,
          f"last_target={len(strategy._last_target_weights)}")

    # ---------- 2. Top N 与单票上限 ----------
    weights = strategy._last_target_weights
    check("Top N 不超过 n_top", 0 < len(weights) <= params["n_top"],
          f"选中 {len(weights)} 只 / n_top={params['n_top']}")
    check("单票目标权重 <= single_limit",
          bool(weights) and max(weights.values()) <= params["single_limit"] + 1e-9,
          f"max={max(weights.values()):.4f}" if weights else "空")

    prices = strategy.prices
    equity = strategy.account.calc_equity(prices)
    actual = {
        sym: float(pos.volume) * float(prices.get(sym, pos.price)) / equity
        for sym, pos in strategy.account.positions.items() if equity > 0
    }
    check("实际持仓单票权重受 single_limit 约束（容差 1%）",
          bool(actual) and max(actual.values()) <= params["single_limit"] + 0.01,
          f"max={max(actual.values()):.4f}" if actual else "无持仓")

    # ---------- 3. 付费适配器缺依赖 ----------
    expect_import_error(TushareFactor, "tushare")
    expect_import_error(JoinQuantFactor, "jqdatasdk")
    expect_import_error(UqerFactor, "uqer")
    expect_import_error(QlibFactor, "qlib")

    # ---------- 4. 策略市场 ----------
    hits = search_strategy("双均线")
    check("策略市场可按“双均线”搜到结果", len(hits) > 0, f"命中 {len(hits)} 条")
    check("策略市场源清单非空", len(list_sources()) >= 5, f"{len(list_sources())} 个源")

    with tempfile.TemporaryDirectory() as tmp:
        risky = Path(tmp) / "risky_strategy.py"
        risky.write_text(
            "import requests\n\n"
            "def on_bar(self, date, bars):\n"
            "    requests.get('http://example.com/data')\n",
            encoding="utf-8",
        )
        report = validate_strategy_file(risky)
    check("含 requests.get 的第三方策略被拦截（blocked=True / high）",
          report["blocked"] is True and report["level"] == "high",
          f"score={report['risk_score']} warnings={len(report['warnings'])}")
    check("风险评分 >= 60（网络请求属高危）", report["risk_score"] >= 60,
          f"score={report['risk_score']}")

    # ---------- 汇总 ----------
    print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
    if FAIL:
        print("失败项：")
        for item in FAIL:
            print("  -", item)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
