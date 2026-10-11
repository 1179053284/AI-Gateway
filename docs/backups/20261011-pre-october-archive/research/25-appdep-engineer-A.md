# 25 · App 依赖与多账号并行判定 —— 研发工程师视角 · Batch A

> 角色问题：**要让调用真跑通，这台机器上到底必须有什么**。判定口径严格区分三件事：
> ① 凭据怎么来（登录/倒库）② 调用期要不要 App **进程** ③ 调用期要不要构造 App 的**产物/字段**。
> 本角色权威依据 = 已能工作的第三方参考实现（DSH 插件，本机只读）+ 本仓既有调研文档 + 本仓代码/落盘凭据形状。
> **全程只读、未发任何真实上游调用**；凡无代码/文档直证处一律写「未验证」。
> 参考源根路径（下文省略前缀 `AI工作站/05-dsh插件/deepseek-harness-codearts/`）；本仓前缀 `Model-Gateway/`。

## 0. 逐产品判定表

| 产品 | D 类 | App 依赖机制(一句话) | 凭据来源(登录/倒库/导入) | 无头刷新可否 | 调用期还须构造什么 | C 类 | 多账号并行阻碍点 | 关键证据(ts 或 md 的 file:line) | 置信度 | 否证条件 |
|---|---|---|---|---|---|---|---|---|---|---|
| `buddy`（CodeBuddy 腾讯） | **D1 首登录依赖** | 登录要在浏览器点 `www.codebuddy.cn/login?platform=ide&state=` 授权，插件轮询取 token；调用期纯 HTTPS+Bearer，零 App 参与 | 插件 external-link 登录 → 本机 2 号 `via=import`（DSH `state.json`/`.credentials.yaml` 倒库） | **可**：`POST /v2/plugin/auth/token/refresh` 带 `X-Refresh-Token`（本机 access 约 28d、refresh 再 +30d） | 归属头族 `X-Domain`/`X-Product-Code`/`X-Product`/`X-IDE-Name/Type/Version`+品牌 UA（缺则后台「使用端」显示 `-`，非拒判据）；`stream:true`；`prompt_cache_key`（命中前缀缓存，实测省 ~17× 积分） | **C0 可并行** | 协议**无设备身份字段** → 账号间无耦合；阻碍点全在我们侧：参考实现账号池**无并发租约**（并发全挤 `candidates[0]`），buddy 还在请求期做余额分档查询 | `src/buddy.ts:5-9`；`src/buddy-oauth.ts:135-163,280-330`；`src/buddy-adapter.ts:1564-1583`；`src/product.ts:96-98`；`docs/research/20-…md:244-253`；`tests/e2e/buddy-pool-probe.e2e.spec.ts:6-12` | 高 | 若同账号被桌面端再次登录后插件 token 即 401/refresh 403（单会话顶号），或 `/v2/chat/completions` 拒缺 IDE 形态头 → 分别升 C2 / 追加构造项 |
| `workbuddy`（国际版） | **D1 首登录依赖** | 与 buddy 同一协议，仅域名/`platform=workbuddy-ai` 不同；登录 URL 额外要 `version`+`loginSessionId`(UUID) | 同上；本机 2 号 `via=import` | **可**：同一 refresh 端点（本机 access 到期 2027-09 ≈1 年，`refresh_expires_at` 与之同值） | **🔴 硬判据：`messages[0]` 必须 `role:'system'`**，否则 `400 + code 11128` 且被伪装成「安全策略拦截」；UA 按模型族分档（`gpt-/gemini-/claude-` 走国际形态、`glm-/hy/kimi-/minimax-` 走国内形态）；国际版**无签到端点** | **C0 可并行** | 同 buddy（无设备字段；池无租约） | `src/product.ts:370-406`；`src/buddy-oauth.ts:517-531`；`src/account-probe.ts:86-95`（实测表） | 高 | 同上；另若「首条必须 system」实为该账号态/网关版本特有，换号后消失 → 该构造项降级 |
| `lobsterai`（有道） | **D1 首登录依赖** | 登录=插件在 `127.0.0.1:随机端口` 起回调服务器 + 浏览器在 `lobsterai.youdao.com/portal` 登录回跳换 token；**调用期无任何进程**（参考实现明确「不需要反代、背后没有任何反代进程」） | 插件 local_callback 两步（本机回跳 + 粘贴回调）；本机 2 号 `via=import` | **可**：`POST /api/auth/refresh`（**不带 Authorization**，体 `firstKeyfrom/latestKeyfrom/version/uuid/userId`，两个 keyfrom 用凭据里**存储的原值**不取当前时刻） | `X-LobsterAI-Client-Capabilities`（`kimi-k3-agentic-v1` 决定目录是否含 kimi-k3；`thinking-level-control-v1` 决定 `reasoning_effort=off` 不 HTTP 500）+ `X-LobsterAI-Client-Version`（动态取 `api-overmind.youdao.com`，兜底 `2026.9.4`，服务端不强校验）；**`stream` 恒 true**（`false`→500）；**不得**带腾讯系归属头 | **C1 需每账号设备身份唯一** | 身份字段 `uuid`（安装标识，「服务端识别同一安装的依据」，续期原样回传）；本机 2 号 uuid 互异（已按 §15.1 硬约束 1 落地）；厂商是否真的按 uuid 分组/限流**未验证** | `src/lobsterai-oauth.ts:95-115,340-350`；`src/lobsterai.ts:103-109,305-341,492-545`；`src/lobsterai-product.ts:83-129`；`src/lobsterai-adapter.ts:13,999-1001`；`docs/lobsterai-integration-plan.md:131-144`；`coding/model_gateway/accounts/registry.py:89-113` | 机制=高；C1 是否厂商强制=**未验证** | 两账号临时共用同一 uuid 仍能各自续期+调用 → 降 C0；或 refresh 拒插件 uuid / 调用要求真实安装指纹 → 升 D3 |
| `qoder`（国际版 api2.qoder.sh） | **D3 离线产物依赖** | 推理**只认加密端点** `POST api2.qoder.sh/algo/api/v2/service/pro/sse/agent_chat_generation?Encode=1`，body 与 `Authorization: Bearer COSY.<载荷>.<签名>` 由 **298KB WASM**（从本机 Qoder 安装提取、随插件分发）产出；要的是**产物**，不要 App 进程 | 插件 device_code(PKCE) 登录：`qoder.com/device/selectAccounts?…&machine_id=<插件自造随机 UUID>` → 浏览器授权 → 轮询 `/api/v1/deviceToken/poll`；本机 1 号 `via=import` | **可**：`/api/v1/deviceToken/refresh` 体 `{refresh_token, machine_id}`（本机 access 约 28d、refresh 再 +330d）；⚠️ 服务端是否校验 machine_id 与设备一致性 = 参考实现自记「本设计最大未验证假设」 | `uid`（缺 → `Signature invalid (101)`，登录/`userinfo` 补齐并回写）；`business:{type:'agent'}`（缺 → 恒路由到故障节点回 `[FAIL]node…Execution failed`）；顶层 `tools`（缺 → 模型正文 XML 臆造调用）；**WASM 返回的头必须原样透传**（普通 Bearer 覆盖 → 403）；`COSY_VERSION=1.1.49`+`clientMetadata` 进签名载荷；目录 key（`qfmodel`…）发公开端点必 `Unsupported model` | **C1 需每账号设备身份唯一** | `machine_id` 「参与服务端的设备绑定」且进签名载荷；WASM 上下文「实例非线程安全，一个账号一个实例」→ 并行须**每账号独立 context**；参考实现的池同样无租约 | `src/qoder-wasm.ts:8-18,550-581,597-706`；`src/qoder-adapter.ts:1-22,655-735,1018-1036`；`src/qoder-product.ts:180-230,300-346,442-445`；`src/qoder.ts:74-95,142-153,285-300`；`coding/model_gateway/upstream/qoder/out.py:1-36,105-130`（`SIGNER_FACTORY=None` → fail-closed） | 机制=高；「推理零 App 进程」=中高（DSH 走通但探针为人工闸门、无输出留档） | 若 COSY 载荷含只有本机 Qoder 会话才有的运行时密钥 → 升 D2；若 Qoder 升级后旧 WASM 恒 `Signature invalid` 必须重取产物 → 仍 D3 但「产物版本时效」成硬约束；若服务端拒绝插件自造 machine_id → 升 D3-强（须复制 App 数据目录身份） |
| `qodercn`（中国版 gateway.qoder.com.cn） | **D3 离线产物依赖（无备选路径）** | 同国际版协议，但 CN **没有可用公开端点**（实测 `gateway.qoder.com.cn/model/v1/chat/completions` 与 `openapi…` 均 503）→ 只能走加密端点，WASM 是唯一通道 | 插件 device_code 登录（`qoder.cn` + CN 专属 `clientId`）；本机 5 号 `via=import`；**且 5 号中 4 号的 uid 命中本机 `~/.qoder-cn/.models/{uid}/catalog-v6`** → 这些号确实在本机 Qoder CN 桌面端登录过（首登录面=D1） | **可**：同 `/api/v1/deviceToken/refresh` 形态（CN openApi 域）；同「machine_id 一致性未证」的限制 | 同 qoder 全部构造项；另三处 CN 特有未定论项：`clientMetadata` 用 **CLI 身份 `client_type:'5'`**（CN 桌面端自己用 `Fh`=10/app/app/app）、`session_type` 默认 `qodercli` vs 国内 `qoder_work`、CN 是否复用国际版那份 WASM —— 参考实现把它们列为探针嫌疑项 | **C1 需每账号设备身份唯一** | 同 qoder；本机 5 号 `machine_id` 全互异（哈希核对），但**并发调用未实测** | `src/qoder-product.ts:580-604`（CN 常量 + 503 实测注）；`tests/e2e/qodercn-chat-probe.e2e.spec.ts:1-30,74-120`；`coding/model_gateway/accounts/registry.py:131-142` | 机制=高；CN 三未定论项=**未验证** | 同 qoder；额外：若 CN 拒国际版那份 WASM（探针注 1）→ 必须从 CN runtime 另提一份产物（仍 D3，但按产品各存一份） |

