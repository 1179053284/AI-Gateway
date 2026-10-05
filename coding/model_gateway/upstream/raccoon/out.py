"""Raccoon（商汤小浣熊）**出站适配**（tech-design v2.0 §22.3；M6-5b 接线）。

本模块是 `FamilyOpenAIOut` 的产品族实现：传输 / SSE 解析 / 错误映射全部继承
（`adapters/openai_out.py`），本类只声明**本产品取证到的差异**：

| 项 | 取值 | 取证 | 处置 |
|---|---|---|---|
| 推理路径 | `POST {apiBase}/api/web/llm/v2/chat/completions` | `raccoon-adapter.ts:6,427`；`raccoon.ts:30,63-65` | `Resource.base_url` 已含 `/api/web/llm/v2`（`accounts/registry.py` 的 raccoon 块）→ **基类缺省 `chat_path` 恰好正确**，不覆盖 |
| 鉴权 | `Authorization: Bearer <access_token>` | `raccoon-adapter.ts:417` | `auth_headers` |
| 身份头 | `X-Org-Code`（= `office_identity`，个人账号空串）+ `X-Raccoon-Language: zh` + `X-Client-Platform` | `raccoon-adapter.ts:414-421`；取值 `raccoon-product.ts:279-281`、`raccoon.ts:281` | 同上（chat 头集**独立于**业务端点的 `protocol.headers`，见下） |
| `Accept` | `text/event-stream` | `raccoon-adapter.ts:415` | 同上 |
| 响应 | 标准 OpenAI 兼容 + 标准 SSE（`chat.completion.chunk` + `data: [DONE]`，无信封） | `raccoon-adapter.ts:1-27` | 复用 `OpenAIOutAdapter` 的解析与归一化 |
| 思考档位 | **只有 `extra_body.thinking.{type}` 一个有效通道**（`enabled` / `disabled`） | `raccoon-product.ts:73-119`、`raccoon-adapter.ts:20-73` 的实测表 | `prepare_body` 做方言翻译（见下） |

🔴 **思考方言翻译（本产品最关键的体差异，逐条有实测依据）**：

| 写法 | 实测结果（`raccoon-product.ts:55-70`） |
|---|---|
| `extra_body.thinking={type:'disabled'}` | **真关闭**（reasoning_tokens 6/6、8/8 全为 0） |
| `extra_body.thinking={type:'enabled'}` | 与默认等价（思考量 218 ≈ 基线 222） |
| `reasoning_effort`（8 个枚举） | **被接受但无效果**（8 轮配对实验正负各 4 次）；`none` **不关闭**思考 |
| **顶层** `thinking`（不在 `extra_body` 内） | **被忽略**（连非法值都不报错） |
| `extra_body.enable_thinking` / 双层 `extra_body.extra_body.*` | 无效 |

网关 IR 层按统一口径注入的是**顶层** `thinking` + `reasoning_effort`（`core/ir.py:94-111`）
—— 对 Raccoon 上游两者都无效。故本适配器把它们翻译成取证有效的 `extra_body.thinking`：

- 关闭判据（**关闭优先**，两通道任一给关闭信号即关闭）= 顶层 `thinking.type == "disabled"`
  **或** `reasoning_effort ∈ {"off", "none"}`（`off` = 本产品关闭档；`none` = IR 对
  `thinking:disabled` 的配对序列化）—— 两个通道由网关 IR **同时**注入（`core/ir.py:94-111`），
  且 IR 会把 `reasoning_effort != none` 派生为 `thinking:enabled`（`:48-49`），
  故**必须**把 effort 一并读进来，否则档位 `off` 会被派生的 `thinking:enabled` 掩盖、
  关闭动作静默失效（`out.py::_thinking_type` 的红证回归用例）；
- 其余（含 `"on"` 与未登记的档位）→ `{"type": "enabled"}` —— 与 DSH 的
  `raccoonThinkingExtraBody`「未知档位一律按开启处理，宁可多思考不可静默关掉」同语义；
- **两处都未指定 → 不发该字段**（保持服务端默认 = 开启，`raccoon-product.ts:115-119`）；
- 翻译后**移除**顶层 `thinking` / `reasoning_effort`：它们对上游无效，留着只会制造
  「看起来控制生效了」的假象（DSH 自有体里也从不出现这两个字段）。

⚠️ **chat 头集不套 `protocol.headers`**（`protocol.headers` 是**业务端点**的形状：
`Accept: application/json`，并按调用方决定是否带 `X-Client-Platform` / `X-Client-Version` /
凭据里有 `device_id` 时的 `X-Client-Device-ID`，`raccoon.ts:264-293`）。DSH 的 chat 发送点
是**独立硬编码**的四个头（`raccoon-adapter.ts:414-421`，无 version、无 device id）→
本模块照抄 chat 的那一份，不混用业务端点的头形态。

⚠️ `X-Client-Platform` 取值经 `const.client_platform()` 按**本机平台**如实映射
（`desktop-windows` / `desktop-macos` / `desktop-linux`；`raccoon-product.ts:175-183`）。
DSH 把 `desktop-windows` 写死在产品配置里是因为它只发 Windows 版；本网关跑在用户自己的
机器上，猜错会被 `login/points/grant` 拒绝 —— chat 沿用同一个取值来源，不另写一份映射。

⚠️ 非流式：DSH 侧 `stream: true` 是它**只做流式**的契约（`raccoon-adapter.ts:271`），
上游是否接受 `stream:false` **未取证** → 本层原样透传网关 IR 的 `stream` 值，
不擅自改写（登记 M6-5b 待实测项，§22.11）。

⚠️ 本模块**无网络副作用**：只构造适配器；请求由 `core/scheduler` 驱动（§22.8-1）。
"""

