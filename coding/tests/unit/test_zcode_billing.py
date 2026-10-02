"""zcode **联网额度腿**的判据（方案 `20261002-zcode-quota-and-refresh.md` §8.1）。

覆盖三件事，每一件都是本轮改动引入的、**改动前必红**的行为：

1. `billing.classify` 的**九格真值表**（§6）—— 判"上游这一轮说了什么"，纯函数、不打网络；
2. `product.quota()` 的两条**不发起**早退与熔断归一（含 429/405/5xx 必须落到熔断面，
   不能被"未知"吞掉 —— 否则 §10-6 的观察期触发器永远判不出"已触发"）；
3. `_net_body()` / `_real_log_record()` 两个 fixture：**形状逐字取自【探针台账】§6.1–§6.3
   的无损原件**，不按实现倒推（QA r3 X-R3-1：倒推出来的 fixture 只能证明代码等于自己）。

🔴 fixture 红线（§8.1-1）：三个既有构造器（`test_v2_zcode_quota.py:_log_record()`、
`tests/accounts/test_zcode.py:_log_record()`、`test_int_v2_zcode_admin.py:_log_line()`）
的**输出形状不得改动** —— 它们钉的是"老形状可读"这条容错，实盘形状由本文件的
`_real_log_record()` 另行表达。想骗过所有断言最省事的动作就是去改构造器，故明令禁止。
"""

from __future__ import annotations

import json
import datetime as dt

import pytest

from model_gateway.accounts.types import QuotaSnapshot
from model_gateway.ops.builtin import query_balance as qb
from model_gateway.upstream.zcode import billing, quota as zq

# ── fixture：网络体三型（逐字来自【台账】§6.1 / §6.2 / §6.3）─────────────────────

#: ① 有数值（`available_units = 1e8`，全量未用）
NET_BODY_WITH_DATA = {
    "code": 0, "msg": "",
    "data": {
        "server_time": 1790905805,
        "plans": [{"user_plan_id": "upl_2105792494636244992",
                   "plan_id": "zcode-v3-start-plan-trust-1002",
                   "name": "ZCode Trust Build", "description": "ZCode Global Build",
                   "priority": 110, "status": "active",
                   "starts_at": 1790895029, "ends_at": 1790956800,
                   "entitlements": [{"entitlement_id": "zcode-v3-start-plan-trust-1002",
                                     "show_name": "GLM-5.3-Flash", "meter": "model_usage",
                                     "unit_type": "token",
                                     "capabilities": ["model:glm-5.3-flash"],
                                     "grant_units": 100000000, "period": "one_time",
                                     "priority": 110, "effective_at": 0}]}],
        "balances": [{"bucket_id": "bucket_2105792494661410816",
                      "user_plan_id": "upl_2105792494636244992",
                      "plan_id": "zcode-v3-start-plan-trust-1002",
                      "entitlement_id": "zcode-v3-start-plan-trust-1002",
                      "show_name": "GLM-5.3-Flash", "meter": "model_usage",
                      "unit_type": "token", "capabilities": ["model:glm-5.3-flash"],
                      "priority": 110, "plan_priority": 110, "entitlement_priority": 110,
                      "total_units": 100000000, "used_units": 0,
                      "remaining_units": 100000000, "available_units": 100000000,
                      "period_start": 1790895029, "period_end": 1790956800,
                      "expires_at": 1790956800}]},
    "logid": "20261002015005250705e2e908b7eaf936",
}

#: ② 空数组（同 code=0、同 200）——「无套餐」判据的**唯一**合法来源
NET_BODY_EMPTY = {
    "code": 0, "msg": "",
    "data": {"server_time": 1790905805, "plans": [], "balances": []},
    "logid": "202610020150053a3aaf116aeb5272fa53",
}

#: ③ 自然耗尽（`available_units = 0`）——"确实为 0"与"没给数字"必须分得开
NET_BODY_ZERO = json.loads(json.dumps(NET_BODY_WITH_DATA))
NET_BODY_ZERO["data"]["balances"][0].update(
    {"used_units": 100000000, "remaining_units": 0, "available_units": 0})


def _resp(status: int = 200):
    class _R:
        status_code = status
    return _R()


def _classify(body: dict, status: int = 200) -> billing.BillingResult:
    return billing.classify(_resp(status), body)


# ── 1) 九格真值表 ───────────────────────────────────────────────────────────────

