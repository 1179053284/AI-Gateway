"""Cline **出站适配**（tech-design v2.0 §22.3；M6-5b 接线）。

本模块是 `FamilyOpenAIOut` 的产品族实现：传输 / SSE 解析 / 错误映射全部继承
（`adapters/openai_out.py`），本类只声明**本产品取证到的差异**：

| 项 | 取值 | 取证 | 处置 |
|---|---|---|---|
| 推理路径 | `POST {apiBase}/api/v1/chat/completions` | `cline-product.ts:301`（`CLINE_CHAT_PATH`）；`cline-adapter.ts:7,568` 实测标准 SSE | `Resource.base_url` 已含 `/api/v1`（`accounts/registry.py` 的 cline 块）→ **基类缺省 `chat_path` 恰好正确**，不覆盖 |
| 鉴权 | `Authorization: Bearer workos:<access_token>`（**前缀不可剥**） | `cline-product.ts:96-115`；`cline.ts:159-182` | 复用 `protocol.auth_headers`（内含 `bearer_value` 幂等补齐） |
| 客户端标识头 | `HTTP-Referer` / `X-Title` / `X-IS-MULTIROOT` / `X-CLIENT-TYPE` | `cline-product.ts:269-274`（`DEFAULT_CLINE_REQUEST_HEADERS`） | 同上（`protocol.CLIENT_HEADERS`） |
| `Accept` | `text/event-stream` | `cline-adapter.ts:571-577` | `protocol.auth_headers` 的 `extra` 覆写 |
| 请求体 | 标准 OpenAI；**`max_tokens` 下限 16**（P1-4，2026-10-11） | `api/admin.py` 探测注释同源取证：cline/Vercel 路把 `max_tokens` 映成 `max_output_tokens` 并要求 `>= 16`，小值回 400「integer below minimum」（2026-10-08 gpt-6 系 14 次失败同因） | 写 `prepare_body`：落模型名（基类）+ 小值抬到 16，其余一字不动 |
| **非流式响应** | **`{success, data:{choices…}, model}` 信封** | **2026-10-01 :8300 实网实测**（顶层键 = `["data","success","model"]`，`choices/usage` 全在 `data` 内） | `_shape_response` 解包（仅"顶层无 `choices` 且内层 `data` 含 `choices`"时；流式帧实测无信封，不受影响） |

🔴 **`workos:` 前缀**（`cline.ts:159-182`，实测坑位）：前缀只在**解码 JWT** 时被剥，
凡是把存储令牌放进 `Authorization` 的请求（出站推理 / `users/me` / `balance`）**必须保留**——
剥掉即 401，且报错文案是 "make sure you're using the latest version of Cline"（与真实原因
毫不相干，会让人误判成「版本过旧」）。`protocol.bearer_value` 做幂等补齐，本模块直接复用。

**错误语义与既有分类器的对齐（逐条给依据，不另造一套）**：

- **401** → `UpstreamError(status_code=401)` → 分类器 `AUTH` → 上层 `disable`（终态、
  不重试、切下一资源）—— 与既有 `openai_out` 的错误形态**逐字一致**（`core/errors.py`
  的 HTTP 通用映射），本模块不额外包装；
- **429** → `QUOTA`（按 `access_mode` 冷却 + 短退避，§22.5-5）；**5xx / 网络类** → `RETRYABLE`；
- **403 不是凭据问题**（本产品特有，`cline-adapter.ts:600-640` 的真实缺陷）：地域封锁
  / 模型未开通会回 **403**（实测 `cline-free/muse-spark-1.3-contributor`：
  `403 {"error":"access forbidden: … is not available in your region","success":false}`）。
  DSH 早期把 401/403 一律当凭据过期 → 触发续期 → 仍 403 → 归 `AUTH` → 界面显示
  「API 密钥无效」，**真实原因被完全掩盖**。本网关的分类器不把 403 归 `AUTH`
  （不 disable）—— 这一半与本模块原先的判断一致。
- 🔴 **但「不 disable」不等于「不换号」（2026-10-08 实盘修正）**：403 落 `BAD_REQUEST`
  兜底 ⇒ 请求**直接失败**，池里其它健康资源全程闲置。实测 `glm-5.3-flash` 池里挂的
  `cline-pass/glm-5.3-flash`（该账号**有余额但没订阅该模型计划**，DSH
  `cline-rate-limit.ts:240-241` 同一账号实录 `/users/me/plan/usage-limits` 回
  `404 no plan history found for user`）恒回
  `403 {"error":{"code":"ENTITLEMENT_ERROR","message":"… not subscribed to required model plan"}}`
  ⇒ **cline 尝试 5/5 全失败**、6 次采样 2 次把 403 交给客户端。
  这类「**资源级不可承接**」必须**换号续跑**（与 `AUTH` 一样"切下一资源"，但不 disable、
  不计 C）—— 故本模块把这两种 403 语义归一成 `RESOURCE_UNAVAILABLE_TYPE`
  交分类器（与 qoder 把 402 归一成 QUOTA 同一手法，`upstream/qoder/out.py:172-188`）。
  ⚠️ **判定只能靠响应体文案**（同一批 403 里既有真凭据问题、也有地域/订阅问题，
  `cline-adapter.ts:958` 的实测结论），且**只认取证过的表述**。

⚠️ 非流式已知口径（2026-10-01 更新）：`stream:false` 上游**接受**（:8300 实网 200），
但响应套 `{success, data}` 信封 → 由 `_shape_response` 解包；流式帧为**标准 chunk**
（实测无信封），照走基类 SSE 解析。

⚠️ 本模块**无网络副作用**：只构造适配器；请求由 `core/scheduler` 驱动（§22.8-1）。
"""

