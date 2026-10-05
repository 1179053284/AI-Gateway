"""OpenAI 兼容出站适配（tech-design §4.4；商汤首发，字段形态经 2026-09-03 实测校准）。

- chat 非流式/流式（SSE 解析、思考字段归一化补充 reasoning_content）
- images generations
- kimi-k3 等仅支持 base64 图片的模型：公网 image_url 自动下载转 base64（下载失败
  → UpstreamError(no_failover=True)，INT-31：仅同资源重试、不切资源）
- 非 2xx → UpstreamError（携带原始响应体供透传）
"""

from __future__ import annotations

import base64
import ipaddress
import json
from typing import AsyncIterator, Callable
from urllib.parse import urlparse

import httpx

from model_gateway.core.errors import UpstreamError
from model_gateway.core.ir import normalize_stream_chunk
from model_gateway.core.resources import normalize_base_url


def _is_local_target(url: str) -> bool:
    """本机/私网目标 → 不走环境代理（E2E 实测校准：公网供应商直连不稳定时，
    环境代理（如系统 Clash）是可靠路径；localhost 假供应商/局域网供应商则必须绕过）。"""
    try:
        host = (urlparse(url).hostname or "").strip("[]").lower()
    except ValueError:
        return False
    if not host:
        return False
    if host == "localhost" or host.endswith(".local") or host.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # 公网域名 → 尊重环境代理
    return ip.is_loopback or ip.is_private


