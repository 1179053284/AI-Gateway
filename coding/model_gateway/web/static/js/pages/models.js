/** 资源池设置（原「系统模型」，Q24 · 2026-09-05 定版）——
 * 左子侧栏 = 按「厂商归属」分组卡片（内置模型目录 GET /admin/api/enums 的 vendor 字段，
 * 与「接入模型资源」页接入商解耦：如 deepseek-v4-* 经商汤接入，仍归 DeepSeek 卡）；
 * 卡内行 = 该厂商已接入的系统模型 + 启用状态点（绿点 = 对外可调用生效中）；
 * 厂商名行右侧「＋」icon（icon-btn sm）= 从该厂商内置目录弹窗选型新建（官方默认参数自动带入，覆盖 Q19-②）。
 * 右侧 = 头卡（启停语义 = 网关统一对外模型能否被调用）+ 模型属性（目录只读）+
 * 资源池 + 参数配置（工具传参 > 网关设置 > 厂商内置；仅 chat 注入）。
 * 端点/分组为系统模型级数据字段（创建时由目录带入），页面不提供编辑区（2026-09-05 用户定版去掉「基本属性」板块）。
 * 交互 = 操作即保存（D3）：变更确认后直接 PUT 并以服务端最新配置重渲染。 */

import { GET, PUT, esc, isDerivedResource } from "../api.js";
import { confirmDialog, modal, toast, initSplitResize } from "../components.js";

let cfg = null;
let presets = [];
let catalog = {};         // name → 内置目录条目（enums API）
let vendorOrder = [];     // 厂商名按目录出现顺序
let selected = null;      // 当前选中系统模型名

