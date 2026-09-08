"""Model-Gateway 入口：装配 + uvicorn 启动（tech-design §7 / §10.1）。

- Runtime：热重载原子替换的运行时聚合（config/resources/classifier/adapters/枚举池）
- 生命周期：事件流水单写 task + 日聚合 task + 配置 mtime 轮询热重载
- 启动：python -m model_gateway.main；配置 data/config.yaml（MG_CONFIG 可覆盖路径）
"""

from __future__ import annotations

import atexit
import asyncio
import contextlib
import datetime as dt
import json
import os
import sys
import threading
import time
from collections import deque
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from model_gateway import __version__
from model_gateway.adapters.openai_out import OpenAIOutAdapter
from model_gateway.api.admin import router as admin_router
from model_gateway.api.anthropic import router as anthropic_router
from model_gateway.api.auth import AuthMiddleware
from model_gateway.api.openai_compat import router as openai_router
from model_gateway.config.loader import ConfigError, load_config
from model_gateway.config.schemas import AppConfig
from model_gateway.core.cancel import CancelRegistry
from model_gateway.core.errors import ErrorClassifier
from model_gateway.core import instance_lock
from model_gateway.core.ir import ReasoningSpec
from model_gateway.core.resources import ResourceManager
from model_gateway.core.scheduler import Scheduler
from model_gateway.enums.matcher import EnumPool, load_enum_pool
from model_gateway.stats.aggregate import aggregate_day
from model_gateway.stats.events import EventLogger

CONFIG_ENV = "MG_CONFIG"
DEFAULT_CONFIG = Path("data") / "config.yaml"
ENUMS_PATH = Path("data") / "model-enums.yaml"
USAGE_DIR = Path("data") / "usage"
LOCK_PATH = Path("data") / instance_lock.LOCK_FILENAME  # 单实例锁（tech §4.10-③，与 USAGE_DIR 同口径固定 data/）


class Runtime:
    """运行时聚合：热重载时整体原子替换可变字段（在途请求绑定的快照不受影响）。"""

    def __init__(self, config: AppConfig, config_path: Path,
                 usage_dir: Path | None = None, enums_path: Path | None = None):
        self.config_path = config_path
        self.usage_dir = Path(usage_dir) if usage_dir else USAGE_DIR
        self.enums_path = Path(enums_path) if enums_path else ENUMS_PATH
        self.started_mono = time.monotonic()
        self.resources = ResourceManager()
        self.classifier = ErrorClassifier(config.error_rules)
        self.enum_pool: EnumPool = load_enum_pool(self.enums_path)
        self.adapters: dict[str, OpenAIOutAdapter] = {}
        self.key_values: dict[str, str] = {}
        self.resource_reasoning: dict[tuple[str, str], ReasoningSpec | None] = {}
        self.model_params: dict[str, dict] = {}  # 网关级模型参数（Q24）：模型名 → 注入参数
        self.events = EventLogger(self.usage_dir, retention_days=config.gateway.retention_days)
        self.cancel_registry = CancelRegistry()
        self.switch_ring: deque = deque(maxlen=200)
        self.scheduler = Scheduler(self)
        self._reload_lock = threading.Lock()
        self.config: AppConfig = config
        self._apply(config)

    def _apply(self, config: AppConfig) -> None:
        """按新快照重建派生件（资源状态按 resource_id 保留，tech §8-4）。"""
        self.config = config
        self.resources.rebuild(config)
        self.classifier = ErrorClassifier(config.error_rules)
        self.enum_pool = load_enum_pool(self.enums_path)
        # key 值索引（资源 id 唯一，schemas 已保证）
        self.key_values = {r.id: r.api_key for r in config.resources}
        # 资源级推理默认（Q15）：(resource_id, vendor_model) → 默认值
        reasoning_map: dict[tuple[str, str], ReasoningSpec | None] = {}
        for m in config.models:
            for r in m.resources:
                rd = r.reasoning
                reasoning_map[(r.resource, r.model)] = (
                    ReasoningSpec(enabled=rd.enabled, effort=rd.effort) if rd else None)
        self.resource_reasoning = reasoning_map
        # 网关级模型参数（Q24）：系统模型名 → 出站注入参数（请求级同名字段优先，仅 chat）
        self.model_params = {m.name: dict(m.params) for m in config.models if m.params}
        # 出站适配器（按资源 id 索引；base_url 变更才重建，防在途连接泄漏）
        new_adapters: dict[str, OpenAIOutAdapter] = {}
        for r in config.resources:
            if not r.base_url:
                continue
            old = self.adapters.get(r.id)
            if old is not None and old.base_url == r.base_url.rstrip("/"):
                new_adapters[r.id] = old
            else:
                new_adapters[r.id] = OpenAIOutAdapter(
                    r.base_url, needs_base64=self.enum_pool.needs_base64_image)
        self.adapters = new_adapters

    async def reload_from_file(self) -> tuple[bool, list[str]]:
        """热重载：校验通过 → 原子替换；失败 → 保留旧快照（INT-19 ②）。"""
        with self._reload_lock:
            try:
                config = load_config(self.config_path)
            except ConfigError as e:
                return False, e.errors
            self._apply(config)
            return True, []

    async def aclose(self) -> None:
        for adapter in self.adapters.values():
            with contextlib.suppress(Exception):
                await adapter.aclose()


