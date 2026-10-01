"""ZCode 额度读取与熔断（tech-design v2.0 §17 关键决策）。

**三通道**（`18` §②），优先级：

| # | 通道 | 说明 |
|---|---|---|
| 1 | **客户端日志** | ⭐ 主用 —— 日志是客户端拿到的**第一手响应**，且**绕开签名风控**（联网请求需 `X-Client-Sig/Nonce/Pow` 私钥握手 + PoW，脚本无法复刻） |
| 2 | 联网（Plan） | `GET zcode.z.ai/api/v1/zcode-plan/billing/balance`，需 `Bearer <jwt>` + **`X-Device-Mid`**（缺则 400/3001） |
| 3 | 联网（API Key） | BigModel biz 网关 —— **不同维度**（账户余额/资源包），非额度桶 |

**3012 熔断**（`18` §③）：服务端风控 `unusual activity` → **全局熔断 30 分钟**，
节流 10s，状态**落盘**（防重启丢失）。

**串号防护**（`18` §②）：按 `expectUserPlanId` 精确匹配；匹配不上 → 返回 None，
**绝不能把别人的额度顶上来**。

**熔断回写**（§17）：熔断/额度耗尽 → 回写该账号对应 `ResourceState.status`，
统一用 **`bench`**（临时冷却，非 `disable`）+ 写 `last_error` 原因
→ 模型转发路径自动绕开，**无需给 `available()` 加额度维度**。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from model_gateway.core.resources import ResourceManager, fmt_recovery_clock, without_clock_suffix


logger = logging.getLogger("model_gateway.zcode")

#: 日志标记（日志通道的锚点）
LOG_MARKER = "billing/balance 请求完成"
#: 只回看文件尾部（4 MiB）
TAIL_BYTES = 4 * 1024 * 1024
#: 日志回看条数上限
MAX_LOG_SCAN = 80

#: 3012 = 服务端风控（unusual activity）
CODE_RISK_CONTROL = 3012


@dataclass
class Bucket:
    """额度桶（按 `show_name` 归并）。"""

    show_name: str
    period: str
    total: int
    used: int
    available: int

    @property
    def reset_note(self) -> str:
        return f"{self.used}/{self.total}"


@dataclass
class QuotaSnapshot:
    account: str
    buckets: list[Bucket] = field(default_factory=list)
    plan: str = ""
    #: None = 未取到；调用方应退回旧快照
    ok: bool = True
    note: str = ""

    @property
    def totals(self) -> tuple[int, int]:
        return (sum(b.used for b in self.buckets), sum(b.total for b in self.buckets))


def _extract_json_after(text: str) -> dict | None:
    """从标记后的 `{` 起用**括号配对**抠出完整 JSON（含字符串/转义处理）。

    为什么不用正则：payload 里可能带引号文案，粗暴匹配会判错（`18` §②）。
    """
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(text[start:i + 1])
                except ValueError:
                    return None
                return data if isinstance(data, dict) else None
    return None


def parse_log_tail(path: Path, *, expect_user_plan_id: str | None = None,
                   max_scan: int = MAX_LOG_SCAN) -> dict | None:
    """日志通道：读文件尾 4 MiB，定位最后 N 条 `billing/balance` 记录。

    `expect_user_plan_id` 给出时做**串号防护**（`18` §②）：
    匹配不上 → 返回 None（**绝不把别人的额度顶上来**）。
    """
    if not path.exists():
        return None
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            f.seek(max(0, size - TAIL_BYTES))
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return None

    found: list[dict] = []
    pos = 0
    while len(found) < max_scan:
        idx = tail.find(LOG_MARKER, pos)
        if idx < 0:
            break
        data = _extract_json_after(tail[idx + len(LOG_MARKER):])
        pos = idx + len(LOG_MARKER)
        if data is None:
            continue
        if expect_user_plan_id:
            # 串号防护：只认本账号的 user_plan_id
            plans = (data.get("data") or {}).get("plans") or []
            ids = {str(p.get("user_plan_id") or "") for p in plans if isinstance(p, dict)}
            if expect_user_plan_id not in ids:
                continue
        found.append(data)
    return found[-1] if found else None


def _bucket_from_balance(b: dict) -> Bucket | None:
    show = str(b.get("show_name") or b.get("showName") or "")
    total = int(b.get("total_units") or 0)
    used = int(b.get("used_units") or 0)
    avail = b.get("available_units")
    # 🔴 兜底：available 缺省时**绝不能拿总量当可用**（`18` §④）
    available = int(avail) if avail is not None else max(0, total - used)
    return Bucket(show_name=show, period=str(b.get("period") or ""),
                  total=total, used=used, available=available)


def normalize_remote(body: dict, *, account: str = "") -> QuotaSnapshot:
    """联网通道归一化：Anthropic/Plan 响应 → `QuotaSnapshot`。

    对字段别名做防御（不同通道键名不同）。
    """
    snap = QuotaSnapshot(account=account)
    if not isinstance(body, dict):
        snap.ok = False
        snap.note = "响应不是对象"
        return snap
    code = body.get("code")
    if code not in (0, None, "0"):
        snap.ok = False
        snap.note = f"上游 code={code}"
        return snap
    data = body.get("data") or {}
    plans = data.get("plans") or []
    if plans and isinstance(plans, list):
        snap.plan = str((plans[0] or {}).get("name") or "")
    balances = data.get("balances") or []
    for b in balances:
        if not isinstance(b, dict):
            continue
        bk = _bucket_from_balance(b)
        if bk is not None:
            snap.buckets.append(bk)
    return snap


def snapshot_from_log_record(record: dict, *, account: str = "") -> QuotaSnapshot:
    """日志记录 → `QuotaSnapshot`（复用同一套归一化，统一数据模型）。"""
    return normalize_remote(record, account=account)


def aggregate(snapshots: list[QuotaSnapshot]) -> dict:
    """跨账号聚合：`{accounts: [...], aggregated: {used, total}}`（§19 M5-2）。"""
    accounts = []
    total_used = total_all = 0
    for s in snapshots:
        used, total = s.totals
        total_used += used
        total_all += total
        accounts.append({
            "account": s.account, "plan": s.plan,
            "used": used, "total": total, "ok": s.ok,
        })
    return {"accounts": accounts,
            "aggregated": {"used": total_used, "total": total_all}}


def read_account_snapshot(accounts_root: Path, account: str,
                          *, log_dirs_tail: int = 3) -> QuotaSnapshot:
    """单账号额度快照：**客户端日志通道优先** → 无记录则 `ok=False`（§17 数据源优先级）。

    🔴 不走联网：额度/权益接口需 `X-Client-Sig/Nonce/Pow` 私钥握手 + PoW，脚本无法复刻，
    且日志是客户端拿到的**第一手响应**（`18` §②）。
    """
    from model_gateway.upstream.zcode.dataroot import v2_dir_of

    log_dir = v2_dir_of(accounts_root, account) / "logs"
    if log_dir.exists():
        try:
            logs = sorted(log_dir.glob("*.log"), reverse=True)[:log_dirs_tail]
        except OSError:
            logs = []
        for log in logs:
            rec = parse_log_tail(log)
            if rec is not None:
                return snapshot_from_log_record(rec, account=account)
    return QuotaSnapshot(account=account, ok=False, note="无可用日志记录")


def remaining_units(snap: QuotaSnapshot) -> int | None:
    """快照的**可用余量**（各桶求和）。取不到 → None（未知，不做额度管控）。

    ⚠️ 口径：1 请求预留 1 单位（`amount` 缺省值），与 `total_units/used_units` 同量纲。
    真实每请求扣减多少由上游决定，网关侧只做**保守闸门**：
    余量为 0 时不再选这条资源，而不是精确记账。
    """
    if not snap.ok or not snap.buckets:
        return None
    return sum(max(0, b.available) for b in snap.buckets)


def refresh_runtime_quotas(runtime, *, accounts: list[str] | None = None) -> int:
    """把各账号额度余量写入 `ResourceState.quota_remaining`（§19 M5-3 的**数据源**）。

    🔴 为什么必须有人写：`available()` 已改为看额度（`has_quota()`），
    但 `quota_remaining` 若永远是 None，"事前预留"就是**空转的机制**
    （上一轮 M5-3 被判"未交付"的确切原因：函数齐了、没人调用）。

    - 取不到快照 → **保持 None**（未知 ≠ 没额度）；否则日志一缺失全部资源就失去服务
    - 返回被更新的资源条目数
    """
    from model_gateway.upstream.zcode import store as zstore

    root = zstore.accounts_root()
    mgr = runtime.resources
    names = accounts if accounts is not None else [a.name for a in zstore.list_accounts()]
    updated = 0
    for name in names:
        rids = resource_ids_of_account(name, runtime.config)
        if not rids:
            continue
        updated += apply_snapshot_to_runtime(runtime, name, read_account_snapshot(root, name))
    return updated


def apply_snapshot_to_runtime(runtime, account: str, snap: "QuotaSnapshot") -> int:
    """把一个额度快照写回该账号资源的额度池，返回被更新的资源数。

    🔴 单一实现：`refresh_runtime_quotas`（批量）与 `query_balance`（单账号）共用它，
    避免出现"两条路径算了两种额度"。
    按 **rid** 写共享池，不是按 `(rid, vendor_model)` 各写一份 —— 后者会让同账号多映射
    在余量为 1 时并发放行 N 个（验收 S-1）。
    取不到余量（未知）→ **不动旧值**：宁可不管控，也不误封资源。

    🔴 余量为 0 时**同时回写资源状态**（§17 表格的字面要求：`last_error = ZCode 额度耗尽`）：
    只写额度池是不够的 —— 预留闸门虽挡住了派发，但用户在总览看到的是 `active`
    且没有任何原因，"为什么这个模型不干活"依旧要猜。
    时长取**一个额度刷新周期**（下次 tick 会重读上游快照；已充值则不再 bench，
    资源在一个周期内自动回池），避免"本地判定"比"上游真相"更久地锁死资源。
    """
    remaining = remaining_units(snap)
    if remaining is None or runtime is None:
        return 0
    mgr = runtime.resources
    updated = 0
    rids = resource_ids_of_account(account, runtime.config)
    for rid in rids:
        # 按 **rid（一把凭据）** 覆盖共享池，不是按 (rid, vendor_model) 各写一份
        if mgr.set_quota(rid, remaining):
            updated += 1
    if remaining == 0 and rids:
        apply_to_resource(runtime, rids, reason=QUOTA_EXHAUSTED_REASON,
                          seconds=_quota_refresh_seconds(runtime))
    return updated


#: 额度耗尽写入 `last_error` 的原因串（§17 表格的**字面**取值，不改写、不加戏）
QUOTA_EXHAUSTED_REASON = "ZCode 额度耗尽"


def _quota_refresh_seconds(runtime) -> float:
    """额度耗尽后把资源挡出生效集的时长 = **一个额度刷新周期**（下次 tick 会重读上游）。"""
    try:
        interval = float(getattr(runtime.config.gateway.zcode, "claim_interval_seconds", 60) or 60)
    except (AttributeError, TypeError, ValueError):
        interval = 60.0
    return max(5.0, interval)


# ---------- 熔断与节流 ----------

#: 3012 风控熔断参数（§17 / `18` §③：全局熔断 30 分钟，节流 10s，状态落盘）
SANITY_HORIZON_MS = 24 * 60 * 60 * 1000
#: （上一行：时间戳合理性上限，超过「现在+24h」的 until_ms 当坏值，第八轮 E-4）
COOLDOWN_MS = 30 * 60 * 1000
THROTTLE_MS = 10 * 1000

#: 状态文件"读不动"时把资源暂时挡出生效集的秒数。**故意不等于 30 分钟**：
#    未知档既要有可见后果（不能静默空转），又不能让人删完文件后还看着一行
#    "剩余 30 分钟 + 请删除该文件"的指令挂在那儿（第十二轮 PM B-12-2 实测：
#    用户照做之后界面 30 分钟内没有任何"已生效"反馈）。每轮同步都会重新挡一次，
#    所以文件仍是坏的 → 资源持续被挡；文件修好/删掉 → 下一轮（≤2 分钟）自动放开。
UNKNOWN_STATE_BLOCK_S = 120.0

#: 熔断文件名（与账号目录同级 —— 见 `circuit_path()`）
CIRCUIT_FILENAME = "circuit.json"


def _epoch_ms() -> float:
    """**墙上时钟**（epoch 毫秒）。

    🔴 不能用 `time.monotonic()`：熔断状态要**落盘防重启丢失**（§17），
    而单调钟的重启后基准无意义 —— 存进去的 `until_ms` 重启后会变成随机数，
    熔断要么永不生效要么永久生效。原实现正是这个错（存 monotonic、跨进程读来比较）。
    """
    return time.time() * 1000


def circuit_path() -> Path:
    """熔断状态文件：与账号根同级（同 `accounts_root()` 的环境变量口径）。"""
    from model_gateway.upstream.zcode import store
    return store.accounts_root().parent / CIRCUIT_FILENAME


def _ms_problem(raw_value: object, now_ms: float) -> str | None:
    """**为什么**这个落盘字段读不动（返回 `None` = 可信）。

    判坏的形态（逐轮实测补齐，一类都没允许"能转就当数"）：缺键 / `null` / **任何字符串**
    （含 `"1790000000000"` 这种**数字串**）/ JSON 布尔 / 非有限数 / 超过「现在+24h」。

    🔴 为什么一个都不许当成 0：当成 0 就是 **fail-open** —— 常驻进程里正熔着的熔断会被
    一次坏写抹掉。第七轮（字符串崩栈）、第九轮（时钟回拨）、第十轮（缺键/`null`/`NaN`）、
    第十一轮（布尔）、第十二轮（**数字串 + 重复键**）五轮各打到一种形态，
    根因都是同一个"能 coerce 成合法数就当它是合法数"。
    返回 `None` 的含义是"**这个字段读不动**"，调用方必须按"这份状态不可信"处理
    （保持内存态 + 不许整盘覆盖，见 `_read_disk()` / `_save()`），**不是**"值为 0"。

    🔴 类型闸要挡在 `float()` **之前**：`float(True) == 1.0`、`float("1790000000000")`
    都是完全合法的数，于是"把数字改成 true"和"给时间戳加上引号"这两种最常见的手写/
    序列化差异，会把 `until_ms` 变成 1970 或一个**过去**的时刻 → 判"已过点" →
    熔断在所有进程里当场消失，`mark_called()` 还顺手整盘覆盖销毁跨进程凭据，全程零日志
    （第十一轮 BLK-3 修了布尔那一半，第十二轮 PM B-12-1 / eng-A BLK-A 打到字符串那一半）。
    """
    if raw_value is None:
        return "缺少该字段（或被写成 null）"
    if isinstance(raw_value, bool):
        return f"被写成布尔值 {raw_value!r}，不是时间戳"
    if not isinstance(raw_value, (int, float)):
        # 带上被写成什么样（截断）：`"1"` 与 `"1770000000000"` 在同一条归因里要分得开，
        # 否则 `_set_untrusted` 的"变化时才记一条"会把两种形态并成一条日志
        return f"类型不对（{type(raw_value).__name__}：{str(raw_value)[:24]}），时间戳必须是数字"
    v = float(raw_value)
    if v != v or v in (float("inf"), float("-inf")):
        return "是非有限数字（NaN/Infinity）"
    # 🔴 合理性上限（第八轮 eng-8a 的 E-4）：超过"现在 + 24 小时"的时间戳不是熔断，
    #    是坏数据 —— 界面会显示「剩余几千万年」，用户只能把整块面板当不可信。
    if v > now_ms + SANITY_HORIZON_MS:
        return "不合理（超过「现在+24h」），不是熔断而是坏数据"
    return None


def until_label(until_ms: float, now_ms: float | None = None) -> str:
    """恢复时刻的可读标签：同日 `HH:MM`，跨午夜 `明日 HH:MM`（验收 S-21 / PRD Q28-⑦）。

    口径本体住在运行态层（`core/resources.fmt_recovery_clock`），因为**两个出口**要用
    同一把尺：全局熔断的 `reason()`（这里）与单条资源的「最近错误」列
    （`snapshot_by_resource` 只有 `cooldown_until`，没有熔断对象）。
    两处各写一份"跨日怎么判"，就会出现 CLI 说「至 00:20」而界面说「至 明日 00:20」
    的同屏矛盾（验收 S-23）。
    """

    return fmt_recovery_clock(until_ms / 1000,
                              None if now_ms is None else now_ms / 1000)


def _with_until(reason: str, until_ms: float, now_ms: float | None = None) -> str:
    """把**裸原因**与恢复时刻拼成 §17 口径的那句话（原因或时刻缺失时原样返回）。

    🔴 拼接前先剥一次尾巴（验收 S-23）：`enter()` 的调用方有可能是拿着**别处渲染过的**
    原因串回来的（`/admin/api/zcode/bench` 收到的就是 CLI 已渲染的 `reason()`），
    不剥就变成「…，至 01:20，至 14:38」。
    """

    base = without_clock_suffix(reason) or ""
    # 🔴 已过期（或没有到期时间）→ **只回裸原因**（第八轮 eng-8a 的 L-1）：
    #    快照侧同一个语义已经钉死，若这里还挂一个过去的钟点，CLI 与界面会在
    #    "文件还在、但已过点"这个窗口里互相矛盾。不靠调用方先用 `active()` 守门。
    if not base or not until_ms:
        return base
    if until_ms <= (now_ms if now_ms is not None else _epoch_ms()):
        return base
    return f"{base}，至 {until_label(until_ms, now_ms)}"


@dataclass
class Cooldown:
    until_ms: float = 0.0
    reason: str = ""
    last_call_ms: float = 0.0

    def left_ms(self, now_ms: float | None = None) -> float:
        now = now_ms if now_ms is not None else _epoch_ms()
        return max(0.0, self.until_ms - now)

    def active(self, now_ms: float | None = None) -> bool:
        return self.left_ms(now_ms) > 0


class CooldownManager:
    """3012 风控的**全局熔断 + 节流**管理器（§17）。

    | 能力 | 口径 |
    |---|---|
    | 熔断 | 命中 3012 → 全局熔断 30 分钟：**所有** ZCode 账号一并停止再打上游（`_circuit_gate`） |
    | 节流 | 两次上游调用至少间隔 10s（`wait_throttle()` 由调用方 await） |
    | 落盘 | `circuit_path()`（与账号目录同级）；**每次判定前按 mtime 回读文件** |
    | 解除 | 到期自动解除；**文件被删除 = 已解除**（跨进程一致，CLI 对用户承诺的出口）|

    ⚠️ 熔断**不拦额度读取**：`query_balance` 走的是**客户端日志通道**（本模块文件读取，
    零上游请求、零签名），继续读没有风控代价，也不与"停止打上游"矛盾。

    🔴 为什么"每次回读"：写状态的一方可能是**另一个进程**（`mgw zcode claim` 在 CLI 进程里
    命中风控，网关进程必须立刻知道）。为它加 watcher 是过度设计 —— 这是一次
    几十字节 JSON 的 stat + 偶发读取，一次批量里最多每个账号一次。
    """

    def __init__(self, path: Path | None = None, *, now: Callable[[], float] | None = None):
        self.path = Path(path) if path is not None else circuit_path()
        self._now = now or _epoch_ms
        self._cd = Cooldown()
        #: 状态文件"读不动"的原因（None = 可信）。见 `_load()` 的三态口径与 fail-closed。
        self._untrusted: str | None = None
        #: 节流字段坏值的告警去重位（每一次判定都读盘，不挡就会刷屏）
        self._throttle_bad = False
        #: 上一次落盘的失败原因（None = 落盘正常或没有待落盘的熔断）
        self._save_error: str | None = None
        self._load()

    # —— 落盘读写 ——

    def _set_untrusted(self, problem: str | None) -> None:
        """信任态**只在变化时**记一条日志。

        🔴 两个方向都要修：第十一轮 PM 实测"坏值路径零痕迹"（13 种坏形态里只有 3 类真打
        WARNING）；但 `active()`/`reason()` 每次判定都要 `_load()` 一次，无脑 warn 会把
        日志刷成噪音 —— 于是**变化时**各说一次，既不留零痕迹也不刷屏。
        """
        if problem == self._untrusted:
            return
        self._untrusted = problem
        if problem:
            logger.warning("熔断状态文件 %s 读不动：%s → 保持现有内存态、**拒绝整盘覆盖**，"
                           "并按熔断拒跑（宁可拒跑也不冒险）。确认无风控后删除该文件即可解除",
                           self.path, problem)
        else:
            logger.info("熔断状态文件 %s 重新可读，恢复按文件判定", self.path)

    def _read_disk(self) -> tuple[Cooldown | None, str | None]:
        """读盘：**不改内存态**，返回 `(盘上状态, 读不动的原因)`。

        - 文件不存在 → `(Cooldown(), None)`：**可信**，语义是"熔断已解除"
          （CLI 对用户承诺的唯一手动出口，验收 S-1）；
        - 读得动但内容不可信 → `(None, 原因)`：**未知**，调用方不许拿它当"没有熔断"。

        🔴 重复键也算"读不动"（第十二轮 eng-A BLK-A）：`json.loads` 默认让后写的键静默
        顶掉先写的，`{"until_ms": 1, "until_ms": 2}` 这种手改/半写入残留会被洗成合法值。
        """
        dup: list[str] = []

        def _pairs(pairs: list[tuple[str, object]]) -> dict:
            out: dict = {}
            for key, val in pairs:
                if key in out:
                    dup.append(key)
                out[key] = val
            return out

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"),
                             object_pairs_hook=_pairs)
        except FileNotFoundError:
            return Cooldown(), None
        except OSError as exc:
            return None, f"读不动（{exc.__class__.__name__}）"
        except ValueError:
            return None, "JSON 解析失败（半写入或被手改坏）"
        if dup:
            return None, f"存在重复键（{'、'.join(sorted(set(dup)))}），后写的值会静默顶掉先写的"
        if not isinstance(raw, dict):
            return None, f"内容不是 JSON 对象（是 {type(raw).__name__}）"
        now = self._now()
        until_problem = _ms_problem(raw.get("until_ms"), now)
        if until_problem:
            # 带上盘上键集：两种"读不动"的形态（缺键 vs 写成 null vs 值是字符串）在日志里
            # 要分得开，同时让 `_set_untrusted` 的"变化时才记一条"不会把不同形态并成一条。
            return None, f"until_ms {until_problem}（盘上键：{sorted(raw) or '无'}）"
        throttle_problem = _ms_problem(raw.get("last_call_ms"), now)
        if throttle_problem and not self._throttle_bad:
            # 节流字段坏 ≠ 熔断状态不可信：措辞必须分开（NB-2/NB-3），否则用户会以为
            # 要删文件，而这里最坏后果只是"多打一次上游"。只在**变化时**说一次。
            self._throttle_bad = True
            logger.warning("熔断状态文件的节流字段读不动（last_call_ms %s）→ 按"
                           "『没有最近一次调用』处理，熔断判定不受影响", throttle_problem)
        elif not throttle_problem:
            self._throttle_bad = False
        # 🔴 旧版本把"写入当时算出的恢复时刻"烘进了 reason（S-21 之前的落盘格式）。
        #    现在时刻是**读时**渲染的，不剥掉这截尾巴就会拼成
        #    「…，至 01:20，至 14:38」—— 一行两个时刻（验收 S-23）。
        return Cooldown(until_ms=float(raw["until_ms"]),
                        reason=without_clock_suffix(str(raw.get("reason") or "")) or "",
                        last_call_ms=0.0 if throttle_problem
                        else float(raw["last_call_ms"])), None

    def _load(self) -> None:
        # 🔴 每次判定**真读一遍文件**，不用 mtime 去重（验收 S-26⑤）：
        #    粗粒度时间戳的卷上（HFS+/NFS/网络盘常见到秒），另一个进程在**同一秒内**
        #    写下的新熔断会被"mtime 没变 → 不重读"吞掉 —— 而这份文件正是跨进程
        #    看见 3012 的唯一凭据。几十字节的本地读取换"看得见别的进程"，值得。
        #
        # 🔴 三态而非两态（第十一轮 eng-A BLK-2）：
        #    ① 文件不存在   = 熔断**已解除**（可信）；
        #    ② 读不动/不可信 = **未知**：保持内存态 + 标不可信（`active()` 据此拒跑，
        #       `_save()` 据此拒绝整盘覆盖 —— 原先这里 fail-open：空内存态放行 +
        #       `mark_called()` 把别人的熔断凭据抹掉）；
        #    ③ 读得动且可信 = 按文件判定。
        disk, problem = self._read_disk()
        if problem is None:
            # 🔴 第十二轮 eng-A BLK-B 的第二半：**"文件不存在"不许抹掉本进程刚建立、
            #    却没能落盘成功的熔断**。目录 0555 时 `enter()` 落盘失败，下一次判定
            #    就走这条"已解除"分支 → 内存态被清空 → 闸门开、下一轮继续打风控账号。
            #    只有"上一次写盘是成功的"才允许把盘上的缺席读成"已解除"。
            keeping_memory = (self._save_error is not None
                              and self._cd.active(self._now())
                              and (disk is None or disk.until_ms <= self._cd.until_ms))
            if not keeping_memory:
                self._cd = disk
        self._set_untrusted(problem)

    def _save(self) -> bool:
        """原子落盘：**唯一命名**临时文件 + `fsync` + `os.replace`，写前读盘合并。

        🔴 第十一轮 eng-A BLK-1：原先用**固定名** `self.path.with_suffix(".tmp")`
        （= `circuit.tmp`），两个进程（cron 与 CLI 各领不同账号、同时命中 3012）并发落盘
        会互相截断 —— 面板 12 秒内实测读到坏 JSON 206,783 次、混合内容 20,351 次。
        也就是说**坏文件是它自己造的**，不需要人手改；BLK-2 再把那份自己造的坏文件
        变成"抹掉熔断"的入口。`mkstemp` 给的是 `O_EXCL` 唯一名，配合 `os.replace`
        的原子改名，读者永远只能看到"旧的完整文件"或"新的完整文件"。

        🔴 BLK-2 的两个方向：
        ① 盘上读不动而本进程又没有生效中的熔断 → **拒绝写盘**（内存里的空状态不代表
           "没有熔断"，写下去就是把别人的凭据整盘抹掉；宁可丢本次 10 秒节流）；
        ② 盘上读得动且熔断**更长** → 以盘上为准（`mark_called()` 原先无条件整盘覆盖，
           几毫秒前另一个进程刚建立的 30 分钟会被这次节流写抹掉）。
        """
        disk, problem = self._read_disk()
        now = self._now()
        if problem is not None and not self._cd.active(now):
            logger.warning("熔断状态文件不可信（%s）且本进程无生效中的熔断 → 本次**不写盘**："
                           "写下去会把跨进程的熔断凭据整盘抹掉（丢的是本次节流，不是熔断）",
                           problem)
            self._save_error = f"状态文件不可信（{problem}），本轮拒写以免抹掉别人的熔断凭据"
            return False
        merged = self._cd
        if disk is not None and disk.until_ms > merged.until_ms:
            merged = Cooldown(until_ms=disk.until_ms,
                              reason=disk.reason or merged.reason,
                              last_call_ms=max(merged.last_call_ms, disk.last_call_ms))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return self._save_failed(exc)
        tmp_name: str | None = None
        try:
            fd, tmp_name = tempfile.mkstemp(dir=str(self.path.parent),
                                            prefix=f".{self.path.name}.", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"until_ms": merged.until_ms,
                           "reason": merged.reason,
                           "last_call_ms": merged.last_call_ms}, fh)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, self.path)
            tmp_name = None
            self._cd = merged
        except OSError as exc:
            # 🔴 第十二轮 eng-A BLK-B：原先这里 `except OSError: pass` 一声不响。
            #    目录 0555 时实测：`enter()` 无异常、**零日志**、文件不存在 → 下一次判定
            #    读成"没有熔断" → 运营闸门开、下一轮继续打风控中的账号，而 CLI 还在打印
            #    「已建立全局熔断：」后面跟一个空原因。落盘失败必须**可分辨**，
            #    并且要把"只在内存里生效"这件事说给每一个出口（见 `unpersisted` / `reason()`）。
            return self._save_failed(exc)
        finally:
            if tmp_name is not None:              # 失败残留会永久占目录，必须扫掉
                with contextlib.suppress(OSError):
                    os.unlink(tmp_name)
        self._save_error = None
        return True

    def _save_failed(self, exc: OSError) -> bool:
        """落盘失败的**唯一**处理点：记下来 + 报出来 + 让调用方知道没写进去。"""
        self._save_error = f"{exc.__class__.__name__}: {exc}"
        logger.warning("熔断状态落盘失败（%s）→ 熔断只在**当前进程内存**里生效，"
                       "跨进程与重启都看不见它，下一轮仍可能打向风控中的账号；"
                       "请检查 %s 所在目录的可写性", self._save_error, self.path)
        return False

    # —— 对外能力 ——

    def enter(self, reason: str) -> None:
        """进入全局熔断（命中 3012 时调用）。

        🔴 文案必须带**恢复时刻**（§17 字面：`ZCode 风控熔断（30min，至 HH:MM）`）：
        只写"30 分钟"要用户自己算从何时起算 —— 而重启之后他连起点都看不到。
        时刻**不在这里烘进字符串**（验收 S-21）：`enter()` 落的盘只存裸原因，
        读的时候（`reason()`）再按当时的钟点拼 —— 23:50 熔的 30 分钟，
        在 23:55 读要显示"至 明日 00:20"，在 00:05 读要显示"至 00:20"，
        同一条落盘状态在两个时刻各自说得对。烘死在文件里就只能对一次。
        """
        now = self._now()
        self._cd.until_ms = now + COOLDOWN_MS
        self._cd.reason = without_clock_suffix(reason) or reason
        self._cd.last_call_ms = now
        self._save()

    def active(self) -> bool:
        self._load()                             # 跨进程可见：每次都回读
        # 🔴 文件读不动 = **按熔断处理**（第十一轮 eng-A BLK-2 的方向修正）。
        #    原先是"未知 = 放行"：新进程遇到坏文件就 active=False，随后 `mark_called()`
        #    整盘覆盖，把别的进程留下的熔断凭据销毁 —— 与用户裁决 S-22
        #    「宁可拒跑也不冒险」正相反。未知按最坏处理。
        return self._untrusted is not None or self._cd.active(self._now())

    @property
    def untrusted(self) -> str | None:
        """状态文件"读不动"的原因（None = 可信）。给 CLI/运营门做**可分辨**归因用。"""
        self._load()
        return self._untrusted

    @property
    def unpersisted(self) -> str | None:
        """内存里有熔断但**没能写进状态文件**的原因（None = 没有这种落差）。

        🔴 第十二轮 eng-A BLK-B：这一档过去完全静默 —— 落盘失败被 `except OSError: pass`
        吃掉，别的进程与重启都看不见这次熔断，闸门照开，而 CLI 还在说"已建立全局熔断"。
        """
        self._load()
        return self._save_error if (self._save_error and self._cd.active(self._now())) else None

    def reason(self) -> str:
        """熔断原因 + **当下读来成立**的恢复时刻（`…，至 明日 00:20` / `…，至 00:20`）。

        🔴 状态不可信时**不给钟点**：我们不知道还要等多久，编一个时刻就是谎报；
        给的是"为什么拒跑 + 手动出口在哪"（与 S-15「最近错误是历史线索」同一口径）。
        🔴 没落盘成功时也必须说出来（`unpersisted`）：否则"已建立熔断"是一句空话。
        """
        self._load()
        base = _with_until(self._cd.reason, self._cd.until_ms, self._now())
        if self._untrusted:
            base = f"{base}；熔断状态文件读不动（{self._untrusted}）→ 按熔断拒跑；" \
                   f"确认无风控后删除 {self.path} 即可解除" if base else \
                   (f"熔断状态文件读不动（{self._untrusted}）→ 按熔断拒跑；"
                    f"确认无风控后删除 {self.path} 即可解除")
        if self._save_error and self._cd.active(self._now()):
            base = f"{base}；且本次熔断**未能写入状态文件**（{self._save_error}）→ " \
                   f"仅当前进程内存生效，跨进程/重启不可见，请检查 {self.path} 的可写性" \
                   if base else (f"熔断未能写入状态文件（{self._save_error}）→ "
                                 f"仅当前进程内存生效，请检查 {self.path} 的可写性")
        return base

    def left_ms(self) -> float:
        self._load()
        return self._cd.left_ms(self._now())

    def remaining_seconds(self) -> float:
        """还要把资源挡出生效集多久（秒）。

        🔴 状态不可信而内存里又没有生效中的熔断时，按 `UNKNOWN_STATE_BLOCK_S`（一个短周期）
        挡、每轮重新挡：未知时长按最坏处理，但**不编一个 30 分钟的恢复时刻**给用户看。
        返回 0 会让 §17 的回写变成"bench 0 秒 = 什么都不做"，于是 CLI 里拒跑、界面上
        毫无痕迹（验收 S-11 的静默空转同族）。
        """
        self._load()
        left = self._cd.left_ms(self._now()) / 1000
        if left > 0:
            return left
        return UNKNOWN_STATE_BLOCK_S if self._untrusted else 0.0

    def left_minutes(self) -> int:
        return int((self.left_ms() + 59_999) // 60_000)

    def throttle_wait_ms(self) -> float:
        """距上次上游调用还需等多久（0 = 可立即调用）。"""
        self._load()
        return max(0.0, THROTTLE_MS - (self._now() - self._cd.last_call_ms))

    def mark_called(self) -> None:
        self._cd.last_call_ms = self._now()
        self._save()


#: 进程内单例（按 accounts_root 解析路径，测试用 `_reset_circuit_for_tests` 重建）
_CIRCUIT: CooldownManager | None = None


def get_circuit() -> CooldownManager:
    global _CIRCUIT
    if _CIRCUIT is None:
        _CIRCUIT = CooldownManager()
    return _CIRCUIT


def _reset_circuit_for_tests(path: Path | None = None) -> CooldownManager:
    """测试注入：换路径重建单例（生产不调用）。"""
    global _CIRCUIT
    _CIRCUIT = CooldownManager(path) if path is not None else CooldownManager()
    return _CIRCUIT


def circuit_hold_scope(runtime, *, held: bool = True) -> contextlib.AbstractContextManager:
    """声明「这一段回写的成因 = 全局风控熔断」（2026-09-29 用户裁决「读时重判」的写入侧）。

    🔴 为什么需要这一层：熔断回写与**额度耗尽**回写共用同一条 `bench_account` →
    `apply_to_resource` → `bench()` 链路，而"删掉 `circuit.json` 就立刻放开"只能作用于
    **熔断当初按住的**那些冷却。来源标记必须在这里显式声明 ——
    **不靠 `reason` 字符串猜**（文案一改，标记就悄悄错位）。

    🔴 只在**熔断此刻真的成立**时声明：`CooldownManager.active()` 为假（文件不存在/已到期）
    或 `untrusted` 之外的异常时，这次回写就不是"熔断按住"的，登记了反而会把一条
    没有熔断背书的冷却在无熔断时随手放开。`active()` 为真包含"文件读不动 → 未知按
    最坏处理"那一档（Q28-⑧① 同向），所以那一档仍然正常登记、且读时不会被释放。

    ⚠️ runtime 的资源管理器不是真 `ResourceManager`（假件 / `runtime=None`）时退化为
    空作用域，本函数覆盖的回写行为与改动前逐字节一致。
    ⚠️ `held=False`（调用方显式声明"这条冷却不是熔断按住的"）→ 同样空作用域：
    参数只用于把"声明"这件事留在调用点上，读起来仍然是"这里是一次熔断回写"。
    """
    mgr = getattr(runtime, "resources", None)
    if not isinstance(mgr, ResourceManager) or not held:
        return contextlib.nullcontext()
    try:
        active = bool(get_circuit().active())
    except Exception:  # noqa: BLE001 — 判据不可用 = 不知道，不知道就不登记熔断成因
        active = False
    return mgr.circuit_hold() if active else contextlib.nullcontext()


def apply_to_resource(runtime, resource_ids: list[str], *, reason: str,
                      seconds: float | None = None) -> int:
    """🔴 熔断/额度耗尽 → 回写 `ResourceState`（**统一 `bench`**，非 `disable`）。

    同时写 `last_error` 原因串 → 总览资源健康卡的「最近错误」列**直接可见**，
    用户能分辨"风控熔断（等 30 分钟）"与"普通失败冷却（该查 Key）"（§17 / M-IX-4）。

    返回实际处理的资源数。

    🔴 **不覆盖更长的既有冷却**（验收 S-1）：一次 60 秒的额度耗尽 tick 不得把
    30 分钟的风控熔断 bench 剪短、更不得把「最近错误」改写成后到的短原因
    —— 那样用户看到的挡路原因是假的。裁决点在 `ResourceManager.bench()` 的返回值
    （它同时保证"冷却只延长"），本函数只在**取得所有权**时写原因。
    ⚠️ 本函数**不接**成因参数：冷却的成因（是否"熔断按住"）由 `bench()` 在取得所有权的
    那一刻按调用侧声明的作用域登记（见 `circuit_hold_scope`），在这里再加一个参数
    只会多出第二个可以互相打脸的口径。
    """
    mgr = runtime.resources
    cooldown_s = seconds if seconds is not None else COOLDOWN_MS / 1000
    done = 0
    for rid in resource_ids:
        for state in mgr.registry.values():
            if state.resource_id[0] != rid:
                continue
            if not mgr.bench(state, cooldown_s):
                continue                      # 更长的冷却在生效，连原因一起保留
            # 🔴 只存**裸原因**：恢复时刻由 `snapshot_by_resource` 读时渲染（验收 S-23）。
            # 传进来的 `reason` 常常是别处渲染过的 `circuit.reason()`（已含「，至 …」），
            # 烘进 `last_error` 就成了午夜后仍在说的假钟点。
            state.last_error = without_clock_suffix(reason)
            done += 1
    return done


def zcode_account_names() -> list[str]:
    """已接入的 ZCode 账号名（全局熔断的作用域来源，§17）。"""
    from model_gateway.upstream.zcode import store
    try:
        return [a.name for a in store.list_accounts()]
    except Exception:  # noqa: BLE001 — 账号根不可读时不阻断
        return []


def bench_all_zcode(runtime, *, reason: str, seconds: float | None = None,
                    only_accounts: list[str] | None = None, circuit: bool = True) -> int:
    """🔴 **全局熔断回写**（§17 口径）：3012 风控 → 对**全部** ZCode 账号一并 bench，
    `last_error` 注明「全局熔断」。

    只 bench 命中的那一个账号是**半生效**的：上游眼里这些号来自同一台设备指纹族，
    风控是账号集级别的，单号冷却后再拿下一个号继续打只会延长风控。

    🔴 整段在 `circuit_hold_scope` 里：这次取得的冷却登记为「熔断按住」，
    用户之后删掉 `circuit.json` 时读时重判才会把它放回去（额度耗尽那条路径不在作用域内）。
    `circuit=False` 是给"共用这条链的别的原因"留的显式出口（管理端点带
    `"circuit": false` 时），默认值保持"这里就是一次熔断回写"的原意。
    """
    names = only_accounts if only_accounts is not None else zcode_account_names()
    done = 0
    with circuit_hold_scope(runtime, held=circuit):
        for name in names:
            done += bench_account(runtime, name, reason=reason, seconds=seconds)
    return done


def sync_circuit_to_runtime(runtime) -> tuple[int, int]:
    """🔴 启动/重启时把**落盘的熔断**对齐回资源状态（§17 / 验收 IX-2）。

    熔断状态是跨进程落盘的（`circuit.json`，墙钟），而 `ResourceState.status` 只在内存：
    重启后配置把资源重建为 `available` → §17 指定的可见出口（总览「最近错误」列）空白、
    模型转发照旧打向仍在风控观察期里的账号。剩余时长对齐成同样的秒数，
    避免"资源先解冻、熔断还在"或反之。

    返回 `(被 bench 的资源数, 备注同名但 product 声明不符而被跳过的资源数)`。
    🔴 第二个数必须有出口（验收 ix-M-6 / eng-M-4）：这条回写是熔断的**唯一**可见出口，
    且依赖"资源备注 == ZCode 账号名"—— 写得不一致时会**静默空转**
    （文件里熔着、界面上毫无变化，看起来像熔断没生效）；反之若别的产品恰好用了
    同一个备注字符串，会被 ZCode 的风控误 bench。两种都必须说出来。
    """
    circuit = get_circuit()
    if not circuit.active():
        return 0, 0
    from model_gateway.upstream.zcode import store as zstore

    benched = skipped = 0
    reason, seconds = circuit.reason(), circuit.remaining_seconds()
    # 🔴 启动对齐 = 熔断按住（成因登记，见 `circuit_hold_scope`）；上面已经确认熔断成立，
    #    所以这里的作用域一定会生效。之后用户删掉状态文件，下一次读就把它放回生效集。
    with circuit_hold_scope(runtime):
        for acct in zstore.list_accounts():
            n = bench_account(runtime, acct.name, reason=reason, seconds=seconds)
            if n:
                benched += n
                continue
            _hit, mismatched = account_bound_resources(acct.name, runtime.config)
            skipped += len(mismatched)
    return benched, skipped


def resource_ids_of_account(account: str, config=None) -> list[str]:
    """反查该 ZCode 账号映射到哪些网关资源 id。

    约定：资源 `account` 备注 == ZCode 账号名（资源定义 = 厂商 + 账号 + Key，Q20-③），
    **且**该资源声明了自己属于 `product: zcode`（D7 字段）。

    🔴 为什么要 `product` 这一层（验收 eng-M-4）：只按备注字符串相等匹配时，
    任何**别的产品**的资源只要备注恰好写成同一个字符串，就会被 ZCode 的风控熔断
    一并 bench —— 熔断的作用域写错了产品，用户看到的是"商汤的 Key 莫名冷却 30 分钟"。
    `product` 为空表示"未声明"（旧配置），按账号备注匹配继续生效（向后兼容），
    但只要有一侧明确声明了别的产品，就**不**纳入。

    ⚠️ `config` 必须由调用方给**运行中的快照**（`runtime.config`）：
    原先在此处 `load_config()` 读默认路径，测试注入临时配置时会对不上，
    且热重载后拿到的可能是旧文件。仅在无 config 时才回退读文件。
    """
    if config is None:
        try:
            from model_gateway.config.loader import load_config
            config = load_config()
        except Exception:  # noqa: BLE001 — 配置不可用时不阻断运营
            return []
    from model_gateway.upstream.zcode import store
    want = store.PRODUCT
    return [r.id for r in config.resources
            if (r.account or "").strip() == account
            and (not (r.product or "").strip() or r.product == want)]


def account_bound_resources(account: str, config=None) -> tuple[list[str], list[str]]:
    """`(纳入熔断的资源 id, 同名但产品不符而被跳过的资源 id)`。

    🔴 为什么要第二个返回值（验收 ix-M-6）：熔断的**唯一可见出口**就是这张回写表，
    而它依赖"账号备注字符串恰好等于 ZCode 账号名"。用户写得不一致时，回写静默空转 ——
    熔断文件生效了、界面上一个资源都没变，看起来像"熔断没起作用"。
    这条判据必须能被看见，所以匹配结果要能分开数。
    """
    if config is None:
        try:
            from model_gateway.config.loader import load_config
            config = load_config()
        except Exception:  # noqa: BLE001
            return [], []
    from model_gateway.upstream.zcode import store
    want = store.PRODUCT
    hit: list[str] = []
    skipped: list[str] = []
    for r in config.resources:
        if (r.account or "").strip() != account:
            continue
        prod = (r.product or "").strip()
        (hit if not prod or prod == want else skipped).append(r.id)
    return hit, skipped


def bench_account(runtime, account: str, *, reason: str,
                  seconds: float | None = None) -> int:
    """把某 ZCode 账号对应的资源**全部 bench**（熔断接线点，§17）。

    调用时机：① 领取遇 3012 风控；② 额度耗尽。

    🔴 正因两条成因共用这一个接线点，**成因不在这里判**（既不看 `reason` 文案也不加参数）：
    由调用侧的作用域声明 —— 熔断那几处（`bench_all_zcode` / `sync_circuit_to_runtime` /
    管理端点 `/admin/api/zcode/bench`）包在 `circuit_hold_scope(runtime)` 里，
    额度耗尽那条（`apply_snapshot_to_runtime`）在作用域之外。
    签名保持原样也是契约的一部分：既有判据的假件按这个签名替换本函数（验收 S-16）。
    """
    rids = resource_ids_of_account(account, runtime.config)
    if not rids:
        return 0
    return apply_to_resource(runtime, rids, reason=reason, seconds=seconds)


#: 从日志/响应里识别风控文案（辅助诊断）
_RISK_TEXT = re.compile(r"unusual activity|异常活动|风控", re.IGNORECASE)


def looks_like_risk_control(message: str | None) -> bool:
    return bool(message and _RISK_TEXT.search(message))
