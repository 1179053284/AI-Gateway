/** 账号接入（tech-design §22.7 · M6-4b · M7-UI 改版设计书 `docs/changes/design-accounts-list-v2.md`）
 *
 * 骨架 A「扁平产品 rail + 单产品账号工作区」（设计书 §1/§2）：
 *   左子侧栏 = 10 行 `.anchor-item` 产品选择器（**无 .group-card / 无 .mode-btn / 无「族」轴**
 *   ——族层是前端臆造的，见设计书 §0-1）＋ 右侧撑满配置区 = 账号表（唯一列表单位）。
 *   接入入口全页唯一：`.subnav-foot .side-add`（§2-注，resources.js:175-178 定版范式）。
 *   实现词汇（协议 / 出站基址 / 设备身份字段 / 目录来源 / 能力位 / 网关资源 / 池额度）
 *   一律降级到展开详情行 `.req-detail`（§3「移出常驻面」，logs.js:149-151 先例）。
 *
 * 数据面（**打开页面只有 1 个 GET**，§4-1）：
 *   GET  /admin/api/accounts                全产品账号视图，能力位已内嵌
 *        （`api/admin_accounts.py::accounts_view` = `{**asdict(ProductMeta), models_wired, accounts}`）
 *        → 本页**不再**调 `/admin/api/accounts/capabilities`（§4-1 判据：两个 GET 变一个）。
 *          该端点仍在册（`api/admin_accounts.py::capabilities_matrix`，消费方只剩
 *          `tests/integration/test_admin_accounts.py` 与 `test_m6_a1_wiring.py`，前端已无第二个调用页）。
 *   GET  /admin/api/accounts/{product}/{name}/models   模型目录（B-1 生产出口）
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
 *   · **额度数据源 = `a.runtime.quota`**（落盘快照 `{state, source, detail, checked_at}`），
 *     `a.quota` 是网关额度池（`remaining-reserved`，**量纲不同不得混列**，只进展开行）。
 *     四值口径：有余量 / 已耗尽 / 未知 / **尚未刷新**（§3：「网关还没查过」≠「查了但拿不到」）。
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
import { modal, confirmDialog, toast, copyText } from "../components.js";

/* ---------- 图标（Lucide 0.555.0，14×14 sw2；全站同契约） ---------- */
const PLUS = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>`;
const TRASH = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 11v6"/><path d="M14 11v6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`;
const COPY = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>`;
const HEART = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 9.5a5.5 5.5 0 0 1 9.591-3.676.56.56 0 0 0 .818 0A5.49 5.49 0 0 1 22 9.5c0 2.29-1.5 4-3 5.5l-5.492 5.313a2 2 0 0 1-3 .019L5 15c-1.5-1.5-3-3.2-3-5.5"/><path d="M3.22 13H9.5l.5-1 2 4.5 2-7 1.5 3.5h5.27"/></svg>`;
const REFRESH = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>`;
const CHECKIN = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/><path d="m9 16 2 2 4-4"/></svg>`;
const AWARD = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15.477 12.89 1.515 8.526a.5.5 0 0 1-.81.47l-3.58-2.687a1 1 0 0 0-1.197 0l-3.586 2.686a.5.5 0 0 1-.81-.469l1.514-8.526"/><circle cx="12" cy="8" r="6"/></svg>`;
const LINK = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>`;
const PHONE = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="20" x="5" y="2" rx="2" ry="2"/><path d="M12 18h.01"/></svg>`;
const CATALOG = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 5h13"/><path d="M13 12h8"/><path d="M13 19h8"/><path d="M3 10a2 2 0 0 0 2 2h3"/><path d="M3 5v12a2 2 0 0 0 2 2h3"/></svg>`;
const MAP = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m16 3 4 4-4 4"/><path d="M20 7H4"/><path d="m8 21-4-4 4-4"/><path d="M4 17h16"/></svg>`;
const IMPORT = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>`;
const SHOP = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>`;
const CHEV_R = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>`;
const CHEV_D = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>`;

/* ---------- 常量（判据表；不要在渲染里散落字面量） ---------- */

/** 登录形态文案（`LoginKind` 五型，§22.3） */
const KIND_TEXT = {
  device_code: "设备码授权", external_link: "外链授权",
  local_callback: "本机回跳", qr: "扫码", sms_code: "短信验证码",
};

/** 上游协议文案（`ProductMeta.protocol`）——**只进展开行**（设计书 §3 / 门 L-A10）。 */
const PROTOCOL_TEXT = {
  openai: "OpenAI 兼容", anthropic: "Anthropic 兼容", custom: "产品专属出站塑形",
};

/** 模型目录来源文案（`ProductMeta.models_source` 三形态）——同样只进展开行。 */
const SOURCE_TEXT = { remote: "远端目录", cache: "磁盘缓存", static: "本地静态表" };
const sourceText = (v) => `${SOURCE_TEXT[v] || "未知来源"}（${v || "?"}）`;

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
let expanded = new Set();      // 展开行：`${product}/${name}`
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
const rowKey = (pid, name) => `${pid}/${name}`;