class OpenAIOutAdapter:
    #: chat 端点路径（**相对 base_url**）。产品族子类按取证值覆盖
    #: （`product_out.FamilyOpenAIOut`，如 CodeBuddy 系 = `/v2/chat/completions`），
    #: 本类的默认值 = 标准 OpenAI 兼容口径，行为与本属性引入前逐字一致。
    chat_path = "/chat/completions"

    def __init__(
        self,
        base_url: str,
        client: httpx.AsyncClient | None = None,
        needs_base64: Callable[[str], bool] | None = None,
    ):
        # 入站即归一化（验收 S-19）：`main.py` 用 `old.base_url` 判适配器可否复用，
        # 与运行态指纹共用 `normalize_base_url`。此处不 strip 的话，带空格的 URL
        # 会让两处口径再次分叉（复用判定恒不等 → 每次热重载都重建客户端连接）。
        self.base_url = normalize_base_url(base_url)
        # 公网供应商 → trust_env=True（环境代理可用则走，直连不稳定时是可靠路径，E2E 实测）；
        # 本机/私网供应商（INT 假供应商、局域网自建）→ trust_env=False 直连
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(60.0), trust_env=not _is_local_target(self.base_url)
        )
        self._needs_base64 = needs_base64 or (lambda _m: False)

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _headers(key: str) -> dict:
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    async def _convert_images_to_base64(self, body: dict) -> None:
        """把消息中的公网 image_url 下载转为 data URI（仅 only_base64_image 模型）。"""
        for msg in body.get("messages", []) or []:
            content = msg.get("content") if isinstance(msg, dict) else None
            if not isinstance(content, list):
                continue
            for part in content:
                if not (isinstance(part, dict) and part.get("type") == "image_url"):
                    continue
                image_url = part.get("image_url")
                url = image_url.get("url") if isinstance(image_url, dict) else None
                if not (isinstance(url, str) and url.startswith(("http://", "https://"))):
                    continue
                try:
                    async with httpx.AsyncClient(
                        timeout=httpx.Timeout(30.0), trust_env=not _is_local_target(url)
                    ) as dl:
                        resp = await dl.get(url)
                        resp.raise_for_status()
                        data = base64.b64encode(resp.content).decode()
                except Exception as e:  # noqa: BLE001 — 下载失败按 RETRYABLE（不切资源）
                    raise UpstreamError(
                        f"image_url download failed: {type(e).__name__}",
                        no_failover=True,
                    ) from e
                mime = resp.headers.get("content-type", "image/png").split(";")[0]
                part["image_url"] = {"url": f"data:{mime};base64,{data}"}

    async def _prepare_body(self, vendor_model: str, body: dict) -> dict:
        out = dict(body)
        out["model"] = vendor_model
        if self._needs_base64(vendor_model):
            await self._convert_images_to_base64(out)
        return out

    def _shape_response(self, data: dict) -> dict:
        """非流式响应体的产品缝（默认**恒等**；产品响应信封的解包在此覆写，§22.3）。

        置于 `normalize_stream_chunk` **之前**：信封不退壳时归一化会对着缺失
        `choices` 的外层空转（静默失配，2026-10-01 cline 实测教训）。
        """
        return data

    # —— chat 非流式 ——
    async def chat_nonstream(self, key: str, vendor_model: str, body: dict,
                             timeout: float) -> dict:
        payload = await self._prepare_body(vendor_model, body)
        try:
            resp = await self._client.post(
                f"{self.base_url}{self.chat_path}",
                headers=self._headers(key),
                content=json.dumps(payload, ensure_ascii=False),
                timeout=timeout,
            )
        except httpx.TimeoutException as e:
            raise UpstreamError(f"timeout: {e}") from e
        except httpx.HTTPError as e:
            raise UpstreamError(f"network: {type(e).__name__}: {e}") from e
        if resp.status_code != 200:
            raise self._http_error(resp)
        data = self._shape_response(resp.json())
        # 思考字段归一化（非流式：补充 reasoning_content，原字段保留）
        normalize_stream_chunk(data)
        return data

    # —— chat 流式（async generator：yield 归一化后的 chunk 字典）——
    async def chat_stream(self, key: str, vendor_model: str, body: dict,
                          timeout: float) -> AsyncIterator[dict]:
        payload = await self._prepare_body(vendor_model, body)
        try:
            async with self._client.stream(
                "POST",
                f"{self.base_url}{self.chat_path}",
                headers=self._headers(key),
                content=json.dumps(payload, ensure_ascii=False),
                timeout=timeout,
            ) as resp:
                if resp.status_code != 200:
                    text = (await resp.aread()).decode("utf-8", "replace")
                    raise self._http_error_from_text(resp.status_code, text)
                # SSE 解析：data: {...} / data: [DONE]（多行 data 累积到空行为止）
                data_lines: list[str] = []
                async for raw in resp.aiter_lines():
                    if raw == "":
                        if data_lines:
                            data = "\n".join(data_lines)
                            data_lines = []
                            if data.strip() == "[DONE]":
                                return
                            try:
                                chunk = json.loads(data)
                            except json.JSONDecodeError:
                                continue
                            if isinstance(chunk, dict):
                                yield normalize_stream_chunk(chunk)
                        continue
                    if raw.startswith("data:"):
                        data_lines.append(raw[5:].strip())
                    elif raw.startswith(":"):
                        continue  # 供应商注释帧（如 keep-alive）
        except UpstreamError:
            raise
        except httpx.TimeoutException as e:
            raise UpstreamError(f"timeout: {e}") from e
        except httpx.HTTPError as e:
            raise UpstreamError(f"network: {type(e).__name__}: {e}") from e

    # —— images ——
    async def images_generate(self, key: str, vendor_model: str, body: dict,
                              timeout: float) -> dict:
        payload = dict(body)
        payload["model"] = vendor_model
        try:
            resp = await self._client.post(
                f"{self.base_url}/images/generations",
                headers=self._headers(key),
                content=json.dumps(payload, ensure_ascii=False),
                timeout=timeout,
            )
        except httpx.TimeoutException as e:
            raise UpstreamError(f"timeout: {e}") from e
        except httpx.HTTPError as e:
            raise UpstreamError(f"network: {type(e).__name__}: {e}") from e
        if resp.status_code != 200:
            raise self._http_error(resp)
        return resp.json()

    @staticmethod
    def _http_error(resp: httpx.Response) -> UpstreamError:
        text = resp.text
        from model_gateway.core.errors import extract_error_type
        return OpenAIOutAdapter._http_error_from_text(resp.status_code, text)

    @staticmethod
    def _http_error_from_text(status_code: int, text: str) -> UpstreamError:
        from model_gateway.core.errors import extract_error_type
        return UpstreamError(
            f"upstream {status_code}",
            status_code=status_code,
            error_body=text,
            error_type=extract_error_type(text),
        )
