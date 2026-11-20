# -*- coding: utf-8 -*-
"""v3.52 回测验收修复回归（第一轮四缺陷）：

C-1 胜率字段名错位（_win_rate 读 pnl）
C-2 CLI 回测留痕三件自动落盘
C-3 信号出口逐条结构化日志（[SIGNAL]）
B-1 熔断死锁：3 日企稳自动恢复 + 状态落盘 + 人工复位协议
"""
from __future__ import annotations

import json
import logging
from datetime import date as _date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import config
from core.account import TradingAccount
from core.risk import RiskManager
from core.runner import _win_rate


# ==================== C-1 胜率 ====================

def test_win_rate_reads_pnl_field():
    """C-1：_win_rate 以落盘字段 pnl 为准（account 权威写端），realized_pnl 兼容。"""
    trades = [
        {"status": "filled", "pnl": 100.0},
        {"status": "filled", "pnl": -50.0},
        {"status": "filled", "pnl": 20.0},
        {"status": "filled", "pnl": 5.0},
        {"status": "rejected", "pnl": 999.0},   # 拒单不计
    ]
    assert _win_rate(trades) == pytest.approx(3 / 4)


def test_win_rate_supports_legacy_alias():
    """realized_pnl 保留为兼容别名（历史数据可读）。"""
    trades = [{"status": "filled", "realized_pnl": 10.0},
              {"status": "filled", "realized_pnl": -1.0}]
    assert _win_rate(trades) == pytest.approx(0.5)


def test_win_rate_empty_returns_zero():
    assert _win_rate([]) == 0.0
    assert _win_rate([{"status": "filled"}]) == 0.0   # 无盈亏字段（开仓单）不崩


def test_win_rate_account_trades_shape():
    """C-1 二次根因回归：account.trades（_trade_record）无 status 字段且字段名 pnl，
    不得被 status==filled 过滤清空（曾致任何回测胜率恒 0）。"""
    account_trades = [
        {"order_id": "o1", "symbol": "600519", "direction": "sell", "action": "close",
         "pnl": 100.0},                                  # 无 status 键
        {"order_id": "o2", "symbol": "600519", "direction": "sell", "action": "close",
         "pnl": -30.0},
        {"order_id": "o3", "symbol": "000001", "direction": "sell", "action": "close",
         "pnl": 20.0},
    ]
    assert _win_rate(account_trades) == pytest.approx(2 / 3)


def test_win_rate_denominator_is_closed_trades_only():
    """v3.53 口径归一（计数口径冻结位）：胜率 = 已实现结果中盈利的比例，
    分母 = 平仓笔（action=="close"，近似交易对——买卖笔数近似 1:1），
    开仓笔没有结果、不得进分母。account.trades 的开仓笔带 pnl=0.0 字段，
    旧实现按「有 pnl 字段」计分母曾把它们当「未盈利」计入（488 分母 vs
    242 明细分母 → 16.60% vs 33.47% 的同名双口径）。"""
    account_trades = [
        # 3 笔平仓：2 盈 1 亏 → 胜率 2/3
        {"direction": "sell", "action": "close", "pnl": 100.0},
        {"direction": "sell", "action": "close", "pnl": -30.0},
        {"direction": "cover", "action": "close", "pnl": 20.0},
        # 5 笔开仓：pnl 恒 0.0（_trade_record 权威写端形态），不计分母
        {"direction": "buy", "action": "open", "pnl": 0.0},
        {"direction": "buy", "action": "open", "pnl": 0.0},
        {"direction": "buy", "action": "open", "pnl": 0.0},
        {"direction": "short", "action": "open", "pnl": 0.0},
        {"direction": "buy", "action": "open", "pnl": 0.0},
    ]
    assert _win_rate(account_trades) == pytest.approx(2 / 3)


def test_win_rate_metrics_matches_detail_basis():
    """v3.53 口径归一：metrics.win_rate 与逐笔明细必须是同一个数——
    同一份 account.trades 下，_win_rate == 明细口径（close 笔中 pnl>0 占比），
    且与「全部成交作分母」的旧错口径不相等（防回归回 16.60%）。"""
    trades = [
        {"direction": "buy", "action": "open", "pnl": 0.0},
        {"direction": "sell", "action": "close", "pnl": 100.0},
        {"direction": "buy", "action": "open", "pnl": 0.0},
        {"direction": "sell", "action": "close", "pnl": -30.0},
        {"direction": "buy", "action": "open", "pnl": 0.0},
        {"direction": "sell", "action": "close", "pnl": 20.0},
    ]
    got = _win_rate(trades)
    # 明细口径：242 平仓笔中 81 正的同构算法 → close 笔分母
    closes = [t for t in trades if t.get("action") == "close"]
    detail = sum(1 for t in closes if t["pnl"] > 0) / len(closes)
    assert got == pytest.approx(detail) == pytest.approx(2 / 3)
    # 旧错口径（全成交作分母 2/6=1/3）必须不再出现
    assert got != pytest.approx(2 / 6)


