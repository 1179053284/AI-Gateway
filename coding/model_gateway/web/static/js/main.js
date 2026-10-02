/** 主入口：路由(hash)（design-spec §4；Q18-① 免令牌门）。 */

import { toast } from "./components.js";
import { GET, POST } from "./api.js";
import { renderDashboard } from "./pages/dashboard.js";
import { renderResources } from "./pages/resources.js";
import { renderModels } from "./pages/models.js";
import { renderAccounts } from "./pages/accounts.js";
import { renderApiAccess } from "./pages/apiaccess.js";
import { renderStats } from "./pages/stats.js";
import { renderLogs } from "./pages/logs.js";
import { renderSettings } from "./pages/settings.js";
import { renderTemplates } from "./pages/templates.js";
// 模板页面（2026-10-01 用户指示接入侧栏）：`web/static/templates/*.html` 是 `frontend-spec.md` 的
// 实现基准/需求预演件；本页把全部模板收进一个入口浏览与内嵌运行。
// （2026-09-29 曾按「正式页面与参考模板剥离」移出侧栏，本次按用户新指示恢复为单入口形态；
//   清单与模板文件的双向一致由 tests/unit/test_v2_templates_page.py 钉住。）

const PAGES = {
  dashboard: renderDashboard, resources: renderResources, models: renderModels,
  accounts: renderAccounts,
  apiaccess: renderApiAccess, stats: renderStats, logs: renderLogs, settings: renderSettings,
  templates: renderTemplates,
};

/* 页面元数据（Q22：顶栏面包屑分组 + 页标题由路由统一注入，页内不再重复标题） */
const PAGE_META = {
  dashboard: { title: "总览", group: "概览" },
  resources: { title: "接入模型资源", group: "资源配置" },
  accounts: { title: "接入账号资源", group: "资源配置" },
  models: { title: "网关模型管理", group: "资源配置" },
  stats: { title: "数据看板", group: "运行观测" },
  logs: { title: "请求日志", group: "运行观测" },
  apiaccess: { title: "API 接入", group: "系统设置" },
  settings: { title: "系统设置", group: "系统设置" },
  templates: { title: "模板页面", group: "模板" },
};

const $ = (id) => document.getElementById(id);
const content = $("content");

/* ---------- 路由 ---------- */
function route() {
  const hash = location.hash || "#/dashboard";
  const name = hash.replace("#/", "").split("?")[0] || "dashboard";
  // 🔴 未知路由不再**静默回落到总览**（原写法让人以为"页面存在只是我没找到"，
  //    也让门/面板拿不到"这个路由根本不存在"的事实）：空 hash 才走总览，其余明确报找不到。
  if (!(name in PAGES)) {
    const pages = Object.keys(PAGES).map((p) => `#/${p}`).join(" · ");
    document.title = `无此页面 · Model-Gateway`;
    $("crumb-group").textContent = "路由";
    $("tb-title").textContent = "无此页面";
    content.innerHTML = `<div class="empty">没有 <b class="mono">#/${name}</b> 这个页面。<br>`
      + `可用页面：${pages}</div>`;
    return;
  }
  const page = name;
  document.querySelectorAll(".nav-item").forEach((a) =>
    a.classList.toggle("active", a.dataset.page === page));
  const meta = PAGE_META[page];
  $("crumb-group").textContent = meta.group;
  $("tb-title").textContent = meta.title;
  document.title = `${meta.title} · Model-Gateway`;
  $("sidenav").classList.remove("open");
  content.scrollTop = 0;
  content.innerHTML = `<div class="loading">加载中…</div>`;
  PAGES[page](content).catch((e) => {
    content.innerHTML = `<div class="empty">${e.message}</div>`;
  });
}
window.addEventListener("hashchange", route);

$("nav-toggle").onclick = () => $("sidenav").classList.toggle("open");

/* ---------- 主题：浅色 / 深色 / 跟随系统（Q21）---------- */
const THEME_KEY = "mg-theme";           // 持久化：light | dark | system
const mqDark = window.matchMedia("(prefers-color-scheme: dark)");
let themeMode = localStorage.getItem(THEME_KEY) || "system";

