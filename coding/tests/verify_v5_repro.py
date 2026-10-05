"""🔴 临时复现件（学习轮 V5 · 2026-10-04）—— 不是在册判据，跑完保留备查，**不入库**。

目的：把 `docs/research/27-DSH插件网关与模型清单调研-结论.md` §3 的 **L10 / L8** 两条
从「读码推断」升级成**行为实测**，并且独立复验报告原文引用的我方代码事实（不抄报告结论）。

实验：
  ① L10-a 建议腿把「两个真实不同的带日期实体」缝成同一个网关模型（`_enum_suggest`）；
  ② L10-b `(资源, 供应商模型名)` 组合唯一性校验**按字面**判 —— 它不会因为日期规范化而误判重复
     （报告里这条怀疑被**证伪**，附对照组）；但同一网关模型内可以安静地同时挂两条不同快照；
  ③ L10-c 入站 `resolve_request_model`：工具请求 `glm-5.2-20250815` ⇒ 被静默服务成 `glm-5.2`；
  ④ L10-d 目录里若同时在册「基础名 + 带日期名」两条实体 ⇒ 带日期那条的**破折号形态**被基础名
     遮蔽，且结果**取决于条目书写顺序**（`_norm` first-wins）；
  ⑤ L10-e 现状核对：内置目录里"日期=别名"是**显式声明**的（5 条），去掉全局剥离需要补的
     aliases 数量 = **0 新增**（已存在的 5 条足以覆盖今天 :8300 上唯一那条真实命中）。
  ⑥ L8-a `PUT /admin/api/config`：把**别的 Key 的掩码**/残缺掩码回传 ⇒ 照存为真值（读盘核对）；
     并证明 `mask_key(掩码) == 掩码`（**不动点**）⇒ 之后再也不会被任何一环认出来；
  ⑦ L8-b 存下之后真实走一次出站：上游回 401，客户端看到的是供应商原话，
     全链路（响应体 / 事件流水）**没有任何一处**提到"这看起来是脱敏显示"；
  ⑧ L8-c 规则该覆盖哪些字段：`gateway.access_tokens[].value` 在 GET 里**根本不脱敏**
     （⇒ 没有回写洞），账号侧目录行**不含凭据字段**（⇒ 无此形状）。

⚠️ 边界（诚实申报）：
  - 零真实网络：上游 = 本地 FakeVendor（随机端口）；配置/事件全落本用例 tmp 树；**:8300 零接触**。
  - 401 的措辞 `Incorrect API key provided` 是**按真实供应商公开行为建模**，不是实测供应商答复。
  - 本文件不改任何既有源码 / 既有测试；断言钉的是**当前基线行为**（含缺陷），
    把 matcher 的日期剥离摘掉后重跑本文件，①③④ 会翻红 = 那三条的撤证。

跑法：
    cd coding && .venv/bin/python -m pytest -q tests/verify_v5_repro.py -s
"""

from __future__ import annotations

import asyncio
import contextlib
import re

import httpx
import pytest
import uvicorn
import yaml

from model_gateway.config.schemas import AppConfig
from model_gateway.enums.matcher import (
    BUILTIN_ENTRIES, EnumEntry, EnumPool, normalize_name,
    resolve_request_model,
)
from model_gateway.stats.events import mask_key
from tests.integration.conftest import GatewayHandle
from tests.integration.fakevendor import Err, FakeVendor, start_fake_vendor


def say(tag: str, **kv) -> None:
    print(f"\n[{tag}] " + "；".join(f"{k}={v}" for k, v in kv.items()))


# ---------------------------------------------------------------- 夹具（自带，tests/ 根不继承 integration/conftest）

@pytest.fixture
async def vendor():
    fake = FakeVendor()
    server, task, wait_ready = start_fake_vendor(fake)
    fake.port = await wait_ready()
    try:
        yield fake
    finally:
        server.should_exit = True
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=10)


