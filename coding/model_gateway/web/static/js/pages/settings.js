/** 系统设置：01 任务执行（全局调度参数）+ 02 系统日志 + 维护区（系统启停），
 * 纵向三卡自然高度堆叠（12px 节奏；参数批量编辑走脏态二段保存——全站唯一保留页）。
 * （骨架 D · frontend-spec §6/§7.12-7.13：卡内二级头 .sec-head.sub、维护区 .maint-*、
 * 停止提示态 .center-card；导出功能已按 2026-09-06 用户指示全站移除）。
 * Q18-③：调度参数全局唯一（x/y/m/超时/冷却），一套机制管控所有模型；
 * Q18-①：管理端免鉴权，无令牌门；接入产品/密钥管理分别移至「接入模型资源」「API 接入」页。 */

import { GET, PUT, POST, esc } from "../api.js";
import { confirmDialog, toast } from "../components.js";

let cfg = null;
let dirty = false;

export async function renderSettings(root) {
  cfg = await GET("/admin/api/config");
  dirty = false;
  draw(root);
}

function draw(root) {
  root.innerHTML = `
    <div class="page-head">
      <div class="page-actions">
        ${dirty ? `<span class="badge b-warn">有未保存修改</span>` : ""}
        <button class="btn btn-primary" id="st-save" ${dirty ? "" : "disabled"}>保存配置</button>
      </div></div>
    <div class="card" id="st-exec" style="margin-bottom:12px">${execSection()}</div>
    <div class="card" id="st-logs" style="margin-bottom:12px">${logsSection()}</div>
    <div class="card">${maintSection()}</div>`;

  root.querySelector("#st-save").onclick = () => save(root);
  bindExec(root);
  bindMaint(root);
}

/* ================= 01 任务执行（全局调度与网关参数）================= */
function execSection() {
  const g = cfg.gateway, s = cfg.scheduling;
  const num = (label, section, name, value, min) => `
    <div class="form-row"><label>${label}</label>
      <input type="number" min="${min}" data-sec="${section}" name="${name}" value="${value ?? ""}"></div>`;
  return `
    <div class="card-head"><span class="card-title">01 · 任务执行</span>
      <span class="value">全局唯一，管控所有模型</span></div>
    <div class="sec-head sub"><span class="t">网关</span></div>
    <div class="form-grid2">
      ${num("端口（port）", "gateway", "port", g.port, 1)}
      ${num("并发上限（0 = 不限）", "gateway", "max_concurrent_requests", g.max_concurrent_requests, 0)}
      ${num("单次尝试超时（秒）", "gateway", "attempt_timeout_seconds", g.attempt_timeout_seconds, 1)}
      ${num("请求总预算（秒，≥尝试超时）", "gateway", "request_total_budget_seconds", g.request_total_budget_seconds, 1)}
    </div>
    <div class="sec-head sub"><span class="t">调度（x / y / m）</span></div>
    <div class="form-grid2">
      ${num("x · 并行可用资源上限（两类接入合计）", "scheduling", "max_active_per_model", s.max_active_per_model, 1)}
      ${num("y · 连续失败阈值", "scheduling", "fail_threshold", s.fail_threshold, 1)}
      ${num("m · 单资源重试上限", "scheduling", "retry_per_request", s.retry_per_request, 0)}
      ${num("重试退避（秒，0 = 立即）", "scheduling", "retry_backoff_seconds", s.retry_backoff_seconds, 0)}
      ${num("api 冷却（秒）", "scheduling", "cooldown_seconds", s.cooldown_seconds, 0)}
      ${num("plan 冷却（秒）", "scheduling", "cooldown_seconds_plan", s.cooldown_seconds_plan, 0)}
    </div>
    <p class="form-hint">校验：x≥1 · y≥1 · m≥0 · 冷却≥0 · 总预算≥尝试超时（违反保存将被 400 拒绝）。</p>`;
}

