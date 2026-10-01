"""多产品账号管理 API（tech-design v2.0 §22.7；M6-4a 实现）。

端点全集（§22.7 **逐条**；管理端免鉴权沿用 Q18-①，**返回体一律不含凭据明文**）::

    GET  /admin/api/accounts                          全产品账号视图（能力/设备/运行态/额度缓存/资源关联）
    GET  /admin/api/accounts/capabilities             能力矩阵（前端按钮数据驱动）
    POST /admin/api/accounts/login/start              {product, kind?, name?} → Challenge
    POST /admin/api/accounts/login/poll               {product, session} → 状态/成功（成功=凭据已暂存，未落盘）
    POST /admin/api/accounts/login/callback           回跳粘贴（local_callback 型）
    POST /admin/api/accounts/login/commit             {session, product?} → {committed, account}（两阶段提交第二段：确认落盘；幂等，永不 404）
    POST /admin/api/accounts/login/cancel             {session, product?} → {cancelled}（幂等；BD2；一并丢弃暂存凭据）
    POST /admin/api/accounts/login/alt                {product, session, name, args}（`_ALT_HOOKS`）
    POST /admin/api/accounts/import                   外部凭据导入（白名单 + 自检回滚，`22 §5.7`）
    GET  /admin/api/accounts/{product}/{name}/models  模型目录（`list_models` 的生产出口，B-1）
    POST /admin/api/accounts/{product}/{name}/claim   签到/领取（**复用 ops 四类结果出口**）
    POST /admin/api/accounts/{product}/{name}/refresh 凭据续期
    POST /admin/api/accounts/{product}/{name}/probe   探活（连通 / 凭据有效两维）
    POST /admin/api/accounts/{product}/{name}/enable | disable
    POST /admin/api/accounts/{product}/{name}/delete  破坏性：必须显式 `?confirm=1`

**模型映射轮增补（2026-10-01，超出上表 §22.7 冻结清单 —— 逐条语义见各函数）**::

    GET  /admin/api/accounts/{product}/catalog        产品级模型目录（映射弹窗的数据面）
    POST /admin/api/accounts/mappings                 初始化映射（目录条目 → 系统模型）
    POST /admin/api/accounts/claim-all                一键领取（全局 / 单产品批量）

**错误语义**（§22.7）：

| 情形 | 出口 |
|---|---|
| 未登记产品 / 非法账号名 / 非法 kind / 契约表缺项 | 400 + 可读原因 |
| 账号不存在 | 404 + 可读原因 |
| 会话**不存在**（未知 id / 已出表；仅 `alt` 经 `_require_session`） | 404 |
| 会话**已过期 / 已取消** | **结构化 `expired` 结果**（HTTP 200，见下） |
| `NotRefreshable` | **409「不可续期」**（明确语义，**不是 500**） |
| 产品层 `RuntimeError`（上游/流程失败，可重试） | 502 + 原可读原因 |
| 落盘自检失败（已整体回滚） | 500（不谎报成功） |
| 其余异常 | 500（入口层已记日志；§22.8-5 不伪装成业务失败） |

🔴 「模型目录取不动」不是错误出口（B-1 修复，2026-09-30）：`GET …/models` 在钩子抛错时返回
**HTTP 200 + `state:"unknown"` + `reason`**（空 `models`）——「读不到」与「真的为空」必须分开
（与「未知不当零」/ 运行态 `status:"unknown"` 同口径），前端据此只展示原因、**不编造**任何条目。

🔴 「过期」不是 404（M6-6 Fix-η 对齐实现，原表行"会话不存在或已过期 → 404"已过期）：
`poll` / `callback` 对**未知 id 与过期/取消**都返回 `{"state": "expired"}`（HTTP 200，
同一结局 = 无"会话是否存在"的枚举差异面）；`alt` 先经 `_require_session` 取对象，
取不到（未知 id / 已被 `_sweep` 出表）才是 404，取到但已过期/取消则由引擎 `_gate`
返回同样的结构化 `expired`（三条通道同一实现，§22.8-2）。

🔴 各条口径（§22.6 逐条落地）：

- **状态查询包含已停用账号**（视图列出全部；`enabled=false` → `status="disabled"`）；
- **运营执行跳过停用**：claim 经 `ops.runner.run_once(enabled_of=…)` → 停用账号得
  `inactive` 且**不发产品钩子**（能力判据同源，不"点了必然失败"）；
  🔴 **定时腿共用同一判据**（`cron_enabled_of`，M7 BD1 / 设计书 §0-4 BUG-3）——
  原先只有本文件的手动腿传 `enabled_of`，cron 两条腿不传，界面那句「账号停用：运营执行跳过」
  因此只对手动入口成立；现在两个入口同真（`main.py::_maybe_start_ops`）；
- **续期不看 enabled**（refresh 与停用位正交）；
- `precheck` **per-product 显式声明**（`20 B6`；trae 必须 True）→ 单一事实源 `_PRECHECK`
  （= `accounts.registry.PRE_CHECK_PRODUCTS` 同一对象）；
- 凭据落盘**只经** `store.commit_login`（§22.2 不变式⑤：落盘唯一入口）；本层的**异步端点**
  一律走异步版（`commit_login_async` / `import_account_async` / `delete_account_async`，A-1
  接线：等锁/写盘下放工作线程，事件循环不被 ≤1.0s 的跨进程锁等待停摆，语义逐字一致）；
  本层不写 ad-hoc 文件；
- 钩子的 `meta` 形参**只经** `store.hook_meta()` 组装（§22.3 补入①：锚字段 `account`/`dir`）。

⚠️ 已登记的契约缺口（M6-4a 报告，见对应函数注释）：**已全部收口**（无遗留）。
（原缺口①"公共层没有公开的「会话 id → 会话对象」查询口"已收口：公共层已补
`login.get_session(id)` 公开口，本层 `_session_of` 只经它取会话，不再触私有会话表。
原缺口②"`precheck` 声明应收敛进 registry"已由 Fix-ζ 关闭：单一事实源 =
`accounts/registry.py::PRE_CHECK_PRODUCTS`，本模块与 `ops/builtin/product_claim.py`
引用**同一对象**，不再各持副本。）
"""

from __future__ import annotations

import dataclasses
import functools
import importlib
import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from model_gateway.accounts import login
from model_gateway.accounts import registry as account_registry
from model_gateway.accounts import store
from model_gateway.accounts.store import CommitError
from model_gateway.accounts.types import (
    Challenge,
    ClaimOutcome,
    LoginOutcome,
    ModelInfo,
    NotRefreshable,
    ProbeResult,
    ProductMeta,
)
from model_gateway.config.loader import ConfigError, load_config, save_config
from model_gateway.config.schemas import ModelResource, SystemModel
from model_gateway.ops import runner as ops_runner
from model_gateway.ops.base import OpReport, OpResult
from model_gateway.ops.bridge import outcome_to_op_result
from model_gateway.ops.builtin import OPERATIONS, product_claim as product_claim_op

logger = logging.getLogger("model_gateway.api.accounts")

router = APIRouter()

#: 账号视图里**允许出接口**的展示用元信息键（白名单投影）。
#: 🔴 为什么是白名单而不是整份 `meta.json`：产品私有字段可被导入载荷带进来（`import_account`
#: 原样收 `meta` 段），白名单是「**凭据永不返回**」这条硬约束的静态护栏；
#: 需要新展示字段 = 在此加一行的显式动作，不会被"某个产品顺手多写一个键"悄悄带出。
_META_DISPLAY_KEYS = ("via", "created_at", "updated_at", "expires_at",
                      "plan", "nickname", "phone", "email")

#: 领取前预检的 per-product 声明（§22.6「`precheck` per-product 显式声明」/ `20 B6`）。
#: 🔴 **单一事实源 = `accounts/registry.py::PRE_CHECK_PRODUCTS`**（Fix-ζ 收敛：产品事实与
#: 能力位同家）。本名是对**同一对象**的引用（消费点沿用，不是第二份副本）；`trae` 必须
#: 为 True 的依据见 registry 内注释（其 claim 幂等只能靠 status 端点判，`20 §3.1`）。
_PRECHECK: dict[str, bool] = account_registry.PRE_CHECK_PRODUCTS

#: 多产品签到/领取动作对象（§22.6 收敛后 id = `claim`；经 `OPERATIONS` 注册表取，
#: **与 CLI / cron 同一张表**，不另立一个"管理端专属"动作）。`claim-all` 两处消费它：
#: ① 全局腿的参与面声明（`supported_products` → 枚举与过滤都按它推导）；
#: ② `run_once` 的 operation 参数（能力声明过滤的唯一事实源）。
_CLAIM_OP = OPERATIONS[product_claim_op.OPERATION_ID]


# ---------- 统一错误出口（§22.7）----------

class _ApiError(Exception):
    """入口层的显式错误（状态码 + 可读原因 + 附加字段）——由 `_endpoint` 统一转 JSON。"""

    def __init__(self, status: int, message: str, **extra) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra


def _json_error(status: int, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"message": message, **extra}})


def _message_of(e: Exception) -> str:
    """`KeyError` 的 `str()` 自带引号 → 取 `args[0]` 才是可读原因。"""
    if isinstance(e, KeyError) and e.args:
        return str(e.args[0])
    return str(e)


