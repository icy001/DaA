# -*- coding: utf-8 -*-
"""规格版本自校验（config.SPEC_VERSION_CHECK 的唯一消费者）。

教训：连「规格」本身都活在副本上，人肉版本号核对会失效；必须机器校验 fail-closed。
本模块只看两件事：指令集文件里的 ``<!-- spec_version: vX.Y -->`` 头，与
``config.SPEC_VERSION`` 是否一致。对不上直接 raise，禁止静默降级。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

import config

_VERSION_RE = re.compile(r"^v(\d+)\.(\d+)")
_CONST_RE = re.compile(r"[A-Z][A-Z0-9_]*")

# v3.54 / 13.0.25 ③：口径键值指纹——cs-v1 结构哈希 ignore_values=True 只守键名
# 不守值，基准/费率/保证金率等「口径键」的值级变更（如 000300→H00300 令超额摆动
# 17.29pp）在结构哈希下毫无告警。本指纹对口径键的【取值】做稳定序列化哈希，
# 与结构哈希互补：两机对拍必含 config_values.sha256；值级变更必须登记验收单
# 「基准口径登记表」（谁/何时/为何/新旧超额对比）。
VALUE_FINGERPRINT_KEYS = [
    "BENCHMARK",              # 基准口径（H00300 全收益 ↔ 策略税前含息，绑定声明见验收单）
    "DEFAULT_ADJUST",         # 全局默认复权口径
    "INITIAL_CASH",           # 绩效分母
    "EXECUTION_MODEL",        # 滑点/撮合基准/量限（值级变化直接影响成交模拟）
    "RISK",                   # 熔断阈值/单票上限/费率相关风控参数
    "CN_FUTURES_VARIETY",     # 期货合约规格（乘数/保证金率/tick/涨跌停/开平平今费率——值级口径）
    "FUTURE_BENCHMARK_MAP",   # 期货基准映射（股指→全收益指数；禁止跨资产混用的值级守护）
    "LIVE_SAFETY",            # live_allowed_markets 白名单等实盘安全参数
    "HK_STOCK_CONFORMANCE",   # 港股标的规格（每手/价位分表/印花税豁免/事件源——值级口径）
]


def _stable(obj) -> str:
    """口径键值的稳定序列化（dict/set 排序、容器递归；标量取 type:值 兜底）。"""
    if isinstance(obj, dict):
        return "{" + ",".join(f"{k}:{_stable(v)}" for k, v in sorted(obj.items())) + "}"
    if isinstance(obj, (set, frozenset)):
        return "[" + ",".join(sorted(_stable(v) for v in obj)) + "]"
    if isinstance(obj, (list, tuple)):
        return "(" + ",".join(_stable(v) for v in obj) + ")"
    return f"{type(obj).__name__}:{obj}"


def compute_value_fingerprint() -> Dict[str, object]:
    """口径键值指纹（v3.54 / 13.0.25 ③）：返回 {per_key, sha256, keys}。

    结构哈希（cs-v1）守键名、本指纹守取值——两件互补，缺一不可。
    """
    import hashlib as _hl
    per_key, payload = {}, []
    for key in VALUE_FINGERPRINT_KEYS:
        value = getattr(config, key, None)
        h = _hl.sha256(_stable(value).encode("utf-8")).hexdigest()
        per_key[key] = h
        payload.append(f"{key}={h}")
    sha = _hl.sha256("|".join(payload).encode("utf-8")).hexdigest()
    return {"keys": list(VALUE_FINGERPRINT_KEYS), "per_key": per_key,
            "sha256": sha}


def write_value_fingerprint(root: Path = None) -> Path:
    """落盘 config_values.sha256（首行总指纹，随后逐键指纹便于定位变更键）。"""
    base = Path(root or config.BASE_DIR)
    fp = compute_value_fingerprint()
    lines = [f"{fp['sha256']}  config_values (algo=values-v1)"]
    lines += [f"{h}  {k}" for k, h in fp["per_key"].items()]
    path = base / "config_values.sha256"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _conf() -> dict:
    return dict(config.SPEC_VERSION_CHECK or {})


def _provenance() -> dict:
    return dict(getattr(config, "SPEC_PROVENANCE", None) or {})


def _draft_permission() -> dict:
    from core.gov_compat import gov
    return gov("SPEC_DRAFT_PERMISSION")


def validate_mode(mode: str) -> str:
    """运行模式封闭白名单校验（v3.49 / 13.0.20 ④）：必须在查 mode_matrix **之前**。

    病态：v3.48 靠「矩阵 miss + default=deny」碰巧拦住；只要代码写成
    ``.get(mode, default)``、或矩阵里多一个宽松条目，未登记模式就会 fail-open。
    现在白名单先行：带空格笔误（``"liv "``）、大小写别名以外的自定义串
    （``"prod_live"``）一律 raise，不做 strip/纠正——纠正本身就是猜。
    """
    perm = _draft_permission()
    valid = [str(x) for x in (perm.get("valid_modes") or [])]
    raw = "" if mode is None else str(mode)
    m = raw.lower()
    if not valid or not perm.get("valid_mode_set_required", True):
        return m
    if m not in valid:
        action = str(perm.get("invalid_mode_action") or "raise")
        msg = (f"未登记运行模式 {raw!r}：合法值只有 {valid}"
               f"（invalid_mode_action={action}）；带空格/拼写笔误/自定义字符串一律拒绝，"
               "禁止靠字典 miss 或 .get(mode, default) 兜底")
        if action == "raise":
            raise ValueError(msg)
    return m


def is_draft_blocked_mode(mode: str) -> bool:
    """draft 规格下该运行模式是否必须 raise（v3.49 / 13.0.20 ④）。

    先过封闭白名单 ``valid_modes``（未知模式 → raise），再查 ``mode_matrix``；
    矩阵命中按值处置，未命中按 ``mode_matrix_default="deny"`` 兜底。
    ``blocked_modes``/``allowed_modes`` 一律由矩阵派生，禁止另写一份清单。
    """
    perm = _draft_permission()
    if not perm:
        m = str(mode or "").lower()
        return bool(_provenance().get("block_live_on_draft", True)) and \
            m in {"live", "live_sim", "paper"}
    m = validate_mode(mode)
    matrix = {str(k).lower(): str(v).lower()
              for k, v in (perm.get("mode_matrix") or {}).items()}
    if m in matrix:
        return matrix[m] == "raise"
    return str(perm.get("mode_matrix_default") or "deny").lower() == "deny"


def is_draft() -> bool:
    """正文是否施工方自撰的草稿（v3.46 / 13.0.17）。

    哈希只能证明「文件没被人改过」；作者=登记者时它证明不了「这是权威规格」。
    非 reviewer_published 一律按 draft 处理，draft 的哈希只认 spec_drafts.sha256。
    """
    prov = _provenance()
    # v3.52 裁定：authority=reviewer 即发布方正式发布；其余（draft_self_authored 等）一律草稿/黄灯
    return bool(prov) and str(prov.get("authority") or "") not in ("reviewer", "reviewer_published")


def find_spec_files(root: Path = None) -> List[Path]:
    """按 glob 找指令集文件（兼容 ``...-2.md`` 之类的副本命名）。"""
    base = Path(root or config.BASE_DIR)
    globs = _conf().get("command_file_globs") or [_conf().get("command_file_glob") or "*指令集*.md"]
    if isinstance(globs, str):
        globs = [globs]
    return sorted({p for g in globs for p in base.glob(g)})


def read_header_version(path: Path) -> Optional[str]:
    """读取 ``<!-- spec_version: vX.Y -->`` 头；没有则返回 None。"""
    marker = _conf().get("version_header_marker") or "<!-- spec_version:"
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if marker in line:
                text = line.split(marker, 1)[1]
                return text.replace("-->", "").strip() or None
    return None


def is_compatible(header: str, expected: str = None) -> bool:
    """允许 -draft 等后缀；主版本号必须完全一致。"""
    expected = expected or config.SPEC_VERSION
    if not header:
        return False
    if str(header).strip() == str(expected).strip():
        return True
    suffixes = _conf().get("allow_suffix") or []
    for suffix in suffixes:
        if str(header).strip() == f"{expected}{suffix}":
            return True
    return False


def compute_sha256(path: Path) -> str:
    """流式计算文件 sha256（大文件不整读进内存）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_file_path(root: Path = None) -> Path:
    base = Path(root or config.BASE_DIR)
    prov = _provenance()
    # v3.46：draft 只认 spec_drafts.sha256，绝不读写发布哈希 spec_content.sha256，
    # 否则「自撰正文 + 自登记哈希」又能把 check-config 刷成绿灯。
    name = prov.get("draft_hash_file") if is_draft() else None
    name = name or prov.get("published_hash_file") or _conf().get("content_hash_file") \
        or "spec_content.sha256"
    return base / name


