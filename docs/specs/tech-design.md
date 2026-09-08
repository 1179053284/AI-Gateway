# Model-Gateway 技术方案（tech-design）

> 版本：v1.6（2026-09-05 Q22 界面参考项目规范精修同步升版，对应 PRD v1.9 §9-Q22——**① 黑主色令牌**（active 态/主按钮/开关 on 统一近黑 `#171b22`，深色主题反转为白 `#e8eaee`，配套 `--on-brand` 文本令牌；推翻 v1.5 indigo 主色）；**② 参考规范组件层**（无边框软阴影卡片 + `#eef1f3` 软边框 + 分段式 tab + 参考色板徽章；tab 纯 CSS 重塑、类名契约不变）；**③ 分组侧栏 + 两行顶栏**（侧栏四分组 + 顶栏面包屑 `Console › 分组` + 页标题由路由 `PAGE_META` 注入，7 页 page-head 去重；指标卡加 38px 图标块）；**纯前端无后端变更**，§4.11）。v1.5 于 2026-09-04 Q21 界面视觉升级同步升版（对应 PRD v1.8 §9-Q21——**① 界面参考 aionui.com 简约清爽大气**（操作后台风格现代化，组件保留小圆角）；**② 三态主题：浅色 · 深色 · 跟随系统**（令牌化双主题 CSS 变量 + `html[data-theme]` + `localStorage.mg-theme` 持久化 + `matchMedia` 系统联动；顶栏主题按钮弹出菜单；侧栏随主题切换，推翻 Q19 固定深色侧栏；**纯前端无后端变更**，§4.9））。v1.4 于 2026-09-04 Q20 资源接入管理三项修正同步升版（对应 PRD v1.7 §9-Q20——**① 厂商名称自定义**（资源表单厂商名自由输入，datalist 联想快填；`resources[].vendor` 落库，`vendor_label` 优先取 vendor 压过预设，事件 provider / by_provider 口径同步，§4.3/§4.7，INT-50）；**② 映射区去除端点/分组**（资源弹窗「就地新建系统模型」只填统一名，默认 chat + 通用；端点/分组为系统模型级属性，移入系统模型页详情可编辑，§4.9）；**③ 资源定义 = 厂商 + 账号 + Key**（账号从可空备注升级为资源身份组成、表单置 Key 前必填，§4.7））。v1.3 于 2026-09-03 Q19 两项修正同步升版（对应 PRD v1.6 §9-Q19——**① 界面视觉重设计 + 静态资源禁缓存**（暗色侧边栏/SVG 图标/组件现代化；`_StaticNoCacheMiddleware` 给全部静态资源加 `Cache-Control: no-cache`，§4.9）；**② 资源导向模型映射**（映射创建移入资源弹窗、可就地新建系统模型；`@new-*` 占位资源 id 由 `PUT /admin/api/config` 保存时解析为真实 `res-<8hex>` 并同步改写 `models[].resources[].resource` 引用，§4.7，INT-49））。v1.2 于 2026-09-03 Q18 五项修正同步升版（对应 PRD v1.5 §9-Q18——**① 管理端免鉴权**（移除 allow_admin，`/admin/api/*` 直访，§4.1）；**② 扁平资源模型**（`resources[]` 一层：厂商+Key+可选账号备注，ID 自动生成 `res-xxxxxxxx`，模型映射条目改为 `resource`+`model` 引用，§4.3/§4.7）；**③ API 接入页**（端点清单+多密钥管理，§4.9）；**④ 全局调度参数**（x/y/m/超时不再按模型覆盖，`models[]` 移除覆盖字段，§5.2/§5.5）；**⑤ 界面信息架构重整**（资源表格化/模型映射纯业务/设置页去产品管理，§4.9/§10.3））。v1.1 于 2026-09-03 五项调整同步升版（对应 PRD v1.4 §9-Q17——新增 §4.10 系统运行控制与单实例锁；`GET /admin/api/presets` 厂商预设注册表；`models[].enabled` 模型启用开关；统计派生维度扩展）。v1.0 于 2026-09-03 终审通过 · §11 八项确认点全部落定：x=并发溢出生效集（Q13）/ m/y=y 先判定（Q14）/ 管理鉴权=复用访问令牌+allow_admin【**已被 Q18-① 推翻**】/ 单次尝试超时 **60s**（原 120s，终审调小）/ 请求总预算 **300s**（原 600s，终审调小）/ 延迟提交代价接受 / failed_precondition 透传+可配覆写 / 图像 URL 有效期提示三处——对应 PRD v1.3 §9-Q16）
> 对应需求：PRD v1.9（需求真相源）
> 日期：2026-09-05
> 状态：**M1 已验收**（v0.1.0：141/141 pytest + 13/13 E2E（curl 可实测项），证据 `docs/changes/e2e-records/E2E-20260903-summary.md`；商汤端点定论 = 端点 A `token.sensenova.cn/v1`（E2E-01），§10.1 十项任务全部完成）；**M2 进行中**——Q17 五项调整（PRD v1.4）已实施（181/181 pytest + E2E 证据 `docs/changes/e2e-records/E2E-20260903-M2-five-adjustments.md`）；Q18 五项修正已实施（184/184 pytest，证据 `docs/changes/e2e-records/E2E-20260903-Q18-ui-overhaul.md`）；**Q19 两项修正已实施**（视觉重设计 + 资源导向映射，185/185 pytest + 浏览器 E2E + 真实调用 200，证据 `docs/changes/e2e-records/E2E-20260903-Q19-visual-remap.md`）；**Q20 资源接入管理三项修正已实施**（厂商名称自定义 / 映射去端点分组 / 资源=厂商+账号+Key，账号必填前置；187/187 pytest（含 INT-50）+ 服务端 JS 字节核验 + 浏览器实测系统模型页，证据 `docs/changes/e2e-records/E2E-20260904-Q20-resource-mgmt.md`）；**Q21 界面视觉升级已实施**（令牌化双主题 + 三态切换，187/187 pytest 回归持平 + headless Chrome CDP 实测三态/持久化/系统联动 + 双主题截图，证据 `docs/changes/e2e-records/E2E-20260904-Q21-theme.md`）；**Q22 界面参考项目规范精修已实施**（黑主色令牌 / 参考规范组件层 / 分组侧栏 + 两行顶栏 + 指标卡图标块，纯前端；187/187 pytest 回归持平 + headless Chrome CDP 七页双主题截图 11 张，证据 `docs/changes/e2e-records/E2E-20260905-Q22-refined-ui.md`）——任何「已实现/已跑通」的宣称必须附运行证据（铁律 2）

---

## 1. 总体架构

### 1.1 架构分层

单进程异步服务，五层结构（入站 → 核心 → 出站，配置/统计/日志横切）：

```
┌────────────────────────────────────────────────────────────────┐
│        客户端工具：Trae / Claude Code / Cherry Studio / curl     │
│        （本机 127.0.0.1 或局域网 IP；Bearer <访问令牌>）          │
└───────────────────────────┬────────────────────────────────────┘
                            │ HTTP / SSE
┌───────────────────────────▼────────────────────────────────────┐
│ 入站层  model_gateway/api/                                      │
│  ├ openai_compat：GET /v1/models · POST /v1/chat/completions    │
│  │                · POST /v1/images/generations                 │
│  ├ anthropic：    POST /v1/messages（含流式）                    │
│  ├ admin：        /admin/api/*（管理 CRUD，免鉴权直访，Q18-①）  │
│  ├ web：          / 静态管理界面（本地内置，无构建）              │
│  └ auth：         /v1/* 访问令牌校验（admin 免鉴权，Q18-①）      │
├────────────────────────────────────────────────────────────────┤
│ 核心层  model_gateway/core/                                     │
│  ├ ir：          内部标准请求/响应/流事件模型（协议中间表示）     │
│  ├ scheduler：   调度状态机（选路/重试 m/切换续跑/兜底）         │
│  ├ resources：   资源池/生效集/冷却/连续失败计数（懒过期恢复）    │
│  ├ errors：      错误分类器（PRD FR-3.13 表 + 商汤校准）         │
│  └ cancel：      取消注册表（客户端断连 → 取消上游）             │
├────────────────────────────────────────────────────────────────┤
│ 出站层  model_gateway/adapters/                                 │
│  ├ openai_out：   OpenAI 兼容出站（商汤按量/TokenPlan 均走此）    │
│  ├ anthropic_out：P1 · gemini_out：P2                           │
├────────────────────────────────────────────────────────────────┤
│ 基础设施  config / enums / stats / logging                      │
│  ├ config：YAML 加载·pydantic 校验·热重载·原子写                │
│  ├ enums：统一模型名枚举池与自动匹配（规范化/别名/置信度）       │
│  ├ stats：事件 JSONL 流水 + 日聚合快照 + 查询聚合               │
│  └ logging：key 全程脱敏                                        │
└────────────────────────────────────────────────────────────────┘
                            │ httpx（异步，流式）
                    厂商上游（商汤等）
```

### 1.2 运行形态
- 单进程（`uvicorn` 单 worker）；管理 API、网关 API、Web 界面**同端口分路径**（默认 `0.0.0.0:8300`，可配）。
- 全 asyncio：每请求一个处理 task；上游请求独立 task，与客户端响应 task 解耦——这是**取消透传**与**切换续跑**可并存的基础。
- 无数据库、无外部消息队列；全部状态在内存 + 本地明文文件。

---

## 2. 技术栈选型

| 层 | 选型 | 理由 | 备注 |
|---|---|---|---|
| 语言 | Python 3.12+ | 用户指定首选；asyncio 生态成熟 | — |
| Web 框架 | FastAPI + uvicorn | 原生 async、SSE（StreamingResponse）、中间件、自动文档 | ASGI |
| 出站 HTTP | httpx（AsyncClient） | 流式读取、精细超时、task 级取消 | 连接池复用 |
| 配置/校验 | PyYAML（MIT）+ pydantic v2（BSD-3-Clause） | 明文 YAML 读写 + 严格 schema 校验 | 均宽松开源许可 |
| Web 界面 | 原生 ES Modules + 手写 CSS（简约风），图表用 **vendored 本地 Chart.js** | 无构建工具链；**禁止 CDN**（宪法级纯本地，前端资源随源码本地内置） | Chart.js MIT，随仓库内置 |
| 测试 | pytest + pytest-asyncio + httpx MockTransport / 本地假厂商 ASGI 服务 | 假厂商后端可编程注入错误序列，确定性验证调度 | 见 test-cases.md §1 |
| 日志 | 标准库 logging | key 脱敏包装 | — |

宪法级约束落实：无遥测、无远程配置、无自动更新；前端静态资源全部本地内置；唯一出站流量是用户配置的厂商 API 调用。

---

## 3. 请求生命周期（核心数据流）

