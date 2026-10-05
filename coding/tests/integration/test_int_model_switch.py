"""INT-39/40/41：模型启用开关集成测试（PRD FR-2.3 / Q17 / D1；tech-design §4.2·§4.7）。

- INT-39：GET /v1/models 仅返回 enabled=true 的网关模型（禁用模型与其枚举池别名
  均不出现）；重新启用后恢复返回
- INT-40：对禁用模型（直名 + 别名命中）POST /v1/chat/completions、
  /v1/images/generations、/v1/messages → 一致 404 + code=model_disabled
  （Anthropic 端点为其错误格式）；FakeVendor 零上游请求；不计资源失败、
  调度器计数不变、无切换事件
- INT-41：config 文件热重载（mtime 轮询）——enabled true→false / false→true
  对新请求即时生效；在途流式请求不中断（请求开始即绑定快照，tech §8-4）

枚举池说明：make_gateway 注入的 enums 文件不存在 → 内置默认池（含
deepseek-v4-flash↔deepseek-v4-flash-0731、claude-sonnet-4↔claude-sonnet-4-20250514
登记别名），禁用模型的别名命中即经由该池解析。
"""

from __future__ import annotations

import asyncio
import time

import httpx
import yaml

from tests.integration.conftest import chat_res, gateway_config
from tests.integration.fakevendor import Ok, StreamOk

CHAT_URL = "/v1/chat/completions"
IMAGES_URL = "/v1/images/generations"
MESSAGES_URL = "/v1/messages"

_ANTHROPIC_HEADERS = {"x-api-key": "mg-test", "anthropic-version": "2023-06-01",
                      "Content-Type": "application/json"}


def _chat_body(model: str, **over) -> dict:
    d = {"model": model, "messages": [{"role": "user", "content": "hi"}]}
    d.update(over)
    return d


async def _fetch_model_ids(client: httpx.AsyncClient, gw) -> list[str]:
    resp = await client.get(f"{gw.base_url}/v1/models")
    assert resp.status_code == 200
    return [m["id"] for m in resp.json()["data"]]


async def _wait_models_contain(client, gw, model_id: str, *, contained: bool,
                               timeout: float = 5.0) -> None:
    """轮询 /v1/models 至目标模型出现/消失（热重载等待手段，超时 5s）。"""
    deadline = time.monotonic() + timeout
    last: list[str] = []
    while time.monotonic() < deadline:
        last = await _fetch_model_ids(client, gw)
        if (model_id in last) == contained:
            return
        await asyncio.sleep(0.1)
    raise AssertionError(
        f"等待 /v1/models 热重载生效超时：{model_id} contained={contained}，最后列表={last}")


def _set_model_enabled(gw, name: str, enabled: bool) -> None:
    """改写运行中网关的 config 文件（mtime 变化触发 1s 轮询热重载）。"""
    data = yaml.safe_load(gw.config_path.read_text(encoding="utf-8"))
    for m in data.get("models", []):
        if m.get("name") == name:
            m["enabled"] = enabled
    gw.config_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


class TestModelsListFilter:
    """INT-39：/v1/models 启用过滤。"""

    async def test_models_list_excludes_disabled(self, vendor, make_gateway, client):
        vendor.set("sk-A", Ok(content="ok"))
        models = [
            chat_res("A", name="deepseek-v4-flash", enabled=False),  # 别名 0731 已登记
            chat_res("A", name="test-model"),
        ]
        gw = await make_gateway(gateway_config(vendor.port, models=models))

        ids = await _fetch_model_ids(client, gw)
        assert ids == ["test-model"]  # 仅返回 enabled=true 者
        # 禁用模型与其枚举池别名均不出现在返回列表
        assert "deepseek-v4-flash" not in ids
        assert "deepseek-v4-flash-0731" not in ids

    async def test_reenable_restores_listing(self, vendor, make_gateway, client):
        """重新启用后恢复返回（重建网关验证；热重载路径由 INT-41 覆盖）。"""
        vendor.set("sk-A", Ok(content="ok"))
        models = [chat_res("A", name="deepseek-v4-flash", enabled=False),
                  chat_res("A", name="test-model")]
        gw = await make_gateway(gateway_config(vendor.port, models=models))
        assert "deepseek-v4-flash" not in await _fetch_model_ids(client, gw)

        models[0]["enabled"] = True
        gw2 = await make_gateway(gateway_config(vendor.port, models=models))
        ids2 = await _fetch_model_ids(client, gw2)
        assert set(ids2) == {"deepseek-v4-flash", "test-model"}


