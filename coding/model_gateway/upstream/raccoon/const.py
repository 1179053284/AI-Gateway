"""Raccoon（商汤小浣熊）产品私有常量：端点 / 请求头取值 / 超时 / 兜底模型表。

🗂 证据面（只读）：DSH 插件 `src/raccoon.ts`、`src/raccoon-product.ts`、`src/raccoon-oauth.ts`、
   `src/raccoon-credits.ts`、`src/raccoon-auth.ts`、`src/raccoon-adapter.ts`；
   调研落点 `docs/research/20 §2.7/§3.1/§4.1`、`21 §1.1`。
🔴 纪律：**取不到就不写**（不猜端点、不猜字段）；本文件只放**已取证**的字面量，
   纯逻辑放 `protocol.py`，IO 放 `login.py` / `models.py`，接线在 `product.py`。

**本产品的三条硬事实（都会影响实现，逐条有证）**：

1. **每日 300 积分没有签到端点** —— 服务端按日自动发放（账单 `biz_type: 'daily_grant'`），
   故能力位 `checkin=False`，`claim` 不得打上游（`raccoon-credits.ts:12-18`、
   `credits-capabilities.js:117-121`；`20 §3.1`）。
2. **登录是「本地页承载」的扫码 / 短信双路径** —— 扫码 `code` 由**客户端本地随机生成**
   （实测服务端接受任意自造 code 并进入 `pending`），绕开官方那条收不到的
   `office-raccoon://auth/callback` 自定义协议回调（`raccoon.ts:10-15`、
   `raccoon-oauth.ts:111-130`、`raccoon-login-page.ts:1-33`）。
3. **`desktop/v1/login/points/grant` 必需 `X-Client-Platform` 头**，取值只允许
   `desktop-windows` / `desktop-macos` / `desktop-linux`（`raccoon-product.ts:175-183`）；
   实际发送点在 `raccoon-credits.ts:87-90`（`raccoonHeaders({platform, version})`）、
   要求写在 `:171-173` 的注释（任务书/`20 §3.1` 把这条引作 `:268` —— 那是 DSH 便捷包装处）。
"""

from __future__ import annotations

import sys

from model_gateway.accounts.types import ModelInfo

# ---------- 宿主与端点前缀（`raccoon.ts:25-34`；基址来源 = 官方 `app.asar` 的 `.env.electron`）----------

#: API 基址（`raccoon.ts:25`）
API_BASE = "https://xiaohuanxiong.com"
#: 认证端点前缀（`raccoon.ts:28`）
AUTH_PREFIX = "/api/web/auth/v1"
#: 推理与模型目录前缀（`raccoon.ts:30`）
LLM_PREFIX = "/api/web/llm/v2"
#: 积分端点前缀（`raccoon.ts:32`）
POINTS_PREFIX = "/api/web/points/v1"
#: 桌面端端点前缀（含一次性登录奖励，`raccoon.ts:34`）
DESKTOP_PREFIX = "/api/web/desktop/v1"

# ---------- 端点路径（逐条附 DSH `file:line`）----------

#: 扫码登录状态轮询（`raccoon-oauth.ts:148`；请求体 `{"qrcode_code": code}`）
LOGIN_QRCODE_PATH = f"{AUTH_PREFIX}/login_with_qrcode_code"
#: 下发短信验证码（`raccoon-oauth.ts:196`；体 `{captcha_param, nation_code, phone(加密)}`）
SEND_SMS_PATH = f"{AUTH_PREFIX}/send_sms"
#: 短信验证码登录（`raccoon-oauth.ts:225`；体 `{nation_code, phone(加密), sms_code}`）
LOGIN_SMS_PATH = f"{AUTH_PREFIX}/login_with_sms"
#: 凭据续期（`raccoon-oauth.ts:295`；体 `{"refresh_token": ...}`）
REFRESH_PATH = f"{AUTH_PREFIX}/refresh"
#: 用户信息（只读；`raccoon-oauth.ts:336`）—— 探活与登录后补全昵称/手机号的端点
USER_INFO_PATH = f"{AUTH_PREFIX}/user_info"
#: 积分余额（**只读**，`raccoon-credits.ts:135`；返回 `available_points` 等四个池）
BALANCE_PATH = f"{POINTS_PREFIX}/balance"
#: 积分账单（只读，`raccoon-credits.ts:234`；登录奖励的「是否已领」只能靠它反查）
BILLS_PATH = f"{POINTS_PREFIX}/bills"
#: 一次性登录奖励（3000 分，幂等；⚠️ **必需 `X-Client-Platform` 头**，`raccoon-credits.ts:182`）
LOGIN_POINTS_GRANT_PATH = f"{DESKTOP_PREFIX}/login/points/grant"
#: 模型目录（`raccoon-auth.ts:476`）
MODEL_CATALOG_PATH = f"{LLM_PREFIX}/model_catalog"
# 推理端点 = `POST {apiBase}/api/web/llm/v2/chat/completions`（**标准 OpenAI 兼容 + 标准 SSE**，
# `raccoon-adapter.ts:6,427`）—— M6-5 出站适配按它与 `registry.base_url` 拼接
# （`base_url` 已含 `/api/web/llm/v2`，见 `accounts/registry.py` 的 raccoon 块）。

