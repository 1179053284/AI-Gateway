/** 账号页共享状态（D-1/D-4 拆分，2026-10-06）。
 *
 * 三级重绘的共享面（原 accounts.js「页面状态」段）：主文件与 accounts/ 子模块
 * 都经本模块读写——**可变状态必须有唯一居所**，ES module 的 live binding 天然
 * 提供「一处 let、处处可见」的语义（拆分前靠同文件模块级 let，拆分后靠这里）。
 */

/** GET /admin/api/accounts（唯一数据源；操作后必重取）。 */
export let view = null;
/** 当前选中产品 id。 */
export let selected = null;
/** 页面 root（drawShell 每路由一次）。 */
export let rootEl = null;
/** 产品 rail（role=tablist 容器）。 */
export let railEl = null;
/** 「只看有账号」开关所在容器（条件渲染）。 */
export let filterEl = null;
/** 右侧配置区容器。 */
export let panelEl = null;
/** §1.3 派生筛选（默认不隐藏产品）。 */
export let onlyWith = false;
/** 深链 `?p=` 未命中的 id（§4-4 要在 `.value` 注明）。 */
export let deepMiss = "";
/** §5 读失败：保留上次数据 + 重试。 */
export let loadError = "";

export const setView = (v) => { view = v; };
export const setSelected = (v) => { selected = v; };
export const setRootEl = (v) => { rootEl = v; };
export const setRailEl = (v) => { railEl = v; };
export const setFilterEl = (v) => { filterEl = v; };
export const setPanelEl = (v) => { panelEl = v; };
export const setOnlyWith = (v) => { onlyWith = v; };
export const setDeepMiss = (v) => { deepMiss = v; };
export const setLoadError = (v) => { loadError = v; };
