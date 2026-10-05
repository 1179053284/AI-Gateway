"""资源池/生效集/冷却/连续失败计数（tech-design §4.3 / §5.3；Q18-② 扁平资源模型）。

- 全局注册表：resource_id=(resource_id, vendor_model) → 状态全局唯一（PRD Q11）
  （资源 = 供应商 + Key；同一资源可服务多个网关模型，各自携带**供应商模型名**）
- 生效集选路（§5.3）：top-x 可用资源（x 全局唯一，Q18-③）；集内在途最少者承接，平局取优先级高
- 选路与在途 +1 在同一同步段（pick_and_acquire，无 await）
- 冷却懒恢复：读时归位（选路 / 出快照两条读取路径共用同一组动作）——
  ① 到期归位（UT-10）；② **熔断已不成立**时把熔断按住的冷却当场放回生效集
  （2026-09-29 用户裁决「读时重判」；判据由装配侧注入，core 不 import upstream）
- 时钟可注入（测试 mock）
"""

from __future__ import annotations

import hashlib
import re
import time
from contextlib import contextmanager
from typing import Callable

from model_gateway.config.presets import preset_name
from model_gateway.config.schemas import AppConfig


def normalize_base_url(url: str | None) -> str:
    """连接身份比较用的 URL 归一化：去首尾空白 + 去尾部 `/`。

    🔴 唯一口径（验收 S-14 → S-19）：判"凭据换过了"的 `_conn_fingerprint` 与
    `main.py` 判"出站适配器可否复用"必须走**同一个函数**。原先两处各写一遍
    （这里 `.strip().rstrip("/")`，那里只 `.rstrip("/")`），粘贴来的带空格 URL
    就会出现"运行态认为没变、适配器认为变了"—— 两处口径一分离，S-14 那类
    复活判死凭据的缺陷就会换个位置复现。
    """
    return (url or "").strip().rstrip("/")


def _conn_fingerprint(r, credential_fp: str = "") -> str:
    """资源**连接身份**摘要（protocol + 归一化 base_url + Key + 产品账号凭据）；判定"凭据换过了"。

    🔴 B-2（M6-6 Fix-γ）：产品资源的"Key"在**账号目录**里（配置里恒为空串），所以连接
    身份必须把 `product + account_ref + 凭据指纹` 一并纳入 —— 否则"重新登录 / 改绑账号
    = 换了一条连接身份 → 运行态清零"（PRD Q28-⑥③、S-2 的立意）在产品场景**不成立**：
    401 判死（终态 `disabled`）的资源永远不回生效集，用户按提示"重新登录"也永远 503。
    对照 `main.py::_adapter_reuse_key` 的复用判据**早已**含这三项 —— 本次把运行态指纹
    对齐到同一口径，消掉这处"连接身份"判定的分叉（S-14 同族缺陷的对称性缺口）。

    `credential_fp` 由**装配侧注入的判据**提供（`ResourceManager.credential_fingerprint`，
    见该字段说明；`core/` 不 import `accounts/`）：只存**摘要**不存明文凭据 ——
    `ResourceState` 会进 repr/日志路径，把密钥/凭据抄进去等于多一处泄露面
    （铁律 1；§22.2 不变式②：日志里凭据只以短哈希出现）。

    归一化必须与 `main.py` 判"适配器可否复用"同源（同用 `normalize_base_url`，
    验收 S-14：口径分叉过一次，后果是"补个尾斜杠就把 401 判死的资源放回生效集"）。
    """
    base = normalize_base_url(getattr(r, "base_url", ""))
    prod = str(getattr(r, "product", "") or "").strip()
    account = str(getattr(r, "account_ref", "") or "").strip()
    raw = (f"{getattr(r, 'protocol', '') or 'openai'}\n{base}\n{getattr(r, 'api_key', '')}"
           f"\n{prod}\n{account}\n{credential_fp}")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def vendor_label(preset: str, vendor: str = "", name: str = "", rid: str = "") -> str:
    """资源供应商展示名（事件 provider 字段 / 统计「按供应商」维度口径，Q20-①）。

    自定义供应商名（resources[].vendor）优先 → 已知预设名 → 预设 id → 资源备注 → id → 'custom'。
    """
    if vendor:
        return vendor
    if preset:
        return preset_name(preset) or preset
    return name or rid or "custom"


class QuotaPool:
    """**一把凭据**的额度桶（v2.0 §19 M5-3）。

    粒度 = 资源 id（`rid`）：一个资源（供应商+账号+Key）可同时映射多个供应商模型名，
    而额度是**账号侧**共享的。早先每个 `(rid, vendor_model)` 各记一份余量 →
    同账号有 N 个映射就能各放行 1 个，余量 1 也并发超发 N 个（验收 S-1）。

    🔴 两个字段各自的语义是**唯一的**，不再有第三个"本地记账"维度：

    | 字段 | 含义 | 谁写 |
    |---|---|---|
    | `remaining` | 上游**最近一次快照**的余量 = 唯一权威 | 额度刷新路径（`set_quota`） |
    | `reserved` | **在飞**已预留、尚未结算的请求数 | 选路 `reserve_quota` / `settle_quota` / `release_quota` |

    ⚠️ 为什么没有"本地已消耗"计数（第三轮我曾加过，是错的）：上游快照本身就会反映
    已用量，本地再猜一份"我扣了 N"只会造成两类故障 ——
    ① 用单调守卫防"快照把余量变大"，结果**充值/新窗口被永久拒收**（自锁到重启）；
    ② 结算时自增本地 `used`，使**下一条滞后快照**被误判成"窗口翻页"而把已消耗的复活。
    真实的上游消耗由上游自己反映；快照未及时反映时，请求打到上游会以 429/quota 失败，
    由 `core/scheduler` 既有的退避 + `note_failure`/`bench` 与 §17 的额度耗尽回写承接。
    """

    __slots__ = ("remaining", "reserved")

    def __init__(self) -> None:
        #: None = 未知/不限（如普通按量 API Key）→ 不做额度管控
        self.remaining: int | None = None
        self.reserved: int = 0

    def has_room(self) -> bool:
        if self.remaining is None:
            return True
        return (self.remaining - self.reserved) > 0

    def __repr__(self) -> str:  # 诊断用
        return f"QuotaPool(remaining={self.remaining}, reserved={self.reserved})"


