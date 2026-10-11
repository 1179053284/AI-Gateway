"""`accounts/registry.py` + 11 个产品模块的**契约判据**（tech-design v2.11 §22.3/§22.4）。

🔴 本文件是"后面 11 个产品各写一版"的**判据**：逐个产品逐条断言钩子签名与 §22.3
   完全一致（参数名 / 参数种类 / `async` 性 / 返回注解），签名一漂就红。
🔴 另一条：`_HOOKS` 契约表必须齐全（入口层按表调度，缺项当场 KeyError）。
🔴 骨架纪律（M6-1 起，M6-6 收窄到**显式声明**）：未接线的钩子必须显式失败
    （`NotImplementedError`，或在产品模块 `_REFUSED_HOOKS` 里逐条登记"显式拒绝"+理由）；
    护栏只信 `_IMPLEMENTED`（精确到钩子）或 `_TESTS_TAKEOVER = "理由"` 这两种
    **模块内声明** —— filename（`test_<product>.py` 存在）不再整体放行（R4 §2.1/F4）。
"""

from __future__ import annotations

import importlib
import inspect

import pytest

from model_gateway.accounts import registry
from model_gateway.accounts.types import LoginOutcome, NotRefreshable, ProductMeta

#: §22.3 冻结钩子表（名字 → (是否 async, 形参名序列, 仅关键字形参, 返回注解)）
FROZEN_HOOKS: dict[str, tuple[bool, tuple[str, ...], tuple[str, ...], str]] = {
    "meta": (False, (), (), "ProductMeta"),
    "login_start": (True, ("session",), (), "Challenge"),
    "login_poll": (True, ("session",), (), "LoginOutcome"),
    "login_callback": (True, ("session", "params"), (), "LoginOutcome"),
    "refresh": (True, ("cred", "meta"), (), "dict"),
    "probe": (True, ("cred", "meta"), (), "ProbeResult"),
    "quota": (True, ("cred", "meta"), (), "QuotaSnapshot"),
    "claim": (True, ("cred", "meta"), ("precheck",), "ClaimOutcome"),
    "list_models": (True, ("cred", "meta"), (), "list[ModelInfo]"),
    "build_out": (False, ("account",), (), "OutboundAdapter"),
}

#: §22.3 的**可选**钩子（M6-3 补入；`FROZEN_HOOKS` 是必装表，本表是加性扩展）：
#: `claim_onboarding` =「一次性新手任务/登录奖励（capability=onboarding 的产品才实现，
#: loomy/raccoon）」→ **出现在某产品的 `_HOOKS` 里就必须满足这里的签名**；
#: 未出现 = 该产品不实现（合法，其余 8 个产品的骨架不受影响）。
OPTIONAL_HOOKS: dict[str, tuple[bool, tuple[str, ...], tuple[str, ...], str]] = {
    "claim_onboarding": (True, ("cred", "meta"), ("precheck",), "ClaimOutcome"),
}



def _module(product: str):
    return importlib.import_module(f"model_gateway.upstream.{product}.product")


def _implemented_hooks(product: str) -> frozenset[str]:
    """该产品**已接线**的钩子名（骨架纪律护栏据此收窄作用面；M6-2/M6-3 波次引入）。

    🔴 只认产品模块里的**显式声明**（M6-6 收窄，R4 §2.1/BL-2）——"存在
    `test_<product>.py` 就整体让位"这条 filename 隐式豁免已删除：文件名不是声明，
    实测它让未声明的产品（`qoder`/`qodercn`）被植入"编造 success"时整层护栏全绿
    （483 用例零红，R4 E2a）。两条显式口径（**取其一**）：

    1. `_IMPLEMENTED`（**首选**：精确到钩子名，未列出的钩子仍受护栏约束 ——
       例如 cline/qoder/qodercn 的 `login_callback` 仍必须显式失败）；
    2. `_TESTS_TAKEOVER = "理由…"`：某产品若确实由自己的单测**整体**接管行为判据，
       必须在自己的模块里写这个常量 + 非空理由（供评审核验），不许靠 filename 隐式豁免。

    两者都没有 → 该产品视为骨架，**全部 10 个钩子**都必须显式 `NotImplementedError`
    （M6-1 的原判据原样保留）。
    """
    module = _module(product)
    declared = getattr(module, "_IMPLEMENTED", None)
    if declared is not None:
        return frozenset(declared)
    takeover = getattr(module, "_TESTS_TAKEOVER", None)
    if isinstance(takeover, str) and takeover.strip():    # 空/缺理由 = 不放行
        return frozenset(FROZEN_HOOKS)
    return frozenset()


