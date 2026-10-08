/** API 接入：对外调用一页取齐（Q18-④；骨架 D · frontend-spec §6/§7.9/§7.13-7.14）。
 * 交互 = 操作即保存（D3，对齐「模型资源」页）：添加 / 删除 / 启停 / 用途标注确认后
 * 直接 PUT 并以服务端最新配置重渲染（服务端自动生成 tok- id 与 mg- 密钥值）。
 * 结构（2026-09-06 用户定版）：接入密钥 .card.flush 表格卡置顶（用途标注行内编辑 +
 * 状态开关 + 密钥值密文显示 + 眼睛查看明文 + 复制 icon）→ .split-50 两板块并列
 * （调用地址 | 端点说明），地址值块内嵌复制 icon（对齐资源页 Base URL 模式）。
 * 密钥值默认密文（maskVal 前5+****+后4，同资源页 Key 规格），眼睛切换明文（2026-09-06）。 */

import { GET, PUT, esc } from "../api.js";
import { modal, confirmDialog, toast, copyText, switchEl } from "../components.js";

const PLUS = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>`;
const TRASH = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 11v6"/><path d="M14 11v6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`;
const COPY = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>`;
const EYE = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/></svg>`;
const EYE_OFF = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1-1.444 2.49"/><path d="M14.084 14.158a3 3 0 0 1-4.242-4.242"/><path d="M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143"/><path d="m2 2 20 20"/></svg>`;

/* 密文规格同资源页 Key：前 5 位 + **** + 后 4 位 */
const maskVal = (v) => v ? v.slice(0, 5) + "****" + v.slice(-4) : "";

let cfg = null;
let overview = null;

export async function renderApiAccess(root) {
  [cfg, overview] = await Promise.all([
    GET("/admin/api/config"), GET("/admin/api/overview")]);
  draw(root);
}

/** 操作即保存：PUT 全量配置 → 无论成败以服务端最新配置重渲染（自同步，同资源页 persist） */
async function persist(root, okMsg = "已保存并生效") {
  try {
    await PUT("/admin/api/config", cfg);
    if (okMsg) toast(okMsg, "ok");
  } catch (e) {
    toast("保存失败：" + e.message, "err");
  }
  await renderApiAccess(root);
}

function draw(root) {
  const addr = overview.call_addresses;
  const tokens = cfg.gateway?.access_tokens || [];
  /* 地址值块内嵌复制 icon（对齐资源页 Base URL 模式：icon 20×20 在框内链接后） */
  const addrPair = (label, url) => `
    <span class="addr-group">
      <span class="addr-label">${label}</span>
      <span class="addr-value" style="display:inline-flex;align-items:center;gap:8px">
        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(url)}</span>
        <button class="icon-btn sm" data-copy="${esc(url)}" title="复制 ${label}地址"
          style="width:20px;height:20px">${COPY}</button>
      </span>
    </span>`;
  root.innerHTML = `
    <p class="page-desc">
      工具端（Trae / Cursor / Cherry Studio 等）接入本网关所需的地址与密钥都在本页；不同工具可用不同密钥，便于区分调用。
      模型清单怎么取、推理强度与参数怎么设，见
      <a href="#/apidocs" style="color:var(--cool);font-weight:600;text-decoration:none">对接说明</a>。</p>

    <div class="card flush" style="margin-bottom:12px">
      <div class="card-head inset">
        <span class="card-title">接入密钥</span>
        <span class="value">${tokens.filter((t) => t.enabled !== false).length}/${tokens.length} 启用 · 未配置密钥时 /v1 免鉴权放行</span>
        <button class="btn btn-sm" id="a-addkey" style="margin-left:auto">${PLUS}添加密钥</button>
      </div>
      ${tokens.length ? `
      <div class="table-wrap"><table class="tbl"><thead><tr>
        <th>用途标注</th><th>密钥</th><th>状态</th><th class="num">操作</th>
      </tr></thead><tbody>
        ${tokens.map((t, i) => tokenRow(t, i)).join("")}
      </tbody></table></div>` :
      `<div class="empty" style="border:none;box-shadow:none">暂无接入密钥——点击「添加密钥」生成（工具端将无法鉴权调用）</div>`}
    </div>

    <div class="split-50">
      <div class="card">
        <div class="card-head"><span class="card-title">调用地址</span></div>
        <div class="addr-row">
          ${addrPair("本机", addr.local)}
          ${addrPair("局域网", addr.lan)}
        </div>
        <p class="form-hint">密钥用法：请求头 <code class="mono">Authorization: Bearer &lt;密钥&gt;</code>
          或 <code class="mono">x-api-key: &lt;密钥&gt;</code>（Anthropic 端点）。</p>
      </div>
      <div class="card">
        <div class="card-head"><span class="card-title">端点说明</span></div>
        <div class="endpoint-list">
          ${endpoint("/v1/chat/completions", "对话（OpenAI 兼容）", "非流式 + 流式（SSE）")}
          ${endpoint("/v1/images/generations", "图像生成", "返回 URL 或 base64（按模型能力）")}
          ${endpoint("/v1/messages", "对话（Anthropic 兼容）", "双向转换，供 Claude 系工具直连")}
          ${endpoint("/v1/models", "模型枚举", "仅返回已启用的网关模型")}
        </div>
      </div>
    </div>`;

  root.querySelector("#a-addkey").onclick = () => addKeyModal(root);
  root.querySelectorAll("[data-copy]").forEach((b) =>
    b.onclick = () => copyText(b.dataset.copy));

  for (const row of root.querySelectorAll("[data-tk]")) {
    const i = +row.dataset.tk;
    const t = cfg.gateway.access_tokens[i];
    row.querySelector("[data-tkname]").onchange = (e) => {
      const v = e.target.value.trim();
      if (v === (t.name || "")) return;
      t.name = v;
      persist(root, "用途标注已更新");
    };
    row.querySelector("[data-tksw]").append(switchEl(t.enabled !== false, async (next) => {
      t.enabled = next;
      await persist(root, next ? "密钥已启用" : "密钥已停用（该密钥的调用将 401）");
      return true;
    }));
    /* 眼睛查看：密文 ⇄ 明文就地切换（不重渲染；重渲染后回到密文安全态） */
    row.querySelector("[data-tkey]").onclick = (e) => {
      const btn = e.currentTarget;
      const span = row.querySelector("[data-tkval]");
      if (btn.dataset.on === "1") {
        span.textContent = maskVal(t.value);
        btn.dataset.on = "";
        btn.innerHTML = EYE;
        btn.title = "显示 / 隐藏明文";
      } else {
        span.textContent = t.value;
        btn.dataset.on = "1";
        btn.innerHTML = EYE_OFF;
        btn.title = "收回明文";
      }
    };
    row.querySelector("[data-cpykey]").onclick = () => copyText(t.value, "密钥已复制");
    row.querySelector("[data-delkey]").onclick = async () => {
      if (!await confirmDialog("删除密钥",
        `确定删除「${t.name || t.id}」？使用该密钥的工具将立即 401。`)) return;
      cfg.gateway.access_tokens.splice(i, 1);
      await persist(root, "密钥已删除");
    };
  }
}

