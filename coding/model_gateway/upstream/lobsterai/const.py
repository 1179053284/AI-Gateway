"""LobsterAI 协议常量（tech-design v2.0 §22.4 行；取值**逐条附 DSH `file:line`**）。

🔴 本模块**只放常量**（端点 / 请求头取值 / 兜底值 / 固定查询参数），不放逻辑。
   每个取值都必须指得出取证行；取不到的留 TODO，**不许编造**（M6-2 任务纪律）。
   证据来源：`docs/research/20 §1.2/§2.5/§3.1/§3.2` 引用的 DSH 源
   （`deepseek-harness-codearts/src/lobsterai*.ts`，`file:line` 沿用 research 的标注口径）。
"""

from __future__ import annotations

#: 本产品标识（= `accounts/registry.py` 的键 = 账号目录名；`product.PRODUCT` 指向它，
#: **单一真相源**——两处各写一份字面量正是分叉的前夕）。
PRODUCT_ID = "lobsterai"

# —— 基址（`src/lobsterai-product.ts`） ——

#: 上游 API 基址（`src/lobsterai-product.ts:63` `LOBSTERAI_API_BASE`；
#: 原始取证 = `lobsterai2api/sigin.py:10` 硬编码，Go 侧被脱敏为 env `LB2A_UPSTREAM_BASE`）。
#: 与 `accounts/registry.py` 的 `lobsterai` 实例 `base_url` **必须同值**（资源物化读的是注册表）。
API_BASE = "https://lobsterai-server.youdao.com"

#: 登录门户基址（`src/lobsterai-product.ts:77`）：登录 URL 挂在它下面，**不是** API 基址
#: （`buildLobsteraiLoginUrl` 用 `product.portalBase`，`lobsterai-oauth.ts:115`）。
PORTAL_BASE = "https://lobsterai.youdao.com"

#: 客户端版本号查询端点（**第三方域名**，`src/lobsterai-product.ts:85-86`）。
#: ⚠️ 该响应与业务接口**不同构**：`code`/`msg` 在外层、载荷在 `data.value`。
CLIENT_VERSION_API = (
    "https://api-overmind.youdao.com/openapi/get/luna/hardware/lobsterai/prod/update")

#: 版本号取不到时的兜底值（`src/lobsterai-product.ts:98`）。`sigin.py:73-76` 在取不到时
#: **整个脚本放弃签到**；DSH 更宽容（宁可用稍旧版本号试，后端并不强校验 version）。
FALLBACK_CLIENT_VERSION = "2026.9.4"

#: `User-Agent`（原样照抄 `lobsterai2api/internal/upstream/client.go:21` 的 `clientUA`，
#: 见 `src/lobsterai-product.ts:119-129`；DSH 刻意不跟着真版本号改这个头）。
USER_AGENT = "LobsterAI/0.1.0"

#: `X-LobsterAI-Client-Capabilities`（`src/lobsterai-product.ts:116-117`）。**两项都必需**：
#: `kimi-k3-agentic-v1` 是模型列表准入条件（不带时 `kimi-k3` 不返回：25 vs 26 个）；
#: `thinking-level-control-v1` 是 `reasoning_effort:"off"` 的前提（不带时服务端 HTTP 500）。
CLIENT_CAPABILITIES = "kimi-k3-agentic-v1,thinking-level-control-v1"

# —— 认证与目录端点（`src/lobsterai.ts:32-47`） ——

#: 授权码换 token（**无需** `Authorization`——换 token 时还没有 token）。
PATH_EXCHANGE = "/api/auth/exchange"
#: 静默续期（**无需** `Authorization`；服务端只认请求体里的 `refreshToken`）。
PATH_REFRESH = "/api/auth/refresh"
#: 可用模型列表（需 Bearer + 两个 `X-LobsterAI-Client-*` 头，`lobsterai.ts:545-555`）。
PATH_MODELS = "/api/models/available"
#: 登录回调路径（`src/lobsterai.ts:47`，对齐 `lobsterai2api/cmd/login/main.go:35` 的
#: `callbackPath`）；门户会校验 `redirect_uri` 必须长这个形状（`lobsterai-oauth.ts:96-97`）。
CALLBACK_PATH = "/auth/callback"

# —— 积分与签到端点（`src/lobsterai-credits.ts:36-40`） ——

#: 活动槽位查询（三步签到第一步）。
PATH_ACTIVITY_SLOT = "/api/client-activities/slot"
#: 活动上下文/动作前缀：第二步 `…/{activityCode}/context`、第三步 `…/{activityCode}/actions/check_in`。
PATH_ACTIVITY_CONTEXT = "/api/client-activities"
#: 积分余额端点。**用 `profile-summary` 而不是 `/api/user/quota`**：后者只显示
#: `freeCreditsTotal=300`、不含活动积分（实测某账号 profile-summary 5297.72 vs quota 300，
#: `lobsterai-credits.ts:297-303`）。
PATH_PROFILE_SUMMARY = "/api/user/profile-summary"

# —— 槽位查询的固定参数（照抄 `lobsterai-credits.ts:50-52`，值来自真实客户端观察） ——

SLOT_PLACEMENT = "desktop_sidebar"
SLOT_CONTAINER_API_VERSION = "2"
#: `platform=win32` 是**伪装客户端形态**：与运行环境无关，改了可能拿不到活动
#: （`lobsterai-credits.ts:46-49`：即使本程序跑在 macOS/Linux 上也照发 win32）。
SLOT_PLATFORM = "win32"

# —— 超时与缓存 ——

#: 控制面请求超时（秒）——`src/lobsterai.ts:50` `LOBSTERAI_REQUEST_TIMEOUT_MS = 30_000`。
REQUEST_TIMEOUT_S = 30.0
#: 客户端版本号缓存 TTL（秒）——`src/lobsterai.ts:60`（12 小时）。版本号是签到必填参数，
#: 不缓存会让每次签到多一次跨域请求；日期式版本号变更频率极低。
VERSION_CACHE_TTL_S = 12 * 60 * 60

#: **会话终止标记**（`src/lobsterai-errors.ts:73-75`）：响应体命中即 `refresh_token`
#: 被后端拒绝 → 重试无意义，只能重新登录（映射为 `accounts/types.py::NotRefreshable`）。
SESSION_DEAD_MARKERS = ("40100", "40101", "token rejected", "refresh token was rejected")
