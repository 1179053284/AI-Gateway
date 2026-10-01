/** 模型资源：版式 = 模板「模型供应商」页（2026-09-05 用户定版）。
 * 左子侧栏：资源供应商纤行（服务器图标 + 名称 + 启用点，items-center，无分组标题）+ 底部「添加模型资源」。
 * 右侧撑满配置区（内部滚动）：
 *   头卡 = 供应商基本信息 + 接入形式 + Base URL（合并一卡；值块无标签；未设置时框内提示可编辑）；
 *   「Key 及关联账号」独立卡（无字段标题，placeholder 提示；开关控制该 Key 投用；空行槽位唯一）；
 *   「模型列表」卡（grid 三列 340/max-content/1fr；自定义下拉箭头贴文字；检测连通状态色 + 删除右对齐）。
 * 新增：点「添加模型资源」→ 右侧内联草稿编辑器（无弹窗），右上「确认添加」落库；未保存不出现在子侧栏。
 * 数据仍为扁平 resources[]（资源 = 供应商 + 账号 + Key，一组 Key = 一条资源）；供应商分组仅是视图，
 * 供应商级编辑（名称/映射/禁用/删除）改写该供应商全部资源。
 * 操作即保存（D3）；已存 Key 脱敏还原（值不变 = 不修改）；删除有确认弹窗。
 * 交互规范：`.anchor-item` 须 align-items:center（参考提炼遗漏致点/文字错位的教训见 pitfalls）。 */

import { GET, PUT, POST, esc } from "../api.js";
import { confirmDialog, toast, switchEl, copyText } from "../components.js";

let cfg = null;
let presets = [];
let selected = null;      // 当前选中供应商 key（"v:名称" / "p:preset" / "r:id" / "__draft__"）
let draftVendor = null;   // 新增资源供应商草稿（确认添加后落库；未保存不出现在子侧栏）
let keyDrafts = [];       // 已存供应商的待填 Key 组草稿（空行槽位唯一）
let mapDrafts = [];       // 已存供应商的待填映射行草稿（空行槽位唯一）
let phSeq = 0;            // @new-N 占位序号（保存时服务端解析为真实 res-id）
const plainById = {};     // 已取到的 Key 明文（rid → 明文，reveal 接口）
const testState = {};     // 连通性检测结果（vm→sys 键 → {ok,latency_ms|error}，供按钮着色保持）

const EYE = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/></svg>`;
const EYE_OFF = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1-1.444 2.49"/><path d="M14.084 14.158a3 3 0 0 1-4.242-4.242"/><path d="M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143"/><path d="m2 2 20 20"/></svg>`;
const TRASH = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 11v6"/><path d="M14 11v6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`;
const PEN = `<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>`;
const CPU = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20v2"/><path d="M12 2v2"/><path d="M17 20v2"/><path d="M17 2v2"/><path d="M2 12h2"/><path d="M2 17h2"/><path d="M2 7h2"/><path d="M20 12h2"/><path d="M20 17h2"/><path d="M20 7h2"/><path d="M7 20v2"/><path d="M7 2v2"/><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="8" y="8" width="8" height="8" rx="1"/></svg>`;
const PLUS = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>`;
const COPY = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>`;
const SERVER = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="8" x="2" y="2" rx="2" ry="2"/><rect width="20" height="8" x="2" y="14" rx="2" ry="2"/><line x1="6" x2="6.01" y1="6" y2="6"/><line x1="6" x2="6.01" y1="18" y2="18"/></svg>`;

export async function renderResources(root) {
  const [c, pdata] = await Promise.all([
    GET("/admin/api/config"), GET("/admin/api/presets")]);
  cfg = c;
  presets = (pdata && pdata.presets) || [];
  draw(root);
}

/** 操作即保存：PUT 全量配置 → 无论成败以服务端最新配置重渲染（自同步） */
async function persist(root, okMsg = "已保存并生效") {
  try {
    await PUT("/admin/api/config", cfg);
    if (okMsg) toast(okMsg, "ok");
  } catch (e) {
    toast("保存失败：" + e.message, "err");
  }
  await renderResources(root);
}

/* ---------- 资源供应商分组（视图层：存储仍为扁平 resources[]） ---------- */
const vkeyOf = (r) => r.vendor ? "v:" + r.vendor : r.preset ? "p:" + r.preset : "r:" + r.id;

function vendorGroups() {
  const out = [];
  const seen = new Set();
  for (const r of cfg.resources || []) {
    const k = vkeyOf(r);
    if (!seen.has(k)) { seen.add(k); out.push({ key: k, first: r }); }
  }
  return out.map(({ key, first }) => {
    const list = (cfg.resources || []).filter((r) => vkeyOf(r) === key);
    return {
      key, list,
      label: key.startsWith("v:") ? key.slice(2)
        : key.startsWith("p:") ? (presets.find((p) => p.id === first.preset)?.name || first.preset)
        : (first.name || first.id || "自定义"),
      enabled: list.some((r) => r.enabled !== false),
    };
  });
}

function maskVal(v) { return v ? v.slice(0, 5) + "****" + v.slice(-4) : ""; }

/** 供应商的映射集合（各资源并集，保持 models[] 顺序） */
function mapsOf(resList) {
  const rids = new Set(resList.map((r) => r.id));
  const out = [], seen = new Set();
  for (const m of cfg.models || []) {
    for (const e of m.resources || []) {
      if (!rids.has(e.resource)) continue;
      const k = e.model + "→" + m.name;
      if (!seen.has(k)) { seen.add(k); out.push({ vm: e.model, sys: m.name }); }
    }
  }
  return out;
}

/* 自定义系统模型下拉：箭头恒距文字 10px（原生 select 箭头钉框右缘的根治）；选中即时显示 */
const sysOptions = () => (cfg.models || []).map((x) =>
  ({ v: x.name, label: x.name + (x.enabled === false ? "（已停用）" : "") }));

function buildSysDropdown(cell, value, onChange) {
  cell.style.position = "relative";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "in";
  btn.style.cssText = "display:inline-flex;align-items:center;gap:10px;text-align:left;width:auto;height:36px";
  const txt = document.createElement("span");
  txt.textContent = value || "选择系统模型…";
  if (!value) txt.style.color = "var(--placeholder)";
  const pick = (v) => { txt.textContent = v; txt.style.color = ""; };
  const chev = document.createElement("span");
  chev.style.cssText = "display:inline-flex;color:var(--text-faint)";
  chev.innerHTML = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>`;
  btn.append(txt, chev);
  const menu = document.createElement("div");
  menu.className = "dropdown";
  menu.style.cssText = "left:0;right:auto;top:42px;width:auto;min-width:220px;max-height:300px;overflow-y:auto";
  for (const o of sysOptions()) {
    const it = document.createElement("button");
    it.type = "button";
    it.className = "dropdown-item";
    it.textContent = o.label;
    if (o.v === value) { it.style.color = "var(--text)"; it.style.fontWeight = "700"; }
    it.onclick = (e) => { e.stopPropagation(); close(); pick(o.v); onChange(o.v); };
    menu.append(it);
  }
  const close = () => {
    if (menu.parentElement) { menu.remove(); document.removeEventListener("click", close); }
  };
  btn.onclick = (e) => {
    e.stopPropagation();
    if (menu.parentElement) return close();
    cell.append(menu);
    document.addEventListener("click", close);
  };
  cell.append(btn);
}