def _endpoint(fn):
    """统一错误出口（映射表见模块头「错误语义」）——**每个端点的唯一异常处理点**。"""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except _ApiError as e:
            return _json_error(e.status, e.message, **e.extra)
        except NotRefreshable as e:          # 必须排在 RuntimeError 之前（子类）
            return _json_error(409, f"该账号不可续期：{e}", refreshable=False)
        except CommitError as e:             # 本地落盘自检失败（已整体回滚）
            return _json_error(500, f"凭据落盘失败（已回滚）：{e}")
        except KeyError as e:
            return _json_error(400, _message_of(e))
        except ValueError as e:
            return _json_error(400, _message_of(e))
        except RuntimeError as e:            # 产品层/上游失败（可重试，原原因回传）
            logger.warning("账号端点 %s 产品层失败：%s", fn.__name__, e)
            return _json_error(502, f"产品层执行失败：{_message_of(e)}")
        except Exception as e:               # noqa: BLE001 — §22.8-5：不伪装成业务失败
            logger.exception("账号端点 %s 内部错误", fn.__name__)
            return _json_error(500, f"内部错误（{type(e).__name__}）：{e}")

    return wrapper


# ---------- 取用点（产品注册表 / 钩子表 / 会话）----------

def _product_meta(product: str) -> ProductMeta:
    """未登记产品 → 400 + 可读原因（不静默降级，§22.6「未登记 = 不支持」）。"""
    if not str(product or "").strip():
        raise _ApiError(400, "缺少产品标识（product）")
    try:
        return account_registry.get(product)
    except KeyError as e:
        raise _ApiError(400, _message_of(e)) from None


def _product_module(product: str):
    """按产品 id 取产品模块（**只经注册表**，与 `accounts/login.py::_module` 同口径）。"""
    _product_meta(product)
    return importlib.import_module(f"model_gateway.upstream.{product}.product")


def _hook_table(product: str, table: str) -> dict:
    """取产品模块的钩子表（表缺项/未导出 → 400，不给字符串 `getattr` 后门）。"""
    hooks = getattr(_product_module(product), table, None)
    if not isinstance(hooks, dict):
        raise _ApiError(400, f"{product} 未导出 `{table}` 表（该产品不提供这类调用）")
    return hooks


def _hook(product: str, hook: str):
    """契约表现在取用点（refresh/probe/claim；与 `login.py::_hook` 同一纪律）。"""
    hooks = _hook_table(product, "_HOOKS")
    if hook not in hooks:
        raise _ApiError(400, f"{product} 未提供钩子 {hook!r}（契约表 `_HOOKS` 缺项）")
    return hooks[hook]


def _models_wired(product: str) -> bool:
    """模型目录接线面：`_HOOKS` 表是否提供可调用的 `list_models`（B-1 修复的按钮判据）。

    与 `account_models` 端点取用**同一张表**（单一事实源）——「按钮可见」等价于
    「端点可达」，未接线 = 前端不渲染（§22.6「未登记 = 不支持」，不出"点了必然失败"的钮）。
    ⚠️ `Capabilities`（§22.3 冻结面）没有目录位，故判据不能再从能力矩阵推导；本旗标在
    视图里现算，产品模块导入失败按未接线处理（fail closed，不把单产品异常打成整页 500）。
    """
    try:
        hooks = getattr(_product_module(product), "_HOOKS", None)
    except Exception:                    # noqa: BLE001 — 只读聚合，单产品模块异常不打死视图
        return False
    return isinstance(hooks, dict) and callable(hooks.get("list_models"))


def _require_account(product: str, name: str):
    """账号存在性校验（400/404 + 可读原因）；返回该产品的账号根。"""
    if not str(name or "").strip():
        raise _ApiError(400, "缺少账号名（name）")
    if store.sanitize_name(name) != name:
        raise _ApiError(400, f"账号名必须匹配 [A-Za-z0-9_-]{{1,32}}：{name!r}")
    root = store.product_root(product)
    if not store.has_account(root, name):
        raise _ApiError(404, f"账号不存在：{product}/{name}")
    return root


def _session_of(session_id: str):
    """会话 id → 会话对象（不存在 → None）。

    （2026-09-30 收口：公共层已补 `login.get_session(id)` 公开口——私有访问点已收敛。）
    """
    return login.get_session(str(session_id or "").strip())


def _require_session(product: str, session_id: str):
    """alt 必须拿到会话对象 → **对象不存在**（未知 id / 已被清理）404；
    对象在表但已过期/取消不在这里拦（由引擎 `_gate` 返回结构化 `expired`）。
    防串线：会话产品必须与请求一致。"""
    sid = str(session_id or "").strip()
    if not sid:
        raise _ApiError(400, "缺少会话 id（session）")
    session = _session_of(sid)
    if session is None:
        raise _ApiError(404, "会话不存在或已过期（请重新发起登录）")
    if session.product != product:
        raise _ApiError(400, f"会话与产品不匹配：会话属于 {session.product!r}，请求按 {product!r}")
    return session


async def _body(request: Request) -> dict:
    """读 JSON 请求体（空体/非对象 → `{}`；具体缺参由各端点给可读原因）。"""
    try:
        data = await request.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _outcome_payload(product: str, outcome: LoginOutcome, *, session=None,
                     with_challenge: bool = False) -> dict:
    """`LoginOutcome` → 入口响应（**凭据绝不回传**；成功时凭据已由引擎落盘，§22.3）。

    ⚠️ M7-C1 的 `with_challenge`（**只有 `login/poll` 用**）：扫码型产品在"上游判旧码作废"时
    会**就地换发一张新二维码**（把新 `Challenge` 写回 `session.challenge`，
    `upstream/{raccoon,loomy}/login.py::_reissue`），而换发动作发生在**轮询**这一步 ——
    所以轮询响应必须带回**当前** challenge，界面才换得出图（DSH 的本地页是同一条形状：
    `raccoon-login-page.ts:213-220` 在 poll 的 JSON 里回 `{qr: <新二维码>}`）。
    🔴 只回 `Challenge`（§22.3 定义就是"用户可见物"），会话私态与凭据一概不出。
    """
    payload = {
        "product": product,
        "account": getattr(session, "name", "") or "",
        "state": outcome.state,
        "detail": outcome.detail,
    }
    if with_challenge:
        challenge = getattr(session, "challenge", None) if session is not None else None
        payload["challenge"] = dataclasses.asdict(challenge) if challenge else {}
    return payload


# ---------- 账号启用位（§22.6 口径）----------

def _enabled_of(meta: dict) -> bool:
    """账号启用位：缺省 = 启用；只有本层写布尔值，非布尔一律按启用处理（不误伤旧数据）。"""
    raw = meta.get("enabled", True)
    return raw if isinstance(raw, bool) else True


def _account_enabled(product: str, name: str) -> bool:
    return _enabled_of(store.load_meta(store.product_root(product), name))


def cron_enabled_of(account: str) -> bool:
    """定时腿（cron）的 `enabled_of` 回调：账号名 → 启用位（设计书 §0-4 BUG-3 / §6 BD1）。

    🔴 **存在意义 = 让"账号停用：运营执行跳过"这句界面话对两条腿同时成立**：手动腿一直
    传 `enabled_of`（本文件 `account_claim`），cron 两条腿原先不传
    （`ops/runner.py:462-470`「给了才跳过」）→ 界面对用户撒了一个只对一半入口有效的谎。
    `main.py::_maybe_start_ops` 的两条腿都用本回调，语义与手动腿逐字同源（同一个
    `_account_enabled`，不另写一份判据）。

    ⚠️ **签名只能按账号名**（`run_once(enabled_of: Callable[[str], bool])`，运营报告行
    也**只带账号名**），产品归属必须在这里现推。取的是 `ops.runner.product_of_account`
    —— 与 `run_once` 自己的能力过滤（`runner.py:449-460`）**以及两个执行体**
    （`ops/builtin/product_claim.py:98`、`ops/builtin/query_balance.py:176`）**同一个函数**：
    「按 `PRODUCT_IDS` 顺序取第一个目录里有该名字的在册产品」。用同一个函数就是为了让
    "读的启用位"与"被操作的那个账号"是同一个——若在这里自创第二套归属口径，就会出现
    "读 A 产品的开关、跳 B 产品的账号"这种比不传更糟的错。

    🔴 **登记而非掩盖**（同名跨产品，设计书 §6 BD5 同一根因）：`all_accounts`
    （`runner.py:394-402`）先按名去重，所以同名账号里**只有首个在册产品那一个**会进
    参与方，本回调读的正是它的开关（一致）；代价是另一个同名账号的开关**永远不会被问**
    ——停用它不会让它从 cron 里消失，因为消失与否由"首个同名"决定。根修要把 `product`
    带进枚举与报告行（牵动 `ops/runner.py` 与落盘形态 = BD5），不在本轮三处后端前置的范围。

    读不动 / 认不出产品 → **按停用处理（跳过）并留日志**（§22.8-5 fail closed 同口径：
    "不知道"不得当成"可以动作"）。⚠️ 注意 `store.load_meta` 自身对损坏的 `meta.json`
    返回 `{}`（= 按启用），所以"损坏元信息被当成启用"这一条**界面与定时腿读的是同一个值**，
    本函数不制造分叉（要改该语义应改 `load_meta`/`_enabled_of`，两处同时跟着变）。
    """
    try:
        product = ops_runner.product_of_account(account)
    except Exception as e:  # noqa: BLE001 — 归属判据读不动 = 不知道，不据此发起运营
        logger.warning("运营跳过（启用位不可判）：账号归属推导失败 %r（%s: %s）",
                       account, type(e).__name__, e)
        return False
    if not product:
        logger.warning("运营跳过（启用位不可判）：认不出账号 %r 归属的产品", account)
        return False
    try:
        return _account_enabled(product, account)
    except Exception as e:  # noqa: BLE001 — 同上：读不动不得当成"可动作"
        logger.warning("运营跳过（启用位不可判）：%s/%s 的 meta 读取失败（%s: %s）",
                       product, account, type(e).__name__, e)
        return False


