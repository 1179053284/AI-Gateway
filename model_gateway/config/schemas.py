"""配置 schema：PRD §6（v1.5）+ tech-design §4.7 运行参数的 pydantic v2 落地。

- 全部字段明文 YAML；密钥仅存本地（铁律 1）。
- 数值边界（tech-design §4.7 ③）：x>=1、y>=1、m>=0、冷却>=0、退避>=0、超时>=1、总预算>=超时。
- 资源模型扁平化（Q18-②）：resources[] = 厂商 + Key（账号标识为次要备注），
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


class GatewayConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = Field(default=8300, ge=1, le=65535)
    # 以下运行参数见 tech-design §4.7 参数表（终审确认点 4 的默认值）
    max_concurrent_requests: int = Field(default=0, ge=0)  # 0 = 不限（FR-4.2）
    attempt_timeout_seconds: int = Field(default=60, ge=1)  # 单次尝试超时（终审 120→60）
    request_total_budget_seconds: int = Field(default=300, ge=1)  # 请求总预算（终审 600→300，§5.5）
    heartbeat_seconds: int = Field(default=15, ge=1)  # SSE 心跳注释帧间隔
    retention_days: int = Field(default=7, ge=1)  # 事件流水保留天数
    access_tokens: list[AccessToken] = Field(default_factory=list)

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
    """资源级推理默认（Q15 / FR-3.16）：请求级指定 > 资源级默认 > 厂商默认（不注入）。

    enabled/effort 均可选；effort 为 opaque 字符串透传（如 low/high/max），不做枚举强校验。
    仅 chat 类资源有效（images 类配置会被忽略并警告，tech-design §4.7 ⑥）。
    """

    enabled: bool | None = None
    effort: str | None = Field(default=None, min_length=1)


class Resource(BaseModel):
    """资源 = 厂商 + 账号 + Key（调度与计费最小单元，Q18-② / Q20-③）。

    - id：系统自动生成（res_ 前缀），用户无需关心；
    - vendor：厂商名称（自定义，Q20-①）；
    - preset：厂商预设标识（sensenova-api / sensenova-tokenplan…；统计「按厂商」口径）；
    - account：账号（资源身份组成，Q20-③ 界面必填；同一厂商可挂多组「账号 + Key」组合）；
    - name：备注（显示用，可空）；
    - enabled：资源开关，false 时退出全部调度。
    """

    id: str = Field(min_length=1)
    name: str = ""
    vendor: str = ""  # 厂商名称（自定义，可空；为空时降级 preset 展示名，Q20-①）
    preset: str = ""  # 厂商预设标识（sensenova-api / sensenova-tokenplan…；统计「按厂商」口径）
    access_mode: AccessMode = "api"
    protocol: Protocol = "openai"
    base_url: str = ""
    api_key: str = Field(min_length=1)
    account: str = ""
    enabled: bool = Field(default=True, strict=True)


class ModelResource(BaseModel):
    """系统模型资源引用：resource（资源 id）+ 厂商侧模型 + 资源级推理默认。"""

    resource: str = Field(min_length=1)
    model: str = Field(min_length=1)  # 厂商侧模型 ID
    reasoning: ReasoningDefault | None = None


# 已知参数键的取值范围（Q24）：模块级常量（类内带注解会被 Pydantic 当私有属性）。
# 未知键不校验直接放行——开放扩展，错误由厂商 400 兜底。
PARAM_RANGES: dict[str, tuple[float, float]] = {
    "temperature": (0.0, 2.0),
    "top_p": (0.0, 1.0),
    "frequency_penalty": (-2.0, 2.0),
    "presence_penalty": (-2.0, 2.0),
}


class SystemModel(BaseModel):
    """系统模型：网关对外统一模型名 + 资源池（有序 = 优先级）。

    调度参数（x/y/m/超时/冷却）全局唯一（Q18-③），不在模型级覆盖。
    params（Q24）：网关级参数默认（temperature/top_p/max_tokens 等，仅 chat 端点
    出站注入）——优先级 = 工具调用传参 > 此处 > 厂商内置默认（ir.apply_model_params）。
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

    @field_validator("params")
    @classmethod
    def _validate_params(cls, v: dict[str, Any]) -> dict[str, Any]:
        """已知键取值范围校验（Q24）；未知键放行（开放扩展，错误由厂商 400 兜底）。"""
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

    provider: str = Field(min_length=1)  # 厂商标识（预设 id 或资源备注）
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

        # —— 引用完整性（资源必须存在）——
        for mi, m in enumerate(self.models):
            for ri, r in enumerate(m.resources):
                loc = f"models[{mi}]('{m.name}').resources[{ri}]"
                if r.resource not in resource_ids:
                    raise ValueError(f"{loc}: 引用不存在的 resource '{r.resource}'")
                # images 资源配推理默认 → 警告并忽略（§4.7 ⑥，Q15）
                if m.endpoint == "images" and r.reasoning is not None:
                    w.append(
                        f"{loc}: images 端点资源配置了 reasoning 默认，已忽略"
                        "（Q15：推理参数仅 chat 类资源有效）"
                    )
                    r.reasoning = None

        return self
