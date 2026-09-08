/** 主入口：路由(hash)（design-spec §4；Q18-① 免令牌门）。 */

import { toast } from "./components.js";
import { renderDashboard } from "./pages/dashboard.js";
import { renderResources } from "./pages/resources.js";
import { renderModels } from "./pages/models.js";
import { renderApiAccess } from "./pages/apiaccess.js";
import { renderStats } from "./pages/stats.js";
import { renderLogs } from "./pages/logs.js";
import { renderSettings } from "./pages/settings.js";

const PAGES = {
  dashboard: renderDashboard, resources: renderResources, models: renderModels,
  apiaccess: renderApiAccess, stats: renderStats, logs: renderLogs, settings: renderSettings,
};

/* 页面元数据（Q22：顶栏面包屑分组 + 页标题由路由统一注入，页内不再重复标题） */
const PAGE_META = {
  dashboard: { title: "总览", group: "概览" },
  resources: { title: "模型资源", group: "资源配置" },
  models: { title: "资源池设置", group: "资源配置" },
  stats: { title: "数据看板", group: "运行观测" },
  logs: { title: "请求日志", group: "运行观测" },
  apiaccess: { title: "API 接入", group: "系统设置" },
  settings: { title: "系统设置", group: "系统设置" },
};

const $ = (id) => document.getElementById(id);
const content = $("content");

/* ---------- 路由 ---------- */
function route() {
  const name = (location.hash || "#/dashboard").replace("#/", "").split("?")[0] || "dashboard";
  const page = PAGES[name] ? name : "dashboard";
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
