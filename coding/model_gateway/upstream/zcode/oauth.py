"""ZCode OAuth 登录与凭据读写（tech-design v2.0 §17 / `12` §④；M6-3 补入 CLI 设备流）。

🔴 **范围声明**：本模块做「**读取本机已有凭据**」「**凭据 map 的组装/读写**」与
「**CLI 设备授权流的发起/轮询/回跳换取**」（`12 §④` 两条通道），
**不实现浏览器自动化**（§20 #16 不做 GUI 自动化）。

🔴 **设备流是「服务端中介」的，但授权页的落点必须被改写**（M7-D 修正）：
`/oauth/cli/init` 返回的 `authorize_url` 里，服务端把回跳参数写成了**它自己的回跳地址**
（provider `bigmodel` 用 `redirect`、`zai` 用 `redirect_uri`）。两家参考实现都在把它
交给用户之前**剥掉这个参数、重新挂上官方桥接页**
（`Z-Accounts-Gateway/src-tauri/src/oauth.rs:127-149`，理由原文见 `:129-131`：
不改写则授权完成后**永远到不了**捕获方；`ZCode-Panel/oauth.js:16-22,66-72` 同口径）：

    https://zcode.z.ai/app/oauth/login?redirect=zcode%3A%2F%2Foauth%2Fcallback&app_version=<ver>

于是**主通道 = 轮询**（用户在任意浏览器授权完，服务端自己知道结果），
**副通道 = 回跳捕获**（本机接收端 / 地址栏粘贴拿到 `code`+`state` → `POST /oauth/token`
换取凭据，`oauth.rs:364-399` / `ZCode-Panel/oauth.js:148-185`）。两条通道赛跑时
由「flow is still mine」守卫保证**只落一次盘**（`login.py`）。
DSH `zcode-login.ts` 只做轮询、不改写也不报错（它从不指望回调），
所以"服务端中介 ⇒ 不需要改写"这个推断是**错的** —— 原注即据此写下，现已更正。

- 凭据文件：`~/.zcode/v2/credentials.json`（扁平 map，值多为 `enc:v1:`）
  关键键：`oauth:active_provider` / `oauth:<p>:access_token` / `oauth:<p>:refresh_token` /
  `oauth:<p>:user_info` / **`zcodejwttoken`**（调计费/权益接口的**唯一正确 token**）
- **`refresh` 未落地**（本轮清理死代码）：§17 的续期属 **M4-3 双通道鉴权**，
  判据本身是"手工 / 待实测 T5a/T5b"；首期凭据一律来自 `mgw zcode import`
  导入的本机已登录缓存 → 无调用点的实现不保留（需要时按 `12` §4.5 补，不自己发明）
- 🔴 **`login()` 软占位已删除**（2026-09-30，M6 后续收口）：`mgw zcode login` 改走下面的
  设备流（`cli_init`/`cli_poll`；`model_gateway/cli_zcode.py::_login`）后，它是**零调用点**
  的旧占位 —— 仓内接线护栏（`tests/unit/test_v2_wiring_guard.py`）按"无引用即死代码"
  判红，且它那句"请用 `mgw zcode import`"的指引与真实流程相矛盾。程序化登录入口若将来
  需要，按 `12 §④` 的设备流补实现，**不恢复占位**（配套的 `LoginResult` 一并删除）。
- Z.ai 邮箱注册通道**已关闭**（§20 #9）→ `providers()` 不暴露它
"""

from __future__ import annotations

import json
import secrets
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import httpx

from model_gateway.accounts.net import make_client
from model_gateway.accounts.store import atomic_write_json
from model_gateway.upstream.zcode import auth, crypto
from model_gateway.upstream.zcode.auth import Credentials

#: 默认客户端数据目录（可用 `MGW_ZCODE_HOME` 覆盖）
DEFAULT_ZCODE_HOME = Path.home() / ".zcode" / "v2"


#: Z.ai 邮箱注册已关闭（§20 #9）—— 仅保留 bigmodel 网页登录
PROVIDERS = ("bigmodel", "zai")


def zcode_home() -> Path:
    import os
    raw = os.environ.get("MGW_ZCODE_HOME")
    return Path(raw) if raw else DEFAULT_ZCODE_HOME


def read_credentials(home: Path | None = None) -> dict:
    """读取并**解密**凭据文件（值多为 `enc:v1:`）。

    `home` 可指向**任意账号的 v2 目录**（整根隔离下每账号一份）——
    `zcode_claim._credentials_of` 用它读该账号自己的凭据（而非主目录）。
    解密失败的值静默降级为空串（同参考实现 `safeDecrypt`）。
    """
    path = (Path(home) if home else zcode_home()) / "credentials.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    secret = crypto.current_secret()
    return {k: crypto.decrypt(v, secret=secret)
            for k, v in raw.items() if isinstance(k, str)}


