#!/usr/bin/env node
/**
 * M7-UI 判据门 · 「账号接入」页 v2 结构（design-accounts-list-v2.md §8 判据 1）
 *
 * 干什么：把 `model_gateway/web/static/js/pages/accounts.js` 的**真源码**编进 vm，
 * 喂三份 fixture（0 账号 / 单产品 7 账号 / 10 产品 31 账号）执行页面的渲染入口
 * `renderAccounts(root)`，对产出的假 DOM 断言设计书 §8 的判据（V1–V17，含 2026-10-02
 * 额度五档改版的 V4'/V7'/V10'/V13/V14/V14b/V15/V17）+ 三条
 * **反转的 M6-IX 判据**（L-A6 / L-A8 / L-A10 —— 原断言见
 * `docs/changes/e2e-records/m6-accounts-assertions.json`，本版把它们逐条反转而不是删除）。
 *
 * 为什么不用 headless Chrome：与 `verify_v2_frontend.mjs:6-8` 同一条理由——本机沙箱下
 * Chrome 加载真实页面会挂住；改用 Node 直接执行前端源码里的真实函数，验证的是**同一份
 * 源码**而不是复制品。
 *
 * 用法：
 *   node scripts/verify_accounts_ui.mjs                 # 实测（人读）
 *   node scripts/verify_accounts_ui.mjs --json          # 机器读（最后一行 JSON，退出码 0）
 *   node scripts/verify_accounts_ui.mjs --mutation      # 变异自证（MUTATIONS 每条一行表，见下）
 *   node scripts/verify_accounts_ui.mjs --help          # 用法
 *   可覆盖：MGW_AC_PAGE=<path> / `--page <path>`（被实测的页面副本，变异模式用）
 *           MGW_AC_FIXDIR=<dir>（fixture 目录，默认 bianyiandhuanjing/scripts/fixtures）
 *   无参数依赖：本门不读 config.yaml、不发网络请求、不启网关进程。
 *
 * 「判据可实现吗」的一条总检（本轮实测留档，2026-09-30）：把本文件 MUTATIONS 里各条的
 *   fix 编辑一次性并到 /tmp 副本上，再 `MGW_AC_PAGE=/tmp/xxx.js node 本门`
 *   → 八条 V 判据全绿（R0 亦绿），只剩 L-A6/L-A8/L-A10 三条红——因为最小 fix 没去动
 *   族标题文字、rail title 与头卡副行，正是实施轮剩下的三件事。
 *   这条同时证明 V 段没有「永远红」的死判据（每条都实测过绿态）。
 *   ⚠️ 上面那句是 **2026-09-30 那一批的历史记录**（当时的 fix 组含 TABLE/QUOTA/WORDS 等 6 组）。
 *   2026-10-02 五档改版后 fix 组已变（`QUOTA_FIX` 退役、V4/V7/V10/V13/V14/V14b/V15/V17 改走
 *   `expectGreen`），本轮的可绿性证据 = 页面已实现 ⇒ **基线 22 项全绿** + `--mutation` 19/19 可红
 *   （原始输出见 `docs/changes/e2e-records/gate-static-20261002.md`），不要再拿上面那句当现状读。
 *
 * 退出码：0 = 全绿；1 = 有失败；2 = 结构级错误（页面渲染不出来 / fixture 不合契约 /
 *   门自身抽取失败）——「渲染不出来」在本门是**判据**（R0），不是被吞掉的异常。
 *
 * 🔴 变异自证的口径（照 `scripts/ui_verify_v2_visible.py:15-16` + `verify_v2_frontend.mjs:16-26`）：
 *   「永远不会红的断言等于没有断言」。本门的处境比既有门更苛刻：**今日基线本来就是红的**
 *   （族层还在页面上，判据先行、实施在后的 §8-1 顺序），所以「变异后变红」对那几条是
 *   永真式（假通过）。因此每条变异前先做一次**可绿性核验**：
 *     ① 该判据在当前页面上已绿 → 直接施加回归变异 → 必须变红；
 *     ② 该判据当前为红 → 先施加最小 `fix` 编辑（/tmp 副本，**不碰工作区**）让页面达到
 *        设计书形态 → 判据**必须转绿**（转不绿 = 死判据或 fix 锚点过期，该记 BAD）；
 *        再在 fix 之上施加回归变异 → 必须变红。
 *   变异锚点要求**恰好命中 1 次**（命中 0 次或多次一律 BAD：锚点过期是最隐蔽的假通过）。
 *   变异跑在 `/tmp` 的页面副本上，由**子进程**执行本门的副本（超时 SIGKILL），
 *   只认子进程真回来的 `ok:false`——崩了/挂住不算「已杀死」。
 *
 * 🔴 覆盖边界（不得让「实测」二字夸大范围，铁律 2）：
 *   · 断言的是**渲染产物**（假 DOM 树 + 页面源码字符串字面量），不是真实浏览器的
 *     计算样式/布局；尺寸、折行、双主题截图另由 CDP 脚本负责。
 *   · 面板段用「轮换 fixture.products 让每个产品都成为默认选中项」来驱动，
 *     刻意**不依赖**点击标记（`data-pid` 之类）的实现细节；深链/localStorage 记忆归后续。
 *   · 向导段驱动到「参数段 → 开始登录 → 展示物（含短信 tab 切换）」；行内操作
 *     （探活/续期/签到/删除）与模型目录弹窗**不在本门面内**（它们要 POST 桩与真实
 *     落库语义，归 pytest / 真机断言）。
 *   · 🔴 2026-10-02（方案 §8.2 V10'-④ / QA N-7）：V10' 的「总额一致性」需要**页面自己的**
 *     缩写函数 `fmtQuotaNumber` 来算期望串 —— 门内重写第二份 = 判据自证（两份实现一起错就永远绿）。
 *     实现姿势 = `DRIVER` 多收一份 probe（每号 `[Σactive remaining, unit]`，由 `buildRuns` 从
 *     fixture 算好送进 realm），realm 调页面函数算出缩写串回传 `qfmt`；页面若删掉那个函数，
 *     V10' 直接报「realm 取不到 fmtQuotaNumber」而不是悄悄换算法。此项属**门改动**须入台账。
 */
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const argv = process.argv.slice(2);
const JSON_ONLY = argv.includes("--json");
const MUTATE = argv.includes("--mutation");

/** 被实测的页面（变异模式把副本写到 /tmp，用 `--page` 指过来） */
const PAGE_FILE = (() => {
  const i = argv.indexOf("--page");
  if (i >= 0 && argv[i + 1]) return resolve(argv[i + 1]);
  if (process.env.MGW_AC_PAGE) return resolve(process.env.MGW_AC_PAGE);
  return join(ROOT, "coding/model_gateway/web/static/js/pages/accounts.js");
})();
const DEPS = {
  api: join(ROOT, "coding/model_gateway/web/static/js/api.js"),
  components: join(ROOT, "coding/model_gateway/web/static/js/components.js"),
};
const FIXDIR = process.env.MGW_AC_FIXDIR || join(ROOT, "bianyiandhuanjing/scripts/fixtures");
const FIXTURES = ["accounts_zero.json", "accounts_one_product.json", "accounts_mixed.json"];

/**
 * 额度列词表与映射表（方案 §4-7 · 2026-10-02 五档定版，推翻旧「四档」口径）。
 * · QUOTA_WORDS = 五档唯一词表（V7 的合法性检查 + 「不得越界」硬约束，QA N-9）；
 * · WANT_BY_STATE = **状态决定文案**的映射（V7' 的映射断言用它——只查词表合法性 = 需求没做也绿，
 *   评审实测：页面完全没实现「无套餐」映射、fixture 塞一行 no_plan 数据，门照样全绿）；
 *   「无套餐」= `state==="unknown" && reason==="no_plan"` 的**前端映射**（裁决③：不动 `QuotaState` 枚举）；
 * · QUOTA_NOTE_MAP = 附属标注五档（方案 §8.2 X-R5-9：这五档**不是第六档**，是注记，
 *   V7 的 exactly-one 靠这个区分成立；`no_identity` 与 `no_credentials` 同文案、两行都要在）。
 * QUOTA_NONCE 与「detail 必含上游原话」的对表：中文原话含「可用/剩余」只进 title（属性），
 * 而本门 `visibleText` 不读属性 ⇒ 可见面不会撞词表（对表结论见交付报告）。
 */
const QUOTA_WORDS = ["有余量", "已耗尽", "无套餐", "未知", "尚未刷新"];
const WANT_BY_STATE = {
  available: "有余量", exhausted: "已耗尽", unknown: "未知",
};
/** `reason === "no_plan"` 优先于状态映射（裁决③ 的唯一前端映射）。 */
const NO_PLAN_WORD = "无套餐";
/** 附属标注映射（V15）：`reason` → 必须出现的注记串。 */
const QUOTA_NOTE_MAP = {
  circuit: "（冷却中）",
  "circuit-untrusted": "（熔断状态不可读）",
  unreachable: "（读取失败）",
  no_credentials: "（未发起）",
  no_identity: "（未发起）",
};
const QUOTA_NONCE = ["剩余", "可用", "undefined", "NaN"];
const BANNED = ["正常", "在服务", "健康", "在线", "已取消"];
/** 展开详情行已废除（2026-10-01）：这些实现词汇在页面上**零出现**（L-A10）。 */
const DETAIL_ONLY = ["设备身份", "模型目录来源", "协议", "OpenAI 兼容", "Anthropic 兼容", "产品专属出站塑形"];

/* ==================== 页面源码 → realm 可执行体 ==================== */

/** 剥 import / export（同 `verify_v2_frontend.mjs:1622` 的 toModuleBody 口径）。 */
const toModuleBody = (src) => src
  .replace(/^\s*import\s+[\s\S]*?from\s+"[^"]*";\s*$/gm, "")
  .replace(/^(\s*)export\s+(async\s+function|function|const|let|var|class)\s/gm, "$1$2 ");

/* ---------------------------------------------------------------------------
 * 假 DOM（🔴 住在 realm **里面**：节点是又读又写的可变对象，宿主对象进 realm 要过
 * Proxy，节点身份/数组属性/constructor 桥都会出问题——`verify_v2_frontend.mjs:226-232`
 * 已把这条坑写死。本段源码里**不得出现反引号**（它被编进模板字符串），字符串一律用引号拼。）
 * ------------------------------------------------------------------------- */
const FAKE_DOM = `
const __els = Object.create(null);
const __timers = { intervals: 0, timeouts: 0, cleared: 0 };
const __opened = [];
const __store = Object.create(null);
let fetch = async (p) => { throw new Error("判据未造 fetch 桩：" + p); };
const localStorage = {
  getItem: (k) => (k in __store ? __store[k] : null),
  setItem: (k, v) => { __store[k] = String(v); },
  removeItem: (k) => { delete __store[k]; },
  clear: () => { for (const k in __store) delete __store[k]; },
};
const location = { hash: "#/accounts", pathname: "/", search: "" };
const window = { open: (u) => { __opened.push(String(u)); }, localStorage: localStorage, location: location };
const navigator = { clipboard: { writeText: async () => {} } };
const setInterval = (fn) => { __timers.intervals += 1; return __timers.intervals; };
const setTimeout = (fn) => { __timers.timeouts += 1; return __timers.timeouts; };
const clearInterval = () => { __timers.cleared += 1; };
const requestAnimationFrame = (fn) => { __timers.timeouts += 1; return __timers.timeouts; };
const __VOID = { br: 1, img: 1, input: 1, meta: 1, link: 1, hr: 1, path: 1, rect: 1,
  circle: 1, ellipse: 1, line: 1, polyline: 1, polygon: 1, use: 1, source: 1, col: 1 };
/* 选择器：支持 a b（后代）与逗号并集；单档 = 标签 / .class / #id / [attr] / [attr=val]
   🔴 每个分支都必须**至少吃掉一个字符**：把标签分支写成可选（(…)?) 时，正则对
   [data-pid] 这类属性选择器会匹配到空串且 lastIndex 不自增 → exec 循环原地打转
   （本门首轮实测挂住 60s 的根因；假 DOM 的选择器是页面找控件的唯一通路，挂住等于门死）。 */
const __parseSimple = (s) => {
  const c = { tag: null, id: null, classes: [], attrs: [] };
  const re = /([a-zA-Z][\\w-]*)|\\.([\\w-]+)|#([\\w-]+)|\\[\\s*([a-zA-Z_:][-a-zA-Z0-9_:.]*)\\s*(?:=\\s*(?:"([^"]*)"|'([^']*)'|([^\\]]*)))?\\s*\\]/g;
  let m;
  while ((m = re.exec(s)) !== null) {
    if (m[1]) c.tag = m[1].toLowerCase();
    else if (m[2]) c.classes.push(m[2]);
    else if (m[3]) c.id = m[3];
    else if (m[4]) c.attrs.push([m[4].toLowerCase(), m[5] !== undefined ? m[5] : (m[6] !== undefined ? m[6] : (m[7] !== undefined ? m[7] : null))]);
    else { re.lastIndex += 1; continue; }
  }
  return c;
};
const __classes = (n) => String(n.attrs.class || "").split(/\\s+/).filter(Boolean);
function __matchOne(n, c) {
  if (c.tag && n.tagName.toLowerCase() !== c.tag) return false;
  if (c.id && n.attrs.id !== c.id) return false;
  const cls = __classes(n);
  for (const k of c.classes) if (cls.indexOf(k) < 0) return false;
  for (const [k, v] of c.attrs) {
    if (!(k in n.attrs)) return false;
    if (v !== null && String(n.attrs[k]) !== v) return false;
  }
  return true;
}
function __match(n, sel) {
  for (const raw of String(sel).split(",")) {
    const parts = raw.trim().split(/\\s+/).filter(Boolean).map(__parseSimple);
    if (!parts.length) continue;
    if (!__matchOne(n, parts[parts.length - 1])) continue;
    let p = parts.length - 2;
    let a = n.parent;
    while (p >= 0 && a) { if (__matchOne(a, parts[p])) p -= 1; a = a.parent; }
    if (p < 0) return true;
  }
  return false;
}
const __unescape = (s) => String(s).replace(/&lt;/g, "<").replace(/&gt;/g, ">")
  .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");
function __ser(n) {
  let at = "";
  for (const k in n.attrs) at += " " + k + '="' + n.attrs[k] + '"';
  let inner = n.ownText;
  for (const c of n.children) inner += __ser(c);
  return "<" + n.tagName.toLowerCase() + at + ">" + inner + "</" + n.tagName.toLowerCase() + ">";
}
function __mk(tag) {
  const el = { tagName: String(tag || "div").toUpperCase(), attrs: {}, children: [],
    parent: null, ownText: "", listeners: {}, hidden: false, style: {} };
  el.classList = {
    contains: (c) => __classes(el).indexOf(c) >= 0,
    add: (c) => { if (!el.classList.contains(c)) el.attrs.class = (el.attrs.class + " " + c).trim(); },
    remove: (c) => { el.attrs.class = __classes(el).filter((x) => x !== c).join(" "); },
    toggle: (c, force) => {
      const want = force === undefined ? !el.classList.contains(c) : !!force;
      if (want) el.classList.add(c); else el.classList.remove(c);
      return want;
    },
  };
  Object.defineProperty(el, "className", {
    get: () => el.attrs.class || "", set: (v) => { el.attrs.class = String(v); },
    enumerable: false, configurable: true });
  Object.defineProperty(el, "id", {
    get: () => el.attrs.id || "", set: (v) => { el.attrs.id = String(v); },
    enumerable: false, configurable: true });
  Object.defineProperty(el, "dataset", {
    get() {
      return new Proxy({}, {
        get: (t, k) => (typeof k === "string" ? el.attrs["data-" + k.replace(/[A-Z]/g, (c2) => "-" + c2.toLowerCase())] : undefined),
        set: (t, k, v) => { el.attrs["data-" + String(k).replace(/[A-Z]/g, (c2) => "-" + c2.toLowerCase())] = String(v); return true; },
        has: (t, k) => el.attrs["data-" + String(k).replace(/[A-Z]/g, (c2) => "-" + c2.toLowerCase())] !== undefined,
        deleteProperty: (t, k) => { delete el.attrs["data-" + String(k).replace(/[A-Z]/g, (c2) => "-" + c2.toLowerCase())]; return true; },
        ownKeys: () => Object.keys(el.attrs).filter((x) => x.indexOf("data-") === 0)
          .map((x) => x.slice(5).replace(/-([a-z])/g, (m2, c2) => c2.toUpperCase())),
        getOwnPropertyDescriptor: () => ({ enumerable: true, configurable: true }),
      });
    },
    enumerable: false, configurable: true });
  Object.defineProperty(el, "firstChild", {
    get: () => (el.children.length ? el.children[0] : null), enumerable: false, configurable: true });
  Object.defineProperty(el, "textContent", {
    get() {
      let t = el.ownText;
      for (const c of el.children) { const s = c.textContent; if (s) t += (t ? " " : "") + s; }
      return t;
    },
    set: (v) => { el.ownText = String(v); el.children = []; },
    enumerable: false, configurable: true });
  Object.defineProperty(el, "innerHTML", {
    get: () => { let s = el.ownText; for (const c of el.children) s += __ser(c); return s; },
    set: (v) => { el.ownText = ""; el.children = []; __parse(String(v), el); },
    enumerable: false, configurable: true });
  for (const p of ["value", "name", "type", "placeholder", "alt"]) {
    Object.defineProperty(el, p, {
      get: () => (el.attrs[p] === undefined ? "" : el.attrs[p]),
      set: (v) => { el.attrs[p] = String(v); }, enumerable: false, configurable: true });
  }
  Object.defineProperty(el, "disabled", {
    get: () => el.attrs.disabled !== undefined,
    set: (v) => { if (v) el.attrs.disabled = ""; else delete el.attrs.disabled; },
    enumerable: false, configurable: true });
  el.setAttribute = (k, v) => { el.attrs[String(k).toLowerCase()] = String(v); };
  el.getAttribute = (k) => (k in el.attrs ? el.attrs[k] : null);
  el.hasAttribute = (k) => String(k).toLowerCase() in el.attrs;
  el.appendChild = (n) => { if (n.parent) n.remove(); n.parent = el; el.children.push(n); return n; };
  el.append = (...ns) => { for (const n of ns) { if (typeof n === "string") el.ownText += n; else el.appendChild(n); } };
  el.prepend = (...ns) => {
    for (let i = ns.length - 1; i >= 0; i -= 1) {
      const n = ns[i];
      if (typeof n === "string") el.ownText = n + el.ownText;
      else { if (n.parent) n.remove(); n.parent = el; el.children.unshift(n); }
    }
  };
  el.remove = () => {
    if (!el.parent) return;
    const i = el.parent.children.indexOf(el);
    if (i >= 0) el.parent.children.splice(i, 1);
    el.parent = null;
  };
  el.addEventListener = (t2, fn) => { el.listeners[t2] = (el.listeners[t2] || []).concat([fn]); };
  el.removeEventListener = (t2) => { delete el.listeners[t2]; };
  el.__all = () => {
    const out = [];
    for (const c of el.children) { out.push(c); for (const d of c.__all()) out.push(d); }
    return out;
  };
  el.querySelectorAll = (s) => el.__all().filter((n) => __match(n, s));
  el.querySelector = (s) => { const f = el.querySelectorAll(s); return f.length ? f[0] : null; };
  return el;
}
function __parse(html, parent) {
  const re = /<(\\/?)([a-zA-Z][\\w-]*)((?:"[^"]*"|'[^']*'|[^>"'])*?)(\\/?)>/g;
  const stack = [parent];
  let m;
  let cur = 0;
  const pushText = (s) => {
    const top = stack[stack.length - 1];
    const t = String(s).trim();
    if (t) top.ownText += (top.ownText ? " " : "") + t;
  };
  while ((m = re.exec(html)) !== null) {
    pushText(html.slice(cur, m.index));
    cur = m.index + m[0].length;
    if (m[1] === "/") { if (stack.length > 1) stack.pop(); continue; }
    const el = __mk(m[2]);
    const at = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\s>]+)))?/g;
    let a;
    while ((a = at.exec(m[3])) !== null) {
      const v = a[2] !== undefined ? a[2] : (a[3] !== undefined ? a[3] : (a[4] !== undefined ? a[4] : ""));
      el.attrs[a[1].toLowerCase()] = __unescape(v);
    }
    stack[stack.length - 1].appendChild(el);
    if (!__VOID[m[2].toLowerCase()] && m[4] !== "/") stack.push(el);
  }
  pushText(html.slice(cur));
}
/* 真壳层只有这两个挂载点（index.html 的 #toast-wrap / #modal-root）；别的 id 查不到 */
__els["toast-wrap"] = __mk("div");
__els["modal-root"] = __mk("div");
const document = {
  getElementById: (id) => (__els[id] === undefined ? null : __els[id]),
  createElement: (t) => __mk(t),
  querySelector: (s) => __els["modal-root"].querySelector(s),
  querySelectorAll: (s) => __els["modal-root"].querySelectorAll(s),
  visibilityState: "visible",
  addEventListener: () => {},
  documentElement: __mk("html"),
  body: __mk("body"),
};
const __resp = (ok, status, body) => ({ ok, status, json: async () => body });
/* 序列化给门外：树只走 JSON 字符串，宿主值一律不进 realm */
function __tree(n) {
  const a = {};
  for (const k in n.attrs) a[k] = n.attrs[k];
  return { t: n.tagName.toLowerCase(), a, x: n.ownText, k: n.children.map(__tree) };
}
`;