**口径说明（防误读）**：D1/D3 的差别只在 ①（要不要人点一次浏览器/装一次 App）之外多了「③要 App 的离线产物」。就**运行期进程**而言，Batch A 五产品在参考实现里**全部为「零 App 进程」**：全仓 `127.0.0.1` 只出现在 OAuth 回调与本地登录页（`src/login.ts:219,348`、`src/lobsterai-oauth.ts:348`、`src/trae-oauth.ts:503`），无任何「连 App 本地端口 / 走 IPC」的推理通道；`spawn` 仅三处：`src/login.ts:125,135`（打开浏览器）、`src/qoder-machine.ts:421,447`（`runtime-info` 取设备身份，**只服务 `/sash/` 积分领取**，唯一调用方 `src/qoder-credits.ts:198`，推理路径零调用）、`src/zcode-captcha.ts:551`（Batch B）。

## 1. buddy / workbuddy（同族）

**DSH 证据链**
1. 登录：`POST {endpoint}/v2/plugin/auth/state?platform=<ide|workbuddy-ai>` → 拿 `state`+`authUrl`（`src/buddy-oauth.ts:135-163`，无需认证，只带 `X-No-*` 与产品 UA）→ 浏览器打开 `https://www.codebuddy.cn/login/?platform=ide&state=…`（`src/buddy.ts:7`）→ `GET /v2/plugin/auth/token?state=` 轮询（`code 11217` 未就绪继续，1s/5min，`src/buddy.ts:31,170-215`）→ `GET /v2/plugin/login/account?state=`（`code 12151`）。WorkBuddy 的 `authUrl` 额外追加 `version=5.5.2`+`loginSessionId`(客户端 UUID)（`src/buddy-oauth.ts:517-531`、`src/product.ts:405-406`）。
2. 续期：`POST /v2/plugin/auth/token/refresh`，头 `Authorization: Bearer <旧 access>` + `X-Refresh-Token` + `X-Auth-Refresh-Source: ide-main`（`src/buddy-oauth.ts:288-330`）；401/403 或 message 含 expired/invalid → `RefreshTokenExpiredError`（终态，停止调度）。**全程无 App**。
3. 推理：`POST {product.endpoint}/v2/chat/completions`（`src/buddy-adapter.ts:1583`），头集合见 `:1564-1581`（`attributionHeaders()` + `Authorization` + `Accept: text/event-stream` + `X-Domain` + `X-Product-Code` + `X-Agent-Purpose: conversation` + `X-IDE-Name/Type/Version` + `X-Product` + UA 按模型族）；响应裸 OpenAI SSE（`docs/research/21-….md:138`）。
4. 模型目录：远端 `GET /v3/config`（+ scoped 端点）→ 兜底表 `CODEBUDDY_FALLBACK_MODELS` / `WORKBUDDY_FALLBACK_MODELS`（`src/product.ts:180-283,295-355`）。兜底表**离线取值来自 IDE 本地缓存** `~/.workbuddy-ai/local_storage/*.info`（`src/product.ts:129-136,289`），但运行时**不读**该目录（全仓 `workbuddy-ai` 仅出现在注释与 `platform` 字面量）。
5. 进程外消费先例：`tests/e2e/buddy-pool-probe.e2e.spec.ts` 直接解析 `~/.dsh/settings.yaml`+`.credentials.yaml` 造 `BuddyAdapter` 发真实请求；`buddy-models.e2e.spec.ts:9-12` 明确「用真实凭据访问真实后端」。

