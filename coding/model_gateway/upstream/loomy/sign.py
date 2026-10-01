"""讯飞账号（CAccount）HMAC-SHA1 签名 —— 逐字节复刻 Loomy 客户端 `electron/xfyun/sign.js`。

🗂 证据面（只读）：DSH `src/loomy-sign.ts`（1:1 搬运；该文件本身即是客户端 `sign.js` 的复刻）。

## 签名字符串（9 段，`\n` 连接；`loomy-sign.ts:92-117`）

```
{METHOD}\n{ESCAPED_PATH}\n{ESCAPED_QUERY}\n{Content-MD5}\n
{Content-Type}\n{Date}\n{Nonce}\n{SignedHeaders}\n{CanonicalizedHeaders}
```

⚠️ 后两段恒为空串（我们不发任何 `x-*` 头），故最终字符串**以两个换行结尾** —— 这是 9 元素
   `join` 的自然结果，**不要**「顺手」去掉尾随换行（去掉会让签名不匹配）。
⚠️ 认证头前缀是 **`account`**（`account {ak}:{sig}`），不是 `Bearer`。
⚠️ **body 必须只序列化一次**：签名与发送共用同一个字符串（二次序列化会改变字节 → 签名失效，
   `loomy-oauth.ts:76-92`）。本模块只收**已序列化**的 body，编排层负责只序列化一次。

本模块**全部是纯函数**（`date`/`nonce` 可注入 → 可用固定值单测，不依赖时钟）。
"""

from __future__ import annotations

import base64
import email.utils
import hashlib
import hmac
import time
import uuid
from urllib.parse import quote

from model_gateway.upstream.loomy import constants as C


def content_md5(body: str) -> str:
    """计算 `Content-MD5`（base64）。

    ⚠️ 空 body 返回**空串**而不是空串的 md5 —— 与客户端 `sign.js:13-18` / DSH
       `loomy-sign.ts:40-43` 一致。
    """
    if not body:
        return ""
    return base64.b64encode(hashlib.md5(body.encode("utf-8")).digest()).decode("ascii")


def escape_rfc3986(value: str) -> str:
    """RFC3986 转义（`loomy-sign.ts:50-57`：`encodeURIComponent` + 补转 `! ' ( ) *`）。

    `urllib.parse.quote(safe="")` 与 JS `encodeURIComponent` 的差异恰好只剩 `!'()*`
    五个字符（JS 不转、Python 转），而 DSH 又把它们补转了 → 两边结果一致，故这里直接
    用 `quote(value, safe="")`（`-_.~` 两边都保留、`/` 两边都转义）。
    """
    return quote(str(value), safe="")


def build_escaped_path(raw_path: str) -> str:
    """构建 `ESCAPED_PATH`（`loomy-sign.ts:65-69`）：补前导 `/`、剥末尾 `/`，逐段转义再拼回。"""
    clean = raw_path if raw_path.startswith("/") else f"/{raw_path}"
    if len(clean) > 1 and clean.endswith("/"):
        clean = clean[:-1]
    return "/".join(escape_rfc3986(seg) if seg else "" for seg in clean.split("/"))


def build_escaped_query_string(query_params: dict[str, str] | None) -> str:
    """构建 `ESCAPED_QUERY_STRING`（`loomy-sign.ts:77-84`）。

    `key=value` 用 `&` 连接、**不排序**（保持传入顺序），两者都转义；
    `None` 值转成空串。
    """
    if not query_params:
        return ""
    return "&".join(
        f"{escape_rfc3986(k)}={'' if v is None else escape_rfc3986(str(v))}"
        for k, v in query_params.items())


def build_signing_string(*, method: str, path: str, query_params: dict[str, str] | None = None,
                         body: str = "", content_type: str = "",
                         date: str, nonce: str) -> str:
    """构建待签名字符串（9 段；`loomy-sign.ts:92-117`）。

    `date` / `nonce` 由调用方传入（而非在此生成），使本函数**完全确定**、可用固定值单测。
    """
    # ⚠️ 后两段恒为空串（本项目不发 x-* 头）。join 后字符串以 `\n\n` 结尾（见模块头）。
    return "\n".join([
        method.upper(),
        build_escaped_path(path),
        build_escaped_query_string(query_params),
        content_md5(body),
        content_type,
        date,
        nonce,
        "",
        "",
    ])


def auth_headers(*, method: str, path: str, query_params: dict[str, str] | None = None,
                 body: str = "", content_type: str = "application/json",
                 access_key_id: str = C.ACCOUNT_ACCESS_KEY_ID,
                 access_key_secret: str = C.ACCOUNT_ACCESS_KEY_SECRET,
                 date: str = "", nonce: str = "") -> dict[str, str]:
    """生成完整的讯飞账号请求头（`loomy-sign.ts:128-148`）。

    - `Date` 用 UTC 字符串（= JS `toUTCString()`）、`Nonce` 用 UUID；两者可注入（单测用）；
    - `Content-MD5` 仅在 body 非空时带上；
    - 返回的 body 必须与签名时的 `body` 是同一个字符串（调用方保证，见模块头）。
    """
    date = date or email.utils.formatdate(time.time(), usegmt=True)
    nonce = nonce or str(uuid.uuid4())
    string_to_sign = build_signing_string(
        method=method, path=path, query_params=query_params, body=body,
        content_type=content_type, date=date, nonce=nonce)
    signature = base64.b64encode(
        hmac.new(access_key_secret.encode("utf-8"),
                 string_to_sign.encode("utf-8"), hashlib.sha1).digest()).decode("ascii")
    headers = {
        "Authorization": f"account {access_key_id}:{signature}",
        "Date": date,
        "Nonce": nonce,
        "Content-Type": content_type,
    }
    md5 = content_md5(body)
    if md5:
        headers["Content-MD5"] = md5
    return headers
