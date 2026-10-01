"""产品出站适配（tech-design v2.0 §22.3「出站适配」；M6-5a 基础设施 + 试点）。

**职责**：把"某产品的某账号"接成网关可调度的出站面 —— 与 `openai_out.py` /
`anthropic_out.py` **同形的 duck typing**（§22.3）::

    base_url: str; protocol: str; product: str; account_ref: str
    async chat_nonstream(key, vendor_model, body, timeout) -> dict
    async chat_stream(key, vendor_model, body, timeout)   -> AsyncIterator[dict]
    async aclose() -> None

🔴 **凭据只在本地账号目录**（铁律 1 / §22.3）：调度侧传进来的 `key` 对产品资源恒为空串
   （物化时 `api_key=""`），适配器从 `account_ref` 经**账号存储唯一入口**
   （`accounts.store.load_credentials` / `hook_meta`）自解 —— 凭据**不进 config、
   不落日志**（§22.8-8：日志里只许出现短哈希指纹）。

分层与形态（§22.1/§22.3）：

- `ProductOutAdapter`：契约载体（四个属性 + 三个方法的**接口声明** + 凭据解析）；
- `FamilyOpenAIOut`：openai 族产品的「**基类 + 头/体钩子**」形态 —— 子类只需给
  `auth_headers(cred, meta, device)`（必装）与 `prepare_body(...)`（可选，默认只落
  厂商模型名）；传输（客户端 / SSE 解析 / 错误映射 / 图片转 base64）全部复用
  `OpenAIOutAdapter`，**不复制第二份**。
- 其余协议族（anthropic 等）后续波次照此形态加 `FamilyAnthropicOut`（M6-5b）。

⚠️ 本模块**不 import 账号层与产品层于模块级**（延迟到调用时）：适配层要被
   `upstream/<product>/` 反向引用（`build_out` 返回本模块的类型），模块级成环会让
   `import model_gateway.adapters` 与 `import model_gateway.upstream.<p>.product` 互锁。
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable

from model_gateway.adapters.openai_out import OpenAIOutAdapter
from model_gateway.core.errors import UpstreamError
from model_gateway.core.resources import normalize_base_url


@dataclass(frozen=True)
class ProductAccount:
    """`build_out(account)` 的**载荷**（§22.3 冻结签名里那个 `account`）。

    字段即适配器构造所需的最小信息集：

    - `product` / `name`（= `Resource.account_ref`，账号名）；
    - `base_url`：**资源侧**配置值（物化时写入产品注册表值，§22.5-1）——允许使用者
      在资源页改指向（如指向本地假上游做验证），故出站基址以资源为准、不以注册表为准；
    - `needs_base64`：资源级能力探针（`EnumPool.needs_base64_image`）。冻结签名
      `build_out(account)` **不允许追加形参**，故由装配侧经本载荷注入；缺省 None =
      不做公网图片转 base64（与 `openai_out.py` 的既有缺省一致）。
    """

    product: str
    name: str
    base_url: str = ""
    needs_base64: Callable[[str], bool] | None = None

    @property
    def account_ref(self) -> str:
        """账号名（与 `Resource.account_ref` 同义，取用侧两种叫法都成立）。"""
        return self.name


class ProductOutAdapter:
    """产品出站适配的**契约**（§22.3 duck typing；`FamilyOpenAIOut` 等下文的族基类实现它）。

    🔴 三个方法在这里只有**接口声明**（`NotImplementedError`），实现由族基类提供 ——
    这是有意的：`FamilyOpenAIOut` 的真实实现来自 `OpenAIOutAdapter`（传输复用，
    不复制第二份 SSE 解析），若本类也定义同名方法，MRO 会把真实现**盖掉**
    （`FamilyOpenAIOut` 的基序是 `(OpenAIOutAdapter, ProductOutAdapter)`）。
    直接继承本类而三个方法都不实现 → 构造出来的适配器首次调用即显式失败（不静默半实现）。

    子类义务（逐条，M6-5b 起新增产品族照此办理）：
    ① 四个属性必须真实（`base_url` 归一化、`product`/`account_ref` 与载荷一致）；
    ② `chat_*` 的返回形态与 `openai_out.py` 同为**网关内部格式**（OpenAI 形状的
       dict / 归一化 chunk；usage 字段映射在适配器内完成，§18.2 ③）；
    ③ 失败一律抛 `UpstreamError`（带 status_code/error_body 供既有分类器判定）。
    """

    def __init__(self, account: ProductAccount, *, protocol: str = "openai") -> None:
        self.product = account.product
        self.account_ref = account.account_ref
        self.base_url = normalize_base_url(account.base_url)
        #: 上游协议族字面量（`Resource.protocol` 口径；产品分派优先于它，§22.5-3）
        self.protocol = protocol

    # —— 凭据解析（四个族基类共用；唯一的凭据读取入口）——

    def resolve_context(self) -> tuple[dict, dict, dict]:
        """`(凭据本体, 钩子 meta, 设备字段)` —— §22.3 的 `meta` 通道 + §22.8-6 的失败隔离。

        - 凭据 → `accounts.store.load_credentials`（**唯一**读入口，§22.2 不变式⑤）；
        - meta → `accounts.store.hook_meta`（锚字段 `account`/`dir` + `meta.json` 铺开，
          M6-4 实测教训：直传会让 zcode 退化为 unknown）；产品族目前只用到 `dir`，
          但**取法必须走唯一组装入口**；
        - device → 按注册表 `DeviceSpec.fields` 从 meta **逐字段**取（§22.3/Q26-②；
          无设备身份的产品为空 dict）；
        - 凭据缺失/读不动 → `UpstreamError`（**fail closed**，不拿空令牌去打上游）。
        """
        from model_gateway.accounts import store as account_store  # 延迟：见模块头 ⚠️

        cred = account_store.load_credentials(self.product, self.account_ref)
        if not cred:
            raise UpstreamError(
                f"账号 {self.product}/{self.account_ref} 无凭据（未登录或凭据文件缺失）"
                " —— 请重新登录该账号（资源已物化、凭据未落盘）")
        meta = account_store.hook_meta(self.product, self.account_ref)
        return cred, meta, _device_of(self.product, meta)

    async def chat_nonstream(self, key: str, vendor_model: str, body: dict,
                             timeout: float) -> dict:
        raise NotImplementedError(f"{type(self).__name__}.chat_nonstream 未实现（§22.3 契约）")

    async def chat_stream(self, key: str, vendor_model: str, body: dict,
                          timeout: float) -> AsyncIterator[dict]:
        # 下面是**不可达**的 yield：本方法须与真实现同为 **async generator**
        # （`openai_out.py` 的形态），否则调用方 `async for` 会拿到 coroutine 报 TypeError，
        # 把"未实现"伪装成无关错误。
        raise NotImplementedError(f"{type(self).__name__}.chat_stream 未实现（§22.3 契约）")
        yield {}  # pragma: no cover

    async def aclose(self) -> None:
        raise NotImplementedError(f"{type(self).__name__}.aclose 未实现（§22.3 契约）")


class FamilyOpenAIOut(OpenAIOutAdapter, ProductOutAdapter):
    """openai 族产品的产品出站适配（「基类 + 头/体钩子」形态，§22.3；M6-5a 试点）。

    - 传输面（`httpx` 客户端 / SSE 解析 / 2xx 错误映射 / only-base64 图片转码）**全部**
      继承 `OpenAIOutAdapter` —— 产品的差异只在两处钩子；
    - `chat_path`：产品推理端点路径（缺省 `/chat/completions`）。子类按**取证值**覆盖
      （buddy 系 = `/v2/chat/completions`），不猜；
    - `auth_headers(cred, meta, device)`：**必装**（子类实现）——返回除 Content-Type 外的
      全部请求头（Content-Type 由本类补齐）；
    - `prepare_body(...)`：可选，默认 `{**body, "model": vendor_model}`。

    ⚠️ 头与体两个钩子**各自**读一次账号上下文（`resolve_context`）：故意**不做跨钩子缓存**
    —— 缓存会让"重新登录拿到新令牌"延迟生效（旧令牌继续打上游 → 401 循环）；
    代价是一次请求多读一个本地小 JSON（非上游调用，不违反 §22.8-1）。
    """

    #: 推理端点路径（子类覆盖；拼接口径与 `OpenAIOutAdapter` 一致）
    chat_path: str = "/chat/completions"

    def __init__(self, account: ProductAccount, *, client=None,
                 needs_base64: Callable[[str], bool] | None = None) -> None:
        # 基序 = (OpenAIOutAdapter, ProductOutAdapter)：`chat_*`/`aclose` 取真实现，
        # 契约属性由 ProductOutAdapter 提供（见 ProductOutAdapter 的 MRO 说明）。
        OpenAIOutAdapter.__init__(
            self, account.base_url, client=client,
            needs_base64=needs_base64 if needs_base64 is not None else account.needs_base64)
        ProductOutAdapter.__init__(self, account)

    # —— 子类钩子 ——

    def auth_headers(self, cred: dict, meta: dict, device: dict) -> dict:
        """鉴权/身份头（**必装**；不含 Content-Type，由本类补齐）。"""
        raise NotImplementedError(
            f"{type(self).__name__}.auth_headers 未实现（§22.3：产品族必须给出身份头）")

    def prepare_body(self, body: dict, *, vendor_model: str, cred: dict,
                     meta: dict, device: dict) -> dict:
        """请求体塑形钩子（可选；默认只落厂商模型名）。

        工具传参 > 网关设置 > 厂商内置的字段级注入已在 `core/scheduler` 完成，
        此处**只做产品私有塑形**（如 qoder 的信封、trae 的成帧 —— M6-5b），
        不要在族基类里重复注入采样参数。
        """
        return {**body, "model": vendor_model}

    # —— OpenAIOutAdapter 的内部缝（基类方法调 `self._prepare_body` / `self._headers`）——

    async def _prepare_body(self, vendor_model: str, body: dict) -> dict:
        cred, meta, device = self.resolve_context()
        out = self.prepare_body(dict(body), vendor_model=vendor_model,
                                cred=cred, meta=meta, device=device)
        if self._needs_base64(vendor_model):
            await self._convert_images_to_base64(out)
        return out

    def _headers(self, key: str) -> dict:
        """覆盖基类的 `Authorization: Bearer <配置 Key>`（`key` 对产品资源恒为空串）。

        🔴 忽略 `key`：产品资源的凭据从账号目录自解（§22.3）——配置里那个空 Key
        不参与鉴权；传进来非空值也不使用（避免"两处凭据"的分叉面）。
        """
        del key
        cred, meta, device = self.resolve_context()
        headers = dict(self.auth_headers(cred, meta, device))
        headers.setdefault("Content-Type", "application/json")
        return headers


def build_product_adapter(product: str, account_ref: str, base_url: str, *,
                          needs_base64: Callable[[str], bool] | None = None) -> Any:
    """按 `product` 构造出站适配器（§22.5-3：**product 分支优先于 protocol**）。

    流程：注册表校验（未登记 → 可读 `KeyError`）→ 载入 `upstream/<product>/product.py`
    → 调它的 `build_out(account)`（§22.3 冻结签名）。产品未实现 `build_out` 时
    `NotImplementedError` 原样冒出，由装配侧按资源降级（**不得**让一条未接线资源
    拖垮整个热重载）。
    """
    from model_gateway.accounts.registry import get as registry_get  # 延迟：见模块头 ⚠️

    prod = str(product or "").strip()
    name = str(account_ref or "").strip()
    if not prod:
        raise ValueError("build_product_adapter: product 不能为空")
    if not name:
        raise ValueError(
            f"资源声明了 product={prod!r} 但 account_ref（账号名）为空 —— 无法解析凭据（§22.5-2）")
    registry_get(prod)  # 未登记当场 KeyError（不静默降级）
    module = importlib.import_module(f"model_gateway.upstream.{prod}.product")
    account = ProductAccount(product=prod, name=name,
                             base_url=normalize_base_url(base_url),
                             needs_base64=needs_base64)
    return module.build_out(account)


def _device_of(product: str, meta: dict) -> dict:
    """按注册表 `DeviceSpec.fields` 从钩子 meta **逐字段**取设备值（§22.3/Q26-②）。

    取不到的产品（未登记 / 无设备身份）→ 空 dict：**不编造**设备值 —— 设备身份是
    跨账号唯一性（§15.1）的判据，凭空造一个会污染上游的风控归因。
    """
    from model_gateway.accounts.registry import get as registry_get  # 延迟：见模块头 ⚠️

    try:
        spec = registry_get(product).device
    except KeyError:
        return {}
    return {field: str(meta.get(field) or "") for field in spec.fields}
