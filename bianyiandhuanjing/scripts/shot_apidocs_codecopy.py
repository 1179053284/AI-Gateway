#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画面取证（PDF 兜底）：对接说明四颗复制钮搬进代码框内右上角后的实际画面。

本机 Ego Lite 无 OS 窗口 ⇒ `Page.captureScreenshot` 必超时（既有事实），沿用跑通的路子：
`Emulation.setDeviceMetricsOverride` 定视口 → `Page.printToPDF` → `qlmanage -t` 转 PNG。
只读：不改配置、不点任何写入钮（复制钮只写剪贴板）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

OUT_DIR = Path("/Users/w/Desktop/Model-Gateway/docs/changes/ui-rounds/20261008-codecopy-button")
URL = "http://127.0.0.1:8300/#/apidocs"

JS = r'''
const fs = await import("node:fs");
const PAYLOAD = JSON.parse(fs.readFileSync("__PAYLOAD__", "utf8"));
const task = await taskSpace("MGW 对接说明钮位画面取证");
let mine = false;
let page;
try { page = await task.page(PAYLOAD.pageLabel); await page.evaluate(() => 1); }
catch (e) { page = await task.newPage(); mine = true; }

const theme0 = await (async () => {
  await page.goto(PAYLOAD.url);
  await page.waitForSelector(".code-shell", { timeout: 20000 });
  return page.evaluate(() => localStorage.getItem("mg-theme"));
})();

const lines = [];
for (const theme of ["light", "dark"]) {
  await page.evaluate((t) => localStorage.setItem("mg-theme", t), theme);
  await page.reload();
  await page.waitForSelector(".code-shell", { timeout: 20000 });
  await page.waitForTimeout(900);
  await page.cdp("Emulation.setDeviceMetricsOverride",
    { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await page.waitForTimeout(260);
  const read = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll(".code-shell").forEach((sh) => {
      const btn = sh.querySelector(".code-copy");
      const vis = [...sh.querySelectorAll("pre.code-block")].find((p) => !p.classList.contains("hidden"));
      const b = btn.getBoundingClientRect(), k = vis.getBoundingClientRect();
      out.push(`${btn.dataset.copygroup}: 上${Math.round(b.top - k.top)}/右${Math.round(k.right - b.right)}`
        + ` 钮${Math.round(b.width)}x${Math.round(b.height)} bg=${getComputedStyle(btn).backgroundColor}`);
    });
    return { n: out.length, lines: out, scrollX: Math.round(document.documentElement.scrollWidth - document.documentElement.clientWidth) };
  });
  lines.push(theme + " 横向溢出=" + read.scrollX + "px ｜ " + read.lines.join(" · "));
  const pdf = await page.cdp("Page.printToPDF",
    { printBackground: true, preferCSSPageSize: false, paperWidth: 15, paperHeight: 9.4,
      marginTop: 0.2, marginBottom: 0.2, marginLeft: 0.2, marginRight: 0.2 });
  fs.writeFileSync(PAYLOAD.outDir + "/apidocs-codecopy-1440-" + theme + ".pdf",
    Buffer.from(pdf.data, "base64"));
}
await page.evaluate((t) => { if (t === null) localStorage.removeItem("mg-theme");
  else localStorage.setItem("mg-theme", t); }, theme0);
try { await page.cdp("Emulation.clearDeviceMetricsOverride", {}); } catch (e) {}
if (mine) { try { await page.close(); } catch (e) {} }
fs.writeFileSync(PAYLOAD.outDir + "/readout.txt", lines.join("\n"), "utf8");
console.log("SHOT_DONE");
'''


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base = OUT_DIR
    pfile = base / "payload.json"
    jfile = base / "shot.js"
    label = f"ccshot-{base.stat().st_mtime_ns % 1000000}"
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
        subprocess.run(["qlmanage", "-t", "-s", "1600", "-o", str(base), str(pdf)],
                       capture_output=True, timeout=120)
        print(("✓ 画面 " if png.exists() else "✗ 转 PNG 失败 ") + str(png if png.exists() else pdf))
    return 0


if __name__ == "__main__":
    sys.exit(main())