以 `POST /v1/chat/completions`（流式）为例：

1. **鉴权**：auth 中间件校验访问令牌（`Authorization: Bearer` / `x-api-key` 按协议惯例）；无效 → 401。
2. **解析**：入站协议请求体 → IR 请求（消息/工具/参数；不认识的字段原样保留于 `vendor_params` 透传）。
3. **模型解析**：`model` 名 → 系统模型定义（枚举池或自定义）；不存在 → 404（标准 error 格式）；命中 enabled=false 的禁用模型（含别名）→ 同样 404，但 `code="model_disabled"`，不进入调度（§4.7 模型启用开关）。
4. **调度选路**：Scheduler 按 §5.3 选路规则——生效集（top-x 可用资源）内取**在途请求最少**者承接（平局取优先级高；低负载即集中打最高优先级，并发时溢出），获得该请求的执行计划（§5）。
5. **出站构造**：IR → 厂商协议请求（出站适配器按资源 protocol 选择）。
6. **上游调用**：httpx 流式请求；注册到 CancelRegistry（request_id → 上游 task）。
7. **流式转发（延迟提交）**：**收到首个内容事件前不向客户端发送任何字节（含响应头）**——此窗口内失败可无感重试/切换续跑；首个内容事件到达后才提交响应头 + 开始转发（§6）。
8. **失败处理**：每次尝试失败 → ErrorClassifier 分类 → 按 §5 统一规则处理（重试/切换/透传/兜底）。
9. **取消透传**：客户端断连 → 响应 task 被 cancel → CancelRegistry 取消对应上游 task；标记 `aborted`，**不计失败、不触发切换**（§4.6）。
10. **收尾**：请求结束（成功/失败/取消）→ 统计事件一行 JSONL 追加（含逐资源尝试明细、重试/切换次数、TTFT、token、usage 来源）。

非流式与图像生成：同链路，无第 7 步的流式细节（响应整体成功或失败，天然可重放）。

---

## 4. 核心模块设计

### 4.1 入站层（api/）

| 端点 | 方法 | 说明 |
|---|---|---|
| `/v1/models` | GET | 仅返回 enabled=true 的系统模型（OpenAI 格式；禁用模型及其枚举池别名不出现——模型启用开关见 §4.7 / PRD FR-2.3） |
| `/v1/chat/completions` | POST | 非流式/SSE 流式；tool calls 透传；厂商扩展参数（thinking/reasoning_effort 等）原样透传 |
| `/v1/images/generations` | POST | 图像生成（OpenAI images 格式）；调度/重试/切换/取消同样适用 |
| `/v1/messages` | POST | Anthropic 原生（含流式），供 Claude Code 直连 |
| `/admin/api/*` | - | 管理 CRUD（资源/模型映射/密钥/设置/统计查询/日志查询/健康测试）+ **`/admin/api/overview` 总览一次取齐**（运行状态/资源健康/今日聚合/最近切换，见 §4.4）+ **`/admin/api/status` 轻量状态**（version/uptime/in_flight/资源快照含 `available` 口径；顶栏 5s 轮询专用——不读事件文件，与 overview 职责区分）——**全部免鉴权直访（Q18-①）** |
| `/admin/api/system/stop` | POST | 系统运行控制：**优雅停机**（免鉴权；返回受理确认——在途请求收尾后进程退出 + 释放单实例锁，见 §4.10） |
| `/admin/api/system/restart` | POST | 系统运行控制：**自重启**（免鉴权；返回受理确认——优雅停机 + 释放锁后 `os.execv` 进程映像替换：PID 不变、同端口重绑、配置重读、锁重新登记，见 §4.10） |
| `/admin/api/presets` | GET | 厂商预设注册表清单（免鉴权；资源表单数据源，见 §4.7） |
| `/admin/api/resources/test` | POST | 单资源 + 厂商模型连通性测试（FR-9.1 最小版，2026-09-05）：最小请求 max_tokens=1，超时 min(30s, 尝试超时)，返回 ok/latency_ms/error |
| `/` | GET | 静态管理界面 |

- 鉴权（Q18-① 修订）：**仅 `/v1/*` 三协议端点要求访问令牌**（Bearer / x-api-key）；管理界面与 `/admin/api/*` **免鉴权直访**（无令牌门、无 localStorage 令牌）。**推翻原因链**：v1.0 终审曾定「admin 额外要求 `allow_admin: true`」——自用单用户场景下徒增摩擦（每次开界面先拿令牌），用户明确「自用的系统暂时不用考虑这个」→ allow_admin 字段与管理端校验整体移除。
- 错误响应：按入站协议各自标准 error 格式（OpenAI / Anthropic / images）。

### 4.2 IR（内部标准格式，core/ir.py）

- **请求**：`messages`（role + content parts：text / image(base64|url) / tool_use / tool_result）、`tools`、采样参数、`stream`、`vendor_params`（原样透传字典）。
- **响应（非流式）**：content（text / tool_calls）、`finish_reason`（映射：stop/length/tool_calls/content_filter）、`usage`、`raw`（原始响应保留）。
- **响应（流式）**：统一事件流——`text_delta` / `reasoning_delta` / `tool_call_delta` / `usage` / `finish` / `error`。
- **设计原则：透传优先**——IR 只做协议间**必需**的语义映射；同协议进出（OpenAI→OpenAI，首发主链路）时近乎零转换，未知字段不丢弃。协议差异在**出站适配器内归一化**：
  1. 商汤 DeepSeek V4 Pro 流式 `delta.thinking_content` vs 其他 `delta.reasoning_content` → 统一为 `reasoning_delta`；
  2. **kimi-k3 图片输入仅支持 base64（PRD FR-1.8 官方口径）**：出站适配器在发送 kimi-k3（及枚举池标记 `only_base64_image: true` 的模型）前，**自动把请求中的 image_url 公网 URL 下载为 bytes → 转 base64 嵌入**；下载异常按 RETRYABLE 分类（单次下载超时/失败计入当前尝试失败，参与正常重试/切换），但不做跨资源（换资源对 URL 下载问题无帮助）。
- **请求 model 解析（所有入站端点统一）**：按「精确命中系统模型名 → 枚举池别名（含 Anthropic/Gemini/厂商原生 model id）→ 规范化匹配（忽略前缀/日期后缀/大小写）」逐级尝试；仍无 → 404。命中 **enabled=false** 的系统模型（含别名命中）→ 同样 404，但 error code 为 `model_disabled`（三端点一致，不进入选路、不触达上游，§4.7 模型启用开关）。由此 Claude Code 等直连工具填 Anthropic 原生 model id 可自动映射到统一系统模型（PRD FR-5.2 兼容）。
- **端点类型校验**：入站端点根据端点类型严格校验系统模型的 `endpoint` 字段——chat 端点（chat/completions / messages）**只接受 endpoint=chat** 的系统模型；images 端点（images/generations）**只接受 endpoint=images** 的系统模型。model 名合法但 endpoint 不匹配 → 400 标准 error（含「模型 XXX 为图像生成模型，请通过 /v1/images/generations 调用」之类明确说明），不触达上游。
- **推理参数（三级合并，PRD Q15/FR-3.16）**：IR 请求显式携带 `reasoning: {enabled: bool | None, effort: str | None}`——仅当请求方**明确指定**时非 None（**「未指定」≠「显式关闭」**，两者必须区分）。出站构造时按**当前尝试资源**合并：`请求级显式值 > 资源级 reasoning 默认 > 不注入（厂商默认）`：
  1. 入站解析时把请求体中的 `reasoning_effort` / `thinking` 从透传字典**提升**为 IR 显式字段（防出站双重注入）；
  2. **合并发生在每次出站构造**（每次尝试/切换目标资源独立合并）——切换续跑换资源后自动按新资源默认重算，非流式/流式天然一致；
  3. 资源未配置且请求未指定 → 出站请求体不含任何推理字段（走厂商默认行为）；
  4. images 类资源不适用推理参数（配置校验警告并忽略）。

### 4.3 调度核心（core/scheduler.py + resources.py + errors.py）

**ResourceManager（全局资源注册表 + 每系统模型有序池；Q18-② 扁平模型）**
- **全局注册表**：`resources[]` 一层扁平（资源 = 厂商 + Key），每条含 `id`（系统自动生成 `res-xxxxxxxx`，全局唯一）/ `name` / `preset` / `access_mode` / `protocol` / `base_url` / `api_key` / `account`（可选账号备注）/ `enabled`。资源状态对象按**资源 ID** 索引；同一资源被多个系统模型引用时状态**全局唯一**——PRD Q11「失败判定按厂商资源维度计数」的准确落地：在模型 M1 的池中该资源连续失败达 y 冷却后，模型 M2 的池中它**同步不可用**（同一次计数、同一次冷却）。配置删除某资源的全部引用时，清理其无主状态。
- 每个系统模型仅持有**有序映射条目列表**（`{resource: <资源ID>, model: <厂商模型ID>, reasoning?: {...}}`，优先级 = 列表顺序），不复制状态。
- **出站适配器按资源 ID 动态管理**：每资源一个 adapter 实例（httpx AsyncClient 池化）；`base_url` 变更（热重载/界面保存）时按 diff 重建受影响资源的 adapter，未变资源连接池保持复用。
- **厂商口径（provider label，Q18-②）**：统计与事件行的 `provider` 字段按资源解析——预设资源取预设展示名（如「商汤按量 API」）、无预设（custom）资源取资源名称备注；`account` 字段直接取资源 `account` 备注（未标注为 null）。
- 资源状态：`active`（可用）/ `cooldown`（冷却至 T）/ `disabled`（手动/401 停用）/ `invalid`（404 模型无效）。
- 每资源维护：连续失败计数 `C`（跨请求累计，含请求内重试；**成功即清零**）、冷却截止时间、状态、最近错误。
- 冷却恢复：**懒过期**——每次选路时检查 `cooldown_until < now` 则恢复 `active`（按原优先级归位），无需后台定时器。
- 状态变更（计数/冷却/停用）以 `asyncio.Lock` 串行化（单进程内足够）。

**ErrorClassifier（PRD FR-3.13 的代码化）**

| 类别 | 判定 | 处理（详见 §5 规则） |
|---|---|---|
| `RETRYABLE`（网络/超时/5xx，商汤 500 `internal_server_error`） | 连接异常、读超时、HTTP 5xx | 重试 ≤ m → 切换续跑；计入 C |
| `QUOTA`（429/配额，商汤 `quota_exceeded_error`） | HTTP 429 或错误体配额语义 | 短指数退避重试（默认 2 次）→ 移出冷却 + 切换续跑 |
| `AUTH`（401/403 凭据类） | HTTP 401；403 且错误体属凭据/权限类 | 立即停用 + 告警事件 + 切换续跑（不重试、不计 C） |
| `NOT_FOUND`（404，商汤 `not_found_error`） | HTTP 404 | 标记 invalid + 告警 + 切换续跑（不重试） |
| `BAD_REQUEST`（4xx 参数类，商汤 400 `invalid_request_error` / `failed_precondition_error`；商汤 403 `permission_denied_error` 语言类） | 其余 4xx | **原样透传调用方**（换资源同样失败，不重试不切换） |
| `CANCELED`（408 / 客户端中断，商汤 `canceled_error`） | HTTP 408 或客户端断连 | aborted 语义，不计失败不切换 |

