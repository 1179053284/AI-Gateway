"""TRAE（字节）协议常量（tech-design v2.0 §22.4 行；取值**逐条附 DSH `file:line`**）。

🔴 本模块**只放常量**（端点 / 请求头取值 / 客户端形态值 / 兜底模型表），不放逻辑。
   每个取值都必须指得出取证行；取不到的留 TODO，**不许编造**（M6-3 任务纪律）。
   证据来源：`docs/research/20 §1.2/§2.7/§3.1/§3.5`、`21 §1.1` 引用的 DSH 源
   （`deepseek-harness-codearts/src/trae*.ts`，`file:line` 沿用 research 的标注口径）。

⚠️ 三个基址**分工不同，不得混用**（`trae-product.ts:154-161`）：

| 常量 | 用途 | 端点族 |
|---|---|---|
| `AGENT_HOST` | 对话 + 模型目录（**出站基址** = 注册表 `base_url`） | `/api/agent/*`、`/api/ide/*` |
| `UG_HOST` | 签到 / 积分（Ug = User Growth） | `/trae/api/v2/ug/*`、`/trae/api/v2/pay/*` |
| `OAUTH_HOST` | ExchangeToken / GetUserInfo | `/cloudide/api/v3/trae/*` |
| `CONSOLE_HOST` | 登录门户（登录 URL 挂它下面） | `/authorization` |
"""

from __future__ import annotations

#: 本产品标识（= `accounts/registry.py` 的键 = 账号目录名；`product.PRODUCT` 指向它，
#: **单一真相源**——两处各写一份字面量正是分叉的前夕）
PRODUCT_ID = "trae"

# —— 基址（`src/trae-product.ts:154-161`） ——

#: 对话 + 模型目录基址（`trae-product.ts:155` `TRAE_AGENT_HOST`）。
#: 与 `accounts/registry.py` 的 `trae` 实例 `base_url` **必须同值**（资源物化读注册表）：
#: chat = `{AGENT_HOST}/api/agent/v3/llm_utils_chat`（`trae-adapter.ts:1175`），
#: 目录 = `{AGENT_HOST}/api/ide/v1/batch_get_detail_param`（`trae-auth.ts:694`）。
AGENT_HOST = "https://trae-api-cn.mchost.guru"

#: 签到 / 积分基址（`trae-product.ts:157` `TRAE_UG_HOST`；`trae-credits.ts:154` 同值硬编码）。
UG_HOST = "https://api.trae.cn"

#: OAuth 基址（`trae-product.ts:159` `TRAE_OAUTH_HOST`）：ExchangeToken / GetUserInfo。
OAUTH_HOST = "https://api.trae.com.cn"

#: 登录门户基址（`trae-product.ts:161` `TRAE_CONSOLE_HOST`）：登录 URL 的宿主。
CONSOLE_HOST = "https://www.trae.cn"

# —— 端点路径（`src/trae.ts:41-65`） ——

