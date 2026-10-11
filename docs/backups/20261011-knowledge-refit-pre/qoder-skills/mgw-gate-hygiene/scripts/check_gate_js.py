#!/usr/bin/env python3
"""抽取 Python 验收门里的内嵌 JS 块并做 ES 模块语法检查（node --check）。

用法：
  python3 check_gate_js.py <gate.py> [<gate2.py> ...]
  python3 check_gate_js.py --dump <gate.py>   # 只导出到 /tmp 供人工/后续 node 运行，不判红

判据（双向）：
  - 任一块 node --check 非 0 → 退出码 1（点名段的行号范围与 node 原文）；
  - 一个 JS 块都取不到 → 退出码 2（**取不到对象即 RED，绝不静默通过**）；
  - 全过 → 退出码 0，并打印 `合计：N 通过 / M 失败`。

为什么必须按 .mjs 检查：前端是 `type="module"` 加载的，`node --check x.js` 按 CommonJS
解析对模块语法**假绿**（`pitfalls.md:58` 两次实证）。
"""
import re, subprocess, sys, tempfile, pathlib

BLOCK = re.compile(r"= r'''(.*?)'''|= r\"\"\"(.*?)\"\"\"", re.S)
JSISH = re.compile(r"document\.|await |const |=>|function ")
SUBS = {
    # 🔴 真 runner 是「裸路径」替换（__PAYLOAD__ 在 JS 里已经带引号）——别再加引号
    "__PAYLOAD__": "/tmp/__gate_payload__.json",
    "__OUT__": "/tmp/__gate_out__.json",
    "__QUOTA_WORDS__": "[]",
    "__BANNED_LIST__": "[]",
}


def blocks_of(path: pathlib.Path):
    src = path.read_text(encoding="utf-8", errors="replace")
    out = []
    for m in BLOCK.finditer(src):
        body = m.group(1) if m.group(1) is not None else m.group(2)
        if not JSISH.search(body):
            continue
        start = src.count("\n", 0, m.start()) + 1
        end = src.count("\n", 0, m.end()) + 1
        out.append((start, end, body))
    return out


def main(argv):
    dump = "--dump" in argv
    files = [a for a in argv[1:] if not a.startswith("--")]
    if not files:
        print(__doc__)
        return 2
    ok = bad = missing = 0
    for f in files:
        p = pathlib.Path(f)
        bs = blocks_of(p)
        if not bs:
            print(f"✗ {p}：一个 JS 块都取不到（模式 `= r'''…'''`）——取不到对象即 RED")
            missing += 1
            continue
        for start, end, body in bs:
            js = body
            for k, v in SUBS.items():
                js = js.replace(k, v)
            tmp = pathlib.Path(tempfile.mkdtemp(prefix="gatejs-")) / f"block-{start}.mjs"
            tmp.write_text(js, encoding="utf-8")
            r = subprocess.run(["node", "--check", str(tmp)], capture_output=True, text=True)
            if r.returncode == 0:
                ok += 1
                print(f"✓ {p.name}:{start}-{end}  node --check OK（{len(js.splitlines())} 行）")
            else:
                bad += 1
                err = (r.stderr or "").strip().splitlines()[:4]
                print(f"✗ {p.name}:{start}-{end}  JS SYNTAX FAIL")
                for line in err:
                    print(f"    {line}")
            if dump:
                print(f"    dumped → {tmp}")
    print(f"合计：{ok} 通过 / {bad + missing} 失败")
    if missing:
        return 2
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
