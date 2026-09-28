"""Versioned, explicit evidence DTOs. Unknown is never replaced by zero."""
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from dy_api.pdca_source_schema import CouponRow, OrderRow, PoiRow, SkuRow


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SnapshotOrder(OrderRow):
    order_status_raw: str | None = None
    order_status_normalized: str | None = None
    updated_at: datetime | None = None
    purchase_quantity: None = None
    order_receipt_amount_cent: None = None
    payment_evidence: Literal['paid_by_cutoff', 'paid_after_cutoff', 'unknown']


class SnapshotCoupon(CouponRow):
    coupon_status_raw: str | None = None
    coupon_status_normalized: str | None = None
    coupon_updated_at: datetime | None = None


class VerificationEvent(StrictModel):
    kind: Literal['verification_events'] = 'verification_events'
    event_id: str
    verify_id: str
    order_id: str
    coupon_id: str
    sku_id: str | None = None
    event_type: Literal['verification', 'revocation', 'unknown']
    original_event_id: str | None = None
    effective_at: datetime | None
    within_business_cutoff: bool | None
    verify_status: str | None = None
    poi_id: str | None = None
    source_run_id: str | None = None
    source_observed_at: datetime | None = None
    history_complete: Literal[False] = False
    evidence_basis: Literal['current_verification_row'] = 'current_verification_row'


class RefundEvent(StrictModel):
    kind: Literal['refund_events'] = 'refund_events'
    refund_event_id: str
    order_id: str
    coupon_id: str | None = None
    refund_type: int
    refund_status: int
    refund_scope: Literal['partial', 'full', 'unknown']
    refund_amount_cent: int | None = None
    occurred_at: datetime | None = None
    effective_at: datetime | None = None
    within_business_cutoff: bool | None = None
    successful_observed_at: datetime | None = None
    source_run_id: str | None = None
    source_observed_at: datetime | None = None
    updated_at: datetime | None = None
    refunded_quantity: None = None
    after_verification: None = None
    history_complete: Literal[False] = False


class RawRefund(StrictModel):
    kind: Literal['raw_refunds'] = 'raw_refunds'
    source_record_key: str
    order_id: str
    refund_id: str | None = None
    raw_refund_status: str | None = None
    normalized_refund_status: int | None = None
    refund_amount_cent: int | None = None
    refund_applied_at: datetime | None = None
    refund_completed_at: datetime | None = None
    source_run_id: str | None = None
    source_observed_at: datetime | None = None
    gmt_modified: datetime | None = None
    amount_field_type: Literal['missing', 'null', 'number', 'string', 'boolean', 'object', 'array']
    completion_fields_present: list[Literal['refund_completed_at', 'completed_at', 'finish_time', 'refund_done_at', 'complete_time']]


class QualityIssue(StrictModel):
    kind: Literal['quality_issues'] = 'quality_issues'
    issue_id: str
    issue_type: str
    order_id: str | None = None
    coupon_id: str | None = None
    severity: str
    source_run_id: str | None = None
    created_at: datetime | None = None
    resolution_status: Literal['unknown'] = 'unknown'


class CollectionBatch(StrictModel):
    kind: Literal['collection_batches'] = 'collection_batches'
    job_id: str
    job_name: str
    job_kind: str | None = None
    parent_job_id: str | None = None
    status: str
    data_source: str | None = None
    config_version: str | None = None
    business_date: date | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    success_count: int | None = None
    failed_count: int | None = None
    rows_read: int | None = None
    rows_written: int | None = None
    collection_complete_through: None = None


class CollectionStage(StrictModel):
    kind: Literal['collection_stages'] = 'collection_stages'
    stage_run_id: str
    job_id: str
    stage_name: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    committed_at: datetime | None = None


SnapshotRow = Annotated[
    SnapshotOrder | SnapshotCoupon | VerificationEvent | RefundEvent | RawRefund |
    QualityIssue | CollectionBatch | CollectionStage | SkuRow | PoiRow,
    Field(discriminator='kind'),
]


class DatasetSummary(StrictModel):
    dataset: str
    row_count: int
    sha256: str
    collection_complete_through: None = None
    coverage_status: Literal['unverified'] = 'unverified'


class SnapshotMeta(StrictModel):
    schema_version: Literal['pdca-event-evidence-v2'] = 'pdca-event-evidence-v2'
    status_dictionary_version: Literal['pdca-status-evidence-v1'] = 'pdca-status-evidence-v1'
    snapshot_id: str
    as_of: datetime
    expires_at: datetime
    business_timezone: Literal['Asia/Shanghai'] = 'Asia/Shanghai'
    period_start: datetime
    period_end_exclusive: datetime
    observed_through: datetime
    sku_ids: list[str]
    scope_basis: Literal['explicit_sku_ids', 'current_sku_rules']
    rule_version: str
    quality_issue_scope: Literal['cohort', 'related_batches'] = 'related_batches'
    read_only: Literal[True] = True
    consistent_snapshot: Literal[True] = True
    snapshot_basis: Literal['read_only_transaction_frozen_projection'] = 'read_only_transaction_frozen_projection'
    collection_complete_through: None = None
    amount_semantics_verified: Literal[False] = False
    publishable: Literal[False] = False
    blocking_reasons: list[str]


class ManifestData(StrictModel):
    datasets: list[DatasetSummary]


class SnapshotManifest(StrictModel):
    data: ManifestData
    meta: SnapshotMeta


class SnapshotPageData(StrictModel):
    rows: list[SnapshotRow]
    dataset: str
    total_rows: int
    dataset_sha256: str
    next_cursor: str | None
    has_more: bool


class SnapshotPage(StrictModel):
    data: SnapshotPageData
    meta: SnapshotMeta
