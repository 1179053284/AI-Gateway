"""TRAE 额度（积分）快照 —— `POST /trae/api/v2/pay/ide_user_ent_usage`。

协议（`trae-credits.ts:26-38` 的文件头 + `:316-381` 的 `fetchTraeCreditBalance`）::

    POST {UG_HOST}/trae/api/v2/pay/ide_user_ent_usage
    body {"require_usage": true, "req_source": 2}
    → {user_entitlement_pack_list: [{entitlement_base_info: {display_desc,
         quota: {credits_limit}}, usage: {credits_amount}, expire_time}, …]}
    remain = Σ(credits_limit − credits_amount)   （只算 credits_limit > 0 的包）

🔴 三态纪律（§22.3 + `23 B2`「**未知不当零**」）：
   查不动 / 结构变了 → `unknown`；**查到了且确实为 0** → `exhausted`。把前者报成后者
   会让调度据此跳过账号（而它其实还有额度）。

⚠️ 请求头用**签到专用完整头**（`trae.ts:281-314`）：上游的积分端点认
   `X-Market-User-Id` / `X-Device-Id`（15 位派生）等一整套客户端形态头
   （`trae-credits.ts:311-318` 原文：请求头齐全 + 基于 uid 的设备身份）。
"""

from __future__ import annotations

import datetime

import httpx

from model_gateway.accounts import net
from model_gateway.accounts.types import QuotaSnapshot
from model_gateway.upstream.trae import const, protocol


class BalanceResult:
    """余额查询结果（`ok=False` = 查不动，**不得**当 0 处理）。"""

    __slots__ = ("ok", "total", "pack_count", "detail", "packages")

    def __init__(self, *, ok: bool, total: float = 0.0, pack_count: int = 0,
                 detail: str = "", packages: list[dict] | None = None) -> None:
        self.ok = ok
        self.total = total
        #: 计入总额的有效包数量（`credits_limit > 0`）。
        self.pack_count = pack_count
        self.detail = detail
        #: 逐包结构（2026-10-01 加字段）：`{name, unit, remaining, total, used,
        #: active, expires_at}`——`display_desc` 即套餐表达（「每月登录赠送」等），
        #: `expire_time` 是**秒级** Unix（`trae-credits.ts:352-360`，须归一化成 ISO）。
        self.packages = packages or []


async def fetch_balance(cred: dict, uid: str) -> BalanceResult:
    """查积分余额（`trae-credits.ts:316-381` 的移植）。

    `uid` 为空时**不发请求**（上游接受不了空身份：`trae-credits.ts:150-152` 回
    「缺少 user_id，无法构造设备身份」）。
    """
    access_token = protocol.read_str(cred, "access_token")
    if not access_token:
        return BalanceResult(ok=False, detail="凭据缺少 access_token（未登录，未发请求）")
    if not uid:
        return BalanceResult(ok=False, detail="凭据缺少 uid（无法构造签到设备身份，未发请求）")
    try:
        async with net.make_client(timeout=const.REQUEST_TIMEOUT_S) as client:
            response = await client.post(
                f"{const.UG_HOST}{const.PATH_ENT_USAGE}",
                headers=protocol.checkin_headers(access_token, uid),
                json=dict(const.BALANCE_BODY))
    except httpx.HTTPError as e:
        return BalanceResult(ok=False, detail=f"余额查询网络错误：{e}")
    if response.status_code != 200:
        return BalanceResult(ok=False, detail=f"余额查询 HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        return BalanceResult(
            ok=False,
            detail="响应不是 JSON（凭据失效时网关会回 HTML 错误页）")
    if not isinstance(body, dict):
        return BalanceResult(ok=False, detail="余额响应不是对象")
    pack_list = body.get("user_entitlement_pack_list")
    if not isinstance(pack_list, list) or not pack_list:
        # DSH 同判据（`trae-credits.ts:330-331`）：拿不到资源包列表 → 无法判定额度
        return BalanceResult(ok=False, detail="响应缺少 user_entitlement_pack_list（结构变更？）")
    total = 0.0
    counted = 0
    packages: list[dict] = []
    for item in pack_list:
        if not isinstance(item, dict):
            continue
        base = item.get("entitlement_base_info")
        quota = base.get("quota") if isinstance(base, dict) else None
        if not isinstance(quota, dict):
            continue
        credits_limit = protocol.read_num(quota, "credits_limit")
        if credits_limit is None or credits_limit <= 0:
            continue
        usage = item.get("usage")
        used = protocol.read_num(usage, "credits_amount") if isinstance(usage, dict) else None
        remaining = credits_limit - (used or 0.0)
        total += remaining
        counted += 1
        desc = base.get("display_desc") if isinstance(base, dict) else ""
        expire_s = protocol.read_num(item, "expire_time") if isinstance(item, dict) else None
        packages.append({
            "name": str(desc or "资源包"),
            "unit": const.BALANCE_UNIT,
            "remaining": remaining,
            "total": credits_limit,
            "used": used,
            "active": True,
            "expires_at": (datetime.datetime.fromtimestamp(expire_s)
                           .isoformat(timespec="seconds") if expire_s else ""),
        })
    return BalanceResult(ok=True, total=total, pack_count=counted, packages=packages,
                         detail=f"资源包 {counted} 个（共 {len(pack_list)} 条）")


async def quota(cred: dict, meta: dict) -> QuotaSnapshot:
    """额度快照（§22.3 三态 + `source`）。

    - `available`：查到 `total > 0`；
    - `exhausted`：查到资源包列表**非空**但有效包合计为 0（确实没有可用额度）；
    - `unknown`：未登录 / 缺 uid / 网络或结构问题 —— **未知不当零**。
    """
    source = "trae-ent-usage"
    uid = protocol.read_str(cred, "uid") or protocol.read_str(meta, "uid")
    balance = await fetch_balance(cred, uid)
    if not balance.ok:
        return QuotaSnapshot(state="unknown", source=source, detail=balance.detail)
    if balance.total > 0:
        return QuotaSnapshot(
            state="available", source=source,
            detail=f"有效资源包 {balance.pack_count} 个，剩余 {balance.total:g} {const.BALANCE_UNIT}",
            plan=(balance.packages[0]["name"] if balance.packages else ""),
            items=tuple(balance.packages))
    return QuotaSnapshot(
        state="exhausted", source=source,
        detail=f"资源包不含可用额度（有效包 0 个，{balance.detail}）")
