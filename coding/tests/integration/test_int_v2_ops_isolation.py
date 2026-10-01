"""§19 M5-1 判据「无住宅代理 → 降级 `failed` 且**模型转发不受影响**」端到端测试。

上一轮该判据只测到"客户端层会报错"（`test_v2_zcode_claim.py`），
**没有**断言"转发不受影响"这一半，也没有并发。本轮补上：
运营批量与模型转发在**同一时刻**跑，运营失败不得污染转发路径。
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from model_gateway.ops import runner as ops_runner
from model_gateway.ops.builtin import zcode_claim
from model_gateway.upstream.zcode import claim as claim_mod
from tests.integration.conftest import chat_res, gateway_config
from tests.integration.fakevendor import Ok

pytestmark = pytest.mark.asyncio


class _NoProxyClient:
    """假上游：preview 有活动，claim 走到验证码时抛 `CaptchaUnavailable`（= 未配住宅代理）。"""

    class _Plan:
        plan_id = "p1"

    def __init__(self, *a, **kw):
        pass

    async def preview(self):
        return self._Plan()

    async def claim(self, plan_id, *, manual=False):
        raise claim_mod.CaptchaUnavailable(
            "未配置住宅代理，验证码求解不可用 —— 请配置 gateway.zcode.proxy"
            "（或环境变量 MGW_ZCODE_PROXY）；也可加 --manual 由人工完成验证码")

    async def aclose(self):
        pass


async def test_ops_failure_does_not_touch_model_forwarding(
        vendor, make_gateway, client, tmp_path, monkeypatch):
    """🔴 运营失败 + 并发转发：转发全部 200，资源**不被冷却**，红点照常累加。"""
    # 账号数据根隔离到 tmp（**必须**：否则 store.accounts_root() 会读仓库真实 data/）
    root = tmp_path / "zcode-accounts"
    monkeypatch.setenv("MGW_ZCODE_ACCOUNTS", str(root))
    _import_account(root, "acct-a")

    vendor.set("sk-A", *[Ok(content="r", delay=0.05)] * 12)
    cfg = gateway_config(vendor.port, models=[chat_res("A", name="zcode-model")])
    cfg["resources"][0]["account"] = "acct-a"        # 资源 ↔ ZCode 账号的映射约定（Q20-③）
    gw = await make_gateway(cfg)
    st = gw.resource("res-A", "vm-A")
    before = st.status

    async def claim(account, **kw):
        return await zcode_claim.claim(account, client_factory=_NoProxyClient, **kw)

    chats = [_chat(client, gw, "zcode-model") for _ in range(6)]
    report, responses = await asyncio.gather(
        ops_runner.run_once(accounts=["acct-a"], claim=claim),
        asyncio.gather(*chats))                 # 内层 gather → 运营与转发**同时在飞**

    # ① 运营侧：降级为 failed，文案给得出路（§16.5 不静默）
    assert [a for a, _ in report.failed] == ["acct-a"]
    assert "住宅代理" in report.failed[0][1]
    assert "gateway.zcode.proxy" in report.failed[0][1]

    # ② 转发侧：6 个并发请求全部正常（判据的另一半，上一轮没测）
    assert [r.status_code for r in responses] == [200] * 6

    # ③ 失败**不是**风控：验证码缺失不得把资源踢出生效集
    assert st.status == before == "active"
    assert st.last_error is None

    # ④ 🔴 红点出口照常（§16.6：后台失败必须可见）。
    #    未读数以落盘文件为准，并**经真端点读出**（§21 的出口是 `/admin/api/status`，
    #    原先直接断言进程内计数器 —— 那既证明不了 CLI 可见，也证明不了界面读得到）
    ops_runner.write_report(report, gw.runtime.usage_dir)
    async with httpx.AsyncClient(timeout=10) as c:
        unread = (await c.get(f"{gw.base_url}/admin/api/status")).json()["ops_failed_unread"]
    assert unread == 1, f"运营失败落了盘却点不亮红点：unread={unread}"


async def _chat(client, gw, model):
    return await client.post(f"{gw.base_url}/v1/chat/completions", json={
        "model": model, "messages": [{"role": "user", "content": "hi"}]})


def _import_account(root, name: str) -> None:
    """在隔离的账号根下建一个**有凭据**的账号（生产 `_credentials_of` 要读得到 JWT）。"""
    import json

    from model_gateway.upstream.zcode import store

    payload = root.parent / f"{name}.json"
    payload.write_text(json.dumps({
        "name": name, "device_mid": f"mid-{name}",
        "credentials.json": {"zcodejwttoken": f"jwt-{name}",
                             "oauth:active_provider": "zai"},
    }), encoding="utf-8")
    assert store.import_account(str(payload)).ok
