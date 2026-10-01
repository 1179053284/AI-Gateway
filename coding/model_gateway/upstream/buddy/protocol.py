"""CodeBuddy 系（buddy / workbuddy）**共享协议面**：常量 / 产品档案 / 纯解析。

tech-design v2.0 §22.3/§22.4；本模块是 buddy 与 workbuddy **唯一一份**私有协议实现
（§22.1：抽象只做在 ≥2 个产品已被证实的共性上）——两者同源：同一 CLI 内核、同一认证协议
（cli-external-link）、同一套计费/签到端点，差异全部收敛为 `ProductProfile` 参数
（platform / X-Product-Code / User-Agent / 登录 URL 附加参数 / 兜底模型表）。

🔴 取证来源（只读）：DSH 插件 `src/product.ts` / `src/buddy.ts` / `src/buddy-oauth.ts` /
   `src/credits.ts` / `src/jet-hub-rpc.ts`；每个常量与解析规则都给出 `file:line`。
   **取不到的字段一律空/None，不编造**（§22.3「取不到不编造」）。
🔴 本模块**无网络、无副作用**（纯常量 + 纯函数）；网络流程在 `buddy/hooks.py`。
🔴 命名纪律：本文件与 `hooks.py` **不得写出刷新钩子的函数定义字面量**（仓内死代码护栏
   `tests/unit/test_v2_cli_zcode.py:182-197` 对 `upstream/*/product.py` 之外的**所有**文件做
   该字面匹配），故刷新实现的函数名是 `refresh_credential`，冻结钩子名在 `product.py` 别名导出。
"""

from __future__ import annotations

import base64
import json
import math
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from model_gateway.accounts.registry import get as registry_get
from model_gateway.accounts.types import ModelInfo

# ── 端点路径（全部以 `product.endpoint` 为基址，`product.ts:80-82`；
#    路径常量见 `buddy.ts:28-39`、`credits.ts:33-51`）─────────────────────────
#: 取 auth state（**免认证**）：`POST /v2/plugin/auth/state?platform=<platform>`（`buddy.ts:29`）
AUTH_STATE_PATH = "/v2/plugin/auth/state"
#: 轮询 token（**免认证**）：`GET /v2/plugin/auth/token?state=...`（`buddy.ts:31`）
AUTH_TOKEN_PATH = "/v2/plugin/auth/token"
#: 轮询账户信息（**需 Bearer**）：`GET /v2/plugin/login/account?state=...`（`buddy.ts:33`）
LOGIN_ACCOUNT_PATH = "/v2/plugin/login/account"
#: 静默续期：`POST /v2/plugin/auth/token/refresh`（`buddy.ts:35`）
AUTH_REFRESH_PATH = "/v2/plugin/auth/token/refresh"
#: 云端配置（模型目录/agents）：`GET /v3/config`（`buddy.ts:39`）
CONFIG_PATH = "/v3/config"

#: 签到活动状态（**权威状态源**，非 `checkin-status`——后者返回占位数据，`credits.ts:11-13`）
CHECKIN_ACTIVITY_STATUS_PATH = "/v2/billing/meter/checkin-activity-status"
#: 每日签到领取（`credits.ts:35`）
DAILY_CHECKIN_PATH = "/v2/billing/meter/daily-checkin"
#: 积分余额（**两产品通用**，只有 baseURL 不同，`credits.ts:39-50`）
USER_RESOURCE_PATH = "/v2/billing/meter/get-user-resource"

# ── 轮询/请求超时（毫秒 → 秒）───────────────────────────────────────────
#: `auth/state` 请求超时：DSH 原为 5s，实测国际版 5.86–7.53s **必超时** → 放宽到 10s（`buddy.ts:47-60`）
STATE_TIMEOUT_S = 10.0
#: 其余控制面请求（token/account/refresh/config/billing）超时（`buddy.ts:62`）
REQUEST_TIMEOUT_S = 60.0
#: DSH 的登录轮询节奏（1s 间隔 / 5min 总超时，`buddy.ts:44-46`）——本网关**不在钩子里
#: 打循环**：轮询由入口层驱动、总时限由会话 TTL 600s 兜住（§22.8-2），钩子内不 sleep。

# ── 业务码（响应体 `code` 为准，**不能只看 HTTP 状态**，`credits.ts:19-21`）────
CODE_OK = 0
#: token 尚未就绪 → 继续轮询（`buddy.ts:67`）
CODE_TOKEN_NOT_READY = 11217
#: 账户信息尚未完成 → 继续轮询（`buddy.ts:69`）
CODE_ACCOUNT_NOT_READY = 12151
#: 「今天已签到」实测值（`credits.ts:57`）
CODE_ALREADY_CLAIMED = 10001
#: 静态分析列出的备选码：1001=已领取（`credits.ts:59-61`）
CODE_ALREADY_CLAIMED_ALT = 1001
#: 1002=无资格；1003=活动结束（`credits.ts:60-61`）
CODE_NO_QUALIFICATION = 1002
CODE_ACTIVITY_ENDED = 1003

# ── HTTP 头名（`buddy.ts:73-83`；推理面三个术语头是 `buddy-adapter.ts:1573-1577` 的内联字面量）──
HEADER_DOMAIN = "X-Domain"
HEADER_ENTERPRISE_ID = "X-Enterprise-Id"
HEADER_TENANT_ID = "X-Tenant-Id"
HEADER_NO_AUTHORIZATION = "X-No-Authorization"
HEADER_NO_USER_ID = "X-No-User-Id"
HEADER_NO_ENTERPRISE_ID = "X-No-Enterprise-Id"
HEADER_NO_DEPARTMENT_INFO = "X-No-Department-Info"
HEADER_REFRESH_TOKEN = "X-Refresh-Token"
HEADER_AUTH_REFRESH_SOURCE = "X-Auth-Refresh-Source"
HEADER_PRODUCT = "X-Product"
HEADER_PRODUCT_CODE = "X-Product-Code"
#: 用量归属头族（`buddy-adapter.ts:1570-1577` 的注释：后台「使用端」列按这组头归因，
#: 缺任一个都显示为 `-`）——**只在推理面发**，计费/配置面没有这组头
HEADER_AGENT_PURPOSE = "X-Agent-Purpose"
HEADER_IDE_NAME = "X-IDE-Name"
HEADER_IDE_TYPE = "X-IDE-Type"
HEADER_IDE_VERSION = "X-IDE-Version"

#: 推理面 `X-Agent-Purpose` 取值（`buddy-adapter.ts:1573`）
AGENT_PURPOSE_CONVERSATION = "conversation"

#: 计费/签到面与云端配置面的 `X-Product` = **部署类型**（两产品共用同一取值，随产品变化的
#: 是 X-Product-Code）：`buddy-oauth.ts:360-363`（`/v3/config`）、`credits.ts:236`（计费端点）。
#: 🔴 **只许这两个面用**：推理面的同名字段是**归属名**（见 `inference_headers` / `_ATTRIBUTION`）
#: —— 把这里的 `SaaS` 套到推理面，正是 DSH 记录在案的「后台归因不到产品」的历史 bug
#: （`buddy-adapter.ts:1570-1572` 的复盘；M6-F3 的根因）。
DEPLOYMENT_TYPE = "SaaS"
#: 刷新来源标识（`buddy.ts:95`）
AUTH_REFRESH_SOURCE = "ide-main"