- 分类输入：HTTP 状态 + 厂商错误体（`type` 字段等）；商汤 type 已按官方文档校准入表（PRD FR-1.8）。
- 规则表**配置可扩展 + 可覆写**：`config.yaml: error_rules` 支持对特定 `(http_status, error_type)` 覆写默认分类（优先级：type 精确匹配 > HTTP 通用映射）。**典型用例**：把商汤 `failed_precondition_error`（默认 BAD_REQUEST 透传）中「引擎不可用」子类覆写为 RETRYABLE 走切换续跑（PRD FR-1.8 官方口径「默认透传，引擎不可用类可配为切换」）。M1 仅配置层支持；M2 提供界面编辑。
- `finish_reason: content_filter` 在流/响应层处理为正常结束（不算失败）。

### 4.4 出站适配层（adapters/）与 Admin 运行状态端点

- `openai_out`（首发）：chat completions + images generations；流式 SSE 解析（含商汤思考字段差异归一化、usage 读取 `stream_options.include_usage`）；多轮工具调用回传完整性由透传原则保证（IR 不删字段）。
- **推理参数出站映射（PRD Q15/FR-3.16，三级合并结果 → 厂商参数）**：合并后的归一化值由适配器按模型映射——商汤 V4 Pro：`reasoning.enabled` → `thinking.type`（`enabled`/`disabled`，仅支持思考开关的模型）；`reasoning.effort` → `reasoning_effort` **原样透传**（opaque 字符串，取值以厂商为准——商汤 V4 系 `low/high/max`，PRD FR-1.8 官方口径；网关不强校验枚举，厂商侧校验失败按 BAD_REQUEST 透传）。Anthropic / Gemini 出站适配器的推理参数映射在各自适配器阶段（P1/P2）按官方文档校准，不在本文档预先断言参数名。
- **U1 Fast / U1.5 Lite URL 有效期提示**（PRD FR-1.8 P0 要求「网关透传时在文档/界面提示该差异」；终审确认点 8：**三处齐上**）：图像生成响应中 `response_format=url` 时，① 在响应 JSON 附加扩展字段 `_gw_note.url_valid_hours`（U1.5 Lite=24，U1 Fast=1）；② **在响应头附加 `X-GW-URL-Valid-Hours: <hours>`**（curl/程序化调用方看头即知，零风险不污染响应体）；③ 枚举池条目 `response_format_url_hours` 字段按模型记录，M2 模型映射详情页展示提示说明。INT-38 验证。
- `anthropic_out`（P1）/ `gemini_out`（P2）：按资源 `protocol` 字段选择。
- 适配器接口：`async def call(resource, ir_request) -> IRResponse | AsyncIterator[IREvent]`（非流式/流式两形态）+ `async def list_models(resource)`。

**`GET /admin/api/overview`（总览一次取齐：运行状态 + 资源健康 + 今日聚合 + 最近切换 + 调用地址；FR-7.1 Dashboard 总览、请求日志页「切换事件」tab 与排查的数据源；M1 已实现）**：
- 返回字段：`{ version, uptime_ms, in_flight_requests, today（今日调用聚合，含 today_switch_count 今日切换次数指标）, today_by_hour（24h 分桶趋势）, resources: [{resource_id, system_models[], status, C, cooldown_remaining_ms, last_error}], recent_switch_events: [ {ts, system_model, from_resource, to_resource, reason, cls} ](内存环形缓冲容量 200，端点返回最近 20 条), call_addresses（本机/局域网调用地址） }`。
- `recent_switch_events` 由调度器在每次「bench(R) → 切下一资源」时写入内存环形缓冲；**同时写入独立事件行** `data/usage/switch-events-YYYYMMDD.jsonl`（与每请求事件行分开存放，按天分文件、7 天保留），供看板/日志页与排查直接读取。这是 PRD FR-3.14「切换与重试事件记录」的精确落地。
- **Q17-1 口径**：总览页**不常驻渲染事件明细**——今日切换以指标数字呈现（D5），明细移至请求日志页「切换事件」tab 按需查看；`recent_switch_events` 字段保留供请求日志页与排查复用（PRD FR-7.1）。

### 4.5 流式处理与「延迟提交」（§6 详述）

- 上游 httpx stream → 逐 SSE 事件解析 → IR 事件 → 入站协议再编码转发。
- **响应头延迟提交**：首个内容事件到达前不发送响应头——失败窗口内可整体重试/切换（客户端零感知）；全失败则返回标准 HTTP 错误（对工具兼容性最好）。
- **流式端点的实现纪律（避免 HTTP 语义违规）**：窗口内（首内容事件前）全部尝试+切换+退避若**耗尽失败**，路由 handler 直接 `return JSONResponse(status_code=<对应码>, body=<标准 error 格式>)`（**503 / 429 / 401 / 404 / 400**，按兜底原因取码），**不构造 StreamingResponse**。只有当首内容事件确定到达、能正向输出时，才构造 `StreamingResponse(status=200)` 并开始 yield SSE 数据。由此**绝对避免「先发 200 header 再发 error 内容」**的 HTTP 违规形态（会让工具端把错误当正常响应）。
- TTFT = 首个内容事件到达时刻 - 请求进入时刻。

### 4.6 取消管理（core/cancel.py）

- `CancelRegistry`：`request_id → 上游 task`；请求结束注销。
- 客户端断连：uvicorn cancel 响应 task → generator 内捕获 `CancelledError`/`asyncio.CancelledError` → **先取消上游 task 再退出**。
- **延迟提交窗口内的断连（首帧未发出、重试/退避/切换进行中）**：非流式 endpoint 在响应未开始时，ASGI **不会**因断连自动 cancel handler task——须在**每次尝试边界主动探测**（`await request.is_disconnected()`，Starlette 基于 receive channel 轮询，开销极小）；探测到断连 → 取消当前上游 → **中止整个尝试链**（不再重试/切换/退避）→ 标记 `aborted`（不计失败、不触发冷却）。退避 sleep 期间以 `asyncio.wait(..., timeout)` 分段，保证可被取消及时打断。
- **关键纪律**：取消路径的 `CancelledError` 必须 re-raise，严禁被通用 `except Exception` 吞掉转成「失败」（否则误计 C、误触发切换）——单测强制覆盖（test-cases UT/INT）。
- SSE 心跳：上游静默超过 `heartbeat_seconds`（默认 15s，可配）发送 `: keep-alive\n\n` 注释帧，尽早暴露死连接。
- 厂商侧返回 408 `canceled_error`（如商汤）：aborted 语义（不计失败、不触发切换），错误**透传调用方**。

### 4.7 配置中心（config/）

- 启动：读 `data/config.yaml` + `data/model-enums.yaml` → pydantic 校验 → 内存快照。
- **热重载**（双触发）：① mtime 轮询后台 task（1s）；② 管理界面保存。两者都：校验通过 → **原子替换**（tempfile + `os.replace` 同目录）→ 重建快照 → 发布 reload 事件；校验失败 → 拒绝并保留旧快照（返回明确错误）。
- **在途请求不受重载影响**：请求开始时绑定配置快照引用，完整执行后结束。
- 校验规则（嵌套层级完整；Q18-② 扁平化后口径）：① **资源引用完整性**：`models[].resources[].resource` 必须存在于 `resources[]`（按资源 ID）；资源 `preset` 若非空必须存在于预设注册表；② 资源 → vendor_model 必须存在于配置或枚举池；③ 数值边界：`x≥1、y≥1、m≥0、冷却≥0、退避≥0、超时≥1、总预算≥超时`；④ 系统模型 endpoint 字段必须为 `chat | images`；⑤ 端口范围合法；⑥ **资源级推理默认 `reasoning`（Q15）**：`enabled: bool`、`effort: 非空字符串`（均可选；effort 值不做枚举强校验，opaque 透传），配置于 endpoint=images 的资源 → **校验警告并忽略**（不阻塞加载）；⑦ **模型启用开关（Q17/D1）**：`models[].enabled` 必须为 bool（非 bool 值拒绝并指明位置；缺省视为 true，UT-25）；⑧ **Q18-④**：`models[]` **不再接受** `max_active` / `fail_threshold` / `retry_per_request` 覆盖字段（未知字段按 pydantic 默认忽略或告警，文档明确不支持）；⑨ **ID 唯一性（Q18-②）**：`resources[].id` 全局唯一（自动生成保证；手填冲突 → 校验错误指明位置）。错误信息**逐条指明位置**（如 `resources[2].api_key`、`models[0].resources[1].resource`）。
- **模型启用开关 `models[].enabled`（Q17/D1，PRD FR-2.3）**：bool，**默认 true**——现有 config.yaml 无该字段时视为启用（向后兼容）。置 false 时：① `GET /v1/models` 不返回该系统模型，其枚举池**别名同样不出现**；② 对禁用模型（含别名命中）的请求在 `/v1/chat/completions`、`/v1/images/generations`、`/v1/messages` **三端点一致拒绝**——HTTP 404 + 各协议标准 error 格式，`code="model_disabled"`，message「模型已禁用，可在管理界面开启」；**不触达上游、不计资源失败**（不参与重试/切换/冷却判定，模型解析阶段即拒绝，§4.2）；③ 管理界面保存或 config.yaml 热重载后**对新请求即时生效、在途请求不受影响**（请求绑定配置快照的既有语义）。UT-24/25、INT-39~41、E2E-16 验证。
- **资源启停开关 `resources[].enabled`（Q18-② 扁平化后口径；原 v1.1「产品接入开关 providers[].enabled」随实例层级一并移除）**：bool，默认 true。置 false 时该资源**退出调度**——`resources.py rebuild` 以 `enabled` 聚合为资源可用口径（`available()` 通道，复用 §5.3 选路过滤），模型若无其他可用资源 → 503 `NO_RESOURCE`（与模型级禁用的 404 `model_disabled` 语义区分：模型级=模型本身关闭，资源级=供给侧退出）。资源快照（`/admin/api/status`、`overview`）含 `available` 综合布尔，资源列表行内直接呈现启停开关。
- **厂商预设注册表（Q17，PRD FR-1.2）**：`model_gateway/config/presets.py` 以**模块级常量清单**内置预设数据（数据驱动，非硬编码 UI 分支），每条字段：`id` / `name`（名称）/ `mode`（接入模式 `api|plan`）/ `protocol`（协议）/ `base_url` / `billing`（计费口径）/ `notes`（说明文案）。首发内置三条：

  | id | mode | protocol | base_url | billing |
  |---|---|---|---|---|
  | `sensenova-api`（商汤按量 API） | api | openai 兼容 | `https://api.sensenova.cn/compatible-mode/v2` | 按量付费 |
  | `sensenova-tokenplan`（商汤 TokenPlan） | plan | openai 兼容 | `https://token.sensenova.cn/v1` | 积分制 |
  | `custom`（空白自定义模板） | — | — | （空） | — |

  `GET /admin/api/presets`（免鉴权，Q18-①）返回该清单，供资源表单预设下拉渲染（M2 资源管理页）。**扩展原则：新增厂商或 Plan 类型 = 仅加一条预设数据**（必要时新增协议适配器），资源表单与 UI 框架零改动；`billing` 为可扩展枚举，未知口径前端优雅降级显示「—」。UT-26、INT-46 验证。
