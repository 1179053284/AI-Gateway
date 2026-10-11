"""`upstream/workbuddy` 产品钩子单测（tech-design v2.0 §22.3/§22.4；M6-2 波次 A1）。

本产品与 buddy **同族共享实现**（`buddy/hooks.py` + `buddy/protocol.py`）：
本文件只判**参数化是否正确**（域名 / 平台 / X-Product-Code / UA / 登录 URL 附加参数 /
兜底表），以及「无签到端点」这条能力差异 —— 共享逻辑的行为判据在 `test_buddy.py`。

HTTP 全部用 `httpx.MockTransport` 注入（monkeypatch `accounts/net.py::make_client`）
→ **无网络、无真实凭据**。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import httpx

from model_gateway.accounts import net
from model_gateway.accounts.login import LoginEngine
from model_gateway.accounts.store import has_account, load_credentials
from model_gateway.upstream.workbuddy import product as workbuddy

ACCESS = "header.payload.sig"          # 非 JWT 也可（解析失败一律回退空，不抛）
REFRESH = "WB-REFRESH-TOKEN"
AUTH_URL = "https://www.workbuddy.ai/login/?platform=cli&state=ST-9"

LOGIN_ROUTES: dict = {
    "/v2/plugin/auth/state": (200, {"code": 0, "data": {"state": "ST-9", "authUrl": AUTH_URL}}),
    "/v2/plugin/auth/token": (200, {"code": 0, "data": {
        "accessToken": ACCESS, "refreshToken": REFRESH, "expiresAt": "1800000000000",
        "tokenType": "Bearer", "domain": "www.workbuddy.ai"}}),
    "/v2/plugin/login/account": (200, {"code": 0, "data": {
        "uid": "wb-1", "nickname": "WB 用户", "enterpriseId": "", "type": "personal"}}),
}

_CRED = {"access_token": ACCESS, "refresh_token": REFRESH, "user_id": "wb-1"}


def _install_http(monkeypatch, routes: dict) -> list[httpx.Request]:
    """把 `net.make_client` 换成 MockTransport 客户端（记录请求；无网络）。"""
    seen: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        route = routes.get(request.url.path)
        if route is None:
            return httpx.Response(404, json={"code": 404, "message": f"unrouted {request.url.path}"})
        if callable(route):
            return route(request)
        status, body = route
        return httpx.Response(status, json=body, request=request)

    def factory(**kwargs):
        kwargs.pop("follow_redirects", None)
        kwargs["timeout"] = httpx.Timeout(5.0)
        return httpx.AsyncClient(transport=httpx.MockTransport(responder), **kwargs)

    monkeypatch.setattr(net, "make_client", factory)
    return seen


# ============ 注册表回填（M6-2 取证）============

def test_registry_base_url_backfilled_from_dsh_source():
    """`base_url` 回填值 = DSH `product.ts:384` 的 `endpoint`（同 `apiDomain`，`:385`）。"""
    meta = workbuddy.meta()
    assert meta.base_url == "https://www.workbuddy.ai"
    assert workbuddy._PROFILE.api_domain == "www.workbuddy.ai"   # X-Domain 由基址派生
    assert meta.capabilities.checkin is False                    # credits-capabilities.js:65
    assert meta.capabilities.balance is True and meta.capabilities.refresh is True


# ============ 登录（同族共享实现 + 本产品参数）============

async def test_login_url_is_decorated_with_session_params(tmp_path, monkeypatch):
    """国际版登录 URL 追加 `version` + `loginSessionId`（`product.ts:137-141`）。"""
    seen = _install_http(monkeypatch, LOGIN_ROUTES)
    engine = LoginEngine(root=tmp_path / "accounts")
    session = await engine.start(workbuddy.PRODUCT)

    url = session.challenge.url
    assert url.startswith(AUTH_URL) and "version=5.5.2" in url and "loginSessionId=" in url
    # 🔴 platform 是 `cli`（不是客户端的 `workbuddy-ai`）：登录页对**非 cli** 平台在
    #    登录成功后会深链交还控制权（`workbuddy-ai://` → 本机 WorkBuddy AI App），
    #    网关是无 GUI 的本机服务，不该冒充桌面客户端。取证与反转条件见
    #    `upstream/workbuddy/product.py::_PROFILE` 上方注释。
    assert seen[0].url.params["platform"] == "cli"
    assert seen[0].headers["User-Agent"].startswith("WorkBuddy/5.5.2 WorkBuddy AI")


async def test_login_session_id_is_fresh_per_start(tmp_path, monkeypatch):
    """`loginSessionId` 每次登录新生（服务端无校验语义，`buddy-oauth.ts:517-519`）。"""
    _install_http(monkeypatch, LOGIN_ROUTES)
    engine = LoginEngine(root=tmp_path / "accounts")
    first = await engine.start(workbuddy.PRODUCT)
    second = await engine.start(workbuddy.PRODUCT)
    assert first.challenge.url != second.challenge.url


async def test_login_flow_end_to_end_commits_international_credential(tmp_path, monkeypatch):
    """登录全流程（共享实现 + 本产品基址）→ 凭据落盘，默认账号名前缀为 workbuddy-。"""
    _install_http(monkeypatch, LOGIN_ROUTES)
    root = tmp_path / "accounts"
    engine = LoginEngine(root=root)
    session = await engine.start(workbuddy.PRODUCT)
    assert session.name.startswith("workbuddy-")

    outcome = await engine.poll(workbuddy.PRODUCT, session.id)
    assert outcome.state == "success", outcome.detail
    assert not has_account(root, session.name), "success 只暂存（M7-E 两阶段提交）"
    assert (await engine.commit_pending(session.id))["committed"] is True
    saved = load_credentials(workbuddy.PRODUCT, session.name, root=root)
    assert saved["access_token"] == ACCESS and saved["refresh_token"] == REFRESH
    assert saved["expires_at"] == "1800000000000"      # 绝对毫秒串原样保留（已被网关重新写入）
    meta = json.loads((root / session.name / "meta.json").read_text(encoding="utf-8"))
    assert meta["uid"] == "wb-1" and meta["nickname"] == "WB 用户"


# ============ 产品身份标识（差异全部走参数）============

async def test_identity_headers_use_international_domain(monkeypatch):
    """额度/余额请求必须带国际版域名与产品码（`credits.ts:230-247`、`product.ts:387`）。"""
    seen = _install_http(monkeypatch, {"/v2/billing/meter/get-user-resource": (200, {
        "code": 0, "data": {"Response": {"Data": {"Accounts": [
            {"PackageName": "Bonus Pack", "Status": 0, "CycleCapacityRemain": 9.5}]}}}})})
    snapshot = await workbuddy.quota(_CRED, workbuddy.meta())
    assert snapshot.state == "available" and snapshot.source == "workbuddy-billing"
    request = seen[0]
    assert request.headers["X-Domain"] == "www.workbuddy.ai"
    assert request.headers["X-Product-Code"] == "workbuddy"
    assert request.headers["X-Product"] == "SaaS"                 # 部署类型，两产品共用
    assert request.headers["User-Agent"].startswith("WorkBuddy/")


async def test_refresh_uses_international_identity(monkeypatch):
    """续期同理**必须按产品覆盖** UA/域名（`buddy-oauth.ts:301-304` 的实测复盘）。"""
    seen = _install_http(monkeypatch, {"/v2/plugin/auth/token/refresh": (200, {"code": 0, "data": {
        "accessToken": "new-access", "refreshToken": "new-refresh", "expiresIn": 60}})})
    merged = await workbuddy.refresh(dict(_CRED), workbuddy.meta())
    assert merged["access_token"] == "new-access" and merged["refresh_token"] == "new-refresh"
    assert seen[0].headers["X-Domain"] == "www.workbuddy.ai"
    assert seen[0].headers["User-Agent"].startswith("WorkBuddy/5.5.2 WorkBuddy AI")


# ============ 能力差异：无签到端点 ============

async def test_claim_is_inactive_and_never_hits_upstream(monkeypatch):
    """🔴 国际版**无签到端点** → `inactive` + 可读原因，且**不发请求**
    （能力位是判据：`credits-capabilities.js:65`、`product.ts:378-380`）。"""
    seen = _install_http(monkeypatch, {})
    outcome = await workbuddy.claim(_CRED, workbuddy.meta(), precheck=True)
    assert outcome.category == "inactive" and "checkin=False" in outcome.detail
    assert seen == []


# ============ 兜底表（国际版各自一份，不得与 buddy 混用）============

def test_fallback_table_is_the_international_one():
    """23 条（`product.ts:295-367`），含国际版独有的 GPT/Gemini 系与 5 个抽象别名。"""
    models = workbuddy._PROFILE.fallback_models
    ids = [m.id for m in models]
    assert len(ids) == 23
    assert ids[:5] == ["default-model", "fast-model", "balanced-model",
                       "primary-model", "deep-model"]         # 顺序即 IDE 展示顺序
    assert "gpt-6-astra" in ids and "gemini-3.5-flash" in ids
    assert "hy3-x" not in ids                                  # 中国版独有 → 不得混入
    # gpt-5.3-codex 远端未下发 maxOutputTokens → 保持未填（不臆造数值，`product.ts:348-350`）
    codex = next(m for m in models if m.id == "gpt-5.3-codex")
    assert codex.max_output is None and codex.image_input is True


async def test_list_models_merges_remote_extras_on_international_table(monkeypatch):
    """远端可追加不在兜底表但被引用的模型（其余共享逻辑与 buddy 同源）。"""
    _install_http(monkeypatch, {"/v3/config": (200, {"code": 0, "data": {
        "agents": [{"name": "craft", "models": ["primary-model", "claude-sonnet-9"]}],
        "models": [{"id": "primary-model", "name": "Primary(远端)", "maxInputTokens": 111_000},
                   {"id": "claude-sonnet-9", "name": "Claude Sonnet 9"}]}})})
    models = await workbuddy.list_models(_CRED, workbuddy.meta())
    by_id = {m.id: m for m in models}
    assert len(models) == 23 + 1
    assert models[-1].id == "claude-sonnet-9"
    assert by_id["primary-model"].name == "Primary(远端)"
    assert by_id["primary-model"].context_window == 111_000       # 远端优先
    assert by_id["primary-model"].max_output == 72_000            # 兜底补位


async def test_list_models_without_credential_uses_international_table(monkeypatch):
    """无凭据 → 兜底表（国际版），零请求。"""
    seen = _install_http(monkeypatch, {})
    models = await workbuddy.list_models({}, workbuddy.meta())
    assert len(models) == 23 and seen == []
    assert models[0].id == "default-model"


def test_workbuddy_module_has_no_duplicated_network_layer():
    """🔴 反复制护栏（本波次硬约束「两产品共享逻辑只写一份」）：

    `workbuddy/product.py` **不得**出现自己的 HTTP 客户端或端点常量 —— 网络与协议全在
    `buddy/hooks.py` + `buddy/protocol.py`；本文件只允许声明参数与兜底表。
    判据走 **AST 代码面**（docstring/注释里引用端点名不算复制实现）。
    """
    tree = ast.parse(Path(workbuddy.__file__).read_text(encoding="utf-8"))
    docstrings = {node.body[0].value for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                       ast.AsyncFunctionDef))
                  and node.body and isinstance(node.body[0], ast.Expr)
                  and isinstance(node.body[0].value, ast.Constant)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] != "httpx" for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "httpx"
        if isinstance(node, ast.Attribute):
            assert node.attr != "make_client", "workbuddy 复制了客户端工厂调用"
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and node not in docstrings:
            for endpoint in ("/v2/plugin", "/v2/billing", "/v3/config"):
                assert endpoint not in node.value, f"workbuddy 复制了端点常量：{endpoint}"