from __future__ import annotations

from model_gateway.adapters.product_out import FamilyOpenAIOut
from model_gateway.core.errors import RESOURCE_UNAVAILABLE_TYPE, UpstreamError
from model_gateway.upstream.cline import protocol

#: 「地域封锁 / 该地区不可用」的响应体特征词（**小写比对**）。
#: 逐字取自 DSH `cline-adapter.ts:969-978` 的 `CLINE_REGION_FORBIDDEN_MARKERS`
#: （四个表述，上游措辞可能微调故取特征词）——**不扩写、不猜**。
_REGION_FORBIDDEN_MARKERS: tuple[str, ...] = (
    "not available in your region",
    "access forbidden",
    "region not supported",
    "not available in your country",
)

#: 「有余额但没订阅该模型计划」的业务码（DSH `cline-rate-limit.ts:240-241` 实录）。
_ENTITLEMENT_CODE = "ENTITLEMENT_ERROR"

#: cline/Vercel 路的输出预算下限（与 `api/admin.py` 探测注释同源取证）：上游把
#: `max_tokens` 映成 `max_output_tokens` 并要求 `>= 16`，客户端发小值即 400
#: 「integer below minimum」⇒ 模型可用却报"不可用"（2026-10-08 12:51–12:53 的
#: gpt-6 系 14 次失败同因）。该约束此前只做在**探测侧**（探测预算写死 64），
#: 转发侧没有任何保护 —— P1-4 把它下沉到本产品的出站塑形（2026-10-11）。
_MIN_OUTPUT_TOKENS = 16


