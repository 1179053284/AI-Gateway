"""ZCode 导入源适配与形态转换（Q31，2026-10-01）。

**单点职责**：把「一份外部凭据」转换成网关 `upstream/zcode/store.py::import_account`
可消费的**载荷**（`{"name", "device_mid", "credentials.json", "config.json", "meta"}`）——
本模块只做形态识别与转换（**纯函数、无网络、不落盘**）；设备冲突决策仍由
`store.import_account` 按 §15.1 三条硬约束执行（本模块不动那套决策顺序）。

三个来源（对应用户本机运行的两个 ZCode 账号工具 + 小店下发；参考实现**只读**，从不修改）：

| 来源 | 参考实现 | 形态 |
|---|---|---|
| ZCode-Panel 粘贴形态 | `ZCode-Panel/import-account.js:1-160` | `{name,jwt,device_mid}` 老格式 / `{family,credentials:{oauth:<f>:*}}` 新格式（小店新版下发）/ `{account:{…}}` 包装 / 别名键 `deviceMid|mid|token|jwtToken` |
| ZCode-Panel 账号库目录 | `settings.js:395-430`（目录解析）、`import-account.js:275`（valid 判据） | `<账号>/meta.json` + `data/.zcode/v2/{credentials.json,config.json}`（值已是 `enc:v1`） |
| zcode-switch 账号库 | `~/.zcode-switch/accounts/<uuid>.json`（实测形态） | `{id,name,created_at,updated_at,hash,credentials,config,virtual_device_mid,virtual_arms_uid}` |

🔴 三条转换纪律：

1. **面板账号库 / switch 文件 = 整份透传**：`credentials.json` / `config` 已是 `enc:v1:`
   （同机可解）——**绝不解密、绝不重加密**；只做键/形态校验（`import-account.js:221-253`
   的 verifyWritten 是值比较，跨机不可复制，这里取其「键在 + 形状对」的可移植子集）。
2. **粘贴形态 = 与面板逐字段对齐地转换**（`import-account.js:264-323`）：凭据值经
   `crypto.encrypt` 加密（客户端只认 `enc:v1:`）、config 按 `buildConfig`
   （`import-account.js:182-214`）组出**本家族**的 builtin provider、写前跑 `verifyWritten`
   等价自检（`:221-253`）——自检不过即**拒绝**（面板同款：宁可现在报错，不留一个
   "面板认为有效、客户端判未登录"的账号）。
3. **未知形态不得静默导入**（本模块只对已识别形态负责；调用方自行决定未识别对象
   是否回落既有直通路径）。

🔴 安全姿态（与面板同尺，`import-account.js:34-46`）：账号名白名单
`[A-Za-z0-9_-]{1,32}`（防目录穿越，第二道由 `accounts.store.sanitize_name` 兜底）、
粘贴形态 device_mid 必须 UUID、credential 键白名单
`^oauth:([a-z]+):(access_token|refresh_token|user_info)$`、`<32位hex>.<secret>` 形态的
请求签名密钥一律拒（按账号派生，带过来的是别人的）、凭据长度上限 200000。

⚠️ 与面板的**一处刻意收窄**：粘贴值已是 `enc:v1:` 前缀时**原样透传、不再加密**
（面板 `importAccount` 会二次加密，`import-account.js:290-292` —— 重加密会把客户端
解出的令牌变成 `enc:v1:…` 字面串，账号"显示但不可用"）；面板 `CRED_RE:42` 本就
接受该前缀，接受面不变，只修正包裹步骤。
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from model_gateway.accounts.store import sanitize_name
from model_gateway.upstream.zcode import crypto

# ---------- 面板同款校验尺（逐字对照 import-account.js:39-46）----------

#: 账号名白名单（防目录穿越；`import-account.js:39`）
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
#: 设备码必须是 UUID（粘贴形态；`import-account.js:40`）
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                     re.IGNORECASE)
#: jwt 三段点分形态（`import-account.js:41`）
JWT_RE = re.compile(r"^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
#: 凭据值形态前缀（`import-account.js:42`）
CRED_RE = re.compile(r"^(eyJ|sk-|enc:v1:)")
#: `<32位hex>.<secret>` 请求签名凭据：按账号派生，模板/卡片带过来的是别人的
#: （`import-account.js:44`）
SIGNING_KEY_RE = re.compile(r"^[0-9a-f]{32}\.[A-Za-z0-9_-]{8,}$")
#: credential 键白名单（`import-account.js:45`）
OAUTH_KEY_RE = re.compile(r"^oauth:([a-z]+):(access_token|refresh_token|user_info)$")
#: 单值长度上限（`import-account.js:46`）
MAX_CRED_LEN = 200_000

#: provider 家族 → 该家族的 builtin provider id（逐字对照 `import-account.js:52-55`；
#: 导入与面板换号共用这一份，两边各写一套曾导致导入建出客户端不认的 provider）
PROVIDER_FAMILY: dict[str, tuple[str, ...]] = {
    "bigmodel": ("builtin:bigmodel", "builtin:bigmodel-coding-plan",
                 "builtin:bigmodel-start-plan"),
    "zai": ("builtin:zai", "builtin:zai-coding-plan", "builtin:zai-start-plan"),
}

#: 无家族信息的老格式默认家族（`import-account.js:58`）
DEFAULT_FAMILY = "bigmodel"

#: 一份模板都抄不到时的兜底 provider（形状照抄官方客户端写在盘上的那几项；
#: `import-account.js:62-77` —— kind 必须是 anthropic，baseURL 是接口路径而不是站点根）
FALLBACK_PROVIDER: dict[str, dict] = {
    "zai": {
        "id": "builtin:zai-start-plan",
        "entry": {
            "name": "Z.ai - Coding Plan", "kind": "anthropic", "enabled": True,
            "source": "import",
            "options": {"apiKey": "", "apiKeyRequired": True,
                        "baseURL": "https://zcode.z.ai/api/v1/zcode-plan/anthropic"},
        },
    },
    "bigmodel": {
        "id": "builtin:bigmodel-start-plan",
        "entry": {
            "name": "BigModel- Coding Plan", "kind": "anthropic", "enabled": True,
            "source": "import",
            "options": {"apiKey": "", "baseURL":
                        "https://zcode.z.ai/api/v1/zcode-plan/anthropic"},
        },
    },
}

# ---------- 形态常量（`detect_payload_form` 的返回值）----------

#: 网关内部载荷形态（含字面键 `credentials.json`/`config.json`）
FORM_GATEWAY = "gateway"
#: zcode-switch 账号 JSON（`virtual_device_mid` + `credentials` + `config`）
FORM_SWITCH = "switch"
#: 面板/小店粘贴形态（jwt / family+credentials）
FORM_PASTE = "paste"
#: 旧网关形态（仅 `name` + `device_mid` 之类，无凭据材料）——按现状直通 store
FORM_META = "meta"
#: 无法识别（由调用方决定拒绝还是回落既有路径）
FORM_UNKNOWN = "unknown"

#: 面板账号库扫描时跳过的保留目录（非账号；Q31 任务清单给定）
_PANEL_RESERVED = frozenset({"last", "profile", "backup", "tmp"})


class ImportValidationError(ValueError):
    """形态校验失败（带面板同款短码，便于调用方分类呈现）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class DetectedAccount:
    """扫描到的**源侧账号**（尚未导入网关；`already_imported` 由 API 层现算）。"""

    name: str
    device_mid: str = ""
    family: str = ""
    path: str = ""