def build_credentials(creds: dict) -> Credentials:
    """从解密后的凭据 map 构造 `Credentials`。

    ⚠️ 各项目对 `oauth:<p>:access_token` 的语义**不一致**（`12` §④.4）：
    有的存 zai OAuth 原始 token、有的存 business token。
    **调计费/权益接口一律用 `zcodejwttoken`** —— 用它才不会 401。
    """
    provider = str(creds.get("oauth:active_provider") or "")
    jwt = str(creds.get("zcodejwttoken") or "")
    api_key = ""
    if provider:
        api_key = str(creds.get(f"oauth:{provider}:access_token") or "")
    return Credentials(jwt=jwt, api_key=api_key, device_mid="", provider=provider)


# ==================== CLI 设备授权流（`12 §④`；DSH `zcode-login.ts` 实测跑通）====================

#: ZCode 平台 origin（设备授权流三端点同源；`12 §④` 一手 + DSH `zcode-login.ts:49`）
ZCODE_ORIGIN = "https://zcode.z.ai"
#: 发起授权：`POST /api/v1/oauth/cli/init`（`12 §④`＝`zcode-switch/oauth.rs:7`；DSH `:52`）
CLI_INIT_PATH = "/api/v1/oauth/cli/init"
#: 轮询授权结果：`GET /api/v1/oauth/cli/poll/{flow_id}`（`oauth.rs:118`；DSH `:55`）
CLI_POLL_PATH = "/api/v1/oauth/cli/poll/{flow_id}"
#: 回跳换取 token：`POST /api/v1/oauth/token`（`oauth.rs:5` + `ZCode-Panel/oauth.js:52,57,148-160`
#: 两家独立同源；body = `{provider, code, redirect_uri, state}`）
TOKEN_PATH = "/api/v1/oauth/token"
#: 官方桥接登录页（授权完成后落在这里，再由它把 `code` 转交 `zcode://` 自定义协议）
#: —— `oauth.rs:127-149` 的 `bridge_redirect_uri()` / `ZCode-Panel/oauth.js:66-72`
BRIDGE_LOGIN_PATH = "/app/oauth/login"
#: 桥接页内层转发目标（官方深链，`oauth.rs:22` 的 `REDIRECT_ENC` 解码后即此值）
DEEP_LINK_PREFIX = "zcode://oauth/callback"
#: 本机回跳接收端服务的**路径**（与官方深链 `/oauth/callback` 同形，便于两种投递共用一套解析）
CALLBACK_PATH = "/oauth/callback"
#: 🔴 各 provider 授权 URL 里**要被改写的回跳参数名**（`oauth.rs:129-131` 逐字：
#: `zai` → `redirect_uri`；`bigmodel` → `redirect`。写错一个字母就是"授权页正常、
#: 回跳打到厂商"的静默失败，所以这张表是判据而不是备忘）
REDIRECT_PARAM_BY_PROVIDER = {"bigmodel": "redirect", "zai": "redirect_uri"}
#: 客户端身份版本（与 `auth.build_headers` / `claim._headers` 的默认值同源，§17）
DEFAULT_APP_VERSION = "3.11.2"
#: 上游超时（秒）：发起 30 / 轮询 20 / 换取 20（DSH `zcode-login.ts:169,251` 两条 AbortSignal 的取值）
INIT_TIMEOUT_S = 30.0
POLL_TIMEOUT_S = 20.0
#: `poll_interval_sec` 缺省/非法时的兜底（DSH `:214-216`：≥1 秒才采纳，否则 2 秒）
DEFAULT_POLL_INTERVAL_S = 2.0
#: 轮询间隔下限（`oauth.rs:164`：`poll_interval_ms < 1000` 判整条流程无效）——
#: 亚秒轮询对上游是打点攻击，服务端也不会给这种值
MIN_POLL_INTERVAL_S = 1.0
#: 设备流程的**文档化生存期**上限（`oauth.rs:6` `FLOW_TIMEOUT_MS = 300_000` = 5 分钟）：
#: 服务端 `expires_at` 与 HTTP `Date` 同一个时钟，两者之差才是可信的相对 TTL（见 `_local_deadline`）
FLOW_TIMEOUT_S = 300.0
#: 服务端"流程已过期"的业务码（`oauth.rs:203-205`：poll 拿到 3004 → 判过期，不再重试）
POLL_CODE_EXPIRED = 3004


#: 官方客户端凭据文件的**基键** —— `read_credentials`/`build_credentials` 认这两个
#: （provider 作用域的三键 `oauth:<provider>:access_token|refresh_token|user_info`
#: 由 `_provider_token_key` 拼，读写同源）
KEY_ACTIVE_PROVIDER = "oauth:active_provider"
KEY_JWT = "zcodejwttoken"


def _provider_token_key(provider: str, kind: str) -> str:
    """`oauth:<provider>:<kind>` —— 官方凭据文件的键名口径（读写同源）。"""
    return f"oauth:{provider}:{kind}"


def _msg_of(body: object) -> str:
    """响应里的可读原因（`msg`/`message` 二选一；都不是字符串时给空串）。"""
    if isinstance(body, dict):
        for key in ("msg", "message"):
            text = str(body.get(key) or "").strip()
            if text:
                return text
    return ""


def _json_body(resp: httpx.Response) -> dict:
    """读 JSON 体；非 JSON / 非对象 → 空 dict（**不因解析失败丢掉 HTTP 事实**）。"""
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


