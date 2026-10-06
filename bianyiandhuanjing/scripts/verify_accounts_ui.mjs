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
 *     缩写函数 `fmtQuotaNum` 来算期望串 —— 门内重写第二份 = 判据自证（两份实现一起错就永远绿）。
 *     实现姿势 = `DRIVER` 多收一份 probe（每号 `[Σactive remaining, unit]`，由 `buildRuns` 从
 *     fixture 算好送进 realm），realm 调页面函数算出缩写串回传 `qfmt`；页面若删掉那个函数，
 *     V10' 直接报「realm 取不到 fmtQuotaNum」而不是悄悄换算法。此项属**门改动**须入台账。
 */
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
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
  /* 🔴 V10'-④：额度总额的**缩写串**必须由**页面自己的** fmtQuotaNum 算（realm 内直调），
     门内不得重写第二份缩写算法（两份一起错就永远绿）。probe 是门外从 fixture 算好的
     [Σactive remaining, unit] 对，回传一一对齐的字符串数组；页面没有那个函数 → hasFmt=false，
     V10' 报"取不到页面缩写函数"而不是换算法。（本段在本门源码里，注释不得用反引号。） */
  let qfmt = null;
  let hasFmt = false;
  try {
    hasFmt = typeof fmtQuotaNum === "function";
    if (hasFmt) qfmt = (P.probes || []).map((x) => fmtQuotaNum(x.sum, x.unit));
  } catch (e) {
    errs.push("realm 调页面 fmtQuotaNum 抛错 " + (e && e.name) + ": " + String(e && e.message).slice(0, 160));
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
async function renderRun(pageSrc, extraParts, payloads) {
  const ctx = vm.createContext({});
  const program = [
    FAKE_DOM,
    toModuleBody(readFileSync(DEPS.api, "utf-8")),
    toModuleBody(readFileSync(DEPS.components, "utf-8")),
    toModuleBody(pageSrc),
    // D-1/D-4 拆分（2026-10-06）：accounts/ 子模块按「主文件 → 子模块」追加——
    // toModuleBody 已剥 import/export ⇒ 同一 realm 顺序执行（子模块引用的主文件
    // 顶层符号在拼接序里已就位）。
    ...extraParts.map((f) => toModuleBody(readFileSync(f, "utf-8"))),
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
 *  · 缩写串**不在门内算**：由 realm 调页面 `fmtQuotaNum` 回传（`r.qfmt`），见 V10'-④。 */
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

async function buildRuns(fixtures, pageSrc, extraParts) {
  const fullSrc = pageSrc + extraParts.map((f) => readFileSync(f, "utf-8")).join("\n");
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
      const out = await renderRun(pageSrc, extraParts, {
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
  // 子模块目录（accounts.js 拆分后）：pages/accounts/ 下全部 .js，state.js 排最前
  //（拼装序与文本判据序都依赖它）。
  const pagePartsDir = PAGE_FILE.replace(/[^/\\]+$/, "") + "accounts/";
  const extraParts = existsSync(pagePartsDir)
    ? readdirSync(pagePartsDir).filter((f) => f.endsWith(".js") && pagePartsDir + f !== PAGE_FILE)
        .sort((a, b) => (a === "state.js" ? -1 : b === "state.js" ? 1 : a.localeCompare(b)))
        .map((f) => pagePartsDir + f)
    : [];
  // 🔴 文本级判据的源码 = 主文件 + 全部子模块拼接（拆分后函数体分散在多文件，
  //    判据找的是「函数体形状」不是「文件位置」——跟实现走，不许删判据）。
  const pageSrcAll = pageSrc + extraParts.map((f) => readFileSync(f, "utf-8")).join("\n");
  const fixtures = loadFixtures(errors);
  if (errors.length) return { checks, errors, runs: [] };
  const runs = decorateRuns(await buildRuns(fixtures, pageSrc, extraParts));
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

  /* ---------- V6 · 表头逐字（2026-10-01 改版：展开列已废，4 列固定列集） ----------
   * 🔴 2026-10-03 用户指示「状态列和额度列交换下位置」⇒ 列序前进为 账号/额度/状态/操作。
   *    这是**随设计推进**（列集仍是这四列、逐字仍钉），不是放宽判据。 */
  const HEAD_EXACT = ["账号", "额度", "状态", "操作"];
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
  check("V6", "⑥ 表头逐字 = 账号 / 额度 / 状态 / 操作（4 列，无展开指示列；2026-10-03 额度与状态交换），且无「参与运营」「最近结果」列",
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
      const tipX = tipOf(q.cell);
      const expiredN = items.filter((it) => it && it.active === false).length;
      const problems = [];
      /* 🔴 2026-10-03 用户实拍重做（「乱对齐一些乱七八糟信息放不下还弄个展开折叠」+ 点名照
         zcode-switch / ZCode-Panel / Jet Hub 做）⇒ 本判据**随设计前进**：
         旧契约正向钉的四样（「查于」/ 套餐徽章 / 「展开 N 个包」/ `.qpacks-detail`）
         现在全部改成**反向判据**（出现即红 = 不许退回旧版），并补上新的三行结构判据。
         理由写在这里而不是删掉了事：下一轮看见"为什么禁徽章"不用再猜。 */
      const collect = (n, c, acc) => {
        const out = acc || [];
        if (n && has(n, c)) out.push(n);
        for (const k of (n && n.k) || []) collect(k, c, out);
        return out;
      };
      if (!collect(q.cell, "qrow").length) problems.push("额度格缺主行 .qrow（结构：主行含逐组明细 / 占比条 / meta 行）");
      // 🔴 `.qnum` 只钉在**上游给了可量化余量**的行上：`remaining` 全为 null 的行本来就没有数字，
      //    要求它出 `.qnum` 等于逼页面编一个数（V13 禁的正是这种谎）——那一行的必需面是「用量未知」。
      const gaveNum = items.filter((it) => it && it.active !== false)
        .some((it) => typeof it.remaining === "number");
      if (gaveNum && !collect(q.cell, "qnum").length) {
        problems.push("给了可量化余量的行缺数值位 .qnum（剩余/总量，分子=剩余）");
      }
      if (!gaveNum && !/(用量未知|未知)/.test(got)) {
        problems.push("上游一个可用数都没给的行必须写「用量未知」（不得凭空出数字，V13 同一把尺）");
      }
      if (collect(q.cell, "badge").length) problems.push("额度格内不得再放套餐徽章（同产品同值、零决策价值；2026-10-03 用户指令删）");
      if (collect(q.cell, "qpacks-detail").length || collect(q.cell, "data-qpacks").length
          || (q.cell.a && q.cell.a["data-qpacks"])) {
        problems.push("额度格内不得有折叠明细块（三家参考实现都没有折叠；2026-10-03 用户指令删）");
      }
      if (/(展开|收起)/.test(got)) problems.push(`额度格可见面不得再出现「展开/收起」文案：「${cut(got, 48)}」`);
      if (got.indexOf("查于") >= 0) problems.push("「查于 + 绝对时刻」已换成相对新鲜度（绝对时刻只进悬停），出现即回退旧版");
      if (got.indexOf("重置于") >= 0) problems.push("「重置于」措辞已随 2026-10-03 改版作废（到期改由 meta 行「至 MM-DD HH:mm」承担）");
      const metaN = collect(q.cell, "qmeta");
      if (!metaN.length) problems.push("缺 meta 行（最早到期 · 相对新鲜度 · 失效计数）");
      else if (!/(刚刚|\d+ 分钟前|\d+ 小时前|\d+ 天前|\d{2}-\d{2} \d{2}:\d{2})/.test(text(metaN[0]))) {
        problems.push(`meta 行没有新鲜度表述（应为 刚刚/N 分钟前/N 小时前/N 天前 或退回的绝对短时刻）：「${cut(text(metaN[0]), 40)}」`);
      }
      const unit0 = String((items[0] && items[0].unit) || "");
      if (unit0 && !/(亿|万|Token|积分|\d)/i.test(`${got} ${tipX}`)) problems.push("缺量纲（亿/万/Token/积分，可见或 tooltip）");
      // ③ 只钉"给了量化余量却合计 0"的行；一个都没给的行归 V14b 管
      const hasNum = items.some((it) => typeof it.remaining === "number");
      const actX = items.filter((it) => it && it.active !== false);
      const sumAct = actX.reduce((s, it) => s + (typeof it.remaining === "number" ? it.remaining : 0), 0);
      const sumTotX = actX.reduce((s, it) => s + (typeof it.total === "number" ? it.total : 0), 0);
      // 占比条：有分母**必画**且宽度 = 剩余/总量；无分母**不得画**（条 = 占比声明，没分母就没资格声明）
      const barI = collect(q.cell, "qbar").map((b) => collect(b, "qbar-fill")[0] || (b.k || [])[0])[0];
      if (hasNum && sumTotX > 0 && !barI) {
        problems.push("有总量分母却没画占比条（.qbar > i）——用户要靠这条读还剩几成");
      } else if (!(hasNum && sumTotX > 0) && barI) {
        problems.push("上游未给总量却画了占比条 = 编造占比（V13 同一把尺：没给数字 ≠ 数字是 0）");
      }
      if (barI && barI.a && /width:\s*([\d.]+)%/.test(String(barI.a.style || "")) && sumTotX > 0) {
        const w = parseFloat(String(barI.a.style).match(/width:\s*([\d.]+)%/)[1]);
        const want = Math.max(0, Math.min(100, sumAct / sumTotX * 100));
        if (Math.abs(w - want) > 0.6) problems.push(`占比条宽度 ${w}% 与 Σ剩余/Σ总量 = ${want.toFixed(1)}% 不符`);
      }
      // 同名聚合后组数 ≤3 ⇒ 明细行必须逐组给量；>3 才允许 `+N 类`（不许虚报也不许静默吞组）
      const gNames = [...new Set(actX.map((it) => String(it.name || "未命名包")))];
      const chipN = collect(q.cell, "qchip");
      if (gNames.length > 1 && !chipN.length) problems.push(`聚合后 ${gNames.length} 组却没有逐组明细行（多组必须逐组给量）`);
      if (chipN.length) {
        const plus = chipN.filter((c) => /\+\d+ 类/.test(text(c)));
        if (gNames.length > 3 && plus.length !== 1) problems.push(`组数 ${gNames.length} > 3 却缺唯一「+N 类」收尾`);
        if (gNames.length <= 3 && plus.length) problems.push(`组数只有 ${gNames.length} 却出现「+N 类」= 虚报还有没给的组`);
        if (chipN.length - plus.length > 3) problems.push("明细行超过 3 组（ZCode-Panel 的 chip 上限就是 3 + N）");
      }
      // 🔴 2026-10-03 用户裁定「合计：900 积分」= **数值贴在标签后面**，不再右浮到列尾。
      //    判据三腿：① 主行标签以「：」收尾（语法是"标签：数值"，不是"左标签…右浮数"）；
      //    ② `.qnum` 直接住在 `.qrow` 里（旧版包了一层右浮的 `.qval` 壳 ⇒ 出现即红）；
      //    ③ 主行里既有标签也有数值（缺一半就是没做）。
      const row0 = collect(q.cell, "qrow")[0];
      const nm = row0 ? collect(row0, "qname")[0] : null;
      const numIn = row0 ? collect(row0, "qnum")[0] : null;
      if (row0 && collect(row0, "qval").length) problems.push("主行又出现右浮的 .qval 壳（用户裁定：数值贴标签）");
      if (nm && !/[：:]$/.test(text(nm).trim())) problems.push(`主行标签没有以「：」收尾：「${text(nm).slice(0, 24)}」`);
      if (nm && !numIn) problems.push("主行里标签与数值不同排（缺 .qnum）");
      if (hasNum && sumAct <= 0) {
        if (!/(已耗尽|无套餐|用量未知)/.test(got)) {
          problems.push("Σ余量=0 的行必须显式出「已耗尽」/「无套餐」/「用量未知」（不得只印 0）");
        } else if (unit0 && !/\d[\s,]*(亿|万|Token|积分|\/token)/i.test(`${got} ${tipX}`)) {
          // 🔴 本意是「Σ=0 的行不许把量纲弄丢」（评审 N-3），不是「量纲必须紧贴在档位词后面」。
          //    原写法 `(已耗尽|无套餐)\s*(Token|积分)` 把两件事混成一件，于是页面只能渲染成
          //    「已耗尽 Token」——状态词后面直接接单位，用户读作"已耗尽 个 Token？"（实盘 15:39 看着就别扭）。
          //    现行页面把**数值与量纲放在一起**（`0 积分` / `0 / 1亿`）、档位词紧随其后。
          //    ⚠️ 2026-10-03 两处自纠：① 上一版重做时我把量纲 alternatives 写成了**可选组**
          //       （`(亿|万|Token|积分)?`），于是"只要格子里有任何数字就绿"= 本条被我自己写空；
          //       现改回必含量纲词。② 旧注释要求"剥掉 `.qpacks-detail` 再判"——折叠块已随
          //       本轮改版删除，判据面就是整格可见文本 + 悬停，不再需要剥离。
          problems.push("Σ余量=0 的行量纲标注不得消失（常驻面须有『数字+量纲』，可见或 tooltip，评审 N-3）");
        }
      } else if (hasNum && sumAct > 0) {
        // ②④ 期望串来自 realm 里的页面函数，门内不重算缩写
        const want10 = r.qfmt[`${r.selected.id}/${a.name}`];
        if (!r.hasFmt) {
          problems.push("realm 取不到页面缩写函数 fmtQuotaNum（V10'-④：判据不得在门内重写第二份算法）");
        } else if (want10 === undefined) {
          problems.push(`realm 没回传本号的缩写串（probe 缺键 ${r.selected.id}/${a.name}）`);
        } else if (!tokenRe(want10).test(got)) {
          problems.push(`剩余与 Σactive remaining 不符：期望「${want10}」，实得「${cut(got, 48)}」（禁 300⊂1300 子串侥幸）`);
        }
      }
      if (expiredN > 0 && got.indexOf("已失效") < 0) problems.push(`有 ${expiredN} 个失效包却无「已失效」注记`);
      /* 2026-10-02 那条「明细必须住在 .qpacks-detail 里并全量列出」的判据**整段作废**：
         2026-10-03 用户否掉了折叠本身（三家参考都没有折叠），改由**同名聚合**保证全量可见
         ——同名裂变包合成一组、每组一行，聚合后组数天然 ≤3，所以既没有"只住 tooltip"
         也没有"截断到 12 行"这两个病。反向判据见上面（出现折叠块 / 「展开」文案即红）。 */
      if (problems.length) structBad.push(`${r.fixture}/${r.selected.id}/${a.name}: ${problems.join("；")}`);
    }
  }
  if (structRows < 5) {
    structBad.push(`结构化判别样本只剩 ${structRows} 行（V10' 没有对象 = 死判据；正常应 ≥5：buddy-main + 5 条 ix-* 结构化行）`);
  }
  check("V10", "⑩' 额度格结构（2026-10-03 三次改判收口）：主行 =「标签：数值」**同排左对齐**（多组时标签恒为「合计：」，数值永不右浮/永不裁字）+ 占比条自占一行 + 逐组明细行（≤3 + N 类）+ meta 行（至 MM-DD HH:mm · 相对新鲜度 · 失效计数）；剩余=Σactive（页面缩写函数算）、有分母必画条无分母必不画；反向钉零徽章零折叠**零右浮 .qval 壳**",
    structBad.length === 0 && structRows > 0,
    () => structBad.length ? `${structBad.length} 处：${[...new Set(structBad)].slice(0, 3).join(" | ")}` : `结构化展示核对 ${structRows} 行（剩余一致性用 realm fmtQuotaNum；反向判据：徽章/折叠/查于/重置于 出现即红）`);

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
  if (pageSrcAll.indexOf("mapAccountsHTML") >= 0) {
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
      /* 🔴 2026-10-03 随额度格重做前进：主行现在是 `剩余 / 总量`（如 `0 / 1亿`），
         旧正则 `\b0\s*(Token|积分)\b` 只认「0 Token」这一种形态 ⇒ 摘掉护栏的坏实现照样绿
         （变异自证实测到这条**纹丝不动**）。改成两条：正确档位词必须在 + 任何「0 接量纲或分母」都算撒谎。 */
      if (!/(用量未知|未知)/.test(got)) {
        nullBad.push(`${r.fixture}/${r.selected.id}/${a.name}: 上游一个可用数都没给，可见面却没有「用量未知」档：「${got}」（护栏被摘 = 把"没给数字"渲染成数字）`);
      }
      if (/\b0\s*(Token|积分|\/\s*[\d.]+[亿万]?)/.test(got)) {
        nullBad.push(`${r.fixture}/${r.selected.id}/${a.name}: 无量化余量却印「0 余量」形态（含 0 / 总量 这种写法）：${got}`);
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
  let freshBad = 0;
  let freshRel = 0;
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
      /* 🔴 自纠（2026-10-03）：本条原先拿 `cut(..., 90)` 的**截断串**当判据面，
         于是三行结构的 buddy 行被切成「… 至 10-1」——到期时刻正好被尾巴削掉，判据假红。
         判据跑整格全文，**消息里**才用截断串（不然输出会刷屏）。 */
      const gotAll = visibleText(q.cell);
      const got = cut(gotAll, 90);
      const items = Array.isArray(rq.items) ? rq.items.filter((it) => it && it.name) : [];
      // 🔴 no_plan 行**没有数值面**（正确文案就是「无套餐」，裁决③），所以不要求「重置于」；
      //    它仍然要过"出现即合形"（②）与标注映射（③）。
      const act = rq.reason === "no_plan" ? [] : items.filter((it) => it.active !== false);
      const hasISO = act.some((it) => isISOShape(it.expires_at));
      /* 🔴 2026-10-03 措辞随设计前进：「重置于 X」改成 meta 行的「至 MM-DD HH:mm」
         （同一个量 = 有效包里最早的到期时刻，两家参考都写成"有效期至 …"）。
         两条硬约束一字不改：**正形必合 `MM-DD HH:mm`**（ISO 护栏被摘时上游秒级 epoch
         会被残切成 6 位数字）+ **新鲜度必须是相对量**。 */
      /* 🔴 自纠（2026-10-03 变异自证抓到）：上一版把 `hasReset` 直接定义成"合形的到期段"，
         于是"出现即合形"这条反向判据**永远不可能红**（出现但不合形 ⇒ hasReset=false ⇒ 不进检查），
         摘掉 ISO 护栏的坏实现（`至 956800`）就这么漏了。"出现"按段面判，"合形"另判一次。 */
      const hasReset = /(^|\s)至 /.test(gotAll);
      if (items.length && hasISO) {
        resetRows += 1;
        if (!hasReset) {
          v15Bad.push(`${r.fixture}/${r.selected.id}/${a.name}: 有 active 且 ISO 形状的到期时刻，却没有 meta 行的「至 MM-DD HH:mm」：「${got}」（§4-5 定义 = 有效包里最早的那个）`);
        }
      }
      if (hasReset && !/(^|\s)至 \d{2}-\d{2} \d{2}:\d{2}/.test(gotAll)) {
        v15Bad.push(`${r.fixture}/${r.selected.id}/${a.name}: 出现了不合形的到期时刻（应为 至 MM-DD HH:mm）：「${got}」—— 页面 ISO 护栏被摘时上游 epoch 会残切成 6 位数字`);
      }
      if (gotAll.indexOf("重置于") >= 0) v15Bad.push(`${r.fixture}/${r.selected.id}/${a.name}: 旧措辞「重置于」又回来了（2026-10-03 已并入 meta 行「至 …」）`);
      // 新鲜度段必须存在（`… 查`），且**相对形态**要有足够样本量——
      // 🔴 不许在门里复刻页面的 7 天阈值（那等于第二份实现，两份一起错就永远绿）：
      //    本条只钉"有 查 段"+"整轮里至少 2 行是相对量（刚刚/N 分钟前/N 小时前/N 天前）"，
      //    页面若把新鲜度整个退回绝对时刻（旧版那种「查于 2026-10-03 08:35」），样本数归零即红。
      // 🔴 `no_plan` 行**不要求**新鲜度段：档位本身就是这一轮的结论（旧契约同样不给「查于」），
      //    而 fixture 里 `ix-noplan-items` 是"reason=no_plan 但 items 非空"的形状，
      //    对它提"必须有 …查"等于要求页面在一个空档位行里再塞一行元数据。
      if (items.length && rq.reason !== "no_plan" && !/\S查/.test(gotAll)) {
        freshBad += 1;
        v15Bad.push(`${r.fixture}/${r.selected.id}/${a.name}: meta 行没有新鲜度段（应形如「… 分钟前查」）：「${cut(gotAll, 60)}」`);
      }
      if (items.length && rq.reason !== "no_plan" && /(刚刚|\d+ 分钟前|\d+ 小时前|\d+ 天前)查/.test(gotAll)) freshRel += 1;
      // ③ 附属标注映射：五档**各自**要求（同文案两档由同一注记串自然覆盖）
      const want = QUOTA_NOTE_MAP[rq.reason];
      if (want) {
        noteSeen[rq.reason] = (noteSeen[rq.reason] || 0) + 1;
        if (gotAll.indexOf(want) < 0) {
          v15Bad.push(`${r.fixture}/${r.selected.id}/${a.name}: reason=${rq.reason} 应带附属标注「${want}」，实得「${got}」（§4-7：标注是附属不是档，摘了映射这一档就没人知道上游这轮没说话）`);
        }
      }
    }
  }
  const missNote = Object.keys(QUOTA_NOTE_MAP).filter((k) => !noteSeen[k]);
  if (missNote.length) v15Bad.push(`附属标注五档缺判别样本：${missNote.join(",")}（fixture 每档各一行，` 
    + "且 no_credentials 与 no_identity 同文案 ⇒ 两行都要在）");
  if (resetRows < 2) v15Bad.push(`到期时刻正形样本只剩 ${resetRows} 行（至少 2 行，否则本条对新契约恒真）`);
  if (freshRel < 2) v15Bad.push(`相对新鲜度样本只剩 ${freshRel} 行（至少 2 行，否则"退回绝对时刻"这种旧版回退抓不到）`);
  check("V15", "⑮ meta 行「至 MM-DD HH:mm」正形 + 出现即合形（摘 ISO 护栏必出 6 位残串 ⇒ 红）+ 相对新鲜度必出 + 附属标注五档映射（冷却中/熔断状态不可读/读取失败/未发起×2）",
    v15Bad.length === 0,
    () => v15Bad.length ? `${v15Bad.length} 处：${[...new Set(v15Bad)].slice(0, 3).join(" | ")}`
      : `到期核对 ${resetRows} 行 · 相对新鲜度 ${freshRel} 行（缺段 ${freshBad}）；标注覆盖 ${Object.keys(noteSeen).length}/5 档（同文案两档 ${noteSeen.no_credentials || 0}+${noteSeen.no_identity || 0} 行）`);

  /* ---------- V17 · 额度格**用户可见面**零裸 epoch（方案 §8.2 ④ = QA X-R5-5 重排后的定稿） ----------
   * 分工写死：钩子 epoch→ISO 归一的真相由 **pytest** 钉（§8.1-3 的撤证，静态门够不着 `upstream/*.py`）；
   * 页面有**防御护栏**（`ISO_RE` 谓词，§4-5），V17 只钉这一层：额度格里不得出现 10 位秒级整数。
   * 🔴 扫描面 = **整格可见文本 + 本格 tooltip**，比方案原文的 `cellTextExcept(cell,"qchk")` **更宽**：
   *   只剥 `.qchk` 就放过了「查于」那一格 —— 而 §4-6 定的是 `查于 = data_at || checked_at`（**上游值优先**），
   *   钩子漏归一的 `data_at` 会原样印在那里（交付要求的反向自证实验 (c) 实测：把 ix-quota-net 的
   *   `data_at` 换成 `1790956800` ⇒ 本条红）。数值面（V10' 的总额一致性）仍按原口径剥 `.qchk`，
   *   两处不混用：**判据只会比方案更严，不会更松**。
   * tooltip 也在扫描面内。🔴 2026-10-03 起本条扫**两支**：10 位裸 epoch + 时刻位上的 4-8 位残串
   *   （逐包 `失效于` 那行随折叠一起删了 ⇒ 只剩残串这一种泄漏形态，只扫 10 位就成死判据）。
   *   "出现即合形"仍归 V15，两条不重叠：V15 管形状对不对，V17 管不许出现裸数字。
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
      /* 2026-10-03 额度格重做：「查于 …」那一行（`.qchk`）已换成 meta 行 `.qmeta`
         （到期 + 相对新鲜度 + 失效计数）⇒ 剥离对象跟着换，"数值面"的语义不变。 */
      const numFace = cellTextExcept(q.cell, "qmeta");    // 数值面（剥掉 meta 行）
      const visFace = visibleText(q.cell);                // 整格可见文本（含「查于」）
      const tipFace = tipOf(q.cell);                      // 本格 tooltip
      const hay = `${visFace} | ${tipFace}`;
      const hit = EPOCH_RE.exec(hay);
      if (hit) {
        const where = EPOCH_RE.test(numFace) ? "数值面"
          : (EPOCH_RE.test(visFace) ? "查于/文案面" : "tooltip");
        epochBad.push(`${r.fixture}/${r.selected.id}/${a.name}: 额度格用户可见面（${where}）出现裸 epoch「${hit[0]}」（上游秒级整数没归一 / 页面 ISO 护栏被摘）：${cut(hay, 70)}`);
      }
      /* 🔴 2026-10-03 随额度格重做补的第二支：逐包 `失效于` 那行没了 ⇒ 摘掉 ISO 护栏后
         泄漏形态从"10 位裸 epoch"变成"被 slice(5) 切出来的 4-8 位残串"（`至 56800`），
         只扫 10 位的本条**再没有可红路径**（变异自证实测到 V17 纹丝不动 = 死判据）。
         合形与否归 V15，本条只管"时刻的位置上不许出现裸数字"。
         误报核查：`至 10-05 00:00` 里 `至` 后是两位 + 连字符，不匹配 `\d{4,8}`；
         `2 天前查` 的「查」在词尾，后面没有数字。 */
      const TAIL_RE = /(?:至|查|失效于)\s*(\d{4,8})(?![\d:])/;
      const tail = TAIL_RE.exec(hay);
      if (tail) {
        epochBad.push(`${r.fixture}/${r.selected.id}/${a.name}: 时刻位上出现裸数字残串「${tail[0].trim()}」（ISO 护栏被摘 ⇒ 上游秒级 epoch 被 slice 切成几位数印给用户）：${cut(hay, 70)}`);
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
  for (const lit of stringLiterals(pageSrcAll)) {
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

  /* ---------- V20 · 网关模型下拉不区分「新建 / 现有」（2026-10-03 用户实拍） ----------
   * 「网关模型不用区分新建的还是之前的。输出的数据都是网关模型」⇒ `targetOptions` 的函数体里
   * ① 不得再出现「新建」二字（旧版给目录里尚未接入的名字加 `新建：` 前缀、并按现有/新建分两段）；
   * ② `label` 与 `value` 同源；③ 必须经过排序（名称族自然序 + 族内能力降序 ⇒ 没有 `.sort(` 就是回潮）。
   * 🔴 只截函数体：函数**上方**的注释允许写「新建」（那记的是这条裁决的来由，不是用户可见面）。 */
  const toFn = (() => {
    const i = pageSrcAll.indexOf("function targetOptions(");
    if (i < 0) return null;
    const j = pageSrcAll.indexOf("\n}", i);
    return j < 0 ? null : pageSrcAll.slice(i, j + 2);
  })();
  check("V20", "⑳ 网关模型下拉平铺一张清单：不出现「新建」前缀、label 与 value 同源、且经过排序",
    !!toFn && toFn.indexOf("新建") < 0 && /label:\s*n\b/.test(toFn) && toFn.indexOf(".sort(") >= 0,
    () => toFn === null ? "找不到 targetOptions（结构变了就要跟着改判据，不许删判据）"
      : `函数体 ${toFn.length} 字：含「新建」=${toFn.indexOf("新建") >= 0}｜label 与 value 同源=${/label:\s*n\b/.test(toFn)}｜有 .sort=${toFn.indexOf(".sort(") >= 0}`);


  /* V21（2026-10-03 用户「资源池里已经关联并开启进池的怎么没显示？」）：进池开关的**读取面**
   * 只许认后端那个位。后端对「既无产品位、也无条目」的行返回 `map_enabled = null`（未映射），
   * 旧写法 `!== false` 把 null 当"开着" ⇒ 弹窗里「开关绿 + 徽章未映射 + 下拉有自动建议的模型名」
   * 三个信号互相矛盾，用户据此以为已落库。定版 = `=== true`。
   * 🔴 这是源码级不变量（真机门 MS2f 量的是画出来的态，两条各管一头）。 */
  // 🔴 负向判据（"某个写法不许再出现"）**必须先剥注释**：解释性文字里出现被禁字符串是**好事**
  //    （说明为什么禁），拿原文扫就是自己造红（本门 2026-10-03/04 连着两次踩到）。
  //    局限：只剥 /* */ 与整行 //，不处理字符串里的 //（本门判据找的都是中文定字符串，够用）。
  const stripComments = (src) => src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
  const fnSlice = (start, end) => {
    const i = pageSrcAll.indexOf(start);
    if (i < 0) return null;
    const j = pageSrcAll.indexOf(end, i);
    return j < 0 ? null : pageSrcAll.slice(i, j + end.length);
  };
  /* 🔴 草稿制（2026-10-05 第四次裁定）之后这一条**判据不换、只换主人**：
     旧对象是 `mapOn.set(i, m.map_enabled === true)`（前端那份"落库后的真实态"），
     新对象是 `persistedEnabled(i)`（盘上真值），而"三态位只认 `=== true`、`null` 不是开着"
     这条律一字未改 —— 它管的是**读**，草稿制改的是**写**。
     新增一条腿：草稿缺省位（`p === null ? true : p`）必须也走 `persistedEnabled` 那一个出口，
     不许在别处再算一遍"没落库算开还是算关"（两处算 = 两套真相）。 */
  const persistedSlice = fnSlice("const persistedEnabled = (i) => {", "\n    };");
  const curOnSlice = fnSlice("const curEnabled = (i) => {", "\n    };");
  check("V21", "㉑ 进池位只认后端那个三态位：`=== true` 才算开（null 不得当成开）+ 草稿缺省只经这一个出口算",
    !!persistedSlice && /m\.map_enabled === true/.test(persistedSlice)
      && pageSrcAll.indexOf("map_enabled !== false") < 0
      && !!curOnSlice && /return p === null \? true : p;/.test(curOnSlice)
      && stripComments(pageSrcAll).indexOf("mapOn.get(i)") < 0,
    () => `persistedEnabled 体=${persistedSlice ? persistedSlice.length + " 字" : "找不到"}`
      + `｜curEnabled 体=${curOnSlice ? "有" : "找不到"}`
      + `｜残留「!== false」写法=${pageSrcAll.indexOf("map_enabled !== false") >= 0}`
      + `｜旧 mapOn 回潮=${stripComments(pageSrcAll).indexOf("mapOn.get(i)") >= 0}`);

  /* ---------- V22/V23 · 脚部三颗钮 +「AI智能匹配」这条腿（2026-10-05 第三、四次裁定） ----------
   * 需求演进（写在这里免得下轮又猜哪句作废）：
   *   Q34「初始化之后…变为保存按钮」→ 10-04 23:2x「编辑区由保存提交、取消必须真能取消」
   *   → 10-05 第二次「为什么要多保存这一步呢，好傻好蠢」⇒ **删掉那一步**、行内一改即落库
   *   → 10-05 第三次「不用首次自动初始化…增加『AI智能匹配』按钮，规定显示」⇒ 那颗钮**常驻一态**
   *   → 🔴 10-05 第四次（本轮）「调用AI分析结果直接回填到弹窗内，但不提交保存，仅在前端进行展示。
   *     右侧显示黑色 保存按钮，所有修改、设置 点击保存提交数据后才能入库存储」
   *     ⇒ **「保存」回来当唯一写入口**，而「AI智能匹配」仍是一颗独立的常驻钮。
   * 🔴 为什么这次不是把上两轮白做：第二次裁定杀掉的是**"人已经逐行做过动作、还要再确认一次"**；
   *   第四次杀掉的是**"机器给的答案不经人确认就进配置"**。两句合起来是一条更准的规则：
   *   **谁做的决定谁负责落库 —— 人做的动作当场生效，机器给的结果必须人看过才生效。**
   *   草稿制同时满足了两句：人改的（下拉/开关/采纳）都进草稿，但草稿**只有一份**、
   *   由「保存」一次提交，所以既没有"多一步确认已生效的东西"，也没有"AI 替我写了配置"。
   * V22 钉**形状**：footer 恰三颗钮、每颗只有一种语义（零 `hidden`、零 `initialized`、零 `okBtn`）；
   * V23 钉**实质**：AI 那条腿打 `auto-map`、**只回填不写盘**、范围 = 屏幕上还空着的行、在飞有可见态。
   * 🔴 两条都是源码级不变量；画出来的态由真机门 MS3/MS4/MS6 量（各管一头，不互相顶）。 */
  const aiSlice = fnSlice("const runAiMatch = async () => {", "\n    };");
  const saveSlice = fnSlice("const saveAll = async () => {", "\n    };");
  const footHtmlSlice = fnSlice('foot.innerHTML = `<button class="btn" data-map="cancel">',
                                'data-map="save" disabled>保存</button>`;');
  const wiringSlice = fnSlice('body.querySelectorAll("select[data-idx]").forEach',
                              "\n    syncFoot();");
  const bodySlice = fnSlice("function mapBodyHTML(", "\n}");
  check("V22", "㉒ 脚部恰三颗钮、**一钮只有一态**：取消 / AI智能匹配（常驻）/ 保存（primary，读脏态使能）"
     + " + 两态机器（`okBtn` / `hidden` / `initialized`）零回潮 + AI 钮使能只看有没有落点",
     !!footHtmlSlice && (footHtmlSlice.match(/<button /g) || []).length === 3
     && /const \[cancelBtn, aiBtn, saveBtn\] = \[\.\.\.foot\.querySelectorAll\("button"\)\];/.test(pageSrcAll)
     && /<button class="btn btn-primary" data-map="save" disabled>保存<\/button>/.test(pageSrcAll)
     && /<button class="btn" data-map="ai" disabled>AI智能匹配<\/button>/.test(pageSrcAll)
     && /aiBtn\.textContent = "AI智能匹配";/.test(pageSrcAll)
     && stripComments(pageSrcAll).indexOf("okBtn") < 0
     && !/Btn\.hidden/.test(stripComments(pageSrcAll))   // 三颗钮任何一颗长显隐都红（不认旧变量名）
     && stripComments(pageSrcAll).indexOf("initialized") < 0
     && /aiBtn\.disabled = !\(catalog && \(catalog\.accounts \|\| \[\]\)\.length\)/.test(pageSrcAll)
     // 「保存」的使能读的是**脏态数**，不是文案、不是"有没有点过 AI"
     && /saveBtn\.disabled = n === 0 \|\| saving;/.test(pageSrcAll)
     && !!aiSlice && !!saveSlice,
     () => `脚部钮数=${!!footHtmlSlice ? (footHtmlSlice.match(/<button /g) || []).length : -1}`
       + `｜三颗引用=${/const \[cancelBtn, aiBtn, saveBtn\]/.test(pageSrcAll)}`
       + `｜primary=保存=${/<button class="btn btn-primary" data-map="save" disabled>保存/.test(pageSrcAll)}`
       + `｜AI 文案固定=${/aiBtn\.textContent = "AI智能匹配";/.test(pageSrcAll)}`
       + `｜okBtn 回潮=${stripComments(pageSrcAll).indexOf("okBtn") >= 0}`
       + `｜任一钮长显隐=${/Btn\.hidden/.test(stripComments(pageSrcAll))}`
       + `｜initialized 回潮=${stripComments(pageSrcAll).indexOf("initialized") >= 0}`
       + `｜AI 看落点=${/aiBtn\.disabled = !\(catalog && \(catalog\.accounts/.test(pageSrcAll)}`
       + `｜保存看脏态=${/saveBtn\.disabled = n === 0 \|\| saving;/.test(pageSrcAll)}`
       + `｜runAiMatch 体=${aiSlice ? aiSlice.length + " 字" : "找不到"}`
       + `｜saveAll 体=${saveSlice ? saveSlice.length + " 字" : "找不到"}`);

  check("V23", "㉓ 「AI智能匹配」= 打 auto-map 且**只回填、零写盘**：这条腿体内一次 mappings/remove 都不许有"
     + " + 分析范围 = 屏幕上还空着的行（`models: empty` 由 `!curTarget(i)` 算）"
     + " + 后端要是写了盘界面当场指出（`r.written !== false`）+ 回填后把「还没入库」说在明面上"
     + " + 常驻消耗声明坐在表上方并写明「不写入配置」",
     !!aiSlice
     && aiSlice.indexOf('POST("/admin/api/accounts/auto-map", { product: p.id, models: empty })') >= 0
     && aiSlice.indexOf("accounts/mappings") < 0
     && aiSlice.indexOf("product-models/remove") < 0
     && /\.filter\(\(\{ i \}\) => !curTarget\(i\)\)/.test(aiSlice)
     && aiSlice.indexOf("r.written !== false") >= 0
     && /还没入库，点「保存」才写入配置/.test(aiSlice)
     && /r\.kept/.test(aiSlice)
     && (aiSlice.match(/setMode\(\);/g) || []).length >= 1
     && /aiBusy = true;/.test(aiSlice) && /aiBusy = false;/.test(aiSlice)
     && !!bodySlice && /真实出站一次，会消耗/.test(bodySlice)
     && /不写入配置/.test(bodySlice)
     && /当前显示为「暂不设置」的/.test(bodySlice)
     && stripComments(bodySlice).indexOf("view.firstTime") < 0
     && bodySlice.indexOf("initNote") < bodySlice.indexOf('<div id="ac-map-err">'),
     () => `auto-map=${!!aiSlice && aiSlice.indexOf("auto-map") >= 0}`
       + `｜AI 腿里的写调用=${!!aiSlice ? (aiSlice.match(/accounts\/mappings|product-models\/remove/g) || []).length : -1}`
       + `｜范围=屏幕空集=${/!curTarget\(i\)/.test(aiSlice || "")}`
       + `｜written 自查=${!!aiSlice && aiSlice.indexOf("r.written !== false") >= 0}`
       + `｜未入库上界面=${/还没入库，点「保存」才写入配置/.test(aiSlice || "")}`
       + `｜kept 上报=${!!aiSlice && /r\.kept/.test(aiSlice)}`
       + `｜消耗声明=${/真实出站一次，会消耗/.test(bodySlice || "")}`
       + `｜声明写明不写盘=${/不写入配置/.test(bodySlice || "")}`);

  /* ---------- V24 · 批量处理结果只走结果浮层（2026-10-03 用户裁定） ----------
   * 原话：「各类处理结果，不允许用这种形式固化显示。执行完毕，弹窗提示具体执行结果，
   * 3s 后自动消失，也可以手动关闭。参考设计规范进行设计」。
   * 这条**推翻我自己 2026-10-02 定版并写进 §7.11 的「异步批量回执落就地槽（重绘后仍可见）」**，
   * 所以判据是"反转 + 新增"，不是删条目：
   * ① 出口唯一 = `showBulkReceipt` → `toastCard`（三条批量腿：刷新额度 / 批量续期 / 批量签到都经它）；
   * ② 固化槽整族清零：`bulkReceipt` 模块级文本、`#ac-receipt` 槽、`renderBulkReceipt` 回填、
   *    `clearBulkReceipt` 清理、`.bulk-receipt` 样式 —— 留一件就是留一条回潮的路；
   * ③ 浮层契约：默认 **3000ms** 自动消失 + × 手动关闭（带 `aria-label`）+ 复用 `#toast-wrap` 载体；
   * ④ 术语解释**不许坐正文**：那段「未发起」/「未参与」定义必须走 `note:`（挂计数行悬停）——
   *    3 秒是读完"计数 + 逐号结果"的时间，不是读定义的时间。 */
  const compSrc = readFileSync(DEPS.components, "utf-8");
  const cssSrc = readFileSync(join(ROOT, "coding/model_gateway/web/static/css/base.css"), "utf-8");
  // 🔴 判"某个类还在不在"必须先剥注释：`.bulk-receipt` 已经删了，但**我写的注释里提到它**
  //    （"旧的 .bulk-receipt 整族删除"），拿原文扫就是自己造红（同一课在令牌判据里也踩过一次）。
  const cssPlain = cssSrc.replace(/\/\*[\s\S]*?\*\//g, "");
  // 🔴 负向判据（"某个写法不许再出现"）**必须先剥注释**：今天第三次踩——CSS 类名扫到我自己
  //    写的"旧的 .bulk-receipt 已删"，这次又扫到注释里引的旧代码 `reason || "已刷新"`。
  //    解释性文字里出现被禁字符串是**好事**（说明为什么禁），拿原文扫就是自己造红。
  //    局限：只剥 `/* */` 与整行 `//`，不处理字符串里的 `//`（本判据只找一个中文串，够用）。
  const receiptBodies = {
    quota: fnSlice("async function batchQuota(btn, p) {", "\n}"),
    renew: fnSlice("function showRenewResult(r) {", "\n}"),
    claim: fnSlice("function showClaimAllResult(r) {", "\n}"),
  };
  const leftovers = ["bulkReceipt =", "renderBulkReceipt", "clearBulkReceipt",
                     "bulkReceiptHTML", "ac-receipt", "bulk-receipt"]
    .filter((k) => pageSrcAll.indexOf(k) >= 0);
  check("V24", "㉔ 批量结果只走结果浮层：出口唯一（三条腿都经 `showBulkReceipt`→`toastCard`）"
     + " + 固化槽零残留（模块级文本/槽/回填/清理/样式）+ 3s 自动消失 + × 手动关闭"
     + " + 术语解释走悬停不坐正文",
     /function showBulkReceipt\(/.test(pageSrcAll)
     && /toastCard\(title, html, \{ type: tone, ms: 3000 \}\);/.test(pageSrcAll)
     && Object.values(receiptBodies).every((b) => !!b && b.indexOf("showBulkReceipt(") >= 0)
     && leftovers.length === 0
     && cssPlain.indexOf(".bulk-receipt") < 0
     && /export function toastCard\(title, html, \{ type = "", ms = 3000 \} = \{\}\)/.test(compSrc)
     && /class="t-close" type="button" aria-label="关闭提示"/.test(compSrc)
     && /setTimeout\(kill, ms\);/.test(compSrc)
     && /note: "「未发起」=/.test(pageSrcAll)
     && /\.t-sum \{[^}]*cursor: help/.test(cssSrc)
     // 第五条腿（:8300 实盘抓出来的自我矛盾）：逐号那一行的词必须读**权威分桶**
     // （`report.failed/success/inactive`），不许再用 `reason || "已刷新"` ——
     // 后端 `reason=""` 是一格多义（既给 success 也给"查了但没给数值"的 inactive），
     // 旧写法让同一张浮层上面写「未发起 2 个」、下面两行写「已刷新」。
     && /inList\(rep\.failed, acc\)/.test(pageSrcAll)
     && /inList\(rep\.success, acc\)/.test(pageSrcAll)
     && stripComments(pageSrcAll).indexOf('reason || "已刷新"') < 0,
     () => Object.entries(receiptBodies).map(([k, v]) => `${k}=${v ? "有" : "找不到"}`).join(" ")
       + `｜固化残留=${leftovers.length ? leftovers.join(" ") : "无"}`
       + `｜css 留类=${cssPlain.indexOf(".bulk-receipt") >= 0}`
       + `｜浮层=${/export function toastCard\(/.test(compSrc)}｜3s=${/ms = 3000/.test(compSrc)}`
       + `｜出口=${/toastCard\(title, html, \{ type: tone, ms: 3000 \}\);/.test(pageSrcAll)}`
       + `｜关闭钮=${/aria-label="关闭提示"/.test(compSrc)}｜解释挂悬停=${/note: "「未发起」=/.test(pageSrcAll)}`);

  /* ---------- V25 · 「状态」列删除（10-04）+ 草稿说明常驻（10-05 第四次裁定，**方向反转**） ----------
   * 删列那条不变：那一列同时说三件事，各格已有主人（下拉 = 挂哪、开关 = 进不进池）。
   * 🔴 本轮反转的是**第③腿**：上一版 V25 禁「保存后解除关联」这类常驻文案（那时没有「保存」，
   *   那句话是假陈述）；现在「保存」是**唯一**写入口，"改了还没入库"重新变成一个真实、
   *   且必须常驻说清的状态 —— 否则用户带着"AI 已经帮我配好了"离开，而盘上一条没写。
   *   判据随设计前进 = **反过来要求它在册**，不是把这条删掉（删掉 = 这条腿从此无人看管）。 */
  const footSlice = fnSlice("function mapFootHTML(", "\n}");
  const pickSlice = fnSlice("function pickTarget(", "\n}");
  const sugSlice = fnSlice("function suggestionOf(", "\n}");
  const repaintSlice = fnSlice("const repaintState = (i) => {", "\n    };");
  const thCount = ((bodySlice || "").match(/\bth\("/g) || []).length;
  const draftNotes = ["点「保存」才入库", "保存后解除关联"];
  check("V25", "㉕ 映射弹窗无「状态」列（表头恰 4 列 + 旧徽章文案零回潮）+ 下拉**只读已落库**的目标"
     + "（建议不得进下拉）+ 🔴 草稿说明常驻在册（「点「保存」才入库」「保存后解除关联」）"
     + " + 重绘只换 [data-mapfoot] 那一行",
     !!bodySlice && !!footSlice && !!pickSlice && !!sugSlice && !!repaintSlice
     && thCount === 4 && (bodySlice || "").indexOf('th("状态")') < 0
     && (bodySlice || "").indexOf("104px") < 0
     && (bodySlice || "").indexOf('badge b-gray">未映射') < 0
     && pageSrcAll.indexOf("已映射 · 进池") < 0
     && /return \(m\.mapped_to \|\| \[\]\)\.find\(inList\) \|\| "";/.test(pickSlice)
     && pickSlice.indexOf("suggest") < 0
     && /confidence >= 0\.7/.test(sugSlice)
     && /data-adopt="\$\{esc\(sug\)\}" data-for="\$\{i\}"/.test(footSlice)
     && footSlice.indexOf(">采纳<") >= 0
     && draftNotes.every((k) => footSlice.indexOf(k) >= 0)
     && /data-mapfoot="\$\{i\}"/.test(bodySlice || "")
     && /slot\.innerHTML = mapFootHTML\(modelOf\(i\), i, \{/.test(repaintSlice)
     && repaintSlice.indexOf("row.children[") < 0
     // 🔴 反向腿：脚注必须告诉用户"这一屏要点保存"（旧版禁「保存」字样，随本轮作废）
     && /点「保存」才写入配置/.test(stripComments(bodySlice || "")),
     () => `表头 th 数=${thCount}｜含状态列=${(bodySlice || "").indexOf('th("状态")') >= 0}`
       + `｜104px 残留=${(bodySlice || "").indexOf("104px") >= 0}`
       + `｜徽章回潮=${(bodySlice || "").indexOf('badge b-gray">未映射') >= 0 || pageSrcAll.indexOf("已映射 · 进池") >= 0}`
       + `｜下拉只读落库=${!!pickSlice && /return \(m\.mapped_to \|\| \[\]\)\.find\(inList\) \|\| "";/.test(pickSlice)}`
       + `｜建议混进下拉(红)=${!!pickSlice && pickSlice.indexOf("suggest") >= 0}`
       + `｜建议出口=${!!sugSlice}｜采纳钮=${/data-adopt/.test(footSlice || "")}`
       + `｜草稿说明缺=${draftNotes.filter((k) => !(footSlice || "").includes(k)).join(" / ") || "无"}`
       + `｜重绘整格覆盖=${!!repaintSlice && repaintSlice.indexOf("row.children[") >= 0}`
       + `｜脚注说保存=${/点「保存」才写入配置/.test(stripComments(bodySlice || ""))}`);

  /* ---------- V26 · 「保存」= 唯一写入口（2026-10-05 第四次裁定）+ 删除入口零残留（10-04 不变） ----------
   * 🔴 本轮的反转项：上一版 V26 钉的是「`saveAll` 整族**不许存在**」，现在反过来钉它**必须在册且是唯一出口**。
   *   四条腿：
   *   ① 行内接线块（下拉 onchange / 采纳钮 / 开关）与 `stage` 体内**零 POST** ——
   *      这一条就是"草稿制"在代码里的形状：改一格只动内存；
   *   ② `saveAll` 体内两个端点各**恰一处**：有目标的行走 `mappings`（一次提交，不逐行发），
   *      改回「暂不设置」而盘上有位的行走 `product-models/remove`（位与条目一起删，判据在后端）；
   *      🔴 不在 `mappings` 写入面里另造第二套「解除」语义（两套真相 = 本项目反复抓的那类病）；
   *   ③ 被拒 / 解除失败的那些行必须**退回盘上的真值**（`draft.delete(i)` + 下拉回写），
   *      且**不关窗**、就地列原话 —— 用户带着"保存过了"离开而盘上没动，是复验 R10 抓过的同一形状；
   *   ④ 删除入口（旧的「删除映射」钮族）零残留：解除只有一个入口 = 改回「暂不设置」。 */
  const delGhosts = ["data-mapdel", "data-del-yes", "data-del-no", "askRemove",
                     "removeMapping", "wireRemove", "const delBtn"]
    .filter((k) => pageSrcAll.indexOf(k) >= 0);
  const stageSlice = fnSlice("const stage = (i, patch) => {", "\n    };");
  const postInWiring = !!wiringSlice ? (wiringSlice.match(/POST\(/g) || []).length : -1;
  check("V26", "㉖ 保存 = 唯一写入口：行内接线块零 POST + saveAll 两条腿各恰一处（mappings 一次 / 逐行 remove）"
     + " + 被拒行退回盘上真值且不关窗 + 删除入口整族零残留",
     !!saveSlice && !!wiringSlice && !!stageSlice
     && postInWiring === 0 && stageSlice.indexOf("POST(") < 0
     && (saveSlice.match(/POST\("\/admin\/api\/accounts\/mappings"/g) || []).length === 1
     && (saveSlice.match(/POST\("\/admin\/api\/accounts\/product-models\/remove"/g) || []).length === 1
     && /if \(items\.length\) \{/.test(saveSlice)
     && /else if \(mapHasBit\(m\)\) unbinds\.push\(i\);/.test(saveSlice)
     && (saveSlice.match(/draft\.delete\(i\);/g) || []).length >= 3
     && /if \(lines\.length\) \{/.test(saveSlice)
     && /else \{[\s\S]{0,60}detachGuard\(\);[\s\S]{0,60}dlg\.close\(\);/.test(saveSlice)
     && delGhosts.length === 0,
     () => `行内接线块 POST 数=${postInWiring}｜stage 内 POST=${stageSlice.indexOf("POST(") >= 0}`
       + `｜mappings 处数=${!!saveSlice ? (saveSlice.match(/accounts\/mappings/g) || []).length : -1}`
       + `｜remove 处数=${!!saveSlice ? (saveSlice.match(/product-models\/remove/g) || []).length : -1}`
       + `｜空 items 不发=${!!saveSlice && /if \(items\.length\)/.test(saveSlice)}`
       + `｜没位不发解除=${!!saveSlice && /else if \(mapHasBit\(m\)\) unbinds\.push/.test(saveSlice)}`
       + `｜退回真值次数=${!!saveSlice ? (saveSlice.match(/draft\.delete\(i\);/g) || []).length : -1}`
       + `｜有失败不关窗=${!!saveSlice && /if \(lines\.length\)/.test(saveSlice)}`
       + `｜删除入口残留=${delGhosts.length ? delGhosts.join(" ") : "无"}`);


  /* ---------- V27 · 两态机器零回潮 +「还没入库」这件事在界面上有主人 ----------
   * 2026-10-04 加的是"脚钮显隐跟着数据走"；10-05 第三次指示改常驻 ⇒ 那台机器作废；
   * 本轮「保存」回来，但它**不是那颗钮的第二态** —— 两颗钮、两种语义、两个主人（V22 钉形状）。
   * 三条腿：
   *   ① 行内三条腿（开关 / 下拉 / 采纳）体内零 `setMode(`：翻态机器留半套就是留着两套真相；
   *   ② 脏态数上界面（`保存（N 处未保存）`）+ 回执 `kept` 上界面 —— 否则"什么都没改"、
   *      "改了 20 行没存"、"AI 填了 20 行没存"三种状态在画面上长得一样；
   *   ③ 在飞有可见态且两支都收回（`aiBusy` + `setMode()`），不留下「AI 匹配中…」的假忙碌。 */
  const switchSlice = fnSlice("const mountSwitch = (i) => {", "\n    };");
  const dirtySlice = fnSlice("const isDirty = (i) => {", "\n    };");
  check("V27", "㉗ 两态机器零回潮（行内三条腿都不翻钮）+ 脏态数与回执 `kept` 都上界面 + 匹配中有可见态",
     !!switchSlice && !!dirtySlice && !!aiSlice && !!saveSlice
     && switchSlice.indexOf("setMode(") < 0
     && wiringSlice.indexOf("setMode(") < 0
     && /保存（\$\{n\} 处未保存）/.test(pageSrcAll)
     && /已配置的 \$\{r\.kept\}|\$\{r\.kept\} 行/.test(aiSlice)
     && /aiBtn\.textContent = "AI 匹配中…";/.test(aiSlice)
     && (aiSlice.match(/setMode\(\);/g) || []).length >= 1
     && /dirtyRows\(\)\.length/.test(pageSrcAll),
     () => `开关体内 setMode=${switchSlice.indexOf("setMode(") >= 0}`
       + `｜接线块 setMode=${wiringSlice.indexOf("setMode(") >= 0}`
       + `｜脏态计数上钮=${/保存（\$\{n\} 处未保存）/.test(pageSrcAll)}`
       + `｜kept 上界面=${/\$\{r\.kept\} 行/.test(aiSlice || "")}`
       + `｜在飞文案=${/AI 匹配中…/.test(aiSlice || "")}`);

  /* ---------- V28 · 行内三条腿都只改草稿（2026-10-05 第四次裁定第①条的代码形状） ----------
   *   ① `select.onchange` 指向 `stage`（旧形状 = 指向 `commitTarget` 当场写盘，本轮作废）；
   *   ② 新映射缺省**进池**：这条从 Q37 原样保留，只是主人从"逐行落库"换成"保存那一次提交" ——
   *      判据 = `curEnabled` 里那一句 `return p === null ? true : p;`（V21 已钉它只有一个出口）；
   *      已有位的行**保持盘上开关态**（用户明确关掉的那条不因改名被悄悄拨开）；
   *   ③ 采纳钮按 `data-for` 行号 + `data-adopt` 目标名派发（按错索引 = 改错行）；
   *   ④ 保存在飞禁二次点击（开关与 AI 钮都禁用），否则半程里改的东西会被上一次提交的结果盖掉。 */
  check("V28", "㉘ 行内只改草稿：onchange/采纳/开关三条腿全走 `stage` + 新行缺省进池只算一处"
     + " + 保存在飞禁二次点击 + 旧「整表按开关位置取 enabled」零回潮",
     /sel\.onchange = \(\) => stage\(i, \{ target: String\(sel\.value \|\| ""\) \}\);/.test(pageSrcAll)
     && /stage\(i, \{ target: btn\.dataset\.adopt \}\);/.test(pageSrcAll)
     && /stage\(i, \{ enabled: !on \}\);/.test(switchSlice || "")
     && /return p === null \? true : p;/.test(curOnSlice || "")
     && /if \(saving\) el\.disabled = true;/.test(switchSlice || "")
     && /aiBtn\.disabled = true;/.test(aiSlice || "")
     && stripComments(pageSrcAll).indexOf("enabled: mapOn.get(i) !== false") < 0
     && stripComments(pageSrcAll).indexOf("commitTarget") < 0,
     () => `onchange 走 stage=${/sel\.onchange = \(\) => stage\(i/.test(pageSrcAll)}`
       + `｜采纳走 stage=${/stage\(i, \{ target: btn\.dataset\.adopt/.test(pageSrcAll)}`
       + `｜开关走 stage=${/stage\(i, \{ enabled: !on/.test(switchSlice || "")}`
       + `｜缺省进池一处算=${/return p === null \? true : p;/.test(curOnSlice || "")}`
       + `｜保存在飞禁点=${/if \(saving\) el\.disabled = true;/.test(switchSlice || "")}`
       + `｜commitTarget 回潮=${stripComments(pageSrcAll).indexOf("commitTarget") >= 0}`);

  /* ---------- V29 · 新增：取消必须真能取消（草稿制的另一半，10-04 那条律随本轮复活） ----------
   * 草稿制下"取消"是**唯一**能丢弃用户劳动的出口，而 modal() 有三条关闭通道
   * （按钮 / 右上角 × / 点遮罩空白）—— 同一形状在 components.js 的 confirmDialog 注释里记过一次：
   * 只堵一条，另外两条就是"静默丢弃"。四条腿：
   *   ① 三条通道都指向同一个 `tryClose`（✕ 用重绑、遮罩用 document 捕获阶段抢在 modal() 之前）；
   *   ② 有脏态时第一次只**警告**（`armed = true` + 就地一条 `data-discard` 说明），不关窗；
   *   ③ 第二次（或没有脏态）才真关，且关之前摘掉全局监听器（不许漏一条捕获在 document 上）；
   *   ④ 任何一次编辑都把那句警告撤掉（`stage` 里 `armed = false` + 摘节点），不留过期恐吓。 */
  const closeSlice = fnSlice("const tryClose = () => {", "\n    };");
  check("V29", "㉙ 取消真能取消：三条关闭通道同走 tryClose + 有脏态先警告再关（两步）+ 关前摘监听 + 一改就撤警告",
     !!closeSlice
     && /cancelBtn\.onclick = tryClose;/.test(pageSrcAll)
     && /dlg\.el\.querySelector\("\.modal-close"\)\.onclick = tryClose;/.test(pageSrcAll)
     && /document\.addEventListener\("mousedown", guardBackdrop, true\);/.test(pageSrcAll)
     && /if \(!n \|\| armed\) \{ detachGuard\(\); dlg\.close\(\); return; \}/.test(closeSlice)
     && (closeSlice.match(/dlg\.close\(\);/g) || []).length === 1
     && /data-discard/.test(closeSlice)
     && /const detachGuard = \(\) => document\.removeEventListener\("mousedown", guardBackdrop, true\);/.test(pageSrcAll)
     && /armed = false;/.test(stageSlice || "")
     && /warn\) warn\.remove\(\);/.test(stageSlice || ""),
     () => `tryClose 体=${closeSlice ? closeSlice.length + " 字" : "找不到"}`
       + `｜取消钮=${/cancelBtn\.onclick = tryClose/.test(pageSrcAll)}`
       + `｜× 钮=${/\.modal-close"\)\.onclick = tryClose/.test(pageSrcAll)}`
       + `｜遮罩捕获=${/guardBackdrop, true\)/.test(pageSrcAll)}`
       + `｜dlg.close 次数=${!!closeSlice ? (closeSlice.match(/dlg\.close\(\);/g) || []).length : -1}`
       + `｜摘监听=${/removeEventListener\("mousedown", guardBackdrop, true\)/.test(pageSrcAll)}`
       + `｜编辑撤警告=${/armed = false;/.test(stageSlice || "")}`);

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
  if (pageSrcAll.indexOf("req-detail") >= 0 || pageSrcAll.indexOf("data-exp") >= 0) {
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
  { id: "V21", fix: [], kills: ["V21"],
    why: "把盘上位读回 `!== false`（后端 null = 未映射会被渲染成\"已开进池\"，"
         + "正是 2026-10-03 用户据此追问资源池的那条假态；草稿制换了写的主人，这条读法一个字没改）",
    from: L('      return mapHasBit(m) ? m.map_enabled === true : null;   // null = 盘上没这条 ⇒ 保存时按缺省进池'),
    to: L('      return mapHasBit(m) ? m.map_enabled !== false : null;') },
  { id: "V21", fix: [], kills: ["V21", "V28"],
    why: "草稿缺省位改口「不进池」（本轮第 1 条「资源池怎么没显示」的根因写法：新行落盘即一条关着的位）",
    from: L('      return p === null ? true : p;      // 新映射缺省进池（Q37 ② 保留，只是主人换成「保存」那一次）'),
    to: L('      return p === null ? false : p;') },
  { id: "V20", fix: [], kills: ["V20"],
    why: "把「新建：」前缀装回网关模型下拉（2026-10-03 用户裁决：输出的数据都是网关模型，不区分新建/现有）",
    from: L('    ...sorted.map((n) => ({ value: n, label: n }))];'),
    to: L('    ...sorted.map((n) => ({ value: n, label: `新建：${n}` }))];') },
  { id: "V22", fix: [], kills: ["V22"],
    why: "把「AI智能匹配」的文案又做成随脏态切换（一颗钮两种语义 = 上一轮判死的那台两态机器回潮）",
    from: L('    aiBtn.textContent = "AI智能匹配";'),
    to: L('    aiBtn.textContent = dirtyRows().length ? "先保存再匹配" : "AI智能匹配";') },
  { id: "V22", fix: [], kills: ["V22"],
    why: "钮又长出显隐语义（`aiBtn.hidden` 一回潮，「什么时候能点」就又变成一门要猜的状态机）",
    from: L('  const setMode = () => {',
            '    aiBtn.textContent = "AI智能匹配";'),
    to: L('  const setMode = (init) => {',
            '    aiBtn.hidden = !!init;',
            '    aiBtn.textContent = "AI智能匹配";') },
  { id: "V22", fix: [], kills: ["V22"],
    why: "「保存」的使能不再读脏态（永远可点 ⇒ 用户会对着一个什么都没改的表按保存，"
         + "而真正没保存时它又和「已保存」长得一样 —— 使能必须读 `draft`，不读文案）",
    from: L('      saveBtn.disabled = n === 0 || saving;'),
    to: L('      saveBtn.disabled = saving;') },
  { id: "V24", fix: [], kills: ["V24"],
    // 结果回到"固化显示"：把浮层出口换成常驻槽（正是用户实拍否掉的那一块）
    why: "结果浮层退回固化槽（`toastCard` 换成往面板里写一块 `.bulk-receipt`）",
    from: L('  toastCard(title, html, { type: tone, ms: 3000 });'),
    to: L('  bulkReceipt = { title, html };',
          '  renderBulkReceipt();') },
  { id: "V24", fix: [], kills: ["V24"],
    // 重定锚（门自己抓的 BAD：上一版把锚指到 `components.js` 的 `setTimeout(kill, ms)`，
    //   而本门只改**页面副本** ⇒ 命中 0 次 = 无效撤证）。改钉页面这一侧能钉的那一半：
    //   时长是调用方传的 ⇒ 把 3000 改成 999999 = "3s 后还挂着"，等价于把固化搬到屏幕上。
    why: "浮层不自动消失（调用方把 3000ms 改成 999999ms ⇒ 结果一直挂在屏幕上 = 固化搬到浮层）",
    from: L('  toastCard(title, html, { type: tone, ms: 3000 });'),
    to: L('  toastCard(title, html, { type: tone, ms: 999999 });') },
  { id: "V24", fix: [], kills: ["V24"],
    why: "逐号结果词退回只读 `by_reason`（`reason=\"\"` 被标成「已刷新」⇒ 浮层自己跟计数行矛盾）",
    from: L('    if (inList(rep.success, acc)) return ["已刷新", "is-ok"];'),
    to: L('    if (!code) return ["已刷新", "is-ok"];') },
  { id: "V24", fix: [], kills: ["V24"],
    why: "术语解释坐进正文（`note:` 换成 `sum:` 的一部分 ⇒ 3 秒读不完的定义变成必读）",
    from: L('    note: "「未发起」= 熔断中 / 网络不可达 / 缺凭据（本轮未对上游发请求，上一轮的数值原样保留）"'),
    to: L('    sumNote: "「未发起」= 熔断中 / 网络不可达 / 缺凭据（本轮未对上游发请求，上一轮的数值原样保留）"') },
  { id: "V23", fix: [], kills: ["V23"],
    why: "AI 这条腿回填完**顺手写盘**（正是第四次裁定要杀的那件事：机器给的结果不经人确认就进配置）",
    from: L('      const r = await POST("/admin/api/accounts/auto-map", { product: p.id, models: empty });'),
    to: L('      const r = await POST("/admin/api/accounts/auto-map", { product: p.id, models: empty });',
          '      await POST("/admin/api/accounts/mappings", { product: p.id, items: [] });') },
  { id: "V23", fix: [], kills: ["V23"],
    why: "分析范围丢掉「屏幕上还空着」这一半（谓词恒真 ⇒ 每次点击都把已填过目标的行再烧一遍额度）",
    from: L('        .filter(({ i }) => !curTarget(i))'),
    to: L('        .filter(({ i }) => true)') },
  { id: "V23", fix: [], kills: ["V23"],
    why: "摘掉 `written !== false` 那条自查（后端哪天恢复写盘，界面不再有任何人看得见这件事）",
    from: L('        if (r.written !== false) {'),
    to: L('        if (false) {') },
  { id: "V23", fix: [], kills: ["V23"],
    why: "消耗声明改回「答案当场写入配置」（声明说的和这条腿实际做的相反 ⇒ 用户以为已经存好了）",
    from: L('        <b>当前显示为「暂不设置」的</b>模型该挂到哪个网关模型；答案<b>只回填进下面的下拉，'),
    to: L('        <b>还没配置过的</b>模型该挂到哪个网关模型；答案<b>当场写入配置并进资源池，') },
  { id: "V25", fix: [], kills: ["V25"],
    why: "「状态」列回潮（表头装回第 5 颗 th ⇒ 用户 2026-10-04 判为多此一举的那一列又站回来了）",
    from: L('      <div class="list-row" style="${grid}">${th("模型")}${th("规则")}${th("网关模型映射")}${th("进池")}</div>'),
    to: L('      <div class="list-row" style="${grid}">${th("模型")}${th("规则")}${th("网关模型映射")}${th("状态")}${th("进池")}</div>') },
  { id: "V25", fix: [], kills: ["V25"],
    why: "删列只删一半（列宽 104px 还留在网格里 ⇒ 界面出现一条谁也不住的空洞列）",
    from: L('  const grid = "display:grid;grid-template-columns:minmax(0,1fr) 56px 208px 44px;gap:12px;align-items:center";'),
    to: L('  const grid = "display:grid;grid-template-columns:minmax(0,1fr) 56px 208px 104px 44px;gap:12px;align-items:center";') },
  { id: "V25", fix: [], kills: ["V25"],
    why: "下拉不读已落库的映射（已挂 hy3 而行显示「暂不设置」⇒ 把「有映射」读成「没映射」）",
    from: L('  return (m.mapped_to || []).find(inList) || "";'),
    to: L('  return (m.mapped_to || []).find((n) => !!n) ? "" : "";') },
  { id: "V25", fix: [], kills: ["V25"],
    why: "正则建议回潮进下拉（:8300 实盘 26 行挂着一个从没写进配置的名字 = 假关联的直接病源）",
    from: L('  return (m.mapped_to || []).find(inList) || "";'),
    to: L('  const p = (m.mapped_to || []).find(inList);',
          '  if (p) return p;',
          '  const sg = m.suggest;',
          '  return sg && sg.name && options.some((o) => o.value === sg.name) ? sg.name : "";') },
  { id: "V25", fix: [], kills: ["V25"],
    // 🔴 方向反转（2026-10-05 第四次裁定）：上一版这条变异是「常驻文案回潮 ⇒ 判红」，
    //    现在这两句话是**真话且必须常驻**，于是变异反过来做 —— 把它们摘掉才判红。
    //    条目不删、方向改，理由写在这里：判据的主人从"没有保存这一步"换成了"保存是唯一写入口"。
    why: "草稿说明被摘掉（改了还没入库这件事没人说 ⇒ 用户带着「AI 已经配好了」离开，而盘上一条没写）",
    from: L('    return note(s ? "已改动 · 点「保存」才入库" : "已清空 · 点「保存」才入库");'),
    to: L('    return "";') },
  { id: "V25", fix: [], kills: ["V25"],
    why: "脚注改口「一改即落库、没有保存这一步」（上一轮的口径，随本轮作废 ⇒ 界面上不许留两套说法）",
    from: L('      取不到的不展示，不编造）；目录来源见顶部。🔴 <b>这一屏的改动要点「保存」才写入配置</b>：'),
    to: L('      取不到的不展示，不编造）；目录来源见顶部。<b>这一行一改即落库，没有「保存」这一步</b>：') },
  { id: "V25", fix: [], kills: ["V25"],
    why: "重绘退回按索引整格覆盖（同格的下拉与说明行会被一起吃掉 = 旧缺陷形状复活）",
    from: L('      if (slot) slot.innerHTML = mapFootHTML(modelOf(i), i, {'),
    to: L('      if (row.children[2]) row.children[2].innerHTML = mapFootHTML(modelOf(i), i, {') },
  /* ---------- V26 的变异：「保存 = 唯一写入口」的每一半都要能红 ---------- */
  { id: "V26", fix: [], kills: ["V26"],
    why: "「删除映射」钮回潮（用户 10-04 明令去掉；解除有第二入口 = 两套真相）",
    from: L('  if (mapHasBit(m)) return "";'),
    to: L('  if (mapHasBit(m)) return `<button class="link-btn" data-mapdel="0">删除映射</button>`;') },
  { id: "V26", fix: [], kills: ["V26"],
    why: "行内采纳钮长出 POST（草稿制的形状就是「接线块里一个 POST 都没有」，破一处就整套失效）",
    from: L('        stage(i, { target: btn.dataset.adopt });'),
    to: L('        POST("/admin/api/accounts/mappings", { product: p.id, items: [] });',
          '        stage(i, { target: btn.dataset.adopt });') },
  { id: "V26", fix: [], kills: ["V26"],
    why: "解除判据丢掉后端那个位（改成「下拉一空就发解除」⇒ 从没配置过的行也吃一次写请求）",
    from: L('        else if (mapHasBit(m)) unbinds.push(i);'),
    to: L('        else unbinds.push(i);') },
  { id: "V26", fix: [], kills: ["V26"],
    why: "整表 items 为空也发（后端对「全部 target 为空」回 400 ⇒ 一次纯解除的保存必红）",
    from: L('        if (items.length) {'),
    to: L('        if (true) {') },
  { id: "V26", fix: [], kills: ["V26"],
    why: "有失败也关窗（用户带着「保存过了」离开，而盘上那几条根本没动 = 复验 R10 抓过的同一形状）",
    from: L('        if (lines.length) {'),
    to: L('        if (false && lines.length) {') },
  { id: "V27", fix: [], kills: ["V27"],
    why: "「跟着数据翻钮」那台机器回潮（三颗钮各有主人，行内开关再翻一次状态 = 两套真相重新长回来）",
    from: L('        stage(i, { enabled: !on });'),
    to: L('        stage(i, { enabled: !on });',
          '        setMode();') },
  { id: "V27", fix: [], kills: ["V27"],
    why: "脏态数不上那颗钮（「什么都没改」「改了 20 行没存」「AI 填了 20 行没存」在画面上长得一样）",
    from: L('      saveBtn.textContent = n ? `保存（${n} 处未保存）` : "保存";'),
    to: L('      saveBtn.textContent = "保存";') },
  { id: "V27", fix: [], kills: ["V27"],
    why: "匹配中不留可见态（顺序执行可达数十秒，界面没有任何「正在做事」的痕迹 = 用户会连点）",
    from: L('      aiBtn.textContent = "AI 匹配中…";'),
    to: L('      // 撤证：不设 in-flight 文案') },
  { id: "V27", fix: [], kills: ["V23", "V27"],
    why: "回执 `kept` 不上界面（一次空点击与一次改了 20 行的点击在界面上同形；连带 V23 那条"
         + "「回填后把没入库说在明面上」的腿一起红 —— 两条判据读的是同一句 toast）",
    from: L('            + (r.kept ? `；${r.kept} 行（已配置或已填值）本轮没送去分析` : ""), "ok");'),
    to: L('            , "ok");') },
  /* ---------- V28 的变异：行内三条腿"只改草稿"的每一半都要能红 ---------- */
  { id: "V28", fix: [], kills: ["V28"],
    why: "onchange 退回直接写盘（回到上一轮「行内一改即落库」，草稿制当场作废）",
    from: L('      sel.onchange = () => stage(i, { target: String(sel.value || "") });'),
    to: L('      sel.onchange = () => commitTarget(i, String(sel.value || ""));') },
  { id: "V28", fix: [], kills: ["V28"],
    why: "采纳钮按错派发（丢掉 `data-for` 行号 ⇒ 点 A 行的采纳改到 B 行）",
    from: L('        stage(i, { target: btn.dataset.adopt });'),
    to: L('        stage(0, { target: btn.dataset.adopt });') },
  { id: "V28", fix: [], kills: ["V28"],
    why: "保存在飞不禁二次点击（半程里改的东西会被上一次提交回来的回执盖掉）",
    from: L('      if (saving) el.disabled = true;                     // 保存在飞：禁二次点击'),
    to: L('      // 撤证：不禁二次点击') },
  /* ---------- V29 的变异（本轮新增）：取消必须真能取消，三条关闭通道一条都不能漏 ---------- */
  { id: "V29", fix: [], kills: ["V29"],
    why: "右上角 × 绕过 tryClose 直接关（modal() 自带这条不经过按钮的关闭路径 ⇒ 静默丢弃用户的草稿）",
    from: L('    dlg.el.querySelector(".modal-close").onclick = tryClose;'),
    to: L('    dlg.el.querySelector(".modal-close").onclick = () => { detachGuard(); dlg.close(); };') },
  { id: "V29", fix: [], kills: ["V29"],
    why: "两步确认退成一步（有脏态也直接关 = 用户一次误点丢掉一屏编辑）",
    from: L('      if (!n || armed) { detachGuard(); dlg.close(); return; }'),
    to: L('      detachGuard(); dlg.close(); return;') },
  { id: "V29", fix: [], kills: ["V29"],
    why: "遮罩那条关闭通道不拦（点空白处 = 静默丢弃，与 × 同一条病）",
    from: L('    document.addEventListener("mousedown", guardBackdrop, true);'),
    to: L('    // 撤证：不拦遮罩') },
  { id: "V29", fix: [], kills: ["V29"],
    why: "编辑之后那句「再点一次就放弃」不撤（恐吓常驻在页面上，用户以为改不动了）",
    from: L('      armed = false;                       // 用户还在编辑 ⇒ 那句"再点一次就放弃"作废'),
    to: L('      // 撤证：编辑后不撤警告') },
  { id: "V6", fix: TABLE_FIX, kills: ["V6", "V4", "V7", "V10", "V14", "V14b", "V15"],
    why: "表头「额度」改名「配额」（§3 是逐字列集，改名即判红；连带：额度列按表头定位，列名一改所有读额度格的判据同时失去对象 = 如实声明，不写成单点）",
    // 重定锚（2026-10-03 用户「状态列和额度列交换下位置」⇒ 表头行改写，锚跟着走；变异后果不变：
    //   把「额度」改名「配额」，V6 逐字列集与所有按表头定位的额度判据同时失去对象）
    from: L('        <th class="num">额度</th><th>状态</th><th class="ops-col">操作</th>'),
    to: L('        <th class="num">配额</th><th>状态</th><th class="ops-col">操作</th>') },
  { id: "V7", fix: [], expectGreen: true, kills: ["V7"],
    why: "第四态「尚未刷新」被折进「未知」（把 BUG-2「网关还没查过」藏成「查了但拿不到」，§3 明令区分）",
    // 重定锚（2026-10-02 五档改版：「尚未刷新」那行的 title 文案扩了字，锚跟着走；变异后果不变）
    // 重定锚（2026-10-03 额度格重做：这一档改由 quotaPlainHTML 包一层，锚跟着走；变异后果不变）
    // 重定锚（2026-10-03 修 D4/V13/V14 红：悬停从档名 span 搬到**额度格根节点**（cellTip 第二参），
    //    锚跟着走；变异后果不变 = 「网关还没查过」这一档被折进「查了但拿不到」）
    from: L('    return quotaPlainHTML(`<span class="qnone">尚未刷新</span>`,',
          '      "运行态里没有额度快照：网关还没查过这个账号（BUG-2 的可见态）");'),
    to: L('    return quotaPlainHTML(`<span class="qnone">未知</span>`,',
          '      "上游未给出额度");') },
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
    // 🔴 2026-10-03 重定锚（不是删条目）：用户否掉了"展开/折叠"本身（三家参考实现都没有折叠），
    //    `.qpacks-detail` 整块随之删除。本条要防的**病**没变——"查到了却不给用户看，只能靠悬停"——
    //    只是新形态下它等于"多组时不逐组给量"。于是锚挪到 chips 行：摘掉它，V10 的组级判据必须红。
    // 重定锚（2026-10-03 三次改判：先否掉折叠 ⇒ 锚挪到 chips 行；再要求明细并进主行 ⇒ 锚挪到主行；
    //    最终裁定「合计：900 积分」⇒ 明细回到自己一行、主行改成"标签：数值"同排）。
    //    本条要防的**病**一字未变：多组时不逐组给量 = 组级信息只剩悬停。
    why: "多组额度不逐组给量（摘掉明细行 ⇒ 组级余量只剩悬停 title）",
    from: L('    out.push(`<div class="qchips">${chips}`',
          '      + (more > 0 ? `<span class="qchip qchip-more" title="${esc(all)}">+${more} 类</span>` : "")',
          '      + `</div>`);'),
    to: L('    // 撤证：多组时不再逐组给量') },
{ id: "V10", fix: [], expectGreen: true, kills: ["V10"],
    // 🔴 新判据配新变异（不删条目、也不留"永远绿"的判据）：把「标签：数值」同排改回
    //    "左标签 + 右浮 .qval 数值" = 用户这次实拍的那一屏的旧形状，V10 必须红。
    why: "数值右浮回潮（去掉标签的「：」并把 .qnum 包回右浮的 .qval 壳）",
    // 🔴 变异必须**只改语法、不改结构**：上一版只写到半截 `<span class="qval">` 没闭合，
    //    假 DOM 解析崩掉 ⇒ V10 的红来自"整行没了"（th=4 td=2）而不是来自判据本身 = 无效撤证。
    //    现在把 push 的三行整体换形，闭合补齐 ⇒ 红只能来自「：」缺失 + `.qval` 壳回潮。
    from: L('    out.push(`<div class="qrow"><span class="qname" title="${esc(name)}">${esc(name)}：</span>`',
          '      + `<b class="qnum">${val}</b>`',
          '      + (exhausted ? `<span class="qtier">已耗尽</span>` : "") + `</div>`);'),
    to: L('    out.push(`<div class="qrow"><span class="qname" title="${esc(name)}">${esc(name)}</span>`',
          '      + `<span class="qval"><b class="qnum">${val}</b>`',
          '      + (exhausted ? `<span class="qtier">已耗尽</span>` : "") + `</span></div>`);') },
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
    // 🔴 反向自证①的同一编辑（`to` 只留注释）；`from` 含整支 ⇒ 逐字唯一命中
    // 重定锚（2026-10-03 额度格重做：这一档也走 quotaPlainHTML；变异后果不变）
    // 重定锚（2026-10-03 修 D4/V13/V14 红：两可性原文改挂**额度格根节点**（cellTip），锚跟着走）
    from: L('  if (rq.reason === "no_plan") {',
          '    return quotaPlainHTML(`<span class="qnone">无套餐${esc(note)}</span>`,',
          '      cellTip(rq, "上游返回空套餐列表"));',
          '  }'),
    to: L('  // 撤证：no_plan 支被摘（页面没有「无套餐」这一档）') },
  { id: "V14b", fix: [], expectGreen: true, kills: ["V14b", "V10"],
    // 连带如实声明（2026-10-03）：护栏一摘，`ix-null-remaining` 那行走进"有量化余量"的分支，
    // 而它是多组行 ⇒ V10 的「多组必须在合计后逐组给量 / 明细须与合计同块」同时失去对象 = 必红。
    // 不是判据写松了，是这一支变异本来就会连带打穿主行结构 —— 写进 kills，不留"未声明连带"。
    why: "摘掉「上游一个可用数都没给」的护栏（= 把 remaining:null 当 0 累加并按 total<=0 判「已耗尽」，§4-3 明令禁止的谎：「没给数字」≠「数字是 0」）",
    // 重定锚（2026-10-03：套餐徽章按用户指令从额度格删除 ⇒ 旧锚第一行不复存在；
    //    护栏本身换了名字 `anyRem`，语义一字未改）
    from: L('  if (!anyRem) {'),
    to: L('  if (false) {') },
  { id: "V15", fix: [], expectGreen: true, kills: ["V15"],
    // 重定锚（2026-10-03 措辞随设计前进：「重置于 X」并入 meta 行的「至 MM-DD HH:mm」，
    //    取数仍是"有效包里最早的那个"，§4-5 定义一字未改）
    why: "到期时刻整段不渲染（§4-5 定义 = 有效包里最早的 expires_at，被摘后用户不知道额度什么时候恢复）",
    from: L('  if (exp) bits.push(`至 ${esc(shortTime(exp).slice(5))}`);'),
    to: L('  if (false && exp) bits.push(`至 ${esc(shortTime(exp).slice(5))}`);') },
  { id: "V15", fix: [], expectGreen: true, kills: ["V15"],
    why: "附属标注映射表里「未发起」那一档的两个 reason（no_credentials / no_identity）同时被摘 ⇒ **同文案两行必须同时红**，否则映射表是假的（方案 §8.2 X-R5-9）",
    from: L('  no_credentials: "（未发起）",',
          '  no_identity: "（未发起）",'),
    to: L('  no_credentials: "",',
          '  no_identity: "",') },
  { id: "V17", fix: [], expectGreen: true, kills: ["V17", "V15"],
    why: "摘掉页面的 ISO 形状护栏（§4-5 后半句「仅当匹配 ^\\d{4}-\\d{2}-\\d{2} 才渲染」，谓词恒真）⇒ 上游秒级 epoch 直接进用户可见面：tooltip 印 10 位裸 epoch（V17 红）、到期时刻被 slice(5) 切成 6 位残串（V15 的「出现即合形」红）",
    // 🔴 这就是 X-R5-5 说的那条绕过：`shortTime(1790956800).slice(5)` = "956800"，
    //    只扫 visibleText 的 V17 看不见 6 位残串 ⇒ 本条能红的通路是 **tooltip 里的 `失效于`**
    //    （V17 因此必须同时扫 `tipOf(cell)`，见判据段注释），残串那一半由 V15 的正形兜住。
    from: L('const ISO_RE = /^\\d{4}-\\d{2}-\\d{2}/;'),
    to: L('const ISO_RE = /./;') },
];

/** D-1/D-4 拆分后（2026-10-06）：锚点可能落在 accounts/ 子模块——逐文件找恰一命中者，
 *  返回 { file, src } 供变异只改那一段（其余文件原样随副本走）。 */
const partFilesOf = () => {
  const dir = PAGE_FILE.replace(/[^/\\]+$/, "") + "accounts";
  return existsSync(dir)
    ? readdirSync(dir).filter((f) => f.endsWith(".js")).sort().map((f) => join(dir, f))
    : [];
};
const locateEdit = ({ from }) => {
  const candidates = [[PAGE_FILE, readFileSync(PAGE_FILE, "utf-8")],
    ...partFilesOf().map((f) => [f, readFileSync(f, "utf-8")])];
  const hits = candidates.map(([f, src]) => [f, src.split(from).length - 1]);
  const hit = hits.filter(([, n]) => n === 1);
  if (hit.length === 1) {
    const [file] = hit[0];
    return { file, src: candidates.find(([f]) => f === file)[1] };
  }
  const total = hits.reduce((a, [, n]) => a + n, 0);
  throw new Error(`锚点在主文件+子模块中命中 ${total} 次（需恰一段恰 1 次）。`
    + "变异锚点过期 = 最隐蔽的一种假通过：请把本条变异重定锚到新页面对应位置，**不许删条目**");
};
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

/** 变异副本 = 主文件副本 + accounts/ 子模块目录原样拷贝（子进程的
 *  pagePartsDir 推导跟随副本父目录 ⇒ 子模块必须随行，否则主文件行为退化）。 */
function stageCopy(work, name, mainSrc, mutatedPartFile, mutatedPartSrc) {
  const copy = join(work, name);
  writeFileSync(copy, mainSrc);
  const srcDir = PAGE_FILE.replace(/[^/\\]+$/, "") + "accounts";
  if (existsSync(srcDir)) {
    const dstDir = join(work, "accounts");
    mkdirSync(dstDir, { recursive: true });
    for (const f of readdirSync(srcDir).filter((f) => f.endsWith(".js"))) {
      writeFileSync(join(dstDir, f),
        mutatedPartFile === f ? mutatedPartSrc : readFileSync(join(srcDir, f), "utf8"));
    }
  }
  return copy;
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
        throw new Error(`fix(${mut.id})：拆分后可绿性核验分支未适配 accounts/ 子模块——基线红时按 locateEdit 逐段修（本轮无此形状，防呆拦下）`);
        const fixed = runChild(copy);
        const fOk = okOf(fixed, mut.id);
        if (!fOk) throw new Error(`fix 后判据 ${mut.id} 读不到`);
        if (!fOk.ok) {
          throw new Error(`判据不可绿（死判据或 fix 编辑不足）：fix 后仍红 —— ${cut(fOk.detail, 120)}`);
        }
        prevRed = redOf(fixed);
        stage = `（基线红 → fix 转绿：${[...prevRed].join(",") || "全绿"} 仍红）`;
      }
      const loc = locateEdit(mut);
      const mutatedPartSrc = loc.src.replace(mut.from, () => mut.to);
      const copy2 = stageCopy(work, `accounts-${mut.id}-mutated.js`,
        loc.file === PAGE_FILE ? mutatedPartSrc : readFileSync(PAGE_FILE, "utf-8"),
        loc.file === PAGE_FILE ? null : loc.file.split("/").pop(), mutatedPartSrc);
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
