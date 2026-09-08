#!/usr/bin/env python3
"""商汤双端点实测脚本（tech-design §10.2，M1 任务 2：Q12 定论路径）。

用法：
    export SENSENOVA_API_KEY=sk-xxxx      # Key 仅从环境变量读取：不落盘、不入日志
    python scripts/sensenova_probe.py

对两个候选端点各执行：
    1. GET /models（Bearer Key）→ HTTP 状态 + 模型清单（存 docs/changes/sensenova-models-{A,B}.json）
    2. 最小 POST /chat/completions（model 优先清单中的 deepseek-v4-flash，
       否则清单首个；清单失败回退官方文档已知模型名）→ 状态 + 响应摘要

判定表（§10.2-4）：
    - 主判据 = 最小 chat 调用：HTTP 200 + 合法响应 = 端点可用
    - /models 为辅助判据（异常而 chat 成功 → 端点可用、清单另案处理）
    - 401/403 = Key 不属于该体系
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

ENDPOINTS: list[tuple[str, str]] = [
    ("A", "https://token.sensenova.cn/v1"),              # 用户答复倾向的体系（优先）
    ("B", "https://api.sensenova.cn/compatible-mode/v2"),  # ModelStudio 按量体系
]

# 官方文档已知模型名（清单获取失败时的回退；按「最便宜优先」排序：lite/flash 系在前）
FALLBACK_MODELS = [
    "sensenova-6.8-flash-lite",
    "deepseek-v4-flash",
    "SenseNova-V6-128K",
    "SenseNova-5-5",
]

CHANGES_DIR = Path(__file__).resolve().parents[1] / "docs" / "changes"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def pick_cheapest(models: list[str]) -> str:
    """从清单中选最便宜模型（用户要求：调试测试用最便宜模型）。

    偏好顺序：名字含 lite 的 > 含 flash 的 > 清单首个。
    """
    for kw in ("lite", "flash"):
        for m in models:
            if kw in m.lower():
                return m
    return models[0] if models else "sensenova-6.8-flash-lite"


def _mask(s: str) -> str:
    """日志脱敏：仅保留前 3 后 2（Key 绝不完整出现在输出中）。"""
    return f"{s[:3]}...{s[-2:]}" if len(s) > 6 else "***"


def probe_models(base_url: str, key: str) -> tuple[int | None, list[str], str]:
    """GET /models → (状态码, 模型清单, 备注)。"""
    try:
        r = httpx.get(f"{base_url}/models", headers={"Authorization": f"Bearer {key}"}, timeout=TIMEOUT)
        models: list[str] = []
        if r.status_code == 200:
            data = r.json().get("data", [])
            models = [m.get("id", "") for m in data if isinstance(m, dict) and m.get("id")]
        return r.status_code, models, ""
    except Exception as e:  # noqa: BLE001 — 探测脚本需汇总一切异常形态
        return None, [], f"{type(e).__name__}: {e}"


def probe_chat(base_url: str, key: str, model: str) -> tuple[int | None, str, str]:
    """最小 POST /chat/completions → (状态码, 响应摘要, 请求模型)。"""
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 8,
        "stream": False,
    }
    try:
        r = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            j = r.json()
            content = (j.get("choices") or [{}])[0].get("message", {}).get("content", "")
            summary = f"200 ok；model={j.get('model')}；content摘要={content[:40]!r}；usage={j.get('usage')}"
        else:
            summary = f"{r.status_code}；错误体={r.text[:200]}"
        return r.status_code, summary, model
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}", model


def judge(models_status: int | None, chat_status: int | None) -> str:
    """判定表（§10.2-4）：chat 为主判据。"""
    if chat_status == 200:
        if models_status == 200:
            return "可用（chat 200 + /models 200）"
        return "可用（chat 200；/models 异常属清单问题，另案处理）"
    if chat_status in (401, 403) or models_status in (401, 403):
        return "Key 不属于该体系（401/403）"
    return "不可用（chat 未成功）"


def main() -> int:
    key = os.environ.get("SENSENOVA_API_KEY", "").strip()
    if not key:
        print("错误：环境变量 SENSENOVA_API_KEY 未设置（Key 不落盘，仅环境变量传入）")
        return 2
    print(f"SENSENOVA_API_KEY = {_mask(key)}（已脱敏）\n")

    CHANGES_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    for tag, base_url in ENDPOINTS:
        print(f"===== 端点 {tag}: {base_url} =====")
        models_status, models, models_note = probe_models(base_url, key)
        print(f"GET /models → {models_status}（{len(models)} 个模型）{models_note}")
        if models_status == 200 and models:
            print(f"  清单（前 10）：{models[:10]}")

        # chat 模型选择：清单优先 deepseek-v4-flash，否则清单首个；失败回退已知名
        if models:
            model = next((m for m in models if m == "deepseek-v4-flash"), models[0])
        else:
            model = next((m for m in FALLBACK_MODELS), "deepseek-v4-flash")
        chat_status, chat_summary, used_model = probe_chat(base_url, key, model)
        print(f"POST /chat/completions（model={used_model}）→ {chat_summary}")

        verdict = judge(models_status, chat_status)
        print(f"判定：{verdict}\n")

        results.append(
            {
                "endpoint": tag,
                "base_url": base_url,
                "models_status": models_status,
                "models_count": len(models),
                "models_note": models_note,
                "chat_model": used_model,
                "chat_status": chat_status,
                "chat_summary": chat_summary,
                "verdict": verdict,
            }
        )

        # 模型清单落盘（§10.2-3：存 docs/changes/sensenova-models-A|B.json）
        out = CHANGES_DIR / f"sensenova-models-{tag}.json"
        out.write_text(
            json.dumps(
                {"endpoint": tag, "base_url": base_url, "http_status": models_status, "models": models},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    print("===== 判定表 =====")
    for r in results:
        print(f"端点 {r['endpoint']} {r['base_url']} → {r['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
