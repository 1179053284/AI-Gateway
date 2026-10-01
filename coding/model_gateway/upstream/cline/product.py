"""Cline 产品钩子（tech-design v2.0 §22.3 冻结签名；**M6-2 实现**）。

本产品证据面（§22.4 行 + `20 §1.2/§2.7/§3.1`；`21 §1.1`）：

- 登录：**WorkOS 设备码轮询**（`20 §1.2` 的 `jet-hub-rpc.ts:1022-1057` 分支）
- 设备：**无设备标识**（`20 §2.7`；`registry.DeviceSpec(fields=())`）
- 额度 ✓（`GET /api/v1/users/{id}/balance`）；签到 ✗ —— 对整个 sidecar 二进制做字符串扫描
  无任何签到端点（`20 §3.1`、`credits-capabilities.js:94-99`）→ **不渲染**签到按钮
- 模型：远端**两端点合并**（`/api/v1/models` 460 条 id + `/api/v1/ai/cline/recommended-models`
  的免费集合为唯一权威，`21 §1.1`）
- 协议：**标准 OpenAI**（`cline-product.ts:13` 的表：唯一一家推理体无自有塑形）→ M6-5 出站适配

🔴 **两个必须写死的判据（都是真实缺陷级的坑）**：

1. **`authorization_pending` ≠ 错误，判据是响应体的 `error` 字段，不是 HTTP 状态码**
   （`cline-oauth.ts:40-44`、`jet-hub-rpc.ts:1022-1026`）：Qoder 用「404 = 尚未授权」，
   Cline/WorkOS 用响应体 `error:authorization_pending` 且**状态码可能非 2xx**。
   若按状态码判失败，会把「用户还没点授权」误报成登录失败。
2. **`Authorization` 必须保留 `workos:` 前缀**（`cline-product.ts:96-115`）：剥掉即 401，
   而报错文案是 "make sure you're using the latest version of Cline"，与真实原因毫不相干。
   适用范围与例外见 `protocol.bearer_value` 的 docstring（token 交换类调用不构造该头）。

🔴 `build_out` **自 M6-5b 起已接线**（`upstream/cline/out.py::ClineOut`：标准 OpenAI 体、
`workos:` 前缀鉴权头，取证与错误语义见该文件模块头）。
🔴 `claim` **本产品无此能力**（能力位 `checkin=False`）→ 显式 `NotImplementedError`，
   入口层按 `Capabilities` 不渲染（§22.6「能力矩阵是判据不是标签」）。
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import quote

import httpx

from model_gateway.accounts.net import make_client
from model_gateway.accounts.registry import get as registry_get
from model_gateway.accounts.types import (
    Challenge,
    ClaimOutcome,
    LoginOutcome,
    ModelInfo,
    NotRefreshable,
    ProbeResult,
    ProductMeta,
    QuotaSnapshot,
)
from model_gateway.upstream.cline import constants as C
from model_gateway.upstream.cline import protocol

logger = logging.getLogger("model_gateway.upstream.cline")

#: 本产品标识（§22.4；与 `accounts/registry.py` 的键、账号目录名一致）
PRODUCT = "cline"

#: **已接线**钩子名（M6-2；`build_out` 自 M6-5b 起进表）。⚠️ 私有约定，只为
#: `tests/accounts/test_registry.py` 的「M6-1 骨架纪律」护栏**收窄作用面**（未列出的钩子
#: 仍必须显式 `NotImplementedError`：`login_callback` 本产品非 local_callback 型、
#: `claim` 无此能力），**不是** §22.3 冻结契约的一部分、也**不被入口层读取**（入口层只认 `_HOOKS` 表）。
_IMPLEMENTED = frozenset({"login_start", "login_poll", "refresh", "probe", "quota",
                          "list_models", "build_out"})

#: 终态错误码（WorkOS `error` 字段；`cline-oauth.ts:267-291`）。`expired_token` 单列 —— 它是
#: 「设备码过期」这一**语义精确**的状态，映射到 §22.3 的 `expired` 而不是泛化的 `failed`。
_TERMINAL_ERRORS = frozenset({"access_denied", "invalid_grant"})


def meta() -> ProductMeta:
    """产品注册信息（唯一事实源 = `accounts/registry.py`，此处不重复填字段）。"""
    return registry_get(PRODUCT)


# ==================== 登录（两步式：start → poll）====================


async def login_start(session) -> Challenge:
    """启动登录：申请 WorkOS 设备码（`cline-oauth.ts:178-212`）。

    ```
    POST {workOsBase}/user_management/authorize/device      # x-www-form-urlencoded
    body: client_id=<workOsClientId>
    → { device_code, user_code, verification_uri, verification_uri_complete, expires_in, interval }
    ```

    🔴 两类码分工（§22.3 / `accounts/types.py:87-103`）：
       · `user_code`（给用户看的码）→ `Challenge.device_code`（展示 + 复制）；
       · `device_code`（**轮询私钥**）→ `session.state`，**绝不进 Challenge**。

    私态落 `session.state`：`device_code` / `interval_ms` / `expires_at`（单调钟截止点）。
    上游失败 → 抛异常（引擎不吞异常，由入口层记日志/返回错误；§22.8-5 fail closed）。
    """
    async with make_client(base_url=C.WORKOS_BASE, timeout=C.HTTP_TIMEOUT_S) as client:
        resp = await client.post(C.DEVICE_AUTHORIZATION_PATH,
                                 data={"client_id": C.WORKOS_CLIENT_ID})
        body = _json_or_empty(resp)
    if not resp.is_success:
        raise RuntimeError(
            f"Cline 设备码授权失败（HTTP {resp.status_code}）{_error_detail(body)}")

    auth = protocol.parse_device_authorization(body)      # 字段不齐 → ValueError（不猜）
    session.state["device_code"] = auth["device_code"]
    session.state["interval_ms"] = auth["interval_ms"]
    session.state["expires_at"] = time.monotonic() + auth["expires_in_s"]
    return Challenge(url=auth["login_url"], device_code=auth["user_code"])


async def login_poll(session) -> LoginOutcome:
    """轮询设备码授权结果；**一次 poll = 一次上游请求**（`cline-oauth.ts:214-307` 的单步）。

    状态机（**判据 = 响应体 `error` 字段**，`cline-oauth.ts:266-291`）：

    | 上游 `error` | 本项目状态 | 说明 |
    |---|---|---|
    | `authorization_pending` | `pending` | **不是错误**：用户还没在浏览器点授权 |
    | `slow_down` | `pending` | 服务端要求降速：间隔**累积** +1s（`intervalSeconds += 1`） |
    | `expired_token` | `expired` | 设备码过期（语义精确，不泛化成 failed） |
    | `access_denied` / `invalid_grant` | `failed` | 终态：用户拒绝 / 授权码无效 |
    | 其它 / 无 `error` 字段 | `failed` | 带 HTTP 状态码与 `error_description` |

    ⚠️ **不得按 HTTP 状态码判 pending**：WorkOS 的非 2xx（400/404…）都可能承载
    `authorization_pending`（`cline-oauth.ts:40-44` 明确「状态码可能非 2xx」）。

    拿 WorkOS token 后还要**再换一次** Cline 自己的 token（`/api/v1/auth/register`，
    `cline-oauth.ts:309-338`），成功才返回凭据 —— 只拿到 WorkOS token 不等于登录完成。
    本钩子**不落盘**：`pending` 直接返回；`success` 的凭据由会话引擎经 `store.commit_login`
    落盘（写回自检 + 失败回滚，§22.3）。
    """
    device_code = str(session.state.get("device_code") or "")
    if not device_code:
        return LoginOutcome(state="failed", detail="会话缺少设备码（login_start 未成功）")
    deadline = float(session.state.get("expires_at") or 0.0)
    if deadline and time.monotonic() >= deadline:
        return LoginOutcome(state="expired", detail="设备码已过期，请重新发起登录")

    async with make_client(base_url=C.WORKOS_BASE, timeout=C.HTTP_TIMEOUT_S) as client:
        resp = await client.post(C.DEVICE_AUTHENTICATE_PATH, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": device_code,
            "client_id": C.WORKOS_CLIENT_ID,
        })
        body = _json_or_empty(resp)

    access_token = str(body.get("access_token") or "")
    refresh_token = str(body.get("refresh_token") or "")
    if resp.is_success and access_token and refresh_token:
        return await _register_tokens(access_token, refresh_token)

    error_code = str(body.get("error") or "")
    if error_code == "authorization_pending":
        return LoginOutcome(state="pending", detail="等待用户在浏览器完成授权")
    if error_code == "slow_down":
        # ⚠️ 退避**必须累积**（源码 `intervalSeconds += 1`），固定间隔会在降速后持续被限流
        interval = int(session.state.get("interval_ms") or C.DEVICE_AUTH_MIN_INTERVAL_MS)
        session.state["interval_ms"] = interval + C.SLOW_DOWN_STEP_MS
        return LoginOutcome(state="pending",
                            detail=f"服务端要求降速，轮询间隔调整为 {session.state['interval_ms']}ms")
    if error_code == "expired_token":
        return LoginOutcome(state="expired",
                            detail=f"设备码已过期：{error_code}{_error_detail(body)}")
    if error_code in _TERMINAL_ERRORS:
        return LoginOutcome(state="failed", detail=f"授权失败：{error_code}{_error_detail(body)}")
    if resp.is_success:
        # 2xx 却缺 token：服务端异常（不是「等用户」），不得当 pending 死循环（`cline-oauth.ts:259-262`）
        return LoginOutcome(state="failed", detail="WorkOS token 响应缺少必要字段（access_token/refresh_token）")
    return LoginOutcome(state="failed",
                        detail=f"WorkOS token 轮询失败（HTTP {resp.status_code}）{_error_detail(body)}")


async def _register_tokens(access_token: str, refresh_token: str) -> LoginOutcome:
    """用 WorkOS token 换 Cline 自己的 token（`cline-oauth.ts:309-338`）。

    ```
    POST {apiBase}/api/v1/auth/register   # ⚠️ 请求体字段是**驼峰** accessToken / refreshToken
    → { success: true, data: { accessToken, refreshToken, expiresAt, tokenType, userInfo } }
    ```

    ⚠️ 注册响应里的 `accessToken` **自带 `workos:` 前缀**（`cline-oauth.ts:408-412`）；
    本函数统一经 `protocol.build_credentials` 幂等补齐，无论服务端带不带前缀都是正确形态。
    """
    async with make_client(base_url=C.API_BASE, headers=C.CLIENT_HEADERS,
                           timeout=C.HTTP_TIMEOUT_S) as client:
        resp = await client.post(C.REGISTER_PATH,
                                 json={"accessToken": access_token, "refreshToken": refresh_token})
        body = _json_or_empty(resp)
    if not resp.is_success:
        return LoginOutcome(state="failed",
                            detail=f"token 注册失败（HTTP {resp.status_code}）{_error_detail(body)}")
    payload = protocol.parse_token_payload(body)
    if not payload.get("access_token"):
        return LoginOutcome(state="failed", detail="登录响应缺少访问令牌")
    credentials = protocol.build_credentials(payload)
    meta_out = {key: payload[key] for key in ("account_id", "email", "display_name")
                if payload.get(key)}
    return LoginOutcome(state="success", credentials=credentials, meta=meta_out, detail="登录成功")


async def login_callback(session, params) -> LoginOutcome:
    """回跳粘贴（仅 local_callback 型产品，§22.3）。

    🔴 本产品是 **device_code 型**（WorkOS 设备码，`20 §1.2`）→ 入口层按
    `ProductMeta.login` 只渲染设备码向导，本钩子**预期永不被调用**；保持显式失败
    （不写一个「看起来能用」的假实现）。
    """
    raise NotImplementedError(
        "cline.login_callback：本产品非 local_callback 型（WorkOS 设备码，20 §1.2）")


# ==================== 续期 ====================


async def refresh(cred, meta) -> dict:
    """凭据续期：`refresh_token` 换新令牌（`cline-auth.ts:307-436`）。

    ```
    POST {apiBase}/api/v1/auth/refresh
    body: {"refreshToken": <refresh_token>, "grantType": "refresh_token"}   # ⚠️ 驼峰，非 OAuth 标准名
    → { success: true, data: { accessToken, refreshToken, expiresAt, tokenType, userInfo } }
    ```

    终态判定（`cline-auth.ts:412-434`）：

    - HTTP **401/403**、或 200 却缺访问令牌 → `NotRefreshable`（**不可续期，用户需重新登录**，
      §22.3：不是故障、不触发冷却、入口层据此置灰/跳过）；
    - 其余非 2xx（5xx / 429）→ `RuntimeError`（**可重试**，交给调用方按退避策略重试）；
    - 传输层失败（网络抖动）→ httpx 异常原样冒泡（同样可重试，**不判终态**，
      `cline-auth.ts:406-410`：网络抖动不该让用户重新登录）。

    返回值 = **新的凭据本体**（合并保留 `account_id`/`email`/`nickname`，见 `protocol.apply_refresh`）。
    """
    credential = dict(cred or {})
    if not str(credential.get("refresh_token") or ""):
        raise NotRefreshable("凭据无 refresh_token（Cline 续期必需），请重新登录")

    async with make_client(base_url=C.API_BASE, headers=C.CLIENT_HEADERS,
                           timeout=C.HTTP_TIMEOUT_S) as client:
        resp = await client.post(C.REFRESH_PATH, json=protocol.refresh_body(credential))
        body = _json_or_empty(resp)

    if resp.status_code in (401, 403):
        raise NotRefreshable(
            f"Cline 续期被拒绝（HTTP {resp.status_code}），refresh_token 已失效，请重新登录")
    if not resp.is_success:
        raise RuntimeError(f"Cline 续期失败（HTTP {resp.status_code}）{_error_detail(body)}")
    payload = protocol.parse_token_payload(body)
    if not payload.get("access_token"):
        # 拿到 200 却没有 token：视为**无法续期**（需重新登录），而不是可重试的瞬时故障
        raise NotRefreshable("续期响应缺少访问令牌（HTTP 200），请重新登录")
    return protocol.apply_refresh(credential, payload)


# ==================== 探活 / 额度 ====================


async def probe(cred, meta) -> ProbeResult:
    """探活：连通 / 凭据有效**两个维度分开**（§22.3）。

    端点 = `GET {apiBase}/api/v1/users/me`（`cline-product.ts:307` 的 `CLINE_ME_PATH`；
    实测 `Bearer workos:eyJ…` → 200，`cline-product.ts:107`）。

    - `valid` **只在 2xx 时为 True**（上游接受该凭据）；401/403 = 明确拒绝；
      其余状态码 = **未确认**（不算通过 —— §22.8-5「未知一律 fail closed」）；
    - 网络失败 → `reachable=False`（探活是结果型钩子，**不抛异常**）。
    """
    token = str((cred or {}).get("access_token") or "")
    if not token:
        return ProbeResult(reachable=False, valid=False, detail="凭据缺少 access_token")
    try:
        async with make_client(base_url=C.API_BASE, timeout=C.HTTP_TIMEOUT_S) as client:
            resp = await client.get(C.ME_PATH, headers=protocol.auth_headers(token))
    except httpx.HTTPError as e:
        return ProbeResult(reachable=False, valid=False,
                           detail=f"网络不可达：{type(e).__name__}: {e}")
    if resp.status_code in (401, 403):
        return ProbeResult(reachable=True, valid=False,
                           detail=f"凭据被上游拒绝（HTTP {resp.status_code}）")
    if not resp.is_success:
        return ProbeResult(reachable=True, valid=False,
                           detail=f"凭据有效性未确认（HTTP {resp.status_code}）")
    return ProbeResult(reachable=True, valid=True, detail="OK")


async def quota(cred, meta) -> QuotaSnapshot:
    """额度快照：`GET {apiBase}/api/v1/users/{account_id}/balance`（`cline-credits.ts:5-13,170-218`）。

    ```
    → {"data": {"userId": "usr-01M3BCV4FYCGJKAWD3MJG3DBQM", "balance": 500000}, "success": true}
    ```

    🔴 **`user_id` 用凭据里的 `account_id`（`usr-…`），不是 JWT 的 `sub`（`user_…`）**：
    传 `sub` 实测返回 `400 {"error":"Invalid request format"}`（`cline-credits.ts:15-18`）。

    三态（**未知不当零**，§22.3 / `23 B2`）：查到数值才给 `available`/`exhausted`；
    缺账号 id、网络失败、非 2xx（含 401 的 `{error:…}` 形态）、解析失败 → **一律 `unknown`**
    （附原因），**绝不把「查不到」写成 0**（那是「已用光」的语义，`cline-credits.ts:129-131`）。
    余额查询失败不应让账号卡片整体不可用 → 本钩子不抛异常（`cline-credits.ts:164-169`）。

    ⚠️ 单位**未取证**（`constants.BALANCE_SOURCE_NOTE`）：detail 只报原始值，不做换算。
    """
    credential = dict(cred or {})
    token = str(credential.get("access_token") or "")
    user_id = str(credential.get("account_id") or "").strip()
    if not user_id:
        return QuotaSnapshot(state="unknown", source=C.QUOTA_SOURCE,
                             detail="凭据缺少账号 id（account_id），未查余额")
    if not token:
        return QuotaSnapshot(state="unknown", source=C.QUOTA_SOURCE,
                             detail="凭据缺少 access_token，未查余额")
    # ⚠️ 账号 id 是 `usr-…` 形态（正常无需转义），此处按路径参数转义防御非常规字符
    path = C.BALANCE_PATH_TEMPLATE.format(user_id=quote(user_id, safe=""))
    try:
        async with make_client(base_url=C.API_BASE, timeout=C.HTTP_TIMEOUT_S) as client:
            resp = await client.get(path, headers=protocol.auth_headers(token))
            body = _json_or_empty(resp)
    except httpx.HTTPError as e:
        return QuotaSnapshot(state="unknown", source=C.QUOTA_SOURCE,
                             detail=f"余额查询网络失败：{type(e).__name__}: {e}")

    if not resp.is_success:
        # ⚠️ 401 的响应体**没有** `success` 字段，真原因只在 `error` 里（`cline-credits.ts:133-140`）
        _, reason = protocol.parse_balance(body)
        return QuotaSnapshot(state="unknown", source=C.QUOTA_SOURCE,
                             detail=f"余额查询失败（HTTP {resp.status_code}）：{reason}")
    raw, reason = protocol.parse_balance(body)
    if raw is None:
        return QuotaSnapshot(state="unknown", source=C.QUOTA_SOURCE, detail=reason)
    return QuotaSnapshot(state="available" if raw > 0 else "exhausted", source=C.QUOTA_SOURCE,
                         detail=f"余额 {protocol.num_text(raw)}（{C.BALANCE_SOURCE_NOTE}）")


# ==================== 签到 / 领取（本产品无此能力）====================


async def claim(cred, meta, *, precheck: bool) -> ClaimOutcome:
    """签到/领取 —— **本产品无此能力**（`Capabilities.checkin=False`，`§22.4` 行；`20 §3.1`）。

    🔴 入口层按 `Capabilities` **不渲染**签到按钮（§22.6「能力矩阵是判据不是标签」：
    未登记 = 不支持，避免"点了必然失败"的请求）→ 正常情况下本钩子**永不被调用**。
    若被调用（接线错误 / 手工调用），这里**显式失败**而不是落到泛化的「产品未支持」文案
    —— 后者会让排查者以为是「产品没注册」，而真相是「该产品没有签到端点」
    （照抄 `jet-hub-rpc.ts:1857-1871` 的工程习惯：DSH 对 cline/raccoon/workbuddy 三个
    「没有签到端点」的产品都回可读的业务性错误，而非落到通用 unsupported 分支）。

    依据：对整个 sidecar 二进制做字符串扫描，`checkin` / `check-in` / `daily` / `campaign`
    均无 Cline 业务端点命中（`credits-capabilities.js:94-99`）。
    ⚠️ 该依据强于「某次调用没看到」（字符串扫描），但仍**不等于「永远不存在」** ——
    若上游将来增加签到，需按 Qoder 那次教训重新采集证据后再实现。
    """
    raise NotImplementedError(
        "cline.claim：本产品无签到端点（能力位 checkin=False，20 §3.1）—— "
        "入口层按 Capabilities 不渲染签到按钮")


# ==================== 模型目录（远端两端点合并）====================


async def list_models(cred, meta) -> list[ModelInfo]:
    """产品模型目录 = **远端两端点合并**（`cline-models.ts:1-36,180-235,256-312`）。

    | 端点 | 内容 | 认证 |
    |---|---|---|
    | `GET {apiBase}/api/v1/ai/cline/recommended-models` | `{recommended[], free[], clinePass[]}`，**免费集合唯一权威** | **不需要** |
    | `GET {apiBase}/api/v1/models` | 460 个 `{id, object, created, owned_by}` —— **只有 id** | 需要 |

    ⚠️ 远端 `/models` 的 460 个 id 里**根本没有 `cline-free/*`**（实测零命中）→ 免费模型
    **只**由 `recommended-models` 下发，这正是「只调 `/models` 会看不到任何免费模型」的原因，
    也是必须同时打两个端点的理由（`cline-models.ts:11-14`）。

    合并顺序与元数据优先级见 `protocol.merge_models`（免费集合 → 兜底表 → 推荐/订阅条目 →
    远端大列表；**兜底表排在远端大列表之前**）。

    容错（与 DSH 同语义，`cline-models.ts:237-255`）：**两端点独立**——任一端点失败只丢该来源
    （记 warning 日志），另一端点与兜底表仍可用，避免「目录服务抖动 → 用户模型列表整个消失」。
    ⚠️ 无 `access_token` 时**不发** `/models`（它需认证，匿名调用必然 401，白产生一条 warning）。
    传输层错误不冒泡（目录是建议性数据；M6-5 的 `/v1/models` 能力位另有内置目录兜底）。
    """
    credential = dict(cred or {})
    recommended, entries = await _fetch_recommended()
    remote_ids = await _fetch_remote_model_ids(credential)
    return protocol.merge_models(recommended, entries, remote_ids)


async def _fetch_recommended() -> tuple[list[str], list[dict]]:
    """拉免费/推荐集合（**免认证**；失败 → 空集合 + warning，不抛）。"""
    try:
        async with make_client(base_url=C.API_BASE, headers=C.CLIENT_HEADERS,
                               timeout=C.MODELS_TIMEOUT_S) as client:
            resp = await client.get(C.RECOMMENDED_MODELS_PATH)
            body = _json_or_empty(resp)
    except httpx.HTTPError as e:
        logger.warning("cline 模型目录来源失败：recommended-models %s: %s", type(e).__name__, e)
        return [], []
    if not resp.is_success:
        logger.warning("cline 模型目录来源失败：recommended-models HTTP %s", resp.status_code)
        return [], []
    parsed = protocol.parse_recommended_models(body)
    # `recommended` 与 `clinePass` 都进 entries：前者让推荐模型拿到 name/description，
    # 后者保证订阅制模型也能被发现（它们不是免费，但用户可能已订阅；`cline-models.ts:306-309`）
    return ([str(entry["id"]) for entry in parsed["free"]],
            [*parsed["free"], *parsed["recommended"], *parsed["clinePass"]])


async def _fetch_remote_model_ids(credential: dict) -> list[str]:
    """拉全量 id 列表（**需认证**；无凭据直接跳过，失败 → 空列表 + warning，不抛）。"""
    token = str(credential.get("access_token") or "")
    if not token:
        logger.warning("cline 模型目录来源跳过：/api/v1/models 需认证，凭据无 access_token")
        return []
    try:
        async with make_client(base_url=C.API_BASE, timeout=C.MODELS_TIMEOUT_S) as client:
            resp = await client.get(C.MODELS_PATH, headers=protocol.auth_headers(token))
            body = _json_or_empty(resp)
    except httpx.HTTPError as e:
        logger.warning("cline 模型目录来源失败：models %s: %s", type(e).__name__, e)
        return []
    if not resp.is_success:
        logger.warning("cline 模型目录来源失败：models HTTP %s", resp.status_code)
        return []
    return protocol.parse_remote_model_ids(body)


# ==================== 出站适配（M6-5）====================


def build_out(account) -> OutboundAdapter:
    """构造出站适配器（§22.3「出站适配」；M6-5b 接线）。

    - `account` = `adapters.product_out.ProductAccount`（product / 账号名 / 资源基址）；
    - 返回 `ClineOut`（openai 族基类；端点 = `{base_url}/chat/completions`，
      而 `registry` 的基址已含 `/api/v1`，合起来即 `cline-product.ts:301` 的取证路径）；
    - 出站必须用 `protocol.auth_headers`（保 `workos:` 前缀，`cline.ts:159-182`）；
    - 延迟 import（`out.py` ↔ 本模块不互相在 import 期拉起，见 `product_out.py` 模块头 ⚠️）。
    """
    from model_gateway.upstream.cline.out import ClineOut
    return ClineOut(account)


# ==================== 内部工具 ====================


def _json_or_empty(resp: httpx.Response) -> dict:
    """读 JSON 体；非 JSON / 非对象 → 空 dict（**不因解析失败而丢掉 HTTP 事实**）。"""
    try:
        body: Any = resp.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _error_detail(body: dict) -> str:
    """错误详情（`error_description` / `error` / `message` 三选一，照 DSH 的 detail 口径）。"""
    for key in ("error_description", "error", "message"):
        text = str(body.get(key) or "").strip()
        if text:
            return f"：{text}"
    return ""


#: §22.3 契约表（入口层 `accounts/login.py::_hook` 与 M6-5 按名取用；缺项当场 KeyError）
_HOOKS = {
    "meta": meta,
    "login_start": login_start,
    "login_poll": login_poll,
    "login_callback": login_callback,
    "refresh": refresh,
    "probe": probe,
    "quota": quota,
    "claim": claim,
    "list_models": list_models,
    "build_out": build_out,
}
