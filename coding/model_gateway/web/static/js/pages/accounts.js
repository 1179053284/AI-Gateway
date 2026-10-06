/** 账号接入（tech-design §22.7 · M6-4b · M7-UI 改版设计书 `docs/changes/design-accounts-list-v2.md`）
 *
 * 骨架 A「扁平产品 rail + 单产品账号工作区」（设计书 §1/§2）：
 *   左子侧栏 = 10 行 `.anchor-item` 产品选择器（**无 .group-card / 无 .mode-btn / 无「族」轴**
 *   ——族层是前端臆造的，见设计书 §0-1）＋ 右侧撑满配置区 = 账号表（唯一列表单位）。
 *   接入入口全页唯一：`.subnav-foot .side-add`（§2-注，resources.js:175-178 定版范式）。
 *   实现词汇（协议 / 出站基址 / 设备身份字段 / 能力位 / 网关资源 / 池额度）2026-10-01 起
 *   **不再常驻**（用户指示去展开详情行）：续期在**账号行操作列**（2026-10-01 用户裁决，
 *   连同登录态失效倒计时一起回列表；弹窗内不放账号级动作）；
 *   模型目录**二级弹窗 2026-10-01 废除**（用户定版：弹窗套弹窗 = 忌讳——目录字段直接
 *   融合进映射行，见 `mapBodyHTML`/`modelFactsHTML`），其余实现词汇只在后端视图里可查。
 *
 * 数据面（**打开页面只有 1 个 GET**，§4-1）：
 *   GET  /admin/api/accounts                全产品账号视图，能力位已内嵌
 *        （`api/admin_accounts.py::accounts_view` = `{**asdict(ProductMeta), models_wired, accounts}`）
 *        → 本页**不再**调 `/admin/api/accounts/capabilities`（§4-1 判据：两个 GET 变一个）。
 *          该端点仍在册（`api/admin_accounts.py::capabilities_matrix`，消费方只剩
 *          `tests/integration/test_admin_accounts.py` 与 `test_m6_a1_wiring.py`，前端已无第二个调用页）。
 *   GET  /admin/api/accounts/{product}/{name}/models   单账号模型目录（B-1 生产出口；
 *        界面 2026-10-01 起**不再调用**——目录字段已由 /catalog 全字段带出，二级弹窗废除）
 *   GET  /admin/api/accounts/{product}/catalog         产品内部模型目录（模型映射弹窗）
 *   POST /admin/api/accounts/mappings                  行内即时写映射 {product, items:[{model,target,enabled}]}
 *   POST /admin/api/accounts/auto-map                  首次配置用：整表自动匹配并落库 {product}
 *        （回执带 `via`=model|regex + `matched_model`/`matched_regex`/`reason`；真发一次出站请求）
 *   POST /admin/api/accounts/claim-all                 批量签到 / 领取 {product|null}
 *   GET  /admin/api/zcode/import/sources               ZCode 本机工具账号来源（导入账号弹窗）
 *   POST /admin/api/zcode/import                       导入（panel/switch/payload；409 = 设备身份冲突 → 用户二选一）
 *   GET  /admin/api/zcode/shop/items | POST …/shop/buy | GET …/shop/order
 *                                                      购买账号（YouYu Shop 代理；订单 2.5s 轮询，关窗即停）
 *   POST /admin/api/accounts/login/{start,poll,callback,alt,cancel}   登录向导（cancel = BD2）
 *   POST /admin/api/accounts/login/commit              确认接入（M7-E 两阶段提交第二段）
 *   POST /admin/api/accounts/{product}/{name}/{claim|refresh|probe|enable|disable|delete}
 *
 * 🔴 后端事实（本轮落地，直接决定界面逻辑，注释在各自落点）：
 *   · **M7-E 两阶段提交（2026-10-01 用户裁决：账号标识系统自动生成不手填 / 拿到回调后
 *     点「确定接入」才保存）**。后端对应契约（`accounts/login.py`
 *     模块头 + `api/admin_accounts.py::login_commit`）：
 *     ① `login/{poll,callback,alt}` 的 `success` 只表示"凭据已认领并**暂存**在服务端会话上"，
 *        **一个字节都不落盘**；② `login/commit` 才是落盘开关（幂等：未知/过期会话回
 *        `{committed:false, reason}`，永不 404）；③ 取消/关窗（`login/cancel`）**丢弃暂存
 *        凭据** —— 未确认的登录不会在账号目录留下任何东西（列表来自磁盘，所以"未确认不
 *        出现"自动成立）；④ `login/start` 不传 name 时后端自动生成 `{product}-{8hex}` 并在
 *        响应 `account` 字段回传（本页只展示结果，不再让用户手填任何标识）。
 *   · **登录窗口 = 弹窗，不是 iframe（2026-10-01 修正轮用户裁决；理由 = 实测框禁头）**：
 *     `https://qoder.com/device/selectAccounts` → `content-security-policy: … frame-ancestors
 *     'none'` + `x-frame-options: SAMEORIGIN` → **iframe 永远显示不了该页**（浏览器必定
 *     拒绝渲染，qodercn 同族同判）。其余实测厂商（`https://www.workbuddy.ai/login` 301→200、
 *     `https://www.codebuddy.cn/login` 301→200、`https://www.workbuddy.cn/login` 301→200、
 *     `https://www.trae.cn/authorization` 200、`https://lobsterai.youdao.com/portal` 200）
 *     重定向链上均无框禁头，但**弹窗对全部厂商一体可用** → 本页只做弹窗，不按厂商分叉、
 *     也不再带"5 秒未加载"那套嵌入兜底。契约细节与参考实现出处见 `openLoginWindow`
 *     上方注释块。
 *   · **BD4 回跳接收端已存在**（`accounts/callback_server.py` + `login.py::_open_callback` +
 *     各产品 `_CALLBACK` 表）：trae / lobsterai 的授权 URL 指向**实际绑定端口**，浏览器授权完
 *     成后自动回跳即完成登录 → 向导以「自动回跳」为主路径，**粘贴只是兜底**（监听可能绑定失败，
 *     此时 `login.py` 记日志并退回粘贴通道，流程仍可用）。⚠️ `login/start` 不回传「监听是否
 *     绑定成功」的位，所以文案只说"优先自动、没反应就用兜底"，不断言接收端一定在听（已登记）。
 *   · **BD2 `login/cancel`**：幂等 `{cancelled: bool}`、永不 404 → 向导的关闭路径统一请求作废会话。
 *   · **BD3a `resource`**：账号视图带 `resource` = `[{id, enabled}]`；`null` = 配置读不动（**未知**，
 *     不是 0），`[]` = 确实没有（`api/admin_accounts.py::_resource_projection`）。
 *   · **额度数据源 = `a.runtime.quota`**（落盘快照 `{state, source, detail, plan, items,
 *     checked_at}`；`plan` = 套餐名、`items` = 逐包结构，2026-10-01 加字段——钩子取不到时
 *     为 ""/()，老快照无这两键走四值口径），`a.quota` 是网关额度池
 *     （`remaining-reserved`，**量纲不同不得混列**）。
 *   · **BD1 `cron_enabled_of`**：停用位现在对**手动腿与定时腿同时**生效（BUG-3 已修）→ 开关的
 *     title 可以如实写「两条腿都跳过」。
 *
 * 🔴 行为契约（后端已定，前端不得自创；改版前后不变）：
 *   ① **local_callback 型不得发起轮询**（R-5：其 `login_poll` 恒 pending，结果只从回跳来）——
 *      `POLLABLE` 表是这条契约的唯一落点；
 *   ② `pending` 不是失败（§22.3），原样展示 `detail`、中性样式、不计次；
 *   ③ 能力位 `false` 的控件**不渲染**（§3 推翻旧死钮），只有瞬态原因才 `disabled` + `title`；
 *   ④ 删除必须二次确认且带 `?confirm=1`（缺省 400 且不动盘）；
 *   ⑤ claim 四类结果按 ops 出口呈现：**只有失败着色**；
 *   ⑥ `state:"unknown"` / `resource:null` 一律读作"未知"，**永不编造**成 0 或空表；
 *   ⑦ **M7-E 两阶段提交**：`success` ≠ 已接入 —— 向导进入「已登录，待确认接入」，
 *      只有 `login/commit` 回 `committed:true` 才算接入成功（toast + 关窗 + 刷新列表）；
 *      `committed:false` 时把真实原因展示给用户（**不谎报成功**）。
 * 交互 = 操作即保存（D3）；三级重绘 `drawShell → paintPanel → patchRow`（§4-2，
 * 行操作**绝不**整页重洗，也绝不拆掉在飞的向导；向导生命周期唯一所有者 = `stopWizard()`）。
 * 图标 = Lucide 0.555.0 官方 path，14px / sw2（frontend-spec §5.7 / §7.7）。
 */

import { GET, POST, esc } from "../api.js";
import { modal, confirmDialog, toast, toastCard, copyText, initSplitResize } from "../components.js";
import { batchClaim, batchRenew, mapBodyHTML, modelFactsHTML, openModelMap } from "./accounts/mapping.js";
import { Z_PRODUCT, openZImport, openZShop, zshop } from "./accounts/zcode.js";

// D-1/D-4 拆分第一步：登录向导子模块（其依赖的主文件符号在下方 export 区）。
import {
  openWizard, stopWizard, settle, openLoginWindow, paintFooter, switchEl,
} from "./accounts/login.js";


/* ---------- 图标（Lucide 0.555.0，14×14 sw2；全站同契约） ---------- */
const PLUS = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>`;
export const COPY = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>`;
const REFRESH = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>`;
const CHECKIN = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/><path d="m9 16 2 2 4-4"/></svg>`;
export const LINK = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>`;
export const PHONE = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="20" x="5" y="2" rx="2" ry="2"/><path d="M12 18h.01"/></svg>`;
const MAP = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m16 3 4 4-4 4"/><path d="M20 7H4"/><path d="m8 21-4-4 4-4"/><path d="M4 17h16"/></svg>`;
const SCAN = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><path d="M7 12h10"/></svg>`;
const IMPORT = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>`;
const SHOP = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>`;

/* ---------- 常量（判据表；不要在渲染里散落字面量） ---------- */

/** 登录形态文案（`LoginKind` 五型，§22.3） */
export const KIND_TEXT = {
  device_code: "设备码授权", external_link: "外链授权",
  local_callback: "本机回跳", qr: "扫码", sms_code: "短信验证码",
};

/** 🔴 local_callback 与短信型**不得轮询**（R-5 / §22.3）：其 `login_poll` 恒 pending，
 *  结果只从「接收端自动回跳 / 地址栏粘贴」或「提交验证码」通道来。本表是唯一落点。 */
export const POLLABLE = new Set(["device_code", "external_link", "qr"]);

/** 🔴 走「弹窗登录窗口」的形态集合（M7-E 修正轮；模式判据的唯一来源）。
 *  device_code / external_link / local_callback 的 `Challenge.url` 是**给浏览器看的登录页**；
 *  `qr` 的 `url` 是二维码**内容**（raccoon 的 `/login/mp?code=…`，也可能是 `weixin://`）、
 *  `sms_code` 的交互全在本页表单 —— 这两型不开窗口（照搬"url 即网页"的假设会弹出一个
 *  不是给浏览器看的东西）。 */
