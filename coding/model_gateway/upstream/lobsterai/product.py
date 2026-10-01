"""LobsterAI 产品钩子（tech-design v2.0 §22.3 冻结签名；M6-2 实现）。

本产品证据面（§22.4 行 + `20 §1.2/§2.5/§3.1/§3.2`）：

- 登录：**local_callback 两步**（回跳接收端投递 + 粘贴兜底；接收端 = 公共层
  `accounts/callback_server.py`，BD4 接线，声明表见本模块 `_CALLBACK`；
  本层不自己起监听，判据见 `login.py` 模块头）
- 设备：身份字段 = `uuid`（安装标识，`lobsterai.ts:102-109`）；`first_keyfrom`/
  `latest_keyfrom`（keyfrom 身份载荷的时间戳，续期请求体必带）是**非身份元数据**——
  §22.3 裁决 2026-09-29：不进 `DeviceSpec`、不参与唯一性，仅按账号元数据写 `meta.json`
- 额度 ✓ `GET /api/user/profile-summary`；签到 ✓ 三步 `slot → context → check_in`
  （幂等 = 客户端 `claimedToday` + `actions` 含 `check_in` 双重预检 + 幂等键 `uuid4`）
- 模型：remote `GET /api/models/available`（带 keyfrom query）+ 兜底表（`21 §1.1`）

🔴 `build_out` **自 M6-5b 起已接线**（`upstream/lobsterai/out.py::LobsteraiOut`：
`POST /api/proxy/v1/chat/completions`、Bearer + 两个 `X-LobsterAI-Client-*` 头、
`stream` 恒真 + 非流式聚合，逐条取证见该文件模块头）。
🔴 `_HOOKS` = 本模块对 §22.3 的**契约表**：入口层按名取用（不给字符串 `getattr` 留后门），
   也是接线护栏能看见的"钩子真的存在"证据。
"""

from __future__ import annotations

from model_gateway.accounts.registry import get as registry_get
from model_gateway.accounts.types import (
    Challenge,
    ClaimOutcome,
    LoginOutcome,
    ModelInfo,
    ProbeResult,
    ProductMeta,
    QuotaSnapshot,
)
from model_gateway.upstream.lobsterai import claim as claim_mod
from model_gateway.upstream.lobsterai import const, login, models, protocol, quota as quota_mod

#: 本产品标识（§22.4；与 `accounts/registry.py` 的键、账号目录名一致；
#: 字面量在 `const.py` 里只写一份，这里指向它）
PRODUCT = const.PRODUCT_ID

#: 已接线的钩子名（`tests/accounts/test_registry.py::_implemented_hooks` 的**首选口径**，
#: 精确到钩子名）。`build_out` 自 **M6-5b** 起已接线（`upstream/lobsterai/out.py`，
#: `/api/proxy/v1/chat/completions` 有取证）→ 进本表。
_IMPLEMENTED = ("meta", "login_start", "login_poll", "login_callback", "refresh",
                "probe", "quota", "claim", "list_models", "build_out")


def meta() -> ProductMeta:
    """产品注册信息（唯一事实源 = `accounts/registry.py`，此处不重复填字段）。"""
    return registry_get(PRODUCT)


async def login_start(session) -> Challenge:
    """启动登录（§22.3 两步式的第一步）：生成会话态 + 返回 portal 登录 URL。

    **零网络调用**是刻意的（照抄 DSH 的两步式动机，`lobsterai-auth.ts:239-250`）：
    浏览器只在用户点击后的短暂窗口（transient activation，约 5 秒）内允许 `window.open`，
    任何阻塞式取数都会让弹窗被拦截、前端兜底跳转把整个设置页带走。
    🔴 回跳监听**也不在这里起**：引擎建会话时已**先绑定**（BD4），本函数只读它的
       **实际端口** —— 门户校验 `redirect_uri` 的**形状**（`lobsterai-oauth.ts:95-97`），
       端口可以随机，形状不行，所以随机端口照样能用（`login.redirect_port`）。
    一次性 `state` / 安装 `uuid` / `first_keyfrom` 进 `session.state`（**不进 Challenge**）；
    `state` 同时是接收端的**关联串**（`_CALLBACK` 表把它和回跳里的 `state` 比对）。
    """
    session.state.update(login.new_login_state())
    return Challenge(url=login.login_url(login.redirect_port(session),
                                         str(session.state["state"])))


