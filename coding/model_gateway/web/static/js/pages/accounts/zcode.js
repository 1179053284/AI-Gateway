/** ZCode 导入账号 + 小店购买子模块（D-1/D-4 拆分第二步，2026-10-06）——从 accounts.js 物理移出。
 * 共享状态经 accounts/state.js（live binding 读 + setXxx 写）。 */
import { GET, POST, esc } from "../../api.js";
import { modal, confirmDialog, toast, toastCard, copyText, initSplitResize } from "../../components.js";
import { rootEl } from "./state.js";

/* ---------- ZCode 专属：导入账号与购买账号（YouYu Shop）----------
 * 契约（后端随本轮落地，前端按冻结 payload 实现，不预判字段；两颗入口只在 `p.id === Z_PRODUCT` 的卡头渲染）：
 *   GET  /admin/api/zcode/import/sources → {panel:{root,exists,accounts:[{name,device_mid,already_imported}]}, switch:{同形}}
 *   POST /admin/api/zcode/import         {source:"panel"|"switch"|"payload", account?, payload?, reuse?, regenerate?}
 *        → 200 {status:"ok",account,device_id,message} ｜ 409 {error,conflict,conflict_with,account,hint} ｜ 400 {error}
 *   GET  /admin/api/zcode/shop/items     → {items:[{id,title,price,note,listed,stock,validity}]}
 *   POST /admin/api/zcode/shop/buy       {itemId,qty} → {orderId,orderToken,payPath,payTypeName,…}
 *   GET  /admin/api/zcode/shop/order?orderId=&token= → {status,expired,note,amount,reallyPrice,payTypeName,payPath,deliveredAt?,accounts?|account?}
 * 交互纪律：
 *   · 409 设备身份冲突**绝不自动选**：弹窗把「复用其身份 / 重新生成」说清，用户按了才带
 *     `reuse` / `regenerate` 二次提交，成功/失败落点与首次导入同一套（attempt 由调用方给）；
 *   · 弹窗正文 = 分段 tab 两页（照 ZCode Panel 形式）：「商品」默认页（价格右置 / `validity`
 *     额度条 / 数量+下单 / 售罄徽章）与「我的订单」（商品标题+状态 / 单号+时间+实付）；
 *   · 订单轮询 2500ms 一条 timer：终态（delivered/failed/expired）即停、无在飞单即清、关窗即清，
 *     生命周期唯一所有者 = `stopZShop()`（照 `stopWizard()` 口径）；轮询不做人为超时。
 *   · 订单台账只存 `{orderId, token, title?, ts?}`（localStorage `mgw.zshop.orders`，上限 5 条；
 *     失败/超时出表、已到账保留以便回来再导）—— 凭据内容一个字节都不进浏览器存储；
 *   · 一切失败展示**响应里的原因**（api.js 的统一错误提取），不写裸「失败」。
 */
export const Z_PRODUCT = "zcode";               // 两颗入口的唯一门控（只有 ZCode 有本机工具与一元小店）
const ZSHOP_STORE = "mgw.zshop.orders";
const ZSHOP_STORE_MAX = 5;
const ZSHOP_POLL_MS = 2500;
export let zshop = null;                        // 购买账号弹窗会话 —— **只有 stopZShop() 置空**

/* ---------- 导入账号（ZCode 专属） ---------- */

/** 导入账号弹窗：打开即读 `import/sources`（本机两工具的账号目录），三段式（粘贴 JSON / 本机工具 / 选文件）。 */
export async function openZImport(root) {
  const body = document.createElement("div");
  body.innerHTML = `<div class="loading">正在读取本机 ZCode 工具的账号…</div>`;
  const foot = document.createElement("div");
  foot.innerHTML = `<button class="btn">关闭</button>`;
  const closeBtn = foot.querySelector(".btn");     // modal() **之前**取（footer 子节点会被平铺搬走，§7.11）
  const dlg = modal({ title: "导入账号 · ZCode", body, footer: foot });
  closeBtn.onclick = dlg.close;
  let src = null;
  try {
    src = await GET("/admin/api/zcode/import/sources");
  } catch (e) {
    body.innerHTML = `
      <div class="alert alert-err"><div class="alert-title">账号来源读取失败</div>
        <div>${esc(e.message)}</div></div>`;
    return;
  }
  body.innerHTML = zImportHTML(src);
  bindZImport(root, body);
}

