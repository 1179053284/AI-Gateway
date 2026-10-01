"""`query_balance` 运营操作（tech-design v2.0 §16.6 / §22.6；R1-F6 接线）。

§16.6 边界一句话：**`upstream/` 负责"怎么调上游"，`ops/` 负责"什么时候调、怎么批量、
结果怎么归类"** → 本模块只做薄适配器，**不自己发请求**。

两条执行通道（都是产品的可查事实，不是偏好）：

| 通道 | 覆盖 | 为什么 |
|---|---|---|
| 离线日志通道（既有实现） | zcode | 余量是**数值**（写共享额度池，§17 / M5-3）；其 `quota` 钩子只出三态、不带数量，走通用体反而把数值丢了 |
| 产品 `quota` 钩子（本轮接线，F6） | 其余 9 个在册产品 | §22.5-6：余额快照由 ops tick **后台**刷新后 `set_quota`（**选路只读**，不照抄请求期网络查余额）；结果同时缓存进账号 `runtime.json`（`store.write_runtime`） |

四类结果的映射（§16.2）：

| 情形 | 类别 | 为什么 |
|---|---|---|
| 额度已取回（available / exhausted） | `success` | 查询本身正常完成；"耗尽"信号以**两处**透出：额度池写 0 + 缓存三态 |
| 未能取到（`unknown`；zcode 无可用快照） | `inactive` | 🔴 **正常业务态，不是失败** —— 判 `failed` 会让红点每轮常亮，稀释真正需要关注的失败（§21.3 原则 3）；**未知不当零**：缓存原样落 `unknown`，额度池一个字节都不动 |
| 读取 / 落盘过程抛异常 | `failed` | 真出错（权限/磁盘/解析），需要用户看 —— **落盘失败也进这一类**（不谎报成功） |

参与方 = 所有 `Capabilities.balance=True` 的产品（**从注册表推导**；在册 10 个全 ✓，含 zcode）。
"""

from __future__ import annotations

import datetime as dt
import logging

from model_gateway.accounts import registry as account_registry
from model_gateway.accounts import store as accounts_store
from model_gateway.accounts.types import QuotaSnapshot
from model_gateway.ops import runner as ops_runner
from model_gateway.ops.base import OpResult
from model_gateway.ops.builtin import product_hooks

logger = logging.getLogger("model_gateway.ops")

#: 注册 id（与 `ops/builtin/__init__.py` 的 OPERATIONS 键一致）
OPERATION_ID = "query_balance"

#: 该 operation 支持的产品（§16.4 per-operation 声明；**从能力矩阵推导**，不硬编码产品名）
SUPPORTED_PRODUCTS: tuple[str, ...] = tuple(
    pid for pid in account_registry.PRODUCT_IDS
    if account_registry.get(pid).capabilities.balance)


async def _query_zcode(account: str, *, runtime=None) -> OpResult:
    """zcode 的离线日志通道（既有实现，语义逐字保留；只走客户端日志，§17 数据源优先级）。"""
    from model_gateway.upstream.zcode import quota as zq
    from model_gateway.upstream.zcode import store

    try:
        snap = zq.read_account_snapshot(store.accounts_root(), account)
    except Exception as e:  # noqa: BLE001 — 单账号异常隔离，不中断批量
        return OpResult(account, "failed", f"{type(e).__name__}: {e}")

    if not snap.ok or not snap.buckets:
        return OpResult(account, "inactive",
                        f"{snap.note or '暂无额度记录'}"
                        f"（客户端未运行过，或账号目录不匹配）")

    remaining = zq.remaining_units(snap)
    used_total = sum(b.used for b in snap.buckets)
    all_total = sum(b.total for b in snap.buckets)
    zq.apply_snapshot_to_runtime(runtime, account, snap)
    detail = (f"{snap.plan or '额度'} 已用 {used_total}/{all_total}，余 {remaining}"
              f"（{' / '.join(f'{b.show_name}:{b.reset_note}' for b in snap.buckets[:3])}）")
    return OpResult(account, "success", detail)


#: 产品私有离线通道（直连；见模块头两通道表）。
#: 🔴 这是**执行体接线**，不是参与方选择（参与方一律由上面的能力矩阵推导）。
_BALANCE_DIRECT = {"zcode": _query_zcode}


