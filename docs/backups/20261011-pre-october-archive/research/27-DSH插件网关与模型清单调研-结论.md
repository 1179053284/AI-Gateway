# DSH 插件（`dsh-codearts-auth`）网关与模型清单调研 —— 交叉验证后的结论

调研日期：2026-10-03（21:1x~22:0x）
调研对象：`/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts`（`package.json` name `dsh-codearts-auth`，MIT，
remote `https://gitee.com/iJetLi/deepseek-harness-codearts.git`，HEAD `586ca00`，257 commits / 18 authors，`src/` 128 个 `.ts`）
被调方全程**只读**（未修改其任何文件、未执行其代码、未读 `~/.dsh` 凭据）。

## 0. 结论速览（每条都能在本文找到 file:line）

| # | 问题 | 结论 | 置信 |
|---|---|---|---|
| 1 | 它整合的那套「网关」是开源项目吗？ | **不是。是自研**（本仓一份 170 行设计文档 + 117 行实施计划 + 7 个源文件 + 7 个测试在**同一个 commit** 里首次落地；候选开源网关 LiteLLM / one-api / new-api / claude-code-router / opencode 的**标志性结构与词汇命中 0**；网关目录**零出站 HTTP**） | 高 |
| 2 | 那这个仓库里有没有"移植"？ | **有，但都在网关之外**，且作者每次都写明：`src/trae-errors.ts:4` 与 `src/lobsterai-errors.ts:4` 明示移植自 Go 的 `trae2api` / `lobsterai2api`。这条**反向加强**了"网关是自研"（同批作者对移植会标注） | 高 |
| 3 | 网关的真实身份 | `src/openai-gateway/`（10 文件 / **1703 行**，我 `wc -l` 复算）= 一个**只对外提供 2 条路由**的 OpenAI 协议外壳：`GET /v1/models` + `POST /v1/chat/completions`（`server.ts:261/265/273`），出站全部交给宿主 `ctx.llm`（`server.ts:217`，宿主接口只有 4 个方法 `server.ts:20-25`） | 高 |
| 4 | 换号/限流在哪一层？ | 🔴 **在本插件仓，不在宿主**：401/403 刷新→换号→全部试完才报错在 `src/buddy-adapter.ts:1358-1490`，(账号×模型) 限流标记与"全受限"判定在 `src/account-pool.ts:66-80 / :890`，冷却在 `src/buddy-adapter.ts:432-560`。（R1 判决行原写"都在宿主 dsh-llm 里"，被 R5 判为**错且与其正文自相矛盾**，我逐行复核后采信 R5 的更正） | 高 |
| 5 | 值得学习的地方 | 有 **11 条**成色很高的（本文 §3），其中 **5 条直接指向我方真实缺陷**：① 🔴 流式终态 —— 我方不只是"没判断腰斩流"，是**主动编造 `finish_reason: stop`**（`trae/out.py:49/169/210`、`qoder/out.py:221`）② (账号×模型) 最小发车间隔与并发型 429 分档（我方 `core/` 零节流）③ 「按模型记账的状态 ⇒ 读取路径每个调用点必须带 modelId」这条律有**源码级结构测试**在钉（我方只有行为测试）④ 我方 `normalize_name` **无条件剥日期后缀**，把可能是两条后端实体的模型缝成一个（且线上已发生）⑤ 能力位布尔**取并**但出站**不校验输入模态** ⇒ 声明了没有任何资源说过的组合 | 高 |
| 6 | 我方已经不比它差的 | 有 **5 条**（本文 §4）：能力位三态、映射判据单点、出站前承载校验 + 超窗换号、凭据脱敏在唯一入口、兜底数据不污染缓存。其中"兜底不污染缓存"与我方**独立得出同一条纪律**（`catalog_cache.py:127`「空清单不写」+ `admin_accounts.py:1370`「兜底表那一路不落盘」） | 高 |
| 7 | 明确不可借鉴（越界） | `src/qoder-auth-wasm.wasm`（298,606 B，git 已跟踪，从**闭源 Qoder 客户端提取**的二进制）、WASM 签名头透传、各家私有登录/验证码链路与凭据获取 —— 我方规则允许借**设计思想**，不允许直接采用/修改第三方闭源或加密产物 | 高 |
| 8 | 最大的一个观念分歧 | **跨供应方同一厂商模型的规格要不要合并**：它的立场是**不合并**（`docs/superpowers/specs/2026-09-30-openai-gateway-design.md:78` 原文「不同 provider 的同名模型不合并」，且测试用例名直接钉死 `namespaces models by provider without merging duplicates`，`tests/unit/openai-gateway-models.spec.ts:16-24`）；我方 Q33 是**合并 + 取大/取并**。我的裁决建议见 §6：**保留合并层（这是"网关模型"这个概念的本体），但借它的三条"怎么合并"的约束** | 中（要用户点头） |

## 1. 方法与交叉验证记录（怎么得到上面这些结论的）

五路角色 + 主 agent 亲自复验，全部报告留在 `docs/changes/reviews/`：

