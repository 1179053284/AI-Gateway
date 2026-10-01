"""LobsterAI 登录与凭据续期（`/api/auth/*`；§22.4 行 + `20 §1.2/§2.5`）。

## 登录形态：local_callback 两步式（本机回跳接收端 + 粘贴兜底）

DSH 的做法（`src/lobsterai-oauth.ts:232-313`）：**自己起一个 127.0.0.1 随机端口的回调服务器**，
`redirect_uri = http://127.0.0.1:{port}/auth/callback`，门户回跳后**就地完成 exchange**
（`:276-286`：exchange 在请求处理器里做完，才回 200「登录成功」页）。

🔴 更正一处**曾经写错的口径**（BD4，2026-09-30）：此前本模块注释说"网关自己就是那个本地
服务器"—— **不成立**：网关的 FastAPI 上没有 `/auth/callback` 这条路由（实测
`GET http://127.0.0.1:8300/auth/callback` → 404），把 `redirect_uri` 指到网关端口只会让
浏览器落在一页 404 上。真正的接收端 = `accounts/callback_server.py`（引擎随会话创建、
**只绑 127.0.0.1**、随机 ≥10000 端口；声明表见 `product.py::_CALLBACK`）。
门户校验的是 `redirect_uri` 的**形状** `http://127.0.0.1:{port}/auth/callback`
（`lobsterai-oauth.ts:95-97`）—— 端口可以随机，形状不行，故本模块仍按该形状拼。

落地为（两条投递、同一出口）：

    login_start(session)      → 生成一次性 state/uuid/first_keyfrom，
                                用**接收端实际端口**拼 portal 登录 URL
    浏览器完成授权后回跳      → 接收端收到 `?code=…&state=…`（`state` 不符 → 400 且继续监听）
                                → 引擎 `_deliver` → `login_callback(session, {"url": 整串})`
    （兜底）地址栏整串粘回来   → 同一个 `login_callback`、同一套 `state` 校验与 exchange

失败语义照取证：`state` 不匹配 = 不是本次登录发起的回调（或伪造）→ **直接拒绝**
（`lobsterai-oauth.ts:262-269`，DSH 回 HTTP 400；本层折叠成 `LoginOutcome(state="failed")`）；
exchange 失败 → 本次登录作废（Go/DSH 同：授权码一次性，重试无意义）。
关闭语义由 `accounts/login.py::LoginEngine` 提供：终态出表、取消即失效、TTL 600s
（与 DSH 的 10 分钟登录窗口 `lobsterai.ts:52` 同值），并**一并关闭接收端**。
"""

from __future__ import annotations

import logging
import time
import uuid
from urllib.parse import parse_qs, urlencode, urlparse

from model_gateway.accounts import callback_server, device, net, store
from model_gateway.accounts.registry import get as registry_get
from model_gateway.accounts.types import NotRefreshable
from model_gateway.upstream.lobsterai import const, protocol

logger = logging.getLogger("model_gateway.accounts")

#: 版本号缓存（`lobsterai.ts:618-675` 的进程内缓存语义；键 = value + 取到的时刻）
_VERSION_CACHE: dict = {"value": "", "at": 0.0}


class LoginError(RuntimeError):
    """登录流程的**可预期失败**（网络 / 信封 / 缺 accessToken）。

    由钩子折叠成 `LoginOutcome(state="failed", detail=…)` —— 用户看得见的失败，
    不是"内部故障"（`accounts/login.py` 的「引擎不吞异常」针对的是**未预期**异常）。
    """


def _now_ms() -> int:
    return int(time.time() * 1000)


# ---------- 客户端版本号 ----------

def _reset_client_version_cache() -> None:
    """清空版本号缓存（**只供测试**：模块级缓存在用例之间会串扰）。"""
    _VERSION_CACHE.update(value="", at=0.0)


def _version_from_update(body: object) -> str:
    """从更新接口响应取 `data.value.version`（`lobsterai.ts:602-609`）。

    ⚠️ 该响应**不是统一信封**：`code`/`msg` 在外层、载荷在 `data.value`
    （`lobsterai-product.ts:80-86` 记录的实测形状）。
    """
    if not isinstance(body, dict):
        return ""
    outer = body.get("data")
    if not isinstance(outer, dict):
        return ""
    value = outer.get("value")
    if not isinstance(value, dict):
        return ""
    return protocol.parse_version(value.get("version"))