/* 快捷复制：copyIcon(取值函数, 提示文案) → icon-btn，点击复制并 toast */
const copyIcon = (getText, title = "点击复制", cls = "rv-copy") => {
  const b = document.createElement("button");
  b.type = "button";
  b.className = `icon-btn sm ${cls}`;
  b.title = title;
  b.innerHTML = COPY;
  b.onclick = async () => {
    try {
      const v = await getText();
      if (!v) return toast("内容为空，无可复制", "err");
      copyText(v, "已复制");
    } catch (e) { toast(e.message || "复制失败", "err"); }
  };
  return b;
};

/* ---------- 页面骨架：左子侧栏 + 右撑满配置区（内部滚动，无底部空白） ---------- */
function draw(root) {
  const groups = vendorGroups();
  if (selected !== "__draft__" && !groups.some((g) => g.key === selected))
    selected = groups[0]?.key || null;
  root.innerHTML = `
    <style>
      /* 本页接管内容区左右/底部留白（顶部 12px 规范留白保留），配置区内部滚动无底部空白 */
      #rv-wrap { margin: -12px -12px -48px; height: calc(100vh - 60px); }
      @media (max-width: 1280px) { #rv-wrap { margin-bottom: -40px; } }
      @media (max-width: 768px) { #rv-wrap { margin: -12px -10px -36px; } }
    </style>
    <div id="rv-wrap" style="display:flex;align-items:stretch;min-height:0">
      <aside class="subnav" style="height:100%">
        <div class="subnav-scroll">
          ${groups.map((g) => `
          <button class="anchor-item" data-vk="${esc(g.key)}" style="display:flex;width:100%;
            ${g.key === selected ? "background:var(--side-hover);color:var(--text);" : ""}"
            title="${esc(g.label)} · ${g.list.length} 组 Key">
            <span class="mark-sm">${SERVER}</span>
            <span style="min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(g.label)}</span>
            <span class="dot ${g.enabled ? "on" : ""}"></span>
          </button>`).join("")}
        </div>
        <div class="subnav-foot">
          <button class="side-add" id="rv-add">
            ${PLUS.replace('width="14" height="14"', 'width="16" height="16"')}添加模型资源
          </button>
        </div>
      </aside>
      <main style="flex:1;min-width:0;overflow-y:auto;padding:12px">
        <div id="rv-detail"></div>
      </main>
    </div>`;

  root.querySelectorAll("[data-vk]").forEach((b) =>
    b.onclick = () => {
      selected = b.dataset.vk;
      if (selected !== "__draft__") { draftVendor = null; keyDrafts = []; mapDrafts = []; }
      draw(root);
    });
  root.querySelector("#rv-add").onclick = () => {
    draftVendor = { name: "", access_mode: "api", base_url: "",
      keys: [{ key: "", account: "" }], maps: [] };
    selected = "__draft__";
    keyDrafts = []; mapDrafts = [];
    draw(root);
  };
  drawDetail(root);
}

/* ---------- 右侧配置区 ---------- */
function drawDetail(root) {
  const box = root.querySelector("#rv-detail");
  if (selected === "__draft__" && draftVendor) return drawDraftEditor(root);
  const g = vendorGroups().find((x) => x.key === selected);
  if (!g) {
    box.innerHTML = `<div class="empty" style="margin-top:80px">暂无模型资源<br>点击左侧「＋ 添加模型资源」接入第一个资源供应商</div>`;
    return;
  }
  const resList = g.list;
  const maps = mapsOf(resList);
  const first = resList[0];

  box.innerHTML = `
    <!-- 供应商基本信息 + 接入形式 + Base URL（合并一卡；值块无标签；未设置时框内提示可编辑） -->
    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:12px">
        <div style="display:flex;min-width:0;align-items:center;gap:12px">
          <span class="logo-block dark">${esc((g.label[0] || "资").toUpperCase())}</span>
          <div style="min-width:0;height:40px;display:flex;flex-direction:column;justify-content:space-between">
            <div style="display:flex;min-width:0;align-items:center;gap:6px;height:20px">
              <button class="edit-name" id="rv-name" title="点击编辑供应商名称"
                style="line-height:20px;height:20px">${esc(g.label)}</button>
              <button class="icon-btn sm" id="rv-name-edit" aria-label="编辑供应商名称"
                style="width:20px;height:20px">${PEN}</button>
            </div>
            <div style="font-size:12px;line-height:18px;font-weight:600;color:var(--text-faint)">
              Key 及关联账号 · ${resList.length} 组 Key · ${maps.length} 个模型映射</div>
          </div>
        </div>
        <div style="display:flex;flex:none;align-items:center;gap:8px">
          <button class="btn" id="rv-toggle">${g.enabled ? "禁用" : "启用"}</button>
          <button class="icon-btn lg danger" id="rv-del" aria-label="删除供应商"
            title="删除该供应商及其全部 Key 与模型映射">${TRASH}</button>
        </div>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
        ${first.base_url ? `
        <span class="addr-value">${first.access_mode === "plan" ? "Plan（订阅 / 积分制）" : "API（按量计费）"}</span>
        <span class="addr-value" style="display:inline-flex;align-items:center;gap:8px">${esc(first.base_url)}
          <button class="icon-btn sm rv-copyurl" title="复制 Base URL" style="width:20px;height:20px">${COPY}</button>
        </span>
        ` : `
        <select id="rv-mode" class="in" style="width:240px">
          <option value="" disabled selected>选择接入形式（API 按量 / Plan 订阅）</option>
          <option value="api">API（按量计费）</option>
          <option value="plan">Plan（订阅 / 积分制）</option>
        </select>
        <input class="in mono" id="rv-url" style="flex:1;min-width:240px" placeholder="Base URL（https://…）">
        `}
      </div>
    </div>

    <!-- Key 及关联账号（独立板块；一组 Key + 账号 = 一条资源） -->
    <section class="card" style="margin-top:12px">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px">
        <div style="font-size:13px;font-weight:800;color:var(--text-soft)">Key 及关联账号</div>
        <div style="font-size:12px;font-weight:500;color:var(--text-faint)">
          一组 Key + 所属账号（选填）= 一条资源，可添加多组</div>
      </div>
      <div id="rv-keys" style="display:flex;flex-direction:column"></div>
      <button class="btn btn-soft" id="rv-addkey" style="margin-top:12px">${PLUS}添加 Key</button>
    </section>

    <!-- 模型列表（grid 三列；自定义下拉箭头贴文字） -->
    <section class="card" style="margin-top:12px">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px">
        <div style="font-size:13px;font-weight:800;color:var(--text-soft)">模型列表</div>
        <div style="font-size:12px;font-weight:500;color:var(--text-faint)">
          厂商模型 ID 映射到系统统一模型（单选）</div>
      </div>
      <div id="rv-maps" style="display:grid;grid-template-columns:340px max-content 1fr;align-items:center"></div>
      <button class="btn btn-soft" id="rv-addmap" style="margin-top:12px">${PLUS}添加模型</button>
    </section>`;

  bindHead(root, g);
  if (!first.base_url) bindAccessOnce(root, g);
  const copyUrlBtn = box.querySelector(".rv-copyurl");
  if (copyUrlBtn) copyUrlBtn.onclick = () =>
    copyText(first.base_url, "Base URL 已复制");
  drawKeys(root, resList);
  drawMaps(root, resList);
}

