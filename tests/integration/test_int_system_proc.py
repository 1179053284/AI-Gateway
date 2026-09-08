"""INT 系统运行控制·子进程级（INT-42 stop / INT-43 restart / INT-44 单实例互斥 / INT-45 陈旧锁）。

子进程设计（防污染真实 data/）：网关锁路径 data/gateway.lock 与 usage 目录均为相对 cwd
路径 → 每个用例独立 tmp_path 作 cwd + MG_CONFIG 指向 tmp 内配置，锁/事件全落
tmp_path/data/，天然隔离。进程输出重定向到 tmp 内日志文件（非 PIPE——uvicorn 访问
日志会撑爆管道缓冲区导致子进程写阻塞死锁）。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import yaml

ADMIN = {"id": "admin", "value": "proc-admin-token"}
USER = {"id": "user", "value": "proc-user-token"}


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _write_config(tmp_path: Path, port: int) -> Path:
    """最小可用配置：双令牌 + 随机高位端口；resources/models 空。"""
    cfg = {
        "gateway": {
            "host": "127.0.0.1",
            "port": port,
            "access_tokens": [ADMIN, USER],
        },
        "resources": [],
        "models": [],
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path


def _start(tmp_path: Path, config_path: Path, name: str):
    """启动网关子进程：cwd=tmp（锁/事件隔离）+ MG_CONFIG + 输出落 tmp 内日志文件。"""
    env = {**os.environ, "MG_CONFIG": str(config_path)}
    log_path = tmp_path / f"{name}.log"
    with open(log_path, "w", encoding="utf-8") as fh:
        proc = subprocess.Popen(
            [sys.executable, "-m", "model_gateway.main"],
            cwd=str(tmp_path), env=env,
            stdout=fh, stderr=subprocess.STDOUT)
    return proc, log_path


def _wait_health(proc, log_path: Path, port: int, *, deadline: float = 15.0,
                 require_down_first: bool = False) -> None:
    """轮询 /health 至 200。

    require_down_first=True（restart 场景）：先观察到旧实例下线（连接失败）再等到
    200——确保 200 来自 execv 后的新映像，而非停机前的旧实例。
    进程先死 → 立即失败并附日志输出（快速定位而非干等超时）。
    """
    t0 = time.monotonic()
    saw_down = False
    last = "未发起请求"
    while time.monotonic() - t0 < deadline:
        if proc.poll() is not None:
            raise AssertionError(
                f"网关进程提前退出（code={proc.returncode}）：\n{log_path.read_text(encoding='utf-8')}")
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.0, trust_env=False)
            if r.status_code == 200 and (saw_down or not require_down_first):
                return
            last = f"status={r.status_code}"
        except httpx.HTTPError as e:
            saw_down = True
            last = repr(e)
        time.sleep(0.05)
    raise AssertionError(f"/health 未在 {deadline}s 内就绪"
                         f"（require_down_first={require_down_first}，last={last}）")


def _kill(proc) -> None:
    """teardown 收尾：SIGKILL + 回收（防僵尸/泄漏；已退出则仅回收）。"""
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=10)


def _lock_data(tmp_path: Path) -> dict | None:
    try:
        return json.loads((tmp_path / "data" / "gateway.lock").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


class TestSystemStop:
    """INT-42：system/stop 优雅停机（PRD FR-12.1/FR-12.3）。"""

    def test_int_42_stop_graceful(self, tmp_path: Path):
        port = _free_port()
        config = _write_config(tmp_path, port)
        a, a_log = _start(tmp_path, config, "a")
        try:
            _wait_health(a, a_log, port)
            base = f"http://127.0.0.1:{port}"
            with httpx.Client(timeout=5.0, trust_env=False) as c:
                # Q18-①：管理端免鉴权（无令牌亦可受理）→ 受理确认（先返回再停机）→ 进程优雅退出
                r = c.post(f"{base}/admin/api/system/stop")
                assert r.status_code == 200
                assert r.json()["status"] == "stopping"
            a.wait(timeout=15)
            assert a.returncode == 0
            # 单实例锁已释放
            assert not (tmp_path / "data" / "gateway.lock").exists()
        finally:
            _kill(a)


class TestSystemRestart:
    """INT-43：system/restart execv 映像替换（PID 不变/同端口/配置重读/锁重新登记）。"""

    def test_int_43_restart_execv(self, tmp_path: Path):
        port = _free_port()
        config = _write_config(tmp_path, port)
        a, a_log = _start(tmp_path, config, "a")
        try:
            _wait_health(a, a_log, port)
            pid = a.pid
            base = f"http://127.0.0.1:{port}"
            with httpx.Client(timeout=5.0, trust_env=False) as c:
                r = c.post(f"{base}/admin/api/system/restart",
                           headers={"Authorization": f"Bearer {ADMIN['value']}"})
                assert r.status_code == 200
                assert r.json()["status"] == "restarting"
            # 优雅停机 → execv → 新映像上线（先见下线再恢复 200；execv 需重启时间）
            _wait_health(a, a_log, port, deadline=20.0, require_down_first=True)
            # PID 不变（execv 映像替换）+ 锁重新登记为同一 pid
            os.kill(pid, 0)
            lock = _lock_data(tmp_path)
            assert lock is not None and lock["pid"] == pid

            # 配置修改经 restart 重读生效（test-cases INT-43 ②）：追加一个令牌
            cfg = yaml.safe_load(config.read_text(encoding="utf-8"))
            cfg["gateway"]["access_tokens"].append(
                {"id": "extra", "value": "proc-extra-token"})
            config.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
            with httpx.Client(timeout=5.0, trust_env=False) as c:
                r = c.post(f"{base}/admin/api/system/restart",
                           headers={"Authorization": f"Bearer {ADMIN['value']}"})
                assert r.status_code == 200
            _wait_health(a, a_log, port, deadline=20.0, require_down_first=True)
            r = httpx.get(f"{base}/health", timeout=5.0, trust_env=False)
            assert r.status_code == 200
            assert r.json()["access_tokens"] == 3  # 双令牌 + 追加 1：新映像重读配置生效
        finally:
            _kill(a)


class TestSingleInstance:
    """INT-44：单实例互斥（第二进程退出码 3，原实例不受影响）。"""

    def test_int_44_second_instance_exits_3(self, tmp_path: Path):
        port = _free_port()
        config = _write_config(tmp_path, port)
        a, a_log = _start(tmp_path, config, "a")
        b = None
        try:
            _wait_health(a, a_log, port)
            # 同 cwd 同 env 启动第二实例 → 命中单实例锁
            b, b_log = _start(tmp_path, config, "b")
            b.wait(timeout=15)
            assert b.returncode == 3
            out = b_log.read_text(encoding="utf-8")
            assert "已有实例运行中" in out
            assert f"http://127.0.0.1:{port}/" in out  # 后台地址 = A 的端口
            # 原实例不受影响持续服务
            r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=5.0, trust_env=False)
            assert r.status_code == 200
        finally:
            if b is not None:
                _kill(b)
            _kill(a)


class TestStaleLock:
    """INT-45：陈旧锁自动清理（kill -9 残留 → 再启动正常接管）。"""

    def test_int_45_stale_lock_reclaimed(self, tmp_path: Path):
        port = _free_port()
        config = _write_config(tmp_path, port)
        a, a_log = _start(tmp_path, config, "a")
        c = None
        try:
            _wait_health(a, a_log, port)
            a.kill()  # SIGKILL：atexit 不执行 → 锁残留
            a.wait(timeout=10)
            lock_path = tmp_path / "data" / "gateway.lock"
            assert lock_path.exists()  # 陈旧锁确实残留
            # 同 cwd 再启动 → 判定 pid 已死 → 清理重写 → 正常启动
            c, c_log = _start(tmp_path, config, "c")
            _wait_health(c, c_log, port)
            lock = _lock_data(tmp_path)
            assert lock is not None and lock["pid"] == c.pid  # 锁已重写为新实例
        finally:
            if c is not None:
                _kill(c)
            _kill(a)
