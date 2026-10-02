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
 *   POST /admin/api/accounts/mappings                  批量初始化映射 {product, items}
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
import { modal, confirmDialog, toast, copyText, initSplitResize } from "../components.js";

/* ---------- 图标（Lucide 0.555.0，14×14 sw2；全站同契约） ---------- */
const PLUS = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>`;
const COPY = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>`;
const REFRESH = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>`;
const CHECKIN = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/><path d="m9 16 2 2 4-4"/></svg>`;
const LINK = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>`;
const PHONE = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="20" x="5" y="2" rx="2" ry="2"/><path d="M12 18h.01"/></svg>`;
const MAP = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m16 3 4 4-4 4"/><path d="M20 7H4"/><path d="m8 21-4-4 4-4"/><path d="M4 17h16"/></svg>`;
const SCAN = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><path d="M7 12h10"/></svg>`;
const IMPORT = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>`;
const SHOP = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>`;

/* ---------- 常量（判据表；不要在渲染里散落字面量） ---------- */

/** 登录形态文案（`LoginKind` 五型，§22.3） */
const KIND_TEXT = {
  device_code: "设备码授权", external_link: "外链授权",
  local_callback: "本机回跳", qr: "扫码", sms_code: "短信验证码",
};

/** 🔴 local_callback 与短信型**不得轮询**（R-5 / §22.3）：其 `login_poll` 恒 pending，
 *  结果只从「接收端自动回跳 / 地址栏粘贴」或「提交验证码」通道来。本表是唯一落点。 */
const POLLABLE = new Set(["device_code", "external_link", "qr"]);

/** 🔴 走「弹窗登录窗口」的形态集合（M7-E 修正轮；模式判据的唯一来源）。
 *  device_code / external_link / local_callback 的 `Challenge.url` 是**给浏览器看的登录页**；
 *  `qr` 的 `url` 是二维码**内容**（raccoon 的 `/login/mp?code=…`，也可能是 `weixin://`）、
 *  `sms_code` 的交互全在本页表单 —— 这两型不开窗口（照搬"url 即网页"的假设会弹出一个
 *  不是给浏览器看的东西）。 */
const WINDOW_KINDS = new Set(["device_code", "external_link", "local_callback"]);

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

const POLL_MS = 2000;          // 登录轮询间隔（仅 POLLABLE 形态）
const POLL_MAX_FAILS = 5;      // 连续轮询失败上限（网络抖动不无限刷）
const TICK_MS = 1000;          // 会话 TTL 倒计时刷新
const PRODUCT_STORE = "mgw-accounts-product";       // §4-4 上次选中产品
const FILTER_STORE = "mgw-accounts-only-with";      // §1.3 派生开关（默认关）

/* ---------- 页面状态（模块级：三级重绘的共享面） ---------- */
let view = null;               // GET /admin/api/accounts（唯一数据源；操作后必重取）
let selected = null;           // 当前选中产品 id
let rootEl = null;             // 页面 root（drawShell 每路由一次）
let railEl = null;             // 产品 rail（role=tablist 容器）
let filterEl = null;           // 「只看有账号」开关所在容器（条件渲染）
let panelEl = null;            // 右侧配置区容器
let wizard = null;             // 登录向导会话 —— **只有 stopWizard() 置空**（§4-2）
let onlyWith = false;          // §1.3 派生筛选（默认不隐藏产品）
let deepMiss = "";             // 深链 `?p=` 未命中的 id（§4-4 要在 `.value` 注明）
let loadError = "";            // §5 读失败：保留上次数据 + 重试

/** 能力位取用点：`/admin/api/accounts` 已内嵌 `capabilities`（§4-1 单 GET 的红证落点）。 */
const capsOf = (pid) => {
  const p = productOf(pid);
  return (p && p.capabilities) || {};
};

const productOf = (pid) => (view && view.products || []).find((p) => p.id === pid) || null;
const selectedProduct = () => productOf(selected);

/* ---------- 入口：1 个 GET + 深链 + 一次性 shell ---------- */
export async function renderAccounts(root) {
  rootEl = root;
  const prevSelected = selected;          // 换产品要清回执，同产品重绘必须留着（下面比对用）
  onlyWith = readStore(FILTER_STORE) === "1";
  await fetchView();
  /* §4-4 深链优先，其次上次记忆，最后 registry 原序首项（= view.products[0]）。
     选中项不在册时回落并登记 `deepMiss`，由卡头 `.value` 如实注明。 */
  const asked = productFromHash() || readStore(PRODUCT_STORE);
  const hit = asked && productOf(asked) ? asked : null;
  deepMiss = asked && !hit ? asked : "";
  const first = view && view.products[0] ? view.products[0].id : null;
  selected = hit || first;
  /* 上次记忆的产品可能被派生开关（§1.3）滤出选择轴：选中项必须在 rail 可见集里，
     否则面板与 rail 的选中态会各说各话 → 退到可见集首项。 */
  const visible = railScope().ids;
  if (visible.length && !visible.includes(selected)) selected = visible[0];
  if (!productOf(selected)) selected = first;
  /* 🔴 产品变了就清回执 —— 判据落在**这里**（渲染入口）而不是只落在 `selectProduct()`：
     深链 `#/accounts?p=y` 与派生开关回落都不经过那颗 rail 点击函数，
     实盘实测到"从 qoder（1 个号）深链切到 zcode，槽里还挂着『刷新 1 个』"。
     同一产品的重绘**不清**（PM B-R4-5 要的就是迟到回执在重绘后仍可见）。 */
  if (prevSelected && prevSelected !== selected) clearBulkReceipt();
  drawShell();
}

