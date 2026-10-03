"""管理 API（tech-design §4.1/§4.4；M1 骨架 → M2 完整化，design-spec §3）。

- GET  /admin/api/overview：总览一次取齐（状态 + 今日聚合 + 资源健康 + 最近切换 + 调用地址）
- GET  /admin/api/stats?days=：看板聚合（daily 快照 + 当日实时双段合并，含按天趋势序列；
       五维 by_model/by_resource/by_token/by_provider/by_account + dimensions 可用维度键）
- GET  /admin/api/presets：厂商预设注册表（接入向导下拉数据源，含 billing_display 展示值）
- POST /admin/api/system/stop：系统运行控制·优雅停机（仅主进程启动形态）
- POST /admin/api/system/restart：系统运行控制·自重启（execv 映像替换，仅主进程启动形态）
- GET  /admin/api/logs/requests?date=&limit=&offset=&model=&status=&token=：请求流水
- GET  /admin/api/logs/switches?date=&limit=：切换事件流水
- GET  /admin/api/config[?reveal=1]：当前配置（默认厂商 Key 脱敏；reveal=1 明文，Q18-① 自用系统免鉴权）
- PUT  /admin/api/config：保存配置（ID/密钥缺省自动生成 → 脱敏还原 → 校验 → 原子写 → 热重载）
- GET/PUT /admin/api/enums：统一名枚举池读写（model-enums.yaml 双向一致）
- GET  /admin/api/zcode/import/sources + POST /admin/api/zcode/import：ZCode 导入兼容（Q31）
- GET/POST /admin/api/zcode/shop/{items,buy} + GET /admin/api/zcode/shop/order：小店代理（Q31）
管理端免鉴权（Q18-①：自用本地系统，仅 /v1/* 需接入密钥）。
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import secrets
import socket
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from model_gateway import __version__
from model_gateway.adapters import build_adapter
from model_gateway.api.admin_accounts import router as accounts_router
from model_gateway.api.admin_zcode import router as zcode_admin_router
from model_gateway.config.loader import ConfigError, load_config, save_config
from model_gateway.config.presets import display_billing, list_presets
from model_gateway.config.schemas import AppConfig
from model_gateway.core.resources import vendor_label
from model_gateway.enums.matcher import BUILTIN_ENTRIES, EnumEntry
from model_gateway.stats.aggregate import aggregate_day
from model_gateway.stats.events import error_summary, mask_key

# ---------- 写方法来源校验（M6-6 / R3-P4：CSRF 收敛）----------

#: 写方法集合（来源校验只覆盖这些方法；GET/HEAD 读取面不受影响）
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: 本机回环主机名族（Origin 与请求 Host 分属其中两个且端口一致 → 视为「同族本机」）
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

#: scheme 的默认端口（Origin 省略端口时的归一化用；浏览器通常显式带端口）
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _url_host_port(raw: str) -> tuple[str, int | None]:
    """`host[:port]`（或 URL / netloc）→ (小写主机名, 端口)；解析不动 → ("", None)。"""
    try:
        u = urlsplit(raw if "//" in raw else "//" + raw)
        return (u.hostname or "").lower(), u.port
    except ValueError:
        return "", None


def _same_origin(origin: str, request: Request) -> bool:
    """`Origin` 与请求 Host 同源判定：端口必须一致；主机名相同，或同属回环族。

    （「同族本机」= `127.0.0.1` / `localhost` / `::1` 互换也视为同一台机器的同一个服务，
    避免网关自身页面用 localhost 打开、接口按 127.0.0.1 寻址时被误伤。）
    """
    try:
        o = urlsplit(origin)
    except ValueError:
        return False
    if o.scheme not in _DEFAULT_PORTS or not o.hostname:
        return False                      # "null" / 非 http(s) 来源（file:// 等）一律不算同源
    o_host = o.hostname.lower()
    try:
        o_port = o.port if o.port is not None else _DEFAULT_PORTS[o.scheme]
    except ValueError:
        return False
    host_header = (request.headers.get("host") or "").strip()
    r_host, r_port = _url_host_port(host_header or request.url.netloc)
    if not r_host:
        return False
    if r_port is None:                    # Host 未带端口（默认端口场景）→ 退回服务端实际端口
        try:
            r_port = request.url.port
        except ValueError:
            return False
    if r_port is None:
        r_port = _DEFAULT_PORTS.get(request.url.scheme, 0)
    if o_port != r_port:
        return False
    return o_host == r_host or (o_host in _LOOPBACK_HOSTS and r_host in _LOOPBACK_HOSTS)


async def admin_write_origin_guard(request: Request) -> None:
    """管理端写方法的**来源校验**（M6-6 / R3-P4；范围 = `/admin/api/*` 的 POST/PUT/PATCH/DELETE）。

    🔴 为什么需要：管理端免鉴权（Q18-①）+ 简单 POST（无预检）→ 异源网页可经 CSRF
    触发 `enable` / `disable` / `claim` / `delete?confirm=1` 等破坏性端点（R3-P4 真 PoC）。
    本校验是**来源收口**，不是鉴权：它只裁剪"浏览器网页被第三方站点驱动"这一面。

    判据（逐条与用户裁决口径对齐）：
    - **不带 `Origin`**（curl / node 脚本 / CLI 的 `local_admin.admin_post`）→ 放行。
      不引入必填头：既有 CLI / 脚本 / 前端验收工作流（如 `scripts/verify_v2_frontend.mjs`）零改动。
    - **带 `Origin`**（浏览器场景）→ 其 host 必须与请求 Host 同源：端口一致，且主机名相同
      或同属回环族（`127.0.0.1` / `localhost` / `::1`）；否则 403 + 可读文案。
    - **`Sec-Fetch-Site: cross-site`** → 一律 403（浏览器跨站信号，不依赖 Origin 是否存在）。

    ⚠️ 局限（显式登记，不伪装更严）：本机进程（含恶意脚本）本就可直接调用免鉴权端点，
    该面不因本校验变化；跨源页面在**不支持 Sec-Fetch-Site 的旧浏览器**上仅靠 Origin 判据。
    """
    if request.method.upper() not in _WRITE_METHODS:
        return
    site = (request.headers.get("sec-fetch-site") or "").strip().lower()
    if site == "cross-site":
        raise HTTPException(status_code=403,
                            detail="跨站请求被拒绝：管理端写操作只接受本机同源请求"
                                   "（Sec-Fetch-Site: cross-site）")
    origin = (request.headers.get("origin") or "").strip()
    if not origin:
        return                            # 非浏览器调用：无 Origin，照常放行
    if not _same_origin(origin, request):
        host = (request.headers.get("host") or request.url.netloc)
        raise HTTPException(status_code=403,
                            detail=f"跨源请求被拒绝：管理端写操作要求同源本机"
                                   f"（Origin {origin!r} 与 Host {host!r} 不同源；"
                                   f"不带 Origin 的本机脚本不受影响）")


router = APIRouter(dependencies=[Depends(admin_write_origin_guard)])

# 多产品账号管理（M6-4a，§22.7）：`/admin/api/accounts*` 挂在同一管理面下（免鉴权沿用 Q18-①）。
# 独立模块（`api/admin_accounts.py`）承载全部账号端点；本文件只做挂载。
# 🔴 来源校验对账号端点同样生效（`include_router` 显式挂依赖；M6-6 / R3-P4）。
router.include_router(accounts_router, dependencies=[Depends(admin_write_origin_guard)])

# ZCode 导入兼容 + 小店代理（Q31，2026-10-01）：`/admin/api/zcode/import*` 与
# `/admin/api/zcode/shop/*`；独立模块（`api/admin_zcode.py`），同样挂来源校验。
router.include_router(zcode_admin_router, dependencies=[Depends(admin_write_origin_guard)])


# ---------- 公共辅助 ----------

def _read_jsonl(runtime, kind: str, day: str) -> list[dict]:
    """读指定日期的事件 JSONL（坏行跳过）。"""
    path = runtime.usage_dir / f"{kind}-{day}.jsonl"
    out: list[dict] = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
    return out


def _today() -> str:
    return dt.date.today().strftime("%Y%m%d")


def _lan_ip() -> str:
    """本机局域网出口 IP（不实际发包）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _merge_bucket(a: dict, b: dict) -> dict:
    """聚合桶相加（in-place 到 a）。"""
    for k, v in b.items():
        a[k] = a.get(k, 0) + v
    return a