@dataclass
class DeviceFlow:
    """一次 CLI 设备授权流程（`cli_init` 的产物；**轮询私钥不出本进程**）。"""

    flow_id: str
    authorize_url: str
    provider: str = "bigmodel"
    #: 本次流程的 CLI 会话密钥（官方的 `UH(32).toString("hex")`；轮询 Bearer 用它）
    flow_secret: str = ""
    #: 官方的并发保护令牌（DSH 实测：轮询**不带**它也返回 200）→ 只留作诊断
    poll_token: str = ""
    #: 🔴 服务端授权 URL 里的 `state`（**从服务端 URL 取**，不本地生成，
    #: `oauth.rs:150-157`）：回跳投递的关联串 + `POST /oauth/token` 的 body 都要它。
    #: `parse_cli_init` 缺它会**当场判非法**，所以空串只可能出现在手工构造的
    #: `DeviceFlow` 上（= 单测替身）；此时 `cli_exchange` 不做 state 比对（无据可比）。
    state: str = ""
    #: 🔴 本次流程使用的**设备码**（`X-Device-Mid`；`login_start` 之前定好，
    #: 与最终 `meta["device_mid"]` 同一个值 —— 两份身份不一致 = 上游眼里的"换设备"）
    device_mid: str = ""
    #: 本地**截止时刻**（unix 秒；0 = 未给出。已按服务端 `Date` 做过时钟偏移校正，
    #: 见 `_local_deadline`）
    expires_at: float = 0.0
    #: 官方建议的轮询间隔（秒；恒 ≥ `MIN_POLL_INTERVAL_S`）
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S

    def expired(self, now_s: float | None = None) -> bool:
        """流程是否已被服务端作废（**在本地超时之前就收敛**，DSH `zcode-login.ts:378-381`）。

        ⚠️ 不给 `expires_at` 设本地下限：服务端说只剩 3 秒就只等 3 秒 ——
        否则用户明明已无法授权，我们还在空转，最后报"超时"而不是"已过期"。
        """
        if not self.expires_at:
            return False
        return (time.time() if now_s is None else now_s) >= self.expires_at


@dataclass
class DevicePoll:
    """设备流**一次轮询**的结果（协议层；`state="pending"` 不是错误，§22.3）。"""

    #: `pending`（等用户）/ `ready`（拿到凭据）/ `failed`（终态拒绝）/ `expired`（流程过期）
    state: str
    detail: str = ""
    #: `ready` 时：官方客户端格式的凭据 map（`credential_map` 组装）
    credentials: dict = field(default_factory=dict)
    #: `ready` 时：`data.user`（展示名/uid 的镜像来源；**不含凭据**）
    user_info: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CallbackParams:
    """一次**回跳**里解析出来的东西（`parse_callback_url`；只含 code/state，不含凭据）。"""

    #: 授权码（官方 `authCode` 优先、`code` 兜底，`oauth.rs:266-268` / `Panel oauth.js:110`）
    code: str = ""
    #: 服务端下发的关联串（必须等于 `DeviceFlow.state`，否则不是本次登录的回跳）
    state: str = ""
    #: 只带渠道归因参数（`channel_id`/`utm_*`）而无 code：官方按**软失败**处理
    #: （`oauth.rs:278-281` 的 `Attribution` → `lib.rs:1686` `deeplink_err_soft`）
    attribution_only: bool = False


def build_flow_secret() -> str:
    """本次流程的 CLI 会话密钥（官方 `UH(32).toString("hex")` = 32 字节 hex）。

    ⚠️ 它**不是**用户凭据：官方的 `/oauth/cli/init` 就是拿这个自生成密钥做 Bearer。
    """
    return secrets.token_hex(32)


def _bridge_redirect_uri(app_version: str = DEFAULT_APP_VERSION) -> str:
    """官方**桥接登录页**地址（`oauth.rs:24-27` 的 `bridge_redirect_uri()` 逐字对齐）。

    ```
    https://zcode.z.ai/app/oauth/login?redirect=zcode%3A%2F%2Foauth%2Fcallback&app_version=<ver>
    ```
    🔴 为什么必须用它（`oauth.rs:129-131` 原文）：服务端给的 `authorize_url` 里回跳参数
    指向**厂商自己的回调**，那样的授权页走完后永远不会导航到捕获方 ——
    换成桥接页才有 `zcode://oauth/callback`（或桥接页自身 query 里的 `code`）可接
    （`ZCode-Panel/main.js:1978-1986`：捕获侧同时接受深链与桥接页两种形态）。
    """
    inner = quote(DEEP_LINK_PREFIX, safe="")            # → zcode%3A%2F%2Foauth%2Fcallback
    return (f"{ZCODE_ORIGIN}{BRIDGE_LOGIN_PATH}"
            f"?redirect={inner}&app_version={quote(app_version, safe='')}")