/* ---------- 头卡：改名 / 禁用 / 删除 ---------- */
function bindHead(root, g) {
  const startRename = () => {
    const nameBtn = root.querySelector("#rv-name");
    /* 已处于改名态：首次点击已把 #rv-name 换成 input，再点（或点铅笔）会 querySelector 得到 null，
       `null.replaceWith` 抛 "Cannot read properties of null (reading 'replaceWith')"。
       此处改为把焦点交回那个输入框，幂等且不空引用。 */
    if (!nameBtn) {
      const cur = root.querySelector("input[data-rename]");
      if (cur) { cur.focus(); cur.select(); }
      return;
    }
    const input = document.createElement("input");
    input.dataset.rename = "1";
    input.value = g.label;
    Object.assign(input.style, {
      height: "20px", minWidth: "180px", maxWidth: "320px",
      border: "1px solid var(--text)", borderRadius: "10px", background: "var(--surface)",
      padding: "0 10px", outline: "none", font: "800 15px Inter,-apple-system,'PingFang SC',sans-serif",
      letterSpacing: "-.02em", color: "var(--text)",
    });
    nameBtn.replaceWith(input);
    input.focus(); input.select();
    const commit = async () => {
      const nv = input.value.trim();
      input.replaceWith(nameBtn);
      if (!nv || nv === g.label) return;
      for (const r of g.list) r.vendor = nv;
      selected = "v:" + nv;
      await persist(root, "供应商名称已更新");
    };
    input.onblur = commit;
    input.onkeydown = (e) => {
      if (e.key === "Enter") input.blur();
      if (e.key === "Escape") { input.value = g.label; input.blur(); }
    };
  };
  root.querySelector("#rv-name").onclick = startRename;
  root.querySelector("#rv-name-edit").onclick = startRename;

  root.querySelector("#rv-toggle").onclick = async () => {
    const next = !g.enabled;
    for (const r of g.list) r.enabled = next;
    await persist(root, next ? "供应商已启用" : "供应商已禁用");
  };

  root.querySelector("#rv-del").onclick = async () => {
    const maps = mapsOf(g.list);
    const sysNames = [...new Set(maps.map((x) => x.sys))];
    const msg = (sysNames.length
      ? `确定删除供应商「${g.label}」？其 ${g.list.length} 组 Key 与 ${maps.length} 处模型映射（${sysNames.join("、")}）将一并移除。`
      : `确定删除供应商「${g.label}」？其 ${g.list.length} 组 Key 将一并移除。`);
    if (!await confirmDialog("删除供应商", msg)) return;
    const rids = new Set(g.list.map((r) => r.id));
    for (const m of cfg.models || []) {
      m.resources = (m.resources || []).filter((e) => !rids.has(e.resource));
    }
    cfg.resources = cfg.resources.filter((r) => !rids.has(r.id));
    selected = null;
    await persist(root, "供应商已删除");
  };
}

/* ---------- 接入信息（仅在未设置时出现，保存后即隐藏） ---------- */
function bindAccessOnce(root, g) {
  root.querySelector("#rv-mode").onchange = async (e) => {
    for (const r of g.list) r.access_mode = e.target.value;
    await persist(root);
  };
  root.querySelector("#rv-url").onchange = async (e) => {
    const v = e.target.value.trim();
    if (!v) return toast("Base URL 必填", "err");
    for (const r of g.list) r.base_url = v;
    await persist(root, "接入配置已保存");
  };
}