| 角色 | 分工 | 产出 | 状态 |
|---|---|---|---|
| R1 | 网关身份判定（是不是开源移植） | `dsh-gw-r1-origin.md`（227 行，12 条证据表 + 6 组反向判据） | 判决成立，**两条数字/表述被推翻**（见下） |
| R2 | 模型清单代码结构逐产品盘点 | `dsh-gw-r2-catalogs.md`（655 行：0 覆盖台账 / 1 逐产品 / 2 双名 / 3 链路 / 4 合并策略 / 5 十五条真实缺陷） | 主体成立，**一处行号越界** |
| R3 | 网关运行时机制 10 项 + 我方逐条对照 | `dsh-gw-r3-runtime.md`（583 行，13 张表） | 成立，其"我方缺 3 条"我已逐条亲验 |
| R4 | 对照与借鉴清单（第 1 次派发中途停摆，已重派） | `dsh-gw-r4-borrow.md` | 见文末补记 |
| R5 | 质疑复核（18 条抽证 + 机械复算 + 三条反向命题） | `dsh-gw-r5-verify.md`（246 行，VERDICT `通过但有保留`，9 条阻塞项） | 有效，抓到 2 处硬伤 |

主 agent 亲自复验（不采信任何二手转述，逐条打开原文）：
`src/openai-gateway/server.ts:246-276`（路由面）·`wc -l src/openai-gateway/*.ts` = **1703**（更正 R1 的 1503）·
`auth.ts:1-60`（43 位定长形态判据 + 「文件内容异常时报错而不是悄悄换 key」）·
`messages.ts:58-80`（三态归一化原文）·`buddy-oauth.ts:420-430`（「采信实际命中的那个端点，不做跨端点取大」）·
`product.ts:192-198`（静态兜底**取小**：128000 是服务端真正接受的额度，131072 只是 `/v3/config` 声明值）·
`trae.ts:1159-1186`（三条择优规则 + 「档位必须与 `function` 同源，整条择优」）·
`account-pool.ts` = **1268 行**（⇒ R2 引用的 `account-pool.ts:2387` 不存在，越界）·
`buddy-adapter.ts:72-92`（`DEFAULT_MODELS` **15 条裸 id** 兄弟表，R2 的"160 条"外延漏了它）·
`remote-catalog-gate.ts:84-95`（`inFlight` 的同步抛错陷阱与"先落局部量、await 后再清、只清仍是自己那一个"）·
`stream.ts:169 / :204`（`incomplete_stream` 两处出口）·`model-gate.ts:11-38`（ZCode 免费通道 429 两种语义、并发配额与剩余额度无关 —— 撞 429 时 token 还剩 299.4 万；GLM-5.3 一轮 74×200 / 21 重试 / 6 终局 429）·
`raccoon-product.ts:267-286`（「远端 `tags` 含 `vision`」被当能力契约 ⇒ 宿主 `projectImagesForTextModel` **把图片替换成文本占位符**，图根本没发出去）·
`tests/unit/trae-model-id-selection.spec.ts:74-218`（8 例，含「传空串时忽略限流标记（这正是缺陷）」与「`refresh` 块仍保留空串（语义不同）」两条**方向相反的**钉）·
我方侧：`core/scheduler.py:720-750`（流结束即 `note_success` + `settle_quota` + `status="success"`）·
`adapters/openai_out.py:145-178`（SSE 只在 `[DONE]` 时 return，上游掐线则 `async for` 自然耗尽、**不报错**）·
`adapters/openai_out.py:73-99`（客户端给的 `image_url` 由网管自己 `GET`，只校验 `http(s)://` 前缀）·
`config/schemas.py:86 host: str = "0.0.0.0"` + `config.example.yaml:10` + 实盘 `lsof` = `TCP *:8300 (LISTEN)` ·
`core/catalog_cache.py:127` 与 `api/admin_accounts.py:1367-1371`（兜底不落盘的自有同型纪律）。

R5 抓出的两处硬伤（已采信并在本文更正）：
1. R1 判决行「路由/凭据/换号/限流都在宿主 `dsh-llm`」——**错**，换号与限流在本仓（见 §0 第 4 行）。
2. R2 引用 `account-pool.ts:2387`——**该文件只有 1268 行**，行号不存在（其 147 处引用里唯一一处越界）。
另：R1 的"1503 行"我复算为 **1703 行**；R1/R2 的"12 张表 160 条"R5 逐表复算**完全对上**，但外延只统计 `*_FALLBACK_MODELS`，漏了 `buddy-adapter.ts:72` 那组 15 条裸 id 表。

## 2. 它的模型清单代码长什么样（这是用户点名要看的部分）

### 2.1 分层：每个产品两套接口，字段形态互不兼容
- `listModels()` —— 轻规格：宿主契约 `LlmModelInfo` = `provider / id / name / description? / inputModalities?`
  （`node_modules/@deepseek-ai/dsh-llm/lib/types/types.d.ts:262-273`，我逐行读过；R2 写"4 字段"少算了一个），给"模型选择器"用；
- `resolveModel(modelId)` —— 重规格：再加 `maxOutputTokens` 与**思考档位表**（`efforts` + `default`），给运行时下发用。
- 🔴 宿主契约里就写着我方争论过的那条律（`types.d.ts:271`）：
  「**Accepted request modalities; absent means unknown, while an explicit omission is negative capability**」
  = "字段缺席是**未知**，显式不给才是**不支持**" —— 与我方 Q33 债1 / R5-F-4 的能力位三态（`null` 不印成 `false`）**同一条判据**，
  而且它是**接口注释层面**的约定，我方是三态实现 + 用例。⇒ 可借鉴的是"把三态写进契约文本"这件事本身。
