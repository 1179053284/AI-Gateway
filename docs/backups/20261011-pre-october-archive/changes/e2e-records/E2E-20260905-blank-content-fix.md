# E2E-20260905 · 界面「只有框架、内容区空白」修复（模块混载 + 装载兜底）

> 日期：2026-09-05 · 触发：用户打开 `#/dashboard` 只见静态框架、内容区全空白
> 层级：UI 层 + 网关中间件 · 服务端实测当时正常（/health 200、overview 200、无痕浏览器渲染正常）

## 根因（证据链）
1. 框架（侧栏/顶栏）= `index.html` 静态内容；内容区 = `<main id="content">` **全由 JS 渲染** → 空白 = JS 模块图未执行。
2. `main.js:43` 的 `.catch` 只兜页面渲染期错误（会显示错误文案，不是空白）→ 空白指向**更早的模块装载失败**（import 解析错误使整个 module graph 死亡，main.js 一行都没跑）。
3. 混载来源：Q19 之前静态资源无缓存控制头 → 浏览器按启发式缓存了旧条目；本日 `dashboard.js` 新增 `import { fmtValue }`（旧 `api.js` 无此导出）→ 浏览器重拉新 dashboard.js + 命中旧 api.js → `SyntaxError: does not provide an export named 'fmtValue'` → 空白。服务端日志可见协商缓存 304（no-cache 生效但旧条目可不经协商直接命中）。

## 修复（三层）
| 层 | 改动 |
|---|---|
| 根治 | `_StaticNoCacheMiddleware`（`main.py`）：静态资源缓存头 `no-cache` → **`no-store`**（本地静态无缓存价值，不落盘 → 今后不可能再混载；Q19-① 加严，需求语义「界面更新即时可见」不变） |
| 兜底 | `index.html` 3s 装载守护：`window.__MG_BOOTED` 未被 `main.js` 置位且内容区为空 → 显示「界面脚本未能加载，请强制刷新（Cmd+Shift+R / Ctrl+F5）」指引卡片 |
| 用户侧 | 旧缓存条目无法被服务端遥控失效 → **需强刷一次**（Cmd+Shift+R），此后 no-store 根绝复发 |

## 实测证据（headless Chrome CDP）
- **兜底实测**：CDP `Network.setBlockedURLs(["*main.js*"])` 模拟装载失败 → 3s 后内容区出现兜底文案（`fallbackShown: true`，截图 `bootguard-fallback.png`）。
- **正常装载**：解除拦截新导航 → `booted: true`、8 张指标卡、资源健康表 1 行（资源口径）。
- **响应头**：`curl -I` 等价实测 `GET /js/main.js` 与 `/` → `Cache-Control: no-store`。
- 回归：pytest 全量 **187/187 passed**。

## 文档同步
design-spec v1.1（装载可靠性加固）、tech-design §4.9 加严说明、PRD FR-7.2 机制词同步（no-store + 兜底）、pitfalls 前端区两条更新。

## 影响面报备
`no-cache → no-store` 仅影响静态 UI 资源响应头（HTML/JS/CSS）；API/事件流水响应不经过该中间件分支。无测试断言旧头值（grep 证实）。
