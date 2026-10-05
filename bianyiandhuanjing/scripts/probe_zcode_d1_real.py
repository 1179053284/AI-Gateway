#!/usr/bin/env python3
"""D1 真实最小实测 —— **用户 2026-10-05 批准的唯一一次真实 zcode 出站**（1 个号 × 2 条推理）。

问题：zcode 的模型转发腿「JWT 直连、不注入每请求验证码」到底成不成立（`docs/research/24 §2-D1`）。
仓库里这句话挂了很久：`upstream/zcode/out.py:30-32` 写"真实可用性待 D1 实测后裁决"，
`main.py` 的横幅写"zcode 直连前提未验证（D1），当前不代表 zcode 转发可用"。
本轮 P5 要把它改成 call-time fail-closed，而**顺序必须先测后建** —— P5 一旦落地这条腿会自己拒发，
就永远测不到 D1 了。

🔴 四条硬护栏（写在代码里，不是写在注释里）：
1. **总出站 = 2 条推理**：`REQUESTS` 常量写死 2；额度腿与领取腿一律关掉
   （`claim_interval_seconds: 0` ⇒ 运营循环根本不起；`quota_net: false`）。
2. **隔离数据根**：`MG_CONFIG` / `MGW_ZCODE_ACCOUNTS` / 两个锁目录全部指向 /tmp，
   且启动后**断言枚举到的账号数 == 1**（不是 0、更不是实盘那 35 个）——
   本仓已归档那条「只传 config_path= 不够，账号根会回落真实 coding/data/」的坑。
3. **不碰实盘配置与实盘账号库**：账号目录是**只读拷贝**单个账号，实盘一个字节都不写。
4. 需要显式 `--i-approve-real-outbound` 才发起，否则只打印计划。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "coding"     # 被测代码 = 本分支工作树
sys.path.insert(0, str(ROOT))

#: 🔴 账号**源数据**在实盘仓库（工作树里没有 data/，它是 gitignore 的）——
#: 这里只读拷贝一个账号到 /tmp，实盘目录本身一个字节都不写。
MAIN_REPO = Path("/Users/w/Desktop/Model-Gateway/coding")
REAL_ACCOUNTS = MAIN_REPO / "data/upstream/zcode/accounts"
ACCOUNT = "1179053284qqcom"          # 实盘读数：state=available、remaining=100000000
MODEL = "glm-5.3-flash"
VENDOR_MODEL = "GLM-5.3-Flash"
REQUESTS = 2                          # 🔴 写死：1 非流式 + 1 流式
PROMPT = "只回两个字，不要思考：你好"
MAX_TOKENS = 2048                     # 带思考的模型给 256 会把预算全花在 reasoning ⇒ 假空返回


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build_isolated(tmp: Path) -> Path:
    """只读拷贝**一个**账号到临时账号根，并写一份最小配置（额度腿/领取腿全关）。"""
    src = REAL_ACCOUNTS / ACCOUNT
    dst_root = tmp / "accounts/zcode"
    dst_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst_root / ACCOUNT, symlinks=True,
                    ignore=shutil.ignore_patterns("logs"))

    conf_dir = tmp / "conf"
    conf_dir.mkdir(parents=True, exist_ok=True)
    cfg = conf_dir / "config.yaml"
    cfg.write_text(f"""resources:
  - id: res-d1
    name: {ACCOUNT}
    vendor: ZCode
    account: {ACCOUNT}
    product: zcode
    account_ref: {ACCOUNT}
    protocol: anthropic
    preset: ""
    base_url: https://zcode.z.ai/api/v1/zcode-plan/anthropic
    api_key: ""
    enabled: true
    access_mode: plan
models:
  - name: {MODEL}
    endpoint: chat
    enabled: true
    resources:
      - resource: res-d1
        model: {VENDOR_MODEL}
        enabled: true
scheduling:
  max_active_per_model: 1
  fail_threshold: 2
  retry_per_request: 1
  retry_backoff_seconds: 0.0
  quota_retry: 0
  cooldown_seconds: 60
  cooldown_seconds_plan: 60
gateway:
  host: 127.0.0.1
  port: {free_port()}
  attempt_timeout_seconds: 60
  request_total_budget_seconds: 120
  heartbeat_seconds: 15
  access_tokens: []
  zcode:
    quota_net: false
    claim_interval_seconds: 0
    fingerprint: false
    proxy: ""