/* ---------- 入口：1 个 GET + 深链 + 一次性 shell ---------- */
export async function renderAccounts(root) {
  rootEl = root;
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
        <div class="nav-group-title" style="padding:12px 12px 0">接入产品</div>
        <button class="btn btn-sm" id="ac-claim-all" style="margin:0 12px 8px;width:calc(100% - 24px)"
          title="对所有支持签到的产品（能力位 checkin=True）的全部已启用账号执行签到 / 领取">${CHECKIN}一键签到</button>
        <div id="ac-filter"></div>
        <div class="subnav-scroll" role="tablist" aria-orientation="vertical"
          aria-label="接入产品" id="ac-rail"></div>
      </aside>
      <main>
        <div id="ac-panel"></div>
      </main>
    </div>`;
  railEl = root.querySelector("#ac-rail");
  filterEl = root.querySelector("#ac-filter");
  panelEl = root.querySelector("#ac-panel");
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
      ${metaLineHTML(p)}
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
          ${p.id === Z_PRODUCT ? `
          <button class="btn btn-sm" id="ac-zimport"
            title="从本机 ZCode 工具导入账号，或粘贴 JSON 导入">${IMPORT}导入账号</button>
          <button class="btn btn-sm" id="ac-zshop"
            title="购买账号（YouYu Shop：一元买一个可用账号）；买完复制账号 JSON 走「导入账号」或直接一键导入">${SHOP}购买账号</button>` : ""}
          <button class="btn btn-sm btn-primary" id="ac-add" style="margin-left:auto">${PLUS}接入账号</button>
        </span>`;
}

/** 「本产品」一行元信息（数据驱动的差异面：登录形态 / 能力位 / 转发是否接线）。
 *  🔴 只放**产品之间确实不同**的事实，不放协议 base_url 这类实现细节（那些进展开行）。
 *  这一行就是为了回答"所有产品接入都是一样的么"——不一样，且差别在这里看得见。 */