const SHOW_DELETE = false; // Q24-④：删除按钮暂时隐藏（恢复 = 改 true；后端能力保留）
const TRASH = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 11v6"/><path d="M14 11v6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`;
const EP_TEXT = { chat: "chat 对话（流式 + 非流式）", images: "images 图像生成" };

export async function renderModels(root) {
  const [c, pdata, edata] = await Promise.all([
    GET("/admin/api/config"), GET("/admin/api/presets"), GET("/admin/api/enums")]);
  cfg = c;
  presets = (pdata && pdata.presets) || [];
  catalog = {};
  vendorOrder = [];
  for (const e of (edata && edata.entries) || []) {
    catalog[e.name] = e;
    if (e.vendor && !vendorOrder.includes(e.vendor)) vendorOrder.push(e.vendor);
  }
  if (!selected || !cfg.models.some((m) => m.name === selected))
    selected = cfg.models[0]?.name || null;
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
  await renderModels(root);
}

/* ---------- 厂商归属分组（目录 vendor 字段；无目录条目 → 自定义） ---------- */
const off = (m) => m.enabled === false;
const vendorOf = (m) => catalog[m.name]?.vendor || "";

function vendorCards() {
  const byVendor = new Map(vendorOrder.map((v) => [v, []]));
  const custom = [];
  for (const m of cfg.models || [])
    (vendorOf(m) ? byVendor.get(vendorOf(m)) || custom : custom).push(m);
  const cards = vendorOrder.map((v) => ({
    vendor: v, models: byVendor.get(v),
    catCount: Object.values(catalog).filter((e) => e.vendor === v).length,
  }));
  return { cards, custom };
}

function cardHTML(c) {
  const anyOn = c.models.some((m) => !off(m));
  const rows = c.models.map((m) => `
    <button class="mode-btn ${m.name === selected ? "active" : ""}" data-sel="${esc(m.name)}"
      title="${esc(m.name)}${off(m) ? "（已禁用）" : ""}">
      <span style="min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:left;${off(m) ? "opacity:.5" : ""}">${esc(m.name)}</span>
      <span class="dot ${off(m) ? "" : "on"}"></span>
    </button>`).join("");
  return `
    <div class="group-card" style="margin-bottom:12px">
      <div style="display:flex;height:28px;align-items:center;gap:8px;padding:0 4px;margin-bottom:6px"
        title="${esc(c.vendor)} · 目录 ${c.catCount} 个模型 / 已接入 ${c.models.length}">
        <span class="mark-sm ${anyOn ? "dark" : ""}">${esc(c.vendor[0])}</span>
        <span style="min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;font-weight:800;color:var(--text-soft)">${esc(c.vendor)}</span>
        <button class="icon-btn sm" data-add="${esc(c.vendor)}" title="添加模型" aria-label="添加模型"
          style="margin-right:-4px"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg></button>
      </div>
      ${rows || `<p class="form-hint" style="padding:2px 0">未接入模型</p>`}
    </div>`;
}

/* ---------- 页面骨架：左子侧栏厂商卡 + 右撑满配置区（骨架类 .panel-split，v2.19 改类） ---------- */
function draw(root) {
  const { cards, custom } = vendorCards();
  root.innerHTML = `
    <style>
      /* 参数配置两列栅格：单元格不继承 .list-row 兄弟分割线（网格中左右线错位），
         行距对齐 12px 节奏；窄屏回退单列 */
      #md-params .list-row + .list-row { border-top: 0; }
      @media (max-width: 1080px) { #md-params { grid-template-columns: minmax(0,1fr) !important; } }
    </style>
    <div class="panel-split">
      <aside class="subnav">
        <div class="subnav-scroll">
          ${cards.map(cardHTML).join("") ||
            `<p class="form-hint" style="padding:2px 0">内置目录为空</p>`}
          ${custom.length ? `
            <div class="nav-group-title" style="padding:0;margin:16px 0 8px">自定义</div>
            <div class="group-card">
              <div style="display:flex;height:28px;align-items:center;gap:8px;padding:0 4px;margin-bottom:6px">
                <span class="mark-sm">?</span>
                <span style="min-width:0;flex:1;font-size:13px;font-weight:800;color:var(--text-soft)">自定义模型</span>
              </div>
              ${custom.map((m) => `
                <button class="mode-btn ${m.name === selected ? "active" : ""}" data-sel="${esc(m.name)}"
                  title="${esc(m.name)}（不在内置目录，无属性/官方参数参考）">
                  <span style="min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:left;${off(m) ? "opacity:.5" : ""}">${esc(m.name)}</span>
                  <span class="dot ${off(m) ? "" : "on"}"></span>
                </button>`).join("")}
            </div>` : ""}
        </div>
      </aside>
      <main>
        <div id="md-detail"></div>
      </main>
    </div>`;

  root.querySelectorAll("[data-sel]").forEach((b) =>
    b.onclick = () => { selected = b.dataset.sel; draw(root); });
  root.querySelectorAll("[data-add]").forEach((b) =>
    b.onclick = () => addModelModal(root, b.dataset.add));
  initSplitResize(root, "models");
  drawDetail(root);
}

/* ---------- 添加模型：列出该厂商目录中未接入的模型（Q24，覆盖 Q19-②） ---------- */
function addModelModal(root, vendor) {
  const entries = Object.values(catalog).filter((e) =>
    e.vendor === vendor && !cfg.models.some((m) => m.name === e.name));
  const body = document.createElement("div");
  if (entries.length) {
    body.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:6px">
        ${entries.map((e, i) => `
          <label data-i="${i}" style="display:flex;align-items:center;min-height:44px;padding:8px 10px;gap:10px;cursor:pointer;border:1px solid var(--border);border-radius:8px">
            <input type="radio" name="am-pick" value="${esc(e.name)}" style="flex:none">
            <span style="flex:1;min-width:0">
              <b class="mono">${esc(e.name)}</b>
              <span style="display:block;font-size:12px;color:var(--text-faint);margin-top:2px">
                ${esc(e.display || e.name)} · ${esc(EP_TEXT[e.endpoint] || e.endpoint)}
                · 上下文 ${fmtTok(e.context_window)} · 输出 ${fmtTok(e.max_output)}
                ${e.reasoning ? ` · 深度推理${e.effort_levels.length ? `（${esc(e.effort_levels.join("/"))}）` : ""}` : ""}
              </span>
            </span>
            <span class="badge ${e.endpoint === "images" ? "b-muted" : "b-brand"}">${esc(e.group || "未分组")}</span>
          </label>`).join("")}
      </div>
      <p class="form-hint" style="margin-top:10px">创建后自动带入官方默认参数；需到「接入模型资源」页为该模型配置资源映射后方可调用。</p>`;
  } else {
    body.innerHTML = `<p class="form-hint">该厂商目录模型已全部接入。</p>`;
  }

  const foot = document.createElement("div");
  foot.innerHTML = `
    <button class="btn">取消</button>
    <button class="btn btn-primary" ${entries.length ? "" : "disabled"}>添加</button>`;
  /* 必须在 modal() **之前**取按钮引用：modal() 会把 footer 的子节点搬进 .modal-foot
     （components.js:32 `while (footer.firstChild) footEl.append(...)`），调用后再查 foot 只会得到空集，
     解构出 undefined → "Cannot set properties of undefined (setting 'onclick')"。
     参照 components.js confirmDialog 的正确写法。 */
  const [cancelBtn, okBtn] = foot.querySelectorAll("button");
  const dlg = modal({ title: `添加模型 · ${vendor}`, body, footer: foot });
  const mark = () => body.querySelectorAll("[data-i]").forEach((row) => {
    row.style.borderColor = row.querySelector("input").checked ? "var(--text)" : "var(--border)";
  });
  body.querySelectorAll("input[name=am-pick]").forEach((r) => r.onchange = mark);
  cancelBtn.onclick = dlg.close;
  okBtn.onclick = async () => {
    const pick = body.querySelector("input[name=am-pick]:checked");
    if (!pick) return;
    const e = catalog[pick.value];
    cfg.models.push({
      name: e.name, group: e.group || "未分组", endpoint: e.endpoint || "chat",
      enabled: true, params: { ...(e.params_default || {}) }, resources: [],
    });
    selected = e.name;
    dlg.close();
    await persist(root, `已添加 ${e.name}（官方默认参数已带入）`);
    toast("请到「接入模型资源」页为该模型配置资源映射", "");
  };
}

