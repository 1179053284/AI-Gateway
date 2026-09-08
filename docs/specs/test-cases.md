# Model-Gateway 测试用例（test-cases）

> 版本：v1.8（2026-09-05 Q24 资源池设置改版同步——**① 更名「资源池设置」**（导航/PAGE_META/document.title）；**② 厂商归属分组**（修正 Q23-① 分组口径：按内置目录 vendor 字段分组，与接入商解耦，deepseek-v4-* 经商汤接入仍归 DeepSeek 卡；不在目录归「自定义」卡）；**③ 启停语义澄清**（= 网关对外该模型能否被调用）；**④ 删除按钮暂时隐藏**（SHOW_DELETE 常量）；**⑤ 模型属性卡**（内置目录只读：厂商/上下文/输出/图片·视频·音频/深度推理与档位）；**⑥ 参数配置卡**（SystemModel.params 新增字段；优先级 = 工具传参 > 网关设置 > 厂商内置，字段级注入仅 chat；官方默认作初始值）：新增 **UT-30~38 / INT-51~53**；**⑦ 添加模型入口**（厂商卡内从目录选型新建，官方默认自动带入，覆盖 Q19-②）；**⑧ 四厂商 2026 模型目录 15 条**（官网逐条取证，来源清单见证据文档）：E2E-20 追加第⑫项核验。v1.7 为 Q23 系统模型页厂商分组卡片改版同步——**① 厂商分组卡片版式**（用户图1 定版：左子侧栏厂商 group-card 按厂家分组 + 行 = 系统模型 ID + 启用状态点（纯指示），点击模型 → 右撑满配置区 = 现有配置 1:1 迁移，操作即保存 D3）；**② 配置参数范围定论：维持现状四类**（零新增字段，调度保持全局）：E2E-20 追加第⑪项核验；**纯前端无后端接口/配置变更**，无新增 UT/INT。v1.6 为 Q22 界面参考项目规范精修同步——**① 黑主色令牌**（active 态/主按钮/开关 on 统一近黑 `#171b22`，深色主题反转为白 `#e8eaee` + `--on-brand` 文本令牌；推翻 v1.5 indigo 主色）；**② 参考规范组件层**（无边框软阴影卡片、`#eef1f3` 软边框、分段式 tab（纯 CSS 重塑，类名契约不变）、表头无底色 + 行分隔、徽章 6px 圆角、指标卡 38px 图标块）；**③ 分组侧栏 + 两行顶栏**（侧栏四分组 + 顶栏面包屑 `Console › 分组` + 页标题由路由 `PAGE_META` 注入，7 页 page-head 去重）：E2E-20 追加第⑩项核验；**纯前端无后端接口/配置变更**，无新增 UT/INT。v1.5 为 Q21 界面视觉升级同步；v1.4 为 Q20 资源接入管理三项修正同步；v1.3 为 Q19 两项修正同步；v1.2 为 Q18 五项修正同步；v1.1 为五项调整同步（UT-24~28、INT-39~47、E2E-16~19）；v1.0 为技术终审定稿）
> 对应需求：PRD v1.11（2026-09-05 Q24 资源池设置改版）；对应设计：tech-design.md v1.6、design-spec.md v2.1
> 日期：2026-09-05
> 状态：**UT/INT 全量 199/199 通过（2026-09-05 Q24 改版后回归，含 UT-24~38 / INT-39~53）；E2E-20（Q18+Q19+Q20+Q21+Q22+Q23+Q24）已通过**（Q18 五项 5/5 见 `docs/changes/e2e-records/E2E-20260903-Q18-ui-overhaul.md`，Q19 两项 2/2 见 `docs/changes/e2e-records/E2E-20260903-Q19-visual-remap.md`，Q20 三项 3/3 见 `docs/changes/e2e-records/E2E-20260904-Q20-resource-mgmt.md`，Q21 两项 2/2 见 `docs/changes/e2e-records/E2E-20260904-Q21-theme.md`，Q22 三项 3/3 见 `docs/changes/e2e-records/E2E-20260905-Q22-refined-ui.md`，Q23 两项 2/2 见 `docs/changes/e2e-records/E2E-20260905-models-vendor-cards.md`，Q24 八项见 `docs/changes/e2e-records/E2E-20260905-Q24-resource-pool.md`）；E2E 其余：13 通过、E2E-07 用户侧待验（SHELL）、E2E-14 按约定以 INT-04 兜底、E2E-16~19 待执行——执行状态一律以证据为准（pytest 输出 / curl 记录 / 截图），**禁止无证据打 ✅**（铁律 2）

---

## 1. 测试策略

### 1.1 三层结构

| 层 | 对象 | 环境 | 依赖网络 |
|---|---|---|---|
| UT 单元测试 | 调度状态机、错误分类器、枚举匹配、配置校验（纯逻辑） | 本地进程内 | 否 |
| INT 集成测试 | 网关全链路 × **假厂商后端**（可编程错误注入） | 本地回环 | 否 |
| E2E 端到端实测 | 真实商汤 API + 真实 AI 工具 | 真实网络 | 是 |

### 1.2 假厂商后端（FakeVendor）

- 本地 ASGI 测试服务（随机端口），模拟 OpenAI 兼容厂商端点（chat completions 流式/非流式、images、models）。
- **可编程脚本注入**（按收到的请求序号返回）：指定 HTTP 状态码 / 错误体（含商汤错误 type）/ 流式中途断开（输出 N 个 chunk 后 abort）/ 延迟 / 429 序列。
- 记录收到的每个请求（供断言「取消透传后上游确实断开」「多轮工具调用字段完整性」等）。

### 1.3 证据形态约定（每用例执行后必须留存其一）

- UT/INT：pytest `-v` 输出（含用例名与结果）、失败时附完整 traceback。
- E2E：curl 命令 + 响应原文（Key 脱敏）/ 工具配置截图与运行截图 / 网关事件 JSONL 对应行 / `docs/changes/` 下的实测记录文件。
- 执行状态跟踪矩阵：本文档 §6 维护，`未执行 / 通过 / 失败 / SHELL(阻塞)` 四态。

---

## 2. 单元测试（UT，纯逻辑）