function zImportHTML(src) {
  return `
    <div id="ac-zimp-err"></div>
    <div class="sec-head"><span class="t">粘贴 JSON</span><span class="d">单个账号的凭据 JSON</span></div>
    <div class="form-row"><label for="ac-zimp-json">账号 JSON</label>
      <textarea id="ac-zimp-json" placeholder="把账号凭据 JSON 整段粘贴到这里（从 ZCode 工具复制，或从购买账号订单里复制）"></textarea></div>
    <div style="margin-bottom:12px"><button class="btn btn-primary" data-z="paste">导入</button></div>
    <div class="sec-head"><span class="t">从本机工具导入</span><span class="d">扫描本机 ZCode 工具的账号目录</span></div>
    <div id="ac-zimp-src">${zSourcesHTML(src)}</div>
    <div class="sec-head" style="margin-top:12px"><span class="t">选择文件</span><span class="d">单个账号凭据 .json 文件</span></div>
    <div class="form-row" style="margin-bottom:0"><label for="ac-zimp-file">凭据文件</label>
      <input type="file" id="ac-zimp-file" accept=".json,application/json"></div>`;
}

/** 两个本机工具各一组：组头行（工具名 + 目录在不在 + 路径 mono 截断）+ 逐账号行。 */
function zSourcesHTML(src) {
  const groups = [["panel", "ZCode-Panel", src && src.panel], ["switch", "zcode-switch", src && src.switch]];
  return `<div class="list-card" style="margin-bottom:0">${groups.map(([key, label, g]) => zSourceGroupHTML(key, label, g)).join("")}</div>`;
}

function zSourceGroupHTML(key, label, g) {
  const grp = g || {};
  const rows = (grp.accounts || []).map((a) => zSourceRowHTML(key, a));
  return `
    <div class="list-row">
      <span style="display:flex;align-items:center;gap:8px;min-width:0">
        <b>${esc(label)}</b>
        <span class="badge ${grp.exists ? "b-ok" : "b-gray"}">${grp.exists ? "已找到" : "未找到"}</span>
      </span>
      <span class="mono" style="margin-left:auto;font-size:12px;color:var(--text-faint);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:55%"
        title="${esc(grp.root || "")}">${esc(grp.root || "—")}</span>
    </div>
    ${rows.length ? rows.join("")
      : `<div class="list-row"><span class="form-hint" style="margin:0">${esc(grp.exists === false ? "本机没有这个工具，或还没有账号目录。" : "目录里没有读到账号。")}</span></div>`}`;
}

/** 账号行：名称 + 设备身份（small mono）+ 槽位（已导入徽章／导入钮；行内结果就落在这个槽里）。 */
function zSourceRowHTML(key, a) {
  const name = String(a.name || "");
  const slot = a.already_imported
    ? `<span class="badge b-ok">已导入</span>`
    : `<button class="btn btn-sm" data-z="row" data-src="${esc(key)}" data-acc="${esc(name)}">导入</button>`;
  return `
    <div class="list-row">
      <span style="min-width:0;flex:1">
        <b class="mono">${esc(name)}</b>
        ${a.device_mid ? `<span class="mono" style="display:block;font-size:12px;color:var(--text-faint);margin-top:4px">${esc(a.device_mid)}</span>` : ""}
      </span>
      <span style="display:inline-flex;align-items:center">${slot}</span>
    </div>`;
}