/* ---------- 模型属性（内置目录只读；官方取证口径见证据文档） ---------- */
const fmtTok = (n) => n == null ? "—" :
  n >= 1048576 && n % 1048576 === 0 ? `${n / 1048576}M` :
  n % 1024 === 0 ? `${n / 1024}K` : String(n);
const yn = (v, tip) => `<span class="badge ${v ? "b-ok" : "b-muted"}" ${tip ? `title="${esc(tip)}"` : ""}>${v ? "✓" : "—"}</span>`;

function attrRows(e) {
  const reasoning = e.reasoning
    ? `支持${e.effort_levels.length ? ` · 档位 ${esc(e.effort_levels.join(" / "))}` : "（官方未公布档位）"}`
    : "—";
  const reasoningTip = e.reasoning && !e.effort_levels.length
    ? "该厂商官方文档与模型元数据均未公布推理档位枚举（仅提供思考模式开关）；资源池行内 effort 提供通用 low/high/max 供选用"
    : "";
  return `
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px 12px">
      <div class="form-row" style="margin-bottom:0"><label>网关端点</label><div>${esc(EP_TEXT[e.endpoint] || e.endpoint)}</div></div>
      <div class="form-row" style="margin-bottom:0"><label>最大上下文</label><div class="mono">${fmtTok(e.context_window)}</div></div>
      <div class="form-row" style="margin-bottom:0"><label>最大输出</label><div class="mono">${fmtTok(e.max_output)}</div></div>
      <div class="form-row" style="margin-bottom:0"><label>图片识别</label><div>${yn(e.image_input, e.image_input ? "支持图片输入（识别/理解）" : "")}</div></div>
      <div class="form-row" style="margin-bottom:0"><label>视频识别</label><div>${yn(e.video_input, e.video_input ? "支持视频输入" : "")}</div></div>
      <div class="form-row" style="margin-bottom:0"><label>音频识别</label><div>${yn(e.audio_input, e.audio_input ? "支持音频输入" : "")}</div></div>
      <div class="form-row" style="margin-bottom:0"><label>深度推理</label><div title="${esc(reasoningTip)}">${esc(reasoning)}</div></div>
      ${e.only_base64_image ? `<div class="form-row" style="margin-bottom:0"><label>图片传入限制</label><div>仅支持 Base64（Data URL）</div></div>` : ""}
      ${e.endpoint === "images" && e.response_format_url_hours ? `<div class="form-row" style="margin-bottom:0"><label>图像 URL 有效期</label><div>${e.response_format_url_hours} 小时</div></div>` : ""}
    </div>`;
}

