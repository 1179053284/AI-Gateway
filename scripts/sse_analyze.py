"""SSE 流分析：chunk 计数 + reasoning/content 聚合（E2E-04 证据辅助）。

用法：python scripts/sse_analyze.py <sse文件>
"""
import json
import sys

path = sys.argv[1]
reasoning, content = "", ""
chunks = 0
usage = None
finish = None
for line in open(path):
    line = line.strip()
    if not line.startswith("data: ") or line == "data: [DONE]":
        continue
    chunks += 1
    try:
        d = json.loads(line[6:])
    except json.JSONDecodeError:
        continue
    if isinstance(d, dict) and d.get("usage"):
        usage = d["usage"]
    for ch in d.get("choices", []):
        delta = ch.get("delta", {})
        rc = delta.get("reasoning_content")
        if isinstance(rc, str):
            reasoning += rc
        cc = delta.get("content")
        if isinstance(cc, str):
            content += cc
        if ch.get("finish_reason"):
            finish = ch["finish_reason"]

print(f"chunks: {chunks}")
print(f"finish_reason: {finish}")
print(f"reasoning_len: {len(reasoning)}")
print(f"reasoning_head: {reasoning[:80]!r}")
print(f"content: {content[:120]!r}")
print(f"usage: {usage}")
