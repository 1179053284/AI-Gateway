"""请求事件 JSONL 流水（tech-design §4.8）。

- 按天分文件：data/usage/events-YYYYMMDD.jsonl / switch-events-YYYYMMDD.jsonl
- 单写队列串行化（asyncio.Queue + 单写 task）防并发交错断行（§8-12）
- 保留策略：retention_days 天前的 events/switch-events 原子删除（daily 快照保留）
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
from pathlib import Path

from model_gateway.core.errors import UpstreamError


def mask_key(value: str) -> str:
    """Key 脱敏：sk-****tail 形态（INT-27）。"""
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:3]}****{value[-4:]}"


def error_summary(err: UpstreamError | Exception | None) -> str | None:
    """错误摘要（不含 Key；供事件与状态端点）。"""
    if err is None:
        return None
    if isinstance(err, UpstreamError):
        body = (err.error_body or "").replace("\n", " ")[:160]
        return f"[{err.status_code if err.status_code is not None else 'network'}] {body or str(err)[:160]}"
    return f"{type(err).__name__}: {str(err)[:160]}"


class EventLogger:
    """事件落盘（单写队列）。put_nowait 投递，后台单 task 串行写。"""

    def __init__(self, usage_dir: Path, retention_days: int = 7):
        self.usage_dir = Path(usage_dir)
        self.retention_days = retention_days
        self.queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self.usage_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_old_files()
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._writer())

    async def stop(self) -> None:
        if self._task is not None:
            # 排空队列后退出
            await self.queue.join()
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def log_request(self, event: dict) -> None:
        self.queue.put_nowait(("events", event))

    def log_switch(self, event: dict) -> None:
        self.queue.put_nowait(("switch-events", event))

    async def _writer(self) -> None:
        while True:
            kind, event = await self.queue.get()
            try:
                day = dt.datetime.now().strftime("%Y%m%d")
                path = self.usage_dir / f"{kind}-{day}.jsonl"
                line = json.dumps(event, ensure_ascii=False, default=str)
                with path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:  # noqa: BLE001 — 落盘失败不阻断网关
                pass
            finally:
                self.queue.task_done()

    def _cleanup_old_files(self) -> None:
        """保留策略：删除 retention_days 天前的 events/switch-events（daily 保留）。"""
        if not self.usage_dir.exists():
            return
        cutoff = dt.date.today() - dt.timedelta(days=self.retention_days)
        for p in self.usage_dir.iterdir():
            m = p.name.split("-")[0]
            if m in ("events", "switch") and p.suffix == ".jsonl":
                day_part = p.stem.split("-", 1)[1] if "-" in p.stem else ""
                if day_part and day_part.isdigit() and len(day_part) == 8:
                    try:
                        if dt.datetime.strptime(day_part, "%Y%m%d").date() < cutoff:
                            p.unlink()
                    except ValueError:
                        pass
