"""产品模型目录的**本地缓存**（Q33-④）：让"账号内部模型的规格"能进调度与对外声明。

## 为什么需要这一层（调研轮的实测结论，不是推测）

- 产品侧的 `context_window` / `max_output` 等规格**只有供应商目录端点知道**，而本仓此前
  唯一的消费者是管理端弹窗 `GET …/catalog`（每次现调钩子、**零缓存**）⇒
  规格既不进 `/v1/models` 的对外声明，也不进选路，"两类接入同级"只存在于口号上。
- 规格要进调度与声明，就**不能在请求期发网络查询**（`tech-design §22.5-6` / `20 §C2`
  的既有定论：请求期查余额/查目录是把 200ms 的本地决策变成 2s 的远程决策）。
  所以只有两条路：**落盘缓存**，或者不接。本模块就是那条落盘的路。

## 与 ZCode 的差异（为什么不能照抄它的"及时"）

ZCode 的目录确实动态可拉，但它的刷新触发点**只有手动按钮**（无 TTL、无失效判据）。
本层把"什么时候算新"写成**数据里的显式字段**（`fetched_at` + `ttl_seconds`），
读侧永远能区分三种状态：**新鲜 / 陈旧（仍可用作兜底，但界面必须标出来）/ 没有**。
绝不把陈旧值当实时值输出（铁律 2：无证据不得宣称）。

## 不变式

1. **只由读侧写**：`GET …/catalog` 成功拿到远端目录时顺带落盘；失败**不覆盖**旧缓存
   （坏数据不得顶掉好数据）。
2. **零网络读**：`read_cache()` 只读文件，任何调用点（含 `rebuild` / `/v1/models`）
   都不会因此发请求。
3. **不入库**：缓存在 `data/upstream/<product>/_catalog_cache.json`（`.gitignore` 的运行时
   数据区，**产品根而不是 `accounts/` 子目录** —— 后者只放账号目录，`list_accounts`
   以"是目录且有 `meta.json`"为判据，把缓存文件混进去放就是给枚举面添一个非账号条目）。
4. **写盘只经唯一入口**：`store.atomic_write_json`（同目录 `mkstemp` 唯一临时名 + fsync +
   `os.replace`，§22.2 不变式①）。
   ⚠️ **§22.2 不变式⑤的两条例外登记**（评审 R1-⑧ / R3-F-1，已在 tech-design 同批归档）：
   ① 本模块的读侧 `GET …/catalog` 是全站唯一一个**读端点顺带写盘**的地方（缓存是账号侧
   规格进调度/声明的唯一来源，而那两条路径都禁止发网络请求）；
   ② 它写的不是凭据，是产品级目录快照。除这两条外，凭据写盘入口仍然只有
   `store.commit_login`。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from model_gateway.accounts import store
from model_gateway.accounts.types import ModelInfo

logger = logging.getLogger("model_gateway.accounts")

#: 缓存文件名（住在产品根，不在 `accounts/` 里 —— 那里只放账号目录）
CACHE_FILE = "_catalog_cache.json"
#: 按号副本的前缀 ⇒ 实际文件名 `_catalog_cache.<清洗名>-<8 位哈希>.json`
#: （与 `schemas.py` / `admin_accounts.py` 的文档措辞一致；R5-⑥ 修的就是这里）
_PER_ACCOUNT_PREFIX = CACHE_FILE[:-5] + "."

#: 默认有效期：一天。产品目录漂移是天级的（套餐/权益变更才会变），
#: 而网关每天会被 ops tick 打到很多次，取一天足够"及时"又不会天天打供应商。
DEFAULT_TTL_SECONDS = 86400


def product_dir(product: str) -> Path:
    """缓存所在的产品根 = **账号根的父目录**（`data/upstream/<product>`）。

    🔴 三个不等式要分清：
    - **不等于** `store.product_root()` —— 那条返回的是它的 `accounts/` 子目录（只放账号目录），
      缓存是**产品级**数据，塞进去会被"枚举账号目录"的读侧当成一个账号的邻居；
    - **不能**写死成 `paths.data_dir()/"upstream"/<product>` —— 那会让 `MGW_<PRODUCT>_ACCOUNTS`
      把账号根重定向到别的盘/别的实例数据树的场合下，缓存独自留在默认树里
      （复验轮 R4-⑥）：实例身份与"这个实例的数据在哪"必须同尺，否则界面上看到的规格
      与实际账号库不是同一棵树；
    - 仍**不入库**：`.gitignore` 覆盖整个 `data/`（实测 `git check-ignore -v` 命中）。
    """
    return store.product_root(product).parent


def cache_path(product: str, *, account: str = "", root: Path | str | None = None) -> Path:
    """`root` = 产品根（`data/upstream/<product>`），不是账号根。

    🔴 **按号那份**（Q33 债务②）：`account` 非空 ⇒ `_catalog_cache.<账号>-<短哈希>.json`。
    为什么必须分文件：产品级缓存只说得出"这个产品有这些模型"，而判定式第四项要问的是
    "**这个号**有没有这个模型"（权益按号算，同产品不同号套餐不同）。拿产品级去筛号
    会把权益窄一点的号误杀、把权益宽的号放进来吃 404 —— 两种都是假判据。
    """
    base = Path(root) if root is not None else product_dir(product)
    name = CACHE_FILE if not account else f"{_PER_ACCOUNT_PREFIX}{_safe(account)}.json"
    return base / name


def _safe(account: str) -> str:
    """账号名 → 文件名片段：白名单字符 + **原文短哈希**后缀。

    🔴 R5-⑤：只清洗不保证唯一 —— `user.name@x.com` 与 `user_name@x.com` 清洗后完全相同、
    超 32 字符的长名被截断后也相同 ⇒ **A 号的目录缓存会替 B 号否决映射**（把"某个号没有这个
    模型"安到另一个号头上），那是按号判据最坏的失效方式（静默、且方向是"错杀可用号"）。
    后缀取 sha1(原名)[:8]：不泄漏账号名以外的信息（名字本身已在文件名里），只保证不撞。
    """
    raw = str(account)
    keep = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in raw[:32])
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return f"{keep or 'anon'}-{digest}"


def account_lacks(product: str, account: str, vendor_model: str,
                  *, root: Path | str | None = None) -> bool:
    """🔴 判定式第四项「该号目录确实有此模型」——**只在有新鲜证据时说不**。

    返回 `True` 的唯一条件：这个号**自己**的目录缓存存在、**未过期**、且里面确实没有这条模型。
    三种"没有证据"一律 `False`（放行，不拦）：
    ① 从没取过这个号的目录（没文件）；② 缓存超 TTL（权益是天级变化的，陈旧值不足以否决）；
    ③ 读不动 / 结构不认识。
    立意与 §12「消灭无报错的失败」一致：**宁可放行后由上游答复告诉我们**，
    也不凭"不知道"就把一条可能可用的映射判死 —— 那才是不可发现的静默降级。
    """
    if not account or not vendor_model:
        return False
    view = read_cache(product, account=account, root=root)
    if not view or view.get("stale"):
        return False
    return not any(getattr(m, "id", None) == vendor_model for m in view["models"])


def write_cache(product: str, models: list[ModelInfo], *, source_account: str = "",
                ttl_seconds: int = DEFAULT_TTL_SECONDS,
                root: Path | str | None = None) -> bool:
    """把一次**成功**的远端目录落盘。空清单不写（"取到了 0 条"不是证据，是异常）。

    🔴 `source_account` 非空 = 这份目录**真的是这个号取到的** ⇒ 除产品级缓存外，
    再落一份**按号副本**（`_catalog_cache.<账号>-<短哈希>.json`）—— 那是判定式第四项
    「该号目录确实有此模型」唯一的按号证据（债务 Q33-债6-②）。产品级那份不代表
    任何单个号的权益：同产品不同号套餐可以不同。

    返回是否写入。写失败只记日志返回 False —— 缓存是加速与可用性兜底，
    它挂了不能把「刚刚成功的那次目录调用」也变成失败。
    """
    if not models:
        return False
    written = _write_one(product, models, source_account=source_account,
                         ttl_seconds=ttl_seconds, root=root, account="")
    if source_account:
        # 按号副本写失败只影响第四项判据的可用性，不撤销产品级已写成功的事实
        _write_one(product, models, source_account=source_account, ttl_seconds=ttl_seconds,
                   root=root, account=source_account)
    return written


def _write_one(product: str, models: list[ModelInfo], *, source_account: str,
               ttl_seconds: int, root: Path | str | None, account: str) -> bool:
    payload = {
        "fetched_at": time.time(),
        "ttl_seconds": int(ttl_seconds),
        "source_account": str(source_account or ""),
        "count": len(models),
        "models": [asdict(m) for m in models],
    }
    path = cache_path(product, account=account, root=root)
    try:
        # 🔴 写盘走 `store.atomic_write_json` 这个**唯一入口**（§22.2 不变式①/⑤，
        # 评审 R1-⑧）：同目录 `mkstemp` 唯一临时名 + fsync + `os.replace`。
        # 先前这里用**固定** `.tmp` 名且无 fsync，而仓内 `zcode/quota.py` 就撞过
        # "固定名被互相截断"的真实缺陷 —— 缓存与凭据写的是同一棵数据树，不该有第二套纪律。
        store.atomic_write_json(path, payload)
    except (OSError, TypeError, ValueError) as e:
        # 🔴 三类都要接住（复验轮 R4-⑤）：钩子回传的是**上游数据**，其字段值出格时
        #    （`Decimal`/嵌套对象等非 JSON 原生值）`atomic_write_json` 抛 `TypeError`，
        #    只捕 `OSError` 会把"刚刚成功的那次目录调用"打成 500 —— 与上面的自述矛盾。
        logger.warning("产品 %s 的目录缓存写入失败（不影响本次结果）：%s: %s",
                       product, type(e).__name__, e)
        return False
    return True


def read_cache(product: str, *, account: str = "",
               root: Path | str | None = None) -> dict[str, Any] | None:
    """读缓存：返回 `{fetched_at, age_seconds, stale, models: [ModelInfo...]}` 或 None。

    `account` 非空 ⇒ 读的是**那个号自己**的副本（按号权益判据用），空 ⇒ 产品级那份。
    两种缓存是两份不同的事实，不可互换：产品级说"这个产品有这些模型"，按号说
    "这个号取到的目录里有这些模型"。

    - 文件不存在/读不动/结构不认识 → `None`（**没有**，与**陈旧**是两种状态，不能混）；
    - `stale = age > ttl`：陈旧仍然返回（离线时它是唯一可用的规格来源），
      但调用方**必须**如实标注陈旧，不得当成实时值对外声明。
    """
    path = cache_path(product, account=account, root=root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    raw = data.get("models")
    if not isinstance(raw, list):
        return None
    models: list[ModelInfo] = []
    known = {f for f in ModelInfo.__dataclass_fields__}
    for item in raw:
        if isinstance(item, dict) and item.get("id"):
            # 字段漂移容忍：只认已知字段（目录结构变了不该让整个读侧抛错）
            models.append(ModelInfo(**{k: v for k, v in item.items() if k in known}))
    if not models:
        return None
    try:
        fetched_at = float(data.get("fetched_at") or 0.0)
        ttl = float(data.get("ttl_seconds") or DEFAULT_TTL_SECONDS)
    except (TypeError, ValueError):
        return None
    age = max(0.0, time.time() - fetched_at)
    return {
        "fetched_at": fetched_at,
        "age_seconds": age,
        "ttl_seconds": ttl,
        "stale": age > ttl,
        "source_account": str(data.get("source_account") or ""),
        "count": len(models),
        "models": models,
    }
