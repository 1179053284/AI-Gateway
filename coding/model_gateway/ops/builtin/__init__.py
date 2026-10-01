"""运营动作注册表（§22.6 收敛后三条：`claim` / `query_balance` / `zcode_claim` 兼容别名）。

🔴 §22.6 的命名收敛结论（原 §16.6"首批 2 个"由本条supersede）：

- `claim` / `query_balance` = **多产品动作**：参与方按各自的 `supported_products`
  匹配（能力矩阵是判据不是标签），并由 `ops/runner.py::run_once` 按它**枚举账号**
  （新产品的账号因此真的进得来，而不只是"机制在"）；
- `zcode_claim` = **向后兼容别名**：语义 = "多产品 `claim` 收窄到 zcode"，
  id / 声明 / 退出码契约（Q28-⑧ 与 `mgw zcode claim`）逐字不变；
  其 `run` 与多产品 `claim` 动作给 zcode 用的执行器是**同一个函数对象**
  （`product_claim._CLAIM_DIRECT["zcode"]`，见该模块"zcode 直连分支"），
  因此 `--manual`（人工验证码）与 `runtime`（§17 熔断回写）语义原样保留。

新增产品动作 = 在这里挂一条 `AccountOperation`，**并声明它支持哪些产品**；
未声明的产品账号会被批量执行器跳过（§16.4）。
"""

from model_gateway.ops.base import AccountOperation
from model_gateway.ops.builtin import product_claim, query_balance, zcode_claim

OPERATIONS: dict[str, AccountOperation] = {
    # —— 多产品签到 / 领取（§22.6 收敛后的正名；参与方 = 所有 checkin=True 的产品）——
    product_claim.OPERATION_ID: AccountOperation(
        id=product_claim.OPERATION_ID,
        title="签到 / 领取（多产品）",
        supported_products=product_claim.SUPPORTED_PRODUCTS,
        run=product_claim.claim,
    ),
    # —— 向后兼容别名（§22.6 / Q28-⑧）：CLI `mgw zcode claim` 与网关 cron 按这个 id 取动作 ——
    zcode_claim.OPERATION_ID: AccountOperation(
        id=zcode_claim.OPERATION_ID,
        title="ZCode 每日领取 / 签到",
        supported_products=zcode_claim.SUPPORTED_PRODUCTS,
        run=product_claim.claim,      # 🔴 与多产品 claim 同一执行体，靠声明收窄到 zcode
    ),
    query_balance.OPERATION_ID: AccountOperation(
        id=query_balance.OPERATION_ID,
        title="额度 / 余额查询（多产品）",
        supported_products=query_balance.SUPPORTED_PRODUCTS,
        run=query_balance.query_balance,
    ),
}