def rewrite_authorize_url(url: str, provider: str,
                          app_version: str = DEFAULT_APP_VERSION) -> str:
    """把服务端给的 `authorize_url` 改写成桥接页形态（`oauth.rs:127-149`）。

    做法与参考实现一致：**剥掉**该 provider 的回跳参数（`redirect` / `redirect_uri`），
    其余参数**原序保留**，再把桥接地址作为该参数**追加到末尾**。
    provider 不在表里（未来新线路）→ 原样返回，不猜参数名（`oauth.rs:131` 的 `_ => None`）。
    """
    key = REDIRECT_PARAM_BY_PROVIDER.get(provider)
    if not key:
        return url
    split = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(split.query, keep_blank_values=True) if k != key]
    kept.append((key, _bridge_redirect_uri(app_version)))
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(kept), split.fragment))


def _server_date_s(resp: httpx.Response) -> float | None:
    """HTTP `Date` 头 → unix 秒（`oauth.rs:100-103`：解析失败按缺失处理）。"""
    raw = resp.headers.get("date") or ""
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.timestamp()


def _local_deadline(expires_at_s: float, server_date_s: float | None,
                    now_s: float) -> float:
    """🔴 时钟偏移安全的本地截止时刻（`oauth.rs:56-72` 的 `local_flow_deadline`）。

    服务端 `expires_at` 与它自己的 HTTP `Date` **共用一个时钟**，所以「两者之差」才是
    可信的相对 TTL；本机时钟偏移时直接拿 `expires_at - 本机 now` 会误判（早到判过期、
    晚到判无限）。三条分支（与参考实现同一口径，另加两条本机既有事实）：

    - 没给 `expires_at` → 0（= 不设本地截止，**本仓既有语义**，DSH 实测同此）；
    - 给了 `expires_at` 但 `Date` 缺失/无法解析 → **原样按绝对时刻采纳**
      （本仓既有测试与 `mgw zcode login` 都依赖"服务端说已过就是已过"，不因缺 Date 放宽）；
    - 两者都有 → `now + min(expires_at - date, FLOW_TIMEOUT_S)`；差值非正 = 服务端
      自己的两个值都说这条流程已经死了 → 立即过期（不空转）；差值 > 2×5 分钟 =
      明显不一致 → 退回官方文档的 5 分钟流程（`oauth.rs:63-67`）。
    """
    if not expires_at_s:
        return 0.0
    if server_date_s is None:
        return expires_at_s
    remaining = expires_at_s - server_date_s
    if remaining <= 0:
        return now_s
    if remaining > FLOW_TIMEOUT_S * 2:
        return now_s + FLOW_TIMEOUT_S
    return now_s + min(remaining, FLOW_TIMEOUT_S)


def _query_of(url: str) -> dict[str, str]:
    """URL 查询参数（百分号解码后；同键多值取首个）。

    ⚠️ **两段都看**：桥接页/门户可能用 hash 路由（`…/#/?code=…`），只读 `?` 前那段会
    把"其实带了 code 的回跳"误判成"没带"（`ZCode-Panel` 的 hash 路由同一教训，
    见 `tests/integration/test_m7_callback_capture.py::query_of`）。
    """
    split = urlsplit(url)
    raw = split.query
    if not raw and "?" in split.fragment:
        raw = split.fragment.split("?", 1)[1]
    return {k: v for k, v in parse_qsl(raw, keep_blank_values=True)}


def parse_callback_url(url: str) -> CallbackParams:
    """解析**回跳**（深链 / 桥接页 / 本机接收端三种形态同一套判据）。

    两家参考实现的口径合并（逐条对应）：
    - `oauth.rs:255-283`：`zcode://oauth/callback?...` → `authCode` 优先、`code` 兜底、
      `state` 必到；只带 `channel_id`/`utm_*` → 归因软失败；
    - `ZCode-Panel/main.js:1978-1986`：**同时接受 `zcode://…` 与 https 桥接页**，
      因为桥接页在自己的 query 里就带着 `code`（深链没落到系统时它是唯一来源）；
      `oauth.js:100-113` 对 scheme 不作限制（任意绝对 URL，只要带 `code`+`state`），
      于是本机接收端 `http://127.0.0.1:{port}/oauth/callback?…` 也走同一个解析器。
    """
    text = str(url or "").strip()
    if not text:
        return CallbackParams()
    query = _query_of(text)
    code = (query.get("authCode") or query.get("code") or "").strip()
    state = (query.get("state") or "").strip()
    if not code and any(query.get(k) for k in ("channel_id", "utm_source", "utm_campaign")):
        return CallbackParams(state=state, attribution_only=True)
    return CallbackParams(code=code, state=state)


def _os_category() -> str:
    """`X-Os-Category`（参考实现 = `std::env::consts::OS` → `macos`/`windows`/`linux`）。"""
    return {"darwin": "macos", "win32": "windows", "cygwin": "windows"}.get(sys.platform,
                                                                            sys.platform)


def _client_timezone() -> str:
    """`X-Client-Timezone` = IANA 时区名（`quota.rs:103-106`）；拿不到就照参考回 `unknown`。"""
    try:
        key = getattr(datetime.now().astimezone().tzinfo, "key", None)
    except (OSError, ValueError):          # 无 tzdata / 时区配置坏：不是故障，是"取不到"
        key = None
    return key if isinstance(key, str) and key else "unknown"