| ID | 模块 | 用例 | 前置 | 预期 | 对应需求 |
|---|---|---|---|---|---|
| UT-01 | errors | 商汤错误码表 7 类分类：400 `invalid_request_error` / 400 `failed_precondition_error` / 403 `permission_denied_error` / 404 `not_found_error` / 408 `canceled_error` / 429 `quota_exceeded_error` / 500 `internal_server_error` | 构造各错误体 | 分别 → BAD_REQUEST / BAD_REQUEST / BAD_REQUEST(语言类透传) / NOT_FOUND / CANCELED / QUOTA / RETRYABLE | FR-1.8 |
| UT-02 | errors | 通用 HTTP 映射：网络异常/读超时→RETRYABLE；401→AUTH；其余 4xx→BAD_REQUEST | — | 分类正确 | FR-3.13 |
| UT-03 | scheduler | 默认 m=3,y=2：资源 A 连续 2 次失败 → A 进冷却、当次请求切 B | 单资源池 [A,B] | 第 2 次失败后立即切 B；A cooldown_until ≈ now+60s | FR-3.4/3.7/tech §5.2 |
| UT-04 | scheduler | y=5,m=2（y>m+1 场景）：A 上尝试 m+1=3 次后切 B，A 未冷却 | 配置覆盖 | 切换发生在第 3 次失败后；A 状态仍 active | tech §5.2 |
| UT-05 | scheduler | 成功清零：A 失败 1 次（C=1）→ 成功 → C=0；再失败 1 次（C=1）不触发冷却 | — | C 计数正确，A 未冷却 | FR-3.7 |
| UT-06 | scheduler | QUOTA 路径：429×(2+1) 次（退避重试 2 次耗尽）→ A 移出冷却 + 当次切 B；plan 模式资源冷却 18000s / api 模式变体冷却 60s | plan 与 api 模式资源各一 | 冷却时长按模式取对应默认值 | FR-3.8 |
| UT-07 | scheduler | AUTH：401 → 资源 disabled（不重试、不计 C）+ 告警事件 + 切下一资源 | — | 状态与事件断言 | FR-3.13 |
| UT-08 | scheduler | NOT_FOUND：404 → invalid 标记 + 告警 + 切换 | — | 同上 | FR-3.13 |
| UT-09 | scheduler | 全部资源不可用兜底：池内全部冷却 → 返回统一「无可用资源」错误（OpenAI error 格式） | — | 错误体含系统模型名与原因摘要；不挂起 | FR-3.9 |
| UT-10 | scheduler | 冷却懒恢复：A 冷却到期后，下一请求选路跳过 B 直接回 A（原优先级归位） | 时钟 mock | 选路结果 = A | FR-3.10 |
| UT-11 | scheduler | 请求内重试与 C 跨请求累计：请求 1 在 A 上失败 1 次成功（C=1，retry_count=1）；请求 2 在 A 上失败 1 次 → C=2 命中 y → A 冷却 | — | C 累计语义正确 | FR-3.4 |
| UT-12 | enums | 统一名匹配：精确命中 / 别名命中（`sensenova-6.7-flash-lite`→6.8）/ 规范化（忽略前缀/日期后缀/大小写，如 `deepseek-v4-flash-0731`）/ 无命中给出候选与置信度 | 预置枚举池 | 匹配结果与置信度符合预期；手动修正可沉淀 | FR-1.4 |
| UT-13 | config | 校验（Q18-②④ 语义重写）：模型映射引用不存在的资源 id → 拒绝并指明位置；x=0/y=0/m=-1 → 拒绝；`models[]` 含已废除的调度覆盖字段（max_active/fail_threshold 等，Q18-④）→ strict schema 拒绝 | 构造坏配置 | 校验错误信息逐条明确 | FR-8.3 |
| UT-14 | config | 原子写：写配置时模拟中断（monkeypatch os.replace 抛异常）→ 原文件内容不变 | — | 旧配置完整可读 | FR-8 / tech §8-3 |
| UT-15 | stats | 事件字段完整性 + 日聚合算术（次数/token/重试/切换按三维聚合正确） | 内存事件样本 | 聚合值与手算一致 | FR-6 |
| UT-16 | errors | `finish_reason: content_filter` → 正常结束不算失败 | 流事件样本 | 状态 success，不触发切换 | FR-3.13 |
| UT-17 | resources | **全局资源状态一致性**（Q18-② 同一资源 id 口径）：同一资源 id 同时映射系统模型 M1、M2；在 M1 的请求中该资源连续失败达 y → 全局冷却 → M2 选路**同步跳过**（同一次计数、同一次冷却） | 双池引用同一资源 | 两池视图一致（PRD Q11「厂商资源维度计数」语义） | PRD Q11 / tech §4.3 |
| UT-18 | config | **扁平资源引用完整性校验**（Q18-② 重写，原三层校验随结构废除）：① 模型映射条目引用不存在的资源 id；② 重复资源 id；③ 重复访问令牌 id；④ 系统模型 endpoint 字段填「audio」（非法值）；⑤ 资源缺 api_key | 构造坏配置 | 均被拒绝；错误信息分别指明具体 path（如 `models[0].resources[1].resource` / `resources[1].id`）与原因 | PRD FR-1.5 / FR-8.3 / tech §4.7 |
| UT-19 | errors | **error_rules 自定义覆写**：默认分类 400 `failed_precondition_error` → BAD_REQUEST；配置 `error_rules: [{http:400, type:"failed_precondition_error", class:"RETRYABLE"}]` → 覆写生效；类型优先级高于 HTTP 通用映射（400 其他 type 仍 BAD_REQUEST） | 内存错误规则样本 | 覆写前后分类结果符合预期；type 精确匹配优先 | PRD FR-1.8 / tech §4.3 |
| UT-20 | enums | **别名与原生 model id 匹配**：枚举池 `deepseek-v4-flash` 有别名 `deepseek-v4-flash-0731`，`claude-sonnet-4` 有别名 `claude-sonnet-4-20250514`（Anthropic 原生）。解析：① 别名命中（含规范化忽略大小写）② 未命中给出置信度候选（UT-12 已有） | 预置枚举池 | 别名可跨协议族命中；未命中不 404 而给出候选；手动修正可沉淀 | PRD FR-1.4 / tech §4.2 |
| UT-21 | resources | **端点类型兼容性**：系统模型 S1(endpoint=chat)、S2(endpoint=images)。请求端点 chat→S2；images→S1；均判定为 endpoint 不匹配 → 明确 400 error（不触达上游） | 配置双模型 | 返回码 400；错误信息包含「请通过对应端点调用」提示 | PRD FR-5.1/5.3 / tech §4.2 |
| UT-22 | scheduler | **并发溢出选路纯逻辑**：池 [A,B,C,D]，x=2——① A/B 在途均 0 → 选 A（平局取优先级高）；② A 在途 1、B 在途 0 → 选 B（溢出）；③ A/B 在途均 1 → 选 A；④ A 冷却 → 生效集 {B,C}，选 B（补位生效）；⑤ x=1 → 恒选 A（退化为纯顺序集中）；⑥ 全部冷却 → 空集（无可用资源）；⑦ 选路失败重试目标：请求已尝试 {A} 且 A 未冷却 → 目标 ⊆ {B,C} 且排除 A | 内存构造池与在途计数 | 七个场景选路结果全部符合 §5.3 规则；选路与在途 +1 在同一同步段（无竞态） | PRD FR-3.2/3.3 / tech §5.3 |
| UT-23 | ir/adapters | **推理参数三级合并纯逻辑**（Q15）：① 请求 effort=high + 资源默认 effort=low → 出站 high；② 请求未指定 + 资源默认 low → 出站 low；③ 请求未指定 + 资源无默认 → 出站**不含**推理字段（厂商默认）；④ 请求显式 enabled=false + 资源默认 enabled=true → 出站 false（显式关闭优先）；⑤ 请求显式 enabled=true + 资源无 enabled 默认 → 出站 true；⑥ images 资源配置 reasoning 默认 → 校验警告并忽略 | 内存构造请求 IR 与资源配置 | 六个场景合并结果全部符合「请求级 > 资源级 > 不注入」优先级；「未指定」与「显式关闭」严格区分 | PRD FR-3.16 / Q15 / tech §4.2 |
| UT-24 | enums | **禁用模型解析拒绝**：请求 model 命中 enabled=false 的系统模型（① 系统模型名直接命中；② 经枚举池别名命中） | 枚举池含 enabled=false 模型及其登记别名 | 解析返回 model_disabled 拒绝语义（与「未命中」的候选建议明确区分），不进入选路；两种命中方式一致拒绝 | PRD FR-2.3 / FR-5.6 |
| UT-25 | config | **models[].enabled 校验与默认兼容**：① enabled 填非 bool 值（如字符串 "true" / 0 / 1）；② 旧配置无 enabled 字段 | 构造两份配置分别加载 | ① 拒绝并指明位置与类型错误；② 正常加载，该模型视为 enabled=true（旧配置向后兼容） | PRD FR-2.3 / FR-8.3 |
| UT-26 | presets | **预设注册表内置数据**：sensenova-api / sensenova-tokenplan / custom 三条字段完整性；未知计费口径降级 | 内置预设注册表 | 三条均含 id / 名称 / 接入模式 / 协议 / base_url / 计费口径 / 说明文案且值正确；计费口径未知的预设降级显示「—」不报错 | PRD FR-1.2 |
| UT-27 | stats | **聚合派生维度**：① 新事件行含 provider/account 冗余字段 → by_provider / by_account 聚合算术正确；② 历史事件行无该字段 → 兼容（空值归组） | 内存事件样本两批（新格式含冗余字段 / 历史旧格式无） | 两维聚合值与手算一致；旧格式行归入空值组、聚合不抛异常 | PRD FR-6.1 |
| UT-28 | lock | **单实例锁检测纯逻辑**（monkeypatch os.kill / 文件系统）：① 无锁文件 → 写入锁；② 锁 pid 存活且非自身 → 返回已有实例信息（后台地址 / PID / 启动时间）+ 退出码 3 语义（不启动新实例）；③ 陈旧锁（pid 已死）→ 清理后重写并正常启动；④ pid==自身（execv 重启场景）→ 覆盖重写继续启动；⑤ 锁文件损坏（半行 JSON）→ 按陈旧锁处理（清理重写） | tmp 目录构造五种锁状态（monkeypatch 模拟 pid 存活 / 已死 / 自身） | 五场景行为逐一符合；锁内容为明文 JSON {pid, port, base_url, started_at} | PRD FR-12.3 / tech-design v1.1 |
| UT-29 | resources | **资源开关 resources[].enabled**（Q18-②）：① enabled=false 资源 → 选路跳过（等效不可用）、状态视图显示停用；② enabled 填非 bool → 校验拒绝；③ 缺省 → 视为 true | 构造资源池含停用资源 | 停用资源不承接流量、不参与生效集；校验与默认兼容行为正确 | PRD FR-1.6 / tech §4.3 |

