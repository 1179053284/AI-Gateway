#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真机只读探针：「网关模型管理」参数配置卡画出来的样子（2026-10-04 参数卡排查轮）。

源码契约级由 `verify_model_param_card.mjs` 钉；本探针判的是**画出来的东西**：

  A1 每张 chat 参数卡：参数行数与依据行数相等（不许有行没依据）
  A2 空态（档案与已设值都为空的模型）不得出现那句谎话「也未设置网关参数」
  A3 只读段 `#md-injected` 恰两行，且 max_tokens 那行带着**实际规格值**（不是空话）
  A4 `glm-5.2` 的 max_tokens 行 × 提示写出「改由统一规格注入 131072」（清空的方向）
  A5 images 模型按定版不渲染参数卡（判据不许把设计内回落算成漏改）
  A6 参数卡与只读段所在卡片零横向溢出（两列栅格 + 长依据文字最容易顶出去）
  A7 依据列是**可见文本**（不是只住在 title 上：悬停不算看见过）
  A8 页面启动标记在、无错误卡（脚本没炸）

全程只读：不点任何写入钮、不改配置。本机 Ego Lite 无 OS 窗口时画面走 PDF 兜底。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

OUT_DIR = Path("/Users/w/Desktop/Model-Gateway/docs/changes/ui-rounds/20261004-param-card")
# 默认打在 :8300（真实例，只读）；本轮档案回填的真机核验用隔离实例：
#   MGW_PARAM_URL=http://127.0.0.1:8491/#/models 覆盖（脚本见交付台账 §5）。
import os

URL = os.environ.get("MGW_PARAM_URL", "http://127.0.0.1:8300/#/models")
# (模型名, 期望形状) —— empty=档案与已设值都应为空；maxtok=参数卡里有 max_tokens 行
WANT = [{"name": "hy3", "kind": "rows",
         "needles": ["网关不注入这一项（走供应商通道默认）", "厂商明确忽略"], "rows": 8},
        {"name": "gemini-3.6-flash", "kind": "rows",
         "needles": ["厂商明确忽略该参数", "对非默认值直接返回报错", "网关不注入这一项"], "rows": 8},
        {"name": "claude-fable-5-1", "kind": "rows",
         "needles": ["对非默认值直接返回报错", "网关不注入这一项"], "rows": 7},
        {"name": "claude-haiku-4-5", "kind": "rows",
         "needles": ["厂商官方缺省 1 · 网关不注入这一项", "未公布缺省值"], "rows": 7},
        {"name": "sensenova-6.8-flash-lite", "kind": "rows",
         "needles": ["厂商推荐值", "网关按它注入"], "rows": 6},
        {"name": "MiniMax-M2.7", "kind": "rows",
         "needles": ["厂商官方缺省 0.95"], "rows": 3},
        {"name": "gpt-6-astra", "kind": "rows",
         "needles": ["已标注废弃", "厂商未公布缺省值"], "rows": 7},
        {"name": "glm-5.2", "kind": "maxtok", "needles": [], "rows": 5},
        {"name": "sensenova-u1-fast", "kind": "images", "needles": [], "rows": 0}]