async def client_version() -> str:
    """解析客户端版本号：缓存 → 远端 → 兜底常量（`lobsterai.ts:642-668`）。

    三个消费点都需要它：exchange 的 `version` 字段、续期请求体的 `version`、
    签到的必填 query 参数（集中在这一处，避免三处各拉一次）。
    🔴 兜底值**刻意不缓存**（`lobsterai.ts:663-666`）：缓存会让一次瞬时故障在 12 小时
       TTL 内持续影响后续请求。
    """
    now = time.monotonic()
    if _VERSION_CACHE["value"] and now - _VERSION_CACHE["at"] < const.VERSION_CACHE_TTL_S:
        return str(_VERSION_CACHE["value"])
    result = await protocol.fetch_json(const.CLIENT_VERSION_API, headers={
        "Accept": "application/json", "User-Agent": const.USER_AGENT})
    if result.reachable and result.status == 200:
        version = _version_from_update(result.body)
        if version:
            _VERSION_CACHE.update(value=version, at=now)
            return version
    return const.FALLBACK_CLIENT_VERSION


def client_version_cached() -> str:
    """**同步**取版本号：命中未过期缓存则用真值，否则回退兜底常量（不做网络 IO）。

    为什么需要它（M6-5b）：出站适配器的头钩子（§22.3 `auth_headers`）是**同步**函数，
    不能 await `client_version()`（那会在事件循环里做网络 IO，§22.8-1）——
    而 `X-LobsterAI-Client-Version` 是 chat 请求的取证头（`lobsterai.ts:517-530`）。
    语义：本进程此前（登录 / 续期 / 签到 / 目录）若已拉到未过 TTL 的真值就用它；
    否则用兜底常量 —— DSH 侧 Go 长期发假值 `0.1.0` 未被拒（服务端不强校验版本，
    `lobsterai.ts:545-550`），宁可用稍旧版本号也不在同步钩子里发网络请求。
    """
    now = time.monotonic()
    if _VERSION_CACHE["value"] and now - _VERSION_CACHE["at"] < const.VERSION_CACHE_TTL_S:
        return str(_VERSION_CACHE["value"])
    return const.FALLBACK_CLIENT_VERSION


# ---------- 登录 URL / 会话态 ----------

def gateway_port() -> int:
    """网关自身监听端口 —— **只作粘贴兜底**用（BD4 之后不再是 `redirect_uri` 的默认值）。

    🔴 别误解：网关**不是**回跳接收端。FastAPI 上没有 `/auth/callback` 路由
       （实测 `GET http://127.0.0.1:8300/auth/callback` → 404），把回跳指到这里
       只能拿到"地址栏里那条完整 URL 供人粘回来"这一个效果。
       正常路径的端口 = `accounts/callback_server.py` 接收端**实际绑定**的端口
       （`product.py::login_start` 经 `callback_server.declared_port(session)` 取）。
    本函数的唯一剩余用处：接收端起不来（端口全被占 / 无权限）时给 `redirect_uri`
    一个**形状合法**的端口（门户校验形状，`lobsterai-oauth.ts:95-97`），
    让登录退化成粘贴兜底而不是当场弹不出来。

    取证：门户校验 `redirect_uri` 必须是 `http://127.0.0.1:{port}/auth/callback` 形态
    （`lobsterai-oauth.ts:96-97` 引 `main.go:223-225`）。

    配置读不动时回落到 schema 默认值 8300：端口只影响回跳落点，不该让登录向导
    整个弹不出来（真正的配置错误会在加载/保存路径上被明确报出）。
    """
    try:
        from model_gateway.config.loader import load_config

        return int(load_config().gateway.port)
    except Exception:  # noqa: BLE001 —— 见上：读配置失败不该阻断登录向导
        return 8300


def login_url(port: int, state: str) -> str:
    """构造 portal 登录 URL（`lobsterai-oauth.ts:104-116` = `main.go:225-228` 的形态）。

    形态：`{portal}/portal#/login?source=electron&redirect_uri=…&state=…`

    - `source=electron`：声明登录来源是桌面客户端（门户据此选择交互流程）；
    - `redirect_uri`：**必须**是 `http://127.0.0.1:{port}/auth/callback`；
      🔴 `port` 传回跳接收端的**实际**端口（BD4：`callback_server.declared_port(session)`；
      接收端用随机端口，门户只校验**形状**，`lobsterai-oauth.ts:95-97`）；
    - `state`：防 CSRF 的一次性随机串，回跳时原样带回并比对（接收端与
      `login_callback` **各校验一次**，同一把基准）。

    ⚠️ `redirect_uri` 含 `://` 与 `:`，必须百分号编码 —— 用 `urlencode` 而不是手拼
    （手拼极易漏编码导致登录页校验失败）；hash 段（`#/login`）不属于 query，只能显式拼装。
    """
    redirect_uri = f"http://127.0.0.1:{port}{const.CALLBACK_PATH}"
    query = urlencode({"source": "electron", "redirect_uri": redirect_uri, "state": state})
    return f"{const.PORTAL_BASE}/portal#/login?{query}"


