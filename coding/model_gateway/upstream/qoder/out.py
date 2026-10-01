"""Qoder / Qoder（中国版）**出站适配**（tech-design v2.0 §22.3/§22.4；M6-5c 接线）。

本产品是 `custom` 协议（§22.4）——**响应**是「信封套 OpenAI SSE」，**请求**必须走
`api2.qoder.sh` 的**加密端点**（认目录 key）：

| 面 | 实现状态 | 说明 |
|---|---|---|
| 响应解包（信封） | ✅ 本波次完成 | `envelope.py`（`unwrapQoderEnvelopeStream` 的 Python 移植，纯文本处理） |
| 明文请求构造 | ✅ 本波次完成 | `ask.py`（`buildQoderInferPayload` 移植：`modelKey` / `business` / `tools` / 历史） |
| **请求加密与 COSY 签名** | 🔴 **未移植（留注入缝 + TODO）** | DSH 用客户端 WASM（`qoder-wasm.ts:599-706` 的 `QoderEncryptedInfer`）产出 `{url, headers, body}`；Python 侧没有等价物 |

## 🔴 注入缝（`SIGNER_FACTORY`）—— 为什么必须留而不是"编一个"

- 加密与签名**不是密码学破解**，而是调用客户端自带 WASM 的导出函数
  （`qoder-wasm.ts:22-26`）；把它移植到 Python 需要 wasm 运行时或本地 Node 桥，
  **本波次不具备该条件**（§22.8-1 禁止引入不明依赖；无网络）。
- 因此本模块把「明文 ask → 签名后的 `{url, headers, body}`」定义为一个**注入点**：
  生产默认 `None`（**fail closed**：请求前当场报可读错误，绝不伪造签名、绝不静默降级
  到公开端点 —— 公开端点**不认目录 key**，发过去只会回 `Unsupported model`）。
- 测试与后续波次可注入实现（M6-5c 集成测试即用假签名器验证**信封 + 明文构造**全链路）。

注入缝契约（与 DSH `prepareInfer(ask)` 同形）::

    factory(product_cfg, base_url, cred, meta) -> signer
    signer(ask_payload: dict) -> SignedRequest(url, headers, body)
    # signer 可为同步函数；返回 awaitable 时本层会 await

## 区域防串用（§22.4「两站互不串用」）

- 适配器由 `product.build_out` 显式注入**本区域的 `QoderProduct`**（qoder → `QODER`、
  qodercn → `QODER_CN`；`require_qoder_family` 取不到当场抛错）；
- 出站前再走 `flow._guard_family` 同款检查（凭据区域标记不符 → `FamilyMismatchError`，
  **不打上游**）——DSH 侧靠「按 provider 取实例」结构性保证（`jet-hub-rpc.ts:1287-1295`）。
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable

import httpx

from model_gateway.adapters.product_out import ProductAccount, ProductOutAdapter
from model_gateway.core.errors import UpstreamError
from model_gateway.upstream.qoder import ask as ask_mod
from model_gateway.upstream.qoder import envelope
from model_gateway.upstream.qoder.config import QoderProduct, model_of


@dataclass(frozen=True)
class SignedRequest:
    """签名器产物（与 DSH `QoderInferRequest` 同形：url / headers / body）。"""

    url: str
    headers: dict
    body: str


#: 签名器类型（同步或异步；见模块头注入缝契约）。
Signer = Callable[[dict], "SignedRequest | Awaitable[SignedRequest]"]
#: 签名器工厂（`product_cfg, base_url, cred, meta` → signer）；生产默认 None = 未接线。
SIGNER_FACTORY: Callable[..., Signer] | None = None

#: 未接线时的**可操作**失败文案（不伪装成上游错误、不静默降级）。
NOT_WIRED_HINT = (
    "qoder 出站需要 WASM 加密与 COSY 签名（DSH qoder-wasm.ts:599-706），"
    "本网关尚未移植该通道（SIGNER_FACTORY 未注入）→ 本资源当前不可用；"
    "请在「接入模型资源」页暂时停用该资源，或等待后续波次接线（见 M6-5c 报告）")


class QoderOut(ProductOutAdapter):
    """Qoder 系出站适配器（custom 协议；§22.3 三方法 + `aclose`）。"""

    def __init__(self, account: ProductAccount, product_cfg: QoderProduct, *,
                 signer: Signer | None = None, client: httpx.AsyncClient | None = None,
                 timeout: float = 60.0) -> None:
        super().__init__(account, protocol="custom")
        self._cfg = product_cfg
        #: 本适配器的区域身份（两站互不串用；`build_out` 显式注入，见模块头）
        self.region = product_cfg.id
        self._signer = signer
        if client is not None:
            self._client = client
        else:
            from model_gateway.adapters.openai_out import _is_local_target
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout), trust_env=not _is_local_target(self.base_url))

    async def aclose(self) -> None:
        await self._client.aclose()

    # —— 凭据 / 区域 ——

    def _check_family(self, cred: dict) -> None:
        """区域防串用（`flow._guard_family` 同一份判据）：不一致 → `UpstreamError`。

        🔴 换成 `UpstreamError` 是**必须**的（不是美化）：调度器只认 `UpstreamError`
        （`scheduler` 的捕获面），裸 `FamilyMismatchError` 会漏成 500。
        `no_failover=True`：这是「资源接错账号」的配置问题，切换其它资源无帮助。
        """
        from model_gateway.upstream.qoder.config import FamilyMismatchError

        try:
            _family_guard()(self._cfg, cred)
        except FamilyMismatchError as e:
            raise UpstreamError(str(e), no_failover=True) from e

    def _require_signer(self, cred: dict, meta: dict) -> Signer:
        signer = self._signer
        if signer is None and SIGNER_FACTORY is not None:
            signer = SIGNER_FACTORY(self._cfg, self.base_url, cred, meta)
        if signer is None:
            raise UpstreamError(NOT_WIRED_HINT, no_failover=True)
        return signer

    # —— 请求 ——

    async def _send_once(self, vendor_model: str, body: dict, timeout: float) -> httpx.Response:
        cred, meta, _device = self.resolve_context()
        self._check_family(cred)                  # 串用 → 可读失败（不打上游）
        signer = self._require_signer(cred, meta)
        model = model_of(self._cfg, vendor_model)
        payload = ask_mod.build_infer_payload(
            body, vendor_model,
            is_reasoning=model.supports_thinking if model is not None else False,
            is_vl=model.supports_image if model is not None else True,
            display_name=model.name if model is not None else "",
            max_input_tokens=model.context_window if model is not None else None)
        signed = signer(payload)
        if inspect.isawaitable(signed):
            signed = await signed
        if not isinstance(signed, SignedRequest):
            signed = SignedRequest(**dict(signed))     # 宽容：dict 形态也可（测试便利）
        try:
            return await self._client.post(
                signed.url, headers=dict(signed.headers),
                content=signed.body, timeout=timeout)
        except httpx.TimeoutException as e:
            raise UpstreamError(f"timeout: {e}") from e
        except httpx.HTTPError as e:
            raise UpstreamError(f"network: {type(e).__name__}: {e}") from e

    @staticmethod
    def _raise_for_status(status: int, text: str) -> None:
        """非 200 → 分类抛错（403 的三种语义分开，`qoder-adapter.ts:743-749`）。

        - 排队（`10605`，或带排队字段）与额度（`110`）→ `envelope.business_error`
          （`code` 保真；排队 = 可重试、额度 = QUOTA）；
        - 其余（含 `105` 签名/认证失败）→ 原状态码抛出（交既有分类器 → AUTH 等）。
        """
        if status in (401, 403):
            err = _try_business_error(text)
            if err is not None:
                raise err
        raise UpstreamError(f"upstream {status}", status_code=status, error_body=text)

    # —— 流式（信封 SSE → OpenAI chunk）——

    async def chat_stream(self, key: str, vendor_model: str, body: dict,
                          timeout: float) -> AsyncIterator[dict]:
        del key  # 凭据从账号目录自解（§22.3；配置里的空 Key 不使用）
        resp = await self._send_once(vendor_model, body, timeout)
        if resp.status_code != 200:
            self._raise_for_status(resp.status_code, resp.text)
        # 信封解包在流式路径上逐帧进行（不缓冲整条流）
        async for chunk in envelope.iter_chunks(resp.aiter_lines()):
            yield chunk

    # —— 非流式（本地聚合信封流）——

    async def chat_nonstream(self, key: str, vendor_model: str, body: dict,
                             timeout: float) -> dict:
        del key
        text: list[str] = []
        reasoning: list[str] = []
        tool_calls: dict[int, dict] = {}
        usage: dict | None = None
        finish: str | None = None
        async for chunk in self.chat_stream("", vendor_model, body, timeout):
            choices = chunk.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                choice = choices[0]
                delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
                if isinstance(delta.get("content"), str):
                    text.append(delta["content"])
                if isinstance(delta.get("reasoning_content"), str):
                    reasoning.append(delta["reasoning_content"])
                for call in delta.get("tool_calls") or []:
                    if not isinstance(call, dict):
                        continue
                    idx = call.get("index")
                    idx = idx if isinstance(idx, int) and not isinstance(idx, bool) else len(tool_calls)
                    slot = tool_calls.setdefault(idx, {
                        "id": "", "type": "function",
                        "function": {"name": "", "arguments": ""}})
                    if call.get("id"):
                        slot["id"] = str(call["id"])
                    fn = call.get("function") if isinstance(call.get("function"), dict) else {}
                    if fn.get("name"):
                        slot["function"]["name"] = str(fn["name"])
                    if isinstance(fn.get("arguments"), str):
                        slot["function"]["arguments"] += fn["arguments"]
                if isinstance(choice.get("finish_reason"), str):
                    finish = choice["finish_reason"]
            if isinstance(chunk.get("usage"), dict):
                usage = dict(chunk["usage"])

        message: dict[str, Any] = {"role": "assistant", "content": "".join(text)}
        if reasoning:
            message["reasoning_content"] = "".join(reasoning)
        if tool_calls:
            message["tool_calls"] = [tool_calls[k] for k in sorted(tool_calls)]
        return {
            "id": "chatcmpl-qoder",
            "object": "chat.completion",
            "created": 0,
            "model": vendor_model,     # 调度器统一替换为系统模型名（scheduler §5.1）
            "choices": [{"index": 0, "message": message,
                         "finish_reason": finish or "stop"}],
            "usage": usage or {},
        }


def _try_business_error(text: str) -> UpstreamError | None:
    """HTTP 401/403 的响应体是否是可识别的**业务错误**（排队 / 额度）。

    只认这两类（DSH 的三种 403 语义里前两种）；其余交给原状态码分类
    （如 `Signature invalid (101)` / `auth_error (105)` → AUTH）。
    """
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        parsed = None
    code = str(parsed.get("code") or "") if isinstance(parsed, dict) else ""
    if code == envelope.QUEUE_BUSINESS_CODE or code == envelope.BILLING_BUSINESS_CODE:
        return envelope.business_error(text)
    if envelope.parse_queue_info(text) is not None:
        return envelope.business_error(text)
    if envelope.looks_like_billing_error(text):
        return envelope.business_error(text)
    return None


def _family_guard():
    """取 `flow._guard_family`（**同一份**串用护栏，不复制第二份判据）。

    延迟 import：`flow.py` 模块级 import 了 `httpx`/`config`，与 `out.py` 无环，
    但延迟取用可让「只读目录/只造适配器」的场景不拉起整个 flow（构造期零副作用）。
    """
    from model_gateway.upstream.qoder.flow import _guard_family
    return _guard_family