**机制推断**：CodeBuddy 系把「IDE 插件登录」做成了**公开的 plugin 协议**（`/v2/plugin/*`），任何持凭据的 HTTP 客户端都能冒充该形态；App 只是这条协议的一个普通消费者，既不签发短期独有材料、也不参与续期。故 D1，运行期 D0 等价。
**未确定项**：① 腾讯是否对「同一账号多路并发」有会话级限制（无代码/注释证据）；② 归属头缺发是否只影响归因（现证据仅支持「显示 `-`」，`src/product.ts:96-98`）；③ 本仓 `buddy/out.py` 取证清单承认 **UA 按模型族分档未逐档取证**（`coding/model_gateway/upstream/buddy/out.py:16`）。

## 2. lobsterai（有道）

**DSH 证据链**：`src/lobsterai-oauth.ts:95-115`（`redirect_uri` 必须 `http://127.0.0.1:{port}/auth/callback`）+ `:340-350`（随机空闲端口、只绑 127.0.0.1）→ 浏览器 portal 登录 → 进程内 `POST /api/auth/exchange`（无 Authorization，`src/lobsterai.ts:492-503`）；续期 `POST /api/auth/refresh` 体见 `src/lobsterai.ts:305-341`；推理 `POST {apiBase}/api/proxy/v1/chat/completions`，头 `src/lobsterai.ts:517-530`（4 基础头 + 两个 `X-LobsterAI-Client-*`）；能力声明的**实测后果**（不带 capabilities → 目录 25 个、无 kimi-k3；`reasoning_effort:"off"` 不带 `thinking-level-control-v1` → 服务端 500）记在 `src/lobsterai.ts:526-544`、`src/lobsterai-product.ts:100-116`。反代进程非必需的原话在 `docs/lobsterai-integration-plan.md:131-144`。