export const WINDOW_KINDS = new Set(["device_code", "external_link", "local_callback"]);

/* claim 四类结果（ops.base.Category）→ 呈现：**只有失败着色**，
   `already_done`/`inactive` 归「跳过」（§16.2 原则 3 / 行为契约⑤）。 */
const CATEGORIES = {
  success: { label: "成功", toast: "ok" },
  already_done: { label: "跳过", toast: "" },
  inactive: { label: "跳过", toast: "" },
  failed: { label: "失败", toast: "err" },
};

/** 批量（`claim-all`）结果四类文案（summary 与逐行共用；键名 = payload.report/details.category）。
 *  ⚠️ 与行级 `CATEGORIES` 有意不同：批量出口把「已领 / 未参与」分开说（行级只出一句「跳过」）；
 *  着色口径一致 —— 仍然**只有失败着红**，success/already_done/inactive 一律中性。 */
const CLAIM_LABEL = { success: "成功", already_done: "已领", inactive: "未参与", failed: "失败" };

/** 新手任务（一次性登录奖励）——⚠️ 后端无 `claim_onboarding` 端点（BD7 未落地）：
 *  按「未登记能力不渲染按钮 / 点了必然失败不做」整体隐藏。补端点后：① 本常量改 true；
 *  ② `runOp` 的 `onboarding` 分支即生效（两处都在位）。 */
const ONBOARDING_ENDPOINT_READY = false;

export const POLL_MS = 2000;          // 登录轮询间隔（仅 POLLABLE 形态）
export const POLL_MAX_FAILS = 5;      // 连续轮询失败上限（网络抖动不无限刷）
export const TICK_MS = 1000;          // 会话 TTL 倒计时刷新
const PRODUCT_STORE = "mgw-accounts-product";       // §4-4 上次选中产品
const FILTER_STORE = "mgw-accounts-only-with";      // §1.3 派生开关（默认关）

/* ---------- 页面状态：收编进 accounts/state.js（D-1/D-4 拆分）----------
 * 可变状态唯一居所；import 的 live binding 供读，赋值走 setXxx。 */
import {
  view, selected, rootEl, railEl, filterEl, panelEl, onlyWith, deepMiss, loadError,
  setView, setSelected, setRootEl, setRailEl, setFilterEl, setPanelEl,
  setOnlyWith, setDeepMiss, setLoadError,
} from "./accounts/state.js";

/** 能力位取用点：`/admin/api/accounts` 已内嵌 `capabilities`（§4-1 单 GET 的红证落点）。 */
const capsOf = (pid) => {
  const p = productOf(pid);
  return (p && p.capabilities) || {};
};

const productOf = (pid) => (view && view.products || []).find((p) => p.id === pid) || null;
const selectedProduct = () => productOf(selected);

/* ---------- 入口：1 个 GET + 深链 + 一次性 shell ---------- */
export async function renderAccounts(root) {
  setRootEl(root);
  const prevSelected = selected;          // 换产品要清回执，同产品重绘必须留着（下面比对用）
  setOnlyWith(readStore(FILTER_STORE) === "1");
  await fetchView();
  /* §4-4 深链优先，其次上次记忆，最后 registry 原序首项（= view.products[0]）。
     选中项不在册时回落并登记 `deepMiss`，由卡头 `.value` 如实注明。 */
  const asked = productFromHash() || readStore(PRODUCT_STORE);
  const hit = asked && productOf(asked) ? asked : null;
  setDeepMiss(asked && !hit ? asked : "");
  const first = view && view.products[0] ? view.products[0].id : null;
  setSelected(hit || first);
  /* 上次记忆的产品可能被派生开关（§1.3）滤出选择轴：选中项必须在 rail 可见集里，
     否则面板与 rail 的选中态会各说各话 → 退到可见集首项。 */
  const visible = railScope().ids;
  if (visible.length && !visible.includes(selected)) setSelected(visible[0]);
  if (!productOf(selected)) setSelected(first);
  drawShell();
}

/** 服务端视图重取（失败不抛：§5 保留上次数据 + 面板给「重试」）。 */
async function fetchView() {
  try {
    setView(await GET("/admin/api/accounts"));
    setLoadError("");
  } catch (e) {
    setLoadError(e.message || "账号视图读取失败");
  }
  return view;
}

/** `#/accounts?p=<id>`：手写解析（本文件要在无 DOM 的 vm 判据里编译，不用 URL 全局对象）。 */
function productFromHash() {
  const hash = String((typeof location === "undefined" || !location.hash) ? "" : location.hash);
  const m = /[?&]p=([^&]+)/.exec(hash);
  return m ? decodeURIComponent(m[1]) : "";
}

function readStore(key) {
  try { return localStorage.getItem(key); } catch { return null; }    // 隐私模式/禁用存储
}
function writeStore(key, val) {
  try { localStorage.setItem(key, val); } catch { /* 记不住不影响本页功能 */ }
}

/* ---------- 三级重绘之第一级：shell 每路由一次 ----------
 * gutter 已收进 base.css 的 `.panel-split`（§4-3，含 ≤768 的 .subnav 横滚条带）→
 * 本页**不再**自带 `<style>` 副本，也不再手写 `#ac-wrap` 负边距。 */
function drawShell() {
  const root = rootEl;
  if (!root) return;
  root.innerHTML = `
    <div class="panel-split panel-split-narrow">
      <aside class="subnav">
        <button class="btn btn-sm" id="ac-claim-all" style="margin:12px 12px 8px;width:calc(100% - 24px)"
          title="对所有支持签到的产品（能力位 checkin=True）的全部已启用账号执行签到 / 领取">${CHECKIN}一键签到</button>
        <div id="ac-filter"></div>
        <div class="subnav-scroll" role="tablist" aria-orientation="vertical"
          aria-label="产品列表" id="ac-rail"></div>
      </aside>
      <main>
        <div id="ac-panel"></div>
      </main>
    </div>`;
  setRailEl(root.querySelector("#ac-rail"));
  setFilterEl(root.querySelector("#ac-filter"));
  setPanelEl(root.querySelector("#ac-panel"));
  initSplitResize(root, "accounts");
  /* 全产品批量入口：能力位门控在服务端（payload 只带 product:null，不发产品清单）——
     哪些产品参与由后端按 capacity 判，前端不替它筛（筛了就是第二份真相）。 */
  const claimAllBtn = root.querySelector("#ac-claim-all");
  if (claimAllBtn) claimAllBtn.onclick = () => batchClaim(claimAllBtn, { product: null });
  wireRailKeys();
  paintRail();
  paintPanel();
}

/* ---------- 左子侧栏：10 行扁平产品选择器（§2） ----------
 * 每行只放四件：`.mark-sm` 首字母 · 产品名（flex:1 + ellipsis + title 全值）·
 * 计数徽章（`N>0` 才渲染）· 四态状态点。**没有族、没有分组卡、没有登录方式**。 */

/** rail 行数据源：默认 = registry 原序全数平铺（0 账号产品也在列，接入入口要始终可见）。
 *  仅当「0 账号产品 ≥ 5 且 有账号产品 ≥ 1」时给一枚**派生**开关（输入 = 同一份视图计数）。 */
function railScope() {
  const products = (view && view.products) || [];
  const byId = new Map(products.map((p) => [p.id, p]));
  const ids = products.map((p) => p.id);
  const empty = ids.filter((id) => !byId.get(id).accounts.length).length;
  const toggle = empty >= 5 && ids.length - empty >= 1;
  const shown = toggle && onlyWith ? ids.filter((id) => byId.get(id).accounts.length) : ids;
  return { byId, ids: shown, toggle };
}

/** rail 行 title 仅此一句（§2；门 L-A8 反转 M6-IX A8）：`产品名 · N 个账号（M 已启用）`。 */
const railTitle = (p) => `${p.title} · ${p.accounts.length} 个账号（${p.accounts.filter((a) => a.enabled).length} 已启用）`;

/** 四态点（§2 v2.1）：橙=存在读不动/未知的账号；绿=有启用；灰=有账号但零启用；无点=0 账号。
 *  ⚠️ 顺序必须是"橙先于绿"：`status:"unknown"` 在 `admin_accounts.py:491` 里**蕴含 enabled**
 *  （停用直接得 `disabled`），若"有 enabled 即绿"排在前面，橙态永不可达（三态同形的老毛病换个方向）。 */
function railDot(p) {
  const n = p.accounts.length;
  if (!n) return "";
  const bad = p.accounts.some((a) => a.status === "unknown" || a.runtime_ok === false);
  if (bad) return `<span class="dot" style="background:var(--warn)"></span>`;
  const on = p.accounts.filter((a) => a.enabled).length;
  return `<span class="dot ${on ? "on" : ""}"></span>`;
}

/** 产品图标 = 各产品**官方图标**（2026-10-03 全部换成官方资产，来源逐条记台账：
 *  本机官方 App 包内资源 / 官网 favicon / 官方注册表），落 `web/static/img/products/`。
 *  旧形态里有几枚是我手绘的占位符（loomy = 蓝底白字「L」、qoder = 放大镜、zcode = 187B 小方块），
 *  那是"看着像图标"而不是图标 ⇒ 一律弃用。`alt` = 首字母，图缺失时浏览器就地显示它。
 *  🔴 扩展名集合与磁盘上的文件**一一对应**，由 `tests/unit/test_v2_product_icons.py` 钉住
 *     （少一个文件 / 扩展名对不上 = 界面上一个 404 破图，肉眼在 20px 下很容易漏）。 */
const ICON_SVG = new Set(["qoder", "trae", "raccoon"]);
function productMark(p) {
  const ext = ICON_SVG.has(p.id) ? "svg" : "png";
  return `<img src="/img/products/${esc(p.id)}.${ext}" alt="${esc((p.title[0] || "?").toUpperCase())}">`;
}

