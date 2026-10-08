#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真机只读探针：两处「纯 CSS 柱状趋势图」**画出来的几何**。

对应 2026-10-08 用户实拍「总览今日调用趋势没有数据」：后端 `/admin/api/overview` 的
`today_by_hour` 一直有数（实盘 0 点 20 次 / 10 点 4 次），塌的是前端——柱体自 v0.1.0 起
恒为 0px：行容器 `align-items:flex-end` ⇒ 每根柱子的包裹层高度=内容高（只剩下面那行标签）
⇒ 轨道 `flex:1` 没有剩余空间可长 ⇒ 里面的 `height:PCT%` 没有确定父高可算 ⇒ 全塌成 0。
v2 门的 K8 判的是「容器可见 + `<div>` 数 > 10」（假 DOM，没有布局引擎），**DOM 在场不等于
画得出来**，所以这条缺陷在 20 多轮门全绿里活了下来。

同族第二处 = 数据看板 Chart.js 缺席时的降级柱状（`stats.js::cssBars`），同一套坏语法；
本探针把 `window.Chart` 置空后重进该页，让降级腿真的有对象可量（不测 = 不知道它也是 0px）。

判据成对（本仓布局类规矩：只验"长了"不验"长对/没撑破"= 给自己发通行证）：
  C1 容器 160px 且 24 根柱子都在场
  C2 有请求的那几根：轨道真有高度（> 100px，不是 0px）
  C3 有请求⇒填充段可见；零请求⇒不画填充段（只有轨道底色）
  C4 逐根柱高 = 轨道高 × max(2%, 次数/最大次数)（容差 0.6px；2% 是"单请求小时必须看得见"的兜底档）
  C5 分段着色与计数自洽（成功:失败 高度比 ≈ 次数比、两色不同）
  C6 24 列等宽 · 文档零横向溢出 · 标签在轨道之下不重叠
  C7 页面本体渲染成功（启动标记为真、无兜底错误卡）
  S1 屏蔽 Chart.js 前看板确实在画 canvas（证明降级腿不是唯一路径）；屏蔽后画的是 CSS 柱
  S2 降级柱逐根有高度（> 2px）且 = 轨道高 × max(2%, 次数/最大次数)
  S3 零请求日不画柱
  S4 降级柱状列等宽、零横向溢出、标签不重叠
全程只读：不改配置、不点任何写入钮、不拨任何开关。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = "http://127.0.0.1:8300"

