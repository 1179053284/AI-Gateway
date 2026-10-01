"""`ClaimOutcome → OpResult` 的**唯一桥接**（A-2，M6 面板修复轮-2；A-5 双账收敛）。

🔴 为什么单独立文件：本桥接原先有**两处实现**（eng-a A-5 点名的双账风险）——

- `ops/builtin/product_claim.py`（多产品 claim 执行体）：非 `failed` 归 `retryable=None`；
- `api/admin_accounts.py::_claim_once`（管理端单账号领取）：`retryable` **原样透传**。

同一份 `ClaimOutcome` 在两处产出**不同**的 `OpResult.retryable`（如 `already_done`
+ `retryable=True`：一处是 `None`、一处是 `True`）。行为上暂未暴露——`retryable` 只
在 `failed` 时被 `runner._retryable_of` 读——但"同一条归一化规则只住在一处"是硬要求
（规则两份 = 下一处改一漏一即分叉）。本模块是该规则的**唯一**落点：

| 输入 | 输出 |
|---|---|
| `ClaimOutcome`（四类之一） | `OpResult(account, outcome.category, outcome.detail)` |
| `category == "failed"` | `retryable = bool(outcome.retryable)`（钩子的结构化表态） |
| 其余三类（success/already_done/inactive） | `retryable = None`（**归 None**，不把"非失败"伪装成可重试声明） |
| 非 `ClaimOutcome`（钩子返回垃圾） | `failed` + 可读原因（**不把非结果对象当成功**） |

消费方（两处，都必须改调这里）：
`ops/builtin/product_claim.py::claim` 与 `api/admin_accounts.py::_claim_once`
（`api/` 侧由 M6 面板修复-1 对接，见交付报告"对接点"）。
"""

from __future__ import annotations

from model_gateway.accounts.types import ClaimOutcome
from model_gateway.ops.base import OpResult


def outcome_to_op_result(outcome: ClaimOutcome, account: str) -> OpResult:
    """`ClaimOutcome` → `OpResult`（**唯一归一化规则**，见模块头表）。

    形参 `outcome` 声明为 `ClaimOutcome`，但本函数**是总的**（total）：钩子可能返回
    任何对象，非 `ClaimOutcome` 一律 `failed`（可读原因带上真实类型名）——两条调用
    路径原先各自带一份同样的类型守卫文案，收敛后它们不再需要各写一份。
    """
    if not isinstance(outcome, ClaimOutcome):
        return OpResult(account, "failed",
                        f"claim 钩子返回值类型异常：{type(outcome).__name__}"
                        "（不把非结果对象当成功）")
    return OpResult(account, outcome.category, outcome.detail,
                    retryable=(bool(outcome.retryable)
                               if outcome.category == "failed" else None))
