"""学习轮 V3 临时复现件（L3 结构门 / L9 能力位取证）—— 🔴 临时件，**不要入库**。

不改动任何既有源码与测试；只读扫描 + 在 tmp 目录里造形状。
入库会污染 `test_readme_test_counts_are_not_stale` 的计数账，用完请删除或留在
untracked 状态（与 `verify_v1_stream_repro.py` / `verify_v2_gate_repro.py` 同一处置）。

跑法：
    cd coding && .venv/bin/python -m pytest -q tests/verify_v3_repro.py

覆盖任务书要求的三条实证：
  ① A 组：`mapping_enabled` 的调用点普查（AST）+ 旁路探测 + 「键维度」普查
  ② B3：图片请求打到「目录声明不支持图片」的账号资源，看我方实际发生什么
  ③ B1/B2：`image_input` 的非取证来源（raccoon 的 `tags` 猜）—— file:line + 实测
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]          # = coding/
PKG = REPO / "model_gateway"
TESTS = REPO / "tests"


# =========================================================================
# 通用：AST 扫描工具（这些函数就是「门」的原型，判据形态在这里先跑通）
# =========================================================================

def _py_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _rel(path: Path) -> str:
    try:
        return path.relative_to(REPO).as_posix()
    except ValueError:
        return path.as_posix()


def _attr_name(node) -> str | None:
    """`cfg.mapping_enabled(...)` → 'mapping_enabled'；`self.x.y(...)()` → 'y'。"""
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def call_sites(files: list[Path], fn_attr: str) -> list[tuple[str, int, int, bool]]:
    """`(文件, 行号, 实参数, 是否带常量实参)` —— 某属性方法的**真实调用点**（AST，不算注释）。

    这是插件 `trae-model-id-selection.spec.ts:189`「选号调用不得传硬编码空串」的 Python 版：
    插件用「大括号配平切源码块 + 正则」，Python 有 AST，不必切文本块。
    """
    out: list[tuple[str, int, int, bool]] = []
    for f in files:
        tree = _parse(f)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and _attr_name(node.func) == fn_attr):
                continue
            hard_coded = any(isinstance(a, ast.Constant) for a in node.args) \
                or any(isinstance(kw.value, ast.Constant) for kw in node.keywords)
            out.append((_rel(f), node.lineno, len(node.args), hard_coded))
    return out


def predicate_bypasses(files: list[Path]) -> list[tuple[str, int, str, list[str]]]:
    """「第二份判据」探测（L3 的核心形状）。

    规则（可机械红、不需要类型推断）：某个函数体里
      ① 把一个 `product_mapping(...)` 的返回值绑到局部名 `X`（含 `X = A if … else None` 这种三元），
      ② **读**了 `X.enabled`（Load 语境；写产品位的 `bit.enabled = …` 不算旁路），
      ③ 而这个函数本身**不是** `mapping_enabled`、内部也**没有**调用 `mapping_enabled`。
    ⇒ 它就是在判据之外自己判了一次「进不进池」。

    对应插件那条律：不是"少传一个参数"，而是"同一个事实有第二个算法"。
    """
    hits: list[tuple[str, int, str, list[str]]] = []
    for f in files:
        tree = _parse(f)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if fn.name == "mapping_enabled":
                continue
            bound: set[str] = set()
            calls_predicate = False
            for node in ast.walk(fn):
                # ① bit = cfg.product_mapping(...)  /  bit = … if … else None
                if isinstance(node, ast.Assign) and _contains_call(node.value, "product_mapping"):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            bound.add(t.id)
                # ③ 同函数里调用过 mapping_enabled
                if isinstance(node, ast.Call) and _attr_name(node.func) == "mapping_enabled":
                    calls_predicate = True
            if not bound or calls_predicate:
                continue
            src = f.read_text(encoding="utf-8").splitlines()
            reads_enabled: list[str] = []
            for node in ast.walk(fn):
                # ② **读** X.enabled（Store 语境 = 写位，不是判位）
                if (isinstance(node, ast.Attribute) and node.attr == "enabled"
                        and isinstance(node.ctx, ast.Load)
                        and isinstance(node.value, ast.Name) and node.value.id in bound):
                    reads_enabled.append(f"{node.lineno}: {src[node.lineno - 1].strip()}")
            if reads_enabled:
                hits.append((_rel(f), fn.lineno, fn.name, reads_enabled))
    return hits


def _contains_call(node, attr: str) -> bool:
    """表达式里（任意深度，含三元/布尔式）是否存在 `.<attr>(...)` 调用。"""
    if isinstance(node, ast.Call) and _attr_name(node.func) == attr:
        return True
    return any(_contains_call(c, attr) for c in ast.iter_child_nodes(node))


def _tuple_vars(tree: ast.Module) -> dict[str, tuple[str, int]]:
    """文件内 `KEY = (a, b, …)` 这类**元组变量**登记表：`{名字: (表达式, 元数)}`。

    仅一层、按整个文件取（不区分作用域）—— 够本普查用，也如实承认它粗：
    真做成门时要按「读点所属函数」收窄，否则同名变量会互相顶替
    （这条教训正是 `test_v2_wiring_guard.py` 里"同名顶替"那一族）。
    """
    table: dict[str, tuple[str, int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Tuple):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    table[t.id] = (ast.unparse(node.value), len(node.value.elts))
    return table


def _key_shape(k, tv: dict[str, tuple[str, int]]) -> tuple[str, int]:
    """键表达式 → `(可读形态, 元数)`；裸变量名会解析回它指向的元组。"""
    if isinstance(k, ast.Tuple):
        return ast.unparse(k), len(k.elts)
    if isinstance(k, ast.Name) and k.id in tv:
        text, arity = tv[k.id]
        return f"{text}（变量 {k.id}）", arity
    return ast.unparse(k), 1


def dict_key_shapes(files: list[Path], names: set[str]) -> list[dict]:
    """「键维度普查」（L3② —— 我方 R8-B-1 / R9-B-1' 那一族病灶的机器可读形态）。

    找 `NAME[key] = value` / `NAME = {k: … for …}` / `NAME.get(key)` / `NAME[key]`：
      - 键若是元组，报出**元素表达式**（人一眼能看出少没少维度）；
      - 键若是裸变量，解析回它指向的元组（`resource_specs[key]` 那种写法）。
    一条律 = 建表与消费的键形状必须逐字同构；R8-B-1 就是"建表带了网关模型维度、
    消费没带"（反过来 B-1' 是"该带的没带"）—— 两个方向都得钉，见 A6。
    """
    out: list[dict] = []
    for f in files:
        tree = _parse(f)
        tv = _tuple_vars(tree)
        for node in ast.walk(tree):
            # 下标赋值：resource_specs[key] = ...
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                            and t.value.id in names):
                        key, arity = _key_shape(t.slice, tv)
                        out.append({"file": _rel(f), "line": node.lineno, "name": t.value.id,
                                    "kind": "写键", "key": key, "arity": arity})
            # 字典推导建表：model_specs = {m.name: ... for m in ...}
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.DictComp):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id in names:
                        key, arity = _key_shape(node.value.key, tv)
                        out.append({"file": _rel(f), "line": node.lineno, "name": t.id,
                                    "kind": "建表(推导)", "key": key, "arity": arity})
            # 消费：NAME.get(key) / getattr(x, "NAME", {}).get(key)
            if isinstance(node, ast.Call) and _attr_name(node.func) == "get":
                base_name = None
                base = node.func.value
                if isinstance(base, ast.Name) and base.id in names:
                    base_name = base.id
                if (base_name is None and isinstance(base, ast.Attribute)
                        and base.attr in names):
                    base_name = base.attr          # runtime.model_specs.get(...) / self.runtime.x
                if (base_name is None and isinstance(base, ast.Call)
                        and isinstance(base.func, ast.Name) and base.func.id == "getattr"):
                    consts = [a.value for a in base.args if isinstance(a, ast.Constant)]
                    base_name = next((c for c in consts if c in names), None)
                if base_name and node.args:
                    key, arity = _key_shape(node.args[0], tv)
                    out.append({"file": _rel(f), "line": node.lineno, "name": base_name,
                                "kind": "读键(.get)", "key": key, "arity": arity})
            # 消费：NAME[key]（非赋值语境）
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
                    and node.value.id in names and not isinstance(node.ctx, ast.Store):
                key, arity = _key_shape(node.slice, tv)
                out.append({"file": _rel(f), "line": node.lineno, "name": node.value.id,
                            "kind": "读键([])", "key": key, "arity": arity})
    return out


# =========================================================================
# A 组：L3 —— 一条判据只有一个主人
# =========================================================================

def test_a1_mapping_enabled_census():
    """① 现役调用点普查：AST 数出来到底几处、每处传了几个实参、有没有硬编码常量实参。"""
    sites = call_sites(_py_files(PKG), "mapping_enabled")
    real = [s for s in sites if s[2] == 3]
    print("\n[L3-①] `AppConfig.mapping_enabled` 的调用点（AST，不含注释/docstring）：")
    for f, ln, arity, hard in sites:
        print(f"   {f}:{ln}  实参数={arity}  含常量实参={'是' if hard else '否'}")
    print(f"   合计 {len(sites)} 处，其中三元（resource, entry, system_model）齐全 {len(real)} 处")

    # 判据本体（未来新增调用点少传参数 ⇒ 这里必红）
    assert len(sites) >= 9, f"调用点数骤降，普查可能失效：{len(sites)}"
    bad = [s for s in sites if s[2] != 3]
    assert not bad, f"有调用点没传满三元判据（少维度 = R8-B-1 同族）：{bad}"
    hard = [s for s in sites if s[3]]
    assert not hard, f"有调用点把判据的某一维写成了常量（漏传/硬编码形状）：{hard}"


def test_a1b_census_scan_is_not_vacuous(tmp_path):
    """①-b 撤证：普查本身必须能红 —— 种一个「只传两元」的调用点，必须被点出来。

    「门跑绿可能只是因为判据悄悄失效」是本仓 pitfalls 反复登记的那一条；
    没有这条，A1 的"0 条违规"没有任何证据价值。
    """
    canary = tmp_path / "model_gateway_canary" / "c.py"
    canary.parent.mkdir(parents=True)
    canary.write_text(
        "def pick(cfg, res, entry):\n"
        "    return cfg.mapping_enabled(res, entry)\n",       # 少了 system_model 那一维
        encoding="utf-8")
    got = call_sites([canary], "mapping_enabled")
    assert got == [(_rel(canary), 2, 2, False)], got
    assert any(s[2] != 3 for s in got), "普查没能认出少传参数 —— 判据是空判据"


def test_a2_second_implementation_census():
    """② 旁路探测：判据之外还有没有第二份「进不进池」的算法。

    🔴 判据随 S-3 前进（2026-10-05）：`_map_enabled` 已合流调度判据（内部调用
    `mapping_enabled`）——探测器规则③「函数内没调 mapping_enabled」现在会**豁免**它
    ⇒ 命中列表为空正是合流成功的机械证据。旧断言（钉 `_map_enabled` 必须在旁路名单里）
    钉的是分叉本身，已随合流作废；探测器本身的撤证在 a2b（种新旁路必被认出）。
    """
    hits = predicate_bypasses(_py_files(PKG))
    print("\n[L3-②] 判据之外读产品位开关位的地方（候选旁路）：")
    for f, ln, name, reads in hits:
        print(f"   {f}:{ln}  {name}()")
        for r in reads:
            print(f"        └ {r}")
    print(f"   合计 {len(hits)} 处")
    known = {h[2] for h in hits}
    assert "_map_enabled" not in known, \
        f"S-3 合流后 `_map_enabled` 不应再是旁路（内部已调 mapping_enabled）：{sorted(known)}"


def test_a2b_bypass_detector_catches_planted(tmp_path):
    """②-b 撤证：种一个同样形状的新旁路，探测器必须认出来（否则 A2 只是抄了一份名单）。"""
    canary = tmp_path / "k.py"
    canary.write_text(
        "def my_pool_on(cfg, product, mid):\n"
        "    bit = cfg.product_mapping(product, mid)\n"
        "    return bool(bit.enabled)\n", encoding="utf-8")
    hits = predicate_bypasses([canary])
    assert [h[2] for h in hits] == ["my_pool_on"], hits
    # 反向：真走了判据的函数不许被误报（否则白名单会长成垃圾桶）
    ok = tmp_path / "ok.py"
    ok.write_text(
        "def use_it(cfg, res, entry, name):\n"
        "    bit = cfg.product_mapping(res.product, entry.model)\n"
        "    return cfg.mapping_enabled(res, entry, name) and bool(bit.enabled)\n",
        encoding="utf-8")
    assert predicate_bypasses([ok]) == [], "已调用判据的函数被误报"


def test_a3_no_fail_open_guard():
    """③ `hasattr(x, "mapping_enabled")` 这种兜底 = 判据缺席时**放行**（fail-open）。

    与插件那条「不得传硬编码空串」是同一族：判据没被真正执行，却报绿。
    """
    bad: list[str] = []
    for f in _py_files(PKG):
        tree = _parse(f)
        src = f.read_text(encoding="utf-8").splitlines()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "hasattr"
                    and any(isinstance(a, ast.Constant)
                            and a.value in ("mapping_enabled", "product_mapping")
                            for a in node.args)):
                bad.append(f"{_rel(f)}:{node.lineno} {src[node.lineno - 1].strip()}")
    print("\n[L3-③] 判据被 hasattr 兜住（缺席即整条短路）的位置：")
    for b in bad:
        print("   " + b)
    print(f"   合计 {len(bad)} 处")
    assert bad, "普查失效预期：本仓当前确有此形状，一条都没有说明扫描没跑起来"
    # 这一条不断言为零（改动面在处方里，不在裁决里）；只把事实钉出来


# =========================================================================
# A 组续：行为侧「两套真相」—— 上面是源码形状，这里验它真的会分叉
# =========================================================================

def _cfg_dict(*, bits: list[dict], models: list[dict], res: list[dict]):
    return {"resources": res, "models": models, "product_models": bits,
            "gateway": {"access_tokens": [{"id": "t1", "value": "gw-x"}]}}


def _acct_res(rid="res-acct", product="buddy", account="a1"):
    return {"id": rid, "name": "账号资源", "product": product, "account_ref": account,
            "account": account, "protocol": "openai", "base_url": "http://127.0.0.1:9/v1",
            "api_key": "", "enabled": True}


def _app_config(cfg_dict: dict):
    from model_gateway.config.schemas import AppConfig

    return AppConfig.model_validate(cfg_dict)


def _resource_names(cfg):
    return {r.id: r for r in cfg.resources}


def test_a4_product_bit_points_elsewhere_two_truths():
    """④ 形状一：产品位指向 sys-a，条目住在 sys-b。

    🔴 判据随 S-3 前进（2026-10-05）：`_map_enabled` 已与 `AppConfig.mapping_enabled`
    合流（无位回落带系统模型维度）——本形状两边一致说「不进池」，两套真相消灭；
    旧断言（`ui is True` 的分叉复现）见 git 历史。
    """
    cfg = _app_config(_cfg_dict(
        res=[_acct_res()],
        models=[
            {"name": "sys-a", "endpoint": "chat", "resources": []},
            {"name": "sys-b", "endpoint": "chat",
             "resources": [{"resource": "res-acct", "model": "vm-x", "enabled": True}]},
        ],
        bits=[{"product": "buddy", "model": "vm-x", "system_model": "sys-a", "enabled": True}],
    ))
    from model_gateway.core.resources import servable_models

    res = _resource_names(cfg)["res-acct"]
    entry_b = cfg.models[1].resources[0]
    judge = cfg.mapping_enabled(res, entry_b, "sys-b")
    from model_gateway.api.admin_accounts import _map_enabled

    ui = _map_enabled(cfg, "buddy", {"res-acct"}, "vm-x")
    servable = servable_models(cfg, None)
    print(f"\n[L3-④] 判据 mapping_enabled(sys-b 条目) = {judge}；"
          f"弹窗 _map_enabled = {ui}；servable_models = {sorted(servable)}")
    assert judge is False, "前提不成立：判据这次没把它拦在池外"
    assert ui is False, f"合流后弹窗也应说不进池：_map_enabled 返回 {ui}"
    assert servable == set(), f"servable 非空：{servable}"


def test_a5_legacy_aggregate_two_truths():
    """⑤ 形状二（旧配置零迁移那条回落路）：无产品位，同组合别名挂两个模型、开关不同。

    🔴 判据随 S-3 前进（2026-10-05）：合流后的 `_map_enabled` 逐系统模型对齐调度判据
    ——「任一系统模型下按调度判据进池 ⇒ True」与调度侧 `servable_models` 一致；
    旧断言钉的「聚合分叉」已消灭。**设计含义**：条目粒度的弹窗开关显示的是
    "该产品条目至少在一个网关模型里活着"，与 `/v1/models` 声明同源。
    """
    cfg = _app_config(_cfg_dict(
        res=[_acct_res()],
        models=[
            {"name": "sys-a", "endpoint": "chat",
             "resources": [{"resource": "res-acct", "model": "vm-x", "enabled": True}]},
            {"name": "sys-b", "endpoint": "chat",
             "resources": [{"resource": "res-acct", "model": "vm-x", "enabled": False}]},
        ],
        bits=[],
    ))
    from model_gateway.api.admin_accounts import _map_enabled

    res = _resource_names(cfg)["res-acct"]
    ui = _map_enabled(cfg, "buddy", {"res-acct"}, "vm-x")
    per_model = {m.name: cfg.mapping_enabled(res, m.resources[0], m.name) for m in cfg.models}
    print(f"\n[L3-⑤] 逐模型判据 = {per_model}；弹窗聚合 _map_enabled = {ui}")
    assert per_model == {"sys-a": True, "sys-b": False}, per_model
    assert ui is True, f"合流后：sys-a 下活着 ⇒ True（与调度一致）：{ui}"
    # 合流的反向钉：两个系统模型里都关着时，弹窗也必须说 False（旧实现同样说 False，
    # 但当时是聚合巧合；现在是有据的）
    cfg2 = _app_config(_cfg_dict(
        res=[_acct_res()],
        models=[
            {"name": "sys-a", "endpoint": "chat",
             "resources": [{"resource": "res-acct", "model": "vm-x", "enabled": False}]},
            {"name": "sys-b", "endpoint": "chat",
             "resources": [{"resource": "res-acct", "model": "vm-x", "enabled": False}]},
        ],
        bits=[],
    ))
    res2 = _resource_names(cfg2)["res-acct"]
    assert _map_enabled(cfg2, "buddy", {"res-acct"}, "vm-x") is False
    assert cfg2.mapping_enabled(res2, cfg2.models[0].resources[0], "sys-a") is False


def test_a6_key_dimension_census():
    """⑥ 「另一个必须整链传参的字段」普查：三张映射表的建表键 vs 消费键形状（R8-B-1 同族）。"""
    shapes = dict_key_shapes(_py_files(PKG), {"reasoning_map", "model_specs", "resource_specs"})
    print("\n[L3-②] 键维度普查（建表键 ⇄ 消费键必须同构）：")
    for s in shapes:
        print(f"   {s['file']}:{s['line']}  {s['name']:<14} {s['kind']:<10} "
              f"元数={s['arity']}  键={s['key']}")
    assert shapes, "普查失效：三张表一个键形状都没扫到"

    by_name: dict[str, list[dict]] = {}
    for s in shapes:
        by_name.setdefault(s["name"], []).append(s)

    # 不变量（**正向钉**）：reasoning_map 的键必须带网关模型维度（R9-B-1' 的修复本体）
    rm = by_name.get("reasoning_map", [])
    assert rm, "reasoning_map 未被扫到（改名/删除 ⇒ 本普查的覆盖面也过期了）"
    assert all(".name" in s["key"] for s in rm if s["kind"].startswith("写")), \
        f"reasoning_map 的键丢了网关模型维度（B-1' 复发）：{rm}"

    # 不变量（**反向钉**，对应插件 `refresh 块应该保留空串` 那一型）：
    # resource_specs 的键**不许**带网关模型维度（R8-B-1 判死的原因），且建表/消费必须同为二元
    rs_all = by_name.get("resource_specs", [])
    rs_read = [s for s in rs_all if s["kind"].startswith("读")]
    assert rs_read, f"resource_specs 的消费点没扫到（普查覆盖面过期）：{rs_all}"
    for s in rs_all:
        assert "m.name" not in s["key"] and "system_model" not in s["key"], \
            f"resource_specs 的键混进了网关模型维度（R8-B-1 复发）：{s}"
    assert all(s["arity"] == 2 for s in rs_all), \
        f"resource_specs 建表/消费的键元数不一致（少一维 = 别名互相覆盖）：{rs_all}"


# =========================================================================
# B 组：L9 —— 能力位必须实测，不许拿元数据当契约
# =========================================================================

#: 2026-10-03 由 DSH 插件实拉的远端 `model_catalog` tags，**逐条抄自**
#: `/Users/w/Desktop/AI工作站/05-dsh插件/deepseek-harness-codearts/tests/unit/raccoon-product.spec.ts`
#: 的 `REMOTE_TAGS`（那份文件本身就是"把远端原始数据钉进测试"的做法）。
#: 用途 = 把**同一份远端事实**喂给我方解析腿，看我方判成什么。
REMOTE_TAGS_20261003: dict[str, list[str]] = {
    "sn-sensenova-6-8-flash": ["general", "chat", "rewrite", "summary", "fast", "vision", "fast"],
    "sn-sensenova-6-8-flash-lite": ["general", "chat", "rewrite", "summary", "fast", "vision", "fast"],
    "sn-glm-5-3": ["general", "office", "code", "vision", "debug", "analysis", "html", "reasoning"],
    "sn-kimi-k3": ["general", "office", "code", "vision", "debug", "analysis", "html", "reasoning"],
    "sn-glm-5-3-flash": ["general", "chat", "rewrite", "summary", "fast"],
    "sn-deepseek-v4-1-flash": ["general", "code", "html", "analysis", "reasoning", "auto"],
}

#: 插件 commit `df25f01` 的**实测结论**（带随机 6 位数字图打真实端点）：
#: 6 个可见模型全部能读图；其中 `sn-glm-5-3` 1/3（provider 侧节点不一致，另一族病）。
MEASURED_IMAGE_OK_20261003 = {
    "sn-sensenova-6-8-flash": True,
    "sn-sensenova-6-8-flash-lite": True,
    "sn-glm-5-3": "1/3 节点不一致",
    "sn-kimi-k3": True,
    "sn-glm-5-3-flash": True,
    "sn-deepseek-v4-1-flash": True,
}


def test_b1_raccoon_image_input_is_derived_from_tags():
    """⑦ `image_input` 的来源链里有一处**非取证来源**：raccoon 的 tags 命中表。

    file:line：
      - `model_gateway/upstream/raccoon/protocol.py:391`
        `image_input=bool(lowered & set(C.VISION_TAGS))`
      - `model_gateway/upstream/raccoon/const.py:125` `VISION_TAGS = ("vision","image","image-understanding")`
    """
    from model_gateway.upstream.raccoon import const as C
    from model_gateway.upstream.raccoon.protocol import _normalize_remote_model

    rows = []
    for mid, tags in REMOTE_TAGS_20261003.items():
        info = _normalize_remote_model({"name": mid, "description": mid,
                                        "params": {"context_window": 1000000,
                                                   "max_tokens": 100000},
                                        "tags": tags})
        assert info is not None, mid
        rows.append((mid, "vision" in tags, info.image_input,
                     MEASURED_IMAGE_OK_20261003[mid]))

    fb = {m.id: m.image_input for m in C.FALLBACK_MODELS}
    print("\n[L9-①] raccoon：远端 tags（2026-10-03 实拉）→ 我方解析 → 我方兜底表 → 插件实测")
    print(f"   {'模型':<30} {'tags含vision':<12} {'我方解析image_input':<18} "
          f"{'我方兜底表':<12} {'插件实测':<12}")
    disagree_parse, disagree_pair = [], []
    for mid, has_tag, parsed, measured in rows:
        mark = "  "
        if parsed is not True:
            disagree_parse.append(mid)
            mark = "🔴"
        if fb.get(mid) != parsed:
            disagree_pair.append(mid)
        print(f"   {mark} {mid:<28} {str(has_tag):<12} {str(parsed):<18} "
              f"{str(fb.get(mid)):<12} {str(measured):<12}")
    print(f"   实测能吃图而我方判 False 的：{disagree_parse}")
    print(f"   兜底表与远端解析**分叉**的：{disagree_pair}")

    # 事实 1：tags 判据把两个实测能看图的模型判成不支持
    assert "sn-deepseek-v4-1-flash" in disagree_parse, \
        f"形状没复现：{disagree_parse}"
    assert "sn-glm-5-3-flash" in disagree_parse, f"形状没复现：{disagree_parse}"
    # 事实 2：**两源今天互相一致**——所以"双真相源一致性锁"抓不到这个缺陷
    assert not disagree_pair, (
        f"兜底表与解析腿已分叉（那正是插件锁的形状）：{disagree_pair}")
    # 事实 3：解析腿产的是**硬 bool**，永远不给"不知道"（None）⇒ 三态在这条腿上被压平
    assert all(isinstance(r[2], bool) for r in rows), [r[2] for r in rows]


def test_b2_existing_test_locks_the_defective_value():
    """⑧ 我方既有测试**正向钉着**这个被证伪的值（= 插件 AGENTS 里那句
    「本条曾经锁死了缺陷行为」在我方的当下版本）。"""
    p = TESTS / "accounts" / "test_raccoon.py"
    text = p.read_text(encoding="utf-8").splitlines()
    hits = [(i + 1, ln.strip()) for i, ln in enumerate(text)
            if "image_input" in ln and "False" in ln]
    print("\n[L9-②] 既有测试里把 image_input 判成 False 的断言：")
    for ln, src in hits:
        print(f"   {p.relative_to(REPO).as_posix()}:{ln}  {src}")
    assert hits, "普查失效：test_raccoon.py 里没有这类断言（形状变了？）"
    # 同一条断言的上下文：sn-glm-5-3-flash 的 tags 里**没有** vision
    block = "\n".join(text[650:680])
    assert "sn-glm-5-3-flash" in block and "vision" not in block.split("sn-glm-5-3-flash")[1][:200], \
        "该断言的上下文与预期不符（请重读）"


def test_b6_builtin_catalog_default_false_is_emitted_as_fact():
    """⑬ 内置目录侧：`EnumEntry.image_input` 是**非空 bool、默认 False**
    （`enums/matcher.py:30`），而它被直接并进对外承诺
    （`core/capabilities.py:91` → `supportsImages`）⇒ "没取证" 与 "厂商明说不支持" 印成同一个字。

    本条不判对错，只把三个事实钉出来（第三条是自相矛盾，最硬）：
      ① 25 条目录项里 12 条 `image_input=False`，逐条看是「填了 False」还是「默认没写」；
      ② 同一台机器上、同一批供应商模型名，账号侧目录缓存说的是 True；
      ③ `kimi-k3` 自己带着 `only_base64_image=True`（注释原文「仅支持 base64 图片输入」）
         却 `image_input=False`。
    """
    from model_gateway.enums.matcher import BUILTIN_ENTRIES

    src = (PKG / "enums" / "matcher.py").read_text(encoding="utf-8")
    false_entries = [e.name for e in BUILTIN_ENTRIES if not e.image_input]
    # 「默认没写」= 该条 EnumEntry(...) 源码块里根本没有 image_input= 这个关键字
    untouched = [n for n in false_entries
                 if f'"{n}"' in src and "image_input" not in
                 src.split(f'"{n}"', 1)[1].split("EnumEntry(", 1)[0]]
    contradictory = [e.name for e in BUILTIN_ENTRIES if e.only_base64_image and not e.image_input]
    print("\n[L9-③ 内置目录] 25 条目录项里 image_input=False 的：", false_entries)
    print(f"   其中「源码里没写这个字段 = 吃了默认值 False」的：{untouched}")
    print(f"   同一条目自相矛盾（only_base64_image=True 却说没有图片输入）：{contradictory}")
    fld = BUILTIN_ENTRIES[0].__dataclass_fields__["image_input"]
    print(f"   字段纪律：EnumEntry.image_input 注解={fld.type} 默认={fld.default}"
          f"（对比同类的 context_window 注解=int | None 默认=None ⇒ 数值走了三态、布尔没走）")

    # 🔴 随内置目录扩容前进（Q24 15→25 → 现 36 条，2026-10-05 实测）；本条钉的是
    # 「False 是否取证过」的形状，不是具体计数 ⇒ 只要求非空且覆盖已知矛盾条目。
    assert len(BUILTIN_ENTRIES) >= 25, len(BUILTIN_ENTRIES)
    assert false_entries, "普查失效"
    assert contradictory == ["kimi-k3"], \
        f"内置目录里那条自相矛盾变了形状（已修？还是新增了别的？）：{contradictory}"


def test_b4_no_admission_consumer_of_image_input():
    """⑪ 谁**消费** `image_input`：本条普查回答「声明了不支持，网关到底会不会拦」。

    结论（实测）：生产码里 `image_input` 只有三类去处 —— 合并、对外声明、给自动映射的
    模型当事实行；**没有一处**据此拒绝/改写/剥离请求里的图片部件。
    """
    consumers: list[tuple[str, int, str]] = []
    for f in _py_files(PKG):
        text = f.read_text(encoding="utf-8")
        for i, ln in enumerate(text.splitlines(), 1):
            if "image_input" in ln and "supportsImages" not in ln:
                consumers.append((_rel(f), i, ln.strip()))
    blocking = [c for c in consumers if any(k in c[2] for k in
                ("raise", "reject", "GatewayError", "strip", "pop(", "del ", "return None"))]
    print("\n[L9-② 消费面] `image_input` 出现处（含注释，逐行由人判）：")
    for f, i, s in consumers:
        print(f"   {f}:{i}  {s[:110]}")
    print(f"   合计 {len(consumers)} 行；其中形如「据此拦/剥」的：{len(blocking)} → {blocking}")
    assert consumers, "普查失效"
    assert blocking == [], f"出现了输入模态拦截（那本案结论要改述）：{blocking}"


def test_b5_other_products_image_input_sources():
    """⑫ `image_input=` 的全部赋值处：来源逐条分类（取证 / 猜 / 不编造）。"""
    src_dir = PKG / "upstream"
    found = []
    for f in sorted(src_dir.rglob("*.py")):
        text = f.read_text(encoding="utf-8")
        for i, ln in enumerate(text.splitlines(), 1):
            if "image_input" in ln and "=" in ln and "def " not in ln:
                found.append((_rel(f), i, ln.strip()))
    print("\n[L9-① 全量] `image_input=` 赋值处（来源分类见报告正文）：")
    for f, i, s in found:
        print(f"   {f}:{i}  {s}")
    assert len(found) >= 4, found
    # 只有 raccoon 一条是"从 tags 猜"；cline 从本地兜底表、buddy 从上游显式字段、其余留 None
    guessing = [x for x in found if "VISION_TAGS" in x[2] or "tags" in x[2].lower()]
    print(f"   其中「从 tags/描述猜」的：{[(x[0], x[1]) for x in guessing]}")
    assert guessing, "普查失效：已知 raccoon 那条猜法没被扫到"


# =========================================================================
# B3（实证 ②）：图片请求打到「声明不支持图片」的账号资源 ⇒ 实际发生了什么
# =========================================================================

RC_ACCOUNT = "v3-img-a"
RC_TOKEN = "eyJhbGciOiJIUzI1NiJ9.v3raccoon"
RC_RES = "res-v3-rc"
RC_VM = "sn-deepseek-v4-1-flash"          # 目录说 image_input=False、插件实测能吃图
RC_SYS = "v3-gw-img"
RC_BASE = "https://v3-raccoon.invalid/api/web/llm/v2"


def _rc_cfg() -> dict:
    return {
        "resources": [{
            "id": RC_RES, "name": "V3 Raccoon 资源", "account": RC_ACCOUNT,
            "product": "raccoon", "account_ref": RC_ACCOUNT,
            "protocol": "openai", "base_url": RC_BASE, "api_key": "", "enabled": True,
        }],
        "models": [{"name": RC_SYS, "endpoint": "chat",
                    "resources": [{"resource": RC_RES, "model": RC_VM}]}],
        "product_models": [{"product": "raccoon", "model": RC_VM,
                            "system_model": RC_SYS, "enabled": True}],
        "gateway": {"access_tokens": [{"id": "t-user", "value": "gw-v3"}]},
    }


async def _rc_gateway(make_gateway, seen: list, monkeypatch):
    """起网关 + 把该资源的出站客户端换成 MockTransport（照抄 test_raccoon_out 的做法）。"""
    import httpx

    from model_gateway.accounts import store

    store.commit_login("raccoon", RC_ACCOUNT,
                       {"access_token": RC_TOKEN, "refresh_token": "rt",
                        "office_identity": "org-v3"}, {})

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content or b"{}")
        return httpx.Response(200, json={
            "id": "chatcmpl-v3", "object": "chat.completion", "model": body.get("model"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "看到了 478368"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 4}}, request=request)

    gw = await make_gateway(_rc_cfg())
    adapter = gw.runtime.adapters[RC_RES]
    old = adapter._client
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    await old.aclose()
    return gw


@pytest.fixture
async def _http_client():
    import httpx

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), trust_env=False) as c:
        yield c


@pytest.fixture
async def make_gateway(tmp_path):
    """本地网关工厂（临时件自持，不依赖 tests/integration/conftest.py 的 fixture 链）。

    与集成基建同一做法：写临时 config.yaml → `create_app` → uvicorn 随机端口 → 用完关停。
    """
    import asyncio
    import contextlib

    import uvicorn
    import yaml

    from model_gateway.main import create_app

    made: list = []

    class _Handle:
        def __init__(self, base_url, config_path, usage_dir, app, server, task):
            self.base_url, self.config_path = base_url, config_path
            self.usage_dir, self.app = usage_dir, app
            self._server, self._task = server, task

        @property
        def runtime(self):
            return self.app.state.runtime

        async def drain_events(self):
            await self.runtime.events.queue.join()
            await asyncio.sleep(0.02)

        def read_events(self):
            import datetime as dt
            import json
            day = dt.datetime.now().strftime("%Y%m%d")
            p = self.usage_dir / f"events-{day}.jsonl"
            if not p.exists():
                return []
            return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]

    n = 0

    async def _make(cfg_dict: dict):
        nonlocal n
        config_path = tmp_path / f"v3-config-{n}.yaml"
        usage_dir = tmp_path / f"v3-usage-{n}"
        config_path.write_text(yaml.safe_dump(cfg_dict, allow_unicode=True), encoding="utf-8")
        app = create_app(config_path=config_path, usage_dir=usage_dir,
                         enums_path=tmp_path / f"v3-enums-{n}.yaml")
        n += 1
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
        task = asyncio.get_running_loop().create_task(server.serve())
        for _ in range(500):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started, "网关启动超时"
        port = server.servers[0].sockets[0].getsockname()[1]
        gw = _Handle(f"http://127.0.0.1:{port}", config_path, usage_dir, app, server, task)
        made.append(gw)
        return gw

    yield _make
    for gw in made:
        gw._server.should_exit = True
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(gw._task, timeout=10)


async def test_b3_image_request_goes_out_while_declaring_false(make_gateway, _http_client,
                                                               monkeypatch):
    """⑩ 实证任务书 ②：目录声明「不支持图片」的账号资源，图片**照样被发出去**，
    而 `/v1/models` 对外说 `supportsImages: false`。

    观测三处：出站请求体 / 网关返回码 / `/v1/models` 的能力位。
    """
    from model_gateway.accounts import catalog_cache
    from model_gateway.accounts.types import ModelInfo

    # 号级目录缓存：这条供应商模型名的 image_input = False（就是 raccoon 解析腿对 tags 的判法）
    catalog_cache.write_cache("raccoon", [ModelInfo(
        id=RC_VM, name="DeepSeek-V4.1-Flash", context_window=1_000_000,
        max_output=100_000, image_input=False, reasoning=True,
        effort_levels=("on", "off"))], source_account=RC_ACCOUNT)

    seen: list = []
    gw = await _rc_gateway(make_gateway, seen, monkeypatch)

    listing = await _http_client.get(f"{gw.base_url}/v1/models",
                                     headers={"Authorization": "Bearer gw-v3"})
    assert listing.status_code == 200, listing.text
    entry = next((m for m in listing.json()["data"] if m["id"] == RC_SYS), None)
    print(f"\n[L9-②] /v1/models 该模型 = {json.dumps(entry, ensure_ascii=False)}")
    assert entry is not None, f"模型没被声明出去：{listing.text[:200]}"

    body = {"model": RC_SYS, "messages": [{"role": "user", "content": [
        {"type": "text", "text": "图里是几个数字？"},
        {"type": "image_url", "image_url": {"url": "https://example.invalid/a.png"}},
    ]}]}
    resp = await _http_client.post(f"{gw.base_url}/v1/chat/completions", json=body,
                                   headers={"Authorization": "Bearer gw-v3"})
    print(f"[L9-②] 带图请求 ⇒ HTTP {resp.status_code}")
    await gw.drain_events()
    ev = gw.read_events()
    print(f"[L9-②] 事件日志最后一条 = "
          f"status={ev[-1]['status'] if ev else '(无)'} "
          f"final={ev[-1].get('final_resource') if ev else ''} "
          f"error={ev[-1].get('error') if ev else ''}")

    assert seen, "一次出站都没发生（那说明网关拦了 —— 与本案判据相反，需重查）"
    sent = json.loads(seen[-1].content)
    has_image = any("image_url" in json.dumps(part) for part in sent["messages"][-1]["content"])
    print(f"[L9-②] 出站请求体里图片部件在场 = {has_image}")
    print(f"[L9-②] 出站体 messages 尾部 = "
          f"{json.dumps(sent['messages'][-1]['content'], ensure_ascii=False)[:220]}")

    assert resp.status_code == 200, resp.text
    assert has_image, "图片被网关剥掉了（那形状与插件那条缺陷更近，需在报告里改述）"
    assert entry.get("supportsImages") is False, \
        f"对外声明不是 false（三态合并的形状变了）：{entry}"