@dataclass
class NormalizedPaste:
    """面板 `normalize()`（`import-account.js:138-173`）的等价产物。"""

    name: str
    jwt: str
    device_mid: str
    family: str
    family_source: str          # field / credentials / default（`import-account.js:80-104`）
    oauth: dict[str, str] = field(default_factory=dict)  # access_token/… → 原值


# ---------- 小工具 ----------

def _read_json(path: Path) -> object:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _pick(o: dict, *keys: str) -> str:
    """取第一个非空字符串值（面板 `pick`，`import-account.js:151-157`）。"""
    for k in keys:
        v = o.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _unwrap(o: dict) -> dict:
    """允许外包一层 `account`/`data`/`payload`（面板判据：**内层须带凭据线索**，
    `import-account.js:147-149`）——与 `store._load_payload` 的无条件解包刻意不同，
    这里严格照抄面板，避免把恰好叫 `payload` 的业务对象整个换掉。"""
    for k in ("account", "data", "payload"):
        inner = o.get(k)
        if isinstance(inner, dict) and any(
                isinstance(inner.get(x), str) and inner.get(x).strip()
                for x in ("jwt", "jwtToken", "device_mid", "deviceMid")):
            return inner
    return o


def infer_family_from_keys(creds) -> str:
    """从凭据键推断家族（单一家族才认；`import-account.js:88-98` 同判据）。"""
    if not isinstance(creds, dict):
        return ""
    seen = {m.group(1) for k in creds if (m := OAUTH_KEY_RE.match(str(k)))}
    if len(seen) == 1:
        only = next(iter(seen))
        return only if only in PROVIDER_FAMILY else ""
    return ""