def test_classify_ok_carries_numbers_plan_and_key():
    r = _classify(NET_BODY_WITH_DATA)
    assert r.kind == "ok" and r.spoke is True
    assert r.plan == "ZCode Trust Build"
    assert r.plan_key == "upl_2105792494636244992"          # 串号防护的主键来源
    assert r.buckets[0].available == 100000000
    assert r.buckets[0].unit_type == "token"                 # 量纲来自真字段，不硬编码
    assert r.buckets[0].period_end == 1790956800             # epoch 原样带出（归一化在钩子）
    assert r.server_time == 1790905805


def test_classify_empty_lists_is_no_plan_not_unreachable():
    """200 + code=0 + 双空 = **上游说了"没有套餐"**，不是"没说"。

    🔴 判据来源限定（§3-1）：只有网络通道这一型能产出 `no_plan`；
    日志/离线面**永不**产出 `reason`（兜底腿的数据不配有确定性结论）。
    """
    r = _classify(NET_BODY_EMPTY)
    assert r.kind == "no_plan" and r.spoke is True
    assert r.buckets == () and r.plan == ""
    assert "空套餐" in r.detail and "无套餐记录" in r.detail   # 两可性如实带出


def test_classify_zero_available_is_not_no_plan():
    r = _classify(NET_BODY_ZERO)
    assert r.kind == "ok"
    assert r.buckets[0].available == 0                       # 0 是事实，不是"没给"


def test_classify_missing_available_units_is_none_not_guessed():
    """缺 `available_units` ⇒ `None`（**绝不** `total - used`、**绝不**看 `remaining_units`）。

    旧兜底 `max(0, total-used)` 与 `quota.py` 自己那行"绝不能拿总量当可用"的注释互相打脸，
    本轮以断言形式定死（配套的 `:115/:128` 两条旧期望值同批被推翻，见 §8.1-2）。
    """
    body = {"code": 0, "data": {"balances": [{"show_name": "X", "total_units": 10,
                                              "used_units": 4, "remaining_units": 6}]}}
    r = _classify(body)
    assert r.kind == "ok"
    assert r.buckets[0].available is None
    assert r.buckets[0].remaining_units == 6                 # 只供展示，不参与聚合


def test_classify_401_is_expired_and_200_non_dict_is_unreachable():
    assert _classify({"code": 401, "msg": "unauthorized"}, status=401).kind == "expired"
    # WAF 页/非 JSON 的 200：状态码 200 **不等于**取到了（§22.8-5 fail closed）
    assert _classify({}).kind == "unreachable"
    assert _classify({"code": 0, "data": {}}).kind == "no_plan"     # data 在但两列表都空
    assert _classify({"code": 3001, "data": {"plans": []}}).kind == "unreachable"


@pytest.mark.parametrize("body,status", [
    ({"code": 3012, "msg": "unusual activity detected"}, 200),      # 业务码风控
    ({"code": 0, "data": {"plans": [{"name": "x"}]}}, 429),          # 限流
    ({"code": 0, "data": {"plans": [{"name": "x"}]}}, 405),          # 方法被挡
    ({"code": 0, "data": {"plans": [{"name": "x"}]}}, 503),           # 上游故障
    ({"code": 0, "msg": "unusual activity detected, try later", "data": {"plans": [{"n": 1}]}}, 200),  # 文案命中
])
def test_risk_control_signals_all_classify_as_risk(body, status):
    """🔴 429/405/5xx 与文案命中都必须落到 `risk_control`（PM r5 B-R4-3：
    枚举没这一格 = "出现任一次 429"在盘上没有可读物 = 触发器永远不会被判定为已触发）。"""
    r = _classify(body, status=status)
    assert r.kind == "risk_control" and r.risk_controlled is True
    assert str(status) in r.detail or "3012" in r.detail            # detail 带 HTTP/码，事后可证


def test_detail_carries_upstream_wording_and_http_number():
    r = _classify({"code": 0, "msg": "too many requests"}, status=429)
    assert "429" in r.detail and "too many requests" in r.detail


# ── 2) 钩子层：熔断归一 / 不发起 / 时间归一化 ──────────────────────────────────

@pytest.fixture
def no_network(monkeypatch):
    """把 HTTP 落点换成可编程的假响应，并记录调用次数（§8.1-9 的可桩落点）。"""
    calls: list = []
    box = {"status": 200, "body": dict(NET_BODY_WITH_DATA), "raise": None}

    async def _fake(jwt, device_mid, *, base_url):
        calls.append({"jwt": bool(jwt), "mid": bool(device_mid), "base": base_url})
        if box["raise"] is not None:
            raise box["raise"]
        class _R:
            status_code = box["status"]

            @staticmethod
            def json():
                return box["body"]
        return _R()

    monkeypatch.setattr(billing, "_http_get_balance", _fake)
    return {"calls": calls, "box": box}