def redirect_port(session) -> int:
    """本次登录 `redirect_uri` 的端口：接收端**实际**端口，起不来时退回兜底端口（BD4）。

    没有接收端（引擎起监听失败 / 直接构造的会话）→ `gateway_port()`：
    形状仍然合法、门户照样回跳，只是落点没人听 → 用户按兜底口径把地址栏粘回来。
    """
    return (callback_server.declared_port(session)
            or gateway_port())


def _new_device_uuid() -> str:
    """生成**跨账号唯一**的安装 UUID（§15.1 硬约束 1 / §22.2 不变式③）。

    DSH 只做 `randomUUID()`（`lobsterai-oauth.ts:83-85`）；本网关多走一道
    `accounts/device.py::generate_unique` 的跨账号查重。`uuid` 是本产品**唯一身份字段**
    （§22.3/§22.4 裁决 2026-09-29；`first_keyfrom`/`latest_keyfrom` 属账号元数据、
    不参与唯一性）→ 直接用注册表规格走公共层单字段路径，**不再做单字段投影**
    （投影曾是 M6-2 绕开多字段查重缺陷的临时绕行，缺陷已在公共层修根）。
    查重路径不可用（账号根读不动等）时**降级为随机 uuid4**：唯一性检查不该让登录
    起不来（碰撞概率 ~0，且随机 uuid 正是参考实现的行为）。
    """
    try:
        spec = registry_get(const.PRODUCT_ID).device
        root = store.product_root(const.PRODUCT_ID)
        return device.generate_unique(root, spec)
    except Exception:  # noqa: BLE001 —— 见上：查重失败降级，不阻断登录
        return str(uuid.uuid4())


def new_login_state() -> dict:
    """生成一次性登录会话态（进 `session.state`，**绝不进 `Challenge`**）。

    - `state`：防 CSRF 的一次性随机串（`lobsterai-oauth.ts:238` 用 `randomUUID`）；
    - `uuid`：安装 UUID —— 登录时生成、之后**每次续期原样回传**，是服务端识别「同一安装」
      的依据（`lobsterai.ts:102-109`），**不能每次刷新都重新生成**；
    - `first_keyfrom`：首次登录时间戳（毫秒字符串，`main.go:166` `newUuid()` 同一批生成）。
    """
    return {"state": str(uuid.uuid4()), "uuid": _new_device_uuid(),
            "first_keyfrom": str(_now_ms())}


def callback_code_state(params: dict) -> tuple[str, str]:
    """从回跳参数取 `(code, state)`；取不到返回 `("", "")`。

    只认两种形态（接收端投递与人工粘贴**共用**这一个取值口，不做更多别名猜测）：
    ① 显式 `{"code": …, "state": …}`；② `{"url": "…/auth/callback?code=…&state=…"}`
    —— 整串地址（接收端交来的真 URL，与浏览器地址栏复制出来的串同形）
    或仅 `code=…&state=…` 查询串（缺 `?` 时自动补）。
    """
    if not isinstance(params, dict):
        return "", ""
    code = str(params.get("code") or "").strip()
    if code:
        return code, str(params.get("state") or "").strip()
    raw = str(params.get("url") or "").strip()
    if not raw:
        return "", ""
    if "?" not in raw and "=" in raw:
        raw = "?" + raw
    values = parse_qs(urlparse(raw).query)
    return (values.get("code") or [""])[0].strip(), (values.get("state") or [""])[0].strip()


# ---------- 授权码换凭据 ----------

