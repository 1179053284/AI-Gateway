"""错误分类器（tech-design §4.3 / PRD FR-3.13 的代码化）。

- ErrorClass 六类：RETRYABLE / BAD_REQUEST / AUTH / NOT_FOUND / QUOTA / CANCELED
- 商汤错误 type 表（PRD FR-1.8 官方口径，实测错误体 {"error":{message,type,code}} 验证）
- error_rules 配置覆写：type 精确匹配规则 > HTTP 通用规则 > 默认表（UT-19）
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

import httpx


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
    - error_body: 原始响应体文本（不修饰，供透传）
    - error_type: 从错误体 JSON 解析出的 type（如 not_found_error）
    - no_failover: True → 换资源无帮助（如 URL 下载失败），仅同资源重试（INT-31）
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
        super().__init__(message)
        self.status_code = status_code
        self.error_body = error_body
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


def wrap_httpx_error(e: Exception) -> UpstreamError:
    """httpx 异常 → UpstreamError（网络类）。CancelledError 绝不在此捕获（铁纪律）。"""
    return UpstreamError(f"{type(e).__name__}: {e}")
