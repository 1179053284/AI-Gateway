"""Model-Gateway 入口：装配 + uvicorn 启动（tech-design §7 / §10.1）。

- Runtime：热重载原子替换的运行时聚合（config/resources/classifier/adapters/枚举池）
- 生命周期：事件流水单写 task + 日聚合 task + 配置 mtime 轮询热重载
- 启动：python -m model_gateway.main；配置 data/config.yaml（MG_CONFIG 可覆盖路径）
"""

from __future__ import annotations

import atexit
import asyncio
import contextlib
import datetime as dt
import json
import logging
import os
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from model_gateway import __version__
from model_gateway.adapters import build_adapter
from model_gateway.api.admin import router as admin_router
from model_gateway.api.admin_accounts import cron_enabled_of
from model_gateway.api.anthropic import router as anthropic_router
from model_gateway.api.auth import AuthMiddleware
from model_gateway.api.openai_compat import router as openai_router
from model_gateway.config.loader import ConfigError, load_config
from model_gateway.config.schemas import AppConfig
from model_gateway.core.cancel import CancelRegistry
from model_gateway.core.dialects import DialectTable
from model_gateway.core import paths
from model_gateway.core.errors import ErrorClassifier, register_secret_values
from model_gateway.core import instance_lock
from model_gateway.core.ir import ReasoningSpec
from model_gateway.core.resources import (
    RESOURCE_PAGE,
    ROUTE_POOL_PAGE,
    ResourceManager,
    normalize_base_url,
    servable_models,
)
from model_gateway.core.scheduler import Scheduler
from model_gateway.enums.matcher import EnumPool, load_enum_pool
from model_gateway.stats.aggregate import aggregate_day
from model_gateway.stats.events import EventLogger

# 🔴 全部数据路径经 `core/paths` 解析（**与 cwd 无关**、MG_CONFIG 优先）：
#    原写法 `Path("data")/...` 在别处启动的 CLI 进程里会指向另一个目录，
#    单实例锁 / 运营互斥锁 / 熔断状态因此各自为政（验收 M-4）。
# 规则：**配置在哪，数据就在哪**（`data_dir()` = 生效配置的父目录）——
# 既保证同一份配置在任何 cwd 下指向同一份状态（跨进程互斥/单实例锁成立），
# 又让 `MG_CONFIG=/tmp/xxx/config.yaml` 天然把全部状态文件隔离到该目录。
ENUMS_PATH = paths.data_dir() / "model-enums.yaml"
USAGE_DIR = paths.data_dir() / "usage"
DIALECTS_PATH = paths.data_dir() / "dialects.json"  # 方言表（§13.4，mgw probe 产出）
LOCK_PATH = paths.data_dir() / instance_lock.LOCK_FILENAME  # 单实例锁（§4.10-③）

logger = logging.getLogger("model_gateway")


def refresh_quotas(runtime) -> int:
    """把 ZCode 账号额度余量刷进 `ResourceState.quota_remaining`（§17 / §19 M5-3）。

    单独成函数是因为它有**三个**触发点（§17 表）：启动、ops tick 末尾、管理端点。
    读取只走**客户端日志通道**（无网络、无签名），代价是一次 4 MiB 尾读。

    ⚠️ §17 的第 ② 个触发点「模型转发成功后按 30s 节流补刷」**有意未接**：
    每次转发都尾读 4 MiB 日志会拖慢热路径，而预留闸门用的是**最近一次快照**，
    tick 级（默认 60s）的新鲜度足以拦住"余量已 0 还在派活"这一类超发。
    """
    try:
        from model_gateway.upstream.zcode import quota as zq
        return zq.refresh_runtime_quotas(runtime)
    except Exception as e:  # noqa: BLE001 — 额度读取失败不得影响转发与领取
        logger.warning("额度刷新失败（不影响模型转发）：%s", e)
        return 0


def sync_circuit(runtime) -> tuple[int, int]:
    """启动时把落盘的 3012 全局熔断对齐回资源状态（§17 / 验收 IX-2）。

    与 `refresh_quotas` 同一族的"上游状态 → ResourceState"回写，
    只是它的触发点**只有启动一个**：熔断是在进程外被别的进程（CLI）写下的，
    本进程重启后必须重新看见它，否则"落盘防重启丢失"只落了文件、丢了效果。

    ⚠️ 方向不对称是**有意的**（2026-09-29 用户裁决「读时重判」）：
    **建立**熔断只在启动时对齐一次（重启前不会有新文件），
    **解除**则在每一次读（出快照 / 选路）时重判 —— 由
    `ResourceManager.circuit_active` 注入的判据负责（见 `Runtime._wire_circuit_rejudge`），
    所以这里 bench 出来的冷却带 `circuit_held` 标记，用户删掉状态文件后
    下一次读就把它放回生效集，不必重启、也不用等旧钟点走完。

    🔴 一个资源都没对上时也要**留痕**（验收 ix-M-6）：这条回写是熔断的唯一可见出口，
    匹配靠"资源备注 == ZCode 账号名"。静默空转会让用户以为"熔断根本没生效"，
    所以 `bench 数为 0 但熔断仍在生效` 与 `有同名资源却因 product 不符被跳过`
    两种情况都必须进日志（界面侧的对应出口是「配置告警」横幅体系，二期补）。

    🔴 但 `(0, 0)` 有**两种**成因（验收 S-19）：熔断仍在生效却没人对上号，
    与**根本没有熔断**。原实现不看熔断是否生效，只要配了资源就打
    "全局风控仍在生效" —— 每次正常启动谎报一次风控状态（同一处症状是空括号 `（）`，
    因为 `reason()` 在未熔断时是空串）。日志里的一句"仍在生效"是用户判断
    "要不要动这些资源"的依据，它必须与文件里的状态一致。
    """
    try:
        from model_gateway.upstream.zcode import quota as zq
        benched, skipped = zq.sync_circuit_to_runtime(runtime)
        circuit = zq.get_circuit()
        if not circuit.active():
            return benched, skipped                  # 未熔断 → 一声不响
        if benched:
            logger.warning("[熔断对齐] 全局风控仍在生效，已 bench %d 个资源（%s）",
                           benched, circuit.reason())
        elif skipped:
            logger.warning("[熔断对齐] 全局风控仍在生效，但 %d 个同名资源的 product 不是 "
                           "zcode，已跳过（%s）", skipped, circuit.reason())
        elif runtime.config.resources:
            logger.warning("[熔断对齐] 全局风控仍在生效（%s），但没有资源的账号备注对上任何 "
                           "ZCode 账号 —— 界面上看不到熔断痕迹，请到%s把对应资源的"
                           "账号备注填成该 ZCode 账号名", circuit.reason(), RESOURCE_PAGE)
        return benched, skipped
    except Exception as e:  # noqa: BLE001 — 对齐失败不得阻断启动
        logger.warning("熔断状态对齐失败（不影响启动）：%s", e)
        return 0, 0