# ---------- 形态识别 ----------

def detect_payload_form(obj) -> str:
    """识别一份 JSON 对象（或 JSON 文本）属于哪种导入形态。

    判据顺序（先强形态后弱形态）：
    1. 含字面键 `credentials.json`/`config.json` → `gateway`（网关内部载荷）；
    2. `virtual_device_mid`，或 `credentials`+`config`+（`id`/`hash`）→ `switch`
       （zcode-switch 账号文件实测形态）；
    3. 有 jwt 系列键（`jwt|jwtToken|zcodejwttoken|token|apiKey`）或 `family`+`credentials`
       → `paste`（面板/小店粘贴形态，`import-account.js:8-18`）；
    4. 仅 `name`/`device_mid` 系列 → `meta`（旧网关形态，按现状直通）；
    5. 其余 → `unknown`（**不假装认识**）。
    """
    if isinstance(obj, str):
        try:
            obj = json.loads(obj.strip().lstrip("\ufeff"))
        except ValueError:
            return FORM_UNKNOWN
    if not isinstance(obj, dict):
        return FORM_UNKNOWN
    o = _unwrap(obj)
    if isinstance(o.get("credentials.json"), (dict, str)) or \
            isinstance(o.get("config.json"), (dict, str)):
        return FORM_GATEWAY
    creds = o.get("credentials")
    if "virtual_device_mid" in o or (
            isinstance(creds, dict) and isinstance(o.get("config"), dict)
            and ("id" in o or "hash" in o)):
        return FORM_SWITCH
    if _pick(o, "jwt", "jwtToken", "zcodejwttoken", "token", "apiKey") or (
            isinstance(creds, dict) and "family" in o):
        return FORM_PASTE
    if _pick(o, "name", "id", "accountName") or \
            _pick(o, "device_mid", "deviceMid", "mid", "deviceId"):
        return FORM_META
    return FORM_UNKNOWN


# ---------- 粘贴形态 → 网关载荷（面板 importAccount 的等价实现）----------

def resolve_family(o: dict) -> tuple[str, str]:
    """家族解析（`import-account.js:80-104`）：显式 `family` > credentials 键推断 >
    老格式默认 `bigmodel`。返回 `(family, source)`。"""
    raw = o.get("family")
    given = raw.strip().lower() if isinstance(raw, str) else ""
    if given:
        if given not in PROVIDER_FAMILY:
            raise ImportValidationError(
                "bad-family",
                "family 不是已知家族（只支持 bigmodel / zai）：" + repr(raw))
        return given, "field"
    creds = o.get("credentials")
    if isinstance(creds, dict):
        seen = {m.group(1) for k in creds if (m := OAUTH_KEY_RE.match(str(k)))}
        if len(seen) == 1:
            only = next(iter(seen))
            if only not in PROVIDER_FAMILY:
                raise ImportValidationError("bad-family",
                                            f"credentials 里的家族不是已知家族：{only}")
            return only, "credentials"
        if len(seen) > 1:
            raise ImportValidationError(
                "bad-family",
                f"credentials 里混了多个家族（{' / '.join(sorted(seen))}），必须显式给 family")
    return DEFAULT_FAMILY, "default"


def pick_oauth(creds, family: str) -> dict[str, str]:
    """只取本家族那三个键、逐值校验形态（`import-account.js:113-135`，消息同文案口径）。"""
    out: dict[str, str] = {}
    if not isinstance(creds, dict):
        return out
    for k, v in creds.items():
        m = OAUTH_KEY_RE.match(str(k))
        if not m or m.group(1) != family:
            continue
        if not isinstance(v, str):
            raise ImportValidationError("bad-cred", f"{k} 不是字符串")
        s = v.strip()
        if not s:
            raise ImportValidationError("bad-cred", f"{k} 是空的")
        if len(s) > MAX_CRED_LEN:
            raise ImportValidationError("bad-cred",
                                        f"{k} 过长（> {MAX_CRED_LEN}），不像凭据")
        if SIGNING_KEY_RE.match(s):
            raise ImportValidationError(
                "bad-cred", f"{k} 是 <32位hex>.<secret> 形态的签名密钥，按账号派生，不能用别人的")
        if s.startswith("{"):
            try:
                parsed = json.loads(s)
                if not isinstance(parsed, dict):
                    raise ValueError("不是对象")
            except ValueError as e:
                raise ImportValidationError("bad-cred", f"{k} 不是合法 JSON 对象：{e}") from None
        elif not CRED_RE.match(s):
            raise ImportValidationError(
                "bad-cred",
                f"{k} 形态不认识（应是 eyJ / sk- / enc:v1: 开头，或 JSON 对象串）")
        out[m.group(2)] = s
    return out


