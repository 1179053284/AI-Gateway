#!/usr/bin/env python3
"""前端 ES 模块「import/export 契约」机械校验（补 2026-10-06 拆分轮暴露的门盲区）。

用法：
  python3 check_esm_symbols.py [<js_dir>] [--all]
  默认目录 = coding/model_gateway/web/static/js；默认跳过 vendor/（压缩产物噪声大）。

两条腿（静态、零启发式猜测，只做确定性解析）：
  ① import 目标存在性 —— `import … from "./x.js"` 解析后的目标文件必须在盘上。
     锚：2026-10-06 P0#1（`../api.js` 应为 `../../api.js` ⇒ 模块图解析失败 ⇒ 全站 8 页无渲染，
     而 vm 静态门剥掉 import 拼接、看不见这一层）。
  ② 具名 import 在目标里确有导出 —— `import { A, B as C } from "./x.js"` 的名字必须 ∈
     x.js 的 {export function/const/let/var/class, export {…}, export default}。
     锚：同日前两次 P0（子模块引用了主文件未导出/未 import 的符号，页面空白/弹窗报错）。

🔴 第三条腿「未定义引用」（段内引用 ∩ 全部导出 − 段内定义 − 已 import）**本脚本不提供**：
   10-07 实测三次启发式实现全被正则字面量/模板串/Tab 键名打成大面积误报（恒红的检查器 = 没检查器）。
   该腿的权威做法是**运行期**：逐模块 `node --input-type=module -e "import('file:///…')"` + 真浏览器逐页渲染。
   本脚本只保证「模块图契约」这一层，跑绿 ≠ 页面能渲染。

判据（双向）：
  - 任一腿有发现 → rc=1，逐条点名 file:line；
  - 目录不存在 / 一支 .js 都没扫到 → rc=2（**取不到对象即 RED，绝不静默通过**）；
  - 全过 → rc=0，并打印 `合计：N 通过 / M 失败（扫描 N 支 .js）`。
"""
import pathlib, re, sys

BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.M)
IMPORT_STMT = re.compile(r"""import\s+(?:([\w$]+)\s*,?\s*)?(?:\{([^}]*)\})?\s*from\s*["']([^"']+)["']|import\s*["']([^"']+)["']""")


def strip_comments(src: str) -> str:
    # 块注释按原换行数占位，保住行号（否则报的行号对不上源文件）
    src = BLOCK_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), src)
    return LINE_COMMENT.sub("", src)


def parse_imports(code: str):
    out = []
    for m in IMPORT_STMT.finditer(code):
        target = m.group(3) or m.group(4)
        named = []
        if m.group(2):
            for part in m.group(2).split(","):
                part = part.strip()
                if part and " as " in part:
                    named.append(part.split(" as ")[-1].strip())
                elif part:
                    named.append(part)
        ln = code.count("\n", 0, m.start()) + 1
        out.append((target, m.group(1), named, ln))
    return out


def parse_exports(code: str):
    exported = set()
    for m in re.finditer(r"\bexport\s+(?:async\s+)?(?:function|class)\s+([\w$]+)", code):
        exported.add(m.group(1))
    for m in re.finditer(r"\bexport\s+(?:const|let|var)\s+([\w$]+)", code):
        exported.add(m.group(1))
    for m in re.finditer(r"\bexport\s*\{([^}]*)\}", code):
        for part in m.group(1).split(","):
            part = part.strip()
            if part:
                exported.add(part.split(" as ")[-1].strip())
    if re.search(r"\bexport\s+default\b", code):
        exported.add("default")
    return exported


def main(argv):
    root = pathlib.Path(next((a for a in argv[1:] if not a.startswith("--")), "coding/model_gateway/web/static/js"))
    if not root.exists():
        print(f"✗ 目录不存在：{root}（取不到对象即 RED）")
        return 2
    files = [f for f in sorted(root.rglob("*.js")) if "vendor" not in f.parts or "--all" in argv]
    if not files:
        print(f"✗ {root} 一支 .js 都没有（取不到对象即 RED）")
        return 2
    exports_cache, ok, bad = {}, 0, 0
    for f in files:
        code = strip_comments(f.read_text(encoding="utf-8", errors="replace"))
        problems = []
        for target, default, named, ln in parse_imports(code):
            if not target or not target.startswith("."):
                continue
            tgt = (f.parent / target).resolve()
            if not tgt.exists():
                problems.append(f"  :{ln} import 目标不存在 → {target}")
                continue
            if named:
                if tgt not in exports_cache:
                    exports_cache[tgt] = parse_exports(strip_comments(tgt.read_text(encoding="utf-8", errors="replace")))
                missing = sorted(x for x in named if x not in exports_cache[tgt])
                if missing:
                    problems.append(f"  :{ln} {tgt.name} 未导出 → {', '.join(missing)}")
        if problems:
            bad += 1
            print(f"✗ {f.relative_to(root)}")
            print("\n".join(problems[:20]))
        else:
            ok += 1
    print(f"合计：{ok} 通过 / {bad} 失败（扫描 {len(files)} 支 .js）")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