# ==================== B-1 熔断自动恢复 ====================

# v3.53 收尾①（评审裁定）：新增特性测试必须锚定具体版本号——>=语义仅限
# 兼容性断言；特性锚定后，未来版本删键/改口径时此处会报错提醒同步更新，
# 防止冻结静默失效。
V3_53 = "v3.53"


def test_v53_feature_keys_anchored_to_spec_version():
    """13.0.24 特性冻结位：熔断恢复参数必须仍在 config.RISK 治理面内，
    且锚定 >=v3.53——版本滚动删键/挪块时本测试必须失败并提示重审。"""
    import config
    assert config.SPEC_VERSION >= V3_53
    acc = config.RISK["account"]
    assert acc["halt_recover_stabilize_days"] == 3
    assert acc["halt_recover_enabled"] is True
    assert "13.0.24" in config.SPEC_VERSION_CHECK["must_contain_markers"]


def test_intraday_bars_do_not_reset_day_start_equity():
    """v3.53 扩围修复回归：分钟线下 date 是 timestamp，换日判定必须按日期
    部分归一——同日多根 bar 不得重置日初权益（日内亏损上限曾因此失效）。"""
    import pandas as pd
    rm = _make_risk(daily_loss_pct_stop=0.05)
    d = pd.Timestamp("2026-01-05")
    rm.on_bar(d + pd.Timedelta(minutes=210), {"X": 10.0})   # 10:30 首根：日初=100
    assert rm._day_start_equity == pytest.approx(100.0)
    rm.on_bar(d + pd.Timedelta(minutes=270), {"X": 10.0})   # 11:30 同日第二根
    assert rm._day == _date(2026, 1, 5)
    assert rm._day_start_equity == pytest.approx(100.0)     # 不得被重置
    # 次日才重置日初
    rm.on_bar(pd.Timestamp("2026-01-06 10:30"), {"X": 10.0})
    assert rm._day == _date(2026, 1, 6)
    assert rm._day_start_equity == pytest.approx(100.0)     # 新一日重新计


class _StubAccount:
    """最小账户桩：calc_equity 返回注入值，持仓为空（无黑天鹅/止损动作）。"""

    def __init__(self):
        self.equity = 100.0

    def calc_equity(self, prices=None):
        return float(self.equity)

    def get_position(self, *a, **k):
        return None

    @property
    def positions(self):
        return {}

    @property
    def short_positions(self):
        return {}


def _make_risk(**params):
    state_file = params.pop("state_file", None)
    return RiskManager(_StubAccount(), params=params,
                       logger=logging.getLogger("test_halt"),
                       state_file=state_file)


def _run_day(rm, date, equity):
    rm.account.equity = equity
    rm.on_bar(date, {"X": 10.0})


def test_halt_triggers_at_drawdown_then_recovers_after_stabilize():
    """熔断触发不变；连续 3 日权益未创新低自动解除，且回撤基准重置为解除日权益。"""
    rm = _make_risk(halt_recover_stabilize_days=3)
    _run_day(rm, "2022-02-23", 100.0)          # 峰值 100
    _run_day(rm, "2022-02-24", 89.0)           # 回撤 -11% → 熔断
    assert rm.halted is True
    assert rm.halt_since == _date(2022, 2, 24)   # v3.53：分钟级换日按日期部分归一
    # 观察期：首日仅记基准，此后连续 3 日未创新低
    _run_day(rm, "2022-02-25", 89.0)           # 首观察日，stabilize=0
    _run_day(rm, "2022-02-28", 89.0)           # 企稳 1
    _run_day(rm, "2022-03-01", 89.5)           # 企稳 2
    assert rm.halted is True
    _run_day(rm, "2022-03-02", 90.0)           # 企稳 3 → 解除
    assert rm.halted is False
    assert rm._peak_equity == pytest.approx(90.0)   # 解除日权益为新基准（防再熔死锁）
    assert rm.check_open("X", 1, 10.0) is None      # 恢复开仓（小单避开单票 20% 上限）


