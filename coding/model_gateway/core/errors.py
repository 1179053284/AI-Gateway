"""错误分类器（tech-design §4.3 / PRD FR-3.13 的代码化）。

- ErrorClass 六类：RETRYABLE / BAD_REQUEST / AUTH / NOT_FOUND / QUOTA / CANCELED
- 商汤错误 type 表（PRD FR-1.8 官方口径，实测错误体 {"error":{message,type,code}} 验证）
- error_rules 配置覆写：type 精确匹配规则 > HTTP 通用规则 > 默认表（UT-19）
"""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Any, Iterable

import httpx


# ============ 上游文本脱敏（M6 面板修复轮-2 · F3：凭据回显红线的统一出口）============
#
# 🔴 触发面：上游把**我方凭据**回显进错误体（WAF/代理错误页、调试型网关都会），
#    明文会经三条出口外泄：①事件 JSONL（`stats.events.error_summary`）、
#    ②客户端响应体（`GatewayError.to_openai_error` / 中途失败 error 帧）、
#    ③任何打印该异常/摘要的日志。
# 🔴 处理点选**上游文本进入系统的唯一入口**（`UpstreamError.__init__`）+
#    `error_summary` 出口兜底：三处出口全部读这两处产出的文本，脱敏一次即全覆盖，
#    且**只处理上游提供的文本**（客户端请求内容不经过这里，绝不改动）。
# 🔴 只遮凭据形态：其余供应商原文（message/type/code/自定义字段）一个字不改
#    —— §6「不修饰透传」的契约只在凭据这一处让步（§22.2 不变式②是绝对口径）。

#: 登记的本网关凭据字面值（**只在内存**，不落盘、不进日志；装配/凭据读取面登记）
_KNOWN_SECRETS: set[str] = set()

#: 登记门槛：过短的值（如测试里的 `sk-A` / `t-1`）不登记 —— 遮掉它们会让
#: 正常文本被误伤，而真实密钥/令牌都远长于此
_SECRET_MIN_LEN = 8

#: Bearer / Basic 认证头形态（含通用 token 字符集）
_AUTH_SCHEME_RE = re.compile(r"(?i)\b(bearer|basic)\s+([A-Za-z0-9._~+/=\-]{6,})")
#: JSON/键值形态的凭据字段（key 白名单，值必须带引号，避免误伤普通句子）
_KV_SECRET_RE = re.compile(
    r"(?i)([\"']?(?:api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|"
    r"authorization|auth[_-]?token|token|secret|password|jwt|credentials?)[\"']?"
    r"\s*[:=]\s*)([\"'])([^\"'\s,}]{6,})\2")
#: `sk-` 形态的按量 Key
_SK_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}")
#: JWT 形态（账号令牌大多是 JWT）
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}(?:\.[A-Za-z0-9_\-]{4,})?")


def _mask_secret(value: str) -> str:
    """脱敏形态（与 `stats.events.mask_key` 同形）：≤8 全遮，否则 前3+****+后4。"""
    if len(value) <= 8:
        return "****"
    return f"{value[:3]}****{value[-4:]}"


def register_secret_values(values: Iterable[str] | str | None) -> int:
    """登记**本网关自己**的凭据字面值（装配侧与凭据读取面调用）。

    为什么要字面值表：形态规则（Bearer / `sk-` / JWT）只能遮"长得像凭据"的串，
    而账号令牌可能是任意串（如 `TOKEN-ACCOUNT-A-9f3c7b21`）—— 上游裸回显它时
    只有精确匹配能遮住。返回新增条数（便于测试断言登记生效）。
    """
    if isinstance(values, str):
        values = (values,)
    added = 0
    for value in values or ():
        if not isinstance(value, str):
            continue
        text = value.strip()
        if len(text) >= _SECRET_MIN_LEN and text not in _KNOWN_SECRETS:
            _KNOWN_SECRETS.add(text)
            added += 1
    return added


