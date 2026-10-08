#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读探针（:8300 真实页面）：对接说明「当前可服务模型」表的模型 ID 后配复制钮。

用户 2026-10-08 指示：「把对接说明中，模型 ID 后面增加复制 icon，点击复制模型 ID 信息，
icon 要符合整体设计规范。」

判据成对（本仓布局类规矩：只验"钮在"不验"没撑坏行/没指错行"= 给自己发通行证）：
  C0  页面装配成功、无脚本加载失败卡（判 __MG_BOOTED 与错误卡**节点**，不扫 body.textContent）；
  C1  覆盖面：ID 行数 == 钮数，且每一格恰一颗（行数为 0 直接红 = 空判据防线）；
  C2  一行的钮只管自己那一行：data-idcopy === 该行 DOM 里的 ID 文本；
  C3  配对几何：钮住在 ID **文本**右缘之后（Range 量文本，不量盒子）6~14px、纵向居中 ≤1.5px、
      钮 rect 落在格子 rect 内；
  C4  组件规格同源：钮 20×20（与本页地址那两颗同档）、svg 14×14、stroke-width 2、
      class 走 icon-btn sm、计算色 === 本页地址钮计算色（不另立一套色值）；
  C5  不撑坏：逐行格子零横向溢出 + 文档零横向滚动 + 行高不超过 2 档；
  C6  复制腿真跑：点第一行 → 剪贴板写入 === 第一行 ID + toast「模型 ID 已复制」；
      点最后一行 → 写入换成那一行自己的 ID（摘掉 wire 的逐行取值这条就红）；
  C7  窄屏 420px：钮仍与 ID 同一行（矩形纵向重叠）+ 格子不溢出 + 文档不横向滚；
  C8  深色主题下 C1~C4 照常成立。
零写入：只点页面自己的复制钮（写剪贴板，不动配置）；config.yaml 的 md5 由 Python 侧前后对账（C9）。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

URL = "http://127.0.0.1:8300/#/apidocs"
CONFIG = Path("/Users/w/Desktop/Model-Gateway/coding/data/config.yaml")

