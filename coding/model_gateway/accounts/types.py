"""公共层**冻结类型**（tech-design v2.0 §22.3；M6-1 之后签名不得再改）。

🔴 本模块**只放类型**，不放实现。字段/字面量与 §22.3 逐字一致；
   新增字段一律带默认值（§22.3 的加字段纪律）。
🔴 裁决回填（2026-09-29，M6-1 报告后由总 agent 落地，见 §22.3 的三条补入）：
   ① `ClaimOutcome` 定义在本模块、`category` 复用 `ops.base.Category`（已获裁决，非私改）；
   ② `protocol` 字面量补入 `custom`；③ 备选登录形态 = `login_alt`（带默认值，放字段末尾）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from model_gateway.ops.base import Category

#: 登录方式（§22.3 冻结字面量）：设备码 / 外链 / 本机回跳 / 扫码 / 短信
LoginKind = Literal["device_code", "external_link", "local_callback", "qr", "sms_code"]

#: 登录状态机（§22.3「pending 不是错误」）：pending 是**正常业务状态**，不得当失败处理
LoginState = Literal["pending", "success", "failed", "expired"]

#: 额度三态（§22.3 + `23 B2`）：**未知不当零** —— `unknown` 必须与「真的为 0」分开
QuotaState = Literal["available", "exhausted", "unknown"]


@dataclass(frozen=True)
class Capabilities:
    """产品能力位（§22.3 / `20 §3.1` 逐产品清点）。

    与前端按钮**同源**（§22.6「能力矩阵是判据不是标签」）：默认 `False` = 不支持
    → 前端**不渲染**按钮（未登记 = 点了必然失败，照抄 `credits-capabilities.js` 语义）。

    - `balance`：有余额/额度查询通道（`20 §3.1`：11 个产品全部 ✓）
    - `checkin`：有可调用的签到/领取端点。**没有端点的产品必须 False** ——
      典型反例：`raccoon` 每日积分由服务端自动发放（`20 §3.1`），做成按钮必然失败
    - `onboarding`：一次性新手任务/登录奖励（`loomy` / `raccoon`，`20 §3.1`）
    - `permanent_lock`：永久积分锁定开关（`buddy` / `workbuddy` / `loomy`，`20 §3.3`）
    - `refresh`：凭据**可续期**（`refresh` 钩子可用）。`loomy` / `zcode` 不可续期
      （`20 §2.6`：loomy 的 refreshAll 只探测已过期账号；zcode 只做磁盘凭据回写）
    """

    balance: bool = False
    checkin: bool = False
    onboarding: bool = False
    permanent_lock: bool = False
    refresh: bool = False


@dataclass(frozen=True)
class DeviceSpec:
    """per-product 设备字段字典（Q26-② 的落地形态，§22.3）。

    - `fields`：该产品所需的设备字段名（如 `("machine_id", "device_id")`）；
      **空元组 = 该产品没有设备身份**（`20 §2.7`：buddy/workbuddy/cline/loomy 无设备标识）。
      字段住在每账号的 `meta.json`（§22.2），**不写进凭据本体**。
    - `derive`：`True` = 可从账号 uid/id **确定性派生**（`20 B12/§3.5`：trae 的
      `device_id = f(uid)`，纯函数、跨进程稳定、天然互异、免持久化）；
      `False` = 随机生成（zcode 的 uuid4 即此类）。
    """

    fields: tuple[str, ...]
    derive: bool


@dataclass(frozen=True)
class ProductMeta:
    """产品注册信息（`upstream/<product>/product.py::meta()` 从 registry 取本实例）。"""

    id: str
    title: str
    login: LoginKind
    #: 上游协议族（决定出站适配基类）。`custom` = 需产品专属出站塑形
    #: （`qoder`/`qodercn` 信封、`trae` SSE 成帧；§22.4）——缺口①已由总 agent 裁决（2026-09-29）。
    protocol: Literal["openai", "anthropic", "custom"]
    #: 上游基址（资源物化时写入 `Resource.base_url`，§22.5-1）；未核实的留空
    base_url: str
    device: DeviceSpec
    capabilities: Capabilities
    #: 目录来源：远端探测 / 磁盘缓存 / 恒本地静态表（`21 §1.1` 四型收敛）
    models_source: Literal["remote", "cache", "static"]
    #: 备选登录形态（裁决补入 2026-09-29：`loomy`/`raccoon` = 扫码 / 短信双路径，
    #: `20 §2.8/§4.1`）；默认空元组 = 只有主形态。**放字段末尾**以满足 dataclass 默认值顺序。
    login_alt: tuple[LoginKind, ...] = ()


@dataclass
class Challenge:
    """登录挑战的**用户可见载荷**（§22.3：只承载用户可见物）。

    四型登录向导（设备码展示 / 外链打开 / 回跳粘贴 / 二维码，§22.7）都从这里取展示物；
    **凭据、中间令牌、设备码私钥一律不进本结构**（它们走 `LoginSession.state`）。
    """

    #: 外链授权页地址（external_link / local_callback / qr 型的展示物）
    url: str = ""
    #: 设备码（device_code 型：展示 + 复制）
    device_code: str = ""
    #: 二维码**图片**（qr 型）：`data:image/...;base64,` 的 data URI，由**服务端出图**
    #: （M7-C1 推翻旧口径「内容串 + 前端自绘」—— 前端没有编码器，也没有微信那张图的取回权限，
    #: 旧口径的实际结果是"一行让用户拿手机扫的文字"与一张永远加载失败的 `<img>`）。
    #: 内容串的归宿 = `Challenge.url`（qr 型：url 恒为**可复制的展示文本**，图片在 qr_payload）；
    #: 出图实现见 `accounts/qr.py`（raccoon 自造码本地编 PNG）与 `upstream/loomy/wechat.py`
    #: （loomy 取微信自己那张 JPEG）。空串 = 本次没有图（界面**不得**画一个空 `<img>`）。
    qr_payload: str = ""
    #: 短信是否已发出（sms_code 型）
    sms_sent: bool = False


@dataclass
class LoginOutcome:
    """登录轮询/回调的结果（§22.3 两步式的第二步）。

    🔴 `state == "pending"` 是**正常业务状态**（用户还没操作完），不是错误 ——
       入口层必须原样透传，不得计失败、不得据此冷却账号。
    🔴 `state == "success"` 时 `credentials`/`meta` 由 **会话引擎**经
       `store.commit_login()` 落盘（写回自检 + 失败回滚），落盘失败会把 state 翻成
       `failed`（不谎报成功）。
    """

    state: LoginState = "pending"
    #: 凭据本体（产品私有格式，明文；**只在本进程内流转**，入口层不得回传明文）
    credentials: dict = field(default_factory=dict)
    #: 账号元信息（设备字段 / plan / 备注…）→ meta.json 的新增部分
    meta: dict = field(default_factory=dict)
    #: 面向用户的说明（等待原因 / 失败原因）；**不含凭据**
    detail: str = ""


@dataclass(frozen=True)
class ProbeResult:
    """探活结果（§22.3「连通 / 凭据有效」两个维度分开）。"""

    #: 网络可达（DNS/连接/HTTP 层拿到了响应）
    reachable: bool = False
    #: 凭据有效（上游认可该凭据，未被 401/403 拒绝）
    valid: bool = False
    detail: str = ""

    @property
    def ok(self) -> bool:
        """两维都成立才算探活通过（缺一即不可用）。"""
        return self.reachable and self.valid


@dataclass(frozen=True)
class QuotaSnapshot:
    """额度快照（§22.3 三态 + `source`，照抄 `23 B2`「未知不当零」）。

    `unknown` 与 `exhausted` **必须分开**：前者是"没查到/查不动"（不能据此停用资源），
    后者是"确实为 0"（选路可据此跳过）。`source` 记录数据来源（如 `"zcode-log"`），
    便于事后判断该结论是不是过期通道给的。
    """

    state: QuotaState = "unknown"
    source: str = ""
    detail: str = ""


@dataclass(frozen=True)
class ModelInfo:
    """产品目录里的一条模型（§22.5-4：vendor 模型 ID 直接作为 `ModelResource.model`）。

    字段镜像网关**内置目录**（`enums` 的 `EnumEntry`：`core/capabilities.py` 逐字段取用），
    供 `/v1/models` 能力位组装。

    🔴 **取不到不编造**（`21 §5.1-1`）：`None` = 未取到（序列化时**不写**该字段），
       `False` = 明确不支持 —— 两者语义不同，编造偏大值会被上游 400。
    """

    id: str
    name: str = ""
    vendor: str = ""
    context_window: int | None = None
    max_output: int | None = None
    tool_call: bool | None = None
    image_input: bool | None = None
    reasoning: bool | None = None
    effort_levels: tuple[str, ...] = ()
    #: 计费倍率结构化字段（2026-10-01 加字段，§22.3 加字段纪律：带默认值放字段末尾）——
    #: 供管理端展示「消耗规则 / 是否免费」。此前只有部分产品把倍率拼进展示名，
    #: 其余产品在 ModelInfo 里被丢弃。逐产品取证与解析规则见各 `upstream/<product>/`
    #: 模块的注释（DSH 参考源 `deepseek-harness-codearts/src/`）。
    #: `free`：True=免费 / False=有计费 / None=**未取到**（不编造，`21 §5.1-1`）。
    #: 逐产品判据：`credits`/`costMultiplier`/`consumption_rate.rate`/`price_factor`
    #: 等计费值等于 0 → True；取不到计费字段 → None（与「明确为 0」分开）。
    free: bool | None = None
    #: `rate`：展示用倍率文本（如 `x0.75` / `x0.2→x0.1`（促销：原价→折后价）/ `x1`；
    #: 免费记为 `x0`，`free=True` 才是「免费」的权威信号）。空串 = **未提供**
    #: （该模型的上游目录不下发计费字段；**不编造** `x1`）。
    rate: str = ""


@dataclass(frozen=True)
class ClaimOutcome:
    """签到/领取结果（§22.6：**结果语义 = `ops` 四类**，出口复用既有 JSONL + 红点）。

    只有 `failed` 需要用户关注；`already_done` / `inactive` 是正常业务状态
    （`ops/base.py` 的 `Category` 字面量集合，此处直接复用不另写一份）。
    `category` **不给默认值**：钩子必须显式表态（照抄 `20 §3.2` 的穷尽性纪律 ——
    "宁可多报一个失败，也不让结果凭空消失"）。

    🔴 `retryable`（R1-F2 修复；§22.3 加字段纪律：带默认值）：**结构化可重试声明**。
    钩子把网络/超时/5xx 类失败折叠成 `failed` 时必须在构造处显式声明 `retryable=True`；
    业务码 / 凭据缺失 / 配置类失败保持默认 `False`。批量执行器（`ops/runner.py`）
    按本字段退避重试，**不再去猜失败文案**（详情文案是给人读的，文案一改判据就静默失效）。
    """

    category: Category
    detail: str = ""
    #: 默认 False = 不重试（业务码/凭据类失败的正确取值；只有网络/5xx 类才可为 True）
    retryable: bool = False


class NotRefreshable(RuntimeError):
    """凭据**不可续期**（`refresh` 钩子的合法返回值形态，§22.3）。

    出现在两处：产品钩子里 `raise NotRefreshable(...)`（如 zcode，`20 §2.6`），
    以及入口层据此把"续期"按钮置灰/跳过 —— **不是**异常故障，不触发冷却。
    """
