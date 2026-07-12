from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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


class UnactivatedStoreAccountRow(BaseModel):
    store_id: str
    store_name: str = ""
    certified_subject_name: str = ""
    account_ids: list[str] = Field(default_factory=list)
    poi_ids: list[str] = Field(default_factory=list)
    poi_names: list[str] = Field(default_factory=list)


class UnactivatedStoreAccountListData(BaseModel):
    rows: list[UnactivatedStoreAccountRow]


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


FeedbackCategory = Literal["experience", "data", "feature", "other"]


class FeedbackSubmissionRequest(BaseModel):
    category: FeedbackCategory = "experience"
    content: str = Field(min_length=1, max_length=2000)
    contact: str | None = Field(default=None, max_length=120)
    page_path: str | None = Field(default=None, max_length=240)

    @field_validator("content")
    def normalize_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content is required")
        return value

    @field_validator("contact", "page_path")
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.strip().split())
        return value or None


class FeedbackSubmissionResponseData(BaseModel):
    feedback_id: str
    category: FeedbackCategory
    status: Literal["new"] = "new"
    created_at: datetime


FeedbackStatus = Literal["new", "reviewed", "resolved", "ignored"]


class FeedbackRow(BaseModel):
    feedback_id: str
    category: FeedbackCategory
    content: str
    contact: str | None = None
    page_path: str | None = None
    user_id: str | None = None
    username: str | None = None
    user_role: str | None = None
    status: FeedbackStatus
    created_at: datetime


class FeedbackListData(BaseModel):
    rows: list[FeedbackRow]
    pagination: "Pagination"
    status_counts: dict[str, int] = Field(default_factory=dict)


class FeedbackStatusUpdateRequest(BaseModel):
    status: FeedbackStatus


class SkuRuleRow(BaseModel):
    sku_id: str
    product_name: str = ""
    product_scope: str = ""
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


class SyncWorkerStatusData(BaseModel):
    mode: str = "collect_and_settle"
    auto_sync_enabled: bool = True
    interval_seconds: int = 86400
    rolling_days: int = 30
    history_chunk_days: int = 1
    run_on_start: bool = True
    run_once: bool = False
    chunk_max_attempts: int = 2
    disabled_poll_seconds: int = 60
    active_job: JobRun | None = None
    latest_success: JobRun | None = None
    latest_failure: JobRun | None = None
    next_scheduled_sync_at: datetime | None = None


class SyncAdminData(BaseModel):
    config: SyncConfigData
    progress: SyncProgressData
    schedule: SyncScheduleData
    worker_status: SyncWorkerStatusData
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
    product_scopes: list[str] = Field(default_factory=list)
    product_scope_type_map: dict[str, list[str]] = Field(default_factory=dict)
    product_types: list[str]
    default_product_type: str = "all"
    sale_months: list[str]
    verify_months: list[str]


class ClueFilterMetadata(BaseModel):
    assigned_stores: list[StoreOption]
    assigned_provinces: list[str]
    assigned_cities: list[str]
    product_types: list[str]
    default_product_type: str = "all"
    lead_statuses: list[str]
    round_statuses: list[str]
    verification_statuses: list[str]


class ClueOverviewMetrics(BaseModel):
    total_clues: int = 0
    active_clues: int = 0
    follow_rate: float = 0
    follow_success_rate: float = 0
    verified_count: int = 0
    self_store_verify_rate: float = 0
    pending_reassign_count: int = 0


class ClueAssignmentRoundRow(BaseModel):
    assignment_round_id: str
    order_id: str
    round_no: int = 1
    lead_status: str
    order_current_status: str = ""
    store_display_status: str = ""
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
    product_name: str | None = None
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


class ClueFollowUpRequest(BaseModel):
    assignment_round_id: str
    follow_result: Literal["unreachable", "lost", "success"]
    note: str | None = None

    @field_validator("assignment_round_id")
    def non_empty_assignment_round_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("assignment_round_id is required")
        return value

    @field_validator("note")
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class ClueFollowUpRecordRow(BaseModel):
    follow_up_record_id: str
    order_id: str
    assignment_round_id: str
    round_no: int
    assigned_store_id: str | None = None
    follow_result: Literal["unreachable", "lost", "success"]
    note: str | None = None
    operator_user_id: str | None = None
    operator_username: str | None = None
    created_at: datetime


class ClueFollowUpResponseData(ClueFollowUpRecordRow):
    pass


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
    follow_up_records: list[ClueFollowUpRecordRow] = Field(default_factory=list)


class CluePhoneRevealData(BaseModel):
    order_id: str
    phone: str
    phone_masked: str


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


