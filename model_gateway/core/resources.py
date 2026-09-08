"""资源池/生效集/冷却/连续失败计数（tech-design §4.3 / §5.3；Q18-② 扁平资源模型）。

- 全局注册表：resource_id=(resource_id, vendor_model) → 状态全局唯一（PRD Q11）
  （资源 = 厂商 + Key；同一资源可服务多个系统模型，各自携带厂商侧模型名）
- 生效集选路（§5.3）：top-x 可用资源（x 全局唯一，Q18-③）；集内在途最少者承接，平局取优先级高
- 选路与在途 +1 在同一同步段（pick_and_acquire，无 await）
- 冷却懒恢复：选路时检查到期归位（UT-10）
- 时钟可注入（测试 mock）
"""

from __future__ import annotations

import time
from typing import Callable

from model_gateway.config.presets import preset_name
from model_gateway.config.schemas import AppConfig


def vendor_label(preset: str, vendor: str = "", name: str = "", rid: str = "") -> str:
    """资源厂商展示名（事件 provider 字段 / 统计「按厂商」维度口径，Q20-①）。

    自定义厂商名（resources[].vendor）优先 → 已知预设名 → 预设 id → 资源备注 → id → 'custom'。
    """
    if vendor:
        return vendor
    if preset:
        return preset_name(preset) or preset
    return name or rid or "custom"


class ResourceState:
    """单资源运行态（跨配置快照持久，按 resource_id 关联，tech §8-4）。"""

    __slots__ = ("rid", "vendor_model", "label", "vendor", "account", "status", "C",
                 "cooldown_until", "last_error", "in_flight", "enabled",
                 "access_mode", "system_models")

    def __init__(self, rid: str, vendor_model: str, *, label: str, vendor: str,
                 account: str, access_mode: str, enabled: bool):
        self.rid = rid  # 资源 id（config.resources[].id）
        self.vendor_model = vendor_model  # 厂商侧模型名（来自模型资源引用）
        self.label = label  # 显示名（资源备注或 id）
        self.vendor = vendor  # 厂商展示名（事件 provider 字段）
        self.account = account  # 账号标识（次要备注，事件 account 字段）
        self.status = "active"  # active | cooldown | disabled | invalid
        self.C = 0  # 连续失败计数（跨请求累计，成功清零）
        self.cooldown_until = 0.0
        self.last_error: str | None = None
        self.in_flight = 0
        self.enabled = enabled  # 资源开关（resources[].enabled）
        self.access_mode = access_mode  # api | plan（决定 429 冷却默认时长）
        self.system_models: set[str] = set()

    @property
    def resource_id(self) -> tuple[str, str]:
        return (self.rid, self.vendor_model)

    @property
    def resource_id_str(self) -> str:
        return f"{self.label}/{self.vendor_model}"

    def available(self) -> bool:
        return self.status == "active" and self.enabled


