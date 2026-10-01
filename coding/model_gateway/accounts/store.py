"""账号存储的**唯一入口**（tech-design v2.0 §22.2 布局 + §22.3 冻结 API）。

🔴 布局（§22.2）::

    data/upstream/<product>/accounts/<账号名>/
    ├── meta.json          # 元信息（设备字段 / via / 时间 / 备注 / family…）
    ├── credentials.json   # 凭据本体（**明文**；产品私有格式）
    └── runtime.json       # 运行态（冷却 / 最近错误 / 水印）—— 与凭据**分离**，不得混写

🔴 不变式（§22.2）：
    ① 全明文 + 原子写（tmp+rename）；
    ② 日志/事件里凭据**只以短哈希指纹**出现（`net.cred_fingerprint`，`23 B4`）；
    ③ 设备身份跨账号唯一 —— **决策**在 `device.py`/`plan_import_device`（§15.1 两条
       路径处置不同），本模块只落盘；
    ④ 运行态与凭据分离（Q25-⑥ 教训：混写会把运行态写进凭据文件）；
    ⑤ 落盘**只经本模块**（禁止 ad-hoc 写盘）；
    ⑥ **跨进程 fail-closed 互斥**（§22.8 硬清单第 4 条）：三条写路径
       （`commit_login` / `import_account` / `delete_account`）全程持
       `<data>/locks/accounts.lock`，形态照抄 `ops/runner.py::AccountLocks`
       （锁文件 + pid 判活 + 超龄回收 + 双条件释放）——**锁不可用一律拒写**，
       不退 `/tmp`、不"拿不到就直接干"（见 `_AccountsWriteLock`）。
🔴 `hook_meta()` = 钩子 `meta` 形参的**唯一组装入口**（§22.3 补入①）：锚字段
    `account`/`dir` + `meta.json` 铺开；入口层禁止自行拼这个 dict（§22.3 ③ 的 `meta` 通道）。
🔴 写回自检 + 失败整体回滚（照抄 `22 §5.7` verifyWritten）：落盘后**逐项读回**，
   本次传入的每个凭据键/元信息键都必须原值可见；任一不过 → 回滚到调用前状态
   （新建账号 → 删掉整个账号目录；既有账号 → 写回旧文件），并抛 `CommitError`。
   理由同参考实现：界面判"账号可用"只看目录在不在，不回滚会留下"永远切不过去"的账号。

⚠️ 账号根可被 `MGW_<PRODUCT>_ACCOUNTS` 覆盖（泛化既有的 `MGW_ZCODE_ACCOUNTS`，
   `upstream/zcode/store.py:53`）：门店外挂盘 / 测试隔离共用同一条口径。

🔴 异步服务路径（管理端登录 / 导入 / 删除 = 事件循环线程）**必须**走
   `commit_login_async` / `import_account_async` / `delete_account_async` 三条
   （A-1，面板修复轮-2）：同步版在循环线程里等跨进程锁最长 1.0s（eng-a 实测
   打点间隔 1007ms，整条事件循环停摆）；三条 async 把整段下放工作线程、语义逐字一致，
   CLI / 同步路径继续用同步版。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from model_gateway.accounts.device import (
    check_unique,
    find_account_by_values,
    generate_identity_values,
)
from model_gateway.accounts.net import cred_fingerprint
from model_gateway.accounts.types import DeviceSpec
from model_gateway.core import paths
from model_gateway.core.errors import register_secret_values

logger = logging.getLogger("model_gateway.accounts")

#: 账号名白名单（§22.2，照抄 `upstream/zcode/store.py:_sanitize` 的字符集）——防目录穿越
_ALLOWED_NAME_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
_NAME_MAX = 32


class CommitError(RuntimeError):
    """写回自检未通过（已整体回滚）——§22.3 的 `commit_login` 失败形态。"""


class RuntimeUnreadable(RuntimeError):
    """`runtime.json` **读不动**（损坏 / 非法 JSON）——§22.8-5「未知/读不动一律 fail closed」。

    与"文件不存在"（= 新账号，合法）分开：读不动时**必须**让调用方停止"按健康处理"。
    """


class WriteLockError(Exception):
    """账号写互斥**不可用 / 被占用** → 拒写（§22.8-4 fail closed，见 `_AccountsWriteLock`）。

    🔴 刻意**不继承** `CommitError`：后者的文案是"写回自检未通过（已整体回滚）"，
    而本异常抛出时**一个字节都没写**、也谈不上回滚 —— 套用那句文案会用错误的归因
    掩盖真实原因（"另一个进程正在写" vs "写坏了已回滚"）。调用方按需分流：
    `import_account` 转成可读 `ImportResult`；admin 端点按内部错误 500 回传（文案自带原因）。
    """


@dataclass
class ImportResult:
    """导入结果（照抄 `upstream/zcode/store.py::ImportResult` 的字段形态）。"""

    ok: bool
    account: str = ""
    device_id: str = ""
    message: str = ""
    #: True = **因设备身份冲突而拒绝**（调用方应打印 3 选项并退出非 0）
    conflict: bool = False
    #: 与哪个账号冲突
    conflict_with: str = ""
    #: 完整设备身份元组（顺序 == `DeviceSpec.fields`；`device_id` = 其首字段，兼容既有调用方）
    device_values: tuple[str, ...] = ()


@dataclass
class DevicePlan:
    """`plan_import_device()` 的决策结果（§15.1 三约束的**共用决策核心**）。"""

    ok: bool = False
    device_id: str = ""
    conflict: bool = False
    conflict_with: str = ""
    message: str = ""
    #: 完整设备身份元组（顺序 == `DeviceSpec.fields`；`device_id` = 其首字段）
    device_values: tuple[str, ...] = ()


# ---------- 路径与命名 ----------

def product_root(product: str) -> Path:
    """产品账号根：`data/upstream/<product>/accounts`（§22.2）。

    `MGW_<PRODUCT>_ACCOUNTS` 可覆盖（zcode 既有环境变量口径的泛化）——
    返回值绝对、与 cwd 无关（跨进程互斥与熔断落盘都依赖它）。
    """
    raw = (os.environ.get(f"MGW_{product.upper()}_ACCOUNTS") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return paths.data_dir() / "upstream" / product / "accounts"


def sanitize_name(name: str) -> str:
    """账号名白名单 `[A-Za-z0-9_-]{1,32}`（§22.2）——防目录穿越，照抄 zcode 口径。

    ⚠️ 本函数是**清洗**（剥离非法字符 + 截断 + 空值兜底 `"account"`，与 zcode 既有
    行为逐字一致）；`commit_login` 等**新建路径**用 `_require_name` 严格校验，
    不静默改用户填的名字。
    """
    cleaned = "".join(c for c in str(name or "") if c in _ALLOWED_NAME_CHARS)
    return cleaned[:_NAME_MAX] or "account"


def account_dir(root: Path | str, name: str) -> Path:
    """账号目录（名先过白名单再拼路径，杜绝 `../` 落点）。"""
    return Path(root) / sanitize_name(name)


def has_account(root: Path | str, name: str) -> bool:
    """该目录下是否存在该账号（判据 = 目录里有 `meta.json`，与 `list_accounts` 同一把尺）。

    空名一律 `False`（`sanitize_name("")` 会兜底成 `"account"`，那是**写入**侧的行为，
    读侧不能把它当成一个真账号）。
    """
    if not str(name or "").strip():
        return False
    return (account_dir(root, name) / "meta.json").exists()


def list_accounts(product: str, *, root: Path | str | None = None) -> list[str]:
    """列出该产品的账号名（按目录名排序）。

    🔴 判据必须是"有 `meta.json` 的目录"：账号根下的**任意**子目录不算账号
    （`upstream/zcode/store.py::list_accounts` 的教训——别的模块在同一数据目录落盘时
    会被误当成账号，运营批量会替它白跑一轮）。
    """
    base = Path(root) if root is not None else product_root(product)
    if not base.exists():
        return []
    out: list[str] = []
    for entry in sorted(base.iterdir()):
        if entry.is_dir() and (entry / "meta.json").exists():
            out.append(entry.name)
    return out


# ---------- 原子写 ----------

def atomic_write_json(path: Path | str, data: dict) -> None:
    """原子写 JSON：**同目录** tempfile + fsync + `os.replace`（§22.2 不变式①）。

    - 临时文件用 `mkstemp`（唯一名，非固定 `.tmp`）：跨进程并发写同一文件时
      固定名会被互相截断（zcode `quota.py` 撞过的真实缺陷）；
    - `fsync` 在 `os.replace` 之前：断电不留下"名字换了、内容还是旧的"的空壳。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent),
                                    prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ---------- 跨进程写互斥（§22.8-4 硬清单第 4 条；fail closed）----------