def normalize_paste_payload(obj) -> NormalizedPaste:
    """粘贴形态归一化（`import-account.js:138-173` 的等价实现；不含加密，纯校验+抽取）。

    接受：JSON 文本或对象；外包一层 `account`/`data`/`payload`；别名键
    `deviceMid|mid|token|jwtToken` 等。拒绝：非法名 / 非三段 jwt / 非 UUID 设备码 /
    未知家族 / 凭据键形态不过（签名密钥、超长、非 JSON 对象串）。
    """
    o = obj
    if isinstance(o, str):
        t = o.strip().lstrip("\ufeff")
        if not t:
            raise ImportValidationError("empty", "内容是空的")
        try:
            o = json.loads(t)
        except ValueError as e:
            raise ImportValidationError("not-json", f"不是合法 JSON：{e}") from None
    if not isinstance(o, dict):
        raise ImportValidationError("not-object", "需要是一个对象")
    o = _unwrap(o)

    name = _pick(o, "name", "id", "accountName")
    jwt = _pick(o, "jwt", "jwtToken", "zcodejwttoken", "token", "apiKey")
    mid = _pick(o, "device_mid", "deviceMid", "mid", "deviceId")

    if not NAME_RE.match(name):
        raise ImportValidationError(
            "bad-name", f"账号名不合法（只允许字母数字下划线短横，1–32 位）：{name!r}")
    if not JWT_RE.match(jwt):
        raise ImportValidationError("bad-jwt", "jwt 不合法（应是 eyJ 开头的三段点分串）")
    if not UUID_RE.match(mid):
        raise ImportValidationError("bad-mid", f"device_mid 不合法（应是 UUID）：{mid!r}")

    family, family_source = resolve_family(o)
    oauth = pick_oauth(o.get("credentials"), family)
    return NormalizedPaste(name=name, jwt=jwt, device_mid=mid, family=family,
                           family_source=family_source, oauth=oauth)


def _seal(value: str, secret: str | None) -> str:
    """凭据值加密为 `enc:v1:`；**已是 `enc:v1:` 的原样透传**（模块头「刻意收窄」）。"""
    if value.startswith(crypto.PREFIX):
        return value
    return crypto.encrypt(value, secret=secret)


def build_credentials(n: NormalizedPaste, *, secret: str | None = None) -> dict:
    """面板 `importAccount` 的 credentials 组法（`import-account.js:286-292`）。

    `oauth:active_provider` 必须跟着 family 走 —— 客户端按它决定去读哪一套
    `oauth:<family>:*` 键，写错家族等于把 access_token / user_info 藏进客户端
    永远不会看的抽屉（`import-account.js:284-285`）。
    """
    cred = {"zcodejwttoken": _seal(n.jwt, secret),
            "oauth:active_provider": _seal(n.family, secret)}
    for k in ("access_token", "refresh_token", "user_info"):
        if n.oauth.get(k):
            cred[f"oauth:{n.family}:{k}"] = _seal(n.oauth[k], secret)
    return cred


def _scrub(value, jwt: str) -> None:
    """就地清洗模板里的凭据残留（`import-account.js:190-196`，含 `32hex.secret` 签名密钥——
    实测面板模板里的 builtin:zai-coding-plan 就带着别人的 49 字符签名密钥）。"""
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, str) and v != jwt and (CRED_RE.match(v) or SIGNING_KEY_RE.match(v)):
                value[k] = ""
            elif isinstance(v, (dict, list)):
                _scrub(v, jwt)
    elif isinstance(value, list):
        for item in value:
            _scrub(item, jwt)


