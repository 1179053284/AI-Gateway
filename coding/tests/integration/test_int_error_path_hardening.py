"""错误路径加固回归（2026-10-10）。

覆盖三项实盘缺陷（证据：`docs/changes/20261010-call-log-audit-1008-1009.md`）：

- **P0-1**：上游 SSE error 帧的 `code` 是**字符串** ⇒ `classify()` 的 `status >= 500`
  抛 `TypeError` ⇒ 端点层接不住 ⇒ 上游 400 被返回成 **HTTP 500**，
  且事件 `error_summary` 留空。实盘末帧原文 `gateway.log:194088`。
- **P1-2**：端点层只 `except GatewayError`，任何非 GatewayError 都裸奔成 500，
  客户端拿不到可读信息。
- **P1-3**：分类器自身抛异常时，`error_summary(e)` 那一行没机会执行 ⇒ 事件无原因。

判据要点：**不是 500**（被正确归类）、**事件带原因**（error_summary 非空）、
未归因异常回**带类型名**的 500（而非空体）。
"""

from __future__ import annotations

from tests.integration.conftest import chat_res, gateway_config
from tests.integration.fakevendor import Err, Ok, StreamOk

MESSAGES_URL = "/v1/messages"
CHAT_URL = "/v1/chat/completions"


def _abody(model: str = "test-model") -> dict:
    return {"model": model, "max_tokens": 64, "stream": False,
            "messages": [{"role": "user", "content": "hi"}]}


def _headers() -> dict:
    return {"x-api-key": "mg-test", "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"}


# ============ P0-1：字符串 code 不得升级成 500 ============

async def test_string_error_code_is_classified_not_500(vendor, make_gateway, client):
    """上游 SSE error 帧带**字符串** `code` → 网关须正常归类（503 无可用资源），
    而不是 TypeError 逃逸成 500。

    复现实盘形状：`{"error": {"code": "ENTITLEMENT_ERROR", "message": ...}}`
    （cline 的错误体就是这种形态，`upstream/cline/out.py:37` 取证）。
    流内**内容前**出错误帧 ⇒ 走 `scheduler` 的"未 committed"分支 ⇒ 必经 `classify()`。
    """
    vendor.set("sk-A", StreamOk(chunks=[],
                                err_after=Err(status="ENTITLEMENT_ERROR",
                                              err_type="ENTITLEMENT_ERROR",
                                              message="not subscribed to required model plan")))
    vendor.set("sk-B", StreamOk(chunks=[],
                                err_after=Err(status="ENTITLEMENT_ERROR",
                                              err_type="ENTITLEMENT_ERROR",
                                              message="not subscribed to required model plan")))
    gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))

    resp = await client.post(f"{gw.base_url}{MESSAGES_URL}",
                             json={**_abody(), "stream": True}, headers=_headers())

    # 关键：不是 500（此前 TypeError 逃逸 → 500）
    assert resp.status_code != 500, resp.text
    assert resp.status_code in (502, 503), resp.text

    # 事件仍带可读原因（此前 classify 提前抛出 ⇒ error_summary 为 null）
    await gw.drain_events()
    evs = gw.read_events()
    assert evs, "未落事件"
    assert all(e.get("error_summary") for e in evs), evs
    assert all(e["status"] != "success" for e in evs), evs


async def test_string_error_code_on_openai_chat_endpoint(vendor, make_gateway, client):
    """同一形状在 `/v1/chat/completions` 上也必须是可归类的错误，不是 500。"""
    for k in "AB":
        vendor.set(f"sk-{k}", StreamOk(chunks=[],
                                       err_after=Err(status="ENTITLEMENT_ERROR",
                                                     err_type="ENTITLEMENT_ERROR",
                                                     message="not subscribed")))
    gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))

    resp = await client.post(f"{gw.base_url}{CHAT_URL}",
                             json={"model": "test-model", "stream": True,
                                   "messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code != 500, resp.text
    assert resp.status_code in (502, 503), resp.text


# ============ P1-2：未归因异常必须可归因，不是空体 500 ============

def _boom(*_a, **_k):
    raise TypeError("' >=' not supported between instances of 'str' and 'int'")


async def test_unattributed_error_on_chat_endpoint(vendor, make_gateway, client, monkeypatch):
    vendor.set("sk-A", Ok(content="x"))
    gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
    monkeypatch.setattr(gw.runtime.scheduler, "execute_chat", _boom)

    resp = await client.post(f"{gw.base_url}{CHAT_URL}",
                             json={"model": "test-model",
                                   "messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 500
    body = resp.json()
    assert "error" in body, f"响应体不是网关错误格式：{body!r}（raw={resp.text[:300]!r}）"
    assert body["error"]["code"] == "UNATTRIBUTED_ERROR"
    assert "TypeError" in body["error"]["message"]     # 类型名足以让两端日志对上


async def test_unattributed_error_on_messages_endpoint(vendor, make_gateway, client, monkeypatch):
    vendor.set("sk-A", Ok(content="x"))
    gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
    monkeypatch.setattr(gw.runtime.scheduler, "execute_chat", _boom)

    resp = await client.post(f"{gw.base_url}{MESSAGES_URL}", json=_abody(),
                             headers=_headers())
    assert resp.status_code == 500
    body = resp.json()
    assert body["type"] == "error"
    assert body["error"]["code"] == "UNATTRIBUTED_ERROR"
    assert "TypeError" in body["error"]["message"]