async def _query_via_hook(product: str, account: str, runtime) -> OpResult:
    """通用体（F6 接线）：`hook_meta` → 产品 `quota` 钩子 → 三态缓存 + 已物化资源 `set_quota`。"""
    # 凭据解析**在 try 内**（§22.8-6 失败隔离：单账号异常不中断批量）
    try:
        cred = accounts_store.load_credentials(product, account)
        hook_meta = accounts_store.hook_meta(product, account)      # §22.3 补入① 唯一组装入口
        hook = product_hooks.hook_of(product, "quota")
        snap = await hook(cred, hook_meta)
    except Exception as e:  # noqa: BLE001 — 单账号失败隔离，不抛给批量执行器
        return OpResult(account, "failed", f"{type(e).__name__}: {e}",
                        retryable=product_hooks.is_transport_failure(e))

    if not isinstance(snap, QuotaSnapshot):
        return OpResult(account, "failed",
                        f"quota 钩子返回值类型异常：{type(snap).__name__}（不把非快照当额度）")

    cache_error = _write_quota_cache(product, account, snap)
    updated = _apply_quota_to_pools(product, account, snap, runtime)
    tail = f"；已刷新 {updated} 个资源额度池" if updated else ""
    if cache_error:
        # 查询到手但**状态没落盘** → 记 failed 且原因可读（§22.8-5 / S-26④：落盘失败必须留痕）
        return OpResult(account, "failed",
                        f"额度已取回但运行态缓存写入失败（{cache_error}）；"
                        f"{snap.state}：{snap.detail or '无详情'}")
    if snap.state == "unknown":
        # 未知不当零（§22.3）：缓存原样落 unknown、额度池不动；类别取 inactive（正常业务态）
        return OpResult(account, "inactive",
                        f"未能取到额度（未知不当零）：{snap.detail or '无详情'}"
                        f"（来源 {snap.source or '未知'}）")
    label = "额度已耗尽" if snap.state == "exhausted" else "额度可用"
    return OpResult(account, "success",
                    f"{label}：{snap.detail or '无详情'}（来源 {snap.source or '未知'}）{tail}")


def _write_quota_cache(product: str, account: str, snap: QuotaSnapshot) -> str:
    """把三态快照写进账号 `runtime.json`（§22.2 布局 / §22.5-6「后台刷新落盘快照」）。

    返回错误原因（`""` = 成功）：
    - **读-改-写**：只动 `quota` 一个键，冷却 / 最近错误 / 水印等既有键原样保留
      （§22.2 不变式④：运行态与凭据分离，且一个写者不得洗掉别家的键）；
    - 文件**读不动**（`RuntimeUnreadable`）→ 直接报错、**不覆盖**（§22.8-5 fail closed：
      不得把"状态文件坏了"当健康，也不得把用户的运行态洗成一份只有额度的文件）。
    """
    try:
        current = accounts_store.read_runtime(product, account)
    except Exception as e:  # noqa: BLE001 — 读不动 = 拒写（fail closed），原因交给用户
        return f"{type(e).__name__}: {e}"
    current["quota"] = {
        "state": snap.state,
        "source": snap.source,
        "detail": snap.detail,
        "checked_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    try:
        accounts_store.write_runtime(product, account, current)
    except Exception as e:  # noqa: BLE001 — 落盘失败必须留痕（不谎报成功）
        return f"{type(e).__name__}: {e}"
    return ""


def _apply_quota_to_pools(product: str, account: str, snap: QuotaSnapshot, runtime) -> int:
    """把三态写进**该账号已物化资源**的共享额度池（§22.5-6：后台刷新、选路只读）。

    三态口径（**未知不当零**，§22.3）：

    - `available` → `None`（回到"未知/不限"：三态只说"有余量"，没有数量可写，
      不做额度管控；同时把上一轮"耗尽"写下的 0 清掉 —— 否则充值成功后资源会被旧 0
      **永久**挡住）；
    - `exhausted` → `0`（确定耗尽 → 预留闸门拦截），不编造数量；
    - `unknown` → **一个字节都不动**（fail closed：不把未知洗成 0，也不把已知的 0 洗成不限）。
    """
    if runtime is None or snap.state == "unknown":
        return 0
    manager = getattr(runtime, "resources", None)
    config = getattr(runtime, "config", None)
    if manager is None or config is None:
        return 0
    remaining = 0 if snap.state == "exhausted" else None
    updated = 0
    for res in getattr(config, "resources", None) or []:
        if str(getattr(res, "product", "") or "") != product:
            continue
        # 物化资源写 product + account_ref（M6-5）；`account` 是旧口径的备注列，作回退
        ref = str(getattr(res, "account_ref", "") or "") or str(getattr(res, "account", "") or "")
        if ref and ref != account:
            continue
        try:
            if manager.set_quota(res.id, remaining):
                updated += 1
        except Exception as e:  # noqa: BLE001 — 单个资源写失败不中断（失败隔离，§22.8-6）
            logger.warning("额度池写入失败（%s/%s → %s）：%s", product, account, res.id, e)
    return updated


async def query_balance(account: str, *, manual: bool = False, runtime=None) -> OpResult:
    """查一次该账号的额度/余额（`run_once` 的 `ClaimFn` 约定；`manual` 对本动作无意义）。

    账号归属产品经注册表推导：认不出 → `failed` + 可读原因（不静默、不拿别的产品接口误跑）。
    """
    del manual  # 形参按 ops 的 ClaimFn 约定保留（额度查询无人工路径）
    product = ops_runner.product_of_account(account)
    if not product:
        return OpResult(account, "failed",
                        "认不出账号归属的产品（账号目录缺失或不在册），未查询额度")
    direct = _BALANCE_DIRECT.get(product)
    if direct is not None:
        return await direct(account, runtime=runtime)
    return await _query_via_hook(product, account, runtime)
