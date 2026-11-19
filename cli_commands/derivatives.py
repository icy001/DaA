# -*- coding: utf-8 -*-
"""场外衍生品定价模拟（个人禁止实盘红字警示，无下单通道）。"""
from __future__ import annotations

from core import cli_gate
from cli_commands._common import *  # noqa: F401,F403

GROUP = "合格投资者层"
DEF = cli_gate.cli_default

def cmd_derivatives_sim(args) -> int:
    """场外衍生品定价/模拟（仅理论模拟，禁止实盘）。"""
    import derivatives_pricing as dp

    product = str(args.product)
    if product == "snowball":
        out = dp.snowball_pricing(
            float(args.s0), ko_barrier=float(args.ko), ki_barrier=float(args.ki),
            coupon=float(args.coupon),
            ko_observe_dates=list(range(1, int(args.months) + 1)),
            ki_observe_dates=[], r=float(args.rate), sigma=float(args.sigma),
            notional=float(args.notional), tenor_months=int(args.months))
        print(f"雪球结构模拟（期初 {args.s0}，敲出 {args.ko}，敲入 {args.ki}）：")
        for key, value in out.items():
            if isinstance(value, float):
                print(f"  {key:<24}{value:>14.4f}")
            else:
                print(f"  {key:<24}{value}")
    elif product == "trs":
        out = dp.trs_pnl_simulation(
            underlying_return=float(args.underlying_return),
            notional=float(args.notional), margin_rate=float(args.margin_rate),
            financing_rate=float(args.financing_rate),
            term_days=int(args.days), maintenance_margin=float(args.maintenance))
        print(f"TRS 收益互换模拟（名义 {args.notional}，期限 {args.days} 天）：")
        for key, value in out.items():
            print(f"  {key:<24}{value:>14.4f}")
        print(f"  强平线（标的累计收益低于）{out['liquidation_return']:+.2%}")
    elif product == "option":
        out = dp.black_scholes(float(args.spot), float(args.strike), float(args.t),
                               r=float(args.rate), sigma=float(args.sigma),
                               option_type=str(args.option_type))
        print(f"BS {args.option_type} 期权（S={args.spot} K={args.strike} "
              f"T={args.t} σ={args.sigma}）：")
        for key, value in out.items():
            print(f"  {key:<24}{value:>14.4f}")
    else:
        print(f"未知衍生品 {product!r}（snowball / trs / option）")
        return 2
    # 红线：个人禁止实盘场外衍生品；定价模块无任何下单通道
    print(dp.print_red_warning())
    dp.assert_no_order_channel()
    return 0


def add_subparser(sp) -> None:
    """注册衍生品定价模拟子命令（个人禁止实盘，无下单通道）。"""
    p = sp.add_parser("derivatives-sim", help=f"[{GROUP}] 场外衍生品定价模拟（禁止实盘）")
    p.add_argument("--product", default="option",
                   choices=["snowball", "trs", "option"])
    p.add_argument("--s0", type=float, default=100.0, help="雪球期初价")
    p.add_argument("--ko", type=float, default=1.03, help="雪球敲出比例")
    p.add_argument("--ki", type=float, default=0.75, help="雪球敲入比例")
    p.add_argument("--coupon", type=float, default=0.12, help="雪球年化票息")
    p.add_argument("--months", type=int, default=24, help="雪球期限（月）")
    p.add_argument("--rate", type=float, default=0.03, help="无风险利率")
    p.add_argument("--sigma", type=float, default=0.25, help="波动率")
    p.add_argument("--notional", type=float, default=1_000_000.0, help="名义本金")
    p.add_argument("--underlying-return", dest="underlying_return", type=float,
                   default=0.10, help="TRS 标的区间累计收益")
    p.add_argument("--margin-rate", dest="margin_rate", type=float, default=0.20,
                   help="TRS 保证金比例")
    p.add_argument("--financing-rate", dest="financing_rate", type=float,
                   default=0.05, help="TRS 融资年化利率")
    p.add_argument("--days", type=int, default=365, help="TRS 期限（天）")
    p.add_argument("--maintenance", type=float, default=0.25,
                   help="TRS 维持保证金比例")
    p.add_argument("--spot", type=float, default=100.0, help="期权标的价格")
    p.add_argument("--strike", type=float, default=100.0, help="行权价")
    p.add_argument("--t", type=float, default=0.5, help="剩余年限")
    p.add_argument("--option-type", dest="option_type", default="call",
                   choices=["call", "put"])
    p.set_defaults(handler=cmd_derivatives_sim)


def handler(args) -> int:
    """derivatives 模块统一分发。"""
    return int((getattr(args, "handler", None) or cmd_derivatives_sim)(args))