- **配置写入的 ID 自动生成与脱敏还原（Q18-② + Q19-② 占位解析）**：`PUT /admin/api/config` 保存时——① 新增资源 `id` 为空 → 服务端生成 `res-<8hex>`；② 新增访问密钥 `id` / `value` 为空 → 服务端生成 `tok-<8hex>` / `mg-<32hex>`；③ `GET /admin/api/config` 返回的 Key 为脱敏形态（`sk-****tail`），保存回传时服务端识别脱敏形态并**还原为已存明文**（未变更不损坏；变更明文则覆盖）；④ **占位资源 id 解析（Q19-②）**：资源弹窗内即配映射时，新资源（尚未落库、无真实 id）以 `@new-*` 占位 id 被 `models[].resources[].resource` 引用 → 保存时服务端统一生成真实 `res-<8hex>` 并**同步改写全部映射条目的引用**（一次 PUT 完成资源 + 映射落库，热重载即刻生效）。INT-48/49 验证。
- 纳入配置 schema 的运行参数（PRD §6 示意的精确化）：
  | 参数 | 默认 | 说明 |
  |---|---|---|
  | `max_concurrent_requests` | 0（不限） | FR-4.2 网关整体并发上限；超限返回 429 + Retry-After |
  | `attempt_timeout_seconds` | **60**（终审由 120 调小） | 单次上游尝试整体超时（connect + read + write），承接 PRD §6 `request_timeout_seconds` |
  | `request_total_budget_seconds` | **300**（终审由 600 调小） | 单请求全部尝试+重试+退避的总时长上限（§5.5） |
  | `heartbeat_seconds` | 15 | SSE 心跳注释帧间隔 |
  | `retry_backoff_seconds` | 0 | RETRYABLE 类同资源重试间隔（0=立即） |
  | `quota_retry` | 2 | QUOTA(429) 短指数退避重试次数（官方建议口径） |
  | `quota_backoff_base_seconds` | 1 | QUOTA 退避基数（第 n 次 = base×2^(n-1)） |
  | `cooldown_seconds` | 60 | api 模式默认冷却时长 |
  | `cooldown_seconds_plan` | 18000 | plan 模式默认冷却时长（对齐商汤滚动 5h 窗口） |
  | `retention_days` | 7 | 事件流水+切换事件+运行日志保留天数 |
  | `error_rules[]` | [] | 覆写默认分类的规则列表（§4.3） |
- **P1 字段预留（M1 允许保留、不强制校验语义）**：PRD FR-10.3 令牌配额 `access_tokens[].quotas.{daily_requests,daily_tokens,total_tokens}`、FR-8.4 导入导出字段。M1 配置 loader 读到这些字段时保留原值、不透传、不校验上限；M3 启用时补语义。
- 环境变量引用 `${VAR}`（P1）。

### 4.8 统计与日志（stats/）

- **事件流水**：每请求一行 JSONL（`data/usage/events-YYYYMMDD.jsonl`，**按天分文件**——较 PRD §6 示意的按月分文件调整：7 天保留清理 = 删除整天文件，简单且原子；PRD §6 标注「示意，最终以架构文档为准」）；**写入经单写队列串行化**（asyncio.Queue + 单写 task），防并发请求交错断行：
```json
{
  "request_id": "...", "ts": "...", "client_token_id": "tok-xxxxxxxx",
  "system_model": "deepseek-v4-flash", "endpoint": "chat", "stream": true,
  "status": "success | failed | aborted",
  "resource_attempts": [
    {"resource": "资源A/vm-A", "attempts": 2,
     "errors": ["500", "500"], "switched": true}
  ],
  "final_resource": "资源A/vm-A", "provider": "商汤按量 API", "account": "主账号",
  "retry_count": 2, "switch_count": 1,
  "duration_ms": 1234, "ttft_ms": 210,
  "input_tokens": 100, "output_tokens": 500,
  "usage_source": "vendor | estimated",
  "images_count": null, "error_summary": null
}
```
- **事件行冗余 `provider` / `account` 字段（Q17，PRD FR-6.1 派生维度；Q18-② 扁平化后口径）**：写入时由配置快照按**承接资源**（资源 ID）解析——`provider` = 预设资源取预设展示名（如「商汤按量 API」）、无预设取资源名称备注；`account` = 资源账号备注字段（未标注为 null；无承接资源或解析失败同样为 null）；**历史行无该字段时聚合按空值兼容**（归入空值组，不报错）。UT-27 验证。
- **切换事件独立流水**（PRD FR-3-14「切换与重试事件记录」精确落地）：每次「触发 bench(R) 并切到下一资源」写入一行 `data/usage/switch-events-YYYYMMDD.jsonl`（按天分文件、7 天保留、单写队列串行化）：`{"ts", "request_id", "system_model", "from_resource", "to_resource", "reason_cls", "error_summary", "was_cooldown": true/false}`。重试（同资源内 m 次）不出独立行，只在 per-request 事件的 `retry_count`/`resource_attempts[].attempts` 体现。
- **日聚合（单天单文件）**：启动时 + 每小时整点，**把当日 events 重算并覆盖写入 `daily-YYYYMMDD.json`**（每一天一个独立文件）。字段：按系统模型 / 资源 / 令牌 / **厂商（provider）/ 账号（account）**五维（`by_model` / `by_resource` / `by_token` / `by_provider` / `by_account`，后两维为 Q17 新增派生维度——由事件行冗余字段聚合而来，PRD FR-6.1）的次数、成功/失败/中断、token、重试、切换、耗时、TTFT、图像张数、费用估算；**历史天的 daily 文件一旦生成不再修改**（重算成本小：events 只保留 7 天）。对比 PRD 示意的 `daily-YYYYMM.json`（月度文件），修正为按天文件的好处：原子覆写、重启无损、7 天清理时直接删 N 天前的两个文件（events + daily）。
- 保留策略（统一）：`retention_days`（默认 7）天之前的 **events-YYYYMMDD.jsonl / switch-events-YYYYMMDD.jsonl / daily-YYYYMMDD.json** 三个文件**原子删除**（启动时 + 每日 04:00 后台 task）。日聚合快照文件**超 7 天也保留**（看板历史视图，容量可忽略）——即只删 events/switch-events，daily 快照历史全部保留。
- 看板/日志页数据源口径：请求日志页读事件 JSONL（实时）；数据看板读「历史 daily 文件 + 当日 events 实时重算」双段，避免整点前数据滞后。**admin stats 响应含可用维度键列表**（`by_model` / `by_resource` / `by_token` / `by_provider` / `by_account`），前端看板维度 tab 由维度键数据驱动生成、**不写死维度清单**（Q17，PRD FR-7.6）——后端新增维度，前端自动出现对应 tab。UT-27、INT-47 验证。
- 费用估算：纯本地查表算术（pricing 表），未配置不计费。
- 日志：`data/logs/gateway.log`（运行日志），key 脱敏（`sk-****tail`）；`RotatingFileHandler` 轮转（默认 10MB × 5 备份，可配），防长期运行无限增长。

### 4.9 Web 管理界面（web/）

- 页面对应 PRD FR-7（**Q18-③/⑤ 信息架构重整：七页**——总览 / **资源管理** / 系统模型 / **API 接入** / 数据看板 / 请求日志 / 系统设置）；design-spec v0.5（modern-minimal，含 Q18 重整 + Q19 视觉重设计与资源导向映射）已产出，M2 据此实施。
- **各页要点**：
  - **资源管理**：扁平资源**表格列表**（名称/厂商预设/账号备注/接入模式/base_url/Key 脱敏+明文切换/映射数/状态/启停/编辑/删除），新增资源表单含预设下拉（`GET /admin/api/presets` 数据驱动）；**资源 ID 不出现于表单**（服务端自动生成）；**新增/编辑资源弹窗内一并配置模型映射（Q19-②）**——「厂商模型 → 系统统一模型」映射行（厂商模型名输入带枚举池 datalist 候选；目标下拉列已有系统模型 + 「＋ 新建系统模型…」就地新建：名称/端点 chat|images/分组；新资源以 `@new-*` 占位 id 引用，§4.7-④ 服务端解析）；
  - **系统模型（Q19-② 重定位：总览与微调）**：左侧分组模型列表（分组标题 + 模型名，选中态高亮）+ 右侧选中模型详情（名称/启停徽章/端点/分组说明、资源池有序管理：上移下移、资源级推理默认、移除、删除模型）；**映射的新增/调整不在本页**——引导文案指向「资源管理」页编辑对应资源；**无任何调度参数**（全局参数在系统设置，Q18-④）；
  - **API 接入（Q18-③）**：调用地址（本机/局域网）+ 端点清单（`/v1/models`、`/v1/chat/completions`、`/v1/images/generations`、`/v1/messages`）+ 鉴权方式说明 + curl 示例 + **访问密钥管理表格**（名称/值/复制/启停/删除，添加时名称可标注工具用途，支持多密钥）；
  - **系统设置**：网关参数 + 调度全局参数（x/y/m/退避/冷却）+ 数据目录 + 系统运行控制（重启/停止）；**无令牌管理（移至 API 接入页）、无「接入产品」管理（Q18-⑤）**。
