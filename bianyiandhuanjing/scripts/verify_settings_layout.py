#!/usr/bin/env python3
"""系统设置「参数行」真机判据 · 只读探针（2026-10-03 用户实拍「信息太分散并且一个输入框那么宽，
设计很不合理很丑呀啊」后的结构重做：三卡满宽表单行 → 两卡参数行）。

静态侧已由 `verify_v2_frontend.mjs` 的 H3/H4/M18 钉住**产物文本**（CSS 定宽、死类已删、12 行一对一）。
本 runner 补静态门证明不了的那一半：**画出来的几何** —— 框的实际宽度、同一列右缘是否对齐、
名称/数字是否被裁、行高是否统一、点名称能否聚焦到那一颗框、底色是否真等于令牌、深色是否反转、
窄屏是否按断点回退。按本仓口径（frontend-spec §7.18 的教训）：**布局判据必须成对 —— L4 对齐 + L5 不溢出**，
只验对齐等于给自己发通行证（上一轮「定宽三列」把数字裁掉 39px 就是这么漏的）。

🔴 **只读**：只 `goto` 与测量；绝不点「保存配置」「重启网关」「停止网关」，也不做置脏测试
   （脏态/二段保存由静态门 M12~M15 在 realm 里真跑判定）。:8300 是用户在册实例，探针结束前把
   视口与主题复位回原值。跑完用 md5 自证「两个被测源文件一字未动」。

用法：
    coding/.venv/bin/python bianyiandhuanjing/scripts/verify_settings_layout.py
    coding/.venv/bin/python bianyiandhuanjing/scripts/verify_settings_layout.py --port 8479
    coding/.venv/bin/python bianyiandhuanjing/scripts/verify_settings_layout.py --shots DIR
退出码：0 = 全绿；1 = 有红；2 = 装配级错误（实例没活 / 浏览器没交回读数）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WATCHED = [
    "coding/model_gateway/web/static/js/pages/settings.js",
    "coding/model_gateway/web/static/css/base.css",
]

JS = r'''
const fs = await import("node:fs");
const PAYLOAD = JSON.parse(fs.readFileSync("__PAYLOAD__", "utf8"));
const OUT = "__OUT__";
const checks = [];
const extra = {};
function ck(id, desc, ok, measured) {
  checks.push({ id: id, desc: desc, ok: !!ok, measured: String(measured) });
}

const task = await taskSpace("MGW 系统设置参数行真机判据");
/* 取页两种姿势都要能跑（并行会话会抢同名标签 ⇒ 标签按进程唯一，红就红在自己的因上） */
const page = await (async () => {
  try {
    const p = task.page(PAYLOAD.pageLabel);
    await p.evaluate(() => 1);
    return p;
  } catch (e) {
    return await task.newPage();
  }
})();

async function setViewport(w, h) {
  await page.cdp("Emulation.setDeviceMetricsOverride",
    { width: w, height: h, deviceScaleFactor: 1, mobile: false });
  await page.waitForTimeout(260);
}
async function shot(name) {
  const p = PAYLOAD.shotsDir + "/" + name + ".png";
  for (let i = 0; i < 3; i++) {
    try { await page.screenshot({ path: p }); (extra.shots = extra.shots || []).push(p); return; }
    catch (e) {
      extra.shotErrors = (extra.shotErrors || []).concat(
        [name + "：" + String(e && e.message).slice(0, 90)]);
      await page.waitForTimeout(1200);
    }
  }
}
async function setTheme(mode) {
  await page.evaluate((m) => { localStorage.setItem("mg-theme", m); }, mode);
  await page.reload();
  await page.waitForSelector(".param-row", { timeout: 20000 });
  await page.waitForTimeout(300);
}
/* 截图前把窗口从 minimized 归回 normal（本机实测：窗口最小化时无帧可采，
   Page.captureScreenshot 必超时，而 DOM/几何读数一切正常 —— 别把"通道没开"当成"页面坏了"） */
async function wakeWindowForShots() {
  try {
    const info = await page.cdp("Browser.getWindowForTarget");
    const id = info.windowId;
    if ((info.bounds || {}).windowState !== "normal") {
      await page.cdp("Browser.setWindowBounds", { windowId: id, bounds: { windowState: "normal" } });
      await page.waitForTimeout(400);
    }
    extra.windowState = (await page.cdp("Browser.getWindowForTarget")).bounds.windowState;
  } catch (e) {
    extra.windowState = "取不到：" + String(e && e.message).slice(0, 60);
  }
}

const READ = () => {
  const rows = [...document.querySelectorAll(".param-row")];
  const cards = [...document.querySelectorAll("#content .card")];
  /* 令牌计算色一律用探针元素解析（不比自定义属性的原始文本：.25rem 这类会骗人） */
  const tokenRgb = (name) => {
    const probe = document.createElement("span");
    probe.style.cssText = "position:fixed;left:-9999px;top:0;width:1px;height:1px;"
      + "background: var(" + name + ")";
    document.body.appendChild(probe);
    const rgb = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return rgb;
  };
  const head = document.querySelector(".param-group .sec-head.sub .t");
  return {
    perRow: rows.map((r) => {
      const lb = r.querySelector("label.pk");
      const ip = r.querySelector("input.in");
      if (!lb || !ip) return { missing: true };
      const lr = lb.getBoundingClientRect(), ir = ip.getBoundingClientRect();
      const cs = getComputedStyle(ip), cls = getComputedStyle(lb);
      const hit = document.elementFromPoint(lr.left + lr.width / 2, lr.top + lr.height / 2);
      return {
        name: ip.getAttribute("name"), sec: ip.getAttribute("data-sec"),
        labelFor: lb.getAttribute("for"), inputId: ip.id,
        rowH: Math.round(r.getBoundingClientRect().height * 100) / 100,
        inW: Math.round(ir.width * 100) / 100,
        inLeft: Math.round(ir.left * 100) / 100,
        inRight: Math.round(ir.right * 100) / 100,
        labelClip: Math.round((lb.scrollWidth - lb.clientWidth) * 100) / 100,
        inputClip: Math.round((ip.scrollWidth - ip.clientWidth) * 100) / 100,
        textAlign: cs.textAlign, inputBg: cs.backgroundColor,
        labelWeight: Number(cls.fontWeight), inputWeight: Number(cs.fontWeight),
        /* 🔴 量**文本**的右缘，不是盒子的右缘：label 是 grid 项、盒子被 1fr 拉满整列，
           拿盒子量出来的间距恒等于 grid gap（12px），列铺满 580px 也照样"绿"——
           这是一条空判据，撤证 R4 就是这么抓出来的（frontend-spec §7.18「判据对象选错」同族）。 */
        textGapToBox: (() => {
          const rng = document.createRange();
          rng.selectNodeContents(lb);
          const d = Math.round((ir.left - rng.getBoundingClientRect().right) * 100) / 100;
          rng.detach();
          return d;
        })(),
        rowW: Math.round(r.getBoundingClientRect().width * 100) / 100,
        hitSelf: (hit === lb || lb.contains(hit)) ? 1 : 0,
      };
    }),
    /* 分组语义靠**垂直间距**表达（本仓不用分割线）：组头离上一组末行要明显远于组内行距 */
    groups: [...document.querySelectorAll(".param-group")].map((gp) => {
      const head = gp.querySelector(".sec-head.sub");
      const rs = [...gp.querySelectorAll(".param-row")];
      const hr = head ? head.getBoundingClientRect() : null;
      /* 🔴 说明跟着分组走（用户第三次实拍纠正）⇒ 每组必须**自己带一条** `.param-notes .pn`，
         并且它是该组的**最后一个元素**：只有它是末元素，它的下缘才正好坐在下一组分割线之上。
         集中到卡尾一块 = 每条读数都会红在这里（不是放宽，是把判据对象换成需求那个集合）。 */
      const nt = gp.querySelector(":scope > .param-notes .pn");
      const nr = nt ? nt.getBoundingClientRect() : null;
      const gr = gp.getBoundingClientRect();
      return {
        t: head ? head.textContent.trim() : "",
        headTop: hr ? Math.round(hr.top * 100) / 100 : null,
        headBottom: hr ? Math.round(hr.bottom * 100) / 100 : null,
        firstRowTop: rs[0] ? Math.round(rs[0].getBoundingClientRect().top * 100) / 100 : null,
        lastRowBottom: rs.length ? Math.round(rs[rs.length - 1].getBoundingClientRect().bottom * 100) / 100 : null,
        rowCount: rs.length,
        noteCount: gp.querySelectorAll(":scope > .param-notes .pn").length,
        noteIsLast: !!gp.lastElementChild && gp.lastElementChild.classList.contains("param-notes"),
        noteBottom: nr ? Math.round(nr.bottom * 100) / 100 : null,
        groupBottom: Math.round(gr.bottom * 100) / 100,
        noteText: nt ? nt.textContent.trim().slice(0, 18) : "",
      };
    }),
    cardCount: cards.length,
    cardTitles: cards.map((c) => ((c.querySelector(".card-title") || {}).textContent) || ""),
    groupHeads: [...document.querySelectorAll(".param-group .sec-head.sub .t")].map((x) => x.textContent),
    /* 🔴 2026-10-03 用户指示改版后新增的读数（组内不再画可见小标题 ⇒ 分组只剩两样东西：
       `aria-label`（语义）与分割线（视觉）；「保存配置」搬进卡内 ⇒ 脚钮区必须落在卡的盒子里。
       这几条读数字段就是 L1 / L9 / L15 / L16 的判据对象，缺一即红。 */
    groupAria: [...document.querySelectorAll(".param-group")].map((gp) => gp.getAttribute("aria-label") || ""),
    groupBorder: [...document.querySelectorAll(".param-group")].map((gp) => getComputedStyle(gp).borderTopWidth),
    noteNameWeight: (() => { const n = document.querySelector(".param-notes .pn b");
      return n ? getComputedStyle(n).fontWeight : "none"; })(),
    cardTitleWeight: (() => { const t = document.querySelector("#st-exec .card-title");
      return t ? getComputedStyle(t).fontWeight : "none"; })(),
    notesAboveFoot: (() => { const ns = [...document.querySelectorAll(".param-notes")],
      f = document.querySelector(".card-foot");
      if (!ns.length || !f) return false;
      /* 🔴 量**最后一条**说明（每组一条之后 `querySelector` 只会拿到第一组那条，
         它离卡脚十万八千里，这条判据就永远为真 = 空判据）。 */
      const n = ns[ns.length - 1];
      return Math.round((f.getBoundingClientRect().top - n.getBoundingClientRect().bottom) * 100) / 100 >= -0.5; })(),
    footInsideCard: (() => { const c = document.querySelector("#st-exec"), f = document.querySelector(".card-foot");
      if (!c || !f) return false; const a = c.getBoundingClientRect(), b = f.getBoundingClientRect();
      return b.bottom <= a.bottom + 0.5 && b.right <= a.right + 0.5 && b.left >= a.left - 0.5; })(),
    saveBtnInFoot: !!document.querySelector(".card-foot #st-save"),
    notesRows: document.querySelectorAll(".param-notes .pn").length,
    /* 🔴 板块头必须**同一行**且描述**弱化**（2026-10-03 用户第四次实拍：描述放到标题后面弱化显示，
       不要单独占一行）。量的是画出来的几何与计算样式，不是 CSS 字符串。 */
    blockHead: [...document.querySelectorAll(".card-head.block-head")].map((h) => {
      const t = h.querySelector(".card-title, .bh-t"), d = h.querySelector(".bh-d");
      if (!t || !d) return { missing: true };
      const a = t.getBoundingClientRect(), b = d.getBoundingClientRect();
      const ct = getComputedStyle(t), cd = getComputedStyle(d);
      return {
        sameLine: Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 0,
        /* 🔴 量**文本**边缘，不是盒子边缘：第一版用 `d.left - t.right`，而间距写成 `.bh-d` 的
           padding-left ⇒ 两个盒子紧挨着，读数恒为 0（真机 L18 就是这么红的）。
           同族教训见本文件 L14 的注释与 frontend-spec §7.18。 */
        afterTitle: (() => {
          const r1 = document.createRange(); r1.selectNodeContents(t);
          const r2 = document.createRange(); r2.selectNodeContents(d);
          const v = Math.round((r2.getBoundingClientRect().left - r1.getBoundingClientRect().right) * 100) / 100;
          r1.detach(); r2.detach();
          return v;
        })(),
        tSize: Number(parseFloat(ct.fontSize).toFixed(1)), dSize: Number(parseFloat(cd.fontSize).toFixed(1)),
        tWeight: Number(ct.fontWeight), dWeight: Number(cd.fontWeight),
        tColor: ct.color, dColor: cd.color,
        title: t.textContent.trim(),
      };
    }),
    groupHeadWeight: head ? getComputedStyle(head).fontWeight : "none",
    formRowCount: document.querySelectorAll(".form-row").length,
    formGrid2Count: document.querySelectorAll(".form-grid2").length,
    cardOverflow: cards.map((c) => Math.round((c.scrollWidth - c.clientWidth) * 100) / 100),
    scrollH: document.getElementById("content").scrollHeight,
    clientH: document.getElementById("content").clientHeight,
    innerW: window.innerWidth,
    tokenMuted: tokenRgb("--surface-muted"),
    tokenTextMuted: tokenRgb("--text-muted"),
    theme: document.documentElement.getAttribute("data-theme") || "",
  };
};
const read = () => page.evaluate(READ);
const spread = (v) => (v.length ? Math.max(...v) - Math.min(...v) : 0);
const rightsByCluster = (r) => {
  const lefts = [...new Set(r.perRow.map((x) => x.inLeft))];
  return { lefts: lefts, spreads: lefts.map((L) => spread(
    r.perRow.filter((x) => x.inLeft === L).map((x) => x.inRight))) };
};

await setViewport(1440, 900);
await page.goto(PAYLOAD.url + "#/settings");
await page.waitForSelector(".param-row", { timeout: 25000 });
/* 🔴 主题必须**显式设定**再开测：:8300 是用户在册实例，它的 localStorage 里存的是**他选的**主题
   （本轮首跑就栽在这里 —— 用户是深色，我把第一遍读数当浅色、"深色令牌 != 浅色"那条永远不可能红
   也不可能绿得有意义；同一族坑在 pitfalls 里记过两次：复用共享标签页 / 未显式设主题）。
   收尾按原值精确复位（原本没有该键就 removeItem，别替用户留下偏好）。 */
const initialTheme = await page.evaluate(() => localStorage.getItem("mg-theme"));
await wakeWindowForShots();
await setTheme("light");
let r = null;
for (let i = 0; i < 30; i++) {
  await page.waitForTimeout(250);
  try { r = await read(); } catch (e) { r = null; }
  if (r && r.perRow.length === 12 && !r.perRow.some((x) => x.missing)) break;
}
if (!r || r.perRow.length !== 12 || r.perRow.some((x) => x.missing)) {
  ck("L0", "页面在真 Chrome 里读出 12 条完整参数行（一名称 + 一数值框）", false,
     "读到 " + (r ? r.perRow.length : 0) + " 条；缺件行=" + (r ? r.perRow.filter((x) => x.missing).length : "-"));
} else {
  const P = r.perRow;
  const w = P.map((x) => x.inW);
  const clu = rightsByCluster(r);
  const clipWorst = Math.max(...P.map((x) => Math.max(x.labelClip, x.inputClip)));

  ck("L1", "两卡 + 运行参数卡五组，且**全页不画可见组头**（2026-10-03 用户指示：去掉「网关服务/超时预算」这类子标题）",
     r.cardCount === 2 && r.cardTitles[0] === "运行参数" && r.cardTitles[1] === "维护"
       && r.groupHeads.length === 0 && r.groups.length === 6
       && r.groupAria.filter(Boolean).length === 6,
     "卡=" + JSON.stringify(r.cardTitles) + "；可见组头=" + JSON.stringify(r.groupHeads)
       + "；组数=" + r.groups.length + "（运行参数 5 + 维护 1）；aria=" + JSON.stringify(r.groupAria));
  ck("L2", "12 行逐行「一个名称 + 一个数值框」，名称 for 与框 id 一一对应且不重复",
     P.every((x) => x.labelFor && x.labelFor === x.inputId)
       && new Set(P.map((x) => x.inputId)).size === 12,
     "for≠id 的行=" + JSON.stringify(P.filter((x) => x.labelFor !== x.inputId).map((x) => x.name))
       + "；id 去重后=" + new Set(P.map((x) => x.inputId)).size + "/12");
  ck("L3", "数值框实测宽度 === 128px（正解是定宽，不是把 4 位数住进满宽 1fr）",
     Math.min(...w) >= 127.5 && Math.max(...w) <= 128.5,
     "宽度 min=" + Math.min(...w) + " max=" + Math.max(...w) + "（12 行全量）");
  ck("L4", "成对判据①对齐：同一列内框的右缘实测差 ≤0.5px（数值列是一条直线）",
     spread(clu.spreads.length ? clu.spreads : [0]) <= 0.5,
     "左缘簇=" + JSON.stringify(clu.lefts) + "；各簇右缘跨度=" + JSON.stringify(clu.spreads));
  ck("L5", "成对判据②不溢出：名称与数字都不被裁、卡横向不溢出（定宽三列那版裁掉数字 39px 的同一课）",
     clipWorst <= 0.5 && Math.max(...r.cardOverflow) <= 1,
     "最坏裁剪量=" + clipWorst + "px；卡横向溢出=" + JSON.stringify(r.cardOverflow));
  ck("L6", "行几何统一：12 行实测行高全等（±0.5px）",
     spread(P.map((x) => x.rowH)) <= 0.5,
     "行高集合=" + JSON.stringify([...new Set(P.map((x) => x.rowH))]));
  ck("L7", "点击命中落在名称自身（没有遮罩/重叠层吃掉这一击）",
     P.every((x) => x.hitSelf === 1),
     "hitSelf=0 的行=" + JSON.stringify(P.filter((x) => !x.hitSelf).map((x) => x.name)));
  const focus = await page.evaluate(() => {
    const out = [];
    for (const row of [...document.querySelectorAll(".param-row")]) {
      const lb = row.querySelector("label.pk"), ip = row.querySelector("input.in");
      lb.click();
      out.push(document.activeElement === ip ? 1 : 0);
      ip.blur();
    }
    return out;
  });
  ck("L7b", "点名称即聚焦这一行的那颗框（真派发 click，12/12）",
     focus.every((x) => x === 1),
     "聚焦成功 " + focus.filter((x) => x === 1).length + "/12");
  ck("L8", "框底色 === --surface-muted 探针解析值 且数字右对齐",
     P.every((x) => x.inputBg === r.tokenMuted) && P.every((x) => x.textAlign === "right"),
     "令牌=" + r.tokenMuted + "；不等色行=" + JSON.stringify(
       P.filter((x) => x.inputBg !== r.tokenMuted).map((x) => x.name))
       + "；text-align 集合=" + JSON.stringify([...new Set(P.map((x) => x.textAlign))]) );
  ck("L9", "字重是层级语言：行内（名称/数值）不抢 700，700 住在卡标题与卡尾说明的组名上（组头已不画）",
     P.every((x) => x.labelWeight < 700 && x.inputWeight < 700)
       && Number(r.noteNameWeight) >= 700 && Number(r.cardTitleWeight) >= 700,
     "名称=" + JSON.stringify([...new Set(P.map((x) => x.labelWeight))])
       + " 数值=" + JSON.stringify([...new Set(P.map((x) => x.inputWeight))])
       + " 卡标题=" + r.cardTitleWeight + " 说明组名=" + r.noteNameWeight);
  ck("L10", "满宽表单行不再住在页面上（.form-row / .form-grid2 计数均为 0）",
     r.formRowCount === 0 && r.formGrid2Count === 0,
     "form-row=" + r.formRowCount + " form-grid2=" + r.formGrid2Count);
  ck("L11", "聚合效果可量化：1440×900 下整页内容高 ≤ 可视高（一屏看完，不用逐卡找参数）",
     r.scrollH <= r.clientH + 1,
     "内容高=" + r.scrollH + " 可视高=" + r.clientH + "（视口宽 " + r.innerW + "）");
  /* L14/L15 = 首版实拍（PDF 兜底取证）自己看出来的缺陷：列铺满整张卡时名称与自己的框之间空 ~300px，
     "名称—值"的配对感没了；组头贴上一组末行，分组只靠字号区分。两条都量**画出来的间距**。
     🔴 L14 第一版量的是 label 的**盒子**右缘，而 label 是 1fr 网格项、盒子被拉满整列 ⇒ 读数恒等于
     grid gap 12px，把 `.param-list` 退回铺满形状照样 16/0 —— 撤证 R4 当场抓到这条**永远不会红的空判据**
     （坏例子红不了的判据等于没有判据；同族见 frontend-spec §7.18「V15 判据对象选错」「D4b 长期空转」）。
     现在量 Range 的**文本**右缘 + 行实测宽。 */
  const tg = P.map((x) => x.textGapToBox);
  const rw = P.map((x) => x.rowW);
  ck("L14", "列宽受限 ⇒ 名称**文本**到自己框的实测距离 ≤220px 且每行宽 ≤440px（不是隔空对齐到 580px 列的两端）",
     Math.max(...tg) <= 220 && Math.max(...rw) <= 440,
     "文本→框 min=" + Math.min(...tg) + " max=" + Math.max(...tg)
       + "；行宽 min=" + Math.min(...rw) + " max=" + Math.max(...rw)
       + "；越界行=" + JSON.stringify(P.filter((x) => x.textGapToBox > 220 || x.rowW > 440).map((x) => x.name)));
  const g = r.groups;
  const gb = r.groupBorder;
  /* 组内不画小标题之后，"这是一组"只剩两样记号：分割线 + 组间距。
     量的是**画出来的**border-top 宽度与相邻组末行→首行的实测距离（不是 margin 声明值）。
     🔴 只量运行参数卡内的前五组：第 6 组住在另一张卡（维护）里，与第 5 组之间没有"组间"关系
        —— 拿它算距离会得到 −517px 这种跨卡负值（首版判据就是这么红的，属判据对象选错）。
        它自己的那条"首组前不画线"仍单独断言（`gb[5] === "0px"`）。 */
  const p5 = g.slice(0, 5);
  const between = p5.slice(1).map((x, i) => Math.round((x.firstRowTop - p5[i].lastRowBottom) * 100) / 100);
  ck("L15", "分组由分割线 + 组间距表达：卡内首组前不画线、其余四组各 1px、组间实测 ≥16px；维护卡首组同样不画线",
     gb.length === 6 && gb[0] === "0px" && gb.slice(1, 5).every((x) => x === "1px")
       && gb[5] === "0px" && Math.min(...between) >= 16,
     "border-top=" + JSON.stringify(gb) + "；组间实测=" + JSON.stringify(between) + "；组数=" + g.length);
  ck("L16", "「保存配置」住在板块框内部（用户指示：按钮搬进板块框内部）",
     r.saveBtnInFoot && r.footInsideCard,
     "钮在脚区内=" + r.saveBtnInFoot + "；脚区在卡内=" + r.footInsideCard);
  /* 🔴 L17 = 用户第三次实拍纠正的判据：「这些说明信息不是让你集中放一起……是放到每个配置分组
     下面，下一组配置分割线之上」。三条腿一起量，缺一半就是空判据：
     ① 卡内五组**每组恰一条**（`noteCount === 1`，集中成卡尾一块 ⇒ 前五组读数是 0）；
     ② 该条是**本组最后一个元素**（`noteIsLast`，否则它会插在参数行中间）；
     ③ 它的下缘 ≤ 本组下缘（`noteBottom ≤ groupBottom`）⇒ 下一组的 border-top 必然在它下面
        （线在下一个元素的顶边，几何上等价于"说明坐在线之上"）。
     第 6 组住在「维护」卡里、用的是 `.group-note`（就近注记另一条线），不参与本判据。 */
  const g5 = g.slice(0, 5);
  ck("L17", "说明跟着分组走：卡内五组各恰一条、且是本组末元素 ⇒ 天然坐在下一组分割线之上",
     g5.every((x) => x.noteCount === 1) && g5.every((x) => x.noteIsLast)
       && g5.every((x) => x.noteBottom !== null && x.noteBottom <= x.groupBottom + 0.5)
       && r.notesRows === 5 && r.notesAboveFoot,
     "逐组[条数/末元素/说明下缘≤组下缘]=" + JSON.stringify(g5.map((x) => [x.noteCount, x.noteIsLast ? 1 : 0,
       x.noteBottom !== null && x.noteBottom <= x.groupBottom + 0.5 ? 1 : 0]))
       + "；全页说明行=" + r.notesRows + "；最后一条在卡脚之上=" + r.notesAboveFoot
       + "；组名=" + JSON.stringify(g5.map((x) => x.noteText)));
  /* 🔴 L18 = 用户第四次实拍：「板块标题描述板块的描述信息，放到板块标题后面 弱化显示，
     不要单独占一行」。四条腿一起量（缺一半就是空判据）：
     ① 标题与描述**同一行**（两者矩形在纵向上有重叠）；② 描述在标题**右边**（实测间隙 6~28px，
        不是换行也不是贴死）；③ 描述**确实被弱化**：字号严格小于标题、字重严格小于标题、
        计算色 === `--text-muted` 探针值（🔴 不许是 `--text-faint`，那是本轮登记过的 2.32:1 不达标灰）；
     ④ 标题仍是全页最重（>= 800）。两张卡（运行参数 / 维护）都要过，不是只抽查一张。 */
  const bh = r.blockHead;
  ck("L18", "板块头单行：标题 + 描述同一行、描述在标题之后且被弱化（字号/字重/色三样都低一档）",
     bh.length === 2 && bh.every((x) => !x.missing)
       && bh.every((x) => x.sameLine && x.afterTitle >= 6 && x.afterTitle <= 28)
       && bh.every((x) => x.dSize < x.tSize && x.dWeight < x.tWeight && x.dWeight <= 600)
       && bh.every((x) => x.dColor === r.tokenTextMuted && x.tWeight >= 800),
     "板块头=" + JSON.stringify(bh.map((x) => x.missing ? "缺" : [x.title,
       "同行" + (x.sameLine ? 1 : 0), "间隙" + x.afterTitle, x.tSize + "/" + x.tWeight,
       x.dSize + "/" + x.dWeight, x.dColor === r.tokenTextMuted ? "muted✓" : x.dColor])));
  await shot("settings-1440-light");

  await setTheme("dark");
  await wakeWindowForShots();
  const d = await read();
  const dw = d.perRow.map((x) => x.inW);
  ck("L12", "深色反转：底色等于深色 --surface-muted 探针值、且与浅色不同，宽度仍是 128px",
     d.perRow.every((x) => x.inputBg === d.tokenMuted) && d.tokenMuted !== r.tokenMuted
       && Math.min(...dw) >= 127.5 && Math.max(...dw) <= 128.5,
     "深色令牌=" + d.tokenMuted + " 浅色=" + r.tokenMuted
       + "；宽度=" + Math.min(...dw) + "~" + Math.max(...dw));
  await shot("settings-1440-dark");

  await setViewport(1024, 900);
  await page.waitForTimeout(400);
  const n = await read();
  const nclu = rightsByCluster(n);
  ck("L13", "窄屏 1024 按断点回退单列：左缘只一簇、右缘跨度 ≤0.5px、零裁剪",
     nclu.lefts.length === 1 && spread(n.perRow.map((x) => x.inRight)) <= 0.5
       && Math.max(...n.perRow.map((x) => Math.max(x.labelClip, x.inputClip))) <= 0.5,
     "左缘簇=" + JSON.stringify(nclu.lefts) + "；右缘跨度="
       + spread(n.perRow.map((x) => x.inRight)) + "；最坏裁剪="
       + Math.max(...n.perRow.map((x) => Math.max(x.labelClip, x.inputClip))));
  await shot("settings-1024-single-column");

  /* 复位：按原值归还用户的主题偏好（原本没这个键就删掉），视口回 1440×900 */
  await page.evaluate((t) => {
    if (t === null) localStorage.removeItem("mg-theme");
    else localStorage.setItem("mg-theme", t);
  }, initialTheme);
  await page.reload();
  await page.waitForSelector(".param-row", { timeout: 20000 });
  await setViewport(1440, 900);
  extra.themeRestoredTo = initialTheme === null ? "(原无该键，已删)" : initialTheme;
}

fs.writeFileSync(OUT, JSON.stringify({ checks: checks, extra: extra }, null, 1));
'''


def sha256(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def instance_alive(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url + "/admin/api/status", timeout=5) as resp:
            return resp.status == 200, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:  # 服务在、路由错也算活着
        return True, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8300)
    ap.add_argument("--shots", default="", help="截图目录（默认 <临时根>/shots）")
    ap.add_argument("--work", default="", help="临时根（默认 mkdtemp）")
    ap.add_argument("--keep", action="store_true", help="保留临时目录")
    args = ap.parse_args()

    url = f"http://127.0.0.1:{args.port}"
    ok, why = instance_alive(url)
    if not ok:
        print(f"✗ 实例 {url} 没活（{why}）—— 本探针只读，不自起实例", file=sys.stderr)
        return 2

    base = Path(args.work or tempfile.mkdtemp(prefix="mgw-settings-layout-"))
    base.mkdir(parents=True, exist_ok=True)
    shots = Path(args.shots) if args.shots else base / "shots"
    shots.mkdir(parents=True, exist_ok=True)

    before = {f: sha256(f) for f in WATCHED}
    pfile = base / "payload.json"
    ofile = base / "results.json"
    jfile = base / "probe.js"
    pfile.write_text(json.dumps({
        "url": url, "shotsDir": str(shots), "pageLabel": f"settings-{__import__('os').getpid()}",
    }, ensure_ascii=False), encoding="utf-8")
    jfile.write_text(JS.replace("__PAYLOAD__", str(pfile)).replace("__OUT__", str(ofile)),
                     encoding="utf-8")

    with jfile.open("r", encoding="utf-8") as fh:
        proc = subprocess.run(["ego-browser", "nodejs"], stdin=fh,
                              capture_output=True, text=True, timeout=600, cwd=str(base))
    if not ofile.exists():
        print(f"✗ 浏览器没交回读数（rc={proc.returncode}）", file=sys.stderr)
        print("  stdout: " + proc.stdout[-1200:], file=sys.stderr)
        print("  stderr: " + proc.stderr[-1200:], file=sys.stderr)
        return 2

    data = json.loads(ofile.read_text(encoding="utf-8"))
    rows = data.get("checks", [])
    failed = [c["id"] for c in rows if not c["ok"]]
    for c in rows:
        print(f"  {'✓' if c['ok'] else '✗'} {c['id']} {c['desc']}｜{c['measured'][:220]}")
    ex = data.get("extra") or {}
    if ex.get("shotErrors"):
        print(f"  （截图失败 {len(ex['shotErrors'])} 张：{ex['shotErrors'][0]}）")
    elif ex.get("shots"):
        print(f"  截图 {len(ex['shots'])} 张 → {shots}")

    changed = [f for f in WATCHED if sha256(f) != before[f]]
    print(f"  只读自证：受监视 {len(WATCHED)} 个源文件 sha256 前后一致"
          f"{'（是）' if not changed else '（否！变动=' + str(changed) + '）'}")

    print("=" * 56)
    print(f"合计：{len(rows) - len(failed)} 通过 / {len(failed)} 失败"
          + (f" {failed}" if failed else ""))
    if not args.keep:
        import shutil
        shutil.rmtree(base, ignore_errors=True)
    else:
        print(f"临时根：{base}")
    return 1 if failed or changed else 0


if __name__ == "__main__":
    sys.exit(main())
