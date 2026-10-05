"""CodeBuddy 系（buddy / workbuddy）**出站适配**（tech-design v2.0 §22.3；M6-5a 试点）。

本模块是 `FamilyOpenAIOut` 的**产品族实现**：两个产品的差异（平台 / X-Product-Code /
UA / 兜底表）全部已在 `product.py::_PROFILE` 里参数化（`product.ts:74-156`），
所以这里只有一份实现，profile 由产品模块在 `build_out` 时注入。

🔴 **取证清单（逐条给出处置，不编造）**：

| 项 | 取值 | 取证 | 处置 |
|---|---|---|---|
| 推理路径 | `/v2/chat/completions` | `buddy-adapter.ts:1583`（`accounts/registry.py` 注释同引） | 落 `chat_path` |
| 鉴权 | `Authorization: Bearer <access_token>` | `buddy-adapter.ts:1565`（`send()` 的头块起点，`:1564-1581`） | `protocol.inference_headers` |
| 身份头 | `X-Domain` / `X-Product-Code` / `X-Agent-Purpose` / `X-IDE-Name` / `X-IDE-Type` / `X-IDE-Version` / `X-Product`(=归属名) / UA | `buddy-adapter.ts:1568-1581`；取值 `product.ts:278-279`（buddy）与 `:401-402`（workbuddy） | `protocol.inference_headers`（`X-Domain` 取**实际请求基址**主机名） |
| 响应 | OpenAI 形态 + 标准 SSE（含 `reasoning_content`） | `21 §2.5`：「buddy：OpenAI SSE（含 reasoning_content）」 | 复用 `OpenAIOutAdapter` 的 SSE 解析与思考字段归一化 |
| `X-IDE-Name/Type/Version` | `attributionName` / `attributionName` / `clientVersion`（**已取证**） | `buddy-adapter.ts:1573-1576` + `product.ts:112-120`（字段语义）、`:278-279`/`:401-402`（取值） | **发**（F3 修正：原注释写"未取证"不实；缺这组头上游「使用端」显示 `-`） |
| UA 按模型族分档 | 只取到单一 UA 形态（DSH `userAgentByModelFamily` 对 workbuddy 有分档规则，本网关未逐档取证） | `product.ts:93-99,428-433` | 发注册表 UA；登记缺口（不按模型猜分档） |
| 请求体 | `prompt_cache_key` / `reasoning_effort` / `max_tokens` 等由 DSH 组装 | 调用链图（`research/_v1-archive/01-…机制.md`；不要引 `buddy-adapter.ts:1089-1126`——那是 `resolveCallWithInfo` 的 maxTokens/reasoning 段，与出站头无关） | 网关侧由既有 IR/参数注入负责（Q24/FR-3.16）；本族 `prepare_body` 只落供应商模型名，**不加自创字段** |
| 非流式 | 通道**只收 SSE**：`stream:false` 实盘 4/4 回 `400 {"code":11101}` | :8300 真实两号（2026-10-04，`coding/data/usage/events-20261004.jsonl`）；同族 DSH 侧 `buddy/protocol.py:277` 亦只走 SSE | `stream_only = True` ⇒ 族基类内部走流式 + 本地聚合（`adapters/product_out.py`） |
| 首条 system | workbuddy 要求首条必须是 `system`：否则 `400 {"code":11128,"msg":"first message is not system prompt"}`；**buddy 同形请求为 200** | :8300 真实数据（2026-10-04：11128 三次全部来自 workbuddy 两个号，buddy 零命中） | `prepare_body` 按 `profile.system_first_text` 补齐 —— 文案只在 **workbuddy 档案**里登记（用户 2026-10-04 指定），buddy 留空 ⇒ 不给没这条限制的通道凭空注入；客户端写了 system 时**内容一字不改、只挪到首位** |

⚠️ 本模块**无网络副作用**：只构造适配器；请求由 `core/scheduler` 驱动。
"""

from __future__ import annotations

from urllib.parse import urlparse

from model_gateway.adapters.product_out import FamilyOpenAIOut, ProductAccount
from model_gateway.core.errors import UpstreamError
from model_gateway.upstream.buddy import protocol as p


