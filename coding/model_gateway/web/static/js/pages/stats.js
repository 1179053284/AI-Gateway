/** 数据看板：时段 tab + 维度 tab 数据驱动 + 指标卡 + 日趋势（Chart.js）+ 维度明细表
 * （骨架 C · frontend-spec §5/§7.8-7.10：指标卡值单行 fmtValue；图表色运行时取令牌；表头 .sortable）。
 * 导出功能已按 2026-09-06 用户指示全站移除。 */

import { GET, esc, fmtNum, fmtDur, fmtValue } from "../api.js";
import { tabBar } from "../components.js";

const DIM_LABELS = {
  by_model: "按模型", by_resource: "按资源", by_token: "按密钥",
  by_provider: "按供应商", by_account: "按账号",
};
const PERIODS = [{ id: 1, label: "今日" }, { id: 7, label: "近 7 天" }, { id: 30, label: "近 30 天" }];

let period = 7;
let dim = "by_model";
let data = null;
let chart = null;
let sortState = { key: "requests", dir: -1 };  // 明细表排序状态

export async function renderStats(root) {
  data = await GET(`/admin/api/stats?days=${period}`);
  if (!data.dimensions?.includes(dim)) dim = data.dimensions?.[0] || "by_model";
  draw(root);
}

function draw(root) {
  const t = data.totals || {};
  const rate = t.requests ? Math.round((t.success / t.requests) * 100) : 0;
  const avg = data.averages || {};
  root.innerHTML = `
    <div style="display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin-bottom:12px">
      <div id="s-period"></div>
      <div id="s-dims"></div>
    </div>
    <div class="card-grid" style="margin-bottom:12px">
      ${metricCard("调用次数", fmtNum(t.requests), "mi-blue", ICON.chart)}
      ${metricCard("成功率", t.requests ? `${rate}%` : "—", "mi-green", ICON.check,
        t.requests ? `成功 ${fmtNum(t.success)} · 失败 ${fmtNum(t.failed)} · 中断 ${fmtNum(t.aborted)}` : "")}
      ${metricCard("token 入/出", `${fmtNum(t.input_tokens)} / ${fmtNum(t.output_tokens)}`, "mi-orange", ICON.coins)}
      ${metricCard("切换次数", `${fmtNum(t.switch_count)} · 重试 ${fmtNum(t.retry_count)}`, "mi-purple", ICON.refresh)}
      ${metricCard("平均耗时", fmtDur(avg.duration_ms), "mi-blue", ICON.timer)}
      ${metricCard("平均 TTFT", fmtDur(avg.ttft_ms), "mi-purple", ICON.gauge)}
      ${t.images_count ? metricCard("图像生成", `${fmtNum(t.images_count)} 张`, "mi-green", ICON.image) : ""}
    </div>
    <div class="card-grid" style="margin-bottom:12px">
      <div class="card" style="grid-column:1/-1">
        <div class="card-head"><span class="card-title">日维度调用趋势</span>
          <span class="value">${PERIODS.find((p) => p.id === period)?.label || ""} · 成功/失败/中断三系列</span></div>
        <div id="s-chart" style="height:220px"></div>
      </div>
    </div>
    <div class="card-grid">
      <div class="card" style="grid-column:1/-1">
        <div class="card-head"><span class="card-title">维度明细 · ${esc(DIM_LABELS[dim] || dim)}</span>
          <span class="value">点击列头排序</span></div>
        <div id="s-table"></div>
      </div>
    </div>`;

  root.querySelector("#s-period").append(tabBar(PERIODS, period, async (id) => {
    period = id;
    data = await GET(`/admin/api/stats?days=${period}`);
    draw(root);
  }));
  root.querySelector("#s-dims").append(tabBar(
    data.dimensions.map((d) => ({ id: d, label: DIM_LABELS[d] || d })), dim,
    (id) => { dim = id; draw(root); }));

  drawTable(root);
  drawChart(root);
}

/* 指标卡（Q22 图标块版式；规范 §7.8：值单行 · fmtValue CJK 等高；
   成功率卡 2026-09-06 用户定版：长枚举附属信息拆 12px 小字 sub 行） */
