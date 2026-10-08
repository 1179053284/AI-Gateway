/** 资源池设置（旧页名「系统模型」，Q24 · 2026-09-05 定版后更名——
 * 左子侧栏 = 按「厂商归属」分组卡片（内置模型目录 GET /admin/api/enums 的 vendor 字段，
 * 与「接入模型资源」页供应商解耦：如 deepseek-v4-* 经商汤接入，仍归 DeepSeek 卡）；
 * 卡内行 = 该厂商已接入的网关模型 + 启用状态点（绿点 = 对外可调用生效中）；
 * 厂商名行右侧「＋」icon（icon-btn sm）= 从该厂商内置目录弹窗选型新建（官方默认参数自动带入，覆盖 Q19-②）。
 * 右侧 = 头卡（启停语义 = 网关统一对外模型能否被调用）+ 模型属性（目录只读）+
 * 资源池 + 参数配置（工具传参 > 网关设置 > 供应商通道默认；仅 chat 注入）。
 * 端点/分组为网关模型级数据字段（创建时由目录带入），页面不提供编辑区（2026-09-05 用户定版去掉「基本属性」板块）。
 * 交互 = 操作即保存（D3）：变更确认后直接 PUT 并以服务端最新配置重渲染。 */

import { GET, PUT, esc, isDerivedResource } from "../api.js";
import { confirmDialog, modal, toast, initSplitResize } from "../components.js";

let cfg = null;
let presets = [];
let catalog = {};         // name → 内置目录条目（enums API）
let vendorOrder = [];     // 厂商名按目录出现顺序
let selected = null;      // 当前选中网关模型名

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

/** 厂商图标 = 各**厂商**（模型生产公司）的官方图标资产（2026-10-03 与账号页产品图标同一口径，来源逐条记台账）。
 *  键是内置目录 `vendor` 字段的**原文** ⇒ 目录改中文名而这里没跟上，界面会静默退回首字母，
 *  由 `tests/unit/test_v2_vendor_icons.py` 按目录实际取值集合钉住。
 *  没在册的厂商（用户自定义 / 未来新增条目）**回落首字母**：宁可朴素，不编造别人的 logo。 */
const VENDOR_ICON = {
  "商汤 SenseNova": "sensenova",
  "DeepSeek": "deepseek",
  "智谱 GLM": "glm",
  "Moonshot Kimi": "kimi",
  "Anthropic": "anthropic",
  "OpenAI": "openai",
  "腾讯混元": "hunyuan",
  "MiniMax": "minimax",
  "Google Gemini": "gemini",
};

/** 厂商官方图标的 `<img>`（不在册 ⇒ `null`）。分派表与回落同 §`VENDOR_ICON` 注释。
 *  20px 卡头（`vendorMark`）与 40px 详情头卡共用这一个产出点：同一块品牌在**同一屏**里
 *  一处是官方图标、一处是首字母，读的人不会认为这是两种设计，只会认为其中一处坏了。 */
function vendorIconTag(vendor) {
  const key = VENDOR_ICON[vendor];
  return key ? `<img src="/img/vendors/${key}.png" alt="${esc(vendor[0] || "?")}">` : null;
}