@pytest.fixture
async def make_gw(tmp_path):
    from model_gateway.main import create_app

    made: list[GatewayHandle] = []
    n = 0

    async def _make(cfg_dict: dict) -> GatewayHandle:
        nonlocal n
        config_path = tmp_path / f"v5cfg-{n}.yaml"
        usage_dir = tmp_path / f"v5usage-{n}"
        config_path.write_text(yaml.safe_dump(cfg_dict, allow_unicode=True), encoding="utf-8")
        app = create_app(config_path=config_path, usage_dir=usage_dir,
                         enums_path=tmp_path / f"v5enums-{n}.yaml")
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0,
                                               log_level="warning"))
        task = asyncio.get_running_loop().create_task(server.serve())
        for _ in range(500):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started, "网关启动超时"
        port = server.servers[0].sockets[0].getsockname()[1]
        made.append(GatewayHandle(f"http://127.0.0.1:{port}", config_path, usage_dir,
                                  app, server, task))
        n += 1
        return made[-1]

    yield _make
    for gw in made:
        gw._server.should_exit = True
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(gw._task, timeout=10)


@pytest.fixture
async def hclient():
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0), trust_env=False) as c:
        yield c


# ---------------------------------------------------------------- 配置构造（Key 用测试替身，非真实凭据）

REAL_1 = "sk-TESTUPSTREAM-AAA0001"       # 资源 1 的测试替身 Key（不打印）
REAL_2 = "sk-TESTUPSTREAM-BBB0002"       # 资源 2 的测试替身 Key（不打印）
DATE_TAIL = re.compile(r"-\d{4,8}$")     # 与 matcher._DATE_SUFFIX 同形


def res(rid: str, key: str) -> dict:
    return {"id": rid, "name": rid, "access_mode": "api", "protocol": "openai",
            "base_url": "http://127.0.0.1:{PORT}/v1", "api_key": key}


def cfg_one_res(rid: str, key: str, model: str, sys_model: str = "glm-5.2") -> dict:
    return {"resources": [res(rid, key)],
            "models": [{"name": sys_model, "endpoint": "chat",
                        "resources": [{"resource": rid, "model": model}]}]}


# ================================================================ L10

def test_l10_a_suggestion_leg_merges_two_dated_entities():
    """① 两个**互不相同**的供应商快照 id（都不在目录、也不是别名）被建议腿挂到同一个网关模型。"""
    from model_gateway.api.admin_accounts import _enum_suggest

    pool = EnumPool(list(BUILTIN_ENTRIES))
    cfg_names = {"glm-5.2"}
    ids = ["glm-5.2-0731", "glm-5.2-0815", "glm-5.2-20250731", "glm-5.2-2507"]
    got = {i: _enum_suggest(pool, cfg_names, i) for i in ids}
    for i in ids:
        say("L10-a", 供应商id=i, normalize=normalize_name(i), 建议=(got[i] or {}).get("name"),
            via=(got[i] or {}).get("via"), conf=(got[i] or {}).get("confidence"))
    names = {(g or {}).get("name") for g in got.values()}
    assert names == {"glm-5.2"}, "基线事实：四条不同的日期快照全部被建议成同一个网关模型"
    assert all((g or {}).get("via") == "normalized" for g in got.values())


def test_l10_b_combo_uniqueness_is_verbatim_report_doubt_refuted():
    """② 报告怀疑「组合唯一性把两个真实不同模型判成重复」—— **证伪**：判据按字面。

    对照组（同一条 `(res-A, glm-5.2-0731)` 写两遍）确实报 `warnings` ⇒ 校验本身活着，
    只是它比的是字面串，不受 `normalize_name` 影响。
    """
    base = {"id": "res-A", "access_mode": "api", "protocol": "openai",
            "base_url": "http://127.0.0.1:1/v1", "api_key": "sk-TESTONLY-000000"}
    two_dated = {
        "resources": [base],
        "models": [{"name": "glm-5.2", "endpoint": "chat", "resources": [
            {"resource": "res-A", "model": "glm-5.2-0731"},
            {"resource": "res-A", "model": "glm-5.2-0815"},
        ]}],
    }
    cfg = AppConfig.model_validate(two_dated)
    say("L10-b", 两个不同日期快照_条目数=len(cfg.models[0].resources),
        告警条数=len(cfg.warnings), 告警=cfg.warnings)
    assert len(cfg.models[0].resources) == 2 and cfg.warnings == []

    dup = {
        "resources": [base],
        "models": [{"name": "glm-5.2", "endpoint": "chat", "resources": [
            {"resource": "res-A", "model": "glm-5.2-0731"},
            {"resource": "res-A", "model": "glm-5.2-0731"},
        ]}],
    }
    cfg2 = AppConfig.model_validate(dup)
    say("L10-b对照", 同组合写两遍_条目数=len(cfg2.models[0].resources),
        告警条数=len(cfg2.warnings))
    assert len(cfg2.models[0].resources) == 1 and len(cfg2.warnings) == 1


