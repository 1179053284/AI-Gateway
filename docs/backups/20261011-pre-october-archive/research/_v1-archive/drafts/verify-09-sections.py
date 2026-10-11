#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨文档章节引用校验（保守版，只报高置信度问题）。

动机：本轮审计发现两类"行号对、但指向错"的错误：
  - `00` 三处把 `docs/changes/ACTIVE.md` 写成 `.cursor/memory/ACTIVE.md`
  - `07` 三处把 Jet Hub 引用写成 `§9`（实为 `§8`）
  - 主 agent 自查发现 `05` §3.2 应为 §3.3.3（TRAE 风控）
常规"路径:行号"校验对这类完全无感。

**保守策略（避免误报）**：只在**同一行内**同时出现「明确的文档点名」与「§引用」时才校验。
明确点名 = `NN` 号文档 / `NN-xxx.md`（NN 为 00~09）。
并跳过：
  - 修订记录 / 第三批修订 段落（刻意引用旧值）
  - 疑似平台条款行（含 协议 / 条款 / ToS / AUP / 服务条款 等）
  - ZCode / DSH 等外部仓库路径（其 `NN-...md` 不是我们的研究文档）
"""

import re
import sys
from pathlib import Path

DOCS = Path("/Users/w/Desktop/Model-Gateway/docs/research")
FILES = sorted(p for p in DOCS.glob("[0-9][0-9]-*.md"))
OURS = {p.name[:2] for p in FILES}

H2 = re.compile(r"^##\s+§?(\d+)[\.、]?\s*(.*)$")   # 兼容 `## 9. xxx` 与 `## §9 xxx`
H3 = re.compile(r"^###\s+§?(\d+\.\d+(?:\.\d+)?)\s*(.*)$")
H4 = re.compile(r"^####\s+(\d+\.\d+\.\d+)\s*(.*)$")
TBL = re.compile(r"^\|\s*\*{0,2}([PQ]\d+-\d+)\*{0,2}\s*\|")
SECREF = re.compile(r"§\s*([PQ]?\d+(?:\.\d+)*(?:-\d+)?)")
# 明确点名：`NN` 号文档 / `NN-xxx.md` / `NN` §（裸编号紧跟 § 的常见写法）
POINT = re.compile(
    r"`(\d{2})`\s*号文档"
    r"|`(\d{2})-[^\s`）)]*\.md`"
    r"|`(\d{2})`\s*§"
)
REV = re.compile(r"修订记录|第三批修订|改动对照")
TOS = re.compile(r"协议|条款|ToS|AUP|服务条款|Privacy|政策")
EXTERNAL = re.compile(r"ZCode|deepseek-harness-codearts|zcode\.z\.ai|github\.com")


def build_toc():
    toc = {}
    for f in FILES:
        s = set()
        for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
            for rx in (H2, H3, H4):
                m = rx.match(ln)
                if m:
                    s.add(m.group(1))
            m = TBL.match(ln)
            if m:
                s.add(m.group(1))
        toc[f.name[:2]] = s
    return toc


def main():
    toc = build_toc()
    errors, skipped = [], 0
    for f in FILES:
        me = f.name[:2]
        skipping = False
        for i, ln in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if REV.search(ln):
                skipping = True
                continue
            if skipping and re.match(r"^##\s", ln):
                skipping = False
            if skipping:
                continue
            if TOS.search(ln) or EXTERNAL.search(ln):
                skipped += 1
                continue
            targets = set()
            for m in POINT.finditer(ln):
                t = m.group(1) or m.group(2)
                if t in OURS and t != me:
                    targets.add(t)
            if not targets:
                continue
            for m in SECREF.finditer(ln):
                ref = m.group(1)
                if not any(ref in toc.get(t, set()) for t in targets):
                    errors.append((f.name, i, ref, sorted(targets)))
    print("=" * 74)
    print("跨文档章节引用校验（保守版）")
    print("=" * 74)
    print(f"  扫描 {len(FILES)} 份文档；跳过 {skipped} 行疑似平台条款/外部仓库行")
    print()
    if errors:
        print(f"❌ {len(errors)} 处高置信度问题：")
        for fn, ln, ref, tg in errors:
            print(f"   [{fn}:{ln}] §{ref} → 点名 {tg}，但其中无 §{ref}")
        return 1
    print("✅ 未发现高置信度的跨文档章节引用错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())
