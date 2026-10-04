"""Qoder / Qoder（中国版）**出站适配**（tech-design v2.0 §22.3/§22.4；M6-5c 接线）。

本产品是 `custom` 协议（§22.4）——**响应**是「信封套 OpenAI SSE」，**请求**必须走
`api2.qoder.sh` 的**加密端点**（认目录 key）：

| 面 | 实现状态 | 说明 |
|---|---|---|
| 响应解包（信封） | ✅ 本波次完成 | `envelope.py`（`unwrapQoderEnvelopeStream` 的 Python 移植，纯文本处理） |
| 明文请求构造 | ✅ 本波次完成 | `ask.py`（`buildQoderInferPayload` 移植：`modelKey` / `business` / `tools` / 历史） |
| **请求加密与 COSY 签名** | ✅ **已就位**（本机 wasm 桥，按环境变量注入） | 加密与签名在客户端自带的 `qoder-auth-wasm.wasm` 里；本仓用 `wasm_signer.py` + `qoder_bridge.mjs` 把它跑在一个 Node 子进程里，产出与 DSH `QoderEncryptedInfer.prepareInfer` 同形的 `{url, headers, body}`。**wasm 二进制不入库**，只按 `MGW_QODER_WASM_GLUE` 指向的目录在运行时读取 |

## 🔴 注入缝（`SIGNER_FACTORY`）—— 为什么必须留而不是"编一个"

- 加密与签名**不是密码学破解**，而是调用客户端自带 WASM 的导出函数
  （`qoder-wasm.ts:22-26`）；Python 侧没有 wasm 运行时，所以这条腿落在**本机 Node 子进程**
  （`wasm_signer.py` + `qoder_bridge.mjs`）：明文由本仓 `ask.py` 造，wasm 只负责加密 + 签名，
  **二进制不入库**、运行时按 `MGW_QODER_WASM_GLUE` 指向的目录读取（铁律 1；不下载、不远程更新）。
- 因此本模块把「明文 ask → 签名后的 `{url, headers, body}`」定义为一个**注入点**：
  生产默认 `None`（**fail closed**：请求前当场报可读错误，绝不伪造签名、绝不静默降级
  到公开端点 —— 公开端点**不认目录 key**，DSH 实测回 `Unsupported model`
  （`qoder-product.ts:195-199` / `:317`），且它的通用名是**另一批模型**（`:338`），
  降级过去等于换模型）。
  ⚠️ 2026-10-04 我方补一条实读（探针存档
  `docs/changes/e2e-records/E2E-20261004-qoder-quota-probe.md`）：**额度为 0 的号上，
  公开端点的额度门跑在模型校验之前** —— 39 个去重后的候选名（含目录 key、展示名规范化、
  `qwen-plus` 这类通用名）**加上空 model、缺 `messages` 的畸形体，全部回同一句
  `402 {"code":116,"error":"quota exceeded"}`，一条 `Unsupported model` 都没拿到**。
  ⇒ 该号没有额度时「哪个公开名可用」**根本无法取证**；名称表只能在有额度后一次真调用里拿。
  ⇒ 所以**公开端点腿仍未实现**（不是"没做"，是**没有可取证的名称表**）；
  而**加密端点腿已就位**（本机 wasm 桥）—— 未设 `MGW_QODER_WASM_GLUE` 时
  `SIGNER_FACTORY is None`，与接线前逐字节一致（一字节不发）。
  🔴 两种读法都不许混：**"签名器已实现" ≠ "Qoder 转发已交付"**，后者要等一次
  真实签名请求拿回 200（当前未验，见 §22.4 待验项）。
- 测试注入假签名器（`tests/integration/test_qoder_out.py`）验证**信封 + 明文构造**全链路。
  本轮新增的三面判据各管一段，别再混写成一句"契约见某文件"（R1 B-3 抓的就是这种假账：
  桥本体当时一行都没被默认判据执行过）：
  签名器契约与 NDJSON 往返 ⇒ `tests/unit/test_qoder_wasm_signer.py`；
  **桥脚本本体**（真 node 跑 `.mjs`：形状不符点名符号、行上限、一账号一上下文）⇒
  `tests/unit/test_qoder_bridge_mjs.py`；
  入站形态规则（system / 多模态 / tool_calls / tools 参数）⇒ `tests/unit/test_qoder_ask_shape.py`；
  与参考实现的逐键比对（**只管 builder 那一层**，两边各写字面量，不复用我方派生结果）⇒
  `test_stage_b_payload_equals_the_reference_builder`。

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
#: 🔴 措辞必须与现状同代：签名能力**已就位**（`wasm_signer.py` + `qoder_bridge.mjs`，
#: 调用客户端自带的 wasm），"未注入"现在只意味着**本机没配 wasm 桥目录**或凭据缺身份字段。
#: 旧文案说"尚未移植该通道"已经是假话，会让用户白等一个不存在的后续波次。
NOT_WIRED_HINT = (
    "qoder 出站需要 WASM 加密与 COSY 签名（客户端内嵌的 qoder-auth-wasm，"
    "DSH qoder-wasm.ts:599-706 同一条链路）；本进程未注入签名器 "
    "（SIGNER_FACTORY is None）→ 本资源当前不可用。"
    "处置：在本机设置 " + "MGW_QODER_WASM_GLUE" + " 指向含 qoder-wasm.js + "
    "qoder-auth-wasm.wasm 的目录（并保证有 node）后重启网关；"
    "或暂时在「接入模型资源」页停用该资源")


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

        - 排队（`10605`，或带排队字段）与额度（`110` / 公开端点的 `116`）→
          `envelope.business_error`（`code` 保真；排队 = 可重试、额度 = QUOTA）；
        - 其余（含 `105` 签名/认证失败）→ 原状态码抛出（交既有分类器 → AUTH 等）。

        🔴 402 也要走这条：额度耗尽时 Qoder 回的是 `402 {"code":116,…}`（2026-10-04 实测），
        只判 401/403 会让它落到 `errors.classify` 的 BAD_REQUEST 兜底 ⇒ **不冷却也不换号**，
        用户看到一条像"请求写错了"的错误。`business_error` 会把状态码归一成 429（QUOTA）。
        """
        if status in (401, 402, 403):
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
    """HTTP 401/402/403 的响应体是否是可识别的**业务错误**（排队 / 额度）。

    🔴 判据**只有一份**：认不认归 `envelope.is_business_error`，本层只做"认了就分类、
    没认就交回原状态码"。本函数原先自己又比了一遍码表（`10605`/`110`），于是加一个新码
    （本轮的 `116`）要改两处，且漏改的那处只能靠文案兜底蒙对 —— 撤证 M4 就是这么抓出来的。

    认不出来的（如 `Signature invalid (101)` / `auth_error (105)`）交给原状态码分类。
    """
    return envelope.business_error(text) if envelope.is_business_error(text) else None


def _family_guard():
    """取 `flow._guard_family`（**同一份**串用护栏，不复制第二份判据）。

    延迟 import：`flow.py` 模块级 import 了 `httpx`/`config`，与 `out.py` 无环，
    但延迟取用可让「只读目录/只造适配器」的场景不拉起整个 flow（构造期零副作用）。
    """
    from model_gateway.upstream.qoder.flow import _guard_family
    return _guard_family
