"""单元测试共享骨架：内存构造 Runtime（不触网、不落盘）。

- FakeAdapter：按 key 分发脚本（list[dict | Exception]，耗尽后回归默认成功响应）
- build_runtime：以 SimpleNamespace 组装 Scheduler 所需的全部 runtime 字段
"""

from __future__ import annotations

from collections import deque
from types import SimpleNamespace

from model_gateway.config.schemas import AppConfig
from model_gateway.core.errors import ErrorClassifier, UpstreamError
from model_gateway.core.ir import ReasoningSpec
from model_gateway.core.resources import ResourceManager
from model_gateway.core.scheduler import Scheduler

DEFAULT_RESPONSE = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"},
                 "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
}


def http_err(status: int, err_type: str, message: str = "vendor error") -> UpstreamError:
    """构造携带厂商错误体的 UpstreamError。"""
    body = '{"error": {"message": "%s", "type": "%s", "code": %d}}' % (message, err_type, status)
    return UpstreamError(f"upstream {status}", status_code=status,
                         error_body=body, error_type=err_type)


class RecordingEvents:
    def __init__(self):
        self.requests: list[dict] = []
        self.switches: list[dict] = []

    def log_request(self, ev: dict) -> None:
        self.requests.append(ev)

    def log_switch(self, ev: dict) -> None:
        self.switches.append(ev)


class FakeAdapter:
    """出站适配器假件：chat_nonstream 按 key 消费脚本。"""

    def __init__(self):
        self.script: dict[str, list] = {}
        self.calls: list[tuple[str, str, dict]] = []  # (key, vendor_model, body)

    def set(self, key: str, *steps) -> None:
        self.script[key] = list(steps)

    async def _next(self, key: str):
        q = self.script.get(key)
        if q:
            step = q.pop(0)
            if isinstance(step, BaseException):
                raise step
            if callable(step):
                return step()
            return step
        return DEFAULT_RESPONSE

    async def chat_nonstream(self, key: str, vendor_model: str, body: dict, timeout: float):
        self.calls.append((key, vendor_model, body))
        return await self._next(key)

    async def images_generate(self, key: str, vendor_model: str, body: dict, timeout: float):
        self.calls.append((key, vendor_model, body))
        return await self._next(key)


def make_config(*, models: list[dict], resources: list[dict] | None = None,
                scheduling: dict | None = None, error_rules: list | None = None,
                gateway: dict | None = None) -> dict:
    """构造可被 AppConfig 校验的配置字典（Q18-② 扁平资源）。"""
    if resources is None:
        resources = [{"id": f"res-{k}", "name": f"资源{k}", "access_mode": "api",
                      "protocol": "openai", "base_url": "http://fake.local/v1",
                      "api_key": f"sk-{k}"} for k in "ABCD"]
    cfg: dict = {"resources": resources, "models": models}
    if scheduling:
        cfg["scheduling"] = scheduling
    if error_rules:
        cfg["error_rules"] = error_rules
    if gateway:
        cfg["gateway"] = gateway
    return cfg


def chat_model(name: str = "test-model", keys: str = "AB", **over) -> dict:
    """单系统模型 + 每 key 一个资源的模型定义（资源顺序 = 优先级）。"""
    resources = over.pop("resources", None)
    if resources is None:
        resources = [{"resource": f"res-{k}", "model": f"vm-{k}"} for k in keys]
    m: dict = {"name": name, "endpoint": "chat", "resources": resources}
    m.update({k: v for k, v in over.items() if v is not None})
    return m


def build_runtime(cfg_dict: dict, adapter: FakeAdapter, clock=None):
    cfg = AppConfig.model_validate(cfg_dict)
    key_values = {r.id: r.api_key for r in cfg.resources}
    resource_reasoning: dict[tuple[str, str], ReasoningSpec | None] = {}
    for m in cfg.models:
        for r in m.resources:
            rd = r.reasoning
            resource_reasoning[(r.resource, r.model)] = (
                ReasoningSpec(enabled=rd.enabled, effort=rd.effort) if rd else None)
    rt = SimpleNamespace(
        config=cfg,
        resources=ResourceManager(clock) if clock else ResourceManager(),
        classifier=ErrorClassifier(cfg.error_rules),
        adapters={r.id: adapter for r in cfg.resources},
        key_values=key_values,
        resource_reasoning=resource_reasoning,
        model_params={m.name: dict(m.params) for m in cfg.models if m.params},
        events=RecordingEvents(),
        switch_ring=deque(maxlen=200),
    )
    rt.resources.rebuild(cfg)
    rt.scheduler = Scheduler(rt)
    return rt
