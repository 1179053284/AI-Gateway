#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读探针（:8300 真实数据）：「模型映射」弹窗删掉「状态」列之后，剩下的格子**各自读得对**。

用户 2026-10-04 原话：「有关联映射配置不就是映射了吗，没关联就是没映射啊。弄个状态这不多次一举么。
给我去掉这列」⇒ 列删了。删列成立的前提 = 那一列原本承载的三件事各自回到了真正的对象上，
本探针按这个前提逐条对账（**全部只读**：不点开关、不下拉、不删映射，零写入）：

  P1 表头逐字四列（「状态」不许回来）+ 每行恰四格（不许留没人住的空列）；
  P2 不撑破：行零横向溢出 + 弹窗零横向滚动（对齐/宽度类判据必须成对，本仓规矩）；
  P3 🔴 下拉 = 「映射了什么」的唯一读数：逐行与后端 `mapped_to` 对账（实盘关键样本
     `hy4-preview-f`：位=False、`mapped_to=['hy4-preview']`、`suggest=None` ⇒ 旧代码下拉显示
     「跳过」，把一条**真实存在的映射**显示成没映射；这一条就是"删列会不会丢信息"的答案）；
  P4 无位而下拉有值（自动建议）⇒ 那一行必须写明「未落库」（此刻它只剩这一个载体，不许只住悬停）；
  P5 🔴 弹窗零删除入口（2026-10-04 第二次裁定：「去掉 删除映射按钮，调整编辑为跳过即解除之前
     关联关系。如果之前没配置 则空着」）+ 只读屏上零「待解除」标注（那是编辑态才有的字）。
     解除这条腿的**行为**判据在真机门 MS8（拨上 → 改回跳过 → 保存只发 remove → 位归 null）。
  P6 开关只认位：后端 null ⇒ 必须为关（2026-10-03 定版那条不变量，载体换了、判据不换）；
  P7 单层弹窗红线未破（遮罩恰 1）+ 关窗归零；
  P8 省下的宽度确实给了模型名（不是留在空列上）。

用法：coding/.venv/bin/python bianyiandhuanjing/scripts/probe_map_status_column.py [--pid workbuddy]
退出码：0 = 全绿；1 = 有失败；2 = 装配级错误（页面/弹窗出不来）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

URL = "http://127.0.0.1:8300/#/accounts"