def display_label(r: "Resource") -> str:
    """资源在**人读的那一尺**上的名字（评审 R9-报备 R-9 的下半句）。

    旧回落是 `name or id` ⇒ 账号侧资源（`materialize` 不填备注名）永远显示成
    `res-9a17353a` 这种自动生成的 id：用户在请求日志、切换事件与"装不下已换号"这类
    理由串里读到的是自己从没起过的串，与同一条链路上其它文案（资源页备注、
    `GatewayError` 的"已尝试：资源B/glm-5.2×1"）不同尺。
    回落顺序 = 备注名 → **账号名**（账号侧资源一定有 `account_ref`，且它就是界面上那一行）→ id。
    按 Key 接入的供应商资源没有账号名 ⇒ 与改动前逐字一致，零行为变化。
    """
    return r.name or r.account_ref or r.id


class ResourceState:
    """单资源运行态（跨配置快照持久，按 resource_id 关联，tech §8-4）。"""

    __slots__ = ("rid", "vendor_model", "label", "vendor", "account", "status", "C",
                 "cooldown_until", "last_error", "in_flight", "enabled",
                 "access_mode", "system_models", "quota", "src_fp", "circuit_held")

    def __init__(self, rid: str, vendor_model: str, *, label: str, vendor: str,
                 account: str, access_mode: str, enabled: bool,
                 quota: QuotaPool | None = None, src_fp: str = ""):
        self.rid = rid  # 资源 id（config.resources[].id）
        self.vendor_model = vendor_model  # 供应商模型名（来自模型资源引用）
        self.label = label  # 显示名（资源备注或 id）
        self.vendor = vendor  # 供应商展示名（事件 provider 字段）
        self.account = account  # 账号标识（次要备注，事件 account 字段）
        self.status = "active"  # active | cooldown | disabled | invalid
        self.C = 0  # 连续失败计数（跨请求累计，成功清零）
        self.cooldown_until = 0.0
        self.last_error: str | None = None
        self.in_flight = 0
        self.enabled = enabled  # 资源开关（resources[].enabled）
        self.access_mode = access_mode  # api | plan（决定 429 冷却默认时长）
        self.system_models: set[str] = set()
        #: 额度池（同 rid 的多个映射**共享同一个实例**）
        self.quota = quota if quota is not None else QuotaPool()
        #: 连接身份指纹（protocol + base_url + Key + 产品账号凭据的摘要，**不存明文**）：
        #: 用户改了凭据 / 重新登录 / 改绑账号 = 一条新的连接身份 → 运行态必须清零
        #: （见 `rebuild`；B-2：产品资源的凭据在账号目录，必须进这份指纹）
        self.src_fp = src_fp
        #: 这条冷却是不是**全局风控熔断**按住我的（2026-09-29 用户裁决「读时重判」）。
        #: 🔴 它不是"第三种状态"，只是 `cooldown` 的**成因来源**标记，且随冷却所有权一起变：
        #: 谁取得所有权（`bench()` 返回 True）谁声明成因 —— 额度耗尽 / 429 退避写的冷却
        #: 恒为 False，于是"熔断文件被删 → 读时重判"只放开熔断当初按住的那一类，
        #: 不会把仍在观察期里的 429 退避提前放行（红线：观察期内不得提前放行）。
        #: 运行态字段，不入配置（Q23-② 的"配置零新增字段"口径不受影响），不落盘。
        self.circuit_held = False

    @property
    def resource_id(self) -> tuple[str, str]:
        return (self.rid, self.vendor_model)

    @property
    def resource_id_str(self) -> str:
        return f"{self.label}/{self.vendor_model}"

    def has_quota(self) -> bool:
        """有效余量 > 0（未知额度视为有）。"""
        return self.quota.has_room()

    def available(self) -> bool:
        return self.status == "active" and self.enabled and self.has_quota()


#: 尾部被**写入时烘死**的恢复时刻（旧 `circuit.json`、以及 CLI 经 `/bench` 回传的
#: `circuit.reason()` 都会带一份"当时算出来的"时刻）
_CLOCK_SUFFIX = re.compile(r"[，,]\s*至\s*(?:明日\s*)?\d{1,2}:\d{2}\s*$")


def without_clock_suffix(text: str | None) -> str | None:
    """剥掉尾部烘死的「，至 HH:MM」/「，至 明日 HH:MM」，只留裸原因（验收 S-23）。

    恢复时刻必须**读时**渲染（PRD Q28-⑦）。原因串有两个来源会自带一份旧时刻：
    ① 上一版落盘的 `circuit.json`（时刻写在 reason 里）；② CLI 把 `circuit.reason()`
    POST 给 `/admin/api/zcode/bench`。不剥掉就会拼成「…，至 01:20，至 14:38」——
    一行里两个时刻、其中一个还是过去时间，用户照着判断何时重试必然判错。
    """
    if not text:
        return text
    return _CLOCK_SUFFIX.sub("", text).rstrip() or None


def fmt_recovery_clock(until_s: float, now_s: float | None = None) -> str:
    """冷却恢复时刻的可读标签：同日 `HH:MM`，跨午夜 `明日 HH:MM`（PRD Q28-⑦）。

    放在**运行态层**而不是熔断模块里，是因为它服务的两个出口共用一把尺：
    全局 3012 熔断（`upstream/zcode/quota.py` 的 `reason()`）与单条资源的
    「最近错误」列（`snapshot_by_resource`）—— 后者只有 `cooldown_until`，没有熔断对象。
    跨日只加「明日」不写日期：冷却最长 30 分钟，跨不过两天，写日期是增加解析成本。
    """
    then = time.localtime(until_s)
    now = time.localtime(now_s if now_s is not None else time.time())
    day = "明日 " if (then.tm_year, then.tm_yday) > (now.tm_year, now.tm_yday) else ""
    return f"{day}{time.strftime('%H:%M', then)}"


#: 状态严重度（聚合与取「最近错误」共用同一把尺）
#: `disabled`（401 判死 / 手动停用）高于 `cooldown`：判死的凭据不会自己恢复，
#: 只是暂时冷却会 —— 混在一起会让「最近错误」显示成无关紧要的那条。
_SEVERITY = {"invalid": 3, "disabled": 2, "cooldown": 1, "active": 0}


def _worst_error_entry(entries: list["ResourceState"]) -> "ResourceState | None":
    """资源级「最近错误」来自**最严重**的那条映射条目（返回条目本身，不只字符串）。

    🔴 为什么返回条目（验收 S-23）：恢复时刻要**读时**渲染，就得知道这条冷却到什么时候、
    现在还在不在冷却中 —— 只回字符串就把这两件事丢了。
    """
    with_err = [e for e in entries if e.last_error]
    if not with_err:
        return None
    return max(with_err, key=lambda e: (_SEVERITY.get(e.status, 0), e.C))