async def _set_enabled(product: str, name: str, enabled: bool) -> dict:
    """写账号 meta 的 `enabled` 位（§22.6：运营跳过停用 / 状态查询含停用 / 续期不看）。

    落盘经唯一入口 `store.commit_login` 的**异步版**（A-1 接线：本函数只被异步端点调用，
    等锁/写盘下放工作线程；写回自检 + 原子写语义逐字一致），凭据本体按现值原样回写、
    只新增/更新 `enabled` 位（**不触碰 runtime.json**，§22.2 不变式④）。
    ⚠️ 显式取舍：这会把当前 `credentials.json` 重写一次（zcode 等"整根隔离"账号会把
    空的 `{}` 落成文件）—— 换取的是"落盘唯一入口 + 写回自检"，不为此开 ad-hoc 写盘口。
    """
    root = _require_account(product, name)
    meta = store.load_meta(root, name)
    if _enabled_of(meta) == enabled:
        return {"status": "ok", "product": product, "account": name,
                "enabled": enabled, "changed": False}
    meta["enabled"] = enabled
    await store.commit_login_async(product, name,
                                   store.load_credentials(product, name, root=root), meta,
                                   root=root, via="admin")
    return {"status": "ok", "product": product, "account": name,
            "enabled": enabled, "changed": True}


# ---------- 视图（账号 / 能力矩阵）----------

def _matched_resources(config, product: str, name: str) -> list:
    """配置里「由该产品该账号供给」的 `Resource` 对象 —— **join 谓词的单一事实源**。

    判据与 `accounts/materialize.py::ensure_resource` 的幂等判据同一条尺
    （§22.5-2）：`Resource.product == product` 且 `account_ref == name`；
    `account_ref` 为空时**回退**读 `account`（Q18-② 的账号备注列，M6-5 物化写同一值），
    回退时"两边都空"不作为筛除条件（旧口径资源不得被判成"与本账号无关"）。

    🔴 返回**对象**而不是 id：调用方各自投影（额度摘要要 id、资源关联要 id+enabled），
    谓词只有一份，避免"两处 join 迟早分叉"。
    """
    out = []
    for r in getattr(config, "resources", None) or []:
        if str(getattr(r, "product", "") or "") != product:
            continue
        ref = str(getattr(r, "account_ref", "") or "") or str(getattr(r, "account", "") or "")
        if ref and ref != name:
            continue
        out.append(r)
    return out


def _resource_projection(runtime, product: str, name: str) -> "list[dict] | None":
    """BD3a（设计书 §6，本轮硬前置）：账号视图里的只读资源关联 = `[{id, enabled}]`。

    界面据此说得出「这个账号已物化成资源 res-xxx · 已启用/已停用」——原先只有
    `quota.resources`（id 列表，且运行态缺失时为 `[]`）而没有开关位，"接了却不在池里"
    与"在池里但被停用了"在界面上同形。

    三个刻意的形状选择：
    - **列表而不是单对象**：物化对同 `(product, account_ref)` 幂等（`ensure_resource`
      命中即复用），自动物化通常只有 1 条；但配置可由资源页手工再加同账号的资源，
      且设计书 §6 的文案就是「已物化 **N** 个资源」——单对象在 N>1 时只能撒谎（挑一条）。
      字段名沿用设计书的 `resource`（值为列表）。
    - **`None` = 配置读不动**（未知），**`[]` = 读到了且确实没有**：与「未知不当零」
      /「模型目录取不动返回 `unknown` 而不是空表」同一把尺（见本文件头 B-1 条款）。
    - **只投影 `id` + `enabled`**：🔴 `Resource` 上有 `api_key`（§22.5-2 产品资源是空串，
      但同表里按量 API 资源带明文 Key）—— 任何情况下**不得进本载荷**（铁律 1 / §22.8-8），
      所以这里用显式白名单投影，不做 `model_dump`。
    - 读失败不冒穿视图：与本函数邻居 `_account_entry` 的运行态读失败同一处置
      （fail closed + 留痕，`status`/视图照样返回，只是这一格降为"未知"）。
    """
    try:
        config = getattr(runtime, "config", None)
        if config is None:
            return None                     # 没有运行态 = 不知道（不是"没有资源"）
        return [{"id": r.id, "enabled": bool(r.enabled)}
                for r in _matched_resources(config, product, name)]
    except Exception as e:  # noqa: BLE001 — 配置读不动不得拖垮账号视图（§22.8-5）
        logger.warning("资源关联读不动（%s/%s → 记为未知，不影响视图）：%s: %s",
                       product, name, type(e).__name__, e)
        return None


def _unknown_quota_summary() -> dict:
    """额度摘要的**中性值**（未知不当零，§22.3）：读不到/没有池时一律这个形状。"""
    return {"state": "unknown", "remaining": None, "reserved": 0,
            "resources": [], "per_resource": {}}


def _quota_summary(runtime, product: str, name: str) -> dict:
    """额度缓存摘要（§22.5-6：余额快照由 ops tick 刷新后 `set_quota`，选路只读）。

    数据源 = 运行态的**资源额度池**（`runtime.resources.quotas[rid]`），按物化资源
    （`Resource.product` + `account_ref`，M6-5）关联本账号（join 谓词 =
    `_matched_resources`，与 BD3a 的 `resource` 字段同源）；`account_ref` 缺席时回退
    读 `Resource.account`（Q18-② 的账号备注列，M6-5 物化写同一值）。
    没有运行态/没有关联资源 → `unknown`（**未知不当零**，§22.3）。
    账号级 `state` 是**摘要**：任一池有余量 → `available`；全部已知且耗尽 → `exhausted`；
    一个都不已知 → `unknown`；逐资源明细在 `per_resource`（真相在那里）。

    ⚠️ 本函数**不吞异常**：读不动的处置在调用点（`_account_entry` 经
    `_quota_summary_or_unknown` 包一层 fail-closed），以保持本函数可被直接单测断言。
    """
    summary = _unknown_quota_summary()
    config = getattr(runtime, "config", None)
    manager = getattr(runtime, "resources", None)
    if config is None or manager is None:
        return summary
    rids: list[str] = [r.id for r in _matched_resources(config, product, name)]
    pools = getattr(manager, "quotas", None) or {}
    known_any = False
    has_room = False
    remaining_min = None
    reserved_total = 0
    for rid in rids:
        pool = pools.get(rid)
        remaining = getattr(pool, "remaining", None) if pool is not None else None
        reserved = int(getattr(pool, "reserved", 0) or 0) if pool is not None else 0
        reserved_total += reserved
        summary["per_resource"][rid] = {"remaining": remaining, "reserved": reserved}
        if remaining is None:
            continue
        known_any = True
        if (remaining - reserved) > 0:
            has_room = True
        remaining_min = remaining if remaining_min is None else min(remaining_min, remaining)
    summary["resources"] = rids
    summary["reserved"] = reserved_total
    summary["remaining"] = remaining_min
    if known_any:
        summary["state"] = "available" if has_room else "exhausted"
    return summary


def _quota_summary_or_unknown(runtime, product: str, name: str) -> dict:
    """`_quota_summary` 的**视图侧 fail-closed 包装**（BD3a 同一条纪律）。

    配置/额度池读不动时按中性值呈现（`state:"unknown"`，**未知不当零**），而不是把整个
    `GET /admin/api/accounts` 冒穿成 500：本视图是"账号还在不在、额度还有没有"的
    唯一可见出口，一格读不动不该让它整体看不见（与邻居的运行态读失败同一处置，
    §22.8-5）。留日志 = 不留哑故障。
    """
    try:
        return _quota_summary(runtime, product, name)
    except Exception as e:  # noqa: BLE001 — 读不动不得冒穿账号视图
        logger.warning("额度摘要读不动（%s/%s → 按未知呈现，不影响视图）：%s: %s",
                       product, name, type(e).__name__, e)
        return _unknown_quota_summary()