class ResourceManager:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.registry: dict[tuple[str, str], ResourceState] = {}
        # 每系统模型有序资源列表（优先序）；x 全局唯一（Q18-③）
        self.pools: dict[str, list[ResourceState]] = {}
        self.x = 2  # 全局并发溢出生效集（rebuild 时从配置刷新）

    # —— 配置同步（热重载保状态，tech §8-4）——
    def rebuild(self, config: AppConfig) -> None:
        res_index = {r.id: r for r in config.resources}

        new_pools: dict[str, list[ResourceState]] = {}
        referenced: set[tuple[str, str]] = set()

        for m in config.models:
            pool: list[ResourceState] = []
            for ref in m.resources:
                rid = (ref.resource, ref.model)
                referenced.add(rid)
                state = self.registry.get(rid)
                if state is None:
                    r = res_index[ref.resource]
                    state = ResourceState(ref.resource, ref.model,
                                          label=r.name or r.id,
                                          vendor=vendor_label(r.preset, r.vendor, r.name, r.id),
                                          account=r.account,
                                          access_mode=r.access_mode,
                                          enabled=r.enabled)
                    self.registry[rid] = state
                else:  # 状态保留（C/冷却/in_flight），仅刷新可变属性
                    r = res_index[ref.resource]
                    state.label = r.name or r.id
                    state.vendor = vendor_label(r.preset, r.vendor, r.name, r.id)
                    state.account = r.account
                    state.enabled = r.enabled
                    state.access_mode = r.access_mode
                pool.append(state)
            new_pools[m.name] = pool

        # 清理无主状态（§4.3：配置删除全部引用时）
        for rid in list(self.registry):
            if rid not in referenced:
                del self.registry[rid]
        # 引用集合重建（含被移除模型的名字）
        for state in self.registry.values():
            state.system_models = {m.name for m in config.models
                                   if any(rr.resource == state.rid and rr.model == state.vendor_model
                                          for rr in m.resources)}
        self.pools = new_pools
        self.x = config.scheduling.max_active_per_model

    # —— 选路（§5.3 并发溢出生效集；UT-22 七场景）——
    def pick_and_acquire(self, system_model: str, exclude: set) -> ResourceState | None:
        """选路并在同一同步段完成在途 +1（单线程事件循环内天然原子）。

        exclude：本请求已尝试过的资源（故障切换目标选取时排除）。
        """
        pool = self.pools.get(system_model)
        if not pool:
            return None
        now = self.clock()
        candidates = []
        for r in pool:
            if r.resource_id in exclude:
                continue
            # 冷却懒恢复（UT-10：到期按原优先级归位）
            if r.status == "cooldown" and now >= r.cooldown_until:
                r.status = "active"
            if r.available():
                candidates.append(r)
        if not candidates:
            return None
        active_set = candidates[:self.x]  # 生效集 = top-x 可用资源（x 全局）
        # 集内在途最少者承接；平局取优先级高（min 返回首个最小值 = 列表序 = 优先级）
        best = min(active_set, key=lambda r: r.in_flight)
        best.in_flight += 1
        return best

    def release(self, state: ResourceState) -> None:
        if state.in_flight > 0:
            state.in_flight -= 1

    # —— 状态变更 ——
    def bench(self, state: ResourceState, seconds: float) -> None:
        """移出生效集 → 冷却至 now+seconds（api/plan 模式时长由调用方决定）。"""
        state.status = "cooldown"
        state.cooldown_until = self.clock() + seconds

    def disable(self, state: ResourceState) -> None:
        state.status = "disabled"

    def invalidate(self, state: ResourceState) -> None:
        state.status = "invalid"

    def note_failure(self, state: ResourceState, error_summary: str) -> int:
        state.C += 1
        state.last_error = error_summary
        return state.C

    def note_success(self, state: ResourceState) -> None:
        state.C = 0

    def cooldown_seconds_for(self, state: ResourceState, snapshot: AppConfig) -> int:
        """冷却时长按资源接入模式取默认（UT-06）。"""
        if state.access_mode == "plan":
            return snapshot.scheduling.cooldown_seconds_plan
        return snapshot.scheduling.cooldown_seconds

    def cooldown_remaining_ms(self, state: ResourceState) -> int:
        if state.status != "cooldown":
            return 0
        rem = (state.cooldown_until - self.clock()) * 1000
        return max(0, int(rem))

    # —— 视图 ——
    def snapshot_by_resource(self, config: AppConfig) -> list[dict]:
        """按资源聚合快照（总览「资源健康」/「资源总数」口径：资源 = 厂商+账号+Key，
        一行一资源；映射条目 (rid, vendor_model) 的运行态聚汇到所属资源）。

        资源级状态聚合：资源停用 disabled > 条目全部 invalid > 条目全部非 active（冷却中）
        > active（任一条目 active 或暂无映射）；C 取条目最大值，in_flight 求和。
        """
        by_rid: dict[str, list[ResourceState]] = {}
        for s in self.registry.values():
            by_rid.setdefault(s.rid, []).append(s)
        out = []
        for r in config.resources:
            entries = by_rid.get(r.id, [])
            if not r.enabled:
                status = "disabled"
            elif entries and all(e.status == "invalid" for e in entries):
                status = "invalid"
            elif entries and all(e.status != "active" for e in entries):
                status = "cooldown"
            else:
                status = "active"
            out.append({
                "rid": r.id,
                "name": r.name or r.id,
                "vendor": vendor_label(r.preset, r.vendor, r.name, r.id),
                "account": r.account,
                "status": status,
                # 可用 = 开关开启且状态正常（能承接请求）
                "available": status == "active",
                "C": max((e.C for e in entries), default=0),
                "in_flight": sum(e.in_flight for e in entries),
                "cooldown_remaining_ms": max((self.cooldown_remaining_ms(e) for e in entries),
                                             default=0),
                "models": len(entries),
            })
        return out
