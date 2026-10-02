#!/usr/bin/env node
/**
 * v2.0 §21 / Q28 前端渲染逻辑实测（不依赖浏览器）+ **变异自证**（验收 IX-5）。
 *
 * 为什么不用 headless Chrome：本机沙箱下 Chrome 加载真实页面会挂住
 * （`--dump-dom` + 真实 URL 超时）。改用 **Node 直接执行前端源码里的真实函数** ——
 * 验证的是**同一份源码**，不是复制品。
 *
 * 用法：
 *   node scripts/verify_v2_frontend.mjs <overview-json>              # 实测
 *   node scripts/verify_v2_frontend.mjs <overview-json> --mutation   # 变异自证
 *
 * 🔴 为什么要 `--mutation`：**永远不会红的断言等于没有断言**。
 * 上一轮有 4 条"绿"实际是假绿（红点文案 / 修复路径 / 熔断行 / "已隐藏"），根因两类：
 * ① 锚点写在 A 文件、断言打在 B 文件的产物上（改了也不红）；
 * ② 负向断言扫错了文件 —— `index.html` 里那句「用 mgw zcode claim 查看详情」
 *    就躲在"只扫 main.js"的判据外面。
 * 现在**每条** check 都在 `MUTATIONS` 里有一个源码变异：变异模式把源码复制到临时目录、
 * 逐条施加、重跑实测，要求指定断言**必须变红**；锚点找不到或出现多次同样判红
 * （"变异锚点过期"是最隐蔽的一种假通过）。
 *
 * 退出码：0 = 全绿；1 = 有失败；2 = 抽取/结构级错误（脚本自身失效，结论无效）
 */
import {
  copyFileSync, mkdirSync, readFileSync, readdirSync, writeFileSync,
} from "node:fs";
import { execFileSync } from "node:child_process";
import { dirname, join, relative, resolve } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

/** 被实测的前端文件（变异模式只复制这几个） */
const FILES = {
  dash: "coding/model_gateway/web/static/js/pages/dashboard.js",
  res: "coding/model_gateway/web/static/js/pages/resources.js",
  models: "coding/model_gateway/web/static/js/pages/models.js",
  apiaccess: "coding/model_gateway/web/static/js/pages/apiaccess.js",
  settings: "coding/model_gateway/web/static/js/pages/settings.js",
  index: "coding/model_gateway/web/static/index.html",
  main: "coding/model_gateway/web/static/js/main.js",
  css: "coding/model_gateway/web/static/css/base.css",
  // 🔴 面板 S-19 escape：指路的**页名**分叉在两侧 —— 前端文案与 Python 文案
  //    （`core/resources.py` 的页名常量、`cli_setup.py` 的成因提示）都会写「X」页。
  //    只扫前端时，把 `ROUTE_POOL_PAGE` 改成一个不存在的页名不会红。
  coreRes: "coding/model_gateway/core/resources.py",
  cliSetup: "coding/model_gateway/cli_setup.py",
  // 🔴 第八轮 B-3：告警文案的**装配地**是 `main.py`（`config_warnings()` 的四条 message
  //    都在那里拼），它不在扫描面里时，硬编码一个坏页名门永远不会响。
  mainPy: "coding/model_gateway/main.py",
  api: "coding/model_gateway/web/static/js/api.js",
  // 门自己的源码也要能被变异（`self: true` 的变异走子进程跑副本）
  gate: "bianyiandhuanjing/scripts/verify_v2_frontend.mjs",
};

/** 递归列文件（跳过 __pycache__ / vendor 第三方包） */
const walkFiles = (dir, keep) => {
  let entries = [];
  try { entries = readdirSync(dir, { withFileTypes: true }); } catch { return []; }
  return entries.flatMap((e) => {
    const p = join(dir, e.name);
    if (e.isDirectory()) return p.includes("__pycache__") || p.endsWith("/vendor")
      ? [] : walkFiles(p, keep);
    return keep(p) ? [p] : [];
  });
};

// 🔴 第九轮 B-3：文案产地由**目录自动发现**，不再手写清单。
//    手写 10 个键时 `pages/logs.js`、`pages/stats.js`、`static/index.html` 的静态文案、
//    `api/admin.py` 的 message 全在面外 —— 把用户指到一个不存在的页面，门照样全绿。
//    新增文件自动入面；变异模式同样会复制这些文件（否则变异无处可施）。
for (const p of [...walkFiles(join(ROOT, "coding/model_gateway"), (x) => x.endsWith(".py")),
                 ...walkFiles(join(ROOT, "coding/model_gateway/web/static/js"), (x) => x.endsWith(".js")),
                 // 🔴 第十轮 B10-7/B10-8：文案还能活在 CSS 与可 HTTP 直达的模板里 ——
                 //    `::after { content: "请前往「模型映射」页" }` 用户看得见，面外就没人红。
                 ...walkFiles(join(ROOT, "coding/model_gateway/web/static/css"), (x) => x.endsWith(".css")),
                 ...walkFiles(join(ROOT, "coding/model_gateway/web/static/templates"), (x) => x.endsWith(".html")),
                 join(ROOT, "coding/model_gateway/web/static/index.html")]) {
  const rel = relative(ROOT, p).split(process.platform === "win32" ? "\\" : "/").join("/");
  if (!Object.values(FILES).includes(rel)) FILES[`copy:${rel}`] = rel;
}

// 🔴 S-46 共享行为层的判据与变异要用稳定的键名。components.js 是**目录自动入面**的
//    （键 = copy: + 相对路径，手写清单漏文件正是第八/九轮的假绿成因），而 apiaccess.js /
//    resources.js 早在具名键里 —— 拿 copy: 前缀去取会取到 undefined（本轮实测撞过一次）。
const COMP_SRC = "copy:coding/model_gateway/web/static/js/components.js";

// HTML 转义口径与前端 `esc()` 一致
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// 🔴 第十轮 ix R-3：`new Function` 编译出的代码住在**本进程全局作用域**里 ——
//    Node 独有的 `process` / `require` / `Buffer` / `setImmediate` 在浏览器里并不存在，
//    于是页面源码里写 `process.env.HOME` 时门照样全绿，用户拿到的是一片空白。
//    现在把被执行的前端源码编译进 **空的 vm 上下文**：那里只有 ECMAScript 内置对象，
//    Node 全局一律取不到，缺什么就以 ReferenceError **真变红**（与浏览器行为一致）。
//    浏览器里本应存在的东西（document/fetch/localStorage…）仍由调用方显式注入形参。
// 🔴 第十二轮 eng-B S-52：**光挡全局名不算沙箱**。宿主函数/对象作为实参进了 realm，
//    就随身带着**宿主的 realm**：`esc.constructor("return process")()` 拿到的是本进程的
//    `Function`，于是页面能读 `process.env.HOME`、能 `console.log` 伪造门的输出 ——
//    这条一旦被利用，`84 项全绿` 与 `可红 109/109` 都是页面自己写的字，门不再可信。
//    现在**一切跨 realm 的值都要过 `__guard`**（在 realm 内编译，所以 guard 自身是 realm 物）：
//    ① 宿主函数 → 换成 realm 里的同名包装（`.constructor` 从此是 realm Function，
//       `new Function("return process")()` 在空上下文里直接 ReferenceError）；
//    ② 宿主对象 → realm `Proxy`，读属性时递归包装，并把 `constructor`/`__proto__`/
//       `prototype` 三个**桥属性**一律返回 undefined（否则 `obj.__proto__.hasOwnProperty
//       .constructor` 同样通向宿主 Function）；
//    ③ 宿主函数的**返回值**也过一遍包装 —— 桥不会只在入口这一侧存在。
//    包装表用 WeakMap 记住，同一宿主对象在同一个 realm 里永远拿到同一个包装，
//    所以假 DOM 的节点身份比较（`nodes["ops-dot"] === 上一次那个`）不受影响。
//    "这道闸到底有没有效"不靠这段注释自证：由 **Z5** 拿着 `INJECTED` 注册表真跑一遍
//    桥探测（可达函数逐个 `f("return typeof process")()`，任何一次拿到非 `undefined` 就红），
//    并由变异表里一条"把 guard 摘掉"的自门变异保证它会红。
const browserFn = (...args) => {
  const body = args[args.length - 1];
  const params = args.slice(0, -1);
  const ctx = vm.createContext({});
  new vm.Script(`globalThis.__guard = (() => {
  const BRIDGE = new Set(["constructor", "__proto__", "prototype"]);
  const cache = new WeakMap();
  const wrap = (v) => {
    if (typeof v !== "object" && typeof v !== "function") return v;
    if (v === null) return v;
    if (cache.has(v)) return cache.get(v);
    if (typeof v === "function") {
      const f = function (...a) { return wrap(v.apply(this, a)); };
      cache.set(v, f);
      return f;
    }
    // 🔴 数组**不能包成 Proxy**：Array.prototype[Symbol.iterator] 之类原生方法要求
    //    receiver 是真数组，包了就是 "called on incompatible receiver"（第一轮试手时
    //    K/I 段 14 条集体红的根因）。输入面（载荷、行集）都是只读的，直接映射成
    //    realm 里的真数组即可。
    if (Array.isArray(v)) {
      const arr = [];
      cache.set(v, arr);            // 先入表再填：自引用数组（A 里含 A）否则无限递归
      for (let i = 0; i < v.length; i += 1) arr.push(wrap(v[i]));
      return arr;
    }
    // 🔴 thenable 同理，而且要**换成 realm 的 Promise**：宿主 Promise 一旦被 Proxy，
    //    页面 await 它就抛 "incompatible receiver"；fetch/GET/POST 全是这条路径。
    if (typeof v.then === "function") {
      const p = new Promise((res, rej) => {
        try { v.then((x) => res(wrap(x)), (e) => rej(e)); } catch (e) { rej(e); }
      });
      cache.set(v, p);
      return p;
    }
    const p = new Proxy(v, {
      get(t, k, r) { if (BRIDGE.has(k)) return undefined; return wrap(Reflect.get(t, k, r)); },
      set(t, k, val) { if (BRIDGE.has(k)) return false; t[k] = val; return true; },
      has(t, k) { return !BRIDGE.has(k) && Reflect.has(t, k); },
      ownKeys(t) { return Reflect.ownKeys(t).filter((k) => !BRIDGE.has(k)); },
      getPrototypeOf() { return Object.prototype; },
    });
    cache.set(v, p);
    return p;
  };
  return wrap;
})();
globalThis.__f = (${params.join(", ")}) => {\n${body}\n};`)
    .runInContext(ctx);
  // 🔴 注册表 = 真的被送进过 realm 的**全部宿主值**（Z5 的覆盖集从这里派生，不是手写名单）
  return (...callArgs) => {
    for (const a of callArgs) INJECTED.push(a);
    return ctx.__f(...callArgs.map((a) => ctx.__guard(a)));
  };
};
const INJECTED = [];

// 🔴 页面函数一抛错就会**带走整轮判据**（第十一轮 eng-B B11-1 的根因）：A/B/C 段的输入是
//    eager 求值的，`configWarnings(...)` 抛错时门自己崩掉，父进程只能靠"崩了算红"推定，
//    于是拿到一个没有证据的 ✓。包一层之后：抛错记一笔 + 返回哨兵串 —— 正向判据（要求含
//    某句话）与反向判据（要求 `=== ""`）都会因为哨兵而红，"有没有抛过错"本身由 Z3 钉住。
const PAGE_THREW = "\u0000PAGE-THREW\u0000";
const PAGE_THROWS = [];
// 🔴 兜网：页代码在 realm **里面**被拒的 promise 不走 `safePageFn` 这条路
//    （L 段的 `copy:` 块直接在 realm 内调 `copyText`）。2026-09-29 主控复采实测：
//    把 `copyText` 的 rejection 分支删掉后，被拒绝的 promise 成了 **unhandled rejection**，
//    Node 默认**直接杀掉整轮**（RC=1、stdout 全空）—— "变异能不能红"退化成"门有没有崩"，
//    正是第十一轮 B11-1 清掉的那类推定分支（崩溃冒充证据）。
//    现在每次未处理拒绝记一笔，Z3 因此红，其余判据照常跑完。
//    A/B 对照（同一条变异，只摘掉兜网）：有兜网 → 判据跑完且 L13/Z3 双红；
//    无兜网 → `子进程 Error，无可判读输出`。所以起作用的是**这一行**，不是 `__guard` 的
//    thenable 包装（我先误记在 `__guard` 头上，复测才分清）。
//    作用域边界：只兜**未处理**的 rejection（页代码自己 catch 掉的照常按原语义走）；
//    不兜未捕获的同步异常 —— 那是门自己的缺陷，应当当场炸出来而不是被静默记一笔。
process.on("unhandledRejection", (reason) => {
  const name = reason && reason.name ? reason.name : "";
  const msg = String((reason && reason.message) || reason || "");
  PAGE_THROWS.push(`未处理的 promise 拒绝 ${name}: ${msg.slice(0, 90)}`);
});
const safePageFn = (label, fn) => (...args) => {
  try {
    const v = fn(...args);
    // 🔴 同步抛错包住了不等于**异步**也包住了（2026-09-29 主控复采实测）：L 段的
    //    `copy:` 块把页面 `copyText` 的 rejection 分支删掉后，被拒绝的 promise 变成
    //    **unhandled rejection**，Node 默认直接**杀掉整轮**（RC=1、stdout 空）——
    //    于是"变异能不能红"退化成"门有没有崩"，正是第十一轮 B11-1 清掉的那类推定分支。
    //    异步页调用一律接一层：记一笔 + 换成哨兵，正向判据（要求含某句话）与
    //    反向判据（要求 `=== ""`）都因此红，"有没有抛过错"仍由 Z3 钉住。
    if (v && typeof v.then === "function") {
      return v.then(undefined, (e) => {
        PAGE_THROWS.push(`${label} 异步 reject ${e && e.name}: ${String(e && e.message).slice(0, 90)}`);
        return PAGE_THREW;
      });
    }
    return v;
  } catch (e) {
    PAGE_THROWS.push(`${label} 抛错 ${e && e.name}: ${String(e && e.message).slice(0, 90)}`);
    return PAGE_THREW;
  }
};

/* ==================== 共享行为层的执行现场（面板 ix B12-1 / S-46） ====================
 * 门此前只真跑了 dashboard.js：api.js 与 components.js 里的**共享行为**一个字节都没执行过。
 * 面板实测三处坏改动门仍 84/84 绿：
 *   ① api.js 的 if (!resp.ok) 改成 if (false) —— 后端真回 400，界面弹**绿色**「配置已保存并热重载生效」；
 *   ② confirmDialog 的取消分支改成 resolve(true) —— 用户点「取消」真的把密钥删了；
 *   ③ copyText 不写剪贴板也 toast「已复制」/ maskVal 改成恒等 —— 明文直接上屏。
 * 所以这里给共享层一套**真跑现场**：把 api.js + components.js 的原源码（去 import/export）
 * 编进 realm，配下面这份假 DOM，四态各喂一次（成功 / 4xx 带后端 message / fetch reject / 非 JSON）。
 *
 * 🔴 假 DOM 为什么写在 **realm 内**（作为源码字符串），而不是像 document/fetch 那样从宿主注入：
 *    节点是**又读又写**的可变对象（页面往它上面挂 onclick、modal 要搬子节点、还要比
 *    e.target === mask 的身份）。宿主节点进 realm 必然过 __guard 的 Proxy，
 *    ① 数组属性会被映射成 realm **副本**（页面往 children 里 push 就丢了），
 *    ② 节点身份在两侧不一致，③ 宿主对象本身还带着宿主 realm 的 constructor（S-52 那条桥）。
 *    在 realm 内自建 DOM 三样都没有，而且**没有任何宿主值跨进来了**。
 * 🔴 这段源码里不得出现反引号（它要被编进模板字符串），字符串一律用引号拼。
 */
const SHARED_DOM = `
const __timers = [];
const __els = Object.create(null);
let fetch = async (p) => { throw new Error("未造 fetch 桩：路径 " + p); };
function __match(n, sel) {
  for (const raw of String(sel).split(",")) {
    const s = raw.trim();
    if (!s) continue;
    if (s.charAt(0) === ".") { if (n.classList.contains(s.slice(1))) return true; }
    else if (s.charAt(0) === "#") { if (n.attrs.id === s.slice(1)) return true; }
    /* 🔴 S-46 第二批补**属性选择器**（[data-tk] / [data-sec] / [name=name] 三种写法，
       含**无引号值**）—— apiaccess.js 与 settings.js 的行内绑定全靠它找控件，原先一律
       匹配不到，于是"页面根本没绑上事件"这种坏改动在 realm 里静默通过。
       纯增量：类 / id / 标签三个分支一字未动，L 段照常跑。 */
    else if (s.charAt(0) === "[") {
      const a = /^\\[([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\]]*)))?\\]$/.exec(s);
      if (!a) continue;
      const k = a[1].toLowerCase();
      const v = a[2] !== undefined ? a[2] : (a[3] !== undefined ? a[3] : a[4]);
      if (v === undefined) { if (n.attrs[k] !== undefined) return true; }
      else if (n.attrs[k] !== undefined && String(n.attrs[k]) === v) return true;
    }
    else if (/^[a-zA-Z][\\w-]*$/.test(s)) { if (n.tagName === s.toUpperCase()) return true; }
  }
  return false;
}
function __ser(n) {
  let at = "";
  for (const k in n.attrs) at += " " + k + '="' + n.attrs[k] + '"';
  let inner = n.ownText;
  for (const c of n.children) inner += __ser(c);
  const t = n.tagName.toLowerCase();
  return "<" + t + at + ">" + inner + "</" + t + ">";
}
const __VOID = { br: 1, img: 1, input: 1, meta: 1, link: 1, hr: 1, path: 1, rect: 1,
  circle: 1, ellipse: 1, line: 1, polyline: 1, polygon: 1, use: 1, source: 1, col: 1 };
/* 🔴 S-46 第二批：真实 DOM 把若干属性**反射**到同名特性上（input.value / input.name /
   button.disabled / el.dataset 等）。页面代码正是这么读的（settings.js:88 读 input.name、
   apiaccess.js:116 读 btn.dataset.on），原先只有 __mk 里几个写死的自有属性：解析出来的
   value="7" / disabled / data-tk="1" 一律读不到，读到的永远是初始空值 ——
   于是"绑定根本没接上"在 realm 里被当成正常渲染。
   反射口径照浏览器：**特性给初值，一旦代码写过就用写进去的值**（has 标记）。
   disabled 按**特性存在即为真**算（裸 disabled 解析出来是空串，仍是真）。 */
const __kebab = (k) => String(k).replace(/[A-Z]/g, (c) => "-" + c.toLowerCase());
function __refl(el, prop, attr, isFlag) {
  let own = null, has = false;
  Object.defineProperty(el, prop, {
    get() {
      if (has) return own;
      const v = el.attrs[attr];
      if (isFlag) return v !== undefined;
      return v === undefined ? "" : v;
    },
    set(v) { has = true; own = isFlag ? !!v : String(v); },
    enumerable: true, configurable: true,
  });
}
function __mk(tag) {
  const el = { tagName: String(tag || "div").toUpperCase(), attrs: {}, children: [],
    parent: null, ownText: "", listeners: {}, hidden: false, style: {} };
  __refl(el, "value", "value", false);
  __refl(el, "name", "name", false);
  __refl(el, "type", "type", false);
  __refl(el, "title", "title", false);
  __refl(el, "disabled", "disabled", true);
  Object.defineProperty(el, "dataset", {
    get() {
      return new Proxy({}, {
        get(t, k) { return typeof k === "string" ? el.attrs["data-" + __kebab(k)] : undefined; },
        set(t, k, v) { el.attrs["data-" + __kebab(k)] = String(v); return true; },
        has(t, k) { return el.attrs["data-" + __kebab(k)] !== undefined; },
        deleteProperty(t, k) { delete el.attrs["data-" + __kebab(k)]; return true; },
        ownKeys() {
          return Object.keys(el.attrs).filter((x) => x.indexOf("data-") === 0)
            .map((x) => x.slice(5).replace(/-([a-z])/g, (m2, c) => c.toUpperCase()));
        },
        getOwnPropertyDescriptor() { return { enumerable: true, configurable: true }; },
      });
    },
    enumerable: false, configurable: true });
  Object.defineProperty(el, "className", {
    get() { return el.attrs.class || ""; },
    set(v) { el.attrs.class = String(v); }, enumerable: false, configurable: true });
  Object.defineProperty(el, "firstChild", {
    get() { return el.children.length ? el.children[0] : null; },
    enumerable: false, configurable: true });
  Object.defineProperty(el, "textContent", {
    get() {
      let t = el.ownText;
      for (const c of el.children) { const s = c.textContent; if (s) t += (t ? " " : "") + s; }
      return t;
    },
    set(v) { el.ownText = String(v); el.children = []; },
    enumerable: false, configurable: true });
  Object.defineProperty(el, "innerHTML", {
    get() { let s = el.ownText; for (const c of el.children) s += __ser(c); return s; },
    set(v) { el.ownText = ""; el.children = []; __parse(String(v), el); },
    enumerable: false, configurable: true });
  el.classList = {
    contains: (c) => (" " + el.className + " ").indexOf(" " + c + " ") >= 0,
    add: (c) => { if (!el.classList.contains(c)) el.className = (el.className + " " + c).trim(); },
    remove: (c) => { el.className = el.className.split(/\\s+/).filter((x) => x && x !== c).join(" "); },
    toggle: (c, force) => {
      const want = force === undefined ? !el.classList.contains(c) : !!force;
      if (want) el.classList.add(c); else el.classList.remove(c);
      return want;
    },
  };
  el.appendChild = (n) => { if (n.parent) n.remove(); n.parent = el; el.children.push(n); return n; };
  el.append = (...ns) => { for (const n of ns) { if (typeof n === "string") el.ownText += n; else el.appendChild(n); } };
  /* 🔴 settings.js:74 的脏态徽章就是 pa.prepend(b) 插到最前面的；原先没有 prepend，
     markDirty 走到那行直接 TypeError —— 徽章永远进不了 DOM（假阴性）。 */
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
  el.__all = () => {
    const out = [];
    for (const c of el.children) { out.push(c); for (const d of c.__all()) out.push(d); }
    return out;
  };
  el.querySelectorAll = (sel) => el.__all().filter((n) => __match(n, sel));
  el.querySelector = (sel) => { const f = el.querySelectorAll(sel); return f.length ? f[0] : null; };
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
      el.attrs[a[1].toLowerCase()] = v;
    }
    stack[stack.length - 1].appendChild(el);
    if (!__VOID[m[2].toLowerCase()] && m[4] !== "/") stack.push(el);
  }
  pushText(html.slice(cur));
}
/* 真壳层 index.html:119-120 就这两个挂载点；别的 id 一律查不到（= 改名会真抛错） */
__els["toast-wrap"] = __mk("div");
__els["modal-root"] = __mk("div");
const document = {
  getElementById: (id) => (__els[id] === undefined ? null : __els[id]),
  createElement: (t) => __mk(t),
  querySelector: (s) => __els["modal-root"].querySelector(s),
  querySelectorAll: (s) => __els["modal-root"].querySelectorAll(s),
  visibilityState: "visible",
};
const navigator = {};
const setTimeout = (fn, ms) => { __timers.push([fn, ms]); return __timers.length; };
const __ev = (type, target) => ({ type, target, currentTarget: target, bubbles: true,
  defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() {} });
const __fire = (el, type) => {
  const e = __ev(type, el);
  const l = el.listeners[type];
  if (l) for (const fn of l.slice()) fn(e);
  if (typeof el["on" + type] === "function") return el["on" + type](e);
  return null;
};
const __fireAt = (el, type, target) => {
  const e = __ev(type, target);
  const l = el.listeners[type];
  if (l) for (const fn of l.slice()) fn(e);
  return e;
};
const __toasts = () => document.getElementById("toast-wrap").children
  .map((c) => ({ text: c.textContent, cls: c.className }));
const __flush = async () => { for (let i = 0; i < 12; i += 1) await Promise.resolve(); };
/* 🔴 页面的一条 D3 操作是 PUT + 重新 GET 全量（apiaccess.js 的 persist → renderApiAccess），
   12 个轮次不够观测到终点；__until 按**条件**排空微任务并交出实际轮次，
   跑不到就在 detail 里报"没等到"，绝不把"没等到"当成"没有副作用"（面板反复批评过）。 */
const __until = async (pred, budget) => {
  const max = budget || 400;
  let n = 0;
  while (!pred() && n < max) { await Promise.resolve(); n += 1; }
  return { done: !!pred(), turns: n, budget: max };
};
/* 一个 promise 到底有没有**返回**（挂死与"返回了但没做事"是两回事，S-61 的教训） */
const __follow = async (p, budget) => {
  let state = "pending";
  if (!p || typeof p.then !== "function") return { state: "not-a-promise", turns: 0 };
  p.then(() => { state = "settled"; }, () => { state = "rejected"; });
  const w = await __until(() => state !== "pending", budget);
  return { state, turns: w.turns, spent: !w.done };
};
/* 🔴 判据不许把「崩了/挂住」当证据：promise 未 settle 也照样要有读数可判 */
const __settle = async (p) => {
  if (!p || typeof p.then !== "function") return { state: "not-a-promise", value: String(p) };
  let st = { state: "pending", value: null };
  p.then((v) => { st = { state: "settled", value: v }; },
    (e) => { st = { state: "rejected", value: String(e && e.message) }; });
  for (let i = 0; i < 12; i += 1) { if (st.state !== "pending") break; await Promise.resolve(); }
  return st;
};
const __reset = () => {
  document.getElementById("modal-root").children.length = 0;
  document.getElementById("toast-wrap").children.length = 0;
};
const __root = () => document.getElementById("modal-root");
const __resp = (ok, status, body, notJson) => ({
  ok, status,
  json: async () => { if (notJson) throw new Error("Unexpected token < in JSON at position 0"); return body; },
});
`;

/* ---- 共享层各场景的 realm 侧驱动（只写事实，判定在门这边） ---- */
const L_SCEN = {
  /* 四态 × 喂给真 api()：成功 / 4xx(errors,error.message,message,detail) / 非 JSON 5xx /
     非 JSON 2xx / fetch reject（网络异常）。每个场景都记 fetch 收到的请求形状。 */
  states: `
const cases = [];
const scen = [
  { name: "200-json", go: () => { fetch = async () => __resp(true, 200, { hello: "world", n: 7 }); } },
  { name: "400-errors", go: () => { fetch = async () => __resp(false, 400, { errors: ["rid 重复：res-a", "models[3].name 必填"] }); } },
  { name: "401-obj", go: () => { fetch = async () => __resp(false, 401, { error: { message: "E 上游 401 invalid_api_key" } }); } },
  { name: "409-msg", go: () => { fetch = async () => __resp(false, 409, { message: "M 配置已被别处改动" }); } },
  { name: "422-detail", go: () => { fetch = async () => __resp(false, 422, { detail: "D 字段校验失败" }); } },
  { name: "500-html", go: () => { fetch = async () => __resp(false, 500, null, true); } },
  { name: "204-nonjson", go: () => { fetch = async () => __resp(true, 204, null, true); } },
  { name: "network", go: () => { fetch = async () => { throw new TypeError("Failed to fetch"); }; } },
];
for (const s of scen) {
  const sent = [];
  s.go();
  const inner = fetch;
  fetch = (p, init) => {
    sent.push({ p, m: init.method || null, ct: (init.headers || {})["Content-Type"] || null,
      b: typeof init.body === "string" ? init.body : "<" + (typeof init.body) + ">" });
    return inner(p, init);
  };
  let got = "NO-RESULT", rejected = false, msg = null, hasData = "none";
  try {
    const v = await api("/admin/api/x", { method: "PATCH", body: "{\\"a\\":1}" });
    got = v === undefined ? "undefined" : JSON.stringify(v);
  } catch (e) {
    rejected = true; msg = String(e.message); hasData = e.data === undefined ? "none" : "yes";
  }
  cases.push({ name: s.name, rejected, msg, got, hasData, sent });
}
return cases;
`,
  methods: `
const sent = [];
fetch = async (p, init) => {
  sent.push({ p, m: init.method || null, ct: (init.headers || {})["Content-Type"] || null,
    b: typeof init.body === "string" ? init.body : "<" + (typeof init.body) + ">" });
  return __resp(true, 200, { id: "tok-1", nested: { n: 3 } });
};
const g = await GET("/admin/api/overview");
const post = await POST("/admin/api/tokens", { name: "Trae", enabled: true });
const put = await PUT("/admin/api/config", { resources: [1, 2] });
return { g, post, put, sent };
`,
  /* 调用方形状照抄 apiaccess.js:31-38 的 persist（PUT + 成功弹绿 / 失败弹红带 e.message） */
  persist: `
fetch = async () => __resp(false, 400, { errors: ["rid 重复：res-a"] });
async function persistLikeProduction(okMsg) {
  try { await PUT("/admin/api/config", { resources: [] }); if (okMsg) toast(okMsg, "ok"); return "ok"; }
  catch (e) { toast("保存失败：" + e.message, "err"); return "err"; }
}
const outcome = await persistLikeProduction("配置已保存并热重载生效");
return { outcome, toasts: __toasts() };
`,
  /* 生产侧形状 = apiaccess.js:130-134：if (!await confirmDialog(...)) return; 才做删除
     🔴 S-61：除了两个按钮，还要走 `modal()` 自带的**两条不经过按钮**的关闭通道
        （✕ `.modal-close`、遮罩 mousedown）—— 旧实现这两条不 resolve，调用方永久挂住。 */
  confirm: `
async function caller(which) {
  __reset();
  const calls = [];
  const p = confirmDialog("删除密钥", "确定删除「Trae」？使用该密钥的工具将立即 401。");
  const root = __root();
  const footEl = root.querySelector(".modal-foot");
  const footBtns = footEl ? footEl.querySelectorAll("button") : [];
  const btns = root.querySelectorAll("button");
  const labels = btns.map((b) => b.textContent);
  const want = which === "cancel" ? "取消" : "确定";
  let target = null, fire = null;
  if (which === "x") {
    target = root.querySelector(".modal-close");
    fire = () => target.onclick(__ev("click", target));
  } else if (which === "mask") {
    target = root.children[0];
    fire = () => __fireAt(target, "mousedown", target);
  } else {
    target = btns.filter((b) => b.textContent.indexOf(want) >= 0)[0];
    fire = () => target.onclick(__ev("click", target));
  }
  if (!target) return { err: "找不到「" + which + "」的关闭入口，实得 " + JSON.stringify(labels) };
  const r = fire();
  if (r && typeof r.then === "function") await r;
  const st = await __settle(p);
  if (st.value) calls.push("DELETE_SENT");
  return { state: st.state, value: String(st.value), calls, open: root.children.length,
    labels, btnCount: btns.length, footBtnCount: footBtns.length,
    footBtnLabels: footBtns.map((b) => b.textContent) };
}
return { cancel: await caller("cancel"), ok: await caller("ok"),
  x: await caller("x"), mask: await caller("mask") };
`,
  copy: `
const out = {};
{ __reset(); const written = [];
  navigator.clipboard = { writeText: (t) => { written.push(t); return Promise.resolve(); } };
  copyText("sk-a1b2c3d4e5f6g7h8", "密钥已复制");
  await __flush();
  out.written = written; out.toasts = __toasts(); }
{ __reset(); const written = [];
  navigator.clipboard = { writeText: (t) => { written.push(t); return Promise.reject(new Error("user denied")); } };
  copyText("sk-zzz", "密钥已复制");
  await __flush();
  out.denyWritten = written; out.denyToasts = __toasts(); }
{ __reset(); navigator.clipboard = undefined;
  copyText("sk-yyyy", "密钥已复制");
  await __flush();
  out.noClipWritten = []; out.noClipToasts = __toasts(); }
{ __reset(); const written = [];
  navigator.clipboard = { writeText: (t) => { written.push(t); return Promise.resolve(); } };
  copyText("https://127.0.0.1:8300/v1");
  await __flush();
  out.defaultToasts = __toasts(); out.defaultWritten = written; }
return out;
`,
  modal: `
const out = {};
{ __reset();
  const foot = document.createElement("div");
  foot.innerHTML = '<button class="btn">取消</button><button class="btn btn-primary">确定</button>';
  const bodyEl = document.createElement("div");
  bodyEl.innerHTML = '<p>正文 <b>粗</b></p>';
  modal({ title: "<script>alert(1)</script>", body: bodyEl, footer: foot, wide: true });
  const mask = __root().children[0];
  const footEl = mask.querySelector(".modal-foot");
  const head = mask.querySelector(".modal-head");
  out.a = { rootKids: __root().children.length, scripts: mask.querySelectorAll("script").length,
    h3: head ? head.querySelector("h3").textContent : null,
    footKids: footEl ? footEl.children.length : -1,
    footTexts: footEl ? footEl.children.map((c) => c.textContent) : [],
    footEmptied: foot.firstChild === null, modalCls: mask.children[0].className,
    bodyKids: mask.querySelector(".modal-body").children.length };
  mask.querySelector(".modal-close").onclick();
  out.afterX = __root().children.length;
}
{ __reset();
  let closed = 0;
  modal({ title: "t", body: document.createElement("div"), onClose: () => { closed += 1; } });
  const mask = __root().children[0];
  __fire(mask, "mousedown");
  out.blankClose = { kids: __root().children.length, closed };
  modal({ title: "t2", body: document.createElement("div") });
  const mask2 = __root().children[0];
  __fireAt(mask2, "mousedown", mask2.children[0]);
  out.innerKids = __root().children.length;
  const m3 = modal({ title: "t3", body: document.createElement("div") });
  out.elIdentity = (m3.el === __root().children[1]) ? "el-ok" : "el-mismatch";
  m3.close();
  out.afterApiClose = __root().children.length;
}
{ __reset();
  modal({ title: "只有标题", body: document.createElement("div") });
  const mask = __root().children[0];
  out.noFooter = { foot: !!mask.querySelector(".modal-foot"), cls: mask.children[0].className };
}
return out;
`,
  sw: `
const one = async (init, ret) => {
  const seen = [];
  const el = switchEl(init, async (next) => { seen.push(next); return ret; });
  const cls0 = el.className;
  await el.onclick(__ev("click", el));
  return { init, ret: String(ret), before: cls0, seen,
    after: el.classList.contains("on"), cls: el.className };
};
const out = {};
out.okTrue = await one(false, true);
out.failFalse = await one(false, false);
out.undef = await one(false, undefined);
out.turnOff = await one(true, true);
{ const el = switchEl(false, null);
  await el.onclick(__ev("click", el));
  out.noToggle = { after: el.classList.contains("on") }; }
return out;
`,
  tabs: `
const switched = [];
const el = tabBar([{ id: "a", label: "时段" }, { id: "b", label: "维度" }], "a", (id) => switched.push(id));
const btns = el.querySelectorAll(".tab");
const b2 = btns[1];
b2.onclick({ type: "click", target: b2, currentTarget: b2 });
const actives = el.querySelectorAll(".tab").filter((x) => x.classList.contains("active"))
  .map((x) => x.textContent);
const pages = [];
const pg = pagination(23, 0, 10, (off) => pages.push(off));
const kids = pg.children.map((c) => ({ tag: c.tagName, text: c.textContent, dis: c.disabled }));
pg.children[2].onclick({ type: "click", target: pg.children[2] });
const pg2 = pagination(23, 20, 10, (off) => pages.push(off));
const kids2 = pg2.children.map((c) => ({ tag: c.tagName, text: c.textContent, dis: c.disabled }));
return { tabs: { count: btns.length, switched, actives, cls: el.className },
  kids, kids2, pages, pagerCls: pg.className };
`,
  inventory: `
return { api: typeof api, GET: typeof GET, PUT: typeof PUT, POST: typeof POST,
  toast: typeof toast, modal: typeof modal, confirmDialog: typeof confirmDialog,
  tabBar: typeof tabBar, switchEl: typeof switchEl, copyText: typeof copyText,
  pagination: typeof pagination, esc: typeof esc };
`,
};

