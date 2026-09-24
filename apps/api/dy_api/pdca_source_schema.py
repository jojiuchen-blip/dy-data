"""Explicit, nullable evidence projections for the standalone PDCA endpoint."""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class EvidenceRow(BaseModel):
    """No raw payload or undeclared fields may leave the evidence endpoint."""
    model_config = ConfigDict(extra='forbid')
    source_run_id: str | None = None
    source_observed_at: datetime | None = None


class OrderRow(EvidenceRow):
    """Order observations, including orders without coupons or redemptions."""
    kind: Literal['orders'] = 'orders'
    order_id: str
    sku_id: str | None = None
    product_name: str | None = None
    create_order_time: datetime | None = None
    pay_time: datetime | None = None
    sale_time: datetime | None = None
    paid_amount_cent: int | None = None
    source_receipt_amount_cent: int | None = None
    source_platform_discount_amount_cent: int | None = None
    order_receipt_candidate_cent: int | None = None
    owner_douyin_uid: str | None = None
    owner_account_name: str | None = None
    sale_role: str | None = None
    sale_channel: str | None = None
    order_status: str | None = None


class CouponRow(EvidenceRow):
    """Coupon evidence; amounts remain separate from order totals."""
    kind: Literal['coupons'] = 'coupons'
    coupon_id: str
    order_id: str
    coupon_status: str | None = None
    coupon_paid_amount_cent: int | None = None
    coupon_refunded_cent: int | None = None
    coupon_refund_time: datetime | None = None
    latest_refund_at: datetime | None = None


class VerificationRow(EvidenceRow):
    """Raw verification and cancellation evidence, not inferred success."""
    kind: Literal['verifications'] = 'verifications'
    verify_id: str
    coupon_id: str | None = None
    sku_id: str | None = None
    verify_status: str | None = None
    verify_time: datetime | None = None
    cancel_time: datetime | None = None
    poi_id: str | None = None
    verify_store_name_raw: str | None = None
    paid_amount_cent: int | None = None


class RefundRow(EvidenceRow):
    """Refund records without guessed reason or normalized-status interpretation."""
    kind: Literal['refunds'] = 'refunds'
    source_record_key: str
    order_id: str
    refund_id: str | None = None
    raw_refund_status: str | None = None
    refund_amount_cent: int | None = None
    refund_applied_at: datetime | None = None
    refund_completed_at: datetime | None = None


class SkuRow(EvidenceRow):
    """Current product mapping, not a historical whitelist snapshot."""
    kind: Literal['sku_rules'] = 'sku_rules'
    sku_id: str
    product_id: str | None = None
    product_scope: str | None = None
    product_type: str | None = None


class PoiRow(EvidenceRow):
    """Explicit POI-to-store association without inferred ownership."""
    kind: Literal['poi_mappings'] = 'poi_mappings'
    store_id: str
    poi_id: str


Row = Annotated[OrderRow | CouponRow | VerificationRow | RefundRow | SkuRow | PoiRow, Field(discriminator='kind')]


class PageData(BaseModel):
    """Bounded keyset page."""
    rows: list[Row]
    next_cursor: str | None
    has_more: bool


class PageMeta(BaseModel):
    """Observation limitations are mandatory, not optional warnings."""
    schema_version: Literal['pdca-source-observation-v1']
    dataset: str
    query_fingerprint: str
    period_start: datetime
    period_end_exclusive: datetime
    observed_through: datetime
    generated_at: datetime
    business_timezone: Literal['Asia/Shanghai'] = 'Asia/Shanghai'
    scope: Literal['order_creation_current_whitelist', 'current_dimensions']
    read_only: Literal[True] = True
    consistent_snapshot: Literal[False] = False
    collection_complete_through: None = None
    refund_reason_available: Literal[False] = False
    amount_semantics_verified: Literal[False] = False
    limitations: list[str]


class EvidencePage(BaseModel):
    """Standalone source contract; no changes to existing API envelopes."""
    data: PageData
    meta: PageMeta
