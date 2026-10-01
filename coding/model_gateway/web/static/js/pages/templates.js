/** 模板页面：模板库浏览与内嵌运行（#/templates；2026-10-01 用户指示重新接入侧栏）。
 *
 * 侧栏入口 = 「模板」分组 ·「模板页面」；子侧栏 = 模板清单（总览 + 基准 / P0 / 需求预演 三组），
 * 右主区 = 总览卡片网格 ⇄ 预览（iframe 内嵌运行：宽度切换 1440/1280/1024/适应、主题跟随控制台、
 * 刷新 / 复制路径 / 新标签打开；深链 `#/templates?t=<id>`）。
 * 结构 = frontend-spec §3 双面板页（`.panel-split` 类化 gutter，§2.3 v2.16 收口）；
 * 组件全部复用 base.css 既有类（新增样式仅 1 条：≤768 条带模式下的分组子侧栏横排，见 base.css 媒体块）。
 *
 * 🔴 目录与 `static/templates/*.html` 的双向一致由 `tests/unit/test_v2_templates_page.py` 钉住
 *    （新增/删除模板文件而不同步本目录 = 测试红），这是"所有模板都在这个入口里"的机械保证。 */

import { esc } from "../api.js";
import { tabBar, copyText } from "../components.js";

const svg = (inner, size = 14) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor"
     stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`;
const ICON_COPY = svg(`<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>`);
const ICON_OPEN = svg(`<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>`);
const ICON_TPL = svg(`<rect width="18" height="7" x="3" y="3" rx="1"/><rect width="9" height="7" x="3" y="14" rx="1"/><rect width="5" height="7" x="16" y="14" rx="1"/>`, 20);

/* ---------- 模板目录（id = 深链 ?t= 值；file = static/templates/ 下文件名；short = 子侧栏行名） ---------- */
const TEMPLATES = [
  { id: "tpl-providers", code: "基准", family: "基准", file: "template-providers.html",
    name: "模型供应商", short: "模型供应商", skeleton: "A · 子侧栏双面板", tags: ["表单 · 列表卡 · 映射卡"],
    desc: "1:1 复刻参考页 ConsolePage.tsx。子侧栏 / 双面板 / 表单 / 列表卡 / 映射卡齐备，是骨架 A 的对照基准。" },
  { id: "tpl-skills", code: "基准", family: "基准", file: "template-skills.html",
    name: "技能页", short: "技能页", skeleton: "B · tab + 列表", tags: ["分段 tab · 搜索 · 列表卡"],
    desc: "1:1 复刻参考页。分段 tab / 搜索 / 列表卡 / 市场面板，是骨架 B 的对照基准。" },
  { id: "tpl-detail-tabs", code: "T-01", family: "P0", file: "template-detail-tabs.html",
    name: "主从详情（子侧栏 + 详情内页签）", short: "主从详情", skeleton: "A · 子侧栏双面板", tags: ["TB-3 主从页签"],
    desc: "资源 / 模型 / 账号详情。头卡 → 5 个内页签（概览 · 密钥与账号 · 模型映射 · 连通性 · 用量），页签切换不重载头卡。" },
  { id: "tpl-tabs-view", code: "T-02", family: "P0", file: "template-tabs-view.html",
    name: "工作台页签条（多对象并行）", short: "页签条", skeleton: "A/B · 外壳层", tags: ["TB-4 工作台页签条"],
    desc: "顶栏下方 36px 页签条：多对象并行、固定（无关闭钮）、关闭后激活右邻、溢出 … 下拉、动态新开对照页签。" },
  { id: "tpl-table-workarea", code: "T-03", family: "P0", file: "template-table-workarea.html",
    name: "数据表工作区（多组 tab + 筛选 + 多选批量）", short: "数据表", skeleton: "B · tab + 列表", tags: ["TB-1/TB-2"],
    desc: "多组 tab 工具行 + 筛选卡 + 多选批量条 + 全字段表格。含「上游形态」合规三态列与受限行弱化。" },
  { id: "tpl-dashboard-metrics", code: "T-04", family: "P0", file: "template-dashboard-metrics.html",
    name: "观测看板（指标卡 + 图表 + 明细表）", short: "观测看板", skeleton: "C · 数据观测", tags: ["TB-1/TB-2"],
    desc: "指标卡行 + 24h 趋势（纯 CSS 降级柱状）+ 环形占比 + TOP 条形 + 明细表；含可见可控的自动刷新开关。" },
  { id: "tpl-stepper-wizard", code: "T-05", family: "P0", file: "template-stepper-wizard.html",
    name: "多步向导（Stepper）", short: "多步向导", skeleton: "D · 工具页", tags: ["TB-5 向导步骤条"],
    desc: "5 步接入向导：选宿主 → 凭据 → 选模型 → 账号授权（两步式登录轮询态）→ 完成；步骤条状态机可点击步进。" },
  { id: "tpl-code-viewer", code: "T-06", family: "P0", file: "template-code-viewer.html",
    name: "代码与配置查看器（多语言 tab + 复制）", short: "代码查看器", skeleton: "D · 工具页", tags: ["TB-1 · .code-tabs"],
    desc: "curl / Python / Node / 环境变量 四语言 tab（恒深底代码块、密钥脱敏）+ 可复制模型清单（未取证显示「未核实」）。" },
  { id: "tpl-tabbed-card", code: "T-15", family: "预演", file: "template-tabbed-card.html",
    name: "大卡内页签（整合卡片 + 卡内切换）", short: "大卡内页签", skeleton: "A · 整合大卡片", tags: ["TB-3 内页签", "演示状态机"],
    desc: "页头下方一张整体大卡片，卡内顶部为切换页签；含加载 / 空 / 错误 / 无结果 / 停用 / 受限等演示状态。" },
  { id: "tpl-premium-list", code: "T-16", family: "预演", file: "template-premium-list.html",
    name: "列表内容板块（左栏 + 页头 + 列表）", short: "列表板块", skeleton: "B · 列表视图", tags: ["TB-1/TB-2 列表", "固定轨道"],
    desc: "左侧栏 + 页头 + 内容板块（列表数据）三段式；列表固定轨道列零漂移，含多态演示与窄屏回退。" },
  { id: "tpl-vendor-accounts", code: "T-17", family: "预演", file: "template-vendor-accounts.html",
    name: "多端账号授权（产品 × 账号主从）", short: "多端账号授权", skeleton: "A · 子侧栏双面板", tags: ["TB-3 主从", "需求预演"],
    desc: "产品 × 账号两级主从（多端授权工作台原型）；含筛选与状态机演示。需求形态预演 · 非线上功能。" },
  { id: "tpl-model-routing", code: "T-18", family: "预演", file: "template-model-routing.html",
    name: "模型路由（匹配 · 选路 · 切换 · 恢复）", short: "模型路由", skeleton: "A · 子侧栏双面板", tags: ["路由判定链", "演示状态机"],
    desc: "入站模型名到实际承接资源的完整判定链：匹配（别名 / 前缀剥离）→ 生效集（x · 在途最少）→ 失败切换（y 先于 m）→ 冷却恢复；含 5 态演示与资源顺位 / 切换事件。" },
];

const FAMILY_CLS = { "基准": "b-gray", "P0": "b-cool", "预演": "b-warn" };
const WIDTHS = [{ id: 1440, label: "1440" }, { id: 1280, label: "1280" },
                { id: 1024, label: "1024" }, { id: 0, label: "适应" }];

const byId = (id) => TEMPLATES.find((t) => t.id === id) || null;
const themeOf = () => (document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light");
const frameUrl = (t) => `/templates/${t.file}?theme=${themeOf()}`;

const state = { mode: "overview", id: null };
let width = 1440;                 // 跨切换保留（回页默认 1440）
let themeObs = null;              // 主题跟随：控制台 [data-theme] 变化 → iframe 按新主题重载

export async function renderTemplates(root) {
  const t = parseTarget();
  state.mode = t ? "preview" : "overview";
  state.id = t ? t.id : null;
  draw(root);
}

function parseTarget() {
  const q = location.hash.split("?")[1] || "";
  const m = q.match(/(?:^|&)t=([\w-]+)/);
  return m ? byId(m[1]) : null;
}

function setHash(id) {
  const target = id ? `#/templates?t=${id}` : "#/templates";
  if (location.hash !== target) history.replaceState(null, "", target);
}