def _account_entry(product: str, name: str, *, root, runtime) -> dict:
    """单个账号的视图条目（设备字段 / 运行态摘要 / 额度缓存摘要 / 资源关联；**无凭据**）。

    🔴 载荷白名单就是本 `return` 的键本身：`resource` 只出 `{id, enabled}`
    （BD3a，见 `_resource_projection`），`display` 走 `_META_DISPLAY_KEYS` 白名单，
    `runtime` 是额度/冷却快照 —— `credentials.json` 与任何 `api_key` 都不在本函数的读面里。
    """
    meta = store.load_meta(root, name)
    enabled = _enabled_of(meta)
    runtime_ok = True
    runtime_error = ""
    snapshot: dict = {}
    try:
        snapshot = store.read_runtime(product, name, root=root)
    except store.RuntimeUnreadable as e:
        # §22.8-5 fail closed：状态文件读不动**不得**呈现为健康（status → unknown）
        runtime_ok, runtime_error = False, str(e)
    spec = account_registry.get(product).device
    device = {f: meta[f] for f in spec.fields
              if isinstance(meta.get(f), str) and meta.get(f)}
    return {
        "name": name,
        "enabled": enabled,
        "status": "disabled" if not enabled else ("unknown" if not runtime_ok else "active"),
        "device": device,
        "display": {k: meta[k] for k in _META_DISPLAY_KEYS if k in meta},
        "runtime": snapshot,
        "runtime_ok": runtime_ok,
        "runtime_error": runtime_error,
        "quota": _quota_summary_or_unknown(runtime, product, name),
        # BD3a（设计书 §6 硬前置）：该账号已物化成的资源（`[{id, enabled}]`；
        # None = 配置读不动 = 未知，[] = 确实没有）。界面据此说"已物化 N 个资源 · 启用/停用"。
        "resource": _resource_projection(runtime, product, name),
    }


@router.get("/admin/api/accounts")
async def accounts_view(request: Request):
    """全产品账号视图（§22.7）：产品元信息 + 账号列表（含已停用）+ 运行态/额度缓存摘要。"""
    runtime = getattr(request.app.state, "runtime", None)
    products = []
    account_count = enabled_count = 0
    for pid in account_registry.PRODUCT_IDS:
        meta = account_registry.PRODUCTS[pid]
        root = store.product_root(pid)
        entries = [_account_entry(pid, name, root=root, runtime=runtime)
                   for name in store.list_accounts(pid, root=root)]
        account_count += len(entries)
        enabled_count += sum(1 for e in entries if e["enabled"])
        products.append({**dataclasses.asdict(meta), "models_wired": _models_wired(pid),
                         "accounts": entries})
    return {
        "products": products,
        "counts": {"products": len(products), "accounts": account_count,
                   "enabled": enabled_count, "disabled": account_count - enabled_count},
    }


@router.get("/admin/api/accounts/capabilities")
async def capabilities_matrix():
    """能力矩阵（§22.7）：与 `registry.registry` 同源（`dataclasses.asdict`）——

    前端按钮**数据驱动**（§22.6：未登记 = 不渲染；「点了必然失败」的按钮一个都不出）。
    """
    return {"products": [
        dataclasses.asdict(account_registry.PRODUCTS[pid])
        for pid in account_registry.PRODUCT_IDS
    ]}


# ---------- 一键领取（全局 / 单产品批量；显式字面量路由）----------

@router.post("/admin/api/accounts/claim-all")
@_endpoint
async def accounts_claim_all(request: Request):
    """一键领取：`product` 给定 = 该产品批量；`product` 缺省 = **全局跨产品**。

    逐条语义（与单账号 `claim` 同源，全部经 `ops.runner`，§16.4）：

    - **执行体** = `ops.builtin.product_claim.claim`（多产品执行体：zcode 直连分支 +
      能力位第二道守卫都在它里面，与 CLI / cron **同一函数对象**）—— 本层只加"逐账号
      收集 `OpResult`"的外壳（响应 `details`），**不加调度、不加锁、不并发**（互斥/退避/
      四类归类全在 `run_once` 既有实现里）；
    - **参与方**：给定产品 → 该产品全部账号（停用账号由 `enabled_of` 过滤成 `skipped`，
      与单账号 claim **同一个** `_account_enabled` 判据，§22.6「运营执行跳过停用」）；
      缺省 → 动作声明面（`_CLAIM_OP.supported_products` 经 `ops_runner.all_accounts`
      枚举 —— 与 `run_once(accounts=None, operation=…)` 内部那一行**同一函数**，
      单一事实源；`checkin=False` 的产品（workbuddy/cline/raccoon）天然不进名单）。
      🔴 全局腿显式枚举而不再传 `accounts=None`：只为让响应里的 `participants` 说得出来
      （同一函数、同一顺序、同一去重，行为逐字一致）；
    - **能力位前置拒绝**（给定产品）：`checkin=False` → 400 + 可读原因，**不发起任何动作**
      （§22.6「能力矩阵是判据不是标签」：这些产品没有可调用的签到端点；界面本就不该
      渲染按钮，端点也不为越权调用放行）；
    - **结果出口**：`report`（四类分开）+ `ops-results-<date>.jsonl` 落盘（顶栏红点同源），
      与单账号端点逐字同一条链（`ops_runner.write_report`）；`details` 是"钩子原话"
      （`OpReport` 对 success/already_done 只存账号名，单账号端点用同款 `captured` 补回）。
    """
    body = await _body(request)
    product = str(body.get("product") or "").strip()
    runtime = getattr(request.app.state, "runtime", None)
    if product:
        meta = _product_meta(product)
        if not meta.capabilities.checkin:
            raise _ApiError(
                400, f"该产品无签到能力（能力位 checkin=False）：{meta.title} "
                     "没有可调用的签到端点（`20 §3.1` 逐产品清点），不发起任何动作")
        accounts: list[str] = store.list_accounts(product, root=store.product_root(product))
        enabled_of = functools.partial(_account_enabled, product)
    else:
        accounts = ops_runner.all_accounts(_CLAIM_OP.supported_products)
        # 全局腿的启用位判据 = cron 腿同款（`cron_enabled_of`：先推账号归属、再读
        # 与被操作账号**同一个**启用位；读不动按停用跳过，fail closed）
        enabled_of = cron_enabled_of

    details: dict[str, dict] = {}

    async def _claim_once(account: str, *, manual: bool = False, runtime=None) -> OpResult:
        """`run_once` 的 `ClaimFn` 约定（形参名与 ops 的调用点逐字一致；`manual` 对
        管理端无意义但原样透传）。每次返回的 `OpResult` 都进 `details` —— 重试场景下
        最后一次覆盖前次，与 `report` 里的最终归类一致。"""
        result = await product_claim_op.claim(account, manual=manual, runtime=runtime)
        details[account] = {"category": result.category, "detail": result.detail}
        return result

    report = await ops_runner.run_once(
        accounts=accounts, enabled_of=enabled_of, claim=_claim_once,
        operation=_CLAIM_OP, runtime=runtime, delay_s=0.0, jitter=False)
    written = ops_runner.write_report(report, getattr(runtime, "usage_dir", None))
    return {
        "product": product or None,
        #: 参与**候选**（送入执行器的名单；停用/能力过滤结果见 report.skipped 与
        #: details 的键集 —— 只有真正发起过的账号才会进 details）
        "participants": list(accounts),
        "report": report.to_dict(),
        "details": details,
        "written": written is not None,
    }


# ---------- 登录会话（§22.7 四端点，委托 `accounts/login.py`）----------

@router.post("/admin/api/accounts/login/start")
@_endpoint
async def login_start(request: Request):
    """启动登录：定形态（缺省主形态）→ 建会话 → 产品 `login_start` → `Challenge`。

    🔴 只回传**用户可见物**（`Challenge`，§22.3）；钩子的私有会话态留在会话里，绝不回显。
    """
    body = await _body(request)
    product = str(body.get("product") or "").strip()
    _product_meta(product)
    kind = str(body.get("kind") or "").strip() or None
    name = str(body.get("name") or "").strip()
    session = await login.start_login(product, name=name, kind=kind)
    return {"session": session.id, "product": product, "account": session.name,
            "kind": session.kind, "ttl_s": session.ttl_s,
            "challenge": dataclasses.asdict(session.challenge) if session.challenge else {}}


@router.post("/admin/api/accounts/login/poll")
@_endpoint
async def login_poll(request: Request):
    """轮询登录状态（`pending` 是正常业务状态，§22.3；会话不存在 → `expired` 状态）。

    🔴 响应**带回当前 `challenge`**（M7-C1）：扫码型产品在上游判旧码作废时会就地换发一张
    新二维码（新图在 `session.challenge.qr_payload`），界面靠这一次轮询就能看到新图并换图，
    不再要用户手动点「重新发起登录」。未换发时 challenge 与 `login/start` 给的逐字节相同，
    前端比对后不重绘（`web/static/js/pages/accounts.js::applyChallenge`）。
    """
    body = await _body(request)
    product = str(body.get("product") or "").strip()
    _product_meta(product)
    sid = str(body.get("session") or "").strip()
    session = _session_of(sid)
    if session is not None and session.product != product:
        raise _ApiError(400, f"会话与产品不匹配：会话属于 {session.product!r}，请求按 {product!r}")
    outcome = await login.poll_login(product, sid)
    return _outcome_payload(product, outcome, session=session, with_challenge=True)


