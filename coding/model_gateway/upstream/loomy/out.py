"""Loomy（讯飞）**出站适配**（tech-design v2.0 §22.3；M6-5b 接线）。

本模块是 `FamilyOpenAIOut` 的产品族实现：传输 / SSE 解析 / 错误映射全部继承
（`adapters/openai_out.py`），本类只声明**本产品取证到的差异**：

| 项 | 取值 | 取证 | 处置 |
|---|---|---|---|
| 推理路径 | `POST {apiBase}/api/v1/chat/completions` | `loomy-adapter.ts:483`（`${apiBase}/chat/completions`） | `Resource.base_url` 已含 `/api/v1`（`accounts/registry.py` 的 loomy 块）→ **基类缺省 `chat_path` 恰好正确**，不覆盖 |
| 鉴权 | `Authorization: Bearer <session>` **且** `token: <session>`（**两个都发**） | `loomy.ts:217-232`（`loomyChatHeaders`）；实测交叉验证：带错的那个 → HTTP 200 + `{"code":"100002","desc":"缺少 token"}` | `auth_headers` 同时给两个头 |
| `Accept` | `text/event-stream` | `loomy.ts:227` | 同挂钩子 |
| 响应 | 标准 OpenAI 兼容 + 标准 SSE（`data:` 帧 + 空 `data:` 终止帧，无信封） | `loomy.ts:22-27`、`loomy-adapter.ts:1-27` | 复用 `OpenAIOutAdapter` 的 SSE 解析与思考字段归一化 |
| 请求体 | 标准 OpenAI 体（`model` / `messages` / `stream` + 采样 / `reasoning_effort`） | `loomy-adapter.ts:454-480` | 不写 `prepare_body`（基类默认只落供应商模型名） |

**两处口径的显式登记（防误读）**：

① `token` 头**不是**替代 Bearer，而是**并存**：`/chat/completions` 只认 Bearer，
   而 `/models`、`/points/*`、`/onboarding/*` 只认小写 `token`（`api.business_headers`）。
   官方客户端在 session 模式下对 chat 也是两个都发（`loomy-adapter.ts:483-493` 引
   `llm-completion.js:149-151`）→ 本适配器照抄「两个都发」，避免上游将来改判据；
② `Bearer ` 前缀**必需**：实测无前缀同样回 `100002 缺少 token`（`loomy.ts:223`）。

⚠️ 业务失败**恒 HTTP 200 + 信封 `code != 0`**（`loomy.ts:80-104`）是**控制面**端点的口径；
推理端点是标准 OpenAI 形态（无信封）→ 走基类的 HTTP 状态码错误映射（401 → `AUTH` →
上层 `disable`；429 → `QUOTA`；5xx / 网络类 → `RETRYABLE`）。⚠️ 但若上游以
**HTTP 200 + 流内错误帧**下发业务失败，由 `core/scheduler` 的既有 error 帧识别路径兜住
（`scheduler.py:597-606`），本适配器不另造一套。

⚠️ 非流式：DSH 侧 `stream: true` 是它**只做流式**的契约（`loomy-adapter.ts:461`），
上游是否接受 `stream:false` **未取证** → 本层原样透传网关 IR 的 `stream` 值，
不擅自改写（登记 M6-5b 待实测项，§22.11）。

⚠️ 本模块**无网络副作用**：只构造适配器；请求由 `core/scheduler` 驱动（§22.8-1）。
"""

from __future__ import annotations

from model_gateway.adapters.product_out import FamilyOpenAIOut
from model_gateway.core.errors import UpstreamError
from model_gateway.upstream.loomy import api as loomy_api


class LoomyOut(FamilyOpenAIOut):
    """Loomy 出站适配器（openai 族基类 + Bearer/token 双鉴权头）。

    `chat_path` **不覆盖**：基类缺省 `/chat/completions` + 资源基址 `…/api/v1`
    = 取证值 `{apiBase}/chat/completions`（`loomy-adapter.ts:483`）。
    """

    # —— 子类钩子 ——

    def auth_headers(self, cred: dict, meta: dict, device: dict) -> dict:
        """身份头（§22.3 钩子；**必装**）。

        - 凭据缺 `access_token`（讯飞 32 位 hex `session`）→ `UpstreamError`
          （fail closed：绝不发 `Bearer ` / 空 `token` 打上游）；
        - 两个头并存（见模块头 ①/②）；`Content-Type` 由族基类补齐；
        - `meta` / `device` 本族当前不用（无设备身份，§22.4）——形参按契约保留。
        """
        del meta, device
        token = loomy_api.access_token_of(cred)
        if not token:
            raise UpstreamError(
                f"Loomy 账号 {self.account_ref} 的凭据缺少 access_token（session）"
                "（请重新登录该账号；本产品无续期端点，过期只能重登）")
        return {
            "Authorization": f"Bearer {token}",
            "token": token,                            # ⚠️ 小写 token 头（loomy.ts:230）
            "Accept": "text/event-stream",
        }


#: 头钩子的**显式登记**（供接线护栏核验，与 buddy 的 `_HEADER_HOOK` 同一性质）：
#: `FamilyOpenAIOut._headers` 按属性名多态调起 `self.auth_headers(...)`，
#: 纯 AST 判据看不见"子类覆盖 + 基类调起"这种间接（会误报死代码）。
_HEADER_HOOK = LoomyOut.auth_headers