function bindZImport(root, body) {
  const errEl = body.querySelector("#ac-zimp-err");
  const setErr = (msg) => {
    if (errEl) errEl.innerHTML = msg
      ? `<div class="alert alert-err" style="margin-bottom:12px"><div class="alert-title">导入未完成</div><div>${esc(msg)}</div></div>`
      : "";
  };
  /** 成功统一落点：toast + 行内徽章（可选）+ 本页数据重取（D3：列表面以服务端为准）。 */
  const onOk = async (r, rowBtn) => {
    setErr("");
    if (rowBtn && rowBtn.replaceWith) {
      const badge = document.createElement("span");
      badge.className = "badge b-ok";
      badge.textContent = "已导入";
      rowBtn.replaceWith(badge);
    }
    await zImportSucceed(r);
  };
  const ta = body.querySelector("#ac-zimp-json");
  const pasteBtn = body.querySelector('[data-z="paste"]');
  if (pasteBtn) pasteBtn.onclick = async () => {
    const raw = ((ta && ta.value) || "").trim();
    if (!raw) { setErr("先粘贴账号 JSON"); return; }
    let payload;
    try {
      payload = JSON.parse(raw);
    } catch (e) {
      setErr("JSON 解析失败：" + e.message);      // 客户端就拦下：整段文本不是 JSON
      return;
    }
    pasteBtn.disabled = true;
    try { await zImportFlow({ source: "payload", payload }, (r) => onOk(r), setErr, errEl); }
    finally { pasteBtn.disabled = false; }
  };
  const fileEl = body.querySelector("#ac-zimp-file");
  if (fileEl) fileEl.onchange = async () => {
    const f = fileEl.files && fileEl.files[0];
    fileEl.value = "";                            // 复位：同一个文件再选一次也能触发 change
    if (!f) return;
    let payload;
    try {
      payload = JSON.parse(await f.text());
    } catch (e) {
      setErr(`文件 ${f.name} 读取或解析失败：` + e.message);
      return;
    }
    await zImportFlow({ source: "payload", payload }, (r) => onOk(r), setErr, errEl);
  };
  for (const b of body.querySelectorAll('[data-z="row"]')) {
    b.onclick = async () => {
      const rowBtn = b;
      b.disabled = true;
      const outcome = await zImportFlow({ source: b.dataset.src, account: b.dataset.acc },
        (r) => onOk(r, rowBtn), setErr, errEl);
      if (outcome !== "ok") b.disabled = false;   // 成功时钮已被徽章替换（不再恢复）
    };
  }
}

/** 导入请求一次（不抛）：成功 / 409 冲突 / 其它错误三态原样带回，由调用方决定怎么呈现。
 *  🔴 409 的附加字段嵌在 `error` 里（`_json_error` 把 extra 并进 `error`；
 *  判据同源 `tests/integration/test_zcode_import_api.py:257` 与本页 :725 的 refreshable 读法）——
 *  早先读 `e.data.conflict` 恒 undefined，**冲突决策路径整条是死的**（2026-10-01 红线审计抓修）。 */
async function zImportOnce(body) {
  try {
    const r = await POST("/admin/api/zcode/import", body);
    return { ok: true, account: (r && r.account) || "" };
  } catch (e) {
    const d = (e.data && e.data.error) || {};
    if (d.conflict) return { conflict: d };
    return { err: e.message };
  }
}

/** 导入成功统一落点（三处导入共用）：toast + 本页数据重取。 */
async function zImportSucceed(r) {
  toast(`已导入账号 ${r.account || ""}`.trim(), "ok");
  await repaintPanel(rootEl);
}

/** 统一导入出口（粘贴 / 本机行 / 到账导入三处共用）：
 *  成功 → onOk；409 → **在 `host` 槽内就地渲染决策**（🔴 红线：弹窗内禁止再开弹窗，
 *  frontend-spec §7.11 / 规矩16——2026-10-01 用户定版，原二级冲突弹窗已废）；其余 → onErr。
 *  settle 口径：Promise<"ok"|"cancel"|"err"> —— 冲突在决策**之后**才结束，调用方据此恢复自身钮的禁用态。 */
function zImportFlow(body, onOk, onErr, host) {
  return new Promise((resolve) => {
    zImportOnce(body).then((r) => {
      if (r.ok) { resolve(onOk(r)); return; }        // onOk 可 async：settle 等它完成
      if (r.conflict) {
        zConflictInline(host, r.conflict,
          async (patch) => {
            const r2 = await zImportOnce({ ...body, ...patch });
            if (r2.ok) { await onOk(r2); return "ok"; }
            if (r2.conflict) return `仍有冲突：${r2.conflict.hint || r2.conflict.error || "需要再次确认"}`;
            return r2.err;
          }).then(resolve);
        return;
      }
      onErr && onErr(r.err);
      resolve("err");
    });
  });
}

/** 设备身份冲突（409）决策：**就地画在宿主槽里，绝不再开第二层弹窗**（红线见 §7.11）。
 *  「绝不自动选」与旧弹窗版一致：取消最左、两个决策钮在右、主色给「复用其身份」；
 *  执行期三钮禁用，失败原因原文留在槽内（不吞、不静默重试）；决策结束后宿主恢复原内容。
 *  无宿主（异常形态）→ 直接 "cancel"，不替用户做选择。 */