def read_expected_hash(path: Path) -> Optional[str]:
    """从 sha256sum 风格文件里取第一个 64 位十六进制串；没有则 None。"""
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"\b([0-9a-fA-F]{64})\b", text)
    return match.group(1).lower() if match else None


def verify_content_hash(spec_path: Path, root: Path = None) -> Dict[str, object]:
    """校验正文哈希：登记值与实际值不一致 / 缺少登记文件都算不通过。

    边界：只能检出「与登记哈希不符」，检不出「两边都忘了更新」——根治仍是单一权威副本。
    """
    conf = _conf()
    if not conf.get("content_hash_required"):
        return {"ok": True, "content_hash_checked": False}
    reg = hash_file_path(root)
    expected = read_expected_hash(reg)
    actual = compute_sha256(spec_path)
    out: Dict[str, object] = {
        "content_hash_checked": True, "content_sha256": actual,
        "expected_sha256": expected, "content_hash_mismatch": False,
        "draft": is_draft(), "hash_file": reg.name,
    }
    if expected is None:
        out.update(ok=False, reason=(
            f"缺少规格正文哈希 {reg.name}（content_hash_required=True）："
            f"投递指令集时必须一并附带 {actual}  {spec_path.name}"))
        return out
    if expected != actual:
        out.update(ok=False, content_hash_mismatch=True, reason=(
            f"规格正文哈希不符：登记={expected[:12]}… 实际={actual[:12]}…"
            f"（登记文件 {reg.name}）；"
            "版本号相同但正文已改（版本号被复用），禁止视为通过"))
        return out
    out.update(ok=True, reason="正文哈希一致" if not out["draft"]
               else f"正文哈希一致（草稿口径：{reg.name}）")
    return out


