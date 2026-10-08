#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读探针（:8300 真实页面）：对接说明的复制钮搬进代码框内右上角后的几何与行为。

用户 2026-10-08 指示：「把对接说明中复制当前示例、复制命令 按钮放到代码片段框内右上角位置，
注意距离上面和右边保留一点间距」。同屏第四颗「复制示例」同一形状，一起搬（否则会被读成坏了）。

判据成对（本仓布局类规矩：只验"搬进去了"不验"没压住代码"= 给自己发通行证）：
  A1 每块恰一颗钮，且钮 rect 全落在**可见**代码块 rect 之内；
  A2 上间距 = 8px、右间距 = 8px（逐块读数，"保留一点间距"要有具体值）；
  A3 钮与代码**文本行矩形**零相交（Range 量文本，不量 pre 盒子）；
  A4 钮底色 ≠ 块底色（深色主题下不许"看不见这里有个钮"）；
  A5 零溢出：文档横向不滚 + pre 自身不滚；
  A6 切语言不跳版（三个 pre 同 padding ⇒ 壳高不变）且钮仍在框内、tab 高亮跟着走；
  A7 复制腿复制的是**当前可见**那一段（打桩收 clipboard 写入，切 Node 后换内容）；
     A7b/A7c 两块单 pre（list / maxtok）的复制腿逐字等于该 pre 的 textContent，
        占位符仍是尖括号原文、第二行缩进没被模板缩进污染（DOM 被我重排过 ⇒ 必须真点一次）；
  A8 窄屏 420px 仍零重叠（预留块顶内边距这条设计的全部理由，实测不推理）；
  A9 深色主题下 A1~A4 照常成立；
  A10 页面装配成功、零 JS 异常（判 __MG_BOOTED 与错误卡节点，不判 body.textContent）。
零写入：只点页面自己的 tab 与复制钮（复制钮只写剪贴板，不动配置）。
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
const notes = [];
function ck(id, desc, ok, measured) { checks.push({ id, desc, ok: !!ok, measured: String(measured) }); }
function note(s) { notes.push(String(s)); }

const task = await taskSpace("MGW 对接说明复制钮位置探针");
let mine = false;
let page;
try { page = await task.page(PAYLOAD.pageLabel); await page.evaluate(() => 1); }
catch (e) { page = await task.newPage(); mine = true; }

const setViewport = async (w, h) => {
  await page.cdp("Emulation.setDeviceMetricsOverride",
    { width: w, height: h, deviceScaleFactor: 1, mobile: false });
  await page.waitForTimeout(300);
};
const clearViewport = async () => {
  try { await page.cdp("Emulation.clearDeviceMetricsOverride", {}); } catch (e) {}
};

const READ = () => {
  const shells = [...document.querySelectorAll(".code-shell")];
  return shells.map((sh) => {
    const btn = sh.querySelector(".code-copy");
    const vis = [...sh.querySelectorAll("pre.code-block")].find((p) => !p.classList.contains("hidden"));
    if (!btn || !vis) return { key: sh.dataset.codeset || "(单块)", missing: true };
    const b = btn.getBoundingClientRect();
    const k = vis.getBoundingClientRect();
    const rg = document.createRange();
    rg.selectNodeContents(vis);
    const lines = [...rg.getClientRects()].filter((r) => r.width > 0 && r.height > 0);
    const hit = lines.filter((r) => r.bottom > b.top && r.top < b.bottom && r.right > b.left && r.left < b.right);
    const bs = getComputedStyle(btn);
    const ks = getComputedStyle(vis);
    const r1 = (n) => Math.round(n * 10) / 10;
    return {
      key: btn.dataset.copygroup,
      label: btn.textContent.trim(),
      lang: vis.dataset.lang,
      inBox: b.top >= k.top - 0.5 && b.left >= k.left - 0.5
        && b.right <= k.right + 0.5 && b.bottom <= k.bottom + 0.5,
      topGap: r1(b.top - k.top),
      rightGap: r1(k.right - b.right),
      btnBox: [Math.round(b.width), Math.round(b.height)],
      overlap: hit.length,
      overlapInto: hit.length ? r1(hit[0].right - b.left) : 0,
      btnBg: bs.backgroundColor,
      blkBg: ks.backgroundColor,
      distinct: bs.backgroundColor !== ks.backgroundColor,
      preScroll: r1(vis.scrollWidth - vis.clientWidth),
      docScroll: r1(document.documentElement.scrollWidth - document.documentElement.clientWidth),
      shellH: Math.round(sh.getBoundingClientRect().height),
      textHead: (vis.textContent || "").replace(/\s+/g, " ").trim().slice(0, 30),
    };
  });
};

