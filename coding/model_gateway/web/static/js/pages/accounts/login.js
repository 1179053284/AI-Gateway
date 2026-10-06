/** 登录向导子模块（D-1/D-4 拆分第一步，2026-10-06）。
 *
 * 从 `accounts.js` 物理移出（原 2567-3263 行段）；契约/弹窗纪律/五型展示物见段首大注释。
 * 依赖注入面（主文件传入的共享符号）经顶部 import 显式声明——
 * 拼装门（verify_accounts_ui.mjs）按「主文件 → 子模块」顺序拼接真源码即可。
 */
import { GET, POST, esc } from "../../api.js";

/** 向导会话状态（模块级；**只有 stopWizard() 置空**，§4-2）——随本子模块搬入。 */
let wizard = null;
import { modal, confirmDialog, toast, copyText } from "../../components.js";
import {
  COPY, KIND_TEXT, LINK, PHONE, POLLABLE, POLL_MAX_FAILS, POLL_MS, TICK_MS,
  WINDOW_KINDS, kindHint, refreshAfter,
} from "../accounts.js";

/* ---------- 登录向导（五型：按 ProductMeta.login ∪ login_alt 与 Challenge 现物渲染） ----------
 * 三段结构（§22.3 两步式协议 + M7-E 两阶段提交）：
 *   **参数段**（登录方式 tab + 开始登录；账号标识由系统自动生成，不手填）
 * → **进行段**（M7-E 修正轮：官方登录页在**弹窗**里打开（`openLoginWindow`，为什么不是
 *   iframe 见其上方契约块）；本页 = 提示 / 「登录窗口」面板 / 设备码 / 二维码 / 兜底粘贴
 *   + 状态 / TTL 倒计时）
 * → **确认段**（`success` 后：正文与页脚都出「确定接入」→ `login/commit` 才真正落盘）。
 * 五型展示物：
 *   device_code  设备码（复制）+ 授权页地址（面板）→ 弹窗 + 轮询
 *   external_link 授权页地址（面板）→ 弹窗 + 轮询
 *   local_callback 授权页地址（面板）→ 弹窗；**接收端自动回跳为主路径**，粘贴是兜底（**不轮询**）
 *   qr           `qr_payload` = **服务端出的图片 data URI** → `<img>`（不开窗口：url 是
 *                二维码内容不是网页）；`url` = 二维码内容文字（兜底）；轮询
 *   sms_code     手机号 → `alt sms_send` → 验证码 → `alt sms_submit`（不开窗口）
 *
 * 🔴 弹窗纪律（M7-E 修正轮）：
 *   · 开窗时机 = `login/start` 响应到达即开（transient activation 窗口内），其间不 await；
 *   · `window.open(url, '_blank', 'width=800,height=600')` 的 features 串**不带 noopener**
 *     （带则返回 null、失去句柄）；链接侧以 `rel="noopener noreferrer"` 兜底；
 *   · 被拦截（句柄 falsy/closed）→ 面板切链接态；**绝不**用 location 赋值导航本管理页；
 *   · 关闭时机：第一段成功（`settle`）与向导关闭（`stopWizard`）。
 *
 * 🔴 轮询期间的**重绘纪律**：`pollOnce` 的每次 `pending` 只走 `paintStatus()`（只换状态格
 *   + 页脚），**绝不整段 `paint()`** —— 每 2 秒重建整个 body 只会闪烁，无任何收益。
 */

/** 本页自带开关（与 components.js `switchEl` 同视觉契约，并补齐 frontend-spec §7.16
 *  可访问性三件套：`role="switch"` + `aria-checked` + `aria-label`，切换时同步 `aria-checked`）。
 *  ⚠️ 共享层 `switchEl`（components.js:84）**无 aria 三件套**，收敛它牵动三个页面 ——
 *  设计书 §6「明确不做」把它单列一项，故本保留页面私有实现（不"顺手收敛"）。 */