/* ---------- 骨架（§3 双面板页；gutter 由 .panel-split 承担） ---------- */
function draw(root) {
  const groups = [
    { title: "", items: [null] },                                   // null = 总览项
    { title: "基准模板 · 对照", items: TEMPLATES.filter((t) => t.family === "基准") },
    { title: "P0 · 本期新增", items: TEMPLATES.filter((t) => t.family === "P0") },
    { title: "需求预演", items: TEMPLATES.filter((t) => t.family === "预演") },
  ];
  root.innerHTML = `
    <div class="panel-split">
      <aside class="subnav">
        <div class="subnav-scroll">
          ${groups.map((g) => `
            ${g.title ? `<div style="font-size:12px;font-weight:700;color:var(--text-faint);margin:12px 0 8px 2px">${g.title}</div>` : ""}
            <div class="group-card">
              ${g.items.map((t) => (t ? `
                <button class="anchor-item${state.mode === "preview" && state.id === t.id ? " active" : ""}"
                        data-tpl-id="${t.id}" title="${esc(t.name)}">
                  <span class="mono" style="flex:none;min-width:32px;font-size:11px;font-weight:700;color:var(--text-faint)">${t.code}</span>
                  <span style="min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(t.short)}</span>
                  <span class="dot on"></span>
                </button>` : `
                <button class="anchor-item${state.mode === "overview" ? " active" : ""}" id="tpl-ov" title="全部模板">
                  <span class="mono" style="flex:none;min-width:32px;font-size:11px;font-weight:700;color:var(--text-faint)">全部</span>
                  <span style="min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">模板总览</span>
                  <span class="dot on"></span>
                </button>`)).join("")}
            </div>`).join("")}
        </div>
        <div class="subnav-foot">
          <div style="font-size:12px;line-height:18px;font-weight:600;color:var(--text-faint)">
            主题跟随控制台（顶栏切换实时同步）；<br>模板为桌面优先设计，默认按 1440 宽渲染。</div>
        </div>
      </aside>
      <main id="tpl-main"></main>
    </div>`;

  root.querySelector("#tpl-ov").onclick = () => {
    state.mode = "overview"; state.id = null; setHash(null); draw(root);
  };
  root.querySelectorAll("[data-tpl-id]").forEach((b) =>
    b.onclick = () => {
      state.mode = "preview"; state.id = b.dataset.tplId; setHash(state.id); draw(root);
    });

  themeObs?.disconnect();
  if (state.mode === "preview") watchTheme();
  drawMain(root);
}

