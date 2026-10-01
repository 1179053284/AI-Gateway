"""`claim` 多产品签到/领取 operation（tech-design v2.0 §22.6；R4-BL-3 收敛落地）。

§22.6 的收敛结论：operation 命名收敛为 `claim` / `query_balance`（**按
`supported_products` 匹配**）；`zcode_claim` 保留为向后兼容别名
（`mgw zcode claim` 的 CLI 契约与退出码 Q28-⑧ 不动，见 `ops/builtin/__init__.py`）。

本执行体的四条纪律（逐条可查）：

| 纪律 | 落地 |
|---|---|
| **参与方从能力矩阵推导** | `SUPPORTED_PRODUCTS` = 注册表里 `Capabilities.checkin=True` 的产品（含 zcode）—— 不硬编码任何渠道字面量；`workbuddy` / `cline` / `raccoon` 天然不在内 |
| 每产品执行体 | `accounts.store.hook_meta` 组 meta → 产品 `claim` 钩子（按 `_HOOKS` 契约表取名，缺项当场失败） |
| `precheck` per-product | 唯一表 = `accounts/registry.py::PRE_CHECK_PRODUCTS`（trae 必须 True，§22.6 / `20 B6`）；本模块与 `api/admin_accounts.py` 引用**同一对象**（Fix-ζ 收敛，防两份分叉） |
| 结果出口 | 钩子 `ClaimOutcome` → `ops/base.py` 四类 **1:1**，不另立语义、不另写出口；桥接本体 = `ops/bridge.py::outcome_to_op_result`（**唯一归一化规则**，A-2：管理端 `_claim_once` 改调同一函数） |

**结构化重试**（R1-F2）：网络/5xx 类失败由执行体显式声明 `OpResult.retryable=True`
（产品钩子经 `ClaimOutcome.retryable` 表态；钩子让传输类异常逃出来时由本层按异常类判定），
业务码/凭据类失败 `False` → 批量执行器**看字段，不看文案**。

**zcode 直连分支**（唯一产品私有分支，理由是可查的签名事实）：§22.3 冻结的 `claim`
钩子签名 `(cred, meta, *, precheck)` 装不下 `manual`（无住宅代理时人工过验证码）
与 `runtime`（3012 风控 → 熔断回写资源态，§17）—— 两者都是既有 CLI / 运营契约，
所以 zcode 走既有执行器 `ops/builtin/zcode_claim.claim`。等价性两处钉死：
`tests/unit/test_ops_claim_multi.py::test_zcode_claim_alias_...`（别名条目 `run` = 本模块
`claim`，对 zcode 账号正是走到这个直连分支）+ 真实 CLI 实测（`mgw zcode claim`）。
"""

from __future__ import annotations

from typing import Awaitable, Callable

from model_gateway.accounts import registry as account_registry
from model_gateway.accounts import store as accounts_store
from model_gateway.accounts.types import ClaimOutcome
from model_gateway.ops import bridge
from model_gateway.ops import runner as ops_runner
from model_gateway.ops.base import OpResult
from model_gateway.ops.builtin import product_hooks, zcode_claim

#: 注册 id（与 `ops/builtin/__init__.py` 的 OPERATIONS 键一致）
OPERATION_ID = "claim"


def _products_with(capability: str) -> tuple[str, ...]:
    """按能力位筛产品（**从注册表推导**，顺序 = `PRODUCT_IDS` 的 UI 顺序）。

    能力位是判据不是标签（§22.6）：`checkin=False` 的产品（workbuddy / cline / raccoon）
    没有可调用的签到端点，声明进来只会得到"点了必然失败"的请求。
    """
    return tuple(pid for pid in account_registry.PRODUCT_IDS
                 if getattr(account_registry.get(pid).capabilities, capability))


#: 该 operation 支持的产品（§16.4 per-operation 声明；`run_once` 按它过滤参与方）
SUPPORTED_PRODUCTS: tuple[str, ...] = _products_with("checkin")

#: 本动作的参与方能力位 → 执行钩子名（钩子名同样**从能力矩阵推导**，不写死产品名）。
#: `onboarding`（一次性新手任务）是**另一个**能力位、另一套端点，不属本动作的参与矩阵
#: —— 在这里"顺手也跑一下"就是 §22.6 明令禁止的误跑。
_CLAIM_HOOK_NAME = "claim"