function vendorMark(vendor, dark) {
  const icon = vendorIconTag(vendor);
  return `<span class="mark-sm${icon ? "" : dark ? " dark" : ""}">${icon || esc(vendor[0] || "?")}</span>`;
}

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
        ${vendorMark(c.vendor, anyOn)}
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
         行距对齐 12px 节奏；窄屏回退单列。🔴 下段「网关自动代发的 2 个参数」同网格 ⇒ 同一课一起覆写 */
      #md-params .list-row + .list-row, #md-injected .list-row + .list-row { border-top: 0; }
      @media (max-width: 1080px) { #md-params, #md-injected { grid-template-columns: minmax(0,1fr) !important; } }
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

/* ---------- 参数配置：控件形状与依据文字都由目录的官方参数档案（`param_fields`）驱动 ---------- */
const PARAM_LABEL = {
  temperature: "温度 temperature", top_p: "核采样 top_p", top_k: "top_k",
  min_p: "min_p", max_tokens: "最大输出 max_tokens",
  presence_penalty: "存在惩罚 presence_penalty", frequency_penalty: "频率惩罚 frequency_penalty",
  repetition_penalty: "重复惩罚 repetition_penalty", stop: "停止词 stop",
  do_sample: "采样开关 do_sample", seed: "随机种子 seed", n: "生成条数 n",
};
const paramVal = (v) => (typeof v === "boolean" ? String(v)
  : Array.isArray(v) ? v.join(", ") : String(v));

/** 未取证 / 自定义模型用的通用参数名候选 —— 🔴 只是"给你个拼写参考"，不是"厂商官方支持"的声明，
 *  datalist 里逐条标开这个区别（把候选说成清单就是编证据）。 */
const COMMON_PARAM_KEYS = ["temperature", "top_p", "top_k", "min_p", "max_tokens",
  "presence_penalty", "frequency_penalty", "repetition_penalty", "seed", "stop", "do_sample", "n"];

/** 这个键在该模型上的官方档案（没在册 = null ⇒ 不猜类型、不装知道） */
function pfield(e, key) {
  return (e && e.param_fields && e.param_fields[key]) || null;
}

/** 每个参数的**特有**人话说明（2026-10-06 用户指示：说明用人话、简短易懂）。
 *  只写"不看就会误解"的那一句（官方 note 的翻译），没有就返回空串——
 *  宁可少说，不编。取证原话与 URL/日期已从行内挪到「参数配置详细说明」帮助页
 *  （/help/params.html），本函数不再是证据出口，只是结论出口。 */
function paramPlainNote(e, key) {
  const v = (e && e.vendor) || "";
  const name = (e && e.name) || "";
  if (v === "Moonshot Kimi"
    && ["temperature", "top_p", "presence_penalty", "frequency_penalty"].includes(key))
    return "厂商固定值，传其他值会报错（保持默认即可）";
  if (v === "DeepSeek") {
    if (key === "temperature") return "深度思考模式下厂商不读这个值";
    if (key === "top_p") return "深度思考模式下低于 0.95 会被按 0.95 处理";
    if (key === "max_tokens") return "厂商缺省随思考档变化（8K/64K/128K），网关因此按资源自己的上限代发";
  }
  if (v === "Anthropic" && (key === "temperature" || key === "top_p")
    && name.startsWith("claude-haiku"))
    return "temperature 与 top_p 只能二选一，同时设置会报错";
  if (v === "智谱 GLM") {
    if (key === "do_sample") return "设为 false 时温度与 top_p 一起失效";
    if (key === "max_tokens") return "官方默认 65536，131072 是上限——两个数不是一回事";
  }
  if (v === "Google Gemini" && key === "temperature" && !/^gemini-3\.[6-8]/.test(name))
    return "官方提示：低于 1.0 可能输出循环或质量下降";
  if (v === "OpenAI" && (key === "temperature" || key === "top_p"))
    return "使用推理档时厂商建议移除这个参数";
  if (v === "腾讯混元"
    && ["temperature", "top_p", "presence_penalty", "frequency_penalty", "n"].includes(key))
    return "官方只有平台级通用默认值（以具体模型能力为准），网关不代发";
  if (v === "MiniMax" && key === "max_tokens")
    return "Chat 端官方已弃用此键，新写法是 max_completion_tokens";
  if (v === "商汤 SenseNova" && key === "presence_penalty")
    return "官方按模式与任务给 4 组推荐值（1.5/0.0/1.5/2.0），这里取第一组";
  return "";
}

/** 一行的"依据"文字（常驻可见，不只住 tooltip：悬停不算看见过）。
 *  人话短句版（2026-10-06）：结论 + 后果；URL/日期/官方原话挪帮助页，不再进行内。 */
function paramBasisText(field, e, key) {
  if (!field) return "未取证：该键不在这个模型的官方参数档案里，网关照原样发出";
  const known = field.default !== undefined && field.default !== null;
  /* 「官方缺省」与「官方推荐值」是两种事实（商汤那六键官方只给了推荐值）——混着写就是把
     证据说重一档。而"网关到底注不注入"必须按**派生的真值**说：`ignored/rejected` 档即便官方
     公布了缺省也不参与派生 ⇒ 绝不许写"按它注入"（第一版就在这条上自己写了假陈述，被真机
     判据抓出：同一行同时出现"按它注入"与"官方对非默认值返回报错"）。 */
  const dLabel = field.default_source === "recommended" ? "厂商推荐值" : "厂商官方缺省";
  const willInject = known && field.availability === "supported" && field.inject !== false;
  const bits = [
    known
      ? `${dLabel} ${paramVal(field.default)}`
        + (willInject ? " · 网关按它注入" : " · 网关不注入这一项（走供应商通道默认）")
      : "厂商未公布缺省值（网关不替你猜）",
  ];
  if (field.kind === "number" || field.kind === "integer") {
    if (field.min != null || field.max != null) {
      bits.push(`官方范围 ${field.min == null ? "" : field.min}~${field.max == null ? "" : field.max}`);
    }
  }
  if (field.kind === "string_list") {
    bits.push("多个值用英文逗号分隔");
    if (field.max != null) bits.push(`官方最多 ${field.max} 条`);
  }
  if (field.kind === "enum" && (field.values || []).length) {
    bits.push(`官方枚举 ${field.values.map(paramVal).join(" / ")}`);
  }
  if (field.availability === "deprecated") bits.push("⚠ 厂商已标注废弃");
  if (field.availability === "ignored") bits.push("⚠ 厂商明确忽略该参数，设了不生效");
  if (field.availability === "rejected") bits.push("⚠ 厂商对非默认值直接返回报错");
  const plain = paramPlainNote(e, key);
  if (plain) bits.push(plain);
  return bits.join(" · ");
}

/** 值输入控件：形状跟着官方档案走（布尔给下拉、枚举给下拉、数组给逗号分隔文本） */
function paramControl(field, key, cur) {
  const name = esc(key);
  const val = cur == null ? "" : paramVal(cur);
  if (field && field.kind === "boolean") {
    const opt = (v, t) => `<option value="${v}"${String(cur) === v ? " selected" : ""}>${t}</option>`;
    return `<select class="in" data-pkey="${name}" style="flex:1;min-width:60px">`
      + `<option value=""${cur == null ? " selected" : ""}>空 = 不注入（走供应商通道默认）</option>`
      + opt("true", "true") + opt("false", "false") + `</select>`;
  }
  if (field && field.kind === "enum" && (field.values || []).length) {
    const opts = field.values.map((v) => `<option value="${esc(paramVal(v))}"${String(val) === paramVal(v) ? " selected" : ""}>${esc(paramVal(v))}</option>`);
    return `<select class="in mono" data-pkey="${name}" style="flex:1;min-width:60px">`
      + `<option value=""${cur == null ? " selected" : ""}>空 = 不注入（走供应商通道默认）</option>`
      + opts.join("") + `</select>`;
  }
  const ph = field
    ? (field.kind === "string_list" ? "多个值用英文逗号分隔"
      : (field.min != null || field.max != null) ? `${field.min ?? ""}~${field.max ?? ""}`
        : "空 = 不注入（走供应商通道默认）")
    : "空 = 不注入（走供应商通道默认）";
  return `<input class="in mono" data-pkey="${name}" value="${esc(val)}" placeholder="${esc(ph)}" style="flex:1;min-width:60px">`;
}

function paramRow(m, e, key) {
  const field = pfield(e, key);
  const official = key in (e?.params_default || {});
  /* 🔴 `max_tokens` 的"清空"不是回到供应商通道默认：这张卡没写它时，统一规格那一腿还会补
     （`core/scheduler.py::_out_body` 先 `apply_model_params` 再 `apply_spec_defaults`）。
     方向说反过一次，所以这一行按当前合并规格把实际后果写出来。 */
  const delTip = key === "max_tokens" && m?.spec?.max_output != null
    ? `清空后这一项改由统一规格注入 ${m.spec.max_output}（见下方「网关自动代发的 2 个参数」）`
    : (official
      ? "清空网关值（不再注入，走供应商通道默认；可用「恢复官方配置」一键还原）"
      : "删除该自定义参数");
  return `
    <div class="list-row" style="padding:6px 0;height:auto;min-width:0;flex-direction:column;align-items:stretch;gap:4px">
      <div style="display:flex;align-items:center;gap:10px;min-width:0">
        <span style="flex:none;width:170px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;font-weight:600;color:var(--text-soft)"
          title="${esc(key)}">${esc(PARAM_LABEL[key] || key)}</span>
        ${paramControl(field, key, m.params?.[key])}
        <button class="icon-btn sm" data-pdel="${esc(key)}" aria-label="移除参数"
          title="${esc(delTip)}" style="flex:none">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
        </button>
      </div>
      <div class="pbasis" style="font-size:11px;font-weight:500;line-height:1.35;color:var(--text-muted);padding-left:180px;overflow-wrap:anywhere">${esc(paramBasisText(field, e, key))}</div>
    </div>`;
}

/** 只读段：网关**确实会发**、但不住在这张卡上的两腿（缺了这段，空卡就在谎称"网关没设参数"） */
function injectedElsewhereHTML(m) {
  const cap = m?.spec?.max_output;
  const reasoningRows = (m.resources || []).filter((r) => r.reasoning
    && (r.reasoning.effort || r.reasoning.enabled !== undefined));
  const cell = (k, v, where) => `
    <div class="list-row" style="padding:6px 0;height:auto;min-width:0;flex-direction:column;align-items:stretch;gap:4px">
      <div style="display:flex;align-items:baseline;gap:10px;min-width:0">
        <span class="mono" style="flex:none;width:170px;font-size:13px;font-weight:600;color:var(--text-soft)">${esc(k)}</span>
        <span style="flex:1;min-width:0;font-size:12px;color:var(--text-soft);overflow-wrap:anywhere">${esc(v)}</span>
        <span class="badge b-muted" style="flex:none" title="这一项不在本卡配置">只读</span>
      </div>
      <div style="font-size:11px;font-weight:500;line-height:1.35;color:var(--text-muted);padding-left:180px;overflow-wrap:anywhere">${esc(where)}</div>
    </div>`;
  /* 人话版（2026-10-06 用户指示）：原文案「按「承接这条请求的资源自己」的最大输出注入…」
     用户读不懂。两条都说「会发什么 + 为什么要管它 + 去哪改」。 */
  return cell("max_tokens",
    cap == null
      ? "规格里没有输出上限这个数 ⇒ 网关不代发（用厂商自己的默认值）"
      : `你没填输出上限时，网关按实际接单账号自己的上限代发（此模型承诺上限 ${cap}；单个账号更小就按该账号的）`,
    "影响：输出到上限即停。想自己定 → 在上方表格写 max_tokens（写了一网关就不代发）")
    + cell("thinking / reasoning_effort",
      reasoningRows.length
        ? `资源池里 ${reasoningRows.length} 行设了推理默认，网关按实际接单行的设置代发`
        : "资源池没设推理默认 ⇒ 网关不代发（用厂商自己的默认行为）",
      "影响：控制模型是否深度思考。想设置 → 下方「资源池」每行右侧的推理档位下拉");
}

/** 网关侧合并规格的三态呈现（数据 = `GET /admin/api/config` 每条模型上的只读派生位 `spec`）。
 *  未知 = 没有任何来源说过（**不印 0**）；陈旧 = 数取自超 TTL 的目录缓存（仍是可用的兜底值）；
 *  实时 = 当天目录说过。三态不许折叠成两态（frontend-spec §7.18 通用律）。 */
function specRows(m) {
  const s = m.spec || null;
  const fmt = (v) => (v === null || v === undefined) ? "未知" : fmtTok(v);
  const hasNum = !!s && (s.max_input != null || s.max_output != null);
  let badge, tip;
  if (!s || !hasNum) {
    badge = `<span class="badge b-gray">未知</span>`;
    tip = "没有任何来源说过这个模型的规格：既没有内置目录条目，也没有生效资源的账号目录";
  } else if (s.stale) {
    tip = "数取自超过一天未刷新的目录缓存：仍是可用的兜底值，但不是当下的事实";
    badge = `<span class="badge b-warn" title="${esc(tip)}">取自昨日目录</span>`;
  } else {
    tip = "规格来自当天取到的目录";
    badge = `<span class="badge b-ok" title="${esc(tip)}">实时</span>`;
  }
  return `
    <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px 12px">
      <div class="form-row" style="margin-bottom:0"><label>最大上下文</label>
        <div class="mono">${fmt(s && s.max_input)}</div></div>
      <div class="form-row" style="margin-bottom:0"><label>最大输出</label>
        <div class="mono">${fmt(s && s.max_output)}</div></div>
      <div class="form-row" style="margin-bottom:0"><label title="${esc(tip)}">规格新鲜度</label>
        <div>${badge}</div></div>
    </div>
    ${s && s.sources ? `<p class="form-hint" style="margin-top:10px">合并自 ${s.sources} 份来源（同一网关模型下所有生效资源的并集；数值取大 = 对外承诺上限）。</p>` : ""}`;
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
  /* 行集合 = 官方档案的键 ∪ 有缺省值的键 ∪ 用户已设的键（自定义键排最后）。
   * 🔴 不能只取 `params_default`：那等于把"官方有这个参数、只是没公布缺省"这类模型整张卡判空
   *   （2026-10-04 排查的那条根因就在这里）。 */
  const pkeys = [...new Set([
    ...Object.keys(e?.param_fields || {}),
    ...Object.keys(e?.params_default || {}), ...Object.keys(m.params || {})])];

  box.innerHTML = `
    <!-- 头卡：模型名 + 端点/状态徽章 + 启停（删除按钮 Q24-④ 暂隐藏） -->
    <div class="card" style="display:flex;align-items:center;justify-content:space-between;gap:12px">
      <div style="display:flex;min-width:0;align-items:center;gap:12px">
        <span class="logo-block ${vendorIconTag(vendorOf(m)) ? "" : "dark"}">${vendorIconTag(vendorOf(m)) || esc((m.name[0] || "模").toUpperCase())}</span>
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
        <!-- 启停 = 开关（2026-10-03 用户指示：把「启用/禁用」那颗文字钮换成开关，拨一下就生效）。
             挂载点由 bindDetail 每次重绘重绑（D3：绑在当下这颗开关上，不绑 id 找旧元素）。 -->
        <span id="md-toggle" style="display:inline-flex;align-items:center"></span>
        ${SHOW_DELETE ? `<button class="icon-btn lg danger" id="md-del" aria-label="删除模型"
          title="删除该网关模型（工具端调用将立即 404）">${TRASH}</button>` : ""}
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

      <!-- 网关承诺（合并规格）：与上面「内置目录 · 官网取证」是**两个来源**，分开画。
           对外声明（/v1/models）与出站缺省注入读的都是这一份 ⇒ 用户问"工具看到的窗口为什么是这个数"
           要看这里，不是属性卡。三态分开画（未知 / 陈旧 / 实时），不许把"没有来源说过"印成 0。 -->
      <section class="card" style="margin-top:12px">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px">
          <div style="font-size:13px;font-weight:800;color:var(--text-soft)">网关承诺（合并规格）</div>
          <div style="font-size:12px;font-weight:500;color:var(--text-faint)">来源：生效资源的统一规格 · 对外声明与出站默认都读它</div>
        </div>
        ${specRows(m)}
      </section>

      <!-- 资源池：有序映射（顺序 = 优先级） -->
      <section class="card" style="margin-top:12px">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px">
          <div style="font-size:13px;font-weight:800;color:var(--text-soft)">资源池</div>
          <div style="font-size:12px;font-weight:500;color:var(--text-faint)">顺序 = 优先级：生效集 top-x 承接、失败切换按序补位</div>
        </div>
        <div id="md-pool" style="display:flex;flex-direction:column">${poolRows(m)}</div>
        <p class="form-hint" style="margin-top:12px">新增 / 调整映射：Key 接入在「接入模型资源」页编辑对应资源，账号接入在「接入账号资源」页用「模型映射」（产品 × 模型）${isChat ? "；行内 effort 为该资源推理默认（请求级指定优先，空 = 不注入）" : ""}。</p>
      </section>

      <!-- 参数配置：工具传参 > 网关设置 > 供应商通道默认（Q24，仅 chat 注入）。
           两段式（2026-10-04；2026-10-06 用户指示改成人话）：上段 = 这张卡能改的；下段 = 网关照样会发、但不在这张卡上的
           （max_tokens 走统一规格、推理档走资源池，见 core/scheduler.py 的 _out_body 两次注入）。
           只画上段的话，空卡就在谎称"网关没设参数"。 -->
      ${isChat ? `
      <section class="card" style="margin-top:12px">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px">
          <div style="display:flex;align-items:baseline;gap:14px;min-width:0">
            <div class="card-title" style="font-size:14px;font-weight:800;color:var(--text)">参数配置</div>
            <span style="font-size:12px;font-weight:500;color:var(--text-muted)">行 = 厂商官方暴露的参数 · 依据来自内置目录取证</span>
          </div>
          <div style="display:flex;align-items:center;gap:12px;flex:none">
            <span style="font-size:12px;font-weight:500;color:var(--text-muted)">优先级：工具调用传参 &gt; 此处网关设置 &gt; 供应商通道默认</span>
            <button class="btn btn-sm" id="md-preset" ${e && Object.keys(e.params_default || {}).length ? "" : "disabled"}
              title="一键将该模型全部参数重置为官方默认（当前值与自定义参数将被覆盖）">恢复官方配置</button>
          </div>
        </div>
        <!-- 公共说明色块（2026-10-06 用户指示）：所有模型通用的文档性信息集中成卡，
             每参数特有说明才下放到行内；详细出处（URL/日期/官方原话）收进帮助页。 -->
        <div class="alert alert-info" style="margin:12px 0 0">
          <div class="alert-title">这个表格怎么用</div>
          这里每一行 = 一个请求参数。表格里填的值，网关会自动随每次对话请求发给厂商；
          留空就发厂商自己的默认值。优先级：工具调用临时带的参数 &gt; 这里设置的值 &gt; 厂商默认。
          只对对话请求生效，图像生成不受影响。<a href="/help/params.html" target="_blank" rel="noopener"
            style="color:var(--cool);font-weight:600;text-decoration:none;white-space:nowrap">参数配置详细说明 ↗</a>
        </div>
        <div id="md-params" style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px 28px;margin-top:12px">
          ${pkeys.map((k) => paramRow(m, e, k)).join("") ||
            `<p class="form-hint" style="padding:2px 0">厂商官方没有公布这个模型的参数缺省值${e ? "（未核实的值网关不替你猜）" : "（该模型不在内置目录，无官方档案）"}，你也还没设过任何参数 ⇒ 这些参数一律不注入，走供应商通道默认。可在下方按参数名手动添加；网关自动代发的内容见下方「网关自动代发的 2 个参数」。</p>`}
        </div>
        <div style="display:flex;gap:8px;margin-top:12px;align-items:center">
          <input class="in mono" id="md-pnew" list="md-pkey-list" placeholder="添加参数名（如 top_k）" style="width:220px">
          <datalist id="md-pkey-list">
            ${[...new Set([...pkeys, ...COMMON_PARAM_KEYS])].map((k) => `<option value="${esc(k)}">${esc(PARAM_LABEL[k] || k)}${k in (e?.param_fields || {}) ? "（该模型官方在册）" : "（通用参数名，未取证）"}</option>`).join("")}
          </datalist>
          <button class="btn" id="md-padd">添加参数</button>
        </div>
        <div style="border-top:1px solid var(--border);margin-top:16px;padding-top:12px">
          <div style="display:flex;align-items:baseline;gap:14px;min-width:0;flex-wrap:wrap">
            <div style="font-size:14px;font-weight:800;color:var(--text)">网关自动代发的 2 个参数 · 这里改不了</div>
            <span style="font-size:12px;font-weight:500;color:var(--text-muted)">只读 · 不在上面的表格里，但网关确实会随请求发出去 · <a href="/help/params.html" target="_blank" rel="noopener" style="color:var(--cool);font-weight:600;text-decoration:none">详见说明 ↗</a></span>
          </div>
          <div id="md-injected" style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px 28px;margin-top:10px">
            ${injectedElsewhereHTML(m)}
          </div>
        </div>
        <p class="form-hint" style="margin-top:12px">表格里的值 = 网关随请求发出去的值（厂商公布了缺省的那几项，新建时已自动带入官方默认）。留空 = 不代发、用厂商默认（<span class="mono">max_tokens</span> 例外：留空时网关按账号上限代发，见上段）。工具请求自带参数时以请求为准。行尾 × = 清空该参数（自定义参数 = 删除该行）；「恢复官方配置」一键还原官方默认。仅 chat 对话生效，图像生成不注入。</p>
      </section>` : ""}
    </div>`;

  bindDetail(root, m, e);
}

/* ---------- 推理 effort 下拉：官方档位枚举优先，无档位文档的模型用跨厂商通用三档 ---------- */
const EFFORT_LABEL = { low: "low · 轻量", medium: "medium · 中档", high: "high · 增强", max: "max · 深度" };

/** 池的「配置单元」= 界面上的一行。两类两种维度（2026-10-02 用户裁决收敛）：
 *  - **Key 接入侧**：一条映射 = 一行（供应商 + Key 维度，维持既有形式）；
 *  - **账号侧**：同一 `(产品, 上游模型)` 的多条派生映射**聚成一行**（产品 × 模型维度）——
 *    账号页「模型映射」的落点是"每个已启用账号的物化资源"
 *    （`api/admin_accounts.py:1355-1358`），所以 CodeBuddy 两个账号 × 同一模型
 *    在数组里是两条、在界面上是一行「N 个账号」。
 * 🔴 只与**相邻**同组条目合并：`m.resources[]` 的下标就是调度优先级，
 *    被别的条目隔开说明这一组在两处各有一个优先级位，合成一行就是在撒谎（也会让"上移"跨位移动）。 */
/** 这条映射**当下进不进池**：只读后端派生的 `mapping_enabled`（= `AppConfig.mapping_enabled`，
 *  Key 接入侧看条目位、账号侧看产品位 + 号开关）。🔴 判据不在前端再写一份——写一份就是两套真相
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
        + "（增删/停用账号请到「接入账号资源」页的模型映射弹窗）"
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
          <option value="" ${curEffort ? "" : "selected"}>${mixed ? "组内不一致（改以统一）" : "不注入（供应商通道默认）"}</option>
          ${levels.map((lv) => `<option value="${esc(lv)}" ${lv === curEffort ? "selected" : ""}>${esc(EFFORT_LABEL[lv] || lv)}</option>`).join("")}
        </select>` : ""}
        <span style="display:flex;gap:4px;flex:none;margin-right:12px">
          <button class="btn btn-sm" data-up="${k}" data-with="${up === undefined ? "" : up}" ${up === undefined ? "disabled" : ""} title="上移（提高优先级）">↑</button>
          <button class="btn btn-sm" data-down="${k}" data-with="${down === undefined ? "" : down}" ${down === undefined ? "disabled" : ""} title="下移（降低优先级）">↓</button>
          <button class="icon-btn sm danger" data-rmres="${idxs}" title="${isAcc ? `移除该组 ${u.idxs.length} 个账号的映射` : "移除该映射"}">${TRASH}</button>
        </span>
      </div>`;
  }).join("") || `<p class="form-hint" style="padding:2px 0">无资源（调用将无可用资源 503）——Key 接入请到「接入模型资源」页添加映射，账号接入请到「接入账号资源」页做「模型映射」</p>`;
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

/** 按官方档案的 kind 解析输入（没档案才回落到上面那套猜类型的老规矩） */
function coerceParamFor(raw, field) {
  const s = String(raw ?? "").trim();
  if (s === "") return null;
  if (field && field.kind === "string_list") {
    const arr = s.split(",").map((x) => x.trim()).filter(Boolean);
    return arr.length ? arr : null;
  }
  if (field && field.kind === "boolean") {
    if (s === "true") return true;
    if (s === "false") return false;
  }
  return coerceParam(s);
}

/** 本页自带开关（与 accounts.js 同一份契约：`role="switch"` + `aria-checked` + `aria-label`，
 *  切换时同步 `aria-checked`；共享层 `components.js::switchEl` 无 aria 三件套，设计书 §6「明确不做」
 *  把它单列一项，故不"顺手收敛"）。 */
function switchEl(on, label, onToggle) {
  const el = document.createElement("button");
  el.className = "switch" + (on ? " on" : "");
  el.setAttribute("role", "switch");
  el.setAttribute("aria-checked", on ? "true" : "false");
  el.setAttribute("aria-label", label);
  el.onclick = async () => {
    const next = !el.classList.contains("on");
    const ok = onToggle ? await onToggle(next) : true;
    if (ok !== false) {
      el.classList.toggle("on", next);
      el.setAttribute("aria-checked", next ? "true" : "false");
    }
  };
  return el;
}

/** 启停落库：🔴 写失败必须回滚本地态并**不翻牌**——界面说"已启用"而配置里没写，
 *  就是 Q33 一直在消灭的那一类假态（`persist()` 把异常吞成 toast，这里不能复用它）。 */
async function toggleEnabled(root, m, next) {
  const prev = m.enabled;
  m.enabled = next;
  try {
    await PUT("/admin/api/config", cfg);
    toast(next ? "模型已启用" : "模型已禁用（对外不可调用）", "ok");
  } catch (e) {
    m.enabled = prev;
    toast("保存失败：" + e.message, "err");
  }
  await renderModels(root);
  return m.enabled === next;
}

function bindDetail(root, m, e) {
  const slot = root.querySelector("#md-toggle");
  if (slot) {
    slot.innerHTML = "";                                 // 重绘前清空，杜绝开关叠开关
    slot.append(switchEl(m.enabled !== false,
      `启用 / 禁用模型 ${m.name}（关 = 对外不可调用：/v1/models 不再返回、调用一律 404 + model_disabled）`,
      (next) => toggleEnabled(root, m, next)));
  }
  if (SHOW_DELETE) root.querySelector("#md-del").onclick = async () => {
    if (!await confirmDialog("删除网关模型",
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

  /* 参数配置（Q24）：编辑 / 官方默认带入 / 新增键。
   * 🔴 取值必须按该键的官方 kind 解析：档案写 `string_list` 却存成字符串，
   *    后端 `stop` 校验与上游拿到的形状就不是一个东西（数组才是官方形状）。 */
  const applyParam = async (key, raw, okMsg) => {
    const v = coerceParamFor(raw, pfield(e, key));
    if (v === null) {
      if (!(key in (m.params || {}))) return;
      delete m.params[key];
      await persist(root, key === "max_tokens" && m.spec?.max_output != null
        ? `已移除 ${key}（改由统一规格注入 ${m.spec.max_output}）`
        : `已移除 ${key}（恢复供应商通道默认）`);
    } else {
      const same = JSON.stringify((m.params || {})[key]) === JSON.stringify(v);
      if (same) return;
      m.params = { ...(m.params || {}), [key]: v };
      await persist(root, okMsg || `${key} 已更新（请求携带时以请求为准）`);
    }
  };
  root.querySelectorAll("[data-pkey]").forEach((input) =>
    input.addEventListener("change", () => applyParam(input.dataset.pkey, input.value)));
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
      await persist(root, official
        ? (key === "max_tokens" && m.spec?.max_output != null
          ? `${key} 已清空（改由统一规格注入 ${m.spec.max_output}）`
          : `${key} 已清空（不再注入，走供应商通道默认）`)
        : `已删除参数 ${key}`);
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
      const v = coerceParamFor(input.value, pfield(e, key));
      if (v === null) return; /* 空值 = 尚未设置，不写配置 */
      m.params = { ...(m.params || {}), [key]: v };
      await persist(root, `${key} 已更新（请求携带时以请求为准）`);
    });
    pnew.value = "";
    input.focus();
  };
}