def build_config(template, jwt: str, family: str) -> dict:
    """面板 `buildConfig` 的等价实现（`import-account.js:182-214`）。

    · 只保留**本家族**的 builtin provider（第三方 provider 和别的家族都夹带别人的凭据）；
    · 清空一切凭据形态的残留值（`nodeKey === true` 处填本次 jwt）；
    · start-plan 那条按真机形状补全：`kind=anthropic`、`apiKey=jwt`、
      `baseURL` 走 zcode-plan 接口。
    """
    fam = family if family in PROVIDER_FAMILY else DEFAULT_FAMILY
    allowed = set(PROVIDER_FAMILY[fam])
    out = json.loads(json.dumps(template)) if isinstance(template, dict) else {}
    provider = out.get("provider")
    if not isinstance(provider, dict):
        provider = {}
    out["provider"] = provider
    for k in list(provider):
        v = provider[k]
        if k not in allowed:
            del provider[k]
            continue
        if isinstance(v, dict) and v.get("nodeKey") is True:
            v["nodeKey"] = jwt
        _scrub(v, jwt)

    fb = FALLBACK_PROVIDER[fam]
    entry = provider.get(fb["id"])
    entry = json.loads(json.dumps(entry)) if isinstance(entry, dict) else \
        json.loads(json.dumps(fb["entry"]))
    options = entry.get("options") if isinstance(entry.get("options"), dict) else {}
    tpl_base = options.get("baseURL") if isinstance(options.get("baseURL"), str) else ""
    if not entry.get("name"):
        entry["name"] = fb["entry"]["name"]
    entry["kind"] = "anthropic"
    entry["enabled"] = True
    merged = dict(options)
    merged.update({
        "apiKey": jwt,
        "apiKeyRequired": True,
        "baseURL": tpl_base if "zcode-plan" in tpl_base
                   else fb["entry"]["options"]["baseURL"],
    })
    entry["options"] = merged
    provider[fb["id"]] = entry
    return out


def verify_payload(payload: dict, *, family: str, jwt: str = "",
                   oauth_keys=()) -> list[str]:
    """写前自检（面板 `verifyWritten` 的内存等价物，`import-account.js:221-253`）。

    返回问题清单（空数组 = 通过）。跨机不可复制的值比较收窄为：
    `jwt` 给了就逐字比对本条 jwt（转换路径），透传路径（不给 jwt）只查
    「apiKey 非空字符串」。**错误文案不带任何凭据值**。
    """
    bad: list[str] = []
    cred = payload.get("credentials.json")
    if not isinstance(cred, dict):
        bad.append("credentials.json 缺失或不是对象")
        cred = {}
    need = ["zcodejwttoken", "oauth:active_provider"] + \
           [f"oauth:{family}:{k}" for k in oauth_keys]
    for k in need:
        v = cred.get(k)
        if not (isinstance(v, str) and v.strip()):
            bad.append(f"credentials 缺 {k}")

    cfg = payload.get("config.json")
    if not isinstance(cfg, dict):
        bad.append("config.json 缺失或不是对象")
        cfg = {}
    providers = cfg.get("provider") if isinstance(cfg.get("provider"), dict) else {}
    fb = FALLBACK_PROVIDER.get(family, FALLBACK_PROVIDER[DEFAULT_FAMILY])
    e = providers.get(fb["id"])
    if not isinstance(e, dict):
        bad.append(f"config 里没有 {fb['id']}")
    else:
        if e.get("kind") != "anthropic":
            bad.append(f"{fb['id']}.kind 不是 anthropic（实际 {e.get('kind')}）")
        opts = e.get("options") if isinstance(e.get("options"), dict) else {}
        api_key = opts.get("apiKey")
        if jwt:
            if api_key != jwt:
                bad.append(f"{fb['id']}.options.apiKey 不是本次导入的 jwt")
        elif not (isinstance(api_key, str) and api_key.strip()):
            bad.append(f"{fb['id']}.options.apiKey 为空")
        base = opts.get("baseURL")
        if not (isinstance(base, str) and "zcode-plan" in base):
            bad.append(f"{fb['id']}.options.baseURL 不是 zcode-plan 接口（实际 {base}）")
    foreign = [k for k in providers if k not in set(PROVIDER_FAMILY.get(family, ()))]
    if foreign:
        bad.append("config 里残留别的 provider：" + " / ".join(foreign))
    return bad


