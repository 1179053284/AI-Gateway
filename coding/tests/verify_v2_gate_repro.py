"""🔴 临时复现件（学习轮 V2 · 2026-10-03）——不是在册判据，跑完保留备查，不入库。

目的：把 `docs/research/27-DSH插件网关与模型清单调研-结论.md` 的 **L2 / L7** 两条
从「读码 + grep 推断」升级成**实测复现**，逐条打出真实时间戳 / 真实秒数 / 真实调用次数。

三问对应三组用例：
  ① 一次 429 之后，同一个 (资源, 模型) 在多长时间内被排除出选择（`TestL2One429ExclusionWindow`）；
  ② 429 与 5xx / 超时走的是不是同一条冷却分支（`TestL2BranchComparison`）；
  ③ 我方会不会自己制造并发、两次发车之间有没有间隔（`TestL2NoDispatchPacing`）；
  ④ 目录取数：连续失败后 `read_cache` 返回什么、有没有冷却/去重、有没有「失败被当成功」的形状
     （`TestL7CatalogFailureState`）。

零真实网络：调度层走 `tests/unit/conftest.py` 的替身适配器；管理端只走
`httpx.ASGITransport`（不起端口、不打 :8300）；目录钩子用假钩子并**计数**。

⚠️ 本文件不修改任何既有源码/测试，只在自己的 tmp 数据树里写缓存文件。
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import httpx
import yaml

from model_gateway.accounts import catalog_cache, store
from model_gateway.accounts.types import ModelInfo
from model_gateway.api import admin_accounts as aa
from model_gateway.core.errors import ErrorClass, ErrorClassifier, UpstreamError
from model_gateway.core.ir import IRRequest
from model_gateway.core.scheduler import CallCtx, GatewayError
from tests.unit.conftest import build_runtime, chat_model, http_err, make_config

SECRET = "SECRET-V2REPRO-DO-NOT-LEAK-7c11"

# 429 的两种语义（DSH 插件 `model-gate.ts:14-15` 原文形态：业务码在**顶层**，
# 不是 OpenAI 的 error.type —— 我方分类器只会看到 HTTP 429）
BODY_CONCURRENCY = '{"code":3009,"msg":"model concurrency limit exceeded"}'
BODY_QUOTA = '{"code":1005,"msg":"exceed quota limit"}'


def _p(tag: str, msg: str) -> None:
    print(f"[{tag}] {msg}")


def _err(status: int, body: str) -> UpstreamError:
    return UpstreamError(f"upstream {status}", status_code=status, error_body=body)


def _ir(model: str = "test-model") -> IRRequest:
    return IRRequest(system_model=model, endpoint="chat", stream=False,
                     body={"messages": [{"role": "user", "content": "hi"}]})


def _ctx(rt, model: str = "test-model") -> CallCtx:
    return CallCtx.new(None, model, "chat", False, rt.config)


class Clock:
    """可冻结 / 可推进的注入钟（`ResourceManager(clock=…)` 的唯一注入点）。"""

    def __init__(self, start: float = 1_000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class PacingAdapter:
    """出站替身：记录**发车时刻**、**同时在飞数**与调度侧 `in_flight` 峰值。"""

    def __init__(self, latency: float = 0.05):
        self.latency = latency
        self.script: dict[str, list] = {}
        self.dispatches: list[tuple[str, float]] = []      # (key, 发车时刻 monotonic)
        self.count: dict[str, int] = {}
        self._live = 0
        self.max_live = 0
        self.max_inflight_seen: dict[str, int] = {}

    async def _run(self, key: str, runtime, rid: str, vm: str) -> dict:
        self.dispatches.append((key, time.monotonic()))
        self.count[key] = self.count.get(key, 0) + 1
        self._live += 1
        self.max_live = max(self.max_live, self._live)
        st = runtime.resources.registry.get((rid, vm))
        if st is not None:
            self.max_inflight_seen[st.resource_id_str] = max(
                self.max_inflight_seen.get(st.resource_id_str, 0), st.in_flight)
        try:
            q = self.script.get(key)
            await asyncio.sleep(self.latency)
            if q:
                step = q.pop(0)
                if isinstance(step, BaseException):
                    raise step
                return step
            return {"choices": [{"message": {"role": "assistant", "content": "ok"},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        finally:
            self._live -= 1

    async def chat_nonstream(self, key, vendor_model, body, timeout):  # pragma: no cover
        raise NotImplementedError("必须经 attach() 绑上 runtime 后才可用")

    async def images_generate(self, key, vendor_model, body, timeout):  # pragma: no cover
        raise NotImplementedError


def attach(adapter: PacingAdapter, rt, rid_by_key: dict[str, str]) -> PacingAdapter:
    """把 runtime 塞进替身（`chat_nonstream` 需要它才读得到 `in_flight`）。"""

    async def chat(key, vendor_model, body, timeout):
        return await adapter._run(key, rt, rid_by_key[key], vendor_model)

    adapter.chat_nonstream = chat            # type: ignore[method-assign]
    return adapter


# ==================================================================
# L2 ①：一次 429 之后，同一 (资源, 模型) 被排除多久
# ==================================================================

class TestL2One429ExclusionWindow:

    async def test_l2_1_two_429_semantics_classify_identically(self):
        """插件断言「429 有两种语义」；我方分类器读不读得出这个区别？"""
        clf = ErrorClassifier([])
        c1 = clf.classify(_err(429, BODY_CONCURRENCY))
        c2 = clf.classify(_err(429, BODY_QUOTA))
        c3 = clf.classify(_err(429, '{"error":{"message":"too many requests"}}'))
        _p("L2-1", f"3009 并发配额 → {c1.value} | 1005 额度耗尽 → {c2.value} | 裸 429 → {c3.value}")
        assert c1 is c2 is c3 is ErrorClass.QUOTA, "三种 429 在我方全部收敛为同一个 QUOTA 档"

    async def test_l2_2_api_mode_exclusion_seconds(self):
        """api 档：真实跑一遍 429 链，打出冷却时间戳与「多长时间内选不到」。"""
        adapter = PacingAdapter(latency=0.0)
        adapter.script["sk-A"] = [_err(429, BODY_CONCURRENCY)] * 6      # 一直并发限流
        clock = Clock(1_000.0)
        rt = build_runtime(make_config(models=[chat_model("test-model", "A")]),
                           adapter, clock=clock)
        attach(adapter, rt, {"sk-A": "res-A"})
        wall0 = time.monotonic()
        boom: GatewayError | None = None
        try:
            await rt.scheduler.execute_chat(_ir(), _ctx(rt))
        except GatewayError as e:
            boom = e
        wall = time.monotonic() - wall0

        st = rt.resources.registry[("res-A", "vm-A")]
        _p("L2-2", f"上游调用次数={adapter.count['sk-A']}  本请求实耗墙钟={wall:.3f}s"
                   f"（quota_backoff 1s+2s 真睡在里面）")
        _p("L2-2", f"status={st.status}  注入钟 now={clock.t:.1f}  cooldown_until={st.cooldown_until:.1f}"
                   f" → 排除时长={st.cooldown_until - clock.t:.1f}s"
                   f"  剩余={rt.resources.cooldown_remaining_ms(st)}ms  连续失败计数 C={st.C}")
        _p("L2-2", f"终局给客户端：HTTP {boom.status_code} reason={boom.exhausted_reason}")
        clock.advance(59.9)
        got = rt.resources.pick_and_acquire("test-model", exclude=set())
        _p("L2-2", f"冷却中 +59.9s → pick_and_acquire 返回 "
                   f"{None if got is None else got.resource_id_str}（整条被排除）")
        assert got is None
        clock.advance(0.2)
        got2 = rt.resources.pick_and_acquire("test-model", exclude=set())
        _p("L2-2", f"冷却中 +60.1s → pick_and_acquire 返回 "
                   f"{None if got2 is None else got2.resource_id_str}（读时到期归位，无定时器）")
        assert got2 is not None and st.status == "active"

    async def test_l2_3_plan_mode_same_429_is_five_hours(self):
        """plan 档：同一条并发型 429、同一个分支，冷却是 18000s（= 5 小时）。"""
        adapter = PacingAdapter(latency=0.0)
        adapter.script["sk-A"] = [_err(429, BODY_CONCURRENCY)] * 6
        clock = Clock(1_000.0)
        cfg = make_config(
            resources=[{"id": "res-A", "name": "订阅号", "access_mode": "plan",
                         "protocol": "openai", "base_url": "http://fake.local/v1",
                         "api_key": "sk-A"}],
            models=[{"name": "test-model", "endpoint": "chat",
                     "resources": [{"resource": "res-A", "model": "vm-A"}]}],
            scheduling={"quota_backoff_base_seconds": 0.0},   # 只省掉真睡，不改冷却口径
        )
        rt = build_runtime(cfg, adapter, clock=clock)
        attach(adapter, rt, {"sk-A": "res-A"})
        try:
            await rt.scheduler.execute_chat(_ir(), _ctx(rt))
            raise AssertionError("plan 号一直 429 应当终局失败")
        except GatewayError:
            pass
        st = rt.resources.registry[("res-A", "vm-A")]
        secs = st.cooldown_until - clock.t
        _p("L2-3", f"access_mode=plan 的同一次并发型 429 → 排除 {secs:.0f}s = {secs/3600:.1f} 小时"
                   f"（读 `cooldown_seconds_plan`，与「额度耗尽等到明天」共用同一天花板）")
        assert secs == 18000.0

    async def test_l2_4_granularity_is_entry_not_whole_account(self):
        """冷却粒度是不是「号」？同一个号的另一个供应商模型名会不会被一起停掉。"""
        adapter = PacingAdapter(latency=0.0)
        adapter.script["sk-A"] = [_err(429, BODY_QUOTA)] * 6
        clock = Clock(1_000.0)
        cfg = make_config(
            resources=[{"id": "res-A", "name": "同一个号", "access_mode": "api",
                         "protocol": "openai", "base_url": "http://fake.local/v1",
                         "api_key": "sk-A"}],
            models=[
                {"name": "m-cool", "endpoint": "chat",
                 "resources": [{"resource": "res-A", "model": "vm-A"}]},
                {"name": "m-other", "endpoint": "chat",
                 "resources": [{"resource": "res-A", "model": "vm-Z"}]},   # 同号、另一模型
            ],
            scheduling={"quota_backoff_base_seconds": 0.0},
        )
        rt = build_runtime(cfg, adapter, clock=clock)
        attach(adapter, rt, {"sk-A": "res-A"})
        try:
            await rt.scheduler.execute_chat(_ir("m-cool"), _ctx(rt, "m-cool"))
        except GatewayError:
            pass
        cooled = rt.resources.registry[("res-A", "vm-A")]
        other = rt.resources.registry[("res-A", "vm-Z")]
        picked = rt.resources.pick_and_acquire("m-other", exclude=set())
        _p("L2-4", f"条目 (res-A, vm-A)={cooled.status}；同一个号的另一条目 (res-A, vm-Z)="
                   f"{other.status}；它此刻可被选中={picked is not None} → 排除的是条目，不是整号")
        assert cooled.status == "cooldown" and picked is other


# ==================================================================
# L2 ②：429 与 5xx / 超时是不是同一条冷却分支
# ==================================================================

class TestL2BranchComparison:

    async def test_l2_5_three_error_shapes_same_bench(self):
        cases = {
            "429 并发型(3009)": [_err(429, BODY_CONCURRENCY)] * 8,
            "429 额度型(1005)": [_err(429, BODY_QUOTA)] * 8,
            "5xx":              [http_err(500, "internal_server_error")] * 8,
            "超时(无状态码)":    [UpstreamError("read timeout", status_code=None)] * 8,
        }
        rows = []
        for label, script in cases.items():
            adapter = PacingAdapter(latency=0.0)
            adapter.script["sk-A"] = list(script)
            clock = Clock(1_000.0)
            rt = build_runtime(make_config(models=[chat_model("test-model", "A")]),
                               adapter, clock=clock)
            attach(adapter, rt, {"sk-A": "res-A"})
            t0 = time.monotonic()
            try:
                await rt.scheduler.execute_chat(_ir(), _ctx(rt))
            except GatewayError:
                pass
            wall = time.monotonic() - t0
            st = rt.resources.registry[("res-A", "vm-A")]
            rows.append((label, adapter.count["sk-A"], st.status,
                         st.cooldown_until - clock.t, st.C, wall))
        _p("L2-5", "分支对照（四种形态最终都落到同一个 `bench()` + 同一个 `cooldown_seconds_for()`）：")
        _p("L2-5", f"{'形态':<16}{'上游次数':>8}{'status':>10}{'排除秒数':>10}{'C':>4}{'墙钟s':>8}")
        for label, n, status, secs, c, wall in rows:
            _p("L2-5", f"{label:<18}{n:>8}{status:>12}{secs:>12.0f}{c:>4}{wall:>9.3f}")
        assert {r[3] for r in rows} == {60.0}, "四种形态的冷却秒数完全相同 = 没有并发/额度分档"
        assert rows[0][1] == 3 and rows[2][1] == 2, "429 比 5xx 多打一次上游、多睡 3 秒"


# ==================================================================
# L2 ③：我方会不会自己制造并发 / 两次发车之间有没有节奏
# ==================================================================

class TestL2NoDispatchPacing:

    async def test_l2_6_concurrent_requests_stack_on_one_entry(self):
        """x=2、池里只有一条可用 ⇒ 三条并发请求全压在同一个 (资源,模型) 上，间隔 ~0ms。"""
        adapter = PacingAdapter(latency=0.05)
        clock = Clock(1_000.0)
        rt = build_runtime(make_config(models=[chat_model("test-model", "A")]),
                           adapter, clock=clock)
        attach(adapter, rt, {"sk-A": "res-A"})
        x = rt.resources.x
        await asyncio.gather(*[rt.scheduler.execute_chat(_ir(), _ctx(rt)) for _ in range(3)])
        ts = [t for _k, t in adapter.dispatches]
        gaps = [(ts[i + 1] - ts[i]) * 1000 for i in range(len(ts) - 1)]
        _p("L2-6", f"x={x}  池成员=1  ⇒ 替身侧同时在飞峰值={adapter.max_live}  "
                   f"调度侧 in_flight 峰值={adapter.max_inflight_seen.get('资源A/vm-A')}  "
                   f"活跃组={ {k: len(v) for k, v in rt.resources._groups.items()} }")
        _p("L2-6", f"相邻两次发车间隔(ms)={[round(g, 2) for g in gaps]} → 最小="
                   f"{min(gaps):.2f}ms（我方没有任何按 (号×模型) 的发车间隔）")
        assert adapter.max_live == 3 and min(gaps) < 1.0

    async def test_l2_8_cooling_is_shared_across_system_models_of_one_entry(self):
        """同一个 (资源,供应商模型名) 条目被两个网关名复用时，冷却是**一份状态**还是两份？
        （决定"发车间隔"该记在哪个对象上：记错了就会各算各的。）"""
        adapter = PacingAdapter(latency=0.0)
        adapter.script["sk-A"] = [_err(429, BODY_CONCURRENCY)] * 6
        clock = Clock(1_000.0)
        cfg = make_config(
            resources=[{"id": "res-A", "name": "一个号", "access_mode": "api",
                         "protocol": "openai", "base_url": "http://fake.local/v1",
                         "api_key": "sk-A"}],
            models=[
                {"name": "gw-a", "endpoint": "chat",
                 "resources": [{"resource": "res-A", "model": "vm-A"}]},
                {"name": "gw-b", "endpoint": "chat",
                 "resources": [{"resource": "res-A", "model": "vm-A"}]},   # 别名复用同一条目
            ],
            scheduling={"quota_backoff_base_seconds": 0.0},
        )
        rt = build_runtime(cfg, adapter, clock=clock)
        attach(adapter, rt, {"sk-A": "res-A"})
        try:
            await rt.scheduler.execute_chat(_ir("gw-a"), _ctx(rt, "gw-a"))
        except GatewayError:
            pass
        a = rt.resources.pick_and_acquire("gw-a", exclude=set())
        b = rt.resources.pick_and_acquire("gw-b", exclude=set())
        n_entries = len(rt.resources.registry)
        _p("L2-8", f"注册表条目数={n_entries}（两个网关名共用一条 (rid,供应商模型名)）；"
                   f"冷却后 gw-a 被排除={a is None}、gw-b 被排除={b is None} "
                   f"⇒ 状态只有一份，挂在**条目**上（按网关名各记一份就会分叉）")
        assert a is None and b is None and n_entries == 1

    async def test_l2_7_serial_requests_have_zero_gap_between_dispatches(self):
        """串行两条请求：上一条**发车**到下一条**发车**之间，除了上游耗时之外有没有空窗。"""
        adapter = PacingAdapter(latency=0.02)
        clock = Clock(1_000.0)
        rt = build_runtime(make_config(models=[chat_model("test-model", "A")]),
                           adapter, clock=clock)
        attach(adapter, rt, {"sk-A": "res-A"})
        await rt.scheduler.execute_chat(_ir(), _ctx(rt))
        await rt.scheduler.execute_chat(_ir(), _ctx(rt))
        gap = (adapter.dispatches[1][1] - adapter.dispatches[0][1]) * 1000
        idle = gap - adapter.latency * 1000
        _p("L2-7", f"串行两次发车的 发车→发车 间隔={gap:.2f}ms，其中上游耗时 "
                   f"{adapter.latency*1000:.0f}ms ⇒ 网关自己加的节奏={idle:.2f}ms")
        assert idle < 20.0, "网关层节奏 ≈ 0：串行只保证不重叠，不保证有间隔（插件 model-gate 的那条律）"


    async def test_l2_9_upstream_given_delay_has_no_consumer(self):
        """上游**已经告诉过我方**要等多久（qoder `10605` 的 `retry_after_seconds` 已被解析出来），
        但有没有人按它等？全仓扫消费方。"""
        from model_gateway import core

        pkg = Path(core.__file__).parent.parent           # model_gateway/
        writers, readers = [], []
        for f in sorted(pkg.rglob("*.py")):
            text = f.read_text(encoding="utf-8")
            if "retry_after_seconds" not in text:
                continue
            (writers if f.name == "envelope.py" else readers).append(str(f.relative_to(pkg)))
        _p("L2-9", f"解析方=envelope.py ；**读取这个字段去等待**的模块={readers or '无'}")
        _p("L2-9", "⇒ 我方已经做了『429/排队分档』的识别（qoder 那一支），却没有做"
                   "『按上游给的时长精确等』这半句；而调度层的等待时长只有配置来的三个数"
                   "（quota_backoff / retry_backoff / 预算）")
        assert readers == []


# ==================================================================
# L7：目录取数的失败态（冷却 / 并发去重 / 「失败被当成功」的形状）
# ==================================================================

class CountingHook:
    """假 `list_models`：账号腿（`cred` 非空）可切成抛错/空表；兜底腿（空凭据）回内置表。"""

    def __init__(self, *, mode: str = "ok",
                 account_ids: tuple[str, ...] = ("vm-0", "vm-1", "vm-2"),
                 fallback_ids: tuple[str, ...] = ("fb-0", "fb-1", "fb-2")):
        self.mode = mode
        self.account_ids = account_ids
        self.fallback_ids = fallback_ids
        self.calls: list[bool] = []          # 每次调用记「是不是账号腿」

    @property
    def account_leg(self) -> int:
        return sum(1 for c in self.calls if c)

    async def __call__(self, cred, meta):
        self.calls.append(bool(cred))
        if cred:
            if self.mode == "raise":
                raise RuntimeError("catalog upstream down")
            if self.mode == "empty":
                return []
            return [ModelInfo(id=i, context_window=100_000, max_output=4096)
                    for i in self.account_ids]
        return [ModelInfo(id=i) for i in self.fallback_ids]


def seed_account(product: str, name: str) -> None:
    store.commit_login(product, name, {"access_token": SECRET}, {})


INFOS = [{"name": "v2-a", "enabled": True, "resource_id": ""}]


class TestL7CatalogFailureState:

    async def test_l7_1_empty_and_failed_never_reach_cache(self):
        """① 从未成功过：两次失败后 `read_cache` 返回什么；② 先好后坏：坏不得覆盖好。"""
        seed_account("buddy", "v2-a")
        root = catalog_cache.product_dir("buddy")

        for i in (1, 2):
            hook = CountingHook(mode="raise")
            models, source, reason = await aa._catalog_models(hook, "buddy", INFOS)
            view = catalog_cache.read_cache("buddy", root=root)
            _p("L7-1", f"第 {i} 次取数失败 → read_cache={view}  source.kind={source['kind']}  "
                       f"models={len(models)}  reason={reason[:44]}")
            assert view is None
        wrote = catalog_cache.write_cache("buddy", [], root=root)
        _p("L7-1", f"write_cache(空清单) → {wrote}（『取到 0 条不是证据』那条纪律成立）")
        assert wrote is False

        await aa._catalog_models(CountingHook(mode="ok"), "buddy", INFOS)
        good = catalog_cache.read_cache("buddy", root=root)
        _p("L7-1", f"成功一次后 read_cache: count={good['count']} stale={good['stale']} "
                   f"source_account={good['source_account']} age={good['age_seconds']:.3f}s")
        for i in (1, 2):
            await aa._catalog_models(CountingHook(mode="empty"), "buddy", INFOS)
            after = catalog_cache.read_cache("buddy", root=root)
            assert [m.id for m in after["models"]] == [m.id for m in good["models"]]
            _p("L7-1", f"随后第 {i} 次取到空表 → 缓存**未**被覆盖，read_cache 仍回旧好数据"
                       f"（stale={after['stale']}）→ 这条不存在『失败被当成功』")

    async def test_l7_2_no_cooldown_and_no_inflight_dedupe(self):
        """连取三次 / 四次并发 ⇒ 真发几次目录请求（我方既无失败冷却，也无并发去重）。"""
        seed_account("buddy", "v2-a")
        hook = CountingHook(mode="raise")
        for i in range(3):
            await aa._catalog_models(hook, "buddy", INFOS)
            _p("L7-2", f"第 {i+1} 次取数后：账号腿累计={hook.account_leg}  "
                       f"兜底腿累计={len(hook.calls) - hook.account_leg}")
        assert hook.account_leg == 3, "失败不产生任何冷却：三次点开 = 三次真打上游（各吃满超时）"

        h2 = CountingHook(mode="raise")
        await asyncio.gather(*[aa._catalog_models(h2, "buddy", INFOS) for _ in range(4)])
        _p("L7-2", f"4 个并发读 → 账号腿={h2.account_leg}（无 in-flight 去重；"
                   f"插件同一形状被 `remote-catalog-gate.ts` 收敛成 1 次）")
        assert h2.account_leg == 4

    async def test_l7_2b_fanout_upper_bound_per_single_click(self):
        """🔴 一次「点开弹窗」的最坏扇出：产品有 N 个启用号、前 N-1 个都取不动 ⇒ 真发几条腿。
        （`_catalog_models` 按存储序**依次试到第一个成功号**为止，中途没有冷却与短路。）"""
        for k in (1, 3):
            seed_account("buddy", f"v2-{k}")
        infos = [{"name": f"v2-{k}", "enabled": True, "resource_id": ""} for k in (1, 3)]

        hook = CountingHook(mode="raise")
        await aa._catalog_models(hook, "buddy", infos)
        _p("L7-2b", f"2 个启用号全部取不动 → 账号腿={hook.account_leg} 兜底腿={len(hook.calls)-hook.account_leg}"
                    f" ⇒ 一屏最坏 = N 条账号腿 + 1 条兜底腿（:8300 实盘 zcode 有 16 号）")
        assert hook.account_leg == 2

        h3 = CountingHook(mode="raise")
        await aa._catalog_models(h3, "buddy", infos[:1] + [{"name": "v2-3", "enabled": False,
                                                            "resource_id": ""}])
        _p("L7-2b", f"停用号被跳过：账号腿={h3.account_leg}（停用的那条不发）")
        assert h3.account_leg == 1


    async def test_l7_3_wall_clock_age_and_rollback(self):
        """`read_cache` 的新鲜度用**墙钟**算：时刻在未来 ⇒ age 被夹成 0 ⇒ 永远算新鲜。"""
        root = catalog_cache.product_dir("buddy")
        catalog_cache.write_cache("buddy", [ModelInfo(id="vm-x", context_window=1000)],
                                  source_account="v2-a", ttl_seconds=3600, root=root)
        path = catalog_cache.cache_path("buddy", root=root)
        view0 = catalog_cache.read_cache("buddy", root=root)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["fetched_at"] = time.time() + 86_400          # 系统时间被回拨一天
        path.write_text(json.dumps(data), encoding="utf-8")
        view = catalog_cache.read_cache("buddy", root=root)
        _p("L7-3", f"正常写入后 age={view0['age_seconds']:.3f}s stale={view0['stale']}")
        _p("L7-3", f"fetched_at 改到未来 +86400s（回拨一天的形状）→ age={view['age_seconds']:.1f} "
                   f"stale={view['stale']} ⇒ 一份未来时刻的缓存被当成最新")
        assert view["stale"] is False

    async def test_l7_4_endpoint_repeated_and_concurrent(self, monkeypatch):
        """端点级复现：GET /catalog 每次真取、并发不去重；兜底腿照实标 `source`。"""
        from model_gateway.upstream.buddy import product as buddy_product

        gw = asgi_gateway()
        hook = CountingHook(mode="raise")
        monkeypatch.setitem(buddy_product._HOOKS, "list_models", hook)
        async with gw["client"] as client:
            for i in range(2):
                r = await client.get("/admin/api/accounts/buddy/catalog")
                body = r.json()
                _p("L7-4", f"第 {i+1} 次 GET /catalog → HTTP {r.status_code} "
                           f"source.kind={body['source']['kind']} "
                           f"detail={body['source']['detail'][:28]} 账号腿={hook.account_leg}")
            before = hook.account_leg
            rs = await asyncio.gather(*[client.get("/admin/api/accounts/buddy/catalog")
                                        for _ in range(3)])
            _p("L7-4", f"3 个并发 GET /catalog → 账号腿 {before} → {hook.account_leg}"
                       f"（每请求各发一次，无去重、无冷却；三条都 200 + 兜底 source）")
            assert hook.account_leg - before == 3
            assert all(r.status_code == 200 for r in rs)

    async def test_l7_5_automap_receipt_loses_catalog_source(self, monkeypatch):
        """🔴 「失败被当成功」的形状在哪：初始化映射的回执里**没有**目录来源这一位。"""
        from model_gateway.upstream.buddy import product as buddy_product

        gw = asgi_gateway()
        # 账号腿整表抛错 → 只能用内置兜底表；兜底条目故意用一个能匹配上的名字
        hook = CountingHook(mode="raise", fallback_ids=("deepseek-v4-flash",))
        monkeypatch.setitem(buddy_product._HOOKS, "list_models", hook)
        async with gw["client"] as client:
            r = await client.post("/admin/api/accounts/auto-map", json={"product": "buddy"})
            body = r.json()
            _p("L7-5", f"账号腿抛错={hook.account_leg} 次 → POST /auto-map HTTP {r.status_code}")
            _p("L7-5", f"回执字段={sorted(body)}  via={body.get('via')} "
                       f"entries={body.get('entries')} added={body.get('added')} "
                       f"含目录来源位吗={'source' in body}")
            assert r.status_code == 200, body
            assert "source" not in body, (
                "实时目录整表失败、实际按内置兜底表生成了映射，回执却只报 entries/added —— "
                "用户在界面上读不出「这一次是按静态兜底目录写的」")
            assert hook.account_leg == 1

    async def test_l7_6_sync_raise_and_inflight_trap(self):
        """插件那条 ★ 律（同步抛错把 `inFlight` 覆盖成已 settle 的 Promise ⇒ 永不再重拉）
        在我方有没有同型结构？我方无 inFlight 槽；顺带验同步抛错会不会把端点打崩。"""
        seed_account("buddy", "v2-a")
        root = catalog_cache.product_dir("buddy")

        def sync_boom(cred, meta):        # 不是协程：账号腿调用即抛（插件 spec :111 那条 ★ 同型输入）
            if cred:
                raise RuntimeError("sync boom")

            async def _fallback():        # 兜底腿仍回一个 awaitable（形态与生产钩子一致）
                return [ModelInfo(id="fb-0")]

            return _fallback()

        models, source, reason = await aa._catalog_models(sync_boom, "buddy", INFOS)
        view = catalog_cache.read_cache("buddy", root=root)
        _p("L7-6", f"钩子**同步**抛错 → 我方 _catalog_models 是否抛出=No（已按「取不动」降级）；"
                   f"source.kind={source['kind']} models={len(models)} read_cache={view}")
        assert view is None and source["kind"] == "fallback"
        # 下一次照样重新打（没有"永久不再重拉"，也没有冷却）
        hook = CountingHook(mode="ok")
        await aa._catalog_models(hook, "buddy", INFOS)
        _p("L7-6", f"下一次取数：账号腿={hook.account_leg}（我方是「永远允许重试」那一侧，"
                   f"代价 = 每次都吃满超时；插件是「冷却期内一次都不发」那一侧）")
        assert hook.account_leg == 1


# ---------- 管理端 ASGI 替身（不起端口、不打 :8300） ----------

def asgi_gateway() -> dict:
    from model_gateway.main import create_app

    base = Path(store.product_root("buddy")).parent.parent   # data/upstream/
    tmp = base / "_v2repro"
    tmp.mkdir(parents=True, exist_ok=True)
    cfg = {
        "gateway": {"access_tokens": [{"id": "t", "value": "gw-v2"}]},
        "resources": [{"id": "res-A", "name": "资源A", "access_mode": "api",
                       "protocol": "openai", "base_url": "http://127.0.0.1:1/v1",
                       "api_key": "sk-A"}],
        "models": [{"name": "deepseek-v4-flash", "endpoint": "chat",
                    "resources": [{"resource": "res-A", "model": "vm-A"}]}],
    }
    p = tmp / "config.yaml"
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    app = create_app(config_path=p, usage_dir=tmp / "usage", enums_path=tmp / "enums.yaml")
    seed_account("buddy", "v2-a")
    return {"app": app,
            "client": httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                        base_url="http://gw",
                                        headers={"Authorization": "Bearer gw-v2"},
                                        timeout=30.0)}
