"""`upstream/workbuddycn` 产品钩子单测（tech-design v2.11 §22.3/§22.4；Q44 波次）。

本产品与 buddy / workbuddy **同族共享实现**（`buddy/hooks.py` + `buddy/protocol.py`）：
本文件只判**参数化是否正确**（域名 / 登录 platform / X-Product-Code / UA_CN / 登录 URL
附加参数 / 兜底表），以及「有签到端点」这条能力差异（**与国际版相反**）—— 共享逻辑的
行为判据在 `test_buddy.py`。

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
from model_gateway.upstream.buddy import protocol as p
from model_gateway.upstream.workbuddycn import product as workbuddycn

ACCESS = "header.payload.sig"          # 非 JWT 也可（解析失败一律回退空，不抛）
REFRESH = "WBCN-REFRESH-TOKEN"
AUTH_URL = "https://www.workbuddy.cn/login/?platform=cli&state=ST-9"

LOGIN_ROUTES: dict = {
    "/v2/plugin/auth/state": (200, {"code": 0, "data": {"state": "ST-9", "authUrl": AUTH_URL}}),
    "/v2/plugin/auth/token": (200, {"code": 0, "data": {
        "accessToken": ACCESS, "refreshToken": REFRESH, "expiresAt": "1800000000000",
        "tokenType": "Bearer", "domain": "www.workbuddy.cn"}}),
    "/v2/plugin/login/account": (200, {"code": 0, "data": {
        "uid": "wbcn-1", "nickname": "WBCN 用户", "enterpriseId": "", "type": "personal"}}),
}

_CRED = {"access_token": ACCESS, "refresh_token": REFRESH, "user_id": "wbcn-1"}


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


# ============ 注册表回填（Q44 取证）============

def test_registry_base_url_backfilled_from_cn_app():
    """`base_url` = 中国版 `cli/product.json` 的 `endpoint`（2026-10-11 本机实读）。"""
    meta = workbuddycn.meta()
    assert meta.base_url == "https://www.workbuddy.cn"
    assert workbuddycn._PROFILE.api_domain == "www.workbuddy.cn"   # X-Domain 由基址派生
    assert meta.capabilities.checkin is True                     # 中国版有签到端点（与国际版相反）
    assert meta.capabilities.balance is True and meta.capabilities.refresh is True
    assert meta.capabilities.permanent_lock is True               # 同族 buddy/workbuddy 同判


# ============ 登录（同族共享实现 + 本产品参数）============

async def test_login_url_is_decorated_with_session_params(tmp_path, monkeypatch):
    """登录 URL 追加 `version` + `loginSessionId`；auth/state 查询串 **platform=cli**。

    🔴 platform 是 `cli`（不是客户端声明的 `workbuddy`）：`workbuddy` 恰是登录页深链
    `workbuddy://` 的键、本机 WorkBuddy.app 已注册该协议（Info.plist 实读）——照抄会
    复刻国际版 `workbuddy-ai://` 的用户报障。取证与反转条件见
    `upstream/workbuddycn/product.py::_PROFILE` 上方注释（同
    `upstream/workbuddy/product.py` 2026-10-10 修复口径）。
    """
    seen = _install_http(monkeypatch, LOGIN_ROUTES)
    engine = LoginEngine(root=tmp_path / "accounts")
    session = await engine.start(workbuddycn.PRODUCT)

    url = session.challenge.url
    assert url.startswith(AUTH_URL) and "version=5.5.2" in url and "loginSessionId=" in url
    assert seen[0].url.params["platform"] == "cli"
    # UA = 中国版形态（中段是第二个 `WorkBuddy/`，不是国际版的 `WorkBuddy AI/`）
    assert seen[0].headers["User-Agent"] == "WorkBuddy/5.5.2 WorkBuddy/5.5.2 CLI/5.5.2"


async def test_login_flow_end_to_end_commits_cn_credential(tmp_path, monkeypatch):
    """登录全流程（共享实现 + 本产品基址）→ 凭据落盘，默认账号名前缀为 workbuddycn-。"""
    _install_http(monkeypatch, LOGIN_ROUTES)
    root = tmp_path / "accounts"
    engine = LoginEngine(root=root)
    session = await engine.start(workbuddycn.PRODUCT)
    assert session.name.startswith("workbuddycn-")

    outcome = await engine.poll(workbuddycn.PRODUCT, session.id)
    assert outcome.state == "success", outcome.detail
    assert not has_account(root, session.name), "success 只暂存（M7-E 两阶段提交）"
    assert (await engine.commit_pending(session.id))["committed"] is True
    saved = load_credentials(workbuddycn.PRODUCT, session.name, root=root)
    assert saved["access_token"] == ACCESS and saved["refresh_token"] == REFRESH
    meta = json.loads((root / session.name / "meta.json").read_text(encoding="utf-8"))
    assert meta["uid"] == "wbcn-1" and meta["nickname"] == "WBCN 用户"


# ============ 产品身份标识（差异全部走参数）============

async def test_identity_headers_use_cn_domain(monkeypatch):
    """额度/余额请求必须带中国版域名与产品码（计费面 `X-Product` = 部署类型 SaaS）。"""
    seen = _install_http(monkeypatch, {"/v2/billing/meter/get-user-resource": (200, {
        "code": 0, "data": {"Response": {"Data": {"Accounts": [
            {"PackageName": "体验版", "Status": 0, "CycleCapacityRemain": 9.5}]}}}})})
    snapshot = await workbuddycn.quota(_CRED, workbuddycn.meta())
    assert snapshot.state == "available" and snapshot.source == "workbuddycn-billing"
    request = seen[0]
    assert request.headers["X-Domain"] == "www.workbuddy.cn"
    assert request.headers["X-Product-Code"] == "workbuddy"
    assert request.headers["X-Product"] == "SaaS"                 # 部署类型，计费面共用
    assert request.headers["User-Agent"] == "WorkBuddy/5.5.2 WorkBuddy/5.5.2 CLI/5.5.2"


def test_inference_attribution_headers_are_the_cn_family_values():
    """🔴 推理面归属头 = `WorkBuddy` / `5.5.2`（`_ATTRIBUTION_BY_PRODUCT` 的 workbuddycn 行）。

    撤证方向 = 删掉 `protocol.py` 归属表里的 `"workbuddycn"` 行 ⇒ 本用例当场 `ValueError`
    （该行缺失时**首次推理请求**在 `auth_headers` 构造身份头处炸，不是静默降级）。
    """
    headers = p.inference_headers(workbuddycn._PROFILE, _CRED)
    assert headers["X-Product"] == "WorkBuddy"
    assert headers["X-IDE-Name"] == "WorkBuddy" and headers["X-IDE-Type"] == "WorkBuddy"
    assert headers["X-IDE-Version"] == "5.5.2"
    assert headers["X-Agent-Purpose"] == "conversation"
    assert headers["X-Product-Code"] == "workbuddy"
    assert headers["User-Agent"] == "WorkBuddy/5.5.2 WorkBuddy/5.5.2 CLI/5.5.2"


async def test_refresh_uses_cn_identity(monkeypatch):
    """续期同理**必须按产品覆盖** UA/域名（`buddy-oauth.ts:301-304` 的实测复盘）。"""
    seen = _install_http(monkeypatch, {"/v2/plugin/auth/token/refresh": (200, {"code": 0, "data": {
        "accessToken": "new-access", "refreshToken": "new-refresh", "expiresIn": 60}})})
    merged = await workbuddycn.refresh(dict(_CRED), workbuddycn.meta())
    assert merged["access_token"] == "new-access" and merged["refresh_token"] == "new-refresh"
    assert seen[0].headers["X-Domain"] == "www.workbuddy.cn"
    assert seen[0].headers["User-Agent"] == "WorkBuddy/5.5.2 WorkBuddy/5.5.2 CLI/5.5.2"


# ============ 能力差异：有签到端点（与国际版相反）============

async def test_claim_checks_in_for_real(monkeypatch):
    """checkin=True ⇒ `claim` 走真实签到腿：precheck 状态 → `daily-checkin` code 0 = success。"""
    seen = _install_http(monkeypatch, {
        "/v2/billing/meter/checkin-activity-status": (200, {"code": 0, "data": {
            "active": True, "today_checked_in": False, "streak_days": 11, "daily_credit": 100}}),
        "/v2/billing/meter/daily-checkin": (200, {"code": 0, "data": {"credit": 100}}),
    })
    outcome = await workbuddycn.claim(_CRED, workbuddycn.meta(), precheck=True)
    assert outcome.category == "success", outcome.detail
    paths = [r.url.path for r in seen]
    assert paths == ["/v2/billing/meter/checkin-activity-status",
                     "/v2/billing/meter/daily-checkin"]


async def test_claim_repeat_is_already_done_not_failure(monkeypatch):
    """幂等：重复领取回 HTTP 400 + 业务码 10001 ⇒ `already_done`（不是失败）。"""
    seen = _install_http(monkeypatch, {
        "/v2/billing/meter/checkin-activity-status": (200, {"code": 0, "data": {
            "active": True, "today_checked_in": False}}),
        "/v2/billing/meter/daily-checkin": (400, {"code": 10001, "message": "今日已签到"}),
    })
    outcome = await workbuddycn.claim(_CRED, workbuddycn.meta(), precheck=True)
    assert outcome.category == "already_done", outcome.detail
    assert seen[-1].url.path == "/v2/billing/meter/daily-checkin"


async def test_claim_precheck_reports_already_checked_in_without_claiming(monkeypatch):
    """precheck 阶段发现 `today_checked_in=true` ⇒ `already_done` 且**不发**领取请求。"""
    seen = _install_http(monkeypatch, {
        "/v2/billing/meter/checkin-activity-status": (200, {"code": 0, "data": {
            "active": True, "today_checked_in": True}}),
    })
    outcome = await workbuddycn.claim(_CRED, workbuddycn.meta(), precheck=True)
    assert outcome.category == "already_done" and seen[-1].url.path.endswith(
        "checkin-activity-status")


# ============ 兜底表（中国版各自一份，不得与 buddy / 国际版混用）============

def test_fallback_table_is_the_cn_one():
    """16 条（cli 白名单 17 条剔除 `auto` 别名），顺序即 IDE 展示顺序，数值 = 2026-10-11 实测。"""
    models = workbuddycn._PROFILE.fallback_models
    ids = [m.id for m in models]
    assert len(ids) == 16
    assert "auto" not in ids                                   # 服务端别名，D2 拍板不收录
    assert ids[0] == "hy4-preview" and ids[2] == "hy3-x"        # 顺序 = cli 白名单序（剔除 auto）
    # 中国版池没有国际版独有的 GPT/Gemini 系与抽象别名
    assert not any(i.startswith(("gpt-", "gemini-", "claude-")) for i in ids)
    assert "default-model" not in ids and "hy4-preview-f" not in ids
    # 也没有 buddy 独有的 deepseek-v4-flash（CN 白名单相对 buddy 少这一条）
    assert "deepseek-v4-flash" not in ids
    # 🔴 数值 = 2026-10-11 实测（方案 §4.5；10-10 首测的 300000 一族是错值/漂移值）
    by_id = {m.id: m for m in models}
    assert by_id["hy4-preview"].context_window == 960_000
    assert by_id["glm-5.3"].context_window == 1_000_000
    assert by_id["glm-5.3-flash"].max_output == 131_072
    assert by_id["minimax-m3"].context_window == 512_000
    assert by_id["kimi-k3-1"].name == "Kimi-K3"                # 远端 name 字面（id 仍 kimi-k3-1）
    assert by_id["kimi-k2.7"].name == "Kimi-K2.7-Code"
    # 兜底表不含计费字段（由远端 /v3/config 覆盖，merge_models 口径）
    assert all(m.free is None and m.rate == "" for m in models)


async def test_list_models_merges_remote_extras_on_cn_table(monkeypatch):
    """远端可追加不在兜底表但被引用的模型（其余共享逻辑与 buddy 同源）。"""
    _install_http(monkeypatch, {"/v3/config": (200, {"code": 0, "data": {
        "agents": [{"name": "cli", "models": ["hy4-preview", "cn-fresh-model"]}],
        "models": [{"id": "hy4-preview", "name": "Hy4 preview(远端)", "maxInputTokens": 970_000},
                   {"id": "cn-fresh-model", "name": "CN Fresh"}]}})})
    models = await workbuddycn.list_models(_CRED, workbuddycn.meta())
    by_id = {m.id: m for m in models}
    assert len(models) == 16 + 1
    assert models[-1].id == "cn-fresh-model"
    assert by_id["hy4-preview"].name == "Hy4 preview(远端)"
    assert by_id["hy4-preview"].context_window == 970_000       # 远端优先
    assert by_id["hy4-preview"].max_output == 64_000            # 兜底补位


async def test_list_models_without_credential_uses_cn_table(monkeypatch):
    """无凭据 → 兜底表（中国版），零请求。"""
    seen = _install_http(monkeypatch, {})
    models = await workbuddycn.list_models({}, workbuddycn.meta())
    assert len(models) == 16 and seen == []
    assert models[0].id == "hy4-preview"


# ============ 零复制护栏（同 test_workbuddy 的 AST 判据，产品名换本产品）============

def test_workbuddycn_module_has_no_duplicated_network_layer():
    """🔴 反复制护栏（本波次硬约束「同族共享逻辑只写一份」）：

    `workbuddycn/product.py` **不得**出现自己的 HTTP 客户端或端点常量 —— 网络与协议全在
    `buddy/hooks.py` + `buddy/protocol.py`；本文件只允许声明参数与兜底表。
    判据走 **AST 代码面**（docstring/注释里引用端点名不算复制实现）。
    """
    tree = ast.parse(Path(workbuddycn.__file__).read_text(encoding="utf-8"))
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
            assert node.attr != "make_client", "workbuddycn 复制了客户端工厂调用"
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and node not in docstrings:
            for endpoint in ("/v2/plugin", "/v2/billing", "/v3/config"):
                assert endpoint not in node.value, f"workbuddycn 复制了端点常量：{endpoint}"