**机制推断**：凭据是自持的 `access_token/refresh_token` + 一组**安装级标识**（`uuid`/`first_keyfrom`），全部落盘可搬；服务端只在**续期**时读这组标识（推理只认 Bearer + 客户端能力头）。因此 App 既不参与签发也不参与调用 —— D1。`uuid` 由客户端 `randomUUID()` 生成（本仓 `lobsterai/login.py:181-209` 照抄并加跨账号查重），说明它是**可自造的虚拟身份**，不是硬件指纹。
**未确定项**：`uuid` 在服务端究竟参与什么（分组/风控/签到去重）无任何代码证据 → C1 判据来自「协议把它当安装身份 + 本仓 §15.1 硬约束」，非厂商实测。

## 3. qoder / qodercn

**DSH 证据链**
1. 两条推理端点（`src/qoder-adapter.ts:5-20` 表格）：公开 `api2-v2.qoder.sh/model/v1/chat/completions`（纯 Bearer，只认通用名）vs 加密 `api2.qoder.sh/algo/.../agent_chat_generation?Encode=1`（认目录 key，`qfmodel` 等 17 个实测可用，`src/qoder-product.ts:311-326`）。**CN 公开端点实测 503**（`src/qoder-product.ts:593-601`）→ CN 无退路。
2. 加密通道：WASM 随插件分发（`src/qoder-wasm.ts:16-18`，文件 `src/qoder-auth-wasm.wasm` 298KB 实测存在），`QoderEncryptedInfer.create({uid, security_oauth_token, machineId, metadata, host})` → `prepareInfer()` 返回 `{url, headers, body}`（`:599-706`），适配器仅补 `Accept` 后原样发（`:1018-1036`）—— **零 App 进程、零本地端口、零 IPC**。
3. 产物提取路径：`scripts/extract-qoder-wasm.mjs:1-25`（「Qoder 升级后签名协议可能变化，判据是对话报 `Signature invalid`」；默认根 `LOCALAPPDATA\Programs\Qoder`，**Windows-only**，mac 需手设 `DSH_QODER_HOME`）；`src/qoder-product.ts:344-346` 兜底目录表来源 = 本机 `~/.qoder/.models/{uid}/catalog-v6` 经 `model_cache_decrypt` 解密。
4. 设备身份 `runtime-info`：只用于 `/sash/`（积分/活动），唯一调用方 `src/qoder-credits.ts:198`；消融表证明缺 `Cosy-MachineToken`+`Cosy-MachineType` 时服务端不下发「可领取」活动（`src/qoder-machine.ts:26-40`）；主路径 spawn、退路读 `machine_token.json`（可能陈旧 179 天）。
5. 本机事实：网关侧 `SIGNER_FACTORY=None` → 未接线即 `UpstreamError(fail-closed)`，绝不降级公开端点（`coding/model_gateway/upstream/qoder/out.py:60-73,105-120`）。

