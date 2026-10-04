"""生产要执行的那 193 行 `qoder_bridge.mjs` 自己的判据（R1 B-3 补的覆盖缺口）。

为什么单独一支文件：此前"假 node"是 **Python 桩**，桥脚本本体在默认判据里一行都没执行过
⇒「形状不符要点名缺哪个符号」「一号一上下文」两句宣称**没有主人**（宣称写进注释、
注释写进 `out.py` 模块头，就成了假账）。这里用**假 glue**（tmp 目录里一份几十行的
ESM 替身 + 一个空 `qoder-auth-wasm.wasm`）把真桥跑起来，只测**我们的**那层逻辑：
NDJSON 往返、形状校验、上下文缓存、行上限、配对。

与 `test_qoder_wasm_signer.py` 的分工：那边测 Python 侧契约（含真 wasm 的 opt-in 一层），
这边测 Node 侧桥本体；两边合起来才盖住"生产实际执行的那份代码"。
"""

from __future__ import annotations

import asyncio
import stat
import sys
from pathlib import Path

import pytest

from model_gateway.core.errors import UpstreamError
from model_gateway.upstream.qoder import wasm_signer
from model_gateway.upstream.qoder.config import QODER

#: 假 glue 的公共部分（`create()` 产物暴露 `{g, context}` + 五个 wasm 符号）
_THROWER_HEAD = """
export function buildQoderInferPayload(ask) { return { echo: ask }; }
export class QoderEncryptedInfer {
  static async create(options) {
    const exports = {
      qodercontext_prepareInferRequest: () => 7,
      requestresult_headers: () => 8,
      requestresult_url: () => 9,
      requestresult_body: () => 10,
      __wbindgen_add_to_stack_pointer: (n) => 1008,
    };
    const g = {
      exports,
      view: () => ({ getInt32: (off) => (off === 1008 ? 2048 : 11) }),
      writeString: () => 1,
      lastLength: () => 2,
      readString: () => 'ok',
      takeObject: () => { throw new Error('boom-in-glue'); },
      callPointer: (fn) => fn(1008),
    };
    return { g, context: 42, metadata: options.metadata, host: options.host };
  }
}
"""

FAKE_GLUE_THROWER = _THROWER_HEAD

#: 假 glue：满足桥要求的形状（`create()` 产物暴露 `{g, context}` + 五个 wasm 符号）
FAKE_GLUE = """
export function buildQoderInferPayload(ask) { return { echo: ask }; }
export class QoderEncryptedInfer {
  static async create(options) {
    const exports = {
      qodercontext_prepareInferRequest: () => 7,
      requestresult_headers: () => 8,
      requestresult_url: () => 9,
      requestresult_body: () => 10,
      __wbindgen_add_to_stack_pointer: (n) => 1008,
    };
    const g = {
      exports,
      view: () => ({ getInt32: (off) => (off === 1008 ? 2048 : 11) }),
      writeString: () => 1,
      lastLength: () => 2,
      readString: () => READS(),
      takeObject: () => new Map([["Authorization", "Bearer COSY.FAKE"],
                                 ["X-Model-Key", "from-glue"]]),
      callPointer: (fn) => fn(1008),
    };
    return { g, context: 42, metadata: options.metadata, host: options.host };
  }
}
"""

node = pytest.mark.skipif(wasm_signer.resolve_node() is None, reason="本机没有 node")


def _glue(tmp_path: Path, *, body: str = FAKE_GLUE) -> Path:
    d = tmp_path / "glue-real"
    d.mkdir(parents=True, exist_ok=True)
    (d / "qoder-wasm.js").write_text("const READS = () => 'ok';\n" + body, encoding="utf-8")
    (d / "qoder-auth-wasm.wasm").write_bytes(b"\x00asm\x01\x00\x00\x00")
    return d


def _frame(key: str = "qoder:u:m:fp") -> dict:
    return {"op": "prepare", "accountKey": key,
            "user": {"uid": "u", "securityOauthToken": "t"},
            "machineId": "m", "metadata": {"client_type": "5"},
            "host": "https://api2.qoder.sh", "payload": {"a": 1},
            "modelKey": "qfmodel", "source": "system"}