- **视觉方案（Q19-① 重设计 + Q21 令牌化双主题）**：**令牌化双主题**——`base.css :root` 定义浅色令牌 + `[data-theme="dark"]` 覆盖深色令牌（bg/surface/border/text/brand/语义色/侧栏/阴影/滚动条/开关全量令牌化，`color-scheme` 同步），**侧栏随主题切换**（浅色白 / 深色深，推翻 Q19 固定深色侧栏）；品牌区 = 渐变 logo 标记 + 产品名；导航项 = SVG 线性图标 + 文字，激活态左侧指示条；底部运行状态点；组件（按钮/表格/表单/弹窗/徽章/开关/toast）统一现代风格（圆角、层次阴影、hover/active 交互态）。**主题三态切换（Q21-②）**：`index.html` 顶栏主题按钮 + 弹出菜单（浅色/深色/跟随系统，全 SVG 图标）；`main.js` 主题模块——`localStorage.mg-theme`（light|dark|system，默认 system）持久化，`html[data-theme]` 由 `matchMedia('(prefers-color-scheme: dark)')` 解析，系统配色变化实时联动（`change` 监听）；**纯前端，无后端接口/配置变更**。数据看板 Chart.js 网格/刻度/图例颜色取主题令牌（`--border`/`--text-faint`）随主题自适应。
- **静态资源禁缓存（Q19-① 根因修复 · 2026-09-05 加严）**：`main.py` 注册 `_StaticNoCacheMiddleware`——对静态资源请求（HTML/JS/CSS，即 StaticFiles 挂载 `/` 的响应）统一加 `Cache-Control: no-store` 响应头（原 no-cache 协商 304；本地静态资源无缓存价值，no-store 不落盘，**杜绝浏览器缓存新旧混载的 ES 模块导致 import 失败——实测症状为静态框架在、JS 渲染的内容区永久空白**），界面改版即时可见；`index.html` 另有装载兜底（3s 未见 main.js 启动标记 → 内容区显示强制刷新指引）；**界面文件更新自动刷新**（2026-09-05）：main.js 启动时快照全部界面模块文本（main/api/components/base.css/七页），每 20s 重取比对，变化 → toast 提示 + 3s 后自动 `location.reload()`——根治「旧标签页长期不刷新，跑旧脚本与新文件混搭」的排障泥潭；`/admin/api/*` 与 `/v1/*` API 响应不受影响。
- **无令牌门**：管理界面免鉴权直访（Q18-①），打开即用，无登录/令牌输入步骤。
- 技术形态：无构建静态资源（原生 ES Modules + 手写 CSS + vendored Chart.js），由 FastAPI StaticFiles 挂载 `/`。
- 全部操作走 `/admin/api/*`，最终读写两个明文 YAML（界面与文件双向一致，改文件也生效——热重载保证）。

### 4.10 系统运行控制与单实例锁（Q17/D2-D4，PRD FR-12）

#### ① main.py Server 化重构与启动序列

- M1 形态为 `uvicorn.run(app, ...)` 直启（`model_gateway/main.py`）——该形态拿不到 Server 句柄，无法从 admin 端点触发停机。v1.1 重构：`uvicorn.Config(app, host, port, ...) + uvicorn.Server(config)` 实例化后以 `server.serve()` 运行；**Server 实例挂 `app.state`**，供 system 端点设置 `should_exit`。
- **启动序列（严格顺序）**：加载配置（config.yaml + model-enums.yaml 校验通过，失败即退出）→ **获取单实例锁**（检测/清理/登记，见 ③④；获取失败按 ④ 退出，不进入服务启动）→ 绑定端口启动服务（`serve()`）；端口绑定失败按 ⑤ 兜底报错退出。

#### ② stop / restart 端点（免鉴权，Q18-①）

- `POST /admin/api/system/stop`：**优雅停机**——端点先返回受理确认（如 `{"status": "stopping"}`），随后设置 `server.should_exit = True`；uvicorn 优雅停机（**在途请求收尾后**才退出事件循环）→ 进程退出前经 atexit 释放单实例锁。
- `POST /admin/api/system/restart`：与 stop 相同的优雅停机 + 锁释放完成后，`os.execv(sys.executable, [sys.executable, "-m", "model_gateway.main", ...原 argv])` **进程映像替换**——**PID 不变、同端口重绑、配置重读、锁重新登记**（新映像重走启动序列，锁检测命中 pid==自身 → 覆盖重写，见 ④）；execv 前后环境变量 / TTY / 文件描述符天然继承（D3：无孤儿进程）。
- **设计纪律**：execv 必须在 `serve()` 返回（在途请求全部收尾）**之后**执行——顺序固定为「返回确认响应 → should_exit → serve() 返回 → 释放锁 → execv」。
- **execv 失败兜底**：捕获 `OSError` → 明确报错退出（此时锁已释放，可经 `启动网关.command` 重新拉起），不静默残留。

#### ③ gateway.lock 文件结构与获取/释放

- 路径 `data/gateway.lock`，**明文 JSON**（可查可删，D2）：`{"pid": <进程号>, "port": <监听端口>, "base_url": "http://127.0.0.1:<port>/", "started_at": "<ISO8601 启动时间>"}`。
- 获取：按 ④ 决策树判定通过后**覆盖重写**（tempfile + `os.replace` 原子写），再继续启动。
- 释放：**atexit 钩子 + SIGTERM/SIGINT 信号处理**统一收尾路径——退出前校验锁内 `pid == 自身` 才删除（幂等，防误删后续实例的锁）；stop / restart / Ctrl+C / kill 信号均走此路径。

#### ④ 启动检测决策树（含陈旧锁清理与退出码 3）

```
读 data/gateway.lock
├─ 锁不存在                         → 写锁 → 继续启动
├─ 读取/解析失败（含半行 JSON 损坏）  → 按陈旧锁处理：清理 → 写锁 → 继续启动
├─ 解析成功，按 pid 分支：
│   ├─ pid == 自身（execv 重启场景）  → 覆盖重写锁 → 继续启动
│   ├─ pid 存活（os.kill(pid, 0) 未抛 ProcessLookupError，且非自身）
│   │    → 终端打印「已有实例运行中：后台地址 http://127.0.0.1:<port>/（PID、启动时间）」
│   │    → 退出码 3 退出（不启动新实例、不换端口、不询问；交互/非交互一致，D4）
│   └─ pid 已死（os.kill 抛 ProcessLookupError → 陈旧锁，异常退出残留）
│        → 自动清理 → 写锁 → 继续启动
```

- **PID 复用误判**（陈旧 pid 被系统分配给无关进程）：按「pid 存活即拒绝启动」保守处理——宁可拒绝不猜测；锁为明文可查可删（D2），用户确认后可手动清理再启动。
- **竞态（TOCTOU）**：读 → 判 → 写在启动早期同段完成，双进程同时冷启动的窗口极小；即使漏检，⑤ 端口绑定兜底保证不出现双实例同端口服务。

#### ⑤ 端口占用兜底

锁检测遗漏（极端竞态）时，第二个实例在 uvicorn 绑定端口阶段失败（端口已被占用）→ **明确报错退出**（错误信息提示已有实例 / 端口占用），不静默换端口。

#### ⑥ 启动网关.command（macOS 双击启动脚本，FR-12.2）

项目根 `启动网关.command`（`chmod +x`），流程：

1. `cd` 到脚本自身所在目录（= 项目根）；
2. 检测 `.venv/`：缺失 → 打印环境搭建指引且**窗口不关闭**（等待按键，防闪退）；
3. 存在 → **前台**执行 `python -m model_gateway.main`——日志直接可见、Ctrl+C 可停；
4. 网关因「已有实例」以**退出码 3** 退出时：窗口显示后台地址并**保持开启**（不重复启动，用户查看地址后自行关闭）；
5. 其它异常退出：窗口同样保持开启显示错误输出，便于排查。

验证用例（test-cases v1.1）：UT-28（锁检测纯逻辑五场景）、INT-42/43（stop/restart 端点）、INT-44/45（单实例互斥/陈旧锁清理）、E2E-17/18/19（界面启停、单实例、双击脚本）。

### 4.11 界面参考项目规范精修（Q22，PRD v1.9 §9-Q22）

> **纯前端改动**（`base.css` / `index.html` / `main.js` / 7 个页面 JS），无后端接口/配置变更；三态主题机制（§4.9 Q21-②）与静态资源禁缓存（§4.9 Q19-①）原样延续。视觉基准 = 用户指定参考项目 `/Users/w/Desktop/react-v16-cursor/整体前端代码`（`ConsolePage.tsx`，主参考页 `/console/skills`，dev server `http://localhost:5173`）。

#### ① 黑主色令牌（推翻 Q21 indigo 主色）

- 参考项目 active 导航/主按钮/开关 on 统一黑主色（`bg-black`、hover `#171717`）——`base.css` 主色令牌整体换黑：浅色主题 `--brand:#171b22`（hover `--brand-strong:#0f1216`），深色主题**反转为白** `--brand:#e8eaee`（`--on-brand` 文本令牌同步反转 `#17191d`），保证按钮/激活态文字对比度。
- 生效面：主按钮（`btn-primary`）/ 激活导航项 / 开关 on / 品牌方块 / `--ring` focus 环 / 分段 tab 激活态全量走 `--brand` 令牌，双主题自动适配。

#### ② 参考规范组件层

- **卡片**：无边框 + 软阴影（`--shadow-card: 0 10px 24px rgba(15,23,42,.035)`，圆角 13px）；深色主题阴影不可见 → 补 1px 深边框（`--card-border` 令牌）。
- **软边框体系**：`#eef1f3` 用于表格行分隔/控件描边/hover 底 `#f6f7f8`；文本三级 `#171b22/#59616a/#a3abb3`；状态绿点 `#16d76d`。
- **分段式 tab**：参考项目 SegmentedTabs——灰底容器（`--seg-bg`）rounded-11 + 活动段白底浮起带小阴影；**纯 CSS 重塑**（`.tabs/.tab` 样式重写），`components.js` 类名契约不变、零改动。
- **表格/表单**：表头无底色 + 行分隔线；输入框底 `#fafcfc` + focus 边框转深；徽章 6px 圆角 + 参考色板语义色；开关 40×24 黑 on。
- **指标卡图标块**：38px 圆角块 + lucide 线性 SVG + 四色调（mi-blue/green/orange/purple 淡底彩字）+ 右侧信息列横排；总览 4 卡 / 数据看板 7 卡落地。

#### ③ 分组侧栏 + 两行顶栏

- **侧栏分组导航**：四分组（概览/资源配置/运行观测/系统设置），组标题 12px bold 灰；激活项黑底白字 + 尾部绿点 `#16d76d`；品牌区加副标题 "LLM Gateway Console"。
- **两行顶栏**：上行面包屑 `Console › 分组`（12px 灰）+ 下行页标题（15px extrabold）——页标题**由路由统一注入**：`main.js` 新增 `PAGE_META`（title/group），`route()` 写入面包屑与 `document.title`；内容区 7 页 `page-head` 移除重复标题（降为纯操作行）。
- Chart.js 网格/刻度/图例继续取主题令牌（Q21 机制），换黑主色后曲线色自动适配新令牌。

#### 验证

