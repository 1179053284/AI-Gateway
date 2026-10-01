"""CodeBuddy 系（buddy / workbuddy）**共享钩子实现**（tech-design v2.0 §22.3 冻结签名的实现面）。

两个产品共用本文件（同一后端协议：`product.ts:1-30`「同源、共用同一 CLI 内核与同一套
ProductProvider 机制，差异全部收敛到 product 配置」）；差异由 `ProductProfile` 参数表达，
`upstream/<product>/product.py` 只做薄接线（§22.1：不做通用 DSL，只做已证实的共性）。

🔴 纪律（逐条可查）：
  ① 上游调用**只经** `accounts/net.py::make_client`（显式超时，§22.8-1）→ 测试可
     monkeypatch 该工厂注入 `httpx.MockTransport`；
  ② 会话私有态只进 `LoginSession.state`（绝不进 `Challenge` / `LoginOutcome.detail`，§22.3）；
  ③ **钩子内不打轮询循环、不 sleep**：DSH 在钩子里循环 1s×5min（`buddy.ts:44-46`），
     本网关由入口层驱动轮询、总时限由会话 TTL 600s 兜住（§22.8-2/§22.8-1）；
  ④ **失败清占位**（`jet-hub-rpc.ts:849-876`）：DSH 先写启用的占位账号、失败再移除；
     本引擎的账号**只在登录成功时**由 `store.commit_login` 物化（§22.3），
     结构上不存在"幽灵占位"——失败时只需让会话按终态出表（由 `accounts/login.py` 负责）；
  ⑤ 凭据**不回写**：续期只返回新凭据体，落盘唯一入口是 `store.commit_login`（§22.2 不变式⑤）；
  ⑥ 失败折叠：可预期失败折叠成 `LoginOutcome(state="failed")` / `QuotaSnapshot(unknown)` /
     `ClaimOutcome(failed)`；**网络与凭据缺失一律 fail closed**（§22.8-5），不编造成功。
"""

from __future__ import annotations

import logging

import httpx

from model_gateway.accounts import net
from model_gateway.accounts.registry import get as registry_get
from model_gateway.accounts.types import (
    Challenge,
    ClaimOutcome,
    LoginOutcome,
    ModelInfo,
    NotRefreshable,
    ProbeResult,
    QuotaSnapshot,
)
from model_gateway.upstream.buddy import protocol as p

logger = logging.getLogger("model_gateway.accounts")


# ── 内部工具 ──────────────────────────────────────────────────────────

async def _request(client: httpx.AsyncClient, method: str, path: str, *,
                   headers: dict | None = None, params: dict | None = None,
                   body: dict | None = None) -> tuple[int, object | None]:
    """发一次请求并尽力解析 JSON：返回 `(status, body|None)`。

    🔴 **不用 `response.json()` 直接判失败**（`credits.ts:285-294` 的真实缺陷复盘）：
       凭据过期时腾讯网关返回 **HTML 错误页**，`json()` 抛出的
       `Unexpected token '<'` 对用户毫无意义 → 这里吞掉解析异常回 `None`，
       由调用方带上 HTTP 状态码给出可读原因。网络异常**照常抛出**（由各钩子 folding）。
    """
    response = await client.request(method, path, headers=headers, params=params, json=body)
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, None


def _profile_client(profile: p.ProductProfile, timeout_s: float) -> httpx.AsyncClient:
    """按产品基址建客户端（`base_url` 唯一事实源 = 注册表；超时显式，§22.8-1）。"""
    return net.make_client(base_url=profile.base_url, timeout=timeout_s)


def _checkin_supported(profile: p.ProductProfile) -> bool:
    """签到能力位（判据不是标签，§22.6）：唯一事实源 = `accounts/registry.py`（`20 §3.1`）。"""
    return registry_get(profile.id).capabilities.checkin


# ── 登录（external_link 轮询型，`jet-hub-rpc.ts:835-877` + `buddy-oauth.ts:137-277`）──

