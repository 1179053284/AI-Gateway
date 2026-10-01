"""v2.0 §19 M5-2 额度聚合端点集成测试。

判据：`GET /admin/api/zcode/quota` 返回 `{accounts, aggregated}`；
**不做对外端点**（与 §16.1 边界一致）。
"""

from __future__ import annotations

import json

import httpx
import pytest
import yaml

from tests.integration.conftest import chat_res, gateway_config

pytestmark = pytest.mark.asyncio

LOG_MARKER = "billing/balance 请求完成 "


def _log_line(*, show: str, total: int, used: int) -> str:
    return LOG_MARKER + json.dumps({
        "data": {"balances": [{"show_name": show, "total_units": total,
                               "used_units": used, "period": "daily"}]}},
        ensure_ascii=False)


async def _gw(tmp_path, accounts_root):
    from model_gateway.main import create_app

    cfg = gateway_config(1, models=[chat_res("AB")])
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    app = create_app(config_path=p, usage_dir=tmp_path / "usage",
                     enums_path=tmp_path / "enums.yaml")
    import uvicorn
    import asyncio
    uc = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(uc)
    task = asyncio.get_running_loop().create_task(server.serve())
    for _ in range(500):
        if server.started:
            break
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]

    class GW:
        base_url = f"http://127.0.0.1:{port}"
        runtime = app.state.runtime

        async def stop(self):
            server.should_exit = True
            await asyncio.wait_for(task, timeout=10)

    return GW()


@pytest.fixture
def zcode_root(tmp_path, monkeypatch):
    root = tmp_path / "zcode-accounts"
    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(root))
    return root


def _seed_account(root, name: str, *, device: str, logs: list[str] | None = None):
    """造一个账号目录（含可选日志）。"""
    base = root / name
    (base / "meta.json").parent.mkdir(parents=True, exist_ok=True)
    (base / "meta.json").write_text(json.dumps({"device_mid": device}), encoding="utf-8")
    if logs:
        d = base / "data" / ".zcode" / "v2" / "logs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "2026-09-26.log").write_text("\n".join(logs) + "\n", encoding="utf-8")


async def test_quota_endpoint_returns_shape(tmp_path, zcode_root):
    gw = await _gw(tmp_path, zcode_root)
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{gw.base_url}/admin/api/zcode/quota")
        assert r.status_code == 200
        body = r.json()
        assert "accounts" in body and "aggregated" in body
        assert set(body["aggregated"]) == {"used", "total"}
    finally:
        await gw.stop()


async def test_quota_reads_from_client_log_first(tmp_path, zcode_root):
    """🔴 数据源优先级：**客户端日志优先**（绕开签名风控，§17）。"""
    _seed_account(zcode_root, "acct-a", device="mid-a",
                  logs=[_log_line(show="GLM-5.3", total=3_000_000, used=1_200_000)])

    gw = await _gw(tmp_path, zcode_root)
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            body = (await c.get(f"{gw.base_url}/admin/api/zcode/quota")).json()

        assert len(body["accounts"]) == 1
        assert body["accounts"][0]["account"] == "acct-a"
        assert body["accounts"][0]["used"] == 1_200_000
        assert body["aggregated"]["used"] == 1_200_000
    finally:
        await gw.stop()


async def test_quota_aggregates_across_accounts(tmp_path, zcode_root):
    _seed_account(zcode_root, "a", device="m1",
                  logs=[_log_line(show="GLM-5.3", total=1000, used=300)])
    _seed_account(zcode_root, "b", device="m2",
                  logs=[_log_line(show="GLM-5.3", total=2000, used=700)])

    gw = await _gw(tmp_path, zcode_root)
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            body = (await c.get(f"{gw.base_url}/admin/api/zcode/quota")).json()

        assert body["aggregated"] == {"used": 1000, "total": 3000}
    finally:
        await gw.stop()