def _declared_refusals(product: str) -> dict[str, str]:
    """该产品**未接线但有显式拒绝行为**的钩子 → 理由（产品模块的 `_REFUSED_HOOKS`）。

    🔴 为什么需要它（M6-6，R4 F4）：未接线钩子默认必须抛 `NotImplementedError`；但
    `qoder`/`qodercn` 的 `login_callback` 是"结构上不该被调用、只回报可预期失败"的
    显式拒绝（非 local_callback 型）——折返成异常对入口层更差。这类钩子必须
    **在产品模块里逐条登记 + 写理由**（同 `_IMPLEMENTED` 的显式声明纪律），
    护栏再用探针钉住其行为（`failed`/`expired` 终态、零凭据 —— 见用例内
    `assert_declared_refusal`）：`success`/`pending`/任何凭据一律判红，即 R4
    "编造 success"红证的拦阻点。
    """
    table = getattr(_module(product), "_REFUSED_HOOKS", None)
    if table is None:
        return {}
    assert isinstance(table, dict) and table, f"{product}._REFUSED_HOOKS 必须是非空 dict"
    for name, reason in table.items():
        assert name in FROZEN_HOOKS, f"{product}._REFUSED_HOOKS 含契约外钩子名：{name!r}"
        assert isinstance(reason, str) and reason.strip(), \
            f"{product}._REFUSED_HOOKS[{name!r}] 必须写非空理由（评审核验用，不许空口豁免）"
    return dict(table)


def _annot(fn) -> str:
    return str(inspect.signature(fn).return_annotation).strip("'\"")


# ============ 注册表本体 ============

def test_registry_has_the_eleven_products_and_no_codearts():
    """§22.0：在册 11 实例 / 10 产品（Q44 起含 workbuddycn）；**排除华为云 CodeArts**（用户指令明确不接）。"""
    assert registry.PRODUCT_IDS == (
        "buddy", "workbuddy", "workbuddycn", "lobsterai", "qoder", "qodercn",
        "trae", "cline", "loomy", "raccoon", "zcode")
    assert set(registry.PRODUCTS) == set(registry.PRODUCT_IDS)
    assert "codearts" not in registry.PRODUCTS
    for pid in registry.PRODUCT_IDS:
        meta = registry.get(pid)
        assert isinstance(meta, ProductMeta)
        assert meta.id == pid and meta.title and meta.login and meta.models_source


def test_unknown_product_fails_loudly():
    """未登记产品 → `KeyError`（不静默返回空规格：界面会渲染"点了必然失败"的按钮）。"""
    for unknown in ("codearts", "", "buddy2"):
        with pytest.raises(KeyError, match="未登记的产品"):
            registry.get(unknown)


def test_every_product_module_meta_comes_from_registry():
    """`meta()` 必须**从注册表取**（唯一事实源）—— 逐产品比对，防两份表各写一份。"""
    for pid in registry.PRODUCT_IDS:
        module = _module(pid)
        assert module.PRODUCT == pid
        assert module.meta() == registry.get(pid)
        assert module._HOOKS["meta"] is module.meta


# ============ 签名契约（防"10 个产品各写一版"）============