#: 资源包 `Status` = 3 → 已过期（`credits.ts:437-443` 实测值）
PACKAGE_STATUS_EXPIRED = 3

#: `/v3/config` 承载「输入框可选模型」的 agent 名，按优先级（`buddy.ts:828-833`）：
#: `cli` = 企业模型端点用，`craft` = `/v3/config` 用（两者不会同时出现）
PREFERRED_AGENT_NAMES = ("cli", "craft")


@dataclass(frozen=True)
class ProductProfile:
    """一个 CodeBuddy 系产品的**身份标识**（差异全部收敛在这里，`product.ts:74-156`）。

    🔴 刻意**不存 base_url**：基址的唯一事实源是 `accounts/registry.py`（§22.4/M6-2 回填），
       `X-Domain`（`api_domain`）由它的主机名派生 —— 证据：`X-Domain` **必须与请求 baseURL
       一致**，跟着凭据里的 `domain` 走会把身份标识发到另一区域（`credits.ts:222-228`）。
    """

    #: provider id（= `accounts/registry.py` 的键 = 账号目录名）
    id: str
    #: `auth/state` 查询参数（`product.ts:78,270,383`）
    platform: str
    #: `X-Product-Code`（随产品变化，`product.ts:92,274,387`）
    product_code: str
    #: 默认 User-Agent（腾讯后台按 UA 归因「使用端」，必须含品牌字样，`product.ts:93-99`）
    user_agent: str
    #: 远端不可用时的**兜底模型目录**（字段对齐 `BuddyFallbackModel`，`product.ts:32-51`）。
    #: 语义见 `product.ts:126-135`：这是 IDE `product.json` 内置的静态表，
    #: **远端配置只是覆盖层** —— 故合并时以它为主集、远端逐字段优先。
    fallback_models: tuple[ModelInfo, ...] = ()
    #: 登录 URL 是否追加 `version` 与 `loginSessionId`（`product.ts:137-143`）
    append_session_params: bool = False
    #: 追加到登录 URL 的版本号（`product.ts:142-143`）
    plugin_version: str = ""

    @property
    def title(self) -> str:
        """产品显示名（唯一事实源 = 注册表）。"""
        return registry_get(self.id).title

    @property
    def base_url(self) -> str:
        """上游基址（唯一事实源 = 注册表；§22.4 该列由 M6-2 取证回填）。"""
        return registry_get(self.id).base_url

    @property
    def api_domain(self) -> str:
        """`X-Domain` 头取值 = 基址主机名（`credits.ts:230-235`）。"""
        return urlparse(self.base_url).hostname or ""


# ── 请求头构造（逐端点对齐 DSH，不自创）────────────────────────────────

def state_headers(profile: ProductProfile) -> dict[str, str]:
    """`auth/state` 头（**免认证**，四个 `X-No-*` 全为 `true`，`buddy-oauth.ts:143-150`）。"""
    return {
        HEADER_DOMAIN: profile.api_domain,
        HEADER_NO_AUTHORIZATION: "true",
        HEADER_NO_USER_ID: "true",
        HEADER_NO_ENTERPRISE_ID: "true",
        HEADER_NO_DEPARTMENT_INFO: "true",
        "User-Agent": profile.user_agent,
    }


def token_poll_headers(profile: ProductProfile) -> dict[str, str]:
    """`auth/token` 头（只需 `X-No-Authorization` + UA，`buddy-oauth.ts:192-195`）。"""
    return {HEADER_NO_AUTHORIZATION: "true", "User-Agent": profile.user_agent}


def account_headers(profile: ProductProfile, token: dict) -> dict[str, str]:
    """`login/account` 头（Bearer + 两个 `X-No-*`，`buddy-oauth.ts:246-252`）。

    与 DSH 的差异（有意）：`X-Domain` 取**产品基址主机名**而非 `token.domain`
    —— `token.domain` 可能为空，且请求 baseURL 恒为本产品基址，两者必须一致
    （`credits.ts:222-228` 对同类错配的实测复盘）。
    """
    del token  # 形参保留：DSH 该端点用 token.domain；本实现按上面注释统一取产品域名
    return {
        HEADER_DOMAIN: profile.api_domain,
        HEADER_NO_USER_ID: "true",
        HEADER_NO_ENTERPRISE_ID: "true",
        "User-Agent": profile.user_agent,
    }


def identity_headers(profile: ProductProfile, cred: dict, *, domain: str = "") -> dict[str, str]:
    """**计费/额度/签到面**的账号身份头（照抄 `credits.ts:230-247` 的 `checkinHeaders`）。

    🔴 本族有**三个面**，头集合各不相同，**不得互相套用**（M6-F3 的根因就是把计费面
    取值套到推理面）：

    | 面 | 函数 | `X-Product` | 出处 |
    |---|---|---|---|
    | 计费/额度/签到 | 本函数 | **部署类型** `SaaS` | `credits.ts:230-247` |
    | 云端配置 `/v3/config` | `config_headers` | 部署类型 `SaaS` | `buddy-oauth.ts:355-364` |
    | **推理** `/v2/chat/completions` | `inference_headers` | **归属名**（产品名） | `buddy-adapter.ts:1564-1581` |

    调用方（现状）：`hooks.py` 的 `probe` / `quota` / `claim` 三处（都是计费端点）。
    `X-User-Id` / `X-Enterprise-Id` / `X-Tenant-Id` 属**本面专属**（`credits.ts:238-244`），
    推理面不发它们（见 `inference_headers` 的有意差异 ②）。

    `domain`：`X-Domain` 的**覆盖值**（缺省 = `profile.api_domain` = 注册表基址主机名）。
    取证口径：`X-Domain` 必须与请求 baseURL 一致（跟着凭据里的 `domain` 走会把身份标识
    发到另一区域，`credits.ts:222-228`）。
    """
    token = access_token_of(cred)
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        HEADER_DOMAIN: domain or profile.api_domain,
        HEADER_PRODUCT: DEPLOYMENT_TYPE,
        HEADER_PRODUCT_CODE: profile.product_code,
        "User-Agent": profile.user_agent,
    }
    if read_str(cred, "user_id"):
        headers["X-User-Id"] = read_str(cred, "user_id")
    if read_str(cred, "enterprise_id"):
        headers[HEADER_ENTERPRISE_ID] = read_str(cred, "enterprise_id")
        headers[HEADER_TENANT_ID] = read_str(cred, "enterprise_id")
    return headers