#: 锁目录环境变量（测试隔离用；与 `MGW_OPS_LOCK_DIR` 同一口径，`ops/runner.py:44`）
ACCOUNTS_LOCK_DIR_ENV = "MGW_ACCOUNTS_LOCK_DIR"

#: 锁文件名（**全局一把**：见 `_AccountsWriteLock` 的 ① 号说明）
ACCOUNTS_LOCK_NAME = "accounts.lock"

#: 锁的最长持有时间：超过即视为陈旧可回收（S-22 第 ④ 条：pid 会被内核复用，
#: 只按"pid 存活"判定会让死进程留下的锁被永久误认成"别人在持有"）
_LOCK_MAX_AGE_S = 15 * 60

#: 刚 `O_CREAT` 完、pid 还没写进去的窗口：此窗口内不抢（S-22 第 ② 条 TOCTOU）
_LOCK_WRITE_GRACE_S = 2.0

#: 等锁预算与轮询间隔（秒）：本机写盘是毫秒级，等一小段仍拿不到 → 确实有并发在写
_LOCK_WAIT_S = 1.0
_LOCK_POLL_S = 0.02

#: 本进程本次持锁的随机令牌（防 pid 复用时误删他人锁，S-22 第 ⑤ 条）
_LOCK_TOKEN = secrets.token_hex(8)

#: 进程内互斥（线程间）；同线程重入由 `_AccountsWriteLock` 的 thread-local 深度负责。
#: 写盘是毫秒级 → 全局一把不构成瓶颈，换取的是"配置与账号目录同临界区"这条硬要求。
_PROCESS_LOCK = threading.Lock()