def test_l10_c_inbound_request_for_dated_snapshot_is_served_by_base():
    """③ 入站：工具请求 `glm-5.2-20250815`（一个目录里根本没有、也不该猜的实体）
       ⇒ 被静默解析成 `glm-5.2` 并真的会发出去（不是 404，不是候选）。"""
    from model_gateway.config.schemas import SystemModel

    models = [SystemModel.model_validate({"name": "glm-5.2", "endpoint": "chat",
                                         "resources": []})]
    for req in ["glm-5.2-20250815", "GLM_5.2_0815", "glm-5.2-0731"]:
        m, cands = resolve_request_model(req, models, EnumPool(list(BUILTIN_ENTRIES)))
        say("L10-c", 请求名=req, 解析到=(m.name if m else None), 候选条数=len(cands))
        assert m is not None and m.name == "glm-5.2", "基线事实：带日期的请求名被基础模型接走"

    # 反证形状：如果这条日期实体本该是**独立**网关模型，它必须在 models[] 里在册
    m2, _ = resolve_request_model("glm-5.2-20250815",
                                  models + [SystemModel.model_validate(
                                      {"name": "glm-5.2-20250815", "endpoint": "chat",
                                       "resources": []})],
                                  EnumPool(list(BUILTIN_ENTRIES)))
    say("L10-c反证", 在册独立模型时解析到=(m2.name if m2 else None))
    assert m2 is not None and m2.name == "glm-5.2-20250815"


def test_l10_d_directory_order_decides_which_entity_survives():
    """④ 目录里同时在册「基础名 + 带日期名」⇒ `_norm` first-wins，
       带日期实体的**破折号形态**被先写那条遮蔽；换顺序结果就反过来。"""
    pool_a = EnumPool([EnumEntry("glm-5.2"), EnumEntry("glm-5.2-0731")])
    pool_b = EnumPool([EnumEntry("glm-5.2-0731"), EnumEntry("glm-5.2")])
    probe = "glm-5-2-0731"
    ra, rb = pool_a.match(probe), pool_b.match(probe)
    say("L10-d", 输入=probe, 基础名在前=ra, 带日期在前=rb)
    assert ra[0] == "glm-5.2" and rb[0] == "glm-5.2-0731"
    assert ra != rb, "基线事实：同一个输入，命中哪条实体取决于目录书写顺序"


def test_l10_e_dated_aliases_are_already_declared_explicitly():
    """⑤ 「日期=别名」在内置目录里是**逐条显式声明**的 ⇒ 去掉全局剥离要补的 aliases = 0。"""
    dated_alias_pairs = [(e.name, a) for e in BUILTIN_ENTRIES for a in e.aliases
                         if DATE_TAIL.search(a)]
    say("L10-e", 显式日期别名条数=len(dated_alias_pairs), 清单=dated_alias_pairs)
    assert len(dated_alias_pairs) == 5
    pool = EnumPool(list(BUILTIN_ENTRIES))
    for _name, a in dated_alias_pairs:
        got = pool.match(a)
        say("L10-e逐条", 别名=a, 命中=got[0], 置信=got[1], 规范化串=normalize_name(a))
        assert got[1] == 0.9, "这些行走的是 alias(0.9)，不是 strip 后的 normalized(0.7)"


# ================================================================ L8

async def _masked_view(gw):
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), trust_env=False) as c:
        r = await c.get(f"{gw.base_url}/admin/api/config")
        assert r.status_code == 200
        return r.json()


async def _put(gw, body):
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), trust_env=False) as c:
        r = await c.put(f"{gw.base_url}/admin/api/config", json=body)
        return r.status_code, r.json()