def _maybe_start_ops(app) -> "asyncio.Task | None":
    """启动运营调度（v2.0 §16.4）—— **配了间隔/cron 就起**，不再看"此刻有没有账号"。

    与 `core/scheduler.py`（模型转发调度）**无关**：本调度只管运营批量触发时机（§16.1 解耦）。
    间隔取 `gateway.zcode.claim_interval_seconds`（0 = 关闭）。

    🔴 M6-6 Fix-η：门与动作 id 都按**声明**取，不再写死 zcode（Fix-δ 报告的 2 行缺口）——
    原先门的判据是 `upstream.zcode.store.list_accounts()`、claim 动作取 `zcode_claim`
    别名（声明 = `("zcode",)`）→ 只接了新产品的部署**根本不起调度器**，新产品账号在
    cron 腿上"注册了但没人跑"（与 `runner.run_once` 的按声明枚举语义自相矛盾）。
    现在：枚举面 = 本 tick 两个动作声明的产品并集（`all_accounts`，与 `run_once` 同源），
    claim 动作取多产品正名 `claim`（`zcode_claim` 别名保留给 `mgw zcode claim` 的
    CLI 契约与它"收窄到 zcode"的语义，不再被 cron 借用）。

    🔴 BD8（设计书 §0-4 BUG-2 / §6 硬前置）：**"启动时 0 账号就永不起定时器"那道一次性判定
    已撤**，门改在**每一轮**（见 `_run` 里的枚举短路）。原判据的本意是"避免空转噪音"，
    代价是整条额度快照链路在新装首启后永久停摆：全新安装 0 账号 → 调度器不起 →
    用户在管理端接入第一个账号 → 本函数只有 startup 钩子这一个调用点（`_startup`），
    于是再没有第二次机会起它 → 账号 `runtime.json` 的唯一写者
    （`ops/builtin/query_balance.py::_write_quota_cache`，`write_runtime` 在 :130）永不运行
    → 额度列恒「尚未刷新」，直到用户重启网关。现在接入后的第一个账号在**下一个 tick**
    自动被跑到，无需重启；代价只是"最长一个间隔"的可见延迟（界面用第四态「尚未刷新」
    如实暴露，设计书 §3）。
    ⚠️ 启动期"枚举不可用 = 不起调度并告警"那道门**刻意保留**（下面的 try/except）：
    它是 fail-closed 留痕判定（注册表/数据目录坏了 ≠ 没有账号，原裸 `except: return None`
    就是把前者说成后者），撤掉它会让坏环境起一个每轮都抛异常的定时器。
    """
    runtime = app.state.runtime
    zcfg = runtime.config.gateway.zcode
    cron = (getattr(zcfg, "claim_cron", "") or "").strip()
    interval = float(getattr(zcfg, "claim_interval_seconds", 60) or 0)
    if not cron and interval <= 0:
        return None

    from model_gateway.ops import builtin as ops_builtin
    from model_gateway.ops import runner as ops_runner

    op_claim = ops_builtin.OPERATIONS[ops_builtin.product_claim.OPERATION_ID]
    op_balance = ops_builtin.OPERATIONS[ops_builtin.query_balance.OPERATION_ID]
    # 枚举面与声明同源（去重保序）：一个只接了 trae/qoder 等新产品的部署也要起调度器
    declared = tuple(dict.fromkeys(op_claim.supported_products + op_balance.supported_products))
    try:
        # 启动期这次枚举**不再决定是否起调度器**（BD8）：只剩两个作用 ——
        #   ① 探"枚举面可用"（下面那道 fail-closed 门），② 给启动日志一个真实数字。
        seeded = ops_runner.all_accounts(declared)
    except Exception as e:  # noqa: BLE001 — 枚举不可用 ≠ 运营必须崩：不起调度并留痕
        # （不上抛：本函数在 startup 钩子里，异常会打断整个启动；但也不能再静默 ——
        #   原先的裸 `except: return None` 让"注册表/数据目录坏了"表现成"没有账号"）
        logger.warning("运营调度未启动：账号枚举失败（%s: %s）", type(e).__name__, e)
        return None

    sched = ops_runner.Scheduler(interval_s=interval or 60.0, cron=cron)

    async def _run() -> None:
        # runtime 透传 → 遇 3012 风控时 **全局熔断 + 回写资源状态**（§17 / §19 M4-4）
        # operation= → 参与方按该动作的 supported_products 过滤 + **枚举**（§16.4 能力声明，
        #   与上面那道门同源；claim 取多产品正名，新产品账号因此真的进得来）
        # 🔴 enabled_of= → **停用账号定时腿也跳过**（BD1 / 设计书 §0-4 BUG-3：界面开关的话
        #   写「账号停用：运营执行跳过」，手动腿一直传（`api/admin_accounts.py::account_claim`），
        #   两条 cron 腿原先不传（`ops/runner.py:462-470`「给了才跳过」）→ 谎只对一半入口成立。
        #   两条腿都传 = 与手动腿同一判据（`cron_enabled_of` 内部就是 `_account_enabled`）；
        #   额度腿同样看停用位：它是运营动作（runner 的过滤语义「运营类跳过 disabled，
        #   续期类不看」—— 续期不属本定时器），账号停用后既不签到也不再替它查余额。
        # 🔴 结果只落 jsonl：顶栏红点的未读数以文件为准（`ops_runner.unread_failures`），
        #    不再累加进程内计数器 —— CLI 独立进程写的失败也要点得亮红点（验收 S-5）
        #
        # BD8 的"每轮门"（取代原启动时的一次性判定）：本轮声明产品里一个账号都没有 →
        #   直接返回，两条腿都不发起。判据与两条腿的枚举同源（`all_accounts(declared)` 是
        #   `run_once` 内部枚举的**超集**，为空时两条腿必然同样无人参与，故无行为损失）。
        #   为什么要在腿外先拦：`run_once` 对空参与方是**正常返回**（`no_participants`，
        #   `runner.py:472-477`）而本函数照常 `write_report` → 0 账号时空写 2×每轮
        #   （60s 间隔 ≈ 2880 行/天）噪音，把真正的运营记录埋掉。
        #   这里不吞异常：枚举读不动就冒给 `Scheduler._tick` 既有的兜底（记 errors +
        #   告警 + 下一轮继续），不在"还没开始干活"的地方悄悄当没事。
        if not ops_runner.all_accounts(declared):
            return
        report = await ops_runner.run_once(operation=op_claim, runtime=runtime,
                                           enabled_of=cron_enabled_of)
        ops_runner.write_report(report, runtime.usage_dir)
        # 🔴 tick 末尾顺带刷额度（§17 触发时机①）：走 **`query_balance` 动作本身**
        #    —— §16.6 首批 2 个 operation 都要真被用到，且失败同样进 JSONL 与红点，
        #    而不是另起一条只有内部效果的刷新路径。
        breport = await ops_runner.run_once(operation=op_balance, runtime=runtime,
                                            enabled_of=cron_enabled_of)
        ops_runner.write_report(breport, runtime.usage_dir)

    # 启动即刷一次：否则首个 tick 之前（最长一个间隔）额度全为"未知"
    refresh_quotas(runtime)

    sched.start(_run)
    app.state.ops_scheduler = sched
    logger.info("运营调度已启动（每 %.0fs 一轮；启动时枚举到 %d 个账号，"
                "无账号的轮次不发起也不落盘）", interval, len(seeded))
    return getattr(sched, "_task", None)


def _outbound_premise_gap(r) -> str | None:
    """该产品资源「出站前提未注入」的原因串（F-5 / F-4，M6-6 Fix-γ）；None = 无缺口。

    🔴 为什么放在这里（装配侧）而不是 `core/`：判据要看 `upstream/<product>/` 的注入缝
    状态，而 `core/` **不得 import `upstream/`**（分层，见 `ResourceManager.circuit_active`
    同一口径）—— 判据由装配侧注入运行态读路径（`ResourceManager.unservable_reason`，
    经 `Runtime._unservable_reason` 组合"装配面缺口 + 本函数"两条），
    `servable_models` 据此把这些映射排除出 `/v1/models` 与 `mgw setup`（选了必然 503 的
    模型不得对外声明，BUG-1 的立意），同时 `config_warnings()` 给出横幅说明去向。

    两类缺口（都是"代码尚未接线"，与"资源被停用/凭据失效"的 ③ 告警分开计数）：

    - **qoder / qodercn**：WASM 加密与 COSY 签名未移植（`SIGNER_FACTORY=None`）
      → 每次调用 fail closed 503（`upstream/qoder/out.py::NOT_WIRED_HINT`）；签名器一旦
      注入（后续波次 / 测试），本判据自动放行，无需改这里。
    - **zcode**：每请求验证码（`CAPTCHA_PROVIDER=None`）未注入 → 走 §17 降级链的
      「JWT 直连」档，**该直连是否成立（D1）尚未裁决**（`docs/research/24 §2-D1`）。
      F-4 的处置是**如实标注、不实现绕过、不加熔断**：本判据让 zcode 模型在前提未注入时
      不对外声明，横幅文案明确写出"zcode 直连前提未验证（D1）"—— 交付话术不得宣称
      "zcode 模型转发可用"。注入验证码 provider 后本判据自动放行（语义即"前提已就位"）。
    """
    prod = str(getattr(r, "product", "") or "").strip()
    if not prod:
        return None
    try:
        if prod in ("qoder", "qodercn"):
            from model_gateway.upstream.qoder import out as qoder_out
            if qoder_out.SIGNER_FACTORY is None:
                return "qoder 签名未注入（WASM/COSY）"
        elif prod == "zcode":
            from model_gateway.upstream.zcode import out as zcode_out
            if zcode_out.CAPTCHA_PROVIDER is None:
                return "zcode 验证码未注入"
    except Exception as e:  # noqa: BLE001 — 判据读不动 = 不知道；不据此隐藏（见 ResourceRegistry）
        logger.warning("出站前提判据不可用（按'无缺口'处理）：%s：%s", prod, e)
        return None
    return None


