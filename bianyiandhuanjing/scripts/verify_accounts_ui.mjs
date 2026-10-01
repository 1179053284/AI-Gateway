#!/usr/bin/env node
/**
 * M7-UI 判据门 · 「账号接入」页 v2 结构（design-accounts-list-v2.md §8 判据 1）
 *
 * 干什么：把 `model_gateway/web/static/js/pages/accounts.js` 的**真源码**编进 vm，
 * 喂三份 fixture（0 账号 / 单产品 6 账号 / 10 产品 20 账号）执行页面的渲染入口
 * `renderAccounts(root)`，对产出的假 DOM 断言设计书 §8 的 8 条判据（V1–V8）+ 三条
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
 *   node scripts/verify_accounts_ui.mjs --mutation      # 变异自证（8 行表，见下）
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

/** 设计书 §3 的额度四值口径（V7 的唯一词表）与 §3 的措辞禁用表（V8 的词表）。 */
const QUOTA_WORDS = ["有余量", "已耗尽", "未知", "尚未刷新"];
const QUOTA_NONCE = ["剩余", "可用", "undefined", "NaN"];
const BANNED = ["正常", "在服务", "健康", "在线", "已取消"];
/** §3「移出常驻面」的信息：只许出现在展开详情行 `.req-detail` 里（L-A10）。 */
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

/* ==================== 数据面：fixture 读取 + 契约校验 + 轮换 ==================== */

/** fixture ↔ `api/admin_accounts.py` 的真实出口形状（键序即 :487-500 的 return）。 */
const ACCOUNT_KEYS = ["name", "enabled", "status", "device", "display", "runtime",
  "runtime_ok", "runtime_error", "quota", "resource"];
