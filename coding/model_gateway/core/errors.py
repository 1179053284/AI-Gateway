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
# 🔴 只遮凭据形态：其余厂商原文（message/type/code/自定义字段）一个字不改
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
    - error_body: 响应体文本（**厂商原文，仅凭据被脱敏**，供透传）
    - error_type: 从错误体 JSON 解析出的 type（如 not_found_error）
    - no_failover: True → 换资源无帮助（如 URL 下载失败），仅同资源重试（INT-31）

    🔴 F3（M6 面板修复轮-2）：`message` / `error_body` 在**本构造函数**里过统一脱敏
    （`scrub_upstream_text`）—— 这是上游文本进入系统的唯一入口，事件 JSONL、
    响应体、日志三条出口全部读它，脱敏一次即全覆盖；除凭据形态外厂商原文一字不改。
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_body: str | None = None,
        error_type: str | None = None,
        no_failover: bool = False,
    ):
        super().__init__(scrub_upstream_text(message) if isinstance(message, str) else message)
        self.status_code = status_code
        self.error_body = scrub_upstream_text(error_body)
        self.error_type = error_type
        self.no_failover = no_failover

    @property
    def retryable_hint(self) -> bool:
        return self.status_code is None or self.status_code >= 500


def extract_error_type(error_body: str | None) -> str | None:
    """从厂商错误体提取 type 字段（OpenAI 兼容形态 {"error":{"type":...}}）。"""
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
        # 1) 网络类异常（无状态码）：超时/连接失败/流中断 → RETRYABLE
        if err.status_code is None:
            return ErrorClass.RETRYABLE

        status = err.status_code
        etype = err.error_type or extract_error_type(err.error_body)

        # 2) error_rules 覆写（type 精确匹配优先于仅 HTTP 匹配）
        if etype and (status, etype) in self._typed:
            return self._typed[(status, etype)]
        if status in self._by_http:
            return self._by_http[status]

        # 3) 商汤/厂商错误 type 表
        if etype and etype in VENDOR_TYPE_TABLE:
            return VENDOR_TYPE_TABLE[etype]

        # 4) HTTP 通用映射（UT-02）
        if status == 401:
            return ErrorClass.AUTH
        if status == 404:
            return ErrorClass.NOT_FOUND
        if status == 429:
            return ErrorClass.QUOTA
        if status == 408:
            return ErrorClass.CANCELED
        if status >= 500:
            return ErrorClass.RETRYABLE
        return ErrorClass.BAD_REQUEST
