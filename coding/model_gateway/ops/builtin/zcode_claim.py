"""`zcode_claim` 运营操作（tech-design v2.0 §16.4 / §19 M5-1）。

**薄适配器**（§16.6）：只把 `upstream/zcode/claim.py` 的上游语义
翻译成 `ops` 的四类结果 —— **不自己发请求、不做调度**。

> ⚠️ operation 命名说明（§16.4）：叫 `zcode_claim` 而**不是** `daily_checkin` ——
> 实测 **ZCode 没有传统意义的"每日签到"端点**（`14` §①），
> 所谓签到 = `billing/claim`（`period=daily`）**+** `event/report` 上报 `app_daily_active` 两件事合成。
"""

from __future__ import annotations

import asyncio
import json

from model_gateway.ops.base import OpResult
from model_gateway.ops.builtin import product_hooks
from model_gateway.upstream.zcode import captcha
from model_gateway.upstream.zcode import claim as claim_mod
from model_gateway.upstream.zcode import store

#: 该 operation 支持的产品（§16.4 per-operation 声明，不按产品整体开关）
#: 🔴 由 `ops/builtin/__init__.py` 挂进 `OPERATIONS` 后被 `run_once` 真正用于筛参与方
SUPPORTED_PRODUCTS = ("zcode",)

#: 注册 id（CLI / cron 用它挑动作）
OPERATION_ID = "zcode_claim"


def _credentials_of(account: str) -> tuple[str, str, str]:
    """取该账号的凭据（JWT + 设备码 + user_id）。

    复用 `oauth.read_credentials`（读该账号自己的 v2 目录）+ `oauth.build_credentials`
    —— 不在此处重复实现解密逻辑（验收修正：消除重复）。
    """
    from model_gateway.upstream.zcode import oauth
    from model_gateway.upstream.zcode.dataroot import _read_json, v2_dir_of

    root = store.accounts_root()
    decrypted = oauth.read_credentials(v2_dir_of(root, account))
    creds = oauth.build_credentials(decrypted)
    jwt = creds.jwt

    # user_id 从 user_info 取（激活事件体必需，`claim.rs:135-156`）
    uid = ""
    provider = creds.provider or "zai"
    info_raw = decrypted.get(f"oauth:{provider}:user_info") or ""
    if info_raw:
        try:
            info = json.loads(info_raw)
            uid = str(info.get("id") or info.get("user_id") or "")
        except (ValueError, TypeError):
            uid = ""

    meta = _read_json(root / account / "meta.json")
    return jwt, str(meta.get("device_mid") or ""), uid


#: Plan 通道基址（Q27-② 双通道之一；API Key 通道由 auth 模块另行选择）
DEFAULT_PLAN_BASE = "https://zcode.z.ai/api/v1/zcode-plan"

#: 站点根（`client/configs` 等客户端接口所在地）
SITE_ROOT = "https://zcode.z.ai"

#: 全局熔断写入 `last_error` 的原因串（§17：必须让用户分辨"风控熔断"与"普通失败冷却"）
GLOBAL_BENCH_REASON = "ZCode 风控熔断（30min，全局）"


def _plan_endpoint() -> tuple[str, str, str]:
    """`(Plan 基址, 住宅代理, 站点根)` —— §16.5 / §17 的三项上游坐标。

    配置不可用时回落默认端点（不阻断运营）。站点根用于 `client/configs`
    （它在 `zcode.z.ai/api/v1/`，**不在** `.../zcode-plan` 下面，挂错 host 会 404）。
    """
    try:
        from model_gateway.config.loader import load_config
        cfg = load_config()
        z = cfg.gateway.zcode
        return (z.plan_base_url or DEFAULT_PLAN_BASE), z.effective_proxy(), SITE_ROOT
    except Exception:  # noqa: BLE001
        import os
        return (DEFAULT_PLAN_BASE,
                (os.environ.get("MGW_ZCODE_PROXY") or "").strip(), SITE_ROOT)


