/** 系统设置：一张「运行参数」卡（网关服务 / 超时与预算 / 并发与切换 / 冷却窗口 / 日志与流水 五组）
 *  + 一张「维护」卡；脏态二段保存（全站唯一保留页）。
 *  （2026-10-03 用户实拍「现在的结构不符合页面设计规范。信息太分散并且一个输入框那么宽，
 *   设计很不合理很丑」⇒ 三卡堆叠（01 任务执行 / 02 系统日志 / 维护）合为两卡，
 *   `.form-grid2` 满宽表单行改 `.param-row` 参数行 = 名称在左 + 数值在右定宽、右缘对齐，
 *   每组两列 ⇒ 12 项一屏看完。口径见 frontend-spec §7.13 参数行档 / §6 骨架 D。
 *   🔴 同日用户第二次实拍「保存配置按钮放到板块框内部去 / 去掉板块内部子标题」⇒ 组内
 *   **不画可见小标题**（分组只留分割线 + `aria-label`），「保存配置」与脏态徽章一起搬进卡内
 *   `.card-foot`（页头吸顶条随之取消）。
 *   🔴 第三次实拍纠正「这些说明信息不是让你集中放一起……是放到每个配置分组下面，
 *   下一组配置分割线之上」⇒ 说明**跟着分组走**：`group(title, note, rows)` 每组渲染一条
 *   `.param-notes .pn`，位置在该组末行之下、下一组分割线之上（最后一组落在卡脚分割线之上）。）
 * Q18-③：调度参数全局唯一（x/y/m/超时/冷却），一套机制管控所有模型；
 * Q18-①：管理端免鉴权，无令牌门；接入产品/密钥管理分别移至「接入模型资源」「API 接入」页。
 * 🔴 12 个字段一律走同一个 num() 行构造器（行几何只能有一份定义）；调用字面与
 *   `#st-save`/`#st-exec`/`#st-restart`/`#st-stop`、脏态徽章文案是 v2 门 M10~M17 的判据对象。 */

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
    <!-- 🔴 2026-10-03 用户指示：「保存配置」按钮放进板块框内部，页头不再挂吸顶条。
         脏态徽章与按钮是同一个动作的两半，必须一起走（原来分在页头 / 卡内两处 = 改完参数
         眼睛在卡里找不到出口）。口径见 frontend-spec §7.13。 -->
    <div class="card" id="st-exec" style="margin-bottom:24px">${paramsSection()}</div>
    <div class="card" id="st-maint">${maintSection()}</div>`;

  root.querySelector("#st-save").onclick = () => save(root);
  bindExec(root);
  bindMaint(root);
  validateCross(root);   // 打开页面就把已有的非法组合标出来，不等用户点到它
}

/* ================= 运行参数（板块 · 五个子板块，子板块之间分割线）================= */
function paramsSection() {
  const g = cfg.gateway, s = cfg.scheduling;
  /* 参数行 = 名称在左（`for` 关联到框，点名称即聚焦）+ 数值在右（128px 定宽，右缘对齐成一条数值列）。
     框体复用全站 36px 行内输入 `.in`（不再另立一套高度）；`.form-row` 的满宽表单行只服务弹窗表单。
     五个实参的调用字面与 num() 内的 `min` 属性是 v2 门 M11/M17 变异锚点的对象 ⇒ 改签名即破锚。 */
  const num = (label, section, name, value, min) => `
    <div class="param-row"><label class="pk" for="p-${section}-${name}">${label}</label>
      <input class="in" id="p-${section}-${name}" type="number" min="${min}"
        data-sec="${section}" name="${name}" value="${value ?? ""}"></div>`;
  /* 🔴 子板块**不画可见小标题**（2026-10-03 用户指示：去掉"网关服务 / 超时与预算"这类子标题）。
     分组这件事留三处痕迹：分割线（CSS `.param-group`）+ `aria-label`（读屏与门都还能说出"这一组是什么"）
     + **该组自己的说明行**。
     🔴 说明行的位置 = 用户第二次纠正（13:5x 那版把五组说明集中成卡尾一块，判「这些说明信息不是让你集中放一起」）：
     **每组一条，跟在本人组配置项下面、下一组分割线之上**（最后一组则落在卡脚分割线之上）。
     集中到卡尾 = 读的人要自己把说明对回它是哪一组，等于没写。 */
  const group = (title, note, rows) => `
    <section class="param-group" aria-label="${title}">
      <div class="param-list">${rows}
      </div>
      <div class="param-notes"><div class="pn"><b>${title}</b><span>${note}</span></div></div>
    </section>`;
  return `
    <div class="card-head block-head">
      <div class="card-title bh-t">运行参数</div>
      <div class="bh-d">全局唯一，管控所有模型 · 改完点本卡右下角「保存配置」才落盘</div>
    </div>
    ${group("网关服务", "端口与全局并发上限（0 = 不限）；超限直接回 429。", `
        ${num("端口（port）", "gateway", "port", g.port, 1)}
        ${num("并发上限（0 = 不限）", "gateway", "max_concurrent_requests", g.max_concurrent_requests, 0)}`)}
    ${group("超时与预算", `<code class="mono">总预算 ≥ 尝试超时</code>，违反时保存被 400 拒。`, `
        ${num("单次尝试超时（秒）", "gateway", "attempt_timeout_seconds", g.attempt_timeout_seconds, 1)}
        ${num("请求总预算（秒，≥尝试超时）", "gateway", "request_total_budget_seconds", g.request_total_budget_seconds, 1)}`)}
    ${group("并发与切换（x / y / m）", `<code class="mono">x</code> 每模型并行资源数 · <code class="mono">y</code> 连败几次切换 · <code class="mono">m</code> 单资源重试次数。`, `
        ${num("x · 并行可用资源上限（两类接入合计）", "scheduling", "max_active_per_model", s.max_active_per_model, 1)}
        ${num("y · 连续失败阈值", "scheduling", "fail_threshold", s.fail_threshold, 1)}
        ${num("m · 单资源重试上限", "scheduling", "retry_per_request", s.retry_per_request, 0)}
        ${num("重试退避（秒，0 = 立即）", "scheduling", "retry_backoff_seconds", s.retry_backoff_seconds, 0)}`)}
    ${group("冷却窗口", "失败资源多久不再被选中；api 按接口失败计，plan 按额度耗尽计。", `
        ${num("api 冷却（秒）", "scheduling", "cooldown_seconds", s.cooldown_seconds, 0)}
        ${num("plan 冷却（秒）", "scheduling", "cooldown_seconds_plan", s.cooldown_seconds_plan, 0)}`)}
    ${group("日志与流水", `流水保留天数与心跳间隔；明文在 <code class="mono">data/usage/*.jsonl</code>。`, `
        ${num("事件流水保留（天）", "gateway", "retention_days", g.retention_days, 1)}
        ${num("SSE 心跳间隔（秒）", "gateway", "heartbeat_seconds", g.heartbeat_seconds, 1)}`)}
    <div class="card-foot" id="st-foot">
      <span class="foot-hint">校验不过会被 400 拒绝且不落盘。</span>
      ${dirty ? `<span class="badge b-warn">有未保存修改</span>` : ""}
      <button class="btn btn-primary" id="st-save" ${dirty ? "" : "disabled"}>保存配置</button>
    </div>`;
}

function bindExec(root) {
  const markDirty = () => {
    dirty = true;
    root.querySelector("#st-save").disabled = false;
    /* 脏态徽章就地补插（draw 时 dirty 恒为 false，重渲染才会出现——既有死 UI，v2.1 修复）。
       🔴 徽章插在**卡内脚钮区**的保存钮左边（2026-10-03 用户指示把按钮搬进板块内部后，
       页头那条已不存在；再往 `.page-actions` 里塞就是往 null 上塞 = 静默失效）。 */
    const foot = root.querySelector("#st-foot");
    if (foot && !foot.querySelector(".badge")) {
      const b = document.createElement("span");
      b.className = "badge b-warn";
      b.textContent = "有未保存修改";
      foot.prepend(b);        // 徽章排在这条动作行最前（与门 M12 的"徽章在最前"同一条口径）
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
      validateCross(root);
    });
  });
}

/* ================= 维护区：系统启停（配置导出已按 2026-09-06 用户指示移除）================= */
function maintSection() {
  /* 与「运行参数」同一套板块/子板块语言（旧形态是 maint-grid 里孤零零一块，
     网格空转 ⇒ 右侧大片无来路空白，且读不出"这是一组危险操作"）。 */
  return `
    <div class="card-head block-head">
      <div class="card-title bh-t">维护</div>
      <div class="bh-d">进程级操作，点击即执行，不走「保存配置」</div>
    </div>
    <section class="param-group" aria-label="系统启停">
      <div class="maint-ops">
        <button class="btn btn-sm btn-danger" id="st-restart">重启网关</button>
        <button class="btn btn-sm btn-danger" id="st-stop">停止网关</button>
      </div>
      <p class="group-note">重启期间在途请求中断后自恢复；停止后需双击「启动网关.command」重启。</p>
    </section>`;
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

/* 跨字段约束的**就地显形**（2026-10-03 独立评审：三方向共同缺的一条——400 防线不该只有后端一句话）。
 * 失焦与提交各校验一次；冲突时红边画在**两个相关字段**上、原因只写在依赖方那一行下面
 * （同一句话出现两次 = 用户要读两遍才知道是一条约束）。前端拦一遍不等于取代后端：
 * 权威仍是 `PUT /admin/api/config` 的 400，这里只是不让用户在已知非法的组合上按下保存。 */
const CROSS_CHECKS = [{
  bad: (g) => g.request_total_budget_seconds < g.attempt_timeout_seconds,
  marks: ["p-gateway-request_total_budget_seconds", "p-gateway-attempt_timeout_seconds"],
  at: "p-gateway-request_total_budget_seconds",
  msg: (g) => `请求总预算须 ≥ 单次尝试超时（当前尝试超时 ${g.attempt_timeout_seconds} 秒）`,
}];

function validateCross(root) {
  const g = cfg.gateway;
  root.querySelectorAll(".in.is-error").forEach((el) => el.classList.remove("is-error"));
  root.querySelectorAll(".param-err").forEach((el) => el.remove());
  const bad = [];
  for (const c of CROSS_CHECKS) {
    if (!c.bad(g)) continue;
    for (const id of c.marks) root.querySelector(`#${id}`)?.classList.add("is-error");
    const box = root.querySelector(`#${c.at}`);
    const anchor = box && (box.closest ? box.closest(".param-row") : box.parentNode);
    if (anchor) {
      const err = document.createElement("div");
      err.className = "param-err";
      err.textContent = c.msg(g);
      anchor.append(err);
    }
    bad.push(c.at);
  }
  return bad;
}

async function save(root) {
  /* 🔴 校验**只标不拦**（2026-10-03 与 v2 门 M15 对撞后裁决）：前端否决已知非法组合会让
     「后端 400 → 红色保存失败 + 服务端原因」这条既有契约永远走不到，等于界面上多立了一个权威、
     却把权威的话替换成自己的一句话。与 §8-16「界面不自建判断」同族 ⇒ 冲突就地标红 + 焦点送到
     第一个错误框，PUT 照发，最终结论由服务端给。 */
  const bad = validateCross(root);
  if (bad.length) root.querySelector(`#${bad[0]}`)?.focus?.();
  try {
    await PUT("/admin/api/config", cfg);
    dirty = false;
    toast("配置已保存并热重载生效", "ok");
    renderSettings(root);
  } catch (e) { toast("保存失败：" + e.message, "err"); }
}