---

## 3. 集成测试（INT，假厂商后端）

> 通用前置：启动网关（随机端口）+ FakeVendor（随机端口）；config 指向 FakeVendor；资源池按用例构造。除非特别说明，m=3、y=2、冷却 60s。

| ID | 场景 | 步骤 | 预期 | 对应需求 |
|---|---|---|---|---|
| INT-01 | 非流式成功基线 | 客户端 POST chat（非流式） | 200 + 完整响应；事件 JSONL 一行（status=success，resource_attempts 明细、duration/token 记录） | FR-5.1 |
| INT-02 | 请求级重试无感 | FakeVendor 脚本：第 1 次 500，第 2 次成功 | 客户端收到正常 200；事件 retry_count=1、C(A)=1；无切换 | FR-3.4 |
| INT-03 | 切换续跑（核心） | FakeVendor：资源 A 恒 500，资源 B 成功 | 客户端收到 200（**无任何错误暴露**）；事件记录 A 尝试 2 次（C=2 冷却）+ 切换到 B；switch_count=1 | FR-3.5 |
| INT-04 | 429 退避路径 | FakeVendor：429 `quota_exceeded_error` ×3 | 退避重试 2 次耗尽 → A 冷却 + 当次切 B 成功；事件含退避明细 | FR-3.8 |
| INT-05 | 401 停用与告警 | FakeVendor：资源 A 恒 401 | A 立即 disabled（无重试）+ 告警事件 + 切 B；后续请求不再选 A | FR-3.13 |
| INT-06 | 404 无效标记 | FakeVendor：资源 A 恒 404 | A invalid + 告警 + 切 B | FR-3.13 |
| INT-07 | 400 原样透传 | FakeVendor：400 `invalid_request_error`（含错误体） | 客户端收到同状态码 + 原错误体；不切换、不重试；C 不变 | FR-3.13 |
| INT-08 | 取消透传（流式） | 客户端发起流式，收到 2 个 chunk 后断连 | FakeVendor **收到连接取消**（断言其请求 task 被 abort）；事件 status=aborted、不计 C、无切换；已产生 token 计入统计 | FR-3.11/3.12 |
| INT-09 | 取消语义保护（防误判） | 同 INT-08，检查调度器状态 | C(A)=0；A 无冷却——**验证 CancelledError 未被吞成失败** | tech §8-1 |
| INT-10 | 流式首帧前切换无感 | FakeVendor：资源 A 流式连接建立后**未输出内容即断开**，资源 B 正常 | 客户端收到完整流（无 error 帧、无重复内容）；事件记录 A 失败（RETRYABLE）+ 切换 | FR-3.6 |
| INT-11 | 流式中途失败·不可重试类 | FakeVendor：输出 2 个 chunk 后返回 400 `invalid_request_error`（或错误 type 未在分类表登记的未知错误） | 客户端已收 2 chunk + error 帧携带厂商原始错误信息（不修饰）；**不自动重放**（无内容重复）；C+1 | FR-3.6-b |
| INT-12 | 流式中途失败·可重试类 | FakeVendor：输出 2 chunk 后网络中断（RST） | error 帧标注 retryable 语义；不自动重放；C+1 | FR-3.6-a |
| INT-13 | 全部资源不可用 | 池 [A,B] 均恒 500 | 客户端收到统一 error（OpenAI 格式，「无可用资源」+ 原因摘要）；不挂起（总耗时 ≤ 请求总预算，tech §5.5） | FR-3.9 |
| INT-14 | 鉴权（Q18-① 修订） | ① /v1/* 无令牌 / 错令牌 / 多令牌（第二个生效）；② /admin/api/* 无任何凭据直访 | ① 前两者 401、第三个 200；② 200（管理端免鉴权，原「非 admin 403」分级已随 Q18-① 废除） | FR-10.2 / FR-10.1 |
| INT-15 | 图像生成 | POST images generations：A 恒 500 → 切 B 成功；b64 与 url 两种 response_format | 200 + 厂商响应透传；事件 images_count 记录；切换逻辑同样生效 | FR-5.3 |
| INT-16 | Anthropic 入站 | POST /v1/messages（非流式+流式），出站为 OpenAI 兼容 FakeVendor | 响应为合法 Anthropic 格式（content 块/stop_reason/usage 映射正确）；流式 event 语义正确 | FR-5.2 |
| INT-17 | 工具调用透传 | 含 tools 的多轮对话：第 1 轮返回 tool_calls → 第 2 轮回传 assistant(tool_calls)+tool 结果 | FakeVendor 断言收到的多轮消息**字段完整**（含 thinking/tool_calls 原样）；finish_reason=tool_calls 正确 | FR-5.1 / FR-1.8 协议注意点 |
| INT-18 | usage 统计 | ① 厂商返回 usage（include_usage）；② 厂商无 usage | ① usage_source=vendor 精确值；② usage_source=estimated 本地估算标注 | FR-5.8 |
| INT-19 | 热重载 | ① 文件新增资源 C → 新请求可选 C；② 写入坏配置 → 拒绝且旧配置继续生效；③ 管理界面保存触发同样路径 | 三场景行为正确；在途请求不受影响 | FR-8.2/8.3 |
| INT-20 | 并发混合稳定性 | 20 并发 × 60s：流式+非流式+随机中途取消混合，FakeVendor 间歇注入 500/429 | 全部请求完成或正常兜底；无堆积；进程 RSS 增长 <10%；无未注销的上游连接（FakeVendor 连接计数归零）；**事件文件行数 = 请求数且每行 JSON 可解析**（单写队列验证，tech §8-12） | FR-4 |
| INT-21 | SSE 心跳 | FakeVendor 流式静默 >15s 后输出 | 客户端在静默期收到 `: keep-alive` 注释帧 | FR-3.11 |
| INT-22 | **并发溢出生效集**（x=2，池 [A,B,C]，FakeVendor 每请求延迟 2s 制造在途重叠）：① 串行发 2 个请求；② 并发同时发 2 个；③ 并发同时发 3 个；④ 先单独触发 A 冷却（恒 500），再并发发 2 个；⑤ A 冷却到期恢复后串行发 1 个 | ① 都打 A（顺序集中）；② A、B 各承接 1（溢出生效）；③ 承接资源 ⊆ {A,B}（第 3 个回落到在途较少者，**永不溢出到 C**）；④ B、C 各 1（A 移出补位生效，管理 API 生效集视图 = {B,C}）；⑤ 回 A（在途归零回集中） | FR-3.2/3.3 / tech §5.3 |
| INT-23 | 入站未知模型 | POST chat，model=未定义的系统模型名 | 404 + OpenAI 标准 error 格式（含 model 名）；**不触达上游**（FakeVendor 断言零请求） | FR-5 / tech §3-3 |
| INT-24 | **延迟提交窗口内客户端断连** | FakeVendor：资源 A 首帧前持续延迟（如 10s）不输出；客户端 2s 后断连 | 整链中止：上游请求被取消（FakeVendor 断言）、事件 aborted、不计 C、无冷却、**不再继续重试/切换**；退避 sleep 场景同理可被及时打断 | tech §4.6 / §8-11 |
| INT-25 | **请求总预算耗尽** | 总预算设为 5s（覆盖配置）；池 [A,B] 恒 500 + 重试 backoff > 0 | 耗尽后返回统一「无可用资源（预算耗尽）」错误（含已尝试资源与原因摘要）；总耗时 ≈ 预算（不挂起）；事件记录已完成尝试明细 | tech §5.5 / FR-3.9 |
| INT-26 | 图像生成取消透传 | POST images，FakeVendor 生成延迟中客户端断连 | 上游请求取消；事件 aborted；无重试；不计失败 | FR-5.3 / FR-3.11 |
| INT-27 | Key 脱敏 | 正常调用数个请求后检查落盘 | 事件 JSONL 与运行日志中**无明文 Key**（`sk-****tail` 脱敏形式）；错误响应/告警事件同样脱敏 | FR-10.4 |
| INT-28 | Anthropic 入站取消 | POST /v1/messages 流式，输出中途客户端断连 | 同 INT-08 语义（上游取消、aborted、不计失败、不切换） | FR-5.2 / FR-3.11 |
| INT-29 | 切换事件独立记录 + admin 状态端点 | A 恒 500 触发冷却切 B；查 `/admin/api/overview` 与事件目录 | overview.resources 中 A.cooldown_remaining_ms > 0；overview.recent_switch_events 含 from A→to B 条目（字段保留，总览页不再渲染，供请求日志页与排查）；`data/usage/switch-events-YYYYMMDD.jsonl` 新增 1 行且字段完整（reason_cls=RETRYABLE_Y） | PRD FR-3.14 / FR-7-1 / tech §4.4 |
| INT-30 | **商汤流式思考字段归一化**：FakeVendor 模拟 V4 Pro→delta.thinking_content；GLM 风格→delta.reasoning_content | 两次流式请求分别命中两种资源 | 客户端收到的 SSE 流中 reasoning 内容**统一字段**（IR→入站时正确编码）；无字段丢失 | PRD FR-1.8 / tech §4.2 |
| INT-31 | kimi-k3 URL→base64 自动转换：资源模型标记 only_base64_image=true；请求带公网 image_url（FakeVendor 内部同时提供一个静态 HTTP 文件 URL 返回） | 多模态请求（含 image_url）→FakeVendor 断言收到的请求体**已转 base64**（无公网 URL） | 转换正确；模拟 URL 下载失败 → 该尝试按 RETRYABLE 计入（不切资源、重试消耗 m 额度）；m 耗尽兜底 | PRD FR-1.8 / tech §4.2 |
| INT-32 | 非流式 chat 取消透传：FakeVendor 非流式响应 5s 延迟；客户端 1s 后断连 | FakeVendor 请求被取消（连接关闭）；事件 aborted；C=0（不计失败） | PRD FR-3-11 / FR-3-12 |
| INT-33 | Anthropic 模型 ID 别名匹配：Claude Code 风格请求 `model=claude-sonnet-4-20250514`（枚举池已登记为某系统模型别名） | POST /v1/messages 命中该 model → 正常调度对应系统模型 | 不 404；调度器实际用的是别名映射的系统模型资源池；FakeVendor 断言收到正确厂商模型名 | PRD FR-5.2 / tech §4.2 |
| INT-34 | error_rules 覆写端到端：配置把 400 `failed_precondition_error` 覆写为 RETRYABLE；FakeVendor 注入该错误 + 后续成功 | 覆写生效：**首次错误后在同资源重试**（非 BAD_REQUEST 透传）；C(A)+1；最终成功或正常切换 | 与 UT-19 分层验证 | PRD FR-1.8 / tech §4.3 |
| INT-35 | 流式窗口耗尽返回非 200：池 [A,B] 首帧前恒失败（预算 5s 内全部耗尽）；注意**响应头状态码断言**（核心验证点） | 客户端收到状态码 **503/429（非 200）**，响应体为 OpenAI 标准 error 格式（含预算耗尽/切换摘要）；绝不是「200 + 内嵌 error」的 HTTP 违规形态 | tech §4.5 / §6 |
| INT-36 | **推理参数三级合并端到端**（Q15）：资源 A 配置 `reasoning: {enabled: true, effort: low}`；FakeVendor 记录收到的请求体。① 请求带 `reasoning_effort=high`；② 请求不带推理字段；③ 资源无默认、请求不带 | ① A 收到 `reasoning_effort=high`（**请求级优先**）；② A 收到 `reasoning_effort=low`（**资源级默认注入**）；③ A 收到的请求体**不含**任何推理字段（厂商默认）；请求体中推理字段**仅出现一次**（无双重注入） | PRD FR-3.16 / tech §4.2 |
| INT-37 | **切换续跑按资源重合并**（Q15 × FR-3.5 交互）：池 [A(默认 effort=low), B(默认 effort=high)]，请求**不带**推理字段；A 恒 500 触发 y 切换至 B | FakeVendor 断言：A 的每次尝试请求体含 `reasoning_effort=low`；切换后 B 的尝试请求体含 `reasoning_effort=high`——**换资源后按 B 的默认重新合并**（每次尝试独立构造出站请求） | PRD FR-3.16 / FR-3.5 |
| INT-38 | **图像 URL 有效期提示三处**（终审确认点 8）：资源映射 U1 Fast（枚举池 `response_format_url_hours: 1`）；POST images `response_format=url`；另配 U1.5 Lite 资源（24）作对照 | 响应体含 `_gw_note.url_valid_hours`（U1 Fast=1 / U1.5 Lite=24，按枚举池字段）；**响应头含 `X-GW-URL-Valid-Hours: 1`**（与响应体一致）；b64 响应（response_format=b64）不含该字段/响应头 | PRD FR-1.8 / tech §4.4 |
| INT-39 | **/v1/models 启用过滤** | 配置含 enabled=false 系统模型（其枚举池别名已登记）→ GET /v1/models；经热重载 / 管理界面保存开启后再次 GET | 禁用模型与其枚举池别名均不出现在返回列表；开启后恢复返回 | PRD FR-2.3 |
| INT-40 | **禁用模型三端点 404 model_disabled** | 对 enabled=false 模型分别 POST /v1/chat/completions、/v1/images/generations、/v1/messages（三端点各一，含经别名命中一例）；FakeVendor 记录收到请求数 | 三端点一致 HTTP 404 + 标准 error 格式 `code="model_disabled"`（message「模型已禁用，可在管理界面开启」）；FakeVendor 断言**零上游请求**；不计资源失败、C 不变、无切换事件 | PRD FR-2.3 / FR-5.6 |
| INT-41 | **模型开关热重载** | ① 修改 config.yaml 将在用模型置 enabled=false（或管理界面保存，同一路径）→ 发新请求；再置 true → 再请求；② 在途流式请求进行中切换开关 | 新请求即时按新状态生效（禁用即 404 model_disabled、开启即恢复调度）；在途请求不受影响、正常收尾 | PRD FR-2.3 / FR-8.2 |
| INT-42 | **system/stop 优雅停机**（Q18-① 免鉴权） | POST /admin/api/system/stop（无凭据），同时挂一个在途慢请求（FakeVendor 延迟响应） | 在途请求收尾后进程退出；`data/gateway.lock` 已释放 | PRD FR-12.1 / FR-12.3 |
| INT-43 | **system/restart 进程映像替换**（Q18-① 免鉴权） | ① POST /admin/api/system/restart（无凭据）；② 修改 config 后再次 restart | 优雅停机 + 释放锁后 os.execv：同端口 /health 恢复 200、**PID 不变**、锁重新登记（pid==自身覆盖重写）；配置修改经 restart 重读生效 | PRD FR-12.1 / FR-12.3 |
| INT-44 | **单实例互斥** | 子进程启动网关（持有 data/gateway.lock）→ 再启动第二个网关进程 | 第二进程打印「已有实例运行中：后台地址（PID、启动时间）」后以**退出码 3** 退出；不启动新实例、不换端口、不占用新端口、不交互询问；原实例不受影响持续服务 | PRD FR-12.3 |
| INT-45 | **陈旧锁自动清理** | kill -9 网关子进程（锁文件残留）→ 再次启动网关 | 判定 pid 已死 → 自动清理陈旧锁 → 正常启动并重写锁，服务可用 | PRD FR-12.3 |
| INT-46 | **presets 端点**（Q18-① 免鉴权） | 无凭据 GET /admin/api/presets | 200：返回内置三预设（sensenova-api / sensenova-tokenplan / custom，字段 id / 名称 / 接入模式 / 协议 / base_url / 计费口径 / 说明文案完整）；原「非 admin 403」分级已废除 | PRD FR-1.2 / FR-10.2 |
| INT-47 | **事件行 provider/account 冗余与聚合维度**（Q18-② 口径） | 正常请求若干次 → 检查事件 JSONL 行与 admin stats 端点 | 事件行含 provider / account 两字段且与配置快照一致（写入时按资源解析：provider = 预设资源取预设展示名（如「商汤按量 API」）、无预设资源取资源名称备注；account = 资源账号备注，未标注为空）；stats 含 by_provider / by_account 聚合值与可用维度键；历史无该字段事件行兼容不报错 | PRD FR-6.1 / FR-7.6 |
| INT-48 | **PUT /admin/api/config 自动生成与脱敏还原**（Q18-②/③） | UI 形态保存：① 新增资源（id 空）+ 新增访问密钥（id/value 空）→ PUT config；② 已存资源传回脱敏 Key 值（`sk-****tail` 形态）→ PUT config | ① 保存后资源 id 补齐 `res-xxxxxxxx`（8 位）、密钥 id `tok-xxxxxxxx` 与值 `mg-<32hex>` 均生成；② 脱敏值还原为明文（未变更不损坏），网关继续可用该资源正常调用 | PRD FR-8.3 / FR-10.2 |
| INT-49 | **占位资源 id 解析与映射引用改写**（Q19-②） | UI 形态保存：资源弹窗内即配映射——新增资源（id = `@new-1` 占位）+ 新系统模型（`models[].resources[].resource` 引用 `@new-1`）→ 一次 PUT config；随后按新系统模型名发起 chat 调用 | ① 保存后占位 id 替换为真实 `res-xxxxxxxx`（不以 `@` 开头）；② 映射条目 `resource` 同步改写为该真实 id（引用一致，校验通过）；③ 新模型即刻可调用（热重载生效，FakeVendor 返回承接资源内容） | PRD FR-8.3（Q19-②）/ FR-2.1 |
| INT-50 | **厂商名称自定义 + 账号必填 round-trip**（Q20-①/③） | ① 资源配置 `vendor` 自定义厂商名（预设存在时也不为空）→ PUT config 保存 → 发起 chat 调用；② GET config 回读 | ① 事件行 provider = 自定义厂商名（**压过预设展示名**，如「商汤按量 API」）；stats `by_provider` 桶 = 自定义厂商名；② round-trip 保存后 `resources[].vendor` 不丢失（GET 回读一致）；账号字段（`resources[].account`）随表单必填持久化 | PRD FR-1.2（Q20-①）/ FR-6.1（Q20-③） |

