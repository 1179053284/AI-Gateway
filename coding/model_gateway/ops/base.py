"""运营操作的基础类型（tech-design v2.0 §16.2 / §16.3）。

🔴 **四类结果**（只有 `failed` 需用户关注）—— 前三类是**正常业务状态**，
与 `failed` 混排会稀释注意力（§16.2 / §21.3 原则 3）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal

Category = Literal["success", "already_done", "inactive", "failed"]
# 「只有 failed 需用户关注」这条规则住在它**生效**的地方：红点数 =
# `ops/runner.py:unread_failures()` 当日汇总里未确认的 `failed` 条数。
# 原先这里另放一张 `NEEDS_ATTENTION` 查询表，全包零引用（§20 死代码，
# 由接线护栏放宽常量口径后抓出）—— 规则两处各写一份正是分叉的前夕。


@dataclass
class OpResult:
    """单个账号的一次操作结果。"""

    account: str
    category: Category
    detail: str = ""
    #: 🔴 **结构化重试声明**（§22.6 / R1-F2）：执行体在失败时明确表态"这是网络/5xx 类、
    #: 可以退避重试"（True）还是"业务码/凭据类、重试无用"（False）。
    #: 默认 `None` = **未声明** → 批量执行器回退既有的"规范化前缀"约定
    #: （`ops/runner.py::_looks_retryable`，兼容 zcode 侧旧调用方；它们遵守
    #: `network:` / `timeout:` / `http 5` 前缀）。唯一消费点：`runner._retryable_of()`。
    #: 🔴 存在的理由：产品钩子的失败文案是**给人读的中文**，拿文案当重试判据
    #: 一改文案就静默失效（R1-F2 实测：`_looks_retryable("签到请求网络错误：…") == False`
    #: → 产品通路的网络类失败**从不退避重试**）。
    retryable: bool | None = None


@dataclass
class OpReport:
    """一次批量执行的结果汇总（**四类分开**，不混排）。"""

    success: list[str] = field(default_factory=list)
    already_done: list[str] = field(default_factory=list)
    inactive: list[str] = field(default_factory=list)
    #: (账号, 原因) —— 只有这一项需要用户关注
    failed: list[tuple[str, str]] = field(default_factory=list)
    #: 🔴 `inactive` 的原因（账号 → 文案）。**只用于落盘**（验收 S-17）：
    #: 红点与 toast 把用户指到 `ops-results-*.jsonl`，而原先那里只有账号名 ——
    #: "熔断拦住所以没试" 与 "本轮确实跑过但没动作" 在文件里长成同一个样子，
    #: 事后翻日志的人无法判断那 30 分钟里到底发生了什么。
    inactive_reasons: dict[str, str] = field(default_factory=dict)
    #: 未参与（如 enabled=false 被跳过）—— 不计入四类
    skipped: list[str] = field(default_factory=list)
    #: 🔴 **无账号参与**（`N=0`）—— 与"有账号但全部无需动作"是**两种不同情形**（§16.4）
    no_participants: bool = False

    def add(self, r: OpResult) -> None:
        if r.category == "success":
            self.success.append(r.account)
        elif r.category == "already_done":
            self.already_done.append(r.account)
        elif r.category == "inactive":
            self.inactive.append(r.account)
            if r.detail:
                self.inactive_reasons[r.account] = r.detail
        else:
            self.failed.append((r.account, r.detail or "未知原因"))

    @property
    def total(self) -> int:
        return len(self.success) + len(self.already_done) + len(self.inactive) + len(self.failed)

    @property
    def all_normal(self) -> bool:
        return not self.failed

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "already_done": self.already_done,
            "inactive": self.inactive,
            "failed": [{"account": a, "reason": r} for a, r in self.failed],
            "inactive_reasons": self.inactive_reasons,
            "skipped": self.skipped,
            "no_participants": self.no_participants,
        }


#: 运营动作的执行签名：`(账号, *, manual=…, runtime=…) -> OpResult`
OpRun = Callable[..., Awaitable["OpResult"]]


@dataclass(frozen=True)
class AccountOperation:
    """一个可注册的运营动作（§16.4 / 09 D25）。

    🔴 `supported_products` **是判据不是标签**：批量执行器在选参与方时按它过滤
    —— 不同产品支持的动作不同（ZCode 有 `billing/claim`，别的产品未必有），
    **不按产品整体开关**（§16.4）。声明错/漏的产品，其账号会被明确跳过而非误跑。
    """

    id: str
    title: str
    supported_products: tuple[str, ...]
    run: OpRun

    def supports(self, product: str) -> bool:
        return product in self.supported_products
