from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ApiMeta(BaseModel):
    generated_at: datetime
    source: str


class ApiDefinition(BaseModel):
    key: str
    label: str
    description: str


class ApiEnvelope(BaseModel):
    data: Any
    definitions: list[ApiDefinition] = Field(default_factory=list)
    meta: ApiMeta


class LoginRequest(BaseModel):
    username: str
    password: str


class AdminUser(BaseModel):
    username: str


class SkuRuleRow(BaseModel):
    sku_id: str
    product_name: str = ""
    product_type: str = ""
    commission_rate: float = 0
    is_service_product: bool = True
    order_count: int = 0
    verified_coupon_count: int = 0


class SkuRuleListData(BaseModel):
    rows: list[SkuRuleRow]
    pagination: "Pagination"


class SkuRuleInput(BaseModel):
    sku_id: str
    product_type: str
    commission_rate: float = Field(ge=0, le=1)
    is_service_product: bool = True


class SkuRuleBulkUpdateRequest(BaseModel):
    rules: list[SkuRuleInput]


class SkuRuleBulkUpdateResult(BaseModel):
    updated_count: int
    job_id: str
    rebuild_status: Literal["queued", "running", "success", "failed"] = "queued"
    settlement_detail_count: int | None = None
    settlement_monthly_count: int | None = None


class StoreOption(BaseModel):
    store_id: str
    store_name: str


class JobRun(BaseModel):
    job_id: str
    job_name: str
    status: Literal["running", "success", "failed", "queued"]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    success_count: int = 0
    failed_count: int = 0
    error_message: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class SyncConfigData(BaseModel):
    history_start: str
    history_end: str = ""
    history_chunk_days: int = Field(ge=1, le=31)
    rolling_days: int = Field(ge=1, le=180)
    interval_seconds: int = Field(ge=300, le=604800)
    backfill_skip_completed: bool = True


class SyncConfigUpdate(BaseModel):
    history_start: str | None = None
    history_end: str | None = None
    history_chunk_days: int | None = Field(default=None, ge=1, le=31)
    rolling_days: int | None = Field(default=None, ge=1, le=180)
    interval_seconds: int | None = Field(default=None, ge=300, le=604800)
    backfill_skip_completed: bool | None = None


class SyncWindowData(BaseModel):
    start: str
    end: str
    timezone: str


class SyncProgressData(BaseModel):
    total_windows: int = 0
    completed_windows: int = 0
    running_jobs: int = 0
    failed_jobs: int = 0
    latest_completed_window: SyncWindowData | None = None


class SyncAdminData(BaseModel):
    config: SyncConfigData
    progress: SyncProgressData
    jobs: list[JobRun] = Field(default_factory=list)


class ManualSyncRequest(BaseModel):
    target: Literal[
        "all",
        "orders",
        "verify_records",
        "shop_pois",
        "aweme_bindings",
        "backend_aweme_export",
        "settlement",
    ]
    days: int | None = Field(default=None, ge=1, le=180)
    start: datetime | None = None
    end: datetime | None = None


class ManualSyncResult(BaseModel):
    job_id: str
    target: str
    window: SyncWindowData


class FilterMetadata(BaseModel):
    stores: list[StoreOption]
    product_types: list[str]
    sale_months: list[str]
    verify_months: list[str]


class StoreRankingRow(BaseModel):
    rank: int
    store_id: str
    store_name: str
    sales_order_count: int = 0
    self_sold_self_verified_count: int = 0
    self_sold_other_verified_count: int = 0
    other_sold_self_verified_count: int = 0
    self_verify_income_cent: int = 0
    effective_commission_income_cent: int = 0


class StoreRankingTotals(BaseModel):
    sales_order_count: int = 0
    self_verify_income_cent: int = 0
    effective_commission_income_cent: int = 0


class StoreRankingData(BaseModel):
    month: str
    product_type: str
    limit: int
    totals: StoreRankingTotals
    rows: list[StoreRankingRow]


class SettlementMetrics(BaseModel):
    estimated_receivable_commission_cent: int = 0
    commissionable_total_cent: int = 0
    estimated_payable_commission_cent: int = 0


class ReceivableCommissionRow(BaseModel):
    product_type: str
    verified_coupon_count: int = 0
    paid_amount_cent: int = 0
    commission_rate: float = 0
    commissionable_total_cent: int = 0
    estimated_receivable_commission_cent: int = 0


class PayableCommissionRow(BaseModel):
    product_type: str
    verified_coupon_count: int = 0
    paid_amount_cent: int = 0
    commission_rate: float = 0
    payable_commission_cent: int = 0


class NonCommissionOrderRow(BaseModel):
    product_type: str
    verified_coupon_count: int = 0
    paid_amount_cent: int = 0


class SettlementTables(BaseModel):
    receivable_commissions: list[ReceivableCommissionRow] = Field(default_factory=list)
    payable_commissions: list[PayableCommissionRow] = Field(default_factory=list)
    non_commission_orders: list[NonCommissionOrderRow] = Field(default_factory=list)


class MonthlySettlementData(BaseModel):
    store: StoreOption
    month: str
    product_type: str
    metrics: SettlementMetrics
    tables: SettlementTables


class OrderDetailRow(BaseModel):
    order_id: str
    coupon_id: str
    sku_id: str
    owner_account_id: str
    owner_account_name: str
    product_type: str
    sale_store_id: str
    sale_store_name: str
    sale_store_subject_name: str = ""
    sale_time: datetime | None = None
    is_verified: bool
    verify_store_id: str = ""
    verify_store_name: str = ""
    verify_store_subject_name: str = ""
    verify_time: datetime | None = None
    relation_type: Literal["same_store", "cross_store", "unverified", "unknown", ""]
    is_commissionable: bool | None = None
    paid_amount_cent: int = 0
    commission_rate: float = 0
    receivable_commission_cent: int = 0
    payable_commission_cent: int = 0


class Pagination(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


class OrderDetailsData(BaseModel):
    rows: list[OrderDetailRow]
    pagination: Pagination


def dump_model(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()