JS = r'''
const fs = await import("node:fs");
const PAYLOAD = JSON.parse(fs.readFileSync("__PAYLOAD__", "utf8"));
const OUT = "__OUT__";
const checks = [];
const notes = [];
function ck(id, desc, ok, measured) { checks.push({ id, desc, ok: !!ok, measured: String(measured) }); }
function note(s) { notes.push(String(s)); }

const task = await taskSpace("MGW 对接说明模型ID复制钮探针");
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

/* 逐行读数：第一格 = 模型 ID 格（表由 th 文本「模型 ID」定位，不靠列序硬编码） */
const READ = () => {
  const tbl = [...document.querySelectorAll("table.tbl")].find(
    (t) => [...t.querySelectorAll("th")].some((h) => h.textContent.trim() === "模型 ID"));
  if (!tbl) return { missing: "没有「模型 ID」这一列" };
  const rows = [...tbl.querySelectorAll("tbody tr")];
  const pageBtns = document.querySelectorAll("[data-idcopy]").length;
  const addrBtn = document.querySelector(".addr-value .icon-btn");
  const addrCs = addrBtn ? getComputedStyle(addrBtn) : null;
  const r1 = (n) => Math.round(n * 10) / 10;
  const items = rows.map((tr, i) => {
    const td = tr.children[0];
    const btns = td.querySelectorAll("[data-idcopy]");
    const btn = btns[0];
    if (!btn) return { i, missing: true, btnCount: btns.length };
    const text = [...td.childNodes].filter((n) => n.nodeType === 3 || n.tagName === "SPAN")
      .map((n) => (n.textContent || "")).join("").replace(/\s+/g, " ").trim();
    const domId = (btn.closest("span").firstChild && btn.closest("span").textContent || "")
      .replace(btn.textContent || "", "").replace(/\s+/g, " ").trim();
    const b = btn.getBoundingClientRect();
    const k = td.getBoundingClientRect();
    const tr0 = tr.getBoundingClientRect();
    const rg = document.createRange();
    const textNode = [...(btn.parentElement ? btn.parentElement.childNodes : [])]
      .find((n) => n.nodeType === 3 && (n.textContent || "").trim());
    let textRight = b.left, textMidY = (tr0.top + tr0.bottom) / 2;
    if (textNode) {
      rg.selectNode(textNode);
      const r = rg.getBoundingClientRect();
      textRight = r.right;
      textMidY = (r.top + r.bottom) / 2;
    }
    const svg = btn.querySelector("svg");
    const sr = svg ? svg.getBoundingClientRect() : null;
    const cs = getComputedStyle(btn);
    return {
      i,
      btnCount: btns.length,
      domId,
      attrId: btn.dataset.idcopy,
      matches: (btn.dataset.idcopy || "") === domId,
      inCell: b.top >= k.top - 0.5 && b.left >= k.left - 0.5 && b.right <= k.right + 0.5
        && b.bottom <= k.bottom + 0.5,
      afterText: r1(b.left - textRight),
      centerYOff: r1(Math.abs((b.top + b.bottom) / 2 - textMidY)),
      sameLine: b.bottom > tr0.top && b.top < tr0.bottom && r1(b.left - textRight) > -1,
      btnBox: [Math.round(b.width), Math.round(b.height)],
      svgBox: sr ? [Math.round(sr.width), Math.round(sr.height)] : null,
      sw: svg ? svg.getAttribute("stroke-width") : null,
      cls: btn.className,
      color: cs.color,
      sameAsAddr: addrCs ? cs.color === addrCs.color : null,
      tdOverflow: r1(td.scrollWidth - td.clientWidth),
      rowH: Math.round(tr0.height),
    };
  });
  return {
    rowCount: rows.length,
    pageBtns,
    docScroll: r1(document.documentElement.scrollWidth - document.documentElement.clientWidth),
    addrColor: addrCs ? addrCs.color : null,
    items,
  };
};

const STUB = () => {
  window.__copied = "(未写)";
  if (navigator.clipboard) {
    navigator.clipboard.writeText = (t) => { window.__copied = t; return Promise.resolve(); };
    return true;
  }
  return false;
};

const pick = (data) => data.items || [];
const all = (data, pred) => { const l = pick(data); return l.length > 0 && l.every(pred); };

await setViewport(1440, 900);
await page.goto(PAYLOAD.url);
await page.waitForSelector("table.tbl", { timeout: 20000 });
const theme0 = await page.evaluate(() => localStorage.getItem("mg-theme"));
await page.evaluate(() => localStorage.setItem("mg-theme", "light"));
await page.reload();
await page.waitForSelector("table.tbl", { timeout: 20000 });
await page.waitForTimeout(900);

const booted = await page.evaluate(() => ({
  booted: !!window.__MG_BOOTED,
  errCard: [...document.querySelectorAll(".center-card")]
    .some((n) => (n.textContent || "").indexOf("界面脚本未能加载") >= 0),
}));
ck("C0", "页面装配成功、无脚本加载失败卡", booted.booted && !booted.errCard,
   `__MG_BOOTED=${booted.booted} 错误卡=${booted.errCard}`);

let L = await page.evaluate(READ);
if (L.missing) {
  ck("C1", "定位到「当前可服务模型」表", false, L.missing);
  fs.writeFileSync(OUT, JSON.stringify({ checks, notes }, null, 2), "utf8");
}
note(`light@1440 行数=${L.rowCount} 全页钮=${L.pageBtns} 地址钮色=${L.addrColor}`);

ck("C1", "覆盖面：ID 行数 == 钮数 且每一格恰一颗（行数 > 0）",
   L.rowCount > 0 && pick(L).length === L.rowCount && L.pageBtns === L.rowCount
   && all(L, (x) => x.btnCount === 1),
   `行数=${L.rowCount} 格内钮=${pick(L).map((x) => x.btnCount).join(",")} 全页=${L.pageBtns}`);
ck("C2", "一行的钮只管自己那一行：data-idcopy === 该行 DOM 里的 ID 文本",
   all(L, (x) => x.matches),
   pick(L).filter((x) => !x.matches).slice(0, 3).map((x) =>
     `行${x.i} 盘上=「${x.attrId}」DOM=「${x.domId}」`).join(" ")
   || pick(L).slice(0, 2).map((x) => `行${x.i}=「${x.attrId}」✓`).join(" "));
ck("C3", "配对几何：钮在 ID 文本右缘后 6~14px、纵向居中 ≤1.5px、钮 rect 落在格内",
   all(L, (x) => x.afterText >= 6 && x.afterText <= 14 && x.centerYOff <= 1.5 && x.inCell),
   pick(L).slice(0, 4).map((x) => `行${x.i} 间隙${x.afterText}/偏心${x.centerYOff}/落格${x.inCell ? "✓" : "✗"}`).join(" "));
ck("C4", "组件规格同源：钮 20×20 · svg 14×14 · sw2 · class=icon-btn sm · 计算色 === 本页地址钮",
   all(L, (x) => String(x.btnBox) === "20,20" && String(x.svgBox) === "14,14"
     && x.sw === "2" && x.cls === "icon-btn sm" && x.sameAsAddr === true),
   pick(L).slice(0, 3).map((x) => `钮${x.btnBox} svg${x.svgBox} sw${x.sw} class=${x.cls} 色同=${x.sameAsAddr}(${x.color})`).join(" "));
ck("C5", "不撑坏：逐格零横向溢出 + 文档零横向滚动 + 行高 ≤ 2 档",
   all(L, (x) => x.tdOverflow <= 0) && L.docScroll <= 0
   && new Set(pick(L).map((x) => x.rowH)).size <= 2,
   `溢出=${[...new Set(pick(L).map((x) => x.tdOverflow))].join(",")} 文档=${L.docScroll} 行高档位=${[...new Set(pick(L).map((x) => x.rowH))].join(",")}`);

/* C6 复制腿：真点两次（第一行 / 最后一行），验"逐行取值"这条真的跟着行走 */
const clipOk = await page.evaluate(STUB);
if (clipOk && L.rowCount >= 2) {
  const grab = async (idx) => page.evaluate((n) => {
    const btn = document.querySelectorAll("[data-idcopy]")[n];
    if (!btn) return { missing: true, copied: "(无钮)", attr: null, toast: "" };
    window.__copied = null;
    document.querySelectorAll(".toast").forEach((t) => t.remove());
    btn.click();
    return new Promise((res) => setTimeout(() => res({
      copied: window.__copied,
      attr: btn.dataset.idcopy,
      toast: [...document.querySelectorAll(".toast")].map((t) => (t.textContent || "").trim()).join("|"),
    }), 220));
  }, idx);
  const first = await grab(0);
  const last = await grab((await page.evaluate(() => document.querySelectorAll("[data-idcopy]").length)) - 1);
  ck("C6a", "点第一行 → 剪贴板写入 === 该行 ID 且 toast 文案点名「模型 ID 已复制」",
     first.copied === first.attr && first.toast.indexOf("模型 ID 已复制") >= 0,
     `写入=「${first.copied}」toast=「${first.toast}」`);
  ck("C6b", "点最后一行 → 写入换成那一行自己的 ID（不是第一行那个）",
     last.copied === last.attr && last.attr !== first.attr,
     `末行 ID=「${last.attr}」写入=「${last.copied}」首行=「${first.attr}」`);
} else {
  ck("C6a", "复制腿不可判（clipboard 不可用或行数 < 2）", false,
     `clipboard=${clipOk} 行数=${L.rowCount}`);
  ck("C6b", "复制腿不可判", false, `clipboard=${clipOk} 行数=${L.rowCount}`);
}

/* C7 窄屏：钮不许掉到 ID 下面一行 */
await setViewport(420, 900);
await page.waitForTimeout(300);
const N = await page.evaluate(READ);
ck("C7", "窄屏 420px：钮仍与 ID 同一行 + 格子不溢出 + 文档不横向滚",
   all(N, (x) => x.sameLine) && all(N, (x) => x.tdOverflow <= 0) && N.docScroll <= 0,
   `同行=${pick(N).filter((x) => x.sameLine).length}/${pick(N).length} 格溢出=${[...new Set(pick(N).map((x) => x.tdOverflow))].join(",")} 文档=${N.docScroll}`);
await setViewport(1440, 900);
await page.waitForTimeout(300);

/* C8 深色主题 */
await page.evaluate(() => localStorage.setItem("mg-theme", "dark"));
await page.reload();
await page.waitForSelector("table.tbl", { timeout: 20000 });
await page.waitForTimeout(900);
const D = await page.evaluate(READ);
ck("C8", "深色主题下覆盖面/配对几何/组件规格照常成立",
   D.rowCount === L.rowCount && all(D, (x) => x.btnCount === 1 && x.matches)
   && all(D, (x) => x.afterText >= 6 && x.afterText <= 14 && x.centerYOff <= 1.5 && x.inCell)
   && all(D, (x) => String(x.btnBox) === "20,20" && x.sameAsAddr === true),
   `行数=${D.rowCount} 色同=${[...new Set(pick(D).map((x) => x.sameAsAddr))].join(",")} 色=${D.addrColor} 间隙=${[...new Set(pick(D).map((x) => x.afterText))].join(",")}`);

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
    cfg0 = hashlib.md5(CONFIG.read_bytes()).hexdigest()
    base = Path(tempfile.mkdtemp(prefix="mgw-idcopy-"))
    pfile = base / "payload.json"
    ofile = base / "results.json"
    jfile = base / "probe.js"
    pfile.write_text(json.dumps({"url": URL, "pageLabel": f"idc-{base.name[-7:]}"},
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
    cfg1 = hashlib.md5(CONFIG.read_bytes()).hexdigest()
    rows.append({
        "id": "C9", "desc": "零写入：coding/data/config.yaml 跑前 = 跑后逐字节一致",
        "ok": cfg0 == cfg1, "measured": f"{cfg0[:12]}… → {cfg1[:12]}…",
    })
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
