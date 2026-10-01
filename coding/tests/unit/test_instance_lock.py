"""UT-28：单实例锁检测纯逻辑（tech-design §4.10-③④，PRD FR-12.3）。

五场景 + 释放语义，全部 tmp_path 隔离；pid 存活/已死经 monkeypatch os.kill 模拟：
① 无锁 → 写入；② pid 存活非自身 → 返回已有实例信息（退出码 3 语义）；
③ 陈旧锁（pid 已死）→ 清理重写；④ pid==自身（execv 重启）→ 覆盖重写；
⑤ 半行 JSON 损坏 → 按陈旧锁清理重写；⑥ release 幂等语义。
"""

from __future__ import annotations

import datetime as dt
import json
import os

from model_gateway.core import instance_lock

OTHER_PID = 999999  # 非自身的假想 pid（存活/已死均由 monkeypatch 决定）


def _write_raw_lock(path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _read_lock_file(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ① 无锁文件 → acquire ok，锁写入且字段完整
def test_acquire_no_lock_creates(tmp_path):
    path = tmp_path / "gateway.lock"
    result = instance_lock.acquire(path, port=8971)

    assert result.ok is True
    assert result.reason == "created"
    assert result.existing is None
    data = _read_lock_file(path)
    assert data["pid"] == os.getpid()
    assert data["port"] == 8971
    assert data["base_url"] == "http://127.0.0.1:8971/"
    dt.datetime.fromisoformat(data["started_at"])  # ISO8601 可解析


# ② 锁 pid 存活且非自身 → 拒绝（不写锁），existing 携带后台地址/PID/启动时间
def test_acquire_alive_pid_refuses(tmp_path, monkeypatch):
    path = tmp_path / "gateway.lock"
    _write_raw_lock(path, {"pid": OTHER_PID, "port": 8971,
                           "base_url": "http://127.0.0.1:8971/",
                           "started_at": "2026-09-03T10:00:00+08:00"})

    # os.kill 不抛（成功）→ pid 存活
    monkeypatch.setattr(instance_lock.os, "kill", lambda pid, sig: None)
    result = instance_lock.acquire(path, port=8971)

    assert result.ok is False
    assert result.reason == "already_running"
    assert result.existing == {"pid": OTHER_PID, "port": 8971,
                               "base_url": "http://127.0.0.1:8971/",
                               "started_at": "2026-09-03T10:00:00+08:00"}
    assert _read_lock_file(path)["pid"] == OTHER_PID  # 未写锁（原锁保持）


# ② 补充：PermissionError 亦按存活处理（§4.10-④ 探测口径）
def test_acquire_alive_pid_via_permission_error(tmp_path, monkeypatch):
    path = tmp_path / "gateway.lock"
    _write_raw_lock(path, {"pid": OTHER_PID, "port": 8971,
                           "base_url": "http://127.0.0.1:8971/",
                           "started_at": "2026-09-03T10:00:00+08:00"})

    def _perm(pid, sig):
        raise PermissionError()

    monkeypatch.setattr(instance_lock.os, "kill", _perm)
    result = instance_lock.acquire(path, port=8971)

    assert result.ok is False
    assert result.reason == "already_running"
    assert result.existing["pid"] == OTHER_PID


# ③ 陈旧锁（pid 已死）→ 清理后重写为自身
def test_acquire_stale_lock_reclaims(tmp_path, monkeypatch):
    path = tmp_path / "gateway.lock"
    _write_raw_lock(path, {"pid": OTHER_PID, "port": 8970,
                           "base_url": "http://127.0.0.1:8970/",
                           "started_at": "2026-09-01T08:00:00+08:00"})

    def _dead(pid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr(instance_lock.os, "kill", _dead)
    result = instance_lock.acquire(path, port=8971)

    assert result.ok is True
    assert result.reason == "reclaimed_stale"
    data = _read_lock_file(path)
    assert data["pid"] == os.getpid()
    assert data["port"] == 8971


# ④ pid==自身（execv 重启场景）→ 覆盖重写继续启动
def test_acquire_self_pid_rewrites(tmp_path):
    path = tmp_path / "gateway.lock"
    _write_raw_lock(path, {"pid": os.getpid(), "port": 8970,
                           "base_url": "http://127.0.0.1:8970/",
                           "started_at": "2026-09-01T08:00:00+08:00"})
    result = instance_lock.acquire(path, port=8971)

    assert result.ok is True
    assert result.reason == "self_restart"
    data = _read_lock_file(path)
    assert data["pid"] == os.getpid()
    assert data["port"] == 8971  # 已覆盖为新端口
    assert data["base_url"] == "http://127.0.0.1:8971/"


# ⑤ 半行 JSON 损坏 → 按陈旧锁处理（清理重写为自身）
def test_acquire_corrupt_lock_recovers(tmp_path):
    path = tmp_path / "gateway.lock"
    path.write_text('{"pid": 123, "po', encoding="utf-8")  # 半行 JSON
    result = instance_lock.acquire(path, port=8971)

    assert result.ok is True
    assert result.reason == "recovered_corrupt"
    data = _read_lock_file(path)
    assert data["pid"] == os.getpid()
    assert data["port"] == 8971


# ⑤ 补充：JSON 可解析但结构非法（缺 pid）→ 同损坏路径清理重写
def test_acquire_invalid_pid_structure_recovers(tmp_path):
    path = tmp_path / "gateway.lock"
    path.write_text('{"port": "8970"}', encoding="utf-8")
    result = instance_lock.acquire(path, port=8971)

    assert result.ok is True
    assert result.reason == "recovered_corrupt"
    assert _read_lock_file(path)["pid"] == os.getpid()


# ⑥ release：自身锁删除；他 pid 锁不删；文件不存在不抛
def test_release_semantics(tmp_path):
    own = tmp_path / "own.lock"
    _write_raw_lock(own, {"pid": os.getpid(), "port": 8971,
                          "base_url": "http://127.0.0.1:8971/",
                          "started_at": "2026-09-03T10:00:00+08:00"})
    instance_lock.release(own, os.getpid())
    assert not own.exists()

    other = tmp_path / "other.lock"
    _write_raw_lock(other, {"pid": OTHER_PID, "port": 8971,
                            "base_url": "http://127.0.0.1:8971/",
                            "started_at": "2026-09-03T10:00:00+08:00"})
    instance_lock.release(other, os.getpid())
    assert other.exists()  # 他 pid 锁不误删

    missing = tmp_path / "missing.lock"
    instance_lock.release(missing, os.getpid())  # 不存在 → 不抛
    assert not missing.exists()