async def _creds_for(tmp_path, monkeypatch, name="acct-net"):
    """让钩子拿到一对**可解析**的凭据（走公共层 `hook_meta` 的真实形状）。"""
    from model_gateway.accounts import store as astore

    def _fake_outbound(cred, meta):
        return ("jwt-value", "mid-value")

    monkeypatch.setattr(billing, "TIMEOUT_S", 1.0)
    return _fake_outbound


async def test_hook_maps_upstream_data_to_snapshot(no_network, monkeypatch):
    from model_gateway.upstream.zcode import product as zproduct

    def _creds(cred, meta):
        return ("jwt-x", "mid-x")

    monkeypatch.setattr(zproduct, "outbound_credentials", _creds)
    # 熔断必须是"没熔着"状态（盘上文件在别的用例里可能被写过）
    _clear_circuit(monkeypatch)

    snap = await zproduct.quota({"account": "a"}, {"account": "a"})
    assert isinstance(snap, QuotaSnapshot)
    assert snap.state == "available" and snap.source == zproduct.QUOTA_SOURCE_NET
    assert snap.reason == "" and snap.remaining == 100000000
    assert snap.plan_key == "upl_2105792494636244992"
    # 🔴 epoch → ISO 是**钩子**的责任（types.py 的 items 键契约原文）。
    #    不归一则前端 `shortTime()` 把 `1790956800` 原样显示、`Date.parse` 得 NaN。
    assert snap.data_at == dt.datetime.fromtimestamp(1790905805).isoformat(timespec="seconds")
    assert snap.data_at[:4].isdigit() and "T" in snap.data_at
    item = snap.items[0]
    assert item["unit"] == "token" and item["remaining"] == 100000000
    assert item["expires_at"] == dt.datetime.fromtimestamp(1790956800).isoformat(timespec="seconds")
    assert len(no_network["calls"]) == 1


async def test_hook_no_plan_maps_to_unknown_with_reason(no_network, monkeypatch):
    """界面第五档「无套餐」= `state=unknown` + `reason=no_plan`：**枚举一字未动**（裁决③）。"""
    from model_gateway.upstream.zcode import product as zproduct

    def _creds(cred, meta):
        return ("jwt-x", "mid-x")
    monkeypatch.setattr(zproduct, "outbound_credentials", _creds)
    _clear_circuit(monkeypatch)
    no_network["box"]["body"] = dict(NET_BODY_EMPTY)

    snap = await zproduct.quota({"account": "a"}, {"account": "a"})
    assert snap.state == "unknown" and snap.reason == "no_plan"
    assert snap.items == () and snap.remaining is None


def _clear_circuit(monkeypatch):
    """把额度腿看到的熔断状态判成"没熔着"（不动真盘：文件在 zcode 账号根里，
    别的用例与真实实例都会读它）。"""
    mgr = zq.get_circuit()
    monkeypatch.setattr(type(mgr), "active", lambda self: False, raising=True)
    monkeypatch.setattr(type(mgr), "untrusted", property(lambda self: None), raising=True)


async def test_hook_risk_control_enters_circuit_and_reports_circuit(no_network, monkeypatch):
    """第 4 格：首次命中风控 ⇒ **建同一份全局熔断** + `reason=circuit`（同轮其余号撞第 5 格）。"""
    from model_gateway.upstream.zcode import product as zproduct

    def _creds(cred, meta):
        return ("jwt-x", "mid-x")
    monkeypatch.setattr(zproduct, "outbound_credentials", _creds)
    _clear_circuit(monkeypatch)
    entered: list = []
    mgr = zq.get_circuit()
    monkeypatch.setattr(mgr, "enter", lambda reason: entered.append(reason), raising=True)
    no_network["box"]["status"] = 429
    no_network["box"]["body"] = {"code": 0, "msg": "too many requests"}

    snap = await zproduct.quota({"account": "a"}, {"account": "a"})
    assert snap.state == "unknown" and snap.reason == "circuit"
    assert snap.source == zproduct.QUOTA_SOURCE_CIRCUIT
    assert entered, "风控信号必须建熔断 —— 它是同轮止损的唯一机制"


