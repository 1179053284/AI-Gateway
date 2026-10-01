"""§20 反过度设计 / 接线完整性护栏（本轮 E1 重做）。

🔔 为什么重写：上一版护栏的**符号清单是人手挑的 12 个** —— 手挑的样本结构上必然漏，
它给的是"我已经查过"的假象（第二轮验收 S-2 的原话）。本版本改为：
**从 AST 自动导出 v2.0 范围内的全部公开符号**，逐个要求"在**别的文件**里被引用"，
例外必须写进显式白名单并附理由（键 = `模块#类.方法` **全路径**，逐符号登记 —— 见
`ALLOWED_NO_REFERRER` 的头注）；白名单里出现已不存在的符号同样判失败（防白名单腐烂）。
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PKG = REPO / "model_gateway"

#: 覆盖面**由文件系统派生**（第十一轮 eng-B B11-2：这份清单是手写的，只盖到 38/56 个模块，
#: 同一个死符号种进 `core/cancel.py` 就 6 passed 一声不响，种进 `core/resources.py` 才红）。
#: 保留 `V2_MODULES` 这个名字是因为 canary 用例要往里追加模块；内容 = 包内全部 `.py`。
def _is_canary(rel: str) -> bool:
    # 接线护栏自己的自播种夹具（canary），不是产品模块 —— 必须从派生覆盖面里排除：
    # 并发跑 pytest 时**别的进程**的 canary 目录会被我的 rglob 扫到，里面的死符号
    # 于是被本进程判红（第十二轮 ix B12-8 的真实机制，比"写进真包"更隐蔽）
    return "_wiring_canary_pkg" in rel


V2_MODULES = sorted(
    p.relative_to(PKG).as_posix()
    for p in PKG.rglob("*.py")
    if "__pycache__" not in p.parts and "vendor" not in p.parts
    and not _is_canary(p.relative_to(PKG).as_posix())
)

#: 允许"全包内除定义处再无引用"的符号 + **理由**；键 = `模块#类.方法`（**全路径**）。
#:
#: 🔔 为什么键必须逐符号（本轮 guard-fix 的根因）：**豁免的粒度必须与判据的粒度一致**。
#:   旧版按**裸名**豁免、却按**逐符号**判过期，两者一旦错位就自相矛盾 ——
#:   `chat_stream` 有 5 个实现自带同文件调用点（`self.chat_stream` / `super().chat_stream`），
#:   被过期检查判成"白名单过期"；而按名删掉整条豁免，又会把**真靠豁免活着**的
#:   `TraeOut.chat_stream`（本类无任何同文件引用）反向误判成死代码。
#: 每一条形同一次技术债登记：只有"由外部机制调起"（鸭子类型多态调起 / 测试隔离缝）
#: 才能进这里，且理由里必须指得出那个外部机制；符号一旦有了包内真实引用，
#: 条目必须删除（`test_allowlist_entries_are_not_stale` 逐符号检查）。
ALLOWED_NO_REFERRER: dict[str, str] = {
    # —— 测试隔离缝（命名即声明只供测试；tests/ 调用，生产不碰）——
    # CLI 入口们**不在这里**：`cli.py` 的分发代码真实引用它们，被引用就不该占白名单位。
    "upstream/zcode/captcha.py#reset_solver_for_tests":
        "测试隔离缝（tests/unit/test_v2_claim_wiring.py:273,275 调用；生产不碰）",
    "upstream/trae/models.py#reset_channels_for_tests":
        "测试隔离缝（tests/integration/test_trae_out.py:90,109 调用；生产不碰）",
    # —— 适配器**接口方法**（§22.3 duck typing）：由 `Scheduler` 鸭子类型多态调起 ——
    # 调用点只存在于 `core/scheduler.py`（`self._adapter(r).<名字>(...)`），而 scheduler
    # 既不 import 任何适配器模块、也不写这些类名；同名方法在包内不唯一时，类方法判据
    # 要靠 import 关系 / 类名认人（`_referencing_files_named`）→ 下面这几个实现**谁都
    # 没法从源码里认出自己的调用方**，逐个登记；同名的兄弟实现自带同文件引用
    # （`self.` / `super.`），不占本表（这正是旧版按名豁免造成的假过期来源）。
    "adapters/anthropic_out.py#AnthropicOutAdapter.images_generate":
        "接口方法（scheduler.py:514 `self._adapter(r).images_generate(...)`；本模块只定义不调用）",
    "adapters/openai_out.py#OpenAIOutAdapter.images_generate":
        "接口方法（scheduler.py:514；同上）",
    "upstream/qoder/out.py#QoderOut.chat_nonstream":
        "接口方法（scheduler.py:500 `self._adapter(r).chat_nonstream(...)`；本类无同文件调用点）",
    "upstream/trae/out.py#TraeOut.chat_nonstream":
        "接口方法（scheduler.py:500；本类直接聚合 SOLO 事件，不经 self.chat_stream）",
    "upstream/trae/out.py#TraeOut.chat_stream":
        "接口方法（scheduler.py:589 `self._adapter(r).chat_stream(...)`；本类 chat_nonstream 不消费自身流，故无同文件引用）",
}

#: 上表里"鸭子类型接口方法"这一类（**按名字**列出；表内同名条目逐条核验，防白名单变垃圾桶）：
#: ① 同名方法至少在两个适配器类上定义（确实是接口而非某个类的私有能力）；
#: ② 包内确实存在 `.<name>(` 的属性调用点（真有动态调用方）。
_POLYMORPHIC_ALLOWLIST = {"chat_stream", "chat_nonstream", "images_generate"}

_ROUTES = ("get", "post", "put", "delete", "patch")


def _is_route(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """FastAPI 路由处理函数由装饰器注册，源码里没有直接调用点 —— 不算死代码。"""
    for dec in fn.decorator_list:
        text = ast.dump(dec)
        if any(f"'{r}'" in text for r in _ROUTES):
            return True
    return False


def _assigned_names(node: ast.stmt) -> list[str]:
    """这条顶层语句**绑定**了哪些名字（`A = 1` / `A = B = 1` / `A: int = 1`）。

    🔴 必须同时吃 `Assign` 与 `AnnAssign`（验收 S-20）：带类型注解的常量
    （`DEFAULT_TIMEOUT: float = 30.0`）在现代码里越来越常见，只看 `Assign`
    等于把这类常量整体排除在覆盖面外 —— 而"看着像配置入口其实零引用"的死常量
    恰恰是 S-16 那一族。多目标赋值 `A = B = 1` 两个都是公开符号。
    """
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
            and node.value is not None:          # 纯声明 `X: int` 不绑定值，不算符号
        return [node.target.id]
    return []


def _public_symbols(tree: ast.Module) -> list[tuple[str, str | None]]:
    """模块级公开符号 **+ 类里的公开方法**（元组第二项 = 所属类名，用于全路径键控）。

    🔴 为什么把方法也纳进来（验收 eng-②）：只看模块级会漏掉整类死代码 ——
    `CooldownManager.clear()` 就是那种"名字像个能力、其实没人调"的符号，
    而它比模块级函数更危险：调用它需要**同时**持有实例，看起来"迟早会有人用"。
    """
    out: list[tuple[str, str | None]] = []
    for node in tree.body:
        # 🔴 模块级 **UPPER_CASE 常量**也算公开符号（验收 S-16 / PM 中-1）：
        #    `DEFAULT_CONFIG_PATH = Path("data")/"config.yaml"` 这种"看着像配置入口、
        #    其实零引用而且随 cwd 漂移"的死常量，只看函数/方法永远抓不到。
        #    不再要求名字里含 `_`（S-20）：`TIMEOUT = 30.0` 这种单词常量同样会死，
        #    加了那条过滤等于给"下划线缺失"开一张免检条。
        for name in _assigned_names(node):
            if name.isupper() and not name.startswith("_"):
                out.append((name, None))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name.startswith("_") or _is_route(node):
                continue
            out.append((node.name, None))
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if (isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and not sub.name.startswith("_")
                            and not _is_route(sub)
                            and not _is_framework_hook(sub)):
                        out.append((sub.name, node.name))
    return out


#: 由框架/协议隐式调起的方法名（不是"我们没人调"，是"调用方在解释器/框架里"）
_FRAMEWORK_HOOKS = {"__str__", "__repr__", "__call__", "__init_subclass__",
                    "__post_init__", "model_post_init", "startup", "shutdown"}


def _is_framework_hook(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return fn.name in _FRAMEWORK_HOOKS or any(
        "property" in ast.dump(d) or "setter" in ast.dump(d) or "staticmethod" in ast.dump(d)
        or "classmethod" in ast.dump(d)
        for d in fn.decorator_list)


def _defines_class(tree: ast.Module, name: str) -> bool:
    return any(isinstance(n, ast.ClassDef) and n.name == name for n in ast.walk(tree))


def _package_symbol_names() -> dict[str, int]:
    """全包内"某个名字被几个不同符号占用"的计数（判同名歧义用）。

    🔴 不只数函数/类，也要数**模块级公开常量**（S-20）：两个模块各写一个 `TIMEOUT`
    时，光看名字谁也认不出引用的是谁 —— 与 `claim` 那类同名顶替是同一个洞，
    此前常量侧完全没参与歧义判定。
    """
    counts: dict[str, int] = {}
    for f in sorted(PKG.rglob("*.py")):
        if "__pycache__" in str(f):
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        seen: set[str] = set()
        for node in tree.body:
            for nm in _assigned_names(node):
                if nm.isupper() and not nm.startswith("_"):
                    seen.add(nm)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                seen.add(node.name)
        for n in seen:
            counts[n] = counts.get(n, 0) + 1
    return counts


#: 快照**不能**在 import 时算一次（S-20 的 canary 就是在 import 之后才把文件写进包里的：
#: 用旧快照时新种下的 `TIMEOUT` 全程"不歧义"，b.py 自家的同名常量正好把它顶替掉 → 假绿）。
#: 改成按"包里有哪些文件（路径+大小+mtime）"作签名，签名一变就重算。
_NAMES_CACHE: tuple | None = None


def _symbol_names() -> dict[str, int]:
    global _NAMES_CACHE
    sig = tuple((f, *(lambda st: (st.st_size, st.st_mtime_ns))(f.stat()))
                for f in sorted(PKG.rglob("*.py")) if "__pycache__" not in str(f))
    if _NAMES_CACHE is None or _NAMES_CACHE[0] != sig:
        _NAMES_CACHE = (sig, _package_symbol_names())
    return _NAMES_CACHE[1]


def _name_is_ambiguous(name: str) -> bool:
    """该名字在包里是否被**多处定义**（同名不同主 → 光看名字认不出是谁的引用）。"""
    return _symbol_names().get(name, 0) > 1


def _referencing_files(sym: dict) -> list[Path]:
    """按 `_population()` 的一条符号查它的真实引用点。"""
    return _referencing_files_named(sym["name"], sym["home"], cls=sym["cls"])


def _reaches_module(text: str, home: Path) -> bool:
    """该文件是否**有可能**拿到 `home` 里定义的符号：提得上类名，或从该模块/其父包 import 过。

    为什么不能只查类名：生产里大量调用是 `adapter.chat_stream(...)`、`_SOLVER.aclose()`
    这种"实例藏在变量里"的形态 —— 变量处不会写出类名。硬要求类名会误报 25 条
    （本轮试过并全部回退），改成"引用文件与本模块有 import 关系"后即可判定同名歧义。
    """
    mod = "model_gateway." + home.relative_to(PKG).with_suffix("").as_posix().replace("/", ".")
    parent = mod.rsplit(".", 1)[0]
    return (f"from {mod} import" in text or f"import {mod}" in text
            or f"from {parent} import" in text or f"from {parent} ." in text
            or f"from .{home.stem.replace('.py', '')} import" in text)


def _mentions_identifier(tree: ast.Module, ident: str) -> bool:
    """该文件是否把 `ident` 当**标识符**写过（`Name` / 定义 / 导入名 / 装饰器里的属性名）。

    与 `ident in text` 的区别正是第七轮面板指出的那条假绿：注释与字符串里的类名
    对 Python 没有任何意义，却能骗过子串匹配。
    """
    for node in ast.walk(tree):
        if (getattr(node, "id", None) == ident            # ast.Name / ast.arg
                or getattr(node, "name", None) == ident):  # ClassDef / FunctionDef
            return True
        if isinstance(node, ast.Attribute) and node.attr == ident:
            return True
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                if a.name == ident or (a.asname or "") == ident:
                    return True
    return False


def _tree(path: Path) -> ast.Module:
    """按 (大小, mtime) 缓存解析结果：本护栏对全包做几百次符号检查，
    不缓存会把每个文件解析上百遍（实测慢到不能用）。"""
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)
    cached = _TREE_CACHE.get(key)
    if cached is not None:
        return cached
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    _TREE_CACHE[key] = tree
    return tree


_TREE_CACHE: dict[tuple, ast.Module] = {}


def _dotted(path: Path) -> str:
    """`model_gateway/core/resources.py` → `model_gateway.core.resources`。"""
    parts = list(path.relative_to(REPO).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _file_package(path: Path) -> str:
    """该文件所属**包**的点分名（相对 import 的解析基准）。"""
    parts = list(path.parent.relative_to(REPO).parts)
    return ".".join(parts)


def _resolved_module(node: ast.ImportFrom, from_pkg: str) -> str:
    """把 `from .x import y` / `from ..a.b import c` 解析成点分绝对模块名。"""
    if node.level == 0:
        return node.module or ""
    parts = from_pkg.split(".") if from_pkg else []
    keep = max(len(parts) - (node.level - 1), 0)
    base = ".".join(parts[:keep])
    return f"{base}.{node.module}" if node.module else base


def _home_import_forms(tree: ast.Module, from_pkg: str,
                       home: Path, name: str) -> tuple[bool, bool]:
    """本文件从 `home` 拿东西的**两种合法形态**：`(直接导入 name, 导入了该模块)`。

    Python 里要用别模块的模块级名字只有两条路：
      ① `from <home> import name [as alias]` / `from <home> import *`
        → 文件里可以出现裸的 `name`（`Name` 节点）；
      ② `import <home> [as a]` 或 `from <home 的包> import <模块名> [as a]`
        → 只能写成 `a.name`（`Attribute` 节点）。
    🔴 光在别处出现一个**同名局部变量**（`def f(): TIMEOUT = 1; return TIMEOUT`）
    两条都不满足，绝不构成本模块常量的引用 —— 而原判据在"全包唯一名"时不加任何
    限制，正好把它当成了引用（第七轮面板的假绿之一）。
    """
    target = _dotted(home)
    parent, own = target.rsplit(".", 1)[0], target.rsplit(".", 1)[1]
    direct = via_module = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = _resolved_module(node, from_pkg)
            if mod == target and any(a.name == name or a.name == "*" for a in node.names):
                direct = True
            if mod == parent and any(a.name == own for a in node.names):
                via_module = True          # `from ..zcode import quota` 之后 `quota.X`
        elif isinstance(node, ast.Import):
            if any(a.name == target for a in node.names):
                via_module = True          # `import model_gateway.core.paths [as p]`
    return direct, via_module


def _referencing_files_named(name: str, home: Path,
                             cls: str | None = None) -> list[Path]:
    """该符号在包内的**真实引用点**（AST 级：Name / Attribute / ImportFrom / 类型注解）。

    🔴 用 AST 而不是 grep：docstring 与注释里提一嘴符号名很常见，
    字符串匹配会把"只在文档里出现过"误判成"已接线"—— 这正是前两轮被骗的形态。

    允许引用出现在自己模块内（同模块调用、当返回类型都算）：本函数要堵的是
    "定义了却谁也没用"。跨模块的**指定接线**另有
    `test_plan_named_symbols_...` 逐条钉死，两道合起来才够。
    返回**全部**命中文件（早前版本返回首个，导致期望映射只看得到一个调用方）。

    🔴 同名歧义处理（面板 eng 项 9 → S-20）：一个名字被多处定义时（`aclose` / `claim`
    这种），光有 `.name` 属性访问**不能**证明是本符号被用了 —— 那正是
    "`AccountLocks.claim` 已无人调用却报绿"的成因。此时要求引用文件与本模块
    有 import 关系或写出过类名；名字全包唯一时不加这条（否则
    `runtime.resources.pick_and_acquire()` 这种"实例藏在变量里"的调用会被误判成死代码）。

    同一条豁免原先**只作用于类方法**（`cls` 为空就直接放行）：模块级同名常量
    （两个模块各有一个 `TIMEOUT`）会互相顶替成"已接线"。常量要用别模块的必须
    import，所以按 import 关系判即可，不需要类名那一半。

    🔴 仍存的已知盲区（登记，不假装没有）：判据是"该文件与本模块**有** import 关系"，
    不是"这个访问点真的来自本模块"。于是 `from .quota import CooldownManager, get_circuit`
    的文件里，任何别处的同名 `.claim()` 也会被算作本符号的引用（假绿方向）。
    反过来"跨包间接（注册表 / getattr 字符串 / 解包 `*`）"看不见 —— 会假红，
    所以真判死之前必须人工确认，护栏只负责**把人叫过来**。
    """
    ambiguous = _name_is_ambiguous(name)
    out: list[Path] = []
    for f in sorted(PKG.rglob("*.py")):
        if "__pycache__" in str(f):
            continue
        text = f.read_text(encoding="utf-8")
        tree = _tree(f)
        direct_import = module_import = False
        if f != home:
            if cls is None:
                # 🔴 模块级常量：跨文件引用**必须**有真实 import（S-26⑥ 之一）
                direct_import, module_import = _home_import_forms(
                    tree, _file_package(f), home, name)
                if not direct_import and not module_import:
                    continue
            elif ambiguous and not _reaches_module(text, home) \
                    and not _mentions_identifier(tree, cls):
                # 🔴 类名要看 AST 里的标识符，不能拿"文件文本里出现过这个串"当证据
                #    （S-26⑥ 之二：注释/docstring 提一句 `CanaryA` 就能把同名顶替打开）
                continue
        def_lines = {n.lineno for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                     and getattr(n, "name", None) == name}
        # 🔴 常量的"定义"也是引用点之一：`FOO = 1` 里 `FOO` 是 Name 节点，
        #    不排掉的话任何模块级常量都"自引用"、永远抓不到死常量
        #    （canary 第一次跑就抓到这个洞）。`FOO: int = 1` 同理（S-20）。
        def_lines |= {n.lineno for n in ast.walk(tree)
                      if isinstance(n, (ast.Assign, ast.AnnAssign))
                      and name in _assigned_names(n)}
        for node in ast.walk(tree):
            if cls and not isinstance(node, ast.Attribute):
                continue          # 方法的引用必须是属性访问（`obj.method()` / `self.method()`）
            if (f != home and cls is None and module_import and not direct_import
                    and not isinstance(node, ast.Attribute)):
                # 只 `import` 了模块、没导入这个名字 → 裸同名是**别人家的**变量
                continue
            hit = ((isinstance(node, ast.Name) and node.id == name)
                   or (isinstance(node, ast.Attribute) and node.attr == name)
                   or (isinstance(node, ast.ImportFrom)
                       and name in [a.name for a in node.names])
                   # 注解里的类型名（`-> ResourceState` / `x: QuotaPool`）同样是引用
                   or (isinstance(node, ast.arg) and node.annotation is not None
                       and name in {n.id for n in ast.walk(node.annotation)
                                    if isinstance(n, ast.Name)}))
            if not hit:
                continue
            if f == home and getattr(node, "lineno", -1) in def_lines:
                continue                       # 定义本身不算引用
            out.append(f)
            break
    return out


def _defines(path: Path, name: str) -> bool:
    """该文件是否定义了 `name`（函数/方法/类），用于定位类方法的定义处。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and node.name == name:
            return True
    return False