def _ledger_path(root: Path = None) -> Path:
    from core.gov_compat import gov
    conf = gov("ACCEPTANCE_GOVERNANCE")
    return Path(root or config.BASE_DIR) / (
        conf.get("hash_ledger_file") or "acceptance_scripts.ledger.jsonl")


def _read_ledger(path: Path):
    """读追加式账本（⑥）：首行 meta + 五元组条目行。返回 (meta, {path: 末条}, problems)。

    旧映射表的漏洞：删测试 = 删一行 = 全过。账本只追加（hash_ledger_append_only），
    改行/删行/坏 JSON 都必须暴露；删测试须追 {"action":"delete"} 且带 reason。
    """
    from core.gov_compat import gov
    conf = gov("ACCEPTANCE_GOVERNANCE")
    schema = list(conf.get("ledger_entry_schema")
                  or ["path", "sha256", "action", "spec_version", "reason"])
    actions = tuple(conf.get("ledger_action_values") or ("register", "update", "delete"))
    meta, entries, problems = None, {}, []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError as exc:
        return None, {}, [f"账本读取失败：{exc}"]
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"账本第 {i + 1} 行不是合法 JSON（禁止改行/删行）：{exc}")
            continue
        if not isinstance(rec, dict):
            problems.append(f"账本第 {i + 1} 行不是对象")
            continue
        if rec.get("meta"):
            if i != 0:
                problems.append("meta 行只能出现在账本首行")
            meta = rec
            continue
        missing = [k for k in schema if k not in rec]
        if missing:
            problems.append(f"账本第 {i + 1} 行缺五元组字段 {missing}（ledger_entry_schema）")
            continue
        if rec.get("action") not in actions:
            problems.append(f"账本第 {i + 1} 行 action={rec.get('action')!r} 不在 {list(actions)}")
            continue
        if rec.get("action") == "delete" and conf.get("delete_requires_reason", True) \
                and not str(rec.get("reason") or "").strip():
            problems.append(f"账本第 {i + 1} 行 delete 缺 reason（delete_requires_reason）")
            continue
        entries[str(rec.get("path"))] = rec
    return meta, entries, problems


