"""日聚合 UT（UT-15；纯内存事件样本，聚合值与手算对照）。"""

from __future__ import annotations

from model_gateway.stats.aggregate import aggregate_day, estimate_usage


def _ev(**over) -> dict:
    base = {
        "request_id": "r", "ts": "2026-09-02T10:00:00",
        "client_token_id": "tok1", "system_model": "m1", "endpoint": "chat",
        "stream": False, "status": "success",
        "resource_attempts": [], "final_resource": "p1/k1/vm1",
        "retry_count": 0, "switch_count": 0, "duration_ms": 100, "ttft_ms": 50,
        "input_tokens": 10, "output_tokens": 5, "usage_source": "vendor",
        "images_count": None, "error_summary": None,
    }
    base.update(over)
    return base


class TestAggregateDay:
    """UT-15：三维（模型/资源/令牌）聚合算术与手算一致。"""

    def test_empty(self):
        agg = aggregate_day([])
        assert agg["totals"]["requests"] == 0
        for dim in ("by_model", "by_resource", "by_token"):
            assert agg[dim] == {}

    def test_single_event_dimensions(self):
        agg = aggregate_day([_ev()])
        t = agg["totals"]
        assert t["requests"] == 1 and t["success"] == 1 and t["failed"] == 0 and t["aborted"] == 0
        assert t["input_tokens"] == 10 and t["output_tokens"] == 5
        assert t["duration_ms_total"] == 100 and t["ttft_ms_total"] == 50 and t["ttft_count"] == 1
        assert agg["by_model"]["m1"]["requests"] == 1
        assert agg["by_resource"]["p1/k1/vm1"]["input_tokens"] == 10
        assert agg["by_token"]["tok1"]["success"] == 1

    def test_multi_event_arithmetic(self):
        """手算对照：3 事件混合状态/模型/资源/令牌。"""
        events = [
            _ev(),  # m1 / p1/k1/vm1 / tok1：success，(10,5)，retry 0
            _ev(request_id="r2", status="failed", system_model="m2",
                final_resource="p2/k2/vm2", retry_count=2, switch_count=1,
                input_tokens=20, output_tokens=0, duration_ms=300, ttft_ms=None),
            _ev(request_id="r3", status="aborted", system_model="m1",
                final_resource=None, client_token_id="tok2",
                input_tokens=0, output_tokens=0, duration_ms=50, ttft_ms=None),
        ]
        agg = aggregate_day(events)
        t = agg["totals"]
        assert t["requests"] == 3
        assert (t["success"], t["failed"], t["aborted"]) == (1, 1, 1)
        assert t["input_tokens"] == 30 and t["output_tokens"] == 5
        assert t["retry_count"] == 2 and t["switch_count"] == 1
        assert t["duration_ms_total"] == 450
        assert t["ttft_ms_total"] == 50 and t["ttft_count"] == 1  # ttft None 不计
        # 模型维
        assert agg["by_model"]["m1"]["requests"] == 2  # r1 + r3
        assert agg["by_model"]["m1"]["aborted"] == 1
        assert agg["by_model"]["m2"]["failed"] == 1
        # 资源维：无 final_resource → (none)
        assert agg["by_resource"]["(none)"]["aborted"] == 1
        # 令牌维：None token → (anonymous)
        assert agg["by_token"]["tok1"]["requests"] == 2
        assert agg["by_token"]["tok2"]["requests"] == 1

    def test_anonymous_and_unknown_buckets(self):
        agg = aggregate_day([
            _ev(client_token_id=None, system_model=None, final_resource=None)])
        assert agg["by_token"]["(anonymous)"]["requests"] == 1
        assert agg["by_model"]["(unknown)"]["requests"] == 1
        assert agg["by_resource"]["(none)"]["requests"] == 1

    def test_images_count(self):
        agg = aggregate_day([_ev(endpoint="images", images_count=4),
                             _ev(endpoint="images", images_count=2)])
        assert agg["totals"]["images_count"] == 6