def _agg_of_day(runtime, day: str) -> dict:
    """某日聚合：历史日读 daily 快照；当日实时重算。"""
    if day == _today():
        return aggregate_day(_read_jsonl(runtime, "events", day))
    path = runtime.usage_dir / f"daily-{day}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError, OSError):
            pass
    return aggregate_day([])


def _fmt_duration(ms: int) -> str:
    s = ms // 1000
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    return f"{h}h{m:02d}m" if h else (f"{m}m{sec:02d}s" if m else f"{sec}s")


# ---------- 总览 ----------

@router.get("/admin/api/status")
async def status(request: Request):
    """轻量状态（令牌门校验 + 顶栏 5s 轮询；不读事件文件，区别于 overview）。"""
    runtime = request.app.state.runtime
    return {
        "version": __version__,
        "uptime_ms": int((time.monotonic() - runtime.started_mono) * 1000),
        "in_flight_requests": sum(r.in_flight for r in runtime.resources.registry.values()),
        "resources": runtime.resources.snapshot_by_resource(runtime.config),
        # v2.0 §21 / §16.6：运营未读失败数（顶栏红点用；复用既有 5s 轮询，不新建轮询）。
        # 🔴 数据源是 `data/usage/ops-results-<date>.jsonl`（+ 已确认水位），**不是进程内计数器**：
        # 否则 CLI 独立进程写下的失败永远点不亮红点，网关重启还会把未读清零（验收 S-5）。
        "ops_failed_unread": ops_runner_unread(runtime.usage_dir),
        # 🔴 实例身份（2026-10-02 用户实拍立项）：验收门/临时副本的界面与 :8300 逐像素一致，
        #    唯一能区分真假的线索原先只有地址栏端口 —— 现在由顶栏横幅在每个页面自证。
        #    复用既有 5s 轮询，不新建端点、不新建轮询通道。
        "instance": runtime.instance_label(),
    }