function drawMain(root) {
  const main = root.querySelector("#tpl-main");
  main.innerHTML = state.mode === "overview" ? overviewHtml() : previewHtml(byId(state.id));
  if (state.mode === "overview") {
    main.querySelectorAll("[data-open]").forEach((c) =>
      c.onclick = () => {
        state.mode = "preview"; state.id = c.dataset.open; setHash(state.id); draw(root);
      });
    return;
  }
  wirePreview(root, byId(state.id));
}

/* ---------- 总览（卡片网格：点击任一卡片 = 预览） ---------- */
function overviewHtml() {
  return `
    <div class="card" style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
      <span class="logo-block dark">${ICON_TPL}</span>
      <div style="min-width:0">
        <div style="font-size:15px;font-weight:800;letter-spacing:-.01em">模板库 · 共 ${TEMPLATES.length} 个</div>
        <div style="margin-top:4px;font-size:12px;font-weight:600;color:var(--text-faint);line-height:18px">
          点击任一模板卡片即可在右侧内嵌运行；主题跟随控制台顶栏切换实时同步。模板均为独立静态页，源文件位于 model_gateway/web/static/templates/。</div>
      </div>
    </div>
    <div class="card-grid">
      ${TEMPLATES.map((t) => `
        <div class="card" data-open="${t.id}" style="cursor:pointer" title="点击预览 ${esc(t.name)}">
          <div style="display:flex;align-items:center;gap:8px">
            <span class="logo-block dark">${ICON_TPL}</span>
            <span class="badge ${FAMILY_CLS[t.family]}">${t.family}</span>
            <span class="badge b-muted">${esc(t.skeleton)}</span>
          </div>
          <div style="margin-top:10px;font-size:15px;font-weight:800;letter-spacing:-.01em">${esc(t.name)}</div>
          <div class="clamp-2" style="margin-top:6px;font-size:13px;line-height:20px;font-weight:500;color:var(--text-tertiary)">${esc(t.desc)}</div>
          <div style="margin-top:10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
            <span class="badge b-pill b-cool">${esc(t.tags[0])}</span>
            <span class="mono" style="font-size:12px;color:var(--text-faint)">${t.file}</span>
          </div>
        </div>`).join("")}
    </div>`;
}