#: 推理面**归属头取值**：`X-Product` / `X-IDE-Name` / `X-IDE-Type` 三头共用 `attributionName`，
#: `X-IDE-Version` = `clientVersion`。逐条照抄 DSH `product.ts`（取值面已取证，不是空缺）：
#:   · buddy     → `product.ts:278`（`'CodeBuddy'`）+ `product.ts:279`（`'1.106.1'`）
#:   · workbuddy → `product.ts:401`（`'WorkBuddy'`）+ `product.ts:402`（`'5.5.2'`）
#: 语义（`product.ts:112-120`）：`X-Product` 是**用量归属名**（产品名），不是部署类型；
#: 缺这组头时后台「使用端」列显示 `-`（`buddy-adapter.ts:1570`）。
_ATTRIBUTION_BY_PRODUCT: dict[str, tuple[str, str]] = {
    "buddy": ("CodeBuddy", "1.106.1"),
    "workbuddy": ("WorkBuddy", "5.5.2"),
}


def _attribution_of(profile: ProductProfile) -> tuple[str, str]:
    """`(attributionName, clientVersion)`；本族档案未登记 → 当场 `ValueError`。

    不猜、不静默降级：归属名决定上游后台把用量记到哪个产品名下，编一个就等于
    "把账单记到别人头上"（`product.ts:112-120` 的历史 bug 复盘）。
    """
    try:
        return _ATTRIBUTION_BY_PRODUCT[profile.id]
    except KeyError as e:
        raise ValueError(
            f"{profile.id!r} 未登记推理面归属头取值（`X-Product` / `X-IDE-*`）—— "
            "拒绝构造身份头：归属名无法从凭据或基址推导，编造只会让后台归因错产品"
            "（`product.ts:112-120`）") from e


def inference_headers(profile: ProductProfile, cred: dict, *, domain: str = "") -> dict[str, str]:
    """**推理面**（`POST {base}/v2/chat/completions`）身份头 —— 逐条对齐
    `buddy-adapter.ts:1564-1581` 的 `send()`：

    | 头 | 取值 | 取证 |
    |---|---|---|
    | `Authorization` | `Bearer <access_token>` | `buddy-adapter.ts:1565` |
    | `X-Domain` | 实际请求基址主机名（见有意差异 ①） | `:1568` |
    | `X-Product-Code` | `profile.product_code` | `:1569` |
    | `X-Agent-Purpose` | `conversation` | `:1573` |
    | `X-IDE-Name` / `X-IDE-Type` | 归属名 | `:1574-1575` + `product.ts:112-120` |
    | `X-IDE-Version` | 客户端形态版本号 | `:1576` + `product.ts:120` |
    | `X-Product` | **归属名**（`'CodeBuddy'` / `'WorkBuddy'`，**不是** `SaaS`） | `:1577` + `product.ts:278/401` |
    | `User-Agent` | `profile.user_agent` | `:1581`（按模型族分档的取值未取证 → 不分支） |

    有意差异（登记，不静默）：
    ① `X-Domain` 取**实际请求基址**主机名而非 `credential.domain`：资源页允许把基址改指向
       别的环境（如本地假上游），而 `X-Domain` 必须与请求 baseURL 一致（`credits.ts:222-228`）；
    ② **不发** `X-User-Id` / `X-Enterprise-Id` / `X-Tenant-Id`：DSH 里这组头属计费面
       （`credits.ts:238-244`），推理面 `send()` 不发（`:1564-1581`）—— 混面正是 F3 的形态；
    ③ `Accept: application/json`：本适配器的 `chat_nonstream` / `chat_stream` 共用同一份头，
       非流式请求不能声明 SSE（DSH 只走 SSE，`:1566` 是 `text/event-stream`）。
    """
    attribution, client_version = _attribution_of(profile)
    return {
        "Authorization": f"Bearer {access_token_of(cred)}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        HEADER_DOMAIN: domain or profile.api_domain,
        HEADER_PRODUCT_CODE: profile.product_code,
        HEADER_AGENT_PURPOSE: AGENT_PURPOSE_CONVERSATION,
        HEADER_IDE_NAME: attribution,
        HEADER_IDE_TYPE: attribution,
        HEADER_IDE_VERSION: client_version,
        HEADER_PRODUCT: attribution,
        "User-Agent": profile.user_agent,
    }


def config_headers(profile: ProductProfile, cred: dict) -> dict[str, str]:
    """`/v3/config` 头（`buddy-oauth.ts:355-364`）。"""
    token = access_token_of(cred)
    return {
        HEADER_DOMAIN: profile.api_domain,
        "User-Agent": profile.user_agent,
        "Authorization": f"Bearer {token}",
        HEADER_PRODUCT: DEPLOYMENT_TYPE,
        HEADER_PRODUCT_CODE: profile.product_code,
    }


def refresh_headers(profile: ProductProfile, cred: dict) -> dict[str, str]:
    """续期头：Bearer + `X-Refresh-Token` + 来源标识（`buddy-oauth.ts:299-308`）。

    `X-Domain` / UA **必须按产品覆盖**，否则 WorkBuddy 会以 CodeBuddy 的身份标识请求
    （`buddy-oauth.ts:301-304` 的实测复盘）。
    """
    return {
        HEADER_DOMAIN: profile.api_domain,
        "User-Agent": profile.user_agent,
        "Authorization": f"Bearer {access_token_of(cred)}",
        HEADER_REFRESH_TOKEN: read_str(cred, "refresh_token"),
        HEADER_AUTH_REFRESH_SOURCE: AUTH_REFRESH_SOURCE,
    }


# ── 小工具（纯读，DSH `buddy.ts:250-269` 同口径）────────────────────────

def read_str(source: object, key: str) -> str:
    """取字符串字段（后端把数字型时间戳返回为 number 时也接受，`buddy.ts:250-255`）。

    会**剔除控制字符**：`scope` 字段实测返回多行文本，换行会破坏落盘 JSON
    （`buddy.ts:243-249` 的真实缺陷复盘）。
    """
    if not isinstance(source, dict):
        return ""
    value = source.get(key)
    if isinstance(value, bool):
        return ""
    if isinstance(value, str):
        return strip_control(value)
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def strip_control(value: str) -> str:
    """去掉控制字符（含 CR/LF/Tab）并把连续空白折叠为单空格（`buddy.ts:257-261`）。"""
    return " ".join(str(value).split())


def read_positive_int(source: object, key: str) -> int | None:
    """取**正**整数字段；缺失/非正数 → `None`（不猜默认值，`buddy.ts:899-906`）。"""
    if not isinstance(source, dict):
        return None
    value = source.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    return None


def read_number(source: object, key: str) -> float:
    """取数值（取不到 → 0.0，供累加；`credits.ts:254-258`）。"""
    if not isinstance(source, dict):
        return 0.0
    value = source.get(key)
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def code_of(body: object) -> int:
    """取响应体业务码（非数值 → 0，与 DSH `responseCode` 同口径，`buddy-oauth.ts:79-83`）。"""
    if not isinstance(body, dict):
        return 0
    value = body.get("code")
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def message_of(body: object) -> str:
    """取响应体 `message`（取不到 → 空串，`buddy-oauth.ts:85-90`）。"""
    return read_str(body, "message")


def data_of(body: object) -> object | None:
    """取 `data` 字段（null → None，`buddy-oauth.ts:92-97`）。"""
    if not isinstance(body, dict):
        return None
    return body.get("data")


