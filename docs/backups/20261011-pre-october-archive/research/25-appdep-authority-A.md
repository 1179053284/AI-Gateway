# 25 · 外部权威证据面 · Batch A（buddy / workbuddy / lobsterai / qoder / qodercn）

> 角色 = 通用权威角色（外部证据面）。本轮**只读**：不改动既有文件、不发真实上游调用、不读任何凭据。
> 判据口径由主 agent 定义（D0–D4 / C0–C3），本文只做「外部权威能说到哪一步」的诚实陈述。
> 证据等级标记：**权威** = 厂商官方文档/条款；**二手** = 第三方开源实现或社区实证；**推断** = 由前两者推出。

## 一、逐产品判定表

| 产品 | D 类 | App 依赖机制(一句话) | 官方是否提供对外 API | token/会话官方策略 | C 类 | 多账号并行官方限制或社区实证 | 关键证据(URL 或 file:line) | 证据等级(权威文档/二手/推断) | 否证条件 |
|---|---|---|---|---|---|---|---|---|---|
| `buddy`(CodeBuddy) | **D1** | 登录 = 服务端下发 `authUrl` 的浏览器授权页 + 免认证轮询取 token，调用期只需 Bearer + UA/产品码头，无任何本机进程 | **有，但不是这条通道**：开放平台 OAuth2（Client Credentials/Authorization Code）只开 BackgroundAgent 与企业 OpenAPI；CodeBuddy Code 另有 `CODEBUDDY_API_KEY`/`CODEBUDDY_AUTH_TOKEN` 无头用法 | 开放平台 `expires_in=3600`（权威）；`/v2/plugin/auth/token/refresh` 存在（本仓已实现 `buddy/protocol.py:41-42`），有效期官方未公布 | **C0**（未见互踢/设备唯一性条款） | 官方无「每账号设备身份」要求；第三方 `workbuddy2api` 以**多 session 文件**跑多账号、声明「网关侧自动刷新 token 与签到」 | https://www.workbuddy.cn/apiDocs/CodeBuddy-Open-Platform-Handbook.md ；https://www.codebuddy.ai/docs/zh/cli/env-vars ；https://pypi.org/pypi/workbuddy2api/json ；`coding/model_gateway/upstream/buddy/protocol.py:35-42,158-226` | 权威（官方手册/条款）+ 二手（PyPI 实证） | 若实测出现「同账号二次登录使旧 token 失效」或 401 伴随设备绑定提示 → 翻 C2/C1 |
| `workbuddy`(国际版) | **D1** | 与 `buddy` **同族同协议**（差异只有平台码/UA/域名），同一浏览器授权 + 轮询取 token | **有**：CodeBuddy Code「HTTP API (Beta)」= 本地守护进程 `127.0.0.1:<port>`、`X-CodeBuddy-Request: 1`、`gateway_session` Cookie 30 天（这是它自己的对外面，不是账号内部模型的 OpenAI 端点） | 同上；官方 CLI 文档给出 `CODEBUDDY_AUTH_TOKEN` 优先级高于 apiKeyHelper/API Key | **C0**（协议面无设备字段，`20 §2.7` 与外部一致） | 同 `buddy`；风险面另有：本机客户端包内置腾讯**图盾**风控 SDK（native/turing-sdk + TuringShield.bundle）→ 服务端风控可能取设备指纹（**推断**） | https://www.codebuddy.ai/docs/zh/cli/http-api ；https://cloud.tencent.com/document/product/1831/137064 ；本机只读 `/Applications/WorkBuddy AI.app/Contents/Resources/TuringShield.bundle` | 权威 + 二手；图盾用途属**推断** | 若图盾只做崩溃/反外挂不参与推理风控、且实测多账号并行无 429/封禁 → 维持 C0 |
| `lobsterai`(网易有道) | **D1** | 门户 `lobsterai.youdao.com` 浏览器登录 + 本机回跳 `127.0.0.1:{port}/auth/callback` 换 JWT；调用期纯 HTTPS Bearer | **无**官方开放 API/OpenAI 兼容端点（官方只有桌面 Agent + 门户）；**官方客户端本身开源**（`netease-youdao/LobsterAI`，6.0k star，Electron+OpenClaw 运行时） | 官方文档未公布；社区逐字实测：**AT = JWT ≈30 天、RT ≈180 天、续期即换发新 RT**，AT 距过期 <7 天滚动续期 | **C0**（无互踢条款/证据） | 社区多账号池实证（Go 反代多账号按积分负载均衡 + 429 软冷却 60s / 额度耗尽 12h）；唯一硬约束在**门户层**：同一浏览器登录第二个号前须先退出第一个号（建议无痕页），非账号级互踢 | https://github.com/netease-youdao/LobsterAI ；https://github.com/xinxinshuhao-create/lobsterai2api （master README L91-98）；https://github.com/L0NE-6/LobsterAI-AutoCheckin ；https://qianling.pw/lobsterai2api/ ；`upstream/lobsterai/const.py:22-49,80-85` | 权威（官方开源仓）+ 二手（三家社区实现一致） | 若出现「新设备登录后旧 refresh_token 被拒（40100/40101）」→ 翻 C2 |
| `qoder`(国际版) | **D3**（本仓所选 IDE 加密推理通道）/ **D1**（官方 CLI 通道） | 推理请求须经 COSY 签名（客户端 WASM 导出物 → 可离线复刻），但**不要 App 进程**；官方 CLI 明确支持无 GUI/CI：打印登录 URL 或直接用 PAT | **有**：Qoder CLI `Personal Access Token`（控制台 Settings → Personal Access Tokens，`pt-` 前缀、可选 scopes 与过期时间）；Cloud Agents API（PAT/SAT，`openapi.qoder.sh`）；自定义模型 BYOK（不占 Credits） | CLI「完成浏览器登录后**后台自动刷新令牌**」；社区对设备码令牌实测「一次性 30 天资产、`refreshable:false`」（与本仓 refresh 端点相左，见 §三） | **C1** | 请求头族 `Cosy-MachineId` + `Cosy-Machinetoken` **成对**且源自授权握手 → 官方按设备身份校验；社区已用纯 Python 复刻签名（无 wasm）；多账号并行由社区实现（每 PAT 独立会话/目录缓存、`qoder-2/_3` 多账号），但官方论坛证实「伪造设备指纹绕过一机一号试用 + 号池轮转 + 卡密贩卖」正被打击（拟换密钥、IP 过滤、服务端背书设备号） | https://docs.qoder.com/zh/cli/authentication ；https://docs.qoder.com/zh/cli/model ；https://qoder.com/account/integrations ；https://forum.qoder.com/t/qoder-is-being-destroyed-by-cybercriminals-qoder/10338 ；https://blog.csdn.net/2401_88756258/article/details/163055114 ；`upstream/qoder/out.py:10-20` | 权威（官方文档/条款/论坛官方回执）+ 二手（社区实现） | 若实测证明 COSY 头族可随意自造且服务端不校验唯一性（多号共用同一 MachineId 不被拒）→ 降级 C0 |
| `qodercn`(中国版) | **D3** | 同上：`gateway.qoder.com.cn` 的签名 SSE 通道，签名算法可离线复刻，**不需要桌面端进程** | **有（同一套体系的 CN 分身）**：`qoder.com.cn/account/integrations` 创建 PAT（形如 `pt-xxxx_019exxxx-…`）→ `openapi.qoder.com.cn/api/v1/jobToken/exchange`；Qoder CN CLI 官方支持无图形界面打印登录 URL、后台自动刷新 | CN CLI 令牌自动刷新（权威）；PAT 创建时配置过期时间（权威）；CN 与 intl **token/端点不通用**（与本仓 `_guard_family` 一致，`upstream/qodercn/product.py:10-12`） | **C1** | 第三方 `qoder2api` 即打 CN 侧 QoderWork 私有协议，声明「任何 OpenAI 客户端带你的 PAT 即可调用**全部模型额度**」、多 PAT 并发隔离；官方 FAQ 权威条款：**Pro 试用资格每人一次、注册多号将被撤销、不支持虚拟机**；服务条款 §2.3 账号仅供个人使用、禁共享凭证 | https://docs.qoder.cn/cli/authentication ；https://help.aliyun.com/zh/lingma/qodercli-cn/user-guide/model ；https://github.com/fengyinxia/qoder2api ；https://docs.qoder.com/zh/troubleshooting/common-issue ；https://qoder.com/zh/product-service | 权威 + 二手 | 同上：设备头不被服务端校验则降 C0 |