function railHTML() {
  const f = railScope();
  const byId = f.byId;
  const items = f.ids.map((pid) => {
    const p = byId.get(pid);
    const n = p.accounts.length;
    return `
          <button class="anchor-item ${pid === selected ? "active" : ""}" data-pid="${esc(pid)}"
            role="tab" aria-selected= "${pid === selected ? "true" : "false"}"
            tabindex="${pid === selected ? "0" : "-1"}" title="${esc(railTitle(p))}">
            <span class="mark-sm">${productMark(p)}</span>
            <span style="min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(p.title)}</span>
            ${n ? `<span class="badge b-gray">${n}</span>` : ""}
            ${railDot(p)}
          </button>`;
  });
  return items.join("");
}

/** 「只看有账号」开关（§1.3 派生筛选，默认关；状态进 localStorage）。 */
function filterHTML() {
  const f = railScope();
  if (!f.toggle) return "";
  return `
      <div style="display:flex;align-items:center;gap:8px;padding:4px 12px 8px">
        <span id="ac-only" style="display:inline-flex;align-items:center"></span>
        <span style="font-size:12px;font-weight:600;color:var(--text-muted)">只看有账号</span>
      </div>`;
}

function paintRail() {
  if (filterEl) {
    filterEl.innerHTML = filterHTML();
    const holder = filterEl.querySelector("#ac-only");
    if (holder) holder.append(switchEl(onlyWith, "只看有账号的产品", (next) => {
      setOnlyWith(next);
      writeStore(FILTER_STORE, next ? "1" : "0");
      const ids = railScope().ids;
      paintRail();
      /* 开关把当前产品滤出选择轴时：跟着换到可见集首项，不留"面板开着、rail 里没有它"的分裂态。 */
      if (ids.length && !ids.includes(selected)) selectProduct(ids[0]);
      else paintPanel();
      return false;                     // 视觉由重绘给出，开关自身不翻
    }));
  }
  if (!railEl) return;
  railEl.innerHTML = railHTML();
  for (const b of railEl.querySelectorAll("[data-pid]")) {
    b.onclick = () => selectProduct(b.dataset.pid);
  }
}

/** 切产品 = 1 击 + 2 class（§4-5 点击预算）：**不重洗整页、不重建 rail**，
 *  更不碰在飞的向导（§4-2 —— 向导只由 `stopWizard()` 处置）。 */
function selectProduct(pid) {
  if (!pid || pid === selected || !productOf(pid) || !railEl) return;
  const prev = railEl.querySelector(`.anchor-item[data-pid="${cssAttr(selected)}"]`);
  if (prev) {
    prev.classList.remove("active");
    prev.setAttribute("aria-selected", "false");
    prev.tabIndex = -1;
  }
  setSelected(pid);
  setDeepMiss("");                 // 回落注记只对入站深链/记忆有意义：用户已自己选定产品
  writeStore(PRODUCT_STORE, pid);
  /* 深链是**入站**判据：写 hash 会触发 main.js 的 hashchange → 整页重洗，与 §4-5 相悖，
     故只更新 localStorage 记忆，不改 `location.hash`。 */
  const cur = railEl.querySelector(`.anchor-item[data-pid="${cssAttr(pid)}"]`);
  if (cur) {
    cur.classList.add("active");
    cur.setAttribute("aria-selected", "true");
    cur.tabIndex = 0;
    if (cur.focus) cur.focus();
  }
  paintPanel();
}

/** rail 键盘：↑/↓/Home/End **立即激活**（roving tabindex，不等空格）。 */
function wireRailKeys() {
  if (!railEl || !railEl.addEventListener) return;
  railEl.addEventListener("keydown", (e) => {
    const rows = Array.from(railEl.querySelectorAll(".anchor-item"));
    const at = rows.findIndex((b) => b === e.target);
    if (at < 0) return;
    let to = -1;
    if (e.key === "ArrowUp") to = Math.max(0, at - 1);
    else if (e.key === "ArrowDown") to = Math.min(rows.length - 1, at + 1);
    else if (e.key === "Home") to = 0;
    else if (e.key === "End") to = rows.length - 1;
    if (to < 0 || !rows[to]) return;
    if (e.preventDefault) e.preventDefault();
    selectProduct(rows[to].dataset.pid);
  });
}

/* ---------- 三级重绘之第二级：面板 ---------- */
function paintPanel() {
  if (!panelEl) return;
  const p = selectedProduct();
  panelEl.innerHTML = panelHTML(p);       // p=null 时 panelHTML 自己出「读失败 alert + 空态」
  bindPanel(p);                           // bindPanel 对 null 仍绑「重试」
}

function panelHTML(p) {
  if (!p) {
    return `
    ${loadError ? alertErrHTML() : ""}
    <div class="empty">无在册产品</div>`;
  }
  const on = p.accounts.filter((a) => a.enabled).length;
  return `
    ${loadError ? alertErrHTML() : ""}
    <div class="card flush">
      <div class="card-head inset">
        <span class="card-title">${esc(p.title)}</span>
        <span class="value">${p.accounts.length} 个账号 · ${on} 已启用</span>
        ${extraValueHTML()}
        ${headOpsHTML(p)}
      </div>
      ${p.accounts.length ? tableHTML(p) : emptyHTML(p)}
    </div>`;
}

/** 卡头右侧操作组：**模型映射**（恒在）· **一键领取**（能力位 `checkin`
 *  门控，与行级签到钮同判据）· **导入账号 / 购买账号**（**ZCode 专属**，`p.id === Z_PRODUCT` 才渲染，
 *  来源与商品都只对本机 ZCode 工具成立）· **接入账号**（唯一接入入口，既有定版）。
 *  🔴 右对齐靠**外层 span 的** `margin-left:auto`：flex 会把自由空间**平分**给每条 auto 边距，
 *  `#ac-add` 自带的那条（定版保留）若与组内另一条并存，自由空间会裂在按钮组中间
 *  （组 → 右侧大空档 → 末钮），所以组内不再加第二条 auto。
 *  🔴 ≤768 窄屏（375px 实测）：三钮并排 292px + 标题/计数挤不进 349px 的卡头，
 *  `.card.flush{overflow:hidden}` 会把最右的「接入账号」直接裁掉 → 组内允许换行、
 *  可缩到 min-content（按钮各自 nowrap），窄屏自动折成多行右对齐（375 实测每行一颗），
 *  宽屏（1440/1280/1024/768 实测）仍是单行、间距 8px、右缘贴卡头内容右缘（ZCode 多两颗钮，
 *  仍在同一换行组里自动折行，不加例外）。 */
function headOpsHTML(p) {
  const c = p.capabilities || {};
  return `
        <span style="margin-left:auto;display:inline-flex;flex-wrap:wrap;justify-content:flex-end;align-items:center;gap:8px;max-width:100%">
          <button class="btn btn-sm" id="ac-map" data-pid="${esc(p.id)}"
            title="查看该产品内部模型（含消耗规则/免费）并初始化到网关模型的映射">${MAP}模型映射</button>
          ${c.checkin ? `<button class="btn btn-sm" id="ac-claim"
            title="对该产品全部已启用账号执行签到 / 领取（结果按四类出口呈现）">${CHECKIN}一键领取</button>` : ""}
          ${c.balance ? `<button class="btn btn-sm" id="ac-quota"
            title="刷新额度：对该产品全部账号只读查一次上游额度（含停用账号；结果就地回执）">${REFRESH}刷新额度</button>` : ""}
          ${c.refresh ? `<button class="btn btn-sm" id="ac-renew"
            title="批量续期：对该产品下登录态 5 小时内将失效的账号刷新凭据并落盘（停用账号也可续；失效时间取不到的不猜、不续）">${REFRESH}批量续期</button>` : ""}
          ${p.id === Z_PRODUCT ? `
          <button class="btn btn-sm" id="ac-zimport"
            title="从本机 ZCode 工具导入账号，或粘贴 JSON 导入">${IMPORT}导入账号</button>
          <button class="btn btn-sm" id="ac-zshop"
            title="购买账号（YouYu Shop：一元买一个可用账号）；买完复制账号 JSON 走「导入账号」或直接一键导入">${SHOP}购买账号</button>` : ""}
          <button class="btn btn-sm btn-primary" id="ac-add" style="margin-left:auto">${PLUS}接入账号</button>
        </span>`;
}

/** 卡头的如实注记（§4-4 深链回落 / §5 读失败）：另起 `.value`，不改动计数那一行。 */
function extraValueHTML() {
  const bits = [];
  if (deepMiss) bits.push(`产品「${deepMiss}」未在册，已回到第一项`);
  if (loadError) bits.push("数据可能已过期");
  return bits.map((t) => `<span class="value">${esc(t)}</span>`).join("");
}

function alertErrHTML() {
  return `
    <div class="alert alert-err" style="margin-bottom:12px">
      <div class="alert-title">账号视图读取失败</div>
      <div>${esc(loadError)}（下方仍是上一次取到的数据）</div>
      <button class="btn btn-sm" id="ac-retry" style="margin-top:8px">重试</button>
    </div>`;
}

/** 空态（§5）：**卡内左对齐两行**，不再嵌一张自带卡片阴影的 `.empty`
 *  （卡里套卡是双层盒子；旧版还写「点左下」，而入口已移到卡头右上）。 */
function emptyHTML(p) {
  const kind = KIND_TEXT[p.login] || p.login;
  return `
      <div style="padding:4px 16px 20px">
        <div style="font-size:13px;font-weight:700;color:var(--text-soft)">还没有账号</div>
        <p class="form-hint" style="margin:6px 0 0">点右上『接入账号』，用${esc(kind)}完成第一个。</p>
      </div>`;
}

/** 每种登录形态**会发生什么**（放进向导第一步，替换掉"所有产品看起来一样"的观感）。
 *  🔴 文案与实现同源：`local_callback` 那句的依据是 `accounts/callback_server.py` 真起了本机接收端
 *  （trae/lobsterai 的 `_CALLBACK` 表），不是"上游会回跳"的想象；「弹窗」是本轮的真实布局
 *  （`openLoginWindow` 的 window.open + 参考实现 jet-hub.js:1318-1345）。 */