@router.post("/admin/api/accounts/login/callback")
@_endpoint
async def login_callback(request: Request):
    """回跳粘贴（local_callback 型：trae / lobsterai）。

    载荷 `{"product", "session", "params": {...}}`；也接受把回跳参数平铺在顶层
    （`url` / `code` / `state` …）—— 两形态合并后原样交给产品钩子（入口层不解释内容）。
    """
    body = await _body(request)
    product = str(body.get("product") or "").strip()
    _product_meta(product)
    sid = str(body.get("session") or "").strip()
    params = body.get("params")
    if not isinstance(params, dict):
        params = {k: v for k, v in body.items()
                  if k not in ("product", "session", "params")}
    session = _session_of(sid)
    if session is not None and session.product != product:
        raise _ApiError(400, f"会话与产品不匹配：会话属于 {session.product!r}，请求按 {product!r}")
    outcome = await login.callback_login(product, sid, params)
    return _outcome_payload(product, outcome, session=session)


@router.post("/admin/api/accounts/login/commit")
@_endpoint
async def login_commit(request: Request):
    """确认接入（两阶段提交第二段，M7-E）：把会话上暂存的凭据经唯一落盘入口写入账号目录。

    载荷 `{"session"}`，可选 `{"product"}` 做串线校验（与 poll/callback/cancel 同一判据）。

    🔴 **永不 404**（与 `login_cancel` 同一幂等纪律）：未知/已过期/已取消的会话 →
    HTTP 200 `{"committed": false, "account": …, "reason": …}`；此前已确认过 → 
    `{"committed": true, "account": <名>}`（幂等，**不二次写盘**）。
    落盘自检失败 / 写盘锁拒写 → `{"committed": false, "reason": <真实原因>}`（**不谎报成功**）。
    契约：`login.start_login` 的 `success` 只表示"凭据已认领暂存"，本端点才是落盘开关。
    """
    body = await _body(request)
    sid = str(body.get("session") or "").strip()
    product = str(body.get("product") or "").strip()
    if product:
        _product_meta(product)
        session = _session_of(sid)
        if session is not None and session.product != product:
            raise _ApiError(400, f"会话与产品不匹配：会话属于 {session.product!r}，请求按 {product!r}")
    return JSONResponse(await login.commit_pending(sid))


@router.post("/admin/api/accounts/login/cancel")
@_endpoint
async def login_cancel(request: Request):
    """取消登录会话（BD2，设计书 §6）：出表 + **关闭其回跳接收端** + **丢弃暂存凭据**。

    🔴 两阶段提交（M7-E）：登录已成功但未点「确定接入」时取消 → 账号目录**不会**
    留下任何东西（这正是确认步的意义；`_drop` 一并做）。

    载荷 `{"session"}`，可选 `{"product"}` 做串线校验（与 poll/callback 同一判据）。

    🔴 **幂等，不报 404**：会话可能已经被 settle/超时/TTL 清掉了 —— 用户点"取消"
    和上游回跳到达本来就是竞态关系，把"已经不需要取消了"呈现成一次失败，
    等于让用户以为界面坏了。这里统一回 `{"cancelled": bool}`：`false` = 会话早已不在，
    **不是错误**（`accounts.js` 据此无条件关窗）。
    """
    body = await _body(request)
    sid = str(body.get("session") or "").strip()
    product = str(body.get("product") or "").strip()
    if product:
        _product_meta(product)
        session = _session_of(sid)
        if session is not None and session.product != product:
            raise _ApiError(400, f"会话与产品不匹配：会话属于 {session.product!r}，请求按 {product!r}")
    return JSONResponse({"cancelled": login.cancel_login(sid)})


@router.post("/admin/api/accounts/login/alt")
@_endpoint
async def login_alt(request: Request):
    """备选登录形态的辅助调用（§22.3 补入③）：如短信两段 `sms_send` / `sms_submit`。

    载荷 `{product, session, name, args}`；结果两形态（产品面的既定差异，都在 `kind` 上标明）：
    `Challenge`（raccoon `sms_send`）或 `LoginOutcome`（loomy 两段 / raccoon `sms_submit`）。
    🔴 第二段成功时**只认领暂存、不落盘**（M7-E 两阶段提交：`login.alt_call` 的
    `_stage_pending` 路径）—— 落盘统一由用户点「确定接入」（`login/commit`）触发，
    五型登录共用同一次确认。
    """
    body = await _body(request)
    product = str(body.get("product") or "").strip()
    hook_name = str(body.get("name") or "").strip()
    if not hook_name:
        raise _ApiError(400, "缺少辅助调用名（name，如 sms_send / sms_submit）")
    alt_hooks = _hook_table(product, "_ALT_HOOKS")
    if hook_name not in alt_hooks:
        legal = "、".join(sorted(alt_hooks)) or "（空表）"
        raise _ApiError(400, f"{product} 的 `_ALT_HOOKS` 无 {hook_name!r}（合法值：{legal}）")
    args = body.get("args")
    if not isinstance(args, dict):
        raise _ApiError(400, "args 必须是对象（钩子 kwargs，如 {\"phone\": \"…\"}）")
    session = _require_session(product, str(body.get("session") or ""))
    result = await login.alt_call(product, session, hook_name, **args)
    if isinstance(result, Challenge):
        return {"product": product, "account": session.name, "kind": "challenge",
                "challenge": dataclasses.asdict(result)}
    if isinstance(result, LoginOutcome):
        return {"kind": "outcome", **_outcome_payload(product, result, session=session)}
    raise _ApiError(502, f"辅助调用返回值类型异常：{type(result).__name__}")


# ---------- 外部凭据导入 ----------

@router.post("/admin/api/accounts/import")
@_endpoint
async def accounts_import(request: Request):
    """外部凭据导入（§22.7 / `22 §5.7`）：`store.import_account_async` 的白名单 + 自检回滚
    （A-1：等锁/写盘下放工作线程；语义与同步版逐字一致）。

    载荷（源**只读**，绝不改写）：`payload`（粘贴的 JSON 对象）或 `path`（本机文件路径）二选一。
    设备身份冲突 → **409 拒绝 + 交用户决策**（带冲突账号与两条出路 `reuse` / `regenerate`），
    绝不静默覆盖（§15.1 硬约束 3）。
    """
    body = await _body(request)
    product = str(body.get("product") or "").strip()
    _product_meta(product)                       # 未登记产品：先拒，不落任何盘
    payload = body.get("payload")
    path = str(body.get("path") or "").strip() or None
    if payload is None and not path:
        raise _ApiError(400, "缺少导入源：payload（JSON 对象）或 path（本机文件）二者之一")
    if payload is not None and not isinstance(payload, dict):
        raise _ApiError(400, "payload 必须是 JSON 对象")
    result = await store.import_account_async(
        product, path,
        payload=payload if isinstance(payload, dict) else None,
        name=str(body.get("name") or "").strip(),
        device_id=str(body.get("device_id") or "").strip(),
        reuse=(str(body.get("reuse") or "").strip() or None),
        regenerate=bool(body.get("regenerate")))
    if result.ok:
        return {"status": "ok", "product": product, "account": result.account,
                "device_id": result.device_id, "device_values": list(result.device_values),
                "message": result.message}
    if result.conflict:
        raise _ApiError(409, result.message, conflict=True,
                        conflict_with=result.conflict_with, account=result.account,
                        hint="设备身份与既有账号冲突：带 reuse=<账号名> 复用其身份，"
                             "或带 regenerate=true 重新生成（拒绝 + 交用户决策，不静默覆盖）")
    raise _ApiError(400, result.message)


# ---------- 单账号操作（claim / refresh / probe / enable / disable / delete）----------

def _single_category(report: OpReport, account: str, *, enabled: bool = True) -> tuple[str, str]:
    """从 ops 报告里取回该账号的**主类别**（前端状态点渲染用；报告本体照常全量返回）。

    `skipped` 有两种成因，**必须分开说**（禁止谎报）：① 账号被停用（§22.6 运营跳过）；
    ② 账号级互斥未取到（另一入口正在对该账号执行，§16.4 双层互斥）—— 二者都属"本次未发起"，
    但原因不同，给用户的话也必须不同（把 ② 说成 ① 会让用户白去查停用位）。
    """
    for acc, reason in report.failed:
        if acc == account:
            return "failed", reason
    if account in report.inactive:
        return "inactive", report.inactive_reasons.get(account, "")
    if account in report.already_done:
        return "already_done", ""
    if account in report.success:
        return "success", ""
    if account in report.skipped or report.no_participants:
        if not enabled:
            return "inactive", ("账号已停用（enabled=false）：运营执行跳过停用账号（§22.6）；"
                                "续期不受该位影响")
        return "inactive", ("账号级互斥未取得：另一入口（CLI / 定时任务）正在对该账号执行，"
                            "本次未发起（§16.4 双层互斥，不并发双领）")
    return "inactive", ""