def classify(outcome: claim_mod.ClaimOutcome) -> tuple[str, str]:
    """业务码 → 四类结果（**业务码优先于 HTTP 状态**，§16.3 教训 2）。"""
    c = outcome.code
    if c == claim_mod.CODE_OK:
        return "success", ""
    if c == claim_mod.CODE_ALREADY_CLAIMED:
        return "already_done", "该套餐已领取过"
    if c == claim_mod.CODE_QUOTA_EXHAUSTED:
        return "inactive", f"今日名额已用完（下次可领 {outcome.next_at or '未知'}）"
    if c in (claim_mod.CODE_ACTIVITY_ENDED, claim_mod.CODE_NOT_ELIGIBLE,
             claim_mod.CODE_PLAN_MISSING):
        return "inactive", outcome.message or "无资格 / 活动结束"
    return "failed", outcome.message or f"业务码 {c}"


def _handle_risk_control(runtime, account: str) -> None:
    """🔴 **熔断接线点**（§17 / §19 M4-4）：命中 3012 → 全局熔断 + 回写资源状态。

    两件事都必须做，缺一件就是半生效：
    - `CooldownManager.enter()` → 30 分钟内**所有** ZCode 账号停止再打上游（落盘，重启不丢）
    - 回写 `ResourceState.status`（`bench` + `last_error`）→ 模型转发路径自动绕开
      （不接这条，刚被风控的账号仍会被选中，要等它再失败一次才进冷却 —— 验收 M4-4 的原始缺陷）

    两条入口都要生效（§16.4 双层互斥同理）：
    - **cron**（网关进程内）→ 直接回写内存态
    - **CLI**（独立进程，`runtime=None`）→ 改不到网关内存，必须经
      `/admin/api/zcode/bench` 让它自己回写（熔断状态本身走共享文件，无需出口）

    🔴 回写的原因串取 `circuit.reason()`，**不是**裸常量（验收 S-6 / 面板两侧同时点名）：
    `enter()` 会把它规范成 §17 要求的 `…，至 HH:MM`。用常量的话"同一进程内实时命中风控"
    这条路径写进「最近错误」的是没有恢复时刻的旧文案，而**重启之后**才有时刻 ——
    §17 那份可见性收益恰好落在了错的一半：最需要看"几点恢复"的是正在用的人。
    """
    from model_gateway.upstream.zcode import quota as zq

    circuit = zq.get_circuit()
    circuit.enter(GLOBAL_BENCH_REASON)
    reason = circuit.reason()
    if runtime is not None:
        zq.bench_all_zcode(runtime, reason=reason)
        return
    from model_gateway.core.local_admin import admin_post

    admin_post("/admin/api/zcode/bench",
               payload={"account": account, "reason": reason, "scope": "global"})


def _circuit_gate(account: str) -> OpResult | None:
    """熔断中 / 节流未到期 → 本轮该账号**不发起上游请求**（§17）。

    分类取 `inactive`：熔断是**正常业务态**（不是失败，不需要用户红点关注），
    但必须在 detail 里给出剩余时间，否则用户只看到"跳过"却不知道被什么挡住。
    """
    from model_gateway.upstream.zcode import quota as zq

    circuit = zq.get_circuit()
    if circuit.active():
        if circuit.untrusted:
            # 🔴 状态文件读不动时**不给钟点**（第十一轮 eng-A BLK-2）：剩余时长是未知的，
            #    说"剩余约 0 分钟"既自相矛盾（0 分钟为什么还跳？）又把"拒跑"洗成"没事"。
            # 🔴 第十二轮 PM B-12-4：这一档记 **failed 而非 inactive** —— 红点只数 failed
            #    （`admin.py` + `runner.py`），记 inactive 就等于"拒跑了但没人知道"。
            #    与 S-22 的锁拒跑同口径：原因在用户侧（状态文件坏）→ 必须点亮红点。
            return OpResult(account, "failed",
                            f"未发起：ZCode 熔断状态文件读不动（{circuit.untrusted}），"
                            f"按熔断拒跑；确认无风控后删除 {circuit.path} 即可解除")
        return OpResult(account, "inactive",
                        f"ZCode 全局风控熔断中（剩余约 {circuit.left_minutes()} 分钟），本轮跳过")
    return None