export function kindHint(kind) {
  switch (kind) {
    case "external_link": return "点『开始登录』会弹出官方登录页（800×600）；若浏览器拦截了弹窗，用下方的链接打开。完成后向导进入待确认，点「确定接入」保存。";
    case "device_code": return "点『开始登录』会弹出官方登录页（800×600），把本页生成的设备码填进登录页核对确认；若浏览器拦截了弹窗，用下方的链接打开。完成后点「确定接入」保存。";
    case "local_callback": return "点『开始登录』会弹出官方登录页（800×600）完成授权，浏览器随后自动回跳本机接收端；若浏览器拦截了弹窗，用下方的链接打开。万一回跳没被接住，把地址栏整串粘回下方的兜底框。";
    case "qr": return "点『开始登录』→ 本页给出登录二维码，用手机扫码并在手机上确认；完成后本向导进入待确认，点「确定接入」保存。";
    case "sms_code": return "点『开始登录』→ 在本页填写手机号，获取并提交短信验证码；完成后本向导进入待确认，点「确定接入」保存。";
    default: return "";
  }
}

/* ---------- 账号表：4 列固定列集（2026-10-01 改版：去展开列，表头逐字） ---------- */
/** 本轮额度没查成的账号有几个、各是什么成因（`reason` ∈ SILENT 名单 = 上游这一轮没说话）。
 *  与后端 `ops/builtin/query_balance.SILENT` 同一份名单，前端不另立判据。 */
function quotaStaleBits(p) {
  const bits = {};
  for (const acc of p.accounts || []) {
    const q = (acc.runtime || {}).quota;          // 刻意不写 `const rq = a.runtime && …`：
    if (q && QUOTA_SILENT.includes(q.reason)) bits[q.reason] = (bits[q.reason] || 0) + 1;  // 那行是 V4 变异的唯一锚点
  }
  return bits;
}

/** 🔴 跨行说明只说一次（2026-10-02 用户指令：失败原因不得刷进每一行）。
 *  行内保留的是**定位用的**注记「（读取失败）」+ 上一轮数值与时刻；
 *  上游原话（`detail`）留在行内悬停里，不占常驻面。 */
function quotaStaleAlertHTML(p) {
  const bits = quotaStaleBits(p);
  const n = Object.values(bits).reduce((x, y) => x + y, 0);
  if (!n) return "";
  const why = Object.entries(bits).map(([k, v]) => `${QUOTA_REASON_TEXT[k] || k} ${v} 个`).join("、");
  return `
    <div class="alert alert-warn" style="margin:0 12px 12px">
      <div class="alert-title">${n} 个账号本轮额度没有取到新数据（${esc(why)}）</div>
      <div>下面这些行显示的是**上一轮**的数值与时刻（每行「查于」即那一轮的时间）；
        上游原话悬停在额度格上可见。要立刻重试：行内「刷新额度」只查这一个账号，
        卡头那颗查本产品全部账号。</div>
    </div>`;
}

const QUOTA_REASON_TEXT = {
  circuit: "冷却中", "circuit-untrusted": "熔断状态不可读", unreachable: "读取失败",
  no_credentials: "未发起（缺凭据）", no_identity: "未发起（缺登录身份）",
};

function tableHTML(p) {
  return `
      ${quotaStaleAlertHTML(p)}
      <div class="table-wrap"><table class="tbl" id="ac-table"><thead><tr>
        <!-- 🔴 列序 = 账号 / 额度 / 状态 / 操作（2026-10-03 用户指示「状态列和额度列交换下位置」）：
             额度是这一页真正要读的东西，紧跟账号名；开关（状态）是动作位，挨着操作列成一组。
             旧序「账号/状态/额度/操作」把 76px 的开关插在账号与额度中间，额度被推到最远端。 -->
        <th>账号</th>
        <th class="num">额度</th><th>状态</th><th class="ops-col">操作</th>
      </tr></thead><tbody>
        ${p.accounts.map((a) => rowHTML(p, a)).join("")}
      </tbody></table></div>`;
}

/** 账号行。停用行只加 `.off`、**有意不加 `.locked`**：停用账号仍需可探活/删除/续期
 *  （`.off + .locked` 成对律 frontend-spec:479 只适用于"必须阻断交互"的场合）。
 *  副行 = 白名单三项（昵称/套餐/到期，`admin_accounts.py::_META_DISPLAY_KEYS`）
 *  + **登录态失效位**（2026-10-01 用户裁决：有续期就要看得见还有多久失效）。 */
function rowHTML(p, a) {
  const disp = a.display || {};
  const metaBits = [disp.nickname, disp.plan ? `套餐 ${disp.plan}` : "",
    disp.expires_at ? `到期 ${shortTime(disp.expires_at)}` : ""].filter(Boolean);
  const exp = loginStateBit(p, a);
  const subLine = [...(metaBits.length ? [esc(metaBits.join(" · "))] : []), exp].filter(Boolean).join(" · ");
  return `
    <tr data-acc="${esc(a.name)}" class="${a.enabled ? "" : "off"}">
      <td class="strong">
        <div class="mono">${esc(a.name)}</div>
        ${subLine ? `<div style="margin-top:4px;font-size:12px;font-weight:600;color:var(--text-faint)">${subLine}</div>` : ""}
      </td>
      <td class="num">${quotaCell(a)}</td>
      <td><span data-sw="${esc(a.name)}" style="display:inline-flex;align-items:center"></span></td>
      <td class="ops">${opsHTML(p, a)}</td>
    </tr>`;
}

/** 登录态失效位（数据源 = `a.credential_expires_at`，后端 `accounts/credexp` 提炼；
 *  "" = 未知——**可续期的产品才如实说"未知"**，不可续期产品不制造无意义的焦虑）。
 *  🔴 已过期（实测 raccoon 两号）：直说"需重新登录"——自动续期腿对 refresh_token 已死的
 *  账号记终态、不再重试，界面不能继续假装"将自动续期"。
 *  ≤2h → 警示色并注明"将自动续期"（cron 续期腿阈值 = `auto_renew.AUTO_RENEW_WITHIN_S`）。 */
function loginStateBit(p, a) {
  const iso = a.credential_expires_at;
  if (iso) {
    const ms = Date.parse(iso);
    const left = isFinite(ms) ? ms - Date.now() : Number.NaN;
    if (isFinite(left) && left <= 0) {
      return `<span style="color:var(--err);font-weight:700">登录态已过期（${esc(shortTime(iso))}），需重新登录</span>`;
    }
    const soon = isFinite(left) && left <= 2 * 3600 * 1000;
    return `<span${soon ? ' style="color:var(--warn);font-weight:700"' : ""}>登录态 ${esc(shortTime(iso))} 失效${soon ? "（≤2h，将自动续期）" : ""}</span>`;
  }
  return capsOf(p.id).refresh ? `<span style="color:var(--text-faint)">登录态失效时间未知</span>` : "";
}

/* ---------- 额度格（2026-10-01 重做：套餐识别 + 逐包余粮） ----------
 * 数据源 = `a.runtime.quota`（`query_balance` 动作落盘的快照；cron 周期刷新）。
 * 展示公式照抄 DSH Jet Hub（jet-hub.js:401-491 / credit-expiry.js）+ zcode-switch 账号行：
 *   套餐徽章（`plan`，取不到不编造）→ 粗体总额 + 量纲标签 → 附属分桶行（三选一：
 *   长期/每日、长期/临时、N 个资源包有效）→「另有 N 已失效」→ 查于时间 → 逐包明细进 tooltip。
 * 🔴「查不到」（unknown/无快照）与「余额 0」（exhausted）严格分型；负值在钩子已 clamp。
 * 🔴 老快照没有 `items` 键 → 退回四值口径（有余量 / 已耗尽 / 未知 / 尚未刷新），不装死。 */

/** 「临时」分桶窗口（DSH `PERMANENT_LOCK_EXPIRING_WINDOW_DAYS`，credits-capabilities.js:180-209）。 */
const EXPIRING_WINDOW_DAYS = 15;

/** 数值格式化：token 用 K/M 两位小数（zcode-switch fmtTokens 同款），其余两位小数封顶。 */
/** 中文量纲（照 ZCode-Panel 的 `fmtTokens`）：token ≥1e8 → 亿、≥1e4 → 万，其余带「 Token」；
 *  积分 / 余额按 DSH 插件的 `formatCredits`——整数原样、小数定 2 位（`472.2328` → `472.23`）。
 *  🔴 两套不混用：积分不写「万」（DSH 源码里明确否决过那种写法，实测 `9453.93万` 那种读不动）。 */
const trimTail = (s) => String(s).replace(/\.0+$/, "").replace(/(\.\d*[1-9])0+$/, "$1");

function fmtQuotaNum(v, unit) {
  const n = Number(v);
  if (!isFinite(n)) return "—";
  if (String(unit || "").toLowerCase().startsWith("token")) {
    const a = Math.abs(n);
    if (a >= 1e8) return trimTail((n / 1e8).toFixed(2)) + "亿";
    if (a >= 1e4) return trimTail((n / 1e4).toFixed(1)) + "万";
    return trimTail(String(Math.round(n * 100) / 100)) + " Token";
  }
  return Number.isInteger(n) ? String(n) : trimTail(n.toFixed(2));
}

/** 单位词：token 的量纲自带在数字里（亿/万/Token），不再缀；积分缀「积分」；
 *  无名单位（cline 的「余额」unit 为空）**不编单位词**。 */
function quotaUnitWord(unit) {
  const u = String(unit || "").toLowerCase();
  if (u.startsWith("token")) return "";
  if (u === "积分" || u === "credit" || u === "credits") return " 积分";
  return "";
}

/** 数据新鲜度 = **相对量**（三家参考一致：面板 `fmtAgo` / switch 的「1天前」）。
 *  绝对时刻不常驻面——它对"还能不能用"这个判断没有信息量，只在悬停里给。
 *  🔴 未来时刻（上游时钟偏 / 时区错）与超过 7 天都退回绝对串，不印「-3 小时前」也不印「8 天前」。 */
function agoShort(iso) {
  const raw = String(iso || "");
  const t = Date.parse(raw.replace(" ", "T"));
  if (!isFinite(t)) return "";
  const s = (Date.now() - t) / 1000;
  if (s < 0 || s >= 86400 * 7) return shortTime(raw);
  if (s < 60) return "刚刚";
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  if (s < 86400) return `${Math.floor(s / 3600)} 小时前`;
  return `${Math.floor(s / 86400)} 天前`;
}

/** 同名包聚合成一组（照 zcode-switch 的 raw 池去重：30+ 包不会变 30+ 行）。
 *  比参考更进一步做**求和**：CodeBuddy 实盘 31 个包里有 30 个同名「国内运营裂变包」，
 *  名称零信息量，用户要的是"这类一共还剩多少"。组内取**最早**到期时刻。 */
