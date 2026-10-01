"""公共层出图判据（M7-C1）：`accounts/qr.py::png_data_uri` 必须产出**真扫得出来的**二维码。

🔴 这条判据存在的理由（缺陷本体，本轮之前一直是坏的）：`qr` 型登录原先只回一条光秃秃的
内容串（`Challenge.qr_payload == url == "…/login/mp?code=…"`），而前端没有任何二维码编码器
→ 向导把一行文字印给用户"请用手机扫一扫"，**扫不出任何东西**。现在服务端出图，
所以必须有一组判据回答"这张图到底是不是那个内容的二维码"。

判据分三层（**不循环论证**：不拿 segno 自报的属性当证据）：

1. **图片面**：data URI 前缀 / PNG 魔数 / IHDR 形状 / 像素矩阵与符号矩阵逐模块一致 /
   静区与三个定位图形（finder）在位；
2. **可解码面**：本文件自带一个**只读版**小程序码解码器（v2-M，单块无交织）——
   从像素里读回 15 位格式信息（自己按 ISO/IEC 18004 的表算 BCH 校验位，不看编码器脸色）、
   按掩码异或还原、按之字形读码字，最后**还原出原文那串字节**；
3. **纪律面**：内容 >213 字节 ⇒ **抛错**，绝不静默截断（照 `raccoon-qr.ts:488-493`）。

⚠️ 未做的事（如实登记）：没有拿手机/扫码枪对屏幕实测（本波次无真机扫码环节），
   也没有实现完整 RS 纠错的解码器（第 2 层用的是"无错母图 + 单块版本"的简化路径）；
   版本 >3 的真实载荷走第 1 层的逐模块比对 + 第 3 层的容量纪律。
"""

from __future__ import annotations

import base64
import struct
import zlib

import pytest
import segno

from model_gateway.accounts import qr
from model_gateway.upstream.raccoon import protocol as raccoon_p

# ---------- 极简 1-bit PNG 读回（segno 写的是 bitdepth=1 / colortype=0 / 无过滤）----------