⇒ **可借鉴点**：把"够 UI 用"和"够出站用"分成两层，我方现在是一条 `ModelInfo` + 一份 `ModelSpec` 混着给（界面与出站读同一份），层次意图不明。

### 2.2 清单来源：**12 张静态表为主**，远端只作补位
逐产品表位（R2 全覆盖台账 + 我抽验）：`product.ts:180-266`（buddy）/`:295-367`（workbuddy）/ `qoder-product.ts`（17 个目录 key，因 `/model/list` 要 WASM 签名 ⇒ `listModels` **不发网络**）/ `lobsterai-product.ts:183-203` / `trae-product.ts:169-202` / `cline-product.ts:146-204` + `cline-models.ts` / `cline-models-dev.ts:142-210`（models.dev 社区目录并入）/ `loomy-product.ts:104-113` / `raccoon-product.ts:218-326` / `zcode-product.ts:180-207` / `minimax-product.ts:76-119` / `opencode-product.ts:103-152` / `llm-adapter.ts:47-70` + `models.ts`（CodeArts）。

它的**可信度分层**是明确写下来的（`cline-models-dev.ts:142-151`）：外部社区目录只允许**补缺**（补名字仅当 `name===id`、补窗口仅当缺失、`maxTokens` 干脆不并、`supportsImage` 只在缺失时补 —— 本地显式 `false` 照样赢）。
⇒ 与我方同型但表达更硬：我方是"实时账号目录 > （枚举池第三档明确不取）"（`UT-93`），它是"本地实测策展 > 上游网关 > 社区目录"。**同一方向，它把"低层只填空位"写成了逐字段规则。**

### 2.3 双名（目录 key vs 通用名）：它的解法是**分派给两个端点**，不是归一
`AGENTS.md` 自述 + `qoder-product.ts`：加密端点 `api2.qoder.sh` 认 `qfmodel`/`dmodel`，公开端点 `api2-v2.qoder.sh/model/v1/chat/completions` 认 `qwen-flash`/`qwen-plus`，两个 host 不是同一个，混用 404；真实用户报障是"发 `qwen3.8-flash` 没回复就终止"。它的处理 = 两套名字各归各端点，**不建同义词表**。
⇒ 对我方直接相关：我方 `enums/matcher.py` 的 `normalize_name`（`._ -空格` 统一折成 `-`、去日期后缀）**不认 `/` 前缀**，`_enum_suggest`（`api/admin_accounts.py:1232`）又只看 id ⇒ 我实测的 22 条收不回（Qoder 的 `gmodel`、Cline 的 `cline-pass/glm-5.3`）。它的教训是：**不要试图把两套名字归一成一个，而是保留"来源身份"**。

### 2.4 「未知」怎么表达 —— 它内部有**四种不互通**的形态（我方该避免，不是该学）
整个键不产出（`buddy-adapter.ts:975-1002`、`cline-models.ts:212-215`）／`0` 作哨兵再 `>0` 过滤（`raccoon-auth.ts:169-171`、`opencode-capability.ts:47-48`）／`undefined` + 字段可选并专门论证"标成 `number` 会让类型撒谎"（`minimax.ts:176-187`）／三态 `string|null|undefined`（`messages.ts:75-79`）。
⇒ 我方是三态 `None`（`/v1/models` 印 `null` 不印 `false`，债1/F-4），**已经比它统一**；但它那条论证（"必填 `number` 会让类型撒谎，因为宿主有硬校验、`undefined` 塞进去整轮崩"）值得抄进我方 `ModelSpec` 的注释纪律。

## 3. 值得学习的 9 条（按对我方的实际价值排序）