async def test_quota_account_without_log_is_marked_not_ok(tmp_path, zcode_root):
    """无日志记录 → `ok=false`（界面可提示"数据可能过期"），**不假装有数据**。"""
    _seed_account(zcode_root, "empty", device="m3")

    gw = await _gw(tmp_path, zcode_root)
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            body = (await c.get(f"{gw.base_url}/admin/api/zcode/quota")).json()

        assert body["accounts"][0]["ok"] is False
        assert body["aggregated"]["used"] == 0
    finally:
        await gw.stop()


async def test_quota_is_not_exposed_on_v1(tmp_path, zcode_root):
    """🔴 **不做对外端点** —— 运营接口不是 OpenAI 兼容 API 的组成部分（§16.1）。"""
    gw = await _gw(tmp_path, zcode_root)
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            for path in ("/v1/zcode/quota", "/v1/quota", "/v1/credits"):
                r = await c.get(f"{gw.base_url}{path}")
                assert r.status_code == 404, f"{path} 不应存在"
    finally:
        await gw.stop()


async def test_status_exposes_ops_failed_counter(tmp_path, zcode_root):
    """顶栏红点数据源：`/admin/api/status` 的 `ops_failed_unread`。"""
    gw = await _gw(tmp_path, zcode_root)
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            body = (await c.get(f"{gw.base_url}/admin/api/status")).json()
        assert body["ops_failed_unread"] == 0
    finally:
        await gw.stop()


# ---------- 新增端点：失败清零 + 方言表重载（验收修正）----------
#
# ⚠️ 这两个用例用 **ASGI transport**（不走真实 uvicorn 端口）——
#    实测该文件里"启真实 uvicorn + 复用 GW 类属性"的组合在个别用例下会拿不到路由
#    （环境相关），ASGI transport 直连 app 更稳且更快。

async def _asgi_client(tmp_path, zcode_root):
    from model_gateway.main import create_app

    cfg = gateway_config(1, models=[chat_res("AB")])
    p = tmp_path / "cfg-asgi.yaml"
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    app = create_app(config_path=p, usage_dir=tmp_path / "usage-asgi",
                     enums_path=tmp_path / "enums-asgi.yaml")
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    return client, app.state.runtime


async def test_ops_ack_endpoint_clears_the_file_backed_count(tmp_path, zcode_root):
    """🔴 红点必须有**清零出口**，且数的与清的是**同一份事实**（验收 S-5）。

    未读数由 `data/usage/ops-results-<date>.jsonl` 算出（cron 与 CLI 两条腿都写它），
    本用例走 `ops_runner.write_report` 这个**生产写入函数**造数据 ——
    不再手工设 `runtime.ops_failed_unread`（那是测试自己造答案，挡不住"改了文件没改计数"）。
    """
    from model_gateway.ops.base import OpReport
    from model_gateway.ops import runner as ops_runner

    client, runtime = await _asgi_client(tmp_path, zcode_root)
    async with client:
        ops_runner.write_report(OpReport(failed=[("a", "网络错"), ("b", "网络错")]),
                                runtime.usage_dir)
        ops_runner.write_report(OpReport(failed=[("c", "验证码")]), runtime.usage_dir)
        assert (await client.get("/admin/api/status")).json()["ops_failed_unread"] == 3

        r = await client.post("/admin/api/ops/ack")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "cleared": 3}
        assert (await client.get("/admin/api/status")).json()["ops_failed_unread"] == 0

        # 确认之后**新写入**的失败必须重新点亮（水位只吃掉它之前的那些）
        ops_runner.write_report(OpReport(failed=[("d", "又失败了")]), runtime.usage_dir)
        assert (await client.get("/admin/api/status")).json()["ops_failed_unread"] == 1


async def test_ops_ack_is_idempotent(tmp_path, zcode_root):
    client, runtime = await _asgi_client(tmp_path, zcode_root)
    async with client:
        assert (await client.post("/admin/api/ops/ack")).json()["cleared"] == 0
        assert (await client.post("/admin/api/ops/ack")).json()["cleared"] == 0