function metaLineHTML(p) {
  const c = p.capabilities || {};
  const bits = [`${esc(loginText(p))}`];
  if (c.checkin) bits.push("可签到 / 领取");
  bits.push(c.refresh ? "可续期" : "不可续期");
  if (c.onboarding) bits.push("有新手任务");
  bits.push(p.models_wired ? "模型转发已接线" : "模型转发未接线");
  return `
      <div style="padding:0 16px 12px;color:var(--text-muted);font-size:12px;font-weight:600">
        ${bits.join(" · ")}
      </div>`;
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

function loginText(p) {
  const alts = (p.login_alt || []).map((k) => KIND_TEXT[k] || k);
  return (KIND_TEXT[p.login] || p.login) + (alts.length ? ` / ${alts.join(" / ")}` : "");
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

/* ---------- 账号表：4 列固定列集（§3；表头逐字，门 V6） ---------- */
function tableHTML(p) {
  return `
      <div class="table-wrap"><table class="tbl" id="ac-table"><thead><tr>
        <th class="exp"></th><th>账号</th><th>状态</th>
        <th class="num">额度</th><th class="num">操作</th>
      </tr></thead><tbody>
        ${p.accounts.map((a) => rowHTML(p, a) + detailHTML(p, a)).join("")}
      </tbody></table></div>`;
}

/** 账号行（§3 四列）。停用行只加 `.off`、**有意不加 `.locked`**：停用账号仍需可探活/删除
 *  （`.off + .locked` 成对律 frontend-spec:479 只适用于"必须阻断交互"的场合——设计书 §3
 *  已把这条区别写明，免得下一轮被当漏洞"顺手补上"）。副行只列白名单三项（昵称/套餐/到期，
 *  `admin_accounts.py::_META_DISPLAY_KEYS`），`via`/`phone`/`email` 是实现词汇不上常驻面。 */
function rowHTML(p, a) {
  const disp = a.display || {};
  const sub = [disp.nickname, disp.plan ? `套餐 ${disp.plan}` : "",
    disp.expires_at ? `到期 ${shortTime(disp.expires_at)}` : ""].filter(Boolean).join(" · ");
  const unknown = a.status === "unknown";
  const stateText = !a.enabled ? "已停用" : unknown ? "状态未知" : "已启用";
  /* §5：单账号读不动 → 「状态未知」+ 中性色（`admin_accounts.py` 的 fail closed 语义
     不含任何凭据有效性判断，所以既不说「启用」也不着红色，原文进展开行）。 */
  return `
    <tr data-acc="${esc(a.name)}" class="${a.enabled ? "" : "off"}">
      <td class="exp" data-exp="${esc(a.name)}" title="展开详情">${expanded.has(rowKey(p.id, a.name)) ? CHEV_D : CHEV_R}</td>
      <td class="strong">
        <div class="mono">${esc(a.name)}</div>
        ${sub ? `<div style="margin-top:4px;font-size:12px;font-weight:600;color:var(--text-faint)">${esc(sub)}</div>` : ""}
      </td>
      <td>
        <span data-sw="${esc(a.name)}" style="display:inline-flex;align-items:center;gap:8px"></span>
        <span style="font-size:12px;font-weight:600;color:var(--text-muted)"
          title="${esc(unknown ? "状态未知：运行态文件读不动（fail closed），原文见展开行；这不是「凭据无效」的结论"
            : a.enabled ? "启用位只决定运营是否纳入本账号（手动与定时两条腿同判据）；不含凭据有效性事实"
              : "已停用：手动与定时运营都跳过本账号；探活与删除仍可用，续期与启用位无关")}">${esc(stateText)}</span>
      </td>
      <td class="num">${quotaCell(a)}</td>
      <td class="ops">${opsHTML(p, a)}</td>
    </tr>`;
}

/** 额度格四值口径（§3；优先运行态快照 → 退池摘要 → 无快照写「尚未刷新」）。
 *  🔴 BUG-1 的本体修复：旧实现只读 `a.quota`（网关池摘要），从不读 `a.runtime.quota`。 */
function quotaCell(a) {
  const rq = a.runtime && a.runtime.quota;
  if (!rq) return `<span style="color:var(--text-faint)" title="运行态里没有额度快照：网关还没查过（BUG-2 的可见态）">尚未刷新</span>`;
  if (rq.state === "available") return `<span>有余量</span><span style="display:block;margin-top:4px;font-size:12px;font-weight:600;color:var(--text-faint)">查于 ${esc(shortTime(rq.checked_at))}</span>`;
  if (rq.state === "exhausted") return `<span style="color:var(--warn)">已耗尽</span>`;
  return `<span style="color:var(--text-faint)" title="${esc(rq.detail || "上游未给出额度")}">未知</span>`;
}

/** 行内动作 ≤3 颗（§3）：签到（能力门控）· 探活 · 删除。续期/目录/新手任务在展开行。 */
function opsHTML(p, a) {
  const c = capsOf(p.id);
  const out = [];
  if (c.checkin) {
    out.push(iconOp("claim", `签到 / 领取 ${a.name}`, "签到 / 领取：结果按运营四类出口呈现（只有失败着色）", CHECKIN));
  }
  out.push(iconOp("probe", `探活 ${a.name}`, "探活：连通与凭据两个维度分开给结论", HEART));
  out.push(iconOp("delete", `删除 ${a.name}`, "删除账号（需二次确认；其关联资源置为停用并保留）", TRASH, "danger"));
  return out.join("");
}

function iconOp(op, label, title, svg, extra = "") {
  return `<button class="icon-btn sm ${extra}" data-op="${op}" aria-label="${esc(label)}"
    title="${esc(title)}">${svg}</button>`;
}

/* ---------- 展开详情行：实现词汇全部降级到这里（§3「移出常驻面」，信息只换层级不删） ---------- */
function detailHTML(p, a) {
  if (!expanded.has(rowKey(p.id, a.name))) return "";
  const cap = capsOf(p.id);
  const dev = (p.device && p.device.fields) || [];
  const devVals = dev.map((f) => `${f}=${(a.device && a.device[f]) ? "已登记" : "缺"}`).join(" + ");
  const bits = [];
  if (p.base_url) bits.push(`出站基址：${esc(p.base_url)}`);
  bits.push(`协议：${esc(PROTOCOL_TEXT[p.protocol] || p.protocol)}`);
  bits.push(`登录方式：${esc(loginText(p))}`);
  bits.push(`模型目录来源：${esc(sourceText(p.models_source))} · 目录出口${p.models_wired ? "已接线" : "未接线"}`);
  if (dev.length) {
    bits.push(`设备身份字段：${esc(dev.join(" + "))}${p.device.derive ? "（可由账号标识派生）" : ""} · 本账号：${esc(devVals)}`);
  }
  const yn = (v) => (v ? "支持" : "不支持");
  bits.push(`能力位：签到 ${esc(yn(cap.checkin))} · 续期 ${esc(yn(cap.refresh))} · 余额 ${esc(yn(cap.balance))} · 永久积分锁 ${esc(yn(cap.permanent_lock))} · 新手任务 ${esc(yn(cap.onboarding))}`);
  bits.push(esc(resourceLine(a)));
  bits.push(esc(poolLine(a)));
  if (a.runtime_error) bits.push(`运行态读取：${esc(a.runtime_error)}`);      // 中性色，见 §5
  return `
    <tr data-rexp="${esc(a.name)}"><td colspan="5">
      <div class="req-detail">
        ${bits.map((b) => `<span>${b}</span>`).join("")}
        <span class="sep">${detailOpsHTML(p, a, cap)}</span>
      </div></td></tr>`;
}

/** BD3a：`resource` 三态必须分开（null=未知，[]=确实没有，非空=已物化 N 个 · 启用 M）。 */
function resourceLine(a) {
  const rs = a.resource;
  if (!Array.isArray(rs)) return "网关资源：未知（配置读不动，不推断成 0）";
  if (!rs.length) return "网关资源：无（该账号没有已物化的资源，或已从配置移除）";
  const on = rs.filter((r) => r && r.enabled).length;
  const ids = rs.map((r) => `${r.id}${r.enabled ? "" : "（停用）"}`).join("、");
  return `已物化 ${rs.length} 个资源 · 启用 ${on}：${ids}`;
}

/** 网关额度池（`remaining-reserved`）与厂商余额快照量纲不同 → 只进展开行（§3）。 */
function poolLine(a) {
  const q = a.quota || {};
  if (q.state === "unknown" || q.state == null) return "网关额度池：未知（尚无缓存或未刷新，不当零）";
  const n = (q.resources || []).length;
  return `网关额度池（与厂商余额快照不同量纲）：${q.state === "exhausted" ? "已耗尽" : "有余量"} · 剩余 ${q.remaining == null ? "未给出" : q.remaining} · 预留 ${q.reserved == null ? 0 : q.reserved} · 关联 ${n} 个资源`;
}

/** 展开行的动作：能力位 false 不渲染（§3 推翻旧「死钮」）；目录出口未接线不渲染。 */
function detailOpsHTML(p, a, cap) {
  const out = [];
  if (cap.refresh) {
    out.push(iconOp("refresh", `续期 ${a.name}`, "续期：刷新凭据并落盘（与启用位正交，停用账号也可续期）", REFRESH));
  }
  if (p.models_wired) {
    out.push(iconOp("models", `模型目录 ${a.name}`, "模型目录：列出该账号凭据可读到的厂商模型（取不到时如实给出原因，不编造）", CATALOG));
  }
  if (cap.onboarding && ONBOARDING_ENDPOINT_READY) {
    out.push(iconOp("onboarding", `新手任务 ${a.name}`, "新手任务：一次性登录奖励", AWARD));
  }
  return out.length ? out.join("") : `<span style="color:var(--text-faint)">该产品无可追加的行内动作</span>`;
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
  const exp = tr.querySelector("[data-exp]");
  if (exp) exp.onclick = () => toggleExpand(p.id, a.name);
  for (const b of tr.querySelectorAll("[data-op]")) b.onclick = () => runOp(p, a, b.dataset.op, b);
  const dtr = panelEl.querySelector(`#ac-table tbody tr[data-rexp="${sel}"]`);
  if (dtr) for (const b of dtr.querySelectorAll("[data-op]")) b.onclick = () => runOp(p, a, b.dataset.op, b);
}

/** 三级重绘之第三级：单行原地替换（含其展开行）；结构变化时退化为面板级重绘。 */
function patchRow(pid, name) {
  const p = productOf(pid) || selectedProduct();
  const a = p && p.accounts.find((x) => x.name === name);
  const sel = cssAttr(name);
  if (!panelEl || !p || !a || !sel) { paintPanel(); return; }
  const tr = panelEl.querySelector(`#ac-table tbody tr[data-acc="${sel}"]`);
  if (!tr) { paintPanel(); return; }
  const holder = document.createElement("tbody");
  holder.innerHTML = rowHTML(p, a) + detailHTML(p, a);
  const made = Array.from(holder.children);
  const detail = panelEl.querySelector(`#ac-table tbody tr[data-rexp="${sel}"]`);
  if (detail) detail.remove();
  const head = made[0];
  if (!head || !tr.replaceWith) { paintPanel(); return; }
  tr.replaceWith(head);
  let last = head;
  for (const el of made.slice(1)) { if (last.after) last.after(el); last = el; }
  bindRow(p, a);
}

function toggleExpand(pid, name) {
  const key = rowKey(pid, name);
  if (expanded.has(key)) expanded.delete(key); else expanded.add(key);
  patchRow(pid, name);
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

/* ---------- 行内操作 ---------- */
const accountPath = (pid, name) => `/admin/api/accounts/${pid}/${encodeURIComponent(name)}`;

async function runOp(p, a, op, btn) {
  if (op === "delete") return delAccount(p, a);
  if (op === "models") return openModels(p, a);          // 只读弹窗：不重取视图、不锁按钮
  if (!btn) return;
  btn.disabled = true;                                    // 长操作防连点
  try {
    if (op === "probe") await doProbe(p, a);
    else if (op === "refresh") await doRefresh(p, a);
    else if (op === "claim") await doClaim(p, a);
    else if (op === "onboarding") await doClaim(p, a, "claim_onboarding");
  } finally {
    btn.disabled = false;
    await refreshAfter(p.id, a.name);                     // 结果与视图一起刷新
  }
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
    + `（统计与历史不丢，彻底删除请到「接入模型资源」页），账号凭据目录将被移除。`)) return;
  try {
    await POST(`${accountPath(p.id, a.name)}/delete?confirm=1`);      // 破坏性：必须显式确认
    toast(`账号 ${a.name} 已删除`, "ok");
    expanded.delete(rowKey(p.id, a.name));
  } catch (e) {
    toast("删除失败：" + e.message, "err");
  }
  await refreshAfter(p.id, null);                                     // 行已不在册 → 面板级重取
}

/* ---------- 模型目录（B-1：账号 → 产品 `list_models` → 目录弹窗） ----------
 * 契约（`api/admin_accounts.py::account_models`）：`{state, source, models[]}` ——
 * 只有 `state==="ok"` 才是目录；`state==="unknown"`（钩子取不动）只展示原因，**不编造条目**
 * （`21 §5.1-1`；与运行态 `status:"unknown"` 同口径）。 */

async function openModels(p, a) {
  const body = document.createElement("div");
  body.innerHTML = `<div class="loading">正在读取模型目录…</div>`;
  const foot = document.createElement("div");
  foot.innerHTML = `<button class="btn">关闭</button>`;
  /* 必须在 modal() **之前**取引用：modal() 会把 footer 子节点平铺进 .modal-foot（§7.11 契约） */
  const closeBtn = foot.querySelector(".btn");
  const dlg = modal({ title: `模型目录 · ${p.title} / ${a.name}`, body, footer: foot });
  closeBtn.onclick = dlg.close;
  try {
    const r = await GET(`/admin/api/accounts/${p.id}/${encodeURIComponent(a.name)}/models`);
    body.innerHTML = modelsHTML(r);
  } catch (e) {
    body.innerHTML = `
      <div class="alert alert-err"><div class="alert-title">模型目录读取失败</div>
        <div>${esc(e.message)}</div></div>`;
  }
}

/** 目录体：来源恒展示；`ok` 才出列表，`unknown` 只给原因（不编造）。 */
function modelsHTML(r) {
  const src = sourceText(r.source);
  if (r.state !== "ok") {
    return `
      <div class="alert alert-warn"><div class="alert-title">目录取不动</div>
        <div>${esc(r.reason || "上游未给出原因")}</div></div>
      <p class="form-hint" style="margin-top:12px">来源：${esc(src)} · 不展示任何未取回的条目（不编造）。</p>`;
  }
  const list = r.models || [];
  if (!list.length) {
    return `
      <p class="form-hint">目录为空：该账号凭据下未读到任何模型条目。</p>
      <p class="form-hint">来源：${esc(src)}</p>`;
  }
  return `
    <div class="sec-head"><span class="t">模型（${list.length}）</span>
      <span class="d">来源：${esc(src)}</span></div>
    <div style="display:flex;flex-direction:column;gap:8px">${list.map(modelRowHTML).join("")}</div>
    <p class="form-hint" style="margin-top:12px">只标注上游明确给出的信息（未取到的不展示，不编造）；
      厂商模型 ID 可直接用于「接入模型资源」页的资源映射。</p>`;
}

/** 单条模型行（id 等宽加粗 + 12px 辅助行；只列已知事实）。 */
function modelRowHTML(m) {
  const facts = [
    (m.name && m.name !== m.id) ? m.name : "",
    m.context_window != null ? `上下文 ${fmtTok(m.context_window)}` : "",
    m.max_output != null ? `输出 ${fmtTok(m.max_output)}` : "",
    m.reasoning === true
      ? `深度推理${(m.effort_levels || []).length ? `（${m.effort_levels.join("/")}）` : ""}` : "",
    m.image_input === true ? "图片输入" : "",
    m.tool_call === true ? "工具调用" : "",
  ].filter(Boolean);
  return `
    <div data-mdl="${esc(m.id)}" style="display:flex;align-items:center;min-height:44px;padding:8px 12px;gap:12px;border:1px solid var(--border);border-radius:var(--radius-md)">
      <span style="flex:1;min-width:0">
        <b class="mono">${esc(m.id)}</b>
        ${facts.length ? `<span style="display:block;font-size:12px;color:var(--text-faint);margin-top:4px">${esc(facts.join(" · "))}</span>` : ""}
      </span>
    </div>`;
}

/* ---------- 模型映射（产品内部模型 → 网关模型）与批量签到 / 领取 ----------
 * 契约（后端随本轮落地，前端按冻结 payload 实现，不预判字段）：
 *   GET  /admin/api/accounts/{product}/catalog → {product,title,checkin,source,models[],accounts[]}
 *   POST /admin/api/accounts/mappings          {product, items:[{model,target}]}
 *   POST /admin/api/accounts/claim-all         {product} 或 {product:null}（null = 全部支持签到的产品）
 * 两处共用纪律：动作期间触发钮进「执行中…」禁用态（顺序执行可达数十秒，**不加人为超时**）；
 * 结果一律从响应 payload 出（失败只报原文，不编造成功）；写完重取服务端视图自同步（D3）。
 */

/** 模型映射弹窗（root = 页面 root，落库后按 models.js `persist(root)` 同款口径重绘本页）。 */
async function openModelMap(root, p) {
  if (!p) return;
  const body = document.createElement("div");
  body.innerHTML = `<div class="loading">正在读取模型目录…</div>`;
  const foot = document.createElement("div");
  foot.innerHTML = `<button class="btn">取消</button>
    <button class="btn btn-primary" disabled>初始化映射</button>`;
  /* 同 `openModels`：必须在 modal() **之前**取引用（components.js 会把 footer 子节点平铺走，§7.11） */
  const [cancelBtn, okBtn] = foot.querySelectorAll("button");
  const dlg = modal({ title: `模型映射 · ${p.title}`, body, footer: foot });
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
    body.innerHTML = mapBodyHTML(catalog, options);
    /* 没账号 = 没有资源可挂：目录照常可看，落库按钮禁用（写了也挂不上，只会在配置里留空映射）。 */
    okBtn.disabled = !(catalog.accounts || []).length;
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
      const m = models[Number(select.dataset.idx)];
      if (m && target) items.push({ model: m.id, target });     // 空值 = 跳过（用户显式没选）
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

/** 弹窗体：来源行（服务端口径原样给出，含 fallback 的如实声明）+ 表头 + 逐模型一行。
 *  状态列只报事实：`mapped_to` 非空 = 已映射（目标名进 title 悬停可见），空 = 未映射（不猜）。 */
function mapBodyHTML(cat, options) {
  const models = cat.models || [];
  const src = cat.source || {};
  const grid = "display:grid;grid-template-columns:minmax(0,1.4fr) 56px 180px 76px;gap:12px;align-items:center";
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
    return `
      <div class="list-row" style="${grid}">
        <span style="min-width:0">
          <b>${esc(m.name || m.id)}</b>
          <span class="mono" style="display:block;font-size:12px;color:var(--text-faint);margin-top:4px">${esc(m.id)}</span>
        </span>
        <span>${ruleHTML(m)}</span>
        <select class="in" data-idx="${i}" style="width:100%" aria-label="映射目标 ${esc(m.name || m.id)}"
          >${optionHTML(options, pickTarget(m, options))}</select>
        <span>${mapped.length
          ? `<span class="badge b-ok" title="${esc("已映射到：" + mapped.join("、"))}">已映射</span>`
          : `<span class="badge b-gray">未映射</span>`}</span>
      </div>`;
  }).join("");
  return `${head}
    <div class="list-card">
      <div class="list-row" style="${grid}">${th("模型")}${th("规则")}${th("目标网关模型")}${th("状态")}</div>
      ${rows}
    </div>`;
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
  if (r) showClaimAllResult(r);
  await refreshAfter(selected, null);      // 运营会改额度快照 → 取服务端最新（不动在飞向导）
}