#: 模型目录（**多通道** batch，真实 CN IDE 用的端点，`trae-auth.ts:694` 在 AGENT_HOST 上打它）。
#: （同族的单通道 `PATH_MODELS = "/api/ide/v1/get_detail_param"`（`trae.ts:46`）本层不用，
#: 故**不落常量** —— 接线护栏要求「无引用即删」，只作解释用的常量就是死代码。）
PATH_BATCH_MODELS = "/api/ide/v1/batch_get_detail_param"
#: ExchangeToken（refreshToken 换 accessToken，**并轮换 refreshToken**）。
PATH_EXCHANGE = "/cloudide/api/v3/trae/oauth/ExchangeToken"
#: 用户信息（探活用；也是登录后补 uid/脱敏手机号的来源）。
PATH_USER_INFO = "/cloudide/api/v3/trae/GetUserInfo"
#: 签到状态（**幂等判据的唯一来源**）。
PATH_CHECKIN_STATUS = "/trae/api/v2/ug/checkin_credits/status"
#: 签到领取。
PATH_CHECKIN_CLAIM = "/trae/api/v2/ug/checkin_credits/claim"
#: 积分余额（资源包列表）。
PATH_ENT_USAGE = "/trae/api/v2/pay/ide_user_ent_usage"
#: 登录回调路径（`trae.ts:65`）：登录页回跳 `http://127.0.0.1:18080/authorize?...`。
CALLBACK_PATH = "/authorize"
#: 登录页路径（`trae-oauth.ts:126`：`{consoleHost}/authorization?…`）。
LOGIN_PATH = "/authorization"
#: 对话端点（`trae.ts:44` `TRAE_CHAT_PATH`，挂 `AGENT_HOST`）—— M6-5 出站接线
#: （`trae-adapter.ts:1175` 的 `{agentHost}/api/agent/v3/llm_utils_chat`）。
PATH_CHAT = "/api/agent/v3/llm_utils_chat"
#: 模型未标通道时的默认通道（`trae.ts:1447-1452` `TRAE_FUNCTION`；channelFor 的回退值，
#: `trae-adapter.ts:658-661`）—— 模型 → 通道的映射由 `models.channel_for` 提供。
FUNCTION = "solo_work_lite"

# —— 客户端形态值（`src/trae-product.ts:263-285` 的 `TRAE` 实例） ——

#: OAuth2 `client_id`（`trae-product.ts:270`）。
CLIENT_ID = "en1oxy7wnw8j9n"
#: `X-App-Id`（`trae-product.ts:271`）。
APP_ID = "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8"
#: IDE 版本号：**模型可用性的准入条件**（0.1.52 才能用 glm-5.3；版本过低报 `4001`）
#: （`trae-product.ts:68-74,272`）。
IDE_VERSION = "0.1.52"
#: IDE 版本号（日期式，`trae-product.ts:75-76,273`）。
IDE_VERSION_CODE = "20260811"
#: 设备品牌 / 系统版本（SOLO 头，`trae-product.ts:77-80,274-275`）。
DEVICE_BRAND = "Apple"
OS_VERSION = "macOS 15.7.4"
#: 目录拉取的通道优先级（`trae-product.ts:217-227`）：顺序即优先级（同条目择优用）。
CHANNELS = ("solo_agent", "solo_work_lite", "solo_agent_remote")
#: 登录 URL 的 `plugin_version`（**不是** IDE 版本号，`trae-product.ts:139-145,282`）。
PLUGIN_VERSION = "2.3.62834"
#: `User-Agent`（`trae-product.ts:284`；SOLO/UG/OAuth 三族共用）。
USER_AGENT = "Trae/0.1.52"

#: `traeSOLOHeaders` 里的固定值（`trae.ts:210-228`）。
SOLO_FIXED_HEADERS = {
    "X-App-Version": "default",
    "X-Ide-Version-Type": "stable",
    "X-Device-Type": "macos",
    "Request-Traffic-Type": "prod",
}

#: 登录 URL 的 `x_*` 系列（客户端形态伪装，`trae-oauth.ts:117-124`）。
LOGIN_DEVICE_BRAND = "PC"
LOGIN_DEVICE_TYPE = "PC"
LOGIN_OS_VERSION = "1.0"
LOGIN_APP_TYPE = "stable"

#: 签到专用完整头里的固定值（对齐 trae-mate `build_headers`，`trae.ts:281-314`）。
#: `User-Agent` 刻意与 SOLO 族不同（`trae.ts:296`：`VSCode 1.107.1 (TRAE SOLO CN)`）。
CHECKIN_USER_AGENT = "VSCode 1.107.1 (TRAE SOLO CN)"
CHECKIN_MARKET_CLIENT_ID = "VSCode 1.107.1"
CHECKIN_FIXED_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "zh-CN",
    "X-Lgw-Req-Sdk-Type": "3",
    "Package-Type": "stable_cn",
    "X-Lscbd-Aid": "787976",
    # `windows` 是**伪装客户端形态**：与真实运行环境（macOS）无关，照抄观察值。
    "X-Lscbd-Platform": "windows",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "none",
}