def _population() -> dict[str, dict]:
    """自动导出：v2.0 范围内全部公开符号 → `{home, name, cls}`。

    🔴 键必须是 `模块#类.方法` **全路径**，不能用裸名（面板 eng 项 9）：
    裸名下"别处的同名符号"会顶替成真引用 —— `AccountLocks.claim` 这类
    已无调用方的方法当时照样报绿。
    """
    out: dict[str, dict] = {}
    for rel in V2_MODULES:
        path = PKG / rel
        assert path.exists(), f"接线护栏的模块清单过期：{rel} 不存在"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name, cls in _public_symbols(tree):
            qual = f"{cls}.{name}" if cls else name
            out.setdefault(f"{rel}#{qual}", {"home": path, "name": name, "cls": cls})
    return out


def test_every_public_symbol_has_a_referrer():
    """🔴 v2.0 全部公开符号（含类方法）必须有**跨文件**引用点，例外须进白名单并写理由
    （白名单键 = `模块#类.方法`，逐符号登记 —— 见 `ALLOWED_NO_REFERRER` 的头注）。

    判据不是"名字在文件里出现过"（那样 docstring 一提就算接线），
    而是 AST 里存在 `Name`/`Attribute`/`ImportFrom` 级别的真实引用。
    """
    pop = _population()
    assert len(pop) >= 120, f"符号全集异常偏小（护栏可能失效）：{len(pop)}"

    unwired = {k: v for k, v in pop.items()
               if not _referencing_files(v) and k not in ALLOWED_NO_REFERRER}
    # 白名单里的键也必须真实存在（防"白名单当垃圾桶"：符号改名/删除后必须同步清理）
    bogus = [k for k in ALLOWED_NO_REFERRER if k not in pop]
    assert not bogus, f"白名单里有不存在的符号（过期条目）：{bogus}"
    assert not unwired, "无生产引用的符号（死代码，§20 反过度设计）：" + "; ".join(
        sorted(unwired))