async def test_hook_circuit_active_short_circuits_without_request(no_network, monkeypatch):
    """第 5 格：盘上已熔着 ⇒ **一次请求都不发**（"止损"不是机制，是这一格的推论）。"""
    from model_gateway.upstream.zcode import product as zproduct

    def _creds(cred, meta):
        return ("jwt-x", "mid-x")
    monkeypatch.setattr(zproduct, "outbound_credentials", _creds)
    mgr = zq.get_circuit()
    monkeypatch.setattr(type(mgr), "active", lambda self: True, raising=True)
    monkeypatch.setattr(type(mgr), "untrusted", property(lambda self: None), raising=True)

    snap = await zproduct.quota({"account": "a"}, {"account": "a"})
    assert snap.reason == "circuit" and "未发起" in snap.detail
    assert no_network["calls"] == []


async def test_hook_untrusted_is_distinct_from_circuit(no_network, monkeypatch):
    """第 7 格：`untrusted`（状态文件读不动）与"已熔着"必须**分得开**，且**不带钟点**。"""
    from model_gateway.upstream.zcode import product as zproduct

    def _creds(cred, meta):
        return ("jwt-x", "mid-x")
    monkeypatch.setattr(zproduct, "outbound_credentials", _creds)
    mgr = zq.get_circuit()
    monkeypatch.setattr(type(mgr), "active", lambda self: True, raising=True)
    monkeypatch.setattr(type(mgr), "untrusted",
                        property(lambda self: "状态文件是半行 JSON"), raising=True)

    snap = await zproduct.quota({"account": "a"}, {"account": "a"})
    assert snap.reason == "circuit-untrusted"
    assert "读不动" in snap.detail
    assert "分钟" not in snap.detail                    # untrusted 时 reason() 自己也拒给时刻
    assert no_network["calls"] == []


# ── 3) 写盘分档 + 执行体签名 + 开关 ───────────────────────────────────────────

def test_silent_table_covers_every_no_data_reason():
    """`SILENT` 必须**穷举**钩子可能产出的"没说"档；漏一档 = 那一档会整键覆盖洗掉旧数值。

    取不到 `reason` 的枚举只能靠这条测试 + 上面九格各自的断言；这里做的是**跨模块对账**
    （`product` 侧新增一档忘了进 `SILENT`，今天没有任何别的判据会红）。
    """
    assert set(qb.SILENT) == {"circuit", "circuit-untrusted", "unreachable",
                              "no_credentials", "no_identity"}
    assert set(qb.PRESERVE_KEYS) == {"items", "plan", "remaining", "data_at", "plan_key"}
    # 反向：说"没说话"的档里不许出现"说了"的两档
    assert "no_plan" not in qb.SILENT and "expired" not in qb.SILENT


def test_cache_key_set_is_snapshot_fields_plus_checked_at():
    """护栏写成**并集**：现盘键集 = dataclass 字段 + `checked_at`，写"键集相等"今天即红。"""
    import dataclasses

    expect = {f.name for f in dataclasses.fields(QuotaSnapshot)} | {"checked_at"}
    assert set(qb._quota_cache_keys()) == expect
    assert "checked_at" not in {f.name for f in dataclasses.fields(QuotaSnapshot)}


# ── 4) 写盘分档：合并写 vs 整键覆盖（§8.1-4 / §4-1）────────────────────────────

def _seed_account(product: str, name: str, quota: dict) -> dict:
    """造一个已有 `runtime.json.quota` 的账号（联网腿跑之前的"上一轮"）。"""
    from model_gateway.accounts import store as astore

    astore.write_runtime(product, name, {"quota": quota})
    return quota


