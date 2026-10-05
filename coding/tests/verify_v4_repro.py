"""🔴 临时复现件（学习轮 V4 · 2026-10-04）—— 不是在册判据，跑完保留备查，**不入库**。

目的：把 `docs/research/27-DSH插件网关与模型清单调研-结论.md` §3 的 **L5 / L6 / L11**
三条「合并语义」借鉴项从「读码 + `grep` 推断」升级成**行为实测**（真实调度路径 + 真实出站体），
并且**独立复验**报告原文引用的我方代码事实（不抄报告结论）。

三个实验：

  ① **缝合法反例（L11）**：两条**账号侧**来源各说一半
     （A 号 `image_input=True, context=262144` / B 号 `image_input=False, context=1000000`）
     ⇒ 打印 `/v1/models` 真正对外声明的那一份，并证明「1M 窗口 + 支持图片」这个组合
     **没有任何一条资源同时说过**；随后走真实调度：带图 + 带 tools 的请求
     真的被派到目录里明说 `image_input=False` 的那个号（`_capacity_reject` 只有输出维）。
     对照组：假供应商按真实供应商那样回 400 ⇒ 网关**原样透传、零次换号**（`BAD_REQUEST` 分支直抛）。

  ② **取大 vs 取小（L5）**：同池两个号 `max_output=512 / 32000`
     ⇒ 实测「出站缺省注入按号」与「超窗换号」两条腿（我方 Q33 已实现的部分），
     量出对外声明仍是**池内最大**（取大只发生在声明层），并量化「若改成取小会损失什么」；
     🔴 另量一条报告没说的一层：**输入维（`max_input`）没有任何对应判据** ——
     取大在输出维是「有兜底的承诺」，在输入维是「没兜底的承诺」。

  ③ **档位是否跨号借用（L6）**：供应商模型名 `glm-5.2` 在**内置公开目录**里有档位表
     `["max","high","low"]`，而两个号自己的目录分别是 `("high","xhigh")` / `("medium","high")`
     ⇒ 实测 `scheduler._degrade_effort_if_needed` 用的那张表**既不是这条号自己的、
     也不是对外声明那一份**（声明取两个号自己的目录并集；clamp 只问内置公开目录，
     键先**供应商模型名**、查不到再退回**网关模型名** —— 两张表根本不是一回事）
     两个方向都量：号支持的档被降掉、号从没说过的档被放出去。

⚠️ 边界（诚实申报）：
  - 假供应商的「文本模型收到 image_url 就回 400」「估算输入超窗就回 400」「收到号没说过的档位就回 400」
    都是**按真实供应商的公开行为建模**，不是我方实测过的真实供应商答复（真测要消耗真实额度 ⇒ 须用户授权）。
    🔴 结构性结论（网关有没有这道校验）不依赖建模值：permissive 那一组才是主证据。
  - 估算输入 token 用我方自己的 `stats.aggregate.estimate_usage`（粗略 chars/4 + CJK 加权），
    与真实供应商的分词器不等值 ⇒ 只用于造出「A 号 262144 < est < B 号 1000000」这个形状。
  - 零真实网络：上游 = 本地 Starlette 假供应商（随机端口）；账号库与目录缓存落在
    本用例自己的 tmp 树里（`MGW_BUDDY_ACCOUNTS`）；:8300 零接触。
  - 本文件不改任何既有源码 / 既有测试。

跑法：
    cd coding && .venv/bin/python -m pytest -q tests/verify_v4_repro.py -s
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path

import httpx
import pytest
import uvicorn
import yaml
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from model_gateway.accounts import catalog_cache, store
from model_gateway.accounts.types import ModelInfo
from model_gateway.core.model_spec import ModelSpec, merge_specs
from model_gateway.stats.aggregate import estimate_usage
from tests.integration.conftest import GatewayHandle

PRODUCT = "buddy"
CHAT_PATH = "/v2/chat/completions"          # buddy 族取证值（`upstream/buddy/out.py`）
TOKEN_IMG = "TK-IMG-ONLY-262K"             # ① 里"支持图片、窗口 262144"的那个号
TOKEN_TXT = "TK-TXT-ONLY-1M"               # ① 里"明说不支持图片、窗口 1M"的那个号
TOKEN_SMALL = "TK-CAP-512"                 # ② 里 max_output=512 的号
TOKEN_BIG = "TK-CAP-32000"                 # ② 里 max_output=32000 的号
TOKEN_A = "TK-EFFORT-HIGH-XHIGH"           # ③ 号 A 自己的档位表 = (high, xhigh)
TOKEN_B = "TK-EFFORT-MEDIUM-HIGH"          # ③ 号 B 自己的档位表 = (medium, high)


# ---------------------------------------------------------------- 打印（读数进报告）

def say(tag: str, **kv) -> None:
    parts = "；".join(f"{k}={_fmt(v)}" for k, v in kv.items())
    print(f"\n[{tag}] {parts}")


def _fmt(v) -> str:
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return repr(v)


# ---------------------------------------------------------------- 假供应商（账号侧上游）

class AccountVendor:
    """按 **Bearer 令牌**区分账号的假 CodeBuddy 上游（OpenAI 形状 + `/v2/chat/completions`）。

    三条可选的"真实供应商建模"拒绝规则（默认全关 = 来者不拒 ⇒ 结构性证据不靠它）：
      - `reject_images_from`：该号收到 `image_url` 部件 ⇒ 400 `invalid_request_error`
      - `reject_over_context`：该号收到的估算输入 token > 给定值 ⇒ 400
      - `reject_efforts`：该号收到自己目录里没说过的档位 ⇒ 400
    """

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.reject_images_from: set[str] = set()
        self.reject_over_context: dict[str, int] = {}
        self.reject_efforts: dict[str, set[str]] = {}
        self.app = Starlette(routes=[Route(CHAT_PATH, self._chat, methods=["POST"]),
                                     Route("/v1/chat/completions", self._chat, methods=["POST"])])

    @staticmethod
    def _token(request: Request) -> str:
        raw = request.headers.get("authorization") or ""
        return raw[7:].strip() if raw.lower().startswith("bearer ") else raw.strip()

    @staticmethod
    def _has_image(body: dict) -> bool:
        for msg in body.get("messages", []) or []:
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        return True
        return False

    def _reject(self, status: int, message: str) -> JSONResponse:
        return JSONResponse({"error": {"message": message, "type": "invalid_request_error",
                                       "code": status}}, status_code=status)

    async def _chat(self, request: Request) -> JSONResponse:
        body = await request.json()
        token = self._token(request)
        est_in, _ = estimate_usage(body, "")
        has_image = self._has_image(body)
        self.requests.append({"token": token, "body": body, "has_image": has_image,
                              "est_input_tokens": est_in,
                              "effort": body.get("reasoning_effort"),
                              "has_tools": bool(body.get("tools"))})
        if token in self.reject_images_from and has_image:
            return self._reject(400, f"model bound to {token} does not support image input")
        limit = self.reject_over_context.get(token)
        if limit is not None and est_in > limit:
            return self._reject(400, f"context length {est_in} exceeds the maximum of {limit}")
        bad = self.reject_efforts.get(token)
        eff = body.get("reasoning_effort")
        if bad and eff in bad:
            return self._reject(400, f"reasoning effort {eff} is not available for {token}")
        # 🔴 S-4 收编修正（2026-10-05）：本件首次真正被 pytest 收集运行（旧默认
        # python_files 让它 2,958 行判据从未跑过）。按出站体的 `stream` 标志分流：
        # · buddy 族资源 `stream_only=True`（upstream/buddy/out.py:48，实盘 4/4 取证
        #   400/11101）⇒ 族基类强制带 stream:true 重发 ⇒ 回 SSE；
        # · 按 Key 资源（protocol=openai）非流式端点回 JSON（OpenAI 常规形状）；
        # · 客户端 stream:true 的直连请求也回 SSE。
        from starlette.responses import StreamingResponse

        if not body.get("stream"):
            return JSONResponse({
                "id": f"chatcmpl-{token}", "object": "chat.completion",
                "model": body.get("model", ""),
                "choices": [{"index": 0, "message": {"role": "assistant",
                                                     "content": f"ok:{token}"},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": est_in, "completion_tokens": 3},
            })

        async def _sse_gen():
            frame = {"id": f"chatcmpl-{token}", "object": "chat.completion.chunk",
                     "model": body.get("model", ""),
                     "choices": [{"index": 0,
                                  "delta": {"role": "assistant", "content": f"ok:{token}"},
                                  "finish_reason": None}]}
            yield f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"
            tail = {"id": f"chatcmpl-{token}", "object": "chat.completion.chunk",
                    "model": body.get("model", ""),
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": est_in, "completion_tokens": 3}}
            yield f"data: {json.dumps(tail, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(_sse_gen(), media_type="text/event-stream")

    def tokens_seen(self) -> list[str]:
        return [r["token"] for r in self.requests]


# ---------------------------------------------------------------- 夹具

@pytest.fixture
async def acc_vendor():
    fake = AccountVendor()
    server = uvicorn.Server(uvicorn.Config(fake.app, host="127.0.0.1", port=0,
                                           log_level="warning"))
    task = asyncio.get_running_loop().create_task(server.serve())
    for _ in range(500):
        if server.started:
            break
        await asyncio.sleep(0.01)
    assert server.started, "假上游启动超时"
    fake.port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield fake
    finally:
        server.should_exit = True
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=10)


@pytest.fixture
async def make_gw(tmp_path):
    from model_gateway.main import create_app

    made: list[GatewayHandle] = []
    n = 0

    async def _make(cfg_dict: dict) -> GatewayHandle:
        nonlocal n
        config_path = tmp_path / f"v4cfg-{n}.yaml"
        usage_dir = tmp_path / f"v4usage-{n}"
        config_path.write_text(yaml.safe_dump(cfg_dict, allow_unicode=True), encoding="utf-8")
        # 🔴 enums_path 指向一个**不存在**的路径 ⇒ `load_enum_pool` 回落内置目录（BUILTIN_ENTRIES）
        #    —— 实验③要的就是"公开枚举目录在册"这个真实形状。
        app = create_app(config_path=config_path, usage_dir=usage_dir,
                         enums_path=tmp_path / f"v4enums-{n}.yaml")
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
        server = uvicorn.Server(config)
        task = asyncio.get_running_loop().create_task(server.serve())
        for _ in range(500):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started, "网关启动超时"
        port = server.servers[0].sockets[0].getsockname()[1]
        made.append(GatewayHandle(f"http://127.0.0.1:{port}", config_path, usage_dir,
                                  app, server, task))
        n += 1
        return made[-1]

    yield _make
    for gw in made:
        gw._server.should_exit = True
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(gw._task, timeout=10)


@pytest.fixture
async def hclient():
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0), trust_env=False) as c:
        yield c


@pytest.fixture
def buddy_root(tmp_path, monkeypatch):
    """把 buddy 的账号根钉到本用例的 tmp 树 ⇒ 目录缓存落点 = 它的父目录（`catalog_cache.product_dir`）。"""
    root = tmp_path / "buddy" / "accounts"
    monkeypatch.setenv("MGW_BUDDY_ACCOUNTS", str(root))
    return store.product_root(PRODUCT).parent        # 网关自己算出来的那一份（同一把尺）


# ---------------------------------------------------------------- 配置 / 缓存构造

def acct_res(rid: str, account: str, port: int, *, name: str) -> dict:
    """账号侧资源（`product` 非空 ⇒ 凭据位置与 Key 分家，`api_key` 恒空串）。"""
    return {"id": rid, "name": name, "vendor": "", "preset": "", "account": account,
            "product": PRODUCT, "account_ref": account, "api_key": "",
            "protocol": "openai", "access_mode": "api", "enabled": True,
            "base_url": f"http://127.0.0.1:{port}"}


def agg_cfg(port: int, *, refs: list[tuple[str, str]], model_name: str,
            vendor_model: str, x: int = 2) -> dict:
    """单网关模型 + 两个账号资源（**池序 = refs 顺序**）+ 产品位（Q33 两级开关的真相）。"""
    return {
        "resources": [acct_res(rid, acct, port, name=f"账号{acct}")
                      for rid, acct in refs],
        "product_models": [{"product": PRODUCT, "model": vendor_model,
                            "system_model": model_name, "enabled": True}],
        "models": [{"name": model_name, "endpoint": "chat",
                    "resources": [{"resource": rid, "model": vendor_model}
                                  for rid, _acct in refs]}],
        "scheduling": {"max_active_per_model": x, "fail_threshold": 2,
                       "retry_per_request": 0, "retry_backoff_seconds": 0},
    }


def only_account(root: Path, account: str, token: str, vendor_model: str, **fields) -> None:
    """只落**这个号自己**的目录缓存（产品级那份写完就删）⇒ 现场只剩按号证据。

    `token` 同时是该号的 `access_token`：假上游按 Bearer 区分是谁接到了这一枪。
    """
    store.commit_login(PRODUCT, account, {"access_token": token}, {})
    catalog_cache.write_cache(PRODUCT, [ModelInfo(id=vendor_model, **fields)],
                              source_account=account, root=root)
    product_copy = catalog_cache.cache_path(PRODUCT, root=root)
    if product_copy.exists():
        product_copy.unlink()
    assert catalog_cache.read_cache(PRODUCT, root=root) is None


def image_body(model: str, *, prompt_chars: int = 8, max_tokens: int | None = None,
               effort: str | None = None) -> dict:
    content: list[dict] = [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
        {"type": "text", "text": "x" * prompt_chars},
    ]
    body: dict = {"model": model, "messages": [{"role": "user", "content": content}],
                  "tools": [{"type": "function",
                             "function": {"name": "read_file",
                                          "description": "t", "parameters": {}}}]}
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if effort is not None:
        body["reasoning_effort"] = effort
    return body


def text_body(model: str, *, prompt_chars: int, max_tokens: int | None = None,
              effort: str | None = None) -> dict:
    body: dict = {"model": model,
                  "messages": [{"role": "user", "content": "y" * prompt_chars}]}
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if effort is not None:
        body["reasoning_effort"] = effort
    return body


async def get_models(gw: GatewayHandle, hclient) -> dict:
    resp = await hclient.get(f"{gw.base_url}/v1/models")
    assert resp.status_code == 200, resp.text
    payload = resp.json()["data"]
    gw._models_payload = payload          # 挂上去只为本文件的打印方便（不改 GatewayHandle）
    return {d["id"]: d for d in payload}


# ================================================================ 实验① 缝合法反例（L11）

async def test_E11_a_kernel_merge_is_a_combination_no_source_stated():
    """纯函数内核：两条来源各说一半 ⇒ 合并结果 = 没有任何一条来源说过的组合（可复算）。"""
    a = {"context_window": 262144, "max_output": 32000, "image_input": True, "tool_call": True}
    b = {"context_window": 1000000, "max_output": 32000, "image_input": False, "tool_call": False}
    merged = merge_specs([a, b])
    pairs = [(s["context_window"], s["image_input"], s["tool_call"]) for s in (a, b)]
    say("E1-kernel", a_号=pairs[0], b_号=pairs[1],
        合并声明=(merged.max_input, merged.image_input, merged.tool_call),
        来源数=merged.sources,
        有任一来源同时说过=("1M + 图片" if (1_000_000, True) in
                          [(c, im) for c, im, _t in pairs] else "没有"))
    assert merged.max_input == 1000000 and merged.image_input is True
    assert merged.tool_call is True
    assert merged.sources == 2
    # 🔴 缝合成立：`(max_input, image_input)` 这个组合两条来源都没有（A=262144/True，B=1M/False）
    assert (merged.max_input, merged.image_input) not in [(a["context_window"], a["image_input"]),
                                                          (b["context_window"], b["image_input"])]
    # 逐位 provenance 现在有没有地方放？
    from dataclasses import fields
    say("E1-provenance-字段", ModelSpec字段=[f.name for f in fields(ModelSpec)])
    assert not any("source" in f.name and f.name != "sources" for f in fields(ModelSpec))


async def test_E11_b_declaration_and_real_dispatch(make_gw, hclient, acc_vendor, buddy_root):
    """真实调度路径：声明侧给出「1M + 支持图片」，出站把带图带 tools 的请求派给了
    目录里**明说** `image_input=False` 的那个号（`_capacity_reject` 只有输出维）。"""
    only_account(buddy_root, "acc-txt", TOKEN_TXT, "acct-glm-x",
                 context_window=1_000_000, max_output=32000, image_input=False,
                 tool_call=False, effort_levels=())
    only_account(buddy_root, "acc-img", TOKEN_IMG, "acct-glm-x",
                 context_window=262_144, max_output=32000, image_input=True,
                 tool_call=True, effort_levels=())
    # 🔴 池序：txt 在前（冷启动游标 0 ⇒ 第一条必然派给它）
    gw = await make_gw(agg_cfg(acc_vendor.port, refs=[("res-txt", "acc-txt"),
                                                      ("res-img", "acc-img")],
                               model_name="gw-agg-model", vendor_model="acct-glm-x"))
    declared = (await get_models(gw, hclient))["gw-agg-model"]
    say("E1-声明", maxInputTokens=declared["maxInputTokens"],
        supportsImages=declared["supportsImages"], supportsToolCall=declared["supportsToolCall"],
        maxOutputTokens=declared["maxOutputTokens"], specStale=declared.get("specStale"))

    per = {rid: (sp.max_input, sp.image_input, sp.tool_call)
           for (rid, _vm), sp in gw.runtime.resource_specs.items()}
    say("E1-逐号事实", 按号=sorted(per.items()),
        同时说过1M与图片的号=[rid for rid, (ci, im, _t) in per.items()
                              if ci and ci >= 1_000_000 and im is True])
    assert declared["maxInputTokens"] == 1_000_000
    assert declared["supportsImages"] is True
    assert declared["supportsToolCall"] is True
    # 🔴 没有任何一条资源同时说过这个组合（声明是缝出来的）
    assert not [rid for rid, (ci, im, _t) in per.items()
                if ci and ci >= 1_000_000 and im is True]

    for _ in range(4):
        r = await hclient.post(f"{gw.base_url}/v1/chat/completions",
                               json=image_body("gw-agg-model", max_tokens=64))
        assert r.status_code == 200, r.text
    imgs = [rec["token"] for rec in acc_vendor.requests if rec["has_image"]]
    tools = [rec["token"] for rec in acc_vendor.requests if rec["has_tools"]]
    say("E1-出站", 收到图片的号=imgs, 收到tools的号=tools,
        明说不支持图片的号=acc_vendor.tokens_seen().count(TOKEN_TXT))
    assert TOKEN_TXT in imgs, "带图请求没有派到 image_input=False 的号 ⇒ 本条断言失效，需查形状"
    assert TOKEN_TXT in tools

    # 对照组：**输出**维有兜底（同一条请求把 max_tokens 抬到超过某号上限 ⇒ 该号被避开）
    acc_vendor.requests.clear()
    r = await hclient.post(f"{gw.base_url}/v1/chat/completions",
                           json=text_body("gw-agg-model", prompt_chars=8, max_tokens=40000))
    say("E1-对照输出维", status=r.status_code, 被派到的号=acc_vendor.tokens_seen())
    assert r.status_code == 503          # 两个号都装不下 40000 ⇒ ALL_OVER_CAPACITY
    assert acc_vendor.tokens_seen() == []  # 零出站：输出维真的被拦住了


async def test_E11_c_upstream_says_no_but_gateway_does_not_switch(make_gw, hclient,
                                                                  acc_vendor, buddy_root):
    """假供应商按真实供应商那样拒绝（文本专供号收到图 ⇒ 400）⇒ 网关**原样透传 400、零次换号**，
    哪怕池里就有一个明说支持图片的号。聚合的"故障自动切换"在这一维完全不生效。"""
    only_account(buddy_root, "acc-txt", TOKEN_TXT, "acct-glm-x",
                 context_window=1_000_000, max_output=32000, image_input=False,
                 tool_call=False, effort_levels=())
    only_account(buddy_root, "acc-img", TOKEN_IMG, "acct-glm-x",
                 context_window=262_144, max_output=32000, image_input=True,
                 tool_call=True, effort_levels=())
    acc_vendor.reject_images_from = {TOKEN_TXT}
    gw = await make_gw(agg_cfg(acc_vendor.port, refs=[("res-txt", "acc-txt"),
                                                      ("res-img", "acc-img")],
                               model_name="gw-agg-model", vendor_model="acct-glm-x"))
    r = await hclient.post(f"{gw.base_url}/v1/chat/completions",
                           json=image_body("gw-agg-model", max_tokens=64))
    await gw.drain_events()
    ev = gw.read_events()[-1]
    say("E1-拒绝透传", status=r.status_code, 错误体=r.json(),
        出站次数=len(acc_vendor.requests), 出站到的号=acc_vendor.tokens_seen(),
        switch_count=ev["switch_count"], resource_attempts=ev["resource_attempts"])
    assert r.status_code == 400
    assert acc_vendor.tokens_seen() == [TOKEN_TXT]        # 一次都没换到支持图片的那个号
    assert ev["switch_count"] == 0
    assert gw.read_switches() == []


# ================================================================ 实验② 取大 vs 取小（L5）

async def test_E12_a_injection_and_switch_are_per_account(make_gw, hclient,
                                                          acc_vendor, buddy_root):
    """池内 512 / 32000：出站缺省注入与承载校验**都按号**（取大只在声明层发生）。"""
    only_account(buddy_root, "acc-small", TOKEN_SMALL, "acct-glm-y",
                 context_window=262_144, max_output=512, image_input=None,
                 tool_call=None, effort_levels=())
    only_account(buddy_root, "acc-big", TOKEN_BIG, "acct-glm-y",
                 context_window=1_000_000, max_output=32_000, image_input=None,
                 tool_call=None, effort_levels=())
    gw = await make_gw(agg_cfg(acc_vendor.port, refs=[("res-small", "acc-small"),
                                                      ("res-big", "acc-big")],
                               model_name="gw-cap-model", vendor_model="acct-glm-y"))
    declared = (await get_models(gw, hclient))["gw-cap-model"]
    per_out = {rid: sp.max_output for (rid, _vm), sp in gw.runtime.resource_specs.items()}
    vals = [v for v in per_out.values() if v]
    say("E2-三份数", 对外声明_maxOutput=declared["maxOutputTokens"],
        对外声明_maxInput=declared["maxInputTokens"], 按号规格=per_out,
        若取小=min(vals), 取大比取小倍数=round(max(vals) / min(vals), 1))
    assert declared["maxOutputTokens"] == 32000          # 取大（承诺上限）
    assert declared["maxInputTokens"] == 1_000_000

    # (a) 调用方没写 max_tokens ⇒ 注入**这个号自己**的数
    acc_vendor.requests.clear()
    for _ in range(4):
        r = await hclient.post(f"{gw.base_url}/v1/chat/completions",
                               json=text_body("gw-cap-model", prompt_chars=8))
        assert r.status_code == 200, r.text
    inj = {rec["token"]: rec["body"].get("max_tokens") for rec in acc_vendor.requests}
    say("E2-按号注入", 出站max_tokens=inj)
    assert inj.get(TOKEN_SMALL) == 512 or TOKEN_SMALL not in inj
    assert inj.get(TOKEN_BIG) == 32000 or TOKEN_BIG not in inj
    assert {rec["body"].get("max_tokens") for rec in acc_vendor.requests} == {512, 32000}

    # (b) 要求 8000 ⇒ 512 那个号被承载校验避开（不记失败、不计 y），32000 那个号承接
    acc_vendor.requests.clear()
    gw.runtime.resources._cursor.clear()
    r = await hclient.post(f"{gw.base_url}/v1/chat/completions",
                           json=text_body("gw-cap-model", prompt_chars=8, max_tokens=8000))
    await gw.drain_events()
    ev = gw.read_events()[-1]
    say("E2-超窗换号", status=r.status_code, 出站到的号=acc_vendor.tokens_seen(),
        attempts=ev["resource_attempts"], switch_count=ev["switch_count"])
    assert r.status_code == 200
    assert acc_vendor.tokens_seen() == [TOKEN_BIG]        # 小窗号一次都没被派
    assert ev["switch_count"] == 0                        # 避开 ≠ 故障切换（不记失败）
    # 🔴 这条就是"取大在输出维是有兜底的"：声明 32000、要求 8000，池里真有一个号能服务
    assert min(v for v in per_out.values() if v) == 512   # ⇒ 若声明取小成 512，客户端就不敢发这 8000

    # (c) 要求 200000 ⇒ 全池超窗 ⇒ 503 ALL_OVER_CAPACITY 且零出站
    acc_vendor.requests.clear()
    r = await hclient.post(f"{gw.base_url}/v1/chat/completions",
                           json=text_body("gw-cap-model", prompt_chars=8, max_tokens=200000))
    say("E2-全池超窗", status=r.status_code, code=r.json()["error"]["code"],
        出站次数=len(acc_vendor.requests))
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "ALL_OVER_CAPACITY"
    assert acc_vendor.requests == []


async def test_E12_b_input_dimension_is_never_checked(make_gw, hclient, acc_vendor, buddy_root):
    """🔴 报告没说的那一层：`max_input` 取大了，但**输入维没有任何对应判据**。
    估算输入 300K token 的纯文本请求照样派给目录里只有 262144 的那个号（输出维被刻意压小）。"""
    only_account(buddy_root, "acc-small", TOKEN_SMALL, "acct-glm-y",
                 context_window=262_144, max_output=512, effort_levels=())
    only_account(buddy_root, "acc-big", TOKEN_BIG, "acct-glm-y",
                 context_window=1_000_000, max_output=32_000, effort_levels=())
    gw = await make_gw(agg_cfg(acc_vendor.port, refs=[("res-small", "acc-small"),
                                                      ("res-big", "acc-big")],
                               model_name="gw-cap-model", vendor_model="acct-glm-y"))
    declared = (await get_models(gw, hclient))["gw-cap-model"]
    body = text_body("gw-cap-model", prompt_chars=1_200_000, max_tokens=64)
    est = estimate_usage(body, "")[0]
    say("E2b-形状", 对外声明maxInput=declared["maxInputTokens"], 估算输入token=est,
        按号窗口={"acc-small": 262144, "acc-big": 1000000},
        形状判定="262144 < est < 1000000 ⇒ 只有大窗号真能服务"
        if 262_144 < est < 1_000_000 else "形状不符，本条读数作废")
    assert 262_144 < est < 1_000_000

    r = await hclient.post(f"{gw.base_url}/v1/chat/completions", json=body)
    say("E2b-宽松上游", status=r.status_code, 出站到的号=acc_vendor.tokens_seen(),
        网关有没有拦=acc_vendor.tokens_seen().count(TOKEN_SMALL) == 0)
    assert r.status_code == 200
    # 🔴 小窗号被正常派发（承载校验从不看输入维）；permissive 假供应商照回 200
    assert acc_vendor.tokens_seen() == [TOKEN_SMALL]


async def test_E12_c_input_over_context_gets_400_and_no_switch(make_gw, hclient,
                                                               acc_vendor, buddy_root):
    """同一形状 + 假供应商按真实供应商那样回 400 ⇒ 客户端吃 400、零换号（对照：输出维会换号）。"""
    only_account(buddy_root, "acc-small", TOKEN_SMALL, "acct-glm-y",
                 context_window=262_144, max_output=512, effort_levels=())
    only_account(buddy_root, "acc-big", TOKEN_BIG, "acct-glm-y",
                 context_window=1_000_000, max_output=32_000, effort_levels=())
    acc_vendor.reject_over_context = {TOKEN_SMALL: 262_144}
    gw = await make_gw(agg_cfg(acc_vendor.port, refs=[("res-small", "acc-small"),
                                                      ("res-big", "acc-big")],
                               model_name="gw-cap-model", vendor_model="acct-glm-y"))
    r = await hclient.post(f"{gw.base_url}/v1/chat/completions",
                           json=text_body("gw-cap-model", prompt_chars=1_200_000, max_tokens=64))
    await gw.drain_events()
    ev = gw.read_events()[-1]
    say("E2c-输入超窗", status=r.status_code, 上游原文=r.json(),
        出站次数=len(acc_vendor.requests), 出站到的号=acc_vendor.tokens_seen(),
        switch_count=ev["switch_count"])
    assert r.status_code == 400
    assert acc_vendor.tokens_seen() == [TOKEN_SMALL]      # 没有换到能装下的大窗号
    assert ev["switch_count"] == 0


# ================================================================ 实验③ 档位是否跨号借用（L6）

async def _effort_probe(make_gw, hclient, acc_vendor, buddy_root, *, vendor_model: str,
                        effort: str, model_name: str = "gw-effort") -> tuple[dict, dict]:
    """两个号（各带自己的档位目录）× 同一条请求 ⇒ 返回（声明的 thinkingLevelMap, 逐号实发档位）。"""
    only_account(buddy_root, "acc-a", TOKEN_A, vendor_model,
                 context_window=200_000, max_output=8192, effort_levels=("high", "xhigh"))
    only_account(buddy_root, "acc-b", TOKEN_B, vendor_model,
                 context_window=200_000, max_output=8192, effort_levels=("medium", "high"))
    acc_vendor.reject_efforts = {}
    gw = await make_gw(agg_cfg(acc_vendor.port, refs=[("res-a", "acc-a"), ("res-b", "acc-b")],
                               model_name=model_name, vendor_model=vendor_model))
    declared = (await get_models(gw, hclient))[model_name]
    acc_vendor.requests.clear()
    for _ in range(4):
        r = await hclient.post(f"{gw.base_url}/v1/chat/completions",
                               json=text_body(model_name, prompt_chars=8, effort=effort))
        assert r.status_code == 200, r.text
    sent = {}
    for rec in acc_vendor.requests:
        sent.setdefault(rec["token"], set()).add(rec["effort"])
    return declared, {k: sorted(v) for k, v in sent.items()}


async def test_E13_a_enum_pool_table_is_used_not_the_account_table(make_gw, hclient,
                                                                   acc_vendor, buddy_root):
    """供应商模型名在内置公开目录里（glm-5.2 = ["max","high","low"]）⇒ clamp 用的是**那一张表**，
    两个号自己的目录一次都没被问过。"""
    declared, sent = await _effort_probe(make_gw, hclient, acc_vendor, buddy_root,
                                         vendor_model="glm-5.2", effort="medium")
    from model_gateway.enums.matcher import load_enum_pool
    enum_entry = load_enum_pool(None).get("glm-5.2")
    say("E3-公开目录", glm52_effort_levels=list(enum_entry.effort_levels),
        号A自己=("high", "xhigh"), 号B自己=("medium", "high"),
        对外声明的档位=[k for k, v in
                     declared["caps"]["thinkingLevelMap"].items() if v is not None],
        请求档位="medium", 实发档位=sent)
    assert list(enum_entry.effort_levels) == ["max", "high", "low"]
    level_map = declared["caps"]["thinkingLevelMap"]
    say("M1-声明的七键", thinkingLevelMap=level_map,
        实发=sent,
        矛盾="对外声明 low=null（工具据此知道不支持），出站却发 reasoning_effort=low"
        if level_map.get("low") is None else "low 在声明里也是亮的")
    # 🔴 §12.2a 自己钉的契约：不支持的档**显式写 null** ⇒ 这里 low=null 却被发出去 = 网关自相矛盾
    assert level_map.get("low") is None
    assert level_map.get("medium") == "medium"
    # 声明（两个号自己的目录并集）里没有 low/max；clamp（内置公开目录，先按供应商模型名查、查不到退网关模型名）里没有 medium/xhigh
    assert "medium" in [k for k, v in declared["caps"]["thinkingLevelMap"].items() if v is not None]
    assert "low" not in [k for k, v in declared["caps"]["thinkingLevelMap"].items() if v is not None]
    # 🔴 两个号都被发了 "low"：号B 明说只有 (medium, high) ⇒ 被降到一个它没说过的档；
    #    号A 明说只有 (high, xhigh) ⇒ 同样收到 low。号自己的目录**从未参与判定**。
    assert sent == {TOKEN_A: ["low"], TOKEN_B: ["low"]}


async def test_E13_b_declared_level_is_dropped_on_the_account_that_has_it(make_gw, hclient,
                                                                          acc_vendor, buddy_root):
    """请求 xhigh（对外声明里 **xhigh 是亮着的**，且号 A 的目录确实支持）⇒ 被 clamp 成 high。
    方向 = 把号本来就支持的档位降掉，用户只看到答案变差。"""
    declared, sent = await _effort_probe(make_gw, hclient, acc_vendor, buddy_root,
                                         vendor_model="glm-5.2", effort="xhigh")
    say("E3-xhigh", 对外声明的档位=[k for k, v in
                                declared["caps"]["thinkingLevelMap"].items() if v is not None],
        请求="xhigh", 实发=sent, 号A支持="xhigh 在册", 号B支持="xhigh 不在册")
    assert "xhigh" in [k for k, v in declared["caps"]["thinkingLevelMap"].items() if v is not None]
    assert sent == {TOKEN_A: ["high"], TOKEN_B: ["high"]}


async def test_E13_c_no_enum_entry_means_no_clamp_at_all(make_gw, hclient,
                                                         acc_vendor, buddy_root):
    """反向对照：供应商模型名不在公开目录（`acct-only-z`）⇒ clamp 那张表为空 ⇒ **完全不判**，
    号 A（只有 high/xhigh）照样收到它从没说过的 "low"。⇒ `scheduler.py:261-277`
    并没有"按资源自身 effort_levels 降级"，它只按公开目录降级；目录没有就原样透传。"""
    declared, sent = await _effort_probe(make_gw, hclient, acc_vendor, buddy_root,
                                         vendor_model="acct-only-z", effort="low")
    from model_gateway.enums.matcher import load_enum_pool
    say("E3-无目录", 目录里有这条吗=load_enum_pool(None).get("acct-only-z"),
        请求="low", 实发=sent,
        号A目录=("high", "xhigh"), 号B目录=("medium", "high"))
    assert load_enum_pool(None).get("acct-only-z") is None
    assert sent == {TOKEN_A: ["low"], TOKEN_B: ["low"]}


async def test_E13_d_union_cannot_erase_levels_and_is_order_free():
    """插件 D4「空档位覆盖有档位 / 后覆盖前」那两条我方天然不成立（取并 + 顺序无关）；
    但取并本身确实会造出"没有单一来源支持的档位集合"（⇒ 需要的是同行约束，不是整条择优）。"""
    merged = merge_specs([{"effort_levels": ()}, {"effort_levels": ("high", "xhigh")}])
    say("E3-D4形状", 空档不覆盖有档=list(merged.effort_levels))
    assert list(merged.effort_levels) == ["high", "xhigh"]
    a = {"effort_levels": ("low", "high")}
    b = {"effort_levels": ("medium", "high", "max")}
    forward, reverse = merge_specs([a, b]), merge_specs([b, a])
    say("E3-顺序无关", 正序=list(forward.effort_levels), 逆序=list(reverse.effort_levels))
    assert forward.effort_levels == reverse.effort_levels
    # 🔴 并集 = 4 档，而**没有任何一个号**同时支持这 4 档
    assert list(forward.effort_levels) == ["low", "medium", "high", "max"]
    per_number = [set(a["effort_levels"]), set(b["effort_levels"])]
    assert not any(set(forward.effort_levels) <= one for one in per_number)


# ================================================================ 实验④ L5 的两处取值不一致

def _module_level_model_infos():
    """扫 `upstream/<产品>/…` 里**模块级常量**中的每一条 `ModelInfo`（产品内置兜底目录）。

    ⚠️ 范围如实申报：只扫模块级（含嵌套在 list/tuple/dict 里的实例）；在函数体内
    临时构造的不算。这条扫描只为回答"我方仓里同一个供应商模型名有没有多个版本的上限"。
    """
    import importlib
    import pkgutil

    import model_gateway.upstream as up
    out: dict[tuple[str, str], list[ModelInfo]] = {}

    def walk(v):
        if isinstance(v, ModelInfo):
            yield v
        elif isinstance(v, (list, tuple, set)):
            for x in v:
                yield from walk(x)
        elif isinstance(v, dict):
            for x in v.values():
                yield from walk(x)

    for mod in pkgutil.iter_modules(list(up.__path__)):
        for sub in ("product", "const", "models", "catalog"):
            try:
                m = importlib.import_module(f"model_gateway.upstream.{mod.name}.{sub}")
            except Exception:  # noqa: BLE001 — 该子模块不存在/导不进来就跳过
                continue
            for attr in dir(m):
                for info in walk(getattr(m, attr)):
                    if info.id:
                        out.setdefault((mod.name, info.id), []).append(info)
    return out


async def test_E15_a_same_model_has_several_published_limits_in_our_own_repo():
    """插件 `buddy.ts:441-446` 记的「三处取值不一致」在我方仓里同样存在，且**两侧都是声明值**。"""
    from model_gateway.enums.matcher import BUILTIN_ENTRIES
    enum = {e.name: e for e in BUILTIN_ENTRIES}
    rows = []
    for (prod, mid), infos in sorted(_module_level_model_infos().items()):
        e = enum.get(mid)
        if e is None:
            continue
        for i in infos:
            if i.max_output and e.max_output and i.max_output != e.max_output:
                rows.append((prod, mid, "max_output", e.max_output, i.max_output))
            if i.context_window and e.context_window and i.context_window != e.context_window:
                rows.append((prod, mid, "context_window", e.context_window, i.context_window))
    say("E15-两侧都在册的条数", 内置目录=len(enum), 产品兜底条目=len(_module_level_model_infos()))
    say("E15-取值不一致", 条数=len(rows), 样例=rows[:8])
    assert rows, "我方两处目录完全一致 ⇒ L5 的『声明值 vs 实测值』讨论失去对象"
    divergent = sorted({(mid, field) for _p, mid, field, _a, _b in rows})
    say("E15-同一个供应商模型名有多个版本", 清单=divergent[:10])


async def test_E15_b_injection_uses_the_published_limit_and_cannot_self_reject(make_gw, hclient,
                                                                              acc_vendor,
                                                                              buddy_root):
    """混合池（按量 Key 走内置公开目录 + 账号走按号目录）：出站缺省注的是**声明值本身**，
    而 `_capacity_reject` 与注入读同一份数 ⇒ 等值 ⇒ 对"声明值 > 服务端真正接受值"这一类误差
    **零保护**（这正是插件 L5 那条纪律在我方的落点，与"跨供应商取大"是两件事）。"""
    only_account(buddy_root, "acc-glm", TOKEN_TXT, "glm-5.2",
                 context_window=1_000_000, max_output=64_000, effort_levels=("high", "xhigh"))
    cfg = {
        "resources": [
            {"id": "res-api", "name": "按量Key", "access_mode": "api", "protocol": "openai",
             "base_url": f"http://127.0.0.1:{acc_vendor.port}/v1", "api_key": "sk-api-glm"},
            acct_res("res-acct", "acc-glm", acc_vendor.port, name="账号acc-glm"),
        ],
        "product_models": [{"product": PRODUCT, "model": "glm-5.2",
                            "system_model": "gw-mixed", "enabled": True}],
        "models": [{"name": "gw-mixed", "endpoint": "chat",
                    "resources": [{"resource": "res-api", "model": "glm-5.2"},
                                  {"resource": "res-acct", "model": "glm-5.2"}]}],
        "scheduling": {"max_active_per_model": 2, "fail_threshold": 2,
                       "retry_per_request": 0, "retry_backoff_seconds": 0},
    }
    gw = await make_gw(cfg)
    declared = (await get_models(gw, hclient))["gw-mixed"]
    per = {rid: sp.max_output for (rid, _vm), sp in gw.runtime.resource_specs.items()}
    say("E15b-三份数", 对外声明maxOutput=declared["maxOutputTokens"], 按号=per,
        公开目录glm52=131072, 账号目录glm52=64000)
    assert declared["maxOutputTokens"] == 131072          # 取大 = 两家声明值的最大者
    assert per == {"res-api": 131072, "res-acct": 64000}  # 出站各自按自己那一份

    acc_vendor.requests.clear()
    for _ in range(4):
        r = await hclient.post(f"{gw.base_url}/v1/chat/completions",
                               json=text_body("gw-mixed", prompt_chars=8))
        assert r.status_code == 200, r.text
    inj = {rec["token"]: rec["body"].get("max_tokens") for rec in acc_vendor.requests}
    say("E15b-注入", 出站max_tokens=inj,
        承载校验能否自我否决="不能（注入值 == 该号自己的 max_output ⇒ asked<=cap 恒成立）")
    assert inj.get("sk-api-glm") == 131072                 # 注入的是**官网声明值**
    assert inj.get(TOKEN_TXT) == 64000


# ================================================================ 撤证 / 处方原型（判据有没有牙）

async def test_M1_clamp_from_own_spec_reads_differently(make_gw, hclient, acc_vendor,
                                                        buddy_root, monkeypatch):
    """撤证①：把 clamp 的表换成**这条号自己**的那一份（L6 处方的方向）⇒ 同一条判据必须变红。
    若换了实现读数仍不变，说明 E13_a 是空判据。"""
    from model_gateway.core.scheduler import Scheduler

    declared, sent_now = await _effort_probe(make_gw, hclient, acc_vendor, buddy_root,
                                             vendor_model="glm-5.2", effort="medium")
    say("M1-现状", 实发=sent_now)

    # 🔴 签名随 R9 前进（收编首跑暴露）：现行 `_degrade_effort_if_needed` 带
    #    `system_model` 第四参（R9-B-1'）；旧三参桩是 TypeError。
    def own_spec_clamp(self, spec, resource, system_model=None):
        if spec is None or not spec.effort:
            return spec
        rs = getattr(self.runtime, "resource_specs", {}).get(
            (resource.rid, resource.vendor_model))
        supported = list(getattr(rs, "effort_levels", ()) or [])
        if not supported:
            return spec
        from dataclasses import replace
        from model_gateway.core.dialects import degrade_effort
        degraded = degrade_effort(spec.effort, supported)
        return spec if degraded == spec.effort else replace(spec, effort=degraded)

    monkeypatch.setattr(Scheduler, "_degrade_effort_if_needed", own_spec_clamp)
    _d2, sent_patched = await _effort_probe(make_gw, hclient, acc_vendor, buddy_root,
                                            vendor_model="glm-5.2", effort="medium")
    say("M1-改成按号表后", 实发=sent_patched,
        说明="号B(medium,high) 拿到 medium（不再被降掉）；号A(high,xhigh) 就近降到 high")
    assert sent_now == {TOKEN_A: ["low"], TOKEN_B: ["low"]}
    assert sent_patched == {TOKEN_A: ["high"], TOKEN_B: ["medium"]}
    assert declared  # 声明与两版实现都无关 ⇒ 两侧都可各自跑偏


async def test_M2_input_gate_prototype_switches_account(make_gw, hclient, acc_vendor,
                                                       buddy_root, monkeypatch):
    """撤证② / 处方②原型：给 `_capacity_reject` 加一条输入维判据（只在该号**自己**的
    `max_input` 已知、且估算值已超它时才拦）⇒ E2c 那条"小窗号吃 400 且零换号"变成
    "大窗号承接 200"。这条判据现在不存在（现状必红）。"""
    from model_gateway.core.scheduler import Scheduler

    only_account(buddy_root, "acc-small", TOKEN_SMALL, "acct-glm-y",
                 context_window=262_144, max_output=512, effort_levels=())
    only_account(buddy_root, "acc-big", TOKEN_BIG, "acct-glm-y",
                 context_window=1_000_000, max_output=32_000, effort_levels=())
    acc_vendor.reject_over_context = {TOKEN_SMALL: 262_144}
    cfg = agg_cfg(acc_vendor.port, refs=[("res-small", "acc-small"), ("res-big", "acc-big")],
                  model_name="gw-cap-model", vendor_model="acct-glm-y")

    # —— 现状：400 + 零换号 ——
    gw1 = await make_gw(cfg)
    r_now = await hclient.post(f"{gw1.base_url}/v1/chat/completions",
                               json=text_body("gw-cap-model", prompt_chars=1_200_000,
                                              max_tokens=64))
    say("M2-现状", status=r_now.status_code, 出站到的号=acc_vendor.tokens_seen())
    assert r_now.status_code == 400 and acc_vendor.tokens_seen() == [TOKEN_SMALL]

    # —— 加上输入维判据后 ——
    orig = Scheduler._capacity_reject

    def with_input_dim(self, ir, resource):
        base = orig(self, ir, resource)
        if base is not None or ir.endpoint != "chat":
            return base
        spec = getattr(self.runtime, "resource_specs", {}).get(
            (resource.rid, resource.vendor_model))
        cap = getattr(spec, "max_input", None) if spec is not None else None
        if cap is None:
            return None                       # 未知 = 不拦（Q33 既有纪律）
        est, _ = estimate_usage(ir.body, "")
        if est <= cap:
            return None
        return f"估算输入 {est} > 该资源最大输入 {cap} ⇒ 承载不了，换下一条"

    monkeypatch.setattr(Scheduler, "_capacity_reject", with_input_dim)
    acc_vendor.requests.clear()
    gw2 = await make_gw(cfg)
    r_gate = await hclient.post(f"{gw2.base_url}/v1/chat/completions",
                                json=text_body("gw-cap-model", prompt_chars=1_200_000,
                                               max_tokens=64))
    await gw2.drain_events()
    ev = gw2.read_events()[-1]
    say("M2-加判据后", status=r_gate.status_code, 出站到的号=acc_vendor.tokens_seen(),
        switch_count=ev["switch_count"], attempts=ev["resource_attempts"])
    assert r_gate.status_code == 200
    assert acc_vendor.tokens_seen() == [TOKEN_BIG]      # 换号成功，客户端不再吃 400
    assert ev["switch_count"] == 0                      # 避开不是故障