def test_allowlist_entries_are_not_stale():
    """白名单里写了但该符号实际**已有引用**的条目必须清掉（防白名单变垃圾场）。

    🔴 逐**符号**判（键 = `模块#类.方法`）：豁免是按符号登记的，过期也必须按符号判 ——
    按裸名判会把"同名的兄弟实现有引用"错算成本条目过期（旧版 5 条 chat_stream 假过期）。
    """
    stale = [k for k, v in _population().items()
             if k in ALLOWED_NO_REFERRER and _referencing_files(v)]
    assert not stale, f"白名单过期，请删除：{stale}"


def test_polymorphic_allowlist_reasons_are_verifiable():
    """🔴 "多态调起"这条豁免必须**可核验**，否则白名单就成了万能借口。

    逐条检查表内的接口方法登记（键 = 全路径）：
    ① 它必须是**类方法**（模块级符号不可能由 `Scheduler` 多态调起）；
    ② 同名方法在**两个以上**类上定义（确实是接口，不是某个类的私有能力）；
    ③ 包内真的存在 `.<name>(` 的属性调用点（有动态调用方，而不是"猜以后会有人调"）。
    """
    pop = _population()
    for key, reason in ALLOWED_NO_REFERRER.items():
        v = pop.get(key)
        assert v is not None, f"白名单条目不存在（改名/删除后未清理）：{key}（理由：{reason}）"
        name = v["name"]
        if name not in _POLYMORPHIC_ALLOWLIST:
            continue
        assert v["cls"], f"{key} 按「接口方法」登记，却是模块级符号 —— 理由不成立"
        defs = [k for k, w in pop.items() if w["name"] == name and w["cls"]]
        assert len(defs) >= 2, f"{name} 只在 {defs} 上定义 —— 不构成接口方法，请删除豁免"
        call_sites = [f.relative_to(PKG).as_posix() for f in PKG.rglob("*.py")
                      if "__pycache__" not in str(f) and f".{name}(" in f.read_text(encoding="utf-8")]
        assert call_sites, f"{name} 全包没有任何 `.{name}(` 调用点 —— 多态调起是编的"


