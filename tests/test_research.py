"""第 5 步：研究流程（走向前分析 / 稳健性 / 实验记录）离线测试。

覆盖：
  a) run_walkforward 返回 n_splits 段、每段参数非空、样本外净值非空、衰减类型正确；
  b) 样本内 / 样本外日期不重叠，且相邻段首尾相接；
  c) perturb_params 生成 n 组、全部落在 ±10%（整数四舍五入留 0.5 松弛）、整数仍为 >0 整数；
  d) validate_robustness 返回 4 项检查、评分在 0–100；
  e) registry 落盘 / 列举 / 横向对比 / 复现查找 / 字段完整性（临时目录）。
不依赖网络，全程 < 60 秒。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.runner import run_backtest
from core.strategy import BaseStrategy
from research.registry import ExperimentRegistry
from research.validator import perturb_params, validate_robustness
from research.walkforward import run_walkforward

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'✅' if ok else '❌'} {name}" + (f" | {detail}" if detail else ""))


# ==================== 桩数据 ====================

class FakeFetcher:
    """400 根随机游走日线，按 start/end 过滤；不联网。"""

    def __init__(self, n: int = 400, seed: int = 7, start_price: float = 100.0):
        self.n = int(n)
        idx = pd.bdate_range(end=pd.Timestamp("2025-12-31"), periods=self.n)
        rng = np.random.default_rng(seed)
        close = start_price * np.exp(np.cumsum(rng.normal(0.0, 0.015, self.n)))
        self.frame = pd.DataFrame({
            "open": close * (1 + rng.normal(0, 0.002, self.n)),
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(self.n, 1_000_000.0),
            "amount": close * 1_000_000.0,
            "price_adjust": "qfq",
        }, index=idx)
        self.frame.attrs["adjust"] = "qfq"
        self.frame.attrs["price_adjust"] = "qfq"

    def get_daily(self, symbol, start_date=None, end_date=None, adjust="qfq",
                  fill_missing=False, market_type=None, for_trading=False, **kwargs):
        frame = self.frame
        if start_date:
            frame = frame.loc[pd.Timestamp(start_date):]
        if end_date:
            frame = frame.loc[:pd.Timestamp(end_date)]
        return frame.copy()

    def get_kline(self, symbol, start_date=None, end_date=None, period="1d",
                  adjust="qfq", market_type=None, **kwargs):
        return self.get_daily(symbol, start_date, end_date, adjust)


class SynthMA(BaseStrategy):
    """合成双均线：只读 close，交叉买卖。"""

    meta = {
        "name": "_synth_ma", "display_name": "合成均线", "markets": ["cn_stock"],
        "periods": ["1d"], "params": {"fast": 5, "slow": 20},
        "description": "离线测试用合成策略", "warmup": [("MA", {"n": 5})],
    }

    def init(self):
        self._fast = max(int(self.params.get("fast", 5)), 1)
        self._slow = max(int(self.params.get("slow", 20)), self._fast + 1)

    def on_bar(self, date, bars):
        symbol = "600519"
        if symbol not in bars:
            return
        need = self._slow + 1
        closes = self.get_history(symbol, need, field="close")
        if len(closes) < need:
            return
        fast = float(closes.tail(self._fast).mean())
        slow = float(closes.tail(self._slow).mean())
        prev_fast = float(closes.iloc[-self._fast - 1:-1].mean())
        prev_slow = float(closes.iloc[-self._slow - 1:-1].mean())
        pos = self.get_position(symbol)
        if pos is None and prev_fast <= prev_slow and fast > slow:
            self.buy(symbol, 100)
        elif pos is not None and prev_fast >= prev_slow and fast < slow:
            self.sell(symbol, pos.available)


# ==================== 测试主体 ====================

def main() -> int:
    fetcher = FakeFetcher()
    symbols = ["600519"]
    start = fetcher.frame.index[0].strftime("%Y-%m-%d")
    end = fetcher.frame.index[-1].strftime("%Y-%m-%d")
    grid = {"fast": [3, 5, 8], "slow": [15, 20]}

    # ---------- a) 走向前分析 ----------
    wf = run_walkforward(SynthMA, grid, symbols, start, end, n_splits=4,
                         train_ratio=0.7, optimizer="grid", fetcher=fetcher)
    segs = wf["segments"]
    check("walkforward 返回 n_splits 段", len(segs) == 4, f"{len(segs)} 段")
    check("每段 best_params 非空", all(bool(s["best_params"]) for s in segs),
          str([s["best_params"] for s in segs]))
    check("oos_nav 长度 > 0", len(wf["oos_nav"]) > 0, f"{len(wf['oos_nav'])} 个点")
    check("degradation 是 float 或 None",
          wf["degradation"] is None or isinstance(wf["degradation"], float),
          f"{wf['degradation']}")
    check("params_history 与段数一致", len(wf["params_history"]) == len(segs))

    # ---------- b) 样本内 / 样本外不重叠且相邻 ----------
    no_overlap = all(pd.Timestamp(s["test_start"]) > pd.Timestamp(s["train_end"])
                     for s in segs)
    calendar = list(fetcher.frame.index)
    adjacent = True
    for prev, nxt in zip(segs, segs[1:]):
        pos = calendar.index(pd.Timestamp(prev["test_end"]))
        adjacent = adjacent and (pos + 1 < len(calendar)
                                 and calendar[pos + 1] == pd.Timestamp(nxt["train_start"]))
    check("每段 test_start > train_end", no_overlap)
    check("相邻段首尾相接", adjacent,
          f"{segs[0]['test_end']} → {segs[1]['train_start']}")

    # ---------- c) 参数微扰 ----------
    origin = {"fast": 50, "slow": 120, "weight": 0.3, "zscore": 1.5, "lookback": 60}
    groups = perturb_params(origin, n=100, pct=0.10, seed=42)
    check("perturb_params 生成 n 组", len(groups) == 100, f"{len(groups)} 组")

    def in_range(key: str, value) -> bool:
        base = origin[key]
        slack = 0.5 if isinstance(base, int) else 1e-9   # 整数四舍五入的松弛
        return abs(float(value) - base) <= 0.10 * abs(base) + slack

    within = all(all(in_range(k, g[k]) for k in origin) for g in groups)
    check("扰动值都在 ±10% 内", within)
    int_ok = all(isinstance(g["lookback"], int) and g["lookback"] > 0
                 and isinstance(g["fast"], int) and g["fast"] > 0 for g in groups)
    check("整数参数仍是 >0 整数", int_ok)

    # ---------- d) 稳健性评分卡 ----------
    card = validate_robustness(SynthMA, {"fast": 5, "slow": 20}, grid, symbols,
                               start, end, fetcher=fetcher, n_perturb=24, seed=42)
    check("评分卡含 4 项检查", len(card["checks"]) == 4,
          str([c["name"] for c in card["checks"]]))
    check("score 在 0–100", 0 <= card["score"] <= 100, f"{card['score']}")
    check("checks 状态合法",
          all(c["status"] in ("pass", "warn", "fail") for c in card["checks"]))

    # ---------- e) 实验记录 ----------
    with tempfile.TemporaryDirectory() as tmp:
        reg = ExperimentRegistry(root=tmp)
        res1 = run_backtest(SynthMA, params={"fast": 5, "slow": 20}, symbols=symbols,
                            start=start, end=end, fetcher=fetcher)
        res2 = run_backtest(SynthMA, params={"fast": 8, "slow": 20}, symbols=symbols,
                            start=start, end=end, fetcher=fetcher)
        id1 = reg.log(res1, tags=["test", "ma"])
        id2 = reg.log(res2)
        records = reg.list()
        check("registry list 2 条", len(records) == 2, f"{len(records)} 条")
        table = reg.compare([id1, id2])
        check("compare 返回 2 行", len(table) == 2, f"shape={table.shape}")
        hits = reg.find_reproducible(res1["params"], res1["symbols"], start, end)
        check("find_reproducible 命中",
              any(r.get("exp_id") == id1 for r in hits), f"{len(hits)} 条命中")
        record = reg.load(id1)
        fields = ["exp_id", "time", "strategy", "strategy_version", "params", "symbols",
                  "start", "end", "metrics", "run_mode", "code_version", "data_hash",
                  "charts", "tags"]
        check("load 字段完整",
              record is not None and all(k in record for k in fields),
              str(sorted(set(fields) - set(record or {}))))
        check("记录策略名与区间正确",
              record["strategy"] == "_synth_ma" and record["start"] == start
              and record["end"] == end,
              f"{record['strategy']} {record['start']}~{record['end']}")
        check("JSON 文件已落盘", len(list(Path(tmp).glob("*.json"))) == 2)

    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：" + "，".join(FAIL))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
