"""10 个产品实例的注册表（tech-design v2.0 §22.4 逐产品矩阵）。

🔴 填表纪律（§22.4 + M6-1 任务书）：**表里有证据的照填，取不到的留空并标「未核实」，
   不许编造**。每条实例的注释给出该行的证据出处（§22.4 行 / `20`–`23` 的 `file:line`）。

**逐产品证据速查**：

| 产品 | 证据行 | 说明 |
|---|---|---|
| buddy / workbuddy | `20 §1.1/§3.1` | 同族（`BuddyProduct` 共用）；workbuddy 国际版**无签到端点** |
| lobsterai | `20 §2.7/§3.1` | 设备 `uuid`（身份）；keyfrom 属账号元数据（不进 spec）；签到三步 `check_in` |
| qoder / qodercn | `20 §2.7/§3.1`、`21 §1.1` | 目录**恒用本地兜底表**（WASM 签名端点不实现）；CR 分支防串用 |
| trae | `20 §3.5`、`21 §1.1` | 设备 `machine_id` + `device_id`（uid 派生，9074 轮换已废弃） |
| cline | `20 §1.2/§3.1` | WorkOS 设备码；**不渲染签到按钮**（sidecar 全量扫描无签到） |
| loomy | `20 §3.1/§3.3` | 扫码/短信；两池额度；新手任务 + 永久锁 |
| raccoon | `20 §3.1/§4.1` | 扫码/短信；每日积分**服务端自动发放**（无签到端点） |
| zcode | 既有实现 + `20 §4.1` | OAuth 设备流；anthropic 协议；不可续期 |

**契约台账（缺口与裁决状态）**：

① `protocol`：**已裁决**（2026-09-29，总 agent）——字面量补入 `custom`（§22.3 补入①），
   `qoder`/`qodercn`/`trae` 三实例落 **`custom`**；物化资源时 `Resource.protocol` 落
   `"openai"` 仅为 `config/schemas.py::Protocol` 字面量兼容，**分派以 `product` 优先**（§22.5-3）。
② `base_url`：§22.4 **没有** base_url 列，`20`/`21` 只给路径不给宿主 →
   除 zcode（仓内既有默认值）外**留空**，由 M6-2/M6-3 逐产品取证回填。
③ `login_alt`：**已裁决**（2026-09-29）——`loomy`/`raccoon` 的扫码 / 短信双路径以
   `login_alt` 登记（主形态仍为 `qr`）。

**能力位口径**（`20 §3.1` 逐行）：`balance` 11/11 ✓；`checkin` 8/11 ✓
（**workbuddy / cline / raccoon 为 ✗**）；`onboarding` 仅 loomy / raccoon ✓；
`permanent_lock` 仅 buddy / workbuddy / loomy ✓；`refresh` 见 `20 §2.6`
（**loomy / zcode 不可续期**）。
"""

from __future__ import annotations

from model_gateway.accounts.types import Capabilities, DeviceSpec, ProductMeta

#: 在册产品（§22.0：10 实例 / 9 产品；**排除华为云 CodeArts**——用户指令明确不接）。
#: 顺序 = UI 左子侧栏的展示顺序（照抄 §22.4 表序）。
PRODUCT_IDS: tuple[str, ...] = (
    "buddy", "workbuddy", "lobsterai", "qoder", "qodercn",
    "trae", "cline", "loomy", "raccoon", "zcode",
)

#: 无设备身份产品的共享空规格（`20 §2.7`：buddy/workbuddy/cline/loomy 均无设备标识）。
_NO_DEVICE = DeviceSpec(fields=(), derive=False)

#: 领取前**必须预检**的产品（§22.6「`precheck` per-product 显式声明」/ `20 B6`）。
#: `trae` 必须在内：其 `claim` 对「今天已签到」同样回 `{code:0, message:"success"}`
#:（真领与重放**不可区分**，`jet-hub-rpc.ts:1801-1806`）→ 幂等**只能**靠 status 端点判
#:（`20 §3.1`）。不在表内 = 不预检（各产品钩子自带幂等判据）。
#: 🔴 **单一事实源**（Fix-ζ 收敛）：ops 批量路径（`ops/builtin/product_claim.py`）与
#: 管理端点（`api/admin_accounts.py`）都**引用本对象**，不再各自持有副本 ——
#: 产品事实（能力位/设备规格）与它同家，改这一处即全站生效。
PRE_CHECK_PRODUCTS: dict[str, bool] = {"trae": True}