async def login_poll(session) -> LoginOutcome:
    """轮询登录状态（§22.3 两步式的兜底轮询）。

    🔴 本机回调型**永远不由轮询自行成功**：凭据只从 `login_callback` 来 ——
       两条投递都汇到那里（接收端真回跳 / 地址栏粘贴兜底）。
    这里返回 `pending`（§22.3：**pending 不是错误**，会话保留到 TTL 600s / 显式取消），
    给界面一个诚实的状态而不是让入口层 500（TS 侧同形：`credits.status` 对没有状态端点的
    产品如实返回 null，`jet-hub-rpc.ts:1688-1702`）。
    """
    return LoginOutcome(state="pending",
                        detail="等待浏览器回跳：本机回跳接收端会自动接管并写出结果页；"
                               "接收端未就绪时，把地址栏里的整串回跳地址粘贴回本页提交"
                               "（本机回调型不经轮询出结果）")


async def login_callback(session, params) -> LoginOutcome:
    """回跳落地（仅 local_callback 型，§22.3）：校验 `state` → 换凭据。

    🔴 两条投递共用（BD4）：接收端把真回跳 URL 经 `accounts/login.py::LoginEngine._deliver`
       灌进同一个 `{"url": …}` 参数形态，人工粘贴是同一入口的兜底 —— exchange 只有一份。
    `state` 不匹配 = 不是本次登录发起的回调（或伪造）→ **直接拒绝**
    （`lobsterai-oauth.ts:262-269`：DSH 回 HTTP 400「登录回调参数无效」；本层折叠成 failed；
    接收端在此之前已按同一把 `state` 回过 400 并**继续监听**）。
    换凭据失败同样作废本次登录：授权码一次性，重试无意义（Go/DSH 同）。
    """
    code, got_state = login.callback_code_state(params)
    expected = str(session.state.get("state") or "")
    if not code or not expected or got_state != expected:
        return LoginOutcome(state="failed",
                            detail="回调参数无效（缺少 code 或 state 不匹配）—— 已按防 CSRF 口径拒绝")
    device_uuid = str(session.state.get("uuid") or "")
    first_keyfrom = str(session.state.get("first_keyfrom") or "")
    if not device_uuid or not first_keyfrom:
        return LoginOutcome(state="failed",
                            detail="登录会话缺少设备状态（会话可能已被取消或过期）")
    try:
        version = await login.client_version()
        credentials = await login.exchange(code, device_uuid=device_uuid,
                                           first_keyfrom=first_keyfrom, version=version)
    except (login.LoginError, protocol.ProtocolError) as e:
        return LoginOutcome(state="failed", detail=str(e))
    return LoginOutcome(state="success", credentials=credentials,
                        meta=protocol.credential_meta(credentials, fallback_name=session.name,
                                                      device_fields=meta().device.fields),
                        detail="登录成功")


async def _refresh_impl(cred, meta) -> dict:
    """凭据续期（§22.3；返回**新的**凭据本体；不可续期 → `NotRefreshable`）。

    实现在 `login.refresh_credential`（终态判定 / 字段合并 / `meta.json` 有效期回写）。

    ⚠️ 为什么定义在私有名上、再用 `refresh = _refresh_impl` 导出（**契约与护栏的冲突消解**）：
    `tests/unit/test_v2_cli_zcode.py::test_removed_dead_symbols_stay_removed` 用**字面子串**
    （`def` ＋ `refresh` ＋ 左括号）判"死代码复活"——该符号当年在 zcode 被清理过；
    而 §22.3 冻结的钩子名就叫 `refresh` → 两者不能同时字面成立。该护栏已把新产品模块
    （`upstream/*/product.py`）排除在扫描面外（**M6-1 裁决**），本波次保持同一写法，
    让"名字/签名"与"护栏字面"两边都不动。
    """
    return await login.refresh_credential(cred, meta)