from __future__ import annotations

from model_gateway.adapters.product_out import FamilyOpenAIOut
from model_gateway.core.errors import UpstreamError
from model_gateway.upstream.raccoon import const as C
from model_gateway.upstream.raccoon import protocol as p

#: 关闭思考的档位取值（`const.REASONING_EFFORTS` 的关闭档 `off` + 网关 IR 对
#: `thinking:disabled` 的配对序列化 `none`，`core/ir.py:108-109`）。
_EFFORT_OFF = frozenset({"off", "none"})


class RaccoonOut(FamilyOpenAIOut):
    """Raccoon 出站适配器（openai 族基类 + 本产品身份头 / 思考方言）。

    `chat_path` **不覆盖**：基类缺省 `/chat/completions` + 资源基址 `…/api/web/llm/v2`
    = 取证值 `{apiBase}/api/web/llm/v2/chat/completions`（`raccoon-adapter.ts:427`）。
    """

    # —— 子类钩子 ——

    def auth_headers(self, cred: dict, meta: dict, device: dict) -> dict:
        """身份头（§22.3 钩子；**必装**，形状 = `raccoon-adapter.ts:414-421`）。

        - 凭据缺 `access_token` → `UpstreamError`（fail closed：绝不发 `Bearer ` 空令牌）；
        - `X-Org-Code` **总是发送**（个人账号为空串，`raccoon.ts:279-280`）；
        - `meta` / `device` 本族当前不用（`device_id?` 可选，DSH 的 chat 也不发
          `X-Client-Device-ID`）——形参按契约保留。
        """
        del meta, device
        token = p.access_token_of(cred)
        if not token:
            raise UpstreamError(
                f"Raccoon 账号 {self.account_ref} 的凭据缺少 access_token（请重新登录该账号）")
        return {
            "Authorization": f"Bearer {token}",
            "X-Org-Code": p.read_str(cred, "office_identity"),
            "X-Raccoon-Language": C.LANGUAGE,
            "X-Client-Platform": C.client_platform(),
            "Accept": "text/event-stream",
        }

    def prepare_body(self, body: dict, *, vendor_model: str, cred: dict,
                     meta: dict, device: dict) -> dict:
        """体塑造：落供应商模型名 + 思考档位方言翻译（模块头 🔴 的落地）。

        除 `thinking` 方言外**不动**任何字段（采样 / 工具 / 图片由网关 IR 层与
        `FamilyOpenAIOut` 的既有路径负责）。
        """
        del cred, meta, device
        out = {**body, "model": vendor_model}
        thinking_type = _thinking_type(out)
        out.pop("thinking", None)            # 顶层 thinking 对上游无效（模块头实测表）
        out.pop("reasoning_effort", None)    # 同上：被接受但无效果
        if thinking_type is not None:
            extra = out.get("extra_body")
            extra = dict(extra) if isinstance(extra, dict) else {}
            extra["thinking"] = {"type": thinking_type}
            out["extra_body"] = extra
        return out


#: 头钩子的**显式登记**（供接线护栏核验，与 buddy 的 `_HEADER_HOOK` 同一性质）：
#: `FamilyOpenAIOut._headers` 按属性名多态调起 `self.auth_headers(...)`，
#: 纯 AST 判据看不见"子类覆盖 + 基类调起"这种间接（会误报死代码）。
_HEADER_HOOK = RaccoonOut.auth_headers

#: 体钩子的**显式登记**（同上）：`FamilyOpenAIOut._prepare_body` 按属性名多态调起
#: `self.prepare_body(...)`，覆盖点在新文件里没有 `.prepare_body` 属性访问可被 AST 看见。
_BODY_HOOK = RaccoonOut.prepare_body


def _thinking_type(body: dict) -> str | None:
    """从出站体推出 Raccoon 的 `thinking.type`：`"disabled"` / `"enabled"` / `None`。

    两个输入通道（网关 IR 会**同时**注入它们，见 `core/ir.py:94-111`）：

    - `reasoning_effort`：Raccoon 目录声明的档位就是 `on` / `off`（`const.REASONING_EFFORTS`）
      —— `off`（及 IR 对 `thinking:disabled` 的配对序列化 `none`）判关闭，其余非空值判开启
      （与 DSH `raccoonThinkingExtraBody`「未知档位按开启处理」同语义）；
    - 顶层 `thinking.type`：`disabled` 判关闭、`enabled` 判开启。

    🔴 **关闭优先**（两个通道任一给出关闭信号即关闭）：与 `core/ir.py::merge_reasoning`
    的防矛盾口径一致（显式关闭优先于其它组合）。这条不只是口径统一 —— 它是**必要**的：
    网关会把 `reasoning_effort != none` **派生**成 `thinking: enabled`（`:48-49`），
    若按"thinking 优先"读，档位 `off`（`off != none` → 派生出 enabled）会被**误判成开启**，
    用户的关闭动作静默失效（本模块测试 `..._translated_into_extra_body[over0]` 即该红证的回归）。

    两通道都未给出信号 → `None`（**不发该字段**，保持服务端默认 = 开启）。
    """
    off = False
    on = False
    effort = body.get("reasoning_effort")
    if isinstance(effort, str) and effort.strip():
        if effort.strip().lower() in _EFFORT_OFF:
            off = True
        else:
            on = True
    thinking = body.get("thinking")
    if isinstance(thinking, dict):
        kind = thinking.get("type")
        if kind == "disabled":
            off = True
        elif kind == "enabled":
            on = True
    if off:
        return "disabled"
    return "enabled" if on else None