#: 领取前预检的 per-product 声明（§22.6「`precheck` per-product 显式声明」/ `20 B6`）。
#: `trae` **必须** True：其 claim 对已签到同样回成功，幂等**只能**靠 status 端点判
#: （`20 §3.1`）。缺省 False = 不预检（各产品钩子自带幂等判据）。
#: 🔴 **单一事实源 = `accounts/registry.py::PRE_CHECK_PRODUCTS`**（Fix-ζ 收敛：产品事实与
#: 能力位同家）。本名是对**同一对象**的引用（消费点与既有判据沿用），不是第二份表 ——
#: 原先本模块与 `api/admin_accounts.py` 各持一份字面量、靠测试钉相等，两处改一漏一即分叉。
_PRECHECK: dict[str, bool] = account_registry.PRE_CHECK_PRODUCTS

#: 直连执行体（不经产品钩子）—— **只登记签名装不下的产品**（见模块头"zcode 直连分支"）：
#: zcode 的冻结钩子签名装不下 `manual` / `runtime`，而两者都是既有 CLI / 运营契约，
#: 所以它直连既有执行器 `zcode_claim.claim`。
#: 🔴 这是**执行体接线**，不是参与方选择（参与方一律由上面的能力矩阵推导）。
_CLAIM_DIRECT: dict[str, Callable[..., Awaitable[OpResult]]] = {
    "zcode": zcode_claim.claim,
}


def _claim_hook_name(product: str) -> str | None:
    """该产品的执行钩子名；`None` = 未登记本动作所需能力（不参与、不误跑）。

    未登记产品（注册表 `KeyError`）由调用方隔离成 `failed`（不静默降级，§22.6）。
    """
    if not account_registry.get(product).capabilities.checkin:
        return None
    return _CLAIM_HOOK_NAME


async def claim(account: str, *, manual: bool = False, runtime=None) -> OpResult:
    """对单个账号执行一次签到/领取（`run_once` 的 `ClaimFn` 约定）。

    - 账号归属产品经注册表推导（`ops.runner.product_of_account`）：认不出 → `failed` +
      可读原因（不静默、不拿别的产品接口误跑）；
    - zcode → 既有直连执行器（`manual` 人工验证码 + `runtime` 熔断回写，Q28-⑧ / §17）；
    - 其余产品 → "`hook_meta` + 产品钩子"通用体（`manual` 对它们无意义，静默保留形参）；
    - 失败的重试性**结构化声明**（`ClaimOutcome.retryable` / 传输类异常），见模块头。
    """
    product = ops_runner.product_of_account(account)
    if not product:
        return OpResult(account, "failed",
                        "认不出账号归属的产品（账号目录缺失或不在册），未发起领取")
    direct = _CLAIM_DIRECT.get(product)
    if direct is not None:
        return await direct(account, manual=manual, runtime=runtime)

    try:
        hook_name = _claim_hook_name(product)
    except KeyError as e:                    # 未登记产品（注册表显式失败）
        return OpResult(account, "failed",
                        str(e.args[0]) if e.args else f"未登记的产品 {product!r}")
    if hook_name is None:
        return OpResult(account, "inactive",
                        f"{product} 未登记签到能力（能力位 checkin=False），本动作不参与"
                        "（不误跑：它没有可调用的签到端点）")

    # 凭据解析**在 try 内**（§22.8-6 失败隔离：单账号异常不中断批量）
    try:
        cred = accounts_store.load_credentials(product, account)
        hook_meta = accounts_store.hook_meta(product, account)      # §22.3 补入① 唯一组装入口
        hook = product_hooks.hook_of(product, hook_name)
        outcome = await hook(cred, hook_meta,
                             precheck=bool(_PRECHECK.get(product, False)))
    except Exception as e:  # noqa: BLE001 — 单账号失败隔离，不抛给批量执行器
        return OpResult(account, "failed", f"{type(e).__name__}: {e}",
                        retryable=product_hooks.is_transport_failure(e))

    if not isinstance(outcome, ClaimOutcome):
        return OpResult(account, "failed",
                        f"{hook_name} 钩子返回值类型异常：{type(outcome).__name__}"
                        "（不把非结果对象当成功）")
    # 🔴 A-2（面板修复轮-2）：归一化规则**只住一处**（`ops/bridge.py`；原先本模块与
    #    `api/admin_accounts.py::_claim_once` 各写一份 → 双账，eng-a A-5。
    #    本行保留上面的类型守卫只为把钩子名带进文案（类型守卫文案带钩子名更可读）；
    #    桥接本体对非 ClaimOutcome 同样是"failed + 类型名"的总函数。
    return bridge.outcome_to_op_result(outcome, account)
