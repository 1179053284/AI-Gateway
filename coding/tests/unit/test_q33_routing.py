"""Q33 · 两级开关（产品位 × 号位）与号间轮转的选路判据（纯内存，无网络）。

覆盖三条定论（用户 2026-10-02 第九轮指令）：
- ① **产品 × 厂商模型** 的映射位是账号侧的唯一真相（`AppConfig.product_models`），
  关 ⇒ 该产品**所有号**一起出池并停止对外声明；
- ② 号开关 = 该号派生资源的 `enabled`，关 ⇒ **只有那个号**出池，其余号照常参与；
- ③ 号间轮转 = 生效集窗口随游标滑动（推翻 tech-design §5.3「低负载集中调用、不轮询」），
  但**切换轮**（`exclude` 非空）仍按用户排的优先级序。

旧配置兼容也在这里钉：没有产品位时回落到条目位（§22.5-2 的零迁移纪律）。
"""

from __future__ import annotations

from model_gateway.config.schemas import AppConfig
from model_gateway.core.resources import ResourceManager
from tests.unit.conftest import build_runtime, chat_model, make_config

MODEL = "test-model"
VM = "deepseek-v4.1"


def _account_cfg(*, product: str = "buddy", accounts: tuple[str, ...] = ("a", "b", "c", "d"),
                 bits: tuple[tuple[str, str, str, bool], ...] = (),
                 x: int = 2, entry_enabled: dict[str, bool] | None = None,
                 resource_disabled: tuple[str, ...] = ()):
    """「1 个产品 × N 个账号资源 + 1 个系统模型」的配置字典。

    `bits` = `(产品, 厂商模型, 系统模型, enabled)`；空 = 不写产品位（走旧配置回落）。
    `entry_enabled` = `{账号: 映射条目位}`；`resource_disabled` = 哪些号的资源被关掉（号位）。
    """
    resources = [{"id": f"res-{a}", "name": f"号{a}", "product": product,
                  "account_ref": a, "account": a, "api_key": "",
                  "protocol": "openai", "base_url": "http://fake.local/v1",
                  "enabled": a not in resource_disabled} for a in accounts]
    entries = [{"resource": f"res-{a}", "model": VM,
                "enabled": (entry_enabled or {}).get(a, True)} for a in accounts]
    cfg = make_config(models=[chat_model(MODEL, resources=entries)],
                      resources=resources, scheduling={"max_active_per_model": x})
    cfg["product_models"] = [{"product": p, "model": m, "system_model": s, "enabled": en}
                             for (p, m, s, en) in bits]
    return cfg


def _bit(enabled: bool = True):
    return ((("buddy", VM, MODEL, enabled)),)


class TestProductSwitch:
    """① 产品位：开 = 全组进池；关 = 全组出池且停止对外声明。"""

    def test_bit_on_puts_every_enabled_account_in_pool(self):
        rt = build_runtime(_account_cfg(bits=_bit(True)), adapter=None)
        assert [s.account for s in rt.resources.pools[MODEL]] == ["a", "b", "c", "d"]

    def test_bit_off_drops_whole_product_and_stops_declaring(self):
        from model_gateway.core.resources import servable_models

        rt = build_runtime(_account_cfg(bits=_bit(False)), adapter=None)
        assert rt.resources.pools[MODEL] == []          # 不进池 ⇒ 调度取不到
        assert MODEL not in servable_models(rt.config, rt.resources.registry)

    def test_bit_off_reaches_accounts_whose_entry_is_still_open(self):
        """🔴 旧「条目聚合当产品开关」的洞：位关掉时，残留开着的那几条也必须一起失效。

        判据读产品位本身，不是「组内至少一条开着就算开着」。
        """
        from model_gateway.core.resources import servable_models

        cfg = _account_cfg(bits=_bit(False), entry_enabled={"a": True, "b": True},
                           resource_disabled=("c",))
        rt = build_runtime(cfg, adapter=None)
        assert rt.resources.pools[MODEL] == []
        assert MODEL not in servable_models(rt.config, rt.resources.registry)

    def test_bit_on_serves_even_accounts_whose_entries_are_all_closed(self):
        """反向：位开着但条目全关（旧数据）⇒ 产品位是真相，照旧进池。

        这条同时证明"号开关 ≠ 映射条目开关"：条目位只是历史残留，不再决定能不能调用。
        """
        cfg = _account_cfg(bits=_bit(True),
                           entry_enabled={a: False for a in ("a", "b", "c", "d")})
        rt = build_runtime(cfg, adapter=None)
        assert len(rt.resources.pools[MODEL]) == 4

    def test_bit_pointing_elsewhere_does_not_feed_this_model(self):
        """产品位挂在别的系统模型上 ⇒ 本模型不得凭它进池（防"挂错池"静默放行）。

        第二模型故意复用同一条 `(res-a, VM)`：**跨系统模型**挂同一组合是既有设计
        （别名 + 运行态共享冷却，UT-84 的第二腿钉着它不被去重摘掉），
        所以本用例真正钉的是判据第三条腿 `pm.system_model == system_model`，不是组合形状。
        """
        cfg = _account_cfg(bits=(("buddy", VM, "另一个模型", True),))
        cfg["models"].append({"name": "另一个模型", "endpoint": "chat",
                              "resources": [{"resource": "res-a", "model": VM}]})
        rt = build_runtime(cfg, adapter=None)
        assert rt.resources.pools[MODEL] == []          # 本模型：位不指它 ⇒ 全出池
        assert len(rt.resources.pools["另一个模型"]) == 1   # 那位下只有 res-a 一条映射