---

## 二、逐产品外部证据与判定

### 1) `buddy` = CodeBuddy（copilot.tencent.com）

**外部证据摘录**
- 官方《CodeBuddy 开放平台》手册（`https://www.workbuddy.cn/apiDocs/CodeBuddy-Open-Platform-Handbook.md`）：「通过开放 API 和 **OAuth 2.0** 授权框架，让第三方应用能够安全、高效地集成 CodeBuddy 核心功能」；`POST https://copilot.tencent.com/oauth2/token` → `{access_token, token_type: Bearer, expires_in: 3600, refresh_token}`；授权页 `https://tencent.sso.copilot.tencent.com/authorize`。
- 官方 OpenAPI（同站 `api.yaml`，323KB）首部约束原文：「本文档涉及的**所有 OpenAPI 接口仅支持 admin 开发平台创建的企业级应用（应用身份）调用，不支持个人 API Key 调用**；个人 API Key 调用任意接口会返回 **401 Authorization Required**」——12 大域全是企业**管控面**（成员/License/用量/模型管理/日志/可观测），**没有 `/v2/chat/completions`**。
- 官方 CLI 文档（`https://www.codebuddy.ai/docs/zh/cli/env-vars`）：`CODEBUDDY_API_KEY`「API 密钥。设置此密钥用于模型接口调用」、`CODEBUDDY_AUTH_TOKEN`「CodeBuddy 平台认证令牌，用于所有平台接口调用」、`CODEBUDDY_BASE_URL`「覆盖 API 端点地址」；`CODEBUDDY_RETRY_WATCHDOG`「开启无人值守 / CI 场景的无限重试模式」。IAM 页（`.../cli/iam`）：优先级 `CODEBUDDY_AUTH_TOKEN > apiKeyHelper > CODEBUDDY_API_KEY`；「访问对应平台获取你的 API Key：海外版 `https://www.codebuddy.ai/profile/keys`」；apiKeyHelper 令牌「默认缓存 5 分钟」；文档导航含独立「无头模式」章节。
- 官方条款（`https://www.codebuddy.cn/agreement/`，2025-09-26 版）§8.2：禁止「(2) 反向工程、反向汇编、反向编译」「(5) 通过修改或伪造指令、数据，变动软件的功能或运行效果」「**(6) 通过非腾讯云授权的第三方软件、插件、外挂登录或使用本软件**」；§8.4 处罚含「警告、限制功能、删除屏蔽内容、**封号**」。
- 社区实证（PyPI `workbuddy2api` 2.0.6，README 全文）：国内 `https://copilot.tencent.com` / 国际 `https://www.codebuddy.ai` 两套 profile，会话文件 `~/.codebuddy-session.json` / `~/.codebuddy-global-session.json`；「首次使用需 `--login`，浏览器登录后自动启动」；日常「自动读取登录态」；「401 authentication failure → Token expired; log in again」；多账号 = 不同 `--session-file`；并给出**风控实证**：不开 `--desensitize` 时「几乎每个请求都会被审核拦截」，典型错误 `{"message":"内容违规","type":"content_policy_violation"}`。