**机制推断**：Qoder 的门槛是**密码学产物（WASM 加密+COSY 签名）**而非进程或活动会话；该产物一旦离线拿到就长期可用，直到厂商换版。所以是 D3 而不是 D2 —— 「必须装有/曾装过 Qoder 并从中提取一份 wasm」，但「此刻 App 可以不存在」。本仓把这条通道留作注入缝而非伪造签名，是对的工程处置。
**未确定项**：CN 的 CLI 身份/`session_type`/wasm 复用三点；插件自造 `machine_id` 是否被服务端设备绑定校验（`src/qoder.ts:74-79` 已声明「不复制硬件指纹」的风险）。

## 4. 这台机器上必须有什么（工程清单）

| 产品 | 必须存在 | 本机现状 |
|---|---|---|
| buddy / workbuddy | 一份含 `refresh_token` 的凭据 + 出网到 `copilot.tencent.com` / `www.workbuddy.ai` | 凭据 2+2 号在 `coding/data/upstream/*/accounts/`；无本地产物依赖 |
| lobsterai | 凭据 + 每账号唯一 `uuid` + 出网 `lobsterai-server.youdao.com`（版本号另有 `api-overmind.youdao.com` 取不到走兜底） | 2 号、uuid 互异；本机未装 LobsterAI（不影响） |
| qoder / qodercn | 凭据（含 `uid`+`machine_id`）**+ 一份与线上签名匹配的 `qoder_auth_wasm`（或等价 Node 桥）**；`/sash` 领取才需要 `machine_token.json` 或可 spawn 的 `runtime-info` | wasm 只有参考源那份（`src/qoder-auth-wasm.wasm`），**本仓未 vendor 任何 .wasm**；`machine_token.json` 在本机**不存在**（`~/Library/Application Support/Qoder{,Work}/SharedClientCache` 无该文件）→ `flow.py::machine_identity()` 现返回 `None`（`coding/model_gateway/upstream/qoder/flow.py:233-271`）；但 `~/.qoder-cn/.bin/runtime-info-darwin-arm64-6153434d1073ca6f/` **存在**（DSH 主路径 spawn，本仓只实现了磁盘退路 = 已知缺口）；`/Applications/{Qoder CN,CodeBuddy CN,WorkBuddy,WorkBuddy AI}.app` 均在，且 `Qoder CN.app/.../app.asar.unpacked` 下**未**解出 `@qoder-ai/qoder-agent-sdk/_worker`（参考脚本按 Windows 布局找路径） |

## 5. 最可能与其他角色分歧的地方

1. **buddy/workbuddy/lobsterai 判 D1 还是 D0**：机制上运行期零 App（可写 D0），但「凭据只能经一次浏览器授权取得」是硬事实（三产品都没有账密/短信纯程序通道）→ 我按「首登录要人点浏览器」判 D1。若另一角色只看 `upstream/*/out.py` 的调用构造会判 D0；两者不冲突，**必须写清是 ① 还是 ② 的口径**。
2. **qoder 判 D3 还是 D2**：看到 `qoder-machine.ts` 里 `spawn`/`execFileSync` 就判「要 App 进程」是**错的** —— 该 spawn 的对象是 App 数据目录里单独一个 `runtime-info` 二进制（UMID 模块，不是桌面端进程），且**只服务 `/sash/` 领取**，推理路径零调用（唯一调用方 `qoder-credits.ts:198`）。
3. **lobsterai 的 C 类**：可能被判 C0（uuid 可自造、厂商未证实校验）或被从 trae 的「同 `device_id` 会被『该设备已签到』拦截」（`src/trae.ts:29,1299`）**外推**成强 C1。两者都过头，我的 C1 附「厂商行为未验证」。
4. **「无头刷新可行」≠「App 不会顶号」**：refresh 端点纯离线可用有代码直证；但「桌面端再登录会不会让插件的 refresh_token 失效」**无任何证据**，谁写成已验证即为编造。
5. **workbuddy 的 `messages[0]` 必须 system** 是实测硬判据（`400+11128`，且错误文案伪装成安全策略拦截，`src/account-probe.ts:86-95`）；只看 `buddy-adapter` 主流程的角色容易把它当成「可选归属头」而漏判——本仓是否已落地需另行核对。
6. **qodercn 的 `via=import` + uid 命中本机 `~/.qoder-cn/.models/`**：说明这批号的**首登录极可能由桌面端完成**。若另一角色据此判 D2/D3-首登录混淆，需要区分「首登录用了 App」与「调用要 App」——后者无证据。