---

## 4. 端到端实测（E2E，真实商汤 + 真实工具）

> 前置：商汤 Key（环境变量，不落盘）；双端点实测（E2E-01）先行，其结论决定后续用例的接入实例配置。所有输出 Key 脱敏后留存 `docs/changes/e2e-records/`。

| ID | 场景 | 步骤 | 预期 / 判据 | 对应需求 |
|---|---|---|---|---|
| E2E-01 | **商汤双端点定论（M1 首项）** | 运行 `scripts/sensenova_probe.py`：端点 A `token.sensenova.cn/v1`（优先）、端点 B `api.sensenova.cn/compatible-mode/v2` 各执行 GET /models + 最小 chat | 判定表：可端点 = HTTP 200 + 合法响应（401/403 = Key 不属该体系）；结论回填 PRD FR-1.8 与预设 | §9-Q12 / tech §10.2 |
| E2E-02 | 模型清单实测 | 对定论端点 GET /models | 返回清单与官方文档模型总览比对，差异记录（如 sensenova-6.7 兼容路由别名）；回填枚举池预置条目 | FR-1.8 |
| E2E-03 | curl 非流式 | curl chat completions（deepseek-v4-flash / glm-5.2） | 200 + 合法响应；事件 JSONL 对应行完整 | FR-5.1 |
| E2E-04 | curl 流式 | 同上 + stream:true | SSE 逐 chunk 透传；思考模型（deepseek-v4-pro thinking）reasoning 内容字段正确呈现 | FR-5.1 / FR-1.8 |
| E2E-05 | curl 工具调用 | tools 请求（如天气查询 tool） | tool_calls 正确返回；多轮回传成功 | FR-5.1 |
| E2E-06 | curl 图像生成 | images generations（sensenova-u1-fast，b64 与 url 两种 response_format） | 200 + 图像数据/链接；url 有效性在文档标注有效期内验证（U1 Fast 1h）；**响应头 `X-GW-URL-Valid-Hours: 1` 与响应体 `_gw_note.url_valid_hours` 一致**（INT-38 真实链路） | FR-5.3 / FR-1.8 |
| E2E-07 | Trae 实配 | base_url=网关地址，model=系统模型名，api_key=访问令牌 | 对话/流式/补全正常工作 | FR-5.7 |
| E2E-08 | Claude Code 实配 | 走网关 Anthropic /v1/messages 端点 | 对话与流式正常 | FR-5.2 |
| E2E-09 | 中途停止（取消透传） | 工具内生成中途点停止 | 网关日志/事件显示 aborted；商汤侧请求确实终止（对比继续生成时 token 消耗） | FR-3.11/3.12 |
| E2E-10 | 失败切换实测 | 人为构造：资源 A 填错 Key（401）或坏 base_url（网络错）→ 正常资源 B | 工具端无感完成请求；事件记录切换明细 | FR-3.5 |
| E2E-11 | 局域网调用 | 另一设备（或本机用局域网 IP）走局域网地址 + 令牌 | 正常调用；无令牌被拒 | FR-10.1/10.2 |
| E2E-12 | /v1/models 列表 | GET /v1/models | 仅返回 enabled=true 的系统模型（OpenAI 格式） | FR-2.3 |
| E2E-13 | 重启可恢复 | 重启网关 | 配置/统计/聚合快照无损；冷却状态可重置（重启后资源重新可用，符合预期设计） | FR-非功能 |
| E2E-14（可选，视条件） | 真实 429 退避与切换 | 用低额度/已耗尽 Key 或短时高频请求触发商汤真实 429 `quota_exceeded_error` | 退避重试 → 冷却 → 切换续跑链路真实生效；事件完整留痕。PRD M1 验收列有「429 限流切换」，若实测期无法触发（Key 额度充足），以 INT-04 为准并在此注明原因 | FR-3.8 / PRD §8-M1 |
| E2E-15 | **真实推理参数生效**（Q15） | ① 请求级：deepseek-v4-flash 带 `reasoning_effort=low` 与 `=max` 各一次对比；② 资源级：资源配置默认 effort 后请求不带参数 | ① 响应含 `reasoning_content`（思考内容）且 low/max 两次的思考长度/耗时差异可感知（强度真实生效）；② 无参数请求的响应呈现资源默认强度的特征 | FR-3.16 / FR-1.8 |
| E2E-16 | 禁用模型对真实工具端不可见 | 管理界面禁用某系统模型 → 真实工具端（Trae；或 curl 模拟工具行为）刷新模型列表并请求该模型（含别名） | /v1/models 不含该模型及其别名；请求该模型 404 + `code="model_disabled"`；重新开启后恢复可见 / 可用 | PRD FR-2.3 |
| E2E-17 | 界面 / 接口启停实测 | ① 管理界面（或接口）触发 stop → 确认进程退出与锁释放 → 以启动脚本重新拉起；② 触发 restart | stop 后进程退出、锁释放、在途请求收尾；脚本拉起后 /health 200 恢复；restart 后同端口 /health 恢复 200 且 **PID 不变**（execv）、配置重读生效 | PRD FR-12.1 / FR-12.2 |
| E2E-18 | 单实例实测 | 网关已运行时再次执行启动命令（终端） | 终端输出「已有实例运行中：后台地址（PID、启动时间）」、进程退出码 3；原实例不受影响（持续 200 服务） | PRD FR-12.3 |
| E2E-19 | 双击启动脚本 | ① Finder 双击项目根 `启动网关.command`；② 网关已运行时再次双击 | ① 正常启动（.venv 缺失时窗口给出环境搭建指引、不关窗）；② 窗口显示后台地址并保持开启，不启动第二实例 | PRD FR-12.2 |
| E2E-20 | **Q18+Q19+Q20+Q21+Q22+Q23+Q24 界面浏览器实测** | 浏览器打开 `http://127.0.0.1:8300/` 逐页核验。**Q18 五项**：① 无令牌门直达总览；② 资源管理 = 表格（备注/厂商/账号/模式/Base URL/Key 脱敏/映射数/启用/操作），新增资源弹窗无 ID 输入项，保存后 id 自动生成；③ API 接入页 = 双地址 + 四端点 + curl 示例 + 密钥表格，新增密钥只填名称、保存后 `mg-` 值生成可复制；④ 系统模型页无任何调度参数（x/y/m/超时/冷却）；⑤ 系统设置无「接入产品」区，01 任务执行为全局参数唯一入口。**Q19 两项（追加核验）**：⑥ 视觉重设计生效——暗色侧边栏（品牌区 + SVG 图标导航 + 状态点）、响应头 `Cache-Control: no-cache`（HTML/JS/CSS 全部命中）；⑦ 资源导向映射——资源弹窗内含「厂商模型 → 系统统一模型」映射区（可选已有或就地新建），新增资源 + 就地新建系统模型一次保存后：资源得真实 `res-` id、映射引用同步改写、系统模型页出现新模型（分组）且资源池正确；测试对象删除后配置还原。**Q20 三项（追加核验）**：⑧ 资源接入管理——厂商名称自由输入（datalist 联想快填，命中预设自动填充 Base URL/接入模式）、账号必填且位于 Key 前（缺失保存提示「账号必填」）、映射就地新建只填统一模型名（**无端点/分组选择**）、系统模型页详情端点（chat|images）与分组可微调；保存后 vendor/account 持久化 + 占位 id 解析。**Q21 两项（追加核验）**：⑨ 界面视觉升级——视觉风格参考 aionui.com 简约清爽大气（留白/层次/组件现代感），**组件保留小圆角**（按钮 8px/卡片 12px，非 aionui 100px 胶囊）；顶栏主题按钮三态切换 **浅色 / 深色 / 跟随系统**（纯前端 `html[data-theme]` + `localStorage.mg-theme` 持久化 + `matchMedia` 系统联动），三主题下页面各页渲染正常、侧栏随主题切换（浅色白 / 深色深）、Chart.js 网格/刻度/图例随主题自适应。**Q22 三项（追加核验）**：⑩ 界面参考项目规范精修——**黑主色令牌**（激活导航/主按钮/开关 on 统一近黑 `#171b22`，深色主题反转为白）、**参考规范组件层**（卡片无边框软阴影、`#eef1f3` 行分隔软边框、分段式 tab、表头无底色、徽章 6px 圆角、指标卡 38px 图标块四色调）、**分组侧栏 + 两行顶栏**（侧栏四分组组标题、顶栏面包屑 `Console › 分组` + 页标题路由注入、7 页 page-head 无重复标题、`document.title` 随路由更新）。**Q23 两项（追加核验）**：⑪ 系统模型页厂商分组卡片——左子侧栏厂商 group-card（mark 首字 + 厂商名）按厂家分组，行 = 系统模型 ID + 启用状态点（绿=生效/灰=未开启，纯指示不承担点击）；点击模型行 → 右侧撑满配置区显示现有配置 1:1 迁移（头卡/基本属性/资源池，零新增字段）；禁用→行点变灰+面板锁定+配置落盘 enabled:false，启用回环后配置与备份逐字节一致；无映射模型归「未映射」区；删除走确认弹窗且配置还原。**Q24 八项（追加核验）**：⑫ 资源池设置——导航/页标题更名；左卡按**厂商归属**分组（内置目录 vendor 字段，deepseek-v4-* 经商汤接入仍归 DeepSeek 卡；不在目录归「自定义」卡），行 = 模型 ID + 启用状态点，每卡「＋ 添加模型」；头卡无删除按钮（暂时隐藏）；模型属性卡只读（厂商/上下文/输出/图片·视频·音频/深度推理档位）；详情区无「基本属性」编辑板块（Q24-⑨ 移除，DOM 断言 #md-endpoint/#md-group 不存在）；参数配置卡（网关值输入 + 卡头「恢复官方配置」一键重置 + 添加参数 + 行尾 ×，优先级提示三层级；参数项经厂商 API 文档二次核实——GLM 4 项 / Kimi 4 项 / DeepSeek 2 项〔双惩罚官方废弃〕/ 商汤 6 项推荐组合）；模型属性卡三列展示且无「归属厂商」行（Q24-⑩）；添加模型回环（选型 → 创建 → params 官方默认带入 → 清理）；资源池行内 effort 为下拉枚举（官方档位优先/通用三档兜底，images 无参数卡无提示段）；真实调用注入/请求覆盖/images 不注入 | 十一项逐一符合（DOM 快照 + 截图留证 `docs/changes/e2e-records/E2E-20260903-Q19-visual-remap.md`（⑥⑦）、`docs/changes/e2e-records/E2E-20260904-Q20-resource-mgmt.md`（⑧）、`docs/changes/e2e-records/E2E-20260904-Q21-theme.md`（⑨）与 `docs/changes/e2e-records/E2E-20260905-Q22-refined-ui.md`（⑩，CDP 截图 11 张存档 `q22-screenshots/`）与 `docs/changes/e2e-records/E2E-20260905-models-vendor-cards.md`（⑪，双主题截图 4 张存档 `assets-20260905-models-vendor-cards/`）与 `docs/changes/e2e-records/E2E-20260905-Q24-resource-pool.md`（⑫，DOM 快照 + 双主题截图 4 张 + 移除基本属性后截图 1 张 + 三列属性卡/参数补全截图 1 张存档 `q24-shots/` + 真实调用注入/覆盖/透传实测）） | PRD FR-7（Q18-③⑤ + Q19-①② + Q20-①②③ + Q21-①② + Q22-①②③ + Q24-①②③④⑤⑥⑦）/ FR-1.6 / FR-8.3 / FR-2.5（Q24-⑥ 参数注入） |

