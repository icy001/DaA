"""多市场量化交易系统入口

当前仅提供欢迎信息与支持市场列表；后续步骤会在这里接入数据层、回测、模拟盘与实盘入口。
"""
from __future__ import annotations

import sys

import config
from core.utils import MARKET_NAMES, setup_logger

VERSION = "v3.3"
VERSION_DESC = "全市场+合格投资者层+行情K线缠论+因子研究+实盘接入+凭证安全+数据长期可用"


def main() -> int:
    logger = setup_logger("main")
    print("=" * 68)
    print("        多市场量化交易系统  Multi-Market Quant Trading System")
    print(f"        版本：{VERSION} · {VERSION_DESC}")
    print("=" * 68)
    print(f"工作目录：{config.BASE_DIR}")
    print(f"运行模式：{config.RUN_MODE}    实盘开关：{'开启' if config.LIVE_TRADING_ENABLED else '关闭'}")
    print("\n支持的市场类型：")
    for index, (key, name) in enumerate(MARKET_NAMES.items(), start=1):
        print(f"  {index:2d}. {key:<16} {name}")
    print(f"\n共 {len(MARKET_NAMES)} 类品种（零售层 13 类 + 合格投资者层 5 类）")
    print("提示：先运行 python check_progress.py 查看搭建进度，再按 README 继续。")
    logger.info("系统启动完成，版本 %s", VERSION)
    return 0


if __name__ == "__main__":
    sys.exit(main())