/* ---------- 参数配置行：网关值（可编辑）+ 官方默认 + 一键带入 ---------- */
const PARAM_LABEL = {
  temperature: "温度 temperature", top_p: "核采样 top_p", top_k: "top_k",
  min_p: "min_p", max_tokens: "最大输出 max_tokens",
  presence_penalty: "存在惩罚 presence_penalty", frequency_penalty: "频率惩罚 frequency_penalty",
  repetition_penalty: "重复惩罚 repetition_penalty", stop: "停止词 stop",
  do_sample: "采样开关 do_sample",
};
const paramVal = (v) => typeof v === "boolean" ? String(v) : String(v);

function paramRow(m, e, key) {
  return `
    <div class="list-row" style="padding:0;height:40px;gap:10px;min-width:0">
      <span style="flex:none;width:170px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;font-weight:600;color:var(--text-soft)"
        title="${esc(key)}">${esc(PARAM_LABEL[key] || key)}</span>
      <input class="in mono" data-pkey="${esc(key)}" value="${m.params?.[key] != null ? esc(paramVal(m.params[key])) : ""}"
        placeholder="空 = 不注入（走厂商内置）" style="flex:1;min-width:60px">
      <button class="icon-btn sm" data-pdel="${esc(key)}" aria-label="移除参数"
        title="${key in (e?.params_default || {}) ? "清空网关值（不再注入，走厂商内置；可用「恢复官方配置」一键还原）" : "删除该自定义参数"}"
        style="flex:none">
        <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
      </button>
    </div>`;
}

