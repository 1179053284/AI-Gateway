#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真机判据（:8300 真实点击路径 · 1440×900 视口）：批量处理结果 = 结果浮层，不固化显示。

用户裁定（2026-10-03，实拍 Raccoon 面板上那块常驻回执）：
  「各类处理结果，不允许用这种形式固化显示。执行完毕，弹窗提示具体执行结果，
   3s 后自动消失，也可以手动关闭。参考设计规范进行设计」

七条判据（R5/R6 两条时间腿成对：手动关闭要立刻没、不点要在 3s 附近没）：
  R1 真点击卡头「刷新额度」后结果浮层出现（不是合成调用）
  R2 计数行原文 + 逐号行，且**逐号词与计数自洽**（「未发起 2 个」⇒ 两行都写「未发起」）
  R3 几何：宽 380px、内容不溢出自身、计数行不被折碎
  R4 不开弹窗（遮罩 0、modal-root 空、卡不在 .modal 内）
  R5 × 手动关闭立即消失
  R6 不点关闭 ⇒ 3s 附近自动消失（实测落点记下来）
  R7 全程面板零固化块（`.bulk-receipt`/`#ac-receipt` 恒 0，浮层没了之后面板也不留回执文本）

零写入：只点「刷新额度」这一条**只读**查询腿（Raccoon 两号登录态已过期 ⇒ 后端判「未发起」、
本轮不对上游发请求，与用户实拍那张截图同一形态）；不点签到/续期/删除/映射开关。
"""
from __future__ import annotations

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
const extra = {};
function ck(id, desc, ok, measured) { checks.push({ id, desc, ok: !!ok, measured: String(measured) }); }

const task = await taskSpace("MGW 批量结果浮层真机判据");
const page = await (async () => {
  try { const p = task.page(PAYLOAD.pageLabel); await p.evaluate(() => 1); return p; }
  catch (e) { return await task.newPage(); }
})();
await page.cdp("Emulation.setDeviceMetricsOverride",
  { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
await page.goto(PAYLOAD.url);
await page.waitForSelector("#ac-table tbody tr", { timeout: 20000 });

const read = () => page.evaluate(() => {
  const txt = (n) => (n ? String(n.textContent || "").replace(/\s+/g, " ").trim() : "");
  const q = (s, r) => Array.from((r || document).querySelectorAll(s));
  const card = document.querySelector("#toast-wrap .toast.card");
  let geo = null;
  if (card) {
    const r = card.getBoundingClientRect();
    const sum = card.querySelector(".t-sum");
    const sr = sum ? sum.getBoundingClientRect() : null;
    geo = { w: Math.round(r.width), h: Math.round(r.height),
            overflow: Math.round((card.scrollWidth - card.clientWidth) * 10) / 10,
            sumLines: sr && sum ? Math.round(sr.height / parseFloat(getComputedStyle(sum).lineHeight)) : null,
            sum: txt(sum), sumTitle: sum ? (sum.getAttribute("title") || "") : "",
            title: txt(card.querySelector(".t-title")),
            tags: q(".t-row .t-tag", card).map(txt),
            rows: q(".t-row", card).length,
            inModal: !!card.closest(".modal"), inWrap: !!card.closest("#toast-wrap"),
            closeAria: card.querySelector(".t-close") ? card.querySelector(".t-close").getAttribute("aria-label") : "" };
  }
  return { geo, toasts: q("#toast-wrap .toast.card").length,
           masks: document.querySelectorAll(".modal-mask").length,
           modalRoot: (document.getElementById("modal-root") || { children: [] }).children.length,
           blocks: document.querySelectorAll(".bulk-receipt, #ac-receipt").length,
           panelHasReceiptText: txt(document.getElementById("ac-panel")).indexOf("刷新 0 个") >= 0,
           theme: document.documentElement.getAttribute("data-theme") };
});

const trigger = async () => {
  await page.evaluate(() => {
    const rail = Array.from(document.querySelectorAll(".subnav .anchor-item"))
      .find((x) => x.textContent.indexOf("Raccoon") >= 0);
    rail.click();
  });
  await page.waitForTimeout(900);
  await page.evaluate(() => {
    const b = Array.from(document.querySelectorAll("#ac-panel button"))
      .find((x) => x.textContent.trim() === "刷新额度" && !x.closest("tr"));
    b.click();
  });
  for (let i = 0; i < 200; i += 1) {
    if ((await read()).toasts > 0) return true;
    await page.waitForTimeout(100);
  }
  return false;
};

/* ---------- 第一击：内容 + 几何 + 不开弹窗，然后 × 手动关闭 ---------- */
const appeared = await trigger();
const a = await read();
ck("R1", "真点击卡头「刷新额度」后结果浮层出现（住在 #toast-wrap，不是合成调用）",
   appeared && a.toasts === 1 && !!a.geo && a.geo.inWrap === true,
   "送达=" + appeared + " 浮层数=" + a.toasts + " 标题=「" + ((a.geo || {}).title || "") + "」");
const g = a.geo || {};
const notFired = /未发起 (\d+) 个/.test(g.sum || "") ? Number(RegExp.$1) : -1;
ck("R2", "计数行原文 + 逐号行，且逐号结果词与计数**自洽**（未发起 N ⇒ N 行都写「未发起」，"
   + "不再出现旧写法把 reason=\"\" 标成「已刷新」那种自我矛盾）",
   /刷新 \d+ 个 · 失败 \d+ 个 · 未发起 \d+ 个/.test(g.sum || "")
   && g.rows >= 1 && g.tags.length === g.rows
   && notFired >= 0 && g.tags.filter((t) => t.indexOf("未发起") >= 0).length === notFired
   && (g.sumTitle || "").length > 40 && g.closeAria === "关闭提示",
   "计数行=「" + (g.sum || "") + "」 逐号=" + JSON.stringify(g.tags)
   + " 悬停解释=" + (g.sumTitle || "").length + "字 关闭 aria=「" + g.closeAria + "」");
ck("R3", "几何：宽 380px、内容不溢出自身、计数行不被折碎（1440×900 实测）",
   g.w === 380 && g.overflow <= 0.5 && g.sumLines === 1 && g.h > 40 && g.h <= 140,
   "w=" + g.w + " h=" + g.h + " 溢出=" + g.overflow + " 计数行折=" + g.sumLines + " 行");
ck("R4", "不开弹窗：遮罩数 0、modal-root 空、卡不在 .modal 内（单层红线由构造保证）",
   a.masks === 0 && a.modalRoot === 0 && g.inModal === false,
   "遮罩=" + a.masks + " modal-root=" + a.modalRoot + " 卡在弹窗里=" + g.inModal);

let b = a;
if (a.toasts === 1) {
  await page.evaluate(() => {
    const t = document.querySelector("#toast-wrap .toast.card");
    if (t) t.dataset.keepalive = "1";      // 只打标，不改变生命周期
  });
  await page.click("#toast-wrap .toast.card .t-close");
  await page.waitForTimeout(350);
  b = await read();
  ck("R5", "× 手动关闭立即消失（点完 350ms 内读数已为 0）",
     b.toasts === 0, "点关闭后浮层数=" + b.toasts);
}

/* ---------- 第二击：不点关闭，量它自己消失的时刻 ---------- */
const appeared2 = await trigger();
const t0 = Date.now();
let goneMs = null;
for (let i = 0; i < 90; i += 1) {
  await page.waitForTimeout(100);
  if ((await read()).toasts === 0) { goneMs = Date.now() - t0; break; }
}
const c = await read();
ck("R6", "不点关闭 ⇒ 约 3s 自动消失（实测落点记下来，判据取 2.4~4.5s 区间）",
   appeared2 && goneMs !== null && goneMs >= 2400 && goneMs <= 4500,
   "送达=" + appeared2 + " 自动消失于 " + goneMs + "ms");
ck("R7", "全程面板零固化块：`.bulk-receipt`/`#ac-receipt` 恒 0，浮层消失后面板也不留回执文本",
   a.blocks === 0 && c.blocks === 0 && c.panelHasReceiptText === false && c.toasts === 0,
   "第一击时块数=" + a.blocks + " 现在=" + c.blocks
   + " 面板残留回执文本=" + c.panelHasReceiptText + " 浮层=" + c.toasts);

/* ---------- 画面（浮层在屏时抓一张；PDF 兜底 = 本机无 OS 窗口） ----------
   🔴 时序坑（第一次抓出来的是**没有浮层的画面**）：`printToPDF` 自身要 1~2s，
   而浮层 3s 就消失 —— 先 sleep 250ms 再切主题再打印，等到光栅化时节点早被 `setTimeout(kill)` 摘掉了。
   改法 = 主题先设好、触发后**立刻**打印，中间不 sleep；并记录打印时浮层还在不在。 */
await page.evaluate(() => { document.documentElement.setAttribute("data-theme", "light"); });
await page.waitForTimeout(200);
await trigger();
const aliveAtPrint = (await read()).toasts;
/* 🔴 打印前把**入场动画**关掉（只此一项，位置/内容/配色一律不动）：
   `@keyframes toast-in` 的起点是 `opacity: 0`，而 print 快照把动画冻结在 t=0 ⇒
   第一次抓到的画面里浮层"存在但全透明"（`aliveAtPrint=1` 却没有画面）。
   这是取证手法的修正，不是产品形态的修正 —— 屏幕上这 180ms 之后本来就是可见的。 */
await page.evaluate(() => {
  document.querySelectorAll("#toast-wrap .toast").forEach((x) => { x.style.animation = "none"; });
});
try {
  const png = await page.cdp("Page.captureScreenshot", { format: "png" });
  fs.writeFileSync(PAYLOAD.shotsDir + "/bulk-receipt-toast-1440-light.png",
    Buffer.from(png.data, "base64"));
  extra.shot = "captureScreenshot ok";
} catch (e) {
  try {
    const pdf = await page.cdp("Page.printToPDF",
      { printBackground: true, paperWidth: 15, paperHeight: 9.4,
        marginTop: 0.2, marginBottom: 0.2, marginLeft: 0.2, marginRight: 0.2 });
    fs.writeFileSync(PAYLOAD.shotsDir + "/bulk-receipt-toast-1440-light.pdf",
      Buffer.from(pdf.data, "base64"));
    extra.shot = "PDF 兜底（captureScreenshot: " + String(e).slice(0, 70) + "）";
  } catch (e2) { extra.shot = "两种都失败: " + String(e2).slice(0, 90); }
}
extra.aliveAtPrint = aliveAtPrint;

extra.reads = { first: a, afterClose: b, afterExpire: c };
await page.evaluate(() => {
  document.querySelectorAll("#toast-wrap .toast").forEach((x) => x.remove());
});
fs.writeFileSync(OUT, JSON.stringify({ checks, extra }, null, 1), "utf8");
console.log("PROBE_DONE");
'''


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="mgw-bulktoast-"))
    shots = Path("/Users/w/Desktop/Model-Gateway/docs/changes/ui-rounds/20261003-bulk-receipt")
    shots.mkdir(parents=True, exist_ok=True)
    pfile = base / "payload.json"
    ofile = base / "results.json"
    jfile = base / "probe.js"
    pfile.write_text(json.dumps({"url": URL, "shotsDir": str(shots),
                                 "pageLabel": f"btoast-{base.name[-6:]}"},
                                ensure_ascii=False), encoding="utf-8")
    jfile.write_text(JS.replace("__PAYLOAD__", str(pfile)).replace("__OUT__", str(ofile)),
                     encoding="utf-8")
    with jfile.open("r", encoding="utf-8") as fh:
        proc = subprocess.run(["ego-browser", "nodejs"], stdin=fh, capture_output=True,
                              text=True, timeout=600, cwd=str(base))
    if not ofile.exists():
        print(f"✗ 浏览器没交回读数（rc={proc.returncode}）", file=sys.stderr)
        print("  stdout: " + proc.stdout[-700:], file=sys.stderr)
        print("  stderr: " + proc.stderr[-700:], file=sys.stderr)
        return 2
    data = json.loads(ofile.read_text(encoding="utf-8"))
    rows = data.get("checks", [])
    bad = [x["id"] for x in rows if not x["ok"]]
    for x in rows:
        print(f"  {'✓' if x['ok'] else '✗'} {x['id']} {x['desc']}｜{x['measured'][:210]}")
    print("  画面：" + str(data.get("extra", {}).get("shot")))
    print(f"\n合计：{len(rows) - len(bad)} 通过 / {len(bad)} 失败" + (f"  红：{bad}" if bad else ""))
    print("  打印时浮层在场：" + str(data.get("extra", {}).get("aliveAtPrint")))
    for pdf in sorted(shots.glob("*.pdf")):
        subprocess.run(["qlmanage", "-t", "-s", "1600", "-o", str(shots), str(pdf)],
                       capture_output=True, timeout=120)
        png = pdf.with_suffix(".pdf.png")
        print(("✓ 画面 " if png.exists() else "✗ 转 PNG 失败 ") + str(png if png.exists() else pdf))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
