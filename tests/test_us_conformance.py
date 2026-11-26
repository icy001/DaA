# -*- coding: utf-8 -*-
"""美股治理面专项测试（v3.54 美股日线预检轮，2026-11-26）。

评审裁定口径钉死：
  - 事件源穷举定案（四渠道无公开免费结构化事件源）→ fail-closed raise
    （与港股 ETF 同构；闸必须挡在路由之前——DataRouter 适配器路径曾绕过
    出口闸，实测 AAPL 经 router 直连成功、TSLA 失败才落老链路）
  - 拆股强制解释线 50%（适配美股高波动）、事件日核验线 5% 不变
  - qty_step=1 无整手限制、T+0、费用逐项（佣金 0.0049/股 最低 0.99 双边
    + SEC 卖出 0.00278% + TAF 卖出 0.000166/股 最低 0.01）
  - USD 计价、固定汇率 7.20 折人民币
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from core.account import TradingAccount
from core.data_fetcher import DataFetcher


def test_us_conformance_governance_block():
    """治理面断言：事件源穷举定案 + 拆股线 50% + 核验线 5% + qty_step + 汇率。"""
    conf = getattr(config, "US_STOCK_CONFORMANCE")
    assert conf["events_source"] == {}, "事件源穷举无果必须显式登记为空（非缺省漏登）"
    assert conf["events_unavailable_action"] == "raise"
    ja = conf["jump_audit"]
    assert float(ja["threshold"]) == 0.05            # 事件日核验线不变
    assert float(ja["threshold_split"]) == 0.50      # 拆股线放宽（评审裁定）
    assert conf["qty_step"] == 1 and conf["t_plus"] == 0
    assert conf["currency"] == "USD" and float(conf["fx_fixed_cny"]) == 7.20
    # MARKETS 基础配置同口径
    rule = config.get_market_config("us_stock")
    assert int(rule["qty_step"]) == 1 and int(rule["t_plus"]) == 0
    assert float(rule["commission_per_share"]) == 0.0049
    assert float(rule["commission_min"]) == 0.99
    assert float(rule["sec_fee_sell"]) == 0.0000278
    assert float(rule["taf_fee_sell"]) == 0.000166 and float(rule["taf_min"]) == 0.01
    assert rule.get("price_limit") is None            # 无涨跌停


def test_us_commission_itemized():
    """费用逐项对账（评审要求全部实测对账）：
    买入仅佣金（单笔最低生效）；卖出 = 佣金 + SEC + TAF（单边、含最低）。"""
    acc = TradingAccount(1_000_000, run_mode="backtest")
    fee_buy = float(acc.calc_commission("AAPL", "buy", 200.0, 100,
                                        market_type="us_stock", is_open=True))
    assert fee_buy == pytest.approx(0.99, abs=0.005)   # max(100×0.0049, 0.99)
    fee_sell = float(acc.calc_commission("AAPL", "sell", 200.0, 100,
                                         market_type="us_stock", is_open=False))
    assert fee_sell == pytest.approx(0.99 + 20000 * 0.0000278
                                     + max(100 * 0.000166, 0.01), abs=0.005)
    # 买 1 股佣金触发最低 0.99；qty_step=1 放行
    res = acc.place_order(symbol="AAPL", direction="buy", volume=1, price=200.0,
                          market_type="us_stock", data=pd.DataFrame(),
                          order_time="2026-11-20", warmup_ok=True)
    assert res["status"] != "rejected", res


def test_us_daily_event_gate_raises_before_router():
    """事件源闸必须挡在路由之前：get_daily（顶层）与 _fetch_us_stock_daily
    （出口）双位 raise，堵死 DataRouter 适配器绕行路径。"""
    f = DataFetcher()
    with pytest.raises(RuntimeError, match="事件源缺失"):
        f.get_daily("AAPL", start_date="2026-10-27", end_date="2026-11-26",
                    market_type="us_stock")
    with pytest.raises(RuntimeError, match="事件源缺失"):
        f.get_daily("TSLA", start_date="2026-10-27", end_date="2026-11-26",
                    market_type="us_stock")
    with pytest.raises(RuntimeError, match="事件源缺失"):
        f._fetch_us_stock_daily("AAPL", "2026-10-27", "2026-11-26", "")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