const PRODUCT_KEYS = ["id", "title", "login", "protocol", "base_url", "device",
  "capabilities", "models_source", "login_alt", "models_wired"];

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
      const out = await renderRun(pageSrc, { view, caps: fx.caps, loginStart: loginStart(selected, kinds[0]) });
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

  /* ---------- V4 · §0-4 BUG-1：额度格必须接 a.runtime.quota（设计书 §8-④） ---------- */
  const bug1 = [];
  for (const r of runs) {
    if (!r.selected.accounts.length) continue;
    const tbl = tableInfo(r.pageNodes);
    if (!tbl.has) continue;
    for (const a of r.selected.accounts) {
      const rq = (a.runtime && a.runtime.quota) || null;
      // 判别样本：运行态快照已知（available/exhausted）而池摘要 unknown —— 只读 a.quota 必然接错
      if (!rq || !["available", "exhausted"].includes(rq.state)) continue;
      if (a.quota && a.quota.state !== "unknown") continue;
      const row = tbl.rows.filter((tr) => text(tr).indexOf(a.name) >= 0)[0];
      if (!row) { bug1.push(`${r.fixture}/${r.selected.id}/${a.name}: 找不到账号行`); continue; }
      const q = quotaCellOf(tbl, row.k.filter((c) => c.t === "td"));
      const got = q.cell ? cut(visibleText(q.cell), 40) : `（${q.err}）`;
      const want = rq.state === "available" ? "有余量" : "已耗尽";
      if (got !== want && !(got.indexOf(want) >= 0 && got.indexOf("未知") < 0)) {
        bug1.push(`${r.fixture}/${r.selected.id}/${a.name}: 额度格「${cut(got, 24)}」≠「${want}」（BUG-1：quotaCell 只读 a.quota，从不读 runtime.quota）`);
      }
    }
  }
  check("V4", "④ 带 runtime.quota 的行额度格文本 ≠「未知」，且取到运行态快照的值（钉 BUG-1）",
    bug1.length === 0, () => bug1.length ? `${bug1.length} 处：${[...new Set(bug1)].slice(0, 3).join(" | ")}` : "全部判别样本都取到 runtime.quota");

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

  /* ---------- V6 · §3 四列固定列集（设计书 §8-⑥） ---------- */
  const HEAD_EXACT = ["账号", "状态", "额度", "操作"];
  const headBad = [];
  for (const r of runs) {
    if (!r.selected.accounts.length) continue;
    const tbl = tableInfo(r.pageNodes);
    if (!tbl.has) { headBad.push(`${r.fixture}/${r.selected.id}: 有账号却没渲染表格`); continue; }
    const texts = tbl.ths.map((t) => t.text);
    const legacy = texts.filter((t) => t === "参与运营" || t === "最近结果");
    if (legacy.length) headBad.push(`${r.fixture}/${r.selected.id}: 残留列「${legacy.join("、")}」（§3 已删）`);
    const rest = tbl.ths.slice(tbl.ths[0] && tbl.ths[0].exp ? 1 : 0).map((t) => t.text);
    if (!tbl.ths[0] || !tbl.ths[0].exp) headBad.push(`${r.fixture}/${r.selected.id}: 缺首列 .exp 空表头（§3 展开指示格）`);
    else if (rest.join("/") !== HEAD_EXACT.join("/")) headBad.push(`${r.fixture}/${r.selected.id}: 列集 ${JSON.stringify(rest)} ≠ ${JSON.stringify(HEAD_EXACT)}`);
  }
  check("V6", "⑥ 表头逐字 =（.exp 空格）+ 账号 / 状态 / 额度 / 操作，且无「参与运营」「最近结果」列",
    headBad.length === 0, () => headBad.length ? `${headBad.length} 处：${[...new Set(headBad)].slice(0, 3).join(" | ")}` : "列集逐字相符");

  /* ---------- V7 · §3 额度四值口径 + §6 BD8 的可见态（设计书 §8-⑦） ---------- */
  const vocabBad = [];
  const notFresh = [];
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
      const got = cut(visibleText(q.cell), 60);
      const hit = QUOTA_WORDS.filter((w) => got.indexOf(w) >= 0);
      const nonce = QUOTA_NONCE.filter((w) => got.indexOf(w) >= 0);
      if (hit.length !== 1 || nonce.length) {
        vocabBad.push(`${r.fixture}/${r.selected.id}/${a.name}: 额度格「${cut(got, 30)}」不在四值口径内（${QUOTA_WORDS.join("/")}）`);
      }
      const rq = a.runtime && a.runtime.quota;
      if (!rq && got.indexOf("尚未刷新") < 0) {
        notFresh.push(`${r.fixture}/${r.selected.id}/${a.name}: runtime.json 无 quota 快照却写「${cut(got, 20)}」（§3 第四态必须与「未知」区分：网关还没查过 ≠ 查了但拿不到）`);
      }
    });
  }
  check("V7", "⑦ 额度文本 ⊂ {有余量, 已耗尽, 未知, 尚未刷新}，且缺 runtime.json 快照的行写「尚未刷新」",
    vocabBad.length === 0 && notFresh.length === 0,
    () => {
      const u = [...new Set(vocabBad.concat(notFresh))];
      return u.length ? `${u.length} 处：${u.slice(0, 3).join(" | ")}` : "四值口径与第四态都对";
    });

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
        if (hay.some((h) => h.indexOf(w) >= 0) && !inside(n, ".req-detail")) {
          detailBad.push(`${r.fixture}/${r.selected.id}：常驻面出现「${w}」@ ${pathOf(n)}`);
        }
      }
    }
  }
  check("L-A10", "反转 M6-IX A10「头卡副行含协议/设备身份」→ 现在这两个字符串只许出现在展开行 .req-detail 里",
    detailBad.length === 0, () => detailBad.length ? [...new Set(detailBad)].slice(0, 3).join(" | ") : "常驻面零命中（协议/设备身份/目录来源/base_url）");

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
const QUOTA_OLD = L('function quotaCell(a) {',
  '  const q = a.quota || {};',
  '  if (q.state === "unknown")',
  '    return `<span style="color:var(--text-faint)" title="未拿到额度缓存（账号尚无物化资源或 ops 未刷新）">—</span>`;',
  '  const n = q.resources?.length || 0;',
  '  const title = `${n} 个关联资源 · 预留 ${q.reserved ?? 0}`;',
  '  const main = q.state === "exhausted"',
  '    ? `<span style="color:var(--warn)">已耗尽</span>`',
  '    : `剩余 ${esc(q.remaining ?? "—")}`;',
  '  return `<span title="${esc(title)}" style="font-variant-numeric:tabular-nums">${main}</span>`;',
  '}');
/** §3 的额度格目标形态：runtime 优先 → 退 a.quota → 无快照写「尚未刷新」。 */
const QUOTA_NEW = L('function quotaCell(a) {',
  '  const rq = a.runtime && a.runtime.quota;',
  '  if (!rq) return `<span style="color:var(--text-faint)" title="运行态里没有额度快照：网关还没查过（BUG-2 的可见态）">尚未刷新</span>`;',
  '  if (rq.state === "available") return `<span>有余量</span><span class="sub">查于 ${esc(shortTime(rq.checked_at))}</span>`;',
  '  if (rq.state === "exhausted") return `<span style="color:var(--warn)">已耗尽</span>`;',
  '  return `<span style="color:var(--text-faint)" title="${esc(rq.detail || "上游未给出额度")}">未知</span>`;',
  '}');