def access_token_of(cred: object) -> str:
    """凭据的访问令牌（缺失 → 空串；**不猜别名**）。"""
    return read_str(cred, "access_token")


def refresh_token_of(cred: object) -> str:
    """凭据的刷新令牌（缺失 → 空串 = 不可续期，`buddy.ts:216-218`）。"""
    return read_str(cred, "refresh_token")


# ── JWT 纯解析（不验签；只用于展示与续期调度，`buddy.ts:177-190`）──────────

def jwt_claim(token: str, claim: str) -> object | None:
    """读 JWT payload 的某个声明（非 JWT/解析失败 → None，`buddy.ts:180-190`）。"""
    parts = str(token or "").split(".")
    if len(parts) < 2:
        return None
    try:
        padding = "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64_urlsafe_decode(parts[1] + padding))
    except (ValueError, TypeError):
        return None
    return payload.get(claim) if isinstance(payload, dict) else None


def base64_urlsafe_decode(text: str) -> str:
    """base64url 解码为字符串（`buddy.ts:185` 的 Node 等价物）。"""
    return base64.urlsafe_b64decode(text.encode("ascii")).decode("utf-8", "replace")


def jwt_expires_at_ms(token: str) -> int | None:
    """JWT `exp`（秒）→ 毫秒（`buddy.ts:180-190`）。"""
    value = jwt_claim(token, "exp")
    return int(value) * 1000 if isinstance(value, (int, float)) else None

def jwt_issued_at_ms(token: str) -> int | None:
    """JWT `iat`（秒）→ 毫秒（`buddy.ts:302-312`）——相对过期时间的换算基准。"""
    value = jwt_claim(token, "iat")
    return int(value) * 1000 if isinstance(value, (int, float)) else None


def jwt_nickname(token: str) -> str:
    """昵称只在 access_token 的 JWT 里（`login/account` 常为空，`buddy.ts:196-207`）。"""
    for claim in ("nickname", "preferred_username", "name"):
        value = jwt_claim(token, claim)
        if isinstance(value, str) and value.strip():
            return strip_control(value)
    return ""


def jwt_subject(token: str) -> str:
    """JWT `sub`（用户 id 回退，`buddy.ts:380-391`）。"""
    value = jwt_claim(token, "sub")
    return strip_control(value) if isinstance(value, str) else ""


# ── 登录：令牌/账户/凭据（`buddy.ts:314-391`）───────────────────────────

def absolute_expiry_ms(record: dict, absolute_key: str, relative_key: str,
                       access_token: str) -> str:
    """绝对过期时刻（毫秒字符串）；缺绝对字段时用相对秒数换算（`buddy.ts:271-299`）。

    e2e 实证：`/v2/plugin/auth/token` 实际**只返回 `expiresIn` / `refreshExpiresIn`**
    （相对秒数），**没有** `expiresAt`，不换算则有效期永远为空（`buddy.ts:314-321`）。
    换算基准：access_token 的 JWT `iat` 优先，缺失时用当前时刻（`buddy.ts:296-298`）。
    """
    absolute = read_str(record, absolute_key)
    if absolute:
        if absolute.isdigit():
            value = int(absolute)
            return str(value if value > 1_000_000_000_000 else value * 1000)
        try:
            return str(int(datetime.fromisoformat(absolute).timestamp() * 1000))
        except ValueError:
            return absolute
    relative = read_number(record, relative_key)
    if relative <= 0:
        # 两个字段都没有：返回空串，由 `parse_token_data` 用 access_token 的 JWT `exp` 兜底
        # （DSH 在读取侧做同一件事，`buddy.ts:154-161`）
        return ""
    base = jwt_issued_at_ms(access_token) or int(time.time() * 1000)
    return str(base + int(relative * 1000))


def parse_token_data(data: object) -> dict:
    """`auth/token` / `auth/token/refresh` 响应 → 凭据字段（`buddy.ts:322-335`）。"""
    record = data if isinstance(data, dict) else {}
    access = read_str(record, "accessToken")
    token_type = read_str(record, "tokenType")
    expires_at = absolute_expiry_ms(record, "expiresAt", "expiresIn", access)
    if not expires_at:
        # access_token 的 JWT `exp` 是权威过期时刻（`buddy.ts:154-161` 的兜底口径）。
        # 放在**写入侧**做：凭据落盘即自带可用有效期，读取方不必各自重解一遍 JWT。
        exp_ms = jwt_expires_at_ms(access)
        expires_at = str(exp_ms) if exp_ms else ""
    return {
        "access_token": access,
        "refresh_token": read_str(record, "refreshToken"),
        "expires_at": expires_at,
        "refresh_expires_at": absolute_expiry_ms(record, "refreshExpiresAt",
                                                "refreshExpiresIn", access),
        "token_type": token_type or "Bearer",
        "scope": read_str(record, "scope"),
        "domain": read_str(record, "domain"),
    }


def parse_account_data(data: object) -> dict:
    """`login/account` 响应 → 账户字段（`buddy.ts:344-353`）。"""
    record = data if isinstance(data, dict) else {}
    account_type = read_str(record, "type")
    return {
        "uid": read_str(record, "uid"),
        "nickname": read_str(record, "nickname"),
        "enterprise_id": read_str(record, "enterpriseId"),
        "account_type": account_type or "personal",
    }


def build_credential(token: dict, account: dict) -> dict:
    """令牌 + 账户 → 可落盘的凭据本体（`buddy.ts:363-378`）。

    昵称回退链：`account.nickname` → JWT.nickname → JWT.preferred_username
    （`login/account` 的 nickname 常为空，真名只在 JWT，`buddy.ts:355-362`）。
    """
    access = read_str(token, "access_token")
    nickname = read_str(account, "nickname") or jwt_nickname(access)
    return {
        "access_token": access,
        "refresh_token": read_str(token, "refresh_token"),
        "expires_at": read_str(token, "expires_at"),
        "refresh_expires_at": read_str(token, "refresh_expires_at"),
        "token_type": read_str(token, "token_type") or "Bearer",
        "scope": read_str(token, "scope"),
        "domain": read_str(token, "domain"),
        "user_id": read_str(account, "uid") or jwt_subject(access),
        "nickname": nickname,
        "enterprise_id": read_str(account, "enterprise_id"),
        "account_type": read_str(account, "account_type") or "personal",
    }


def decorate_login_url(auth_url: str, profile: ProductProfile) -> str:
    """按产品装饰登录 URL（`buddy-oauth.ts:525-538`）。

    WorkBuddy（`append_session_params=True`）需要 `version` 与 `loginSessionId`
    （后者为客户端生成的 UUID，仅服务端日志追踪用，无校验语义）。
    ⚠️ 只**追加**参数，不重建 URL —— platform/state/路径全部来自服务端下发的 authUrl。
    """
    if not profile.append_session_params:
        return auth_url
    try:
        parts = urlsplit(auth_url)
    except ValueError:
        return auth_url
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if profile.plugin_version:
        query["version"] = profile.plugin_version
    query["loginSessionId"] = str(uuid.uuid4())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