@pytest.mark.parametrize("product", registry.PRODUCT_IDS)
def test_hook_signatures_match_frozen_contract(product):
    """🔴 逐产品逐钩子断言 §22.3 签名：`async` 性 / 形参名 / 种类 / 返回注解。"""
    module = _module(product)
    for name, (is_async, names, kwonly, returns) in FROZEN_HOOKS.items():
        fn = getattr(module, name, None)
        assert fn is not None, f"{product}.{name} 缺钩子（§22.3）"
        assert inspect.iscoroutinefunction(fn) is is_async, f"{product}.{name} async 性不符"
        params = list(inspect.signature(fn).parameters.values())
        assert tuple(p.name for p in params) == names + kwonly, f"{product}.{name} 形参名不符"
        for p in params:
            if p.name in kwonly:
                assert p.kind is inspect.Parameter.KEYWORD_ONLY, f"{product}.{name}.{p.name} 应为仅关键字"
            else:
                assert p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
            assert p.default is inspect.Parameter.empty, f"{product}.{name}.{p.name} 不得带默认值"
        assert _annot(fn) == returns, f"{product}.{name} 返回注解不符（应 {returns}）"
    # `claim(precheck: bool)` 的类型注解也要在（§22.3 冻结签名的一部分）
    assert str(inspect.signature(module.claim).parameters["precheck"].annotation).strip("'\"") == "bool"
    # 可选钩子：**声明了就得满足签名**（未声明 = 不实现，合法）
    for name, (is_async, names, kwonly, returns) in OPTIONAL_HOOKS.items():
        if name not in module._HOOKS:
            continue
        fn = getattr(module, name)
        assert inspect.iscoroutinefunction(fn) is is_async, f"{product}.{name} async 性不符（可选钩子）"
        params = list(inspect.signature(fn).parameters.values())
        assert tuple(p.name for p in params) == names + kwonly, f"{product}.{name} 形参名不符（可选钩子）"
        for p in params:
            if p.name in kwonly:
                assert p.kind is inspect.Parameter.KEYWORD_ONLY
            else:
                assert p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
            assert p.default is inspect.Parameter.empty, f"{product}.{name}.{p.name} 不得带默认值"
        assert _annot(fn) == returns, f"{product}.{name} 返回注解不符（应 {returns}）"


@pytest.mark.parametrize("product", registry.PRODUCT_IDS)
def test_hooks_table_covers_the_frozen_contract(product):
    """`_HOOKS` = 入口层真的在用的派发表：必装表**一项都不能少**，可选钩子**只准加**
    （§22.3：`claim_onboarding` 是可选钩子，capability=onboarding 的产品才实现 —— M6-3 补入）。
    """
    module = _module(product)
    assert set(FROZEN_HOOKS) <= set(module._HOOKS) <= set(FROZEN_HOOKS) | set(OPTIONAL_HOOKS)
    for name in module._HOOKS:
        assert module._HOOKS[name] is getattr(module, name)


