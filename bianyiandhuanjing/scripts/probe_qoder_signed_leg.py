"""Qoder **加密端点**签名腿的一次出站探针（零消耗设计，判据是"错误码语义"不是"出词"）。

## 为什么打这一枪是**零消耗**的

用 `qoder`（国际版）那个号：2026-10-04 同日已实测它对公开端点的 39 个候选名 + 空 model +
畸形体**全部**回 `402 {"code":116,"error":"quota exceeded"}`（存档
`E2E-20261004-qoder-quota-probe.md`）⇒ 该号额度为 0，且额度门跑在生成之前。
所以这一枪**不可能产生计费输出**；它的价值恰恰在**不消耗**的前提下拿到判据：

| 回什么 | 判读 |
|---|---|
| `403` + `Signature invalid` / 业务码 `101`/`105` | 🔴 签名**不被接受** ⇒ 腿还没通，必须继续修 |
| `402` + `code=116`（或信封内层 110） | ✅ 签名**被判有效**（服务端已经走进额度门）⇒ 这是本探针要的证据 |
| `403` + `isQueued` / `code=10605` | ✅ 同上（进了排队分支，说明身份/签名已过） |
| `200` + 正常出词 | 说明该号**其实有额度**（与同日更早的证据矛盾）⇒ 本探针的零消耗前提不成立，如实上报 |

凭据**可用不可打印**：脚本只输出状态码、业务码、头名集合与逐字剔掉凭据后的短文本。
"""

from __future__ import annotations

import json
import sys

import httpx

import asyncio

from model_gateway.accounts import store
from model_gateway.upstream.qoder import ask as ask_mod
from model_gateway.upstream.qoder import envelope, wasm_signer
from model_gateway.upstream.qoder.config import require_qoder_family

PRODUCT = "qoder"          # 国际版：当日已证额度为 0
MODEL_KEY = "qfmodel"      # 加密端点认目录 key（公开端点不认）


def _short(text: str, secrets: tuple[str, ...], limit: int = 220) -> str:
    out = str(text or "")
    for s in secrets:
        if len(str(s)) >= 6:
            out = out.replace(str(s), "***")
    return out[:limit].replace("\n", "⏎")


def main() -> int:
    glue, why = wasm_signer.resolve_glue_dir()
    node = wasm_signer.resolve_node()
    if glue is None or node is None:
        print(f"签名器不可用：{why or '找不到 node'}")
        return 2
    cfg = require_qoder_family(PRODUCT)
    names = store.list_accounts(PRODUCT)
    if not names:
        print(f"账号目录里没有 {PRODUCT} 的号")
        return 2
    name = names[0]
    cred = store.load_credentials(PRODUCT, name)
    meta = store.load_meta(store.product_root(PRODUCT), name)
    signer = wasm_signer.make_signer(cfg, cfg.encrypted_infer_base, cred, meta,
                                     glue_dir=glue, node_bin=node)
    body = {"model": MODEL_KEY, "messages": [{"role": "user", "content": "说一个字"}],
            "max_tokens": 8}
    payload = ask_mod.build_infer_payload(body, MODEL_KEY, is_reasoning=False,
                                          display_name="Qwen3.8-Flash")
    signed = asyncio.run(signer(payload))      # 签名是本地计算：只起桥，不打上游

    secrets = (cred.get("uid", ""), cred.get("security_oauth_token", ""),
               meta.get("machine_id", ""), cred.get("access_token", ""))
    print(f"product={PRODUCT} account={name} glue={glue.name} node={node}")
    print(f"signed.url={_short(signed.url, secrets, 160)}")
    print(f"header 数={len(signed.headers)}  Authorization 形态="
          f"{_short(signed.headers.get('Authorization', '')[:16], secrets)}…")
    print(f"body 长度={len(signed.body)}  明文是否残留在体内={('说一个字' in signed.body)}")

    r = httpx.post(signed.url, headers=dict(signed.headers), content=signed.body,
                   timeout=60.0)
    print(f"HTTP {r.status_code}")
    print(f"响应头 content-type={r.headers.get('content-type', '')}")
    text = r.text
    code = ""
    try:
        code = str(json.loads(text).get("code", ""))
    except Exception:
        codes = [str(c) for c in envelope._BILLING_CODES] + [envelope.QUEUE_BUSINESS_CODE]
        code = next((c for c in codes if c in text or f'"{c}"' in text), "")
    print(f"业务码={code or '(未识别)'}")
    print(f"响应体（脱敏短文本）={_short(text, secrets)}")
    if r.status_code == 403 and ("ignature" in text or code in ("101", "105")):
        print("判读：签名**不被接受** ⇒ 加密腿未通")
        return 1
    if r.status_code in (200,) and ("delta" in text or "content" in text):
        print("判读：该号**其实有额度** ⇒ 本探针的零消耗前提不成立，如实上报")
        return 1
    if code == "116" or code == envelope.BILLING_BUSINESS_CODE \
            or envelope.looks_like_billing_error(text):
        print("判读：✅ **签名被判有效**（服务端已走进额度门，未产生任何计费输出）")
        return 0
    if envelope.parse_queue_info(text) is not None:
        print("判读：✅ 签名被判有效（进入排队分支）")
        return 0
    print("判读：不可归入上述四类 ⇒ 以原文为准人工判读")
    return 1


if __name__ == "__main__":
    sys.exit(main())
