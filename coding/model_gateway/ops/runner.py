"""批量运营执行器（tech-design v2.0 §16.4 / PRD Q27-④）。

执行策略（逐条对应方案）：

| 策略 | 落地 |
|---|---|
| 并发 | **串行 + 间隔 + 随机抖动**（实测批量操作敏感，探测阶段已有 1/3 触发 429） |
| **双层互斥** | **plan 级 `TryLock`**（拿不到跳过本 tick，不排队）+ **账号级锁**（防 CLI/管理端点与 cron 双领） |
| 失败隔离 | **逐账号**，单账号失败不中断其余 |
| 重试 | **仅网络类 / 5xx 退避重试**；**业务码不重试** |
| 空跑语义 | ① 有账号参与但全无需动作 → `success`；② **`N=0` → `inactive`**（**不得报 success**） |
| 参与范围 | 跳过 `enabled=false` 账号 |
| 结果出口 | 落 `data/usage/ops-results-<date>.jsonl`（**网关 cron 与 CLI 两条腿都写**）；顶栏红点的未读数以该文件 + 已确认水位为准（`unread_failures`/`ack_reports`） |

🔴 **硬边界**（§16.6）：本模块**不 import** `core/scheduler` 与 `core/errors.ErrorClassifier`
（后者会把 `HTTP 400 + code 1003` 判成 `BAD_REQUEST`，与 §16.3 教训 2 冲突）。
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import logging
import os
import random
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Awaitable, Callable

from model_gateway.core import paths
from model_gateway.ops.base import OpReport, OpResult

#: 账号间基础间隔（秒）+ 0~50% 随机抖动（防风控）
DEFAULT_DELAY_S = 1.2

#: 网络类失败的退避序列（ms）—— 业务码**不重试**
RETRY_BACKOFF_MS = (500, 1500, 4000)

#: 每个账号单轮最大尝试次数（防死循环）
MAX_ATTEMPTS_PER_ACCOUNT = 3


#: 锁目录环境变量（测试隔离用）；缺省见 `ops_lock_dir()`
OPS_LOCK_DIR_ENV = "MGW_OPS_LOCK_DIR"

#: 计划锁占用 `AccountLocks` 里的键名
PLAN_LOCK_KEY = "__plan__"

#: 🔴 锁的最长持有时间：超过即视为陈旧可回收。
# 存在的意义是**防"永远拿不到锁"**：pid 会被内核复用，一个死进程留下的锁文件
# 若只按"pid 是否存活"判定，复用到同号进程后会被永久误判为"别人在持有"
# （验收 M-2 第 ④ 条）。运营一轮是秒级，15 分钟远超任何正常轮次。
LOCK_MAX_AGE_S = 15 * 60

#: 刚 `O_CREAT` 完、pid 还没写进去的窗口：此窗口内不得被别人抢走（M-2 第 ② 条 TOCTOU）
LOCK_WRITE_GRACE_S = 2.0

#: 「本轮因互斥不可用而拒跑」的原因前缀（第八轮 ix-8：CLI 抬头必须把它与
#: "发起后失败"分开说，否则 `✗ 失败 3 个` 会被读成"领了但没成功"）
LOCK_REFUSAL_PREFIX = "运营互斥锁目录"

#: **本进程**当前持有的锁，键 = (锁目录, 账号)（所有实例共享）。
# 锁文件按 pid 判活 → 同进程的第二个实例会把文件当成"自己的陈旧锁"回收，
# 所以同进程互斥靠这个集合；跨进程互斥才靠文件。
# 键里带目录是防"另一个实例换了锁目录却互相顶锁"（M-2 第 ③ 条）。
_HELD_BY_US: set[tuple[str, str]] = set()
_HELD_GUARD = threading.Lock()

#: 本进程本次持锁的随机令牌（防 pid 复用时误删他人在持有的锁）
_LOCK_TOKEN = secrets.token_hex(8)

logger = logging.getLogger("model_gateway.ops")


def ops_lock_dir() -> Path:
    """运营锁目录（**调用时**解析，故环境变量对模块级单例也生效）。"""
    raw = (os.environ.get(OPS_LOCK_DIR_ENV) or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    # 🔴 必须与 cwd 无关：cron 在网关进程（repo cwd）、`mgw zcode claim` 在 CLI 进程
    #    （用户可能在 ~ 或任意目录执行）—— 相对路径会让两边各用一把锁目录，
    #    §16.4 的跨进程互斥就此静默失效（验收 M-4）。
    return paths.data_dir() / "ops-locks"


class AccountLocks:
    """账号级互斥（§16.4 第二层）：**进程内 + 跨进程**双层。

    防 **CLI / 管理端点手动**与 cron 并发双领 —— 同一账号同时只允许一个操作在飞。

    🔴 为什么必须落到文件（上一轮修正）：`mgw zcode claim` 与网关的 cron 是**两个进程**，
    纯内存 `set` 各自一份 → 上一轮即使改成"模块级共享锁"，跨进程互斥**仍然不成立**。
    再把它的静默失效条件堵上（验收 M-2 / S-22）：
    ① 目录不可写 → **拒跑本轮**（fail closed，用户裁决），不放行、也不退到 `/tmp`；
    ② 刚创建未写 pid 的窗口 → 抢不走（写宽限期）；
    ③ 同进程多实例顶锁 → 持有集按 (目录, 账号) 记；
    ④ pid 复用让锁永挡 → 超 `LOCK_MAX_AGE_S` 视为陈旧；
    ⑤ 误删他人锁 → 文件内容带本进程令牌，release 双条件匹配。

    🔴 ① 为什么撤掉 `/tmp` 退路（原 M-2 ① 的修法，本轮由用户裁决推翻）：退路的毛病
    不是"会失败"，而是**成功得可疑** —— `/tmp` 本机所有人可写、重启即清，而
    "数据目录不可写"本身已经说明这份配置的状态写不进去（熔断文件、领取落盘同样会失败）。
    在这种环境下继续跑，用户看到的是一次"互斥成立、领取正常"的结果，
    实际落点却在一个随时会消失的目录里；明确拒跑至少不谎报。

    `lock_dir=None` = 走默认目录（`ops_lock_dir()`）；显式传目录可隔离测试。
    """

    def __init__(self, lock_dir: Path | None = None) -> None:
        self._dir = Path(lock_dir) if lock_dir else None

    # —— 锁文件路径与内容 ——

    @property
    def lock_dir(self) -> Path:
        return self._dir if self._dir is not None else ops_lock_dir()

    def _key(self, account: str) -> tuple[str, str]:
        return (str(self.lock_dir), account)

    def _path_in(self, base: Path, account: str) -> Path:
        safe = re.sub(r"[^0-9A-Za-z._-]", "_", account or "")[:80] or "anonymous"
        return base / f"{safe}.lock"

    def _path(self, account: str) -> Path:
        return self._path_in(self.lock_dir, account)

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        """pid 存活探测（同 `instance_lock` 口径：宁可误拒不猜测）。"""
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @staticmethod
    def _read_lock(path: Path) -> tuple[int | None, str, float]:
        """返回 `(pid, token, 年龄秒)`；读不到/损坏时 pid=None。"""
        try:
            text = path.read_text(encoding="utf-8").strip()
            age = max(0.0, time.time() - path.stat().st_mtime)
        except OSError:
            return None, "", 0.0
        parts = text.split()
        try:
            pid = int(parts[0]) if parts else None
        except ValueError:
            pid = None
        return pid, (parts[1] if len(parts) > 1 else ""), age

    def _try_create(self, path: Path) -> bool:
        """原子创建并写入 `pid token`；已被他人有效持有 → False。"""
        for _ in (0, 1):
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pid, _token, age = self._read_lock(path)
                if pid is None:
                    # 空/损坏：可能是别人刚创建还没写 pid（TOCTOU）→ 宽限期内不抢
                    if age < LOCK_WRITE_GRACE_S:
                        return False
                    path.unlink(missing_ok=True)      # 真损坏 → 回收后重试
                    continue
                if pid == os.getpid():
                    path.unlink(missing_ok=True)      # 自己上次留下的陈旧锁 → 回收
                    continue
                alive_and_young = (self._pid_alive(pid)
                                   and age < LOCK_MAX_AGE_S)
                if alive_and_young:
                    return False                      # 别人确实还在持有 → 跳过不排队
                path.unlink(missing_ok=True)          # 已死 / 超龄 → 陈旧回收
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(f"{os.getpid()} {_LOCK_TOKEN}")
            return True
        return False

    def _acquire_file(self, account: str) -> bool:
        """拿锁。返回 False = **别人正持有** 或 **锁不可用**（两者都不得放行双领）。

        🔴 主目录不可写就拒（用户裁决 S-22 fail closed）：`run_once` 会先做一次
        `usable()` 探测把成因报出来，这里只是第二道防线 —— 但**任何** OSError
        都只能得到 False，绝不"因为拿不到锁所以直接干"。
        """
        target = self._path(account)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            return self._try_create(target)
        except OSError as e:                 # 只读目录 / 权限 / 磁盘问题
            logger.error("运营互斥锁目录不可用（%s：%s）→ 拒绝该账号本轮，不冒险双领",
                         target.parent, e)
            return False

    def usable(self) -> bool:
        """锁目录**现在**能否建立互斥（建目录 + 试写 + 收回）。

        只在一个用途上需要它：把"别人正在持有"（正常，静默跳过）与
        "锁根本建不起来"（异常，运营会每轮静默停摆）分开 —— 两者的返回值
        都是 `try_acquire() == False`，而只有后者需要告诉用户。
        """
        probe = self._path(".write-probe")
        try:
            probe.parent.mkdir(parents=True, exist_ok=True)
            probe.write_text(f"{os.getpid()} {_LOCK_TOKEN}", encoding="utf-8")
        except OSError as e:
            logger.error("运营互斥锁目录不可写（%s：%s）", probe.parent, e)
            return False
        with contextlib.suppress(OSError):
            probe.unlink(missing_ok=True)
        return True

    def _release_file(self, account: str) -> None:
        path = self._path(account)
        pid, token, _age = self._read_lock(path)
        # 🔴 双条件：pid 与本次持锁令牌都要匹配，才删（防 pid 复用误删他人锁，M-2 ⑤）
        if pid == os.getpid() and token == _LOCK_TOKEN:
            try:
                path.unlink(missing_ok=True)
            except OSError as e:
                # 🔴 `unlink(missing_ok=True)` 只吞 `FileNotFoundError` —— 目录被改成只读、
                #    外接盘抖动都会抛 `PermissionError`/`OSError`（验收 S-24，面板实测）。
                #    这条路径在 `run_once` 与 `Scheduler._tick` 的 `finally` 上，异常冒出去
                #    会当场杀死定时器任务 = 运营从此不再跑，而进程看着一切正常 ——
                #    正是 S-22 要消灭的那种静默停摆。锁文件有 `LOCK_MAX_AGE_S` 兜底
                #    （超龄视为陈旧、会被后来者回收），留在盘上不致命，绝不为此牺牲调度。
                logger.warning("运营锁释放失败（%s：%s）→ 交给超龄回收，不向上抛", path, e)

    def try_acquire(self, account: str) -> bool:
        key = self._key(account)
        with _HELD_GUARD:
            if key in _HELD_BY_US:
                return False
            # 先登记再落盘：同进程内**另一个 AccountLocks 实例**也抢不到同一账号
            _HELD_BY_US.add(key)
        if not self._acquire_file(account):
            with _HELD_GUARD:
                _HELD_BY_US.discard(key)
            return False
        return True

    def release(self, account: str) -> None:
        key = self._key(account)
        with _HELD_GUARD:
            if key not in _HELD_BY_US:
                return
            _HELD_BY_US.discard(key)
        self._release_file(account)


class PlanLock:
    """计划级互斥（§16.4 第一层）：拿不到就**跳过本 tick，不排队**。

    同样两层：进程内 `threading.Lock` + 锁文件（cron 与手动触发分属两个进程）。
    """

    def __init__(self, path: Path | None = None) -> None:
        self._lock = threading.Lock()
        #: 复用 `AccountLocks` 的文件机制，计划锁占用 `__plan__` 这个键名
        self._files = AccountLocks(path)

    def try_acquire(self) -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        if not self._files.try_acquire(PLAN_LOCK_KEY):
            self._lock.release()
            return False
        return True

    @property
    def lock_dir(self) -> Path:
        return self._files.lock_dir

    def usable(self) -> bool:
        """锁目录能否建立互斥（把"别人正持有"与"根本建不起来"分开，验收 S-22）。"""
        return self._files.usable()

    def release(self) -> None:
        # 🔴 无论文件释放发生什么，进程内那把 `threading.Lock` **必须**放开（验收 S-24）：
        #    原先 `_files.release()` 在前且 unprotected，一次抛出就让它后面的
        #    `_lock.release()` 永远不执行 —— 本进程的 plan 锁被自己永久占住，
        #    之后每个 tick 都"正被持有"，运营再也跑不起来，重启才好。
        try:
            self._files.release(PLAN_LOCK_KEY)
        finally:
            with contextlib.suppress(RuntimeError):   # 没持有过就 release
                self._lock.release()


#: 模块级共享锁（§16.4 双层互斥的第二层）。
# 🔴 必须是**进程内单例 + 落盘锁文件**：
#    ① 原实现在 `run_once` 内每次新建 `AccountLocks()` → 两次调用各持一把锁（内存锁失效）；
#    ② 只改单例仍不够 —— cron 在网关进程、`mgw zcode claim` 在 CLI 进程，
#       跨进程要靠锁文件（本轮修正）。
_SHARED_LOCKS = AccountLocks()

#: 单账号操作的签名：`(account) -> OpResult`（生产注入真实 HTTP；单测注入假序列）
ClaimFn = Callable[..., Awaitable[OpResult]]


# ⚠️ 已删除 `classify_http_error()` / `is_retryable()`（验收修正）：
#    它们与 `ops/builtin/zcode_claim.classify()`（**实际使用**的那份）**重复实现同一张业务码表**。
#    按"不过度设计"原则保留一份 —— 业务码判定以 `zcode_claim.classify` 为准（§16.3）。
#    重试判定 = `_retryable_of()`（结构化声明优先，前缀约定只作未声明时的回退）。


def _looks_retryable(detail: str) -> bool:
    """从失败详情判断是否网络类（**仅回退用**：生产由 claim 侧给出规范化前缀）。

    🔴 这只是**未声明重试性**时的兼容回退（zcode 侧旧调用方遵守前缀约定）；
    产品钩子一律经 `OpResult.retryable` 结构化表态，不走文案猜谜
    （R1-F2：中文文案对不上前缀 → 产品通路的网络类失败从不退避重试）。
    """
    d = (detail or "").lower()
    return d.startswith("network:") or d.startswith("timeout:") or "http 5" in d


def _retryable_of(r: OpResult) -> bool:
    """退避重试判据（§22.6「失败退避仅网络/5xx、业务码不重试」/ §22.8-10）。

    **结构化声明优先**：`OpResult.retryable` 有表态（True/False）就以它为准；
    只有 `None`（未声明，如 zcode 既有执行器）才回退 `_looks_retryable` 的前缀约定。
    """
    if r.retryable is not None:
        return bool(r.retryable)
    return _looks_retryable(r.detail)


async def _run_one(account: str, claim: ClaimFn, *, attempts: int = MAX_ATTEMPTS_PER_ACCOUNT,
                   sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> OpResult:
    """单账号执行（含网络类退避重试）。

    **单账号失败不抛异常** —— 返回 `OpResult(category="failed")`，由调用方隔离。
    """
    last: OpResult | None = None
    for i in range(attempts):
        try:
            r = await claim(account)
        except Exception as e:  # noqa: BLE001 — 任何异常都归为 failed，不中断批量
            last = OpResult(account, "failed", f"{type(e).__name__}: {e}")
            r = last
        if r.category != "failed":
            return r
        last = r
        # 只有网络类才退避重试；业务失败不重试（判据 = `_retryable_of`：结构化优先）
        if not _retryable_of(r):
            break
        if i < len(RETRY_BACKOFF_MS):
            await sleep(RETRY_BACKOFF_MS[i] / 1000)
    return last or OpResult(account, "failed", "未知失败")


def product_of_account(account: str) -> str:
    """账号 → 产品标识（§16.4 能力声明的判据输入）。

    M6-1 起**遍历 `accounts/registry.py` 的产品表**（原为写死 zcode，Q29-③ 修订：
    在册 10 实例）—— 新增产品只需在注册表登记，不必改这里。
    各产品的账号根由 `accounts.store.product_root()` 解析（zcode 沿用
    `MGW_ZCODE_ACCOUNTS`，其余产品 = `data/upstream/<product>/accounts`）。
    认不出的账号返回 ""，由执行器**显式跳过并说明**，不静默执行。
    """
    from model_gateway.accounts import store as accounts_store
    from model_gateway.accounts.registry import PRODUCT_IDS

    if not account:
        return ""
    for product in PRODUCT_IDS:
        root = accounts_store.product_root(product)
        if accounts_store.has_account(root, account):
            return product
    return ""


def all_accounts(products: tuple[str, ...] | None = None) -> list[str]:
    """枚举在册产品的账号（缺省 = 全部在册产品；给出 `products` 时只枚举这些产品）。

    🔴 **跨产品枚举是"多产品运营"的最后一公里**（§22.6 / R4-BL-3）：原实现把缺省账号
    写死为 `upstream.zcode.store.list_accounts()` —— 于是即便 operation 声明了全部
    10 个产品，cron/批量路径也**永远只看得见 zcode 账号**，新产品"注册了但没人跑"。
    判据与各产品账号根同源（`accounts.store.list_accounts`：目录里有 `meta.json`
    才算账号），账号名按产品顺序去重（同名跨产品在 `product_of_account` 口径下本就
    解析到首个在册产品，重复枚举只会把同一动作跑两遍）。
    """
    from model_gateway.accounts import store as accounts_store
    from model_gateway.accounts.registry import PRODUCT_IDS

    pids = PRODUCT_IDS if products is None else tuple(products)
    seen: set[str] = set()
    out: list[str] = []
    for pid in pids:
        for name in accounts_store.list_accounts(pid):
            if name not in seen:
                seen.add(name)
                out.append(name)
    return out


async def run_once(
    *,
    accounts: list[str] | None = None,
    enabled_of: Callable[[str], bool] | None = None,
    claim: ClaimFn | None = None,
    operation=None,
    product_of: Callable[[str], str] | None = None,
    manual: bool = False,
    locks: AccountLocks | None = None,
    runtime=None,
    delay_s: float = DEFAULT_DELAY_S,
    jitter: bool = True,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> OpReport:
    """执行一轮批量领取。

    - `accounts` 缺省 = 全部在册产品的账号（给出 `operation` 时**按它声明的产品枚举**，
      §22.6 多产品运营；无 operation 的旧默认仍是 zcode 账号口径）
    - `enabled_of` 给出时，**跳过 `enabled=false` 的账号**（§16.4 参与范围）
    - 🔴 `operation`（`base.AccountOperation`）给出时，**按其 `supported_products` 过滤参与方**
      （§16.4「per-operation 声明，不按产品整体开关」）：产品不在声明内的账号
      **跳过并在结果里说明原因**，而不是拿别的产品接口去误跑；`claim` 也缺省取该 operation
    - `claim` 缺省 = 真实 ZCode 领取实现（`ops.builtin.zcode_claim`）
    - `manual` = 用户手动过验证码（无住宅代理时的降级路径）
    - `locks` 缺省 = **模块级共享锁**（保证 cron 与 CLI 手动之间互斥）
    - `runtime` 给出时透传给 claim（**风控熔断接线**，§17）
    """
    report = OpReport()

    if accounts is None:
        if operation is not None:
            # 🔴 枚举面与参与方声明**同源**（§22.6 多产品运营）：按该动作声明的产品枚举，
            #    否则新产品账号在批量路径上"注册了但没人枚举到"（R4-BL-3）。
            #    按声明枚举而非"全枚举+过滤"，也免得每个 tick 把别家账号刷成一串 skipped。
            accounts = all_accounts(operation.supported_products)
        else:
            # 旧默认（无 operation：claim 缺省 = zcode 执行器）维持 zcode 账号口径
            from model_gateway.upstream.zcode import store
            accounts = [a.name for a in store.list_accounts()]

    if operation is not None and claim is None:
        claim = operation.run

    # 🔴 §16.4 能力声明过滤：动作不认该产品 → 明确跳过（不得"顺手也跑一下"）
    if operation is not None:
        pick = product_of or product_of_account
        keep = []
        for a in accounts:
            product = pick(a)
            if operation.supports(product):
                keep.append(a)
            else:
                report.skipped.append(
                    f"{a}（产品 {product or '未知'} 不在 {operation.id} 的支持范围 "
                    f"{'/'.join(operation.supported_products)} 内）")
        accounts = keep

    # 参与范围过滤：运营类**跳过 disabled 账号**（续期类不看 enabled，那是另一个开关）
    if enabled_of is not None:
        keep = []
        for a in accounts:
            if enabled_of(a):
                keep.append(a)
            else:
                report.skipped.append(a)
        accounts = keep

    # 🔴 空跑情形 ②：**无账号参与 → 记 `inactive` + 明确说明**（§16.4「不得报 success」）
    #    注意判据在**两道过滤之后**：账号全被产品/停用过滤掉同样属于"无人参与"。
    if not accounts:
        report.inactive.append("（无账号参与）")
        report.no_participants = True
        return report

    if claim is None:
        from model_gateway.ops.builtin.zcode_claim import claim as claim  # noqa: PLC0415

    locks = locks if locks is not None else _SHARED_LOCKS

    # 🔴 互斥前提不成立 = **整轮拒跑**（用户裁决 S-22 fail closed，不再退 `/tmp`）。
    #    记成 `failed` 而不是 `skipped`：这一轮一个账号都没发起，而原因在用户侧
    #    （数据目录权限/只读挂载）—— 只有 `failed` 才会进 `ops-results` 落盘、
    #    点亮顶栏红点、让 CLI 退出码非 0。`skipped` 是"正常没动作"，会被读成没事。
    if not locks.usable():
        why = (f"{LOCK_REFUSAL_PREFIX}不可写：{locks.lock_dir} —— 跨进程互斥建立不起来，"
               "本轮未对任何账号发起操作（宁可拒跑也不双领）。"
               "请检查数据目录权限或是否被只读挂载")
        for a in accounts:
            report.add(OpResult(a, "failed", why))
        return report

    for idx, account in enumerate(accounts):
        # 🔴 第二层互斥：账号级锁（防 CLI/管理端点与 cron 双领）
        if not locks.try_acquire(account):
            # `try_acquire()` 的 False 有两种成因（第八轮 eng-8b 的阻塞）：
            #   ① 别人正持有这个账号 = 设计内的静默跳过；
            #   ② 本轮**中途**锁目录失去可写性 —— 开局探测时还好好的（S-22 只堵住了开局）。
            # 原先两种都走 `skipped`，于是真实 CLI 打印"全部正常，无需处理"、退出码 0、
            # 红点 0，而实际上本账号及其后所有账号**一个都没发起** ——
            # 与用户 S-22 的裁决（主目录不可写即拒跑本轮）自相矛盾。
            if not locks.usable():
                why = (f"{LOCK_REFUSAL_PREFIX}在本轮中途不可写：{locks.lock_dir} —— "
                       f"跨进程互斥建立不起来，本账号及其后共 {len(accounts) - idx} 个账号"
                       "均未发起操作（宁可拒跑也不双领）。请检查数据目录权限或是否被只读挂载")
                for rest in accounts[idx:]:
                    report.add(OpResult(rest, "failed", why))
                return report
            report.skipped.append(account)
            continue
        try:
            r = await _run_one(account, lambda a: claim(a, manual=manual, runtime=runtime),
                               sleep=sleep)
            report.add(r)
        finally:
            locks.release(account)
        # 账号间间隔 + 0~50% 抖动（防风控）
        if idx < len(accounts) - 1:
            d = delay_s
            if jitter:
                d += random.random() * delay_s * 0.5
            if d > 0:
                await sleep(d)
    return report


def write_report(report: OpReport, usage_dir: Path | None = None) -> Path | None:
    """落盘 `data/usage/ops-results-<date>.jsonl`（与 `events-*.jsonl` 同形态）。

    🔴 两条写入路径都必须调它：网关 cron 腿与 `mgw zcode claim`（CLI 独立进程）——
    红点的未读数以这份文件为准（`unread_failures`），CLI 不落盘就等于
    "界面上指路的那个文件里永远没有 CLI 看到的失败"（验收 M-4）。
    """
    # 兜底目录同样经 `core/paths`（认 MG_CONFIG、绝对路径）——
    # 原先写死 `Path("data")/"usage"` 是相对 cwd 的，违反本轮立的"与 cwd 无关"纪律（L-4）
    base = Path(usage_dir) if usage_dir else default_usage_dir()
    try:
        base.mkdir(parents=True, exist_ok=True)
        path = _results_path(base)
        line = json.dumps({
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
            **report.to_dict(),
        }, ensure_ascii=False)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        return path
    except OSError as e:
        # 🔴 落盘失败**必须留痕**（验收 S-26④）：顶栏红点的未读数以这份文件为唯一事实源
        #    （S-5 的裁决），写不进去 = 这一轮的失败对用户彻底不存在。
        #    原先静默 `return None` 比不跑更糟：界面说"逐条原因见 ops-results-*.jsonl"，
        #    而那个文件里什么都没有，用户只会认为"没有失败"。
        logger.error("运营结果落盘失败（%s：%s）→ 本轮明细未写入 %s，"
                     "顶栏红点不会点亮这些失败；请检查数据目录权限", base, e, base)
        return None


def _results_path(usage_dir: Path | None = None, day: str | None = None) -> Path:
    base = Path(usage_dir) if usage_dir else default_usage_dir()
    return base / f"ops-results-{day or _today()}.jsonl"


def _ack_path(usage_dir: Path | None = None) -> Path:
    base = Path(usage_dir) if usage_dir else default_usage_dir()
    return base / "ops-results-ack.json"


def default_usage_dir() -> Path:
    """与网关同一个 `data/usage`（经 `core/paths` → 认 `MG_CONFIG`）。"""
    return paths.data_dir() / "usage"


def _today() -> str:
    return dt.datetime.now().strftime("%Y%m%d")


def _report_rows(path: Path) -> list[dict]:
    """读当日结果文件（逐行 JSON；坏行跳过而不是整读失败）。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _backlog(usage_dir: Path, day: str) -> tuple[list[dict], int]:
    """同一次读里拿到 `(当日全部行, 已确认水位行号)` —— **只能是一个快照**。

    🔴 为什么强调"一次"（验收 S-13）：未读数与水位若分两次读文件，
    两次之间另一个进程（网关 cron，或另一个终端里的 CLI）追加的行会被水位一起推进去 ——
    `cleared` 报得比用户真正见过的多，而那些行用户从未看过。
    """
    rows = _report_rows(_results_path(usage_dir, day))
    acked = 0
    try:
        ack = json.loads(_ack_path(usage_dir).read_text(encoding="utf-8"))
        if isinstance(ack, dict) and ack.get("date") == day:
            acked = int(ack.get("rows") or 0)
    except (OSError, ValueError, TypeError):
        pass
    return rows, max(0, acked)


