#!/usr/bin/env python3
"""v2 调研文档机械核验器（两段式 + 内容断言 + 植入错误自测）。

用法：
    python3 docs/research/drafts-v2/verify-v2.py            # 正式核验
    python3 docs/research/drafts-v2/verify-v2.py --selftest # 植入错误自测

设计要点（对应 SKILL 要求）：
  1. 两段式：先从文档抽取被引用的 basename（约 96 个），再按名字索引仓库，
     避免全仓 2.3 万文件逐文件读行数导致 SIGTERM。
  2. 三层判定：FILE_NOT_FOUND（找不到文件）/ LINE_OOB（行号越界）/
     CONTENT_MISMATCH（行内断言不匹配）。第三层才是真正的"内容核验"。
  3. --selftest：把已知对/错的用例注入，确认核验器**能报错**。
     只报"0 问题"而不报"检查了多少条"的核验器等于没检查。
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOTS = {
    "gw": Path("/Users/w/Desktop/Model-Gateway"),
    "zc": Path("/Users/w/Desktop/01-关注的开源项目/ZCode"),
    "dsh": Path("/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts"),
}

DOC_DIR = Path("/Users/w/Desktop/Model-Gateway/docs/research")
DOCS = [
    "00-总览与阅读指引.md",
    "01-ZCode-模型参数与能力归一化机制.md",
    "02-DSH-多产品多账号资源池机制.md",
    "03-DSH-聚合模型输出面与可复用性.md",
    "04-网关-CLI对接模式设计.md",
    "05-网关改造落地方案.md",
    "06-参数归一化方案-从ZCode的不足到更优解.md",
    "07-交付核验与覆盖度审计.md",
]

# 目录剪枝：这些目录名一旦出现在路径里，整棵子树跳过
PRUNE_DIRS = {
    ".git", "node_modules", "dist", "build", "out", "__pycache__",
    ".venv", "venv", ".next", ".turbo", "coverage", ".cache",
    "tool-results", ".mypy_cache", ".pytest_cache", ".ruff_cache",
}
# 只保留真正可能被引用的文件扩展名，减少索引体量
KEEP_EXTS = {
    ".py", ".md", ".json", ".ts", ".tsx", ".js", ".jsx", ".yaml", ".yml",
    ".mdc", ".toml", ".wasm", ".css", ".html", ".command", ".txt", ".cfg",
    ".ini", ".sh", ".zsh",
}

EXTS = r"(?:py|md|json|ts|tsx|js|jsx|yaml|yml|mdc|toml|wasm|css|html|command)"
PAT = re.compile(r"`([A-Za-z0-9_\u4e00-\u9fff\-./]+\.%s):([0-9][0-9,\-/]*)`" % EXTS)

# ── 内容断言表：只覆盖"结论所依赖的关键行" ────────────────────────────────
# (仓库tag, 路径提示(可只写尾部若干段), 行号spec, 必须包含的片段(任一命中), 说明)
# 行号必须精确到"这句话真的在这一行"，不要写 1-999 这种宽区间 —— 宽区间等于没断言。
ASSERTIONS: list[tuple[str, str, str, list[str], str]] = [
    # ---- 网关本体（自研，最需要证据）----
    ("gw", "model_gateway/api/openai_compat.py", "36-44", ["def list_models"],
     "BUG-1 根因：list_models 入口"),
    ("gw", "model_gateway/api/openai_compat.py", "42", ["enabled"],
     "BUG-1 根因：只按 m.enabled 过滤（无可用资源检查）"),
    ("gw", "model_gateway/core/ir.py", "100-120", ["reasoning_effort"],
     "BUG-2 根因：inject_reasoning_into_body 覆盖 params"),
    ("gw", "model_gateway/core/resources.py", "120-144", ["pick_and_acquire"],
     "并发溢出选择器 pick_and_acquire"),
    ("gw", "model_gateway/core/resources.py", "63-64", ["available"],
     "ResourceState.available 判据"),
    ("gw", "model_gateway/core/scheduler.py", "223-232", ["_out_body"],
     "出站体构造 _out_body"),
    ("gw", "model_gateway/config/schemas.py", "1-255", ["class SystemModel"],
     "SystemModel 定义存在"),
    ("gw", "model_gateway/core/ir.py", "1-174", ["def merge_reasoning"],
     "三级推理参数合并入口"),
    # ---- ZCode ----
    ("zc", "model-option-map/src/types.ts", "8", ["RestrictedCelValue = string | number"],
     "★ 求值期仅接受单标量（string|number），无上下文对象"),
    ("zc", "model-option-map/src/types.ts", "9", ["reasoningLevel", "maxOutputTokens"],
     "★ DSL 只有 2 个变量：reasoningLevel / maxOutputTokens"),
    ("zc", "model-option-map/src/evaluator.ts", "9-13", ["RestrictedCelValue"],
     "求值入口签名只收单标量 input"),
    ("zc", "model-option-map/src/compiler.ts", "44-50", ["must return a JSON object"],
     "编译期强制返回对象（否则 throw）"),
    ("zc", "model-option-map/src/merge-patch.ts", "66-67", ["delete result[key]"],
     "JSON Merge Patch 语义：null → 删除键"),
    ("zc", "model-option-map/src/parser.ts", "1-240", ["RestrictedCel"],
     "受限 CEL 解析器存在"),
    ("zc", "model-option-map/src/option-maps.ts", "20-22", ["compileModelOptionMap"],
     "★ 内置 option map 装配点：只有 reasoningLevel / maxOutputTokens 两个"),
    ("zc", "zcode-builtin.json", "3520-3548", ["reasoning_effort"],
     "opencode 站 reasoningLevel.map 写 reasoning_effort"),
    ("zc", "zcode-builtin.json", "3373-3400", ["contextWindow"],
     "glm-5.1 opencode 站 contextWindow=202752"),
    ("zc", "zcode-builtin.json", "2045-2065", ["disabled"],
     "模型层基线值域四档（disabled/low/high/max）"),
    ("zc", "zcode-builtin.json", "4148-4162", ["reasoning"],
     "DeepSeek 官方站 openai-responses 写 reasoning.effort"),
    # ---- DSH ----
    ("dsh", "src/account-pool.ts", "578", ["Date.now()"],
     "账号池限流过期判断内联 Date.now（D2 缺陷）"),
    ("dsh", "src/account-pool.ts", "662", ["Date.now()"],
     "第二处内联 Date.now"),
    ("dsh", "src/account-pool.ts", "1-771", ["class "],
     "账号池实现存在"),
    ("dsh", "src/llm-adapter.ts", "1452-1462", ["registerAdapter"],
     "registerAdapter 调用点"),
    ("dsh", "src/jet-hub-rpc.ts", "95", ["jet-hub"],
     "管理面 RPC 端点"),
    ("dsh", "src/sse.ts", "91", ["resolveToolPairing"],
     "可复用 SSE 工具配对函数"),
    ("dsh", "src/openai-compat.ts", "1-500", ["serializeMessages"],
     "可复用消息序列化"),
]

# ── 负向断言：断言"某文件里不存在某模式" ────────────────────────────────
# (仓库tag, 文件basename, 不得出现的正则, 说明)
NEG_ASSERTIONS: list[tuple[str, str, str, str]] = [
    ("gw", "pyproject.toml", r"\[project\.scripts\]",
     "网关尚无 [project.scripts] —— mgw 入口需新增（P0-2）"),
    ("dsh", "account-pool.ts", r"\b(lease|reserve|acquire|in_flight|lock|mutex)\b",
     "账号池无并发租约 —— 不可照抄（结论 02-D2）"),
    ("dsh", "account-pool.ts", r"\b(Clock|timeProvider|nowProvider)\b",
     "账号池无可注入时钟 —— 不可照抄（结论 02-D2）"),
]


_LC_CACHE: dict[Path, int] = {}
_LINES_CACHE: dict[Path, list[str]] = {}


def line_count(p: Path) -> int:
    """以 splitlines 为准（与 read_lines 一致）。

    注意：不能用「数换行符」——文件末尾无换行时会计少一行，
    导致 `:1-93` 这类引用被误判越界（本核验器 v1 就踩过这个坑）。
    """
    if p in _LC_CACHE:
        return _LC_CACHE[p]
    n = len(read_lines(p))
    _LC_CACHE[p] = n
    return n


def read_lines(p: Path) -> list[str]:
    if p in _LINES_CACHE:
        return _LINES_CACHE[p]
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            ls = f.read().splitlines()
    except Exception:
        ls = []
    _LINES_CACHE[p] = ls
    return ls


def needed_basenames() -> set[str]:
    names: set[str] = set()
    for name in DOCS:
        doc = DOC_DIR / name
        if doc.exists():
            for ref_path, _ in PAT.findall(doc.read_text(encoding="utf-8")):
                names.add(os.path.basename(ref_path))
    for _, hint, _, _, _ in ASSERTIONS:
        names.add(os.path.basename(hint))
    for _, hint, _, _ in NEG_ASSERTIONS:
        names.add(os.path.basename(hint))
    return names


def build_index(needed: set[str]) -> dict[str, list[tuple[str, Path]]]:
    """剪枝遍历三仓，只记录 basename 在 needed 里的文件。"""
    idx: dict[str, list[tuple[str, Path]]] = {}
    for tag, root in ROOTS.items():
        if not root.exists():
            print(f"!! 仓库根不存在，已跳过：{tag} = {root}")
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
            for fn in filenames:
                if fn not in needed:
                    continue
                if os.path.splitext(fn)[1] not in KEEP_EXTS:
                    continue
                idx.setdefault(fn, []).append((tag, Path(dirpath) / fn))
    return idx


def max_ref_line(spec: str) -> int:
    nums = [int(x) for x in re.split(r"[,\-/]", spec) if x.isdigit()]
    return max(nums) if nums else 0


def span_of(spec: str) -> tuple[int, int]:
    nums = [int(x) for x in re.split(r"[,\-/]", spec) if x.isdigit()]
    if not nums:
        return 0, 0
    return min(nums), max(nums)


def _fuzzy_suffix_hits(cands, ref_path: str):
    """路径组件按序包含匹配：文档写 `contracts/model/index.ts`，
    实际路径 `.../packages/contracts/src/model/index.ts` 也命中。
    比 endswith 宽松，比 basename 严格。"""
    parts = [x for x in ref_path.split("/") if x]
    hits = []
    for t, p in cands:
        comps = p.parts
        i = 0
        for c in comps:
            if i < len(parts) and c == parts[i]:
                i += 1
        if i == len(parts):
            hits.append((t, p))
    return hits


def resolve(idx, ref_path: str, spec: str):
    """返回 (status, detail)。status ∈ ok / ambiguous / FILE_NOT_FOUND / LINE_OOB

    三级收敛：① 严格 endswith → ② 路径组件按序包含 → ③ basename 全量。
    前两级能唯一定位就不报 ambiguous。
    """
    base = os.path.basename(ref_path)
    cands = idx.get(base, [])
    if not cands:
        return "FILE_NOT_FOUND", ""

    strict = [(t, p) for t, p in cands if str(p).endswith(ref_path)]
    pool = strict or _fuzzy_suffix_hits(cands, ref_path) or cands
    converged = bool(strict) or len(pool) < len(cands)

    lo, hi = span_of(spec)
    fits = [(t, p) for t, p in pool if line_count(p) >= hi]
    if not fits:
        mx = max(line_count(p) for _, p in pool)
        return "LINE_OOB", f"候选最大行数 {mx}"
    if len(fits) > 1 and not converged:
        return "ambiguous", ", ".join(f"{t}:{p}" for t, p in fits[:8]) + \
               (f" …共 {len(fits)}" if len(fits) > 8 else "")
    return "ok", f"{fits[0][0]}:{fits[0][1]}"


def _pick(idx, tag: str, path_hint: str):
    """按路径提示在指定仓库里挑候选：严格后缀 → 模糊组件包含 → basename。"""
    base = os.path.basename(path_hint)
    cands = [(t, p) for t, p in idx.get(base, []) if t == tag]
    if not cands:
        return []
    strict = [(t, p) for t, p in cands if str(p).endswith(path_hint)]
    if strict:
        return strict
    fuzzy = _fuzzy_suffix_hits(cands, path_hint)
    if fuzzy:
        return fuzzy
    return cands


def check_content(idx, tag: str, path_hint: str, spec: str, needles: list[str]):
    """读行号区间，检查是否含任一 needle。"""
    cands = _pick(idx, tag, path_hint)
    if not cands:
        return "FILE_NOT_FOUND", f"{tag}:{path_hint} 未索引到"
    lo, hi = span_of(spec)
    hits = []
    for t, p in cands:
        lines = read_lines(p)
        if hi > len(lines):
            hits.append(f"LINE_OOB({p} 共 {len(lines)} 行 < {hi})")
            continue
        seg = "\n".join(lines[lo - 1:hi]) if lo else "\n".join(lines[:hi])
        if any(n in seg for n in needles):
            hits.append(f"OK({p})")
        else:
            hits.append(f"MISMATCH({p}:{lo}-{hi} 未含 {needles})")
    ok = [h for h in hits if h.startswith("OK")]
    return ("ok" if ok else "CONTENT_MISMATCH"), " | ".join(hits)


def run_doc_scan(idx) -> tuple[int, list, list]:
    total, problems, ambiguous = 0, [], []
    for name in DOCS:
        doc = DOC_DIR / name
        if not doc.exists():
            problems.append((name, "DOC_MISSING", "-", "-", ""))
            continue
        refs = PAT.findall(doc.read_text(encoding="utf-8"))
        total += len(refs)
        for ref_path, spec in refs:
            status, detail = resolve(idx, ref_path, spec)
            if status in ("FILE_NOT_FOUND", "LINE_OOB"):
                problems.append((name, status, ref_path, spec, detail))
            elif status == "ambiguous":
                ambiguous.append((name, ref_path, spec, detail))
        print(f"  {name}: {len(refs)} 条引用")
    return total, problems, ambiguous


def check_negative(idx, tag: str, path_hint: str, pattern: str):
    """负向断言：全文件不得出现该正则。"""
    cands = _pick(idx, tag, path_hint)
    if not cands:
        return "FILE_NOT_FOUND", f"{tag}:{path_hint} 未索引到"
    rx = re.compile(pattern)
    bad = []
    for t, p in cands:
        hits = [f"{i + 1}:{ln.strip()[:90]}"
                for i, ln in enumerate(read_lines(p)) if rx.search(ln)]
        if hits:
            bad.append(f"{p} 命中 {len(hits)} 处: {hits[:3]}")
    return ("CONTENT_MISMATCH" if bad else "ok"), (" | ".join(bad) or "确认不存在")


def run_negative(idx) -> tuple[int, list]:
    total, problems = 0, []
    for tag, bn, pattern, why in NEG_ASSERTIONS:
        total += 1
        status, detail = check_negative(idx, tag, bn, pattern)
        mark = "✓" if status == "ok" else "✗"
        print(f"  {mark} [负向][{tag}] {bn} 不含 /{pattern}/ — {why}")
        if status != "ok":
            print(f"      {status}: {detail}")
            problems.append((tag, bn, pattern, why, status, detail))
    return total, problems


# ── 统计断言：文档 06 的头条数字，必须能被重算复现 ──────────────────────
# 这些不是 file:line 引用，而是"文档里写的数字" —— 必须机器复核，
# 否则数字写错了没人发现（本文件 v1 就出过 21 vs 22 的口径分歧）。
ZC_JSON = ROOTS["zc"] / "config/provider/zcode-builtin.json"
ZC_RENAMES = ROOTS["zc"] / "packages/provider-node/src/legacy-reasoning-level-renames.ts"

SLOT_PATTERNS = [
    ("thinking.type", r'"thinking"\s*:\s*\{[^}]*"type"'),
    ("reasoning.effort", r'"reasoning"\s*:\s*\{[^}]*"effort"'),
    ("reasoning.enabled", r'"reasoning"\s*:\s*\{[^}]*"enabled"'),
    ("output_config.effort", r'"output_config"\s*:\s*\{[^}]*"effort"'),
    ("reasoning_effort", r'"reasoning_effort"\s*:'),
    ("enable_thinking", r'"enable_thinking"\s*:'),
]


def zcode_stats() -> dict:
    """重算 zcode-builtin.json 的全部统计（文档 06 §3/§5/§11 的数字来源）。"""
    raw = ZC_JSON.read_bytes()
    d = json.loads(raw.decode("utf-8"))
    mcr = d["config"]["modelConfigRules"]

    maps, values, mo, cw = (collections.Counter() for _ in range(4))

    def scan(node):
        st = [node]
        while st:
            cur = st.pop()
            if isinstance(cur, dict):
                for k, v in cur.items():
                    if k == "reasoningLevel" and isinstance(v, dict):
                        values[tuple(v.get("values") or [])] += 1
                        mp = v.get("map")
                        maps[json.dumps(mp, sort_keys=True) if not isinstance(mp, str) else mp] += 1
                    elif k == "maxOutputTokens" and isinstance(v, dict):
                        if v.get("map") is not None:
                            mp = v.get("map")
                            mo[json.dumps(mp, sort_keys=True) if not isinstance(mp, str) else mp] += 1
                    elif k == "contextWindow":
                        cw[json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v] += 1
                    st.append(v)
            elif isinstance(cur, list):
                st.extend(cur)

    for _layer, val in mcr.items():
        for node in (val if isinstance(val, list) else [val]):
            if isinstance(node, dict):
                scan(node)

    real = {m: n for m, n in maps.items() if m not in ("null", "{}")}
    combos = collections.Counter()
    for m, n in real.items():
        combos[tuple(sorted(s for s, pat in SLOT_PATTERNS if re.search(pat, m)))] += n
    mo_fields = set()
    for m in mo:
        for f in re.findall(r"['\"]([a-z_]+)['\"]\s*:", m):
            mo_fields.add(f)

    ren_txt = ZC_RENAMES.read_text(encoding="utf-8")
    ren = re.findall(r'modelMatch:\s*"([^"]+)",\s*\n\s*oldLevel:\s*"([^"]+)"', ren_txt)

    return {
        "revision": d.get("revision"),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "lines": len(raw.decode("utf-8").splitlines()),
        "rl_occurrences": sum(values.values()),
        "values_domains_all": len(values),
        "values_domains_nonempty": len([k for k in values if k]),
        "rl_maps_total": len(maps),
        "rl_maps_real": len(real),
        "rl_null_maps": maps.get("null", 0),
        "rl_empty_maps": maps.get("{}", 0),
        "mo_map_variants": len(mo),
        "mo_field_names": len(mo_fields),
        "mo_fields": sorted(mo_fields),
        "context_windows": len(cw),
        "combos": len(combos),
        "ternary": len([m for m in real if re.search(r"\?\s*\{", m)]),
        "renames": len(ren),
        "renames_off": sum(1 for _, v in ren if v == "off"),
        "renames_nothink": sum(1 for _, v in ren if v == "nothink"),
    }


# (键, 期望值, 文档出处)
STAT_ASSERTIONS: list[tuple[str, object, str]] = [
    ("revision", 30, "06 §基线：zcode-builtin.json revision 30"),
    ("sha256", "0b3d735e0c2334353eecadfa8c0756a1a19fc4f7938fc62882048d6630c5f424",
     "06 §基线：sha256（两份副本同内容）"),
    ("lines", 6212, "06 §基线：6212 行"),
    ("rl_occurrences", 155, "06 §3不足4：reasoningLevel 出现 155 次"),
    ("values_domains_nonempty", 17, "06 §3不足4：17 种非空值域"),
    ("values_domains_all", 18, "06 §3不足4：18 种值域（含 1 种空）"),
    ("rl_maps_total", 22, "06 §3不足4：22 种 map 去重"),
    ("rl_maps_real", 20, "06 §3不足4：20 种真实表达式"),
    ("rl_null_maps", 54, "06 §3不足4：null×54（不写入）"),
    ("rl_empty_maps", 8, "06 §3不足4：{}×8（空 patch）"),
    ("mo_map_variants", 4, "06 §3不足4：4 种 maxOutputTokens.map 写法"),
    ("mo_field_names", 3, "06 §3不足4：3 个字段名（max_tokens/max_completion_tokens/max_output_tokens）"),
    ("context_windows", 16, "06 §3不足4 / §七：16 种 contextWindow 取值"),
    ("combos", 10, "06 §5.3：20 种表达式 → 10 种写入位组合"),
    ("ternary", 6, "06 §5.3：6 种含三元分支"),
    ("renames", 25, "06 §3不足2：legacy-reasoning-level-renames 共 25 条"),
    ("renames_off", 24, "06 §3不足2：24 条 off"),
    ("renames_nothink", 1, "06 §3不足2：1 条 nothink（GLM-5.2）"),
]

# 值域空值计数（78 处 values:[]）单独算，因为它在文档里是"一半配置行"的论据
STAT_ASSERTIONS.append(("values_empty_occurrences", 78, "06 §3不足4：78 处 values:[]"))


def run_stats(idx) -> tuple[int, list]:
    print(f"  基线文件：{ZC_JSON}")
    if not ZC_JSON.exists():
        return 0, [("ZC_JSON", "FILE_NOT_FOUND", "-", "-", "FILE_NOT_FOUND", str(ZC_JSON))]
    try:
        s = zcode_stats()
    except Exception as e:  # noqa: BLE001
        return 0, [("ZC_JSON", "PARSE_ERROR", "-", "-", "PARSE_ERROR", repr(e))]

    # values:[] 出现次数
    d = json.loads(ZC_JSON.read_text(encoding="utf-8"))
    empty = 0

    def cnt(node):
        nonlocal empty
        st = [node]
        while st:
            cur = st.pop()
            if isinstance(cur, dict):
                for k, v in cur.items():
                    if k == "reasoningLevel" and isinstance(v, dict) and not (v.get("values") or []):
                        empty += 1
                    st.append(v)
            elif isinstance(cur, list):
                st.extend(cur)

    for _l, val in d["config"]["modelConfigRules"].items():
        for node in (val if isinstance(val, list) else [val]):
            if isinstance(node, dict):
                cnt(node)
    s["values_empty_occurrences"] = empty

    total, problems = 0, []
    for key, expect, why in STAT_ASSERTIONS:
        total += 1
        got = s.get(key)
        good = got == expect
        mark = "✓" if good else "✗"
        shown = f"{got}" if not isinstance(got, str) or len(str(got)) < 24 else str(got)[:20] + "…"
        print(f"  {mark} {key} = {shown}  — {why}")
        if not good:
            problems.append(("stats", key, str(expect), why, "STAT_MISMATCH", f"期望 {expect}，实得 {got}"))
    print(f"  （maxOutputTokens 字段名实测：{s['mo_fields']}）")
    return total, problems


def run_assertions(idx) -> tuple[int, list]:
    total, problems = 0, []
    for tag, bn, spec, needles, why in ASSERTIONS:
        total += 1
        status, detail = check_content(idx, tag, bn, spec, needles)
        mark = "✓" if status == "ok" else "✗"
        print(f"  {mark} [{tag}] {bn}:{spec} — {why}")
        if status != "ok":
            print(f"      {status}: {detail}")
            problems.append((tag, bn, spec, why, status, detail))
    return total, problems


def selftest(idx) -> int:
    """植入已知对/错用例，确认核验器能区分。"""
    print("=" * 72)
    print("植入错误自测：17 例（9 例应通过 / 8 例应报错）")
    print("=" * 72)
    cases = [
        # (期望, 描述, 调用)
        ("ok", "真实存在的文件+合法行号", resolve(idx, "model_gateway/api/openai_compat.py", "36-44")),
        ("ok", "真实 ZCode 大 json 合法行号", resolve(idx, "zcode-builtin.json", "3520-3548")),
        ("ok", "模糊路径消歧（省略中间 src/ 段）",
         resolve(idx, "contracts/model/index.ts", "625-627")),
        ("FILE_NOT_FOUND", "不存在的文件名", resolve(idx, "no-such-file-xyz.py", "1-2")),
        ("LINE_OOB", "真实文件但行号远超总行数", resolve(idx, "openai_compat.py", "99999")),
        ("ok", "内容断言命中", check_content(idx, "gw", "ir.py", "100-120", ["reasoning_effort"])),
        ("CONTENT_MISMATCH", "内容断言故意用不存在的 token",
         check_content(idx, "gw", "ir.py", "100-120", ["ZZZ_NOT_IN_FILE_ZZZ"])),
        ("CONTENT_MISMATCH", "内容断言取错行区间（取 1-5 行找 reasoning_effort）",
         check_content(idx, "gw", "ir.py", "1-5", ["reasoning_effort"])),
        ("FILE_NOT_FOUND", "仓库 tag 写错（zc 里找 gw 文件）",
         check_content(idx, "zc", "openai_compat.py", "36-44", ["def list_models"])),
        # 负向断言
        ("ok", "负向：pyproject 确实无 [project.scripts]",
         check_negative(idx, "gw", "pyproject.toml", r"\[project\.scripts\]")),
        ("CONTENT_MISMATCH", "负向：故意断言 ir.py 不含 def（实际含）",
         check_negative(idx, "gw", "ir.py", r"^\s*def\s")),
        ("ok", "负向：account-pool 无租约关键字",
         check_negative(idx, "dsh", "account-pool.ts",
                        r"\b(lease|reserve|acquire|in_flight|lock|mutex)\b")),
        # off-by-one 回归：末尾无换行的文件，splitlines 计数必须正确
        ("ok", "off-by-one 回归：credits-capabilities.js:1-92 应在界内",
         resolve(idx, "credits-capabilities.js", "1-92")),
        ("LINE_OOB", "off-by-one 回归：credits-capabilities.js:1-200 应越界",
         resolve(idx, "credits-capabilities.js", "1-200")),
    ]
    # 统计断言层自测：确认「数字对得上」和「数字对不上」能被区分
    try:
        s = zcode_stats()
        cases.append(("ok", "统计：zcode-builtin.json revision == 30",
                      ("ok" if s["revision"] == 30 else "STAT_MISMATCH", "")))
        cases.append(("STAT_MISMATCH", "统计：故意用错误期望值（revision==999）",
                      ("ok" if s["revision"] == 999 else "STAT_MISMATCH", "")))
        cases.append(("ok", "统计：155 次 reasoningLevel",
                      ("ok" if s["rl_occurrences"] == 155 else "STAT_MISMATCH", "")))
    except Exception as e:  # noqa: BLE001
        print(f"  !! 统计层自测无法运行：{e!r}")

    passed = 0
    for expect, desc, (got, _detail) in cases:
        good = got == expect
        passed += good
        print(f"  {'✓' if good else '✗'} 期望 {expect:<16} 实得 {got:<16} {desc}")
    print(f"\n自测结果：{passed}/{len(cases)} 通过")
    if passed != len(cases):
        print("!! 核验器本身有问题，正式核验结果不可信。")
        return 1
    print("核验器自测通过，可用于正式核验。")
    return 0


def main() -> int:
    needed = needed_basenames()
    print(f"待索引 basename：{len(needed)} 个")
    idx = build_index(needed)
    print(f"索引命中文件：{sum(len(v) for v in idx.values())} 个"
          f"（{len(idx)} 个不同 basename）")
    missing = sorted(needed - set(idx))
    if missing:
        print(f"!! 未被索引到的 basename（{len(missing)}）：{missing}")
    print()

    if "--selftest" in sys.argv:
        return selftest(idx)

    print("=" * 72)
    print("第一层 · 引用可解析性核验（文件存在 + 行号在界内）")
    print("=" * 72)
    total, problems, ambiguous = run_doc_scan(idx)
    print(f"\n  合计引用 {total} 条｜确认问题 {len(problems)} 条｜"
          f"同名多候选 {len(ambiguous)} 条")

    print()
    print("=" * 72)
    print("第二层 · 关键结论内容断言核验（结论所依赖的行真的写了这句话吗）")
    print("=" * 72)
    atotal, aproblems = run_assertions(idx)
    print(f"\n  断言 {atotal} 条｜失败 {len(aproblems)} 条")

    print()
    print("=" * 72)
    print("第三层 · 负向断言核验（「某能力不存在」类结论必须可证伪）")
    print("=" * 72)
    ntotal, nproblems = run_negative(idx)
    print(f"\n  负向断言 {ntotal} 条｜失败 {len(nproblems)} 条")

    print()
    print("=" * 72)
    print("第四层 · 统计断言核验（文档里的数字必须能被重算复现）")
    print("=" * 72)
    stotal, sproblems = run_stats(idx)
    print(f"\n  统计断言 {stotal} 条｜失败 {len(sproblems)} 条")

    print()
    print("=" * 72)
    grand = total + atotal + ntotal + stotal
    gprob = len(problems) + len(aproblems) + len(nproblems) + len(sproblems)
    print(f"总计：引用 {total} 条 + 正向断言 {atotal} 条 + 负向断言 {ntotal} 条"
          f" + 统计断言 {stotal} 条 = 校验 {grand} 项")
    print(f"确认问题 {len(problems)} + {len(aproblems)} + {len(nproblems)}"
          f" + {len(sproblems)} = {gprob} 条")
    print("=" * 72)

    if problems:
        print("\n### 引用层问题")
        for doc, kind, ref, spec, extra in problems[:80]:
            print(f"  [{kind}] {doc} :: {ref}:{spec} {extra}")
        if len(problems) > 80:
            print(f"  ...（共 {len(problems)} 条，已截断）")

    if aproblems:
        print("\n### 正向断言问题")
        for tag, bn, spec, why, status, detail in aproblems:
            print(f"  [{status}] {tag}:{bn}:{spec} — {why}\n      {detail}")

    if nproblems:
        print("\n### 负向断言问题")
        for tag, bn, pattern, why, status, detail in nproblems:
            print(f"  [{status}] {tag}:{bn} /{pattern}/ — {why}\n      {detail}")

    if sproblems:
        print("\n### 统计断言问题")
        for tag, key, expect, why, status, detail in sproblems:
            print(f"  [{status}] {key} — {why}\n      {detail}")

    if ambiguous:
        print(f"\n### 同名多候选（{len(ambiguous)} 条，需人工消歧）")
        seen = set()
        for doc, ref, spec, cands in ambiguous:
            key = (ref, spec)
            if key in seen:
                continue
            seen.add(key)
            print(f"  {doc} :: {ref}:{spec}\n      → {cands}")
        print(f"  （去重后 {len(seen)} 组）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