def ops_runner_unread(usage_dir) -> int:
    """未读运营失败数（运营模块不可用时按 0 处理，不影响状态页其余字段）。"""
    try:
        from model_gateway.ops.runner import unread_failures

        return unread_failures(usage_dir)
    except Exception:  # noqa: BLE001 — 状态页不得因运营子模块异常而 500
        return 0


@router.get("/admin/api/overview")
async def overview(request: Request):
    runtime = request.app.state.runtime
    cfg = runtime.config
    today = _agg_of_day(runtime, _today())
    totals = today.get("totals", {})
    switches = _read_jsonl(runtime, "switch-events", _today())
    lan_ip = _lan_ip()
    port = cfg.gateway.port
    return {
        "version": __version__,
        "uptime_ms": int((time.monotonic() - runtime.started_mono) * 1000),
        "in_flight_requests": sum(r.in_flight for r in runtime.resources.registry.values()),
        "counts": {
            # 资源/厂商口径 = 配置资源（厂商+账号+Key），非 (资源×模型) 映射条目（注册表）
            "vendors": len({vendor_label(r.preset, r.vendor, r.name, r.id)
                            for r in cfg.resources}),
            "resources": len(cfg.resources),
            "models": sum(1 for m in cfg.models if m.enabled),
        },
        "today": {
            "requests": totals.get("requests", 0),
            "success": totals.get("success", 0),
            "failed": totals.get("failed", 0),
            "aborted": totals.get("aborted", 0),
            "input_tokens": totals.get("input_tokens", 0),
            "output_tokens": totals.get("output_tokens", 0),
            "images_count": totals.get("images_count", 0),
            "switch_count": totals.get("switch_count", 0),
        },
        "today_by_hour": _today_hourly(runtime),
        "resources": runtime.resources.snapshot_by_resource(cfg),
        "recent_switch_events": list(runtime.switch_ring)[-20:],
        "today_switch_count": len(switches),
        "call_addresses": {
            "local": f"http://127.0.0.1:{port}/v1",
            "lan": f"http://{lan_ip}:{port}/v1",
            "lan_ip": lan_ip,
        },
        # v2.0 §21 / PRD Q25-⑧：配置告警（**两类**，措辞不同）。
        # 🔴 必须走接口而非只写日志 —— 启动脚本正常路径是 nohup 后台 + 自动关窗，
        #    写日志 = 用户看不见。总览页用既有 .alert-warn 渲染横幅。
        # ⚠️ 与既有的 config.warnings（schema 校验告警，经 /health 暴露）**语义不同**，勿混。
        "warnings": runtime.config_warnings(),
    }


def _today_hourly(runtime) -> list[dict]:
    """今日 24 小时分桶（趋势迷你图用）。"""
    buckets = [{"hour": h, "requests": 0, "success": 0, "failed": 0, "aborted": 0}
               for h in range(24)]
    for ev in _read_jsonl(runtime, "events", _today()):
        ts = ev.get("ts", "")
        try:
            hour = dt.datetime.fromisoformat(ts).hour
        except (ValueError, TypeError):
            continue
        st = ev.get("status", "failed")
        if 0 <= hour < 24:
            buckets[hour]["requests"] += 1
            if st in ("success", "failed", "aborted"):
                buckets[hour][st] += 1
    return buckets


# ---------- 看板聚合 ----------

@router.get("/admin/api/stats")
async def stats(request: Request, days: int = Query(default=7, ge=1, le=90)):
    """看板聚合（tech-design §4.8）：五维合并 + dimensions 可用维度键（前端 tab 数据驱动）。"""
    runtime = request.app.state.runtime
    today = dt.date.today()
    dims = ("by_model", "by_resource", "by_token", "by_provider", "by_account")
    merged = {dim: {} for dim in dims}
    merged["totals"] = {}
    trend: list[dict] = []
    for i in range(days - 1, -1, -1):
        day = (today - dt.timedelta(days=i)).strftime("%Y%m%d")
        agg = _agg_of_day(runtime, day)
        totals = agg.get("totals", {})
        trend.append({
            "date": day,
            "requests": totals.get("requests", 0),
            "success": totals.get("success", 0),
            "failed": totals.get("failed", 0),
            "aborted": totals.get("aborted", 0),
            "input_tokens": totals.get("input_tokens", 0),
            "output_tokens": totals.get("output_tokens", 0),
            "images_count": totals.get("images_count", 0),
        })
        for dim in dims:
            for key, bucket in agg.get(dim, {}).items():
                _merge_bucket(merged[dim].setdefault(key, {}), bucket)
        _merge_bucket(merged["totals"], totals)
    # 均值指标（分母防 0）
    t = merged["totals"]
    reqs = t.get("requests", 0) or 1
    merged["averages"] = {
        "duration_ms": round(t.get("duration_ms_total", 0) / reqs),
        "ttft_ms": round(t.get("ttft_ms_total", 0) / (t.get("ttft_count", 0) or 1)),
    }
    return {"days": days, "trend": trend, "dimensions": list(dims), **merged,
            "pricing": [p.model_dump(mode="json") for p in runtime.config.pricing]}