def verify_acceptance_scripts(root: Path = None) -> Dict[str, object]:
    """⑥ 验收脚本哈希校验（账本制，v3.48 / 13.0.19）。

    权威来源是追加式账本 ``acceptance_scripts.ledger.jsonl``：config 里的
    ``script_hashes`` 只是登记索引（哪些脚本受管），比对一律以账本末条为准；
    删测试须追 delete 条目，已删脚本复活 / 账本缺记录 / 来源自证都不通过。
    """
    from core.gov_compat import gov
    conf = gov("ACCEPTANCE_GOVERNANCE")
    if not conf.get("script_hash_locked"):
        return {"ok": True, "script_hash_checked": False}
    base = Path(root or config.BASE_DIR)
    declared = {str(k) for k in (conf.get("script_hashes") or {})}
    ledger = _ledger_path(base)
    if not ledger.exists():
        return {"ok": False, "script_hash_checked": True, "hash_file": ledger.name,
                "mismatches": [f"缺少哈希账本 {ledger.name}（hash_ledger_append_only=True）："
                               "旧映射表已冻结（legacy_manifest_frozen），权威来源是追加式账本"],
                "reason": f"缺少哈希账本 {ledger.name}"}
    meta, entries, problems = _read_ledger(ledger)
    meta_authority = (meta.get("meta") or {}).get("authority") if meta else None
    if conf.get("ledger_meta_authority_required", True):
        if not meta:
            problems.append(f"{ledger.name} 缺首行 meta（authority 声明行）")
        elif str(meta_authority or "") != str(conf.get("script_hash_authority") or ""):
            problems.append(
                f"账本来源自证：meta.authority={meta_authority!r}，"
                f"而 config 自称 {conf.get('script_hash_authority')!r}；"
                "作者=登记者时不得把级别往上写")
    if conf.get("ledger_must_cover_all_registered_scripts", True):
        for rel in sorted(declared):
            if rel not in entries:
                problems.append(f"{rel}: 未在账本 {ledger.name} 登记（config 自填哈希不生效）")
    # ---- v3.49 / 13.0.20 ③：账本必须覆盖 glob 命中的全部验收脚本 ----
    # v3.48 只登记 2 条，而 glob 命中 40+ 个文件：未登记的脚本改了没人知道。
    script_globs = [str(g) for g in (conf.get("script_globs") or [])]
    globbed = sorted({p.relative_to(base).as_posix()
                      for g in script_globs for p in base.glob(g) if p.is_file()})
    if conf.get("ledger_must_cover_all_script_globs", True):
        for rel in globbed:
            if rel not in entries:
                problems.append(
                    f"{rel}: glob 命中但账本未登记（unregistered_script_action="
                    f"{conf.get('unregistered_script_action', 'fail')}）")
    for rel, rec in sorted(entries.items()):
        if rel not in declared and rel not in globbed:
            continue          # 账本可含已退役脚本；只校验仍在受管范围的
        path = base / rel
        if rec.get("action") == "delete":
            if path.exists():
                problems.append(
                    f"{rel}: 账本已记 delete 但文件仍存在（script_deletion_counts_as_change）")
            continue
        actual = compute_sha256(path) if path.exists() else None
        if actual != str(rec.get("sha256") or "").lower():
            problems.append(
                f"{rel}: 账本登记={str(rec.get('sha256'))[:12]}… 实际={str(actual)[:12]}…"
                "（改了验收脚本必须由非施工方追加 update 条目）")
    return {
        "ok": not problems,
        "script_hash_checked": True,
        "hash_file": ledger.name,
        "authority": meta_authority,
        "status": str(conf.get("script_hash_draft_status") or "yellow"),
        "mismatches": problems,
        "globbed": len(globbed),
        "registered": len(entries),
        "coverage": f"{len([r for r in globbed if r in entries])}/{len(globbed)}",
        "reason": "验收脚本哈希与账本一致" if not problems else "；".join(problems),
    }


# ==================== v3.50 / 13.0.21：cs-v1 配置面算法（可复现） ====================
# 教训：v3.49 钉死了「哪些元素进集合」，没钉死「集合怎么变成哈希」——登记值
# d7df508d… 用七种自然读法都复现不出，连看守者都算不出的期望值无法跨机比对。
# cs-v1 把 S1~S5 全部定死，并用黄金向量自证；算法对不上就不要比数据。