class Runtime:
    """运行时聚合：热重载时整体原子替换可变字段（在途请求绑定的快照不受影响）。"""

    def __init__(self, config: AppConfig, config_path: Path,
                 usage_dir: Path | None = None, enums_path: Path | None = None,
                 dialects_path: Path | None = None):
        self.config_path = config_path
        self.usage_dir = Path(usage_dir) if usage_dir else USAGE_DIR
        self.enums_path = Path(enums_path) if enums_path else ENUMS_PATH
        self.dialects_path = Path(dialects_path) if dialects_path else DIALECTS_PATH
        self.started_mono = time.monotonic()
        self.resources = ResourceManager()
        #: 本轮 `_apply` 里**构造失败的资源**（rid → 原因；B-1 的"未接线/坏"标记）。
        #: 必须住在实例上而不是局部：`config_warnings()`（总览横幅）要在**装配之后**读它 ——
        #: 只写日志 = 用户看不见（本仓自己的论据，见 `config_warnings` 头注）。
        #: ⚠️ 初始化必须排在 `_unservable_reason` 注入**之前**（该判据会读它）。
        self._adapter_errors: dict[str, str] = {}
        #: 最近一次热重载失败的原因（F2，面板修复轮-2）：`_apply` 前置步骤失败时
        #: 运行态保持上一代（整体不换），失败原因经 `config_warnings()` 出横幅 ——
        #: 原先只有 stdout/日志，而启动脚本自动关窗（用户看不见），表现为"改了配置没反应"。
        self._apply_error: str | None = None
        # 🔴 熔断的"读时重判"判据在这里接线（2026-09-29 用户裁决）：
        #    `core/` 不 import `upstream/zcode/`，所以由装配侧把「熔断此刻是否仍成立」
        #    注入运行态读路径（出快照 / 选路两处共用）。与 `sync_circuit()` 的启动对齐
        #    同族 —— 那条只在启动写一次，这条每次读都重判，两者共用同一个落盘判据。
        self._wire_circuit_rejudge()
        # 🔴 B-2 / F-5（M6-6 Fix-γ）：两条**装配侧判据**同样在这里接线（分层与熔断重判同口径）：
        #    · 凭据短哈希 → 连接身份指纹（重新登录 / 改绑账号 = 新连接 → 终态清零）；
        #    · 「出站前提未注入」→ 该资源的映射不进可服务集（`servable_models`
        #      与 `config_warnings()` 共用同一判据）。
        # 🔴 F1（面板修复轮-2）：判据从"仅出站前提"扩为 `self._unservable_reason` ——
        #    **没有可用户适配器**（空 `base_url` 静默跳过 / 构造失败降级）的资源同样
        #    选中必 503（`Scheduler._adapter` 抛网关错误），必须与前提缺口走同一条缝。
        self.resources.credential_fingerprint = self._resource_credential_fp
        self.resources.unservable_reason = self._unservable_reason
        self.classifier = ErrorClassifier(config.error_rules)
        self.enum_pool: EnumPool = load_enum_pool(self.enums_path)
        # 方言表（v2.0 §13.4）：**启动时加载一次**进内存快照；`mgw probe` 写完文件后
        # 由 reload_dialects() 显式重载 —— **不新增 mtime 轮询**（不为它加第二个 watcher）。
        self.dialects: DialectTable = DialectTable.load(self.dialects_path)
        self.adapters: dict[str, Any] = {}
        #: 每条资源当前适配器的**复用判据**（§22.5-3）：与 `self.adapters` 同生共死。
        #: 为什么单独存一份而不是问适配器要：判据里含 `product + account_ref + 凭据指纹`，
        #: 而后者是**账号目录的当前状态**（适配器自己不知道"建它的时候凭据是什么"）。
        self._adapter_keys: dict[str, tuple] = {}
        # 🔴 已退役但**还不能关**的出站适配器（旧账 #48）：在途请求绑的是旧运行时快照，
        #    立刻 `aclose()` 会把正在流的响应截断，所以走"延迟排空"。
        self._pending_close: list[Any] = []
        self._drain_tasks: set = set()
        # 🔴 运营未读失败数**不住在这里**：以 `data/usage/ops-results-<date>.jsonl` 为唯一
        #    事实源（`ops.runner.unread_failures`）—— 进程内计数器既看不见 CLI 进程写的
        #    失败，又会在网关重启时把"还没人看过"的记录清零（验收 S-5）。
        self.key_values: dict[str, str] = {}
        self.resource_reasoning: dict[tuple[str, str], ReasoningSpec | None] = {}
        self.model_params: dict[str, dict] = {}  # 网关级模型参数（Q24）：模型名 → 注入参数
        self.events = EventLogger(self.usage_dir, retention_days=config.gateway.retention_days)
        self.cancel_registry = CancelRegistry()
        self.switch_ring: deque = deque(maxlen=200)
        self.scheduler = Scheduler(self)
        self._reload_lock = threading.Lock()
        self.config: AppConfig = config
        self._apply(config)

    def _wire_circuit_rejudge(self) -> None:
        """把「全局熔断此刻是否仍成立」的判据注入 `ResourceManager`（读时重判的分层缝）。

        🔴 取**调用时**的单例（`zq.get_circuit()`）而不是启动时绑好的实例方法：
        `CooldownManager` 是进程内单例，测试与运维会整体重建它
        （`_reset_circuit_for_tests`），绑成 `get_circuit().active` 会让注入的判据
        永久指向那个已被换掉的旧实例 —— 旧实例记的还是上一个临时目录里的状态文件，
        于是"删了文件却没放开"这类错会换个位置复现，而且只在全绿的情况下复现。

        ⚠️ 判据抛错（ZCode 子模块不可用 / 状态文件读不动）由
        `ResourceManager._circuit_cleared()` 按 **fail-closed** 处理：不知道就不放开
        （与 Q28-⑧①「读不动按熔断拒跑」同向）。装配失败只影响"重判"这一条新增能力，
        到期归位、启动对齐、熔断闸门本身都不依赖它。
        """
        try:
            from model_gateway.upstream.zcode import quota as zq
        except Exception as e:  # noqa: BLE001 — ZCode 子模块缺失不得阻断启动
            logger.warning("熔断读时重判未接线（不影响转发与到期归位）：%s", e)
            return

        self.resources.circuit_active = lambda: zq.get_circuit().active()

    def _apply(self, config: AppConfig) -> None:
        """按新快照重建派生件（资源状态按 resource_id 保留，tech §8-4）。

        🔴 F2（面板修复轮-2）：**两阶段——先全部构造、后一次换**。派生件里的任何
        前步骤（如 `load_enum_pool` 读坏用户可扩展的 `model-enums.yaml`）失败，
        都在**触碰任何共享状态之前**抛出：运行态保持上一代（config 与 adapters
        同代），不再出现"config 已换新、adapters/key_values 还是旧的"半应用。
        失败原因由 `reload_from_file` 记进 `self._apply_error` → `config_warnings()`
        出横幅（原先只有 stdout/日志，启动脚本自动关窗时用户看不见）。
        """
        # —— 阶段 1：纯构造（可抛；抛出 = 调用方保持旧运行态，见 reload_from_file）——
        classifier = ErrorClassifier(config.error_rules)
        enum_pool = load_enum_pool(self.enums_path)
        # 资源级推理默认（Q15）：(resource_id, vendor_model) → 默认值
        reasoning_map: dict[tuple[str, str], ReasoningSpec | None] = {}
        for m in config.models:
            for r in m.resources:
                rd = r.reasoning
                reasoning_map[(r.resource, r.model)] = (
                    ReasoningSpec(enabled=rd.enabled, effort=rd.effort) if rd else None)
        # 网关级模型参数（Q24）：系统模型名 → 出站注入参数（请求级同名字段优先，仅 chat）
        model_params = {m.name: dict(m.params) for m in config.models if m.params}
        new_adapters, new_keys, adapter_errors = self._build_adapters(config, enum_pool)
        # F3（面板修复轮-2）：把本网关自己的 Key 登记进脱敏表（只进内存，不落盘/不进日志）
        # —— 上游裸回显（无 `Bearer`/`sk-` 形态）时只有字面值匹配能遮住。
        register_secret_values(r.api_key for r in config.resources)

        # —— 阶段 2：一次性提交（赋值；无失败路径）——
        self.config = config
        self.resources.rebuild(config)
        self.classifier = classifier
        self.enum_pool = enum_pool
        # key 值索引（资源 id 唯一，schemas 已保证）
        self.key_values = {r.id: r.api_key for r in config.resources}
        self.resource_reasoning = reasoning_map
        self.model_params = model_params
        # 🔴 被换下/删掉的那些**不能直接丢**（旧账 #48，2026-09-29 实测取证）：
        #    下面这行一执行，旧适配器就没人引用了，而它的 `httpx.AsyncClient` 只有在被
        #    `aclose()` 时才释放连接池 —— 原先整条路径都没有这一步，`Runtime.aclose()`
        #    又只遍历**当前**字典，于是变成"每改一次配置就漂一个 client 到进程退出"。
        #    上面那句「防在途连接泄漏」的注释以前是**说满了**：复用判据只防住"凭据类改动
        #    多造一个 client"，真正被换掉的那些照样漏（同族毛病：注释写的比实现做的多）。
        #    现在交给 `_retire_adapters` 延迟排空，宽限期取请求总预算，不截断在途请求。
        reused = {id(a) for a in new_adapters.values()}
        self._retire_adapters([a for a in self.adapters.values() if id(a) not in reused])
        self.adapters = new_adapters
        self._adapter_keys = new_keys
        self._adapter_errors = adapter_errors
        self._apply_error = None
        if getattr(getattr(config.gateway, "zcode", None), "fingerprint", False):
            from model_gateway.upstream.zcode.auth import fingerprint_available
            if not fingerprint_available():
                logger.warning(
                    "已开启 gateway.zcode.fingerprint，但 curl_cffi 不可用 → 已降级为普通 httpx"
                    "（zcode.z.ai 可能被 WAF 拦截，建议 pip install curl_cffi）")

    def _build_adapters(self, config: AppConfig,
                        enum_pool: EnumPool) -> tuple[dict[str, Any], dict[str, tuple],
                                                      dict[str, str]]:
        """阶段 1 的出站适配器构造（F2 拆出：可抛、不碰 `self.*`；读旧代做复用判据）。

        返回 `(adapters, reuse_keys, adapter_errors)`；**任何**构造失败按资源降级
        （B-1：标记进 `adapter_errors` + 横幅，其余资源与热重载照常）。
        """
        # 出站适配器（按资源 id 索引；复用判据见 `_adapter_reuse_key`）。
        # 🔴 复用判据只防"凭据类改动多造一个 client"，**不防泄漏**：被换掉的那些由
        #    `_retire_adapters` 延迟排空负责（旧账 #48；此处注释以前写"防在途连接泄漏"
        #    是说满了，实测被换下的 client 整个进程周期都没人关）。
        # v2.0 §18.2 ②：按 `r.protocol` 分支 —— v1.6 此处**无条件**构造 OpenAIOutAdapter，
        # `protocol` 字段完全未被使用（ZCode 这类 Anthropic 上游接不进来）。
        # §22.5-3（M6-5a）：`product` 非空 → 产品出站分支（优先于 protocol），
        # 判据追加 `product + account_ref + 凭据指纹`（改绑账号必须重建，S-14 同族）。
        new_adapters: dict[str, Any] = {}
        new_keys: dict[str, tuple] = {}
        adapter_errors: dict[str, str] = {}   # 每轮重建：坏资源的标记随配置一起换（B-1）
        for r in config.resources:
            # 🔴 判空要用同一把归一化尺（第八轮 8a 的 E-1）：只填了空格的 URL 在
            #    `if not r.base_url` 眼里算"有"，于是建出一个指向空串的适配器，
            #    请求照发、错误直出 httpx 黑话 —— 用户看到的是网络故障而不是"没配端点"。
            # 🔴 F1（面板修复轮-2）：这里 `continue` 掉的资源由 `_adapter_gap` 判据
            #    认领（进不可服务集 + 横幅），不再是"零横幅静默跳过"。
            if not normalize_base_url(r.base_url):
                continue
            key = self._adapter_reuse_key(r)
            old = self.adapters.get(r.id)
            if old is not None and self._adapter_keys.get(r.id) == key:
                new_adapters[r.id] = old
                new_keys[r.id] = key
                continue
            try:
                adapter = build_adapter(
                    r.protocol, normalize_base_url(r.base_url),
                    needs_base64=enum_pool.needs_base64_image,
                    # TLS 指纹（§17）：由 `gateway.zcode.fingerprint` 驱动；
                    # 开启但 curl_cffi 不可用时在下面告警（不静默失败）
                    fingerprint=bool(getattr(getattr(config.gateway, "zcode", None),
                                             "fingerprint", False)) and r.protocol == "anthropic",
                    product=r.product, account_ref=r.account_ref)
            except Exception as e:  # noqa: BLE001 — 🔴 B-1（M6-6 Fix-γ）
                # **任何**构造失败都按资源降级，不得冒穿（原先只捕 `NotImplementedError`，
                # 未登记 product 的 `KeyError`（`product_out.py::registry_get`）直接打死
                # 热重载任务）。`_apply` 跑在 mtime 轮询任务里：一条坏资源 = 此后**所有**
                # 配置改动不再生效，而界面与 `/health` 毫无提示 —— 比"缺一个适配器"严重
                # 得多（本行上面的原注释对该论证同样成立，护栏此前只覆盖了一半）。
                # 资源标记 = 本轮跳过 + WARNING + `config_warnings()` 横幅（用户可见出口）
                # + **进不可服务集**（F1：`_adapter_gap` 判据，其映射不再对外声明）；
                # 请求真落到它时由 `Scheduler._adapter` 给出可读 GatewayError（既有语义）。
                logger.warning("资源 %s 的出站适配器构造失败，本轮跳过（其余资源与热重载照常）："
                               "%s: %s", r.id, type(e).__name__, e)
                adapter_errors[r.id] = f"{type(e).__name__}: {e}"
                continue
            # ⚠️ F-6（M6-6 Fix-γ）：原先这里有一行 `adapter.protocol = r.protocol`
            #    —— **死写 + 语义污染**（全仓无读者：复用判据读的是配置里的 `r.protocol`），
            #    且会把产品适配器**自报**的协议族（qoder/trae 的 `custom`、zcode 的
            #    `anthropic`）覆写成 schema 字面量。产品分派以 `product` 为准（§22.5-3），
            #    留在这里只会让诊断看到假值 —— 已删，不要再加回来。
            new_adapters[r.id] = adapter
            new_keys[r.id] = key
        return new_adapters, new_keys, adapter_errors

    def _adapter_gap(self, r) -> str | None:
        """该资源**装配面**的不可服务原因（F1；None = 有可用适配器）。

        两类成因（都是"选了必 503"，与"资源停用/失效"的运行态口径分开计数）：

        - **`base_url` 为空**（含只填空格，判空用 `normalize_base_url` 同一把尺）：
          `_build_adapters` 静默跳过 —— 原先**零横幅**，调用文案还谎报
          "protocol 未实现"（协议明明已实现，是地址没配）；
        - **适配器构造失败**（未登记产品 / `build_out` 未接线 / 任何装配异常）：
          B-1 已按资源降级并记 `_adapter_errors`，本判据把它接入可服务集。
        """
        if not normalize_base_url(getattr(r, "base_url", "")):
            return "base_url 未配置（出站地址为空）"
        err = self._adapter_errors.get(getattr(r, "id", ""))
        if err:
            return f"出站适配器构造失败（{err}）"
        return None

    def _unservable_reason(self, r) -> str | None:
        """`ResourceManager.unservable_reason` 判据本体（装配侧；F1 扩展）。

        顺序：装配面缺口（空地址 / 构造失败）**优先**于出站前提缺口 —— 两者都会让
        资源必然 503，但前者的处置动作是"补配置/修产品名"，后者是"等接线 / 先停用"，
        横幅分开展示（`config_warnings()` ⑥ 与 ⑤）。
        """
        reason = self._adapter_gap(r)
        if reason:
            return reason
        return _outbound_premise_gap(r)

    def _adapter_reuse_key(self, r) -> tuple:
        """出站适配器的**复用判据**（§22.5-3；`_apply` 每轮热重载逐资源比较）。

        - `base_url` / `protocol`：既有口径（归一化走 `normalize_base_url` 唯一尺，S-19）；
        - `product` + `account_ref`：**改绑账号必须重建适配器**（S-14「连接身份分叉」
          同族缺陷 —— 复用旧账号的适配器 = 请求带着旧账号的凭据/身份头打上游）；
        - 凭据短哈希指纹：账号重新登录 / 凭据更替也算换了连接身份。指纹**只进内存判据**，
          不落盘、不进日志（§22.2 不变式②：日志里凭据只以短哈希出现）。

        指纹读不动（未登录 / 文件损坏）→ 空串：两次都读不动时保持复用（不因读取失败
        抖动重建），一旦可读（指纹变化）立刻重建。**读取失败只降级判据，不阻断装配**。
        """
        prod = (r.product or "").strip()
        return (normalize_base_url(r.base_url), r.protocol, prod,
                (r.account_ref or "").strip(),
                self._credential_fp(prod, r.account_ref))

    def _resource_credential_fp(self, r) -> str:
        """B-2 的连接身份**凭据分量**：该产品资源当前凭据的短哈希（`Resource` → str）。

        由 `Runtime.__init__` 注入 `ResourceManager.credential_fingerprint`（装配侧判据，
        分层：`core/` 不 import `accounts/`）—— 401 判死的产品资源在**重新登录 / 改绑账号**
        后（凭据变化 → 连接身份变化）由 `rebuild` 把 `disabled` 终态清零，用户按提示
        "重新登录"才真的能恢复。判据读不动 → 空串（运行态至少仍含 `product + account_ref`）。
        """
        return self._credential_fp((getattr(r, "product", "") or "").strip(),
                                   getattr(r, "account_ref", ""))

    def _credential_fp(self, product: str, account_ref: str) -> str:
        """账号目录凭据的短哈希（**连接身份判据的唯一读取口径**；失败 → 空串）。

        🔴 B-2（M6-6 Fix-γ）：复用判据（本类 `_adapter_reuse_key`）与运行态指纹
        （`ResourceManager._credential_fp`）**共用这一个函数** —— 两处各写一份序列化
        口径就是 S-14「连接身份分叉」的形态。指纹只进内存判据，不落盘、不进日志
        （§22.2 不变式②：日志里凭据只以短哈希出现）。
        """
        prod = (product or "").strip()
        if not prod:
            return ""
        try:
            from model_gateway.accounts.materialize import credential_fingerprint
            return credential_fingerprint(prod, (account_ref or "").strip())
        except Exception as e:  # noqa: BLE001 — 判据降级，装配照常（§22.8-6）
            logger.warning("账号凭据指纹读取失败（连接身份判据降级为空串）：%s/%s：%s",
                           prod, account_ref, e)
            return ""

    def _drain_grace_seconds(self) -> float:
        """排空宽限期 = **请求总预算**（`gateway.request_total_budget_seconds`，Q16/§5.5，默认 300）。

        为什么取这个数而不是拍一个常数：在途请求最久不会超过总预算，所以
        "宽限期 ≥ 总预算"既**不可能截断任何合法请求**，又给出泄漏上界。
        配置缺字段/不是正数时退回 300 —— 退回方向是**更保守**（等得更久），不是更快关。
        """
        raw = getattr(self.config.gateway, "request_total_budget_seconds", None)
        return float(raw) if isinstance(raw, (int, float)) and raw > 0 else 300.0

    def _retire_adapters(self, olds: list[Any]) -> None:
        if not olds:
            return
        self._pending_close.extend(olds)
        self._schedule_drain()

    def _schedule_drain(self) -> None:
        """挂一个延迟任务去排空。没有事件循环时**原样留在 `_pending_close`**，
        由停机的 `aclose()` 兜底 —— 宁可晚关，不可不关，且兜底路径必须真存在。"""
        if not self._pending_close:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._drain_pending())
        self._drain_tasks.add(task)
        task.add_done_callback(self._drain_tasks.discard)

    async def _drain_pending(self) -> None:
        await asyncio.sleep(self._drain_grace_seconds())
        # 🔴 **先摘再关**：若在循环中途被取消（停机），不会出现
        #    "任务里持有、列表里已清"两边都不负责的彻底漏关。
        while self._pending_close:
            adapter = self._pending_close.pop(0)
            with contextlib.suppress(Exception):
                await adapter.aclose()

    async def reload_from_file(self) -> tuple[bool, list[str]]:
        """热重载：校验通过 → 原子替换；失败 → 保留旧快照（INT-19 ②）。

        🔴 F2（面板修复轮-2）：`_apply` 的**任何**失败（如用户手改坏被 UI 直写的
        `model-enums.yaml` → `load_enum_pool` 抛 ParserError）都走"**整体不换** +
        横幅"：`_apply` 已按"先构造、后提交"写成两阶段，抛出时 `self.config` /
        `self.adapters` 仍是上一代（同代）；失败原因记进 `self._apply_error`，
        由 `config_warnings()` 出横幅（原先只有 stdout/日志 + 运行态半应用）。
        """
        with self._reload_lock:
            try:
                config = load_config(self.config_path)
            except ConfigError as e:
                self._apply_error = f"配置校验失败：{'；'.join(e.errors)}"
                return False, e.errors
            try:
                self._apply(config)
            except Exception as e:  # noqa: BLE001 — 🔴 F2：前置派生件失败 → 整体不换 + 横幅
                logger.warning("配置热重载失败，运行态保持上一代（config/adapters 同代）："
                               "%s: %s", type(e).__name__, e)
                self._apply_error = f"{type(e).__name__}: {e}"
                return False, [self._apply_error]
            return True, []

    def reload_dialects(self) -> None:
        """显式重载方言表（v2.0 §13.4）。

        由 `mgw probe` 写完 `data/dialects.json` 后调用（CLI 侧走管理端点或重启）。
        **不新增 mtime 轮询** —— 现有热重载只监听 config.yaml，不为方言表加第二个 watcher。
        """
        self.dialects = DialectTable.load(self.dialects_path)

    def config_warnings(self) -> list[dict[str, str]]:
        """配置告警（v2.0 §21 / PRD Q25-⑧）—— **两类**，措辞不同。

        🔴 为什么必须暴露到接口而不只写日志：启动脚本正常路径是 `nohup` 后台拉起
        + **自动关闭终端窗口**（`启动网关.command`）→ **告警写进日志 = 用户看不见**。
        而本告警的立项理由正是"启动时无任何提示"。

        返回 `[{"kind", "message"}]`，由 `/admin/api/overview` 的 `warnings[]` 承载，
        管理端总览页用既有 `.alert-warn` 渲染横幅。
        """
        out: list[dict[str, str]] = []
        # ⓪ F2（面板修复轮-2）：最近一次**热重载失败**必须出横幅 —— 运行态保持上一代
        #    （整体不换），但用户改的那份文件没有生效；原先只有 stdout/日志，
        #    启动脚本自动关窗时表现为"改了配置没反应"（本方法头注的同一论据）。
        if self._apply_error:
            out.append({
                "kind": "hot_reload_failed",
                "message": (f"最近一次配置热重载失败：{self._apply_error}"
                            f" —— 运行态仍是上一代（已生效的模型/资源未变）；"
                            f"修正该文件后再次保存配置即可重试"),
            })
        # ① 模型已启用但 resources 为空 → 调用必返 503 NO_RESOURCE（实测踩过的坑）
        # 🔴 指路的**归属**由控件决定（第十一轮 PM B-11-1）：「添加映射」的入口
        #    `#rv-addmap` 长在 resources.js（「模型资源」页），资源池那一侧只有
        #    档位/优先级/移除映射（models.js）—— 指到「资源池设置」页会让人在那一屏
        #    找不到任何"添加"按钮，比指错页更难查（他会以为自己找错地方）。
        empty_models = [m.name for m in self.config.models if m.enabled and not m.resources]
        if empty_models:
            out.append({
                "kind": "model_without_resource",
                "message": (f"{len(empty_models)} 个系统模型未配置任何资源，"
                            f"已从 /v1/models 与 mgw setup 隐藏（调用将返回 503）"
                            f" —— 到{RESOURCE_PAGE}选中要承接的资源，在「模型列表」里"
                            f"添加映射指向该系统模型"
                            f"（{'、'.join(empty_models[:5])}"
                            f"{'…' if len(empty_models) > 5 else ''}）"),
            })
        # ② 资源已启用但无任何模型引用 → 该资源不会被使用（配置冗余，非故障）
        referenced = {r.resource for m in self.config.models for r in m.resources}
        orphan = [r.name or r.id for r in self.config.resources
                  if r.enabled and r.id not in referenced]
        if orphan:
            out.append({
                "kind": "resource_without_model",
                "message": (f"{len(orphan)} 个资源未被任何系统模型引用"
                            f"（{'、'.join(orphan[:5])}{'…' if len(orphan) > 5 else ''}）"),
            })
        # ③ BUG-1：模型配了映射但无任何可用资源 → 已从 /v1/models 与 mgw setup 隐藏。
        #    隐藏本身解决了"工具选到必然失败的模型"，但**必须由横幅说明去向**，
        #    否则用户看到的是"模型凭空消失"——那是另一种静默。
        #    🔴 这条告警拆三类（F-5，M6-6 Fix-γ + F1，面板修复轮-2）：**仅因出站前提
        #    未注入**而不可服务（qoder 签名 / zcode 验证码未接线，见 `_outbound_premise_gap`）
        #    的模型进 ⑤；**仅因装配面缺口**（空 `base_url` / 适配器构造失败，见
        #    `_adapter_gap`）的模型进 ⑥；其余的（资源停用 / 凭据失效）留在本条 ——
        #    分开计数，同一个模型不会被两条横幅各报一次（用户的处置动作也完全不同）。
        hidden_models = [m for m in self.config.models
                         if m.enabled and m.resources
                         and m.name not in servable_models(self.config, self.resources.registry)]
        gap_hidden: list[tuple[str, list[str]]] = []
        assembly_hidden: list[str] = []
        hidden: list[str] = []
        for m in hidden_models:
            premise = self._premise_gaps(m)
            if premise:
                gap_hidden.append((m.name, premise))
            elif self._assembly_gaps(m):
                assembly_hidden.append(m.name)
            else:
                hidden.append(m.name)
        if hidden:
            out.append({
                "kind": "model_unservable",
                # 🔴 指路必须指对页面（验收 IX-M-3 + 第十一轮 PM B-11-1）：
                #    资源的**启用/禁用**开关与**添加/更换映射**的入口都在「模型资源」页
                #    （resources.js 的 `#rv-toggle` 与 `#rv-addmap`）；
                #    「资源池设置」页只管这一条映射的**档位/优先级/移除**（models.js），
                #    所以"更换映射"不能指到那里 —— 那一屏没有"添加"这一半。
                "message": (f"{len(hidden)} 个已启用模型的资源映射全部不可用（已停用或凭据失效），"
                            f"已从 /v1/models 与 mgw setup 隐藏 —— 到{RESOURCE_PAGE}启用对应资源，"
                            f"或在同一页的「模型列表」里给该模型更换映射"
                            f"（{'、'.join(hidden[:5])}{'…' if len(hidden) > 5 else ''}）"),
            })
        # ④ BUG-2 可见性（**优先级本身不改**，按 PRD FR-3.16/Q15 定序）：
        #    推理档位有三处可配 —— 请求级 > **资源级默认** > 模型参数卡（Q24 网关设置）。
        #    资源级默认更具体（"免费资源默认 low 省额度、主力资源默认 max"），
        #    所以参数卡里同名字段会在这些资源上被覆盖 —— 覆盖是对的，**静默才是缺陷**。
        shadowed = self._shadowed_params()
        if shadowed:
            out.append({
                "kind": "param_shadowed",
                # 🔴 用户要能"看完就知道怎么办"（验收 IX-M-2）：点名是哪个系统模型、
                #    两侧各是什么值、去哪个页面改，并给出完整生效序。
                "message": (f"{len(shadowed)} 个模型的参数卡推理字段不生效："
                            f"{'；'.join(shadowed)}。"
                            f"实际生效序 = 请求级 > 资源级默认 > 参数卡（PRD FR-3.16）"
                            f" —— 要让参数卡生效，请到{ROUTE_POOL_PAGE}清掉对应资源的推理默认"),
            })
        # ⑤ F-5 / F-4（M6-6 Fix-γ）：**出站前提未注入**（qoder 签名 / zcode 验证码）
        #    → 这些映射选了必然 503，已从 /v1/models 与 mgw setup 隐藏。与 ③ 同一立意：
        #    隐藏必须由横幅说明**去向与成因**（"模型凭空消失"是另一种静默）。
        #    F-4 的诚实标注（D1 未裁决：zcode 直连是否成立未验证）并入本条文案；
        #    本波次**不实现绕过、不加熔断**（见 `_outbound_premise_gap` 与 zcode/out.py 注释）。
        if gap_hidden:
            names = [n for n, _gs in gap_hidden]
            causes = sorted({c for _n, gs in gap_hidden for c in gs})
            message = (f"{len(names)} 个模型因出站前提未注入不可服务"
                       f"（{'、'.join(causes)}），已从 /v1/models 与 mgw setup 隐藏 —— "
                       f"选到它们必然失败（503）；请在{RESOURCE_PAGE}暂时停用对应资源，"
                       f"或等待出站通道接线"
                       f"（{'、'.join(names[:5])}{'…' if len(names) > 5 else ''}）")
            if any("zcode" in c for c in causes):
                message += "；注意：zcode 直连前提未验证（D1），当前不代表 zcode 转发可用"
            out.append({"kind": "model_unservable_premise", "message": message})
        # ⑥ B-1（M6-6 Fix-γ）+ F1（面板修复轮-2）：**没有可用出站适配器**的已启用资源
        #    —— 空 `base_url`（原先零横幅静默跳过）/ 构造失败（未登记产品名 /
        #    `build_out` 未接线 / 任何装配异常）。两类都已按资源降级（其余资源照常、
        #    热重载不死），但用户必须看得见"这条资源用不了、它的模型已隐藏"：
        #    只写日志 = 用户看不见（见本方法头注）。
        #    🔴 与 ⑤ 分开计数（见 ③ 的归因注释）；文案里点名的模型 = `assembly_hidden`
        #    （仅因装配面缺口被隐藏的那些），不再让它们落进 ③ 的"已停用或凭据失效"
        #    （那是错的归因：资源的启用开关与凭据都没问题，是适配器没建出来）。
        gap_resources = [r for r in self.config.resources
                         if r.enabled and self._adapter_gap(r)]
        if gap_resources:
            items = [f"{self._resource_label(r.id)}（{self._adapter_gap(r)}）" for r in gap_resources]
            message = (f"{len(items)} 个已启用资源没有可用的出站适配器"
                       f"（base_url 未配置或构造失败），该资源不可调用"
                       f"（其余资源与热重载不受影响）："
                       f"{'；'.join(items[:3])}{'…' if len(items) > 3 else ''}"
                       f" —— 到{RESOURCE_PAGE}补全出站地址，或检查产品名与账号配置")
            if assembly_hidden:
                message += (f"；其映射的 {len(assembly_hidden)} 个系统模型已从 /v1/models "
                            f"与 mgw setup 隐藏"
                            f"（{'、'.join(assembly_hidden[:5])}"
                            f"{'…' if len(assembly_hidden) > 5 else ''}）")
            out.append({"kind": "resource_adapter_unbuilt", "message": message})
        return out

    def _premise_gaps(self, m) -> list[str]:
        """该模型**全部启用映射**的「出站前提未注入」缺口（空列表 = 不因前提被隐藏）。

        判据用**装配侧的前提谓词本体**（`_outbound_premise_gap`，与 `servable_models`
        注入的 `_unservable_reason` 里那一半同源）—— 只是换个方向归类：只要有一条
        启用映射的前提是就位的，这个模型就**不属于** ⑤（它若被隐藏，成因是那一条的
        运行态失效 → 归 ③ 或装配面缺口 → 归 ⑥）。
        """
        return self._gap_reasons(m, _outbound_premise_gap)

    def _assembly_gaps(self, m) -> list[str]:
        """该模型**全部启用映射**的「没有可用出站适配器」缺口（F1；空列表 = 不因此被隐藏）。"""
        return self._gap_reasons(m, self._adapter_gap)

    def _gap_reasons(self, m, probe) -> list[str]:
        """`m` 的全部启用映射都命中 `probe` 时返回原因列表，否则返回 `[]`。

        空列表有两种含义（= 该模型不该由这条横幅认领）：某条映射没有缺口（模型被别的原因
        隐藏），或没有可用映射（`enabled=False` 的引用不算 —— 归 ③ 的停用口径）。
        判据抛错同样返回 `[]`（与 `servable_models` 同口径：不知道就不据此归类）。
        """
        by_id = {r.id: r for r in self.config.resources}
        reasons: list[str] = []
        for ref in m.resources:
            r = by_id.get(ref.resource)
            if r is None or not r.enabled:
                continue
            try:
                reason = probe(r)
            except Exception:  # noqa: BLE001 — 判据不可用 = 不知道（与 servable_models 同口径）
                return []
            if not reason:
                return []
            reasons.append(str(reason))
        return reasons

    def _resource_label(self, rid: str) -> str:
        """资源显示名（备注 → id），供告警文案指认。"""
        for r in self.config.resources:
            if r.id == rid:
                return r.name or r.id
        return rid

    def _shadowed_params(self) -> list[str]:
        """列出「参数卡配了推理字段、但该模型下又有资源级推理默认」的模型（BUG-2 可见性）。"""
        res_by_id = {r.id: r for r in self.config.resources}
        out: list[str] = []
        for m in self.config.models:
            if not m.enabled:
                continue
            shadow_keys = [k for k in ("reasoning_effort", "thinking")
                           if m.params.get(k) is not None]
            if not shadow_keys:
                continue
            hit: list[str] = []
            for ref in m.resources:
                r = res_by_id.get(ref.resource)
                if r is None or not r.enabled or ref.reasoning is None:
                    continue
                if ref.reasoning.effort or ref.reasoning.enabled is not None:
                    dft = ref.reasoning.effort or ("关闭" if ref.reasoning.enabled is False
                                                  else "开启")
                    hit.append(f"资源「{r.name or r.id}」默认 {dft}")
            if hit:
                card_vals = "、".join(f"{k}={m.params.get(k)}" for k in shadow_keys)
                res_vals = "；".join(hit[:2])
                out.append(f"「{m.name}」参数卡 {card_vals} 被资源级默认（{res_vals}）覆盖")
        return out

    async def aclose(self) -> None:
        # 验证码求解器复用同一浏览器（§16.5）→ 停机时必须关掉，否则留无头进程
        with contextlib.suppress(Exception):
            from model_gateway.upstream.zcode.captcha import _SOLVER
            if _SOLVER is not None:
                await _SOLVER.aclose()
        for adapter in self.adapters.values():
            with contextlib.suppress(Exception):
                await adapter.aclose()
        # 🔴 停机时把**还没到宽限期**的退役适配器也关掉（旧账 #48 的兜底路径）：
        #    进程都要退了，不存在"还在途的请求"，等宽限期没有意义；不关就是真漏。
        for task in list(self._drain_tasks):
            task.cancel()
        self._drain_tasks.clear()
        while self._pending_close:
            adapter = self._pending_close.pop(0)
            with contextlib.suppress(Exception):
                await adapter.aclose()


