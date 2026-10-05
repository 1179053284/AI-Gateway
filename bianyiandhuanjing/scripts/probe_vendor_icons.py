#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真机只读探针 + 画面取证：「网关模型管理」左栏厂商卡头的官方图标。

对应 2026-10-03 用户实拍（rail 里 20px 方块画的是我手绘的首字母「商」「D」）。
判的是**画出来的东西**，不是源码字面（源码那侧由 `tests/unit/test_v2_vendor_icons.py` 钉）：
  I1 六个厂商卡头**全部**是 `<img>`，零裸字母
  I2 每枚图**真的加载成功**（`complete && naturalWidth>=64`）——404 的破图在 20px 下肉眼极易漏
  I3 渲染尺寸 20×20 且带圆角（与账号页产品图标同一形状，不是把 128px 原图摊出来）
  I4 图标与厂商名同一行、垂直居中不偏（baseline 对齐会跟着字高跑）
  I5 左栏无横向溢出（图标是最宽的固定列时容易顶出去）
  I6 「自定义模型」组仍是设计内的字母回落（判据不许把回落一起算成漏改）
  I7 页面本体渲染成功（启动标记为真、无错误卡、详情区在场）
  I8 详情头卡那枚 40px 也是官方图标（与 rail 同一批资产；同一屏里不许一处图标一处字母）

本机 Ego Lite 无 OS 窗口 ⇒ `Page.captureScreenshot` 必超时（既有事实），
画面走 `Page.printToPDF` → `qlmanage -t` 转 PNG。全程只读：不改配置、不点任何写入钮。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

OUT_DIR = Path("/Users/w/Desktop/Model-Gateway/docs/changes/ui-rounds/20261003-vendor-icons")
URL = "http://127.0.0.1:8300/#/models"
WANT = ["商汤 SenseNova", "DeepSeek", "智谱 GLM", "Moonshot Kimi", "Anthropic", "OpenAI"]

