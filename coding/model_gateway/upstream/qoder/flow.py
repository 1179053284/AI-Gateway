"""Qoder 同族协议实现（`qoder` / `qodercn` 共用；两个 `product.py` 只是**传区域配置**）。

照抄依据（DSH，只读取证，逐函数标注行号）：
`src/qoder.ts`（协议纯函数）/ `src/qoder-oauth.ts`（设备码登录）/ `src/qoder-auth.ts`（续期）/
`src/qoder-credits.ts`（额度与每日领取）/ `src/qoder-machine.ts`（设备身份头）/
`src/jet-hub-rpc.ts`（入口编排与防串用）。

🔴 **区域参数必须显式**：本文件所有函数第一个形参都是 `product: QoderProduct`（`config.py`），
   不引用任何默认区域 —— 两站 token 不通用（`20 §4.1`，`jet-hub-rpc.ts:1287-1295` 注释）。
🔴 **凭据区域标记**（`config.FAMILY_KEY`）：登录/续期写入本产品 id；此后 refresh/probe/quota/claim
   先校验标记，不一致 → `FamilyMismatchError`（**不打上游**）。DSH 侧靠「按 provider 取实例」
   结构性保证（`jet-hub-rpc.ts:744-757`），本项目用显式标记落地同一约束。
🔴 `build_out` **不在本文件**（M6-5；§22.4 标 custom/信封）。

设备身份（`machine_id`）的两处用途**分开**：
  ① 账号设备字段（§22.2 不变式③）：登录时生成 → `LoginOutcome.meta` → `meta.json`；
  ② DSH 凭据字段 `machine_id`（续期载荷必带，`20 §2.7`）：同一值写进凭据本体（DSH 形状兼容）。
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import secrets
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

import httpx

from model_gateway.accounts import net, store
from model_gateway.accounts.types import (
    Challenge,
    ClaimOutcome,
    LoginOutcome,
    ModelInfo,
    NotRefreshable,
    ProbeResult,
    QuotaSnapshot,
)
from model_gateway.upstream.qoder.config import (
    FAMILY_KEY,
    FamilyMismatchError,
    QoderProduct,
    billing_info,
    efforts_for,
)

# ---------- 端点路径与常量（全部逐条对照 DSH）----------

#: 授权页路径（挂 `auth_base`）—— `qoder.ts:23`
DEVICE_SELECT_PATH = "/device/selectAccounts"
#: 轮询取 token 路径（挂 `open_api_base`）—— `qoder.ts:25`
POLL_PATH = "/api/v1/deviceToken/poll"
#: 续期路径（挂 `open_api_base`）—— `qoder.ts:27`
REFRESH_PATH = "/api/v1/deviceToken/refresh"
#: 用户信息路径（挂 `open_api_base`）—— `qoder.ts:29`
USERINFO_PATH = "/api/v1/userinfo"
#: 用量（余额）路径（挂 `open_api_base`）—— `qoder-credits.ts:76`
USAGE_PATH = "/sash/api/v2/me/usage"
#: 活动列表路径（挂 `open_api_base`）—— `qoder-credits.ts:78`；领取 = 再拼 `/{campaignId}/claim`
CAMPAIGNS_PATH = "/sash/api/v1/me/campaigns"

#: 轮询连续网络失败上限（DSH `QODER_POLL_MAX_FAILURES = 5`，`qoder.ts:20`）
POLL_MAX_FAILURES = 5
#: 额度/活动/领取的单次请求超时（DSH `QODER_CREDITS_TIMEOUT_MS = 15_000`，`qoder-credits.ts:81`）
CREDITS_TIMEOUT = httpx.Timeout(connect=10.0, read=15.0, write=15.0, pool=10.0)

#: PKCE 字符集 = RFC 7636 unreserved 66 字符（DSH `PKCE_ALPHABET`，`qoder.ts:39`）
_PKCE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"

#: 「账号尚未开通每日领取」的可操作提示（照抄 `qoder-credits.ts:103-105` 的语义）。
NOT_ACTIVATED_HINT = (
    "该账号尚未在 Qoder 侧开通每日领取（每日 100 Credits）。"
    "请先用 Qoder 官方客户端登录一次该账号，开通后再回来领取。"
)
#: 读不到本机 machine 身份时的降级说明（服务端可能因此不下发可领活动，`qoder-machine.ts:28-40`）。
_MACHINE_HEADER_NOTE = "（未读到本机 Qoder machine_token，服务端可能未下发可领活动）"

#: 额度快照的 `source` 前缀（最终 = `{product.id}-usage`）—— 数据来自 `/sash/api/v2/me/usage`
QUOTA_SOURCE_SUFFIX = "-usage"


# ---------- 测试接缝（假上游注入）----------

#: `httpx.MockTransport` 注入点；生产恒为 `None`（走 `accounts/net.py::make_client`，
#: 显式超时由公共层统一给出，§22.8-1）。测试用 `monkeypatch.setattr(flow, "_transport", ...)`。
_transport: httpx.AsyncBaseTransport | None = None


def _client(*, base_url: str = "", headers: dict | None = None,
            timeout: httpx.Timeout | None = None) -> httpx.AsyncClient:
    """构造带**显式超时**的客户端（§22.8-1）；测试接缝见 `_transport`。"""
    if _transport is not None:                       # 仅测试路径
        return httpx.AsyncClient(base_url=base_url, headers=headers or {},
                                 transport=_transport, timeout=timeout or net.DEFAULT_TIMEOUT,
                                 follow_redirects=True)
    return net.make_client(base_url=base_url, headers=headers, timeout=timeout)


# ---------- 纯函数：PKCE / URL / 载荷 / 凭据（`qoder.ts` 对应段）----------

def create_pkce() -> tuple[str, str]:
    """生成 PKCE `(verifier, challenge)`（`qoder.ts:56-69`）。

    verifier 长度 43..128（源码 `43 + floor(86*random)`）；challenge =
    `base64url(sha256(verifier))` **去 padding** —— 带 `=` 会让服务端校验失败。
    """
    length = 43 + secrets.randbelow(86)
    verifier = "".join(secrets.choice(_PKCE_ALPHABET) for _ in range(length))
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_auth_url(product: QoderProduct, *, challenge: str, nonce: str, machine_id: str) -> str:
    """设备码授权页 URL（`qoder.ts:109-118`）。

    形态：`{auth_base}/device/selectAccounts?challenge&challenge_method=S256&nonce&machine_id&client_id`
    ⚠️ `client_id` 必须是该产品的 prod id（两站不同；用错 → 授权回调阶段被拒，`qoder.ts:100-107`）。
    """
    query = "&".join((
        f"challenge={_q(challenge)}",
        "challenge_method=S256",
        f"nonce={_q(nonce)}",
        f"machine_id={_q(machine_id)}",
        f"client_id={_q(product.client_id)}",
    ))
    return f"{product.auth_base}{DEVICE_SELECT_PATH}?{query}"


def build_poll_url(product: QoderProduct, *, nonce: str, verifier: str) -> str:
    """轮询 URL（`qoder.ts:127-134`）—— 挂 **`open_api_base`**（不是 `auth_base`）。

    ⚠️ 实测 `qoder.com` 的该路径返回 401，而 `openapi.qoder.sh` 返回 404（= 无待授权会话，
    应继续轮询）；写错 host 会让登录永远失败（`qoder.ts:120-126`）。
    """
    query = "&".join((
        f"nonce={_q(nonce)}",
        f"verifier={_q(verifier)}",
        "challenge_method=S256",
    ))
    return f"{product.open_api_base}{POLL_PATH}?{query}"


def parse_token_payload(value: Any) -> dict:
    """解析 token 响应（登录/续期共用一个解析器，`qoder.ts:211-235`）。

    登录响应用 `token`，续期响应用 `device_token` —— 两者字段名不同故都接受；
    垃圾输入返回**空** `access_token`（不抛错），由调用方判失败。
    时间戳兼容 ISO 串与秒/毫秒数字；**无法解析不填 0**（「没有过期时间」≠「1970 过期」）。
    """
    if not isinstance(value, dict):
        return {"access_token": ""}
    access = _read_string(value, ("token", "device_token", "access_token")) or ""
    out: dict[str, Any] = {"access_token": access}
    refresh = _read_string(value, ("refresh_token", "refreshToken"))
    if refresh is not None:
        out["refresh_token"] = refresh
    expires = _read_timestamp(value.get("expires_at", value.get("expiresAt")))
    if expires is not None:
        out["expire_time"] = expires
    refresh_expires = _read_timestamp(
        value.get("refresh_token_expires_at", value.get("refreshTokenExpiresAt")))
    if refresh_expires is not None:
        out["refresh_token_expire_time"] = refresh_expires
    # ⚠️ 设备码响应带 `user_id` / `user_name`（加密推理需要 uid，`qoder.ts:222-226`）
    uid = _read_string(value, ("user_id", "userId"))
    if uid is not None:
        out["uid"] = uid
    user_name = _read_string(value, ("user_name", "userName"))
    if user_name is not None:
        out["user_name"] = user_name
    return out


def build_credentials(product: QoderProduct, payload: dict, *, machine_id: str,
                      nickname: str = "") -> dict:
    """构造凭据本体（`qoder.ts:238-258` + 本地区域标记）。

    - `security_oauth_token` 与 `access_token` **双写同值**：Qoder 取用顺序是
      `security_oauth_token ?? access_token`（源码 `a6e()`，`qoder.ts:136-143`）；
    - `machine_id` **必须持久化**（续期载荷必带、参与服务端设备绑定，`20 §2.7`）；
    - `family` = 本产品 id（**本地标记**，非上游字段）→ 防两站串用（见模块头）。
    """
    credentials: dict[str, Any] = {
        "security_oauth_token": payload.get("access_token", ""),
        "access_token": payload.get("access_token", ""),
        "machine_id": machine_id,
        FAMILY_KEY: product.id,
    }
    for key in ("refresh_token", "expire_time", "refresh_token_expire_time", "uid"):
        if payload.get(key) is not None:
            credentials[key] = payload[key]
    nickname = nickname or str(payload.get("user_name") or "")
    if nickname:
        credentials["nickname"] = nickname
    return credentials


def apply_refresh(product: QoderProduct, old: dict, payload: dict, *, machine_id: str) -> dict:
    """用续期结果覆盖旧凭据（`qoder.ts:324-341`）—— **保留**不在响应里的关键字段。

    保留 `machine_id` / `uid` / `nickname`（丢失会让下次续期缺设备标识、或让加密推理缺 uid）；
    响应未带新 `refresh_token` 时沿用旧的（避免把可续期凭据变成不可续期）。
    """
    next_creds = build_credentials(product, payload, machine_id=machine_id)
    if "refresh_token" not in next_creds and old.get("refresh_token"):
        next_creds["refresh_token"] = old["refresh_token"]
    if "uid" not in next_creds and old.get("uid"):
        next_creds["uid"] = old["uid"]
    if "nickname" not in next_creds and old.get("nickname"):
        next_creds["nickname"] = old["nickname"]
    return next_creds


def token_of(cred: dict | None) -> str:
    """取 Bearer 令牌（`security_oauth_token` 优先，与源码一致，`qoder.ts:295-299`）。"""
    source = cred if isinstance(cred, dict) else {}
    token = source.get("security_oauth_token")
    if isinstance(token, str) and token:
        return token
    fallback = source.get("access_token")
    return fallback if isinstance(fallback, str) else ""


# ---------- 设备身份头（`Cosy-MachineToken` / `Cosy-MachineType`）----------

def machine_token_paths() -> list[Path]:
    """`machine_token.json` 候选路径（照抄 `qoder-machine.ts:124-141` 的三平台清单）。

    ⚠️ **只实现磁盘缓存这一条路径**（DSH 还有主路径：spawn `runtime-info`）。TODO(M6-3/M6-4)：
    实时生成路径未实现 —— 桌面端 `runtime-info(.exe)`（`.bin/umid-*/` 目录名带哈希，须枚举，
    `qoder-machine.ts:289-309`，参数 `[environment='3', '--account-stdin']`，`:365-378`）；
    缺失的后果是「服务端可能不下发可领活动」（`:28-40` 的消融表），本层以保守降级 + 提示处理。
    """
    override = (os.environ.get("QODER_MACHINE_TOKEN_PATH") or "").strip()
    if override:
        return [Path(override)]
    home = Path.home()
    appdata = (os.environ.get("APPDATA") or "").strip()
    out: list[Path] = []
    for name in ("Qoder", "Qoder CN"):
        if appdata:
            out.append(Path(appdata) / name / "SharedClientCache" / "cache" / "machine_token.json")
        out.append(home / "Library" / "Application Support" / name
                   / "SharedClientCache" / "cache" / "machine_token.json")
        out.append(home / ".config" / name / "SharedClientCache" / "cache" / "machine_token.json")
    return out


def machine_identity() -> tuple[str, str] | None:
    """读本机 Qoder 设备身份 `(token, type)`；拿不到 → `None`（**保守降级**，不带这两个头）。

    `%APPDATA%\\Qoder\\SharedClientCache\\cache\\machine_token.json` 的 `{token,type}`
    （`qoder-machine.ts:45-66`）。**两个值必须成对**：缺任一即视为拿不到 —— 消融实验证实
    单独带任一头均无效（`:28-40`）。文件可能陈旧，但仍比不带强（`:102-122`）。
    """
    for path in machine_token_paths():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        token = data.get("token")
        type_ = data.get("type")
        if isinstance(token, str) and token and isinstance(type_, str) and type_:
            return token, type_
    return None


def sash_headers(product: QoderProduct, token: str, *, machine: tuple[str, str] | None = None,
                 json_body: bool = False) -> dict:
    """`/sash/` 端点（用量、活动）的公共请求头（`qoder-credits.ts:194-205`）。

    ⚠️ **`Cosy-ClientType` 与 machine 头族都是「拿到可领活动」的必要条件**（不是充分条件）：
    只用 `'5'`（CLI 身份）时 `/sash/api/v1/me/campaigns` 恒回 `campaigns:[]`；只用 `'10'`
    时只回一条 `VIEW_DETAILS`；`'10'` + `MachineToken` + `MachineType` 才有
    `CLAIM_BENEFIT/CLAIMABLE`（`:167-192` 的消融表）。
    """
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Cosy-ClientType": product.sash_client_type,
        "User-Agent": "Qoder",
    }
    if machine is not None:
        headers["Cosy-MachineToken"] = machine[0]
        headers["Cosy-MachineType"] = machine[1]
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


# ---------- HTTP 调用（薄封装；错误语义由调用方判定）----------

async def _request(method: str, url: str, *, headers: dict | None = None,
                   json_body: dict | None = None, content: bytes | None = None,
                   timeout: httpx.Timeout | None = None) -> httpx.Response:
    """发一次请求（显式超时；调用方负责生命周期）—— 网络异常原样抛 `httpx.HTTPError`。"""
    client = _client(timeout=timeout)
    try:
        return await client.request(method, url, headers=headers or {},
                                    json=json_body, content=content)
    finally:
        await client.aclose()


def _json_body_of(response: httpx.Response) -> Any:
    """尽力解析响应体 JSON；失败 → `None`（调用方按"拿不到"处理，不当 0/空）。"""
    try:
        return response.json()
    except ValueError:
        return None


# ---------- 登录（`qoder-oauth.ts` 的 start/poll 两段）----------

async def login_start(product: QoderProduct, session) -> Challenge:
    """启动设备码登录（`qoder.ts:89-95` + `qoder-oauth.ts:205-215`）。

    私钥（PKCE verifier）、`nonce`、`machine_id` 一律进 `session.state`（不回显）；
    `Challenge` 只给用户可见的授权 URL（前端开窗/展示二维码）。
    """
    verifier, challenge = create_pkce()
    nonce = str(uuid.uuid4())
    machine_id = _new_machine_id(product)
    session.state["pkce_verifier"] = verifier
    session.state["nonce"] = nonce
    session.state["machine_id"] = machine_id
    session.state["poll_failures"] = 0
    return Challenge(url=build_auth_url(product, challenge=challenge, nonce=nonce,
                                        machine_id=machine_id))


async def login_poll(product: QoderProduct, session) -> LoginOutcome:
    """轮询设备码授权结果（`qoder-oauth.ts:119-164`）。

    - **404 = 用户尚未完成授权 → `pending`**（实测 `openapi.qoder.sh` 该路径回 404
      `{"errorCode":"NotFound"}`，任意不存在路径回 401 → 404 是业务层「会话未就绪」）；
    - 2xx 但尚无 token → 同样继续轮询；
    - 其它非 2xx（5xx…）→ 服务端异常 → `failed`（不伪装成"等用户"）；
    - 网络失败容忍 `POLL_MAX_FAILURES` 次连续失败，超过 → `failed`（`:116-118/149-161`）。
    """
    nonce = str(session.state.get("nonce") or "")
    verifier = str(session.state.get("pkce_verifier") or "")
    machine_id = str(session.state.get("machine_id") or "")
    if not nonce or not verifier or not machine_id:
        return LoginOutcome(state="failed",
                            detail="登录会话缺少 nonce/verifier/machine_id（会话状态丢失），请重新发起登录")
    try:
        response = await _request("GET", build_poll_url(product, nonce=nonce, verifier=verifier),
                                  headers={"Accept": "application/json"})
    except httpx.HTTPError as e:
        return _poll_network_failure(session, e)
    if response.status_code == 404:
        session.state["poll_failures"] = 0
        return LoginOutcome(state="pending", detail="等待用户在浏览器完成授权")
    if not response.is_success:
        return LoginOutcome(state="failed",
                            detail=f"登录服务返回异常（HTTP {response.status_code}）")
    session.state["poll_failures"] = 0
    payload = parse_token_payload(_json_body_of(response))
    if not payload["access_token"]:
        return LoginOutcome(state="pending", detail="授权尚未完成（服务端未返回令牌）")
    # ⚠️ 设备码轮询响应**不带 `user_name`** → 必须补一次 userinfo 才有真实名字
    #（`qoder.ts:343-394`；失败不阻塞登录，昵称只是展示信息）
    nickname = await fetch_user_nickname(product, payload["access_token"])
    credentials = build_credentials(product, payload, machine_id=machine_id, nickname=nickname)
    meta = {"machine_id": machine_id}
    if nickname:
        meta["nickname"] = nickname
    detail = f"登录成功（{product.title}）" + (f"：{nickname}" if nickname else "")
    return LoginOutcome(state="success", credentials=credentials, meta=meta, detail=detail)


async def login_callback(product: QoderProduct, session, params: dict) -> LoginOutcome:
    """回跳粘贴 —— **本族非 local_callback 型**（§22.3：仅 local_callback 型产品实现）。

    照抄 `qoder-oauth.ts:1-20`：redirect_uri 是自定义协议 `qoder-app://`，官方 CLI 亦走
    「打开授权页 → 轮询」，**不起本地监听端口** → 本钩子只回报可预期的失败（不静默、不抛栈）。
    """
    return LoginOutcome(
        state="failed",
        detail=f"{product.id} 走设备码轮询（device_code），不支持回跳粘贴登录")


def _poll_network_failure(session, error: Exception) -> LoginOutcome:
    """轮询网络失败：容忍 `POLL_MAX_FAILURES` 次连续失败（`qoder-oauth.ts:149-161`）。"""
    failures = int(session.state.get("poll_failures") or 0) + 1
    session.state["poll_failures"] = failures
    detail = f"{type(error).__name__}: {error}"
    if failures >= POLL_MAX_FAILURES:
        return LoginOutcome(state="failed",
                            detail=f"无法连接 Qoder 登录服务（连续 {failures} 次失败）：{detail}")
    return LoginOutcome(state="pending",
                        detail=f"登录服务暂时不可达（第 {failures}/{POLL_MAX_FAILURES} 次，继续重试）：{detail}")


async def fetch_user_nickname(product: QoderProduct, token: str) -> str:
    """`GET /api/v1/userinfo` 取真实昵称（`qoder.ts:371-394`）；失败返回空串。

    ⚠️ **失败不抛错**：昵称只是展示信息，拿不到不应让登录整体失败（与 DSH 同原则）。
    """
    if not token:
        return ""
    try:
        response = await _request("GET", f"{product.open_api_base}{USERINFO_PATH}",
                                  headers={"Accept": "application/json",
                                           "Authorization": f"Bearer {token}"})
    except httpx.HTTPError:
        return ""
    if not response.is_success:
        return ""
    body = _json_body_of(response)
    if not isinstance(body, dict):
        return ""
    name = body.get("name")
    return name.strip() if isinstance(name, str) and name.strip() else ""


def _new_machine_id(product: QoderProduct) -> str:
    """为本次登录生成**跨账号唯一**的 `machine_id`（§22.2 不变式③ / §15.1 硬约束 1）。

    DSH 侧是 `randomUUID()`（`qoder.ts:89-95`）；本项目按公共层口径走
    `device.generate_unique`（uuid4 + 与既有账号查重，**有上限不静默降级**）。
    设备字段住 `meta.json`（§22.2），凭据本体里的同名键是 DSH 形状兼容（续期载荷必带）。
    """
    from model_gateway.accounts import device
    from model_gateway.accounts.registry import get as registry_get

    spec = registry_get(product.id).device
    return device.generate_unique(store.product_root(product.id), spec)


# ---------- 续期（`qoder-auth.ts::refreshCredential`）----------

# 🔴 命名纪律：本文件**不得出现「函数定义关键字 + refresh + 左括号」的字面串** ——
# 仓内死代码护栏 `tests/unit/test_v2_cli_zcode.py::test_removed_dead_symbols_stay_removed`
# 对全仓做该字面匹配（只排除 `upstream/*/product.py`），故共享实现里的函数名是
# `refresh_credential`，§22.3 的冻结钩子名 `refresh` 在 `product.py` 用真函数定义
# （同 buddy 系的既定口径）。
async def refresh_credential(product: QoderProduct, cred: dict, meta: dict) -> dict:
    """静默续期：`refresh_token` + `machine_id` 换取新令牌（`qoder-auth.ts:395-438`）。

    终态判定（照抄 DSH）：
    - HTTP 401/403、或 200 但缺 token → `NotRefreshable`（DSH `RefreshTokenExpiredError`；
      我们的冻结语义「不可续期」，入口层不据此冷却）；
    - 网络抖动 / 5xx / 429 → 普通 `RuntimeError`（可重试，**不判终态**，`:408-412`）。
    """
    _guard_family(product, cred)
    refresh_token = str(cred.get("refresh_token") or "")
    if not refresh_token:
        raise NotRefreshable("凭据无 refresh_token，不可续期（qoder.ts:264-272），请重新登录")
    machine_id = _machine_id_of(cred, meta)
    if not machine_id:
        raise NotRefreshable("凭据缺 machine_id（续期载荷必带，20 §2.7），请重新登录")
    body = {"refresh_token": refresh_token, "machine_id": machine_id}
    headers = {"Accept": "application/json", "Content-Type": "application/json",
               "User-Agent": f"{product.user_agent_prefix}/1.0.0"}
    try:
        response = await _request("POST", f"{product.open_api_base}{REFRESH_PATH}",
                                  headers=headers, json_body=body)
    except httpx.HTTPError as e:
        raise RuntimeError(f"{product.id} 续期网络失败：{type(e).__name__}: {e}") from e
    if response.status_code in (401, 403):
        raise NotRefreshable(
            f"{product.id} 续期被拒绝（HTTP {response.status_code}），refresh_token 已失效，请重新登录")
    parsed = _json_body_of(response)
    if parsed is None:
        raise RuntimeError(f"{product.id} 续期响应不是 JSON（HTTP {response.status_code}）")
    if not response.is_success:
        detail = json.dumps(parsed, ensure_ascii=False)[:200]
        raise RuntimeError(f"{product.id} 续期失败（HTTP {response.status_code}）：{detail}")
    payload = parse_token_payload(parsed)
    if not payload["access_token"]:
        raise NotRefreshable("续期响应缺少访问令牌，请重新登录")
    return apply_refresh(product, cred, payload, machine_id=machine_id)


def _machine_id_of(cred: dict, meta: dict) -> str:
    """取续期载荷要用的 `machine_id`：账号元信息（§22.3③ 的 `meta` 通道）优先，凭据兜底。

    两处都可能是 DSH 时代的旧账号（只有凭据里那一份）→ 读侧同时认这两处是对的，
    但**写侧**：登录把同一值同时写进两处（见 `login_poll`），续期只改凭据。
    """
    for source in (meta, cred):
        if isinstance(source, dict):
            value = source.get("machine_id")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _guard_family(product: QoderProduct, cred: dict | None) -> None:
    """串用护栏：凭据带**本地**区域标记且与本产品不符 → 立刻拒绝（**不打上游**）。

    DSH 的结构性等价物 = `requireQoderFamily(entry.provider)` 按 provider 取实例
    （`jet-hub-rpc.ts:1287-1295` 注释：「不要图省事写 `qoder.refreshAccountCredential(...)`」）。
    无标记（如 DSH 侧导入的旧凭据）不拦 —— 保持导入可用性；标记只由本层写入。
    """
    marker = str((cred or {}).get(FAMILY_KEY) or "").strip() if isinstance(cred, dict) else ""
    if marker and marker != product.id:
        raise FamilyMismatchError(
            f"凭据区域标记 {marker!r} 与产品 {product.id!r} 不符："
            f"国际版/中国版两站 token 不通用（20 §4.1），已拒绝（未打上游）")


# ---------- 探活（userinfo 通道）----------

async def probe(product: QoderProduct, cred: dict, meta: dict) -> ProbeResult:
    """探活：连通 / 凭据有效两维分开（§22.3）。

    判据通道 = `GET /api/v1/userinfo`（Bearer；`qoder.ts:29/371-394` 的既有取数路径）：
    - `reachable`：拿到了 HTTP 响应（DNS/连接/HTTP 层成立）；
    - `valid`：`reachable` 且 **未被 401/403 拒绝**（`accounts/types.py::ProbeResult` 的冻结定义）
      —— 5xx 等其它状态**不算凭据失效**（那是上游服务问题；误判会走「401 → disable」路径
      把好账号停用，§22.5-5），故此处保守判「未被拒绝」。
    """
    _guard_family(product, cred)
    token = token_of(cred)
    if not token:
        return ProbeResult(reachable=False, valid=False, detail="凭据缺访问令牌（security_oauth_token/access_token）")
    try:
        response = await _request("GET", f"{product.open_api_base}{USERINFO_PATH}",
                                  headers={"Accept": "application/json",
                                           "Authorization": f"Bearer {token}"})
    except httpx.HTTPError as e:
        return ProbeResult(reachable=False, valid=False,
                           detail=f"网络不可达：{type(e).__name__}: {e}")
    if response.status_code in (401, 403):
        return ProbeResult(reachable=True, valid=False,
                           detail=f"凭据被上游拒绝（HTTP {response.status_code}）")
    if response.is_success:
        return ProbeResult(reachable=True, valid=True, detail="userinfo 返回 200")
    return ProbeResult(reachable=True, valid=True,
                       detail=f"上游返回 HTTP {response.status_code}（非凭据问题；未据此停用账号）")


# ---------- 额度（`qoder-credits.ts::fetchQoderCreditBalance`）----------

async def quota(product: QoderProduct, cred: dict, meta: dict) -> QuotaSnapshot:
    """额度快照（`GET /sash/api/v2/me/usage`，`qoder-credits.ts:278-340`）。

    - **未知不当零**（`23 B2`）：网络失败 / 非 2xx / 形状非法 / 企业版（无额度数字，只给外链）
      → `unknown`；一个包都没解析出来 → `unknown`（`qoder-credits.ts:334-336`）；
    - 余额 = `userQuota` + `addOnQuota` + `dedicatedResourcePackages[]` 的 `remaining` 之和
      （⚠️ 只读 `userQuota` 会漏掉「资源包 100 积分」，`:27-29`）；`remaining` 缺失按
      `max(0, total-used)`，负值 clamp 到 0（`:234-266`）；
    - 合计 > 0 → `available`；= 0 → `exhausted`（确实为 0，选路可跳过）。
    """
    _guard_family(product, cred)
    source = f"{product.id}{QUOTA_SOURCE_SUFFIX}"
    token = token_of(cred)
    if not token:
        return QuotaSnapshot(state="unknown", source=source, detail="凭据缺访问令牌")
    try:
        response = await _request(
            "GET", f"{product.open_api_base}{USAGE_PATH}",
            headers=sash_headers(product, token, machine=machine_identity()),
            timeout=CREDITS_TIMEOUT)
    except httpx.HTTPError as e:
        return QuotaSnapshot(state="unknown", source=source,
                             detail=f"用量查询失败：{type(e).__name__}: {e}")
    if not response.is_success:
        return QuotaSnapshot(state="unknown", source=source,
                             detail=f"用量端点非 2xx（HTTP {response.status_code}）")
    body = _json_body_of(response)
    if not isinstance(body, dict):
        return QuotaSnapshot(state="unknown", source=source, detail="用量响应不是对象")
    if body.get("displayMode") == "enterprise":
        return QuotaSnapshot(state="unknown", source=source,
                             detail="企业版账号不提供额度数字（qoder-credits.ts:309-310）")
    usage = body.get("qoderUsage")
    if not isinstance(usage, dict):
        return QuotaSnapshot(state="unknown", source=source, detail="用量响应缺 qoderUsage")
    packages = _usage_packages(usage)
    if not packages:
        return QuotaSnapshot(state="unknown", source=source,
                             detail="用量响应形状与预期不符（一个额度包都没解析出来）")
    total = max(0, round(sum(packages.values())))
    detail = "余额 0" if total == 0 else f"{total} credits（{len(packages)} 个包）"
    names = "、".join(f"{name} {value:g}" for name, value in packages.items())
    return QuotaSnapshot(state="available" if total > 0 else "exhausted",
                         source=source, detail=f"{detail}：{names}")


def _usage_packages(usage: dict) -> dict[str, float]:
    """把 `qoderUsage` 的额度层解析成 `{展示名: remaining}`（`qoder-credits.ts:315-336`）。

    顺序即展示顺序：套餐额度 → 资源包 → 专用资源包（`dedicatedResourcePackages[]`）。
    """
    out: dict[str, float] = {}
    for key, name in (("userQuota", "套餐额度"), ("addOnQuota", "资源包")):
        remaining = _quota_remaining(usage.get(key))
        if remaining is not None:
            out[name] = remaining
    dedicated = usage.get("dedicatedResourcePackages")
    if isinstance(dedicated, list):
        for index, item in enumerate(dedicated, start=1):
            remaining = _quota_remaining(item)
            if remaining is not None:
                key = "专用资源包" if len(dedicated) == 1 else f"专用资源包{index}"
                out[key] = remaining
    return out


def _quota_remaining(quota: Any) -> float | None:
    """单个额度对象的 `remaining`（缺失按 `max(0,total-used)`；负值 clamp 0）。"""
    if not isinstance(quota, dict):
        return None
    total = _number(quota.get("total"))
    used = _number(quota.get("used"))
    remaining = _number(quota.get("remaining"))
    if total is None and used is None and remaining is None:
        return None
    if remaining is not None:
        return max(0.0, remaining)
    return max(0.0, (total or 0.0) - (used or 0.0))


# ---------- 每日领取（`qoder-credits.ts::claimQoderDailyCheckin`）----------

async def claim(product: QoderProduct, cred: dict, meta: dict, *, precheck: bool) -> ClaimOutcome:
    """签到/领取：`campaigns` → 逐个 `/{campaignId}/claim`（`qoder-credits.ts:612-656`）。

    - 幂等 = 响应体 **`replayed:true`**（重复领取同样 HTTP 200，`qoder-credits.ts:53-57`）
      → `already_done`；
    - **「无可领活动」必须 `inactive`**（`:605-610`：旧实现报「今天已领取」是真实缺陷；
      未开通时给**可操作**提示 `NOT_ACTIVATED_HINT`）；
    - `precheck=True`（本产品 DSH 侧传 false，见 `jet-hub-rpc.ts:1753-1768`）：
      先查活动列表，**已领 → 直接 `already_done`、无可领 → `inactive`，都不发 claim**；
      有可领则继续领取（复用同一份列表，不重复 GET）。
    """
    _guard_family(product, cred)
    token = token_of(cred)
    if not token:
        # 凭据类：未发请求 → 不重试（`retryable=False` 缺省）
        return ClaimOutcome(category="failed", detail="凭据缺访问令牌，无法领取")
    machine = machine_identity()
    campaigns, campaigns_retryable = await _load_campaigns(product, token, machine)
    if campaigns is None:
        # 重试性由查询阶段的结构化判据给出（传输异常/5xx → True；4xx/结构 → False）
        return ClaimOutcome(category="failed", retryable=campaigns_retryable,
                            detail="活动列表查询失败（网络或响应异常）")
    claimable = [c for c in campaigns if c.get("actionType") == "CLAIM_BENEFIT"
                 and c.get("claimStatus") == "CLAIMABLE"]
    claimed_before = any(c.get("actionType") == "CLAIM_BENEFIT"
                         and c.get("claimStatus") == "CLAIMED" for c in campaigns)
    if not claimable:
        return await _no_target_outcome(product, token, machine, campaigns, claimed_before=claimed_before)
    total = 0.0
    claimed_n = 0
    replayed_n = 0
    first_error = ""
    first_retryable = False
    for campaign in claimable:
        outcome = await _claim_campaign(product, token, machine, str(campaign.get("campaignId") or ""))
        if outcome["kind"] == "claimed":
            claimed_n += 1
            total += outcome["amount"]
        elif outcome["kind"] == "already_done":
            replayed_n += 1
        elif not first_error:
            first_error = outcome["detail"]
            first_retryable = bool(outcome.get("retryable"))   # 与 first_error 同一条来源
    # 汇总口径照抄 DSH（`qoder-credits.ts:646-655`）：有成功 → claimed；否则有错 → failed；
    # 否则（全 replayed）→ already_done。
    if claimed_n and not first_error:
        return ClaimOutcome(category="success",
                            detail=f"领取成功：{claimed_n} 个活动，共 +{total:g} credits")
    if claimed_n:
        return ClaimOutcome(category="success",
                            detail=(f"部分成功：{claimed_n} 个活动 +{total:g} credits；"
                                    f"1+ 个失败（{first_error}）"))
    if first_error:
        return ClaimOutcome(category="failed", retryable=first_retryable, detail=first_error)
    return ClaimOutcome(category="already_done",
                        detail=f"今天已领取（服务端回放 replayed:true；{replayed_n} 个活动）")


async def _no_target_outcome(product: QoderProduct, token: str, machine: tuple[str, str] | None,
                             campaigns: list[dict], *, claimed_before: bool) -> ClaimOutcome:
    """没有可领活动时的三态判定（`qoder-credits.ts:623-644`）。

    ① 确有「已领」的领分类活动 → `already_done`；
    ② 未开通（活动列表无 `CLAIM_BENEFIT` **且** 用量响应无 `addOnQuota` 字段，两条同时满足）
       → `inactive` + 可操作提示；
    ③ 其余（未到刷新时间 / 请求头不完整 / 本就无活动）→ `inactive`。
    """
    if claimed_before:
        return ClaimOutcome(category="already_done", detail="今天已领取")
    hint = "" if machine is not None else _MACHINE_HEADER_NOTE
    usage = await _fetch_usage_raw(product, token, machine)
    if _is_not_activated(campaigns, usage):
        return ClaimOutcome(category="inactive", detail=NOT_ACTIVATED_HINT + hint)
    return ClaimOutcome(category="inactive", detail="当前没有可领取的活动" + hint)


def _is_not_activated(campaigns: list[dict], usage_body: Any) -> bool:
    """是否「尚未开通每日领取」（`qoder-credits.ts:121-137`）。

    两条**同时**满足才算：① 活动列表里没有 `CLAIM_BENEFIT`（连已领的都没有）；
    ② 用量响应 `qoderUsage.addOnQuota` **字段不存在**（缺失 ≠ 0：已开通账号用尽也有该字段）。
    """
    if any(c.get("actionType") == "CLAIM_BENEFIT" for c in campaigns):
        return False
    if not isinstance(usage_body, dict):
        return False
    usage = usage_body.get("qoderUsage")
    if not isinstance(usage, dict):
        return False
    return usage.get("addOnQuota") is None


async def _fetch_usage_raw(product: QoderProduct, token: str,
                           machine: tuple[str, str] | None) -> Any:
    """拉取用量原始响应体（只读；失败 → `None`，`qoder-credits.ts:146-162`）。"""
    try:
        response = await _request("GET", f"{product.open_api_base}{USAGE_PATH}",
                                  headers=sash_headers(product, token, machine=machine),
                                  timeout=CREDITS_TIMEOUT)
    except httpx.HTTPError:
        return None
    if not response.is_success:
        return None
    return _json_body_of(response)


async def _load_campaigns(product: QoderProduct, token: str,
                          machine: tuple[str, str] | None) -> tuple[list[dict] | None, bool]:
    """拉取活动列表（失败/形状非法 → `(None, retryable)`，`qoder-credits.ts:417-436`）。

    ⚠️ `claimable:false` 时**不代表没有活动**（今天已领后服务端回 `campaigns:[]`），
    故这里只解析、不下结论（`:366-377`）。
    `retryable` = 失败是否属**网络/5xx 类**（传输异常 → True；HTTP 5xx → True；
    4xx/结构异常 → False）；只读 GET，重放安全。
    """
    try:
        response = await _request("GET", f"{product.open_api_base}{CAMPAIGNS_PATH}",
                                  headers=sash_headers(product, token, machine=machine),
                                  timeout=CREDITS_TIMEOUT)
    except httpx.HTTPError:
        return None, True
    if not response.is_success:
        return None, response.status_code >= 500
    body = _json_body_of(response)
    if not isinstance(body, dict):
        return None, response.status_code >= 500
    raw = body.get("campaigns")
    if not isinstance(raw, list):
        return [], False
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        campaign_id = item.get("campaignId")
        if not isinstance(campaign_id, str) or not campaign_id:
            continue
        out.append({
            "campaignId": campaign_id,
            "actionType": item.get("actionType") if isinstance(item.get("actionType"), str) else "",
            "claimStatus": item.get("claimStatus") if isinstance(item.get("claimStatus"), str) else "",
            "amount": _number((item.get("benefit") or {}).get("amount")
                              if isinstance(item.get("benefit"), dict) else None) or 0.0,
        })
    return out, False


async def _claim_campaign(product: QoderProduct, token: str, machine: tuple[str, str] | None,
                          campaign_id: str) -> dict:
    """领取一个活动（`qoder-credits.ts:547-584`）。

    ⚠️ **请求体必须是空串**（抓包实测 `content-length: 0`）；发 `{}` 属未经验证的额外风险。
    ⚠️ 幂等判据是响应体 `replayed`，**不是 HTTP 状态码**（重复领取同样 200）。
    """
    url = f"{product.open_api_base}{CAMPAIGNS_PATH}/{_q(campaign_id)}/claim"
    try:
        response = await _request("POST", url,
                                  headers=sash_headers(product, token, machine=machine, json_body=True),
                                  content=b"", timeout=CREDITS_TIMEOUT)
    except httpx.HTTPError as e:
        # 网络类（传输异常）→ 可重试（服务端 `replayed` 幂等，重放不改终态）
        return {"kind": "failed", "amount": 0.0, "retryable": True,
                "detail": f"领取请求失败（{type(e).__name__}: {e}）"}
    body = _json_body_of(response)
    if body is None or not isinstance(body, dict):
        if response.status_code in (401, 403):
            return {"kind": "failed", "amount": 0.0, "retryable": False,
                    "detail": f"凭据已失效（HTTP {response.status_code}），请重新登录该账号"}
        return {"kind": "failed", "amount": 0.0,
                "retryable": response.status_code >= 500,   # 非 JSON：仅 5xx 可重试
                "detail": f"服务端返回了非 JSON 响应（HTTP {response.status_code}）"}
    if not response.is_success:
        return {"kind": "failed", "amount": 0.0,
                "retryable": response.status_code >= 500,   # 5xx = 服务端瞬时
                "detail": f"领取失败（HTTP {response.status_code}）"}
    if body.get("replayed") is True:
        return {"kind": "already_done", "amount": 0.0, "detail": "今天已领取"}
    status = body.get("status")
    if isinstance(status, str) and status and status != "CLAIMED":
        # 业务类（status 非 CLAIMED）→ 不重试：重放只会得到同一业务结论
        return {"kind": "failed", "amount": 0.0, "retryable": False,
                "detail": f"领取未成功（status={status}）"}
    benefit = body.get("benefit")
    amount = _number(benefit.get("amount")) if isinstance(benefit, dict) else None
    return {"kind": "claimed", "amount": amount or 0.0, "detail": "领取成功"}


# ---------- 模型目录（恒本地兜底表，零网络）----------

def list_models(product: QoderProduct, *, now: dt.datetime | None = None) -> list[ModelInfo]:
    """产品模型目录（§22.4：**恒本地兜底表**；目录端点需 WASM 签名，明确不实现，`21 §1.1`）。

    逐字段映射（来源 = `config.QoderModel`，即 DSH `QoderFallbackModel`）：
    - `id` = 目录 key（`qfmodel` 这类）—— 只有加密端点认（`qoder-product.ts:311-343`）；
    - `context_window` = 档位表最大档；`max_output` = **不编造**（DSH 兜底表无该字段）；
    - `image_input` = `supports_image`（缺省按 DSH 保守口径报 text-only，`qoder-adapter.ts:507-511`）；
    - `reasoning` / `effort_levels` = `efforts_for()`（`efforts` + 可关闭时追加 `none`；
      空数组 → DSH 不声明 `reasoning`，UI 显示「未提供推理等级」）；
    - `tool_call` = `None`（**未取到**：DSH 明确「工具支持不作为模型元数据播报」，`21 §1.2`）；
    - `vendor` = 空（DSH 兜底表无厂商字段 → 不编造；资源侧厂商归属由资源物化决定，§22.5-1）；
    - `free` / `rate` = `config.billing_info()`（`qoderDisplayName` 的复刻：`price_factor: 0`
      → 免费；错峰窗口内显示 `x原价→x折后价`，窗口外只显示原价，`qoder-adapter.ts:1099-1119`）。
      `now` 是折扣窗口判定的注入缝（缺省 = 当下；**窗口必须本地推算**，不采信目录的
      `promotion.active` 快照 —— 它是目录下发那一刻的值，客户端不重启就会过期）。

    ⚠️ **远端目录路径不存在**：DSH 的 `listModels` 恒用静态表（远端目录需签名，
    `qoder-product.ts:296-304`），本网关同款；故 free/rate 只在**静态表**这一条路径上计算。
    """
    out: list[ModelInfo] = []
    for model in product.fallback_models:
        efforts = efforts_for(model)
        free, rate = billing_info(model, now)
        out.append(ModelInfo(
            id=model.id,
            name=model.name,
            vendor="",
            context_window=model.context_window,
            max_output=None,
            tool_call=None,
            image_input=model.supports_image,
            reasoning=bool(efforts),
            effort_levels=efforts,
            free=free,
            rate=rate,
        ))
    return out


# ---------- 小工具 ----------

def _read_string(source: dict, keys: tuple[str, ...]) -> str | None:
    """读第一个非空字符串字段（容忍缺失与类型错误，`qoder.ts:179-185`）。"""
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _read_timestamp(value: Any) -> int | None:
    """时间值 → 毫秒时间戳（兼容 ISO 串与秒/毫秒数字；**无法解析返回 None 不填 0**）。

    照抄 `qoder.ts:193-203`：10 位视为秒、13 位视为毫秒。
    """
    if isinstance(value, (int, float)) and value > 0:
        return round(value * 1000) if value < 1e12 else round(value)
    if isinstance(value, str) and value:
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return round(parsed.timestamp() * 1000)
    return None


def _number(value: Any) -> float | None:
    """安全读数字（容忍字符串与缺失，`qoder-credits.ts:207-217`）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _q(value: str) -> str:
    """URL 组件编码（照抄 `encodeURIComponent` 的语义；campaignId 必须编码）。"""
    return urllib.parse.quote(str(value), safe="")