class BuddyFamilyOut(FamilyOpenAIOut):
    """CodeBuddy 系出站适配器（`buddy` / `workbuddy` 共用，§22.1「零复制」）。

    传输/SSE/错误映射全部继承 `FamilyOpenAIOut` → `OpenAIOutAdapter`；本类只声明
    **两个产品差异**：推理路径与身份头（profile 注入）。
    """

    #: 推理端点：`POST {base}/v2/chat/completions`（两产品同源共用，`product.ts:14-18`）
    chat_path = "/v2/chat/completions"

    #: 上游只支持 SSE：`stream:false` 被通道回 `400 {"code":11101,"msg":"Non-stream chat
    #: request is currently not supported"}`（:8300 真实两号 4/4 命中，2026-10-04，
    #: 判据见 `adapters/product_out.py::FamilyOpenAIOut.stream_only`）。非流式请求由族基类
    #: 内部走流式并本地聚合 —— 客户端的 `stream:false` 是与**网关**的契约，不该变成
    #: 客户端可见的供应商通道错。
    stream_only = True

    def __init__(self, account: ProductAccount, profile: p.ProductProfile) -> None:
        super().__init__(account)
        self._profile = profile

    def auth_headers(self, cred: dict, meta: dict, device: dict) -> dict:
        """身份头（§22.3 钩子；**必装**）。

        - 凭据缺 `access_token` → `UpstreamError`（fail closed：绝不发 `Bearer ` 空令牌）；
        - 头集合 = `protocol.inference_headers`（**推理面**口径，逐条对 `buddy-adapter.ts:1564-1581`）：
          `X-Product` 发**归属名**（CodeBuddy/WorkBuddy），不发计费面的 `SaaS`——
          后者是 DSH 记录在案的"后台归因不到产品"的历史 bug 值（F3 修正）；
        - `X-Domain` 取**本适配器的实际请求基址**主机名（不是注册表值，也不是凭据里的
          `domain`）—— 取证：`X-Domain` 必须与请求 baseURL 一致（`credits.ts:222-228`；
          资源页允许把基址改指向别的环境，如本地假上游）；
        - `meta` / `device` 本族当前不用（无设备身份，§22.4）——形参按契约保留。
        """
        del meta, device
        if not p.access_token_of(cred):
            raise UpstreamError(
                f"{self._profile.title} 账号 {self.account_ref} 的凭据缺少 access_token"
                "（请重新登录该账号）")
        domain = urlparse(self.base_url).hostname or ""
        return p.inference_headers(self._profile, cred, domain=domain)

    def prepare_body(self, body: dict, *, vendor_model: str, cred: dict,
                     meta: dict, device: dict) -> dict:
        """体塑造：落供应商模型名 + **首条 system 补齐**（只对"有这条脾气"的通道生效）。

        - 取证（:8300 真实两号，2026-10-04）：workbuddy 对首条非 `system` 的请求回
          `400 {"code":11128,"msg":"first message is not system prompt"}`，而 buddy 的**同形
          请求**是 200 ⇒ 补齐文案只登记在 workbuddy 的档案里，没这条限制的通道一字不加；
        - 🔴 客户端**自己写了 system** 时绝不被网关的固定文案替换（那条更该生效），只是把它
          挪到首位 —— 补齐只发生在"这条请求根本没有 system 消息"时；
        - 其余字段（采样 / 思考 / 工具）仍由网关 IR 层按既有口径注入，本层不做删改。
        """
        out = super().prepare_body(body, vendor_model=vendor_model,
                                   cred=cred, meta=meta, device=device)
        return _with_system_first(out, self._profile.system_first_text)


#: 头钩子的**显式登记**（供接线护栏核验，与 `_IMPLEMENTED` 同一性质）：
#: `FamilyOpenAIOut._headers` 按属性名多态调起 `self.auth_headers(...)`，
#: 纯 AST 判据看不见"子类覆盖 + 基类调起"这种间接（会误报死代码）。
_HEADER_HOOK = BuddyFamilyOut.auth_headers

#: 体钩子的**显式登记**（同上）：`FamilyOpenAIOut._prepare_body` 按属性名多态调起
#: `self.prepare_body(...)`，跨文件 AST 判据看不见这条覆盖。
_BODY_HOOK = BuddyFamilyOut.prepare_body


def _with_system_first(body: dict, text: str) -> dict:
    """把 `messages` 整形成"首条是 system"—— 🔴 只动**位置**与**缺失补齐**，不改用户写的内容。

    四条分支（顺序即优先级）：
    1. `text` 为空 ⇒ 原样返回（该产品没有这条限制）；
    2. 首条已是 `system` ⇒ 原样返回；
    3. 有 `system` 但不在首位 ⇒ **移动**到首位，内容一字不动（通道只认位置不认语义）；
    4. 一条 `system` 都没有 ⇒ 在首位补 `text`。

    ⚠️ 只换 `messages` 这个**新列表**，不就地改调用方传进来的那份 —— IR body 还要进事件行与
    日志，被适配器改写过就让"用户实际发了什么"失去唯一真相。
    """
    if not text:
        return body
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return {**body, "messages": [{"role": "system", "content": text}]}
    first = messages[0]
    if isinstance(first, dict) and first.get("role") == "system":
        return body
    for index, item in enumerate(messages):
        if isinstance(item, dict) and item.get("role") == "system":
            moved = list(messages)
            moved.insert(0, moved.pop(index))
            return {**body, "messages": moved}
    return {**body, "messages": [{"role": "system", "content": text}, *messages]}