@node
async def test_bridge_round_trip_through_the_real_mjs(tmp_path):
    glue = _glue(tmp_path)
    bridge = wasm_signer._bridge(glue, wasm_signer.resolve_node())
    try:
        result = await bridge.request(_frame())
    finally:
        await bridge.close()
    assert result["headers"]["Authorization"] == "Bearer COSY.FAKE"
    assert result["url"] == "ok"           # readString 的返回值就是 url/body


@node
async def test_shape_mismatch_names_the_missing_symbol(tmp_path):
    """🔴 不认识产物形状时必须**点名缺哪一个**并拒绝服务。

    反例（曾经的真实状态）：把校验摘掉 → 裸 `TypeError: g.readString is not a function`
    流进用户文案，等于"红但不指路"；也不许在这种时候退回"让上游自己拼明文"。
    """
    glue = _glue(tmp_path, body=FAKE_GLUE.replace("readString: () => READS(),", "", 1))
    bridge = wasm_signer._bridge(glue, wasm_signer.resolve_node())
    try:
        with pytest.raises(UpstreamError) as e:
            await bridge.request(_frame())
        msg = str(e.value)
        # 🔴 必须同时判"这是**形状校验**给的答复"，不只判符号名在不在文案里：
        # 只 grep `g.readString` 的话，摘掉校验后裸 `TypeError: g.readString is not a
        # function` 也含这个串 ⇒ 判据恒绿、形同虚设（R4 BL-2 实测出的正是这一种）。
        assert "形状不符" in msg and "g.readString" in msg, msg
    finally:
        await bridge.close()


@node
async def test_export_mismatch_names_the_missing_wasm_symbol(tmp_path):
    glue = _glue(tmp_path, body=FAKE_GLUE.replace("requestresult_body: () => 10,", "", 1))
    bridge = wasm_signer._bridge(glue, wasm_signer.resolve_node())
    try:
        with pytest.raises(UpstreamError) as e:
            await bridge.request(_frame())
        msg = str(e.value)
        assert "形状不符" in msg and "g.exports.requestresult_body" in msg, msg
    finally:
        await bridge.close()


@node
async def test_one_context_per_account_key(tmp_path):
    """「一号一上下文」第一次有了主人：同 key 复用，换 key（含换令牌指纹）才新建。"""
    glue = _glue(tmp_path)
    bridge = wasm_signer._bridge(glue, wasm_signer.resolve_node())
    try:
        for key in ("qoder:u:m:fp1", "qoder:u:m:fp1", "qoder:u:m:fp2", "qodercn:u:m:fp1"):
            await bridge.request(_frame(key))
        info = await bridge.request({"op": "info"})
    finally:
        await bridge.close()
    assert info["accounts"] == 3, f"三个账号三份上下文（同 key 必须复用）：{info}"


@node
async def test_big_frame_survives_the_default_64kib_line_limit(tmp_path):
    """R1 B-1：整份密文一帧装完，asyncio 默认 64 KiB 会抛
    `ValueError: Separator is not found, and chunk exceed the limit` ⇒ 读任务静默死亡。

    这条送 **1.5 MB** 的帧：必须正常返回。撤证 = 把 `limit=BRIDGE_LINE_LIMIT` 摘掉。
    """
    glue = _glue(tmp_path, body=FAKE_GLUE.replace("readString: () => READS(),",
                                                  "readString: () => 'B'.repeat(1500000),", 1))
    bridge = wasm_signer._bridge(glue, wasm_signer.resolve_node())
    try:
        result = await asyncio.wait_for(bridge.request(_frame()),
                                        timeout=wasm_signer.SIGN_TIMEOUT)
        assert len(result["body"]) > 1_000_000
    finally:
        await bridge.close()