def _client_headers(*, bearer: str, app_version: str, device_mid: str,
                    content_type: bool = True) -> dict:
    """🔴 官方客户端**全套**身份头（`quota.rs:171-196` 的 `zai_headers_with_version`）。

    此前 `cli_init`/`cli_poll` 只发了五六个头（`X-Title`/`X-Client-Timezone`/
    `X-Os-Category`/`X-Os-Version`/`X-Device-Mid`/`x-request-id` 全缺）
    —— 上游按"客户端指纹齐全度"放行时，缺头就是"这台机器不是 ZCode"的证据。
    三处调用（init / poll / token）一律从这里取，不再各写一份。

    ⚠️ `X-Platform` / `X-Client-Language` / `X-Release-Channel` **不在此重复字面量**：
    它们的事实源是 `auth.EXTRA_HEADERS`（领取 / 额度 / 出站三条线共用同一份，§17），
    这里只补 OAuth 这条线独有的那几个头 —— 两处各写一份迟早会漂。

    `bearer` 为空时**不发** `Authorization`（对齐 `oauth.rs:370-375`：`/oauth/token`
    这条线官方就是不带 Bearer 的，带着空 `Bearer ` 反而被拒）。
    """
    headers = {
        **auth.EXTRA_HEADERS,
        "User-Agent": f"ZCode/{app_version}",
        "HTTP-Referer": ZCODE_ORIGIN,
        "X-Title": "Z Code@electron",
        "X-ZCode-App-Version": app_version,
        "X-Client-Timezone": _client_timezone(),
        "X-Os-Category": _os_category(),
        "x-request-id": str(uuid.uuid4()),
    }
    release = _platform_release()
    if release:
        headers["X-Os-Version"] = release
    if device_mid:
        headers["X-Device-Mid"] = device_mid
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    if content_type:
        headers["Content-Type"] = "application/json"
    return headers


def _platform_release() -> str:
    """`X-Os-Version` = `uname -r`（`quota.rs:69-78`）；取不到给空串（**不编造**）。"""
    import os

    try:
        return (os.uname().release or "").strip()
    except (AttributeError, OSError):      # Windows 无 `uname`：该头**不发**（参考实现同口径）
        return ""


def parse_cli_init(body: dict, *, flow_secret: str = "",
                   provider: str = "bigmodel", device_mid: str = "",
                   server_date_s: float | None = None,
                   now_s: float | None = None) -> DeviceFlow:
    """`POST /oauth/cli/init` 响应 → `DeviceFlow`（缺 `flow_id`/`authorize_url` → ValueError，**不猜**）。

    响应形态（`12 §④` 第 1 步 + DSH `zcode-login.ts:183-225` 实测）：

    ```
    { code: 0, data: { flow_id, poll_token?, authorize_url, expires_at, poll_interval_sec } }
    ```

    🔴 本函数**必须**做两件参考实现做、我们此前漏掉的事（`oauth.rs:127-170`）：
    ① 把 `authorize_url` 的回跳参数改写成官方桥接页（见 `rewrite_authorize_url`）；
    ② `state` **从服务端给的 URL 里取**（不本地生成 —— 自己造的 state 服务端不认，
       回跳换取 token 必然被拒）。缺 `state` 判整条流程无效：那是一条永远换不到
       凭据的"半可用"流程，报错比让用户白点一次授权诚实。
    ③ 非 https、轮询间隔 ≥ 流程剩余时间 一律拒绝（`oauth.rs:164-166`）。
    """
    data = body.get("data") if isinstance(body, dict) and isinstance(body.get("data"), dict) else {}
    flow_id = str(data.get("flow_id") or "").strip()
    url = str(data.get("authorize_url") or "").strip()
    if not flow_id:
        raise ValueError(f"授权初始化响应缺 flow_id（{_msg_of(body) or '无说明'}）")
    if not url.startswith("https://"):
        raise ValueError("授权初始化响应缺合法的 authorize_url")
    now = time.time() if now_s is None else now_s
    expires_raw = data.get("expires_at")
    expires = float(expires_raw) if isinstance(expires_raw, (int, float)) \
        and not isinstance(expires_raw, bool) else 0.0
    deadline = _local_deadline(expires, server_date_s, now)
    interval_raw = data.get("poll_interval_sec")
    interval = float(interval_raw) if isinstance(interval_raw, (int, float)) \
        and not isinstance(interval_raw, bool) and interval_raw >= MIN_POLL_INTERVAL_S \
        else DEFAULT_POLL_INTERVAL_S
    interval = max(interval, MIN_POLL_INTERVAL_S)       # 🔴 ≥1s 地板（`oauth.rs:164`）
    remaining = (deadline - now) if deadline else 0.0
    if 0.0 < remaining <= interval:
        # 轮询间隔比整条流程还长 = 永远轮不到结果（`oauth.rs:164` 的 `interval >= remaining`）。
        # ⚠️ `remaining <= 0`（服务端说的过期时刻**已经过去**）不在这里判"响应非法"：
        #    那是一条正常响应 + 一条已死的流程，正确结局是 `expired`（文案"请重新发起登录"），
        #    由 `cli_poll` 用 `DeviceFlow.expired()` 收口 —— 本仓既有用例与
        #    `mgw zcode login` 都依赖这条区分（参考实现在这里给的是同一个 `invalid()`，
        #    但它没有"过期 vs 非法"两种文案的分档，不必照抄）。
        raise ValueError(f"授权初始化响应非法：轮询间隔 {interval}s ≥ 流程剩余 {remaining:.0f}s")


    authorize_url = rewrite_authorize_url(url, provider)
    state = (_query_of(authorize_url).get("state") or "").strip()
    if not state:
        raise ValueError("授权初始化响应非法：authorize_url 里没有 state"
                         "（回跳换取 token 需要它；缺了这条流程只能靠轮询收敛）")
    return DeviceFlow(
        flow_id=flow_id, authorize_url=authorize_url, provider=provider,
        flow_secret=flow_secret, poll_token=str(data.get("poll_token") or ""),
        state=state, device_mid=str(device_mid or ""),
        expires_at=deadline, poll_interval_s=interval)