/* ==================== 两个正式页面的真跑现场（S-46 第二批 · M 段） ====================
 * 上一批只把**共享层**（api.js + components.js）接进 realm，六个页面各自的 renderXxx 一个
 * 字都没跑过（那批 §6.1 自己记着）。面板点名的两处谎报形态正长在页面上：
 *   · settings.js 少一行解禁 → 保存按钮永远灰，而脏态徽章照样显示（用户看见「有未保存修改」
 *     却点不动保存 —— 徽章与按钮不同源）；
 *   · apiaccess.js 的操作即保存（D3）到底有没有真发请求 / 点「取消」到底有没有不发。
 * 这里复用同一套 SHARED_DOM，把两个页面的模块体（去 import/export）编进 realm 真跑。
 * 🔴 fixture 不是编的：逐字段抄自生产端点的真回包 —— CONFIG_FIXTURE 来自
 *    `GET /admin/api/config`（resources[].api_key 就是端点默认脱敏后的 "****"），
 *    PUT 的 400 errors 来自 `PUT /admin/api/config` 把 request_total_budget_seconds 改成 1
 *    时的真回包，成功回包 {"status":"ok","message":"配置已保存并生效"} 同样是真取的。
 *    只有**参数取值**被刻意改成互不相同（生产默认 x=2 / y=2 同值，对调不可判别 —— K10 的教训）。
 * 🔴 场景体里不得出现反引号（它们要被编进模板字符串）。
 */
const CONFIG_FIXTURE = {
  gateway: {
    host: "0.0.0.0", port: 8300, max_concurrent_requests: 5, attempt_timeout_seconds: 45,
    request_total_budget_seconds: 300, heartbeat_seconds: 15, retention_days: 7,
    access_tokens: [
      { id: "tok-1", name: "Trae", value: "mg-a1b2c3d4e5f60718293a4b5c6d7e8f90", enabled: true,
        quotas: { daily_requests: 0, daily_tokens: 0, total_tokens: 0 } },
      { id: "tok-2", name: "Cursor", value: "mg-0f1e2d3c4b5a69788796a5b4c3d2e1f0", enabled: false,
        quotas: { daily_requests: 0, daily_tokens: 0, total_tokens: 0 } },
    ],
    zcode: { proxy: "", plan_base_url: "https://zcode.z.ai/api/v1/zcode-plan",
      claim_interval_seconds: 60, claim_cron: "", fingerprint: false },
  },
  scheduling: {
    max_active_per_model: 2, fail_threshold: 3, retry_per_request: 4,
    retry_backoff_seconds: 1.5, quota_retry: 2, quota_backoff_base_seconds: 1,
    cooldown_seconds: 60, cooldown_seconds_plan: 18000,
  },
  error_rules: [],
  resources: [
    { id: "res-a", name: "资源A", vendor: "", preset: "", access_mode: "api", protocol: "openai",
      base_url: "http://127.0.0.1:9/v1", api_key: "****", account: "", product: "", enabled: true },
    { id: "res-b", name: "孤儿资源", vendor: "", preset: "", access_mode: "api", protocol: "openai",
      base_url: "http://127.0.0.1:9/v1", api_key: "****", account: "", product: "", enabled: true },
    { id: "res-c", name: "停用资源", vendor: "", preset: "", access_mode: "api", protocol: "openai",
      base_url: "http://127.0.0.1:9/v1", api_key: "****", account: "", product: "", enabled: false },
    { id: "res-d", name: "资源D", vendor: "", preset: "", access_mode: "api", protocol: "openai",
      base_url: "http://127.0.0.1:9/v1", api_key: "****", account: "", product: "", enabled: true },
  ],
  models: [
    { name: "ok-model", group: "", endpoint: "chat", enabled: true, params: {},
      resources: [{ resource: "res-a", model: "vm-a", reasoning: null }], caps_overrides: {} },
    { name: "empty-model", group: "", endpoint: "chat", enabled: true, params: {},
      resources: [], caps_overrides: {} },
    { name: "shadow-model", group: "", endpoint: "chat", enabled: true,
      params: { reasoning_effort: "max" },
      resources: [{ resource: "res-d", model: "vm-d", reasoning: { enabled: true, effort: "low" } }],
      caps_overrides: {} },
  ],
  pricing: [],
};
// 🔴 生产真回包（探针命令见证据文档 §2）：PUT 校验失败 = 400 {"status":"rejected","errors":[…]}
const PUT_400_BUDGET = ["gateway: Value error, request_total_budget_seconds(1) 必须 "
  + ">= attempt_timeout_seconds(45)（tech-design §4.7 ③）"];
// 同一条 PUT 路由对**密钥改动**的真回包（把两条 access_tokens 的 id 改成重复时端点的原样返回）
const PUT_400_TOKEN = ["Value error, gateway.access_tokens[].id 重复：'tok-1'"];

/* ---- 页面真跑的场景体（服务端假件 env 由 runChecks 侧的 mEnv 注入） ---- */
const M_SCEN = {
  a_render: `
const root = __mk("div");
let err = "";
try { await renderApiAccess(root); }
catch (e) { err = String(e && e.name) + ": " + String(e && e.message); }
const toks = SRV.cfg.gateway.access_tokens;
const rows = [];
for (let i = 0; i < toks.length; i += 1) rows.push(rowView(root, i));
return { err, reqs: reqLines(), tokens: toks, rows, addrs: OV.call_addresses,
  head: (root.querySelector(".value") || {}).textContent,
  addBtn: !!root.querySelector("#a-addkey"),
  copies: root.querySelectorAll("[data-copy]").map((b) => b.attrs["data-copy"]),
  heads: root.querySelectorAll("th").map((x) => x.textContent),
  endpoints: root.querySelectorAll(".endpoint-item").map((x) => x.textContent),
  empty: !!root.querySelector(".empty"), desc: (root.querySelector(".page-desc") || {}).textContent,
  fns: { renderApiAccess: typeof renderApiAccess, persist: typeof persist, draw: typeof draw,
    tokenRow: typeof tokenRow, endpoint: typeof endpoint, addKeyModal: typeof addKeyModal,
    maskVal: typeof maskVal },
  text: root.textContent, html: __ser(root) };
`,
  a_eye: `
const root = __mk("div");
await renderApiAccess(root);
const row = root.querySelectorAll("[data-tk]")[0];
const eye = row.querySelector("[data-tkey]");
const out = { before: rowView(root, 0), icon0: eye.innerHTML, title0: eye.title };
__fire(eye, "click");
await __until(() => (row.querySelector("[data-tkval]").textContent || "").indexOf("****") < 0);
out.shown1 = row.querySelector("[data-tkval]").textContent;
out.icon1 = eye.innerHTML; out.title1 = eye.title; out.on1 = eye.dataset.on;
__fire(eye, "click");
await __flush();
out.after = rowView(root, 0); out.icon2 = eye.innerHTML; out.on2 = eye.dataset.on;
out.html = __ser(root); out.text = root.textContent; out.reqs = reqLines();
out.server = SRV.cfg.gateway.access_tokens[0].value;
return out;
`,
  a_copy: `
const root = __mk("div");
const written = [];
navigator.clipboard = { writeText: (t) => { written.push(t); return Promise.resolve(); } };
await renderApiAccess(root);
__fire(root.querySelectorAll("[data-tk]")[0].querySelector("[data-cpykey]"), "click");
await __until(() => written.length >= 1);
const afterKey = written.slice(); const toastsKey = __toasts();
const addrs = root.querySelectorAll("[data-copy]");
for (const b of addrs) __fire(b, "click");
await __until(() => written.length >= 1 + addrs.length);
return { written, afterKey, toastsKey, toasts: __toasts(), reqs: reqLines(),
  addrVals: addrs.map((b) => b.attrs["data-copy"]),
  serverKey: SRV.cfg.gateway.access_tokens[0].value, noClip: written.length };
`,
  a_switch: `
const root = __mk("div");
if (FAIL) SRV.putFails = FAIL;
await renderApiAccess(root);
const i = WANT;
const rowOld = root.querySelectorAll("[data-tk]")[i];
const sw = rowOld.querySelector("[data-tksw]").children[0];
const beforeOn = sw.classList.contains("on");
const p = __fire(sw, "click");
/* 等待口径：persist 无论成败都会重渲染 —— 行节点被换掉就是"界面已跟着服务端刷新" */
const w = await settle(() => root.querySelectorAll("[data-tk]")[i] !== rowOld, 300);
const f = await __follow(p, 200);
return { i, beforeOn, wait: w, follow: f, reqs: reqLines(), put: puts(),
  after: rowView(root, i), head: (root.querySelector(".value") || {}).textContent,
  server: SRV.cfg.gateway.access_tokens[i].enabled, toasts: __toasts(),
  moduleCfg: cfg.gateway.access_tokens[i].enabled };
`,
  a_name: `
const root = __mk("div");
await renderApiAccess(root);
const inp = root.querySelectorAll("[data-tk]")[0].querySelector("[data-tkname]");
const name0 = inp.value;
inp.value = "Trae 改过";
__fire(inp, "change");
const w = await settle(() => SRV.cfg.gateway.access_tokens[0].name === "Trae 改过", 300);
const put = puts();
const newName = root.querySelectorAll("[data-tk]")[0].querySelector("[data-tkname]").value;
const n0 = SRV.reqs.length;
const inp2 = root.querySelectorAll("[data-tk]")[1].querySelector("[data-tkname]");
inp2.value = SRV.cfg.gateway.access_tokens[1].name;
__fire(inp2, "change");
await settle(() => SRV.reqs.length > n0, 30);
return { name0, put, newName, w, reqs: reqLines(), sameValueNewReqs: SRV.reqs.length - n0,
  toasts: __toasts(), server: SRV.cfg.gateway.access_tokens[0].name };
`,
  a_add: `
const root = __mk("div");
await renderApiAccess(root);
const footBtns = () => {
  const mask = __root().children[0];
  const foot = mask ? mask.querySelector(".modal-foot") : null;
  return foot ? foot.querySelectorAll("button") : [];
};
__fire(root.querySelector("#a-addkey"), "click");
await __flush();
const m0 = __root().children[0];
const open = { title: m0 ? (m0.querySelector(".modal-head") || {}).textContent : null,
  labels: footBtns().map((b) => b.textContent),
  hasNameBox: !!(m0 && m0.querySelector("[name=name]")),
  hint: m0 ? (m0.querySelector(".modal-body") || {}).textContent : null };
const cancel = footBtns().filter((b) => b.textContent === "取消")[0];
__fire(cancel, "click");
await __flush();
const afterCancel = { reqs: reqLines(), putN: SRV.reqs.filter((r) => r.m === "PUT").length,
  rows: root.querySelectorAll("[data-tk]").length, open: __root().children.length,
  toasts: __toasts(), server: SRV.cfg.gateway.access_tokens.length };
__fire(root.querySelector("#a-addkey"), "click");
await __flush();
const mask = __root().children[0];
mask.querySelector("[name=name]").value = "Cherry Studio";
const ok = footBtns().filter((b) => b.textContent.indexOf("生成并添加") >= 0)[0];
__fire(ok, "click");
const w = await settle(() => root.querySelectorAll("[data-tk]").length === 3, 300);
return { open, afterCancel, w, okLabel: ok ? ok.textContent : null,
  reqs: reqLines(), put: puts(), rows: root.querySelectorAll("[data-tk]").length,
  row2: rowView(root, 2), head: (root.querySelector(".value") || {}).textContent,
  server: SRV.cfg.gateway.access_tokens, openAfter: __root().children.length,
  toasts: __toasts() };
`,
  a_del: `
const root = __mk("div");
await renderApiAccess(root);
const drive = async (which) => {
  __reset();
  const want = which === "ok" ? "确定" : "取消";
  const n0 = SRV.reqs.length;
  const rows0 = root.querySelectorAll("[data-tk]").length;
  const delEl = root.querySelectorAll("[data-tk]")[0];
  if (!delEl) return { which, err: "表里已经没有行了（rows=0，前面某一支把密钥删光了）" };
  const del = delEl.querySelector("[data-delkey]");
  const p = __fire(del, "click");
  await __flush();
  const mask = __root().children[0];
  if (!mask) return { which, err: "点删除后没有弹确认框" };
  let acted;
  if (which === "x") acted = __fire(mask.querySelector(".modal-close"), "click");
  else if (which === "mask") acted = __fireAt(mask, "mousedown", mask);
  else {
    const btn = mask.querySelectorAll("button").filter((b) => b.textContent === want)[0];
    if (!btn) return { which, err: "确认框里没有「" + want + "」按钮",
      labels: mask.querySelectorAll("button").map((b) => b.textContent) };
    acted = __fire(btn, "click");
  }
  if (acted && typeof acted.then === "function") await acted;
  const f = await __follow(p, which === "ok" ? 300 : 60);
  return { which, title: (mask.querySelector(".modal-head") || {}).textContent,
    bodyText: (mask.querySelector(".modal-body") || {}).textContent, follow: f,
    sent: SRV.reqs.slice(n0).map((x) => x.m + " " + x.path),
    put: SRV.reqs.slice(n0).filter((x) => x.m === "PUT").map((x) => x.body),
    rows0, rows: root.querySelectorAll("[data-tk]").length, open: __root().children.length,
    server: SRV.cfg.gateway.access_tokens.map((t) => t.id), toasts: __toasts() };
};
const out = {};
for (const which of ["cancel", "x", "mask", "ok"]) out[which] = await drive(which);
return out;
`,
  s_render: `
const root = __mk("div");
let err = "";
try { await renderSettings(root); }
catch (e) { err = String(e && e.name) + ": " + String(e && e.message); }
const save = root.querySelector("#st-save");
return { err, reqs: reqLines(), dirty: dirty, saveMissing: !save,
  ins: root.querySelectorAll("[data-sec]").map((x) => ({ sec: x.dataset.sec, name: x.name,
    value: x.value, type: x.type, min: x.attrs.min })),
  saveDisabled: save ? save.disabled : null, saveText: save ? save.textContent : null,
  badge: !!root.querySelector(".badge"), badges: root.querySelectorAll(".badge").length,
  heads: root.querySelectorAll(".card-title").map((x) => x.textContent),
  restart: !!root.querySelector("#st-restart"), stopBtn: !!root.querySelector("#st-stop"),
  hasExport: root.textContent.indexOf("导出") >= 0, text: root.textContent, html: __ser(root) };
`,
  s_dirty: `
const root = __mk("div");
await renderSettings(root);
const snap = () => ({ badge: !!root.querySelector(".badge"),
  badges: root.querySelectorAll(".badge").length,
  disabled: root.querySelector("#st-save").disabled, dirty: dirty,
  reqs: SRV.reqs.length, badgeText: (root.querySelector(".badge") || {}).textContent });
const s0 = snap();
const inp3 = root.querySelector("[name=cooldown_seconds]");
inp3.value = "";
__fire(inp3, "input");
const cleanedEmpty = inp3.value;
__fire(inp3, "change");
await __flush();
const sClean = snap();
const cooldownAfterClear = cfg.scheduling.cooldown_seconds;
const inp = root.querySelector("[name=fail_threshold]");
inp.value = "12a3-.x9";
__fire(inp, "input");
const cleaned = inp.value;
inp.value = "7";
__fire(inp, "change");
await __until(() => dirty === true, 40);
const s1 = snap();
const badgeNode = root.querySelector(".badge");
const firstKid = root.querySelector(".page-actions").children[0];
inp.value = "8";
__fire(inp, "change");
await __flush();
const s2 = snap();
return { s0, sClean, s1, s2, cleaned, cleanedEmpty, cooldownAfterClear,
  yInCfg: cfg.scheduling.fail_threshold, badgeIsFirst: firstKid === badgeNode,
  reqs: reqLines(), headOrder: root.querySelector(".page-actions").children.map((c) => c.textContent) };
`,
  s_save: `
const root = __mk("div");
await renderSettings(root);
const inp = root.querySelector("[name=fail_threshold]");
inp.value = "7";
__fire(inp, "change");
await __until(() => dirty === true, 40);
const before = { reqs: reqLines(), put: SRV.reqs.filter((r) => r.m === "PUT").length };
__fire(root.querySelector("#st-save"), "click");
/* 徽章只在**重渲染之后**才消失（save 成功 → draw 走 dirty=false 分支） */
const w = await settle(() => SRV.reqs.length >= 3 && !root.querySelector(".badge"), 300);
return { before, w, reqs: reqLines(), put: puts(), server: SRV.cfg.scheduling.fail_threshold,
  badge: !!root.querySelector(".badge"), disabled: root.querySelector("#st-save").disabled,
  dirty: dirty, val: root.querySelector("[name=fail_threshold]").value, toasts: __toasts(),
  inputs: root.querySelectorAll("[data-sec]").length };
`,
  s_savefail: `
const root = __mk("div");
await renderSettings(root);
SRV.putFails = FAIL;
const inp = root.querySelector("[name=request_total_budget_seconds]");
inp.value = "1";
__fire(inp, "change");
await __until(() => dirty === true, 40);
__fire(root.querySelector("#st-save"), "click");
const w = await settle(() => __toasts().length >= 1, 300);
return { w, reqs: reqLines(), put: puts(), serverBudget: SRV.cfg.gateway.request_total_budget_seconds,
  toasts: __toasts(), badge: !!root.querySelector(".badge"),
  disabled: root.querySelector("#st-save").disabled, dirty: dirty,
  val: root.querySelector("[name=request_total_budget_seconds]").value };
`,
  s_stop: `
const root = __mk("div");
await renderSettings(root);
const drive = async (which) => {
  __reset();
  const n0 = SRV.reqs.length;
  const stopBtn = root.querySelector("#st-stop");
  if (!stopBtn) return { which, err: "页面上已没有「停止网关」按钮，当前页面文本："
    + JSON.stringify(String(root.textContent).slice(0, 60)) };
  const p = __fire(stopBtn, "click");
  await __flush();
  const mask = __root().children[0];
  if (!mask) return { which, err: "点停止网关后没有弹确认框" };
  const want2 = which === "cancel" ? "取消" : "确定";
  const btn = mask.querySelectorAll("button").filter((b) => b.textContent === want2)[0];
  if (!btn) return { which, err: "没有「" + want2 + "」按钮" };
  __fire(btn, "click");
  const f = await __follow(p, 200);
  await __until(() => SRV.reqs.length > n0, 40);
  return { which, title: (mask.querySelector(".modal-head") || {}).textContent,
    bodyText: (mask.querySelector(".modal-body") || {}).textContent, follow: f,
    sent: SRV.reqs.slice(n0).map((x) => x.m + " " + x.path), open: __root().children.length,
    toasts: __toasts(), stopped: root.textContent.indexOf("网关已停止") >= 0,
    keptCards: root.querySelectorAll(".card").length };
};
return { cancel: await drive("cancel"), ok: await drive("ok") };
`,
  s_restart: `
const root = __mk("div");
await renderSettings(root);
const p = __fire(root.querySelector("#st-restart"), "click");
await __flush();
const mask = __root().children[0];
if (!mask) return { err: "点重启网关后没有弹确认框" };
const btn = mask.querySelectorAll("button").filter((b) => b.textContent === "确定")[0];
if (!btn) return { err: "确认框里没有「确定」钮，脚钮=" + JSON.stringify(mask.querySelectorAll("button").map((b) => b.textContent)) };
__fire(btn, "click");
await settle(() => __toasts().length >= 1, 60);
const box = root.querySelector("#st-exec");
return { title: (mask.querySelector(".modal-head") || {}).textContent,
  sent: SRV.reqs.map((x) => x.m + " " + x.path), toasts: __toasts(),
  waiting: box ? box.style.opacity : null, timers: __timers.length,
  follow: await __follow(p, 20) };
`,
};


/* ==================== 实测：对给定 root 跑一遍全部判据 ==================== */