| # | 它的做法（file:line） | 我方现状（file:line） | 我方为什么缺 | 建议 |
|---|---|---|---|---|
| **L1** | 流式**终态不变量** `incomplete_stream`：上游没发 finish 就结束 ⇒ 一处给客户端发 error 帧、一处抛 502（`src/openai-gateway/stream.ts:169`、`:204`；条件原文在 `:167` —— `if (state.finishReason === undefined)` 才走这条，即**它把"没见过终止"当独立事实处理，不猜**） | 🔴🔴 **比我最初报的更糟：我方不是"没判断"，是"主动编造终止原因"** —— `upstream/trae/out.py:49` 定义 `_DEFAULT_FINISH = "stop"` 并在 `:169 / :210` **作为初值**写入，`qoder/out.py:221` 写 `finish or "stop"`；再叠加 `adapters/openai_out.py:155-170`（线被掐 ⇒ `async for` 自然耗尽、不报错）与 `core/scheduler.py:732-736`（随即 `note_success` + `settle_quota` + `status="success"`）。⇒ 一条被腰斩的回答，客户端拿到的是 `finish_reason: stop` +  usage 结算 + 日志记成功 | 我方把"没观察到终止"翻译成了"正常说完"，这是**伪造上游事实**（与铁律 2 相反的方向），且额度被真实烧掉而无人可见 | 两步：① 解析腿记 `saw_finish`，未见终止标记 ⇒ 按失败处理并带 `incomplete_stream` 原因码（不许默认成 `stop`）；② 各家 `out.py` 里"缺失即补 `stop`"的三处（`trae/out.py:49/169/210`、`qoder/out.py:221`）改成**保留未知**（`None`）或由 ① 的前置判据拦住。判据与撤证同批补（**已开任务 #47**，本轮升级为阻塞级） |
| **L2** | **(账号×模型) 限流 + 最小发车间隔**：`model-gate.ts:11-38` 是 48 行实测台账（429 有两种语义；**并发配额与剩余额度无关**，撞 429 时 token 还剩 299.4 万；GLM-5.3 一轮 74×200/21 重试/6 终局 429）；`account-pool.ts:66-80` 判"全部账号该模型都受限"（缺标记/0/已过期 = 不受限） | `core/` 无任何节流（`grep` 只命中 `cancel.py:65` 轮询与 `scheduler.py:319` 预算等待 0.1s）；撞一次 429 就进资源冷却 | 我方把"节奏问题"升级成"账号停用"，方向偏重；也解释不了"额度很多却一直 429" | 加 (号×模型) 最小发车间隔与 `resetAt` 标记，429 先分"并发/配额"与"额度"两档再决定是否冷却。**已开任务 #48** |
| **L3** | **一条律配一个源码级结构测试**：`tests/unit/trae-model-id-selection.spec.ts:189`「`resolveCredential` 块的选号调用不得传硬编码空串」（直接读源码块扫）+ `:211`「至少八个 provider 的 `resolveCredential` 接收 modelId」+ `:218` 反向钉「`refresh` 块**仍保留**空串（语义是定位账号，不该按模型过滤）」 | 我方判据单点靠行为测试（`mapping_enabled` 八个调用点各有用例），**没有**"不许出现第二份实现/不许漏传参数"的结构门 | 行为测试能证明当下正确，挡不住后来新增的调用点漏传 | 在 `bianyiandhuanjing/scripts/` 加一支静态门：扫账号侧选号/额度/承载三类调用点必须带 `model`/`vendor_model` 实参；反向钉 `refresh` 语义。**这是"判据只有一份"从口头约定变成机器可红** |
| **L4** | **参数归一的三态与"只标不拦"的边界**：`messages.ts:58-112` —— 用户没传=`undefined`；传了但本模型没这组档位=`null`（**不下发**，否则整轮失败）；模型**声明了**档位却不含用户那档=**抛 400**（静默丢弃会让用户以为生效） | 🔴 已复验：`scheduler.py:261-277 _degrade_effort_if_needed` 会**静默改写**用户请求的档位（`replace(spec, effort=degraded)`），**全程不留痕**（无事件、无日志、响应里也不标注）；目录无档位信息时原样透传（这一半是对的：不臆断） | 用户要 `high` 拿到 `medium`，界面上没有任何地方说这件事 —— 与它"声明了档位却不含用户那档必须抛 400"的取舍不同，但**我方连"改写发生过"都不可观测**，比它更弱 | 补一条可观测性：改写时在请求事件里落 `effort_degraded: {from, to, reason}`（"只标不拦"，与 v2.34 的跨字段校验同一纪律），界面在日志/明细里可见；要不要同时抛 400 属产品口径，需用户点头。**已开任务 #50** |
| **L5** | **静态兜底取"服务端真正接受的额度"**：`product.ts:192-198`（128000 vs 131072 取小）+ `buddy-oauth.ts:427`「采信实际命中的那个端点，**不做跨端点取大**」+ `buddy.ts:441-446` 实测三处取值不一致 | `core/model_spec.py` 数值**取大** | 我们的取大有承载校验兜底（超窗换号 + `ALL_OVER_CAPACITY`），所以不是错；但**对外承诺 = 池里最乐观那家**这件事对用户是可误导的 | 保留取大（它是网关模型聚合的本体，见 §6），但借它两点：① 静态兜底一律取"实测被接受"的那个值而不是声明值；② `sources` 之外再给界面一句"这个数来自哪一家 / 有没有更小的供应方" |
| **L6** | **合并时保持来源同构**：`trae.ts:1159-1186`「档位必须与 `function` 同源，**整条择优**，不许把 A 通道的 `reasoningConfig` 搬到 B 通道」+ 空档位不得覆盖有档位 + 两侧都有档位才按通道优先级 | `core/model_spec.py` 按字段分别取优（数值取大、布尔取并、档位取并） | 这正是我方 R8-B-1 别名形状病灶的**一般形态**：按键/按字段合并会把不同来源的属性缝成一条没人支持的记录 | 在 `model_spec.py` 的合并判据里补一条"能力字段（档位表）必须与其载体同源"的约束 + 用例（我方现有 `UT-92` 是它的特例） |
| **L7** | **失败态与并发去重做在"内部事实"上**：`remote-catalog-gate.ts`（114 行）+ `zcode-auth.ts:1265-1278` 把它写成通用律 + `minimax-auth.ts:361-369`「判据做在内部事实，不做内容比对」+ `:86-92` 那个具体的 async 赋值陷阱（同步抛错 ⇒ `inFlight` 被覆盖成已 settle 的 Promise ⇒ **永久不再重拉，冷却到期也救不回**）；测试 `remote-catalog-gate.spec.ts` 11 例含「时钟回拨不得把冷却拉长」 | 我方 `accounts/catalog_cache.py` 有 TTL + `stale`，**没有**失败冷却/in-flight 去重；但有同型的"空清单不写"（`:127`）与"兜底不落盘"（`admin_accounts.py:1370`） | 我方目录取数发生在界面动作上，撞不到它那种"永久污染"；但多号并发取数确实可能重复发请求 | 只借**判据表达**（"拿到目录没有"不许用长度或内容比对），冷却暂不做（记债务，别虚报为已完成） |
| **L8** | **密钥形态判据 + 报错不自愈**：`auth.ts:8-15`（base64url 定长 43 位 ⇒ 可机械区分"我们写的东西"与"被人动过"）+ `:34-45`（内容异常时报错并给恢复办法，**不悄悄换 key**，理由：换 key 会让所有已配置客户端同时 `unauthorized` 且毫无线索） | 🔴 复验后**我方形态判据已更严**：`api/admin.py:677-683 _unmask_resources` 要求界面回传值与 `mask_key(当前真值)`**逐字相等**才还原成明文 ⇒ 不会被"任意长得像掩码的串"骗过。残余缺口只有一个：若用户把**别的 key 的掩码**或残缺掩码当真 Key 粘进来（不等于当前掩码），我方**照存**，后果是之后一条上游 401，用户不知道为什么 | 借它的**报错方向**（可疑输入要明确拒绝并给恢复办法，而不是静默接受），不是借它的形态判据 | 在 `PUT /admin/api/config` 保存资源时，`api_key` 命中"掩码形状"（含 `****`）却不等于该项当前掩码 ⇒ 400 + 一句「这看起来是界面上的脱敏显示，不是真实 Key」；配判据。含后端改动 ⇒ 要重启 |
| **L9** | **能力位必须实测，不许拿元数据当契约**：commit `df25f01` + `raccoon-product.ts:267-286`（根因链完整：tags 没 `vision` ⇒ 播 `['text']` ⇒ 宿主**把图片替换成文本占位符** ⇒ 用户看到"读不到图片"而端点其实正常）；测试 `raccoon-product.spec.ts` 新增 6 例，其中"两个真相源必须一致"把 2026-10-03 实拉的 `REMOTE_TAGS` **逐条抄进测试**，并写反向验证；作者还把旧断言标注为「本条曾经锁死了缺陷行为」 | 我方能力位来自内置目录官网取证 + 号级目录；`caps_overrides` 可人工覆盖；三态已闭（债1/F-4） | 我方没有"上游元数据与实测行为不一致"时的**白名单+双真相源测试**这一层 | 借两件事：① 能力位可疑时走"实测白名单"而不是信元数据；② 把某次实拉的远端原始数据逐条钉进测试（我方门里已有同型做法，可推广到能力位） |