function quotaGroups(items) {
  const g = new Map();
  for (const it of items) {
    const key = String(it.name || "未命名包");
    let one = g.get(key);
    if (!one) {
      one = { name: key, unit: it.unit || "", rem: 0, tot: 0, hasRem: false, hasTot: false, exp: "", n: 1 };
      g.set(key, one);
    } else {
      one.n += 1;
    }
    if (typeof it.remaining === "number") { one.rem += it.remaining; one.hasRem = true; }
    if (typeof it.total === "number") { one.tot += it.total; one.hasTot = true; }
    const e = String(it.expires_at || "");
    if (ISO_RE.test(e) && (!one.exp || e < one.exp)) one.exp = e;
  }
  return [...g.values()].sort((x, y) => (y.hasTot ? y.tot : 0) - (x.hasTot ? x.tot : 0));
}

/** 占比条：画的永远是**剩余**（与 zcode-switch 同一条：条长 = 剩余占比，不是已用）。
 *  🔴 分母缺失 ⇒ **不画条**——条是"还剩几成"的声明，没有分母就没资格声明
 *  （ZCode-Panel 对拿不到 balances 的号也宁可写「用量未知」，不编 `500万/500万`）。
 *  色档阈值照 switch：剩余 ≤10% 红、≤30% 琥珀、其余绿。 */
function quotaBarHTML(rem, tot) {
  if (!(typeof tot === "number" && tot > 0) || typeof rem !== "number") return "";
  const pct = Math.max(0, Math.min(100, (rem / tot) * 100));
  const cls = pct <= 10 ? " is-low" : pct <= 30 ? " is-mid" : "";
  return `<span class="qbar${cls}" title="${esc("剩余 " + pct.toFixed(0) + "%")}"
    aria-hidden="true"><i style="width:${pct.toFixed(1)}%"></i></span>`;
}

/** ISO 形状谓词：上游 epoch 未归一时**不渲染时间**（页面兜底，不把脏值印给用户）。 */
const ISO_RE = /^\d{4}-\d{2}-\d{2}/;

/** 距到期不足窗口天（`expires_at` 取不到/非法 = 不算临时，保守归长期）。 */
function expiresSoon(iso) {
  if (!iso) return false;
  const t = Date.parse(iso);
  if (!isFinite(t)) return false;
  const days = (t - Date.now()) / 86400000;
  return days >= 0 && days <= EXPIRING_WINDOW_DAYS;
}

/** 附属标注（**不是第六档**，方案 §4-7）：`reason` → 注记文案。
 *  🔴 六档里的「冷却中/读取失败/未发起」是**附属注记**，额度档仍只有五档 ——
 *      V7/D6 的 exactly-one 判据靠这个区分成立（多一档状态就会当场打红）。 */
const QUOTA_NOTE = {
  circuit: "（冷却中）",
  "circuit-untrusted": "（熔断状态不可读）",
  unreachable: "（读取失败）",
  no_credentials: "（未发起）",
  no_identity: "（未发起）",
};
/* 「上游这一轮没说话」的档 —— 与后端 `ops/builtin/query_balance.SILENT` 同一份名单。
   这些档**保住上一轮的真实数值**（合并写），只在后面挂注记，绝不把数字洗成「未知」。 */
const QUOTA_SILENT = ["circuit", "circuit-untrusted", "unreachable", "no_credentials", "no_identity"];


/** 悬停 = **这一个额度格**的证据条：套餐名 + 数据绝对时刻 + 上游原话（`detail`）。
 *  🔴 挂在 `.qcell` **根节点**上，不挂在某个词上：用户悬停的对象是「额度」这一整格，
 *     挂在内部 span 上等于"鼠标差几像素就没证据看"（2026-10-03 真机门 D4/V13/V14 红的就是这条）。
 *  `fallback` = 上游连原话都没给时**这一档自己的说法**，证据条不留空。 */
function cellTip(rq, fallback) {
  const bits = [];
  if (rq) {
    if (rq.plan) bits.push(`套餐：${rq.plan}`);
    const when = rq.data_at || rq.checked_at;
    if (when) bits.push(`数据时刻：${shortTime(when)}`);
  }
  const raw = (rq && rq.detail) ? String(rq.detail) : (fallback || "");
  if (raw) bits.push(raw);
  return bits.join(" · ");
}

/** 格根：`warn` ⇒ 整格**着色**为 `var(--warn)`（D1b 的判据对象是**这一格**，不是格子里的某个词）。
 *  🔴 只给颜色不给字重：字重是"这一格里谁是主读数"的语言（见 base.css 的额度格字重档），
 *     整格加粗会把标签、明细一起喊成主读数（2026-10-03 用户实拍「怎么有的字体加粗有的不加粗」）。 */
function qcellOpen(tip, warn) {
  return `<div class="qcell${warn ? " is-warn" : ""}"${tip ? ` title="${esc(tip)}"` : ""}>`;
}

/** 无结构化 items 的档位（五档词表原样）：只有档名 + 注记，**不出 meta 行**——
 *  这是 2026-10-02 的定版（「已耗尽/未知/无套餐/尚未刷新」这四个早退档不排新鲜度行，
 *  注记已经挂在档名后面），本轮重做只搬家常驻面，不推翻这条。 */
function quotaPlainHTML(main, tip, warn) {
  return qcellOpen(tip, warn) + `<div class="qrow">${main}</div></div>`;
}

/** 额度格（🔴 2026-10-03 用户实拍重做：「参考 zcode-switch / ZCode Panel / Jet Hub，
 *  你在这里乱对齐一些乱七八糟信息放不下还弄个展开折叠」）。
 *  一屏只回答三个问题，其余一律不上常驻面：
 *    ① **还剩多少** = 剩余/总量 + 占比条（分子永远是剩余，中文量纲 亿/万）；
 *    ② **什么时候没** = 最早到期时刻（`至 MM-DD HH:mm`，仅 ISO 形状才渲染）；
 *    ③ **数多新** = 相对新鲜度（`刚刚 / N 分钟前 / N 小时前 / N 天前`），绝对时刻进悬停。
 *  删掉的三样（用户点名）：套餐名徽章（同产品同值、零决策价值 → 悬停）、
 *  「展开 N 个包」折叠交互（三家参考**都没有**折叠 → 同名聚合 + `+N 类`）、
 *  「重置于 / 查于」两条绝对时刻并排（读不出重点）。
 *  🔴 同名聚合后组数天然 ≤3 ⇒ 全量都在常驻面上，不存在「明细没出口」这件事
 *     （`POST …/quota` 的响应本来也不回 items，不为此加后端字段）。
 *  五档词表（`有余量 / 已耗尽 / 无套餐 / 未知 / 尚未刷新`）与附属注记**一字不改**——
 *  那是 2026-10-02 定版、V7/V13/V14 钉着的机器码映射，本轮只动呈现不动语义。 */
function quotaCell(a) {
  const rq = a.runtime && a.runtime.quota;
  if (!rq) {
    return quotaPlainHTML(`<span class="qnone">尚未刷新</span>`,
      "运行态里没有额度快照：网关还没查过这个账号（BUG-2 的可见态）");
  }
  const note = QUOTA_NOTE[rq.reason] || "";
  // 🔴 「无套餐」= 三态 `unknown` + `reason==="no_plan"`（没有第四态枚举，§22.3 冻结不动），
  //    且排在结构化分支之前：有没有 items 都必须出这一档（V14 的反向变异打的就是这条分支）。
  if (rq.reason === "no_plan") {
    return quotaPlainHTML(`<span class="qnone">无套餐${esc(note)}</span>`,
      cellTip(rq, "上游返回空套餐列表"));
  }
  const items = (Array.isArray(rq.items) ? rq.items : []).filter((it) => it && it.name);
  if (!items.length) {
    if (rq.state === "exhausted") {
      return quotaPlainHTML(`<span class="qtier">已耗尽${esc(note)}</span>`, cellTip(rq), true);
    }
    if (rq.state !== "available") {
      return quotaPlainHTML(`<span class="qnone">未知${esc(note)}</span>`,
        cellTip(rq, "上游未给出额度"));
    }
    // `有余量` 无 items：档名独占主行，注记按 2026-10-02 定版挂在 **meta 行末尾**（与结构化档同一把尺）。
    // 档位词一律走 `.qtier`（五档同字重）——漏了类的话它会退回 400，与「无套餐/未知」的 600 参差。
    return qcellOpen(cellTip(rq))
      + `<div class="qrow"><span class="qtier">有余量</span></div>`
      + quotaMetaHTML(rq, [], 0, note) + `</div>`;
  }
  const active = items.filter((it) => it.active !== false);
  const expiredN = items.length - active.length;
  const groups = quotaGroups(active);
  const unit = groups[0] ? groups[0].unit : "";
  const word = quotaUnitWord(unit);
  const fmt = (v) => fmtQuotaNum(v, unit);
  // 🔴 `remaining` 可能是 `null`（上游没给可用数）：**不得**当 0 累加、更**不得**因此判「已耗尽」
  //    ——「没给数字」与「数字是 0」是两件事（V13 钉的就是这条谎）。
  const anyRem = active.some((it) => typeof it.remaining === "number");
  const sumRem = active.reduce((acc, it) => acc + (typeof it.remaining === "number" ? it.remaining : 0), 0);
  const sumTot = active.reduce((acc, it) => acc + (typeof it.total === "number" ? it.total : 0), 0);
  const hasTot = active.some((it) => typeof it.total === "number");

  // 🔴 整格是否「已耗尽」在 out 之前就定下来：着色对象是**这一格**（D1b），
  //    只把档位词染琥珀、格子其余部分保持黑，等于"警示只有一行字"——读的人不知道整格在说什么。
  const exhausted = anyRem && (rq.state === "exhausted" || !active.length || (sumTot <= 0 && sumRem <= 0));

  const out = [];
  if (!anyRem) {
    out.push(`<div class="qrow"><span class="qnone">用量未知</span></div>`);
  } else {
    const val = `${esc(fmt(sumRem))}${word ? esc(word) : ""}`
      + (hasTot ? ` / ${esc(fmt(sumTot))}` : "");
    // 🔴 多组时主行标签必须是「合计」：实盘 lobsterai 的 `plan` 就等于其中一个包名
    //    （「新用户赠送」），拿 plan 当标签会出现"主行和明细同名不同数"的怪相。
    const many = groups.length > 1;
    const name = many ? "合计" : groups[0].name;
    // 🔴 2026-10-03 用户裁定「合计：900 积分」= **数值贴在标签后面**，不再右浮到列尾：
    //    旧形态左一个孤立标签、右一个粗数，中间一大片空档，读的人要自己把两头对起来。
    //    标签与数值同排左对齐；标签过长时**省略号只收在标签上**（`title` 给全名），
    //    数值 `flex:none` 永不裁字 —— 被挤的只能是次要的那一半（与占比条那轮同一分工）。
    out.push(`<div class="qrow"><span class="qname" title="${esc(name)}">${esc(name)}：</span>`
      + `<b class="qnum">${val}</b>`
      + (exhausted ? `<span class="qtier">已耗尽</span>` : "") + `</div>`);
    // 🔴 占比条**独占一行、画满格宽**（照 zcode-switch 的形态：文字在上、条在下）。
    //    内联在名称与数字之间 = 条的左边缘随两侧文字宽度漂移（用户实拍「进度条怎么还有错落啊」）；
    //    而"定宽三列"的修法则把数字挤到裁字（:8300 实测 `.qnum` 需 129px、只给到 90px）。
    //    条自占一行后，左边缘恒等于格的左边缘 ⇒ 对齐是**结构保证**，不靠列宽算式。
    const bar = quotaBarHTML(sumRem, hasTot ? sumTot : null);
    if (bar) out.push(`<div class="qbarline">${bar}</div>`);
  }
  // 多组：逐组明细**另起一行**（同名聚合 ≤3 + `+N 类`，ZCode-Panel 的 chip 上限同款）。
  // 🔴 同一轮里我试过把这一行并进「合计：」后面 —— :8300 只读探针实测：实盘长包名
  //    （「CodeBuddy个人版国内运营裂变包 1365.01 / 1400」）在 268px 的列里折成 **5~6 行**、
  //    整格 112px 高 ⇒ 用户裁定改回「合计：900 积分」+ 明细另起一行（选项①）。
  //    悬停给「同名 N 包合计」与各自量 ⇒ 聚合后组数本来就在 3 以内，既不必折叠也无从截断。
  if (groups.length > 1) {
    const chips = groups.slice(0, 3).map((g) => {
      const gv = g.hasRem ? fmtQuotaNum(g.rem, g.unit) : "未给";
      const gt = g.hasTot ? " / " + fmtQuotaNum(g.tot, g.unit) : "";
      return `<span class="qchip" title="${esc(g.name + "：" + gv + gt + (g.n > 1 ? "（同名 " + g.n + " 包合计）" : ""))}">${esc(g.name)} ${esc(gv + gt)}</span>`;
    }).join("");
    const more = groups.length - 3;
    const all = groups.map((g) => `${g.name} ${g.hasRem ? fmtQuotaNum(g.rem, g.unit) : "未给"}${g.hasTot ? "/" + fmtQuotaNum(g.tot, g.unit) : ""}`).join("\n");
    out.push(`<div class="qchips">${chips}`
      + (more > 0 ? `<span class="qchip qchip-more" title="${esc(all)}">+${more} 类</span>` : "")
      + `</div>`);
  }
  out.push(quotaMetaHTML(rq, groups, expiredN, note));
  // 证据条同样挂格根：`用量未知` 这一档上游原话没给时，兜底说法必须自己写清楚（V13）。
  return qcellOpen(cellTip(rq, anyRem ? "" : "上游未给可用数"), exhausted)
    + out.join("") + `</div>`;
}