class TestDisabledModelRequests:
    """INT-40：禁用模型三端点一致 404 model_disabled；零上游请求、不计失败。"""

    async def test_three_endpoints_404_model_disabled(self, vendor, make_gateway, client):
        vendor.set("sk-A", Ok(content="ok"))  # 若误触达上游会成功返回——用于反证零触达
        models = [
            chat_res("A", name="deepseek-v4-flash", enabled=False),   # chat 直名 + 别名
            chat_res("A", name="claude-sonnet-4", enabled=False),     # messages 别名命中
            {"name": "sensenova-u1-fast", "endpoint": "images", "enabled": False,
             "resources": [{"resource": "res-A", "model": "vm-A"}]},
        ]
        gw = await make_gateway(gateway_config(vendor.port, models=models))

        # —— /v1/chat/completions：直名命中禁用模型 ——
        resp = await client.post(f"{gw.base_url}{CHAT_URL}",
                                 json=_chat_body("deepseek-v4-flash"))
        assert resp.status_code == 404
        err = resp.json()["error"]
        assert err["code"] == "model_disabled"
        assert "已禁用" in err["message"]
        assert "管理界面" in err["message"]
        assert err["requested_model"] == "deepseek-v4-flash"

        # —— /v1/chat/completions：枚举池别名命中禁用模型 ——
        resp = await client.post(f"{gw.base_url}{CHAT_URL}",
                                 json=_chat_body("deepseek-v4-flash-0731"))
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "model_disabled"

        # —— /v1/images/generations：直名命中禁用图像模型 ——
        resp = await client.post(f"{gw.base_url}{IMAGES_URL}",
                                 json={"model": "sensenova-u1-fast", "prompt": "a cat"})
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "model_disabled"

        # —— /v1/messages：Anthropic 原生 model id 别名命中禁用模型（Anthropic 错误格式）——
        resp = await client.post(f"{gw.base_url}{MESSAGES_URL}",
                                 json={"model": "claude-sonnet-4-20250514",
                                       "max_tokens": 64,
                                       "messages": [{"role": "user", "content": "hi"}]},
                                 headers=_ANTHROPIC_HEADERS)
        assert resp.status_code == 404
        body = resp.json()
        assert body["type"] == "error"  # Anthropic 错误形态
        assert body["error"]["code"] == "model_disabled"
        assert "已禁用" in body["error"]["message"]
        assert "管理界面" in body["error"]["message"]

        # —— FakeVendor 断言零上游请求（解析层即拒绝）——
        assert vendor.requests == []

        # —— 不计资源失败、调度器计数不变、无事件/切换记录 ——
        await gw.drain_events()
        assert gw.read_events() == []
        assert gw.read_switches() == []
        a = gw.resource("res-A")
        assert a.C == 0
        assert a.status == "active"
        assert a.in_flight == 0


class TestHotReloadToggle:
    """INT-41：模型开关热重载（mtime 轮询 + Runtime._apply 原子替换，tech §8-4）。"""

    async def test_disable_then_enable_via_config_file(self, vendor, make_gateway, client):
        vendor.set("sk-A", Ok(content="ok"))
        models = [chat_res("A", name="test-model")]  # enabled 缺省 = true
        gw = await make_gateway(gateway_config(vendor.port, models=models))

        # 基线：启用状态请求成功
        resp = await client.post(f"{gw.base_url}{CHAT_URL}",
                                 json=_chat_body("test-model"))
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "ok"
        upstream_after_baseline = len(vendor.requests)

        # true → false：新请求即时按新状态生效（404 model_disabled）
        _set_model_enabled(gw, "test-model", False)
        await _wait_models_contain(client, gw, "test-model", contained=False)
        resp = await client.post(f"{gw.base_url}{CHAT_URL}",
                                 json=_chat_body("test-model"))
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "model_disabled"
        assert len(vendor.requests) == upstream_after_baseline  # 不触达上游

        # false → true：恢复调度
        _set_model_enabled(gw, "test-model", True)
        await _wait_models_contain(client, gw, "test-model", contained=True)
        resp = await client.post(f"{gw.base_url}{CHAT_URL}",
                                 json=_chat_body("test-model"))
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "ok"

    async def test_inflight_stream_unaffected_by_toggle(self, vendor, make_gateway, client):
        """在途流式请求进行中禁用模型 → 该请求不中断、正常收尾（快照语义）。"""
        vendor.set("sk-A", StreamOk(chunks=["你", "好"], delay_between=1.0))
        gw = await make_gateway(gateway_config(vendor.port,
                                                models=[chat_res("A", name="test-model")]))

        collected: list[str] = []

        async def consume() -> None:
            async with client.stream("POST", f"{gw.base_url}{CHAT_URL}",
                                     json=_chat_body("test-model", stream=True)) as resp:
                assert resp.status_code == 200  # 延迟提交窗口过后成功提交
                async for line in resp.aiter_lines():
                    collected.append(line)

        task = asyncio.create_task(consume())

        # 等待首内容帧到达（请求已在途、已绑定快照）
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if any("chat.completion.chunk" in line for line in collected):
                break
            await asyncio.sleep(0.05)
        assert any("chat.completion.chunk" in line for line in collected), "首帧超时未到"

        # 在途期间禁用模型并等热重载生效（对新请求的 /v1/models 可见性变化为准）
        _set_model_enabled(gw, "test-model", False)
        await _wait_models_contain(client, gw, "test-model", contained=False)

        # 新请求被拒，但在途流式请求正常收尾（不中断、有 [DONE]）
        resp = await client.post(f"{gw.base_url}{CHAT_URL}",
                                 json=_chat_body("test-model"))
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "model_disabled"

        await asyncio.wait_for(task, timeout=10.0)
        assert any("[DONE]" in line for line in collected), "在途流未正常收尾"
        assert any("你" in line for line in collected)