async def start_login(profile: p.ProductProfile, session) -> Challenge:
    """两步式第一步：`POST /v2/plugin/auth/state?platform=<platform>` → 外链授权页 URL。

    `Challenge` 只承载用户可见物（`url`）；轮询所需的 `state` 留在 `session.state`。
    """
    try:
        async with _profile_client(profile, p.STATE_TIMEOUT_S) as client:
            status, body = await _request(
                client, "POST", p.AUTH_STATE_PATH,
                headers=p.state_headers(profile),
                params={"platform": profile.platform})
    except httpx.HTTPError as e:
        # 对齐 DSH 的可读文案（`jet-hub-rpc.ts:844-847`：网络失败要指向"登录地址取不到"）
        raise RuntimeError(f"无法获取 {profile.title} 登录地址（网络请求失败）：{e}") from e
    if status != 200:
        raise RuntimeError(f"auth/state HTTP {status}：{p.message_of(body)}")
    data = p.data_of(body)
    if not isinstance(data, dict):
        raise RuntimeError("auth/state 响应缺少 data 字段")
    auth_state = p.read_str(data, "state")
    auth_url = p.read_str(data, "authUrl")
    if not auth_state:
        raise RuntimeError("auth/state 响应缺少 state 字段")
    if not auth_url:
        raise RuntimeError("auth/state 响应缺少 authUrl 字段")
    session.state["auth_state"] = auth_state
    decorated = p.decorate_login_url(auth_url, profile)
    session.state["auth_url"] = decorated
    return Challenge(url=decorated)


async def _poll_token(profile: p.ProductProfile, auth_state: str) -> tuple[dict | None, LoginOutcome | None]:
    """轮询 token（`buddy-oauth.ts:178-222`）：就绪返回 `(token, None)`，否则 `(None, outcome)`。"""
    try:
        async with _profile_client(profile, p.REQUEST_TIMEOUT_S) as client:
            status, body = await _request(
                client, "GET", p.AUTH_TOKEN_PATH,
                headers=p.token_poll_headers(profile), params={"state": auth_state})
    except httpx.HTTPError as e:
        # DSH：网络错误继续轮询（不中断登录流程，`buddy-oauth.ts:206-209`）
        return None, LoginOutcome(state="pending", detail=f"token 轮询网络错误（继续等待）：{e}")
    if status == 200:
        data = p.data_of(body)
        if not isinstance(data, dict):
            return None, LoginOutcome(state="pending", detail="token 尚未就绪（响应无 data）")
        token = p.parse_token_data(data)
        # 空令牌**不得**当成功（`token` 响应可能只带相对过期时间；空 accessToken 若放行
        # 会落盘一个永远 401 的凭据 —— 对齐 `expiry-sync.ts:201-206`「绝不把空令牌落盘」）
        if not token["access_token"]:
            return None, LoginOutcome(state="pending", detail="token 尚未就绪（响应无 accessToken）")
        return token, None
    if p.code_of(body) == p.CODE_TOKEN_NOT_READY:
        return None, LoginOutcome(state="pending", detail="等待用户在浏览器完成授权")
    return None, LoginOutcome(
        state="failed",
        detail=f"auth/token HTTP {status} code={p.code_of(body)}：{p.message_of(body)}")


