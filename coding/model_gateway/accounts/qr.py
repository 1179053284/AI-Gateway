"""扫码型登录的公共层：**服务端出二维码图** + 换发上限（M7-C1，2026-10-01）。

## 为什么这一层要出图（推翻 §22.3 旧分工「本层不出图」）

旧分工是「网关只回**内容串**，前端自绘二维码」。但本网关前端**没有二维码编码器**
（`pyproject.toml` 原先零 QR 依赖、`web/static/js/` 里也没有任何绘图实现），于是 `qr` 型
向导只能把那行内容印成文字、提示用户"用手机扫一扫这条链接"——**这就是本轮修的缺陷本身**
（raccoon：`upstream/raccoon/login.py` 旧 `:60` 回 `url == qr_payload == 内容串`；
loomy：`<img src="https://open.weixin.qq.com/connect/qrcode/<uuid>">` 让浏览器跨域取图，
而那张图必须带 UA + Referer 才取得到 → 图片永远加载失败）。

取证（只读参考 `AI工作站/05-dsh插件/deepseek-harness-codearts`）：DSH 的 raccoon 登录页把
同一形态的 URL **在宿主侧**用自研零依赖编码器画成内联 SVG ——
`src/raccoon-qr.ts:476-562`：byte 模式 + 纠错等级 M + 版本 1–10，
**内容超过 213 字节直接抛错**（原文："超出容量时抛错，由调用方缩短内容，
而不是静默产出扫不出来的坏码"）。本模块把同一段职责搬进网关 Python 侧，
用 `segno`（纯 Python / 零传递依赖 / MIT / 不需 Pillow 即可写 PNG）替掉那份手写编码器。

## 与那份编码器的三处刻意一致

1. **byte 模式**：内容按 **UTF-8 字节**交给编码器，并**校验**编码器真的按 byte 模式编
   （实测 segno 会把纯大写 + 数字的内容折成 `alphanumeric` —— 模式一换，扫码器解出来的
   就不是原内容，所以这里不是"传 bytes 就完事"，而是要验一遍）；
2. **纠错等级恒 M** + **版本上限 10**：`MAX_BYTES = 213` 正是「EC=M ∧ 版本 ≤10」的
   byte 模式容量上限；
3. **过长即抛、绝不静默截断**，且文案给出**实际字节数与上限**（`raccoon-qr.ts:488-493` 同形）。

⚠️ **两处必须显式按住的 segno 默认行为**（实测 1.6.6，两条都会悄悄改掉上面的承诺）：
① `make(data, version=10)` 会拿富余容量**抬高纠错等级**（M→Q）→ 本层不钉版本，
   改为显式 `boost_error=False`，让等级恒等于 `EC_LEVEL`；这样「213 字节 ⇔ 版本 ≤10」
   这条算术才成立（等级一抬，版本跟着漂）。
② 不指定模式时按内容挑最紧凑的模式 → 出图前验 `mode == MODE`（见上第 1 条）。
   本产品与 loomy 的实际内容（小写 URL + `%` 转义）天然落在 byte 模式，这条是防线不是负担。

## 换发上限 `MAX_REISSUES`

上游说「这张码没了」（loomy 的微信 402/403、raccoon 的 `canceled`）时，**服务端就地换发一张
新码**并把新图带回给界面（`raccoon-login-page.ts:213-220`：`canceled` 时
`state.qrCode = generateQrCode()` + 把新二维码塞回页面）。DSH 的换发次数无上限（它的页面
自己会关），本层要有界，否则一张没人看的码会一直问上游要新码。判据用**既有事实**算：
会话 TTL 600s（`accounts/login.py::DEFAULT_SESSION_TTL_S`）÷ 微信二维码寿命约 120s
（`loomy-wechat.ts` 的 402 语义）≈ 5 次 → 给 2 倍余量 = **10 次**；超上限就如实回
`expired` 让用户重新发起（不无限重铸，也不假装还能扫）。
"""

from __future__ import annotations

import segno

#: 纠错等级恒 M（照 `raccoon-qr.ts:478-483`：那份编码器只实现 M，收到别的等级就抛错）。
EC_LEVEL = "M"
#: 承诺的编码模式（byte：内容按 UTF-8 原样字节进码字，与 `raccoon-qr.ts` 同形）。
MODE = "byte"
#: 版本上限（同上，`:469-475` 的说明：本用途只编一个约 145 字节的固定形态 URL）。
MAX_VERSION = 10
#: byte 模式在「EC=M ∧ 版本 ≤10」下的容量上限（字节）= `raccoon-qr.ts:490` 的那句「上限 213 字节」。
MAX_BYTES = 213
#: 一次会话内二维码**换发**上限（见模块头最后一段的算法；消费点 = loomy / raccoon 的 `login_poll`）。
MAX_REISSUES = 10

#: 一个模块画几个像素（DSH 出的是 158px 内联 SVG；这里出 PNG，4px/模块 ≈ 260px，缩放到清晰）
SCALE_PX = 4
#: 静区宽度（**模块**数）：扫码器要求四周留白，DSH 的 `renderQrSvg` 同样取 4（`:525`）。
QUIET_ZONE = 4


def png_data_uri(content: str, *, scale: int = SCALE_PX, border: int = QUIET_ZONE) -> str:
    """把二维码**内容**编成 `data:image/png;base64,…`（服务端出图，浏览器不再自己画/跨域取）。

    @raises RuntimeError 内容为空、超过 `MAX_BYTES`、需要的版本 > `MAX_VERSION`，
        或编码器没按 byte 模式编 —— 一律**抛错，不静默截断/降级**。
    """
    raw = str(content or "").encode("utf-8")
    if not raw:
        raise RuntimeError("二维码内容为空（不编空图）")
    if len(raw) > MAX_BYTES:
        raise RuntimeError(f"二维码内容过长（{len(raw)} 字节，上限 {MAX_BYTES} 字节），"
                           f"请缩短内容——本层不做静默截断")
    # `boost_error=False`：见模块头 ⚠️①——不许编码器拿富余容量抬高纠错等级。
    symbol = segno.make(raw, error=EC_LEVEL, boost_error=False)
    if symbol.version > MAX_VERSION:
        raise RuntimeError(f"二维码需要版本 {symbol.version}（上限 {MAX_VERSION}），"
                           f"请缩短内容——本层不做静默截断")
    if str(symbol.mode) != MODE:
        raise RuntimeError(f"编码器选了 {symbol.mode} 模式（本层承诺 {MODE}）——"
                           f"模式一换，扫码器解出来的就不是原内容")
    return symbol.png_data_uri(scale=scale, border=border)