| **L10** | 🔴 **带日期的模型名可能是另一个后端实体，不许并名**：`src/models.ts:31-52` + `AGENTS.md:1900-1947`（`benefit` 集合与 `maas_type` 头的实测矩阵：带日期与不带日期的两个 id，**服务端要求的请求头方向相反** ⇒ 并成一个就有一条必被拒；修复方向还写成「远端下发的集合优先，新增模型无需改代码」） | 🔴 我方**已经在并**：`enums/matcher.py:211 _DATE_SUFFIX = r"-(\d{4,8})$"` 被 `normalize_name()` **无条件**执行 ⇒ `deepseek-v4-pro-0813` 规范化成 `deepseek-v4-pro`。实证就在我自己上一轮的盘点里：:8300 实读 Loomy 的 `deepseek-v4-flash-0731` 被建议腿挂成 `deepseek-v4-flash`（`docs/changes/20261003-mapping-census.md` §3 Loomy 行）；同时内置目录里 `claude-sonnet-4` 的**别名表**恰好把 `claude-sonnet-4-20250514` 当同义（`matcher.py:198-203`）⇒ 同一套规范化里"日期=别名"与"日期=另一实体"**两种语义混用** | 这不是"待裁决的口径"，而是**已经在线上发生的合并**：Anthropic 的 `-YYYYMMDD` 是真别名，国产模型的 `-MMDD` 可能是另一条后端实体，一刀切剥离必然有一半是错的 | 把日期剥离从"全局规范化"降为**逐条目录项声明的别名**：`normalize_name` 不再自动去日期，需要并的写进 `aliases`（claude 那两条正是这么做的）；判据 = 带日期 id 不与无日期基础名互相解析 + 撤证。**已开任务 #51** |
| **L11** | **合并出的组合必须有来源说过**（L6 的一般形式）：`design.md:78` 的"不合并" + 内部三条合并约束，实质是**不承诺任何单一来源没说过的组合** | 🔴 我方 `core/model_spec.py:18/116/134` 是"任一来源具备即具备"（`_any_true`），而 `image_input` 在 `core/scheduler.py` 与 `adapters/openai_out.py` 里 **grep 零命中** ⇒ 声明侧可以给出"1M 窗口 + 支持图片"这种**没有任何一条资源同时说过**的组合，而出站选号**完全不校验输入模态** | 承载校验只做了 token 维（超窗换号），输入模态这一维是空的；插件的 D1 恰好演示这条链坏掉时的表现（图片被静默换成文本占位符，用户只看到"读不到图片"） | 两条并行：① 选号把 `image_input`（及工具维）纳入承载判定，不满足 ⇒ 换号 / `ALL_OVER_CAPACITY` 同族终局；② 声明保留取大取并，但 `sources` 从计数精化成**逐位归属**（谁说的这一位）。**已开任务 #52** |

