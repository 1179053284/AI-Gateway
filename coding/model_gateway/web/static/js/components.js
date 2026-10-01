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

/* ---------- 弹窗（宽大方：modal-wide 800px）---------- */
export function modal({ title, body, footer, wide = false, onClose }) {
  const root = document.getElementById("modal-root");
  const mask = document.createElement("div");
  mask.className = "modal-mask";
  mask.innerHTML = `
    <div class="modal${wide ? " wide" : ""}">
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
