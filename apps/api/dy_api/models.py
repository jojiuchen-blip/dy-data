from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    event,
    ForeignKey,
    func,
    Identity,
    Index,
    Integer,
    JSON,
    Numeric,
    select,
    String,
    Text,
    UniqueConstraint,
    text,
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
    __table_args__ = (
        UniqueConstraint("order_id", name="uk_raw_douyin_orders_order_id"),
        Index("idx_raw_douyin_orders_status", "order_status_normalized"),
        Index("idx_raw_douyin_orders_sale_month", "sale_time"),
        Index(
            "idx_raw_douyin_orders_channel_owner",
            "sale_channel_normalized",
            "owner_account_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    order_id: Mapped[str] = mapped_column(Text, nullable=False)
    order_status: Mapped[str | None] = mapped_column(Text)
    order_status_raw: Mapped[str | None] = mapped_column(String(128))
    order_status_normalized: Mapped[str | None] = mapped_column(String(32))
    sku_id: Mapped[str | None] = mapped_column(Text, index=True)
    product_name: Mapped[str | None] = mapped_column(Text)
    pay_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    sale_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    create_order_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_amount_cent: Mapped[int | None] = mapped_column(Integer)
    order_paid_amount_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    owner_account_id: Mapped[str | None] = mapped_column(Text, index=True)
    owner_douyin_uid: Mapped[str | None] = mapped_column(Text)
    owner_account_name: Mapped[str | None] = mapped_column(Text, index=True)
    sale_role: Mapped[str | None] = mapped_column(Text)
    sale_channel: Mapped[str | None] = mapped_column(Text)
    sale_channel_raw: Mapped[str | None] = mapped_column(String(128))
    sale_channel_normalized: Mapped[str | None] = mapped_column(String(32))
    intention_poi_id: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    source_run_id: Mapped[str | None] = mapped_column(Text, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RawDouyinOrderCoupon(Base):
    __tablename__ = "raw_douyin_order_coupons"
    __table_args__ = (
        UniqueConstraint("coupon_id", name="uk_raw_douyin_order_coupons_coupon_id"),
        Index(
            "idx_raw_douyin_order_coupons_status", "coupon_status_normalized"
        ),
        Index("idx_raw_douyin_order_coupons_latest_refund", "latest_refund_at"),
        Index("idx_raw_douyin_order_coupons_raw_order", "raw_order_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    coupon_id: Mapped[str] = mapped_column(Text, nullable=False)
    order_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    raw_order_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=False
    )
    order_item_id: Mapped[str | None] = mapped_column(Text)
    coupon_status: Mapped[str | None] = mapped_column(Text, index=True)
    coupon_status_raw: Mapped[str | None] = mapped_column(String(128))
    coupon_status_normalized: Mapped[str | None] = mapped_column(String(32))
    coupon_paid_amount_cent: Mapped[int | None] = mapped_column(BigInteger)
    coupon_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    coupon_refunded_cent: Mapped[int | None] = mapped_column(Integer)
    coupon_refunded_amount_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    coupon_refund_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_refund_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    source_run_id: Mapped[str | None] = mapped_column(Text, index=True)


@event.listens_for(RawDouyinOrderCoupon, "before_insert")
def _populate_raw_coupon_internal_order_id(
    _mapper: Any,
    connection: Any,
    target: RawDouyinOrderCoupon,
) -> None:
    if target.raw_order_id is None:
        raw_order_id = connection.scalar(
            select(RawDouyinOrder.id).where(RawDouyinOrder.order_id == target.order_id)
        )
        if raw_order_id is None:
            raise ValueError(f"raw order does not exist: order_id={target.order_id}")
        target.raw_order_id = int(raw_order_id)


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
    follow_poi_id: Mapped[str | None] = mapped_column(Text, index=True)
    intention_poi_id: Mapped[str | None] = mapped_column(Text, index=True)
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
    standard_province: Mapped[str | None] = mapped_column(Text)
    standard_city: Mapped[str | None] = mapped_column(Text)
    city_code: Mapped[str | None] = mapped_column(Text, index=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    is_douyin_clue_applicable: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    participates_in_clue_allocation: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    location_source: Mapped[str | None] = mapped_column(Text)
    location_status: Mapped[str] = mapped_column(String(32), default="missing", index=True)
    location_status_note: Mapped[str | None] = mapped_column(Text)
    location_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        UniqueConstraint("external_account_id", name="uq_users_external_account_id"),
    )

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    username: Mapped[str] = mapped_column(Text, index=True)
    external_account_id: Mapped[str | None] = mapped_column(Text, index=True)
    display_name: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32), default="store", index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    is_initialized: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class UserStoreScope(Base):
    __tablename__ = "user_store_scopes"
    __table_args__ = (Index("ix_user_store_scopes_store_id", "store_id"),)

    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True
    )
    store_id: Mapped[str] = mapped_column(
        Text, ForeignKey("dim_stores.store_id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserFeedbackSubmission(Base):
    __tablename__ = "user_feedback_submissions"
    __table_args__ = (
        Index("ix_user_feedback_submissions_created_at", "created_at"),
        Index("ix_user_feedback_submissions_status", "status"),
        Index("ix_user_feedback_submissions_user_id", "user_id"),
    )

    feedback_id: Mapped[str] = mapped_column(Text, primary_key=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    content: Mapped[str] = mapped_column(Text)
    contact: Mapped[str | None] = mapped_column(Text)
    page_path: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(Text)
    username: Mapped[str | None] = mapped_column(Text)
    user_role: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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
    __table_args__ = (
        UniqueConstraint("sku_id", name="uk_dim_sku_product_rules_sku_id"),
        Index("idx_dim_sku_product_rules_product_id", "product_id"),
        Index("idx_dim_sku_product_rules_spu_id", "spu_id"),
        Index(
            "idx_dim_sku_product_rules_scope_type",
            "product_scope",
            "product_type",
        ),
        Index(
            "idx_dim_sku_product_rules_owner_status",
            "owner_account_id",
            "product_status_normalized",
        ),
        Index("idx_dim_sku_product_rules_active", "is_active_product"),
        Index("idx_dim_sku_product_rules_sync_run", "sync_run_id"),
        Index("idx_dim_sku_product_rules_last_synced", "last_synced_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    sku_id: Mapped[str] = mapped_column(String(128))
    sku_name: Mapped[str | None] = mapped_column(String(512))
    product_id: Mapped[str | None] = mapped_column(String(128))
    product_name: Mapped[str | None] = mapped_column(String(512))
    spu_id: Mapped[str | None] = mapped_column(String(128))
    product_scope: Mapped[str] = mapped_column(String(128), default="")
    product_type: Mapped[str] = mapped_column(String(128), default="")
    is_service_product: Mapped[bool] = mapped_column(Boolean, default=False)
    creator_account_id: Mapped[str | None] = mapped_column(String(128))
    creator_account_name: Mapped[str | None] = mapped_column(String(255))
    owner_account_id: Mapped[str | None] = mapped_column(String(128))
    owner_account_name: Mapped[str | None] = mapped_column(String(255))
    product_status_raw: Mapped[str | None] = mapped_column(String(128))
    product_status_normalized: Mapped[str | None] = mapped_column(String(32))
    is_active_product: Mapped[bool] = mapped_column(Boolean, default=False)
    sync_source: Mapped[str | None] = mapped_column(String(64))
    sync_run_id: Mapped[str | None] = mapped_column(String(128))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manual_modified_by: Mapped[str | None] = mapped_column(String(128))
    manual_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Compatibility-only until all settlement reads use immutable sku_fee_rule versions.
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SkuProductSyncHistory(Base):
    __tablename__ = "sku_product_sync_history"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id", name="uk_sku_product_sync_history_snapshot_id"
        ),
        Index(
            "idx_sku_product_sync_history_sku_observed", "sku_id", "observed_at"
        ),
        Index("idx_sku_product_sync_history_run", "sync_run_id"),
        Index("idx_sku_product_sync_history_product", "product_id"),
        Index("idx_sku_product_sync_history_owner", "owner_account_id"),
        Index("idx_sku_product_sync_history_payload", "payload_sha256"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    snapshot_id: Mapped[str] = mapped_column(String(128))
    sync_run_id: Mapped[str] = mapped_column(String(128))
    sku_id: Mapped[str] = mapped_column(String(128))
    product_id: Mapped[str | None] = mapped_column(String(128))
    spu_id: Mapped[str | None] = mapped_column(String(128))
    sku_name: Mapped[str | None] = mapped_column(String(512))
    product_name: Mapped[str | None] = mapped_column(String(512))
    creator_account_id: Mapped[str | None] = mapped_column(String(128))
    creator_account_name: Mapped[str | None] = mapped_column(String(255))
    owner_account_id: Mapped[str | None] = mapped_column(String(128))
    owner_account_name: Mapped[str | None] = mapped_column(String(255))
    product_status_raw: Mapped[str | None] = mapped_column(String(128))
    product_status_normalized: Mapped[str | None] = mapped_column(String(32))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SettlementScopeRule(Base):
    __tablename__ = "settlement_scope_rule"
    __table_args__ = (
        UniqueConstraint(
            "scope_rule_version", name="uk_settlement_scope_rule_version"
        ),
        UniqueConstraint(
            "idempotency_key_hash",
            "sale_channel_normalized",
            name="uk_settlement_scope_rule_idempotency_channel",
        ),
        UniqueConstraint(
            "effective_month",
            "owner_account_id",
            "sale_channel_normalized",
            name="uk_settlement_scope_rule_slot",
        ),
        CheckConstraint(
            "sale_channel_normalized IN ('live', 'short_video')",
            name="ck_settlement_scope_rule_sale_channel",
        ),
        Index("idx_settlement_scope_rule_active", "is_active", "effective_month"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    scope_rule_version: Mapped[str] = mapped_column(String(64))
    idempotency_key_hash: Mapped[str] = mapped_column(String(64))
    request_payload_sha256: Mapped[str] = mapped_column(String(64))
    effective_month: Mapped[str] = mapped_column(String(7))
    owner_account_id: Mapped[str] = mapped_column(String(128))
    sale_channel_normalized: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(128))
    change_reason: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SkuFeeRule(Base):
    __tablename__ = "sku_fee_rule"
    __table_args__ = (
        UniqueConstraint("rule_version", name="uk_sku_fee_rule_version"),
        UniqueConstraint(
            "idempotency_key_hash",
            "sku_id",
            name="uk_sku_fee_rule_idempotency_sku",
        ),
        UniqueConstraint(
            "sku_id", "effective_date", name="uk_sku_fee_rule_sku_date"
        ),
        CheckConstraint(
            "promotion_service_fee_rate >= 0 AND promotion_service_fee_rate <= 1",
            name="ck_sku_fee_rule_promotion_rate",
        ),
        CheckConstraint(
            "management_service_fee_rate >= 0 AND management_service_fee_rate <= 1",
            name="ck_sku_fee_rule_management_rate",
        ),
        CheckConstraint("rule_status IN (1, 2)", name="ck_sku_fee_rule_status"),
        Index("idx_sku_fee_rule_match", "sku_id", "rule_status", "effective_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    rule_version: Mapped[str] = mapped_column(String(64))
    idempotency_key_hash: Mapped[str] = mapped_column(String(64))
    request_payload_sha256: Mapped[str] = mapped_column(String(64))
    sku_id: Mapped[str] = mapped_column(String(128))
    sku_name_snapshot: Mapped[str | None] = mapped_column(String(512))
    product_scope_snapshot: Mapped[str] = mapped_column(String(128), default="")
    product_type_snapshot: Mapped[str] = mapped_column(String(128), default="")
    promotion_service_fee_rate: Mapped[Decimal] = mapped_column(
        Numeric(8, 6), default=Decimal("0")
    )
    management_service_fee_rate: Mapped[Decimal] = mapped_column(
        Numeric(8, 6), default=Decimal("0")
    )
    effective_date: Mapped[date] = mapped_column(Date)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rule_status: Mapped[int] = mapped_column(Integer, default=1)
    previous_rule_version: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(128))
    change_reason: Mapped[str] = mapped_column(String(512))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SkuFeeRuleImportBatch(Base):
    __tablename__ = "sku_fee_rule_import_batch"
    __table_args__ = (
        UniqueConstraint("batch_id", name="uk_sku_fee_rule_import_batch_id"),
        UniqueConstraint(
            "commit_idempotency_key_hash",
            name="uk_sku_fee_rule_import_batch_commit_key",
        ),
        CheckConstraint(
            "batch_status IN (1, 2, 3, 4, 5, 6)",
            name="ck_sku_fee_rule_import_batch_status",
        ),
        CheckConstraint(
            "commit_mode = 1", name="ck_sku_fee_rule_import_batch_commit_mode"
        ),
        CheckConstraint(
            "total_count >= 0 AND valid_count >= 0 AND success_count >= 0 "
            "AND failed_count >= 0",
            name="ck_sku_fee_rule_import_batch_counts",
        ),
        Index("idx_sku_fee_rule_import_batch_sha", "file_sha256"),
        Index("idx_sku_fee_rule_import_batch_effective_date", "effective_date"),
        Index(
            "idx_sku_fee_rule_import_batch_user_status", "uploaded_by", "batch_status"
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    batch_id: Mapped[str] = mapped_column(String(128))
    file_name: Mapped[str] = mapped_column(String(512))
    file_sha256: Mapped[str] = mapped_column(String(64))
    batch_status: Mapped[int] = mapped_column(Integer, default=1)
    commit_mode: Mapped[int] = mapped_column(Integer, default=1)
    effective_date: Mapped[date] = mapped_column(Date)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    valid_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by: Mapped[str] = mapped_column(String(128))
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    commit_idempotency_key_hash: Mapped[str | None] = mapped_column(String(64))
    commit_payload_sha256: Mapped[str | None] = mapped_column(String(64))
    result_file_key: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SkuFeeRuleImportRow(Base):
    __tablename__ = "sku_fee_rule_import_row"
    __table_args__ = (
        UniqueConstraint(
            "batch_id", "row_number", name="uk_sku_fee_rule_import_row_number"
        ),
        CheckConstraint("row_number > 0", name="ck_sku_fee_rule_import_row_number"),
        CheckConstraint(
            "validation_status IN (1, 2, 3, 4, 5)",
            name="ck_sku_fee_rule_import_row_status",
        ),
        CheckConstraint(
            "error_count >= 0", name="ck_sku_fee_rule_import_row_error_count"
        ),
        Index("idx_sku_fee_rule_import_row_sku", "sku_id"),
        Index(
            "idx_sku_fee_rule_import_row_status", "batch_id", "validation_status"
        ),
        Index("idx_sku_fee_rule_import_row_error_field", "error_field"),
        Index("idx_sku_fee_rule_import_row_error_code", "error_code"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    batch_id: Mapped[str] = mapped_column(String(128))
    row_number: Mapped[int] = mapped_column(Integer)
    sku_name: Mapped[str | None] = mapped_column(String(512))
    sku_id: Mapped[str | None] = mapped_column(String(128))
    promotion_service_fee_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    management_service_fee_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    validation_status: Mapped[int] = mapped_column(Integer, default=1)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    error_field: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(1000))
    validation_errors_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON_TYPE)
    created_rule_version: Mapped[str | None] = mapped_column(String(64))
    source_row_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


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


class DouyinRefundEvent(Base):
    __tablename__ = "douyin_refund_event"
    __table_args__ = (
        UniqueConstraint("refund_event_id", name="uk_douyin_refund_event_id"),
        CheckConstraint("refund_type IN (1, 2)", name="ck_douyin_refund_event_type"),
        CheckConstraint(
            "refund_status IN (1, 2, 3, 4)", name="ck_douyin_refund_event_status"
        ),
        CheckConstraint(
            "refund_amount_cent >= 0", name="ck_douyin_refund_event_amount"
        ),
        Index("idx_douyin_refund_event_coupon_time", "coupon_id", "occurred_at"),
        Index("idx_douyin_refund_event_order_time", "order_id", "occurred_at"),
        Index("idx_douyin_refund_event_source_run", "source_run_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    refund_event_id: Mapped[str] = mapped_column(String(128))
    order_id: Mapped[str] = mapped_column(String(128))
    coupon_id: Mapped[str | None] = mapped_column(String(128))
    refund_type: Mapped[int] = mapped_column(Integer)
    refund_status: Mapped[int] = mapped_column(Integer)
    refund_amount_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_run_id: Mapped[str | None] = mapped_column(String(128))
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    successful_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


@event.listens_for(DouyinRefundEvent, "before_insert")
@event.listens_for(DouyinRefundEvent, "before_update")
def _freeze_refund_success_observed_at(
    _mapper: Any,
    _connection: Any,
    target: DouyinRefundEvent,
) -> None:
    if target.refund_status == 2 and target.successful_observed_at is None:
        target.successful_observed_at = utcnow()


class SettlementFeeResult(Base):
    __tablename__ = "settlement_fee_result"
    __table_args__ = (
        UniqueConstraint("fee_result_id", name="uk_settlement_fee_result_id"),
        UniqueConstraint(
            "coupon_id",
            "fee_direction",
            "result_version",
            name="uk_settlement_fee_result_revision",
        ),
        CheckConstraint(
            "fee_direction IN (1, 2)", name="ck_settlement_fee_result_direction"
        ),
        CheckConstraint(
            "result_version > 0", name="ck_settlement_fee_result_version"
        ),
        CheckConstraint(
            "source_amount_cent >= 0 AND refunded_amount_cent >= 0 "
            "AND fee_base_cent >= 0 AND fee_amount_cent >= 0",
            name="ck_settlement_fee_result_amounts",
        ),
        CheckConstraint(
            "fee_rate >= 0 AND fee_rate <= 1",
            name="ck_settlement_fee_result_rate",
        ),
        CheckConstraint(
            "result_status IN (1, 2, 3)", name="ck_settlement_fee_result_status"
        ),
        Index(
            "idx_settlement_fee_result_month_store",
            "original_business_month",
            "fee_direction",
            "sale_store_id",
            "verify_store_id",
        ),
        Index(
            "idx_settlement_fee_result_product", "product_scope", "product_type"
        ),
        Index("idx_settlement_fee_result_rule", "rule_version"),
        Index(
            "idx_settlement_fee_result_match_date", "rule_match_date", "fee_direction"
        ),
        Index("idx_settlement_fee_result_calculation_run", "calculation_run_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    fee_result_id: Mapped[str] = mapped_column(String(128))
    coupon_id: Mapped[str] = mapped_column(String(128))
    order_id: Mapped[str] = mapped_column(String(128))
    fee_direction: Mapped[int] = mapped_column(Integer)
    result_version: Mapped[int] = mapped_column(Integer, default=1)
    original_business_month: Mapped[str] = mapped_column(String(7))
    rule_match_date: Mapped[date] = mapped_column(Date)
    sale_store_id: Mapped[str | None] = mapped_column(String(128))
    verify_store_id: Mapped[str | None] = mapped_column(String(128))
    sku_id: Mapped[str] = mapped_column(String(128))
    product_scope: Mapped[str] = mapped_column(String(128), default="")
    product_type: Mapped[str] = mapped_column(String(128), default="")
    sale_channel_normalized: Mapped[str] = mapped_column(String(32))
    source_amount_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    refunded_amount_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    fee_base_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    fee_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=Decimal("0"))
    fee_amount_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    rule_version: Mapped[str] = mapped_column(String(64))
    scope_rule_version: Mapped[str] = mapped_column(String(64))
    result_status: Mapped[int] = mapped_column(Integer, default=1)
    calculation_run_id: Mapped[str] = mapped_column(String(128))
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SettlementFeeResultCurrent(Base):
    __tablename__ = "settlement_fee_result_current"
    __table_args__ = (
        UniqueConstraint(
            "coupon_id",
            "fee_direction",
            name="uk_settlement_fee_result_current_slot",
        ),
        UniqueConstraint(
            "fee_result_id", name="uk_settlement_fee_result_current_result"
        ),
        CheckConstraint(
            "fee_direction IN (1, 2)",
            name="ck_settlement_fee_result_current_direction",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    coupon_id: Mapped[str] = mapped_column(String(128))
    fee_direction: Mapped[int] = mapped_column(Integer)
    fee_result_id: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SettlementFeeAdjustment(Base):
    __tablename__ = "settlement_fee_adjustment"
    __table_args__ = (
        UniqueConstraint(
            "adjustment_id", name="uk_settlement_fee_adjustment_id"
        ),
        CheckConstraint(
            "fee_direction IN (1, 2)",
            name="ck_settlement_fee_adjustment_direction",
        ),
        CheckConstraint(
            "adjustment_type IN (1, 2, 3, 4)",
            name="ck_settlement_fee_adjustment_type",
        ),
        Index("idx_settlement_fee_adjustment_original", "original_fee_result_id"),
        Index("idx_settlement_fee_adjustment_refund", "refund_event_id"),
        Index(
            "idx_settlement_fee_adjustment_posting",
            "adjustment_posting_month",
            "fee_direction",
        ),
        Index(
            "idx_settlement_fee_adjustment_coupon", "coupon_id", "occurred_at"
        ),
        Index("idx_settlement_fee_adjustment_rule", "rule_version"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    adjustment_id: Mapped[str] = mapped_column(String(128))
    original_fee_result_id: Mapped[str] = mapped_column(String(128))
    refund_event_id: Mapped[str | None] = mapped_column(String(128))
    coupon_id: Mapped[str] = mapped_column(String(128))
    order_id: Mapped[str] = mapped_column(String(128))
    fee_direction: Mapped[int] = mapped_column(Integer)
    original_business_month: Mapped[str] = mapped_column(String(7))
    adjustment_posting_month: Mapped[str] = mapped_column(String(7))
    adjustment_type: Mapped[int] = mapped_column(Integer)
    adjustment_base_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    adjustment_fee_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    rule_version: Mapped[str] = mapped_column(String(64))
    adjustment_reason: Mapped[str] = mapped_column(String(1000))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SettlementStatement(Base):
    __tablename__ = "settlement_statement"
    __table_args__ = (
        UniqueConstraint("statement_id", name="uk_settlement_statement_id"),
        UniqueConstraint(
            "store_id", "statement_month", name="uk_settlement_statement_store_month"
        ),
        UniqueConstraint(
            "lock_version", name="uk_settlement_statement_lock_version"
        ),
        CheckConstraint(
            "statement_status IN (1, 2, 3, 4)",
            name="ck_settlement_statement_status",
        ),
        CheckConstraint(
            "promotion_net_fee_cent = promotion_original_fee_cent + "
            "promotion_adjustment_fee_cent",
            name="ck_settlement_statement_promotion_net",
        ),
        CheckConstraint(
            "management_net_fee_cent = management_original_fee_cent + "
            "management_adjustment_fee_cent",
            name="ck_settlement_statement_management_net",
        ),
        Index(
            "idx_settlement_statement_status_month",
            "statement_status",
            "statement_month",
        ),
        Index("idx_settlement_statement_locked_at", "locked_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    statement_id: Mapped[str] = mapped_column(String(128))
    store_id: Mapped[str] = mapped_column(String(128))
    statement_month: Mapped[str] = mapped_column(String(7))
    statement_status: Mapped[int] = mapped_column(Integer, default=1)
    promotion_original_fee_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    promotion_adjustment_fee_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    promotion_net_fee_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    management_original_fee_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    management_adjustment_fee_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    management_net_fee_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    confirmed_by: Mapped[str | None] = mapped_column(String(128))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(128))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lock_version: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SettlementStatementLine(Base):
    __tablename__ = "settlement_statement_line"
    __table_args__ = (
        UniqueConstraint(
            "statement_line_id", name="uk_settlement_statement_line_id"
        ),
        UniqueConstraint(
            "statement_id",
            "fee_direction",
            "product_scope",
            "product_type",
            name="uk_settlement_statement_line_dimension",
        ),
        CheckConstraint(
            "fee_direction IN (1, 2)",
            name="ck_settlement_statement_line_direction",
        ),
        CheckConstraint(
            "original_entry_count >= 0 AND adjustment_entry_count >= 0",
            name="ck_settlement_statement_line_counts",
        ),
        CheckConstraint(
            "net_base_cent = original_base_cent + adjustment_base_cent",
            name="ck_settlement_statement_line_net_base",
        ),
        CheckConstraint(
            "net_fee_cent = original_fee_cent + adjustment_fee_cent",
            name="ck_settlement_statement_line_net_fee",
        ),
        Index(
            "idx_settlement_statement_line_statement", "statement_id", "fee_direction"
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    statement_line_id: Mapped[str] = mapped_column(String(128))
    statement_id: Mapped[str] = mapped_column(String(128))
    fee_direction: Mapped[int] = mapped_column(Integer)
    product_scope: Mapped[str] = mapped_column(String(128), default="")
    product_type: Mapped[str] = mapped_column(String(128), default="")
    original_entry_count: Mapped[int] = mapped_column(Integer, default=0)
    adjustment_entry_count: Mapped[int] = mapped_column(Integer, default=0)
    original_base_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    adjustment_base_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    net_base_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    original_fee_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    adjustment_fee_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    net_fee_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SettlementStatementEntry(Base):
    __tablename__ = "settlement_statement_entry"
    __table_args__ = (
        UniqueConstraint(
            "statement_entry_id", name="uk_settlement_statement_entry_id"
        ),
        UniqueConstraint(
            "source_type",
            "source_record_id",
            name="uk_settlement_statement_entry_source",
        ),
        CheckConstraint(
            "source_type IN (1, 2)", name="ck_settlement_statement_entry_source_type"
        ),
        CheckConstraint(
            "fee_direction IN (1, 2)",
            name="ck_settlement_statement_entry_direction",
        ),
        Index("idx_settlement_statement_entry_line", "statement_line_id"),
        Index(
            "idx_settlement_statement_entry_statement_order", "statement_id", "order_id"
        ),
        Index("idx_settlement_statement_entry_coupon", "coupon_id"),
        Index("idx_settlement_statement_entry_original", "original_fee_result_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    statement_entry_id: Mapped[str] = mapped_column(String(128))
    statement_id: Mapped[str] = mapped_column(String(128))
    statement_line_id: Mapped[str] = mapped_column(String(128))
    source_type: Mapped[int] = mapped_column(Integer)
    source_record_id: Mapped[str] = mapped_column(String(128))
    original_fee_result_id: Mapped[str] = mapped_column(String(128))
    coupon_id: Mapped[str] = mapped_column(String(128))
    order_id: Mapped[str] = mapped_column(String(128))
    fee_direction: Mapped[int] = mapped_column(Integer)
    original_business_month: Mapped[str] = mapped_column(String(7))
    statement_posting_month: Mapped[str] = mapped_column(String(7))
    product_scope: Mapped[str] = mapped_column(String(128), default="")
    product_type: Mapped[str] = mapped_column(String(128), default="")
    base_amount_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    fee_amount_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    rule_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AggStoreRanking(Base):
    __tablename__ = "agg_store_ranking"
    __table_args__ = (
        UniqueConstraint(
            "period_type",
            "period_key",
            "store_id",
            "product_scope",
            "product_type",
            name="uk_agg_store_ranking_slot",
        ),
        CheckConstraint(
            "period_type IN (1, 2)", name="ck_agg_store_ranking_period_type"
        ),
        CheckConstraint(
            "net_settlement_reference_cent = promotion_net_fee_cent - "
            "management_net_fee_cent",
            name="ck_agg_store_ranking_net_reference",
        ),
        Index(
            "idx_agg_store_ranking_period_fee",
            "period_type",
            "period_key",
            "promotion_net_fee_cent",
        ),
        Index(
            "idx_agg_store_ranking_period_sales",
            "period_type",
            "period_key",
            "sales_amount_cent",
        ),
        Index("idx_agg_store_ranking_month", "month"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    period_type: Mapped[int] = mapped_column(Integer, default=1)
    period_key: Mapped[str] = mapped_column(String(7))
    store_id: Mapped[str] = mapped_column(String(128))
    store_name: Mapped[str] = mapped_column(String(255), default="")
    product_scope: Mapped[str] = mapped_column(String(128), default="all")
    product_type: Mapped[str] = mapped_column(String(128), default="all")
    sales_order_count: Mapped[int] = mapped_column(Integer, default=0)
    sales_amount_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    verified_order_count: Mapped[int] = mapped_column(Integer, default=0)
    verified_amount_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    promotion_net_fee_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    management_net_fee_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    net_settlement_reference_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    projection_run_id: Mapped[str] = mapped_column(String(128))
    # Compatibility columns for the legacy read APIs during the staged cutover.
    month: Mapped[str] = mapped_column(String(7))
    self_sold_self_verified_count: Mapped[int] = mapped_column(Integer, default=0)
    self_sold_other_verified_count: Mapped[int] = mapped_column(Integer, default=0)
    other_sold_self_verified_count: Mapped[int] = mapped_column(Integer, default=0)
    self_verify_income_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    effective_commission_income_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AggStoreMonthlySettlement(Base):
    __tablename__ = "agg_store_monthly_settlement"
    __table_args__ = (
        UniqueConstraint(
            "month",
            "store_id",
            "product_scope",
            "product_type",
            name="uk_agg_store_monthly_settlement_slot",
        ),
        CheckConstraint(
            "statement_status IN (1, 2, 3, 4)",
            name="ck_agg_store_monthly_settlement_status",
        ),
        Index(
            "idx_agg_store_monthly_settlement_store_month", "store_id", "month"
        ),
        Index("idx_agg_store_monthly_settlement_status", "statement_status"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    month: Mapped[str] = mapped_column(String(7))
    store_id: Mapped[str] = mapped_column(String(128))
    product_scope: Mapped[str] = mapped_column(String(128), default="all")
    product_type: Mapped[str] = mapped_column(String(128), default="all")
    sales_order_count: Mapped[int] = mapped_column(Integer, default=0)
    sales_amount_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    verified_order_count: Mapped[int] = mapped_column(Integer, default=0)
    verified_amount_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    promotion_base_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    promotion_original_fee_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    promotion_adjustment_fee_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    promotion_net_fee_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    management_base_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    management_original_fee_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    management_adjustment_fee_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    management_net_fee_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    statement_status: Mapped[int] = mapped_column(Integer, default=1)
    projection_run_id: Mapped[str] = mapped_column(String(128))
    # Compatibility columns for the legacy read APIs during the staged cutover.
    estimated_receivable_commission_cent: Mapped[int] = mapped_column(
        BigInteger, default=0
    )
    commissionable_total_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    estimated_payable_commission_cent: Mapped[int] = mapped_column(
        BigInteger, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


@event.listens_for(AggStoreRanking, "before_insert")
def _fill_legacy_ranking_projection_fields(
    _mapper: Any, _connection: Any, target: AggStoreRanking
) -> None:
    if not target.period_key:
        target.period_key = target.month
    if not target.projection_run_id:
        target.projection_run_id = "legacy-compat"


@event.listens_for(AggStoreMonthlySettlement, "before_insert")
def _fill_legacy_monthly_projection_fields(
    _mapper: Any, _connection: Any, target: AggStoreMonthlySettlement
) -> None:
    if not target.projection_run_id:
        target.projection_run_id = "legacy-compat"


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = (
        Index(
            "uq_job_runs_product_sync_active_slot",
            "job_name",
            unique=True,
            sqlite_where=text(
                "job_name = 'product_sync' AND status IN ('queued', 'running')"
            ),
            postgresql_where=text(
                "job_name = 'product_sync' AND status IN ('queued', 'running')"
            ),
        ),
        Index(
            "uq_job_runs_product_sync_idempotency_key",
            "job_name",
            "idempotency_key_hash",
            unique=True,
            sqlite_where=text(
                "job_name = 'product_sync' AND idempotency_key_hash IS NOT NULL"
            ),
            postgresql_where=text(
                "job_name = 'product_sync' AND idempotency_key_hash IS NOT NULL"
            ),
        ),
    )

    job_id: Mapped[str] = mapped_column(Text, primary_key=True)
    job_name: Mapped[str] = mapped_column(Text, index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    idempotency_key_hash: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)


class SyncSetting(Base):
    __tablename__ = "sync_settings"

    setting_key: Mapped[str] = mapped_column(Text, primary_key=True)
    setting_value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ProductTypeVisibilitySetting(Base):
    __tablename__ = "product_type_visibility_settings"

    setting_key: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    visible_product_scopes: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list)
    visible_product_types: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list)
    default_product_type: Mapped[str] = mapped_column(Text, default="all")
    updated_by: Mapped[str | None] = mapped_column(Text)
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


class ClueMasterLead(Base):
    __tablename__ = "clue_master_leads"
    __table_args__ = (
        UniqueConstraint("source_clue_row_key", name="uq_clue_master_leads_source_clue_row_key"),
        UniqueConstraint("source_identity_key", name="uq_clue_master_leads_source_identity_key"),
        Index("ix_clue_master_leads_order_location", "order_id", "pool_location"),
        Index("ix_clue_master_leads_lifecycle_location", "lifecycle_status", "pool_location"),
        Index("ix_clue_master_leads_anchor_store", "anchor_store_id"),
    )

    lead_key: Mapped[str] = mapped_column(Text, primary_key=True)
    source_clue_row_key: Mapped[str] = mapped_column(Text)
    source_identity_key: Mapped[str] = mapped_column(Text)
    canonical_clue_id: Mapped[str | None] = mapped_column(Text, index=True)
    order_id: Mapped[str | None] = mapped_column(Text, index=True)
    raw_order_status: Mapped[str | None] = mapped_column(Text)
    normalized_order_status: Mapped[str] = mapped_column(String(32), default="unknown", index=True)
    status_source: Mapped[str] = mapped_column(String(32), default="clue")
    lifecycle_status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    pool_location: Mapped[str | None] = mapped_column(String(32), index=True)
    allocation_state: Mapped[str] = mapped_column(String(32), default="pending_allocation", index=True)
    current_assignment_round_id: Mapped[str | None] = mapped_column(Text, index=True)
    allocation_cycle_id: Mapped[str | None] = mapped_column(Text, index=True)
    ended_without_assignment: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    closed_reason: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    anchor_poi_id: Mapped[str | None] = mapped_column(Text, index=True)
    anchor_store_id: Mapped[str | None] = mapped_column(Text, index=True)
    anchor_source: Mapped[str | None] = mapped_column(Text)
    anchor_unavailable_reason: Mapped[str | None] = mapped_column(Text)
    anchor_province: Mapped[str | None] = mapped_column(Text)
    anchor_city: Mapped[str | None] = mapped_column(Text)
    anchor_city_code: Mapped[str | None] = mapped_column(Text, index=True)
    anchor_longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    anchor_latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ClueOrderStatusEvent(Base):
    __tablename__ = "clue_order_status_events"
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_clue_order_status_events_event_key"),
        Index("ix_clue_order_status_events_lead_observed", "lead_key", "observed_at"),
    )

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_key: Mapped[str] = mapped_column(Text, nullable=False)
    lead_key: Mapped[str] = mapped_column(Text, index=True)
    order_id: Mapped[str | None] = mapped_column(Text, index=True)
    raw_status: Mapped[str | None] = mapped_column(Text)
    normalized_status: Mapped[str] = mapped_column(String(32), index=True)
    status_source: Mapped[str] = mapped_column(String(32))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
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
    phone_plain: Mapped[str | None] = mapped_column(Text)
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
        UniqueConstraint(
            "lead_key",
            "execution_mode",
            "round_no",
            name="uq_clue_assignment_rounds_lead_execution_mode_round",
        ),
    )

    assignment_round_id: Mapped[str] = mapped_column(Text, primary_key=True)
    order_id: Mapped[str] = mapped_column(Text, index=True)
    lead_key: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("clue_master_leads.lead_key", ondelete="RESTRICT"),
        index=True,
    )
    rule_version_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("clue_allocation_rule_versions.rule_version_id", ondelete="RESTRICT"),
        index=True,
    )
    strategy_type: Mapped[str | None] = mapped_column(String(64), index=True)
    allocation_decision_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("clue_allocation_decisions.decision_id", ondelete="RESTRICT"),
        index=True,
    )
    allocation_cycle_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("clue_allocation_cycles.allocation_cycle_id", ondelete="RESTRICT"),
        index=True,
    )
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
    execution_mode: Mapped[str] = mapped_column(String(32), default="legacy", index=True)
    matured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    terminal_reason: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    first_sla_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    protection_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    protection_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    auto_expiry_enabled: Mapped[bool | None] = mapped_column(Boolean)
    first_follow_up_sla_hours: Mapped[int | None] = mapped_column(Integer)
    protection_days: Mapped[int | None] = mapped_column(Integer)
    reassign_reason: Mapped[str | None] = mapped_column(Text)
    reassigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_store_id: Mapped[str | None] = mapped_column(Text, index=True)
    verified_store_name: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    is_self_store_verified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ClueFollowUpRecord(Base):
    __tablename__ = "clue_follow_up_records"
    __table_args__ = (
        Index("ix_clue_follow_up_records_order_id", "order_id"),
        Index("ix_clue_follow_up_records_assignment_round_id", "assignment_round_id"),
        Index("ix_clue_follow_up_records_assigned_store_id", "assigned_store_id"),
        Index("ix_clue_follow_up_records_created_at", "created_at"),
    )

    follow_up_record_id: Mapped[str] = mapped_column(Text, primary_key=True)
    order_id: Mapped[str] = mapped_column(Text)
    assignment_round_id: Mapped[str] = mapped_column(Text)
    round_no: Mapped[int] = mapped_column(Integer)
    assigned_store_id: Mapped[str | None] = mapped_column(Text)
    follow_result: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
    operator_user_id: Mapped[str | None] = mapped_column(Text)
    operator_username: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    deleted_by_user_id: Mapped[str | None] = mapped_column(Text)
    deleted_by_username: Mapped[str | None] = mapped_column(Text)
    deletion_reason: Mapped[str | None] = mapped_column(Text)


class StoreScoreSnapshotRun(Base):
    __tablename__ = "store_score_snapshot_runs"
    __table_args__ = (
        UniqueConstraint("scheduled_key", name="uq_store_score_snapshot_runs_scheduled_key"),
        Index("ix_store_score_snapshot_runs_date_mode", "snapshot_date", "run_mode"),
    )

    snapshot_run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    run_mode: Mapped[str] = mapped_column(String(32), default="scheduled", index=True)
    scheduled_key: Mapped[str | None] = mapped_column(Text)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    candidate_store_count: Mapped[int] = mapped_column(Integer, default=0)
    snapshot_count: Mapped[int] = mapped_column(Integer, default=0)
    triggered_by: Mapped[str | None] = mapped_column(Text)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StoreScoreSnapshot(Base):
    __tablename__ = "store_score_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_run_id", "store_id", name="uq_store_score_snapshots_run_store"),
        Index("ix_store_score_snapshots_date_store", "snapshot_date", "store_id"),
        Index("ix_store_score_snapshots_city_date", "city_code", "snapshot_date"),
    )

    snapshot_id: Mapped[str] = mapped_column(Text, primary_key=True)
    snapshot_run_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("store_score_snapshot_runs.snapshot_run_id", ondelete="CASCADE"),
        index=True,
    )
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    run_mode: Mapped[str] = mapped_column(String(32), default="scheduled")
    store_id: Mapped[str] = mapped_column(Text, ForeignKey("dim_stores.store_id", ondelete="CASCADE"), index=True)
    city_code: Mapped[str | None] = mapped_column(Text, index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    conversion_numerator: Mapped[int] = mapped_column(Integer, default=0)
    conversion_denominator: Mapped[int] = mapped_column(Integer, default=0)
    conversion_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))
    conversion_value_source: Mapped[str] = mapped_column(String(32), default="cold_start_empty")
    follow_24h_numerator: Mapped[int] = mapped_column(Integer, default=0)
    follow_24h_denominator: Mapped[int] = mapped_column(Integer, default=0)
    follow_24h_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))
    follow_24h_value_source: Mapped[str] = mapped_column(String(32), default="cold_start_empty")
    conversion_weight: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal("0.7"))
    follow_24h_weight: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal("0.3"))
    store_weight: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal("1"))
    composite_score: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"), index=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClueStoreGroup(Base):
    __tablename__ = "clue_store_groups"
    __table_args__ = (UniqueConstraint("group_name", name="uq_clue_store_groups_group_name"),)

    store_group_id: Mapped[str] = mapped_column(Text, primary_key=True)
    group_name: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ClueStoreGroupMember(Base):
    __tablename__ = "clue_store_group_members"
    __table_args__ = (
        UniqueConstraint("store_id", name="uq_clue_store_group_members_store_id"),
        Index("ix_clue_store_group_members_store_id", "store_id"),
    )

    store_group_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("clue_store_groups.store_group_id", ondelete="CASCADE"),
        primary_key=True,
    )
    store_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("dim_stores.store_id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClueAllocationRule(Base):
    __tablename__ = "clue_allocation_rules"
    __table_args__ = (
        UniqueConstraint("scope_key", name="uq_clue_allocation_rules_scope_key"),
        Index("ix_clue_allocation_rules_scope", "scope_type", "scope_key"),
    )

    rule_id: Mapped[str] = mapped_column(Text, primary_key=True)
    rule_name: Mapped[str] = mapped_column(Text)
    scope_type: Mapped[str] = mapped_column(String(32), index=True)
    scope_key: Mapped[str] = mapped_column(Text)
    scope_city_code: Mapped[str | None] = mapped_column(Text, index=True)
    scope_store_group_id: Mapped[str | None] = mapped_column(Text, index=True)
    scope_anchor_store_id: Mapped[str | None] = mapped_column(Text, index=True)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ClueAllocationRuleVersion(Base):
    __tablename__ = "clue_allocation_rule_versions"
    __table_args__ = (
        UniqueConstraint("rule_id", "version_no", name="uq_clue_allocation_rule_versions_rule_version"),
        Index("ix_clue_allocation_rule_versions_rule_status", "rule_id", "status"),
        Index(
            "uq_clue_allocation_rule_versions_published",
            "rule_id",
            unique=True,
            sqlite_where=text("status = 'published'"),
            postgresql_where=text("status = 'published'"),
        ),
    )

    rule_version_id: Mapped[str] = mapped_column(Text, primary_key=True)
    rule_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("clue_allocation_rules.rule_id", ondelete="CASCADE"),
        index=True,
    )
    version_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    auto_expiry_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    first_follow_up_sla_hours: Mapped[int | None] = mapped_column(Integer)
    protection_days: Mapped[int | None] = mapped_column(Integer)
    conversion_weight: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    follow_24h_weight: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    lookback_days: Mapped[int | None] = mapped_column(Integer)
    min_samples: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)
    published_by: Mapped[str | None] = mapped_column(Text)
    retired_by: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ClueAllocationStrategyConfig(Base):
    __tablename__ = "clue_allocation_strategy_configs"
    __table_args__ = (Index("ix_clue_allocation_strategy_configs_version_order", "rule_version_id", "execution_order"),)

    strategy_config_id: Mapped[str] = mapped_column(Text, primary_key=True)
    rule_version_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("clue_allocation_rule_versions.rule_version_id", ondelete="CASCADE"),
        index=True,
    )
    strategy_type: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    execution_order: Mapped[int] = mapped_column(Integer)
    params_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ClueLeadRuleVersionBinding(Base):
    __tablename__ = "clue_lead_rule_version_bindings"
    __table_args__ = (Index("ix_clue_lead_rule_version_bindings_rule_version", "rule_version_id"),)

    lead_key: Mapped[str] = mapped_column(Text, primary_key=True)
    rule_version_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("clue_allocation_rule_versions.rule_version_id", ondelete="RESTRICT"),
    )
    scope_type: Mapped[str] = mapped_column(String(32), index=True)
    scope_key: Mapped[str] = mapped_column(Text)
    scope_resolution_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    rule_version_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClueAllocationDecision(Base):
    """Append-only audit event emitted for each allocation strategy evaluation."""

    __tablename__ = "clue_allocation_decisions"
    __table_args__ = (
        UniqueConstraint("attempt_key", name="uq_clue_allocation_decisions_attempt_key"),
        Index("ix_clue_allocation_decisions_lead_executed", "lead_key", "executed_at"),
        Index("ix_clue_allocation_decisions_order_executed", "order_id", "executed_at"),
        Index("ix_clue_allocation_decisions_rule_version", "rule_version_id"),
        Index("ix_clue_allocation_decisions_status", "decision_status"),
    )

    decision_id: Mapped[str] = mapped_column(Text, primary_key=True)
    attempt_key: Mapped[str] = mapped_column(Text)
    lead_key: Mapped[str] = mapped_column(
        Text,
        ForeignKey("clue_master_leads.lead_key", ondelete="RESTRICT"),
        index=True,
    )
    order_id: Mapped[str | None] = mapped_column(Text, index=True)
    rule_id: Mapped[str | None] = mapped_column(Text, index=True)
    rule_version_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("clue_allocation_rule_versions.rule_version_id", ondelete="RESTRICT"),
        index=True,
    )
    scope_type: Mapped[str | None] = mapped_column(String(32), index=True)
    scope_key: Mapped[str | None] = mapped_column(Text)
    strategy_type: Mapped[str] = mapped_column(String(64), index=True)
    execution_order: Mapped[int | None] = mapped_column(Integer)
    allocation_cycle_id: Mapped[str | None] = mapped_column(Text, index=True)
    execution_mode: Mapped[str] = mapped_column(String(32), default="formal", index=True)
    assignment_round_id: Mapped[str | None] = mapped_column(Text, index=True)
    round_no: Mapped[int | None] = mapped_column(Integer)
    selected_store_id: Mapped[str | None] = mapped_column(Text, index=True)
    selected_store_name: Mapped[str | None] = mapped_column(Text)
    decision_status: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    decision_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    actor: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ClueAllocationCycle(Base):
    __tablename__ = "clue_allocation_cycles"
    __table_args__ = (
        Index("ix_clue_allocation_cycles_mode_status", "execution_mode", "status"),
        Index("ix_clue_allocation_cycles_parent", "parent_cycle_id"),
        Index("uq_clue_allocation_cycles_preview_token_hash", "preview_token_hash", unique=True),
    )

    allocation_cycle_id: Mapped[str] = mapped_column(Text, primary_key=True)
    cycle_type: Mapped[str] = mapped_column(String(32), index=True)
    execution_mode: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    parent_cycle_id: Mapped[str | None] = mapped_column(Text, index=True)
    selected_lead_keys: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list)
    requested_lead_count: Mapped[int] = mapped_column(Integer, default=0)
    active_lead_count: Mapped[int] = mapped_column(Integer, default=0)
    planned_impact_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    actual_impact_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    actor: Mapped[str | None] = mapped_column(Text)
    privileged_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    preview_token_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class ClueHeadquartersPoolEntry(Base):
    __tablename__ = "clue_headquarters_pool_entries"
    __table_args__ = (
        Index("ix_clue_headquarters_pool_entries_lead_status", "lead_key", "status"),
        Index("ix_clue_headquarters_pool_entries_entered", "entered_at"),
        Index(
            "uq_clue_headquarters_pool_entries_active_lead",
            "lead_key",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )

    headquarters_pool_entry_id: Mapped[str] = mapped_column(Text, primary_key=True)
    lead_key: Mapped[str] = mapped_column(
        Text,
        ForeignKey("clue_master_leads.lead_key", ondelete="RESTRICT"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    reason: Mapped[str] = mapped_column(Text)
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    close_reason: Mapped[str | None] = mapped_column(Text)
    source_assignment_round_id: Mapped[str | None] = mapped_column(Text, index=True)
    source_decision_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("clue_allocation_decisions.decision_id", ondelete="RESTRICT"),
        index=True,
    )
    source_rule_version_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("clue_allocation_rule_versions.rule_version_id", ondelete="RESTRICT"),
        index=True,
    )
    allocation_cycle_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("clue_allocation_cycles.allocation_cycle_id", ondelete="RESTRICT"),
        index=True,
    )
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ClueAllocationAuditLog(Base):
    __tablename__ = "clue_allocation_audit_logs"
    __table_args__ = (
        Index("ix_clue_allocation_audit_logs_cycle_created", "allocation_cycle_id", "created_at"),
        Index("ix_clue_allocation_audit_logs_event_created", "event_type", "created_at"),
    )

    audit_log_id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    allocation_cycle_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("clue_allocation_cycles.allocation_cycle_id", ondelete="RESTRICT"),
        index=True,
    )
    actor: Mapped[str | None] = mapped_column(Text)
    privileged_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    before_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    after_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    detail_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