**与「必须打开 App 才能调用」这一假设的关系**：**不支持该假设**。官方 CLI/CI 通道 + 社区反代两条独立证据都把「首登录（浏览器）+ 之后纯 HTTP」坐实；桌面端在调用期零参与。要区分的是：官方 OAuth 开放平台开的是 **Agent/管控面**，不是账号权益内的 `/v2/chat/completions`，所以「官方有 API」≠「本仓通道被官方授权」——本仓通道恰好落在 ToS §8.2(6) 的禁止表述内。

**未确定项**：① plugin token 的官方有效期/是否轮换；② 同账号多设备并发是否有互踢或并发限流（无任何外部条款或实证）；③ `profile/keys` 出来的 Key 究竟扣订阅权益还是走公开计费（TokenHub），外部文档未写。

### 2) `workbuddy` = WorkBuddy 国际版

**外部证据摘录**
- 品牌同源直接可见：CodeBuddy/WorkBuddy **共用同一套 VitePress 文档站**，按 hostname 切品牌（`workbuddy.cn` / `workbuddy.ai` → `data-brand=wb`，`codebuddy.*` → `cb`），取源 `https://www.codebuddy.ai/docs/zh/cli/env-vars` 响应头脚本原文。
- 官方《CodeBuddy Code HTTP API》（`https://www.codebuddy.ai/docs/zh/cli/http-api` + 腾讯云文档 `https://cloud.tencent.com/document/product/1831/137064`）：需要显式启动本地进程（`--serve`，默认 `127.0.0.1:8080` 形态）、「`--serve` 默认开启密码认证」、「所有 API 请求（除豁免路径外）必须携带自定义请求头 `X-CodeBuddy-Request: 1`」、「服务端会下发有效期 **30 天**的 `gateway_session` Cookie」；文档明确「**不暴露云端订阅推理端点**」，模型调用由 run/job 间接触发；该服务「作为独立后台守护进程运行，无需原生桌面应用」。
- 社区：`workbuddy2api` 的 `--global` 模式即「国际版 CodeBuddy 后端」，登录/刷新/目录与 `buddy` 同机制；教程侧（`https://cloud.tencent.com/developer/article/2735030`）新用户路径是「官网下载客户端 → 微信扫码或手机号登录」，说明**首登录有 App 与浏览器两条路**，而调用期不需要。
- 本机只读证据：`/Applications/WorkBuddy AI.app`（`com.workbuddy.workbuddy-ai`，CFBundleShortVersionString **5.6.2**）内含 `Contents/Resources/TuringShield.bundle` 与 `Contents/Resources/app.asar.unpacked/native/turing-sdk/{build,index.cjs,package.json}` = 腾讯图盾风控 SDK 以原生模块随包发布。
- 协议面与本仓一致：`coding/model_gateway/upstream/workbuddy/product.py:5-13` 声明「登录同 buddy、共用后端协议；**无设备标识**」，与外部（`20 §2.7`：buddy/workbuddy 无设备指纹字段）互证。

