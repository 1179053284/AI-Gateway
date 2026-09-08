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

import yaml
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from model_gateway import __version__
from model_gateway.adapters.openai_out import OpenAIOutAdapter
from model_gateway.config.loader import ConfigError, load_config
from model_gateway.config.presets import display_billing, list_presets
from model_gateway.config.schemas import AppConfig
from model_gateway.core.resources import vendor_label
from model_gateway.enums.matcher import BUILTIN_ENTRIES, EnumEntry
from model_gateway.stats.aggregate import aggregate_day
from model_gateway.stats.events import error_summary, mask_key

router = APIRouter()


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
    }


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
        if adapter is None or not key:
            return JSONResponse(status_code=400,
                                content={"error": {"message": "该资源无可用出站适配器或 Key"}})
    else:
        adapter = OpenAIOutAdapter(base_url)
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


# ---------- 配置读写 ----------# ---------- 配置读写 ----------

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
    """当前配置（Q18-② 扁平资源）。默认脱敏 resources[].api_key；接入密钥明文（UI 复制用）。"""
    runtime = request.app.state.runtime
    data = runtime.config.model_dump(mode="json")
    if not reveal:
        for r in data.get("resources", []):
            if r.get("api_key"):
                r["api_key"] = mask_key(r["api_key"])
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
    # 原子写（tempfile + os.replace 同目录）
    path = runtime.config_path
    tmp_name = None
    try:
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".yaml.tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(config.model_dump(mode="json", exclude={"warnings"}),
                           f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        os.replace(tmp_name, path)
    except OSError as e:
        if tmp_name:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
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
    return {"source": "file" if path.exists() else "builtin", "path": str(path),
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