def test_halt_recovery_resets_on_new_low():
    """观察期内创新低 → 企稳计数归零，恢复重新起算。"""
    rm = _make_risk(halt_recover_stabilize_days=3)
    _run_day(rm, "d1", 100.0)
    _run_day(rm, "d2", 89.0)                    # 熔断
    _run_day(rm, "d3", 89.0)                    # 观察 0
    _run_day(rm, "d4", 89.0)                    # 企稳 1
    _run_day(rm, "d5", 88.0)                    # 创新低 → 归零
    assert rm.halted is True and rm._stabilize_days == 0
    _run_day(rm, "d6", 88.0)
    _run_day(rm, "d7", 88.0)
    _run_day(rm, "d8", 88.5)
    assert rm.halted is False                   # 重新起算满 3 日后解除


def test_new_day_does_not_silently_reset_halt():
    """B-1 死锁根因回归：换日禁止无条件解除熔断（旧逻辑「每日复位→每日重熔」）。"""
    rm = _make_risk()
    _run_day(rm, "d1", 100.0)
    _run_day(rm, "d2", 89.0)
    assert rm.halted is True
    rm.new_day("d3", equity=89.0)
    assert rm.halted is True                    # 关键回归点：不再被 new_day 静默复位
    assert rm._day_start_equity == pytest.approx(89.0)  # 日内基准照常重置


def test_halt_state_snapshot_fields():
    rm = _make_risk()
    _run_day(rm, "d1", 100.0)
    _run_day(rm, "d2", 89.0)
    st = rm.halt_state()
    assert st["halted"] is True
    assert st["halt_since"] == "d2"
    assert st["stabilize_days"] == 0
    assert st["recover_stabilize_days"] == 3
    assert st["recover_enabled"] is True
    assert "熔断线" in st["halt_reason"]


