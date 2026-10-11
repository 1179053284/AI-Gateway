"""接入向导「确定接入」**唯一入口**（2026-10-11 用户报障修）。

用户原话：「我发起接入，一直显示这个。另外这个弹窗也有逻辑问题，为什么两个确认接入按钮。
好奇葩的设计」

根因不是后端：网关日志里 `login/start` 8 次、`login/poll` 30 次、**`login/commit` 0 次**
（`coding/data/gateway.log` 全量计数），账号目录也为空 —— 前端**从未发出**过确认请求。
两颗同名同处理的按钮并排出现，用户既不知道"要点"、也不知道"点哪颗"。

修法：动作归**页脚**（与本应用其它弹窗 `confirmDialog` / 映射弹窗的动作栏同构），
正文 `confirmBlockHTML` 只留**说明**。本文件把这条不变式钉住 —— 判据是**源码形状**
（`login.js` 是纯前端模块，无构建步骤；页面的真机判据在 `verify_accounts_ui_live.py`），
理由与 `test_v2_product_icons.py` 同：宁可钉住"只有一颗"，也不要下次再长出第二颗。
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "model_gateway" / "web" / "static"
LOGIN_JS = STATIC / "js" / "pages" / "accounts" / "login.js"


def _src() -> str:
    return LOGIN_JS.read_text(encoding="utf-8")


def _block(src: str, header: str) -> str:
    """取一个顶层函数/箭头函数的**源码块**（从 header 到下一个顶层声明为止）。

    `login.js` 里没有嵌套的同名声明，故"到下一个 `function `/`export function `/`const x =`
    顶格声明"这一段就是该函数的完整块 —— 够用来断言"这段里有没有按钮"，不需要真解析 AST。
    """
    start = src.index(header)
    tail = src[start + len(header):]
    # 块尾 = 下一个顶层声明**或**下一个块注释（后者是下一个函数的 docstring，不属于本函数；
    # 不切在注释前的话，相邻函数的 docstring 会被算进来，一句 `<button` 描述就能造成假红）。
    nxt = re.search(r"\n(?:export )?(?:async )?function |\nconst [A-Za-z_$][\w$]* = "
                    r"|\nexport const |\n/\*\*", tail)
    return tail[: nxt.start()] if nxt else tail


def test_confirm_button_rendered_exactly_once():
    """全文件 `data-wz="confirm"` 恰好一处 —— 两颗同名钮正是用户报障的那处。"""
    hits = re.findall(r'data-wz="confirm"', _src())
    assert len(hits) == 1, f"「确定接入」按钮出现了 {len(hits)} 处，必须恰好 1 处（唯一入口）"


def test_confirm_button_lives_in_footer_not_body():
    """唯一那颗在**页脚**（`paintFooter`）；正文块里不得有 `<button`。"""
    src = _src()
    footer = _block(src, "export function paintFooter(st)")
    assert 'data-wz="confirm"' in footer, "页脚没有「确定接入」—— 确认动作就没有入口了"

    body = _block(src, "function confirmBlockHTML(st)")
    assert "<button" not in body, "正文 `confirmBlockHTML` 又长出按钮了（唯一入口在页脚）"
    assert 'data-wz="confirm"' not in body, "正文不得再渲染第二颗「确定接入」"
    assert "form-hint" in body, "正文那块仍要保留说明文案（用户得知道为什么还要点一次）"


def test_confirm_visible_for_pending_local_callback_too():
    """页脚的确认钮要覆盖 `local_callback` 未 awaiting 的那一段。

    那一型的结果由**接收端投递**到达，服务端暂存后没有推送（`login_poll` 是显式
    `NotImplementedError`）⇒ 正文说明段恒出；确认钮既然只留页脚一处，页脚就必须在这
    一态也出 —— 否则该型的确认动作整条消失（按钮被搬走却没搬全的回归）。
    """
    footer = _block(_src(), "export function paintFooter(st)")
    m = re.search(r"else if \(([^)]*)\)", footer)
    assert m, "页脚的三态分支没解析出来（paintFooter 结构变了？）"
    cond = m.group(1)
    assert "st.awaiting" in cond and 'st.kind === "local_callback"' in cond, (
        f"页脚确认态判据应同时覆盖 awaiting 与 local_callback，实际是：{cond}")
