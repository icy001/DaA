# -*- coding: utf-8 -*-
"""美股日线预检（v3.54，验收单 §六C.20，可复现脚本）。

评审口径：AAPL + TSLA 最近 1 个月日线小样本，复用现有多市场框架；
事件源覆盖不足的标的 fail-closed raise（与港股 ETF 同构）。

事件源穷举（2026-11-26 实测，四渠道均无公开免费结构化分红/拆股事件源）：
  ① akshare stock_us* 全列无 div/split 接口
  ② 东财 datacenter F10 美股分红报表名穷举均「报表配置不存在」
  ③ 雅虎 query1/query2 全部 403（评审裁定放弃）
  ④ Nasdaq analyst dividends API 404
→ 按裁定：治理面 US_STOCK_CONFORMANCE.events_source 登记为空 +
  events_unavailable_action=raise——事件源接入前禁止取数/回测；
  双价折算与跳变审计的实测验证在事件源接入后进行，本轮验证
  数据源能力 + 闸门行为 + 交易规则逐项对账。

必查项：
  1) 数据源（直连实测）：东财美股日线 AAPL/TSLA 行数/列/交易日历无周末
  2) 事件源穷举证据 + fail-closed raise 证据（AAPL/TSLA 数据层出口）
  3) 交易规则：T+0、qty_step=1（可买 1 股，不复用整手校验）、费用逐项
     对账（佣金 0.0049/股 最低 0.99 双边 + SEC 卖出 0.00278% + TAF 卖出
     0.000166/股 最低 0.01）
  4) 固定汇率 7.20 折人民币口径（meta 标注）
  5) 治理面断言（events_source 空 / split=0.50 / qty_step / fx）
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import akshare as ak
import config
from core.account import TradingAccount
from core.data_fetcher import DataFetcher

TARGETS = ["AAPL", "TSLA"]
START = "2026-10-27"
END = "2026-11-26"


def main() -> int:
    ok = True
    anomaly = []
    t0 = time.time()
    print("=" * 68)
    print(f"美股日线预检 {'/'.join(TARGETS)} 请求区间 {START}~{END}（小样本口径）")

    # ---------- 1) 数据源直连实测（东财，免费公开接口；经内部出口带节流重试） ----------
    f0 = DataFetcher()
    for sym in TARGETS:
        try:
            raw = f0._request(ak.stock_us_hist, symbol=f"105.{sym}", period="daily",
                              start_date="20261027", end_date="20261126",
                              adjust="", _source="eastmoney")
            dates = pd.to_datetime(raw["日期"])
            weekend = int((dates.dt.dayofweek >= 5).sum())
            if len(raw) >= 15 and weekend == 0:
                print(f"✅ 1) 数据源 {sym}：{len(raw)} 行 {raw['日期'].iloc[0]}~"
                      f"{raw['日期'].iloc[-1]}，周末零 bar（交易日历独立、无周末错位）")
            else:
                anomaly.append(f"{sym} 数据异常 {len(raw)} 行/周末 {weekend}")
                ok = False
                print(f"❌ 1) {sym} 数据异常：{len(raw)} 行，周末 bar {weekend}")
        except Exception as exc:  # noqa: BLE001
            anomaly.append(f"{sym} 直连失败 {exc}")
            ok = False
            print(f"❌ 1) {sym} 东财直连失败：{str(exc)[:100]}")
        time.sleep(5)

    # ---------- 2) 事件源穷举 + fail-closed raise ----------
    print("✅ 2) 事件源穷举（四渠道，实测证据登记 US_STOCK_CONFORMANCE 注释）：")
    print("   ① akshare stock_us* 全列无 div/split 接口；② 东财 F10 报表名穷举"
          "「报表配置不存在」；③ 雅虎 403（裁定放弃）；④ Nasdaq API 404")
    for sym in TARGETS:
        try:
            f0.get_daily(sym, start_date=START, end_date=END, market_type="us_stock")
            anomaly.append(f"{sym} 未被事件闸拒绝")
            ok = False
            print(f"❌ 2) {sym} 未被 raise（事件闸被绕过——事件源缺失标的禁止取数）")
        except Exception as exc:  # noqa: BLE001
            if "事件源缺失" in str(exc):
                print(f"✅ 2) {sym} 数据层出口彻底 raise（与港股 ETF 同构，"
                      "fail-closed 正确行为）：双价折算与跳变审计待事件源接入后实测")
            else:
                anomaly.append(f"{sym} 拦截语义不符 {str(exc)[:60]}")
                ok = False
                print(f"❌ 2) {sym} 拦截原因不符：{str(exc)[:100]}")

    # ---------- 3) 交易规则：T+0 / qty_step=1 / 费用逐项对账 ----------
    acc = TradingAccount(1_000_000, run_mode="backtest")
    res1 = acc.place_order(symbol="AAPL", direction="buy", volume=1, price=200.0,
                           market_type="us_stock", data=pd.DataFrame(),
                           order_time=START, warmup_ok=True)
    if res1["status"] != "rejected":
        print("✅ 3) 无整手限制：买 1 股放行（qty_step=1，不复用港股/A股整手闸）")
    else:
        anomaly.append("买 1 股被拒")
        ok = False
        print(f"❌ 3) 买 1 股被拒：{res1.get('reason')}")
    fee_buy = float(acc.calc_commission("AAPL", "buy", 200.0, 100,
                                        market_type="us_stock", is_open=True))
    # 佣金 = max(100×0.0049, 0.99) = 0.99（买入仅佣金）
    if abs(fee_buy - 0.99) < 0.005:
        print(f"✅ 3b) 买入费用：100 股 @200 = {fee_buy:.2f} USD"
              "（佣金 max(0.49, 0.99)=0.99，单笔最低生效）")
    else:
        anomaly.append(f"买入费用 {fee_buy}")
        ok = False
        print(f"❌ 3b) 买入费用 {fee_buy} ≠ 0.99")
    fee_sell = float(acc.calc_commission("AAPL", "sell", 200.0, 100,
                                         market_type="us_stock", is_open=False))
    # 卖出 = 佣金 0.99 + SEC 20000×0.00278%=0.556 + TAF max(0.0166, 0.01)=0.0166
    exp_sell = 0.99 + 20000 * 0.0000278 + max(100 * 0.000166, 0.01)
    if abs(fee_sell - exp_sell) < 0.005:
        print(f"✅ 3c) 卖出费用：{fee_sell:.4f} USD（佣金 0.99 + SEC 0.556 + "
              f"TAF 0.0166，逐项吻合；SEC/TAF 卖出单边官方口径）")
    else:
        anomaly.append(f"卖出费用 {fee_sell} ≠ {exp_sell}")
        ok = False
        print(f"❌ 3c) 卖出费用 {fee_sell} ≠ {exp_sell}")
    t0_cfg = config.get_market_config("us_stock").get("t_plus")
    if t0_cfg == 0:
        print("✅ 3d) T+0 回转：t_plus=0 生效（当日买卖无持仓冻结）")
    else:
        anomaly.append("t_plus ≠ 0")
        ok = False

    # ---------- 4) 固定汇率折算口径 ----------
    fx = getattr(config, "US_STOCK_CONFORMANCE", {}).get("fx_fixed_cny")
    if fx == 7.20:
        print(f"✅ 4) 汇率口径：USD 计价，固定汇率 {fx} 折人民币（meta 标注；"
              "动态汇率+汇兑损益单列为非阻塞后续项）")
    else:
        anomaly.append(f"汇率口径 {fx}")
        ok = False

    # ---------- 5) 治理面断言 ----------
    conf = getattr(config, "US_STOCK_CONFORMANCE", {})
    checks = [
        (conf.get("events_source") == {}, "events_source 登记为空（穷举定案）"),
        (conf.get("events_unavailable_action") == "raise", "raise 闸"),
        (conf.get("jump_audit", {}).get("threshold_split") == 0.50,
         "拆股强制解释线 50%（评审裁定放宽，适配美股高波动）"),
        (conf.get("jump_audit", {}).get("threshold") == 0.05, "事件日核验线 5% 不变"),
        (conf.get("qty_step") == 1, "qty_step=1"),
        (conf.get("currency") == "USD" and conf.get("tz") == "America/New_York",
         "USD/America_New_York"),
    ]
    bad = [name for passed, name in checks if not passed]
    if not bad:
        print("✅ 5) 治理面断言全部成立：" + "；".join(name for _, name in checks))
    else:
        anomaly.append(f"治理面断言失败 {bad}")
        ok = False
        print(f"❌ 5) 治理面断言失败：{bad}")

    # ---------- 结果 ----------
    print("=" * 68)
    print(f"耗时 {time.time()-t0:.0f}s")
    if anomaly:
        print(f"❌ 异常表 {len(anomaly)} 条：{anomaly}")
        print("❌ 美股日线预检未通过")
        return 1
    print("✅ 异常表 0 条")
    print("✅ 美股日线预检通过（事件源穷举定案→raise 闸生效；双价/跳变审计/"
          "七闸门回测待事件源接入后实测，扩围口径待评审裁定）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