const STUB = () => {
  window.__copied = "(\u672a\u5199)";
  if (navigator.clipboard) {
    navigator.clipboard.writeText = (t) => { window.__copied = t; return Promise.resolve(); };
    return true;
  }
  return false;
};

await setViewport(1440, 900);
await page.goto(PAYLOAD.url);
await page.waitForSelector(".code-shell", { timeout: 20000 });
const theme0 = await page.evaluate(() => localStorage.getItem("mg-theme"));
await page.evaluate(() => localStorage.setItem("mg-theme", "light"));
await page.reload();
await page.waitForSelector(".code-shell", { timeout: 20000 });
await page.waitForTimeout(900);

const booted = await page.evaluate(() => ({
  booted: !!window.__MG_BOOTED,
  // 兜底卡是 .center-card 那个**节点**（那句文案本来就在 index.html 的内联 script 里，
  // 扫 body.textContent 会永远为真 = 假判据）
  errCard: [...document.querySelectorAll(".center-card")]
    .some((n) => (n.textContent || "").indexOf("界面脚本未能加载") >= 0),
}));
const L = await page.evaluate(READ);
const sig = (arr) => arr.map((x) => `${x.key}:${x.label}`).join(" ");
note(`light@1440 ${sig(L)}`);

ck("A0", "页面装配成功、无脚本加载失败卡", booted.booted && !booted.errCard,
   `__MG_BOOTED=${booted.booted} 错误卡=${booted.errCard}`);
ck("A1", "四块各一颗钮，钮 rect 全落在可见代码块 rect 内",
   L.length === 4 && L.every((x) => !x.missing && x.inBox),
   L.map((x) => `${x.key}${x.inBox ? "✓" : "✗"}`).join(" "));
ck("A1b", "块外不留第二颗复制钮（data-copygroup 全部住在 .code-shell 里）",
   await page.evaluate(() => document.querySelectorAll("[data-copygroup]").length
     === document.querySelectorAll(".code-shell .code-copy").length),
   await page.evaluate(() => `[data-copygroup]=${document.querySelectorAll("[data-copygroup]").length}`
     + ` .code-shell .code-copy=${document.querySelectorAll(".code-shell .code-copy").length}`));
ck("A2", "上间距 8px 且右间距 8px（逐块）",
   L.every((x) => x.topGap === 8 && x.rightGap === 8),
   L.map((x) => `${x.key} 上${x.topGap}/右${x.rightGap}`).join(" "));
ck("A3", "钮与代码文本行零相交（量 Range 文本边缘）",
   L.every((x) => x.overlap === 0),
   L.map((x) => `${x.key} 重叠${x.overlap}${x.overlap ? "(压入" + x.overlapInto + "px)" : ""}`).join(" "));
ck("A4", "钮底色 ≠ 代码块底色（浅色下是白片）",
   L.every((x) => x.distinct),
   L.map((x) => `${x.key} ${x.btnBg} vs ${x.blkBg}`).join(" "));
ck("A5", "零溢出：文档横向不滚 + pre 自身不滚",
   L.every((x) => x.docScroll <= 0 && x.preScroll <= 0),
   L.map((x) => `${x.key} 文档${x.docScroll}/块${x.preScroll}`).join(" "));