- test-cases v1.6 E2E-20 追加⑩项；实测证据 `docs/changes/e2e-records/E2E-20260905-Q22-refined-ui.md`（pytest 187 passed 持平 + headless Chrome CDP 七页双主题截图 11 张存档 `q22-screenshots/`）。

---

## 5. 调度精确语义（核心状态机）

> 本节把 PRD FR-3.4/3.5/3.7/3.8 的语义精确化为**统一判定规则**；默认 m=3、y=2（PRD Q11 定值）。

### 5.1 记号
- `m`：单请求单资源**重试**上限（默认 3）→ 同一资源上最多尝试 `m+1` 次（1 次首发 + m 次重试）。
- `y`：资源连续失败判定阈值（默认 2）。
- `C(R)`：资源 R 的连续失败计数（**跨请求累计，含请求内每次尝试失败**；成功清零）。

### 5.2 统一判定规则（每次上游尝试结束后按序执行）

```
async def execute(ir_req, system_model):
    deadline = now() + cfg.request_total_budget       # ★ 请求总预算（§5.5，默认 300s，可配）
    exhausted_reason = NONE
    tried = ∅
    while (resource = pick_for_request(pool, exclude=tried)) is not None:
        # ★ 选路规则（§5.3 并发溢出生效集，2026-09-03 定论）：
        #   生效集 = 池中 top-x 可用资源（跳过 cooldown/disabled/invalid，成员被
        #   移出时由待命资源补位）；集内取「在途请求最少」者承接本次请求，平局取
        #   优先级高者 → 低负载集中打最高优先级，并发时溢出到生效集内下一资源；
        #   故障切换的目标资源同样按此规则选取（排除本请求已尝试过的资源）
        m, y = cfg.retry_per_request, cfg.fail_threshold   # ★ 全局参数（Q18-④：不支持按模型覆盖）
        tried.add(resource)
        for attempt in 1..m+1:
            # ★ 每次尝试边界：先探测断连（§4.6 延迟提交窗口）再检查预算
            if await client_disconnected():
                cancel_upstream(); mark aborted; return   # 中止整链：不计失败不重试

            if now() > deadline:
                exhausted_reason = "BUDGET_EXHAUSTED"
                break                                     # 总预算耗尽 → 跳出走兜底
            #
            # ★ CancelledError 专用捕获（设计纪律：绝不能与上游失败混为一谈）
            #   - asyncio.CancelledError = 客户端主动取消（响应task被cancel）→ aborted
            #   - httpx.TimeoutException/ConnectError 等 = 厂商端异常 → RETRYABLE
            #   - HTTP 408 canceled_error（商汤） → classify 归 CANCELED → aborted 透传
            try:
                outcome = await call_upstream(resource, ir_req,
                                 timeout=cfg.attempt_timeout)  # 单次尝试超时（§5.5）
            except asyncio.CancelledError as ce:
                cancel_upstream()         # 保险：取消已注册的上游task
                mark aborted
                raise ce                  # ★ 关键纪律：必须 re-raise，严禁吞！
                                                 #   （调用方捕获后不进入失败分类）
            except Exception as e:
                outcome = Failure(error=e)   # httpx 异常 → 进入 classify

            if outcome.ok:
                C(R) = 0                                # 成功清零
                return outcome                          # ★ 工具端拿到结果
            cls = classify(outcome.error)

            if cls == CANCELED:                         # 厂商 408 canceled_error
                mark aborted                            # 不计失败不切换；
                return passthrough(outcome.error)       #   错误**透传调用方**（区分于客户端取消）

            if cls == BAD_REQUEST:                      # 参数类 4xx
                return passthrough_error(outcome.error)  # ★ 原样透传（换资源同样失败）

            if cls == AUTH:                             # 401/凭据 403
                disable(R); emit_switch_event(reason="AUTH"); break   # 停用+告警 → 切下一资源

            if cls == NOT_FOUND:                        # 404
                mark_invalid(R); emit_switch_event(reason="NOT_FOUND"); break  # 无效+告警 → 切下一资源

            if cls == QUOTA:                            # 429/配额
                ok = backoff_retry(R, ir_req, times=cfg.quota_retry,   # 默认 2
                                   delay=指数退避)       # 1s,2s…（可配；sleep 分段可取消）
                if ok: C(R)=0; return ok
                bench(R); emit_switch_event(reason="QUOTA"); break   # 移出+冷却 → 切下一资源

            # cls == RETRYABLE（网络/超时/5xx）
            C(R) += 1                                    # ★ 计入连续失败（跨请求）
            if C(R) >= y:
                bench(R); emit_switch_event(reason="RETRYABLE_Y")
                break                                     # ★ 命中 y：移出冷却 + 当次请求立即切下一资源
            if attempt == m+1:
                exhausted_reason = "RETRY_EXHAUSTED"
                break                                    # 重试额度耗尽（C 仍 < y，即 y > m+1 场景）
                                                          #   → 切下一资源，R 不冷却
            await sleep(cfg.retry_backoff)               # 默认 0 = 立即重试
        if exhausted_reason == "BUDGET_EXHAUSTED": break  # 预算耗尽时跳过后续资源
    return unified_no_resource_error(system_model,      # ★ 全部不可用/预算耗尽兜底
                                     reason=exhausted_reason,
                                     attempts_summary=...)   # 含「预算耗尽」标注+已尝试资源
                                                          #   （唯一向工具端报错的出口之一）
```

- `bench(R)`：移出生效集 → `cooldown_until = now + cooldown_seconds`（api 模式默认 60s；plan 模式默认 18000s 对齐滚动窗口；均可配）→ 到期懒恢复归位。
- 请求内在 R 上的失败**同时**计入 C(R)（PRD FR-3.4）；C(R) 命中 y 时**当次请求立即切换**（不再消耗 R 上剩余重试额度）——「命中条件即更换资源」（PRD Q11 用户原话口径）。
- **默认参数下的实际行为（m=3, y=2）**：资源连续失败 2 次即冷却并切换——即「失败 1 次 → 原资源重试 1 次 → 仍失败 → 切资源」。m 的余量在 y > m+1 或 QUOTA 退避等场景生效。此 m/y 生效顺序（**y 先判定**）已于 2026-09-03 经用户确认定论（PRD v1.1 §9-Q14），原待评审确认点 1 撤销。
- 429 退避重试默认 2 次、指数间隔（基值 1s，可配 `quota_backoff_base_seconds`）；plan 模式 429 冷却默认对齐滚动窗口（18000s）。
- 并发请求间通过 `asyncio.Lock` 串行化 C(R)/状态变更；同一资源可同时服务多个请求（厂商侧并发不管理，非目标）。

### 5.3 x（max_active_per_model）：并发溢出生效集（2026-09-03 重对齐定论）

> v0.2/v0.3 曾结论「x 仅展示性」——那是「顺序集中 + 补位 + 不中断」三条已确认决策联立的数学结果（路由恒等于「取最高优先级可用资源」，x 取任何值结果相同）。用户不认可该口径，于 2026-09-03 重新对齐，在四个候选（A 并发溢出 / B 生效集内轮询 / C 单请求切换深度上限 / D 维持热备窗口）中**选定 A 并发溢出**（PRD v1.1 §9-Q13）。

**选路规则（每个请求进入调度时执行，`pick_for_request`）**：
1. **生效集** = 池中 top-x **可用**资源（按优先级，跳过 cooldown/disabled/invalid；成员被移出时由池中下一待命资源**补位**，集合大小恒为 min(x, 可用数)）；
2. 生效集内取「**在途请求最少**」的资源承接本次请求；**平局取优先级高者**。

**行为效果**：
- **低负载（顺序请求）**：在途归零后，新请求总是回到最高优先级资源——与原「顺序集中调用」完全一致；
- **并发时（多工具同时调用）**：最高优先级资源在途未清零 → 溢出到生效集内下一资源——**任意时刻最多 x 个资源同时承接流量**（「最多同时生效 x 个资源」的准确落地）；
- **x=1 退化为纯顺序集中**；x 越大，并发吞吐上限越高；
- 故障切换/冷却/重试（m/y）机制不受影响：资源命中 y 被移出后由待命资源补位，生效集保持满员；**故障切换的目标资源也按同一选路规则选取**（排除本请求已尝试过的资源）。

**在途计数（in-flight，纯内存态）**：每资源维护计数器——请求开始在该资源上尝试时 +1，该次尝试结束（成功/失败/取消）时 -1；重启归零、不落盘。选路与 +1 在同一 asyncio 同步段内完成（单线程事件循环，天然无竞态）。

**与原确认决策的关系（诚实标注）**：低负载行为 = 原「顺序集中调用，不轮询」；并发行为 = 溢出分流——原表述「请求集中打到生效集中优先级最高的资源」在并发场景放宽为「集中打到生效集内在途最少的资源」。

### 5.4 切换续跑的流式边界

见 §6。非流式/图像：请求可整体重放，全规则适用（含跨多资源逐个尝试，直到成功或全部耗尽）。

### 5.5 超时与请求总预算（「不中断」与「不挂起」的边界，v0.2 新增）

PRD FR-3.5 要求「只要有可用资源不中断」，FR-3.9 要求「禁止无限挂起」——两者需要一个明确边界，否则资源池大时（如 10 资源 × 每资源多次尝试 + 退避）最坏耗时不可控：

| 参数 | 默认 | 语义 |
|---|---|---|
| `attempt_timeout_seconds`（承接 PRD §6 `request_timeout_seconds`） | **60**（终审由 120 调小；思考型模型首字节慢若被误杀，实测后调回即可） | **单次上游尝试**整体超时（connect + read + write 合并）；超时异常按 RETRYABLE 分类，正常参与同资源重试 / 切换续跑 |
| `request_total_budget_seconds` | **300**（终审由 600 调小） | **单请求总预算**：一次入站请求的全部资源尝试 + 重试 + 退避的总时长上限（**不管成功任务本身的执行时长**——流式输出开始后跑多久都行）；每次新尝试开始前检查，耗尽 → 跳出循环走「无可用资源」兜底（错误信息标注「预算耗尽」+ 已尝试资源与原因摘要） |

- 单次尝试超时 ≠ 请求失败：它只是 RETRYABLE 的一个失败样本（网络慢场景下换资源常有效）。
- 总预算同时是延迟提交窗口的等待上限（§6）：客户端在首帧前的最长无字节等待 ≤ 总预算。
- 两参数均为**全局参数**（Q18-④：不支持按模型/资源覆盖），可按需调整（调大 = 更坚持不中断；调小 = 更快兜底）；默认值已经终审确认（§11-4/6，PRD v1.3 §9-Q16）。

---

## 6. 流式边界与中途失败实现口径（PRD FR-3.6 的精确化）

**判定点 = 「首帧转发」（向客户端发出第一个内容字节）**，严于「首 token 接收」：

