"""日聚合 + 看板查询（tech-design §4.8；UT-15/UT-27）。

纯函数：由当日事件列表重算日聚合（按网关模型/资源/令牌/供应商/账号五维，
后两维由事件行冗余 provider/account 字段派生——Q17/PRD FR-6.1；
历史行无该字段时按空值归组兼容，不报错）。
M3 看板读「历史 daily 文件 + 当日实时」双段。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _new_bucket() -> dict[str, Any]:
    return {
        "requests": 0, "success": 0, "failed": 0, "aborted": 0,
        "input_tokens": 0, "output_tokens": 0,
        "retry_count": 0, "switch_count": 0,
        "duration_ms_total": 0, "ttft_ms_total": 0, "ttft_count": 0,
        "images_count": 0,
    }


def aggregate_day(events: list[dict]) -> dict[str, Any]:
    """按五维（system_model / final_resource / client_token_id / provider / account）聚合当日事件。

    聚合值与手算一致（UT-15/UT-27）：次数、成功/失败/中断、token、重试、切换、
    耗时、TTFT、图像张数。provider/account 为事件行冗余派生字段，历史行无该
    字段（或为 null）→ 归入 "(unknown)" 空值组（UT-27）。
    """
    dims: dict[str, dict[str, dict[str, Any]]] = {
        "by_model": defaultdict(_new_bucket),
        "by_resource": defaultdict(_new_bucket),
        "by_token": defaultdict(_new_bucket),
        "by_provider": defaultdict(_new_bucket),
        "by_account": defaultdict(_new_bucket),
    }
    totals = _new_bucket()

    def _apply(bucket: dict, ev: dict) -> None:
        bucket["requests"] += 1
        status = ev.get("status", "failed")
        if status in ("success", "failed", "aborted"):
            bucket[status] += 1
        bucket["input_tokens"] += ev.get("input_tokens") or 0
        bucket["output_tokens"] += ev.get("output_tokens") or 0
        bucket["retry_count"] += ev.get("retry_count") or 0
        bucket["switch_count"] += ev.get("switch_count") or 0
        bucket["duration_ms_total"] += ev.get("duration_ms") or 0
        ttft = ev.get("ttft_ms")
        if ttft is not None:
            bucket["ttft_ms_total"] += ttft
            bucket["ttft_count"] += 1
        bucket["images_count"] += ev.get("images_count") or 0

    for ev in events:
        _apply(totals, ev)
        _apply(dims["by_model"][ev.get("system_model") or "(unknown)"], ev)
        res = ev.get("final_resource") or "(none)"
        _apply(dims["by_resource"][res], ev)
        tok = ev.get("client_token_id") or "(anonymous)"
        _apply(dims["by_token"][tok], ev)
        _apply(dims["by_provider"][ev.get("provider") or "(unknown)"], ev)
        _apply(dims["by_account"][ev.get("account") or "(unknown)"], ev)

    return {**{k: dict(v) for k, v in dims.items()}, "totals": totals}


def estimate_usage(body: dict, response_text: str) -> tuple[int, int]:
    """本地 token 估算（FR-5.8 usage_source=estimated）：粗略 chars/4（含 CJK 加权）。"""
    prompt_text = ""
    for m in body.get("messages", []) or []:
        if isinstance(m, dict):
            c = m.get("content")
            if isinstance(c, str):
                prompt_text += c
            elif isinstance(c, list):
                for part in c:
                    if isinstance(part, dict) and part.get("type") == "text":
                        prompt_text += part.get("text", "")
    cjk = sum(1 for ch in prompt_text if "\u4e00" <= ch <= "\u9fff")
    other = len(prompt_text) - cjk
    input_tokens = int(cjk / 1.5 + other / 4) + 8
    cjk_o = sum(1 for ch in response_text if "\u4e00" <= ch <= "\u9fff")
    other_o = len(response_text) - cjk_o
    output_tokens = int(cjk_o / 1.5 + other_o / 4) + 1
    return max(1, input_tokens), max(0, output_tokens)