/* realm 侧驱动：喂 fixture、跑页面真实入口、把面板与向导两段的树交出去（只写事实，判定在门外）。 */
const DRIVER = `
globalThis.__drive = async (payloadJson) => {
  const P = JSON.parse(payloadJson);
  const errs = [];
  const stages = [];
  fetch = async (p, init) => {
    const path = String(p);
    if (path === "/admin/api/accounts") return __resp(true, 200, P.view);
    if (path === "/admin/api/accounts/capabilities") return __resp(true, 200, P.caps);
    if (path.indexOf("/admin/api/accounts/login/start") >= 0) return __resp(true, 200, P.loginStart);
    if (path.indexOf("/admin/api/accounts/login/poll") >= 0) return __resp(true, 200, { state: "pending", detail: "判据桩：等待用户操作" });
    // BD2 取消路由（admin_accounts.py::login_cancel，幂等）：不造桩的话，
    // 任何走到「取消登录」/✕/遮罩的点击都会被判成"未造桩端点"，
    // 于是页面只能为了过门去调整按钮序 —— 判据的洞不该由被审方绕。
    if (path.indexOf("/admin/api/accounts/login/cancel") >= 0) return __resp(true, 200, { cancelled: true });
    errs.push("判据未造桩的端点 " + path);
    return __resp(false, 501, { error: { message: "判据未造桩：" + path } });
  };
  const root = __mk("div");
  try {
    if (typeof renderAccounts !== "function") {
      errs.push("页面没有可调用的 renderAccounts(root)（改名/删除？判据失去对象）");
    } else {
      await renderAccounts(root);
    }
  } catch (e) {
    errs.push("renderAccounts 抛错 " + (e && e.name) + ": " + String(e && e.message).slice(0, 200));
  }
  stages.push({ kind: "page", tree: __tree(root) });
  /* 🔴 V10'-④：额度总额的**缩写串**必须由**页面自己的** fmtQuotaNumber 算（realm 内直调），
     门内不得重写第二份缩写算法（两份一起错就永远绿）。probe 是门外从 fixture 算好的
     [Σactive remaining, unit] 对，回传一一对齐的字符串数组；页面没有那个函数 → hasFmt=false，
     V10' 报"取不到页面缩写函数"而不是换算法。（本段在本门源码里，注释不得用反引号。） */
  let qfmt = null;
  let hasFmt = false;
  try {
    hasFmt = typeof fmtQuotaNumber === "function";
    if (hasFmt) qfmt = (P.probes || []).map((x) => fmtQuotaNumber(x.sum, x.unit));
  } catch (e) {
    errs.push("realm 调页面 fmtQuotaNumber 抛错 " + (e && e.name) + ": " + String(e && e.message).slice(0, 160));
  }
  /* 向导段：点页面唯一的接入入口 → 开始登录 → 有短信备选形态就切过去（V8 的「已取消」面在这里） */
  const mroot = __els["modal-root"];
  let wizard = "跳过（页面未渲染出接入入口按钮）";
  try {
    const entry = root.querySelectorAll("button").filter((b) => (b.textContent || "").indexOf("接入账号") >= 0)[0];
    if (!entry) wizard = "未渲染：页面上找不到文本含「接入账号」的按钮";
    else {
      if (typeof entry.onclick === "function") entry.onclick();
      wizard = "参数段";
      const start = mroot.querySelectorAll("[data-wz]").filter((b) => b.attrs["data-wz"] === "start")[0];
      if (!start) wizard += "（无 data-wz=start 钮：停在参数段）";
      else {
        const pr = start.onclick();
        if (pr && typeof pr.then === "function") await pr;
        wizard = "进行段";
      }
      // 🔴 M7-C1：主形态的**展示物**要在切到短信 tab **之前**单独存一段（W1 判据读它；
      // raccoon / loomy 都带 login_alt = sms_code，只留最后那段的话，二维码视图会被短信表单覆盖掉）
      stages.push({ kind: "challenge", tree: __tree(mroot) });
      const alt = mroot.querySelectorAll("[data-kind]").filter((b) => b.attrs["data-kind"] === "sms_code")[0];
      if (alt && typeof alt.onclick === "function") { alt.onclick(); wizard += " + 短信形态"; }
    }
  } catch (e) {
    errs.push("向导段驱动抛错 " + (e && e.name) + ": " + String(e && e.message).slice(0, 200));
  }
  stages.push({ kind: "wizard", note: wizard, tree: __tree(mroot) });
  const cancel = mroot.querySelectorAll(".modal-foot button")[0] || mroot.querySelector(".modal-close");
  if (cancel && typeof cancel.onclick === "function") cancel.onclick();
  return JSON.stringify({
    errs, stages, wizard,
    hasFmt, qfmt,
    timers: { intervals: __timers.intervals, timeouts: __timers.timeouts, cleared: __timers.cleared },
    opened: __opened.slice(),
  });
};
`;

/** 渲染一轮：fresh realm（页面源码 + api.js + components.js 的**真源码**）+ 一份 fixture。 */
async function renderRun(pageSrc, payloads) {
  const ctx = vm.createContext({});
  const program = [
    FAKE_DOM,
    toModuleBody(readFileSync(DEPS.api, "utf-8")),
    toModuleBody(readFileSync(DEPS.components, "utf-8")),
    toModuleBody(pageSrc),
    DRIVER,
  ].join("\n");
  new vm.Script(program, { filename: "accounts-ui-realm" }).runInContext(ctx);
  // 🔴 必须 await：realm 里的 __drive 返回 Promise，String() 它只能拿到 "[object Promise]"
  return JSON.parse(String(await ctx.__drive(JSON.stringify(payloads))));
}

/* ==================== 树侧读取（门这一侧的选择器 / 取值） ==================== */

const flatten = (node, parent, out) => {
  node.parent = parent || null;
  out.push(node);
  for (const c of node.k) flatten(c, node, out);
  return out;
};
const cls = (n) => String(n.a.class || "").split(/\s+/).filter(Boolean);
const has = (n, c) => cls(n).indexOf(c) >= 0;
const text = (n) => {
  let t = n.x || "";
  for (const c of n.k) { const s = text(c); if (s) t += (t ? " " : "") + s; }
  return t;
};
/** 可见文本：跳过 style/script 子树（CSS 里的 `content:` 不是本页文案，源码扫描另有其位）。 */
const visibleText = (n) => {
  if (n.t === "style" || n.t === "script") return "";
  let t = n.x || "";
  for (const c of n.k) { const s = visibleText(c); if (s) t += (t ? " " : "") + s; }
  return t;
};
const parseSimple = (s) => {
  const c = { tag: null, id: null, classes: [], attrs: [] };
  // 🔴 同 realm 侧那条注释：分支必须各吃掉 ≥1 字符，否则 `[attr]` 选择器把 exec 打进死循环
  const re = /([a-zA-Z][\w-]*)|\.([\w-]+)|#([\w-]+)|\[\s*([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*(?:=\s*(?:"([^"]*)"|'([^']*)'|([^\]]*)))?\s*\]/g;
  let m;
  while ((m = re.exec(s)) !== null) {
    if (m[1]) c.tag = m[1].toLowerCase();
    else if (m[2]) c.classes.push(m[2]);
    else if (m[3]) c.id = m[3];
    else if (m[4]) c.attrs.push([m[4].toLowerCase(),
      m[5] !== undefined ? m[5] : (m[6] !== undefined ? m[6] : (m[7] !== undefined ? m[7] : null))]);
    else { re.lastIndex += 1; continue; }
  }
  return c;
};
const matchOne = (n, c) => {
  if (c.tag && n.t !== c.tag) return false;
  if (c.id && n.a.id !== c.id) return false;
  const cs = cls(n);
  for (const k of c.classes) if (cs.indexOf(k) < 0) return false;
  for (const [k, v] of c.attrs) {
    if (!(k in n.a)) return false;
    if (v !== null && String(n.a[k]) !== v) return false;
  }
  return true;
};
const sel = (nodes, selector) => {
  const alts = String(selector).split(",").map((raw) => raw.trim().split(/\s+/).filter(Boolean).map(parseSimple))
    .filter((a) => a.length);
  return nodes.filter((n) => alts.some((parts) => {
    if (!matchOne(n, parts[parts.length - 1])) return false;
    let p = parts.length - 2;
    let a = n.parent;
    while (p >= 0 && a) { if (matchOne(a, parts[p])) p -= 1; a = a.parent; }
    return p < 0;
  }));
};
const inside = (n, selector) => sel([n], selector).length > 0
  || (() => { let a = n.parent; while (a) { if (sel([a], selector).length) return true; a = a.parent; } return false; })();
const pathOf = (n) => {
  const seg = [];
  let a = n;
  while (a) { seg.unshift(a.t + (cls(a).length ? "." + cls(a)[0] : "") + (a.a.id ? "#" + a.a.id : "")); a = a.parent; }
  return seg.join(" > ");
};
const cut = (s, n = 90) => String(s).replace(/\s+/g, " ").trim().slice(0, n);

/** 表格读数：表头 + 行 + 「额度」格定位（`.exp` 格让 th/td 同数；不同数就报「列数与表头不符」）。 */
function tableInfo(pageNodes) {
  const table = sel(pageNodes, "table")[0] || null;
  if (!table) return { has: false };
  const flat = flatten(table, null, []);
  const thRow = sel(flat, "thead tr")[0] || sel(flat, "tr")[0];
  const ths = thRow ? thRow.k.filter((c) => c.t === "th") : [];
  const body = sel(flat, "tbody")[0] || thRow;
  const rows = sel(flat, "tbody tr");
  return {
    has: true,
    ths: ths.map((th) => ({ node: th, text: cut(text(th), 40), exp: has(th, "exp") })),
    rows,
    rowsOf: rows.map((tr) => tr.k.filter((c) => c.t === "td")),
    quotaIndex: ths.findIndex((th) => cut(text(th), 40) === "额度"),
  };
}
const quotaCellOf = (tbl, tdRow) => {
  if (tbl.quotaIndex < 0) return { err: "无额度列（表头里没有「额度」）" };
  if (tdRow.length === tbl.ths.length) return { cell: tdRow[tbl.quotaIndex] };
  if (tdRow.length === tbl.ths.length - 1) return { cell: tdRow[tbl.quotaIndex - 1] };
  return { err: `列数与表头不符（th=${tbl.ths.length} td=${tdRow.length}，无法按列定位额度格）` };
};

/* ---------- 额度格读数辅助（2026-10-02 五档改版新增） ----------
 * 🔴 三条纪律都落在这里，不是散在各判据里：
 *  · `cellTextExcept`：**按 DOM 结构**剥离 `.qchk`（「查于 …」那一行），替代旧
 *    「查于」+ 非数字通配 的旧正则 —— 旧正则会把时间戳旁边**别的数字**一起剥掉（V10'-① 去自我豁免）；
 *  · `tipOf`：递归收 tooltip（title 属性）文本 —— 方案 §4-7「量纲保留（**可见或 tooltip**）」
 *    要求同时读两处（旧子句只读 visibleText ⇒ 永远读不到 tooltip，评审 X-R5-2 的误红根因）；
 *  · 缩写串**不在门内算**：由 realm 调页面 `fmtQuotaNumber` 回传（`r.qfmt`），见 V10'-④。 */
const cellTextExcept = (n, skipClass) => {
  if (has(n, skipClass)) return "";
  let t = n.x || "";
  for (const c of n.k) { const s = cellTextExcept(c, skipClass); if (s) t += (t ? " " : "") + s; }
  return t;
};
/** 多类剥离版：`cellTextExcept` 只能剥一类，而「常驻面」要同时剥掉
 *  「查于 …」（`.qchk`）与**折叠着的逐包明细**（`.qpacks-detail`）——
 *  明细块里恒写着「合计剩余 N Token」，任何"量纲在不在"的子串判据拿它当尺子都会
 *  把"常驻面把量纲摘掉"的坏实现一并判绿（本轮实测到：摘掉可见量纲后门仍 23/0 全绿）。 */
const cellTextExceptAll = (n, skipClasses) => {
  if (skipClasses.some((c) => has(n, c))) return "";
  let t = n.x || "";
  for (const c of n.k) { const s = cellTextExceptAll(c, skipClasses); if (s) t += (t ? " " : "") + s; }
  return t;
};
const tipOf = (n) => [String((n.a && n.a.title) || ""), ...n.k.map(tipOf)].join(" | ");
/** `expires_at` 的 ISO 形状谓词（与页面 `ISO_RE` 同口径：`^\d{4}-\d{2}-\d{2}`）。 */
const isISOShape = (v) => /^\d{4}-\d{2}-\d{2}/.test(String(v === null || v === undefined ? "" : v));
/** 把缩写串当**完整 token** 钉（禁 `300 ⊂ 1300` 那种子串侥幸，V10'-②）。 */
const tokenRe = (s) => new RegExp(`(^|[^0-9.])${String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}([^0-9.]|$)`);
/** 「查于 / 数值」里不得出现的裸 10 位秒级 epoch（V17）。 */
const EPOCH_RE = /\b\d{10}\b/;