def _load_config_or_exit(config_path: Path) -> AppConfig:
    """加载并校验配置：失败 → 打印错误、退出码 2（create_app 与 main() 共用口径）。"""
    try:
        return load_config(config_path)
    except ConfigError as e:
        print("配置校验失败，拒绝启动：", file=sys.stderr)
        for err in e.errors:
            print(f"  - {err}", file=sys.stderr)
        raise SystemExit(2) from e


class _StaticNoCacheMiddleware:
    """静态 UI 资源禁用缓存（Q19-①：浏览器缓存旧 JS/CSS 导致界面更新不可见/模块混载）。

    对 text/html / text/css / JavaScript 响应追加 Cache-Control: no-store——
    本地静态资源无缓存价值，no-store（不落盘）比 no-cache（协商 304）更彻底：
    杜绝浏览器缓存新旧混载的 ES 模块导致 import 失败、内容区空白（2026-09-05 实测）；
    /admin/api 等 JSON 响应不受影响。
    """

    _STATIC_TYPES = ("text/html", "text/css", "text/javascript", "application/javascript")

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message) -> None:  # type: ignore[no-untyped-def]
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                ctype = next((v.decode("latin-1") for k, v in headers
                              if k == b"content-type"), "")
                if any(t in ctype for t in self._STATIC_TYPES):
                    headers.append((b"cache-control", b"no-store"))
            await send(message)

        await self.app(scope, receive, send_wrapper)