@pytest.mark.parametrize("product", registry.PRODUCT_IDS)
async def test_unimplemented_hooks_do_not_fake_implementations(product):
    """🔴 M6-1 骨架纪律（M6-2 起**按产品收窄**；M6-6 收窄到**显式声明**）：未接线的钩子必须
    **显式失败**（`NotImplementedError`；或产品在 `_REFUSED_HOOKS` 里逐条登记过的显式拒绝
    ——回报 `failed`/`expired` 终态、零凭据），**不得**返回编造的挑战/额度/模型/success 凭据 ——
    写一半的假实现会让后续波次误以为已做好。

    收窄机制（见 `_implemented_hooks` / `_declared_refusals`）：只认产品模块里的**显式声明**
    （`_IMPLEMENTED` 精确到钩子 / `_TESTS_TAKEOVER` 带理由）。filename
    （`test_<product>.py` 存在）**不再**让护栏整体让位 —— R4 实测该隐式豁免让
    "编造 success"（`qodercn.product.login_callback`）在 483 个用例里全绿（E2a/F4）。
    实现后的**行为**由该产品自己的单测覆盖（如 `tests/accounts/test_cline.py`）。
    """
    module = _module(product)
    implemented = _implemented_hooks(product)
    refusals = _declared_refusals(product)

    class _Session:
        product = "skeleton"

    async def assert_declared_refusal(name: str, call) -> None:
        """显式拒绝型未接线钩子（`_REFUSED_HOOKS` 已登记 + 理由）：只许回报**可预期失败**。

        探针即"编造 success"的拦阻点：`success` / `pending` / 任何凭据 → 判红
        （`pending` 会让入口层永远等下去，同样是"看起来能用"的假实现）；
        抛 `NotImplementedError` 也接受（更强的显式失败）。
        """
        try:
            result = await call()
        except NotImplementedError:
            return
        except Exception as e:
            pytest.fail(
                f"{product}.{name} 已在 `_REFUSED_HOOKS` 登记为显式拒绝，却抛了 "
                f"{type(e).__name__}: {e}（登记与行为不符：要么改成可预期失败，要么撤掉登记）")
        assert isinstance(result, LoginOutcome), (
            f"{product}.{name} 登记为显式拒绝，却返回 {type(result).__name__}"
            f"（应 LoginOutcome，state=failed/expired）")
        assert result.state in ("failed", "expired"), (
            f"{product}.{name} 登记为显式拒绝，却返回 state={result.state!r}"
            f" —— success/pending 都是「看起来能用」的假实现（R4 F4 红证形态）")
        assert not result.credentials, f"{product}.{name} 显式拒绝不得携带任何凭据"

    async def assert_skeleton(name: str, call) -> None:
        """未登记的钩子必须按骨架纪律**显式**失败（`NotImplementedError`；登记过的显式拒绝
        走 `assert_declared_refusal`）。

        取不到该异常时给出**可操作的**失败文案：产品若已接线，请登记
        （`_IMPLEMENTED` / `_TESTS_TAKEOVER = "理由"`）—— 否则护栏无法把「已接线」与
        「骨架返回编造值」分开，「写一半的假实现」就再也拦不住。
        """
        if name in implemented:
            return
        if name in refusals:
            await assert_declared_refusal(name, call)
            return
        try:
            await call()
        except NotImplementedError:
            return
        except Exception as e:                        # 已接线：哑元前置条件不满足它的实现
            pytest.fail(
                f"{product}.{name} 已接线但未登记：请在 `model_gateway/upstream/{product}/product.py` "
                f"声明 `_IMPLEMENTED`（或 `_TESTS_TAKEOVER = \"理由\"`）；"
                f"原始异常：{type(e).__name__}: {e}")
        pytest.fail(f"{product}.{name} 是骨架却返回了值（不得返回编造的挑战/额度/模型）")

    await assert_skeleton("login_start", lambda: module._HOOKS["login_start"](_Session()))
    await assert_skeleton("login_poll", lambda: module._HOOKS["login_poll"](_Session()))
    await assert_skeleton("login_callback", lambda: module._HOOKS["login_callback"](_Session(), {}))
    await assert_skeleton("probe", lambda: module._HOOKS["probe"]({}, module.meta()))
    await assert_skeleton("list_models", lambda: module._HOOKS["list_models"]({}, module.meta()))
    if "build_out" not in implemented:
        with pytest.raises(NotImplementedError):
            module._HOOKS["build_out"](object())

    if product == "zcode":
        # zcode 的四个钩子已委托既有实现（§22.1）：refresh 不可续期、quota/claim 缺账号时
        # **fail closed**（unknown / failed），既不编造也不打上游
        with pytest.raises(NotRefreshable):
            await module._HOOKS["refresh"]({}, module.meta())
        assert (await module._HOOKS["quota"]({}, module.meta())).state == "unknown"
        got = await module._HOOKS["claim"]({}, module.meta(), precheck=True)
        assert got.category == "failed" and "账号名" in got.detail
    else:
        await assert_skeleton("refresh", lambda: module._HOOKS["refresh"]({}, module.meta()))
        await assert_skeleton("quota", lambda: module._HOOKS["quota"]({}, module.meta()))
        await assert_skeleton("claim", lambda: module._HOOKS["claim"]({}, module.meta(), precheck=True))


# ============ §22.4 逐产品矩阵（证据面）============