const svg = (inner) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`;
const ICON = {
  chart: svg(`<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>`),
  check: svg(`<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>`),
  coins: svg(`<circle cx="8" cy="8" r="6"/><path d="M18.09 10.37A6 6 0 1 1 10.34 18"/><path d="M7 6h1v4"/><path d="m16.71 13.88.7.71-2.82 2.82"/>`),
  refresh: svg(`<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>`),
  timer: svg(`<line x1="10" y1="2" x2="14" y2="2"/><line x1="12" y1="14" x2="15" y2="11"/><circle cx="12" cy="14" r="8"/>`),
  gauge: svg(`<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>`),
  image: svg(`<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>`),
};

function metricCard(label, value, tone, icon, sub = "") {
  return `<div class="card metric-card">
    <span class="metric-ico ${tone}">${icon}</span>
    <div class="metric-main">
      <div class="metric-label">${esc(label)}</div>
      <div class="metric-value">${fmtValue(value)}</div>
      ${sub ? `<div class="metric-label" style="margin-top:2px">${fmtValue(sub)}</div>` : ""}
    </div></div>`;
}

/* ---------- 维度明细表（排序状态 sortState） ---------- */
function drawTable(root) {
  const { key: sortKey, dir: sortDir } = sortState;
  const box = root.querySelector("#s-table");
  const buckets = Object.entries(data[dim] || {})
    .sort((a, b) => ((a[1][sortKey] ?? -1) < (b[1][sortKey] ?? -1) ? -1 :
      (a[1][sortKey] ?? -1) > (b[1][sortKey] ?? -1) ? 1 : 0) * sortDir);
  if (!buckets.length) {
    box.innerHTML = `<div class="empty">该维度暂无数据</div>`;
    return;
  }
  const cols = [
    ["名称", null], ["调用", "requests"], ["成功", "success"], ["失败", "failed"], ["中断", "aborted"],
    ["成功率", null], ["入 token", "input_tokens"], ["出 token", "output_tokens"],
    ["重试", "retry_count"], ["切换", "switch_count"], ["均耗时", null], ["均 TTFT", null],
  ];
  const th = (label, key) => `<th class="num${key ? " sortable" : ""}"${key ? ` data-sk="${key}"` : ""}>${label}${key === sortKey && key ? (sortDir > 0 ? " ↑" : " ↓") : ""}</th>`;
  box.innerHTML = `<div class="table-wrap"><table class="tbl"><thead><tr>
    ${cols.map(([l, k]) => (k ? th(l, k) : `<th class="num">${l}</th>`)).join("")}
  </tr></thead><tbody>${buckets.map(([name, b]) => {
    const rate = b.requests ? Math.round((b.success / b.requests) * 100) + "%" : "—";
    return `<tr>
      <td class="mono strong" style="text-align:left">${esc(name)}</td>
      <td class="num">${fmtNum(b.requests)}</td>
      <td class="num">${fmtNum(b.success)}</td>
      <td class="num">${fmtNum(b.failed)}</td>
      <td class="num">${fmtNum(b.aborted)}</td>
      <td class="num">${rate}</td>
      <td class="num">${fmtNum(b.input_tokens)}</td>
      <td class="num">${fmtNum(b.output_tokens)}</td>
      <td class="num">${fmtNum(b.retry_count)}</td>
      <td class="num">${fmtNum(b.switch_count)}</td>
      <td class="num mono">${fmtDur(Math.round((b.duration_ms_total || 0) / (b.requests || 1)))}</td>
      <td class="num mono">${b.ttft_count ? fmtDur(Math.round(b.ttft_ms_total / b.ttft_count)) : "—"}</td>
    </tr>`;
  }).join("")}</tbody></table></div>`;
  box.querySelectorAll("[data-sk]").forEach((el) =>
    el.onclick = () => {
      sortState = { key: el.dataset.sk, dir: el.dataset.sk === sortState.key ? -sortState.dir : -1 };
      drawTable(root);
    });
}

/* ---------- 日趋势折线（Chart.js 全局，index.html 引入；缺失时纯 CSS 降级）---------- */
function drawChart(root) {
  const box = root.querySelector("#s-chart");
  const trend = data.trend || [];
  const labels = trend.map((d) => `${d.date.slice(4, 6)}/${d.date.slice(6, 8)}`);
  if (typeof Chart === "undefined") { cssBars(box, trend); return; }
  if (chart) chart.destroy();
  box.innerHTML = "<canvas></canvas>"; // Chart.js v4 仅接受 canvas 元素（容器 div 不支持）
  // 双主题自适应：网格/刻度/系列色一律运行时读主题令牌（规范 §7.10，禁止硬编码系列色）
  const cs = getComputedStyle(document.documentElement);
  const tok = (n, fb) => cs.getPropertyValue(n).trim() || fb;
  const grid = tok("--border", "#e6e8ec");
  const tick = tok("--text-faint", "#969dab");
  const alpha = (hex, a) => {
    const n = parseInt(hex.replace("#", ""), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  };
  const series = [
    { key: "--ok", fallback: "#20a877", label: "成功", data: trend.map((d) => d.success), fill: true },
    { key: "--err", fallback: "#d95757", label: "失败", data: trend.map((d) => d.failed), fill: false },
    { key: "--warn", fallback: "#c26a00", label: "中断", data: trend.map((d) => d.aborted), fill: false },
  ].map((s) => {
    const c = tok(s.key, s.fallback);
    return { label: s.label, data: s.data, borderColor: c,
      backgroundColor: s.fill ? alpha(c, .08) : "transparent", fill: s.fill, tension: .3 };
  });
  chart = new Chart(box.querySelector("canvas"), {
    type: "line",
    data: { labels, datasets: series },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { color: tick, boxWidth: 12, font: { size: 12 } } } },
      scales: {
        x: { ticks: { color: tick }, grid: { color: grid } },
        y: { beginAtZero: true, ticks: { color: tick, precision: 0 }, grid: { color: grid } },
      },
    },
  });
}

function cssBars(box, trend) {
  const max = Math.max(1, ...trend.map((d) => d.requests));
  box.innerHTML = `<div style="display:flex;height:100%;align-items:flex-end;gap:3px">${trend.map((d) => `
    <div title="${d.date} · ${d.requests} 次" style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px">
      <div style="width:60%;height:${Math.round((d.requests / max) * 100)}%;background:var(--ok);border-radius:3px 3px 0 0;opacity:.85"></div>
      <div style="font-size:10px;color:var(--text-faint)">${d.date.slice(4, 6)}/${d.date.slice(6, 8)}</div>
    </div>`).join("")}</div>`;
}