def create_app(config_path: Path | None = None, *,
               usage_dir: Path | None = None, enums_path: Path | None = None) -> FastAPI:
    """装配 FastAPI 应用（测试与启动共用；usage_dir/enums_path 供测试隔离注入）。"""
    config_path = paths.resolve_config_path(config_path)
    config = _load_config_or_exit(config_path)

    runtime = Runtime(config, config_path, usage_dir=usage_dir, enums_path=enums_path)
    for warning in config.warnings:
        print(f"[config 警告] {warning}", file=sys.stderr)
    if not config.gateway.access_tokens:
        print("[config 警告] 未配置任何接入密钥：/v1 端点免鉴权放行（本地单用户场景）", file=sys.stderr)

    app = FastAPI(title="Model-Gateway", version=__version__, docs_url=None, redoc_url=None)
    app.state.runtime = runtime
    app.state.config_path = config_path
    app.state.config_file_loaded = config_path.exists()

    app.include_router(openai_router)
    app.include_router(anthropic_router)
    app.include_router(admin_router)

    @app.get("/health")
    async def health() -> dict:
        cfg = runtime.config
        return {
            "status": "ok",
            "version": __version__,
            "config": {"path": str(config_path), "file_loaded": config_path.exists(),
                       "warnings": cfg.warnings},
            "gateway": {"host": cfg.gateway.host, "port": cfg.gateway.port,
                        "attempt_timeout_seconds": cfg.gateway.attempt_timeout_seconds,
                        "request_total_budget_seconds": cfg.gateway.request_total_budget_seconds},
            "scheduling": {"max_active_per_model": cfg.scheduling.max_active_per_model,
                           "fail_threshold": cfg.scheduling.fail_threshold,
                           "retry_per_request": cfg.scheduling.retry_per_request},
            "resources": len(cfg.resources),
            "system_models": len(cfg.models),
            "access_tokens": len(cfg.gateway.access_tokens),
        }

    # 鉴权中间件（纯 ASGI；持 runtime 引用取最新令牌）
    app.add_middleware(AuthMiddleware, runtime_provider=lambda: app.state.runtime)
    # 静态 UI no-cache（Q19-①：防浏览器缓存旧界面）
    app.add_middleware(_StaticNoCacheMiddleware)

    # Web 管理界面（tech §4.9：无构建静态资源本地内置；置于全部 API 路由之后挂载，
    # 免遮蔽 /health 与 /admin/api/*；html=True 使 / 返回 index.html）
    static_dir = Path(__file__).parent / "web" / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="web")

    @app.on_event("startup")
    async def _startup() -> None:
        runtime.events.start()
        await _write_daily_snapshot(runtime)
        # v2.0 §21 / PRD Q25-⑧：配置告警**双通道**——既进 /admin/api/overview 的 warnings[]
        # （总览页横幅），也打启动日志。单写日志是不够的：启动脚本正常路径是 nohup
        # 后台拉起 + 自动关窗，用户看不到日志。
        for w in runtime.config_warnings():
            logger.warning("[配置告警] %s", w["message"])
        # 🔴 熔断对齐（§17 / 验收 IX-2）：**独立于运营调度是否启动**——
        #    熔断可能由另一个进程（`mgw zcode claim`）写下，即使本进程关闭了运营，
        #    模型转发也不该在风控观察期内打向这些账号。
        sync_circuit(runtime)
        # 运营调度（v2.0 §16.4）：**配了间隔/cron 就起**（BD8：门在每一轮的枚举上，
        #   不在"启动时有没有账号"上 —— 原先 0 账号起不来，接入第一个账号后要等重启才有额度快照）。
        ops_task = _maybe_start_ops(app)
        app.state.background_tasks = [
            asyncio.get_running_loop().create_task(_reload_watcher(app)),
            asyncio.get_running_loop().create_task(_hourly_aggregation(app)),
        ]
        if ops_task is not None:
            app.state.background_tasks.append(ops_task)

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        for t in getattr(app.state, "background_tasks", []):
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        await runtime.events.stop()
        await runtime.aclose()

    return app