SURFACE_ALGO_ID = "cs-v1"
# 黄金向量：{"b":1,"A":{"c":2},"L":[{"dropped":9}]} + 常量 ["A","GOLDEN","Z"]
# 期望元素 ["A","GOLDEN","L","Z","b","c"]（L 内的 dropped 是列表元素，不得下钻；
# "A" 同时是常量与块内键，强制覆盖 S3 的并集去重路径——v3.51 ④）
SURFACE_GOLDEN_ELEMENTS = ["A", "GOLDEN", "L", "Z", "b", "c"]
SURFACE_GOLDEN_SHA256 = \
    "72bc8831bd7d585a256c74b123d952715841e4a5ed117addc179db183ef756b2"
# S1~S5（与指令集 13.0.21 逐字一致）
SURFACE_ALGO_STEPS = [
    "S1 常量集：AST 解析 config.py 顶层赋值（Assign/AnnAssign）中形如 [A-Z][A-Z0-9_]* 的名字，"
    "禁止 dir()/正则扫注释",
    "S2 键集：只对 surface_recurse_blocks 白名单块做递归，只收集 dict 的键；列表是取值，不展开",
    "S3 合并：常量集合 ∪ 键集合，去重后按 ASCII 升序排序",
    "S4 序列化：逐元素以 '\\n' 连接，末尾补一个 '\\n'",
    "S5 哈希：对 S4 的 UTF-8 字节取 sha256，十六进制小写",
]


def _ast_constants(source: str) -> list:
    """S1：从源码 AST 顶层赋值取常量名（不用 dir()，避免 import 进来的大写名混入）。"""
    import ast
    tree = ast.parse(source)
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and _CONST_RE.fullmatch(target.id):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and node.value is not None \
                and isinstance(node.target, ast.Name) and _CONST_RE.fullmatch(node.target.id):
            names.add(node.target.id)
    return sorted(names)


def _dict_keys_only(obj, rule: dict = None) -> set:
    """S2：只递归 dict 的键；列表元素不展开（列表是取值，不是结构）。

    v3.51 ②：先按该块的 whitelist_exclusions 剔业务键（键名与子树都不计、
    不下钻），与参考实现 tools/compute_config_surface_cs_v1.py 的 walk 逐字一致。
    """
    out: set = set()
    if not isinstance(obj, dict):
        return out
    pat = None
    eks = set()
    if rule:
        if rule.get("exclude_key_pattern"):
            pat = re.compile(rule["exclude_key_pattern"])
        eks = set(rule.get("exclude_keys", []))
    for k, v in obj.items():
        ks = str(k)
        if (pat and pat.match(ks)) or ks in eks:
            continue
        out.add(ks)
        out |= _dict_keys_only(v, rule)
    return out


def surface_elements(constants=None, blocks=None) -> list:
    """S3：常量 ∪ 键，去重排序（供哈希与 dump 共用同一份元素表）。"""
    if constants is None:
        source = Path(config.__file__).read_text(encoding="utf-8")
        constants = _ast_constants(source)
    if blocks is None:
        blocks = [str(b) for b in (dict(getattr(config, "CONFIG_SURFACE", None) or {})
                                   .get("surface_recurse_blocks") or [])]
    ex = (dict(getattr(config, "CONFIG_SURFACE", None) or {})
          .get("whitelist_exclusions") or {})
    keys: set = set()
    for name in blocks:
        keys |= _dict_keys_only(getattr(config, name, None), ex.get(name))
    return sorted(set(str(c) for c in constants) | keys)


def surface_digest(elements) -> str:
    """S4+S5：'\\n'.join(elements) + '\\n' 的 UTF-8 sha256。"""
    payload = "\n".join(str(e) for e in elements) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_surface_algorithm() -> Dict[str, object]:
    """黄金向量自证：算法先对，再比数据。"""
    got = surface_digest(SURFACE_GOLDEN_ELEMENTS)
    return {"ok": got == SURFACE_GOLDEN_SHA256, "algo": SURFACE_ALGO_ID,
            "golden_sha256": SURFACE_GOLDEN_SHA256, "actual_sha256": got}