@router.post("/admin/api/accounts/{product}/{name}/claim")
@_endpoint
async def account_claim(request: Request, product: str, name: str):
    """签到/领取（§22.7）：**复用 ops 四类结果出口** —— 加锁、网络退避重试、四类归类、
    `ops-results-*.jsonl` 落盘（顶栏红点同源）全部走 `ops.runner` 既有实现，不另起一套。

    §22.6 口径：**停用账号被跳过**（`enabled_of` 过滤 → `inactive`，且不发产品钩子）。
    """
    _product_meta(product)
    _require_account(product, name)
    runtime = getattr(request.app.state, "runtime", None)
    precheck = bool(_PRECHECK.get(product, False))
    #: 钩子返回的原始原因（`OpReport` 对 success/already_done **只存账号名**，
    #: 钩子的话（如"已领取 +100"）会被丢掉 —— 单账号响应从这里补回 detail；
    #: 报告本体（`report`）仍按 ops 的原样形态返回，两边不互相迁就）。
    captured: dict[str, OpResult] = {}

    async def _claim_once(account: str, *, manual: bool = False, runtime=None) -> OpResult:
        """单账号一次领取（形参按 ops 的 `ClaimFn` 约定；**凭据解析在 try 内**，§22.8-6）。"""
        del manual, runtime          # 本层不做验证码人工路径；运行时经闭包外绑定
        try:
            cred = store.load_credentials(product, account)
            hook_meta = store.hook_meta(product, account)
        except Exception as e:       # noqa: BLE001 — 单账号异常隔离，不中断批量
            result = OpResult(account, "failed", f"{type(e).__name__}: {e}")
        else:
            outcome = await _hook(product, "claim")(cred, hook_meta, precheck=precheck)
            # `ClaimOutcome → OpResult` = 修复-2 的单一事实源（eng-a A-5 双账收敛；
            # 归一化规则住 `ops/bridge.py`，本层不再自带一份：非 failed 归 `retryable=None`、
            # 非 `ClaimOutcome` 一律 `failed`，两处消费点（本处 + `ops/builtin/product_claim.py`）同源）。
            result = outcome_to_op_result(outcome, account)
        captured[account] = result
        return result

    report = await ops_runner.run_once(
        accounts=[name],
        enabled_of=lambda a: _account_enabled(product, a),
        claim=_claim_once,
        runtime=runtime,
        delay_s=0.0, jitter=False)
    written = ops_runner.write_report(report, getattr(runtime, "usage_dir", None))
    category, detail = _single_category(report, name,
                                        enabled=_account_enabled(product, name))
    if not detail and name in captured:
        detail = captured[name].detail
    return {"product": product, "account": name, "category": category, "detail": detail,
            "precheck": precheck, "report": report.to_dict(), "written": written is not None}


@router.post("/admin/api/accounts/{product}/{name}/refresh")
@_endpoint
async def account_refresh(request: Request, product: str, name: str):
    """凭据续期（§22.3）：`refresh` 钩子返回**新凭据本体** → `store.commit_login_async` 落盘
    （A-1：等锁/写盘下放工作线程；写回自检语义不变）。

    - **不看 enabled**（§22.6：续期与停用位正交）；
    - `NotRefreshable` → 409「不可续期」（由 `_endpoint` 统一出口，不是 500）；
    - 空返回值**不覆盖**旧凭据（"不写回空令牌"纪律，返回 502）。
    """
    _product_meta(product)
    _require_account(product, name)
    cred = store.load_credentials(product, name)
    meta = store.hook_meta(product, name)        # §22.3 补入①：锚字段唯一组装入口
    new_cred = await _hook(product, "refresh")(cred, meta)
    if not isinstance(new_cred, dict) or not new_cred:
        raise _ApiError(502, "续期未返回新凭据（不覆盖旧凭据）")
    await store.commit_login_async(product, name, new_cred, {}, via="refresh")
    return {"status": "ok", "product": product, "account": name,
            "message": "凭据已续期并落盘"}


@router.post("/admin/api/accounts/{product}/{name}/probe")
@_endpoint
async def account_probe(request: Request, product: str, name: str):
    """探活（§22.3）：连通 / 凭据有效**两维分开**返回（`ok` = 两维皆真）。"""
    _product_meta(product)
    _require_account(product, name)
    cred = store.load_credentials(product, name)
    meta = store.hook_meta(product, name)
    result = await _hook(product, "probe")(cred, meta)
    if not isinstance(result, ProbeResult):
        raise _ApiError(502, f"探活钩子返回值类型异常：{type(result).__name__}")
    return {"product": product, "account": name,
            "reachable": result.reachable, "valid": result.valid,
            "ok": result.ok, "detail": result.detail}


# ---------- 模型目录（§22.0 交付面；B-1 生产出口）----------

@router.get("/admin/api/accounts/{product}/{name}/models")
@_endpoint
async def account_models(product: str, name: str):
    """产品模型目录：调该产品 `list_models(cred, hook_meta)`，返回 `{state, source, models[]}`。

    - **生产出口**（M6 面板 B-1 修复）：此前 10 产品的 `list_models` 全部实现但**零消费者**；
      本端点与「接入账号资源」页的「模型目录」入口是该钩子的第一组真实出口（标准与 R1-F6 为
      `quota` 补的 `query_balance` 出口一致）；
    - 数据源 = 产品钩子真实执行结果（远端失败由产品层按各自纪律回退/如实上报），
      `source` 取注册表 `ProductMeta.models_source`（目录来源形态）——**本层不编造任何条目**；
    - **取不动 → `state:"unknown"` + `reason`**（HTTP 200，空 `models`）：「读不到」与
      「真的为空」分开（与「未知不当零」/ 运行态 `status:"unknown"` 同口径），前端只展示原因；
    - 钩子未接线（`_HOOKS` 缺 `list_models`）→ 400 + 可读原因（§22.6「未登记 = 不支持」）；
      钩子返回值类型不符契约（非 `list[ModelInfo]`）→ 502 + 可读原因（编程错误不静默）；
    - 🔴 **永不回传凭据**（§22.7 硬约束）：响应只含模型元信息 / 来源 / 原因文案三面，
      `cred` 与 `hook_meta`（含账号目录）只在本进程内传给钩子。`reason` 面 = 产品层异常
      文案（与既有 502 出口同一口径）；产品钩子不得把凭据拼进异常文案（§22.2 不变式②）。
    """
    meta = _product_meta(product)                     # 未登记产品 → 400
    _require_account(product, name)                   # 账号不存在 → 404
    hook = _hook(product, "list_models")              # 未接线 → 400（先拒，不落任何调用）
    cred = store.load_credentials(product, name)
    hook_meta = store.hook_meta(product, name)
    payload = {"product": product, "account": name, "source": meta.models_source}
    try:
        models = await hook(cred, hook_meta)
    except Exception as e:                            # noqa: BLE001 — 取不动 = 数据态（见 docstring）
        logger.warning("模型目录取不动：%s/%s：%s", product, name, e)
        return {**payload, "state": "unknown", "models": [],
                "reason": f"{type(e).__name__}: {e}"}
    if not isinstance(models, list):
        raise _ApiError(502, f"模型目录钩子返回值类型异常：{type(models).__name__}"
                             "（期望 list[ModelInfo]）")
    for m in models:
        if not isinstance(m, ModelInfo):
            raise _ApiError(502, f"模型目录条目类型异常：{type(m).__name__}（期望 ModelInfo）")
    return {**payload, "state": "ok", "models": [dataclasses.asdict(m) for m in models]}


# ---------- 模型映射：产品级目录（弹窗数据面）----------

#: `EnumPool.match` 的三级置信度 → `via` 字面量（置信度是池子的返回值，本层不二次猜测）。
_VIA_BY_CONF = {1.0: "exact", 0.9: "alias", 0.7: "normalized"}

#: 兜底目录的 `source`（无可用账号 / 远端目录不可用时；文案逐字定稿）。
_FALLBACK_SOURCE = {"kind": "fallback", "account": "",
                    "detail": "内置兜底目录（无可用账号或远端目录不可用）"}


def _enum_suggest(pool, cfg_names: set[str], mid: str) -> dict | None:
    """目录条目 → 网关系统模型的**建议映射**（映射弹窗里的一键带出；服务端解析的读侧）。

    算法（三级匹配 + 首段前缀剥离）：
    ① `pool.match(mid)` 直接命中（精确 1.0 / 别名 0.9 / 规范化 0.7，`via` 由置信度映射）；
    ② 未命中且 `mid` 含 `-` → 剥**第一段**再匹配（厂商前缀形态：`sn-glm-5-3` → `glm-5-3`）
       → `via="prefix"`、置信度 = min(命中值, 0.7)（前缀剥离是启发式，不冒充直配）；
    ③ 仍未命中 → `None`（**不编造建议**）。
    仅当规范名**可落地**（已是现有系统模型，或枚举池条目可即时创建）才给出 ——
    建议必须能一键变成配置，否则前端只能画一个"点了必然失败"的钮（§22.6 同口径）。
    """
    if pool is None or not mid:
        return None
    canonical, conf = pool.match(mid)
    via = _VIA_BY_CONF.get(conf)
    if canonical is None and "-" in mid:
        canonical, conf = pool.match(mid.split("-", 1)[1])
        if canonical is not None:
            via, conf = "prefix", min(conf, 0.7)
    if not canonical or via is None:
        return None
    if canonical in cfg_names or pool.get(canonical) is not None:
        return {"name": canonical, "confidence": round(float(conf), 2), "via": via}
    return None