/* ==================== 数据面：fixture 读取 + 契约校验 + 轮换 ==================== */

/** fixture ↔ `api/admin_accounts.py` 的真实出口形状（键序即 `_account_entry` 的 return，
 *  2026-10-01 起含 `credential_expires_at`；行号引用同步为 `admin_accounts.py:532-547`）。 */
const ACCOUNT_KEYS = ["name", "enabled", "status", "device", "display", "runtime",
  "runtime_ok", "runtime_error", "credential_expires_at", "quota", "resource"];
const PRODUCT_KEYS = ["id", "title", "login", "protocol", "base_url", "device",
  "capabilities", "models_source", "login_alt", "models_wired"];
/** 🔴 落盘 `runtime.quota` 的键集（方案 §4-1/§4-2：`QuotaSnapshot` 9 字段 ∪ 缓存层 `checked_at`）。
 *  这是**视图契约同步**（补覆盖），不是新增判据：`loadFixtures` 只查"fixture 缺键"，
 *  从不与后端 return 比对（QA r3 N-7 定性，r3-eng N-3 同）—— fixture 与真出口脱节时，
 *  额度判据读的是想象中的形状，页面接错键也照绿。 */
const SNAP_KEYS = ["state", "source", "detail", "plan", "items", "remaining",
  "reason", "data_at", "plan_key", "checked_at"];

function loadFixtures(errors) {
  const out = [];
  for (const f of FIXTURES) {
    let view;
    try {
      view = JSON.parse(readFileSync(join(FIXDIR, f), "utf-8"));
    } catch (e) {
      errors.push(`fixture ${f} 读不出来：${e.message}`);
      continue;
    }
    if (!Array.isArray(view.products) || !view.counts) {
      errors.push(`fixture ${f} 缺 products/counts（accounts_view 出口，admin_accounts.py:518-522）`);
      continue;
    }
    for (const p of view.products) {
      for (const k of PRODUCT_KEYS) {
        if (!(k in p)) errors.push(`fixture ${f} 产品 ${p.id} 缺键 ${k}（asdict(ProductMeta)+models_wired）`);
      }
      for (const a of p.accounts) {
        for (const k of ACCOUNT_KEYS) {
          if (!(k in a)) errors.push(`fixture ${f} 的 ${p.id}/${a.name} 缺键 ${k}（_account_entry 白名单，admin_accounts.py:487-500）`);
        }
        if (a.resource !== null && Array.isArray(a.resource)) {
          for (const r of a.resource) {
            if (!r || typeof r.id !== "string" || typeof r.enabled !== "boolean") {
              errors.push(`fixture ${f} 的 ${p.id}/${a.name} resource 元素不是 {id, enabled}（_resource_projection）`);
            }
          }
          const a1 = (a.resource || []).map((r) => r.id).sort().join(",");
          const a2 = (a.quota.resources || []).slice().sort().join(",");
          if (a1 !== a2) errors.push(`fixture ${f} 的 ${p.id}/${a.name}：resource 的 rid 集与 quota.resources 不一致（同一 _matched_resources 谓词）`);
        }
        if (!["active", "disabled", "unknown"].includes(a.status)) {
          errors.push(`fixture ${f} 的 ${p.id}/${a.name} status=${a.status} 不在 active/disabled/unknown`);
        }
        // 视图契约同步：`runtime.quota` 存在就必须带齐快照 10 键（缺键 = fixture 落后于
        // `QuotaSnapshot`，判据读的是想象中的形状；多键不查，同 ACCOUNT_KEYS 的下界语义）
        const snap = (a.runtime || {}).quota;
        if (snap && typeof snap === "object") {
          for (const k of SNAP_KEYS) {
            if (!(k in snap)) {
              errors.push(`fixture ${f} 的 ${p.id}/${a.name} runtime.quota 缺键 ${k}`
                + `（_write_quota_cache 落盘键集 = SNAP_FIELDS ∪ {checked_at}，方案 §4-1/§4-2）`);
            }
          }
        }
      }
    }
    const n = view.products.reduce((s, p) => s + p.accounts.length, 0);
    const en = view.products.reduce((s, p) => s + p.accounts.filter((a) => a.enabled).length, 0);
    if (view.counts.accounts !== n || view.counts.enabled !== en || view.counts.products !== view.products.length) {
      errors.push(`fixture ${f} 的 counts 与 accounts 实数不符（accounts_view:520-521）`);
    }
    let caps;
    try {
      caps = JSON.parse(readFileSync(join(FIXDIR, "capabilities.json"), "utf-8"));
    } catch (e) {
      errors.push(`capabilities.json 读不出来：${e.message}`);
    }
    out.push({ name: f.replace(".json", ""), view, caps });
  }
  return out;
}

/** 登录向导桩：按当前产品的形态给 Challenge（§22.3 用户可见物，不含凭据）。
 *
 *  ⚠️ M7-C1 同步的真实契约（`model_gateway/accounts/types.py::Challenge`）：
 *  `qr_payload` = **服务端出的图片 data URI**（下面这份是从 `accounts/qr.png_data_uri()`
 *  对 raccoon 内容形态 `{api}/login/mp?code=<32hex>&appname=…` 的真机取样，scale=2/border=2；
 *  门只判 `data:image` 前缀与"不跨域"，不判像素），`url` = 二维码内容文字。
 *  🔴 旧桩给的是 `qr_payload = "https://…/qr-content"`（一条光秃秃的 URL 字符串）——
 *  那正是本轮修掉的缺陷形态，界面拿到它只能印成文字让用户"扫一行字"。
 */
const QR_IMAGE = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGoAAABqAQAAAAB8Wvk6AAABvUlEQVR42qVUMQoYQQiU2Ap+RbAV9usLtsJ+RbBd2JgikHA2IVscHIM6o6Pw/nwb/uk3QS+WqUoB7h/w96sndpiPOq76oqihrnDSRQfU7ity32dEFU/AwnwT+gxFFkStoW5z/v0Gzi1Lty20py3wk3kDawIEWg16PZ+LqbHS+WZmsGfLE+7+xl7cXRpNGPKrKGXlllJU219Fl3ceb7F76bduBSo9s1c6cL50vENtLWcdMhs+rZ6gFn9ZbXeIlyYpQ+ajshUrhPeQuU7jt9jIfOiGCVbt0GAfJuhlsAAM6A0oKDfWbcRvr1rNbrXccxy68VwzqH0hqN+6rwqXLJT2/FBX+qMg0aswZMZkVbrW1vx24x14N1uPMA1+trrdJFI9iwdWnIfcbm6d9LYnb14LqgEFdPLIo5HDpvQIb1sP0XJ9WSXIMqGrG4YJ5mU8yn4hhumrIgah45k29MRuskRt+K+f7zUWt4pf5hwcW7G9glbUsEeL3RawyDijlyep3SGeZ/CV4O1T57t0ujna1lhCB4fYQkk3+HWwYERv1ANSIpwuYZ/IFIozdKPeonW1mt/Qjb51uS713Zh28D8u/09SQb8/LanxIgAAAABJRU5ErkJggg==";
const loginStart = (p, kind) => ({
  session: "sess-gate-1", product: p.id, kind, account: `${p.id}-wiz`, ttl_s: 600,
  challenge: {
    url: "https://example.invalid/authorize?session=gate",
    device_code: kind === "device_code" ? "GX-012345" : "",
    qr_payload: kind === "qr" ? QR_IMAGE : "",
    sms_sent: false,
  },
});

/** 额度总额的 probe（V10'-②/④ 的数据源）：`[Σactive remaining, unit]`，只算**结构化行**。
 *  Σ 的口径照方案 §4-3/§6 表：失效包（`active === false`）不计入展示总额；
 *  `remaining` 非数值按 0 参与求和**是不允许的**（那正是 V14b 要禁的谎），所以这里
 *  只把数值项加起来 —— 全非数值的行 `sum` 为 0，由 `hasNum` 谓词在判据侧区分。 */
function quotaProbes(selected) {
  const probes = [];
  for (const a of selected.accounts) {
    const rq = a.runtime && a.runtime.quota;
    const items = rq && Array.isArray(rq.items) ? rq.items.filter((it) => it && it.name) : [];
    if (!items.length) continue;
    const act = items.filter((it) => it.active !== false);
    probes.push({
      key: `${selected.id}/${a.name}`,
      sum: act.reduce((s, it) => s + (typeof it.remaining === "number" ? it.remaining : 0), 0),
      unit: items[0].unit || "",
    });
  }
  return probes;
}

async function buildRuns(fixtures, pageSrc) {
  const runs = [];
  for (const fx of fixtures) {
    const n = fx.view.products.length;
    for (let i = 0; i < n; i += 1) {
      // 轮换 products 让每个产品都当上「默认选中项」：不依赖任何点击标记的实现细节
      const products = fx.view.products.slice(i).concat(fx.view.products.slice(0, i));
      const view = { ...fx.view, products };
      const selected = products[0];
      const kinds = [selected.login, ...(selected.login_alt || [])];
      const probes = quotaProbes(selected);
      const out = await renderRun(pageSrc, {
        view, caps: fx.caps, loginStart: loginStart(selected, kinds[0]), probes,
      });
      const qfmt = {};
      (out.qfmt || []).forEach((v, k) => { if (probes[k]) qfmt[probes[k].key] = v; });
      const emptyTree = () => ({ tree: { t: "div", a: {}, x: "", k: [] } });
      const page = out.stages.find((s) => s.kind === "page") || emptyTree();
      const wiz = out.stages.find((s) => s.kind === "wizard") || emptyTree();
      const chal = out.stages.find((s) => s.kind === "challenge") || emptyTree();
      runs.push({
        fixture: fx.name, selected, productCount: n, allProducts: products,
        pageNodes: flatten(page.tree, null, []),
        wizardNodes: flatten(wiz.tree, null, []),
        // 主形态展示物（切短信 tab 之前）：W1 的读取面
        challengeNodes: flatten(chal.tree, null, []),
        wizardNote: out.wizard, errs: out.errs, timers: out.timers,
        // V10'-④ 的数据面：页面缩写函数算出的每号总额串（键 = `<pid>/<账号名>`）
        qfmt, hasFmt: !!out.hasFmt,
      });
    }
  }
  return runs;
}

/* ==================== 断言求值 ==================== */