def scrub_upstream_text(text: str | None) -> str | None:
    """把**上游提供的文本**里的凭据遮掉（F3 唯一口径；None/空串原样返回）。

    顺序有意：先形态规则（Bearer / KV / `sk-` / JWT）、后字面值表 ——
    否则字面值先被遮成 `***` 后仍可能命中 `sk-` 规则被二次遮，形态反而更难读。
    幂等：遮完的文本再跑一遍不再变化（`***` 里没有可再遮的形态）。
    """
    if not text:
        return text
    out = _AUTH_SCHEME_RE.sub(lambda m: f"{m.group(1)} {_mask_secret(m.group(2))}", text)
    out = _KV_SECRET_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{_mask_secret(m.group(3))}{m.group(2)}", out)
    out = _SK_RE.sub(lambda m: _mask_secret(m.group(0)), out)
    out = _JWT_RE.sub(lambda m: _mask_secret(m.group(0)), out)
    for secret in sorted(_KNOWN_SECRETS, key=len, reverse=True):
        if secret in out:
            out = out.replace(secret, _mask_secret(secret))
    return out


class ErrorClass(str, Enum):
    RETRYABLE = "RETRYABLE"
    BAD_REQUEST = "BAD_REQUEST"
    AUTH = "AUTH"
    NOT_FOUND = "NOT_FOUND"
    QUOTA = "QUOTA"
    CANCELED = "CANCELED"
    #: **资源级不可承接**：上游明确否认**这条资源**对本模型有资格（未订阅 / 地域封锁），
    #: 但请求本身没错 —— 换一条资源就能成。与 `BAD_REQUEST` 的分界是本质的：
    #: `BAD_REQUEST` = 请求属性有问题（换谁都不行，如商汤 403「不支持当前语言」），
    #: 故原样透传、不换号；本类 = 资源属性有问题，故**换号续跑**。
    RESOURCE_UNAVAILABLE = "RESOURCE_UNAVAILABLE"


#: 通道级风控的**归一化错误 type**（各上游自己那套信封里的码，由出站层翻译成这一个）。
#: 🔴 它落 RETRYABLE 而不是 BAD_REQUEST：3012 这类风控是**账号级状态**（与 429 同类），
#: 不是"客户端请求写错了"。按 FR-3.13 原样透传的后果 = 不换号、不计 C、不冷却 ⇒
#: 一条坏号永远占着活跃组名额、每轮轮转再把失败交给用户一次
#: （2026-10-05 用户裁定：「没额度和多次请求失败，就应该排除到可用调用范围」）。
RISK_CONTROL_TYPE = "zcode_risk_control"

#: **资源级不可承接**的归一化错误 type（产品层翻译后交本分类器；2026-10-08）。
#:
#: 为什么需要它（缺陷取证，2026-10-07 实盘）：`glm-5.3-flash` 池里挂了一条 cline 资源
#: （`cline-pass/glm-5.3-flash`），该账号**有余额但没订阅该模型计划**，上游恒回
#: `403 {"error":{"code":"ENTITLEMENT_ERROR","message":"… not subscribed to required model plan"}}`。
#: 而 403 在 `classify()` 里落到 `BAD_REQUEST` 兜底 ⇒ **不换号**、请求直接失败，
#: 池里 8 条健康资源（zcode/loomy）全程闲置 —— 实测 cline 尝试 **5/5 全失败**、
#: 6 次采样 **2 次**把 403 交给客户端。这与 qoder 已修复的
#: 「402 落 BAD_REQUEST ⇒ 不冷却也不换号」（`upstream/qoder/out.py:180-182`）**是同一类缺陷**。
#:
#: 判据来源（逐字取证，不扩写）：DSH `isClineRegionForbidden`（`cline-adapter.ts:969-978`
#: 的四个特征词）＋ `cline-rate-limit.ts:240-241` 的 `ENTITLEMENT_ERROR` 实录
#: （同一账号 `/users/me/plan/usage-limits` 回 `404 no plan history found for user`
#: ⇒ 确属**订阅状态**，不是凭据、也不是限流）。
RESOURCE_UNAVAILABLE_TYPE = "resource_unavailable"