**与该假设的关系**：**不支持**。国际版走 `buddy` 同一 D1 机制。注意别把两件事混一条：官方的「HTTP API (Beta)」是**本地 CLI 网关自己的 REST 面**（若走它才是 D2——必须有 `--serve` 进程），而本仓走的是账号 token + 云端 `/v2/chat/completions`（D1）。

**未确定项**：① 图盾 SDK 是否参与推理请求的风险评分（只能靠实测）；② 国际版是否有与国内版不同的并发/设备政策；③ `gateway_session` 30 天只适用于本地 API，不能外推到 plugin token。

### 3) `lobsterai` = 网易有道 LobsterAI

**外部证据摘录**
- **官方产品本身开源**：`https://github.com/netease-youdao/LobsterAI`（6084 star，pushed 2026-10-01，homepage `https://lobsterai.youdao.com`），README：「The first open-source desktop-grade Agent among major Chinese tech companies, built by NetEase Youdao」、Electron 43；架构叙述「Cowork is the product/session layer. **OpenClaw is the runtime and gateway underneath it**」，并列出 `src/main/libs/openclawConfigSync.ts` 负责「Renders LobsterAI providers, models, agents… into OpenClaw config」→ 桌面端内含**本地 gateway 进程**（那是它自己的执行面，与云侧账号推理 API 不是一条路）。
- 第三方反代（`https://github.com/xinxinshuhao-create/lobsterai2api`，MIT，85 star，2026-10-01 仍在更新）README：「OpenAI-compatible API bridge for LobsterAI — multi-account pool with credit-based load balancing, SSE streaming, and **automatic token refresh**」；「OAuth login — **local callback server, browser-based login**, auto-save credentials」；「Token refresh — JWT expiry parsing, **proactive refresh 10min before expiry**, session death auto-disable」；「Error classification — **hard credit cooldown 12h, 429 soft cooldown 60s, consecutive errors 3→10m**, refresh rejected → disable」；登录用法 `./login.exe url` → 「open URL in browser → phone/WeChat login」。
- 部署实证长文（`https://qianling.pw/lobsterai2api/`，2026-09-14）：「官方登录使用的是**本地回环回调**，网页登录成功后，前端会跳转到 `http://127.0.0.1:<随机端口>/auth/callback`」；登录链接形态 `https://lobsterai.youdao.com/portal#/login?source=electron&redirect_uri=…&state=…`；远程部署时「地址栏变成 127.0.0.1:xxxx 且提示无法访问是正常现象，把整条 URL 复制回服务器打回容器」；**多账号注意**：「同一浏览器里登录多个账号时，需要先把前一个号的登录退出，否则下一个号登录时会卡在『未获取到有道用户信息』，建议直接用无痕标签页登录」；额度规则「注册赠 300 分（14 天）/ 邀请赠 300 分（365 天）/ 每日签到 100 分（30 天）」，倍率以 `/api/models/available` 的 `costMultiplier` 为准。
- 令牌生命周期最明确的一份（`https://github.com/L0NE-6/LobsterAI-AutoCheckin`）：「AT = accessToken（JWT，**约 30 天有效**）；RT = refreshToken（JWT，**约 180 天有效**）」、「距过期 < 7 天时自动用 RT 续期…每次续期会**换发新 RT**」；取 token 有两条路：**方式一**从桌面客户端本地库提取（`%APPDATA%/LobsterAI/lobsterai.sqlite` 的 `kv` 表 `auth_tokens`），**方式三 短信验证码登录（免客户端）**——Playwright 打开登录页、人工过滑块、截回调 `code` 换 token。
- 与本仓一致：`coding/model_gateway/upstream/lobsterai/const.py:22-49` 的 `API_BASE=lobsterai-server.youdao.com` / `PORTAL_BASE=lobsterai.youdao.com` / `CALLBACK_PATH=/auth/callback` / `USER_AGENT="LobsterAI/0.1.0"` / `CLIENT_CAPABILITIES`，以及 `login.py:6-24` 的「网关自己不是那个本地服务器，接收端 = `accounts/callback_server.py`」更正——外部证据逐条吻合（含「端口可随机、形状不行」）。