# ---------- 请求日志 ----------

@router.get("/admin/api/logs/requests")
async def logs_requests(request: Request,
                        date: str | None = Query(default=None),
                        limit: int = Query(default=100, ge=1, le=500),
                        offset: int = Query(default=0, ge=0),
                        model: str | None = Query(default=None),
                        status: str | None = Query(default=None),
                        token: str | None = Query(default=None)):
    runtime = request.app.state.runtime
    day = date or _today()
    rows = _read_jsonl(runtime, "events", day)
    if model:
        rows = [r for r in rows if r.get("system_model") == model]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if token:
        rows = [r for r in rows if r.get("client_token_id") == token]
    rows.reverse()  # 最新在前
    total = len(rows)
    return {"date": day, "total": total, "offset": offset, "limit": limit,
            "rows": rows[offset:offset + limit]}


@router.get("/admin/api/logs/switches")
async def logs_switches(request: Request,
                        date: str | None = Query(default=None),
                        limit: int = Query(default=100, ge=1, le=500)):
    runtime = request.app.state.runtime
    day = date or _today()
    rows = _read_jsonl(runtime, "switch-events", day)
    rows.reverse()
    return {"date": day, "total": len(rows), "rows": rows[:limit]}


# ---------- 资源连通性测试（FR-9.1 最小实现） ----------

