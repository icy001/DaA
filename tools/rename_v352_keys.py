#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v3.49 -> v3.52 键名对齐第一步：AST 级字典键改名（发布方 163 对映射，逐字转写）。

只改白名单治理块内作为【字典键】出现的名字（ast.Constant 键节点），
不动取值、不动 docstring/注释/业务块。发布方格式「目标键名 ← 本机键名」。

用法：
  python3 tools/rename_v352_keys.py [SRC] [DST]   # 缺省 config.py -> config.renamed.py
"""
import ast
import io
import sys

# (块名, 本机键名, 目标键名) —— 与发布方映射逐字一致；同名多次出现按文档顺序消费
RENAME_MAP = {
    "ACCEPTANCE_GOVERNANCE": [
        ("ledger_action_values", "ledger_entries_immutable"),
        ("ledger_required_fields", "ledger_entry_required_fields"),
        ("ledger_hash_chain_prev_field", "ledger_prev_hash_field"),
        ("ledger_hash_chain_entry_field", "ledger_entry_hash_field"),
        ("migration_must_verify_old_hash_first", "ledger_migration_must_verify_old_hash"),
        ("rehash_on_migrate_forbidden", "ledger_migration_forbid_rehash"),
        ("ledger_hash_chain_required", "ledger_chain_required"),
        ("ledger_hash_chain_prev_field", "ledger_chain_prev_field"),
        ("ledger_hash_chain_entry_field", "ledger_chain_entry_field"),
        ("ledger_append_only_required", "ledger_append_only"),
        ("ledger_no_overwrite_allowed", "ledger_no_overwrite"),
        ("ledger_no_delete_allowed", "ledger_no_delete"),
        ("manifest_hash_required_on_migrate", "ledger_manifest_hash_required"),
        ("run_id_required_in_entry", "ledger_run_id_required"),
        ("timestamp_required_in_entry", "ledger_timestamp_required"),
        ("counts_required_in_entry", "ledger_counts_required"),
        ("surface_hash_required_in_entry", "ledger_surface_hash_required"),
        ("spec_version_required_in_entry", "ledger_spec_version_required"),
        ("algo_id_required_in_entry", "ledger_algo_id_required"),
        ("whitelist_hash_required_in_entry", "ledger_whitelist_hash_required"),
        ("mode_required_in_entry", "ledger_mode_required"),
        ("exit_code_required_in_entry", "ledger_exit_code_required"),
    ],
    "SUITE_COVERAGE_GUARD": [
        ("baseline_anchored_to_historical_peak", "suite_baseline_anchor_peak_required"),
        ("baseline_initial_peaks", "suite_baseline_initial_peaks"),
        ("silent_ratchet_down_forbidden", "suite_silent_ratchet_down_forbidden"),
        ("baseline_file", "suite_baseline_file"),
        ("baseline_format", "suite_baseline_format"),
        ("baseline_version_field", "suite_baseline_version_field"),
        ("baseline_counts_field", "suite_baseline_counts_field"),
        ("baseline_updated_at_field", "suite_baseline_updated_at_field"),
        ("baseline_evidence_field", "suite_baseline_evidence_field"),
        ("baseline_evidence_required", "suite_baseline_evidence_required"),
        ("baseline_evidence_format", "suite_baseline_evidence_format"),
        ("per_suite_breakdown_required", "suite_per_suite_required"),
        ("count_definition_stable", "suite_count_definition_stable"),
        ("frozen_total_suites", "suite_frozen_total"),
        ("on_unjustified_shrink", "suite_on_unjustified_shrink"),
        ("unit_field_required", "suite_unit_field_required"),
        ("unit_allowed_values", "suite_unit_allowed_values"),
    ],
    "DATA_SOURCE_ADAPTER_GUARD": [
        ("internal_failover_whitelist_only", "internal_failover_allowlist"),
        ("required_adapter_interface", "adapter_required_interface"),
        ("required_adapter_methods", "adapter_required_methods"),
        ("fetch_kline_signature", "adapter_fetch_kline_signature"),
        ("fetch_instrument_signature", "adapter_fetch_instrument_signature"),
        ("fetch_quote_signature", "adapter_fetch_quote_signature"),
        ("normalize_frame_required", "adapter_normalize_frame"),
        ("raise_on_missing_column", "adapter_raise_on_missing"),
        ("ts_sorted_required", "adapter_ts_sorted"),
        ("ts_ascending_required", "adapter_ts_ascending"),
        ("code_dtype_required", "adapter_code_dtype"),
        ("duplicate_detect_required", "adapter_duplicate_detect"),
        ("cache_ttl_required", "adapter_cache_ttl"),
        ("market_field_required", "adapter_market_field"),
    ],
    "EMPTY_REASON_PROVENANCE": [
        ("required_fields", "empty_reason_required_fields"),
        ("reason_code_required", "empty_reason_code_required"),
        ("source_required", "empty_reason_source_required"),
        ("ts_required", "empty_reason_ts_required"),
        ("market_required", "empty_reason_market_required"),
        ("reason_code_allowlist", "empty_reason_code_allowlist"),
        ("no_silent_drop", "empty_reason_no_silent_drop"),
        ("log_required", "empty_reason_log_required"),
        ("raise_on_unknown_code", "empty_reason_raise_on_unknown"),
        ("persist_to_cache", "empty_reason_persist_to_cache"),
        ("cache_field_name", "empty_reason_cache_field"),
        ("report_field_name", "empty_reason_report_field"),
        ("snapshot_field_name", "empty_reason_snapshot_field"),
        ("audit_trail_required", "empty_reason_audit_trail"),
    ],
    "SYSTEM_CONFORMANCE": [
        ("must_report_raw_and_bound", "must_report_raw_observed"),
        ("expected_counts_action", "expected_counts_mismatch_action"),
        ("frozen_counts_are_outputs_not_criteria", "frozen_counts_are_outputs"),
        ("hand_typed_expected_forbidden", "hand_typed_expected_forbidden"),  # 恒等对
        ("cross_version_compare_action", "cross_version_compare_refuse"),
        ("compare_requires_same_spec_version", "compare_requires_same_spec"),
        ("compare_requires_same_algo_id", "compare_requires_same_algo"),
        ("compare_requires_same_whitelist", "compare_requires_same_whitelist"),
        ("delivery_channel_must_be_verified", "delivery_channel_verified"),
        ("spec_body_must_allow_key_level_reconstruction", "spec_body_key_level_reconstruct"),
    ],
    "NONDETERMINISTIC_SCRIPT_GUARD": [
        ("surface_collection_must_be_ast_based", "nondet_ast_based_collection"),
        ("dir_based_collection_forbidden", "nondet_dir_based_forbidden"),
        ("recurse_blocks_exhaustive", "nondet_recurse_blocks_exhaustive"),
        ("missing_recurse_block_action", "nondet_missing_recurse_block_raise"),
        ("guard_block_name_pattern", "nondet_guard_block_name_pattern"),
        ("valid_modes", "nondet_valid_modes"),
        ("invalid_mode_action", "nondet_invalid_mode_raise"),
        ("whitelist_completeness_required", "nondet_whitelist_completeness"),
        ("offline_bound_must_be_ast_literal", "nondet_offline_bound_ast"),
        ("observed_gt_bound_raise", "nondet_observed_gt_bound_raise"),
        ("deterministic_bound_naming", "nondet_bound_naming"),
    ],
    "LIVE_SAFETY": [
        ("personal_derivatives_block", "personal_derivatives_hard_block"),
        ("personal_derivatives_block_message", "personal_derivatives_block_message"),  # 恒等对
        ("live_sim_only_markets", "live_sim_only_markets"),                            # 恒等对
        ("live_real_markets_allowlist", "live_real_markets_allowlist"),                # 恒等对
        ("live_order_precheck_required", "live_order_precheck"),
        ("live_order_precheck_fields", "live_order_precheck_fields"),
        ("live_order_risk_check_required", "live_order_risk_check"),
        ("live_position_limit_per_code", "live_position_limit"),
        ("live_daily_loss_limit_pct", "live_daily_loss_limit"),
        ("live_kill_switch_enabled", "live_kill_switch"),
        ("live_manual_confirm_required", "live_confirm_required"),
        ("live_log_all_orders_required", "live_log_all_orders"),
    ],
    "CLI_CONFORMANCE": [
        ("required_modules", "cli_required_modules"),
        ("required_module_interface", "cli_module_interface"),
        ("module_register_func_name", "cli_module_register_func"),
        ("module_name_field", "cli_module_name_field"),
        ("module_help_field", "cli_module_help_field"),
        ("subcommand_required", "cli_subcommand_required"),
        ("no_unknown_args_allowed", "cli_no_unknown_args"),
        ("exit_code_convention", "cli_exit_code_convention"),
        ("exit_code_ok", "cli_exit_ok"),
        ("exit_code_fail", "cli_exit_fail"),
        ("exit_code_config_error", "cli_exit_config_error"),
        ("exit_code_spec_error", "cli_exit_spec_error"),
        ("exit_code_runtime_error", "cli_exit_runtime_error"),
        ("log_timestamp_required", "cli_log_timestamp"),
        ("log_level_required", "cli_log_level"),
        ("log_to_file_required", "cli_log_to_file"),
        ("log_file_path", "cli_log_file_path"),
        ("log_rotation_required", "cli_log_rotation"),
        ("dry_run_flag_required", "cli_dry_run_flag"),
    ],
    "GATE_CONFORMANCE": [
        ("gate_registry_required", "gate_registry_required"),          # 恒等对
        ("gate_run_order", "gate_run_order"),                          # 恒等对
        ("gate_fail_closed", "gate_fail_closed"),                      # 恒等对
        ("gate_error_message_required", "gate_error_message_required"),# 恒等对
        ("gate_error_code_required", "gate_error_code_required"),      # 恒等对
        ("gate_log_result_required", "gate_log_result"),
        ("gate_cache_result_required", "gate_cache_result"),
        ("gate_skip_allowlist", "gate_skip_allowlist"),                # 恒等对
    ],
    "SIGNAL_EGRESS_CONFORMANCE": [
        ("single_exit_required", "signal_egress_single_exit"),
        ("validator_required", "signal_egress_validator"),
        ("schema_required", "signal_egress_schema"),
        ("required_fields", "signal_egress_fields"),
        ("no_direct_order_call", "signal_egress_no_direct_order"),
        ("log_required", "signal_egress_log"),
        ("replayable_required", "signal_egress_replayable"),
    ],
    "ENGINE_CONFORMANCE": [
        ("required_interface", "engine_required_interface"),
        ("init_signature", "engine_init_signature"),
        ("on_bar_signature", "engine_on_bar_signature"),
        ("on_order_update_required", "engine_on_order_update"),
        ("state_persist_required", "engine_state_persist"),
        ("state_restore_required", "engine_state_restore"),
    ],
    "EXECUTION_MODEL": [
        ("order_confirm_required", "exec_model_order_confirm"),
        ("position_sync_required", "exec_model_position_sync"),
        ("cash_sync_required", "exec_model_cash_sync"),
        ("slippage_model_required", "exec_model_slippage_model"),
        ("commission_model_required", "exec_model_commission_model"),
    ],
    "ORDER_PORT_CONFORMANCE": [
        ("required_methods", "order_port_required_methods"),
        ("send_order_signature", "order_port_send_order"),
        ("cancel_order_signature", "order_port_cancel_order"),
        ("query_position_signature", "order_port_query_position"),
        ("query_cash_signature", "order_port_query_cash"),
    ],
    "CACHE_GOVERNANCE": [
        ("dir_layout_required", "cache_dir_layout"),
        ("file_naming_required", "cache_file_naming"),
        ("manifest_file_name", "cache_manifest_file"),
        ("manifest_format", "cache_manifest_format"),
        ("ttl_field_name", "cache_ttl_field"),
        ("invalidate_on_miss_required", "cache_invalidate_on_miss"),
    ],
    "OPTION_VALUATION_GUARD": [
        ("required", "option_valuation_required"),
        ("model_required", "option_valuation_model"),
        ("greeks_required", "option_valuation_greeks"),
        ("no_static_strike_price", "option_valuation_no_static_strike"),
    ],
    "REPORT_CONFORMANCE": [
        ("required_fields", "report_required_fields"),
        ("timestamp_field", "report_timestamp_field"),
        ("spec_version_field", "report_spec_version_field"),
        ("run_id_field", "report_run_id_field"),
        ("format_required", "report_format"),
    ],
    "REPORT_ARCHIVE_CONFORMANCE": [
        ("archive_dir_required", "report_archive_dir"),
        ("archive_naming_required", "report_archive_naming"),
        ("archive_immutable", "report_archive_immutable"),
    ],
    "REPORT_LONG_TERM": [
        ("index_file_required", "report_long_term_index"),
        ("index_required_fields", "report_long_term_index_fields"),
        ("reproducible_required", "report_long_term_reproducible"),
    ],
    "DISCLOSURE_CONFORMANCE": [
        ("required_fields", "disclosure_required_fields"),
        ("watermark_required", "disclosure_watermark"),
        ("no_forward_looking_claim", "disclosure_no_forward_looking"),
    ],
    "INDICATOR_HARDENING": [
        ("na_propagation_required", "indicator_na_propagation"),
        ("raise_on_short_window", "indicator_raise_on_short_window"),
        ("window_check_required", "indicator_window_check"),
        ("min_periods_required", "indicator_min_periods"),
    ],
    "INDICATOR_WARMUP_GUARD": [
        ("warmup_required", "warmup_required"),                        # 恒等对
        ("min_bars_required", "warmup_min_bars"),
        ("raise_on_insufficient", "warmup_raise_on_insufficient"),
    ],
    "SNAPSHOT_PIT_GUARD": [
        ("pit_required", "snapshot_pit_required"),
        ("pit_index_source", "snapshot_pit_index_source"),
        ("pit_date_field", "snapshot_pit_date_field"),
        ("pit_members_field", "snapshot_pit_members_field"),
        ("no_future_data_leak", "snapshot_no_future_data"),
    ],
    "SPEC_PROVENANCE": [
        ("authority_field", "spec_provenance_authority"),
        ("draft_marker_field", "spec_provenance_draft_marker"),
    ],
    "CONFIG_SURFACE": [
        ("algo_id", "surface_algo_id"),
        ("dump_file", "surface_dump_file"),
    ],
    "BACKTEST_DEFAULTS": [
        ("default_cash", "backtest_default_cash"),
        ("default_commission", "backtest_default_commission"),
        ("default_slippage", "backtest_default_slippage"),
    ],
    "RISK": [
        ("max_position_pct", "risk_max_position_pct"),
        ("max_drawdown_pct", "risk_max_drawdown_pct"),
    ],
}


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "config.py"
    dst = sys.argv[2] if len(sys.argv) > 2 else "config.renamed.py"
    text = io.open(src, encoding="utf-8").read()
    tree = ast.parse(text)

    nodes = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            nodes[n.targets[0].id] = n

    # v3.52 标准 30 块 = 改名作用域（含换入的 BACKTEST_DEFAULTS/EXECUTION_MODEL/RISK）。
    # surface 是平面集合不看块归属；实测映射的块头与本机实际落块不一致（如
    # must_report_raw_and_bound 实际在 SUITE、baseline_anchored_to_historical_peak 在 SYSTEM），
    # 故按键名在作用域内全局收集出现点，按映射顺序逐个消费。
    SCOPE = [
        "SYSTEM_CONFORMANCE", "CLI_CONFORMANCE", "SPEC_VERSION_CHECK", "GATE_CONFORMANCE",
        "SIGNAL_EGRESS_CONFORMANCE", "ENGINE_CONFORMANCE", "LIVE_SAFETY", "EXECUTION_MODEL",
        "ORDER_PORT_CONFORMANCE", "DATA_LONG_TERM", "DATA_SOURCE_ADAPTER_GUARD", "CACHE_GOVERNANCE",
        "OPTION_VALUATION_GUARD", "REPORT_CONFORMANCE", "REPORT_ARCHIVE_CONFORMANCE", "REPORT_LONG_TERM",
        "DISCLOSURE_CONFORMANCE", "UNIVERSE_RESOLUTION_GUARD", "INDICATOR_HARDENING",
        "INDICATOR_WARMUP_GUARD", "SNAPSHOT_PIT_GUARD", "EMPTY_REASON_PROVENANCE", "SPEC_DRAFT_PERMISSION",
        "SUITE_COVERAGE_GUARD", "NONDETERMINISTIC_SCRIPT_GUARD", "ACCEPTANCE_GOVERNANCE",
        "SPEC_PROVENANCE", "CONFIG_SURFACE", "BACKTEST_DEFAULTS", "RISK",
    ]

    # 展平映射：old -> [new, ...]（保持发布方顺序，含恒等对占位）
    flat = {}
    for block, pairs in RENAME_MAP.items():
        for (o, n) in pairs:
            if o != n:
                flat.setdefault(o, []).append((block, n))

    # 收集作用域内每个源键名的全部出现点（文档顺序）
    occurrences = {}   # old -> [(block, key_node), ...]
    for block in SCOPE:
        node = nodes.get(block)
        if node is None:
            continue
        wanted = set(flat)
        for d in ast.walk(node.value):
            if isinstance(d, ast.Dict):
                for k in d.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str) and k.value in wanted:
                        occurrences.setdefault(k.value, []).append((block, k))

    edits, applied, missing = [], [], []
    for old, targets in flat.items():
        occ = occurrences.get(old, [])
        if len(occ) < len(targets):
            missing.append((old, "作用域内出现 %d 次 < 映射 %d 条" % (len(occ), len(targets))))
        for (block, new), (occ_block, k_node) in zip(targets, occ):
            edits.append((k_node.lineno - 1, k_node.col_offset,
                          k_node.end_lineno - 1, k_node.end_col_offset, repr(new)))
            applied.append((occ_block, old, new))
        for (occ_block, _k) in occ[len(targets):]:
            missing.append((old, "%s 块内多余出现点未消费" % occ_block))

    lines = text.split("\n")

    def to_char(line_no0, byte_col):
        if not (0 <= line_no0 < len(lines)):
            return byte_col
        return len(lines[line_no0].encode("utf-8")[:byte_col].decode("utf-8", "ignore"))

    edits = [(sl, to_char(sl, sc), el, to_char(el, ec), new) for (sl, sc, el, ec, new) in edits]
    edits.sort(key=lambda e: (e[0], e[1]), reverse=True)
    for (sl, sc, el, ec, new) in edits:
        if sl == el:
            lines[sl] = lines[sl][:sc] + new + lines[sl][ec:]
        else:
            lines[sl] = lines[sl][:sc] + new + lines[el][ec:]
            for i in range(sl + 1, el + 1):
                lines[i] = None
    out = "\n".join(l for l in lines if l is not None)
    ast.parse(out)  # 改名后必须仍是合法 Python
    io.open(dst, "w", encoding="utf-8").write(out)

    print("written: %s" % dst)
    print("  实际改名: %d 处" % len(applied))
    print("  恒等对(跳过): %d" % sum(1 for bs in RENAME_MAP.values() for (o, n) in bs if o == n))
    if missing:
        print("  ⚠ 未命中/异常 %d 条:" % len(missing))
        for item in missing:
            print("    %s" % (item,))


if __name__ == "__main__":
    main()