## 4. 我方已经不比它差 / 不需要学的 5 条（防只报喜）

1. **对外声明的聚合层**：它没有"网关模型"概念 —— `id = ${provider}/${model}`、`owned_by = provider`（`openai-gateway/models.ts:27-29`、`:108-120`），同名的两条并存各说各话。我方有系统模型 + 合并规格 + `/v1/models` 单名对外，这是产品定位差异，**我方更贴近用户要的东西**（用户原话：网关模型 = 把各家同一厂商模型标准化）。
2. **按号承载校验与超窗换号**：它完全没有（选号只看限流标记/余额/顺序，不看 `contextWindow/maxTokens`），所以它也**不需要**我方那套 `ALL_OVER_CAPACITY` 终局与可达性对照。⇒ 它的"不合并"在它自己的架构里自洽，照搬到我方会拆掉承载校验。
3. **凭据脱敏**：我方有唯一入口 + 出口兜底、先脱敏再截断（`stats/events.py::error_summary`）；**它整个网关目录零脱敏实现**（R3 实测）。
4. **流式的"首帧前不发 200"+ 心跳 + 首帧后失败策略**：我方比它细 —— 心跳 `config/schemas.py:92 heartbeat_seconds=15` → `api/openai_compat.py:182/217` 与 `api/anthropic.py:419-421`（`event: ping`）；`committed` 之后失败不重放、走流内 error 帧（`core/scheduler.py:42` `ERROR_EVENT`、`:622`、`:717/721/747`）。⇒ 补上 L1 的 `incomplete_stream` 终态即两者兼得。
5. **兜底不污染缓存**：我方独立写下同一条纪律（`catalog_cache.py:127`「取到了 0 条不是证据，是异常」+ `admin_accounts.py:1370`「兜底表不落盘：缓存它等于把『没有来源』伪装成『有来源』」）。⇒ 它的 D2 缺陷在我方**不发生**，但缺冷却/in-flight（§3-L7）。

## 5. 它的十五条真实缺陷里，对我方最有价值的六条（原文缺陷 → 我方对应风险）

| 它的缺陷（commit） | 症状原文 | 我方对应风险（不是"我也有"，是"同型形状"） |
|---|---|---|
| D2 兜底污染远端缓存（`0ca8256`，10 个消费点一次改） | 判"拿到目录了吗"用空数组 ⇒ 兜底被永久缓存，只能重启 | 我方 `stale`/TTL 判据已避开；但**界面读缓存的 4 个消费点**（弹窗/调度/声明/权益闸门）若将来加"长度判据"就会复现 —— L3 的结构门正是防这个 |
| D3 冷启动能力表为空（`1960870`） | 异步盘读 ⇒ 窗口内恒 `[]` ⇒ 宿主准入直接拒发图；并且"后台刷新后广播"救不了（广播只重渲染，不会重走准入） | 我方装配期注入目录（调度零网络），形状不同；但**"广播/热重载不等于下游会重算"**这条对我方热重载路径同样成立，值得自查一次 |
| D4 空档位覆盖有档位（Issue `IKI7WT`/`IKILR7`） | 假设"后面那条更完整"与真实数据相反 ⇒ 实测 **13 个模型丢档位**，修后有档位的从 5 恢复到 15 | 我方 `model_spec.py` 的取并/取大是同族风险；L6 的"整条择优"约束正是补丁 |
| D5 只声明 `context` 从不声明 `reasoning`（`c94c3fa`） | 档位选择器**从来没出现过**，尽管目录早就下发了 `thinking_config` | 我方 `check-models`/弹窗/`/v1/models` 三处字段口径曾经不对称（债1/F-4 修的就是这类），同型问题要按"每个消费口都有一条正向判据"来防 |
| D8 免费模型被"永久积分锁定"门拦下（`7566e2e`/`71ecbdd`） | 「账号明明有余额却失败」；反向风险也钉了：付费模型误判为免费会**真烧永久积分且不可撤回** | 我方按号权益闸门（判定式第四项）同族，误判方向也要有反证用例 —— 这条是判据**设计**层面的借鉴 |
| D10 UI 里开关在最右侧要横向滑动才看见 | 不是功能缺失是**看不见**（300 个 id 超 20 字符，最长 56）；副作用是 `disabledModels` 长期为空 = 用户从没能关过 | 与我方 2026-10-02「进池开关覆盖面」事故**同型**（旧实现把开关画在"已映射"这个历史前提上 ⇒ 9/10 产品 0 颗开关）；它的验证法值得抄：**从真实源码模块提取样式**渲染复现页，修前实测 8/8 行开关全部不可见。🔴 同一条律在 `src/lobsterai-adapter.ts:843` 有第二处自证：「设置页必须渲染被关闭的模型（否则用户无法重新打开），而 `listModels` 会按黑名单过滤」⇒ **可见性判据要覆盖"关着的那批"**，我方 `check-models`/弹窗两侧都该照此复查一次 |