# ── 计费倍率（`buddy.ts:476-698`：credits + modelPromotions 促销表）────────
#
# 🔴 三处形态坑（全部来自 DSH 的真实缺陷复盘，逐条照抄）：
# ① `data.models[].credits` 是**字符串**：`"x0.29"` / `"x0.03 credits"` / `""`（空）；
# ② 促销值 `discountedCredits` 的 `x` 在**后**（`"0.50x"`），与 credits 相反 —— 早期只认
#    前缀写法，促销价被**静默丢弃**（`buddy.ts:491-503`）；
# ③ 促销**必须按 `schedule` 本地推算此刻是否生效**，不能只看 `enabled`；`factor: 0`
#    是「免费」而非「已结束」（无时间窗口的 `0x` 才是占位）—— 不看时段会全天显示
#    夜间折扣价（用户报障「hy4 preview 夜间 0，现在显示 0.29」，`buddy.ts:569-625`）。
# ⚠️ 本族促销**只由 `/v3/config` 下发**，企业模型端点没有（`buddy-oauth.ts:348-408`）；
#    本网关的目录路径恒走 `/v3/config`（`hooks.py::list_models`），故不存在漏促销面。

#: 倍率数字形态（与 `normalizeRate` 的正则同构：`\d+(?:\.\d+)?`；用 `[0-9]` 避免
#: Python 的 `\d` 收 Unicode 数字，JS 的 `\d` 只认 ASCII）
_RATE_NUMBER = r"[0-9]+(?:\.[0-9]+)?"
_RATE_PREFIXED = re.compile(rf"^x({_RATE_NUMBER})\b", re.IGNORECASE)
_RATE_SUFFIXED = re.compile(rf"^({_RATE_NUMBER})x\b", re.IGNORECASE)
_HHMM_RE = re.compile(r"^([0-9]{1,2}):([0-9]{2})$")


def _normalize_rate(value: object) -> str:
    """倍率文本的共用解析（`normalizeRate`，`buddy.ts:511-518`）。

    先试前缀写法（`x0.29`）再试后缀写法（`0.50x`），统一输出 `x<数字>`；去掉可能
    存在的单位后缀（如 `"x0.03 credits"` 取第一个空白段）。解析不出 → 空串
    （**不回退成 `x1`**：编造倍率比不显示更糟）。
    """
    if not isinstance(value, str):
        return ""
    parts = value.strip().split()
    if not parts:
        return ""
    head = parts[0]
    found = _RATE_PREFIXED.match(head) or _RATE_SUFFIXED.match(head)
    return f"x{found.group(1)}" if found is not None else ""


def normalize_credits_rate(value: object) -> str:
    """`data.models[].credits` → 展示用倍率文本（`normalizeCreditsRate`，`buddy.ts:487-489`）。

    真实形态：`"x0.29"` / `"x0.03 credits"` / `""`（空，如 `auto` / `codewise-*`）。
    """
    return _normalize_rate(value)


def normalize_discounted_rate(value: object) -> str:
    """`modelPromotions[].discount.discountedCredits` → 展示用倍率文本。

    （`normalizeDiscountedRate`，`buddy.ts:501-503`。）⚠️ 与 `credits` 形态**相反**：
    实测促销值是 `"0.50x"`（x 在**后**）—— 两套写法都认（对上游变更鲁棒）。
    """
    return _normalize_rate(value)


def combined_billing(credits_rate: str, promo_rate: str) -> tuple[bool | None, str]:
    """合并原价与生效促销 → `(free, rate)`（`formatCreditsRate`，`buddy.ts:692-698`）。

    - 两者皆无 → `(None, "")`（**未取到**；`credits` 为空串即此情形，`21 §5.1-1`）；
    - 只有一方 → 直接用该值（如促销下发的模型的 `credits` 可能缺失）；
    - 都有 → `原价→促销价`（如 `x0.79→x0.50`）。

    `free`：**生效价**为 `x0` 时 `True`（免费促销，如 `hy4-preview` 夜间免费）；
    其余有倍率信息 → `False`（有计费）。
    """
    if not credits_rate and not promo_rate:
        return None, ""
    effective = promo_rate or credits_rate
    rate_text = f"{credits_rate}→{promo_rate}" if credits_rate and promo_rate else effective
    return effective == "x0", rate_text


def _priority_of(item: object) -> float:
    """读促销项 `priority`（缺失/非法按 0 最低，`priorityOf`，`buddy.ts:676-681`）。"""
    if not isinstance(item, dict):
        return 0.0
    priority = item.get("priority")
    if isinstance(priority, bool) or not isinstance(priority, (int, float)):
        return 0.0
    number = float(priority)
    return number if math.isfinite(number) else 0.0


def _moment_of(now: datetime | None) -> datetime:
    """注入时刻归一：缺省 = 当下（`new Date()` 的等价物）；naive 视为本机时区。

    `now` 形参镜像 DSH 的 `parsePromotions(record, now = new Date())` 注入缝
    （`buddy.ts:626-629`），供单测喂固定时刻（活动时段判据必须可复现）。
    """
    if now is None:
        return datetime.now(timezone.utc)
    return now if now.tzinfo is not None else now.astimezone()


def _parse_hhmm(value: object) -> int | None:
    """`HH:MM`（容忍小时不补零）→ 当日分钟数；非法 → `None`（`parseHHMM`，`buddy.ts:532-540`）。"""
    if not isinstance(value, str):
        return None
    found = _HHMM_RE.match(value.strip())
    if found is None:
        return None
    hours, minutes = int(found.group(1)), int(found.group(2))
    return hours * 60 + minutes if hours < 24 and minutes < 60 else None


def _zoned_minutes(now: datetime, zone_name: object) -> int | None:
    """指定时区「当前墙上时间」的当日分钟数（`zonedMinutes`，`buddy.ts:542-561`）。

    用 IANA 时区而非手算 UTC 偏移：活动时区由服务端下发（实测 `Asia/Shanghai`，
    缺省同值），硬编码 +8 在其它时区的活动上会算错。时区非法 → `None`
    （调用方**不误杀**：宁可多显示一次折扣，也不要让活动凭空消失）。
    """
    name = zone_name if isinstance(zone_name, str) and zone_name else "Asia/Shanghai"
    try:
        zone = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    local = now.astimezone(zone)
    return local.hour * 60 + local.minute