async function runChecks() {
  const checks = [];
  const errors = [];
  // 🔴 断言求不得把异常漏给外层：变异模式若靠「跑崩了」算红，等于用崩溃冒充证据
  //    （照 verify_v2_frontend.mjs:1020-1042 的 check 口径）
  const check = (id, desc, fn, detail = "") => {
    let passed = false;
    let note = "";
    try {
      const v = typeof fn === "function" ? fn() : fn;
      try { note = typeof detail === "function" ? detail() : detail; }
      catch { note = "(detail 求值失败)"; }
      passed = !!v;
    } catch (e) {
      passed = false;
      note = `求值抛错 ${e && e.name}: ${String(e && e.message).slice(0, 140)}`;
    }
    checks.push({ id, desc, ok: passed, detail: note });
  };

  const pageSrc = readFileSync(PAGE_FILE, "utf-8");
  const fixtures = loadFixtures(errors);
  if (errors.length) return { checks, errors, runs: [] };
  const runs = decorateRuns(await buildRuns(fixtures, pageSrc));
  const allNodes = () => runs.flatMap((r) => [...r.pageNodes, ...r.wizardNodes]);
  const pageNodes = () => runs.flatMap((r) => r.pageNodes);

  /* ---------- F · 渲染现场可达性（页面渲染不出来 = 本门的判据，不是被吞掉的异常） ---------- */
  const threw = runs.flatMap((r) => r.errs.map((e) => `${r.fixture}/${r.selected.id}: ${e}`));
  check("R0", "页面可渲染：三轮 fixture × 全部产品面板，renderAccounts(root) 未抛错且产出 DOM",
    () => threw.length === 0 && runs.every((r) => r.pageNodes.length > 1),
    () => threw.length ? threw.slice(0, 3).join(" | ")
      : `runs=${runs.length} 节点最少=${Math.min(...runs.map((x) => x.pageNodes.length))}`);

  /* ---------- V1 · §2 族层消失（设计书 §8-①） ---------- */
  const perRun = runs.map((r) => ({
    r, gc: sel(r.pageNodes, ".group-card").length, mb: sel(r.pageNodes, ".mode-btn").length,
    ai: sel(r.pageNodes, ".anchor-item").length,
  }));
  const v1bad = perRun.filter((x) => x.gc || x.mb);
  check("V1", "① 族层消失：.group-card 与 .mode-btn 计数都必须为 0（产品降为 rail 选择器，不是容器）",
    v1bad.length === 0,
    () => v1bad.length
      ? `${v1bad.length}/${runs.length} 轮仍有族层：每轮 .group-card=${v1bad[0].gc} .mode-btn=${v1bad[0].mb}（两者都必须为 0；rail 行改用 .anchor-item）`
      : ".group-card=0 .mode-btn=0");

  /* ---------- V2 · §2 rail 行数 = 在册产品数（设计书 §8-②） ---------- */
  const railBad = perRun.filter((x) => x.ai !== x.r.productCount)
    .map((x) => `${x.r.fixture}/${x.r.selected.id}=${x.ai}`);
  check("V2", "② .anchor-item 计数 === fixture 产品数（10 个在册产品全数平铺，0 账号产品也在列）",
    railBad.length === 0,
    () => railBad.length ? `期望 ${runs[0].productCount}，不符 ${railBad.length}/${runs.length} 轮：${railBad.slice(0, 3).join(" ")}`
      : `每轮 .anchor-item=${perRun[0].ai}`);

  /* ---------- V9 · §2 rail 用**每个产品自己的官方图标**（2026-09-30 用户要求：用对应产品的 icon） ---------- */
  const iconBad = [];
  const seen = new Set();
  for (const r of runs) {
    for (const pid of r.allProducts.map((p) => p.id)) {
      // 选择器引擎语义：在本批节点里筛出"属于某祖先"的节点 —— 后代关系写在选择器里，不能传子树当根
      const img = sel(r.pageNodes, `.anchor-item[data-pid="${pid}"] img`)[0];
      const src = img ? String(img.a.src || "") : "";
      if (!/^\/img\/products\//.test(src)) { iconBad.push(`${r.fixture}/${pid}: 无产品图标 img（src=${src || "空"}）`); continue; }
      const want = src.replace(/^\/img\/products\//, "").replace(/\.(png|svg)$/, "");
      if (want !== pid) iconBad.push(`${r.fixture}/${pid}: 图标张冠李戴 → ${src}`);
      seen.add(src.replace(/^\//, ""));
    }
  }
  const missingFiles = [...seen].filter((rel) => !existsSync(join(ROOT, "coding/model_gateway/web/static", rel)));
  check("V9", "⑩ rail 每行用**该产品自己的官方图标**（`/img/products/<id>.<png|svg>`，文件必须真实存在）",
    iconBad.length === 0 && missingFiles.length === 0,
    () => iconBad.length || missingFiles.length
      ? `${[...new Set(iconBad)].slice(0, 3).join(" | ")}${missingFiles.length ? ` ｜ 盘上缺文件：${missingFiles.slice(0, 3).join(",")}` : ""}`
      : `10 个产品图标逐一对上且文件在盘（${seen.size} 个）`);

  /* ---------- V3 · §2 接入入口唯一（2026-09-30 修订：入口在**卡头**，与所作用产品同框） ---------- */
  const entries = (r) => {
    const head = sel(r.pageNodes, ".card-head #ac-add");
    const elsewhere = sel(r.pageNodes, "button").filter((b) => (text(b).indexOf("接入账号") >= 0)
      && !inside(b, ".card-head"));
    return { head: head.length, elsewhere: elsewhere.length };
  };
  const eBad = perRun.map(({ r }) => ({ r, e: entries(r) }))
    .filter(({ e }) => e.head !== 1 || e.elsewhere !== 0)
    .map(({ r, e }) => `${r.fixture}/${r.selected.id}: .card-head #ac-add=${e.head} 他处接入钮=${e.elsewhere}`);
  check("V3", "③ 接入入口恰好 1 处，且在卡头（与所作用产品同框；rail 底与空态都不放按钮）",
    eBad.length === 0, () => eBad.length ? `${eBad.length}/${runs.length} 轮不符：${[...new Set(eBad)].slice(0, 2).join(" | ")}` : "各轮 head=1 他处=0");

  /* ---------- V4' · §0-4 BUG-1：额度格必须接 a.runtime.quota（方案 §8.2 ① = QA X-R5-1 原文） ------ */
  const bug1 = [];
  let v4Rows = 0;
  for (const r of runs) {
    if (!r.selected.accounts.length) continue;
    const tbl = tableInfo(r.pageNodes);
    if (!tbl.has) continue;
    for (const a of r.selected.accounts) {
      const rq = (a.runtime && a.runtime.quota) || null;
      // V4'（方案 §8.2 ①/X-R5-1）：**白名单放开** —— unknown / no_plan 一样要有运行态快照。
      // 🔴 只保留「额度格有没有取到运行态快照」这一件事；带 items 的行归 V10' 的总额一致性管
      //    （否则正确实现必红：结构化行的合法文案是「套餐徽章 + 总额」，五档档位词从不进它）。
      if (!rq) continue;
      if (a.quota && a.quota.state !== "unknown") continue;   // 判别样本前提（QA r4 N-1）
      const row = tbl.rows.filter((tr) => text(tr).indexOf(a.name) >= 0)[0];
      if (!row) { bug1.push(`${r.fixture}/${r.selected.id}/${a.name}: 找不到账号行`); continue; }
      const q = quotaCellOf(tbl, row.k.filter((c) => c.t === "td"));
      const got = q.cell ? cut(visibleText(q.cell), 40) : `（${q.err}）`;
      const itX = Array.isArray(rq.items) ? rq.items.filter((x) => x && x.name) : [];
      const want = rq.reason === "no_plan" ? NO_PLAN_WORD : (WANT_BY_STATE[rq.state] || null);
      // 🔴 旧形 `got.indexOf("未知") < 0` 这半边**必须删**（它对 BUG-1 不损失判别力：接错到池摘要
      //    时渲染的是 —/空/尚未刷新，`want` 一定不在串里），而留着它 + 白名单放开 = `state=unknown`
      //    行的**恒假判据**（X-R5-1）；`|| /[0-9]/.test(got)` 逃生口同样**必须删**——时间戳
      //    「查于 2026-10-02 09:12」就能把它糊过去（QA r5 X-R5-1 / r4 E3 实测 17/0）。
      const okText = !want || itX.length > 0 || got.indexOf(want) >= 0;
      if (!okText) {
        bug1.push(`${r.fixture}/${r.selected.id}/${a.name}: 额度格「${cut(got, 24)}」未取到运行态快照的值（want=「${want}」 state=${rq.state} reason=${rq.reason || "∅"}；BUG-1：quotaCell 只读 a.quota，从不读 runtime.quota）`);
      }
      if (want && itX.length === 0) v4Rows += 1;
    }
  }
  // 🔴 死判据防护：判别样本不在场（fixture 被改坏/被删）时本条等于没断言
  if (v4Rows < 6) bug1.push(`V4 的判别样本只剩 ${v4Rows} 行（无 items 且池摘要 unknown 的运行态快照行必须成批在场，否则本条恒真）`);
  check("V4", "④' 额度格取到运行态快照：无 items 的行必须出现 state/reason → 档位词（白名单放开到 unknown/no_plan，钉 BUG-1）",
    bug1.length === 0, () => bug1.length ? `${bug1.length} 处：${[...new Set(bug1)].slice(0, 3).join(" | ")}` : `全部判别样本（${v4Rows} 行）都取到 runtime.quota 的档位词`);

  /* ---------- V5 · §2/§8-⑤ 圆点不当动作目标 ----------
   * 判据收窄口径（设计书 §8-⑤ v2.1 更正 + v2.1 自纠表第 3 行）：
   *   · 🔴 禁止：`.dot` 落在 `[role=switch]` 里 —— frontend-spec.md:524 禁的是「用圆点承担开关」，
   *     开关的语义载荷必须是 role/aria-checked，不能是一个变色的小圆点；
   *   · ✅ 合法：rail `.anchor-item` 里的 `.dot` —— 那颗按钮的动作是**选中产品**（切换面板），
   *     点只是四态状态指示（§2），不是被切换的值；因此圆点不得是该按钮的**唯一**语义载荷：
   *     按钮必须另带产品名文本。 */
  const dotInSwitch = sel(allNodes(), "[role=switch] .dot").length;
  const dotOnly = [];
  for (const b of sel(allNodes(), "button")) {
    if (!sel([b], ".dot").length) continue;
    const label = cut(text(b).replace(/\s+/g, " "), 200);
    const ariaLabel = b.a["aria-label"] || "";
    if (!label && !ariaLabel) dotOnly.push(pathOf(b));
  }
  check("V5", "⑤ 圆点不当动作目标：[role=switch] 内不得有 .dot；rail .anchor-item 内的点合法但须另有文本载荷",
    dotInSwitch === 0 && dotOnly.length === 0,
    `[role=switch] 内 .dot=${dotInSwitch}（必须 0）; 圆点为唯一语义载荷的按钮=${dotOnly.length}${dotOnly.length ? `（${dotOnly.slice(0, 2).join(" / ")}）` : ""}`);

  /* ---------- V6 · 表头逐字（2026-10-01 改版：展开列已废，4 列固定列集） ---------- */
  const HEAD_EXACT = ["账号", "状态", "额度", "操作"];
  const headBad = [];
  for (const r of runs) {
    if (!r.selected.accounts.length) continue;
    const tbl = tableInfo(r.pageNodes);
    if (!tbl.has) { headBad.push(`${r.fixture}/${r.selected.id}: 有账号却没渲染表格`); continue; }
    const texts = tbl.ths.map((t) => t.text);
    const legacy = texts.filter((t) => t === "参与运营" || t === "最近结果");
    if (legacy.length) headBad.push(`${r.fixture}/${r.selected.id}: 残留列「${legacy.join("、")}」（已删）`);
    if (texts.some((t, i) => t !== HEAD_EXACT[i]) || tbl.ths.length !== HEAD_EXACT.length) {
      headBad.push(`${r.fixture}/${r.selected.id}: 列集 ${JSON.stringify(texts)} ≠ ${JSON.stringify(HEAD_EXACT)}`);
    }
    if (tbl.ths.some((t) => t.exp)) headBad.push(`${r.fixture}/${r.selected.id}: 残留 .exp 展开指示列（2026-10-01 已废除展开行）`);
  }
  check("V6", "⑥ 表头逐字 = 账号 / 状态 / 额度 / 操作（4 列，无展开指示列），且无「参与运营」「最近结果」列",
    headBad.length === 0, () => headBad.length ? `${headBad.length} 处：${[...new Set(headBad)].slice(0, 3).join(" | ")}` : "列集逐字相符");

  /* ---------- V7' · 额度**五档**词表 + `state/reason → 文案` 映射断言（方案 §8.2 ②③） ----------
   * 🔴 只查"词表合法性"= 需求没做也绿（评审实测：页面完全没实现「无套餐」映射、fixture 塞一行
   *    no_plan 数据，门照样 17/0）⇒ 本条必须钉**映射**：状态决定文案。
   *    豁免只让给 `reason !== "no_plan"` 的结构化行（QA X-R4-9 的 `mapExempt` 原文），
   *    否则 `state=available + items` 的合法行被误红（那条文案本来就是「套餐徽章 + 总额」）。
   *    push 串一律 `(rqM && rqM.state) || "∅"` 防 undefined（X-R5-3：需求没做时门必须以**红**
   *    收场，而不是解引用崩到退出码 2、把 `--mutation` 记成 BAD = 用崩溃冒充证据）。 */
  const vocabBad = [];
  const notFresh = [];
  let mapRows = 0;
  let noPlanRows = 0;
  for (const r of runs) {
    if (!r.selected.accounts.length) continue;
    const tbl = tableInfo(r.pageNodes);
    if (!tbl.has) continue;
    if (tbl.quotaIndex < 0) { vocabBad.push(`${r.fixture}/${r.selected.id}: 有账号却没有额度列`); continue; }
    r.selected.accounts.forEach((a, i) => {
      const row = tbl.rows[i];
      if (!row || text(row).indexOf(a.name) < 0) { vocabBad.push(`${r.fixture}/${r.selected.id}: 第 ${i} 行与数据错位`); return; }
      const q = quotaCellOf(tbl, row.k.filter((c) => c.t === "td"));
      if (q.err) { vocabBad.push(`${r.fixture}/${r.selected.id}/${a.name}: ${q.err}`); return; }
      const rqM = a.runtime && a.runtime.quota;
      const structX = (rqM && Array.isArray(rqM.items) ? rqM.items : []).filter((it) => it && it.name);
      const got = cut(visibleText(q.cell), 60);
      // 「无套餐」行**即使带 items** 也在词表内（它本来就不该出数字），所以豁免条件与映射同源
      if (structX.length === 0 || (rqM && rqM.reason === "no_plan")) {
        const hit = QUOTA_WORDS.filter((w) => got.indexOf(w) >= 0);
        const nonce = QUOTA_NONCE.filter((w) => got.indexOf(w) >= 0);
        if (hit.length !== 1 || nonce.length) {
          vocabBad.push(`${r.fixture}/${r.selected.id}/${a.name}: 额度格「${cut(got, 30)}」不在五档口径内或越界（${QUOTA_WORDS.join("/")}；命中 ${JSON.stringify(hit)}；§4-7 硬约束 = 可见文本不得含其它档词子串）`);
        }
      }
      const wantM = !rqM ? "尚未刷新"
        : (rqM.reason === "no_plan" ? NO_PLAN_WORD : (WANT_BY_STATE[rqM.state] || null));
      const mapExempt = structX.length > 0 && !(rqM && rqM.reason === "no_plan");   // 只有这里能豁免
      if (wantM && !mapExempt) {
        mapRows += 1;
        if (rqM && rqM.reason === "no_plan") noPlanRows += 1;
        if (got.indexOf(wantM) < 0) {
          vocabBad.push(`${r.fixture}/${r.selected.id}/${a.name}: state=${(rqM && rqM.state) || "∅"} reason=${(rqM && rqM.reason) || "∅"} 应出「${wantM}」却渲染「${cut(got, 30)}」（§4-7 五档：状态决定文案，不是词表合法性）`);
        }
      }
      if (!rqM && got.indexOf("尚未刷新") < 0) {
        notFresh.push(`${r.fixture}/${r.selected.id}/${a.name}: runtime.json 无 quota 快照却写「${cut(got, 20)}」（§3 第四态必须与「未知」区分：网关还没查过 ≠ 查了但拿不到）`);
      }
    });
  }
  // 🔴 死判据防护：「无套餐」这一档的两个判别样本（items=[] 与 items.length>0）必须在场，
  //    否则映射断言对新档零覆盖（QA r3 X-R3-2 第 3 条）
  if (noPlanRows < 2) {
    vocabBad.push(`判别样本不足：五档映射只核到 ${mapRows} 行、其中「无套餐」行 ${noPlanRows} 行（`
      + "items=[] 与 items.length>0 两类 no_plan 样本都要在 fixture 里，否则本条对新档恒真）");
  }
  check("V7", "⑦' 额度文本 ⊂ {有余量, 已耗尽, 无套餐, 未知, 尚未刷新} **且** state/reason 决定文案，缺 runtime.json 快照的行写「尚未刷新」",
    vocabBad.length === 0 && notFresh.length === 0,
    () => {
      const u = [...new Set(vocabBad.concat(notFresh))];
      return u.length ? `${u.length} 处：${u.slice(0, 3).join(" | ")}` : `五档词表 + 映射核对 ${mapRows} 行（其中 no_plan ${noPlanRows} 行）`;
    });

  /* ---------- V10 · 结构化套餐余粮展示（2026-10-01 用户指示，DSH Jet Hub 展示公式） ----------
   * 带结构化逐包数据（`runtime.quota.items`）的账号行，额度格必须：
   *   含「查于」（刷新时间恒示）+ 套餐名徽章（`plan` 取到了就必须显示）+
   *   量纲标签（Token/积分）或数字；失效包 >0 必须出「已失效」注记。
   * 🔴 逐包明细进 tooltip（title 属性），不在常驻面刷屏 —— 断言 title 含包名。
   * 2026-10-02 按方案 §8.2 ②（QA X-R5-2 原文）去掉三条自我豁免：
   *   ① 「查于」的剥离走 **DOM 结构**（`.qchk`）而不用「查于+非数字通配」的旧正则（那正则会连旁边的数字
   *      一起剥掉，等于判据自己给自己让路）；
   *   ② 总额一致性 = `Σ active remaining` 经**页面缩写函数**（realm 回传 `r.qfmt`）缩写后的
   *      **完整 token** 比对（禁 `300 ⊂ 1300` 那种子串侥幸），且只在"上游确实给了量化余量"
   *      （`hasNum`）时钉 —— null 行的正确档位是「未知」，归 V14b 管（v5 两条互斥 = 要绿必须撒谎）；
   *   ③ `hasNum && Σ<=0` 的行必须显式出「已耗尽」或「无套餐」**且量纲不消失**（可见或 tooltip，
   *      评审 N-3 的既有缺陷：`total<=0` 那一支把 Token 一起吞了）；
   *   ④ 缩写算法**不在门内重写第二份**（两份一起错就永远绿），取不到 realm 函数直接报红。 */
  const structBad = [];
  let structRows = 0;
  for (const r of runs) {
    if (!r.selected.accounts.length) continue;
    const tbl = tableInfo(r.pageNodes);
    if (!tbl.has) continue;
    if (tbl.quotaIndex < 0) { structBad.push(`${r.fixture}/${r.selected.id}: 有账号却没有额度列`); continue; }
    for (const a of r.selected.accounts) {
      const rq = a.runtime && a.runtime.quota;
      const items = rq && Array.isArray(rq.items) ? rq.items : [];
      if (!items.length) continue;
      // 🔴 no_plan 行不归本条：它的正确文案就是「无套餐」（**不显示数字**），
      //    数字面由 V14 钉（分支顺序：no_plan 支排在结构化支之前）。
      if (rq.reason === "no_plan") continue;
      structRows += 1;
      const row = tbl.rows.filter((tr) => text(tr).indexOf(a.name) >= 0)[0];
      if (!row) { structBad.push(`${r.fixture}/${r.selected.id}/${a.name}: 找不到账号行`); continue; }
      const q = quotaCellOf(tbl, row.k.filter((c) => c.t === "td"));
      if (q.err) { structBad.push(`${r.fixture}/${r.selected.id}/${a.name}: ${q.err}`); continue; }
      const got = visibleText(q.cell);
      const main = cellTextExcept(q.cell, "qchk");          // ① 结构剥离「查于 …」那一行
      const tipX = tipOf(q.cell);                            // 量纲允许只出现在 tooltip
      const expiredN = items.filter((it) => it && it.active === false).length;
      const problems = [];
      if (got.indexOf("查于") < 0) problems.push("缺「查于」刷新时间");
      if (rq.plan && got.indexOf(rq.plan) < 0) problems.push(`缺套餐徽章「${rq.plan}」`);
      const unit0 = String((items[0] && items[0].unit) || "");
      if (unit0 && !/(Token|积分)/i.test(`${got} ${tipX}`)) problems.push("缺量纲标签（Token/积分，可见或 tooltip）");
      // ③ 只钉"给了量化余量却合计 0"的行；一个都没给的行归 V14b 管
      const hasNum = items.some((it) => typeof it.remaining === "number");
      const actX = items.filter((it) => it && it.active !== false);
      const sumAct = actX.reduce((s, it) => s + (typeof it.remaining === "number" ? it.remaining : 0), 0);
      if (hasNum && sumAct <= 0) {
        if (!/(已耗尽|无套餐)/.test(main)) {
          problems.push("Σ余量=0 的行必须显式出「已耗尽」或「无套餐」（不得只印 0）");
        } else if (unit0 && !/\d[\s,]*(Token|积分|\/token)/i.test(
          `${cellTextExceptAll(q.cell, ["qchk", "qpacks-detail"])} ${tipX}`)) {
          // 🔴 本意是「Σ=0 的行不许把量纲弄丢」（评审 N-3），不是「量纲必须紧贴在档位词后面」。
          //    原写法 `(已耗尽|无套餐)\s*(Token|积分)` 把两件事混成一件，于是页面只能渲染成
          //    「已耗尽 Token」——状态词后面直接接单位，用户读作"已耗尽 个 Token？"（实盘 15:39 看着就别扭）。
          //    现行页面把**数值与量纲放在一起**（`0 Token`）、档位词紧随其后。
          //    ⚠️ 判据面必须剥掉折叠的逐包明细（`.qpacks-detail` 里恒写「合计剩余 N Token」），
          //    否则"摘掉常驻量纲"的坏实现也会被判绿（实测：不剥时 23/0 全绿；剥后该变异必红）。
          problems.push("Σ余量=0 的行量纲标注不得消失（常驻面须有『数字+量纲』，可见或 tooltip，评审 N-3）");
        }
      } else if (hasNum && sumAct > 0) {
        // ②④ 期望串来自 realm 里的页面函数，门内不重算缩写
        const want10 = r.qfmt[`${r.selected.id}/${a.name}`];
        if (!r.hasFmt) {
          problems.push("realm 取不到页面缩写函数 fmtQuotaNumber（V10'-④：判据不得在门内重写第二份算法）");
        } else if (want10 === undefined) {
          problems.push(`realm 没回传本号的缩写串（probe 缺键 ${r.selected.id}/${a.name}）`);
        } else if (!tokenRe(want10).test(main)) {
          problems.push(`总额与 Σactive remaining 不符：期望完整 token「${want10}」，实得「${cut(main, 48)}」（禁 300⊂1300 子串侥幸）`);
        }
      }
      if (expiredN > 0 && got.indexOf("已失效") < 0) problems.push(`有 ${expiredN} 个失效包却无「已失效」注记`);
      // 排除与套餐同名的包：套餐徽章的 title（「套餐：X」）也含 X，拿它核对是假通过
      const firstActive = items.find((it) => it && it.active !== false && it.name && it.name !== rq.plan);
      /* 🔴 2026-10-02 用户指令推进（旧判据"逐包明细只许写在本格 title 上"随之作废）：
         31 个包时 tooltip 既不可选中也不能复制，还被实现截断到 12 行 ⇒ 明细必须住在
         **本格内的就地展开块**（`.qpacks-detail`）里并**全量**列出；tooltip 只留套餐名。
         设计变了，钉旧设计的判据要带着理由前进，不许退回。 */
      const detail = (r.pageNodes || []).filter((n) => has(n, "qpacks-detail")
        && String((n.a && n.a["data-qpacks-for"]) || "") === a.name)[0];
      const dtxt = detail ? text(detail) : "";
      if (!detail) problems.push("本格无就地展开的逐包明细块（.qpacks-detail）");
      else if (firstActive && dtxt.indexOf(firstActive.name) < 0) problems.push("展开块里没有逐包行");
      if (got.indexOf("展开") < 0 || !/个包/.test(got)) problems.push("缺「展开 N 个包」入口（明细只能靠悬停 = 用户指令的原始缺陷）");
      if (items.length > 12 && dtxt.indexOf(`共 ${items.length} 个包`) < 0) {
        problems.push(`展开块必须全量并写明「共 ${items.length} 个包」（截断到 12 行会让用户以为只有 12 个）`);
      }
      if (problems.length) structBad.push(`${r.fixture}/${r.selected.id}/${a.name}: ${problems.join("；")}`);
    }
  }
  if (structRows < 5) {
    structBad.push(`结构化判别样本只剩 ${structRows} 行（V10' 没有对象 = 死判据；正常应 ≥5：buddy-main + 5 条 ix-* 结构化行）`);
  }
  check("V10", "⑩' 结构化套餐余粮：查于 + 套餐徽章 + 量纲 + **总额=Σactive remaining（页面缩写函数算）** + 失效包注记 + 本格 tooltip 逐包明细",
    structBad.length === 0 && structRows > 0,
    () => structBad.length ? `${structBad.length} 处：${[...new Set(structBad)].slice(0, 3).join(" | ")}` : `结构化展示核对 ${structRows} 行（总额一致性用 realm fmtQuotaNumber）`);

  /* ---------- V11 · 续期回行内 + 登录态倒计时（2026-10-01 用户裁决） ----------
   * ① 行内动作 = 中文文字按钮，`data-op="refresh"` 的**有无**必须与能力位 `refresh` 严格同相
   *    （能力位是判据不是标签：false 产品渲染 = 死钮，true 产品不渲染 = 功能缺失）；
   * ② 可续期产品必须给出登录态位：有 `credential_expires_at` → 写"登录态 … 失效"，
   *    没有 → 如实写"登录态失效时间未知"（**不判定、不猜**）；
   * ③ 不可续期产品**不写**倒计时位（不制造无意义的焦虑）。 */
  const renewBad = [];
  let renewRows = 0;
  for (const r of runs) {
    const cap = r.selected.capabilities || {};
    for (const a of r.selected.accounts) {
      renewRows += 1;
      const btns = sel(r.pageNodes, `tr[data-acc="${a.name}"] [data-op]`);
      const ops = btns.map((b) => b.a["data-op"]);
      const hasRefresh = ops.indexOf("refresh") >= 0;
      if (hasRefresh !== !!cap.refresh) {
        renewBad.push(`${r.fixture}/${a.name}: 续期钮=${hasRefresh} 与能力位 refresh=${!!cap.refresh} 不同相（ops=${JSON.stringify(ops)}）`);
      }
      for (const b of btns) {
        if (!visibleText(b).trim()) renewBad.push(`${r.fixture}/${a.name}: 有无可见文字的钮（操作列必须是中文文字按钮）@ ${pathOf(b)}`);
      }
      const cell = sel(r.pageNodes, `tr[data-acc="${a.name}"] td`)[0];
      const cellText = cell ? visibleText(cell) : "";
      if (cap.refresh) {
        if (a.credential_expires_at) {
          if (cellText.indexOf("登录态") < 0 || cellText.indexOf("失效") < 0) {
            renewBad.push(`${r.fixture}/${a.name}: 有 credential_expires_at 却没渲染登录态倒计时位`);
          }
        } else if (cellText.indexOf("登录态失效时间未知") < 0) {
          renewBad.push(`${r.fixture}/${a.name}: 拿不到失效时刻却没写「登录态失效时间未知」（未知也要说清楚）`);
        }
      } else if (cellText.indexOf("登录态") >= 0) {
        renewBad.push(`${r.fixture}/${a.name}: 不可续期产品却出现登录态位（无意义焦虑）`);
      }
    }
  }
  check("V11", "⑪ 续期钮与能力位同相 + 操作列全中文文字 + 登录态倒计时位（未知如实写、不可续期产品不写）",
    renewBad.length === 0 && renewRows > 0,
    () => renewBad.length ? `${renewBad.length} 处：${[...new Set(renewBad)].slice(0, 3).join(" | ")}` : `核对 ${renewRows} 行`);

  /* ---------- V12 · 映射弹窗内零账号级动作（2026-10-01 用户裁决：续期回行内） ----------
   * 弹窗只承载产品级信息（目录 + 映射），账号级动作（续期）一律在列表行内。 */
  const modalOpsBad = [];
  for (const r of runs) {
    for (const n of sel(r.pageNodes, "[data-mop]")) modalOpsBad.push(`${r.fixture}: 面板里出现 [data-mop] 动作 @ ${pathOf(n)}`);
  }
  if (pageSrc.indexOf("mapAccountsHTML") >= 0) {
    modalOpsBad.push("页面源码仍留有 mapAccountsHTML（弹窗内账号操作区必须整体移除）");
  }
  check("V12", "⑫ 弹窗零账号级动作：页面无 [data-mop]、源码无 mapAccountsHTML（续期只在行内）",
    modalOpsBad.length === 0, () => modalOpsBad.length ? [...new Set(modalOpsBad)].slice(0, 3).join(" | ") : "零命中");

  /* ---------- V13 · 「刷新额度」两处入口与 `balance` 能力位同相（方案 §5-2/§5-6，指令 2 = 10/10） ----------
   * 行内第 3 颗（签到 · 续期 · 刷新额度 · 探活 · 删除）+ 卡头一颗，**同一判据** = `capabilities.balance`
   * （能力位是判据不是标签：false 产品渲染 = 死钮，true 产品不渲染 = 功能缺失，同 V11 口径）。
   * 卡头钮数按能力位逐档对表（模型映射 + 接入账号恒在 = 2 颗底，checkin/balance/refresh 各加一颗，
   * ZCode 另加导入/购买两颗），并**绝对钉住** buddy 形态 = 5 颗（frontend-spec 行内 5 钮 / 卡头 5 钮的
   * 定版事实，不随能力位漂移）。
   * ⚠️ 诚实标注：10/10 产品 `balance=True` ⇒ 本条只有正例，**未构造 `balance=false` 的反例形态**
   *   （方案 §8.2 真机段落同一声明）；反例要 monkeypatch 假能力位，属 pytest 面。 */
  const quotaOpBad = [];
  let quotaOpRows = 0;
  for (const r of runs) {
    const cap = r.selected.capabilities || {};
    const headBtns = sel(r.pageNodes, ".card-head .btn");
    const headQuota = headBtns.filter((b) => b.a.id === "ac-quota").length;
    const wantHead = 2 + (cap.checkin ? 1 : 0) + (cap.balance ? 1 : 0) + (cap.refresh ? 1 : 0)
      + (r.selected.id === "zcode" ? 2 : 0);
    if (headQuota !== (cap.balance ? 1 : 0)) {
      quotaOpBad.push(`${r.fixture}/${r.selected.id}: 卡头「刷新额度」=${headQuota} 与能力位 balance=${!!cap.balance} 不同相`);
    }
    if (headBtns.length !== wantHead) {
      quotaOpBad.push(`${r.fixture}/${r.selected.id}: 卡头钮数 ${headBtns.length} ≠ 能力位对表值 ${wantHead}（模型映射+接入账号恒在，checkin/balance/refresh 各一颗，ZCode 另加导入/购买）`);
    }
    if (r.selected.id === "buddy" && headBtns.length !== 5) {
      quotaOpBad.push(`${r.fixture}/buddy: 卡头钮数 ${headBtns.length} ≠ 定版 5 颗（模型映射/一键领取/刷新额度/批量续期/接入账号）`);
    }
    for (const a of r.selected.accounts) {
      quotaOpRows += 1;
      const ops = sel(r.pageNodes, `tr[data-acc="${a.name}"] [data-op]`).map((b) => b.a["data-op"]);
      const hasQuota = ops.indexOf("quota") >= 0;
      if (hasQuota !== !!cap.balance) {
        quotaOpBad.push(`${r.fixture}/${a.name}: 行内「刷新额度」=${hasQuota} 与能力位 balance=${!!cap.balance} 不同相（ops=${JSON.stringify(ops)}）`);
      }
      if (ops.indexOf("quota") >= 0 && ops.indexOf("refresh") >= 0
        && ops.indexOf("quota") !== ops.indexOf("refresh") + 1) {
        quotaOpBad.push(`${r.fixture}/${a.name}: 行内钮序不是「续期 → 刷新额度 → 探活」（§5-6 定版第 3 颗）：${JSON.stringify(ops)}`);
      }
    }
  }
  check("V13", "⑬ 行内第 3 颗与卡头的「刷新额度」都与 `balance` 能力位同相；卡头钮数与能力位逐档对表（buddy 定版 5 颗）",
    quotaOpBad.length === 0 && quotaOpRows > 0,
    () => quotaOpBad.length ? `${quotaOpBad.length} 处：${[...new Set(quotaOpBad)].slice(0, 3).join(" | ")}` : `核对 ${quotaOpRows} 行 + ${runs.length} 轮卡头（balance 全 true ⇒ 只钉了正例，false 形态未构造）`);

  /* ---------- V14 · 裁决③：`reason==="no_plan"` **无论有没有 items** 必出「无套餐」+ title ----------
   * 这条打的是**分支顺序**（页面 `quotaCell` 把 no_plan 支排在结构化支之前），
   * `ix-noplan-items` 一行（🔴 非可产出形状：后端 no_plan 走整键覆盖 ⇒ items 恒空，
   * 样本只用来把顺序钉死）与 `ix-no-plan` / `buddy-noplan` 成对。
   * title 必带**两可性原文**（§8.2 裁决③：「`plans=[]` 是确实无套餐还是身份无 entitlement」未判定）。 */
  const noPlanBad = [];
  let noPlanSeen = 0;
  let noPlanWithItems = 0;
  for (const r of runs) {
    const tbl = tableInfo(r.pageNodes);
    if (!tbl.has || tbl.quotaIndex < 0) continue;
    for (const a of r.selected.accounts) {
      const rq = a.runtime && a.runtime.quota;
      if (!rq || rq.reason !== "no_plan") continue;
      noPlanSeen += 1;
      const withItems = (Array.isArray(rq.items) ? rq.items : []).filter((it) => it && it.name).length > 0;
      if (withItems) noPlanWithItems += 1;
      const row = tbl.rows.filter((tr) => text(tr).indexOf(a.name) >= 0)[0];
      if (!row) { noPlanBad.push(`${r.fixture}/${r.selected.id}/${a.name}: 找不到账号行`); continue; }
      const q = quotaCellOf(tbl, row.k.filter((c) => c.t === "td"));
      if (q.err) { noPlanBad.push(`${r.fixture}/${r.selected.id}/${a.name}: ${q.err}`); continue; }
      const got = cut(visibleText(q.cell), 60);
      const tip = tipOf(q.cell);
      if (got.indexOf(NO_PLAN_WORD) < 0) {
        noPlanBad.push(`${r.fixture}/${r.selected.id}/${a.name}: reason=no_plan（items ${withItems ? "有" : "空"}）却渲染「${got}」，没出「无套餐」（裁决③：no_plan 支必须排在结构化支之前）`);
      }
      if (!tip.trim()) {
        noPlanBad.push(`${r.fixture}/${r.selected.id}/${a.name}: 「无套餐」没有 title 说明（§8.2 裁决③：title 必须带"确实无套餐 vs 身份无 entitlement"的两可性原文，不许把未判定印成结论）`);
      }
    }
  }
  if (noPlanSeen < 2 || noPlanWithItems < 1) {
    noPlanBad.push(`no_plan 判别样本不足：共 ${noPlanSeen} 行、其中带 items 的 ${noPlanWithItems} 行（两类都要在，否则分支顺序零覆盖 = 死判据）`);
  }
  check("V14", "⑭ 无套餐档：reason=no_plan 无论有无 items 必出「无套餐」，且本格带 title 两可性原文",
    noPlanBad.length === 0,
    () => noPlanBad.length ? [...new Set(noPlanBad)].slice(0, 3).join(" | ") : `核对 ${noPlanSeen} 行 no_plan（含 ${noPlanWithItems} 行带 items 的顺序样本）`);

  /* ---------- V14b · `remaining:null` 的行**不得**渲染「已耗尽」（方案 §4-3/§4-4） ----------
   * 「没给数字」与「数字是 0」是两件事；把前者渲染成后者 = 本轮点名的谎（工程 r3 B-R3-3）。
   * 与 V10'-③ 的分工（QA X-R5-2）：**上游一个量化余量都没给**的行归本条，
   * 给了却合计 0 的行归 ③，两条互不打架。 */
  const nullBad = [];
  let nullRows = 0;
  for (const r of runs) {
    const tbl = tableInfo(r.pageNodes);
    if (!tbl.has || tbl.quotaIndex < 0) continue;
    for (const a of r.selected.accounts) {
      const rq = a.runtime && a.runtime.quota;
      const items = rq && Array.isArray(rq.items) ? rq.items.filter((it) => it && it.name) : [];
      if (!items.length) continue;
      const hasNum = items.some((it) => typeof it.remaining === "number");
      if (hasNum) continue;
      nullRows += 1;
      const row = tbl.rows.filter((tr) => text(tr).indexOf(a.name) >= 0)[0];
      if (!row) { nullBad.push(`${r.fixture}/${r.selected.id}/${a.name}: 找不到账号行`); continue; }
      const q = quotaCellOf(tbl, row.k.filter((c) => c.t === "td"));
      if (q.err) { nullBad.push(`${r.fixture}/${r.selected.id}/${a.name}: ${q.err}`); continue; }
      const got = cut(visibleText(q.cell), 60);
      if (got.indexOf("已耗尽") >= 0) {
        nullBad.push(`${r.fixture}/${r.selected.id}/${a.name}: 上游只给了桶、一个可用数都没给（remaining 全 null）却渲染「${got}」——「没给数字」≠「数字是 0」（§4-3 任一桶 None ⇒ 整号 None，禁止当 0）`);
      }
      if (/\b0\s*(Token|积分)\b/.test(got)) {
        nullBad.push(`${r.fixture}/${r.selected.id}/${a.name}: 无量化余量却印「0 余量」形态：${got}`);
      }
    }
  }
  if (nullRows < 1) nullBad.push("没有 `remaining:null` 且无量化余量的判别样本（V14b 失去对象 = 死判据）");
  check("V14b", "⑭b 上游没给可用数（items 全 remaining:null）的行不得渲染「已耗尽」，也不得印成 0 余量",
    nullBad.length === 0,
    () => nullBad.length ? [...new Set(nullBad)].slice(0, 3).join(" | ") : `核对 ${nullRows} 行（全部只出「未知」档）`);

  /* ---------- V15 · 「重置于 X」+ 附属标注**五档**映射（方案 §4-5/§4-6 + §8.2 X-R5-9） ----------
   * ① 正形：`active` 且 `expires_at` 为 ISO 形状 ⇒ 必出 `重置于 MM-DD HH:mm`（谓词收紧 = X-R5-5）；
   * ② 反向：出现的「重置于」必须形如 `MM-DD HH:mm` —— 摘掉页面 ISO 护栏时上游秒级 epoch 会被
   *    `shortTime(...).slice(5)` 切成 6 位残串印出来，V17 的 `\b\d{10}\b` 看不见（QA 实测的绕过），
   *    真正把这一格抓住的就是这里的正形；
   * ③ 附属标注五档映射：`reason → 注记文案`（`no_identity` 与 `no_credentials` 同文案、
   *    两行都要在；摘掉映射时这两行必须**同时红**，否则映射表是假的）。 */
  const v15Bad = [];
  let resetRows = 0;
  const noteSeen = {};
  for (const r of runs) {
    const tbl = tableInfo(r.pageNodes);
    if (!tbl.has || tbl.quotaIndex < 0) continue;
    for (const a of r.selected.accounts) {
      const rq = a.runtime && a.runtime.quota;
      if (!rq) continue;
      const row = tbl.rows.filter((tr) => text(tr).indexOf(a.name) >= 0)[0];
      if (!row) continue;
      const q = quotaCellOf(tbl, row.k.filter((c) => c.t === "td"));
      if (q.err || !q.cell) continue;
      const got = cut(visibleText(q.cell), 90);
      const items = Array.isArray(rq.items) ? rq.items.filter((it) => it && it.name) : [];
      // 🔴 no_plan 行**没有数值面**（正确文案就是「无套餐」，裁决③），所以不要求「重置于」；
      //    它仍然要过"出现即合形"（②）与标注映射（③）。
      const act = rq.reason === "no_plan" ? [] : items.filter((it) => it.active !== false);
      const hasISO = act.some((it) => isISOShape(it.expires_at));
      const hasReset = got.indexOf("重置于") >= 0;
      if (items.length && hasISO) {
        resetRows += 1;
        if (!/重置于 \d{2}-\d{2} \d{2}:\d{2}/.test(got)) {
          v15Bad.push(`${r.fixture}/${r.selected.id}/${a.name}: 有 active 且 ISO 形状的到期时刻，却没有「重置于 MM-DD HH:mm」：「${got}」（§4-5 定义 = 有效包里最早的那个）`);
        }
      }
      if (hasReset && !/重置于 \d{2}-\d{2} \d{2}:\d{2}/.test(got)) {
        v15Bad.push(`${r.fixture}/${r.selected.id}/${a.name}: 出现了不合形的「重置于」（应为 MM-DD HH:mm）：「${got}」—— 页面 ISO 护栏被摘时上游 epoch 会残切成 6 位数字`);
      }
      // ③ 附属标注映射：五档**各自**要求（同文案两档由同一注记串自然覆盖）
      const want = QUOTA_NOTE_MAP[rq.reason];
      if (want) {
        noteSeen[rq.reason] = (noteSeen[rq.reason] || 0) + 1;
        if (got.indexOf(want) < 0) {
          v15Bad.push(`${r.fixture}/${r.selected.id}/${a.name}: reason=${rq.reason} 应带附属标注「${want}」，实得「${got}」（§4-7：标注是附属不是档，摘了映射这一档就没人知道上游这轮没说话）`);
        }
      }
    }
  }
  const missNote = Object.keys(QUOTA_NOTE_MAP).filter((k) => !noteSeen[k]);
  if (missNote.length) v15Bad.push(`附属标注五档缺判别样本：${missNote.join(",")}（fixture 每档各一行，` 
    + "且 no_credentials 与 no_identity 同文案 ⇒ 两行都要在）");
  if (resetRows < 2) v15Bad.push(`「重置于」正形样本只剩 ${resetRows} 行（至少 2 行，否则本条对新契约恒真）`);
  check("V15", "⑮ 「重置于 MM-DD HH:mm」正形 + 出现即合形 + 附属标注五档映射（冷却中/熔断状态不可读/读取失败/未发起×2）",
    v15Bad.length === 0,
    () => v15Bad.length ? `${v15Bad.length} 处：${[...new Set(v15Bad)].slice(0, 3).join(" | ")}`
      : `重置于核对 ${resetRows} 行；标注覆盖 ${Object.keys(noteSeen).length}/5 档（同文案两档 ${noteSeen.no_credentials || 0}+${noteSeen.no_identity || 0} 行）`);

  /* ---------- V17 · 额度格**用户可见面**零裸 epoch（方案 §8.2 ④ = QA X-R5-5 重排后的定稿） ----------
   * 分工写死：钩子 epoch→ISO 归一的真相由 **pytest** 钉（§8.1-3 的撤证，静态门够不着 `upstream/*.py`）；
   * 页面有**防御护栏**（`ISO_RE` 谓词，§4-5），V17 只钉这一层：额度格里不得出现 10 位秒级整数。
   * 🔴 扫描面 = **整格可见文本 + 本格 tooltip**，比方案原文的 `cellTextExcept(cell,"qchk")` **更宽**：
   *   只剥 `.qchk` 就放过了「查于」那一格 —— 而 §4-6 定的是 `查于 = data_at || checked_at`（**上游值优先**），
   *   钩子漏归一的 `data_at` 会原样印在那里（交付要求的反向自证实验 (c) 实测：把 ix-quota-net 的
   *   `data_at` 换成 `1790956800` ⇒ 本条红）。数值面（V10' 的总额一致性）仍按原口径剥 `.qchk`，
   *   两处不混用：**判据只会比方案更严，不会更松**。
   * tooltip 也在扫描面内：`失效于` 那一支就在 title 里，只扫 visibleText 会让本条**没有任何可红路径**
   *   （= 死判据；X-R5-5 说的"epoch 被切片成 6 位残串"由 V15 的「出现即合形」补抓）。
   * `ix-epoch` 常驻 fixture：正确实现下必须**绿**（页面整段不出「重置于」，tooltip 也不印）。 */
  const epochBad = [];
  let epochScanned = 0;
  for (const r of runs) {
    const tbl = tableInfo(r.pageNodes);
    if (!tbl.has || tbl.quotaIndex < 0) continue;
    for (const a of r.selected.accounts) {
      const rq = a.runtime && a.runtime.quota;
      if (!rq) continue;
      const row = tbl.rows.filter((tr) => text(tr).indexOf(a.name) >= 0)[0];
      if (!row) continue;
      const q = quotaCellOf(tbl, row.k.filter((c) => c.t === "td"));
      if (q.err || !q.cell) continue;
      epochScanned += 1;
      const numFace = cellTextExcept(q.cell, "qchk");     // 数值面（剥掉「查于 …」）
      const visFace = visibleText(q.cell);                // 整格可见文本（含「查于」）
      const tipFace = tipOf(q.cell);                      // 本格 tooltip
      const hay = `${visFace} | ${tipFace}`;
      const hit = EPOCH_RE.exec(hay);
      if (hit) {
        const where = EPOCH_RE.test(numFace) ? "数值面"
          : (EPOCH_RE.test(visFace) ? "查于/文案面" : "tooltip");
        epochBad.push(`${r.fixture}/${r.selected.id}/${a.name}: 额度格用户可见面（${where}）出现裸 epoch「${hit[0]}」（上游秒级整数没归一 / 页面 ISO 护栏被摘）：${cut(hay, 70)}`);
      }
    }
  }
  const epochSamples = runs.reduce((s, r2) => s + r2.selected.accounts.filter(
    (a) => a.runtime && a.runtime.quota && Array.isArray(a.runtime.quota.items)
      && a.runtime.quota.items.some((it) => it && /^\d{10}$/.test(String(it.expires_at))),
  ).length, 0);
  if (epochSamples < 1) epochBad.push("fixture 没有 `expires_at` 为裸 epoch 的行（ix-epoch 常驻样本被删 ⇒ V17 失去对象）");
  check("V17", "⑰ 额度格**用户可见面**零裸 10 位 epoch（整格文本含「查于」那一格 + 本格 tooltip）；护栏在页面，钩子归一由 pytest 钉",
    epochBad.length === 0,
    () => epochBad.length ? `${epochBad.length} 处：${[...new Set(epochBad)].slice(0, 3).join(" | ")}`
      : `扫描 ${epochScanned} 行额度格可见面 + tooltip 零命中（含 ${epochSamples} 行 ix-epoch 常驻样本被护栏兜住）`);

  /* ---------- V8 · §3 措辞禁用表（设计书 §8-⑧） ---------- */
  const hits = [];
  for (const r of runs) {
    for (const n of [...r.pageNodes, ...r.wizardNodes]) {
      if (n.t === "style" || n.t === "script") continue;
      for (const w of BANNED) {
        if ((n.x || "").indexOf(w) >= 0) hits.push(`${r.fixture}/${r.selected.id} 可见文本含「${w}」：${cut(n.x, 40)} @ ${pathOf(n)}`);
        for (const k in n.a) {
          if (k === "style") continue;
          if (String(n.a[k]).indexOf(w) >= 0) hits.push(`${r.fixture}/${r.selected.id} 属性 ${k} 含「${w}」：${cut(n.a[k], 40)} @ ${pathOf(n)}`);
        }
      }
    }
  }
  // 源码字符串字面量扫描（注释剥干净后）：覆盖「渲染不到但用户一点就看见」的文案（如向导各段）
  for (const lit of stringLiterals(pageSrc)) {
    for (const w of BANNED) {
      if (lit.indexOf(w) >= 0) hits.push(`源码字符串字面量含禁用词「${w}」：${cut(lit, 40)}`);
    }
  }
  check("V8", "⑧ 可见文本与属性零命中禁用词「正常」「在服务」「健康」「在线」「已取消」（§3 措辞禁用表）",
    hits.length === 0, () => hits.length ? `${hits.length} 处：${[...new Set(hits)].slice(0, 2).join(" | ")}` : `扫描 ${runs.length} 轮 DOM + 源码字面量零命中`);

  /* ---------- V19 · 额度失败轮的"跨行说明只说一次"（2026-10-02 用户指令） ----------
   * 用户实拍那一屏的病根：把"本轮没查成、下面显示的是上一轮"这句**跨行说明**塞进了
   * 每一行的额度格 ⇒ 十行账号糊出十段失败文案。定版 = 面板顶部一条 alert 说一次，
   * 行内只留定位注记「（读取失败/冷却中/未发起）」。正反两向都要有判据：
   *   ① 有 SILENT 轮的轮 ⇒ 恰一条横幅且计数与数据同源；
   *   ② 没有任何 SILENT 轮的轮 ⇒ 一条都不许出（不误报"没查成"）；
   *   ③ 任何情况下，额度格里都不许出现那句跨行说明。 */
  const STALE_REASONS = ["circuit", "circuit-untrusted", "unreachable", "no_credentials", "no_identity"];
  // 与页面 `QUOTA_SILENT` / 后端 `query_balance.SILENT` 同一份名单（三处同尺，缺一处就漏判）
  const STALE_SENTENCE = "下面这些行显示的是";
  const staleBad = [];
  let staleRounds = 0, cleanRounds = 0;
  for (const r of runs) {
    const accs = r.selected.accounts || [];
    const silent = accs.filter((a) => {
      const q = a.runtime && a.runtime.quota;
      return q && STALE_REASONS.includes(q.reason);
    });
    const panelAlerts = sel(r.pageNodes, "#ac-panel .alert")
      .filter((n) => text(n).indexOf("本轮额度没有取到新数据") >= 0);
    const cells = sel(r.pageNodes, "#ac-panel td.num")
      .filter((n) => text(n).indexOf(STALE_SENTENCE) >= 0);
    if (cells.length) staleBad.push(`${r.fixture}/${r.selected.id}: ${cells.length} 个额度格里重复了跨行说明`);
    if (silent.length) {
      staleRounds += 1;
      if (panelAlerts.length !== 1) {
        staleBad.push(`${r.fixture}/${r.selected.id}: 有 ${silent.length} 个 SILENT 账号却出了 ${panelAlerts.length} 条横幅（必须恰一条）`);
      } else if (text(panelAlerts[0]).indexOf(`${silent.length} 个账号`) < 0) {
        staleBad.push(`${r.fixture}/${r.selected.id}: 横幅计数与数据不符（期望含「${silent.length} 个账号」，实得「${cut(text(panelAlerts[0]), 60)}」`);
      }
    } else {
      cleanRounds += 1;
      if (panelAlerts.length) staleBad.push(`${r.fixture}/${r.selected.id}: 本轮没有任何 SILENT 账号，横幅却出现了（误报"没查成"）`);
    }
  }
  check("V19", "⑲ 额度失败轮：面板顶部恰一条横幅（计数与数据同源），行内不重复跨行说明；无失败轮不误报",
    staleBad.length === 0 && staleRounds >= 1 && cleanRounds >= 1,
    () => staleBad.length ? `${staleBad.length} 处：${[...new Set(staleBad)].slice(0, 2).join(" | ")}`
      : `有 SILENT 轮 ${staleRounds} / 无 SILENT 轮 ${cleanRounds}（两向都有样本）`);

  /* ---------- L · 反转的 M6-IX 真机断言（e2e-records/m6-accounts-assertions.json） ----------
   * 设计书 §8-2：A6 / A8 / A10 正是本版要删的结构 → **逐条反转**（不是删除）。 */
  const railWithFamilyWord = [...new Set(pageNodes().filter((s) => s.t === "aside" || has(s, "subnav"))
    .filter((s) => visibleText(s).indexOf("族") >= 0).map((s) => cut(visibleText(s), 44)))];
  const famRuns = perRun.filter((x) => x.gc).length;
  check("L-A6", "反转 M6-IX A6「产品族分组卡 = 8」→ 现在必须 = 0，且 rail 文本不再出现「族」这个臆造轴",
    famRuns === 0 && railWithFamilyWord.length === 0,
    `分组卡：${famRuns}/${runs.length} 轮仍有（原断言 = 8，本版必须 0）；rail 文本含「族」${railWithFamilyWord.length} 处${railWithFamilyWord.length ? `（如「${railWithFamilyWord[0]}」）` : ""}`);

  const titleBad = [];
  let titleRows = 0;
  for (const r of runs) {
    /* 2026-10-01 重定锚（卡头新增「模型映射」钮起）：本判据的对象是 **rail 行**。
       卡头操作钮按任务契约也带 `data-pid`（标注所作用产品，`#ac-map`），其 title 是操作
       说明 —— 旧选择器 `.anchor-item, .mode-btn, [data-pid]` 会把面板控件一并卷进来，
       与「rail 行 title 逐字核对」的判据语义不符（那条注释一直写着"面板里也带 data-pid
       的控件另有其位"，实现却从未排除）。收窄到子侧栏作用域；rail 行仍是逐行核对。 */
    for (const row of sel(r.pageNodes, ".subnav .anchor-item, .subnav .mode-btn")) {
      const pid = row.a["data-pid"];
      const want = pid && r.titleExpected[pid];
      if (!want) continue;                       // 不是 rail 行（面板里也带 data-pid 的控件另有其位）
      titleRows += 1;
      const got = cut(row.a.title || "", 140);
      if (got !== want) titleBad.push(`${r.fixture}/${pid}：title「${got}」≠「${want}」`);
    }
  }
  /* 🔴 收窄选择器后必须证明它**真的核到了行**（核对行数 = 各轮在册产品数之和）：
     选择器写错成空集时 titleBad 恒空 = 死判据 —— 正是本门 doctrine 反复点名的那种假通过。 */
  const titleWant = runs.reduce((s, r) => s + r.productCount, 0);
  check("L-A8", "反转 M6-IX A8「行 title = 账号数(启用数) + 登录方式」→ 现在必须恰为「产品名 · N 个账号（M 已启用）」",
    titleBad.length === 0 && titleRows === titleWant,
    () => titleBad.length ? [...new Set(titleBad)].slice(0, 3).join(" | ")
      : `核对 ${titleRows}/${titleWant} 行 rail title 逐字相符`);

  const detailBad = [];
  for (const r of runs) {
    const needles = DETAIL_ONLY.concat(r.baseHost ? [r.baseHost] : []);
    for (const n of r.pageNodes) {
      if (n.t === "style" || n.t === "script") continue;
      const hay = [n.x || "", ...Object.entries(n.a).filter(([k]) => k !== "style").map(([, v]) => String(v))];
      for (const w of needles) {
        if (!w) continue;
        if (hay.some((h) => h.indexOf(w) >= 0)) {
          detailBad.push(`${r.fixture}/${r.selected.id}：常驻面出现「${w}」@ ${pathOf(n)}`);
        }
      }
    }
  }
  // 2026-10-01 用户指示废除展开详情行：实现词汇不再「降级到 .req-detail」而是**整页不出现**
  // （续期/模型目录并入模型映射弹窗；协议/设备身份/base_url 等只在后端视图可查）。
  if (pageSrc.indexOf("req-detail") >= 0 || pageSrc.indexOf("data-exp") >= 0) {
    detailBad.push("页面源码残留 req-detail / data-exp（展开行结构必须整体移除，不许只藏起来）");
  }
  check("L-A10", "反转 M6-IX A10：展开详情行已废除——协议/设备身份/目录来源/base_url 在页面上零出现，源码无 req-detail/data-exp 残留",
    detailBad.length === 0, () => detailBad.length ? [...new Set(detailBad)].slice(0, 3).join(" | ") : "常驻面零命中（协议/设备身份/目录来源/base_url），展开行结构已整体移除");

  /* ---------- W1 · M7-C1 扫码型（`login === "qr"`）的渲染契约 ----------
   * 钉两个缺陷本体（都在 raccoon / loomy 上实测存在过）：
   *   ① `qr_payload` 是一条**光秃秃的 URL 字符串**：本页没有二维码编码器，于是界面只能把它
   *      印成一行文字、提示用户"用手机扫一扫这行字"——扫不出任何东西；
   *   ② `<img src>` 直接指向上游**图片地址**（loomy 的 `open.weixin.qq.com/connect/qrcode/…`）：
   *      那张图必须由网关带着铸出 uuid 的 UA + Referer 才取到，浏览器跨域带不上 → 一张坏图。
   * 现在的契约（`accounts/types.py::Challenge`、`accounts/qr.py`）：图片以
   * `data:image…` data URI 进 `qr_payload` → 恰有一个 `<img>` 且它的 src 是 data URI；
   * 文字载荷（`url`）仍并排可见（这台设备扫不了时的兜底），且不带任何远程 `<img>`。 */
  const qrRuns = runs.filter((r) => r.selected.login === "qr");
  const wBad = [];
  if (qrRuns.length < 2) {
    wBad.push(`fixture 里 qr 型产品只剩 ${qrRuns.length} 轮（raccoon / loomy 至少各 1 轮，`
      + "否则本判据没有对象 = 死判据）");
  }
  for (const r of qrRuns) {
    const stub = loginStart(r.selected, "qr").challenge;
    const nodes = r.challengeNodes;
    const imgs = sel(nodes, "img");
    const local = imgs.filter((n) => String(n.a.src || "").startsWith("data:image"));
    const remote = imgs.filter((n) => /^(https?:|\/\/)/.test(String(n.a.src || "")));
    if (local.length !== 1) {
      wBad.push(`${r.fixture}/${r.selected.id}：<img src="data:image…">=${local.length}（必须恰 1；`
        + `img 总数=${imgs.length}）——qr_payload 不是图片 data URI 时界面就只能印文字`);
    }
    if (remote.length) {
      wBad.push(`${r.fixture}/${r.selected.id}：${remote.length} 个 <img> 的 src 是**远程地址**`
        + `（浏览器跨域取不到上游那张图）：${cut(remote[0].a.src, 56)}`);
    }
    const hay = [];
    for (const n of nodes) {
      hay.push(String(n.x || ""));
      for (const k in n.a) if (k !== "src") hay.push(String(n.a[k]));
    }
    if (hay.every((h) => h.indexOf(stub.url) < 0)) {
      wBad.push(`${r.fixture}/${r.selected.id}：文字载荷（Challenge.url）没出现在二维码视图里`
        + "——「这台设备扫不了」时用户没有可复制的东西");
    }
    // 图片 data URI 被当文字印出来（几百字符的 base64 糊在界面上）也算缺陷
    const printed = nodes.filter((n) => String(n.x || "").indexOf(stub.qr_payload) >= 0);
    if (printed.length) {
      wBad.push(`${r.fixture}/${r.selected.id}：图片 data URI 被当成**文字**印在页面上 @ ${pathOf(printed[0])}`);
    }
    const noAria = sel(nodes, ".icon-btn").filter((b) => !(b.a["aria-label"] || "").trim()
      && !visibleText(b).trim());
    if (noAria.length) {
      wBad.push(`${r.fixture}/${r.selected.id}：${noAria.length} 颗纯图标钮没有 aria-label`
        + "（frontend-spec 可访问性表：只有 SVG、无可见文字的钮必须有 aria-label）@ "
        + pathOf(noAria[0]));
    }
  }
  check("W1", "⑨ 扫码型出图：`qr_payload` 是图片 → 恰有一个 `<img src=\"data:image…\">`；零远程 `<img>`；文字载荷仍可见；图标钮带 aria-label",
    wBad.length === 0,
    () => wBad.length ? `${wBad.length} 处：${[...new Set(wBad)].slice(0, 3).join(" | ")}`
      : `qr 型 ${qrRuns.length} 轮都画出了 data URI 图 + 文字兜底`);

  return { checks, errors, runs };
}

/** 给 L-A8 用：每轮的「rail 行 title 期望值」查表 + 当前产品的 base_url 主机名。 */
function decorateRuns(runs) {
  for (const r of runs) {
    const map = {};
    for (const p of (r.allProducts || [])) {
      const on = p.accounts.filter((a) => a.enabled).length;
      map[p.id] = `${p.title} · ${p.accounts.length} 个账号（${on} 已启用）`;
    }
    r.titleExpected = map;
    const m = /^https?:\/\/([^/]+)/.exec(r.selected.base_url || "");
    r.baseHost = m ? m[1] : "";
  }
  return runs;
}

/* ---------- 源码字符串字面量抽取（剥注释；模板里的 ${…} 递归回代码态，避免嵌套模板误判） ---------- */
function stringLiterals(src) {
  const out = [];
  let i = 0;
  const n = src.length;
  const braceDepth = [];   // 模板字面量嵌套：`${}` 里是代码态，遇到新的模板要下钻
  while (i < n) {
    const c = src[i];
    const c2 = src[i + 1];
    if (c === "/" && c2 === "/") { while (i < n && src[i] !== "\n") i += 1; continue; }
    if (c === "/" && c2 === "*") { i += 2; while (i < n && !(src[i] === "*" && src[i + 1] === "/")) i += 1; i += 2; continue; }
    if (c === '"' || c === "'") {
      const q = c;
      let s = "";
      i += 1;
      while (i < n && src[i] !== q) { if (src[i] === "\\") { s += src[i] + (src[i + 1] || ""); i += 2; continue; } s += src[i]; i += 1; }
      i += 1;
      out.push(s);
      continue;
    }
    if (c === "`") {
      let s = "";
      i += 1;
      while (i < n && src[i] !== "`") {
        if (src[i] === "\\") { s += src[i] + (src[i + 1] || ""); i += 2; continue; }
        if (src[i] === "$" && src[i + 1] === "{") {          // 内插：把已accumulated 的模板切片入库，代码态继续扫
          out.push(s);
          s = "";
          i += 2;
          braceDepth.push(1);
          while (i < n && braceDepth.length) {
            if (src[i] === "{") braceDepth[braceDepth.length - 1] += 1;
            else if (src[i] === "}") {
              braceDepth[braceDepth.length - 1] -= 1;
              if (braceDepth[braceDepth.length - 1] === 0) { braceDepth.pop(); i += 1; break; }
            }
            i += 1;
          }
          continue;
        }
        s += src[i];
        i += 1;
      }
      out.push(s);
      i += 1;
      continue;
    }
    i += 1;
  }
  return out.filter(Boolean);
}

/* ==================== 变异自证 ==================== */

const L = (...lines) => lines.join("\n");

/** 让当前页面达到设计书形态的最小编辑（/tmp 副本，**绝不写工作区**）。 */
const FLAT_RAIL_FIX = [
  { from: L('      <div class="group-card" style="margin-bottom:12px">'),
    to: L('      <div class="rail-flat" style="margin-bottom:12px">') },
  { from: L('        <button class="mode-btn ${pid === selected ? "active" : ""}" data-pid="${esc(pid)}"'),
    to: L('        <button class="anchor-item ${pid === selected ? "active" : ""}" data-pid="${esc(pid)}"') },
];
const ENTRY_FIX = [
  // 2026-09-30 修订：入口定版在**卡头**（`#ac-add`），故 fix = 把"别处复辟的那一颗"拿掉
  { from: L('      <button class="btn btn-sm" id="ac-add-dup">${PLUS}接入账号</button>'),
    to: "" },
];
const ICON_FIX = [
  // V9 的"可绿"证明：把"全用 buddy 图标"改回"每产品自己的图标"
  { from: L('            <span class="mark-sm"><img src="/img/products/buddy.png" alt="?"></span>'),
    to: L('            <span class="mark-sm">${productMark(p)}</span>') },
];
const TABLE_FIX = [  { from: L('        <th>账号</th><th>状态</th>',
            '        ${devFields.length ? "<th>设备</th>" : ""}',
            '        ${quotaCol ? `<th class="num">额度</th>` : ""}',
            '        <th>最近结果</th><th class="num">操作</th>'),
    to: L('        <th class="exp"></th><th>账号</th><th>状态</th>',
          '        <th class="num">额度</th><th class="num">操作</th>') },
  { from: L('    <tr data-acc="${esc(a.name)}">', '      <td class="strong ${a.enabled ? "" : "off"}">'),
    to: L('    <tr data-acc="${esc(a.name)}">', '      <td class="exp"></td>',
          '      <td class="strong ${a.enabled ? "" : "off"}">') },
  { from: L('      ${opt.devFields.length ? `<td>${dev}</td>` : ""}',
            '      ${opt.quotaCol ? `<td class="num">${quotaCell(a)}</td>` : ""}',
            '      <td>${r',
            '        ? `<span class="badge ${r.badge}" title="${esc(r.detail || "")}">${esc(r.label)}</span>`',
            '        : `<span style="color:var(--text-faint)">—</span>`}</td>'),
    to: L('      <td class="num">${quotaCell(a)}</td>') },
];
/** 🔴 2026-10-02 五档改版：`QUOTA_OLD`/`QUOTA_NEW`/`QUOTA_FIX` 整组**退役删除**（不是删判据）。
 *  原因 = 方案 §8.2 前置批③（工程 B-R5-5）：`fix` 只在**该判据基线为红**时才执行，而页面已经是
 *  五档形态 ⇒ V4'/V7' 的基线必须为绿，"把未实现页修成设计形态"这件事已经没有可锚的对象
 *  （旧 `quotaCell` 字面量在现页 0 命中，一走到就 `hits=0` 抛错 = 用锚点过期冒充结论）。
 *  ⇒ 这两条判据改走 `expectGreen`（红 = 真缺陷，报可读消息、不施加变异、不计入可红分母，
 *     漏跑变异由 `rows < denom` + `bad.length` 双重保证退出码 1，不会假绿）。
 *  `TABLE_FIX` 仍被本轮**没动**的 V6 引着（同属休眠债，按"其余过期组不顺手大改"保留）。 */
const WORDS_FIX = [
  { from: '（本机端口打不开属正常，整串粘贴到此处）', to: '（本机回跳接收端未落地，整串粘贴到此处）' },
];

/** 每条判据一个最小回归变异（施加在 fix 之后的副本上）；kills = 该变异**必须新钉住**的判据
 *  （只声明本条变异真正会让它变红的那些；fix 阶段本来就红的写进声明是 vacuous，实测由
 *   runMutations 逐条核对，声明失真/锚点过期一律 BAD——不许靠声明蒙混）。 */
const MUTATIONS = [
  { id: "V1", fix: FLAT_RAIL_FIX, kills: ["V1"],
    why: "把 .group-card 塞回 rail（设计书 §8-3 成对撤证①：族容器复活）",
    // 重定锚（实施轮 §2 结构定稿：rail 行直接挂进 .subnav-scroll，族容器 .group-card 已删）：
    // 锚点从旧页的 `<div class="group-card" style="margin-bottom:12px">` 改到新版 rail 容器那一行，
    // **语义与变异后果不变**（换成 .group-card 即 V1 变红，实测见 --mutation 表）。
    from: L('        <div class="subnav-scroll" role="tablist"'),
    to: L('        <div class="group-card" role="tablist"') },
  { id: "V2", fix: FLAT_RAIL_FIX, kills: ["V2", "V9"],   // V9 连带变红：rail 少行 → 该产品图标缺失，如实声明
    why: "rail 只显示有账号的产品（0 账号产品的接入入口从选择轴上消失，§1.3 默认不筛）",
    // 重定锚：同一条语句，实施轮去掉了「族 map」的一层嵌套 → 缩进少 2 空格（变异后果不变）。
    from: L('  const items = f.ids.map((pid) => {'),
    to: L('  const items = f.ids.filter((id) => byId.get(id).accounts.length).map((pid) => {') },
  { id: "V3", fix: ENTRY_FIX, kills: ["V3"],
    why: "卡头之外再复辟一颗「接入账号」钮（v1 的原始缺陷：入口不在所作用产品的框里）",
    // 重定锚（2026-10-01 改版：卡头说明行 metaLineHTML 已删）——落点改在面板体首行之前，
    // 仍在 `.card-head` 之外，专打"他处接入钮"那条分支
    from: L('      ${p.accounts.length ? tableHTML(p) : emptyHTML(p)}'),
    to: L('      <button class="btn btn-sm" id="ac-add-dup">${PLUS}接入账号</button>',
          '      ${p.accounts.length ? tableHTML(p) : emptyHTML(p)}') },
  { id: "V4", fix: [], expectGreen: true, kills: ["V4", "V7", "V10", "V14", "V15"],
    // 实测注记（2026-10-02 五档改写后重跑）：本条把 quotaCell 的数据源换回网关池摘要，
    // 于是「无 items 的行」丢掉快照档位词（V4'/V7' 同红）、「有 items 的行」丢掉数字/徽章/重置于
    // （V10'/V14/V15 连带红）—— kills 按实测声明，不虚报也不漏报。
    why: "quotaCell 改回只读 a.quota（BUG-1 本体：额度列接到网关池摘要，运行态快照再也不看）",
    from: L('  const rq = a.runtime && a.runtime.quota;'),
    to: L('  const rq = a.quota && a.quota.state !== "unknown" ? {',
          '    state: a.quota.state, checked_at: "", } : null;') },
  { id: "V5", fix: [], kills: ["V5"],
    why: "开关里塞一颗 .dot（用圆点承担开关，frontend-spec.md:524 的禁令本体）",
    from: L('  el.setAttribute("role", "switch");'),
    to: L('  el.setAttribute("role", "switch");',
          '  { const d = document.createElement("span"); d.className = "dot"; el.appendChild(d); }') },
  { id: "V6", fix: TABLE_FIX, kills: ["V6", "V4", "V7", "V10", "V14", "V14b", "V15"],
    why: "表头「额度」改名「配额」（§3 是逐字列集，改名即判红；连带：额度列按表头定位，列名一改所有读额度格的判据同时失去对象 = 如实声明，不写成单点）",
    from: L('        <th class="num">额度</th><th class="num">操作</th>'),
    to: L('        <th class="num">配额</th><th class="num">操作</th>') },
  { id: "V7", fix: [], expectGreen: true, kills: ["V7"],
    why: "第四态「尚未刷新」被折进「未知」（把 BUG-2「网关还没查过」藏成「查了但拿不到」，§3 明令区分）",
    // 重定锚（2026-10-02 五档改版：「尚未刷新」那行的 title 文案扩了字，锚跟着走；变异后果不变）
    from: L('    return `<span style="color:var(--text-faint)" title="运行态里没有额度快照：网关还没查过这个账号（BUG-2 的可见态）">尚未刷新</span>`;'),
    to: L('    return `<span style="color:var(--text-faint)">未知</span>`;') },
  { id: "V8", fix: WORDS_FIX, kills: ["V8"],
    why: "空态文案塞进禁用词「正常」（评审 B-2「正常」是第三个谎：status 不含任何凭据有效性事实）",
    // 重定锚（2026-10-01 改版：开关后的状态文字已删）——V8 的词表扫描覆盖 DOM + 源码字面量，
    // 改打空态标题那行；变异后果不变（可见文本 + 源码字面量两处都会红）。
    from: L('        <div style="font-size:13px;font-weight:700;color:var(--text-soft)">还没有账号</div>'),
    to: L('        <div style="font-size:13px;font-weight:700;color:var(--text-soft)">运行正常</div>') },
  { id: "V9", fix: ICON_FIX, kills: ["V9"],
    why: "10 个产品全用同一个图标（张冠李戴；V9 存在的意义就是钉「各自用各自产品的 icon」）",
    from: L('            <span class="mark-sm">${productMark(p)}</span>'),
    to: L('            <span class="mark-sm"><img src="/img/products/buddy.png" alt="?"></span>') },
      { id: "V19", fix: [], expectGreen: true, kills: ["V19"],
    why: "摘掉面板顶部的额度失败横幅（回到「每行各说一遍」或「干脆不说」的旧形态）",
    from: L('  const n = Object.values(bits).reduce((x, y) => x + y, 0);',
          '  if (!n) return "";'),
    to: L('  const n = 0;   // 撤证：横幅永不出现') },
{ id: "V10", fix: [], expectGreen: true, kills: ["V10"],
    why: "摘掉本格内的就地展开明细（2026-10-02 用户指令的反面：明细又只剩悬停可见）",
    from: L('  out.push(packsDetailHTML(a, rq, items));'),
    to: L('  // 撤证：逐包明细不再就地展开（回到只住 tooltip 的旧形态）') },
{ id: "V10", fix: [], expectGreen: true, kills: ["V10", "V15"],
    why: "结构化套餐余粮被静默丢弃（quotaCell 忽略 items，退回「有余量」档——Q30 调研出的「查到了但不展示」缺陷本体）",
    from: L('  const items = (Array.isArray(rq.items) ? rq.items : []).filter((it) => it && it.name);'),
    to: L('  const items = [];') },
  { id: "V11", fix: [], kills: ["V11"],
    why: "行内续期钮被摘掉（能力位 refresh=True 的产品失去账号维度续期入口 = 2026-10-01 裁决的功能缺失）",
    from: L('    out.push(textOp("refresh", `续期 ${a.name}`, "续期：刷新凭据并落盘（与启用位正交，停用账号也可续期；与额度无关）", "续期"));'),
    to: L('    // 撤证：续期钮被摘') },
  { id: "V12", fix: [], kills: ["V12"],
    why: "账号级续期动作被塞回「模型映射」弹窗（用户裁决：续期属账号维度 → 只在列表行内，弹窗零动作）",
    from: L('      ${p.accounts.length ? tableHTML(p) : emptyHTML(p)}'),
    to: L('      <button class="btn btn-sm" data-mop="refresh">续期</button>',
          '      ${p.accounts.length ? tableHTML(p) : emptyHTML(p)}') },

  /* ==================== 2026-10-02 五档改版新增 ====================
   * 🔴 锚点纪律（方案 §8.2「变异锚纪律」/ QA X-R5-4 第 4 条）：每条 `from` 都取**整行 + 前一行**
   *    （`applyEdit` 是 `src.split(from).length-1` 的子串计数，2 空格前缀会同时命中 4 空格行），
   *    并且都**与本轮页面实现同批定稿** —— 对当时页面的 `hits=1` 实测数见交付报告
   *    （`docs/changes/e2e-records/gate-static-20261002.md`，逐条 grep 原始输出）。
   *    `fix: [] + expectGreen: true` = 页面已实现该契约 ⇒ 基线必须为绿；红了就是真缺陷，
   *    门报可读消息并跳过变异（`rows < denom` + `bad` 双保险 ⇒ 退出码必为 1，不可能假绿）。 */
  { id: "V13", fix: [], expectGreen: true, kills: ["V13"],
    why: "行内第 3 颗「刷新额度」被摘（指令 2「每个产品都要有账号维度刷新」的功能缺失 + 能力位同相判据失去对象）",
    from: L('  if (c.balance) {',
          '    out.push(textOp("quota", `刷新额度 ${a.name}`,',
          '      "刷新额度：只读上游额度，不改凭据、不消耗签到配额（zcode 走联网腿；其余产品同款钩子）", "刷新额度"));',
          '  }'),
    to: L('  if (false) {',
          '    // 撤证：行内「刷新额度」钮被摘',
          '  }') },
  { id: "V13", fix: [], expectGreen: true, kills: ["V13"],
    why: "卡头产品级「刷新额度」被摘（指令 2 的第二条腿 = 产品维度；行内还在、卡头没了 ⇒ 同相判据必红）",
    from: L('          ${c.balance ? `<button class="btn btn-sm" id="ac-quota"',
          '            title="刷新额度：对该产品全部账号只读查一次上游额度（含停用账号；结果就地回执）">${REFRESH}刷新额度</button>` : ""}'),
    to: L('          ${c.balance ? "" : ""}') },
  { id: "V14", fix: [], expectGreen: true, kills: ["V14", "V7", "V4"],
    why: "摘掉 `reason===\"no_plan\"` 那一支（裁决③ 的前端映射根本没做 → 无套餐行落回「未知」/结构化数字，「无套餐」档在界面上消失）",
    // 🔴 反向自证①的同一编辑（`to` 只留注释）；`from` 含整支三行 ⇒ 逐字唯一命中
    from: L('  if (rq.reason === "no_plan") {',
          '    return `<span style="color:var(--text-faint)" title="${esc(rq.detail || "上游返回空套餐列表")}">无套餐${esc(note)}</span>`;',
          '  }'),
    to: L('  // 撤证：no_plan 支被摘（页面没有「无套餐」这一档）') },
  { id: "V14b", fix: [], expectGreen: true, kills: ["V14b"],
    why: "摘掉「上游一个可用数都没给」的护栏（= 把 remaining:null 当 0 累加并按 total<=0 判「已耗尽」，§4-3 明令禁止的谎：「没给数字」≠「数字是 0」）",
    from: L('  if (rq.plan) out.push(`<span class="badge b-gray" style="margin-bottom:4px" title="${esc("套餐：" + rq.plan)}">${esc(rq.plan)}</span>`);',
          '  if (!nums.length) {'),
    to: L('  if (rq.plan) out.push(`<span class="badge b-gray" style="margin-bottom:4px" title="${esc("套餐：" + rq.plan)}">${esc(rq.plan)}</span>`);',
          '  if (false) {') },
  { id: "V15", fix: [], expectGreen: true, kills: ["V15"],
    why: "「重置于 X」整段不渲染（§4-5 定义 = 有效包里最早的 expires_at，被摘后用户不知道额度什么时候恢复）",
    from: L('  const isoExp = active.map((it) => it.expires_at).filter((v) => ISO_RE.test(String(v || "")))',
          '    .sort()[0];',
          '  if (isoExp) buckets.push(`重置于 ${esc(shortTime(isoExp).slice(5))}`);'),
    to: L('  const isoExp = active.map((it) => it.expires_at).filter((v) => ISO_RE.test(String(v || "")))',
          '    .sort()[0];',
          '  if (false && isoExp) buckets.push(`重置于 ${esc(shortTime(isoExp).slice(5))}`);') },
  { id: "V15", fix: [], expectGreen: true, kills: ["V15"],
    why: "附属标注映射表里「未发起」那一档的两个 reason（no_credentials / no_identity）同时被摘 ⇒ **同文案两行必须同时红**，否则映射表是假的（方案 §8.2 X-R5-9）",
    from: L('  no_credentials: "（未发起）",',
          '  no_identity: "（未发起）",'),
    to: L('  no_credentials: "",',
          '  no_identity: "",') },
  { id: "V17", fix: [], expectGreen: true, kills: ["V17", "V15"],
    why: "摘掉页面的 ISO 形状护栏（§4-5 后半句「仅当匹配 ^\\d{4}-\\d{2}-\\d{2} 才渲染」，谓词恒真）⇒ 上游秒级 epoch 直接进用户可见面：tooltip 印 10 位裸 epoch（V17 红）、「重置于」被 slice(5) 切成 6 位残串（V15 的「出现即合形」红）",
    // 🔴 这就是 X-R5-5 说的那条绕过：`shortTime(1790956800).slice(5)` = "956800"，
    //    只扫 visibleText 的 V17 看不见 6 位残串 ⇒ 本条能红的通路是 **tooltip 里的 `失效于`**
    //    （V17 因此必须同时扫 `tipOf(cell)`，见判据段注释），残串那一半由 V15 的正形兜住。
    from: L('const ISO_RE = /^\\d{4}-\\d{2}-\\d{2}/;'),
    to: L('const ISO_RE = /./;') },
];

const applyEdit = (src, { from, to }, tag) => {
  const hits = src.split(from).length - 1;
  if (hits !== 1) {
    throw new Error(`${tag}：锚点在页面里命中 ${hits} 次（需恰好 1 次）。`
      + (String(tag).startsWith("fix")
        ? "fix 锚点过期多半是实施轮已改版 —— 请重定锚或删除该条 fix（判据已绿时不会走这条路）"
        : "变异锚点过期 = 最隐蔽的一种假通过：请把本条变异重定锚到新页面对应位置，**不许删条目**"));
  }
  return src.replace(from, to);
};

function runChild(pagePath) {
  const out = execFileSync(process.execPath,
    [join(ROOT, "bianyiandhuanjing", "scripts", "verify_accounts_ui.mjs"), "--json", "--page", pagePath],
    { encoding: "utf-8", maxBuffer: 64 * 1024 * 1024, timeout: 90_000, killSignal: "SIGKILL" });
  const parsed = JSON.parse(out.trim().split("\n").filter(Boolean).pop());
  return parsed;
}

async function runMutations() {
  const work = join(tmpdir(), `mgw-ac-ui-mut-${process.pid}-${Date.now()}`);
  mkdirSync(work, { recursive: true });
  const baseSrc = readFileSync(PAGE_FILE, "utf-8");
  const rows = [];
  const bad = [];
  let baseRun = null;
  try {
    baseRun = runChild(PAGE_FILE);
  } catch (e) {
    console.error("✗ 基线子进程跑不出读数，变异结论无效：", String(e.message).slice(0, 200));
    return 2;
  }
  const okOf = (run, id) => {
    const c = (run.checks || []).find((x) => x.id === id);
    return c ? { ok: !!c.ok, detail: c.detail || "" } : null;
  };
  /** 一次读数里的红集合（连带变红要相对**施加变异前的那一份副本**算，不是相对基线）。 */
  const redOf = (run) => new Set((run.checks || []).filter((c) => !c.ok).map((c) => c.id));
  const baseRed = [...redOf(baseRun)];
  /** 🔴 `expectGreen` 型条目（方案 §8.2 前置批① = 工程 B-R5-5 原文）：
   *  语义 = 「本判据在**已实现页面**上基线必须为绿；一旦为红就是真缺陷，不是可绿性核验的对象」。
   *  净效果只有一条：**禁止把真缺陷混进可绿性核验**（旧逻辑会去施加过期 fix，报"锚点过期"，
   *  把坏页面说成门的毛病）。它**不可能造成假绿** —— 跳过变异 ⇒ 该条既进 `bad` 又不计入 `rows`
   *  ⇒ `rows.length < denom` 且 `bad.length > 0`，退出码必为 1（这条安全边写在文件头）。 */
  const greenExpected = MUTATIONS.filter((m) => m.expectGreen).length;
  const skipped = [];
  console.log(`\n[变异自证] 真实页面基线：${(baseRun.checks || []).length} 项，红 ${baseRed.length} 项（${baseRed.join(",") || "无"}）`);
  console.log(`  基线为红的条目先做**可绿性核验**（最小 fix 编辑，/tmp 副本）；`);
  console.log("  expectGreen 型 " + greenExpected + " 条：基线红 = 真缺陷，记为不可核验并跳过变异（不施加过期 fix）。\n");

  for (const mut of MUTATIONS) {
    let src = baseSrc;
    let stage = "";
    try {
      const before = okOf(baseRun, mut.id);
      if (!before) throw new Error(`判据 ${mut.id} 在基线输出里不存在（判据没跑起来？）`);
      let prevRed = redOf(baseRun);
      if (!before.ok) {
        if (mut.expectGreen && mut.fix.length) {
          bad.push(`${mut.id} ← expectGreen 与 fix 同时声明（二者互斥：要么基线必须绿，要么走可绿性核验）`);
          console.log(`  ✗ ${mut.id} ← ${mut.why}  ← BAD：声明矛盾（expectGreen + fix 并存）`);
          continue;
        }
        if (mut.expectGreen) {
          skipped.push(mut.id);
          bad.push(`${mut.id} ← 基线必须为绿却是红（真缺陷，非可绿性核验对象）：${cut(before.detail, 120)}`);
          console.log(`  ✗ ${mut.id} ← ${mut.why}  ← BAD：基线红（expectGreen 型 = 真缺陷）：${cut(before.detail, 120)}`);
          continue;
        }
        if (!mut.fix.length) {
          bad.push(`${mut.id} ← 基线红且无 fix：可绿性与证伪都无从核验（补 fix 或与页面同批落地）`);
          console.log(`  ✗ ${mut.id} ← ${mut.why}  ← BAD：基线红且没有 fix 可走`);
          continue;
        }
        for (const f of mut.fix) src = applyEdit(src, f, `fix(${mut.id})`);
        const copy = join(work, `accounts-${mut.id}-fixed.js`);
        writeFileSync(copy, src);
        const fixed = runChild(copy);
        const fOk = okOf(fixed, mut.id);
        if (!fOk) throw new Error(`fix 后判据 ${mut.id} 读不到`);
        if (!fOk.ok) {
          throw new Error(`判据不可绿（死判据或 fix 编辑不足）：fix 后仍红 —— ${cut(fOk.detail, 120)}`);
        }
        prevRed = redOf(fixed);
        stage = `（基线红 → fix 转绿：${[...prevRed].join(",") || "全绿"} 仍红）`;
      }
      const mutated = applyEdit(src, mut, mut.id);
      const copy2 = join(work, `accounts-${mut.id}-mutated.js`);
      writeFileSync(copy2, mutated);
      const after = runChild(copy2);
      const aOk = okOf(after, mut.id);
      if (!aOk) throw new Error(`变异后判据 ${mut.id} 读不到`);
      if (!aOk.ok) {
        const nowRed = redOf(after);
        const slept = mut.kills.filter((x) => !nowRed.has(x));
        if (slept.length) throw new Error(`声明该变异必须一并钉住的判据纹丝不动：${slept.join(",")}（kills 表过期，要么改变异要么改声明）`);
        const extra = [...nowRed].filter((x) => !prevRed.has(x) && !mut.kills.includes(x));
        rows.push({ mut: mut.why, id: mut.id, stage, msg: aOk.detail, extra });
        console.log(`  ✓ ${mut.id} ← ${mut.why}${stage}`);
        console.log(`      红消息：${cut(aOk.detail, 200)}${extra.length ? `（另：未声明的连带变红 ${extra.join(",")}）` : ""}`);
      } else {
        bad.push(`${mut.id} ← 纹丝不动：施加「${mut.why}」后仍绿`);
        console.log(`  ✗ ${mut.id} ← ${mut.why}${stage}  ← 未红（判据对该变异不敏感）`);
      }
    } catch (e) {
      bad.push(`${mut.id} ← ${String(e.message).slice(0, 200)}`);
      console.log(`  ✗ ${mut.id} ← ${mut.why}  ← BAD：${String(e.message).slice(0, 200)}`);
    }
  }
  console.log("\n[变异自证表]");
  console.log("| 变异（施加在 /tmp 页面副本上） | 判据 | 变红消息 |");
  console.log("| --- | --- | --- |");
  for (const r of rows) {
    console.log(`| ${r.mut}${r.stage} | ${r.id} | ${cut(r.msg, 160).replace(/\|/g, "／")} |`);
  }
  const covered = new Set(MUTATIONS.map((m) => m.id));
  for (const c of (baseRun.checks || [])) if (!covered.has(c.id) && /^V/.test(c.id)) {
    bad.push(`判据 ${c.id} 没有任何对应变异（永远不会红 = 等于没有断言）`);
  }
  const denom = MUTATIONS.length - skipped.length;
  console.log("=".repeat(56));
  console.log(`可红 ${rows.length}/${denom}${bad.length ? `；${bad.length} 项 BAD` : `；${rows.length} 条判据全部可证伪`}`
    + `（expectGreen 型 ${greenExpected} 条已计入分母：基线为绿时照常证伪，为红则跳变异并记为不可核验，本次跳过 ${skipped.length} 条）`);
  bad.forEach((b) => console.log(`  ✗ ${b}`));
  try { rmSync(work, { recursive: true, force: true }); } catch { /* /tmp 副本清不掉不影响结论 */ }
  return (rows.length === denom && !bad.length) ? 0 : 1;
}

/* ==================== 入口 ==================== */

async function main() {
  if (argv.includes("--help")) {
    console.log("用法：node scripts/verify_accounts_ui.mjs [--json | --mutation] [--page <页面副本>]"
      + "（环境变量同效：MGW_AC_PAGE / MGW_AC_FIXDIR）");
    process.exit(0);
  }
  const unknown = argv.filter((a) => a.startsWith("--") && !["--json", "--mutation", "--help", "--page"].includes(a));
  if (unknown.length) {
    console.error(`✗ 未知参数 ${unknown.join(" ")}（--help 看用法）—— 拒绝把「参数写错」当成「跑过了」`);
    process.exit(2);
  }
  if (MUTATE) {
    process.exit(await runMutations());
  }
  // 单进程实测（基线与变异子进程都走这条路）：结构级错误 → 退出码 2
  let result;
  try {
    result = await runChecks();
  } catch (e) {
    console.error(`✗ 页面渲染不出来，门的结论无效：${e && e.name}: ${String(e && e.message).slice(0, 400)}`);
    console.error("  🔴 「渲染不出来」本身就是发现（假 DOM/vm 装配不上或被渲染入口抛错带走）——");
    console.error("     报缺陷、修门，绝不用编出来的树替页面作证。");
    process.exit(2);
  }
  const { checks, errors, runs } = result;

  if (JSON_ONLY) {
    console.log(JSON.stringify({
      checks: checks.map((c) => ({ id: c.id, ok: !!c.ok, detail: c.detail })),
      errors,
      runs: runs.length,
      threw: runs.flatMap((r) => r.errs),
    }));
    process.exit(0);
  }
  if (errors.length) {
    errors.forEach((e) => console.error(`✗ ${e}`));
    process.exit(2);
  }

  const SECTIONS = {
    R: "渲染现场可达性", V: "设计书 §8 结构判据 + 2026-10-02 额度五档判据（V4'/V7'/V10'/V13/V14/V14b/V15/V17）",
    L: "反转的 M6-IX 真机判据",
    W: "扫码型（qr）渲染契约（M7-C1）",
  };
  const failed = checks.filter((c) => !c.ok);
  let last = "";
  console.log(`\n页面：${PAGE_FILE.replace(ROOT + "/", "")}｜fixture：${FIXTURES.join(", ")}｜渲染轮次 ${runs.length}`);
  for (const c of checks) {
    const k = c.id[0];
    if (k !== last) { console.log(`\n[${SECTIONS[k] || k}]`); last = k; }
    console.log(`  ${c.ok ? "✓" : "✗"} ${c.id} ${c.desc}${c.detail ? "  ｜ " + cut(c.detail, 220) : ""}`);
  }
  console.log("\n" + "=".repeat(56));
  console.log(`合计：${checks.length - failed.length} 通过 / ${failed.length} 失败`);
  failed.forEach((c) => console.log(`  ✗ ${c.id} ${c.desc}｜${cut(c.detail, 220)}`));
  // TODO(M7-UI 实施轮接线，本任务不装)：
  //   tests/unit/test_m7_accounts_ui_gate.py::test_accounts_ui_gate
  //     → subprocess.run(["node", "scripts/verify_accounts_ui.mjs"], check=False) 断言 rc == 0
  //       （本机无 node 时 pytest.skip；与 scripts/verify_v2_frontend.mjs 的既有接法同款）
  process.exit(failed.length ? 1 : 0);
}

/* 直接被 `node` 调用才跑门；被 import（诊断/探针）时只导出定义，不劫持进程。 */
if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  await main();
}

export { FAKE_DOM, DRIVER, toModuleBody, renderRun, buildRuns, runChecks, stringLiterals,
  MUTATIONS, PAGE_FILE, loadFixtures, loginStart, sel, flatten, text, visibleText, tableInfo };