/** meta 行 = 最早到期 + 相对新鲜度 + 失效计数 + 附属注记。
 *  🔴 时刻一律受 ISO 形状护栏约束（V17 的同一把尺）：上游给秒级 epoch 时**不渲染时刻**，
 *     而不是把 `1790956800` 切成 6 位残串印在用户面前。 */
function quotaMetaHTML(rq, groups, expiredN, note) {
  const bits = [];
  const exp = groups.map((g) => g.exp).filter(Boolean).sort()[0];
  if (exp) bits.push(`至 ${esc(shortTime(exp).slice(5))}`);
  const when = rq.data_at || rq.checked_at;
  const ago = agoShort(when);
  if (ago) bits.push(`${esc(ago)}查`);
  if (expiredN) bits.push(`另有 ${expiredN} 包已失效`);
  if (note) bits.push(esc(note));   // 注记原形带括号（QUOTA_NOTE 五档映射的形状，门 V15 按原形钉）
  // 🔴 meta 行**不自带悬停**：套餐名与数据绝对时刻的证据条统一挂在额度格根节点上（`cellTip`），
  //    同一件事有两个悬停主人 = 这一格里"乱七八糟"的来源之一。
  return `<div class="qmeta">${bits.join(" · ") || "—"}</div>`;
}

/** 行内动作 = **中文文字按钮**（2026-10-01 用户指示）：签到（能力门控）·
 *  **续期（能力门控，账号维度——同日用户裁决：从映射弹窗挪回行内）** · 探活 · 删除。 */
function opsHTML(p, a) {
  const c = capsOf(p.id);
  const out = [];
  if (c.checkin) {
    out.push(textOp("claim", `签到 / 领取 ${a.name}`, "签到 / 领取：结果按运营四类出口呈现（只有失败着色）", "签到"));
  }
  if (c.refresh) {
    out.push(textOp("refresh", `续期 ${a.name}`, "续期：刷新凭据并落盘（与启用位正交，停用账号也可续期；与额度无关）", "续期"));
  }
  // 🔴 「刷新额度」= 账号维度手动刷一次**只读**额度（2026-10-02 用户指令：每个产品都要有
  //    账号维度 + 产品维度刷新额度）。能力位 balance 门控 = 与卡头那颗、与后端端点同一判据。
  if (c.balance) {
    out.push(textOp("quota", `刷新额度 ${a.name}`,
      "刷新额度：只读上游额度，不改凭据、不消耗签到配额（zcode 走联网腿；其余产品同款钩子）", "刷新额度"));
  }
  out.push(textOp("probe", `探活 ${a.name}`, "探活：连通与凭据两个维度分开给结论", "探活"));
  // 🔴 「模型检测」= 账号维度逐模型真发一次最小请求（2026-10-02 用户指令：把「接入模型资源」
  //    的检测能力搬到账号侧）。范围只覆盖「模型映射」里**已开启**的那些模型
  //    （映射级开关关掉的不参与调度，检测它们没有意义）；会消耗该账号额度 ⇒ 按钮 title 说清。
  out.push(textOp("check", `模型检测 ${a.name}`,
    "模型检测：对该账号已开启的模型映射逐个发一次最小对话请求（真实出站，会消耗该账号额度），"
    + "逐个回结果：可用 / 不可用（附原因）/ 检测中", "模型检测"));
  out.push(textOp("delete", `删除 ${a.name}`, "删除账号（需二次确认；其关联资源置为停用并保留）", "删除", "danger"));
  return out.join("");
}

function textOp(op, label, title, text, extra = "") {
  return `<button class="btn btn-sm ${extra}" data-op="${op}" aria-label="${esc(label)}"
    title="${esc(title)}">${esc(text)}</button>`;
}

/* ---------- 绑定（D3：操作即落库，无「保存」按钮） ---------- */
function bindPanel(p) {
  if (!panelEl) return;
  const retry = panelEl.querySelector("#ac-retry");
  if (retry) retry.onclick = async () => { await fetchView(); paintRail(); paintPanel(); };
  const add = panelEl.querySelector("#ac-add");      // 唯一入口现在在卡头（与所作用的产品同框）
  if (add) add.onclick = () => openWizard(selectedProduct());
  const map = panelEl.querySelector("#ac-map");      // 每次重绘重绑（D3：绑在当下这颗钮上）
  if (map) map.onclick = () => openModelMap(rootEl, p);
  const claim = panelEl.querySelector("#ac-claim");  // 能力位 false 不渲染（§3 推翻死钮）
  if (claim) claim.onclick = () => batchClaim(claim, { product: p.id });
  const renew = panelEl.querySelector("#ac-renew");  // 批量续期（能力位 refresh 门控，同判据渲染）
  if (renew) renew.onclick = () => batchRenew(renew, p);
  const quota = panelEl.querySelector("#ac-quota");  // 产品级刷新额度（能力位 balance 同判据）
  if (quota) quota.onclick = () => batchQuota(quota, p);
  const zimp = panelEl.querySelector("#ac-zimport"); // ZCode 专属（headOpsHTML 里同判据渲染）
  if (zimp) zimp.onclick = () => openZImport(rootEl);
  const zshopBtn = panelEl.querySelector("#ac-zshop");
  if (zshopBtn) zshopBtn.onclick = () => openZShop(rootEl);
  if (!p) return;
  for (const a of p.accounts) bindRow(p, a);
}

function bindRow(p, a) {
  if (!panelEl) return;
  const sel = cssAttr(a.name);
  if (!sel) { paintPanel(); return; }                 // 账号名不在白名单形态 → 整面板重绘兜底
  const tr = panelEl.querySelector(`#ac-table tbody tr[data-acc="${sel}"]`);
  if (!tr) return;
  const sw = tr.querySelector("[data-sw]");
  if (sw) {
    sw.innerHTML = "";                                 // 重绘前清空，杜绝开关叠开关
    sw.append(switchEl(a.enabled, `启用 / 停用账号 ${a.name}`, (next) => setEnabled(p, a, next)));
  }
  for (const b of tr.querySelectorAll("[data-op]")) b.onclick = () => runOp(p, a, b.dataset.op, b);
  /* 🔴 2026-10-03 用户实拍「还弄个展开折叠，无语了」：逐包折叠交互**整体删除**
     （三家参考实现 zcode-switch / ZCode-Panel / Jet Hub 都没有折叠）。
     多包改由 `quotaCell` 做**同名聚合**（zcode-switch 同款：同名只留一条），
     聚合后组数天然 ≤3 ⇒ 全量本来就在常驻面上，既不必折叠也无从截断。 */
}

/** 三级重绘之第三级：单行原地替换；结构变化时退化为面板级重绘。 */
function patchRow(pid, name) {
  const p = productOf(pid) || selectedProduct();
  const a = p && p.accounts.find((x) => x.name === name);
  const sel = cssAttr(name);
  if (!panelEl || !p || !a || !sel) { paintPanel(); return; }
  const tr = panelEl.querySelector(`#ac-table tbody tr[data-acc="${sel}"]`);
  if (!tr) { paintPanel(); return; }
  const holder = document.createElement("tbody");
  holder.innerHTML = rowHTML(p, a);
  const head = holder.children[0];
  if (!head || !tr.replaceWith) { paintPanel(); return; }
  tr.replaceWith(head);
  bindRow(p, a);
}

