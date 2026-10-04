"""Qoder wasm 签名桥的契约测试（`upstream/qoder/wasm_signer.py` + `qoder_bridge.mjs`）。

三层判据，逐层收紧：

1. **装配面**（零外部依赖）：环境变量没配 ⇒ `SIGNER_FACTORY` 保持 `None` 且原因可操作；
   配齐 ⇒ 注入。钉住"未配置时与接线前逐字节一致"这条承诺。
2. **往返面**（**假 node** = 一个只讲 NDJSON 的 Python 桩）：出帧内容、头**原样透传**、
   错误脱敏、产物不完整/进程退出都是可读失败而不是悬挂、并发按 id 配对。
   签名器自己的逻辑全在这一层可测，不需要客户端 wasm 存在。
3. **真 wasm 面**（opt-in：设 `MGW_QODER_WASM_GLUE_TEST` 才跑；**零网络**）：客户端
   wasm 能签出 `Bearer COSY.` + 密文体，并与上游参考实现的 builder **逐键比对**
   （`test_stage_b_payload_equals_the_reference_builder`，两边各写字面量）。
   ⚠️ 更正（2026-10-04 R4）：这条网起初写成 `history: ours["messages"]` 那种"自己喂给
   自己"的形态，结构性抽不到 stage A 的派生错；且它当日"抓到系统提示住错位置"的结论
   **是误读**（要看调用方 `qoder-adapter.ts` 怎么喂，不能只看 builder 怎么用），该改动
   已撤销。stage A 的形状规则另有主人：`tests/unit/test_qoder_ask_shape.py`；
   桥本体（真 node 跑 `.mjs`）另有 `tests/unit/test_qoder_bridge_mjs.py`。

⚠️ 第 3 层用**假身份**（`probe-*`）：签名是纯本地计算，不打上游、不消耗任何人额度。
它验的是"桥接得通 + 形态一致"，**不是**"服务端接受我们的签名"（那要一次真实 200，
仍未验 —— 不许据本文件宣称 Qoder 转发已交付）。
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from model_gateway.core.errors import UpstreamError
from model_gateway.upstream.qoder import ask as ask_mod
from model_gateway.upstream.qoder import out as qoder_out
from model_gateway.upstream.qoder import wasm_signer
from model_gateway.upstream.qoder.config import QODER, QODER_CN

#: 第 3 层的开关（刻意不复用生产变量：conftest 会抹掉它，以免判据随本机状态漂移）
REAL_ENV = "MGW_QODER_WASM_GLUE_TEST"

UID = "u-1"
TOKEN = "secret-token-xyz"
MACHINE = "m-1"


def _glue(tmp_path: Path, *, js: bool = True, wasm: bool = True) -> Path:
    d = tmp_path / "glue"
    d.mkdir(parents=True, exist_ok=True)
    if js:
        (d / "qoder-wasm.js").write_text("export {}\n", encoding="utf-8")
    if wasm:
        (d / "qoder-auth-wasm.wasm").write_bytes(b"\x00asm\x01\x00\x00\x00")
    return d


def _cred(**over) -> dict:
    return {"uid": UID, "security_oauth_token": TOKEN, **over}


def _payload(key: str = "qfmodel") -> dict:
    p = ask_mod.build_infer_payload({"messages": [{"role": "user", "content": "hi"}]}, key)
    return p


# ============================================================ 1. 装配面 ======

def test_unset_env_means_seam_stays_open(tmp_path, monkeypatch):
    monkeypatch.delenv(wasm_signer.GLUE_ENV, raising=False)
    d, why = wasm_signer.resolve_glue_dir()
    assert d is None and wasm_signer.GLUE_ENV in why, "未配置要点名是哪个环境变量"
    impl, why2 = wasm_signer.build_factory()
    assert impl is None and why2 == why


def test_missing_half_the_files_is_named(tmp_path, monkeypatch):
    d = _glue(tmp_path, wasm=False)
    monkeypatch.setenv(wasm_signer.GLUE_ENV, str(d))
    resolved, why = wasm_signer.resolve_glue_dir()
    assert resolved is None and "qoder-auth-wasm.wasm" in why
    assert "qoder-wasm.js" not in why.split("缺少", 1)[1], "在册的那份不该被一起报成缺件"


def test_dir_not_exists(tmp_path, monkeypatch):
    monkeypatch.setenv(wasm_signer.GLUE_ENV, str(tmp_path / "nope"))
    resolved, why = wasm_signer.resolve_glue_dir()
    assert resolved is None and "不存在" in why


def test_install_without_env_leaves_fail_closed_path(monkeypatch):
    monkeypatch.delenv(wasm_signer.GLUE_ENV, raising=False)
    monkeypatch.setattr(qoder_out, "SIGNER_FACTORY", None)
    reason = wasm_signer.install()
    assert reason and wasm_signer.GLUE_ENV in reason
    assert qoder_out.SIGNER_FACTORY is None, "未配置时缝必须仍是未注入（NOT_WIRED_HINT 那条路）"


def test_install_injects_the_factory(tmp_path, monkeypatch):
    monkeypatch.setenv(wasm_signer.GLUE_ENV, str(_glue(tmp_path)))
    monkeypatch.setenv(wasm_signer.NODE_ENV, sys.executable)   # 装配只判"在位"，不起进程
    monkeypatch.setattr(qoder_out, "SIGNER_FACTORY", None)
    assert wasm_signer.install() == ""
    assert qoder_out.SIGNER_FACTORY is wasm_signer.factory


def test_install_refuses_without_node(tmp_path, monkeypatch):
    """没有 node ⇒ **不算已接线**。否则界面看到"已注入"、第一次请求才炸，是假态。"""
    monkeypatch.setenv(wasm_signer.GLUE_ENV, str(_glue(tmp_path)))
    monkeypatch.setenv(wasm_signer.NODE_ENV, str(tmp_path / "not-node"))
    monkeypatch.setattr(qoder_out, "SIGNER_FACTORY", None)
    assert "node" in wasm_signer.install()
    assert qoder_out.SIGNER_FACTORY is None


@pytest.mark.parametrize("field", ["uid", "security_oauth_token", "machine_id"])
def test_missing_identity_field_fails_closed(field, tmp_path):
    cred, meta = _cred(), {"machine_id": MACHINE}
    if field == "machine_id":
        meta = {}
    else:
        cred = {k: v for k, v in cred.items() if k != field}
    with pytest.raises(UpstreamError) as e:
        wasm_signer.make_signer(QODER, "https://api2.qoder.sh", cred, meta,
                                glue_dir=tmp_path, node_bin=sys.executable)
    assert field in str(e.value), "文案必须点名缺哪个字段，否则用户无法定位"
    # 🔴 方向判据（R1 B-4）：**这一个号**残缺 ⇒ 允许换号，健康号补位。
    # 置 no_failover=True 就是一个残缺号终止整条请求，正是 Q35-③ 红线那个形状。
    assert e.value.no_failover is not True, "残缺号不许终止整条请求（换号无帮助的是基础设施级失败）"


# ============================================================ 2. 往返面 ======

_STUB = """#!@PY@
import json, os, sys