JS = r'''
const fs = await import("node:fs");
const PAYLOAD = JSON.parse(fs.readFileSync("__PAYLOAD__", "utf8"));
const task = await taskSpace("MGW 厂商官方图标真机取证");
const page = await (async () => {
  try { const p = task.page(PAYLOAD.pageLabel); await p.evaluate(() => 1); return p; }
  catch (e) { return await task.newPage(); }
})();
const results = [];

for (const theme of ["light", "dark"]) {
  await page.goto(PAYLOAD.url);
  await page.evaluate((t) => { document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("mgw-theme", t); } catch (e) {} }, theme);
  await page.waitForSelector("#content .panel-split .subnav .group-card", { timeout: 20000 });
  await page.waitForTimeout(1500);
  await page.cdp("Emulation.setDeviceMetricsOverride",
    { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await page.waitForTimeout(300);

  const r = await page.evaluate((want) => {
    const cards = Array.from(document.querySelectorAll("#content .subnav .group-card"));
    const items = [];
    const other = [];
    for (const card of cards) {
      const head = card.querySelector("div");
      const mark = card.querySelector(".mark-sm");
      if (!head || !mark) continue;
      const label = String(head.textContent).replace(/\s+/g, " ").trim();
      // 厂商卡 vs 「自定义模型」卡：只有前者带 `目录 N 个模型 / 已接入 M` 的 title
      if (!/目录/.test(head.getAttribute("title") || "")) {
        other.push({ label: label.slice(0, 20), text: String(mark.textContent).trim(), hasImg: !!mark.querySelector("img") });
        continue;
      }
      const img = mark.querySelector("img");
      const mr = mark.getBoundingClientRect();
      const ir = img ? img.getBoundingClientRect() : null;
      const cs = getComputedStyle(mark);
      items.push({
        label: label.slice(0, 26),
        hasImg: !!img,
        src: img ? (img.getAttribute("src") || "") : "",
        natural: img ? img.naturalWidth : 0,
        loaded: img ? !!img.complete && img.naturalWidth > 0 : false,
        w: Math.round(mr.width * 100) / 100,
        h: Math.round(mr.height * 100) / 100,
        radius: cs.borderRadius,
        bg: cs.backgroundColor,
        // 图标与厂商名是否同一行：纵向中心差
        dy: (() => {
          if (!ir) return null;
          const name = Array.from(head.querySelectorAll("span")).find((s) => s !== mark && s.textContent.trim());
          if (!name) return null;
          const nr = name.getBoundingClientRect();
          return Math.round(((mr.top + mr.height / 2) - (nr.top + nr.height / 2)) * 100) / 100;
        })(),
      });
    }
    const rail = document.querySelector("#content .subnav");
    return {
      cards: items,
      other: other,
      railOverflow: rail ? Math.round((rail.scrollWidth - rail.clientWidth) * 100) / 100 : null,
      pageOverflow: Math.round((document.documentElement.scrollWidth - document.documentElement.clientWidth) * 100) / 100,
      letterMarks: items.filter((i) => !i.hasImg).map((i) => i.label),
      ok: !!document.querySelector("#content .panel-split"),
      // 兜底错误条的判据用**启动标记 + 错误卡本身**：整页 textContent 里永远有那句字符串
      // （它就写在 index.html 的内联 `<script>` 里，而 script 的文本算进 textContent）
      // ⇒ 拿字符串扫 body 是一条**永远为真的假判据**（本轮第一次跑就被它打了红）。
      booted: window.__MG_BOOTED === true,
      errorCard: !!document.querySelector("#content .center-card h2"),
      hasDetail: !!document.querySelector("#md-detail"),
      // 详情头卡那枚 40px：同一块品牌在同一屏里不许一处官方图标、一处字母
      headLogo: (() => {
        const b = document.querySelector("#md-detail .logo-block");
        if (!b) return null;
        const im = b.querySelector("img");
        const r = b.getBoundingClientRect();
        return { hasImg: !!im, src: im ? im.getAttribute("src") : "",
          natural: im ? im.naturalWidth : 0, dark: b.classList.contains("dark"),
          w: Math.round(r.width), h: Math.round(r.height),
          text: String(b.textContent).trim() };
      })(),
    };
  }, PAYLOAD.want);

  const known = PAYLOAD.want;
  const byLabel = {};
  for (const i of r.cards) byLabel[i.label] = i;
  const missing = known.filter((v) => !r.cards.some((i) => i.label.startsWith(v)));
  const notLoaded = r.cards.filter((i) => i.hasImg && !i.loaded).map((i) => i.src);
  const badBox = r.cards.filter((i) => Math.abs(i.w - 20) > 0.6 || Math.abs(i.h - 20) > 0.6)
    .map((i) => `${i.label}:${i.w}x${i.h}`);
  const noRadius = r.cards.filter((i) => parseFloat(i.radius) < 1).map((i) => i.label);
  const misaligned = r.cards.filter((i) => i.dy !== null && Math.abs(i.dy) > 2)
    .map((i) => `${i.label}:${i.dy}`);

  const pass = (name, ok, detail) => results.push(`${ok ? "✓" : "✗"} ${theme} ${name}${detail ? " — " + detail : ""}`);
  pass("I1 全部厂商卡头是真图标（零裸字母）", r.letterMarks.length === 0 && missing.length === 0,
    `裸字母=${JSON.stringify(r.letterMarks)} 缺卡=${JSON.stringify(missing)}`);
  pass("I2 每枚图加载成功（naturalWidth>=64）", notLoaded.length === 0 &&
    r.cards.every((i) => i.natural >= 64),
    `失败=${JSON.stringify(notLoaded)} natural=${JSON.stringify(r.cards.map((i) => i.natural))}`);
  pass("I3 渲染 20×20 + 圆角", badBox.length === 0 && noRadius.length === 0,
    `尺寸异常=${JSON.stringify(badBox)} 无圆角=${JSON.stringify(noRadius)} 底色=${JSON.stringify([...new Set(r.cards.map((i) => i.bg))])}`);
  pass("I4 与厂商名同一行垂直居中（|Δy|<=2px）", misaligned.length === 0,
    `偏差=${JSON.stringify(misaligned)}`);
  pass("I5 无横向溢出", r.railOverflow <= 0 && r.pageOverflow <= 0,
    `rail=${r.railOverflow} page=${r.pageOverflow}`);
  // 「自定义模型」那一组没有厂商可查 ⇒ 首字母 `?` 是**设计内的回落**，不是漏改
  pass("I6 回落只留给无官方资产的分组（自定义组仍是字母）",
    r.other.every((o) => !o.hasImg && o.text === "?"),
    `非厂商卡=${JSON.stringify(r.other)}`);
  // 脚本没加载成功时整页是错误条（本轮之前的真实事故形态）⇒ 页面骨架 + 详情区必须在
  pass("I7 页面本体渲染成功（启动标记为真、无错误卡、详情区在场）",
    r.ok && r.booted && !r.errorCard && r.hasDetail,
    `booted=${r.booted} 错误卡=${r.errorCard} detail=${r.hasDetail}`);
  // 详情头卡 40px 与 rail 20px 是**同一块品牌**：同一屏里不许一处官方图标、一处首字母
  const railSrcs = r.cards.map((i) => i.src);
  const hl = r.headLogo;
  pass("I8 详情头卡 40px 也是官方图标（且用的是 rail 同一批资产、不再铺品牌底色）",
    !!hl && hl.hasImg && hl.natural >= 64 && !hl.dark && hl.w === 40 && hl.h === 40
    && railSrcs.indexOf(hl.src) >= 0,
    `读数=${JSON.stringify(hl)} 在 rail 资产集内=${hl ? railSrcs.indexOf(hl.src) : -1}`);
  results.push(`  ${theme} 读数: ${JSON.stringify(r.cards.map((i) => ({ l: i.label, s: i.src, n: i.natural })))}`);

  const pdf = await page.cdp("Page.printToPDF",
    { printBackground: true, preferCSSPageSize: false, paperWidth: 15, paperHeight: 9.4,
      marginTop: 0.2, marginBottom: 0.2, marginLeft: 0.2, marginRight: 0.2 });
  fs.writeFileSync(`${PAYLOAD.outDir}/vendor-icons-1440-${theme}.pdf`,
    Buffer.from(pdf.data, "base64"));
}
fs.writeFileSync(`${PAYLOAD.outDir}/readout.txt`, results.join("\n"), "utf8");
console.log("PROBE_DONE");
'''


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base = OUT_DIR
    pfile = base / "payload.json"
    jfile = base / "probe.js"
    label = f"vishot-{base.stat().st_mtime_ns % 1000000}"
    pfile.write_text(json.dumps({"url": URL, "outDir": str(base), "pageLabel": label,
                                 "want": WANT}, ensure_ascii=False), encoding="utf-8")
    jfile.write_text(JS.replace("__PAYLOAD__", str(pfile)), encoding="utf-8")
    with jfile.open("r", encoding="utf-8") as fh:
        proc = subprocess.run(["ego-browser", "nodejs"], stdin=fh, capture_output=True,
                              text=True, timeout=300, cwd=str(base))
    out = base / "readout.txt"
    if not out.exists():
        print(f"✗ 没拿到读数（rc={proc.returncode}）", file=sys.stderr)
        print(proc.stdout[-800:], proc.stderr[-800:], file=sys.stderr)
        return 2
    text = out.read_text(encoding="utf-8")
    print(text)
    fails = [ln for ln in text.splitlines() if ln.startswith("✗")]
    for pdf in sorted(base.glob("*.pdf")):
        subprocess.run(["qlmanage", "-t", "-s", "1600", "-o", str(base), str(pdf)],
                       capture_output=True, timeout=120)
        png = pdf.with_suffix(".pdf.png")
        print(("✓ 画面 " if png.exists() else "✗ 转 PNG 失败 ") + str(png if png.exists() else pdf))
    print(f"合计：{len([l for l in text.splitlines() if l.startswith('✓')])} 通过 / "
          f"{len(fails)} 失败")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