def test_every_product_declares_its_wiring_explicitly():
    """🔴 护栏的信任面必须**显式**（M6-6 收窄，R4 §2.1/BL-2）：每产品要么 `_IMPLEMENTED`
    （精确到钩子，未列出的仍受骨架约束），要么 `_TESTS_TAKEOVER = "理由"`（整体让位 + 理由）
    —— **不许靠 filename 隐式豁免**（`test_<product>.py` 存在与否不再是声明）。

    顺带钉住登记面与派发表的一致性（防"登记表与 `_HOOKS` 脱节"）与"同一钩子不许
    既声明已接线、又登记为显式拒绝"。
    """
    for pid in registry.PRODUCT_IDS:
        module = _module(pid)
        declared = getattr(module, "_IMPLEMENTED", None)
        takeover = getattr(module, "_TESTS_TAKEOVER", None)
        assert declared is not None or (isinstance(takeover, str) and takeover.strip()), (
            f"{pid} 未显式声明接线面（`_IMPLEMENTED` / `_TESTS_TAKEOVER`）——"
            f"骨架护栏无法把「已接线」与「骨架返回编造值」分开")
        if declared is not None:
            assert set(declared) <= set(FROZEN_HOOKS) | set(OPTIONAL_HOOKS), \
                f"{pid}._IMPLEMENTED 含契约外名字"
            # 登记的钩子必须由本模块的钩子表暴露（`_HOOKS` 或 `_OPTIONAL_HOOKS` ——
            # 两家注册面分裂一事已由 R1 F7 单独登记，不在本收窄的判据里）
            exposed = set(module._HOOKS) | set(getattr(module, "_OPTIONAL_HOOKS", None) or ())
            assert set(declared) <= exposed, \
                f"{pid}._IMPLEMENTED 登记了两张钩子表都没有的钩子（登记表与派发表脱节）"
        assert not (set(_declared_refusals(pid)) & set(declared or ())), (
            f"{pid}: 同一钩子既声明已接线、又登记为显式拒绝（二选一）")


def test_tests_takeover_needs_an_explicit_reason(monkeypatch):
    """filename 不再让护栏整体让位（M6-6 收窄）：唯一「整体接管」出口 = 产品模块里**显式**写
    `_TESTS_TAKEOVER = "理由…"`，空/缺理由一律不放行（防退回隐式豁免）。"""
    module = _module("qoder")
    monkeypatch.delattr(module, "_IMPLEMENTED", raising=False)
    monkeypatch.delattr(module, "_REFUSED_HOOKS", raising=False)
    assert _implemented_hooks("qoder") == frozenset(), \
        "无声明必须按骨架全约束（不再是 filename 放行）"
    monkeypatch.setattr(module, "_TESTS_TAKEOVER", "   ", raising=False)
    assert _implemented_hooks("qoder") == frozenset(), "空理由不放行"
    monkeypatch.setattr(module, "_TESTS_TAKEOVER",
                        "qoder 的行为判据整体由 tests/accounts/test_qoder.py 接管（本用例的示例理由）",
                        raising=False)
    assert _implemented_hooks("qoder") == frozenset(FROZEN_HOOKS), \
        "显式声明 + 非空理由才整体让位"


def test_matrix_login_and_models_source():
    """登录方式与目录来源逐条对照 §22.4 表。"""
    expect_login = {
        "buddy": "external_link", "workbuddy": "external_link", "workbuddycn": "external_link",
        "lobsterai": "local_callback", "qoder": "device_code", "qodercn": "device_code",
        "trae": "local_callback", "cline": "device_code",
        "loomy": "qr", "raccoon": "qr", "zcode": "device_code",
    }
    expect_source = {
        "buddy": "remote", "workbuddy": "remote", "workbuddycn": "remote",
        "lobsterai": "remote",
        "qoder": "static", "qodercn": "static", "trae": "remote",
        "cline": "remote", "loomy": "remote", "raccoon": "remote", "zcode": "static",
    }
    expect_alt = {"loomy": ("sms_code",), "raccoon": ("sms_code",)}
    for pid in registry.PRODUCT_IDS:
        assert registry.get(pid).login == expect_login[pid], f"{pid} 登录方式与 §22.4 不符"
        assert registry.get(pid).login_alt == expect_alt.get(pid, ()), f"{pid} 备选登录形态不符"
        assert registry.get(pid).models_source == expect_source[pid], f"{pid} 目录来源不符"


