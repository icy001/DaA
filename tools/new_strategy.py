"""策略脚手架生成器（第 5 步 · 5.5 第 1 步）。

用法：
    python tools/new_strategy.py --name my_ma --template ma_cross
    python tools/new_strategy.py --name my_ma --template breakout --force

一次生成三个文件：
    strategies/<name>.py            策略骨架（只有信号逻辑，不碰取数/下单/费用/交易日）
    configs/strategies/<name>.yaml  本次运行参数 + 优化搜索范围
    tests/test_<name>.py            信号单测骨架（先用合成数据做冒烟检查）

内置模板：ma_cross / breakout / mean_reversion / grid / custom。

硬性约束（生成的代码同样遵守）：
  策略文件里只允许出现 self.buy / self.sell / self.short / self.cover /
  self.get_position / self.get_history / self.params；指标计算只用 core.indicators
  纯函数，且只吃 get_history 拿到的序列。
"""
from __future__ import annotations

import argparse
import py_compile
import re
import sys
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
STRATEGY_DIR = BASE_DIR / "strategies"
CONFIG_DIR = BASE_DIR / "configs" / "strategies"
TEST_DIR = BASE_DIR / "tests"

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
RESERVED = {"base", "_selftest"}

# ==================== 模板 ====================
# 模板字符串用 __X__ 占位符（不用 str.format，避免生成代码里的 {} 被当成占位符）

_HEADER = '''"""__DISPLAY__（由 tools/new_strategy.py 生成，模板 __TEMPLATE__）。

__DESC__

硬性约束：本文件只调用 self.buy/sell/short/cover 与 self.get_position/
self.get_history/self.params；指标计算只用 core.indicators 纯函数，
且只吃 self.get_history 拿到的序列。禁止直接取数/下单/算手续费/判断交易日。
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):       # 支持 `python strategies/__NAME__.py` 直接运行
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

'''

_FOOTER = '''

if __name__ == "__main__":
    from strategies._selftest import run_selftest

    run_selftest(__CLASS__, symbols=["__SYMBOL__"])
'''

_MA_CROSS_BODY = '''class __CLASS__(BaseStrategy):
    """短均线 / 长均线金叉死叉。"""

    meta = {
        "name": "__NAME__",
        "display_name": "__DISPLAY__",
        "markets": __MARKETS__,
        "periods": ["1d"],
        "params": __PARAMS__,
        "description": "__DESC__",
        "author": "quant-team",
        "version": "0.1",
        "warmup": __WARMUP__,
    }

    def on_bar(self, date, bars):
        short_n = int(self.params["short_window"])
        long_n = int(self.params["long_window"])
        if long_n <= short_n:
            return
        for symbol, bar in bars.items():
            if not self.is_warmup_ok(symbol):
                continue
            close = self.get_history(symbol, long_n + 2, "close")
            fast = ind.MA(close, short_n)
            slow = ind.MA(close, long_n)
            if len(fast) < 2 or not np.isfinite(fast.iloc[-2]) or not np.isfinite(slow.iloc[-2]):
                continue
            prev_diff = float(fast.iloc[-2] - slow.iloc[-2])
            cur_diff = float(fast.iloc[-1] - slow.iloc[-1])
            if not np.isfinite(cur_diff):
                continue
            price = float(bar.get("close") or 0.0)
            if price <= 0:
                continue
            pos = self.get_position(symbol)
            if prev_diff <= 0.0 < cur_diff and pos is None:
                self.buy(symbol, self._qty(price), price)
            elif prev_diff >= 0.0 > cur_diff and pos is not None and pos.available > 0:
                self.sell(symbol, pos.available, price)

    def _qty(self, price: float) -> float:
        lot = max(int(self.params.get("lot_size", 100) or 1), 1)
        value = float(self.params.get("order_value", 100_000.0))
        return float(max(int(value / price / lot) * lot, lot))
'''