def _mapped_to(cfg, product_rids: set[str], mid: str) -> list[str]:
    """该条目已挂上的系统模型名（映射条目 `resource ∈ 本产品资源` 且 `model == mid`）。

    扫**生效配置**（`runtime.config`）——与「初始化映射」的去重判据同源
    （(resource, model) 组合不重复挂载）。弹窗据此把已映射条目显示为"已挂到 X"。
    """
    out: list[str] = []
    for m in getattr(cfg, "models", None) or []:
        if any(e.resource in product_rids and e.model == mid for e in m.resources):
            out.append(m.name)
    return out


def _catalog_accounts(runtime, product: str) -> list[dict]:
    """映射弹窗的账号列：**全部账号（含停用）**，`{name, enabled, resource_id}`。

    - 顺序 = `store.list_accounts`（目录名排序 = 与账号视图同一枚举点）；
      `enabled` 与运营跳过同源（`_account_enabled`）；
    - `resource_id` 取 `_matched_resources`（product + account_ref 的**单一 join 谓词**，
      与账号视图/额度摘要同尺）；同账号有多条资源时取**首条**（弹窗只需要一个可展示的
      落点；"已物化 N 个"的完整清单在账号视图的 `resource` 字段里）；
    - 🔴 `"" = 尚未物化`：本端点**不物化**（物化是「初始化映射」提交步骤的事）——
      读端点永不产生写盘副作用。
    """
    cfg = getattr(runtime, "config", None)
    root = store.product_root(product)
    out = []
    for name in store.list_accounts(product, root=root):
        rid = ""
        if cfg is not None:
            matched = _matched_resources(cfg, product, name)
            rid = matched[0].id if matched else ""
        out.append({"name": name, "enabled": _account_enabled(product, name),
                    "resource_id": rid})
    return out


async def _catalog_models(hook, product: str, account_infos: list[dict]) -> tuple[list, dict, str]:
    """目录选源 → `(models, source, reason)`（reason 仅在兜底腿也取不动时非空）。

    ① **账号实时目录**：按存储序找第一个**已启用**账号，其 `list_models(cred, hook_meta)`
       返回非空 `list[ModelInfo]` 即用（`source.kind="account"`）——
       单账号取不动 / 空表 / 形态不符 → 记日志换下一个（不静默、不中断）；
    ② **内置兜底**：无可用账号或全部为空 → 以**空凭据 `{}`** 调同一钩子（10 产品的钩子
       对空凭据都回内置目录，逐产品在
       `tests/integration/test_accounts_catalog_mapping_api.py` 里钉死）；
       抛错 / 形态不符 → `models=[]` + `reason`（「读不到」与「真的为空」分开，
       与 B-1 的 `state:"unknown"` 同口径 —— 本层不编造任何条目）。

    `source` 说清这份目录**来自哪**：界面照实展示，不把兜底表冒充成"实时目录"。
    """
    root = store.product_root(product)
    for info in account_infos:
        if not info["enabled"]:
            continue
        name = info["name"]
        try:
            cred = store.load_credentials(product, name, root=root)
            hook_meta = store.hook_meta(product, name, root=root)
            models = await hook(cred, hook_meta)
        except Exception as e:  # noqa: BLE001 — 单账号取不动 → 试下一个（留痕，不静默）
            logger.warning("模型目录取源跳过：%s/%s：%s: %s",
                           product, name, type(e).__name__, e)
            continue
        if isinstance(models, list) and models and all(isinstance(m, ModelInfo) for m in models):
            return (models,
                    {"kind": "account", "account": name,
                     "detail": f"来自账号 {name} 的实时目录"},
                    "")
        logger.warning("模型目录取源跳过：%s/%s 返回空表或形态异常（%s）",
                       product, name, type(models).__name__)
    fallback = dict(_FALLBACK_SOURCE)
    try:
        models = await hook({}, {})
    except Exception as e:  # noqa: BLE001 — 兜底也取不动 → 空表 + 原因（不编造，不 5xx）
        logger.warning("内置兜底目录取不动：%s：%s: %s", product, type(e).__name__, e)
        return [], fallback, f"{type(e).__name__}: {e}"
    if isinstance(models, list) and all(isinstance(m, ModelInfo) for m in models):
        return models, fallback, ""
    reason = f"模型目录钩子返回值类型异常：{type(models).__name__}（期望 list[ModelInfo]）"
    logger.warning("内置兜底目录形态异常：%s：%s", product, reason)
    return [], fallback, reason


@router.get("/admin/api/accounts/{product}/catalog")
@_endpoint
async def account_catalog(request: Request, product: str):
    """产品级模型目录（「模型映射」弹窗的数据面；产品维度而非账号维度）。

    与 `GET /admin/api/accounts/{product}/{name}/models` 的关系：那条是**单账号**的
    目录出口（B-1 生产出口）；本端点是**产品级**选源聚合 —— 映射弹窗要在"还没有账号"
    时也画得出目录（先看目录、勾选目标模型，再接入账号），所以保留空凭据兜底腿。

    响应：
    - `source`：`{kind: account|fallback, account, detail}`（见 `_catalog_models`）；
    - `models[]`：`asdict(ModelInfo)` 逐字段（**字段随冻结类型演进，不硬编码字段表**；
      目录条目扩展 `free`/`rate` 等字段时自动带出）+ `suggest`（枚举池建议，见
      `_enum_suggest`）+ `mapped_to`（已挂上的系统模型名，见 `_mapped_to`）；
    - `accounts[]`：`{name, enabled, resource_id}`（`resource_id` 空串 = 尚未物化；
      **本端点不物化**）；
    - `checkin`：能力位（弹窗据此决定是否显示签到入口）。
    兜底腿也取不动时附 `reason`（HTTP 200 + 空 `models`，不编造条目；同 §22.7 B-1 口径）。
    未登记产品 → 400；`_HOOKS` 未接线 `list_models` → 400（先拒，不落任何调用）。
    """
    meta = _product_meta(product)
    hook = _hook(product, "list_models")
    runtime = getattr(request.app.state, "runtime", None)
    cfg = getattr(runtime, "config", None)
    pool = getattr(runtime, "enum_pool", None)
    accounts_out = _catalog_accounts(runtime, product)
    models, source, reason = await _catalog_models(hook, product, accounts_out)
    cfg_names = {m.name for m in getattr(cfg, "models", None) or []}
    product_rids = {r.id for r in getattr(cfg, "resources", None) or []
                    if (getattr(r, "product", "") or "").strip() == product}
    entries = []
    for m in models:
        item = dataclasses.asdict(m)
        mid = str(item.get("id") or "")
        item["suggest"] = _enum_suggest(pool, cfg_names, mid)
        item["mapped_to"] = _mapped_to(cfg, product_rids, mid)
        entries.append(item)
    payload = {"product": product, "title": meta.title,
               "checkin": meta.capabilities.checkin,
               "source": source, "models": entries, "accounts": accounts_out}
    if reason:
        payload["reason"] = reason
    return payload


# ---------- 模型映射：初始化映射（mappings，写面）----------

def _load_config_for_write(path):
    """写前读盘（**磁盘为准**：热重载的权威是文件，不是任何进程内快照）。

    读不动 → 拒写（`_ApiError`）：拿一份"缺了很多内容"的坏配置回写 = 数据丢失
    （与物化面 `_load_or_fail` 同一纪律，§22.5-1）。
    """
    try:
        return load_config(path)
    except ConfigError as e:
        raise _ApiError(500, "配置不可用（拒绝写入，避免用缺内容的快照覆盖用户配置）："
                             + "；".join(e.errors)) from None


def _create_system_model(config, pool, name: str) -> SystemModel:
    """目标模型不存在时**就地创建**（Q19-②「服务端解析」同口径：名字必须可追溯）。

    字段 = 枚举池条目的 `name`/`group`/`endpoint` + `params=params_default`（Q24：官方
    默认作网关初始值）+ `enabled=True` + `resources=[]`（映射由调用方追加）。
    🔴 只有**枚举池条目名**允许创建 —— 用户随手敲的名字会造出一个谁也追溯不到的模型
    （列表里看不出它从哪来、该配什么资源）；宁可直接 400 让用户先去「网关模型管理」页建。
    """
    entry = pool.get(name)
    if entry is None:
        raise _ApiError(400, f"系统模型 {name!r} 不存在，且不是统一名枚举池条目：请先在"
                             "「网关模型管理」页创建它，或改用枚举池里的名字"
                             "（不自动创建用户无法追溯的模型名）")
    model = SystemModel(name=name, group=entry.group, endpoint=entry.endpoint,
                        params=dict(entry.params_default or {}), enabled=True,
                        resources=[])
    config.models.append(model)
    return model


def _mapping_holder(config, rid: str, mid: str):
    """`(resource=rid, model=mid)` 组合当前挂在哪个系统模型上（无 → `None`）。

    判据扫**全部**系统模型：同一组合挂两处会让调度按模型复制资源、统计口径打架，
    所以"已在别处"是拒绝理由（进 `skipped`）而不是幂等命中（幂等命中 = **已在目标模型**上）。
    """
    for m in config.models:
        for e in m.resources:
            if e.resource == rid and e.model == mid:
                return m
    return None