**与该假设的关系**：**不支持「必须开 App」**。三条独立路径（浏览器 OAuth 回跳 / 门户短信+滑块 / 桌面端 sqlite 提取）里只有第三条用到 App 的**离线产物**，且用的是它留下的文件而非进程 → 顶多 D3 备胎；本仓与两家社区实现走的是 D1。

**未确定项**：① `X-LobsterAI-Client-Capabilities` / `platform=win32` 这类**伪装客户端声明**是社区逆向所得，官方无任何文档，一旦服务端加严即从 D1 滑向 D3；② 429 的具体阈值、同账号并发上限（社区只给了自家冷却表，是**规避**而非官方规定）；③ 多账号是否触发账号级联坐（无实证）。

### 4) `qoder` = Qoder 国际版

**外部证据摘录**
- 官方 CLI 认证（`https://docs.qoder.com/zh/cli/authentication`，可取 `…/authentication.md` 原文）：两种认证 —— 「交互式登录：在终端里通过浏览器或粘贴令牌完成登录」与「环境变量：通过 **Personal Access Token** 认证，适合 **CI/CD 流水线和无浏览器的自动化环境**」；「**完成浏览器登录后，Qoder CLI 会在后台自动刷新令牌**」；PAT 创建页 **「https://qoder.com/account/integrations」**；无图形界面判定条件（`CI` / `SSH_CONNECTION` / Linux 无 `DISPLAY` 等）→「登录界面会直接打印登录 URL…因此在远程服务器、容器和 CI 环境中无需额外配置」；配置目录默认 `~/.qoder`。
- 官方 CLI 模型页（`https://docs.qoder.com/zh/cli/model`）：「Qoder CLI 内置了全球 SOTA 级别的 AI 模型」、「使用 `--list-models` 可以在**无界面模式下输出当前账号可用的模型列表**」、「可选模型……可能随服务端模型列表更新；以 `/model` 界面和 `--list-models` 输出为准」；自定义模型「用户使用自己在对应厂商的 API Key 即可调用」，且官方 custom-models 页明确 BYOK「费用由服务商 API 账户直接结算，**不占用 Qoder Credits**」。
- 官方 Cloud Agents API 认证（`https://docs.qoder.com/cloud-agents/api/conventions/authentication`）：「PAT 在 Qoder 控制台 **Settings → Personal Access Tokens** 创建，可配置 name、**scopes** 和 **expiration**；PAT 以 `pt-` 前缀、仅创建时完整显示」；SAT 由 SA Key 到 `$QODER_OPENAPI_BASE_URL/api/v1/serviceToken/exchange` 换「short-lived JWT」，示例 `ttl_seconds: 43200`；端点 `QODER_OPENAPI_BASE_URL=https://openapi.qoder.sh`、`QODER_API_BASE_URL=https://api.qoder.com`。
- 官方 Credits/FAQ（`https://docs.qoder.com/zh/Credits`、`.../troubleshooting/common-issue`）：「Credits 是 Qoder 中 AI 模型的资源配额」、「模型调用失败时不扣减 Credits」；**反滥用条款（权威）**：「Pro 试用资格（包含 300 Credits 试用额度）**仅限每位用户享受一次，注册多个账号获得的试用资格将被撤销**」、「**不支持在虚拟机里使用 Pro 试用资格**」；「过期的登录会话需要您重新尝试」。安全页（`.../qoder/security-and-authorization`）只有软性建议「Sign in only on devices you control」，**没有任何设备数量/并发会话上限**。
- 官方条款（`https://qoder.com/zh/product-service`）：§2.3「你的账户仅供你个人使用……**你不得共享账户凭证，不得允许任何第三方访问或使用你的账户**」；§3.2.9「对本服务的任何部分进行**反向工程、反汇编或反编译**」被禁止；§3.2.10 禁「通过脚本、引擎、软件、工具、代理……抓取/挖掘/提炼任何信息」；§3.2.11 禁「以旨在**规避相关费用**的方式访问或使用本服务」。
- 黑产与风控实证（官方论坛 `https://forum.qoder.com/t/qoder-is-being-destroyed-by-cybercriminals-qoder/10338`，2026-06-22，2 楼含官方回复）：举报内容称某工具「用**硬编码 AES 密钥 `QoderFree_Secret_2024`** 伪造设备指纹、批量注册试用号、经 MITM 代理轮转号池」，并点明该机制绕过的是「**one-device-one-trial**（一机一号试用）」；处置建议含「立即更换泄露密钥、中继 IP 过滤、注册强制联系方式核验、**后端对物理标识做密码学背书**」；官方 Ruyan_Liu 回复：「感谢你的报告！这边也收到邮件反馈了，已经提交给了技术团队并安排进行处理。」
- 机制细节（社区深度分析 `https://blog.csdn.net/2401_88756258/article/details/163055114`，2026-07-20）：签名「组合了 **RSA、AES-CBC、MD5** 三种密码学原语」；请求头 `Authorization: Bearer COSY.{header}.{sig}`；「设备身份由初次 OAuth 握手派生的、**必须成对匹配的 `Cosy-Machineid` 与 `Cosy-Machinetoken`** 锚定」；端点清单 `api3.qoder.sh/algo/api/v2/service/pro/sse/agent_chat_generation?AgentId=agent_common`、`/algo/api/v2/model/list`、`openapi.qoder.sh/api/v2/quota/usage`、`/api/v1/deviceToken/poll`；令牌观察「**一次性的 30 天资产，标了 `refreshable: false`**」；限流处理「lastError 指向 429/403 且未到 retryAfter 的 connection 会被排除」；结论「**不需要原生 Qoder 应用处于活动状态**」。
- 离线复刻已发生（`https://github.com/fengyinxia/qoder2api`）：「`qoder_auth.py` 用纯 Python 复刻了 `qoder_auth_wasm` 的全部加密/签名逻辑（自定义 base64、cosy 请求签名、RSA 密钥交换、AES payload 加密），**完全不依赖 wasm**」；`QODER_SIGNATURE_SECRET`「内置默认」。另 `https://pi.dev/packages/@jischeng/pi-provider-qoder`（v0.4.12，2026-09-21 发布，1559 次/月下载）自述「with OAuth authentication, **COSY signatures and WAF bypass**」、「10605 排队自动重试……最多 4 次」。
- 本机只读旁证：`/Applications/Qoder CN.app`（`com.qodercn.app`，**0.4.3**）的 `Contents/Resources/app.asar` 内以字符串出现 `Cosy-MachineId / Cosy-MachineToken / Cosy-MachineType / Cosy-MachineOS / Cosy-MachineCode / Cosy-MachineHostname / cosyVersion`（grep 命中计数各 3 次）→ 官方客户端确实发送这一整族设备头，与上面社区分析一致。