## 6. 专题裁决：合并 vs 不合并

**事实**：它不合并（`design.md:78` 原文 + 用例名钉死），且**同一产品两个 provider 也分开**（`qoder` vs `qodercn`、`buddy` vs `workbuddy`）；全仓没有一处把同一厂商模型的多供应方规格合成一份。它的三个内部合并决策（Buddy 先命中为准 / TRAE 整条择优 / Cline 社区目录只补缺）**全在 provider 内部**。

**为什么它敢不合并**：它不出站、不按号校验承载，选号不看窗口 —— 合并了也没人消费。
**为什么我方要合并**：产品承诺就是"一个网关名 = 一个厂商模型的标准参数"（用户定义），且我方有承载校验 + 超窗换号 + 按号缺省注入来**消费**这份合并结果。

**我的结论（建议，不改代码）**：**保留合并层，吸收它的三条合并约束** —— ① 字段不许跨来源分别取优（整条择优，L6）；② 静态兜底取"实测被接受值"，不取声明值（L5）；③ 可信度分层显式化（`cline-models-dev.ts:142-151` 的逐字段"只补缺"）。
🔴 但 R4 与我独立得出同一条**加强判据**：它"不合并"的实质不是"不给统一名字"，而是**不承诺任何单一来源没说过的组合**。我方现在恰恰在承诺这种组合（`model_spec.py:116/134` 的 `_any_true` 把 A 家的"支持图片"与 B 家的"1M 窗口"缝成一个模型，而出站对输入模态**零校验**）。⇒ 保留合并的**前提**是补齐三件：① 逐位 provenance（每一位是谁说的，不只是 `sources` 计数）；② 承载判定加输入维（任务 #52）；③ 能力字段与其载体同行（L6）。这三件不齐，"取大取并"就是它在 `design.md:78` 里反对的那件事，我们没有资格只保留结论不保留约束。
**R4 的立场**（独立复核，与我一致）：不采纳"不合并"作模型身份层（那会推翻 Q33-⑤ 与产品定位），但全盘采纳四条判据（保留取大 + 逐位 provenance + 承载校验补输入维 + 字段与来源同行）。
**反转触发条件**：若出现"合并后的对外承诺让客户端按 1M 规划请求，而池内**所有**号都装不下"的频率明显上升（`ALL_OVER_CAPACITY` 终局计数），则退到"对外声明取池内最小值、按号仍注入按号值"的两档口径 —— 那时要同步改 `UT` 的取大判据与 `/v1/models` 文案，不能只改一边。

## 7. 未验证 / 待复核（禁止冒充完成）

1. **离线无对拍语料**：R1 的"自研"判定建立在结构证据 + 作者标注习惯上，**没有做逐段代码相似度比对**（无法联网拉取候选开源项目源码）。若日后能取到 LiteLLM/one-api/new-api/CCR 源码，应做一次相似度抽查再收口。
2. `trae2api` / `lobsterai2api` 是否公开开源、其许可条款如何 —— **未判定**（这影响我方能否引用它们的思路，不影响"网关自研"结论）。
3. 该插件的**实际运行行为**未验证（本轮全程静态阅读 + `git log`，未运行其代码、未发真实请求）。所有"它这么做"的结论是**代码事实**，不是**行为实测**。
4. R2 十五条缺陷里 6 条只找到两源证据（作者已在报告里标 🟡），本文引用时保留了 🟡 标注。
5. 我方 L1（腰斩流）与 L2（无节流）两条缺陷是**读码 + `grep` 复算**得出，尚未做端到端实测复现（要复现得构造"上游不发 [DONE] 就断线"的假厂商用例 —— 这本身就是应补的判据）。
6. **R4 已交付**（`dsh-gw-r4-borrow.md`，240 行 / 12 条独立复核 + 14 条借鉴 + 11 条"我方已更优"+ 8 条越界项）。与本文 §3 的 11 条**不是同一把尺**：本文只收"我已逐行复验原文"的条目，R4 另有 3 条（面板/凭据展示、错误翻译粒度、批量操作可见性）我没复验 ⇒ 本文不收，需要时去 R4 读原文再定。**R4 贡献了两条我原来漏掉的升级**：① 我方流式侧不止"没判腰斩"，`trae/out.py:49/169/210` 与 `qoder/out.py:221` 是**主动把终止原因写成 `stop`**（我复验原文后并入 L1）；② `normalize_name` 全局剥日期 ⇒ 与内置目录把 `-20250514` 当别名混用（我复验后列为 L10）。
7. R4 报告里"我方 `qoder/out.py`、`trae/out.py` 两处编造 finish"已复验；它给的另外两条行号（`stream.ts:167-172`、`models.ts:31-52`）我也逐行对过原文。

## 附：本文所有数字的复现命令