def _build_client(jwt: str, device_mid: str, *, manual: bool = False):
    """按配置装配领取客户端（**生产恒接求解器**，§16.5）。

    单独成函数是因为"求解器有没有真的接上"必须是可断言的装配事实 ——
    上一轮正是这行没传 `captcha_solver`，导致验证码路径整体是假的。
    代理未配置时同样交给求解器说话（它才知道原因），不在客户端里瞎猜。
    """
    base, proxy, site_root = _plan_endpoint()
    return claim_mod.ZCodeClaimClient(
        base, jwt, device_mid, proxy=proxy,
        captcha_solver=captcha.get_solver(proxy=proxy, site_root=site_root,
                                          manual=manual))


async def claim(account: str, *, manual: bool = False,
                client_factory=None, runtime=None) -> OpResult:
    """对单个账号执行一次领取。

    - `manual=True`：无住宅代理时的降级路径（由用户手动过验证码）
    - `client_factory`：可注入（单测用假上游）
    - `runtime`：给出时，**遇风控会 bench 该账号对应资源**（熔断接线，§17）
    """
    jwt, device_mid, user_id = _credentials_of(account)
    if not jwt:
        return OpResult(account, "failed", "凭据缺失（先 `mgw zcode login` 或 `mgw zcode import`）")

    from model_gateway.upstream.zcode import quota as zq

    # 🔴 熔断闸门：全局熔断中就不再打上游（继续打只会延长风控），并把 10s 节流落地
    gated = _circuit_gate(account)
    if gated is not None:
        return gated
    circuit = zq.get_circuit()
    wait_ms = circuit.throttle_wait_ms()
    if wait_ms > 0:
        await asyncio.sleep(wait_ms / 1000)
    circuit.mark_called()

    if client_factory is None:
        client_factory = lambda: _build_client(jwt, device_mid, manual=manual)  # noqa: E731

    client = client_factory()
    try:
        # ① preview：有可领活动才继续（无可领 → inactive，不是失败）
        plan = await client.preview()
        if plan is None:
            return OpResult(account, "inactive", "当前无可领取活动")

        # ② + ③ 验证码 + claim
        try:
            outcome = await client.claim(plan.plan_id, manual=manual)
        except claim_mod.CaptchaUnavailable as e:
            return OpResult(account, "failed", str(e))

        if outcome.code == zq.CODE_RISK_CONTROL or zq.looks_like_risk_control(
                outcome.message or ""):
            _handle_risk_control(runtime, account)
        category, detail = classify(outcome)

        # 🔴 激活事件上报（§16.4 / `14` §③）：所谓"签到" = `billing/claim`
        #    **+** `event/report` 上报 `app_daily_active` **两件事合成** —— 不能只做前者。
        #    上报失败**不影响领取结论**（尽力而为，不因此把成功判成失败）。
        if category == "success" and user_id:
            try:
                await client.report_activation(user_id=user_id)
            except Exception:  # noqa: BLE001 — 上报失败不改变领取结论
                pass

        return OpResult(account, category, detail)
    except Exception as e:  # noqa: BLE001 — 单账号失败隔离（不抛给批量执行器）
        # 🔴 A-3（面板修复轮-2）：重试性判据与 7 产品**同一把尺** —— 只有**传输类**
        # 异常（`product_hooks.is_transport_failure`：httpx 网络/超时/协议错误 + OSError）
        # 声明 `retryable=True`；其余（业务异常 / 解析错误 / 内部 bug）一律
        # `retryable=False`（不重试）。原实现是**全异常 blanket True**（连非网络异常
        # 也退避重试，与 §22.6「失败退避仅网络/5xx、业务码不重试」相悖的遗留口径）。
        # 文案仍保留 `network:` 前缀（旧调用方的可读约定），但判据不再靠文案猜。
        retryable = product_hooks.is_transport_failure(e)
        prefix = "network: " if retryable else ""
        return OpResult(account, "failed", f"{prefix}{type(e).__name__}: {e}",
                        retryable=retryable)
    finally:
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass
