/** 公共组件：弹窗 / toast / 无边框 tab / 开关（design-spec §1.3）。 */

import { esc } from "./api.js";

/* ---------- toast ---------- */
export function toast(msg, type = "") {
  const wrap = document.getElementById("toast-wrap");
  const el = document.createElement("div");
  el.className = "toast " + type;
  el.textContent = msg;
  wrap.appendChild(el);
  setTimeout(() => el.remove(), type === "err" ? 6000 : 3000);
}

/** 结果浮层（富 toast）：标题 + 计数行 + 逐条明细 + 手动关闭，`ms` 后自动消失。
 *  🔴 2026-10-03 用户裁定「各类处理结果，不允许用这种形式固化显示。执行完毕，弹窗提示具体执行结果，
 *  3s 后自动消失，也可以手动关闭」⇒ 批量动作的结果不再往面板里写一块常驻"回执区"：
 *  ① 它是**浮层**，与 `toast()` 同一个载体（`#toast-wrap`），不新增第二种提示位置；
 *  ② 它**不是 modal** ⇒ 旧实现里"等待期用户已开弹窗 ⇒ 迟到回执只能塞就地槽"那条判遮罩的构造性
 *     权衡整族作废，单层弹窗红线（`.modal-mask` ∈ {0,1}）由构造保证而不是由分支保证；
 *  ③ 权威状态在表里（回执发出前已按服务端重取过视图），浮层只说"这一批发生了什么"
 *     ⇒ **3 秒读不完的内容不许放正文**（术语解释挂计数行悬停）。
 * `html` 由调用方拼（`.t-sum` / `.t-rows` / `.t-row`，值一律先 `esc`），本函数只管载体、时长与关闭。 */
export function toastCard(title, html, { type = "", ms = 3000 } = {}) {
  const wrap = document.getElementById("toast-wrap");
  if (!wrap) return;
  const el = document.createElement("div");
  el.className = `toast card${type ? " " + type : ""}`;
  el.setAttribute("role", "status");
  el.innerHTML = `<div class="t-head"><b class="t-title">${esc(title)}</b>`
    + `<button class="t-close" type="button" aria-label="关闭提示">`
    + `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>`
    + `</button></div><div class="t-body"></div>`;
  el.querySelector(".t-body").innerHTML = html;
  const kill = () => { if (el.isConnected) el.remove(); };
  el.querySelector(".t-close").onclick = kill;
  wrap.appendChild(el);
  setTimeout(kill, ms);
}

/* ---------- 弹窗（宽大方：modal-wide 800px）---------- */
export function modal({ title, body, footer, wide = false, cls = "", onClose }) {
  const root = document.getElementById("modal-root");
  const mask = document.createElement("div");
  mask.className = "modal-mask";
  mask.innerHTML = `
    <div class="modal${wide ? " wide" : ""}${cls ? " " + cls : ""}">
      <div class="modal-head"><h3>${esc(title)}</h3>
        <button class="modal-close" aria-label="关闭"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg></button></div>
      <div class="modal-body"></div>
      ${footer ? `<div class="modal-foot"></div>` : ""}
    </div>`;
  mask.querySelector(".modal-body").append(body);
  if (footer) {
    /* footer 子节点平铺进 .modal-foot：让 flex gap 8px 直接分隔按钮
       （原实现整个 footer div 被 append，按钮挤在中间层里贴在一起——2026-09-06 用户指出） */
    const footEl = mask.querySelector(".modal-foot");
    while (footer.firstChild) footEl.append(footer.firstChild);
  }
  const close = () => { mask.remove(); onClose && onClose(); };
  mask.querySelector(".modal-close").onclick = close;
  mask.addEventListener("mousedown", (e) => { if (e.target === mask) close(); });
  root.appendChild(mask);
  return { close, el: mask };
}

/* ---------- 确认弹窗 ---------- */
export function confirmDialog(title, text, danger = true) {
  return new Promise((resolve) => {
    // 🔴 答复必须由**三条关闭通道**共同给出（S-61）：`modal()` 自带 ✕（`.modal-close`）与
    //    遮罩 mousedown 两条**不经过按钮**的关闭路径，旧写法只在「取消」「确定」上 resolve ——
    //    用户点 ✕ 或点空白处时 promise 永不 settle，`if (!await confirmDialog(...)) return;`
    //    的调用方永久挂住：弹窗没了、后面的代码再也不执行，界面上看不出任何异常。
    let answered = false;
    const settle = (v) => { if (answered) return; answered = true; resolve(v); };
    const body = document.createElement("div");
    body.innerHTML = `<p>${esc(text)}</p>`;
    const foot = document.createElement("div");
    foot.innerHTML = `<button class="btn">取消</button>
      <button class="btn ${danger ? "btn-danger" : "btn-primary"}">确定</button>`;
    const [cancel, ok] = foot.querySelectorAll("button");
    // ✕ / 遮罩 = 用户没做选择 = **取消**（绝不能当成「确定」去触发破坏性动作）
    const m = modal({ title, body, footer: foot, onClose: () => settle(false) });
    // 先给答复再关：`m.close()` 会**同步**回调 `onClose`，顺序颠倒则「确定」被
    // onClose 的 false 抢先定掉 —— 按钮分支就此失效（变异表里有一条专门钉这个顺序）
    cancel.onclick = () => { settle(false); m.close(); };
    ok.onclick = () => { settle(true); m.close(); };
  });
}