_BREAKOUT_BODY = '''class __CLASS__(BaseStrategy):
    """唐奇安通道突破（多头版；做空请自行加 self.short/self.cover）。"""

    meta = {
        "name": "__NAME__",
        "display_name": "__DISPLAY__",
        "markets": __MARKETS__,
        "periods": ["1d"],
        "params": __PARAMS__,
        "description": "__DESC__",
        "author": "quant-team",
        "version": "0.1",
        "warmup": __WARMUP__,
    }

    def on_bar(self, date, bars):
        entry = int(self.params["entry_window"])
        exit_n = int(self.params["exit_window"])
        if entry <= exit_n:
            return
        need = entry + 2
        for symbol, bar in bars.items():
            if not self.is_warmup_ok(symbol):
                continue
            high = self.get_history(symbol, need, "high")
            low = self.get_history(symbol, need, "low")
            if len(high) < need:
                continue
            price = float(bar.get("close") or 0.0)
            if price <= 0:
                continue
            upper = float(high.iloc[-entry - 1:-1].max())
            exit_low = float(low.iloc[-exit_n - 1:-1].min())
            if not np.isfinite([upper, exit_low]).all():
                continue
            pos = self.get_position(symbol)
            if pos is None and price > upper:
                self.buy(symbol, self._qty(price), price)
            elif pos is not None and pos.available > 0 and price < exit_low:
                self.sell(symbol, pos.available, price)

    def _qty(self, price: float) -> float:
        lot = max(int(self.params.get("lot_size", 100) or 1), 1)
        value = float(self.params.get("order_value", 100_000.0))
        return float(max(int(value / price / lot) * lot, lot))
'''

_MEAN_REVERSION_BODY = '''class __CLASS__(BaseStrategy):
    """布林带下轨买入、中轨卖出。"""

    meta = {
        "name": "__NAME__",
        "display_name": "__DISPLAY__",
        "markets": __MARKETS__,
        "periods": ["1d"],
        "params": __PARAMS__,
        "description": "__DESC__",
        "author": "quant-team",
        "version": "0.1",
        "warmup": __WARMUP__,
    }

    def on_bar(self, date, bars):
        n = int(self.params["boll_n"])
        k = float(self.params["boll_k"])
        need = ind.required_bars("BOLL", n=n) + 2
        for symbol, bar in bars.items():
            if not self.is_warmup_ok(symbol):
                continue
            close = self.get_history(symbol, need, "close")
            boll = ind.BOLL(close, n=n, k=k)
            if len(boll) < 2 or boll.iloc[-1].isna().any():
                continue
            price = float(bar.get("close") or 0.0)
            if price <= 0:
                continue
            lower = float(boll["lower"].iloc[-1])
            mid = float(boll["mid"].iloc[-1])
            pos = self.get_position(symbol)
            if pos is None and price < lower:
                self.buy(symbol, self._qty(price), price)
            elif pos is not None and pos.available > 0 and price > mid:
                self.sell(symbol, pos.available, price)

    def _qty(self, price: float) -> float:
        lot = max(int(self.params.get("lot_size", 100) or 1), 1)
        value = float(self.params.get("order_value", 100_000.0))
        return float(max(int(value / price / lot) * lot, lot))
'''

