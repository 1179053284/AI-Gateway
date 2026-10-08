#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""撤证（变异）：对接说明复制钮那三条几何判据**能不能红**。

🔴 不在共享工作树上改 base.css（并行会话正在同一棵树跑门，改 60 秒就会送他们一条假红）
⇒ 变异打在**浏览器运行时 CSSOM** 上：注入"坏形状"规则，读数走的是与主探针完全相同的
READ 路径（同一把尺），只有计算样式不同。坏形状必须让对应判据变红，否则那条判据是空判据。

  M1 撤掉块顶预留带（padding-top 42px → 13px）⇒ 窄屏折行代码压进钮下 ⇒ A3/A8 类读数必须红；
  M2 间距打回 2px（top/right 8px → 2px）⇒ A2 类读数必须红；
  M3 钮搬回框外（position:static）⇒ "钮在框内"读数必须红。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

URL = "http://127.0.0.1:8300/#/apidocs"

JS = r'''
const fs = await import("node:fs");
const PAYLOAD = JSON.parse(fs.readFileSync("__PAYLOAD__", "utf8"));
const OUT = "__OUT__";
const checks = [];
function ck(id, desc, ok, measured) { checks.push({ id, desc, ok: !!ok, measured: String(measured) }); }

const task = await taskSpace("MGW 对接说明钮位撤证");
let mine = false;
let page;
try { page = await task.page(PAYLOAD.pageLabel); await page.evaluate(() => 1); }
catch (e) { page = await task.newPage(); mine = true; }

const setViewport = async (w, h) => {
  await page.cdp("Emulation.setDeviceMetricsOverride",
    { width: w, height: h, deviceScaleFactor: 1, mobile: false });
  await page.waitForTimeout(300);
};

/* 与主探针同一把尺（READ），返回每块的 上/右间距、重叠数、是否在框内 */
const READ = () => {
  return [...document.querySelectorAll(".code-shell")].map((sh) => {
    const btn = sh.querySelector(".code-copy");
    const vis = [...sh.querySelectorAll("pre.code-block")].find((p) => !p.classList.contains("hidden"));
    const b = btn.getBoundingClientRect();
    const k = vis.getBoundingClientRect();
    const rg = document.createRange(); rg.selectNodeContents(vis);
    const lines = [...rg.getClientRects()].filter((r) => r.width > 0 && r.height > 0);
    const hit = lines.filter((r) => r.bottom > b.top && r.top < b.bottom && r.right > b.left && r.left < b.right);
    const r1 = (n) => Math.round(n * 10) / 10;
    return {
      key: btn.dataset.copygroup,
      topGap: r1(b.top - k.top), rightGap: r1(k.right - b.right),
      overlap: hit.length,
      inBox: b.top >= k.top - 0.5 && b.left >= k.left - 0.5 && b.right <= k.right + 0.5 && b.bottom <= k.bottom + 0.5,
    };
  });
};

const inject = (css) => page.evaluate((c) => {
  const st = document.createElement("style");
  st.id = "__mgw_mutation__";
  st.textContent = c;
  document.head.appendChild(st);
}, css);
const removeMutation = () => page.evaluate(() => {
  const n = document.getElementById("__mgw_mutation__"); if (n) n.remove();
});

await setViewport(1440, 900);
await page.goto(PAYLOAD.url);
await page.waitForSelector(".code-shell", { timeout: 20000 });
const theme0 = await page.evaluate(() => localStorage.getItem("mg-theme"));
await page.evaluate(() => localStorage.setItem("mg-theme", "light"));
await page.reload();
await page.waitForSelector(".code-shell", { timeout: 20000 });
await page.waitForTimeout(900);

/* 基线（同一把尺，先证明"好形状"在这一轮里也是绿的，否则下面的红没有对照） */
const base = await page.evaluate(READ);
ck("M0", "基线：未注入变异时三条读数全为好形状（上8/右8/零重叠/框内）",
   base.every((x) => x.topGap === 8 && x.rightGap === 8 && x.overlap === 0 && x.inBox),
   base.map((x) => `${x.key} 上${x.topGap}/右${x.rightGap}/重叠${x.overlap}/框内${x.inBox}`).join(" "));

/* M1 撤掉预留带 —— 窄屏 */
await setViewport(420, 900);
await inject(".code-shell > .code-block { padding-top: 13px !important; }");
await page.waitForTimeout(260);
const m1 = await page.evaluate(READ);
await removeMutation();
await setViewport(1440, 900);
await page.waitForTimeout(260);
ck("M1", "撤掉块顶预留带 ⇒ 窄屏折行代码压进钮下（重叠数 > 0 才算这条判据有效）",
   m1.some((x) => x.overlap > 0),
   m1.map((x) => `${x.key} 重叠${x.overlap}`).join(" "));

/* M2 间距打回 2px */
await inject(".btn.code-copy { top: 2px !important; right: 2px !important; }");
await page.waitForTimeout(260);
const m2 = await page.evaluate(READ);
await removeMutation();
ck("M2", "间距改成 2px ⇒ 上/右间距读数跟着变（判据不是恒真）",
   m2.every((x) => x.topGap === 2 && x.rightGap === 2),
   m2.map((x) => `${x.key} 上${x.topGap}/右${x.rightGap}`).join(" "));

/* M3 钮搬回框外（绝对定位失效 = 回到"悬在块外"的旧形状） */
await inject(".btn.code-copy { position: static !important; }");
await page.waitForTimeout(260);
const m3 = await page.evaluate(READ);
await removeMutation();
ck("M3", "钮改回静态（搬出框外）⇒ inBox 读数必须为否",
   m3.some((x) => !x.inBox),
   m3.map((x) => `${x.key} 框内${x.inBox}`).join(" "));

/* 复位：主题回原值 + 视口回原生 + 关掉自己开的标签页 */
await page.evaluate((t) => { if (t === null) localStorage.removeItem("mg-theme");
  else localStorage.setItem("mg-theme", t); }, theme0);
try { await page.cdp("Emulation.clearDeviceMetricsOverride", {}); } catch (e) {}
if (mine) { try { await page.close(); } catch (e) {} }

fs.writeFileSync(OUT, JSON.stringify({ checks }, null, 2), "utf8");
'''


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="mgw-codecopy-mut-"))
    pfile = base / "payload.json"
    ofile = base / "results.json"
    jfile = base / "probe.js"
    pfile.write_text(json.dumps({"url": URL, "pageLabel": f"ccm-{base.name[-7:]}"},
                                ensure_ascii=False), encoding="utf-8")
    jfile.write_text(JS.replace("__PAYLOAD__", str(pfile)).replace("__OUT__", str(ofile)),
                     encoding="utf-8")
    with jfile.open("r", encoding="utf-8") as fh:
        proc = subprocess.run(["ego-browser", "nodejs"], stdin=fh, capture_output=True,
                              text=True, timeout=300, cwd=str(base))
    if not ofile.exists():
        print(f"✗ 浏览器没交回读数（rc={proc.returncode}）", file=sys.stderr)
        print("  stdout: " + proc.stdout[-900:], file=sys.stderr)
        print("  stderr: " + proc.stderr[-900:], file=sys.stderr)
        return 2
    data = json.loads(ofile.read_text(encoding="utf-8"))
    rows = data.get("checks", [])
    bad = [c["id"] for c in rows if not c["ok"]]
    for c in rows:
        print(f"  {'✓' if c['ok'] else '✗'} {c['id']} {c['desc']}｜{c['measured'][:240]}")
    print(f"\n合计：{len(rows) - len(bad)} 通过 / {len(bad)} 失败"
          + (f"  红：{bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