def _load_config_or_exit(config_path: Path) -> AppConfig:
    """加载并校验配置：失败 → 打印错误、退出码 2（create_app 与 main() 共用口径）。"""
    try:
        return load_config(config_path)
    except ConfigError as e:
        print("配置校验失败，拒绝启动：", file=sys.stderr)
        for err in e.errors:
            print(f"  - {err}", file=sys.stderr)
        raise SystemExit(2) from e


class _StaticNoCacheMiddleware:
    """静态 UI 资源禁用缓存（Q19-①：浏览器缓存旧 JS/CSS 导致界面更新不可见/模块混载）。

    对 text/html / text/css / JavaScript 响应追加 Cache-Control: no-store——
    本地静态资源无缓存价值，no-store（不落盘）比 no-cache（协商 304）更彻底：
    杜绝浏览器缓存新旧混载的 ES 模块导致 import 失败、内容区空白（2026-09-05 实测）；
    /admin/api 等 JSON 响应不受影响。
    """

    _STATIC_TYPES = ("text/html", "text/css", "text/javascript", "application/javascript")

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message) -> None:  # type: ignore[no-untyped-def]
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                ctype = next((v.decode("latin-1") for k, v in headers
                              if k == b"content-type"), "")
                if any(t in ctype for t in self._STATIC_TYPES):
                    headers.append((b"cache-control", b"no-store"))
            await send(message)

        await self.app(scope, receive, send_wrapper)


def create_app(config_path: Path | None = None, *,
               usage_dir: Path | None = None, enums_path: Path | None = None) -> FastAPI:
    """装配 FastAPI 应用（测试与启动共用；usage_dir/enums_path 供测试隔离注入）。"""
    config_path = config_path or Path(os.environ.get(CONFIG_ENV) or DEFAULT_CONFIG)
    config = _load_config_or_exit(config_path)

    runtime = Runtime(config, config_path, usage_dir=usage_dir, enums_path=enums_path)
    for warning in config.warnings:
        print(f"[config 警告] {warning}", file=sys.stderr)
    if not config.gateway.access_tokens:
        print("[config 警告] 未配置任何接入密钥：/v1 端点免鉴权放行（本地单用户场景）", file=sys.stderr)

    app = FastAPI(title="Model-Gateway", version=__version__, docs_url=None, redoc_url=None)
    app.state.runtime = runtime
    app.state.config_path = config_path
    app.state.config_file_loaded = config_path.exists()

    app.include_router(openai_router)
    app.include_router(anthropic_router)
    app.include_router(admin_router)

    @app.get("/health")
    async def health() -> dict:
        cfg = runtime.config
        return {
            "status": "ok",
            "version": __version__,
            "config": {"path": str(config_path), "file_loaded": config_path.exists(),
                       "warnings": cfg.warnings},
            "gateway": {"host": cfg.gateway.host, "port": cfg.gateway.port,
                        "attempt_timeout_seconds": cfg.gateway.attempt_timeout_seconds,
                        "request_total_budget_seconds": cfg.gateway.request_total_budget_seconds},
            "scheduling": {"max_active_per_model": cfg.scheduling.max_active_per_model,
                           "fail_threshold": cfg.scheduling.fail_threshold,
                           "retry_per_request": cfg.scheduling.retry_per_request},
            "resources": len(cfg.resources),
            "system_models": len(cfg.models),
            "access_tokens": len(cfg.gateway.access_tokens),
        }

    # 鉴权中间件（纯 ASGI；持 runtime 引用取最新令牌）
    app.add_middleware(AuthMiddleware, runtime_provider=lambda: app.state.runtime)
    # 静态 UI no-cache（Q19-①：防浏览器缓存旧界面）
    app.add_middleware(_StaticNoCacheMiddleware)

    # Web 管理界面（tech §4.9：无构建静态资源本地内置；置于全部 API 路由之后挂载，
    # 免遮蔽 /health 与 /admin/api/*；html=True 使 / 返回 index.html）
    static_dir = Path(__file__).parent / "web" / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="web")

    @app.on_event("startup")
    async def _startup() -> None:
        runtime.events.start()
        await _write_daily_snapshot(runtime)
        app.state.background_tasks = [
            asyncio.get_running_loop().create_task(_reload_watcher(app)),
            asyncio.get_running_loop().create_task(_hourly_aggregation(app)),
        ]

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        for t in getattr(app.state, "background_tasks", []):
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        await runtime.events.stop()
        await runtime.aclose()

    return app


