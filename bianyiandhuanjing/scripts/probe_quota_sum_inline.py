#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读探针（:8300 真实数据）：额度格「合计：900 积分」的**几何**是否成立。

用户裁定链（同日三次）：① 否掉折叠 ⇒ 逐组明细常驻；② 占比条左缘固定 + 灰轨道；
③ 本轮「合计：900 积分」⇒ **数值贴在标签后面**、不再右浮到列尾，明细留在自己一行。

判据成对（本仓布局类判据的规矩：只验"贴了"不验"没撑破"= 给自己发通行证）：
  A 标签文本右缘 → 数值文本左缘 ≤ 8px（量 **文本** 边缘，不量 flex 项盒子）；
  B 数值零裁字（被挤的只能是标签那一半）；
  C 单元格 / td / 文档零横向溢出；
  D 明细行仍在且逐组给量；
  E 主行回到一行高（上一版把明细并进主行 ⇒ 实盘长包名折成 5~6 行、整格 112px，正是被否掉的形态）。
零写入：只读 DOM，不点任何钮、不拨任何开关。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

URL = "http://127.0.0.1:8300/#/accounts"

JS = r'''
const fs = await import("node:fs");
const PAYLOAD = JSON.parse(fs.readFileSync("__PAYLOAD__", "utf8"));
const OUT = "__OUT__";
const checks = [];
const extra = { rows: [] };
function ck(id, desc, ok, measured) { checks.push({ id, desc, ok: !!ok, measured: String(measured) }); }

const task = await taskSpace("MGW 额度格合计贴标签探针");
const page = await (async () => {
  try { const p = task.page(PAYLOAD.pageLabel); await p.evaluate(() => 1); return p; }
  catch (e) { return await task.newPage(); }
})();
await page.goto(PAYLOAD.url);
await page.waitForSelector("#ac-table tbody tr", { timeout: 20000 });
await page.waitForTimeout(900);

const data = await page.evaluate(() => {
  const txt = (n) => (n ? String(n.textContent || "").replace(/\s+/g, " ").trim() : "");
  const q = (s, r) => Array.from((r || document).querySelectorAll(s));
  const edge = (n) => { const rg = document.createRange(); rg.selectNodeContents(n);
    return rg.getBoundingClientRect(); };
  const rows = [];
  q("#ac-table tbody tr").forEach((tr) => {
    const tds = q("td", tr);
    const td = tds.find((x) => x.querySelector(".qcell"));
    if (!td) return;
    const cell = td.querySelector(".qcell");
    const row = cell.querySelector(".qrow");
    const nm = row && row.querySelector(".qname");
    const num = row && row.querySelector(".qnum");
    if (!nm || !num) return;
    const chips = cell.querySelector(".qchips");
    rows.push({
      acc: txt(q("td", tr)[0]).slice(0, 24),
      isSum: txt(nm).indexOf("合计") >= 0,
      label: txt(nm),
      value: txt(num),
      // A：标签文本右缘 → 数值文本左缘
      gap: Math.round((edge(num).left - edge(nm).right) * 10) / 10,
      numClip: Math.round((num.scrollWidth - num.clientWidth) * 10) / 10,
      labelClip: Math.round((nm.scrollWidth - nm.clientWidth) * 10) / 10,
      labelTitle: (nm.getAttribute("title") || "").slice(0, 40),
      rowH: Math.round(row.getBoundingClientRect().height),
      cellH: Math.round(cell.getBoundingClientRect().height),
      cellOverflow: Math.round((cell.scrollWidth - cell.clientWidth) * 10) / 10,
      tdOverflow: Math.round((td.scrollWidth - td.clientWidth) * 10) / 10,
      qvalShells: q(".qval", cell).length,
      chipsText: chips ? txt(chips) : "",
      chipN: chips ? q(".qchip", chips).length : 0,
      meta: txt(cell.querySelector(".qmeta")),
    });
  });
  const wrap = document.querySelector("#ac-table").closest(".table-wrap");
  return { rows,
    docOverflow: Math.round((document.documentElement.scrollWidth
      - document.documentElement.clientWidth) * 10) / 10,
    /* 🔴 「表比 main 宽」不是溢出——本库的表本来就住在 `.table-wrap{overflow-x:auto}` 里
       （base.css:295 / accounts.js:529）。我第一版拿 `closest("main")` 当尺子量出 284px 的"溢出"
       是**量错对象**（同一条「量盒子不等于量文本」的课，这次栽在容器上）。
       正确的两问：① 容器存在且宽度差被它自己吸收（`wrap.scrollWidth >= 表宽`）；
       ② 页面本身零横向滚动（`docOverflow`）。 */
    hasWrap: !!wrap,
    wrapAbsorbs: wrap ? (wrap.scrollWidth >= document.querySelector("#ac-table").scrollWidth - 1) : false,
    wrapOverflow: wrap ? Math.round((wrap.scrollWidth - wrap.clientWidth) * 10) / 10 : null };
});

extra.rows = data.rows;
const sums = data.rows.filter((r) => r.isSum);
const all = data.rows;
ck("A", "存在多组行（「合计：」）——没有对象就是空判据", sums.length > 0,
   `多组 ${sums.length} 行 / 有额度格 ${all.length} 行`);
ck("B", "数值贴标签：标签文本右缘 → 数值文本左缘 ≤8px（量 Range 文本边缘，不量 flex 盒子）",
   sums.every((r) => r.gap <= 8 && r.gap > -1),
   "gap=" + sums.map((r) => r.gap + "px").join(" ") + "｜首行=「" + (sums[0] || {}).label + (sums[0] || {}).value + "」");
ck("C", "数值零裁字（被挤的只能是标签那一半；标签可省略号但 title 给全名）",
   all.every((r) => r.numClip <= 0.5),
   "numClip max=" + Math.max(0, ...all.map((r) => r.numClip))
   + "｜labelClip max=" + Math.max(0, ...all.map((r) => r.labelClip))
   + "｜标签有 title=" + all.every((r) => !!r.labelTitle));
ck("D", "语法两半：标签以「：」收尾 + 零右浮 .qval 壳",
   all.every((r) => /[：:]$/.test(r.label) && r.qvalShells === 0),
   "非冒号收尾=" + all.filter((r) => !/[：:]$/.test(r.label)).map((r) => r.label).slice(0, 2).join(" ")
   + " qval壳=" + all.reduce((x, r) => x + r.qvalShells, 0));
ck("E", "不撑破：单元格 / td 零横向溢出 + 页面零横向滚动（表的宽度由 `.table-wrap{overflow-x:auto}` 吸收）",
   all.every((r) => r.cellOverflow <= 0.5 && r.tdOverflow <= 0.5)
   && data.docOverflow <= 1 && data.hasWrap && data.wrapAbsorbs,
   `cell max=${Math.max(0, ...all.map((r) => r.cellOverflow))} td max=${Math.max(0, ...all.map((r) => r.tdOverflow))}`
   + ` 文档横向溢出=${data.docOverflow}px 容器吸收=${data.wrapAbsorbs}（wrap 自身溢出 ${data.wrapOverflow}px，非判据）`);
ck("F", "逐组明细仍在自己一行且给量（多组行 chip 数 ≥2、含数字）",
   sums.every((r) => r.chipN >= 2 && /[0-9]/.test(r.chipsText)),
   "chip 数=" + sums.map((r) => r.chipN).join(" ") + "｜首行明细=「" + ((sums[0] || {}).chipsText || "").slice(0, 70) + "」");
ck("G", "主行回到一行高（上一版把明细并进主行 ⇒ 长包名折 5~6 行、整格 112px，正是被否掉的形态）",
   all.every((r) => r.rowH <= 22),
   "主行高=" + all.map((r) => r.rowH + "px").join(" ") + "｜整格高=" + all.map((r) => r.cellH + "px").join(" "));

fs.writeFileSync(OUT, JSON.stringify({ checks, extra }, null, 1), "utf8");
console.log("PROBE_DONE");
'''


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="mgw-qsum-"))
    pfile = base / "payload.json"
    ofile = base / "results.json"
    jfile = base / "probe.js"
    pfile.write_text(json.dumps({"url": URL, "pageLabel": f"qsum-{base.name[-6:]}"},
                                ensure_ascii=False), encoding="utf-8")
    jfile.write_text(JS.replace("__PAYLOAD__", str(pfile)).replace("__OUT__", str(ofile)),
                     encoding="utf-8")
    with jfile.open("r", encoding="utf-8") as fh:
        proc = subprocess.run(["ego-browser", "nodejs"], stdin=fh, capture_output=True,
                              text=True, timeout=300, cwd=str(base))
    if not ofile.exists():
        print(f"✗ 浏览器没交回读数（rc={proc.returncode}）", file=sys.stderr)
        print("  stdout: " + proc.stdout[-700:], file=sys.stderr)
        print("  stderr: " + proc.stderr[-700:], file=sys.stderr)
        return 2
    data = json.loads(ofile.read_text(encoding="utf-8"))
    rows = data.get("checks", [])
    bad = [c["id"] for c in rows if not c["ok"]]
    for c in rows:
        print(f"  {'✓' if c['ok'] else '✗'} {c['id']} {c['desc']}｜{c['measured'][:210]}")
    print("\n逐行读数：")
    for r in data.get("extra", {}).get("rows", []):
        print(f"  {r['acc']:<24} gap={r['gap']:>5}px 主行高={r['rowH']:>3}px 整格={r['cellH']:>3}px "
              f"裁字(数/标)={r['numClip']}/{r['labelClip']} chip={r['chipN']}")
        print(f"      主行=「{r['label']}{r['value']}」")
        if r["chipsText"]:
            print(f"      明细=「{r['chipsText'][:88]}」")
        print(f"      meta=「{r['meta'][:64]}」")
    print(f"\n合计：{len(rows) - len(bad)} 通过 / {len(bad)} 失败" + (f"  红：{bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