#: 模型目录请求体里的**全部** function（22 条，逐条照抄 `trae-auth.ts:673-688`）。
#: ⚠️ 必须全传：真实 CN IDE 传的就是全部 22 个，只传聊天通道会让响应的通道分组错位。
MODELS_FUNCTIONS = (
    "ui_builder_v2", "solo_coder", "chat_v3", "solo_builder",
    "builder_v3", "builder", "chat", "inline_chat", "git_ai",
    "custom_agent_generation", "utils", "code_reviewer",
    "code_review_summary", "solo_agent", "solo_agent_remote",
    "solo_work_remote", "solo_agent_lite", "solo_work_lite",
    "solo_design_lite", "solo_design_remote", "multimodal",
    "system_diagnosis",
)

#: 本地回调的**首选**端口（`trae-oauth.ts:40` 的 `TRAE_CALLBACK_PORT`，对齐 Go 端默认）。
#: 🔴 BD4（2026-09-30）更正口径：它**不是**"写死的监听端口"。
#: `accounts/callback_server.py` 的接收端**先试它、拿不到就回退系统分配的随机端口**
#: （`:530-543` 的 `EADDRINUSE`/`EACCES` 回退），授权 URL 与回跳校验都用**实际**端口
#: （`:680-693`）。本常量的两个用处：① 接收端的 `preferred_port`（对齐参考实现默认值）；
#: ② 没有接收端时（起监听失败 / 直接构造的会话）粘贴兜底的校验基准端口。
CALLBACK_PORT = 18080
#: 回调的**回环**主机名白名单（DSH 只绑 `127.0.0.1`，`:499-503`；接收端同样只绑回环）。
CALLBACK_HOSTS = ("127.0.0.1", "localhost")

#: 控制面请求超时（秒）——`trae.ts:68` `TRAE_REQUEST_TIMEOUT_MS = 30_000`。
REQUEST_TIMEOUT_S = 30.0

# —— 兜底模型表（`src/trae-product.ts:169-202`，32 条，顺序照抄不重排） ——

#: 兜底模型目录 `TRAE_FALLBACK_MODELS`。
#:
#: 来源链：`trae-product.ts:164-168`「来源：`handler.go:247-280`，2026-08 实测快照；
#: 顺序照抄 Go 端 staticModels，不重排」→ 原始出处 `trae2api/internal/server/handler.go:247-280`。
#:
#: - `contextWindow` **照抄 200_000**：DSH 自注「**数值是估值**（采信实测主流值
#:   `contextWindow=200000`），远端可用时完全采信远端」（`trae-product.ts:34-37`）；
#: - `hidden=True` 的 4 条 = 上游标记的内部/隐藏条目（`isHidden`，子代理/标题生成等），
#:   与远端路径的硬性过滤 `is_invisible_to_user === true`（`trae.ts:1231`）**同一条判据**
#:   → `models.fallback_models()` 不返回它们（保留在表里是为了「逐条照抄」与留痕）。
FALLBACK_MODELS: tuple[tuple[str, str, int, bool], ...] = (
    ("DeepSeek-V4-Flash-Official", "DeepSeek V4 Flash Official", 200_000, False),
    ("Doubao-Seed-2.1-Pro", "Doubao Seed 2.1 Pro", 200_000, False),
    ("seed-code-pro-0430", "Seed Code Pro 0430", 200_000, False),
    ("Doubao-Seed-2.1-Turbo", "Doubao Seed 2.1 Turbo", 200_000, False),
    ("Doubao-Seed-2.0-Code", "Doubao Seed 2.0 Code", 200_000, False),
    ("browser_use_subagent", "Browser Use Subagent", 200_000, True),
    ("glm-5.2", "GLM-5.2", 200_000, False),
    ("glm-5-turbo", "GLM-5 Turbo", 200_000, False),
    ("glm-5", "GLM-5", 200_000, False),
    ("DeepSeek-V4-Pro", "DeepSeek V4 Pro", 200_000, False),
    ("DeepSeek-V4-Flash", "DeepSeek V4 Flash", 200_000, False),
    ("kimi-k3", "Kimi K3", 200_000, False),
    ("kimi-k2.7-code", "Kimi K2.7 Code", 200_000, False),
    ("kimi-k2.6", "Kimi K2.6", 200_000, False),
    ("minimax-m3", "MiniMax M3", 200_000, False),
    ("qwen-3.7-plus", "Qwen 3.7 Plus", 200_000, False),
    ("sagitta", "Sagitta", 200_000, False),
    ("aquila", "Aquila", 200_000, False),
    ("custom_model_gemini", "Custom Gemini", 200_000, False),
    ("custom_model_placeholder", "Custom Placeholder", 200_000, False),
    ("custom_model_1M_text", "Custom 1M Text", 200_000, False),
    ("custom_model_1M", "Custom 1M", 200_000, False),
    ("custom_model_kimi", "Custom Kimi", 200_000, False),
    ("custom_model_claude", "Custom Claude", 200_000, False),
    ("custom_model_gpt-5", "Custom GPT-5", 200_000, False),
    ("custom_model_no-fc", "Custom No-FC", 200_000, False),
    ("custom_model_deepseek_chat", "Custom DeepSeek Chat", 200_000, False),
    ("custom_model_deepseek_reasoner", "Custom DeepSeek Reasoner", 200_000, False),
    ("custom_model_deepseek_v4", "Custom DeepSeek V4", 200_000, False),
    ("explore_sub_agent_v13", "Explore Sub Agent V13", 200_000, True),
    ("explore_sub_agent_v2", "Explore Sub Agent V2", 200_000, True),
    ("summary", "Summary", 200_000, True),
)

