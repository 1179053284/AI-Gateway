#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基线漂移检查：比对文档声明的参考项目基线 vs 仓库实际 HEAD。

**为什么必须有这个脚本**：`git status --porcelain` 干净 **只证明"我没改它"**，
**不能证明"它没变"**。2026-09-22 实测踩到这个坑：
参考仓库 `deepseek-harness-codearts` 在调研过程中被**重建**（HEAD 从 `3979729` 变为 `d461361`，
且 `3979729` 不再是 HEAD 的祖先 —— 历史被重写），导致文档里数百个行号引用**静默失效**。
而当时每轮"只读确认"用的都是 `git status`，**全部显示干净**。

**本脚本做三件事**：
  1. 从各文档抽取声明的基线 commit（`3979729...` 这类 40 位 hash 或 `git rev-parse HEAD` 上下文）
  2. 读仓库实际 HEAD，比对
  3. 若不一致 → 报错并给出漂移文件的规模变化，提示需要重锚行号

用法：`python3 verify-baseline.py`
"""

import re
import subprocess
import sys
from pathlib import Path

DOCS = Path("/Users/w/Desktop/Model-Gateway/docs/research")
REPOS = {
    "deepseek-harness-codearts": Path("/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts"),
    "ZCode": Path("/Users/w/Desktop/01-关注的开源项目/ZCode"),
    "Model-Gateway": Path("/Users/w/Desktop/Model-Gateway"),
}
# 关注这些文件的行数变化（行号引用密集）
WATCH = ["src/index.ts", "src/llm-adapter.ts", "AGENTS.md", "package.json", "README.md",
         "docs/lobsterai-integration-plan.md", "docs/adding-a-new-provider.md"]
HASH = re.compile(r"\b([0-9a-f]{40})\b")
# 这些行是在**刻意引用已失效的旧基线做说明**（漂移声明 / 原基线标注），不算"声明的现行基线"
HISTORICAL = re.compile(r"已失效|原基线|原复核基线|从仓库历史中消失|不再是 HEAD 的祖先|原基线（")


def head(repo: Path):
    try:
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


def is_ancestor(repo: Path, old: str):
    try:
        r = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", old, "HEAD"],
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return None


def lines_of(p: Path):
    try:
        return len(p.read_text(encoding="utf-8", errors="replace").splitlines())
    except Exception:  # noqa: BLE001
        return None


def main():
    print("=" * 76)
    print("基线漂移检查")
    print("=" * 76)
    declared = {}   # hash -> [文件:行]
    skipped = 0
    for doc in sorted(DOCS.glob("[0-9][0-9]-*.md")):
        for i, ln in enumerate(doc.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if HISTORICAL.search(ln):
                skipped += 1
                continue          # 刻意引用旧基线做说明的行，跳过
            for h in HASH.findall(ln):
                declared.setdefault(h, []).append(f"{doc.name}:{i}")
    if skipped:
        print(f"  （跳过 {skipped} 行「刻意引用已失效旧基线」的说明行）")

    if not declared:
        print("  未在文档中找到声明的基线 commit hash")
        return 0

    problems = []
    for h, where in declared.items():
        owner = None
        for name, path in REPOS.items():
            cur = head(path)
            if cur and (cur.startswith(h[:7]) or h.startswith(cur[:7])):
                owner = name
                break
        if owner is None:
            # 不在任何仓库的 HEAD —— 可能是历史 commit，逐个仓库试 is-ancestor
            for name, path in REPOS.items():
                anc = is_ancestor(path, h)
                if anc:
                    owner = name
                    break
        if owner is None:
            problems.append((h, where, "**该 commit 不在任何参考仓库的历史中**（历史可能被重建）"))
            continue
        path = REPOS[owner]
        cur = head(path)
        if cur and not cur.startswith(h[:7]):
            anc = is_ancestor(path, h)
            tag = "（旧 commit 是 HEAD 祖先，属正常前进）" if anc else "**（旧 commit 不是 HEAD 祖先 —— 历史被重建！）**"
            problems.append((h, where, f"{owner} HEAD 已变为 {cur[:12]} {tag}"))

    if problems:
        print(f"❌ 发现 {len(problems)} 处基线漂移：\n")
        for h, where, msg in problems:
            print(f"  声明基线 {h[:12]}…（{len(where)} 处引用，首处 {where[0]}）")
            print(f"    → {msg}\n")
        # 给出漂移文件的规模对比
        for name, path in REPOS.items():
            print(f"  [{name}] 现行 HEAD = {(head(path) or '?')[:12]}，关键文件行数：")
            for f in WATCH:
                p = path / f
                if p.exists():
                    print(f"     {f:<38} {lines_of(p):>6} 行")
            print()
        print("  ⚠️ 处置：**行号引用需按新基线重锚**；不能只靠 `git status` 判断基线是否变化。")
        return 1

    print("✅ 文档声明的基线 commit 与各仓库 HEAD 一致（或旧 commit 仍是 HEAD 祖先）")
    for name, path in REPOS.items():
        print(f"  [{name}] HEAD = {(head(path) or '?')[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
