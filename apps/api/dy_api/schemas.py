from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


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
    user_id: str | None = None
    display_name: str | None = None
    role: str = "admin"
    status: str = "active"
    is_initialized: bool = True
    store_ids: list[str] = Field(default_factory=list)


class AccountInitializeRequest(BaseModel):
    external_account_id: str
    certified_subject_name: str
    username: str
    password: str
    password_confirm: str
    display_name: str | None = None

    @field_validator("external_account_id", "certified_subject_name", "username", "password", "password_confirm")
    def non_empty_account_input(cls, value: str) -> str:
        value = " ".join(value.strip().split())
        if not value:
            raise ValueError("value is required")
        return value


class AccountStoreScopeRow(BaseModel):
    store_id: str
    store_name: str = ""


class AccountRow(BaseModel):
    user_id: str
    username: str
    external_account_id: str | None = None
    display_name: str
    role: Literal["admin", "viewer", "store"] = "store"
    status: Literal["active", "disabled"] = "active"
    is_initialized: bool = False
    stores: list[AccountStoreScopeRow] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AccountListData(BaseModel):
    rows: list[AccountRow]


class AccountUpsertRequest(BaseModel):
    username: str
    display_name: str
    role: Literal["admin", "viewer", "store"] = "store"
    status: Literal["active", "disabled"] = "active"
    external_account_id: str | None = None
    store_ids: list[str] = Field(default_factory=list)
    password: str | None = None
    password_confirm: str | None = None

    @field_validator("username", "display_name")
    def non_empty_user_input(cls, value: str) -> str:
        value = " ".join(value.strip().split())
        if not value:
            raise ValueError("value is required")
        return value


class AccountPasswordUpdateRequest(BaseModel):
    password: str
    password_confirm: str

    @field_validator("password", "password_confirm")
    def non_empty_password_input(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("password is required")
        return value


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


class SkuRuleLookupRequest(BaseModel):
    sku_ids: list[str] = Field(max_length=500)

    @field_validator("sku_ids")
    def normalize_sku_ids(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value.strip()]


class SkuRuleLookupData(BaseModel):
    rows: list[SkuRuleRow]
    missing_sku_ids: list[str] = Field(default_factory=list)
    duplicate_sku_ids: list[str] = Field(default_factory=list)


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


class NonCommissionOwnerAccountRow(BaseModel):
    owner_account_name: str
    normalized_owner_account_name: str
    is_active: bool = True
    updated_at: datetime | None = None
    updated_by: str | None = None


class NonCommissionOwnerAccountInput(BaseModel):
    owner_account_name: str

    @field_validator("owner_account_name")
    def normalize_owner_account_name_input(cls, value: str) -> str:
        return value.strip()


class NonCommissionOwnerAccountListData(BaseModel):
    rows: list[NonCommissionOwnerAccountRow]


class NonCommissionOwnerAccountBulkUpdateRequest(BaseModel):
    accounts: list[NonCommissionOwnerAccountInput] = Field(default_factory=list, max_length=500)


class NonCommissionOwnerAccountBulkUpdateResult(BaseModel):
    rows: list[NonCommissionOwnerAccountRow]
    updated_count: int
    job_id: str
    rebuild_status: Literal["queued", "running", "success", "failed"] = "queued"


class CommissionRuleSkuSummaryRow(BaseModel):
    sku_id: str
    product_name: str = ""
    commission_rate: float = 0


class CommissionRulesSummaryData(BaseModel):
    non_commission_owner_accounts: list[str] = Field(default_factory=list)
    commission_skus: list[CommissionRuleSkuSummaryRow] = Field(default_factory=list)


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
    auto_sync_enabled: bool = True
    backfill_skip_completed: bool = True


class SyncConfigUpdate(BaseModel):
    history_start: str | None = None
    history_end: str | None = None
    history_chunk_days: int | None = Field(default=None, ge=1, le=31)
    rolling_days: int | None = Field(default=None, ge=1, le=180)
    interval_seconds: int | None = Field(default=None, ge=300, le=604800)
    auto_sync_enabled: bool | None = None
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


class SyncScheduleData(BaseModel):
    auto_sync_enabled: bool = True
    latest_successful_sync_at: datetime | None = None
    next_scheduled_sync_at: datetime | None = None


class SyncAdminData(BaseModel):
    config: SyncConfigData
    progress: SyncProgressData
    schedule: SyncScheduleData
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


class ClueFilterMetadata(BaseModel):
    assigned_stores: list[StoreOption]
    assigned_cities: list[str]
    product_types: list[str]
    lead_statuses: list[str]
    round_statuses: list[str]


class ClueOverviewMetrics(BaseModel):
    total_clues: int = 0
    active_clues: int = 0
    follow_rate: float = 0
    follow_success_rate: float = 0
    self_store_verify_rate: float = 0
    pending_reassign_count: int = 0


class ClueAssignmentRoundRow(BaseModel):
    assignment_round_id: str
    order_id: str
    round_no: int = 1
    lead_status: str
    order_current_status: str = ""
    current_assignment_round_id: str | None = None
    current_round_no: int = 0
    current_round_status: str = ""
    current_assigned_store_id: str | None = None
    current_assigned_store_name: str | None = None
    is_current_round: bool = False
    round_effective_status: Literal["active", "inactive"] = "inactive"
    round_status: str
    assigned_at: datetime | None = None
    expires_at: datetime | None = None
    remaining_reassign_seconds: int | None = None
    assigned_store_id: str | None = None
    assigned_store_name: str | None = None
    phone_masked: str = ""
    product_type: str | None = None
    author_nickname: str | None = None
    followed_at: datetime | None = None
    follow_result: str
    reassign_reason: str | None = None
    reassigned_at: datetime | None = None
    verified_store_id: str | None = None
    verified_store_name: str | None = None
    verified_at: datetime | None = None
    is_self_store_verified: bool = False


class ClueAssignmentRoundData(BaseModel):
    rows: list[ClueAssignmentRoundRow]
    pagination: "Pagination"


class ClueOrderDetailData(BaseModel):
    order_id: str
    canonical_clue_id: str | None = None
    lead_status: str
    phone_masked: str = ""
    product_id: str | None = None
    product_name: str | None = None
    product_type: str | None = None
    author_nickname: str | None = None
    assigned_city: str | None = None
    assigned_province: str | None = None
    rounds: list[ClueAssignmentRoundRow] = Field(default_factory=list)


class ClueReassignRuleData(BaseModel):
    reassign_sla_hours: int | None = None
    updated_at: datetime | None = None
    updated_by: str | None = None


class ClueReassignRuleUpdate(BaseModel):
    reassign_sla_hours: int | None = None

    @field_validator("reassign_sla_hours")
    def validate_reassign_sla_hours(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value < 1 or value > 168:
            raise ValueError("reassign_sla_hours must be between 1 and 168")
        return value


class ClueRebuildResult(BaseModel):
    rebuilt_order_count: int = 0
    rebuilt_round_count: int = 0


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