@node
async def test_glue_exception_returns_an_error_frame_and_the_bridge_survives(tmp_path):
    """wasm 里抛异常 ⇒ 回一帧 `ok:false` + **桥不死**，下一条请求照常。

    真机理由：签名器是**全账号共用一条**子进程，一次上游无关的抖动如果把读循环带走，
    后面每个号都会跟着挂 20 秒（R1 B-1 那一族的另一面）。
    """
    glue = _glue(tmp_path, body=FAKE_GLUE_THROWER)
    bridge = wasm_signer._bridge(glue, wasm_signer.resolve_node())
    try:
        with pytest.raises(UpstreamError) as e:
            await bridge.request(_frame())
        assert "boom-in-glue" in str(e.value), str(e.value)
        # 桥还活着：换个不再抛的 glue 走不了（同进程），所以这里验"还能收一帧"即可
        info = await bridge.request({"op": "info"})
        assert "gluePath" in info
    finally:
        await bridge.close()


#: 子进程一启动就把**测试用的身份值**打到 stderr 后退出（值与用例里的 uid/machine 一致） —— 专门踩「stderr 尾巴进用户文案」那条例径
LEAK_GLUE = """
console.error("debug uid=1234567890123 machineId=probe-machine-987654321");
process.exit(1);
"""


@node
async def test_child_stderr_is_scrubbed_before_it_reaches_the_user(tmp_path):
    """R2 B-3 的主人（R4 条目 9：先前只有独立探针，仓内判据零覆盖）。

    被依赖方往 stderr 打调试行是**它的地盘**，管不着；而 `_pump` 的退出文案会拼上
    stderr 尾巴 ⇒ 那是凭据进响应体 / 事件 JSONL / 日志的第三条出口。
    出口必须按值剔干净（`***`），并且**不是**恰好被 `scrub_upstream_text` 的形状规则蒙对：
    这里用的是纯数字长 uid 与 UUID 形态的 machine_id，形状规则认不出来。
    """
    d = tmp_path / "leakglue"
    d.mkdir()
    (d / "qoder-wasm.js").write_text(LEAK_GLUE, encoding="utf-8")
    (d / "qoder-auth-wasm.wasm").write_bytes(b"")
    uid, machine = "1234567890123", "probe-machine-987654321"
    bridge = wasm_signer._bridge(d, wasm_signer.resolve_node())
    try:
        with pytest.raises(UpstreamError) as e:
            await bridge.request({"op": "prepare", "accountKey": "k",
                                  "user": {"uid": uid, "securityOauthToken": "probe-secret-token"},
                                  "machineId": machine, "metadata": {}, "host": "https://h",
                                  "payload": {}, "modelKey": "qfmodel", "source": "system"},
                                 secrets=(uid, "probe-secret-token", machine))
        msg = str(e.value)
        assert uid not in msg and machine not in msg, msg
        assert "***" in msg, f"应看到脱敏标记而不是原值：{msg}"
    finally:
        await bridge.close()


# ---------------------------------------------------------------- 配对与续期 ——


def _oob_node(tmp_path: Path) -> str:
    """**倒序**回帧的桩：配对一旦退化成 FIFO（取最早 pending），结果立刻串号。"""
    p = tmp_path / "oob-node"
    p.write_text("""#!PY@
import json, sys
seen = []
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    seen.append(json.loads(line))
    if len(seen) == 3:
        for req in reversed(seen):
            print(json.dumps({"id": req["id"], "ok": True, "result": {
                "url": "https://api2.qoder.sh/x",
                "headers": {"X-Model-Key": req["modelKey"]},
                "body": "C:" + req["modelKey"]}}), flush=True)
""".replace("PY@", sys.executable), encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(p)


async def test_out_of_order_frames_pair_by_id(tmp_path):
    from model_gateway.upstream.qoder import ask as ask_mod
    node_bin = _oob_node(tmp_path)
    signers = [wasm_signer.make_signer(QODER, "", {"uid": "u", "security_oauth_token": "t"},
                                       {"machine_id": "m"}, glue_dir=tmp_path,
                                       node_bin=node_bin) for _ in range(3)]
    payloads = []
    for i in range(3):
        pl = ask_mod.build_infer_payload({"messages": [{"role": "user", "content": "hi"}]},
                                         f"key-{i}")
        payloads.append(pl)
    try:
        done = await asyncio.gather(*[s(pl) for s, pl in zip(signers, payloads)])
    finally:
        await wasm_signer._bridge(tmp_path, node_bin).close()
    bodies = [r.body for r in done]
    assert bodies == ["C:key-0", "C:key-1", "C:key-2"], bodies