JS = r'''
const fs = await import("node:fs");
const PAYLOAD = JSON.parse(fs.readFileSync("__PAYLOAD__", "utf8"));
const OUT = "__OUT__";
const checks = [];
const extra = { rows: [] };
function ck(id, desc, ok, measured) { checks.push({ id, desc, ok: !!ok, measured: String(measured) }); }

const task = await taskSpace("MGW 映射弹窗状态列探针");
const page = await (async () => {
  try { const p = task.page(PAYLOAD.pageLabel); await p.evaluate(() => 1); return p; }
  catch (e) { return await task.newPage(); }
})();
/* 🔴 视口必须显式设：本机 Ego Lite 0 个 OS 窗口 ⇒ 不覆盖就是 0×0，`getBoundingClientRect()`
   全为 0 ⇒ 几何类判据（P2 不撑破 / P8 列宽）量出来的是**环境的产物**（首跑就是这两条红）。
   与真机门同一做法（`verify_accounts_ui_live.py::setViewport`），跑完 `clearViewport` 复位——
   这是用户共享的浏览器空间，不许留覆盖。 */
async function setViewport(w, h) {
  await page.cdp("Emulation.setDeviceMetricsOverride",
    { width: w, height: h, deviceScaleFactor: 1, mobile: false });
  await page.waitForTimeout(300);
}
async function clearViewport() {
  await page.cdp("Emulation.clearDeviceMetricsOverride");
  await page.waitForTimeout(200);
}
await setViewport(1440, 900);
await page.goto(PAYLOAD.url);
await page.waitForSelector(".anchor-item[data-pid]", { timeout: 20000 });
await page.waitForTimeout(700);
await page.evaluate((pid) => { const b = document.querySelector(`.anchor-item[data-pid='${pid}']`); if (b) b.click(); });
await page.waitForTimeout(700);
await page.evaluate(() => { const b = document.querySelector("#ac-map"); if (b) b.click(); });
/* 🔴 不用 `page.waitForSelector`：本机 Ego Lite 0 个 OS 窗口 ⇒ 驱动按"可见"筛元素，
   弹窗明明在 DOM 里、`page.evaluate` 读得到全文，`waitForSelector` 却恒超时（首跑实测 45s 两条选择器都红）。
   ⇒ 改**页内轮询**（判据对象是"那一行在不在"，可见性由 P2 的几何读数单独负责）。 */
let opened = false;
for (let i = 0; i < 60; i += 1) {
  opened = await page.evaluate(() => !!document.querySelector(".modal .list-card .list-row"));
  if (opened) break;
  await page.waitForTimeout(500);
}
if (!opened) {
  const seen = await page.evaluate(() => {
    const m = document.querySelector(".modal");
    return { modal: !!m, text: m ? String(m.textContent || "").replace(/\s+/g, " ").trim().slice(0, 220) : "",
             rail: Array.from(document.querySelectorAll(".anchor-item")).length,
             mapBtn: !!document.querySelector("#ac-map") };
  });
  ck("P0", "映射弹窗没出来（装配级，其余判据无从执行）", false,
     "45s 内页内轮询没等到 .modal .list-card .list-row｜" + JSON.stringify(seen));
}
if (opened) {
await page.waitForTimeout(600);

const data = await page.evaluate(async (pid) => {
  const txt = (n) => (n ? String(n.textContent || "").replace(/\s+/g, " ").trim() : "");
  const q = (s, r) => Array.from((r || document).querySelectorAll(s));
  const api = await fetch(`/admin/api/accounts/${pid}/catalog`).then((x) => x.json());
  const card = document.querySelector(".modal .list-card");
  const rowsAll = q(".list-row", card);
  const heads = Array.from(rowsAll[0].children).map((c) => txt(c));
  const rows = rowsAll.slice(1).map((r2) => {
    const sel = r2.querySelector("select[data-idx]");
    const foot = r2.querySelector("[data-mapfoot]");
    const sw = r2.querySelector("[data-mapsw] .switch");
    const nm = r2.querySelector("b");
    return { name: txt(nm),
             selV: sel ? sel.value : null,
             opts: sel ? Array.from(sel.options).map((o) => o.value) : [],
             foot: foot ? txt(foot) : "∅", hasFoot: !!foot,
             delBtn: !!r2.querySelector("[data-mapdel]"),
             swOn: sw ? sw.classList.contains("on") : null,
             swDisabled: sw ? !!sw.disabled : null,
             swTitle: sw ? (sw.title || "") : "",
             cells: r2.children.length,
             nameW: Math.round((nm ? nm.closest("span").getBoundingClientRect().width : 0)),
             rowOverflow: Math.round((r2.scrollWidth - r2.clientWidth) * 10) / 10 };
  });
  const modal = document.querySelector(".modal");
  return { heads, rows,
    masks: document.querySelectorAll(".modal-mask").length,
    modalOverflow: modal ? Math.round((modal.scrollHeight - modal.clientHeight) * 10) / 10 : null,
    modalW: modal ? Math.round(modal.getBoundingClientRect().width) : null,
    docOverflow: Math.round((document.documentElement.scrollWidth
      - document.documentElement.clientWidth) * 10) / 10,
    truth: (api.models || []).map((m) => ({ id: m.id,
      enabled: m.map_enabled === null || m.map_enabled === undefined ? null : m.map_enabled === true,
      mappedTo: (m.mapped_to || []).filter(Boolean),
      suggest: (m.suggest && typeof m.suggest.confidence === "number" && m.suggest.confidence >= 0.7)
        ? String(m.suggest.name || "") : "" })) };
}, PAYLOAD.pid);

extra.rows = data.rows.map((r, i) => ({ ...r, truth: data.truth[i] || null }));
const T = data.truth, R = data.rows;
const paired = R.length > 0 && R.length === T.length;

ck("P0", "样本前提：弹窗行数 == 后端目录条数（读不到同一批对象，后面全是空判据）",
   paired, `UI 行=${R.length} / API=${T.length}（产品 ${PAYLOAD.pid}）`);
ck("P1", "🔴 状态列已删：表头逐字 = 模型/规则/网关模型映射/进池（4 列、零「状态」）且每行恰 4 格",
   data.heads.join("/") === "模型/规则/网关模型映射/进池" && R.every((r) => r.cells === 4),
   "表头=" + JSON.stringify(data.heads) + "；行格数集合=" + JSON.stringify([...new Set(R.map((r) => r.cells))]));
ck("P2", "不撑破：每行零横向溢出 + 页面零横向滚动（宽度类判据必须与 P1 成对）",
   R.every((r) => r.rowOverflow <= 0.5) && data.docOverflow <= 1,
   `行溢出 max=${Math.max(0, ...R.map((r) => r.rowOverflow))}px 文档横向溢出=${data.docOverflow}px 弹窗宽=${data.modalW}px`);
const selBad = [], hintBad = [], noFoot = [];
T.forEach((t, i) => {
  const u = R[i];
  if (!u) return;
  const want = (t.mappedTo || []).find((n) => (u.opts || []).indexOf(n) >= 0);
  if (want && u.selV !== want) selBad.push(`${t.id}:显示「${u.selV}」≠已落库「${want}」`);
  if (!u.hasFoot) noFoot.push(t.id);
  if (t.enabled === null && u.selV && u.foot.indexOf("未落库") < 0) {
    hintBad.push(`${t.id}:有值「${u.selV}」而那一行=「${u.foot.slice(0, 20)}」`);
  }
});
ck("P3", "🔴 下拉就是「映射了什么」：逐行显示**已落库**的那个目标（不是正则建议）",
   selBad.length === 0,
   selBad.length ? selBad.slice(0, 4).join(" ／ ")
     : `对账 ${T.length} 行；其中已落库 ${T.filter((t) => (t.mappedTo || []).length).length} 行逐行相符`);
ck("P4", "未落库而行里有值 ⇒ 那一行写明「未落库」（常驻可见，不是悬停）",
   noFoot.length === 0 && hintBad.length === 0,
   noFoot.length ? "缺那一行的行：" + noFoot.slice(0, 3).join(" ")
     : hintBad.length ? hintBad.slice(0, 4).join(" ／ ")
       : `有值而未落库的行 ${T.filter((t, i) => t.enabled === null && R[i] && R[i].selV).length} 条全部标注`);
/* P5（2026-10-04 第二次裁定后前进）：弹窗里**不许再有删除入口**；而"那一行"只许出现在
   两种待提交态（未落库 / 保存后解除关联），已落库且没被改动的行必须**空着**。
   只读屏上永远不会有"待解除"（那是编辑态才有的字），所以这里的负向腿是：零 `解除` 标注。 */
const delBad = T.map((t, i) => ({ id: t.id, 有位: t.enabled !== null,
  有删除入口: (R[i] || {}).delBtn })).filter((x) => x.有删除入口);
const footBad = T.map((t, i) => ({ id: t.id, 位: t.enabled, 那一行: (R[i] || {}).foot }))
  .filter((x) => /解除/.test(x.那一行 || ""));
ck("P5", "🔴 弹窗零删除入口（用户明令去掉）+ 只读屏上零「待解除」标注（那是编辑态才有的字）",
   delBad.length === 0 && footBad.length === 0,
   `删除入口=${delBad.length ? JSON.stringify(delBad.slice(0, 3)) : "0"}；待解除标注=`
   + `${footBad.length ? JSON.stringify(footBad.slice(0, 3)) : "0"}`);
const lyingOn = T.map((t, i) => ({ id: t.id, e: t.enabled, on: (R[i] || {}).swOn }))
  .filter((x) => x.e === null && x.on !== false);
ck("P6", "开关只认后端那个位：`map_enabled=null` 的行必须为关（2026-10-03 不变量，换了载体不换判据）",
   lyingOn.length === 0,
   lyingOn.length ? "矛盾行：" + JSON.stringify(lyingOn.slice(0, 4))
     : `无位行 ${T.filter((t) => t.enabled === null).length}，全为关；开着的 ${R.filter((r) => r.swOn === true).length} 颗都有位`);
ck("P7", "🔴 单层弹窗红线未破：打开映射弹窗后 .modal-mask 恰 1",
   data.masks === 1, "遮罩数=" + data.masks);
const nameW = R.length ? Math.min(...R.map((r) => r.nameW)) : 0;
ck("P8", "省下的宽度给了模型名（不是留在没人住的空列上）：模型名列实测 ≥ 440px",
   nameW >= 440, `模型名列最小实测=${nameW}px（弹窗 ${data.modalW}px，四列网格）`);

/* 关窗归零（只点「取消」：取消不落库，这条路径零写入） */
await page.evaluate(() => { const b = document.querySelector(".modal-foot .btn"); if (b) b.click(); });
await page.waitForTimeout(400);
const closed = await page.evaluate(() => ({
  masks: document.querySelectorAll(".modal-mask").length,
  root: document.querySelectorAll("#modal-root > *").length }));
ck("P9", "关窗归零（点「取消」= 零写入；全程没有拨过任何开关）",
   closed.masks === 0 && closed.root === 0, JSON.stringify(closed));
}

await clearViewport();
fs.writeFileSync(OUT, JSON.stringify({ checks, extra }, null, 1), "utf8");
console.log("PROBE_DONE");
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", default="workbuddy", help="产品 id（默认 workbuddy = 用户实拍那一屏）")
    args = ap.parse_args()
    base = Path(tempfile.mkdtemp(prefix="mgw-mapcol-"))
    pfile, ofile, jfile = base / "p.json", base / "r.json", base / "probe.js"
    pfile.write_text(json.dumps({"url": URL, "pid": args.pid,
                                 "pageLabel": f"mapcol-{base.name[-6:]}"}, ensure_ascii=False),
                     encoding="utf-8")
    jfile.write_text(JS.replace("__PAYLOAD__", str(pfile)).replace("__OUT__", str(ofile)),
                     encoding="utf-8")
    with jfile.open("r", encoding="utf-8") as fh:
        proc = subprocess.run(["ego-browser", "nodejs"], stdin=fh, capture_output=True,
                              text=True, timeout=300, cwd=str(base))
    if not ofile.exists():
        print(f"✗ 浏览器没交回读数（rc={proc.returncode}）", file=sys.stderr)
        print("  stdout: " + proc.stdout[-700:], file=sys.stderr)
        print("  stderr: " + proc.stderr[-700:], file=sys.stderr)
        return 2
    data = json.loads(ofile.read_text(encoding="utf-8"))
    rows = data.get("checks", [])
    bad = [c["id"] for c in rows if not c["ok"]]
    for c in rows:
        print(f"  {'✓' if c['ok'] else '✗'} {c['id']} {c['desc']}｜{c['measured'][:200]}")
    print("\n逐行读数（界面 ⇄ 后端真相）：")
    for r in data.get("extra", {}).get("rows", []):
        t = r.get("truth") or {}
        print(f"  {r['name']:<18} 下拉=「{r['selV']}」 位={str(t.get('enabled')):<5} "
              f"已落库={t.get('mappedTo')} 建议=「{t.get('suggest')}」")
        print(f"      那一行=「{r['foot'][:46]}」 删除钮={r['delBtn']} 开关on={r['swOn']} "
              f"禁用={r['swDisabled']} 格数={r['cells']} 名列宽={r['nameW']}px")
    print(f"\n合计：{len(rows) - len(bad)} 通过 / {len(bad)} 失败" + (f"  红：{bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