def paste_to_payload(obj, *, template=None, secret: str | None = None) -> dict:
    """粘贴形态 → 网关载荷（含自检；不过则抛 `ImportValidationError`）。

    `template` = 一份现成账号的 config.json（调用方经 `find_config_template` 取，
    面板 `main.js:2325-2335` 同路线：让写出来的 config 与现成账号同形）。
    """
    n = normalize_paste_payload(obj)
    payload = {
        "name": n.name,
        "device_mid": n.device_mid,
        "credentials.json": build_credentials(n, secret=secret),
        "config.json": build_config(template, n.jwt, n.family),
        "family": n.family,
        "meta": {"family": n.family, "family_source": n.family_source},
    }
    problems = verify_payload(payload, family=n.family, jwt=n.jwt,
                              oauth_keys=list(n.oauth))
    if problems:
        raise ImportValidationError("verify", "导入自检未通过：" + "；".join(problems))
    return payload


# ---------- 面板账号库（整目录透传）----------

def _panel_files_of(d: Path) -> tuple[Path, Path] | None:
    """面板账号目录的两份凭据文件；不满足 valid 判据返回 None。

    valid = v2 `credentials.json` 在 **且**（v2 `config.json` 或顶层 `config.json`）在
    （`import-account.js:275` 的 hasCred && hasCfg）。
    """
    v2 = Path(d) / "data" / ".zcode" / "v2"
    cred = v2 / "credentials.json"
    if not cred.is_file():
        return None
    for cfg in (v2 / "config.json", Path(d) / "config.json"):
        if cfg.is_file():
            return cred, cfg
    return None


def from_panel_account(account_dir) -> dict:
    """面板账号目录 → 网关载荷（`credentials.json`/`config.json` **原样透传**）。

    校验（键 + 形状，不取值、不解密，Q31 任务口径）：
    · 目录名过白名单（面板 `NAME_RE`）；
    · `meta.json` 必须有非空 `device_mid` —— **缺了就拒**：网关会为此生成新设备码，
      而上游眼里"换设备"正是 §15.1 硬约束 2 要避免的风控触发面（宁可不导入）；
    · credentials 必须有 `zcodejwttoken` + `oauth:active_provider` 两个锚键
      （面板 verifyWritten 同判据，`import-account.js:230-234`）；
    · config 必须有 `provider` 段。
    `family` 取 `meta.json`（缺则从凭据键推断；仍无则空 —— **不编造**）。
    """
    d = Path(account_dir)
    name = d.name
    if not NAME_RE.match(name):
        raise ImportValidationError("bad-name", f"面板账号目录名不合法：{name!r}")
    meta = _read_json(d / "meta.json")
    meta = meta if isinstance(meta, dict) else {}
    mid = meta.get("device_mid")
    if not (isinstance(mid, str) and mid.strip()):
        raise ImportValidationError(
            "bad-mid",
            f"面板账号『{name}』缺 device_mid（meta.json）——不导入（新生成设备码会被上游视为换设备）")
    files = _panel_files_of(d)
    if files is None:
        raise ImportValidationError(
            "bad-cred", f"面板账号『{name}』缺 data/.zcode/v2/credentials.json 或 config.json")
    cred = _read_json(files[0])
    if not isinstance(cred, dict) or not cred:
        raise ImportValidationError("bad-cred",
                                    f"面板账号『{name}』的 credentials.json 不可读或为空")
    cfg = _read_json(files[1])
    if not isinstance(cfg, dict) or not cfg:
        raise ImportValidationError("bad-cfg", f"面板账号『{name}』的 config.json 不可读或为空")
    for k in ("zcodejwttoken", "oauth:active_provider"):
        v = cred.get(k)
        if not (isinstance(v, str) and v.strip()):
            raise ImportValidationError(
                "bad-cred", f"面板账号『{name}』的 credentials.json 缺 {k}")
    if not isinstance(cfg.get("provider"), dict):
        raise ImportValidationError("bad-cfg",
                                    f"面板账号『{name}』的 config.json 缺 provider 段")
    family = str(meta.get("family") or "").strip().lower()
    if family not in PROVIDER_FAMILY:
        family = infer_family_from_keys(cred)
    out: dict = {"name": name, "device_mid": mid.strip(),
                 "credentials.json": cred, "config.json": cfg}
    if family:
        out["family"] = family
        out["meta"] = {"family": family}
    return out