async def poll_login(profile: p.ProductProfile, session) -> LoginOutcome:
    """两步式第二步：轮询 token → 轮询账户 → 组装凭据（`buddy-oauth.ts:549-589`）。

    🔴 `pending` 是**正常业务状态**（用户还没点完），不是错误（§22.3）。
    """
    auth_state = str(session.state.get("auth_state") or "")
    if not auth_state:
        return LoginOutcome(state="failed",
                            detail="会话缺少 auth state（登录未正确启动，请重新发起）")
    token = session.state.get("token")
    if not isinstance(token, dict) or not token.get("access_token"):
        token, outcome = await _poll_token(profile, auth_state)
        if outcome is not None:
            return outcome
        session.state["token"] = token       # 缓存：避免下一轮重复取 token
    try:
        async with _profile_client(profile, p.REQUEST_TIMEOUT_S) as client:
            status, body = await _request(
                client, "GET", p.LOGIN_ACCOUNT_PATH,
                headers=p.account_headers(profile, token), params={"state": auth_state})
    except httpx.HTTPError as e:
        return LoginOutcome(state="pending", detail=f"账户信息轮询网络错误（继续等待）：{e}")
    if status == 200 and isinstance(p.data_of(body), dict):
        account = p.parse_account_data(p.data_of(body))
        credential = p.build_credential(token, account)
        meta = {
            "uid": p.read_str(account, "uid"),
            "nickname": p.read_str(account, "nickname"),
            "account_type": p.read_str(account, "account_type"),
        }
        return LoginOutcome(state="success", credentials=credential, meta=meta,
                            detail=f"登录成功（{profile.title}）")
    if p.code_of(body) == p.CODE_ACCOUNT_NOT_READY:
        return LoginOutcome(state="pending", detail="账户信息尚未完成（请稍候）")
    return LoginOutcome(
        state="failed",
        detail=f"login/account HTTP {status} code={p.code_of(body)}：{p.message_of(body)}")


# ── 续期（`buddy-oauth.ts:289-329` + `buddy-auth.ts:272-285`）────────────

async def refresh_credential(profile: p.ProductProfile, cred: dict, meta: dict) -> dict:
    """静默续期：`POST /v2/plugin/auth/token/refresh` → **新的**凭据体（§22.3）。

    - 无 `refresh_token` → `NotRefreshable`（DSH：`RefreshTokenExpiredError('无 refresh_token')`，
      `buddy-oauth.ts:295-297`）——**不是**异常故障、不触发冷却（§22.3）；
    - `refresh_token` 被后端判定失效（HTTP/业务码 401/403，或 message 含 expired/invalid）
      → `NotRefreshable`（停止重试、提示重新登录，`buddy-oauth.ts:312-324`）；
    - 其余失败（网络/5xx）→ 普通异常（可重试，由调用方按 §22.6 退避）。
    """
    del meta  # 形参按 §22.3 保留：本产品无设备身份、无私有文件（`20 §2.7`），不读账号目录
    refresh_token = p.refresh_token_of(cred)
    if not refresh_token:
        raise NotRefreshable("无 refresh_token，请重新登录")
    try:
        async with _profile_client(profile, p.REQUEST_TIMEOUT_S) as client:
            status, body = await _request(client, "POST", p.AUTH_REFRESH_PATH,
                                          headers=p.refresh_headers(profile, cred))
    except httpx.HTTPError as e:
        raise RuntimeError(f"刷新 token 网络错误（可重试）：{e}") from e
    if status != 200:
        code = p.code_of(body)
        message = p.message_of(body)
        expired = status in (401, 403) or code in (401, 403) \
            or "expired" in message or "invalid" in message
        if expired:
            raise NotRefreshable(message or f"HTTP {status}")
        raise RuntimeError(f"刷新 token HTTP {status} code={code}：{message}")
    data = p.data_of(body)
    if not isinstance(data, dict):
        raise RuntimeError("刷新 token 响应缺少 data 字段")
    new_token = p.parse_token_data(data)
    # 空令牌绝不上盘（`expiry-sync.ts:201-206`：会把好凭据覆盖成死值）
    if not new_token["access_token"]:
        raise RuntimeError("刷新响应缺少 accessToken（不写回空令牌）")
    # 字段合并照抄 `buddy-auth.ts:272-285`；**两处加固**：
    # ① 新 refresh_token 为空时保留旧值（不丢续期能力）；② domain 为空时保留旧值。
    return {
        **cred,
        "access_token": new_token["access_token"],
        "refresh_token": new_token["refresh_token"] or refresh_token,
        "expires_at": new_token["expires_at"],
        "refresh_expires_at": new_token["refresh_expires_at"],
        "token_type": new_token["token_type"],
        "scope": new_token["scope"],
        **({"domain": new_token["domain"]} if new_token["domain"] else {}),
    }


# ── 探活（§22.3「连通 / 凭据有效」两维）────────────────────────────────