def test_guard_catches_a_planted_dead_method(tmp_path, monkeypatch):
    """🔴 护栏自己也要能红（面板 eng 项 9 / S-20 的自证）：种下的死符号必须被报出来。

    没有这条，"护栏跑绿"可能只是因为它的判据悄悄失效了（前两轮反复出现的形态）。
    变种都要抓到，且**每个"死"旁边都放一个"活"的对照**（只测能报红，会退化成
    "把所有常量都判死"也算过）：
    ① 全包唯一名的死方法；② **与别处同名**的死方法（`claim` —— 老版本被顶替而报绿）；
    ③ 普通赋值死常量；④ **带类型注解**的赋值死常量（`X: int = 1`）；
    ⑤ **名字里没有下划线**的单词常量（`TIMEOUT`，且 b.py 用自己的同名常量也不许顶替）。
    """
    # 🔴 canary 目录**带 pid**（第十二轮 ix B12-8）：往真包里写固定名字时，
    #    四个验收面板并发跑 pytest 会互相踩（面板全量实测 `1 failed, 714 passed`，
    #    单跑却 6 绿）—— "全量绿"因此变成不可复现的口径。
    canary_name = f"_wiring_canary_pkg_{os.getpid()}"
    canary_dir = PKG / canary_name
    canary_dir.mkdir(exist_ok=True)
    try:
        (canary_dir / "__init__.py").write_text("", encoding="utf-8")
        (canary_dir / "a.py").write_text(
            "DEAD_CONSTANT_IN_CANARY = 1\n"
            "LOCAL_MASK = 7\n"                             # S-26⑥：不许被同名局部变量顶替
            "USED_CONSTANT_IN_CANARY = 2\n"
            "DEAD_ANNOTATED_CONSTANT: int = 3\n"          # S-20：带注解的赋值也要进覆盖面
            "TIMEOUT = 4\n"                               # S-20：无下划线的单词常量
            "USED_TIMEOUT: float = 5.0\n\n\n"
            "def use_const():\n    return USED_CONSTANT_IN_CANARY\n\n\n"
            "def use_timeout():\n    return USED_TIMEOUT\n\n\n"
            "class CanaryA:\n"
            "    def never_called_unique(self) -> int: return 1\n"
            "    def claim(self) -> int: return 2\n", encoding="utf-8")
        (canary_dir / "b.py").write_text(
            "TIMEOUT = 9\n\n\n"
            "class CanaryB:\n"
            "    def claim(self) -> int: return 3\n\n\n"
            "def use_it(x):\n"
            '    """顺带提一句 CanaryA，但只是 docstring 里的一句话。"""\n'
            "    return x.claim()\n\n\n"
            "def use_its_own_timeout():\n"
            "    return TIMEOUT\n", encoding="utf-8")
        # 🔴 S-26⑥：c.py 里那个**同名局部变量**不得算作 a.py#LOCAL_MASK 的引用
        (canary_dir / "c.py").write_text(
            "def shadowing_local():\n"
            "    LOCAL_MASK = 1\n"
            "    return LOCAL_MASK\n", encoding="utf-8")
        monkeypatch.setattr(sys.modules[__name__], "V2_MODULES",
            [f"{canary_name}/a.py", f"{canary_name}/b.py",
             f"{canary_name}/c.py"] + V2_MODULES)
        pop = _population()
        flagged = {k for k, v in pop.items()
                   if not _referencing_files(v) and k not in ALLOWED_NO_REFERRER}
        assert f"{canary_name}/a.py#CanaryA.never_called_unique" in flagged, flagged
        # 🔴 关键：`CanaryA.claim` 与 `CanaryB.claim` 同名，且 b.py 里真有 `.claim(` 调用 ——
        #    老护栏会把这当成 A 的引用而报绿；按全路径 + 歧义判据必须仍然抓到 A
        assert f"{canary_name}/a.py#CanaryA.claim" in flagged, \
            f"同名顶替又生效了，A.claim 未被报出：{sorted(flagged)}"
        assert f"{canary_name}/b.py#CanaryB.claim" not in flagged, "真有调用方的那个被误报了"
        # 🔴 模块级常量也在覆盖面里（S-16：`DEFAULT_CONFIG_PATH` 那类死常量的来源）
        assert f"{canary_name}/a.py#DEAD_CONSTANT_IN_CANARY" in flagged, \
            f"死常量未被报出：{sorted(flagged)}"
        assert f"{canary_name}/a.py#USED_CONSTANT_IN_CANARY" not in flagged
        # 🔴 S-20 两个新缺口都要抓到：带注解的赋值语句、**名字里没有下划线**的单词常量
        assert f"{canary_name}/a.py#DEAD_ANNOTATED_CONSTANT" in flagged, \
            f"AnnAssign 死常量未被报出（`X: int = 1` 被整体排除）：{sorted(flagged)}"
        assert f"{canary_name}/a.py#TIMEOUT" in flagged, \
            f"无下划线单词常量未被报出（被 `'_' in name` 过滤豁免，或被别家的同名常量顶替）：{sorted(flagged)}"
        # 🔴 同名不许顶替：b.py **用自己家的** TIMEOUT，a.py 那个仍然是死的
        assert f"{canary_name}/b.py#TIMEOUT" not in flagged, \
            "同模块内真被使用的常量被误报（AnnAssign/Assign 的定义行没被排掉？）"
        assert f"{canary_name}/a.py#USED_TIMEOUT" not in flagged
        # 🔴 S-26⑥ 两条假绿都要堵住：
        #   ① 别处的**同名局部变量**不算本模块常量的引用
        assert f"{canary_name}/a.py#LOCAL_MASK" in flagged, \
            f"局部变量顶替了模块级死常量：{sorted(flagged)}"
        #   ② 类名只出现在别人的 **docstring 字符串**里，不算"写出过类名"
        assert f"{canary_name}/a.py#CanaryA.claim" in flagged, \
            "docstring 里提到 CanaryA 就把 A.claim 当成已接线（子串匹配的假绿）"
    finally:
        for f in canary_dir.glob("*.py"):
            f.unlink(missing_ok=True)
        canary_dir.rmdir()
        assert not canary_dir.exists(), "canary 目录没扫干净，会污染下一次派生覆盖面"


