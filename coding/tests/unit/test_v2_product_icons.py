"""产品官方图标在册性（2026-10-03 用户指令：账号页产品图标换成官方 icon）。

钉的是三类真实踩过的坑：
① **代码要的扩展名与磁盘上的文件对不上** ⇒ 界面上是一个 20px 的破图，肉眼极易漏；
② **占位符冒充图标**（旧 `loomy.svg` = 蓝底 + 单个字母 `<text>`、旧 `zcode.png` = 187B 小方块）
   ⇒ 尺寸/形状检查把它挡在门外；
③ **孤儿资产**（改了渲染分派却忘了删旧文件）⇒ 目录里留死文件。

`ICON_SVG` 从 `accounts.js` 里**解析**而不是在本测试里重抄一份：重抄 = 测试与页面各信一套。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from model_gateway.accounts.registry import PRODUCT_IDS

STATIC = Path(__file__).resolve().parents[2] / "model_gateway" / "web" / "static"
ICON_DIR = STATIC / "img" / "products"
ACCOUNTS_JS = STATIC / "js" / "pages" / "accounts.js"

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MIN_RASTER_EDGE = 64          # 官方资产最小 128px；64 是"不许再退回 32px 占位"的底线


def _icon_svg_set() -> set[str]:
    src = ACCOUNTS_JS.read_text(encoding="utf-8")
    m = re.search(r"const ICON_SVG = new Set\(\[(.*?)\]\)", src, re.S)
    assert m, "accounts.js 里找不到 `const ICON_SVG = new Set([...])`（分派表被改名？）"
    return set(re.findall(r'"([a-z0-9_-]+)"', m.group(1)))


def _png_size(path: Path) -> tuple[int, int]:
    body = path.read_bytes()
    # PNG IHDR 的宽高就在第 16/20 字节起（大端 4 字节），不必引 PIL
    return int.from_bytes(body[16:20], "big"), int.from_bytes(body[20:24], "big")


@pytest.mark.parametrize("pid", PRODUCT_IDS)
def test_every_product_has_exactly_one_icon_matching_the_dispatch(pid: str) -> None:
    svg_ids = _icon_svg_set()
    want = ICON_DIR / f"{pid}.{'svg' if pid in svg_ids else 'png'}"
    twin = ICON_DIR / f"{pid}.{'png' if pid in svg_ids else 'svg'}"
    assert want.is_file(), f"{pid} 缺官方图标：页面要 {want.name}，磁盘上没有 ⇒ 界面是破图"
    assert not twin.is_file(), f"{pid} 同时存在 {want.name} 与 {twin.name}：分派表与资产二义，删掉不被引用的那个"


@pytest.mark.parametrize("pid", PRODUCT_IDS)
def test_icon_is_a_real_asset_not_a_placeholder(pid: str) -> None:
    svg_ids = _icon_svg_set()
    path = ICON_DIR / f"{pid}.{'svg' if pid in svg_ids else 'png'}"
    if pid in svg_ids:
        text = path.read_text(encoding="utf-8")
        assert text.lstrip().startswith("<svg"), f"{path.name} 不是 SVG"
        # 手绘占位符的形状：一个圆角矩形 + 一个字母（旧 loomy.svg 正是这个结构）
        assert not re.search(r"<text[^>]*>\s*[A-Za-z？?]\s*</text>", text), \
            f"{path.name} 是「矩形 + 单字母」的手绘占位符，不是官方图标"
        assert len(text) > 300, f"{path.name} 只有 {len(text)} 字节，不像一份真实 logo"
    else:
        body = path.read_bytes()
        assert body.startswith(PNG_MAGIC), f"{path.name} 不是 PNG"
        w, h = _png_size(path)
        assert min(w, h) >= MIN_RASTER_EDGE, f"{path.name} 只有 {w}x{h}，低于 {MIN_RASTER_EDGE}px 底线（占位图尺寸）"
        assert len(body) > 2048, f"{path.name} 只有 {len(body)} 字节，不像一份真实 logo"


def test_no_orphan_icon_files() -> None:
    known = {f"{pid}.{'svg' if pid in _icon_svg_set() else 'png'}" for pid in PRODUCT_IDS}
    extra = sorted(p.name for p in ICON_DIR.iterdir() if p.is_file() and p.name not in known)
    assert not extra, f"图标目录里有不被任何产品引用的文件（死资产）：{extra}"


def test_icon_dispatch_set_is_a_subset_of_products() -> None:
    svg_ids = _icon_svg_set()
    stray = sorted(svg_ids - set(PRODUCT_IDS))
    assert not stray, f"ICON_SVG 里出现了不在册的产品 id：{stray}"