async def test_l8_a_foreign_or_truncated_mask_is_stored_as_the_real_key(make_gw, vendor):
    """⑥（S-2 后，2026-10-05）：GET 出口是**显式哨兵** `mgw-masked:sk-****xxxx` ——
    界面原样传回的哨兵被还原成明文（控制组）；「别的 Key 的哨兵粘给 r2」不会被还原
    （还原按 id 配对，粘错位=字面保存但**形态可识别**，用户/运维一眼能看出存错了）；
    残缺哨兵同理按字面保存。旧世界的不动点（`mask_key(掩码)==掩码` ⇒ 存下后永认不出）
    随哨兵化被消灭，原断言见 git 历史。"""
    cfg = {"resources": [res("r1", REAL_1), res("r2", REAL_2)],
           "models": [{"name": "glm-5.2", "endpoint": "chat", "resources": [
               {"resource": "r1", "model": "glm-5.2"},
               {"resource": "r2", "model": "glm-5.2"}]}]}
    cfg["resources"][0]["base_url"] = cfg["resources"][0]["base_url"].replace(
        "{PORT}", str(vendor.port))
    cfg["resources"][1]["base_url"] = cfg["resources"][1]["base_url"].replace(
        "{PORT}", str(vendor.port))
    gw = await make_gw(cfg)

    view = await _masked_view(gw)
    m1 = view["resources"][0]["api_key"]
    m2 = view["resources"][1]["api_key"]
    assert m1.startswith("mgw-masked:") and m2.startswith("mgw-masked:"), "GET 出口必须是哨兵形态"
    assert m1 != mask_key(REAL_1), "哨兵不再是 mask_key 输出 ⇒ 不动点消失"
    say("L8-a", 哨兵1=m1, 哨兵2=m2)

    body = dict(view)
    body["resources"][1]["api_key"] = m1          # 把 r1 的哨兵粘给 r2（错位）
    status, out = await _put(gw, body)
    say("L8-a保存", 状态码=status, 响应=out)
    assert status == 200

    on_disk = yaml.safe_load(gw.config_path.read_text(encoding="utf-8"))
    stored = {r["id"]: r["api_key"] for r in on_disk["resources"]}
    say("L8-a落盘", r1_还原明文=(stored["r1"] == REAL_1),
        r2_存的是r1的哨兵=(stored["r2"] == m1),
        r2_是否还是原真值=(stored["r2"] == REAL_2))
    assert stored["r1"] == REAL_1, "自己那份哨兵被正确还原（控制组：_unmask_resources 生效）"
    # 🔴 S-2 后的新语义：**任何哨兵形态都还原到该资源自己的现值** —— 粘错位的哨兵
    # 等价于「没改」，不可能把掩码串存成 Key（旧世界的不动点毁数据路径被消灭）。
    assert stored["r2"] == REAL_2, "错位哨兵 ⇒ 保留该资源现值（绝不存掩码串）"

    # 残缺哨兵（用户在输入框里删掉一位再存）⇒ 仍带前缀 ⇒ 保留现值（旧世界会把残缺串存成 Key）
    view2 = await _masked_view(gw)
    body2 = dict(view2)
    body2["resources"][0]["api_key"] = m1[:-1]    # 差一位的哨兵
    status2, out2 = await _put(gw, body2)
    on_disk2 = yaml.safe_load(gw.config_path.read_text(encoding="utf-8"))
    stored2 = {r["id"]: r["api_key"] for r in on_disk2["resources"]}
    say("L8-a残缺", 状态码=status2, 响应=out2,
        r1_保留明文现值=(stored2["r1"] == REAL_1),
        响应里有没有提到脱敏=any("脱敏" in str(x) for x in (out2 or {}).values()))
    assert status2 == 200 and stored2["r1"] == REAL_1, "残缺哨兵 ⇒ 保留现值（掩码串进不了凭据位）"