@router.post("/admin/api/resources/test")
async def resource_test(request: Request):
    """连通性测试（FR-9.1 最小版）：发最小对话请求，返回连通 / 延迟 / 错误摘要。

    两种调用形态：
    - {"resource": rid, "model": m}：已存资源，走其配置的适配器与 Key；
    - {"base_url": u, "api_key": k, "model": m}：未落库草稿直连测试（临时适配器，用后即毁）。
    超时取 min(30s, 全局单次尝试超时)。
    """
    runtime = request.app.state.runtime
    body = await request.json()
    rid = (body.get("resource") or "").strip() if isinstance(body, dict) else ""
    model = (body.get("model") or "").strip() if isinstance(body, dict) else ""
    base_url = (body.get("base_url") or "").strip() if isinstance(body, dict) else ""
    api_key = (body.get("api_key") or "").strip() if isinstance(body, dict) else ""
    # v2.0 §18.2 ②：草稿直连测试需按协议选适配器（默认 openai，向后兼容）
    protocol = (body.get("protocol") or "openai").strip() if isinstance(body, dict) else "openai"
    if protocol not in ("openai", "anthropic", "gemini"):
        protocol = "openai"
    if not model or (not rid and not (base_url and api_key)):
        return JSONResponse(status_code=400,
                            content={"error": {"message": "参数缺失（需 resource 或 base_url+api_key）"}})

    close_after = False
    if rid:
        r = next((x for x in runtime.config.resources if x.id == rid), None)
        if r is None:
            return JSONResponse(status_code=400,
                                content={"error": {"message": "资源不存在"}})
        adapter = runtime.adapters.get(rid)
        key = runtime.key_values.get(rid, "")
        # 🔴 两类接入的凭据位置不同（§22.5-2 互斥契约）：`product` 非空 = 账号体系供给的资源，
        #    `api_key` **恒为空串**、凭据由适配器自解（§22.3）—— 原先无条件要求 key，
        #    使账号侧资源的检测**永远**回「无可用出站适配器或 Key」（审计 P2 的死路径）。
        if adapter is None:
            gap = ""
            try:
                gap = str((getattr(runtime, "_adapter_errors", None) or {}).get(rid) or "")
            except Exception:  # noqa: BLE001 — 诊断不得反过来打死检测
                pass
            return JSONResponse(status_code=400, content={"error": {"message":
                "该资源没有可用的出站适配器"
                + (f"（构造失败：{gap}）" if gap else
                   ("（产品出站前提未注入，如签名器/验证码求解器）" if (r.product or "").strip()
                    else "（Key 缺失）"))}})
        if not key and not (r.product or "").strip():
            return JSONResponse(status_code=400,
                                content={"error": {"message": "该资源无可用 Key（按量 API 资源必须配 Key）"}})
    else:
        # v2.0 §18.2 ②：健康测试同样按协议分支（v1.6 无条件 OpenAIOutAdapter）
        adapter = build_adapter(protocol, base_url)
        key = api_key
        close_after = True

    req_body = {"messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1, "stream": False}
    t0 = time.monotonic()
    try:
        await adapter.chat_nonstream(
            key, model, req_body,
            timeout=min(30, runtime.config.gateway.attempt_timeout_seconds))
        out = {"ok": True, "latency_ms": int((time.monotonic() - t0) * 1000), "model": model}
    except Exception as e:  # noqa: BLE001 — 连通性测试任何失败都原样回报
        out = {"ok": False, "latency_ms": int((time.monotonic() - t0) * 1000),
               "model": model, "error": error_summary(e)}
    if close_after:
        with contextlib.suppress(Exception):
            await adapter.aclose()
    return out


@router.get("/admin/api/zcode/quota")
async def zcode_quota(request: Request):
    """ZCode 额度聚合（**管理端点**，v2.0 §19 M5-2）。

    🔴 **不做对外端点** —— 与 §16.1「运营接口不是 OpenAI 兼容 API 的组成部分」一致。
    消费者 = 二期「账号授权」页的「用量」面板（`templates/template-vendor-accounts.html`）。

    数据源（2026-10-02 §17 改述后的定位）：本端点是**离线聚合面** —— 读
    `zq.read_account_snapshot()` 的**客户端日志**快照（本机实况：账号根内没有任何 `.log`，
    16/16 号恒 `ok=False`）。额度的**实时源**不在这里，而是联网腿
    （管理端「刷新额度」按钮 = `POST /admin/api/accounts/zcode/{name}/quota`，
    自动腿由 `gateway.zcode.quota_net` 授权，默认关）。
    旧注释的「客户端日志 → 旧快照 → 联网兜底」优先级已被实测推翻：那句"绕开签名风控"
    的前提是联网取数需要 `X-Client-Sig/Nonce/Pow`，而一条 `Bearer + X-Device-Mid` 的只读
    GET 就取到了数值（【探针台账】§2，**仅测这条 GET**）。
    """
    from model_gateway.upstream.zcode import quota as zq
    from model_gateway.upstream.zcode import store as zstore

    runtime = request.app.state.runtime
    accounts = zstore.list_accounts()

    snapshots = []
    for acc in accounts:
        snap = _zcode_quota_of(runtime, zq, zstore, acc.name)
        snap.account = acc.name
        snapshots.append(snap)

    # 🔴 §17 触发时机③：管理端点也顺带回写额度 → 让 M5-3 的预留闸门拿到最新值
    #   （否则只有 ops tick 一个写入点，停机时手动查额度不影响选路）
    zq.refresh_runtime_quotas(runtime, accounts=[a.name for a in accounts])

    out = zq.aggregate(snapshots)
    out["updated_at"] = int(time.time() * 1000)
    return out


def _zcode_quota_of(runtime, zq, zstore, account: str):
    """单账号额度：日志优先 → 无记录返回 `ok=False` 快照（§17）。

    实现收敂到 `quota.read_account_snapshot`（验收发现此处与 ops 侧各写一份，
    且 ops 刷新路径**没有**回写 `ResourceState` → 额度预扣永远空转）。
    """
    return zq.read_account_snapshot(zstore.accounts_root(), account)


@router.post("/admin/api/dialects/reload")
async def dialects_reload(request: Request):
    """重载方言表（v2.0 §13.4）。

    🔴 为什么需要：方言表在**启动时加载一次**进内存快照（§13.4 明确"不新增 mtime 轮询"）。
    `mgw probe` 是**独立进程**写完 `data/dialects.json` 后，必须**显式触发**运行中的网关重载，
    否则 `/v1/models` 的 `caps.thinkingLevelMap` 不会更新（验收发现的缺口）。
    """
    runtime = request.app.state.runtime
    before = len(getattr(runtime.dialects, "entries", {}))
    runtime.reload_dialects()
    after = len(getattr(runtime.dialects, "entries", {}))
    return {"ok": True, "before": before, "after": after}


@router.post("/admin/api/ops/ack")
async def ops_ack(request: Request):
    """确认运营失败（清零顶栏红点，v2.0 §21 / M-IX-2）。

    🔴 为什么需要：未读失败若**只增不减**，一次失败后顶栏红点会永久常亮。
    实现是**写已确认水位**（`ops.runner.ack_reports`）而不是清内存计数器 ——
    红点的数来自 jsonl，水位也必须落在文件里才能与它同口径（跨进程、跨重启一致）。
    """
    from model_gateway.ops.runner import ack_reports

    cleared = ack_reports(request.app.state.runtime.usage_dir)
    return {"ok": True, "cleared": cleared}


@router.post("/admin/api/zcode/bench")
async def zcode_bench(request: Request):
    """CLI 领取遇风控 → 让**本进程**回写资源熔断（v2.0 §17 / §19 M4-4）。

    🔴 为什么需要：`mgw zcode claim` 是**独立进程**，改不到运行中网关的 `ResourceState`
    （在内存里）。原实现只有 cron 一条腿生效 —— 验收复发的"接线但半生效"。
    与 `/admin/api/ops/ack`、`/admin/api/dialects/reload` 同一类跨进程出口。

    🔴 成因由调用方**显式**声明（2026-09-29 用户裁决「读时重判」）：载荷里的 `circuit`
    决定这次冷却是否登记为「全局熔断按住」。
    - 缺省 = `true`：本端点的定义就是"领取遇风控 → 回写熔断"，且默认 `reason`
      已是 §17 的熔断文案；CLI 那条腿（`ops/builtin/zcode_claim.py`）不带这个字段，
      风控成因保持不变。
    - 别的原因（额度耗尽 / 手工挡一段）请带 `"circuit": false`，否则用户删掉
      `circuit.json` 时这条冷却会被一起放开 —— 那是"在别的观察期内提前放行"。
      **不靠 `reason` 文案猜成因**：文案一改标记就悄悄错位。
    """
    from model_gateway.upstream.zcode import quota as zq

    body = await request.json()
    account = str(body.get("account") or "").strip()
    reason = str(body.get("reason") or "ZCode 风控熔断（30min，全局）")
    seconds = body.get("seconds")
    secs = float(seconds) if seconds is not None else None
    runtime = request.app.state.runtime
    # 只认**显式**的假值（`false` / `0` / `no`）；其余（含缺省）按熔断成因登记
    declared = str(body["circuit"]).strip().lower() if "circuit" in body else "true"
    is_circuit = declared not in ("false", "0", "no")
    # 🔴 真正被登记为"熔断按住"的前提是熔断**此刻真的成立**（`circuit_hold_scope` 里判）：
    #    响应里回的是这个交集，而不是调用方的声明本身 —— 否则 `circuit_held: true`
    #    会在"文件已经没了"的回写里谎报"这次是熔断按住の"。
    circuit_held = is_circuit and bool(zq.get_circuit().active())
    # 🔴 scope=global → 按 §17 的**全局熔断**口径一并回写全部 ZCode 账号；
    #    只 bench 上报的那一个号是半生效（风控是账号集级别，换号继续打只会延长风控）
    scope = str(body.get("scope") or "global").lower()
    if scope == "global":
        done = zq.bench_all_zcode(runtime, reason=reason, seconds=secs, circuit=is_circuit)
        return {"ok": True, "scope": "global", "reason": reason, "benched": done,
                "circuit_held": circuit_held}
    if not account:
        return JSONResponse(status_code=400, content={"error": "scope=account 时 account 必填"})
    with zq.circuit_hold_scope(runtime, held=is_circuit):
        done = zq.bench_account(runtime, account, reason=reason, seconds=secs)
    return {"ok": True, "scope": "account", "account": account, "benched": done,
            "circuit_held": circuit_held}


# ---------- 配置读写 ----------

def _autogen_ids(body: dict) -> None:
    """系统自动生成 ID / 密钥值（Q18-②/④：用户无需输入，保存时服务端补齐）。

    - resources[].id → res-xxxxxxxx（资源 id 全局唯一）
    - access_tokens[].id → tok-xxxxxxxx；value → mg-<32hex>（接入密钥）
    - 资源 id 为 ``@`` 开头占位符（Q19-②：新增资源时界面内即配模型映射，
      映射条目引用占位 id）→ 生成真实 id 并同步改写 models[].resources[].resource 引用
    生成时避开请求内已有 id，冲突由后续 Pydantic 唯一性校验兜底。
    """
    def gen(prefix: str, taken: set) -> str:
        while True:
            v = prefix + secrets.token_hex(4)
            if v not in taken:
                taken.add(v)
                return v

    placeholder: dict[str, str] = {}
    res_taken = {(r.get("id") or "").strip() for r in body.get("resources", []) or []}
    for r in body.get("resources", []) or []:
        rid = (r.get("id") or "").strip()
        if not rid or rid.startswith("@"):
            real = gen("res-", res_taken)
            if rid:
                placeholder[rid] = real
            r["id"] = real
    if placeholder:  # 改写模型映射中的占位引用（Q19-②）
        for m in body.get("models", []) or []:
            if not isinstance(m, dict):
                continue
            entries = m.get("resources")
            if not isinstance(entries, list):
                continue
            for e in entries:
                if isinstance(e, dict) and e.get("resource") in placeholder:
                    e["resource"] = placeholder[e["resource"]]
    gw = body.get("gateway")
    if isinstance(gw, dict):
        toks = gw.get("access_tokens")
        if isinstance(toks, list):
            tok_taken = {(t.get("id") or "").strip() for t in toks if isinstance(t, dict)}
            for t in toks:
                if not isinstance(t, dict):
                    continue
                if not (t.get("id") or "").strip():
                    t["id"] = gen("tok-", tok_taken)
                if not (t.get("value") or "").strip():
                    t["value"] = "mg-" + secrets.token_hex(16)


@router.get("/admin/api/config")
async def get_config(request: Request, reveal: int = Query(default=0)):
    """当前配置（Q18-② 扁平资源）。默认脱敏 resources[].api_key；接入密钥明文（UI 复制用）。

    🔴 每条映射条目额外带一个**派生位** `mapping_enabled` = `AppConfig.mapping_enabled`
    （Q33-① 唯一判据：厂商侧看条目位、账号侧看产品位 + 号开关）。界面（「网关模型管理」
    资源池行与"N 个资源"计数）只读这一位——判据在前端再写一份就会分叉（映射弹窗说进池、
    资源池表说不进池），正是 Q33 要消灭的"两套真相"。写回时该键被 Pydantic 忽略
    （`ModelResource` 没这个字段），不会污染配置文件。
    """
    runtime = request.app.state.runtime
    cfg = runtime.config
    data = cfg.model_dump(mode="json")
    if not reveal:
        for r in data.get("resources", []):
            if r.get("api_key"):
                r["api_key"] = mask_key(r["api_key"])
    by_id = {r.id: r for r in cfg.resources}
    # `model_dump` 保序 ⇒ 逐位对齐即可，不必再按 id 找一遍（找错了就是把 A 条目的判据写到 B 上）
    for m_dump, m in zip(data.get("models", []), cfg.models):
        for e_dump, e in zip(m_dump.get("resources", []), m.resources):
            res = by_id.get(e.resource)
            e_dump["mapping_enabled"] = bool(
                cfg.mapping_enabled(res, e, m.name) if res is not None else e.enabled)
    return data


def _unmask_resources(body: dict, current: AppConfig) -> None:
    """PUT 还原：界面传回的脱敏 Key 值 → 原明文（仅当值与当前脱敏形态一致时）。"""
    cur = {r.id: r.api_key for r in current.resources}
    for r in body.get("resources", []) or []:
        v = r.get("api_key") or ""
        if v and r.get("id") in cur and v == mask_key(cur[r["id"]]):
            r["api_key"] = cur[r["id"]]


@router.put("/admin/api/config")
async def put_config(request: Request):
    """保存配置：ID/密钥缺省自动生成 → 脱敏还原 → Pydantic 校验 → 原子写 → 热重载（失败 400 保留旧快照）。"""
    runtime = request.app.state.runtime
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"status": "rejected",
                                                      "errors": ["请求体须为配置对象"]})
    _autogen_ids(body)
    _unmask_resources(body, runtime.config)
    try:
        config = AppConfig.model_validate(body)
    except Exception as e:  # noqa: BLE001 — Pydantic 校验错误统一转为列表
        errors = []
        for err in getattr(e, "errors", lambda: [])():
            loc = ".".join(str(x) for x in err.get("loc", []))
            errors.append(f"{loc}: {err.get('msg', str(e))}" if loc else str(err.get("msg", e)))
        if not errors:
            errors = [str(e)]
        return JSONResponse(status_code=400, content={"status": "rejected", "errors": errors})
    # 🔴 落盘只用**一份实现**：`config.loader.save_config`（tempfile + fsync + os.replace，
    #    且 `BaseException` 也清临时文件）。原先这里又手写了一遍原子写，
    #    于是 `save_config` 变成"只有测试在用的死函数" —— 两份实现同一件事，
    #    将来只改一份就是 bug（接线护栏把它报出来后按此口径收敛）。
    try:
        save_config(config, runtime.config_path)
    except OSError as e:
        return JSONResponse(status_code=500, content={"status": "rejected",
                                                      "errors": [f"写入失败: {e}"]})
    # 写入成功 → 热重载（校验已在内存完成，reload 只会因文件竞争失败）
    ok, errors = await runtime.reload_from_file()
    if not ok:
        return JSONResponse(status_code=400, content={"status": "rejected", "errors": errors})
    return {"status": "ok", "message": "配置已保存并生效"}