def compute_config_surface() -> Dict[str, object]:
    """⑦ 配置面哈希（cs-v1）：只比结构（常量名 + 键名），不比取值。

    v3.49 的毛病是「算法可解释、不可复现」：元素集合定了，序列化与哈希口径没定，
    结果登记值谁都算不出。cs-v1 的 S1~S5 见 :data:`SURFACE_ALGO_STEPS`，并由
    :func:`verify_surface_algorithm` 用黄金向量自证——算法不过就不该拿去比数据。
    """
    conf = dict(getattr(config, "CONFIG_SURFACE", None) or {})
    ex = conf.get("whitelist_exclusions") or {}
    if not conf.get("enabled", True):
        return {"enabled": False}
    blocks = [str(b) for b in (conf.get("surface_recurse_blocks") or [])]
    if not blocks:
        raise RuntimeError(
            "CONFIG_SURFACE.surface_recurse_blocks 为空（白名单口径）："
            "递归范围必须逐名列出，不得用「guard 块」这类形容词做判据")
    missing = [b for b in blocks if not isinstance(getattr(config, b, None), dict)]
    if missing:
        action = str(conf.get("missing_recurse_block_action") or "raise")
        msg = f"白名单块在 config 中缺失或不是 dict：{missing}（两机对齐的前提是同一份集合）"
        if action == "raise":
            raise RuntimeError(msg)

    source = Path(config.__file__).read_text(encoding="utf-8")
    constants = _ast_constants(source)
    keys: set = set()
    for name in blocks:
        keys |= _dict_keys_only(getattr(config, name), ex.get(name))
    elements = sorted(set(constants) | keys)
    digest = surface_digest(elements)
    return {"enabled": True, "algo": SURFACE_ALGO_ID, "sha256": digest,
            "constants": len(constants), "keys": len(keys),
            "elements": len(elements), "blocks": len(blocks),
            "golden_ok": verify_surface_algorithm()["ok"]}


def surface_hash_path(root: Path = None) -> Path:
    conf = dict(getattr(config, "CONFIG_SURFACE", None) or {})
    return Path(root or config.BASE_DIR) / (
        conf.get("surface_hash_file") or "config_surface.sha256")


def surface_dump_path(root: Path = None) -> Path:
    """cs-v1 规范化元素表：comm -3 定位两机差异用的就是这份文件。"""
    conf = dict(getattr(config, "CONFIG_SURFACE", None) or {})
    return Path(root or config.BASE_DIR) / (
        conf.get("surface_dump_file") or "config_surface.elements.txt")


# 白名单完备性（④）：guard 类块若漏纳 = surface 失明；若误纳业务数据 = 治理面被污染。
# 这里只做「像 guard 却没进白名单」的单向扫描，避免把业务常量误判成守卫块。
_GUARD_NAME_TOKENS = ("GUARD", "CONFORMANCE", "GOVERNANCE", "SAFETY",
                      "PERMISSION", "PROVENANCE", "_CHECK")


def scan_unlisted_guard_blocks() -> Dict[str, object]:
    """列出「名字像治理/守卫块、是 dict、但不在白名单」的顶层常量。"""
    conf = dict(getattr(config, "CONFIG_SURFACE", None) or {})
    whitelist = {str(b) for b in (conf.get("surface_recurse_blocks") or [])}
    source = Path(config.__file__).read_text(encoding="utf-8")
    unlisted = [c for c in _ast_constants(source)
                if c not in whitelist
                and any(tok in c for tok in _GUARD_NAME_TOKENS)
                and isinstance(getattr(config, c, None), dict)]
    return {"ok": not unlisted, "unlisted": unlisted,
            "whitelist_total": len(whitelist),
            "reason": "白名单覆盖全部 guard 类块" if not unlisted
            else f"疑似漏纳 guard 块：{unlisted}（unlisted_guard_block_action=raise）"}


