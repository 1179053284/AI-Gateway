"""`mgw probe` 实现（tech-design v2.0 §13.3 / PRD Q25-⑤）。

CLI 交互契约（§13.3）：探测是**长耗时且会触发上游频控**的操作（实测约 1/3 请求触发 429），
因此必须：**执行前确认 + 逐个模型即时打印 + 结束打印计数**。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import httpx

from model_gateway.core.dialects import DialectTable
from model_gateway.core.resources import normalize_base_url
from model_gateway.probe import CallFn, probe_model

from model_gateway.core import paths



def _make_call_fn(base_url: str, api_key: str, timeout: float = 30.0) -> CallFn:
    """构造真实探测调用函数：`(body) -> (status, json)`。

    单测注入假序列即可**确定性验证** S1/S2/S3 三步逻辑（§13.4 可测试性要求）。
    """
    # 🔴 与运行态指纹 / 适配器复用同一把尺（`normalize_base_url`，验收 S-14→S-19→S-26）：
    #    各写一遍 `rstrip("/")` 时，粘贴来的带空格 URL 会出现"网关能跑、probe 报
    #    UnsupportedProtocol"这种对不上账的分叉。
    url = normalize_base_url(base_url) + "/chat/completions"

    async def _call(body: dict) -> tuple[int, dict]:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(url, json=body, headers=headers)
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, {}
        except httpx.HTTPError as e:
            return 0, {"error": {"message": f"网络错误：{e}"}}

    return _call


def _pick_resource(config, model):
    """取该模型第一条启用资源（探测只需一条可用链路）。"""
    enabled = {r.id: r for r in config.resources
                 if r.enabled and normalize_base_url(r.base_url)}   # 只填空格的端点不算有端点
    for mr in model.resources:
        r = enabled.get(mr.resource)
        if r is not None:
            return r, mr.model
    return None, None


async def _run(args: argparse.Namespace) -> int:
    from model_gateway.config.loader import ConfigError, load_config
    from model_gateway.main import DIALECTS_PATH

    cfg_path = paths.resolve_config_path(args.config)
    try:
        config = load_config(cfg_path)
    except ConfigError as e:
        print(f"✗ 配置校验失败：{e.errors}", file=sys.stderr)
        return 2

    table = DialectTable.load(DIALECTS_PATH)

    # 默认：当前启用且**尚无方言记录**的模型（避免重复探测，§13.3）
    targets = []
    for m in config.models:
        if not m.enabled:
            continue
        if args.model and m.name not in args.model:
            continue
        if not args.model and not args.all and table.get(m.name) is not None:
            continue
        targets.append(m)

    if args.model:
        missing = [n for n in args.model if n not in {m.name for m in config.models}]
        if missing:
            print(f"✗ 未定义的网关模型：{', '.join(missing)}", file=sys.stderr)
            return 2

    if not targets:
        print("没有需要探测的模型（全部已有方言记录；用 --all 强制重探）")
        return 0

    # 执行前确认（§13.3 交互契约）
    print(f"将探测 {len(targets)} 个模型，预计 {len(targets) * 6} 次请求"
          f"（可能触发上游频控），继续？", end=" ")
    if not args.yes:
        if not sys.stdin.isatty():
            print("\n✗ 非交互环境需显式 --yes", file=sys.stderr)
            return 2
        try:
            ans = input("[y/N] ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("y", "yes"):
            print("已取消")
            return 1
    else:
        print("（--yes）")

    ok = fail = 0
    for m in targets:
        res, vendor_model = _pick_resource(config, m)
        if res is None:
            print(f"✗ {m.name:<28} → 无可用资源，跳过")
            fail += 1
            continue
        call = _make_call_fn(res.base_url, res.api_key)
        outcome = await probe_model(vendor_model or m.name, call)
        d = outcome.dialect
        if d.verified:
            # 逐模型即时打印（长任务不能等结束才输出）
            print(f"✓ {m.name:<28} → 写入位 {d.write_field}"
                  f"（档位 {', '.join(d.values)}）")
            table.entries[m.name] = d
            ok += 1
        else:
            print(f"✗ {m.name:<28} → 探测失败，保留硬编码 fallback")
            fail += 1
        # 串行 + 间隔（§13.4 探测纪律：实测约 1/3 请求触发 429）
        await asyncio.sleep(1.5)

    table.save()
    print(f"\n完成：成功 {ok} 个，失败 {fail} 个（方言表已写入 {DIALECTS_PATH}）")
    _reload_running_gateway(config)
    return 0 if fail == 0 else 1


def _reload_running_gateway(config) -> None:
    """让**运行中的网关**重载方言表（§13.4：探测后必须显式触发，不加 watcher）。

    网关未运行（如停机中）时静默跳过 —— 下次启动会自然加载新文件。
    """
    from model_gateway.core.local_admin import admin_post

    body = admin_post("/admin/api/dialects/reload", port=config.gateway.port)
    if body is None:
        print("（网关未运行，跳过重载通知；下次启动会自动加载）")
    else:
        print(f"已通知网关重载方言表（{body.get('before')} → {body.get('after')} 条）")


def run_probe(args: argparse.Namespace) -> int:
    return asyncio.run(_run(args))