def test_population_covers_the_modules_named_by_the_plan():
    """覆盖面自检：清单 == 磁盘上的模块全集（第十一轮 eng-B B11-2 之后由派生保证）。

    原先这条只比对"手写清单 vs 另一份手写清单"，18 个模块在面外照样绿。
    现在两头都钉：① 面里不许有磁盘上不存在的过期路径；② 磁盘上每个 `.py` 都必须入面。
    """
    on_disk = {p.relative_to(PKG).as_posix() for p in PKG.rglob("*.py")
               if "__pycache__" not in p.parts and "vendor" not in p.parts
               and not _is_canary(p.relative_to(PKG).as_posix())}
    listed = set(V2_MODULES)
    stale = sorted(r for r in listed if not (PKG / r).exists())
    missing = sorted(on_disk - listed)
    assert not stale, f"清单里有已不存在的路径：{stale}"
    assert not missing, f"这些模块不在接线护栏的覆盖面里（新增文件必须自动入面）：{missing}"
    for rel in ("upstream/zcode/captcha.py", "upstream/zcode/quota.py",
                "ops/runner.py", "core/resources.py", "core/local_admin.py",
                "adapters/anthropic_out.py", "core/cancel.py", "core/errors.py",
                "config/schemas.py", "stats/events.py"):
        assert rel in listed, f"{rel} 未纳入接线护栏"