# —— 签到错误分类与冷却（`src/trae-credits.ts:74-100` 的 `classifyTraeCheckinError`） ——

#: 冷却秒数取值（照抄表中字面量；`-1` = **永久**，`0` = 不冷却）。
#: 类型 → 冷却：PlanLimit 43200 / SoftRate 60 / SessionDead -1 / NotFound 60 /
#: Server 600 / Client 600 / BusinessError 300 / Unknown 0。
COOLDOWN_PLAN_LIMIT_S = 43_200
COOLDOWN_SOFT_RATE_S = 60
COOLDOWN_PERMANENT_S = -1
COOLDOWN_NOT_FOUND_S = 60
COOLDOWN_SERVER_S = 600
COOLDOWN_CLIENT_S = 600
COOLDOWN_BUSINESS_S = 300
#: Plan 权益不足的业务码（`trae-credits.ts:78`：HTTP 200 + code 1005）。
CODE_PLAN_LIMIT = 1005
#: 「签到人数过多」业务码（`trae-credits.ts:107` 的 `TRAE_CHECKIN_BUSY_CODE`）。
#: ⚠️ **不再触发换设备号重试**（9074 轮换代次机制**已废弃**，`20 R14/§3.5`；
#: `trae-credits.ts:265-276` 注释原文「设备轮换已废弃，不再重试」）——
#: 直接按 BusinessError 报失败（冷却见 `claim.py`）。
CODE_CHECKIN_BUSY = 9074

# —— 积分余额（`src/trae-credits.ts:316-381`） ——

#: 余额请求体（`trae-credits.ts:321-326`：`{"require_usage": true, "req_source": 2}`）。
BALANCE_BODY = {"require_usage": True, "req_source": 2}
#: 余额单位（`trae-credits.ts:366`：`unit: 'credits'`——TRAE 的额度单位是积分数）。
BALANCE_UNIT = "credits"

#: GetUserInfo 请求体（`trae-oauth.ts:422`：`{"ReqSource": "IDE", "IDEVersion": …}`）。
USER_INFO_BODY = {"ReqSource": "IDE", "IDEVersion": IDE_VERSION}

#: ExchangeToken 请求体里的 `ClientSecret` 占位（`trae-oauth.ts:375-380`、
#: `trae-auth.ts:380-385`：字面量 `'-'`，**不是**真实密钥）。
EXCHANGE_CLIENT_SECRET = "-"