#: 二维码承载的微信登录页（`raccoon-oauth.ts:127-130`；`appname` 由 DSH 原文照抄）
QR_PAGE_PATH = "/login/mp"
QR_PAGE_APPNAME = "商汤小浣熊官网"

# ---------- 扫码状态机（`raccoon.ts:64-69`）----------

QR_STATUS_PENDING = "pending"
QR_STATUS_LOGGING = "logging"
QR_STATUS_CANCELED = "canceled"
QR_STATUS_SUCCESS = "success"

# ---------- 客户端身份（`raccoon-product.ts:266-289`）----------

#: 客户端版本（`raccoon-product.ts:280`；`X-Client-Version` 取值）
CLIENT_VERSION = "v1.0.35"

#: `X-Client-Platform` 的三个合法取值（`raccoon-product.ts:175-183`：
#: 依据主进程 `desktopDeviceIdentity.js` 的 `resolveDesktopClientPlatform` —— `win32` →
#: `desktop-windows`）。猜错会被 `login/points/grant` 拒绝。
PLATFORM_WINDOWS = "desktop-windows"
PLATFORM_MACOS = "desktop-macos"
PLATFORM_LINUX = "desktop-linux"

#: 语言头（`raccoon.ts:281`）
LANGUAGE = "zh"

# ---------- 业务码（只列**用到**的；DSH `file:line` 逐条附）----------

#: 手机号未加密 / 加密参数错误（`raccoon.ts:17`：`100003 params_encryted_error`）
CODE_PHONE_ENCRYPT_ERROR = 100003
#: 阿里云滑块校验失败（`raccoon-oauth.ts:205`：`100006 captcha_verify_error`）
CODE_CAPTCHA_VERIFY_ERROR = 100006
#: 登录态过期（`raccoon-oauth.ts:299`：续期时判「需重新登录」）
CODE_SESSION_EXPIRED = 200003

# ---------- 一次性登录奖励（`raccoon-credits.ts:8-18,38-41,228-258`）----------

#: 登录奖励默认额度（服务端未在 popup 里给出时的兜底，`raccoon-credits.ts:38`）
LOGIN_REWARD_POINTS = 3000
#: 登录奖励在账单里的 `event_name`（`raccoon-credits.ts:41`）——「是否已领」的唯一判据
LOGIN_REWARD_EVENT_NAME = "桌面端登录奖励"
#: 账单类型：奖励发放（`raccoon-credits.ts:251`）。⚠️ **必须叠加 event_name** ——
#: 「新人注册礼包」也是 `reward_grant`，只看它会误报「已领取」（`raccoon-credits.ts:221-224`）。
BILL_BIZ_REWARD_GRANT = "reward_grant"

# ---------- 超时（`raccoon.ts:55`：60s；显式给 httpx，§22.8-1）----------

REQUEST_TIMEOUT_S = 60.0

# ---------- 凭证 / JWT ----------

#: 手机号 AES-128-CFB 传输层密钥（`raccoon.ts:43`）。**公开常量**（官方客户端把它硬编码在
#: 前端 bundle 里），只用于避免手机号明文出现在日志/代理，不是安全边界。
PHONE_CIPHER_SECRET = "senseraccoon2023"

# ---------- 模型目录 ----------

#: 远端目录里视为「支持图片输入」的 tags（`raccoon-auth.ts:180`）
VISION_TAGS: tuple[str, ...] = ("vision", "image", "image-understanding")