class TestAggregateDerivedDims:
    """UT-27：by_provider / by_account 派生维度（Q17/PRD FR-6.1）。

    新格式行含事件冗余 provider/account 字段；历史行无该字段 → 空值归组 "(unknown)"。
    """

    def test_derived_dims_arithmetic(self):
        """手算对照：p1/acc-A 两行 + p2/acc-B 一行。"""
        events = [
            _ev(request_id="r1", provider="p1", account="acc-A",
                input_tokens=10, output_tokens=5, duration_ms=100, ttft_ms=50),
            _ev(request_id="r2", provider="p1", account="acc-A", status="failed",
                input_tokens=20, output_tokens=0, duration_ms=200, ttft_ms=None),
            _ev(request_id="r3", provider="p2", account="acc-B",
                input_tokens=7, output_tokens=3, duration_ms=30, ttft_ms=10),
        ]
        agg = aggregate_day(events)
        # by_provider：p1 = r1+r2，p2 = r3
        p1 = agg["by_provider"]["p1"]
        assert p1["requests"] == 2 and p1["success"] == 1 and p1["failed"] == 1
        assert p1["input_tokens"] == 30 and p1["output_tokens"] == 5
        assert p1["duration_ms_total"] == 300
        assert p1["ttft_ms_total"] == 50 and p1["ttft_count"] == 1  # r2 ttft None 不计
        p2 = agg["by_provider"]["p2"]
        assert p2["requests"] == 1 and p2["success"] == 1
        assert p2["input_tokens"] == 7 and p2["output_tokens"] == 3
        assert p2["ttft_ms_total"] == 10 and p2["ttft_count"] == 1
        # by_account：acc-A = r1+r2，acc-B = r3
        a = agg["by_account"]["acc-A"]
        assert a["requests"] == 2 and a["failed"] == 1
        assert a["input_tokens"] == 30 and a["duration_ms_total"] == 300
        b = agg["by_account"]["acc-B"]
        assert b["requests"] == 1 and b["output_tokens"] == 3

    def test_legacy_rows_grouped_as_unknown(self):
        """历史行无 provider/account 字段（或值为 null）→ 归入 (unknown)，不抛异常。"""
        events = [
            _ev(request_id="r1", provider="p1", account="acc-A"),
            _ev(request_id="r2"),  # 历史旧格式：无两字段
            _ev(request_id="r3", provider=None, account=None),  # 解析失败 → null 落盘
        ]
        agg = aggregate_day(events)
        assert agg["by_provider"]["(unknown)"]["requests"] == 2  # r2 + r3
        assert agg["by_provider"]["(unknown)"]["success"] == 2  # 均为基线 status=success
        assert agg["by_provider"]["p1"]["requests"] == 1
        assert agg["by_account"]["(unknown)"]["requests"] == 2
        assert agg["by_account"]["acc-A"]["requests"] == 1

    def test_existing_dims_and_totals_unaffected(self):
        """既有三维（by_model/by_resource/by_token）与 totals 不受新维度影响；五维键齐备。"""
        events = [
            _ev(request_id="r1", provider="p1", account="acc-A"),
            _ev(request_id="r2", provider="p2", account="acc-B", status="failed",
                input_tokens=20),
        ]
        agg = aggregate_day(events)
        t = agg["totals"]
        assert t["requests"] == 2 and t["success"] == 1 and t["failed"] == 1
        assert t["input_tokens"] == 30
        assert agg["by_model"]["m1"]["requests"] == 2
        assert agg["by_resource"]["p1/k1/vm1"]["requests"] == 2
        assert agg["by_token"]["tok1"]["requests"] == 2
        for dim in ("by_model", "by_resource", "by_token", "by_provider", "by_account"):
            assert dim in agg


class TestEstimateUsage:
    """FR-5.8：厂商缺 usage 时本地估算（>0，CJK 加权）。"""

    def test_ascii(self):
        inp, out = estimate_usage({"messages": [{"role": "user", "content": "hello world"}]},
                                  "hi there")
        assert inp >= 1 and out >= 1

    def test_cjk(self):
        inp, out = estimate_usage({"messages": [{"role": "user", "content": "你好世界"}]},
                                  "回复内容")
        assert inp >= 3 and out >= 2  # CJK 权重 1/1.5

    def test_multimodal_parts(self):
        body = {"messages": [{"role": "user", "content": [
            {"type": "text", "text": "看图"}, {"type": "image_url", "image_url": {"url": "x"}}]}]}
        inp, _ = estimate_usage(body, "")
        assert inp >= 2
