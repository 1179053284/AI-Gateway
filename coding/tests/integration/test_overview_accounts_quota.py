"""总览「账号资源额度」聚合（2026-10-07 用户指令：每产品一个小卡片，显示可用总额度）。

钉的是板块数据的三条承重腿：

① **口径** = 「接入账号资源」页额度格（`quotaCell`）的同一把尺：只计 `active` 包、
   只计**数值型** `remaining`（`null` 不当 0 —— 「没给数字」与「数字是 0」是两件事）；
② **分桶** = `counted / unknown / no_plan / no_snapshot` 互斥、合计 = 账号数，
   **停用账号照样计入**（额度是只读视图，Q32 纪律）；`oldest_checked_at` 只取计入账号的
   最旧数据时刻（`data_at || checked_at`）；
③ **fail-closed** = 单账号 `runtime.json` 读不动只进 `unknown` 桶 + 留日志，
   不冒穿整个 `/admin/api/overview`、不拖累同产品其他账号。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from model_gateway.accounts import store

BUDDY = "buddy"
ZCODE = "zcode"
RACCOON = "raccoon"
WORKBUDDY = "workbuddy"


def _write_cfg(tmp_path: Path) -> Path:
    """最小配置：零资源零模型 + **关掉运营定时器**（claim_interval_seconds=0）。

    🔴 关定时器是测试卫生：本文件造的是"额度快照已落盘"的状态，不需要（也不允许）
    任何自动腿在本回合真的出站。
    """
    cfg = {"resources": [], "models": [],
           "gateway": {"zcode": {"claim_interval_seconds": 0}}}
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return p


def _seed(product: str, name: str, *, enabled: bool = True, runtime: dict | None = None) -> None:
    """造一个账号（生产同一条落盘入口）+ 可选的 runtime.json（额度快照的落点）。"""
    store.commit_login(product, name, {"token": f"t-{name}"}, {"enabled": enabled})
    if runtime is not None:
        store.write_runtime(product, name, runtime)


def _quota(state: str = "available", *, reason: str = "", items: list | None = None,
           checked_at: str = "2026-10-07T10:00:00", data_at: str = "") -> dict:
    """额度快照（字段集与 `_write_quota_cache` 的落盘键一致）。"""
    return {"state": state, "source": "test", "detail": "", "checked_at": checked_at,
            "plan": "", "items": items or [], "remaining": None, "reason": reason,
            "data_at": data_at, "plan_key": ""}


def _item(unit: str, remaining, *, active: bool = True) -> dict:
    return {"name": "包", "unit": unit, "remaining": remaining, "total": None,
            "used": None, "active": active, "expires_at": ""}


@pytest.fixture()
def client(tmp_path):
    from fastapi.testclient import TestClient

    from model_gateway.main import create_app

    app = create_app(config_path=_write_cfg(tmp_path), usage_dir=tmp_path / "usage",
                     enums_path=tmp_path / "enums.yaml")
    with TestClient(app) as c:
        yield c


def _overview(client) -> dict:
    resp = client.get("/admin/api/overview")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _of(payload: dict, product: str) -> dict:
    return next(p for p in payload["accounts_quota"] if p["product"] == product)


class TestAggregation:
    def test_credits_sum_excludes_inactive_skips_null_and_counts_disabled(self, client):
        """积分类合计：失效包不计、null 不当 0（进 unknown 桶）、停用账号照常计入。"""
        _seed(BUDDY, "acc-a", runtime={"quota": _quota(items=[
            _item("credits", 500.0),
            _item("credits", 100.5),
            _item("credits", 999.0, active=False),      # 失效包：不得计入
            _item("credit", 40.0),
        ])})
        _seed(BUDDY, "acc-b", enabled=False, runtime={"quota": _quota(items=[
            _item("credits", 40.0),
        ])})
        # 只有 null 余量的账号：没给数字 ⇒ unknown 桶，**不许**当 0 混进 counted
        _seed(BUDDY, "acc-c", runtime={"quota": _quota(items=[_item("credits", None)])})
        row = _of(_overview(client), BUDDY)
        assert row["accounts"] == 3 and row["enabled"] == 2
        assert row["counted"] == 2, "acc-a + acc-b 计入；acc-c 只有 null 余量不得计入"
        assert row["unknown"] == 1
        assert row["totals"] == [{"unit": "credits", "remaining": 680.5}], \
            "500+100.5+40+40=680.5；999（失效）与 null 都不得进来"
        assert row["oldest_checked_at"] == "2026-10-07T10:00:00"

    def test_token_unit_kept_and_oldest_uses_data_at_then_checked_at(self, client):
        """token 量纲单独成类；`oldest_checked_at` = 计入账号里最旧的 `data_at || checked_at`。"""
        _seed(ZCODE, "acc-t1", runtime={"quota": _quota(
            items=[_item("token", 100_000_000)], data_at="2026-10-07T08:00:00",
            checked_at="2026-10-07T12:00:00")})
        _seed(ZCODE, "acc-t2", runtime={"quota": _quota(
            items=[_item("token", 5_000_000)], checked_at="2026-10-06T07:00:00")})
        row = _of(_overview(client), ZCODE)
        assert row["counted"] == 2
        assert row["totals"] == [{"unit": "token", "remaining": 105_000_000}]
        # t1 取 data_at（08:00，优先于更晚的 checked_at）；t2 取 checked_at（前一天）⇒ 最旧 = t2
        assert row["oldest_checked_at"] == "2026-10-06T07:00:00"

    def test_buckets_are_exclusive_and_no_snapshot_separate(self, client):
        """`no_plan`（上游明说无套餐）与 `no_snapshot`（根本没刷新过）各归各桶。"""
        _seed(ZCODE, "acc-noplan", runtime={"quota": _quota(state="unknown", reason="no_plan")})
        _seed(ZCODE, "acc-never")                                   # 无 runtime.json
        _seed(RACCOON, "acc-unknown",
              runtime={"quota": _quota(state="unknown", reason="unreachable")})
        payload = _overview(client)
        zc = _of(payload, ZCODE)
        assert (zc["counted"], zc["unknown"], zc["no_plan"], zc["no_snapshot"]) == (0, 0, 1, 1)
        assert zc["totals"] == [] and zc["oldest_checked_at"] is None
        rc = _of(payload, RACCOON)
        assert (rc["counted"], rc["unknown"]) == (0, 1)

    def test_unreadable_runtime_is_fail_closed(self, client):
        """单账号读不动：端点照样 200，该号进 unknown 桶，同产品好号不受影响。"""
        _seed(BUDDY, "acc-good", runtime={"quota": _quota(items=[_item("credits", 12.5)])})
        _seed(BUDDY, "acc-bad")
        (store.product_root(BUDDY) / "acc-bad" / "runtime.json").write_text(
            "{not json", encoding="utf-8")
        row = _of(_overview(client), BUDDY)
        assert row["counted"] == 1 and row["unknown"] == 1
        assert row["totals"] == [{"unit": "credits", "remaining": 12.5}]

    def test_no_accounts_means_empty_list(self, client):
        """零账号 ⇒ 空表（前端据此不渲染板块）；不是 10 行全 0。"""
        assert _overview(client)["accounts_quota"] == []

    def test_credit_and_credits_merge_into_one_class(self, client):
        """同一账号里 `credit` / `credits` 是同一量纲类 ⇒ 合计只有一个条目（workbuddy 实盘形状）。"""
        _seed(WORKBUDDY, "acc-w", runtime={"quota": _quota(items=[
            _item("credit", 300.0), _item("credits", 3.89),
        ])})
        row = _of(_overview(client), WORKBUDDY)
        assert row["totals"] == [{"unit": "credits", "remaining": 303.89}]

    def test_zero_remaining_is_counted_not_unknown(self, client):
        """真的 0（已耗尽）算 counted；这与「没给数字」必须分开。"""
        _seed(BUDDY, "acc-zero", runtime={"quota": _quota(state="exhausted",
                                                           items=[_item("credits", 0.0)])})
        row = _of(_overview(client), BUDDY)
        assert row["counted"] == 1 and row["unknown"] == 0
        assert row["totals"] == [{"unit": "credits", "remaining": 0.0}]

    def test_non_finite_and_bool_never_enter_the_sum(self, client):
        """坏值不冒穿端点，也不进合计：`Infinity`/`NaN`（`json.loads` 收得下）、`true`（是 int 实例）。

        来源不是想象：`runtime.json` 是落盘文件，外来/手改进的 `Infinity` 字面量会被
        `json.loads` 原样解析成 `float('inf')`，而 `math.isfinite(10**400)` 在 Python 里
        直接抛 `OverflowError` —— 少一层判定就是整条 `/admin/api/overview` 的 500。
        """
        _seed(BUDDY, "acc-bad-numbers", runtime=None)
        (store.product_root(BUDDY) / "acc-bad-numbers" / "runtime.json").write_text(
            '{"quota": {"state": "available", "reason": "", "checked_at": "2026-10-07T10:00:00",'
            ' "data_at": "", "items": ['
            '{"name": "无穷包", "unit": "credits", "remaining": Infinity, "active": true},'
            '{"name": "非数包", "unit": "credits", "remaining": NaN, "active": true},'
            '{"name": "布尔包", "unit": "credits", "remaining": true, "active": true}'
            ']}}', encoding="utf-8")
        _seed(BUDDY, "acc-ok", runtime={"quota": _quota(items=[_item("credits", 7.5)])})
        row = _of(_overview(client), BUDDY)
        assert row["counted"] == 1, "三个坏值都不算「取到了数值」"
        assert row["unknown"] == 1
        assert row["totals"] == [{"unit": "credits", "remaining": 7.5}], \
            "坏值一旦被当数字累加，合计就成了 inf/nan/1 —— 整张卡不可读"
        assert json.dumps(row, ensure_ascii=False, allow_nan=False)
