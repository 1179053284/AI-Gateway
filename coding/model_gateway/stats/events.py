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

from model_gateway.core.errors import UpstreamError, scrub_upstream_text


def mask_key(value: str) -> str:
    """Key 脱敏：sk-****tail 形态（INT-27）。"""
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:3]}****{value[-4:]}"


def _scrub(text: str | None) -> str:
    """脱敏 + 归一化空白（None → 空串；F3 出口统一走这里）。"""
    return (scrub_upstream_text(text) or "").replace("\n", " ")


def error_summary(err: UpstreamError | Exception | None) -> str | None:
    """错误摘要（不含 Key；供事件与状态端点）。

    🔴 F3（M6 面板修复轮-2）：**本函数是事件 JSONL 的出口**，上游回显的凭据
    （`error_body` / 异常文案里的 Bearer、api_key、账号令牌）在这里再兜一层
    `scrub_upstream_text` —— `UpstreamError` 已在构造时脱敏，但本函数也吃任意
    异常（`f"{type(err).__name__}: {err}"`），文案可能带着上游原文逃逸。
    脱敏在**截断之前**做：先截 160 字会把凭据切成"半截仍在"的形态；截断口径
    与改动前逐字一致（body 截 160，摘要 = `[状态码] body`）。
    """
    if err is None:
        return None
    if isinstance(err, UpstreamError):
        body = _scrub(err.error_body)[:160]
        return (f"[{err.status_code if err.status_code is not None else 'network'}] "
                f"{body or _scrub(str(err))[:160]}")
    return f"{type(err).__name__}: {_scrub(str(err))[:160]}"


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
        """保留策略：删除 retention_days 天前的 events/switch-events/**ops-results**（daily 保留）。

        🔴 `ops-results-<date>.jsonl` 必须在其列（验收 S-15）：v2.0 起运营结果按天落盘，
        不纳入保留策略 = 每天一个文件、无限增长，而它就在用户的数据目录里。
        水位文件 `ops-results-ack.json` 只在"它记录的那一天"有用 → 一并过期删除
        （删掉等价于"当日零已读"，只会多提醒不会少提醒）。
        """
        if not self.usage_dir.exists():
            return
        cutoff = dt.date.today() - dt.timedelta(days=self.retention_days)
        for p in self.usage_dir.iterdir():
            # 前缀要取"去掉末尾日期后的整段"：`switch-events-<date>` / `ops-results-<date>`
            # 自己名字里就带连字符，`split("-")[0]` 只能拿到 "switch"/"ops" → 静默不清
            m = p.stem.rsplit("-", 1)[0] if "-" in p.stem else p.stem
            if m == "ops-results" and p.name.endswith("-ack.json"):
                try:
                    ack_day = str(json.loads(p.read_text(encoding="utf-8")).get("date") or "")
                    if len(ack_day) == 8 and ack_day.isdigit() \
                            and dt.datetime.strptime(ack_day, "%Y%m%d").date() < cutoff:
                        p.unlink()
                except (OSError, ValueError, TypeError):
                    pass
                continue
            if m in ("events", "switch-events", "ops-results") and p.suffix == ".jsonl":
                # 日期取**最后一段**：`switch-events-20260918` / `ops-results-20260918`
                # 的名字里都自带连字符，用 split("-", 1)[1] 会得到 "results-20260918"
                # → 整天数字判断不成立 → 静默不清（本条判据抓出来的）
                day_part = p.stem.rsplit("-", 1)[-1] if "-" in p.stem else ""
                if day_part and day_part.isdigit() and len(day_part) == 8:
                    try:
                        if dt.datetime.strptime(day_part, "%Y%m%d").date() < cutoff:
                            p.unlink()
                    except ValueError:
                        pass
