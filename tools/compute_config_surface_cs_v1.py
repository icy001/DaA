# -*- coding: utf-8 -*-
"""cs-v1 参考实现：把「config 结构面」算成一个可复现的哈希。

口径（与 config.CONFIG_SURFACE.surface_algo_steps 一一对应）：
  S1 常量集 = 源码 AST 顶层赋值目标名中匹配 [A-Z][A-Z0-9_]* 者（不看运行期命名空间）
  S2 键集   = surface_recurse_blocks 每块递归其 dict（只下钻 dict，不下钻 list/tuple），取 str(键名)；
              并先按该块的 whitelist_exclusions 规则剔除业务键（v3.51）
  S3 元素集 = sorted(set(常量集) | set(键集))，ASCII 升序
  S4 规范化串 = 元素集以 LF 逐行连接 + 末尾一个 LF（UTF-8）
  S5 sha256(规范化串)

用法（v3.52 / 13.0.23 ① 修正：必须可参数化）：
  python3 compute_config_surface_cs_v1.py [PATH] [--dump PATH] [--check]
                                          [--legacy-v349 | --legacy-whitelist FILE]
  PATH        待测 config 文件（缺省 ./config.py；13.0.23 ①：禁止硬编码）
  --dump PATH 把规范化元素表写到 PATH（缺省不写，--check 时写 config_surface.elements.txt）
  --check     校验黄金向量（失败 exit 1）与冻结快照（仅 warn）
  --legacy-v349
              老版本 config 缺 CONFIG_SURFACE 元数据时，改用内置 v3.49 标准白名单
              （发布方 30 块）且不应用任何剔除规则
  --legacy-whitelist FILE
              同上，但白名单块名逐行取自 FILE（两机 v3.49 白名单不同，各用各的）
"""
import ast, hashlib, importlib.util, io, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CFG = os.path.join(ROOT, "config.py")
UP = re.compile(r"[A-Z][A-Z0-9_]*$")

# 发布方 v3.49/v3.52 标准白名单（--legacy-v349 内置用；v3.49→v3.52 白名单未变）
LEGACY_V349_BLOCKS = [
    "SYSTEM_CONFORMANCE", "CLI_CONFORMANCE", "SPEC_VERSION_CHECK", "GATE_CONFORMANCE",
    "SIGNAL_EGRESS_CONFORMANCE", "ENGINE_CONFORMANCE", "LIVE_SAFETY", "EXECUTION_MODEL",
    "ORDER_PORT_CONFORMANCE", "DATA_LONG_TERM", "DATA_SOURCE_ADAPTER_GUARD", "CACHE_GOVERNANCE",
    "OPTION_VALUATION_GUARD", "REPORT_CONFORMANCE", "REPORT_ARCHIVE_CONFORMANCE", "REPORT_LONG_TERM",
    "DISCLOSURE_CONFORMANCE", "UNIVERSE_RESOLUTION_GUARD", "INDICATOR_HARDENING",
    "INDICATOR_WARMUP_GUARD", "SNAPSHOT_PIT_GUARD", "EMPTY_REASON_PROVENANCE", "SPEC_DRAFT_PERMISSION",
    "SUITE_COVERAGE_GUARD", "NONDETERMINISTIC_SCRIPT_GUARD", "ACCEPTANCE_GOVERNANCE",
    "SPEC_PROVENANCE", "CONFIG_SURFACE", "BACKTEST_DEFAULTS", "RISK",
]


