#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画面取证（PDF 兜底）：接入账号页额度列「合计：数值」的实际形态。

本机 Ego Lite 无 OS 窗口 ⇒ `Page.captureScreenshot` 必超时（既有事实），
沿用上一轮跑通的路子：`Emulation.setDeviceMetricsOverride` 定视口 → `Page.printToPDF`
→ `qlmanage -t` 转 PNG。只读：不改配置、不点任何写入钮。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

OUT_DIR = Path("/Users/w/Desktop/Model-Gateway/docs/changes/ui-rounds/20261003-quota-sum")
URL = "http://127.0.0.1:8300/#/accounts"

JS = r'''
const fs = await import("node:fs");
const PAYLOAD = JSON.parse(fs.readFileSync("__PAYLOAD__", "utf8"));
const task = await taskSpace("MGW 额度格合计贴标签画面取证");
const page = await (async () => {
  try { const p = task.page(PAYLOAD.pageLabel); await p.evaluate(() => 1); return p; }
  catch (e) { return await task.newPage(); }
})();
const errs = [];
for (const theme of ["light", "dark"]) {
  await page.goto(PAYLOAD.url);
  await page.evaluate((t) => { document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("mgw-theme", t); } catch (e) {} }, theme);
  await page.waitForSelector("#ac-table tbody tr", { timeout: 20000 });
  await page.waitForTimeout(1200);
  await page.cdp("Emulation.setDeviceMetricsOverride",
    { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  const read = await page.evaluate(() => {
    const q = (s) => Array.from(document.querySelectorAll(s));
    const rows = q("#ac-table tbody tr").filter((tr) => tr.querySelector(".qname"));
    return { n: rows.length,
      first: rows[0] ? String(rows[0].querySelector(".qrow").textContent).replace(/\s+/g, " ").trim() : "",
      chips: rows[0] ? String((rows[0].querySelector(".qchips") || {}).textContent || "").replace(/\s+/g, " ").trim() : "",
      overflow: Math.round(document.documentElement.scrollWidth - document.documentElement.clientWidth) };
  });
  errs.push(theme + ": " + JSON.stringify(read));
  const pdf = await page.cdp("Page.printToPDF",
    { printBackground: true, preferCSSPageSize: false, paperWidth: 15, paperHeight: 9.4,
      marginTop: 0.2, marginBottom: 0.2, marginLeft: 0.2, marginRight: 0.2 });
  fs.writeFileSync(PAYLOAD.outDir + "/quota-sum-1440-" + theme + ".pdf",
    Buffer.from(pdf.data, "base64"));
}
fs.writeFileSync(PAYLOAD.outDir + "/readout.txt", errs.join("\n"), "utf8");
console.log("SHOT_DONE");
'''


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base = OUT_DIR
    pfile = base / "payload.json"
    jfile = base / "shot.js"
    label = f"qshot-{base.stat().st_mtime_ns % 1000000}"
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
        subprocess.run(["qlmanage", "-t", "-s", "1600", "-o", str(base), str(pdf)],
                       capture_output=True, timeout=120)
        print(("✓ 画面 " if png.exists() else "✗ 转 PNG 失败 ") + str(png if png.exists() else pdf))
    return 0


if __name__ == "__main__":
    sys.exit(main())