const QUOTA_FIX = [
  { from: L('  const quotaCol = p.accounts.some((a) => a.quota && a.quota.state !== "unknown");'),
    to: L('  const quotaCol = p.accounts.some((a) => (a.runtime && a.runtime.quota) || a.quota);') },
  { from: QUOTA_OLD, to: QUOTA_NEW },
];
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
    // 锚点取卡头与元信息行之间 —— 落点**在 `.card-head` 之外**，专打"他处接入钮"那条分支
    from: L('      ${metaLineHTML(p)}'),
    to: L('      <button class="btn btn-sm" id="ac-add-dup">${PLUS}接入账号</button>',
          '      ${metaLineHTML(p)}') },
  { id: "V4", fix: [...TABLE_FIX, ...QUOTA_FIX], kills: ["V4"],
    // 实测注记：本条只把数据源换回网关池摘要，**措辞仍是四值** → V7 不随行变红（V7 由下面那条专门钉）
    why: "quotaCell 改回只读 a.quota（BUG-1 本体：额度列接到网关池摘要，运行态快照再也不看）",
    from: L('  const rq = a.runtime && a.runtime.quota;'),
    to: L('  const rq = a.quota && a.quota.state !== "unknown" ? {',
          '    state: a.quota.state, checked_at: "", } : null;') },
  { id: "V5", fix: [], kills: ["V5"],
    why: "开关里塞一颗 .dot（用圆点承担开关，frontend-spec.md:524 的禁令本体）",
    from: L('  el.setAttribute("role", "switch");'),
    to: L('  el.setAttribute("role", "switch");',
          '  { const d = document.createElement("span"); d.className = "dot"; el.appendChild(d); }') },
  { id: "V6", fix: TABLE_FIX, kills: ["V6"],
    why: "表头「额度」改名「配额」（§3 是逐字列集，改名即判红）",
    from: L('        <th class="num">额度</th><th class="num">操作</th>'),
    to: L('        <th class="num">配额</th><th class="num">操作</th>') },
  { id: "V7", fix: [...TABLE_FIX, ...QUOTA_FIX], kills: ["V7"],
    why: "第四态「尚未刷新」被折进「未知」（把 BUG-2「网关还没查过」藏成「查了但拿不到」，§3 明令区分）",
    from: L('  if (!rq) return `<span style="color:var(--text-faint)" title="运行态里没有额度快照：网关还没查过（BUG-2 的可见态）">尚未刷新</span>`;'),
    to: L('  if (!rq) return `<span style="color:var(--text-faint)">未知</span>`;') },
  { id: "V8", fix: WORDS_FIX, kills: ["V8"],
    why: "状态文字「启用」写成「正常」（评审 B-2「正常」是第三个谎：status 不含任何凭据有效性事实）",
    // 重定锚：§3 定版措辞「已启用」（与 rail title 的「M 已启用」同口径），锚点只多一个「已」字；
    // 变异后果不变（把那一档写成「正常」→ DOM 可见文本 + 源码字面量两处都会红）。
    from: L('  const stateText = !a.enabled ? "已停用" : unknown ? "状态未知" : "已启用";'),
    to: L('  const stateText = !a.enabled ? "已停用" : unknown ? "状态未知" : "正常";') },
  { id: "V9", fix: ICON_FIX, kills: ["V9"],
    why: "10 个产品全用同一个图标（张冠李戴；V9 存在的意义就是钉「各自用各自产品的 icon」）",
    from: L('            <span class="mark-sm">${productMark(p)}</span>'),
    to: L('            <span class="mark-sm"><img src="/img/products/buddy.png" alt="?"></span>') },
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
  console.log(`\n[变异自证] 真实页面基线：${(baseRun.checks || []).length} 项，红 ${baseRed.length} 项（${baseRed.join(",") || "无"}）`);
  console.log("  🔴 本门是「判据先行」：基线为红是预期态，故每条变异先做**可绿性核验**（见文件头），");
  console.log("     红项先施加最小 fix 编辑（/tmp 副本）转绿，再施加回归变异要求它**必须重新变红**。\n");

  for (const mut of MUTATIONS) {
    let src = baseSrc;
    let stage = "";
    try {
      const before = okOf(baseRun, mut.id);
      if (!before) throw new Error(`判据 ${mut.id} 在基线输出里不存在（判据没跑起来？）`);
      let prevRed = redOf(baseRun);
      if (!before.ok) {
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
  console.log("=".repeat(56));
  console.log(`可红 ${rows.length}/${MUTATIONS.length}${bad.length ? `；${bad.length} 项 BAD` : "；" + rows.length + " 条判据全部可证伪"}`);
  bad.forEach((b) => console.log(`  ✗ ${b}`));
  try { rmSync(work, { recursive: true, force: true }); } catch { /* /tmp 副本清不掉不影响结论 */ }
  return (rows.length === MUTATIONS.length && !bad.length) ? 0 : 1;
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
    R: "渲染现场可达性", V: "设计书 §8 八条判据（v2 结构）", L: "反转的 M6-IX 真机判据",
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
