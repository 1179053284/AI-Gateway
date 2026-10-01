"""v2.0 §19 M5-3 额度预扣**端到端**测试（走真实网关 + FakeVendor）。

单元层（`test_v2_quota_reservation.py`）验的是记账；本文件验的是
**"额度已 0 的资源仍被派活"这件事在真实请求路径上是否还会发生** ——
上一轮 M5-3 被判未交付，正是因为只有函数、没接进 `pick_and_acquire` 的选路。
"""

from __future__ import annotations

import asyncio

import pytest

from tests.integration.conftest import chat_res, gateway_config
from tests.integration.fakevendor import Err, Ok

pytestmark = pytest.mark.asyncio


async def _chat(client, gw, model):
    return await client.post(f"{gw.base_url}/v1/chat/completions", json={
        "model": model, "messages": [{"role": "user", "content": "hi"}]})


async def test_exhausted_quota_does_not_take_more_requests(vendor, make_gateway, client):
    """🔴 并发不超发（判据本体）：额度 2、上游各 0.5s → 恰好 2 个成功，其余 503。

    用 `delay` 把请求真的叠在飞行中：**预留**（而非事后扣）才拦得住第三个。
    """
    vendor.set("sk-A", *[Ok(content="r", delay=0.5)] * 6)
    gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
    st = gw.resource("res-A", "vm-A")
    gw.runtime.resources.set_quota(st, 2)

    rs = await asyncio.gather(*[_chat(client, gw, "test-model") for _ in range(5)])
    codes = [r.status_code for r in rs]

    assert codes.count(200) == 2, f"超发：{codes}"
    assert set(codes) <= {200, 503}
    assert codes.count(503) == 3
    # 结算后：预留与在途都归零（对称，无泄漏）。
    # ⚠️ 余量仍是 2 —— 快照才是余量的权威，结算不扣它；两个快照之间继续消耗到 0
    #    时由上游 429 → `note_failure`/`bench` 与 §17 的额度耗尽回写承接。
    assert st.quota.remaining == 2
    assert st.quota.reserved == 0
    assert st.in_flight == 0


async def test_unknown_quota_keeps_serving(vendor, make_gateway, client):
    """额度未知（普通按量 Key，`quota_remaining=None`）→ 与 v1.6 行为一致，不受管控。"""
    vendor.set("sk-A", *[Ok(content="r")] * 8)
    gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
    rs = await asyncio.gather(*[_chat(client, gw, "test-model") for _ in range(8)])
    assert all(r.status_code == 200 for r in rs)
    assert gw.resource("res-A", "vm-A").in_flight == 0


async def test_exhausted_primary_fails_over_to_backup(vendor, make_gateway, client):
    """主资源额度耗尽 → 备资源承接，而不是直接 503（§17 额度维度进选路的收益）。"""
    vendor.set("sk-A", Ok(content="A"))
    vendor.set("sk-B", Ok(content="B"))
    gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("AB")]))
    gw.runtime.resources.set_quota(gw.resource("res-A", "vm-A"), 0)

    r = await _chat(client, gw, "test-model")
    assert r.status_code == 200
    assert vendor.bodies_for("sk-A") == []        # 耗尽的主资源一次都不该被派活
    assert len(vendor.bodies_for("sk-B")) == 1


async def test_failure_releases_reservation_so_quota_is_not_burned(
        vendor, make_gateway, client):
    """上游失败 → **释放预留**（不扣额度）：否则几次报错就把额度烧光，用户白挨 503。"""
    vendor.set("sk-A", *[Err(500)] * 8)
    gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")]))
    st = gw.resource("res-A", "vm-A")
    gw.runtime.resources.set_quota(st, 3)

    r = await _chat(client, gw, "test-model")
    assert r.status_code == 503
    assert st.quota.remaining == 3, "失败不应消耗额度"
    assert st.quota.reserved == 0 and st.in_flight == 0
