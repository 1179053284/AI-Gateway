#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""撤证（变异）：对接说明模型 ID 复制钮那几条判据**能不能红**。

每条变异只改一处语法、不改结构（改结构会让页面不可解析 = 无效撤证，本仓已归档过这个坑）。
跑前 = 跑后 apidocs.js 的 md5 必须逐字节一致，用 /tmp 备份复原（不用 git checkout —— 该文件未跟踪）。

预期红族：
  M1 摘掉整颗钮      → 覆盖面链一起红（C1/C2/C3/C4/C6a/C6b/C7/C8）
  M2 配对间距 8px→2px → 只 C3 红
  M3 钮 20×20→30×30   → C4 + C8（深色同一条腿）红
  M4 复制腿恒取第一颗 → 只 C6b 红（C2 仍真 = 钉的是"点下去写的是哪一个"）
  M5 去掉 toast 文案参 → 只 C6a 红
  M6 组件类换成 btn   → C4 + C8 红（计算色不再与地址钮同源）
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path("/Users/w/Desktop/Model-Gateway")
TARGET = ROOT / "coding/model_gateway/web/static/js/pages/apidocs.js"
PROBE = ROOT / "bianyiandhuanjing/scripts/probe_apidocs_modelid_copy.py"

MUTATIONS = [
    ("M1 摘掉钮（只留 ID 文本）",
     '<td class="mono strong">${idCell(m.id)}</td>',
     '<td class="mono strong">${esc(m.id)}</td>'),
    ("M2 配对间距 8px → 2px",
     'align-items:center;gap:8px">${esc(id)}',
     'align-items:center;gap:2px">${esc(id)}'),
    ("M3 钮尺寸 20×20 → 30×30",
     'style="width:20px;height:20px">${COPY}</button></span>',
     'style="width:30px;height:30px">${COPY}</button></span>'),
    ("M4 复制腿恒取第一颗钮的 id",
     'copyText(b.dataset.idcopy, "模型 ID 已复制")',
     'copyText(document.querySelector("[data-idcopy]").dataset.idcopy, "模型 ID 已复制")'),
    ("M5 去掉 toast 文案参（回落成通用「已复制」）",
     'copyText(b.dataset.idcopy, "模型 ID 已复制")',
     'copyText(b.dataset.idcopy)'),
    ("M6 组件类 icon-btn sm → btn btn-sm（脱离图标钮体系）",
     'class="icon-btn sm" data-idcopy=',
     'class="btn btn-sm" data-idcopy='),
]


def run_probe() -> tuple[int, list[str], str]:
    proc = subprocess.run([sys.executable, str(PROBE)], capture_output=True,
                          text=True, timeout=360, cwd=str(ROOT))
    red: list[str] = []
    for line in proc.stdout.splitlines():
        if line.lstrip().startswith("✗"):
            red.append(line.split()[1])
    if "合计：" not in proc.stdout:
        return proc.returncode, red, "探针没交回读数" + proc.stderr[-300:]
    tail = [l for l in proc.stdout.splitlines() if l.startswith("合计：")]
    return proc.returncode, red, tail[0] if tail else ""


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    orig_md5 = hashlib.md5(src.encode("utf8")).hexdigest()
    backup = Path("/tmp/apidocs-modelid-backup.js")
    backup.write_text(src, encoding="utf-8")
    rows = []
    bad = []
    try:
        for name, old, new in MUTATIONS:
            if src.count(old) != 1:
                rows.append((name, "BAD", f"变异锚命中 {src.count(old)} 次（应为 1）"))
                bad.append(name)
                continue
            TARGET.write_text(src.replace(old, new, 1), encoding="utf-8")
            rc, red, tail = run_probe()
            # 先复原，再核对复原后的 md5（顺序写反会把"本来就该是变异态"的文件判成 BAD）
            TARGET.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
            restored = hashlib.md5(TARGET.read_bytes()).hexdigest()
            if restored != orig_md5:
                rows.append((name, "BAD", f"复原后 md5 {restored[:12]} ≠ {orig_md5[:12]}"))
                bad.append(name + " 复原失败")
            else:
                rows.append((name, red or ["(无红)"], tail))
                if not red:
                    bad.append(name + " → 判据不红 = 空判据（或探针崩了没交回读数）")
    finally:
        TARGET.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")

    final = hashlib.md5(TARGET.read_bytes()).hexdigest()
    print("=" * 96)
    for name, reds, tail in rows:
        print(f"  {name}\n     红：{reds}\n     {tail}")
    print(f"\n  复原核对：apidocs.js md5 跑前={orig_md5[:12]}… 跑后={final[:12]}… "
          + ("✓ 逐字节一致" if final == orig_md5 else "✗ 不一致"))
    print(f"合计：{len(MUTATIONS) - len(bad)} 条变异可红 / {len(bad)} 条不红或 BAD")
    for b in bad:
        print(f"  ✗ {b}")
    return 1 if bad or final != orig_md5 else 0


if __name__ == "__main__":
    sys.exit(main())