| 阶段 | 状态 | 失败处理 |
|---|---|---|
| 响应头未提交 + 未转发任何内容 | **可安全重放窗口** | 完整适用 §5 规则：重试 ≤ m → 切资源续跑 → …… 工具端**零感知**（只观察到正常延迟） |
| 已转发部分内容 | **不可重放**（重发导致内容重复错乱） | ① **不自动重放**；② ErrorClassifier 分类：**可重试类**（网络断/超时/5xx）→ 以标准 SSE error 帧终止流并标注 `retryable`（支持自动重试的工具端可自行重新发起整请求）；**不可重试/不确定类** → 厂商原始错误信息作为 error 帧**原封透传**（已输出内容已在客户端，不吞、不修饰），由用户判断是否重新触发；③ 两种情况均计入 C(R)（中途失败也是失败） |

- 「首帧转发」前网关仅缓冲初始事件（如 role chunk），不向客户端发送任何字节——由此「首 token 前」与「首转发前」统一，实现无歧义。
- 请求幂等性依据：POST chat/completions 无服务端副作用，重放安全。
- 延迟提交的代价：重试/切换期间客户端无字节到达（工具端自身超时需容许；**请求总预算兜底**，见 §5.5——首帧前最长等待 ≤ 总预算，不会无限挂起）。

---

## 7. 代码目录结构

```
Model-Gateway/
├── AGENTS.md
├── pyproject.toml              # 包元数据 + 依赖 + pytest 配置
├── 启动网关.command             # macOS 双击启动脚本（§4.10-⑥）
├── .cursor/                    # rules / memory（已有）
├── docs/specs/                 # prd.md · tech-design.md · test-cases.md（真相源）
├── model_gateway/
│   ├── __init__.py
│   ├── main.py                 # 入口：装配 + uvicorn Server 启动（单实例锁/优雅停机/自重启，§4.10）
│   ├── api/                    # 入站层
│   │   ├── auth.py             # /v1/* 访问令牌中间件（admin 免鉴权，Q18-①）
│   │   ├── openai_compat.py    # /v1/models · /v1/chat/completions · /v1/images/generations
│   │   ├── anthropic.py        # /v1/messages
│   │   └── admin.py            # 管理 API（CRUD + 统计/日志查询 + 健康测试；ID 自动生成与脱敏还原）
│   ├── core/
│   │   ├── ir.py               # 内部标准格式（pydantic）
│   │   ├── scheduler.py        # §5 调度状态机
│   │   ├── resources.py        # 资源池/生效集/冷却/计数（懒恢复）
│   │   ├── errors.py           # 错误分类器（FR-3.13 代码化）
│   │   └── cancel.py            # 取消注册表与透传
│   ├── adapters/
│   │   ├── base.py             # 适配器接口
│   │   ├── openai_out.py       # OpenAI 兼容出站（商汤首发）
│   │   ├── anthropic_out.py    # P1
│   │   └── gemini_out.py       # P2
│   ├── config/
│   │   ├── loader.py           # 加载/校验/热重载/原子写
│   │   ├── schemas.py          # pydantic 配置模型（PRD §6 schema 落地）
│   │   └── presets.py          # 厂商预设注册表（内置常量清单，§4.7）
│   ├── enums/
│   │   └── matcher.py          # 统一名自动匹配（精确→别名→规范化，置信度）
│   ├── stats/
│   │   ├── events.py           # JSONL 流水
│   │   └── aggregate.py        # 日聚合 + 看板查询
│   ├── web/
│   │   └── static/             # 管理界面（无构建；vendored chart.js/）
│   │       ├── index.html      # 七页单页骨架（hash 路由）
│   │       └── js/pages/       # dashboard / resources / models / apiaccess / stats / logs / settings
│   └── logsetup.py             # 脱敏日志
├── tests/
│   ├── unit/                   # 调度/分类/匹配/校验纯逻辑
│   ├── integration/            # 假厂商后端（可编程错误序列）
│   └── conftest.py
├── scripts/
│   └── sensenova_probe.py      # M1 商汤双端点实测脚本（§10.2）
└── data/                       # 运行时数据（.gitignore；config.yaml 由用户创建/界面生成）
```

---

## 8. 关键技术决策与风险

| # | 决策/风险 | 处置 |
|---|---|---|
| 1 | **asyncio 取消语义陷阱**：客户端断连的 `CancelledError` 若被通用 `except Exception` 捕获，会误判为上游失败（误计 C、误切换） | 取消路径专用处理 + 必须 re-raise；单测/集测强制覆盖（INT-09）；评审时重点检查每个 `except` 块 |
| 2 | **超时与取消混淆**：httpx 超时异常 ≠ 取消 | 分类器区分 `httpx.TimeoutException`（RETRYABLE）与 `CancelledError`（CANCELED） |
| 3 | **配置文件崩溃损坏** | 全部写入走 tempfile + `os.replace` 原子替换（同目录，保证同文件系统） |
| 4 | **热重载与在途请求竞态** | 请求绑定配置快照；资源状态（C/冷却）独立于配置快照，按资源 ID 关联 |
| 5 | **流式重放边界实现歧义** | 「首帧转发」严格定义（§6）；初始事件缓冲后才提交 |
| 6 | **m/y 生效顺序** | 统一规则见 §5.2；**y 先判定**（2026-09-03 用户确认，原 §11-1 落定） |
| 7 | **商汤 Key 体系未知** | 不猜测：M1 首项双端点实测定论（§10.2）；两种预设内置，切换零成本 |
| 8 | **纯本地前端资源** | 禁 CDN；Chart.js vendored 进仓库（MIT） |
| 9 | **单 worker 并发能力** | asyncio IO 密集场景足够；网关自身并发上限可配（保护本机，FR-4.2）；不做多进程 |
| 10 | **厂商流式思考字段差异**（商汤 DeepSeek V4 Pro `thinking_content`） | 出站适配器归一化为 `reasoning_delta`；透传原则保证多轮回传完整 |
| 11 | **延迟提交窗口断连检测**（v0.2）：响应未开始时 ASGI 不主动推送断连事件，普通 endpoint 的 handler task 不会被自动 cancel | 每次尝试边界 `request.is_disconnected()` 主动探测（§4.6/§5.2 伪代码已含）；INT-24 实测验证 |
| 12 | **事件 JSONL 并发写交错断行**（v0.2） | 单写队列串行化（§4.8）；INT-20 断言行完整性验证 |
| 13 | **CancelledError 与失败混淆**（v0.3 新增）：通用 `except Exception` 捕获 CancelledError 会误判为上游失败（误计 C、误切换） | §5.2 伪代码专用 try/except + CancelledError re-raise；分类器明确区分 httpx 异常 vs CancelledError |
| 14 | **流式端点 HTTP 语义违规**（v0.3 新增）：先发 200 StreamingResponse header 再写 error body 会让工具端混淆 | §4.5 规定窗口耗尽直接 return JSONResponse（非 200），首内容确定到达时才构造 StreamingResponse(200) |
| 15 | **kimi-k3 图片 URL 不支持**（v0.3 新增，PRD FR-1.8 官方口径） | 出站适配器 URL→base64 自动下载转换（§4.2）；下载失败 RETRYABLE 处理 |
| 16 | **切换事件记录形态**（v0.3 新增，PRD FR-3-14 / FR-7-1）：Dashboard 「最近切换事件」需要独立可读数据源 | 独立 switch-events-YYYYMMDD.jsonl + /admin/api/overview 内存环形缓冲（§4.4/§4.8） |
| 17 | **日聚合文件模糊命名**（v0.3 新增）：`daily-YYYYMM.json` 月度文件 + 当日重写会导致重启/竞态 | 修正为按天单文件 `daily-YYYYMMDD.json`（§4.8），原子覆写当天文件，历史文件只读 |
| 18 | **并发溢出选路的在途竞态**（v0.4）：两请求同时选路可能都取同一资源而未溢出 | 选路与在途 +1 在同一 asyncio 同步段完成（单线程事件循环天然原子）；UT-22/INT-22 验证 |
| 19 | **推理参数合并歧义**（v0.5，Q15）：「未指定」与「显式关闭」混淆会把资源默认强加给显式关闭的请求；入站透传字段与出站注入字段重复注入 | IR 用 `None` 区分未指定/显式值；入站把 `reasoning_effort`/`thinking` 从透传字典提升为显式字段（防双重注入）；UT-23/INT-36/37 验证 |
| 20 | **execv 重启边界**（v1.1 新增，Q17）：映像替换时机不当会切断在途请求；环境变量/TTY 继承不确定；execv 失败进程死亡无提示 | execv 严格排在 `serve()` 返回（在途请求收尾）+ 释放锁之后（§4.10-② 设计纪律）；execv 前后环境/argv 原样传递（PID/TTY 天然保持，D3）；捕获 `OSError` 明确报错退出（锁已释放，可脚本重新拉起）；INT-43/E2E-17 实测 |
| 21 | **锁文件竞态与陈旧判定**（v1.1 新增）：TOCTOU（双进程同时判定无锁）、PID 复用误判（陈旧 pid 被新进程占用）、锁文件损坏（半行 JSON） | 读→判→写同段完成压缩竞态窗口；pid 存活即拒绝启动（保守，宁可误拒——锁明文可查可删，D2）；损坏 JSON 按陈旧锁清理重写；端口绑定失败兜底（§4.10-⑤）；UT-28 五场景 + INT-44/45 |
| 22 | **信号处理与 atexit 锁释放时序**（v1.1 新增）：SIGTERM/SIGINT、uvicorn 优雅停机与 atexit 锁释放顺序不当 → 锁残留（下次启动误拒）或误删后续实例的锁 | 统一收尾路径：信号 handler 只触发 `should_exit`（在途收尾），进程退出时 atexit 释放锁；释放前校验锁内 pid==自身（幂等）；INT-42/44 覆盖 |
| 23 | **三层配置结构迁移风险**（v1.2 新增，Q18-②）：providers→accounts→keys 扁平化为 resources[] 时，存量 data/config.yaml 不兼容（启动校验失败）+ 事件/统计的资源标识口径变化 | 提供**迁移脚本/逻辑**：启动或迁移时把三层结构压平为资源条目（厂商+Key+账号备注，ID 自动生成），模型映射三元组改为 resource 引用；资源标识统一为「资源名/厂商模型」展示口径；INT-48 + 浏览器 E2E 验证迁移后可用 |
| 24 | **管理端免鉴权暴露面**（v1.2 新增，Q18-①）：移除管理鉴权后，同网段任意进程可读写配置/停止网关 | 接受（用户定论：自用系统暂不考虑）——监听仅服务用户自己设备（宪法级），风险由局域网边界承担；文档诚实标注此取舍 |

---

## 9. 性能与稳定性基线（验收口径，实施阶段实测）