function tokenRow(t, i) {
  const off = t.enabled === false;
  return `<tr data-tk="${i}">
    <td class="${off ? "off" : ""}" style="width:220px">
      <input class="in" data-tkname value="${esc(t.name || "")}" placeholder="用途标注（如 Trae）"
        style="width:100%;border:none;background:transparent;box-shadow:none;border-radius:0;padding:0;font-weight:600">
    </td>
    <td>
      <div style="display:flex;align-items:center;gap:8px;min-width:0">
        <span class="mono ellip tk-val ${off ? "off" : ""}" data-tkval style="flex:0 1 auto;min-width:0">${esc(maskVal(t.value))}</span>
        <button class="icon-btn sm ${off ? "off" : ""}" data-tkey title="显示 / 隐藏明文">${EYE}</button>
        <button class="icon-btn sm ${off ? "off" : ""}" data-cpykey title="复制密钥（直取明文）">${COPY}</button>
      </div>
    </td>
    <td><span data-tksw="${i}" style="display:inline-flex;align-items:center"></span></td>
    <td class="num" style="white-space:nowrap">
      <button class="icon-btn sm danger" data-delkey aria-label="删除密钥"
        title="删除该密钥（使用它的工具将立即 401）">${TRASH}</button>
    </td>
  </tr>`;
}

function endpoint(path, name, note) {
  return `<div class="endpoint-item">
    <span class="mono" style="font-weight:600">${esc(path)}</span>
    <span style="color:var(--text-muted)">${esc(name)}</span>
    <span class="form-hint">${esc(note)}</span>
  </div>`;
}

/* ---------- 添加密钥（值由系统自动生成；确认即落库生效） ---------- */
function addKeyModal(root) {
  const body = document.createElement("div");
  body.innerHTML = `
    <div class="form-row"><label>用途标注（区分不同工具调用）</label>
      <input name="name" placeholder="如：Trae / Cursor / Cherry Studio"></div>
    <p class="form-hint">密钥值与 ID 由系统自动生成（mg- 前缀），确认后立即生效，可在列表复制。</p>`;
  const foot = document.createElement("div");
  foot.innerHTML = `<button class="btn">取消</button><button class="btn btn-primary">生成并添加</button>`;
  /* 必须在 modal() **之前**取引用：modal() 会搬走 footer 子节点（components.js:32），
     调用后再 foot.querySelector 得到 null → "Cannot set properties of null (setting 'onclick')" */
  const cancelBtn = foot.querySelector(".btn");
  const okBtn = foot.querySelector(".btn-primary");
  const m = modal({ title: "添加接入密钥", body, footer: foot });
  cancelBtn.onclick = () => m.close();
  okBtn.onclick = async () => {
    const name = body.querySelector("[name=name]").value.trim();
    cfg.gateway.access_tokens ||= [];
    cfg.gateway.access_tokens.push({ id: "", name, value: "", enabled: true });  // id/value 服务端生成
    m.close();
    await persist(root, "已生成密钥并生效");
  };
}
