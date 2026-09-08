/** 请求日志：双 tab（请求流水/切换事件）+ 竖向排列（筛选卡在上 · 日志表格卡在下，
 * 2026-09-06 用户定版；筛选字段 .filter-grid 横排一行、窄屏自动换行）
 * （骨架 D 混合 · frontend-spec §6/§7.9：表头 .sortable、展开行 .exp + .req-detail、分页 .pager；
 * 按需加载：仅进入本页才请求日志数据）。 */

import { GET, esc, fmtNum, fmtDur } from "../api.js";
import { tabBar, pagination } from "../components.js";

const PAGE_SIZE = 100;
/* 展开指示（Lucide chevron-right / chevron-down，14px sw2） */
const CHEV_R = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>`;
const CHEV_D = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>`;

let tab = "requests";        // requests | switches
let filters = { date: todayStr(), model: "", status: "", token: "" };
let page = { offset: 0, total: 0 };
let sortKey = "ts", sortDir = -1; // 默认时间倒序（后端已最新在前）
let options = { models: [], tokens: [] };

function todayStr() { return new Date().toISOString().slice(0, 10); }
function dayParam() { return filters.date.replace(/-/g, ""); }

export async function renderLogs(root) {
  try {
    const cfg = await GET("/admin/api/config");
    options.models = (cfg.models || []).map((m) => m.name);
    options.tokens = (cfg.gateway?.access_tokens || []).map((t) => t.id);
  } catch { /* 下拉选项加载失败不阻断日志主体 */ }
  draw(root);
}

function draw(root) {
  root.innerHTML = `
    <div id="log-tabs" style="margin-bottom:12px"></div>
    <div class="card" style="margin-bottom:12px">
      <div class="card-head"><span class="card-title">筛选</span></div>
      <div class="filter-grid">
        <div class="form-row"><label>日期</label>
          <input type="date" id="f-date" value="${esc(filters.date)}" max="${todayStr()}"></div>
        ${tab === "requests" ? `
        <div class="form-row"><label>模型</label>
          <select id="f-model"><option value="">全部</option>
            ${options.models.map((m) => `<option value="${esc(m)}" ${m === filters.model ? "selected" : ""}>${esc(m)}</option>`).join("")}
          </select></div>
        <div class="form-row"><label>状态</label>
          <select id="f-status"><option value="">全部</option>
            ${["success", "failed", "aborted"].map((s) =>
              `<option value="${s}" ${s === filters.status ? "selected" : ""}>${statusLabel(s)}</option>`).join("")}
          </select></div>
        <div class="form-row"><label>密钥</label>
          <select id="f-token"><option value="">全部</option>
            ${options.tokens.map((t) => `<option value="${esc(t)}" ${t === filters.token ? "selected" : ""}>${esc(t)}</option>`).join("")}
          </select></div>` : `
        <p class="form-hint" style="flex:1;align-self:center">切换事件支持日期筛选；其余筛选仅请求流水 tab 提供。</p>`}
        <button class="btn btn-lg" id="f-reset">重置筛选</button>
      </div>
    </div>
    <div class="card">
      <div class="card-head"><span class="card-title">${tab === "requests" ? "请求流水" : "切换事件"}</span>
        <span class="value" id="f-count"></span></div>
      <div id="log-table"></div>
      <div id="log-page"></div>
    </div>`;

  const tabs = tabBar(
    [{ id: "requests", label: "请求流水" }, { id: "switches", label: "切换事件" }],
    tab, (id) => { tab = id; page.offset = 0; draw(root); });
  root.querySelector("#log-tabs").append(tabs);

  root.querySelector("#f-date").onchange = (e) => { filters.date = e.target.value; page.offset = 0; load(root); };
  if (tab === "requests") {
    root.querySelector("#f-model").onchange = (e) => { filters.model = e.target.value; page.offset = 0; load(root); };
    root.querySelector("#f-status").onchange = (e) => { filters.status = e.target.value; page.offset = 0; load(root); };
    root.querySelector("#f-token").onchange = (e) => { filters.token = e.target.value; page.offset = 0; load(root); };
  }
  root.querySelector("#f-reset").onclick = () => {
    filters = { date: todayStr(), model: "", status: "", token: "" };
    page.offset = 0; draw(root);
  };
  load(root);
}

async function load(root) {
  const tableBox = root.querySelector("#log-table");
  const pageBox = root.querySelector("#log-page");
  const countBox = root.querySelector("#f-count");
  tableBox.innerHTML = `<div class="loading">加载中…</div>`;
  pageBox.innerHTML = "";
  try {
    let rows;
    if (tab === "requests") {
      const q = new URLSearchParams({ date: dayParam(), limit: PAGE_SIZE, offset: page.offset });
      if (filters.model) q.set("model", filters.model);
      if (filters.status) q.set("status", filters.status);
      if (filters.token) q.set("token", filters.token);
      const data = await GET(`/admin/api/logs/requests?${q}`);
      rows = data.rows; page.total = data.total;
      tableBox.innerHTML = requestsTable(rows);
      bindExpand(root);
      bindSort(root, rows);
    } else {
      const q = new URLSearchParams({ date: dayParam(), limit: PAGE_SIZE });
      const data = await GET(`/admin/api/logs/switches?${q}`);
      rows = data.rows; page.total = data.total;
      tableBox.innerHTML = switchesTable(rows);
    }
    countBox.textContent = `共 ${page.total} 条`;
    if (page.total > PAGE_SIZE)
      pageBox.append(pagination(page.total, page.offset, PAGE_SIZE, (off) => {
        page.offset = off; load(root);
      }));
    else pageBox.innerHTML = "";
  } catch (e) {
    tableBox.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    countBox.textContent = "";
  }
}