## 6. 必须有实测才能定论的地方（具体怎么测）

> 归实测角色执行；**本角色未发任何真实上游调用**。以下命令只观察返回码/头部，不落凭据明文。

1. **App 进程必要性总判据（五产品通用）**：`pgrep -fl "Qoder|CodeBuddy|WorkBuddy|LobsterAI"` 确认**无相关进程**（且临时把 `/Applications/*.app` 改名，杜绝「顺手起了 App」），再对 `:8300` 各发一次最小 chat（`messages[0]` 带 system）。预期 `200 + data:` 帧 → 判 D1/D3（运行期零进程）成立；任何一路 `401/403` 且**同凭据在同刻桌面端可用** → 该路升 D2。
2. **qoder/qodercn 通道能否走通（当前最大未知）**：先用 Node 桥把参考源 `src/qoder-wasm.ts` 编译产物挂到本仓 `SIGNER_FACTORY`（**不重签、不改算法**），对免费模型各发一次：国际版 `qmodel_38max` / CN `qfmodel`（`is_free:true`，不消耗积分）。判读：`200`+SSE= D3 且那份 wasm 通用于两站；`403 Signature invalid (101)`=凭据缺 `uid`；`[FAIL]node:…Execution failed`=缺 `business:{type:'agent'}`；CN 报 session 相关=换 `session_type=qoder_work`（`DSH_QODERCN_SESSION_TYPE` 同义覆写）再报 client 相关=`clientMetadata` 换 CN 桌面端那组 `10/app/app/app`；`404`=host 错。四嫌疑顺序见 `tests/e2e/qodercn-chat-probe.e2e.spec.ts:110-120`。
3. **无头刷新的真实终态**：对每产品各取一个账号做「refresh 一次 + 用旧 refresh_token 再 refresh 一次」。预期第一次 200、第二次 401/403（若厂商做一次性旋转）→ 说明**并发双刷会烧号**，网关必须做 refresh 单飞；qoder 侧另断言 `POST {openApiBase}/api/v1/deviceToken/refresh` 返回 `200`（`4xx` 非 401 即服务端校验了设备一致性，`machine_id` 需改从 App 派生 → 升 D3-强）。
4. **多账号并行（C 判据）**：同产品 N=2（qodercn 用 5）账号**同时**各发一条不同前缀请求，逐账号记录首帧与 usage；随后**串行复跑同一组**作对照。观察三点：① 是否出现「后启动的账号请求把先启动的顶成 401」（=厂商单会话/设备互斥 → C2）；② 是否只在并发下出现限流/排队码（buddy `6004`、qoder `10605`、lobsterai `RATE_LIMIT`）；③ qoder/qodercn 是否共享单个 WASM context 导致串行化/错帧（验「一账号一实例」是否必需）。
5. **lobsterai 的 C1 是否厂商强制**：**仅在测试号/可弃号**上做——把两账号的 `uuid` 临时改成同值后各自续期+调用一次，观察 refresh 是否 4xx、当日签到/额度是否互相占用。严禁拿在 :8300 正常服役的 2 号做（改前先备份凭据目录）。
6. **qoder 积分领取的设备头**：本机 `machine_identity()` 返回 `None`，先跑 `/admin` 的 qoder `credits.status` 看是否恒 `campaigns:[]`/误报「今日已领取」；再验证本地子进程 `~/.qoder-cn/.bin/runtime-info-darwin-arm64-*/runtime-info 3 --account-stdin`（stdin 喂 `{"account":""}`）在无桌面端运行时能否输出 `machineToken/machineType`（**参数顺序必须是 `[environment, '--account-stdin']`**，漏 `3` 会拿到另一套 fallback 身份，`src/qoder-machine.ts:355-378`），并核对该值与本机 Qoder CN 实际出站是否一致。