async def probe(profile: p.ProductProfile, cred: dict, meta: dict) -> ProbeResult:
    """探活：连通（拿到了 HTTP 响应）+ 凭据有效（上游认可该凭据）**两维分开**。

    判据端点 = `get-user-resource`（`credits.ts:39-50`：两产品通用、只需 Bearer、
    **不消耗额度**）。DSH 的探活是"发一次真实 chat"（`account-probe.ts:163-206`），
    属出站适配面（M6-5 接线）；本波次用计费端点做**凭据级**判定，避免为探活烧额度。
    """
    del meta  # 形参按 §22.3 保留（同 refresh 的说明）
    if not p.access_token_of(cred):
        return ProbeResult(reachable=False, valid=False,
                           detail="凭据缺少 access_token（未登录，未发请求）")
    try:
        async with _profile_client(profile, p.REQUEST_TIMEOUT_S) as client:
            status, body = await _request(client, "POST", p.USER_RESOURCE_PATH,
                                          headers=p.identity_headers(profile, cred), body={})
    except httpx.HTTPError as e:
        return ProbeResult(reachable=False, valid=False, detail=f"上游不可达：{e}")
    if status in (401, 403):
        return ProbeResult(reachable=True, valid=False,
                           detail=f"凭据已失效（HTTP {status}），请重新登录")
    if isinstance(body, dict) and p.code_of(body) in (401, 403):
        return ProbeResult(reachable=True, valid=False,
                           detail=f"凭据已失效（业务码 {p.code_of(body)}），请重新登录")
    if status == 200 and isinstance(body, dict) and p.code_of(body) == p.CODE_OK:
        return ProbeResult(reachable=True, valid=True, detail="凭据有效")
    if status == 200 and not isinstance(body, dict):
        # 200 但非 JSON：腾讯网关在异常时会回 HTML 页面 —— **不得**当成「凭据有效」
        # （`code_of(None)` 会是 0，直接判 code 会把这类响应误判为有效）
        return ProbeResult(reachable=True, valid=False,
                           detail="响应不是 JSON（凭据失效时网关会回 HTML 错误页）")
    if status == 200:
        return ProbeResult(reachable=True, valid=False,
                           detail=f"上游拒绝（业务码 {p.code_of(body)}：{p.message_of(body)}）")
    return ProbeResult(reachable=True, valid=False, detail=f"HTTP {status}")


# ── 额度（`credits.ts:494-531`；三态语义见 `23 B2`）────────────────────

async def quota(profile: p.ProductProfile, cred: dict, meta: dict) -> QuotaSnapshot:
    """余额快照：`available` / `exhausted` / `unknown` —— **未知不当零**（§22.3）。"""
    del meta  # 形参按 §22.3 保留（同 refresh 的说明）
    source = f"{profile.id}-billing"
    if not p.access_token_of(cred):
        return QuotaSnapshot(state="unknown", source=source,
                             detail="凭据缺少 access_token（未登录，未发请求）")
    try:
        async with _profile_client(profile, p.REQUEST_TIMEOUT_S) as client:
            status, body = await _request(client, "POST", p.USER_RESOURCE_PATH,
                                          headers=p.identity_headers(profile, cred), body={})
    except httpx.HTTPError as e:
        return QuotaSnapshot(state="unknown", source=source, detail=f"余额查询网络错误：{e}")
    if status != 200:
        return QuotaSnapshot(state="unknown", source=source, detail=f"余额查询 HTTP {status}")
    if not isinstance(body, dict):
        return QuotaSnapshot(state="unknown", source=source,
                             detail="响应不是 JSON（凭据失效时网关会回 HTML 错误页）")
    if p.code_of(body) != p.CODE_OK:
        return QuotaSnapshot(state="unknown", source=source,
                             detail=f"业务码 {p.code_of(body)}：{p.message_of(body)}")
    summary = p.summarize_balance(body)
    if summary is None:
        return QuotaSnapshot(state="unknown", source=source,
                             detail="响应缺少 data.Response.Data.Accounts（结构变更？）")
    unit = summary.unit or "credits"
    detail = f"有效包 {summary.active_count} 个，本周期剩余 {summary.total:g} {unit}"
    if summary.expired_count:
        detail += f"；另有 {summary.expired_count} 个失效包（{summary.expired_total:g}，不可扣费）"
    return QuotaSnapshot(state="available" if summary.total > 0 else "exhausted",
                         source=source, detail=detail)


