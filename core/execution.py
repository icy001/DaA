"""引擎无关的成交模型（core/execution.py）

第 7 步开工前置 D2/D4：滑点、涨跌停、成交量上限、限价撮合只允许有**一份实现**，
`core/backtester.py` / `core/paper_trader.py` / 实盘引擎**只调用、不重写**。
三环境差异只允许参数化，参数全部来自 `config.EXECUTION_MODEL`：

    slippage = slippage_base_pct × slippage_multiplier[run_mode]
        backtest = 0.0005 × 1.0
        paper    = 0.0005 × 2.0
        live     = 0.0005 × 2.0

已知简化（写入 `config.EXECUTION_MODEL["known_simplifications"]`，偏差方向见
`bias_direction`，回测与实盘偏差必须可归因）：
  - 卖出滑点按开盘价统一计算（`sell_slippage_at_open`：中性偏乐观）；
  - 涨跌停仅判「开盘即封板」，未模拟盘中反复开板（`zdt_open_only`：偏悲观，过度拒单）；
  - 量限按市场分档 `volume_limit_pct_by_market`（原固定 1%，修正后收敛）；
  - 基金/逆回购走净值透传，不参与撮合量限（`nav_pass_through`：中性）。

账户层钩子：`TradingAccount.execution_model` 只要求实现
`set_context(bars, prev_close)` 与 `check(...) -> {"reject": ...} | {"price", "volume"}`，
回测 / 模拟盘 / 实盘挂同一个类，不允许各写一套。
"""
from __future__ import annotations

import logging
import math
from typing import Dict, Optional

import config
from core.account import TradingAccount
from core.utils import setup_logger

__all__ = [
    "ExecutionModel",
    "LookaheadError",
    "NAV_PASSTHROUGH_MARKETS",
    "assert_fill_after_signal",
    "config_snapshot",
    "match_price_basis",
    "match_price_basis_meta",
    "slippage_for",
    "volume_limit_pct",
]

# 只做净值/定价、不参与二级市场撮合的市场（基金申赎 / 逆回购 / 场外产品）
NAV_PASSTHROUGH_MARKETS = {
    "cn_fund", "cn_reverse_repo", "private_fund", "qii_product",
    "asset_management", "otc_deriv", "trust",
}


class LookaheadError(RuntimeError):
    """成交所用 bar 早于/等于决策所用 bar —— 用未来信息在当下成交。"""


def config_snapshot() -> dict:
    return dict(getattr(config, "EXECUTION_MODEL", {}) or {})


def match_price_basis() -> str:
    """当前撮合价基准（`config.EXECUTION_MODEL["match_price_basis"]`，唯一参数源）。"""
    cfg = config_snapshot()
    basis = str(cfg.get("match_price_basis") or "next_open")
    meta = cfg.get("match_price_basis_meta") or {}
    if basis not in meta:
        raise ValueError(
            f"未知的 match_price_basis={basis!r}，合法取值 {sorted(meta)}；"
            f"请检查 config.EXECUTION_MODEL")
    return basis


def match_price_basis_meta(basis: str = None) -> dict:
    """基准元数据：{"price": open|close, "bar_offset": 0|1, "lookahead_safe": bool}。"""
    basis = str(basis or match_price_basis())
    cfg = config_snapshot()
    meta = dict((cfg.get("match_price_basis_meta") or {}).get(basis) or {})
    if not meta:
        raise ValueError(f"未知的 match_price_basis={basis!r}")
    meta.setdefault("price", "open")
    meta["bar_offset"] = int(meta.get("bar_offset", 1))
    meta["lookahead_safe"] = bool(meta.get("lookahead_safe", meta["bar_offset"] >= 1))
    return meta


def assert_fill_after_signal(signal_bar_index, fill_bar_index,
                             basis: str = None) -> None:
    """成交 bar 必须严格晚于决策 bar；违反时抛 LookaheadError。

    - `signal_bar_index`：策略做出决策时所用 bar 的下标；
    - `fill_bar_index`：实际撮合所用 bar 的下标；
    - 无论 basis 是 next_* 还是 same_*，只要带 signal 下标，成交 bar **必须严格大于**
      决策 bar；same_open / same_close（bar_offset=0）同根成交一律视为未来函数。
    `config.EXECUTION_MODEL["enforce_fill_after_signal"]=False` 时仅告警，便于对照实验。
    """
    if signal_bar_index is None or fill_bar_index is None:
        return
    meta = match_price_basis_meta(basis)
    signal_i, fill_i = int(signal_bar_index), int(fill_bar_index)
    # same_* 的 bar_offset=0 只表示"基准价字段取当根"，不代表允许同根成交
    earliest = signal_i + max(int(meta["bar_offset"]), 1)
    if fill_i >= earliest:
        return
    msg = (f"未来函数：决策 bar#{signal_i} → 成交 bar#{fill_i}（基准 {basis or match_price_basis()}，"
           f"要求 fill >= {earliest}）。禁止用同一根/更早的 bar 成交。")
    if bool(config_snapshot().get("enforce_fill_after_signal", True)):
        raise LookaheadError(msg)
    logging.getLogger(__name__).warning(msg)