def test_halt_state_file_written_and_manual_sync():
    """实盘状态文件协议：halt 落盘；文件被 CLI 删除后换日 sync → 内存同步解除。"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        state_file = str(Path(td) / "RISK_HALT.json")
        rm = _make_risk(state_file=state_file)
        _run_day(rm, "d1", 100.0)
        _run_day(rm, "d2", 89.0)
        p = Path(state_file)
        assert p.exists() and json.loads(p.read_text(encoding="utf-8"))["halted"] is True
        # CLI risk-reset 删除标志文件 → 运行中进程换日同步解除（人工复位生效点）
        p.unlink()
        rm.new_day("d3", equity=89.0)
        assert rm.halted is False
        assert rm.halt_since is None


# ==================== 人工复位 CLI（二次确认） ====================

def test_risk_reset_cli_requires_confirm(tmp_path, monkeypatch):
    from cli_commands.retail import cmd_risk_reset
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    halt_dir = tmp_path / "live_trading"
    halt_dir.mkdir()
    (halt_dir / "RISK_HALT.json").write_text(
        json.dumps({"halted": True, "halt_since": "d2", "halt_reason": "回撤熔断"},
                   ensure_ascii=False), encoding="utf-8")
    # 无二次确认 → 拒绝，文件保留
    rc = cmd_risk_reset(SimpleNamespace(confirm=None, operator="t"))
    assert rc == 2 and (halt_dir / "RISK_HALT.json").exists()
    # --confirm yes → 删除标志文件 + 写审计行
    rc = cmd_risk_reset(SimpleNamespace(confirm="yes", operator="tester"))
    assert rc == 0 and not (halt_dir / "RISK_HALT.json").exists()
    audit = (halt_dir / "RISK_HALT_RESETS.log").read_text(encoding="utf-8")
    assert "manual_reset" in audit and "tester" in audit
    # 幂等：再复位一次 → 「未熔断」
    assert cmd_risk_reset(SimpleNamespace(confirm="yes", operator="t")) == 0


# ==================== C-2 CLI 回测落盘 ====================

def test_backtest_artifacts_dumped(tmp_path, monkeypatch):
    """cmd_backtest 留痕三件：trades.csv / equity.csv / config.json 自动生成。"""
    from cli_commands.retail import _dump_backtest_artifacts
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    args = SimpleNamespace(strategy="double_ma_cross", adjust="qfq", initial_cash=1000000.0)
    nav = pd.Series([1000000.0, 1010000.0], index=pd.to_datetime(["2020-01-02", "2020-01-03"]),
                    name="equity")
    result = {
        "run_mode": "backtest",
        "params": {"fast": 5, "slow": 20},
        "metrics": {"total_return": 0.01, "win_rate": 0.5, "trade_count": 2},
        "nav": nav,
        "trades": [{"symbol": "600519", "direction": "buy", "status": "filled", "pnl": 0.0},
                   {"symbol": "600519", "direction": "sell", "status": "filled", "pnl": 100.0}],
        "rejected": [],
        "halt_state": {"halted": False, "halt_reason": "", "halt_since": None,
                       "stabilize_days": 0, "recover_stabilize_days": 3,
                       "recover_enabled": True},
    }
    _dump_backtest_artifacts(args, result, ["600519"], "2020-01-01", "2026-11-18")
    files = sorted(p.name for p in (tmp_path / "backtest_results").iterdir())
    assert len(files) == 3
    assert any(f.endswith("_trades.csv") for f in files)
    assert any(f.endswith("_equity.csv") for f in files)
    cfg_file = next(f for f in files if f.endswith("_config.json"))
    cfg = json.loads((tmp_path / "backtest_results" / cfg_file).read_text(encoding="utf-8"))
    assert cfg["spec_version"] == config.SPEC_VERSION
    assert cfg["strategy"] == "double_ma_cross"
    assert cfg["halt_state"]["halted"] is False
    assert cfg["metrics"]["win_rate"] == 0.5


# ==================== C-3 信号出口日志 ====================

class _MiniStrategy:
    """绕过 BaseStrategy 重构造：只验证 _order 出口日志行为不合算——
    改为直接驱动真实 BaseStrategy 的最小子类（见 test_signal_log_*）。"""


def _make_strategy(tmp_path, cash=100000.0):
    from core.strategy import BaseStrategy

    class _S(BaseStrategy):
        def on_bar(self, date, bars):
            pass

    acc = TradingAccount(cash, run_mode="backtest")
    return _S(account=acc, data_fetcher=None, params={}, logger=logging.getLogger("test_sig"),
              run_mode="backtest", history_provider=lambda symbol, n: pd.DataFrame())


def test_signal_log_filled_path(tmp_path, caplog):
    """成交路径：每笔信号恰好一条 [SIGNAL] 日志，status=filled。"""
    st = _make_strategy(tmp_path)
    st._warmup_ok["600519"] = True
    st._prices["600519"] = 10.0
    with caplog.at_level(logging.INFO, logger="test_sig"):
        rec = st.buy("600519", 100, price=10.0)
    assert rec["status"] == "filled"
    sigs = [r for r in caplog.records if "[SIGNAL]" in r.getMessage()]
    assert len(sigs) == 1
    msg = sigs[0].getMessage()
    assert "status=filled" in msg and "600519" in msg and "direction=buy" in msg


def test_signal_log_rejected_path_records_reason(tmp_path, caplog):
    """拒单路径：[SIGNAL] 日志带命中闸门（code）与拒单原因。"""
    st = _make_strategy(tmp_path)
    st._prices["600519"] = 10.0
    with caplog.at_level(logging.INFO, logger="test_sig"):
        rec = st.buy("600519", 100, price=10.0)   # 未设 warmup_ok → 预热闸门拒
    assert rec["status"] == "rejected"
    sigs = [r for r in caplog.records if "[SIGNAL]" in r.getMessage()]
    assert len(sigs) == 1
    msg = sigs[0].getMessage()
    assert "status=rejected" in msg and "warmup" in msg and "reason=" in msg


def test_signal_log_risk_block_path(tmp_path, caplog):
    """熔断拒单路径：[SIGNAL] 记录 risk_block 与熔断原因（B-1+C-3 联动）。"""
    st = _make_strategy(tmp_path)
    st._warmup_ok["600519"] = True
    st._prices["600519"] = 10.0
    st.risk_manager.halted = True
    st.risk_manager.halt_reason = "权益回撤 -10.30% 触及熔断线 10.00%，停止开仓"
    with caplog.at_level(logging.INFO, logger="test_sig"):
        rec = st.buy("600519", 100, price=10.0)
    assert rec["status"] == "rejected" and rec["stage"] == "risk"
    sigs = [r for r in caplog.records if "[SIGNAL]" in r.getMessage()]
    assert len(sigs) == 1 and "risk_block" in sigs[0].getMessage()
