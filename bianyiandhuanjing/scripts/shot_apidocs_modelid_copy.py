#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画面取证（PDF 兜底）：对接说明「当前可服务模型」表的模型 ID 后那颗复制钮长什么样。

本机 Ego Lite 无 OS 窗口 ⇒ `Page.captureScreenshot` 必超时（既有事实），沿用跑通的路子：
定高视口 → `Page.printToPDF`（纸张高度按文档实际高度算 ⇒ 整页进一张）→ `qlmanage -t` 转 PNG。
只读：不改配置、不点任何写入钮（复制钮只写剪贴板，这里连点都不点）。
🔴 本库正文住在内部滚动容器里（`document.scrollHeight` 恒等于视口高），所以画面取证必须
**先把视口拉到能装下整张表的高度**再 printToPDF —— 按 900 高打出来的那张只有页头，表在滚动区外。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

OUT_DIR = Path("/Users/w/Desktop/Model-Gateway/docs/changes/ui-rounds/20261008-modelid-copy")
URL = "http://127.0.0.1:8300/#/apidocs"

JS = r'''
const fs = await import("node:fs");
const PAYLOAD = JSON.parse(fs.readFileSync("__PAYLOAD__", "utf8"));
const task = await taskSpace("MGW 对接说明模型ID复制钮画面取证");
let mine = false;
let page;
try { page = await task.page(PAYLOAD.pageLabel); await page.evaluate(() => 1); }
catch (e) { page = await task.newPage(); mine = true; }

const theme0 = await (async () => {
  await page.goto(PAYLOAD.url);
  await page.waitForSelector("table.tbl", { timeout: 20000 });
  return page.evaluate(() => localStorage.getItem("mg-theme"));
})();

const MEASURE = () => {
  const tbl = [...document.querySelectorAll("table.tbl")].find(
    (t) => [...t.querySelectorAll("th")].some((h) => h.textContent.trim() === "模型 ID"));
  const box = tbl.getBoundingClientRect();
  const rows = [...tbl.querySelectorAll("tbody tr")];
  const r0 = rows[0].getBoundingClientRect();
  const td = rows[0].children[0];
  const btn = td.querySelector("[data-idcopy]");
  const b = btn.getBoundingClientRect();
  const cs = getComputedStyle(btn);
  const svg = btn.querySelector("svg").getBoundingClientRect();
  return {
    viewH: innerHeight,
    tableTop: Math.ceil(box.top + scrollY),
    tableBottom: Math.ceil(box.bottom + scrollY),
    rowH: Math.round(r0.height),
    btnBox: [Math.round(b.width), Math.round(b.height)],
    svgBox: [Math.round(svg.width), Math.round(svg.height)],
    color: cs.color,
    idText: td.textContent.replace(/\s+/g, " ").trim(),
    rows: rows.length,
  };
};

const readout = [];
for (const theme of ["light", "dark"]) {
  await page.evaluate((t) => localStorage.setItem("mg-theme", t), theme);
  await page.reload();
  await page.waitForSelector("table.tbl", { timeout: 20000 });
  await page.waitForTimeout(1000);
  await page.cdp("Emulation.setDeviceMetricsOverride",
    { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await page.waitForTimeout(260);
  const probe = await page.evaluate(MEASURE);
  const needH = Math.min(4600, probe.tableBottom + 80);
  await page.cdp("Emulation.setDeviceMetricsOverride",
    { width: 1440, height: needH, deviceScaleFactor: 1, mobile: false });
  await page.waitForTimeout(420);
  const m = await page.evaluate(MEASURE);
  readout.push(`${theme}: 视口 1440×${needH}px（表底 ${probe.tableBottom}px）`
    + ` 表起点=${m.tableTop} 表底=${m.tableBottom} 整表进画面=${m.tableBottom <= needH}`
    + ` 行高=${m.rowH} 钮${m.btnBox} svg${m.svgBox} 色=${m.color} 行数=${m.rows} 首格文本=「${m.idText}」`);
  const paperH = Math.ceil((needH / 96) * 10) / 10 + 0.6;
  const pdf = await page.cdp("Page.printToPDF",
    { printBackground: true, preferCSSPageSize: false, paperWidth: 15, paperHeight: paperH,
      marginTop: 0.2, marginBottom: 0.2, marginLeft: 0.2, marginRight: 0.2 });
  fs.writeFileSync(PAYLOAD.outDir + `/apidocs-modelid-1440-${theme}.pdf`,
    Buffer.from(pdf.data, "base64"));
  readout.push(`${theme}: 纸张 15×${paperH}in（整页一张）`);
}

await page.evaluate((t) => { if (t === null) localStorage.removeItem("mg-theme");
  else localStorage.setItem("mg-theme", t); }, theme0);
try { await page.cdp("Emulation.clearDeviceMetricsOverride", {}); } catch (e) {}
if (mine) { try { await page.close(); } catch (e) {} }
fs.writeFileSync(PAYLOAD.outDir + "/readout.txt", readout.join("\n"), "utf8");
console.log("SHOT_DONE");
'''


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base = OUT_DIR
    pfile = base / "payload.json"
    jfile = base / "shot.js"
    label = f"idcshot-{base.stat().st_mtime_ns % 1000000}"
    pfile.write_text(json.dumps({"url": URL, "outDir": str(base), "pageLabel": label},
                                ensure_ascii=False), encoding="utf-8")
    jfile.write_text(JS.replace("__PAYLOAD__", str(pfile)), encoding="utf-8")
    with jfile.open("r", encoding="utf-8") as fh:
        proc = subprocess.run(["ego-browser", "nodejs"], stdin=fh, capture_output=True,
                              text=True, timeout=300, cwd=str(base))
    out = base / "readout.txt"
    if not out.exists():
        print(f"✗ 没拿到读数（rc={proc.returncode}）", file=sys.stderr)
        print(proc.stdout[-600:], proc.stderr[-600:], file=sys.stderr)
        return 2
    print(out.read_text(encoding="utf-8"))
    for pdf in sorted(base.glob("*.pdf")):
        png = pdf.with_suffix(".pdf.png")
        if png.exists():
            png.unlink()
        subprocess.run(["qlmanage", "-t", "-s", "3000", "-o", str(base), str(pdf)],
                       capture_output=True, timeout=180)
        print(("✓ 画面 " if png.exists() else "✗ 转 PNG 失败 ") + str(png if png.exists() else pdf))
    return 0


if __name__ == "__main__":
    sys.exit(main())