/* ---------- Key 及关联账号（placeholder 提示；开关 + 删除同容器居中；空行槽位唯一） ---------- */
function drawKeys(root, resList) {
  const box = root.querySelector("#rv-keys");
  const keyInput = (cls, val, isNew) => `
    <div style="position:relative;display:flex;align-items:center">
      <input class="in mono ${cls}" ${isNew ? 'type="password"' : 'type="text"'} value="${esc(val)}"
        placeholder="Key 值（sk-…）" style="width:100%;padding-right:56px;font-weight:400">
      <button class="icon-btn sm rv-keycopy" type="button" title="复制 Key"
        style="position:absolute;right:26px">${COPY}</button>
      <button class="icon-btn sm rv-eye" type="button" title="显示 / 隐藏明文"
        style="position:absolute;right:4px">${EYE}</button>
    </div>`;

  box.innerHTML = resList.map((r, ki) => `
    <div class="list-row" data-rid="${esc(r.id)}" style="padding:12px 0;gap:12px;align-items:center;
      ${ki > 0 ? "border-top:1px solid var(--border);" : ""}
      ${r.enabled === false ? "opacity:.55" : ""}">
      <div style="flex:1;display:grid;grid-template-columns:1.2fr 1fr;gap:10px;min-width:0">
        ${keyInput("rv-key", r.api_key, false)}
        <input class="in rv-acc" value="${esc(r.account || "")}"
          placeholder="所属账号（选填）" style="width:100%">
      </div>
      <div style="flex:none;display:flex;gap:4px;align-items:center">
        <span data-swkey="${esc(r.id)}" style="display:inline-flex;align-items:center"></span>
        <button class="icon-btn sm danger rv-delkey" title="删除该组 Key（连同其模型映射）">${TRASH}</button>
      </div>
    </div>`).join("") + keyDrafts.map((d, i) => `
    <div class="list-row" data-dki="${i}" style="padding:12px 0;gap:12px;align-items:center;
      ${resList.length || i > 0 ? "border-top:1px solid var(--border);" : ""}">
      <div style="flex:1;display:grid;grid-template-columns:1.2fr 1fr;gap:10px;min-width:0">
        ${keyInput("rv-dkey", d.key, true)}
        <input class="in rv-dacc" value="${esc(d.account)}"
          placeholder="所属账号（选填）" style="width:100%">
      </div>
      <div style="flex:none;display:flex;gap:4px;align-items:center">
        <button class="icon-btn sm danger rv-deldraft" title="丢弃该组">${TRASH}</button>
      </div>
    </div>`).join("");

  for (const row of box.querySelectorAll("[data-rid]")) {
    const rid = row.dataset.rid;
    const r = resList.find((x) => x.id === rid);
    const input = row.querySelector(".rv-key");
    const acc = row.querySelector(".rv-acc");
    const eye = row.querySelector(".rv-eye");

    input.onchange = async () => {
      if (input.value === r.api_key) return;
      if (!input.value.trim()) { input.value = r.api_key; return toast("Key 值不能为空", "err"); }
      r.api_key = input.value.trim();
      delete plainById[rid];
      await persist(root, "Key 已更新");
    };
    acc.onchange = async () => {
      if (acc.value.trim() === (r.account || "")) return;
      r.account = acc.value.trim();
      await persist(root);
    };
    eye.onclick = async () => {
      if (eye.dataset.on === "1") {           // 明文 → 收回脱敏
        if (input.value === plainById[rid]) input.value = r.api_key;
        eye.dataset.on = ""; eye.innerHTML = EYE;
        return;
      }
      if (plainById[rid] == null) {
        try {
          const full = await GET("/admin/api/config?reveal=1");
          const fr = (full.resources || []).find((x) => x.id === rid);
          plainById[rid] = fr ? fr.api_key : r.api_key;
        } catch (e) { return toast(e.message, "err"); }
      }
      input.value = plainById[rid];
      eye.dataset.on = "1"; eye.innerHTML = EYE_OFF;
    };
    row.querySelector(".rv-keycopy").onclick = async () => {
      if (plainById[rid] == null) {
        try {
          const full = await GET("/admin/api/config?reveal=1");
          const fr = (full.resources || []).find((x) => x.id === rid);
          plainById[rid] = fr ? fr.api_key : r.api_key;
        } catch (e) { return toast(e.message, "err"); }
      }
      copyText(plainById[rid], "Key 已复制");
    };
    row.querySelector("[data-swkey]").append(switchEl(r.enabled !== false, async (next) => {
      r.enabled = next;
      await persist(root, next ? "该 Key 已启用" : "该 Key 已停用（退出调度）");
      return true;
    }));

    row.querySelector(".rv-delkey").onclick = async () => {
      const maps = mapsOf([r]);
      const sysNames = [...new Set(maps.map((x) => x.sys))];
      const msg = (sysNames.length
        ? `确定删除该组 Key（${r.account || "未标注账号"}）？其 ${maps.length} 处模型映射（${sysNames.join("、")}）将一并移除。`
        : `确定删除该组 Key（${r.account || "未标注账号"}）？`);
      if (!await confirmDialog("删除 Key", msg)) return;
      for (const m of cfg.models || []) {
        m.resources = (m.resources || []).filter((e) => e.resource !== rid);
      }
      cfg.resources = cfg.resources.filter((x) => x.id !== rid);
      delete plainById[rid];
      await persist(root, "Key 已删除");
    };
  }

  for (const row of box.querySelectorAll("[data-dki]")) {
    const i = +row.dataset.dki;
    const input = row.querySelector(".rv-dkey");
    const acc = row.querySelector(".rv-dacc");
    const eye = row.querySelector(".rv-eye");
    eye.onclick = () => {
      input.type = input.type === "password" ? "text" : "password";
      eye.innerHTML = input.type === "password" ? EYE : EYE_OFF;
    };
    input.onchange = () => {
      const v = input.value.trim();
      if (!v) return toast("Key 值必填（填写后自动保存）", "err");
      keyDrafts[i].key = v;
      promoteKeyDraft(root, resList, i);
    };
    acc.onchange = () => { keyDrafts[i].account = acc.value.trim(); };
    row.querySelector(".rv-keycopy").onclick = () => {
      const v = input.value.trim();
      if (v && !v.includes("****")) copyText(v, "Key 已复制");
      else toast("该行 Key 未填写", "err");
    };
    row.querySelector(".rv-deldraft").onclick = () => { keyDrafts.splice(i, 1); drawDetail(root); };
  }

  root.querySelector("#rv-addkey").onclick = () => {
    const empty = keyDrafts.findIndex((k) => !k.key.trim() && !k.account.trim());
    if (empty >= 0) {  // 空行槽位唯一：已有空行只聚焦，杜绝空行堆积
      drawDetail(root);
      root.querySelectorAll(".rv-dkey")[empty]?.focus();
      return;
    }
    keyDrafts.push({ key: "", account: "" });
    drawDetail(root);
    root.querySelectorAll(".rv-dkey")[keyDrafts.length - 1]?.focus();
  };
}

/** Key 草稿填写完成 → 落为一条新资源（供应商字段继承本组） */
async function promoteKeyDraft(root, resList, i) {
  const d = keyDrafts[i];
  const first = resList[0];
  cfg.resources.push({
    id: `@new-${++phSeq}`,
    vendor: first.vendor || "", preset: first.preset || "",
    product: first.product || "",   // 同组新增 Key 继承产品归属（漏传会被后端默认成空）
    name: "", account: d.account || "",
    access_mode: first.access_mode, protocol: first.protocol || "openai",
    base_url: first.base_url, api_key: d.key, enabled: true,
  });
  keyDrafts.splice(i, 1);
  await persist(root, "已添加 1 组 Key");
}

