"""`mgw setup` 实现（tech-design v2.0 §12.4 路径 A / PRD Q25-⑨）。

把网关的**启用系统模型 + 能力位**写成工具可读的 `models.json`。

⚠️ 交互纪律（§12.4.1 写入纪律 0）：**写前打印解析结果并等待确认** ——
   因为该路径**曾被环境变量劫持**（`WORKBUDDY_CONFIG_DIR` 由另一个产品注入，
   导致从 WorkBuddy.app 取的 CLI 跑到了 WorkBuddy AI 的目录）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from model_gateway.accounts import catalog_cache
from model_gateway.core import model_spec
from model_gateway.core.capabilities import build_caps_block, build_model_caps
from model_gateway.core import local_admin
from model_gateway.core.resources import (
    OVERVIEW_HEALTH_PAGE,
    PRODUCT_ROUTE_NOTE,
    RESOURCE_PAGE,
    servable_models,
)
from model_gateway.setup_tools import PRODUCTS, resolve_target_dir, write_models_json

from model_gateway.core import paths



def build_cli_models(config, enum_pool, dialects, base_url: str, api_key: str,
                     servable: set[str] | None = None) -> list[dict]:
    """把网关系统模型组装成 CLI 侧 `models.json` 的 `models[]` 条目。

    字段名以**工具契约**为准（camelCase）—— 实测 `08` §4.1。
    `caps` 含 `thinkingLevelMap`（**7 键齐全**，§12.2a）。

    🔴 与 `/v1/models` 同一条判据（BUG-1）：**只下发可服务模型** ——
    路径 A（写文件）与路径 B（API）都得守，否则 WorkBuddy 这类只读文件的工具
    照样会选到一个必然失败的模型。
    """
    # servable 由调用方给（优先取运行中网关的 /v1/models，含失效/停用等运行态）；
    # 取不到才退回纯配置判定 —— 两条路径**同一判据**（PRD Q28-②），不得各说各话
    if servable is None:
        servable = servable_models(config)
    out: list[dict] = []
    spec_cache: dict = {}     # 同一次 CLI 里按产品复用的目录缓存读（零网络）
    for m in config.models:
        if not m.enabled or m.name not in servable:
            continue
        # 🔴 R5-3：同一个 spec 必须**同时**喂给能力位与 `caps` 块。旧写法只给 `build_model_caps`，
        #    `build_caps_block` 漏传 ⇒ 账号独有模型（不在内置枚举池、档位只在按号目录缓存里）
        #    写进工具配置文件的 `thinkingLevelMap` 七个键全 null —— 工具侧推理档位变哑，
        #    正是本轮 R3-F-2 刚消灭的那个形状在**另一条出口**上复活。与 `/v1/models`
        #    （`openai_compat` 两处都传 spec）同一条判据，不得各说各话。
        spec = model_spec.resolve(config, m, enum_pool,
                                  reader=catalog_cache.read_cache, cache=spec_cache)
        caps_fields = build_model_caps(m, enum_pool, dialects, spec=spec)
        out.append({
            "id": f"custom-local:{m.name}",   # 工具侧前缀（网关入站会剥离，Q25-⑦）
            "name": f"Model-Gateway · {m.name}",
            "vendor": "Model-Gateway",
            "url": base_url,
            "apiKey": api_key,
            "useCustomProtocol": False,
            "supportsToolCall": caps_fields["supportsToolCall"],
            "supportsImages": caps_fields["supportsImages"],
            "supportsReasoning": caps_fields["supportsReasoning"],
            "maxInputTokens": caps_fields["maxInputTokens"],
            "maxOutputTokens": caps_fields["maxOutputTokens"],
            # 🔴 复验 R10 报备 4：`/v1/models` 带了这个位而**下发文件**不带，
            #    只读文件的工具（WorkBuddy 这类）就仍然分不清"昨天的数"与"实时的数"，
            #    等于把刚闭口的欠账在第二条出口上复活。字段与 `/v1/models` 同名同语义。
            "specStale": caps_fields["specStale"],
            "tags": ["custom"],
            "caps": build_caps_block(m, enum_pool, dialects, spec=spec),
        })
    return out


#: 隐藏成因 → 该去哪修（三句话各不相同）。
#: 🔴 面板 S-9：原先不分成因统一说"到「接入模型资源」页添加映射" ——
#: 对"映射有但资源开关没关着"和"凭据被上游判死"两种情形是**错的指路**，
#: 用户照着做会发现自己根本没有可添加的东西。
_CAUSE_HINTS = {
    # 🔴 「添加映射」的控件（`#rv-addmap`）长在「接入模型资源」页，「网关模型管理」页只有
    #    档位/优先级/移除映射 —— 指错了用户会在那一屏找不到"添加"（第十一轮 PM B-11-1）。
    "no_mapping": f"到{RESOURCE_PAGE}为该模型添加资源映射{PRODUCT_ROUTE_NOTE}",
    "resource_disabled": f"到{RESOURCE_PAGE}打开对应资源的启用开关{PRODUCT_ROUTE_NOTE}",
    # 🔴 「最近错误」这一列在**总览**的资源健康表上，不在「接入模型资源」页
    #    （实测 `grep -c 最近错误 pages/resources.js` → 0；面板 S-17 指错页面）
    "runtime_dead": f"到{OVERVIEW_HEALTH_PAGE}看该资源的「最近错误」"
                    "（凭据失效需换 Key，风控/额度冷却会自行恢复）",
}


def _hidden_causes(config, hidden: list[str]) -> dict[str, list[str]]:
    """把被隐藏的模型按**可诊断的成因**分桶（CLI 独立进程无运行态，只能按配置判前两类）。"""
    by_name = {m.name: m for m in config.models}
    res_by_id = {r.id: r for r in config.resources}
    out: dict[str, list[str]] = {"no_mapping": [], "resource_disabled": [], "runtime_dead": []}
    for name in hidden:
        m = by_name.get(name)
        refs = list(m.resources) if m else []
        if not refs:
            out["no_mapping"].append(name)
        elif all((res_by_id.get(r.resource) is None or not res_by_id[r.resource].enabled)
                 for r in refs):
            out["resource_disabled"].append(name)
        else:
            # 映射在、资源开关也开着，却仍不可服务 → 运行态问题（invalid / 正在冷却）
            out["runtime_dead"].append(name)
    return out


def name_note(kind: str) -> str:
    return {"no_mapping": "未配置任何资源映射", "resource_disabled": "映射的资源均未启用",
            "runtime_dead": "映射资源运行态不可用"}[kind]


def run_setup(args: argparse.Namespace) -> int:
    from model_gateway.config.loader import ConfigError, load_config
    from model_gateway.core.dialects import DialectTable
    from model_gateway.enums.matcher import load_enum_pool
    from model_gateway.main import DIALECTS_PATH, ENUMS_PATH

    tool = args.tool
    if tool not in PRODUCTS:
        print(f"✗ 未知产品 '{tool}'（可选：{', '.join(PRODUCTS)})", file=sys.stderr)
        return 2

    cfg_path = paths.resolve_config_path(args.config)
    try:
        config = load_config(cfg_path)
    except ConfigError as e:
        print(f"✗ 配置校验失败：{e.errors}", file=sys.stderr)
        return 2

    # 目标目录解析（Q25-⑨）—— 打印结果供用户核对（写入纪律 0）
    target_dir, source = resolve_target_dir(tool)
    print(f"目标目录：{target_dir}")
    print(f"    （来源：{source}）")

    # 取一条启用的接入密钥（工具端用）
    tokens = [t for t in config.gateway.access_tokens if t.enabled]
    if not tokens:
        print("✗ 未配置任何启用的接入密钥（到「API 接入」页新建）", file=sys.stderr)
        return 2
    api_key = tokens[0].value
    base_url = f"http://127.0.0.1:{config.gateway.port}/v1"

    # 🔴 运行态优先：向在跑的网关要 `/v1/models`（它才知道哪些资源已被判失效/停用）。
    #    `/v1/*` 在鉴权中间件后面，**必须带接入密钥**，否则 401 → 曾因此谎报"网关未运行"
    #    （验收 T9b）。取不到不猜 —— 显式说明按什么判定，否则用户以为看到的是实时状态。
    live, why = local_admin.admin_get_detail(
        "/v1/models", port=config.gateway.port,
        headers={"Authorization": f"Bearer {api_key}"})
    servable: set[str] | None = None
    if why == "ok" and live is not None:
        servable = {str(m.get("id", "")).split(":")[-1]
                    for m in live.get("data", []) if isinstance(m, dict)}
        judged_by = f"运行中网关的 /v1/models（{len(servable)} 个模型可服务，含运行态）"
    else:
        # 降级可以，**谎报不行**：原因原样打印，用户才知道该查密钥还是查进程
        judged_by = (f"本地配置 · 原因：{local_admin.reason_text(why)}"
                     " —— 感知不到资源失效等运行态")
    print(f"可服务模型判定依据：{judged_by}")

    models = build_cli_models(config, load_enum_pool(ENUMS_PATH),
                              DialectTable.load(DIALECTS_PATH), base_url, api_key,
                              servable=servable)
    # 🔴 被隐藏的模型必须说清数量与去处，否则等于又一次静默降级
    hidden = [m.name for m in config.models
              if m.enabled and m.name not in (servable if servable is not None
                                              else servable_models(config))]
    if hidden:
        # 🔴 分成因各说一句（数量 + 名字 + 去处），否则"统一指到添加映射"对
        # 三种成因里的两种是错的（面板 S-9）
        causes = _hidden_causes(config, hidden)
        print(f"已跳过 {len(hidden)} 个不可服务的系统模型：")
        for kind, names in causes.items():
            if not names:
                continue
            shown = "、".join(names[:5]) + ("…" if len(names) > 5 else "")
            print(f"    · {len(names)} 个{name_note(kind)}（{shown}）—— {_CAUSE_HINTS[kind]}")
    if not models:
        print("✗ 没有可下发的系统模型（无启用模型，或启用模型均无可用资源）", file=sys.stderr)
        return 2

    degrade_note = ""
    if servable is None:
        # 🔴 降级写盘也要在**最后一行**留提醒（面板 S-17：用户只看得到"✓ 成功"）
        degrade_note = "；⚠ 未取到运行态，清单可能含已不可服务的模型（原因见上方判定依据行）"
    print(f"将写入：models.json（{len(models)} 条系统模型{degrade_note}）")
    if args.dry_run:
        res = write_models_json(tool, models, dry_run=True)
        print(f"  {res.message}")
        return 0

    # 确认（非交互需 --yes）
    if not args.yes:
        if not sys.stdin.isatty():
            print("✗ 非交互环境需显式 --yes", file=sys.stderr)
            return 2
        try:
            ans = input("继续？[y/N] ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("y", "yes"):
            print("已取消")
            return 1

    res = write_models_json(tool, models)
    if res.ok:
        print(f"✓ {res.message}")
        if res.backup:
            print(f"  原文件备份为：{res.backup.name}")
        return 0
    print(f"✗ {res.message}", file=sys.stderr)
    return 3