def unread_failures(usage_dir: Path | None = None) -> int:
    """顶栏红点的**未读失败数** = 当日落盘结果里、用户尚未确认过的那些 `failed`。

    🔴 为什么以文件为准而不是内存计数（验收 S-5）：
    原先 `runtime.ops_failed_unread` 是网关进程内的累加器，于是
    ① `mgw zcode claim`（**另一个进程**）看到的失败永远点不亮红点；
    ② 网关重启把"还没人看过"的失败一起清零 —— 而文件里明明还在。
    以 jsonl 为唯一事实源后，CLI 与 cron 两条写入路径天然等价，跨进程、跨重启一致。
    复用既有 `/admin/api/status` 5s 轮询，**不新建轮询、不新建页面、不新建端点**。
    """
    base = Path(usage_dir) if usage_dir else default_usage_dir()
    rows, acked = _backlog(base, _today())
    return sum(len(r.get("failed") or []) for r in rows[acked:])


def ack_reports(usage_dir: Path | None = None) -> int:
    """记"用户已确认"水位（清零红点），返回本次清掉的条数（§21 / M-IX-2）。

    🔴 必须有清零出口 —— 验收发现：原实现**只增不减**，一次失败后红点永久常亮。
    水位记**已读行数**（不是时间戳）：行序是本地追加事实，不受系统时钟调整影响，
    也不会因"同一秒内既有失败又有确认"而漏账。
    🔴 计数与写水位取自**同一份快照**（`_backlog`，验收 S-13），否则会吞掉并发新行。
    """
    base = Path(usage_dir) if usage_dir else default_usage_dir()
    day = _today()
    rows, acked = _backlog(base, day)
    cleared = sum(len(r.get("failed") or []) for r in rows[acked:])
    try:
        base.mkdir(parents=True, exist_ok=True)
        tmp = _ack_path(base).with_suffix(".tmp")
        tmp.write_text(json.dumps({"date": day, "rows": len(rows)}), encoding="utf-8")
        os.replace(tmp, _ack_path(base))
    except OSError:
        return 0
    return cleared