@router.post("/admin/api/config/reload")
async def reload_config(request: Request):
    runtime = request.app.state.runtime
    ok, errors = await runtime.reload_from_file()
    if ok:
        return {"status": "ok", "message": "配置已重载"}
    return JSONResponse(status_code=400, content={"status": "rejected", "errors": errors})


# ---------- 枚举池 ----------

def _enums_path(request: Request) -> Path:
    return request.app.state.runtime.enums_path


def _dump_enums(entries: list[EnumEntry], path: Path) -> None:
    data = {"entries": [e.to_dict() for e in entries]}
    tmp_name = None
    try:
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".yaml.tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp_name, path)
    finally:
        if tmp_name and os.path.exists(tmp_name):
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)


@router.get("/admin/api/enums")
async def get_enums(request: Request):
    """枚举池当前条目（含来源标记：用户文件 or 内置默认）。"""
    path = _enums_path(request)
    runtime = request.app.state.runtime
    entries = [e.to_dict() for e in runtime.enum_pool.entries.values()]
    # 🔴 `source` 说的是"**这份数据从哪来**"，不是"那个文件在不在"（验收 L-3）：
    # 空文件会被 `load_enum_pool` 回落成内置目录，此时报 source=file 等于骗用户。
    from_file = path.exists() and bool(runtime.enum_pool.entries)
    return {"source": "file" if from_file else "builtin", "path": str(path),
            "entries": entries}