class TestAccountSwitch:
    """② 号位：关一个号，那个号就永远不会被选到；其余号照常轮转。

    🔴 判据落点与产品位**不同层**：产品位关 ⇒ 条目**不进池**（`rebuild` 跳过）；
    号位关 ⇒ 条目**在池里但 `available()` 为假**（`Resource.enabled` 走运行态判据，
    冷却/判死历史都留着，重新启用即恢复）。两条轴各自的位置必须钉清楚，
    否则改一处就会把另一处的语义顺手改掉。
    """

    def test_disabled_account_is_never_picked(self):
        rt = build_runtime(_account_cfg(bits=_bit(True), resource_disabled=("b",)),
                           adapter=None)
        seen = set()
        for _ in range(8):
            r = rt.resources.pick_and_acquire(MODEL, set())
            assert r is not None
            seen.add(r.account)
            rt.resources.release(r)
        assert "b" not in seen                      # 停用的号一次都没被选中
        assert seen == {"a", "c", "d"}              # 其余三个号照常轮转

    def test_registry_keeps_state_for_disabled_account(self):
        """停用号的状态条目仍留着（冷却/判死历史不丢），重新启用即回池。"""
        rt = build_runtime(_account_cfg(bits=_bit(True), resource_disabled=("b",)),
                           adapter=None)
        assert (f"res-b", VM) in rt.resources.registry
        st = rt.resources.registry[(f"res-b", VM)]
        assert st.enabled is False and st.available() is False


def test_account_resource_reads_as_the_account_name_not_a_bare_id():
    """🔴 评审 R9-报备 R-9 的下半句：账号侧资源没有备注名时，人读那一尺必须落到**账号名**。

    旧回落是 `name or id` ⇒ `materialize` 不填备注名的账号资源永远显示成 `res-9a17353a`，
    用户在请求日志 / 切换事件 / "装不下已换号"的理由串里读到的是自己从没起过的串
    （同一条链路上其它文案都用 `resource_id_str`）。厂商侧资源没有账号名 ⇒ 逐字不变。
    """
    cfg = AppConfig.model_validate({
        "resources": [
            {"id": "res-K", "api_key": "sk", "protocol": "openai", "base_url": "http://x/v1"},
            {"id": "res-P", "product": "buddy", "account_ref": "ix-a", "protocol": "openai",
             "base_url": "http://y/v1"},
            {"id": "res-N", "name": "我的备注", "product": "buddy", "account_ref": "ix-b",
             "protocol": "openai", "base_url": "http://y/v1"},
        ],
        "models": [{"name": "m", "endpoint": "chat", "resources": [
            {"resource": "res-K", "model": "vm-k"}, {"resource": "res-P", "model": "vm-x"},
            {"resource": "res-N", "model": "vm-x"}]}],
    })
    rm = ResourceManager()
    rm.rebuild(cfg)
    assert rm.registry[("res-K", "vm-k")].resource_id_str == "res-K/vm-k"      # 厂商侧逐字不变
    assert rm.registry[("res-P", "vm-x")].resource_id_str == "ix-a/vm-x"       # 落到账号名
    assert rm.registry[("res-N", "vm-x")].resource_id_str == "我的备注/vm-x"     # 备注名优先