export function switchEl(on, label, onToggle) {
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

export function openWizard(p) {
  if (!p) { toast("请先在左侧选择一个产品", "err"); return; }
  stopWizard();                                     // 单实例：开新向导前收干净旧的
  const kinds = [p.login, ...(p.login_alt || [])];
  /* 状态字段（M7-E 新增：awaiting = 已登录待确认；win = 弹窗句柄、winState = 窗口状态
     （"" 未开 / "open" / "blocked"）；bodyEl = paintStatus 的就地更新锚点）。
     **没有 name 字段**：账号标识由后端自动生成。 */
  const st = { p, kinds, kind: kinds[0], session: "", ttl: 0, deadline: 0,
    pollTimer: null, tickTimer: null, fails: 0, challenge: {}, account: "",
    phone: "", smsSent: false, status: null, busy: false, awaiting: false,
    win: null, winState: "", m: null, bodyEl: null };
  wizard = st;
  const body = document.createElement("div");
  const foot = document.createElement("div");
  /* 弹窗宽度决策（M7-E 修正轮，2026-10-01）：撤掉 `wide: true`、回默认 560px + 纵向堆叠。
     当年要 800px 只为容下右栏那张 420px 高的内嵌页画布；官方登录页改**弹窗**后，面板只剩
     「状态行 + 链接行 + 重开钮」三件小物 —— 两栏在 560px 里各约 250px 放不下长授权地址，
     而堆叠让地址/设备码行吃到整宽（截断更少），阅读顺序（提示 → 窗口状态 → 设备码/兜底
     → 确认）与操作顺序一致。 */
  st.m = modal({ title: `接入账号 · ${p.title}`, body, footer: foot,
    /* ✕ / 遮罩同样是"放弃本次登录"：一并请求作废会话（BD2 幂等，永不 404）——
       后端会**丢弃暂存凭据**：未点「确定接入」的登录不留任何账号目录。 */
    onClose: () => { if (wizard === st) { cancelSession(st); stopWizard(); } } });
  st.footEl = st.m.el ? st.m.el.querySelector(".modal-foot") : null;
  const paint = () => {
    body.innerHTML = wizardHTML(st);
    bindWizard(st, body, paint);
    paintFooter(st);
  };
  st.paint = paint;
  st.bodyEl = body;
  paint();
}

/** 页脚三态（M7-E）：
 *  · 未建会话 = 只有「关闭」；
 *  · 已建会话、未确认 = 「重新发起登录」+ TTL +「取消登录」；
 *  · **已登录待确认** = 追加主按钮「确定接入」（两阶段提交第二段）。
 *  🔴 按钮序：`取消登录` 在待确认态**不是最右**——最右留给确认落盘的肯定动作
 *  （与 `confirmDialog` 的「取消在前、确定在后」同序）；把"丢弃刚拿到的凭据"放在
 *  最右会撞上"右侧是主按钮"的肌肉记忆，风险高于收益。 */
export function paintFooter(st) {
  const footEl = st.footEl;
  if (!footEl) return;
  if (!st.session) {
    footEl.innerHTML = `<button class="btn" data-wz="cancel">关闭</button>`;
  } else if (st.awaiting) {
    footEl.innerHTML = `
      <button class="btn" data-wz="restart">重新发起登录</button>
      <span data-wz="ttl" style="margin-left:auto;font-size:12px;font-weight:600;color:var(--text-faint)">${esc(ttlText(st))}</span>
      <button class="btn btn-danger" data-wz="cancel">取消登录</button>
      <button class="btn btn-primary" data-wz="confirm" ${st.busy ? "disabled" : ""}>确定接入</button>`;
  } else {
    footEl.innerHTML = `
      <button class="btn" data-wz="restart">重新发起登录</button>
      <span data-wz="ttl" style="margin-left:auto;font-size:12px;font-weight:600;color:var(--text-faint)">${esc(ttlText(st))}</span>
      <button class="btn btn-danger" data-wz="cancel">取消登录</button>`;
  }
  for (const b of footEl.querySelectorAll("[data-wz]")) {
    const act = b.dataset.wz;
    if (act === "restart") b.onclick = () => startKind(st);
    else if (act === "cancel") b.onclick = () => { cancelSession(st); stopWizard(); };
    else if (act === "confirm") b.onclick = () => confirmCommit(st);
  }
}

const ttlText = (st) => (st.session ? `本次会话约 ${fmtLeft(st)} 后自动失效` : "");

/** TTL 倒计时（`ttl_s` 来自 `login/start`，§22.7）。 */
function fmtLeft(st) {
  if (!st.deadline) return "—";
  const left = Math.max(0, Math.round((st.deadline - Date.now()) / 1000));
  const m = Math.floor(left / 60);
  return `${m}:${String(left % 60).padStart(2, "0")}`;
}

/** 向导生命周期**唯一**出口（§4-2 守卫倒置的根修）：`wizard=null` 只在这里赋值。
 *  旧实现 `reload()` 先 `wizard=null` 再重渲染，于是 `draw()` 里的 `if (wizard) stopWizard()`
 *  永不为真 → 轮询 timer 泄漏 + 弹窗留在 #modal-root + `pollOnce` 的 `!wizard` 早退把登录静默冻死。 */
export function stopWizard() {
  const st = wizard;
  if (!st) return;
  wizard = null;
  if (st.pollTimer) clearInterval(st.pollTimer);
  if (st.tickTimer) clearInterval(st.tickTimer);
  st.pollTimer = st.tickTimer = null;
  closeLoginWindow(st);             // 向导关闭 = 放弃本次登录：它开出来的登录窗口一并收起
  const m = st.m;
  if (m) m.close();                 // 会回调 onClose；那里 `wizard === st` 已不成立 → 不重复取消
}

/** 作废上游登录会话（BD2）：幂等 `{cancelled:bool}`，`false` = 会话早已不在（**不是错误**）；
 *  🔴 M7-E：`st.session=""` 只出现在「确定接入」成功之后（会话已被服务端出表）；
 *  待确认态关窗/取消会照常发 cancel —— 后端**丢弃暂存凭据**，账号目录不留东西。 */
async function cancelSession(st) {
  if (!st || !st.session) return;
  const pid = st.p.id;
  const sid = st.session;
  try {
    await POST("/admin/api/accounts/login/cancel", { product: pid, session: sid });
  } catch (e) {
    /* 取消失败不阻塞关窗：会话仍会在 TTL 到期时由服务端出表，如实说明而不是假装成功。 */
    toast(`关窗了，但会话取消失败（约 ${Math.round((st.ttl || 0) / 60)} 分钟后自动失效）：${e.message}`, "err");
  }
}

async function startKind(st) {
  if (st.pollTimer) { clearInterval(st.pollTimer); st.pollTimer = null; }
  if (st.tickTimer) { clearInterval(st.tickTimer); st.tickTimer = null; }
  /* 新会话先清旧态（M7-E：awaiting / 窗口状态也必须复位，否则"重新发起登录"会带着
     上一轮的待确认态或窗口状态进来；旧弹窗一并收起 —— 重发后向导只认新会话，留着
     旧窗只会让人对错窗）。 */
  st.session = ""; st.challenge = {}; st.busy = false; st.fails = 0;
  st.deadline = 0; st.phone = ""; st.smsSent = false; st.account = "";
  st.awaiting = false; st.winState = "";
  closeLoginWindow(st);
  st.status = { title: "发起中", text: "正在向上游申请本次登录…", tone: "info" };
  st.paint();
  try {
    /* 🔴 不传 name（M7-E 用户裁决）：账号标识由后端自动生成（`{product}-{8hex}`，
       不重名）并在 `login/start` 响应 `account` 字段回传 —— 本页只展示，不手填。 */
    const r = await POST("/admin/api/accounts/login/start", { product: st.p.id, kind: st.kind });
    st.session = r.session || "";
    st.ttl = r.ttl_s || 0;
    st.deadline = st.ttl ? Date.now() + st.ttl * 1000 : 0;
    st.challenge = r.challenge || {};
    st.account = r.account || "";
    /* 🔴 响应到达**立即**开窗（中途不 await 任何东西）：此刻仍在用户点「开始登录」的
       transient activation 窗口内 —— 多一个 await 就可能被浏览器判成非用户手势而拦截
       （两步式后端先回 URL、后台再等回调；参考实现 jet-hub.js:1318-1329 同款纪律）。 */
    openLoginWindow(st);
    st.status = { title: "等待用户操作", text: guideText(st), tone: "info" };
    st.paint();
    /* 🔴 local_callback 与短信型**不轮询**（POLLABLE = R-5 契约的唯一落点）；
       local_callback 的结果由 BD4 接收端投递（服务端暂存到会话），界面靠轮询/回跳得知。 */
    if (POLLABLE.has(st.kind) && st.session) {
      st.pollTimer = setInterval(() => pollOnce(st), POLL_MS);
    }
    if (st.session && st.ttl) {
      st.tickTimer = setInterval(() => {
        if (wizard !== st) return;
        const left = Math.max(0, st.deadline - Date.now());
        /* TTL 文案出现在两处（正文 + 页脚）：一次 tick 两处都换，不用整段重绘
           （整段重绘的代价见 paintStatus 注） */
        if (st.bodyEl) {
          for (const cell of st.bodyEl.querySelectorAll('[data-wz="ttl"]')) {
            cell.textContent = ttlText(st);
          }
        }
        const cell = st.footEl && st.footEl.querySelector('[data-wz="ttl"]');
        if (cell) cell.textContent = ttlText(st);
        if (left <= 0) {
          clearInterval(st.tickTimer); st.tickTimer = null;
          if (st.pollTimer) { clearInterval(st.pollTimer); st.pollTimer = null; }
          st.status = { title: "会话已到期", text: "上游会话超时自动失效，可重新发起登录。", tone: "failed" };
          st.paint();
        }
      }, TICK_MS);
    }
  } catch (e) {
    st.status = { title: "发起登录失败", text: e.message, tone: "failed" };
    st.paint();
  }
}

function wizardHTML(st) {
  const c = st.challenge || {};
  const parts = [];
  if (st.kinds.length > 1) {
    parts.push(`<div class="tabs" style="margin-bottom:12px">${st.kinds.map((k) => `
      <button class="tab ${k === st.kind ? "active" : ""}" data-kind="${esc(k)}"
        ${st.session ? "disabled" : ""}>${esc(KIND_TEXT[k] || k)}</button>`).join("")}</div>`);
  }
  if (!st.session) {
    /* 参数段（M7-E）：**没有账号名输入** —— 账号标识由后端自动生成；
       展示文案只说明"会发生什么"，不让用户填任何标识数据。
       窗口型形态的「登录窗口」面板先在位：一行说明点「开始登录」后会发生什么
       （弹窗 800×600），开始后它变成窗口状态 + 链接 + 重开钮的操作面。 */
    parts.push(`<p class="form-hint" style="margin:0 0 12px">${esc(kindHint(st.kind))}</p>`);
    if (WINDOW_KINDS.has(st.kind)) parts.push(loginWindowHTML(st));
    parts.push(`<button class="btn btn-primary" data-wz="start">开始登录</button>
      <p class="form-hint" style="margin:8px 0 0">账号标识由系统自动生成（无需填写），
        登录完成后可在结果里看到。</p>`);
    return parts.join("");
  }
  /* 进行段（M7-E 修正轮 2026-10-01：官方登录页改**弹窗**，右栏内嵌页撤除；纵向堆叠：
     提示 → 「登录窗口」面板 → 设备码/二维码/兜底粘贴 → 账号标识 → TTL → 状态 → 待确认块） */
  parts.push(`<p class="form-hint" style="margin:0 0 12px">${esc(kindHint(st.kind))}</p>`);
  if (WINDOW_KINDS.has(st.kind)) parts.push(loginWindowHTML(st));
  if (st.kind === "sms_code") parts.push(smsHTML(st));
  else if (st.kind === "local_callback") parts.push(callbackHTML());
  else parts.push(linkHTML(st, c));
  parts.push(accountLineHTML(st));
  parts.push(`<p class="form-hint" style="margin:8px 0 0" data-wz="ttl">${esc(ttlText(st))}</p>`);
  parts.push(`<div id="ac-wz-status">${st.status ? alertHTML(st.status) : ""}</div>`);
  /* 待确认块：`awaiting`（轮询/粘贴通道已报 success）必出；local_callback 型**恒出** ——
     🔴 它的主通道是接收端投递，服务端暂存后**没有推送**给本页（trae 的 `login_poll` 是显式
     `NotImplementedError`，轮询这条路被 R-5/POLLABLE 与本页共同封死），所以这里把
     「确定接入」留给用户自己按：还没接住时按钮会如实回报"没有待确认的凭据"（可重试），
     接住之后按 = 正常落盘。这是本轮唯一一处"按了可能被业务拒绝"的按钮，理由与处置
     写在已登记缺口 ⑧。 */
  if (st.awaiting || st.kind === "local_callback") parts.push(confirmBlockHTML(st));
  return parts.join("");
}

/* ---------- 登录窗口（弹窗）契约（M7-E 修正轮，2026-10-01 用户裁决）----------
 * 为什么不是 iframe（实测证据，只写事实）：`https://qoder.com/device/selectAccounts`
 *   的响应带 `content-security-policy: … frame-ancestors 'none'` + `x-frame-options:
 *   SAMEORIGIN` → **iframe 永远显示不了该页**（浏览器必定拒绝渲染；qodercn 同族同判）。
 *   其余已实测厂商（workbuddy.ai/.cn、codebuddy.cn、trae.cn、lobsterai）未发框禁头，但
 *   弹窗**对全部厂商一体可用** —— 故本页只做弹窗，不按厂商分叉。
 * 参考实现（只读）：`/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts/
 *   plugin-src/client/jet-hub.js:1318-1345` —— 点击后立刻 `window.open(loginUrl, '_blank',
 *   'width=800,height=600')`；弹窗被拦截（`!loginWindow || loginWindow.closed`）时改为
 *   展示可点击链接，并显式警告**绝不**回退到用 location.href 赋值把整个设置页导航去
 *   外部登录页（那正是其用户报障「主页面直接跳转过去了」的现象），登录完成后也回不来；
 *   完成后 `if (loginWindow && !loginWindow.closed) loginWindow.close()`。ZCode-Panel
 *   （main.js）与 Z-Accounts（lib.rs）用应用内 BrowserWindow / WebviewWindow，同为顶层
 *   窗口、从不用 iframe。
 * 🔴 第三参 features 串（'width=800,height=600'）**不得**带 `noopener`：带 noopener 时
 *   Chrome 的 window.open 返回 null（句柄丢失、成功时关不了窗）；链接侧改用
 *   `rel="noopener noreferrer"` 兜底（见 `loginWindowHTML` 的 `<a>` 的 rel）。 */

/** 打开（或重新打开）官方登录页 —— **单一实现，全部调用点共用**
 *  （`login/start` 响应到达即调 + 面板「重新打开登录页」）。
 *  blocked 态由本函数判定：句柄 falsy 或 `closed` = 被拦截 → 面板切链接态；
 *  **绝不**用 location 赋值导航本管理页（参考实现的警告见上）。 */
export function openLoginWindow(st) {
  const url = winURL(st);
  if (!url) return;
  const w = window.open(url, "_blank", "width=800,height=600");
  if (!w || w.closed) {                            // 被拦截：**不动**旧窗口（若有），链接兜底恒在
    st.winState = "blocked";
    return;
  }
  if (st.win && !st.win.closed) st.win.close();    // 新窗已到手：收回同一向导的旧窗（只留一个）
  st.win = w;
  st.winState = "open";
}

/** 收起登录窗口（两阶段提交**第一段成功**时调，照参考实现 jet-hub.js:1344 的收尾；
 *  也挂在 `stopWizard()` 上：向导关闭 = 放弃本次登录，它开出来的窗口一并收掉）。 */
function closeLoginWindow(st) {
  if (st.win && !st.win.closed) st.win.close();
  st.win = null;
}

/** 登录窗口要打开的地址（空串 = 本形态不开窗口）。
 *  🔴 只认 `http(s)` 真页面，形态判据源是 `WINDOW_KINDS`：`qr` 型的 `url` 是二维码**内容**
 *  （raccoon 的 `/login/mp?code=…`，也可能是 `weixin://`）、`sms_code` 型交互全在本页表单 ——
 *  照搬"url 即网页"的假设会弹出一个不是给浏览器看的东西。 */
function winURL(st) {
  if (!WINDOW_KINDS.has(st.kind)) return "";
  const url = String((st.challenge || {}).url || "");
  return /^https?:\/\//.test(url) ? url : "";
}

/** 登录窗口状态行（面板唯一的"现在什么情况"出口；文案与实际发生过的动作同源）。 */
function winStateText(st, url) {
  if (!st.session) return "尚未打开：点『开始登录』后会自动弹出官方登录页（800×600）。";
  if (st.awaiting) return "登录已完成，登录窗口已收起。";
  if (!url) return "上游未返回登录页地址，本次没有可打开的登录窗口。";
  if (st.winState === "open") return "登录页已在新窗口打开，请在弹出的窗口里完成登录。";
  if (st.winState === "blocked") return "弹窗被拦截 —— 点下方链接打开。";
  return "登录页尚未打开。";
}

/** 「登录窗口」面板（M7-E 修正轮：右侧**不再嵌入**，面板只做三件事）：
 *   (a) 状态行 = 窗口开没开 / 被没被拦（`winStateText`）；
 *   (b) 授权地址 = 可点击链接（target=_blank + rel="noopener noreferrer"）+ 既有复制钮
 *       （`data-copy` 由 `bindWizard` 统一绑定；noopener 在这里给，不在 window.open 的
 *       features 串里给）；
 *   (c) 「重新打开登录页」＝ 再走一次同一个 `openLoginWindow`（窗口被手关/被拦都可用）。
 *  参数段（未建会话）也在位：一行说明点「开始登录」后会发生什么（此时无链接可给）。 */
function loginWindowHTML(st) {
  const url = winURL(st);
  const row = url && !st.awaiting ? `
      <div class="addr-value" style="display:flex;align-items:center;gap:8px;margin-top:8px">
        <a class="mono" href="${esc(url)}" target="_blank" rel="noopener noreferrer"
          style="flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
          title="用新窗口打开登录页">${esc(url)}</a>
        <button class="icon-btn sm" data-copy="${esc(url)}" aria-label="复制登录页地址"
          title="复制地址">${COPY}</button>
      </div>` : "";
  const reopen = url && !st.awaiting ? `
      <div style="margin-top:12px">
        <button class="btn btn-sm" data-wz="reopen">${LINK}重新打开登录页</button>
      </div>` : "";
  return `
    <div style="margin:0 0 12px;border:1px solid var(--border);border-radius:var(--radius-md);padding:12px">
      <div style="font-size:13px;font-weight:700;color:var(--text-soft)">登录窗口</div>
      <p class="form-hint" style="margin:6px 0 0">${esc(winStateText(st, url))}</p>
      ${row}${reopen}
    </div>`;
}

/** 账号标识行（M7-E：系统自动生成并在 `login/start` 响应里回传；用户全程不手填）。 */
function accountLineHTML(st) {
  if (!st.account) return "";
  return `<p class="form-hint" style="margin:8px 0 0">账号标识（系统自动生成）：
    <span class="mono">${esc(st.account)}</span></p>`;
}

/** 待确认接入块（M7-E 两阶段提交的确认步；页脚也有一颗，两处同一处理函数）。
 *  `st.awaiting` = 通道已报 success（按钮即落盘动作）；未 awaiting 时（local_callback 的
 *  自动回跳尚未到达，见 `wizardHTML` 注）文案改为"完成授权后点"，结果一律如实回报。 */
function confirmBlockHTML(st) {
  const hint = st.awaiting
    ? "点确认后凭据才会写入本机账号目录并出现在左侧列表；在此之前关闭窗口不会保存任何东西。"
    : "在登录窗口（弹窗被拦截时用面板里的链接）完成授权后点这颗按钮即可保存；若还没接住，会如实告诉你没有待确认的凭据。";
  return `
    <div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border)">
      <button class="btn btn-primary" data-wz="confirm" ${st.busy ? "disabled" : ""}>确定接入</button>
      <p class="form-hint" style="margin:8px 0 0">${esc(hint)}</p>
    </div>`;
}

/** 设备码 / 二维码两型的页内展示物（`Challenge`：device_code / qr_payload）。
 *  授权地址（含复制与打开）自 M7-E 修正轮起归「登录窗口」面板，本函数不再重复渲染；
 *  上游没给地址的场合同样由面板状态行如实说明（`winStateText`），这里不再出占位句。 */
function linkHTML(st, c) {
  if (st.kind === "qr") return qrHTML(c);
  if (st.kind === "device_code" && c.device_code) return `
    <div class="form-row"><label>设备码（在登录窗口的登录页里核对后填入）</label>
      <div class="addr-value" style="display:flex;align-items:center;gap:8px">
        <span class="mono" style="flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:15px;font-weight:700">${esc(c.device_code)}</span>
        <button class="icon-btn sm" data-copy="${esc(c.device_code)}" aria-label="复制设备码"
          title="复制设备码">${COPY}</button>
      </div></div>`;
  return "";
}

/** 二维码（M7-C1）：`qr_payload` = **服务端出的图片 data URI** → `<img>`；`url` = 二维码内容
 *  （raccoon 那条 `/login/mp?code=…`）或官方图片地址（loomy），**始终并排给出**：
 *  这台设备扫不了时复制给能扫的设备。
 *
 *  🔴 只有 `data:image` 开头的载荷才画 `<img>`。旧实现把上游**图片地址**直接塞进
 *  `src="{url}"`（loomy：`open.weixin.qq.com/connect/qrcode/<uuid>`）——那张图必须由网关
 *  带着铸出 uuid 的 UA + Referer 才取到，浏览器跨域带不上这两个头，结果就是一张
 *  永远加载失败的图（本轮修的就是它，改判据见 `accounts/qr.py` / `upstream/loomy/wechat.py`）。
 *  ⚠️ 拿不到图（上游图片端点抖动 / 本产品未出图）时**不画空 `<img>`**：如实说明 + 给文字载荷。
 */
function qrHTML(c) {
  const image = String(c.qr_payload || "");
  const text = String(c.url || "");
  const parts = [];
  if (image.startsWith("data:image")) {
    parts.push(`
    <div style="display:flex;justify-content:center;padding:4px 0 12px">
      <img data-wz="qr-img" src="${esc(image)}" alt="登录二维码" width="200" height="200"
        style="border:1px solid var(--border);border-radius:var(--radius-md);background:var(--surface);padding:8px">
    </div>`);
  } else {
    parts.push(`
    <p class="form-hint" style="margin-bottom:8px">本次没有拿到二维码图片（原因见下方状态行，
      可点「重新发起登录」再要一张）。</p>`);
  }
  if (text) {
    parts.push(`
    <div class="form-row"><label>二维码内容（扫不了这台设备时复制过去）</label>
      <div class="addr-value" style="display:flex;align-items:center;gap:8px">
        <span class="mono" style="flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(text)}">${esc(text)}</span>
        <button class="icon-btn sm" data-copy="${esc(text)}" aria-label="复制二维码内容"
          title="复制内容">${COPY}</button>
      </div></div>`);
  }
  if (!text && !image.startsWith("data:image")) return `<p class="form-hint">上游未返回二维码展示物。</p>`;
  return parts.join("");
}

/** local_callback：BD4 接收端已落地 → **自动回跳是主路径**，粘贴框留作兜底（不轮询）。
 *  ⚠️ `login/start` 不回传监听绑定结果（已登记缺口），故文案说"没反应就用兜底"，
 *  不说"一定能接住"。M7-E 修正轮：授权页在**弹窗**打开（地址与「重新打开」在
 *  「登录窗口」面板里），本段只留粘贴兜底。 */
function callbackHTML() {
  return `
    <div class="form-row"><label for="ac-cb-url">兜底：回跳地址（整串粘贴）</label>
      <textarea id="ac-cb-url" placeholder="浏览器完成授权后自动回跳本机接收端；没接住时，把地址栏整串粘贴到这里提交"></textarea></div>
    <button class="btn btn-primary" data-wz="callback">提交回跳地址</button>
    <p class="form-hint" style="margin-top:8px">主路径是自动回跳：网关在发起登录时已为本会话绑定本机端口，
      授权完成后浏览器回跳到该端口即直接完成登录并进入待确认。
      只有当端口没绑定成功（被占用 / 权限不足，后端 login.py 会记日志）时才需要下面这个粘贴框。</p>`;
}

/** 短信两段：手机号 → `alt sms_send` → 验证码 → `alt sms_submit`（不轮询）。 */
function smsHTML(st) {
  if (!st.smsSent) return `
    <div class="form-row"><label for="ac-phone">手机号</label>
      <input id="ac-phone" inputmode="numeric" maxlength="11" placeholder="11 位手机号"
        value="${esc(st.phone || "")}"></div>
    <button class="btn btn-primary" data-wz="sms-send">${PHONE}发送验证码</button>
    <p class="form-hint" style="margin-top:8px">短信通道若要求图形验证码（滑块），本向导未内置——请改用主形态登录。</p>`;
  return `
    <div class="form-row"><label for="ac-phone">手机号</label>
      <input id="ac-phone" inputmode="numeric" maxlength="11" value="${esc(st.phone || "")}" disabled></div>
    <div class="form-row"><label for="ac-sms">短信验证码</label>
      <input id="ac-sms" inputmode="numeric" maxlength="8" placeholder="验证码"></div>
    <div style="display:flex;gap:8px">
      <button class="btn btn-primary" data-wz="sms-submit">提交验证码</button>
      <button class="btn" data-wz="sms-send">重新发送</button>
    </div>`;
}

function alertHTML(s) {
  const cls = s.tone === "failed" ? "alert-err" : s.tone === "warn" ? "alert-warn" : "alert-info";
  return `
    <div class="alert ${cls}" style="margin-top:12px">
      <div class="alert-title">${esc(s.title || "")}</div>
      ${s.text ? `<div>${esc(s.text)}</div>` : ""}
      ${s.tone === "failed" ? `<button class="btn btn-sm" data-wz="restart" style="margin-top:8px">重新发起登录</button>` : ""}
    </div>`;
}

/** 每种形态的「下一步做什么」导语（纯用户指引，不改后端语义；M7-E 修正轮同步弹窗布局）。 */
function guideText(st) {
  switch (st.kind) {
    case "device_code":
      return st.challenge.device_code
        ? "已生成设备码：把设备码填入登录窗口里的登录页并确认，本页会自动轮询登录结果。"
        : "已生成授权地址：在登录窗口里完成授权，本页会自动轮询登录结果。";
    case "external_link":
      return "已生成授权地址：在登录窗口里完成登录，本页会自动轮询登录结果。";
    case "qr":
      return "请用手机扫码本页的二维码完成授权，本页会自动轮询登录结果；"
        + "这张码失效或你在手机侧撤掉授权时，服务端会换发一张新的，本页跟着换图。";
    case "local_callback":
      return "请在登录窗口里完成授权：回跳会被本机接收端接住并结束登录。"
        + "若一会儿没有反应（接收端没绑定成功），把地址栏整串粘贴到下方兜底框提交。";
    case "sms_code":
      return "先点『发送验证码』，收到短信后填入验证码完成登录。";
    default:
      return "请按上方指引完成登录。";
  }
}

/** 绑定一个作用域里的向导控件（M7-E：`scope` 参数化 —— 全量重绘绑 body；
 *  `paintStatus` 只重绑状态格子树，避免为一次状态文案变化重建整个正文）。 */
function bindWizard(st, scope, paint) {
  scope.querySelectorAll("[data-copy]").forEach((b) =>
    b.onclick = () => copyText(b.dataset.copy));
  scope.querySelectorAll("[data-kind]").forEach((b) => {
    b.onclick = () => {
      if (b.disabled || st.session) return;      // 会话已建 = 形态锁定（换形态要另起会话）
      st.kind = b.dataset.kind;
      paint();
    };
  });
  scope.querySelectorAll("[data-wz]").forEach((b) => {
    const act = b.dataset.wz;
    if (act === "start") b.onclick = () => startKind(st);
    else if (act === "callback") b.onclick = () => submitCallback(st, scope);
    else if (act === "sms-send") b.onclick = () => smsSend(st, scope);
    else if (act === "sms-submit") b.onclick = () => smsSubmit(st, scope);
    else if (act === "restart") b.onclick = () => startKind(st);
    else if (act === "reopen") b.onclick = () => { openLoginWindow(st); st.paint(); };
    else if (act === "confirm") b.onclick = () => confirmCommit(st);
    // 图片是服务端给的 data URI（不发跨域请求），所以只有载荷本身坏了才会走到这里
    else if (act === "qr-img") b.onerror = () => toast("二维码图片解码失败（上游返回的内容不是图片）", "err");
  });
  const phoneEl = scope.querySelector("#ac-phone");
  if (phoneEl && !phoneEl.disabled) phoneEl.oninput = () => { st.phone = phoneEl.value.trim(); };
}

/** 只换状态格 + 页脚（M7-E 轮询期专用）：绝不整段重绘 —— 每 2 秒重建整个 body
 *  只会闪烁（qr 型还会把同一张 data URI 图重新解码），用户正在看的其它格不需要动。 */
function paintStatus(st) {
  const holder = st.bodyEl && st.bodyEl.querySelector("#ac-wz-status");
  if (!holder) { st.paint(); return; }          // 结构不在（异常态）→ 退回整段重绘兜底
  holder.innerHTML = st.status ? alertHTML(st.status) : "";
  bindWizard(st, holder, st.paint);             // 只重绑这一格（「重新发起登录」钮在 alert 里）
  const ttlCell = st.bodyEl.querySelector('[data-wz="ttl"]');
  if (ttlCell) ttlCell.textContent = ttlText(st);
  paintFooter(st);
}

async function submitCallback(st, body) {
  const url = (body.querySelector("#ac-cb-url")?.value || "").trim();
  if (!url) { toast("请先粘贴回跳地址", "err"); return; }
  st.status = { title: "提交中", text: "正在校验回跳地址并换取凭据…", tone: "info" };
  st.paint();
  try {
    const r = await POST("/admin/api/accounts/login/callback",
      { product: st.p.id, session: st.session, params: { url } });
    await settle(st, r);
  } catch (e) {
    st.status = { title: "提交失败", text: e.message, tone: "failed" };
    st.paint();
  }
}

async function smsSend(st, body) {
  const phone = (body.querySelector("#ac-phone")?.value || st.phone || "").trim();
  if (!/^1[3-9]\d{9}$/.test(phone)) { toast("请输入 11 位有效手机号", "err"); return; }
  st.phone = phone;
  st.status = { title: "下发中", text: "正在请求上游下发短信验证码…", tone: "info" };
  st.paint();
  try {
    const r = await POST("/admin/api/accounts/login/alt",
      { product: st.p.id, session: st.session, name: "sms_send", args: { phone } });
    st.smsSent = true;
    if (r.kind === "challenge") {
      st.challenge = r.challenge || {};
      st.status = { title: "验证码已下发", text: "请输入收到的短信验证码完成登录。", tone: "info" };
    } else {
      /* 两形态并存是产品面既定差异（raccoon 回 Challenge / loomy 回 LoginOutcome）；
         pending 是业务状态而非故障（R-6），原文展示。 */
      st.status = { title: r.state === "pending" ? "待继续" : "结果", text: r.detail || "", tone: "info" };
    }
  } catch (e) {
    st.smsSent = false;
    st.status = { title: "验证码发送失败", text: e.message, tone: "failed" };
  }
  st.paint();
}

async function smsSubmit(st, body) {
  const code = (body.querySelector("#ac-sms")?.value || "").trim();
  if (!code) { toast("请输入短信验证码", "err"); return; }
  st.status = { title: "提交中", text: "正在校验验证码…", tone: "info" };
  st.paint();
  try {
    const r = await POST("/admin/api/accounts/login/alt",
      { product: st.p.id, session: st.session, name: "sms_submit", args: { sms_code: code } });
    if (r.kind === "outcome") return await settle(st, r);
    st.status = { title: "待继续", text: r.detail || "请继续按上游指引操作。", tone: "info" };
  } catch (e) {
    st.status = { title: "提交失败", text: e.message, tone: "failed" };
  }
  st.paint();
}

/** 登录终点统一处置（poll / callback / alt 三通道同形：`{state, detail, account}`）。
 *
 * 🔴 M7-E 两阶段提交：`success` 只表示"凭据已认领并**暂存**在服务端会话上"（未落盘）——
 * 界面进入「已登录，待确认接入」，**不刷新列表、不报"已接入"**；账号要等用户点
 * 「确定接入」→ `login/commit` 回 `committed:true` 才真正出现（列表来自磁盘）。
 */
export async function settle(st, r) {
  if (r.state === "success") {
    st.awaiting = true;                 // 待确认接入：页脚与正文都出「确定接入」
    st.account = r.account || st.account;
    if (st.pollTimer) { clearInterval(st.pollTimer); st.pollTimer = null; }
    closeLoginWindow(st);               // 照参考实现（jet-hub.js:1344）：登录完成即收起弹窗
    st.status = {
      title: "已登录，待确认接入",
      text: `凭据已获取${st.account ? `（账号标识：${st.account}）` : ""}；` +
        "点「确定接入」写入本机账号目录后，才会出现在左侧列表。",
      tone: "info",
    };
    st.paint();
    return;
  }
  const pending = r.state === "pending";            // pending 不是失败（§22.3）
  st.status = {
    title: pending ? "待继续" : r.state === "expired" ? "会话已到期" : "登录失败",
    text: r.detail || (pending ? "等待用户完成操作…" : ""),
    tone: pending ? "info" : "failed",
  };
  st.paint();
}

/** 「确定接入」（M7-E 两阶段提交第二段）：`login/commit` → **真落盘才报成功**。
 *  🔴 结果如实转述：`committed:false` 时把后端给的 reason 原样展示（写回自检失败 /
 *  会话已过期 / 已确认过……），**不弹绿色 toast、不关窗**（可能只是要重试或重新登录）。 */
async function confirmCommit(st) {
  if (!st || !st.session || st.busy) return;
  st.busy = true;
  st.status = { title: "正在保存", text: "正在把凭据写入本机账号目录（含写回自检）…", tone: "info" };
  st.paint();
  let r = null;
  try {
    r = await POST("/admin/api/accounts/login/commit", { product: st.p.id, session: st.session });
  } catch (e) {
    st.busy = false;
    st.status = { title: "保存失败", text: `提交确认请求失败：${e.message}`, tone: "failed" };
    st.paint();
    toast("保存失败：" + e.message, "err");
    return;
  }
  if (r && r.committed) {
    const pid = st.p.id, name = r.account || st.account, title = st.p.title;
    st.session = "";                    // 已确认落盘 → 关窗时不再发 cancel
    stopWizard();                       // 生命周期唯一所有者（onClose 里的 `wizard === st` 已不成立）
    toast(`账号 ${name} 已接入 ${title}`, "ok");
    await refreshAfter(pid, name);
    return;
  }
  st.busy = false;
  const why = (r && (r.reason || r.detail)) || "后端未确认落盘（凭据未写入）";
  st.status = { title: "未确认落盘", text: why, tone: "failed" };
  st.paint();
  toast("未保存：" + why, "err");
}

/** 轮询响应带回的 challenge：**只在内容真的变了时才换**（服务端换发新二维码的场景）。
 *
 * 上游判旧码作废（raccoon `canceled` / 微信 402·403）时，产品会就地换发一张新码并把新
 * `Challenge` 写回会话，入口层在 `login/poll` 的响应里带回它（`admin_accounts.py::login_poll`）
 * → 界面据此换图，用户不必再手点一次「重新发起登录」。未换发时带回的那份与 start 给的
 * 逐字节相同，比对后不重绘（每 2 秒重绘一次会打断复制选区，也与 §4-2 的三级重绘纪律相悖）。
 * ⚠️ 刻意只比 `qr_payload` / `url` 两个展示物：challenge 里没有别的会变的字段。
 */
function adoptChallenge(st, next) {
  if (!next || typeof next !== "object") return false;
  const cur = st.challenge || {};
  const changed = String(next.qr_payload || "") !== String(cur.qr_payload || "")
    || String(next.url || "") !== String(cur.url || "");
  if (!changed) return false;
  st.challenge = next;
  return true;
}

/** 轮询一次（仅 POLLABLE 形态调用；`pending` 原样展示 `detail`，不作失败计数）。
 *  🔴 M7-E：轮询期的状态更新一律走 `paintStatus()`（只换状态格 + 页脚）——
 *  整段 `paint()` 每 2 秒重建整个 body 只会闪烁（还会打断用户正在进行的复制选区）。 */
async function pollOnce(st) {
  if (wizard !== st || !st.session || st.busy) return;    // 向导已被关闭/替换：本 tick 直接放弃
  st.busy = true;
  try {
    const r = await POST("/admin/api/accounts/login/poll",
      { product: st.p.id, session: st.session });
    st.fails = 0;
    const reissued = adoptChallenge(st, r.challenge);     // 服务端换发了新码？
    if (r.state === "pending") {
      st.status = {
        title: reissued ? "已换发新二维码" : "等待中",
        text: r.detail || "等待用户完成授权…",
        tone: "info",
      };
      if (reissued) st.paint();                           // 换码要重画二维码（结构性变化）
      else st.paintStatus();                              // 只有状态变了：整段重绘没必要
      return;
    }
    if (reissued) st.paint();                             // 终态前也让用户看见最后一张图
    await settle(st, r);                                  // 终态（success/failed/expired）
  } catch (e) {
    st.fails += 1;
    if (st.fails >= POLL_MAX_FAILS) {
      clearInterval(st.pollTimer); st.pollTimer = null;
      st.status = { title: "轮询已停止", text: `连续 ${st.fails} 次轮询失败：${e.message}`, tone: "failed" };
    } else {
      st.status = { title: "等待中", text: `轮询失败（第 ${st.fails} 次，将重试）：${e.message}`, tone: "info" };
    }
    st.paintStatus();
  } finally {
    st.busy = false;
  }
}