def test_plan_named_symbols_are_wired_into_their_declared_caller():
    """上一版 `_WIRED_SYMBOLS` 的"期望接线文件"从未被断言 —— 这里补上。

    §17/§19 的接线要求是**具体到调用方**的：`apply_to_resource` 要被领取路径调、
    `settle_quota` 要被调度器调……只要求"某处引用过"挡不住接错地方。
    """
    expectations = {
        "bench_all_zcode": "ops/builtin/zcode_claim.py",
        "apply_snapshot_to_runtime": "ops/builtin/query_balance.py",
        "refresh_runtime_quotas": "main.py",                    # 启动 + tick + 管理端点
        "get_circuit": "ops/builtin/zcode_claim.py",
        "apply_to_resource": "upstream/zcode/quota.py",
        "settle_quota": "core/scheduler.py",
        "release_quota": "core/scheduler.py",
        "servable_models": "api/openai_compat.py",
        "read_account_snapshot": "api/admin.py",
        "get_solver": "ops/builtin/zcode_claim.py",
        "build_headers": "upstream/zcode/claim.py",
        "admin_post": "ops/builtin/zcode_claim.py",
        "resolve_config_path": "config/loader.py",
    }
    pop = _population()
    for name, caller in expectations.items():
        hits = [v for v in pop.values() if v["name"] == name]
        if not hits:
            # 类方法（`settle_quota` / `release_quota` 是 ResourceManager 的方法）可能
            # 不在清单模块里 —— 按"整包引用点"验，home=定义处（无定义需排除的模块级符号）
            origin = next((f for f in sorted(PKG.rglob("*.py"))
                           if _defines(f, name)), None)
            assert origin is not None, f"{name} 在包内不存在（被改名或删除？）"
            home = origin
        else:
            home = hits[0]["home"]
        # 🔴 必须带上 `cls` 再查（S-26⑥）：这些名字多数是**类方法**
        #    （`settle_quota` / `release_quota` 长在 `ResourceManager` 上），
        #    漏了 cls 就被当成模块级常量走"必须有 import"那条更严的尺 ——
        #    调度器是按 `self.runtime.resources.x()` 的鸭子类型调的，两边都没有 import。
        cls = hits[0]["cls"] if hits else None
        callers = {f.relative_to(PKG).as_posix()
                   for f in _referencing_files_named(name, home, cls=cls)}
        assert caller in callers, (
            f"{name} 未接进 {caller}，实际引用方：{sorted(callers)}")