function resolveTheme(mode) {
  if (mode === "system") return mqDark.matches ? "dark" : "light";
  return mode;
}
function applyTheme() {
  document.documentElement.setAttribute("data-theme", resolveTheme(themeMode));
  document.querySelectorAll("#theme-group [data-theme-mode]").forEach((b) =>
    b.classList.toggle("on", b.dataset.themeMode === themeMode));
}
function setTheme(mode) {
  themeMode = mode;
  localStorage.setItem(THEME_KEY, mode);
  applyTheme();
}
// 跟随系统：监听系统配色变化实时切换
mqDark.addEventListener?.("change", () => { if (themeMode === "system") applyTheme(); });

document.querySelectorAll("#theme-group [data-theme-mode]").forEach((b) =>
  b.onclick = () => setTheme(b.dataset.themeMode));
applyTheme();
window.__MG_BOOTED = true;  // 模块图装载成功标记（index.html 兜底守护探测）
route();

/* ---------- 运营失败红点（v2.0 §21 / §16.6） ----------
 * 有未读 failed 时在顶栏状态区显示红点。数据源 `/admin/api/status`（复用既有轻量端点，
 * **不新建轮询端点、不新建页面**）；点击给出去哪里看（CLI）。
 * 只在页面可见时轮询，隐藏时跳过（省电、不打扰）。 */
{
  const dot = document.getElementById("ops-dot");
  const dotText = document.getElementById("ops-dot-text");
  const banner = document.getElementById("instance-banner");
  const poll = async () => {
    if (document.visibilityState === "hidden") return;
    try {
      const s = await GET("/admin/api/status");
      const n = Number(s.ops_failed_unread || 0);
      if (dot && dotText) {
        if (n > 0) { dotText.textContent = `运营失败 ${n}`; dot.hidden = false; }
        else { dot.hidden = true; }
      }
      /* 实例身份：非默认数据根 ⇒ 每页顶部一条自证横幅（文案后端单源，前端只显示）。 */
      if (banner) {
        const inst = s.instance || {};
        const show = inst.kind && inst.kind !== "default" && inst.note;
        banner.textContent = show ? String(inst.note) : "";
        banner.hidden = !show;
        banner.classList.toggle("is-fake", inst.kind === "fake-upstream");
      }
    } catch { /* 网关离线（如停机中）忽略 */ }
  };
  if (dot) {
    dot.addEventListener("click", async () => {
      // 🔴 点击 = **确认已读** → 清零（否则红点只增不减、永久常亮，验收发现）
      try {
        await POST("/admin/api/ops/ack");
      } catch { /* 网关离线忽略 */ }
      dot.hidden = true;
      // 🔴 文案必须与副作用一致：`mgw zcode claim` 是**再跑一次领取**，不是"查看"。
      //    历史明细在 `data/usage/ops-results-<日期>.jsonl`；未装 mgw 时用
      //    `python -m model_gateway.cli`（验收 M-5：原指路会 command not found）
      toast("已确认运营失败。逐条原因见 data/usage/ops-results-*.jsonl；"
            + "重跑用 mgw zcode claim（未安装则 python -m model_gateway.cli zcode claim）");
    });
    poll();
    setInterval(poll, 5000);
  }
}

/* ---------- 界面文件更新自动刷新（根治旧标签页跑旧脚本的新旧混搭） ----------
 * 启动时快照本页加载的全部界面模块文本；每 20s 重取比对，有变化 → 提示后自动刷新。
 * 仅本地小文件轮询；正常使用（文件不变）零动作。 */
{
  const FILES = ["/js/main.js", "/js/api.js", "/js/components.js", "/css/base.css",
    ...Object.keys(PAGES).map((n) => `/js/pages/${n}.js`)];
  let snap = "";
  const poll = async () => {
    try {
      const texts = await Promise.all(FILES.map((f) =>
        fetch(f, { cache: "reload" }).then((r) => r.text())));
      const cur = texts.join("\u0000");
      if (!snap) { snap = cur; return; }
      if (cur !== snap) {
        toast("界面文件已更新，3 秒后自动刷新…");
        setTimeout(() => location.reload(), 3000);
      }
    } catch { /* 网关离线（如停机中）忽略 */ }
  };
  poll();
  setInterval(poll, 20000);
}
