"""多产品账号公共层（tech-design v2.0 §22 / PRD Q29）。

分层（§22.1）::

    入口层   /admin/api/accounts* · web 静态页 · mgw 子命令
    公共层   model_gateway/accounts/     ← 本包（**最小公共层**）
    产品层   model_gateway/upstream/<product>/product.py（§22.3 钩子）
    转接层   adapters/ 的产品分支 + core/scheduler 既有选路/在途/冷却/额度预留

🔴 抽象只做在 **≥2 个产品已被证实的共性**上（登录两步式、凭据存储、设备身份三约束、
   四类结果）——不做通用 DSL、不做统一四表（Q27-⑤ 维持，§22.1）。
🔴 本文件是**公开面**（最小导出，§22.3）：包外一律经它取公共层的东西；
   包内各模块之间用绝对模块路径互相引用（不经包属性，避免导入期的部分初始化歧义）。
"""

from __future__ import annotations

# 🔴 导入顺序 = 依赖顺序（types → net → device → store → login → registry）：
#    包内模块用绝对路径互相 import，中途任何一环都不会撞上"父包只初始化了一半"。
from model_gateway.accounts.types import (
    Capabilities,
    Challenge,
    ClaimOutcome,
    DeviceSpec,
    LoginKind,
    LoginOutcome,
    LoginState,
    ModelInfo,
    NotRefreshable,
    ProbeResult,
    ProductMeta,
    QuotaSnapshot,
    QuotaState,
)
from model_gateway.accounts.net import cred_fingerprint, make_client, mask
from model_gateway.accounts.device import (
    check_unique,
    derive_id,
    find_account_by_values,
    generate_unique,
)
from model_gateway.accounts.store import (
    CommitError,
    ImportResult,
    RuntimeUnreadable,
    commit_login,
    delete_account,
    hook_meta,
    import_account,
    list_accounts,
    load_credentials,
    plan_import_device,
    product_root,
    read_runtime,
    sanitize_name,
    write_runtime,
)
from model_gateway.accounts.login import (
    LoginEngine,
    LoginSession,
    alt_call,
    callback_login,
    cancel_login,
    commit_pending,
    get_session,
    poll_login,
    shutdown_login,
    start_login,
)
from model_gateway.accounts.materialize import (
    credential_fingerprint,
    disable_resource,
    ensure_resource,
)

__all__ = [
    # 类型（§22.3 冻结）
    "Capabilities", "Challenge", "ClaimOutcome", "DeviceSpec", "LoginKind",
    "LoginOutcome", "LoginState", "ModelInfo", "NotRefreshable", "ProbeResult",
    "ProductMeta", "QuotaSnapshot", "QuotaState",
    # 登录两步式会话引擎（含 §22.3 补入②/③：`kind` 形态、`_ALT_HOOKS` 派发；
    # `commit_pending` = M7-E 两阶段提交第二段：用户点「确定接入」才落盘）
    "LoginEngine", "LoginSession", "alt_call", "callback_login", "cancel_login",
    "commit_pending", "get_session", "poll_login", "shutdown_login", "start_login",
    # 账号 → 资源物化（§22.5-1：登录/导入成功自动物化，删除时停用保留）
    "credential_fingerprint", "disable_resource", "ensure_resource",
    # 账号存储唯一入口（§22.2 布局 / §22.3 写回自检 + 失败整体回滚 / 补入① `hook_meta`）
    "CommitError", "ImportResult", "RuntimeUnreadable", "commit_login",
    "delete_account", "hook_meta", "import_account", "list_accounts",
    "load_credentials",
    "plan_import_device", "product_root", "read_runtime", "sanitize_name",
    "write_runtime",
    # 设备身份（§15.1 三约束的泛化）
    "check_unique", "derive_id", "find_account_by_values", "generate_unique",
    # 网络与脱敏工具
    "cred_fingerprint", "make_client", "mask",
]