function drawDetail(root) {
  const box = root.querySelector("#md-detail");
  const m = cfg.models.find((x) => x.name === selected);
  if (!m) {
    box.innerHTML = `<div class="empty" style="margin-top:80px">暂无模型<br>点击左侧厂商卡右上角「＋」从内置目录接入，或到「接入模型资源」页通过映射创建</div>`;
    return;
  }
  const disabled = m.enabled === false;
  const e = catalog[m.name] || null;
  const isChat = m.endpoint !== "images";
  const pkeys = [...new Set([
    ...Object.keys(e?.params_default || {}), ...Object.keys(m.params || {})])];

  box.innerHTML = `
    <!-- 头卡：模型名 + 端点/状态徽章 + 启停（删除按钮 Q24-④ 暂隐藏） -->
    <div class="card" style="display:flex;align-items:center;justify-content:space-between;gap:12px">
      <div style="display:flex;min-width:0;align-items:center;gap:12px">
        <span class="logo-block dark">${esc((m.name[0] || "模").toUpperCase())}</span>
        <div style="min-width:0">
          <div style="display:flex;min-width:0;align-items:center;gap:8px">
            <span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:15px;font-weight:800;letter-spacing:-.02em;color:var(--text);${disabled ? "opacity:.45" : ""}">${esc(m.name)}</span>
            <span class="badge b-brand" style="flex:none">${esc(m.endpoint)}</span>
            <span class="badge ${disabled ? "b-muted" : "b-ok"}" style="flex:none">${disabled ? "已禁用" : "启用"}</span>
          </div>
          <div style="margin-top:4px;font-size:12px;font-weight:600;color:var(--text-faint)">
            ${esc(EP_TEXT[m.endpoint] || m.endpoint)} · ${esc(m.group || "未分组")} · ${(m.resources || []).filter((e) => !poolOff(e)).length} 个资源（顺序 = 优先级）</div>
        </div>
      </div>
      <div style="display:flex;flex:none;align-items:center;gap:8px">
        <button class="btn" id="md-toggle">${disabled ? "启用" : "禁用"}</button>
        ${SHOW_DELETE ? `<button class="icon-btn lg danger" id="md-del" aria-label="删除模型"
          title="删除该系统模型（工具端调用将立即 404）">${TRASH}</button>` : ""}
      </div>
    </div>

    ${disabled ? `<p class="form-hint" style="margin-top:12px">该模型已禁用：网关统一对外的这个模型不可被调用——/v1/models 不再返回，三端点调用（含别名）一律 404 + model_disabled，保存后热重载即时生效。</p>` : ""}
    <div style="${disabled ? "opacity:.55;pointer-events:none" : ""}">
      <!-- 模型属性：内置目录只读（官方取证；自定义模型无此卡） -->
      <section class="card" style="margin-top:12px">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px">
          <div style="font-size:13px;font-weight:800;color:var(--text-soft)">模型属性</div>
          <div style="font-size:12px;font-weight:500;color:var(--text-faint)">来源：内置模型目录（官网取证）· 只读</div>
        </div>
        ${e ? attrRows(e) : `<p class="form-hint" style="padding:2px 0">自定义模型：不在内置目录，暂无官方属性参考。</p>`}
      </section>

      <!-- 资源池：有序映射（顺序 = 优先级） -->
      <section class="card" style="margin-top:12px">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px">
          <div style="font-size:13px;font-weight:800;color:var(--text-soft)">资源池</div>
          <div style="font-size:12px;font-weight:500;color:var(--text-faint)">顺序 = 优先级：生效集 top-x 承接、失败切换按序补位</div>
        </div>
        <div id="md-pool" style="display:flex;flex-direction:column">${poolRows(m)}</div>
        <p class="form-hint" style="margin-top:12px">新增 / 调整映射：供应商侧在「接入模型资源」页编辑对应资源，账号侧在「接入账号资源」页用「模型映射」（产品 × 模型）${isChat ? "；行内 effort 为该资源推理默认（请求级指定优先，空 = 不注入）" : ""}。</p>
      </section>

      <!-- 参数配置：工具传参 > 网关设置 > 厂商内置（Q24，仅 chat 注入） -->
      ${isChat ? `
      <section class="card" style="margin-top:12px">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px">
          <div style="font-size:13px;font-weight:800;color:var(--text-soft)">参数配置</div>
          <div style="display:flex;align-items:center;gap:12px">
            <span style="font-size:12px;font-weight:500;color:var(--text-faint)">优先级：工具调用传参 &gt; 此处网关设置 &gt; 模型厂商官方内置</span>
            <button class="btn btn-sm" id="md-preset" ${e && Object.keys(e.params_default || {}).length ? "" : "disabled"}
              title="一键将该模型全部参数重置为官方默认（当前值与自定义参数将被覆盖）">恢复官方配置</button>
          </div>
        </div>
        <div id="md-params" style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px 28px">
          ${pkeys.map((k) => paramRow(m, e, k)).join("") ||
            `<p class="form-hint" style="padding:2px 0">该模型暂无官方参数参考，也未设置网关参数——可在下方手动添加。</p>`}
        </div>
        <div style="display:flex;gap:8px;margin-top:12px;align-items:center">
          <input class="in mono" id="md-pnew" placeholder="添加参数名（如 top_k）" style="width:220px">
          <button class="btn" id="md-padd">添加参数</button>
        </div>
        <p class="form-hint" style="margin-top:12px">行内值即网关注入值（初始化 = 官方默认）；清空 = 不注入（走厂商内置默认）；同一参数请求已携带时以请求为准。行尾 ×：清空该参数（自定义参数 = 删除该行），「恢复官方配置」可一键还原全部默认。推理开关与档位属推理参数体系，在资源池行内按资源配置。仅 chat 端点注入；images 不注入。</p>
      </section>` : ""}
    </div>`;

  bindDetail(root, m, e);
}

/* ---------- 推理 effort 下拉：官方档位枚举优先，无档位文档的模型用跨厂商通用三档 ---------- */
const EFFORT_LABEL = { low: "low · 轻量", medium: "medium · 中档", high: "high · 增强", max: "max · 深度" };

/** 池的「配置单元」= 界面上的一行。两类两种维度（2026-10-02 用户裁决收敛）：
 *  - **供应商侧**：一条映射 = 一行（模型供应商 + Key 维度，维持既有形式）；
 *  - **账号侧**：同一 `(产品, 上游模型)` 的多条派生映射**聚成一行**（产品 × 模型维度）——
 *    账号页「模型映射」的落点是"每个已启用账号的物化资源"
 *    （`api/admin_accounts.py:1355-1358`），所以 CodeBuddy 两个账号 × 同一模型
 *    在数组里是两条、在界面上是一行「N 个账号」。
 * 🔴 只与**相邻**同组条目合并：`m.resources[]` 的下标就是调度优先级，
 *    被别的条目隔开说明这一组在两处各有一个优先级位，合成一行就是在撒谎（也会让"上移"跨位移动）。 */
