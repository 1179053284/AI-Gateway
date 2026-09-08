#!/usr/bin/env python3
"""真实 API 字段形态探索（一次性调试脚本，最便宜模型、最小 token）。

目的：为出站适配器实现校准——
  1. 非流式响应的思考字段名（reasoning_content?）与结构
  2. 流式 SSE chunk 的思考字段（thinking_content vs reasoning_content）
  3. images 端点参数（size 支持）与响应结构（url/b64）
Key 从环境变量 SENSENOVA_API_KEY 读取（不落盘）。
"""

from __future__ import annotations

import json
import os
import sys

import httpx

BASE = "https://token.sensenova.cn/v1"
CHEAP_CHAT = "sensenova-6.8-flash-lite"  # 最便宜 chat 模型
THINK_CHAT = "deepseek-v4-flash"  # 思考模型（探测思考字段）
IMG_MODEL = "sensenova-u1-fast"  # 图像（探测参数）

TIMEOUT = httpx.Timeout(60.0, connect=10.0)


def key() -> str:
    k = os.environ.get("SENSENOVA_API_KEY", "").strip()
    if not k:
        print("SENSENOVA_API_KEY 未设置"); sys.exit(2)
    return k


def H() -> dict:
    return {"Authorization": f"Bearer {key()}", "Content-Type": "application/json"}


def main() -> None:
    with httpx.Client(timeout=TIMEOUT) as c:
        # 1. 最便宜模型非流式
        r = c.post(f"{BASE}/chat/completions", headers=H(), json={
            "model": CHEAP_CHAT, "stream": False, "max_tokens": 50,
            "messages": [{"role": "user", "content": "回复：ok"}],
        })
        print("== 1. 非流式", CHEAP_CHAT, r.status_code)
        j = r.json()
        print(json.dumps(j, ensure_ascii=False, indent=1)[:1200])

        # 2. 思考模型非流式（看 reasoning 字段）
        r = c.post(f"{BASE}/chat/completions", headers=H(), json={
            "model": THINK_CHAT, "stream": False, "max_tokens": 200,
            "messages": [{"role": "user", "content": "1+1=?只回答数字"}],
        })
        print("\n== 2. 非流式", THINK_CHAT, r.status_code)
        j = r.json()
        msg = (j.get("choices") or [{}])[0].get("message", {})
        print("message keys:", list(msg.keys()))
        print("reasoning_content 摘要:", str(msg.get("reasoning_content"))[:200])
        print("content:", str(msg.get("content"))[:100])
        print("usage:", j.get("usage"))

        # 3. 思考模型流式（看 delta 字段名）
        print("\n== 3. 流式", THINK_CHAT)
        with c.stream("POST", f"{BASE}/chat/completions", headers=H(), json={
            "model": THINK_CHAT, "stream": True, "max_tokens": 150,
            "messages": [{"role": "user", "content": "1+2=?只回答数字"}],
        }) as resp:
            print("status:", resp.status_code)
            n = 0
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    print("  [DONE]"); break
                try:
                    ch = json.loads(data)
                    delta = (ch.get("choices") or [{}])[0].get("delta", {})
                    if delta:
                        print("  delta keys:", list(delta.keys()), "|", {k: str(v)[:40] for k, v in delta.items()})
                        n += 1
                    elif ch.get("usage"):
                        print("  usage chunk:", ch.get("usage"))
                except Exception:
                    print("  raw:", line[:150])
                if n > 12:
                    print("  ...（截断）"); break

        # 4. 思考模型流式 + reasoning_effort=low（Q15 字段是否被接受）
        print("\n== 4. 流式 + reasoning_effort=low")
        r = c.post(f"{BASE}/chat/completions", headers=H(), json={
            "model": THINK_CHAT, "stream": False, "max_tokens": 200,
            "reasoning_effort": "low",
            "messages": [{"role": "user", "content": "3+4=?只回答数字"}],
        })
        print("status:", r.status_code)
        if r.status_code == 200:
            j = r.json(); msg = (j.get("choices") or [{}])[0].get("message", {})
            print("reasoning len:", len(str(msg.get("reasoning_content") or "")), "| usage:", j.get("usage"))
        else:
            print("错误体:", r.text[:300])

        # 5. thinking 开关参数形态探测
        print("\n== 5. thinking={type:disabled}")
        r = c.post(f"{BASE}/chat/completions", headers=H(), json={
            "model": THINK_CHAT, "stream": False, "max_tokens": 100,
            "thinking": {"type": "disabled"},
            "messages": [{"role": "user", "content": "5+6=?只回答数字"}],
        })
        print("status:", r.status_code)
        if r.status_code == 200:
            j = r.json(); msg = (j.get("choices") or [{}])[0].get("message", {})
            print("reasoning_content:", msg.get("reasoning_content"), "| usage:", j.get("usage"))
        else:
            print("错误体:", r.text[:300])

        # 6. images 参数探测（先试小 size）
        print("\n== 6. images", IMG_MODEL)
        for size in ("512x512", "1024x1024", None):
            body = {"model": IMG_MODEL, "prompt": "a red circle", "n": 1}
            if size:
                body["size"] = size
            r = c.post(f"{BASE}/images/generations", headers=H(), json=body)
            print(f"size={size} → {r.status_code}")
            if r.status_code == 200:
                j = r.json()
                print("  响应 keys:", list(j.keys()))
                item = (j.get("data") or [{}])[0]
                print("  item keys:", list(item.keys()))
                for k, v in item.items():
                    print(f"  {k}: {str(v)[:90]}")
                break
            else:
                print("  错误体:", r.text[:200])


if __name__ == "__main__":
    main()