async def test_silent_leg_preserves_last_real_numbers(tmp_path, monkeypatch):
    """熔断轮**不得**把上一轮的真实余量洗成空（方案 §4-1；工程 r4 B-R4-1 / QA r4 X-R4-5）。

    这是"删掉节奏层就没有洗盘洞"的反例：洗盘发生在**写盘侧**，与"被不被挡"无关。
    断言三件事同时成立才算修好：数值面逐字不变、`checked_at` 前进、`reason` 落档。
    """
    from model_gateway.accounts import store as astore
    from model_gateway.accounts.types import QuotaSnapshot

    # 数据根隔离由 `tests/conftest.py::_data_dir_isolated` 钉（它认 `MG_CONFIG`，不是 `MGW_DATA_ROOT`）
    prev = {"state": "available", "source": "zcode-billing", "detail": "上一轮",
            "checked_at": "2026-10-02T09:00:00", "plan": "ZCode Trust Build",
            "items": [{"name": "GLM-5.3-Flash", "unit": "token", "remaining": 70576812,
                       "total": 100000000, "used": 29423188, "active": True,
                       "expires_at": "2026-10-03T00:00:00"}],
            "remaining": 70576812, "reason": "", "data_at": "2026-10-02T09:00:00",
            "plan_key": "upl_existing"}
    _seed_account("zcode", "acct-merge", prev)

    snap = QuotaSnapshot(state="unknown", source="zcode-circuit", reason="circuit",
                         detail="全局风控熔断中（剩余约 28 分钟）→ 未发起额度查询")
    assert qb._write_quota_cache("zcode", "acct-merge", snap) == ""
    cache = astore.read_runtime("zcode", "acct-merge")["quota"]
    for k in qb.PRESERVE_KEYS:
        assert cache[k] == prev[k], f"合并写丢了 {k}（一次熔断不该清空上一轮的真实数据）"
    assert cache["checked_at"] != prev["checked_at"]        # 这一轮确实判过一次
    assert cache["reason"] == "circuit" and cache["state"] == "unknown"


async def test_spoken_leg_overwrites_wholesale(tmp_path, monkeypatch):
    """上游**明确说了**（`no_plan` / `expired` / 有数值）⇒ 整键覆盖：旧数值必须消失。

    反向半条：把 `SILENT` 与覆盖档写反（例如 `no_plan` 也合并写），本条必红 ——
    那会让一个"确认无套餐"的号永远挂着上一次的余量数字。
    """
    from model_gateway.accounts import store as astore
    from model_gateway.accounts.types import QuotaSnapshot

    prev = {"state": "available", "source": "zcode-billing", "detail": "上一轮",
            "checked_at": "2026-10-02T09:00:00", "plan": "旧套餐",
            "items": [{"name": "旧包", "unit": "token", "remaining": 5, "total": 9,
                       "used": 4, "active": True, "expires_at": ""}],
            "remaining": 5, "reason": "", "data_at": "2026-10-02T09:00:00",
            "plan_key": "upl_old"}
    _seed_account("zcode", "acct-speak", prev)
    snap = QuotaSnapshot(state="unknown", source="zcode-billing", reason="no_plan",
                         detail="上游返回空套餐与空余额列表（code=0）")
    assert qb._write_quota_cache("zcode", "acct-speak", snap) == ""
    cache = astore.read_runtime("zcode", "acct-speak")["quota"]
    assert cache["items"] == [] and cache["plan"] == "" and cache["remaining"] is None
    assert cache["reason"] == "no_plan"


# ── 5) 开关与执行体（§6 第 8 格 / §5-1）───────────────────────────────────────

def _cfg_with(quota_net: bool):
    """造一个**运行态形状**的对象（`run_for` 读的是 `runtime.config.gateway.zcode.quota_net`，
    直接塞 `AppConfig` 会因少一层 `.config` 而走 except 支 ⇒ 测不到开关本身）。"""
    from types import SimpleNamespace

    from model_gateway.config.schemas import AppConfig

    cfg = AppConfig.model_validate({"resources": [], "models": []})
    cfg.gateway.zcode.quota_net = quota_net
    return SimpleNamespace(config=cfg, resources=None)


async def test_switch_off_blocks_cron_leg_but_not_the_user_leg(no_network, monkeypatch):
    """第 8 格两条对照：开关只管 cron，**手动腿必须真刷**。

    🔴 判据不能挂 `manual`（全仓 `run_once(..., manual=True)` 零调用）——
    挂错了的表现正是"用户点了刷新额度、界面上什么都没变"。
    """
    from model_gateway.upstream.zcode import product as zproduct

    def _creds(cred, meta):
        return ("jwt-x", "mid-x")
    monkeypatch.setattr(zproduct, "outbound_credentials", _creds)
    _clear_circuit(monkeypatch)
    reasons: dict = {}

    off = _cfg_with(False)
    r = await qb.run_for("zcode", "acct-x", runtime=off, via="cron", reasons_out=reasons)
    assert r.category == "inactive" and "未发起" in r.detail
    assert reasons["acct-x"] == qb.QUOTA_NET_OFF          # 哨兵：这格没有 reason 可用
    assert no_network["calls"] == []

    reasons2: dict = {}
    r2 = await qb.run_for("zcode", "acct-y", runtime=off, via="user", reasons_out=reasons2)
    assert r2.category == "success" and reasons2["acct-y"] == ""
    assert len(no_network["calls"]) == 1                  # 手动腿照样联网