/* ---------- 无边框 tab ---------- */
export function tabBar(tabs, active, onSwitch) {
  const el = document.createElement("div");
  el.className = "tabs";
  for (const t of tabs) {
    const b = document.createElement("button");
    b.className = "tab" + (t.id === active ? " active" : "");
    b.textContent = t.label;
    b.onclick = () => {
      el.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      onSwitch(t.id);
    };
    el.appendChild(b);
  }
  return el;
}

/* ---------- 开关 ---------- */
export function switchEl(on, onToggle) {
  const el = document.createElement("button");
  el.className = "switch" + (on ? " on" : "");
  el.onclick = async () => {
    const next = !el.classList.contains("on");
    const ok = onToggle ? await onToggle(next, el) : true;
    if (ok !== false) el.classList.toggle("on", next);
  };
  return el;
}

/* ---------- 复制到剪贴板 ---------- */
export function copyText(text, okMsg = "已复制") {
  navigator.clipboard?.writeText(text).then(
    () => toast(okMsg, "ok"), () => toast("复制失败", "err"));
}

/* ---------- 子侧栏拖拽调宽（双面板页三处共用，frontend-spec §3.1） ----------
 * 宽度经 `--rail-w` 变量下发（base.css `.subnav { width: var(--rail-w, …) }`），
 * **不用 aside.style.width**——内联值会压死 ≤768 条带的 `width:100%` 媒体规则。
 * handle 是 aside 的兄弟节点：5px + `margin-right:-5px` 吃掉主区左内衬——
 * 零布局位移，且不覆盖 aside 右缘的 4px 滚动条（压上就抓不到滚动条了）。
 * 宽按页持久化（mgw-railw-<key>）：本页交互全部重绘 innerHTML，不存就每次归零。
 * 窗口变窄的兜底不在这里：base.css 的 `max-width: calc(100% - 360px)` 是布局级钳制
 * （任何缩放即时生效，且拖拽值保留——窗口回宽后回弹；JS 侧若监听 resize 复钳，
 * 事件时读到的 clientWidth 可能是旧视口，钳制会静默放过——实测教训）。 */
const RAIL_MIN = 150, RAIL_MAX = 560, RAIL_KEEP = 360;   // 栏下限 / 上限 / 主区最低保留

function railClamp(w, wrap) {
  const max = Math.max(RAIL_MIN, Math.min(RAIL_MAX, wrap.clientWidth - RAIL_KEEP));
  return Math.min(max, Math.max(RAIL_MIN, w));
}

export function initSplitResize(root, key) {
  const wrap = root.querySelector(".panel-split");
  const aside = wrap && wrap.querySelector("aside.subnav");
  if (!wrap || !aside) return;
  /* vm 假 DOM（验收门脚本）无 CSSOM / after()：跳过接线。真浏览器判据在 CDP 真机侧。 */
  if (!wrap.style || typeof wrap.style.setProperty !== "function"
      || typeof aside.after !== "function") return;
  const storeKey = `mgw-railw-${key}`;
  const apply = (w) => wrap.style.setProperty("--rail-w", Math.round(w) + "px");
  let saved = NaN;
  try { saved = parseInt(localStorage.getItem(storeKey) || "", 10); } catch { /* 无存储 */ }
  if (Number.isFinite(saved)) apply(railClamp(saved, wrap));

  const handle = document.createElement("div");
  handle.className = "split-handle";
  handle.setAttribute("role", "separator");
  handle.setAttribute("aria-orientation", "vertical");
  handle.setAttribute("aria-label", "拖动调整侧栏宽度");
  handle.title = "拖动调整宽度";
  aside.after(handle);

  let startX = 0, startW = 0;
  handle.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    startX = e.clientX;
    startW = aside.getBoundingClientRect().width;
    handle.setPointerCapture(e.pointerId);
    document.body.classList.add("rail-resizing");
    e.preventDefault();
  });
  handle.addEventListener("pointermove", (e) => {
    if (!handle.hasPointerCapture(e.pointerId)) return;
    apply(railClamp(startW + e.clientX - startX, wrap));
  });
  const done = (e) => {
    if (!handle.hasPointerCapture(e.pointerId)) return;
    handle.releasePointerCapture(e.pointerId);
    document.body.classList.remove("rail-resizing");
    try {
      localStorage.setItem(storeKey, String(Math.round(aside.getBoundingClientRect().width)));
    } catch { /* 记不住不影响本页功能 */ }
  };
  handle.addEventListener("pointerup", done);
  handle.addEventListener("pointercancel", done);
}

/* ---------- 简易分页（样式类 .pager，base.css v2.0）---------- */
export function pagination(total, offset, limit, onPage) {
  const el = document.createElement("div");
  el.className = "pager";
  const pages = Math.max(1, Math.ceil(total / limit));
  const cur = Math.floor(offset / limit) + 1;
  const mk = (label, off, disabled) => {
    const b = document.createElement("button");
    b.className = "btn btn-sm"; b.textContent = label; b.disabled = disabled;
    b.onclick = () => onPage(off);
    return b;
  };
  el.appendChild(mk("‹", Math.max(0, offset - limit), cur <= 1));
  const info = document.createElement("span");
  info.textContent = `${cur} / ${pages}（共 ${total} 条）`;
  el.appendChild(info);
  el.appendChild(mk("›", Math.min((pages - 1) * limit, offset + limit), cur >= pages));
  return el;
}