JS = r'''
const fs = await import("node:fs");
const PAYLOAD = JSON.parse(fs.readFileSync("__PAYLOAD__", "utf8"));
const task = await taskSpace("MGW 参数配置卡真机取证");
const page = await (async () => {
  try { const p = task.page(PAYLOAD.pageLabel); await p.evaluate(() => 1); return p; }
  catch (e) { return await task.newPage(); }
})();
const results = [];
const push = (ok, id, desc, detail) =>
  results.push(`${ok ? "✓" : "✗"} ${id} ${desc}${detail ? "  ｜ " + detail : ""}`);

await page.goto(PAYLOAD.url);
await page.evaluate(() => { document.documentElement.setAttribute("data-theme", "light");
  try { localStorage.setItem("mgw-theme", "light"); } catch (e) {} });
await page.waitForSelector("#content .panel-split .subnav", { timeout: 20000 });
await page.cdp("Emulation.setDeviceMetricsOverride",
  { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
await page.waitForTimeout(600);

push(await page.evaluate(() => !!window.__MG_BOOTED), "A8",
     "页面启动标记为真（脚本没炸，参数卡才有读数资格）");

for (const w of PAYLOAD.want) {
  const r = await page.evaluate(async (name) => {
    const btn = [...document.querySelectorAll("[data-sel]")]
      .find((b) => b.textContent.trim().startsWith(name));
    if (!btn) return { missing: true };
    btn.click();
    // drawDetail 是同步重绘，但 persist 之后会整页重挂 ⇒ 等一帧再读
    await new Promise((res) => requestAnimationFrame(() => res()));
    const card = [...document.querySelectorAll("#md-detail section.card")]
      .find((c) => /参数配置/.test(c.querySelector("div")?.textContent || ""));
    const injected = card ? card.querySelector("#md-injected") : null;
    const cells = card ? [...card.querySelectorAll("#md-params .list-row")] : [];
    const bases = card ? [...card.querySelectorAll("#md-params .pbasis")] : [];
    const injectedRows = injected ? [...injected.querySelectorAll(".list-row")] : [];
    const emptyHint = card ? (card.querySelector("#md-params .form-hint")?.textContent || "") : "";
    const mtDel = card ? card.querySelector('[data-pdel="max_tokens"]') : null;
    const basisTitleOnly = bases.filter((b) => !b.textContent.trim() && b.getAttribute("title")).length;
    let overflow = [];
    if (card) {
      // 🔴 设计内的省略号截断（名称列 170px + title 给全值）不算溢出：那是本项目定的
      //   "被挤的只能是次要那一半"。判据要区分"文字收进省略号"与"内容顶出卡片"，
      //   否则它会把正确的做法报成缺陷（本轮首跑 4 条红就是这么来的）。
      const ell = (el) => {
        const s = getComputedStyle(el);
        return s.overflowX === "hidden" && s.textOverflow === "ellipsis"
          && s.whiteSpace === "nowrap";
      };
      overflow = [...card.querySelectorAll("*")]
        .filter((el) => el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0 && !ell(el))
        .map((el) => `${el.className || el.tagName}:${el.scrollWidth}>${el.clientWidth}`)
        .slice(0, 3);
      if (card.scrollWidth > card.clientWidth + 1) {
        overflow.push(`card:${card.scrollWidth}>${card.clientWidth}`);
      }
    }
    return {
      found: !!card,
      cells: cells.length, bases: bases.length,
      basisEmptyButTitled: basisTitleOnly,
      firstBasis: (bases[0]?.textContent || "").trim().slice(0, 120),
      allBasis: bases.map((b) => b.textContent).join("\n"),
      injectedRows: injectedRows.length,
      injectedText: injectedRows.map((x) => x.textContent.replace(/\s+/g, " ").trim().slice(0, 160)),
      emptyHint: emptyHint.trim().slice(0, 200),
      delTitle: mtDel ? mtDel.getAttribute("title") : null,
      overflow: Array.isArray(overflow) ? overflow : overflow,
      datalist: (document.querySelector("#md-pkey-list") || {}).length
        || document.querySelectorAll("#md-pkey-list option").length,
    };
  }, w.name);

  if (r.missing) { push(false, `A-${w.name}`, "模型在左栏找不到（读数作废）", "rail 无此行"); continue; }
  if (w.kind === "images") {
    push(!r.found, `A5-${w.name}`, "images 模型按定版不渲染参数卡", `卡在场=${r.found}`);
    continue;
  }
  push(r.found, `A-${w.name}.0`, "参数卡在渲染", "");
  if (r.cells > 0) {
    push(r.cells === r.bases, `A1-${w.name}`, `每行都有依据列（行 ${r.cells} / 依据 ${r.bases}）`,
         `首条依据：${r.firstBasis}`);
    push(r.basisEmptyButTitled === 0, `A7-${w.name}`, "依据是可见文本，不是只挂 title",
         `空文本挂 title 的依据格 ${r.basisEmptyButTitled} 个`);
  }
  if (w.kind === "rows") {
    const shown = r.cells;
    push(shown === w.rows, `B1-${w.name}`, `档案行数照画（期望 ${w.rows}，实画 ${shown}）`,
         `依据首条：${r.firstBasis}`);
    const all = r.allBasis || "";
    for (const nd of w.needles) {
      push(all.includes(nd), `B2-${w.name}`, `依据列写着「${nd}」`, `实画：${(r.allBasis||"").slice(0,150)}`);
    }
    push(!/也未设置网关参数/.test(r.emptyHint), `B3-${w.name}`, "没有那句谎话", "");
  }
  if (w.kind === "empty") {
    push(!/也未设置网关参数/.test(r.emptyHint), `A2-${w.name}`,
         "空态没有那句谎话", r.emptyHint.slice(0, 150));
    push(r.injectedRows === 2, `A3-${w.name}`, "只读段恰两行", `${r.injectedRows} 行`);
    push(r.injectedText.some((t) => /max_tokens/.test(t) && /\d{4,}/.test(t)),
         `A3b-${w.name}`, "max_tokens 那行带实际规格值", (r.injectedText[0] || "").slice(0, 150));
  }
  if (w.kind === "maxtok") {
    push(/131072/.test(r.delTitle || ""), `A4-${w.name}`,
         "清空 max_tokens 的后果按合并规格说（131072）", String(r.delTitle));
    push(r.datalist > 0, `A6b-${w.name}`, "参数名候选 datalist 有内容", `${r.datalist} 项`);
  }
  push((r.overflow || []).length === 0, `A6-${w.name}`, "卡内无顶出（设计内省略号不计）",
       (r.overflow || []).join(" , ") || "无");
}

try {
  const pdf = await page.cdp("Page.printToPDF", { printBackground: true,
    paperWidth: 1440 / 96, paperHeight: 1800 / 96, marginTop: 0, marginBottom: 0,
    marginLeft: 0, marginRight: 0, pageWidth: 1440 / 96, pageHeight: 1800 / 96 });
  fs.writeFileSync(`${PAYLOAD.outDir}/param-card-1440-light.pdf`, Buffer.from(pdf.data, "base64"));
} catch (e) { results.push("✗ PDF 兜底失败：" + String(e).slice(0, 120)); }

fs.writeFileSync(`${PAYLOAD.outDir}/readout.txt`, results.join("\n"), "utf8");
console.log("PROBE_DONE");
'''


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base = OUT_DIR
    pfile, jfile = base / "payload.json", base / "probe.js"
    label = f"paramcard-{base.stat().st_mtime_ns % 1000000}"
    pfile.write_text(json.dumps({"url": URL, "outDir": str(base), "pageLabel": label,
                                 "want": WANT}, ensure_ascii=False), encoding="utf-8")
    jfile.write_text(JS.replace("__PAYLOAD__", str(pfile)), encoding="utf-8")
    with jfile.open("r", encoding="utf-8") as fh:
        proc = subprocess.run(["ego-browser", "nodejs"], stdin=fh, capture_output=True,
                              text=True, timeout=300, cwd=str(base))
    out = base / "readout.txt"
    if not out.exists():
        print(f"✗ 没拿到读数（rc={proc.returncode}）", file=sys.stderr)
        print(proc.stdout[-1000:], proc.stderr[-1000:], file=sys.stderr)
        return 2
    text = out.read_text(encoding="utf-8")
    print(text)
    fails = [ln for ln in text.splitlines() if ln.startswith("✗")]
    for pdf in sorted(base.glob("*.pdf")):
        subprocess.run(["qlmanage", "-t", "-s", "1600", "-o", str(base), str(pdf)],
                       capture_output=True, timeout=120)
        png = pdf.with_suffix(".pdf.png")
        print(("✓ 画面 " if png.exists() else "✗ 转 PNG 失败 ") + str(png if png.exists() else pdf))
    print(f"合计：{len([l for l in text.splitlines() if l.startswith('✓')])} 通过 / {len(fails)} 失败")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