def write_surface_hash(root: Path = None) -> Dict[str, object]:
    """落盘配置面哈希 + 规范化元素表（两机对齐基线；由 check-config 打印）。"""
    surface = compute_config_surface()
    if not surface.get("enabled"):
        return surface
    path = surface_hash_path(root)
    path.write_text(
        f"{surface['sha256']}  config.py（{surface['algo']}：常量 {surface['constants']} + "
        f"白名单块 {surface['blocks']} 个递归键 {surface['keys']}，共 {surface['elements']} 元素；"
        "排序后 '\\n'.join + 尾换行再 sha256，只比结构不比取值）\n",
        encoding="utf-8")
    dump = surface_dump_path(root)
    dump.write_text("\n".join(surface_elements()) + "\n", encoding="utf-8")
    return surface


def verify_config_surface(root: Path = None) -> Dict[str, object]:
    """⑦ 登记值 vs 实算值：不一致 = 结构漂移（config 改了键而未登记）。

    cs-v1：先过黄金向量自证，算法不过直接 ok=False——算法没对齐时比哈希毫无意义。
    """
    golden = verify_surface_algorithm()
    surface = compute_config_surface()
    if not surface.get("enabled"):
        return {"ok": True, "checked": False, "golden_ok": golden["ok"]}
    if not golden["ok"]:
        return {"ok": False, "checked": True, "golden_ok": False,
                "sha256": surface["sha256"], "registered": None,
                "algo": SURFACE_ALGO_ID, "constants": surface["constants"],
                "keys": surface["keys"], "elements": surface["elements"],
                "reason": (f"{SURFACE_ALGO_ID} 黄金向量自证失败：期望 "
                           f"{golden['golden_sha256'][:12]}… 实算 "
                           f"{golden['actual_sha256'][:12]}…；算法未对齐，禁止拿哈希比数据")}
    path = surface_hash_path(root)
    registered = read_expected_hash(path) if path.exists() else None
    drift = registered is not None and registered != surface["sha256"]
    return {"ok": not drift, "checked": True, "golden_ok": True,
            "sha256": surface["sha256"], "registered": registered,
            "surface_file": path.name, "algo": SURFACE_ALGO_ID,
            "constants": surface["constants"], "keys": surface["keys"],
            "elements": surface["elements"],
            "reason": "配置面哈希与登记一致" if not drift else
                      (f"配置面结构漂移：登记={str(registered)[:12]}… 实算="
                       f"{surface['sha256'][:12]}…（改了 config 键结构须重算 "
                       f"{path.name}；两机对齐用 {surface_dump_path(root).name} 做 comm -3）")}


