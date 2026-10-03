"""厂商官方图标在册性（2026-10-03 用户指令：网关模型管理页厂商名前的图标换成官方 icon）。

与 `test_v2_product_icons.py` 同一套判据，只是对象从「接入产品」换成「内置目录厂商」。
钉的是三类真实踩过的坑：
① **分派表要的扩展名与磁盘文件对不上** ⇒ 20px 的破图，肉眼极易漏；
② **占位符冒充图标**（旧形态就是厂商名首字母画在灰方块里，账号页曾有过蓝底白字「L」那种）
   ⇒ 单字母 `<text>` 的 SVG、低于最小边/最小字节的 PNG 直接判红；
③ **孤儿资产**（改了分派忘了删文件）⇒ 目录里留死文件。

🔴 双向钉：`VENDOR_ICON` 的键集合必须**等于** `BUILTIN_ENTRIES` 里实际出现的 vendor 集合。
少一边各是一种真事故——键多了是死配置，键少了界面上那一家就退回首字母（用户这次拍的正是这个）。

`VENDOR_ICON` 从 `models.js` 里**解析**而不是在本测试里重抄一份：重抄 = 测试与页面各信一套。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from model_gateway.enums.matcher import BUILTIN_ENTRIES

STATIC = Path(__file__).resolve().parents[2] / "model_gateway" / "web" / "static"
ICON_DIR = STATIC / "img" / "vendors"
MODELS_JS = STATIC / "js" / "pages" / "models.js"

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MIN_RASTER_EDGE = 64          # 官方资产最小 90~128px；64 是"不许退回 32px 占位"的底线
MIN_PNG_BYTES = 2048
SVG_KEYS: set[str] = set()    # 当前六枚全是 PNG；出现 SVG 时在这里登记


def _vendor_icon_map() -> dict[str, str]:
    src = MODELS_JS.read_text(encoding="utf-8")
    m = re.search(r"const VENDOR_ICON = \{(.*?)\n\};", src, re.S)
    assert m, "models.js 里找不到 `const VENDOR_ICON = {...}`（分派表被改名？）"
    pairs = re.findall(r'"([^"]+)"\s*:\s*"([^"]+)"', m.group(1))
    assert pairs, "VENDOR_ICON 解析出零条 ⇒ 正则与代码形状已失配，这条判据正在空转"
    return dict(pairs)


def _catalog_vendors() -> list[str]:
    seen: list[str] = []
    for e in BUILTIN_ENTRIES:
        if e.vendor and e.vendor not in seen:
            seen.append(e.vendor)
    return seen


def _png_size(path: Path) -> tuple[int, int]:
    body = path.read_bytes()
    # PNG IHDR 的宽高就在第 16/20 字节起（大端 4 字节），不必引 PIL
    return int.from_bytes(body[16:20], "big"), int.from_bytes(body[20:24], "big")


def test_dispatch_covers_exactly_the_catalog_vendors() -> None:
    got = set(_vendor_icon_map())
    want = set(_catalog_vendors())
    missing = sorted(want - got)
    dead = sorted(got - want)
    assert not missing, f"目录里有厂商没有官方图标，界面上会退回首字母：{missing}"
    assert not dead, f"VENDOR_ICON 里有目录中不存在的厂商（死配置）：{dead}"


@pytest.mark.parametrize("vendor", _catalog_vendors())
def test_every_vendor_has_one_real_asset_matching_the_dispatch(vendor: str) -> None:
    key = _vendor_icon_map()[vendor]
    ext = "svg" if key in SVG_KEYS else "png"
    want = ICON_DIR / f"{key}.{ext}"
    twin = ICON_DIR / f"{key}.{'png' if ext == 'svg' else 'svg'}"
    assert want.is_file(), f"{vendor} 缺官方图标：页面要 {want.name}，磁盘上没有 ⇒ 界面是破图"
    assert not twin.is_file(), f"{key} 同时存在 {want.name} 与 {twin.name}：分派二义，删掉不被引用的那个"


@pytest.mark.parametrize("vendor", _catalog_vendors())
def test_icon_is_a_real_asset_not_a_placeholder(vendor: str) -> None:
    key = _vendor_icon_map()[vendor]
    ext = "svg" if key in SVG_KEYS else "png"
    path = ICON_DIR / f"{key}.{ext}"
    if ext == "svg":
        text = path.read_text(encoding="utf-8")
        assert text.lstrip().startswith("<svg"), f"{path.name} 不是 SVG"
        assert not re.search(r"<text[^>]*>\s*[A-Za-z？?]\s*</text>", text), \
            f"{path.name} 是「矩形 + 单字母」的手绘占位符，不是官方图标"
        assert len(text) > 300, f"{path.name} 只有 {len(text)} 字节，不像一份真实 logo"
    else:
        body = path.read_bytes()
        assert body.startswith(PNG_MAGIC), f"{path.name} 不是 PNG"
        w, h = _png_size(path)
        assert min(w, h) >= MIN_RASTER_EDGE, \
            f"{path.name} 只有 {w}x{h}，低于 {MIN_RASTER_EDGE}px 底线（占位图尺寸）"
        assert len(body) > MIN_PNG_BYTES, \
            f"{path.name} 只有 {len(body)} 字节，不像一份真实 logo"


def test_no_orphan_icon_files() -> None:
    known = {f"{k}.{'svg' if k in SVG_KEYS else 'png'}" for k in _vendor_icon_map().values()}
    extra = sorted(p.name for p in ICON_DIR.iterdir() if p.is_file() and p.name not in known)
    assert not extra, f"厂商图标目录里有不被任何分派引用的文件（死资产）：{extra}"


def test_letter_avatar_only_survives_as_the_fallback() -> None:
    """**两处**品牌位都必须走分派出口 `vendorIconTag()`：把首字母直接写进模板 = 这次的病根回潮。
    ① 左栏厂商卡头（20px `.mark-sm`）② 详情头卡（40px `.logo-block`）——同一块品牌在同一屏里
    一处是官方图标、一处是字母，读的人不会认为这是两种设计，只会认为其中一处坏了。
    只切 `cardHTML` 一个函数体 —— 「自定义模型」那一组（在 `draw()` 里）本来就该是 `?`。"""
    src = MODELS_JS.read_text(encoding="utf-8")
    start = src.index("function cardHTML")
    tail = src.index("\nfunction ", start + 1)
    body = src[start:tail]
    assert "vendorMark(c.vendor" in body, "厂商卡头不再调用 vendorMark()，图标分派被绕过"
    assert 'class="mark-sm' not in re.sub(r"\$\{vendorMark\([^)]*\)\}", "", body), \
        "cardHTML 里出现了绕过 vendorMark() 的裸 mark-sm"
    # ② 详情头卡：`.logo-block` 的 img 位必须由分派出口供给，字母只作为 `||` 右半边兜底
    logo = [ln for ln in src.splitlines() if 'class="logo-block' in ln]
    assert len(logo) == 1, f"详情头卡的 logo 块渲染点应恰一处，实得 {len(logo)} 处：判据对象已漂移"
    assert "vendorIconTag(vendorOf(m))" in logo[0], \
        "详情头卡退回裸首字母 ⇒ 同一屏里 20px 是官方图标、40px 是字母，两种身份读成一处坏了"
    assert '"logo-block dark"' not in src, \
        "出现了无条件 `.dark` 的 logo 块：有官方图标时不该再铺品牌底色"
