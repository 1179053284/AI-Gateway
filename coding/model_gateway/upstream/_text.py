"""上游产品层的**共享文本清洗**（R2a-F-4，2026-10-06 第三轮对账落地）。

为什么存在：`scope` 等上游字段实测返回多行文本，换行/控制字符会破坏落盘 JSON
（buddy `scope` 缺陷的一手复盘，`buddy.ts:243-249`）。buddy 一家长期自带剥离，
其余产品的 `read_str` 同位敞着同一形状 ⇒ 收成**一份实现**（不是 6 份抄）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx


def strip_control(value: str) -> str:
    """去掉控制字符（含 CR/LF/Tab）并把连续空白折叠为单空格（`buddy.ts:257-261`）。"""
    return " ".join(str(value).split())


def json_or_none(resp: "httpx.Response") -> object:
    """读 JSON 体；非 JSON → `None`（不因解析失败而丢掉 HTTP 事实）。

    凭据过期时网关可能回 HTML 错误页，`resp.json()` 抛出的 `Unexpected token '<'`
    对用户毫无意义（raccoon `credits.ts:285-294` 的真实缺陷复盘——R2a-F-5 收编）。
    """
    try:
        return resp.json()
    except ValueError:
        return None


def json_or_empty(resp: "httpx.Response") -> dict:
    """读 JSON 体；非 JSON / 非对象 → 空 dict（R2a-F-5 收编，cline/zcode 同口径）。"""
    body = json_or_none(resp)
    return body if isinstance(body, dict) else {}
