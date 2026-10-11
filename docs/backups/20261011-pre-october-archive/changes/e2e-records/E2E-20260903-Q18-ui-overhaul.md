# E2E 实测记录 · Q18 界面重整（2026-09-03）

> 对应：PRD v1.5 §9-Q18（① 管理端免鉴权 / ② 扁平资源模型 / ③ API 接入页 / ④ 全局调度参数 / ⑤ 界面信息架构重整）
> 设计：tech-design v1.2 §4.9、design-spec v0.4；用例：test-cases v1.2 **E2E-20**（INT-48 支撑自动生成链路）
> 网关：`http://127.0.0.1:8300/`（重启后 PID 49320，Q18 新代码）；浏览器：ego-browser（Chromium，DOM 快照取证，同 M2 口径）
> 执行方：AI（Trae）；执行时间：2026-09-03 15:41–15:55（本地）

---

## 0. 结论

| 项 | 结果 | 证据 |
|---|---|---|
| 全量回归 pytest | **184 passed**（38.77s，UT 29 + INT 48 + 其它） | §1 |
| E2E-20 五项核验 | **5/5 通过** | §2 |
| 过程缺陷 | 1 个（presets 响应解包），已修复并复测 | §3 |
| 业务链路（真实商汤） | 见 §4 | §4 |

---

## 1. 全量回归（UT/INT）

```
$ .venv/bin/python -m pytest -q
184 passed, 196 warnings in 38.77s
```

- 覆盖 test-cases v1.2 全部 UT（01~29）与 INT（01~48），含 Q18 新增：UT-29（资源开关）、INT-48（PUT config 自动生成 `res-xxxxxxxx` / `tok-xxxxxxxx` / `mg-<32hex>` 与脱敏还原）、INT-14/42/43/46/47 免鉴权与扁平口径修订。
- test-cases.md §6 状态矩阵已同步（UT 29/29、INT 48/48 通过）。

## 2. E2E-20 五项核验（浏览器 DOM 证据）

### ① 免鉴权直达（Q18-①）

- 浏览器打开 `http://127.0.0.1:8300/` **无任何令牌输入**，直接渲染总览页（title「Model-Gateway 管理界面」；顶栏「运行中 · v0.1.0 · 在途 0」；今日调用 104 / 成功 72 / 失败 23 / 中断 9 / 切换 8；资源健康 7/7）。
- 接口层：`GET /admin/api/config`、`GET /admin/api/presets` 无 Authorization 头均 200。
- 对照（业务端点仍鉴权）：`/v1/models` 无令牌 401、坏令牌 401、有效令牌 200（curl 实测，§4）。

### ② 资源管理 · 扁平表格（Q18-②⑤）

页面表格九列，实测 DOM 表头与首行：

```
备注 | 厂商 | 账号 | 模式 | Base URL | Key | 引用 | 启用 | 操作
商汤 TokenPlan·主Key | 商汤 TokenPlan | 主账号 | Plan · 积分 | https://token.sensenova.cn/v1 | sk-*****pb1w [明文] | 7 | [开关] | [编辑] [删除]
```

- 一行一资源，无实例/账号层级嵌套；账号为次要备注灰字。
- Key 默认脱敏（`sk-*****pb1w`），「明文」按钮走 `GET /admin/api/config?reveal=1`（30s 自动恢复）。
- **新增/编辑弹窗字段**：厂商预设（下拉三预设：商汤按量 API · 按量付费 / 商汤 TokenPlan · 积分制 / 自定义接入）/ 备注 / 账号 / 接入模式 / Base URL / Key 值——**无 ID 输入项**（DOM 断言 `hasIdInput: false`）。
- **端到端自动生成实测**：UI 新增资源「E2E临时资源」（http://127.0.0.1:19999/v1，sk-e2e-temp-key）→ 保存配置 → `GET /admin/api/config` 返回 `id: res-48477bee`（服务端生成，`res-` + 8 hex）→ 删除并保存还原。表格行引用数实时反映（新资源引用 0）。

### ③ API 接入页（Q18-③）

实测 DOM 结构逐项：

