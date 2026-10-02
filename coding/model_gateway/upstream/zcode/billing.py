"""zcode 额度的**联网取数**通道（方案 `20261002-zcode-quota-and-refresh.md` §3）。

一句话职责：**只回答"上游这一轮说了什么"** —— 不判熔断、不建熔断、不写盘、不归一化时间。
熔断与节奏归 `product.quota`，写盘分档归 `ops/builtin/query_balance`，ISO 归一化归钩子
（`accounts/types.py` 的 items 键契约原文就把"归一化成 ISO"定为**钩子的责任**）。

## 🔴 为什么需要这个模块（此前 zcode 额度"一直没有数据"的真因）

`upstream/zcode/quota.py` 的旧注释写着「不走联网：额度/权益接口需 `X-Client-Sig/Nonce/Pow`
私钥握手 + PoW，**脚本无法复刻**」—— 这句结论**从未被实测过**，于是网关只读客户端日志；
而 16 个在册账号的目录里**一个 `.log` 都没有**（日志是官方客户端跑出来的，导入号只带凭据快照）
⇒ 额度列必然空。

2026-10-02 用**公共层同一套凭据**（`store.hook_meta` + `product.outbound_credentials` +
`auth.build_headers("jwt", …)`）直连实测：**16/16 号 `GET /billing/balance` 全部 HTTP 200 / code=0**，
单请求 ≈0.1s，其中 6 号当场返回真实 token 数值（含 1 号 `available_units=0` 的自然耗尽）。
原始响应体逐字存档：`docs/changes/e2e-records/E2E-20261002-zcode-quota-probe.md` §6.1–§6.3。
⇒ "无法复刻"在**这条只读 GET** 面上被证伪（推理面/captcha 面仍未测，D1 的其余子问题原样保留）。

## 形状事实（同一份台账 §6.4，别按实现倒推）

- **网络响应体**顶层就是 `{code, msg, data:{server_time, plans, balances}, logid}`，
  **没有 `payload` 包** ⇒ `quota.normalize_remote` 读 `body["data"]` 对本通道**本来就是对的**，
  不改它。（`payload` 只存在于**客户端日志记录**里 —— 那是另一条通道，见 `quota._unwrap_log_record`。）
- `server_time` / `period_start` / `period_end` / `expires_at` **全是秒级整数 epoch**（不是 ISO、不是毫秒）。
- `available_units` 与 `remaining_units` 同时存在且相等 ⇒ **`available_units` 是唯一聚合来源**；
  `remaining_units` 只进展示，不参与求和、不作回退。缺 `available_units` = "未给出"，
  **绝不拿 `total - used` 当可用**（`18` §④ 的老纪律）。
- 顶层 `plans[]` 带 `user_plan_id`，日志记录的顶层摊平 `plans[]` **不带** ⇒ 串号防护的主键
  由本通道产出并落盘（`QuotaSnapshot.plan_key`），日志腿再拿它去过滤。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from model_gateway.accounts.net import make_client
from model_gateway.upstream.zcode import auth, oauth
from model_gateway.upstream.zcode import quota as zq

#: 额度端点 = `product.PROBE_PATH` 的同一个只读 GET（**同 path 同方法同鉴权**）。
#: 两处必须一致 ⇒ 由 `tests/unit/test_zcode_billing.py` 的常量对账断言钉住
#: （改了探活路径没改额度路径 = 静默分叉；本模块顶层不能 import `product`，那是反向依赖成环）。
BALANCE_PATH = "/billing/balance"

#: 超时与探活同档（`product.PROBE_TIMEOUT_S`）：显式超时是纪律（§22.8-1），不放任默认无限等待。
TIMEOUT_S = 20.0

@dataclass(frozen=True)
class BillingResult:
    """一次额度查询的**原始事实**（数值仍是上游量纲，时间仍是 epoch 整数）。

    - `ok`             取到 plans/balances（`buckets` 非空或至少 plans 非空）
    - `no_plan`        200 + `code=0` + 认证过的 JWT + `plans==[] && balances==[]`
                       ⇒ 上游明确"这个身份当前没有套餐记录"（界面档 =「无套餐」）
    - `expired`        HTTP 401/403（凭据被上游拒绝 → 需重新登录或导入）
    - `risk_control`   3012 / 429 / 405 / 5xx / `quota.looks_like_risk_control(msg)` 命中
                       ⇒ **调用方**据此建全局熔断；本模块不 `enter()`、不写熔断文件
    - `unreachable`    网络异常、非 2xx 的其他情形、非 JSON 的 200（WAF 页等）、`code!=0` 的业务失败
                       🔴 200 但**看不出是余额响应**时落这里而不是 `ok`：状态码 200 ≠ 取到了
                       （`product.probe` 里同一判据的既有姿势，fail closed，§22.8-5）
    """

    kind: str
    http_status: int = 0
    code: object = None
    msg: str = ""
    plan: str = ""
    plan_key: str = ""                                    # 上游 `user_plan_id`（串号防护主键）
    buckets: tuple[zq.Bucket, ...] = ()
    server_time: int | None = None                        # epoch 秒（**不**归一化）
    detail: str = ""
    raw: dict = field(default_factory=dict, repr=False)   # 只给单测/台账，不进任何出口

    @property
    def spoke(self) -> bool:
        """上游这一轮**有没有说话**（决定 §4-1 的写盘分档：说话→覆盖，没说→合并写）。"""
        return self.kind in {"ok", "no_plan", "expired"}

    @property
    def risk_controlled(self) -> bool:
        return self.kind == "risk_control"


async def _http_get_balance(jwt: str, device_mid: str, *, base_url: str) -> httpx.Response:
    """本模块**唯一**的 HTTP 落点（单测 monkeypatch 这里，或按 `make_client` 注入假传输）。

    鉴权头一律经 `auth.build_headers`（三参齐全：`mode, creds, *, app_version`；
    缺 `X-Device-Mid` 上游回 400/3001 这一事实也由同一处承载，见 `auth.py:53-71`）。

    🔴 `base_url` 由调用方（`product.quota` → `product._plan_base()`）**注入**，本模块不自己解析配置：
    基址的唯一实现留在 `product`（`billing` 顶层不能 import `product` —— 那是反向依赖，会成环）。
    """
    headers = auth.build_headers("jwt", auth.Credentials(jwt=jwt, device_mid=device_mid),
                                 app_version=oauth.DEFAULT_APP_VERSION)
    async with make_client(base_url=base_url, headers=headers, timeout=TIMEOUT_S) as client:
        return await client.get(BALANCE_PATH,
                                params={"app_version": oauth.DEFAULT_APP_VERSION})


def classify(response: httpx.Response | None, body: dict,
             error: Exception | None = None) -> BillingResult:
    """一次出站结果 → `BillingResult`。**纯函数**：不碰网络、不碰盘，故 §6 的 9 格能逐格单测。

    判据顺序是**有意的**：异常 → 风控信号（429/405/5xx 必须落到熔断面，不能被"未知"吞掉，
    方案 §3-7 / PM r4 B-R4-3 的"触发器要有生产者"）→ 鉴权 → 2xx/业务码 → 数值 → 空数组。
    """
    if error is not None:
        return BillingResult(kind="unreachable",
                             detail=f"网络不可达：{type(error).__name__}: {error}")
    status = int(getattr(response, "status_code", 0) or 0)
    code = body.get("code")
    msg = str(body.get("msg") or "")

    if (code == zq.CODE_RISK_CONTROL or zq.looks_like_risk_control(msg)
            or status in (429, 405) or status >= 500):
        # detail 必须带**上游原话 + HTTP 数字**：否则 429 事后不可证（方案 §10-6 的观察期靠它）
        return BillingResult(kind="risk_control", http_status=status, code=code, msg=msg,
                             detail=f"上游风控信号（HTTP {status}"
                                    f"{'，code=' + str(code) if code is not None else ''}）："
                                    f"{msg or '无文案'}")
    if status in (401, 403):
        return BillingResult(kind="expired", http_status=status, code=code, msg=msg,
                             detail=f"凭据被上游拒绝（HTTP {status}）→ 需重新登录或导入")
    if status and not 200 <= status < 300:
        return BillingResult(kind="unreachable", http_status=status, code=code, msg=msg,
                             detail=f"非 2xx（HTTP {status}）：{msg or '无文案'}")

    data = body.get("data")
    if not isinstance(data, dict):
        return BillingResult(kind="unreachable", http_status=status or 200, code=code, msg=msg,
                             detail="响应体不是额度对象（200 不等于取到，§22.8-5 fail closed）")
    if code not in (0, None, "0"):
        return BillingResult(kind="unreachable", http_status=status or 200, code=code, msg=msg,
                             detail=f"上游 code={code}：{msg or '无文案'}")

    plans = [p for p in (data.get("plans") or []) if isinstance(p, dict)]
    balances = [b for b in (data.get("balances") or []) if isinstance(b, dict)]
    server_time = _epoch(data.get("server_time"))
    buckets = tuple(b for b in (zq.bucket_from_balance(x) for x in balances) if b is not None)
    plan = str((plans[0] or {}).get("name") or "") if plans else ""
    plan_key = ""
    for p in plans:                                     # 主键取**active** 那一条的 user_plan_id
        if str(p.get("status") or "") == "active" and p.get("user_plan_id"):
            plan_key = str(p.get("user_plan_id"))
            break
    if not plan_key and plans:
        plan_key = str(plans[0].get("user_plan_id") or "")

    if not plans and not balances:
        # 🔴 判据来源限定（方案 §3-1）：**只有网络通道**的 200 + code=0 + 认证过的 JWT 才配产出
        # no_plan；日志/离线面**永不**产出 `reason` —— 兜底腿的数据不配有确定性结论。
        # 两可性如实带出（【台账】§5：无法区分"确实无套餐"与"该身份无 entitlement"）。
        return BillingResult(kind="no_plan", http_status=status or 200, code=code, msg=msg,
                             server_time=server_time, raw=body,
                             detail="上游返回空套餐与空余额列表（code=0）：该身份当前无套餐记录")
    return BillingResult(kind="ok", http_status=status or 200, code=code, msg=msg, plan=plan,
                         plan_key=plan_key, buckets=buckets, server_time=server_time, raw=body)


async def fetch_balance(jwt: str, device_mid: str, *, base_url: str) -> BillingResult:
    """查一次额度（本模块唯一对外函数；调用方只拿 `BillingResult`，拿不到 httpx 对象）。

    🔴 缺凭据时**根本不发起**（`kind="unreachable"` + `detail` 说明），不冒异常、不写盘 ——
    这既接住 `tests/accounts/test_registry.py:258-263` 钉的「既不编造也不打上游」，
    也让 §8.1-9 的出网护栏在测试里可判（`httpx` 调用计数必须为 0）。
    """
    if not jwt or not device_mid or not base_url:
        return BillingResult(kind="unreachable",
                             detail="缺 jwt 或设备码 → 未发起额度查询（不发请求、不猜）")
    try:
        response = await _http_get_balance(jwt, device_mid, base_url=base_url)
    except httpx.HTTPError as e:
        return classify(None, {}, error=e)
    try:
        body = response.json()
    except ValueError:
        body = {}
    return classify(response, body if isinstance(body, dict) else {})


def _epoch(v) -> int | None:
    """上游时间收成 int epoch；非数/0/缺 → `None`（**不编造**，也不拿 0 当"1970 年"）。"""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n or None