# ── 签到（`credits.ts:382-417` + `jet-hub-rpc.ts:461-531` 的 precheck 语义）──

async def _claim_buddy(profile: p.ProductProfile, cred: dict, *, precheck: bool) -> ClaimOutcome:
    """CodeBuddy 中国版签到：预检（可选）→ 领取（幂等 = HTTP 400 + 业务码 10001）。"""
    headers = p.identity_headers(profile, cred)
    async with _profile_client(profile, p.REQUEST_TIMEOUT_S) as client:
        if precheck:
            # 先查状态可省一次无效领取（`credits.ts:8-13`：必须用 checkin-activity-status，
            # 不能用 checkin-status——后者是占位数据）
            try:
                status, body = await _request(client, "POST", p.CHECKIN_ACTIVITY_STATUS_PATH,
                                              headers=headers, body={})
            except httpx.HTTPError as e:
                # 网络类（连接/超时）→ 结构化声明可重试（§22.6 失败退避仅网络/5xx）
                return ClaimOutcome(category="failed", retryable=True,
                                    detail=f"签到状态查询网络错误：{e}")
            state = p.parse_checkin_status(body) if status == 200 else None
            if state is not None and not state.active:
                # DSH 同款文案（`jet-hub-rpc.ts:510-511`）
                return ClaimOutcome(category="inactive", detail="签到活动未开启")
            if state is not None and state.today_checked_in:
                return ClaimOutcome(category="already_done", detail="今天已签到")
            # 状态查询失败（state is None）时**仍然尝试领取**：无法确认不代表不能领，
            # 交给领取接口以响应体 code 定夺（`jet-hub-rpc.ts:514-517` 原文语义）
        try:
            status, body = await _request(client, "POST", p.DAILY_CHECKIN_PATH,
                                          headers=headers, body={})
        except httpx.HTTPError as e:
            # 网络类（连接/超时）→ 可重试；签到幂等（重放回 10001）→ 重试不改终态
            return ClaimOutcome(category="failed", retryable=True,
                                detail=f"签到请求网络错误：{e}")
    if not isinstance(body, dict):
        # 非 JSON 多半是网关 HTML 错误页（凭据失效的典型表现，`credits.ts:308-315`）
        # → 凭据类不重试；仅当 HTTP 5xx（服务端瞬时）才声明可重试
        return ClaimOutcome(category="failed", retryable=(status >= 500),
                            detail=f"签到响应不是 JSON（HTTP {status}），请检查凭据是否有效")
    code = p.code_of(body)
    message = p.message_of(body)
    category = p.claim_category(code)
    if category == "already_done":
        # 幂等：重复领取是 HTTP 400 + code 10001，**不是失败**（`credits.ts:19-21,395-397`）
        return ClaimOutcome(category="already_done", detail=message or "今天已签到")
    if category == "inactive":
        return ClaimOutcome(category="inactive", detail=message or "当前无领取资格")
    if code != p.CODE_OK:
        # 业务码类（含 5xx JSON 体兜底）：重试与幂等无关、也治不了码本身的语义 → 不重试
        return ClaimOutcome(category="failed",
                            detail=f"业务码 {code}：{message or '领取失败'}")
    detail = p.parse_claim_success(body)
    if not detail:
        # 结构类失败（响应缺 data）：重试同一次请求不会让上游多出字段 → 不重试
        return ClaimOutcome(category="failed", detail="领取响应缺少 data 字段（不谎报成功）")
    return ClaimOutcome(category="success", detail=detail)


