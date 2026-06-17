from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


JSON_TYPE = JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql")


class Base(DeclarativeBase):
    pass


class RawDouyinOrder(Base):
    __tablename__ = "raw_douyin_orders"

    order_id: Mapped[str] = mapped_column(Text, primary_key=True)
    order_status: Mapped[str | None] = mapped_column(Text)
    sku_id: Mapped[str | None] = mapped_column(Text, index=True)
    product_name: Mapped[str | None] = mapped_column(Text)
    pay_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    create_order_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_amount_cent: Mapped[int | None] = mapped_column(Integer)
    owner_account_id: Mapped[str | None] = mapped_column(Text, index=True)
    owner_douyin_uid: Mapped[str | None] = mapped_column(Text)
    owner_account_name: Mapped[str | None] = mapped_column(Text, index=True)
    sale_role: Mapped[str | None] = mapped_column(Text)
    sale_channel: Mapped[str | None] = mapped_column(Text)
    intention_poi_id: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    source_run_id: Mapped[str | None] = mapped_column(Text, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RawDouyinOrderCoupon(Base):
    __tablename__ = "raw_douyin_order_coupons"

    coupon_id: Mapped[str] = mapped_column(Text, primary_key=True)
    order_id: Mapped[str] = mapped_column(
        Text, ForeignKey("raw_douyin_orders.order_id", ondelete="CASCADE"), index=True
    )
    order_item_id: Mapped[str | None] = mapped_column(Text)
    coupon_status: Mapped[str | None] = mapped_column(Text, index=True)
    coupon_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    coupon_refunded_cent: Mapped[int | None] = mapped_column(Integer)
    coupon_refund_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    source_run_id: Mapped[str | None] = mapped_column(Text, index=True)


class RawDouyinVerifyRecord(Base):
    __tablename__ = "raw_douyin_verify_records"

    verify_id: Mapped[str] = mapped_column(Text, primary_key=True)
    coupon_id: Mapped[str | None] = mapped_column(Text, index=True)
    verify_status: Mapped[str | None] = mapped_column(Text, index=True)
    verify_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    poi_id: Mapped[str | None] = mapped_column(Text, index=True)
    verify_store_name_raw: Mapped[str | None] = mapped_column(Text)
    sku_id: Mapped[str | None] = mapped_column(Text)
    product_name: Mapped[str | None] = mapped_column(Text)
    paid_amount_cent: Mapped[int | None] = mapped_column(Integer)
    cancel_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    source_run_id: Mapped[str | None] = mapped_column(Text, index=True)


class RawAwemeBinding(Base):
    __tablename__ = "raw_aweme_bindings"

    binding_key: Mapped[str] = mapped_column(Text, primary_key=True)
    douyin_id: Mapped[str | None] = mapped_column(Text, index=True)
    douyin_nickname: Mapped[str | None] = mapped_column(Text, index=True)
    account_id: Mapped[str | None] = mapped_column(Text, index=True)
    account_name: Mapped[str | None] = mapped_column(Text)
    poi_id: Mapped[str | None] = mapped_column(Text, index=True)
    binding_status: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    source_run_id: Mapped[str | None] = mapped_column(Text, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RawDouyinClue(Base):
    __tablename__ = "raw_douyin_clues"

    clue_row_key: Mapped[str] = mapped_column(Text, primary_key=True)
    clue_id: Mapped[str | None] = mapped_column(Text, index=True)
    source_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    source_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    create_time_detail: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    modify_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    name: Mapped[str | None] = mapped_column(Text)
    telephone: Mapped[str | None] = mapped_column(Text)
    enc_telephone: Mapped[str | None] = mapped_column(Text)
    product_id: Mapped[str | None] = mapped_column(Text, index=True)
    product_name: Mapped[str | None] = mapped_column(Text)
    order_id: Mapped[str | None] = mapped_column(Text, index=True)
    order_status: Mapped[str | None] = mapped_column(Text, index=True)
    follow_life_account_id: Mapped[str | None] = mapped_column(Text, index=True)
    follow_life_account_name: Mapped[str | None] = mapped_column(Text)
    auto_city_name: Mapped[str | None] = mapped_column(Text, index=True)
    auto_province_name: Mapped[str | None] = mapped_column(Text)
    author_nickname: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    source_file: Mapped[str | None] = mapped_column(Text)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DimStore(Base):
    __tablename__ = "dim_stores"

    store_id: Mapped[str] = mapped_column(Text, primary_key=True)
    store_name: Mapped[str] = mapped_column(Text)
    certified_subject_name: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DimStorePoiMapping(Base):
    __tablename__ = "dim_store_poi_mappings"
    __table_args__ = (
        UniqueConstraint("poi_id", name="uq_dim_store_poi_mappings_poi_id"),
        Index("ix_dim_store_poi_mappings_store_id", "store_id"),
    )

    store_id: Mapped[str] = mapped_column(
        Text, ForeignKey("dim_stores.store_id", ondelete="CASCADE"), primary_key=True
    )
    poi_id: Mapped[str] = mapped_column(Text, primary_key=True)
    poi_name: Mapped[str | None] = mapped_column(Text)
    mapping_source: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)


class DimSkuProductRule(Base):
    __tablename__ = "dim_sku_product_rules"

    sku_id: Mapped[str] = mapped_column(Text, primary_key=True)
    product_type: Mapped[str] = mapped_column(Text, index=True)
    product_name: Mapped[str | None] = mapped_column(Text)
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal("0"))
    is_service_product: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DimNonCommissionOwnerAccount(Base):
    __tablename__ = "dim_non_commission_owner_accounts"

    normalized_owner_account_name: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_account_name: Mapped[str] = mapped_column(Text, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    updated_by: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DimAwemeAccount(Base):
    __tablename__ = "dim_aweme_accounts"

    account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    nickname: Mapped[str | None] = mapped_column(Text, index=True)
    store_id: Mapped[str | None] = mapped_column(Text, ForeignKey("dim_stores.store_id"))
    binding_status: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SettlementOrderDetail(Base):
    __tablename__ = "settlement_order_details"
    __table_args__ = (
        Index("ix_settlement_order_details_sale_store_month", "sale_store_id", "sale_time"),
        Index("ix_settlement_order_details_verify_store_month", "verify_store_id", "verify_time"),
        Index("ix_settlement_order_details_product_type", "product_type"),
        Index("ix_settlement_order_details_relation_type", "relation_type"),
    )

    coupon_id: Mapped[str] = mapped_column(Text, primary_key=True)
    order_id: Mapped[str] = mapped_column(Text, index=True)
    verify_id: Mapped[str | None] = mapped_column(Text, index=True)
    sku_id: Mapped[str | None] = mapped_column(Text, index=True)
    owner_account_id: Mapped[str | None] = mapped_column(Text)
    owner_account_name: Mapped[str | None] = mapped_column(Text)
    product_type: Mapped[str] = mapped_column(Text)
    sale_store_id: Mapped[str | None] = mapped_column(Text, index=True)
    sale_store_name: Mapped[str | None] = mapped_column(Text)
    sale_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verify_store_id: Mapped[str | None] = mapped_column(Text, index=True)
    verify_store_name: Mapped[str | None] = mapped_column(Text)
    verify_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    relation_type: Mapped[str] = mapped_column(String(32), default="unknown")
    is_commissionable: Mapped[bool] = mapped_column(Boolean, default=False)
    is_refund_excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    paid_amount_cent: Mapped[int] = mapped_column(Integer, default=0)
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal("0"))
    receivable_commission_cent: Mapped[int] = mapped_column(Integer, default=0)
    payable_commission_cent: Mapped[int] = mapped_column(Integer, default=0)
    source_run_id: Mapped[str | None] = mapped_column(Text, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AggStoreRanking(Base):
    __tablename__ = "agg_store_ranking"

    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    product_type: Mapped[str] = mapped_column(Text, primary_key=True)
    store_id: Mapped[str] = mapped_column(Text, primary_key=True)
    store_name: Mapped[str | None] = mapped_column(Text)
    sales_order_count: Mapped[int] = mapped_column(Integer, default=0)
    self_sold_self_verified_count: Mapped[int] = mapped_column(Integer, default=0)
    self_sold_other_verified_count: Mapped[int] = mapped_column(Integer, default=0)
    other_sold_self_verified_count: Mapped[int] = mapped_column(Integer, default=0)
    self_verify_income_cent: Mapped[int] = mapped_column(Integer, default=0)
    effective_commission_income_cent: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AggStoreMonthlySettlement(Base):
    __tablename__ = "agg_store_monthly_settlement"

    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    store_id: Mapped[str] = mapped_column(Text, primary_key=True)
    product_type: Mapped[str] = mapped_column(Text, primary_key=True)
    estimated_receivable_commission_cent: Mapped[int] = mapped_column(Integer, default=0)
    commissionable_total_cent: Mapped[int] = mapped_column(Integer, default=0)
    estimated_payable_commission_cent: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class JobRun(Base):
    __tablename__ = "job_runs"

    job_id: Mapped[str] = mapped_column(Text, primary_key=True)
    job_name: Mapped[str] = mapped_column(Text, index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)


class SyncSetting(Base):
    __tablename__ = "sync_settings"

    setting_key: Mapped[str] = mapped_column(Text, primary_key=True)
    setting_value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"
    __table_args__ = (
        Index("ix_data_quality_issues_type_source", "issue_type", "source_run_id"),
        Index("ix_data_quality_issues_order_coupon", "order_id", "coupon_id"),
    )

    issue_id: Mapped[str] = mapped_column(Text, primary_key=True)
    issue_type: Mapped[str] = mapped_column(Text, index=True)
    order_id: Mapped[str | None] = mapped_column(Text, index=True)
    coupon_id: Mapped[str | None] = mapped_column(Text, index=True)
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    message: Mapped[str] = mapped_column(Text)
    raw_context_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    source_run_id: Mapped[str | None] = mapped_column(Text, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClueCenterOrder(Base):
    __tablename__ = "clue_center_orders"

    order_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_clue_ids: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list)
    source_clue_count: Mapped[int] = mapped_column(Integer, default=0)
    canonical_clue_id: Mapped[str | None] = mapped_column(Text, index=True)
    lead_status: Mapped[str] = mapped_column(String(32), index=True)
    current_assignment_round_id: Mapped[str | None] = mapped_column(Text, index=True)
    current_round_no: Mapped[int] = mapped_column(Integer, default=1)
    current_round_status: Mapped[str] = mapped_column(String(32), index=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    assigned_at_source: Mapped[str] = mapped_column(Text, default="clue_create_time_detail")
    assigned_store_id: Mapped[str | None] = mapped_column(Text, index=True)
    assigned_store_name: Mapped[str | None] = mapped_column(Text)
    assigned_city: Mapped[str | None] = mapped_column(Text, index=True)
    assigned_province: Mapped[str | None] = mapped_column(Text)
    phone_masked: Mapped[str | None] = mapped_column(Text)
    phone_source: Mapped[str | None] = mapped_column(Text)
    product_id: Mapped[str | None] = mapped_column(Text, index=True)
    product_name: Mapped[str | None] = mapped_column(Text)
    product_type: Mapped[str | None] = mapped_column(Text, index=True)
    author_nickname: Mapped[str | None] = mapped_column(Text)
    follow_result: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    is_followed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_follow_success: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_store_id: Mapped[str | None] = mapped_column(Text, index=True)
    verified_store_name: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    is_self_store_verified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    reassign_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ClueAssignmentRound(Base):
    __tablename__ = "clue_assignment_rounds"
    __table_args__ = (
        UniqueConstraint("order_id", "round_no", name="uq_clue_assignment_rounds_order_round"),
    )

    assignment_round_id: Mapped[str] = mapped_column(Text, primary_key=True)
    order_id: Mapped[str] = mapped_column(Text, index=True)
    round_no: Mapped[int] = mapped_column(Integer, default=1)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    assigned_at_source: Mapped[str] = mapped_column(Text, default="clue_create_time_detail")
    assigned_store_id: Mapped[str | None] = mapped_column(Text, index=True)
    assigned_store_name: Mapped[str | None] = mapped_column(Text)
    followed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    follow_result: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    is_followed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_follow_success: Mapped[bool] = mapped_column(Boolean, default=False)
    round_status: Mapped[str] = mapped_column(String(32), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    reassign_reason: Mapped[str | None] = mapped_column(Text)
    reassigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_store_id: Mapped[str | None] = mapped_column(Text, index=True)
    verified_store_name: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    is_self_store_verified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ClueReassignRuleSetting(Base):
    __tablename__ = "clue_reassign_rule_settings"

    setting_key: Mapped[str] = mapped_column(Text, primary_key=True)
    reassign_sla_hours: Mapped[int | None] = mapped_column(Integer)
    updated_by: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
