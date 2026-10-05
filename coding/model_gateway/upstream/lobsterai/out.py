"""LobsterAI **出站适配**（tech-design v2.0 §22.3；M6-5b 接线）。

本模块是 `FamilyOpenAIOut` 的产品族实现：传输 / SSE 解析 / 错误映射全部继承
（`adapters/openai_out.py`），本类只声明**本产品取证到的三处差异**：

| 项 | 取值 | 取证 | 处置 |
|---|---|---|---|
| 推理路径 | `/api/proxy/v1/chat/completions`（挂 `API_BASE`） | `lobsterai.ts:17,45`（`LOBSTERAI_CHAT_PATH`） | 落 `chat_path` |
| 鉴权 | `Authorization: Bearer <access_token>` | `lobsterai.ts:492-503`（只四个基础头） | 复用 `protocol.auth_headers` |
| 身份头 | `User-Agent`（`LobsterAI/0.1.0`）+ 两个 `X-LobsterAI-Client-*` | `lobsterai.ts:517-530`；取值 `lobsterai-product.ts:116-129` | 复用 `protocol.client_headers` |
| `Accept` | `text/event-stream, application/json` | `lobsterai.ts:529` | 同上（accept 形参） |
| 请求体 | **`stream` 恒为 `true`** —— 上游只支持 SSE，`stream:false` 返回 **500** | `client.go:168-195`（DSH 照抄该结论，`lobsterai-adapter.ts:996-1001`） | `prepare_body` 强制改写；非流式走**聚合**（见下） |
| `prompt_cache_key` | **不发** —— 那是腾讯后端的前缀缓存机制，本产品未实测支持 | `lobsterai-adapter.ts:20` 差异表 | 不注入该字段（工具带来时原样透传，网关不做字段级删改） |
| 图片 | DSH 侧 `inputModalities` 恒 `['text']`（本适配器不额外声明） | `lobsterai-adapter.ts:19` 差异表 | 能力位归目录（`list_models`），出站不造字段 |

⚠️ **不设** CodeBuddy 系归属头（`X-Domain` / `X-Product*` / `X-IDE-*`）：`lobsterai.ts:492-503`
明确「LobsterAI 不认那套头，带上可能让服务端按错误的客户端形态归因」。

🔴 **非流式 = SSE 聚合**（上游只接受 `stream:true`）：本类置 `stream_only = True`，
非流式请求由族基类（`adapters/product_out.py`）把 `chat_stream` 的 chunk 聚合成一条
OpenAI 形状 `chat.completion`（聚合器全包唯一一份，只搬上游出现过的字段，**不编造**）；
其余产品走基类直连非流式端点。取证：`client.go:168-195`（DSH 照抄，
`lobsterai-adapter.ts:996-1001`）。

⚠️ 本模块**无网络副作用**：只构造适配器；请求由 `core/scheduler` 驱动（§22.8-1）。
"""

from __future__ import annotations

from model_gateway.adapters.product_out import FamilyOpenAIOut
from model_gateway.core.errors import UpstreamError
from model_gateway.upstream.lobsterai import const, login, protocol


class LobsteraiOut(FamilyOpenAIOut):
    """LobsterAI 出站适配器（openai 族基类 + 本产品身份头 / 体差异）。"""

    #: 推理端点：`POST {base}/api/proxy/v1/chat/completions`（`lobsterai.ts:45`）。
    #: `Resource.base_url` = `API_BASE`（`registry.py` 的 lobsterai 块，不含路径前缀）。
    chat_path = "/api/proxy/v1/chat/completions"

    # —— 子类钩子 ——

    def auth_headers(self, cred: dict, meta: dict, device: dict) -> dict:
        """身份头（§22.3 钩子；**必装**）。

        - 凭据缺 `access_token` → `UpstreamError`（fail closed：绝不发 `Bearer ` 空令牌）；
        - `X-LobsterAI-Client-Version` 取**进程内缓存**（`login.client_version_cached`）：
          头钩子是同步函数，不能 await 网络（§22.8-1）；缓存未命中回退兜底常量
          （Go 侧长期发假值 `0.1.0` 未被拒 —— 服务端不强校验版本，`lobsterai.ts:545-550`）；
        - `meta` / `device` 本族当前不用（无设备身份；`uuid` 只参与登录标识）——形参按契约保留。
        """
        del meta, device
        if not protocol.read_str(cred, "access_token"):
            raise UpstreamError(
                f"LobsterAI 账号 {self.account_ref} 的凭据缺少 access_token（请重新登录该账号）")
        # Accept 用 chat 端点的取证值（`lobsterai.ts:529`）；Content-Type 由族基类补。
        version = login.client_version_cached()
        return protocol.client_headers(cred, version, accept="text/event-stream, application/json")

    def prepare_body(self, body: dict, *, vendor_model: str, cred: dict,
                     meta: dict, device: dict) -> dict:
        """体塑造：只落供应商模型名 + **强制 `stream:true`**（取证见模块头）。

        其余字段（采样 / 思考 / 工具）由网关 IR 层按既有口径注入，本层不重复不做删改。
        """
        del cred, meta, device
        return {**body, "model": vendor_model, "stream": True}

    #: 上游只支持 SSE（`client.go:168-195`）：非流式请求由族基类内部走流式并本地聚合
    #: （聚合器唯一一份 = `adapters/product_out.py::_aggregate`，本类不再自带实现）。
    stream_only = True


#: 头钩子的**显式登记**（供接线护栏核验，与 buddy 的 `_HEADER_HOOK` 同一性质）：
#: 纯 AST 判据看不见"子类覆盖 + 基类多态调起"，登记一行让"真的有人用"可见。
_HEADER_HOOK = LobsteraiOut.auth_headers

#: 体钩子的**显式登记**（同上）：`FamilyOpenAIOut._prepare_body` 按属性名多态调起
#: `self.prepare_body(...)`，覆盖点在新文件里没有 `.prepare_body` 属性访问可被 AST 看见。
_BODY_HOOK = LobsteraiOut.prepare_body