record = os.environ.get("STUB_RECORD")
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    if record:
        with open(record, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(req, ensure_ascii=False) + "\\n")
    mode = req.get("mode") or os.environ.get("STUB_MODE") or "ok"
    if mode == "err":
        # 故意把凭据回显在 error 里：脱敏必须是**我方出口**的责任
        msg = "boom token=" + str(req.get("user", {}).get("securityOauthToken"))
        print(json.dumps({"id": req["id"], "ok": False, "error": msg}), flush=True)
        continue
    if mode == "incomplete":
        print(json.dumps({"id": req["id"], "ok": True,
                          "result": {"url": "https://x/y", "headers": {}}}), flush=True)
        continue
    if mode == "die":
        sys.exit(3)
    print(json.dumps({
        "id": req["id"], "ok": True,
        "result": {
            "url": req["host"] + "/algo/api/v2/service/pro/sse/agent_chat_generation",
            "headers": {"Authorization": "Bearer COSY.SIGNED",
                        "X-Model-Key": req["modelKey"],
                        "Cosy-MachineId": req["machineId"]},
            "body": "CIPHER:" + json.dumps(req["payload"], ensure_ascii=False)[:40],
        }}), flush=True)
"""


@pytest.fixture
def stub_node(tmp_path, monkeypatch):
    p = tmp_path / "fake-node"
    p.write_text(_STUB.replace("@PY@", sys.executable), encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("STUB_RECORD", str(tmp_path / "frames.jsonl"))
    return str(p)


def _frames(tmp_path) -> list[dict]:
    f = tmp_path / "frames.jsonl"
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x] \
        if f.exists() else []


def _signer(tmp_path, stub_node, cfg=QODER, cred=None, meta=None):
    return wasm_signer.make_signer(cfg, "https://wrong.example.com", cred or _cred(),
                                   meta or {"machine_id": MACHINE},
                                   glue_dir=tmp_path, node_bin=stub_node)


async def test_frame_carries_our_payload_verbatim(tmp_path, stub_node):
    payload = _payload()
    signer = _signer(tmp_path, stub_node)
    try:
        await signer(payload)
    finally:
        await wasm_signer._bridge(tmp_path, stub_node).close()
    frame = _frames(tmp_path)[0]
    assert frame["op"] == "prepare"
    assert frame["payload"] == payload, "桥不许改写/重造明文（明文只有一份实现：ask.py）"
    assert frame["modelKey"] == "qfmodel" == payload["model_config"]["key"], \
        "签名参数里的目录 key 必须与请求体同源"
    assert frame["source"] == payload["model_config"]["source"]
    assert frame["user"] == {"uid": UID, "securityOauthToken": TOKEN}
    assert frame["machineId"] == MACHINE


async def test_host_comes_from_region_config_not_from_resource_base_url(tmp_path, stub_node):
    """资源里填公开端点也不能把签名打到那里（两站/两端互不串用，§22.4 第一条）。"""
    try:
        await _signer(tmp_path, stub_node, cfg=QODER_CN)(_payload())
    finally:
        await wasm_signer._bridge(tmp_path, stub_node).close()
    host = _frames(tmp_path)[0]["host"]
    assert host == QODER_CN.encrypted_infer_base and "wrong.example.com" not in host


async def test_account_key_separates_accounts_and_regions(tmp_path, stub_node):
    try:
        await _signer(tmp_path, stub_node)(_payload())
        await _signer(tmp_path, stub_node, cred=_cred(uid="u-2"))(_payload())
        await _signer(tmp_path, stub_node, cfg=QODER_CN)(_payload())
    finally:
        await wasm_signer._bridge(tmp_path, stub_node).close()
    keys = [f["accountKey"] for f in _frames(tmp_path)]
    assert len(set(keys)) == 3, f"一号一上下文；两站更不能共用：{keys}"
    assert keys[2].startswith("qodercn:") and keys[0].startswith("qoder:")


async def test_signed_headers_pass_through_untouched(tmp_path, stub_node):
    signer = _signer(tmp_path, stub_node)
    try:
        req = await signer(_payload())
    finally:
        await wasm_signer._bridge(tmp_path, stub_node).close()
    assert req.headers["Authorization"] == "Bearer COSY.SIGNED", \
        "覆盖成普通 Bearer 必回 403 Signature invalid（DSH qoder-adapter.ts:743）"
    assert req.headers["Cosy-MachineId"] == MACHINE
    assert req.url.startswith(QODER.encrypted_infer_base)


async def test_error_text_is_scrubbed_at_our_exit(tmp_path, stub_node, monkeypatch):
    """桩把 token 回显在 error 里 ⇒ 出口必须剔干净（§22.2 不变式②：日志/响应都不许带凭据）。

    🔴 走**签名器**这条真实路径，不绕过它直连 bridge —— 脱敏发生在 sign() 里，
    直连 bridge 测到的是另一个出口（那样这条判据就是空判据）。
    """
    monkeypatch.setenv("STUB_MODE", "err")
    with pytest.raises(UpstreamError) as e:
        await _signer(tmp_path, stub_node)(_payload())
    assert TOKEN not in str(e.value) and "***" in str(e.value), str(e.value)
    await wasm_signer._bridge(tmp_path, stub_node).close()


async def test_incomplete_product_is_readable_not_silently_empty(tmp_path, stub_node,
                                                                monkeypatch):
    """签名器给了 url+headers 但**没有密文体** ⇒ 当场失败，绝不发一个空 body 给上游。"""
    monkeypatch.setenv("STUB_MODE", "incomplete")
    with pytest.raises(UpstreamError) as e:
        await _signer(tmp_path, stub_node)(_payload())
    assert "不完整" in str(e.value)
    await wasm_signer._bridge(tmp_path, stub_node).close()


async def test_subprocess_exit_is_a_failure_not_a_hang(tmp_path, stub_node, monkeypatch):
    """子进程直接退出：等待者必须拿到可读异常（超时兜底之外还要有 EOF 兜底）。"""
    monkeypatch.setenv("STUB_MODE", "die")
    with pytest.raises(UpstreamError):
        await asyncio.wait_for(_signer(tmp_path, stub_node)(_payload()),
                               timeout=wasm_signer.SIGN_TIMEOUT)
    await wasm_signer._bridge(tmp_path, stub_node).close()


async def test_concurrent_requests_pair_by_id(tmp_path, stub_node):
    """三条并发各拿回**自己**那份密文（配错 id = 把 A 的请求结果发给 B 的调用方）。"""
    signers = [_signer(tmp_path, stub_node) for _ in range(3)]
    payloads = [_payload(f"key-{i}") for i in range(3)]
    try:
        done = await asyncio.gather(*[s(p) for s, p in zip(signers, payloads)])
    finally:
        await wasm_signer._bridge(tmp_path, stub_node).close()
    got = [r.headers["X-Model-Key"] for r in done]
    assert got == [f"key-{i}" for i in range(3)], got


async def test_account_key_carries_a_token_fingerprint(tmp_path, stub_node):
    """🔴 R1 B-2 的主人（R4 BL-1：这条先前只写在台账里、仓内并不存在）。

    本仓 qoder 号会**续期**（`flow.apply_refresh`），而 wasm 上下文在构造时就把身份材料
    算进去了 ⇒ 键里必须带令牌指纹。退化检查：指纹写死成常量、或把令牌原文直接当键，
    本条都会红（前者两键相等，后者违反"凭据只以短哈希出现"）。
    """
    try:
        await _signer(tmp_path, stub_node)(_payload())
        await _signer(tmp_path, stub_node, cred=_cred(security_oauth_token="token-轮换后"))(
            _payload())
    finally:
        await wasm_signer._bridge(tmp_path, stub_node).close()
    keys = [f["accountKey"] for f in _frames(tmp_path)]
    assert keys[0] != keys[1], f"令牌换了而键没换 = 续期后永久用旧身份签：{keys}"
    assert TOKEN not in keys[0] and "token-轮换后" not in keys[1], f"键里只许放指纹：{keys}"
    tail = keys[0].rsplit(":", 1)[1]
    assert len(tail) == 12 and all(c in "0123456789abcdef" for c in tail), \
        f"指纹应是 sha256 短摘要（12 位十六进制）：{tail}"


async def test_infra_level_failures_still_refuse_failover(tmp_path, stub_node, monkeypatch):
    """方向 B（R1 B-4 的另一半）：**单号残缺**可换号，**基础设施级**失败不许换号空转。

    只钉一边等于没钉方向：换号对一个没装桥的机器毫无帮助，白烧一整轮池子才把错误
    交给用户；而把一个残缺号也标成 no_failover，就是"一个坏号终止整条请求"。
    """
    monkeypatch.setenv(wasm_signer.GLUE_ENV, str(tmp_path / "桥目录已消失"))
    with pytest.raises(UpstreamError) as e:
        wasm_signer.factory(QODER, "https://api2.qoder.sh", _cred(), {"machine_id": MACHINE})
    assert e.value.no_failover is True, "签名器整体不可用 ⇒ 换号无帮助"
    monkeypatch.setenv(wasm_signer.GLUE_ENV, str(_glue(tmp_path)))
    monkeypatch.setenv(wasm_signer.NODE_ENV, str(tmp_path / "没有这个-node"))
    with pytest.raises(UpstreamError) as e2:
        wasm_signer.factory(QODER, "https://api2.qoder.sh", _cred(), {"machine_id": MACHINE})
    assert e2.value.no_failover is True and "node" in str(e2.value)


# ======================================================= 3. 真 wasm 面 =======

def _real_glue() -> Path | None:
    raw = os.environ.get(REAL_ENV, "").strip()
    if not raw:
        return None
    return wasm_signer.resolve_glue_dir({wasm_signer.GLUE_ENV: raw})[0]


real = pytest.mark.skipif(
    _real_glue() is None,
    reason=f"未设 {REAL_ENV}（真 wasm 一层是 opt-in：需要本机存在客户端 wasm 桥目录）")


@real
async def test_real_wasm_produces_cosy_signature_and_encrypted_body(tmp_path):
    glue = _real_glue()
    node = wasm_signer.resolve_node() or "node"
    signer = wasm_signer.make_signer(
        QODER, "", {"uid": "probe-uid", "security_oauth_token": "probe-token"},
        {"machine_id": "probe-machine"}, glue_dir=glue, node_bin=node)
    payload = ask_mod.build_infer_payload(
        {"messages": [{"role": "system", "content": "你是助手"},
                      {"role": "user", "content": "说一句话"}]}, "qfmodel",
        is_reasoning=True, display_name="Qwen3.8-Flash")
    try:
        req = await signer(payload)
    finally:
        await wasm_signer._bridge(glue, node).close()
    assert req.url.startswith(QODER.encrypted_infer_base)
    assert req.headers["Authorization"].startswith("Bearer COSY.")
    assert "Cosy-Key" in req.headers and "X-Model-Key" in req.headers
    with pytest.raises(json.JSONDecodeError):
        json.loads(req.body)                       # 密文不是明文 JSON
    assert "说一句话" not in req.body and "你是助手" not in req.body, "明文泄露进密文"


@real
async def test_stage_b_payload_equals_the_reference_builder(tmp_path):
    """🔴 反漂移判据（**只管 stage B**）：同一份输入，我方 `build_infer_payload` 与参考
    实现 `buildQoderInferPayload` 的产物逐键相等。

    这条网能红的前提是"两边各拿一份**独立字面量**"：`ask.history` / `ask.tools` 是
    手写的（等于参考实现 `buildQoderHistory`/`buildQoderTools` 应有的产物），
    **不是**从我方产物里抄回去的 —— R3 复算指出我原先那种 `history: ours["messages"]`
    的喂法把 `history_of`/`tools_of` 的派生错误结构性遮掉了（自己喂给自己，永不红）。
    现在 stage A 若派生错，`messages`/`tools` 两键当场分叉。

    它**不覆盖**的层面另有主人：stage A 的形状规则在 `tests/unit/test_qoder_ask_shape.py`
    （逐条对着 `qoder-adapter.ts:211-364` 钉），本文件只钉 builder 那一层。
    随机键（三个 id + `session_id`）不参与比对。
    """
    glue = _real_glue()
    node = wasm_signer.resolve_node() or "node"
    bridge = wasm_signer._bridge(glue, node)
    body = {"messages": [{"role": "system", "content": "你是助手"},
                         {"role": "user", "content": "第一问"},
                         {"role": "assistant", "tool_calls": [
                             {"id": "c1", "type": "function",
                              "function": {"name": "get_time", "arguments": "{}"}}]},
                         {"role": "tool", "tool_call_id": "c1", "content": "09:00"},
                         {"role": "user", "content": "谢谢"}],
            "tools": [{"type": "function", "function": {
                "name": "get_time", "description": "取时间",
                "parameters": {"type": "object", "properties": {}}}}],
            "max_tokens": 512}
    ours = ask_mod.build_infer_payload(body, "qfmodel", is_reasoning=True, is_vl=False,
                                       display_name="Qwen3.8-Flash", max_input_tokens=200000)
    # ↓ 手写：与参考实现**应有的**产物同形（system 留在历史里，见 ask.system_prompt_of 头注）
    literal_history = [
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "第一问"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "get_time", "arguments": "{}"}}]},
        {"role": "tool", "content": "09:00", "tool_call_id": "c1"},
        {"role": "user", "content": "谢谢"}]
    literal_tools = [{"type": "function", "function": {
        "name": "get_time", "description": "取时间",
        "parameters": {"type": "object", "properties": {}}}}]
    try:
        ref = (await bridge.request({"op": "build", "ask": {
            "modelKey": "qfmodel", "userText": "谢谢",
            "isReasoning": True, "history": literal_history, "tools": literal_tools,
            "maxTokens": 512, "isVl": False, "displayName": "Qwen3.8-Flash",
            "maxInputTokens": 200000, "business": {"type": "agent"}}}))["payload"]
    finally:
        await bridge.close()
    random_keys = {"request_id", "request_set_id", "chat_record_id", "session_id"}
    a = {k: v for k, v in ours.items() if k not in random_keys}
    b = {k: v for k, v in ref.items() if k not in random_keys}
    only_ours = sorted(set(a) - set(b))
    only_ref = sorted(set(b) - set(a))
    diff = sorted(k for k in set(a) & set(b) if a[k] != b[k])
    assert not (only_ours or only_ref or diff), (
        f"我方明文与参考实现分叉 | 只在我方={only_ours} 只在参考={only_ref} 不等={diff}")
    assert a["business"] == {"type": "agent"}, "business 必填（缺了恒落故障节点，实测结论）"



