/** API 封装：统一错误提取（Q18-① 管理端免鉴权，无令牌门）。 */

export async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  const resp = await fetch(path, { ...opts, headers });
  let data = null;
  try { data = await resp.json(); } catch { /* 非 JSON */ }
  if (!resp.ok) {
    const msg = (data && (data.errors ? data.errors.join("；") :
      (data.error && data.error.message) || data.message || data.detail)) || `HTTP ${resp.status}`;
    const err = new Error(msg);
    err.data = data;
    throw err;
  }
  return data;
}

export const GET = (p) => api(p);
export const PUT = (p, body) => api(p, { method: "PUT", body: JSON.stringify(body) });
export const POST = (p, body) => api(p, { method: "POST", body: JSON.stringify(body) });

/* ---------- 通用辅助 ---------- */

export function fmtNum(n) {
  if (n == null) return "—";
  if (n >= 1e9) return (n / 1e9).toFixed(1) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(n);
}

export function fmtDur(ms) {
  if (ms == null) return "—";
  if (ms < 1000) return ms + "ms";
  const s = ms / 1000;
  return s < 60 ? s.toFixed(1) + "s" : Math.floor(s / 60) + "m" + Math.round(s % 60) + "s";
}

export function fmtUptime(ms) {
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h}h${String(m).padStart(2, "0")}m` : `${m}m${String(s % 60).padStart(2, "0")}s`;
}

export function groupColor(group) {
  if (group === "图像生成") return "g-image";
  if (group === "编程") return "g-coding";
  return "g-generic";
}

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* 指标卡数值混排等视觉：CJK 字面占满 em 高、数字 cap 高约 0.7em，同字号下中文显大；
   CJK 段包 .cv（font-size .8em）使两者视觉等高（2026-09-05 用户反馈） */
export function fmtValue(v) {
  return esc(v).replace(/[\u4e00-\u9fff]+/g, '<span class="cv">$&</span>');
}

export function debounce(fn, ms = 300) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/* ---------- 两类接入资源的分流判据（2026-10-02 用户裁决：两类并行资源，界面不得互串） ----------
 * 判据不是命名约定，而是 `Resource` 的 schema 互斥契约（tech-design §22.5-2）：
 *   `product` 为空 ⇒ 用户自己接入的**模型供应商资源**（API Key / 供应商 plan，必须有 api_key）；
 *   `product` 非空 ⇒ 由该产品**账号体系供给的派生资源**（`account_ref` 必填、`api_key` 必须为空，
 *                    凭据在本地账号目录，`accounts/materialize.py::ensure_resource` 落的行）。
 * 聚合发生在网关调度层（两类同池、按序溢出的故障切换照旧），所以**只有视图按此分流**，
 * 任何写路径都不得因为"看不见"而删掉对方那一类（`m.resources[]` 里的隐藏条目下标必须保序）。 */
export const isDerivedResource = (r) => !!(r && String(r.product || "").trim());
export const isProviderResource = (r) => !isDerivedResource(r);