/** 批量结果弹窗：摘要行 + 每参与账号一行（分类 + 明细）；**只有失败着红**（行级 claim 同口径）。 */
function showClaimAllResult(r) {
  const p = r.product ? productOf(r.product) : null;
  const body = document.createElement("div");
  body.innerHTML = claimReportHTML(r);
  const foot = document.createElement("div");
  foot.innerHTML = `<button class="btn">关闭</button>`;
  const closeBtn = foot.querySelector(".btn");          // modal() 之前取（§7.11 契约）
  const dlg = modal({ title: `批量签到结果 · ${p ? p.title : "全部支持签到的产品"}`, body, footer: foot });
  closeBtn.onclick = dlg.close;
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
 *   · 订单轮询 2500ms 一条 timer：终态（delivered/failed/expired）即停、无在飞单即清、关窗即清，
 *     生命周期唯一所有者 = `stopZShop()`（照 `stopWizard()` 口径）；轮询不做人为超时。
 *   · 订单台账只存 `{orderId, token}`（localStorage `mgw.zshop.orders`，上限 5 条；失败/超时出表、
 *     已到账保留以便回来再导）—— 凭据内容一个字节都不进浏览器存储；
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
    try { await zImportFlow({ source: "payload", payload }, (r) => onOk(r), setErr); }
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
    await zImportFlow({ source: "payload", payload }, (r) => onOk(r), setErr);
  };
  for (const b of body.querySelectorAll('[data-z="row"]')) {
    b.onclick = async () => {
      const rowBtn = b;
      b.disabled = true;
      const outcome = await zImportFlow({ source: b.dataset.src, account: b.dataset.acc },
        (r) => onOk(r, rowBtn), setErr);
      if (outcome !== "ok") b.disabled = false;   // 成功时钮已被徽章替换（不再恢复）
    };
  }
}