@router.put("/admin/api/enums")
async def put_enums(request: Request):
    """保存枚举池（全量替换）→ 写 model-enums.yaml → 重载生效。"""
    runtime = request.app.state.runtime
    path = _enums_path(request)
    body = await request.json()
    items = body.get("entries") if isinstance(body, dict) else body
    if not isinstance(items, list):
        return JSONResponse(status_code=400, content={"status": "rejected",
                                                      "errors": ["请求体须含 entries 数组"]})
    names = [i.get("name") for i in items if isinstance(i, dict)]
    if len(names) != len(items) or any(not n for n in names):
        return JSONResponse(status_code=400, content={"status": "rejected",
                                                      "errors": ["存在缺失 name 的条目"]})
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        return JSONResponse(status_code=400,
                            content={"status": "rejected", "errors": [f"name 重复: {dup}"]})
    if not items:
        # 🔴 空清单**不能**当"保存成功"：`load_enum_pool` 见空文件会回落内置目录，
        # 于是界面写着"已保存并生效"、实际一条都没生效，且 GET 还报 source=file
        # （验收 L-3）。真要回到内置目录，删掉该文件才是受支持的路径。
        return JSONResponse(status_code=400, content={"status": "rejected", "errors": [
            "entries 不能为空：清空枚举池会被网关回落为内置目录，等于没保存。"
            "要恢复内置目录请直接删除该文件：" + str(_enums_path(request))]})
    entries = [EnumEntry(
        name=i["name"], display=i.get("display", ""), aliases=list(i.get("aliases", [])),
        group=i.get("group", ""), endpoint=i.get("endpoint", "chat"),
        response_format_url_hours=i.get("response_format_url_hours"),
        only_base64_image=bool(i.get("only_base64_image", False)),
        vendor=i.get("vendor", ""),
        context_window=i.get("context_window"), max_output=i.get("max_output"),
        image_input=bool(i.get("image_input", False)),
        video_input=bool(i.get("video_input", False)),
        audio_input=bool(i.get("audio_input", False)),
        reasoning=bool(i.get("reasoning", False)),
        effort_levels=[str(x) for x in i.get("effort_levels", [])],
        params_default=dict(i.get("params_default", {})),
        # GET 会导出这个键，PUT 若不读回来 → 编辑一次枚举池就把
        # 用户手写的 `tool_call: false` 全部抹回默认值
        tool_call=bool(i.get("tool_call", True)),
    ) for i in items]
    path.parent.mkdir(parents=True, exist_ok=True)
    _dump_enums(entries, path)
    ok, errors = await runtime.reload_from_file()
    if not ok:
        return JSONResponse(status_code=400, content={"status": "rejected", "errors": errors})
    return {"status": "ok", "message": "枚举池已保存并生效"}