def test_account_view_and_status_rows_carry_the_same_label():
    """🔴 评审 R11-报备：`display_label` 必须在**每一条出口**上都生效，不只日志串。

    同一个回落原先在四个地方各写一遍 `name or id`（资源状态行、告警文案、影子参数提示、
    事件里的 `resource_id_str`）⇒ 只改一处就是假修：界面上那一列仍会是 `res-9a17353a`。
    这里把"状态视图那一列"与"配置告警文案"两条出口一起钉住。
    """
    cfg = AppConfig.model_validate({
        "resources": [{"id": "res-P", "product": "buddy", "account_ref": "ix-a",
                       "protocol": "openai", "base_url": "http://y/v1"}],
        "models": [{"name": "m", "endpoint": "chat",
                    "resources": [{"resource": "res-P", "model": "vm-x"}]}],
    })
    rm = ResourceManager()
    rm.rebuild(cfg)
    rows = rm.snapshot_by_resource(cfg)      # 管理端「资源状态」那一列的数据源
    row = next(x for x in rows if x["rid"] == "res-P")
    assert row["name"] == "ix-a", row
    # 事件/日志那一尺同一条串
    assert rm.registry[("res-P", "vm-x")].resource_id_str == "ix-a/vm-x"


class TestRotation:
    """③ 号间轮转（推翻 §5.3「不轮询」）。"""

    def test_four_idle_accounts_each_get_a_turn(self):
        """x=2、四个号全空闲：连续六轮（每轮 release）必须**四个号都被用到**。

        旧实现（固定前缀切片 + 平局取池首）只会反复给 A/B，C/D 永远轮不上 ——
        这条就是那个缺陷的反证：一行改回 `candidates[:x]` 立刻红。
        """
        rt = build_runtime(_account_cfg(bits=_bit(True), x=2), adapter=None)
        seen = []
        for _ in range(6):
            r = rt.resources.pick_and_acquire(MODEL, set())
            assert r is not None
            seen.append(r.account)
            rt.resources.release(r)
        assert set(seen) == {"a", "b", "c", "d"}, seen

    def test_two_concurrent_requests_land_on_two_different_accounts(self):
        """并发两条（都不 release）⇒ 必须落在**两个不同**的号上（多号并行的直接判据）。"""
        rt = build_runtime(_account_cfg(bits=_bit(True), x=2), adapter=None)
        first = rt.resources.pick_and_acquire(MODEL, set())
        second = rt.resources.pick_and_acquire(MODEL, set())
        assert (first.account, second.account) == ("a", "b")
        assert first.resource_id != second.resource_id
        rt.resources.release(first)
        rt.resources.release(second)

    def test_window_stays_x_wide(self):
        """🔴 x 的真判据（R2-① 抓出我原先这条是**空断言**：四号同时在途也照样过）。

        ① 并发不释放：三条只能由 ≤ x 个号承接（第三条复用组内较闲的那个）；
        ② 串行（每条都排空）：连续八条必须把四个号都用上 —— 这才叫"轮流调用"。
        """
        rt = build_runtime(_account_cfg(bits=_bit(True), x=2), adapter=None)
        pool = rt.resources.pools[MODEL]
        held = [rt.resources.pick_and_acquire(MODEL, set()) for _ in range(3)]
        carriers = {h.account for h in held}
        assert len(carriers) == 2 and carriers == {"a", "b"}, f"承接者越出 x：{carriers}"
        assert sum(h.in_flight for h in pool) == 3
        for h in held:
            rt.resources.release(h)

        seen = set()
        for _ in range(8):
            r = rt.resources.pick_and_acquire(MODEL, set())
            seen.add(r.account)
            rt.resources.release(r)
        assert seen == {"a", "b", "c", "d"}, f"串行八条仍有号从未轮到：{sorted(seen)}"

    def test_no_carrier_leak_when_one_member_drains_early(self):
        """🔴 组内**单个**成员先排空时不得让位（x 上限的漏口，白盒复现评审 R2-① 的探针）。

        只按"某个号排空就推游标"的写法：a、b 同时在途（x=2）→ b 先排空 → 窗口滑到 {c,d}
        → a 仍在途却落到窗外，c、d 照开 ⇒ **同时在途 3 条 > x**。
        活跃组的判据是"**整组**排空才换位"，所以这一步窗口仍锁在 {a,b}。
        红证（将 `release` 的整组前置判断撤掉 = 恢复"单个排空即推游标"）：本用例红。
        """
        rt = build_runtime(_account_cfg(bits=_bit(True), x=2), adapter=None)
        pick = rt.resources.pick_and_acquire
        a = pick(MODEL, set())
        b = pick(MODEL, set())
        assert (a.account, b.account) == ("a", "b")
        rt.resources.release(b)                       # 组里 a 还在途 ⇒ 不让位
        third = pick(MODEL, set())
        fourth = pick(MODEL, set())
        carriers = {a.account, third.account, fourth.account}
        assert len(carriers) <= 2, f"同时在途承接者越出 x=2：{sorted(carriers)}"
        assert rt.resources._cursor.get(MODEL, 0) == 0, "整组未排空就推进了游标"
        for r in (a, b, third, fourth):
            rt.resources.release(r)

    def test_rotation_survives_unavailable_members(self):
        """🔴 池里有停用/冷却号时，轮转不得把某些号**永久跳过**（索引空间混用的回归锚）。

        停用 b、冷却 c，只剩 a/d 可用 ⇒ 若干轮后 a 与 d 都必须被轮到。
        """
        rt = build_runtime(_account_cfg(bits=_bit(True), x=2, resource_disabled=("b",)),
                           adapter=None)
        c = rt.resources.registry[(f"res-c", VM)]
        rt.resources.bench(c, 600)
        seen = set()
        for _ in range(6):
            r = rt.resources.pick_and_acquire(MODEL, set())
            assert r is not None
            seen.add(r.account)
            rt.resources.release(r)
        assert seen == {"a", "d"}, f"可用号没被轮完：{sorted(seen)}"

    def test_failover_round_does_not_move_cursor(self):
        """🔴 切换轮**不推进游标**（§5.3a 第 3 条的机制判据，白盒直读游标）。

        推进只发生在"某个号排空释放"那一刻；切换轮只是同一条请求的替补尝试，
        它改了游标就会把用户排的优先级顺序冲掉。
        """
        rt = build_runtime(_account_cfg(bits=_bit(True), x=2), adapter=None)
        first = rt.resources.pick_and_acquire(MODEL, set())
        assert first.account == "a"
        assert rt.resources._cursor.get(MODEL, 0) == 0        # 常态轮也不在选中时推进
        second = rt.resources.pick_and_acquire(MODEL, exclude={(f"res-a", VM)})
        assert second.account == "b"                          # 切换轮按池序
        assert rt.resources._cursor.get(MODEL, 0) == 0        # 没被切换轮改写
        rt.resources.release(second)
        assert rt.resources._cursor.get(MODEL, 0) == 0        # 组里 a 还在途 ⇒ 整组未排空，不让位
        rt.resources.release(first)
        assert rt.resources._cursor.get(MODEL) == 1           # 最后一条排空 ⇒ 起点推到 a 之后
        nxt = rt.resources.pick_and_acquire(MODEL, set())
        assert nxt.account == "b"
        rt.resources.release(nxt)

    def test_failover_prefers_the_group_over_fresh_accounts(self):
        """🔴 切换轮的替补顺序 = **组内优先**，组内无人可换才开池外备胎（x 上限的唯一例外）。

        复验轮 R4-A 判死：`UT-71` 只断"选到 b"，而"永远取池序第一个"的实现同样满足 ⇒
        它钉不住"组内优先 + 取在途最少"这条真语义。本用例两头都断：
        ① a 故障、组里还剩 b（即便 b 已在途）⇒ 必须给 b，**不许**去开 c/d；
        ② a、b 都被排除 ⇒ 才允许用组外备胎，此刻并行数可越出 x 一条
           （tech §5.3a 第 3 条登记的例外：不能让"明明有可用号"的请求吃 503）。
        """
        rt = build_runtime(_account_cfg(bits=_bit(True), x=2), adapter=None)
        pick = rt.resources.pick_and_acquire
        a = pick(MODEL, set())
        b = pick(MODEL, set())
        assert (a.account, b.account) == ("a", "b")           # 组 = {a, b}，两条都在途
        sub = pick(MODEL, exclude={(f"res-a", VM)})
        assert sub.account == "b", f"替补越出活跃组，x 上限被切换轮自己打破：{sub.account}"
        assert sub.in_flight == 2
        spare = pick(MODEL, exclude={(f"res-a", VM), (f"res-b", VM)})
        assert spare.account in ("c", "d"), f"组内无人时未取池外备胎：{spare.account}"
        for r in (a, b, sub, spare):
            rt.resources.release(r)

    def test_cold_start_matches_old_behaviour(self):
        """新建进程第一次选路仍是池首（游标初值 0）—— 轮转不改变"第一下打谁"。"""
        rt = build_runtime(_account_cfg(bits=_bit(True)), adapter=None)
        r = rt.resources.pick_and_acquire(MODEL, set())
        assert r.account == "a"
        rt.resources.release(r)


    def test_duplicate_combo_is_dropped_not_silently_doubled(self):
        """🔴 UT-84 · **同一系统模型内** `(资源, 厂商模型)` 组合唯一进跨节校验（§6-8 授权落地）。

        旧形状：组合唯一只由写面保证（`_mapping_holder` 扫一遍），手改 YAML 在一个模型的
        `resources[]` 里把同组合写两遍，读侧照单全收 ⇒ 生效集把同一条算两遍，
        承诺 x=2 实际只有 1 条能承接（评审 R1-§二实测）。
        🔴 作用域只在本模型内：**跨系统模型**挂同一组合是既有设计（别名 + 运行态按
        `(rid, vendor_model)` 共享冷却），被 `test_scheduler.py::
        test_cooldown_shared_across_system_models` 钉着 —— 这里第二腿就把那条例别形状
        当作**必须保留**的反证，防止下一轮把去重做成全配置唯一。
        """
        from model_gateway.config.schemas import AppConfig
        from tests.unit.conftest import chat_model, make_config

        res = [{"id": "res-a", "api_key": "sk-a", "protocol": "openai",
                "base_url": "http://fake.local/v1"},
               {"id": "res-b", "api_key": "sk-b", "protocol": "openai",
                "base_url": "http://fake.local/v1"}]
        cfg = make_config(resources=res, models=[
            # m-1 里同组合写两遍（非法）+ 一条正常
            chat_model("m-1", resources=[{"resource": "res-a", "model": VM},
                                         {"resource": "res-a", "model": VM},
                                         {"resource": "res-b", "model": VM}]),
            # m-2 复用 res-a/VM：合法别名，不得被摘
            chat_model("m-2", resources=[{"resource": "res-a", "model": VM}]),
        ])
        got = AppConfig.model_validate(cfg)
        assert [(e.resource, e.model) for e in got.models[0].resources] == [
            ("res-a", VM), ("res-b", VM)], got.models[0].resources
        assert [e.resource for e in got.models[1].resources] == ["res-a"]   # 别名保留
        assert any("出现两次" in w and "已忽略本条" in w for w in got.warnings), got.warnings
        # 丢重不得把"引用不存在的资源"这类真错误一起吞掉（那条仍是 raise）
        broken = make_config(resources=res[:1], models=[
            chat_model("m-3", resources=[{"resource": "res-ghost", "model": VM}])])
        try:
            AppConfig.model_validate(broken)
            raise AssertionError("引用不存在的资源必须抛，不能被去重逻辑吞掉")
        except ValueError as e:
            assert "res-ghost" in str(e)