def credential_map(*, provider: str, jwt: str, access_token: str, refresh_token: str = "",
                   user_info: dict | None = None) -> dict:
    """按**官方客户端凭据文件**的键名组装凭据 map（读写同源：`read_credentials`/`build_credentials`）。

    - `zcodejwttoken`：调计费/权益接口的**唯一正确 token**（`12 §④.4`）；
    - `oauth:active_provider` + `oauth:<provider>:access_token`：API Key 通道（`build_credentials` 的 api_key 来源）；
    - `oauth:<provider>:user_info`：**JSON 字符串**（官方客户端同形）——
      `ops/builtin/zcode_claim._credentials_of` 对它做 `json.loads` 取 `id`/`user_id`，
      存成对象会静默取不到 user_id（激活事件体必需）。
    ⚠️ 值一律**明文**（铁律 1：本地明文，不入库、不硬编码）。
    """
    out = {
        KEY_ACTIVE_PROVIDER: provider,
        KEY_JWT: jwt,
        _provider_token_key(provider, "access_token"): access_token,
    }
    if refresh_token:
        out[_provider_token_key(provider, "refresh_token")] = refresh_token
    if user_info:
        out[_provider_token_key(provider, "user_info")] = json.dumps(user_info, ensure_ascii=False)
    return out


def write_client_credentials(home: Path, creds: dict) -> Path:
    """把凭据写进**该账号自己的**客户端数据根（`<home>/credentials.json`，明文；原子写）。

    🔴 为什么需要它（两处落盘并存的现实，§22.3 ③「产品私有文件经 meta['dir'] 读写」）：
    既有 zcode 取数路径（`ops/builtin/zcode_claim` 的凭据解析、额度日志、`mgw zcode launch`
    启动的客户端）都读**客户端数据根**；而 §22.3 的凭据落盘走账号目录顶层
    `credentials.json`（`store.commit_login`）。设备流登录成功后两份都写，
    账号才对"钩子层"与"既有 SDK/客户端路径"同时可用 —— 半可用比不可用更难查。

    ⚠️ `home` **必须**是该账号的 `data/.zcode/v2`（`dataroot.v2_dir_of`）——
    绝不写客户端主 `~/.zcode/v2/`（§15.3 整根隔离；`MGW_ZCODE_HOME` 只影响读的默认值）。
    """
    path = Path(home) / "credentials.json"
    atomic_write_json(path, dict(creds or {}))
    return path


async def cli_init(provider: str = "bigmodel", *,
                   app_version: str = DEFAULT_APP_VERSION,
                   device_mid: str = "") -> DeviceFlow:
    """发起设备授权：拿到**改写过的** `authorize_url`（`12 §④` 第 1 步；DSH 实测 HTTP 200）。

    ```
    POST {origin}/api/v1/oauth/cli/init
      <全套 z.ai 客户端头>                                 # 见 `_client_headers`
      Authorization: Bearer <本次自生成的会话密钥>          # 不是用户凭据
      X-Device-Mid: <本次登录定下的设备码>                  # 🔴 必须在**流程开始之前**定好
      body: {"provider": "bigmodel"}
    → { flow_id, authorize_url, poll_token?, expires_at, poll_interval_sec }
    ```

    🔴 `device_mid` 由调用方（`product.login_start`）**在发起之前**按 §15.1 定案并透传：
    init 与 poll 打的是同一个身份，流程中途换码 = 上游眼里的"换设备"（§15.1 硬约束 3）。
    传空 = 该产品路径没有设备身份（`mgw zcode login` 旧 CLI 路径，见 `_login`），
    此时**不发**该头（参考实现 `quota.rs:187-189` 同口径：`Some(mid)` 才发）。

    上游不可用 → 抛异常（**不返回"假成功"**：登录向导据此显示真实原因）。
    """
    if provider not in PROVIDERS:
        raise ValueError(f"不支持的 provider：{provider}（在册：{'/'.join(PROVIDERS)}）")
    flow_secret = build_flow_secret()
    headers = _client_headers(bearer=flow_secret, app_version=app_version,
                              device_mid=device_mid)
    async with make_client(base_url=ZCODE_ORIGIN, timeout=INIT_TIMEOUT_S) as client:
        resp = await client.post(CLI_INIT_PATH, json={"provider": provider}, headers=headers)
    body = _json_body(resp)
    if not resp.is_success:
        raise RuntimeError(
            f"ZCode 设备授权发起失败（HTTP {resp.status_code}）：{_msg_of(body) or '无响应体'}")
    return parse_cli_init(body, flow_secret=flow_secret, provider=provider,
                          device_mid=device_mid, server_date_s=_server_date_s(resp))