async def _reload_watcher(app: FastAPI) -> None:
    """mtime 轮询热重载（tech §4.7 双触发之①；1s 间隔）。

    🔴 B-1（M6-6 Fix-γ）：**本任务不得被任何异常打死**。原先循环体没有任何捕获，
    配置里一条未登记 / 未接线的资源就能让本任务带着异常退出 —— 此后**所有**配置改动
    都不再生效，而界面与 `/health` 毫无提示（比"缺一个适配器"严重得多）。
    `_apply` 已按资源降级（单条坏资源不再冒穿），这里是**第二道兜底**：未知异常
    只终结本轮，循环照常；mtime 记账放在重载之外，坏配置只在那一个 mtime 上试一次，
    不会按 1Hz 刷屏重试。
    """
    runtime: Runtime = app.state.runtime
    last_mtime: float | None = None
    initialized = False
    while True:
        mtime: float | None = None
        try:
            mtime = runtime.config_path.stat().st_mtime if runtime.config_path.exists() else None
            if initialized and mtime != last_mtime:
                ok, errors = await runtime.reload_from_file()
                if ok:
                    print(f"[hot-reload] 配置已重载：{runtime.config_path}")
                else:
                    print(f"[hot-reload] 校验失败，保留旧配置：{'；'.join(errors)}", file=sys.stderr)
        except asyncio.CancelledError:
            raise                      # 停机信号照常冒穿（不得被兜底吞掉）
        except Exception as e:  # noqa: BLE001 — 兜底（B-1）：异常只终结本轮，循环不死
            logger.warning("[hot-reload] 本轮重载异常，循环继续（后续配置改动仍会生效）："
                           "%s: %s", type(e).__name__, e, exc_info=True)
        last_mtime = mtime
        initialized = True
        await asyncio.sleep(1.0)