---

## 5. PRD 覆盖矩阵（P0 需求 ↔ 用例映射，防漏测）

| PRD 条目 | 覆盖用例 |
|---|---|
| FR-1 资源管理（Q18-② 扁平化：预设/枚举池/自动匹配/URL→base64/列表呈现/资源开关） | UT-12/18/19/20/29、INT-19/31/33/48、E2E-01/02/20（模型自动发现的 M1 形态=脚本拉取） |
| FR-1.2 预设注册表（内置预设数据 + GET /admin/api/presets 免鉴权，Q17/Q18-①）+ 厂商名称自定义（Q20-①：预设名 datalist 联想快填，厂商名落 `resources[].vendor`，provider/by_provider 优先取 vendor） | UT-26、INT-46、INT-50 |
| FR-2 模型映射与统一命名 | UT-12/20/21、INT-23/33、E2E-12 |
| FR-2.3 模型启用开关（models[].enabled / /v1/models 仅返回启用 / 禁用 404 model_disabled，Q17/D1） | UT-24/25、INT-39/40/41、E2E-16 |
| FR-3 调度/重试/切换/冷却/取消/切换事件记录 | UT-01~11/16/17/22、INT-02~13/20~26/28~29/32/34、E2E-09/10/14 |
| FR-3.16 推理参数（资源级默认+请求级覆盖，Q15） | UT-23、INT-36/37、E2E-15 |
| FR-4 多工具并发稳定 | INT-20 |
| FR-5 统一 API（三端点+鉴权+统计+端点类型+模型别名） | INT-01/14~18/23/26/28/30/33/35、E2E-03~08/11/12 |
| FR-6 统计与看板（事件/切换/聚合/保留） | UT-15、INT-01/18/27/29（看板 UI 于 M3 按 FR-6 验收，另补界面用例） |
| FR-6.1 统计派生维度（事件行 provider/account 冗余 + by_provider/by_account 聚合，Q17）+ FR-7.6 看板维度 tab 数据驱动 | UT-27、INT-47 |
| FR-7-1 Dashboard 总览·切换事件 | INT-29（/admin/api/overview 实时快照 + switch-events 文件；总览仅展示切换次数指标，明细见请求日志页） |
| FR-8 配置管理（热重载/校验/原子写/error_rules/扁平引用完整性/ID 自动生成与脱敏还原/占位 id 解析，Q18-② + Q19-②） | UT-13/14/18/19、INT-19/34/48/49 |
| FR-10 访问与安全（Q18-① 管理端免鉴权 + Q18-③ API 接入页密钥管理） | INT-14/27/48、E2E-11/20 |
| FR-12 系统运行控制（FR-12.1 stop/restart 端点免鉴权 / FR-12.2 启动网关.command / FR-12.3 单实例锁 data/gateway.lock，Q17/D2-D4 + Q18-①） | UT-28、INT-42/43/44/45、E2E-17/18/19 |
| FR-7 管理界面 Q18 重整（七页信息架构/资源表格化/API 接入页/设置页全局参数唯一入口，Q18-③⑤） | E2E-20（INT-48 支撑自动生成链路） |
| FR-7.2 界面视觉重设计 + 静态资源禁缓存（暗色侧边栏/SVG 图标/`Cache-Control: no-cache`，Q19-①） | E2E-20⑥ |
| FR-2.1 资源导向模型映射（资源弹窗内配映射/就地新建系统模型/占位 id 解析，Q19-②；就地新建只填统一名、端点/分组归系统模型页，Q20-②） | INT-49、E2E-20⑦⑧ |
| FR-7 资源接入管理 Q20（厂商名称自定义① / 映射区去端点分组② / 资源=厂商+账号+Key 账号必填前置③） | INT-50、E2E-20⑧ |
| FR-7 界面视觉升级 Q21（参考 aionui.com 简约清爽大气、组件保留小圆角① / 三态主题：浅色·深色·跟随系统，纯前端令牌化双主题 + localStorage 持久化②） | E2E-20⑨ |
| FR-7 界面参考项目规范精修 Q22（黑主色令牌① / 参考规范组件层（无边框软阴影卡片、分段式 tab、指标卡图标块）② / 分组侧栏 + 两行顶栏（面包屑 + 页标题路由注入）③；纯前端无后端变更） | E2E-20⑩ |
| FR-2/FR-7 系统模型页厂商分组卡片改版 Q23（图1 卡片版式：按厂家分组 + 启用状态点① / 配置参数范围维持现状四类、调度保持全局②；纯前端无后端变更） | E2E-20⑪ |
| FR-7 资源池设置改版 Q24（更名① / 厂商归属分组② / 启停语义③ / 隐藏删除④ / 模型属性卡⑤ / 参数配置卡与三级优先级注入⑥ / 添加模型入口⑦ / 四厂商 2026 目录⑧） | UT-30~38、INT-51~53、E2E-20⑫ |
| 非功能（可恢复/明文/脱敏/CancelledError 保护/HTTP 语义合规） | UT-14、INT-09/27/35、E2E-13 |
| tech §4.2 模型解析+端点校验+推理合并 | UT-20/21/23、INT-23/33/35/36/37 |
| tech §4.3 error_rules 覆写 | UT-19、INT-34 |
| tech §4.4 admin/status + 切换事件 | INT-29 |
| tech §4.5 流式窗口耗尽非 200 响应 | INT-35 |
| tech §5.2 统一调度语义（含 CancelledError try/except） | UT-03/04/05/11、INT-02/03/04/09/32 |
| tech §5.3 并发溢出生效集（x，Q13） | UT-22、INT-22 |
| tech §5.5 超时与总预算 | INT-13/24/25 |
| tech §4.3 全局资源状态 | UT-17 |
| tech §4.6 延迟提交窗口断连 | INT-24/32 |

