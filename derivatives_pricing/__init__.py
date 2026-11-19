# -*- coding: utf-8 -*-
"""场外衍生品定价模拟包（derivatives_pricing/）——⚠️ 个人禁止实盘

⚠️⚠️⚠️ 警告 ⚠️⚠️⚠️
本模块仅用于衍生品定价理论学习和学术研究。
中国大陆个人投资者禁止直接参与场外期权/收益互换交易。
市面上所谓"通道""过桥"参与场外衍生品均属违规灰色业务，风险自担。
本模块不提供任何实盘下单功能。

硬约束（第 10 步 10.4）：
* 本包**不导出任何下单/下单网关函数**，``ORDER_CHANNELS`` 恒为空；
* ``assert_no_order_channel()`` 供外部审计：一旦有人往本包塞交易通道即报错；
* 所有输出仅为理论价格、希腊字母与模拟损益分布。
"""
from __future__ import annotations

LIVE_TRADING_FORBIDDEN = True
ORDER_CHANNELS: tuple = ()

_RED_WARNING = """
⚠️⚠️⚠️ 警告 ⚠️⚠️⚠️
本模块仅用于衍生品定价理论学习和学术研究。
中国大陆个人投资者禁止直接参与场外期权/收益互换交易。
市面上所谓"通道""过桥"参与场外衍生品均属违规灰色业务，风险自担。
本模块不提供任何实盘下单功能。
"""


def print_red_warning() -> str:
    """打印显眼警告（模块导入时自动调用一次）。"""
    print(_RED_WARNING)
    return _RED_WARNING


def assert_no_order_channel() -> None:
    """审计断言：本包不得存在任何实盘下单通道。"""
    if ORDER_CHANNELS:
        raise RuntimeError(f"衍生品模块禁止绑定任何交易通道：{ORDER_CHANNELS}")
    if not LIVE_TRADING_FORBIDDEN:
        raise RuntimeError("衍生品模块必须保持「个人禁止实盘」红线")


print_red_warning()