/** 服务端视图重取（失败不抛：§5 保留上次数据 + 面板给「重试」）。 */
async function fetchView() {
  try {
    view = await GET("/admin/api/accounts");
    loadError = "";
  } catch (e) {
    loadError = e.message || "账号视图读取失败";
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
        <button class="btn btn-sm" id="ac-claim-all" style="margin:0 12px 8px;width:calc(100% - 24px)"
          title="对所有支持签到的产品（能力位 checkin=True）的全部已启用账号执行签到 / 领取">${CHECKIN}一键签到</button>
        <div id="ac-filter"></div>
        <div class="subnav-scroll" role="tablist" aria-orientation="vertical"
          aria-label="产品列表" id="ac-rail"></div>
      </aside>
      <main>
        <div id="ac-panel"></div>
      </main>
    </div>`;
  railEl = root.querySelector("#ac-rail");
  filterEl = root.querySelector("#ac-filter");
  panelEl = root.querySelector("#ac-panel");
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

/** 产品图标：用各产品**官方图标**（参考程序从官方客户端资源提取，落 `web/static/img/products/`；
 *  其中 lobsterai/qoder/trae/loomy 是 SVG，其余 PNG）。`alt` = 首字母，图缺失时浏览器就地显示它。 */
const ICON_SVG = new Set(["lobsterai", "qoder", "trae", "loomy"]);
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
            role="tab" aria-selected="${pid === selected ? "true" : "false"}"
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
      onlyWith = next;
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
  selected = pid;
  deepMiss = "";                 // 回落注记只对入站深链/记忆有意义：用户已自己选定产品
  writeStore(PRODUCT_STORE, pid);
  clearBulkReceipt();            // 🔴 切产品即清空批量回执：上一批的结论不属于这个产品
                                 //    （槽是产品级 DOM，`paintPanel()` 会把模块级文本回填进**新**面板）
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
  renderBulkReceipt();                     // 🔴 重绘之后回填：回执文本住模块级，不住 DOM
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
      ${bulkReceiptHTML()}
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
function kindHint(kind) {
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
        <th>账号</th><th>状态</th>
        <th class="num">额度</th><th class="num">操作</th>
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
      <td><span data-sw="${esc(a.name)}" style="display:inline-flex;align-items:center"></span></td>
      <td class="num">${quotaCell(a)}</td>
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
function fmtQuotaNumber(v, unit) {
  if (unit === "token" && Math.abs(v) >= 1000) {
    return v >= 1e6 ? (v / 1e6).toFixed(2) + "M" : (v / 1e3).toFixed(2) + "K";
  }
  return String(Math.round(v * 100) / 100);
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

/** 额度格（2026-10-02 五档定版）。数据面 = `runtime.json.quota`，**没有快照**才叫「尚未刷新」。 */
function quotaCell(a) {
  const rq = a.runtime && a.runtime.quota;
  if (!rq) {
    return `<span style="color:var(--text-faint)" title="运行态里没有额度快照：网关还没查过这个账号（BUG-2 的可见态）">尚未刷新</span>`;
  }
  const note = QUOTA_NOTE[rq.reason] || "";
  // 🔴 「无套餐」= 三态 `unknown` + `reason==="no_plan"`（**没有第四态枚举**，§22.3 冻结不动）。
  //    它排在「未知」之前、也排在结构化分支之前：无论有没有 items 都必须出这一档
  //    （V14 的反向变异打的就是这条分支）。
  if (rq.reason === "no_plan") {
    return `<span style="color:var(--text-faint)" title="${esc(rq.detail || "上游返回空套餐列表")}">无套餐${esc(note)}</span>`;
  }
  const items = (Array.isArray(rq.items) ? rq.items : []).filter((it) => it && it.name);
  if (!items.length) {
    if (rq.state === "exhausted") return `<span style="color:var(--warn)">已耗尽${esc(note)}</span>`;
    if (rq.state !== "available") {
      return `<span style="color:var(--text-faint)" title="${esc(rq.detail || "上游未给出额度")}">未知${esc(note)}</span>`;
    }
    // 附属标注同样要挂上：熔断/读取失败轮里 `state` 仍是上一轮的 `available`，
    // 不挂注记就等于把"这一轮没查成"说成"刚刚查过且有余量"（门探针实测到的漏注记分支）。
    return `<span>有余量</span>${chkHTML(rq, note)}`;
  }
  const active = items.filter((it) => it.active !== false);
  const expiredN = items.length - active.length;
  const unit = items[0].unit || "";
  const unitLabel = unit.toLowerCase() === "token" ? " Token" : " 积分";
  // 🔴 `remaining` 可能是 `null`（上游没给出可用数）：**不得**当 0 累加、更**不得**因此判「已耗尽」
  //    —— "没给数字" 与 "数字是 0" 是两件事，把前者渲染成后者是本轮点名的谎（工程 r3 B-R3-3）。
  const nums = active.filter((it) => typeof it.remaining === "number");
  const sum = (arr) => arr.reduce((acc, it) => acc + (typeof it.remaining === "number" ? it.remaining : 0), 0);
  const fmt = (v) => fmtQuotaNumber(v, unit);
  const daily = active.filter((it) => String(it.name).includes("每日"));
  const rest = active.filter((it) => !String(it.name).includes("每日"));
  const total = sum(active);
  const out = [];
  if (rq.plan) out.push(`<span class="badge b-gray" style="margin-bottom:4px" title="${esc("套餐：" + rq.plan)}">${esc(rq.plan)}</span>`);
  if (!nums.length) {
    out.push(`<span style="color:var(--text-faint)" title="${esc(rq.detail || "上游未给出可用数")}">未知</span>`);
  } else if (rq.state === "exhausted" || !active.length || total <= 0) {
    // 🔴 档位词「已耗尽」**不挂量纲** —— 写成「已耗尽 Token」是把单位接在一个不是数字的词后面，
    //    实盘实测到（15:35 那一轮 `axxshx…` 等 4 号）。数值照旧出（`0 Token`，与 Σactive 一致，
    //    V10' 的总额一致性才成立），档位紧跟其后，着色仍取 `--warn`（门 D1b 钉的是颜色不是拼接）。
    const zero = nums.length ? `<b>${esc(fmt(total) + (unit ? unitLabel : ""))}</b> ` : "";
    out.push(`${zero}<span style="color:var(--warn)">已耗尽${esc(note)}</span>`);
  } else {
    out.push(`<b>${esc(fmt(total) + (unit ? unitLabel : ""))}</b>`);
  }
  const buckets = [];
  if (daily.length && rest.length) buckets.push(`长期 ${esc(fmt(sum(rest)))} · 每日 ${esc(fmt(sum(daily)))}`);
  else if (active.length > 1) buckets.push(`${active.length} 个资源包有效`);
  if (expiredN) buckets.push(`另有 ${expiredN} 已失效`);
  // 🔴 「重置于 X」= **active 包里最早**的 `expires_at`（方案 §4-5 定义，不是"临期"的另一种说法）。
  //    仅当该值是 ISO 形状时才渲染 —— 上游给的是**秒级 epoch 整数**，归一化是钩子的责任；
  //    万一某条通道漏归一，这里**整段不出**，而不是把 `1790956800` 切成 `956800` 印给用户（V17）。
  const isoExp = active.map((it) => it.expires_at).filter((v) => ISO_RE.test(String(v || "")))
    .sort()[0];
  if (isoExp) buckets.push(`重置于 ${esc(shortTime(isoExp).slice(5))}`);
  if (buckets.length) {
    out.push(`<span style="display:block;margin-top:4px;font-size:12px;font-weight:600;color:var(--text-faint)">${buckets.join(" · ")}</span>`);
  }
  out.push(chkHTML(rq, note));
  // 🔴 逐包明细走**就地展开**（frontend-spec §7.11 三正解之一），不再只住 tooltip：
  //    31 个包时悬停既不可选中也不能复制，且被截断到 12 行 —— 用户以为只有 12 个包。
  //    常驻面仍只有「档位 + 总额 + 分桶 + 查于」，展开行才是逐包全量（一行都不藏）。
  out.push(`<button class="btn btn-sm" data-qpacks="${esc(a.name)}" aria-expanded="false"
    title="${esc("展开后在本格逐包列出（可选中复制）；收起不影响任何数据")}"
    style="margin-top:4px">展开 ${items.length} 个包</button>`);
  out.push(packsDetailHTML(a, rq, items));
  return `<span style="display:inline-block;text-align:right"
    title="${esc(rq.plan ? "套餐：" + rq.plan : "")}">${out.join("")}</span>`;
}

/** 本格内的逐包明细（默认 hidden，点「展开 N 个包」显形）：全量列出，一行都不截断。
 *  🔴 时刻仍受 ISO 形状护栏约束（V17 的同一把尺）：上游给秒级 epoch 时**不渲染时刻**，
 *     而不是把 `1790956800` 切成 6 位残串印在用户面前。 */
function packsDetailHTML(a, rq, items) {
  const unit = items[0].unit || "";
  const fmt = (v) => fmtQuotaNumber(v, unit);
  const unitLabel = unit ? (unit.toLowerCase() === "token" ? " Token" : " 积分") : "";
  const sumAll = items.reduce((acc, it) =>
    acc + (typeof it.remaining === "number" ? it.remaining : 0), 0);
  const activeN = items.filter((it) => it.active !== false).length;
  const lines = items.map((it) => {
    const rem = typeof it.remaining === "number" ? `${fmt(it.remaining)}${unitLabel}` : "上游未给可用数";
    const tot = typeof it.total === "number" ? ` / 总额 ${fmt(it.total)}` : "";
    const exp = ISO_RE.test(String(it.expires_at || "")) ? ` · 失效于 ${shortTime(it.expires_at)}` : "";
    const st = it.active === false ? "（已失效）" : "";
    return `<div class="qpack-line">· ${esc(it.name)}${st}：${esc(rem + tot + exp)}</div>`;
  }).join("");
  return `
    <div class="qpacks-detail" data-qpacks-for="${esc(a.name)}" hidden
      style="text-align:left;margin-top:6px;font-size:12px;line-height:1.7;color:var(--text-soft)">
      <div style="color:var(--text-faint);font-weight:700">共 ${items.length} 个包（有效 ${activeN} 个）
        · 合计剩余 ${esc(fmt(sumAll))}${esc(unitLabel)} · 数据时刻 ${esc(shortTime(rq.data_at || rq.checked_at))}</div>
      ${lines}
    </div>`;
}

/** 「查于 X」= **上游数据时刻优先**（`data_at`），没有才退回网关写盘时刻（`checked_at`）。
 *  两个量必须分开：熔断/失败轮里上游什么都没给，此时"查于"若前进到本轮，
 *  就等于把十几分钟前的数值说成刚刚查过的（QA r3 X-R3-6 判的"伪装刷新"）。 */
function chkHTML(rq, note = "") {
  const when = rq.data_at || rq.checked_at;
  return `<span class="qchk" style="display:block;margin-top:2px;font-size:12px;font-weight:600;color:var(--text-faint)">查于 ${esc(shortTime(when))}${esc(note || "")}</span>`;
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
  /* 逐包明细就地展开（2026-10-02 用户指令：明细不该只住 tooltip）。
     展开态记在**数据行**的 data-open 上，重绘后据此恢复（否则刷一次额度就自己收起）。 */
  const btn = tr.querySelector("[data-qpacks]");
  const detail = tr.querySelector(`.qpacks-detail[data-qpacks-for="${sel}"]`);
  if (btn && detail) {
    const apply = (open) => {
      detail.hidden = !open;
      btn.setAttribute("aria-expanded", open ? "true" : "false");
      btn.textContent = open ? "收起明细" : `展开 ${(a.runtime && a.runtime.quota && a.runtime.quota.items || []).length} 个包`;
      tr.dataset.open = open ? "1" : "";
    };
    apply(tr.dataset.open === "1");
    btn.onclick = () => apply(detail.hidden);
  }
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
async function refreshAfter(pid, name) {
  await fetchView();
  paintRail();
  if (name) patchRow(pid, name); else paintPanel();
}

/* ---------- 批量动作的回执（🔴 单层弹窗红线的构造化落点） ----------
 *
 * 项目红线：任意交互序列后 `.modal-mask` 计数 ∈ {0,1}（frontend-spec §7.11/§8-13 + 规矩 16）。
 * `components.js::modal()` 是**追加不是替换**，而批量腿的形状天生危险：
 *   页级按钮 → 长 await（产品级扇出是**分钟级**窗口）→ 迟到回执。
 * 用户在等待期顺手点开「模型映射」→ 回执到达时页面上已经有一层遮罩 → 直接开第二层就违规。
 *
 * v4 的"就地槽 + 判遮罩"写法被 PM r5 判为**半个修法**：槽会被随后的整块重绘吃掉。
 * 因此这里把**文本**存进模块级 `bulkReceipt`，由 `paintPanel()` 末尾回填 ——
 * 送达不再依赖"记得按顺序调用"，红线与可见性都由构造保证。
 * 切产品 / 换页 / 再次触发批量动作时清空（旧结论不留在新画面上）。 */
let bulkReceipt = null;

/** 槽的骨架（每次面板重绘都会重建；文本由 `renderBulkReceipt()` 回填）。 */
function bulkReceiptHTML() {
  return `<div class="bulk-receipt" id="ac-receipt" hidden></div>`;
}

function renderBulkReceipt() {
  if (!panelEl || !bulkReceipt) return;
  const slot = panelEl.querySelector("#ac-receipt");
  if (!slot) return;
  slot.innerHTML = bulkReceipt.html;
  slot.hidden = false;
  const close = slot.querySelector("[data-receipt-close]");
  if (close) close.onclick = () => clearBulkReceipt();
}

/** 清空批量回执：模块级文本与**当前画面上那个槽**一起清。
 *
 *  🔴 只清 `bulkReceipt` 变量不够：槽的 DOM 要等下一次 `paintPanel()` 才重绘，
 *  于是"新批次在飞的几十秒里，屏幕上仍挂着**上一批**的结论"—— 实盘实测到
 *  （连点两个产品的「刷新额度」，第二个产品的回执位一度还写着第一个产品的「刷新 2 个」，
 *  而它那一批只有 1 个号）。产品级扇出是分钟级窗口，这个错位不是边角料。 */
function clearBulkReceipt() {
  bulkReceipt = null;
  if (!panelEl) return;
  const slot = panelEl.querySelector("#ac-receipt");
  if (!slot) return;
  slot.hidden = true;
  slot.innerHTML = "";
}

/** 批量回执的唯一出口：有遮罩 → 只写就地槽（**不开第二层**）；无遮罩 → 弹窗 + 同文入槽兜底。 */
function showBulkReceipt(title, html) {
  bulkReceipt = { title, html };
  const masked = document.querySelector(".modal-mask");
  if (!masked) {
    const body = document.createElement("div");
    body.innerHTML = html;
    const foot = document.createElement("div");
    foot.innerHTML = `<button class="btn">关闭</button>`;
    const closeBtn = foot.querySelector(".btn");        // modal() 之前取引用（§7.11 契约）
    const dlg = modal({ title, body, footer: foot });
    closeBtn.onclick = dlg.close;
  }
  renderBulkReceipt();                                   // 遮罩存在时这是**唯一**出口；否则是兜底
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
         要测别的模型，先到卡头「模型映射」里挂上并把「进池」开关打开。</div></div>`
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
  clearBulkReceipt();                       // 上一批的结论不留在这一批的画面上（槽也要清）
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
  const rows = Object.entries(rc.by_reason || {}).map(([acc, reason]) => `
    <div class="list-row" style="display:flex;gap:8px;align-items:center;min-height:40px">
      <b class="mono" style="flex:1;min-width:0">${esc(acc)}</b>
      <span class="badge ${reason ? "b-gray" : "b-ok"}">${esc(reason || "已刷新")}</span>
    </div>`).join("");
  const html = `
    <p class="form-hint" style="margin:0 0 12px">
      刷新 ${esc(String(rc.refreshed ?? 0))} 个 · 失败 ${esc(String(rc.failed ?? 0))} 个 ·
      未发起 ${esc(String(rc.not_fired ?? 0))} 个${rc.not_participating ? ` · 未参与（停用）${esc(String(rc.not_participating))} 个` : ""}。
    </p>
    <p class="form-hint" style="margin:0 0 12px">「未发起」= 熔断中 / 网络不可达 / 缺凭据（本轮未对上游发请求，
      上一轮的数值原样保留）/ 查了但上游没给可量化余量；「未参与」= 这一轮没被执行到
      （账号锁没拿到 / 该产品下没有账号）。停用账号照样查（额度是只读视图）。前两者与「未参与」都不是一回事。</p>
    ${rows || `<p class="form-hint" style="margin:0">该产品下没有账号。</p>`}`;
  showBulkReceipt(`刷新额度结果 · ${p.title}`, html);
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

/* ---------- 模型映射（产品内部模型 → 网关模型）与批量签到 / 领取 ----------
 * 契约（后端随本轮落地，前端按冻结 payload 实现，不预判字段）：
 *   GET  /admin/api/accounts/{product}/catalog → {product,title,checkin,source,models[],accounts[]}
 *        （ModelInfo 全字段随 asdict 带出——映射行的目录辅助信息即来源于此，**无需第二个弹窗**；
 *         单账号 `/{product}/{name}/models` 是 B-1 生产出口，仅后端/测试消费，界面不再调用）
 *   POST /admin/api/accounts/mappings          {product, items:[{model,target}]}
 *   POST /admin/api/accounts/claim-all         {product} 或 {product:null}（null = 全部支持签到的产品）
 * 两处共用纪律：动作期间触发钮进「执行中…」禁用态（顺序执行可达数十秒，**不加人为超时**）；
 * 结果一律从响应 payload 出（失败只报原文，不编造成功）；写完重取服务端视图自同步（D3）。
 */

/** 模型映射弹窗（root = 页面 root，落库后按 models.js `persist(root)` 同款口径重绘本页）。
 *  🔴 **宽版 + 单层弹窗**（2026-10-01 用户定版：弹窗里绝不许再叠弹窗——需要更多信息就
 *  加宽弹窗、把信息融合进列表或就地展开）。目录字段（上下文/输出/推理…）直接画进映射行。 */
async function openModelMap(root, p) {
  if (!p) return;
  const body = document.createElement("div");
  body.innerHTML = `<div class="loading">正在读取模型目录…</div>`;
  const foot = document.createElement("div");
  foot.innerHTML = `<button class="btn">取消</button>
    <button class="btn btn-primary" disabled>初始化映射</button>`;
  /* 必须在 modal() **之前**取引用（components.js 会把 footer 子节点平铺走，§7.11） */
  const [cancelBtn, okBtn] = foot.querySelectorAll("button");
  const dlg = modal({ title: `模型映射 · ${p.title}`, body, footer: foot, wide: true });
  cancelBtn.onclick = dlg.close;
  let catalog = null;
  try {
    const [cat, cfg, enums] = await Promise.all([
      GET(`/admin/api/accounts/${p.id}/catalog`),
      GET("/admin/api/config"),
      GET("/admin/api/enums"),
    ]);
    catalog = cat || {};
    const options = targetOptions((cfg && cfg.models) || [], (enums && enums.entries) || []);
    body.innerHTML = mapBodyHTML(catalog, options, p);
    /* 没账号 = 没有资源可挂：目录照常可看，落库按钮禁用（写了也挂不上，只会在配置里留空映射）。 */
    okBtn.disabled = !(catalog.accounts || []).length;
    /* 行开关：状态存在 mapOn（渲染态与配置态在点成功后一起更新），关掉时行变灰但保留映射。 */
    const mapOn = new Map();
    (catalog.models || []).forEach((m, i) => { mapOn.set(i, m.map_enabled !== false); });
    const rowOf = (i) => body.querySelector(`[data-mapsw="${i}"]`)?.closest(".list-row");
    const repaintState = (i) => {
      const row = rowOf(i);
      if (!row) return;
      const m = (catalog.models || [])[i] || {};
      const mapped = (m.mapped_to || []).filter(Boolean);
      const on = mapOn.get(i);
      const cell = row.children[3];
      if (cell) cell.innerHTML = !mapped.length ? `<span class="badge b-gray">未映射</span>`
        : on ? `<span class="badge b-ok" title="${esc("已映射到：" + mapped.join("、"))}">已映射 · 进池</span>`
             : `<span class="badge b-gray" title="${esc("已映射到：" + mapped.join("、") + "；当前关闭：不进资源池、不出现在 /v1/models")}">已映射 · 已关</span>`;
      row.style.opacity = on ? "" : "0.6";
    };
    const mountSwitch = (i, on) => {
      const holder = body.querySelector(`[data-mapsw="${i}"]`);
      if (!holder) return;
      const m = (catalog.models || [])[i] || {};
      holder.replaceChildren();
      holder.append(switchEl(on, `进池开关 ${m.name || m.id}`, () => togglePool(i)));
    };
    /* 单行开关 = 一次即时落库（D3 操作即保存）：目标取当前下拉值，
       落点仍是后端那个 (产品, 模型) 组的全部账号条目；失败把原因留在槽内并按原态重挂。 */
    const togglePool = async (i) => {
      const m = (catalog.models || [])[i] || {};
      const select = body.querySelector(`select[data-idx="${i}"]`);
      const target = String((select && select.value) || (m.mapped_to || [])[0] || "");
      if (!target) { toast("该条目还没有映射目标，先选系统模型", "warn"); return; }
      const next = !mapOn.get(i);
      mountSwitch(i, next);                            // 先落到目标态并禁二次点击（执行中）
      try {
        const r = await POST("/admin/api/accounts/mappings",
          { product: p.id, items: [{ model: m.id, target, enabled: next }] });
        mapOn.set(i, next);
        m.map_enabled = next;
        m.mapped_to = m.mapped_to && m.mapped_to.length ? m.mapped_to : [target];
        repaintState(i);
        const n = next ? (r.turned_on ?? 0) : (r.turned_off ?? 0);
        toast(next ? `已进池（${n} 个账号的映射）`
                   : `已移出资源池（${n} 个账号的映射，映射关系保留）`, "ok");
      } catch (e) {
        const slot = body.querySelector("#ac-map-err");
        if (slot) slot.innerHTML = `
          <div class="alert alert-err" style="margin-bottom:12px"><div class="alert-title">开关写入失败</div>
            <div>${esc(e.message)}</div></div>`;
        mountSwitch(i, mapOn.get(i));                  // 回到落库前的真实态，不假装成功
      }
    };
    body.querySelectorAll("[data-mapsw]").forEach((holder) => mountSwitch(Number(holder.dataset.mapsw), mapOn.get(Number(holder.dataset.mapsw))));
  } catch (e) {
    body.innerHTML = `
      <div class="alert alert-err"><div class="alert-title">模型目录读取失败</div>
        <div>${esc(e.message)}</div></div>`;
    return;
  }
  okBtn.onclick = async () => {
    const models = catalog.models || [];
    const items = [];
    for (const select of body.querySelectorAll("select[data-idx]")) {
      const target = String(select.value || "");
      const i = Number(select.dataset.idx);
      const m = models[i];
      // 空值 = 跳过（用户显式没选）；开关态一并带上，否则"初始化映射"会把刚关掉的行悄悄拨回进池
      if (m && target) items.push({ model: m.id, target, enabled: mapOn.get(i) !== false });
    }
    okBtn.disabled = true;
    try {
      const r = await POST("/admin/api/accounts/mappings", { product: p.id, items });
      toast(`新增映射 ${r.added ?? 0} 条（已存在 ${r.already ?? 0} 条）`, "ok");
      dlg.close();
      await repaintPanel(root);
    } catch (e) {
      const slot = body.querySelector("#ac-map-err");
      if (slot) slot.innerHTML = `
        <div class="alert alert-err" style="margin-bottom:12px"><div class="alert-title">映射写入失败</div>
          <div>${esc(e.message)}</div></div>`;
      okBtn.disabled = !(catalog.accounts || []).length;
    }
  };
}

/** 弹窗体：来源行（服务端口径原样给出，含 fallback 的如实声明）+ 账号操作区 + 表头 + 逐模型一行。
 *  状态列只报事实：`mapped_to` 非空 = 已映射（目标名进 title 悬停可见），空 = 未映射（不猜）。
 *  🔴 2026-10-01 用户定版：**目录字段直接画进行内**（上下文/输出/推理/图片/工具——取不到不展示），
 *  原「模型目录」二级弹窗废除（弹窗套弹窗 = 用户明令禁止的交互，frontend-spec §7.11 红线）。 */
function mapBodyHTML(cat, options, p) {
  const models = cat.models || [];
  const src = cat.source || {};
  const grid = "display:grid;grid-template-columns:minmax(0,1.4fr) 60px 196px 104px 72px;gap:12px;align-items:center";
  const th = (t) => `<span style="font-size:12px;font-weight:700;color:var(--text-faint)">${t}</span>`;
  const head = `
    <p class="form-hint" style="margin:0 0 12px">${esc(src.detail || "目录来源未说明")}</p>
    ${(cat.accounts || []).length ? "" : `
    <div class="alert alert-warn" style="margin-bottom:12px">
      该产品还没有账号：目录可查看，但映射要等「接入账号」后才有资源可挂。</div>`}
    <div id="ac-map-err"></div>`;
  if (!models.length) {
    return `${head}<p class="form-hint" style="margin:0">目录为空：未读到该产品的模型条目。</p>`;
  }
  const rows = models.map((m, i) => {
    const mapped = (m.mapped_to || []).filter(Boolean);
    // 状态三态：未映射 / 已映射·进池 / 已映射·已关（`map_enabled` 由后端与调度读同一个位）
    const on = m.map_enabled !== false;
    const state = !mapped.length
      ? `<span class="badge b-gray">未映射</span>`
      : on
        ? `<span class="badge b-ok" title="${esc("已映射到：" + mapped.join("、"))}">已映射 · 进池</span>`
        : `<span class="badge b-gray" title="${esc("已映射到：" + mapped.join("、") + "；当前关闭：不进资源池、不出现在 /v1/models")}">已映射 · 已关</span>`;
    const sw = mapped.length
      ? `<span data-mapsw="${i}" title="${esc(on ? "开启：该映射进资源池，可对外调用" : "关闭：该映射不进资源池，不可对外调用（映射关系保留，随时可拨回）")}"></span>`
      : `<span style="color:var(--text-faint);font-size:12px">—</span>`;
    return `
      <div class="list-row" style="${grid}">
        <span style="min-width:0">
          <b>${esc(m.name || m.id)}</b>
          <span style="display:block;font-size:12px;color:var(--text-faint);margin-top:4px">
            <span class="mono">${esc(m.id)}</span>${modelFactsHTML(m)}</span>
        </span>
        <span>${ruleHTML(m)}</span>
        <select class="in" data-idx="${i}" style="width:100%" aria-label="映射目标 ${esc(m.name || m.id)}"
          >${optionHTML(options, pickTarget(m, options))}</select>
        <span>${state}</span>
        <span style="display:flex;justify-content:flex-end">${sw}</span>
      </div>`;
  }).join("");
  return `${head}
    <div class="list-card">
      <div class="list-row" style="${grid}">${th("模型")}${th("规则")}${th("目标网关模型")}${th("状态")}${th("进池")}</div>
      ${rows}
    </div>
    <p class="form-hint" style="margin-top:12px">行内辅助信息 = 目录字段（上下文 / 输出 / 推理 / 图片 / 工具——
      取不到的不展示，不编造）；目录来源见顶部。<b>「进池」开关</b>：开 = 该映射参与资源池并可被对外调用；
      关 = 不进资源池、不出现在 /v1/models（映射关系与账号凭据都保留，随时可拨回）。</p>`;
}

/** 目录字段辅助段（拼在模型 ID 后；只列上游明确给出的事实，None/缺省一律不展示）。 */
function modelFactsHTML(m) {
  const facts = [
    m.context_window != null ? `上下文 ${fmtTok(m.context_window)}` : "",
    m.max_output != null ? `输出 ${fmtTok(m.max_output)}` : "",
    m.reasoning === true
      ? `深度推理${(m.effort_levels || []).length ? `（${m.effort_levels.join("/")}）` : ""}` : "",
    m.image_input === true ? "图片输入" : "",
    m.tool_call === true ? "工具调用" : "",
  ].filter(Boolean);
  return facts.length ? ` · ${esc(facts.join(" · "))}` : "";
}

/** 消耗规则：显式 `free:true` → 免费徽章；否则非空 `rate` 文本；都没有 = `—`（**不冒充免费**）。 */
function ruleHTML(m) {
  if (m.free === true) return `<span class="badge b-brand">免费</span>`;
  if (m.rate) return `<span class="mono">${esc(m.rate)}</span>`;
  return `<span style="color:var(--text-faint)">—</span>`;
}

/** 目标下拉选项：跳过 → 网关现有模型（可直接挂资源）→ 内置目录里**尚未接入**的（`新建：`，服务端建档）。
 *  同名按 value 去重，现有模型优先（同一目标不会出现两个选项）。 */
function targetOptions(cfgModels, enumEntries) {
  const opts = [{ value: "", label: "跳过" }];
  const seen = new Set([""]);
  for (const m of cfgModels) {
    const n = m && m.name;
    if (n && !seen.has(n)) { seen.add(n); opts.push({ value: n, label: n }); }
  }
  for (const e of enumEntries) {
    const n = e && e.name;
    if (n && !seen.has(n)) { seen.add(n); opts.push({ value: n, label: `新建：${n}` }); }
  }
  return opts;
}

/** 预选：`suggest.confidence >= 0.7` 且该目标**真在下拉里** → 选中；否则「跳过」。
 *  🔴 不在下拉（= 网关没有这个模型）时不得硬塞一个不存在的 value —— 原生 select 会
 *  找不到匹配项而显示空白，看着像已选、提交时却什么也没选。 */
function pickTarget(m, options) {
  const s = m.suggest;
  const name = s && typeof s.confidence === "number" && s.confidence >= 0.7 ? String(s.name || "") : "";
  return name && options.some((o) => o.value === name) ? name : "";
}

const optionHTML = (options, cur) => options.map((o) =>
  `<option value="${esc(o.value)}"${o.value === cur ? " selected" : ""}>${esc(o.label)}</option>`).join("");

/** 批量签到 / 领取（卡头「一键领取」与子侧栏「一键签到」共用）：
 *  `payload.product = null` = 全部支持签到的产品（谁参与由后端按能力位判，前端不筛）。 */
async function batchClaim(btn, payload) {
  if (!btn || btn.disabled) return;
  clearBulkReceipt();            // 与另两条批量腿同一条纪律：新批次在飞时不留上一批结论
  const label = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "执行中…";
  let r = null;
  try {
    r = await POST("/admin/api/accounts/claim-all", payload);
  } catch (e) {
    toast("批量执行失败：" + e.message, "err");
  }
  btn.innerHTML = label;                   // 钮可能已被重绘替换：改的是旧节点也不影响页面
  btn.disabled = false;
  await refreshAfter(selected, null);      // 🔴 先重绘（运营会改额度快照，且整块 innerHTML 重建）
  if (r) showClaimAllResult(r);            // 再落回执：反序则回执刚写进槽就被自己的重绘吃掉
}

/** 批量续期（2026-10-01 用户裁决：产品维度批量续期，窗口 = 5h 内失效）：
 *  `POST /admin/api/accounts/{product}/refresh-due`（缺省窗口由后端 `BATCH_RENEW_WITHIN_S` 定）。
 *  回执只说"动了谁"：续期 / 失败 / 失效时间未知（不猜、不续）三类分开列。 */
async function batchRenew(btn, p) {
  if (!btn || btn.disabled || !p) return;
  clearBulkReceipt();
  const label = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "执行中…";
  let r = null;
  try {
    r = await POST(`/admin/api/accounts/${p.id}/refresh-due`, {});
  } catch (e) {
    toast("批量续期失败：" + e.message, "err");
  }
  btn.innerHTML = label;                   // 钮可能已被重绘替换：改旧节点不影响页面
  btn.disabled = false;
  await refreshAfter(p.id, null);          // 🔴 先重绘（整块 innerHTML 重建）
  if (r) showRenewResult(r);               // 再落回执 —— 顺序反了回执就被自己抹掉（PM r5 B-R4-5）
}

function showRenewResult(r) {
  const SKIP_TEXT = { "no-expiry": "未续（失效时间未知）", cooldown: "冷却中（30 分钟内已续过）",
    terminal: "需重新登录（上游判不可续期）" };
  const rows = (r.results || []).map((x) => `
    <div class="list-row" style="display:flex;gap:8px;align-items:center;min-height:40px">
      <b class="mono" style="flex:1;min-width:0">${esc(x.account)}</b>
      ${x.skipped ? `<span class="badge b-gray">${esc(SKIP_TEXT[x.skipped] || "未续")}</span>`
        : x.ok ? `<span class="badge b-ok">已续期</span>` : `<span class="badge b-err">失败</span>`}
      <span style="color:var(--text-muted);font-size:12px">${esc(x.detail || "")}</span>
    </div>`).join("");
  const sk = r.skipped || {};
  const bits = [`续期 ${r.renewed} 个`, `失败 ${r.failed} 个`];
  if (sk["no-expiry"]) bits.push(`失效时间未知 ${sk["no-expiry"]} 个`);
  if (sk.cooldown) bits.push(`冷却中 ${sk.cooldown} 个`);
  if (sk.terminal) bits.push(`需重新登录 ${sk.terminal} 个`);
  const html = `
    <p class="form-hint" style="margin:0 0 12px">窗口 ${esc(String(r.within_hours))} 小时内到期的账号：
      ${esc(bits.join(" · "))}。</p>
    ${rows || `<p class="form-hint" style="margin:0">该窗口内没有到期的账号（未发起任何续期）。</p>`}`;
  // 🔴 走 `showBulkReceipt` 这**一条**出口（不再自己 `modal()`）：批量腿的形状是
  //    "页级按钮 → 长 await → 迟到回执"，无条件开弹窗在"等待期用户已开映射弹窗"的序列里
  //    会叠出第二层遮罩 = 撞单层弹窗红线；文本同时进就地槽 ⇒ 重绘后仍看得见。
  const p = productOf(r.product);
  showBulkReceipt(`批量续期结果 · ${p ? p.title : r.product}`, html);
}

/** 批量结果弹窗：摘要行 + 每参与账号一行（分类 + 明细）；**只有失败着红**（行级 claim 同口径）。 */
function showClaimAllResult(r) {
  const p = r.product ? productOf(r.product) : null;
  showBulkReceipt(`批量签到结果 · ${p ? p.title : "全部支持签到的产品"}`, claimReportHTML(r));
}

function claimReportHTML(r) {
  const rep = r.report || {};
  const details = r.details || {};
  const people = r.participants || [];
  const none = `<p class="form-hint" style="margin:0">没有可参与的账号（全部停用/无账号）。</p>`;
  if (rep.no_participants || !people.length) return none;
  const sum = `成功 ${(rep.success || []).length} · 已领 ${(rep.already_done || []).length}`
    + ` · 未参与 ${(rep.inactive || []).length} · 失败 ${(rep.failed || []).length}`;
  const grid = "display:grid;grid-template-columns:minmax(0,1fr) 64px minmax(0,1.6fr);gap:12px;align-items:center";
  return `
    <p style="margin:0 0 12px;font-size:13px;font-weight:700;color:var(--text-soft)">${esc(sum)}</p>
    <div class="list-card">${people.map((name) => {
      const d = details[name] || {};
      const cat = String(d.category || "");
      const failed = cat === "failed";
      return `
      <div class="list-row" style="${grid}">
        <span class="mono" style="font-weight:700">${esc(name)}</span>
        <span style="font-size:12px;font-weight:700;color:${failed ? "var(--err)" : "var(--text-muted)"}"
          >${esc(CLAIM_LABEL[cat] || cat || "—")}</span>
        <span style="font-size:12px;font-weight:500;color:var(--text-faint)">${esc(d.detail || "—")}</span>
      </div>`;
    }).join("")}</div>`;
}

/** 批量动作后的重绘（服务端为准）：重取视图 → rail + 面板。
 *  `root` 用于壳被重建过时重新锚定面板（正常路径与 drawShell 捕获的是同一节点）。 */
async function repaintPanel(root) {
  await fetchView();
  const panel = root && root.querySelector ? root.querySelector("#ac-panel") : null;
  if (panel) panelEl = panel;
  paintRail();
  paintPanel();
}

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
const Z_PRODUCT = "zcode";               // 两颗入口的唯一门控（只有 ZCode 有本机工具与一元小店）
const ZSHOP_STORE = "mgw.zshop.orders";
const ZSHOP_STORE_MAX = 5;
const ZSHOP_POLL_MS = 2500;
let zshop = null;                        // 购买账号弹窗会话 —— **只有 stopZShop() 置空**

/* ---------- 导入账号（ZCode 专属） ---------- */

/** 导入账号弹窗：打开即读 `import/sources`（本机两工具的账号目录），三段式（粘贴 JSON / 本机工具 / 选文件）。 */
async function openZImport(root) {
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
function openZShop(root) {                          // root 仅为调用点签名一致；落点统一走 repaintPanel(rootEl)
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
function switchEl(on, label, onToggle) {
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

function openWizard(p) {
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
function paintFooter(st) {
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
function stopWizard() {
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
function openLoginWindow(st) {
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
async function settle(st, r) {
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