/** 启停（1 击 + 1 请求，§4-5）。BD1 已落地 → title 可对两条腿都说实话。 */
async function setEnabled(p, a, next) {
  try {
    await POST(`/admin/api/accounts/${p.id}/${encodeURIComponent(a.name)}/${next ? "enable" : "disable"}`);
    toast(next ? `账号 ${a.name} 已启用，运营会纳入本账号` : `账号 ${a.name} 已停用：手动与定时运营都跳过（续期不受影响）`, "ok");
  } catch (e) {
    toast("启停失败：" + e.message, "err");
  }
  await refreshAfter(p.id, a.name);        // 落库为准（失败也重取，杜绝界面漂移）
  return false;                            // 视觉刷新交给重绘，开关自身不翻
}

/** 行操作后的统一收尾：重取视图 → rail + 单行重绘（**不动向导**，§4-2）。 */
export async function refreshAfter(pid, name) {
  await fetchView();
  paintRail();
  if (name) patchRow(pid, name); else paintPanel();
}

/* ---------- 批量动作的回执（2026-10-03 用户裁定：**不许固化显示**） ----------
 *
 * 用户原话（实拍 Raccoon 面板上那块常驻的「刷新 0 个 · 失败 0 个 · 未发起 2 个」+ 术语解释 +
 * 逐号列表）：「各类处理结果，不允许用这种形式固化显示。执行完毕，弹窗提示具体执行结果，
 * 3s 后自动消失，也可以手动关闭。参考设计规范进行设计」。
 *
 * 旧形态（我 2026-10-02 定版、现被推翻）有两处毛病：
 * ① 结果写进面板里一块常驻槽 ⇒ 下一批之前它一直挂在页面上，且会被整块重绘吃掉
 *    （所以才需要模块级文本 + `paintPanel()` 末尾回填 —— 那套机器本身就是病的补丁）；
 * ② 为了绕开「等待期用户已开弹窗 ⇒ 迟到回执会叠第二层遮罩」而写的**判遮罩**分支，
 *    把"提示"做成了"常驻块"的借口。
 *
 * 新出口 = `components.js::toastCard`（结果浮层）：执行完毕弹一条，**3s 自动消失 + × 手动关闭**。
 * 它不是 modal ⇒ 单层弹窗红线（`.modal-mask` ∈ {0,1}）由**构造**保证，不再需要判遮罩；
 * 面板里也不留任何回执位（权威状态在表里：回执发出前已按服务端重取过视图）。
 * 🔴 术语解释（「未发起」/「未参与」那段）挂**计数行悬停**，不进正文 ——
 *    3 秒是读完"计数 + 逐号结果"的时间，不是读定义的时间；定义不许做成必读正文。 */
function showBulkReceipt(title, { sum = "", note = "", rows = "", empty = "", tone = "" } = {}) {
  const html = (sum
    ? `<div class="t-sum"${note ? ` title="${esc(note)}"` : ""}>${sum}</div>` : "")
    + `<div class="t-rows">${rows || (empty ? `<div class="t-empty">${esc(empty)}</div>` : "")}</div>`;
  toastCard(title, html, { type: tone, ms: 3000 });
}

/** 逐号一行：名称（过长省略号 + `title` 全名）+ 可选明细 + 结果词（色只走令牌）。 */
function receiptRow(name, tag, tone = "", detail = "") {
  return `<div class="t-row"><span class="t-cell">`
    + `<span class="t-name" title="${esc(name)}">${esc(name)}</span>`
    + (detail ? `<span class="t-detail" title="${esc(detail)}">${esc(detail)}</span>` : "")
    + `</span><span class="t-tag${tone ? " " + tone : ""}">${esc(tag)}</span></div>`;
}

/* ---------- 行内操作 ---------- */
const accountPath = (pid, name) => `/admin/api/accounts/${pid}/${encodeURIComponent(name)}`;

async function runOp(p, a, op, btn) {
  if (op === "delete") return delAccount(p, a);
  if (op === "check") return openModelCheck(p, a);   // 自带弹窗与逐行状态，不参与行操作刷新链
  if (!btn) return;
  btn.disabled = true;                                    // 长操作防连点
  try {
    if (op === "probe") await doProbe(p, a);
    else if (op === "refresh") await doRefresh(p, a);
    else if (op === "quota") await doQuota(p, a);
    else if (op === "claim") await doClaim(p, a);
    else if (op === "onboarding") await doClaim(p, a, "claim_onboarding");
  } finally {
    btn.disabled = false;
    await refreshAfter(p.id, a.name);                     // 结果与视图一起刷新
  }
}

/* ---------- 模型检测（账号维度，2026-10-02 用户指令） ----------
 * 契约：
 *  · 范围 = `GET …/check-models` 返回的**已开启**映射（映射级开关关掉的不测，与调度同判据）；
 *  · 一次一条（同账号并发打上游容易进风控，且"检测中"逐行显形本来就是顺序语义）；
 *  · 三态：检测中（灰/橘交替闪烁）· 可用（蓝，附延迟）· 不可用（红，附**具体原因**原文）；
 *  · 🔴 单层弹窗：本弹窗内不再开第二层（frontend-spec §7.11 红线），也不放任何账号级动作；
 *  · 用户中途关窗 ⇒ 立刻停止后续请求（不后台继续烧额度，也不假装跑完）。 */
function checkRowHTML(it, i) {
  return `
    <div class="list-row mc-row" data-mc="${i}"
      style="padding:0;height:44px;gap:10px;${i ? "border-top:1px solid var(--border);" : ""}">
      <span class="mc-ico">${SCAN}</span>
      <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
        <span class="mono" style="font-weight:700">${esc(it.vendor_model)}</span>
        <span style="color:var(--text-faint);font-size:12px"> → ${esc(it.system_model)}</span>
      </span>
      <span class="mc-result" style="flex:none;max-width:46%;text-align:right">排队中</span>
    </div>`;
}

function checkBodyHTML(p, a, list, info) {
  const head = `
    <p style="margin:0 0 12px;font-size:13px;font-weight:600;color:var(--text-soft)">
      将向该账号逐个发起最小对话请求（1 条 ping · max_tokens=1）检测
      <b>${list.length}</b> 个已开启的模型 —— <b>真实出站，会消耗该账号额度</b>。</p>`;
  const warn = !list.length
    ? `<div class="alert alert-warn" style="margin-bottom:12px">
         <div>该账号没有任何**已开启**的模型映射，检测不会发出任何请求。
         要测别的模型，先到卡头的模型映射入口挂上目标，再打开进池开关。</div></div>`
    : (info.resource_enabled === false
      ? `<div class="alert alert-warn" style="margin-bottom:12px">该账号当前停用，
             其资源不参与调度；下面这些请求仍会真发（只为验证凭据与上游是否可用）。</div>` : "")
      + (info.mapped_off
        ? `<p class="form-hint" style="margin:0 0 12px">另有 ${info.mapped_off} 条映射处于关闭状态，
             不在本次检测范围内（关闭即不进资源池、不可对外调用）。</p>` : "");
  return `${head}${warn}
    ${list.length ? `<div class="list-card" id="ac-mc-list">${list.map(checkRowHTML).join("")}</div>` : ""}
    <p class="mc-summary form-hint" style="margin-top:12px" hidden></p>`;
}

async function openModelCheck(p, a) {
  const body = document.createElement("div");
  body.innerHTML = `<div class="loading">正在读取该账号已开启的模型映射…</div>`;
  const foot = document.createElement("div");
  foot.innerHTML = `<button class="btn">关闭</button>`;
  const [closeBtn] = foot.querySelectorAll("button");        // 引用必须在 modal() 之前取（§7.11）
  const dlg = modal({ title: `模型检测 · ${p.title} · ${a.name}`, body, footer: foot, wide: true });
  closeBtn.onclick = dlg.close;

  let info = {};
  try {
    info = await GET(`${accountPath(p.id, a.name)}/check-models`) || {};
  } catch (e) {
    body.innerHTML = `<div class="alert alert-err"><div class="alert-title">可检测模型读取失败</div>
      <div>${esc(e.message)}</div></div>`;
    return;
  }
  const list = info.models || [];
  body.innerHTML = checkBodyHTML(p, a, list, info);
  if (!list.length) return;

  const sum = body.querySelector(".mc-summary");
  let done = 0, okN = 0;
  const paint = (i, st, text) => {
    const row = body.querySelector(`[data-mc="${i}"]`);
    if (!row) return;
    row.classList.remove("mc-run", "mc-ok", "mc-fail");
    row.classList.add(st === "run" ? "mc-run" : st === "ok" ? "mc-ok" : "mc-fail");
    const cell = row.querySelector(".mc-result");
    if (cell) { cell.textContent = text; cell.title = text; }
  };
  for (let i = 0; i < list.length; i++) {
    if (!document.body.contains(body)) return;      // 用户已关窗 ⇒ 立即停手（不后台烧额度）
    paint(i, "run", "检测中");
    let res = null, err = "";
    try {
      res = await POST("/admin/api/resources/test",
        { resource: list[i].resource_id, model: list[i].vendor_model });
    } catch (e) { err = e.message || "检测请求失败"; }
    if (!document.body.contains(body)) return;
    if (res && res.ok) { okN += 1; paint(i, "ok", `可用 · ${res.latency_ms ?? "—"}ms`); }
    else paint(i, "fail", `不可用 · ${(res && res.error) || err || "上游未给出原因"}`);
    done += 1;
    if (sum) {
      sum.hidden = false;
      sum.textContent = `检测进度 ${done}/${list.length} · 可用 ${okN} · 不可用 ${done - okN}`;
    }
  }
  if (sum) sum.textContent = `检测完成 ${list.length} 个模型 · 可用 ${okN} · 不可用 ${list.length - okN}`;
}

/** 账号级刷新额度：成功后单行重绘就能看到新数值（`refreshAfter` 已负责重取视图）。 */
async function doQuota(p, a) {
  try {
    const r = await POST(`${accountPath(p.id, a.name)}/quota`);
    const cat = CATEGORIES[r.category] || { label: r.category, toast: "" };
    const bits = [cat.label || r.category];
    if (r.reason) bits.push(r.reason);
    toast(`账号 ${a.name} 额度刷新：${bits.join(" · ")}${r.detail ? "\n" + r.detail : ""}`, cat.toast);
  } catch (e) {
    toast("刷新额度失败：" + e.message, "err");
  }
}

