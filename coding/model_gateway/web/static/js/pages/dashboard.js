/** 总览 Dashboard：指标卡水平响应式 + 资源健康 + 今日趋势（design-spec §2.1 v0.3：无常驻事件块）。 */

import { GET, fmtNum, fmtUptime, fmtValue, esc } from "../api.js";

export async function renderDashboard(root) {
  const data = await GET("/admin/api/overview");
  const t = data.today;
  const c = data.counts || {};
  const healthy = data.resources.filter((r) => r.available).length;
  const cool = data.resources.filter((r) => r.status === "cooldown").length;
  const rate = t.requests ? Math.round((t.success / t.requests) * 1000) / 10 : 0;

  root.innerHTML = `
    ${configWarnings(data.warnings)}
    <div class="card-grid" style="margin-bottom:12px">
      ${metricCard("运行状态", cool ? `${cool} 资源冷却中` : "运行中", "mi-green", ICON.power)}
      ${metricCard("运行时长", fmtUptime(data.uptime_ms), "mi-green", ICON.activity)}
      ${metricCard("今日调用（次）", `成功 ${t.success} · 成功比 ${rate}%`,
        "mi-blue", ICON.calls)}
      ${metricCard("今日 token", `输入 ${fmtNum(t.input_tokens)} · 输出 ${fmtNum(t.output_tokens)}`,
        "mi-orange", ICON.coins)}
      ${metricCard("资源健康", `健康 ${healthy} · 总数 ${data.resources.length}`,
        "mi-purple", ICON.shield)}
      ${metricCard("厂商数量", c.vendors ?? "—", "mi-blue", ICON.factory)}
      ${metricCard("资源总数", c.resources ?? "—", "mi-purple", ICON.server)}
      ${metricCard("可用模型总数", c.models ?? "—", "mi-green", ICON.cpu)}
    </div>
    <div class="card-grid" style="margin-bottom:12px">
      <div class="card" style="grid-column:1/-1">
        <div class="card-head"><span class="card-title">今日调用趋势（24h）</span></div>
        <div id="hour-chart" style="height:160px"></div>
      </div>
    </div>
    <div class="card-grid">
      <div class="card" style="grid-column:1/-1">
        <div class="card-head"><span class="card-title">资源健康</span>
          <span class="value">今日切换 ${data.today.switch_count} 次 · <a href="#/logs" style="color:var(--cool);font-weight:700">查看日志</a></span></div>
        ${resourceHealthTable(data.resources)}
      </div>
    </div>`;

  drawHourChart(data.today_by_hour);
}

/* 指标卡图标（Q22：图标块 + 右侧信息列，参考规范组件层） */
const svg = (inner) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`;
const ICON = {
  power: svg(`<path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.77.04"/>`),
  activity: svg(`<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>`),
  calls: svg(`<path d="M8 3 4 7l4 4"/><path d="M4 7h16"/><path d="m16 21 4-4-4-4"/><path d="M20 17H4"/>`),
  coins: svg(`<circle cx="8" cy="8" r="6"/><path d="M18.09 10.37A6 6 0 1 1 10.34 18"/><path d="M7 6h1v4"/><path d="m16.71 13.88.7.71-2.82 2.82"/>`),
  shield: svg(`<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>`),
  factory: svg(`<rect width="16" height="20" x="4" y="2" rx="2" ry="2"/><path d="M9 22v-4h6v4"/><path d="M8 6h.01"/><path d="M16 6h.01"/><path d="M12 6h.01"/><path d="M12 10h.01"/><path d="M12 14h.01"/><path d="M16 10h.01"/><path d="M16 14h.01"/><path d="M8 10h.01"/><path d="M8 14h.01"/>`),
  server: svg(`<rect width="20" height="8" x="2" y="2" rx="2" ry="2"/><rect width="20" height="8" x="2" y="14" rx="2" ry="2"/><path d="M6 6h.01"/><path d="M6 18h.01"/>`),
  cpu: svg(`<rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>`),
};

/** 配置告警横幅（v2.0 §21 / PRD Q25-⑧）。
 *
 * 🔴 为什么走接口而非只写日志：启动脚本正常路径是 nohup 后台 + **自动关窗**，
 * 告警写进日志 = 用户看不见。本横幅是它在界面上的出口（复用既有 .alert-warn 组件）。
 */
function configWarnings(warnings) {
  const list = Array.isArray(warnings) ? warnings : [];
  if (!list.length) return "";
  return list.map((w) => `
    <div class="alert alert-warn">
      <div class="alert-title">配置告警</div>
      <div>${esc(w.message || "")}</div>
    </div>`).join("");
}

function metricCard(label, value, tone, icon) {
  return `<div class="card metric-card">
    <span class="metric-ico ${tone}">${icon}</span>
    <div class="metric-main">
      <div class="metric-label">${esc(label)}</div>
      <div class="metric-value">${fmtValue(value)}</div>
    </div></div>`;
}

/* 资源状态表（design-spec §2.1：资源名 / 状态 / 连续失败 C / 在途 / 冷却剩余 / 最近错误）。
 *
 * 🔴 单独成函数 = 可被 Node 直接执行来验渲染（本仓前端无构建、headless Chrome 在本机沙箱会挂）。
 * 「最近错误」是 §17 熔断回写的**唯一用户可见出口** —— 没有它，用户分不清
 * 「风控熔断（等 30 分钟）」与「普通失败冷却（该查 Key）」。
 */