/* A6 切语言：钮跟着当前块走（三个 pre 同块顶预留 ⇒ 预留带恒定，总高随内容本来就该变） */
await page.evaluate(() => {
  const t = document.querySelector('[data-codetabs="quick"] [data-codelang="python"]');
  t.click();
});
await page.waitForTimeout(200);
const tabRead = () => page.evaluate(() => {
  const sh = document.querySelector('[data-codeset="quick"]');
  const btn = sh.querySelector(".code-copy");
  const vis = [...sh.querySelectorAll("pre.code-block")].find((p) => !p.classList.contains("hidden"));
  const b = btn.getBoundingClientRect();
  const k = vis.getBoundingClientRect();
  const rg = document.createRange(); rg.selectNodeContents(vis);
  const lines = [...rg.getClientRects()].filter((r) => r.width > 0 && r.height > 0);
  const hit = lines.filter((r) => r.bottom > b.top && r.top < b.bottom && r.right > b.left && r.left < b.right);
  return {
    lang: vis.dataset.lang,
    active: document.querySelector('[data-codetabs="quick"] .code-tab.active').dataset.codelang,
    shown: sh.querySelectorAll("pre.code-block:not(.hidden)").length,
    inBox: b.top >= k.top - 0.5 && b.right <= k.right + 0.5,
    topGap: Math.round((b.top - k.top) * 10) / 10,
    rightGap: Math.round((k.right - b.right) * 10) / 10,
    overlap: hit.length,
    padTop: Math.round(parseFloat(getComputedStyle(vis).paddingTop)),
  };
});
const tPy = await tabRead();
await page.evaluate(() => document.querySelector('[data-codetabs="quick"] [data-codelang="node"]').click());
await page.waitForTimeout(200);
const tNd = await tabRead();
ck("A6", "切语言：可见块跟着换·只一块可见·钮仍框内 8px·零重叠·块顶预留带恒 42px",
   tPy.lang === "python" && tPy.active === "python" && tPy.shown === 1
   && tPy.inBox && tPy.topGap === 8 && tPy.rightGap === 8 && tPy.overlap === 0 && tPy.padTop === 42
   && tNd.lang === "node" && tNd.inBox && tNd.topGap === 8 && tNd.overlap === 0 && tNd.padTop === 42,
   `python: 可见=${tPy.lang} 高亮=${tPy.active} 块数=${tPy.shown} 上${tPy.topGap}/右${tPy.rightGap}/重叠${tPy.overlap}/预留${tPy.padTop} → node: 上${tNd.topGap}/重叠${tNd.overlap}/预留${tNd.padTop}`);

/* A7 复制腿 = 当前可见那一段 */
const clipOk = await page.evaluate(STUB);
let a7 = { ok: false, why: "clipboard 不可用" };
if (clipOk) {
  const grab = async (lang) => {
    await page.evaluate((l) => document.querySelector(`[data-codetabs="quick"] [data-codelang="${l}"]`).click(), lang);
    await page.waitForTimeout(160);
    await page.evaluate(() => document.querySelector('[data-copygroup="quick"]').click());
    await page.waitForTimeout(120);
    return page.evaluate(() => ({
      copied: (window.__copied || "").replace(/\s+/g, " ").trim().slice(0, 30),
      shown: [...document.querySelectorAll('[data-codeset="quick"] pre.code-block')]
        .find((p) => !p.classList.contains("hidden")).dataset.lang,
    }));
  };
  const cu = await grab("curl");
  const nd = await grab("node");
  a7 = {
    ok: cu.copied.startsWith("curl http") && cu.shown === "curl"
      && nd.copied.startsWith("const BASE") && nd.shown === "node",
    why: `curl 可见→「${cu.copied}」 / node 可见→「${nd.copied}」`,
  };
}
ck("A7", "复制钮写进剪贴板的就是当前可见那段（切 Node 后换内容）", a7.ok, a7.why);

