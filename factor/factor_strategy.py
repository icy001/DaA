"""因子 → 交易策略适配器（第 5 步 5.9.9）。

把「日期×股票」的因子综合打分转换成可直接接入回测 / 模拟盘 / 实盘仿真的
`BaseStrategy` 子类：用户只配置因子与权重参数，不用自己写交易代码。

【策略文件铁律的唯一例外】
`core/strategy.py` 规定策略文件里禁止直接取数。本文件是**系统内置适配器**，
不是用户策略文件，因此允许在内部用执行器注入的 `self.fetcher` 构造
`FactorEngine` 拉取全市场面板——`self.get_history()` 只能拿到单标的窗口，
拿不到「日期×股票」的因子面板，没有别的合规途径。
除此之外，下单、风控、预热闸门仍然全部走父类的 `self.buy/sell`。

【关键设计】
1. 构造 / `init()` 阶段绝不联网：因子打分延迟到首次 `on_bar` 才计算一次，
   之后按调仓日取当日截面打分（只用 <= 当日 的分数，不引入未来数据）；
2. 离线测试可注入 `params["factor_panel_provider"]`：
   `callable(params, symbols) -> {factor_name: DataFrame(日期×股票)}`，
   完全绕过网络；
3. 调仓日按 `rebalance_freq` 从因子面板日期推导（weekly/biweekly/monthly 的
   每周期最后一个交易日；遇节假日顺延到下一个有行情的交易日执行）；
4. 非调仓日不做任何买卖，止损 / 止盈由父类内置风控完成，不在这里重复实现。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

import config
from core.strategy import BaseStrategy

from .combiner import combine

logger = logging.getLogger(__name__)

__all__ = ["FactorStrategy"]


class FactorStrategy(BaseStrategy):
    """多因子选股策略：调仓日按综合打分选 Top N 并做权重约束。"""

    meta = {
        "name": "factor_strategy",
        "display_name": "多因子选股策略",
        "markets": ["cn_stock", "cn_etf"],
        "periods": ["1d"],
        "params": {
            "factor_list": ["alpha001"],
            "combine_method": "equal_weight",
            "universe": "hs300",
            "n_top": 50,
            "rebalance_freq": "weekly",
            "weight_method": "equal_weight",
            "single_limit": 0.05,
            "industry_limit": 0.30,
            "stop_loss": 0.08,
            "take_profit": 0.20,
            # 成交额下限（元）；缺失 amount 字段时跳过该过滤
            "min_amount": 5e7,
        },
        "description": "按因子综合打分选股的多因子策略（支持 Top N / 单票与行业权重约束）",
        "author": "DaA",
        "version": "1.0",
        # 至少声明 MA20：用于反推 warmup_bars，保证预热期不出开仓信号
        "warmup": [("MA", {"n": 20})],
    }

    # ==================== 生命周期 ====================
    def init(self) -> None:
        """只做参数读取，绝不联网；因子面板在首次 on_bar 时才准备。"""
        p = self.params
        self.factor_list: List[str] = list(p.get("factor_list") or ["alpha001"])
        self.combine_method: str = str(p.get("combine_method") or "equal_weight")
        self.universe = p.get("universe") or "hs300"
        self.n_top: int = max(int(p.get("n_top") or 50), 1)
        self.rebalance_freq: str = str(p.get("rebalance_freq") or "weekly").lower()
        self.weight_method: str = str(p.get("weight_method") or "equal_weight").lower()
        self.single_limit: float = float(p.get("single_limit") or 0.05)
        self.industry_limit: float = float(p.get("industry_limit") or 0.30)
        self.min_amount: float = float(p.get("min_amount") or 0.0)

        self._factor_panel: Optional[Dict[str, pd.DataFrame]] = None
        self._scores: Optional[pd.DataFrame] = None
        self._rebalance_dates: List[pd.Timestamp] = []
        self._last_rebalance: Optional[pd.Timestamp] = None
        self._last_target_weights: Dict[str, float] = {}
        self._warned: set = set()

    # ==================== 主循环 ====================
    def on_bar(self, date, bar_dict: Dict[str, dict]) -> None:
        self._ensure_scores(bar_dict)
        if self._scores is None or self._scores.empty:
            return
        if not self._is_rebalance_due(date):
            # 非调仓日：止损/止盈由父类 _run_risk_controls 已完成
            return
        row = self._score_row(date)
        if row is None:
            return
        self._rebalance(date, bar_dict, row)

    # ==================== 因子打分（延迟、只算一次） ====================
    def _ensure_scores(self, bar_dict: Dict[str, dict]) -> None:
        if self._factor_panel is not None:
            return
        symbols = self._universe_symbols(bar_dict)
        if not symbols:
            return

        provider = self.params.get("factor_panel_provider")
        if callable(provider):
            # 离线/测试注入的桩：直接返回 {因子名: 日期×股票}
            raw = provider(dict(self.params), symbols)
        else:
            # 【铁律例外】系统内置适配器允许用执行器注入的 fetcher 构造因子引擎
            from .factor_engine import FactorEngine

            engine = FactorEngine(fetcher=self.fetcher)
            start, end = self._factor_window()
            raw = engine.compute(self.factor_list, universe=self.universe,
                                 start=start, end=end)

        panels: Dict[str, pd.DataFrame] = {}
        for name, value in (raw or {}).items():
            if not isinstance(value, pd.DataFrame) or value.empty:
                continue
            df = value.copy()
            df.index = pd.to_datetime(df.index)
            df.columns = [str(c) for c in df.columns]
            panels[str(name)] = df.sort_index()
        if not panels:
            self._warn_once("empty_panel", "因子面板为空，策略本周不调仓")
            return

        try:
            self._scores = combine(self.combine_method, panels)
        except Exception as exc:  # 合成失败不应让整个回测中断
            self._warn_once("combine_fail", f"因子合成失败（{exc}），降级为等权")
            self._scores = combine("equal_weight", panels)

        self._factor_panel = panels
        self._rebalance_dates = self._build_rebalance_dates(self._scores.index)

    def _universe_symbols(self, bar_dict: Dict[str, dict]) -> List[str]:
        """股票池：优先 params["symbols"]，否则用当日有行情的标的。"""
        explicit = self.params.get("symbols")
        if explicit:
            return [str(s) for s in explicit]
        return list(bar_dict.keys())

    def _factor_window(self) -> Tuple[str, str]:
        """因子计算区间：默认覆盖回测区间；纯预测场景下可用 factor_start/end 覆盖。"""
        end = (self.params.get("factor_end") or self.params.get("end")
               or pd.Timestamp.today().strftime("%Y-%m-%d"))
        start = self.params.get("factor_start") or self.params.get("start")
        if not start:
            start = (pd.Timestamp(end) - pd.Timedelta(days=420)).strftime("%Y-%m-%d")
        return str(start), str(end)

    def _build_rebalance_dates(self, index: pd.Index) -> List[pd.Timestamp]:
        """从因子面板日期推导每个周期的最后一个交易日。"""
        idx = pd.DatetimeIndex(pd.to_datetime(index)).sort_values()
        if len(idx) == 0:
            return []
        freq = self.rebalance_freq
        if freq == "monthly":
            groups = idx.to_series().groupby([idx.year, idx.month])
            dates = [g.max() for _, g in groups]
        else:
            weeks = list(idx.to_series().groupby([idx.year, idx.isocalendar().week]))
            weeks.sort(key=lambda kv: kv[1].max())
            dates = []
            for i, (_, g) in enumerate(weeks):
                if freq in ("biweekly", "bi_weekly", "2weekly") and i % 2 == 1:
                    continue
                dates.append(g.max())
        return sorted(pd.Timestamp(d) for d in dates)

    # ==================== 调仓日判定 ====================
    def _is_rebalance_due(self, date) -> bool:
        if not self._rebalance_dates:
            return False
        day = pd.Timestamp(date)
        due = [d for d in self._rebalance_dates if d <= day]
        if not due:
            return False
        target = due[-1]
        # 每周最后一个交易日恰逢节假日时，顺延到下一个有行情的交易日执行
        return self._last_rebalance is None or target > self._last_rebalance

    def _score_row(self, date) -> Optional[pd.Series]:
        window = self._scores.loc[:pd.Timestamp(date)]
        if window.empty:
            return None
        return window.iloc[-1]

    # ==================== 组合构建 ====================
    def _rebalance(self, date, bars: Dict[str, dict], scores: pd.Series) -> None:
        equity = self.equity
        if equity <= 0:
            return

        candidates: List[Tuple[str, float]] = []
        for symbol, score in scores.items():
            bar = bars.get(str(symbol))
            if bar is None or not np.isfinite(float(score)):
                continue
            reason = self._filter_reason(bar)
            if reason:
                continue
            candidates.append((str(symbol), float(score)))
        if not candidates:
            self._last_rebalance = pd.Timestamp(date)
            return

        candidates.sort(key=lambda item: item[1], reverse=True)
        top = candidates[: self.n_top]
        weights = self._allocate_weights(top, bars)
        self._last_target_weights = dict(weights)
        self._last_rebalance = pd.Timestamp(date)

        prices = self.prices
        # 先卖出（腾出现金、满足 T+1 后再买），再买入
        for symbol, pos in list(self.account.positions.items()):
            px = prices.get(symbol)
            if px is None or px <= 0 or pos.volume <= 0:
                continue
            target_vol = self._target_volume(equity, weights.get(symbol, 0.0), px, symbol)
            available = float(pos.available)
            if available <= 0:
                continue
            if symbol not in weights:
                self.sell(symbol, available, px)
            elif pos.volume - target_vol >= self._lot_size(symbol):
                diff = min(available, pos.volume - target_vol)
                if diff > 0:
                    self.sell(symbol, diff, px)

        for symbol, weight in weights.items():
            px = prices.get(symbol)
            if px is None or px <= 0:
                continue
            if not self.is_warmup_ok(symbol):
                # 预热期由父类拒单；这里提前跳过，避免刷无意义的拒单记录
                continue
            pos = self.get_position(symbol)
            current = float(pos.volume) if pos is not None else 0.0
            target_vol = self._target_volume(equity, weight, px, symbol)
            diff = target_vol - current
            lot = self._lot_size(symbol)
            if diff >= lot:
                self.buy(symbol, int(diff // lot * lot), px)

        self.logger.info("因子调仓 %s：选中 %d 只，目标权重合计 %.2f%%",
                         pd.Timestamp(date).date(), len(weights),
                         sum(weights.values()) * 100)

    def _allocate_weights(self, top: Sequence[Tuple[str, float]],
                          bars: Dict[str, dict]) -> Dict[str, float]:
        n = len(top)
        if n == 0:
            return {}
        raw: Dict[str, float] = {}
        if self.weight_method == "rank_weight":
            scores = {sym: float(n - i) for i, (sym, _) in enumerate(top)}
            total = sum(scores.values()) or 1.0
            raw = {sym: v / total for sym, v in scores.items()}
        elif self.weight_method == "market_cap_weight":
            caps: Dict[str, float] = {}
            for sym, _ in top:
                bar = bars.get(sym) or {}
                cap = (bar.get("market_cap") or bar.get("cap")
                       or bar.get("circ_mv") or bar.get("total_mv"))
                if cap is None or not np.isfinite(float(cap)) or float(cap) <= 0:
                    caps = {}
                    break
                caps[sym] = float(cap)
            if not caps:
                self._warn_once("no_cap", "缺少市值字段，market_cap_weight 降级为等权")
                raw = {sym: 1.0 / n for sym, _ in top}
            else:
                total = sum(caps.values()) or 1.0
                raw = {sym: v / total for sym, v in caps.items()}
        else:
            raw = {sym: 1.0 / n for sym, _ in top}

        # 单票上限
        weights = {sym: min(float(w), self.single_limit) for sym, w in raw.items()}

        # 行业集中度上限：行业内合计超限则等比例缩减
        industries: Dict[str, str] = {}
        missing = False
        for sym, _ in top:
            bar = bars.get(sym) or {}
            ind = bar.get("industry") or bar.get("sector") or bar.get("sw_industry")
            if ind is None:
                missing = True
                break
            industries[sym] = str(ind)
        if missing:
            self._warn_once("no_industry", "行情缺少行业字段，跳过行业集中度约束")
        elif industries:
            totals: Dict[str, float] = {}
            for sym, w in weights.items():
                totals[industries[sym]] = totals.get(industries[sym], 0.0) + w
            for sym, w in list(weights.items()):
                total = totals.get(industries[sym], 0.0)
                if total > self.industry_limit > 0:
                    weights[sym] = w * self.industry_limit / total

        # 缩放后再次保证单票上限
        return {sym: min(w, self.single_limit) for sym, w in weights.items() if w > 0}

    # ==================== 过滤 ====================
    def _filter_reason(self, bar: dict) -> Optional[str]:
        """返回剔除原因；返回 None 表示通过。缺失字段时跳过该过滤并只警告一次。"""
        if not any(k in bar for k in ("is_suspended", "is_pause", "volume")):
            self._warn_once("no_pause", "行情缺少停牌字段（is_suspended/volume），跳过停牌过滤")
        else:
            suspended = bar.get("is_suspended", bar.get("is_pause"))
            if suspended is True:
                return "停牌"
            volume = bar.get("volume")
            if volume is not None and np.isfinite(float(volume)) and float(volume) <= 0:
                return "停牌（成交量 0）"

        if not any(k in bar for k in ("is_st", "is_risk_warning", "name")):
            self._warn_once("no_st", "行情缺少 ST 字段（is_st/name），跳过 ST 过滤")
        elif bar.get("is_st") is True or bar.get("is_risk_warning") is True:
            return "ST/风险警示"

        limit = self._limit_hit(bar)
        if limit is None:
            self._warn_once("no_limit", "行情缺少涨跌停字段（limit_up/pct_chg），跳过涨跌停过滤")
        elif limit:
            return "涨停/跌停"

        if "amount" not in bar:
            self._warn_once("no_amount", "行情缺少成交额字段（amount），跳过流动性过滤")
        elif self.min_amount > 0:
            amount = bar.get("amount")
            if amount is not None and np.isfinite(float(amount)) and float(amount) < self.min_amount:
                return "成交额不足"
        return None

    @staticmethod
    def _limit_hit(bar: dict) -> Optional[bool]:
        """True=涨跌停；False=正常；None=字段缺失无法判断。"""
        if "limit_up" in bar or "limit_down" in bar:
            return bool(bar.get("limit_up") is True or bar.get("limit_down") is True)
        pct = bar.get("pct_chg")
        if pct is not None and np.isfinite(float(pct)):
            return abs(float(pct)) >= 9.8
        pre_close, close = bar.get("pre_close"), bar.get("close")
        if pre_close is not None and close is not None and float(pre_close) > 0:
            return abs(float(close) / float(pre_close) - 1.0) >= 0.098
        return None

    # ==================== 小工具 ====================
    def _target_volume(self, equity: float, weight: float, price: float, symbol: str) -> float:
        if weight <= 0 or price <= 0:
            return 0.0
        lot = self._lot_size(symbol)
        shares = equity * float(weight) / float(price)
        return float(np.floor(shares / lot) * lot)

    @staticmethod
    def _lot_size(symbol: str) -> int:
        try:
            market = config.detect_market_type(str(symbol))
        except Exception:
            market = "cn_stock"
        return 100 if market in ("cn_stock", "cn_etf") else 1

    def _warn_once(self, key: str, message: str) -> None:
        if key in self._warned:
            return
        self._warned.add(key)
        self.logger.warning("FactorStrategy: %s", message)

    # ==================== 配置加载 ====================
    @classmethod
    def from_config(cls, path=None) -> dict:
        """读取策略 yaml（默认 configs/strategies/factor_strategy.yaml）。

        文件不存在时只返回默认参数，不报错；返回结构：
        {"strategy": 名称, "params": 合并后的参数, "symbols": [...],
         "start": ..., "end": ...}
        """
        cfg_path = Path(path) if path else (
            Path(config.BASE_DIR) / "configs" / "strategies" / "factor_strategy.yaml")
        result = {
            "strategy": cls.meta["name"],
            "params": dict(cls.meta.get("params") or {}),
            "symbols": [],
            "start": None,
            "end": None,
        }
        if not cfg_path.exists():
            return result
        try:
            import yaml
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # 配置写坏也不能让调用方崩溃
            logger.warning("读取策略配置 %s 失败：%s，已回退默认参数", cfg_path, exc)
            return result
        result["params"].update(dict(data.get("params") or {}))
        result["symbols"] = [str(s) for s in (data.get("symbols") or [])]
        result["start"] = data.get("start")
        result["end"] = data.get("end")
        return result
