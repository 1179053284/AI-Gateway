"""单实例锁：data/gateway.lock 明文 JSON 的获取/释放（tech-design §4.10-③④，PRD FR-12.3）。

纯逻辑模块（路径由调用方注入，便于 UT-28 以 tmp_path 隔离）：
- acquire：按决策树判定——不存在/损坏（半行 JSON）→ 清理重写；pid==自身（execv 重启）
  → 覆盖重写；pid 存活且非自身 → 拒绝（不写锁，返回已有实例信息）；pid 已死（陈旧锁）
  → 清理重写。读→判→写同段完成，压缩 TOCTOU 竞态窗口（§4.10-④）。
- release：仅当锁内 pid == own_pid 才删除（幂等，防误删后续实例的锁）。
- PID 复用误判按「pid 存活即拒绝」保守处理（宁可误拒不猜测；锁明文可查可删）。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

LOCK_FILENAME = "gateway.lock"

# acquire 结果原因（UT-28 五场景对应）
REASON_CREATED = "created"                  # 锁不存在 → 新写
REASON_RECLAIMED_STALE = "reclaimed_stale"  # 陈旧锁（pid 已死）→ 清理重写
REASON_RECOVERED_CORRUPT = "recovered_corrupt"  # 损坏（半行 JSON/结构非法）→ 清理重写
REASON_SELF_RESTART = "self_restart"        # pid==自身（execv 重启）→ 覆盖重写
REASON_ALREADY_RUNNING = "already_running"  # pid 存活且非自身 → 拒绝启动


@dataclass(frozen=True)
class AcquireResult:
    """获取结果：ok=False 且 reason=already_running 时 existing 携带在跑实例信息。"""

    ok: bool
    reason: str
    existing: dict | None = None


def read_lock(path: Path) -> dict | None:
    """读锁：不存在 / 损坏 / 结构非法（非 dict）→ None（调用方按陈旧锁清理重写）。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_lock(path: Path, port: int) -> None:
    """tempfile 同目录 + os.replace 原子覆盖写（tech §4.10-③）。"""
    payload = {
        "pid": os.getpid(),
        "port": port,
        "base_url": f"http://127.0.0.1:{port}/",
        "started_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix="gateway.lock.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp_name, path)


def _pid_alive(pid: int) -> bool:
    """pid 存活探测（§4.10-④）：ProcessLookupError → 死；PermissionError/成功 → 存活。"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire(path: Path, port: int) -> AcquireResult:
    """获取单实例锁（§4.10-④ 决策树逐字落实；读→判→写同段完成）。"""
    data = read_lock(path)
    if data is None:
        # 不存在 与 损坏（含半行 JSON）统一走「清理→写锁→继续」，reason 区分以便 UT 断言
        corrupted = path.exists()
        if corrupted:
            path.unlink(missing_ok=True)
        write_lock(path, port)
        return AcquireResult(ok=True,
                             reason=REASON_RECOVERED_CORRUPT if corrupted else REASON_CREATED)

    pid = data.get("pid")
    if not isinstance(pid, int):
        # 解析成功但结构非法（缺 pid/类型异常）→ 同损坏路径：清理重写
        write_lock(path, port)
        return AcquireResult(ok=True, reason=REASON_RECOVERED_CORRUPT)

    if pid == os.getpid():
        # execv 重启场景：新映像重走启动序列，命中自身 pid → 覆盖重写
        write_lock(path, port)
        return AcquireResult(ok=True, reason=REASON_SELF_RESTART)

    if _pid_alive(pid):
        # pid 存活且非自身（含 PID 复用误判，保守拒绝）→ 不写锁
        return AcquireResult(ok=False, reason=REASON_ALREADY_RUNNING, existing=data)

    # pid 已死 → 陈旧锁：清理 → 写锁 → 继续启动
    path.unlink(missing_ok=True)
    write_lock(path, port)
    return AcquireResult(ok=True, reason=REASON_RECLAIMED_STALE)


def release(path: Path, own_pid: int) -> None:
    """释放锁：仅当锁内 pid == own_pid 才删除（幂等；不存在/损坏/pid 不符 → 不动作）。"""
    data = read_lock(path)
    if data is not None and data.get("pid") == own_pid:
        path.unlink(missing_ok=True)