def _is_resource_scoped_403(text: str) -> bool:
    """这条 403 是「**资源级不可承接**」而不是凭据问题吗？

    🔴 判据只能靠响应体文案（DSH `cline-adapter.ts:958` 实测：同一批 403 里既有真的
    凭据问题、也有地域限制）。认两种**取证过**的表述：

    1. `ENTITLEMENT_ERROR` 业务码 —— 有余额、没订阅该模型计划
       （`cline-rate-limit.ts:240-241`；额度端点回 `404 no plan history found for user`）；
    2. 地域特征词 —— `isClineRegionForbidden` 的四个标记（`cline-adapter.ts:969-978`）。

    ⚠️ 不认「forbidden」这类泛词（会把真凭据问题误吞成"换号就行"）；
    非 403 一律不认（401 走 `AUTH`、402/429 走 `QUOTA`、5xx 走 `RETRYABLE`，各归各位）。
    """
    lowered = (text or "").lower()
    if _ENTITLEMENT_CODE.lower() in lowered:
        return True
    return any(marker in lowered for marker in _REGION_FORBIDDEN_MARKERS)


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

    def prepare_body(self, body: dict, *, vendor_model: str, cred: dict,
                     meta: dict, device: dict) -> dict:
        """体塑造：落供应商模型名（基类）+ **输出预算下限**（P1-4，2026-10-11）。

        - 取证：`_MIN_OUTPUT_TOKENS` 注释（上游约束 `>= 16`，此前只护探测不护转发）；
        - 只上钳不注入：客户端没发 `max_tokens` 就不加（上游默认值是它自己的事）；
          发 `>= 16` 原样透传；发小值抬到 16 —— 只放宽**上限**不改语义（模型到
          EOS 即停，多给的预算不改变内容），且仅限本产品（其它通道无此取证不扩）；
        - 其余字段一字不动（本产品推理体无自有塑形，`cline-product.ts:13` 协议表）。
        """
        out = super().prepare_body(body, vendor_model=vendor_model,
                                   cred=cred, meta=meta, device=device)
        asked = out.get("max_tokens")
        if isinstance(asked, (int, float)) and not isinstance(asked, bool) \
                and asked < _MIN_OUTPUT_TOKENS:
            out["max_tokens"] = _MIN_OUTPUT_TOKENS
        return out

    # —— 响应整形钩子 ——

    def _http_error_from_text(self, status_code: int, text: str) -> UpstreamError:
        """非 200 → 错误（**并重解释 403 的资源级语义**，2026-10-08）。

        只改写一种形状：`403` + 取证过的「资源级不可承接」文案 ⇒ 打上
        `RESOURCE_UNAVAILABLE_TYPE` 交分类器 → `RESOURCE_UNAVAILABLE`
        → 调度器**换号续跑 + 冷却这条 (资源, 模型)**（不 disable、不计 C）。
        其余状态码（401/402/429/5xx/网络）**一字不动**，走既有归属。

        🔴 覆写本钩子即同时覆盖流式与非流式两条腿（基类两处都是 `self.` 调用，
        2026-10-08 顺带把基类那处硬编码修成多态，见 `openai_out._http_error` 注释）。
        """
        err = super()._http_error_from_text(status_code, text)
        if status_code == 403 and _is_resource_scoped_403(text):
            err.error_type = RESOURCE_UNAVAILABLE_TYPE
        return err

    def _shape_response(self, data: dict) -> dict:
        """解开 `{success, data}` 信封（非流式实测形，2026-10-01；§22.3 `_shape_response` 缝）。

        只在"顶层无 `choices` 且内层 `data` 是含 `choices` 的 dict"时退壳 ——
        其余形状（已是标准体 / 业务错误体 / 异常体）**原样返回**，不吞不造。
        """
        if isinstance(data, dict) and "choices" not in data:
            inner = data.get("data")
            if isinstance(inner, dict) and "choices" in inner:
                return inner
        return data


#: 头钩子的**显式登记**（供接线护栏核验，与 buddy 的 `_HEADER_HOOK` 同一性质）：
#: `FamilyOpenAIOut._headers` 按属性名多态调起 `self.auth_headers(...)`，
#: 纯 AST 判据看不见"子类覆盖 + 基类调起"这种间接（会误报死代码）。
_HEADER_HOOK = ClineOut.auth_headers
