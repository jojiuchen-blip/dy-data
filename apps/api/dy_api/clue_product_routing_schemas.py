"""HTTP contracts for product routing and explicit human management."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictRoutingModel(BaseModel):
    """Reject unrecognized management fields instead of ignoring them."""

    model_config = ConfigDict(extra="forbid")


class FollowUpPolicyPatch(StrictRoutingModel):
    """Optional protection settings; omitted fields keep the published value."""

    appointment_hours: int | None = Field(default=None, ge=1, le=8760, strict=True)
    further_follow_up_hours: int | None = Field(default=None, ge=1, le=8760, strict=True)
    unreachable_hours: int | None = Field(default=None, ge=1, le=8760, strict=True)
    pending_action: Literal["next", "close"] | None = None
    appointment_action: Literal["next", "close"] | None = None
    further_follow_up_action: Literal["next", "close"] | None = None
    unreachable_action: Literal["next", "close"] | None = None


class ProductRulePatch(FollowUpPolicyPatch):
    """A field patch for one product or the shared Jingcheng base."""

    first_follow_up_sla_hours: int | None = Field(default=None, ge=1, le=168, strict=True)
    follow_up_policy: FollowUpPolicyPatch | None = None


class ProductRoutingFilters(StrictRoutingModel):
    """The full-result selection used by cross-page product selection."""

    q: str = Field(default="", max_length=200)
    product_scope: Literal["all", "jingcheng", "byd"] = "all"


class ProductStoreListInput(StrictRoutingModel):
    """Per-product imported store codes, preserving leading zeros."""

    product_id: str = Field(min_length=1, max_length=256)
    store_ids: list[str] = Field(max_length=20000)


class ProductRoutingBatchRequest(StrictRoutingModel):
    """An explicit preview or commit, with independent product outcomes."""

    product_ids: list[str] = Field(default_factory=list)
    all_matching: bool = False
    filters: ProductRoutingFilters = Field(default_factory=ProductRoutingFilters)
    action: Literal["publish_list", "publish_rule", "enable", "disable"]
    store_ids: list[str] | None = Field(default=None, max_length=20000)
    lists: list[ProductStoreListInput] | None = None
    rules: ProductRulePatch | None = None
    authorization_note: str | None = Field(default=None, max_length=2000)
    expected_list_versions: dict[str, str | None] | None = None
    preview: bool = True

    @model_validator(mode="after")
    def validate_selection(self) -> "ProductRoutingBatchRequest":
        """Keep selection and imported-list precedence unambiguous."""
        if self.all_matching and self.product_ids:
            raise ValueError("all_matching 与 product_ids 不可同时使用")
        if not self.all_matching and not self.product_ids:
            raise ValueError("请选择商品")
        if self.store_ids is not None and self.lists is not None:
            raise ValueError("公共名单与按商品名单不可同时提交")
        if self.lists is not None:
            ids = [row.product_id.strip() for row in self.lists]
            if len(ids) != len(set(ids)):
                raise ValueError("按商品导入的商品 ID 不可重复")
        return self


class ProductRoutingGrantsRequest(StrictRoutingModel):
    """Replace only the selected product's explicit management grants."""

    user_ids: list[str] = Field(max_length=5000)


class SharedRoutingRuleRequest(StrictRoutingModel):
    """Preview or publish a base version without switching existing products."""

    rules: ProductRulePatch
    preview: bool = True