- 多工具并发混合场景（20 并发：流式+非流式+中途取消，持续 ≥ 60s）：无请求堆积、内存 RSS 稳定（增长 < 10%）。
- 取消透传延迟：客户端断连 → 上游取消发起 ≤ 1s（心跳周期内更早）。
- 调度开销：选路 + 分类纯内存操作，单请求网关自身开销目标 < 5ms（不含上游）。
- 数值验收标准以实测证据为准（PRD FR-4.3），不在文档预写结论。

---

## 10. 实施计划

### 10.1 M1 任务拆解（核心网关）

| # | 任务 | 依赖 |
|---|---|---|
| 1 | 脚手架：pyproject + 包结构 + 配置 schema（PRD §6 落地）+ 样例 config | - |
| 2 | **商汤双端点实测**（scripts/sensenova_probe.py，§10.2）→ 回填 PRD/预设 | 1 |
| 3 | 最小链路：openai_compat 入站（非流式）→ 调度（单资源直通）→ openai_out 出站 → 事件落盘 | 1 |
| 4 | 调度完整化：错误分类器 + 重试 m + 切换续跑 + 冷却恢复 + y 计数 | 3 |
| 5 | 流式：SSE 透传 + 延迟提交 + 首帧边界 + 心跳 + 中途失败两分支 | 4 |
| 6 | 取消透传：CancelRegistry + 断连检测 + aborted 语义 | 5 |
| 7 | Anthropic /v1/messages 入站（IR 双向转换） | 4 |
| 8 | images 端点（调度/重试/切换/取消同样适用） | 4 |
| 9 | 访问令牌 + admin 骨架 + 热重载 | 1 |
| 10 | pytest 全量 + curl/工具实测（含 test-cases.md E2E 清单） | 全部 |

> **M1 状态（2026-09-03）**：上表任务 1-10 全部完成并**验收通过**——v0.1.0：141/141 pytest + 13/13 E2E（curl 可实测项；E2E-07 Trae 实配移交用户验收、E2E-14 按用例约定以 INT-04 兜底），证据 `docs/changes/e2e-records/E2E-20260903-summary.md`；商汤端点定论 = 端点 A `token.sensenova.cn/v1`（E2E-01）。

M2（管理界面）**进行中**（Q17 五项调整已实施并留证；**Q18 五项修正已实施**：184/184 pytest，浏览器 E2E 与验收待完成）/ M3（统计看板）/ M4（增强）按 PRD §8 里程碑执行。

> **模型自动发现（PRD FR-1.4 P0）的形态分阶段说明**：M1 形态 = 任务 2 的 `/models` 拉取（脚本输出清单）+ 手动填 config.yaml + 枚举池自动匹配（matcher）；产品级「拉取 → 自动匹配推荐 → 确认入库」向导随 **M2 资源管理界面**交付。P0 功能不悬空，形态分两步落地。

### 10.2 商汤双端点实测方案（M1 首项，Q12 定论路径）

`scripts/sensenova_probe.py`（Key 从环境变量 `SENSENOVA_API_KEY` 读取，不落盘、不入日志）：

1. 端点 A：`https://token.sensenova.cn/v1`（用户答复倾向的体系，**优先**）；
2. 端点 B：`https://api.sensenova.cn/compatible-mode/v2`；
3. 对每个端点执行：
   - `GET /models`（Bearer Key）→ 记录 HTTP 状态 + 模型清单（存 `docs/changes/sensenova-models-A|B.json`）；
   - 最小 `POST /chat/completions`（model 优先取清单中的 `deepseek-v4-flash`，否则清单首个；清单获取失败时回退官方文档已知模型名）→ 记录状态 + 响应摘要；
4. 输出判定表：**以最小 chat 调用为主判据**（HTTP 200 + 合法响应 = 端点可用）；`GET /models` 为模型清单辅助判据（若 /models 异常而 chat 成功：端点可用、清单另案处理，不据此判死端点）。401/403 = Key 不属于该体系。
5. 结论回填：PRD FR-1.8、config 预设默认值、decisions.md；模型清单差异同步枚举池预置条目。

> **实测定论（2026-09-03，E2E-01/02 已执行）**：端点 A `https://token.sensenova.cn/v1` **可用**（`GET /models` 200 返回 8 模型 + 最小 chat 200），定论为商汤首发接入端点；端点 B 结果存档 `docs/changes/sensenova-models-B.json`。证据：`docs/changes/e2e-records/E2E-20260903-summary.md`。

### 10.3 M2 任务拆解（管理界面 · 含五项调整 Q17 + 五项修正 Q18 + 两项修正 Q19）

> 对应 PRD v1.4 §9-Q17（D1-D5）/ v1.5 §9-Q18 / v1.6 §9-Q19、design-spec v0.3/v0.4/v0.5、test-cases v1.1/v1.2/v1.3 新增用例（UT-24~28 / INT-39~49 / E2E-16~20）。

| # | 任务 | 内容 | 依赖 | 对应用例 |
|---|---|---|---|---|
| 1 | **模型启用开关** | `models[].enabled` 配置/校验/解析拒绝（三端点 404 `model_disabled`）+ `/v1/models` 过滤 + 热重载即时生效 + 模型映射页开关 UI（§4.7） | M1 | UT-24/25、INT-39~41、E2E-16 |
| 2 | **厂商预设注册表** | `config/presets.py` 内置三条预设 + `GET /admin/api/presets` + 资源表单预设下拉数据驱动渲染（§4.7） | M1 | UT-26、INT-46 |
| 3 | **统计维度扩展** | 事件行冗余 provider/account + `by_provider`/`by_account` 聚合 + stats 可用维度键返回（§4.8） | M1 | UT-27、INT-47 |
| 4 | **系统运行控制端点** | main.py Server 化重构（§4.10-①）+ `POST /admin/api/system/stop` / `restart`（§4.10-②） | M1 | INT-42/43、E2E-17 |
| 5 | **单实例锁** | `data/gateway.lock` 检测/登记/释放 + 启动序列集成 + 端口占用兜底（§4.10-③④⑤） | 4 | UT-28、INT-44/45、E2E-18 |
| 6 | **双击启动脚本** | 项目根 `启动网关.command`（§4.10-⑥） | 5 | E2E-19 |
| 7 | **前端六页 + Q18 重整** | 数据看板（维度 tab 数据驱动）/ 请求日志（独立页双 tab 按需加载）/ 系统设置（含系统运行控制与全局调度参数）；Q18 重整：接入管理 → **资源管理表格页**（扁平资源 + ID 自动生成 + 账号备注）、模型映射**去调度参数**、新增 **API 接入页**（端点清单 + 多密钥管理）、设置页**去令牌管理与产品管理**、前端**去令牌门** | 1/2/3/4 | E2E-16/17 |
| 8 | **Q18 后端配套** | schemas.py 扁平资源模型 + admin.py 配置读写（ID 自动生成/脱敏还原，INT-48）+ auth.py 收窄至 /v1/* + 存量 config.yaml 迁移 | M1 | INT-48 |
| 9 | **Q19 视觉重设计 + 禁缓存** | 暗色侧边栏 + SVG 图标 + 组件现代化（§4.9 视觉方案）+ `_StaticNoCacheMiddleware` 静态资源 `Cache-Control: no-cache`（§4.9） | 7 | E2E-20 |
| 10 | **Q19 资源导向映射** | 资源弹窗内配「厂商模型 → 系统统一模型」映射（可就地新建系统模型，`@new-*` 占位 id，§4.9/§4.7-④）+ 系统模型页重定位为总览微调 + admin.py 占位 id 解析与引用改写 | 8 | INT-49、E2E-20 |
| 11 | **M2 回归** | 全量 pytest + 界面/脚本 E2E（E2E-16~20） | 全部 | — |

---

## 11. 确认点记录（全部已落定 · 2026-09-03 终审）

> 2026-09-03：确认点 1/2（m/y 顺序、x 语义）与推理参数需求（PRD Q15）先行落定；**同日终审确认点 3-8 全部落定（PRD v1.3 §9-Q16），本文档升级 v1.0，M1 启动**。

1. **m/y 生效顺序** → **已落定（2026-09-03）：y 先判定**——资源连续失败达 y 即冷却 + 当次请求立即切换（每资源每请求实际尝试 y=2 次）；m 为同资源重试上限（重试耗尽同样切换）。写入 §5.2，PRD §9-Q14。
2. **x 的定位** → **已落定（2026-09-03）：并发溢出生效集**——x = 同时承接流量的资源数上限；生效集内取在途最少者（平局优先级高），低负载顺序集中、并发溢出。写入 §5.3，PRD §9-Q13。
3. **管理 API 鉴权** → **已落定（终审）：复用访问令牌 + `allow_admin` 标志**（方案 A）——管理界面登录输入持有该标志的令牌（§4.1）；不设独立管理密码。【**已被 Q18-① 推翻（2026-09-03）**：管理端整体免鉴权，allow_admin 移除——自用系统不考虑管理鉴权，PRD v1.5 §9-Q18】
4. **默认参数** → **已落定（终审）**：端口 8300、SSE 心跳 15s、事件流水保留 7 天、429 退避 2 次（1s/2s 起）、**单次尝试超时 60s（原方案 120s，终审调小；思考型模型首字节慢若被误杀，实测后调回即可）**、**请求总预算 300s（原方案 600s，终审调小）**、网关并发上限默认不限、冷却 api 60s / plan 18000s、重试间隔 0。全部可配。【「多数可按模型覆盖」**已被 Q18-④ 取消**：调度参数全局唯一一套，PRD v1.5 §9-Q18】
5. **响应头延迟提交** → **已落定（终审）：接受**——重试/切换期间客户端零字节到达（开头多等几秒），换首帧前无感续跑（§4.5/§6）。
6. **请求总预算语义** → **已落定（终审）：认可语义，默认值调小为 300s**——预算只管「失败重试切换」总时长，**不管成功任务本身的执行时长**（流式输出开始后跑多久都行）；耗尽即返回统一错误（防挂起，FR-3.9）（§5.5）。
7. **failed_precondition_error 默认策略** → **已落定（终审）：默认透传 + 配置可覆写**（M1 配置层、M2 界面）——错误体无法区分「引擎不可用/安全检查/编码失败」，默认 BAD_REQUEST 透传；M1 双端点实测后观察真实错误分布，一行配置即可切换为 RETRYABLE（§4.3）。
8. **图像 URL 有效期提示** → **已落定（终审）：三处齐上**——响应体 `_gw_note.url_valid_hours` + **响应头 `X-GW-URL-Valid-Hours`** + M2 界面模型详情页（§4.4）。

> **评审通过（2026-09-03 终审）：八项全部落定，本文档升级 v1.0，M1 实施（任务 1 脚手架 + 任务 2 商汤双端点实测）启动**；实施证据按 test-cases.md §6 口径留存。