**与该假设的关系**：**「必须打开并登录桌面端」不成立**，但要分两层说清楚：
1. **调用期不需要进程**（权威 + 二手一致）：官方 CLI 在 CI/SSH/容器里跑，桌面端从未参与；社区三家（qoder2api / 9router / pi-provider）都无进程。
2. **需要客户端的离线产物**：本仓选的 IDE 加密推理通道必须有 COSY 签名能力 → 判 **D3**，而不是 D2。D3 的强度已被外部削弱为「**算法 + 常量可复刻**」而非「必须有 WASM 二进制」。
3. 另有一条**官方自建的 D1 通道**（Qoder CLI + PAT），它消费的正是账号 Credits 里的内置/前沿模型（`--list-models` = 当前账号可用模型）——若允许换通道，本仓 qoder 可以不走签名端点。

**未确定项**：① 官方 CLI/PAT 通道与 IDE 加密通道在**模型集合与限流**上是否同源（外部只能证明 CLI 有目录，未能证明目录 = IDE 目录）；② `Cosy-MachineId` 服务端是否做**跨账号唯一性**校验（论坛只证明「一机一号试用」在用）；③ 国际版网关主机到底是 `api2.qoder.sh`（本仓）还是 `api3.qoder.sh`（两家社区），属可实测项。

