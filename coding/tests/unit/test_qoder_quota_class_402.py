"""Qoder 额度/排队态的分类判据（2026-10-04 学习轮第一刀）。

**为什么改**：Qoder 公开端点在额度为 0 的号上回 `402 {"code":116,"error":"quota exceeded"}`
（探针存档 `docs/changes/e2e-records/E2E-20261004-qoder-quota-probe.md`）。改动前 402 落
`errors.classify` 的兜底 = `BAD_REQUEST` ⇒ **不冷却、不换号**，用户看到一条像"请求写错了"的错误，
而真因是"这个号没额度了，该走下一个号"。

⚠️ 本文件**不**宣称 Qoder 转发可用：加密腿仍 `SIGNER_FACTORY is None`（一字节不发），
公开腿本波次没做（没有可取证的公开名）。这里锁的是"额度别再冒充客户端错"这一层分类。

## 判据设计纪律（验收轮 PA-2 的反省落成的形状）
`envelope.is_business_error` 是**四支并列判据**（码表 / 队列信息 / 排队码 / 文案兜底）。
上一版把它们混在一条"码+文案同时在场"的用例里 ⇒ 摘掉任何一支都照样绿（= 空判据）。
所以**每一支都有一个只有它能救活的用例**（下表 `锁` 列），撤证时逐支可红：

| 用例 | 锁住的那一支 |
|---|---|
| `test_public_quota_code_maps_to_quota` / `test_quota_code_accepts_int_or_string` | 码表（116） |
| `test_legacy_billing_code_still_quota` | 码表（110，不许被新码挤掉） |
| `test_queue_shape_without_code_is_retryable_and_keeps_wait` | `parse_queue_info` |
| `test_queue_code_yields_queued_error_not_quota` | 排队码 `10605` |
| `test_billing_text_without_code_falls_back_to_hint` | 文案兜底 |
| `test_bare_402_without_business_body_is_still_quota` | 全局 HTTP 通用档 |
| `test_http_gate_recognizes_business_code_on_402` | 出站委托（`out` 层不再自己比码表） |
| `test_401_with_quota_wording_stays_out_of_quota` / `test_403_signature_failure_is_not_quota` | 🔴 反向：不许把认证态吞成额度 |
"""

from __future__ import annotations

import pytest

from model_gateway.core.errors import ErrorClass, ErrorClassifier, UpstreamError
from model_gateway.upstream.qoder import envelope
from model_gateway.upstream.qoder.out import QoderOut

QUOTA_402 = '{"code":116,"error":"quota exceeded"}'
classify = ErrorClassifier([]).classify


# —— 码表支（116 / 110）——

def test_public_quota_code_maps_to_quota():
    err = envelope.business_error(QUOTA_402)
    assert isinstance(err, envelope.QoderBusinessError)
    assert err.status_code == 429, "额度必须归一成 429，才走既有 QUOTA 冷却 + 换号路径"
    assert err.code == "116", f"业务码要保真（排障要知道是哪一码）：{err.code!r}"
    assert "quota exceeded" in (err.error_body or ""), "上游原话要留在错误体里（客户端摘要读的是它）"
    assert classify(err) is ErrorClass.QUOTA


def test_quota_code_accepts_int_or_string():
    """真实 JSON 的 `code` 可能是**数字**也可能是**字符串**，两支都必须认。

    撤证位：把 `str(code or "")` 改成 `parsed.get("code") == "116"` 这类字面比较 ⇒ 数字形状变绿跑。
    """
    for raw in ('{"code":116,"message":"额度已用完"}', '{"code":"116","message":"额度已用完"}'):
        err = envelope.business_error(raw)
        assert err.status_code == 429, f"数字/字符串两种 code 都得归额度：{raw}"
        assert classify(err) is ErrorClass.QUOTA


def test_legacy_billing_code_still_quota():
    """新码不许把老码挤掉（`110` = 信封内层的 billing）。"""
    err = envelope.business_error('{"code":110,"message":"Billing daily count exceeded"}')
    assert err.status_code == 429 and classify(err) is ErrorClass.QUOTA


# —— 队列信息支 / 排队码支 ——

def test_queue_shape_without_code_is_retryable_and_keeps_wait():
    """排队信息**没有 code 字段**（内层帧形状）⇒ 只能由 `parse_queue_info` 那一支救活。"""
    err = envelope.business_error('{"isQueued":true,"retryAfterSeconds":30}')
    assert isinstance(err, envelope.QoderQueuedError), f"必须是排队类：{type(err).__name__}"
    assert err.retry_after_seconds == 30, "服务端建议的等待时长要留着（摘了它就退化成普通重试）"
    assert classify(err) is ErrorClass.RETRYABLE, "排队是暂时受阻，不该被当成额度冷却"