def accounts_lock_dir() -> Path:
    """账号写互斥锁目录（**调用时**解析，故环境变量对模块级单例也生效）。

    缺省 = `data/locks`（`core/paths.data_dir()` 派生）——必须与 cwd 无关：
    网关在仓库根跑、`mgw` CLI 在用户任意目录跑，两边解析到**不同目录**时
    §22.8-4 的跨进程互斥就会像 M-4 那次一样静默消失（`core/paths.py` 的整段教训）。
    """
    raw = (os.environ.get(ACCOUNTS_LOCK_DIR_ENV) or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return paths.data_dir() / "locks"


class _AccountsWriteLock:
    """账号写路径的**跨进程 fail-closed 互斥**（§22.8-4）。形态照抄
    `ops/runner.py::AccountLocks`（锁文件 + pid 判活 + 超龄回收 + 双条件释放）。

    与运营锁的**两处有意差异**（都是账号写盘的语义要求，不是简化）：

    ① **全局一把锁**（`<data>/locks/accounts.lock`，不按账号分锁）：账号写路径的
       读-改-写横跨"账号目录 + 配置文件"两处 —— `commit_login` 成功后会紧跟
       `materialize` 的配置保存（读 config → 追加资源 → 写回），按账号分锁护不住
       "两个账号同时物化配置"的丢更新。写盘是毫秒级，粗粒度不构成瓶颈。
    ② 拿不到锁 → **拒写并抛可读错误**（不学运营的"跳过本轮"）：本模块是用户
       点保存/导入的同步面，静默跳过 = 用户以为写成功。等一小段
       （`_LOCK_WAIT_S`）仍拿不到 → 拒绝，理由写进异常文案。

    🔴 fail closed 的两层含义（照 S-22 口径）：
    - 锁**建不起来**（锁目录不可写 / 只读盘 / 磁盘满）→ 抛错**拒写**：绝不
      "因为拿不到锁所以直接干"，也不退到 `/tmp`（那是"成功得可疑"——互斥看似成立、
      落点却随时会消失，而"数据目录写不进去"本身就说明这份配置的状态存不下）；
    - 锁**被别人持有**（另一个进程正在写）→ 等预算耗尽后抛错拒写，绝不并发写盘。

    进程内：同线程可重入（`import_account` → `commit_login` 是嵌套），
    线程间由 `_PROCESS_LOCK` + 同一等待预算串行（同进程两个登录同时提交时，
    后者等前者写完，而不是被误伤成失败）。
    """

    def __init__(self, lock_dir: Path | str | None = None) -> None:
        self._dir = Path(lock_dir) if lock_dir is not None else None
        self._tls = threading.local()

    # —— 路径 ——

    @property
    def lock_dir(self) -> Path:
        return self._dir if self._dir is not None else accounts_lock_dir()

    @property
    def lock_path(self) -> Path:
        return self.lock_dir / ACCOUNTS_LOCK_NAME

    # —— 取/放（可作上下文管理器）——

    def __enter__(self) -> _AccountsWriteLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> bool:
        self.release()
        return False

    def acquire(self) -> None:
        depth = getattr(self._tls, "depth", 0)
        if depth:                                   # 同线程重入：记深度，不再落盘
            self._tls.depth = depth + 1
            return
        deadline = time.monotonic() + _LOCK_WAIT_S
        self._acquire_process_lock(deadline)
        try:
            self._acquire_file(deadline)
        except BaseException:
            _PROCESS_LOCK.release()                 # 文件锁没拿到：进程内那把必须还回去
            raise
        self._tls.depth = 1

    def release(self) -> None:
        depth = getattr(self._tls, "depth", 0)
        if depth > 1:
            self._tls.depth = depth - 1
            return
        if depth == 0:
            return
        self._tls.depth = 0
        try:
            self._release_file()
        finally:
            _PROCESS_LOCK.release()

    # —— 进程内（线程间）——

    def _acquire_process_lock(self, deadline: float) -> None:
        while not _PROCESS_LOCK.acquire(blocking=False):
            if time.monotonic() >= deadline:
                raise WriteLockError(
                    f"账号写互斥未取得：本进程另一个写操作正在进行（已等待 {_LOCK_WAIT_S:g}s）"
                    " → 本次**拒绝写入**（未落任何字节），请稍后重试")
            time.sleep(_LOCK_POLL_S)

    # —— 跨进程（锁文件；形态同 `ops/runner.py::AccountLocks._try_create`）——

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

    def _reclaim_if_stale(self, path: Path) -> bool:
        """陈旧锁回收；返回 True = 已收回（调用方应立刻重试创建）。

        不回收的两种情况：① 刚创建、pid 还没写进去（宽限窗口）；② 持有者 pid 存活
        且未超龄（**真有人在写**）。
        """
        pid, _token, age = self._read_lock(path)
        if pid is None:
            if age < _LOCK_WRITE_GRACE_S:
                return False                        # TOCTOU 窗口：不抢
            _unlink_quietly(path)
            return True                             # 空/损坏且已过宽限 → 回收
        if pid == os.getpid():
            # 本进程遗留（上次崩溃/异常退出时没走到 release）：进程内互斥在
            # `_PROCESS_LOCK` 上，活着的持有者不会走到这里 → 可安全回收
            _unlink_quietly(path)
            return True
        if self._pid_alive(pid) and age < _LOCK_MAX_AGE_S:
            return False                            # 别人确实还在持有
        _unlink_quietly(path)                       # 已死 / 超龄 → 陈旧回收
        return True

    def _acquire_file(self, deadline: float) -> None:
        path = self.lock_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            # 🔴 fail closed（S-22）：锁建不起来就**拒写**。绝不退 `/tmp` 退路 ——
            #    那会给出"互斥成立、写入成功"的假象，而落点在一个随时消失的目录里。
            raise WriteLockError(
                f"账号写互斥锁目录不可用（{path.parent}：{e}）→ 拒绝写入："
                "拿不到锁就落盘等于放弃互斥（并发写会静默丢更新），"
                "退到临时目录更只是把失败伪装成成功") from e
        while True:
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                if self._reclaim_if_stale(path):
                    continue
                if time.monotonic() >= deadline:
                    pid, _token, _age = self._read_lock(path)
                    raise WriteLockError(
                        f"账号写互斥被占用（{path}，持有者 pid {pid if pid else '未知'}，"
                        f"已等待 {_LOCK_WAIT_S:g}s）→ 本次**拒绝写入**（未落任何字节）："
                        "另一个进程正在写账号数据/配置，请稍后重试")
                time.sleep(_LOCK_POLL_S)
                continue
            except OSError as e:
                raise WriteLockError(
                    f"账号写互斥锁文件建不起来（{path}：{e}）→ 拒绝写入") from e
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(f"{os.getpid()} {_LOCK_TOKEN}")
            return

    def _release_file(self) -> None:
        path = self.lock_path
        pid, token, _age = self._read_lock(path)
        # 双条件（pid + 本次持锁令牌）才删：防 pid 复用时误删他人的锁（S-22 ⑤）
        if not (pid == os.getpid() and token == _LOCK_TOKEN):
            return
        try:
            path.unlink(missing_ok=True)
        except OSError as e:
            # 🔴 释放失败**不得向上抛**（同 `ops/runner.py` 的 S-24 复盘）：本函数在
            #    `finally` 上，抛出去会盖掉原始异常、把"写失败的原因"换成"释放失败"。
            #    留在盘上的锁由 `_LOCK_MAX_AGE_S` 超龄回收兜底。
            logger.warning("账号写互斥锁释放失败（%s：%s）→ 交给超龄回收，不向上抛", path, e)


def _unlink_quietly(path: Path) -> None:
    """回收陈旧锁文件（尽力而为；失败留日志，不打断写路径）。"""
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        logger.warning("陈旧账号写锁回收失败（%s：%s）→ 交给超龄回收", path, e)


#: 账号写路径的模块级单例锁（三条写路径共用；`lock_dir` 调用时解析 → 环境变量对
#: 模块级单例也生效，测试隔离口径同 `MGW_OPS_LOCK_DIR`）。
_WRITE_LOCK = _AccountsWriteLock()


# ---------- 读写 ----------

def load_meta(root: Path | str, name: str) -> dict:
    """读账号 `meta.json`（不存在/损坏 → 空 dict；**只读**，不改盘）。"""
    path = account_dir(root, name) / "meta.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def hook_meta(product: str, name: str, root: Path | str | None = None) -> dict:
    """钩子 `meta` 形参的**唯一组装入口**（tech-design v2.0 §22.3「会话与入口的补充约定」①）。

    返回 `{"account": name, "dir": str(账号目录), **meta.json 内容}`：

    - `account`（账号名）与 `dir`（该账号目录，`product_root` 缺省下为**绝对路径**）是
      **锚字段**：由本函数直接给出，`meta.json` 里的同名键**不得覆盖**——否则一份被污染/
      旧布局的元信息就能把钩子的落点引到别的目录（zcode 代理实测的「退化为 unknown、
      续期回写静默跳过」正是这类静默失效）。
    - 锚值取**白名单后的名字**（`account_dir` 同一把尺）：产品钩子会拿 `account` 去拼
      私有文件路径（zcode 的 `_identity_of`），未清洗的名字在这里就会变成目录穿越
      （§22.2 白名单口径）；合法名字下与传入值逐字一致。
    - `meta.json` 的其余键**优先**照原样铺开（钩子读设备字段 / `expires_at` 等就在这里）；
      文件不存在/损坏 → `load_meta` 返回 `{}`（只读，不改盘）。
    """
    base = Path(root) if root is not None else product_root(product)
    directory = account_dir(base, name)
    merged = dict(load_meta(base, name))     # meta.json 优先（同名普通键以文件为准）
    merged["account"] = directory.name       # 锚字段：写在最后，meta.json 不得覆盖
    merged["dir"] = str(directory)
    return merged


def load_credentials(product: str, name: str, *, root: Path | str | None = None) -> dict:
    """读账号凭据本体（明文，产品私有格式）。

    ⚠️ 未被 `commit_login` 写过的账号（如 zcode 的整根隔离布局）返回空 dict ——
     **不猜格式**；产品私有的取数路径由产品层自己走（§22.3：凭据是产品私有格式）。

    🔴 F3（面板修复轮-2）：读到的明文值顺带**登记进出口脱敏表**
    （`core.errors.register_secret_values`）—— 上游把账号令牌裸回显进错误体时
    （无 `Bearer`/`sk-` 形态可栽），只有字面值匹配能遮住；登记只在内存、不落盘、
    不进日志（§22.2 不变式②：日志/事件里凭据只以短哈希出现）。
    """
    base = Path(root) if root is not None else product_root(product)
    path = account_dir(base, name) / "credentials.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    register_secret_values(_secret_strings(data))
    return data


def read_runtime(product: str, name: str, *, root: Path | str | None = None) -> dict:
    """读运行态快照（§22.2 不变式④：运行态与凭据分离）。

    - 文件不存在 → `{}`（新账号，合法）；
    - 文件存在但**读不动/不是对象** → 抛 `RuntimeUnreadable`（§22.8-5 fail closed：
      不得把"状态文件坏了"当成"状态健康"）。
    """
    base = Path(root) if root is not None else product_root(product)
    path = account_dir(base, name) / "runtime.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RuntimeUnreadable(f"运行态文件读不动：{path}（{e}）") from e
    if not isinstance(data, dict):
        raise RuntimeUnreadable(f"运行态文件不是对象：{path}")
    return data


def write_runtime(product: str, name: str, runtime: dict, *,
                  root: Path | str | None = None) -> None:
    """原子写运行态快照（**只动 `runtime.json`**，不碰凭据/元信息）。

    有意**不取** `_WRITE_LOCK`：它是单文件原子写、不读-改-写别的文件（运行态的
    权威在内存、落盘只是快照，§22.8-5），并发写同一账号只会"后写者胜"，不会丢
    账号资源/元信息；把它并进全局锁反而会让高频运行态写阻塞登录落盘。
    """
    base = Path(root) if root is not None else product_root(product)
    atomic_write_json(account_dir(base, name) / "runtime.json", dict(runtime or {}))


# ---------- 落盘（写回自检 + 失败整体回滚）----------

def commit_login(product: str, name: str, credentials: dict, meta: dict, *,
                 root: Path | str | None = None, via: str = "login") -> str:
    """登录/续期成功后**唯一**的凭据落盘入口（§22.3；写回自检 + 失败整体回滚）。

    - 凭据**明文**落 `credentials.json`（铁律 1）；日志只打短哈希指纹（§22.2 不变式②）；
    - 目录已存在（重登）→ 合并旧 meta（保留设备字段等既有键），逐文件原子覆盖；
      **`runtime.json` 原样保留**（不变式④：运行态不由凭据写入面触碰）；
    - 落盘后逐项读回（照抄 `22 §5.7`）：本次传入的每个**凭据**键、以及**落盘期望内容**
      （`merged`，含 store 管理的 `created_at/updated_at/via`）的每个**元信息**键必须读回一致，
      任一不过 → 回滚（新建 → 删掉整个账号目录；既有 → 写回旧文件）并抛 `CommitError`。
    - 🔴 **整段持跨进程写锁**（§22.8-4）：从"读旧字节做回滚快照"到"写回自检"，
      再到末尾的**资源物化**（`materialize` 的 config 读-改-写）全在同一临界区 ——
      只锁写、不锁读-改-写，两个进程仍会各自基于过期快照覆盖对方（静默丢更新）。
      锁不可用/被占用 → `WriteLockError`（拒写，见 `_AccountsWriteLock`）。
    """
    base = Path(root) if root is not None else product_root(product)
    clean = _require_name(name)
    target = base / clean
    meta_path = target / "meta.json"
    cred_path = target / "credentials.json"

    with _WRITE_LOCK:
        created = not target.exists()
        prev = {p: (p.read_bytes() if p.exists() else None) for p in (meta_path, cred_path)}
        try:
            target.mkdir(parents=True, exist_ok=True)
            merged = {**load_meta(base, clean), **dict(meta or {})}
            now = _now()
            merged.setdefault("created_at", now)
            merged["updated_at"] = now
            merged["via"] = str(merged.get("via") or via)
            atomic_write_json(cred_path, dict(credentials or {}))
            atomic_write_json(meta_path, merged)
            _verify_written(cred_path, meta_path, dict(credentials or {}), merged)
        except BaseException:
            _rollback(target, prev, created)
            raise
        # F3：刚落盘的凭据立刻登记进脱敏表（读取面没走过它也不会被上游回显外泄）
        register_secret_values(_secret_strings(credentials or {}))
        logger.info("凭据已落盘：%s/%s（指纹 %s）", product, clean,
                    cred_fingerprint(_fingerprint_material(credentials)))
        _materialize_best_effort(product, clean)
    return clean


async def commit_login_async(product: str, name: str, credentials: dict, meta: dict, *,
                             root: Path | str | None = None, via: str = "login") -> str:
    """`commit_login` 的**不阻塞事件循环**版本（A-1，面板修复轮-2）。

    🔴 为什么必须存在：`commit_login` 的跨进程写锁等待（`_LOCK_WAIT_S`，持锁者僵死时
    可达 1.0s）与同步 fsync 写盘都发生在**调用线程**里。异步服务路径
    （`POST /admin/api/accounts/login/commit` → `login.LoginEngine.commit_pending`
    → `login._commit_outcome` → 本模块；M7-E 两阶段提交的第二段）直接调同步版时，
    这段等待会把**整个事件循环**停摆 ——
    eng-a 实测打点间隔 **1007ms**（所有并发请求一起被拖住）。
    本函数把整段（等锁 + 写盘 + 写回自检 + 物化）下放工作线程，协程只 await：
    等待发生在工作线程，事件循环照常调度（心跳延迟回到毫秒级）。

    🔴 语义与同步版**逐字一致**（同一个实现换线程跑）：写回自检、失败整体回滚、
    跨进程锁覆盖、`CommitError`/`WriteLockError` 形态全不变；**CLI 同步路径继续用
    `commit_login`**（不强制线程化）。同一线程内重入（`import_account` → `commit_login`）
    在工作线程里照常生效（锁的深度是线程局部）。

    ⚠️ 对接点（报告注明）：`accounts/login.py::_commit_outcome`（经 `commit_pending`）
    与管理端账号写路径（`api/admin_accounts.py` 的 import / refresh / delete）都走
    对应的 `*_async`（本模块提供三条），生产异步路径不直接调同步版。
    """
    return await asyncio.to_thread(commit_login, product, name, credentials, meta,
                                   root=root, via=via)


async def import_account_async(product: str, path: str | None = None, *,
                               payload: dict | None = None, name: str = "",
                               device_id: str = "", reuse: str | None = None,
                               regenerate: bool = False,
                               root: Path | str | None = None) -> ImportResult:
    """`import_account` 的不阻塞事件循环版本（A-1；语义与同步版逐字一致）。"""
    return await asyncio.to_thread(import_account, product, path, payload=payload,
                                   name=name, device_id=device_id, reuse=reuse,
                                   regenerate=regenerate, root=root)


async def delete_account_async(product: str, name: str, *,
                               root: Path | str | None = None) -> bool:
    """`delete_account` 的不阻塞事件循环版本（A-1；语义与同步版逐字一致）。"""
    return await asyncio.to_thread(delete_account, product, name, root=root)


def plan_import_device(root: Path | str, spec: DeviceSpec, incoming: str | tuple[str, ...],
                       *, reuse: str | None = None, regenerate: bool = False) -> DevicePlan:
    """导入路径的设备身份决策（§15.1 三约束的**共用核心**，zcode 与公共层同源）。

    `incoming` = 待复用的身份值：`str`（单字段 / 首字段）或元组（顺序 == `spec.fields`，
    缺失字段用空串）。决策顺序：
    1. 载荷带身份值（**逐字段**）：
       - 任一字段都不与既有账号相同（`check_unique` 保守口径）→
         完整 → **原样复用**（硬约束 2）；缺字段 → 保留已有值、逐字段补生成；
       - 冲突 → `regenerate` 优先于 `reuse`；两者都无 → **拒绝 + 交用户决策**（硬约束 3）；
    2. 完全没有身份值 → 逐字段生成一套新的完整身份（硬约束 1）。
    """
    base = Path(root)
    if not spec.fields:
        # 无设备身份的产品（buddy/workbuddy/cline/loomy，§22.4 设备列 = 无）→ 无冲突可言
        return DevicePlan(ok=True, device_id="", device_values=())
    values = _normalize_incoming(spec, incoming)
    provided = {f: v for f, v in zip(spec.fields, values) if v}
    if provided:
        if check_unique(base, spec, values):
            if len(provided) == len(spec.fields):
                return DevicePlan(ok=True, device_id=values[0], device_values=values)
            generated = generate_identity_values(base, spec, presets=provided)
            return DevicePlan(ok=True, device_id=generated[0], device_values=generated)
        owner = find_account_by_values(base, spec, values)
        if regenerate:
            generated = generate_identity_values(base, spec)
            return DevicePlan(ok=True, device_id=generated[0], device_values=generated)
        if reuse:
            reused = _identity_of(base, spec, reuse)
            if reused is None:
                return DevicePlan(ok=False, message=f"--reuse 目标账号『{reuse}』不存在")
            return DevicePlan(ok=True, device_id=reused[0], device_values=reused)
        return DevicePlan(ok=False, conflict=True, conflict_with=owner or "（未知）",
                          message=f"设备身份冲突（被『{owner or '（未知）'}』占用），未导入")
    generated = generate_identity_values(base, spec)
    return DevicePlan(ok=True, device_id=generated[0], device_values=generated)


def import_account(product: str, path: str | None = None, *, payload: dict | None = None,
                   name: str = "", device_id: str = "", reuse: str | None = None,
                   regenerate: bool = False,
                   root: Path | str | None = None) -> ImportResult:
    """外部凭据导入（§22.3 / `22 §5`；白名单 + 目录穿越防护 + 设备唯一性三约束）。

    - `path` 指向凭据 JSON 或 `payload` 直接给 dict（管理端 `POST /admin/api/accounts/import`）；
    - 🔴 **只读源**：绝不改写 `path` 指向的文件（`23 B4` 的逐字节不变判据）；
    - 载荷形态：`{"credentials": {...}, "meta": {...}}` 或**裸凭据对象**（裸对象按凭据本体收，
      设备字段在顶层或 `meta` 里按 `DeviceSpec.fields` **逐字段**取）；
    - 🔴 身份字段**全量**落 meta.json 并**全字段**查重（任一字段相同即冲突）；
    - 🔴 **查重与落盘同临界区**（§22.8-4 跨进程锁）：先查后写若跨进程交错，
      两个导入会各自通过查重、后写者覆盖先写者（设备身份唯一性被静默破坏）；
    - 落盘复用 `commit_login`（写回自检 + 失败整体回滚，`22 §5.7`；锁可重入）；
    - 锁不可用/被占用 → `ImportResult(ok=False)` + 可读原因（CLI 面不抛栈）。
    """
    from model_gateway.accounts.registry import get as registry_get  # 延迟：import 期不拉起注册表

    base = Path(root) if root is not None else product_root(product)
    spec = registry_get(product).device
    data = payload if isinstance(payload, dict) else _load_payload(path)
    if not isinstance(data, dict):
        return ImportResult(ok=False, message="凭据不可用（路径不存在或不是合法 JSON）")

    clean = sanitize_name(name or str(data.get("name") or "") or _stem(path) or "account")
    incoming = _extract_identity(data, spec)
    if device_id:
        # 显式传入的 `device_id` 覆盖首字段（既有调用方语义），其余字段仍从载荷逐字段抽
        incoming = (device_id.strip(), *incoming[1:])

    try:
        with _WRITE_LOCK:
            if has_account(base, clean) and not (reuse or regenerate):
                return ImportResult(ok=False, account=clean,
                                    message=f"账号『{clean}』已存在（用 --reuse/--regenerate 覆盖）")
            plan = plan_import_device(base, spec, incoming, reuse=reuse, regenerate=regenerate)
            if not plan.ok:
                return ImportResult(ok=False, account=clean, conflict=plan.conflict,
                                    conflict_with=plan.conflict_with, message=plan.message)

            meta = dict(data.get("meta") or {}) if isinstance(data.get("meta"), dict) else {}
            if spec.fields:
                # 🔴 全部身份字段落 meta.json（逐字段；缺字段在 plan 里已补生成）——只写第一个字段
                #    会让该账号身份残缺、后续查重对它视而不见（W2-fix 缺陷根因二）
                for field, value in zip(spec.fields, plan.device_values):
                    meta[field] = value
            meta["via"] = "import"
            # 裸载荷形态：设备字段归 meta.json（§22.2：设备字段住元信息，不进凭据本体）
            skip = {"meta", "name", *_device_keys(spec)}
            credentials = data.get("credentials") if isinstance(data.get("credentials"), dict) else \
                {k: v for k, v in data.items() if k not in skip}
            try:
                commit_login(product, clean, credentials, meta, root=base, via="import")
            except CommitError as e:
                return ImportResult(ok=False, account=clean, message=f"写回自检未通过（已回滚）：{e}")
    except WriteLockError as e:
        # 拒写不是"导入失败在源载荷"——原因原样透出（CLI 打印 message、退出码非 0）
        return ImportResult(ok=False, account=clean, message=str(e))
    return ImportResult(ok=True, account=clean, device_id=plan.device_id,
                        device_values=plan.device_values, message=f"已导入账号 {clean}")


def delete_account(product: str, name: str, *, root: Path | str | None = None) -> bool:
    """删除账号目录（破坏性；调用方需确认）。

    ⚠️ 只删本地账号数据 —— 配置里指向它的资源由调用方按 §22.5-1 处置
    （删除账号 = 其资源置 `enabled=false` **保留**，彻底删除在资源页手动做）。
    🔴 本函数**自动接线**该处置（`materialize.disable_resource`，M6-5a）：删除账号后
    同名资源仍能承接请求会打到"没有凭据的账号"上（fail closed 但白跑 m 次重试），
    所以停用是删除的**后果**而不是可选项；失败只留日志（用户仍可在资源页手动停用）。
    🔴 **整段持跨进程写锁**（§22.8-4）：`rmtree` + 配置停用同临界区 —— 与并发的
    登录/导入交错时，"先删目录、后停用资源"会留下指着空目录的启用资源。
    锁不可用/被占用 → 抛 `WriteLockError`（**不用 `False` 表示拒写**：`False` 的既有
    语义是"账号不存在"，用它会谎报删除结果）。
    """
    base = Path(root) if root is not None else product_root(product)
    target = account_dir(base, name)
    if not target.exists():                      # 快路径：不存在的账号不必抢锁
        return False
    with _WRITE_LOCK:
        if not target.exists():                  # 双检：等锁期间可能已被另一个进程删掉
            return False
        shutil.rmtree(target)
        _disable_materialized(product, str(name or "").strip())
        return True


# ---------- 内部 ----------

def _materialize_best_effort(product: str, name: str) -> None:
    """登录/导入成功后的**尽力而为**物化（§22.5-1；M6-5a 接线）。

    🔴 为什么不让它抛（= 不动 `commit_login` 的既有语义）：本函数的契约是
    "凭据落盘 + 写回自检 + 失败整体回滚"，走到这里凭据**已经写好并验过**；
    物化失败是**配置面**的问题（产品基址未取证 / 配置文件损坏），把它升级成登录失败
    会让用户以为凭据没保存 —— 实际上保存了，重试也不会有不同结果。
    失败原因按可执行文案进日志（`MaterializeError` 自带"为什么 + 怎么办"）。
    """
    try:
        from model_gateway.accounts import materialize  # 延迟：import 期不成环
        materialize.ensure_resource(product, name)
    except Exception as e:  # noqa: BLE001 — 物化失败不得改变"凭据已保存"这一事实
        logger.warning("账号已保存，但资源物化未完成（可稍后重试）：%s/%s：%s",
                       product, name, e)


def _disable_materialized(product: str, name: str) -> None:
    """账号删除后停用其资源（§22.5-1；M6-5a 接线）——失败只留日志。"""
    if not name:
        return
    try:
        from model_gateway.accounts import materialize
        materialize.disable_resource(product, name)
    except Exception as e:  # noqa: BLE001 — 删除已完成；停用失败可在资源页手动补
        logger.warning("账号已删除，但其资源停用未完成（可到资源页手动停用）：%s/%s：%s",
                       product, name, e)


def _require_name(name: str) -> str:
    """新建路径的账号名**严格校验**（不静默改名/截断，防目录穿越）。"""
    clean = sanitize_name(name)
    if not str(name or "").strip() or clean != name:
        raise ValueError(f"账号名必须匹配 [A-Za-z0-9_-]{{1,{_NAME_MAX}}}：{name!r}")
    return clean


def _verify_written(cred_path: Path, meta_path: Path, credentials: dict,
                    expected_meta: dict) -> None:
    """写回自检（照抄 `22 §5.7` verifyWritten 语义）。

    ① 两个文件都必须能读回、且是我们刚写的内容；
    ② **本次传入的**每个凭据键必须原值可见（没传的不查 —— 老格式能过检）；
    ③ **落盘期望元信息**（`expected_meta` = 保留的旧键 + 本次传入 + store 管理的
      `created_at/updated_at/via`）逐键读回一致（设备字段在 meta 里，写不准 = 上游换设备）。
      🔴 比较基准**不是调用方传入的原始 dict**（P-B1，2026-09-30 真机复现）：调用方（如
      enable/disable）会带着上一次读到的**过期** `updated_at` 再来提交，而 store 会把它
      覆写成 now —— 照原值比对会让"隔秒后的任何元信息更新"必 500（同秒内侥幸相等，
      M6-4a 用例因此漏网；Fix-4 在 8399 实例 curl 复现）。
    任一不过 → 抛 `CommitError`，由调用方整体回滚。
    """
    try:
        got_cred = json.loads(cred_path.read_text(encoding="utf-8"))
        got_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise CommitError(f"写回自检读不回：{e}") from e
    if not isinstance(got_cred, dict) or not isinstance(got_meta, dict):
        raise CommitError("写回自检：落盘内容不是对象")
    for key, value in credentials.items():
        if key not in got_cred or got_cred[key] != value:
            raise CommitError(f"写回自检：凭据键 {key!r} 读回不一致")
    for key, value in expected_meta.items():
        if key not in got_meta or got_meta[key] != value:
            raise CommitError(f"写回自检：元信息键 {key!r} 读回不一致")


def _rollback(target: Path, prev: dict[Path, bytes | None], created: bool) -> None:
    """失败整体回滚：新建账号删整个目录；既有账号写回旧字节（§22.3「失败整体回滚」）。

    回滚自身**尽力而为、不再抛**（原始异常必须原样冒出去，回滚失败只留日志）。
    """
    try:
        if created:
            shutil.rmtree(target, ignore_errors=True)
            return
        for path, data in prev.items():
            if data is None:
                path.unlink(missing_ok=True)
            else:
                _write_bytes_atomic(path, data)
    except OSError as e:
        logger.error("账号目录回滚失败（%s：%s）→ 该目录可能残留半成品，请人工检查",
                     target, e)


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    """按字节原子写（回滚用；不解析内容）。"""
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _load_payload(path: str | None) -> dict | None:
    """读导入源（**只读**；允许外包一层 `account` / `data` / `payload`，与参考实现同口径）。"""
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    for outer in ("account", "data", "payload"):
        inner = data.get(outer)
        if isinstance(inner, dict):
            return inner
    return data


def _field_keys(field: str) -> tuple[str, ...]:
    """单个身份字段的候选键：字段名 + camelCase 变体（只此两种，**不猜更多别名**）。"""
    camel = "".join(part.capitalize() if i else part
                    for i, part in enumerate(field.split("_")))
    return (field, camel)


def _device_keys(spec: DeviceSpec) -> tuple[str, ...]:
    """设备字段的全部候选键（字段名 + camelCase 变体）。"""
    keys: list[str] = []
    for field in spec.fields:
        keys.extend(_field_keys(field))
    return tuple(keys)


def _extract_identity(data: dict, spec: DeviceSpec) -> tuple[str, ...]:
    """按 `spec.fields` **逐字段**抽设备身份值（顶层与 `meta` 子对象都看；缺 → 空串）。

    🔴 必须逐字段取，不能"扫全部别名键、取第一个命中"——那会把第二个及以后的字段吞掉
    （W2-fix 缺陷根因的载荷侧同族形态）。返回顺序 == `spec.fields`。
    产品私有的历史别名表（如 zcode 的 `deviceMid`/`mid`）留在产品层，
    不升格成所有产品的契约（§22.1：抽象只做在已证实的共性上）。
    """
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    out: list[str] = []
    for field in spec.fields:
        value = ""
        for key in _field_keys(field):
            for source in (data, meta):
                candidate = source.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    value = candidate.strip()
                    break
            if value:
                break
        out.append(value)
    return tuple(out)


def _normalize_incoming(spec: DeviceSpec, incoming: str | tuple[str, ...]) -> tuple[str, ...]:
    """把 `incoming` 对齐到 `spec.fields`：`str` = 单字段（或首字段）值；缺失字段补 `""`。"""
    raw: tuple[str, ...] = (incoming,) if isinstance(incoming, str) else tuple(incoming or ())
    values = [v.strip() if isinstance(v, str) else "" for v in raw]
    values = values[:len(spec.fields)] + [""] * max(0, len(spec.fields) - len(values))
    return tuple(values)


def _identity_of(root: Path, spec: DeviceSpec, account: str) -> tuple[str, ...] | None:
    """取某账号的**完整**设备身份元组（`--reuse` 用；任一字段缺席 → None）。"""
    from model_gateway.accounts.device import _meta_of, _present_fields  # 同包内部工具（private）

    present = _present_fields(spec, _meta_of(account_dir(root, account)))
    if len(present) != len(spec.fields):
        return None
    return tuple(present[field] for field in spec.fields)


def _fingerprint_material(credentials: dict) -> str:
    """凭据的**稳定指纹素材**（按 key 排序，避免同一内容两种哈希）。"""
    return json.dumps(credentials or {}, ensure_ascii=False, sort_keys=True, default=str)


def _secret_strings(value) -> list[str]:
    """凭据本体里的全部字符串值（F3 脱敏登记用；凭据是扁平 JSON，嵌套也照走）。"""
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(_secret_strings(item))
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            out.extend(_secret_strings(item))
        return out
    return [value] if isinstance(value, str) else []


def _stem(path: str | None) -> str:
    return Path(path).stem if path else ""


def _now() -> str:
    """本地时间戳（秒级 ISO；与 zcode 既有 `_commit` 同口径）。"""
    import datetime as dt

    return dt.datetime.now().isoformat(timespec="seconds")
