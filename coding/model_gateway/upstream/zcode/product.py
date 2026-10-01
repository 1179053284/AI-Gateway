"""`zcode` 产品钩子（tech-design v2.0 §22.3 冻结签名；M6-1 骨架 → **M6-3 对齐**）。

本产品证据面（§22.4 行 + `20 §2.6/§4.1` + `12 §④` + `18 §②` + 仓内既有实现）：

- 登录：**OAuth 设备流**（`POST /oauth/cli/init` → 浏览器授权 → `GET /oauth/cli/poll/{flow_id}`，
  `20 §4.1` / `12 §④`；协议实现在 `oauth.py`，本文件只做 §22.3 接线，**不重写协议**）。
  🔴 **两条通道赛跑**（M7-D）：`login_poll`（主，服务端中介，用户在哪台机器授权都收敛）
  + `login_callback`（副：本机回跳接收端 / 地址栏粘贴 → `POST /oauth/token` 换取凭据，
  `oauth.rs:364-399`）；两条线**共用** `_settle_login` 收尾，`store.commit_login` 由引擎
  在「flow is still mine」守卫下**至多调一次**（`accounts/login.py`）
- 设备：`device_mid`（🔴 **流程发起之前**定案并透传给 `cli/init`+`cli_poll`，M7-D 需求 ②；
  生成新账号时经 `dataroot.generate_unique_device_id()` **跨账号唯一**，§15.1 硬约束 1；
  已有账号**原样复用**，硬约束 2）
- 额度 ✓（`billing/balance` 需 `X-Device-Mid`；本网关主用**离线日志通道**，`18 §②`）
- 签到 ✓ = `billing/claim` + 激活事件上报（⚠️ **需阿里云 captcha 且一次性**：每个 plan 必须
  重新 mint，复用会得 `3007`；量纲是 **token 不是积分**，`20 §3.1`）
- 模型：**静态白名单**（§22.4；实测可用两条，来源见 `_MODELS` 的注释）
- ⚠️ **不可续期**（`20 §2.6`：refreshAll 只把磁盘上最新凭据回写；`oauth.py` 明确 refresh 未落地）

🔴 `meta` 通道（§22.3 ③，**M6-3 起的正式通道**）：`quota`/`claim`/`probe` 从
   `meta["account"]`（账号名）与 `meta["dir"]`（该账号目录绝对路径）取账号身份，
   产品私有文件（客户端日志、凭据）经 `meta["dir"]` 定位；`cred["account"]` 仅作
   **向后兼容回退**（M6-1 骨架期的临时通道）—— 两处的取舍都写在下方的 `_identity_of`。
🔴 **双处落盘的现实（登录路径，不是新发明的分叉）**：设备流登录成功后两份凭据都写 ——
   ① 账号目录顶层 `credentials.json` 由会话引擎经 `store.commit_login()` 落盘
      （写回自检 + 失败整体回滚，§22.3）；
   ② 客户端数据根 `<账号>/data/.zcode/v2/credentials.json` 由 `oauth.write_client_credentials()`
      原子写 —— 既有取数路径（`ops/builtin/zcode_claim` 的凭据解析、额度日志、
      `mgw zcode launch` 启动的官方客户端）都读后者，这是 zcode「整根隔离」布局的既定事实。
🔴 `build_out` 自 **M6-5c** 起已接线（`upstream/zcode/out.py::ZcodeOut`，§17 的接线：
    `AnthropicOutAdapter` + `auth.build_headers`；验证码走 `CAPTCHA_PROVIDER` 注入缝）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from model_gateway.accounts.net import make_client
from model_gateway.accounts.registry import get as registry_get
from model_gateway.accounts.types import (
    Challenge,
    ClaimOutcome,
    LoginOutcome,
    ModelInfo,
    NotRefreshable,
    ProbeResult,
    ProductMeta,
    QuotaSnapshot,
)
from model_gateway.upstream.zcode import auth, dataroot, oauth
from model_gateway.upstream.zcode import store as zstore

#: 本产品标识（§22.4；与 `accounts/registry.py` 的键、账号目录名一致）
PRODUCT = "zcode"

#: 额度数据来源标识（离线日志通道；§17 的数据源优先级：日志是客户端拿到的第一手响应）
QUOTA_SOURCE = "zcode-log"

#: 主推登录 provider（Z.ai 邮箱注册通道已关闭，§20 #9；与 `oauth.PROVIDERS` 及
#: `mgw zcode login --provider` 的默认值同源）
LOGIN_PROVIDER = "bigmodel"

#: 探活端点（相对 Plan 通道基址）：`GET {plan_base}/billing/balance`
#: （`18 §②` 的联网通道，用户主动触发；头需求矩阵：缺 `Authorization` 回 401、
#: 缺 `X-Device-Mid` 回 400 code 3001 —— DSH `zcode-upstream.ts:5-20` 实测表）
PROBE_PATH = "/billing/balance"

#: 探活超时（秒）——显式超时是纪律（§22.8-1），不放任默认无限等待
PROBE_TIMEOUT_S = 20.0

#: Plan 通道基址缺省值（配置不可用时的回落；与 `config/schemas.py` 的默认值同源）
DEFAULT_PLAN_BASE_URL = "https://zcode.z.ai/api/v1/zcode-plan"

#: 静态白名单（§22.4「静态白名单起步」）—— 只列**实测可用**的模型。
#: 来源：DSH `zcode-product.ts:80-171` 的 `ZCODE_FALLBACK_MODELS`（2026-09-28/29 实测）：
#: ① 上游 `GET /api/v1/client/configs` 的 `builtinModels` **逐字抄录**（contextWindow /
#:    maxCompletionTokens / capabilities.vision / reasoning.levels）；
#: ② 真实推理端到端验证（`GLM-5.3` 3/3 正确、`GLM-5.3-Flash` 10/15 正确）。
#: ⚠️ 上游清单里的 `GLM-5-Turbo` / `GLM-5.2` 在 Start Plan 下**返回空响应**（实测 0/3）
#: → **不列入**（列一个用不了的模型比不列更糟）。
#: ⚠️ `tool_call` 恒 `None`：上游 `builtinModels` 不声明工具能力，**取不到不编造**（`21 §5.1-1`）。
#: ⚠️ `defaultLevel=max` 无处承载（§22.3 的 `ModelInfo` 无该字段）—— 与 buddy 同一处已登记缺口。
#: ⚠️ id 用**上游官方大小写**（`GLM-5.3-Flash`）：该值会作为 `ModelResource.model` 原样发给上游；
#:   官方名即此形态（`client/configs` 的 `modelId`；`15 §⑤` zcode2api 的别名表也是
#:   `glm-5.3 → GLM-5.3` 的小写入 / 官方名出）。
#: ⚠️ 计费倍率：本通道按 **token 额度**计（免费额度 1 亿 token/日，单位不是积分/倍率）——
#:   上游目录无 credits/price 类字段 → `free` / `rate` 保持默认（`None` / `""`，**不编造**）。
_MODELS: tuple[ModelInfo, ...] = (
    ModelInfo(id="GLM-5.3-Flash", name="GLM-5.3-Flash",
              context_window=1_000_000, max_output=128_000,
              image_input=True, reasoning=True,
              effort_levels=("low", "high", "max")),
    ModelInfo(id="GLM-5.3", name="GLM-5.3",
              context_window=1_000_000, max_output=128_000,
              image_input=False, reasoning=True,
              effort_levels=("low", "high", "max")),
)


def _plan_base() -> str:
    """Plan 通道基址（配置优先 → 官方端点回落，不阻断探活；与领取路径同口径）。

    ⚠️ 领取出站基址由 `ops/builtin/zcode_claim._plan_endpoint()` 解析（同一配置项）；
    产品层**不 import `ops/`**（分层：`upstream/` 只被 `ops/` 调用，不得反向依赖）。
    """
    try:
        from model_gateway.config.loader import load_config

        base = (load_config().gateway.zcode.plan_base_url or "").strip()
        return (base or DEFAULT_PLAN_BASE_URL).rstrip("/")
    except Exception:  # noqa: BLE001 — 配置不可用不阻断探活（回落到官方端点）
        return DEFAULT_PLAN_BASE_URL


def meta() -> ProductMeta:
    """产品注册信息（唯一事实源 = `accounts/registry.py`，此处不重复填字段）。"""
    return registry_get(PRODUCT)


# ==================== 账号身份（§22.3 ③ 的 meta 通道）====================


def _as_dict(value) -> dict:
    """宽容取 dict（`meta` 形参在护栏用例里可能是 `ProductMeta`；不因类型不符而抛）。"""
    return value if isinstance(value, dict) else {}


def _identity_of(meta, cred) -> tuple[str, Path | None]:
    """账号身份 `(账号名, 账号根)` —— **正式通道 = `meta`（§22.3 ③）**。

    - 账号名：`meta["account"]` 优先；缺则取 `meta["dir"]` 的**末段**（§22.2 布局
      `<账号根>/<账号名>/`，目录名即账号名）；两者都缺才回退 `cred["account"]`
      （**向后兼容**：M6-1 骨架期钩子只拿到 cred —— 该分支保留但不再是首选通道）。
    - 账号根：`meta["dir"]` 给出时取其父目录（= 该产品的 `accounts_root`），否则 `None`
      （调用方回退既有 `store.accounts_root()`）。

    ⚠️ 公共层目前**没有**统一的 meta 组装入口（详见 M6-3 报告：契约级缺口 + 最小修法）——
    入口层（M6-4 管理 API）调用钩子时**必须**按 §22.3 ③ 传 `{"account": ..., "dir": ...}`。
    """
    m = _as_dict(meta)
    account_dir_raw = str(m.get("dir") or "").strip()
    account_dir = Path(account_dir_raw) if account_dir_raw else None
    account = str(m.get("account") or "").strip()
    if not account and account_dir is not None:
        account = account_dir.name
    if not account:
        account = str(_as_dict(cred).get("account") or "").strip()
    root = account_dir.parent if account_dir is not None else None
    return account, root


def _account_root_of(root: Path | None) -> Path:
    """账号根：meta 通道给出（`meta["dir"]` 的父目录）则用它，否则回退既有 `store.accounts_root()`。"""
    return root if root is not None else zstore.accounts_root()


def _resolved_credentials(cred, meta, account_dir: Path | None) -> tuple[str, str]:
    """该账号的 `(zcodejwttoken, device_mid)`，取不到就是空串（**不编造**）。

    两个来源按序合并 —— 这是 zcode「双处落盘」现实的读取侧：
    ① **凭据本体**（`cred`，公共层 `credentials.json`；设备流登录写的那份）优先；
    ② **客户端数据根**（`meta["dir"]` 下的 `<v2>/credentials.json` + `meta.json`；
       `mgw zcode import` 导入的官方缓存写的那份）兜底。
    """
    c = _as_dict(cred)
    jwt = str(c.get(oauth.KEY_JWT) or c.get("jwt") or "").strip()
    mid = str(_as_dict(meta).get("device_mid") or "").strip()
    if account_dir is not None:
        if not mid:
            mid = str(dataroot._read_json(account_dir / "meta.json").get("device_mid") or "").strip()
        if not jwt:
            clients = oauth.read_credentials(
                dataroot.v2_dir_of(account_dir.parent, account_dir.name))
            jwt = oauth.build_credentials(clients).jwt
    if not mid:
        mid = str(c.get("device_mid") or "").strip()
    return jwt, mid


def outbound_credentials(cred: dict, meta: dict) -> tuple[str, str]:
    """出站（模型转发）用的 `(jwt, device_mid)` —— **复用** `_resolved_credentials` 的口径。

    模型转发与探活/领取读的是**同一套双处落盘合并规则**（凭据本体优先 → 客户端数据根兜底），
    这里只是把「按 `meta` 通道定位账号目录」的取法公开出来（M6-5c；`out.py` 不重写一份）。
    取不到一律空串（**不编造**，由调用方 fail closed）。
    """
    account, root = _identity_of(meta, cred)
    dir_raw = str(_as_dict(meta).get("dir") or "").strip()
    account_dir = Path(dir_raw) if dir_raw else (
        _account_root_of(root) / account if account else None)
    return _resolved_credentials(cred, meta, account_dir)


# ==================== 登录（两步式：start → poll；副通道 callback）====================


#: 会话态键（**引擎**读它做回跳关联校验，见下方 `_CALLBACK` 声明表）
STATE_KEY = "state"


async def login_start(session) -> Challenge:
    """两步式第一步：申请设备授权流程，把**改写后的** `authorize_url` 交给用户。

    协议细节全在 `oauth.cli_init`（**不在此重写**）：`POST /api/v1/oauth/cli/init`
    → `{flow_id, authorize_url, poll_token?, expires_at, poll_interval_sec}`；
    交给用户之前那串 `authorize_url` 已被剥掉服务端回跳参数、重挂官方桥接页
    （`oauth.rs:127-149`，理由见 `oauth.py` 模块头），`state` 也从服务端那条 URL 里取。

    🔴 **设备码必须在发起之前定案**（M7-D 需求 ②）：`X-Device-Mid` 要出现在
    `cli/init` **和** `cli/poll` 两次请求上，且最终进 `meta["device_mid"]` 落盘的
    必须**是同一个值** —— 中途换码 = 上游眼里"换设备"（§15.1 硬约束 2/3）。
    决策仍走 `_device_mid_for_login`（重登复用 / 新号跨账号唯一），本函数只是把
    它的时机从"轮询成功后"提前到"流程发起前"，并把它挂进 `DeviceFlow` 一起走。
    持久化时机**不变**（仍由引擎 `commit_login` 写 `meta.json`）：提前写 `meta.json`
    会让一个"发起了登录但没授权完"的目录被 `accounts/store.py::list_accounts`
    的判据（"有 meta.json 的目录"）当成账号，在界面上多出一行没有凭据的假账号。

    🔴 私态（`flow_id` / 轮询密钥 / 设备码）落 `session.state`，**绝不进 `Challenge`**
    （`Challenge` 只承载用户可见物，§22.3）；上游不可用 → 抛异常（引擎不吞异常，§22.8-5）。
    """
    account = str(getattr(session, "name", "") or "")
    if not account:
        raise ValueError("zcode.login_start：会话缺账号名（引擎未给 session.name）")
    device_mid = _device_mid_for_login(account, zstore.accounts_root())
    flow = await oauth.cli_init(LOGIN_PROVIDER, device_mid=device_mid)
    session.state["flow"] = flow
    session.state["device_mid"] = device_mid
    # 🔴 回跳关联串 = 服务端给的 state（引擎按 `_CALLBACK.secret_state_key` 读它）：
    # 一条没带 state 或 state 不符的回跳会被接收端直接 400 且**继续监听**，
    # 不会把用户正在进行的登录打死（`callback_server._correlation_problem`）。
    session.state[STATE_KEY] = flow.state
    return Challenge(url=flow.authorize_url)


async def login_poll(session) -> LoginOutcome:
    """两步式第二步（**主通道**）：轮询一次授权结果（**pending 不是错误**，§22.3）。

    - `pending`：原样透传，等下一次轮询（会话 TTL 由引擎兜底，§22.8-2）；
    - `expired` / `failed`：终态，透传协议层给出的可读原因；
    - `ready`：交给 `_settle_login`（与回跳通道**同一个**收尾，见那里的说明）。
    """
    flow = _flow_of(session)
    if flow is None:
        return LoginOutcome(state="failed", detail="会话缺少授权流程（login_start 未成功）")
    poll = await oauth.cli_poll(flow)
    if poll.state != "ready":
        return LoginOutcome(state=poll.state, detail=poll.detail)
    return await _settle_login(session, flow, poll, channel="轮询")


async def login_callback(session, params) -> LoginOutcome:
    """🔴 **副通道**：回跳投递（本机接收端 / 地址栏粘贴，同一入口、同一 handler）。

    本产品是**服务端中介**的设备流：主通道是 `login_poll`（用户在哪台机器上授权都收敛）。
    但授权页走完最后一步时，浏览器/桥接页手里还有一条带 `code`+`state` 的回跳 ——
    拿到它就能**立刻**换取凭据，不必等下一轮轮询（`oauth.rs:1698-1706,1835-1898`
    正是让这两条线赛跑、由「flow is still mine」守卫保证只落一次盘）。

    形状（`ZCode-Panel/main.js:1978-1986`：两种形态都要接受）：
    - `zcode://oauth/callback?authCode=…&state=…` —— 官方深链（装了客户端的机器上才有意义）；
    - `https://zcode.z.ai/app/oauth/login?code=…&state=…` —— 桥接页**自己的** query；
    - `http://127.0.0.1:{port}/oauth/callback?…` —— 本机接收端重建的地址。
    入口层的 `POST /admin/api/accounts/login/callback` 也接受平铺的
    `{"code"/"authCode", "state"}`（`admin_accounts.login_callback` 的两种载荷形态）。

    state 不符 = 不是本次登录的回跳 → `failed` 且**不打上游**（协议层同一判据）。
    """
    flow = _flow_of(session)
    if flow is None:
        return LoginOutcome(state="failed", detail="会话缺少授权流程（login_start 未成功）")
    poll = await oauth.cli_exchange(_callback_params_of(params), flow)
    if poll.state != "ready":
        return LoginOutcome(state=poll.state or "failed", detail=poll.detail)
    return await _settle_login(session, flow, poll, channel="回跳")


def _flow_of(session) -> oauth.DeviceFlow | None:
    """会话里的授权流程（没有 = `login_start` 没成功过，两条通道都无从继续）。"""
    flow = session.state.get("flow") if isinstance(session.state, dict) else None
    return flow if isinstance(flow, oauth.DeviceFlow) else None


def _callback_params_of(params) -> oauth.CallbackParams:
    """把两种投递形态收敛成一个 `CallbackParams`（解析规则只有一份：`parse_callback_url`）。"""
    if isinstance(params, oauth.CallbackParams):
        return params
    bag = _as_dict(params)
    url = str(bag.get("url") or "").strip()
    if url:
        return oauth.parse_callback_url(url)
    return oauth.CallbackParams(code=str(bag.get("authCode") or bag.get("code") or "").strip(),
                                state=str(bag.get("state") or "").strip())


async def _settle_login(session, flow: oauth.DeviceFlow,
                        poll: oauth.DevicePoll, *, channel: str) -> LoginOutcome:
    """两条通道**同一个**收尾（设备码 / 落盘 / meta 组装一行都不重复实现）。

    ① 设备码：沿用 `login_start` 发起时定下的那个（`flow.device_mid`）——
       与已经打到上游的两次请求是同一个身份；会话态里被别的通道抢先定过也要以它为准；
    ② 把官方格式凭据写进该账号的**客户端数据根**（见模块头「双处落盘的现实」）；
    ③ `credentials`/`meta` 交给会话引擎经 `store.commit_login()` 落盘
      （写回自检 + 失败回滚；**本函数一次都不调 `commit_login`** ——
       落盘只有一处，「flow is still mine」守卫才能证明它每条会话至多执行一次）。

    落盘失败 → 翻成 `failed`（**不谎报成功**）；`meta["device_mid"]` 是设备身份的唯一载体
    （`accounts/device.py` 按各账号 `meta.json` 的字段值判重）。
    """
    account = str(getattr(session, "name", "") or "")
    if not account:
        return LoginOutcome(state="failed", detail="会话缺账号名（引擎未给 session.name）")
    root = zstore.accounts_root()
    device_mid = str(flow.device_mid or session.state.get("device_mid") or "") \
        or _device_mid_for_login(account, root)
    try:
        _materialize_client_store(account, poll.credentials)
        dataroot.sync_device_mid_to_telemetry(root, account, device_mid)
    except (OSError, RuntimeError) as e:
        # 可预期失败（磁盘写不动 / 设备码生成耗尽）→ 折叠成 failed（§22.3：不谎报成功）
        return LoginOutcome(state="failed",
                            detail=f"登录收尾失败（设备码生成或凭据写入客户端数据根）："
                                   f"{type(e).__name__}: {e} —— 本轮未落盘，请重试")
    user = _as_dict(poll.user_info)
    meta_out: dict = {"device_mid": device_mid, "provider": flow.provider}
    display = str(user.get("name") or user.get("email") or "").strip()
    if display:
        meta_out["display_name"] = display          # 展示镜像（§22.7：返回体不含凭据明文）
    uid = str(user.get("user_id") or user.get("id") or "").strip()
    if uid:
        meta_out["user_id"] = uid
    return LoginOutcome(state="success", credentials=poll.credentials, meta=meta_out,
                        detail=f"登录成功（{flow.provider}，{channel}通道）")


def _device_mid_for_login(account: str, root: Path) -> str:
    """登录路径的设备码决策（§15.1 两条硬约束，**不静默降级**）：

    - 该账号已有 `device_mid`（重登录）→ **原样复用**（硬约束 2：绝不重新生成 ——
      重登换码 = 上游眼里"换设备"，反而触发风控，§15.1 硬约束 3 的同一理由）；
    - 新账号 → `dataroot.generate_unique_device_id()` 生成**跨账号唯一**的新码（硬约束 1，
      冲突即重生成、有上限、耗尽显式失败）。

    ⚠️ **只决策、不落盘**（落盘归引擎的 `commit_login`）：调用时机自 M7-D 起提前到
    「流程发起之前」，但提前**写** `meta.json` 会让没授权完的目录被
    `store.list_accounts` 认成账号（它的判据就是"有 meta.json"）→ 界面多一行空账号。
    `mgw zcode login`（`cli_zcode._login_device_mid`）复用同一函数，两条路径零分叉。
    """
    existing = dataroot._read_json(root / account / "meta.json")
    mid = str(existing.get("device_mid") or "").strip()
    return mid or dataroot.generate_unique_device_id(root)



def _materialize_client_store(account: str, credentials: dict) -> Path:
    """把凭据写进该账号的客户端数据根（整根隔离），返回写入路径。

    读它的是**两条既有路径**：① `ops/builtin/zcode_claim` 的凭据解析（领取）；
    ② `mgw zcode launch` 启动的官方客户端。不写这一份，设备流登录出的账号就是
    「钩子层能用、领取/客户端不能用」的半可用状态。

    账号根取 `store.accounts_root()`（`MGW_ZCODE_ACCOUNTS` 口径）——与会话引擎
    默认落盘根同源；`commit_login` 由引擎随后做（写回自检 + 失败整体回滚）。

    ⚠️ 本步在 `commit_login` **之前**（引擎在钩子返回后才落盘）→ 若随后落盘自检失败，
    可能留下一个**不是账号**的目录骨架（没有 `meta.json`，`list_accounts` 的判据不认它，
    `accounts/device.py` 的唯一性检查也不看它）；重试登录会覆盖同一路径。这是「先写客户端
    数据根、后 commit」这一顺序的固有窗口，登记在此而不是假装不存在。
    """
    root = zstore.accounts_root()
    dataroot.ensure_layout(root, account)
    return oauth.write_client_credentials(dataroot.v2_dir_of(root, account), credentials)


# ==================== 续期 ====================


async def refresh(cred, meta) -> dict:
    """凭据续期 —— **本产品不可续期**（§22.3 的 `NotRefreshable` 语义）。

    依据：`20 §2.6`（`refreshAll` 对 zcode 只做磁盘凭据回写）+ 仓内 `upstream/zcode/oauth.py`
    的模块头（refresh 未落地）。**这不是故障**（不触发冷却）。
    ⚠️ 本钩子不消费账号身份，因此**不读** `meta["account"]`/`meta["dir"]`（§22.3 ③ 的
    正式通道仍是它们；将来若上游给出续期能力，身份从这里取）。

    ⚠️ 护栏协调（2026-09-29 已裁决）：`tests/unit/test_v2_cli_zcode.py` 的
    「死符号复活」护栏扫描面已收窄到**旧 zcode 面**（排除新产品模块）——
    本函数是 §22.3 的**在册钩子**，不是死代码复活；原先的 `_refresh_impl` 别名绕行已撤销。
    """
    raise NotRefreshable("ZCode 凭据不可续期（20 §2.6：只做磁盘凭据回写）")


# ==================== 探活 / 额度 ====================


async def probe(cred, meta) -> ProbeResult:
    """探活：**连通 / 凭据有效**两个维度分开（§22.3）。

    判据端到端（DSH `zcode-auth.ts:236-269`：只看文件存在不够 —— "解出来了但已失效"
    必须如实反映）：`GET {plan_base}/billing/balance`（`18 §②` 联网通道，用户主动触发；
    头需求矩阵 = 缺 `Authorization` 回 401、缺 `X-Device-Mid` 回 400/3001）。

    映射（**未知一律 fail closed**，§22.8-5）：

    | 上游情形 | 结果 |
    |---|---|
    | 2xx 且 `code=0`（或带 `data` 对象）| `reachable=True, valid=True` |
    | 401/403，或 `code=3012`（风控）| `reachable=True, valid=False`（**不重试**）|
    | 其余非 2xx / 200 但看不出是余额响应 | `reachable=True, valid=False`（"未确认"≠通过）|
    | 网络层失败 | `reachable=False` |

    纪律：与领取路径共用 3012 熔断闸门与 10s 节流（熔断中**不发起**，如实说明原因）；
    探活**不打验证码、不吃住宅代理**（代理是 captcha 求解的硬依赖，与本端点无关）。
    ⚠️ 真实可用性未在本机用真实凭据实测（§22.11 用户驱动；直连风控结论见 `24 §2-D1`）。
    """
    cred_d = _as_dict(cred)
    account, root = _identity_of(meta, cred)
    dir_raw = str(_as_dict(meta).get("dir") or "").strip()
    account_dir = Path(dir_raw) if dir_raw else (
        _account_root_of(root) / account if account else None)
    jwt, device_mid = _resolved_credentials(cred_d, meta, account_dir)
    if not jwt:
        return ProbeResult(reachable=False, valid=False,
                           detail="凭据缺失（zcodejwttoken 既不在凭据本体、客户端数据根也没有）"
                                  "→ 未发起探活")
    if not device_mid:
        return ProbeResult(reachable=False, valid=False,
                           detail="账号缺设备码（device_mid；缺它上游必回 400/3001）"
                                  "→ 未发起探活")

    from model_gateway.upstream.zcode import quota as zq

    circuit = zq.get_circuit()
    if circuit.active():
        return ProbeResult(reachable=False, valid=False,
                           detail=f"ZCode 全局风控熔断中（剩余约 {circuit.left_minutes()} 分钟）"
                                  "→ 未发起探活")
    wait_ms = circuit.throttle_wait_ms()
    if wait_ms > 0:
        await asyncio.sleep(wait_ms / 1000)          # 与领取路径共用 10s 节流（§17）
    circuit.mark_called()
    try:
        resp = await _fetch_balance(jwt, device_mid)
    except httpx.HTTPError as e:
        return ProbeResult(reachable=False, valid=False,
                           detail=f"网络不可达：{type(e).__name__}: {e}")
    body = _json_or_empty(resp)
    code = body.get("code")
    if resp.is_success and (code in (0, "0")
                            or (code is None and isinstance(body.get("data"), dict))):
        # 2xx 且**看得出是余额响应**（业务码 0，或按 DSH `zcode-upstream.ts:203-227` 的判据
        # 至少带 `data` 对象）才算通过 —— 非 JSON 的 200（WAF 页等）落到下面"未确认"，
        # 不因为状态码是 200 就宣布凭据有效（fail closed，§22.8-5）。
        return ProbeResult(reachable=True, valid=True, detail="OK（billing/balance 200）")
    if code == zq.CODE_RISK_CONTROL or zq.looks_like_risk_control(str(body.get("msg") or "")):
        return ProbeResult(reachable=True, valid=False,
                           detail="命中 3012 风控（unusual activity）—— 未重试；"
                                  "领取路径命中同一信号时会建立全局熔断（§17）")
    if resp.status_code in (401, 403):
        return ProbeResult(reachable=True, valid=False,
                           detail=f"凭据被上游拒绝（HTTP {resp.status_code}）"
                                  "→ 需重新登录或导入")
    suffix = f"，code={code}" if code is not None else ""
    return ProbeResult(reachable=True, valid=False,
                       detail=f"凭据有效性未确认（HTTP {resp.status_code}{suffix}）"
                              "—— 未确认不等于通过（§22.8-5）")


async def _fetch_balance(jwt: str, device_mid: str) -> httpx.Response:
    """探活的**唯一 HTTP 落点**（单测 monkeypatch 本模块的 `make_client` 即可，不连网）。

    鉴权头取 **`auth.build_headers`**（§17：双通道鉴权归 `auth` —— 不在这里另写一份
    Bearer / X-Device-Mid 构造；缺 mid 时上游回 400/3001 的事实也由同一处承载）。
    """
    headers = auth.build_headers("jwt", auth.Credentials(jwt=jwt, device_mid=device_mid),
                                 app_version=oauth.DEFAULT_APP_VERSION)
    async with make_client(base_url=_plan_base(), headers=headers,
                           timeout=PROBE_TIMEOUT_S) as client:
        return await client.get(PROBE_PATH, params={"app_version": oauth.DEFAULT_APP_VERSION})


def _json_or_empty(resp: httpx.Response) -> dict:
    """读 JSON 体；非 JSON / 非对象 → 空 dict（**不因解析失败丢掉 HTTP 事实**）。"""
    try:
        body = resp.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


async def quota(cred, meta) -> QuotaSnapshot:
    """额度快照 —— **委托既有实现**（`upstream/zcode/quota.py` 的离线日志通道）。

    既有实现以**账号目录**为输入（日志在 `<账号>/data/.zcode/v2/logs/`）；身份取
    §22.3 ③ 的 `meta` 通道（`meta["account"]`/`meta["dir"]`，缺则回退 `cred["account"]`，
    见 `_identity_of`）。缺账号名 → `unknown`（**不编造**：`23 B2`「未知不当零」）。
    """
    from model_gateway.upstream.zcode import quota as zq

    account, root = _identity_of(meta, cred)
    if not account:
        return QuotaSnapshot(
            state="unknown", source=QUOTA_SOURCE,
            detail="缺账号名（meta['account']/meta['dir']；向后兼容 cred['account']），未取额度")
    snap = zq.read_account_snapshot(_account_root_of(root), account)
    if not snap.ok:
        return QuotaSnapshot(state="unknown", source=QUOTA_SOURCE,
                             detail=snap.note or "无可用日志记录")
    remaining = zq.remaining_units(snap)
    if remaining is None:
        return QuotaSnapshot(state="unknown", source=QUOTA_SOURCE,
                             detail=f"plan={snap.plan}；余量口径不可得")
    return QuotaSnapshot(state="available" if remaining > 0 else "exhausted",
                         source=QUOTA_SOURCE,
                         detail=f"plan={snap.plan}；可用余量 {remaining}（token 量纲）")


async def claim(cred, meta, *, precheck: bool) -> ClaimOutcome:
    """签到/领取 —— **委托既有实现**（`ops/builtin/zcode_claim.py::claim`，四类语义同源）。

    - 既有实现自带 `preview` 预检（等价 `precheck=True`）与全局熔断闸门（§17），
      因此本钩子不再重复预检；
    - `20 §3.1`：captcha **一次性**（每个 plan 必须重新 mint）与"量纲是 token"两条
      由既有实现与入口层文案负责；
    - 身份取 §22.3 ③ 的 `meta` 通道（缺则回退 `cred["account"]`，见 `_identity_of`）；
      缺账号名 → `failed`（**不编造**领取结果）。
    """
    from model_gateway.ops.builtin import zcode_claim

    account, _root = _identity_of(meta, cred)
    if not account:
        return ClaimOutcome(
            category="failed",
            detail="缺账号名（meta['account']/meta['dir']；向后兼容 cred['account']），无法领取")
    result = await zcode_claim.claim(account)
    # 🔴 结构化重试声明**沿既有执行体原样带出**（§22.6 R1-F2）：执行体在
    # 网络/5xx 折叠处置 `retryable=True`；其余（业务码/凭据/熔断状态文件等）为
    # None/False → 这里归一成 False = 不可重试（该产品非网络的失败折叠均属此类）。
    return ClaimOutcome(category=result.category, detail=result.detail,
                        retryable=bool(result.retryable))


async def list_models(cred, meta) -> list[ModelInfo]:
    """产品模型目录（§22.4：**静态白名单**，`models_source="static"`）。

    不发上游请求、**不编造**：本表逐条有实测出处（见 `_MODELS` 的注释）。
    `cred`/`meta` 无需消费（白名单与账号无关）→ 保持冻结签名。
    """
    return list(_MODELS)


# ==================== 出站适配（M6-5c）====================


def build_out(account) -> OutboundAdapter:
    """构造出站适配器（§22.3；zcode 走 anthropic 协议 + TLS 指纹伪装，§17）。

    - 返回 `upstream/zcode/out.py::ZcodeOut`：**复用** `AnthropicOutAdapter`
      （传输 / SSE 事件翻译 / usage 映射）+ `auth.build_headers`（Plan/JWT 通道）；
    - TLS 指纹**按配置**（`gateway.zcode.fingerprint`；`curl_cffi` 不可用时
      `auth.build_client` 内降级 httpx，不静默改变语义）；
    - 验证码走 `out.CAPTCHA_PROVIDER` 注入缝（未注入 = §17 降级链的「JWT 直连」档；
      §16.5 的 `CaptchaSolver` 带 45s 缓存，**不能**直接用于每请求一次性的转发路径）；
    - 延迟 import（`out.py` ↔ 本模块不互相在 import 期拉起）。
    """
    from model_gateway.upstream.zcode.out import ZcodeOut
    return ZcodeOut(account)


#: 骨架纪律护栏的**登记面**（`tests/accounts/test_registry.py::_implemented_hooks` 读它）：
#: 本产品已接线的钩子名。**`login_callback` 自 M7-D 起已接线**（回跳副通道：
#: 接收端投递 / 地址栏粘贴 → `oauth.cli_exchange` → 与轮询**同一个** `_settle_login` 收尾）；
#: `build_out` 自 **M6-5c** 起已接线。
_IMPLEMENTED = ("login_start", "login_poll", "login_callback", "refresh", "probe",
                "quota", "claim", "list_models", "build_out")


#: §22.3 契约表（入口层 `accounts/login.py::_hook` 与 M6-5 按名取用；缺项当场 KeyError）
_HOOKS = {
    "meta": meta,
    "login_start": login_start,
    "login_poll": login_poll,
    "login_callback": login_callback,
    "refresh": refresh,
    "probe": probe,
    "quota": quota,
    "claim": claim,
    "list_models": list_models,
    "build_out": build_out,
}

#: 回跳接收端声明（BD4；引擎 `accounts/login.py::_callback_plan` 读这张表，
#: 与 `_HOOKS`/`_ALT_HOOKS` 同一条"表里有什么才用什么"的纪律，形状同
#: `upstream/trae/product.py` / `upstream/lobsterai/product.py`）。
#:
#: 🔴 zcode 与那两个产品的**差别**：主通道是**服务端中介的轮询**（`login=device_code`），
#: 这张表声明的是**副通道** —— 引擎据此为本会话绑一条 127.0.0.1 监听：浏览器能落到本机
#: 时当场把凭据换回来，落不到时轮询照常收敛（两条线赛跑，由引擎的
#: 「flow is still mine」守卫保证 `commit_login` 每条会话至多一次）。
#:
#: - `path` `/oauth/callback`：与官方深链 `zcode://oauth/callback`（`oauth.rs:258`）**同形**
#:   → 「深链 / 桥接页 / 本机回环」三种投递共用同一个解析器（`oauth.parse_callback_url`）；
#: - `preferred_port=0`：官方没有任何固定端口约定（它走的是自定义协议，不是 loopback 回调）
#:   → 随机端口（`callback_server._bind` 保证 ≥10000）；
#: - `secret_state_key` / `secret_key` 都是 `state`：**服务端**在 `authorize_url` 里给的
#:   关联串（M7-D 需求 ①：从服务端取、不本地生成，`oauth.rs:150-157`）；
#: - `secret_required=True`：没带 `state` 的回跳不是本次登录的 → 接收端回 400 且**继续监听**，
#:   不把用户正在进行的登录打死。
_CALLBACK = {
    "path": oauth.CALLBACK_PATH,
    "preferred_port": 0,
    "secret_state_key": STATE_KEY,
    "secret_key": STATE_KEY,
    "secret_required": True,
}