_GRID_BODY = '''class __CLASS__(BaseStrategy):
    """区间网格：跌破下一格买入、涨破上一格卖出，用 self._grid_state 防重复挂单。"""

    meta = {
        "name": "__NAME__",
        "display_name": "__DISPLAY__",
        "markets": __MARKETS__,
        "periods": ["1d"],
        "params": __PARAMS__,
        "description": "__DESC__",
        "author": "quant-team",
        "version": "0.1",
        "warmup": __WARMUP__,
    }

    def init(self):
        self._grid_state = {}

    def on_bar(self, date, bars):
        grid_num = max(int(self.params["grid_num"]), 2)
        span = float(self.params["price_range_pct"])
        decimals = int(self.params.get("qty_decimals", 6))
        for symbol, bar in bars.items():
            if not self.is_warmup_ok(symbol):
                continue
            price = float(bar.get("close") or 0.0)
            if price <= 0:
                continue
            state = self._grid_state.get(symbol)
            if state is None or not (state["lower"] <= price <= state["upper"]):
                center = price
                state = {
                    "lower": center * (1.0 - span),
                    "upper": center * (1.0 + span),
                    "step": center * span * 2.0 / grid_num,
                    "index": grid_num // 2,
                }
                self._grid_state[symbol] = state
                continue
            index = int((price - state["lower"]) / state["step"])
            index = max(0, min(grid_num, index))
            prev = int(state["index"])
            qty = round(float(self.params["order_value"]) / price, decimals)
            pos = self.get_position(symbol)
            if index < prev and qty > 0:
                self.buy(symbol, qty, price)
                state["index"] = index
            elif index > prev and pos is not None and pos.available > 0:
                self.sell(symbol, min(qty, pos.available), price)
                state["index"] = index
'''

_CUSTOM_BODY = '''class __CLASS__(BaseStrategy):
    """空白模板：把 TODO 换成你的信号逻辑。"""

    meta = {
        "name": "__NAME__",
        "display_name": "__DISPLAY__",
        "markets": __MARKETS__,
        "periods": ["1d"],
        "params": __PARAMS__,
        "description": "__DESC__",
        "author": "quant-team",
        "version": "0.1",
        "warmup": __WARMUP__,
    }

    def on_bar(self, date, bars):
        for symbol, bar in bars.items():
            if not self.is_warmup_ok(symbol):
                continue
            price = float(bar.get("close") or 0.0)
            if price <= 0:
                continue
            # TODO: 换成你的指标与买卖条件，例如：
            # close = self.get_history(symbol, 22, "close")
            # if self.get_position(symbol) is None and <买入条件>:
            #     self.buy(symbol, self._qty(price), price)
            # elif <卖出条件>:
            #     self.sell(symbol, self.get_position(symbol).available, price)
            _ = self.get_position(symbol)

    def _qty(self, price: float) -> float:
        lot = max(int(self.params.get("lot_size", 100) or 1), 1)
        value = float(self.params.get("order_value", 100_000.0))
        return float(max(int(value / price / lot) * lot, lot))
'''