def _rendered_last_error(entries: list["ResourceState"], status: str,
                         remaining_ms: int) -> str | None:
    """「最近错误」列的一句话：裸原因 + **此刻读来成立**的恢复时刻（验收 S-23 → S-28 → S-31）。

    🔴 时刻由**墙钟**换算，而不是把 `cooldown_until` 直接交给 `time.localtime`（S-28）：
    `ResourceState.cooldown_until` 活在 `manager.clock` 的时间基里，而生产默认钟是
    `time.monotonic`（开机以来的秒数，量级几十万）。第八轮两个面板独立打到同一处：
    真 `create_app` 回环里界面写「至 10:53」，而当时 15:18、真实恢复 15:48，
    「明日」分支在生产几乎永不触发 —— 修了公式、错了时基，等于把谎报换了个数。

    🔴 用的剩余量是**同一行「冷却剩余」列正在显示的那个数**（聚合后的最大值，S-31）：
    原先钟点取自"最严重条目"自己的到期时间，而那一列取所有条目的最大值，
    同一行会出现「1800s 后自动回池」配「至 23:51」—— 两列各说一套，用户必须自己裁决。

    - 资源聚合状态是 `cooldown` 且剩余 > 0 → 追加 `，至 HH:MM` / `，至 明日 HH:MM`；
    - 其它状态（含判死、含已恢复）→ **只留原因**：S-15 定稿「最近错误」是历史线索，
      给历史行配一个已经过去的钟点就是谎报；`disabled`/`invalid` 更是没有"几点恢复"这回事。
    """
    e = _worst_error_entry(entries)
    if e is None or not e.last_error:
        return None
    if status == "cooldown" and remaining_ms > 0:
        wall = time.time()
        return f"{e.last_error}，至 " \
               f"{fmt_recovery_clock(wall + remaining_ms / 1000, wall)}"
    return e.last_error


#: 排障路线的**单一事实源**（验收 S-17）：哪一列长在哪个页面，只有这里说一次。
#: 原先「接入模型资源」/「网关模型管理」这类页名在 `main.config_warnings()` 与
#: `cli_setup._CAUSE_HINTS` 各写一份 —— 两处漂移时前端门照样全绿（它只验"文案原样透传"）。
ROUTE_POOL_PAGE = "「网关模型管理」页"      # 模型 ↔ 资源的映射、档位、优先级
RESOURCE_PAGE = "「接入模型资源」页"        # Key 接入侧资源的启用开关、Key
ACCOUNT_RESOURCE_PAGE = "「接入账号资源」页"  # 🔴 产品账号供给的资源（`product` 非空）只在这里管
OVERVIEW_HEALTH_PAGE = "「总览」页的资源健康表"   # 「最近错误」/「冷却剩余」两列在这里

#: 🔴 两类接入分流后的指路补语（2026-10-02 用户裁决：派生资源**完全不出现在**
#: 「接入模型资源」与「网关模型管理 › 资源池设置」两页，只由账号页的模型映射自动进
#: `/v1/models`）。原先这些提示统一说"到「接入模型资源」页"，对 `product` 非空的资源是
#: **死路**（那一页已经看不见它了）—— 指错页面等于把 503 的排障线索咽回去。
#: 判据与视图同源：`Resource.product` 非空（§22.5-2 互斥契约），前端 `api.js::isDerivedResource`。
PRODUCT_ROUTE_NOTE = (f"；由产品账号供给的资源不在该页显示——"
                      f"请到{ACCOUNT_RESOURCE_PAGE}对该账号重新登录或启用")



class ResourceRegistry(dict):
    """`ResourceManager.registry` 的容器（dict 子类）+ 随映射一起走的**装配侧判据**。

    🔴 为什么判据要搭在 registry 上（F-5，M6-6 Fix-γ）：`servable_models(config, registry)`
    是 `/v1/models`（`api/openai_compat.py`）与 `mgw setup`（`cli_setup.py`）共用的
    **唯一判据源**，它的入参只有 `(config, registry)` —— 把「该资源出站前提未注入」的
    谓词随 registry 一起递到判定点，两个调用方**零改动**，而 `core/` 不必 import
    `upstream/<product>/`（分层：判据本体在装配侧，见 `main.py::_outbound_premise_gap`）。

    `unservable_reason(resource) -> str | None`：**非 None** = 该资源当前不可服务
    （原因串，如 qoder 签名器 / zcode 验证码未注入、或装配面缺口 **F1**：空 `base_url` /
    适配器构造失败）→ 其映射不计入可服务；None = 无此缺口。
    **未注入（默认 None）= 无判据**，行为与本次改动前完全一致（CLI 进程 / 单测）。

    判据抛错 → 由 `servable_models` 按"不知道"处理（不据此隐藏模型）：
    隐藏而不解释 = 换一种静默，而判据自身的故障不是"模型不可服务"的证据。
    """

    #: 注入形态照 `ResourceManager.circuit_active`（装配侧的判据，core 只按接口询问）。
    unservable_reason: Callable[[Any], str | None] | None = None


def servable_models(config: AppConfig, registry: dict | None = None) -> set[str]:
    """**可服务**的网关模型集合（BUG-1 修正，v2.0 §12.1「消灭静默降级」）。

    🔴 判据 = 「至少有一条**已启用的资源映射**且其运行态未失效」。
    只看 `enabled` 是不够的：`/v1/models` 与 `mgw setup` 曾把「映射为空 / 资源全停用 /
    凭据已 invalid」的模型一并下发给工具 —— 工具选中即 `NO_RESOURCE`，
    **无报错的失败**正是本设计要消灭的那类缺陷。

    - 冷却中（`cooldown`）**仍算可服务**：只是临时避开，隐藏它会让模型从工具里凭空消失
    - 额度耗尽同样不隐藏（由 §17 的熔断回写走 `cooldown`/`bench` 路径表达）
    - `registry=None`（CLI 独立进程无内存态）→ 退化为纯配置判定，与网关侧同一份代码

    ⚠️ 因此这条判据**不需要**接"熔断读时重判"（2026-09-29 复核）：熔断回写落的是
    `cooldown`，而 `cooldown` 在本判据里一直是可服务 —— 重判真正影响的是
    **生效集/派发**（`pick_and_acquire`）与**总览那一行**（`snapshot_by_resource`），
    那两处才读 `status`/`available()`。把它接到这里只会多一次磁盘回读而无任何效果差异。

    🔴 F-5（M6-6 Fix-γ）+ F1（M6 面板修复轮-2）：registry 可携带**装配侧判据**
    `unservable_reason`（见 `ResourceRegistry`）——「产品资源出站前提未注入」（qoder 签名 /
    zcode 验证码）与「**没有可用出站适配器**」（空 `base_url` / 构造失败）的映射同样
    **不得对外声明**：工具选到它必然 503，正是 BUG-1 要消灭的"选了必失败"。
    """
    by_id = {r.id: r for r in config.resources}
    premise = getattr(registry, "unservable_reason", None)   # None = 无判据（旧行为）
    out: set[str] = set()
    for m in config.models:
        if not m.enabled:
            continue
        for ref in m.resources:
            r = by_id.get(ref.resource)
            if r is None or not r.enabled:
                continue
            # 🔴 映射关 ⇒ 不对外声明（/v1/models 与 setup 都不出）。判据与 `rebuild`
            # **同一条**（`AppConfig.mapping_enabled`，Q33-①）：两处各写一份就会分叉 ——
            # 账号侧看产品位、Key 接入侧看条目位。
            if not config.mapping_enabled(r, ref, m.name):
                continue
            if premise is not None:
                try:
                    if premise(r):
                        continue
                except Exception:  # noqa: BLE001 — 判据不可用 = 无证据；不据此隐藏模型
                    pass
            if registry is not None:
                st = registry.get((ref.resource, ref.model))
                if st is not None and st.status in ("disabled", "invalid"):
                    continue
            out.add(m.name)
            break
    return out