@router.post("/admin/api/accounts/mappings")
@_endpoint
async def account_mappings(request: Request):
    """初始化映射（「模型映射」弹窗的提交面）：把产品目录条目挂到系统模型。

    载荷：`{"product", "items": [{"model", "target"}, …]}`（`target` = 空串 = 跳过该条）。

    逐条语义：
    - 参数形态（先拒后动，全部在写盘前）：`product` 必须已登记；`items` 非空对象数组；
      `model` 非空字符串；`target` 为字符串（空串 = 跳过）；全部跳过 → 400（无动作不做假成功）；
    - `target` 必须**可追溯**：现有系统模型，或枚举池条目名（缺失时**就地创建**，
      `name/group/endpoint/params=params_default`，Q19-② 同口径）；两者都不是 → 400；
    - 映射落点 = 每个**已启用**账号的物化资源（`ensure_resource` 幂等；显式钉到
      `runtime.config_path` —— 资源与本次映射写入必须是**同一份配置**，否则引用完整性
      校验必然失败）；停用账号不参与（与运营跳过停用同一判据）；产品没有已启用账号
      → 400（映射无处可落，拒绝而不是空跑：`added:0` 的成功形态会被误读成"已配置"）;
    - 去重判据 = (resource, model) 组合**全配置唯一**：已在目标模型 → 计入 `already`；
      已在别的系统模型 → 进 `skipped`（附账号与占位模型名）；
    - 写盘 = **既有保存链**（`config.loader.save_config` 原子写 + `runtime.reload_from_file`
      热重载，与 `PUT /admin/api/config` **同一实现**，不新造写盘通道）；`reload` 如实
      回报，失败时附 `reload_errors`（写入已发生但运行态未换代 —— 不谎报成功）;
    - **幂等**：同载荷重发 → `added: 0`，全部落 `already`，`created_models` 为空。

    ⚠️ 已知残留（登记，不伪装已覆盖）：本端点的"读-改-写"与 `PUT /admin/api/config`
    同属**未纳入跨进程写锁**的管理端保存路径（`accounts/materialize.py` 模块头残留②的
    同一口径）；与并发登录/物化落在同一毫秒窗口时后写者整份覆盖 —— 丢失无歧义、可重做
    （映射动作幂等），且不产生半成品（本端点的物化在映射写入之前、各自都过校验）。
    """
    body = await _body(request)
    product = str(body.get("product") or "").strip()
    meta = _product_meta(product)
    items = body.get("items")
    if not isinstance(items, list) or not items:
        raise _ApiError(400, "缺少映射项：items 须为非空数组（[{model, target}, ...]）")
    parsed: list[tuple[str, str]] = []
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise _ApiError(400, f"items[{i}] 必须是对象（{{model, target}}）")
        mid = str(raw.get("model") or "").strip()
        if not mid:
            raise _ApiError(400, f"items[{i}] 缺少 model（厂商侧模型 id）")
        target = raw.get("target") or ""
        if not isinstance(target, str):
            raise _ApiError(400, f"items[{i}].target 必须是字符串（空串 = 跳过该条）")
        parsed.append((mid, target.strip()))
    if not any(t for _, t in parsed):
        raise _ApiError(400, "没有需要建立的映射（全部 target 为空）—— 请至少选择一条目录条目")

    runtime = getattr(request.app.state, "runtime", None)
    path = getattr(runtime, "config_path", None)
    pool = getattr(runtime, "enum_pool", None)
    if runtime is None or path is None or pool is None:
        raise _ApiError(500, "运行态不可用（无配置快照），拒绝写入")

    # 阶段 1（**零副作用预检**）：目标模型可追溯性 —— 现有系统模型 或 枚举池条目。
    # 全部通过后才开始物化写盘（"先拒后动"：坏输入不得留下任何半成品）。
    snapshot = _load_config_for_write(path)
    existing = {m.name for m in snapshot.models}
    for _, target in parsed:
        if target and target not in existing and pool.get(target) is None:
            raise _ApiError(400, f"系统模型 {target!r} 不存在，且不是统一名枚举池条目："
                                 "请先在「网关模型管理」页创建它，或改用枚举池里的名字"
                                 "（不自动创建用户无法追溯的模型名）")

    # 阶段 2：已启用账号 → 物化资源（幂等，§22.5-1）。物化面在自身临界区内
    # "读 → 改 → 写"同一份 `runtime.config_path`；本端点的映射写入紧随其后。
    from model_gateway.accounts.materialize import MaterializeError, ensure_resource

    root = store.product_root(product)
    names = [n for n in store.list_accounts(product, root=root)
             if _account_enabled(product, n)]
    if not names:
        raise _ApiError(400, f"产品 {meta.title} 没有已启用的账号：映射的落点是账号的"
                             "物化资源，请先接入并启用至少一个账号（停用账号不参与）")
    accounts_out: list[dict] = []
    rids: dict[str, str] = {}
    for name in names:
        try:
            rid = ensure_resource(product, name, config_path=path)
        except MaterializeError as e:
            raise _ApiError(400, f"资源物化被拒（{product}/{name}）：{e}") from None
        rids[name] = rid
        accounts_out.append({"name": name, "enabled": True, "resource_id": rid})

    # 阶段 3：读**写后**磁盘快照（含刚物化的资源行）→ 建/找目标模型 → 追加映射 → 保存 → 重载。
    config = _load_config_for_write(path)
    created: list[str] = []
    added = already = 0
    skipped: list[dict] = []
    for mid, target in parsed:
        if not target:
            continue
        model = next((m for m in config.models if m.name == target), None)
        if model is None:
            model = _create_system_model(config, pool, target)
            created.append(target)
        for name in names:
            rid = rids[name]
            holder = _mapping_holder(config, rid, mid)
            if holder is not None:
                if holder.name == target:
                    already += 1
                else:
                    skipped.append({
                        "model": mid, "target": target,
                        "reason": f"账号 {name} 的资源 {rid} 与厂商模型 {mid} 已挂在系统模型 "
                                  f"{holder.name}（同一组合不重复挂载）"})
                continue
            model.resources.append(ModelResource(resource=rid, model=mid, reasoning=None))
            added += 1
    try:
        save_config(config, path)
    except OSError as e:
        raise _ApiError(500, f"配置写入失败：{e}") from None
    ok, errors = await runtime.reload_from_file()
    payload = {"product": product, "created_models": created, "accounts": accounts_out,
               "added": added, "already": already, "skipped": skipped, "reload": ok}
    if not ok:
        payload["reload_errors"] = errors
    return payload


@router.post("/admin/api/accounts/{product}/{name}/enable")
@_endpoint
async def account_enable(product: str, name: str):
    """启用账号（写 meta `enabled=true`）。"""
    _product_meta(product)
    return await _set_enabled(product, name, True)


@router.post("/admin/api/accounts/{product}/{name}/disable")
@_endpoint
async def account_disable(product: str, name: str):
    """停用账号（写 meta `enabled=false`）：运营执行跳过、状态查询仍列出、续期照常。"""
    _product_meta(product)
    return await _set_enabled(product, name, False)


def _disable_linked_resources(product: str, name: str) -> bool:
    """§22.5-1「删除账号 = 其资源置 `enabled=false` **保留**」——经物化面执行。

    - 实现在 `accounts/materialize.py::disable_resource`（M6-5a；幂等、只动 `enabled` 位、
      经既有配置保存路径原子写，热重载由装配侧 mtime 轮询承接）；
    - 配置读不动 → `MaterializeError` → **拒删账号**（_ApiError 500）：不允许出现
      "账号目录没了、资源还指着它"的半成品；
    - ⚠️ 该模块尚未导出到 `accounts/__init__.py` 公开面（M6-4a 报告已登记）；
      这里按包内模块绝对路径引用，若其签名变化会在本调用点显式失败（不静默）。
    """
    from model_gateway.accounts.materialize import MaterializeError, disable_resource

    try:
        return disable_resource(product, name)
    except MaterializeError as e:
        raise _ApiError(500, f"配置不可用于停用关联资源（拒删账号以避免半成品）：{e}") from None


@router.post("/admin/api/accounts/{product}/{name}/delete")
@_endpoint
async def account_delete(product: str, name: str, confirm: int = Query(default=0)):
    """删除账号目录（**破坏性**：必须显式 `?confirm=1`，缺省拒绝且不动盘）。

    顺序固定（§22.5-1）：**先停用其关联资源**（`enabled=false` 保留，统计与历史不丢），
    **再删账号目录** —— 任一步失败都留下可重试的完整状态。

    ⚠️ 彻底删除资源是资源页的手动操作；本端点不删配置条目，只把它停用。
    """
    _product_meta(product)
    _require_account(product, name)
    if confirm != 1:
        raise _ApiError(400, "删除为破坏性操作：请显式带 ?confirm=1 确认"
                             "（本端点会先停用该账号的关联资源，再删账号目录）")
    disabled = _disable_linked_resources(product, name)
    deleted = await store.delete_account_async(product, name)
    return {"status": "ok", "product": product, "account": name,
            "deleted": deleted, "resources_disabled": disabled,
            "message": f"账号 {name} 已删除"
                       + ("（其关联资源已置为停用并保留）" if disabled else "")}
