"""示例策略 5/9：期权卖出宽跨式（进阶，期权专属）。

逻辑：
  - 每月**首个交易日**卖出当月虚值看涨 + 虚值看跌（宽跨式），收取权利金；
  - 行权价按「ATM 近似 + 行权价间距」向外找 delta≈0.2 的档位
    （ATM 用标的收盘价近似，delta 用 core.indicators.DELTA 计算）；
  - 只有 IVR（隐含波动率分位）> 50 才开仓：低波动时卖期权收不到多少权利金，
    却承担尾部风险；
  - 任一腿 delta > 0.5（已被打成实值）或临近到期 → 平仓；
  - 双边保证金合计不超过总资金的 30%。

简化：标的取最新收盘价作 ATM；IV 由期权当日收盘价经
`core.indicators.IMPLIED_VOL` 反解后按历史分位得 IVR；保证金按交易所系数估算。

已知限制：第 5 步的轻量账户对「期权卖方」的持仓成本按合约名义金额记账
（`core/account.py`，第 6 步全市场回测引擎会改成按权利金口径），
因此自检里持有期内权益曲线会被放大，收益/回撤数字只看个「跑通了」即可。
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from core import indicators as ind
from core.strategy import BaseStrategy


class OptionSellStrangle(BaseStrategy):
    """IV 高位卖宽跨式，delta 走深或临期平仓。"""

    meta = {
        "name": "option_sell_strangle",
        "display_name": "期权卖出宽跨式",
        "markets": ["cn_option"],
        "periods": ["1d"],
        "params": {
            "underlying": "510300",
            "call_symbol": "10004567",
            "put_symbol": "10004568",
            "strike_step": 0.05,          # 行权价间距（ETF 期权近似）
            "delta_target": 0.2,          # 卖出的虚值档位
            "delta_close": 0.5,           # 任一腿 delta 超过它即平仓
            "ivr_threshold": 50.0,        # IVR > 50 才开仓
            "ivr_min_samples": 60,        # IVR 至少要有的历史样本数
            "sigma": 0.2,                 # 计算 delta 用的波动率假设
            "days_to_expiry": 30,
            "contracts": 1,
            "multiplier": 10_000,
            "seller_margin_rate": {"call": 0.12, "put": 0.07},
            "margin_limit": 0.3,          # 保证金 / 总资金上限
            "capital": 1_000_000.0,
            "close_before_expiry_days": 2,
        },
        "description": "每月初 IVR>50 时卖出 delta≈0.2 的宽跨式，delta>0.5 或临期平仓",
        "author": "quant-team",
        "version": "1.0",
        "warmup": [("MA", {"n": 20})],
    }

    def init(self):
        self._open_month = None
        self._legs: dict = {}        # 期权代码 → {strike, expiry, kind}
        self._iv_hist: list = []

    def on_bar(self, date, bars):
        underlying = str(self.params["underlying"])
        if underlying not in bars:
            return
        today = pd.Timestamp(date).normalize()
        spot_bar = bars[underlying]
        spot = float(spot_bar.get("close") or 0.0)
        if spot <= 0:
            return

        call_sym = str(self.params["call_symbol"])
        put_sym = str(self.params["put_symbol"])
        call_bar = bars.get(call_sym)
        put_bar = bars.get(put_sym)
        days = float(self.params["days_to_expiry"])
        atm = self._atm_strike(spot)

        # ---------- 1) IV 采样与 IVR ----------
        if call_bar and call_bar.get("close"):
            iv = ind.IMPLIED_VOL(float(call_bar["close"]), spot, atm, days / 365.0,
                                 kind="call")
            if np.isfinite(iv) and float(iv) > 0:
                self._iv_hist.append(float(iv))
                self._iv_hist = self._iv_hist[-500:]
        ivr = self._ivr()

        # ---------- 2) 平仓：delta 走深 / 临近到期 ----------
        for symbol, leg in list(self._legs.items()):
            pos = self.get_position(symbol)
            if pos is None or pos.available <= 0:
                self._legs.pop(symbol, None)
                continue
            remain = max((leg["expiry"] - today).days, 0)
            delta = abs(float(ind.DELTA(spot, leg["strike"], max(remain, 1) / 365.0,
                                        sigma=float(self.params["sigma"]), kind=leg["kind"])))
            if delta > float(self.params["delta_close"]) \
                    or remain <= int(self.params["close_before_expiry_days"]):
                self.cover(symbol, pos.available)
                self._legs.pop(symbol, None)

        # ---------- 3) 每月首个交易日开仓 ----------
        month_key = today.strftime("%Y-%m")
        if self._open_month == month_key:
            return
        self._open_month = month_key
        if ivr is None or ivr <= float(self.params["ivr_threshold"]):
            return
        if not (call_bar and put_bar):
            return
        if self.get_position(call_sym) is not None or self.get_position(put_sym) is not None:
            return
        call_price = float(call_bar.get("close") or 0.0)
        put_price = float(put_bar.get("close") or 0.0)
        if call_price <= 0 or put_price <= 0:
            return

        k_call = self._delta_strike(spot, days / 365.0, "call", +1)
        k_put = self._delta_strike(spot, days / 365.0, "put", -1)
        margin = self._margin_estimate(spot, call_price, put_price)
        if margin > float(self.params["capital"]) * float(self.params["margin_limit"]):
            return

        expiry = today + pd.Timedelta(days=int(days))
        contracts = float(self.params["contracts"])
        self.short(call_sym, contracts, call_price, underlying_price=spot,
                   option_type="call", strike=k_call, expiry=expiry)
        self.short(put_sym, contracts, put_price, underlying_price=spot,
                   option_type="put", strike=k_put, expiry=expiry)
        self._legs[call_sym] = {"strike": k_call, "expiry": expiry, "kind": "call"}
        self._legs[put_sym] = {"strike": k_put, "expiry": expiry, "kind": "put"}

    # ---------- 内部工具 ----------
    def _atm_strike(self, spot: float) -> float:
        step = float(self.params["strike_step"])
        return round(spot / step) * step

    def _delta_strike(self, spot: float, tenor: float, kind: str, direction: int) -> float:
        """从 ATM 向外逐档移动，直到 |delta| <= delta_target。"""
        step = float(self.params["strike_step"])
        target = float(self.params["delta_target"])
        strike = self._atm_strike(spot)
        for _ in range(60):
            delta = abs(float(ind.DELTA(spot, strike, tenor,
                                        sigma=float(self.params["sigma"]), kind=kind)))
            if delta <= target:
                break
            strike += direction * step
        return round(strike, 6)

    def _margin_estimate(self, spot: float, call_price: float, put_price: float) -> float:
        multiplier = float(self.params["multiplier"])
        rates = self.params["seller_margin_rate"]
        contracts = float(self.params["contracts"])
        call_part = call_price * multiplier + spot * multiplier * float(rates["call"])
        put_part = put_price * multiplier + spot * multiplier * float(rates["put"])
        return (call_part + put_part) * contracts

    def _ivr(self):
        """IVR：当前 IV 在最近样本中的百分位（0~100），样本不足返回 None。"""
        if len(self._iv_hist) < int(self.params["ivr_min_samples"]):
            return None
        window = self._iv_hist[-252:]
        current = window[-1]
        return 100.0 * float(np.mean(np.asarray(window) <= current))


if __name__ == "__main__":
    from strategies._selftest import run_selftest

    run_selftest(OptionSellStrangle, symbols=["510300", "10004567", "10004568"])