class ProductTypeVisibilityData(BaseModel):
    enabled: bool = False
    visible_product_scopes: list[str] = Field(default_factory=list)
    visible_product_types: list[str] = Field(default_factory=list)
    default_product_type: str = "all"
    available_product_scopes: list[str] = Field(default_factory=list)
    available_product_types: list[str] = Field(default_factory=list)
    product_scope_type_map: dict[str, list[str]] = Field(default_factory=dict)
    updated_at: datetime | None = None
    updated_by: str | None = None


class ProductTypeVisibilityUpdate(BaseModel):
    enabled: bool = False
    visible_product_scopes: list[str] = Field(default_factory=list, max_length=100)
    visible_product_types: list[str] = Field(default_factory=list, max_length=100)
    default_product_type: str = "all"

    @field_validator("visible_product_scopes", "visible_product_types")
    def normalize_product_values(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            product_value = " ".join(str(value).strip().split())
            if not product_value or product_value == "all" or product_value in seen:
                continue
            normalized.append(product_value)
            seen.add(product_value)
        return normalized

    @field_validator("default_product_type")
    def normalize_default_product_type(cls, value: str) -> str:
        product_type = " ".join(str(value).strip().split())
        return product_type or "all"


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
    product_scope: str = "all"
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
    product_scope: str = "all"
    product_type: str
    metrics: SettlementMetrics
    tables: SettlementTables


class OrderDetailRow(BaseModel):
    order_id: str
    coupon_id: str
    product_name: str = ""
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
    is_refund_excluded: bool = False
    paid_amount_cent: int = 0
    commission_rate: float = 0
    receivable_commission_cent: int = 0
    payable_commission_cent: int = 0


class Pagination(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


class ClueMasterLeadRow(BaseModel):
    canonical_clue_id: str | None = None
    order_id: str | None = None
    raw_order_status: str | None = None
    normalized_order_status: str
    lifecycle_status: str
    pool_location: str | None = None
    allocation_state: str
    current_assignment_round_id: str | None = None
    allocation_cycle_id: str | None = None
    ended_without_assignment: bool = False
    closed_at: datetime | None = None
    closed_reason: str | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    anchor_poi_id: str | None = None
    anchor_store_id: str | None = None
    anchor_source: str | None = None
    anchor_unavailable_reason: str | None = None
    anchor_province: str | None = None
    anchor_city: str | None = None
    anchor_city_code: str | None = None


class ClueMasterLeadData(BaseModel):
    rows: list[ClueMasterLeadRow] = Field(default_factory=list)
    pagination: Pagination


class StoreScoreSnapshotRunData(BaseModel):
    snapshot_run_id: str
    snapshot_date: date
    run_mode: str
    window_start: datetime
    window_end: datetime
    candidate_store_count: int = 0
    snapshot_count: int = 0
    triggered_by: str | None = None
    computed_at: datetime


class StoreScoreSnapshotRow(BaseModel):
    store_id: str
    city_code: str | None = None
    conversion_numerator: int = 0
    conversion_denominator: int = 0
    conversion_rate: float = 0
    conversion_value_source: str
    follow_24h_numerator: int = 0
    follow_24h_denominator: int = 0
    follow_24h_rate: float = 0
    follow_24h_value_source: str
    store_weight: float = 1
    composite_score: float = 0


class StoreScoreSnapshotData(BaseModel):
    run: StoreScoreSnapshotRunData | None = None
    rows: list[StoreScoreSnapshotRow] = Field(default_factory=list)
    pagination: Pagination


class StoreScoreRefreshRequest(BaseModel):
    lookback_days: int = Field(default=30, ge=1, le=365)
    min_samples: int = Field(default=20, ge=1, le=10000)


class StoreScoreRefreshResult(BaseModel):
    snapshot_run_id: str
    snapshot_count: int = 0


class ClueAllocationRuleScopeInput(BaseModel):
    scope_type: Literal["global", "city", "store_group", "anchor_store"]
    city_code: str | None = Field(default=None, max_length=128)
    store_group_id: str | None = Field(default=None, max_length=256)
    anchor_store_id: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def validate_scope_target(self) -> "ClueAllocationRuleScopeInput":
        targets = {
            "city": self.city_code,
            "store_group": self.store_group_id,
            "anchor_store": self.anchor_store_id,
        }
        if self.scope_type == "global":
            if any(target.strip() for target in targets.values() if target):
                raise ValueError("global scope cannot include a target")
            return self
        selected_target = targets[self.scope_type]
        if not selected_target or not selected_target.strip():
            raise ValueError(f"{self.scope_type} scope requires its target identifier")
        if any(target.strip() for name, target in targets.items() if name != self.scope_type and target):
            raise ValueError("a logical rule scope can only declare one target")
        return self


class ClueAllocationRuleScopeData(BaseModel):
    scope_type: Literal["global", "city", "store_group", "anchor_store"]
    city_code: str | None = None
    store_group_id: str | None = None
    anchor_store_id: str | None = None


class ClueAllocationRuleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    scope: ClueAllocationRuleScopeInput

    @field_validator("name")
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name is required")
        return normalized


class ClueAllocationStrategyConfigInput(BaseModel):
    strategy_type: Literal["sales_store_priority", "nearby_city_optimization", "city_fallback"]
    enabled: bool
    execution_order: int
    params: dict[str, Any] = Field(default_factory=dict)


class ClueAllocationStrategyConfigData(BaseModel):
    strategy_type: Literal["sales_store_priority", "nearby_city_optimization", "city_fallback"]
    enabled: bool
    execution_order: int
    params: dict[str, Any] = Field(default_factory=dict)


class ClueAllocationRuleVersionWrite(BaseModel):
    auto_expiry_enabled: bool | None = None
    first_follow_up_sla_hours: int | None = None
    protection_days: int | None = None
    conversion_weight: float | None = None
    follow_24h_weight: float | None = None
    lookback_days: int | None = None
    min_samples: int | None = None
    strategy_configs: list[ClueAllocationStrategyConfigInput] = Field(default_factory=list, max_length=10)


class ClueAllocationRuleVersionData(BaseModel):
    rule_version_id: str
    rule_id: str
    version_no: int
    status: Literal["draft", "published", "retired"]
    auto_expiry_enabled: bool | None = None
    first_follow_up_sla_hours: int | None = None
    protection_days: int | None = None
    conversion_weight: float | None = None
    follow_24h_weight: float | None = None
    lookback_days: int | None = None
    min_samples: int | None = None
    strategy_configs: list[ClueAllocationStrategyConfigData] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None
    retired_at: datetime | None = None


class ClueAllocationRuleData(BaseModel):
    rule_id: str
    name: str
    scope: ClueAllocationRuleScopeData
    created_at: datetime
    updated_at: datetime


class ClueAllocationRuleListData(BaseModel):
    rows: list[ClueAllocationRuleData] = Field(default_factory=list)
    pagination: Pagination


class ClueAllocationRuleDetailData(BaseModel):
    rule: ClueAllocationRuleData
    versions: list[ClueAllocationRuleVersionData] = Field(default_factory=list)


class ClueAllocationRuleVersionDeleteData(BaseModel):
    rule_version_id: str
    deleted: bool


class ClueStoreGroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    member_store_ids: list[str] = Field(default_factory=list, max_length=500)

    @field_validator("name")
    def normalize_group_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name is required")
        return normalized


class ClueStoreGroupMembersUpdate(BaseModel):
    member_store_ids: list[str] = Field(default_factory=list, max_length=500)


class ClueStoreGroupData(BaseModel):
    store_group_id: str
    name: str
    member_store_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ClueStoreGroupListData(BaseModel):
    rows: list[ClueStoreGroupData] = Field(default_factory=list)


class OrderDetailsData(BaseModel):
    rows: list[OrderDetailRow]
    pagination: Pagination


class SalesDashboardMetrics(BaseModel):
    total_sales_order_count: int = 0
    self_verify_order_count: int = 0
    self_verify_rate: float = 0
    total_verify_order_count: int = 0
    actual_verify_amount_cent: int = 0
    avg_verify_cycle_days: float | None = None


class SalesMetricRow(SalesDashboardMetrics):
    product_type: str


class SalesTrendRow(BaseModel):
    month: str
    order_count: int = 0
    verify_order_count: int = 0


class SalesCyclePoint(BaseModel):
    order_id: str
    cycle_days: float
    sale_time: datetime | None = None
    verify_time: datetime | None = None


class SalesCycleDistributionRow(BaseModel):
    product_type: str
    count: int = 0
    min_days: float | None = None
    q1_days: float | None = None
    median_days: float | None = None
    q3_days: float | None = None
    max_days: float | None = None
    avg_days: float | None = None
    sample_points: list[SalesCyclePoint] = Field(default_factory=list)


class SalesDashboardData(BaseModel):
    store: StoreOption
    month: str
    product_scope: str = "all"
    product_type: str
    metrics: SalesDashboardMetrics
    product_rows: list[SalesMetricRow] = Field(default_factory=list)
    trend_rows: list[SalesTrendRow] = Field(default_factory=list)
    cycle_rows: list[SalesCycleDistributionRow] = Field(default_factory=list)
    source_row_count: int = 0


def dump_model(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()
