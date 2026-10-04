"""Qoder 同族产品配置（国际版 `qoder` / 中国版 `qodercn`）—— **差异全部是本文件的字段值**。

照抄依据（DSH，只读取证）：`/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts/src/qoder-product.ts`

| 本项目 | DSH 对应 | 行号 |
|---|---|---|
| `QODER`（国际版实例） | `export const QODER` | `qoder-product.ts:439-459` |
| `QODER_CN`（中国版实例） | `export const QODER_CN` | `qoder-product.ts:584-631` |
| `QODER_MODELS`（国际兜底目录 17 条） | `QODER_FALLBACK_MODELS` | `qoder-product.ts:362-436` |
| `QODER_CN_MODELS`（中国兜底目录 14 条） | `QODER_CN_FALLBACK_MODELS` | `qoder-product.ts:480-581` |
| `require_qoder_family`（防串用） | `requireQoderFamily` | `jet-hub-rpc.ts:753-757` |

🔴 **两站 token 不通用**（`20 §4.1` 引 `jet-hub-rpc.ts:1287-1295` 注释）：国际/中国的
   `authBase` / `openApiBase` / `clientId` 各不相同，**任何请求都必须显式带区域配置**
   （本文件的 `QoderProduct` 实例）——产品钩子层除此之外没有任何默认值。
🔴 **定价字段已回填**（2026-10-01；`ModelInfo` 增了 `free` / `rate` 字段后不再"无处承载"）：
   `priceFactor` / `originalPriceFactor` / `promotion` 逐条从 DSH 表搬入（见各条注释与
   `billing_info`）。原先「不搬运」的理由（契约无对应字段）已随字段新增失效。
   仍**不搬运**的 DSH 字段：`isFree`（`qoderDisplayName` 的免费判据是 `priceFactor === 0`，
   `isFree` 从不参与展示，搬进来是死数据）与 `promotion.badgeZh`（"错峰 N 折"角标，
   DSH 注释明说当前不参与展示，`qoder-product.ts:157-164`）。
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QoderPromotion:
    """错峰折扣（目录 `promotion`；DSH `QoderModelPromotion` 的字段子集，`qoder-product.ts:139-165`）。

    ⚠️ **`active` 是「目录下发那一刻」的快照，不可作为长期判据**：用户长时间不重启
    客户端时它会过期。真实窗口由 `window_start` / `window_end` 描述且稳定，故展示时
    **按当前时间本地推算**（见 `promotion_active_now`），`active` 仅作窗口缺失时的回退
    （`qoder-adapter.ts:1042-1052`）。

    关系式（实测三条全部吻合，`qoder-product.ts:91-93`）：
    `price_factor === before_promotion_price_factor × discount_factor`
    —— 故可据原价与折扣推算任意时刻的生效价。
    """

    #: 目录下发时是否处于折扣时段内（远端 `active`；快照值，仅作回退）。
    active: bool = False
    #: 折扣后倍率（远端 `discount_factor`），如 0.4 = 4 折。
    discount_factor: float | None = None
    #: 折扣前倍率（远端 `before_promotion_price_factor`）。
    before_promotion_price_factor: float | None = None
    #: 时段起点（远端 `window_start`，如 `22:00`）。
    window_start: str = ""
    #: 时段终点（远端 `window_end`，如 `08:00`）。
    window_end: str = ""


@dataclass(frozen=True)
class QoderModel:
    """兜底目录的一条（DSH `QoderFallbackModel` 的字段子集，见模块头「不搬运」说明）。

    - `context_window`：取官方档位表 `context_config` 的**最大档**，不是 `max_input_tokens`
      （`qoder-product.ts:38-46`；两站同口径，CN 的实测论证见 `:485-518`）；
    - `efforts`：目录 `thinking_config.enabled.efforts` 的**键**（目录原序，`:99-119`）；
    - `supports_disable`：目录存在 `thinking_config.disabled` 分支 —— 客户端会**追加** `none`
      （「关闭思考」，`:107-110` 的 `gU()` 复刻规则）；
    - `supports_image`：目录 `is_vl`。缺省 `False` = 该条未声明 → 按 DSH 的保守口径报
      text-only（`qoder-adapter.ts:507-511` 的 `inputModalitiesFor`）；
    - `supports_thinking`：目录 `is_reasoning`（DSH `supportsThinking`），M6-5c 回填 ——
      它是**出站请求体** `model_config.is_reasoning` 的取值（`qoder-adapter.ts:715`
      的 `fallback?.supportsThinking ?? false`）。缺省 `False` = DSH 原表未声明。
      取证：`qoder-product.ts:362-436`（国际 17 条）/ `:480-581`（CN 14 条）逐条值。
    - `price_factor` / `original_price_factor` / `promotion`（2026-10-01 回填）：目录
      `price_factor` / `original_price_factor` / `promotion` 的实测值（`qoder-product.ts:355-359`
      的字段口径）。**`price_factor: 0` 是合法的免费值**，不能用 `> 0` 过滤
      （`qoder-product.ts:66-68`；qfmodel 实测为 0）。
    """

    id: str
    name: str
    context_window: int
    supports_image: bool = False
    efforts: tuple[str, ...] = ()
    #: 目录 `efforts.<key>.is_default === true` 的键；空 = 不设（上游自行决定）
    default_effort: str = ""
    #: 目录存在 `disabled` 分支 → 可选「关闭思考」（追加 `none`）
    supports_disable: bool = False
    #: 目录 `is_reasoning`（出站请求体的 `model_config.is_reasoning`，M6-5c）
    supports_thinking: bool = False
    #: 计费倍率（目录 `price_factor`；**采集时刻的生效价**，会随错峰窗口变化，
    #: `qoder-product.ts:53-70`）。`None` = 该条未下发（不编造）。
    price_factor: float | None = None
    #: 促销前的原价倍率（目录 `original_price_factor`；仅部分模型下发，`qoder-product.ts:72-79`）。
    original_price_factor: float | None = None
    #: 错峰折扣（目录 `promotion`；三档实测，`qoder-product.ts:80-95`）。
    promotion: QoderPromotion | None = None


#: 国际版兜底目录（**17 条**，`qoder-product.ts:362-436` 逐条照抄）。
#: ⚠️ 这些 id 是**目录 key**（如 `qfmodel`）—— 只有加密端点认它们；公开 OpenAI 兼容端点
#: 只认通用名（`qwen-flash` 等），发错会回 `Unsupported model`（`:311-343`）。
#: ⚠️ `price_factor` 等定价字段为 2026-10-01 回填（逐条对照 `:387-435`）；**0 是合法值**
#: （qfmodel 免费），窗口「22:00–08:00」与折扣值为 `:401-425` 的实测原值。
QODER_MODELS: tuple[QoderModel, ...] = (
    QoderModel("auto", "Auto", 200_000, True, price_factor=0.5),
    QoderModel("ultimate", "Ultimate", 1_000_000, True,
               ("xhigh", "high", "low", "max", "medium"), "high", True,
               supports_thinking=True, price_factor=2),
    QoderModel("performance", "Performance", 1_000_000, True,
               ("xhigh", "high", "low", "max", "medium"), "medium", True,
               price_factor=1.1),
    QoderModel("efficient", "Efficient", 1_000_000, True, price_factor=0.3),
    QoderModel("smodel", "Sonus", 1_000_000, True,
               ("xhigh", "high", "low", "max", "medium"), "high",
               supports_thinking=True, price_factor=8),
    QoderModel("cmodel", "Cantus", 1_000_000, True,
               ("xhigh", "high", "low", "max", "medium"), "high",
               supports_thinking=True, price_factor=4),
    QoderModel("qmodel_38max", "Qwen3.8-Max", 1_000_000, True,
               ("xhigh", "low", "medium"), "xhigh", True,
               supports_thinking=True, price_factor=0.2,
               promotion=QoderPromotion(active=True, discount_factor=0.4,
                                        before_promotion_price_factor=0.5,
                                        window_start="22:00", window_end="08:00")),
    QoderModel("qfmodel", "Qwen3.8-Flash", 1_000_000, True,
               ("xhigh", "low", "medium"), "medium", True,
               supports_thinking=True, price_factor=0,
               original_price_factor=0.1),
    QoderModel("qmodel_latest", "Qwen3.7-Max", 1_000_000, True,
               (), "", True, price_factor=0.1, original_price_factor=0.5,
               promotion=QoderPromotion(active=True, discount_factor=0.2,
                                        before_promotion_price_factor=0.5,
                                        window_start="22:00", window_end="08:00")),
    QoderModel("qmodel", "Qwen3.7-Plus", 1_000_000, True, (), "", True,
               price_factor=0.04,
               promotion=QoderPromotion(active=True, discount_factor=0.4,
                                        before_promotion_price_factor=0.1,
                                        window_start="22:00", window_end="08:00")),
    QoderModel("kmodel_latest", "Kimi-K3", 1_000_000, True,
               ("high", "low", "max"), "max", price_factor=1.4),
    QoderModel("kmodel", "Kimi-K2.8-Preview", 1_000_000, True,
               ("high", "low", "max"), "max", price_factor=0.8),
    QoderModel("gmodel", "GLM-5.3", 1_000_000, True,
               ("high", "low", "max"), "max",
               supports_thinking=True, price_factor=0.8),
    QoderModel("gfmodel", "GLM-5.3-Flash", 1_000_000, True,
               ("high", "max"), "max",
               supports_thinking=True, price_factor=0.1),
    QoderModel("dmodel", "DeepSeek-V4-Pro", 1_000_000, True,
               ("high", "max"), "max", True,
               supports_thinking=True, price_factor=0.5),
    QoderModel("dfmodel", "DeepSeek-Flash", 1_000_000, True,
               ("high", "max", "low"), "max", True,
               supports_thinking=True, price_factor=0.1),
    QoderModel("mmodel", "MiniMax-M3", 1_000_000, True, price_factor=0.2),
)

#: 中国版兜底目录（**14 条**，`qoder-product.ts:480-581` 逐条照抄）。
#: ⚠️ 不能沿用国际版那张表（`:466-473`）：CN 独有 `q37fmodel` / `gm51model`；CN 没有
#: `ultimate` / `performance` / `efficient` / `smodel` / `cmodel`（沿用会让菜单出现 CN
#: 端点根本不认的模型）；`mmodel` 在 CN 是 MiniMax-M2.7 且档位表只有 200K。
#: ⚠️ 定价字段同国际版口径（2026-10-01 回填，逐条对照 `:531-580`）。
QODER_CN_MODELS: tuple[QoderModel, ...] = (
    QoderModel("auto", "Auto", 200_000, True, supports_thinking=True, price_factor=0.5),
    QoderModel("qmodel_38max", "Qwen3.8-Max", 1_000_000, True,
               ("xhigh", "low", "medium"), "medium", True,
               supports_thinking=True, price_factor=0.2,
               promotion=QoderPromotion(active=True, discount_factor=0.4,
                                        before_promotion_price_factor=0.5,
                                        window_start="22:00", window_end="08:00")),
    QoderModel("qfmodel", "Qwen3.8-Flash", 1_000_000, True,
               ("xhigh", "low", "medium"), "medium", True,
               supports_thinking=True, price_factor=0,
               original_price_factor=0.1),
    QoderModel("qmodel_latest", "Qwen3.7-Max", 1_000_000, True, (), "", True,
               supports_thinking=True, price_factor=0.1, original_price_factor=0.5,
               promotion=QoderPromotion(active=True, discount_factor=0.2,
                                        before_promotion_price_factor=0.5,
                                        window_start="22:00", window_end="08:00")),
    QoderModel("qmodel", "Qwen3.7-Plus", 1_000_000, True, (), "", True,
               supports_thinking=True, price_factor=0.04,
               promotion=QoderPromotion(active=True, discount_factor=0.4,
                                        before_promotion_price_factor=0.1,
                                        window_start="22:00", window_end="08:00")),
    QoderModel("q37fmodel", "Qwen3.7-Flash", 1_000_000, True,
               supports_thinking=True, price_factor=0.1),
    QoderModel("dmodel", "DeepSeek-V4-Pro", 1_000_000, True,
               ("high", "max"), "max", True,
               supports_thinking=True, price_factor=0.5),
    # ⚠️ CN 的 `is_reasoning` 为 false（国际版为 true）→ 不声明 supports_thinking
    #（`qoder-product.ts:556-558` 的注释就在说明这一差异）。
    QoderModel("dfmodel", "DeepSeek-Flash", 1_000_000, True,
               ("high", "max", "low"), "max", True, price_factor=0.1),
    QoderModel("gmodel", "GLM-5.3", 1_000_000, True,
               ("high", "low", "max"), "max",
               supports_thinking=True, price_factor=0.8),
    QoderModel("gfmodel", "GLM-5.3-Flash", 1_000_000, True,
               ("high", "max"), "max",
               supports_thinking=True, price_factor=0.1),
    QoderModel("gm51model", "GLM-5.2", 1_000_000, True,
               ("high", "max"), "max", True,
               supports_thinking=True, price_factor=0.6),
    QoderModel("kmodel_latest", "Kimi-K3", 1_000_000, True,
               ("high", "low", "max"), "max", price_factor=1.4),
    QoderModel("kmodel", "Kimi-K2.8-Preview", 1_000_000, True,
               ("high", "low", "max"), "max",
               supports_thinking=True, price_factor=0.8),
    QoderModel("mmodel", "MiniMax-M2.7", 200_000, False, price_factor=0.2),
)


@dataclass(frozen=True)
class QoderProduct:
    """一个区域实例的全部差异（DSH `QoderProduct` 的**字段子集**，`qoder-product.ts:172-306`）。"""

    #: = `accounts/registry.py` 的键 = 账号目录名 = 凭据族标记（防串用）
    id: str
    #: 展示名（DSH `displayName`）
    title: str
    #: 授权页基址（DSH `authBase`，`:442` / `:592`）
    auth_base: str
    #: OpenAPI 基址 —— **登录轮询 / 续期 / userinfo / 额度 / 活动全部挂它**（DSH `openApiBase`）
    open_api_base: str
    #: 公开 OpenAI 兼容端点（DSH `inferBase`；只认通用名、不认目录 key → 本层不发，仅登记）
    infer_base: str
    #: 加密端点（DSH `encryptedInferBase`）—— **认目录 key**；资源 `base_url` 取它（M6-5 接线）
    encrypted_infer_base: str
    #: PKCE 设备码 `client_id`（prod，DSH `clientId`；⚠️ 两站完全不同，`:446` / `:609`）
    client_id: str
    #: `/sash/` 端点（用量/活动）的 `Cosy-ClientType` 头（桌面 app 身份 `'10'`，`:274` / `:626`）
    sash_client_type: str
    #: **推理请求加密信封**里的客户端身份（DSH `clientMetadata`，`:448-453` / `:619-624`）。
    #: 🔴 与上面的 `sash_client_type` 是**两个不同身份，不许合并**：本值是官方 CLI 默认值
    #: （`client_type '5'` + `business_product 'cli'`，源码 `Fp()`），只喂 `QoderContext`；
    #: `'10'` 是桌面 app 身份，只用于 `/sash/` 活动/用量端点（DSH `qoder-product.ts:247-262`
    #: 实测：`/sash/api/v1/me/campaigns` 带 `'5'` 回 `claimable:false`，带 `'10'` 才下发活动）。
    client_metadata: dict
    #: `User-Agent` 前缀（DSH `userAgentPrefix`，两站同值 `qoder`；续期/推理拼 `qoder/1.0.0`）
    user_agent_prefix: str
    #: 兜底模型目录（恒本地，零网络；§22.4「恒本地兜底表」）
    fallback_models: tuple[QoderModel, ...]


#: 国际版（`qoder-product.ts:439-459`）。
QODER = QoderProduct(
    id="qoder",
    title="Qoder",
    auth_base="https://qoder.com",                       # :442
    open_api_base="https://openapi.qoder.sh",            # :443（轮询/续期/userinfo/额度）
    infer_base="https://api2-v2.qoder.sh",               # :444（公开端点，不认目录 key）
    encrypted_infer_base="https://api2.qoder.sh",        # :445（认目录 key）
    client_id="e883ade2-e6e3-4d6d-adf7-f92ceff5fdcb",    # :446（prod 用的 J_a）
    sash_client_type="10",                               # :455
    client_metadata={"client_type": "5", "business_product": "cli",
                     "business_type": "agent", "scene": "assistant"},   # :448-453（CLI 身份）
    user_agent_prefix="qoder",                           # :456
    fallback_models=QODER_MODELS,
)

#: 中国版（`qoder-product.ts:584-631`）。
#: ⚠️ `authBase` / `openApiBase` / `clientId` / 加密端点**四项全部与国际版不同**；
#: `clientId` 用错国际版 id 的症状是「授权页 302 正常、点击授权后报参数无效」（`:606-608`）。
QODER_CN = QoderProduct(
    id="qodercn",
    title="Qoder（中国版）",
    auth_base="https://qoder.cn",                        # :592
    open_api_base="https://openapi.qoder.com.cn",        # :593
    infer_base="https://gateway.qoder.com.cn",           # :601（CN 无可用公开端点，实测 503）
    encrypted_infer_base="https://gateway.qoder.com.cn", # :604
    client_id="732aef47-9cf2-46a2-95fe-4cebb5d0d1fa",    # :609（CN prod；test 同值 :612）
    sash_client_type="10",                               # :626（CN asar 同为 clientType 10）
    # 沿用国际版的 **CLI** 身份（DSH `:613-624` 同此，并留了一句实话：CN 桌面端自己用的是
    # app 身份，插件走 CLI 在国际版实测可用、CN 侧「若被拒再改这一组值」。本仓照此登记，
    # 🔴 不宣称 CN 的 CLI 身份已实测通过 —— 那要看第一次真实签名请求的回执（见 §22.4 待验）。
    client_metadata={"client_type": "5", "business_product": "cli",
                     "business_type": "agent", "scene": "assistant"},
    user_agent_prefix="qoder",                           # :628
    fallback_models=QODER_CN_MODELS,
)

#: 全部同族实例（顺序 = `require_qoder_family` 的查找顺序，`qoder-product.ts:640`）。
ALL_QODER_PRODUCTS: tuple[QoderProduct, ...] = (QODER, QODER_CN)

#: 凭据里的**本地**区域标记键（非上游字段；凭据是产品私有格式）。
#: 登录/续期时写入本产品 id → 续期/探活/额度/领取先校验，**杜绝两站串用**
#: （`20 §4.1`：国际/中国两站 token 不通用；DSH 侧由「按 provider 取实例」结构性保证）。
FAMILY_KEY = "family"


class UnknownQoderFamilyError(RuntimeError):
    """非 Qoder 同族的产品 id（DSH `requireQoderFamily` 的 `Unknown Qoder family provider`）。"""


class FamilyMismatchError(RuntimeError):
    """凭据的区域标记与本产品不符 —— **拒绝操作、不打上游**（两站 token 不通用）。"""


def require_qoder_family(product_id: str) -> QoderProduct:
    """按产品 id 取同族区域配置；非本族 → **显式失败**（DSH `requireQoderFamily` 语义）。

    照抄 `jet-hub-rpc.ts:753-757`：存在性判定与取用分开，取不到就抛错而不是返回 `None`
    ——「否则中国版会拿国际版的域名与 client_id 发请求」（`:948-949` 的注释）。
    """
    for product in ALL_QODER_PRODUCTS:
        if product.id == product_id:
            return product
    raise UnknownQoderFamilyError(
        f"Unknown Qoder family provider: {product_id!r}"
        f"（在册：{'/'.join(p.id for p in ALL_QODER_PRODUCTS)}）")


def efforts_for(model: QoderModel) -> tuple[str, ...]:
    """模型在 UI 上可选的思考档位（复刻客户端 `gU()`，DSH `qoderEffortsFor`，`qoder-adapter.ts:152-156`）。

    - `efforts` 原样（目录顺序保持）；
    - `supports_disable` 为真时**追加** `none`（「关闭思考」）；两者皆无 → 空数组
      （调用方**不声明** `reasoning` —— UI 显示「当前模型未提供推理等级」，与 IDE 一致）。
    """
    efforts = list(model.efforts)
    if model.supports_disable and "none" not in efforts:
        efforts.append("none")
    return tuple(efforts)


def model_of(product: QoderProduct, model_key: str) -> QoderModel | None:
    """按**目录 key** 取兜底目录里的一条（M6-5c 出站用）。

    取不到 → `None`：出站塑形对未知 key **不编造** `is_reasoning`/`is_vl` 等目录字段
    （DSH 同口径：`fallback` 缺失时 `isReasoning` 落 false、`isVl` 缺省 true，
    但那是 DSH 的兜底；本层把它显式记为「目录未收录」，由调用方决定取哪些默认）。
    """
    for model in product.fallback_models:
        if model.id == model_key:
            return model
    return None


# ---------- 计费（`qoderDisplayName`，`qoder-adapter.ts:1042-1119`）----------

#: `HH:MM`（容忍小时不补零；用 `[0-9]` 避免 Python 的 `\d` 收 Unicode 数字）
_HHMM_RE = re.compile(r"^([0-9]{1,2}):([0-9]{2})$")


def _rate_text(value: float) -> str:
    """倍率数字 → 展示文本（无尾随 0，不出现科学计数法）。

    对齐 JS 的 `x${price}` 字符串形态（`0.5` → `x0.5`、`2` → `x2`、`0.04` → `x0.04`）。
    """
    number = f"{value:.10f}".rstrip("0").rstrip(".")
    return f"x{number or '0'}"


def promotion_active_now(promotion: QoderPromotion, now: dt.datetime | None = None) -> bool:
    """当前是否落在错峰折扣窗口内（本地推算，`promotionActiveNow`，`qoder-adapter.ts:1042-1072`）。

    🔴 **为什么不直接用目录的 `promotion.active`**：那是**目录下发那一刻**的快照，
       客户端长时间不重启就会过期 —— 用它会让用户在窗口外看到折后价（按折扣价预期、
       实际按原价计费），或窗口内看不到折扣。窗口本身（`window_start`/`window_end`）稳定，
       故按当前时间**本地推算**（`qoder-adapter.ts:1042-1048`）。

    窗口按 **UTC+8** 计（目录 `timezone: Asia/Singapore`，与用户所在时区一致，
    `qoder-adapter.ts:1050-1051`）；支持跨零点（如 22:00–08:00）。
    窗口字段缺失 / 非法时回退到目录的 `active`（快照兜底，`:1055,1064`）。
    `now` 为注入缝（缺省 = 当下；naive 视为本机时区）—— 与 DSH 的
    `promotionActiveNow(promo, now)` 形参同构，供单测喂固定时刻。
    """
    moment = dt.datetime.now(dt.timezone.utc) if now is None else now
    if moment.tzinfo is None:
        moment = moment.astimezone()
    start = _parse_hhmm(promotion.window_start)
    end = _parse_hhmm(promotion.window_end)
    if start is None or end is None:
        return promotion.active
    # 取 UTC+8 的「墙上时间」（目录时区与用户一致，故无需真实时区换算，
    # `qoder-adapter.ts:1066-1068`）
    utc8 = moment.astimezone(dt.timezone(dt.timedelta(hours=8)))
    minutes = utc8.hour * 60 + utc8.minute
    return minutes >= start and minutes < end if start <= end \
        else minutes >= start or minutes < end


def _parse_hhmm(value: str) -> int | None:
    """`HH:MM` → 当日分钟数；非法 → `None`（`toMinutes`，`qoder-adapter.ts:1056-1061`）。"""
    if not isinstance(value, str):
        return None
    found = _HHMM_RE.match(value.strip())
    if found is None:
        return None
    hours, minutes = int(found.group(1)), int(found.group(2))
    return hours * 60 + minutes if hours < 24 and minutes < 60 else None


def billing_info(model: QoderModel, now: dt.datetime | None = None) -> tuple[bool | None, str]:
    """模型 → `(free, rate)`（复刻 `qoderDisplayName`，`qoder-adapter.ts:1099-1119`）。

    - `price_factor == 0` → `(True, "x0")`（**免费优先于一切**；`0` 是合法倍率，不能显示成
      `x0` 之外的编造值，`:1106-1107`）。DSH 同情形展示「免费」，本层由 `free=True` 表达；
    - 折扣**当前生效**（窗口本地推算，不采信 `promotion.active`）→ `x原价→x折后价`，
      折后价 = `beforePromotionPriceFactor × discountFactor`（四舍五入到 4 位，
      对齐 `Number((before*discount).toFixed(4))`，`:1109-1112`）；
    - 窗口外 / 无折扣 → **原价**（有 promotion 时原价 = before，而非采集到的折后价，
      `:1115-1118`）；
    - `price_factor` 未下发（`None`）→ `(None, "")`（**不编造**，`:1118` 的
      `price !== undefined` 分支）。
    """
    promo = model.promotion
    before = promo.before_promotion_price_factor if promo is not None else None
    discount = promo.discount_factor if promo is not None else None
    has_promo = promo is not None and before is not None and discount is not None
    if model.price_factor == 0:
        return True, "x0"
    if has_promo and promotion_active_now(promo, now):
        effective = round(before * discount, 4)
        return False, f"{_rate_text(before)}→{_rate_text(effective)}"
    price = before if has_promo else model.price_factor
    if price is None:
        return None, ""
    return False, _rate_text(price)