_TEMPLATES = {
    "ma_cross": {
        "display": "双均线交叉（脚手架）",
        "description": "短均线上穿长均线买入、下穿卖出，用作最基础的验证策略。",
        "markets": ["cn_stock", "cn_etf", "cn_convertible", "cn_future",
                    "us_stock", "hk_stock", "crypto", "forex"],
        "symbols": ["600519"],
        "params": {"short_window": 5, "long_window": 20,
                   "order_value": 100000.0, "lot_size": 100},
        "optimize": {"short_window": [3, 5, 8, 10],
                     "long_window": [15, 20, 30, 60]},
        "warmup": '[("MA", {"n": 20})]',
        "imports": "import numpy as np\n\nfrom core import indicators as ind\nfrom core.strategy import BaseStrategy\n",
        "body": _MA_CROSS_BODY,
    },
    "breakout": {
        "display": "唐奇安通道突破（脚手架）",
        "description": "价格突破 N 日高点买入、跌破 M 日低点卖出，经典趋势跟踪骨架。",
        "markets": ["cn_future", "global_future", "cn_stock", "us_stock",
                    "crypto", "forex"],
        "symbols": ["rb2510"],
        "params": {"entry_window": 20, "exit_window": 10,
                   "order_value": 100000.0, "lot_size": 100},
        "optimize": {"entry_window": [10, 20, 30, 55],
                     "exit_window": [5, 10, 20]},
        "warmup": '[("MA", {"n": 20})]',
        "imports": "import numpy as np\n\nfrom core.strategy import BaseStrategy\n",
        "body": _BREAKOUT_BODY,
    },
    "mean_reversion": {
        "display": "布林带均值回归（脚手架）",
        "description": "收盘跌破布林下轨买入、回到中轨卖出，适用于震荡行情。",
        "markets": ["cn_stock", "cn_etf", "us_stock", "hk_stock", "crypto"],
        "symbols": ["600519"],
        "params": {"boll_n": 20, "boll_k": 2.0,
                   "order_value": 100000.0, "lot_size": 100},
        "optimize": {"boll_n": [10, 20, 30], "boll_k": [1.5, 2.0, 2.5]},
        "warmup": '[("BOLL", {"n": 20})]',
        "imports": "import numpy as np\n\nfrom core import indicators as ind\nfrom core.strategy import BaseStrategy\n",
        "body": _MEAN_REVERSION_BODY,
    },
    "grid": {
        "display": "价格网格（脚手架）",
        "description": "在当前价上下 price_range_pct 区间等分 grid_num 格，逐格高抛低吸。",
        "markets": ["crypto", "cn_etf", "us_etf"],
        "symbols": ["BTC"],
        "params": {"grid_num": 20, "price_range_pct": 0.2,
                   "order_value": 3000.0, "qty_decimals": 6},
        "optimize": {"grid_num": [10, 20, 30, 50],
                     "price_range_pct": [0.1, 0.2, 0.3]},
        "warmup": '[("MA", {"n": 20})]',
        "imports": "from core.strategy import BaseStrategy\n",
        "body": _GRID_BODY,
    },
    "custom": {
        "display": "自定义策略（空白骨架）",
        "description": "TODO：写下你的信号逻辑（只能调用允许的策略 API）。",
        "markets": ["cn_stock"],
        "symbols": ["600519"],
        "params": {"order_value": 100000.0, "lot_size": 100},
        "optimize": {"order_value": [50000.0, 100000.0, 200000.0]},
        "warmup": '[("MA", {"n": 20})]',
        "imports": "from core.strategy import BaseStrategy\n",
        "body": _CUSTOM_BODY,
    },
}

# ==================== 测试骨架 ====================