async def test_switch_on_lets_the_cron_leg_through(no_network, monkeypatch):
    from model_gateway.upstream.zcode import product as zproduct

    def _creds(cred, meta):
        return ("jwt-x", "mid-x")
    monkeypatch.setattr(zproduct, "outbound_credentials", _creds)
    _clear_circuit(monkeypatch)
    reasons: dict = {}
    r = await qb.run_for("zcode", "acct-z", runtime=_cfg_with(True), via="cron",
                         reasons_out=reasons)
    assert r.category == "success" and reasons["acct-z"] == ""
    assert len(no_network["calls"]) == 1


def test_quota_net_defaults_to_off_in_the_schema():
    """**默认 false**：授权方向是"用户点头才开"，不是"默认开着等否决"（PM r6 N-R5）。"""
    from model_gateway.config.loader import load_config  # noqa: F401  (确认可导入，不在测试期读盘)
    from model_gateway.config.schemas import GatewayConfig

    assert GatewayConfig().zcode.quota_net is False


# ── 6) 回写分派：zcode 保留 §17 义务、通用体不 bench（§8.1-6 / 6b / 6c）────────

def _runtime_with(rid: str, account: str):
    from model_gateway.config.schemas import AppConfig
    from model_gateway.core.resources import ResourceManager

    cfg = AppConfig.model_validate({
        "resources": [{"id": rid, "name": "R", "product": "zcode", "account_ref": account,
                       "account": account, "base_url": "http://127.0.0.1:9/v1", "api_key": ""}],
        "models": [{"name": "m", "endpoint": "chat",
                    "resources": [{"resource": rid, "model": "vm"}]}]})
    mgr = ResourceManager()
    mgr.rebuild(cfg)

    class _RT:
        resources = mgr
        config = cfg

    return _RT(), mgr


async def test_zcode_exhausted_writes_status_and_reason(tmp_path, monkeypatch):
    """裁决⑤ 的命门：余量 0 ⇒ 池 0 **+ `status=cooldown` + `last_error=额度耗尽**（§17 字面义务）。

    这条之所以必须存在：既有用例都是**函数直调** `apply_snapshot_to_runtime`，
    通道合并后它们照样绿 ⇒ "全绿但行为变了"。工程 r7 实测的另一半：
    今天 zcode ops 腿对池**零写入**，所以拿"与改动前盘上一致"当尺子是空转 ——
    这里改成**同一事实喂两条写入源对照**。
    """
    from model_gateway.accounts.types import QuotaSnapshot as Pub
    from model_gateway.upstream.zcode import quota as zq

    RT, mgr = _runtime_with("res-z1", "acct-z")
    net = Pub(state="exhausted", source="zcode-billing", detail="余量 0", remaining=0)
    n1 = qb._apply_zcode_quota("zcode", "acct-z", net, RT)
    st = mgr.registry[("res-z1", "vm")]
    assert st.quota.remaining == 0 and n1 == 1
    assert st.status == "cooldown" and st.last_error == zq.QUOTA_EXHAUSTED_REASON

    # 离线面（日志腿）喂同一个"余量 0"事实 ⇒ 三项逐字相同（单一实现，不是两份口径）
    RT2, mgr2 = _runtime_with("res-z2", "acct-z2")
    private = zq.QuotaSnapshot(account="acct-z2",
                              buckets=[zq.Bucket(show_name="GLM", period="", total=10,
                                                 used=10, available=0)])
    n2 = zq.apply_snapshot_to_runtime(RT2, "acct-z2", private)
    st2 = mgr2.registry[("res-z2", "vm")]
    assert n2 == n1 and st2.quota.remaining == 0
    assert st2.status == "cooldown" and st2.last_error == zq.QUOTA_EXHAUSTED_REASON
    assert mgr2.set_quota is not None   # 只证明对象可用，不额外断言