JS = r'''
const fs = await import("node:fs");
const PAYLOAD = JSON.parse(fs.readFileSync("__PAYLOAD__", "utf8"));
const OUT = "__OUT__";
const checks = [];
const extra = {};
function ck(id, desc, ok, measured) { checks.push({ id, desc, ok: !!ok, measured: String(measured) }); }
const RR = (n) => Math.round(n * 100) / 100;

const task = await taskSpace("MGW 趋势柱体几何真机判据");
const page = await (async () => {
  try { const p = task.page(PAYLOAD.pageLabel); await p.evaluate(() => 1); return p; }
  catch (e) { return await task.newPage(); }
})();
await page.cdp("Emulation.setDeviceMetricsOverride",
  { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

/* 通用量测：把 #hour-chart / #s-chart 那一排柱子读成结构化数 */
const MEASURE = (sel) => {
  const box = document.querySelector(sel);
  if (!box) return { missing: true };
  const row = box.children[0];
  if (!row) return { missing: true };
  const bars = Array.from(row.children);
  const R = (n) => Math.round(n * 100) / 100;
  const H = (n) => (n ? R(n.getBoundingClientRect().height) : 0);
  const rows = bars.map((b, i) => {
    const track = b.children[0];
    const label = b.children[b.children.length - 1];
    const kids = Array.from(track.children);
    const fill = kids.length ? kids[0] : null;
    const t = track.getAttribute("title") || "";
    const num = (re) => Number((t.match(re) || [0, 0])[1]);
    return {
      i: i,
      requests: num(/· (\d+) 次/), success: num(/成功(\d+)/),
      failed: num(/失败(\d+)/), aborted: num(/中断(\d+)/),
      barH: H(b), trackH: H(track), fillH: H(fill),
      segs: fill ? Array.from(fill.children).map((s) =>
        ({ h: H(s), color: getComputedStyle(s).backgroundColor,
           bottom: R(s.getBoundingClientRect().bottom) })) : [],
      trackBottom: R(track.getBoundingClientRect().bottom),
      labelTop: R(label.getBoundingClientRect().top),
      w: R(b.getBoundingClientRect().width),
    };
  });
  return {
    boxH: H(box), rowH: H(row), align: getComputedStyle(row).alignItems,
    barCount: bars.length, canvas: box.querySelectorAll("canvas").length,
    scrollX: Math.round(document.documentElement.scrollWidth
      - document.documentElement.clientWidth),
    widths: rows.map((r) => r.w), rows: rows,
    okColor: (function () {
      const d = document.createElement('div');
      d.style.color = 'var(--ok)';
      document.body.appendChild(d);
      const c = getComputedStyle(d).color;
      d.remove();
      return c;
    })(),
    boot: !!window.__MG_BOOTED,
    loadFail: (function () {
      const c = document.querySelector(".center-card");
      return !!c && String(c.textContent || "").indexOf("界面脚本未能加载") >= 0;
    })(),
  };
};

/* ---------- ① 总览「今日调用趋势（24h）」（主题显式设定，不跟着用户当前偏好漂移）---------- */
const gotoDash = async (theme) => {
  await page.goto(PAYLOAD.base + "/#/dashboard");
  await page.waitForSelector("#hour-chart > div > div", { timeout: 20000 });
  await page.evaluate((t) => { localStorage.setItem("mg-theme", t); }, theme);
  await page.reload();
  await page.waitForSelector("#hour-chart > div > div", { timeout: 20000 });
  await page.waitForTimeout(1100);
  return page.evaluate(MEASURE, "#hour-chart");
};
const g = await gotoDash("light");
const nz = g.rows.filter((r) => r.requests > 0);
const z = g.rows.filter((r) => r.requests === 0);
const spread = RR(Math.max(...g.widths) - Math.min(...g.widths));
extra.nonzeros = nz.map((r) => ({ hour: r.i, requests: r.requests, trackH: r.trackH, fillH: r.fillH }));

ck("C1", "总览：容器 160px 且 24 根柱子都在场", g.boxH >= 150 && g.barCount === 24,
   `boxH=${g.boxH} rowH=${g.rowH} bars=${g.barCount}`);
ck("C2", "总览：有请求的那几根轨道真有高度（不是 0px）",
   nz.length > 0 && nz.every((r) => r.trackH > 100),
   `align-items=${g.align} 轨道高=${nz.map((r) => r.trackH).join("/")}`);
ck("C3", "总览：有请求⇒填充段可见；零请求⇒不画填充段",
   nz.length > 0 && nz.every((r) => r.fillH > 2) && z.length > 0 && z.every((r) => r.fillH === 0),
   `非零填充高=${nz.map((r) => r.fillH).join("/")}｜零小时 ${z.length} 根填充=${z.slice(0, 2).map((r) => r.fillH).join("/")}`);
ck("C4", "总览：逐根柱高 = 轨道高 × max(2%, 次数/最大次数)（容差 0.6px）", (() => {
   const mx = Math.max(...g.rows.map((r) => r.requests));
   const above = nz.filter((r) => (r.requests / mx) * 100 > 2);
   if (!above.length) { extra.ratio = "全部非零小时都落在 2% 兜底档，比例腿无对象"; return false; }
   const bad = nz.map((r) => ({ i: r.i, want: RR(r.trackH * Math.max(2, r.requests / mx * 100) / 100),
                                got: r.fillH }))
                 .filter((x) => Math.abs(x.want - x.got) > 0.6);
   extra.ratio = { maxRequests: mx, 超兜底档: above.length, 偏差柱: bad.slice(0, 3) };
   return bad.length === 0;
 })(), `max=${JSON.stringify((extra.ratio || {}).maxRequests)} 超兜底档=${JSON.stringify((extra.ratio || {})["超兜底档"])} 偏差柱=${JSON.stringify((extra.ratio || {})["偏差柱"])}`);
ck("C5", "总览：分段着色与计数自洽（成功:失败 高度比 ≈ 次数比、两色不同）", (() => {
   const a = nz.filter((r) => r.segs.length >= 2 && r.failed > 0)[0];
   if (!a) { extra.segRatio = "载荷里没有同时含成功与失败的小时"; return false; }
   const ok = a.segs[0], err = a.segs[1];
   const base = a.segs.filter((x) => Math.abs(x.bottom - a.trackBottom) <= 1)[0];
   extra.segRatio = { want: RR(a.success / a.failed), got: RR(ok.h / err.h), hour: a.i,
                      colors: [ok.color, err.color], 柱底段: base ? base.color : "无",
                      okColor: g.okColor };
   return Math.abs(ok.h / err.h - a.success / a.failed) < 0.5 && ok.color !== err.color
     && !!base && base.color === g.okColor;
 })(), `期望=${JSON.stringify((extra.segRatio || {}).want)} 实测=${JSON.stringify((extra.segRatio || {}).got)} 色=${JSON.stringify((extra.segRatio || {}).colors)}`);
ck("C6", "总览：24 列等宽（≤0.5px 抖动）· 零横向溢出 · 标签不与轨道重叠", (() => {
   const bad = g.rows.filter((r) => r.labelTop - r.trackBottom < 3);
   return spread <= 0.5 && g.scrollX === 0 && bad.length === 0;
 })(), `列宽抖动=${spread}px 溢出=${g.scrollX}px 重叠=${g.rows.filter(r => r.labelTop - r.trackBottom < 3).length} 根`);
ck("C7", "总览：页面本体渲染成功（启动标记为真、无兜底错误卡）",
   g.boot === true && g.loadFail === false, `boot=${g.boot} loadFail=${g.loadFail}`);

/* ---------- ② 数据看板：屏蔽 Chart.js ⇒ 走降级柱状 ---------- */
await page.goto(PAYLOAD.base + "/#/stats");
await page.waitForSelector("#s-chart > *, " + "#s-chart canvas", { timeout: 20000 });
await page.waitForTimeout(1000);
const withChart = await page.evaluate(MEASURE, "#s-chart");
await page.evaluate(() => { window.Chart = undefined; location.hash = "#/dashboard"; });
await page.waitForTimeout(400);
await page.evaluate(() => { location.hash = "#/stats"; });
await page.waitForSelector("#s-chart > div > div", { timeout: 20000 });
await page.waitForTimeout(1000);
const s = await page.evaluate(MEASURE, "#s-chart");
const snz = s.rows.filter((r) => r.requests > 0);
const sz = s.rows.filter((r) => r.requests === 0);
const sspread = RR(Math.max(...s.widths) - Math.min(...s.widths));
extra.stats = { canvasBefore: withChart.canvas, canvasAfter: s.canvas,
                days: s.barCount, nonzeros: snz.map((r) => ({ d: r.i, n: r.requests, h: r.fillH })) };

ck("S1", "看板：屏蔽 Chart.js 后画的是 CSS 柱（零 canvas、柱数 = 天数）",
   withChart.canvas >= 1 && s.canvas === 0 && s.barCount >= 2,
   `屏蔽前 canvas=${withChart.canvas}（证明默认腿真在画）→ 屏蔽后 canvas=${s.canvas} 柱数=${s.barCount}`);
ck("S2", "看板：降级柱体逐根有高度且 = 轨道高 × max(2%, 次数/最大次数)", (() => {
   if (!snz.length) { extra.sratio = "近 N 天零请求，无对象可判"; return false; }
   const mx = Math.max(...s.rows.map((r) => r.requests));
   const above = snz.filter((r) => (r.requests / mx) * 100 > 2);
   const bad = snz.map((r) => ({ i: r.i, want: RR(r.trackH * Math.max(2, r.requests / mx * 100) / 100),
                                 got: r.fillH }))
                  .filter((x) => Math.abs(x.want - x.got) > 0.6);
   extra.sratio = { maxRequests: mx, 超兜底档: above.length, 偏差柱: bad.slice(0, 3),
                    全部柱高: snz.map(r => r.fillH) };
   return above.length >= 1 && bad.length === 0 && snz.every((r) => r.fillH > 2);
 })(), `读数=${JSON.stringify(extra.sratio)}`);
ck("S3", "看板：零请求日不画柱（有零请求日才判，全有请求则如实说明）",
   sz.length > 0 ? sz.every((r) => r.fillH === 0) : true,
   `零请求日 ${sz.length} 根，填充高=${sz.slice(0, 3).map((r) => r.fillH).join("/") || "（无零请求日）"}`);
ck("S4", "看板：降级柱状列等宽 · 零横向溢出 · 标签不重叠", (() => {
   const bad = s.rows.filter((r) => r.labelTop - r.trackBottom < 3);
   return sspread <= 0.5 && s.scrollX === 0 && bad.length === 0;
 })(), `列宽抖动=${sspread}px 溢出=${s.scrollX}px 重叠=${s.rows.filter(r => r.labelTop - r.trackBottom < 3).length} 根`);

fs.writeFileSync(OUT, JSON.stringify({ checks, extra }, null, 1), "utf8");
console.log("PROBE_DONE");
'''


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="mgw-trend-"))
    pfile = base / "payload.json"
    ofile = base / "results.json"
    jfile = base / "probe.js"
    pfile.write_text(json.dumps({"base": BASE, "pageLabel": f"trend-{base.name[-6:]}"},
                                ensure_ascii=False), encoding="utf-8")
    jfile.write_text(JS.replace("__PAYLOAD__", str(pfile)).replace("__OUT__", str(ofile)),
                     encoding="utf-8")
    with jfile.open("r", encoding="utf-8") as fh:
        proc = subprocess.run(["ego-browser", "nodejs"], stdin=fh, capture_output=True,
                              text=True, timeout=420, cwd=str(base))
    if not ofile.exists():
        print(f"✗ 浏览器没交回读数（rc={proc.returncode}）", file=sys.stderr)
        print("  stdout: " + proc.stdout[-900:], file=sys.stderr)
        print("  stderr: " + proc.stderr[-900:], file=sys.stderr)
        return 2
    data = json.loads(ofile.read_text(encoding="utf-8"))
    rows = data.get("checks", [])
    bad = [c["id"] for c in rows if not c["ok"]]
    for c in rows:
        print(f"  {'✓' if c['ok'] else '✗'} {c['id']} {c['desc']}｜{c['measured'][:230]}")
    ex = data.get("extra", {})
    print("\n总览非零小时：", ex.get("nonzeros"))
    print("看板降级读数：", json.dumps(ex.get("stats"), ensure_ascii=False)[:400])
    print(f"\n合计：{len(rows) - len(bad)} 通过 / {len(bad)} 失败" + (f"  红：{bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