class TestLegacyFallback:
    """零迁移：没有产品位时，条目位（`ModelResource.enabled`）照旧是唯一判据。"""

    def test_no_bit_all_entries_closed_leaves_pool_empty(self):
        from model_gateway.core.resources import servable_models

        cfg = _account_cfg(entry_enabled={a: False for a in ("a", "b", "c", "d")})
        rt = build_runtime(cfg, adapter=None)
        assert rt.resources.pools[MODEL] == []
        assert MODEL not in servable_models(rt.config, rt.resources.registry)

    def test_no_bit_open_entries_still_serve(self):
        rt = build_runtime(_account_cfg(entry_enabled={"a": True}), adapter=None)
        assert len(rt.resources.pools[MODEL]) == 4

    def test_duplicate_bit_dropped_with_warning_not_config_blowup(self):
        """🔴 坏位的处置 = **丢掉那一条 + 告警**，不是让整份配置加载失败（R2-④ 判死）。

        原先 `raise` 的后果是"删掉一个系统模型 ⇒ 网关所有模型一起停服，而界面上没有任何
        自救入口" —— 那是可用性灾难。有效/无效的把关属于**写面**（`POST …/mappings`
        动盘前就拒，回执 400 可执行），读面只负责"能起就起、坏的丢掉并如实说"。
        """
        from model_gateway.config.schemas import AppConfig

        cfg = _account_cfg(bits=(("buddy", VM, MODEL, True), ("buddy", VM, MODEL, False)))
        got = AppConfig.model_validate(cfg)
        assert len(got.product_models) == 1 and got.product_models[0].enabled is True
        assert any("重复" in w for w in got.warnings), got.warnings

    def test_bit_pointing_at_deleted_model_is_dropped_not_fatal(self):
        """删系统模型后配置仍能加载（首条位被丢 + 告警），其余资源不受影响。"""
        from model_gateway.config.schemas import AppConfig

        cfg = _account_cfg(bits=(("buddy", VM, "不存在-的模型", True),))
        got = AppConfig.model_validate(cfg)
        assert got.product_models == []
        assert any("不是 models[] 里在册的系统模型" in w for w in got.warnings), got.warnings
        assert len(got.resources) == 4 and any(m.name == MODEL for m in got.models)