async def test_generic_applier_never_writes_resource_status(tmp_path, monkeypatch):
    """**9 个非 zcode 产品永不 bench**：它们本轮不填 `remaining`，耗尽只写池 0。

    撤证（可红方向写死）：往缺省体 `_apply_quota_to_pools` 里、紧接既有
    `remaining = 0 if snap.state == "exhausted" else None` 那行**也加一条 bench**
    ⇒ 本条必红。⚠️ 不得写成 `snap.remaining == 0` —— 那一支对 9 个产品恒不点着
    （该字段本轮恒 None），撤证就变成不可红的空转（工程 r6 B-R6-5 / QA R7-4 实测）。
    """
    from model_gateway.accounts.types import QuotaSnapshot as Pub
    from model_gateway.config.schemas import AppConfig
    from model_gateway.core.resources import ResourceManager

    cfg = AppConfig.model_validate({
        "resources": [{"id": "res-q1", "name": "Q", "product": "qoder",
                       "account_ref": "acct-q", "account": "acct-q",
                       "base_url": "http://127.0.0.1:9/v1", "api_key": ""}],
        "models": [{"name": "m", "endpoint": "chat",
                    "resources": [{"resource": "res-q1", "model": "vm"}]}]})
    mgr = ResourceManager()
    mgr.rebuild(cfg)

    class _RT:
        resources = mgr
        config = cfg

    st = mgr.registry[("res-q1", "vm")]
    snap = Pub(state="exhausted", source="qoder-usage", detail="额度已耗尽")   # 不填 remaining
    assert qb._apply_quota_to_pools("qoder", "acct-q", snap, _RT()) == 1
    assert st.quota.remaining == 0                     # 池写 0（现行为）
    assert st.status == "active" and not st.last_error  # 🔴 不回写状态：未经取证的变更


# ── 7) §8.1-6c：9 个非 zcode 产品的**写盘语义**逐字节不变（QA r5 X-R5-9 第三条）──

#: 除 zcode 外的 9 个在册产品（本轮它们都不填 `remaining`、不产 `reason`）
NON_ZCODE_PRODUCTS = ("buddy", "workbuddy", "lobsterai", "qoder", "qodercn",
                      "trae", "cline", "loomy", "raccoon")


async def test_nine_products_keep_wholesale_overwrite():
    """9 个产品的失败腿**仍是整键覆盖**：上一轮 `items` 被洗成 `[]`，与改动前逐字一致。

    防的是"顺手把分派条件写成 `state == "unknown" ⇒ 合并写`"：那种写法会让这 9 个产品在
    **未经取证**的情况下突然开始保留上一轮数值。§8.1-6 只钉"池值与选路结果"，抓不到
    盘上语义变了（QA X-R5-9 的缺口就在这），故这条单独钉写盘侧。
    反向撤证 = 把 9 产品并入合并写（例如分派条件改成 `state=="unknown"`）⇒ 本条必红。
    """
    from model_gateway.accounts import store as astore
    from model_gateway.accounts.types import QuotaSnapshot

    for product in NON_ZCODE_PRODUCTS:
        name = f"acct-{product}"
        prev = {"state": "available", "source": f"{product}-usage", "detail": "上一轮",
                "checked_at": "2026-10-02T09:00:00", "plan": "旧套餐",
                "items": [{"name": "旧包", "unit": "credits", "remaining": 12,
                           "total": 40, "used": 28, "active": True, "expires_at": ""}],
                "remaining": 12, "reason": "", "data_at": "2026-10-02T09:00:00",
                "plan_key": "old-key"}
        astore.write_runtime(product, name, {"quota": prev})
        # 失败腿：这 9 个产品的钩子本轮只可能产出 `unknown + reason=""`
        fail = QuotaSnapshot(state="unknown", source=f"{product}-usage",
                             detail="未能取到额度（未知不当零）")
        assert qb._write_quota_cache(product, name, fail) == ""
        cache = astore.read_runtime(product, name)["quota"]
        assert cache["items"] == [] and cache["plan"] == "", f"{product} 的洗盘语义变了"
        assert cache["remaining"] is None and cache["plan_key"] == ""
        assert cache["reason"] == "" and cache["state"] == "unknown"


# ── 8) §8.1-10：钩子**每条**非成功路径都必须给出表内 reason（工程 r7 B-R7-1 的正解）──

#: 八条出口 → 期望的机器可读档位（方案 §6 真值表 + §3-7 的网络异常档）
HOOK_EXITS = {
    "no_identity": "no_identity",
    "no_jwt": "no_credentials",
    "no_device_mid": "no_credentials",
    "network_error": "unreachable",
    "http_401": "expired",
    "risk_control_3012": "circuit",
    "circuit_on_disk": "circuit",
    "untrusted": "circuit-untrusted",
}