async def _reload_watcher(app: FastAPI) -> None:
    """mtime 轮询热重载（tech §4.7 双触发之①；1s 间隔）。"""
    runtime: Runtime = app.state.runtime
    last_mtime: float | None = None
    initialized = False
    while True:
        try:
            mtime = runtime.config_path.stat().st_mtime if runtime.config_path.exists() else None
        except OSError:
            mtime = None
        if initialized and mtime != last_mtime:
            ok, errors = await runtime.reload_from_file()
            if ok:
                print(f"[hot-reload] 配置已重载：{runtime.config_path}")
            else:
                print(f"[hot-reload] 校验失败，保留旧配置：{'；'.join(errors)}", file=sys.stderr)
        last_mtime = mtime
        initialized = True
        await asyncio.sleep(1.0)


async def _hourly_aggregation(app: FastAPI) -> None:
    """日聚合：每小时整点重算当日 events → daily-YYYYMMDD.json（tech §4.8）。"""
    runtime: Runtime = app.state.runtime
    while True:
        now = dt.datetime.now()
        nxt = (now + dt.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        await asyncio.sleep((nxt - now).total_seconds())
        with contextlib.suppress(Exception):
            await _write_daily_snapshot(runtime)


async def _write_daily_snapshot(runtime: Runtime) -> None:
    day = dt.date.today()
    path = runtime.usage_dir / f"events-{day.strftime('%Y%m%d')}.jsonl"
    events: list[dict] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
    snapshot = runtime.usage_dir / f"daily-{day.strftime('%Y%m%d')}.json"
    tmp = snapshot.with_suffix(".tmp")
    tmp.write_text(json.dumps(aggregate_day(events), ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, snapshot)


def main() -> None:
    # tech-design §4.10-① 启动序列（严格顺序）：加载配置 → 单实例锁 → 绑定端口启动服务
    config_path = Path(os.environ.get(CONFIG_ENV) or DEFAULT_CONFIG)
    cfg = _load_config_or_exit(config_path)  # ① 校验失败退出码 2 保持

    # ② 单实例锁：获取失败（已有实例）→ 打印后台地址后退出码 3，不启动/不换端口/不询问（§4.10-④）
    result = instance_lock.acquire(LOCK_PATH, cfg.gateway.port)
    if not result.ok:
        ex = result.existing or {}
        base_url = ex.get("base_url") or f"http://127.0.0.1:{ex.get('port', cfg.gateway.port)}/"
        print(f"已有实例运行中：后台地址 {base_url}"
              f"（PID {ex.get('pid', '未知')}、启动时间 {ex.get('started_at', '未知')}）",
              file=sys.stderr)
        sys.exit(3)

    app = create_app(config_path)

    # ④ Server 化（拿句柄替代 uvicorn.run 直启）：server 挂 app.state 供 system 端点
    #    设置 should_exit（stop）；restart 端点置位 restart_requested（§4.10-①②）
    server = uvicorn.Server(uvicorn.Config(app, host=cfg.gateway.host,
                                           port=cfg.gateway.port, log_level="info"))
    app.state.server = server
    app.state.restart_requested = False

    # ⑤ atexit 兜底释放锁（uvicorn 自带 SIGINT/SIGTERM → should_exit 优雅停机；
    #    0.52.4 serve() 内置 capture_signals，无需自注册信号）
    atexit.register(instance_lock.release, LOCK_PATH, os.getpid())

    server.run()

    # 优雅停机完成（run() 返回）：显式释放锁（release 幂等，atexit 兜底）→
    # restart 请求则 execv 进程映像替换（必须排在停机收尾 + 锁释放之后，§4.10-②）
    instance_lock.release(LOCK_PATH, os.getpid())
    if getattr(app.state, "restart_requested", False):
        try:
            os.execv(sys.executable, [sys.executable, "-m", "model_gateway.main", *sys.argv[1:]])
        except OSError as e:
            # execv 失败兜底：锁已释放，可重新拉起；明确报错退出，不静默残留（§4.10-②）
            print(f"[restart] 自重启失败（execv：{e}）；单实例锁已释放，可重新启动网关",
                  file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
