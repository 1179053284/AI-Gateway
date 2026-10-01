"""产品出站适配（§22.3 duck typing；M6-5a）：凭据自解 / 身份头 / 传输复用 / 分派与复用判据。

判据逐条对应 §22.3 与 §22.5-3：

· 形状 = 与 `openai_out.py` **同形**的 duck typing（属性 + 三个方法）；
· 凭据**只在本地账号目录**（铁律 1）：调度侧传进来的 `key` 对产品资源恒为空串，
  适配器从 `account_ref` 自解；配置里的 Key 值**不得**被使用；
· 缺凭据 → fail closed（**不发请求**，`UpstreamError` 可读）；
· `product` 分支优先于 `protocol`；复用判据含 `product + account_ref + 凭据指纹`
  —— **改绑账号 / 重新登录必须换适配器**（S-14 同族缺陷的红证）。

HTTP 全部走 `httpx.MockTransport`（无网络）；账号读取打桩在
`accounts.store.load_credentials` / `hook_meta`（适配器唯一读入口）。
"""

from __future__ import annotations

import asyncio
import json
import pathlib

import httpx
import pytest

from model_gateway.accounts import store
from model_gateway.adapters import build_adapter
from model_gateway.adapters.openai_out import OpenAIOutAdapter
from model_gateway.adapters.product_out import (
    FamilyOpenAIOut,
    ProductAccount,
    ProductOutAdapter,
    build_product_adapter,
)
from model_gateway.core.errors import UpstreamError
from model_gateway.upstream.buddy import product as buddy
from model_gateway.upstream.buddy.out import BuddyFamilyOut

BASE = "http://127.0.0.1:9"   # 与注册表同形：buddy 基址**不含**路径前缀（chat_path 自带 /v2）
CRED = {"access_token": "TOKEN-FROM-ACCOUNT", "user_id": "u-1",
        "enterprise_id": "ent-9", "token_type": "Bearer"}


def _install_store(monkeypatch, cred: dict | None = None, meta: dict | None = None):
    """把适配器的**唯一凭据读入口**换成固定值（返回记录以便断言"没被读"）。"""
    reads = {"cred": 0, "meta": 0}

    def _cred(product, name, *, root=None):
        reads["cred"] += 1
        return dict(cred if cred is not None else CRED)

    def _meta(product, name, root=None):
        reads["meta"] += 1
        return {"account": name, "dir": "/tmp/fake", **(meta or {})}

    monkeypatch.setattr(store, "load_credentials", _cred)
    monkeypatch.setattr(store, "hook_meta", _meta)
    return reads


def _adapter(monkeypatch, *, cred=None, meta=None, transport=None, product="buddy",
             name="acc-1", base_url=BASE, needs_base64=None, factory=buddy.build_out):
    _install_store(monkeypatch, cred, meta)
    account = ProductAccount(product=product, name=name, base_url=base_url,
                             needs_base64=needs_base64)
    adapter = factory(account)
    if transport is not None:
        adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    return adapter


def _capture(monkeypatch, *, response: dict | None = None, sse: str | None = None,
             status: int = 200, body: str = ""):
    """MockTransport 记录器：返回 (seen, handler)。"""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if sse is not None:
            return httpx.Response(200, text=sse, request=request,
                                  headers={"content-type": "text/event-stream"})
        if status != 200:
            return httpx.Response(status, text=body, request=request)
        return httpx.Response(200, json=response or _ok_json(), request=request)

    return seen, handler


def _ok_json(content: str = "hi") -> dict:
    return {"id": "cmpl-1", "object": "chat.completion", "model": "hy3",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2}}