function zConflictInline(host, res, attempt) {
  return new Promise((resolve) => {
    const account = String(res.account || "");
    const withName = String(res.conflict_with || "");
    if (!host || !host.querySelector) { resolve("cancel"); return; }
    const prev = host.innerHTML;
    let settled = false;
    const finish = (v) => { if (settled) return; settled = true; host.innerHTML = prev; resolve(v); };
    host.innerHTML = `
      <div class="alert alert-warn" style="margin-bottom:12px">
        <div class="alert-title">设备身份与账号 ${esc(account)} 冲突</div>
        <div>复用其身份 = 与既有账号「${esc(withName)}」共用同一设备身份；重新生成 = 为新账号换一个新设备身份。两者都会立即导入，请按上游对设备数量的要求选择。</div>
        ${res.hint ? `<div style="margin-top:4px">${esc(res.hint)}</div>` : ""}
        <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:8px">
          <button class="btn" data-zcf="cancel">取消</button>
          <button class="btn" data-zcf="regen">重新生成</button>
          <button class="btn btn-primary" data-zcf="reuse">复用其身份</button>
        </div>
        <div data-zcf="err"></div>
      </div>`;
    const btns = [...host.querySelectorAll("button[data-zcf]")];
    const errEl = host.querySelector("[data-zcf='err']");
    const cancelBtn = host.querySelector("[data-zcf='cancel']");
    cancelBtn.onclick = () => finish("cancel");
    const pick = async (patch) => {
      btns.forEach((b) => { b.disabled = true; });
      let out = "";
      try {
        out = await attempt(patch);
      } catch (e) {
        out = (e && e.message) || String(e);
      }
      if (out === "ok") { finish("ok"); return; }
      if (errEl) errEl.innerHTML = `<div class="alert alert-err" style="margin-top:8px"><div class="alert-title">仍未导入</div><div>${esc(out || "后端未给出原因")}</div></div>`;
      btns.forEach((b) => { b.disabled = false; });
    };
    host.querySelector("[data-zcf='reuse']").onclick = () => pick({ reuse: withName });
    host.querySelector("[data-zcf='regen']").onclick = () => pick({ regenerate: true });
  });
}

/* ---------- 购买账号（一元账号 · YouYu Shop）弹窗 ---------- */

/** 订单台账：只存 `{orderId, token}`（凭据内容一个字节都不进浏览器存储）。 */
function readZOrders() {
  try {
    const raw = JSON.parse(readStore(ZSHOP_STORE) || "[]");
    return Array.isArray(raw)
      ? raw.filter((o) => o && o.orderId && o.token).slice(0, ZSHOP_STORE_MAX)
      : [];
  } catch { return []; }
}
function writeZOrders(list) {
  writeStore(ZSHOP_STORE, JSON.stringify((list || []).slice(0, ZSHOP_STORE_MAX)));
}
function zRememberOrder(orderId, token, meta) {
  writeZOrders([Object.assign({ orderId, token }, meta || {})]
    .concat(readZOrders().filter((o) => o.orderId !== orderId)));
}
function zForgetOrder(orderId) {
  writeZOrders(readZOrders().filter((o) => o.orderId !== orderId));
}

/** 订单会话对象（台账恢复与下单共用；`term` = 终态，轮询即停的判据）。 */
function zBlankOrder(orderId, token) {
  return {
    orderId: String(orderId || ""), token: String(token || ""),
    payPath: "", payTypeName: "", amount: null, note: "", deliveredAt: "",
    status: "", expired: false, term: false, delivered: false,
    err: "", accs: [], busy: false,
  };
}

/** 购买账号弹窗：分段 tab 两页（照 ZCode Panel）——商品 tab 默认 + 我的订单 tab（台账恢复，pending 继续轮询）。 */
export function openZShop(root) {                          // root 仅为调用点签名一致；落点统一走 repaintPanel(rootEl)
  stopZShop();                                     // 单实例：开新窗先收干净旧窗（timer 一并清）
  const st = { body: null, m: null, timer: null, tab: "items",
    orders: readZOrders().map((o) => {
      const od = zBlankOrder(o.orderId, o.token);
      od.title = String(o.title || "");            // 下单时刻的商品名（台账老记录没有 → 卡上退化为通用名）
      od.ots = String(o.ts || "");                 // 下单本地时间
      return od;
    }) };
  zshop = st;
  const body = document.createElement("div");
  st.body = body;
  body.innerHTML = `
    <div id="ac-zshop-err"></div>
    <div class="tabs" id="ac-zshop-tabs" role="tablist">
      <button class="tab active" data-zt="items">商品</button>
      <button class="tab" data-zt="orders"></button>
    </div>
    <div id="ac-zshop-pane-items" style="margin-top:12px"></div>
    <div id="ac-zshop-pane-orders" hidden></div>`;
  const foot = document.createElement("div");
  foot.innerHTML = `<button class="btn" style="margin-right:auto" data-zs="refresh">${REFRESH}刷新</button>
    <button class="btn" data-zs="close">关闭</button>`;
  const [refreshBtn, closeBtn] = foot.querySelectorAll("button");            // modal() 之前取（§7.11）
  st.m = modal({ title: "购买账号 · ZCode（一元账号 · YouYu Shop）", body, footer: foot,
    onClose: () => { if (zshop === st) stopZShop(); } });
  closeBtn.onclick = st.m.close;
  refreshBtn.onclick = () => { paintZItems(st); zShopTick(st); };
  for (const b of body.querySelectorAll("#ac-zshop-tabs .tab"))
    b.onclick = () => zShopTab(st, b.dataset.zt);
  paintZOrders(st);                                // 先绘订单（补 tab 上的计数），再拉商品
  paintZItems(st);
  zShopTick(st);                                   // 恢复未完成订单：立即查一轮，再按 2.5s 节拍走
}