/* ---------- 请求流水表 ---------- */
function requestsTable(rows) {
  if (!rows.length) return `<div class="empty">该筛选条件下无请求记录</div>`;
  const th = (key, label, num) => {
    const cls = [num && "num", key && "sortable"].filter(Boolean).join(" ");
    return `<th ${cls ? `class="${cls}"` : ""} ${key ? `data-sort="${key}"` : ""}>${label}${sortKey === key ? (sortDir > 0 ? " ↑" : " ↓") : ""}</th>`;
  };
  return `<div class="table-wrap"><table class="tbl"><thead><tr>
    ${th("ts", "时间")}${th("system_model", "模型")}${th("", "密钥")}${th("final_resource", "资源(终)")}
    ${th("", "状态")}${th("duration_ms", "耗时", 1)}${th("ttft_ms", "TTFT", 1)}
    ${th("input_tokens", "入/出", 1)}${th("retry_count", "重试", 1)}${th("", "")}
  </tr></thead><tbody>${rows.map((r) => requestRow(r)).join("")}
  </tbody></table></div>`;
}

function requestRow(r) {
  const attempts = (r.resource_attempts || []).map((a) => `
      <span>${esc(a.resource)} · 尝试 ${a.attempts} 次${a.switched ? ` · <span class="badge b-warn">切换出口</span>` : ""}
        ${(a.errors || []).length ? `<br><span class="errline">${esc(a.errors.join(" | "))}</span>` : ""}</span>`).join("");
  return `
    <tr class="req-row" data-rerow="${esc(r.request_id)}">
      <td class="mono">${esc((r.ts || "").replace("T", " ").slice(5, 23))}</td>
      <td class="strong">${esc(r.system_model || "")}</td>
      <td class="mono">${esc(r.client_token_id || "—")}</td>
      <td class="mono" title="${esc(r.provider || "")}${r.account ? " / " + esc(r.account) : ""}">${esc(r.final_resource || "—")}</td>
      <td>${statusDot(r.status)}</td>
      <td class="num mono">${fmtDur(r.duration_ms)}</td>
      <td class="num mono">${r.ttft_ms != null ? fmtDur(r.ttft_ms) : "—"}</td>
      <td class="num mono">${fmtNum(r.input_tokens)} / ${fmtNum(r.output_tokens)}</td>
      <td class="num">${r.retry_count || 0}${r.switch_count ? `+${r.switch_count}切换` : ""}</td>
      <td class="exp" data-expand="${esc(r.request_id)}" title="展开详情">${CHEV_R}</td>
    </tr>
    <tr class="hidden" data-rexp="${esc(r.request_id)}"><td></td><td colspan="9">
      <div class="req-detail">
        <span>request_id：${esc(r.request_id)} · ${r.endpoint || "chat"}${r.stream ? " · stream" : ""} · usage：${esc(r.usage_source || "estimated")}${r.images_count ? ` · 图像 ${r.images_count} 张` : ""}</span>
        ${r.error_summary ? `<span class="errline">错误：${esc(r.error_summary)}</span>` : ""}
        ${attempts ? `<span class="sep">${attempts}</span>` : ""}
      </div></td></tr>`;
}

/* ---------- 切换事件表 ---------- */
function switchesTable(rows) {
  if (!rows.length) return `<div class="empty">该日无切换事件</div>`;
  return `<div class="table-wrap"><table class="tbl"><thead><tr>
    <th>时间</th><th>模型</th><th>资源切换</th><th>原因</th><th>错误摘要</th><th>关联请求</th>
  </tr></thead><tbody>${rows.map((e) => `
    <tr>
      <td class="mono">${esc((e.ts || "").replace("T", " ").slice(5, 23))}</td>
      <td class="strong">${esc(e.system_model || "")}</td>
      <td class="mono">${esc(e.from_resource || "")}<br>→ ${esc(e.to_resource || "（无）")}</td>
      <td><span class="badge b-warn">${esc(e.reason_cls || "")}</span>${e.was_cooldown ? ` <span class="badge b-cool">冷却引发</span>` : ""}</td>
      <td class="mono ellip" style="max-width:260px" title="${esc(e.error_summary || "")}">${esc(e.error_summary || "—")}</td>
      <td class="mono">${esc(e.request_id?.slice(0, 8) || "—")}</td>
    </tr>`).join("")}
  </tbody></table></div>`;
}

/* ---------- 展开与排序 ---------- */
function bindExpand(root) {
  root.querySelectorAll("[data-expand]").forEach((t) =>
    t.onclick = () => {
      const exp = root.querySelector(`[data-rexp="${CSS.escape(t.dataset.expand)}"]`);
      const open = exp.classList.toggle("hidden");
      t.innerHTML = open ? CHEV_R : CHEV_D;
    });
}

function bindSort(root, rows) {
  root.querySelectorAll("[data-sort]").forEach((th) =>
    th.onclick = () => {
      const key = th.dataset.sort;
      if (sortKey === key) sortDir = -sortDir;
      else { sortKey = key; sortDir = -1; }
      rows.sort((a, b) => {
        const va = a[key] ?? -1, vb = b[key] ?? -1;
        return (va < vb ? -1 : va > vb ? 1 : 0) * sortDir;
      });
      root.querySelector("#log-table").innerHTML = requestsTable(rows);
      bindExpand(root); bindSort(root, rows);
    });
}

function statusLabel(s) {
  return { success: "成功", failed: "失败", aborted: "中断" }[s] || s;
}
function statusDot(s) {
  const cls = { success: "b-ok", failed: "b-err", aborted: "b-warn" }[s] || "b-muted";
  return `<span class="badge ${cls}">${statusLabel(s)}</span>`;
}
