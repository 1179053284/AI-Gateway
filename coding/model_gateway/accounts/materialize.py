"""账号 → 资源物化（tech-design v2.0 §22.5-1；M6-5a 波次）。

**唯一职责**：把"某产品某账号已接入"这件事落成配置里的一条 `Resource`
（`product` + `account_ref` + `vendor`/`account` = 展示名/账号名 + `protocol`/`base_url`
= 产品注册表值 + `enabled=true`），写入走**既有配置保存路径**
（`config.loader.save_config`：同目录 tempfile + fsync + `os.replace` 原子替换）——
本模块**不新造写盘通道**（§22.8-4）。

三条纪律（逐条可查）：

1. **幂等**：`ensure_resource()` 重复调用不重复建 —— 判据 = 已存在
   `product == product and account_ref == name` 的资源（**含已停用的**：用户手动停用的
   开关是用户的决定，重新登录不得把它拨回来）。命中即返回其 id，**内容一个字节都不改**
   （只额外前推一次配置 mtime，见下面 ⚠️ 热重载 —— 那是重载信号，不是内容变更）。
2. **不编造**：产品注册表 `base_url` 为空 → **拒建** + 可执行错误（补齐取证再重试），
   绝不猜一个域名；`custom` 协议族落 `"openai"` 仅为 schema 字面量兼容（§22.5-3 裁决，
   真正分派以 `product` 优先）。
3. **删除 = 停用**（§22.5-1）：`disable_resource()` 只把 `enabled` 置 false **保留历史**
   （统计与事件不丢）。🔴 2026-10-02 用户裁决：原句「彻底删除是资源页的手动操作」**作废**
   —— 派生资源已从「接入模型资源」页整体移出（两类接入不得互串），该页看不见它；
   资源位的日常归属改为**账号那颗开关**（`set_resource_enabled`，一个开关一个主人），
   彻底清除 = 直接编辑配置文件 `resources[]`。本模块仍不提供删除口。

⚠️ 热重载：写盘后由 `main.py` 的既有 mtime 轮询（1s）自动重载；本模块**不 import
   `main`**（分层：公共层不得反向依赖装配层）。需要即时生效的调用方可自行
   `runtime.reload_from_file()`。
   🔴 M6-6 Fix-η（B-2 残差）：**命中既有资源**（登录/续期成功，但配置一个字节都没变）
   时也要让网关重算运行态 —— 否则 `src_fp`（含凭据指纹）不刷新，401 判死的资源
   永远不复活，用户按提示"重新登录"却照旧 503。机制 = `_nudge_reload()`：
   只前推配置 mtime、**不改内容**，把信号交给既有热重载协议（跨进程同样成立）。
⚠️ 并发边界（M6-6 Fix-η 更新，原文"跨进程仍可能丢更新"已过期）：登录 / 导入 / 删除
   三条写路径经 `store.commit_login` / `import_account` / `delete_account` 全程持
   **跨进程写锁** `<data>/locks/accounts.lock`（`accounts/store.py::_AccountsWriteLock`），
   本模块的"读配置 → 改 → 写配置"在**同一临界区**内，CLI 与服务端并发登录不再互相覆盖。
   **仍未纳入该锁的两条路径**（正式登记的已知残留，不许当成已覆盖）：
   ① `disable_resource()` 的**直调**（`api/admin_accounts.py::_disable_linked_resources`，
      删账号前的"先停用"一步）；② 管理端 `PUT /admin/api/config`（`api/admin.py` 整份保存）。
   何时会丢：二者与并发的物化写落在同一毫秒窗口（两侧都是"读整份 → 改 → 整份替换"）。
   丢了什么：后写者用自己读到的快照覆盖前写者**刚写入的那一次配置改动**
   （物化的资源行 / 停用位 / 管理端保存的内容，三者之一）。
   为什么可接受：本地单用户网关，两侧都是用户动作（登录 + 手动保存/删除），争用窗口毫秒级；
   丢失无歧义、可重做（重登会重新物化，保存/停用本身幂等），且不产生"账号目录没了、
   资源还指着它"的半成品（停用早于删目录、`delete_account` 内部持锁后会再停用一次）。
   收口代价：需要在 `api/admin.py` 与 `store.py` 的公开锁入口上动手 —— 二者在本波次
   独占文件集之外，故登记为残留契约项而非悬空。
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from pathlib import Path

from model_gateway.accounts.net import cred_fingerprint
from model_gateway.accounts.registry import get as registry_get
from model_gateway.accounts.store import load_credentials, sanitize_name
from model_gateway.config.loader import ConfigError, load_config, save_config
from model_gateway.config.schemas import AppConfig, Resource
from model_gateway.core import paths

logger = logging.getLogger("model_gateway.accounts")

#: 进程内串行化"读配置 → 改 → 写配置"（跨进程情形见模块头 ⚠️）
_ORDER_LOCK = threading.Lock()


class MaterializeError(RuntimeError):
    """物化被拒（消息必须**可执行**：为什么不建 + 下一步怎么办）。"""


def ensure_resource(product: str, name: str, *, config_path: Path | str | None = None) -> str:
    """物化（或复用）一条产品资源，返回资源 id —— 幂等（§22.5-1）。

    - 已存在同 `(product, account_ref)` 的资源 → 原样返回其 id（含已停用的，不复活开关）；
      额外前推一次配置 mtime（`_nudge_reload`）：内容不变，但让网关进程按**当前**凭据
      重算运行态（B-2：重登 / 续期成功 → 401 判死的资源复活，用户无需额外操作）；
    - 不存在 → 追加一条并**经既有保存路径**落盘（原子写；热重载由装配侧承接）；
    - 产品未登记 / 注册表 `base_url` 为空 / 配置读不动 → `MaterializeError`（拒建，不编造）。
    """
    prod = str(product or "").strip()
    if not prod:
        raise MaterializeError("ensure_resource: product 不能为空（产品 id，见 accounts/registry.py）")
    account = _require_name(name)
    meta = _product_meta(prod)
    base_url = (meta.base_url or "").strip()
    if not base_url:
        raise MaterializeError(
            f"产品 {prod!r} 未登记上游基址（`accounts/registry.py` 该实例 base_url 为空）"
            "—— 拒绝物化：基址无法从凭据或账号目录推导，编造一个只会让请求打到错误域名。"
            "请先补齐该产品的取证回填后重试；本次登录的凭据已保存在账号目录，可随时重试")
    path = paths.resolve_config_path(config_path)
    with _ORDER_LOCK:
        config = _load_or_fail(path, prod)
        found = _find(config, prod, account)
        if found is not None:
            # 🔴 B-2 残差（M6-6 Fix-η）：凭据可能刚被重登/续期换过，而配置一个字节都没变
            #    —— 必须让网关重算运行态（`rebuild` 重读凭据指纹），否则 401 判死的资源
            #    不复活。信号走既有 mtime 热重载协议，不新增 watcher / 端点 / 进程内耦合。
            _nudge_reload(path)
            return found.id
        rid = _new_id({r.id for r in config.resources})
        config.resources.append(Resource(
            id=rid,
            product=prod,
            account_ref=account,
            vendor=meta.title,          # 产品显示名（§22.5-1）
            account=account,            # 账号名（§22.5-1；与 account_ref 同值，事件/统计口径）
            protocol=_schema_protocol(meta.protocol),
            base_url=base_url,
            api_key="",                 # 凭据在账号目录，不进配置（铁律 1 / §22.3）
            enabled=True,
        ))
        _save(config, path)
        logger.info("账号已物化为资源：%s/%s → %s（%s）", prod, account, rid, base_url)
        return rid


def disable_resource(product: str, name: str, *, config_path: Path | str | None = None) -> bool:
    """账号删除/停用 → 其资源置 `enabled=false` **保留**（§22.5-1），返回是否有改动。

    幂等：资源不存在或已停用 → `False`（不写盘）。**不校验产品是否在册**——
    停用是"关掉一条既有配置"，未登记产品（如注册表已改名）的资源也必须能被关掉。
    """
    prod = str(product or "").strip()
    account = str(name or "").strip()
    if not prod or not account:
        return False
    path = paths.resolve_config_path(config_path)
    with _ORDER_LOCK:
        config = _load_or_fail(path, prod)
        changed = 0
        for r in config.resources:
            if (r.product or "").strip() == prod \
                    and (r.account_ref or "").strip() == account and r.enabled:
                r.enabled = False
                changed += 1
        if not changed:
            return False
        _save(config, path)
        logger.info("账号已删除/停用，其 %d 条资源置为停用（保留历史）：%s/%s",
                    changed, prod, account)
        return True


def set_resource_enabled(product: str, name: str, enabled: bool,
                         *, config_path: Path | str | None = None) -> int:
    """账号启用/停用 ⇒ 其派生资源的 `enabled` 位**同步跟上**，返回改动条数（0 = 本就一致）。

    🔴 为什么需要这一条（2026-10-02 用户裁决，两类资源分流暴露的缺陷）：
    分流后派生资源**不再出现在**「接入模型资源」页，而账号页那颗开关原先只写账号 meta
    （§22.6 的运营跳过位）—— 于是资源级启用位变成**没有任何主人的隐藏开关**：
    账号被删时我们把它置 false（`disable_resource`），用户后来重新启用账号，
    资源却仍 false ⇒ 永久不可服务且界面上看不见（`ensure_resource` 按纪律 1 也**不**拨回）。
    定版 = **一个开关一个主人**：账号开关同时驱动其资源位。

    与纪律 1 不冲突：纪律 1 说的是「**登录/续期**不得拨回用户手动停用的开关」，
    那条路径本函数不参与；这里只在**用户显式启停账号**时同步。
    """
    prod = str(product or "").strip()
    account = str(name or "").strip()
    if not prod or not account:
        return 0
    path = paths.resolve_config_path(config_path)
    with _ORDER_LOCK:
        config = _load_or_fail(path, prod)
        changed = 0
        for r in config.resources:
            if (r.product or "").strip() != prod:
                continue
            ref = (r.account_ref or "").strip() or (r.account or "").strip()
            if ref == account and bool(r.enabled) != bool(enabled):
                r.enabled = bool(enabled)
                changed += 1
        if not changed:
            return 0
        _save(config, path)
        logger.info("账号 %s/%s %s，其 %d 条派生资源的启用位同步为 %s",
                    prod, account, "启用" if enabled else "停用", changed,
                    "启用" if enabled else "停用")
        return changed


def credential_fingerprint(product: str, name: str, *, root: Path | str | None = None) -> str:
    """账号凭据的**短哈希指纹**（适配器复用判据用；非明文，§22.2 不变式②）。

    读不到凭据（未登录 / 文件缺失）→ 空串（"无凭据"本身也是一种可比较的连接身份）。
    序列化口径与 `store.commit_login` 的日志指纹**同源**（排序、`default=str`），
    否则同一份凭据会出现两个指纹，"改绑账号"判据随之两处打架。
    """
    cred = load_credentials(product, name, root=root)
    if not cred:
        return ""
    material = json.dumps(cred, ensure_ascii=False, sort_keys=True, default=str)
    return cred_fingerprint(material)


# ---------- 内部 ----------

def _require_name(name: str) -> str:
    """账号名按 §22.2 白名单**严格**校验（不静默改名/截断 —— 名字是资源的连接身份）。"""
    clean = str(name or "").strip()
    if not clean or sanitize_name(clean) != clean:
        raise MaterializeError(
            f"账号名不合法：{name!r}（必须匹配 [A-Za-z0-9_-]{{1,32}}，§22.2 防目录穿越）")
    return clean


def _product_meta(product: str):
    """产品注册信息（未登记 → 可执行错误，不静默降级，§22.6「未登记 = 不支持」）。"""
    try:
        return registry_get(product)
    except KeyError as e:
        raise MaterializeError(f"{e} —— 无法物化资源") from e


def _schema_protocol(protocol: str) -> str:
    """注册表协议族 → `Resource.protocol` schema 字面量（§22.5-3 裁决）。

    `custom`（qoder/qodercn/trae）落 `"openai"` **仅为字面量兼容**：真正分派以
    `product` 优先（`adapters.build_adapter` 的 product 分支），不是"这个产品说 openai"。
    """
    return "openai" if protocol == "custom" else protocol


def _load_or_fail(path: Path, product: str) -> AppConfig:
    """读当前配置（**磁盘为准**：热重载的权威是文件，不是任何进程内快照）。

    读不动 → 拒建（`MaterializeError`）：配置坏了还写回去，等于用一份"缺了很多资源"的
    快照覆盖用户的配置 —— 那是数据丢失，不是物化失败。
    """
    try:
        return load_config(path)
    except ConfigError as e:
        raise MaterializeError(
            f"{product} 物化被拒：配置校验失败（不覆盖坏配置）：{'；'.join(e.errors)}") from e


def _find(config: AppConfig, product: str, account: str) -> Resource | None:
    """按 `(product, account_ref)` 找既有资源（幂等判据）。"""
    for r in config.resources:
        if (r.product or "").strip() == product \
                and (r.account_ref or "").strip() == account:
            return r
    return None


def _new_id(taken: set[str]) -> str:
    """资源 id（`res-` + 8 hex，与 `api/admin.py::_autogen_ids` 同一形态）。"""
    while True:
        rid = "res-" + secrets.token_hex(4)
        if rid not in taken:
            return rid


def _nudge_reload(path: Path) -> None:
    """把配置文件的 mtime 前推一次 —— 既有热重载轮询（`main.py::_reload_watcher`，1s）据此重算运行态。

    🔴 B-2 残差（M6-6 Fix-η）：重登 / 续期成功后凭据已在账号目录里换了，但配置**一个字节
    都没变**（资源行命中幂等）→ mtime 不变 → 网关不 `rebuild` → `src_fp`（含凭据指纹）
    不刷新 → 401 判死的资源（终态 `disabled`）不复活，用户按提示"重新登录"仍永远 503。

    🔴 为什么是"前推 mtime"而不是"内容变更写入"：
    - 配置的 mtime 就是既有热重载协议的**唯一输入**（`_reload_watcher` 只 stat 它），
      信号不需要改内容就成立；
    - 重写内容（即便字节相同）会重排 YAML 格式、**剥掉用户写的注释** —— 一次登录
      不该有这种副作用；`os.utime` 一个字节都不写，模块头"判据 1"（幂等 = 不改内容）
      字面成立；
    - 跨进程同样成立：CLI 登录（`mgw … login`）也会前推，网关进程照样看得见 ——
      不 import 装配层、不新增端点、不新增 watcher。

    失败只留日志（拿不到信号不得影响"凭据已保存"这一事实）；文件不存在 = 没有可重算的配置。
    """
    try:
        if path.exists():
            os.utime(path)
    except OSError as e:
        logger.warning("配置 mtime 前推失败（登录已成功，但网关可能不会立即重算运行态）："
                       "%s：%s", path, e)


def _save(config: AppConfig, path: Path) -> None:
    """经**既有**保存路径落盘（`config.loader.save_config`；原子写，中断不留半截文件）。"""
    save_config(config, path)