/** tab 切换：只翻页不重拉（数据由各自 paint 函数维护，「刷新」钮负责重读）。 */
function zShopTab(st, name) {
  if (zshop !== st) return;
  st.tab = name === "orders" ? "orders" : "items";
  for (const b of st.body.querySelectorAll("#ac-zshop-tabs .tab"))
    b.classList.toggle("active", b.dataset.zt === st.tab);
  st.body.querySelector("#ac-zshop-pane-items").hidden = st.tab !== "items";
  st.body.querySelector("#ac-zshop-pane-orders").hidden = st.tab !== "orders";
}

/** 一元账号弹窗生命周期**唯一**出口（照 `stopWizard()`）：timer 只在这里清、`zshop` 只在这里置空。 */
function stopZShop() {
  const st = zshop;
  if (!st) return;
  zshop = null;
  if (st.timer) { clearInterval(st.timer); st.timer = null; }
  if (st.m) st.m.close();                          // onClose 里 `zshop === st` 已不成立 → 不重复停
}

/** 轮询一轮：无在飞单即清 timer（终态即停的另一半），否则逐单并发查询并续 2.5s 节拍。 */
function zShopTick(st) {
  if (zshop !== st) return;
  const active = st.orders.filter((od) => !od.term);
  if (!active.length) {
    if (st.timer) { clearInterval(st.timer); st.timer = null; }
    return;
  }
  for (const od of active) zPollOrder(st, od);
  if (!st.timer) st.timer = setInterval(() => zShopTick(st), ZSHOP_POLL_MS);
}

async function zPollOrder(st, od) {
  if (zshop !== st || od.busy || od.term) return;
  od.busy = true;
  try {
    const r = await GET(`/admin/api/zcode/shop/order?orderId=${encodeURIComponent(od.orderId)}&token=${encodeURIComponent(od.token)}`);
    if (zshop !== st) return;                      // 查询往返期间窗被关了：不再落笔
    zApplyOrder(st, od, r || {});
  } catch (e) {
    if (zshop !== st) return;
    od.busy = false;
    od.err = e.message;                            // 网络/5xx：红色内联原文，轮询继续（瞬时抖动不清单）
    paintZOrders(st);
  }
}

/** 订单查询响应 → 会话对象 + 台账（失败/超时出表，已到账保留以便回来再导）。 */
function zApplyOrder(st, od, r) {
  od.busy = false;
  od.err = "";
  od.status = String(r.status || od.status || "");
  od.expired = !!r.expired;
  if (r.reallyPrice != null || r.amount != null) od.amount = r.reallyPrice != null ? r.reallyPrice : r.amount;
  od.payTypeName = String(r.payTypeName || od.payTypeName || "");
  od.payPath = String(r.payPath || od.payPath || "");
  od.note = String(r.note || "");
  od.deliveredAt = String(r.deliveredAt || "");
  const accs = Array.isArray(r.accounts) ? r.accounts : (r.account ? [r.account] : []);
  if (accs.length) od.accs = accs;
  od.delivered = od.status === "delivered";
  od.term = od.delivered || od.status === "failed" || od.expired;
  if (od.term && !od.delivered) zForgetOrder(od.orderId);
  paintZOrders(st);
}