function bindExec(root) {
  const markDirty = () => {
    dirty = true;
    root.querySelector("#st-save").disabled = false;
    /* 脏态徽章就地补插（draw 时 dirty 恒为 false，重渲染才会出现——既有死 UI，v2.1 修复） */
    const pa = root.querySelector(".page-actions");
    if (pa && !pa.querySelector(".badge")) {
      const b = document.createElement("span");
      b.className = "badge b-warn";
      b.textContent = "有未保存修改";
      pa.prepend(b);
    }
  };
  root.querySelectorAll("[data-sec]").forEach((input) => {
    /* 正整数格式限制：键入/粘贴即时滤除非数字字符（禁负号/小数点/科学计数法；
       空 = 未修改语义由 change 分支处理；min 下限约束走既有 change 校验 + 后端 400） */
    input.addEventListener("input", () => {
      const clean = input.value.replace(/[^\d]/g, "");
      if (input.value !== clean) input.value = clean;
    });
    input.addEventListener("change", () => {
      const sec = input.dataset.sec;
      const v = input.value === "" ? null : Number(input.value);
      if (v == null || Number.isNaN(v)) return;
      cfg[sec][input.name] = v;
      markDirty();
    });
  });
}

/* ================= 02 系统日志（自然高度卡）================= */
function logsSection() {
  const g = cfg.gateway;
  return `
    <div class="card-head"><span class="card-title">02 · 系统日志</span></div>
    <div class="form-grid2">
      <div class="form-row"><label>事件流水保留（天）</label>
        <input type="number" min="1" data-sec="gateway" name="retention_days" value="${g.retention_days}"></div>
      <div class="form-row"><label>SSE 心跳间隔（秒）</label>
        <input type="number" min="1" data-sec="gateway" name="heartbeat_seconds" value="${g.heartbeat_seconds}"></div>
    </div>
    <p class="form-hint">排查问题时直接查询存储的明文流水：data/usage/events-*.jsonl ·
      switch-events-*.jsonl · daily-*.json（管理界面「请求日志」页为同数据页面化展示）。</p>`;
}

/* ================= 维护区：系统启停（配置导出已按 2026-09-06 用户指示移除）================= */
function maintSection() {
  return `
    <div class="card-head"><span class="card-title">维护</span></div>
    <div class="maint-grid">
      <div>
        <div class="maint-title danger">系统启停</div>
        <div class="maint-ops">
          <button class="btn btn-sm btn-danger" id="st-restart">重启网关</button>
          <button class="btn btn-sm btn-danger" id="st-stop">停止网关</button>
          <span class="form-hint">重启期间在途请求中断后自恢复；停止后需双击「启动网关.command」重启</span>
        </div>
      </div>
    </div>`;
}

function bindMaint(root) {
  root.querySelector("#st-restart").onclick = async () => {
    if (!await confirmDialog("重启网关",
      "重启期间在途请求将中断，网关会优雅停机后同端口自动重启（进程映像替换，配置重读）。确定继续？")) return;
    try {
      await POST("/admin/api/system/restart");
      toast("重启已受理，等待恢复…", "ok");
      await waitForRecovery(root);
    } catch (e) { toast("重启失败：" + e.message, "err"); }
  };
  root.querySelector("#st-stop").onclick = async () => {
    if (!await confirmDialog("停止网关",
      "停止后网关下线、管理界面无法操作；需通过项目根「启动网关.command」重新启动。确定停止？")) return;
    try {
      await POST("/admin/api/system/stop");
      stoppedState(root);
    } catch (e) { toast("停止失败：" + e.message, "err"); }
  };
}

async function waitForRecovery(root) {
  const deadline = Date.now() + 30000;
  const box = root.querySelector("#st-exec");
  box.style.opacity = ".5";
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 1000));
    try {
      await GET("/admin/api/status");
      toast("网关已重启恢复", "ok");
      renderSettings(root);
      return;
    } catch { /* 尚未恢复，继续等待 */ }
  }
  toast("30s 内未检测到恢复，请手动刷新确认", "err");
  box.style.opacity = "";
}

function stoppedState(root) {
  root.innerHTML = `
    <div class="card center-card">
      <div style="margin-bottom:16px;color:var(--err)"><svg viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.77.04"/></svg></div>
      <h2 style="font-size:18px;margin-bottom:8px">网关已停止</h2>
      <p style="color:var(--text-muted);font-size:13px;margin-bottom:20px">
        管理界面已无法连接后端。需要重新启动时，请双击项目根目录的
        <b>启动网关.command</b>（或终端执行 <code class="mono">.venv/bin/python -m model_gateway.main</code>），
        启动后刷新本页。</p>
    </div>`;
}

async function save(root) {
  try {
    await PUT("/admin/api/config", cfg);
    dirty = false;
    toast("配置已保存并热重载生效", "ok");
    renderSettings(root);
  } catch (e) { toast("保存失败：" + e.message, "err"); }
}
