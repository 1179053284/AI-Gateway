"""M7-UI 后端硬前置 BD1 / BD8 / BD3a（设计书 `docs/changes/design-accounts-list-v2.md` §0-4、§6）。

三条都是"界面对用户撒的谎"的后端半边（设计书 §9），逐条判据与**撤修复红证**成对登记：

| 用例 | 被测行为（落点） | 撤掉修复后本文件哪条转红 |
|---|---|---|
| `test_cron_leg_skips_disabled_account` | `main.py::_maybe_start_ops` 两条腿传 `enabled_of=cron_enabled_of`（BD1） | 停用账号出现在 `claims` 与落盘行的 `success` 里 |
| `test_cron_leg_without_enabled_of_still_claims_disabled` | —— 同一条的**在册反向对照**：修前的调用形态（不传 `enabled_of`） | 本条即设计书 §8-3③ 要求的撤证，长期可复跑 |
| `test_cron_enabled_of_reads_the_same_bit_as_the_switch` | `api/admin_accounts.py::cron_enabled_of` 与界面开关同源（BD1） | 停用位读成启用 → 正向那条与手动腿一起错位 |
| `test_ops_scheduler_starts_with_zero_accounts` | 启动期"0 账号即永不起"的门已撤（BD8） | `app.state.ops_scheduler is None` |
| `test_empty_tick_writes_nothing_then_first_account_gets_snapshot` | 门改在每一轮 + 空轮不落盘（BD8） | 空轮写出噪音行；接入账号后 `runtime.json` 不出现 |
| `test_gateway_process_writes_quota_snapshot_without_restart` | 真进程（随机端口、间隔 1s）接入第一个账号后自行出快照（BD8） | 同上（进程级复现） |
| `test_view_resource_join_materialised_and_absent` | `_account_entry` 的 `resource` 只读投影（BD3a） | `KeyError: 'resource'` |
| `test_view_survives_unreadable_config_with_resource_unknown` | 配置读不动 → 视图 200 + `resource` 为 `None`（BD3a） | 视图 500（一格读不动把整页拖没） |

纪律：无网络（假钩子 / 假体 operation）、不碰仓库 `data/`（conftest 钉 `MG_CONFIG`）、
不碰 `127.0.0.1:8300`（进程级用例走随机端口）。
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import json
import types
from pathlib import Path

from model_gateway.accounts import store
from model_gateway.accounts.types import ClaimOutcome, QuotaSnapshot
from model_gateway.api import admin_accounts
from model_gateway.config.schemas import AppConfig
from model_gateway.core.resources import ResourceManager
from model_gateway.main import _maybe_start_ops
from model_gateway.ops import builtin as ops_builtin
from model_gateway.ops import runner as ops_runner
from model_gateway.ops.base import OpResult
from model_gateway.upstream.buddy import product as buddy
from tests.integration.conftest import chat_res, gateway_config

#: 假凭据探针：出现在凭据/配置里，逐个响应断言它没被发出去（铁律 1 / §22.8-8）
SECRET = "SECRET-DO-NOT-LEAK-m7-3c"

TOKENS = {"access_tokens": [{"id": "t-user", "value": "gw-user"}]}


# ---------- 基建 ----------

def _declared() -> tuple[str, ...]:
    """两个动作声明的产品并集（与 `main._maybe_start_ops` 同一算式，不是测试自编的）。"""
    op_claim = ops_builtin.OPERATIONS[ops_builtin.product_claim.OPERATION_ID]
    op_balance = ops_builtin.OPERATIONS[ops_builtin.query_balance.OPERATION_ID]
    return tuple(dict.fromkeys(op_claim.supported_products + op_balance.supported_products))


def _ops_runtime(tmp_path) -> types.SimpleNamespace:
    """`_maybe_start_ops` 需要的最小运行时（真 ResourceManager + 私有 usage_dir）。"""
    cfg = AppConfig.model_validate({
        "resources": [], "models": [],
        "gateway": {"zcode": {"claim_interval_seconds": 60}},
    })
    return types.SimpleNamespace(config=cfg, usage_dir=tmp_path / "usage",
                                 resources=ResourceManager())


def _capture_tick(monkeypatch, app) -> dict:
    """跑**生产装配入口**，抓下它交给调度器的那段 `run`（与 `test_m6_revive` 同一手法）。

    只桩 `Scheduler.start`（不真的等定时器），门/枚举/过滤/落盘全走生产代码。
    """
    captured: dict = {}

    def spy_start(self, run):
        captured["sched"] = self
        captured["run"] = run

    monkeypatch.setattr(ops_runner.Scheduler, "start", spy_start)
    _maybe_start_ops(app)
    return captured


def _jsonl_rows(usage_dir: Path) -> list[dict]:
    path = usage_dir / f"ops-results-{dt.date.today():%Y%m%d}.jsonl"
    assert path.exists(), f"cron 轮次结果未落盘：{path}"
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def _no_sleep(_s: float) -> None:
    """账号间节奏不在被测范围内（`run_once` 默认 1.2s + 抖动，测试里不真睡）。"""


async def _wait(predicate, timeout: float = 20.0, interval: float = 0.1) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return False


# ============ BD1：定时腿必须看账号启用位（设计书 §0-4 BUG-3）============

async def test_cron_leg_skips_disabled_account(tmp_path, monkeypatch):
    """🔴 停用账号在**定时腿**上也不参与运营，且在落盘报告里被点名跳过（BD1）。

    手动腿一直传 `enabled_of`（`api/admin_accounts.py::account_claim`），cron 两条腿原先
    不传（`ops/runner.py:462-470`「给了才跳过」）→ 界面开关的
    「账号停用：运营执行跳过」（`web/static/js/pages/accounts.js` 行内 title）
    只对一半入口成立。本用例跑的是 `_maybe_start_ops` 交给调度器的那段真 `run`。
    """
    store.commit_login("buddy", "bd1-on", {"token": "T-ON"}, {})
    store.commit_login("buddy", "bd1-off", {"token": SECRET}, {"enabled": False})
    assert admin_accounts.cron_enabled_of("bd1-on") is True
    assert admin_accounts.cron_enabled_of("bd1-off") is False

    claims: list[str] = []
    balances: list[str] = []

    async def fake_claim(account, *, manual=False, runtime=None):
        claims.append(account)
        return OpResult(account, "success")

    async def fake_balance(account, *, manual=False, runtime=None):
        balances.append(account)
        return OpResult(account, "inactive", "（测试假体，不触网）")

    # 只换执行体，**保留真实声明与真实过滤**（enabled_of 正是挂在声明枚举之后的那道）
    monkeypatch.setitem(ops_builtin.OPERATIONS, "claim",
                        dataclasses.replace(ops_builtin.OPERATIONS["claim"], run=fake_claim))
    monkeypatch.setitem(ops_builtin.OPERATIONS, "query_balance",
                        dataclasses.replace(ops_builtin.OPERATIONS["query_balance"],
                                            run=fake_balance))

    app = types.SimpleNamespace(state=types.SimpleNamespace(runtime=_ops_runtime(tmp_path)))
    captured = _capture_tick(monkeypatch, app)
    assert "run" in captured, "调度器没拿到批量任务"
    await captured["run"]()

    assert claims == ["bd1-on"], f"定时腿发起了停用账号：{claims}"
    assert balances == ["bd1-on"], f"额度腿发起了停用账号：{balances}"
    rows = _jsonl_rows(tmp_path / "usage")
    claim_row = rows[0]
    assert claim_row["success"] == ["bd1-on"]
    assert "bd1-off" in claim_row["skipped"], f"停用账号未落进跳过名单：{claim_row}"
    assert claim_row["no_participants"] is False
    assert SECRET not in json.dumps(rows), "落盘行不得带出凭据"


async def test_cron_leg_without_enabled_of_still_claims_disabled(tmp_path, monkeypatch):
    """🔴 BD1 的**在册反向对照**（设计书 §8-3③ 的撤证）：不传 `enabled_of` 时停用账号**仍被领取**。

    这里的调用形态 `run_once(operation=…, runtime=…)` 就是修前 `main.py:180/185` 两行的
    字面样子。把它固定在仓库里，是为了让"摘掉 wiring"这件事**永远双向可查**：
    正向那条转红 + 本条继续为真 = 有人撤了修复；两条同时变 = 语义被整体改掉，必须重新裁决。
    （`sleep=_no_sleep` 只是不真睡 1.2s 节奏，不参与判据。）
    """
    store.commit_login("buddy", "bd1-on", {"token": "T-ON"}, {})
    store.commit_login("buddy", "bd1-off", {"token": "T-OFF"}, {"enabled": False})
    seen: list[str] = []

    async def fake_claim(account, *, manual=False, runtime=None):
        seen.append(account)
        return OpResult(account, "success")

    op = dataclasses.replace(ops_builtin.OPERATIONS["claim"], run=fake_claim)
    report = await ops_runner.run_once(operation=op, runtime=_ops_runtime(tmp_path),
                                       sleep=_no_sleep)      # ← 撤掉 enabled_of 的原调用
    assert sorted(report.success) == ["bd1-off", "bd1-on"], (
        f"反向对照本身失效（停用账号已经不参与了？那 BD1 的门就白加）：{report.to_dict()}")
    assert sorted(seen) == ["bd1-off", "bd1-on"], f"执行体确实被叫到了停用账号：{seen}"


def test_cron_enabled_of_reads_the_same_bit_as_the_switch():
    """`cron_enabled_of` 与界面开关/手动腿**同一个读面**（缺省与非布尔 = 启用；False = 停用）。

    另断两条边界：认不出归属产品的账号 → **按停用处理**（fail closed，不知道就不发起），
    以及跨产品同名账号读的是 `product_of_account` 认定的那一个（与执行体同源，见函数注）。
    """
    store.commit_login("buddy", "def-on", {"token": "T"}, {})
    store.commit_login("buddy", "off-1", {"token": "T"}, {"enabled": False})
    store.commit_login("buddy", "weird-1", {"token": "T"}, {"enabled": "yes-please"})
    assert admin_accounts.cron_enabled_of("def-on") is True
    assert admin_accounts.cron_enabled_of("off-1") is False
    # 非布尔一律按启用（`_enabled_of` 的既有口径：不误伤旧数据）—— 界面显示的是同一个值
    assert admin_accounts.cron_enabled_of("weird-1") is True
    assert store.load_meta(store.product_root("buddy"), "weird-1")["enabled"] == "yes-please"
    # 认不出产品 = 不知道 → 不据此发起运营
    assert admin_accounts.cron_enabled_of("ghost-not-registered") is False


# ============ BD8：额度快照不得等到重启（设计书 §0-4 BUG-2）============

async def test_ops_scheduler_starts_with_zero_accounts(tmp_path, monkeypatch):
    """🔴 启动时 0 账号**也要起调度器**（BD8：门从"启动一次"改到"每一轮"）。

    修前：`_maybe_start_ops` 在 `refresh_quotas()` 之前就有 `if not accounts: return None`
    → 全新安装（0 账号）接入第一个账号后，`runtime.json` 的唯一写者
    （`ops/builtin/query_balance.py::_write_quota_cache`）再也没有机会运行，额度列恒
    「尚未刷新」，直到用户重启网关。
    ⚠️ 同时断"枚举不可用仍不起调度"那道 fail-closed 门**没有被顺手撤掉**。
    """
    assert ops_runner.all_accounts(_declared()) == [], "前置事实：此刻一个账号都没有"
    app = types.SimpleNamespace(state=types.SimpleNamespace(runtime=_ops_runtime(tmp_path)))
    captured = _capture_tick(monkeypatch, app)

    assert getattr(app.state, "ops_scheduler", None) is not None, \
        "0 账号时调度器仍没起来 —— 接入第一个账号后要等重启才有额度快照（BUG-2 复活）"
    assert "run" in captured, "起了调度器却没把批量任务交出去"

    # 门保留核对：枚举面坏掉（数据目录不可解析）时仍然不起、且留痕
    def _boom(_products):
        raise OSError("账号目录读不动（假体）")

    monkeypatch.setattr(ops_runner, "all_accounts", _boom)
    app2 = types.SimpleNamespace(state=types.SimpleNamespace(runtime=_ops_runtime(tmp_path)))
    assert _maybe_start_ops(app2) is None
    assert getattr(app2.state, "ops_scheduler", None) is None, \
        "枚举失败那道 fail-closed 门被撤掉了（坏环境会起一个每轮都抛异常的定时器）"


async def test_empty_tick_writes_nothing_then_first_account_gets_snapshot(tmp_path, monkeypatch):
    """🔴 BD8 主判据：空轮**无事发生**（不落盘、不抛），接入第一个账号后的下一轮就有快照。

    全程同一个进程、同一次 `_maybe_start_ops`：这正是"用户接入第一个账号"的真实时序
    （修前这段时序永远等不到 `runtime.json`）。
    """
    async def fake_quota(cred, meta):
        return QuotaSnapshot(state="available", source="fake", detail="余量 100（测试假体）")

    async def fake_claim(cred, meta, *, precheck=False):
        return ClaimOutcome(category="success", detail="（测试假体，不触网）")

    # 假**产品钩子**（网络面），但 `query_balance` 动作本体与它的落盘写者都是真的
    monkeypatch.setitem(buddy._HOOKS, "quota", fake_quota)
    monkeypatch.setitem(buddy._HOOKS, "claim", fake_claim)

    app = types.SimpleNamespace(state=types.SimpleNamespace(runtime=_ops_runtime(tmp_path)))
    captured = _capture_tick(monkeypatch, app)
    usage = tmp_path / "usage"

    await captured["run"]()                      # ① 0 账号的一轮
    assert not usage.exists() or list(usage.iterdir()) == [], \
        "空 tick 写了噪音文件（60s 间隔 ≈ 2880 行/天，把真正的运营记录埋掉）"

    store.commit_login("buddy", "first-ever", {"token": SECRET}, {})   # ② 接入第一个账号
    await captured["run"]()                      # ③ 下一轮（不重启）

    snap = store.read_runtime("buddy", "first-ever")
    assert "quota" in snap, f"接入后仍没有额度快照：{snap}"
    assert snap["quota"]["state"] == "available" and snap["quota"]["source"] == "fake"
    assert SECRET not in json.dumps(snap), "额度快照不得回显凭据"
    assert (store.product_root("buddy") / "first-ever" / "runtime.json").exists()


async def test_gateway_process_writes_quota_snapshot_without_restart(
        vendor, make_gateway, monkeypatch):
    """🔴 BD8 进程级复现：真网关（随机端口、间隔 1s）0 账号起步 → 接入 → 自行出快照。

    与上一条的分工：那条抓时序，这条抓**装配面真的把定时器起起来了**
    （`create_app` 的 startup 钩子 → `_maybe_start_ops` → `Scheduler` 的 1s 周期），
    账号是在进程活着的时候才被接入的，全程不重启、不发一个请求。
    """
    cfg = gateway_config(vendor.port, models=[chat_res("A")],
                         gateway={**TOKENS, "zcode": {"claim_interval_seconds": 1}})
    gw = await make_gateway(cfg)

    assert getattr(gw.app.state, "ops_scheduler", None) is not None, \
        "0 账号的网关没起运营定时器（BUG-2：接入第一个账号后额度恒「尚未刷新」）"
    await asyncio.sleep(2.5)                     # 至少跑过两轮空轮
    assert list(gw.usage_dir.glob("ops-results-*.jsonl")) == [], \
        "0 账号时运营定时器仍在落盘噪音（门撤到每轮的实现没生效）"

    async def fake_quota(cred, meta):
        return QuotaSnapshot(state="exhausted", source="fake", detail="余量 0（测试假体）")

    async def fake_claim(cred, meta, *, precheck=False):
        return ClaimOutcome(category="success", detail="（测试假体，不触网）")

    monkeypatch.setitem(buddy._HOOKS, "quota", fake_quota)
    monkeypatch.setitem(buddy._HOOKS, "claim", fake_claim)
    store.commit_login("buddy", "onboarded", {"token": SECRET}, {})

    rt_path = store.product_root("buddy") / "onboarded" / "runtime.json"
    assert await _wait(rt_path.exists), (
        "接入第一个账号后 20s（=20 个 tick）仍未写出 runtime.json —— 进程不重启就拿不到额度快照")
    snap = json.loads(rt_path.read_text(encoding="utf-8"))
    assert snap["quota"]["state"] == "exhausted" and snap["quota"]["source"] == "fake"
    assert SECRET not in rt_path.read_text(encoding="utf-8")
    assert await _wait(lambda: list(gw.usage_dir.glob("ops-results-*.jsonl"))), \
        "有账号后 cron 轮次结果没落盘（顶栏红点的事实源丢了）"


# ============ BD3a：账号视图里的只读资源关联（设计书 §6）============

def _resource_row(rid: str, *, product: str, account_ref: str, enabled: bool = True) -> dict:
    """产品资源行（§22.5-2：`api_key` 故意填值 —— 出站绝不用它，界面也绝不该看见它）。"""
    return {"id": rid, "name": f"资源{rid}", "vendor": "", "preset": "",
            "account": account_ref, "product": product, "account_ref": account_ref,
            "protocol": "openai", "base_url": "http://127.0.0.1:9/v1",
            "api_key": SECRET, "enabled": enabled, "access_mode": "api"}


async def test_view_resource_join_materialised_and_absent(vendor, make_gateway, client):
    """🔴 BD3a：`resource` = 该账号物化成的资源 `[{id, enabled}]`；没有则为 `[]`（≠ 未知）。

    join 谓词 = `product` + `account_ref`（与 `_quota_summary` 同源，`_matched_resources`），
    所以"另一账号"与"另一产品的同名账号"都不得混进来；
    🔴 载荷只出 `id`/`enabled` —— 配置里的 `api_key` 一个字也不得出现在视图（铁律 1）。
    """
    cfg = gateway_config(vendor.port, models=[chat_res("A")], gateway=TOKENS)
    cfg["resources"] += [
        _resource_row("res-r1", product="buddy", account_ref="acc-r1"),
        _resource_row("res-r2", product="buddy", account_ref="acc-r1", enabled=False),
        _resource_row("res-other", product="buddy", account_ref="acc-r-other"),
        _resource_row("res-trae-same", product="trae", account_ref="acc-r1"),
    ]
    gw = await make_gateway(cfg)
    store.commit_login("buddy", "acc-r1", {"token": SECRET}, {})
    store.commit_login("buddy", "acc-r-other", {"token": SECRET}, {"enabled": False})
    store.commit_login("buddy", "acc-plain", {"token": SECRET}, {})
    store.commit_login("trae", "acc-r1", {"access_token": SECRET}, {})

    resp = await client.get(f"{gw.base_url}/admin/api/accounts")
    assert resp.status_code == 200, resp.text
    assert SECRET not in resp.text, "视图泄露了配置 api_key / 凭据"
    data = resp.json()

    def acc(pid: str, name: str) -> dict:
        p = next(x for x in data["products"] if x["id"] == pid)
        return next(a for a in p["accounts"] if a["name"] == name)

    joined = acc("buddy", "acc-r1")
    assert joined["resource"] == [{"id": "res-r1", "enabled": True},
                                  {"id": "res-r2", "enabled": False}], (
        f"资源关联不对（顺序 = 配置顺序；须含停用资源、不得含别家）：{joined['resource']}")
    assert joined["quota"]["resources"] == ["res-r1", "res-r2"], "quota join 与新增字段不同源"
    # 另一账号只认到**自己**那一条（谓词按账号名筛，不是"同产品全带出"）
    assert acc("buddy", "acc-r-other")["resource"] == [{"id": "res-other", "enabled": True}]
    # 完全没物化资源的账号 → 空列表（"确实没有"），与下一条用例的"读不动 = None"分得开
    assert acc("buddy", "acc-plain")["resource"] == []
    # 同账号名跨产品：trae 的 acc-r1 只认到 trae 的资源，不被 buddy 的两条污染
    assert acc("trae", "acc-r1")["resource"] == [{"id": "res-trae-same", "enabled": True}]


async def test_view_survives_unreadable_config_with_resource_unknown(vendor, make_gateway, client):
    """🔴 BD3a 的 fail-closed：配置读不动时视图仍 200，`resource` 为 `None`（未知 ≠ 没有）。

    两种"读不动"都走一遍：① 根本没有运行态（`runtime=None`）；② `runtime.config` 取值就抛。
    ② 同时钉住邻居 `quota` 摘要的同一处置（原先 `_quota_summary` 裸读配置 = 一格读不动
    把整页冒穿成 500，与账号页"必须看得见"的定位相反）。
    """
    gw = await make_gateway(gateway_config(vendor.port, models=[chat_res("A")],
                                           gateway=TOKENS))
    store.commit_login("buddy", "acc-quiet", {"token": SECRET}, {})
    real_runtime = gw.runtime

    class _Unreadable:
        @property
        def config(self):                                     # 配置读不动（假体）
            raise RuntimeError("配置读不动（测试假体）")

    for stub, label in ((None, "没有运行态"), (_Unreadable(), "config 取值即抛")):
        gw.app.state.runtime = stub
        resp = await client.get(f"{gw.base_url}/admin/api/accounts")
        assert resp.status_code == 200, \
            f"{label}：视图被冒穿 → {resp.status_code} {resp.text[:200]}"
        body = resp.json()
        p = next(x for x in body["products"] if x["id"] == "buddy")
        entry = next(a for a in p["accounts"] if a["name"] == "acc-quiet")
        assert "resource" in entry and entry["resource"] is None, \
            f"{label}：resource 应为 None（未知），不是 []（确实没有）：{entry.get('resource')}"
        assert entry["quota"]["state"] == "unknown" and entry["quota"]["resources"] == [], \
            f"{label}：额度摘要未按未知呈现：{entry['quota']}"
        assert entry["name"] == "acc-quiet" and body["counts"]["accounts"] >= 1, \
            f"{label}：账号本体仍须可见（读不动的只是资源/额度这两格）"
        assert SECRET not in resp.text, f"{label}：失败分支也不得带出凭据"

    # 运行态回来后立即恢复成**真列表**（"未知"不是被缓存洗住的死态）
    gw.app.state.runtime = real_runtime
    resp = await client.get(f"{gw.base_url}/admin/api/accounts")
    assert resp.status_code == 200, resp.text
    entry = next(a for a in next(x for x in resp.json()["products"] if x["id"] == "buddy")
                 ["accounts"] if a["name"] == "acc-quiet")
    assert entry["resource"] == [], f"读得动了却还停在未知：{entry['resource']}"