async function runChecks(root, overviewPath) {
  const read = (key) => readFileSync(resolve(root, FILES[key]), "utf-8");
  const checks = [];
  const errors = [];
  // 🔴 断言求值**不得**把异常漏给外层：变异模式若靠"跑崩了"来算红，等于用崩溃冒充证据。
  //    这里把每条断言单独包起来 —— 求值抛错 = 该条红（并记下异常名，便于区分"判据失效"与"被测代码坏了"）。
  const check = (id, name, ok, detail = "") => {
    let passed = false, note = "", promise = null;
    try {
      const v = typeof ok === "function" ? ok() : ok;
      // detail 允许是惰性函数（值要在判据跑完后才知道）；先求值再决定要不要打印
      try { note = typeof detail === "function" ? detail() : detail; }
      catch { note = "(detail 求值失败)"; }
      if (v && typeof v.then === "function") {
        // 🔴 异步判据（要跑一段真代码才能判定）**必须 await**：
        // `!!Promise` 恒为 true，直接收下就是一条永远不会红的空过判据。
        const row = { id, name, ok: false, detail: note, pending: v };
        checks.push(row);
        return;
      }
      passed = !!v;
    } catch (e) {
      passed = false;
      note = `求值抛错 ${e && e.name}: ${String(e && e.message).slice(0, 120)}`;
    }
    checks.push({ id, name, ok: passed, detail: note });
  };

  const dashSrc = read("dash");
  const cwFn = dashSrc.match(/function configWarnings\(warnings\)\s*\{[\s\S]*?\n\}/);
  const badgeFn = dashSrc.match(/function statusBadge\(r\)\s*\{[\s\S]*?\n\}/);
  const tblFn = dashSrc.match(/function resourceHealthTable\(resources\)\s*\{[\s\S]*?\n\}/);
  const fmtFn = dashSrc.match(/function fmtCooldown\(ms\)\s*\{[\s\S]*?\n\}/);
  if (!cwFn) errors.push("未能从 dashboard.js 抽取 configWarnings（改名/删除？）");
  if (!badgeFn) errors.push("未能从 dashboard.js 抽取 statusBadge");
  if (!tblFn) errors.push("未能从 dashboard.js 抽取 resourceHealthTable");
  if (!fmtFn) errors.push("未能从 dashboard.js 抽取 fmtCooldown（徽章与冷却列的共同口径）");
  if (errors.length) return { checks, errors };

  const configWarnings = safePageFn("configWarnings(warnings)",
    browserFn("esc", `${cwFn[0]}; return configWarnings;`)(esc));
  const statusBadge = safePageFn("statusBadge(row)",
    browserFn("esc", `${fmtFn[0]}\n${badgeFn[0]}; return statusBadge;`)(esc));
  const renderTable = safePageFn("resourceHealthTable(rows)",
    browserFn("esc",
      `${fmtFn[0]}\n${badgeFn[0]}\n${tblFn[0]}\nreturn resourceHealthTable;`)(esc));
  const overview = JSON.parse(readFileSync(overviewPath, "utf-8"));

  /* ---------- A · 配置告警横幅（§21 出口① / Q28-②③）---------- */
  const html = configWarnings(overview.warnings);
  const hiddenHits = (html.match(/已从 \/v1\/models[^。]{0,40}?隐藏/g) || []).length;
  check("A1", "渲染出 .alert-warn 横幅", html.includes('class="alert alert-warn"'));
  // 🔴 A2~A9 判的是"后端文案**原样到达 DOM**"；文案本身对不对归 pytest（后端拼的那部分）
  check("A2", "文案透传：含 503", html.includes("503"));
  check("A3", "文案透传：含「未被任何系统模型引用」", html.includes("未被任何系统模型引用"));
  check("A4", "含「已从 /v1/models …隐藏」（Q28-②）", hiddenHits >= 1);
  check("A5", "两类隐藏说明各一句（零映射 + 不可服务）", hiddenHits >= 2, `命中 ${hiddenHits}`);
  check("A6", "含推理优先级说明「请求级」（Q28-③）", html.includes("请求级"));
  check("A7", "覆盖告警点名系统模型", /「[\w.-]+」参数卡/.test(html));
  check("A8", "覆盖告警给出两侧具体值", html.includes("=max") && html.includes("默认 low"));
  check("A9", "覆盖告警指到可操作页面", html.includes("「网关模型管理」页"));
  check("A10", "每条告警各渲染一条横幅",
    (html.match(/alert-warn/g) || []).length === (overview.warnings || []).length,
    `banners=${(html.match(/alert-warn/g) || []).length} warnings=${(overview.warnings || []).length}`);
  check("A11", "空 warnings → 不渲染任何横幅", configWarnings([]) === "");
  check("A12", "warnings 非数组 → 安全降级不抛", configWarnings(undefined) === "");
  // 🔴 判别式：四类 kind **各自**都要能渲染（防"某一类被渲染器吞掉"这种整屏假绿）
  const kinds = ["model_without_resource", "resource_without_model", "model_unservable",
    "param_shadowed"];
  const synth = configWarnings(kinds.map((k, i) => ({ kind: k, message: `哨兵${i}-${k}` })));
  check("A13", "四类 kind 各渲染一条（无被吞类别）",
    (synth.match(/alert-warn/g) || []).length === kinds.length && synth.includes("哨兵"),
    `banners=${(synth.match(/alert-warn/g) || []).length}/${kinds.length}`);
  check("A14", "告警文案经 HTML 转义",
    configWarnings([{ kind: "model_without_resource", message: "<script>x</script>" }])
      .includes("&lt;script&gt;"));

  /* ---------- B · 资源健康表（§17 熔断原因的唯一可见出口）---------- */
  const benchRow = (overview.resources || []).find((r) => r.rid === "res-a")
    || { rid: "res-a", name: "资源A", status: "cooldown", in_flight: 0, C: 1, models: 1,
         cooldown_remaining_ms: 1799000, last_error: "ZCode 风控熔断（30min，全局）" };
  const tbl = renderTable([benchRow, { rid: "res-x", name: "健康资源", status: "active",
                                       models: 1, C: 0, in_flight: 0,
                                       cooldown_remaining_ms: 0, last_error: null }]);
  const rows = tbl.split("<tr>").filter((x) => x.includes("<td"));
  check("B1", "表头有「最近错误」列（design-spec §2.1）", /<th[^>]*>\s*最近错误/.test(tbl));
  check("B2", "表头有「冷却剩余」列", /<th[^>]*class="num"[^>]*>\s*冷却剩余/.test(tbl));
  check("B3", "熔断原因在 td 正文里（不能只在 title 属性）",
    /<td[^>]*>[^<]*风控熔断[^<]*<\/td>/.test(tbl), String(benchRow.last_error));
  check("B4", "冷却剩余带单位秒", /<td[^>]*class="num"[^>]*>\s*\d+s\s*<\/td>/.test(tbl));
  check("B5", "无错误资源显示占位符而非空白",
    /<td[^>]*class="ellip"[^>]*>[^<]*—\s*<\/td>/.test(tbl));
  // 🔴 E-1 补漏：把表格里对 statusBadge 的调用换成硬编码绿标，原判据一条都不会响
  //    （C1~C7 只单测函数本身，B1~B6 只看列/文案）—— 这条断言"表格真的用了它"。
  // 🔴 面板 S-18 ESCAPE-1：`configWarnings(data.warnings)` 被改成
  //    `configWarnings(data.warnings.filter(...))` 时，A 段全部判据照样绿
  //    —— 因为它们都**直接调函数**，没人检查页面上的调用点交出了什么。
  check("A15", "总览把**整份** warnings 交给渲染器（调用点不筛类别）", () => {
    const call = (dashSrc.match(/configWarnings\(([^)]*)\)/g) || [])
      .map((x) => x.replace(/\s/g, ""));
    const real = call.filter((x) => !x.startsWith("configWarnings(warnings)"));
    return real.length > 0
      && real.every((x) => /^configWarnings\(data\.warnings\)$/.test(x));
  });
  check("B7", "资源健康表逐行调用 statusBadge（不是硬编码徽章）", () => {    const seen = [];
    // 注意**不注入** badgeFn 源码：`function statusBadge` 的声明会遮蔽同名形参，
    // 注入了就测不到"表格是否真的调用它"（这正是面板 E-1 逃逸的成因）
    // 只替换 statusBadge 这一个绑定（故不注入 badgeFn 源码——同名 function 声明会遮蔽形参）
    const spyTable = browserFn("esc", "fmtCooldown", "statusBadge",
      `${fmtFn[0]}\n${tblFn[0]}\nreturn resourceHealthTable;`)(
      esc, (ms) => { const n = Math.ceil((ms || 0) / 1000); return n > 0 ? `${n}s` : "—"; },
      (r) => { seen.push(r.rid); return `<span class="badge b-x">${r.status}</span>`; });
    const out = spyTable([benchRow, { rid: "res-x", name: "健康", status: "active", models: 1,
                                      C: 0, in_flight: 0, cooldown_remaining_ms: 0,
                                      last_error: null }]);
    return seen.length === 2 && out.includes("b-x");
  });
  check("B6", "每行单元格数 = 表头列数（防空列错位）",
    rows.length === 2 && rows.every((r) =>
      (r.match(/<td/g) || []).length === (tbl.match(/<th[ >]/g) || []).length),
    // 注：`<thead>` 也以 `<th` 开头，故表头列数按 `<th `/`<th>` 计数（否则恒多算一列）
    `行=${rows.length} 列=${(tbl.match(/<th[ >]/g) || []).length} ` +
    `每行单元格=${rows.map((r) => (r.match(/<td/g) || []).length).join(",")}`);

  /* ---------- C · 状态徽章四态（验收 IX-4 / S-19）---------- */
  // 🔴 可见文案与 title 必须**分开判**：只看 `html.includes("模型名无效")` 时，
  //    把文案改成英文枚举 `invalid` 而 title 里还留着"该模型名无效"的变异不会红
  //    —— 用户看到的是文案，不是属性。
  const visible = (h) => h.replace(/<[^>]*>/g, "");
  // 🔴 没有 `title=` 时返回哨兵而不是空串：空串会让"title 里不许出现 X"这类**反向**判据
  //    在"根本没有 title"的情况下白过（第十二轮 ix B12-6 的同族缺省 fail-open）。
  const NO_TITLE = "\u0000无 title\u0000";
  const titleOf = (h) => (h.match(/title="([^"]*)"/) || ["", NO_TITLE])[1];
  // 🔴 fixture 必须是**生产行的形状**（第七轮 ix 的逃逸③）：`statusBadge` 一旦按
  //    `r.account` / `r.C` / `r.name` 分叉出第二套文案，缺字段的假行永远走"好分支"，
  //    C 段全部判据照样绿 —— 而真实载荷里那些字段是有值的。
  const FULL = { rid: "res-a", name: "资源A", vendor: "SenseTime", account: "acct-a",
                 C: 3, in_flight: 1, models: 2,
                 last_error: "ZCode 风控熔断（30min，全局），至 15:30" };
  const mkRow = (over) => ({ ...FULL, status: "active", available: true,
                              cooldown_remaining_ms: 0, ...over });
  const fmtCooldown = safePageFn("fmtCooldown(ms)",
    browserFn(`${fmtFn[0]}; return fmtCooldown;`)());
  const b = {
    active: statusBadge(mkRow({ available: true })),
    cooldown: statusBadge(mkRow({ status: "cooldown", available: false,
                                  cooldown_remaining_ms: 61000 })),
    invalid: statusBadge(mkRow({ status: "invalid", available: false })),
    disabled: statusBadge(mkRow({ status: "disabled", available: false })),
  };
  check("C1", "active → 绿标 + 人话「可用」", b.active.includes("b-ok")
    && visible(b.active) === "可用", b.active);
  check("C2", "cooldown → 冷却标 b-cool + 人话「冷却中」，**不得**说成「停用」",
    b.cooldown.includes("b-cool") && visible(b.cooldown) === "冷却中"
    && !b.cooldown.includes("停用"), b.cooldown);
  check("C3", "invalid（404 模型名无效）→ 红标 + 文案直说模型名无效 + 指对页面 + **不提换 Key**",
    b.invalid.includes("b-err") && visible(b.invalid) === "模型名无效"
    // 🔴 归属由控件决定（第十一轮 PM B-11-1）：添加/更换映射的入口 `#rv-addmap`
    //    在「接入模型资源」页，「网关模型管理」页只有档位/优先级/移除映射。
    && titleOf(b.invalid).includes("「接入模型资源」页")
    // 🔴 禁的是"换 Key"这件事的任何写法（第七轮 ix 逃逸②：只禁字面「更换 Key」时，
    //    改成「也可先换 Key 重试」就蒙过去了 —— 而那正是 404 场景下的错处置）
    && !/换\s*(?:Key|key|密钥|api[_ ]?key)/.test(titleOf(b.invalid))
    && titleOf(b.invalid).includes("不会自愈"), b.invalid);
  // 🔴 C17 · 同一行两格不许互相打脸（第十二轮 PM B-12-2）：「最近错误」写着
  //    "确认无风控后删除该文件"，徽章却报"1800s 后自动回池，无需处理" —— 用户会等着，
  //    而实际上不删文件永远不会放开。需要人工确认的冷却，徽章措辞必须跟上。
  const bUnknown = statusBadge(mkRow({ status: "cooldown", available: false,
    cooldown_remaining_ms: 120000,
    last_error: "熔断状态文件读不动（until_ms 类型不对（str：1770000000000）"
      + "）→ 按熔断拒跑；确认无风控后删除 /data/circuit.json 即可解除" }));
  const bNormal = statusBadge(mkRow({ status: "cooldown", available: false,
    cooldown_remaining_ms: 61000, last_error: "上游 429 限流" }));
  check("C17", "未知档冷却徽章说「需人工确认」并指向「最近错误」列；普通冷却仍说「无需处理」",
    titleOf(bUnknown).includes("需人工确认") && !/无需处理/.test(titleOf(bUnknown))
    && titleOf(bUnknown).includes("「最近错误」列") && titleOf(bNormal).includes("无需处理"),
    `未知档=${titleOf(bUnknown)}；普通档=${titleOf(bNormal)}`);

  check("C4", "disabled → 文案「已停用」并在 title **同时给出两种成因与各自处置**（S-19 严重项）",
    visible(b.disabled) === "已停用" && titleOf(b.disabled).includes("资源开关已关闭")
    && titleOf(b.disabled).includes("401") && titleOf(b.disabled).includes("更换 Key")
    && titleOf(b.disabled).includes("「最近错误」列"), b.disabled);
  // 🔴 S-18：四态都得是中文人话，英文枚举直出等于让用户自己猜
  check("C9", "四态文案无英文枚举残留（active/cooldown/invalid 不得直出）",
    ![b.active, b.cooldown, b.invalid, b.disabled].some(
      (x) => />(active|cooldown|invalid)</.test(x)), JSON.stringify(b));
  check("C5", "四态的**样式类与文案**都互不相同（兜底分支不得吃掉冷却/失效）",
    new Set([b.active, b.cooldown, b.invalid, b.disabled]).size === 4
    && new Set([b.active, b.cooldown, b.invalid, b.disabled]
      .map((x) => (x.match(/badge (b-\w+)/) || [])[1])).size === 4, JSON.stringify(b));
  check("C6", "cooldown 徽章带剩余秒数与恢复口径（多久回池、要不要动手）",
    b.cooldown.includes("61s") && b.cooldown.includes("自动回池")
    && b.cooldown.includes("无需处理"), b.cooldown);
  check("C7", "未知状态原样显示（不静默归为正常）",
    statusBadge({ status: "weird", available: false }).includes("weird"));
  // 🔴 S-18：未知状态**不得染红** —— 红 = "需要关注"，用户会读成"凭据被判死"
  check("C10", "未知状态用中性样式（不冒充判死）",
    !statusBadge({ status: "weird", available: false }).includes("b-err"));
  check("C11", "冷却已到期（remaining=0）不说「剩余 0s」",
    !statusBadge({ status: "cooldown", available: false, cooldown_remaining_ms: 0 })
      .includes("剩余 0s"));
  // 🔴 本轮复采发现（变异自证 108/109 里那条"纹丝不动"）：**到期分支的文案没人管**。
  //    `已到期，下次选路即回池` 改成 `稍后自动回池`（用户读成"还得再等一会儿"）门全绿 ——
  //    C6/C12 走的是 `remaining>0` 那一支，C11 只钉住"不说剩余 0s"，钉不住
  //    "到期这件事有没有说出口、有没有留一个还要等的口径"。
  const expiredTitle = titleOf(statusBadge(mkRow({ status: "cooldown", available: false,
                                                   cooldown_remaining_ms: 0 })));
  check("C18", "冷却已到期（remaining=0）要说清「已到期 + 下次选路即回池」，不得残留倒计时或「还要等」口径",
    expiredTitle.includes("已到期") && expiredTitle.includes("下次选路即回池")
    && !/\d+s\s*后/.test(expiredTitle) && !/稍后|需等待|再等|还要等/.test(expiredTitle),
    expiredTitle);
  // 🔴 S-19：徽章与「冷却剩余」列必须同源同口径，且非冷却行不得显示秒数
  check("C12", "徽章 title 与「冷却剩余」列用同一个格式化口径", () => {
    const html2 = renderTable([benchRow]);
    const cell = (html2.match(/<td class="num" style="[^"]*">([^<]*)<\/td>/g) || [])
      .map((x) => x.replace(/<[^>]+>/g, "")).filter((x) => /s$|^—$/.test(x));
    const title = (statusBadge(benchRow).match(/title="([^"]*)"/) || ["", ""])[1];
    return cell.length > 0 && cell.every((x) => x !== "—"
      ? title.includes(x) : !/\d+s 后自动回池/.test(title));
  });
  check("C13", "非 cooldown 的行「冷却剩余」列一律显示 —（不与徽章打架）", () => {
    const html2 = renderTable([{ rid: "res-d", name: "停用但有剩余", status: "disabled",
                                 models: 1, C: 0, in_flight: 0,
                                 cooldown_remaining_ms: 1766000, last_error: "上游 401" }]);
    return /—<\/td>\s*<td class="ellip"/.test(html2) && !/1766s/.test(html2);
  });
  check("C14", "未知状态文案里保留原值且用中性样式（已含在 C7/C10，此处钉 title 说明）",
    statusBadge({ status: "quota_window_flipped", available: false })
      .includes("未识别的状态值"));
  // 🔴 第七轮 ix 逃逸①：`fmtCooldown` 由 ceil 改成 floor 时，徽章与「冷却剩余」列
  //    **仍然自相一致**（C12 只比对一致性），fixture 又多半是整秒 → 门全绿。
  //    取整方向本身是产品判据："还剩 0.1 秒"要说 1s，不能报 0s 让用户以为已到。
  check("C15", "冷却剩余一律**向上取整**（不得把未满一秒报成 0s，也不得截短）",
    fmtCooldown(1799999) === "1800s" && fmtCooldown(61001) === "62s"
    && fmtCooldown(1) === "1s" && fmtCooldown(0) === "—",
    [1799999, 61001, 1, 0].map((ms) => `${ms}→${fmtCooldown(ms)}`).join(" "));
  // 🔴 第七轮 ix 逃逸③：徽章必须是 `status`（+冷却时长）的**纯函数**。
  //    按账号/名称/连续失败数分叉文案，就会有两套措辞在同一列里随机出现。
  check("C16", "徽章只由 status + 冷却时长决定（按其它字段/按量级分叉即判红）", () => {
    // 🔴 第八轮 B-5/B-13：两点纯度测试看不见"按具体值分叉"（`r.account === "主账号"`）
    //    也看不见"按 ms 量级分叉"（120≤ms<1800 用 floor 分钟）—— 所以这里是**矩阵**：
    //    每个状态都要在 4 组字段形态 × 4 个冷却量级上给出**逐字节相同**的输出。
    const variants = [
      mkRow({}),
      { rid: "res-z", name: "另一个资源", vendor: "DeepSeek", account: "", C: 0,
        in_flight: 5, models: 0, last_error: null },
      { rid: "res-q", name: "带中文 名", vendor: "Kimi", account: "主账号", C: 9,
        in_flight: 0, models: 7, last_error: "上游 401：invalid_api_key" },
      { rid: "res-r", name: "X", vendor: "商汤", account: "acct-b", C: 1,
        in_flight: 2, models: 1, last_error: "带 <script> 标签与 '引号' 的原文" },
      // 🔴 第十轮 B10-6：真实上游的 429 原文常到 70~200 字，矩阵必须覆盖**长度维**，
      //    否则 `if (err.length > 40)` 这种分叉永远看不见（同一列出两种说法）。
      { rid: "res-long", name: "长错误原文资源", vendor: "DeepSeek", account: "acct-long",
        C: 7, in_flight: 3, models: 4,
        last_error: "上游 429：Your account is rate limited, please reduce the request "
          + "frequency and try again later. Request id: 021758498273640ac4b9c1f7e0a3d2 "
          + "—— 已按退避策略冷却，稍后会自动回池，无需人工处理。" },
    ];
    const mags = [0, 1, 61000, 1799999, 3600000];
    for (const st of ["active", "cooldown", "invalid", "disabled"]) {
      const first = statusBadge({ ...variants[0], status: st, available: st === "active",
                                  cooldown_remaining_ms: 61000 });
      if (!first) return false;
      for (const v of variants) {
        for (const ms of mags) {
          // 🔴 `available` 同样要正交（第九轮 B-7）：徽章只准看 `status` + 冷却时长。
          //    聚合口径里 `available === false` 覆盖全部非 active 态，
          //    一旦有人拿它分叉文案，同一状态就会出现两种说法。
          for (const av of [true, false]) {
            const out = statusBadge({ ...v, status: st, available: av,
                                      cooldown_remaining_ms: ms });
            // 冷却态允许钟点随时长变化；其它状态的钟点必须完全一致
            if (st !== "cooldown") {
              if (out !== first) return false;
            } else {
              const base = statusBadge({ ...variants[0], status: st, available: false,
                                         cooldown_remaining_ms: ms });
              if (out !== base) return false;
            }
          }
        }
      }
    }
    return true;
  }, JSON.stringify(b));
  // 🔴 E-3 补漏：面板用真实生产载荷打出 `cooldown + remaining=0`（后端懒翻转），
  //    渲染出绿标 active —— 原 fixture 的 cooldown 恒 >0，这个形态从来没有载荷。
  check("C8", "cooldown 且剩余 0ms 时不得归正为绿标", () => {
    const z = statusBadge({ status: "cooldown", available: false, cooldown_remaining_ms: 0 });
    return !z.includes("b-ok") && z.includes("b-cool");
  });

  /* ---------- D · 资源编辑器字段继承（静态）---------- */
  const promote = read("res").match(/async function promoteKeyDraft[\s\S]*?\n}/);
  check("D1", "promoteKeyDraft 存在", !!promote);
  if (promote) {
    check("D2", "新增 Key 继承 product（漏传会被后端默认成空 = 静默丢字段）",
      /product:\s*first\.product/.test(promote[0]));
    check("D3", "同组字段一并继承（vendor/preset/access_mode/protocol）",
      /vendor:\s*first\.vendor/.test(promote[0]) && /preset:\s*first\.preset/.test(promote[0])
      && /access_mode:\s*first\.access_mode/.test(promote[0]));
  }

  /* ---------- E · 顶栏红点的 DOM 契约（index.html）---------- */
  const indexSrc = read("index");
  const dotTag = (indexSrc.match(/<button[^>]*id="ops-dot"[^>]*>/) || [""])[0];
  check("E1", "存在 #ops-dot 元素", !!dotTag);
  check("E2", "默认 hidden（0 失败时不显示）", /hidden/.test(dotTag));
  check("E3", "存在文案节点 #ops-dot-text", indexSrc.includes('id="ops-dot-text"'));
  // 🔴 IX-M-5 的文案位**包括**红点的 title（上一轮只扫 main.js → 假绿）
  check("E4", "红点 title 与副作用一致（说「确认」不说「查看」）",
    !/查看/.test(dotTag) && /确认/.test(dotTag), dotTag);

  /* ---------- F · 红点轮询与副作用（main.js）---------- */
  const mainSrc = read("main");
  check("F1", "轮询 /admin/api/status", mainSrc.includes('GET("/admin/api/status")'));
  check("F2", "读取 ops_failed_unread", mainSrc.includes("ops_failed_unread"));
  check("F3", "5s 轮询间隔", mainSrc.includes("setInterval(poll, 5000)"));
  check("F4", "页面隐藏时跳过轮询", mainSrc.includes('visibilityState === "hidden"'));
  check("F5", "已导入 GET（否则运行时报错）",
    /import\s*\{[^}]*\bGET\b[^}]*\}\s*from\s*"\.\/api\.js"/.test(mainSrc));
  check("F6", "红点按计数显隐（两个方向都写）",
    /dot\.hidden = false;/.test(mainSrc) && /dot\.hidden = true;/.test(mainSrc));
  check("F7", "点击红点真的 POST 确认（不是只弹提示）",
    mainSrc.includes('POST("/admin/api/ops/ack")'));

  /* ---------- I · 红点**行为**（直接执行 main.js 里那段真实代码）----------
   * 🔴 面板 E-2 的成因：F1~F7 全是"`某串在文件里出现过`"，
   * 在点击处理器首行插一句 `return;` 也能全绿 —— 名字承诺的是行为，判据却只做文本包含。
   * 这里把整段红点逻辑抽出来，配假 DOM 真跑一遍：轮询参数、显隐翻转、点击副作用
   * 全部按**可观察的调用**断言。 */
  const dotBlock = mainSrc.match(/\{\n  const dot = document\.getElementById\("ops-dot"\);[\s\S]*?\n\}/);
  check("I0", "能抽取红点逻辑整块（抽不到=结构被改，本节后继判据失去意义）", !!dotBlock);
  if (dotBlock) {
    const runDot = async ({ unread = 0, visible = true, withDot = true, click = false } = {}) => {
      const calls = { GET: [], POST: [], toast: [], intervals: [] };
      const el = (id) => (withDot || id !== "ops-dot")
        ? { id, hidden: true, textContent: "", listeners: {},
            addEventListener(ev, fn) { this.listeners[ev] = fn; } }
        : null;
      const nodes = {};
      const document = {
        visibilityState: visible ? "visible" : "hidden",
        getElementById: (id) => (nodes[id] ||= el(id)),
      };
      const GET = async (path) => { calls.GET.push(path); return { ops_failed_unread: unread }; };
      const POST = async (path) => { calls.POST.push(path); return { ok: true }; };
      const toast = (msg) => calls.toast.push(msg);
      const setInterval = (fn, ms) => { calls.intervals.push([fn, ms]); return 1; };
      browserFn("document", "GET", "POST", "toast", "setInterval", dotBlock[0])(
        document, GET, POST, toast, setInterval);
      // 🔴 等**宏任务边界**而不是单个微任务：代码现在跑在独立 vm realm 里，
      //    await 一个跨 realm 的 promise 比同 realm 多几个微任务 tick，
      //    `await Promise.resolve()` 会让我们在半完成状态下判定（I1 因此在沙箱化后变红）。
      const flush = () => new Promise((r) => setTimeout(r, 0));
      await flush();
      if (click && nodes["ops-dot"]?.listeners?.click) {
        await nodes["ops-dot"].listeners.click();
        await flush();
      }
      return { calls, nodes };
    };
    check("I1", "有未读失败 → 红点去 hidden 并写明条数",
      () => runDot({ unread: 3 }).then(({ nodes }) => nodes["ops-dot"].hidden === false
        && /3/.test(nodes["ops-dot-text"].textContent)));
    check("I2", "无未读 → 红点保持 hidden",
      () => runDot({ unread: 0 }).then(({ nodes }) => nodes["ops-dot"].hidden === true));
    check("I3", "轮询打的是 /admin/api/status 且读 ops_failed_unread",
      () => runDot({ unread: 1 }).then(({ calls }) => calls.GET.includes("/admin/api/status")));
    check("I4", "轮询间隔 5000ms",
      () => runDot({ unread: 1 }).then(({ calls }) =>
        calls.intervals.some(([, ms]) => ms === 5000)));
    check("I5", "页面隐藏时不发请求",
      () => runDot({ unread: 2, visible: false }).then(({ calls }) => calls.GET.length === 0));
    check("I6", "点击 = 确认（POST ack）且立即隐藏红点",
      () => runDot({ unread: 2, click: true }).then(({ calls, nodes }) =>
        calls.POST.includes("/admin/api/ops/ack") && nodes["ops-dot"].hidden === true));
    check("I7", "点击后给出去看明细与重跑的真实指路",
      () => runDot({ unread: 2, click: true }).then(({ calls }) =>
        calls.toast.some((t) => t.includes("ops-results") && t.includes("python -m model_gateway.cli"))));
    check("I8", "红点元素不存在时静默跳过（首屏未就绪不得抛错）",
      () => runDot({ unread: 1, withDot: false }).then(({ calls }) => calls.GET.length === 0));
    // 🔴 "只有点击才确认"才是真判据：只测"点击会 POST"的话，加载即 POST 也能全绿
    check("I9", "未经点击绝不 POST 确认（否则每 5s 自动吞掉用户的失败）",
      () => runDot({ unread: 3 }).then(({ calls }) => calls.POST.length === 0));
  }

  /* ---------- G · 红点文案与指路 ---------- */
  check("G1", "toast 把副作用说成「重跑」而不是「查看详情」",
    !/claim`?\s*查看/.test(mainSrc) && /重跑用 mgw zcode claim/.test(mainSrc));
  check("G2", "指到已落盘的逐条原因（ops-results jsonl）",
    mainSrc.includes("ops-results-*.jsonl"));
  check("G3", "给出未装 mgw 时的等价命令", mainSrc.includes("python -m model_gateway.cli zcode claim"));

  /* ---------- H · 样式（base.css）---------- */
  const cssSrc = read("css");
  check("H1", ".ops-dot 样式存在", cssSrc.includes(".ops-dot {"));
  check("H2", "用双主题令牌（--err-bg），不写死颜色",
    /\.ops-dot \{[\s\S]{0,400}background: var\(--err-bg\)/.test(cssSrc));

  /* ---------- J · 指路的页名必须真存在（面板 S-19 escape：页名 ↔ 导航标签交叉核对）----------
   * 「到『资源池设置』页更换映射」这类指路文案散在 4 处（前端徽章、Python 告警、
   * `mgw setup` 成因提示、页名常量）。页名一旦改版（Q24 就把「系统模型」改成
   * 「资源池设置」），漏改的那一处会把用户指向一个**不存在的页面**，而此前没有任何
   * 判据把"文案里的页名"和"侧栏里的页名"放在一起对过。 */
  const navAnchors = [...indexSrc.matchAll(
    /<a\b[^>]*data-page="([^"]+)"[^>]*>([\s\S]*?)<\/a>/g)]
    // 「模板预览」的演示项复用同一个 `data-page="templates"`，不是真页面 → 不参与同名核对
    .filter((m) => !m[0].includes('data-tpl'));
  const navLabels = new Map(navAnchors.map((m) => {
    const spans = [...m[2].matchAll(/<span>([^<]*)<\/span>/g)].map((s) => s[1].trim());
    return [m[1], spans.length ? spans[spans.length - 1] : ""];
  }));
  const metaBlock = mainSrc.match(/const PAGE_META = \{([\s\S]*?)\n\};/);
  const metaTitles = metaBlock
    ? Object.fromEntries([...metaBlock[1].matchAll(
        /(\w+):\s*\{[^}]*title:\s*"([^"]+)"/g)].map((m) => [m[1], m[2]]))
    : {};
  check("J1", "侧栏标签与路由注入的页标题同源（PAGE_META.title === 侧栏 <span>）", () => {
    if (!metaBlock) return false;
    const pages = [...navLabels.keys()];
    return pages.length >= 7
      && pages.every((p) => navLabels.get(p) === metaTitles[p])
      && Object.keys(metaTitles).every((p) => navLabels.has(p));
  }, `nav=${navLabels.size} meta=${Object.keys(metaTitles).length} `
     + [...navLabels].map(([p, l]) => `${p}:${l !== metaTitles[p] ? `≠${metaTitles[p]}` : "✓"}`).join(","));
  // 注释里的页名不是用户看得见的文案：先剥块注释，再跳过整行注释
  // 🔴 剥注释必须是**结构性的**（第八轮 B-4）：原先按"行首是 `//`/`#`/`*`"判注释，
  //    于是多行模板字符串里以这些字符开头的**可见文案行**会被整行删掉 ——
  //    那句指路用户看得见，判据却当它不存在。现在按字符扫：模板串/字符串内部的
  //    `#`、`//` 一律是正文；只有代码态里的注释才剥。
  const stripComments = (raw) => {
    // HTML 注释先整块去掉：`index.html` / `templates/*.html` 里的 `<!-- -->` 不是用户
    // 看得见的文案（第十一轮起 HTML 也进文案产地面，注释不剥就会拿开发者说明当指路判红）
    const src = String(raw).replace(/<!--[\s\S]*?-->/g, "")
      .replace(/"""[\s\S]*?"""/g, "").replace(/'''[\s\S]*?'''/g, "");
    let out = "", i = 0;
    const n = src.length;
    let mode = "code";            // code | line | block | squote | dquote | template
    let depth = 0;                // 模板串 ${} 里又回到代码态
    const tplStack = [];
    while (i < n) {
      const two = src.slice(i, i + 2);
      if (mode === "line") {
        if (two[0] === "\n") { mode = tplStack.length ? "template" : "code"; out += two[0]; i++; }
        else i++;
        continue;
      }
      if (mode === "block") {
        if (two === "*/") { i += 2; mode = tplStack.length ? "template" : "code"; }
        else { if (src[i] === "\n") out += "\n"; i++; }
        continue;
      }
      if (mode === "squote" || mode === "dquote") {
        const q = mode === "squote" ? "'" : '"';
        if (src[i] === "\\") { out += src.slice(i, i + 2); i += 2; continue; }
        out += src[i];
        if (src[i] === q) mode = "code";
        i++;
        continue;
      }
      if (mode === "template") {
        if (src[i] === "\\") { out += src.slice(i, i + 2); i += 2; continue; }
        if (src[i] === "`") { mode = tplStack.pop() || "code"; out += src[i]; i++; continue; }
        if (two === "${") { tplStack.push(mode); mode = "code"; depth++; out += two; i += 2; continue; }
        out += src[i]; i++; continue;
      }
      // code 态
      if (two === "//") { mode = "line"; i += 2; continue; }
      if (two === "/*") { mode = "block"; i += 2; continue; }
      if (src[i] === "`") { tplStack.push("code"); mode = "template"; out += src[i]; i++; continue; }
      if (src[i] === "'") { mode = "squote"; out += src[i]; i++; continue; }
      if (src[i] === '"') { mode = "dquote"; out += src[i]; i++; continue; }
      if (src[i] === "}" && depth > 0 && tplStack.length) { depth--; mode = "template"; }
      out += src[i]; i++;
    }
    return out.split("\n")
      // Python 侧：整行 `#` 开头是注释；三引号块是 docstring（写给维护者看的，
      // 不是用户可见文案 —— 但生产消息都是普通字符串，不会被这条误伤）
      .filter((l) => !/^\s*#/.test(l)).join("\n");
  };
  // 「」/『』 带括号，与**不带括号的"到 X 页"**（第八轮 B-7）都要认
  const PAGE_REFS = (src) => {
    const withBracket = [...src.matchAll(/[「『]([^「」『』]{2,12})[」』]\s*页/g)].map((m) => m[1]);
    const bare = [...src.matchAll(/(?:到|前往|请到|打开|去|进入|跳到)\s+?([\u4e00-\u9fa5A-Za-z0-9 ]{2,12}?)\s*页/g)]
      .map((m) => m[1])
      // 只认"看起来像页名"的裸串：排除"这一页/该页/那个页"等指示代词与已带括号的重叠
      .filter((x) => !/^[这那该本此全各]|^\s*$/.test(x));
    // 🔴 第九轮 B-4：两条正则都强制以「页」结尾 —— 把"页"字删掉（`请到「模型映射」为…`）
    //    就全绿，而那句指路里的死页名（Q24 已把「系统模型」改名「资源池设置」）照样坑用户。
    //    所以：**cue 动词后紧跟的括号串**本身就是候选页名，不要求出现"页"字。
    const CUE = "(?:到|前往|请到|请打开|打开|去|进入|跳到|切换至|导航至)";
    const cued = [...src.matchAll(new RegExp(CUE + "\\s*[「『]([^「」『』]{2,12})[」『]", "g"))]
      .map((x) => x[1])
      // 「＋ 添加模型资源」这类按钮文案不是页名：要求串内只有文字/数字/空格
      .filter((x) => /^[\u4e00-\u9fa5A-Za-z0-9 ]{2,12}$/.test(x));
    return [...new Set([...withBracket, ...bare, ...cued])];
  };
  const copySources = {};
  for (const [key, rel] of Object.entries(FILES)) {
    if (!key.startsWith("copy:")) continue;         // 具名键由其它判据各自使用
    copySources[rel] = read(key);
  }
  // 具名产地同样在面内（同一份内容，别因为键名不同就漏掉）
  for (const key of ["dash", "res", "models", "apiaccess", "settings", "main", "index",
                     "coreRes", "cliSetup", "mainPy", "api", "css"]) {
    copySources[FILES[key]] = read(key);
  }
  // 「」与『』两种书名号都要认（第七轮 ix 逃逸⑤：只认「」时，写成『模型映射』页就漏检）
  const PAGE_REF = /[「『]([^「」『』]{2,12})[」』]\s*页/g;
  const pageRefs = (src) => PAGE_REFS(stripComments(src));
  check("J2", "可见文案里出现的「X」页都是真实导航项（页名改版不留旧指路）", () => {
    const labels = new Set([...navLabels.values()].filter(Boolean));
    const bad = [];
    let total = 0;
    for (const [name, src] of Object.entries(copySources)) {
      for (const page of pageRefs(src)) {
        total += 1;
        if (!labels.has(page)) bad.push(`${name}→${page}`);
      }
    }
    // `total >= 8`：抽取判据本身失效（正则/文件被改坏）时不得当成"零违规"放过
    return total >= 8 && bad.length === 0;
  }, "违规指路：" + (() => {
    const labels = new Set([...navLabels.values()].filter(Boolean));
    const bad = [];
    for (const [name, src] of Object.entries(copySources)) {
      for (const page of pageRefs(src)) if (!labels.has(page)) bad.push(`${name}→「${page}」页`);
    }
    return bad.join(", ") || "无";
  })() + " 指路总数：" + Object.entries(copySources)
    .filter(([n, src]) => pageRefs(src).length > 0)
    .map(([n, src]) => `${n}:${pageRefs(src).length}`).join(",")
    + ` ｜入面文件=${Object.keys(copySources).length}`);

  // 🔴 J3 · 指路的**归属**必须由控件派生（第十一轮 PM B-11-1 + ix B11-6）：
  //    J2 只证明"那一页存在"，而用户需要的是"那一页真的长着我照提示要按的按钮"。
  //    所有权表不手写：每条动作绑一个源码里真实存在的**控件标记**（id / 函数名），
  //    拥有该动作的页 = 页面实现文件里含该标记的那一页。
  //    本轮的坏改动正是：「资源池设置」页在导航里真实存在（J2 全绿），
  //    但"添加/更换映射"的 `#rv-addmap` 只在 resources.js —— 指过去用户找不到按钮。
  const ROUTE_MARKERS = [
    { action: /(?:添加|新增|更换|新建)[^，。；、「」()]{0,10}映射/, control: "rv-addmap" },
    { action: /(?:更换|换)\s*(?:Key|key|密钥)/, control: "rv-addkey" },
    { action: /(?:打开|启用)[^，。；、「」()]{0,6}(?:开关|资源)/, control: "rv-toggle" },
    { action: /(?:移除映射|档位|优先级)/, control: "poolRows" },
  ];
  let __j3 = "";
  // Python 侧的指路是**常量拼出来的**（`f"到{RESOURCE_PAGE}启用对应资源"`），源码里
  // 根本没有「X」页字面 —— 先把页名常量还原成字面值，否则第十一轮那种
  // "错指路写在 main.py / cli_setup.py"的形态在门侧完全看不见。
  const pageConsts = {};
  for (const m of read("coreRes").matchAll(/^([A-Z_]*PAGE[A-Z_]*)\s*=\s*"([^"]+)"/gm)) {
    pageConsts[m[1]] = m[2];
  }
  const expandPageConsts = (name, src) => (name.toLowerCase().endsWith(".py")
    ? src.replace(/\{([A-Z_]*PAGE[A-Z_]*)\}/g, (x, k) => pageConsts[k] || x)
    : src);
  check("J3", "「到 X 页做 Y」的指路：Y 的控件必须真的长在 X 页的实现文件里（归属派生）",
    () => {
      const byLabel = new Map([...navLabels].map(([k, l]) => [l, k]));
      const cache = new Map();
      const bodyOf = (page) => {
        const key = byLabel.get(page);
        if (!key) return null;                       // 未知页名：J2 负责
        if (!cache.has(key)) {
          try { cache.set(key, readFileSync(join(root, "coding/model_gateway/web/static/js/pages",
                                                 `${key}.js`), "utf-8")); }
          catch { cache.set(key, ""); }
        }
        return cache.get(key);
      };
      const bad = [];
      let seen = 0;
      for (const [name, src] of Object.entries(copySources)) {
        const text = expandPageConsts(name, stripComments(src));
        for (const m of text.matchAll(/[「『]([^「」『』]{2,10})[」』]页/g)) {
          // 分句只到**边界**为止：模板串结束符 `<`、句号、分号、换行、括号（括号里是
          // 解释而不是"到这一页要做的事"，例如「总览」页那处「（凭据失效需换 Key）」），
          // 以及 Python 的行尾 `#` 注释（常量定义行的注释不是用户看得见的文案，
          // 否则会把下一段代码里的"优先级"当成指路承诺的动作 —— 第一版就误伤过）
          const raw = text.slice(m.index, m.index + 60);
          const cut = raw.search(/[<。;\n#（(]/);
          const clause = cut < 0 ? raw : raw.slice(0, cut);
          for (const { action, control } of ROUTE_MARKERS) {
            if (!action.test(clause)) continue;
            seen += 1;
            const body = bodyOf(m[1]);
            if (body !== null && !body.includes(control)) {
              bad.push(`${name}：说「${clause.replace(/\s+/g, "").slice(0, 26)}」`
                       + `却指「${m[1]}」页，而那一页的实现文件里没有 ${control}`);
            }
          }
        }
      }
      __j3 = `派生命中 ${seen} 条指路；${bad.join(" | ") || "归属全部对得上"}`;
      // seen 下限：抽取本身坏掉（正则/文件被改）时不得把"零违规"当成通过
      return seen >= 4 && bad.length === 0;
    }, () => __j3);

  /* ---------- K · 整页装配**可达性**（第八轮 B-1/B-9/B-12）----------
   * A/B/C 段全部是"直接调用函数"—— 函数本身写对了，但**调用点没接进页面**
   * （被注释掉、包进 `<!-- -->`、放进死分支、改了名）时一条都不会红：
   * 第七轮 ix 把 `configWarnings(...)` 包进 HTML 注释，15 条 A 段判据照样全绿。
   * 这里**执行真实的 `renderDashboard`**（假 DOM 接住 innerHTML），
   * 判据下在**页面产出的 HTML** 上 —— 红点段 I0~I9 已经证明这条路能堵死这类逃逸。 */
  const toModuleBody = (src) => src
    .replace(/^\s*import\s+[\s\S]*?from\s+"[^"]*";\s*$/gm, "")
    .replace(/^\s*export\s+(async\s+function|function|const|let|var|class)\b/gm, "$1");
  // 载荷里带 HTML/引号的哨兵：转义必须在**页面产出**上被验一次（第九轮 B-5）。
  const SENTINEL = `<img src=x onerror=alert(1)>"哨兵"<script>`;
  let pageHtml = "", sentinelHtml = "", chartHtml = "";
  let renderErr = "", sentinelErr = "";

  const renderPage = async (payload) => {
    const nodes = {};
    const fakeDocument = {
      getElementById: (id) => (nodes[id] ||= { id, innerHTML: "", style: {} }),
      querySelectorAll: () => [],
      createElement: (tag) => ({ tag, style: {}, setAttribute() {}, appendChild() {} }),
    };
    const storage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
    const makeRender = browserFn("fetch", "document", "window", "localStorage",
      `${toModuleBody(read("api"))}\n${toModuleBody(read("dash"))}\nreturn renderDashboard;`);
    // 🔴 第九轮 B-1：假 fetch **按路径分派**。原先无视路径一律回 fixture，
    //    于是把 `GET("/admin/api/overview")` 改成 `GET("/admin/api/panel")`
    //    （后端根本没有那个路由，生产上整屏空白）门照样"渲染成功"。
    const known = { "/admin/api/overview": payload };
    const fetchStub = async (path) => {
      const key = String(path).split("?")[0];
      if (!(key in known)) {
        return { ok: false, status: 404, json: async () => ({ errors: [`无此端点：${key}`] }) };
      }
      return { ok: true, status: 200, json: async () => known[key] };
    };
    const render = makeRender(fetchStub, fakeDocument,
      { localStorage: storage, matchMedia: () => ({ matches: false }) }, storage);
    const root = { innerHTML: "" };
    await render(root);
    return { html: root.innerHTML || "", nodes };
  };
  try {
    const r1 = await renderPage(JSON.parse(readFileSync(overviewPath, "utf-8")));
    pageHtml = r1.html;
    chartHtml = (r1.nodes["hour-chart"] && r1.nodes["hour-chart"].innerHTML) || "";
  } catch (e) {
    renderErr = `${e && e.name}: ${String(e && e.message).slice(0, 180)}`;
  }
  try {
    const base = JSON.parse(readFileSync(overviewPath, "utf-8"));
    base.warnings = [...(base.warnings || []),
      { kind: "model_without_resource", message: SENTINEL }];
    sentinelHtml = (await renderPage(base)).html;
  } catch (e) {
    sentinelErr = `${e && e.name}: ${String(e && e.message).slice(0, 180)}`;
  }

  // 🔴 第九轮 B-2：「DOM 里有这段文本」不等于「用户看得见」。做一次**结构化可见性清洗**：
  //    丢掉 `hidden` / `aria-hidden="true"` / `display:none` / `visibility:hidden` 的元素
  //    **及其整棵子树**，丢掉注释与 `<script>`/`<style>` 正文，并且**属性里的文本不计入**
  //    （"把正文塞进 title=" 正是原先整族判据看不见的动作）。
  const VOID_TAGS = new Set(["br", "img", "input", "meta", "link", "hr",
    "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "use", "source"]);
  // 🔴 隐藏写法按**属性语义**判，不按字面串巧合（第十轮 ix B10-1/B10-3）：
  //    ① 属性名大小写不敏感（`STYLE="DISPLAY: NONE"`、`ARIA-HIDDEN="TRUE"`）；
  //    ② 裸 `hidden` / 裸 `aria-hidden`（HTML 规范里出现即为真）都算隐藏；
  //    ③ "看着就没有内容"的样式也算：display:none / visibility:hidden|collapse /
  //       opacity:0 / height:0 / 位移出屏（left:-9999px）/ scale(0)。
  //    `class="alert hidden"` 这种**类名里带 hidden** 不算 —— 那要按属性解析才不误伤。
  // 属性名/值**成对解析**（第十轮 ix：`class="… hidden"` 里的 "hidden" 是字面巧合，
  // 判据不能靠"属性串里出现过 hidden" —— 那样既会误伤也会与真属性撞车）
  const parseAttrs = (raw) => {
    const out = [];
    const re = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*(?:=\s*(?:"([^"]*)"|'([^']*)'|([^\s>"']+)))?/g;
    let m;
    while ((m = re.exec(String(raw || ""))) !== null) {
      out.push([m[1].toLowerCase(), String(m[2] ?? m[3] ?? m[4] ?? "")]);
    }
    return out;
  };
  // 🔴 样式表层叠（第十一轮 PM B-11-3 + ix B11-1）：只看内联属性的 `isInvisible`
  //    本质上只是"更长的隐藏写法白名单"。浏览器里看不见从来不只由内联 style 决定 ——
  //    `base.css` 里加一行 `.alert-warn{display:none}`，四条配置告警在真 Chrome 里
  //    高度全为 0、`body.innerText` 从 856 字掉到 459 字，而门 81 项全绿。
  //    更直接的是：**本项目自己就用工具类**（`base.css` 的 `.hidden{display:none!important}`，
  //    `logs.js:151` 的折叠行真在用）—— 所以"类名里带 hidden 不算隐藏"这条第十轮判据
  //    对本项目是错的。可见性必须按 内联属性 ⊕ 样式表命中的选择器 一起算。
  const HIDE_DECL = /(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*(?:hidden|collapse)|opacity\s*:\s*0(?:\.0+)?\s*(?:!important)?\s*(?:;|$)|max-height\s*:\s*0(?:px)?\s*(?:;|$)|font-size\s*:\s*0(?:px)?\s*(?:;|$)|color\s*:\s*transparent|clip-path\s*:\s*inset\(|zoom\s*:\s*0|(?:left|right)\s*:\s*-\d{3,}px|transform\s*:\s*(?:scale\(0\)|translate\(-\d{3,}px))/;
  const hidesIn = (decls) => HIDE_DECL.test(decls)
    || (/(^|;)\s*height\s*:\s*0(px|rem|em|%)?\s*(;|$)/.test(decls)
        && /overflow\s*:\s*hidden/.test(decls));
  const cssHiding = (css) => {
    // 🔴 第十二轮 ix B12-3：上一版注释写"含 @media"，实现却把 at-rule 整块跳过
    //    （`sel = atRule !== 0 ? "" : head` 让 @media 里的规则一律拿不到选择器）——
    //    面板把这个函数单独切出来跑探针，派生集只剩 `classes=["hidden"]`，
    //    `.alert-warn{display:none}` 藏进 @media 就完全查不出来，而 Chrome 里告警真的看不见。
    //    现在按**栈**分两类：`@media`/`@supports`/`@layer` 是透明的（里面的规则照常参与判定），
    //    只有 `@keyframes`/`@font-face`/`@property` 整块跳过（关键帧的 opacity:0 不是隐藏）。
    //    三条误伤排除（每条都在这份样式表里真实存在，不排就是假红）：
    //    ① 伪类/伪元素最右段（`.nav-item.active::after{display:none}` 藏的是装饰层）；
    //    ② 后代选择器里的裸标签（`.nav-item span{display:none}` 只在那一条窄屏路上成立，
    //       按标签全局隐藏会把表格里所有 `<span>` 判成不可见）；
    //    ③ at-rule 自己的头部。
    const src = String(css || "").replace(/\/\*[\s\S]*?\*\//g, "");
    const classes = new Set(), ids = new Set(), tags = new Set();
    let selStart = 0, sel = "";
    const stack = [];
    for (let i = 0; i < src.length; i += 1) {
      if (src[i] === "{") {
        const head = src.slice(selStart, i).trim();
        if (/^@[\w-]+/.test(head)) {
          stack.push(/^@(?:keyframes|font-face|property)/.test(head) ? "ignore" : "at");
          sel = "";
        } else {
          stack.push("rule");
          sel = stack.includes("ignore") ? "" : head;
        }
        selStart = i + 1;
        continue;
      }
      if (src[i] !== "}") continue;
      const decls = src.slice(selStart, i);
      selStart = i + 1;
      const kind = stack.pop() || "rule";
      if (kind === "rule" && sel && hidesIn(decls.replace(/\s+/g, " "))) {
        for (const part of sel.split(",")) {
          const pieces = part.trim().split(/[\s>+~]+/);
          const right = pieces.pop() || "";
          if (!right || right.includes(":")) continue;
          const cls = right.match(/\.([\w-]+)/g) || [];
          const idm = right.match(/#([\w-]+)/);
          const tag = right.match(/^([a-zA-Z][\w-]*)(\[[^\]]*\])?$/);
          if (cls.length) cls.forEach((c) => classes.add(c.slice(1).toLowerCase()));
          else if (idm) ids.add(idm[1].toLowerCase());
          else if (tag && pieces.length === 0) tags.add(tag[1].toLowerCase());
        }
      }
      sel = "";
    }
    return { classes, ids, tags };
  };
  // 来源不止 base.css：壳层 index.html 里的 `<style>` 同样进生产（第十二轮 ix B12-3）
  const HIDDEN_BY_CSS = cssHiding(read("css") + "\n"
    + (read("index").match(/<style>[\s\S]*?<\/style>/g) || []).join("\n")
        .replace(/<\/?style>/g, ""));
  const isInvisible = (rawAttrs) => {
    const attrs = parseAttrs(rawAttrs);
    for (const [name, value] of attrs) {
      const v = String(value).toLowerCase().replace(/\s+/g, " ");
      if (name === "hidden") return true;      // 出现即为真（HTML 规范）
      if (name === "aria-hidden" && v.trim() !== "false") return true;
      if (name === "style" && hidesIn(v)) return true;
    }
    for (const [name, value] of attrs) {
      const v = String(value).toLowerCase();
      if (name === "class"
          && v.split(/\s+/).some((c) => c && HIDDEN_BY_CSS.classes.has(c))) return true;
      if (name === "id" && HIDDEN_BY_CSS.ids.has(v.trim())) return true;
    }
    return false;
  };
  const visibleText = (html) => {
    const src = String(html || "").replace(/<!--[\s\S]*?-->/g, "");
    const tagRe = /<(\/?)([a-zA-Z][\w-]*)((?:"[^"]*"|'[^']*'|[^>"'])*?)(\/?)>/g;
    let out = "", cursor = 0;
    const stack = [];
    let m;
    while ((m = tagRe.exec(src))) {
      const text = src.slice(cursor, m.index);
      const insideHidden = stack.length > 0 && stack[stack.length - 1].hidden;
      if (!insideHidden && text) out += text;
      cursor = m.index + m[0].length;
      const closing = m[1] === "/";
      const name = m[2].toLowerCase();
      const attrs = m[3] || "";
      const selfClose = m[4] === "/";
      if (closing) {
        for (let i = stack.length - 1; i >= 0; i--) {
          if (stack[i].name === name) { stack.length = i; break; }
        }
        continue;
      }
      const parentHidden = stack.length > 0 && stack[stack.length - 1].hidden;
      // `<template>` / `<noscript>` 里的内容用户看不见（B10-2）；script/style 同理；
      // 样式表里被整条隐藏的**标签**（如 `p{display:none}`）也算（第十一轮 B-11-3）
      const hidden = isInvisible(attrs) || HIDDEN_BY_CSS.tags.has(name)
        || ["script", "style", "template", "noscript"].includes(name) || parentHidden;
      if (!selfClose && !VOID_TAGS.has(name)) stack.push({ name, hidden });
    }
    const tail = src.slice(cursor);
    const stillHidden = stack.length > 0 && stack[stack.length - 1].hidden;
    if (!stillHidden) out += tail;
    return out.replace(/\s+/g, " ");
  };
  const visibleHtml = () => pageHtml.replace(/<!--[\s\S]*?-->/g, "");
  let __note = "";   // 判据内部算出的线索。箭头函数里写 `return a, b` 是**逗号表达式**，
  let __note2 = "";  // 返回的是 b —— 字符串恒真会让整条判据永不变红（本轮自己踩到两次）
  let __note4 = "";
  let __note8 = "";   // K8 专用：容器查不到时把事实写进 detail，不参与判定的"缺省空串"就是 fail-open
  const containerAttrsForNote = () => {
    const m = pageHtml.match(/<div\s+id="hour-chart"([^>]*)>/);
    return m ? m[1] : "无（容器不存在）";
  };

  check("K0", "能执行真实 renderDashboard（执行不了=本段判据失去对象）",
    () => !renderErr, renderErr);
  check("K7", "页面请求的就是后端真实存在的 `/admin/api/overview`（第九轮 B-1）", () => {
    // 双重钉：① 源码里有这个端点字面量；② 假 fetch 按路径分派后渲染没抛错
    //（改成别的路径 → api.js 拿到 404 抛错 → K0/renderErr 也会红）
    return /GET\("\/admin\/api\/overview"\)/.test(dashSrc) && !renderErr;
  }, `源码含端点=${/GET\("\/admin\/api\/overview"\)/.test(dashSrc)} err=${renderErr}`);
  check("K1", "每条告警都作为**可见文本**出现在横幅里（注释掉/藏起来/塞进 title 都要红）", () => {
    const want = (JSON.parse(readFileSync(overviewPath, "utf-8")).warnings || []);
    const opened = (pageHtml.match(/<div[^>]*class="alert alert-warn"[^>]*>/g) || []).length;
    const decode = (t) => String(t).replace(/&lt;/g, "<").replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");
    const seen = decode(visibleText(pageHtml));
    const missing = want.filter((w) => !seen.includes(decode(String(w.message || "")).replace(/\s+/g, " ")));
    __note = `横幅节点=${opened} 期望=${want.length} 正文缺失=${missing.length}`;
    return want.length > 0 && opened === want.length && missing.length === 0;
  }, () => __note);
  check("K2", "资源健康表真的挂进页面且**可见**（表头 + 数据行）", () => {
    const shown = visibleText(pageHtml);
    const rows = (pageHtml.match(/<tr[ >]/g) || []).length;
    __note2 = `rows=${rows} 冷却中=${shown.includes("冷却中")}`;
    return /冷却剩余/.test(pageHtml) && /最近错误/.test(pageHtml)
      && pageHtml.includes("<tbody>") && rows >= 3 && shown.includes("冷却中");
  }, () => __note2);
  check("K3", "八张指标卡全部**可见**（此前指标卡零覆盖，display:none 也算藏）", () => {
    const shown = visibleText(pageHtml);
    return ["运行状态", "运行时长", "今日调用", "今日 token", "资源健康",
      "厂商数量", "资源总数", "可用模型总数"].every((t) => shown.includes(t));
  });
  check("K8", "趋势图真画进**可见**容器（删调用/把容器压成 height:0 都要红，第九轮 B-6 + 第十轮 B10-5）",
    () => {
      __note8 = "";
      // 🔴 第十二轮 eng-B B11-8 / ix B12-6：**容器不存在 = 红**，不能缺省成空串当"可见"过。
      //    旧写法 `|| ["", ""]` 让"把容器 id 改掉"（页面上那一块直接空掉、柱数 0）被判成通过。
      const container = pageHtml.match(/<div\s+id="hour-chart"([^>]*)>/);
      if (!container) {
        __note8 = "页面上找不到 #hour-chart 容器（趋势卡整块不存在，不是『可见』）";
        return false;
      }
      const attrs = container[1];
      const bars = (chartHtml.match(/<div/g) || []).length;
      // 容器自身的样式也判：`height:0` 的图表在页面上就是一条空白带
      return !isInvisible(attrs) && !/height\s*:\s*0(px|rem|em|%)?/i.test(attrs)
        && bars > 10 && chartHtml.length > 100;
    },
    () => (__note8 || `容器属性=${containerAttrsForNote()} 元素数=${(chartHtml.match(/<div/g) || []).length}`));
  check("K4", "页面产出的每个链接都指向真实导航项，且**没有任何外部链接**", () => {
    const pages = new Set([...navLabels.keys()]);
    const found = [...pageHtml.matchAll(
      /(?:href|location\.hash|location\.href)\s*=?\s*["']#?\/?([\w-]+)/g)].map((m) => m[1]);
    // 🔴 外链不是解析噪声（第十一轮 B11-7）：旧写法 `p !== "http" && p !== "https"`
    //    会把 `href="https://docs…"` 当成正则截断的垃圾直接丢掉 —— 而管理台里出现远程
    //    链接正好违反铁律 1（纯本地运行、无远程下发），必须是一条红线。
    const external = [...pageHtml.matchAll(/(?:href|src)\s*=\s*"((?:https?:)?\/\/[^"]*)"/g)]
      .map((m) => m[1]);
    const links = found.filter(Boolean);
    __note4 = `内部 ${links.length} 条；外链 ${external.length} 条`
      + (external.length ? `：${external.slice(0, 2).join(",")}` : "");
    return external.length === 0 && links.length >= 1 && links.every((p) => pages.has(p));
  }, () => __note4);
  check("K5", "页面**产出了内容**且没有坏插值（undefined / [object Object] / 残留 ${）",
    () => pageHtml.length > 200
      && !/\$\{|undefined|\[object Object\]/.test(visibleText(pageHtml)),
    () => (visibleText(pageHtml).match(/.{0,40}(undefined|\$\{|\[object)/g) || [])
      .slice(0, 3).join(" | "));
  check("K9", "后端下发的原文经页面转义（`<script>` 不得原样出现在产出里，第九轮 B-5）", () => {
    // 载荷里塞一条含 HTML 的 message，看**页面产出**：必须只剩转义后的实体
    if (sentinelErr || !sentinelHtml) return false;
    return sentinelHtml.includes("&lt;script&gt;")
      && !/<script>/.test(sentinelHtml)
      && !/onerror=alert\(1\)>/.test(sentinelHtml.replace(/&lt;img[^&]*$/gm, ""))
      && visibleText(sentinelHtml).includes("哨兵");
  }, () => `err=${sentinelErr} 含转义=${sentinelHtml.includes("&lt;script&gt;")}`);
  check("K6", "恢复时刻落在**「最近错误」那一列**且肉眼可见（第九轮 B-7：不许搬到别的列）", () => {
    const rows = pageHtml.split("<tr").slice(1);
    const cool = rows.find((r) => /冷却中/.test(r));
    if (!cool) return false;
    // 🔴 表头必须**自身可见**才算列位（第十轮 B10-4：`<th hidden>` 让整列失去标题仍全绿）
    const heads = [...pageHtml.matchAll(/<th([^>]*)>([\s\S]*?)<\/th>/g)]
      .filter((m) => !isInvisible(m[1]))
      .map((m) => m[2].replace(/<[^>]*>/g, "").trim());
    const idx = heads.indexOf("最近错误");
    if (idx < 0) return false;
    const cells = cool.split("<td").slice(1);
    const errCell = visibleText(cells[idx] ? `<td${cells[idx]}` : "");
    const coolCell = visibleText(`<td${cells[heads.indexOf("冷却剩余")] || ""}`);
    // 恢复时刻**只准出现在那一列**：搬到别的列（或整行到处都印）就等于没有列位契约
    const elsewhere = cells.filter((_, i) => i !== idx)
      .map((c2) => visibleText(`<td${c2}`)).filter((t) => /，至 (?:明日 )?\d{2}:\d{2}/.test(t));
    __note = `表头=${heads.join(",")} 最近错误列=${errCell} 冷却剩余列=${coolCell} 串列=${elsewhere.length}`;
    return /，至 (?:明日 )?\d{2}:\d{2}/.test(errCell)
      && /\d+s/.test(coolCell) && elsewhere.length === 0;
  }, () => __note);

  // 🔴 K10 · 单元格的**取值身份**（第十一轮 eng-B B11-4）：把「连续失败」与「处理中」两列的
  //    取值对调（表头文字、`<td>` 数量都不变）时，B1~B7 与 K2/K6 一条都不红 —— 它们要么只数
  //    列数、要么只看「最近错误」那一列。用户在表里读到的是反的数："失败 0 次 / 在途 7 个"。
  //    fixture 里这两列原先恒为 0/0，对调天然不可判别 —— 所以"可判别行数"本身也是判据的一部分。
  let __k10 = "";
  check("K10", "逐行核：「连续失败」= 该行 C、「处理中」= 该行 in_flight（对调即红）", () => {
    const all = overview.resources || [];
    const discriminating = all.filter((r) => String(r.C ?? 0) !== String(r.in_flight ?? 0));
    if (discriminating.length === 0) {
      __k10 = `fixture 里 ${all.length} 行的 C 与 in_flight 全相等 —— 不可判别，判据视为失效`;
      return false;
    }
    const htmlAll = renderTable(all);
    const heads = [...htmlAll.matchAll(/<th([^>]*)>([\s\S]*?)<\/th>/g)]
      .filter((m) => !isInvisible(m[1]))
      .map((m) => m[2].replace(/<[^>]*>/g, "").trim());
    const iC = heads.indexOf("连续失败"), iF = heads.indexOf("处理中");
    if (iC < 0 || iF < 0) {
      __k10 = `可见表头里找不到这两列：${heads.join(",")}`;
      return false;
    }
    const body = htmlAll.split("<tr").filter((x) => x.includes("<td"));
    const bad = [];
    body.forEach((row, n) => {
      const r = all[n];
      if (!r) return;
      const cells = row.split(/<td/).slice(1);
      const at = (i) => visibleText(`<td${cells[i] ?? ""}`).trim();
      if (at(iC) !== String(r.C ?? 0)) bad.push(`第${n}行 连续失败读到「${at(iC)}」应为 ${r.C ?? 0}`);
      if (at(iF) !== String(r.in_flight ?? 0)) {
        bad.push(`第${n}行 处理中读到「${at(iF)}」应为 ${r.in_flight ?? 0}`);
      }
    });
    __k10 = `可判别 ${discriminating.length}/${all.length} 行；${bad.join(" | ") || "逐行对得上"}`;
    return bad.length === 0;
  }, () => __k10);

  /* ---------- L · 共享行为层真跑（api.js + components.js，面板 ix B12-1 / S-46 第一半） ----------
   * 与 K 段的分工：K 段跑的是 dashboard.js 这一个页面；L 段跑的是**六个页面共用的那批函数**。
   * 场景先 await 求值再判（与 A/B/C 段同一口径）—— check 的 detail 是在登记时求值的，
   * 异步判据把 detail 写成箭头函数只会拿到空串（本轮实测踩过，故 L 段一律先跑后判）。
   */
  const COMPONENTS_KEY = COMP_SRC;
  const sharedCache = new Map();
  const shared = (label, scenario) => {
    if (!sharedCache.has(label)) {
      let p;
      try {
        const prelude = `${SHARED_DOM}\n${toModuleBody(read("api"))}\n`
          + `${toModuleBody(read(COMPONENTS_KEY))}\n`;
        p = browserFn(`${prelude}return (async () => {\n${scenario}\n})();\n`)();
      } catch (e) { p = Promise.reject(e); }
      sharedCache.set(label, p.then(
        (out) => ({ out, threw: "" }),
        (e) => ({ out: null, threw: `${e && e.name}: ${String(e && e.message).slice(0, 170)}` })));
    }
    return sharedCache.get(label);
  };
  // maskVal 不在共享层（账本口径偏差，见证据文档）：它是**两处逐字重复**的页内函数
  // （apiaccess.js:19 / resources.js:76）。密文规格是全站口径，所以两处定义都要真跑一遍；
  // 抽取数量本身也是判据的一部分（抽不到 = 红，不得当成"零违规"放过 —— J2/J3 同一教训）。
  const maskDefs = () => {
    const defs = [];
    for (const [, rel] of Object.entries(FILES)) {
      if (!rel.endsWith(".js")) continue;
      let src = "";
      try { src = readFileSync(join(root, rel), "utf-8"); } catch { continue; }
      for (const m of src.matchAll(/^[ \t]*(?:function[ \t]+maskVal\b[^\n]*\{[\s\S]*?\}|(?:const|let|var)[ \t]+maskVal[ \t]=[ \t][^\n]*;)[ \t]*$/gm)) {
        defs.push({ file: rel, src: m[0] });
      }
    }
    return defs;
  };
  const maskScenario = (defs) => `
const defs = [];
${defs.map((d) => `defs.push((function () {
${d.src}
return maskVal;
})());`).join("\n")}
const KEY = "sk-a1b2c3d4e5f6g7h8j9k0lm";
const MID = KEY.slice(5, KEY.length - 4);
return defs.map((f) => {
  const m = String(f(KEY));
  const td = document.createElement("td");
  td.textContent = m;
  return { got: m, spec: KEY.slice(0, 5) + "****" + KEY.slice(-4), same: m === KEY,
    midLeak: m.indexOf(MID) >= 0, star: m.indexOf("****") >= 0,
    domText: td.textContent, domLeak: td.textContent.indexOf(KEY) >= 0,
    empty: JSON.stringify(f("")) };
});
`;
  const rInv = await shared("inventory", L_SCEN.inventory);
  const rStates = await shared("states", L_SCEN.states);
  const rMethods = await shared("methods", L_SCEN.methods);
  const rPersist = await shared("persist", L_SCEN.persist);
  const rConfirm = await shared("confirm", L_SCEN.confirm);
  const rCopy = await shared("copy", L_SCEN.copy);
  const rModal = await shared("modal", L_SCEN.modal);
  const rSw = await shared("sw", L_SCEN.sw);
  const rTabs = await shared("tabs", L_SCEN.tabs);
  const defs = maskDefs();
  const rMask = await shared("mask", maskScenario(defs));
  // 🔴 取不到结果时必须回一个**对象**：`[] || [{}]` 是 truthy 的空数组，`[0]` 就是 undefined，
  //    而 detail 里的 `st(x).rejected` 是在 check() **之前**求值的字符串 —— 整个子进程会崩掉
  //    （本轮第一次跑变异自证就撞在两条让 states 拿不到结果的变异上：崩掉 = 盲，不是红）。
  const st = (name) => {
    const hit = (rStates.out || []).filter((c) => c && c.name === name);
    return hit.length > 0 ? hit[0]
      : { name, missing: "该场景没跑出结果（realm 编译/执行抛错，见 threw）", rejected: null, got: "", msg: "" };
  };
  const LNOTE = {};   // 判据内部算出的线索（detail 在登记时求值，L 段先跑后判所以拿得到）

  check("L0", "共享层能在 realm 里编译并真跑（12 个导出齐备；编不过/少导出 = L 段判据失去对象）",
    () => {
      if (rInv.threw) return false;
      const bad = Object.entries(rInv.out || {}).filter(([, t]) => t !== "function");
      return Object.keys(rInv.out || {}).length === 12 && bad.length === 0;
    },
    rInv.threw ? "realm 编译/执行抛错 " + rInv.threw
      : (() => {
        const bad = Object.entries(rInv.out || {}).filter(([, t]) => t !== "function")
          .map(([k, t]) => `${k}=${t}`);
        return `导出 ${Object.keys(rInv.out || {}).length}/12${bad.length ? "；不是函数：" + bad.join(",") : "；全部为函数"}`;
      })());

  check("L1", "成功路径返回**后端那份数据**（2xx JSON 原样交出，不是 null / 不是 HTTP 串）",
    () => {
      const c = st("200-json");
      return !rStates.threw && c.rejected === false
        && c.got === JSON.stringify({ hello: "world", n: 7 });
    },
    rStates.threw ? "realm 抛错 " + rStates.threw
      : `200-json → rejected=${st("200-json").rejected} got=${st("200-json").got}`);

  check("L2", "四类后端错误形态的原因都被带进 Error.message（errors[] / error.message / message / detail）",
    () => {
      const want = { "400-errors": ["rid 重复：res-a", "models[3].name 必填"],
        "401-obj": ["E 上游 401 invalid_api_key"], "409-msg": ["M 配置已被别处改动"],
        "422-detail": ["D 字段校验失败"] };
      if (rStates.threw) return false;
      const bad = [];
      for (const [name, parts] of Object.entries(want)) {
        const c = st(name);
        const msg = String(c.msg || "");
        for (const p of parts) if (msg.indexOf(p) < 0) bad.push(`${name}→「${msg}」缺「${p}」`);
        if (parts.length > 1 && msg.split("；").length !== parts.length) {
          bad.push(`${name}→多条原因没拼全：「${msg}」`);
        }
      }
      LNOTE.l2 = bad;
      return bad.length === 0;
    }, () => (rStates.threw ? "realm 抛错 " + rStates.threw : LNOTE.l2.join(" | ") || "四类形态逐条对上"));

  const L3FAIL = ["400-errors", "401-obj", "409-msg", "422-detail", "500-html", "network"];
  check("L3", "!resp.ok 一律 reject（4xx/5xx 绝不允许被当成成功返回数据）",
    () => {
      if (rStates.threw) return false;
      LNOTE.l3 = L3FAIL.filter((n) => st(n).rejected !== true).map((n) => `${n}→resolve(${st(n).got})`);
      return LNOTE.l3.length === 0;
    }, () => (rStates.threw ? "realm 抛错 " + rStates.threw
      : `六种失败响应：${L3FAIL.map((n) => `${n}→${st(n).rejected ? "reject" : "resolve(" + st(n).got + ")"}`).join(" ")}`
        + (LNOTE.l3 && LNOTE.l3.length ? " ｜静默当成功：" + LNOTE.l3.join(",") : "")));

  check("L4", "网络异常（fetch reject）原样抛出，不得吞成 null/undefined 让界面以为成功",
    () => {
      const c = st("network");
      return !rStates.threw && c.rejected === true && c.got === "NO-RESULT"
        && String(c.msg).indexOf("Failed to fetch") >= 0;
    }, () => `network → rejected=${st("network").rejected} msg=${st("network").msg} got=${st("network").got}`);

  check("L5", "后端回 400 时界面只有红色「保存失败」并带后端原因，绿色「配置已保存并热重载生效」必须消失",
    () => {
      if (rPersist.threw) return false;
      const o = rPersist.out || {};
      const t = o.toasts || [];
      LNOTE.l5 = `outcome=${o.outcome} toasts=${JSON.stringify(t)}`;
      return t.length === 1 && o.outcome === "err"
        && /(^| )err( |$)/.test(String(t[0].cls))
        && String(t[0].text).indexOf("rid 重复：res-a") >= 0
        && String(t[0].text).indexOf("配置已保存并热重载生效") < 0;
    }, () => (rPersist.threw ? "realm 抛错 " + rPersist.threw : LNOTE.l5));

  check("L6", "非 JSON 的 4xx/5xx（网关 HTML 错误页）仍 reject 并给出 HTTP 状态口径",
    () => {
      const c = st("500-html");
      return !rStates.threw && c.rejected === true && c.msg === "HTTP 500" && c.got === "NO-RESULT";
    }, () => `500-html → rejected=${st("500-html").rejected} msg=${st("500-html").msg} got=${st("500-html").got}`);

  check("L7", "非 JSON 的 2xx → 返回 null（不得凭空造 {} 让调用方以为拿到了配置）",
    () => {
      const c = st("204-nonjson");
      return !rStates.threw && c.rejected === false && c.got === "null";
    }, () => `204-nonjson → got=${st("204-nonjson").got} rejected=${st("204-nonjson").rejected}`);

  check("L8", "GET/POST/PUT 的 HTTP 语义真的带出去（method + JSON 序列化 + Content-Type）",
    () => {
      if (rMethods.threw) return false;
      const o = rMethods.out || {};
      const sent = o.sent || [];
      LNOTE.l8 = JSON.stringify(sent);
      const g = sent[0] || {}, p = sent[1] || {}, u = sent[2] || {};
      return sent.length === 3 && g.m === null && g.p === "/admin/api/overview"
        && p.m === "POST" && p.b === JSON.stringify({ name: "Trae", enabled: true })
        && u.m === "PUT" && u.b === JSON.stringify({ resources: [1, 2] })
        && [g, p, u].every((x) => x.ct === "application/json")
        && o.post && o.post.id === "tok-1" && o.g && o.g.nested && o.g.nested.n === 3;
    }, () => (rMethods.threw ? "realm 抛错 " + rMethods.threw : "实际发出的请求：" + LNOTE.l8));

  check("L9", "确认弹窗点「取消」：不执行副作用（DELETE_SENT 一次都没有）+ 弹窗关掉 + 给出答复",
    () => {
      if (rConfirm.threw) return false;
      const c = (rConfirm.out || {}).cancel || {};
      LNOTE.l9 = JSON.stringify(c);
      return !c.err && c.state === "settled" && c.value === "false"
        && (c.calls || []).length === 0 && c.open === 0
        && c.footBtnCount === 2 && JSON.stringify(c.footBtnLabels) === JSON.stringify(["取消", "确定"]);
    }, () => (rConfirm.threw ? "realm 抛错 " + rConfirm.threw : "取消分支：" + LNOTE.l9));

  check("L10", "确认弹窗点「确定」：副作用**恰好一次**（确认不得被吞掉），弹窗关掉",
    () => {
      if (rConfirm.threw) return false;
      const o = (rConfirm.out || {}).ok || {};
      LNOTE.l10 = JSON.stringify(o);
      return !o.err && o.state === "settled" && o.value === "true"
        && JSON.stringify(o.calls) === JSON.stringify(["DELETE_SENT"]) && o.open === 0;
    }, () => (rConfirm.threw ? "realm 抛错 " + rConfirm.threw : "确定分支：" + LNOTE.l10));

  // 🔴 S-61（本轮自查，非面板所报）：`modal()` 有**两条不经过按钮**的关闭通道（✕、遮罩）。
  //    旧实现只在两个按钮上 resolve → 用户点 ✕ 后 promise 永不 settle，
  //    `if (!await confirmDialog(...)) return;` 的调用方永久挂住：弹窗没了、
  //    删除既不执行也不报错，界面看不出任何异常。
  //    ⚠ 判据钉的是"**有没有给出答复**"，不是"取消不执行副作用" —— 挂住的 promise
  //    连副作用都没有，后者那种写法照样绿（这是本条必须独立成判据的理由）。
  check("L21", "确认弹窗经 ✕ / 遮罩关闭也必须 settle 并答复「取消」（副作用零次、弹窗关掉）",
    () => {
      if (rConfirm.threw) return false;
      const o = rConfirm.out || {};
      const bad = [];
      for (const k of ["x", "mask"]) {
        const c = o[k] || {};
        if (c.err) { bad.push(`${k}:${c.err}`); continue; }
        if (c.state !== "settled") {
          bad.push(`${k}:promise 处于 ${c.state} —— 没给出答复，调用方会永久挂住`);
          continue;
        }
        if (c.value !== "false") bad.push(`${k}:答复=${c.value}（没做选择不得当成「确定」）`);
        if ((c.calls || []).length !== 0) bad.push(`${k}:副作用 ${c.calls.length} 次`);
        if (c.open !== 0) bad.push(`${k}:弹窗没关掉`);
      }
      LNOTE.l21 = bad.length ? bad.join("；") : `两条通道都 settle 且答复=false`;
      return bad.length === 0;
    }, () => (rConfirm.threw ? "realm 抛错 " + rConfirm.threw : LNOTE.l21));

  check("L11", "copyText 成功：写进剪贴板的正是那段明文，toast 文案与 ok 样式同源",
    () => {
      if (rCopy.threw) return false;
      const o = rCopy.out || {};
      const t = o.toasts || [];
      LNOTE.l11 = `written=${JSON.stringify(o.written)} toasts=${JSON.stringify(t)}`;
      return JSON.stringify(o.written) === JSON.stringify(["sk-a1b2c3d4e5f6g7h8"])
        && t.length === 1 && t[0].text === "密钥已复制" && /(^| )ok( |$)/.test(t[0].cls)
        && JSON.stringify(o.defaultWritten) === JSON.stringify(["https://127.0.0.1:8300/v1"])
        && (o.defaultToasts || [])[0] && (o.defaultToasts || [])[0].text === "已复制";
    }, () => (rCopy.threw ? "realm 抛错 " + rCopy.threw : LNOTE.l11));

  check("L12", "剪贴板写入被拒（权限/非安全上下文）：toast 只能说不一致的口径，不得报「已复制」",
    () => {
      if (rCopy.threw) return false;
      const o = rCopy.out || {};
      const t = o.denyToasts || [];
      LNOTE.l12 = `written=${JSON.stringify(o.denyWritten)} toasts=${JSON.stringify(t)}`;
      return t.length === 1 && t[0].text === "复制失败" && /(^| )err( |$)/.test(t[0].cls)
        && String(t[0].text).indexOf("复制成功") < 0 && JSON.stringify(o.denyWritten)
          === JSON.stringify(["sk-zzz"]);
    }, () => (rCopy.threw ? "realm 抛错 " + rCopy.threw : LNOTE.l12));

  check("L13", "navigator.clipboard 不存在时**绝不谎报已复制**（没有任何真实写入路径就不许弹成功）",
    () => {
      if (rCopy.threw) return false;
      const o = rCopy.out || {};
      LNOTE.l13 = `toasts=${JSON.stringify(o.noClipToasts)} written=${JSON.stringify(o.noClipWritten)}`;
      return (o.noClipToasts || []).length === 0 && (o.noClipWritten || []).length === 0;
    }, () => (rCopy.threw ? "realm 抛错 " + rCopy.threw : LNOTE.l13));

  check("L14", "modal 标题走 esc：title 里的 <script> 不得成为真元素（管理台注入面）",
    () => {
      if (rModal.threw) return false;
      const a = (rModal.out || {}).a || {};
      LNOTE.l14 = `scripts=${a.scripts} h3=${a.h3}`;
      return a.scripts === 0 && String(a.h3 || "").indexOf("<script>") < 0
        && String(a.h3 || "").indexOf("alert(1)") >= 0;
    }, () => (rModal.threw ? "realm 抛错 " + rModal.threw : LNOTE.l14));

  check("L15", "modal 的 footer 子节点**平铺**进 .modal-foot（Q21 间距根修：整块 append 会让 gap 失效）",
    () => {
      if (rModal.threw) return false;
      const o = rModal.out || {};
      const a = o.a || {};
      LNOTE.l15 = `footKids=${a.footKids} texts=${JSON.stringify(a.footTexts)} emptied=${a.footEmptied}`;
      return a.footKids === 2 && JSON.stringify(a.footTexts) === JSON.stringify(["取消", "确定"])
        && a.footEmptied === true && a.bodyKids === 1 && a.modalCls === "modal wide";
    }, () => (rModal.threw ? "realm 抛错 " + rModal.threw : LNOTE.l15));

  check("L16", "modal 关闭三通道：X 按钮关、点遮罩关（并回调 onClose）、点弹窗内部**不关**",
    () => {
      if (rModal.threw) return false;
      const o = rModal.out || {};
      LNOTE.l16 = JSON.stringify({ afterX: o.afterX, blank: o.blankClose, innerKids: o.innerKids,
        api: o.afterApiClose, el: o.elIdentity, noFooter: o.noFooter });
      return o.afterX === 0 && o.blankClose && o.blankClose.kids === 0
        && o.blankClose.closed === 1 && o.innerKids === 1 && o.elIdentity === "el-ok"
        && o.afterApiClose === 1 && o.noFooter && o.noFooter.foot === false
        && o.noFooter.cls === "modal";
    }, () => (rModal.threw ? "realm 抛错 " + rModal.threw : LNOTE.l16));

  check("L17", "switchEl：保存成功（onToggle 返回 true）才翻视觉，返回 false 必须回滚（D3 操作即保存）",
    () => {
      if (rSw.threw) return false;
      const o = rSw.out || {};
      LNOTE.l17 = JSON.stringify(o);
      return o.okTrue && o.okTrue.after === true && JSON.stringify(o.okTrue.seen) === "[true]"
        && o.failFalse.after === false && o.failFalse.cls === "switch"
        && o.undef.after === true
        && o.turnOff.after === false && JSON.stringify(o.turnOff.seen) === "[false]"
        && o.noToggle.after === true;
    }, () => (rSw.threw ? "realm 抛错 " + rSw.threw : LNOTE.l17));

  check("L18", "tabBar：选中态唯一，且回调收到**被点的那个** tab id",
    () => {
      if (rTabs.threw) return false;
      const t = (rTabs.out || {}).tabs || {};
      LNOTE.l18 = JSON.stringify(t);
      return t.count === 2 && JSON.stringify(t.switched) === JSON.stringify(["b"])
        && JSON.stringify(t.actives) === JSON.stringify(["维度"]);
    }, () => (rTabs.threw ? "realm 抛错 " + rTabs.threw : LNOTE.l18));

  check("L19", "pagination：首页禁「‹」/末页禁「›」，点「›」交出下一页 offset",
    () => {
      if (rTabs.threw) return false;
      const o = rTabs.out || {};
      const k1 = (o.kids || []).map((x) => [x.text, x.dis]);
      const k2 = (o.kids2 || []).map((x) => [x.text, x.dis]);
      LNOTE.l19 = `first=${JSON.stringify(k1)} last=${JSON.stringify(k2)} pages=${JSON.stringify(o.pages)}`;
      return JSON.stringify(k1) === JSON.stringify([["‹", true], ["1 / 3（共 23 条）", false], ["›", false]])
        && JSON.stringify(k2) === JSON.stringify([["‹", false], ["3 / 3（共 23 条）", false], ["›", true]])
        && JSON.stringify(o.pages) === "[10]" && o.pagerCls === "pager";
    }, () => (rTabs.threw ? "realm 抛错 " + rTabs.threw : LNOTE.l19));

  check("L20", "maskVal：每处定义都输出「前5+****+后4」密文，DOM 文本里不得出现完整明文",
    () => {
      if (rMask.threw) return false;
      const rows = rMask.out || [];
      const bad = [];
      if (rows.length !== defs.length || defs.length < 2) {
        bad.push(`定义抽取 ${defs.length} 处（全站 maskVal 至少 2 处：apiaccess.js / resources.js），真跑 ${rows.length} 处`);
      }
      rows.forEach((r, i) => {
        const f = defs[i] ? defs[i].file : "?";
        if (r.same) bad.push(`${f}：恒等返回明文（输出===输入）`);
        if (!r.star) bad.push(`${f}：输出里没有 **** 掩码段`);
        if (r.midLeak) bad.push(`${f}：密钥中段泄漏`);
        if (r.domLeak) bad.push(`${f}：DOM 文本里出现完整明文`);
        if (r.got !== r.spec) bad.push(`${f}：口径不是「前5+****+后4」，实得 ${r.got}`);
        if (r.empty !== '""') bad.push(`${f}：空值不再是空串，实得 ${r.empty}`);
      });
      LNOTE.l20 = bad.join(" | ")
        || `${rows.length} 处定义逐条对上（样例 ${(rows[0] || {}).got}）`;
      return bad.length === 0;
    }, () => (rMask.threw ? "realm 抛错 " + rMask.threw
      : `抽取 ${defs.length} 处：${defs.map((d) => d.file.replace(/^.*\//, "")).join(",")} ｜ ${LNOTE.l20}`));

  /* ---------- M · 两个正式页面真跑（apiaccess.js + settings.js · S-46 第二批） ----------
   * 与 L 段的分工：L 段跑**六个页面共用**的那批函数；M 段跑这两页自己的 render/persist/行内绑定。
   * 面板点名的"徽章说脏却点不动保存"这类**页面级**谎报只能在 M 段被抓到
   * （上一批 §6.1 自己把它列为未覆盖项）。口径同 L 段：场景先 await 跑完、判定同步做。
   */
  const maskOf = (v) => (v ? String(v).slice(0, 5) + "****" + String(v).slice(-4) : "");
  const deepClone = (x) => JSON.parse(JSON.stringify(x));
  const fixtureWith = (mut) => { const c = deepClone(CONFIG_FIXTURE); mut(c); return c; };
  // 假"服务端"：按 method+path 分派、把 PUT 真的落库（含生产端点的 id/密钥自动生成），
  // 于是"重渲染回落到服务端态""body 是不是全量配置"这类语义真的可判，而不是看字串。
  const mEnv = (extra) => `
const SRV = { cfg: ${JSON.stringify(CONFIG_FIXTURE)}, reqs: [], putFails: null, gen: 0 };
const OV = { call_addresses: ${JSON.stringify(overview.call_addresses || null)} };
${extra || ""}
const cloneOf = (x) => JSON.parse(JSON.stringify(x));
/* 🔴 等待口径：**按条件**排空微任务再多转一轮（__flush），拿"界面已经重渲染"这类
   可观察事实当终点。原先只等 SRV.reqs.length>=5 就取样，那是**请求刚发出**、draw 还没跑，
   M8 第一次就因此读到旧的两行 —— 假阴性会伪装成"页面坏了"，必须等真状态。 */
const settle = async (pred, budget) => { const w = await __until(pred, budget || 300); await __flush(); return w; };
const reqLines = () => SRV.reqs.map((r) => r.m + " " + r.path);
const puts = () => SRV.reqs.filter((r) => r.m === "PUT").map((r) => r.body);
fetch = (p, init) => {
  const path = String(p).split("?")[0];
  const m = (init && init.method) || "GET";
  const body = (init && typeof init.body === "string") ? JSON.parse(init.body) : null;
  SRV.reqs.push({ path, m, body });
  if (path === "/admin/api/config" && m === "PUT") {
    if (SRV.putFails) return Promise.resolve(__resp(false, 400, { status: "rejected", errors: SRV.putFails }));
    const next = cloneOf(body);
    /* 🔴 桩自己也要兜住"PUT 回来的是残缺配置"：变异成只发一节的写法会交上没有 gateway 的
       body，直接取 next.gateway.access_tokens 就在**假服务端**里抛 TypeError（红是红了，
       但归因糊在驱动器上）。这里当残缺请求处理：不落库、按 400 回后端原因。 */
    if (!next || typeof next !== "object" || !next.gateway || !next.scheduling) {
      return Promise.resolve(__resp(false, 400, { status: "rejected",
        errors: ["请求体须为完整配置对象（缺 gateway / scheduling）"] }));
    }
    (next.gateway.access_tokens || []).forEach((t) => {
      if (!t.id) { SRV.gen += 1; t.id = "tok-" + (9000 + SRV.gen); }
      if (!t.value) { SRV.gen += 1; t.value = "mg-" + (10000 + SRV.gen) + "abcdef0123456789abcdef01"; }
    });
    (next.resources || []).forEach((r) => { if (r.api_key === "****") r.api_key = "sk-server-side-plain"; });
    SRV.cfg = next;
    return Promise.resolve(__resp(true, 200, { status: "ok", message: "配置已保存并生效" }));
  }
  if (path === "/admin/api/config" && m === "GET") return Promise.resolve(__resp(true, 200, cloneOf(SRV.cfg)));
  if (path === "/admin/api/overview" && m === "GET") return Promise.resolve(__resp(true, 200, cloneOf(OV)));
  if (m === "POST" && (path === "/admin/api/system/stop" || path === "/admin/api/system/restart"))
    return Promise.resolve(__resp(true, 200, { status: "ok", message: "已受理" }));
  return Promise.resolve(__resp(false, 404, { errors: ["无此端点：" + path] }));
};
const rowView = (root, i) => {
  const rows = root.querySelectorAll("[data-tk]");
  const row = rows[i];
  if (!row) return { missing: "第 " + i + " 行不存在（当前共 " + rows.length + " 行）" };
  const val = row.querySelector("[data-tkval]");
  const span = row.querySelector("[data-tksw]");
  const sw = span ? span.children[0] : null;
  const eye = row.querySelector("[data-tkey]");
  return { i, rows: rows.length, name: (row.querySelector("[data-tkname]") || {}).value,
    tdCls: row.children[0].className, shown: val ? val.textContent : null,
    valCls: val ? val.className : null, swOn: sw ? sw.classList.contains("on") : null,
    swCls: sw ? sw.className : null, eyeTitle: eye ? eye.title : null,
    del: !!row.querySelector("[data-delkey]"), cpy: !!row.querySelector("[data-cpykey]") };
};
`;
  const pageCache = new Map();
  const pageRun = (fileKey, label, scen, extra) => {
    const ck = `${fileKey}:${label}`;
    if (!pageCache.has(ck)) {
      let p;
      try {
        const prelude = `${SHARED_DOM}\n${toModuleBody(read("api"))}\n`
          + `${toModuleBody(read(COMPONENTS_KEY))}\n${mEnv(extra)}\n`
          + `${toModuleBody(read(fileKey))}\n`;
        p = browserFn(`${prelude}return (async () => {\n${scen}\n})();\n`)();
      } catch (e) { p = Promise.reject(e); }
      pageCache.set(ck, p.then(
        (out) => ({ out, threw: "" }),
        (e) => ({ out: null, threw: `${e && e.name}: ${String(e && e.message).slice(0, 200)}` })));
    }
    return pageCache.get(ck);
  };
  const MNOTE = {};
  const aR = await pageRun("apiaccess", "render", M_SCEN.a_render);
  const aE = await pageRun("apiaccess", "eye", M_SCEN.a_eye);
  const aC = await pageRun("apiaccess", "copy", M_SCEN.a_copy);
  const aSw = await pageRun("apiaccess", "switch", M_SCEN.a_switch,
    "const WANT = 1; const FAIL = null;");
  const aSwF = await pageRun("apiaccess", "switch-fail", M_SCEN.a_switch,
    `const WANT = 1; const FAIL = ${JSON.stringify(PUT_400_TOKEN)};`);
  const aNm = await pageRun("apiaccess", "name", M_SCEN.a_name);
  const aAdd = await pageRun("apiaccess", "add", M_SCEN.a_add);
  const aDel = await pageRun("apiaccess", "del", M_SCEN.a_del);
  const sR = await pageRun("settings", "render", M_SCEN.s_render);
  const sD = await pageRun("settings", "dirty", M_SCEN.s_dirty);
  const sS = await pageRun("settings", "save", M_SCEN.s_save);
  const sSF = await pageRun("settings", "savefail", M_SCEN.s_savefail,
    `const FAIL = ${JSON.stringify(PUT_400_BUDGET)};`);
  const sStop = await pageRun("settings", "stop", M_SCEN.s_stop);
  const sRe = await pageRun("settings", "restart", M_SCEN.s_restart);
  check("M0", "API 接入页能在 realm 里真跑：首屏发出的就是两条生产端点 GET（7 个页内函数齐备）", () => {
    if (aR.threw) return false;
    const o = aR.out || {};
    const fns = Object.entries(o.fns || {}).filter(([, t]) => t !== "function");
    MNOTE.m0 = `请求=${JSON.stringify(o.reqs)}；页内函数 ${Object.keys(o.fns || {}).length - fns.length}`
      + `/${Object.keys(o.fns || {}).length}${fns.length ? "（缺：" + fns.map(([k]) => k).join(",") + "）" : ""}`
      + `；地址字段=${JSON.stringify(o.addrs)}；端点说明 ${(o.endpoints || []).length} 条；`
      + `表头 ${JSON.stringify(o.heads)}；err=${o.err || "无"}`;
    /* 🔴 地址两块必须**非空且就是后端给的那两条**：`esc(undefined)` 交的是空串，
       所以字段名打错时页面表现为"地址栏一片空白"而不出现 undefined —— M17 那种坏插值判据
       抓不到它（本批实测撞出来的，见证据文档 §8），只能在这里正面钉。 */
    const ca = o.addrs || {};
    const addrWant = [ca.local, ca.lan];
    const gotAddr = o.copies || [];
    const addrBad = !ca.local || !ca.lan || JSON.stringify(gotAddr) !== JSON.stringify(addrWant);
    return !o.err && !addrBad && Object.keys(o.fns || {}).length === 7 && fns.length === 0
      && JSON.stringify(o.reqs) === JSON.stringify(["GET /admin/api/config", "GET /admin/api/overview"])
      && (o.endpoints || []).length === 4 && gotAddr.length === 2;
  }, () => (aR.threw ? "realm 编译/执行抛错 " + aR.threw : MNOTE.m0
    + `；地址块=${JSON.stringify((aR.out || {}).copies)}`));

  check("M1", "API 接入：密钥表**逐行**对上服务端（行数/用途标注/开关态/删除钮/停用行置灰）+ 卡头 N/M 启用计数", () => {
    if (aR.threw) return false;
    const o = aR.out || {};
    const toks = o.tokens || [];
    const rows = o.rows || [];
    const bad = [];
    if (rows.length !== toks.length) bad.push(`渲染 ${rows.length} 行 vs 服务端 ${toks.length} 条`);
    rows.forEach((r, i) => {
      const t = toks[i] || {};
      if (r.missing) { bad.push(`第${i}行：${r.missing}`); return; }
      if (r.name !== (t.name || "")) bad.push(`第${i}行 用途标注读到「${r.name}」应为「${t.name}」`);
      if (r.swOn !== (t.enabled !== false)) {
        bad.push(`第${i}行 开关态=${r.swOn} 应为 ${t.enabled !== false}（${t.name}）`);
      }
      if (!r.del) bad.push(`第${i}行 没有删除钮`);
      if (!r.cpy) bad.push(`第${i}行 没有复制钮`);
      if ((/off/.test(String(r.tdCls)) !== (t.enabled === false))) {
        bad.push(`第${i}行 停用置灰态 td class=${JSON.stringify(r.tdCls)} 与 enabled=${t.enabled} 不一致`);
      }
    });
    const on = toks.filter((t) => t.enabled !== false).length;
    const wantHead = `${on}/${toks.length} 启用`;
    if (!String(o.head || "").startsWith(wantHead)) {
      bad.push(`卡头计数=${JSON.stringify(o.head)}，应以「${wantHead}」开头`);
    }
    MNOTE.m1 = `${rows.length} 行 / ${toks.length} 条；卡头「${o.head}」；停用行 `
      + `${rows.filter((r) => /off/.test(String(r.tdCls))).length} 个；${bad.join(" | ") || "逐行对得上"}`;
    return rows.length >= 2 && bad.length === 0;
  }, () => (aR.threw ? "realm 抛错 " + aR.threw : MNOTE.m1));

  check("M2", "API 接入：密钥值上屏只能是密文（前5+****+后4），整页序列化 HTML 连属性里都不许出现完整明文", () => {
    if (aR.threw) return false;
    const o = aR.out || {};
    const rows = o.rows || [];
    const toks = o.tokens || [];
    const bad = [];
    rows.forEach((r, i) => {
      const t = toks[i] || {};
      const want = maskOf(t.value);
      if (r.shown !== want) bad.push(`第${i}行 值格显示「${r.shown}」应为密文「${want}」`);
      if (r.shown === String(t.value)) bad.push(`第${i}行 值格就是明文本身`);
      if (t.value && String(o.html).indexOf(String(t.value)) >= 0) {
        bad.push(`第${i}行 完整明文泄漏进序列化 DOM（含属性）`);
      }
    });
    const masked = rows.filter((r) => String(r.shown || "").indexOf("****") >= 0).length;
    MNOTE.m2 = `${rows.length} 行里 ${masked} 行是密文；样例「${(rows[0] || {}).shown}」；`
      + `序列化 HTML ${String(o.html || "").length} 字符；${bad.join(" | ") || "无明文"}`;
    return rows.length >= 2 && bad.length === 0;
  }, () => (aR.threw ? "realm 抛错 " + aR.threw : MNOTE.m2));

  check("M3", "API 接入：眼睛就地⇄收回（点开见明文+图标与 title 同向变；点回见密文且 DOM 不留明文；全程零请求）", () => {
    if (aE.threw) return false;
    const o = aE.out || {};
    const key = String(o.server || "");
    const before = o.before || {}; const after = o.after || {};
    const bad = [];
    if (before.shown !== maskOf(key)) bad.push(`初始值格「${before.shown}」不是密文`);
    if (o.shown1 !== key) bad.push(`点眼睛后值格「${o.shown1}」没变成明文`);
    if (o.icon1 === o.icon0) bad.push("点眼睛后图标没换（还是「显示」态那张）");
    if (o.title1 !== "收回明文") bad.push(`点眼睛后 title=「${o.title1}」应为「收回明文」`);
    if (o.on1 !== "1") bad.push(`点眼睛后 data-on=${JSON.stringify(o.on1)} 应为 1`);
    if (after.shown !== maskOf(key)) bad.push(`再点一次值格「${after.shown}」没回到密文`);
    if (o.icon2 !== o.icon0) bad.push("收回后图标没换回原样");
    if (o.on2 !== "") bad.push(`收回后 data-on=${JSON.stringify(o.on2)} 应清空`);
    if (after.eyeTitle !== "显示 / 隐藏明文") bad.push(`收回后 title=「${after.eyeTitle}」`);
    if (String(o.html).indexOf(key) >= 0) bad.push("收回后 DOM 里仍留着完整明文");
    if (JSON.stringify(o.reqs) !== JSON.stringify(["GET /admin/api/config", "GET /admin/api/overview"])) {
      bad.push(`眼睛不该发请求，实得 ${JSON.stringify(o.reqs)}`);
    }
    MNOTE.m3 = `密文「${before.shown}」→ 明文「${String(o.shown1).slice(0, 14)}…」→ 密文「${after.shown}」；`
      + `图标换了 ${o.icon0 !== o.icon1}/${o.icon1 !== o.icon2}；请求 ${JSON.stringify(o.reqs)}；${bad.join(" | ") || "三态都对"}`;
    return bad.length === 0;
  }, () => (aE.threw ? "realm 抛错 " + aE.threw : MNOTE.m3));

  check("M4", "API 接入：复制写进剪贴板的必须是**明文**（密钥=完整 value、地址=URL 原文）并给回执，且复制本身零请求", () => {
    if (aC.threw) return false;
    const o = aC.out || {};
    const key = String(o.serverKey || "");
    const written = o.written || [];
    const bad = [];
    if (written[0] !== key) bad.push(`密钥复制写进剪贴板的是「${written[0]}」不是完整明文（前5+****+后4 那种密文复制出去不可用）`);
    (o.addrVals || []).forEach((a, i) => {
      if (written[1 + i] !== a) bad.push(`第${i}个地址复制写进「${written[1 + i]}」应为「${a}」`);
    });
    const texts = (o.toasts || []).map((t) => t.text);
    if (!texts.some((x) => /已复制/.test(x))) bad.push(`复制后没有任何回执 toast：${JSON.stringify(texts)}`);
    if (texts.some((x) => /复制失败/.test(x))) bad.push("剪贴板可用却报了复制失败");
    if (JSON.stringify(o.reqs) !== JSON.stringify(["GET /admin/api/config", "GET /admin/api/overview"])) {
      bad.push(`复制不该发请求，实得 ${JSON.stringify(o.reqs)}`);
    }
    MNOTE.m4 = `剪贴板收到 ${JSON.stringify(written)}；toast ${JSON.stringify(texts)}；${bad.join(" | ") || "全部对上"}`;
    return bad.length === 0 && written.length >= 3;
  }, () => (aC.threw ? "realm 抛错 " + aC.threw : MNOTE.m4));
  const swWant = fixtureWith((c) => { c.gateway.access_tokens[1].enabled = true; });
  check("M5", "API 接入（D3 启停·成功支）：点开关**恰好一次** PUT，body 是改动后的完整配置，重渲染与服务端/计数一致并弹绿回执", () => {
    if (aSw.threw) return false;
    const o = aSw.out || {};
    const put = o.put || [];
    const bad = [];
    if (put.length !== 1) bad.push(`PUT 发出 ${put.length} 次（应恰好 1 次）`);
    if (JSON.stringify(o.reqs) !== JSON.stringify(["GET /admin/api/config", "GET /admin/api/overview",
      "PUT /admin/api/config", "GET /admin/api/config", "GET /admin/api/overview"])) {
      bad.push(`请求序列=${JSON.stringify(o.reqs)}`);
    }
    if (put[0] && JSON.stringify(put[0]) !== JSON.stringify(swWant)) {
      bad.push("PUT body 与「改动后的完整配置」逐字段不一致（只发增量 / 丢字段 / 改动没带上都算）");
    }
    if (o.server !== true) bad.push(`服务端那条仍是 enabled=${o.server}`);
    if (o.after && o.after.swOn !== true) bad.push(`重渲染后开关视觉态=${o.after.swOn} 应为 on`);
    if (o.after && /(^| )off( |$)/.test(String(o.after.valCls))) bad.push(`重渲染后值格还带停用样式：${o.after.valCls}`);
    if (!/^2\/2 启用/.test(String(o.head || ""))) bad.push(`重渲染卡头=${JSON.stringify(o.head)}`);
    if (JSON.stringify((o.toasts || []).map((t) => t.text)) !== JSON.stringify(["密钥已启用"])) {
      bad.push(`toast=${JSON.stringify(o.toasts)}`);
    }
    if (!/(^| )ok( |$)/.test(String((o.toasts || [])[0] ? o.toasts[0].cls : ""))) {
      bad.push(`成功回执不是绿色样式：${JSON.stringify((o.toasts || [])[0] || {})}`);
    }
    MNOTE.m5 = `请求 ${JSON.stringify(o.reqs)}；PUT body 的第 2 条 enabled=${put[0] && put[0].gateway.access_tokens[1].enabled}`
      + `、顶层键 ${put[0] ? Object.keys(put[0]).length : 0} 个；服务端=${o.server}；界面开关=${o.after && o.after.swOn}；`
      + `卡头「${o.head}」；toast ${JSON.stringify((o.toasts || []).map((t) => t.text))}；${bad.join(" | ") || "启停闭环对得上"}`;
    return !!(o.wait && o.wait.done) && bad.length === 0;
  }, () => (aSw.threw ? "realm 抛错 " + aSw.threw : MNOTE.m5));

  check("M6", "API 接入（D3 启停·失败支）：后端 400 时只有红色「保存失败」带后端原因，绿色「密钥已启用」必须消失且界面回落到服务端态", () => {
    if (aSwF.threw) return false;
    const o = aSwF.out || {};
    const t = o.toasts || [];
    const bad = [];
    if ((o.put || []).length !== 1) bad.push(`PUT ${(o.put || []).length} 次`);
    if (o.server !== false) bad.push(`后端拒绝了，服务端却变成 enabled=${o.server}`);
    if (t.length !== 1) bad.push(`toast ${t.length} 条：${JSON.stringify(t.map((x) => x.text))}`);
    if (/密钥已启用/.test(t.map((x) => x.text).join("|"))) bad.push("400 之后还弹绿色「密钥已启用」");
    if (!/(^| )err( |$)/.test(String(t[0] ? t[0].cls : ""))) bad.push(`失败 toast 不是红色样式：${JSON.stringify(t[0] || {})}`);
    if (!/^保存失败：/.test(String(t[0] ? t[0].text : ""))) bad.push(`失败 toast 开头不是「保存失败」：${JSON.stringify(t[0] && t[0].text)}`);
    if (String(t[0] ? t[0].text : "").indexOf("access_tokens") < 0) bad.push(`失败 toast 没带后端原因：${JSON.stringify(t[0] && t[0].text)}`);
    if (o.after && o.after.swOn !== false) bad.push(`失败后界面开关=${o.after && o.after.swOn}（应回落成关）`);
    if (o.moduleCfg !== false) bad.push(`重渲染后页内 cfg 也被带歪了（enabled=${o.moduleCfg}）`);
    MNOTE.m6 = `请求 ${JSON.stringify(o.reqs)}；toast=${JSON.stringify(t)}；服务端 enabled=${o.server}；`
      + `界面开关=${o.after && o.after.swOn}；${bad.join(" | ") || "失败支口径正确"}`;
    return bad.length === 0;
  }, () => (aSwF.threw ? "realm 抛错 " + aSwF.threw : MNOTE.m6));

  const nmWant = fixtureWith((c) => { c.gateway.access_tokens[0].name = "Trae 改过"; });
  check("M7", "API 接入（D3 用途标注）：改名发**恰好一次** PUT 且 body 带新名 + 绿回执；改成同值不得再发请求", () => {
    if (aNm.threw) return false;
    const o = aNm.out || {};
    const put = o.put || [];
    const bad = [];
    if (put.length !== 1) bad.push(`PUT 发出 ${put.length} 次`);
    if (put[0] && JSON.stringify(put[0]) !== JSON.stringify(nmWant)) bad.push("PUT body 不是改名后的完整配置");
    if (o.server !== "Trae 改过") bad.push(`服务端存的名字=${JSON.stringify(o.server)}`);
    if (o.newName !== "Trae 改过") bad.push(`重渲染后输入框值=${JSON.stringify(o.newName)}`);
    if (JSON.stringify((o.toasts || []).map((x) => x.text)) !== JSON.stringify(["用途标注已更新"])) {
      bad.push(`toast=${JSON.stringify(o.toasts)}`);
    }
    if (o.sameValueNewReqs !== 0) bad.push(`改成同名仍发了 ${o.sameValueNewReqs} 次请求`);
    MNOTE.m7 = `原名=${JSON.stringify(o.name0)} → PUT body 名字=${put[0] && put[0].gateway.access_tokens[0].name}；`
      + `服务端=${JSON.stringify(o.server)}；同值新增请求=${o.sameValueNewReqs}；`
      + `toast ${JSON.stringify((o.toasts || []).map((x) => x.text))}；${bad.join(" | ") || "编辑闭环对得上"}`;
    return bad.length === 0;
  }, () => (aNm.threw ? "realm 抛错 " + aNm.threw : MNOTE.m7));

  check("M8", "API 接入（添加密钥）：点「取消」零 PUT 且行数不变；点「生成并添加」PUT 里多一条空 id/value，服务端补齐后新行以密文出现", () => {
    if (aAdd.threw) return false;
    const o = aAdd.out || {};
    const bad = [];
    const op = o.open || {};
    if (op.title !== "添加接入密钥") bad.push(`弹窗标题=${JSON.stringify(op.title)}`);
    if (JSON.stringify(op.labels) !== JSON.stringify(["取消", "生成并添加"])) bad.push(`脚钮=${JSON.stringify(op.labels)}`);
    if (op.hasNameBox !== true) bad.push("弹窗里没有 name=name 输入框（取值会落空）");
    const c = o.afterCancel || {};
    if (c.putN !== 0) bad.push(`点「取消」后发出 ${c.putN} 次 PUT`);
    if (c.rows !== 2) bad.push(`点「取消」后表格变成 ${c.rows} 行`);
    if (c.open !== 0) bad.push(`点「取消」后弹窗还剩 ${c.open} 层`);
    if ((c.toasts || []).length !== 0) bad.push(`点「取消」却弹了 ${JSON.stringify((c.toasts || []).map((x) => x.text))}`);
    const put = o.put || [];
    if (put.length !== 1) bad.push(`确定支 PUT 发出 ${put.length} 次`);
    const added = put[0] ? put[0].gateway.access_tokens : [];
    if (added.length !== 3) bad.push(`PUT body 里密钥 ${added.length} 条（应为 3）`);
    const nu = added[2] || {};
    if (!(nu.id === "" && nu.value === "" && nu.name === "Cherry Studio" && nu.enabled === true)) {
      bad.push(`新增那条=${JSON.stringify(nu)}（id/value 该留空交服务端生成）`);
    }
    if (o.rows !== 3) bad.push(`重渲染后行数=${o.rows}`);
    const srv = (o.server || [])[2] || {};
    if (!srv.id || !srv.value) bad.push(`服务端没补齐 id/value：${JSON.stringify(srv)}`);
    if (o.row2 && o.row2.shown !== maskOf(srv.value)) {
      bad.push(`新行显示「${o.row2 && o.row2.shown}」应为密文「${maskOf(srv.value)}」`);
    }
    if (o.row2 && String(o.html || "").indexOf(String(srv.value)) >= 0) bad.push("新密钥明文出现在 DOM 里");
    if (!/^2\/3 启用/.test(String(o.head || ""))) bad.push(`卡头=${JSON.stringify(o.head)}（新增那条 enabled=true、Cursor 那条仍是停用 → 应为 2/3）`);
    if (JSON.stringify((o.toasts || []).map((x) => x.text)) !== JSON.stringify(["已生成密钥并生效"])) {
      bad.push(`toast=${JSON.stringify(o.toasts)}`);
    }
    MNOTE.m8 = `取消支：PUT ${c.putN} 次 / ${c.rows} 行 / 弹窗 ${c.open} 层；确定支：PUT ${put.length} 次，`
      + `body ${added.length} 条，服务端补齐 id=${srv.id}，界面 ${o.rows} 行、新行「${o.row2 && o.row2.shown}」、卡头「${o.head}」；`
      + `${bad.join(" | ") || "两条支路都对"}`;
    return !!(o.w && o.w.done) && bad.length === 0;
  }, () => (aAdd.threw ? "realm 抛错 " + aAdd.threw : MNOTE.m8));

  check("M9", "API 接入（删除密钥）：取消 / ✕ / 遮罩三种关闭都要**调用方已返回且零请求**；确定才发一次 PUT 且 body 少一条", () => {
    if (aDel.threw) return false;
    const o = aDel.out || {};
    const bad = [];
    for (const k of ["cancel", "x", "mask"]) {
      const c = o[k] || {};
      if (c.err) { bad.push(`${k}：${c.err}`); continue; }
      if (c.follow && c.follow.state !== "settled") {
        bad.push(`${k}：调用方 promise 处于 ${c.follow.state}（spent=${c.follow.spent}）—— 挂死了，`
          + "不能把它当成「没有副作用」");
        continue;
      }
      if ((c.sent || []).length !== 0) bad.push(`${k}：发出了 ${JSON.stringify(c.sent)}`);
      if (c.rows !== c.rows0) bad.push(`${k}：行数 ${c.rows0} → ${c.rows}`);
      if ((c.server || []).length !== 2) bad.push(`${k}：服务端剩 ${(c.server || []).length} 条`);
      if (c.open !== 0) bad.push(`${k}：弹窗剩 ${c.open} 层没关`);
    }
    const ok = o.ok || {};
    if (ok.err) bad.push(`确定：${ok.err}`);
    else {
      if (JSON.stringify(ok.sent) !== JSON.stringify(["PUT /admin/api/config",
        "GET /admin/api/config", "GET /admin/api/overview"])) {
        bad.push(`确定支请求序列=${JSON.stringify(ok.sent)}`);
      }
      if ((ok.put || []).length !== 1) bad.push(`确定支 PUT ${(ok.put || []).length} 次`);
      const left = ok.put && ok.put[0] ? ok.put[0].gateway.access_tokens.map((t) => t.id) : [];
      if (JSON.stringify(left) !== JSON.stringify(["tok-2"])) bad.push(`PUT body 里剩 ${JSON.stringify(left)}`);
      if (ok.rows !== 1) bad.push(`重渲染后行数=${ok.rows}`);
      if (JSON.stringify((ok.toasts || []).map((x) => x.text)) !== JSON.stringify(["密钥已删除"])) {
        bad.push(`toast=${JSON.stringify(ok.toasts)}`);
      }
    }
    MNOTE.m9 = `cancel/x/mask 的 promise 态=${["cancel", "x", "mask"].map((k) => `${k}:${((o[k] || {}).follow || {}).state}`).join(",")}`
      + `；各自发出的请求数=${["cancel", "x", "mask"].map((k) => ((o[k] || {}).sent || []).length).join(",")}；`
      + `确定支 ${JSON.stringify(ok.sent || [])}、body 剩 ${JSON.stringify((ok.put && ok.put[0] ? ok.put[0].gateway.access_tokens.map((t) => t.id) : []))}；`
      + `${bad.join(" | ") || "四支全对"}`;
    return bad.length === 0;
  }, () => (aDel.threw ? "realm 抛错 " + aDel.threw : MNOTE.m9));
  /* ---------- settings.js ---------- */
  const PARAM_BINDINGS = [
    ["gateway", "port", 1], ["gateway", "max_concurrent_requests", 0],
    ["gateway", "attempt_timeout_seconds", 1], ["gateway", "request_total_budget_seconds", 1],
    ["scheduling", "max_active_per_model", 1], ["scheduling", "fail_threshold", 1],
    ["scheduling", "retry_per_request", 0], ["scheduling", "retry_backoff_seconds", 0],
    ["scheduling", "cooldown_seconds", 0], ["scheduling", "cooldown_seconds_plan", 0],
    ["gateway", "retention_days", 1], ["gateway", "heartbeat_seconds", 1],
  ];
  check("M10", "系统设置页能在 realm 里真跑：首屏发出的就是生产端点 GET /admin/api/config（三卡 + 启停钮都在）", () => {
    if (sR.threw) return false;
    const o = sR.out || {};
    MNOTE.m10 = `请求=${JSON.stringify(o.reqs)}；卡 ${JSON.stringify(o.heads)}；输入 ${(o.ins || []).length} 个；`
      + `保存钮 disabled=${o.saveDisabled} 文案「${o.saveText}」；徽章=${!!o.badge}；`
      + `重启=${!!o.restart} 停止=${!!o.stopBtn}；err=${o.err || "无"}`;
    return !o.err && JSON.stringify(o.reqs) === JSON.stringify(["GET /admin/api/config"])
      && (o.heads || []).length === 3 && !!o.restart && !!o.stopBtn
      && o.saveText === "保存配置" && o.hasExport === false;
  }, () => (sR.threw ? "realm 编译/执行抛错 " + sR.threw : MNOTE.m10));

  check("M11", "系统设置：12 个参数输入框**逐个**绑到生产配置字段（sec/name/value 三样对齐 + min 与 schema 下限一致）", () => {
    if (sR.threw) return false;
    const o = sR.out || {};
    const ins = o.ins || [];
    const bad = [];
    if (ins.length !== PARAM_BINDINGS.length) bad.push(`页面上 ${ins.length} 个参数输入，期望 ${PARAM_BINDINGS.length} 个`);
    const seen = new Set(ins.map((x) => `${x.sec}.${x.name}`));
    PARAM_BINDINGS.forEach(([sec, name, min]) => {
      const key = `${sec}.${name}`;
      if (!seen.has(key)) { bad.push(`缺输入框 ${key}`); return; }
      const hit = ins.filter((x) => x.sec === sec && x.name === name)[0];
      const want = CONFIG_FIXTURE[sec][name];
      if (String(hit.value) !== String(want)) bad.push(`${key} 框里是「${hit.value}」，配置里是 ${want}`);
      if (String(hit.min) !== String(min)) bad.push(`${key} 的 min=${hit.min}，schema 下限是 ${min}`);
    });
    for (const x of ins) {
      if (!PARAM_BINDINGS.some((p) => p[0] === x.sec && p[1] === x.name)) bad.push(`多出一个 ${x.sec}.${x.name}`);
      if (x.type !== "number") bad.push(`${x.sec}.${x.name} 的 type=${x.type}`);
    }
    MNOTE.m11 = `对不上的 ${bad.length} 处 / 共 ${ins.length} 个绑定；`
      + `x=${(ins[4] || {}).value} y=${(ins[5] || {}).value} m=${(ins[6] || {}).value} `
      + `退避=${(ins[7] || {}).value}；${bad.join(" | ") || "逐字段对上"}`;
    return bad.length === 0 && ins.length === PARAM_BINDINGS.length;
  }, () => (sR.threw ? "realm 抛错 " + sR.threw : MNOTE.m11));

  check("M12", "系统设置：脏态徽章与保存按钮使能**同源**（干净=无徽章+点不动；改一处=有徽章+可点；徽章唯一且在最前）", () => {
    if (sD.threw) return false;
    const o = sD.out || {};
    const s0 = o.s0 || {}; const s1 = o.s1 || {}; const s2 = o.s2 || {};
    const bad = [];
    // 方向二：徽章干净 ⇒ 按钮不可点
    if (!(s0.badge === false && s0.disabled === true && s0.dirty === false)) {
      bad.push(`首屏 徽章=${s0.badge} 按钮 disabled=${s0.disabled} dirty=${s0.dirty}（应为 false/true/false）`);
    }
    // 方向一：徽章说脏 ⇒ 按钮可点（面板实测的正是这一向：少一行解禁 → 徽章在、按钮永远灰）
    if (!(s1.badge === true && s1.disabled === false && s1.dirty === true)) {
      bad.push(`改动后 徽章=${s1.badges} 枚「${s1.badgeText}」 按钮 disabled=${s1.disabled} dirty=${s1.dirty}`
        + ` —— 两者必须同时翻（徽章在而按钮灰 = 用户点不动；按钮可点而徽章不在 = 用户不知道有未保存修改）`);
    }
    if (s1.badges !== 1) bad.push(`改动后徽章 ${s1.badges} 枚`);
    if (o.badgeIsFirst !== true) bad.push("徽章没插到页头最前面");
    if (s1.badgeText !== "有未保存修改") bad.push(`徽章文案=${JSON.stringify(s1.badgeText)}`);
    if (!(s2.badge === true && s2.disabled === false && s2.badges === 1)) {
      bad.push(`第二次改动后徽章=${s2.badges} 按钮 disabled=${s2.disabled}`);
    }
    MNOTE.m12 = `首屏 徽章=${s0.badge}/disabled=${s0.disabled}/dirty=${s0.dirty}；改后 徽章=${s1.badges} 枚`
      + `「${s1.badgeText}」/disabled=${s1.disabled}/dirty=${s1.dirty}；再改 徽章=${s2.badges}/disabled=${s2.disabled}；`
      + `页头顺序 ${JSON.stringify(o.headOrder)}；${bad.join(" | ") || "两向同源"}`;
    return bad.length === 0;
  }, () => (sD.threw ? "realm 抛错 " + sD.threw : MNOTE.m12));

  check("M13", "系统设置：正整数过滤即时剔除非数字；清空 = 未修改（不置脏、不发请求、不把配置写成 null）", () => {
    if (sD.threw) return false;
    const o = sD.out || {};
    const bad = [];
    if (o.cleaned !== "1239") bad.push(`键入「12a3-.x9」过滤后实得「${o.cleaned}」（应为 1239）`);
    if (o.cleanedEmpty !== "") bad.push(`清空后值格=${JSON.stringify(o.cleanedEmpty)} 应为空串`);
    const sc = o.sClean || {};
    if (!(sc.badge === false && sc.disabled === true && sc.dirty === false)) {
      bad.push(`清空被当成修改：徽章=${sc.badge} disabled=${sc.disabled} dirty=${sc.dirty}`);
    }
    if (sc.reqs !== (o.s0 || {}).reqs) bad.push(`清空多发 ${sc.reqs - (o.s0 || {}).reqs} 次请求`);
    if (o.cooldownAfterClear !== CONFIG_FIXTURE.scheduling.cooldown_seconds) {
      bad.push(`配置里 cooldown_seconds 被写成 ${JSON.stringify(o.cooldownAfterClear)}`);
    }
    if (o.yInCfg !== 8) bad.push(`两次改动后页内 cfg.scheduling.fail_threshold=${JSON.stringify(o.yInCfg)}（最后一次是 8）`);
    MNOTE.m13 = `过滤后「${o.cleaned}」；清空后 徽章=${sc.badge}/disabled=${sc.disabled}；`
      + `cooldown_seconds=${o.cooldownAfterClear}；页内 y=${o.yInCfg}；请求 ${JSON.stringify(o.reqs)}；`
      + `${bad.join(" | ") || "过滤与未修改语义都在"}`;
    return bad.length === 0;
  }, () => (sD.threw ? "realm 抛错 " + sD.threw : MNOTE.m13));
  const saveWant = fixtureWith((c) => { c.scheduling.fail_threshold = 7; });
  check("M14", "系统设置（全站唯一二段保存）：改了不点保存**零 PUT**；点保存恰好一次 PUT 且 body 是改动后的完整配置，成功后回到干净态", () => {
    if (sS.threw) return false;
    const o = sS.out || {};
    const put = o.put || [];
    const bad = [];
    if ((o.before || {}).put !== 0) bad.push(`还没点保存就发了 ${(o.before || {}).put} 次 PUT`);
    if (put.length !== 1) bad.push(`点保存后 PUT ${put.length} 次`);
    if (put[0] && JSON.stringify(put[0]) !== JSON.stringify(saveWant)) {
      bad.push("PUT body 不是「改动后的完整配置」（只发增量 / 丢字段 / 改动没带上都算）");
    }
    if (JSON.stringify(o.reqs) !== JSON.stringify(["GET /admin/api/config", "PUT /admin/api/config",
      "GET /admin/api/config"])) bad.push(`请求序列=${JSON.stringify(o.reqs)}`);
    if (o.server !== 7) bad.push(`服务端 fail_threshold=${JSON.stringify(o.server)}`);
    if (JSON.stringify((o.toasts || []).map((t) => t.text)) !== JSON.stringify(["配置已保存并热重载生效"])) {
      bad.push(`toast=${JSON.stringify(o.toasts)}`);
    }
    if (!(o.badge === false && o.disabled === true && o.dirty === false)) {
      bad.push(`保存成功后 徽章=${o.badge} disabled=${o.disabled} dirty=${o.dirty}（应回到干净态）`);
    }
    if (o.val !== "7") bad.push(`重渲染后 y 输入框值=${JSON.stringify(o.val)}`);
    if (o.inputs !== 12) bad.push(`重渲染后参数输入框 ${o.inputs} 个`);
    MNOTE.m14 = `点保存前 PUT ${(o.before || {}).put} 次；点后 ${put.length} 次，body 的 y=`
      + `${put[0] && put[0].scheduling.fail_threshold}、顶层键 ${put[0] ? Object.keys(put[0]).length : 0} 个；`
      + `服务端 y=${o.server}；界面 y=${o.val}；徽章=${o.badge}/disabled=${o.disabled}；`
      + `${bad.join(" | ") || "二段保存闭环对得上"}`;
    return !!(o.w && o.w.done) && bad.length === 0;
  }, () => (sS.threw ? "realm 抛错 " + sS.threw : MNOTE.m14));

  check("M15", "系统设置（保存失败支）：后端 400 只有红色「保存失败」带后端原因，绿色「配置已保存并热重载生效」必须消失，服务端未采纳且页面仍脏", () => {
    if (sSF.threw) return false;
    const o = sSF.out || {};
    const t = o.toasts || [];
    const bad = [];
    if ((o.put || []).length !== 1) bad.push(`PUT ${(o.put || []).length} 次`);
    if (o.serverBudget !== CONFIG_FIXTURE.gateway.request_total_budget_seconds) {
      bad.push(`后端拒绝了，服务端预算却变成 ${o.serverBudget}`);
    }
    if (t.length !== 1) bad.push(`toast ${t.length} 条：${JSON.stringify(t.map((x) => x.text))}`);
    if (t.map((x) => x.text).join("|").indexOf("配置已保存并热重载生效") >= 0) bad.push("400 之后弹了绿色「已保存」");
    if (!/(^| )err( |$)/.test(String(t[0] ? t[0].cls : ""))) bad.push(`失败 toast 不是红色样式：${JSON.stringify(t[0] || {})}`);
    if (!/^保存失败：/.test(String(t[0] ? t[0].text : ""))) bad.push(`失败 toast 开头不是「保存失败」：${JSON.stringify(t[0] && t[0].text)}`);
    if (String(t[0] ? t[0].text : "").indexOf("必须 >=") < 0) bad.push(`失败 toast 没带后端原因：${JSON.stringify(t[0] && t[0].text)}`);
    if (!(o.badge === true && o.disabled === false && o.dirty === true)) {
      bad.push(`失败后应仍是脏态：徽章=${o.badge} disabled=${o.disabled} dirty=${o.dirty}`);
    }
    if (o.val !== "1") bad.push(`失败后输入框值=${JSON.stringify(o.val)}（用户填的应当还在）`);
    MNOTE.m15 = `toast=${JSON.stringify(t)}；服务端预算=${o.serverBudget}；界面值=${o.val}；`
      + `脏态 徽章=${o.badge}/disabled=${o.disabled}；${bad.join(" | ") || "失败支口径正确"}`;
    return !!(o.w && o.w.done) && bad.length === 0;
  }, () => (sSF.threw ? "realm 抛错 " + sSF.threw : MNOTE.m15));

  check("M16", "系统设置（维护区破坏性动作）：取消 → 零 POST 且调用方已返回；确定 → 恰好一次 POST（停止进「网关已停止」态、重启弹绿回执并进等待态）", () => {
    if (sStop.threw || sRe.threw) return false;
    const sp = sStop.out || {};
    const re = sRe.out || {};
    const bad = [];
    const c = sp.cancel || {};
    if (c.err) bad.push(`停止·取消：${c.err}`);
    else {
      if (c.follow && c.follow.state !== "settled") bad.push(`停止·取消：调用方 ${c.follow.state}（挂死）`);
      if ((c.sent || []).length !== 0) bad.push(`停止·取消：发出了 ${JSON.stringify(c.sent)}`);
      if (c.stopped !== false) bad.push("停止·取消：页面却进入了停止态");
      if (c.keptCards !== 3) bad.push(`停止·取消：三张卡变成 ${c.keptCards} 张`);
      if (c.open !== 0) bad.push(`停止·取消：弹窗剩 ${c.open} 层`);
      if (!/停止后网关下线/.test(String(c.bodyText))) bad.push(`停止·取消：确认文案=${JSON.stringify(c.bodyText)}`);
    }
    const k = sp.ok || {};
    if (k.err) bad.push(`停止·确定：${k.err}`);
    else {
      if (JSON.stringify(k.sent) !== JSON.stringify(["POST /admin/api/system/stop"])) {
        bad.push(`停止·确定：发出了 ${JSON.stringify(k.sent)}`);
      }
      if (k.stopped !== true) bad.push("停止·确定：页面没有进入「网关已停止」态");
      if (k.keptCards !== 1) bad.push(`停止·确定：停止态之外还剩 ${k.keptCards} 张卡`);
      if ((k.toasts || []).length !== 0) bad.push(`停止·确定：额外弹了 ${JSON.stringify(k.toasts)}`);
      if (k.follow && k.follow.state !== "settled") bad.push(`停止·确定：调用方 ${k.follow.state}`);
    }
    if (re.err) bad.push(`重启：${re.err}`);
    else {
      const posts = (re.sent || []).filter((x) => x.indexOf("POST") === 0);
      if (JSON.stringify(posts) !== JSON.stringify(["POST /admin/api/system/restart"])) {
        bad.push(`重启·确定：发出了 ${JSON.stringify(re.sent)}`);
      }
      if (JSON.stringify((re.toasts || []).map((x) => x.text)) !== JSON.stringify(["重启已受理，等待恢复…"])) {
        bad.push(`重启回执 toast=${JSON.stringify(re.toasts)}`);
      }
      if (re.waiting !== ".5") bad.push(`重启等待态没把任务卡压暗（opacity=${JSON.stringify(re.waiting)}）`);
    }
    MNOTE.m16 = `停止·取消 ${JSON.stringify(c.sent || [])} / promise ${(c.follow || {}).state}；`
      + `停止·确定 ${JSON.stringify(k.sent || [])} 停止态=${k.stopped}；`
      + `重启·确定 POST=${JSON.stringify((re.sent || []).filter((x) => x.indexOf("POST") === 0))}`
      + ` 等待态 opacity=${re.waiting} 待触发定时器 ${re.timers} 个（恢复轮询不在判据内，见证据文档负面清单）；`
      + `${bad.join(" | ") || "两条破坏性动作都要确认才落地"}`;
    return bad.length === 0;
  }, () => ((sStop.threw || sRe.threw) ? "realm 抛错 " + (sStop.threw || sRe.threw) : MNOTE.m16));

  check("M17", "两页真跑产物里没有坏插值（undefined / [object Object] / 残留插值符）——判的是产物，不是源码字面", () => {
    const a = aR.out || {};
    const s = sR.out || {};
    const samples = [["API 接入", `${a.text || ""} ${a.html || ""}`, aR.threw],
      ["系统设置", `${s.text || ""} ${s.html || ""}`, sR.threw]];
    const bad = [];
    samples.forEach(([name, txt, threw]) => {
      if (threw) { bad.push(`${name}：realm 抛错 ${threw}`); return; }
      if (!String(txt).trim()) { bad.push(`${name}：没有产物可判（页面没跑起来）`); return; }
      const hits = ["undefined", "[object Object]", "${"].filter((p) => String(txt).indexOf(p) >= 0);
      if (hits.length) {
        bad.push(`${name}：出现 ${hits.join(",")} —— 「${(String(txt).match(/.{0,20}(undefined|\[object Object\])\S{0,14}/g) || []).slice(0, 2).join(" / ")}」`);
      }
    });
    MNOTE.m17 = `${samples.map(([n, t]) => `${n} ${String(t).length} 字符`).join("；")}；`
      + `${bad.join(" | ") || "两页产物干净"}`;
    return bad.length === 0;
  }, () => MNOTE.m17);


  // 🔴 Z 段 = **门自己的**语义自测：可见性判据必须按属性语义走，
  //    不能靠"属性串里出现过 hidden 字样"这种巧合（第十轮 ix 指出那条红是字面巧合）。
  //    判据不测自己，就会像前九轮那样"门变绿而判据已经坏了"。
  check("Z1", "可见性判据 = **内联属性 ⊕ 样式表命中**（`.hidden` 这类工具类按 base.css 算隐藏）",
    () => {
      const cases = [
        // 类名命中样式表里的隐藏规则 → **算隐藏**（本项目 `.hidden{display:none!important}`
        // 就是干这个的；第十轮把它当成"字面巧合不算"是错的，第十一轮 PM/ix 各自打到）
        [' class="alert hidden"', true], [' class="hidden"', true],
        [' class="alert not-a-utility-class-in-this-css"', false],
        [' id="ops-dot"', false],
        [' hidden', true], [' HIDDEN', true],
        [' class="x" hidden', true], [' aria-hidden', true], [' aria-hidden="true"', true],
        [' ARIA-HIDDEN="TRUE"', true], [' aria-hidden="false"', false],
        [' style="DISPLAY: NONE"', true], [' style="display:none"', true],
        [' style="opacity:0"', true], [' style="opacity:0.5"', false],
        [' style="height:0;overflow:hidden"', true], [' style="height:160px"', false],
        [' style="max-height:0"', true], [' style="font-size:0"', true],
        [' style="color:transparent"', true], [' style="clip-path:inset(50%)"', true],
        [' style="zoom:0"', true], [' style="transform:translate(-9999px,0)"', true],
        [' style="visibility:collapse"', true], [' style="left:-9999px"', true],
        [' style="transform:scale(0)"', true], [' style="padding:0"', false],
      ];
      const wrong = cases.filter(([a, want]) => isInvisible(a) !== want)
        .map(([a, want]) => `${a}→期望${want}`);
      __note = wrong.join(" | ");
      return wrong.length === 0;
    }, () => __note);

  // 🔴 Z2 = 执行环境自测（第十轮 R-3）。被测名集**由宿主派生**，不再是手写的 5 个名字
  //    （第十一轮 ix B11-3 实测：只漏 `global` 一个名字，页面就能真读 `process.env.HOME`
  //    而 Z2 照样 ok:true —— 手写黑名单的覆盖面等于作者的记性）。
  //    派生法：宿主 globalThis 的名字全集，减去 ①空 vm 上下文本来就有的 ECMAScript 内置、
  //    ②浏览器里确实存在、我们允许注入的 Web 全局 —— 剩下的就是"只有 Node 才有"的一批，
  //    它们在门执行前端源码的那个上下文里必须一律取不到。
  const ECMA_GLOBALS = new vm.Script("Object.getOwnPropertyNames(globalThis)")
    .runInContext(vm.createContext({}));
  const BROWSER_GLOBALS = new Set([
    "window", "self", "document", "navigator", "location", "history", "screen",
    "localStorage", "sessionStorage", "fetch", "XMLHttpRequest", "WebSocket", "console",
    "alert", "confirm", "prompt", "setTimeout", "clearTimeout", "setInterval",
    "clearInterval", "requestAnimationFrame", "getComputedStyle", "matchMedia", "Image",
    "Event", "CustomEvent", "URL", "URLSearchParams", "Blob", "FileReader", "FormData",
    "MutationObserver", "IntersectionObserver", "ResizeObserver", "Intl", "structuredClone",
    "crypto", "performance", "Notification", "HTMLElement", "Node",
  ]);
  const NODE_ONLY = Object.getOwnPropertyNames(globalThis)
    .filter((g) => !ECMA_GLOBALS.includes(g) && !BROWSER_GLOBALS.has(g));
  const leaked = NODE_ONLY.filter((g) => browserFn(`return typeof ${g};`)() !== "undefined");
  // 派生完整性的 canary：不是覆盖面，只是"派生本身塌了"时的报警（空集合会让判据空过）。
  // 只列 ESM 宿主 globalThis 上**真实存在**的那几个（`require`/`__dirname` 是 CJS 包装器
  // 注入的，本来就不在 globalThis 上 —— 拿它们当 canary 会永远红，那是判据写错不是门坏）。
  const derivationBroken = ["process", "Buffer", "global"]
    .filter((g) => !NODE_ONLY.includes(g));
  check("Z2", "执行环境不含 Node 专有全局（名集由宿主派生；派生集本身带 canary）",
    NODE_ONLY.length >= 8 && derivationBroken.length === 0 && leaked.length === 0,
    `派生 ${NODE_ONLY.length} 个；${derivationBroken.length ? "派生漏掉 " + derivationBroken.join(",")
      : (leaked.length ? "泄漏 " + leaked.join(",") : "全部取不到")}`);

  // 🔴 Z5 = **realm 桥**必须封死（第十二轮 eng-B S-52）。Z2 只查"上下文里有没有 Node 全局名"，
  //    但宿主函数/对象本身带着**宿主的 realm** 进来了：面板实测页面里
  //    `esc.constructor("return process")()` 直接拿到本进程 `Function`，读 `HOME` 写 stdout，
  //    Z2/Z3 全绿、84 项全绿、`可红 104/104` —— 那一刻"门的输出"是页面自己写的字。
  //    判据不是背那几个名字：拿 `INJECTED` 注册表（**每个真被送进过 realm 的宿主值**，
  //    由 browserFn 自己登记）在 realm 内做 BFS，对可达的每个函数问一句
  //    "你的 constructor 是不是本 realm 的 Function" —— 不是就是桥还开着。
  //    ⚠ 探测**不得调用**被注入的假件：第一版为了拿结果真去 `f("return typeof process")()`，
  //    于是 GET 被当成"用户请求了一次"记进 calls，I5/I8/I9 三条"不该发请求"的判据
  //    当场被自己的探针污染成红（实测 3 条红）。判据不该改动被测现场，这条也写进来。
  //    作用域边界（免得又只长一张白名单）：
  //      ✅ 管：入口实参、宿主调用的**返回值**、对象属性、原型链上的函数；
  //      ❌ 不管：页面自己在 realm 内新建的对象（它的 intrinsic 本来就出不去）。
  const controlHost = () => ({ nested() { return 1; } });
  const bridgeLeaks = browserFn("vals", "probeHost", `
    const leaks = [];
    const seen = new WeakSet();
    const testFn = (f, path) => {
      if (typeof f !== "function") return;
      let c;
      try { c = f.constructor; } catch (e) { return; }
      if (c === undefined) return;
      if (c !== Function) leaks.push(path);
    };
    const walk = (v, path, d) => {
      if (d > 3 || v === null) return;
      if (typeof v !== "object" && typeof v !== "function") return;
      if (seen.has(v)) return;
      seen.add(v);
      testFn(v, path);
      let names = [];
      try { names = Object.getOwnPropertyNames(v); } catch (e) {}
      for (const k of names) {
        let x;
        try { x = v[k]; } catch (e) { continue; }
        testFn(x, path + "." + k);
        walk(x, path + "." + k, d + 1);
      }
      let p = null;
      try { p = Object.getPrototypeOf(v); } catch (e) {}
      if (p && !seen.has(p)) {
        testFn(p.constructor, path + "[[proto]].constructor");
        walk(p, path + "[[proto]]", d + 1);
      }
    };
    for (let i = 0; i < vals.length; i += 1) walk(vals[i], "injected[" + i + "]", 0);
    // 返回值那一侧：用一个**只为探测造的**宿主假件，调它不影响任何判据的现场
    const ret = probeHost();
    testFn(ret, "returned");
    testFn(ret.nested, "returned.nested");
    testFn(ret.nested.constructor, "returned.nested.constructor");
    walk(ret, "returned", 0);
    return leaks;
  `)([...INJECTED], controlHost);
  check("Z5", "跨 realm 桥封死：注入面与返回值上的可达函数都不带宿主 realm（覆盖集由 INJECTED 派生）",
    INJECTED.length >= 8 && Array.isArray(bridgeLeaks) && bridgeLeaks.length === 0,
    `登记注入值 ${INJECTED.length} 个${Array.isArray(bridgeLeaks) && bridgeLeaks.length
      ? "；桥可通：" + bridgeLeaks.slice(0, 4).join(", ") : "；全部走不出去"}`);

  // 🔴 Z4 = 样式表派生本身的可判别自测（第十二轮 ix B12-3：上一版注释说"含 @media"，
  //    实现把 at-rule 整块跳过 → 派生集只剩 `hidden` 一个类名，藏进 @media 的规则全查不出）。
  //    用一段合成样式表喂给同一个 `cssHiding()`，正反两向都要对：
  //    `@media`/`@supports`/`@layer` 里的隐藏必须进集合；`@keyframes`、伪元素、后代裸标签不能进。
  const probeCss = cssHiding([
    ".plain-hide { display: none; }",
    "@media (max-width: 900px) { .media-hide { display: none; } }",
    "@supports (display: grid) { .supports-hide { visibility: hidden; } }",
    "@layer components { .layered-hide { opacity: 0; } }",
    "@keyframes fade { from { opacity: 0 } to { opacity: 1 } }",
    ".nav-item span { display: none; }",
    ".card::after { display: none; }",
  ].join("\n"));
  check("Z4", "样式表派生自测：@media/@supports/@layer 的隐藏要进集合；@keyframes/伪元素/后代裸标签不能进",
    probeCss.classes.has("plain-hide") && probeCss.classes.has("media-hide")
    && probeCss.classes.has("supports-hide") && probeCss.classes.has("layered-hide")
    && !probeCss.classes.has("fade") && !probeCss.classes.has("span")
    && !probeCss.classes.has("card") && HIDDEN_BY_CSS.classes.has("hidden"),
    `派生=${[...probeCss.classes].join(",")}；本项目样式表派生出 ${HIDDEN_BY_CSS.classes.size} 类`
    + `/${HIDDEN_BY_CSS.ids.size} id/${HIDDEN_BY_CSS.tags.size} 标签`);

  await Promise.all(checks.filter((c) => c.pending).map(async (c) => {
    try {
      c.ok = !!(await c.pending);
    } catch (e) {
      c.detail = `求值抛错 ${e && e.name}: ${String(e && e.message).slice(0, 120)}`;
    }
    delete c.pending;
  }));

  // 🔴 Z3 = "门有没有被页面代码打瞎"本身必须是判据（第十一轮 eng-B B11-1）。
  //    A/B/C 段的输入是 eager 求值的：页面函数一抛错，以前是**整个子进程崩掉**，
  //    父进程只能靠"崩了算红"推定出一个没有证据的 ✓（实测 99/100 被报成 100/100）。
  //    现在同步抛错经 `safePageFn` 记一笔 + 返回哨兵；异步 reject 由
  //    `process.on("unhandledRejection")` 兜网记同一份账。
  //    ⚠ **求值时机**（2026-09-29 复采实测）：兜网是在**宏任务边界之后**才记账的，
  //    所以 Z3 必须排在全部判据（含异步判据）之后、并先排空两次宏任务，否则
  //    "Z3 已经判完了，记录才落进来" —— 那条新变异当时就是 `未红：Z3`。
  await new Promise((r) => setTimeout(r, 0));
  await new Promise((r) => setTimeout(r, 0));
  check("Z3", "页面函数对全部判据输入**未抛错、未留下未处理的拒绝**（不许用崩溃冒充证据）",
    PAGE_THROWS.length === 0, PAGE_THROWS.join(" | "));
  return { checks, errors };
}

/* ==================== 变异表：每条 check 都要能红（IX-5）==================== */

const MUTATIONS = [
  { why: "横幅改用 info 样式（不再是告警）", file: "dash",
    from: 'class="alert alert-warn"', to: 'class="alert alert-info"', kills: ["A1", "A10", "A13"] },
  { why: "渲染器丢掉后端文案（只剩标题壳）", file: "dash",
    from: '${esc(w.message || "")}', to: "", kills: ["A2", "A3", "A4", "A6", "A7", "A8", "A9"] },
  { why: "只渲染第一条告警，其余静默丢弃", file: "dash",
    from: "list.map((w) =>", to: "list.slice(0, 1).map((w) =>", kills: ["A5", "A10", "A13"] },
  { why: "文案不做转义（注入面）", file: "dash",
    from: '${esc(w.message || "")}', to: '${w.message || ""}', kills: ["A14"] },
  { why: "空数组也渲染外壳", file: "dash",
    from: 'if (!list.length) return "";',
    to: 'if (!list.length) return "<div class=\\"alert alert-warn\\"></div>";', kills: ["A11"] },
  { why: "非数组 warnings 不做类型兜底（运行时抛错）", file: "dash",
    from: "const list = Array.isArray(warnings) ? warnings : [];",
    to: "const list = warnings;", kills: ["A12", "Z3"] },
  { why: "去掉「最近错误」表头措辞", file: "dash", from: ">最近错误<", to: ">错误<", kills: ["B1"] },
  { why: "去掉「冷却剩余」表头措辞", file: "dash", from: ">冷却剩余<", to: ">剩余<", kills: ["B2"] },
  { why: "熔断原因从正文消失", file: "dash",
    from: '${esc(r.last_error || "—")}', to: "x", kills: ["B3", "B5"] },
  { why: "冷却剩余不带单位（徽章与「冷却剩余」列同源，一处丢单位两处都丢）", file: "dash",
    from: "return n > 0 ? `${n}s` : \"—\";", to: "return n > 0 ? `${n}` : \"—\";",
    kills: ["B4", "C6", "C12"] },
  { why: "少渲染一列（与表头列数不一致）", file: "dash",
    from: '<td class="num">${r.in_flight || 0}</td>', to: "", kills: ["B6"] },
  { why: "🔴 IX-4 回归：`available===false` 兜底吃掉冷却/失效", file: "dash",
    from: "  switch (r.status) {",
    to: '  if (r.available === false) return `<span class="badge b-muted" '
      + 'title="Key 或所属产品已停用">停用</span>`;\n  switch (r.status) {',
    kills: ["C2", "C3", "C4", "C5", "C6", "C7"] },
  { why: "active 分支拼错（落兜底）", file: "dash",
    from: 'case "active": return `<span class="badge b-ok" title="可承接请求">可用</span>`;',
    to: 'case "active_": return `<span class="badge b-ok" title="可承接请求">可用</span>`;',
    kills: ["C1", "C5", "C9"] },
  { why: "cooldown 分支被删", file: "dash",
    from: 'case "cooldown": return `<span class="badge b-cool" title="${',
    to: 'case "cooldown_": return `<span class="badge b-cool" title="${',
    kills: ["C2", "C5", "C6", "C9", "C12"] },
  { why: "🔴 本轮复采：冷却**已到期**那一支的文案没人管 —— 改成「稍后自动回池」"
      + "（用户读成还要再等）时 C6/C12 纹丝不动，因为它们只走 remaining>0 的分支",
    file: "dash",
    from: ': "已到期，下次选路即回池"}',
    to: ': "稍后自动回池"}',
    kills: ["C18"] },
  { why: "🔴 面板 S-18：冷却已到期仍印「剩余 0s」这种自相矛盾口径", file: "dash",
    from: '"已到期，下次选路即回池"', to: '`剩余 ${left}s`', kills: ["C11"] },
  { why: "invalid 也显示成「停用」", file: "dash",
    from: 'case "invalid": return `<span class="badge b-err" title="上游回 404：该模型名无效 —— 到「接入模型资源」页更换映射（不会自愈）">模型名无效</span>`;',
    to: 'case "invalid": return `<span class="badge b-muted" title="Key 或所属产品已停用">停用</span>`;',
    kills: ["C3"] },
  { why: "🔴 第十一轮 PM B11-1：把「更换映射」指回「资源池设置」页（那一页只有档位/优先级/"
      + "移除映射，没有 `rv-addmap`）—— 页名真实存在，所以 J2 不响，必须靠归属判据",
    file: "dash", from: "到「接入模型资源」页更换映射", to: "到「网关模型管理」页更换映射",
    kills: ["C3", "J3"] },
  { why: "🔴 第十二轮 PM B-12-2：把『需人工确认』的分叉摘掉 —— 状态文件读不动时徽章照样说无需处理",
    file: "dash",
    from: '/(读不动|不可信)/.test(r.last_error || "")',
    to: '/never-match-this-state-zz/.test(r.last_error || "")', kills: ["C17"] },
  { why: "🔴 面板 S-18：invalid 直出英文枚举、不说要不要动手", file: "dash",
    from: ">模型名无效</span>`;", to: ">invalid</span>`;", kills: ["C3", "C9"] },
  { why: "停用的提示回到误导文案（只说开关，401 判死的资源会被支去翻已打开的开关）",
    file: "dash",
    from: 'case "disabled": return `<span class="badge b-muted" title="两种成因之一：资源开关已关闭（打开即恢复），或凭据被上游拒绝 401（需到「接入模型资源」页更换 Key，不会自愈）—— 见「最近错误」列">已停用</span>`;',
    to: 'case "disabled": return `<span class="badge b-muted" title="资源开关已关闭 —— 打开开关即恢复">已停用</span>`;',
    kills: ["C4"] },
  { why: "未知状态被兜底成「正常」", file: "dash",
    from: 'default: return `<span class="badge b-muted" title="网关未识别的状态值（可能是新版本引入的态）">${esc(String(r.status))}</span>`;',
    to: 'default: return `<span class="badge b-ok" title="可承接请求">可用</span>`;',
    kills: ["C7"] },
  { why: "🔴 面板 S-18：未知状态染红（用户读成「凭据被判死」）", file: "dash",
    from: 'default: return `<span class="badge b-muted" title="网关未识别的状态值（可能是新版本引入的态）">${esc(String(r.status))}</span>`;',
    to: 'default: return `<span class="badge b-err" title="上游已拒绝（Key 或模型名失效）—— 需在「接入模型资源」页更换，不会自愈">${esc(String(r.status))}</span>`;',
    kills: ["C10"] },
  { why: "🔴 面板 S-19：非冷却行也印秒数（停用/判死的资源带着冷却剩余数字，用户以为马上回池）",
    file: "dash",
    from: '${r.status === "cooldown" ? fmtCooldown(r.cooldown_remaining_ms) : "—"}',
    to: "${fmtCooldown(r.cooldown_remaining_ms)}",
    kills: ["C13"] },
  { why: "🔴 面板 S-19：未知状态不再说明「未识别」（用户无从判断是不是新版本引入的态）",
    file: "dash",
    from: 'default: return `<span class="badge b-muted" title="网关未识别的状态值（可能是新版本引入的态）">${esc(String(r.status))}</span>`;',
    to: 'default: return `<span class="badge b-muted">${esc(String(r.status))}</span>`;',
    kills: ["C14"] },
  { why: "🔴 面板 S-18 ESCAPE-1：总览按 kind 过滤后再交给渲染器", file: "dash",
    from: "${configWarnings(data.warnings)}",
    to: '${configWarnings(data.warnings.filter((w) => w.kind === "param_shadowed"))}',
    kills: ["A15"] },
  { why: "新增 Key 丢掉 product", file: "res", from: 'product: first.product || "",', to: "",
    kills: ["D2"] },
  { why: "新增 Key 丢掉厂商归属", file: "res", from: 'vendor: first.vendor || "",', to: "",
    kills: ["D3"] },
  { why: "🔴 面板 E-1：表格不再调用徽章函数（整表硬编码绿标）", file: "dash",
    from: "<td>${statusBadge(r)}</td>", to: '<td><span class="badge b-ok">active</span></td>',
    kills: ["B7"] },
  { why: "🔴 面板 E-3：cooldown 且剩余 0 被归正为绿标", file: "dash",
    from: "  switch (r.status) {",
    to: '  if (r.status === "cooldown" && !(r.cooldown_remaining_ms > 0)) '
      + 'return `<span class="badge b-ok">active</span>`;\n  switch (r.status) {',
    kills: ["C8"] },
  { why: "🔴 面板 E-2：点击处理器首行 return;（字符串都还在，行为没了）", file: "main",
    from: "    dot.addEventListener(\"click\", async () => {",
    to: "    dot.addEventListener(\"click\", async () => {\n      return;",
    kills: ["I6", "I7"] },
  { why: "把未读数当恒 >0（0 失败也亮红点）", file: "main",
    from: "const n = Number(s.ops_failed_unread || 0);", to: "const n = 1;", kills: ["I2"] },
  { why: "红点计数 >0 也不去掉 hidden", file: "main", from: "dot.hidden = false;",
    to: "dot.hidden = true;", kills: ["I1", "F6"] },
  { why: "有失败时也把红点藏起来（文案恒空）", file: "main",
    // 🔴 2026-10-02 16:0x 更新：原锚 `        dotText.textContent = \`运营失败 ${n}\`;`（八空格独占一行）
    //    在「实例身份横幅」那次改动里被折进了 `if (n > 0) { … }` 的单行形态
    //    （`web/static/js/main.js:117`），于是命中数归 0、`--mutation` 里这一条报「锚点已过期」，
    //    连带 `test_int_v2_frontend_gate.py::test_frontend_assertions_can_actually_go_red` 判红。
    //    语义不变：把文案赋值整段摘掉，只剩"隐藏位不变"，I1 必须红。
    from: "        if (n > 0) { dotText.textContent = `运营失败 ${n}`; dot.hidden = false; }",
    to: "        if (n > 0) { dot.hidden = false; }", kills: ["I1"] },
  { why: "轮询打错端点", file: "main", from: 'await GET("/admin/api/status")',
    to: 'await GET("/admin/api/stat")', kills: ["I3"] },
  { why: "轮询间隔 30s", file: "main", from: "setInterval(poll, 5000)",
    to: "setInterval(poll, 30000)", kills: ["I4", "F3"] },
  { why: "页面隐藏时照常发请求", file: "main", from: 'visibilityState === "hidden"',
    to: 'visibilityState === "gone"', kills: ["I5", "F4"] },
  { why: "不判 dot 是否存在就绑事件（首屏未就绪即抛）", file: "main",
    from: "  if (dot) {", to: "  if (true) {", kills: ["I8"] },
  { why: "红点块换了取节点的方式（本 harness 抽取不到 = 判据失去对象）", file: "main",
    from: '  const dot = document.getElementById("ops-dot");',
    to: '  const dot = document.querySelector(".ops-dot");', kills: ["I0"] },
  { why: "promoteKeyDraft 不再是 async 函数（抽取失败=入口被移除）", file: "res",
    from: "async function promoteKeyDraft(root, resList, i) {",
    to: "function promoteKeyDraftRetired(root, resList, i) {", kills: ["D1"] },
  { why: "红点元素改名（轮询找不到节点）", file: "index", from: 'id="ops-dot"', to: 'id="opsdot"',
    kills: ["E1", "E2"] },
  { why: "红点文案节点改名（计数无处可写）", file: "index", from: 'id="ops-dot-text"',
    to: 'id="opsdot-text"', kills: ["E3"] },
  { why: "红点默认可见（0 失败也亮）", file: "index", from: 'id="ops-dot" hidden',
    to: 'id="ops-dot"', kills: ["E2"] },
  { why: "红点 title 回到「查看详情」（IX-M-5 原缺陷）", file: "index",
    from: "点击确认（逐条原因见 data/usage/ops-results-*.jsonl）", to: "用 mgw zcode claim 查看详情",
    kills: ["E4"] },
  { why: "轮询端点写错", file: "main", from: 'GET("/admin/api/status")',
    to: 'GET("/admin/api/stat")', kills: ["F1"] },
  { why: "不再读未读计数", file: "main", from: "ops_failed_unread", to: "ops_failed_total",
    kills: ["F2"] },
  { why: "GET 未导入（运行时 ReferenceError）", file: "main", from: "import { GET, POST }",
    to: "import { POST }", kills: ["F5"] },
  { why: "点击不再确认（红点永久常亮）", file: "main",
    from: 'await POST("/admin/api/ops/ack");', to: "", kills: ["F7", "I6"] },
  { why: "🔴 面板 S-18 ESCAPE-2：加载即确认（每 5s 自动吞掉失败）", file: "main",
    from: '  const dot = document.getElementById("ops-dot");',
    to: '  const dot = document.getElementById("ops-dot");\n  if (dot) POST("/admin/api/ops/ack");',
    kills: ["I9"] },
  { why: "toast 把重新领取说成查看详情", file: "main", from: "重跑用 mgw zcode claim",
    to: "claim 查看", kills: ["G1"] },
  { why: "指路不再指向落盘的明细文件", file: "main",
    from: "逐条原因见 data/usage/ops-results-*.jsonl", to: "逐条原因见界面", kills: ["G2"] },
  { why: "未装 mgw 时只给 mgw 命令", file: "main",
    from: "未安装则 python -m model_gateway.cli zcode claim", to: "重跑", kills: ["G3"] },
  { why: "红点样式类改名", file: "css", from: ".ops-dot {", to: ".opsdot {", kills: ["H1", "H2"] },
  { why: "红点颜色写死（丢双主题）", file: "css",
    from: "background: var(--err-bg);\n  color: var(--text);",
    to: "background: #c00;\n  color: #fff;", kills: ["H2"] },
  { why: "🔴 面板 S-19：侧栏页名改了、路由标题没改（面包屑与侧栏打架 + 指路指空页）",
    file: "index", from: "<span>网关模型管理</span></a>", to: "<span>模型映射</span></a>",
    kills: ["J1", "J2"] },
  { why: "🔴 面板 S-19：PAGE_META 改了、侧栏没改", file: "main",
    from: 'models: { title: "网关模型管理", group: "资源配置" },',
    to: 'models: { title: "模型映射", group: "资源配置" },', kills: ["J1"] },
  { why: "🔴 面板 S-19：Python 侧页名常量指向不存在的页面（前端有门也拦不住 CLI/告警）",
    file: "coreRes", from: 'ROUTE_POOL_PAGE = "「网关模型管理」页"',
    to: 'ROUTE_POOL_PAGE = "「模型映射」页"', kills: ["J2"] },
  /* —— 第七轮 ix 的六条语义逃逸，逐条补上"能红"的证据 —— */
  { why: "🔴 第七轮 ix 逃逸①：冷却剩余改成**向下**取整（未满一秒报 0s、30 分钟报成 29 分钟）",
    file: "dash", from: 'return n > 0 ? `${n}s` : "—";',
    to: 'const f = Math.floor((ms || 0) / 1000); return f > 0 ? `${f}s` : "—";',
    kills: ["C15"] },
  { why: "🔴 第七轮 ix 逃逸②：invalid 文案补一句「也可先换 Key 重试」（404 的错处置）",
    file: "dash", from: "到「接入模型资源」页更换映射（不会自愈）\"",
    to: "到「接入模型资源」页更换映射（不会自愈）；也可先换 Key 重试\"",
    kills: ["C3"] },
  { why: "🔴 第七轮 ix 逃逸③：徽章按 `C`（连续失败数）分叉出第二套文案", file: "dash",
    from: 'case "disabled": return `<span class="badge b-muted" title="两种成因之一：资源开关已关闭（打开即恢复），或凭据被上游拒绝 401（需到「接入模型资源」页更换 Key，不会自愈）—— 见「最近错误」列">已停用</span>`;',
    to: 'case "disabled": return `<span class="badge b-muted" title="${r.C > 0 ? "资源已停用" : "两种成因之一：资源开关已关闭（打开即恢复），或凭据被上游拒绝 401（需到「接入模型资源」页更换 Key，不会自愈）—— 见「最近错误」列"}">已停用</span>`;',
    kills: ["C4", "C16"] },
  { why: "🔴 第七轮 ix 逃逸④a：resources.js（原先不在 J2 扫描范围里）指去不存在的页",
    file: "res", from: "点击左侧「＋ 添加模型资源」接入第一个资源供应商",
    to: "点击左侧「＋ 添加模型资源」接入，或到「接入管理」页配置", kills: ["J2"] },
  { why: "🔴 第七轮 ix 逃逸④b：main.js（同样不在范围里）指去不存在的页", file: "main",
    from: "document.title = `${meta.title} · Model-Gateway`;",
    to: 'document.title = `${meta.title} · Model-Gateway`;\n  localStorage.setItem("mgw-hint", "详情到「运行监控」页查看");',
    kills: ["J2"] },
  { why: "🔴 第七轮 ix 逃逸⑤：用『』括号写页名（旧正则只认「」，改写括号就漏检）",
    file: "cliSetup", from: "到「API 接入」页新建", to: "到『模型映射』页新建",
    kills: ["J2"] },
  /* —— 第八轮 ix-8 的 13 条逃逸，逐条补"能打红"的变异 —— */
  { why: "🔴 第八轮 B-1：把告警调用包进 HTML 注释（横幅整块从界面消失，A 段 15 条仍全绿）",
    file: "dash", from: "${configWarnings(data.warnings)}",
    to: "<!--${configWarnings(data.warnings)}-->", kills: ["K1"] },
  { why: "🔴 第八轮 B-11：告警加 aria-hidden（视觉上在、读屏软件里等于没有）", file: "dash",
    from: 'class="alert alert-warn"', to: 'class="alert alert-warn" aria-hidden="true"',
    kills: ["K1"] },
  { why: "🔴 第八轮 B-9：指标卡少渲染一张（此前指标卡零覆盖）", file: "dash",
    from: 'metricCard("厂商数量", c.vendors ?? "—", "mi-blue", ICON.factory)', to: "",
    kills: ["K3"] },
  { why: "🔴 第八轮 B-12：页面链接指去不存在的路由", file: "dash",
    from: '<a href="#/logs" style="color:var(--cool);font-weight:700">查看日志</a>',
    to: '<a href="#/operations" style="color:var(--cool);font-weight:700">查看日志</a>',
    kills: ["K4"] },
  { why: "🔴 第八轮 B-3：坏页名写在告警装配地 `main.py`（原先不在扫描面里）", file: "mainPy",
    // 2026-10-02 重锚：装配地的文案被别的轮次改写过
    // （「N 个系统模型未配置任何资源，」→「N 个系统模型没有任何生效的资源映射，」，`main.py:694`），
    // 旧字面命中 0 次 ⇒ 这条变异空转。判据原意不变：在**告警装配地**插一个坏页名，J2 必须响。
    from: "个系统模型没有任何生效的资源映射，",
    to: "个系统模型没有任何生效的资源映射（去「模型映射」页处理），",
    kills: ["J2"] },
  { why: "🔴 第八轮 B-4：可见文案落在**模板字符串里以 `//` 开头的一行**（旧剥离器当注释删）",
    file: "models",
    // 2026-10-02 重锚：那句指路文案加了"供应商侧 / 账号侧"分流（`models.js:407`），
    // 旧字面（只到「添加映射」）命中 0 次。判据原意不变：把坏页名放进模板串里以 `//`
    // 开头的那一行，剥注释若按"行首 `//` 即注释"判，用户看得见的指路就从扫描面消失。
    from: "无资源（调用将无可用资源 503）——供应商侧到「接入模型资源」页添加映射，账号侧到「接入账号资源」页做「模型映射」",
    to: "无资源（调用将无可用资源 503）——\n      // 到「运维面板」页编辑资源添加映射",
    kills: ["J2"] },
  { why: "🔴 第八轮 B-7：不带括号的页名（旧正则只认「」/『』）", file: "cliSetup",
    from: "到「API 接入」页新建", to: "请到 模型映射 页新建", kills: ["J2"] },
  { why: "🔴 第八轮 B-5：徽章按**具体账号值**分叉（两点纯度测试看不见）", file: "dash",
    from: "  const left = Math.ceil((r.cooldown_remaining_ms || 0) / 1000);",
    to: '  if (r.account === "acct-a") return `<span class="badge b-ok" title="可承接请求">可用</span>`;\n  const left = Math.ceil((r.cooldown_remaining_ms || 0) / 1000);',
    kills: ["C2", "C3", "C4", "C5", "C6", "C16"] },
  { why: "🔴 第八轮 B-5：格式化按 **ms 量级**分叉（120s~30min 用 floor 分钟，与列的秒数打架）",
    file: "dash", from: 'const n = Math.ceil((ms || 0) / 1000);',
    to: 'const n = (ms >= 120000 && ms < 1800000) ? Math.floor(ms / 60000) : Math.ceil((ms || 0) / 1000);',
    kills: ["C15"] },
  { why: "🔴 第八轮 B-6：同义词绕过（「更换**密钥**」躲开 `/换 Key/`）", file: "dash",
    from: "到「接入模型资源」页更换映射（不会自愈）\"",
    to: "到「接入模型资源」页更换映射（不会自愈）；也可先更换密钥重试\"",
    kills: ["C3"] },
  { why: "🔴 页面渲染整体抛错（K 段判据失去对象也要能红）", file: "dash",
    from: "  const t = data.today;", to: "  const t = data.nope;",
    kills: ["K0", "K1", "K2", "K3", "K4", "K5"] },
  { why: "🔴 页面里不再挂资源健康表（函数还在、调用点没了）", file: "dash",
    from: "${resourceHealthTable(data.resources)}", to: "", kills: ["K2"] },
  { why: "🔴 指标卡把缺失字段 String() 出来（界面上印出 undefined）", file: "dash",
    from: 'metricCard("厂商数量", c.vendors ?? "—", "mi-blue", ICON.factory)',
    to: 'metricCard("厂商数量", String(c.vendor_total), "mi-blue", ICON.factory)',
    kills: ["K5"] },
  { why: "🔴 第八轮 B-8：「最近错误」列不再显示后端传来的原因（改印状态码）", file: "dash",
    from: '${esc(r.last_error || "—")}</td>', to: '${r.status}</td>',
    kills: ["B3", "B5", "K6"] },
  /* —— 第九轮 ix-9 的 7 条阻塞：逐条配一个能打红的变异 —— */
  { why: "🔴 第九轮 B-1：页面改去请求一个后端没有的端点（生产必整屏空白）", file: "dash",
    from: "const data = await GET(\"/admin/api/overview\");",
    to: "const data = await GET(\"/admin/api/panel\");", kills: ["K7"] },
  { why: "🔴 第九轮 B-2a：横幅加 `hidden`（DOM 里在、用户看不见）", file: "dash",
    from: '<div class="alert alert-warn">', to: '<div class="alert alert-warn" hidden>',
    kills: ["K1"] },
  { why: "🔴 第九轮 B-2b：告警正文 `display:none`（A 段函数级判据完全无感）", file: "dash",
    from: '      <div>${esc(w.message || "")}</div>',
    to: '      <div style="display:none">${esc(w.message || "")}</div>', kills: ["K1"] },
  { why: "🔴 第九轮 B-2c：正文只进 `title=`（不悬停就看不见，等于把原因藏起来）", file: "dash",
    from: '      <div>${esc(w.message || "")}</div>',
    to: '      <div title="${esc(w.message || \"\")}">（详见悬浮提示）</div>', kills: ["K1"] },
  { why: "🔴 第九轮 B-3：坏页名写在 `logs.js`（手写清单里的产地之外）",
    file: "copy:coding/model_gateway/web/static/js/pages/logs.js",
    from: "该筛选条件下无请求记录", to: "该筛选条件下无请求记录，可打开「运行监控」页核对",
    kills: ["J2"] },
  { why: "🔴 第九轮 B-4：去掉\"页\"字的死页名（cue 动词 + 括号）", file: "models",
    from: "请到「接入模型资源」页为该模型配置资源映射", to: "请到「模型映射」为该模型配置资源映射",
    kills: ["J2"] },
  { why: "🔴 第九轮 B-5：`api.js` 的 esc 被弱化（页面产出未转义 = 存储型 XSS 面）",
    file: "api", from: `  return String(s ?? "").replace(/[&<>"']/g, (c) =>`,
    to: `  return String(s ?? "") || (c) =>`, kills: ["K9"] },
  { why: "🔴 第九轮 B-6a：趋势图不再绘制（容器空，页面看着\"正常\")", file: "dash",
    from: "  drawHourChart(data.today_by_hour);", to: "", kills: ["K8"] },
  { why: "🔴 第九轮 B-6b：onclick 里跳到一个不存在的路由（K4 原先只认 href）", file: "dash",
    from: '<a href="#/logs" style="color:var(--cool);font-weight:700">查看日志</a>',
    to: `<a href="#/logs" onclick="location.hash='#/audit-log'" style="color:var(--cool);font-weight:700">查看日志</a>`,
    kills: ["K4"] },
  { why: "🔴 第九轮 B-7a：恢复时刻被搬到「冷却剩余」列（列位契约没了）", file: "dash",
    from: '${r.status === "cooldown" ? fmtCooldown(r.cooldown_remaining_ms) : "—"}',
    to: '${r.status === "cooldown" ? fmtCooldown(r.cooldown_remaining_ms) + "，至 12:34" : "—"}',
    kills: ["K6"] },
  { why: "🔴 第九轮 B-7b：active 徽章按 `available` 分叉文案（同状态两种说法）", file: "dash",
    from: 'case "active": return `<span class="badge b-ok" title="可承接请求">可用</span>`;',
    to: 'case "active": return `<span class="badge b-ok" title="可承接请求">${r.available ? "可用" : "在线"}</span>`;',
    kills: ["C16"] },
  /* —— 第十轮 ix-10 的 9 条门洞：逐条配一个能打红的变异 —— */
  { why: "🔴 第十轮 B10-1a：告警 `opacity:0`（DOM 在、用户看不见）", file: "dash",
    from: '<div class="alert alert-warn">', to: '<div class="alert alert-warn" style="opacity:0">',
    kills: ["K1"] },
  { why: "🔴 第十轮 B10-1b：属性名/样式**大写**绕过（STYLE=\"DISPLAY: NONE\"）", file: "dash",
    from: '<div class="alert alert-warn">',
    to: '<div class="alert alert-warn" STYLE="DISPLAY: NONE">', kills: ["K1"] },
  { why: "🔴 第十轮 B10-1c：`height:0;overflow:hidden` 折叠掉横幅内容", file: "dash",
    from: '      <div>${esc(w.message || "")}</div>',
    to: '      <div style="height:0;overflow:hidden">${esc(w.message || "")}</div>',
    kills: ["K1"] },
  { why: "🔴 第十轮 B10-2：正文包进 `<template>`（DOM 里有、页面上没有）", file: "dash",
    from: '      <div>${esc(w.message || "")}</div>',
    to: '      <template>${esc(w.message || "")}</template>', kills: ["K1"] },
  { why: "🔴 第十轮 B10-3：裸 `aria-hidden`（无 =\"true\"，读屏软件里整块消失）", file: "dash",
    from: '<div class="alert alert-warn">', to: '<div class="alert alert-warn" aria-hidden>',
    kills: ["K1"] },
  { why: "🔴 第十轮 B10-4：把「最近错误」表头藏掉（列失去标题，钟点无处归位）", file: "dash",
    from: '<th title="熔断 / 失败原因（风控熔断与普通冷却的区分）">最近错误</th>',
    to: '<th hidden title="熔断 / 失败原因（风控熔断与普通冷却的区分）">最近错误</th>',
    kills: ["K6"] },
  { why: "🔴 第十轮 B10-5：趋势图容器压成 height:0（图形区一条空白）", file: "dash",
    from: '<div id="hour-chart" style="height:160px"></div>',
    to: '<div id="hour-chart" style="height:0px"></div>', kills: ["K8"] },
  { why: "🔴 第十二轮 ix B12-6 / eng-B B11-8：把趋势容器改名（页面上那块根本不存在了）"
      + " —— 旧缺省 `|| [\"\"]` 会把『查无此物』判成『容器可见』", file: "dash",
    from: '<div id="hour-chart" style="height:160px"></div>',
    to: '<div id="hourchart-x" style="height:160px"></div>', kills: ["K8"] },
  { why: "🔴 第十二轮 ix B12-6 同族：徽章去掉 `title=`（处置说明全部消失）"
      + " —— 空串缺省会让 titleOf 的反向判据白过", file: "dash",
    from: 'title="上游回 404：该模型名无效 —— 到「接入模型资源」页更换映射（不会自愈）"',
    to: "", kills: ["C3"] },
  { why: "🔴 第十一轮 eng-B B11-4：「连续失败」与「处理中」两列**取值对调**"
      + "（表头文字与 `<td>` 数量都不变，B6/B7/K 段全部看不见）", file: "dash",
    from: '      <td class="num">${r.C || 0}</td>\n      <td class="num">${r.in_flight || 0}</td>',
    to: '      <td class="num">${r.in_flight || 0}</td>\n      <td class="num">${r.C || 0}</td>',
    kills: ["K10"] },
  { why: "🔴 第十轮 B10-6：徽章按 `last_error` **长度**分叉（70 字的真实 429 原文走另一套说法）",
    file: "dash",
    from: 'case "disabled": return `<span class="badge b-muted" title="两种成因之一：资源开关已关闭（打开即恢复），或凭据被上游拒绝 401（需到「接入模型资源」页更换 Key，不会自愈）—— 见「最近错误」列">已停用</span>`;',
    to: 'case "disabled": return `<span class="badge b-muted" title="${(r.last_error || "").length > 40 ? "资源已停用" : "两种成因之一：资源开关已关闭（打开即恢复），或凭据被上游拒绝 401（需到「接入模型资源」页更换 Key，不会自愈）—— 见「最近错误」列"}">已停用</span>`;',
    kills: ["C16"] },
  { why: "🔴 第十轮 B10-7：坏页名写在 **CSS 的 content** 里（原先 CSS 不在产地面）",
    file: "css", from: ".ops-dot {",
    to: '.copy-hint::after { content: "请前往「模型映射」页处理"; }\n.ops-dot {', kills: ["J2"] },
  { why: "🔴 第十一轮 B-11-3 / B11-1：CSS 里一条 `.alert-warn{display:none}` 让四条告警"
      + "在真浏览器里高度全为 0（只看内联 style 的门 81 项全绿）", file: "css",
    from: ".hidden { display: none !important; }",
    to: ".alert-warn { display: none; }\n.hidden { display: none !important; }",
    kills: ["K1"] },
  { why: "🔴 第十一轮 B-11-3：删掉 `.hidden` 工具类这条规则 —— 可见性必须由样式表派生，"
      + "规则没了就说明判据其实是在背清单", file: "css",
    from: ".hidden { display: none !important; }",
    to: "/* .hidden 工具类被删（第十轮 Z1 曾把 class=\"hidden\" 判成\"字面巧合不算\"） */",
    kills: ["Z1"] },
  { why: "🔴 第十二轮 ix B12-3 的**门自身**回归：把 at-rule 一律当『整块跳过』（就是上一版的错），"
      + "@media 里的隐藏规则就又查不出来了", self: true, file: "gate",
    from: '          stack.push(/^@(?:keyframes|font-face|property)/.test(head) ? "ignore" : "at");\n'
        + '          sel = "";',
    to: '          stack.push("ignore");\n          sel = "";',
    kills: ["Z4"] },
  { why: "🔴 把 `hidden` 属性判据摘掉（门自测必须红：可见性判据不能悄悄坏掉）",
    self: true, file: "gate",
    // 锚点取**两行**：单行文本会同时命中本文件 MUTATIONS 里的那份字面量（要求恰好 1 次）
    from: '      const v = String(value).toLowerCase().replace(/\\s+/g, " ");\n'
        + '      if (name === "hidden") return true;',
    to: '      const v = String(value).toLowerCase().replace(/\\s+/g, " ");\n'
      + '      if (name === "hidden-not-judged") return true;',
    kills: ["Z1"] },
  { why: "🔴 第十二轮 eng-B S-52：摘掉 realm 桥的闸门（宿主实参原样进 realm）—— "
      + "页面里 esc.constructor(\"return process\")() 就又能拿到宿主 Function，"
      + "而 Z2 只看上下文全局名，照样全绿（锚点取**两行**：单行会和 MUTATIONS 里"
      + "这份字面量撞成 2 次命中）", self: true, file: "gate",
    from: '    return ctx.__f(...callArgs.map((a) => ctx.__guard(a)));\n  };',
    to: '    return ctx.__f(...callArgs);\n  };', kills: ["Z5"] },
  { why: "🔴 第十二轮 eng-B S-52 的另一半：入口包了、**返回值不包** —— 宿主调用吐回来的"
      + "宿主对象/函数照样带 realm（await GET(p) 之后 .nested.constructor 就是宿主 Function）",
    self: true, file: "gate",
    from: '      const f = function (...a) { return wrap(v.apply(this, a)); };\n      cache.set(v, f);',
    to: '      const f = function (...a) { return v.apply(this, a); };\n      cache.set(v, f);',
    kills: ["Z5"] },
  { why: "🔴 第十二轮 eng-B S-52 的第三层：不伪造原型链 —— 走 Object.getPrototypeOf(宿主对象)"
      + " 拿到**宿主的** Object.prototype，上面每个原生方法的 .constructor 都是宿主 Function",
    self: true, file: "gate",
    from: '      ownKeys(t) { return Reflect.ownKeys(t).filter((k) => !BRIDGE.has(k)); },\n'
        + '      getPrototypeOf() { return Object.prototype; },',
    to: '      ownKeys(t) { return Reflect.ownKeys(t).filter((k) => !BRIDGE.has(k)); },',
    kills: ["Z5"] },
  { why: "🔴 第十轮 R-3：沙箱泄漏 Node 全局（把 `process` 塞进 vm 上下文，"
      + "页面写 `process.x` 时门看不见，浏览器却崩页）",
    self: true, file: "gate",
    from: '  const ctx = vm.createContext({});\n'
        + '  new vm.Script(',
    to: '  const ctx = vm.createContext({ process: globalThis.process });\n'
      + '  new vm.Script(', kills: ["Z2"] },
  { why: "🔴 第十轮 B10-8：坏页名写在可 HTTP 直达的静态模板里（templates/*.html）",
    file: "copy:coding/model_gateway/web/static/templates/template-skills.html",
    from: "当前没有已安装技能", to: "当前没有已安装技能，可去「插件市场」页安装", kills: ["J2"] },
  { why: "🔴 第十轮 B10-9：cue 动词闭集外的写法（`或去「模型映射」核对`，不带\"页\"字）",
    file: "apiaccess", from: "暂无接入密钥——点击「添加密钥」生成",
    to: "暂无接入密钥——或去「模型映射」核对后点击「添加密钥」生成", kills: ["J2"] },
  { why: "🔴 第十二轮 ix B12-3：把隐藏规则藏进 @media（上一版 at-rule 整块跳过，派生查不出）",
    file: "css",
    from: "@media (max-width: 1280px) {\n  .app { grid-template-columns: 62px 1fr; }",
    to: "@media (max-width: 1280px) {\n  .alert-warn { display: none; }\n"
      + "  .app { grid-template-columns: 62px 1fr; }",
    kills: ["K1"] },
  { why: "🔴 第十一轮 B11-9：K4 把外链当解析噪声丢掉 —— 管理台里出现远程文档链接"
      + "（违反铁律 1「纯本地、无远程下发」）门却全绿", file: "dash",
    from: '<div class="alert alert-warn">',
    to: '<div class="alert alert-warn"><a href="https://docs.model-gateway.example.com/faq">说明</a>',
    kills: ["K4"] },
  /* —— 第十三轮 S-46 第一半：共享行为层（api.js / components.js）真跑的 21 条判据，
        逐条配一个能打红的源码变异（面板 ix B12-1 实测的三类坏改动就在其中①②③） —— */
  { why: "🔴 面板 ix B12-1 ①：4xx 不再抛错（后端真回 400，界面弹绿色「配置已保存并热重载生效」）",
    file: "api", from: '  if (!resp.ok) {', to: '  if (false) {', kills: ["L2", "L3", "L5", "L6"] },
  { why: "🔴 同族的半吊子写法：只在「有 JSON 正文」时才判失败（HTML 错误页 502 被当成功）",
    file: "api", from: '  if (!resp.ok) {', to: '  if (resp.ok === false && data) {',
    kills: ["L3", "L6"] },
  { why: "后端多条校验原因不再拼接（只剩 HTTP 状态码，用户不知道改哪一行）",
    file: "api", from: 'data.errors ? data.errors.join("；") :', to: 'data.errors ? "" :',
    kills: ["L2", "L5"] },
  { why: "成功路径把后端数据丢掉（界面拿到 null）", file: "api", from: "  return data;",
    to: "  return null;", kills: ["L1"] },
  { why: "🔴 网络异常被吞成 null（断网/服务没起时界面按「空配置」渲染，不报任何错）",
    file: "api", from: "  const resp = await fetch(path, { ...opts, headers });",
    to: '  let resp; try { resp = await fetch(path, { ...opts, headers }); } catch { return null; }',
    kills: ["L4"] },
  { why: "非 JSON 的 4xx 不再报状态码（只剩一句「请求失败」，无从判断是 401 还是 502）",
    file: "api", from: ' || `HTTP ${resp.status}`;', to: ' || "请求失败";', kills: ["L6"] },
  { why: "非 JSON 的 2xx 凭空造出一个空对象（调用方以为拿到了配置）", file: "api",
    from: '  try { data = await resp.json(); } catch { /* 非 JSON */ }',
    to: '  try { data = await resp.json(); } catch { data = {}; }', kills: ["L7"] },
  { why: "POST 的 method 写错（后端路由按 method 分派，界面弹成功、数据没落库）", file: "api",
    from: 'export const POST = (p, body) => api(p, { method: "POST", body: JSON.stringify(body) });',
    to: 'export const POST = (p, body) => api(p, { method: "PATCH", body: JSON.stringify(body) });',
    kills: ["L8"] },
  { why: "PUT 不再序列化请求体（fetch 收到对象 → 后端 422，界面照旧弹成功）", file: "api",
    from: 'export const PUT = (p, body) => api(p, { method: "PUT", body: JSON.stringify(body) });',
    to: 'export const PUT = (p, body) => api(p, { method: "PUT", body });', kills: ["L8"] },
  { why: "🔴 toast 的类型丢掉（失败也染成绿色 ok 样式，红绿色失去含义）", file: COMP_SRC,
    from: '  el.className = "toast " + type;', to: '  el.className = "toast ok";',
    kills: ["L5", "L12"] },
  { why: "🔴 面板 ix B12-1 ②：确认弹窗的取消分支改成答复 true（点「取消」真的删了密钥）",
    file: COMP_SRC, from: '    cancel.onclick = () => { settle(false); m.close(); };',
    to: '    cancel.onclick = () => { settle(true); m.close(); };', kills: ["L9"] },
  { why: "取消时忘了关弹窗（用户对着一个关不掉的确认框，或删除已执行）", file: COMP_SRC,
    from: '    cancel.onclick = () => { settle(false); m.close(); };',
    to: '    cancel.onclick = () => { settle(false); };', kills: ["L9"] },
  { why: "确定分支被改成 false（所有确认类操作静默失效：删除/重启/停止全按不下去）",
    file: COMP_SRC, from: '    ok.onclick = () => { settle(true); m.close(); };',
    to: '    ok.onclick = () => { settle(false); m.close(); };', kills: ["L10"] },
  /* —— S-61：✕ / 遮罩这两条不经过按钮的关闭通道 —— */
  { why: "🔴 S-61 原样复发：不给 `modal()` 传 onClose（点 ✕ / 遮罩时 promise 永不 settle，"
      + "调用方永久挂住）—— 这正是本条判据要钉住的那个缺陷本体", file: COMP_SRC,
    from: '    const m = modal({ title, body, footer: foot, onClose: () => settle(false) });',
    to: '    const m = modal({ title, body, footer: foot });', kills: ["L21"] },
  { why: "🔴 关闭通道有答复但方向错：用户点 ✕ / 遮罩（**没做选择**）被当成「确定」→ 直接执行破坏性动作",
    file: COMP_SRC, from: '    const m = modal({ title, body, footer: foot, onClose: () => settle(false) });',
    to: '    const m = modal({ title, body, footer: foot, onClose: () => settle(true) });',
    kills: ["L21"] },
  { why: "🔴 按钮分支把顺序写反（先 `m.close()` 再答复）：`close()` 同步触发 onClose → "
      + "「确定」被 onClose 的 false 抢先定掉，所有确认类操作静默失效 —— 钉住 S-61 修法的顺序",
    file: COMP_SRC, from: '    ok.onclick = () => { settle(true); m.close(); };',
    to: '    ok.onclick = () => { m.close(); settle(true); };', kills: ["L10"] },
  { why: "🔴 面板 ix B12-1 ③：copyText 不写剪贴板直接报「已复制」", file: COMP_SRC,
    from: '  navigator.clipboard?.writeText(text).then(\n    () => toast(okMsg, "ok"), () => toast("复制失败", "err"));',
    to: '  toast(okMsg, "ok");', kills: ["L11", "L12", "L13"] },
  { why: "🔴 2026-09-29 主控复采新发现的**门自身**缺陷：写入照发、rejection 分支删掉 —— "
      + "被拒绝的 promise 成了 unhandled rejection，旧门整轮崩掉（RC=1、零输出），"
      + "有兜网之后 Z3 记红、其余判据照常跑完（崩溃不是证据）", file: COMP_SRC,
    from: '  navigator.clipboard?.writeText(text).then(\n    () => toast(okMsg, "ok"), () => toast("复制失败", "err"));',
    to: '  navigator.clipboard?.writeText(text);\n  toast(okMsg, "ok");', kills: ["L13", "Z3"] },
  { why: "clipboard 缺失时伪造一个必然成功的写入（非安全上下文里谎报已复制）", file: COMP_SRC,
    from: '  navigator.clipboard?.writeText(text).then(',
    to: '  (navigator.clipboard || { writeText: () => Promise.resolve() }).writeText(text).then(',
    kills: ["L13"] },
  { why: "modal 标题不做转义（title 里的 <script> 成为真元素 = 管理台注入面）", file: COMP_SRC,
    from: '<h3>${esc(title)}</h3>', to: '<h3>${title}</h3>', kills: ["L14"] },
  { why: "🔴 弹窗脚钮间距回归（整块 append footer，gap 落在中间层 → 取消/确定贴死，2026-09-06 已修过一次）",
    file: COMP_SRC, from: '    while (footer.firstChild) footEl.append(footer.firstChild);',
    to: '    footEl.append(footer);', kills: ["L15"] },
  { why: "点弹窗内部也关闭（填了一半的表单被误点丢掉）", file: COMP_SRC,
    from: '  mask.addEventListener("mousedown", (e) => { if (e.target === mask) close(); });',
    to: '  mask.addEventListener("mousedown", (e) => { close(); });', kills: ["L16"] },
  { why: "X 按钮不再绑关闭事件（弹窗只能点遮罩关）", file: COMP_SRC,
    from: '  mask.querySelector(".modal-close").onclick = close;',
    to: '  /* 关闭按钮不再绑事件 */', kills: ["L16"] },
  { why: "🔴 开关不再按保存结果回滚（onToggle 返回 false 也翻成开启 = 界面与配置打架）",
    file: COMP_SRC, from: '    if (ok !== false) el.classList.toggle("on", next);',
    to: '    if (true) el.classList.toggle("on", next);', kills: ["L17"] },
  { why: "开关点了不翻转（视觉与真相反着来，D3 操作即保存失效）", file: COMP_SRC,
    from: '    if (ok !== false) el.classList.toggle("on", next);',
    to: '    /* 视觉翻转被删 */', kills: ["L17"] },
  { why: "开关的下一个状态不看当前 class（关不掉了，每次点都传 true）", file: COMP_SRC,
    from: '    const next = !el.classList.contains("on");', to: '    const next = true;',
    kills: ["L17"] },
  { why: "tab 切换回调交出的是**初始** active（第二组 tab 永远切不动）", file: COMP_SRC,
    from: '      onSwitch(t.id);', to: '      onSwitch(active);', kills: ["L18"] },
  { why: "tab 旧选中态不清掉（两个 tab 同时高亮，用户不知道当前是哪一组）", file: COMP_SRC,
    from: '      el.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));',
    to: '      /* 旧选中态不清掉 */', kills: ["L18"] },
  { why: "分页按钮不再置 disabled（首页还能点「‹」、末页还能点「›」，offset 跑到负数）",
    file: COMP_SRC, from: '    b.className = "btn btn-sm"; b.textContent = label; b.disabled = disabled;',
    to: '    b.className = "btn btn-sm"; b.textContent = label;', kills: ["L19"] },
  { why: "共享层少一个导出（switchEl 改名：L 段判据失去对象，必须先红给看）", file: COMP_SRC,
    from: 'export function switchEl(on, onToggle) {',
    to: 'export function switchElRenamed(on, onToggle) {', kills: ["L0"] },
  { why: "🔴 面板 ix B12-1 ④：maskVal 改成恒等（API 接入页密钥明文直接上屏）", file: "apiaccess",
    from: 'const maskVal = (v) => v ? v.slice(0, 5) + "****" + v.slice(-4) : "";',
    to: 'const maskVal = (v) => v || "";', kills: ["L20"] },
  { why: "🔴 面板 ix B12-1 ④ 的另一处副本：资源页 maskVal 去掉 **** 段（前5+后4 之外全露）",
    file: "res",
    from: 'function maskVal(v) { return v ? v.slice(0, 5) + "****" + v.slice(-4) : ""; }',
    to: 'function maskVal(v) { return v ? v.slice(0, 5) + v.slice(-4) : ""; }', kills: ["L20"] },
  { why: "🔴 门自己：toModuleBody 不再剥 import —— 共享层根本编不进 realm（L 段用的是复制品而非真源码）",
    self: true, file: "gate",
    from: '  const toModuleBody = (src) => src\n'
        + '    .replace(/^\\s*import\\s+[\\s\\S]*?from\\s+"[^"]*";\\s*$/gm, "")',
    to: '  const toModuleBody = (src) => src\n    .replace(/^\\s*$/gm, "")', kills: ["L0"] },

  /* -------- M 段：两个正式页面真跑（S-46 第二批） -------- */
  { why: "M0：API 接入页把 overview 端点写错（后端没这条路由 → 整屏空白，门却看不出）", file: "apiaccess",
    from: 'GET("/admin/api/config"), GET("/admin/api/overview")]);',
    to: 'GET("/admin/api/config"), GET("/admin/api/panel")]);', kills: ["M0"] },
  { why: "M1：密钥表只渲染第一行（多密钥场景其余密钥静默消失）", file: "apiaccess",
    from: '${tokens.map((t, i) => tokenRow(t, i)).join("")}',
    to: '${tokens.slice(0, 1).map((t, i) => tokenRow(t, i)).join("")}', kills: ["M1"] },
  { why: "M1：卡头把「N/M 启用」谎报成「M/M 启用」（停用密钥看起来在用）", file: "apiaccess",
    from: '${tokens.filter((t) => t.enabled !== false).length}/${tokens.length} 启用',
    to: '${tokens.length}/${tokens.length} 启用', kills: ["M1"] },
  { why: "M1：开关初值取反（停用密钥看起来是开着的）", file: "apiaccess",
    from: 'append(switchEl(t.enabled !== false, async (next) => {',
    to: 'append(switchEl(t.enabled === false, async (next) => {', kills: ["M1"] },
  { why: "🔴 M2：值格直接印明文（maskVal 调用被摘掉 —— 面板 ix B12-1 ④ 的页面版）", file: "apiaccess",
    from: '${esc(maskVal(t.value))}', to: '${esc(t.value)}', kills: ["M2", "M3"] },
  { why: "M3：眼睛点开拿不到明文（用户看不到完整密钥，复制流程随之断裂）", file: "apiaccess",
    from: 'span.textContent = t.value;', to: 'span.textContent = maskVal(t.value);', kills: ["M3"] },
  { why: "M3：眼睛收不回（data-on 不写回，明文一直挂在屏幕上）", file: "apiaccess",
    from: 'btn.dataset.on = "";', to: 'btn.dataset.on = "1";', kills: ["M3"] },
  { why: "🔴 M4：复制按钮复制的是密文（粘到工具端立刻 401，用户以为密钥坏了）", file: "apiaccess",
    from: 'copyText(t.value, "密钥已复制")', to: 'copyText(maskVal(t.value), "密钥已复制")', kills: ["M4"] },
  { why: "M5：启停改了本地对象却没写回（PUT body 仍是旧 enabled —— 界面翻了、后端没变）", file: "apiaccess",
    from: '      t.enabled = next;\n', to: "", kills: ["M5"] },
  { why: "M5：persist 不再 PUT 全量配置（只发 gateway 一节，后端按全量校验会清掉其余字段）", file: "apiaccess",
    from: 'await PUT("/admin/api/config", cfg);',
    to: 'await PUT("/admin/api/config", { gateway: cfg.gateway });', kills: ["M5", "M7"] },
  { why: "🔴 M6：启停遇到 400 也弹绿色「密钥已启用」（后端拒绝了，界面说成功）", file: "apiaccess",
    from: '    toast("保存失败：" + e.message, "err");', to: '    toast(okMsg, "ok");', kills: ["M6"] },
  { why: "M6：失败 toast 丢掉后端原因（只剩一句「保存失败」，用户不知道改哪一行）", file: "apiaccess",
    from: '    toast("保存失败：" + e.message, "err");', to: '    toast("保存失败", "err");', kills: ["M6"] },
  { why: "M7：用途标注没写进配置（PUT 发了、名字没变 —— 行内编辑静默失效）", file: "apiaccess",
    from: '      t.name = v;\n', to: "", kills: ["M7"] },
  { why: "M7：改成同名也发全量 PUT（每次失焦都写盘一次）", file: "apiaccess",
    from: 'if (v === (t.name || "")) return;', to: 'if (false) return;', kills: ["M7"] },
  { why: "🔴 M8：点「取消」也把密钥写进配置（取消钮接到新增逻辑上）", file: "apiaccess",
    from: '  cancelBtn.onclick = () => m.close();',
    to: '  cancelBtn.onclick = async () => {\n'
      + '    cfg.gateway.access_tokens.push({ id: "", name: "误加", value: "", enabled: true });\n'
      + '    m.close(); await persist(root, "已生成密钥并生效"); };', kills: ["M8"] },
  { why: "M8：客户端自己编 id/value（抢走服务端 _autogen_ids 的契约，列表里的 id 与密钥从此不一致）",
    file: "apiaccess",
    from: 'cfg.gateway.access_tokens.push({ id: "", name, value: "", enabled: true });',
    to: 'cfg.gateway.access_tokens.push({ id: "tok-mine", name, value: "mg-mine-mine", enabled: true });',
    kills: ["M8"] },
  { why: "🔴 M9：删除不看确认结果（点「取消」也真的把密钥删了）", file: "apiaccess",
    from: '      if (!await confirmDialog("删除密钥",',
    to: '      if (false && await confirmDialog("删除密钥",', kills: ["M9"] },
  { why: "M9：确认删了、PUT 里却没少那条（弹窗关了就当成功）", file: "apiaccess",
    from: '      cfg.gateway.access_tokens.splice(i, 1);', to: '      /* 变异：忘了真的删 */', kills: ["M9"] },
  { why: "M10：系统设置把配置端点写错（GET 404 → 整页空白）", file: "settings",
    from: 'cfg = await GET("/admin/api/config");', to: 'cfg = await GET("/admin/api/conf");', kills: ["M10"] },
  { why: "M10：维护区的「停止网关」按钮没了（系统运行控制失去唯一入口）", file: "settings",
    from: '<button class="btn btn-sm btn-danger" id="st-stop">停止网关</button>', to: "",
    kills: ["M10", "M16"] },
  { why: "🔴 M11：y 与 m 两个参数框绑反（用户调的是「连续失败阈值」，写的却是重试上限）", file: "settings",
    from: 'num("y · 连续失败阈值", "scheduling", "fail_threshold", s.fail_threshold, 1)',
    to: 'num("y · 连续失败阈值", "scheduling", "retry_per_request", s.retry_per_request, 1)', kills: ["M11"] },
  { why: "M11：字段名对、取的却是别的值（api 冷却框里印的是 plan 冷却）", file: "settings",
    from: 'num("api 冷却（秒）", "scheduling", "cooldown_seconds", s.cooldown_seconds, 0)',
    to: 'num("api 冷却（秒）", "scheduling", "cooldown_seconds", s.cooldown_seconds_plan, 0)', kills: ["M11"] },
  { why: "M11：min 与 schema 下限不符（并发上限 0 = 不限，却被 HTML 拦成 ≥1）", file: "settings",
    from: 'num("并发上限（0 = 不限）", "gateway", "max_concurrent_requests", g.max_concurrent_requests, 0)',
    to: 'num("并发上限（0 = 不限）", "gateway", "max_concurrent_requests", g.max_concurrent_requests, 1)',
    kills: ["M11"] },
  { why: "🔴 M12：面板点名那条 —— markDirty 忘记解禁保存按钮（徽章照样显示，保存永远点不动）",
    file: "settings", from: '    root.querySelector("#st-save").disabled = false;\n', to: "", kills: ["M12"] },
  { why: "M12：反向 —— 干净态按钮也可点（没有未保存修改也能 PUT 一次）", file: "settings",
    from: '<button class="btn btn-primary" id="st-save" ${dirty ? "" : "disabled"}>保存配置</button>',
    to: '<button class="btn btn-primary" id="st-save">保存配置</button>', kills: ["M12", "M14"] },
  { why: "M12：改动后不插徽章（按钮可点、用户却不知道有未保存修改 —— 同源的另一半）", file: "settings",
    from: '      pa.prepend(b);', to: '      /* 变异：徽章忘了插 */;', kills: ["M12"] },
  { why: "M13：正整数过滤死掉（负号/小数点/科学计数法都能键进去）", file: "settings",
    from: 'const clean = input.value.replace(/[^\\d]/g, "");', to: 'const clean = input.value;', kills: ["M13"] },
  { why: "M13：清空被当成修改（配置写成 null → 后端 400 或落盘坏值）", file: "settings",
    from: '      if (v == null || Number.isNaN(v)) return;\n', to: "", kills: ["M13"] },
  { why: "M14：二段保存退化成一段（改一下就自动 PUT，用户还没点保存配置就落盘）", file: "settings",
    from: '      cfg[sec][input.name] = v;\n      markDirty();',
    to: '      cfg[sec][input.name] = v;\n      markDirty();\n      save(root);', kills: ["M14"] },
  { why: "M14：保存只 PUT 被改那一节（其余字段被后端按默认值重建）", file: "settings",
    from: 'await PUT("/admin/api/config", cfg);\n    dirty = false;',
    to: 'await PUT("/admin/api/config", { scheduling: cfg.scheduling });\n    dirty = false;', kills: ["M14"] },
  { why: "🔴 M15：后端 400 也弹绿色「配置已保存并热重载生效」（设置在页版的谎报形态）", file: "settings",
    from: '  } catch (e) { toast("保存失败：" + e.message, "err"); }',
    to: '  } catch (e) { toast("配置已保存并热重载生效", "ok"); }', kills: ["M15"] },
  { why: "M15：保存失败什么都不说（静默吞掉，用户以为已经保存）", file: "settings",
    from: '  } catch (e) { toast("保存失败：" + e.message, "err"); }',
    to: '  } catch { /* 变异：静默吞掉 */ }', kills: ["M15"] },
  { why: "🔴 M16：停止网关不看确认结果（点「取消」也把网关停了）", file: "settings",
    from: '    if (!await confirmDialog("停止网关",',
    to: '    if (false && await confirmDialog("停止网关",', kills: ["M16"] },
  { why: "M16：重启网关不看确认结果（点「取消」也把在途请求打断）", file: "settings",
    from: '    if (!await confirmDialog("重启网关",',
    to: '    if (false && await confirmDialog("重启网关",', kills: ["M16"] },
  { why: "M16：停止端点写错（POST 到不存在的路由，界面弹「停止失败」而用户以为已停止）", file: "settings",
    from: 'await POST("/admin/api/system/stop");', to: 'await POST("/admin/api/system/stops");', kills: ["M16"] },
  { why: "🔴 M0：API 接入页把地址字段名打错 —— esc(undefined) 交空串，地址栏变成**一片空白**（不是 undefined，坏插值判据抓不到，只能正面钉）",
    file: "apiaccess", from: '${addrPair("本机", addr.local)}', to: '${addrPair("本机", addr.loca)}',
    kills: ["M0"] },
  { why: "M17：卡头计数写成不存在的字段名（用户读到 1/undefined 启用）", file: "apiaccess",
    from: '${tokens.filter((t) => t.enabled !== false).length}/${tokens.length} 启用',
    to: '${tokens.filter((t) => t.enabled !== false).length}/${tokens.lenght} 启用',
    kills: ["M1", "M17"] },
  { why: "M17：系统设置把日志字段名打错（保留天数那格显示 undefined）", file: "settings",
    from: 'value="${g.retention_days}"', to: 'value="${g.retention_dayz}"', kills: ["M11", "M17"] },
  { why: "🔴 门自己：M 段不再把页面源码编进 realm —— 页面判据失去对象（用的是共享层复制品）",
    self: true, file: "gate",
    from: '          + `${toModuleBody(read(COMPONENTS_KEY))}\\n${mEnv(extra)}\\n`\n'
        + '          + `${toModuleBody(read(fileKey))}\\n`;',
    to: '          + `${toModuleBody(read(COMPONENTS_KEY))}\\n${mEnv(extra)}\\n`;',
    kills: ["M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10", "M11", "M12", "M13",
      "M14", "M15", "M16", "M17"] },
];

/* ==================== 变异自证 ==================== */

async function runMutations(overviewPath) {
  const work = join(tmpdir(), `mgw-fe-mut-${process.pid}-${Date.now()}`);
  for (const [key, rel] of Object.entries(FILES)) {
    const dst = join(work, rel);
    mkdirSync(dirname(dst), { recursive: true });
    copyFileSync(resolve(ROOT, rel), dst);
  }
  const base = await runChecks(work, overviewPath);
  if (base.errors.length) {
    console.error("✗ 基线抽取失败，变异结论无效：", base.errors);
    return 2;
  }
  const baseFail = base.checks.filter((c) => !c.ok).map((c) => c.id);
  if (baseFail.length) {
    console.error(`✗ 基线本身就有 ${baseFail.length} 条红（${baseFail.join(",")}）——`
      + "先修实测再谈变异，否则「变红」无法归因");
    return 2;
  }
  console.log(`\n[变异自证] 基线 ${base.checks.length} 条全绿 → 施加 ${MUTATIONS.length} 个源码变异`);
  const bad = [];
  for (const mut of MUTATIONS) {
    const path = join(work, FILES[mut.file]);
    const src = readFileSync(path, "utf-8");
    const hits = src.split(mut.from).length - 1;
    if (hits !== 1) {
      bad.push(`${mut.why} ← 锚点在 ${FILES[mut.file]} 中出现 ${hits} 次（需恰好 1 次）`);
      console.log(`  ✗ ${mut.why}  ← 锚点命中 ${hits} 次（已过期？）`);
      continue;
    }
    writeFileSync(path, src.replace(mut.from, mut.to));
    let red = [];
    let blind = "";
    try {
      // 🔴 第十一轮 eng-B B11-1：**所有**变异一律走子进程 + `--json`，取消"抛错算红"的
      //    推定分支。原先页面源码变异让 `runChecks` 崩掉时，catch 里直接 `red = mut.kills`
      //    就白拿一个"✓ 已杀死"（面板独立驱动实测 observed 99/100，门自己报 100/100）。
      //    现在只认子进程真回来的 `ok:false`；崩了/抽取盲了就记 BAD —— 逼我把判据改成能读数的。
      // 跑的是**门的副本**（ROOT 由它自己的位置推出 → 读到的正是 work/ 里被改过的那些文件），
      // 而不是被改的那个文件本身。
      // 🔴 必须有 timeout（第十二轮 eng-B S-52 的第二项）：一条死循环变异会把整轮挂死，
      //    父进程永久等在 `execFileSync` 上，还留一个 98% CPU 的孤儿进程。超时按 SIGKILL
      //    处理（SIGTERM 会被 JS 忙循环拖住），子进程被杀 → `e.name` 记进 `blind` → 该变异
      //    判 BAD，**不会**白拿一个"已杀死"。
      const out = execFileSync(process.execPath, [join(work, FILES.gate), overviewPath, "--json"],
                               { encoding: "utf-8", maxBuffer: 64 * 1024 * 1024,
                                 timeout: 30_000, killSignal: "SIGKILL" });
      // JSON 是**最后一行**：`indexOf("{")` 会撞上人读行里的 `${`（第十轮 ix）
      const parsed = JSON.parse(out.trim().split("\n").filter(Boolean).pop());
      red = parsed.checks.filter((x) => !x.ok).map((x) => x.id);
      if ((parsed.errors || []).length) blind = `门盲掉：${parsed.errors.join(" | ")}`;
    } catch (e) {
      blind = `子进程 ${e.name}，无可判读输出`;
    } finally {
      writeFileSync(path, src);
    }
    const missed = mut.kills.filter((id) => !red.includes(id));
    const extra = red.filter((id) => !mut.kills.includes(id));
    if (blind) bad.push(`${mut.why} ← ${blind}`);
    else if (missed.length) bad.push(`${mut.why} ← 纹丝不动：${missed.join(",")}`);
    console.log(`  ${(blind || missed.length) ? "✗" : "✓"} ${mut.why}`
      + (blind ? `  ← ${blind}` : "")
      + (missed.length ? `  ← 未红：${missed.join(",")}` : "")
      + (extra.length ? `  （连带变红：${extra.join(",")}）` : ""));
  }
  const covered = new Set(MUTATIONS.flatMap((m) => m.kills));
  const uncovered = base.checks.map((c) => c.id).filter((id) => !covered.has(id));
  console.log("=".repeat(56));
  console.log(`可红 ${MUTATIONS.length - bad.length}/${MUTATIONS.length}`
    + (uncovered.length ? `；未被任何变异覆盖的断言：${uncovered.join(",")}` : "；每条断言都有对应变异"));
  bad.forEach((b) => console.log(`  ✗ ${b}`));
  return (bad.length || uncovered.length) ? 1 : 0;
}

/* ==================== 入口 ==================== */

const argv = process.argv.slice(2);
const jsonPath = argv.find((a) => !a.startsWith("--"));
if (!jsonPath) {
  console.error("用法：node scripts/verify_v2_frontend.mjs <overview-json> [--mutation]");
  process.exit(2);
}
if (argv.includes("--mutation")) process.exit(await runMutations(resolve(jsonPath)));
const JSON_ONLY = argv.includes("--json");

const { checks, errors } = await runChecks(ROOT, resolve(jsonPath));
if (JSON_ONLY) {
  // 🔴 只能输出 JSON：人读行里带 `${`（K5 的判据名），父进程 `indexOf("{")` 会切到
  //    那一行然后 JSON 解析失败 —— 于是"门自己判据坏了"这次自证是**靠抛错蒙过去的**，
  //    而不是真读到 Z1 变红（第十轮 ix：推定分支不能充当证据）。
  // 抽取失败也照样回 JSON（放在 `errors` 里）：退出码固定 0，红绿与"门盲没盲"由父进程判定。
  console.log(JSON.stringify({ checks: checks.map((c) => ({ id: c.id, ok: !!c.ok })), errors }));
  process.exit(0);
}
if (errors.length) {
  errors.forEach((e) => console.error(`✗ ${e}`));
  process.exit(2);
}
const SECTIONS = { A: "配置告警横幅", B: "资源健康表", C: "状态徽章四态",
  D: "资源编辑器字段继承", E: "顶栏红点 DOM 契约", F: "红点轮询与副作用",
  G: "红点文案与指路", H: "红点样式", I: "红点行为（执行真代码）",
  J: "页名与导航同源", K: "整页装配可达性",
  L: "共享行为层真跑（api.js + components.js · S-46）",
  M: "两个正式页面真跑（apiaccess.js + settings.js · S-46 第二批）", Z: "门自身判据自测" };
const failed = checks.filter((c) => !c.ok);
let last = "";
for (const c of checks) {
  if (c.id[0] !== last) { console.log(`\n[${SECTIONS[c.id[0]]}]`); last = c.id[0]; }
  console.log(`  ${c.ok ? "✓" : "✗"} ${c.id} ${c.name}${c.ok || !c.detail ? "" : "  " + c.detail}`);
}
console.log("\n" + "=".repeat(56));
console.log(`实测 ${checks.length} 项，通过 ${checks.length - failed.length} 项，失败 ${failed.length} 项`);
failed.forEach((c) => console.log(`  ✗ ${c.id} ${c.name}`));
// 🔴 --notes：把人读模式默认不打印的 **绿态读数** 也交出来（面板批评过"零读数"的判据：
//    绿不等于有证据，detail 里的真实数字才是）。不影响默认输出与 --json（变异自证用那条）。
if (argv.includes("--notes")) {
  console.log("\n[读数明细 --notes]");
  checks.forEach((c) => console.log(`  ${c.ok ? "✓" : "✗"} ${c.id} :: ${c.detail || "(空)"}`));
}
process.exit(failed.length ? 1 : 0);