_TEST_TEMPLATE = '''"""__NAME__ 策略信号单测骨架（由 tools/new_strategy.py 生成）。

TODO（第 2 步 · 信号单元测试）：
  用手工构造的小段 OHLCV（例如「先跌后涨、必然出现金叉」）断言：
  信号方向对、数量对、时间点对；并覆盖数据不足 / 横盘 / 连续涨停 / 停牌 等边界。

当前只做冒烟检查：meta 完整、loader 能按名字取到、合成数据回测能跑通。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategies._selftest import run_selftest  # noqa: E402

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" | {detail}" if detail else ""))


def main() -> int:
    from core.strategy import BaseStrategy
    from core.strategy_loader import get

    cls = get("__NAME__")
    meta = dict(getattr(cls, "meta", {}) or {})
    check("meta.name 正确", meta.get("name") == "__NAME__", str(meta.get("name")))
    check("meta 必填项", all(meta.get(k) for k in
                            ("name", "display_name", "markets", "params",
                             "description", "version")))
    check("已实现 on_bar", getattr(cls, "on_bar", None) is not BaseStrategy.on_bar)
    result = run_selftest(cls, verbose=False)
    check("合成数据回测跑通", isinstance(result.get("metrics"), dict),
          str(result.get("metrics")))
    print(f"\\nPASS {len(PASS)} / FAIL {len(FAIL)}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


# ==================== 生成逻辑 ====================

def _class_name(name: str) -> str:
    parts = [p for p in name.split("_") if p]
    return "".join(p[:1].upper() + p[1:] for p in parts) + "Strategy"


def _render(text: str, name: str, template: str) -> str:
    tpl = _TEMPLATES[template] if template in _TEMPLATES else {}
    mapping = {
        "__NAME__": name,
        "__CLASS__": _class_name(name),
        "__DISPLAY__": str(tpl.get("display", name)),
        "__DESC__": str(tpl.get("description", "")),
        "__MARKETS__": repr(tpl.get("markets", ["cn_stock"])),
        "__PARAMS__": repr(tpl.get("params", {})),
        "__WARMUP__": str(tpl.get("warmup", "[]")),
        "__TEMPLATE__": template,
        "__SYMBOL__": (tpl.get("symbols") or [""])[0],
    }
    for key, value in mapping.items():
        text = text.replace(key, value)
    return text


def _strategy_source(name: str, template: str) -> str:
    tpl = _TEMPLATES[template]
    source = (_HEADER + tpl["imports"] + "\n\n" + tpl["body"] + _FOOTER)
    return _render(source, name, template)


def _yaml_source(name: str, template: str) -> str:
    tpl = _TEMPLATES[template]
    data = {
        "strategy": name,
        "params": tpl["params"],
        "symbols": tpl["symbols"],
        "start": "2023-01-01",
        "end": "2026-01-01",
        "optimize": tpl["optimize"],
    }
    head = (f"# {name}：由 tools/new_strategy.py 生成（模板 {template}）\n"
            f"# params 为本次运行参数；optimize 为参数优化搜索范围（第 7 步使用）\n")
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False,
                          default_flow_style=False)
    return head + body


def _test_source(name: str) -> str:
    return _render(_TEST_TEMPLATE, name, "custom")


def _compile(path: Path) -> None:
    py_compile.compile(str(path), doraise=True)


def generate(name: str, template: str, force: bool = False) -> list:
    """生成三个文件；返回路径列表。同名文件存在且未加 --force 时抛 FileExistsError。"""
    strategy_path = STRATEGY_DIR / f"{name}.py"
    config_path = CONFIG_DIR / f"{name}.yaml"
    test_path = TEST_DIR / f"test_{name}.py"
    targets = [strategy_path, config_path, test_path]

    existing = [str(p) for p in targets if p.exists()]
    if existing and not force:
        raise FileExistsError("以下文件已存在，加 --force 覆盖：\n  " + "\n  ".join(existing))

    STRATEGY_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TEST_DIR.mkdir(parents=True, exist_ok=True)

    strategy_path.write_text(_strategy_source(name, template), encoding="utf-8")
    config_path.write_text(_yaml_source(name, template), encoding="utf-8")
    test_path.write_text(_test_source(name), encoding="utf-8")

    # 只对 Python 文件做语法校验；yaml 用 safe_load 校验
    _compile(strategy_path)
    _compile(test_path)
    yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return targets


def _validate_name(name: str) -> str:
    if name in RESERVED:
        return f"{name!r} 是保留名，请换一个"
    if not NAME_RE.match(name):
        return "策略名只能是「小写字母开头 + 小写字母/数字/下划线」，例如 my_ma"
    return ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生成策略 / 配置 / 测试三个骨架文件")
    parser.add_argument("--name", required=True, help="策略名（即 meta['name'] 与文件名）")
    parser.add_argument("--template", default="ma_cross", choices=sorted(_TEMPLATES),
                        help="模板：ma_cross / breakout / mean_reversion / grid / custom")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的同名文件")
    args = parser.parse_args(argv)

    error = _validate_name(args.name)
    if error:
        print(f"[错误] {error}")
        return 2

    try:
        paths = generate(args.name, args.template, force=args.force)
    except FileExistsError as exc:
        print(f"[错误] {exc}")
        return 2
    except py_compile.PyCompileError as exc:      # 模板本身写错时才会触发
        print(f"[错误] 生成的文件语法校验失败：{exc}")
        return 1

    print("生成完成（模板 %s）：" % args.template)
    for path in paths:
        print(f"  {path.relative_to(BASE_DIR)}")
    print("\n下一步：")
    print(f"  1) python strategies/{args.name}.py                       # 离线自检（合成数据）")
    print(f"  2) python tests/test_{args.name}.py                       # 信号单测骨架")
    print(f"  3) python tools/strategy_checklist.py --strategy {args.name}   # 上线前检查")
    print("\n提示：策略层只允许 self.buy/sell/short/cover、self.get_position/"
          "self.get_history、self.params；指标只用 core.indicators 纯函数。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