/** 订单页整绘（单量 ≤5，整绘最简单；待付 / 已发货 / 超时 / 失败四态各有落点），顺带把单数补到 tab 上。 */
function paintZOrders(st) {
  if (zshop !== st) return;
  const tabBtn = st.body && st.body.querySelector('[data-zt="orders"]');
  if (tabBtn) tabBtn.textContent = st.orders.length ? `我的订单（${st.orders.length}）` : "我的订单";
  const holder = st.body && st.body.querySelector("#ac-zshop-pane-orders");
  if (!holder) return;
  if (!st.orders.length) {
    holder.innerHTML = `<div class="list-empty">还没有订单：下单后在这里看支付状态与取货。</div>`;
    return;
  }
  holder.innerHTML = st.orders.map((od, i) => `<div data-zord="${i}">${zOrderHTML(od)}</div>`).join("");
  st.orders.forEach((od, i) => {
    const card = holder.querySelector(`[data-zord="${i}"]`);
    if (!card) return;
    const pay = card.querySelector('[data-zo="pay"]');
    if (pay) pay.onclick = () => zOpenCashier(od);
    const check = card.querySelector('[data-zo="check"]');
    if (check) check.onclick = () => zCheckPaid(st, od, check);
    for (const b of card.querySelectorAll("[data-zc]")) {
      const idx = Number(b.dataset.oi);
      if (b.dataset.zc === "copy") b.onclick = () => copyText(JSON.stringify(od.accs[idx], null, 2));
      else if (b.dataset.zc === "import") b.onclick = () => zImportDelivered(st, od, idx, b);
    }
  });
}

function zOrderHTML(od) {
  const state = od.term
    ? (od.delivered ? `<span style="color:var(--ok)">已发货</span>`
      : od.expired ? `<span style="color:var(--warn)">已超时</span>`
        : `<span style="color:var(--err)">下单失败</span>`)
    : `<span style="color:var(--text-muted)">待付款</span>`;
  const when = od.ots || od.deliveredAt;
  let bottom = "";
  if (!od.term) {
    bottom = `
      <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn btn-primary btn-sm" data-zo="pay" ${od.payPath ? "" : "disabled"}>${LINK}打开收银台</button>
        <button class="btn btn-sm" data-zo="check">我已付款</button>
      </div>
      <p class="form-hint" style="margin:8px 0 0">收银台在独立小窗打开；本窗每 2.5 秒查询一次支付状态，付款后会自动更新。</p>`;
  } else if (od.delivered) {
    bottom = zDeliveredHTML(od);
  } else {
    bottom = `<p class="form-hint" style="margin:8px 0 0">${esc(od.expired
      ? "订单已超时，重新下一单即可。"
      : (od.note || "本次支付未完成，可重新下一单。"))}</p>`;
  }
  return `
    <div class="list-card" style="margin-bottom:12px">
      <div class="list-row" style="display:block">
        <div style="display:flex;align-items:center;gap:8px">
          <b>${esc(od.title || "ZCode 账号订单")}</b>
          <span style="margin-left:auto;font-size:12px;font-weight:700">${state}</span>
        </div>
        <div style="display:flex;align-items:baseline;gap:8px;margin-top:4px">
          <span class="mono" style="font-size:12px;color:var(--text-faint)">${esc(od.orderId)}</span>
          ${when ? `<span style="font-size:12px;color:var(--text-faint)">${esc(shortTime(when))}</span>` : ""}
          <span style="margin-left:auto;color:var(--err);font-weight:700;white-space:nowrap">${od.amount == null ? "" : `¥${esc(od.amount)}`}</span>
        </div>
        ${od.err ? `<div class="alert alert-err" style="margin-top:12px"><div>${esc(od.err)}</div></div>` : ""}
        ${bottom}
      </div>
    </div>`;
}

/** 已到账：逐账号一行（名称 + 已核验套餐 + 复制 JSON + 导入到网关）。 */
function zDeliveredHTML(od) {
  const accs = od.accs || [];
  if (!accs.length) return `<p class="form-hint" style="margin:8px 0 0">订单已发货，但响应里没有账号内容；可到 YouYu Shop 的订单里查看。</p>`;
  return `
    <p class="form-hint" style="margin:8px 0 0">已发货${od.deliveredAt ? `（${esc(shortTime(od.deliveredAt))}）` : ""}，共 ${accs.length} 个账号：</p>
    <div style="margin-top:8px">${accs.map((a, i) => zAccRowHTML(a, i)).join("")}</div>`;
}