# ---------- 计划级互斥 + 定时（§16.4）----------

class Scheduler:
    """运营调度器：plan 级 `TryLock` + 定时 tick（§16.4）。

    与 `core/scheduler.py`（模型转发调度）**同名不同物** —— 本类只管运营批量的触发时机。

    两种触发方式（二选一）：
    - `interval_s`：固定间隔（默认 60s）
    - `cron`：**5 段 cron 表达式**（分 时 日 月 周），每分钟检查一次是否命中
    """

    def __init__(self, *, interval_s: float = 60.0, cron: str = "",
                 plan_lock: PlanLock | None = None):
        self.interval_s = interval_s
        self.cron = (cron or "").strip()
        self.plan_lock = plan_lock or PlanLock()
        self._task: asyncio.Task | None = None
        #: 因 cron 未命中而跳过的 tick 数（诊断用）
        self.skipped_ticks = 0
        #: tick 内异常次数（诊断：运营停摆时先看这个）
        self.errors = 0

    def _should_fire(self, now: dt.datetime) -> bool:
        if not self.cron:
            return True
        return cron_matches(self.cron, now)

    async def _tick(self, run: Callable[[], Awaitable[None]]) -> None:
        # 🔴 plan 级 TryLock：拿不到**直接跳过本 tick，不排队**（防堆积）
        if not self.plan_lock.try_acquire():
            # 两种成因返回值一样，但只有一种该说出来（验收 S-22）：
            # ① 另一路（CLI 或上一 tick）正在跑 = 正常，静默跳过；
            # ② 锁目录建不起来 = 每一轮都会静默跳过 = **运营停摆而进程看着正常**，
            #    正是下面注释里"最难查的那种故障"，必须计一次错误并留日志。
            if not self.plan_lock.usable():
                logger.error("运营 plan 锁不可用（%s）→ 定时器每轮都会跳过，运营已停摆；"
                             "请检查数据目录权限", self.plan_lock.lock_dir)
                self.errors += 1
            return
        try:
            await run()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — 单轮失败不得让定时器静默死亡
            # 原来异常会一路冒出 `loop()` → 任务结束 → **此后再也不跑**，
            # 而进程活着、界面正常，只有运营静默停摆（最难查的那种故障）。
            logger.warning("运营 tick 异常（下一轮继续）：%s: %s", type(e).__name__, e)
            self.errors += 1
        finally:
            # 🔴 收尾本身不许把异常抛回 `loop()`（验收 S-24）：任务一死，
            #    进程还活着、界面还正常，只有运营从此再也不跑 —— 最难查的那种故障。
            try:
                self.plan_lock.release()
            except Exception as e:  # noqa: BLE001 — 释放失败只记账，不终止调度
                self.errors += 1
                logger.warning("运营 plan 锁释放异常（下一轮继续）：%s: %s", type(e).__name__, e)

    def start(self, run: Callable[[], Awaitable[None]]) -> None:
        # cron 模式固定 60s 检查一次（cron 最小粒度是分钟）
        period = 60.0 if self.cron else self.interval_s

        async def loop() -> None:
            while True:
                # 🔴 **先等一个周期再跑**：t=0 就跑等于"每次启动网关都立刻发起一次真实领取"
                #   —— 用户没有要求这个行为，且它会在重启风暴里对着上游连打（§16.4 敏感）。
                await asyncio.sleep(period)
                if self._should_fire(dt.datetime.now()):
                    await self._tick(run)
                else:
                    self.skipped_ticks += 1

        self._task = asyncio.get_running_loop().create_task(loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None


# ---------- 5 段 cron 匹配（自研，无依赖）----------

def cron_matches(expr: str, when: dt.datetime) -> bool:
    """最小 5 段 cron 匹配（分 时 日 月 周）。

    支持 `*` / `*/n` / `a,b` / `a-b` / `a-b/n`（与参考实现同能力集）。
    """
    fields = (expr or "").split()
    if len(fields) != 5:
        return False
    values = (when.minute, when.hour, when.day, when.month, when.weekday() and when.isoweekday() % 7)
    for spec, val in zip(fields, values):
        if not _field_matches(spec, val):
            return False
    return True


def _field_matches(spec: str, value: int) -> bool:
    if spec == "*":
        return True
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, _, raw = part.partition("/")
            try:
                step = int(raw)
            except ValueError:
                continue
            if step <= 0:
                continue
        if part in ("", "*"):
            lo, hi = 0, 10**6
        elif "-" in part:
            a, _, b = part.partition("-")
            try:
                lo, hi = int(a), int(b)
            except ValueError:
                continue
        else:
            try:
                lo = hi = int(part)
            except ValueError:
                continue
        if lo <= value <= hi and (value - lo) % step == 0:
            return True
    return False