/* A7b/A7c 两块**单 pre** 的复制腿（DOM 被我重排过 ⇒ "代码没改这条腿"不是证据）：
   逐字等于该 pre 的 textContent，且占位符仍是尖括号原文、第二行缩进没被模板缩进污染 */
for (const key of ["list", "maxtok"]) {
  const r = await page.evaluate(async (k) => {
    const btn = document.querySelector(`[data-copygroup="${k}"]`);
    const pre = document.querySelector(`pre[data-copyset="${k}"]`);
    window.__copied = null;
    btn.click();
    await new Promise((res) => setTimeout(res, 150));
    const src = pre.textContent;
    return {
      inShell: !!btn.closest(".code-shell"),
      same: window.__copied === src,
      placeholder: (window.__copied || "").indexOf("<接入密钥>") >= 0,
      secondLine: (src || "").split("\n")[1] || "",
      lines: (src || "").split("\n").length,
    };
  }, key);
  ck(`A7b-${key}`, `${key}：钮住壳内 且 剪贴板写入 === 该 pre 逐字相等`,
     r.inShell && r.same, `壳内=${r.inShell} 逐字相等=${r.same} 行数=${r.lines}`);
  ck(`A7c-${key}`, `${key}：占位符仍是尖括号原文 + 第二行缩进 2 空格未被模板缩进污染`,
     r.placeholder && /^ {2}-H /.test(r.secondLine), `第二行=「${r.secondLine}」`);
}

/* A8 窄屏：预留块顶内边距这条设计的理由 */
await setViewport(420, 900);
await page.waitForTimeout(300);
const N = await page.evaluate(READ);
ck("A8", "窄屏 420px：钮仍在框内、8px 间距、与折行代码零重叠、文档不横向滚",
   N.length === 4 && N.every((x) => x.inBox && x.topGap === 8 && x.rightGap === 8
     && x.overlap === 0 && x.docScroll <= 0),
   N.map((x) => `${x.key} 上${x.topGap}/右${x.rightGap}/重叠${x.overlap}/文档${x.docScroll}px/壳${x.shellH}px`).join(" "));
await setViewport(1440, 900);
await page.waitForTimeout(300);

/* A9 深色主题 */
await page.evaluate(() => localStorage.setItem("mg-theme", "dark"));
await page.reload();
await page.waitForSelector(".code-shell", { timeout: 20000 });
await page.waitForTimeout(900);
const D = await page.evaluate(READ);
ck("A9", "深色主题下 A1~A4 照常成立（框内 / 8px / 零重叠 / 底色分得开）",
   D.length === 4 && D.every((x) => x.inBox && x.topGap === 8 && x.rightGap === 8
     && x.overlap === 0 && x.distinct),
   D.map((x) => `${x.key} ${x.btnBg} vs ${x.blkBg} 上${x.topGap}/右${x.rightGap}/重叠${x.overlap}`).join(" "));

/* 复位：主题回原值 + 视口回原生 + 关掉我自己开的标签页 */
await page.evaluate((t) => { if (t === null) localStorage.removeItem("mg-theme");
  else localStorage.setItem("mg-theme", t); }, theme0);
await page.reload();
await page.waitForTimeout(400);
await clearViewport();
if (mine) { try { await page.close(); } catch (e) {} }

fs.writeFileSync(OUT, JSON.stringify({ checks, notes }, null, 2), "utf8");
'''


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="mgw-codecopy-"))
    pfile = base / "payload.json"
    ofile = base / "results.json"
    jfile = base / "probe.js"
    pfile.write_text(json.dumps({"url": URL, "pageLabel": f"cc-{base.name[-7:]}"},
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
    for n in data.get("notes", []):
        print(f"  note: {n}")
    print(f"\n合计：{len(rows) - len(bad)} 通过 / {len(bad)} 失败"
          + (f"  红：{bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