function zAccRowHTML(acc, i) {
  const name = String((acc && (acc.name || acc.account)) || `账号 ${i + 1}`);
  const plans = acc && acc.verifiedPlans;
  const planText = Array.isArray(plans) ? plans.join("、") : (plans ? String(plans) : "");
  return `
    <div class="list-row" style="padding:8px 0">
      <span style="min-width:0;flex:1">
        <b class="mono">${esc(name)}</b>
        ${planText ? `<span style="display:block;font-size:12px;color:var(--text-faint);margin-top:4px">已核验套餐：${esc(planText)}</span>` : ""}
      </span>
      <button class="icon-btn sm" data-zc="copy" data-oi="${i}" aria-label="复制账号 ${esc(name)} 的 JSON" title="复制 JSON">${COPY}</button>
      <button class="btn btn-sm btn-primary" data-zc="import" data-oi="${i}">导入到网关</button>
    </div>`;
}

/** 到账账号「导入到网关」：成功把按钮换成「已导入」徽章（同单内不重复导）；失败原因留在单内。 */
async function zImportDelivered(st, od, idx, btn) {
  const acc = od.accs[idx];
  if (!acc || !btn) return;
  btn.disabled = true;
  const outcome = await zImportFlow({ source: "payload", payload: acc },
    async (r) => {
      const badge = document.createElement("span");
      badge.className = "badge b-ok";
      badge.textContent = "已导入";
      btn.replaceWith(badge);
      await zImportSucceed(r);
    },
    (msg) => { od.err = msg; paintZOrders(st); },
    st.body && st.body.querySelector("#ac-zshop-err"));   // 冲突决策就地画在弹窗错误槽（红线：不开第二层弹窗）
  if (outcome !== "ok") btn.disabled = false;      // 成功时钮已被徽章替换（不再恢复）
}

/** 商品页（开窗首绘与「刷新」共用；失败给出响应里的原因）。 */
async function paintZItems(st) {
  const holder = st.body && st.body.querySelector("#ac-zshop-pane-items");
  if (!holder) return;
  holder.innerHTML = `<div class="loading">正在读取商品列表…</div>`;
  let items = null;
  try {
    const r = await GET("/admin/api/zcode/shop/items");
    items = (r && r.items) || [];
  } catch (e) {
    if (zshop !== st) return;
    holder.innerHTML = `
      <div class="alert alert-err"><div class="alert-title">商品列表读取失败</div>
        <div>${esc(e.message)}</div></div>`;
    return;
  }
  if (zshop !== st) return;                        // 拉取期间窗被关了：不再落笔
  holder.innerHTML = items.length ? zItemsHTML(items) : `<div class="list-empty">商店当前没有在售商品。</div>`;
  for (const b of holder.querySelectorAll("[data-zi]")) {
    const it = items[Number(b.dataset.idx)];
    b.onclick = () => {
      const inp = holder.querySelector(`input[data-zq="${b.dataset.idx}"]`);
      const qty = Math.max(1, Math.min(99, Math.floor(Number(inp && inp.value) || 1)));
      zBuy(st, it, b, qty);
    };
  }
}

/** 小店 `validity` 对象 → 面板同款额度条（券量/券名/到期/剩余小时 + 账号有效期）；没数据就不出条。 */
function zValidityHTML(v) {
  if (!v || typeof v !== "object") return "";
  const lines = [];
  if (Number(v.couponUnits) > 0) {
    lines.push(`券实际 ${zFmtUnits(Number(v.couponUnits))}${v.couponName ? `（${v.couponName}）` : ""}`
      + (v.couponEndsAt ? `，${zFmtMD(v.couponEndsAt)} 到期` : "")
      + (v.couponHoursLeft != null ? ` 剩 ${v.couponHoursLeft} 小时` : ""));
  }
  if (v.planEndsAt) lines.push(`账号有效期至 ${zFmtMD(v.planEndsAt)}`);
  if (!lines.length) return "";
  return `<div style="margin-top:10px;padding:8px 10px;border-radius:var(--radius-sm);background:var(--cool-bg);font-size:12px;color:var(--text-muted);line-height:1.7">`
    + lines.map(esc).join("<br>") + `</div>`;
}

/** 1 亿 → 「1亿」、3 万 → 「3万」（与面板口径一致）；非整亿落万、其余原样。 */
function zFmtUnits(n) {
  return n >= 1e8 && n % 1e8 === 0 ? `${n / 1e8}亿`
    : n >= 1e4 ? `${Math.round((n / 1e4) * 10) / 10}万`
    : String(n);
}