def check_spec_version(root: Path = None, raise_on_error: bool = True) -> Dict[str, object]:
    """返回 {ok, spec_version, header, file, reason}；失败时按配置 raise。

    v3.40：版本号之外再验正文哈希——同一版本号对应两份不同内容时，字符串比对会假绿。
    """
    conf = _conf()
    files = find_spec_files(root)
    result: Dict[str, object] = {
        "ok": False, "spec_version": config.SPEC_VERSION,
        "header": None, "file": None, "reason": "",
        "draft": is_draft(), "authority": _provenance().get("authority"),
    }
    if not files:
        result["reason"] = (
            f"未找到指令集文件（glob={conf.get('command_file_glob')}），"
            f"请把规格文件放到 {config.BASE_DIR} 后重试")
        if raise_on_error:
            raise RuntimeError(result["reason"])
        return result

    path = files[0]
    # v3.44：多副本并存必须报错——glob 命中多份时按排序静默取一份，等于哈希只锁住
    # 「碰巧排前」的那份，其余副本游离在校验之外（多副本 = 版本漂移根源，13.0.15）。
    if len(files) > 1:
        names = "、".join(p.name for p in files)
        result["reason"] = (
            f"目录下存在 {len(files)} 份指令集副本：{names}；"
            "只保留一份权威副本（其余移出本目录或删除）后重试")
        if raise_on_error:
            raise RuntimeError(result["reason"])
        return result
    header = read_header_version(path)
    result.update(file=path.name, header=header)

    if header is None:
        # v3.52 裁定：缺版本头 = 无法判定版本，fail-closed 直接 raise
        result["reason"] = (
            f"{path.name} 缺少版本头 {conf.get('version_header_marker')} vX.Y -->；"
            "规格未标注版本，无法机器校验")
        if raise_on_error:
            raise ValueError(result["reason"])
        return result
    if not is_compatible(header):
        # v3.52 裁定：有头但版本不匹配 → warn（提示升级，不 raise 不阻塞）
        result["reason"] = (
            f"规格版本不一致：指令集={header}，config.SPEC_VERSION={config.SPEC_VERSION}；"
            "请用与代码同版本的指令集覆盖后重试")
        result.update(ok=False, status="warn")
        return result
    else:
        # v3.44：版本头一致但正文缺关键章节标记 → 不通过（正文被裁剪后版本号不变照样拦）
        markers = conf.get("must_contain_markers") or []
        if markers:
            text = path.read_text(encoding="utf-8", errors="ignore")
            missing = [m for m in markers if m not in text]
            if missing:
                result["reason"] = (
                    f"{path.name} 缺少必备章节标记：{'、'.join(missing)}；"
                    "正文疑似被裁剪或混入旧版")
                # v3.52 收口：on_marker_missing 硬化为默认 raise（正文被裁剪必须拦截）；
                # 版本滚动期曾临时 warn，正式验收前已收回
                marker_policy = str(conf.get("on_marker_missing") or "raise").lower()
                if raise_on_error and marker_policy == "raise":
                    raise ValueError(result["reason"])
                result["markers_missing"] = missing
                result["marker_policy"] = marker_policy
                # warn：不 return，继续走正文哈希校验（哈希才是通过与否的判据）
        hash_result = verify_content_hash(path, root)
        result.update(hash_result)
        if hash_result["ok"]:
            if result.get("draft"):
                result.update(ok=True, status="yellow", reason=(
                    f"版本与草稿哈希一致，但正文来源={result.get('authority')}（非 reviewer_published）："
                    "哈希只能证明文件未被改动，不能证明其为权威规格；按黄灯处理"))
            else:
                result.update(ok=True, status="green", reason="规格版本与正文哈希一致")
            return result
        result["reason"] = hash_result["reason"]

    raise_on = conf.get(
        "on_content_hash_mismatch" if result.get("content_hash_mismatch")
        else "on_mismatch", "raise")
    if raise_on_error and raise_on == "raise":
        raise ValueError(str(result["reason"]))
    return result


def enforce_on_startup(mode: str = None) -> Dict[str, object]:
    """按运行模式接入启动自检：live/live_sim/paper 拦截，tooling/backtest 不拦。

    tooling 模式（回测、研究、数据维护）只返回带 reason 的结果，不 raise，
    避免规格升级期间把取数/回测全部锁死；真实资金与模拟盘路径必须 fail-closed。
    """
    conf = _conf()
    if not conf.get("enforce_on_startup"):
        return {"ok": True, "skipped": True, "reason": "enforce_on_startup=False"}
    if mode is None:
        from core import cli_gate
        mode = cli_gate.current_mode()
    mode = validate_mode(mode)          # v3.49 / 13.0.20 ④：白名单先行，未知模式直接 raise
    enforce_modes = [str(m).lower() for m in
                     (conf.get("enforce_modes") or ["live", "live_sim", "paper"])]
    # v3.47：draft 的权限判定优先于 enforce_modes 早退——否则把某个模式挪进
    # SPEC_DRAFT_PERMISSION.blocked_modes 也不会生效（早退先返回了 skipped）。
    if mode not in enforce_modes and not is_draft_blocked_mode(mode):
        result = check_spec_version(raise_on_error=False)
        result["skipped"] = True
        result["reason"] = f"tooling 模式 {mode} 不拦截：{result.get('reason')}"
        return result
    result = check_spec_version(raise_on_error=True)
    # v3.47：draft 不能只有「黄灯」没有权限——自撰规格拿到黄灯后照样能把实盘解锁。
    # 权限判定统一读 config.SPEC_DRAFT_PERMISSION（blocked_modes 拦 / allowed_modes 放）。
    if result.get("draft") and is_draft_blocked_mode(mode):
        msg = (f"规格正文为草稿（authority={result.get('authority')}），"
               f"SPEC_DRAFT_PERMISSION.mode_matrix 命中 raise（valid_modes 已先行校验）："
               f"{mode} 模式禁止使用未评审发布的规格；"
               f"请投递权威正文并登记 {_provenance().get('published_hash_file')}")
        if str(_draft_permission().get("on_blocked_mode") or "raise") == "raise":
            raise RuntimeError(msg)
        result.update(ok=False, reason=msg)
    return result