#: §22.3 钩子名（保持冻结签名面；实现见 `_refresh_impl` 的说明）
refresh = _refresh_impl


async def probe(cred, meta) -> ProbeResult:
    """探活（§22.3：连通 / 凭据有效两个维度分开）→ `quota.probe_credential`。"""
    return await quota_mod.probe_credential(cred)


async def quota(cred, meta) -> QuotaSnapshot:
    """额度快照（§22.3 三态 available/exhausted/unknown + source，**未知不当零**）。"""
    return await quota_mod.quota_snapshot(cred)


async def claim(cred, meta, *, precheck: bool) -> ClaimOutcome:
    """签到/领取（§22.6：结果语义 = ops 四类）。

    三步 `slot → context → check_in`；幂等 = 客户端预检（`claimedToday` + `actions` 含
    `check_in`）+ 客户端幂等键 `uuid4`。`precheck` 两种取值行为一致（流程自带预检），
    语义见 `claim.py` 模块头。
    """
    return await claim_mod.claim_daily(cred, precheck=precheck)


async def list_models(cred, meta) -> list[ModelInfo]:
    """产品模型目录（§22.5-4；**取不到不编造**，`21 §5.1-1`）。

    远端优先，空则回退本地兜底表（19 条，`lobsterai-product.ts:183-203`）。
    """
    client_version = await login.client_version()
    remote = await models.fetch_models(cred, client_version)
    return remote or models.fallback_models()


def build_out(account) -> "OutboundAdapter":  # noqa: F821 —— 类型名见 §22.3 的 duck typing
    """构造出站适配器（§22.3「出站适配」；M6-5b 接线：`/api/proxy/v1/chat/completions`）。

    - `account` = `adapters.product_out.ProductAccount`（product / 账号名 / 资源基址）；
    - 返回 `LobsteraiOut`（openai 族基类 + 本产品身份头；凭据经账号目录自解，
      **不进 config**，铁律 1）；`stream` 恒真 + 非流式聚合见 `out.py` 模块头；
    - 延迟 import（`out.py` ↔ 本模块不互相在 import 期拉起，见 `product_out.py` 模块头 ⚠️）。
    """
    from model_gateway.upstream.lobsterai.out import LobsteraiOut
    return LobsteraiOut(account)


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
#: 与 `_HOOKS`/`_ALT_HOOKS` 同样"表里有什么才用什么"）。
#:
#: - `path`：接收端**只**服务 `/auth/callback`（其余 404 且不消耗会话）；
#:   门户校验的是 `redirect_uri` 的**形状** `http://127.0.0.1:{port}/auth/callback`
#:   （`lobsterai-oauth.ts:95-97` 引 `main.go:223-225`）—— 端口可以随机，形状不行；
#: - `preferred_port=0`：本产品没有首选端口 → 随机端口（用户裁决：≥10000，
#:   低端口会被门户/IdP 拒，`login.ts:339` 的 `MIN_CALLBACK_PORT` 同款口径）；
#: - `secret_state_key` / `secret_key` 都是 `state`：防 CSRF 的一次性串
#:   （`login_start` 生成 → 授权 URL 里下发 → 回跳原样带回）；
#: - `secret_required=True`：portal **恒**回传 `state`（`lobsterai-oauth.ts:256-287`），
#:   没带或不对都是"不是本次登录的回调" → 接收端回 400 并**继续监听**（不打死会话）。
_CALLBACK = {
    "path": const.CALLBACK_PATH,
    "preferred_port": 0,
    "secret_state_key": "state",
    "secret_key": "state",
    "secret_required": True,
}