""", encoding="utf-8")

    os.environ["MG_CONFIG"] = str(cfg)
    os.environ["MGW_ZCODE_ACCOUNTS"] = str(dst_root)
    os.environ["MGW_OPS_LOCK_DIR"] = str(tmp / "ops-locks")
    os.environ["MGW_ACCOUNTS_LOCK_DIR"] = str(tmp / "acct-locks")
    os.environ.pop("MGW_QODER_WASM_GLUE", None)
    os.environ.pop("MGW_QODER_WASM_NODE", None)
    return cfg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--i-approve-real-outbound", action="store_true",
                    help=f"确认发起 {REQUESTS} 条真实 zcode 推理（账号 {ACCOUNT}）")
    args = ap.parse_args()

    import uvicorn
    from model_gateway.accounts import store
    from model_gateway.main import create_app

    tmp = Path("/tmp/mgw-d1")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    cfg = build_isolated(tmp)

    listed = store.list_accounts("zcode")
    print(f"账号根 = {os.environ['MGW_ZCODE_ACCOUNTS']}")
    print(f"枚举到的 zcode 账号 = {len(listed)} {listed}")
    names = [a if isinstance(a, str) else getattr(a, "name", str(a)) for a in listed]
    assert names == [ACCOUNT], f"隔离面破了：账号根不是只有这一个号，而是 {names}"

    if not args.i_approve_real_outbound:
        print("\n[未发起] 只打印计划。加 --i-approve-real-outbound 才会真打 "
              f"{REQUESTS} 条推理（非流式 1 + 流式 1，max_tokens={MAX_TOKENS}）。")
        return

    app = create_app(config_path=cfg, usage_dir=tmp / "usage", enums_path=tmp / "enums.yaml")
    port = int(cfg.read_text(encoding="utf-8").split("  port: ")[1].split("\n")[0])
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(500):
        if server.started:
            break
        time.sleep(0.02)
    assert server.started, "网关未起来"
    base = f"http://127.0.0.1:{port}"
    print(f"网关 :{port}（隔离根 {tmp}；运营循环已关：claim_interval_seconds=0）\n")

    import httpx

    results = []
    for stream in (False, True):
        body = {"model": MODEL, "max_tokens": MAX_TOKENS, "stream": stream,
                "messages": [{"role": "user", "content": PROMPT}]}
        t0 = time.time()
        try:
            with httpx.Client(timeout=httpx.Timeout(90.0), trust_env=False) as c:
                if not stream:
                    r = c.post(f"{base}/v1/chat/completions", json=body)
                    text = r.text[:600]
                else:
                    parts, err = [], None
                    with c.stream("POST", f"{base}/v1/chat/completions", json=body) as r:
                        code = r.status_code
                        for line in r.iter_lines():
                            if not line.startswith("data: "):
                                continue
                            payload = line[6:]
                            if payload.strip() in ("", "[DONE]"):
                                continue
                            try:
                                d = json.loads(payload)
                            except ValueError:
                                err = payload[:200]
                                continue
                            if d.get("error"):
                                err = json.dumps(d["error"], ensure_ascii=False)[:300]
                            for ch in (d.get("choices") or []):
                                parts.append(((ch.get("delta") or {}).get("content") or ""))
                    text = f"SSE 正文={(''.join(parts))[:300]!r} 错误帧={err!r}"
                    r = None
                status = code if stream else r.status_code
        except Exception as e:  # noqa: BLE001 — 读数原样交出去
            status, text = f"EXC {type(e).__name__}", str(e)[:400]
        results.append((stream, status, round(time.time() - t0, 2), text))
        print(f"--- {'流式' if stream else '非流式'} → HTTP {status}（{results[-1][2]}s）")
        print(f"    {text}\n")

    day = time.strftime("%Y%m%d")
    ev_path = tmp / f"usage/events-{day}.jsonl"
    if ev_path.exists():
        for line in ev_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            print(f"[事件行] status={e.get('status')} stream={e.get('stream')} "
                  f"final={e.get('final_resource')} attempts={e.get('resource_attempts')} "
                  f"switch={e.get('switch_count')} in/out={e.get('input_tokens')}/"
                  f"{e.get('output_tokens')} usage_source={e.get('usage_source')} "
                  f"err={str(e.get('error_summary'))[:260]!r}")
    server.should_exit = True
    time.sleep(0.3)
    print(f"\n总真实出站条数 = {REQUESTS}（非流式 1 + 流式 1）。台账以此行为准。")


if __name__ == "__main__":
    main()