/* ---------- 模型列表（grid 三列；自定义下拉；检测连通状态色；图标右对齐） ---------- */
function drawMaps(root, resList) {
  const box = root.querySelector("#rv-maps");
  const maps = mapsOf(resList);
  const rows = [...maps.map((m) => ({ kind: "saved", m })), ...mapDrafts.map((d) => ({ kind: "draft", d }))];
  const BT = (i) => (i > 0 ? "border-top:1px solid var(--border);" : "");

  // 表头三格必须是 grid 直接子元素（包 div 会整体占首列挤错位）
  let html = `
    <span style="padding:0 0 6px;font-size:11.5px;font-weight:600;color:var(--text-faint)">供应商模型ID</span>
    <span style="padding:0 0 6px;font-size:11.5px;font-weight:600;color:var(--text-faint)">系统映射模型ID</span>
    <span style="justify-self:end;width:60px;text-align:left;padding-bottom:6px;
      font-size:11.5px;font-weight:600;color:var(--text-faint)">操作</span>`;
  rows.forEach((row, i) => {
    const bt = BT(i);
    if (row.kind === "saved") {
      html += `
      <div style="${bt}display:flex;align-items:center;position:relative;min-width:0;height:46px">
        <input class="in mono rv-vm" data-vm="${i}" value="${esc(row.m.vm)}"
          placeholder="供应商模型 ID" style="width:100%;padding:0 30px 0 0;border:none;background:transparent;
          box-shadow:none;border-radius:0">
        <button class="icon-btn sm rv-vmcopy" data-vmcopy="${i}" title="复制模型 ID"
          style="position:absolute;right:6px">${COPY}</button>
      </div>
      <div data-syscell="${i}" style="${bt}display:flex;align-items:center;position:relative;
        align-self:stretch;height:46px"></div>
      <div style="${bt}height:46px;display:flex;align-items:center;justify-content:end;gap:4px;
        align-self:stretch">
        <button class="icon-btn sm rv-test" data-test="${i}" title="检测连通性">${CPU}</button>
        <button class="icon-btn sm danger rv-delmap" data-delmap="${i}" title="删除该映射">${TRASH}</button>
      </div>`;
    } else {
      html += `
      <div data-dmi="${i - maps.length}" style="${bt}display:flex;align-items:center;position:relative;
        min-width:0;height:46px">
        <input class="in mono rv-dvm" value="${esc(row.d.vm)}"
          placeholder="供应商模型 ID" style="width:100%;padding:0 30px 0 0;border:none;background:transparent;
          box-shadow:none;border-radius:0">
        <button class="icon-btn sm rv-dvmcopy" data-dvmcopy="${i - maps.length}" title="复制模型 ID"
          style="position:absolute;right:6px">${COPY}</button>
      </div>
      <div data-sysdraft="${i - maps.length}" style="${bt}display:flex;align-items:center;position:relative;
        align-self:stretch;height:46px"></div>
      <div data-dmi="${i - maps.length}" style="${bt}height:46px;display:flex;align-items:center;justify-content:end;gap:4px;
        align-self:stretch">
        <button class="icon-btn sm rv-testdraft" data-testdraft="${i - maps.length}" title="检测连通性">${CPU}</button>
        <button class="icon-btn sm danger rv-deldraftmap" title="丢弃该行">${TRASH}</button>
      </div>`;
    }
  });
  root.querySelector("#rv-addmap").onclick = () => {
    const empty = mapDrafts.findIndex((m) => !m.vm.trim() && !m.sys);
    if (empty >= 0) {  // 空行槽位唯一
      drawDetail(root);
      root.querySelectorAll(".rv-dvm")[empty]?.focus();
      return;
    }
    mapDrafts.push({ vm: "", sys: "" });
    drawDetail(root);
    root.querySelectorAll(".rv-dvm")[mapDrafts.length - 1]?.focus();
  };
  if (!rows.length) {
    box.innerHTML = `<p class="form-hint" style="grid-column:1/-1;padding:2px 0">暂无映射——点「添加模型」将厂商模型映射到系统统一模型</p>`;
    return;
  }
  box.innerHTML = html;

  const applyTestState = (btn, key) => {
    const st = testState[key];
    if (!st) return;
    if (st.st === "ok") {
      btn.style.color = "var(--ok)";
      btn.title = `连通正常 · ${st.ok}/${st.total} · 最快 ${st.minLat}ms`;
    } else if (st.st === "partial") {
      btn.style.color = "var(--warn)";
      btn.title = `部分连通 · ${st.ok}/${st.total}，不通过：${st.fails.join("；")}`;
    } else {
      btn.style.color = "var(--err)";
      btn.title = `全部 Key 不生效（0/${st.total}）`;
    }
  };

  for (const btn of box.querySelectorAll(".rv-vmcopy")) {
    const i = +btn.dataset.vmcopy;
    btn.onclick = () => {
      const v = maps[i].vm.trim();
      if (v) copyText(v, "模型 ID 已复制");
      else toast("该行模型 ID 为空", "err");
    };
  }
  for (const input of box.querySelectorAll(".rv-vm")) {
    const i = +input.dataset.vm;
    input.onchange = async () => {
      const nv = input.value.trim();
      const old = maps[i].vm;
      if (!nv || nv === old) { input.value = old; return; }
      for (const r of resList) {
        for (const m of cfg.models || []) {
          for (const e of m.resources || []) {
            if (e.resource === r.id && e.model === old) e.model = nv;
          }
        }
      }
      // 同资源去重（重名映射合并，保留首条）
      for (const r of resList) {
        const seenPair = new Set();
        for (const m of cfg.models || []) {
          m.resources = (m.resources || []).filter((e) => {
            if (e.resource !== r.id) return true;
            const k = e.model + "\u0000" + m.name;
            if (seenPair.has(k)) return false;
            seenPair.add(k);
            return true;
          });
        }
      }
      await persist(root, "映射已更新");
    };
  }
  box.querySelectorAll("[data-syscell]").forEach((cell) => {
    const i = +cell.dataset.syscell;
    buildSysDropdown(cell, maps[i].sys, async (nv) => {
      const rowm = maps[i];
      const tmOld = cfg.models.find((x) => x.name === rowm.sys);
      const tmNew = cfg.models.find((x) => x.name === nv);
      if (!tmNew) return;
      for (const r of resList) {
        const idx = tmOld?.resources.findIndex((e) => e.resource === r.id && e.model === rowm.vm);
        if (idx != null && idx >= 0) {
          const [e] = tmOld.resources.splice(idx, 1);
          if (!tmNew.resources.some((x) => x.resource === r.id && x.model === rowm.vm))
            tmNew.resources.push(e);
        }
      }
      await persist(root, "映射已更新");
    });
  });
  const applyTest = async (btn, rowm) => {
    const key = rowm.vm + "\u0000" + rowm.sys;
    const targets = resList.filter((r) => r.enabled !== false);
    if (!targets.length) return toast("该供应商全部 Key 处于停用状态，无法检测", "err");
    btn.disabled = true; btn.style.opacity = ".45";
    btn.style.color = ""; btn.title = "检测中…";
    let ok = 0, minLat = Infinity;
    const fails = [];
    for (let idx = 0; idx < targets.length; idx++) {
      const r = targets[idx];
      const tag = `第${idx + 1} 组 Key${r.account ? `（${r.account}）` : ""}`;
      try {
        const res = await POST("/admin/api/resources/test",
          { resource: r.id, model: rowm.vm });
        if (res.ok) { ok++; minLat = Math.min(minLat, res.latency_ms); }
        else fails.push(`${tag}：${res.error || "失败"}`);
      } catch (e) { fails.push(`${tag}：${e.message}`); }
    }
    btn.disabled = false; btn.style.opacity = "";
    if (!fails.length) {
      testState[key] = { st: "ok", ok, total: targets.length, minLat };
      btn.style.color = "var(--ok)";
      btn.title = `连通正常 · ${ok}/${targets.length} · 最快 ${minLat}ms`;
      toast(`连通正常 · ${ok}/${targets.length} · 最快 ${minLat}ms`, "ok");
    } else if (ok > 0) {
      testState[key] = { st: "partial", ok, total: targets.length, minLat, fails };
      btn.style.color = "var(--warn)";
      btn.title = `部分连通 · ${ok}/${targets.length}`;
      toast(`部分 Key 不通过（${ok}/${targets.length}）：${fails.join("；")}`, "err");
    } else {
      testState[key] = { st: "fail", ok: 0, total: targets.length, fails };
      btn.style.color = "var(--err)";
      btn.title = `全部 Key 不生效（0/${targets.length}）`;
      toast(`全部 Key 不生效（0/${targets.length}）：${fails.join("；")}`, "err");
    }
  };
  for (const btn of box.querySelectorAll(".rv-test")) {
    const i = +btn.dataset.test;
    applyTestState(btn, maps[i]);
    btn.onclick = () => applyTest(btn, maps[i]);
  }
  for (const btn of box.querySelectorAll(".rv-delmap")) {
    const i = +btn.dataset.delmap;
    btn.onclick = async () => {
      const row = maps[i];
      const rids = new Set(resList.map((r) => r.id));
      for (const m of cfg.models || []) {
        m.resources = (m.resources || []).filter((e) =>
          !(rids.has(e.resource) && e.model === row.vm && m.name === row.sys));
      }
      await persist(root, "映射已删除");
    };
  }
  box.querySelectorAll("[data-sysdraft]").forEach((cell) => {
    const i = +cell.dataset.sysdraft;
    buildSysDropdown(cell, mapDrafts[i].sys, async (nv) => {
      mapDrafts[i].sys = nv;
      await promoteMapDraft(root, resList, i);
    });
  });
  for (const btn of box.querySelectorAll(".rv-dvmcopy")) {
    const i = +btn.dataset.dvmcopy;
    btn.onclick = () => {
      const v = (mapDrafts[i]?.vm || "").trim();
      // data-dvmcopy 即草稿索引
      if (v) copyText(v, "模型 ID 已复制");
      else toast("该行模型 ID 为空", "err");
    };
  }
  for (const input of box.querySelectorAll(".rv-dvm")) {
    const i = +input.closest("[data-dmi]").dataset.dmi;
    input.onchange = () => {
      mapDrafts[i].vm = input.value.trim();
      promoteMapDraft(root, resList, i);
    };
  }
  for (const btn of box.querySelectorAll(".rv-testdraft")) {
    const i = +btn.dataset.testdraft;
    btn.onclick = async () => {
      const rowm = mapDrafts[i];
      if (!rowm.vm.trim()) return toast("请先填写供应商模型 ID 再检测", "err");
      if (!resList[0]?.base_url) return toast("请先完成该供应商的 Base URL 配置", "err");
      await applyTest(btn, rowm);
    };
  }
  for (const btn of box.querySelectorAll(".rv-deldraftmap")) {
    const i = +btn.closest("[data-dmi]").dataset.dmi;
    btn.onclick = () => { mapDrafts.splice(i, 1); drawDetail(root); };
  }
}

