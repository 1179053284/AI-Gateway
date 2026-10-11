#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""脚本化校验 09 号文档及 07/08/00 改动的全部 `路径:行号` 引用。

两层校验：
  A. 结构性：文件存在 + 行号在 [1, 总行数] 内
  B. 内容性：关键引用所在行必须命中预期关键词（CONTENT_CHECKS）

同名文件消歧（关键）：仓库间存在多个同名文件（`AGENTS.md` / `README.md` / `package.json` …）。
本脚本用「**行号能否落在该候选文件范围内**」来消歧 —— 这是可判定的客观标准，不依赖人工猜测。
若多个候选都满足或都不满足，则记为 INFO（提示），不计为错误。
"""

import re
import sys
from pathlib import Path

DSH = Path("/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts")
MGW = Path("/Users/w/Desktop/Model-Gateway")
ZCODE = Path("/Users/w/Desktop/01-关注的开源项目/ZCode")
DOCS = MGW / "docs" / "research"

ROOT_MAP = {
    "deepseek-harness-codearts": DSH,
    "Model-Gateway": MGW,
    "ZCode": ZCODE,
}
SEARCH_ROOTS = [MGW, DSH, ZCODE]

REF_RE = re.compile(
    r"`(?P<path>[A-Za-z0-9_./\-\u4e00-\u9fff]+\.(?:py|ts|js|json|yaml|yml|md))"
    r":(?P<lines>\d+(?:[-,]\d+)*)`"
)

CONTENT_CHECKS = [
    # ── DSH 插件侧（L3 判定） ──
    ("src/llm-adapter.ts", 10, ["signRequestHuawei"]),
    ("src/llm-adapter.ts", 14, ["CHAT_API_BASE", "myhuaweicloud"]),
    ("src/llm-adapter.ts", 726, ["class CodeArtsAdapter", "LlmAdapter"]),
    ("src/llm-adapter.ts", 835, ["async *stream", "AsyncIterable", "StreamChunk"]),
    ("src/llm-adapter.ts", 1454, ["registerConfigurableProviders"]),
    ("src/llm-adapter.ts", 1458, ["registerAdapter"]),
    ("src/index.ts", 25, ["name", "codearts-auth"]),
    ("src/index.ts", 33, ["inject", "credentials", "commands", "llm"]),
    ("src/index.ts", 121, ["function apply", "Context"]),
    ("AGENTS.md", 984, ["unhandled error", "整个 DSH 宿主"]),
    ("docs/lobsterai-integration-plan.md", 131, ["不需要跑那个反代"]),
    ("docs/lobsterai-integration-plan.md", 136, ["registerAdapter", "已经就是那一层"]),
    ("docs/lobsterai-integration-plan.md", 144, ["少一个进程"]),
    # ── 网关侧（L2 判定） ──
    ("config.example.yaml", 3, ["密钥仅存本地明文"]),
    ("config.example.yaml", 10, ["host", "0.0.0.0"]),
    ("config.example.yaml", 11, ["port", "8300"]),
    ("config.example.yaml", 17, ["access_tokens"]),
    ("config.example.yaml", 20, ["mg-"]),
    ("config.example.yaml", 48, ["api_key", "明文"]),
    ("model_gateway/main.py", 67, ["model_params"]),
    ("model_gateway/main.py", 88, ["reasoning"]),
    ("model_gateway/main.py", 93, ["model_params"]),
    ("model_gateway/main.py", 174, ["access_tokens"]),
    ("model_gateway/main.py", 175, ["免鉴权"]),
    ("model_gateway/main.py", 182, ["include_router", "openai"]),
    ("model_gateway/main.py", 183, ["include_router", "anthropic"]),
    ("model_gateway/main.py", 184, ["include_router", "admin"]),
    ("model_gateway/main.py", 186, ["/health"]),
    ("model_gateway/main.py", 288, ["def main"]),
    ("model_gateway/main.py", 294, ["instance_lock.acquire"]),
    ("model_gateway/main.py", 307, ["uvicorn.Server", "uvicorn.Config"]),
    ("model_gateway/main.py", 308, ["port"]),
    ("model_gateway/api/openai_compat.py", 36, ["/v1/models"]),
    ("model_gateway/api/openai_compat.py", 101, ["/v1/chat/completions"]),
    ("model_gateway/api/openai_compat.py", 104, ["request.json"]),
    ("model_gateway/api/openai_compat.py", 238, ["/v1/images/generations"]),
    ("model_gateway/api/anthropic.py", 3, ["透传优先"]),
    ("model_gateway/api/anthropic.py", 316, ["/v1/messages"]),
    ("model_gateway/enums/matcher.py", 18, ["class EnumEntry"]),
    ("model_gateway/enums/matcher.py", 137, ["未取证"]),
    ("model_gateway/core/scheduler.py", 223, ["_out_body"]),
    # ── 同名文件消歧的定点验证（用带仓库前缀的全路径强制指向） ──
    ("deepseek-harness-codearts/package.json", 6, ["lib/index.js"]),
    ("deepseek-harness-codearts/README.md", 46, ["dsh plugin"]),
    ("deepseek-harness-codearts/README.md", 59, ["dsh plugin"]),
    ("deepseek-harness-codearts/AGENTS.md", 152, ["registerProvider"]),
    ("deepseek-harness-codearts/docs/adding-a-new-provider.md", 338, ["必须实现的 4 个方法"]),
    ("deepseek-harness-codearts/docs/adding-a-new-provider.md", 339, ["providerInfo"]),
    ("deepseek-harness-codearts/docs/adding-a-new-provider.md", 342, ["stream"]),
    ("Model-Gateway/README.zh-CN.md", 17, ["Trae", "Cursor", "Cherry Studio"]),
    ("Model-Gateway/docs/changes/ACTIVE.md", 27, ["T6", "无 git 仓库"]),
    ("Model-Gateway/model_gateway/api/admin.py", 110, ["/admin/api/status"]),
]


def line_count(p: Path) -> int:
    try:
        return len(p.read_text(encoding="utf-8", errors="replace").splitlines())
    except Exception:  # noqa: BLE001
        return -1


def get_line(p: Path, n: int) -> str:
    try:
        ls = p.read_text(encoding="utf-8", errors="replace").splitlines()
        return ls[n - 1] if 1 <= n <= len(ls) else ""
    except Exception:  # noqa: BLE001
        return ""


def parse_lines(spec: str):
    out = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out.append((int(a), int(b)))
        else:
            n = int(part)
            out.append((n, n))
    return out


def fits(p: Path, spans) -> bool:
    n = line_count(p)
    return n > 0 and all(1 <= a and b <= n for a, b in spans)


def candidates(path_str: str):
    """返回候选绝对路径列表（去重、排除 .git / node_modules）。"""
    out = []
    for prefix, root in ROOT_MAP.items():
        if path_str.startswith(prefix + "/"):
            out.append(root / path_str[len(prefix) + 1:])
            return out
    # 直接拼接（覆盖 .cursor/... 这类隐藏目录）
    for root in SEARCH_ROOTS:
        c = root / path_str
        if c.exists():
            out.append(c)
    if out:
        return out
    for root in SEARCH_ROOTS:
        try:
            out.extend(root.glob(f"**/{path_str}"))
        except Exception:  # noqa: BLE001
            pass
    seen, uniq = set(), []
    for p in out:
        s = str(p)
        if "/.git/" in s or "/node_modules/" in s or "/.pytest_cache/" in s:
            continue
        if s not in seen:
            seen.add(s)
            uniq.append(p)
    return uniq


def resolve(path_str: str, spans):
    """返回 (Path|None, 状态, 说明)。状态 ∈ ok / ambiguous / missing。"""
    cands = candidates(path_str)
    if not cands:
        return None, "missing", f"未找到（{path_str}）"
    if len(cands) == 1:
        return cands[0], "ok", "unique"
    good = [c for c in cands if fits(c, spans)]
    if len(good) == 1:
        return good[0], "ok", f"按行号消歧（{len(cands)} 个同名候选中唯一匹配）"
    return cands[0], "ambiguous", f"同名 {len(cands)} 处、按行号消歧后剩 {len(good)} 处"


def strip_revision(text: str) -> str:
    kept, skipping = [], False
    for ln in text.splitlines():
        if re.match(r"^#{2,3}\s*(修订记录|第三批修订|改动对照|核验报告)", ln.strip()):
            skipping = True
            continue
        if skipping and re.match(r"^#{2}\s", ln):
            skipping = False
        if not skipping:
            kept.append(ln)
    return "\n".join(kept)


def main():
    targets = [
        DOCS / "09-网关形态定位与本地LLM形态辨析.md",
        DOCS / "07-DSH插件本地LLM形态与宿主契约.md",
        DOCS / "08-宿主原生Provider机制横向调研.md",
        DOCS / "00-总览与落地建议.md",
    ]
    total, errors, warns, per_file = 0, [], [], {}

    for doc in targets:
        if not doc.exists():
            errors.append(f"[缺失文档] {doc}")
            continue
        text = strip_revision(doc.read_text(encoding="utf-8"))
        n_refs = 0
        for m in REF_RE.finditer(text):
            ps = m.group("path")
            spans = parse_lines(m.group("lines"))
            total += 1
            n_refs += 1
            p, st, note = resolve(ps, spans)
            if st == "missing":
                errors.append(f"[{doc.name}] {note}")
                continue
            if st == "ambiguous":
                warns.append(f"[{doc.name}] {note}：{ps}")
                continue
            for a, b in spans:
                if not fits(p, [(a, b)]):
                    errors.append(
                        f"[{doc.name}] 行号越界: {ps}:{a}-{b}"
                        f"（{p.relative_to(p.anchor) if False else p.name} 共 {line_count(p)} 行）")
        per_file[doc.name] = n_refs

    content_fail = []
    for frag, ln, kws in CONTENT_CHECKS:
        p, st, note = resolve(frag, [(ln, ln)])
        if p is None:
            content_fail.append(f"内容校验：找不到文件 {frag}")
            continue
        actual = get_line(p, ln)
        for kw in kws:
            if kw not in actual:
                content_fail.append(
                    f"{frag}:{ln} 期望含「{kw}」｜实际: {actual.strip()[:110]}")

    print("=" * 74)
    print("引用校验结果")
    print("=" * 74)
    for name, n in per_file.items():
        print(f"  {name}: {n} 处引用")
    print(f"  合计: {total} 处引用 ｜ 内容校验: {len(CONTENT_CHECKS)} 条")
    print()
    if warns:
        print(f"ℹ️  {len(warns)} 条提示（非错误，同名文件消歧失败）：")
        for w in warns[:10]:
            print("   -", w)
        if len(warns) > 10:
            print(f"   … 另 {len(warns) - 10} 条同类")
        print()
    if content_fail:
        print(f"❌ 内容校验发现 {len(content_fail)} 处问题：")
        for x in content_fail:
            print("   -", x)
        print()
    if errors:
        print(f"❌ 结构校验发现 {len(errors)} 处问题：")
        for x in errors:
            print("   -", x)
        return 1
    print("✅ 结构校验通过（文件存在 + 行号在范围内）")
    if content_fail:
        return 1
    print("✅ 内容校验通过（关键引用所在行命中预期关键词）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
