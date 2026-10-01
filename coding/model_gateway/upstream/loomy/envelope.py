"""Loomy 业务信封解析（**唯一**的成败判据；`loomy.ts:80-104`）。

🔴 Loomy 的业务失败**恒返回 HTTP 200**，成败只能读 body 的 `code`
   （`loomy.ts:80-85`："只看状态码会把「登录已失效」误判成成功"）。
"""

from __future__ import annotations

from dataclasses import dataclass

from model_gateway.upstream.loomy import constants as C


@dataclass(frozen=True)
class Envelope:
    """拆封结果（`ok=False` 时 `data` 恒为 None —— 失败响应里的 data 一律不采信）。"""

    ok: bool
    code: str = ""
    message: str = ""
    data: object = None


def parse(payload: object) -> Envelope:
    """解析业务信封（`loomy.ts:86-104`）。

    - 非 JSON 对象（含列表 / None / 标量）→ `ok=False`（`message` 说明原因）；
    - `message` 取值优先级：`desc`（非空）→ `message`（`loomy.ts:92-94`）；
    - `code == OK_CODE`（`000000`）才算成功；其余（含缺 code）一律失败。
    """
    if not isinstance(payload, dict):
        return Envelope(ok=False, message="响应不是 JSON 对象")
    code = payload.get("code") if isinstance(payload.get("code"), str) else ""
    desc = payload.get("desc")
    fallback = payload.get("message")
    if isinstance(desc, str) and desc:
        message = desc
    elif isinstance(fallback, str):
        message = fallback
    else:
        message = ""
    if code != C.OK_CODE:
        return Envelope(ok=False, code=code,
                        message=message or f"业务错误 {code or '(缺少 code)'}")
    return Envelope(ok=True, code=code, message=message, data=payload.get("data"))