def _parse_iso_moment(value: object) -> datetime | None:
    """ISO 串 → 时刻（`Date.parse` 的等价物，`buddy.ts:582-583`）。

    解析不出 → `None`（该条时限**不参与判定**，与 JS 的 `NaN` 分支同义）。
    naive 时间（无偏移）按本机时区解释 —— 与 JS `Date.parse` 的口径一致。
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:  # `Z` 后缀 → `+00:00`（3.11 起原生支持 Z，双保险，同 cline 的 parse_timestamp_ms）
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.astimezone()


def _has_time_window(schedule: dict) -> bool:
    """活动是否带任何时间窗口（`hasTimeWindow`，`buddy.ts:563-567`）。

    ⚠️ 有效期判据照抄 JS 的 `!== undefined`：**键存在即算**（显式 `null` 也算有
       窗口，只有键缺失才不算）—— 用 `in` 而不是 `is not None` 保持同义。
    """
    daily = schedule.get("daily")
    return (isinstance(daily, list) and len(daily) > 0) \
        or "validFrom" in schedule or "validUntil" in schedule


def _promotion_active_now(item: dict, now: datetime) -> bool:
    """活动在 `now` 是否生效（`promotionActiveNow`，`buddy.ts:577-599`）。

    🔴 **必须本地推算，不能只看 `enabled`**：实测 `glm-5.2` 有夜间/白天两条互补活动，
       不看时段会**全天**显示夜间折扣价（用户按折扣价预期、实际被按原价计费）。
    支持跨零点（如 `23:00–7:50`）；带任何时间窗口的活动才判；无 `schedule` → 视为生效。
    """
    raw = item.get("schedule")
    if not isinstance(raw, dict):
        return True
    from_moment = _parse_iso_moment(raw.get("validFrom"))
    until_moment = _parse_iso_moment(raw.get("validUntil"))
    if from_moment is not None and now < from_moment:
        return False
    if until_moment is not None and now >= until_moment:
        return False
    daily = raw.get("daily")
    if not isinstance(daily, list) or not daily:
        return True
    minutes = _zoned_minutes(now, raw.get("timezone"))
    if minutes is None:
        return True   # 时区不可解析时不误杀（宁可多显示一次折扣）
    for slot in daily:
        if not isinstance(slot, dict):
            continue
        start = _parse_hhmm(slot.get("start"))
        end = _parse_hhmm(slot.get("end"))
        if start is None or end is None:
            continue
        in_slot = minutes >= start and minutes < end if start <= end \
            else minutes >= start or minutes < end          # 跨零点
        if in_slot:
            return True
    return False


def parse_promotions(record: object, now: datetime | None = None) -> dict[str, str]:
    """`data.modelPromotions` → 「模型 id → **此刻生效的**促销价」映射。

    （`parsePromotions`，`buddy.ts:626-674`。）真实结构是**数组**（按 `modelIds`
    关联，不是全局），形如::

        [{"kind": "discount", "enabled": true, "priority": 100,
          "discount": {"discountedCredits": "0.50x", "factor": 0.5},
          "badge": {"color": "#1E90FF", "label": "夜间折扣"},
          "schedule": {"daily": [{"start": "23:00", "end": "7:50"}], "timezone": "Asia/Shanghai"},
          "modelIds": ["glm-5.2"]}]

    四个必须处理的退化情形：
    - **时段未到 / 已过**（`schedule`）—— 跳过，见 `_promotion_active_now`；
    - **有效期已过**（`validFrom` / `validUntil`，如 `hy3` 的限时免费）—— 跳过；
    - `enabled: false` —— 已停用，跳过；
    - 同一模型命中多条 —— 取 `priority` 最高者。

    ⚠️ **`factor: 0` 是「免费」而非「活动已结束」**：实测 `hy4-preview` 的夜间活动是
       `{discountedCredits: "0x", factor: 0}` —— 它**真的免费**。作为防御：**无任何时间
       窗口**的 `factor: 0` 仍按「已结束占位」跳过（免费额度必然是限时的）。
    返回值为统一 x 形态：折扣价 `x0.50`；免费促销 `x0`（DSH 同情形展示「免费」，
    本层的结构化表达是 `free=True` + `rate="x0"`）。
    """
    moment = _moment_of(now)
    result: dict[str, str] = {}
    if not isinstance(record, dict):
        return result
    promotions = record.get("modelPromotions")
    if not isinstance(promotions, list):
        return result
    chosen: dict[str, float] = {}
    # 按 priority 升序处理，使高 priority 覆盖低 priority（排序稳定，同 JS）。
    for item in sorted(promotions, key=_priority_of):
        if not isinstance(item, dict):
            continue
        if item.get("enabled") is False:
            continue
        if not _promotion_active_now(item, moment):
            continue
        discount = item.get("discount")
        if not isinstance(discount, dict):
            continue
        factor = discount.get("factor")
        has_zero_factor = isinstance(factor, (int, float)) and not isinstance(factor, bool) \
            and factor == 0
        raw_schedule = item.get("schedule")
        windowed = isinstance(raw_schedule, dict) and _has_time_window(raw_schedule)
        if has_zero_factor:
            if not windowed:
                continue   # 无窗口的 `0x` 视为「已结束」占位
            rate = "x0"
        else:
            rate = normalize_discounted_rate(discount.get("discountedCredits"))
            if rate in ("", "x0"):
                continue   # 归一化后仍是 `x0` = 无 factor 的占位，跳过
        model_ids = item.get("modelIds")
        if not isinstance(model_ids, list):
            continue
        priority = _priority_of(item)
        for model_id in model_ids:
            if not isinstance(model_id, str) or not model_id:
                continue
            previous = chosen.get(model_id)
            if previous is not None and previous > priority:
                continue
            chosen[model_id] = priority
            result[model_id] = rate
    return result


# ── 模型目录（`buddy.ts:700-948`）─────────────────────────────────────

@dataclass(frozen=True)
class RemoteCatalog:
    """`/v3/config` 的解析结果。"""

    #: 远端声明的可选对话模型（顺序 = craft/cli agent 引用在前，其余 `data.models` 在后）
    models: tuple[ModelInfo, ...] = ()
    #: 被任一 agent 引用的 id 集合（= 服务端「对话里可选」信号，`buddy.ts:741-754`）
    agent_referenced: frozenset[str] = field(default_factory=frozenset)


def is_auto_select_alias(model_id: str) -> bool:
    """`auto` / `default` = 服务端自行挑后端的内部别名，**不是真实模型**（`buddy.ts:865-879`）。

    只按这两个字面量过滤，**不做前缀匹配** —— 国际版的 `default-model` 是被 craft 引用的
    官方入口，前缀匹配会误伤（`buddy.ts:871-875`）。
    """
    return model_id in ("auto", "default")


def is_chat_model(model_id: str, meta: object) -> bool:
    """是否「可供用户选择的对话模型」（`buddy.ts:865-888` ③ 类排除）。

    排除：补全/NES 专用（`nes-`/`completion-`/`codewise-` 前缀、`supportsExtra`）、
    输出上限 ≤256 的补全用途、`text-to-image` 标签的生成式模型。
    """
    if model_id.startswith(("nes-", "completion-", "codewise-")):
        return False
    if isinstance(meta, dict):
        if meta.get("supportsExtra") is True:
            return False
        max_output = meta.get("maxOutputTokens")
        if isinstance(max_output, (int, float)) and not isinstance(max_output, bool) \
                and 0 < max_output <= 256:
            return False
        tags = meta.get("tags")
        if isinstance(tags, list) and "text-to-image" in tags:
            return False
    return True


def model_info_from_meta(model_id: str, meta: object, promo_rate: str = "") -> ModelInfo:
    """远端 `data.models[]` 条目 → `ModelInfo`（`buddy.ts:896-922`）。

    - `context_window` ← `maxInputTokens`、`max_output` ← `maxOutputTokens`（**只取正数**，
      缺失即 None，不猜默认值）；
    - `image_input` ← `supportsImages`（只在**显式**下发时保留，缺失 = 未取到）；
    - `effort_levels` ← `reasoning.supportedEfforts`（`defaultEffort` **不搬运**：
      §22.3 的 `ModelInfo` 冻结类型无该字段，登记为字段缺口）；
    - `tool_call` **恒 None**：`/v3/config` 不声明工具能力，取不到不编造（`21 §5.1-1`）；
    - `free` / `rate`（2026-10-01 补）= `data.models[].credits`（字符串形态）与
      `modelPromotions` 促销（`promo_rate` 形参，由 `parse_models_from_config` 按 id 取得）
      的合并，规则见 `combined_billing`（`buddy.ts:692-698` 的 `formatCreditsRate`）。
    """
    record = meta if isinstance(meta, dict) else {}
    reasoning = record.get("reasoning")
    efforts: tuple[str, ...] = ()
    if isinstance(reasoning, dict):
        raw = reasoning.get("supportedEfforts")
        if isinstance(raw, list):
            efforts = tuple(item for item in raw if isinstance(item, str) and item.strip())
    images = record.get("supportsImages")
    free, rate = combined_billing(normalize_credits_rate(record.get("credits")), promo_rate)
    return ModelInfo(
        id=model_id,
        name=read_str(record, "name"),
        context_window=read_positive_int(record, "maxInputTokens"),
        max_output=read_positive_int(record, "maxOutputTokens"),
        tool_call=None,
        image_input=images if isinstance(images, bool) else None,
        reasoning=True if efforts else None,
        effort_levels=efforts,
        free=free,
        rate=rate,
    )


def parse_models_from_config(body: object, now: datetime | None = None) -> RemoteCatalog:
    """`GET /v3/config` 响应 → 可选对话模型（`buddy.ts:700-825`）。

    解析策略（顺序即优先级，`buddy.ts:707-718`）：
    1. 主对话 agent（`cli` → `craft`，`buddy.ts:828-833`）引用的模型排最前；
    2. `data.models` 里其余可对话模型；
    3. 试用横幅（`productFeaturesConfig.ModelTrialBanner[].targetModelId`，`buddy.ts:836-850`）
       —— 它既不在 agent 列表也不在 `data.models`，但实测可调用。

    `now`：促销时段判定的注入时刻（缺省 = 当下，`parsePromotions(record, now)` 的同一注入缝，
    `buddy.ts:626-629`）—— 单独提出来是为了让「此刻是否打折」在单测里可复现。
    """
    data = data_of(body)
    if not isinstance(data, dict):
        return RemoteCatalog()
    meta_by_id: dict[str, dict] = {}
    for entry in data.get("models") or []:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            meta_by_id[entry["id"]] = entry

    # 促销折扣是**独立于 data.models 的全局活动表**（`buddy.ts:737-739`），先解析成
    # id → 促销价映射，再在构造时按 id 关联。
    promotions = parse_promotions(data, now)

    agent_referenced: set[str] = set()
    agents = data.get("agents")
    if isinstance(agents, list):
        for agent in agents:
            if not isinstance(agent, dict):
                continue
            models = agent.get("models")
            if isinstance(models, list):
                agent_referenced.update(m for m in models if isinstance(m, str))

    order: list[str] = []
    seen: set[str] = set()

    def push(model_id: str) -> None:
        if is_auto_select_alias(model_id) or model_id in seen \
                or not is_chat_model(model_id, meta_by_id.get(model_id)):
            return
        seen.add(model_id)
        order.append(model_id)

    if isinstance(agents, list):
        for agent_name in PREFERRED_AGENT_NAMES:
            hit = next((a for a in agents if isinstance(a, dict) and a.get("name") == agent_name),
                       None)
            if hit is not None:
                for model_id in hit.get("models") or []:
                    if isinstance(model_id, str):
                        push(model_id)
                break
    for model_id in meta_by_id:
        push(model_id)
    # 试用横幅（第三步）：**不过滤对话能力**（照抄 `buddy.ts:807-822`——这类模型既不在
    # agent 列表也不在 `data.models`，唯一信号就是「服务端推荐可用」）；同时标记为
    # `agent_referenced`（`buddy.ts:819-821`：「试用横幅本身就是服务端推荐可用的信号，
    # 与 agent 引用同义」）——否则白名单式合并会把不在兜底表的试用模型丢掉。
    for model_id in trial_model_ids(data):
        if is_auto_select_alias(model_id) or model_id in seen:
            continue
        seen.add(model_id)
        order.append(model_id)
        agent_referenced.add(model_id)

    return RemoteCatalog(
        models=tuple(model_info_from_meta(mid, meta_by_id.get(mid), promotions.get(mid, ""))
                     for mid in order),
        agent_referenced=frozenset(agent_referenced),
    )


def trial_model_ids(data: dict) -> list[str]:
    """`productFeaturesConfig.ModelTrialBanner` 下发的试用模型 id（`buddy.ts:835-850`）。"""
    features = data.get("productFeaturesConfig")
    banner = features.get("ModelTrialBanner") if isinstance(features, dict) else None
    banners = banner.get("banners") if isinstance(banner, dict) else None
    if not isinstance(banners, list):
        return []
    return [strip_control(item["targetModelId"]) for item in banners
            if isinstance(item, dict) and isinstance(item.get("targetModelId"), str)
            and item["targetModelId"]]


def merge_models(remote: RemoteCatalog, fallback: tuple[ModelInfo, ...]) -> list[ModelInfo]:
    """兜底表（主集）+ 远端（逐字段优先）→ 可用目录（`buddy-adapter.ts:901-948`）。

    DSH 的 `reconcileWithFallback` 是**白名单式重建**：以产品兜底表定集合与顺序，
    远端只做字段级覆盖（远端缺失的字段由兜底表补位）。两条例外/纪律照抄：
    - 被 agent 引用但不在兜底表的模型**追加在末尾**（真实缺陷：`hy4-preview-f` 只在
      `/v3/config` 且被 craft 引用，白名单重建会把它丢掉，`buddy-adapter.ts:890-899,937-946`）；
    - 兜底表为空时（本产品不可能）退化为远端原样。
    """
    remote_by_id = {m.id: m for m in remote.models}
    out: list[ModelInfo] = []
    for entry in fallback:
        hit = remote_by_id.get(entry.id)
        efforts = hit.effort_levels if (hit and hit.effort_levels) else entry.effort_levels
        out.append(ModelInfo(
            id=entry.id,
            # 远端 name 优先（静态表对老模型的叫法可能已过时），再兜底表，最后退 id
            name=(hit.name if hit and hit.name else "") or entry.name or entry.id,
            # 生产厂家未在 /v3/config 声明 → 留空（不编造，§22.3）
            vendor="",
            context_window=hit.context_window if (hit and hit.context_window is not None)
            else entry.context_window,
            max_output=hit.max_output if (hit and hit.max_output is not None) else entry.max_output,
            tool_call=None,
            image_input=hit.image_input if (hit and hit.image_input is not None) else entry.image_input,
            reasoning=True if efforts else None,
            effort_levels=efforts,
            # 计费：远端声明优先；兜底表（`product.ts` 的 BuddyFallbackModel）**不含**
            # credits 字段 → 远端缺失时保持兜底值（None / ""，**未取到不编造**）
            free=hit.free if (hit is not None and hit.free is not None) else entry.free,
            rate=(hit.rate if (hit is not None and hit.rate) else "") or entry.rate,
        ))
    known = {m.id for m in out}
    for hit in remote.models:
        if hit.id in remote.agent_referenced and hit.id not in known:
            known.add(hit.id)
            out.append(hit if hit.name else ModelInfo(
                id=hit.id, name=hit.id, context_window=hit.context_window,
                max_output=hit.max_output, tool_call=None, image_input=hit.image_input,
                reasoning=hit.reasoning, effort_levels=hit.effort_levels,
                free=hit.free, rate=hit.rate))
    return out


# ── 额度/签到（`credits.ts`）───────────────────────────────────────────

@dataclass(frozen=True)
class BalanceSummary:
    """`get-user-resource` 的汇总（口径照抄 `credits.ts:494-531`）。"""

    #: 各**有效**包的本周期剩余之和（IDE 顶部 "Credits Balance" 的同款口径）
    total: float = 0.0
    #: 已失效包里的剩余合计（**不并进 total**，`credits.ts:511-520` 的真实缺陷复盘）
    expired_total: float = 0.0
    active_count: int = 0
    expired_count: int = 0
    #: 额度单位（`CapacityUnit`，取首个非空值；取不到 → 空）
    unit: str = ""


def round_credits(value: float) -> float:
    """额度规整到两位小数（`credits.ts:533-545`：浮点尾数噪声只到分）。"""
    return round(float(value) * 100) / 100


def _read_precise_number(source: dict, base_key: str) -> float:
    """优先读 `<key>Precise` 精确值（字符串两位小数），否则读整数版（`credits.ts:426-434`）。"""
    precise = source.get(f"{base_key}Precise")
    if isinstance(precise, str):
        try:
            return float(precise)
        except ValueError:
            pass
    if isinstance(precise, (int, float)) and not isinstance(precise, bool):
        return float(precise)
    return read_number(source, base_key)


def parse_package(entry: dict) -> dict:
    """`Accounts[]` 的一个资源包（`credits.ts:455-482`）。

    失效判据三条（任一命中即失效）：`Status == 3`、`ExpiredTime` 已过、`DeductionEndTime` 已过。
    ⚠️ `DeductionEndTime` 才是「这批积分何时作废」的字段（`CycleEndTime` 会把每月刷新的
    套餐误判成快作废，`credits.ts:176-193`）。
    余额取 **`CycleCapacityRemain`（本周期口径）** 而非 `CapacityRemain`（终身口径）。
    """
    name = (read_str(entry, "PackageName") or read_str(entry, "SubProductName")
            or read_str(entry, "PackageCode"))
    status = entry.get("Status")
    expired_time = read_str(entry, "ExpiredTime")
    expired_at: float | None = None
    if expired_time:
        try:
            expired_at = datetime.fromisoformat(expired_time.replace(" ", "T")).timestamp()
        except ValueError:
            expired_at = None
    deduction_end = read_number(entry, "DeductionEndTime")     # 毫秒
    now = time.time()
    active = status != PACKAGE_STATUS_EXPIRED \
        and not (expired_at is not None and now >= expired_at) \
        and not (deduction_end > 0 and now >= deduction_end / 1000)
    return {
        "name": name,
        "unit": read_str(entry, "CapacityUnit") or read_str(entry, "OriginUnit"),
        "remaining": _read_precise_number(entry, "CycleCapacityRemain"),
        "active": active,
    }


def summarize_balance(body: object) -> BalanceSummary | None:
    """`get-user-resource` 响应 → 余额汇总（`credits.ts:494-531`）。

    🔴 `data` 是**两层嵌套**：`data.Response.Data.Accounts[]`（本接口最易解析错的地方，
    `credits.ts:490-492`）。任一层缺失 → `None`（= **未知**，绝不当 0，`23 B2`）。
    """
    if code_of(body) != CODE_OK:
        return None
    outer = data_of(body)
    response = outer.get("Response") if isinstance(outer, dict) else None
    inner = response.get("Data") if isinstance(response, dict) else None
    accounts = inner.get("Accounts") if isinstance(inner, dict) else None
    if not isinstance(accounts, list):
        return None
    total = expired_total = 0.0
    active_count = expired_count = 0
    unit = ""
    for item in accounts:
        if not isinstance(item, dict):
            continue
        package = parse_package(item)
        unit = unit or package["unit"]
        if package["active"]:
            total += package["remaining"]
            active_count += 1
        else:
            expired_total += package["remaining"]
            expired_count += 1
    return BalanceSummary(total=round_credits(total), expired_total=round_credits(expired_total),
                          active_count=active_count, expired_count=expired_count, unit=unit)


@dataclass(frozen=True)
class CheckinStatus:
    """签到活动状态（权威源 = `checkin-activity-status`，`credits.ts:11-13,348-373`）。"""

    active: bool = False
    today_checked_in: bool = False
    streak_days: int = 0
    daily_credit: float = 0.0


def parse_checkin_status(body: object) -> CheckinStatus | None:
    """`checkin-activity-status` 响应 → 状态（业务码非 0 / 结构缺失 → None）。"""
    if code_of(body) != CODE_OK:
        return None
    data = data_of(body)
    if not isinstance(data, dict):
        return None
    return CheckinStatus(
        active=data.get("active") is True,
        today_checked_in=data.get("today_checked_in") is True,
        streak_days=int(read_number(data, "streak_days")),
        daily_credit=read_number(data, "daily_credit"),
    )


def claim_category(code: int) -> str | None:
    """业务码 → 非致命类别（None = 交给调用方按成功/失败继续判定，`credits.ts:382-403`）。

    - `10001` / `1001` → `already_done`（**正常业务状态，不是失败**）；
    - `1002` / `1003` → `inactive`。
    """
    if code in (CODE_ALREADY_CLAIMED, CODE_ALREADY_CLAIMED_ALT):
        return "already_done"
    if code in (CODE_NO_QUALIFICATION, CODE_ACTIVITY_ENDED):
        return "inactive"
    return None


def parse_claim_success(body: object) -> str:
    """领取成功（code 0）的 detail 文案；结构不合规 → 返回空串（调用方判 failed）。

    `data` 必须存在（`credits.ts:404-407`：缺少 `data` 视为失败，不谎报成功）。
    """
    data = data_of(body)
    if not isinstance(data, dict):
        return ""
    credit = read_number(data, "credit")
    streak = int(read_number(data, "streak_days"))
    unit = "积分"
    text = f"已领取 {credit:g} {unit}"
    if streak > 0:
        text += f"（连续 {streak} 天）"
    delayed = read_str(data, "message")
    return f"{text} · {delayed}" if delayed else text