/** 导入请求一次（不抛）：成功 / 409 冲突 / 其它错误三态原样带回，由调用方决定怎么呈现。 */
async function zImportOnce(body) {
  try {
    const r = await POST("/admin/api/zcode/import", body);
    return { ok: true, account: (r && r.account) || "" };
  } catch (e) {
    const d = e.data || {};
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
 *  成功 → onOk；409 → 冲突弹窗（用户二选一后二次提交，成功仍走 onOk）；其余 → onErr。
 *  settle 口径：Promise<"ok"|"cancel"|"err"> —— 冲突在弹窗**之后**才结束，调用方据此恢复自身钮的禁用态。 */
function zImportFlow(body, onOk, onErr) {
  return new Promise((resolve) => {
    zImportOnce(body).then((r) => {
      if (r.ok) { resolve(onOk(r)); return; }        // onOk 可 async：settle 等它完成
      if (r.conflict) {
        zConflictDialog(r.conflict,
          async (patch) => {
            const r2 = await zImportOnce({ ...body, ...patch });
            if (r2.ok) { await onOk(r2); return "ok"; }
            if (r2.conflict) return `仍有冲突：${r2.conflict.hint || r2.conflict.error || "需要再次确认"}`;
            return r2.err;
          },
          (outcome) => resolve(outcome));
        return;
      }
      onErr && onErr(r.err);
      resolve("err");
    });
  });
}

/** 设备身份冲突（409）决策窗：**绝不自动选**（复用 = 与既有账号共用设备身份；
 *  重新生成 = 换新设备身份）。「取消」最左（与 `confirmDialog` 同序），两个决策钮放右、主色给
 *  「复用其身份」（任务契约列为首选路径，但两个动作都等用户按了才走）；
 *  attempt 执行期三钮禁用，失败把原因原文留在窗内（不吞、不静默重试）。 */
function zConflictDialog(res, attempt, settled = () => {}) {
  const account = String(res.account || "");
  const withName = String(res.conflict_with || "");
  const body = document.createElement("div");
  body.innerHTML = `
    <p style="margin:0 0 12px;font-size:13px;font-weight:600;color:var(--text-soft)">
      账号「${esc(account)}」的设备身份与既有账号「${esc(withName)}」冲突。</p>
    <div class="alert alert-warn" style="margin-bottom:12px">
      <div>复用其身份 = 与既有账号「${esc(withName)}」共用同一设备身份；重新生成 = 为新账号换一个新设备身份。两者都会立即导入，请按上游对设备数量的要求选择。</div>
      ${res.hint ? `<div style="margin-top:4px">${esc(res.hint)}</div>` : ""}
    </div>
    <div id="ac-zconf-err"></div>`;
  const foot = document.createElement("div");
  foot.innerHTML = `<button class="btn" data-zc="cancel">取消</button>
    <button class="btn" data-zc="regen">重新生成</button>
    <button class="btn btn-primary" data-zc="reuse">复用其身份</button>`;
  const [cancelBtn, regenBtn, reuseBtn] = foot.querySelectorAll("button");   // modal() 之前取（§7.11）
  let done = false;
  const finish = (v) => { if (!done) { done = true; settled(v); } };
  const dlg = modal({ title: `设备身份与账号 ${account} 冲突`, body, footer: foot,
    onClose: () => finish("cancel") });
  cancelBtn.onclick = dlg.close;
  const errEl = body.querySelector("#ac-zconf-err");
  const pick = async (patch) => {
    cancelBtn.disabled = regenBtn.disabled = reuseBtn.disabled = true;
    let out = "";
    try {
      out = await attempt(patch);
    } catch (e) {
      out = e.message;
    }
    if (out === "ok") {
      finish("ok");                              // 先答复再关窗（close 的 onClose 会再报 "cancel"，被 done 挡掉）
      dlg.close();
      return;
    }
    errEl.innerHTML = `<div class="alert alert-err"><div class="alert-title">仍未导入</div><div>${esc(out || "后端未给出原因")}</div></div>`;
    cancelBtn.disabled = regenBtn.disabled = reuseBtn.disabled = false;
  };
  reuseBtn.onclick = () => pick({ reuse: withName });
  regenBtn.onclick = () => pick({ regenerate: true });
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
function zRememberOrder(orderId, token) {
  writeZOrders([{ orderId, token }].concat(readZOrders().filter((o) => o.orderId !== orderId)));
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

/** 购买账号弹窗：订单区（台账恢复，pending 继续轮询）+ 商品区（开窗即读）。 */
function openZShop(root) {                          // root 仅为调用点签名一致；落点统一走 repaintPanel(rootEl)
  stopZShop();                                     // 单实例：开新窗先收干净旧窗（timer 一并清）
  const st = { body: null, m: null, timer: null,
    orders: readZOrders().map((o) => zBlankOrder(o.orderId, o.token)) };
  zshop = st;
  const body = document.createElement("div");
  st.body = body;
  body.innerHTML = `
    <div id="ac-zshop-err"></div>
    <div class="sec-head"><span class="t">我的订单</span><span class="d">台账存本机浏览器（只存订单号与查询令牌）</span></div>
    <div id="ac-zshop-orders"></div>
    <div class="sec-head"><span class="t">商品</span><span class="d">YouYu Shop · 一元买一个可用账号</span></div>
    <div id="ac-zshop-items"><div class="loading">正在读取商品列表…</div></div>`;
  const foot = document.createElement("div");
  foot.innerHTML = `<button class="btn" style="margin-right:auto" data-zs="refresh">${REFRESH}刷新</button>
    <button class="btn" data-zs="close">关闭</button>`;
  const [refreshBtn, closeBtn] = foot.querySelectorAll("button");            // modal() 之前取（§7.11）
  st.m = modal({ title: "购买账号 · ZCode（一元账号 · YouYu Shop）", body, footer: foot,
    onClose: () => { if (zshop === st) stopZShop(); } });
  closeBtn.onclick = st.m.close;
  refreshBtn.onclick = () => paintZItems(st);
  paintZOrders(st);
  paintZItems(st);
  zShopTick(st);                                   // 恢复未完成订单：立即查一轮，再按 2.5s 节拍走
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

/** 订单区整绘（单量 ≤5，整绘最简单；待付 / 到账 / 超时 / 失败四态各有落点）。 */
function paintZOrders(st) {
  if (zshop !== st) return;
  const holder = st.body && st.body.querySelector("#ac-zshop-orders");
  if (!holder) return;
  if (!st.orders.length) {
    holder.innerHTML = `<div class="list-empty" style="margin-bottom:12px">还没有订单：下单后在这里看支付状态。</div>`;
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
  const money = od.amount == null ? "" : `实付 ¥${od.amount}`;
  const state = od.term
    ? (od.delivered ? `<span style="color:var(--ok)">已到账</span>`
      : od.expired ? `<span style="color:var(--warn)">已超时</span>`
        : `<span style="color:var(--err)">下单失败</span>`)
    : `<span style="color:var(--text-muted)">等待付款…</span>`;
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
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <b class="mono">${esc(od.orderId)}</b>
          ${money ? `<span class="form-hint" style="margin:0">${esc(money)}${od.payTypeName ? " · " + esc(od.payTypeName) : ""}</span>` : ""}
          <span style="margin-left:auto;font-size:12px;font-weight:700">${state}</span>
        </div>
        ${od.err ? `<div class="alert alert-err" style="margin-top:12px"><div>${esc(od.err)}</div></div>` : ""}
        ${bottom}
      </div>
    </div>`;
}

/** 已到账：逐账号一行（名称 + 已核验套餐 + 复制 JSON + 导入到网关）。 */
function zDeliveredHTML(od) {
  const accs = od.accs || [];
  if (!accs.length) return `<p class="form-hint" style="margin:8px 0 0">订单已到账，但响应里没有账号内容；可到 YouYu Shop 的订单里查看。</p>`;
  return `
    <p class="form-hint" style="margin:8px 0 0">已到账${od.deliveredAt ? `（${esc(shortTime(od.deliveredAt))}）` : ""}，共 ${accs.length} 个账号：</p>
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
    (msg) => { od.err = msg; paintZOrders(st); });
  if (outcome !== "ok") btn.disabled = false;      // 成功时钮已被徽章替换（不再恢复）
}

/** 商品区（开窗首绘与「刷新」共用；失败给出响应里的原因）。 */
async function paintZItems(st) {
  const holder = st.body && st.body.querySelector("#ac-zshop-items");
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
    b.onclick = () => zBuy(st, it, b);
  }
}

function zItemsHTML(items) {
  return `<div class="list-card" style="margin-bottom:12px">${items.map((it, i) => {
    const soldout = typeof it.stock === "number" && it.stock <= 0;
    const off = it.listed === false || soldout;
    const meta = [
      `¥${it.price}`,
      typeof it.stock === "number" ? `库存 ${it.stock}` : "",
      it.validity || "",
      it.note || "",
    ].filter(Boolean);
    return `
    <div class="list-row">
      <span style="min-width:0;flex:1">
        <b>${esc(it.title || it.id || "未命名商品")}</b>
        <span style="display:block;font-size:12px;color:var(--text-faint);margin-top:4px">${esc(meta.join(" · "))}</span>
      </span>
      <button class="btn btn-sm btn-primary" data-zi="buy" data-idx="${i}"
        ${off ? `disabled title="${soldout ? "已售罄" : "已下架"}"` : ""}>${SHOP}购买</button>
    </div>`;
  }).join("")}</div>`;
}

/** 下单：payload 固定 `{itemId, qty:1}`；成功即入台账 + 立绘订单块 + 立即查一轮状态。 */
async function zBuy(st, it, btn) {
  if (!it || !btn || btn.disabled) return;
  const label = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "下单中…";
  try {
    const r = await POST("/admin/api/zcode/shop/buy", { itemId: it.id, qty: 1 });
    const od = zBlankOrder(r.orderId, r.orderToken);   // 查询令牌 = 下单响应的 orderToken
    od.payPath = String(r.payPath || "");
    od.payTypeName = String(r.payTypeName || "");
    if (r.reallyPrice != null || r.amount != null) od.amount = r.reallyPrice != null ? r.reallyPrice : r.amount;
    st.orders = st.orders.filter((o) => o.orderId !== od.orderId);   // 同号去重：台账恢复的单撞号时不出现两张卡
    st.orders.unshift(od);
    zRememberOrder(od.orderId, od.token);
    paintZOrders(st);
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
