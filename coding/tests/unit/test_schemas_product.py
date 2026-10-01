"""§22.5-2 schema **最小改动用例**（M6-5a）：`Resource.account_ref` + `api_key` 放宽 + 互斥校验。

三条判据（逐条对应 tech-design §22.5-2 原文）：

① `api_key` 放宽为可空串，但 `product == ""` 时**仍必须非空** → **旧配置零改动**即可加载；
② `product` 非空时 `account_ref`（产品账号名）必填；
③ 新字段随 `model_dump` 走写盘路径（保存后重启不丢）。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from model_gateway.config.schemas import AppConfig, Resource


def _res(**over) -> dict:
    base = {"id": "res-a", "name": "A", "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-a"}
    base.update(over)
    return base


# ============ ① 旧配置零改动 ============

def test_legacy_resource_unchanged_without_new_field():
    """旧式按量资源（无 product / 无 account_ref）**照旧加载**，新字段取默认值。"""
    r = Resource.model_validate(_res())
    assert r.api_key == "sk-a" and r.product == "" and r.account_ref == ""


@pytest.mark.parametrize("api_key", ["", None])
def test_empty_api_key_still_rejected_when_no_product(api_key):
    """`api_key` 放宽为可空串**只为容纳产品资源**：`product` 为空时仍必须非空。"""
    data = _res()
    if api_key is None:
        del data["api_key"]
    else:
        data["api_key"] = api_key
    with pytest.raises(ValidationError) as e:
        Resource.model_validate(data)
    assert "api_key 不能为空" in str(e.value)


def test_whitespace_only_product_is_treated_as_absent():
    """`product=" "`（只填了空格）按**未声明产品**处理（与 `resource_ids_of_account` 的 strip 同尺）。"""
    with pytest.raises(ValidationError, match="api_key 不能为空"):
        Resource.model_validate(_res(product=" ", api_key=""))
    r = Resource.model_validate(_res(product=" ", api_key="sk-a"))
    assert r.product == " "          # 原值保留（不清洗用户输入），但校验按"未声明"走


# ============ ② product 非空 → account_ref 必填 ============

@pytest.mark.parametrize("account_ref", [None, "", "   "])
def test_product_requires_account_ref(account_ref):
    data = _res(product="buddy", api_key="")
    if account_ref is not None:
        data["account_ref"] = account_ref
    with pytest.raises(ValidationError) as e:
        Resource.model_validate(data)
    assert "account_ref" in str(e.value)


def test_product_resource_allows_empty_api_key():
    """产品资源的凭据在本地账号目录（铁律 1）：`api_key=""` 是**正常形态**。"""
    r = Resource.model_validate(_res(product="buddy", account_ref="acc-1", api_key=""))
    assert (r.product, r.account_ref, r.api_key) == ("buddy", "acc-1", "")


def test_product_resource_with_key_is_not_forbidden():
    """反向不禁止（`api_key` 同时存在 → 由出站适配器忽略，见 product_out 的 `_headers`）。

    刻意**不加**这条禁令：旧配置里可能已有 `product` + Key（§14.2 阶段一的过渡形态），
    多一条互斥规则就多一类"加载即拒绝"的迁移事故面。
    """
    r = Resource.model_validate(_res(product="zcode", account_ref="acc-1", api_key="sk-legacy"))
    assert r.api_key == "sk-legacy"


# ============ ③ 写盘路径 ============

def test_new_field_round_trips_through_dump():
    """`model_dump`（`save_config` / PUT 保存的同一路径）必须带上 `account_ref`，重启不丢。"""
    cfg = AppConfig.model_validate({
        "resources": [_res(product="buddy", account_ref="acc-1", api_key="")],
        "models": [{"name": "m", "endpoint": "chat",
                    "resources": [{"resource": "res-a", "model": "hy3"}]}]})
    dumped = cfg.model_dump(mode="json")
    assert dumped["resources"][0]["account_ref"] == "acc-1"
    again = AppConfig.model_validate(dumped)
    assert again.resources[0].account_ref == "acc-1"
    assert again.resources[0].api_key == ""


def test_error_message_is_actionable():
    """报错必须"看完就知道怎么办"（§22.5-2 的互斥契约不是猜谜）：两类错误各点出缺哪一项。"""
    with pytest.raises(ValidationError) as e1:
        Resource.model_validate(_res(api_key=""))
    assert "product" in str(e1.value) and "account_ref" in str(e1.value)
    with pytest.raises(ValidationError) as e2:
        Resource.model_validate(_res(product="qoder", api_key=""))
    assert "qoder" in str(e2.value) and "account_ref" in str(e2.value)