async def test_l8_b_failure_surface_says_nothing_about_masks(make_gw, vendor, hclient):
    """⑦（S-2 后）存了一个**错误的明文 Key** 再真调一次：客户端与事件流水里**只有供应商
    原话**，没有任何"这看起来是脱敏显示"。（旧写法"把残缺掩码当真 Key 存进去"在新语义下
    不可能——残缺哨兵仍带前缀 ⇒ 保留现值，掩码串永远进不了凭据位。）"""
    cfg = {"resources": [res("r9", REAL_2)],
           "models": [{"name": "glm-5.2", "endpoint": "chat",
                       "resources": [{"resource": "r9", "model": "glm-5.2"}]}]}
    cfg["resources"][0]["base_url"] = cfg["resources"][0]["base_url"].replace(
        "{PORT}", str(vendor.port))
    gw = await make_gw(cfg)

    bad = "sk-wrong-key-stored-on-purpose"
    body = yaml.safe_load(gw.config_path.read_text(encoding="utf-8"))
    body["resources"][0]["api_key"] = bad          # 用户手滑存错 Key（明文形状）
    status, _ = await _put(gw, body)
    assert status == 200

    vendor.set(bad, Err(status=401, err_type="invalid_request_error",
                        message="Incorrect API key provided"))
    r = await hclient.post(f"{gw.base_url}/v1/chat/completions",
                           json={"model": "glm-5.2",
                                 "messages": [{"role": "user", "content": "hi"}]})
    text = r.text
    say("L8-b", 客户端状态码=r.status_code, 响应体=text[:220],
        提到脱敏=("脱敏" in text), 提到mask=("mask" in text.lower()))
    assert r.status_code == 401
    assert "脱敏" not in text and "mask" not in text.lower()
    assert vendor.calls_for(bad), "掩码串被当作 Authorization 真发出去了"

    await gw.drain_events()
    events = gw.read_events()
    e = events[-1] if events else {}
    red = {k: v for k, v in e.items()}
    et = str(e)
    for secret in (REAL_1, REAL_2):        # 防御：绝不把测试替身 Key 打进输出
        et = et.replace(secret, "<redacted>")
        red = {k: (str(v).replace(secret, "<redacted>") if isinstance(v, str) else v)
               for k, v in red.items()}
    say("L8-b事件行字段", 键=sorted(e.keys()))
    say("L8-b事件", 整行=et[:400])
    assert e, "事件流水应有这一条"
    assert "脱敏" not in et
    assert REAL_2 not in et, "事件流水不得落明文 Key（既有脱敏纪律）"


async def test_l8_c_scope_is_api_key_only(make_gw, vendor, hclient):
    """⑧ 规则该覆盖哪些字段：`access_tokens[].value` 在 GET 里**不脱敏**（无回写洞），
       账号侧目录行不含凭据字段（形状不同，不是一条律的两个出口）。"""
    cfg = {"resources": [res("r1", REAL_1)],
           "gateway": {"access_tokens": [{"id": "tok-1", "name": "Trae",
                                          "value": "mg-TESTTOKEN-0001"}]},
           "models": [{"name": "glm-5.2", "endpoint": "chat",
                       "resources": [{"resource": "r1", "model": "glm-5.2"}]}]}
    cfg["resources"][0]["base_url"] = cfg["resources"][0]["base_url"].replace(
        "{PORT}", str(vendor.port))
    gw = await make_gw(cfg)

    masked_view = await _masked_view(gw)
    tok = masked_view["gateway"]["access_tokens"][0]["value"]
    say("L8-c", resources被脱敏=(masked_view["resources"][0]["api_key"] == mask_key(REAL_1)),
        access_token在GET里是否明文=(tok == "mg-TESTTOKEN-0001"))
    assert masked_view["resources"][0]["api_key"] != REAL_1
    assert tok == "mg-TESTTOKEN-0001", "接入密钥在默认 GET 里原样返回 ⇒ 没有掩码回写这条洞"

    # 账号侧（product 非空）资源：凭据不在配置文件里 ⇒ 掩码规则与它无关
    acct_cfg = {"resources": [{"id": "ra", "name": "号A", "product": "buddy",
                               "account_ref": "acct-a", "api_key": "",
                               "access_mode": "api", "protocol": "openai", "base_url": ""}],
                "models": [{"name": "glm-5.2", "endpoint": "chat",
                            "resources": [{"resource": "ra", "model": "glm-5.2"}]}]}
    gw2 = await make_gw(acct_cfg)
    v2 = await _masked_view(gw2)
    say("L8-c账号侧", api_key落盘值=v2["resources"][0]["api_key"],
        掩码=repr(mask_key(v2["resources"][0]["api_key"])))
    assert v2["resources"][0]["api_key"] == ""