> M2（管理界面）/M3（看板）阶段用例在 design-spec 定稿后按 FR-7/FR-6 细化追加（本文档追加 §7 界面用例）。

---

## 6. 执行状态跟踪矩阵（执行时填写，禁止无证据标通过）

| 用例组 | 总数 | 通过 | 失败 | SHELL | 未执行 | 最近执行 | 证据位置 |
|---|---|---|---|---|---|---|---|
| UT | 38 | 38 | 0 | 0 | 0 | 2026-09-05 | Q20 修正后全量回归 **187 passed in 39.91s**（UT+INT 合并执行，`.venv/bin/python -m pytest -q`）：UT-01~23 随 M1 验收（`docs/changes/e2e-records/E2E-20260903-summary.md`）；UT-24~28（v1.1）与 UT-29（v1.2）随回归通过 |
| INT | 53 | 53 | 0 | 0 | 0 | 2026-09-05 | 同上 187 passed（INT-01~38 随 M1 验收；INT-39~47（v1.1）、INT-48（v1.2）、INT-49（v1.3 Q19-② 占位 id 解析）、**INT-50（v1.4 Q20-① 厂商名称自定义）**随回归通过，证据 `docs/changes/e2e-records/E2E-20260904-Q20-resource-mgmt.md`） |
| E2E | 20 | 16 | 0 | 1 | 3 | 2026-09-05 | `docs/changes/e2e-records/E2E-20260903-summary.md`：13 条实测通过（E2E-01~06/08~13/15）；**E2E-20（Q18+Q19+Q20+Q21+Q22 界面实测）通过**：`docs/changes/e2e-records/E2E-20260903-Q18-ui-overhaul.md`（Q18 五项 5/5）+ `docs/changes/e2e-records/E2E-20260903-Q19-visual-remap.md`（Q19 两项 2/2：视觉重设计 + no-cache 实测、资源导向映射全链路（占位 id→真实 id→调用→清理还原）+ 真实调用 200）+ `docs/changes/e2e-records/E2E-20260904-Q20-resource-mgmt.md`（Q20 三项 3/3：厂商名称自定义、映射去端点分组、账号必填前置 + 全链路创建/保存/还原）+ `docs/changes/e2e-records/E2E-20260904-Q21-theme.md`（Q21 两项 2/2：aionui 风格 + 组件小圆角、三态主题切换 + localStorage 持久化 + 系统联动 + Chart 随主题自适应 + 三主题各页渲染核验）+ `docs/changes/e2e-records/E2E-20260905-Q22-refined-ui.md`（Q22 三项 3/3：黑主色令牌、参考规范组件层、分组侧栏 + 两行顶栏 + 指标卡图标块；CDP 七页双主题截图 11 张存档 `q22-screenshots/`）+ `docs/changes/e2e-records/E2E-20260905-models-vendor-cards.md`（Q23 两项 2/2：厂商分组卡片版式 + 现有配置 1:1 迁移 + 操作即保存；启停/删除回环配置逐字节一致，双主题截图 4 张存档 `assets-20260905-models-vendor-cards/`）；`docs/changes/e2e-records/E2E-20260905-Q24-resource-pool.md`（Q24 八项：更名/归属分组/隐藏删除/属性卡/参数卡/添加模型回环；pytest **199 passed**（UT-30~38 + INT-51~53 随回归）+ 真实调用注入/请求覆盖/images 透传 200 + 双主题截图 4 张存档 `q24-shots/`）；E2E-07（Trae 实配）移交用户验收（SHELL）；E2E-14 无法真实触发（Key 额度充足），按用例约定以 INT-04 兜底（计入未执行列）；E2E-16~19 未执行 |

---

> 本文档随实施推进维护：每轮执行后更新 §6 状态并留存证据；失败用例须附问题记录（同问题 2 次未解决 → 停手升层，铁律 3）。