async def _hourly_aggregation(app: FastAPI) -> None:
    """日聚合：每小时整点重算当日 events → daily-YYYYMMDD.json（tech §4.8）。"""
    runtime: Runtime = app.state.runtime
    while True:
        now = dt.datetime.now()
        nxt = (now + dt.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        await asyncio.sleep((nxt - now).total_seconds())
        with contextlib.suppress(Exception):
            await _write_daily_snapshot(runtime)


async def _write_daily_snapshot(runtime: Runtime) -> None:
    day = dt.date.today()
    path = runtime.usage_dir / f"events-{day.strftime('%Y%m%d')}.jsonl"
    events: list[dict] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
    snapshot = runtime.usage_dir / f"daily-{day.strftime('%Y%m%d')}.json"
    tmp = snapshot.with_suffix(".tmp")
    tmp.write_text(json.dumps(aggregate_day(events), ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, snapshot)


def main() -> None:
    # tech-design §4.10-① 启动序列（严格顺序）：加载配置 → 单实例锁 → 绑定端口启动服务
    config_path = paths.resolve_config_path(None)
    cfg = _load_config_or_exit(config_path)  # ① 校验失败退出码 2 保持

    # ② 单实例锁：获取失败（已有实例）→ 打印后台地址后退出码 3，不启动/不换端口/不询问（§4.10-④）
    result = instance_lock.acquire(LOCK_PATH, cfg.gateway.port)
    if not result.ok:
        ex = result.existing or {}
        base_url = ex.get("base_url") or f"http://127.0.0.1:{ex.get('port', cfg.gateway.port)}/"
        print(f"已有实例运行中：后台地址 {base_url}"
              f"（PID {ex.get('pid', '未知')}、启动时间 {ex.get('started_at', '未知')}）",
              file=sys.stderr)
        sys.exit(3)

    app = create_app(config_path)

    # ④ Server 化（拿句柄替代 uvicorn.run 直启）：server 挂 app.state 供 system 端点
    #    设置 should_exit（stop）；restart 端点置位 restart_requested（§4.10-①②）
    server = uvicorn.Server(uvicorn.Config(app, host=cfg.gateway.host,
                                           port=cfg.gateway.port, log_level="info"))
    app.state.server = server
    app.state.restart_requested = False

    # ⑤ atexit 兜底释放锁（uvicorn 自带 SIGINT/SIGTERM → should_exit 优雅停机；
    #    0.52.4 serve() 内置 capture_signals，无需自注册信号）
    atexit.register(instance_lock.release, LOCK_PATH, os.getpid())

    server.run()

    # 优雅停机完成（run() 返回）：显式释放锁（release 幂等，atexit 兜底）→
    # restart 请求则 execv 进程映像替换（必须排在停机收尾 + 锁释放之后，§4.10-②）
    instance_lock.release(LOCK_PATH, os.getpid())
    if getattr(app.state, "restart_requested", False):
        try:
            os.execv(sys.executable, [sys.executable, "-m", "model_gateway.main", *sys.argv[1:]])
        except OSError as e:
            # execv 失败兜底：锁已释放，可重新拉起；明确报错退出，不静默残留（§4.10-②）
            print(f"[restart] 自重启失败（execv：{e}）；单实例锁已释放，可重新启动网关",
                  file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