def _sse() -> str:
    frames = [
        {"id": "c", "object": "chat.completion.chunk", "model": "hy3",
         "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"id": "c", "object": "chat.completion.chunk", "model": "hy3",
         "choices": [{"index": 0, "delta": {"content": "你"}, "finish_reason": None}]},
        {"id": "c", "object": "chat.completion.chunk", "model": "hy3",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    out = "".join(f"data: {json.dumps(f, ensure_ascii=False)}\n\n" for f in frames)
    return out + "data: [DONE]\n\n"


# ============ 形状（§22.3 duck typing）============

def test_adapter_shape_matches_the_duck_typing_contract(monkeypatch):
    adapter = _adapter(monkeypatch)
    assert isinstance(adapter, ProductOutAdapter)
    assert isinstance(adapter, OpenAIOutAdapter)
    assert (adapter.product, adapter.account_ref) == ("buddy", "acc-1")
    assert adapter.base_url == BASE and adapter.protocol == "openai"
    assert adapter.chat_path == "/v2/chat/completions"
    for method in ("chat_nonstream", "chat_stream", "aclose"):
        assert callable(getattr(adapter, method))
    asyncio.run(adapter.aclose())


def test_base_contract_methods_fail_loudly(monkeypatch):
    """直接继承契约类而不实现 → 首次调用即显式失败（不静默半实现，§22.3）。"""
    adapter = ProductOutAdapter(ProductAccount(product="p", name="n", base_url=BASE))
    with pytest.raises(NotImplementedError):
        asyncio.run(adapter.chat_nonstream("", "m", {}, 5.0))
    with pytest.raises(NotImplementedError):
        asyncio.run(adapter.chat_stream("", "m", {}, 5.0).__anext__())   # async generator 形态
    with pytest.raises(NotImplementedError):
        asyncio.run(adapter.aclose())


# ============ 凭据自解 + 身份头 ============

def test_chat_nonstream_resolves_credential_from_account_and_sends_family_headers(monkeypatch):
    seen, handler = _capture(monkeypatch)
    adapter = _adapter(monkeypatch, transport=handler, base_url="http://127.0.0.1:9")
    body = {"messages": [{"role": "user", "content": "hi"}]}
    data = asyncio.run(adapter.chat_nonstream("", "hy3", body, 10.0))
    asyncio.run(adapter.aclose())

    assert data["choices"][0]["message"]["content"] == "hi"
    request = seen[0]
    assert request.url.path == "/v2/chat/completions"          # 取证路径（不是 /chat/completions）
    assert request.headers["authorization"] == "Bearer TOKEN-FROM-ACCOUNT"
    assert request.headers["x-domain"] == "127.0.0.1"          # 与实际请求基址一致（credits.ts:222-228）
    # ⚠️ 本行与并行会话的 buddy 推理面取证同步（`upstream/buddy/out.py` 的 F3 修正：
    #    推理面 `X-Product` 发**归属名**，`SaaS` 是计费面 `credits.ts:236` 的值，
    #    套到推理面正是 DSH 记录在案的「后台归因不到产品」历史 bug；集成测试
    #    `test_buddy_out.py` 已同步）。Fix-γ 只同步这一条断言，未改其它用例。
    assert request.headers["x-product"] == "CodeBuddy"         # buddy-adapter.ts:1577 + product.ts:278
    assert request.headers["x-product-code"] == "codebuddy"    # product.ts:274
    assert request.headers["user-agent"] == "CodeBuddyIDE/1.106.1"
    # ⚠️ 同上（并行会话 F3 修正）：`X-User-Id` / `X-Enterprise-Id` 属**计费面**
    #    （`credits.ts:238-244`），推理面 `send()`（`:1564-1581`）**不发** —— 混面正是
    #    F3 的形态；凭据里的这两个字段仍在（本用例的 CRED），只是不外发。
    assert "x-user-id" not in request.headers and "x-enterprise-id" not in request.headers
    assert request.headers["x-ide-name"] == "CodeBuddy"        # :1574 + product.ts:278
    assert request.headers["x-ide-type"] == "CodeBuddy"        # :1575
    assert request.headers["x-ide-version"] == "1.106.1"       # :1576 + product.ts:279
    assert request.headers["x-agent-purpose"] == "conversation"  # :1573
    assert json.loads(request.content)["model"] == "hy3"


def test_config_key_is_never_used_for_product_resources(monkeypatch):
    """🔴 铁律 1 的判据：调度侧传进来的配置 Key **不参与鉴权**（凭据只在账号目录）。"""
    seen, handler = _capture(monkeypatch)
    adapter = _adapter(monkeypatch, transport=handler)
    asyncio.run(adapter.chat_nonstream("sk-config-key-must-not-leak", "hy3", {}, 10.0))
    asyncio.run(adapter.aclose())
    assert "sk-config-key-must-not-leak" not in seen[0].headers.get("authorization", "")


def test_missing_credentials_fail_closed_without_upstream_call(monkeypatch):
    """凭据缺失 → `UpstreamError` 且**不发请求**（§22.8-5 fail closed）。"""
    seen, handler = _capture(monkeypatch)
    adapter = _adapter(monkeypatch, cred={}, transport=handler)
    with pytest.raises(UpstreamError, match="无凭据"):
        asyncio.run(adapter.chat_nonstream("", "hy3", {}, 10.0))
    asyncio.run(adapter.aclose())
    assert seen == []


def test_credential_without_access_token_is_rejected_before_request(monkeypatch):
    seen, handler = _capture(monkeypatch)
    adapter = _adapter(monkeypatch, cred={"refresh_token": "rt"}, transport=handler)
    with pytest.raises(UpstreamError, match="access_token"):
        asyncio.run(adapter.chat_nonstream("", "hy3", {}, 10.0))
    asyncio.run(adapter.aclose())
    assert seen == []


def test_prepare_body_default_only_sets_vendor_model(monkeypatch):
    """默认体塑造 = 只落厂商模型名（不塞自创字段；采样/推理注入归 IR 层）。"""
    seen, handler = _capture(monkeypatch)
    adapter = _adapter(monkeypatch, transport=handler)
    asyncio.run(adapter.chat_nonstream("", "hy3", {"messages": [], "temperature": 0.3}, 10.0))
    asyncio.run(adapter.aclose())
    body = json.loads(seen[0].content)
    assert body == {"messages": [], "temperature": 0.3, "model": "hy3"}


def test_needs_base64_probe_flows_from_the_account_payload(monkeypatch):
    """资源级能力探针经 `ProductAccount` 注入（冻结签名不允许追加形参）。"""
    probe = lambda model: model == "kimi-only-b64"  # noqa: E731
    adapter = _adapter(monkeypatch, needs_base64=probe)
    assert adapter._needs_base64("kimi-only-b64") is True
    assert adapter._needs_base64("hy3") is False
    asyncio.run(adapter.aclose())


# ============ 传输复用（SSE / 错误映射）============

def test_chat_stream_reuses_openai_sse_parsing(monkeypatch):
    seen, handler = _capture(monkeypatch, sse=_sse())
    adapter = _adapter(monkeypatch, transport=handler)

    async def run() -> list[dict]:
        return [chunk async for chunk in adapter.chat_stream("", "hy3", {"stream": True}, 10.0)]

    chunks = asyncio.run(run())
    asyncio.run(adapter.aclose())
    assert seen[0].url.path == "/v2/chat/completions"
    assert json.loads(seen[0].content)["stream"] is True
    assert [c["choices"][0]["delta"].get("content") for c in chunks if c.get("choices")] \
        == [None, "你", None]


def test_upstream_error_status_and_body_are_preserved(monkeypatch):
    seen, handler = _capture(monkeypatch, status=429,
                             body='{"error": {"type": "rate_limit_error", "message": "slow down"}}')
    adapter = _adapter(monkeypatch, transport=handler)
    with pytest.raises(UpstreamError) as e:
        asyncio.run(adapter.chat_nonstream("", "hy3", {}, 10.0))
    asyncio.run(adapter.aclose())
    assert e.value.status_code == 429
    assert "rate_limit_error" in (e.value.error_body or "")
    assert len(seen) == 1


# ============ 分派（§22.5-3：product 优先于 protocol）============

def test_build_adapter_dispatches_to_the_product_branch(monkeypatch):
    _install_store(monkeypatch, CRED)
    adapter = build_adapter("anthropic", "http://127.0.0.1:9/v1", product="buddy",
                            account_ref="acc-1")            # protocol 故意与产品无关
    assert isinstance(adapter, BuddyFamilyOut)
    assert adapter.chat_path == "/v2/chat/completions"      # 以 product 为准
    asyncio.run(adapter.aclose())


def test_build_adapter_without_product_keeps_legacy_behavior():
    adapter = build_adapter("openai", "http://127.0.0.1:9/v1")
    assert type(adapter) is OpenAIOutAdapter
    asyncio.run(adapter.aclose())


def test_build_product_adapter_rejects_empty_account_ref():
    with pytest.raises(ValueError, match="account_ref"):
        build_product_adapter("buddy", "  ", "http://127.0.0.1:9/v1")


def test_build_product_adapter_unknown_product_fails_loudly():
    with pytest.raises(KeyError, match="未登记的产品"):
        build_product_adapter("codearts", "acc", "http://127.0.0.1:9/v1")


def _unwire_product(monkeypatch, product: str) -> None:
    """把某产品的 `build_out` 打回"未接线"态（人工构造 M6-5b 之前的状态）。

    🔴 为什么不拿真产品当样本（2026-09-30 guard-fix 改造）：十款产品现已**全部接线**
    （M6-5b/M6-5c），注册表里已不存在"未接线产品" —— 原来那条"断言某个真产品未接线"
    编码的是**当时的波次状态**，产品全接线后即过期。这里沿**真实分派路径**注入：
    `build_product_adapter` → `import model_gateway.upstream.<product>.product` →
    `build_out(account)`，让"显式失败 / 按资源降级"的判据继续被真实验证；
    monkeypatch 用完自动还原，不影响其它用例。
    """
    import importlib

    module = importlib.import_module(f"model_gateway.upstream.{product}.product")

    def _not_wired(account):  # 签名同 §22.3 冻结签名 `build_out(account)`
        raise NotImplementedError(f"{product}.build_out 未接线（本用例人工构造）")

    monkeypatch.setattr(module, "build_out", _not_wired)


def test_build_product_adapter_reports_unwired_products(monkeypatch):
    """未接线产品的 `build_out` 必须**显式失败**（不得返回半成品）——错误原样冒出。"""
    _unwire_product(monkeypatch, "cline")
    with pytest.raises(NotImplementedError, match="cline.build_out"):
        build_product_adapter("cline", "acc", "http://127.0.0.1:9/v1")


def test_custom_protocol_products_schema_literal_is_openai():
    """`custom` 协议族物化时 schema 落 `openai` 字面量（§22.5-3），分派仍以 product 为准。"""
    from model_gateway.accounts import registry as reg
    meta = reg.get("qoder")
    assert meta.protocol == "custom"
    from model_gateway.accounts.materialize import _schema_protocol
    assert _schema_protocol(meta.protocol) == "openai"


# ============ 复用判据（§22.5-3：改绑账号必须重建；S-14 同族红证）============

def _product_config(account_ref: str = "acc-a", *, base_url: str = BASE) -> dict:
    return {
        "resources": [{"id": "res-p1", "name": "产品资源", "vendor": "", "preset": "",
                       "account": account_ref, "product": "buddy", "account_ref": account_ref,
                       "protocol": "openai", "base_url": base_url, "api_key": "",
                       "enabled": True, "access_mode": "api"}],
        "models": [{"name": "m", "endpoint": "chat",
                    "resources": [{"resource": "res-p1", "model": "hy3"}]}],
    }


def _runtime(tmp_path: pathlib.Path):
    import yaml

    from model_gateway.config.loader import load_config
    from model_gateway.main import Runtime

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(_product_config(), allow_unicode=True), encoding="utf-8")
    return Runtime(load_config(cfg_path), cfg_path,
                   usage_dir=tmp_path / "usage", enums_path=tmp_path / "enums.yaml",
                   dialects_path=tmp_path / "dialects.yaml"), cfg_path


def test_product_resource_gets_a_family_adapter(tmp_path):
    rt, _ = _runtime(tmp_path)
    assert isinstance(rt.adapters["res-p1"], BuddyFamilyOut)
    asyncio.run(rt.aclose())


def test_unchanged_product_resource_reuses_the_adapter(tmp_path):
    rt, _ = _runtime(tmp_path)
    first = rt.adapters["res-p1"]
    ok, errors = asyncio.run(rt.reload_from_file())
    assert ok, errors
    assert rt.adapters["res-p1"] is first, "无变更却重建了适配器（每轮热重载都漏一个 client）"
    asyncio.run(rt.aclose())


def test_rebinding_the_account_rebuilds_the_adapter(tmp_path):
    """🔴 改绑账号**必须**换适配器（否则请求带着旧账号的凭据/身份头打上游 —— S-14 同族）。"""
    import yaml

    store.commit_login("buddy", "acc-a", {"access_token": "TOKEN-A"}, {})
    store.commit_login("buddy", "acc-b", {"access_token": "TOKEN-B"}, {})
    rt, cfg_path = _runtime(tmp_path)
    first = rt.adapters["res-p1"]
    assert first.account_ref == "acc-a"

    cfg_path.write_text(yaml.safe_dump(_product_config("acc-b"), allow_unicode=True),
                        encoding="utf-8")
    ok, errors = asyncio.run(rt.reload_from_file())
    assert ok, errors
    second = rt.adapters["res-p1"]
    assert second is not first, "改绑账号却复用了旧适配器（S-14 同族缺陷）"
    assert second.account_ref == "acc-b"
    assert first in rt._pending_close, "被换下的适配器没进待关清单（旧账 #48 同族）"
    asyncio.run(rt.aclose())


def test_credential_change_rebuilds_the_adapter(tmp_path):
    """重新登录（凭据文件变更）→ 连接身份变了 → 适配器重建（复用判据含凭据指纹）。"""
    store.commit_login("buddy", "acc-a", {"access_token": "TOKEN-OLD"}, {})
    rt, _ = _runtime(tmp_path)
    first = rt.adapters["res-p1"]

    store.commit_login("buddy", "acc-a", {"access_token": "TOKEN-NEW"}, {})
    ok, errors = asyncio.run(rt.reload_from_file())
    assert ok, errors
    assert rt.adapters["res-p1"] is not first, "凭据换了却复用旧适配器"
    asyncio.run(rt.aclose())


def test_unwired_product_resource_is_skipped_not_fatal(tmp_path, monkeypatch):
    """未接线产品的资源：`_apply` **跳过它**，其余资源与热重载照常（不打死热重载）。

    场景为**人工构造**（十款产品已全部接线，见 `_unwire_product`）：把 cline 的
    `build_out` 打回未接线态后装进配置 —— 判据不变：只有该资源降级，别的照常。
    """
    import yaml

    from model_gateway.config.loader import load_config
    from model_gateway.main import Runtime

    _unwire_product(monkeypatch, "cline")
    cfg = _product_config()
    cfg["resources"].append({"id": "res-c", "name": "Cline 资源（未接线，人工构造）",
                             "account": "c-1", "product": "cline", "account_ref": "c-1",
                             "protocol": "openai", "base_url": BASE, "api_key": "",
                             "enabled": True, "access_mode": "api"})
    cfg["models"][0]["resources"].append({"resource": "res-c", "model": "c-model"})
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    rt = Runtime(load_config(cfg_path), cfg_path, usage_dir=tmp_path / "usage",
                 enums_path=tmp_path / "enums.yaml", dialects_path=tmp_path / "dialects.yaml")
    assert isinstance(rt.adapters["res-p1"], BuddyFamilyOut)   # 接线产品照常
    assert "res-c" not in rt.adapters                          # 未接线 → 按资源降级
    ok, errors = asyncio.run(rt.reload_from_file())            # 热重载不得被打死
    assert ok, errors
    asyncio.run(rt.aclose())


# ============ B-2（M6-6 Fix-γ）：终态资源必须能被"重新登录 / 改绑账号"复活 ============

def _terminal_state(rt):
    return rt.resources.registry[("res-p1", "hy3")]


def _make_it_dead(rt):
    """复刻 401 判死（终态）——出站 401 → `ResourceManager.disable`（scheduler 的落点）。"""
    st = _terminal_state(rt)
    rt.resources.disable(st, "upstream 401：凭据被上游拒绝")
    assert st.status == "disabled"
    assert rt.resources.pick_and_acquire("m", set()) is None, "判死后不得再进生效集"
    return st


def test_relogin_revives_a_dead_product_resource(tmp_path):
    """🔴 B-2：重新登录同一账号（凭据变化）= 新的连接身份 → 401 判死的资源回 active。

    产品资源的"Key"在**账号目录**里（配置里恒为空串），所以连接身份指纹必须含
    `product + account_ref + 凭据指纹` —— 否则用户按提示"重新登录"也永远 503
    （评审报告 B-2 的红证：reload=True、适配器重建，但 status 停在 disabled）。

    红证（撤修复）：`_conn_fingerprint` 不算凭据分量时，本用例的 status 停在 disabled。
    """
    store.commit_login("buddy", "acc-a", {"access_token": "TOKEN-OLD"}, {})
    rt, _ = _runtime(tmp_path)
    st = _make_it_dead(rt)

    store.commit_login("buddy", "acc-a", {"access_token": "TOKEN-NEW"}, {})
    ok, errors = asyncio.run(rt.reload_from_file())
    assert ok, errors
    assert st.status == "active", "重新登录后仍是 disabled —— 用户按提示操作却永远 503"
    assert st.C == 0 and st.cooldown_until == 0.0 and st.last_error is None
    assert rt.resources.pick_and_acquire("m", set()) is st, "复活后必须回到生效集"
    asyncio.run(rt.aclose())


def test_rebinding_the_account_also_revives_a_dead_product_resource(tmp_path):
    """🔴 B-2 的另一半：改绑到另一个账号同样是"新的连接身份" → 终态清零。

    红证（撤修复）：同上 —— 指纹不含 `account_ref` 时，改绑后仍 disabled。
    """
    import yaml

    store.commit_login("buddy", "acc-a", {"access_token": "TOKEN-A"}, {})
    store.commit_login("buddy", "acc-b", {"access_token": "TOKEN-B"}, {})
    rt, cfg_path = _runtime(tmp_path)
    st = _make_it_dead(rt)

    cfg_path.write_text(yaml.safe_dump(_product_config("acc-b"), allow_unicode=True),
                        encoding="utf-8")
    ok, errors = asyncio.run(rt.reload_from_file())
    assert ok, errors
    assert st.status == "active", "改绑账号后仍 disabled（改绑 = 换连接身份）"
    asyncio.run(rt.aclose())


def test_same_credentials_do_not_reset_the_terminal_state(tmp_path):
    """反向护栏：凭据**没变**的热重载不得把 401 判死清零（否则"判死"名存实亡）。"""
    store.commit_login("buddy", "acc-a", {"access_token": "TOKEN-SAME"}, {})
    rt, _ = _runtime(tmp_path)
    st = _make_it_dead(rt)

    ok, errors = asyncio.run(rt.reload_from_file())
    assert ok, errors
    assert st.status == "disabled", "连接身份没变却清掉了 401 判死 —— 反向红"
    asyncio.run(rt.aclose())