def _panel_app_dir() -> Path:
    """面板 `appDataDir` 的三条平台分支（`settings.js:38-48`，与 Electron 口径一致）。"""
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def default_panel_root() -> Path:
    """面板账号库的默认解析（`settings.js:395-430` 的 `accountsDir()` 口径）：
    `$ZPANEL_ACCOUNTS_DIR` > settings.json 的自定义 `accountsDir` > 打包态
    `~/Library/Application Support/zcode-panel/accounts`。

    ⚠️ 面板**开发态**（仓库下 `accounts/`，`settings.js:400-405`）无稳定探测面：
    开发用户按面板自身机制经 settings.json 的 `accountsDir` 或 `ZPANEL_ACCOUNTS_DIR`
    指过来即被本函数采纳（这也是面板自己认的两个出口）。扫描/导入接口永远回报
    实际使用的 root，不猜。
    """
    env = (os.environ.get("ZPANEL_ACCOUNTS_DIR") or "").strip()
    if env:
        return Path(env).expanduser()
    app_dir = _panel_app_dir() / "zcode-panel"
    settings = _read_json(app_dir / "settings.json")
    if isinstance(settings, dict):
        custom = settings.get("accountsDir")
        if isinstance(custom, str) and custom.strip():
            return Path(custom.strip()).expanduser()
    return app_dir / "accounts"


def scan_panel_dir(root=None) -> list[DetectedAccount]:
    """扫描面板账号库（默认根见 `default_panel_root`）。

    跳过：非目录、点开头目录、保留目录（`last/profile/backup/tmp`）、不满足
    valid 判据的目录。**目录名不做白名单过滤**：不合法的名字照样列出，
    导入时由 `from_panel_account` 给出可读拒绝（不静默隐藏用户数据）。
    """
    base = Path(root).expanduser() if root else default_panel_root()
    if not base.is_dir():
        return []
    out: list[DetectedAccount] = []
    for child in sorted(base.iterdir(), key=lambda p: p.name):
        try:
            is_dir = child.is_dir()
        except OSError:
            continue
        if not is_dir or child.name.startswith(".") or child.name in _PANEL_RESERVED:
            continue
        if _panel_files_of(child) is None:
            continue
        meta = _read_json(child / "meta.json")
        meta = meta if isinstance(meta, dict) else {}
        out.append(DetectedAccount(
            name=child.name,
            device_mid=str(meta.get("device_mid") or "").strip(),
            family=str(meta.get("family") or "").strip().lower(),
            path=str(child)))
    return out


# ---------- zcode-switch 账号库 ----------

def default_switch_root() -> Path:
    """zcode-switch 账号库默认根（实测形态：`~/.zcode-switch/accounts/<uuid>.json`）。"""
    return Path.home() / ".zcode-switch" / "accounts"


def _switch_name(data: dict, stem: str) -> str:
    """switch 账号名 → 网关白名单名（实测数据里 `name` 常是邮箱，含 `@`/`.` 过不了白名单）。

    顺序：`name` 字段（合法则原样）→ 网关既有**清洗语义**（`accounts.store.sanitize_name`：
    去掉非法字符 + 截 32，如 `1971962463@qq.com` → `1971962463qqcom`，保留可辨识前缀）→
    文件名（uuid）截 32。**不静默丢信息**：被改名的原始值由 `_switch_to_payload` 写进
    `meta.display_name`（与 `mgw zcode login` 的展示镜像同一键）。
    """
    raw = str(data.get("name") or "").strip()
    if raw and NAME_RE.match(raw):
        return raw
    if raw:
        cleaned = sanitize_name(raw).strip()
        if cleaned != "account" and NAME_RE.match(cleaned):
            return cleaned
    return str(stem or "")[:32]


def _switch_to_payload(data: dict, *, stem: str = "") -> dict:
    """switch 账号对象 → 网关载荷（`credentials`/`config` 两个 map 原样透传）。"""
    mid = data.get("virtual_device_mid")
    if not (isinstance(mid, str) and mid.strip()):
        raise ImportValidationError(
            "bad-mid", "不是 zcode-switch 账号（缺 virtual_device_mid）——不导入")
    cred = data.get("credentials")
    if not isinstance(cred, dict) or not cred:
        raise ImportValidationError("bad-cred", "zcode-switch 账号缺 credentials（或为空）")
    cfg = data.get("config")
    if not isinstance(cfg, dict) or not cfg:
        raise ImportValidationError("bad-cfg", "zcode-switch 账号缺 config（或为空）")
    name = _switch_name(data, stem)
    if not name:
        raise ImportValidationError(
            "bad-name",
            "zcode-switch 账号缺 name（对象导入没有文件名可兜底：请带 name 字段，或改用文件导入）")
    out: dict = {"name": name, "device_mid": mid.strip(),
                 "credentials.json": cred, "config.json": cfg}
    meta: dict = {}
    family = infer_family_from_keys(cred)
    if family:
        out["family"] = family
        meta["family"] = family
    raw_name = str(data.get("name") or "").strip()
    if raw_name and raw_name != name:
        meta["display_name"] = raw_name        # 改名时的可追溯镜像（同 login 的展示键）
    if meta:
        out["meta"] = meta
    return out


