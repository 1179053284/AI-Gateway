"""**承接资格闸门**（2026-10-05 用户裁定，PRD Q39）：一条供应商通道此刻**有没有资格**被派发。

这是「没有额度的号就不该纳入可用调用范围」那句话说到底的唯一实现点。
放 `core/` 而不是任何 `upstream/<product>/`：阈值按**量纲**走，而量纲是跨产品的
（zcode 是 token，buddy / lobsterai / loomy / trae / workbuddy / qoder 是积分），
长在某个产品里就会变成"第二条路径算第二种额度"。

判定式（自上而下，先命中先定）：

1. **上游明确否认**（`reason == "no_plan"`：`200 + code=0 + plans/balances 皆空`）⇒ `False`。
2. **逐包阈值触底**（下面的"量纲阈值"表）⇒ 全部在册包都低于各自阈值 ⇒ `False`；
   只要有一个包没触底（含余量未知）⇒ `True`。**余量为负（透支）与量纲无关，直接计触底**
   （2026-10-11 P2-6：实盘 cline「余额」包 `remaining=-33270, unit=""`，旧逻辑因"认不出
   量纲 ⇒ 无权判定"落到第 ③ 条放行，靠上游 403 兜底白跑往返）。
3. **正向三态**：`state ∈ {available, exhausted}` 且没有第 1/2 条证据 ⇒ `True`
   （`exhausted` = 上游给了包但这一窗口用完，仍是"有承接资格"的账号，`remaining=0` 那条
   既有闸门会挡它，不在这里重复判定）。
4. **其余一律 `None` = 不动闸门** —— `unreachable / circuit / expired / no_credentials /
   no_identity / ""` 都是**没查到**，不是"上游说没有"。与 `quota.remaining_units()` 的
   「未知不当 0」同一纪律：一次网络抖动不许封掉整条产品线。

🔴 量纲阈值（用户 2026-10-05 定的两个数，缺省=不设阈值）：

| 量纲 | 识别的单位串（小写去空格后） | 阈值 | 触底即剔 |
| --- | --- | --- | --- |
| token | `token` `tokens` | **< 10000**（1 万） | 是 |
| 积分 | `credit` `credits` `积分` `点` | **< 50** | 是 |
| 认不出单位（空串 / 美元 / 次数…） | —— | **不设阈值** | 否（宁可宽松，不编数） |

⚠️ 边界与代价（都写在台账里，不在代码里藏）：

- 包上 `active=False`（已失效/已过期）**不参与**"全部触底"的计算 —— 一个号只剩过期包
  等于没有包，走第 1/3/4 条，不该由阈值说了算。
- 认不出量纲时**不设阈值**：这是刻意的宽松方向。反过来（把认不出的当积分）会拿 50 去卡
  一个单位是"次"或"美元"的号，属于编造事实。唯一例外 = **负余量**：透支不需要认识单位
  （任何量纲下都不可能达标，2026-10-11 P2-6）。
- 已知的**呈现缺口**（登记为债，见台账 §7 债 Q39-债1）：总览的 `available` 是
  `status == "active"` 的视图位，不含资格与额度 ⇒ 被本闸门剔出的号在界面上仍显示「可用」。
  补这一格要动 `snapshot_by_resource` 的聚合与界面文案，属独立一刀。
"""

from __future__ import annotations

from typing import Any

#: token 制：余量低于这个数 ⇒ 剔出可用范围（用户 2026-10-05 定的「1 万」）
TOKEN_FLOOR = 10_000
#: 积分制：余量低于这个数 ⇒ 剔出可用范围（用户同日定的「50」）
CREDIT_FLOOR = 50

#: 单位串 → 阈值（唯一一份；界面与闸门读的是同一个数）
_UNIT_FLOORS: dict[str, tuple[str, int]] = {
    "token": ("token", TOKEN_FLOOR),
    "tokens": ("token", TOKEN_FLOOR),
    "credit": ("credits", CREDIT_FLOOR),
    "credits": ("credits", CREDIT_FLOOR),
    "积分": ("credits", CREDIT_FLOOR),
    "点": ("credits", CREDIT_FLOOR),
}


