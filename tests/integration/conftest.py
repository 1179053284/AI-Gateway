"""INT 集成测试基建：FakeVendor（module 级）+ 网关（function 级）。

- 每个用例独立网关实例（独立 config / usage_dir / 端口），互不污染
- 网关 resources[].base_url 指向 FakeVendor；事件落盘走真实 EventLogger 单写队列
- drain_events()：等单写队列排空后再读 JSONL（防读到半写状态）
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
from pathlib import Path

import httpx
import pytest
import uvicorn
import yaml

from tests.integration.fakevendor import FakeVendor, start_fake_vendor


@pytest.fixture
async def vendor():
    """FakeVendor：function 级（与测试同事件循环；跨 loop 的 uvicorn 无法处理请求）。"""
    v = FakeVendor()
    server, task, wait_ready = start_fake_vendor(v)
    v.port = await wait_ready()
    yield v
    server.should_exit = True
    await asyncio.wait_for(task, timeout=10)


class GatewayHandle:
    def __init__(self, base_url: str, config_path: Path, usage_dir: Path,
                 app, server, task):
        self.base_url = base_url
        self.config_path = config_path
        self.usage_dir = usage_dir
        self.app = app
        self._server = server
        self._task = task

    @property
    def runtime(self):
        return self.app.state.runtime

    async def stop(self):
        self._server.should_exit = True
        await asyncio.wait_for(self._task, timeout=10)

    async def drain_events(self):
        """等单写队列排空（事件 JSONL 可读）。"""
        await self.runtime.events.queue.join()
        await asyncio.sleep(0.02)  # 文件 flush 余量

    def _read_jsonl(self, kind: str) -> list[dict]:
        day = dt.datetime.now().strftime("%Y%m%d")
        path = self.usage_dir / f"{kind}-{day}.jsonl"
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                raise AssertionError(f"JSONL 存在不可解析行：{line[:120]}")
        return out

    def read_events(self) -> list[dict]:
        return self._read_jsonl("events")

    def read_switches(self) -> list[dict]:
        return self._read_jsonl("switch-events")

    def resource(self, res_id: str, vendor_model: str | None = None):
        vm = vendor_model or f"vm-{res_id[-1]}"
        return self.runtime.resources.registry.get((res_id, vm))


def gateway_config(vendor_port: int, *, models: list[dict],
                   scheduling: dict | None = None, gateway: dict | None = None,
                   error_rules: list | None = None) -> dict:
    """构造指向 FakeVendor 的完整配置字典（Q18-② 扁平资源）。"""
    cfg: dict = {
        "resources": [{"id": f"res-{k}", "name": f"资源{k}", "access_mode": "api",
                       "protocol": "openai",
                       "base_url": f"http://127.0.0.1:{vendor_port}/v1",
                       "api_key": f"sk-{k}"} for k in "ABCD"],
        "models": models,
    }
    if scheduling:
        cfg["scheduling"] = scheduling
    if gateway:
        cfg["gateway"] = gateway
    if error_rules:
        cfg["error_rules"] = error_rules
    return cfg


def chat_res(keys: str = "AB", *, name: str = "test-model", **over) -> dict:
    """chat 系统模型 + 每资源一个引用（顺序 = 优先级；厂商模型 vm-{k}）。"""
    resources = over.pop("resources", None)
    if resources is None:
        resources = [{"resource": f"res-{k}", "model": f"vm-{k}"} for k in keys]
    m: dict = {"name": name, "endpoint": "chat", "resources": resources}
    m.update(over)
    return m


@pytest.fixture
async def make_gateway(tmp_path: Path, vendor):
    """网关工厂：写临时 config → create_app → uvicorn 随机端口。"""
    from model_gateway.main import create_app

    made: list[GatewayHandle] = []
    n = 0

    async def _make(cfg_dict: dict) -> GatewayHandle:
        nonlocal n
        config_path = tmp_path / f"config-{n}.yaml"
        usage_dir = tmp_path / f"usage-{n}"
        config_path.write_text(yaml.safe_dump(cfg_dict, allow_unicode=True), encoding="utf-8")
        app = create_app(config_path=config_path, usage_dir=usage_dir,
                         enums_path=tmp_path / f"enums-{n}.yaml")
        n += 1
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
        server = uvicorn.Server(config)
        task = asyncio.get_running_loop().create_task(server.serve())
        for _ in range(500):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started, "网关启动超时"
        port = server.servers[0].sockets[0].getsockname()[1]
        gw = GatewayHandle(f"http://127.0.0.1:{port}", config_path, usage_dir, app, server, task)
        made.append(gw)
        return gw

    yield _make
    for gw in made:
        gw._server.should_exit = True
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(gw._task, timeout=10)


@pytest.fixture
async def client():
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), trust_env=False) as c:
        yield c