def load_config(path=CFG):
    sp = importlib.util.spec_from_file_location("cfg", path)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def collect_consts(path=CFG):
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    out = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and UP.match(t.id):
                    out.append(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and UP.match(node.target.id):
            out.append(node.target.id)
    return sorted(set(out))


def walk(obj, acc, path=None, rule=None):
    """只下钻 dict；rule 给出该块的业务键剔除规则（exclude_key_pattern / exclude_keys）。"""
    if not isinstance(obj, dict):
        return
    path = list(path) if path else []
    pat = None
    eks = set()
    if rule:
        if rule.get("exclude_key_pattern"):
            pat = re.compile(rule["exclude_key_pattern"])
        eks = set(rule.get("exclude_keys", []))
    for k, v in obj.items():
        ks = str(k)
        if (pat and pat.match(ks)) or ks in eks:
            continue                      # 业务键：键名与其子树都不计入（不下钻、不收集）
        acc.append(ks)
        walk(v, acc, path + [ks], rule)


def collect_keys(cfg, override_blocks=None, use_exclusions=True):
    acc = []
    if override_blocks is not None:
        blocks = override_blocks
        ex = {}
    else:
        blocks = cfg.CONFIG_SURFACE["surface_recurse_blocks"]
        ex = cfg.CONFIG_SURFACE.get("whitelist_exclusions") or {}
    for block in blocks:
        obj = getattr(cfg, block)
        if not isinstance(obj, dict):
            raise TypeError("白名单块必须是 dict（non_dict_block_action=raise）: %s" % block)
        walk(obj, acc, [], ex.get(block) if use_exclusions else None)
    return acc


def canonical(consts, keys):
    elems = sorted(set(consts) | set(keys))
    return "\n".join(elems) + "\n", elems


def compute(path=CFG, override_blocks=None):
    cfg = load_config(path)
    consts = collect_consts(path)
    keys = collect_keys(cfg, override_blocks=override_blocks)
    text, elems = canonical(consts, keys)
    return {
        "algo_id": (cfg.CONFIG_SURFACE.get("surface_algo_id", "cs-v1")
                    if isinstance(getattr(cfg, "CONFIG_SURFACE", None), dict) else "cs-v1"),
        "n_consts": len(consts),
        "n_keys_raw": len(keys),
        "n_keys_uniq": len(set(keys)),
        "n_elements": len(elems),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "canonical_text": text,
    }


def golden_check(cfg):
    gv = cfg.CONFIG_SURFACE["surface_golden_vector"]
    acc = []
    walk(gv["block"], acc)
    text, elems = canonical(gv["consts"], acc)
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    ok = (sha == gv["expected_sha256"]) and (elems == gv["expected_elements"])
    return ok, sha, elems


def main():
    # v3.52 / 13.0.23 ①：位置参数 PATH + --dump PATH + --check + --legacy-*
    args = sys.argv[1:]
    path, dump_path, check = CFG, None, False
    override = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--dump":
            i += 1
            dump_path = args[i]
        elif a == "--check":
            check = True
        elif a == "--legacy-v349":
            override = list(LEGACY_V349_BLOCKS)
        elif a == "--legacy-whitelist":
            i += 1
            override = [ln.strip() for ln in io.open(args[i], encoding="utf-8")
                        if ln.strip() and not ln.startswith("#")]
        else:
            path = a
        i += 1

    r = compute(path, override_blocks=override)
    print("[surface] algo=%s consts=%d keys_raw=%d keys_uniq=%d elements=%d"
          % (r["algo_id"], r["n_consts"], r["n_keys_raw"], r["n_keys_uniq"], r["n_elements"]))
    print("[surface] sha256=%s" % r["sha256"])
    dump = dump_path or os.path.join(ROOT, "config_surface.elements.txt")
    io.open(dump, "w", encoding="utf-8").write(r["canonical_text"])
    print("[surface] dump -> %s (%d lines)" % (dump, r["n_elements"]))
    if check:
        cfg = load_config(path)
        ok, gsha, gelems = golden_check(cfg)
        exp = (cfg.CONFIG_SURFACE.get("surface_expected_counts")
               if isinstance(getattr(cfg, "CONFIG_SURFACE", None), dict) else None)
        act = {"n_consts": r["n_consts"], "n_keys_raw": r["n_keys_raw"],
               "n_keys_uniq": r["n_keys_uniq"], "n_elements": r["n_elements"]}
        print("[golden] ok=%s sha256=%s elems=%s" % (ok, gsha, gelems))
        if exp == act:
            print("[frozen] match=True expected=%s" % (exp,))
        else:
            # v3.51：计数是【产物】不是【判据】——不匹配只 warn，不影响 exit code
            print("[frozen] mismatch (warn_not_fail; counts are outputs, not criteria)")
            print("         expected=%s" % (exp,))
            print("         actual  =%s" % (act,))
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