async def claim(profile: p.ProductProfile, cred: dict, meta: dict, *,
                precheck: bool) -> ClaimOutcome:
    """签到/领取（§22.6：结果语义 = ops 四类；`precheck` per-product 显式声明）。

    🔴 能力位是**判据**（§22.6「能力矩阵是判据不是标签」）：`checkin=False` 的产品
       （workbuddy/cline/raccoon，`20 §3.1`）没有可调用的签到端点 → 返回
       `inactive`（**正常业务状态**）+ 可读原因，而不是打一个必然失败的上游请求
       （DSH 同款工程习惯：`jet-hub-rpc.ts:1857-1888` 显式回可读业务错误，
       不用泛化的「未注册 provider」文案）。
    """
    del meta  # 形参按 §22.3 保留（同 refresh 的说明）
    if not _checkin_supported(profile):
        return ClaimOutcome(
            category="inactive",
            detail=f"{profile.title} 无每日签到端点（能力位 checkin=False，`20 §3.1`）")
    if not p.access_token_of(cred):
        # 凭据类：未发请求，重试不会变出令牌 → 不重试（`retryable=False` 缺省）
        return ClaimOutcome(category="failed", detail="凭据缺少 access_token（未登录，未发请求）")
    return await _claim_buddy(profile, cred, precheck=precheck)


# ── 模型目录（`buddy-oauth.ts:348-408` + `buddy-adapter.ts:901-948`）──────

async def list_models(profile: p.ProductProfile, cred: dict, meta: dict) -> list[ModelInfo]:
    """产品模型目录：远端 `/v3/config` + 产品兜底表合并（§22.5-4；取不到不编造）。

    取不到凭据 / 远端失败 → **兜底表**（`product.ts:126-135`：该表是 IDE `product.json`
    内置的静态目录，远端配置只是覆盖层）；远端可达 → 以兜底表为主集、远端逐字段优先，
    并追加「被 agent 引用/被试用横幅下发但不在兜底表」的模型（`buddy-adapter.ts:937-946`）。

    ⚠️ 未实现（登记在 M6-2 报告，非静默）：DSH 的 `fetchModels` 还有**第一优先**的
    企业模型端点 `/console/enterprises/personal/models`（`buddy-oauth.ts:366-395,479-499`）；
    任务书指定本波次只做 `/v3/config`。
    """
    del meta  # 形参按 §22.3 保留（同 refresh 的说明）
    if not p.access_token_of(cred):
        return p.merge_models(p.RemoteCatalog(), profile.fallback_models)
    try:
        async with _profile_client(profile, p.REQUEST_TIMEOUT_S) as client:
            status, body = await _request(client, "GET", p.CONFIG_PATH,
                                          headers=p.config_headers(profile, cred))
    except httpx.HTTPError as e:
        logger.warning("[%s] 模型目录远端不可用（回退兜底表）：%s", profile.id, e)
        return p.merge_models(p.RemoteCatalog(), profile.fallback_models)
    if status != 200:
        logger.warning("[%s] 模型目录 HTTP %s（回退兜底表）", profile.id, status)
        return p.merge_models(p.RemoteCatalog(), profile.fallback_models)
    remote = p.parse_models_from_config(body)
    if not remote.models:
        logger.warning("[%s] /v3/config 未解析出模型（回退兜底表）", profile.id)
    return p.merge_models(remote, profile.fallback_models)


# ── 登录回调（非 local_callback 型，§22.3）────────────────────────────

async def login_callback(profile: p.ProductProfile, session, params: dict) -> LoginOutcome:
    """本产品族**不是** local_callback 型登录（external_link 轮询，`jet-hub-rpc.ts:835-877`）。

    入口层对非 local_callback 产品不暴露「回跳粘贴」（`ProductMeta.login`）；本钩子在此
    **显式拒绝**，不静默返回伪造的登录成功 —— 该产品族不存在本机回跳通道，没有"待实现"一说。
    """
    raise NotImplementedError(
        f"{profile.id}.login_callback：本产品为 external_link 轮询型（无本机回跳通道，"
        "`jet-hub-rpc.ts:835-877`），不支持回跳粘贴")