def test_matrix_protocol():
    """协议族逐条对照 §22.4（缺口①已于 2026-09-29 裁决：字面量补入 `custom`）。

    `custom` = 需产品专属出站塑形（qoder/qodercn 信封、trae SSE 成帧）；物化资源时
    其 `Resource.protocol` 落最近协议族（openai），**分派以 `product` 优先**（§22.5-3）。
    """
    expect = {
        "buddy": "openai", "workbuddy": "openai", "workbuddycn": "openai",
        "lobsterai": "openai",
        "qoder": "custom", "qodercn": "custom", "trae": "custom",
        "cline": "openai", "loomy": "openai", "raccoon": "openai",
        "zcode": "anthropic",
    }
    for pid in registry.PRODUCT_IDS:
        assert registry.get(pid).protocol == expect[pid], f"{pid} protocol 与台账不符"
    assert registry.get("zcode").base_url == "https://zcode.z.ai/api/v1/zcode-plan/anthropic"


def test_matrix_device_fields():
    """设备字段逐条对照 §22.4 的「设备」列（`20 §2.7`）。"""
    expect = {
        "buddy": ((), False), "workbuddy": ((), False), "workbuddycn": ((), False),
        "cline": ((), False),
        "loomy": ((), False),
        "lobsterai": (("uuid",), False),                  # keyfrom 属元数据（W2-fix 裁决）
        "qoder": (("machine_id",), False), "qodercn": (("machine_id",), False),
        "trae": (("machine_id", "device_id"), True),      # device_id 由 uid 派生（20 §3.5）
        "raccoon": (("device_id",), False),
        "zcode": (("device_mid",), False),
    }
    for pid in registry.PRODUCT_IDS:
        spec = registry.get(pid).device
        assert (spec.fields, spec.derive) == expect[pid], f"{pid} 设备规格与 §22.4 不符"


def test_matrix_capabilities_from_research_3_1():
    """能力位逐条对照 `20 §3.1` + Q44 增补（balance 12/12、checkin 9/12、onboarding 2、
    永久锁 4、refresh 除 loomy/zcode 外均可续期，`20 §2.6`）。"""
    expect = {
        # pid: (balance, checkin, onboarding, permanent_lock, refresh)
        "buddy": (True, True, False, True, True),
        "workbuddy": (True, False, False, True, True),
        "workbuddycn": (True, True, False, True, True),   # 中国版有签到端点，与国际版相反
        "lobsterai": (True, True, False, False, True),
        "qoder": (True, True, False, False, True),
        "qodercn": (True, True, False, False, True),
        "trae": (True, True, False, False, True),
        "cline": (True, False, False, False, True),
        "loomy": (True, True, True, True, False),
        "raccoon": (True, False, True, False, True),
        "zcode": (True, True, False, False, False),
    }
    for pid in registry.PRODUCT_IDS:
        cap = registry.get(pid).capabilities
        got = (cap.balance, cap.checkin, cap.onboarding, cap.permanent_lock, cap.refresh)
        assert got == expect[pid], f"{pid} 能力位与 20 §3.1/§2.6 不符：{got}"


def test_no_checkin_products_are_marked_unavailable():
    """「没有签到端点」的产品必须在能力位里为 False（`20 §3.1`：workbuddy/cline/raccoon）——
    这是前端**不渲染按钮**的判据，标错就会让用户每次点击必然失败。"""
    assert {pid for pid in registry.PRODUCT_IDS
            if not registry.get(pid).capabilities.checkin} == {"workbuddy", "cline", "raccoon"}


