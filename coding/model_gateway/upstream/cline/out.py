"""Cline **出站适配**（tech-design v2.0 §22.3；M6-5b 接线）。

本模块是 `FamilyOpenAIOut` 的产品族实现：传输 / SSE 解析 / 错误映射全部继承
（`adapters/openai_out.py`），本类只声明**本产品取证到的差异**：

| 项 | 取值 | 取证 | 处置 |
|---|---|---|---|
| 推理路径 | `POST {apiBase}/api/v1/chat/completions` | `cline-product.ts:301`（`CLINE_CHAT_PATH`）；`cline-adapter.ts:7,568` 实测标准 SSE | `Resource.base_url` 已含 `/api/v1`（`accounts/registry.py` 的 cline 块）→ **基类缺省 `chat_path` 恰好正确**，不覆盖 |
| 鉴权 | `Authorization: Bearer workos:<access_token>`（**前缀不可剥**） | `cline-product.ts:96-115`；`cline.ts:159-182` | 复用 `protocol.auth_headers`（内含 `bearer_value` 幂等补齐） |
| 客户端标识头 | `HTTP-Referer` / `X-Title` / `X-IS-MULTIROOT` / `X-CLIENT-TYPE` | `cline-product.ts:269-274`（`DEFAULT_CLINE_REQUEST_HEADERS`） | 同上（`protocol.CLIENT_HEADERS`） |
| `Accept` | `text/event-stream` | `cline-adapter.ts:571-577` | `protocol.auth_headers` 的 `extra` 覆写 |
| 请求体 | 标准 OpenAI（**唯一一家推理体无自有塑形**） | `cline-product.ts:13` 的协议表 | 不写 `prepare_body`（基类默认只落厂商模型名） |

🔴 **`workos:` 前缀**（`cline.ts:159-182`，实测坑位）：前缀只在**解码 JWT** 时被剥，
凡是把存储令牌放进 `Authorization` 的请求（出站推理 / `users/me` / `balance`）**必须保留**——
剥掉即 401，且报错文案是 "make sure you're using the latest version of Cline"（与真实原因
毫不相干，会让人误判成「版本过旧」）。`protocol.bearer_value` 做幂等补齐，本模块直接复用。

**错误语义与既有分类器的对齐（逐条给依据，不另造一套）**：

- **401** → `UpstreamError(status_code=401)` → 分类器 `AUTH` → 上层 `disable`（终态、
  不重试、切下一资源）—— 与既有 `openai_out` 的错误形态**逐字一致**（`core/errors.py`
  的 HTTP 通用映射），本模块不额外包装；
- **429** → `QUOTA`（按 `access_mode` 冷却 + 短退避，§22.5-5）；**5xx / 网络类** → `RETRYABLE`；
- ⚠️ **403 不是凭据问题**（本产品特有，`cline-adapter.ts:600-640` 的真实缺陷）：地域封锁
  / 模型未开通会回 **403**（实测 `cline-free/muse-spark-1.3-contributor`：
  `403 {"error":"access forbidden: … is not available in your region","success":false}`）。
  DSH 早期把 401/403 一律当凭据过期 → 触发续期 → 仍 403 → 归 `AUTH` → 界面显示
  「API 密钥无效」，**真实原因被完全掩盖**。本网关的分类器天然把 403 归 `BAD_REQUEST`
  （不 disable、不重试、原样透传）→ 无需在适配器里加特判（`core/errors.py:120-131`）。

⚠️ 非流式：DSH 侧 `stream: true` 是它**只做流式**的契约（`cline-adapter.ts:444`），
上游是否接受 `stream:false` **未取证** → 本层原样透传网关 IR 的 `stream` 值，
不擅自改写（登记 M6-5b 待实测项，§22.11）。

⚠️ 本模块**无网络副作用**：只构造适配器；请求由 `core/scheduler` 驱动（§22.8-1）。
"""

from __future__ import annotations

from model_gateway.adapters.product_out import FamilyOpenAIOut
from model_gateway.core.errors import UpstreamError
from model_gateway.upstream.cline import protocol


class ClineOut(FamilyOpenAIOut):
    """Cline 出站适配器（openai 族基类 + `workos:` 前缀鉴权头）。

    `chat_path` **不覆盖**：基类缺省 `/chat/completions` + 资源基址 `…/api/v1`
    = 取证值 `{apiBase}/api/v1/chat/completions`（`cline-product.ts:301`）。
    """

    # —— 子类钩子 ——

    def auth_headers(self, cred: dict, meta: dict, device: dict) -> dict:
        """身份头（§22.3 钩子；**必装**）。

        - 凭据缺 `access_token` → `UpstreamError`（fail closed：绝不发 `Bearer ` 空令牌）；
        - `Accept` 用 chat 端点的取证值 `text/event-stream`（`cline-adapter.ts:571-577`）；
        - `meta` / `device` 本族当前不用（无设备身份，§22.4）——形参按契约保留。
        """
        del meta, device
        token = str((cred or {}).get("access_token") or "").strip()
        if not token:
            raise UpstreamError(
                f"Cline 账号 {self.account_ref} 的凭据缺少 access_token（请重新登录该账号）")
        return protocol.auth_headers(token, {"Accept": "text/event-stream"})


#: 头钩子的**显式登记**（供接线护栏核验，与 buddy 的 `_HEADER_HOOK` 同一性质）：
#: `FamilyOpenAIOut._headers` 按属性名多态调起 `self.auth_headers(...)`，
#: 纯 AST 判据看不见"子类覆盖 + 基类调起"这种间接（会误报死代码）。
_HEADER_HOOK = ClineOut.auth_headers
