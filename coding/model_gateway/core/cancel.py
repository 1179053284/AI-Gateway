"""取消注册表与透传（tech-design §4.6）。

- CancelRegistry：request_id → 上游 task；请求结束注销
- 客户端断连 → 取消上游 task → aborted（不计失败、不触发冷却）
- CancelledError 绝不吞（必须 re-raise；防误计 C / 误切换，tech §8-1）
"""

from __future__ import annotations

import asyncio


class CancelRegistry:
    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}

    def register(self, request_id: str, task: asyncio.Task) -> None:
        self._tasks[request_id] = task

    def cancel(self, request_id: str) -> None:
        task = self._tasks.get(request_id)
        if task is not None and not task.done():
            task.cancel()

    def unregister(self, request_id: str) -> None:
        self._tasks.pop(request_id, None)


class DisconnectWatcher:
    """延迟提交窗口内的断连探测（tech §8-11：ASGI 不主动推送，须轮询 is_disconnected）。

    单任务轮询（每 interval 秒一次），供非流式/首帧前等待阶段并行监听。
    探测到断连时触发 on_disconnect 回调（如取消当前处理 task → 上游请求同步取消）。
    """

    def __init__(self, is_disconnected_coro, interval: float = 0.2, on_disconnect=None):
        self._check = is_disconnected_coro  # awaitable () -> bool
        self._interval = interval
        self._on_disconnect = on_disconnect  # Callable[[], None]，fire once
        self._task: asyncio.Task | None = None
        self.disconnected = False

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._run())

    def cancel_sync(self) -> None:
        """同步取消探测 task（请求收尾/取消路径用，不 await）。"""
        if self._task is not None:
            self._task.cancel()

    async def _run(self) -> None:
        while not self.disconnected:
            try:
                self.disconnected = await self._check()
            except Exception:  # noqa: BLE001 — 探测失败不影响主链路
                return
            if self.disconnected:
                if self._on_disconnect is not None:
                    try:
                        self._on_disconnect()
                    except Exception:  # noqa: BLE001
                        pass
                return
            await asyncio.sleep(self._interval)

    async def stop(self) -> bool:
        """停止探测并返回断连状态。"""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        return self.disconnected