/* ---------- 预览（头卡 + 宽度切换 + iframe 内嵌运行） ---------- */
function previewHtml(t) {
  return `
    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:12px">
        <div style="display:flex;min-width:0;align-items:center;gap:12px">
          <span class="logo-block dark" style="font-size:12px">${esc(t.code)}</span>
          <div style="min-width:0">
            <div style="display:flex;min-width:0;align-items:center;gap:8px;flex-wrap:wrap">
              <span style="font-size:15px;font-weight:800;letter-spacing:-.02em">${esc(t.name)}</span>
              <span class="badge ${FAMILY_CLS[t.family]}">${t.family}</span>
              <span class="badge b-muted">${esc(t.skeleton)}</span>
              ${t.tags.map((x) => `<span class="badge b-pill b-cool">${esc(x)}</span>`).join("")}
            </div>
            <div style="margin-top:4px;font-size:12px;font-weight:600;color:var(--text-faint);line-height:18px">${esc(t.desc)}</div>
          </div>
        </div>
        <div style="display:flex;flex:none;align-items:center;gap:8px">
          <button class="btn" id="tpl-refresh">刷新</button>
          <button class="btn" id="tpl-copy">${ICON_COPY}复制路径</button>
          <button class="btn btn-primary" id="tpl-open">${ICON_OPEN}新标签打开</button>
        </div>
      </div>
      <div style="display:flex;align-items:center;gap:12px;margin-top:12px">
        <span id="tpl-widths" style="flex:none"></span>
        <span class="mono" style="font-size:12px;color:var(--text-faint);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">/templates/${t.file}</span>
      </div>
    </div>
    ${t.family === "预演" ? `
    <div class="alert alert-warn" style="margin-top:12px">
      <div class="alert-title">需求形态预演 · 非线上功能</div>
      <div>本模板为需求预演件（演示数据），用于对齐需求形态；不代表已实现的线上功能，不得据此外推。</div>
    </div>` : ""}
    <div class="card" style="margin-top:12px;padding:8px;overflow-x:auto">
      <iframe id="tpl-frame" data-tpl="${t.id}" src="${frameUrl(t)}" title="${esc(t.name)} 模板预览"
              style="border:0;border-radius:var(--radius-md);display:block;background:var(--surface);
                     width:${width ? width + "px" : "100%"};height:calc(100vh - 250px);min-height:360px"></iframe>
    </div>`;
}

function wirePreview(root, t) {
  root.querySelector("#tpl-widths").append(tabBar(
    WIDTHS, width, (id) => {
      width = id;
      applyWidth(root);
    }));
  root.querySelector("#tpl-refresh").onclick = () => {
    const f = document.getElementById("tpl-frame");
    if (f) f.src = frameUrl(t);
  };
  root.querySelector("#tpl-copy").onclick = () => copyText(`/templates/${t.file}`, "模板路径已复制");
  root.querySelector("#tpl-open").onclick = () => window.open(frameUrl(t), "_blank");
}

function applyWidth(root) {
  const f = root.querySelector("#tpl-frame");
  if (f) f.style.width = width ? `${width}px` : "100%";
}

/* 主题跟随：控制台 data-theme 一变，iframe 带新 `?theme=` 重载（模板主题契约，frontend-spec §7.15） */
function watchTheme() {
  themeObs = new MutationObserver(() => {
    const f = document.getElementById("tpl-frame");
    const t = f && byId(f.dataset.tpl);
    if (t) f.src = frameUrl(t);
  });
  themeObs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
}
