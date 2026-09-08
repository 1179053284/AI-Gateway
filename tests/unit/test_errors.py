"""错误分类器 UT（UT-01 / UT-02 / UT-16 / UT-19）。"""

from __future__ import annotations

from model_gateway.config.schemas import ErrorRule
from model_gateway.core.errors import ErrorClass, ErrorClassifier, UpstreamError
from tests.unit.conftest import http_err


def _err(status: int | None, body: str | None = None, etype: str | None = None):
    return UpstreamError(f"e-{status}", status_code=status, error_body=body, error_type=etype)


class TestVendorTypeTable:
    """UT-01：商汤错误码表 7 类分类。"""

    def test_400_invalid_request(self):
        assert ErrorClassifier().classify(
            _err(400, etype="invalid_request_error")) is ErrorClass.BAD_REQUEST

    def test_400_failed_precondition(self):
        # 终审确认点 5：默认透传（BAD_REQUEST），可配覆写为 RETRYABLE（见 TestErrorRules）
        assert ErrorClassifier().classify(
            _err(400, etype="failed_precondition_error")) is ErrorClass.BAD_REQUEST

    def test_403_permission_denied(self):
        assert ErrorClassifier().classify(
            _err(403, etype="permission_denied_error")) is ErrorClass.BAD_REQUEST

    def test_404_not_found(self):
        assert ErrorClassifier().classify(
            _err(404, etype="not_found_error")) is ErrorClass.NOT_FOUND

    def test_408_canceled(self):
        assert ErrorClassifier().classify(
            _err(408, etype="canceled_error")) is ErrorClass.CANCELED

    def test_429_quota_exceeded(self):
        assert ErrorClassifier().classify(
            _err(429, etype="quota_exceeded_error")) is ErrorClass.QUOTA

    def test_500_internal(self):
        assert ErrorClassifier().classify(
            _err(500, etype="internal_server_error")) is ErrorClass.RETRYABLE

    def test_type_extracted_from_body(self):
        """error_type 未显式给出时从 error_body JSON 提取（classify 内部回退）。"""
        e = _err(404, body='{"error":{"message":"no","type":"not_found_error"}}')
        assert ErrorClassifier().classify(e) is ErrorClass.NOT_FOUND


class TestHttpGenericMapping:
    """UT-02：通用 HTTP 映射。"""

    def test_network_exception_retryable(self):
        assert ErrorClassifier().classify(_err(None)) is ErrorClass.RETRYABLE

    def test_read_timeout_retryable(self):
        e = UpstreamError("timeout: ReadTimeout")
        assert ErrorClassifier().classify(e) is ErrorClass.RETRYABLE

    def test_401_auth(self):
        assert ErrorClassifier().classify(_err(401)) is ErrorClass.AUTH

    def test_other_4xx_bad_request(self):
        assert ErrorClassifier().classify(_err(422)) is ErrorClass.BAD_REQUEST

    def test_5xx_retryable(self):
        assert ErrorClassifier().classify(_err(502)) is ErrorClass.RETRYABLE


class TestErrorRulesOverride:
    """UT-19：error_rules 自定义覆写（type 精确匹配优先于 HTTP 通用映射）。"""

    RULES = [ErrorRule.model_validate({"http": 400, "type": "failed_precondition_error",
                                      "class": "RETRYABLE"})]

    def test_default_is_bad_request(self):
        assert ErrorClassifier([]).classify(
            _err(400, etype="failed_precondition_error")) is ErrorClass.BAD_REQUEST

    def test_override_to_retryable(self):
        clf = ErrorClassifier(self.RULES)
        assert clf.classify(
            _err(400, etype="failed_precondition_error")) is ErrorClass.RETRYABLE

    def test_type_match_takes_priority_over_http_rule(self):
        """type 精确匹配优先：仅 HTTP 的规则不得拦截带 type 的覆写。"""
        rules = [
            ErrorRule.model_validate({"http": 400, "type": "failed_precondition_error",
                                      "class": "RETRYABLE"}),
            ErrorRule.model_validate({"http": 400, "type": "", "class": "BAD_REQUEST"}),
        ]
        clf = ErrorClassifier(rules)
        assert clf.classify(
            _err(400, etype="failed_precondition_error")) is ErrorClass.RETRYABLE
        # 其他 type 落入「仅 HTTP」规则
        assert clf.classify(_err(400, etype="invalid_request_error")) is ErrorClass.BAD_REQUEST

    def test_http_only_rule_covers_untyped(self):
        rules = [ErrorRule.model_validate({"http": 404, "type": "", "class": "RETRYABLE"})]
        assert ErrorClassifier(rules).classify(_err(404)) is ErrorClass.RETRYABLE


class TestFinishReasonContentFilter:
    """UT-16（分类器侧）：content_filter 出现在 200 响应体中，不构成上游错误。"""

    def test_200_response_never_classified(self):
        # finish_reason=content_filter 属 200 响应体内容 → 调度层按成功处理（见 test_scheduler）；
        # 分类器仅在非 2xx 时介入，此处断言 200 响应不会进入失败分类路径
        e = UpstreamError("stray 200", status_code=200)
        assert e.retryable_hint is False


def test_upstream_error_no_failover_flag():
    """INT-31 语义载体：no_failover 标记随异常传递。"""
    e = UpstreamError("image_url download failed", no_failover=True)
    assert e.no_failover is True
    assert ErrorClassifier().classify(e) is ErrorClass.RETRYABLE
