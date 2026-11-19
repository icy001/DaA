"""第 4 步统一账户与订单管理测试（不依赖网络，纯构造数据/桩 fetcher）。

覆盖：
 1) 100 万账户买茅台（A股 T+1、佣金/过户费、持仓成本）；
 2) 当日卖出被 T+1 拦截、次日可卖；
 3) 资金不足拒单；
 4) 螺纹钢期货（保证金占用、平今仓手续费与保证金释放）；
 5) IF 平今仓费率远高于开仓（calc_commission 直算）；
 6) 做空权限：A股拒绝、美股可做空并正确回补；
 7) 可转债 T+0 当日买卖；
 8) 期权买方付权利金 / 卖方收权利金并冻结保证金；
 9) 国债逆回购下单、到期本息回款；
10) 基金申购费与按持有天数递减的赎回费；
11) 不可交易品种（sh000300）拒单；
12) 【数据时效闸门】live 模式下无时效列仍被 refetch 拦住；backtest 豁免；
    回测内显式 for_trading=True 仍拦；refetch 失败开仓拒/平仓放；TTL 内复用；
13) 权益口径（现货市值、卖空负债、保证金加回）。
"""
from __future__ import annotations

import sys
from datetime import date as _date
from datetime import timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from core.account import Position, TradingAccount

PASS, FAIL = [], []
EPS = 0.011  # 金额比较容差（分）


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'✅' if ok else '❌'} {name}" + (f" | {detail}" if detail else ""))


def near(a, b, tol=EPS) -> bool:
    return abs(float(a) - float(b)) <= tol


# ==================== 时效闸门桩 fetcher ====================

class StaleFetcher:
    """返回一根 40 天前的日线，模拟本地库过期。"""

    def __init__(self, days_ago: int = 40):
        self.asof = pd.Timestamp.today().normalize() - pd.Timedelta(days=days_ago)

    def get_daily(self, symbol, start_date=None, end_date=None, adjust="", market_type=None):
        idx = pd.DatetimeIndex([self.asof])
        return pd.DataFrame({"close": [100.0]}, index=idx)


class FreshFetcher:
    """返回今天的一根日线（视为最新）。"""

    def __init__(self):
        self.calls = 0

    def get_daily(self, symbol, start_date=None, end_date=None, adjust="", market_type=None):
        self.calls += 1
        idx = pd.DatetimeIndex([pd.Timestamp.today().normalize()])
        return pd.DataFrame({"close": [100.0]}, index=idx)


class FailingFetcher:
    """数据源不可达。"""

    def get_daily(self, *args, **kwargs):
        raise RuntimeError("模拟数据源不可达")