#: 思考档位：**只有开 / 关**（`raccoon-product.ts:73-119`）。
#:
#: ⚠️ `reasoning_effort`（8 个枚举）被服务端接受但**实测无效果**（8 轮配对实验，正负各 4 次）；
#: 唯一有效通道是 `extra_body.thinking.type`；且它是 **provider 级方言**（与模型无关）——
#: 所有可见模型都返回这两档（`raccoon-product.ts:100-110`）。故 `ModelInfo.effort_levels`
#: 对所有模型一致，不做 per-model 分派（那会是凭空猜测）。
REASONING_EFFORTS: tuple[tuple[str, str], ...] = (("on", "开启"), ("off", "关闭"))

#: 兜底模型目录（6 个 `visible:true` 模型）—— **逐条照抄** DSH `RACCOON_FALLBACK_MODELS`
#: （`raccoon-product.ts:218-263`）。来源：2026-09-26 用本机登录态实测
#: `GET /api/web/llm/v2/model_catalog` 取 `visible:true` 的 6 条；顺序**照抄远端返回顺序**。
#:
#: ⚠️ **不含** `Raccoon-Auto`（它是客户端 i18n 条目渲染的「自动选模」入口，直接发给
#: `chat/completions` 会 404）与 3 个 `visible:false` 的 `raccoon-*` 内部模型
#: （`raccoon-product.ts:213-217`）。
#: `tool_call` 恒 `None`：DSH 未声明工具能力 → 不编造（`21 §5.1-1`）。
#: `vendor` 留空：远端不声明厂商（同 buddy/cline 口径）。
#: `free` / `rate` = 结构化计费（2026-10-01 补），取值逐条对照 DSH 表注释里的
#: 「原价 / 生效价」实测表（`raccoon-product.ts:206-212` 的表格）与 `billing_info` 同判据：
#: 生效价 0 → `free=True` + `rate="x0"`（展示名仍是「免费」）；促销 → `x原价→x折后价`。
FALLBACK_MODELS: tuple[ModelInfo, ...] = (
    ModelInfo(id="sn-sensenova-6-8-flash", name="SenseNova-6.8-Flash · 免费",
              context_window=256_000, max_output=63_999, image_input=True,
              free=True, rate="x0"),
    ModelInfo(id="sn-sensenova-6-8-flash-lite", name="SenseNova-6.8-Flash-Lite · 免费",
              context_window=256_000, max_output=63_999, image_input=True,
              free=True, rate="x0"),
    ModelInfo(id="sn-glm-5-3", name="GLM-5-3 · x0.75",
              context_window=1_000_000, max_output=100_000, image_input=True,
              free=False, rate="x0.75"),
    # ⚠️ 1 倍也要显示倍率（用户报障纠正过：省略会让该模型看起来「没有计费信息」，
    # `raccoon.ts:232-236`）
    ModelInfo(id="sn-kimi-k3", name="Kimi-K3 · x1",
              context_window=1_000_000, max_output=100_000, image_input=True,
              free=False, rate="x1"),
    ModelInfo(id="sn-glm-5-3-flash", name="GLM-5-3-Flash · x0.2→x0.1",
              context_window=1_000_000, max_output=100_000, image_input=False,
              free=False, rate="x0.2→x0.1"),
    ModelInfo(id="sn-deepseek-v4-1-flash", name="DeepSeek-V4.1-Flash · x0.25",
              context_window=1_000_000, max_output=100_000, image_input=False,
              free=False, rate="x0.25"),
)


def client_platform(platform: str | None = None) -> str:
    """`X-Client-Platform` 取值（按宿主平台解析，照抄 `resolveDesktopClientPlatform` 语义）。

    `raccoon-product.ts:175-183`：取值**必须**是 `desktop-windows` / `desktop-macos` /
    `desktop-linux` 三者之一（由主进程把 `win32` 映射成 `desktop-windows`）。DSH 插件把
    `desktop-windows` 写死在产品配置里（它只发 Windows 版）；本网关跑在用户自己的机器上，
    故按 `sys.platform` 如实映射 —— 猜错会被 `login/points/grant` 拒绝。

    `platform` 形参仅供单测注入（省略 = 取 `sys.platform`）。
    """
    raw = sys.platform if platform is None else platform
    if raw.startswith("win"):
        return PLATFORM_WINDOWS
    if raw == "darwin":
        return PLATFORM_MACOS
    return PLATFORM_LINUX