- **调用地址双行**：本机 `http://127.0.0.1:8300/v1` + 局域网 `http://192.168.31.57:8300/v1`，各带复制按钮；密钥用法说明（`Authorization: Bearer <密钥>` 或 `x-api-key: <密钥>`）。
- **端点说明四条**：`/v1/chat/completions`（对话 OpenAI 兼容，非流式+流式）、`/v1/images/generations`（图像生成）、`/v1/messages`（Anthropic 兼容双向转换）、`/v1/models`（仅返回已启用模型）。
- **curl 使用示例**：以第一个启用密钥与首个启用 chat 模型动态生成（实测示例含 `sensenova-6.8-flash-lite` + 当前密钥）。
- **密钥表格**：用途标注 / 密钥 / 状态 / 操作（复制·启停·删除）；现有 2 密钥正常渲染。
- **新增密钥只填名称**：弹窗仅 1 个 name 字段（DOM 断言无 value/id 输入）→ 创建「E2E临时密钥」→ 保存 → 服务端生成 `tok-d258e275` + `mg-643eed9af2b35f0b0bddd4cd5208db64`（`mg-` + 32 hex），表格即时显示明文可复制。
- **新密钥真实可用**：`GET /v1/models` 用该新密钥 200；坏密钥 401；无密牌 401。清理：删除临时密钥并保存还原（2/2 启用）。

### ④ 模型映射 · 纯业务（Q18-④）

- 页首提示：「系统模型 = 对外统一模型名 → 有序资源池（顺序即优先级；调度机制 x/y/m 全局统一，见「系统设置」）」。
- 左列 7 模型按分组（通用/编程/图像生成）+ 每模型启用开关；右列详情：启用徽章 / 端点徽章 / 资源池行（`商汤 TokenPlan·主Key [sensenova-tokenplan] / sensenova-6.8-flash-lite` + 资源级推理 effort 输入 + ↑↓移除）。
- **DOM 断言：页面无 x/y/m/超时/冷却任何字段**（全页字段仅 分组/端点/资源池/effort/别名等业务项）。

### ⑤ 系统设置 · 聚焦系统自身（Q18-⑤）

- 分区仅三卡：`01 · 任务执行` / `02 · 系统日志` / `维护`——**无「接入产品」区**（DOM 断言 `hasProductSection: false`）。
- 01 任务执行 = 全局参数唯一入口，字段：port=8300、并发上限=0、尝试超时=60、总预算=300、x=2、y=2、m=3、重试退避=0、api 冷却=60、plan 冷却=18000 + 校验提示（违反 400）。
- 02 系统日志：事件流水保留 7 天 / SSE 心跳 15s + 明文流水路径提示（data/usage/*.jsonl）。
- 维护：导出全量（含明文 Key）/ 导出脱敏 / 重启网关 / 停止网关（红色危险操作，均存在）。
- 侧边导航七页：总览 / 资源管理 / 模型映射 / API 接入 / 数据看板 / 请求日志 / 系统设置。

## 3. 过程缺陷记录（E2E 中发现并修复）

| # | 现象 | 根因 | 修复 | 复测 |
|---|---|---|---|---|
| 1 | 资源管理页渲染「presets.find is not a function」 | `GET /admin/api/presets` 返回包装对象 `{"presets":[…]}`，`resources.js` 误将整体当数组解构 | [resources.js](../../model_gateway/web/static/js/pages/resources.js#L15-L22)：改为 `presets = (pdata && pdata.presets) || []` | 浏览器强制刷新（CDP ignoreCache）后表格正常渲染，后续全部用例通过 |

## 4. 业务链路（真实商汤）

- 网关重启：旧进程 39646（M2 旧代码）SIGTERM 停止 → 端口释放、锁文件残留（pid 已死）→ 新进程 49320 启动时**自动清理陈旧锁**并重写（`{"pid": 49320, "port": 8300, …}`，INT-45 语义真机复现）。
- `/health`：`{"status":"ok", …, "resources":1, "system_models":7, "access_tokens":2}`（扁平资源口径）。
- 真实 chat 调用（`sensenova-6.8-flash-lite`，令牌 mg-trae-e2e-2026，max_tokens=8）：**200 成功**——`{"model":"sensenova-6.8-flash-lite","choices":[{"message":{"role":"assistant","reasoning_content":"Thinking Process:\n\n1.  **"},"finish_reason":"length"}],"usage":{"prompt_tokens":14,"completion_tokens":8,"total_tokens":22}}`（OpenAI 标准格式，usage 透传；finish_reason=length 系 max_tokens 截断，符合预期）。
- 鉴权矩阵（curl）：`/v1/models` 无令牌 401 / 坏令牌 401 / 新建 UI 密钥 200；`/admin/api/*` 无凭据 200。

## 5. 环境与还原

- 测试产生的临时对象均已清理：临时资源（res-48477bee）已删除、临时密钥（tok-d258e275）已删除，`data/config.yaml` 恢复 1 资源 + 2 密钥 + 7 模型。
- 网关保持运行：`http://127.0.0.1:8300/`（PID 49320）。
- 本文档由 AI 执行并记录；执行状态以本文档与 test-cases v1.2 §6 为准。