def main() -> int:
    today = _date.today()
    tomorrow = today + timedelta(days=1)

    # ---------- 1. 初始化 ----------
    acct = TradingAccount(1_000_000)
    check("初始化 100 万账户：现金/持仓/保证金", near(acct.cash, 1_000_000)
          and not acct.positions and acct.margin_used == 0,
          f"cash={acct.cash:.2f}")

    # ---------- 2. 买茅台（A股 T+1） ----------
    r = acct.place_order("600519", "buy", "market", 100, 1600.0, order_time=today,
                         warmup_ok=True)
    pos = acct.positions.get("600519")
    exp_fee = round(max(160000 * 0.00025, 5) + 160000 * 0.00001, 2)  # 佣金 40 + 过户费 1.6
    check("茅台买入成交", r["status"] == "filled", str(r.get("reason", "")))
    check("茅台手续费 = 佣金40 + 过户费1.6 = 41.6", near(r["commission"], exp_fee),
          f"{r['commission']} vs {exp_fee}")
    check("买入后现金扣减正确", near(acct.cash, 1_000_000 - 160_000 - exp_fee),
          f"{acct.cash:.2f}")
    check("持仓成本含买入费用", pos is not None and near(pos.avg_cost, (160_000 + exp_fee) / 100),
          f"avg_cost={pos.avg_cost:.6f}")
    check("T+1：当日买入不可卖（冻结 100）", pos is not None and pos.frozen_volume == 100)

    r_t1 = acct.place_order("600519", "sell", "market", 100, 1650.0, order_time=today)
    check("当天卖出茅台被 T+1 拒绝",
          r_t1["status"] == "rejected" and ("T+1" in r_t1["reason"] or "可用持仓不足" in r_t1["reason"]),
          r_t1["reason"])

    r_next = acct.place_order("600519", "sell", "market", 100, 1650.0, order_time=tomorrow)
    sell_fee = round(max(165000 * 0.00025, 5) + 165000 * 0.0005 + 165000 * 0.00001, 2)
    exp_realized = round((1650 - (160_000 + exp_fee) / 100) * 100 - sell_fee, 2)
    check("次日卖出成交（印花税+佣金+过户费）",
          r_next["status"] == "filled" and near(r_next["commission"], sell_fee),
          f"fee={r_next.get('commission')} vs {sell_fee}")
    check("卖出已实现盈亏正确", near(r_next.get("realized_pnl", 0), exp_realized),
          f"{r_next.get('realized_pnl')} vs {exp_realized}")

    # ---------- 3. 资金不足 ----------
    poor = TradingAccount(1_000_000)
    r = poor.place_order("600519", "buy", "market", 1000, 1600.0, order_time=today,
                         warmup_ok=True)
    check("1000 股茅台（160 万）资金不足拒单",
          r["status"] == "rejected" and "资金不足" in r["reason"], r["reason"])

    # ---------- 4. 螺纹钢期货（保证金 + 平今） ----------
    fut = TradingAccount(1_000_000)
    r = fut.place_order("RB2601", "buy", "market", 10, 3800.0, order_time=today,
                        warmup_ok=True)
    p = fut.positions.get("RB2601")
    exp_margin = 3800 * 10 * 10 * 0.09
    check("螺纹钢 10 手买入成交", r["status"] == "filled", r.get("reason", ""))
    check("期货保证金 = 3800×10×10×9% = 34200", near(r.get("margin", 0), exp_margin),
          f"{r.get('margin')} vs {exp_margin}")
    check("期货开仓手续费 1 元/手×10 = 10", near(r["commission"], 10.0), f"{r['commission']}")
    check("保证金从现金划出、计入 margin_used",
          near(fut.cash, 1_000_000 - exp_margin - 10) and near(fut.margin_used, exp_margin),
          f"cash={fut.cash:.2f} margin={fut.margin_used:.2f}")

    r2 = fut.place_order("RB2601", "sell", "market", 4, 3850.0, order_time=today)
    exp_pnl = (3850 - 3800) * 10 * 4 - 4  # 平今 1 元/手
    check("当日卖出 4 手按平今仓计费", r2["status"] == "filled" and near(r2["commission"], 4.0),
          f"fee={r2.get('commission')}")
    check("平仓盈亏 = 50×10×4 − 手续费 4", near(r2.get("realized_pnl", 0), exp_pnl),
          f"{r2.get('realized_pnl')} vs {exp_pnl}")
    check("平仓释放 40% 保证金", near(fut.margin_used, exp_margin * 0.6),
          f"{fut.margin_used:.2f} vs {exp_margin * 0.6:.2f}")

    # 平今费率 vs 开仓费率（IF：0.0345% vs 0.0023%）
    if_open = fut.calc_commission("IF2612", "buy", 4000, 1, is_open=True)
    if_today = fut.calc_commission("IF2612", "sell", 4000, 1, is_close_today=True, is_open=False)
    check("IF 平今费率显著高于开仓", near(if_open, 4000 * 300 * 0.000023)
          and near(if_today, 4000 * 300 * 0.000345) and if_today > if_open * 10,
          f"open={if_open:.2f} close_today={if_today:.2f}")

    # ---------- 5. 做空权限 ----------
    r = acct.place_order("600519", "short", "market", 100, 1600.0, order_time=today,
                         warmup_ok=True)
    check("A股做空被拒绝", r["status"] == "rejected" and "不支持做空" in r["reason"],
          r["reason"])

    us = TradingAccount(1_000_000)
    r = us.place_order("AAPL", "short", "market", 10, 200.0, order_time=today,
                       warmup_ok=True)
    sp = us.short_positions.get("AAPL")
    fx = us.fx_rates["USD"]
    # 卖空属于「卖出」：SEC 费 0.00278% + TAF 0.0166 美分/股
    us_fee_usd = round(2000 * 0.0000278 + 10 * 0.000166, 2)
    check("美股做空成交（现金按汇率入账）",
          r["status"] == "filled" and sp is not None
          and near(us.cash, 1_000_000 + 2000 * fx - us_fee_usd * fx),
          f"cash={us.cash:.2f}")
    check("美股做空冻结 50% 保证金", near(us.margin_used, 2000 * fx * 0.5),
          f"margin={us.margin_used:.2f}")
    r = us.place_order("AAPL", "cover", "market", 10, 190.0, order_time=today)
    us_cost = (2000 - us_fee_usd) / 10  # 开仓卖出费用计入成本
    exp_cover_pnl = (us_cost - 190) * 10 * fx
    check("美股回补盈亏 = (200−10)−... 含开仓费用", near(r.get("realized_pnl", 0), exp_cover_pnl),
          f"{r.get('realized_pnl')} vs {exp_cover_pnl:.2f}")
    check("回补后空头持仓清空、保证金释放",
          "AAPL" not in us.short_positions and near(us.margin_used, 0),
          f"margin={us.margin_used:.2f}")

    # ---------- 6. 可转债 T+0 ----------
    cb = TradingAccount(1_000_000)
    b = cb.place_order("110043", "buy", "market", 10, 120.0, order_time=today,
                       warmup_ok=True)
    s = cb.place_order("110043", "sell", "market", 10, 121.0, order_time=today)
    check("可转债 T+0 当日买入后可当日卖出",
          b["status"] == "filled" and s["status"] == "filled",
          s.get("reason", ""))
    check("可转债买卖手续费 0.06（万0.5，免印花税）",
          near(b["commission"], 0.06) and near(s["commission"], 0.06),
          f"{b['commission']}/{s['commission']}")
    check("可转债当日平仓后无持仓", "110043" not in cb.positions)

    # ---------- 7. 期权买卖方 ----------
    opt = TradingAccount(1_000_000)
    rb = opt.place_order("10007666", "buy", "market", 1, 0.05, order_time=today,
                         strike=3.0, expiry=today + timedelta(days=30), warmup_ok=True)
    check("期权买方成交（权利金 500 + 手续费 5）",
          rb["status"] == "filled" and near(rb["commission"], 5.0)
          and near(opt.cash, 1_000_000 - 500 - 5),
          f"cash={opt.cash:.2f}")
    rs = opt.place_order("10007667", "sell", "market", 1, 0.05, order_time=today,
                         strike=3.0, underlying_price=3.0,
                         expiry=today + timedelta(days=30), warmup_ok=True)
    exp_margin = 500 + 3.0 * 10000 * 0.12
    check("期权卖方冻结保证金 = 权利金 + 标的市值×12%",
          rs["status"] == "filled" and near(rs.get("margin", 0), exp_margin),
          f"{rs.get('margin')} vs {exp_margin}")
    check("卖方保证金占用正确、权利金净增现金",
          near(opt.margin_used, exp_margin)
          and near(opt.cash, 1_000_000 - 505 + 500 - 5 - exp_margin),
          f"cash={opt.cash:.2f} margin_used={opt.margin_used:.2f}")

    # ---------- 8. 国债逆回购 ----------
    repo = TradingAccount(1_000_000)
    rr = repo.place_order("204001", "sell", "market", 100000, 2.5, order_time=today)
    rp = repo.positions.get("204001")
    exp_interest = round(100000 * 0.025 * 1 / 365, 2)
    check("逆回购下单成交（手续费 0.001% = 1 元）",
          rr["status"] == "filled" and near(rr["commission"], 1.0)
          and near(repo.cash, 1_000_000 - 100_000 - 1),
          f"cash={repo.cash:.2f}")
    check("逆回购记录到期日与应得利息",
          rp is not None and near(rp.repo_interest, exp_interest)
          and rp.mature_date is not None and rp.repo_days == 1,
          f"interest={exp_interest}")
    snap = repo.end_of_day(rp.mature_date, {"204001": 100.0})
    check("逆回购到期本息自动回款",
          "204001" not in repo.positions
          and near(repo.cash, 1_000_000 - 100_000 - 1 + 100_000 + exp_interest),
          f"cash={repo.cash:.2f} equity={snap['equity']:.2f}")
    r_early = TradingAccount(1_000_000)
    r_early.place_order("204001", "sell", "market", 100000, 2.5, order_time=today)
    r_early_res = r_early.place_order("204001", "sell", "market", 1000, 2.5, order_time=today)
    check("逆回购金额不满足 10 万整数倍被拒",
          r_early_res["status"] == "rejected" and "逆回购" in r_early_res["reason"],
          r_early_res["reason"])

    # ---------- 9. 基金申赎 ----------
    fund = TradingAccount(1_000_000)
    fb = fund.place_order("519066", "buy", "market", 10000, 1.5, order_time=today)
    check("基金申购费 = 15000×0.15% = 2.25",
          fb["status"] == "filled" and near(fb["commission"], 2.25),
          f"{fb.get('commission')}")
    f5 = fund.calc_commission("519066", "sell", 1.5, 10000, hold_days=5, is_open=False)
    f8 = fund.calc_commission("519066", "sell", 1.5, 10000, hold_days=8, is_open=False)
    f400 = fund.calc_commission("519066", "sell", 1.5, 10000, hold_days=400, is_open=False)
    check("赎回费按持有天数递减（5天1.5% / 8天0.75% / 400天0.25%）",
          near(f5, 225.0) and near(f8, 112.5) and near(f400, 37.5),
          f"{f5}/{f8}/{f400}")
    fs = fund.place_order("519066", "sell", "market", 10000, 1.5,
                          order_time=today + timedelta(days=8))
    check("基金持有 8 天后赎回成交", fs["status"] == "filled" and near(fs["commission"], 112.5),
          f"{fs.get('commission')}")

    # ---------- 10. 不可交易品种 ----------
    idx = TradingAccount(1_000_000)
    r = idx.place_order("sh000300", "buy", "market", 100, 4000.0, order_time=today)
    check("指数 sh000300 下单被拒（不可直接交易）",
          r["status"] == "rejected" and "指数" in r["reason"], r["reason"])

    # ---------- 11. 数据时效闸门 ----------
    live = TradingAccount(1_000_000, fetcher=StaleFetcher(40), run_mode="live")
    r = live.place_order("600000", "buy", "market", 100, 10.0, order_time=today,
                         warmup_ok=True)
    check("live 模式：无时效列 + refetch 到过期数据 → 拒单",
          r["status"] == "rejected" and "时效" in r["reason"], r["reason"])

    bt = TradingAccount(1_000_000, fetcher=StaleFetcher(40), run_mode="backtest")
    r = bt.place_order("600036", "buy", "market", 100, 10.0, order_time=today,
                       warmup_ok=True)
    check("backtest 模式默认豁免时效闸门", r["status"] == "filled", r.get("reason", ""))

    bt2 = TradingAccount(1_000_000, fetcher=StaleFetcher(40), run_mode="backtest")
    r = bt2.place_order("601318", "buy", "market", 100, 10.0, order_time=today,
                        for_trading=True, warmup_ok=True)
    check("回测内显式 for_trading=True 仍拦截过期数据",
          r["status"] == "rejected" and "时效" in r["reason"], r["reason"])

    fail_open = TradingAccount(1_000_000, fetcher=FailingFetcher(), run_mode="live")
    r = fail_open.place_order("601988", "buy", "market", 100, 10.0, order_time=today,
                              warmup_ok=True)
    check("refetch 失败：开仓拒单", r["status"] == "rejected" and "时效" in r["reason"],
          r["reason"])

    fail_close = TradingAccount(1_000_000, fetcher=FailingFetcher(), run_mode="live")
    fail_close.positions["601288"] = Position(
        symbol="601288", market="cn_stock", direction="long", volume=100,
        avg_cost=10.0, open_date=today, last_trade_date=today, kind="spot")
    r = fail_close.place_order("601288", "sell", "market", 100, 11.0, order_time=today)
    check("refetch 失败：平仓放行（否则止损单下不出去）", r["status"] == "filled",
          r.get("reason", ""))

    counter = FreshFetcher()
    ttl = TradingAccount(1_000_000, fetcher=counter, run_mode="live")
    ttl.place_order("600030", "buy", "market", 100, 10.0, order_time=today,
                    warmup_ok=True)
    ttl.place_order("600030", "buy", "market", 100, 10.0, order_time=today,
                    warmup_ok=True)
    check("同一批次 refetch 结果在 TTL 内复用（2 单只取 1 次）", counter.calls == 1,
          f"calls={counter.calls}")

    # ---------- 12. 指标预热闸门联动（第 3 步 B5） ----------
    wg = TradingAccount(1_000_000)
    r_warm = wg.place_order("600519", "buy", "market", 100, 1600.0, order_time=today,
                            warmup_ok=False)
    check("预热期（warmup_ok=False）开仓拒单",
          r_warm["status"] == "rejected" and "预热" in r_warm["reason"], r_warm["reason"])
    r_bare = wg.place_order("600519", "buy", "market", 100, 1600.0, order_time=today)
    check("未携带 warmup_ok 的裸开仓单按最保守处置拒单",
          r_bare["status"] == "rejected" and "warmup_ok" in r_bare["reason"], r_bare["reason"])
    wg.place_order("600519", "buy", "market", 100, 1600.0, order_time=today,
                   warmup_ok=True)
    r_close = wg.place_order("600519", "sell", "market", 100, 1600.0,
                             order_time=today + timedelta(days=1), warmup_ok=False)
    check("预热期平仓/减仓不受限（开严平宽）", r_close["status"] == "filled",
          r_close.get("reason", ""))

    # ---------- 13. 权益口径 ----------
    eq = TradingAccount(1_000_000)
    eq.place_order("600519", "buy", "market", 100, 1600.0, order_time=today,
                   warmup_ok=True)
    equity = eq.calc_equity({"600519": 1600.0})
    check("现货权益 = 现金 + 持仓市值", near(equity, eq.cash + 160000),
          f"{equity:.2f} vs {eq.cash + 160000:.2f}")

    eq2 = TradingAccount(1_000_000)
    eq2.place_order("AAPL", "short", "market", 10, 200.0, order_time=today,
                    warmup_ok=True)
    equity2 = eq2.calc_equity({"AAPL": 200.0})
    check("卖空权益 = 现金 − 空头负债（按现价）",
          near(equity2, 1_000_000 - us_fee_usd * fx), f"{equity2:.2f}")

    # ---------- 13. 持仓不足卖出 ----------
    r = acct.place_order("600519", "sell", "market", 100, 1600.0, order_time=today)
    check("无持仓卖出被拒", r["status"] == "rejected" and "持仓" in r["reason"], r["reason"])

    # ---------- 汇总 ----------
    print("\n" + "=" * 60)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：")
        for name in FAIL:
            print(f"  - {name}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
