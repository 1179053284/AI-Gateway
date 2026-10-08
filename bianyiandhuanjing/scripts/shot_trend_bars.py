#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画面取证（PDF 兜底）：总览「今日调用趋势（24h）」与数据看板降级柱状**画出来长什么样**。

本机 Ego Lite 无 OS 窗口 ⇒ `Page.captureScreenshot` 必超时（既有事实），沿用跑通的路子：
`Emulation.setDeviceMetricsOverride` 定视口 → `Page.printToPDF` → `qlmanage -t` 转 PNG。
只读：不改配置、不点任何写入钮。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

OUT_DIR = Path("/Users/w/Desktop/Model-Gateway/docs/changes/ui-rounds/20261008-trend-bars")
BASE = "http://127.0.0.1:8300"

JS = r'''
const fs = await import("node:fs");
const PAYLOAD = JSON.parse(fs.readFileSync("__PAYLOAD__", "utf8"));
const task = await taskSpace("MGW 趋势柱体画面取证");
const page = await (async () => {
  try { const p = task.page(PAYLOAD.pageLabel); await p.evaluate(() => 1); return p; }
  catch (e) { return await task.newPage(); }
})();
await page.cdp("Emulation.setDeviceMetricsOverride",
  { width: 1440, height: 2000, deviceScaleFactor: 1, mobile: false });
const readout = [];

for (const theme of ["light", "dark"]) {
  await page.goto(PAYLOAD.base + "/#/dashboard");
  await page.waitForSelector("#hour-chart > div > div", { timeout: 20000 });
  await page.evaluate((t) => { document.documentElement.setAttribute("data-theme", t);
    localStorage.setItem("mg-theme", t); }, theme);
  await page.reload();
  await page.waitForSelector("#hour-chart > div > div", { timeout: 20000 });
  await page.waitForTimeout(1200);
  readout.push("dashboard " + theme + ": " + JSON.stringify(await page.evaluate(() => {
    const b = document.getElementById("hour-chart").getBoundingClientRect();
    const filled = Array.from(document.querySelectorAll("#hour-chart [title]"))
      .filter((n) => !/· 0 次/.test(n.getAttribute("title") || ""))
      .map((n) => n.getAttribute("title") + "→" + Math.round(n.firstElementChild.getBoundingClientRect().height) + "px");
    return { top: Math.round(b.top), h: Math.round(b.height), filled: filled };
  })));
  const pdf = await page.cdp("Page.printToPDF",
    { printBackground: true, preferCSSPageSize: false, paperWidth: 15, paperHeight: 21.5,
      marginTop: 0.2, marginBottom: 0.2, marginLeft: 0.2, marginRight: 0.2 });
  fs.writeFileSync(PAYLOAD.outDir + "/overview-trend-1440-" + theme + ".pdf",
    Buffer.from(pdf.data, "base64"));
}

/* 数据看板降级腿：屏蔽 Chart.js 后才有对象 */
await page.goto(PAYLOAD.base + "/#/stats");
await page.waitForSelector("#s-chart > *", { timeout: 20000 });
await page.evaluate(() => { window.Chart = undefined; location.hash = "#/dashboard"; });
await page.waitForTimeout(400);
await page.evaluate(() => { location.hash = "#/stats"; });
await page.waitForSelector("#s-chart > div > div", { timeout: 20000 });
await page.waitForTimeout(900);
readout.push("stats cssBars light: " + JSON.stringify(await page.evaluate(() => {
  const b = document.getElementById("s-chart").getBoundingClientRect();
  return { top: Math.round(b.top), h: Math.round(b.height),
    filled: Array.from(document.querySelectorAll("#s-chart [title]"))
      .filter((n) => !/· 0 次/.test(n.getAttribute("title") || ""))
      .map((n) => n.getAttribute("title") + "→" + Math.round(n.firstElementChild.getBoundingClientRect().height) + "px") };
})));
const pdf2 = await page.cdp("Page.printToPDF",
  { printBackground: true, preferCSSPageSize: false, paperWidth: 15, paperHeight: 21.5,
    marginTop: 0.2, marginBottom: 0.2, marginLeft: 0.2, marginRight: 0.2 });
fs.writeFileSync(PAYLOAD.outDir + "/stats-fallback-bars-1440-light.pdf",
  Buffer.from(pdf2.data, "base64"));

fs.writeFileSync(PAYLOAD.outDir + "/readout.txt", readout.join("\n"), "utf8");
console.log("SHOT_DONE");
'''


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pfile = OUT_DIR / "payload.json"
    jfile = OUT_DIR / "shot.js"
    pfile.write_text(json.dumps({"base": BASE, "outDir": str(OUT_DIR),
                                 "pageLabel": "mgw-trend-shot"}, ensure_ascii=False),
                     encoding="utf-8")
    jfile.write_text(JS.replace("__PAYLOAD__", str(pfile)), encoding="utf-8")
    with jfile.open("r", encoding="utf-8") as fh:
        proc = subprocess.run(["ego-browser", "nodejs"], stdin=fh, capture_output=True,
                              text=True, timeout=420, cwd=str(OUT_DIR))
    print(proc.stdout[-1500:])
    if proc.returncode != 0:
        print("stderr: " + proc.stderr[-1200:], file=sys.stderr)
        return 1
    for pdf in sorted(OUT_DIR.glob("*.pdf")):
        subprocess.run(["qlmanage", "-t", "-s", "1600", "-o", str(OUT_DIR), str(pdf)],
                       capture_output=True, timeout=120)
    pngs = sorted(OUT_DIR.glob("*.png"))
    print("\nPNG：")
    for p in pngs:
        print(f"  {p}")
    rp = OUT_DIR / "readout.txt"
    if rp.exists():
        print("\n读数：")
        print(rp.read_text(encoding="utf-8"))
    return 0 if pngs else 1


if __name__ == "__main__":
    sys.exit(main())