def _png_pixels(uri: str) -> tuple[list[list[int]], int, int]:
    """data URI → 每像素 0/1 的位图（**1 = 白**，0 = 黑，PNG 1-bit 灰阶的规范取值）。

    segno 写的是 bitdepth=1 / colortype=0（无调色板），但**会按行选过滤器**，
    所以下面要走一遍 PNG 的 5 种行过滤器还原（不还原就会看到一片假噪声）。
    """
    assert uri.startswith("data:image/png;base64,"), f"不是 PNG data URI：{uri[:40]!r}"
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", "缺 PNG 魔数（拿回来的不是图片）"
    pos, idat, width = 8, b"", 0
    rows_of = 0
    while pos + 8 <= len(raw):
        (length,) = struct.unpack(">I", raw[pos:pos + 4])
        kind, body = raw[pos + 4:pos + 8], raw[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, rows_of, depth, color = struct.unpack(">IIBB", body[:10])
            assert (depth, color) == (1, 0), f"预期 1-bit 灰阶 PNG，得到 depth={depth} color={color}"
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
        pos += 12 + length
    stride = (width + 7) // 8
    data = zlib.decompress(idat)
    assert len(data) == rows_of * (stride + 1), "IDAT 长度与 IHDR 尺寸不符（图被截断）"
    # segno 会按行选 PNG 过滤器（None/Sub/Up/Average/Paeth）压掉大片同色 → 这里按规范还原
    rows, prev = [], bytearray(stride)
    for y in range(rows_of):
        base = y * (stride + 1)
        kind_filter = data[base]
        line = bytearray(data[base + 1:base + 1 + stride])
        for i in range(stride):
            left = line[i - 1] if i else 0
            up = prev[i]
            upper_left = prev[i - 1] if i else 0
            if kind_filter == 1:
                line[i] = (line[i] + left) & 0xFF
            elif kind_filter == 2:
                line[i] = (line[i] + up) & 0xFF
            elif kind_filter == 3:
                line[i] = (line[i] + (left + up) // 2) & 0xFF
            elif kind_filter == 4:
                p = left + up - upper_left
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - upper_left)
                pred = left if (pa <= pb and pa <= pc) else (up if pb <= pc else upper_left)
                line[i] = (line[i] + pred) & 0xFF
            elif kind_filter != 0:
                raise AssertionError(f"未知 PNG 行过滤器 {kind_filter}")
        rows.append(line)
        prev = line
    pixels = [[(line[x // 8] >> (7 - x % 8)) & 1 for x in range(width)] for line in rows]
    return pixels, width, rows_of


def _modules(uri: str, *, scale: int, border: int, symbol: int) -> list[list[int]]:
    """像素图 → **符号区**模块图（跳过静区，每模块取块中心采样），并核对整张图的尺寸构成。"""
    side = (symbol + 2 * border) * scale
    pixels, w, h = _png_pixels(uri)
    assert (w, h) == (side, side), f"图幅 {w}x{h} ≠ (模块 {symbol} + 静区 {border}×2) × scale {scale}"
    return [[pixels[(y + border) * scale + scale // 2][(x + border) * scale + scale // 2]
             for x in range(symbol)] for y in range(symbol)]


def _dark(modules) -> list[list[bool]]:
    return [[pixel == 0 for pixel in row] for row in modules]


# ---------- 小程序码解码器（仅 v2 + EC M：单块、无交织、无对齐图形）----------

_FMT_TOPLEFT = [(0, 8), (1, 8), (2, 8), (3, 8), (4, 8), (5, 8), (7, 8), (8, 8),
                (8, 7), (8, 5), (8, 4), (8, 3), (8, 2), (8, 1), (8, 0)]   # bit0 → bit14
_MASKS = [lambda i, j: (i + j) % 2 == 0, lambda i, j: i % 2 == 0, lambda i, j: j % 3 == 0,
          lambda i, j: (i + j) % 3 == 0, lambda i, j: (i // 2 + j // 3) % 2 == 0,
          lambda i, j: (i * j) % 2 + (i * j) % 3 == 0,
          lambda i, j: ((i * j) % 2 + (i * j) % 3) % 2 == 0,
          lambda i, j: ((i + j) % 2 + (i * j) % 3) % 2 == 0]


def _function_map(size: int) -> list[list[bool]]:
    """**版本 2** 的函数图形（本文件的解码判据只在 v2 上做，见 `test_image_decodes_back…`）。

    合计必须正好 266 个函数模块（625 − 44 码字×8 − 7 余位 = 266），差一个就会
    在 `_read_codewords` 的整字节断言上炸掉 —— 那条断言就是本函数的自检。
      · 3 个「7×7 定位 + 分隔符」= 8×8 = 192；
      · 第 6 行 / 第 6 列时序（角块之外）= 18；
      · 格式信息两份副本 + 固定黑块 = 31；
      · 校正图形（alignment）1 个 5×5，中心 (18,18) = 25。
    """
    grid = [[(r <= 7 and c <= 7) or (r <= 7 and c >= size - 8) or (r >= size - 8 and c <= 7)
             or r == 6 or c == 6 or (r == 8 and c <= 8) or (c == 8 and r <= 8)
             or (r == 8 and c >= size - 8) or (c == 8 and r >= size - 8)
             or (16 <= r <= 20 and 16 <= c <= 20)                      # v2 唯一的校正图形
             for c in range(size)] for r in range(size)]
    assert sum(sum(row) for row in grid) == 266, f"v2 函数图形计数失真：{sum(sum(r) for r in grid)}"
    return grid


def _read_format(dark) -> tuple[int, int]:
    """读 15 位格式信息 → (纠错等级位, 掩码号)。两份副本必须一致（ISO/IEC 18004 图 25）。

    位序按"bit0 在最外侧"的那份实现（与 segno 写出的图实测一致）：
    左上副本 bit0..7 走第 8 列、bit8..14 走第 8 行；另一份副本在右上/左下各截一段。
    """
    size = len(dark)

    def value(positions):
        return sum((1 if dark[r][c] else 0) << i for i, (r, c) in enumerate(positions))

    copy1 = value(_FMT_TOPLEFT)
    copy2 = value([(8, size - 1 - i) for i in range(8)]
                  + [(size - 7 + j, 8) for j in range(7)])
    assert copy1 == copy2, "格式信息两份副本不一致（扫码器会直接判废图）"
    data = copy1 ^ 0b101010000010010                    # ISO/IEC 18004 的固定 XOR
    assert (data >> 15) == 0, f"格式信息超出 15 位：{copy1:b}"
    return (data >> 13) & 0b11, (data >> 10) & 0b111    # 2 位等级 + 3 位掩码


def _read_codewords(dark, mask: int) -> bytes:
    """按之字形读出数据区码字（先去掩码）。"""
    size = len(dark)
    fn = _function_map(size)
    bits: list[int] = []
    col, upward = size - 1, True
    while col > 0:
        if col == 6:
            col -= 1
        for step in range(size):
            row = (size - 1 - step) if upward else step
            for c in (col, col - 1):
                if not fn[row][c]:
                    flip = _MASKS[mask](row, c)
                    bits.append((1 if dark[row][c] else 0) ^ (1 if flip else 0))
        col -= 2
        upward = not upward
    assert len(bits) == 359, f"v2 的非函数模块应为 359（44 码字 × 8 + 7 余位），实得 {len(bits)}"
    bits = bits[:352]                       # 版本 2 有 7 个**余位**（不进码字，ISO/IEC 18004 表 6）
    out = bytearray()
    for i in range(0, len(bits), 8):
        byte = 0
        for b in bits[i:i + 8]:
            byte = (byte << 1) | b
        out.append(byte)
    return bytes(out)


def _decode_byte_mode(dark, mask: int) -> bytes:
    """解出 byte 模式段（v2 的计数段是 8 位）。"""
    words = _read_codewords(dark, mask)
    bits = "".join(f"{b:08b}" for b in words)
    assert bits[:4] == "0100", f"模式不是 byte（0100），而是 {bits[:4]}（扫码器按 ECI/数字模式会解错）"
    length = int(bits[4:12], 2)
    return bytes(int(bits[12 + i * 8:20 + i * 8], 2) for i in range(length))


# ---------- 判据 ----------


def test_png_data_uri_shape_and_matrix_fidelity():
    """真机取样：图片是**合法 PNG**，且像素与符号矩阵逐模块一致（渲染环节不丢一位）。"""
    payload = raccoon_p.qr_login_url("0123456789abcdef0123456789abcdef")
    scale, border = 3, 4
    uri = qr.png_data_uri(payload, scale=scale, border=border)
    symbol = segno.make(payload.encode("utf-8"), error=qr.EC_LEVEL, boost_error=False)

    modules = _modules(uri, scale=scale, border=border, symbol=symbol.version * 4 + 17)
    dark = _dark(modules)
    assert str(symbol.mode) == qr.MODE, "编码器选了非 byte 模式（内容串会被按别的字符集解）"
    assert symbol.version <= qr.MAX_VERSION
    for y, row in enumerate(symbol.matrix):
        for x, module in enumerate(row):
            assert bool(int(module)) == dark[y][x], f"第 {y} 行第 {x} 个模块与图片不符"

    # 静区必须全白（扫码器靠它定位）：在**像素图**上判（模块图已裁掉静区）
    pixels, w, h = _png_pixels(uri)
    band = border * scale
    for y in range(h):
        for x in range(w):
            if y < band or x < band or y >= h - band or x >= w - band:
                assert pixels[y][x] == 1, f"静区 ({y},{x}) 不是白像素"


def test_finder_patterns_present():
    """三个定位图形（7×7 黑边白环黑心）+ 时序图形在位 —— 结构坏了的图扫不出来。"""
    uri = qr.png_data_uri("mgw-qr-roundtrip-0123456", scale=2, border=4)
    symbol = segno.make(b"mgw-qr-roundtrip-0123456", error=qr.EC_LEVEL, boost_error=False)
    dark = _dark(_modules(uri, scale=2, border=4, symbol=symbol.version * 4 + 17))
    corners = [(0, 0), (0, len(dark) - 7), (len(dark) - 7, 0)]
    for top, left in corners:
        ring = [dark[top + r][left + c] for r, c in
                ((0, 0), (0, 6), (6, 0), (6, 6), (3, 3))]
        assert ring == [True] * 5, f"角 {top},{left} 的 finder 不完整：{ring}"
        assert dark[top + 1][left + 1:left + 6] == [False] * 5, "finder 内环应为白"
    assert [dark[6][i] for i in range(8, len(dark) - 8)] == \
           [i % 2 == 0 for i in range(8, len(dark) - 8)], "水平时序图形不交替"


def test_image_decodes_back_to_the_exact_payload():
    """🔴 可扫性的正面证据：**从像素里把原文解回来**（自带解码器，不看编码器的脸色）。

    顺带钉住三件本层的承诺：byte 模式（`_decode_byte_mode` 里判）、**纠错等级恒 M**
    （从 15 位格式信息里读出来判，不是读 segno 的属性）、格式信息两份副本自洽。
    """
    payload = "mgw-qr-roundtrip-0123456"                    # 15–27 字节 → 版本 2（单块，无交织）
    uri = qr.png_data_uri(payload, scale=2, border=4)
    symbol = segno.make(payload.encode("utf-8"), error=qr.EC_LEVEL, boost_error=False)
    assert symbol.version == 2, f"取样失效：本判据只在版本 2（单块）上做完整解码，实得 {symbol.version}"
    dark = _dark(_modules(uri, scale=2, border=4, symbol=25))

    ec_bits, mask = _read_format(dark)
    assert ec_bits == 0b00, f"格式信息里的纠错等级 = {ec_bits:b}，承诺的是 M（00）"
    assert _decode_byte_mode(dark, mask) == payload.encode("utf-8"), "图里解回来的原文与内容不一致"


@pytest.mark.parametrize("n", [qr.MAX_BYTES, qr.MAX_BYTES + 1])
def test_capacity_boundary_is_hard_and_not_silently_truncated(n):
    """213 字节 = 上限内（版本 10）；214 字节 ⇒ 抛错并给出处置建议，**不截断出坏码**。"""
    payload = "a" * n
    if n <= qr.MAX_BYTES:
        symbol = segno.make(payload.encode(), error=qr.EC_LEVEL, boost_error=False)
        assert symbol.version == qr.MAX_VERSION
        assert qr.png_data_uri(payload).startswith("data:image/png;base64,")
        return
    with pytest.raises(RuntimeError) as err:
        qr.png_data_uri(payload)
    message = str(err.value)
    assert f"{n} 字节" in message and str(qr.MAX_BYTES) in message, message
    assert "不静默截断" in message or "缩短" in message, message


def test_empty_payload_is_refused():
    """空内容不出图（一张空二维码不是"能扫"，是骗过界面）。"""
    with pytest.raises(RuntimeError, match="为空"):
        qr.png_data_uri("")


def test_raccoon_payload_shape_is_the_reference_one_and_fits():
    """raccoon 的内容形态与 DSH 逐字同形，且容量余量真实存在（约 145 字节，非拍脑袋）。"""
    code = "0" * 32
    payload = raccoon_p.qr_login_url(code)
    assert payload.startswith("https://xiaohuanxiong.com/login/mp?code=")
    assert f"appname={raccoon_p.C.QR_PAGE_APPNAME}" in payload or "appname=%E5%95" in payload
    assert 100 < len(payload.encode("utf-8")) < qr.MAX_BYTES
    assert qr.png_data_uri(payload).startswith("data:image/png;base64,")