/** 这条映射**当下进不进池**：只读后端派生的 `mapping_enabled`（= `AppConfig.mapping_enabled`，
 *  厂商侧看条目位、账号侧看产品位 + 号开关）。🔴 判据不在前端再写一份——写一份就是两套真相
 *  （映射弹窗那颗开关说进池、这张表说不进池）。字段缺失（旧 payload / 别的出口）才回落条目位。 */
const poolOff = (e) => (typeof e.mapping_enabled === "boolean"
  ? e.mapping_enabled === false : e.enabled === false);

function poolUnits(m) {
  const byId = new Map((cfg.resources || []).map((x) => [x.id, x]));
  const units = [];
  (m.resources || []).forEach((r, i) => {
    const res = byId.get(r.resource);
    const prod = res ? String(res.product || "").trim() : "";
    // 映射级开关（账号页模型映射弹窗那一颗）关掉的条目**不进池**，也就不是本表的行；
    // 但它仍占数组里的一个优先级位 —— 单元下标必须按全量算，交换才不会跨过它搬别人。
    const off = poolOff(r);
    if (!isDerivedResource(res)) { units.push({ kind: "provider", key: "p:" + i, idxs: [i], res, model: r.model, off }); return; }
    const key = "a:" + prod + ":" + r.model;
    const last = units[units.length - 1];
    if (last && last.key === key && last.off === off) { last.idxs.push(i); return; }
    units.push({ kind: "account", key, idxs: [i], res, model: r.model,
                 prod, title: res.vendor || prod, off });
  });
  return units;
}

function poolRows(m) {
  const all = m.resources || [];
  const units = poolUnits(m);
  const live = units.map((u, k) => ({ u, k })).filter(({ u }) => !u.off);
  const prevLive = new Map(), nextLive = new Map();
  live.forEach(({ k }, n) => {
    if (n > 0) prevLive.set(k, live[n - 1].k);
    if (n < live.length - 1) nextLive.set(k, live[n + 1].k);
  });
  return live.map(({ u, k }, n) => {
    const r = all[u.idxs[0]];
    const isAcc = u.kind === "account";
    const label = isAcc ? u.title : ((u.res && (u.res.name || u.res.id)) || r.resource);
    const badge = isAcc ? `账号供给 ${u.idxs.length}`
      : (u.res ? (u.res.vendor || (u.res.preset
          ? (presets.find((p) => p.id === u.res.preset)?.name || u.res.preset) : "自定义")) : "未知");
    const badgeTitle = isAcc
      ? `产品 ${u.prod} 的账号体系供给：该产品的 ${u.idxs.length} 个已启用账号各一条映射`
        + "（增删/停用账号请到「接入账号资源」页的「模型映射」）"
      : "";
    // 档位取组内首条；组内不一致时如实标出来（不静默按第一条显示）
    const efforts = new Set(u.idxs.map((i) => all[i].reasoning?.effort || ""));
    const curEffort = efforts.size === 1 ? [...efforts][0] : "";
    const mixed = efforts.size > 1;
    const levels = (e2levels(m) || ["low", "high", "max"]).slice();
    if (curEffort && !levels.includes(curEffort)) levels.push(curEffort);
    for (const e of efforts) if (e && !levels.includes(e)) levels.push(e);
    const effTitle = (e2levels(m)
      ? "该模型官方推理档位（资源级默认；请求级指定优先；空 = 不注入）"
      : "该模型官方未公布档位枚举——low/high/max 为跨厂商通用值（资源级默认；空 = 不注入）")
      + (isAcc ? "；改一次作用于该组全部账号" : "")
      + (mixed ? "；⚠ 组内当前档位不一致，改动会统一成所选值" : "");
    const idxs = u.idxs.join(",");
    const up = prevLive.get(k), down = nextLive.get(k);
    return `
      <div class="list-row" style="padding:0;height:46px;gap:10px;${n ? "border-top:1px solid var(--border);" : ""}">
        <span style="width:20px;text-align:right;color:var(--text-faint);font-variant-numeric:tabular-nums;flex:none">${n + 1}.</span>
        <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
          <span class="mono" style="font-weight:700">${esc(label)}</span>
          <span class="badge ${isAcc ? "b-gray" : "b-brand"}"${badgeTitle ? ` title="${esc(badgeTitle)}"` : ""}>${esc(badge)}</span>
          <b class="mono">/ ${esc(r.model)}</b>
          ${mixed ? `<span class="badge b-warn" title="组内档位不一致：${esc([...efforts].join(" / "))}">档位不一</span>` : ""}
        </span>
        ${m.endpoint === "chat" ? `
        <select class="in mono" data-effort="${idxs}" title="${esc(effTitle)}" style="width:150px;flex:none">
          <option value="" ${curEffort ? "" : "selected"}>${mixed ? "组内不一致（改以统一）" : "不注入（厂商默认）"}</option>
          ${levels.map((lv) => `<option value="${esc(lv)}" ${lv === curEffort ? "selected" : ""}>${esc(EFFORT_LABEL[lv] || lv)}</option>`).join("")}
        </select>` : ""}
        <span style="display:flex;gap:4px;flex:none;margin-right:12px">
          <button class="btn btn-sm" data-up="${k}" data-with="${up === undefined ? "" : up}" ${up === undefined ? "disabled" : ""} title="上移（提高优先级）">↑</button>
          <button class="btn btn-sm" data-down="${k}" data-with="${down === undefined ? "" : down}" ${down === undefined ? "disabled" : ""} title="下移（降低优先级）">↓</button>
          <button class="icon-btn sm danger" data-rmres="${idxs}" title="${isAcc ? `移除该组 ${u.idxs.length} 个账号的映射` : "移除该映射"}">${TRASH}</button>
        </span>
      </div>`;
  }).join("") || `<p class="form-hint" style="padding:2px 0">无资源（调用将无可用资源 503）——供应商侧到「接入模型资源」页添加映射，账号侧到「接入账号资源」页做「模型映射」</p>`;
}

