#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v3.49 -> v3.52 结构与判据对齐（不覆盖原文件，默认输出 config.v352.py）。

只做 5 件事（业务块、业务键一律不动）：
  1. SPEC_VERSION 值 -> "v3.52"
  2. SPEC_VERSION_CHECK.must_contain_markers -> v3.52 标准列表（含 13.0.21/22/23）
  3. CONFIG_SURFACE.surface_recurse_blocks -> v3.52 标准白名单（严格 30 块）
  4. 5 个治理块补齐 v3.52 新增的 47 个顶层键（只增，不改已有键的值）
  5. 5 个顶层常量：缺则追加到文件末尾（本机已有则原样跳过）

用法：
  python3 apply_v352_alignment.py                 # config.py -> config.v352.py
  python3 apply_v352_alignment.py SRC DST          # 指定输入输出
"""
import ast
import io
import pprint
import sys

RECURSE_BLOCKS = [
    "SYSTEM_CONFORMANCE", "CLI_CONFORMANCE", "SPEC_VERSION_CHECK", "GATE_CONFORMANCE",
    "SIGNAL_EGRESS_CONFORMANCE", "ENGINE_CONFORMANCE", "LIVE_SAFETY", "EXECUTION_MODEL",
    "ORDER_PORT_CONFORMANCE", "DATA_LONG_TERM", "DATA_SOURCE_ADAPTER_GUARD", "CACHE_GOVERNANCE",
    "OPTION_VALUATION_GUARD", "REPORT_CONFORMANCE", "REPORT_ARCHIVE_CONFORMANCE", "REPORT_LONG_TERM",
    "DISCLOSURE_CONFORMANCE", "UNIVERSE_RESOLUTION_GUARD", "INDICATOR_HARDENING",
    "INDICATOR_WARMUP_GUARD", "SNAPSHOT_PIT_GUARD", "EMPTY_REASON_PROVENANCE", "SPEC_DRAFT_PERMISSION",
    "SUITE_COVERAGE_GUARD", "NONDETERMINISTIC_SCRIPT_GUARD", "ACCEPTANCE_GOVERNANCE",
    "SPEC_PROVENANCE", "CONFIG_SURFACE", "BACKTEST_DEFAULTS", "RISK",
]

MARKERS = [
    "13.0 开工前置", "13.0.13", "13.0.14", "13.0.15", "13.0.16", "13.0.17", "13.0.18",
    "13.0.19", "13.0.20", "13.0.21", "13.0.22", "13.0.23", "13.13 收尾总检",
]

NEW_KEYS = {
    "CONFIG_SURFACE": {
        "business_key_pattern_excluded": True,
        "compare_baseline_dump_per_version_required": True,
        "compare_requires_same_algo_id": True,
        "compare_requires_same_spec_version": True,
        "compare_requires_same_whitelist": True,
        "cross_version_compare_action": 'refuse',
        "dir_based_collection_forbidden": True,
        "dump_required_on_mismatch": True,
        "exclusion_must_cite_reason": True,
        "expected_counts_mismatch_action": 'warn_not_fail',
        "frozen_counts_are_outputs_not_criteria": True,
        "golden_vector_must_cover": ['ast_const', 'dict_recurse', 'list_not_recursed',
                                     'set_dedup', 'lf_join', 'trailing_lf'],
        "golden_vector_must_match_action": 'raise',
        "guard_block_name_pattern": '(_GUARD|_CONFORMANCE|_SAFETY|_GOVERNANCE|_PROVENANCE|_PERMISSION|_LONG_TERM|_HARDENING)$|^RISK$|^CONFIG_SURFACE$|^EXECUTION_MODEL$|^SPEC_VERSION_CHECK$',
        "hand_typed_expected_forbidden": True,
        "non_dict_block_action": 'raise',
        "surface_algo_id": 'cs-v1',
        "surface_algo_steps": ['S1 常量集 = 源码 AST 顶层赋值目标名中匹配 [A-Z][A-Z0-9_]* 者（不看运行期命名空间）',
                               'S2 键集 = surface_recurse_blocks 中每块递归其 dict（只下钻 dict，不下钻 list/tuple），取 str(键名)',
                               'S3 元素集 = sorted(set(常量集) | set(键集))，ASCII 升序',
                               'S4 规范化串 = 元素集以 LF 逐行连接 + 末尾一个 LF（UTF-8）',
                               'S5 sha256(规范化串)'],
        "surface_canonical_text_required": True,
        "surface_collection_must_be_ast_based": True,
        "surface_dump_file": 'config_surface.elements.txt',
        "surface_expected_counts": {'n_consts': 167, 'n_keys_raw': 644, 'n_keys_uniq': 591, 'n_elements': 757},
        "surface_golden_vector": {'consts': ['A', 'GOLDEN', 'Z'],
                                  'block': {'b': 1, 'A': {'c': 2}, 'L': [{'dropped': 9}]},
                                  'expected_elements': ['A', 'GOLDEN', 'L', 'Z', 'b', 'c'],
                                  'expected_sha256': '72bc8831bd7d585a256c74b123d952715841e4a5ed117addc179db183ef756b2'},
        "unlisted_guard_block_action": 'raise',
        "whitelist_completeness_required": True,
        "whitelist_exclusions": {'UNIVERSE_RESOLUTION_GUARD': {
            'exclude_key_pattern': '^\\d{6}(\\.(SH|SZ|BJ))?$',
            'keep_container_key': True,
            'reason': '业务样例的键是股票代码；治理面哈希只应随治理结构变化，不随示例代码增减而变'}},
    },
    "ACCEPTANCE_GOVERNANCE": {
        "chain_break_action": 'raise',
        "chain_genesis": 'GENESIS',
        "entry_field": 'entry_sha256',
        "ledger_entry_must_include_prev_sha256": True,
        "ledger_hash_chain_required": True,
        "migration_entry_requires_old_and_new_hash": True,
        "migration_hash_mismatch_requires_declaration": True,
        "migration_must_verify_old_hash_first": True,
        "prev_entry_field": 'prev_entry_sha256',
        "rehash_on_migrate_forbidden": True,
    },
    "SUITE_COVERAGE_GUARD": {
        "historical_peak_must_cite_evidence": True,
        "peak_evidence_file": 'suite_baselines.evidence.jsonl',
        "peak_evidence_schema": ['suite', 'historical_peak', 'spec_version', 'command', 'output_sha256'],
        "peak_from_declaration_action": 'raise',
    },
    "DATA_LONG_TERM": {
        "local_fallback_must_declare_today_missing": True,
        "missing_today_must_be_structured_field": True,
        "today_missing_field": 'today_missing_declared',
    },
    "SYSTEM_CONFORMANCE": {
        "config_surface_must_be_reproducible": True,
        "expected_value_provenance_required": True,
        "ledger_append_only_mechanically_enforced": True,
        "whitelist_completeness_enforced": True,
    },
}

EXTRA_CONSTS = {
    "SUPPORTED_KLINE_MARKETS": '''SUPPORTED_KLINE_MARKETS = {
    "daily":   ["cn_stock","cn_index","cn_fund","cn_cb","cn_bond","hk_stock","us_stock","crypto","commodity","cn_future","cn_option","hk_option","us_option","fx","cn_reits","nav_product"],
    "minute":  ["cn_stock","cn_index","cn_future","cn_cb","crypto"],
}''',
    "DATA_SOURCE_META": '''DATA_SOURCE_META = {
    ("akshare",  "cn_stock", "daily"):  {"unit_volume": "股",   "adjust_supported": True,  "limit": 5000},
    ("akshare",  "cn_stock", "minute"): {"unit_volume": "手",   "adjust_supported": False, "limit": 1000},
    ("akshare",  "cn_index", "daily"):  {"unit_volume": "手",   "adjust_supported": False, "limit": 5000},
    ("baostock", "cn_stock", "daily"):  {"unit_volume": "股",   "adjust_supported": True,  "limit": None},
    ("baostock", "cn_stock", "minute"): {"unit_volume": "股",   "adjust_supported": False, "limit": None},
    ("tushare",  "cn_stock", "daily"):  {"unit_volume": "手",   "adjust_supported": True,  "limit": 8000},
    ("local",    "*",         "*"):     {"unit_volume": "local_adjusted", "adjust_supported": True, "limit": None},
}''',
    "QI_MONITOR_ALERTS": '''QI_MONITOR_ALERTS = {
    "reits_premium":     {"enabled": True, "check_every_minutes": 15},
    "neeq_zero_volume":  {"enabled": True, "lookback_days": 5},
    "amr_suitability":   {"enabled": True, "on_fail": "log_and_alert"},
}''',
    "QI_REITS_PREMIUM_THRESHOLDS": 'QI_REITS_PREMIUM_THRESHOLDS = {"warn_pct": 0.20, "hard_block_pct": 0.50}',
    "QI_NEEQ_ZERO_VOLUME_DAYS": 'QI_NEEQ_ZERO_VOLUME_DAYS = 5',
}


def kv_line(key, value, indent=4):
    s = pprint.pformat(value, width=90, sort_dicts=False)
    s = s.replace("\n", "\n" + " " * indent)
    return " " * indent + repr(key) + ": " + s + ",\n"


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "config.py"
    dst = sys.argv[2] if len(sys.argv) > 2 else "config.v352.py"
    text = io.open(src, encoding="utf-8").read()
    tree = ast.parse(text)

    nodes = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            nodes[n.targets[0].id] = n

    edits = []          # (start_line0, start_col, end_line0, end_col, new_text)

    def replace_value(node, new_text):
        v = node.value
        edits.append((v.lineno - 1, v.col_offset, v.end_lineno - 1, v.end_col_offset, new_text))

    # 1. SPEC_VERSION
    if "SPEC_VERSION" in nodes:
        replace_value(nodes["SPEC_VERSION"], '"v3.52"')

    # 2. must_contain_markers
    n_chk = nodes.get("SPEC_VERSION_CHECK")
    if n_chk is not None and isinstance(n_chk.value, ast.Dict):
        for k, val in zip(n_chk.value.keys, n_chk.value.values):
            if isinstance(k, ast.Constant) and k.value == "must_contain_markers":
                edits.append((val.lineno - 1, val.col_offset, val.end_lineno - 1, val.end_col_offset,
                              pprint.pformat(MARKERS, width=110)))

    # 3. surface_recurse_blocks
    n_cs = nodes.get("CONFIG_SURFACE")
    if n_cs is not None and isinstance(n_cs.value, ast.Dict):
        for k, val in zip(n_cs.value.keys, n_cs.value.values):
            if isinstance(k, ast.Constant) and k.value == "surface_recurse_blocks":
                edits.append((val.lineno - 1, val.col_offset, val.end_lineno - 1, val.end_col_offset,
                              pprint.pformat(RECURSE_BLOCKS, width=100)))

    # 4. 5 个块补键
    added = {}
    for blk, kv in NEW_KEYS.items():
        n = nodes.get(blk)
        if n is None or not isinstance(n.value, ast.Dict):
            print("[warn] 找不到块 %s（跳过）" % blk)
            continue
        have = set()
        for k in n.value.keys:
            try:
                have.add(ast.literal_eval(k))
            except Exception:
                pass
        miss = [(k, v) for k, v in kv.items() if k not in have]
        if not miss:
            continue
        added[blk] = [k for k, _ in miss]
        line0 = n.value.end_lineno - 1
        col = n.value.end_col_offset - 1          # 指向该块的收尾 '}'
        before = text.split("\n")[line0][:col]
        body = "".join(kv_line(k, v) for k, v in miss)
        if before.strip() == "":
            new = body
        else:
            sep = "\n" if before.rstrip().endswith(",") else ",\n"
            new = sep + body.rstrip("\n")
        edits.append((line0, col, line0, col, new))

    # 5. 常量追加
    miss_consts = [name for name in EXTRA_CONSTS if name not in nodes]

    # ast 的 col_offset 是 UTF-8 字节偏移，统一转成字符列，避免中文注释处切片错位
    lines = text.split("\n")

    def to_char(line_no0, byte_col):
        if not (0 <= line_no0 < len(lines)):
            return byte_col
        return len(lines[line_no0].encode("utf-8")[:byte_col].decode("utf-8", "ignore"))

    edits = [(sl, to_char(sl, sc), el, to_char(el, ec), new) for (sl, sc, el, ec, new) in edits]

    # 应用（从后往前，避免行号漂移）
    edits.sort(key=lambda e: (e[0], e[1]), reverse=True)
    for (sl, sc, el, ec, new) in edits:
        if sl == el:
            lines[sl] = lines[sl][:sc] + new + lines[sl][ec:]
        else:
            lines[sl] = lines[sl][:sc] + new + lines[el][ec:]
            for i in range(sl + 1, el + 1):
                lines[i] = None
    out = "\n".join(l for l in lines if l is not None)

    if miss_consts:
        out = out.rstrip("\n") + "\n\n\n# ==== v3.52：发布方漏发的顶层常量（本机已有则不会走到这里）====\n"
        out += "\n\n".join(EXTRA_CONSTS[c] for c in miss_consts) + "\n"

    io.open(dst, "w", encoding="utf-8").write(out)

    print("written: %s" % dst)
    print("  补键: " + (", ".join("%s+%d" % (b, len(v)) for b, v in added.items()) or "无（已齐）"))
    print("  补常量: " + (", ".join(miss_consts) or "无（已存在）"))


if __name__ == "__main__":
    main()