async def exchange(code: str, *, device_uuid: str, first_keyfrom: str, version: str) -> dict:
    """用授权码换凭据（`lobsterai-oauth.ts:130-185`）。

    请求体**必须**含 5 个字段（对齐 `main.go:264-270`）：`authCode` / `firstKeyfrom` /
    `latestKeyfrom` / `uuid` / `version`；其中 `latestKeyfrom` 取**当前时刻**
    （与 `first_keyfrom` 分工：后者是首次登录时间戳、前者是本会话最近活动）。
    该端点**不需要** `Authorization`（换 token 时还没有 token）。
    """
    now_ms = _now_ms()
    body = {
        "authCode": code,
        "firstKeyfrom": first_keyfrom,
        "latestKeyfrom": str(now_ms),
        "uuid": device_uuid,
        "version": version,
    }
    result = await protocol.fetch_json(f"{const.API_BASE}{const.PATH_EXCHANGE}",
                                       method="POST", headers=protocol.anonymous_headers(),
                                       body=body)
    if not result.reachable:
        raise LoginError(f"exchange 网络失败：{result.error}")
    if not isinstance(result.body, dict):
        raise LoginError(f"exchange 响应不是 JSON（HTTP {result.status}）")
    envelope = protocol.parse_envelope(result.body)
    if not envelope.ok:
        raise LoginError(protocol.envelope_failure(
            result, envelope, f"exchange 失败（code={envelope.code}）"))
    payload = protocol.parse_token_payload(envelope.data)
    if not payload.access_token:
        # 与 Go 的 `refresh_failed: no accessToken` 同理：没有令牌就没有可用凭据，
        # 不能把半成品存进凭据库（`lobsterai-oauth.ts:174-178`）。
        raise LoginError("exchange 响应缺少 accessToken")
    logger.info("lobsterai 登录换取凭据成功（token 指纹 %s）",
                net.cred_fingerprint(payload.access_token))
    return protocol.build_credential(payload, uuid=device_uuid, first_keyfrom=first_keyfrom,
                                     latest_keyfrom=str(now_ms), now_ms=now_ms)


# ---------- 续期 ----------

async def refresh_credential(cred: dict, meta: dict | None = None) -> dict:
    """凭据续期（`lobsterai-auth.ts:519-562` + `lobsterai.ts:333-341`）。

    三条**终态**判定（映射为 `accounts/types.py::NotRefreshable`；比 Go 精确：Go 只判
    「响应里有没有 accessToken」，会把网络抖动也当成终态，见 `lobsterai-auth.ts:377-384`）：

    1. 本地无 `refresh_token` → 只能重新登录；
    2. HTTP 401/403 **或**响应体命中会话终止标记（40100/40101…）→ `refresh_token` 已被拒；
    3. `code:0` 但缺 `accessToken` → 与 Go 的 `refresh_failed` 同理。

    其余失败（网络抖动 / 非 JSON / 非终态业务码）抛 `ProtocolError` —— **可重试**，
    由调用方决定退避重试（§22.6：失败退避仅网络/5xx、**业务码不重试**）。
    成功后把新的 `expires_at` **回写 `meta.json`**（照抄 DSH 的真实缺陷教训 !IKIRTT：
    只更新凭据不写回池值，界面会永远显示「已过期」且没有自救手段，`lobsterai-auth.ts:420-425`）。
    """
    if not protocol.read_str(cred, "refresh_token"):
        raise NotRefreshable("无 refresh_token，请重新登录")
    version = await client_version()
    result = await protocol.fetch_json(
        f"{const.API_BASE}{const.PATH_REFRESH}", method="POST",
        headers=protocol.anonymous_headers(), body=protocol.refresh_body(cred, version))
    if not result.reachable:
        raise protocol.ProtocolError(f"续期网络失败：{result.error}")
    if not isinstance(result.body, dict):
        raise protocol.ProtocolError(f"续期响应不是 JSON（HTTP {result.status}）")
    envelope = protocol.parse_envelope(result.body)
    if not envelope.ok:
        if result.status in (401, 403) or protocol.is_session_dead(result.text):
            raise NotRefreshable(f"refresh_token 已被后端拒绝：{envelope.message}")
        raise protocol.ProtocolError(f"续期失败：{envelope.message}")
    payload = protocol.parse_token_payload(envelope.data)
    if not payload.access_token:
        raise NotRefreshable("续期响应缺少 accessToken，请重新登录")
    merged = protocol.merge_refreshed(cred, payload, now_ms=_now_ms())
    logger.info("lobsterai 续期成功（新 token 指纹 %s）",
                net.cred_fingerprint(protocol.read_str(merged, "access_token")))
    if isinstance(meta, dict):
        expires = protocol.credential_expires_at_ms(merged)
        if expires is not None:
            protocol.write_meta_fields(str(meta.get("dir") or ""), {"expires_at": int(expires)})
    return merged