/** 映射草稿双字段齐全 → 落为该供应商全部资源的映射 */
async function promoteMapDraft(root, resList, i) {
  const d = mapDrafts[i];
  if (!d.vm || !d.sys) return;   // 未填齐不提交
  for (const r of resList) {
    const tm = cfg.models.find((x) => x.name === d.sys);
    if (!tm) { mapDrafts[i] = d; return toast("系统模型不存在", "err"); }
    if (!tm.resources.some((e) => e.resource === r.id && e.model === d.vm))
      tm.resources.push({ resource: r.id, model: d.vm, reasoning: null });
  }
  mapDrafts.splice(i, 1);
  await persist(root, "映射已添加");
}

/* ---------- 新增资源供应商：右侧内联草稿编辑器（确认添加后落库） ---------- */
function drawDraftEditor(root) {
  const d = draftVendor;
  const box = root.querySelector("#rv-detail");
  box.innerHTML = `
    <!-- 供应商基本信息 + 接入形式 + Base URL（草稿态：名称为输入框，右上「确认添加」） -->
    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:12px">
        <div style="display:flex;min-width:0;align-items:center;gap:12px">
          <span class="logo-block dark" id="rv-dlogo">新</span>
          <div style="min-width:0;height:40px;display:flex;flex-direction:column;justify-content:space-between">
            <input id="rv-dname" value="${esc(d.name)}" placeholder="供应商名称"
              title="供应商名称" style="min-width:0;max-width:320px;height:20px;border:none;
              outline:none;background:transparent;font:800 15px Inter,-apple-system,'PingFang SC',sans-serif;
              letter-spacing:-.02em;color:var(--text)">
            <div style="font-size:12px;line-height:18px;font-weight:600;color:var(--text-faint)">
              确认添加后生成资源配置</div>
          </div>
        </div>
        <div style="display:flex;flex:none;align-items:center;gap:8px">
          <button class="btn btn-primary" id="rv-confirm">确认添加</button>
        </div>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
        <select id="rv-mode" class="in" style="width:240px">
          <option value="api" ${d.access_mode === "api" ? "selected" : ""}>API（按量计费）</option>
          <option value="plan" ${d.access_mode === "plan" ? "selected" : ""}>Plan（订阅 / 积分制）</option>
        </select>
        <input class="in mono" id="rv-url" style="flex:1;min-width:240px" value="${esc(d.base_url)}"
          placeholder="Base URL（https://…）">
      </div>
    </div>

    <!-- Key 及关联账号（草稿） -->
    <section class="card" style="margin-top:12px">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px">
        <div style="font-size:13px;font-weight:800;color:var(--text-soft)">Key 及关联账号</div>
        <div style="font-size:12px;font-weight:500;color:var(--text-faint)">
          一组 Key + 所属账号（选填）= 一条资源，可添加多组</div>
      </div>
      <div id="rv-keys" style="display:flex;flex-direction:column"></div>
      <button class="btn btn-soft" id="rv-addkey" style="margin-top:12px">${PLUS}添加 Key</button>
    </section>

    <!-- 模型列表（草稿） -->
    <section class="card" style="margin-top:12px">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px">
        <div style="font-size:13px;font-weight:800;color:var(--text-soft)">模型列表</div>
        <div style="font-size:12px;font-weight:500;color:var(--text-faint)">
          厂商模型 ID 映射到系统统一模型（单选）</div>
      </div>
      <div id="rv-maps" style="display:grid;grid-template-columns:340px max-content 1fr;align-items:center"></div>
      <button class="btn btn-soft" id="rv-addmap" style="margin-top:12px">${PLUS}添加模型</button>
    </section>`;

  // 供应商名称：草稿状态 + 预设联想快填（输入完整预设名自动带出 Base URL / 接入形式，无下拉框）
  const nameInput = box.querySelector("#rv-dname");
  const logo = box.querySelector("#rv-dlogo");
  let presetId = "";
  nameInput.oninput = () => {
    d.name = nameInput.value;
    logo.textContent = (d.name[0] || "新").toUpperCase();
    const p = presets.find((x) => x.name === d.name.trim());
    if (p && p.id !== "custom") {
      presetId = p.id;
      const url = box.querySelector("#rv-url");
      const known = new Set(presets.map((x) => x.base_url).filter(Boolean));
      if (!url.value.trim() || known.has(url.value.trim())) url.value = p.base_url || "";
      if (p.mode) { box.querySelector("#rv-mode").value = p.mode; d.access_mode = p.mode; }
    } else presetId = "";
  };

  box.querySelector("#rv-mode").onchange = (e) => { d.access_mode = e.target.value; };
  box.querySelector("#rv-url").onchange = (e) => { d.base_url = e.target.value.trim(); };

  // Key 组（草稿；空行槽位唯一）
  const drawDraftKeys = () => {
    const keysBox = box.querySelector("#rv-keys");
    keysBox.innerHTML = d.keys.map((k, i) => `
      <div class="list-row" data-dki="${i}" style="padding:12px 0;gap:12px;align-items:center;
        ${i > 0 ? "border-top:1px solid var(--border);" : ""}">
        <div style="flex:1;display:grid;grid-template-columns:1.2fr 1fr;gap:10px;min-width:0">
          <div style="position:relative;display:flex;align-items:center">
            <input class="in mono rv-gkey" type="password" value="${esc(k.key)}"
              placeholder="Key 值（sk-…）" style="width:100%;padding-right:56px;font-weight:400">
            <button class="icon-btn sm rv-keycopy" type="button" title="复制 Key"
              style="position:absolute;right:26px">${COPY}</button>
            <button class="icon-btn sm rv-geye" type="button" title="显示 / 隐藏明文"
              style="position:absolute;right:4px">${EYE}</button>
          </div>
          <input class="in rv-gacc" value="${esc(k.account)}"
            placeholder="所属账号（选填）" style="width:100%">
        </div>
        <div style="flex:none;display:flex;gap:4px;align-items:center">
          <button class="icon-btn sm danger rv-gdel" title="删除该组 Key">${TRASH}</button>
        </div>
      </div>`).join("");
    keysBox.querySelectorAll("[data-dki]").forEach((row) => {
      const i = +row.dataset.dki;
      const input = row.querySelector(".rv-gkey");
      const acc = row.querySelector(".rv-gacc");
      const eye = row.querySelector(".rv-geye");
      eye.onclick = () => {
        input.type = input.type === "password" ? "text" : "password";
        eye.innerHTML = input.type === "password" ? EYE : EYE_OFF;
      };
      input.onchange = () => { d.keys[i].key = input.value.trim(); };
      acc.onchange = () => { d.keys[i].account = acc.value.trim(); };
      row.querySelector(".rv-keycopy").onclick = () => {
        const v = input.value.trim();
        if (v) copyText(v, "Key 已复制");
        else toast("该行 Key 未填写", "err");
      };
      row.querySelector(".rv-gdel").onclick = () => { d.keys.splice(i, 1); drawDraftKeys(); };
    });
  };
  drawDraftKeys();
  box.querySelector("#rv-addkey").onclick = () => {
    const empty = d.keys.findIndex((k) => !k.key.trim() && !k.account.trim());
    if (empty >= 0) {  // 空行槽位唯一
      drawDraftKeys();
      box.querySelectorAll(".rv-gkey")[empty]?.focus();
      return;
    }
    d.keys.push({ key: "", account: "" });
    drawDraftKeys();
    box.querySelectorAll(".rv-gkey")[d.keys.length - 1]?.focus();
  };

  // 模型映射（草稿；grid 头行一体；自定义下拉）
  const drawDraftMaps = () => {
    const mapsBox = box.querySelector("#rv-maps");
    const BT = (i) => (i > 0 ? "border-top:1px solid var(--border);" : "");
    let html = `
      <span style="padding:0 0 6px;font-size:11.5px;font-weight:600;color:var(--text-faint)">供应商模型ID</span>
      <span style="padding:0 0 6px;font-size:11.5px;font-weight:600;color:var(--text-faint)">系统映射模型ID</span>
      <span style="justify-self:end;width:60px;text-align:left;padding-bottom:6px;
        font-size:11.5px;font-weight:600;color:var(--text-faint)">操作</span>`;
    d.maps.forEach((m, i) => {
      html += `
      <div style="${BT(i)}display:flex;align-items:center;position:relative;min-width:0;height:46px">
        <input class="in mono rv-mvm" data-mvm="${i}" value="${esc(m.vm)}"
          placeholder="供应商模型 ID" style="width:100%;padding:0 30px 0 0;border:none;background:transparent;
          box-shadow:none;border-radius:0">
        <button class="icon-btn sm rv-mvmcopy" data-mvmcopy="${i}" title="复制模型 ID"
          style="position:absolute;right:6px">${COPY}</button>
      </div>
      <div data-msys="${i}" style="${BT(i)}display:flex;align-items:center;position:relative;
        align-self:stretch;height:46px"></div>
      <div style="${BT(i)}height:46px;display:flex;align-items:center;justify-content:end;gap:4px;
        align-self:stretch">
        <button class="icon-btn sm rv-gtest" data-gtest="${i}" title="检测连通性">${CPU}</button>
        <button class="icon-btn sm danger rv-mdel" data-mdel="${i}" title="删除该行">${TRASH}</button>
      </div>`;
    });
    if (!d.maps.length) {
      mapsBox.innerHTML = `<p class="form-hint" style="grid-column:1/-1;padding:2px 0">暂无映射——点「添加模型」将厂商模型映射到系统统一模型</p>`;
      return;
    }
    mapsBox.innerHTML = html;
    mapsBox.querySelectorAll(".rv-mvmcopy").forEach((btn) => {
      const i = +btn.dataset.mvmcopy;
      btn.onclick = () => {
        const v = (d.maps[i]?.vm || "").trim();
        if (v) copyText(v, "模型 ID 已复制");
        else toast("该行模型 ID 为空", "err");
      };
    });
    mapsBox.querySelectorAll("[data-mvm]").forEach((input) => {
      const i = +input.dataset.mvm;
      input.onchange = () => { d.maps[i].vm = input.value.trim(); };
    });
    mapsBox.querySelectorAll("[data-msys]").forEach((cell) => {
      const i = +cell.dataset.msys;
      buildSysDropdown(cell, d.maps[i].sys, (nv) => { d.maps[i].sys = nv; });
    });
    const applyDraftTest = async (btn, m) => {
      if (!d.base_url.trim()) return toast("请先填写 Base URL", "err");
      const targets = d.keys.filter((k) => k.key.trim());
      if (!targets.length) return toast("请先填写 Key 值", "err");
      btn.disabled = true; btn.style.opacity = ".45";
      btn.style.color = ""; btn.title = "检测中…";
      let ok = 0, minLat = Infinity;
      const fails = [];
      for (let idx = 0; idx < targets.length; idx++) {
        const k = targets[idx];
        const tag = `第${d.keys.indexOf(k) + 1} 组 Key${k.account ? `（${k.account}）` : ""}`;
        try {
          const res = await POST("/admin/api/resources/test",
            { base_url: d.base_url.trim(), api_key: k.key.trim(), model: m.vm });
          if (res.ok) { ok++; minLat = Math.min(minLat, res.latency_ms); }
          else fails.push(`${tag}：${res.error || "失败"}`);
        } catch (e) { fails.push(`${tag}：${e.message}`); }
      }
      btn.disabled = false; btn.style.opacity = "";
      const key = m.vm + "\u0000" + m.sys;
      if (!fails.length) {
        testState[key] = { st: "ok", ok, total: targets.length, minLat };
        btn.style.color = "var(--ok)";
        btn.title = `连通正常 · ${ok}/${targets.length} · 最快 ${minLat}ms`;
        toast(`连通正常 · ${ok}/${targets.length} · 最快 ${minLat}ms`, "ok");
      } else if (ok > 0) {
        testState[key] = { st: "partial", ok, total: targets.length, minLat, fails };
        btn.style.color = "var(--warn)";
        btn.title = `部分连通 · ${ok}/${targets.length}`;
        toast(`部分 Key 不通过（${ok}/${targets.length}）：${fails.join("；")}`, "err");
      } else {
        testState[key] = { st: "fail", ok: 0, total: targets.length, fails };
        btn.style.color = "var(--err)";
        btn.title = `全部 Key 不生效（0/${targets.length}）`;
        toast(`全部 Key 不生效（0/${targets.length}）：${fails.join("；")}`, "err");
      }
    };
    mapsBox.querySelectorAll(".rv-gtest").forEach((btn) => {
      const i = +btn.dataset.gtest;
      btn.onclick = () => applyDraftTest(btn, d.maps[i]);
    });
    mapsBox.querySelectorAll(".rv-mdel").forEach((btn) => {
      const i = +btn.dataset.mdel;
      btn.onclick = () => { d.maps.splice(i, 1); drawDraftMaps(); };
    });
  };
  drawDraftMaps();
  box.querySelector("#rv-addmap").onclick = () => {
    const empty = d.maps.findIndex((m) => !m.vm.trim() && !m.sys);
    if (empty >= 0) {  // 空行槽位唯一
      drawDraftMaps();
      box.querySelectorAll(".rv-mvm")[empty]?.focus();
      return;
    }
    d.maps.push({ vm: "", sys: "" });
    drawDraftMaps();
    box.querySelectorAll(".rv-mvm")[d.maps.length - 1]?.focus();
  };

  // 确认添加：校验 → 落库（多组 Key 拆条 + 映射复制）
  box.querySelector("#rv-confirm").onclick = async () => {
    if (!d.name.trim()) return toast("供应商名称必填", "err");
    if (!d.base_url.trim()) return toast("Base URL 必填", "err");
    const keys = d.keys.filter((k) => k.key.trim());
    if (!keys.length) return toast("至少填写一组 Key", "err");
    const seenKey = new Set();
    for (const k of keys) {
      if (seenKey.has(k.key.trim())) return toast("存在重复 Key：各组 Key 须不同", "err");
      seenKey.add(k.key.trim());
    }
    const maps = d.maps.filter((m) => m.vm.trim() || m.sys);
    for (const m of maps) {
      if (!m.vm.trim() || !m.sys)
        return toast("映射行需同时填写供应商模型 ID 并选择系统模型", "err");
    }
    const seenMap = new Set();
    for (const m of maps) {
      const k = m.vm.trim() + "\u0000" + m.sys;
      if (seenMap.has(k)) return toast(`重复映射：${m.vm.trim()} → ${m.sys}`, "err");
      seenMap.add(k);
    }

    const rids = [];
    for (const k of keys) {
      const rid = `@new-${++phSeq}`;
      cfg.resources.push({
        id: rid, vendor: d.name.trim(), preset: presetId, name: "",
        account: k.account.trim(), access_mode: d.access_mode || "api",
        protocol: "openai", base_url: d.base_url.trim(), api_key: k.key.trim(), enabled: true,
      });
      rids.push(rid);
    }
    for (const rid of rids) {
      for (const m of maps) {
        const tm = cfg.models.find((x) => x.name === m.sys);
        if (!tm) continue;
        if (!tm.resources.some((e) => e.resource === rid && e.model === m.vm))
          tm.resources.push({ resource: rid, model: m.vm, reasoning: null });
      }
    }
    draftVendor = null;
    selected = "v:" + d.name.trim();
    await persist(root, `已创建 ${rids.length} 条资源并生效`);
  };
}