# ---------- 厂商预设 ----------

@router.get("/admin/api/presets")
async def get_presets():
    """厂商预设清单（tech-design §4.7；PRD FR-1.2，INT-46）。

    每条附 billing_display：空/未知计费口径 →「—」（前端渲染降级）；
    原始 billing 保留。扩展原则：新增厂商 = 仅加一条预设数据，UI 零改动。
    """
    return {"presets": [{**p, "billing_display": display_billing(p)}
                        for p in list_presets()]}


# ---------- 系统运行控制（tech-design §4.10-②；PRD FR-12.1） ----------

@router.post("/admin/api/system/stop")
async def system_stop(request: Request):
    """优雅停机：先返回受理确认，再置 should_exit（在途请求收尾后进程退出 + 释放锁）。

    server 句柄仅主进程形态（main() Server 化启动）挂载 app.state——测试内嵌形态
    无句柄时返回 503，明确「当前运行形态不可用」而非静默无效。
    """
    server = getattr(request.app.state, "server", None)
    if server is None:
        return JSONResponse(
            status_code=503,
            content={"error": {"message": "系统控制在当前运行形态不可用（仅主进程启动形态支持）"}})
    server.should_exit = True
    return {"status": "stopping", "message": "网关停止已受理：在途请求收尾后进程退出"}


@router.post("/admin/api/system/restart")
async def system_restart(request: Request):
    """自重启：置 restart_requested + should_exit——优雅停机 + 释放锁后 main() 执行 execv
    进程映像替换（PID 不变、同端口重绑、配置重读、锁重新登记）。"""
    server = getattr(request.app.state, "server", None)
    if server is None:
        return JSONResponse(
            status_code=503,
            content={"error": {"message": "系统控制在当前运行形态不可用（仅主进程启动形态支持）"}})
    request.app.state.restart_requested = True
    server.should_exit = True
    return {"status": "restarting", "message": "网关重启已受理：优雅停机后同端口自动重启"}
