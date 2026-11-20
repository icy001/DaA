# -*- coding: utf-8 -*-
"""规格版本自校验验收：缺文件/缺版本头/版本不一致必须 fail-closed。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import config
from core import spec_check
from core.gov_compat import gov


def _write(tmp_path, header: str = None):
    body = "# 指令集\n"
    if header:
        body += f"<!-- spec_version: {header} -->\n"
    # v3.44：正文必须含必备章节标记（must_contain_markers），测试基座同步补齐；
    # v3.52 收口：on_marker_missing 默认 raise，基座直接从治理块生成全部 marker，
    # 未来新增 13.0.2x 时夹具自动跟随，不再出现「夹具缺 marker」整批误报
    for marker in gov("SPEC_VERSION_CHECK").get("must_contain_markers") or []:
        body += f"## {marker}\n"
    md = tmp_path / "Trae多市场量化系统搭建指令集-2.md"
    md.write_text(body, encoding="utf-8")
    # v3.40：版本号之外还要登记正文哈希（机器验内容，人看版本号）
    digest = spec_check.compute_sha256(md)
    for name in ("spec_content.sha256", "spec_drafts.sha256"):
        (tmp_path / name).write_text(f"{digest}  {md.name}\n", encoding="utf-8")
    return md


def _effective_hash_file() -> str:
    """当前口径下的哈希登记文件（draft → spec_drafts.sha256）。"""
    return spec_check.hash_file_path().name


def test_pass_when_header_matches(tmp_path):
    _write(tmp_path, config.SPEC_VERSION)
    out = spec_check.check_spec_version(root=tmp_path)
    assert out["ok"] is True and out["file"].endswith("-2.md")
    assert out["header"] == config.SPEC_VERSION


def test_glob_matches_copied_filename(tmp_path):
    """副本命名带 -2 也能被 glob 命中（旧版钉死单一文件名会误报）。"""
    _write(tmp_path, config.SPEC_VERSION)
    assert [p.name for p in spec_check.find_spec_files(tmp_path)] == \
        ["Trae多市场量化系统搭建指令集-2.md"]


def test_missing_file_raises_with_guidance(tmp_path):
    with pytest.raises(RuntimeError, match="未找到指令集文件"):
        spec_check.check_spec_version(root=tmp_path)


def test_missing_header_raises(tmp_path):
    _write(tmp_path, None)
    with pytest.raises(ValueError, match="缺少版本头"):
        spec_check.check_spec_version(root=tmp_path)


def test_version_mismatch_warns_not_raises(tmp_path):
    """v3.52 裁定：有头但版本不匹配 → warn（不 raise、不阻塞）。"""
    _write(tmp_path, "v0.01")
    out = spec_check.check_spec_version(root=tmp_path)
    assert out["ok"] is False and out["status"] == "warn"
    assert "规格版本不一致" in out["reason"]


def test_draft_suffix_allowed(tmp_path):
    _write(tmp_path, f"{config.SPEC_VERSION}-draft")
    assert spec_check.check_spec_version(root=tmp_path)["ok"] is True


def test_no_raise_mode_returns_reason(tmp_path):
    _write(tmp_path, "v0.01")
    out = spec_check.check_spec_version(root=tmp_path, raise_on_error=False)
    assert out["ok"] is False and "不一致" in out["reason"]


def test_check_config_cli_exit_code(tmp_path, monkeypatch, capsys):
    from cli_commands import check_config
    _write(tmp_path, config.SPEC_VERSION)
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    assert check_config.handler(None) == 0
    out = capsys.readouterr().out
    # v3.46：draft 口径只给黄灯，不得出现「[通过]」
    expected = "[草稿/黄]" if spec_check.is_draft() else "[通过]"
    assert expected in out

    # v3.52 裁定：版本不匹配 → warn（不阻塞，exit 0）
    (tmp_path / "Trae多市场量化系统搭建指令集-2.md").write_text(
        "<!-- spec_version: v0.01 -->", encoding="utf-8")
    assert check_config.handler(None) == 0
    assert "[警告]" in capsys.readouterr().out


# ==================== 分模式接入：钱相关拦、tooling 不拦 ====================

def test_enforce_skips_tooling(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    _write(tmp_path, None)                     # 规格不合规
    out = spec_check.enforce_on_startup("backtest")
    assert out["ok"] is False and out["skipped"] is True
    assert "不拦截" in out["reason"]


@pytest.mark.parametrize("mode", ["live", "live_sim", "paper"])
def test_enforce_raises_for_money_paths(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    _write(tmp_path, None)
    with pytest.raises(ValueError, match="缺少版本头"):
        spec_check.enforce_on_startup(mode)


def test_enforce_blocks_draft_on_money_paths(tmp_path, monkeypatch):
    """v3.46：草稿正文即使版本/哈希一致，也禁止进入 live/paper 链路。"""
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    _write(tmp_path, config.SPEC_VERSION)
    if not spec_check.is_draft():
        pytest.skip("当前 SPEC_PROVENANCE 已切为 reviewer_published")
    with pytest.raises(RuntimeError, match="草稿"):
        spec_check.enforce_on_startup("live")


def test_enforce_passes_when_published_and_version_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "SPEC_PROVENANCE",
                        {**config.SPEC_PROVENANCE, "authority": "reviewer_published"})
    _write(tmp_path, config.SPEC_VERSION)
    out = spec_check.enforce_on_startup("live")
    assert out["ok"] is True and out["draft"] is False


def test_enforce_modes_come_from_config():
    chk = gov("SPEC_VERSION_CHECK")
    assert set(chk["enforce_modes_strict"]) == {"live", "paper"}
    assert set(chk["enforce_modes_warn"]) == {"backtest", "research", "tooling"}


# ==================== v3.40：版本号不变、正文被改 → 必须不通过 ====================

def test_same_version_changed_content_fails(tmp_path):
    md = _write(tmp_path, config.SPEC_VERSION)
    with open(md, "a", encoding="utf-8") as fh:      # 版本头不动，只改正文
        fh.write("偷偷加一条规则\n")
    out = spec_check.check_spec_version(root=tmp_path, raise_on_error=False)
    assert out["ok"] is False and out["content_hash_mismatch"] is True
    assert "哈希不符" in out["reason"]
    with pytest.raises(ValueError, match="版本号被复用"):
        spec_check.check_spec_version(root=tmp_path)


def test_missing_hash_file_fails(tmp_path):
    _write(tmp_path, config.SPEC_VERSION)
    (tmp_path / _effective_hash_file()).unlink()
    out = spec_check.check_spec_version(root=tmp_path, raise_on_error=False)
    assert out["ok"] is False and "缺少规格正文哈希" in out["reason"]


def test_hash_matches_when_content_untouched(tmp_path):
    _write(tmp_path, config.SPEC_VERSION)
    out = spec_check.check_spec_version(root=tmp_path)
    assert out["ok"] is True and out["content_hash_checked"] is True


def test_check_config_cli_fails_on_hash_mismatch(tmp_path, monkeypatch, capsys):
    md = _write(tmp_path, config.SPEC_VERSION)
    from cli_commands import check_config
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    assert check_config.handler(None) == 0
    with open(md, "a", encoding="utf-8") as fh:
        fh.write("正文被改\n")
    assert check_config.handler(None) == 2
    assert "哈希" in capsys.readouterr().out


def test_hash_config_keys_declared():
    conf = config.SPEC_VERSION_CHECK
    assert conf["content_hash_required"] is True
    assert conf["content_hash_file"] == "spec_content.sha256"
    assert conf["on_content_hash_mismatch"] == "raise"
    assert conf["version_number_never_reused"] is True


# ==================== v3.44：章节标记 + 脚本哈希锁定 + 多副本 fail-closed ====================

def test_must_contain_markers_declared():
    """v3.52：清单单一来源=治理块，测试只钉单点锚，不再手抄第二份清单。

    手抄全列表必然随版本滚动失真（13.0.2x 逐版追加）；这里只钉三个单点锚
    （系列首 / 最新增量章节 / 收尾章居尾）——清单被静默截断在旧版时此处红。
    发布方追加 13.0.24 时增量锚同轮更新（改 config 必须同轮的约束）。
    """
    markers = config.SPEC_VERSION_CHECK["must_contain_markers"]
    assert markers, "must_contain_markers 不得为空（缺失即失守）"
    assert "13.0 开工前置" in markers       # 系列首锚
    assert "13.0.23" in markers             # 最新增量章节锚（追加 13.0.24 时同轮更新）
    assert markers[-1] == "13.13 收尾总检"  # 收尾章恒居尾


def test_missing_required_markers_fails(tmp_path, monkeypatch):
    """机制用例：缺 marker 必须拦——注入合成 marker 集，不绑定真实 13.0.x 列表。

    分工：夹具负责「合法文档能过」（marker 由治理块现场渲染）；
    本用例负责「非法文档被拦」（合成集 + 故意漏一个，断言 raise）。
    """
    monkeypatch.setattr(
        config, "SPEC_VERSION_CHECK",
        {**config.SPEC_VERSION_CHECK, "must_contain_markers": ["M1", "M2"]})
    md = tmp_path / "Trae多市场量化系统搭建指令集-2.md"
    md.write_text(f"<!-- spec_version: {config.SPEC_VERSION} -->\n## M1\n",
                  encoding="utf-8")
    (tmp_path / "spec_content.sha256").write_text(
        f"{spec_check.compute_sha256(md)}  {md.name}\n", encoding="utf-8")
    # 缺 M2：默认（未显式配置）即 raise，正文被裁剪后版本号不变照样拦
    with pytest.raises(ValueError, match="必备章节标记"):
        spec_check.check_spec_version(root=tmp_path)
    # 补齐 M2（夹具同款合法文档）：不因 marker 拦，哈希一致 → ok
    md.write_text(f"<!-- spec_version: {config.SPEC_VERSION} -->\n## M1\n## M2\n",
                  encoding="utf-8")
    (tmp_path / "spec_content.sha256").write_text(
        f"{spec_check.compute_sha256(md)}  {md.name}\n", encoding="utf-8")
    out = spec_check.check_spec_version(root=tmp_path)
    assert out["ok"] is True and "markers_missing" not in out


def test_marker_warn_mode_records_and_continues(tmp_path, monkeypatch):
    """机制用例：显式 warn 口径（版本滚动期临时配置）只记录缺失清单，不拦。"""
    monkeypatch.setattr(
        config, "SPEC_VERSION_CHECK",
        {**config.SPEC_VERSION_CHECK, "must_contain_markers": ["M1", "M2"],
         "on_marker_missing": "warn"})
    md = tmp_path / "Trae多市场量化系统搭建指令集-2.md"
    md.write_text(f"<!-- spec_version: {config.SPEC_VERSION} -->\n## M1\n",
                  encoding="utf-8")
    (tmp_path / "spec_content.sha256").write_text(
        f"{spec_check.compute_sha256(md)}  {md.name}\n", encoding="utf-8")
    out = spec_check.check_spec_version(root=tmp_path)
    assert out["ok"] is True and out.get("markers_missing") == ["M2"]
    assert out.get("marker_policy") == "warn"


def test_acceptance_script_hash_registered_and_matching():
    """仓库账本与脚本实况一致：config 登记的脚本必须在账本有记录且哈希吻合。"""
    out = spec_check.verify_acceptance_scripts()
    assert out["ok"] is True, out["reason"]
    assert out["script_hash_checked"] is True
    assert out["hash_file"] == "acceptance_scripts.ledger.jsonl"


def test_acceptance_script_hash_mismatch_detected(tmp_path):
    """账本登记的脚本被改动 → 不通过（改断言必须由非施工方追加 update 条目）。"""
    (tmp_path / "test_data.py").write_text("print('被篡改')\n", encoding="utf-8")
    (tmp_path / "acceptance_scripts.ledger.jsonl").write_text(
        json.dumps({"meta": {"authority": "draft_self_authored"}}) + "\n" +
        json.dumps({"path": "test_data.py", "sha256": "0" * 64,
                    "action": "register", "spec_version": config.SPEC_VERSION,
                    "reason": "v3.48 建账"}) + "\n",
        encoding="utf-8")
    out = spec_check.verify_acceptance_scripts(root=tmp_path)
    assert out["ok"] is False and "test_data.py" in out["reason"]
    assert "update 条目" in out["reason"]


def test_acceptance_governance_keys_declared():
    """v3.52：操作键以发布方块为标准 + 业务区 compat 补位（gov 唯一入口）。"""
    conf = gov("ACCEPTANCE_GOVERNANCE")
    assert conf["script_hash_locked"] is True
    assert conf["source_unreachable_must_mark"] == "skipped_due_to_source"
    assert conf["skipped_counts_as"] == "uncovered"
    assert conf["core_check_offline_impl_required"] is True
    assert "cn_index" in conf["unit_invariants_by_asset_class"]
    assert "禁用 close×volume" in conf["unit_invariants_by_asset_class"]["cn_index"]
    # 发布方新增的账本链式键必须就位
    assert conf["ledger_hash_chain_required"] is True
    assert conf["chain_break_action"] == "raise"


def test_multiple_spec_copies_fail_closed(tmp_path):
    """v3.44：多副本并存必须报错——哈希只锁住被检查的一份，另一份游离即漂移根源。"""
    _write(tmp_path, config.SPEC_VERSION)
    (tmp_path / "Trae多市场量化系统搭建指令集-3.md").write_text(
        "<!-- spec_version: v0.01 -->\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="副本"):
        spec_check.check_spec_version(root=tmp_path)


# ==================== v3.46 / 13.0.17：draft 只给黄灯，不得自证转绿 ====================

def test_spec_provenance_declared():
    """v3.52：authority=reviewer 即发布；本机操作态是 draft_self_authored（黄灯）。"""
    prov = gov("SPEC_PROVENANCE")
    assert prov["authority"] == "reviewer"
    assert prov["forbid_draft_as_authority"] is True
    assert prov["local_selfauthored_is_draft"] is True
    sysc = gov("SYSTEM_CONFORMANCE")
    assert sysc["spec_authority_single_source"] is True
    assert sysc["test_data_count_must_be_reported_raw"] is True
    # operational：本机脚本哈希登记权威（黄灯依据），不得上冒
    assert gov("ACCEPTANCE_GOVERNANCE")["script_hash_authority"] == "draft_self_authored"


def test_draft_uses_draft_hash_file_and_never_greens(tmp_path, monkeypatch):
    """draft 必须读 spec_drafts.sha256；即使哈希一致也只能是黄灯。"""
    monkeypatch.setattr(config, "SPEC_PROVENANCE",
                        {**config.SPEC_PROVENANCE, "authority": "draft_self_authored"})
    _write(tmp_path, config.SPEC_VERSION)
    assert spec_check.hash_file_path(tmp_path).name == "spec_drafts.sha256"
    out = spec_check.check_spec_version(root=tmp_path)
    assert out["ok"] is True and out["draft"] is True and out["status"] == "yellow"

    # 只改发布哈希不影响 draft 判定：draft 根本不读 spec_content.sha256
    (tmp_path / "spec_content.sha256").write_text("0" * 64 + "  x\n", encoding="utf-8")
    assert spec_check.check_spec_version(root=tmp_path)["ok"] is True


def test_published_uses_content_hash_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SPEC_PROVENANCE",
                        {**config.SPEC_PROVENANCE, "authority": "reviewer_published"})
    _write(tmp_path, config.SPEC_VERSION)
    assert spec_check.hash_file_path(tmp_path).name == "spec_content.sha256"
    out = spec_check.check_spec_version(root=tmp_path)
    assert out["ok"] is True and out["draft"] is False and out["status"] == "green"


# ==================== v3.47 / 13.0.18：draft 有权限 + 脚本哈希不得自证 ====================

def test_draft_blocks_money_paths_but_check_config_still_runs(tmp_path, monkeypatch, capsys):
    """③ draft 只给黄灯不等于有权限：live/paper raise，check-config 与研究路径仍可跑。"""
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "SPEC_PROVENANCE",
                        {**config.SPEC_PROVENANCE, "authority": "draft_self_authored"})
    _write(tmp_path, config.SPEC_VERSION)

    from cli_commands import check_config
    assert check_config.handler(None) == 0          # 自检命令不受 draft 锁定
    assert "[草稿/黄]" in capsys.readouterr().out

    perm = gov("SPEC_DRAFT_PERMISSION")
    blocked = [m for m, v in perm["mode_matrix"].items() if v == "raise"]
    allowed = [m for m, v in perm["mode_matrix"].items() if v != "raise"]
    for mode in blocked:
        with pytest.raises(RuntimeError, match="SPEC_DRAFT_PERMISSION"):
            spec_check.enforce_on_startup(mode)
    for mode in allowed:
        assert spec_check.enforce_on_startup(mode)["skipped"] is True

    # 权限判定来自 mode_matrix（唯一来源）：把 tooling 改成 raise 也必须拦
    monkeypatch.setattr(config, "SPEC_DRAFT_PERMISSION",
                        {**config.SPEC_DRAFT_PERMISSION,
                         "mode_matrix": {**config.SPEC_DRAFT_PERMISSION["mode_matrix"],
                                         "tooling": "raise"}})
    with pytest.raises(RuntimeError, match="草稿"):
        spec_check.enforce_on_startup("tooling")


def test_script_hash_registry_is_authoritative(tmp_path, monkeypatch):
    """⑥ 脚本哈希的权威来源是追加式账本：缺账本/来源自证都必须不通过。"""
    (tmp_path / "test_data.py").write_text("print(1)\n", encoding="utf-8")
    monkeypatch.setattr(config, "_GOV_RUNTIME_COMPAT",
                        {**config._GOV_RUNTIME_COMPAT,
                         "ACCEPTANCE_GOVERNANCE": {
                             k: v for k, v in config._GOV_RUNTIME_COMPAT[
                                 "ACCEPTANCE_GOVERNANCE"].items()
                             if k != "script_hashes"}})
    out = spec_check.verify_acceptance_scripts(root=tmp_path)
    assert out["ok"] is False and "缺少哈希账本" in out["reason"]

    digest = spec_check.compute_sha256(tmp_path / "test_data.py")
    (tmp_path / "acceptance_scripts.ledger.jsonl").write_text(
        json.dumps({"meta": {"authority": "draft_self_authored"}}) + "\n" +
        json.dumps({"path": "test_data.py", "sha256": digest,
                    "action": "register", "spec_version": config.SPEC_VERSION,
                    "reason": "v3.48 建账"}) + "\n",
        encoding="utf-8")
    # config 自称的级别高于账本 meta → 自证，不通过（作者=登记者不得自抬级别）
    # v3.52：OPERATIONAL_OVERRIDES 最优先，自证模拟必须两处同步改
    compat = {**config._GOV_RUNTIME_COMPAT}
    compat["ACCEPTANCE_GOVERNANCE"] = {**compat.get("ACCEPTANCE_GOVERNANCE", {}),
                                       "script_hash_authority": "reviewer_published"}
    compat["OPERATIONAL_OVERRIDES"] = {
        **compat.get("OPERATIONAL_OVERRIDES", {}),
        "ACCEPTANCE_GOVERNANCE": {**compat.get("OPERATIONAL_OVERRIDES", {})
                                  .get("ACCEPTANCE_GOVERNANCE", {}),
                                  "script_hash_authority": "reviewer_published"}}
    monkeypatch.setattr(config, "_GOV_RUNTIME_COMPAT", compat)
    out = spec_check.verify_acceptance_scripts(root=tmp_path)
    assert out["ok"] is False and "自证" in out["reason"]


def test_script_hash_registry_matches_repo():
    """⑥ 仓库账本与 config 声明同源（比对以账本末条为准，config 值不参与）。"""
    out = spec_check.verify_acceptance_scripts()
    assert out["ok"] is True, out["reason"]
    assert out["hash_file"] == gov("ACCEPTANCE_GOVERNANCE")["hash_ledger_file"]
    assert out["authority"] == gov("ACCEPTANCE_GOVERNANCE")["script_hash_authority"]


# ==================== v3.48 / 13.0.19：矩阵默认拒绝 + 追加式账本 + 配置面哈希 ====================

def _ledger_entry(path, sha256, action="register", reason="v3.48 建账"):
    return json.dumps({"path": path, "sha256": sha256, "action": action,
                       "spec_version": config.SPEC_VERSION, "reason": reason})


# ---------- ⑤ 未登记模式默认拒绝（mode_matrix_default=deny） ----------

def test_unknown_mode_blocked_by_matrix_default():
    """⑤ 未登记模式在白名单之前就被拦（v3.49：不再靠矩阵 miss 碰巧兜住）。

    v3.48 靠「矩阵 miss + default=deny」；v3.49 改为 valid_modes 白名单先行，
    枚举外的模式（含拼写错误）一律 raise，不进入矩阵查询。
    """
    assert config.SPEC_DRAFT_PERMISSION["mode_matrix_default"] == "deny"
    assert config.SPEC_DRAFT_PERMISSION["unknown_mode_action"] == "raise"
    assert spec_check.is_draft_blocked_mode("live") is True          # 矩阵命中
    assert spec_check.is_draft_blocked_mode("backtest") is False     # 矩阵命中
    with pytest.raises(ValueError, match="未登记运行模式"):
        spec_check.is_draft_blocked_mode("mars_live")                # 白名单外 → raise


def test_unknown_mode_enforce_raises_with_default_deny(tmp_path, monkeypatch):
    """⑤ enforce 链路：未登记模式必须在白名单校验处 raise，不落到矩阵兜底。"""
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "SPEC_PROVENANCE",
                        {**config.SPEC_PROVENANCE, "authority": "draft_self_authored"})
    _write(tmp_path, config.SPEC_VERSION)
    with pytest.raises(ValueError, match="未登记运行模式"):
        spec_check.enforce_on_startup("mars_live")
    # 已登记的钱路径 raise 文案指向矩阵命中，两种文案必须可区分
    with pytest.raises(RuntimeError, match="mode_matrix 命中"):
        spec_check.enforce_on_startup("live")


def test_mode_matrix_is_single_source():
    """⑤ v3.52：矩阵是唯一来源，default=deny；raise 项必须落在 valid_modes 内。"""
    perm = gov("SPEC_DRAFT_PERMISSION")
    assert perm["mode_matrix_default"] == "deny"
    assert set(perm["valid_modes"]) == {"backtest", "research", "paper",
                                        "live", "live_sim", "tooling"}
    matrix_raise = {m for m, v in perm["mode_matrix"].items() if v == "raise"}
    assert matrix_raise <= set(perm["valid_modes"])
    assert perm["unknown_mode_action"] == "raise"


# ---------- ⑥ 追加式账本：改行/删行/删测试都必须暴露 ----------

def test_ledger_bad_json_and_missing_fields_fail(tmp_path):
    """⑥ 账本是只追加的：改行（坏 JSON）/缺五元组字段 → 不通过。"""
    (tmp_path / "test_data.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "acceptance_scripts.ledger.jsonl").write_text(
        json.dumps({"meta": {"authority": "draft_self_authored"}}) + "\n" +
        "不是 JSON 的一行（改行痕迹）\n" +
        json.dumps({"path": "test_data.py", "sha256": "0" * 64}) + "\n",
        encoding="utf-8")
    out = spec_check.verify_acceptance_scripts(root=tmp_path)
    assert out["ok"] is False
    assert "不是合法 JSON" in out["reason"]          # 改行
    assert "缺五元组字段" in out["reason"]            # action/spec_version/reason 缺失


def test_ledger_update_entry_supersedes_register(tmp_path, monkeypatch):
    """⑥ 同一脚本多条记录 → 以末条为准（追加 update 覆盖 register）。"""
    # v3.52：script_hashes 操作键在业务区 compat，隔离后 tmp 账本自洽
    monkeypatch.setattr(config, "_GOV_RUNTIME_COMPAT",
                        {**config._GOV_RUNTIME_COMPAT,
                         "ACCEPTANCE_GOVERNANCE": {
                             k: v for k, v in config._GOV_RUNTIME_COMPAT[
                                 "ACCEPTANCE_GOVERNANCE"].items()
                             if k != "script_hashes"}})
    p = tmp_path / "test_data.py"
    p.write_text("print('v2 内容')\n", encoding="utf-8")
    digest = spec_check.compute_sha256(p)
    (tmp_path / "acceptance_scripts.ledger.jsonl").write_text(
        json.dumps({"meta": {"authority": "draft_self_authored"}}) + "\n" +
        _ledger_entry("test_data.py", "0" * 64) + "\n" +
        _ledger_entry("test_data.py", digest, action="update",
                      reason="断言扩充，重新登记") + "\n",
        encoding="utf-8")
    out = spec_check.verify_acceptance_scripts(root=tmp_path)
    assert out["ok"] is True, out["reason"]           # 末条 update 生效


def test_ledger_delete_without_reason_fails(tmp_path):
    """⑥ 删测试必须追 delete 条目且带 reason：缺 reason / 文件复活都不通过。"""
    (tmp_path / "test_data.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "acceptance_scripts.ledger.jsonl").write_text(
        json.dumps({"meta": {"authority": "draft_self_authored"}}) + "\n" +
        json.dumps({"path": "test_data.py", "sha256": "0" * 64,
                    "action": "delete", "spec_version": config.SPEC_VERSION,
                    "reason": ""}) + "\n",
        encoding="utf-8")
    out = spec_check.verify_acceptance_scripts(root=tmp_path)
    assert out["ok"] is False and "delete 缺 reason" in out["reason"]
    # 已记 delete 但文件仍存在（删了登记没删文件 / 复活）→ 不通过
    (tmp_path / "acceptance_scripts.ledger.jsonl").write_text(
        json.dumps({"meta": {"authority": "draft_self_authored"}}) + "\n" +
        _ledger_entry("test_data.py", "0" * 64, action="delete",
                      reason="脚本退役") + "\n",
        encoding="utf-8")
    out = spec_check.verify_acceptance_scripts(root=tmp_path)
    assert out["ok"] is False and "已记 delete 但文件仍存在" in out["reason"]


def test_legacy_manifest_no_longer_authoritative(tmp_path):
    """⑥ 旧映射表已冻结：拿 legacy_manifest_frozen 冒充账本 → 缺账本 fail。"""
    (tmp_path / "test_data.py").write_text("print(1)\n", encoding="utf-8")
    legacy = gov("ACCEPTANCE_GOVERNANCE")["legacy_manifest_frozen"]
    (tmp_path / legacy).write_text("# authority: draft_self_authored\n", encoding="utf-8")
    out = spec_check.verify_acceptance_scripts(root=tmp_path)
    assert out["ok"] is False and "缺少哈希账本" in out["reason"]


# ---------- ⑦ 配置面哈希：只比结构、不比取值 ----------

def test_config_surface_computable_and_registered():
    """⑦ 配置面哈希可计算且已登记（两机对齐的锚点）。"""
    surface = spec_check.compute_config_surface()
    assert surface["enabled"] is True and surface["sha256"]
    assert surface["constants"] > 100 and surface["elements"] > surface["constants"]
    out = spec_check.verify_config_surface()
    assert out["checked"] is True
    assert out["ok"] is True, out["reason"]


def test_config_surface_drift_detected(tmp_path, monkeypatch):
    """⑦ 登记值与实算值不一致 = 结构漂移（改了键结构未重算登记）。"""
    surface = spec_check.compute_config_surface()
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    (tmp_path / "config_surface.sha256").write_text(
        "0" * 64 + "  config.py\n", encoding="utf-8")
    out = spec_check.verify_config_surface()
    assert out["ok"] is False and "结构漂移" in out["reason"]
    assert out["sha256"] == surface["sha256"]         # 实算值不受登记影响


def test_config_surface_ignores_values_and_comments(monkeypatch, tmp_path):
    """⑦ 只比结构不比取值：改值/加注释不得改变哈希；加键必须改变哈希。"""
    surface = spec_check.compute_config_surface()
    src = Path(config.__file__).read_text(encoding="utf-8")
    fake = tmp_path / "config.py"

    # ① 取值改动 + 施工注释：结构面必须不变（surface 只看常量名与键名）
    patched = src.replace(f'SPEC_VERSION = "{config.SPEC_VERSION}"',
                          'SPEC_VERSION = "v9.99"  # 施工注释不参与 surface')
    assert patched != src, "锚点未命中：config.py 的 SPEC_VERSION 行"
    fake.write_text(patched, encoding="utf-8")
    monkeypatch.setattr(config, "__file__", str(fake))
    assert spec_check.compute_config_surface()["sha256"] == surface["sha256"], \
        "改值/加注释不得改变结构面哈希"

    # ② 新增顶层常量 = 结构变化：哈希必须变（漏键/多键正是靠这个暴露）
    fake.write_text(src + "\nNEW_V348_PROBE_KEY = 1\n", encoding="utf-8")
    drifted = spec_check.compute_config_surface()
    assert drifted["sha256"] != surface["sha256"], "加键未改变哈希 → surface 失效"
    assert drifted["constants"] == surface["constants"] + 1


def test_surface_cs_v1_golden_vector(monkeypatch):
    """① cs-v1 算法自证：黄金向量必须复现 72bc8831…（算法先对，再比数据）。"""
    out = spec_check.verify_surface_algorithm()
    assert out["algo"] == "cs-v1"
    assert out["ok"] is True, out
    assert out["golden_sha256"] == out["actual_sha256"]
    # 只下钻 dict 不下钻 list：L 内的 dropped 不得出现
    assert "dropped" not in spec_check.SURFACE_GOLDEN_ELEMENTS
    assert spec_check.surface_digest(["A", "GOLDEN", "L", "Z", "b", "c"]) == \
        spec_check.SURFACE_GOLDEN_SHA256
    # 少一个尾换行就是另一个哈希（v3.49 正是没钉死这一步）
    import hashlib
    no_trail = hashlib.sha256("\n".join(spec_check.SURFACE_GOLDEN_ELEMENTS).encode()).hexdigest()
    assert no_trail != spec_check.SURFACE_GOLDEN_SHA256
    # v3.51 ④：黄金向量必须覆盖去重路径——"A" 同时是常量与块内键，
    # 并集去重后元素集与哈希不变（consts 与块键零交集时该路径从未执行）
    monkeypatch.setattr(config, "SURFACE_GOLDEN_BLOCK",
                        {"b": 1, "A": {"c": 2}, "L": [{"dropped": 9}]}, raising=False)
    elements = spec_check.surface_elements(constants=["A", "GOLDEN", "Z"],
                                           blocks=["SURFACE_GOLDEN_BLOCK"])
    assert elements == ["A", "GOLDEN", "L", "Z", "b", "c"]
    assert spec_check.surface_digest(elements) == spec_check.SURFACE_GOLDEN_SHA256


def test_surface_dump_file_matches_elements(tmp_path, monkeypatch):
    """② 规范化元素表可导出，且与实算元素逐行一致（comm -3 的唯一输入）。"""
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    (tmp_path / "config.py").write_text(
        Path(config.__file__).read_text(encoding="utf-8"), encoding="utf-8")
    spec_check.write_surface_hash(root=tmp_path)
    dump = tmp_path / "config_surface.elements.txt"
    assert dump.exists()
    lines = dump.read_text(encoding="utf-8").splitlines()
    assert lines == spec_check.surface_elements()
    assert len(lines) == spec_check.compute_config_surface()["elements"]


def test_guard_whitelist_covers_guard_blocks():
    """④ 白名单完备性：名字像治理/守卫的 dict 块必须全部在册（漏纳 = surface 失明）。"""
    out = spec_check.scan_unlisted_guard_blocks()
    assert out["ok"] is True, out["reason"]
    assert out["whitelist_total"] == 30


# ==================== v3.49 / 13.0.20：判据是白名单 ====================

def test_surface_whitelist_exact():
    """① 递归集合严格等于 surface_recurse_blocks：逐名列出、全部存在且是 dict。"""
    conf = config.CONFIG_SURFACE          # 发布方血统键逐字断言
    blocks = list(conf["surface_recurse_blocks"])
    assert conf["surface_algo_id"] == "cs-v1"
    assert conf["non_dict_block_action"] == "raise"
    assert conf["unlisted_guard_block_action"] == "raise"
    assert "whitelist_exclusions" in conf   # v3.51 ②：白名单纯净性规则就位
    assert len(blocks) == len(set(blocks)) == 30
    # 业务配置不得混进递归集合（CN_INDEX/MARKETS/BROKER_DEFAULT 等）
    for business in ("CN_INDEX", "MARKETS", "BROKER_DEFAULT", "INITIAL_CASH"):
        assert business not in blocks, f"业务配置 {business} 不得进入治理面白名单"
    surface = spec_check.compute_config_surface()
    assert surface["blocks"] == len(blocks)
    # v3.52：常量名与块内键名可能重名（并集去重），元素数 = |常量集 ∪ 键集|
    assert surface["elements"] == len(spec_check.surface_elements())
    assert surface["elements"] <= surface["constants"] + surface["keys"]


def test_surface_missing_block_raises(monkeypatch):
    """① 白名单块在 config 中缺失 → raise（两机对齐的前提是同一份集合）。"""
    conf = dict(config.CONFIG_SURFACE)
    conf["surface_recurse_blocks"] = list(conf["surface_recurse_blocks"]) + \
        ["THIS_BLOCK_DOES_NOT_EXIST"]
    monkeypatch.setattr(config, "CONFIG_SURFACE", conf)
    with pytest.raises(RuntimeError, match="白名单块在 config 中缺失"):
        spec_check.compute_config_surface()


def test_surface_ignores_list_elements(monkeypatch):
    """① 列表是取值不是结构：往白名单块内的列表追加元素，surface 必须不变。"""
    before = spec_check.compute_config_surface()["sha256"]
    block = {k: (list(v) if isinstance(v, list) else v)
             for k, v in config.DATA_LONG_TERM.items()}
    block["data_source_priority"] = list(block["data_source_priority"]) + ["probe_source"]
    monkeypatch.setattr(config, "DATA_LONG_TERM", block)
    assert spec_check.compute_config_surface()["sha256"] == before, \
        "列表元素被递归展开 → 业务取值混进结构面"


def test_invalid_mode_raises_before_matrix(monkeypatch):
    """④ 封闭白名单先于矩阵：空格笔误 / CLI 自定义串 / 矩阵扩容都不得 fail-open。"""
    valid = config.SPEC_DRAFT_PERMISSION["valid_modes"]
    assert valid == ["backtest", "research", "paper", "live", "live_sim", "tooling"]
    # .env 笔误：带空格
    with pytest.raises(ValueError, match="未登记运行模式"):
        spec_check.validate_mode("liv ")
    # CLI 自定义字符串
    with pytest.raises(ValueError, match="未登记运行模式"):
        spec_check.validate_mode("prod_live")
    # 即使矩阵里加了 prod_live=allow，但未加入 valid_modes → 仍然 raise
    perm = dict(config.SPEC_DRAFT_PERMISSION)
    perm["mode_matrix"] = {**perm["mode_matrix"], "prod_live": "allow"}
    monkeypatch.setattr(config, "SPEC_DRAFT_PERMISSION", perm)
    with pytest.raises(ValueError, match="未登记运行模式"):
        spec_check.validate_mode("prod_live")
    with pytest.raises(ValueError, match="未登记运行模式"):
        spec_check.is_draft_blocked_mode("prod_live")
    # 合法模式不受影响
    assert spec_check.validate_mode("LIVE") == "live"


def test_ledger_covers_all_script_globs():
    """③ 账本必须覆盖 glob 命中的全部验收脚本（不是只登记 2 条）。"""
    out = spec_check.verify_acceptance_scripts()
    assert out["ok"] is True, out["reason"]
    globbed, registered = int(out["globbed"]), int(out["registered"])
    # 48 = 47（v3.53 评审二轮冻结）+ 1（tests/test_dual_price_minute.py：双价体系除权日专项套件）
    assert globbed == 48, f"glob 命中 {globbed} 个验收脚本（9 根 + 38 tests + 1 checklist）"
    assert out["coverage"] == f"{globbed}/{globbed}"
    assert registered >= globbed


def test_unregistered_glob_script_fails(tmp_path, monkeypatch):
    """③ glob 命中但账本没登记 → 不通过（未登记脚本改了没人知道）。"""
    monkeypatch.setattr(config, "ACCEPTANCE_GOVERNANCE",
                        {**config.ACCEPTANCE_GOVERNANCE,
                         "script_hashes": {}, "script_globs": ["test_*.py"]})
    p = tmp_path / "test_probe.py"
    p.write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "acceptance_scripts.ledger.jsonl").write_text(
        json.dumps({"meta": {"authority": "draft_self_authored"}}) + "\n",
        encoding="utf-8")
    out = spec_check.verify_acceptance_scripts(root=tmp_path)
    assert out["ok"] is False
    assert "glob 命中但账本未登记" in out["reason"]
    assert out["coverage"] == "0/1"


def test_legacy_manifest_migrated_into_ledger():
    """③ 旧映射表条目必须全量 migrate 到账本（action=add + 迁移理由），旧表冻结。"""
    path = Path(config.BASE_DIR) / config.ACCEPTANCE_GOVERNANCE["hash_ledger_file"]
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    migrated = {r["path"]: r for r in lines
                if r.get("action") == "add"
                and "legacy migration" in str(r.get("reason") or "")}
    legacy = gov("ACCEPTANCE_GOVERNANCE")["legacy_manifest_frozen"]
    legacy_lines = (Path(config.BASE_DIR) / legacy).read_text(encoding="utf-8").splitlines()
    legacy_paths = {ln.split()[-1] for ln in legacy_lines
                    if ln.strip() and not ln.startswith("#")}
    assert legacy_paths, "旧映射表应含待迁移条目"
    assert legacy_paths <= set(migrated), f"未迁移：{legacy_paths - set(migrated)}"