/** unix 秒 → 「10-2 00:00」（面板同款不补零月日）。 */
function zFmtMD(sec) {
  const d = new Date(Number(sec) * 1000);
  if (isNaN(d)) return "";
  const hh = String(d.getHours()).padStart(2, "0"), mm = String(d.getMinutes()).padStart(2, "0");
  return `${d.getMonth() + 1}-${d.getDate()} ${hh}:${mm}`;
}

/** 商品卡照 ZCode Panel：标题+右置单价 → 说明 → 额度条 → 数量+下单+剩余/售罄。 */
function zItemsHTML(items) {
  return items.map((it, i) => {
    const soldout = typeof it.stock === "number" && it.stock <= 0;
    const off = it.listed === false || soldout;
    return `
    <div class="list-card" style="margin-bottom:12px">
      <div class="list-row" style="display:block">
        <div style="display:flex;align-items:baseline;gap:8px">
          <b>${esc(it.title || it.id || "未命名商品")}</b>
          <span style="margin-left:auto;color:var(--warn);font-weight:700;white-space:nowrap">¥${esc(it.price)}<span style="font-size:12px;font-weight:400;color:var(--text-faint)">/个</span></span>
        </div>
        ${it.note ? `<p style="margin:6px 0 0;font-size:12px;color:var(--text-faint);line-height:1.6">${esc(String(it.note))}</p>` : ""}
        ${zValidityHTML(it.validity)}
        <div style="margin-top:12px;display:flex;align-items:center;gap:8px">
          <input type="number" min="1" step="1" value="1" data-zq="${i}" ${off ? "disabled" : ""}
            aria-label="购买数量" style="width:64px;text-align:center">
          <button class="btn btn-sm btn-primary" data-zi="buy" data-idx="${i}"
            ${off ? `disabled title="${soldout ? "已售罄" : "已下架"}"` : ""}>下单</button>
          ${soldout ? `<span class="badge b-warn">已售罄</span>`
            : it.listed === false ? `<span class="badge">已下架</span>`
            : typeof it.stock === "number" ? `<span style="margin-left:auto;font-size:12px;color:var(--text-faint)">剩余 ${it.stock} 个</span>` : ""}
        </div>
      </div>
    </div>`;
  }).join("");
}

/** 下单：payload `{itemId, qty}`（数量随商品卡输入，钳 1~99）；成功即入台账 + 立绘订单 + 立即查一轮状态。 */
async function zBuy(st, it, btn, qty) {
  if (!it || !btn || btn.disabled) return;
  const label = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "下单中…";
  try {
    const r = await POST("/admin/api/zcode/shop/buy", { itemId: it.id, qty: qty || 1 });
    const od = zBlankOrder(r.orderId, r.orderToken);   // 查询令牌 = 下单响应的 orderToken
    od.title = String(it.title || it.id || "");
    od.ots = new Date().toISOString();
    od.payPath = String(r.payPath || "");
    od.payTypeName = String(r.payTypeName || "");
    if (r.reallyPrice != null || r.amount != null) od.amount = r.reallyPrice != null ? r.reallyPrice : r.amount;
    st.orders = st.orders.filter((o) => o.orderId !== od.orderId);   // 同号去重：台账恢复的单撞号时不出现两张卡
    st.orders.unshift(od);
    zRememberOrder(od.orderId, od.token, { title: od.title, ts: od.ots });
    paintZOrders(st);
    zShopNote(st, "");
    zShopTab(st, "orders");                        // 面板行为：下单成功即切至订单 tab 看支付状态
    zShopTick(st);                                 // 立刻查一次（不必等 2.5s 节拍）
  } catch (e) {
    zShopNote(st, "下单未完成：" + e.message);
  }
  btn.innerHTML = label;
  btn.disabled = false;
}

function zShopNote(st, msg) {
  const el = st.body && st.body.querySelector("#ac-zshop-err");
  if (el) el.innerHTML = msg
    ? `<div class="alert alert-err" style="margin-bottom:12px"><div class="alert-title">操作未完成</div><div>${esc(msg)}</div></div>`
    : "";
}

/** 收银台 = 独立小窗（窗口尺寸照商铺自身页面；不用 iframe —— 支付页的框禁头不可预期）。 */
function zOpenCashier(od) {
  if (!od.payPath) return;
  window.open(od.payPath, "youyu-cashier", "width=420,height=660");
}

/** 「我已付款」= 立即查一次（不等节拍）；状态由订单区整绘呈现（节点会随重绘替换，无需恢复禁用态）。 */
async function zCheckPaid(st, od, btn) {
  if (btn) btn.disabled = true;
  await zPollOrder(st, od);
}

