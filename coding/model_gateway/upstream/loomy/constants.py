"""Loomy（讯飞 Loomy）产品私有常量：基址 / 端点 / 错误码 / 任务分值 / 兜底模型表。

🗂 证据面（只读；DSH 插件 `src/loomy*.ts`、`src/index.ts`；`docs/research/20 §3.1/§3.3`、
   `21 §1.1`）——本文件只放**已取证的字面量**，逻辑放 `sign.py` / `wechat.py` / `login.py` /
   `credits.py` / `models.py`，IO 编排只经 `product.py` 的十个冻结钩子。
🔴 纪律：**取不到就留空/不写**，不猜端点、不猜字段（M6-1 骨架纪律在 M6-3 的延续）。

两个基址（`loomy.ts:29-33`）——**业务与账号是两套**，认证方式也完全不同：

| 基址 | 用途 | 认证 |
|---|---|---|
| `API_BASE`（`loomyad.xunfei.cn/api/v1`） | 推理 / 模型列表 / 积分 / 新手任务 | 用户 `token` 头（chat 端点认 Bearer，见 `models.py`） |
| `ACCOUNT_BASE`（`account.xfinfr.com`） | 短信登录 / 微信绑定（讯飞 CAccount） | HMAC-SHA1 签名（`sign.py`），**与用户凭据无关** |

⚠️ **封套纪律**（`loomy.ts:80-104`）：业务失败**恒返回 HTTP 200**，成败只能读 body 的 `code`
   （成功 `000000`、登录失效 `100002`、参数错误 `100001`）。只看状态码会把「登录已失效」
   误判成成功 —— 本产品所有业务请求都必须拆封套。
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------- 宿主与基址 ----------

#: 业务端点基址（推理 / 模型列表 / 积分 / 新手任务；`loomy.ts:30`）。
#: 资源物化写入 `Resource.base_url` 的值 = 它（网关适配器按 `{base_url}/chat/completions` 拼接）。
API_BASE = "https://loomyad.xunfei.cn/api/v1"
#: 讯飞账号（CAccount）基址（`loomy.ts:33`）—— 仅短信登录与微信绑定用。
ACCOUNT_BASE = "https://account.xfinfr.com"

#: 业务成功码（`loomy.ts:36`）。
OK_CODE = "000000"
#: 登录失效码（`loomy.ts:39`）—— 收到它**不得重试**，应标记凭据失效并提示重新登录。
AUTH_ERROR_CODE = "100002"
#: 台账（**不设符号**：本网关没有需要按它分支的场景，`loomy.ts:42` 的 `100001`「参数错误」
#: 与其它业务码一样落 `failed/unknown` + 原始 message；引用为 0 的常量不进代码，见
#: `tests/unit/test_v2_wiring_guard.py` 的「公开符号必须有生产引用」纪律）。

#: 请求超时（秒）= `LOOMY_REQUEST_TIMEOUT_MS`（`loomy.ts:45` 的 60_000）。
REQUEST_TIMEOUT_S = 60.0
#: 模型目录请求超时（秒）= DSH `index.ts:843` 的 30_000（目录接口给 30s 足够）。
MODELS_TIMEOUT_S = 30.0

# ---------- 讯飞账号端点（HMAC-SHA1 签名；`loomy-oauth.ts`）----------

#: 下发短信验证码（独立短信登录，第 1 步；`loomy-oauth.ts:13,141`）。
SEND_SMS_PATH = "/login/phone/sendMsgCode"
#: 提交验证码完成登录（独立短信登录，第 2 步；`loomy-oauth.ts:14,173`）。
LOGIN_SMS_PATH = "/login/phone/checkCode"
#: 微信 code 换 `rcode` 并得知是否已绑手机号（`loomy-oauth.ts:223`）。
BIND_AUTH_PATH = "/login/thirdAccount/bind/auth"
#: 向待绑定手机号下发验证码（`loomy-oauth.ts:261`）。
BIND_SEND_MSG_PATH = "/login/thirdAccount/bind/sendMsg"
#: 验证并完成绑定 + 登录（`loomy-oauth.ts:287`）。
BIND_CHECK_CODE_PATH = "/login/thirdAccount/bind/checkCode"
#: 已绑手机号时跳过绑定、直接换 session（`loomy-oauth.ts:312`）。
BIND_SKIP_PATH = "/login/thirdAccount/bind/skip"

#: 短信验证码有效期（秒）= `LOOMY_SMS_CODE_TTL_SECONDS`（`loomy-oauth.ts:30`）。
SMS_CODE_TTL_S = 300
#: 登录会话有效期（秒）= 14 天 = `LOOMY_SESSION_TTL_SECONDS`（`loomy-oauth.ts:39`）。
#: ⚠️ 这只是向服务端**声明**的有效期：响应里不带到期时间戳，凭据的 `expires_at` 由本地推算
#: （`loomy-oauth.ts:35-38`、`loomy-auth.ts:277-279`）。
SESSION_TTL_S = 1_209_600

#: 讯飞 `appId`（账号请求体 `base.appid`；`loomy-product.ts:126`，取自客户端 `.env.prod`）。
ACCOUNT_APP_ID = "GM3LOOMY"
#: 讯飞账号 AccessKeyId（HMAC-SHA1 的 `account {ak}:{sig}` 前半；`loomy-product.ts:124`）。
ACCOUNT_ACCESS_KEY_ID = "2thryby66wxi53sk"
#: 讯飞账号 AccessKeySecret（HMAC-SHA1 的密钥；`loomy-product.ts:125`）。
ACCOUNT_ACCESS_KEY_SECRET = "zsak6eadrbawz683wf5r3m2snrwj868r"
#: 账号请求体 `base.ua`（`loomy-oauth.ts:65`）——**硬编码 macOS**，官方客户端在 Windows 上
#: 发的也是这个值，照抄不要改。
ACCOUNT_UA = "Loomy|Desktop|Electron|macOS"
#: 账号请求体 `base` 的其余固定字段（`loomy-oauth.ts:61-64`）。
ACCOUNT_MODEL_ID = "Web"
ACCOUNT_VERSION = "1.0.0"
ACCOUNT_DEVID = "web"

# ⚠️ **AccessKey 的定位**（`loomy-product.ts:19-23`，照抄不删）：它只用于**讯飞账号**端点
#    （`account.xfinfr.com`）的 HMAC-SHA1 签名（短信验证码登录）。业务与推理端点用的是用户
#    登录后的 `session`，与 AccessKey 无关。故 AccessKey 泄露不涉及任何用户数据。
#    它与 cline 的 `WORKOS_CLIENT_ID` 同类：**公开客户端标识**，不是用户密钥，
#    进源码不违反铁律 1（铁律 1 管的是 API Key / 用户令牌）。

# ---------- 业务端点（`API_BASE` 之下）----------
#
# 推理端点是 `POST {API_BASE}/chat/completions`（OpenAI 兼容 + 标准 SSE；`loomy.ts:24-27`、
# `loomy-adapter.ts:483`）—— **本模块不设该路径常量**：它是出站适配器的知识（M6-5 接线，
# `Resource.base_url` 已含 `/api/v1`，适配器按 `{base_url}/chat/completions` 拼接）。
# ⚠️ chat 端点**只认 `Authorization: Bearer`**（业务端点才认 `token`，`loomy.ts:13-20`）。

#: 模型目录（`index.ts:840-845`：`fetch(apiBase + '/models')`，**只认 `token` 头**）。
MODELS_PATH = "/models"
#: 积分两池 + 记录（**只读**，无副作用；`loomy-auth.ts:375`、`loomy-credits.ts:130`）。
#: ⚠️ 选它而不是 `first-login`：后者是**写**端点，在「打开面板」这种高频路径上调用会意外触发签到。
POINTS_RECORDS_PATH = "/points/records?pageNo=1&pageSize=1&recordType=all"
#: 每日额度签到（触发每日赠送额度；`loomy-credits.ts:216`）。幂等判据 = 响应体 `alreadyProcessed`。
POINTS_FIRST_LOGIN_PATH = "/points/first-login"
#: 新手任务状态（只读；`loomy-onboarding.ts:20`）。
ONBOARDING_TASKS_PATH = "/onboarding/tasks"
#: 完成单个新手任务（`loomy-onboarding.ts:21`；body 只有 `key`）。
ONBOARDING_COMPLETE_PATH = "/onboarding/tasks/complete"

#: 「一键签到」的语义说明（`loomy-credits.ts:50`）—— 供 UI 文案用，
#: **不要**写成「+5000 积分」：`dailyBalance = dailyQuota - dailyConsumed`，消耗后不回补。
DAILY_QUOTA_DESCRIPTION = "每日赠送额度（消耗后不回补）"

# ---------- 微信开放平台（扫码登录；`loomy-wechat.ts`）----------

#: 微信开放平台「网站应用」AppID（`loomy-wechat.ts:33`，取自客户端 `.env.prod`）。
WECHAT_APP_ID = "wx18d60be432287cf8"
#: 微信授权回调地址（`loomy-wechat.ts:43`）—— **必须是这个官方地址**：微信校验域名白名单，
#: 换本地地址或任意域名会得到「redirect_uri 参数错误」；它实际返回 404，但本链路只把它当
#: 白名单占位，`code` 是从长轮询拿到的（`loomy-wechat.ts:24-30`）。
WECHAT_REDIRECT_URI = "https://loomy.xunfei.cn/oauth/wechat/callback"
#: 授权页 + 二维码图片宿主（`loomy-wechat.ts:117,156`）。
WECHAT_OPEN_ORIGIN = "https://open.weixin.qq.com"
#: 长轮询宿主（`loomy-wechat.ts:263`）。
WECHAT_LONG_ORIGIN = "https://long.open.weixin.qq.com"
#: 扫码请求统一带的浏览器 UA（`loomy-wechat.ts:100-101`）—— 微信对空 UA / 爬虫 UA 可能拒绝。
WECHAT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
#: 长轮询的**连接/写/池**超时上限（秒）= `LOOMY_WECHAT_POLL_TIMEOUT_MS`（`loomy-wechat.ts:46`
#: 的 40_000）—— 微信侧约 25 秒无状态变化才返回，故给足余量。
#: ⚠️ M7-C1：**读**超时不再用它（40s 会把一个管理端请求按住 40s），读预算见下一条。
WECHAT_POLL_TIMEOUT_S = 40.0
#: 管理端**单轮**状态查询的读预算（秒，M7-C1）：到点即「这一轮没有状态变化」→ `waiting`。
#: 取值理由 = 前端轮询节奏 `accounts.js::POLL_MS = 2000`：一轮在读预算内落定，
#: 下一次轮询才会在自己那一轮里看到新状态（预算 > 节奏只会让请求排队，换不来更快感知）。
#: 🔴 不丢事件的依据：长轮询按 `last=` 续查，微信在状态变化时立即回帧（`wechat.poll_once` 的
#: `budget_s` 段），DSH 自己那条本机页面通道也是「一轮完了再起一轮」的同形节奏。
WECHAT_POLL_BUDGET_S = 2.0
#: 拉授权页 / 下载二维码图片的超时（秒）= `loomy-wechat.ts:173,207` 的 30_000。
WECHAT_FETCH_TIMEOUT_S = 30.0
#: 二维码图片的最小可信字节数（`loomy-wechat.ts:216` 的 `bytes.length < 200`）：
#: 小于它说明拿回来的不是图（错误页/空响应），宁可报错也不给用户看一张花图。
#: 实测正常值约 47KB（JPEG）。
MIN_QR_IMAGE_BYTES = 200

#: 长轮询 errcode 语义（`loomy-wechat.ts:72-85`，**以微信授权页内嵌 JS 为准**——
#: 那是官方源码，不是推测）。⚠️ 404 与 405 极易读反：404 = 已扫码**待确认**（继续轮询），
#: 405 = **已确认**且 `wx_code` 就在这一帧（DSH 真实缺陷，用户报障「扫码后没有跳转」）。
WECHAT_ERR_WAITING = "408"     # 待扫码（常态）
WECHAT_ERR_SCANNED = "404"     # 已扫码，等用户在手机上点确认
WECHAT_ERR_CONFIRMED = "405"   # 已确认，`wx_code` 在本帧
WECHAT_ERR_CANCELLED = "403"   # 用户取消
WECHAT_ERR_EXPIRED = "402"     # 二维码失效

# ---------- 新手任务（`loomy-onboarding.ts`）----------

#: 任务 key → 积分（`loomy-onboarding.ts:46-55`，照抄官方客户端
#: `electron/onboarding-service.js:18-27` 的 `TASK_POINTS`；其单测断言各项之和 === 10000）。
#: 顺序即执行顺序。
TASK_POINTS: dict[str, int] = {
    "first_message": 500,
    "pick_skill": 1000,
    "generate_ppt": 1500,
    "set_schedule": 1000,
    "install_skill": 1500,
    "configure_remote": 1000,
    "create_soul": 1500,
    "share_soul": 2000,
}

#: 任务 key → 中文标题（`loomy-onboarding.ts:58-67`，客户端 `GE` 注册表的 `title`）。
TASK_TITLES: dict[str, str] = {
    "first_message": "发送你的第一条消息",
    "pick_skill": "试试选择一个技能",
    "generate_ppt": "生成第一份 PPT",
    "set_schedule": "设置定时任务",
    "install_skill": "在技能广场安装一个技能",
    "configure_remote": "配置远程控制",
    "create_soul": "创建你的第一个搭子",
    "share_soul": "把搭子分享给朋友",
}

#: 新手任务积分合计（`loomy-onboarding.ts:70`）。
#: ⚠️ **不采信服务端 `earned`**，按本表**本地现算**（`loomy-onboarding.ts:26-28`：
#: 服务端回传的 `earned` 只是参考，历史上出现过与本地表不一致；官方自己也这么做）。
ONBOARDING_TOTAL = 10_000

# ---------- 兜底模型目录（`loomy-product.ts:92-113`）----------

#: 实测的思考档位：8 个 chat 模型**完全一致**（`loomy-product.ts:92`，2026-09-28 真实凭据采集）。
#: 远端可用时**优先用远端的 `reasoning_efforts`**，本常量只在远端整体失败时顶替。
LOOMY_EFFORTS: tuple[str, ...] = ("none", "low", "medium", "high", "xhigh")

# ⚠️ 默认思考档**不设符号**：DSH 有意不沿用远端的 `default_reasoning_effort: low`，改用
#    `high`（`loomy-product.ts:94-102`）；而 §22.3 的 `ModelInfo` **没有** `default_effort`
#    字段（同 buddy 的 `defaultReasoningEffort` 登记缺口）→ 本网关不搬运默认档，
#    故没有可接线的常量（详见 `models.py::fallback_models` 的说明）。


@dataclass(frozen=True)
class FallbackModel:
    """兜底表条目（`loomy-product.ts:29-46` 的 `LoomyFallbackModel` 的搬运形态）。"""

    id: str
    #: **已规范化**的展示名（含倍率，` · x{n}` 分隔；`loomy-product.ts:78-83` 的口径）。
    name: str
    context_window: int


#: 兜底模型目录（8 个 chat 模型；`loomy-product.ts:104-113` 逐条照抄）。
#: 来源：2026-09-26 实测 `GET /api/v1/models` 取 `type === 'chat'` 的条目；
#: 顺序**照抄远端返回顺序**，不重排（`loomy-product.ts:76-77`）。
#: ⚠️ `spark-x` 的 `context_length` 是**已知分歧**：远端声明 1048576，而 Loomy 客户端用本地表
#: 强制降到 262144；本表**先采信远端**（`loomy-product.ts:79-83`）。
FALLBACK_MODELS: tuple[FallbackModel, ...] = (
    FallbackModel(id="deepseek-v4-flash-0731", name="DeepSeek V4 Flash 0731 · x3.0",
                  context_window=1_048_576),
    FallbackModel(id="MiniMax-M3", name="MiniMax M3 · x4.0", context_window=1_048_576),
    FallbackModel(id="Kimi-k2.6", name="Kimi k2.6 · x6.5", context_window=262_144),
    FallbackModel(id="qwen-3.8-max", name="Qwen 3.8 Max · x12.0", context_window=1_000_000),
    FallbackModel(id="GLM-5.3-Flash", name="GLM 5.3 Flash · x0.8", context_window=1_048_576),
    FallbackModel(id="qwen3.8-flash", name="qwen 3.8 flash · x0.8", context_window=1_000_000),
    FallbackModel(id="spark-x", name="Spark X2.5 · x0.1", context_window=1_048_576),
    FallbackModel(id="mimo-v2.5", name="MiMo V2.5 · x3.3", context_window=1_048_576),
)
