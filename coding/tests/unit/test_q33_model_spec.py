"""Q33-④ · 统一规格层的判据（合并规则 / 零网络来源 / 不编数）。

覆盖四件事，每件都是"两类接入同级"这条要求落到代码上的具体形状：
1. `merge_specs` 的合并规则（数值取大、布尔取并、`None` 不参与、档位并集按规范序回排）；
2. 目录缓存的读写与**新鲜度**（陈旧仍可用但必须标注；空清单不覆盖好数据）；
3. `build_model_caps` 带规格时按"固定最大标准"合并，不带规格时与改动前**逐字一致**；
4. 出站默认注入的优先级：工具传参 > 网关设置 > 统一规格 > 供应商通道默认。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
import yaml

from model_gateway.accounts import catalog_cache
from model_gateway.accounts.types import ModelInfo
from model_gateway.core.capabilities import build_model_caps
from model_gateway.core.ir import apply_model_params, apply_spec_defaults
from model_gateway.core.model_spec import (
    ModelSpec, merge_specs, product_spec, resolve, resource_spec)
from model_gateway.config.schemas import AppConfig


def _READER(product, root=None, account=""):
    """装配侧注入的账号侧目录缓存读函数（生产由 `main.py` 传同一个，测试只是接上 tmp 根）。

    🔴 `account` 形参必须与生产同 arity（R5-F-1 之后 `core` 会**带着号**来问）：
    双少一个形参就是 `TypeError`，而这条注入的失败方式恰好是"规格层静默拿不到数"，
    所以在假读函数上把口径钉死，而不是等真机复验再抓。
    """
    return catalog_cache.read_cache(product, root=root, account=account)


def test_core_does_not_import_the_accounts_layer():
    """🔴 UT-85 · 分层红线（债务 Q33-债2 的判据）：`core/` 不得 import `accounts/`。

    规格层的账号侧取数**必须由装配侧注入**（与 `circuit_active` / `credential_fingerprint`
    同一个口径）。core 一旦自己去读 `data/upstream/…`，"哪个实例的哪棵数据树"就散进核心逻辑，
    服务进程与 `mgw` CLI 各读各的，`core/` 也再也无法独立单测。
    用 **AST 扫源码**而不是查运行时 import —— 后者会被"这条路径本轮没被执行"糊过去（假绿）。
    """
    import ast as _ast

    core_dir = Path(__file__).resolve().parents[2] / "model_gateway" / "core"
    assert core_dir.is_dir(), f"扫不到 core 目录：{core_dir}"
    offenders = []
    for py in sorted(core_dir.glob("*.py")):
        for node in _ast.walk(_ast.parse(py.read_text(encoding="utf-8"))):
            mod = ""
            if isinstance(node, _ast.ImportFrom):
                mod = node.module or ""
            elif isinstance(node, _ast.Import):
                mod = ",".join(a.name for a in node.names)
            if "model_gateway.accounts" in mod:
                offenders.append(f"{py.name}:{getattr(node, 'lineno', '?')} → {mod}")
    assert offenders == [], f"core/ 反向依赖 accounts/（取数应改为注入）：{offenders}"


class TestMergeRules:
    def test_numeric_take_max_and_none_does_not_join(self):
        spec = merge_specs([{"context_window": 262144, "max_output": 65536},
                            {"context_window": 1000000, "max_output": None},
                            {"context_window": 0, "max_output": -5}])
        assert spec.max_input == 1000000          # 取大
        assert spec.max_output == 65536           # 0/负数/None 都不参与
        assert spec.sources == 3

    def test_no_source_at_all_is_none_not_zero(self):
        """🔴 "不知道"必须是 None：印 0 会让工具以为自己拿到了数（铁律 2）。"""
        spec = merge_specs([{}, {"context_window": None, "max_output": None}])
        assert spec.max_input is None and spec.max_output is None

    def test_booleans_are_union_and_absent_is_none(self):
        spec = merge_specs([{"tool_call": False, "image_input": None, "reasoning": True},
                            {"tool_call": True}])
        assert spec.tool_call is True and spec.reasoning is True
        assert spec.image_input is None           # 一个来源都没说过这件事

    def test_all_sources_saying_no_means_no(self):
        spec = merge_specs([{"tool_call": False}, {"tool_call": False}])
        assert spec.tool_call is False

    def test_effort_union_keeps_canonical_order(self):
        spec = merge_specs([{"effort_levels": ["high", "max"]},
                            {"effort_levels": ["low", "ultra", "custom-tier"]}])
        assert spec.effort_levels == ("low", "high", "max", "ultra", "custom-tier")

    def test_stale_flag_propagates(self):
        spec = merge_specs([{"max_output": 1, "_stale": True}])
        assert spec.from_stale_cache is True


class TestCatalogCache:
    def test_write_then_read_roundtrip(self, tmp_path):
        wrote = catalog_cache.write_cache("buddy", [ModelInfo(id="m-1", context_window=1000,
                                                             max_output=200)],
                                          source_account="a1", root=tmp_path / "buddy")
        assert wrote is True
        cache = catalog_cache.read_cache("buddy", root=tmp_path / "buddy")
        assert cache and cache["stale"] is False and cache["source_account"] == "a1"
        assert cache["models"][0].id == "m-1" and cache["models"][0].max_output == 200

    def test_empty_list_is_not_a_source(self, tmp_path):
        """"取到了 0 条"是异常不是证据 ⇒ 不写盘，更不覆盖既有好数据。"""
        root = tmp_path / "buddy"
        assert catalog_cache.write_cache("buddy", [], root=root) is False
        assert catalog_cache.read_cache("buddy", root=root) is None

    def test_failure_does_not_clobber_good_cache(self, tmp_path):
        root = tmp_path / "buddy"
        catalog_cache.write_cache("buddy", [ModelInfo(id="m-1")], source_account="a1", root=root)
        # 写失败路径（空清单）不touch文件
        assert catalog_cache.write_cache("buddy", [], root=root) is False
        assert catalog_cache.read_cache("buddy", root=root)["count"] == 1

    def test_stale_after_ttl(self, tmp_path):
        root = tmp_path / "buddy"
        catalog_cache.write_cache("buddy", [ModelInfo(id="m-1")], ttl_seconds=1, root=root)
        path = catalog_cache.cache_path("buddy", root=root)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["fetched_at"] = time.time() - 30      # 假装是 30 秒前取的
        path.write_text(json.dumps(data), encoding="utf-8")
        cache = catalog_cache.read_cache("buddy", root=root)
        assert cache["stale"] is True and cache["count"] == 1

    def test_unreadable_or_unknown_shape_reads_as_none(self, tmp_path):
        root = tmp_path / "buddy"
        root.mkdir(parents=True)
        (root / catalog_cache.CACHE_FILE).write_text("{ 坏 JSON", encoding="utf-8")
        assert catalog_cache.read_cache("buddy", root=root) is None
        (root / catalog_cache.CACHE_FILE).write_text(json.dumps({"models": "不是表"}),
                                                     encoding="utf-8")
        assert catalog_cache.read_cache("buddy", root=root) is None

    def test_per_account_name_is_what_the_reader_reads(self, tmp_path):
        """🔴 UT-89 · 按号缓存的**文件名字符串**必须与读侧一致（真机复验 R5-F-3 的坑位）。

        文档/指令里曾写作 `_catalog_cache.<账号>.json`，实现产的是
        `_catalog_cache.<清洗名>-<sha1[:8]>.json`（`_safe` 挂短哈希防两个号清洗后同名，
        R5-⑤）。后果不是难看，而是**按文档名手写的文件生产读不到**：
        排障/造数时人照着文档建的那份缓存永远不参与任何判据，看起来"闸门坏了"。
        ⇒ 口径定为：路径**只经 `cache_path()` 取**，任何人不得手写第二套名字。
        """
        root = tmp_path / "buddy"
        root.mkdir(parents=True)
        # ① 文档名（不含哈希）落在同一目录里 = 读不到，这是**已知行为**不是缺陷
        (root / "_catalog_cache.ix-c.json").write_text(
            json.dumps({"fetched_at": time.time(), "ttl_seconds": 86400,
                        "models": [{"id": "m-1", "max_output": 4096}]}), encoding="utf-8")
        assert catalog_cache.read_cache("buddy", account="ix-c", root=root) is None
        # ② 生产写入用 cache_path()，回读也用它 ⇒ 这一份才认
        catalog_cache.write_cache("buddy", [ModelInfo(id="m-1", max_output=4096)],
                                  source_account="ix-c", root=root)
        assert catalog_cache.cache_path("buddy", account="ix-c", root=root).exists()
        view = catalog_cache.read_cache("buddy", account="ix-c", root=root)
        assert view and view["models"][0].max_output == 4096
        # ③ 清洗后同名 ≠ 真同名：短哈希把两个号分开（R5-⑤，防"A 号的缓存替 B 号否决"）
        a = catalog_cache.cache_path("buddy", account="user.name@x.com", root=root).name
        b = catalog_cache.cache_path("buddy", account="user_name@x.com", root=root).name
        assert a != b and a.startswith("_catalog_cache.user_name_x_com-")

    def test_cache_root_follows_an_overridden_account_root(self, tmp_path, monkeypatch):
        """🔴 缓存根 = **账号根的父目录**，不是写死的默认数据树（复验轮 R4-⑥）。

        `MGW_BUDDY_ACCOUNTS` 把账号库指到别处（换盘 / 另一棵实例数据树）时，
        产品级缓存必须跟着那棵树走：默认树里留一份缓存 = 界面上看到的规格
        与实际账号库不是同一份数据，正是"实例身份自证"那条红线要防的形状。
        """
        alt = tmp_path / "elsewhere" / "buddy" / "accounts"
        alt.mkdir(parents=True)
        monkeypatch.setenv("MGW_BUDDY_ACCOUNTS", str(alt))
        got = catalog_cache.cache_path("buddy")
        assert got == alt.parent / catalog_cache.CACHE_FILE
        assert got.parent != alt                      # 不落进 accounts/（那里只放账号目录）

    def test_write_cache_survives_a_non_serializable_field(self, tmp_path):
        """缓存写挂了**不得**把刚刚成功的目录调用打成失败（复验轮 R4-⑤）。

        钩子回传的是上游数据，字段值出格（`Decimal` / 嵌套对象）时 `json` 抛 `TypeError`，
        旧实现只捕 `OSError` ⇒ 端点 500、用户这次明明取到了目录却什么都看不见。
        """
        from decimal import Decimal
        root = tmp_path / "buddy"
        bad = ModelInfo(id="m-1", context_window=Decimal("1000"))
        assert catalog_cache.write_cache("buddy", [bad], root=root) is False
        assert catalog_cache.read_cache("buddy", root=root) is None

    def test_field_drift_is_tolerated(self, tmp_path):
        """目录将来多出新字段不该让整个读侧抛错 —— 只认已知字段。"""
        root = tmp_path / "buddy"
        catalog_cache.write_cache("buddy", [ModelInfo(id="m-1")], root=root)
        path = catalog_cache.cache_path("buddy", root=root)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["models"][0]["brand_new_field_from_vendor"] = {"nested": 1}
        path.write_text(json.dumps(data), encoding="utf-8")
        got = catalog_cache.read_cache("buddy", root=root)
        assert got is not None and got["models"][0].id == "m-1"


class _Entry:
    """枚举池（= 厂商公开目录）条目的最小形状 —— **按量 Key 那一路**的规格来源，
    测试用，不依赖内置目录真数据。"""

    def __init__(self, name="glm-5.3", *, context_window=262144, max_output=65536,
                 tool_call=True, image_input=False, reasoning=True,
                 effort_levels=("low", "high")):
        self.display = "GLM 5.3"
        self.vendor = "智谱"
        self.context_window = context_window
        self.max_output = max_output
        self.tool_call = tool_call
        self.image_input = image_input
        self.reasoning = reasoning
        self.effort_levels = effort_levels


class _Pool:
    """枚举池的最小替身。

    🔴 查表用的**实参** = `entry.model`（供应商模型名），不是网关模型名 ——
    生产 `EnumPool.get` 的**键空间是厂商模型标准名**（`EnumEntry.name`），这里让替身
    只对 `vm-k` 应答，模拟"这条映射的供应商模型名正是目录里那个标准名"的常见形状。
    `_two_path_config` 里Key 接入侧条目的供应商模型名是 `vm-k`、网关模型是 `glm-5.3`，
    先前这里按网关模型名回条目，正好把 `sources_for_entries` 用错键的缺陷掩盖了
    （评审 R2-③ 的同一条：单元绿、接线红）。
    """

    def __init__(self, entry=None):
        self._entry = entry if entry is not None else _Entry()

    def get(self, name):
        return self._entry if name == "vm-k" else None


def _two_path_config(product_bit: bool = True):
    """一份「同一网关模型同时挂 按量 Key 资源 + 账号资源」的配置（两类接入同级）。"""
    return AppConfig.model_validate({
        "resources": [
            {"id": "res-k", "api_key": "sk-k", "protocol": "openai", "base_url": "http://x/v1"},
            {"id": "res-p", "product": "buddy", "account_ref": "a1", "api_key": "",
             "protocol": "openai", "base_url": "http://y/v1"},
        ],
        "product_models": [{"product": "buddy", "model": "vm-x", "system_model": "glm-5.3",
                            "enabled": product_bit}],
        "models": [{"name": "glm-5.3", "endpoint": "chat",
                    "resources": [{"resource": "res-k", "model": "vm-k"},
                                  {"resource": "res-p", "model": "vm-x"}]}],
    })


class TestResolveAcrossBothAccessPaths:
    """同一网关模型挂着「按量 Key 资源」与「账号资源」时，规格必须并成一份最大。"""

    def test_maxima_and_union_over_both_access_paths(self, tmp_path):
        root = tmp_path / "buddy"
        catalog_cache.write_cache("buddy", [ModelInfo(id="vm-x", context_window=1000000,
                                                      max_output=32000, tool_call=False,
                                                      image_input=True, reasoning=True,
                                                      effort_levels=("ultra",))],
                                 source_account="a1", root=root)
        cfg = _two_path_config()
        spec = resolve(cfg, cfg.models[0], _Pool(), cache_root=root, reader=_READER)
        assert spec.sources == 2                       # 两类接入各贡献一份来源
        assert spec.max_input == 1000000               # 厂商 262K vs 账号 1M ⇒ 取大
        assert spec.max_output == 65536                # 账号侧更小 ⇒ 不降级承诺
        assert spec.tool_call is True                  # 任一具备即具备
        assert spec.image_input is True
        assert "ultra" in spec.effort_levels and "low" in spec.effort_levels
        assert spec.sources == 2 and spec.from_stale_cache is False

    def test_resolve_is_strictly_zero_network(self, tmp_path, monkeypatch):
        """🔴 规格取数**绝不发网络**：把假上游换成"一调用就炸"，resolve 照样出数。

        这条钉的是 §22.5-6 的既有定论（请求期/选路期不查目录），也是这一层能进
        `/v1/models` 与出站默认的**前提** —— 一旦有人把目录查询挪进热重载路径，
        每次改配置就要打十个产品，这条会立刻红。
        """
        from model_gateway.accounts import net as accounts_net  # noqa: F401（锚点：扫描面必含它）
        # 让"名字已绑死"的那两类模块先进程（否则扫描面只剩源模块一条，判据退化）
        from model_gateway.upstream import cline as cline_pkg  # noqa: F401
        from model_gateway.upstream.cline import product as cline_product  # noqa: F401
        from model_gateway.upstream.buddy import product as buddy_product  # noqa: F401
        assert hasattr(cline_product, "make_client") or hasattr(buddy_product, "make_client"), \
            "产品模块不再 from-import make_client ⇒ 本条扫描式打桩的前提变了，须同步改判据"

        calls: list[str] = []

        def boom(*a, **kw):
            calls.append("outbound")
            raise AssertionError("规格层不得发网络请求")

        # 🔴 只 patch `accounts.net.make_client` 拦不住真实出站（评审 R2-④）：多数产品模块是
        #    `from model_gateway.accounts.net import make_client`（`upstream/cline/product.py`、
        #    `upstream/zcode/product.py`、`upstream/loomy/api.py` 实测），名字在导入时就绑死了，
        #    换掉源模块的属性对它们毫无影响 ⇒ 这条判据原本"打不到真路径"。
        #    改法：**遍历已加载的 `model_gateway.*`**，把每个持有 `make_client` 的模块都换成 boom，
        #    并断"扫描面确实覆盖到多处"（只抓到 1 处 = 扫描失效，判据自己先红）。
        patched = 0
        for mod_name, mod in list(sys.modules.items()):
            if not mod_name.startswith("model_gateway."):
                continue
            if getattr(mod, "make_client", None) is not None:
                monkeypatch.setattr(mod, "make_client", boom)
                patched += 1
        assert patched >= 2, f"零网络扫描面过窄（只替换到 {patched} 处 make_client）"

        root = tmp_path / "buddy"
        catalog_cache.write_cache("buddy", [ModelInfo(id="vm-x", context_window=512000,
                                                      max_output=8000)], root=root)
        cfg = _two_path_config()
        spec = resolve(cfg, cfg.models[0], _Pool(), cache_root=root, reader=_READER)
        assert spec.max_input == 512000 and spec.sources == 2
        assert not calls, "规格层发出了出站请求"

    def test_missing_cache_means_no_account_source_at_all(self, tmp_path):
        """缓存没有 = 账号侧**没有来源**：不联网补、不拿厂商那份冒充、不编数。"""
        cfg = _two_path_config()
        spec = resolve(cfg, cfg.models[0], _Pool(), cache_root=tmp_path / "buddy", reader=_READER)
        assert spec.sources == 1                       # 只剩Key 接入侧那一份
        assert spec.max_input == 262144

    def test_closed_product_bit_contributes_no_spec(self, tmp_path):
        """映射关着的资源不得把自己的大窗口"顶上去"（与调度同一判据）。"""
        root = tmp_path / "buddy"
        catalog_cache.write_cache("buddy", [ModelInfo(id="vm-x", context_window=1000000,
                                                      max_output=32000)], root=root)
        cfg = _two_path_config(product_bit=False)
        spec = resolve(cfg, cfg.models[0], _Pool(), cache_root=root, reader=_READER)
        assert spec.sources == 1 and spec.max_input == 262144

    def test_disabled_resource_contributes_no_spec(self, tmp_path):
        root = tmp_path / "buddy"
        catalog_cache.write_cache("buddy", [ModelInfo(id="vm-x", context_window=1000000)],
                                  root=root)
        cfg = _two_path_config()
        cfg.resources[1].enabled = False               # 号被停用
        spec = resolve(cfg, cfg.models[0], _Pool(), cache_root=root, reader=_READER)
        assert spec.sources == 1 and spec.max_input == 262144


def _two_account_config():
    """同一产品两个号 × 同一网关模型（🔴 号级规格的判据对象 = R5-F-1 那条没接的腿）。

    两个号故意写成**同一 base_url**：唯一的差别只有"各自的目录缓存"，
    这样任何数差都只能来自按号取数，不可能来自Key 接入侧/端点差异。
    """
    return AppConfig.model_validate({
        "resources": [
            {"id": "res-big", "product": "buddy", "account_ref": "a1", "api_key": "",
             "protocol": "openai", "base_url": "http://y/v1"},
            {"id": "res-small", "product": "buddy", "account_ref": "a2", "api_key": "",
             "protocol": "openai", "base_url": "http://y/v1"},
        ],
        "product_models": [{"product": "buddy", "model": "vm-x", "system_model": "glm-5.3",
                            "enabled": True}],
        "models": [{"name": "glm-5.3", "endpoint": "chat",
                    "resources": [{"resource": "res-big", "model": "vm-x"},
                                  {"resource": "res-small", "model": "vm-x"}]}],
    })


def _write_only_for_account(root, account, **fields):
    """只落**这个号自己**的目录缓存（产品级那份写完就删）⇒ 现场只剩按号证据。

    为什么必须删：`write_cache(source_account=…)` 会同时写产品级与按号两份，
    留着产品级就分不清"读到了按号那份"还是"读到了产品级那份" —— 判据会假绿。
    """
    catalog_cache.write_cache("buddy", [ModelInfo(id="vm-x", **fields)],
                              source_account=account, root=root)
    product_copy = catalog_cache.cache_path("buddy", root=root)
    if product_copy.exists():
        product_copy.unlink()
    assert catalog_cache.read_cache("buddy", root=root) is None


class _Pool2:
    """按**厂商模型标准名**索引的枚举池替身（键口径与生产同尺，见 M12 的教训）。"""

    def get(self, name):
        return _Entry(name) if name == "glm-5.2" else None


class TestPerAccountSpec:
    """🔴 R5-F-1（真机复验判死的阻塞项）：号级规格 / 承载校验 / 缺省注入必须**按号**取数。

    接线前 `product_spec` 只调 `reader(product, root=root)`（不带 `account`）⇒
    同产品全部账号共用**产品级**那一份。真机后果三条都已复现：
    ① 上限 64 的号照样被派活（承载判据根本不看号）；
    ② 没有自己目录的号被打上别号的上限 ⇒ 真实上游回 400，是我们主动制造的失败；
    ③ 只有按号缓存时 `/v1/models` 一律 `null` —— 规格明明取到了却不声明。
    """

    def test_each_account_carries_its_own_numbers(self, tmp_path):
        root = tmp_path / "buddy"
        _write_only_for_account(root, "a1", context_window=200000, max_output=8192)
        _write_only_for_account(root, "a2", context_window=200000, max_output=64)
        cfg = _two_account_config()
        big, small = cfg.resources[0], cfg.resources[1]

        assert resource_spec(big, "vm-x", None,
                             cache_root=root, reader=_READER).max_output == 8192
        assert resource_spec(small, "vm-x", None,
                             cache_root=root, reader=_READER).max_output == 64

    def test_declaration_is_not_null_when_only_per_account_caches_exist(self, tmp_path):
        """③ 的反证：对外声明读的是**逐号合并**，只有按号缓存也必须出数（不再 `null`）。"""
        root = tmp_path / "buddy"
        _write_only_for_account(root, "a1", context_window=1000000, max_output=8192)
        _write_only_for_account(root, "a2", context_window=262144, max_output=64)
        cfg = _two_account_config()
        spec = resolve(cfg, cfg.models[0], None, cache_root=root, reader=_READER)
        assert spec.sources == 2
        assert spec.max_input == 1000000          # 固定最大标准：池内取大
        assert spec.max_output == 8192

    def test_account_without_a_copy_falls_back_to_the_product_one(self, tmp_path):
        """兜底方向只能是"产品级兜底"（`a2` 从没取过目录 ⇒ 用产品那个数），
        且**不得**反过来：`a1` 有自己的证据时产品级那一份不能覆盖它。"""
        root = tmp_path / "buddy"
        # 顺序有意义：`source_account` 那次会**同时**覆盖产品级那一份，所以产品级单独再写一次，
        # 现场才是真实的"a1 有自己的数、产品级是另一个数、a2 从没取过目录"。
        catalog_cache.write_cache("buddy", [ModelInfo(id="vm-x", max_output=4096)],
                                  source_account="a1", root=root)
        catalog_cache.write_cache("buddy", [ModelInfo(id="vm-x", max_output=8192)], root=root)
        cfg = _two_account_config()
        big, small = cfg.resources[0], cfg.resources[1]
        assert resource_spec(big, "vm-x", None,
                             cache_root=root, reader=_READER).max_output == 4096
        assert resource_spec(small, "vm-x", None,
                             cache_root=root, reader=_READER).max_output == 8192

    def test_per_account_reads_are_memoized_separately(self, tmp_path):
        """🔴 记忆化键必须含号：一次热重载里同产品两个号共用 `cache` 字典，
        键只有 `(产品,)` 时**先读到的那个号会把数写给另一个号**（正是要防的 400）。"""
        root = tmp_path / "buddy"
        _write_only_for_account(root, "a1", max_output=8192)
        _write_only_for_account(root, "a2", max_output=64)
        cfg = _two_account_config()
        shared: dict = {}
        big, small = cfg.resources[0], cfg.resources[1]
        first = resource_spec(big, "vm-x", None, cache=shared, cache_root=root, reader=_READER)
        second = resource_spec(small, "vm-x", None, cache=shared, cache_root=root,
                               reader=_READER)
        assert (first.max_output, second.max_output) == (8192, 64)

    def test_one_shared_cache_across_two_data_roots_does_not_bleed(self, tmp_path):
        """🔴 评审 R8-报备 R-4：记忆化键必须含 `root`（`root` 这个形参存在的意义就是跨树）。

        同一次装配里两棵数据根（非默认根的实例 / 测试）共用一个 `cache` 字典时，
        键只有 `(产品, 号)` ⇒ 第二个号读到**第一棵树**的缓存：界面上的规格与实际账号库不同源，
        正是"实例身份自证"那条红线要防的形状。
        """
        a = tmp_path / "tree-a" / "buddy"
        b = tmp_path / "tree-b" / "buddy"
        catalog_cache.write_cache("buddy", [ModelInfo(id="vm-x", max_output=8192)],
                                  source_account="a1", root=a)
        catalog_cache.write_cache("buddy", [ModelInfo(id="vm-x", max_output=64)],
                                  source_account="a1", root=b)
        cfg = _two_account_config()
        shared: dict = {}
        res = cfg.resources[0]
        assert resource_spec(res, "vm-x", None, cache=shared, cache_root=a,
                             reader=_READER).max_output == 8192
        assert resource_spec(res, "vm-x", None, cache=shared, cache_root=b,
                             reader=_READER).max_output == 64

    def test_the_public_catalog_is_deliberately_not_a_third_fallback(self):
        """🔴 第三档兜底（枚举池公开上限）明确**不取**，这条把决定钉住（评审 R9 SPEC-NOPOOL）。

        账号侧取数只有两档：按号副本 → 产品级副本。公开目录里同 id 的 `max_output`
        （如 `glm-5.2` = 131072）**不拿来给没刷过目录的号兜底**，因为那个数是厂商公开上限、
        而号级套餐可以更窄 ⇒ 用它当"这条号装得了"的依据 = 又一次 fail-open 的 400
        （正是 R5-F-1 判死的那件事）。代价也如实写：没刷过目录的号在承载与缺省两条腿上都是"不知道"
        ⇒ 一切照发，由上游答复告诉我们（`tech-design §22.5-9` 的取舍段已同步）。
        """
        cfg = _two_account_config()
        spec = resource_spec(cfg.resources[0], "glm-5.2", _Pool2(),
                             cache_root=None, reader=lambda *a, **kw: None)
        assert spec.max_output is None and spec.sources == 0

    def test_a_disabled_mapping_never_erases_the_resource_fact(self):
        """🔴 评审 R8-B-1 的语义那半句：资源级规格 = 这条 (资源, 供应商模型名) **自己**的事实。

        开关（条目位 / 产品位）决定的是"进不进这个系统的池"，那份判据归 `sources_for_entries`
        （对外声明用）；把它同时压在资源级规格上，就会在**别名**形状下出事：
        同一组合挂在第二个网关模型上而那一头关着 ⇒ 后算的那份空壳**覆盖**掉生效那份
        （键 `(rid, vendor_model)` 没有网关模型维度），承载判据与缺省注入双双静默失效，
        而且红不红取决于配置书写顺序。端到端那条腿在
        `test_q33_two_level_switch_api.py::TestPerAccountSpecWiring::test_another_system_model_switch_cannot_erase_this_resources_spec`。
        """
        cfg = _two_path_config()
        cfg.models[0].resources[0].enabled = False          # Key 接入侧条目关着
        spec = resource_spec(cfg.resources[0], "vm-k", _Pool())
        assert spec.max_output == 65536, spec
        # 同一份配置走**声明**那条路：关着的映射不得把自己的窗口"顶上去"（判据仍在）
        assert resolve(cfg, cfg.models[0], _Pool(), reader=None).sources == 0

    def test_no_cache_for_the_account_invents_nothing(self, tmp_path):
        """两样都没有 ⇒ `max_output=None` = 不知道，承载判据据此**不拦**（不编数）。"""
        cfg = _two_account_config()
        spec = resource_spec(cfg.resources[0], "vm-x", None,
                             cache_root=tmp_path / "buddy", reader=_READER)
        assert spec.max_output is None and spec.sources == 0


class TestCapsMerge:
    class _Entry:
        def __init__(self, *, tool_call=True, image_input=False, reasoning=True):
            self.display = "GLM 5.3"
            self.vendor = "智谱"
            self.context_window = 262144
            self.max_output = 65536
            self.tool_call = tool_call
            self.image_input = image_input
            self.reasoning = reasoning
            self.effort_levels = ("low", "high")

    class _Pool:
        def __init__(self, entry):
            self._e = entry

        def get(self, name):
            return self._e if name == "glm-5.3" else None

    class _Model:
        name = "glm-5.3"

    def test_without_spec_is_byte_identical_to_before(self):
        pool = self._Pool(self._Entry())
        caps = build_model_caps(self._Model(), pool)
        # 🔴 契约扩展之后多了一个**只读标注位** `specStale`（台账 §17）；
        #    这条判据的原意是"不传规格时数值/布尔腿一个字都不许变"，所以只把新增位摘出来，
        #    其余七项仍逐字对老形状。
        assert caps.pop("specStale") is False, "无合并规格参与声明 ⇒ 陈旧位必须是 False，不是缺失"
        assert caps == {"name": "GLM 5.3", "vendor": "智谱", "maxInputTokens": 262144,
                        "maxOutputTokens": 65536, "supportsToolCall": True,
                        "supportsImages": False, "supportsReasoning": True}

    def test_spec_staleness_is_declared_and_only_that(self):
        """🔴 UT-95（单元腿；端到端见 INT-93）：`from_stale_cache` 必须有用户可见出口。

        上一版这件事算出来了却**零消费方** ⇒ 界面上"昨天取到的数"与"实时取到的数"一模一样。
        三条缺一不可：陈旧 ⇒ `true`、新鲜 ⇒ `false`、**不许**顺手改动数值腿。
        """
        pool = self._Pool(self._Entry())
        stale = ModelSpec(max_input=1_000_000, max_output=65536, sources=1,
                          from_stale_cache=True)
        fresh = ModelSpec(max_input=1_000_000, max_output=65536, sources=1,
                          from_stale_cache=False)
        a = build_model_caps(self._Model(), pool, spec=stale)
        b = build_model_caps(self._Model(), pool, spec=fresh)
        assert a["specStale"] is True and b["specStale"] is False
        # 标注位是**附加**事实，不许把数改掉或改成 null（工具侧仍按承诺上限规划请求）
        assert a["maxInputTokens"] == b["maxInputTokens"] == 1_000_000

    def test_custom_model_without_catalog_entry_still_declares_the_flag(self):
        """不在内置目录、只有规格时也必须带这个位（缺字段 = 界面只能显示"不知道"）。"""
        caps = build_model_caps(self._Model(), None,
                                spec=ModelSpec(max_output=4096, sources=1,
                                               from_stale_cache=True))
        assert caps["specStale"] is True and caps["maxOutputTokens"] == 4096

    def test_minimal_exit_without_pool_or_spec_still_declares_the_flag(self):
        """🔴 复验 R10 报备 1 补的判据：三条 return 都得带这个位，**最早那条也不例外**。

        `entry is None and spec is None`（既不在内置目录、又没有合并规格）走的是函数开头
        那条最小 return。把 `specStale` 只加在后两条上时，全量 115 条**一条都不红**，
        而这个模型是真的会走到那条路上（自定义名 + 号全没目录）⇒ 字段集随分支漂移，
        消费方就得写 `if (specStale === undefined)`，等于把"陈旧"重新变成不可判定。
        """
        caps = build_model_caps(self._Model(), None)
        assert "specStale" in caps, f"最小出口丢了标注位：{sorted(caps)}"
        assert caps["specStale"] is False, caps
        assert caps["maxOutputTokens"] is None and caps["supportsToolCall"] is None

    def test_spec_can_lift_numbers_and_union_flags(self):
        pool = self._Pool(self._Entry())
        spec = ModelSpec(max_input=1000000, max_output=32000, tool_call=None,
                         image_input=True, reasoning=None, sources=1)
        caps = build_model_caps(self._Model(), pool, spec=spec)
        assert caps["maxInputTokens"] == 1000000      # 取大
        assert caps["maxOutputTokens"] == 65536       # 规格更小 ⇒ 不降级
        assert caps["supportsImages"] is True         # 取并
        assert caps["supportsToolCall"] is True       # 规格 None ⇒ 保留目录值

    def test_custom_model_with_spec_only_does_not_crash(self):
        """不在内置目录的自定义模型：只拿到账号侧规格时也必须能声明。"""
        class M:
            name = "my-own-model"

        spec = ModelSpec(max_input=8000, max_output=2000, tool_call=True,
                         image_input=None, reasoning=True, sources=1)
        caps = build_model_caps(M(), None, spec=spec)
        assert caps["name"] == "my-own-model" and caps["vendor"] == ""
        assert caps["maxInputTokens"] == 8000 and caps["supportsToolCall"] is True
        # 🔴 规格与目录都**没说**图片输入 ⇒ 输出 `null`（不知道），不再印 `false`
        #    （R3-F-3：`false` 是明确不支持的承诺，而我们没有这个证据）
        assert caps["supportsImages"] is None

    def test_spec_saying_no_out_loud_lands_false_not_null(self):
        """🔴 R5-F-4 缺口①（并集的下半句）：全否是**有据的否**，必须落 `false`。

        `merge_specs` 只有在"每个开过口的来源都说不具备"时才给出 `False`（混着沉默给 `None`），
        所以到这一层的 `False` 已经是证据，继续印 `null` 就是把这条证据丢掉 ——
        目录侧能表达"明确不支持"、账号侧只能表达"不知道"也不对称。
        """
        class M:
            name = "my-own-model"

        spec = merge_specs([{"image_input": False}, {"image_input": False}])
        assert spec.image_input is False and spec.sources == 2
        caps = build_model_caps(M(), None, spec=spec)
        assert caps["supportsImages"] is False

    def test_a_silent_source_blocks_the_negative_claim(self):
        """反向腿（不许把"有沉默来源"当成"全都说不"）：一个号明说不支持、另一个号没说
        ⇒ 只能说不知道。写成 `false` 会让工具删掉 `tools`，误杀那个没说话的号。"""
        class M:
            name = "my-own-model"

        spec = merge_specs([{"tool_call": False}, {}])
        assert spec.tool_call is None
        # 🔴 评审 R8-报备 R-5 的落地：字段 `sourced` 直接删掉（零生产消费方的"看起来是判据"
        #    最容易被子下轮当成证据用）。这里改断**具体字段**：沉默的来源挡住否定、计数照实
        assert spec.sources == 2
        caps = build_model_caps(M(), None, spec=spec)
        assert caps["supportsToolCall"] is None

    def test_non_chat_endpoint_never_promise_tool_call(self):
        """🔴 R5-F-4 缺口②（端点不变量要守住**出口**）：`endpoint=images` 曾被账号目录的
        `tool_call=true` 并成 `supportsToolCall: true` —— 图像端点没有 `tools` 参数，
        那句承诺是空的。`EnumEntry.__post_init__` 只压得住来源，压不住合并腿。"""
        class M:
            name = "my-own-model"
            endpoint = "images"

        caps = build_model_caps(M(), None, spec=ModelSpec(tool_call=True, image_input=True, sources=1))
        assert caps["supportsToolCall"] is False      # 有依据的否，不许被并上来翻掉
        assert caps["supportsImages"] is True         # 其余位照常合并


    def test_endpoint_invariant_holds_without_a_spec(self, ):
        """🔴 评审 R8-报备 R-8：端点不变量原先**只在合并腿**上压。

        `spec=None` 的那条出口（`build_model_caps` 直接返回 `base`）根本不经过 `_merge_spec_maxima`，
        于是"目录里有同名 chat 条目 + 网关模型被改成 images 端点"这种形状照样对外承诺
        `supportsToolCall: true` —— 图像端点没有 `tools` 参数，那句承诺是空的。
        不变量属于**出口**，不属于某一条来源的算法。
        """
        class M:
            name = "glm-5.3"
            endpoint = "images"

        entry = self._Entry(tool_call=True)      # 目录侧说"能"，端点侧根本做不到
        caps = build_model_caps(M(), self._Pool(entry))
        assert caps["supportsToolCall"] is False
        assert caps["maxInputTokens"] == 262144   # 其余字段照旧（不是把整块压成保守）

class TestOutboundDefaultPriority:
    """工具传参 > 网关设置 > 统一规格 > 供应商通道默认（Q24 与 Q33-④ 同一条优先级链）。"""

    def test_caller_value_wins(self):
        body = {"max_tokens": 128}
        apply_spec_defaults(apply_model_params(body, {"max_tokens": 4096}),
                            ModelSpec(max_output=65536))
        assert body["max_tokens"] == 128

    def test_gateway_params_win_over_spec(self):
        body = {}
        apply_spec_defaults(apply_model_params(body, {"max_tokens": 4096}),
                            ModelSpec(max_output=65536))
        assert body["max_tokens"] == 4096

    def test_spec_fills_only_when_nothing_said(self):
        body = {}
        apply_spec_defaults(apply_model_params(body, None), ModelSpec(max_output=65536))
        assert body["max_tokens"] == 65536

    def test_max_completion_tokens_counts_as_said(self):
        body = {"max_completion_tokens": 512}
        apply_spec_defaults(body, ModelSpec(max_output=65536))
        assert "max_tokens" not in body

    def test_no_spec_or_no_number_injects_nothing(self):
        """🔴 规格没这个数就**什么都不注入**（继续走该供应商通道默认，不编一个"看起来对"的数）。"""
        for spec in (None, ModelSpec(), ModelSpec(max_output=0)):
            body = {}
            apply_spec_defaults(body, spec)
            assert body == {}