/** 产品级刷新额度：三段计数 = 刷新 N · 失败 K · 未发起 J（后端 `receipt` 按 reason 码算，
 *  界面**不做中文串匹配**）；结果走 `showBulkReceipt`（就地槽 + 必要时弹窗）。 */
async function batchQuota(btn, p) {
  if (!btn || btn.disabled || !p) return;
  const label = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "执行中…";
  let r = null;
  try {
    r = await POST(`/admin/api/accounts/${p.id}/quota-all`, {});
  } catch (e) {
    toast("刷新额度失败：" + e.message, "err");
  }
  if (panelEl && panelEl.contains(btn)) { btn.innerHTML = label; btn.disabled = false; }
  await refreshAfter(p.id, null);           // 🔴 先重绘（拿到服务端最新额度），再落回执
  if (!r) return;
  const rc = r.receipt || {};
  // 🔴 逐号那一行的词**不能只看 `by_reason`**（:8300 实盘抓出来的假态）：`reason=""` 在后端是
  //    一格**多义**值 —— 既出现在 `success`（查到了）也出现在 `inactive`（查了但上游没给可量化余量，
  //    计入「未发起」J，见 `_quota_receipt` 的 ⚠️ 段）。旧写法 `reason || "已刷新"` 把后者也标成
  //    「已刷新」⇒ 同一张浮层里计数行说「未发起 2 个」、下面两行写「已刷新」，自己跟自己矛盾。
  //    定版 = 逐号词读**权威分桶**（`report.failed / success / inactive`）+ 原因码查既有词表。
  const rep = r.report || {};
  const reasons = rc.by_reason || {};
  const inList = (list, acc) => (list || []).some((x) => (typeof x === "string" ? x : x.account) === acc);
  const quotaWord = (acc) => {
    const code = String(reasons[acc] ?? "");
    if (inList(rep.failed, acc)) return ["失败", "is-err"];
    if (inList(rep.success, acc)) return ["已刷新", "is-ok"];
    if (code === "no_plan") return ["无套餐", "is-warn"];
    if (code === "expired") return ["凭据已失效", "is-warn"];
    if (code === "quota_net_off") return ["未发起（自动腿未授权）", "is-warn"];
    if (QUOTA_REASON_TEXT[code]) return [QUOTA_REASON_TEXT[code], "is-warn"];
    return ["未发起", "is-warn"];   // 含 `""`：查了但上游没给可量化余量（计数里就落在 J）
  };
  const rows = Object.keys(reasons).sort()
    .map((acc) => { const [tag, tone] = quotaWord(acc); return receiptRow(acc, tag, tone); }).join("");
  showBulkReceipt(`刷新额度 · ${p.title}`, {
    sum: `刷新 ${esc(String(rc.refreshed ?? 0))} 个 · 失败 ${esc(String(rc.failed ?? 0))} 个`
      + ` · 未发起 ${esc(String(rc.not_fired ?? 0))} 个`
      + (rc.not_participating ? ` · 未参与（停用）${esc(String(rc.not_participating))} 个` : "") + "。",
    note: "「未发起」= 熔断中 / 网络不可达 / 缺凭据（本轮未对上游发请求，上一轮的数值原样保留）"
      + "/ 查了但上游没给可量化余量；「未参与」= 这一轮没被执行到（账号锁没拿到 / 该产品下没有账号）。"
      + "停用账号照样查（额度是只读视图）。前两者与「未参与」都不是一回事。",
    rows, empty: "该产品下没有账号。",
    tone: (rc.failed ?? 0) > 0 ? "err" : "ok",
  });
}

async function doProbe(p, a) {
  try {
    const r = await POST(`${accountPath(p.id, a.name)}/probe`);
    if (r.ok) toast(`账号 ${a.name} 探活通过${r.detail ? "：" + r.detail : ""}`, "ok");
    /* 两维分开（§22.3）：`reachable=false` 只说明**没拿到响应**（含"凭据缺失未发请求"），
       不替上游下"不可达"的结论 → 原文给出去，不贴死刑标签。 */
    else toast(`账号 ${a.name} 探活未通过${r.reachable ? "（凭据无效）" : ""}：${r.detail || ""}`, "err");
  } catch (e) {
    toast("探活失败：" + e.message, "err");
  }
}

async function doRefresh(p, a) {
  try {
    await POST(`${accountPath(p.id, a.name)}/refresh`);
    toast(`账号 ${a.name} 凭据已续期`, "ok");
  } catch (e) {
    /* 409 = NotRefreshable 业务拒绝（不是故障）：中性回执 + 原文原因 */
    const nor = e.data && e.data.error && e.data.error.refreshable === false;
    toast((nor ? "不可续期：" : "续期失败：") + e.message, nor ? "" : "err");
  }
}

async function doClaim(p, a, endpoint = "claim") {
  try {
    const r = await POST(`${accountPath(p.id, a.name)}/${endpoint}`);
    const cat = CATEGORIES[r.category] || { label: r.category, toast: "" };
    toast(`账号 ${a.name}：${cat.label}${r.detail ? "（" + r.detail + "）" : ""}`, cat.toast);
  } catch (e) {
    toast("领取失败：" + e.message, "err");
  }
}

/** 删除：二次确认 + `?confirm=1`（缺省 400 且不动盘）+ 级联去向如实说明。 */
async function delAccount(p, a) {
  if (!await confirmDialog("删除账号",
    `确定删除 ${p.title} 的账号「${a.name}」？删除后其关联资源会被置为停用并保留`
    + `（统计与历史不丢：它的资源行只置为停用并保留，不再参与调度；该行不在「接入模型资源」页显示——`
    + `要彻底清除请在配置文件的 resources[] 里删掉它），账号凭据目录将被移除。`)) return;
  try {
    await POST(`${accountPath(p.id, a.name)}/delete?confirm=1`);      // 破坏性：必须显式确认
    toast(`账号 ${a.name} 已删除`, "ok");
  } catch (e) {
    toast("删除失败：" + e.message, "err");
  }
  await refreshAfter(p.id, null);                                     // 行已不在册 → 面板级重取
}

/* ---------- 展示口径辅助 ---------- */
const shortTime = (v) => String(v ?? "").replace("T", " ").slice(0, 16);

/** token 数压缩（与 models.js 同款 12px 辅助行格式，非规则副本）。 */
const fmtTok = (n) => n == null ? "—" :
  n >= 1048576 && n % 1048576 === 0 ? `${n / 1048576}M` :
  n % 1024 === 0 ? `${n / 1024}K` : String(n);

/** 属性选择器取值：账号名走 `store` 的白名单（`A-Za-z0-9_-`），非白名单形态一律退化重绘。 */
function cssAttr(name) {
  return /^[\w.\-]+$/.test(String(name)) ? String(name) : "";
}

/* ---------- 已登记缺口（只改前端约束下的诚实登记，未擅自补后端） ----------
 * ① `claim_onboarding` 无入口端点（BD7）：loomy/raccoon 能力位 `onboarding=true` 已在册，
 *    `api/admin_accounts.py` 未暴露该动作 → 按「未登记能力不渲染按钮」整体隐藏
 *    （`ONBOARDING_ENDPOINT_READY`）。
 * ② BD3b（`unservable_reason` 按产品/账号出口）未落地 → 设计书 §5 的「转发未接线」
 *    `.alert.alert-info` **整块不显示**（判据缺失不猜，也绝不硬编码产品 id）。
 * ③ BD5（每账号 `last_op`）未落地 → 「最近运营」**整列不出现**（§6）：会话内结果只走
 *    toast 回执，不做"刷新即清空却叫最近结果"的假列。
 * ④ `login/start` 不回传「本机接收端是否绑定成功」：BD4 的监听可能因端口占用/权限不足
 *    退化为粘贴通道，界面无法区分 → local_callback 文案只写"自动优先 + 没反应用兜底"。
 *    后端补一个 `callback_listening` 位后，这里可以改成确定语气。
 * ⑤ 「重新发起登录」不作废旧会话（新会话以本次为准，旧的由服务端 TTL 出表）：
 *    见 `paintFooter()` 的按钮序说明。
 * ⑥ 凭据导入端点 `/admin/api/accounts/import`（含设备冲突 409 的 reuse/regenerate 决策）
 *    已就绪但设计书 §6「明确不做」本轮不做导入 UI（冲突决策要独立交互设计）。
 * ⑦ 扫码型的**关窗仍然作废本次登录**（M7-C1 如实登记）：DSH 的缺陷是"轮询循环活在弹窗页里，
 *    关窗即断"（`raccoon-login-page.ts` / `loomy-wechat-login.ts` 的本地页模型）。本网关的
 *    节奏**不在**本页（页只做 2s 一次的触发，状态机在服务端 `login/poll`），但 ✕/遮罩按
 *    **BD2** 显式 `login/cancel` 作废会话 —— 这是本台网关自己的既定契约（用户主动关窗 = 放弃
 *    本次登录），不是 DSH 那个 bug，故**不**随本轮改；换发新码、长轮询读预算、出图三件事
 *    都已落在服务端（`upstream/{raccoon,loomy}/login.py`、`accounts/qr.py`）。
 * ⑧ **local_callback 的自动回跳没有推送通道**（M7-E 如实登记，M7-B 的正题）：
 *    接收端投递成功后凭据已**暂存在服务端会话**上，但服务端**不会**通知本页（trae 的
 *    `login_poll` 是显式 `NotImplementedError`，lobsterai 恒 pending；R-5/POLLABLE 又禁止
 *    本页对这两型轮询）→ 弹窗里回跳完成后，向导不会自动切到「已登录，待确认接入」。
 *    本轮的过渡处置：local_callback 型正文**恒显**「确定接入」，用户完成授权后自己点 →
 *    `/login/commit` 如实回报（成功即落盘；没接住 = "没有待确认的凭据"，可重试）。
 *    根治要把回跳结局推给页面（候选：接收端完成页 `postMessage` 给父窗口 / 一个不驱动产品
 *    钩子的会话状态端点）—— 两者都动契约面，归 M7-B「登录两步契约对齐」一并裁决。
 * ⑨ 弹窗侧的浏览器限制如实登记：弹窗拦截器可能把 `window.open` 拦掉（→ 面板切链接态，
 *    兜底 = 面板里恒在的可点链接）；第三方 Cookie 拦截这类 iframe 时代的老问题**不适用** ——
 *    弹窗是顶层浏览上下文，厂商页的 Cookie 是第一方（这也是弹窗优于 iframe 的另一面）。
 */