def from_switch_json(path) -> dict:
    """读一份 zcode-switch 账号 JSON → 网关载荷（§15.1 的设备码 = `virtual_device_mid`）。

    校验：文件是 JSON 对象、`virtual_device_mid` 非空、`credentials`/`config` 为
    非空对象、账号名可落白名单（见 `_switch_name`，含清洗与 uuid 兜底）。
    凭据值**原样透传**（同机 `enc:v1:` 可解，不重加密）。
    """
    p = Path(path)
    data = _read_json(p)
    if not isinstance(data, dict):
        raise ImportValidationError("not-object", f"不是合法 JSON 对象：{p.name}")
    return _switch_to_payload(data, stem=p.stem[:32])


def scan_switch_dir(root=None) -> list[DetectedAccount]:
    """扫描 switch 账号库（默认根见 `default_switch_root`）。

    枚举 `*.json`；跳过写盘中间态（文件名含 `.tmp`，实测残留 `*.tmp-<hex>`）与
    读不出/非对象/缺 `virtual_device_mid` 的文件（它们本就导不进来）。
    """
    base = Path(root).expanduser() if root else default_switch_root()
    if not base.is_dir():
        return []
    out: list[DetectedAccount] = []
    for f in sorted(base.glob("*.json"), key=lambda p: p.name):
        if ".tmp" in f.name:
            continue
        data = _read_json(f)
        if not isinstance(data, dict):
            continue
        mid = data.get("virtual_device_mid")
        if not (isinstance(mid, str) and mid.strip()):
            continue
        out.append(DetectedAccount(
            name=_switch_name(data, f.stem[:32]),
            device_mid=mid.strip(),
            family=infer_family_from_keys(data.get("credentials")),
            path=str(f)))
    return out


# ---------- 载荷模板（面板 main.js:2325-2335 同路线）----------

def find_config_template(accounts_root) -> dict | None:
    """从**现存账号**里挑一份 config 当模板（有裸 `starter` 也不用 —— 面板判据是
    「第一份含 `builtin:` provider 的 config」，让新导入的 config 与现成账号同形）。

    兼容两种目录布局：网关账号（`<名>/data/.zcode/v2/config.json`）与面板账号
    （同上或顶层 `<名>/config.json`）。取不到 → `None`（转换侧走最小兜底 config）。
    """
    base = Path(accounts_root)
    if not base.is_dir():
        return None
    for child in sorted(base.iterdir(), key=lambda p: p.name):
        try:
            if not child.is_dir() or child.name.startswith("."):
                continue
        except OSError:
            continue
        for cfg_path in (child / "data" / ".zcode" / "v2" / "config.json",
                         child / "config.json"):
            cfg = _read_json(cfg_path)
            if isinstance(cfg, dict):
                prov = cfg.get("provider")
                if isinstance(prov, dict) and any(str(k).startswith("builtin:") for k in prov):
                    return cfg
    return None


# ---------- 统一入口（CLI / API 共用；对象级，不含文件读）----------

def payload_for_form(obj, form: str, *, template=None, secret: str | None = None) -> dict:
    """按已识别形态把对象转成网关载荷（`FORM_GATEWAY`/`FORM_META` 原样直通）。

    `FORM_UNKNOWN` → 抛错（**不猜**；调用方若要回落既有直通路径，应先自行判定）。
    """
    if form == FORM_PASTE:
        return paste_to_payload(obj, template=template, secret=secret)
    if form in (FORM_SWITCH, FORM_GATEWAY, FORM_META):
        data = obj
        if isinstance(data, str):
            t = data.strip().lstrip("\ufeff")
            try:
                data = json.loads(t)
            except ValueError as e:
                raise ImportValidationError("not-json", f"不是合法 JSON：{e}") from None
        if not isinstance(data, dict):
            raise ImportValidationError("not-object", "需要是一个对象")
        if form == FORM_SWITCH:
            return _switch_to_payload(_unwrap(data))
        return data
    raise ImportValidationError(
        "unknown-form",
        "无法识别的导入形态（支持：面板/小店粘贴 JSON、zcode-switch 账号 JSON、"
        "网关载荷 JSON）")
