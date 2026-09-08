"""复现测试：httpx 走环境代理访问商汤（trust_env=True/False 对比）。"""
import asyncio
import os
import time

import httpx

BODY = {
    "model": "sensenova-6.8-flash-lite",
    "messages": [{"role": "user", "content": "只回复ok"}],
    "max_tokens": 8,
    "thinking": {"type": "disabled"},
    "reasoning_effort": "none",
}
URL = "https://token.sensenova.cn/v1/chat/completions"
KEY = os.environ.get("SENSENOVA_API_KEY", "")


async def one(trust_env: bool, label: str):
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0), trust_env=trust_env) as c:
            r = await c.post(URL, headers={"Authorization": f"Bearer {KEY}"}, json=BODY)
            print(f"{label}: HTTP {r.status_code} {time.monotonic()-t0:.1f}s")
    except Exception as e:
        print(f"{label}: {type(e).__name__}: {e} ({time.monotonic()-t0:.1f}s)")


async def main():
    await one(True, "trust_env=True (走代理)")
    await one(False, "trust_env=False (直连)")


asyncio.run(main())