/** 当前模型目录的官方推理档位（无 = null，用通用三档兜底） */
function e2levels(m) {
  const lv = catalog[m.name]?.effort_levels;
  return lv && lv.length ? lv : null;
}

/** 参数输入值 → 配置值：数字/布尔自动转型，空串 = 移除该键 */
function coerceParam(raw) {
  const s = raw.trim();
  if (s === "") return null;
  if (s === "true") return true;
  if (s === "false") return false;
  if (/^-?\d+(\.\d+)?$/.test(s)) return Number(s);
  return s;
}

function bindDetail(root, m, e) {
  root.querySelector("#md-toggle").onclick = async () => {
    m.enabled = m.enabled === false;
    await persist(root, m.enabled ? "模型已启用" : "模型已禁用（对外不可调用）");
  };
  if (SHOW_DELETE) root.querySelector("#md-del").onclick = async () => {
    if (!await confirmDialog("删除系统模型",
      `确定删除「${m.name}」？工具端调用将立即 404；资源与其 Key 不受影响（仅移除映射条目）。`)) return;
    cfg.models = cfg.models.filter((x) => x.name !== m.name);
    selected = cfg.models[0]?.name || null;
    await persist(root, "模型已删除");
  };
  root.querySelectorAll("[data-effort]").forEach((input) =>
    input.addEventListener("change", async () => {
      const idxs = input.dataset.effort.split(",").map(Number);   // 账号侧一行 = 一组，改一次全组生效
      const effort = input.value.trim();
      if (idxs.every((i) => (m.resources[i]?.reasoning?.effort || "") === effort)) return;
      for (const i of idxs) m.resources[i].reasoning = effort ? { enabled: true, effort } : null;
      await persist(root, idxs.length > 1 ? `推理默认已更新（该组 ${idxs.length} 个账号）` : "推理默认已更新");
    }));
  /* 优先级 = 数组顺序，而一行可能代表**一组**条目 ⇒ 移动必须按"块"整组搬：
   * 两个单元在它们共同占据的那段下标里换位置，组内相对顺序不动、组外条目一个字节都不受影响。
   * （旧实现按相邻下标交换，遇到组/隐藏条目会把用户的"上移"变成"什么都没发生"或静默改到别人头上。） */
  const swapUnits = async (a, b) => {
    const u = poolUnits(m);
    const ua = u[a], ub = u[b];
    if (!ua || !ub || ua.off || ub.off) return;
    const arr = m.resources.slice();
    const span = [...ua.idxs, ...ub.idxs].sort((x, y) => x - y);
    const moved = [...ub.idxs, ...ua.idxs].map((i) => arr[i]);
    span.forEach((pos, k) => { arr[pos] = moved[k]; });
    m.resources = arr;
    await persist(root, "优先级已更新");
  };
  root.querySelectorAll("[data-up]").forEach((btn) =>
    btn.onclick = () => { const w = +btn.dataset.with; if (w >= 0) swapUnits(+btn.dataset.up, w); });
  root.querySelectorAll("[data-down]").forEach((btn) =>
    btn.onclick = () => { const w = +btn.dataset.with; if (w >= 0) swapUnits(+btn.dataset.down, w); });
  root.querySelectorAll("[data-rmres]").forEach((b) =>
    b.onclick = async () => {
      const idxs = b.dataset.rmres.split(",").map(Number);
      const what = idxs.length > 1 ? `该组 ${idxs.length} 个账号的映射条目` : "该映射条目";
      if (!await confirmDialog("移除映射",
        `确定从「${m.name}」资源池移除${what}？仅断开映射，不删除资源。`)) return;
      m.resources = m.resources.filter((_, i) => !idxs.includes(i));
      await persist(root, idxs.length > 1 ? `映射已移除（${idxs.length} 条）` : "映射已移除");
    });

  /* 参数配置（Q24）：编辑 / 官方默认带入 / 新增键 */
  root.querySelectorAll("[data-pkey]").forEach((input) =>
    input.addEventListener("change", async () => {
      const key = input.dataset.pkey;
      const v = coerceParam(input.value);
      if (v === null) {
        if (!(key in (m.params || {}))) return;
        delete m.params[key];
        await persist(root, `已移除 ${key}（恢复厂商内置默认）`);
      } else {
        if ((m.params || {})[key] === v) return;
        m.params = { ...(m.params || {}), [key]: v };
        await persist(root, `${key} 已更新（请求携带时以请求为准）`);
      }
    }));
  /* 恢复官方配置：全部参数一键重置为目录官方默认（覆盖当前值与自定义参数） */
  const preset = root.querySelector("#md-preset");
  if (preset) preset.onclick = async () => {
    const def = e?.params_default || {};
    if (!Object.keys(def).length) { toast("该模型无官方默认参数", "err"); return; }
    if (!await confirmDialog("恢复官方配置",
      `将「${m.name}」的全部参数重置为官方默认（${Object.keys(def).length} 项）？当前值与自定义参数将被覆盖。`, false)) return;
    m.params = { ...def };
    await persist(root, "已恢复官方默认参数");
  };
  /* × 移除：官方参数 = 清空网关值（行保留，可一键恢复）；自定义参数 / 未保存行 = 删除该行 */
  root.querySelectorAll("[data-pdel]").forEach((b) =>
    b.onclick = async () => {
      const key = b.dataset.pdel;
      const official = key in (e?.params_default || {});
      if (!(key in (m.params || {}))) {
        b.closest(".list-row")?.remove();
        return;
      }
      delete m.params[key];
      await persist(root, official ? `${key} 已清空（不再注入，走厂商内置）` : `已删除参数 ${key}`);
    });
  const pnew = root.querySelector("#md-pnew");
  if (pnew) root.querySelector("#md-padd").onclick = () => {
    const key = pnew.value.trim();
    if (!key) return;
    if (key in (m.params || {}) || root.querySelector(`[data-pkey="${CSS.escape(key)}"]`)) {
      toast("该参数已存在", "err"); return;
    }
    /* 空值不落配置：先插本地行，用户填值 change 后才保存 */
    const tmp = document.createElement("div");
    tmp.innerHTML = paramRow(m, e, key);
    const rowEl = tmp.firstElementChild;
    root.querySelector("#md-params").appendChild(rowEl);
    const input = rowEl.querySelector("[data-pkey]");
    input.addEventListener("change", async () => {
      const v = coerceParam(input.value);
      if (v === null) return; /* 空值 = 尚未设置，不写配置 */
      m.params = { ...(m.params || {}), [key]: v };
      await persist(root, `${key} 已更新（请求携带时以请求为准）`);
    });
    pnew.value = "";
    input.focus();
  };
}