def unit_floor(unit: Any) -> tuple[str, int] | None:
    """把一个包的单位归一成 `(量纲名, 阈值)`；认不出 ⇒ `None`（**不设阈值**）。"""
    key = str(unit or "").strip().lower()
    return _UNIT_FLOORS.get(key)


def _packages(snap: Any) -> list[dict]:
    """把两种证据形状归一成「逐包清单」：账号层快照的 `items` 或 zcode 快照的 `buckets`。"""
    items = getattr(snap, "items", None)
    if items:
        return [dict(i) for i in items if isinstance(i, dict)]
    buckets = getattr(snap, "buckets", None)
    if buckets:
        return [{"remaining": getattr(b, "available", None),
                 "unit": getattr(b, "unit_type", ""),
                 "active": True} for b in buckets]
    return []


def below_floor(snap: Any) -> bool | None:
    """**逐包阈值**这一条证据怎么说：`True` = 全部在册包都触底，`False` = 至少一个没触底，
    `None` = 没有可判定的包（没包 / 全部余量未知 / 全部认不出量纲）。"""
    judged = 0
    for p in _packages(snap):
        if p.get("active") is False:
            continue                     # 已失效的包不贡献"还有余量"，也不参与触底判定
        floor = unit_floor(p.get("unit"))
        rem = p.get("remaining")
        if floor is None:
            # 🔴 2026-10-11 P2-6：负余量（透支）与量纲无关 —— rem<0 在任何量纲下都
            #    不可能达标，不需要认识单位就能下结论。实盘根因（cline-8881b795）：
            #    余额包 {name:"余额", remaining:-33270.0, unit:""}，旧逻辑因"认不出
            #    量纲 ⇒ 无权判定"落到第③条 exhausted=True，闸门开着放行，靠上游
            #    403 兜底白跑往返。0 与正数仍不判（无换算依据不编造），宽松方向不变。
            if isinstance(rem, (int, float)) and not isinstance(rem, bool) and rem < 0:
                judged += 1
            continue
        if rem is None:
            continue                     # 上游没给余量 ⇒ 这条包无权判定
        judged += 1
        if rem >= floor[1]:
            return False                 # 有一个没触底就够了
    return True if judged else None


def reason_of(snap: Any) -> str:
    """资格被关闭时的**原因串**（进日志用；界面那一格是债 Q39-债1，不在这里造新档位）。

    只说这一条判据真的知道的事，各关闭原因分开写 —— 混成一句"额度不足"会把
    "上游说这号没有套餐"、"包快见底"与"余额透支为负"几种完全不同的处置揉成一团。
    """
    if str(getattr(snap, "reason", "") or "") == "no_plan":
        return "上游明确回复无套餐（200 + code=0 + plans/balances 皆空）"
    pairs: set[str] = set()
    negs: set[str] = set()
    for pkg in _packages(snap):
        found = unit_floor(pkg.get("unit"))
        rem = pkg.get("remaining")
        if found is not None:
            if rem is not None and rem < found[1]:
                pairs.add(f"{found[0]}<{found[1]}")
        elif isinstance(rem, (int, float)) and not isinstance(rem, bool) and rem < 0:
            negs.add(f"余量为负（{rem:g}）")
    parts: list[str] = []
    if pairs:
        parts.append(f"全部在册额度包均低于量纲阈值（{'、'.join(sorted(pairs))}）")
    if negs:
        parts.append("、".join(sorted(negs)))
    return "；".join(parts)


def entitled_for(snap: Any) -> bool | None:
    """这条通道此刻**有没有承接资格**（`False` 剔出可用范围 / `True` 保留 / `None` 不动）。

    两条腿（zcode 的量化余量与其余产品的三态）都调这**同一个函数**，
    避免出现"两条路径判两种资格"。
    """
    if str(getattr(snap, "reason", "") or "") == "no_plan":
        return False                                  # ① 上游明确否认
    drained = below_floor(snap)
    if drained is not None:
        return not drained                            # ② 逐包阈值说了算（优先于三态的 available）
    if not getattr(snap, "reason", "") and str(getattr(snap, "state", "") or "") in (
            "available", "exhausted"):
        return True                                   # ③ 上游说了有包（哪怕这一窗口用完）
    return None                                       # ④ 没查到 ⇒ 不动闸门