```
wc -l src/openai-gateway/*.ts                                  # 1703（更正 R1 的 1503）
sed -n '246,276p' src/openai-gateway/server.ts                 # 2 条路由 + OPTIONS + 鉴权在分派之前
grep -nE "fetch\(|undici|http\.request|axios" src/openai-gateway/*.ts   # 零出站
wc -l src/account-pool.ts                                      # 1268（⇒ R2 的 :2387 越界）
sed -n '66,92p' src/buddy-adapter.ts                           # 15 条裸 id 兄弟表
sed -n '1159,1186p' src/trae.ts ; sed -n '420,430p' src/buddy-oauth.ts ; sed -n '192,198p' src/product.ts
sed -n '11,38p' src/model-gate.ts ; sed -n '84,95p' src/remote-catalog-gate.ts
grep -n "incomplete_stream" src/openai-gateway/stream.ts       # :169 :204
sed -n '732,743p' coding/model_gateway/core/scheduler.py       # 流自然结束即判成功
sed -n '145,178p' coding/model_gateway/adapters/openai_out.py  # 没有 [DONE] 也算正常返回
sed -n '73,99p'   coding/model_gateway/adapters/openai_out.py  # 客户端 image_url 由网关 GET
grep -n "min_interval\|throttle" coding/model_gateway/core/*.py # 我方零命中
lsof -nP -iTCP -sTCP:LISTEN | grep 8300                        # TCP *:8300 (LISTEN)
```

---

## 9. ⚠️ 本文 §3 的 11 条经六路实证复核后的更正（2026-10-04，必读）

裁决与实跑证据 = `docs/changes/reviews/dsh-learn-v{1,2,3,4,5}.md` 与 `dsh-learn-v6-premises.md`；汇总与实施队列 = `dsh-learn-0-verdicts.md`。本文以下表述**已被自己派出的角色推翻或降级，引用时以本节为准**：

1. **L11 的归属挂错了**：插件 `docs/superpowers/specs/2026-09-30-openai-gateway-design.md:78` 原文只说「不同 provider 的同名模型不合并」，**从未说**「不承诺任何来源没说过的组合」——那是我方推断。它没有承载校验，"不合并"对它是**无需**而非**原则**。⇒ §6 里"两边独立得出同一条收敛"这句要降级为"我方自己的判据，只是被它的立场提醒了方向"。
2. **L2 的成色要降级**：`model-gate.ts:11-38` 那组数字（74×200 / 21 重试 / 6 终局 429 / 剩 299.4 万）是**注释自述**，且该文件 `:6-7` 自陈吸收自**不在本仓**的 `dsh-free-glm`（全仓只有三处文字重复、零原始产物）；机制上 `ModelGate` **只被 zcode 一个 adapter 使用**（`zcode-adapter.ts:316/1256`），间隔键**只有模型维、没有账号维** ⇒ 我写的"(账号×模型) 最小发车间隔"是**我方自创**，不是它的做法。真实现的是限流那半（`account-pool.ts:65-79` + `index.ts:482-496` 带解禁时刻报错）。
3. **L10 的"线上已发生"错了**：:8300 实读 29 条带日期目录 id，**0 条被剥离挂错**；唯一拿到建议的 Loomy 那条走的是 `via=alias/0.9`（`matcher.py:120`），摘掉全局剥离后读数一字不变 ⇒ 我原来把 alias 命中误读成日期剥离命中。处方改为：`_DATE_SUFFIX` 收窄到 `-(?:19|20)\d{6}$`、`_norm` 撞车键不许 first-wins、auto-map 正则腿不许静默置 `enabled=True`。
4. **L4 / L6 的前提要改**：我在 §3-L6 与上一轮回答里断言"我方 `_degrade_effort_if_needed` 已按资源自身 `effort_levels` 降级"—— V4 实测**不成立**：clamp 读的是**公开枚举目录**，账号档位表一次都没被问过；同一系统模型 `/v1/models` 声明 `low: null`（说不支持）而出站实发 `reasoning_effort:"low"`。⇒ 这一条从"我方已有"改判为"我方真缺"，列为 P3。
5. **行号更正**：L1 的判定条件在 `stream.ts:168`（不是 167）；`_DATE_SUFFIX` 定义在我方 `matcher.py:206`、执行在 `:215`（我此前写的 `:211` 是注释行）；§0 第 4 行里 `account-pool.ts:890` 指向的是"清除限流"路径，不是判定路径。
6. **新增两条原文没登记的真实缺陷**（实施时并入队列）：① `api/admin_accounts.py:1277 _map_enabled` docstring 写"逐字同一条"却**自算且不传系统模型维**（V3 行为复现，须手改 YAML 才可达）；② `POST …/auto-map` 在实时目录整表失败、**用内置兜底表**生成映射并写库时仍回 200，回执 19 个字段里**没有目录来源位**（V2 抓到）；③ 缓存新鲜度用**墙钟** ⇒ `fetched_at` 在未来即判"新鲜"（V2 实测 `age=0.0 stale=False`），而冷却用 monotonic 天然免疫回拨；④ 同一厂商模型在我方**两套目录里取值不一致 20 处**，出站注入读的是官网声明值（V4）；⑤ 内置目录 `image_input` **默认 False 被当事实**（12/25 条吃默认值，:8300 现报 4 模型 `supportsImages:false`，而 `kimi-k3` 同条目 `only_base64_image=True` 自相矛盾），真机图片照样发出且记成功（V3）。
7. **裁决结果**：采纳 4（L3/L4/L8/L11）· 部分采纳 6（L1/L2/L5/L6/L7/L9）· 不采纳 1（L7 的失败冷却部分 / L5 的取小 / L9 的白名单表与"实拉数据钉测试"）—— 逐条边界见 `dsh-learn-0-verdicts.md` §1。