def slippage_for(run_mode: str = "backtest", base_pct: float = None,
                 multiplier: float = None) -> float:
    """按运行环境参数化滑点：base × multiplier[run_mode]。"""
    cfg = config_snapshot()
    base = float(cfg.get("slippage_base_pct", 0.0005) if base_pct is None else base_pct)
    if multiplier is None:
        table = cfg.get("slippage_multiplier") or {}
        multiplier = float(table.get(str(run_mode).lower(), 1.0))
    return base * float(multiplier)


def volume_limit_pct(market: str) -> Optional[float]:
    """该市场的单笔成交量上限比例；None 表示不参与撮合量限。"""
    table = config_snapshot().get("volume_limit_pct_by_market") or {}
    if str(market) not in table:
        return None
    pct = table.get(str(market))
    return None if pct is None else float(pct)


class ExecutionModel:
    """透明成交模型：滑点 / 涨跌停 / 成交量上限 / 限价撮合（三引擎共用）。"""

    def __init__(self, slippage: float = None, max_volume_pct: float = None,
                 run_mode: str = "backtest", slippage_multiplier: float = None,
                 logger: logging.Logger = None, basis: str = None):
        cfg = config_snapshot()
        self.run_mode = str(run_mode or "backtest").lower()
        # 撮合价基准（唯一参数源 config.EXECUTION_MODEL，禁止写死开盘/收盘价）
        self.basis = str(basis or match_price_basis())
        self.basis_meta = match_price_basis_meta(self.basis)
        self.price_field = str(self.basis_meta["price"])
        self.bar_offset = int(self.basis_meta["bar_offset"])
        self.lookahead_safe = bool(self.basis_meta["lookahead_safe"])
        self.slippage = float(
            slippage if slippage is not None
            else slippage_for(self.run_mode, multiplier=slippage_multiplier))
        self.slippage_multiplier = float(
            slippage_multiplier if slippage_multiplier is not None
            else (cfg.get("slippage_multiplier") or {}).get(self.run_mode, 1.0))
        # 显式传入 max_volume_pct 时统一覆盖（兼容旧调用）；否则按市场分档
        self._uniform_volume_pct = None if max_volume_pct is None else float(max_volume_pct)
        self.zdt_reject_on_open = bool(cfg.get("zdt_reject_on_open", True))
        self.logger = logger or setup_logger("execution", config.LOG_DIR / "execution.log")
        self.bars: Dict[str, dict] = {}
        self.prev_close: Dict[str, float] = {}
        self._day_volume_base: Dict[str, float] = {}
        self.bar_index = None
        self.capped_orders = 0
        self.limit_rejects = 0
        self.limit_fills = 0

    # -- 参数 --
    @property
    def max_volume_pct(self) -> Optional[float]:
        """兼容旧接口：显式覆盖值；未覆盖返回 None（按市场分档）。"""
        return self._uniform_volume_pct

    def volume_pct_for(self, market: str) -> Optional[float]:
        if self._uniform_volume_pct is not None:
            return self._uniform_volume_pct
        return volume_limit_pct(market)

    # -- 上下文 --
    def set_context(self, bars: Dict[str, dict], prev_close: Dict[str, float],
                    bar_index: int = None, day_volume_base: Dict[str, float] = None) -> None:
        self.bars = dict(bars or {})
        self.prev_close = dict(prev_close or {})
        self.bar_index = bar_index
        # 分钟级量限分母（v3.53 扩围裁定）：{symbol: 最近已完结交易日全天成交量}。
        # 语义 = 「全天累计成交量不超过 X%」，用昨日全天量作分母（当日量在 bar
        # 开始时不可知）。None/缺 symbol 时回退当前 bar 的 volume（日线行为）。
        self._day_volume_base = dict(day_volume_base or {})

    # -- 未来函数 --
    def assert_fill_bar(self, signal_bar_index) -> None:
        """当前上下文 bar 作为成交 bar，校验它严格晚于决策 bar。"""
        assert_fill_after_signal(signal_bar_index, getattr(self, "bar_index", None),
                                 basis=self.basis)

    # -- 工具 --
    @staticmethod
    def _step_of(market: str, rule: dict) -> float:
        if market in ("cn_future", "global_future"):
            return float(rule.get("lot_step", 1) or 1)
        if market == "forex":
            return float(rule.get("min_lot", 0.01) or 0.01)
        if market == "crypto":
            return 1e-6
        if market == "cn_option":
            return 1.0
        if market == "cn_fund":
            return 1e-4
        return float(rule.get("qty_step") or rule.get("min_qty") or 1)

    def check(self, *, symbol: str, direction: str, action: str, order_type: str,
              volume: float, price: float, market: str, rule: dict,
              day=None, signal_bar_index: int = None) -> dict:
        """返回 {"reject": 原因} 或 {"price": 成交价, "volume": 成交量, ...}。

        `signal_bar_index` 非空时强制校验「成交 bar 严格晚于决策 bar」，
        违反 `config.EXECUTION_MODEL["match_price_basis"]` 的时点约束直接抛 LookaheadError。
        """
        self.assert_fill_bar(signal_bar_index)
        bar = self.bars.get(str(symbol))
        if not bar:
            return {"reject": f"当日无 {symbol} 行情，无法撮合"}
        if market in NAV_PASSTHROUGH_MARKETS:
            return {"price": float(price), "volume": float(volume)}

        open_px = float(bar.get("open") or 0) or float(price)
        high = float(bar.get("high") or open_px)
        low = float(bar.get("low") or open_px)
        close = float(bar.get("close") or open_px)
        buy_side = str(direction) in ("buy", "cover")

        # ---- 涨跌停：开盘即涨停买不进 / 开盘即跌停卖不出 ----
        pct = TradingAccount.price_limit_pct(market, symbol, rule)
        pc = self.prev_close.get(str(symbol))
        if self.zdt_reject_on_open and pct and pc and pc > 0:
            up = pc * (1 + pct)
            down = pc * (1 - pct)
            if buy_side and open_px >= up - 1e-9:
                self.limit_rejects += 1
                return {"reject": f"{symbol} 开盘即涨停（{open_px:g} ≥ {up:.4f}），买单不成交"}
            if (not buy_side) and open_px <= down + 1e-9:
                self.limit_rejects += 1
                return {"reject": f"{symbol} 开盘即跌停（{open_px:g} ≤ {down:.4f}），卖单不成交"}

        # ---- 限价单撮合 ----
        fill_px = None
        if order_type == "limit":
            limit_px = float(price)
            if buy_side and low <= limit_px:
                fill_px = min(limit_px, open_px)       # 开盘更优则按开盘成交
            elif (not buy_side) and high >= limit_px:
                fill_px = max(limit_px, open_px)
            if fill_px is None:
                return {"reject": f"{symbol} 限价单未触发（限价 {limit_px:g}，"
                                  f"当日区间 [{low:g}, {high:g}]）"}
            self.limit_fills += 1
        else:
            # 基准价字段由 match_price_basis_meta 决定（open / close），不在此写死
            ref_px = close if self.price_field == "close" else open_px
            fill_px = ref_px * (1 + self.slippage) if buy_side else ref_px * (1 - self.slippage)

        # ---- 成交量上限：按市场分档（None 表示不设限）----
        volume = float(volume)
        # 分钟级分母 = 最近已完结交易日全天量（「全天累计不超 X%」，防单分钟
        # 1% 过度宽松）；日线/未提供时 = 当前 bar volume（bar 即全天，行为不变）
        day_volume = float(self._day_volume_base.get(str(symbol))
                           or bar.get("volume") or 0)
        capped = False
        pct_cap = self.volume_pct_for(market)
        if pct_cap is not None and day_volume > 0:
            cap = day_volume * pct_cap
            step = self._step_of(market, rule)
            cap_units = math.floor(cap / step + 1e-9) * step
            if cap_units < step - 1e-9:
                return {"reject": f"{symbol} 流动性不足：当日成交量 {day_volume:g} 的 "
                                  f"{pct_cap:.2%} 不足最小成交单位 {step:g}"}
            if volume > cap_units + 1e-9:
                volume = cap_units
                capped = True
                self.capped_orders += 1
                self.logger.debug("%s 单笔委托超过当日量 %.2f%%，截断为 %.4f",
                                  symbol, pct_cap * 100, cap_units)

        return {"price": round(float(fill_px), 8), "volume": float(volume),
                "capped": capped, "open": open_px, "close": close}