function resourceHealthTable(resources) {
  const list = Array.isArray(resources) ? resources : [];
  const head = `<tr><th>资源</th><th>状态</th>
    <th class="num" title="连续失败次数（调用成功后清零；取该资源各模型条目最大值）">连续失败</th>
    <th class="num" title="当前正在处理的请求数（各模型条目合计）">处理中</th>
    <th class="num" title="移出生效集的剩余等待时间">冷却剩余</th>
    <th title="熔断 / 失败原因（风控熔断与普通冷却的区分）">最近错误</th></tr>`;
  const rows = list.map((r) => `
    <tr>
      <td class="mono" title="${esc(r.vendor || "")}${r.account ? " / " + esc(r.account) : ""} · ${r.models || 0} 个模型映射">${esc(r.name)}</td>
      <td>${statusBadge(r)}</td>
      <td class="num">${r.C || 0}</td>
      <td class="num">${r.in_flight || 0}</td>
      <td class="num" style="color:${r.status === "cooldown" ? "var(--cool)" : "var(--text-faint)"}">${r.status === "cooldown" ? fmtCooldown(r.cooldown_remaining_ms) : "—"}</td>
      <td class="ellip" style="max-width:280px;${r.last_error ? "" : "color:var(--text-faint)"}" title="${esc(r.last_error || "")}">${esc(r.last_error || "—")}</td>
    </tr>`).join("");
  return `<div class="table-wrap"><table class="tbl"><thead>${head}</thead>
    <tbody>${rows}</tbody></table></div>`;
}

/* 冷却剩余的统一口径（徽章 title 与「冷却剩余」列必须同源，验收 S-19）：
   同一份 ms 走同一个函数，避免"徽章 floor / 列 ceil"或"列显示 — 而 title 显示剩余 0s"。 */
function fmtCooldown(ms) {
  const n = Math.ceil((ms || 0) / 1000);
  return n > 0 ? `${n}s` : "—";
}

function statusBadge(r) {
  /* 🔴 判据只能是 `status`（后端已把"开关关闭 / 全部失效 / 全在冷却 / 正常"聚合成
     四态之一，见 `ResourceManager.snapshot_by_resource`）。
     原先第一行用 `available === false` 兜住"停用" —— 而 `available` 对所有非 active
     状态都是 false，于是冷却中/失效的资源都被说成「停用」（验收 IX-4）。
   * 🔴 四态给人话 + **与真实现一致的处置**（验收 S-18/S-19）：
     - `disabled` 有两个成因（`tech-design:140`「手动/401 停用」，实测 401 走
       `scheduler.py:403 disable()`），只说"打开开关即恢复"会让用户去拨一个本来就开着的开关，
       而真因（凭据被拒）只写在「最近错误」列里 → 文案必须两条出路都给；
     - `invalid` 的实义是 404「模型名无效」（`errors.py` NOT_FOUND → `invalidate()`），
       处置是**更换映射**，不是换 Key；
     - 未知状态保持中性样式（红=需要关注，不许乱给）。 */
  const left = Math.ceil((r.cooldown_remaining_ms || 0) / 1000);
  switch (r.status) {
    case "active": return `<span class="badge b-ok" title="可承接请求">可用</span>`;
    case "cooldown": return `<span class="badge b-cool" title="${
      left > 0 ? (/(读不动|不可信)/.test(r.last_error || "")
        // 🔴 第十二轮 PM B-12-2：同一行「最近错误」写着"确认无风控后删除该文件"，
        //    徽章却说"无需处理" —— 同屏两格互相打脸，用户会等自动恢复而不去处理。
        ? `${fmtCooldown(r.cooldown_remaining_ms)} 后暂时回池；熔断状态文件读不动，`
          + `需人工确认 —— 见「最近错误」列`
        : `${fmtCooldown(r.cooldown_remaining_ms)} 后自动回池，无需处理`)
               : "已到期，下次选路即回池"}">冷却中</span>`;
    case "invalid": return `<span class="badge b-err" title="上游回 404：该模型名无效 —— 到「接入模型资源」页更换映射（不会自愈）">模型名无效</span>`;
    case "disabled": return `<span class="badge b-muted" title="两种成因之一：资源开关已关闭（打开即恢复），或凭据被上游拒绝 401（需到「接入模型资源」页更换 Key，不会自愈）—— 见「最近错误」列">已停用</span>`;
    default: return `<span class="badge b-muted" title="网关未识别的状态值（可能是新版本引入的态）">${esc(String(r.status))}</span>`;
  }
}

/* 纯 CSS 柱状（24h 趋势，零依赖降级形态） */
function drawHourChart(hours) {
  const box = document.getElementById("hour-chart");
  if (!box) return;
  const max = Math.max(1, ...hours.map((h) => h.requests));
  const bar = (h) => {
    const pct = Math.round((h.requests / max) * 100);
    const parts = [h.success && `var(--ok) ${h.success}`, h.failed && `var(--err) ${h.failed}`,
      h.aborted && `var(--warn) ${h.aborted}`].filter(Boolean);
    return `<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;min-width:0">
      <div title="${h.hour}:00 · ${h.requests} 次（成功${h.success}/失败${h.failed}/中断${h.aborted}）"
        style="width:60%;flex:1;display:flex;flex-direction:column-reverse;border-radius:3px 3px 0 0;overflow:hidden;background:var(--surface-muted)">
        ${h.requests ? `<div style="display:flex;flex-direction:column;height:${pct}%;${parts.length ? "" : "background:var(--border)"}">${parts.map((p) => {
          const [color, n] = p.split(" ");
          return `<div style="background:${color};flex:${n}"></div>`; }).join("")}</div>` : ""}
      </div>
      <div style="font-size:10px;color:var(--text-faint)">${h.hour}</div></div>`;
  };
  box.innerHTML = `<div style="display:flex;height:100%;align-items:flex-end;gap:2px">${hours.map(bar).join("")}</div>`;
}