def test_every_product_base_url_is_pinned_to_its_module_constant():
    """🔴 §22.4 的 `base_url` 逐产品判据（R4 §2.2/NB-2 登记缺口收口）。

    R4 复核结论：10 条 `base_url` 里**只有 zcode 被用例钉住**（`test_matrix_protocol`），
    其余 9 条"仅文档可溯、无判据"—— 注册表值由此成了"无人能核的自由量"（改坏不红）。
    本用例逐产品给出**可核（可红）**的等式：注册表值必须与**产品模块内的权威常量**相等；
    改 `accounts/registry.py` 任一 `base_url`（或改产品模块常量）→ 对应那一行必红。

    逐产品出处（注册表值 ← 产品模块常量；括号内为常量所在文件）：

    | 产品 | 等式 | 常量出处 |
    |---|---|---|
    | lobsterai | `== lobsterai/const.py::API_BASE` | `lobsterai-product.ts:63`（`20 §1.1`） |
    | qoder | `== qoder/config.py::QODER.encrypted_infer_base` | `qoder-product.ts:445` |
    | qodercn | `== qoder/config.py::QODER_CN.encrypted_infer_base` | `qoder-product.ts:604` |
    | trae | `== trae/const.py::AGENT_HOST` | `trae-product.ts:155` |
    | cline | `== cline/constants.py::API_BASE + "/api/v1"` | `cline-product.ts:265` + 全部 `/api/v1/*` 端点路径（`MODELS_PATH`/`REFRESH_PATH`/`ME_PATH`…） |
    | loomy | `== loomy/constants.py::API_BASE` | `loomy.ts:30`（含 `/api/v1`，网关按 `{base}/chat/completions` 拼接） |
    | raccoon | `== raccoon/const.py::API_BASE + LLM_PREFIX` | `raccoon.ts:25,30`（推理前缀必须随基址） |
    | zcode | `== zcode/product.py::DEFAULT_PLAN_BASE_URL + "/anthropic"` | `auth.py:7` 的 Plan/JWT 通道基址 |

    ⚠️ **buddy / workbuddy 仅非空断言 + 出处注释**：这两个产品**没有**模块级主机常量 ——
    `upstream/buddy/protocol.py::ProductProfile` **刻意不存 base_url**（`:115-118`：基址的唯一
    事实源就是注册表，`X-Domain` 由它的主机名派生）→ 在这里再抄一份字面量会造出第二个事实源
    （正是本用例要防的形态）。出处：`product.ts:271`（`copilot.tencent.com`）/
    `product.ts:384-385`（`www.workbuddy.ai`），见注册表内的逐条注释。
    """
    from model_gateway.upstream.cline import constants as cline_constants
    from model_gateway.upstream.lobsterai import const as lobsterai_const
    from model_gateway.upstream.loomy import constants as loomy_constants
    from model_gateway.upstream.qoder import config as qoder_config
    from model_gateway.upstream.raccoon import const as raccoon_const
    from model_gateway.upstream.trae import const as trae_const
    from model_gateway.upstream.zcode import product as zcode_product

    #: 产品 → 期望值（**动态取自产品模块常量**，不经注册表绕回 —— 否则等式恒真）
    expect = {
        "lobsterai": lobsterai_const.API_BASE,
        "qoder": qoder_config.QODER.encrypted_infer_base,
        "qodercn": qoder_config.QODER_CN.encrypted_infer_base,
        "trae": trae_const.AGENT_HOST,
        "cline": cline_constants.API_BASE + "/api/v1",
        "loomy": loomy_constants.API_BASE,
        "raccoon": raccoon_const.API_BASE + raccoon_const.LLM_PREFIX,
        "zcode": zcode_product.DEFAULT_PLAN_BASE_URL + "/anthropic",
    }
    # 全体：非空 + https（buddy/workbuddy 的判据止步于此，理由见 docstring）
    for pid in registry.PRODUCT_IDS:
        base = registry.get(pid).base_url
        assert base and base.startswith("https://"), f"{pid} base_url 缺失/非法：{base!r}"
    # 有权威常量的 8 个产品：等式判据
    for pid, expected in expect.items():
        assert registry.get(pid).base_url == expected, (
            f"{pid} base_url 与产品模块常量不符：注册表 {registry.get(pid).base_url!r} "
            f"vs 常量 {expected!r}（两处必须同源，不得各写一份）")