### 5) `qodercn` = Qoder 中国版（gateway.qoder.com.cn）

**外部证据摘录**
- 官方 CN CLI 认证（`https://docs.qoder.cn/cli/authentication`）：同双路径（交互式登录 / `QODERCN_PERSONAL_ACCESS_TOKEN` 环境变量 PAT），「完成浏览器登录后，Qoder CLI CN 会在后台自动刷新令牌」，配置目录默认 `~/.qoder-cn`，环境变量 PAT **优先于** `/login` 落盘凭据；明确「在没有图形界面的环境中……自动跳过拉起浏览器，打印登录 URL」。
- 官方 CN 模型页（`https://help.aliyun.com/zh/lingma/qodercli-cn/user-guide/model`）：CLI 前缀 `qoderclicn`，`--list-models`「无界面列出当前账号可用模型」；模型分五档（Auto/Ultimate/Performance/Efficient/**Lite 免费但「仅限 Team 版」**）+ 前沿模型直选（Qwen3.7-Max/Plus、DeepSeek-V4-Pro/Flash、GLM-5.2、Kimi-K2.7-Code、MiniMax-M3）并各自标 Credit 倍率；Custom = BYOK「用户使用自己在对应厂商的 API Key 即可调用」。**未提及**任何对外 OpenAI 兼容 REST 端点。
- CN PAT 与端点（二手，两家一致）：`qoder2api` README「打开 **https://qoder.cn/account/integrations** → 服务集成 → 创建个人访问令牌，形如 `pt-xxxx_019exxxx-…`」；`@jischeng/pi-provider-qoder` 的服务端点表给出 CN：PAT 交换 `https://openapi.qoder.com.cn/api/v1/jobToken/exchange`、用户信息 `/api/v1/userinfo`、用量 `/api/v2/quota/usage`、**聊天网关 `https://gateway.qoder.com.cn/`**（国际版对应 `https://api3.qoder.sh/`）。
- CN 目录可拉（二手）：`qoder2api` 「缓存过期 → `GET {gateway}/algo/api/v2/model/list?Encode=1`（带 cosy 鉴权）…响应是明文 JSON（**实测**）」，模型表为 display_name → 内部 key（如 `GLM-5.2`→`gm51model`、`Qwen3.7-Max`→`qmodel_latest`），视觉能力 `is_vl` 同样动态下发；兜底只在拉取失败时启用并打 WARN。
- 权威反滥用/条款同 `qoder`（同一服务条款体系 + 官方 FAQ「多号试用撤销 / 禁虚拟机」）。

**与该假设的关系**：**不需要打开桌面端**（本仓记录的 `QODER_CN` 与国际版共用协议族，登录即设备码轮询、续期即 HTTP，`coding/model_gateway/upstream/qodercn/product.py:5-17`）；阻塞点与 `qoder` 同 = **签名产物（D3）**。

**未确定项**：① 本仓记载「`/model/v1/chat/completions` 实测 503」与外部「签名 SSE `agent_chat_generation` 可用」并不矛盾（不同路径/不同面），但**哪条才是 CN 当前正确的推理路径**必须由实测裁定；② CN 是否有与国内文档 `qoder.com.cn` 完全不同的席位并发限制（无外部证据）；③ PAT 交换出的 jobToken 有效期（外部只写「短期」，未给秒数）。

---

## 三、仅凭外部权威无法定论、只能靠代码/实测的格子

1. **全部五个产品的 C 类「同一账号多设备/多会话并存」行为**：无一家官方文档写明设备数量或并发会话上限（Qoder 安全页只有「在你能控制的设备上登录」这类建议）。只有两条**间接**权威：Qoder FAQ「多号试用撤销 + 禁虚拟机」、CodeBuddy ToS §8.2(6)/§8.4。互踢与并发限流的具体形态只能实测。
2. **`buddy`/`workbuddy` plugin token 的有效期与刷新语义**：官方只给开放平台 `expires_in=3600`；本仓的 `AUTH_REFRESH_PATH` 是从上游客户端取证而来（`buddy/protocol.py:41-42`），外部无文档；社区反代遇到 401 就「重新登录」（不承认 refresh），与本仓能刷新并不完全一致 → 需实测刷新是否真的换新 RT。
3. **图盾（TuringShield / native turing-sdk）是否参与推理风控**：包内存在是硬事实，用途是推断。只能靠「同 UA/同 token 换设备/换指纹是否被拒」实测。
4. **`lobsterai` 的伪装声明是否会升级为准入条件**：`X-LobsterAI-Client-Capabilities` 决定 `kimi-k3` 是否返回、`reasoning_effort:"off"` 是否 500（本仓 `const.py:41-47` 已钉），外部同样只有社区实现 → 该面一旦变化就是 D1→D3 的滑坡，须持续实测。
5. **`qoder`/`qodercn` 的 jobToken/PAT 实际 TTL 与 refreshable 语义**：官方文档不写数值；社区一方说 PAT→jobToken「周期续期」、另一方说设备码 token「一次性 30 天、`refreshable:false`」——两者不兼容，只能用真实响应体裁定（本仓 `qoder/flow.py:449-483` 走的是 refresh 路线）。
6. **Qoder 远端模型目录 = 网关可用模型** 的等价性：外部证明目录能拉到、且 `Unsupported model` 是名字不在目录里；但「目录里的 key 是否都能被本账号权益调用（倍率/权限）」需逐模型实测。
7. **多账号并行的真实风控阈值**（尤其 Qoder 的 10605 排队、lobsterai 的 429、buddy 的「内容违规」拦截）：外部只给了「存在限流/审核」的证据，无任何数值。

## 四、我预测会与「代码角色」分歧的格子及原因

1. **`qoder`/`qodercn` 的「目录端点需 292KB WASM 签名 → 不实现」这条口径**（本仓 `qoder/product.py:11`、`qoder/out.py:10-20`、`21 §1.1`）：外部有两家独立实现（`fengyinxia/qoder2api`、9router）**纯算法复刻同一签名并成功调用 `model/list` 与 chat SSE**，且 `QODER_SIGNATURE_SECRET` 有内置默认值、论坛泄露了历史 AES 常量。我的预测：真实门槛是「离线可复刻的算法+常量」（= **D3，可实现**），不是「必须有 WASM 二进制/必须有客户端」。若代码角色写「结构性不可行」，这条就是分歧点。
2. **`qodercn` 的「无可用公开端点 / 503」**：外部证据显示 CN 推理实际走 `gateway.qoder.com.cn` 的签名 SSE（`agent_chat_generation`），`/model/v1/chat/completions` 的 503 更像是「路径选错/未签名」而非「CN 无通道」。预测分歧：代码角色可能据 503 判「CN 不可接」，我判「可接、卡在签名」。
3. **`qoder` 国际版网关主机**：本仓 = `api2.qoder.sh`；两家社区 = `api3.qoder.sh`（含 `/algo/...` 前缀）。分歧原因：IDE 面与 agent 面可能本就是两个入口，或域名已轮换。需实测两域同一 token/同一目录是否都通。
4. **`buddy`/`workbuddy` 的 C 类**：本仓口径「无设备标识 → 无设备面约束」（`20 §2.7`）。我预测代码角色会据此给 C0 干净结论；外部两条反向证据（ToS §8.2(6) 明文禁止非授权第三方登录 + 本机 WorkBuddy 随包图盾 SDK）意味着**至少 C3（风控未知）**更诚实，多账号并行可能撞审核/风控而不是撞设备绑定（`workbuddy2api` 的「几乎每个请求被拦截」就是这条的实证）。
5. **`lobsterai` 的 D 类**：若代码角色按「凭据来自桌面端本地 sqlite（`%APPDATA%/LobsterAI/lobsterai.sqlite` 的 `auth_tokens`）」判 D3（社区 AutoCheckin 的**推荐**路径就是这条），而本仓/权威面走「门户浏览器 OAuth + 本机回跳」判 **D1**——两条路都真，分歧只在「凭据从哪儿来」。我维持 D1，并把「从 App 数据目录复制凭据」列为 D3 备胎，避免把两种来源合成一条结论。
6. **`qoder` 的 token 续期能力**：本仓有 `POST /api/v1/deviceToken/refresh`（`qoder/flow.py:449-483`）；9router 的实测观察是「token 一次性、30 天、`refreshable:false`」；官方 CLI 文档又说「后台自动刷新令牌」。三者不完全一致，我的判断是「**通道不同**（IDE 设备码 vs CLI 令牌）」，但这是推断，须实测，否则会被写成「已验证」。