async def test_dialects_reload_endpoint(tmp_path, zcode_root):
    """🔴 `mgw probe` 写完方言表后需**显式触发**运行中网关重载（§13.4，不加 watcher）。"""
    client, _ = await _asgi_client(tmp_path, zcode_root)
    async with client:
        r = await client.post("/admin/api/dialects/reload")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True and "before" in body and "after" in body


# ---------- 🔴 §17 全局熔断回写端点（CLI 独立进程 → 让运行中的网关自己回写）----------

async def test_bench_endpoint_global_scope_benches_all_zcode_resources(tmp_path, zcode_root):
    """scope=global → 两个账号的资源**一并**进冷却，`last_error` 注明全局熔断。

    这是"CLI 腿熔断"的落点：上一轮只有 cron 一条腿，手动领取遇风控时静默不生效。
    """
    from model_gateway.upstream.zcode import store

    client, runtime = await _asgi_client(tmp_path, zcode_root)
    _seed_account(zcode_root, "acct-a", device="mid-a")
    _seed_account(zcode_root, "acct-b", device="mid-b")
    # 让 cfg 的 res-A / res-B 分别挂到两个 ZCode 账号上（资源 ↔ 账号映射约定 Q20-③）
    runtime.config.resources[0].account = "acct-a"
    runtime.config.resources[1].account = "acct-b"
    assert [a.name for a in store.list_accounts()] == ["acct-a", "acct-b"]

    async with client:
        r = await client.post("/admin/api/zcode/bench",
                              json={"scope": "global", "account": "acct-a"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True and body["scope"] == "global"
        assert body["benched"] == 2, "全局熔断必须一并回写全部 ZCode 账号"

    states = [s for s in runtime.resources.registry.values()
              if s.rid in ("res-A", "res-B")]
    assert all(s.status == "cooldown" for s in states)
    assert all("全局熔断" in (s.last_error or "") or "风控熔断" in (s.last_error or "")
               for s in states), [s.last_error for s in states]


async def test_bench_endpoint_account_scope_requires_account(tmp_path, zcode_root):
    """scope=account 时缺 account → 400（不得静默按全局处理，那是放大破坏面）。"""
    client, runtime = await _asgi_client(tmp_path, zcode_root)
    async with client:
        assert (await client.post("/admin/api/zcode/bench",
                                  json={"scope": "account"})).status_code == 400
        assert all(s.status == "active" for s in runtime.resources.registry.values())


async def test_overview_surfaces_circuit_reason(tmp_path, zcode_root):
    """🔴 验收 B3 的端到端版：熔断后**接口**要把原因带出来（前端那一列的数据源）。

    只写 `ResourceState.last_error`、不进 `/admin/api/overview` = 用户还是看不见，
    §17「无需改前端就能看到熔断原因」的收益根本不成立。
    """
    _seed_account(zcode_root, "acct-a", device="mid-a")
    client, runtime = await _asgi_client(tmp_path, zcode_root)
    runtime.config.resources[0].account = "acct-a"
    async with client:
        await client.post("/admin/api/zcode/bench", json={"scope": "global"})
        ov = (await client.get("/admin/api/overview")).json()
    row = next((r for r in ov["resources"] if r["rid"] == "res-A"), None)
    assert row is not None, "资源健康卡数据里找不到该资源"
    assert "风控熔断" in str(row.get("last_error") or ""), row
    assert row["status"] == "cooldown"


async def test_bench_endpoint_leaves_non_zcode_resources_alone(tmp_path, zcode_root):
    """非 ZCode 账号的资源（普通按量 Key）不得被风控熔断牵连。"""
    _seed_account(zcode_root, "acct-a", device="mid-a")
    client, runtime = await _asgi_client(tmp_path, zcode_root)
    runtime.config.resources[0].account = "acct-a"     # 只有 res-A 属于 ZCode 账号
    async with client:
        body = (await client.post("/admin/api/zcode/bench",
                                  json={"scope": "global"})).json()
    assert body["benched"] == 1
    by_rid = {s.rid: s.status for s in runtime.resources.registry.values()}
    assert by_rid["res-A"] == "cooldown"
    assert all(st == "active" for rid, st in by_rid.items() if rid != "res-A")