# 商汤官方错误 type → 默认分类（PRD FR-1.8；UT-01 断言口径）
VENDOR_TYPE_TABLE: dict[str, ErrorClass] = {
    "invalid_request_error": ErrorClass.BAD_REQUEST,
    "failed_precondition_error": ErrorClass.BAD_REQUEST,  # 终审确认点 5：默认透传，可配覆写
    "permission_denied_error": ErrorClass.BAD_REQUEST,   # 语言类透传（UT-01）
    "not_found_error": ErrorClass.NOT_FOUND,
    "canceled_error": ErrorClass.CANCELED,
    "quota_exceeded_error": ErrorClass.QUOTA,
    "internal_server_error": ErrorClass.RETRYABLE,
}


class UpstreamError(Exception):
    """上游调用失败（网络异常 / HTTP 错误响应 / 下载失败等）。

    - status_code=None → 网络类异常（连接失败/超时/中断）
    - error_body: 响应体文本（**供应商原文，仅凭据被脱敏**，供透传）
    - error_type: 从错误体 JSON 解析出的 type（如 not_found_error）
    - no_failover: True → 换资源无帮助（如 URL 下载失败），仅同资源重试（INT-31）

    🔴 F3（M6 面板修复轮-2）：`message` / `error_body` 在**本构造函数**里过统一脱敏
    （`scrub_upstream_text`）—— 这是上游文本进入系统的唯一入口，事件 JSONL、
    响应体、日志三条出口全部读它，脱敏一次即全覆盖；除凭据形态外供应商原文一字不改。
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_body: str | None = None,
        error_type: str | None = None,
        no_failover: bool = False,
        risk_control: bool = False,
        error_class: "ErrorClass | None" = None,
    ):
        super().__init__(scrub_upstream_text(message) if isinstance(message, str) else message)
        self.status_code = status_code
        self.error_body = scrub_upstream_text(error_body)
        self.error_type = error_type
        self.no_failover = no_failover
        # 🔴 通道级风控标记（2026-10-07 P0-2，ZCode 3012/WAF 专用）：
        # 由出站层 `_as_risk_control()` 置位（分类仍走 RETRYABLE——2026-10-05 用户
        # 裁定「多次失败应排除出可用范围」的换号语义保留）。调度器据此走
        # **梯度对齐处置**：首试即 bench 30min（上游 3012 惩罚第一档，DSH
        # `zcode-identity.ts:42`）+ 不在同资源重试（同资源再打 = 帮它多记一次
        # 3012，梯度 3 次/24h→24h、5 次→停用）。普通 429/超时**不带**此标记。
        self.risk_control = risk_control
        # 🔴 **出站层已定类别**（2026-10-08；自有信封业务码翻译的产物）：
        # 产品层按**取证过的官方归因表**把业务码翻成类别（如 ZCode `1005` 额度耗尽
        # ⇒ QUOTA —— 它走 `200 + 信封`，HTTP 状态本身无信息量）。
        # `ErrorClassifier.classify()` 第 1.5 步采信它（用户的 `error_rules` 覆写仍更优先）；
        # `None` = 出站层没判断，交回既有 HTTP/type 逻辑。
        self.error_class = error_class

    @property
    def retryable_hint(self) -> bool:
        return self.status_code is None or self.status_code >= 500


def extract_error_type(error_body: str | None) -> str | None:
    """从供应商错误体提取 type 字段（OpenAI 兼容形态 {"error":{"type":...}}）。"""
    if not error_body:
        return None
    try:
        data = json.loads(error_body)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict) and isinstance(err.get("type"), str):
            return err["type"]
        if isinstance(data.get("type"), str):
            return data["type"]
    return None


class ErrorClassifier:
    """分类优先级（UT-19）：error_rules(type 精确) > error_rules(仅 HTTP) > 商汤 type 表 > HTTP 通用映射。"""

    def __init__(self, rules: list | None = None):
        # rules: model_gateway.config.schemas.ErrorRule 列表（或测试注入的同形对象）
        self._typed: dict[tuple[int, str], ErrorClass] = {}
        self._by_http: dict[int, ErrorClass] = {}
        for r in rules or []:
            cls = ErrorClass(r.error_class) if not isinstance(r.error_class, ErrorClass) else r.error_class
            if r.type:
                self._typed[(r.http, r.type)] = cls
            else:
                self._by_http[r.http] = cls

    def classify(self, err: UpstreamError) -> ErrorClass:
        status = err.status_code
        etype = err.error_type or extract_error_type(err.error_body)
        # 🔴 规则的匹配键：`status_code=None`（自有信封 / 网络类）用哨兵 `0` 表示
        #    —— 否则「用户配置覆写一切默认判断」这条红线对信封类错误**结构性失效**
        #    （2026-10-08 自测抓到：`1005` 的规则覆写被跳过，配置形同不存在）。
        rule_status = 0 if status is None else status

        # 1) error_rules 覆写（type 精确匹配优先于仅 HTTP 匹配）—— **永远最高**
        #    （铁律 4：用户的显式配置是唯一可覆写面；出站层的判断也不得越过它）。
        if etype and (rule_status, etype) in self._typed:
            return self._typed[(rule_status, etype)]
        if rule_status in self._by_http:
            return self._by_http[rule_status]

        # 2) 出站层已定类别（2026-10-08；自有信封业务码翻译的产物）。
        #    为什么排在网络兜底**之前**：出站层知道的事实比"无状态码 = 网络问题"
        #    更具体 —— ZCode 的业务错误走 `200 + 信封`，`status_code=None` 是**形状**
        #    决定的，不是网络故障（`1005` 额度耗尽被当成网络抖动，就会用短冷却反复打
        #    一条已经没额度的号；官方 `providerBusinessError.ts` 明写它要"刷新配额"）。
        if err.error_class is not None:
            return err.error_class

        # 3) 网络类异常（无状态码）：超时/连接失败/流中断 → RETRYABLE
        if status is None:
            return ErrorClass.RETRYABLE

        # 4) 商汤/供应商错误 type 表
        if etype and etype in VENDOR_TYPE_TABLE:
            return VENDOR_TYPE_TABLE[etype]

        # 4b) 通道级风控（出站层归一化后的 type）⇒ 可重试：换号 + 计 C + y 次后冷却。
        #     `error_rules` 的精确覆写仍排在前面（上面第 1 步）⇒ 某产品要改判据不必动代码。
        if etype == RISK_CONTROL_TYPE:
            return ErrorClass.RETRYABLE

        # 4c) 资源级不可承接（出站层归一化后的 type）⇒ 换号续跑 + 冷却该条 (资源, 模型)。
        #     为什么不是 RETRYABLE：本类**不该在同一条资源上重试**（上游是确定性否认，
        #     重试只是多打一次）；为什么不是 BAD_REQUEST：请求本身没错，换一条资源就能成
        #     （判据与取证见 `RESOURCE_UNAVAILABLE_TYPE` 的常量注释）。
        if etype == RESOURCE_UNAVAILABLE_TYPE:
            return ErrorClass.RESOURCE_UNAVAILABLE

        # 5) HTTP 通用映射（UT-02）
        if status == 401:
            return ErrorClass.AUTH
        if status == 404:
            return ErrorClass.NOT_FOUND
        if status == 429:
            return ErrorClass.QUOTA
        # 402 Payment Required 按字面归**额度类**。为什么不算"请求写错了"：落到下面的
        # BAD_REQUEST 分支 ⇒ 不冷却、不换号，用户拿到一条像客户端错的错误。
        # 触发取证（2026-10-04，存档 `docs/changes/e2e-records/E2E-20261004-qoder-quota-probe.md`）：
        # Qoder 公开端点在额度为 0 的号上回 `402 {"code":116,"error":"quota exceeded"}`，
        # 且该响应在**空 model、缺 `messages` 的畸形体**下也一样 ⇒ 额度门跑在模型校验之前
        # （这是**单个号**上的观察，不外推成"402 只可能是额度"）。
        # 顺序保障：`error_rules` 的 (http,type) 精确覆写与本表都排在前面 ⇒
        # 某供应商若用 402 表达别的语义，可在配置里精确覆写回来，不必改代码。
        if status == 402:
            return ErrorClass.QUOTA
        if status == 408:
            return ErrorClass.CANCELED
        if status >= 500:
            return ErrorClass.RETRYABLE
        return ErrorClass.BAD_REQUEST