PRODUCTS: dict[str, ProductMeta] = {
    # —— buddy：CodeBuddy（`20 §1.1` 第 2 行）——
    # 登录 external_link 轮询；额度 ✓；签到 ✓（幂等 = HTTP 400 + 业务码 10001）；
    # 永久锁 ✓；模型 remote `/v3/config` + 兜底表；无设备标识。
    "buddy": ProductMeta(
        id="buddy", title="CodeBuddy",
        login="external_link",
        protocol="openai",
        # M6-2 回填（A1）：DSH `src/product.ts:271` 的 `endpoint`（同 `apiDomain`，
        # `buddy.ts:20,98`）——**所有** `/v2/plugin/*`、`/v3/config` 与
        # `POST /v2/chat/completions`（`buddy-adapter.ts:1583`）都以此为基址。
        base_url="https://copilot.tencent.com",
        device=_NO_DEVICE,
        capabilities=Capabilities(balance=True, checkin=True,
                                  onboarding=False, permanent_lock=True, refresh=True),
        models_source="remote",
    ),
    # —— workbuddy：WorkBuddy 国际版（`20 §1.1` 第 3 行，与 buddy 同族共用类型）——
    # 签到 ✗（国际版后端**无签到接口**，`20 §3.1`）；永久锁 ✓；无设备标识。
    "workbuddy": ProductMeta(
        id="workbuddy", title="WorkBuddy（国际版）",   # 2026-09-30 用户反馈：与参考程序 `jet-hub.js` 的标签同口径，避免与「国内 WorkBuddy（workbuddy.cn）」混淆
        login="external_link",
        protocol="openai",
        # M6-2 回填（A1）：DSH `src/product.ts:384` 的 `endpoint`（同 `apiDomain`，`:385`）
        # ——国际版域名，模型池随区域变化（`product.ts:14-18`）。
        base_url="https://www.workbuddy.ai",
        device=_NO_DEVICE,
        capabilities=Capabilities(balance=True, checkin=False,
                                  onboarding=False, permanent_lock=True, refresh=True),
        models_source="remote",
    ),
    # —— lobsterai（`20 §1.1` 第 4 行）——
    # local_callback 两步（本机回跳 + 粘贴回调）；签到三步 `check_in`（客户端幂等预检）；
    # 模型 remote `/api/models/available`。
    # base_url：`lobsterai-product.ts:63` 的 `LOBSTERAI_API_BASE`（= `lobsterai2api/sigin.py:10`
    #   硬编码值，Go 侧脱敏为 env `LB2A_UPSTREAM_BASE`，DSH 插件固化同值）。
    #   登录门户另有基址 `https://lobsterai.youdao.com`（`lobsterai-product.ts:77`）——
    #   它不是资源出站基址，由产品层 `const.PORTAL_BASE` 持有，**不进本表**。
    # 设备：**身份字段只有 `uuid`**（安装标识，`lobsterai.ts:102-109`：客户端 `randomUUID()`
    #   生成、每次续期原样回传）。`first_keyfrom`/`latest_keyfrom`（keyfrom 身份载荷的时间戳，
    #   exchange/refresh 请求体必带）= **非身份元数据**：不进 spec（§22.3 DeviceSpec 定义：
    #   「非身份元数据不进 spec」＋ §22.4 表「keyfrom 属账号元数据，非身份字段」），
    #   由产品层按账号元数据写 `meta.json`（`protocol.credential_meta`）。
    #   🔴 2026-09-29 总 agent 裁决（W2-fix）：三字段并存时「同 uuid 不同 keyfrom」不会被
    #   唯一性拦下（keyfrom 是时间戳，两个账号天然不同 → 元组比较形同虚设）；收敛为 uuid
    #   单身份 = 与 §15.1「同一安装标识不得被第二个账号复用」逐字一致。M6-2 的
    #   「单字段投影绕行」（`login.py::_new_device_uuid`）随本轮删除。
    "lobsterai": ProductMeta(
        id="lobsterai", title="LobsterAI",
        login="local_callback",
        protocol="openai",
        base_url="https://lobsterai-server.youdao.com",
        device=DeviceSpec(fields=("uuid",), derive=False),
        capabilities=Capabilities(balance=True, checkin=True,
                                  onboarding=False, permanent_lock=False, refresh=True),
        models_source="remote",
    ),
    # —— qoder（`20 §1.1` 第 5 行、`21 §1.1`）——
    # device_code 轮询；设备 `machine_id`；签到 = campaigns → claim（幂等 `replayed:true`）；
    # 目录**恒本地兜底表**（远端目录端点需 WASM 签名，明确不实现）。
    "qoder": ProductMeta(
        id="qoder", title="Qoder",
        login="device_code",
        protocol="custom",               # 信封协议（§22.4）；分派以 product 优先（§22.5-3）
        # 出站基址 = 加密推理端点（**认目录 key**；公开端点 `api2-v2.qoder.sh` 只认通用名，
        # 发目录 key 回 `Unsupported model`）—— 取证：DSH `qoder-product.ts:445`
        # `encryptedInferBase: 'https://api2.qoder.sh'`；M6-5 出站塑形以 product 分派。
        base_url="https://api2.qoder.sh",
        device=DeviceSpec(fields=("machine_id",), derive=False),
        capabilities=Capabilities(balance=True, checkin=True,
                                  onboarding=False, permanent_lock=False, refresh=True),
        models_source="static",
    ),
    # —— qodercn（`20 §1.1` 第 6 行；`requireQoderFamily` 防与 qoder 串用）——
    "qodercn": ProductMeta(
        id="qodercn", title="Qoder（中国版）",
        login="device_code",
        protocol="custom",               # 同 qoder（分派以 product 优先）
        # CN 加密端点换域名（`qoder-product.ts:604` 同值；CN 无可用公开 OpenAI 兼容端点，
        # 实测 `gateway.qoder.com.cn/model/v1/chat/completions` 回 503，`:594-600`）
        base_url="https://gateway.qoder.com.cn",
        device=DeviceSpec(fields=("machine_id",), derive=False),
        capabilities=Capabilities(balance=True, checkin=True,
                                  onboarding=False, permanent_lock=False, refresh=True),
        models_source="static",
    ),
    # —— trae（`20 §1.1` 第 7 行、`20 §3.5`）——
    # local_callback（**固定端口**）；设备 `machine_id` + `device_id`（uid 派生；
    # 9074 设备轮换代次机制**已废弃**，`20 R14/§3.5`）；
    # 签到幂等**只能**靠 status 端点（`precheck` 必须 True，`20 §3.1`）。
    "trae": ProductMeta(
        id="trae", title="Trae",
        login="local_callback",
        protocol="custom",               # SSE 成帧（§22.4）；分派以 product 优先（§22.5-3）
        # M6-3 回填（A）：DSH `trae-product.ts:155` 的 `TRAE_AGENT_HOST`（Agent 服务：
        # 对话 `trae-adapter.ts:1175` + batch 目录 `trae-auth.ts:694` 都挂在它下面）。
        # ⚠️ 另两个基址**不是**资源出站基址，由产品层 `upstream/trae/const.py` 持有：
        # 签到/积分 `https://api.trae.cn`（`:157`）、OAuth `https://api.trae.com.cn`（`:159`）。
        base_url="https://trae-api-cn.mchost.guru",
        # machine_id 随机 + device_id 由 uid 派生（20 §2.7/§3.5）→ derive 标记针对 device_id
        device=DeviceSpec(fields=("machine_id", "device_id"), derive=True),
        capabilities=Capabilities(balance=True, checkin=True,
                                  onboarding=False, permanent_lock=False, refresh=True),
        models_source="remote",
    ),
    # —— cline（`20 §1.1` 第 8 行）——
    # WorkOS 设备码；**无设备标识**；签到 ✗（对整个 sidecar 二进制字符串扫描无签到端点，
    # `20 §3.1`）→ 前端不得渲染签到按钮；模型 remote 两端点合并（免费集合 + 全量）。
    "cline": ProductMeta(
        id="cline", title="Cline",
        login="device_code",
        protocol="openai",
        # 出站基址 = `CLINE.apiBase`（`cline-product.ts:265` 的 `https://api.cline.bot`）
        # + OpenAI 兼容根 `/api/v1`：推理端点 = `{apiBase}/api/v1/chat/completions`
        # （`cline-product.ts:301` 的 `CLINE_CHAT_PATH`），而网关适配器按
        # `{base_url}/chat/completions` 拼接（`adapters/openai_out.py:109`）→ 必须含 `/api/v1`。
        base_url="https://api.cline.bot/api/v1",
        device=_NO_DEVICE,
        capabilities=Capabilities(balance=True, checkin=False,
                                  onboarding=False, permanent_lock=False, refresh=True),
        models_source="remote",
    ),
    # —— loomy（`20 §1.1` 第 9 行、`20 §3.3`）——
    # 扫码 / 短信（`login.sendSms`/`submitSms` 辅助，`20 §2.8`；主形态取**扫码**，
    # 短信通道以 `login_alt` 登记——裁决落地，2026-09-29）；
    # 额度两池（daily/permanent）；签到 + 新手任务 + 永久锁；**不可续期**（`20 §2.6`）。
    "loomy": ProductMeta(
        id="loomy", title="Loomy",
        login="qr",
        login_alt=("sms_code",),         # 扫码 / 短信双路径（`20 §2.8`）
        protocol="openai",
        # M6-3 回填（B）：DSH `loomy.ts:30` 的 `LOOMY_API_BASE` —— 推理 / 目录 / 积分 / 新手任务
        # 全挂它下面（`loomy-adapter.ts:483` 的 `{apiBase}/chat/completions`），网关适配器按
        # `{base_url}/chat/completions` 拼接，故含 `/api/v1`。
        #   ⚠️ 账号（短信登录 / 微信绑定）是**另一套宿主** `account.xfinfr.com`（`loomy.ts:33`），
        #   由产品层 `upstream/loomy/constants.py::ACCOUNT_BASE` 持有、**不进本表** ——
        #   它不是资源出站基址（同 lobsterai 的门户基址口径）。
        base_url="https://loomyad.xunfei.cn/api/v1",
        device=_NO_DEVICE,
        capabilities=Capabilities(balance=True, checkin=True,
                                  onboarding=True, permanent_lock=True, refresh=False),
        models_source="remote",
    ),
    # —— raccoon（`20 §1.1` 第 10 行、`20 §4.1`）——
    # 扫码 / 短信（主形态取扫码，短信通道以 `login_alt` 登记）；设备 `device_id?`（可选，`20 §2.7`）；
    # 签到 ✗（每日 300 分**服务端按日自动发放**，无可调用端点）→ 但**登录奖励** ✓
    # 属 onboarding；模型 remote `model_catalog`。
    "raccoon": ProductMeta(
        id="raccoon", title="Raccoon",
        login="qr",
        login_alt=("sms_code",),         # 扫码 / 短信双路径（`20 §4.1`）
        protocol="openai",
        # M6-3 回填（C）：DSH `raccoon.ts:25` 的 `RACCOON_API_BASE`（来源 = 官方 `app.asar`
        # 的 `.env.electron`）+ 推理根前缀 `LLM_PREFIX = /api/web/llm/v2`（`raccoon.ts:30`）——
        # 推理端点是 `POST {apiBase}/api/web/llm/v2/chat/completions`
        # （`raccoon-adapter.ts:6,427`：**标准 OpenAI 兼容 + 标准 SSE**），而网关适配器按
        # `{base_url}/chat/completions` 拼接（`adapters/openai_out.py:109`）→ 必须含该前缀
        # （同 cline 的 `…/api/v1` 口径）。目录/认证/积分端点各自挂自己的前缀
        # （`/api/web/llm/v2`、`/api/web/auth/v1`、`/api/web/points/v1`、`/api/web/desktop/v1`，
        # `raccoon.ts:28-34`），由产品层常量持有（`upstream/raccoon/const.py`）。
        base_url="https://xiaohuanxiong.com/api/web/llm/v2",
        device=DeviceSpec(fields=("device_id",), derive=False),
        capabilities=Capabilities(balance=True, checkin=False,
                                  onboarding=True, permanent_lock=False, refresh=True),
        models_source="remote",
    ),
    # —— zcode（既有实现，`20 §4.1` + 仓内 `upstream/zcode/`）——
    # OAuth 设备流（`/oauth/cli/init` → 浏览器 → `/oauth/cli/poll/{flow_id}`）；
    # 设备 `device_mid`（本机生成 uuid4 后持久化，`dataroot.generate_unique_device_id`）；
    # 签到 = `billing/claim` + 激活事件（**需阿里云 captcha 且一次性**，`20 §3.1`）；
    # 目录 = **静态白名单起步**（§22.4）；**不可续期**（`20 §2.6`）。
    "zcode": ProductMeta(
        id="zcode", title="ZCode",
        login="device_code",
        protocol="anthropic",            # Anthropic Messages（`upstream/zcode/auth.py:7`）
        # 出站基址 = Plan/JWT 通道的 anthropic 基址（`upstream/zcode/auth.py:7` 同值；
        # ≠ `config/schemas.py:58` 的 `plan_base_url`——那是计费/领取用的 base，用途不同）
        base_url="https://zcode.z.ai/api/v1/zcode-plan/anthropic",
        device=DeviceSpec(fields=("device_mid",), derive=False),
        capabilities=Capabilities(balance=True, checkin=True,
                                  onboarding=False, permanent_lock=False, refresh=False),
        models_source="static",
        # 🔴 整根隔离布局：凭据只落在 `<账号>/data/.zcode/v2/credentials.json`
        # （`mgw zcode import` 写的那份），公共层 `credentials.json` 实盘 16 个号**全部没有**
        # ⇒ 转发腿必须让产品层的 `outbound_credentials` 去判凭据在不在，
        #   不能在公共读取入口读空就当"无凭据"（2026-10-05 D1 轮实测的真因）。
        credentials_from="product",
    ),
}


def get(product: str) -> ProductMeta:
    """按产品 id 取注册信息（**未知产品显式失败**，不静默降级）。

    未登记的产品没有账号目录、没有能力位 —— 静默返回空规格会让上层"以为它存在"
    （§22.6：未登记 = 不支持，宁可当场 KeyError 也不渲染必然失败的按钮）。
    """
    try:
        return PRODUCTS[product]
    except KeyError:
        raise KeyError(
            f"未登记的产品 {product!r}（在册：{'/'.join(PRODUCT_IDS)}）") from None
