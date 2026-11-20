"""Internal monthly fee trial response contracts, with explicit unknown amounts."""
from typing import Literal

from pydantic import BaseModel


class FeeTrialReason(BaseModel):
    code: str
    label: str
    coupon_count: int


class FeeTrialCoverage(BaseModel):
    scope_unresolved: bool
    source_success_days: int | None
    source_total_days: int | None
    reasons: list[FeeTrialReason]
    note: str


class FeeTrialSummary(BaseModel):
    calculated_fee_cent: int | None
    calculated_coupon_count: int
    pending_coupon_count: int
    excluded_coupon_count: int
    candidate_coupon_count: int
    coverage_complete: bool


class FeeTrialRow(BaseModel):
    coupon_id: str
    order_id: str | None
    store_id: str | None
    store_name: str | None
    product_type: str
    sku_id: str | None
    fee_amount_cent: int | None
    base_amount_cent: int | None
    fee_rate: str | None
    rule_version: str | None
    record_status: Literal["CALCULATED", "PENDING", "EXCLUDED"]
    reason_code: str | None
    reason: str | None


class FeeTrialData(BaseModel):
    month: str
    fee_direction: Literal["PROMOTION", "MANAGEMENT"]
    status: Literal["TRIAL"]
    summary: FeeTrialSummary
    coverage: FeeTrialCoverage
    list: list[FeeTrialRow]
    total: int
    page: int
    page_size: int


class FeeTrialStoreRow(FeeTrialSummary):
    store_id: str | None
    store_name: str


class FeeTrialStoresData(FeeTrialData):
    list: list[FeeTrialStoreRow]