def test_queue_code_yields_queued_error_not_quota():
    """排队码 `10605`：必须是排队类（**不是**"任何非 BAD_REQUEST 都算过"那种空断言）。"""
    err = envelope.business_error('{"code":"10605","message":"queued"}')
    assert isinstance(err, envelope.QoderQueuedError)
    assert err.code == "10605"
    assert classify(err) is ErrorClass.RETRYABLE


# —— 文案兜底支 ——

def test_billing_text_without_code_falls_back_to_hint():
    """没有码、只有 billing 文案 ⇒ 只能由文案兜底那一支救活（词表刻意**不含** "quota exceeded"）。"""
    err = envelope.business_error('{"message":"Billing daily count exceeded, please retry tomorrow"}')
    assert err.status_code == 429 and classify(err) is ErrorClass.QUOTA


# —— 全局 HTTP 档 + 出站委托 ——

def test_bare_402_without_business_body_is_still_quota():
    """body 不是 Qoder 业务错误（别的厂商也可能用 402）⇒ 走全局 HTTP 通用映射。"""
    assert classify(UpstreamError("upstream 402", status_code=402,
                                  error_body="payment required")) is ErrorClass.QUOTA


def test_http_gate_recognizes_business_code_on_402():
    """🔴 出站那支必须**只凭码**认额度（曾经自己比了一遍码表，只认 110 ⇒ 116 靠文案蒙对）。"""
    with pytest.raises(UpstreamError) as got:
        QoderOut._raise_for_status(402, '{"code":116,"message":"额度已用完"}')
    err = got.value
    assert err.status_code == 429 and getattr(err, "code", "") == "116"
    assert classify(err) is ErrorClass.QUOTA


# —— 🔴 反向：认证态不许被吞成额度 ——

def test_401_with_quota_wording_stays_out_of_quota():
    """验收 PA-1 抓出的形状：文案判据扫整条响应体，`401 + 含 "quota exceeded" 的 body`
    曾从 AUTH 翻成 QUOTA。本波次把新词**只放进码表**，这条就是那个选择的锁。"""
    with pytest.raises(UpstreamError) as got:
        QoderOut._raise_for_status(401, '{"error":"quota exceeded"}')
    err = got.value
    assert err.status_code == 401, "认不出业务码时状态码必须原样交回（不许被改写成 429）"
    assert classify(err) is ErrorClass.AUTH


def test_403_signature_failure_is_not_quota():
    """签名/认证失败（`105`）不许被当成额度 ⇒ 否则该号被额度冷却，方向完全错。"""
    with pytest.raises(UpstreamError) as got:
        QoderOut._raise_for_status(403, '{"code":105,"message":"auth_error"}')
    err = got.value
    assert err.status_code == 403
    assert classify(err) is not ErrorClass.QUOTA


# —— 单一判据的自证：四支各自可红（canary） ——

@pytest.mark.parametrize("body,is_business,expect_class", [
    ('{"code":116}', True, ErrorClass.QUOTA),                       # 码表（新）
    ('{"code":110}', True, ErrorClass.QUOTA),                       # 码表（老）
    ('{"isQueued":true,"retryAfterSeconds":9}', True, ErrorClass.RETRYABLE),  # 队列信息
    ('{"message":"daily count exceeded"}', True, ErrorClass.QUOTA),           # 文案兜底
    ('{"code":10605}', True, ErrorClass.RETRYABLE),                 # 排队码
    ('{"code":105,"message":"auth_error"}', False, ErrorClass.BAD_REQUEST),   # 非额度非排队
    ('not json at all', False, None),                               # 认不出 ⇒ 交回原状态码
])
def test_single_predicate_agrees_with_downstream_class(body, is_business, expect_class):
    """`is_business_error`（唯一判据）与它下游的分类结果必须**一致**。

    这条钉的是"判据只有一份"的后果：`out` 层与 `business_error` 若再分叉（各自写一套码表，
    就是本波次被抓到的那个形状），这里会红。认不出的形状 `expect_class=None` = 调用方
    按原状态码走，不在本判据范围内。
    """
    assert envelope.is_business_error(body) is is_business, f"业务错误识别不符：{body}"
    if not is_business:
        return
    got = classify(envelope.business_error(body))
    assert got is expect_class, f"{body} 应判 {expect_class}，实判 {got}"