class ResourceManager:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.registry: ResourceRegistry = ResourceRegistry()
        # 每网关模型有序资源列表（优先序）；x 全局唯一（Q18-③）
        self.pools: dict[str, list[ResourceState]] = {}
        #: 额度池（按 rid 共享；跨热重载保留，与 registry 同口径）
        self.quotas: dict[str, QuotaPool] = {}
        self.x = 2  # 全局并发溢出生效集（rebuild 时从配置刷新）
        #: 🔴 号间轮转游标（Q33-③）：`网关模型 → 下一次选路的起点`（池内下标）。
        #: 有界：键集 ⊆ `self.pools` 的键集，`rebuild` 里随池一起回收（§22.8-9「无全局列表无界增长」）。
        #: 只影响"平局给谁"，不影响能不能被选中 —— 冷启动等价于游标 0（池首优先，旧行为）。
        self._cursor: dict[str, int] = {}
        #: 🔴 **活跃组**（Q33-③ 的两级开关配套，评审 R2-① 判死后的修正）：
        #: `网关模型 → 此刻正在承接流量的那批资源的 rid`，长度恒 ≤ x。
        #: 为什么光有游标 + 窗口不够：窗口是"从游标起 x 条"，但**排空一个号就把游标推到它之后**，
        #: 于是别的仍在途的号会落到窗口外，新流量照旧能在窗口里再开 x 个新号 ⇒
        #: 同时承接者可达 x+1、x+2……"最多 x 个资源并行"（用户指令 1 里 x 的定义）当场失效。
        #: 组把"当前这 x 条"固化成派发域：**只有组内成员能被派发**，组整体排空才让位给
        #: 游标方向的下一组 ⇒ 并行上限硬成立，串行仍逐号轮转。
        #: 有界：键集 ⊆ `self.pools` 的键集，值 ⊆ 该池的 rid ⇒ 与游标同在 `rebuild` 回收。
        self._groups: dict[str, list[str]] = {}
        #: **读时重判**的判据：「全局风控熔断此刻是否仍成立」（2026-09-29 用户裁决）。
        #: 🔴 分层：`core/` 不 import `upstream/zcode/`，所以判据由装配侧注入
        #: （`main.py` 的 `Runtime` 把 `zq.get_circuit().active` 包一层传进来）。
        #: None = 本进程没有熔断可判（CLI 独立进程 / 单测）→ 只做"到期归位"这一条释放。
        self.circuit_active: Callable[[], bool] | None = None
        #: 产品资源**凭据**的短哈希判据（B-2，M6-6 Fix-γ）：签名 `resource -> str`。
        #: 🔴 与 `circuit_active` 同一分层口径：`core/` 不 import `accounts/`
        #: （凭据读取走账号存储唯一入口），判据本体由装配侧注入（`Runtime`）。
        #: 未注入 / 判据抛错 → 空串（判据降级：连接身份仍含 product + account_ref，
        #: 读取失败不阻断 rebuild —— §22.8-6 失败隔离）。
        self.credential_fingerprint: Callable[[Any], str] | None = None
        #: 当前 `bench()` 的成因作用域（见 `circuit_hold()`）：作用域内取得的冷却 = 熔断按住。
        self._bench_held_by_circuit = False

    #: 「该资源出站前提未注入」的判据（F-5，M6-6 Fix-γ）——**写在 registry 上**：
    #: `servable_models(config, registry)` 是 `/v1/models` 与 `mgw setup` 共用的唯一判据源，
    #: 入参只有 registry，判据随它一起走（见 `ResourceRegistry`）。注入形态照 `circuit_active`。
    @property
    def unservable_reason(self) -> Callable[[Any], str | None] | None:
        return self.registry.unservable_reason

    @unservable_reason.setter
    def unservable_reason(self, premise: Callable[[Any], str | None] | None) -> None:
        self.registry.unservable_reason = premise

    def _credential_fp(self, r) -> str:
        """该资源的产品凭据短哈希（B-2 连接身份分量；判据降级 → 空串）。

        非产品资源（`product` 空）恒空串：它们的凭据就是配置里的 `api_key`，
        已在 `_conn_fingerprint` 的既有分量里。
        """
        if self.credential_fingerprint is None:
            return ""
        if not str(getattr(r, "product", "") or "").strip():
            return ""
        try:
            return str(self.credential_fingerprint(r) or "")
        except Exception:  # noqa: BLE001 — 判据读取失败只降级（不阻断 rebuild）
            return ""

    @contextmanager
    def circuit_hold(self):
        """声明"**这一段之内**由 `bench()` 取得的冷却，成因是全局风控熔断"。

        🔴 成因必须由写入侧**显式声明**，不靠 `reason` 字符串猜（猜文案 = 熔断原因一改，
        来源标记就悄悄错位）。调用侧是 `upstream/zcode/quota.py` 的
        `circuit_hold_scope()`（全局回写 / 启动对齐 / 管理端点三条熔断路径）。

        ⚠️ 作用域内**不得 `await`**：这是进程内一个布尔，跨 await 会让别的协程的
        普通冷却（额度耗尽 / 429 退避）被误登记成熔断按住。三条熔断回写路径全程同步，
        单线程事件循环内天然原子（与 `pick_and_acquire` 同一套理由）。
        """
        prev = self._bench_held_by_circuit
        self._bench_held_by_circuit = True
        try:
            yield
        finally:
            self._bench_held_by_circuit = prev

    def _pool_for(self, rid: str) -> QuotaPool:
        """取/建该**资源**的额度池（同 rid 的多个供应商模型名共享同一实例）。"""
        pool = self.quotas.get(rid)
        if pool is None:
            pool = QuotaPool()
            self.quotas[rid] = pool
        return pool

    # —— 配置同步（热重载保状态，tech §8-4）——
    def rebuild(self, config: AppConfig) -> None:
        res_index = {r.id: r for r in config.resources}

        new_pools: dict[str, list[ResourceState]] = {}
        referenced: set[tuple[str, str]] = set()

        for m in config.models:
            pool: list[ResourceState] = []
            for ref in m.resources:
                rid = (ref.resource, ref.model)
                referenced.add(rid)      # 仍算"被引用"：关掉的映射不回收状态，打开即恢复
                r = res_index[ref.resource]
                # 🔴 映射关 ⇒ **不进资源池**（调度取不到它）。判据唯一入口 =
                # `AppConfig.mapping_enabled`（Q33-①）：Key 接入侧看条目位、
                # 账号侧看**产品位**（含已停用的号，产品开关对它们同样有效）。
                if not config.mapping_enabled(r, ref, m.name):
                    continue
                state = self.registry.get(rid)
                fp = _conn_fingerprint(r, self._credential_fp(r))
                if state is None:
                    state = ResourceState(ref.resource, ref.model,
                                          label=display_label(r),
                                          vendor=vendor_label(r.preset, r.vendor, r.name, r.id),
                                          account=r.account,
                                          access_mode=r.access_mode,
                                          enabled=r.enabled,
                                          quota=self._pool_for(ref.resource),
                                          src_fp=fp)
                    self.registry[rid] = state
                else:  # 状态保留（C/冷却/in_flight），仅刷新可变属性
                    state.label = display_label(r)
                    state.vendor = vendor_label(r.preset, r.vendor, r.name, r.id)
                    state.account = r.account
                    state.enabled = r.enabled
                    state.access_mode = r.access_mode
                    if state.src_fp != fp:
                        # 🔴 连接身份变了（改了 Key / base_url，或产品资源**重新登录** /
                        # **改绑账号** —— B-2：凭据分量已进指纹）→ 运行态清零。
                        # `invalid`/`disabled` 是终态、冷却到期才回池，原先**没有任何**
                        # 恢复路径（面板 S-2「invalid/401 永不自愈」）：用户把失效的 Key
                        # 改对了，资源仍永远躺在生效集外，只能靠重启进程解决。
                        # tech §8-4 的"热重载保状态"保的是**同一条连接**的冷却计数，
                        # 换凭据已是另一条连接，保留旧判死结果没有意义。
                        state.status = "active"
                        state.cooldown_until = 0.0
                        state.C = 0
                        state.last_error = None
                        state.src_fp = fp
                        # 🔴 来源标记一起清（交付项"标记的清理"）：运行态清零之后留一个
                        # `circuit_held=True` 就是假阳性 —— 下一条**别的原因**的冷却
                        # 会被读时重判当成"熔断按住的"提前放开（第 1 号坑的同族）。
                        # 新建条目走 `__init__` 的默认 False，不经过这里。
                        state.circuit_held = False
                pool.append(state)
            new_pools[m.name] = pool

        # 清理无主状态（§4.3：配置删除全部引用时）
        for rid in list(self.registry):
            if rid not in referenced:
                del self.registry[rid]
        # 额度池随资源一并回收（资源被删 → 池不留，防残留余量被同名新资源复用）
        alive_rids = {s.rid for s in self.registry.values()}
        for rid in list(self.quotas):
            if rid not in alive_rids:
                del self.quotas[rid]
        # 引用集合重建（含被移除模型的名字）
        for state in self.registry.values():
            state.system_models = {m.name for m in config.models
                                   if any(rr.resource == state.rid and rr.model == state.vendor_model
                                          for rr in m.resources)}
        self.pools = new_pools
        self.x = config.scheduling.max_active_per_model
        # 轮转游标随池回收（§22.8-9 内存有界）：模型被删/改名后不留孤儿键。
        # 仍在的模型**保留游标** —— 热重载不该把轮转位置重置成"又从第一个号开始"，
        # 否则一次配置保存就把刚被用过的号排到队尾之后很久才再轮到，等于变相压低它。
        for name in list(self._cursor):
            if name not in new_pools:
                del self._cursor[name]
        # 活跃组同样随池回收，并且**成员必须在新的池里**（映射被关掉/资源被停用的成员
        # 不能继续当"占坑者"，否则组永远凑不满 x 条，x 被变相调小）。
        for name in list(self._groups):
            pool = new_pools.get(name)
            if pool is None:
                del self._groups[name]
                continue
            live = {s.resource_id for s in pool}
            kept = [rid for rid in self._groups[name] if rid in live]
            if kept:
                self._groups[name] = kept
            else:
                del self._groups[name]

    # —— 选路（§5.3 生效集 + Q33-③ 号间轮转；UT-22 场景 + 轮转场景）——
    def pick_and_acquire(self, system_model: str, exclude: set) -> ResourceState | None:
        """选路并在同一同步段完成在途 +1 与**额度预留**（v2.0 §19 M5-3）。

        exclude：本请求已尝试过的资源（故障切换目标选取时排除）。

        🔴 生效集 = **从轮转游标起、按池序取 x 条可用候选的滑动窗口**（Q33-③，
        推翻 §5.3 原「低负载集中调用、不轮询」的定论）。为什么必须滑动而不是固定前缀：
        一个模型下挂 10 个号、`x=2` 时，固定前缀会让**永远只有排在最前的 2 个号被用到**，
        其余 8 个号额度再多功能也轮不上 —— 用户要的「4 个号轮流调用」直接落空，
        而多号池化的真正收益是**额度与风控分摊**（§26 调研轮结论），不是并发上限。
        "窗口"在实现上是**活跃组**（`self._groups`）：组内成员就是本轮可被派发的资源，
        只有整组排空才让位 ⇒ 「任意时刻最多 x 个资源同时承接流量」这条既有定论成立
        （用户指令 1：x = 两类接入合计的"总的并行可用资源"）。

        集内取在途最少者（保留原「不堆同一个号」的性质）；**平局由游标决定**，
        于是空闲号之间按池序轮转：连续四条请求打同一模型、四个号都空闲 ⇒ 1/2/3/4 各一条。

        🔴 预留必须与 `in_flight += 1` 在**同一同步段**：单线程事件循环内这段不 await，
        因此天然原子 —— 这正是我们比参考项目强的地方（`16` §④：它们的选路无租约，
        并发请求可全部撞在同一个"剩余额度=1"的账号上，事后才按 429 纠偏）。

        🔴 **游标在"选中"时不推进，只在被选中的号**排空释放**时推进（见 `release`）**
        （Q33 评审 R2-① 判死后的修正）。选中即推进 = 每条并发请求都换一个新号，
        「任意时刻最多 x 个资源同时承接流量」这条既有定论直接被绕过
        （实测 x=1 / x=2 / x=3 三种配之下四个号同时在途 ⇒ x 形同虚设）。
        挪到排空时推进后两条要求同时成立：串行请求仍在一组号里轮着来（额度与风控分摊），
        并发时超出 x 的请求继续复用组内最闲的那个，承接者数不超过 x。
        """
        pool = self.pools.get(system_model)
        if not pool:
            return None
        now = self.clock()
        circuit_cleared = self._circuit_cleared()
        # 🔴 游标与旋转**只用一个索引空间 = 池下标**（Q33 自测抓出的实现错：先前把
        # "池下标存的游标"去对"过滤后的候选列表"取模，冷却/停用号一多就会把某些号永久跳过）。
        # 做法：先把**池**按游标环形旋转，再按既有顺序过滤可用者，窗口取过滤后前 x 条。
        n = len(pool)
        # 切换轮（`exclude` 非空）从池首开始：切换的语义是"刚试过 A，按优先级找替补"，
        # 跟着滑动会跳到窗口尾部，把用户排好的 ↑↓ 主备次序劫持掉（§5.3a 第 3 条）。
        start = 0 if exclude else self._cursor.get(system_model, 0) % n
        candidates = []
        for r in pool[start:] + pool[:start]:
            if r.resource_id in exclude:
                continue
            # 冷却到期归位（UT-10）+ 熔断读时重判 —— 与快照走**同一组动作**，
            # 不得两套语义（验收 S-15 / 2026-09-29 用户裁决）
            self._lift_for_read(r, now, circuit_cleared)
            if r.available():
                candidates.append(r)
        if not candidates:
            return None
        # —— 活跃组 = 本轮的**派发域**（≤ x 条并行）——
        # 🔴 仍在途的成员**不得被逐出记账**（复验轮 R4 阻塞项 A：先前只用"此刻可用候选"
        #    重过滤组 ⇒ 切换轮的 `exclude` 与成员冷却/停用都会把仍在途的号从组里抹掉，
        #    `release` 的"整组排空"因此看不见它，组重新凑满 x 条 ⇒ 承接者实测越出 x）。
        #    占名额 ≠ 可派发：在途但此刻不可用/被排除的成员继续占着组里的坑，只是本轮不给它派活。
        by_state = {s.resource_id: s for s in pool}
        held = [rid for rid in self._groups.get(system_model, ())
                if by_state.get(rid) is not None and by_state[rid].in_flight > 0]
        avail = {c.resource_id: c for c in candidates}
        group = list(held)
        if not exclude:
            # 常态轮：从游标方向（= `candidates` 的序）把组补齐到 x 条。
            # 切换轮**不扩组**：它的语义是"给刚失败的请求找替补"，扩组会把替补位
            # 永久占住在途之外，反而压低并行上限的严肃性。
            for c in candidates:
                if len(group) >= self.x:
                    break
                if c.resource_id not in group:
                    group.append(c.resource_id)
        in_group = set(group)
        self._groups[system_model] = group
        group_targets = [avail[rid] for rid in group if rid in avail]
        # 🔴 组内没有可派发的替补时（整组都在 exclude 里 / 都冷却了），切换轮才允许用**池外备胎**：
        #    宁可那一刻越出 x 一条，也不能让"明明有可用号"的请求吃 503
        #    —— 这是"最多 x 条并行"的唯一例外，tech §5.3a 第 3 条已如实登记。
        targets = group_targets
        if exclude and not group_targets:
            targets = [c for c in candidates if c.resource_id not in in_group]
        if not targets:
            return None
        # 组内取在途最少者（保留原「不堆同一个号」的性质）；平局保持**轮转序**
        # （`sorted` 稳定 ⇒ 首个最小值 = 游标方向最近的那个空闲号）
        order = sorted(range(len(targets)), key=lambda i: targets[i].in_flight)
        for i in order:
            best = targets[i]
            if self.reserve_quota(best):
                best.in_flight += 1
                # 🔴 这里**不推进游标**（推进在 `release` 的排空时刻）：选中即推进等于
                # 每条并发请求都换一个新号，x 的"最多 x 个资源同时承接"当场失效。
                if best.resource_id not in in_group:
                    group.append(best.resource_id)     # 备胎进组：它现在承接流量了
                return best
            # 预留失败 = 选中即耗尽（同一 tick 内已被并发占满）→ 按同序换下一个
        return None

    def release(self, state: ResourceState) -> None:
        """在途 -1；**活跃组整体排空时**才把轮转游标推到排空者之后并让组作废（Q33-③ 落点）。

        为什么在释放侧而不是选中侧推进：见 `pick_and_acquire` 的 🔴 段。
        🔴 为什么还要"整组排空"这个前提（评审 R2-①）：只要"某一个号排空"就换位，
        仍在途的同号会落到新窗口之外，而新窗口照样能开满 x 条 ⇒ 同时承接者 = x + 残留，
        "最多 x 个资源并行"被自己写的注释绕过。整组排空才换位 ⇒ 上限硬成立，
        串行请求仍然逐号轮转（一次一条时组里只有一个成员，排空即换位）。
        """
        if state.in_flight > 0:
            state.in_flight -= 1
        if state.in_flight != 0:
            return
        for model in state.system_models:
            pool = self.pools.get(model)
            if not pool:
                continue
            try:
                idx = pool.index(state)
            except ValueError:
                continue      # 映射已关 / 被移出池：没有位置可推进（不编一个位置出来）
            group = self._groups.get(model)
            if group is not None:
                by_rid = {s.resource_id: s for s in pool}
                # 组里还有谁在途 = 这一组还没服务完，不让位（新请求继续复用组内最闲的）
                if any(by_rid.get(rid) is not None and by_rid[rid].in_flight > 0
                       for rid in group):
                    continue
                del self._groups[model]
            self._cursor[model] = (idx + 1) % len(pool)

    # —— 状态变更 ——
    def bench(self, state: ResourceState, seconds: float) -> bool:
        """移出生效集 → 冷却至 `now+seconds`，返回**本次是否取得冷却所有权**。

        🔴 不变量一：**冷却只延长，不缩短**（`cooldown_until = max(旧, 新)`）。
        覆盖式写法让"后到的短冷却"能把先到的长冷却**就地剪短**：实测一轮 30 分钟的
        风控熔断 bench，被一次 60 秒的额度耗尽 tick 剪成 60 秒（熔断还剩 30 分钟，
        资源却已回到生效集 = 在风控观察期内提前放行）。
        调用方语义都是"至少冷却这么久"，没有任何一处需要"把冷却改短"。

        🔴 不变量二：**`invalid` / `disabled` 是终态，临时冷却不得把它改回可服务**。
        tech-design:140 定义 `disabled`=手动/401 停用、`invalid`=404 模型无效，
        :452 的生效集口径是"跳过 cooldown/disabled/invalid"。一旦 bench 把
        `invalid` 覆盖成 `cooldown`，到期就自动回池 —— 实测被 401 判死的凭据
        会重新被 `servable_models` 下发、被选中打上游（用户看到的"失效"和真实行为相反）。

        返回值即"谁 owns 这条冷却"的唯一裁决点：写 `last_error` 的一方必须问它，
        否则「最近错误」会被后到的短原因改写，用户在总览看到的挡路原因是假的。

        🔴 不变量三：**成因标记随所有权一起换**（2026-09-29 用户裁决「读时重判」）。
        取得所有权（`extended`）时把 `circuit_held` 重写成"本次调用是否声明了熔断成因"
        （见 `circuit_hold()`）；**没取得所有权时一个字都不动** —— 更长的旧冷却还在说话，
        它的成因仍然是旧的。这条不变量把第 1 号坑钉死：熔断之后又来了一个**更长**的
        429 退避（plan 档 18000s > 熔断 1800s），所有权转给退避 → 标记归假 →
        用户删掉 `circuit.json` 时**不会**把那条仍在观察期里的退避一起提前放行。
        """
        if state.status in ("invalid", "disabled"):
            return False
        until = self.clock() + seconds
        extended = state.status != "cooldown" or until > state.cooldown_until
        state.status = "cooldown"
        if extended:
            state.cooldown_until = until
            state.circuit_held = self._bench_held_by_circuit
        return extended

    def disable(self, state: ResourceState, reason: str = "") -> None:
        """判死（401 凭据被拒）。终态，不因冷却到期自动恢复（PRD Q28-⑥③）。

        🔴 `reason` 必须写进 `last_error`（验收 S-26③）：总览徽章写着
        "…或凭据被上游拒绝 401 —— 见「最近错误」列"，而原先这两条分支只改状态不记原因，
        用户照着提示去看那一列，读到的是空的 `—` —— 提示把人流放到了一个不存在的地方。
        """
        state.status = "disabled"
        if reason:
            state.last_error = reason

    def invalidate(self, state: ResourceState, reason: str = "") -> None:
        """判死（404 模型名无效）。终态，处置是换映射而不是换 Key。"""
        state.status = "invalid"
        if reason:
            state.last_error = reason

    def note_failure(self, state: ResourceState, error_summary: str) -> int:
        state.C += 1
        state.last_error = error_summary
        return state.C

    # —— 额度预扣（v2.0 §19 M5-3；粒度 = 资源 rid 的**共享池**）——
    def _pool_of(self, target) -> QuotaPool:
        """接受 `ResourceState` 或 rid 字符串，返回其共享额度池。"""
        if isinstance(target, str):
            return self._pool_for(target)
        return target.quota

    def set_quota(self, target, remaining: int | None) -> bool:
        """用上游快照覆盖某资源的余量，返回**是否发生变化**。

        直接覆盖，不做任何"只准变小"的守卫 —— 上游是权威（见 `QuotaPool` 的说明）。
        `remaining=None` → 未知/不限（不做额度管控，与 v1.6 行为一致，**向后兼容**）。
        """
        pool = self._pool_of(target)
        if pool.remaining == remaining:
            return False
        pool.remaining = remaining
        return True

    def reserve_quota(self, state: ResourceState) -> bool:
        """**事前预留** 1 单位（与 `in_flight += 1` 同一同步段，事件循环内天然原子）。

        🔴 故意**没有 `amount` 形参**：预留 / 结算 / 释放必须 1:1 对称。
        此前 `reserve_quota(amount=5)` 配 `settle/release` 硬编码减 1 → `reserved` 永久泄漏 4
        （验收 M-5）。生产永远是"一请求一预留"，多出来的自由度只是风险。
        """
        pool = state.quota
        if pool.remaining is None:
            return True
        if (pool.remaining - pool.reserved) < 1:
            return False
        pool.reserved += 1
        return True

    def settle_quota(self, state: ResourceState) -> None:
        """请求成功 → 释放该请求占的**一个预留**（与 `reserve_quota` 1:1 对称）。

        🔴 归还预留**不受 `remaining` 是否已知影响**（验收 L-2）：
        原先 `remaining is None` 就早退，于是"预留时还知道额度、结算前刷成了未知"
        会让 `reserved` 永久泄漏（闸门从此只减不加地挡调用）。
        只清预留；**不动 remaining**：上游快照才是权威，本地不伪造消耗。
        """
        state.quota.reserved = max(0, state.quota.reserved - 1)

    def release_quota(self, state: ResourceState) -> None:
        """失败时释放预留（**不扣额度**，该额度随后可再用）。同 `settle_quota`：
        额度变未知也不能不还预留。"""
        state.quota.reserved = max(0, state.quota.reserved - 1)

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
    def reconcile_expired(self) -> int:
        """把**已经不再成立**的 `cooldown` 归位为 `active`（读时判定，两条释放条件）。

        🔴 释放条件一 = **到期**（验收 S-4）：冷却恢复原先**只在选路时**懒翻转
        （`pick_and_acquire` 里那几行）。没有流量 → 快照长期显示
        `status=cooldown / cooldown_remaining_ms=0 / last_error="ZCode 额度耗尽"`，
        用户以为资源还锁着，实际早已可用。**0 剩余时间的冷却**本身就是"已经冷却完"
        这个事实的自证，不需要额外记账。

        🔴 释放条件二 = **熔断已不成立**（2026-09-29 用户裁决「读时重判」）：
        全局风控熔断落盘在 `circuit.json`，用户删掉它就是官方给的唯一手动出口，
        但界面上那一行原先要按写死的 `cooldown_until` 继续冻结（最长 30 分钟）且毫无反馈。
        现在**谁读谁重判**：`circuit_active()` 每次回读磁盘（`CooldownManager.active()`
        的既有机制，删文件后立刻为假），据此把**熔断当初按住的那些**条目放回生效集。
        不加 watcher、不做跨进程通知、不在别处另起第二处释放。

        返回被归位的条目数。归位动作本身在 `_lift_for_read`
        （选路与出快照**共用同一组动作**，验收 S-15）。
        """
        now = self.clock()
        circuit_cleared = self._circuit_cleared()
        return sum(1 for s in self.registry.values()
                   if self._lift_for_read(s, now, circuit_cleared))

    def _circuit_cleared(self) -> bool:
        """读时重判的前提：装配侧接了判据 **且** 熔断当前**不成立**。

        🔴 四种情形只在这一处裁决：
        - 没接判据（CLI 独立进程 / 未装配的单测）→ False：不重判，行为与本次改动前一致；
        - 判据说"仍在熔断" → False：观察期内绝不提前放行（反向红线）；
        - 判据**抛错** → False：fail-closed，与 Q28-⑧①「状态文件读不动按熔断拒跑」同向；
        - `circuit.untrusted`（文件读不动）→ 判据 `active()` 本身就返回 True
          （未知按最坏处理是 `CooldownManager.active()` 的既有口径），
          所以这里**不特判第二遍**，"读不动一律不释放"自动成立。
        """
        if self.circuit_active is None:
            return False
        try:
            return not bool(self.circuit_active())
        except Exception:  # noqa: BLE001 — 判据不可用 = 不知道，不知道就不放开
            return False

    def _lift_for_read(self, state: ResourceState, now: float, circuit_cleared: bool) -> bool:
        """读路径的归位动作（两条读取路径共用，验收 S-15 的口径延伸到第二个条件）。"""
        if self._lift_if_expired(state, now):
            return True
        return self._lift_if_circuit_cleared(state, circuit_cleared)

    def _lift_if_expired(self, state: ResourceState, now: float) -> bool:
        """到期的 `cooldown` → `active`，返回**本次是否归位**。

        🔴 两条读取路径（`pick_and_acquire` 选路 / `snapshot_by_resource` 出快照）
        必须共用这一个动作（验收 S-15）：原先一个清 `last_error`、一个不清，
        有流量的资源恢复后就被永久钉在旧故障原因上。
        ⚠️ **不清 `last_error`**：这一列的语义是「最近错误」（design-spec §2.1 的历史位），
        不是「当前故障」——"现在能不能用"由 `status` 与「冷却剩余」表达，
        "刚才发生过什么"必须留着，否则几十分钟后用户事后无任何可查痕迹
        （面板 ix §4 第 4 条）。
        ⚠️ **要清 `circuit_held`**（交付项"标记的清理"）：熔断按住的冷却自然到期后，
        留着标记就是假阳性 —— 下一条**别的原因**（额度耗尽 / 429 退避）的短冷却
        会被读时重判当成"熔断按住的"提前放开（第 1 号坑）。
        """
        if not (state.status == "cooldown" and now >= state.cooldown_until):
            return False
        state.status = "active"
        state.circuit_held = False
        return True

    def _lift_if_circuit_cleared(self, state: ResourceState, circuit_cleared: bool) -> bool:
        """熔断已不成立 → 把**熔断按住的那条冷却**当场归位，返回本次是否归位。

        🔴 与 `_lift_if_expired` 同口径的三点（2026-09-29 用户裁决）：
        - **只放成因是熔断的冷却**（`circuit_held`）：额度耗尽 / 429 退避的冷却由各自的
          时长说话，一次删文件动作不得把它们提前放行（第 1 号坑）；
        - **不看 `cooldown_until`** —— 这一条存在的全部理由就是"墙上的钟点还是旧的、
          而熔断已经不成立"；仍然按那个钟点冻着，就是用户照官方出口操作却得不到反馈；
        - **不清 `last_error`**（S-15 / PRD Q28-⑦①）：恢复后那一列留作历史线索，
          但**不再配任何钟点** —— `_rendered_last_error` 只在"状态是 cooldown 且剩余 > 0"
          时才追加时刻，状态回到 `active` 就自然只剩裸原因。
        - `invalid` / `disabled` 是**终态**（PRD Q28-⑥③）：状态不是 `cooldown` 一律不动，
          本次改动没有任何路径把终态变回 `active`。
        """
        if not circuit_cleared or not state.circuit_held:
            return False
        if state.status != "cooldown":
            return False
        state.status = "active"
        # 熔断那份旧钟点作废：资源已回到生效集，留着它下一次快照/选路都不该再读到一个未来时刻
        state.cooldown_until = 0.0
        state.circuit_held = False     # 解除后不得残留成假阳性
        return True

    def snapshot_by_resource(self, config: AppConfig) -> list[dict]:
        """按资源聚合快照（总览「资源健康」/「资源总数」口径：资源 = 供应商+账号+Key，
        一行一资源；映射条目 (rid, vendor_model) 的运行态聚汇到所属资源）。

        资源级状态聚合：**资源开关关闭 → disabled**；条目里**任一 active → active**
        （资源仍可承接，其余条目的故障走「最近错误」列）；全非 active 时取**最严重**的
        条目状态（invalid > disabled > cooldown）。
        🔴 不取"全部非 active 即 cooldown"那种写法（验收 S-2）：条目级 `disabled`
        （401 判死）会被折成 `cooldown`，徽章显示"剩余 0s"、同行「冷却剩余」是 `—`，
        而同页横幅却说"凭据失效" —— 同一屏两处互相打脸。
        C 取条目最大值，in_flight 求和。

        🔴 这一行读的是**此刻成立**的状态：`reconcile_expired()` 在这里做两条释放
        （到期 / 熔断已不成立），所以用户删掉 `circuit.json` 后**下一次出快照**
        就看到那一行回到 `active`，不再等旧钟点（2026-09-29 用户裁决「读时重判」）。
        """
        self.reconcile_expired()
        by_rid: dict[str, list[ResourceState]] = {}
        for s in self.registry.values():
            by_rid.setdefault(s.rid, []).append(s)
        out = []
        for r in config.resources:
            entries = by_rid.get(r.id, [])
            if not r.enabled:
                status = "disabled"
            elif entries and any(e.status == "active" for e in entries):
                status = "active"      # 任一条目可承接 = 资源可用（其余条目的故障见「最近错误」）
            elif entries:
                status = max((e.status for e in entries),
                             key=lambda st: _SEVERITY.get(st, 0))
            else:
                status = "active"
            remaining_ms = max((self.cooldown_remaining_ms(x) for x in entries),
                               default=0)      # 「冷却剩余」列与恢复时刻**同一个数**（S-31）
            out.append({
                "rid": r.id,
                "name": display_label(r),      # 与 `resource_id_str` 同一把尺（评审 R11）
                "vendor": vendor_label(r.preset, r.vendor, r.name, r.id),
                "account": r.account,
                "status": status,
                # 可用 = 开关开启且状态正常（能承接请求）
                "available": status == "active",
                "C": max((e.C for e in entries), default=0),
                "in_flight": sum(e.in_flight for e in entries),
                "cooldown_remaining_ms": remaining_ms,
                # 🔴 熔断/失败原因（design-spec §2.1 资源状态表要求的「最近错误」列）
                "last_error": _rendered_last_error(entries, status, remaining_ms),
                "models": len(entries),
            })
        return out
