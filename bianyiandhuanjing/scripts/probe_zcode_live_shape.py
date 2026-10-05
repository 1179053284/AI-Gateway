#!/usr/bin/env python3
"""实盘形状复刻探针：调网关 `glm-5.3-flash`，把**内部到底选了哪些号**逐条对账。

为什么要它：pytest 那 22 条判据是一条条孤立形状，看不清「一整轮下来池子怎么被用」。
本探针把实盘 16 个 zcode 号的**额度分档**（7 有余量 / 3 额度=0 / 5 无套餐 / 1 号开关关）
与实盘调度参数（x=8、y=2、m=3、冷却 60s / plan 18000s）一比一复刻到一台**隔离实例**上，
上游 = 本地假 ZCode（真实 HTTP，全程不打 zcode.z.ai），然后连续发请求，逐条读事件行对账：

    规则 A：额度=0 的号 ⇒ 不该被派到
    规则 B：号开关关 ⇒ 不该被派到
    规则 C：无套餐（上游明确说没有包）⇒ 不该被派到   ← 用户 2026-10-05 的裁定
    规则 D：反复失败的号 ⇒ 该被移出去冷却            ← 用户同一句里的「多次请求失败」

判据不进 pytest 收集范围（共享树上不留红行），只出读数。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODING = ROOT.parent / "coding"
sys.path.insert(0, str(CODING))

import httpx                                          # noqa: E402
import yaml                                           # noqa: E402
import uvicorn                                        # noqa: E402
from starlette.applications import Starlette          # noqa: E402
from starlette.requests import Request                # noqa: E402
from starlette.responses import JSONResponse          # noqa: E402
from starlette.routing import Route                   # noqa: E402

MODEL = "glm-5.3-flash"
VENDOR_MODEL = "GLM-5.3-Flash"
PATH = "/api/v1/zcode-plan/anthropic/v1/messages"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ6Yy0xIn0.c2ln"

# ---- 实盘 16 号的额度分档（来源：data/upstream/zcode/accounts/*/runtime.json，只读取） ----
LIVE_SHAPE = [
    # (账号, 号开关, 额度 remaining, 套餐状态)
    ("1179053284qqcom", True, 100_000_000, "available"),
    ("ayznq07clqvlsuzphkxpaptkcwuxianb", True, 50_151_426, "available"),
    ("bsu325alnctfkmlqioitokenbond", True, 100_000_000, "available"),
    ("enhbhfn2", True, 100_000_000, "available"),
    ("hclkm997", True, 100_000_000, "available"),
    ("ptygxlkx", True, 100_000_000, "available"),
    ("2632", True, 2_289_131, "available"),
    ("river4812", True, 0, "exhausted"),
    ("2721720949qqcom", True, 0, "exhausted"),
    ("15600155657phonelocal", True, 0, "exhausted"),
    ("bzdmlz6730zvoyaokjrifttkksyccfre", True, None, "no_plan"),
    ("1971962463qqcom", True, None, "no_plan"),
    ("pvtord11", True, None, "no_plan"),
    ("axxshx0129cusdrcioitokenbond", True, None, "no_plan"),
    ("15600155657163com", True, None, "no_plan"),
    ("zcode-ef91d043", False, None, "no_plan"),
]
TAG = {a: (f"{state}{'(开关关)' if not en else ''}") for a, en, _r, state in LIVE_SHAPE}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeZcode:
    """按 `X-Device-Mid` 分派行为的假 ZCode Plan 通道（与 pytest 那套同形）。"""

    def __init__(self) -> None:
        self.behavior: dict[str, dict] = {}
        self.hits: list[str] = []
        self.app = Starlette(routes=[Route(PATH, self._messages, methods=["POST"])])

    async def _messages(self, request: Request):
        mid = request.headers.get("x-device-mid", "")
        self.hits.append(mid)
        beh = self.behavior.get(mid, {"kind": "ok"})
        if beh["kind"] == "http":
            return JSONResponse(beh.get("payload") or {"code": 3012, "msg": "unusual activity"},
                                status_code=beh["status"])
        body = await request.json()
        return JSONResponse({"id": "m", "type": "message", "role": "assistant",
                             "model": body["model"],
                             "content": [{"type": "text", "text": "OK-" + mid[-6:]}],
                             "stop_reason": "end_turn",
                             "usage": {"input_tokens": 9, "output_tokens": 3}})


def serve(app, port: int) -> tuple[uvicorn.Server, threading.Thread]:
    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(cfg)
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(400):
        if server.started:
            break
        time.sleep(0.02)
    assert server.started, "服务未起来"
    return server, th


def build_gateway(tmp: Path, upstream_port: int) -> tuple[object, int]:
    """在 tmp 数据根上起一台网关（🔴 MG_CONFIG 必须显式设，否则账号根回落真实 `coding/data/`）。"""
    from model_gateway.accounts import store
    from model_gateway.main import create_app

    conf_dir = tmp / "mgw-conf"
    conf_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MG_CONFIG"] = str(conf_dir / "config.yaml")
    os.environ["MGW_OPS_LOCK_DIR"] = str(tmp / "ops-locks")

    mid_of = {}
    resources = []
    entries = []
    for i, (acct, enabled, _rem, _st) in enumerate(LIVE_SHAPE):
        rid = f"res-{i:02d}"
        mid = f"mid-{i:08d}"
        mid_of[mid] = acct
        store.commit_login("zcode", acct, {"zcodejwttoken": JWT, "device_mid": mid}, {})
        resources.append({"id": rid, "name": acct, "vendor": "ZCode", "account": acct,
                          "product": "zcode", "account_ref": acct, "protocol": "anthropic",
                          "preset": "",
                          "base_url": f"http://127.0.0.1:{upstream_port}/api/v1/zcode-plan/anthropic",
                          "api_key": "", "enabled": enabled, "access_mode": "plan"})
        entries.append({"resource": rid, "model": VENDOR_MODEL, "enabled": True})

    cfg_yaml = conf_dir / "config.yaml"
    cfg_yaml.write_text(yaml.safe_dump({
        "resources": resources,
        "models": [{"name": MODEL, "endpoint": "chat", "enabled": True,
                    "resources": entries}],
        "scheduling": {"max_active_per_model": 8, "fail_threshold": 2,
                       "retry_per_request": 3, "retry_backoff_seconds": 0.0,
                       "quota_retry": 2, "quota_backoff_base_seconds": 0.5,
                       "cooldown_seconds": 60, "cooldown_seconds_plan": 18000},
        "gateway": {"attempt_timeout_seconds": 5, "request_total_budget_seconds": 30},
    }, allow_unicode=True, sort_keys=False), encoding="utf-8")

    usage = tmp / "usage"
    app = create_app(config_path=cfg_yaml, usage_dir=usage, enums_path=tmp / "enums.yaml")
    port = free_port()
    server, _th = serve(app, port)
    return (server, app, mid_of, usage, resources), port


def hydrate_quota(rt, resources) -> None:
    """把实盘的额度分档灌进额度池 —— 走**生产者用的同一个函数**
    （`quota.apply_remaining_to_runtime`，联网腿与通用体调的也是它），
    而不是直调 `set_quota`，否则"资格位有没有接到闸门"这条就永远测不到。
    证据形状与实盘一致：**逐包 items**（zcode = token 量纲、`no_plan` 的号没有包）。"""
    from model_gateway.core import quota_policy
    from model_gateway.upstream.zcode import quota as zq

    for acct, _en, rem, st in LIVE_SHAPE:
        items = () if st == "no_plan" else (
            {"name": "GLM-5.3-Flash", "unit": "token", "remaining": rem,
             "total": 100_000_000, "active": True, "expires_at": ""},)
        snap = type("S", (), {"state": st, "remaining": rem,
                              "reason": "no_plan" if st == "no_plan" else "",
                              "items": items})()
        zq.apply_remaining_to_runtime(rt, acct, rem,
                                      entitled=quota_policy.entitled_for(snap))


def events(usage: Path) -> list[dict]:
    day = time.strftime("%Y%m%d")
    p = usage / f"events-{day}.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def ask(base: str, n: int = 1, stream: bool = False) -> list[int]:
    codes = []
    with httpx.Client(timeout=40.0, trust_env=False) as c:
        for _ in range(n):
            r = c.post(f"{base}/v1/chat/completions", json={
                "model": MODEL, "stream": stream,
                "messages": [{"role": "user", "content": "只回一个字"}]})
            codes.append(r.status_code)
    return codes


def acct_of(mid: str, mid_of: dict) -> str:
    return mid_of.get(mid, "?")


def audit(title: str, rows: list[dict], hits: list[str], mid_of: dict,
          expect: dict[str, list[str]]) -> None:
    """把一轮里被派到的号按档位归类，逐条规则判红/判绿。"""
    served = [e.get("account") for e in rows]
    from collections import Counter
    by_tag = Counter(TAG.get(a, "?") for a in served)
    print(f"\n=== {title} ===")
    print(f"  请求数={len(rows)}  出站命中数={len(hits)}  承接档位分布={dict(by_tag)}")
    for rule, banned in expect.items():
        bad = [b for b in banned if by_tag.get(b, 0) > 0]
        print(f"  [{'红' if bad else '绿'}] {rule}"
              + (f" ← 实际派到 {bad}" if bad else ""))
    fails = Counter(e.get("status") for e in rows)
    print(f"  事件状态计数={dict(fails)}")


def main() -> None:
    fake = FakeZcode()
    fport = free_port()
    fserver, _ = serve(fake.app, fport)

    tmp = Path(tempfile.mkdtemp(prefix="mgw-probe-zcode-"))
    (gw_tuple, gport) = build_gateway(tmp, fport)
    gserver, app, mid_of, usage, resources = gw_tuple
    base = f"http://127.0.0.1:{gport}"
    rt = app.state.runtime
    hydrate_quota(rt, resources)

    print(f"网关 :{gport}（隔离数据根 {tmp}）；上游=本地假 ZCode :{fport}；不打真实 zcode")

    try:
        # —— 轮 1：全号正常，20 条串行 ——
        fake.hits.clear()
        codes = ask(base, 20)
        audit("轮 1 · 全号正常 · 20 条串行（x=8 实盘参数）", events(usage)[-20:],
              fake.hits, mid_of,
              {"规则 A 额度=0 不该被派到": ["exhausted"],
               "规则 B 号开关关不该被派到": ["no_plan(开关关)"],
               "规则 C 无套餐不该被派到（用户裁定）": ["no_plan"]})
        print(f"  HTTP 码计数={ {c: codes.count(c) for c in set(codes)} }")

        # —— 轮 2：把 2 个「有余量」号打成持续 5xx，看是否被移出 ——
        ok_accts = [a for a, en, r, st in LIVE_SHAPE if en and r]
        mids = {acct: mid for mid, acct in mid_of.items()}
        for acct in ok_accts[:2]:
            fake.behavior[mids[acct]] = {"kind": "http", "status": 503,
                                         "payload": {"type": "error"}}
        fake.hits.clear()
        codes = ask(base, 12)
        rows = events(usage)[-12:]
        audit("轮 2 · 2 个有余量号持续 5xx（y=2 ⇒ 应被移出冷却）", rows, fake.hits, mid_of,
              {"规则 D 反复 5xx 的号不该继续被派到": ["?"]})
        st = [x for x in rt.resources.registry.values() if x.status == "cooldown"]
        print(f"  冷却中资源数={len(st)}（5xx 的号 y 次后应进冷却）")
        print(f"  被派到的号里是否还有 5xx 那两个："
              f"{[a for a in ok_accts[:2] if any(e.get('account') == a for e in rows)]}")

        # —— 轮 3：把一个号打成持续 400/3012，看是否被移出 ——
        mids = {acct: mid for mid, acct in mid_of.items()}
        bad_acct = ok_accts[2]
        fake.behavior[mids[bad_acct]] = {"kind": "http", "status": 400,
                                         "payload": {"code": 3012, "msg": "unusual activity"}}
        fake.hits.clear()
        codes = ask(base, 16)
        rows = events(usage)[-16:]
        bad_mid = mids[bad_acct]
        n_bad = fake.hits.count(bad_mid)
        rid_bad = next(r["id"] for r in resources if r["name"] == bad_acct)
        state = rt.resources.registry.get((rid_bad, VENDOR_MODEL))
        print(f"\n=== 轮 3 · 一个有余量的号持续回 400/3012（规则 D：反复失败应移出）===")
        print(f"  该号被派到 {n_bad} 次；失败透传给客户端 {codes.count(400)} 次；"
              f"其余 {codes.count(200)} 次成功")
        print(f"  该号运行态：C={state.C} status={state.status} cooldown_until>0={state.cooldown_until > 0}")
        print(f"  [{'绿' if state.status == 'cooldown' else '红'}] 规则 D："
              f"{'已被移出' if state.status == 'cooldown' else '从未被移出 —— 它会一直占着活跃组名额'}")
        print(f"  事件状态计数={ {k: sum(1 for e in rows if e.get('status') == k) for k in {e.get('status') for e in rows}} }")

        # —— 轮 5/6：token 阈值（用户 2026-10-05 补的规则：低于 1 万自动剔出）——
        # 🔴 号集必须与轮 2/轮 3 **互不相交**：那两轮已经把 ok_accts[:3] 打进 5 小时冷却了，
        # 拿它们做阈值判据 = 空判据（红是排队造成的，绿也是排队造成的，跟阈值无关）。
        from model_gateway.core import quota_policy as qp
        from model_gateway.upstream.zcode import quota as zq_mod

        mids = {acct: mid for mid, acct in mid_of.items()}
        low_accts = ok_accts[3:6]

        def _set_floor(acct, rem):
            snap = type("S", (), {"state": "available", "reason": "", "remaining": rem,
                                  "items": ({"name": "GLM-5.3-Flash", "unit": "token",
                                             "remaining": rem, "total": 100_000_000,
                                             "active": True, "expires_at": ""},)})()
            zq_mod.apply_remaining_to_runtime(rt, acct, rem, entitled=qp.entitled_for(snap))
            return qp.entitled_for(snap)

        def _served(acct, n=12):
            rt.resources._cursor[MODEL] = 0
            fake.hits.clear()
            codes = ask(base, n)
            return fake.hits.count(mids[acct]), codes

        print("\n=== 轮 5 · token 包余量阈值（用户：少于 1 万自动剔出）===")
        for acct in low_accts:
            before, _ = _served(acct)
            verdict = _set_floor(acct, 5_000)
            after, codes = _served(acct)
            back, _ = _served(acct, 6) if after else (0, [])
            _set_floor(acct, 10_000)
            revived, _ = _served(acct)
            flag = '绿' if (before > 0 and after == 0 and verdict is False and revived > 0) else '红'
            print(f"  [{flag}] {acct[:26]:26} 阈值前={before} 次 · 5000 token(判据={verdict}) 后={after} 次"
                  f" · 回到 10000 后={revived} 次")
            if flag == '红':
                print(f"      ↳ 读数异常：HTTP={ {c: codes.count(c) for c in set(codes)} }")

        # —— 轮 4：并发 6 条，看同时在途的号数与档位 ——
        fake.behavior.clear()
        fake.hits.clear()
        with httpx.Client(timeout=40.0, trust_env=False) as c:
            codes = [r.status_code for r in
                     [c.post(f"{base}/v1/chat/completions", json={
                         "model": MODEL, "messages": [{"role": "user", "content": "hi"}]})
                      for _ in range(6)]]
        audit("轮 4 · 并发 6 条（同一号可复用，规则只看档位）", events(usage)[-6:],
              fake.hits, mid_of,
              {"规则 A 额度=0 不该被派到": ["exhausted"],
               "规则 C 无套餐不该被派到（用户裁定）": ["no_plan"]})
    finally:
        gserver.should_exit = True
        fserver.should_exit = True
        time.sleep(0.4)


if __name__ == "__main__":
    main()
