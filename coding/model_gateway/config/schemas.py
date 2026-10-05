"""配置 schema：PRD §6（v1.5）+ tech-design §4.7 运行参数的 pydantic v2 落地。

- 全部字段明文 YAML；密钥仅存本地（铁律 1）。
- 数值边界（tech-design §4.7 ③）：x>=1、y>=1、m>=0、冷却>=0、退避>=0、超时>=1、总预算>=超时。
- 资源模型扁平化（Q18-②）：resources[] = 供应商 + Key（账号标识为次要备注），
  ID 由系统自动生成（管理 API 保存时补齐），用户无需输入。
- 引用完整性（resources <-> models[].resources）在 AppConfig 根校验器。
- P1 字段（quotas 等）读入保留、不校验语义（tech-design §4.7 P1 预留条目）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Endpoint = Literal["chat", "images"]
AccessMode = Literal["api", "plan"]
Protocol = Literal["openai", "anthropic", "gemini"]

# 错误分类（tech-design §4.3 / FR-3.13）
ErrorClass = Literal["RETRYABLE", "BAD_REQUEST", "AUTH", "NOT_FOUND", "QUOTA", "CANCELED"]


class Quotas(BaseModel):
    """令牌配额（P1 预留：M1 读入保留、不校验上限，M3 启用语义）。"""

    daily_requests: int = 0
    daily_tokens: int = 0
    total_tokens: int = 0


class AccessToken(BaseModel):
    """网关接入密钥：工具端 Bearer 凭据（API 接入页管理，多密钥区分不同工具，Q18-④）。

    id/value 由系统自动生成（tok_ / mg- 前缀）；name 为用途标注（如 Trae / Cursor）。
    """

    id: str = Field(min_length=1)
    name: str = ""
    value: str = Field(min_length=1)
    enabled: bool = True
    quotas: Quotas = Field(default_factory=Quotas)


class ZcodeUpstreamConfig(BaseModel):
    """ZCode 上游配置（v2.0 §16.5 / §17）。

    ⚠️ 为什么单独建这个模型：验收发现 `mgw zcode claim` 的失败提示让用户配
    `gateway.zcode.proxy`，但**该键此前不存在**（Pydantic 默认静默忽略未知键）
    → 用户照做会被**静默丢弃**。此处补齐，使提示与配置一致。
    """

    #: 住宅代理地址（验证码求解必需；数据中心 IP 会被风控 F001 拒绝）
    #: 留空则回退环境变量 `MGW_ZCODE_PROXY`；仍为空 → 领取能力降级（明确报错，不静默）
    proxy: str = ""
    #: Plan 通道基址（Q27-② 双通道之一；默认官方端点）
    plan_base_url: str = "https://zcode.z.ai/api/v1/zcode-plan"
    #: 领取/签到调度间隔（秒）；0 = 关闭自动调度
    claim_interval_seconds: int = Field(default=60, ge=0)
    #: 5 段 cron 表达式（分 时 日 月 周）；**非空则优先于 interval**（§16.4）
    claim_cron: str = ""
    #: 是否对 `zcode.z.ai` 启用 **TLS 指纹伪装**（§17 / P1-8）。
    #: 前置 ESA WAF 会按 ClientHello 识别机器程序；curl_cffi 不可用时自动降级并告警（§19 T5a/T5b）
    fingerprint: bool = False
    #: 🔴 额度**自动**联网腿总开关（方案 §6 第 8 格 / §12 U-8）。**默认 `false`** 是有意的：
    #: 打开它 = 授权网关在用户不在场时、按 cron 节奏对 15 个上游身份持续发起只读出站
    #: （实测推算 ≈192 次/小时 ≈ 4,600 次/天，单身份 ≈1 次/5 分钟）。
    #: 客体是**用户的账号资产**，所以授权方向只能是"用户点头后才打开"，而不是"默认开着等否决"。
    #:
    #: - `false`：cron 腿**不发起**、不改写 `runtime.json`（界面沿用上一轮数值）；
    #:   **手动腿不受影响**（`via="user"` 照常联网）⇒ 「账号级/产品级刷新额度」始终可用。
    #: - `true`：cron 每轮对全部 zcode 号联网查额度；出现任一次风控 ⇒ 按 §10-6 回落本值并记台账。
    #:
    #: 判据：`tests/unit/test_zcode_billing.py` 的第 8 格两条对照（cron 不发起 / 手动的确发起）
    #: ＋ `test_quota_net_defaults_to_off_in_the_schema`（默认值本身）。
    quota_net: bool = False

    def effective_proxy(self) -> str:
        """生效的代理地址：配置项优先，其次环境变量。"""
        import os
        return (self.proxy or "").strip() or (os.environ.get("MGW_ZCODE_PROXY") or "").strip()


class GatewayConfig(BaseModel):
    # 🔴 默认只回环（S-5 收口，2026-10-05 用户批准）：`/admin/` 免鉴权 + `get_config`
    #    默认出 `access_tokens[].value` 明文，都是按「自用本地系统」裁定的（api/auth.py）；
    #    旧默认 `0.0.0.0` 让这个前提对同网段设备不成立 ⇒ 任一设备可读走全部接入密钥并
    #    消费真实账号额度。要局域网访问必须在配置里显式写 `host: 0.0.0.0`。
    host: str = "127.0.0.1"
    port: int = Field(default=8300, ge=1, le=65535)
    # 以下运行参数见 tech-design §4.7 参数表（终审确认点 4 的默认值）
    max_concurrent_requests: int = Field(default=0, ge=0)  # 0 = 不限（FR-4.2）
    attempt_timeout_seconds: int = Field(default=60, ge=1)  # 单次尝试超时（终审 120→60）
    request_total_budget_seconds: int = Field(default=300, ge=1)  # 请求总预算（终审 600→300，§5.5）
    heartbeat_seconds: int = Field(default=15, ge=1)  # SSE 心跳注释帧间隔
    retention_days: int = Field(default=7, ge=1)  # 事件流水保留天数
    access_tokens: list[AccessToken] = Field(default_factory=list)
    # ZCode 上游配置（v2.0 §16.5）：`gateway.zcode.proxy` 等
    zcode: ZcodeUpstreamConfig = Field(default_factory=ZcodeUpstreamConfig)

    @model_validator(mode="after")
    def _budget_ge_attempt_timeout(self) -> "GatewayConfig":
        if self.request_total_budget_seconds < self.attempt_timeout_seconds:
            raise ValueError(
                "request_total_budget_seconds("
                f"{self.request_total_budget_seconds}) 必须 >= attempt_timeout_seconds"
                f"({self.attempt_timeout_seconds})（tech-design §4.7 ③）"
            )
        return self


class SchedulingConfig(BaseModel):
    """调度参数：x/y/m 全局唯一（Q18-③：不随模型分化，一套机制管控所有模型）。

    语义见 tech-design §5（Q13/Q14 定论）。
    """

    max_active_per_model: int = Field(default=2, ge=1)  # x：并发溢出生效集
    fail_threshold: int = Field(default=2, ge=1)  # y：连续失败阈值（先判定）
    retry_per_request: int = Field(default=3, ge=0)  # m：单请求单资源重试上限
    retry_backoff_seconds: float = Field(default=0.0, ge=0)  # RETRYABLE 重试间隔（0=立即）
    quota_retry: int = Field(default=2, ge=0)  # QUOTA(429) 短指数退避重试次数
    quota_backoff_base_seconds: float = Field(default=1.0, ge=0)  # 第 n 次 = base×2^(n-1)
    cooldown_seconds: int = Field(default=60, ge=0)  # api 模式默认冷却
    cooldown_seconds_plan: int = Field(default=18000, ge=0)  # plan 模式（对齐滚动 5h 窗口）


class ErrorRule(BaseModel):
    """error_rules：对特定 (http, type) 覆写默认分类（§4.3；终审确认点 5）。

    type 为空表示该状态码全部错误体；type 精确匹配优先于 HTTP 通用映射。
    典型用例：商汤 failed_precondition_error 覆写为 RETRYABLE。
    """

    http: int = Field(ge=400, le=599)
    type: str = ""
    error_class: ErrorClass = Field(alias="class")

    model_config = {"populate_by_name": True}


class ReasoningDefault(BaseModel):
    """资源级推理默认（Q15 / FR-3.16）：请求级指定 > 资源级默认 > 不注入（该供应商通道默认）。

    enabled/effort 均可选；effort 为 opaque 字符串透传（如 low/high/max），不做枚举强校验。
    仅 chat 类资源有效（images 类配置会被忽略并警告，tech-design §4.7 ⑥）。
    """

    enabled: bool | None = None
    effort: str | None = Field(default=None, min_length=1)


class Resource(BaseModel):
    """资源 = 供应商 + 账号 + Key（调度与计费最小单元，Q18-② / Q20-③）。

    - id：系统自动生成（res_ 前缀），用户无需关心；
    - vendor：供应商名称（自定义，Q20-①）；🔴 与内置目录 `EnumEntry.vendor`（承载**厂商**=生产公司）
      同名不同义，判身份看它在哪一层（定义见 PRD §2）；
    - preset：供应商预设标识（sensenova-api / sensenova-tokenplan…；统计「按供应商」口径）；
    - account：账号（资源身份组成，Q20-③ 界面必填；同一供应商可挂多组「账号 + Key」组合）；
    - name：备注（显示用，可空）；
    - enabled：资源开关，false 时退出全部调度。

    产品资源（§22.5-2，M6-5）：
    - `product` 非空 = 由该产品的账号体系供给（凭据在本地账号目录，**不进本文件**）；
    - `account_ref` = 该产品账号名（`product` 非空时必填）；
    - 此时 `api_key` 允许为空串（凭据由出站适配器从账号目录自解，铁律 1）。
    """

    id: str = Field(min_length=1)
    name: str = ""
    vendor: str = ""  # 供应商名称（自定义，可空；为空时降级 preset 展示名，Q20-①）
    preset: str = ""  # 供应商预设标识（sensenova-api / sensenova-tokenplan…；统计「按供应商」口径）
    access_mode: AccessMode = "api"
    protocol: Protocol = "openai"
    base_url: str = ""
    #: 按量 API 的 Key；**产品资源为空串**（见下方 `_key_or_account` 校验，§22.5-2）
    api_key: str = ""
    account: str = ""
    #: 产品归属标识（v2.0 §14.2 阶段一 / 调研 09 D7）。
    #: 🔴 默认空 = 旧行为（纯按量 API 资源），**旧配置零改动即可加载**；
    #:    非空时该资源由该产品的账号体系供给，运营类操作按 `supported_products` 匹配参与方
    #:    （§16.4「per-operation 声明支持的产品，不按产品整体开关」）。
    #:    Q27-⑤ 已否决"统一四表"，本列是账号存储落地的**唯一**保留项。
    product: str = ""
    #: 产品账号名（§22.5-2）：`product` 非空时必填；出站适配器据此自解凭据（§22.3）
    account_ref: str = ""
    enabled: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def _key_or_account(self) -> "Resource":
        """`api_key` 与 `product`/`account_ref` 的**互斥契约**（tech-design §22.5-2）。

        - `product` 为空 = 旧式按量 API 资源 → `api_key` **仍必须非空**
          （`api_key` 字段本身已放宽为可空串，只为容纳产品资源；旧配置零改动即可加载）；
        - `product` 非空 = 产品账号供给的资源 → `account_ref`（账号名）必填，
          凭据不落配置（由适配器从账号目录自解，铁律 1）。
        """
        prod = (self.product or "").strip()
        if not prod:
            if not self.api_key:
                raise ValueError(
                    "api_key 不能为空（product 为空 = 按量 API 资源，必须配 Key；"
                    "产品账号资源请填写 product 与 account_ref，§22.5-2）")
        elif not (self.account_ref or "").strip():
            raise ValueError(
                f"product='{prod}' 时 account_ref（产品账号名）必填"
                "（出站适配器按它从账号目录自解凭据，§22.5-2）")
        return self


class ModelResource(BaseModel):
    """网关模型资源引用：resource（资源 id）+ 供应商模型名 + 资源级推理默认 + **映射级开关**。

    🔴 `enabled` 是**这条映射**参不参与调度，与 `Resource.enabled`（那颗资源开关）是两把位：
      - 映射关 ⇒ 该 `(resource, model)` **不进资源池**（`ResourceManager.rebuild` 跳过）、
        **不对外声明**（`servable_models` 跳过 ⇒ 不出现在 `/v1/models`、不被 `mgw setup` 下发），
        但条目**留在配置里**并保留运行态（冷却/判死历史），再打开即恢复；
      - 资源关 ⇒ 该资源的全部映射都不参与（既有语义，不变）。
    界面入口：「接入账号资源」页的「模型映射」弹窗逐行开关（产品 × 模型维度）。
    strict 同 `SystemModel.enabled`（UT-25 ①：非 bool 值拒绝而不是被宽松转换）。
    """

    resource: str = Field(min_length=1)
    model: str = Field(min_length=1)  # 供应商模型名
    reasoning: ReasoningDefault | None = None
    enabled: bool = Field(default=True, strict=True)


class ProductModelMapping(BaseModel):
    """**产品维度**的模型映射位（Q33-①）：某产品的某供应商模型名 → 哪个网关模型，以及是否进池。

    🔴 为什么需要它（而不是继续用 `ModelResource.enabled` 当产品开关）：
    账号资源是「一个产品 × N 个账号」，产品维度的开关若靠往每个账号的映射条目上刷一遍
    来表达，就必然出现两件事：① 停用的账号被扇出集排除，产品开关对它的映射**既关不掉也打不开**
    （写面只遍历已启用账号）；② 聚合只能写成「组内至少一条开着就算开着」，
    于是「产品关 + 个别号手动开着」这种状态不可表达。本字段是**唯一真相**，
    `ModelResource` 上的条目只负责「这个账号有没有这条映射」的**存在性**。

    两级开关的判定式（Q33-①②，`core/resources.py` 落地）::

        可调用 = 网关模型开
               ∧ 产品位开（本字段）
               ∧ 号开（`Resource.enabled`，由账号页那颗开关同步驱动）

    🔴 第四条件「该号目录确实有此模型」**已接**（债务 Q33-债6-②）：判据在
    `accounts/catalog_cache.account_lacks()` —— 只认**这个号自己的**、
    **未过期**的目录缓存（`_catalog_cache.<号>-<短哈希>.json`，只在"取的就是这个号的凭据"那两条腿上落盘）。
    为什么必须按号：产品级那份只说得出"这个产品有这些模型"，而权益是按号算的（同产品不同号
    套餐可以不同），拿产品级去筛号会**误杀**权益窄的号、放进权益宽的号 —— 两种都是假判据。
    三种"没有证据"一律**不拦**（没取过 / 超 TTL / 读不动）：不知道就照建条目，由调用期上游答复
    告诉我们，与 §12「消灭无报错的失败」同一条立意 —— 静默否决比一次可见的 404 更坏。
    拦下时逐号如实报进写面回执的 `skipped`（绝不静默跳过）。

    旧配置零迁移：本列表为空 ⇒ 产品资源回落到条目 `ModelResource.enabled`（既有语义不变）。
    strict 同其余开关（非 bool 拒绝，不被宽松转换）。
    """

    product: str = Field(min_length=1)        # 产品 id（`accounts/registry.py` 在册）
    model: str = Field(min_length=1)          # 供应商模型名（该产品目录里的 id）
    system_model: str = Field(min_length=1)   # 网关模型 name
    enabled: bool = Field(default=True, strict=True)


# 已知参数键的取值范围（Q24）：模块级常量（类内带注解会被 Pydantic 当私有属性）。
# 未知键不校验直接放行——开放扩展，错误由供应商 400 兜底。
PARAM_RANGES: dict[str, tuple[float, float]] = {
    "temperature": (0.0, 2.0),
    "top_p": (0.0, 1.0),
    "frequency_penalty": (-2.0, 2.0),
    "presence_penalty": (-2.0, 2.0),
}


class SystemModel(BaseModel):
    """网关模型：网关对外统一模型名 + 资源池（有序 = 优先级）。

    调度参数（x/y/m/超时/冷却）全局唯一（Q18-③），不在模型级覆盖。
    params（Q24）：网关级参数默认（temperature/top_p/max_tokens 等，仅 chat 端点
    出站注入）——优先级 = 工具调用传参 > 此处 > 供应商通道默认（ir.apply_model_params）。
    开放 dict 为将来扩展自定义键预留（用户 2026-09-05 定论：暂不支持自定义、架构可扩展）；
    已知键做取值范围校验，未知键放行。
    """

    name: str = Field(min_length=1)
    group: str = ""
    endpoint: Endpoint = "chat"
    # 启用开关（FR-2.3 / Q17 / D1）：false 时 /v1/models 不返回、请求 404 model_disabled。
    # strict 保证非 bool 值（如 "yes"/0/1）拒绝而非被 Pydantic 宽松模式强制转换（UT-25 ①）。
    enabled: bool = Field(default=True, strict=True)
    params: dict[str, Any] = Field(default_factory=dict)
    resources: list[ModelResource] = Field(default_factory=list)
    # 能力覆盖（v2.0 §12.3 / §14.1，PRD Q25-①）：**默认空**，仅在"内置目录不准 / 探测失败"时使用。
    # 形状：{"thinkingLevelMap": {"max": "ultra", "minimal": None}, "thinkingFormat": "openai"}
    # ⚠️ 与 params 职责正交：params 是**采样参数**（注入出站请求体）；本字段是**能力声明**（只影响 /v1/models 输出）。
    # ⚠️ 首期**不做界面**（§20 #12 / Q25-⑩）：YAML 手改，由既有 mtime 热重载生效。
    caps_overrides: dict[str, Any] = Field(default_factory=dict)

    @field_validator("params")
    @classmethod
    def _validate_params(cls, v: dict[str, Any]) -> dict[str, Any]:
        """已知键取值范围校验（Q24）；未知键放行（开放扩展，错误由供应商 400 兜底）。"""
        for k, val in v.items():
            if k in PARAM_RANGES:
                lo, hi = PARAM_RANGES[k]
                try:
                    num = float(val)
                except (TypeError, ValueError):
                    raise ValueError(f"params.{k} 需为数值，得到 {val!r}") from None
                if not lo <= num <= hi:
                    raise ValueError(f"params.{k}={val} 超出取值范围 [{lo}, {hi}]")
            elif k == "max_tokens":
                try:
                    ok = int(val) >= 1
                except (TypeError, ValueError):
                    ok = False
                if not ok:
                    raise ValueError(f"params.max_tokens 需为 ≥1 的整数，得到 {val!r}")
            elif k == "stop" and not isinstance(val, (str, list)):
                raise ValueError("params.stop 需为字符串或字符串数组")
        return v


class Pricing(BaseModel):
    """成本估算（双口径，P1 预留）：api 模式 token 单价/图像按张；plan 模式积分系数。"""

    provider: str = Field(min_length=1)  # 供应商标识（预设 id 或资源备注）
    model: str = Field(min_length=1)
    currency: str = ""
    input_per_1m: float | None = Field(default=None, ge=0)
    output_per_1m: float | None = Field(default=None, ge=0)
    per_image: float | None = Field(default=None, ge=0)
    credits_per_1k_tokens: float | None = Field(default=None, ge=0)


class AppConfig(BaseModel):
    """根配置：config.yaml 全量模型。"""

    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    scheduling: SchedulingConfig = Field(default_factory=SchedulingConfig)
    error_rules: list[ErrorRule] = Field(default_factory=list)
    resources: list[Resource] = Field(default_factory=list)
    models: list[SystemModel] = Field(default_factory=list)
    #: 🔴 产品维度的模型映射位（Q33-①）：账号侧「产品 × 供应商模型名」的唯一真相。
    #: 空 = 旧配置 ⇒ 产品资源回落到条目 `ModelResource.enabled`（零迁移）。
    product_models: list[ProductModelMapping] = Field(default_factory=list)
    pricing: list[Pricing] = Field(default_factory=list)

    # 软校验警告（不阻塞加载；排除序列化，不写回文件）
    warnings: list[str] = Field(default_factory=list, exclude=True)

    @model_validator(mode="after")
    def _cross_references(self) -> "AppConfig":
        """跨节校验（tech-design §4.7）：唯一性 + 引用完整性 + images 推理忽略。"""
        w = self.warnings

        # —— 唯一性 ——
        resource_ids: dict[str, int] = {}
        for i, r in enumerate(self.resources):
            if r.id in resource_ids:
                raise ValueError(
                    f"resources[{i}].id 重复：'{r.id}'（首次出现在 resources[{resource_ids[r.id]}]）"
                )
            resource_ids[r.id] = i

        token_ids = [t.id for t in self.gateway.access_tokens]
        for dup in sorted({x for x in token_ids if token_ids.count(x) > 1}):
            raise ValueError(f"gateway.access_tokens[].id 重复：'{dup}'")

        model_names = [m.name for m in self.models]
        for dup in sorted({x for x in model_names if model_names.count(x) > 1}):
            raise ValueError(f"models[].name 重复：'{dup}'")

        # —— 产品维度映射位（Q33-①）：唯一性 + 目标可追溯 ——
        # 一个 (产品, 供应商模型名) 只允许有一个真相位：两条位会让「产品开关」重新变成
        # 一个需要聚合的状态（聚合语义一旦不一致，就又是那个「既关不掉也打不开」的洞）。
        #
        # 🔴 坏位**只丢不炸**（Q33 评审 R2-④ 判死后的修正）：原先用 `raise` 表达"位无效"，
        #    后果是**整份配置加载失败** ⇒ 网关把所有模型一起停服，而界面上没有任何自救入口
        #    （删掉一个网关模型就能把用户推到这一步 = 灾难级可用性）。有效/无效的把关属于
        #    **写面**的职责（`POST /admin/api/accounts/mappings` 在动盘前就拒，回执 400 可执行），
        #    读面的职责是"能起就起、坏的那条丢掉并如实告警"。
        pm_seen: dict[tuple[str, str], int] = {}
        keep_bits: list[ProductModelMapping] = []
        for i, pm in enumerate(self.product_models):
            key = (pm.product, pm.model)
            if key in pm_seen:
                w.append(f"product_models[{i}] 重复：'{pm.product}/{pm.model}'"
                         f"（与 product_models[{pm_seen[key]}] 同键）—— 已忽略本条，"
                         "同一产品同一供应商模型名只能有一个映射位")
                continue
            if pm.system_model not in set(model_names):
                w.append(f"product_models[{i}]('{pm.product}/{pm.model}').system_model "
                         f"'{pm.system_model}' 不是 models[] 里在册的网关模型 —— 已忽略本条"
                         "（该模型可能已被删除；请到「接入账号资源」页的模型映射弹窗重新指定目标）")
                continue
            pm_seen[key] = i
            keep_bits.append(pm)
        self.product_models = keep_bits

        # —— 引用完整性（资源必须存在）+ 🔴 **同一网关模型内**的组合唯一 ——
        # 后果（评审 R1-§二实测）：同一条 `models[].resources[]` 里出现两次
        # `(resource, model)` ⇒ 生效集窗口被算成 `[a, a]`，承诺 x=2 实际只有 1 条能承接，
        # 池宽与统计口径一起虚增。
        # 🔴 作用域只在**本模型内**：**跨网关模型**挂同一组合是既有设计（一条上游模型起两个
        #    网关名，运行态按 `(rid, vendor_model)` 共享冷却 —— 判据
        #    `tests/unit/test_scheduler.py::TestGlobalResourceState::
        #    test_cooldown_shared_across_system_models` 钉着）；在跨节校验里把它丢掉，
        #    等于把"别名"这条路堵死，用户看到的是"无可用资源"。
        # 处置与产品位同一条纪律：**留首条、丢重复、如实告警**（不抛 —— 抛 = 整份配置加载失败，
        # 一条坏映射不该把全网关停服）。
        for mi, m in enumerate(self.models):
            combo_seen: dict[tuple[str, str], int] = {}
            keep_refs: list[ModelResource] = []
            for ri, r in enumerate(m.resources):
                loc = f"models[{mi}]('{m.name}').resources[{ri}]"
                if r.resource not in resource_ids:
                    raise ValueError(f"{loc}: 引用不存在的 resource '{r.resource}'")
                key = (r.resource, r.model)
                if key in combo_seen:
                    w.append(f"{loc}: 同一网关模型 '{m.name}' 里 (resource '{r.resource}', "
                             f"model '{r.model}') 出现两次（首条在 resources[{combo_seen[key]}]）"
                             " —— 已忽略本条：重复条目会让生效集把同一条算两遍，"
                             "承诺的 x 条并行实际能承接的更少")
                    continue
                combo_seen[key] = ri
                keep_refs.append(r)
                # images 资源配推理默认 → 警告并忽略（§4.7 ⑥，Q15）
                if m.endpoint == "images" and r.reasoning is not None:
                    w.append(
                        f"{loc}: images 端点资源配置了 reasoning 默认，已忽略"
                        "（Q15：推理参数仅 chat 类资源有效）"
                    )
                    r.reasoning = None
            m.resources = keep_refs

        return self

    # —— 映射开关的唯一取数入口（Q33-①）——

    def product_mapping(self, product: str, model: str) -> "ProductModelMapping | None":
        """按 `(产品, 供应商模型名)` 取产品位；无该产品位返回 `None`（= 旧配置回落路径）。"""
        if not product:
            return None
        for pm in self.product_models:
            if pm.product == product and pm.model == model:
                return pm
        return None

    def mapping_enabled(self, resource: "Resource", entry: "ModelResource",
                        system_model: str) -> bool:
        """这条「资源 × 供应商模型名 → 网关模型」映射**是否参与调度与对外声明**（唯一判据）。

        - **按 Key 接入的供应商资源**（`product` 空）⇒ 条目位 `entry.enabled` 说了算（既有语义，零变化）；
        - **账号侧资源** ⇒ 产品位说了算，四种情形：
          · 有位、开关开、目标就是本网关模型 → 进；
          · 有位、开关关 → 不进（该产品**全部账号**一起退出，含已停用的号——
            这正是产品位独立存一份的理由：号开关是另一条正交轴，不能拿来当映射存在性的前置，
            否则「产品开关对停用号的映射既关不掉也打不开」那个洞必然复发）；
          · 有位、但目标指向别的网关模型 → 不进（手改 YAML 造成的不一致，
            由 `rebuild` 侧出告警，不静默放行到错误的池里）；
          · **无位**（旧配置零迁移）→ 回落到条目位 `entry.enabled`。
        """
        if not resource.product:
            return entry.enabled
        pm = self.product_mapping(resource.product, entry.model)
        if pm is None:
            return entry.enabled
        return pm.enabled and pm.system_model == system_model