async def cli_poll(flow: DeviceFlow, *,
                   app_version: str = DEFAULT_APP_VERSION) -> DevicePoll:
    """轮询一次授权结果（`12 §④` 第 3 步；**一次调用 = 一次上游请求**，pending 不是错误）。

    状态机（DSH `zcode-login.ts:235-337` 实测 + `oauth.rs:187-240` `poll_flow_once`）：

    | 上游情形 | 本项目状态 | 理由 |
    |---|---|---|
    | 网络错误 / 5xx / 408 / 429 | `pending` | 抖动不是失败：由会话 TTL 收敛（官方同口径 `:252-270`） |
    | HTTP 4xx（除 408/429） | `failed` | **终态拒绝**（`oauth.rs:191-200` 原式） |
    | 业务码 `3004` | `expired` | 流程已被服务端作废（`oauth.rs:201-205`），继续等只是空转 |
    | `data.status = pending` | `pending` | 用户还没在浏览器完成授权 |
    | `data.status = failed` | `failed` | 用户拒绝 / 授权失败 |
    | `data.status = ready` | `ready`* | `token` + `{provider}.access_token` + `user.user_id` **三件齐全**才成立 |
    | 其它 / 无法识别 | `failed` | **不拿未知状态当成功**（`21 §5.1-1` 同向） |
    | 服务端 `expires_at` 已过 | `expired` | 不空转（`DeviceFlow.expired`） |

    *缺件 → `failed`：落盘半个响应会得到"登录了却调不通"的账号。
    """
    if flow.expired():
        return DevicePoll(state="expired",
                          detail="授权流程已过期（服务端 expires_at 已过），请重新发起登录")
    path = CLI_POLL_PATH.format(flow_id=quote(flow.flow_id, safe=""))
    headers = _client_headers(bearer=flow.flow_secret, app_version=app_version,
                              device_mid=flow.device_mid, content_type=False)
    try:
        async with make_client(base_url=ZCODE_ORIGIN, timeout=POLL_TIMEOUT_S) as client:
            resp = await client.get(path, headers=headers)
    except httpx.HTTPError as e:
        return DevicePoll(state="pending",
                          detail=f"轮询网络抖动（继续等待）：{type(e).__name__}")
    body = _json_body(resp)
    if _is_expired_code(body):
        # 🔴 3004 与"HTTP 4xx"谁先到都判同一件事：流程已死（`oauth.rs:201-205` 把它
        #    单列成 `err.oauth.expired`，与 `poll_terminal` 分开）—— 文案必须能区分，
        #    否则用户以为是自己点慢了，其实服务端已经不再接受这条流程。
        return DevicePoll(state="expired",
                          detail=f"授权流程已过期（服务端 code={POLL_CODE_EXPIRED}："
                                 f"{_msg_of(body) or '无说明'}），请重新发起登录")
    if 400 <= resp.status_code < 500 and resp.status_code not in (408, 429):
        return DevicePoll(state="failed",
                          detail=f"轮询被服务端拒绝（HTTP {resp.status_code}）："
                                 f"{_msg_of(body) or '无响应体'}")
    if not resp.is_success:
        return DevicePoll(state="pending",
                          detail=f"上游暂不可用（HTTP {resp.status_code}），继续等待")
    code = body.get("code")
    if code not in (0, None, "0"):
        return DevicePoll(state="pending",
                          detail=f"上游返回 code={code}（{_msg_of(body) or '无说明'}），继续等待")
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    status = str(data.get("status") or "")
    if not status or status == "pending":
        return DevicePoll(state="pending", detail="等待用户在浏览器完成授权")
    if status == "failed":
        return DevicePoll(state="failed", detail="用户在授权页拒绝或授权失败（服务端 status=failed）")
    if status != "ready":
        return DevicePoll(state="failed",
                          detail=f"轮询响应状态无法识别：{status!r}（不拿未知状态当成功）")
    return _ready_poll(data, flow.provider)


def _is_expired_code(body: dict) -> bool:
    """业务码是不是"流程已过期"（3004；`oauth.rs:201-205`，HTTP 状态与业务码两处都要看）。"""
    code = body.get("code") if isinstance(body, dict) else None
    return code == POLL_CODE_EXPIRED or code == str(POLL_CODE_EXPIRED)


