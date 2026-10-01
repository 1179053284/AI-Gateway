"""Cline 产品私有常量：端点 / 请求头 / 超时 / 兜底模型表 —— 逐条附 DSH 取证 `file:line`。

🗂 证据面（只读，2026-09-25 实测）：DSH 插件 `src/cline-product.ts`、`src/cline-oauth.ts`、
   `src/cline-credits.ts`、`src/cline-models.ts`（`docs/research/20 §1.2/§3.1`、`21 §1.1`）。
🔴 纪律：**取不到就留空/不写**，不猜端点、不猜字段（M6-1 骨架纪律在 M6-2 的延续）；
   本文件只放**已取证**的字面量，逻辑放 `protocol.py`，IO 放 `product.py`。
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------- 宿主与身份 ----------

#: API 基址 = `CLINE.apiBase`（`cline-product.ts:265`）—— 推理 / 目录 / 账号 / auth 全挂它下面
API_BASE = "https://api.cline.bot"
#: WorkOS 基址 = `DEFAULT_WORKOS_API_BASE_URL`（`cline-product.ts:267`）——
#: **设备码授权与 token 轮询走它，不是 `API_BASE`**（`cline-product.ts:76-81`）
WORKOS_BASE = "https://api.workos.com"
#: WorkOS client id（`cline-product.ts:268`；prod 环境，staging/local 各有自己的值，本项目只支持 prod）。
#: ⚠️ 这是**公开客户端标识**（public client identifier），**不是密钥**：设备码授权（device_code
#: grant）本就要求把它放进请求体（`cline-oauth.ts:186`），且同一值同时出现在凭据 JWT 的
#: `client_id` claim 里与官方桌面端产物中（`cline-product.ts:82-87`）—— 无法也不该伪装成秘密。
#: 它进源码不违反「密钥只存本地明文配置/环境变量」的那条纪律（铁律 1 管的是 API Key/令牌）。
WORKOS_CLIENT_ID = "client_01K3A541FN8TA3EPPHTD2325AR"
#: 客户端标识请求头 = `DEFAULT_CLINE_REQUEST_HEADERS`（`cline-product.ts:269-274`）。
#: ⚠️ 推理与账号端点**都要带**（`cline-product.ts:91-96`：官方客户端的身份声明，
#: 只带 Authorization 实测虽可通，但缺失可能在某些网关策略下被拒或降级）。
CLIENT_HEADERS: dict[str, str] = {
    "HTTP-Referer": "https://cline.bot",
    "X-Title": "Cline",
    "X-IS-MULTIROOT": "false",
    "X-CLIENT-TYPE": "cline-sdk",
}
#: 访问令牌前缀（`cline-product.ts:96-115`）—— **必须保留**，见 `protocol.bearer_value` 的坑位说明
TOKEN_PREFIX = "workos:"

# ---------- 端点路径（`cline-product.ts:288-307` 的常量组）----------

#: 设备码授权（挂 `WORKOS_BASE`；`cline-product.ts:293`）
DEVICE_AUTHORIZATION_PATH = "/user_management/authorize/device"
#: 设备码 token 轮询（挂 `WORKOS_BASE`；`cline-product.ts:295`）
DEVICE_AUTHENTICATE_PATH = "/user_management/authenticate"
#: 注册 WorkOS token → 换 Cline 自己的 token（挂 `API_BASE`；`cline-product.ts:297`）
REGISTER_PATH = "/api/v1/auth/register"
#: 凭据续期（挂 `API_BASE`；`cline-product.ts:299`）
REFRESH_PATH = "/api/v1/auth/refresh"
#: 全量模型 id 列表（挂 `API_BASE`，**需认证**；`cline-product.ts:303`）
MODELS_PATH = "/api/v1/models"
#: 推荐模型（含 **`free` 数组**，挂 `API_BASE`，**免认证**；`cline-product.ts:305`）
RECOMMENDED_MODELS_PATH = "/api/v1/ai/cline/recommended-models"
#: 账号信息（挂 `API_BASE`；`cline-product.ts:307`）。实测 `Bearer workos:eyJ…` → 200
#: （`cline-product.ts:107`）—— 本项目的探活端点（DSH 自身只声明未接线）
ME_PATH = "/api/v1/users/me"
#: 余额端点（挂 `API_BASE`；`cline-credits.ts:181` 的 `` `${apiBase}/api/v1/users/${userId}/balance` ``）。
#: ⚠️ `{user_id}` 必须是**凭据里的 `account_id`**（`usr-…`），不是 JWT 的 `sub`（`user_…`）——
#: 传 `sub` 实测返回 `400 {"error":"Invalid request format"}`（`cline-credits.ts:15-18, 176-181`）
BALANCE_PATH_TEMPLATE = "/api/v1/users/{user_id}/balance"

# ---------- 超时与设备码默认值 ----------

#: 单次 HTTP 请求超时（秒）= `CLINE_HTTP_TIMEOUT_MS = 30_000`（`cline-oauth.ts:77`；
#: 余额同值 `cline-credits.ts:63`）
HTTP_TIMEOUT_S = 30.0
#: 模型目录端点超时（秒）= `CLINE_MODELS_TIMEOUT_MS = 20_000`（`cline-models.ts:48`）
MODELS_TIMEOUT_S = 20.0
#: 设备码默认有效期（秒）= `DEFAULT_DEVICE_AUTH_EXPIRES_IN_SECONDS = 300`（`cline-oauth.ts:80`）
DEVICE_AUTH_EXPIRES_S = 300
#: 设备码默认轮询间隔（秒）= `DEFAULT_DEVICE_AUTH_INTERVAL_SECONDS = 5`（`cline-oauth.ts:83`）
DEVICE_AUTH_INTERVAL_S = 5
#: 轮询间隔下限（毫秒）：服务端可能下发 0 或负数，无节制轮询会被限流（`cline-oauth.ts:236-237`）
DEVICE_AUTH_MIN_INTERVAL_MS = 1_000
#: `slow_down` 的退避步长（毫秒）：源码 `intervalSeconds += 1`，**必须累积**（`cline-oauth.ts:273-278`）
SLOW_DOWN_STEP_MS = 1_000

# ---------- 余额口径 ----------

#: 余额数据来源标识（三态快照的 `source`，便于事后判断结论来自哪个通道）
QUOTA_SOURCE = "cline-balance"
#: ⚠️ 余额**单位未取证**（`cline-credits.ts:26-34`）：实测 `balance: 500000`，DSH 把换算系数
#: 收敛为单个常量 `CLINE_BALANCE_SCALE = 100_000`（推测 micro-USD → $5.00），
#: 但 sidecar 里 `balance` 只出现在 zod schema（`z.string()`）与 redaction 关键词表中，
#: **没有任何换算点**。本项目**不做换算**：`QuotaSnapshot.detail` 只报原始值并注明未取证，
#: 避免把一个推测当口径写进网关（`23 B2`「未知不当零」的同一精神）。
BALANCE_SOURCE_NOTE = "原始单位未取证，DSH 推测 micro-USD，见 cline-credits.ts:26-34"

# ---------- 模型 ----------

#: 免费模型 id 的**后缀**约定（内嵌目录的 `:free` 条目；`cline-models.ts:75`）
FREE_ID_SUFFIX = ":free"
#: 免费模型 id 的**前缀**约定（`cline-free/` 命名空间；`cline-models.ts:77`）
FREE_ID_PREFIX = "cline-free/"

#: 思考档位（**产品级统一表**，远端不下发；`cline-product.ts:206-248`）。
#: `(wire 值, 展示名)` —— 上游认的前四档 + 最高档 `max`（展示名 `Extra`）：
#: 实测 `xhigh` 与 `high` 无可辨差异（伪档位）故不登记；不传 = 不思考。
#: ⚠️ 上游对**不认识**的档位静默忽略（`reasoning_effort:'banana'` → HTTP 200 且思考量 0），
#: 故最坏情况是「开关无效」而不是「请求失败」（`cline-product.ts:216-219, 236-241`）。
REASONING_EFFORTS: tuple[tuple[str, str], ...] = (
    ("none", "None"), ("low", "Low"), ("medium", "Medium"), ("high", "High"), ("max", "Extra"),
)


@dataclass(frozen=True)
class FallbackModel:
    """内嵌兜底模型表的一条（`ClineFallbackModel`，`cline-product.ts:39-59`）。

    ⚠️ 本表只是**兜底**：真实免费集合由远端 `recommended-models` 的 `free` 数组下发，
    且内嵌目录**缺 `cline-free/gemini-3.8-flash`**（远端有）→ 故合并（而非回退）才有意义
    （`cline-product.ts:33-38`、`cline-models.ts:180-235`）。
    """

    id: str
    name: str
    context_window: int
    max_output: int | None = None
    supports_image: bool | None = None
    is_free: bool = False


#: 兜底目录 = `CLINE_FALLBACK_MODELS`（`cline-product.ts:146-204`），**顺序即展示顺序**。
#: ⚠️ `cline-free/gemini-3.8-flash` 的输出上限是 **65536，不要照抄其它免费模型的 131072**
#: —— 给该模型发 `max_tokens=131072` 会被上游 vertex provider 以 400 拒绝（用户报障实测，
#: `cline-product.ts:177-184`）。
FALLBACK_MODELS: tuple[FallbackModel, ...] = (
    FallbackModel("stealth/space-bunny-alpha", "Space Bunny Alpha",
                  context_window=1_000_000, max_output=524_288, supports_image=True, is_free=True),
    FallbackModel("cline-free/mimo-v2.6-flash", "MiMo-V2.6-Flash",
                  context_window=1_048_576, max_output=131_072, supports_image=True, is_free=True),
    FallbackModel("cline-free/deepseek-v4.1-flash", "DeepSeek V4.1 Flash",
                  context_window=1_048_576, max_output=131_072, supports_image=True, is_free=True),
    FallbackModel("cline-free/gemini-3.8-flash", "Gemini 3.8 Flash",
                  context_window=1_048_576, max_output=65_536, supports_image=True, is_free=True),
    FallbackModel("cline-free/muse-spark-1.3-contributor", "Muse Spark 1.3 Contributor",
                  context_window=1_048_576, max_output=943_718, supports_image=True, is_free=True),
)
