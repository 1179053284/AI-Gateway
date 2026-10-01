"""模板页面（#/templates）的目录完整性机械门（2026-10-01 用户指示接入侧栏）。

用户诉求：侧栏「模板页面」入口里要能看到**所有**模板。页面清单手写在
`js/pages/templates.js` 的 TEMPLATES 数组（名称/描述/徽章等富元数据无法从文件系统
自动生成，故为手写目录）——手写清单会漂：
- 模板文件加了而清单没加 → 用户"看不到所有模板"（本门第一种红）；
- 清单列了而文件被删 → 点开是 404（本门第二种红）。
两个方向都在这里钉死；入口三件套（侧栏锚点 / PAGE_META / PAGES 挂载）同样上钉。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STATIC = REPO / "model_gateway" / "web" / "static"
PAGE_JS = STATIC / "js" / "pages" / "templates.js"
TPL_DIR = STATIC / "templates"


def _catalog_block() -> str:
    src = PAGE_JS.read_text(encoding="utf-8")
    m = re.search(r"const TEMPLATES = \[(.*?)\n\];", src, re.S)
    assert m, "templates.js 里找不到 TEMPLATES 数组（结构被改名/删除了？）"
    return m.group(1)


def test_catalog_covers_every_template_file_both_ways():
    """目录 ↔ `static/templates/*.html` 双向一致（任一方向不齐 = 用户看到/点开就缺件）。"""
    disk = sorted(p.name for p in TPL_DIR.glob("*.html"))
    assert disk, "templates/ 目录为空 —— 判据失去对象，视为失效"
    listed = sorted(re.findall(r'file:\s*"([^"]+)"', _catalog_block()))
    missing = [f for f in disk if f not in listed]
    assert not missing, f"templates/ 下的文件没进页面清单（这个入口里看不到它们）：{missing}"
    ghost = [f for f in listed if f not in disk]
    assert not ghost, f"页面清单列了不存在的文件（点开会 404）：{ghost}"
    assert len(listed) == len(set(listed)), f"清单里同一文件重复登记：{listed}"


def test_catalog_ids_unique_and_deep_linkable():
    """id = 深链 `#/templates?t=<id>` 的取值：唯一且形如 tpl-*（与需求书 §5.2 深链口径一致）。"""
    ids = re.findall(r'id:\s*"([^"]+)"', _catalog_block())
    files = re.findall(r'file:\s*"([^"]+)"', _catalog_block())
    assert len(ids) == len(files), "有条目缺 id/file 字段（条数对不上）"
    assert len(ids) == len(set(ids)), f"目录 id 重复：{ids}"
    bad = [i for i in ids if not re.fullmatch(r"tpl-[a-z0-9-]+", i)]
    assert not bad, f"id 需可深链（tpl-* 小写连字符）：{bad}"


def test_entry_wired_into_shell():
    """入口三件套：侧栏锚点（标签=模板页面）/ PAGE_META 注入 / PAGES 挂载。"""
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    main = (STATIC / "js" / "main.js").read_text(encoding="utf-8")
    assert re.search(r'<a\b[^>]*data-page="templates"[^>]*>[\s\S]*?<span>模板页面</span></a>', index), \
        "index.html 侧栏缺 data-page=templates 入口（或标签不是「模板页面」）"
    assert re.search(r'templates:\s*\{\s*title:\s*"模板页面"', main), "PAGE_META 缺 templates 注入"
    assert re.search(r"templates:\s*renderTemplates\b", main), "PAGES 未挂载 renderTemplates"


T18 = TPL_DIR / "template-model-routing.html"


def test_t18_template_static_contract():
    """T-18（模型路由预演）静态契约四查：类名有定义 / 无外链 / 主题参数约定 / 标注条+预演声明。

    类名检查是 brief §7.15 红线（禁止未在 base.css 定义的类名）的机械化版本；
    外链检查对应铁律 1（纯本地运行）；后两项对应 brief §6.0 模板公共要求。
    """
    src = T18.read_text(encoding="utf-8")
    css = (STATIC / "css" / "base.css").read_text(encoding="utf-8")
    tokens: set[str] = set()
    for m in re.finditer(r'class="([^"]+)"', src):
        tokens.update(m.group(1).split())
    assert len(tokens) >= 30, f"类名抽取疑似失效（只拿到 {len(tokens)} 个 token）"
    missing = sorted(t for t in tokens
                     if not re.search(r"\." + re.escape(t) + r"[\s{,.:\[>)]", css))
    assert not missing, f"T-18 用了 base.css 未定义的类名：{missing}"
    assert not re.search(r'(?:href|src)\s*=\s*"(?:https?:)?//', src), "T-18 出现外部链接（铁律 1）"
    assert 'URLSearchParams(location.search).get("theme")' in src, "T-18 缺 ?theme= 主题预览约定"
    assert "T-18 · 需求预演（演示数据） · 模型路由" in src, "T-18 缺标注条（brief §6.0）"
    assert "需求形态预演 · 非线上功能" in src, "T-18 缺预演声明（brief §5.2 诚实标注）"