def _access_token_of(data: dict, provider: str) -> tuple[str, str]:
    """`(access_token, refresh_token)`（`oauth.rs:531-546` + `Panel oauth.js:132-146`）。

    取值顺序照两家参考实现的合并结果：`data.<provider>.access_token|accessToken` →
    `data.access_token|accessToken`（bigmodel 线路的回退链；zai 只看自己的分组）。
    """
    def pick(bag: dict) -> tuple[str, str]:
        access = str(bag.get("access_token") or bag.get("accessToken") or "").strip()
        refresh = str(bag.get("refresh_token") or bag.get("refreshToken") or "").strip()
        return access, refresh

    block = data.get(provider) if isinstance(data.get(provider), dict) else {}
    access, refresh = pick(block)
    if not access and provider != "zai":
        access, _ignored = pick(data)
    return access, refresh


async def cli_exchange(cb: CallbackParams, flow: DeviceFlow, *,
                       app_version: str = DEFAULT_APP_VERSION) -> DevicePoll:
    """🔴 回跳换取凭据（**副通道**；`oauth.rs:364-399` / `Panel oauth.js:148-185`）。

    ```
    POST {origin}/api/v1/oauth/token
      <全套 z.ai 客户端头，但**不带** Authorization>       # oauth.rs:370-375 逐字跳过该头
      body: {provider, code, redirect_uri: 桥接页地址, state}
    → { code:0, data:{ token, <provider>:{access_token,…}, user? } }
    ```

    判据（**与轮询同一收口**：`state` 必须等于本次流程的 state，否则不是这次登录的回跳）：
    - `code`/`state` 不齐或 state 不符 → `failed`，**不打上游**（拿别人的授权码去换 = 白送一次
      无效请求，还会把"串线"伪装成"上游拒绝"）；
    - 缺 `data.token` 或缺 `access_token` → `failed`（`oauth.rs:392-397` 的 `no_token` +
      `Panel oauth.js:177-179` 的缺 access_token 同一条判据）；
    - 网络/HTTP/业务码异常 → `failed` 带原因（副通道失败**不该**再拖一轮：主通道是轮询，
      它自己会收敛，本通道的职责就是"要么拿到、要么说清为什么没拿到"）。
    """
    if not cb.code or not cb.state:
        return DevicePoll(state="failed",
                          detail="回跳里没有 authCode/code + state，换不了凭据"
                                 "（请回到「接入账号资源」页用轮询结果，或重新发起登录）")
    if flow.state and cb.state != flow.state:
        return DevicePoll(state="failed",
                          detail="回跳与本次登录不匹配（state 不一致），已拒绝")
    body = {"provider": flow.provider, "code": cb.code,
            "redirect_uri": _bridge_redirect_uri(app_version), "state": cb.state}
    headers = _client_headers(bearer="", app_version=app_version,
                              device_mid=flow.device_mid)
    try:
        async with make_client(base_url=ZCODE_ORIGIN, timeout=POLL_TIMEOUT_S) as client:
            resp = await client.post(TOKEN_PATH, json=body, headers=headers)
    except httpx.HTTPError as e:
        return DevicePoll(state="failed",
                          detail=f"回跳换取凭据失败（网络：{type(e).__name__}）："
                                 "轮询通道仍在等，可直接等授权结果")
    data = _json_body(resp)
    if not resp.is_success:
        return DevicePoll(state="failed",
                          detail=f"回跳换取凭据被拒（HTTP {resp.status_code}）："
                                 f"{_msg_of(data) or '无响应体'}")
    code = data.get("code")
    if code not in (0, None, "0"):
        return DevicePoll(state="failed",
                          detail=f"回跳换取凭据被拒（code={code}）：{_msg_of(data) or '无说明'}")
    payload = data.get("data") if isinstance(data.get("data"), dict) else {}
    jwt = str(payload.get("token") or payload.get("zcodeJwtToken") or "").strip()
    access, refresh = _access_token_of(payload, flow.provider)
    user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    missing = [name for name, value in (("data.token", jwt),
                                        (f"data.{flow.provider}.access_token", access))
               if not value]
    if missing:
        return DevicePoll(state="failed",
                          detail=f"换取响应缺关键字段（{'/'.join(missing)}），不当作登录成功")
    return DevicePoll(
        state="ready",
        credentials=credential_map(provider=flow.provider, jwt=jwt, access_token=access,
                                   refresh_token=refresh, user_info=user),
        user_info=dict(user),
        detail="授权完成（回跳换取）")


def _ready_poll(data: dict, provider: str) -> DevicePoll:
    """`status=ready` 的齐备性校验 + 凭据组装（DSH `zcode-login.ts:300-318`）。

    三件**缺一不可**：`token`（zcode JWT）、`{provider}.access_token`、`user.user_id`
    （`oauth.rs:222-236` 同一判据）。
    """
    jwt = str(data.get("token") or "").strip()
    access, refresh = _access_token_of(data, provider)
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    uid = str(user.get("user_id") or user.get("id") or "").strip()
    missing = [name for name, value in (
        ("token", jwt), (f"{provider}.access_token", access), ("user.user_id", uid)) if not value]
    if missing:
        return DevicePoll(state="failed",
                          detail=f"轮询响应缺关键字段（{'/'.join(missing)}），不当作登录成功")
    return DevicePoll(
        state="ready",
        credentials=credential_map(provider=provider, jwt=jwt, access_token=access,
                                   refresh_token=refresh, user_info=user),
        user_info=dict(user),
        detail="授权完成")