def _drive(exit_name: str, no_network, monkeypatch):
    """把真钩子推到指定的那一条出口上，返回它这一轮的快照。

    遍历范围**写死成这 8 条**（工程 r8 O-3）：§4-3 那一档（200 有桶但 `available` 全缺
    = `unknown + reason=""`）**显式不在列**，它由 `test_bucket_without_available_is_unknown_with_no_reason`
    单独钉 —— 若把它也要求成"必须有 reason"，对正确实现必红。
    """
    import httpx

    from model_gateway.upstream.zcode import product as zproduct

    def _creds(_cred, _meta):
        return ("jwt-x", "mid-x")

    monkeypatch.setattr(zproduct, "outbound_credentials", _creds)
    _clear_circuit(monkeypatch)
    entered: list = []
    monkeypatch.setattr(zq.get_circuit(), "enter", lambda why=None: entered.append(why),
                        raising=True)
    box = no_network["box"]

    if exit_name == "no_identity":
        return {}, {}
    if exit_name == "no_jwt":
        monkeypatch.setattr(zproduct, "outbound_credentials",
                            lambda _c, _m: ("", "mid-x"))
    elif exit_name == "no_device_mid":
        monkeypatch.setattr(zproduct, "outbound_credentials",
                            lambda _c, _m: ("jwt-x", ""))
    elif exit_name == "network_error":
        box["raise"] = httpx.ConnectError("connection refused")
    elif exit_name == "http_401":
        box["status"] = 401
        box["body"] = {"code": 0, "msg": "unauthorized"}
    elif exit_name == "risk_control_3012":
        box["body"] = {"code": zq.CODE_RISK_CONTROL, "msg": "risk control"}
    elif exit_name == "circuit_on_disk":
        mgr = zq.get_circuit()
        monkeypatch.setattr(type(mgr), "active", lambda self: True, raising=True)
    elif exit_name == "untrusted":
        mgr = zq.get_circuit()
        monkeypatch.setattr(type(mgr), "untrusted",
                            property(lambda self: "RuntimeUnreadable: 盘坏了"), raising=True)
    return {"account": "acct-exit"}, {"account": "acct-exit"}


@pytest.mark.parametrize("exit_name", sorted(HOOK_EXITS))
async def test_every_hook_exit_reports_a_registered_reason(exit_name, no_network, monkeypatch):
    """漏登记一档 = 那一档会整键覆盖、静默洗掉上一轮的真实数值 —— 今天没有别的判据会红。

    正向：这 8 条出口的 `reason` 必须**非空**且在 `SILENT ∪ {expired, no_plan}` 里；
    反向撤证：把「缺账号名」那档改回 `reason=""` ⇒ `in registered` 半条当场红。
    """
    from model_gateway.upstream.zcode import product as zproduct

    cred, meta = _drive(exit_name, no_network, monkeypatch)
    snap = await zproduct.quota(cred, meta)
    registered = set(qb.SILENT) | {"expired", "no_plan"}

    assert snap.state == "unknown", f"{exit_name} 不是非成功出口"
    assert snap.reason, f"{exit_name} 没给 reason —— 会被整键覆盖洗掉旧数值"
    assert snap.reason in registered, f"{exit_name} 的 {snap.reason} 未登记进 SILENT"
    assert snap.reason == HOOK_EXITS[exit_name]


async def test_bucket_without_available_is_unknown_with_no_reason(no_network, monkeypatch):
    """§4-3 那一档的**豁免**：200 有桶但 `available_units` 全缺 ⇒ `unknown + reason=""`。

    它属于"上游说了、但没给可量化余量"，走**整键覆盖**（不是合并写）；
    若把它也算进"必须有 reason"的遍历，对正确实现必红（工程 r8 O-3）。
    """
    from copy import deepcopy

    from model_gateway.upstream.zcode import product as zproduct

    def _creds(_cred, _meta):
        return ("jwt-x", "mid-x")
    monkeypatch.setattr(zproduct, "outbound_credentials", _creds)
    _clear_circuit(monkeypatch)
    body = deepcopy(NET_BODY_WITH_DATA)
    body["data"]["balances"][0].pop("available_units")
    no_network["box"]["body"] = body

    snap = await zproduct.quota({"account": "a"}, {"account": "a"})
    assert snap.state == "unknown" and snap.reason == ""
    assert snap.remaining is None and snap.items[0]["remaining"] is None
    assert snap.reason not in qb.SILENT                    # ⇒ 覆盖支（旧数值该洗就洗）
