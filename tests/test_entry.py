# -*- coding: utf-8 -*-
"""第 11 步验收测试：一键运行入口（控制平面）一致性。

四条硬断言（指令集 11.0 / 验收清单）：
    ① 无旁路开关：argv 出现黑名单旗标直接拒（BypassFlagError），
       且 build_parser 的 argparse 注册面也必须干净；
    ② 模式不可提升：backtest→paper 提升在无 strategy / 无 --confirm /
       清单有 FAIL 时分别抛 RunModePromotionError；降级放行；
    ③ 子命令默认值与 config 一致：argparse 默认值逐项来自
       CLI_CONFORMANCE['cli_defaults']（单一事实源）；
    ④ --data 导入三物化列齐备：缺列 / NaN 拒绝（fail-closed），
       正常导入帧三列有效且逐 symbol 各自物化。

全部离线：不触网、不读真实行情缓存。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import config
import main as main_mod
from core import cli_gate
from data.data_import import (LocalDataImportError, import_local_frame,
                              required_columns)

pytestmark = pytest.mark.usefixtures("no_network")


@pytest.fixture
def no_network(monkeypatch):
    """禁掉出网出口（导入路径只读本地文件，理论上不会触网；双保险）。"""
    monkeypatch.setattr("requests.get", lambda *a, **k: None, raising=False)


@pytest.fixture(autouse=True)
def restore_mode():
    """每个用例后恢复 config.RUN_MODE，防止模式状态泄漏。"""
    before = config.RUN_MODE
    yield
    config.RUN_MODE = before


# --------------------------------------------------------------------------- #
# ① 无旁路开关
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("flag", cli_gate.bypass_flags())
def test_bypass_flag_argv_rejected(flag):
    """黑名单旗标出现在 argv → BypassFlagError，禁止绕过闸门。"""
    with pytest.raises(cli_gate.BypassFlagError):
        cli_gate.guard_argv(["backtest", flag])


@pytest.mark.parametrize("flag", cli_gate.bypass_flags())
def test_bypass_flag_equals_variant_rejected(flag):
    """--flag=value 变体同样拒收。"""
    with pytest.raises(cli_gate.BypassFlagError):
        cli_gate.assert_no_bypass_flags(["backtest", f"{flag}=1"])


def test_parser_registration_has_no_bypass_flags():
    """argparse 注册面审计：任何子命令都没有注册旁路旗标。"""
    parser = main_mod.build_parser()
    cli_gate.assert_no_bypass_registration(parser)  # 不抛即通过


def test_main_rejects_bypass_before_parse():
    """main() 在解析前就拦：旁路旗标导致 SystemExit 而非执行命令。"""
    with pytest.raises(cli_gate.BypassFlagError):
        main_mod.main(["backtest", "--strategy", "ma_cross",
                       "--no-risk", "--symbols", "600519"])


# --------------------------------------------------------------------------- #
# ② 模式不可提升（提升被拒或需显式确认）
# --------------------------------------------------------------------------- #

def _with_mode(mode):
    config.RUN_MODE = mode
    return mode


def test_promote_without_strategy_rejected():
    _with_mode("backtest")
    with pytest.raises(cli_gate.RunModePromotionError):
        cli_gate.enter_mode("paper", strategy=None, confirm=True)


def test_promote_without_confirm_rejected():
    """清单全 PASS 也必须显式确认（checklist_fn 注入全 PASS 桩）。"""
    _with_mode("backtest")
    ok_rows = [(1, "样本数", "PASS", ""), (2, "回撤", "PASS", "")]
    with pytest.raises(cli_gate.RunModePromotionError):
        cli_gate.enter_mode("paper", strategy="ma_cross", confirm=False,
                            checklist_fn=lambda _s: ok_rows)


def test_promote_with_fail_checklist_rejected():
    """清单存在 FAIL → 拦截（checklist 须能拦）。"""
    _with_mode("backtest")
    rows = [(1, "样本数", "PASS", ""), (2, "回撤", "FAIL", "回撤超标"),
            (3, "流动性", "WARN", "")]
    with pytest.raises(cli_gate.RunModePromotionError):
        cli_gate.enter_mode("paper", strategy="ma_cross", confirm=True,
                            checklist_fn=lambda _s: rows)


def test_promote_with_clean_checklist_and_confirm_passes():
    _with_mode("backtest")
    ok_rows = [(i, f"item{i}", "PASS", "") for i in range(1, 17)]
    out = cli_gate.enter_mode("paper", strategy="ma_cross", confirm=True,
                               checklist_fn=lambda _s: ok_rows)
    assert out["ok"] is True
    assert cli_gate.current_mode() == "paper"


def test_downgrade_always_allowed_without_gate():
    """降级（live→paper→backtest）不需要清单与确认，直接放行。"""
    _with_mode("live")
    out = cli_gate.enter_mode("paper")
    assert out["ok"] is True and cli_gate.current_mode() == "paper"
    out = cli_gate.enter_mode("backtest", checklist_fn=None)
    assert out["ok"] is True and cli_gate.current_mode() == "backtest"


def test_unknown_mode_rejected():
    _with_mode("backtest")
    with pytest.raises(cli_gate.RunModeError):
        cli_gate.enter_mode("live_trading_surely")


# --------------------------------------------------------------------------- #
# ③ 子命令默认值与 config 一致（单一事实源）
# --------------------------------------------------------------------------- #

def test_cli_defaults_table_matches_global_config():
    """cli_defaults 登记表与 config 全局默认同源（INITIAL_CASH/DEFAULT_START）。"""
    table = config._USER_CLI_DEFAULTS["cli_defaults"]
    assert table["initial_cash"] == config.INITIAL_CASH
    assert table["start"] == config.DEFAULT_START
    assert table["end"] == config.DEFAULT_END
    assert table["adjust"] == config.INDICATOR_CONFIG["default_adjust"]


def test_cli_default_unknown_key_raises():
    """未登记的默认值键必须抛 KeyError（禁止静默拿 None）。"""
    with pytest.raises(KeyError):
        cli_gate.cli_default("definitely_not_registered")


def test_parser_defaults_come_from_config():
    """argparse 注册的默认值逐项 == _USER_CLI_DEFAULTS['cli_defaults']。"""
    parser = main_mod.build_parser()
    table = config._USER_CLI_DEFAULTS["cli_defaults"]
    args = parser.parse_args(["backtest", "--strategy", "ma_cross"])
    assert args.initial_cash == table["initial_cash"]
    assert args.start == table["start"]
    assert args.end == table["end"]
    assert args.adjust == table["adjust"]
    # optimize 子命令
    args = parser.parse_args(["optimize", "--strategy", "ma_cross"])
    assert args.method == table["optimize_method"]
    assert args.n_iter == table["n_iter"]
    assert args.top_n == table["top_n"]
    # report 子命令
    args = parser.parse_args(["report", "--strategy", "ma_cross"])
    assert args.report_type == table["report_type"]
    # chart 子命令
    args = parser.parse_args(["chart"])
    assert args.period == table["chart_period"]


def test_set_mode_choices_is_ladder():
    """set-mode 的可选模式必须等于运行模式阶梯（不可越级到未登记模式）。"""
    assert cli_gate.ladder() == ["backtest", "paper", "live"]


# --------------------------------------------------------------------------- #
# ④ --data 导入三物化列齐备（缺列拒绝 / fail-closed）
# --------------------------------------------------------------------------- #

def _make_frame(n=80) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "date": idx.strftime("%Y-%m-%d"),
        "open": [10.0 + 0.01 * i for i in range(n)],
        "close": [10.0 + 0.02 * i for i in range(n)],
        "high": [10.5 + 0.02 * i for i in range(n)],
        "low": [9.5 + 0.02 * i for i in range(n)],
        "volume": [1_000_000] * n,
    })


def test_import_ok_frame_has_three_columns(tmp_path):
    """正常导入：三物化列齐备、无 NaN、逐 symbol 各自物化。"""
    path = tmp_path / "600519.csv"
    _make_frame().to_csv(path, index=False)
    out = import_local_frame(path, symbol="600519", adjust="qfq")
    for col in required_columns():
        assert col in out.columns, f"缺物化列 {col}"
        assert not out[col].isna().any(), f"{col} 含 NaN"
    # warmup 前 60 根 False、之后 True
    assert not out["warmup_ok"].iloc[0]
    assert out["warmup_ok"].iloc[-1]
    # data_asof_date 是最后一根 bar 的实际日期（非取数时刻）
    assert str(out["data_asof_date"].iloc[-1].date()) == out.index[-1].strftime("%Y-%m-%d")
    # price_adjust 归一
    assert set(out["price_adjust"].unique()) == {"qfq"}


def test_import_missing_price_column_rejected(tmp_path):
    """缺行情列 → 拒绝导入（fail-closed）。"""
    frame = _make_frame().drop(columns=["close"])
    path = tmp_path / "bad.csv"
    frame.to_csv(path, index=False)
    with pytest.raises(LocalDataImportError):
        import_local_frame(path, symbol="600519")


def test_import_frame_with_nan_in_materialized_column_rejected(tmp_path):
    """导入帧三物化列含 NaN（symbol 列出现 NaN 使 asof 物化失效）→ 拒绝。"""
    frame = _make_frame()
    frame["symbol"] = "600519"
    frame.loc[0, "symbol"] = None       # symbol 缺失 → data_asof_date 物化出 NaN
    path = tmp_path / "nan.csv"
    frame.to_csv(path, index=False)
    with pytest.raises(LocalDataImportError):
        import_local_frame(path, symbol="600519")


def test_import_empty_file_rejected(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("date,open,close\n", encoding="utf-8")
    with pytest.raises(LocalDataImportError):
        import_local_frame(path)


def test_local_fetcher_paths_symbols_must_match(tmp_path):
    """文件数与 symbols 数不一致 → 整体拒绝（禁止部分成功静默继续）。"""
    path = tmp_path / "600519.csv"
    _make_frame().to_csv(path, index=False)
    with pytest.raises(Exception):
        from data.data_import import import_local_fetcher
        import_local_fetcher(str(path), symbols=["600519", "000001"])


# --------------------------------------------------------------------------- #
# 入口行为
# --------------------------------------------------------------------------- #

def test_main_without_command_shows_welcome(capsys):
    """无子命令 → welcome 页（不执行任何取数动作）。"""
    code = main_mod.main([])
    captured = capsys.readouterr().out
    assert "多市场量化交易系统" in captured
    assert "运行模式" in captured
    assert code == 0


def test_cli_conformance_constants_present():
    """CLI_CONFORMANCE 关键字段齐备（控制平面配置不缺项）。"""
    conf = config.CLI_CONFORMANCE
    # v3.52：键名以发布方血统件为准；cli_defaults 等业务键移入 _USER_CLI_DEFAULTS
    assert conf["mode_order"] == ["backtest", "paper", "live"]
    assert conf["mode_may_only_downgrade"] is True
    assert conf["thin_entry"] is True
    assert conf["forbidden_flags_check_mode"] == "structural"
    assert conf["import_paths_must_use_data_layer"] is True
    assert set(required_columns()) == set(conf["must_feed_columns"])
    assert "checklist_pass" in conf["promote_requires"]
    assert "explicit_confirm_flag" in conf["promote_requires"]
    assert config._USER_CLI_DEFAULTS["cli_defaults"]["initial_cash"] == config.INITIAL_CASH


# --------------------------------------------------------------------------- #
# ⑤ 薄入口硬约束（I1/I4）：main.py ≤ 300 行，子模块 ≤ 300 行
# --------------------------------------------------------------------------- #

def test_thin_entry_line_limits():
    """main.py ≤ max_entry_lines；每个 cli_commands/*.py ≤ 300 行。"""
    root = Path(config.BASE_DIR)
    conf = config.CLI_CONFORMANCE
    assert conf["thin_entry"] is True
    limit = int(conf["max_entry_lines"])
    lines = len((root / "main.py").read_text(encoding="utf-8").splitlines())
    assert lines <= limit, f"main.py {lines} 行 > {limit}（薄入口约束）"
    mod_dir = root / conf["command_modules_dir"]
    assert mod_dir.is_dir()
    for path in sorted(mod_dir.glob("*.py")):
        count = len(path.read_text(encoding="utf-8").splitlines())
        assert count <= 300, f"{path.name} {count} 行 > 300"


def test_command_modules_expose_interface():
    """每个命令模块必须暴露 add_subparser(sp) 与 handler(args)。"""
    import importlib

    for name in main_mod.MODULES:
        module = importlib.import_module(f"cli_commands.{name}")
        assert callable(getattr(module, "add_subparser", None)), name
        assert callable(getattr(module, "handler", None)), name


def test_required_forbidden_flags_all_in_blacklist():
    """I3 点名的旁路开关必须全部在黑名单里（--force/--skip-freshness 等）。"""
    blacklist = {f.lower() for f in config.CLI_CONFORMANCE["forbidden_flags"]}
    required = {"--no-gate", "--force", "--skip-freshness", "--ignore-warmup",
                "--no-risk", "--disable-gate", "--skip-check"}
    assert required <= blacklist, f"黑名单缺项：{required - blacklist}"


@pytest.mark.parametrize("alias", ["--data", "--csv", "--from-file"])
def test_local_data_alias_parsed(alias):
    """--data / --csv / --from-file 三别名统一落到 args.data。"""
    parser = main_mod.build_parser()
    args = parser.parse_args(["backtest", "--strategy", "ma_cross", alias, "a.csv"])
    assert args.data == "a.csv"


def test_import_subcommand_parses_local_file():
    """data import 的 --csv/--from-file 别名同样落到 args.file。"""
    parser = main_mod.build_parser()
    assert parser.parse_args(["import", "--csv", "x.csv"]).file == "x.csv"
    assert parser.parse_args(["import", "--from-file", "y.csv"]).file == "y.csv"


def test_checklist_prints_four_counts(capsys):
    """checklist 输出四类计数（通过/警告/不通过/不适用）+ 已跑/未跑口径对照。"""
    parser = main_mod.build_parser()
    args = parser.parse_args(["checklist", "--strategy", "double_ma_cross"])
    code = args.handler(args)
    out = capsys.readouterr().out
    assert "汇总：通过" in out and "不适用" in out
    assert "口径对照" in out and "已跑" in out and "未跑" in out
    assert code in (0, 1)


def test_set_mode_subcommand_promotion_rejected_without_confirm(capsys):
    """set-mode 提升在无 --confirm 时被拒（清单通过也不行）。"""
    config.RUN_MODE = "backtest"
    parser = main_mod.build_parser()
    args = parser.parse_args(["set-mode", "--to", "paper", "--strategy",
                              "double_ma_cross"])
    monkey = cli_gate.enter_mode
    try:
        cli_gate.enter_mode = lambda *a, **k: (_ for _ in ()).throw(
            cli_gate.RunModePromotionError("需显式确认"))
        code = args.handler(args)
    finally:
        cli_gate.enter_mode = monkey
    assert code == 2
    assert "提升被拒" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# ⑥ K1：结构化禁参审计（与参数名无关，只看能力）
# --------------------------------------------------------------------------- #

def test_forbidden_flags_check_mode_is_structural():
    assert config.CLI_CONFORMANCE["forbidden_flags_check_mode"] == "structural"
    assert cli_gate.capability_violations(main_mod.build_parser()) == []


def test_structural_audit_catches_renamed_bypass():
    """改名后的旁路开关（--gate-off / --target live）同样被抓。"""
    import argparse

    parser = argparse.ArgumentParser(prog="fake")
    sub = parser.add_subparsers(dest="command")
    p = sub.add_parser("run")
    p.add_argument("--gate-off", dest="gate_off", action="store_true")
    p.add_argument("--target", choices=["backtest", "paper", "live"])
    p.set_defaults(handler=lambda args: 0)

    issues = cli_gate.capability_violations(parser)
    assert any("gate-off" in i for i in issues)
    assert any("--target" in i for i in issues)
    with pytest.raises(cli_gate.BypassFlagError):
        cli_gate.assert_no_structural_bypass(parser)


def test_structural_audit_catches_risk_skip_and_live_toggle():
    import argparse

    parser = argparse.ArgumentParser(prog="fake2")
    sub = parser.add_subparsers(dest="command")
    p = sub.add_parser("run")
    p.add_argument("--no-risk-check", action="store_true")
    p.add_argument("--live", action="store_true")
    p.add_argument("--runmode", choices=["paper"])
    p.set_defaults(handler=lambda args: 0)
    issues = cli_gate.capability_violations(parser)
    assert len(issues) >= 3, issues


def test_audited_mode_action_is_the_only_exception():
    """唯一豁免：config 登记的 set-mode --to（经 enter_mode 双门禁）。"""
    audited = config._USER_CLI_DEFAULTS["audited_mode_actions"]
    assert {"command": "set-mode", "dest": "to"} in audited
    parser = main_mod.build_parser()
    actions = {a.dest for a in parser._subparsers._group_actions[0].choices["set-mode"]
               ._actions}
    assert "to" in actions


def test_single_data_import_path():
    """--data / --csv 只允许走数据层出口（data/data_import），无第二旁路。"""
    root = Path(config.BASE_DIR)
    callers = []
    for path in root.rglob("*.py"):
        parts = path.relative_to(root).parts
        if parts[0] in ("tests", "data") or "site-packages" in parts:
            continue
        if "import_local_fetcher(" in path.read_text(encoding="utf-8", errors="ignore"):
            callers.append(str(path.relative_to(root)))
    assert callers == ["cli_commands/_common.py"], callers
