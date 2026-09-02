from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
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
    event,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.orm.attributes import NO_VALUE


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
    payload_fingerprint: Mapped[str | None] = mapped_column(String(64))
    source_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observation_key: Mapped[str | None] = mapped_column(String(256))
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
    payload_fingerprint: Mapped[str | None] = mapped_column(String(64))
    source_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observation_key: Mapped[str | None] = mapped_column(String(256))


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
    payload_fingerprint: Mapped[str | None] = mapped_column(String(64))
    source_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observation_key: Mapped[str | None] = mapped_column(String(256))


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
    __table_args__ = (
        Index("ix_raw_douyin_clues_order_row_key", "order_id", "clue_row_key"),
        Index("ix_raw_douyin_clues_follow_poi_row_key", "follow_poi_id", "clue_row_key"),
        Index(
            "ix_raw_douyin_clues_intention_poi_row_key",
            "intention_poi_id",
            "clue_row_key",
        ),
    )

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
    source_run_id: Mapped[str | None] = mapped_column(Text, index=True)
    payload_fingerprint: Mapped[str | None] = mapped_column(String(64))
    source_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observation_key: Mapped[str | None] = mapped_column(String(256))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RawDouyinRefundRecord(Base):
    """Raw evidence returned by the Douyin after-sale/refund API."""

    __tablename__ = "raw_douyin_refund_records"
    __table_args__ = (
        UniqueConstraint(
            "source_record_key",
            name="uk_raw_douyin_refund_record_source_record_key",
        ),
        Index(
            "idx_raw_douyin_refund_record_order_observed",
            "order_id",
            "source_observed_at",
        ),
        Index("idx_raw_douyin_refund_record_refund_id", "refund_id"),
        Index("idx_raw_douyin_refund_record_source_run", "source_run_id"),
        CheckConstraint(
            "normalized_refund_status BETWEEN 0 AND 4",
            name="ck_raw_douyin_refund_record_normalized_status",
        ),
        CheckConstraint(
            "refund_amount_cent >= 0",
            name="ck_raw_douyin_refund_record_amount",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    source_record_key: Mapped[str] = mapped_column(String(128), nullable=False)
    account_id: Mapped[str | None] = mapped_column(String(64))
    order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    refund_id: Mapped[str | None] = mapped_column(String(128))
    raw_refund_status: Mapped[str | None] = mapped_column(String(128))
    normalized_refund_status: Mapped[int] = mapped_column(Integer, default=0)
    refund_amount_cent: Mapped[int | None] = mapped_column(BigInteger)
    refund_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refund_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_run_id: Mapped[str | None] = mapped_column(String(64))
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    gmt_create: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    gmt_modified: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


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
    cli_subject: Mapped[str] = mapped_column(
        Text, unique=True, index=True, default=lambda: uuid4().hex
    )
    auth_generation: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    __mapper_args__ = {"version_id_col": auth_generation}
    username: Mapped[str] = mapped_column(Text, index=True)
    external_account_id: Mapped[str | None] = mapped_column(Text, index=True)
    display_name: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32), default="store", index=True)
    store_scope_mode: Mapped[str] = mapped_column(String(16), default="specified", index=True)
    auth_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    is_initialized: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CliDeviceAuthorization(Base):
    __tablename__ = "cli_device_authorizations"

    device_authorization_id: Mapped[str] = mapped_column(Text, primary_key=True)
    device_code_hash: Mapped[str] = mapped_column(Text, unique=True, index=True)
    user_code_hash: Mapped[str] = mapped_column(Text, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    scope: Mapped[str] = mapped_column(Text, default="cli:read")
    user_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    username: Mapped[str | None] = mapped_column(Text)
    auth_type: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CliRefreshToken(Base):
    __tablename__ = "cli_refresh_tokens"

    refresh_token_id: Mapped[str] = mapped_column(Text, primary_key=True)
    family_id: Mapped[str] = mapped_column(Text, index=True, default=lambda: uuid4().hex)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, index=True)
    user_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    username: Mapped[str] = mapped_column(Text)
    auth_type: Mapped[str] = mapped_column(String(32))
    authorization_fingerprint: Mapped[str] = mapped_column(Text)
    issued_auth_generation: Mapped[int | None] = mapped_column(Integer)
    scope: Mapped[str] = mapped_column(Text, default="cli:read")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    replaced_by_token_id: Mapped[str | None] = mapped_column(Text)


class McpOAuthClient(Base):
    __tablename__ = "mcp_oauth_clients"

    client_id: Mapped[str] = mapped_column(Text, primary_key=True)
    environment: Mapped[str] = mapped_column(String(32), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class McpAuthorizationRequest(Base):
    __tablename__ = "mcp_authorization_requests"

    authorization_request_id: Mapped[str] = mapped_column(Text, primary_key=True)
    request_token_hash: Mapped[str] = mapped_column(Text, unique=True, index=True)
    client_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("mcp_oauth_clients.client_id", ondelete="CASCADE"),
        index=True,
    )
    environment: Mapped[str] = mapped_column(String(32), index=True)
    redirect_uri: Mapped[str] = mapped_column(Text)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(Boolean)
    state: Mapped[str | None] = mapped_column(Text)
    scopes: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list)
    code_challenge: Mapped[str] = mapped_column(Text)
    resource: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    code_hash: Mapped[str | None] = mapped_column(Text, unique=True, index=True)
    subject: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    username: Mapped[str | None] = mapped_column(Text)
    auth_type: Mapped[str | None] = mapped_column(String(32))
    authorization_fingerprint: Mapped[str | None] = mapped_column(Text)
    issued_auth_generation: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class McpAccessToken(Base):
    __tablename__ = "mcp_access_tokens"

    access_token_id: Mapped[str] = mapped_column(Text, primary_key=True)
    family_id: Mapped[str] = mapped_column(Text, index=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, index=True)
    client_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("mcp_oauth_clients.client_id", ondelete="CASCADE"),
        index=True,
    )
    environment: Mapped[str] = mapped_column(String(32), index=True)
    subject: Mapped[str] = mapped_column(Text, index=True)
    user_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    username: Mapped[str] = mapped_column(Text)
    auth_type: Mapped[str] = mapped_column(String(32))
    authorization_fingerprint: Mapped[str] = mapped_column(Text, default="")
    issued_auth_generation: Mapped[int | None] = mapped_column(Integer)
    scopes: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list)
    resource: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class McpRefreshToken(Base):
    __tablename__ = "mcp_refresh_tokens"

    refresh_token_id: Mapped[str] = mapped_column(Text, primary_key=True)
    family_id: Mapped[str] = mapped_column(Text, index=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, index=True)
    client_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("mcp_oauth_clients.client_id", ondelete="CASCADE"),
        index=True,
    )
    environment: Mapped[str] = mapped_column(String(32), index=True)
    subject: Mapped[str] = mapped_column(Text, index=True)
    user_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    username: Mapped[str] = mapped_column(Text)
    auth_type: Mapped[str] = mapped_column(String(32))
    authorization_fingerprint: Mapped[str] = mapped_column(Text, default="")
    issued_auth_generation: Mapped[int | None] = mapped_column(Integer)
    scopes: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list)
    resource: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    replaced_by_token_id: Mapped[str | None] = mapped_column(Text)


class CliAuditEvent(Base):
    __tablename__ = "cli_audit_events"
    __table_args__ = (
        Index("ix_cli_audit_events_command_created", "command", "created_at"),
        Index("ix_cli_audit_events_operation_created", "operation", "created_at"),
    )

    audit_event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    operation: Mapped[str] = mapped_column(String(64), index=True)
    request_id: Mapped[str] = mapped_column(Text, index=True)
    command: Mapped[str] = mapped_column(Text, index=True)
    environment: Mapped[str] = mapped_column(String(32), default="production")
    channel: Mapped[str] = mapped_column(String(16), default="cli", index=True)
    user_id: Mapped[str | None] = mapped_column(Text, index=True)
    auth_type: Mapped[str | None] = mapped_column(String(32))
    authorization_scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    cli_version: Mapped[str | None] = mapped_column(String(64))
    schema_version: Mapped[str | None] = mapped_column(String(32))
    date_range: Mapped[list[str] | None] = mapped_column(JSON)
    requested_store_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    effective_store_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    returned_store_count: Mapped[int] = mapped_column(Integer, default=0)
    result_status: Mapped[int] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


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


class AccessPage(Base):
    __tablename__ = "access_pages"

    page_key: Mapped[str] = mapped_column(String(8), primary_key=True)
    page_name: Mapped[str] = mapped_column(Text)
    module_name: Mapped[str] = mapped_column(Text)
    route_patterns: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RolePagePermission(Base):
    __tablename__ = "role_page_permissions"

    role: Mapped[str] = mapped_column(String(32), primary_key=True)
    page_key: Mapped[str] = mapped_column(
        String(8), ForeignKey("access_pages.page_key", ondelete="CASCADE"), primary_key=True
    )
    is_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class UserPagePermissionOverride(Base):
    __tablename__ = "user_page_permission_overrides"
    __table_args__ = (Index("ix_user_page_permission_overrides_page_key", "page_key"),)

    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True
    )
    page_key: Mapped[str] = mapped_column(
        String(8), ForeignKey("access_pages.page_key", ondelete="CASCADE"), primary_key=True
    )
    effect: Mapped[str] = mapped_column(String(8))
    updated_by: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AccountPermissionAuditLog(Base):
    __tablename__ = "account_permission_audit_logs"
    __table_args__ = (
        Index("ix_account_permission_audit_logs_created_at", "created_at"),
        Index("ix_account_permission_audit_logs_target_user_id", "target_user_id"),
        Index("ix_account_permission_audit_logs_actor_user_id", "actor_user_id"),
    )

    audit_id: Mapped[str] = mapped_column(Text, primary_key=True)
    action: Mapped[str] = mapped_column(String(96), index=True)
    result: Mapped[str] = mapped_column(String(16), default="success")
    actor_user_id: Mapped[str | None] = mapped_column(Text)
    actor_username: Mapped[str] = mapped_column(Text)
    actor_role: Mapped[str] = mapped_column(String(32))
    target_user_id: Mapped[str | None] = mapped_column(Text)
    target_username: Mapped[str | None] = mapped_column(Text)
    before_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    after_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(User.cli_subject, "set", retval=True, active_history=True)
def _prevent_cli_subject_reassignment(
    _target: User, value: str, old_value: str | object, _initiator: object
) -> str:
    """Keep a user's opaque CLI subject stable for the lifetime of the identity."""
    if old_value is not NO_VALUE and old_value is not None and value != old_value:
        raise ValueError("cli_subject is immutable")
    return value


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
    source_run_id: Mapped[str | None] = mapped_column(Text)
    payload_fingerprint: Mapped[str | None] = mapped_column(String(64))
    source_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observation_key: Mapped[str | None] = mapped_column(String(256))


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
        Index("idx_dim_sku_product_rules_sync_status", "sync_status"),
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
    product_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active_product: Mapped[bool] = mapped_column(Boolean, default=False)
    sync_source: Mapped[str | None] = mapped_column(String(64))
    sync_run_id: Mapped[str | None] = mapped_column(String(128))
    sync_status: Mapped[str | None] = mapped_column(String(32))
    sync_error: Mapped[str | None] = mapped_column(Text)
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
        Index("idx_sku_product_sync_history_status", "sync_status"),
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
    product_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_status: Mapped[str | None] = mapped_column(String(32))
    sync_error: Mapped[str | None] = mapped_column(Text)
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


class SkuProductImportBatch(Base):
    __tablename__ = "sku_product_import_batch"
    __table_args__ = (
        UniqueConstraint("batch_id", name="uk_sku_product_import_batch_id"),
        CheckConstraint(
            "batch_status IN (1, 2, 3, 4, 5, 6)",
            name="ck_sku_product_import_batch_status",
        ),
        Index("idx_sku_product_import_batch_user_status", "uploaded_by", "batch_status"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), Identity(), primary_key=True
    )
    batch_id: Mapped[str] = mapped_column(String(128))
    file_name: Mapped[str] = mapped_column(String(512))
    file_sha256: Mapped[str] = mapped_column(String(64))
    batch_status: Mapped[int] = mapped_column(Integer, default=1)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    valid_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by: Mapped[str] = mapped_column(String(128))
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SkuProductImportRow(Base):
    __tablename__ = "sku_product_import_row"
    __table_args__ = (
        UniqueConstraint(
            "batch_id", "row_number", name="uk_sku_product_import_row_number"
        ),
        Index("idx_sku_product_import_row_sku", "sku_id"),
        Index("idx_sku_product_import_row_status", "batch_id", "validation_status"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), Identity(), primary_key=True
    )
    batch_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("sku_product_import_batch.batch_id", ondelete="CASCADE"),
    )
    row_number: Mapped[int] = mapped_column(Integer)
    sku_id: Mapped[str | None] = mapped_column(String(128))
    product_scope: Mapped[str | None] = mapped_column(String(128))
    product_type: Mapped[str | None] = mapped_column(String(128))
    keep_product_scope: Mapped[bool] = mapped_column(Boolean, default=False)
    keep_product_type: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_status: Mapped[int] = mapped_column(Integer, default=1)
    validation_errors_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON_TYPE)
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
        Index(
            "ix_settlement_order_details_order_verified_time",
            "order_id",
            "is_verified",
            "verify_time",
            "coupon_id",
        ),
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
    source_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload_fingerprint: Mapped[str | None] = mapped_column(String(64))
    observation_key: Mapped[str | None] = mapped_column(String(256))
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


class JobImpact(Base):
    """Durable, deduplicated change-capture record for incremental stages."""

    __tablename__ = "job_impacts"
    __table_args__ = (
        UniqueConstraint("impact_key", name="uk_job_impacts_impact_key"),
        Index("ix_job_impacts_entity_order", "entity_type", "entity_key", "id"),
        Index("ix_job_impacts_created", "created_at", "id"),
        Index("ix_job_impacts_source_run", "source_run_id"),
        Index("ix_job_impacts_source_run_id_id", "source_run_id", "id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    impact_key: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_key: Mapped[str] = mapped_column(String(256), nullable=False)
    change_kind: Mapped[str] = mapped_column(String(32), default="upsert")
    old_values_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    new_values_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    affected_closure_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    source_run_id: Mapped[str | None] = mapped_column(String(128))
    source_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClueMaterializationWorkItem(Base):
    """Stable keyset item materialized from one change-capture record."""

    __tablename__ = "clue_materialization_work_items"
    __table_args__ = (
        UniqueConstraint(
            "scope", "impact_id", name="uk_clue_materialization_work_scope_impact"
        ),
        Index(
            "ix_clue_materialization_work_scope_state",
            "scope",
            "state",
            "work_item_id",
        ),
        Index("ix_clue_materialization_work_impact", "impact_id"),
        Index(
            "ix_clue_materialization_work_lease",
            "state",
            "lease_expires_at",
        ),
        CheckConstraint(
            "state IN ('pending', 'processing', 'completed')",
            name="ck_clue_materialization_work_state",
        ),
    )

    work_item_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    scope: Mapped[str] = mapped_column(String(128), nullable=False)
    impact_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("job_impacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_key: Mapped[str] = mapped_column(String(256), nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="pending")
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    leased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_cursor: Mapped[str | None] = mapped_column(Text)
    raw_page_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    center_cursor: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClueMaterializationTarget(Base):
    """Durable cycle-level marker for bounded raw and center fanout."""

    __tablename__ = "clue_materialization_targets"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "cycle_id",
            "target_type",
            "target_key",
            name="uk_clue_materialization_target_cycle_key",
        ),
        Index(
            "ix_clue_materialization_target_cycle_type_key",
            "scope",
            "cycle_id",
            "target_type",
            "target_key",
        ),
        CheckConstraint(
            "target_type IN ('raw', 'center')",
            name="ck_clue_materialization_target_type",
        ),
    )

    target_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    scope: Mapped[str] = mapped_column(String(128), nullable=False)
    cycle_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JobImpactWatermark(Base):
    """Frozen upper bound and cursor for one bounded incremental pass."""

    __tablename__ = "job_impact_watermarks"
    __table_args__ = (
        Index("ix_job_impact_watermarks_upper_bound", "frozen_upper_bound_id"),
    )

    scope: Mapped[str] = mapped_column(String(128), primary_key=True)
    cycle_id: Mapped[str] = mapped_column(String(64), nullable=False)
    frozen_upper_bound_id: Mapped[int] = mapped_column(BigInteger, default=0)
    last_work_item_id: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


ClueMaterializationCheckpoint = JobImpactWatermark
ImpactWatermark = JobImpactWatermark


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
        UniqueConstraint(
            "coupon_id",
            "fee_direction",
            "calculation_run_id",
            name="uk_settlement_fee_result_calculation_run",
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
    input_fingerprint: Mapped[str | None] = mapped_column(String(64))
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
        UniqueConstraint(
            "refund_event_id",
            "original_fee_result_id",
            "fee_direction",
            name="uk_settlement_fee_adjustment_refund_result_direction",
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


class SettlementCarryforwardSource(Base):
    """Immutable fee delta captured when its event month cannot be changed."""

    __tablename__ = "settlement_carryforward_source"
    __table_args__ = (
        UniqueConstraint(
            "carryforward_source_id",
            name="uk_settlement_carryforward_source_id",
        ),
        UniqueConstraint(
            "source_event_key",
            "original_fee_result_id",
            "fee_direction",
            name="uk_settlement_carryforward_source_business",
        ),
        CheckConstraint(
            "source_event_type IN (1, 2)",
            name="ck_settlement_carryforward_source_event_type",
        ),
        CheckConstraint(
            "fee_direction IN (1, 2)",
            name="ck_settlement_carryforward_source_direction",
        ),
        CheckConstraint(
            "adjustment_type IN (1, 2, 3, 4)",
            name="ck_settlement_carryforward_source_adjustment_type",
        ),
        CheckConstraint(
            "(source_event_type = 1 AND refund_event_id IS NOT NULL "
            "AND verify_id IS NULL) OR "
            "(source_event_type = 2 AND refund_event_id IS NULL "
            "AND verify_id IS NOT NULL)",
            name="ck_settlement_carryforward_source_event_reference",
        ),
        Index(
            "idx_settlement_carryforward_source_pending",
            "store_id",
            "event_month",
            "occurred_at",
        ),
        Index(
            "idx_settlement_carryforward_source_original",
            "original_fee_result_id",
        ),
        Index(
            "idx_settlement_carryforward_source_refund",
            "refund_event_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    carryforward_source_id: Mapped[str] = mapped_column(String(128))
    source_event_type: Mapped[int] = mapped_column(Integer)
    source_event_key: Mapped[str] = mapped_column(String(255))
    original_fee_result_id: Mapped[str] = mapped_column(String(128))
    refund_event_id: Mapped[str | None] = mapped_column(String(128))
    verify_id: Mapped[str | None] = mapped_column(String(128))
    coupon_id: Mapped[str] = mapped_column(String(128))
    order_id: Mapped[str] = mapped_column(String(128))
    store_id: Mapped[str] = mapped_column(String(128))
    fee_direction: Mapped[int] = mapped_column(Integer)
    original_business_month: Mapped[str] = mapped_column(String(7))
    event_month: Mapped[str] = mapped_column(String(7))
    adjustment_type: Mapped[int] = mapped_column(Integer)
    adjustment_base_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    adjustment_fee_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    rule_version: Mapped[str] = mapped_column(String(64))
    carryforward_reason: Mapped[str] = mapped_column(String(1000))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )


class SettlementCarryforwardApplication(Base):
    """Versioned immutable posting of a carryforward source to one statement."""

    __tablename__ = "settlement_carryforward_application"
    __table_args__ = (
        UniqueConstraint(
            "carryforward_application_id",
            name="uk_settlement_carryforward_application_id",
        ),
        UniqueConstraint(
            "carryforward_source_id",
            "application_version",
            name="uk_settlement_carryforward_application_version",
        ),
        UniqueConstraint(
            "target_adjustment_id",
            name="uk_settlement_carryforward_application_adjustment",
        ),
        CheckConstraint(
            "application_version > 0",
            name="ck_settlement_carryforward_application_version",
        ),
        CheckConstraint(
            "target_statement_version > 0",
            name="ck_settlement_carryforward_application_statement_version",
        ),
        Index(
            "idx_settlement_carryforward_application_current",
            "carryforward_source_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
        Index(
            "idx_settlement_carryforward_application_statement",
            "target_statement_id",
        ),
        Index(
            "idx_settlement_carryforward_application_posting",
            "target_posting_month",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    carryforward_application_id: Mapped[str] = mapped_column(String(128))
    carryforward_source_id: Mapped[str] = mapped_column(String(128))
    target_statement_id: Mapped[str] = mapped_column(String(128))
    target_statement_version: Mapped[int] = mapped_column(Integer)
    target_adjustment_id: Mapped[str] = mapped_column(String(128))
    target_posting_month: Mapped[str] = mapped_column(String(7))
    application_version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    applied_by: Mapped[str] = mapped_column(String(128))
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )


class SettlementStatement(Base):
    __tablename__ = "settlement_statement"
    __table_args__ = (
        UniqueConstraint("statement_id", name="uk_settlement_statement_id"),
        UniqueConstraint(
            "store_id",
            "statement_month",
            "version_no",
            name="uk_settlement_statement_store_month_version",
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
        CheckConstraint(
            "store_snapshot_status IN "
            "('LIVE_CAPTURED', 'BACKFILLED_PROFILE', 'UNRESOLVED')",
            name="ck_settlement_statement_snapshot_status",
        ),
        Index(
            "idx_settlement_statement_status_month",
            "statement_status",
            "statement_month",
        ),
        Index("idx_settlement_statement_locked_at", "locked_at"),
        Index(
            "idx_settlement_statement_current_slot",
            "store_id",
            "statement_month",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
        Index("idx_settlement_statement_supersedes", "supersedes_statement_id"),
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
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    supersedes_statement_id: Mapped[str | None] = mapped_column(String(128))
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
    store_name_snapshot: Mapped[str | None] = mapped_column(String(255))
    sap_code_snapshot: Mapped[str | None] = mapped_column(String(128))
    store_snapshot_status: Mapped[str] = mapped_column(
        String(32), default="UNRESOLVED", server_default="UNRESOLVED"
    )
    store_snapshot_profile_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SettlementStatementSnapshotMigrationException(Base):
    """Track historical statement snapshots that cannot be backfilled safely."""

    __tablename__ = "settlement_statement_snapshot_migration_exception"
    __table_args__ = (
        UniqueConstraint(
            "statement_id",
            name="uk_settlement_statement_snapshot_exception_statement",
        ),
        CheckConstraint(
            "reason_code IN "
            "('NO_PRIOR_BASIC_PROFILE', "
            "'PROFILE_NOT_COMMITTED_BEFORE_STATEMENT', "
            "'AMBIGUOUS_PROFILE_TIME', 'INVALID_PROFILE_VERSION_ORDER')",
            name="ck_settlement_statement_snapshot_exception_reason",
        ),
        Index(
            "idx_settlement_statement_snapshot_exception_unresolved",
            "resolved_at",
            "reason_code",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    statement_id: Mapped[str] = mapped_column(String(128))
    reason_code: Mapped[str] = mapped_column(String(64))
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SettlementStatementEntrySnapshotMigrationException(Base):
    """Track historical statement entries whose display snapshot is incomplete."""

    __tablename__ = "settlement_statement_entry_snapshot_migration_exception"
    __table_args__ = (
        UniqueConstraint(
            "statement_entry_id",
            name="uk_statement_entry_snapshot_exception_entry",
        ),
        CheckConstraint(
            "reason_code IN ('MISSING_REQUIRED_ENTRY_SNAPSHOT')",
            name="ck_statement_entry_snapshot_exception_reason",
        ),
        Index(
            "idx_statement_entry_snapshot_exception_unresolved",
            "resolved_at",
            "reason_code",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    statement_entry_id: Mapped[str] = mapped_column(String(128))
    statement_id: Mapped[str] = mapped_column(String(128))
    reason_code: Mapped[str] = mapped_column(String(64))
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(String(1000))
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
            "statement_id",
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
    order_status_snapshot: Mapped[str | None] = mapped_column(String(64))
    coupon_status_snapshot: Mapped[str | None] = mapped_column(String(64))
    product_name_snapshot: Mapped[str | None] = mapped_column(String(512))
    sku_id_snapshot: Mapped[str | None] = mapped_column(String(128))
    sku_name_snapshot: Mapped[str | None] = mapped_column(String(512))
    sale_channel_snapshot: Mapped[str | None] = mapped_column(String(32))
    sale_store_id_snapshot: Mapped[str | None] = mapped_column(String(128))
    sale_store_snapshot: Mapped[str | None] = mapped_column(String(255))
    verify_store_id_snapshot: Mapped[str | None] = mapped_column(String(128))
    verify_store_snapshot: Mapped[str | None] = mapped_column(String(255))
    sale_time_snapshot: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verify_time_snapshot: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_amount_cent_snapshot: Mapped[int | None] = mapped_column(BigInteger)
    fee_rate_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    refund_at_snapshot: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    adjustment_type_snapshot: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SettlementStatementConfirmation(Base):
    __tablename__ = "settlement_statement_confirmation"
    __table_args__ = (
        UniqueConstraint(
            "statement_id",
            "fee_direction",
            name="uk_statement_confirmation_direction",
        ),
        UniqueConstraint("confirmation_id", name="uk_statement_confirmation_id"),
        UniqueConstraint(
            "idempotency_key_hash",
            name="uk_statement_confirmation_idempotency_key",
        ),
        CheckConstraint(
            "fee_direction IN (1, 2)",
            name="ck_statement_confirmation_direction",
        ),
        CheckConstraint(
            "confirmation_status IN (1, 2)",
            name="ck_statement_confirmation_status",
        ),
        Index("idx_statement_confirmation_by", "confirmed_by"),
        Index("idx_statement_confirmation_at", "confirmed_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    confirmation_id: Mapped[str] = mapped_column(String(128))
    statement_id: Mapped[str] = mapped_column(String(128))
    fee_direction: Mapped[int] = mapped_column(Integer)
    confirmation_status: Mapped[int] = mapped_column(Integer, default=1)
    confirmed_amount_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    confirmed_by: Mapped[str] = mapped_column(String(128))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    idempotency_key_hash: Mapped[str | None] = mapped_column(String(64))
    request_payload_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SettlementDispute(Base):
    __tablename__ = "settlement_dispute"
    __table_args__ = (
        UniqueConstraint("dispute_id", name="uk_settlement_dispute_id"),
        UniqueConstraint(
            "idempotency_key_hash", name="uk_settlement_dispute_idempotency_key"
        ),
        CheckConstraint("fee_direction IN (1, 2)", name="ck_settlement_dispute_direction"),
        CheckConstraint("dispute_type IN (1, 2, 3, 4)", name="ck_settlement_dispute_type"),
        CheckConstraint("status IN (1, 2, 3, 4, 5, 6)", name="ck_settlement_dispute_status"),
        Index("idx_settlement_dispute_statement", "statement_id"),
        Index("idx_settlement_dispute_store_month", "store_id", "statement_month"),
        Index("idx_settlement_dispute_status", "status"),
        Index("idx_settlement_dispute_submitted_by", "submitted_by"),
        Index("idx_settlement_dispute_processed_by", "processed_by"),
        Index("idx_settlement_dispute_result_statement", "result_statement_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    dispute_id: Mapped[str] = mapped_column(String(128))
    statement_id: Mapped[str] = mapped_column(String(128))
    store_id: Mapped[str] = mapped_column(String(128))
    statement_month: Mapped[str] = mapped_column(String(7))
    fee_direction: Mapped[int] = mapped_column(Integer)
    dispute_type: Mapped[int] = mapped_column(Integer)
    status: Mapped[int] = mapped_column(Integer, default=1)
    disputed_amount_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    description: Mapped[str] = mapped_column(Text)
    contact_name: Mapped[str] = mapped_column(String(128))
    contact_phone_ciphertext: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON_TYPE, default=list)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    result_statement_id: Mapped[str | None] = mapped_column(String(128))
    submitted_by: Mapped[str] = mapped_column(String(128))
    idempotency_key_hash: Mapped[str | None] = mapped_column(String(64))
    request_payload_sha256: Mapped[str | None] = mapped_column(String(64))
    processed_by: Mapped[str | None] = mapped_column(String(128))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SettlementDisputeOrder(Base):
    __tablename__ = "settlement_dispute_order"
    __table_args__ = (
        UniqueConstraint(
            "dispute_id",
            "order_id",
            "coupon_id",
            name="uk_settlement_dispute_order_scope",
        ),
        Index("idx_settlement_dispute_order_dispute", "dispute_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    dispute_id: Mapped[str] = mapped_column(String(128))
    order_id: Mapped[str] = mapped_column(String(128))
    coupon_id: Mapped[str | None] = mapped_column(String(128))
    disputed_amount_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class InvoiceRecord(Base):
    __tablename__ = "invoice_record"
    __table_args__ = (
        UniqueConstraint("invoice_id", name="uk_invoice_record_id"),
        UniqueConstraint(
            "store_id",
            "statement_month",
            "fee_direction",
            "version_no",
            name="uk_invoice_record_version",
        ),
        CheckConstraint("fee_direction IN (1, 2)", name="ck_invoice_record_direction"),
        CheckConstraint("invoice_status IN (1, 2, 3, 4)", name="ck_invoice_record_status"),
        CheckConstraint("source_type IN (1, 2, 3)", name="ck_invoice_record_source"),
        CheckConstraint("invoice_amount_cent >= 0", name="ck_invoice_record_amount"),
        Index(
            "idx_invoice_record_current_slot",
            "store_id",
            "statement_month",
            "fee_direction",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
        Index("idx_invoice_record_statement", "statement_id"),
        Index("idx_invoice_record_number", "invoice_number"),
        Index("idx_invoice_record_date", "invoice_date"),
        Index("idx_invoice_record_status", "invoice_status"),
        Index("idx_invoice_record_import_batch", "import_batch_id"),
        Index("idx_invoice_record_registered_by", "registered_by"),
        Index("idx_invoice_record_registered_at", "registered_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    invoice_id: Mapped[str] = mapped_column(String(128))
    store_id: Mapped[str] = mapped_column(String(128))
    statement_month: Mapped[str] = mapped_column(String(7))
    statement_id: Mapped[str] = mapped_column(String(128))
    fee_direction: Mapped[int] = mapped_column(Integer)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    is_tombstone: Mapped[bool] = mapped_column(Boolean, default=False)
    invoice_number: Mapped[str] = mapped_column(String(20))
    invoice_date: Mapped[date] = mapped_column(Date)
    invoice_amount_cent: Mapped[int] = mapped_column(BigInteger)
    invoice_status: Mapped[int] = mapped_column(Integer, default=1)
    source_type: Mapped[int] = mapped_column(Integer)
    import_batch_id: Mapped[str | None] = mapped_column(String(128))
    factory_deduction_date: Mapped[date | None] = mapped_column(Date)
    factory_deduction_amount_cent: Mapped[int | None] = mapped_column(BigInteger)
    registered_by: Mapped[str] = mapped_column(String(128))
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class InvoiceStatusEvent(Base):
    __tablename__ = "invoice_status_event"
    __table_args__ = (
        UniqueConstraint("event_id", name="uk_invoice_status_event_id"),
        CheckConstraint("event_type IN (1, 2, 3, 4)", name="ck_invoice_status_event_type"),
        CheckConstraint("to_status IN (1, 2, 3, 4)", name="ck_invoice_status_event_to"),
        Index("idx_invoice_status_event_invoice", "invoice_id"),
        Index("idx_invoice_status_event_operator", "operator_id"),
        Index("idx_invoice_status_event_import_batch", "import_batch_id"),
        Index("idx_invoice_status_event_occurred_at", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    event_id: Mapped[str] = mapped_column(String(128))
    invoice_id: Mapped[str] = mapped_column(String(128))
    event_type: Mapped[int] = mapped_column(Integer)
    from_status: Mapped[int | None] = mapped_column(Integer)
    to_status: Mapped[int] = mapped_column(Integer)
    operator_id: Mapped[str] = mapped_column(String(128))
    import_batch_id: Mapped[str | None] = mapped_column(String(128))
    result_reason: Mapped[str | None] = mapped_column(String(1000))
    business_date: Mapped[date | None] = mapped_column(Date)
    business_amount_cent: Mapped[int | None] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PromotionInvoice(Base):
    __tablename__ = "promotion_invoice"
    __table_args__ = (
        UniqueConstraint("invoice_id", name="uk_promotion_invoice_id"),
        UniqueConstraint(
            "idempotency_key_hash", name="uk_promotion_invoice_idempotency_key"
        ),
        UniqueConstraint(
            "physical_invoice_id",
            "version_no",
            name="uk_promotion_invoice_physical_version",
        ),
        CheckConstraint("version_no > 0", name="ck_promotion_invoice_version"),
        CheckConstraint(
            "version_kind IN (1, 2)", name="ck_promotion_invoice_version_kind"
        ),
        CheckConstraint(
            "invoice_status IN (2, 3, 4)", name="ck_promotion_invoice_status"
        ),
        CheckConstraint("invoice_amount_cent >= 0", name="ck_promotion_invoice_amount"),
        CheckConstraint("tax_rate_percent = 6", name="ck_promotion_invoice_tax_rate"),
        CheckConstraint(
            "net_amount_cent IS NULL OR net_amount_cent >= 0",
            name="ck_promotion_invoice_net_amount",
        ),
        CheckConstraint(
            "tax_amount_cent IS NULL OR tax_amount_cent >= 0",
            name="ck_promotion_invoice_tax_amount",
        ),
        CheckConstraint(
            "(net_amount_cent IS NULL AND tax_amount_cent IS NULL) OR "
            "(net_amount_cent IS NOT NULL AND tax_amount_cent IS NOT NULL "
            "AND ABS(net_amount_cent + tax_amount_cent - invoice_amount_cent) <= 1)",
            name="ck_promotion_invoice_amount_identity",
        ),
        Index(
            "idx_promotion_invoice_current_number",
            "invoice_number",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
        Index("idx_promotion_invoice_current", "store_id", "is_current"),
        Index(
            "idx_promotion_invoice_current_physical",
            "physical_invoice_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
        Index(
            "idx_promotion_invoice_unique_replacement_source",
            "replaces_invoice_id",
            unique=True,
            postgresql_where=text(
                "replaces_invoice_id IS NOT NULL AND version_kind = 1"
            ),
            sqlite_where=text(
                "replaces_invoice_id IS NOT NULL AND version_kind = 1"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    invoice_id: Mapped[str] = mapped_column(String(128))
    physical_invoice_id: Mapped[str] = mapped_column(
        String(128), default=lambda: f"physical-invoice-{uuid4().hex}"
    )
    store_id: Mapped[str] = mapped_column(String(128))
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    version_kind: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    is_tombstone: Mapped[bool] = mapped_column(Boolean, default=False)
    supersedes_invoice_id: Mapped[str | None] = mapped_column(String(128))
    replaces_invoice_id: Mapped[str | None] = mapped_column(String(128))
    invoice_number: Mapped[str] = mapped_column(String(20))
    invoice_date: Mapped[date] = mapped_column(Date)
    invoice_amount_cent: Mapped[int] = mapped_column(BigInteger)
    buyer_name: Mapped[str] = mapped_column(String(255))
    tax_rate_percent: Mapped[int] = mapped_column(Integer)
    filler_phone_ciphertext: Mapped[str | None] = mapped_column(Text)
    net_amount_cent: Mapped[int | None] = mapped_column(BigInteger)
    tax_amount_cent: Mapped[int | None] = mapped_column(BigInteger)
    invoice_status: Mapped[int] = mapped_column(Integer, default=2)
    registered_by: Mapped[str] = mapped_column(String(128))
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    idempotency_key_hash: Mapped[str | None] = mapped_column(String(64))
    request_payload_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PromotionInvoiceNumberRegistry(Base):
    """Global one-number-to-one-physical-invoice ownership registry."""

    __tablename__ = "promotion_invoice_number_registry"
    __table_args__ = (
        UniqueConstraint(
            "invoice_number", name="uk_promotion_invoice_number_registry_number"
        ),
        UniqueConstraint(
            "physical_invoice_id",
            name="uk_promotion_invoice_number_registry_physical",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    invoice_number: Mapped[str] = mapped_column(String(20))
    physical_invoice_id: Mapped[str] = mapped_column(String(128))
    first_invoice_id: Mapped[str] = mapped_column(String(128))
    store_id: Mapped[str] = mapped_column(String(128))
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class PromotionInvoiceReplacementSource(Base):
    """Many-to-one audit links from terminated invoices to one replacement."""

    __tablename__ = "promotion_invoice_replacement_source"
    __table_args__ = (
        UniqueConstraint(
            "replacement_invoice_id",
            "source_invoice_id",
            name="uk_promotion_invoice_replacement_source_pair",
        ),
        UniqueConstraint(
            "source_invoice_id",
            name="uk_promotion_invoice_replacement_source_source",
        ),
        Index(
            "idx_promotion_invoice_replacement_source_replacement",
            "replacement_invoice_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    replacement_invoice_id: Mapped[str] = mapped_column(String(128))
    source_invoice_id: Mapped[str] = mapped_column(String(128))
    source_physical_invoice_id: Mapped[str] = mapped_column(String(128))
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class PromotionInvoiceLifecycleEvent(Base):
    """Immutable record of red-flush or void facts completed outside the system."""

    __tablename__ = "promotion_invoice_lifecycle_event"
    __table_args__ = (
        UniqueConstraint(
            "lifecycle_event_id",
            name="uk_promotion_invoice_lifecycle_event_id",
        ),
        UniqueConstraint(
            "idempotency_key_hash",
            name="uk_promotion_invoice_lifecycle_idempotency",
        ),
        CheckConstraint(
            "event_type IN (1, 2)",
            name="ck_promotion_invoice_lifecycle_event_type",
        ),
        CheckConstraint(
            "read_version > 0",
            name="ck_promotion_invoice_lifecycle_read_version",
        ),
        Index(
            "idx_promotion_invoice_lifecycle_current_physical",
            "physical_invoice_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
        Index("idx_promotion_invoice_lifecycle_invoice", "invoice_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    lifecycle_event_id: Mapped[str] = mapped_column(String(128))
    physical_invoice_id: Mapped[str] = mapped_column(String(128))
    invoice_id: Mapped[str] = mapped_column(String(128))
    invoice_version: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(1000))
    read_version: Mapped[int] = mapped_column(Integer)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    operator_id: Mapped[str] = mapped_column(String(128))
    idempotency_key_hash: Mapped[str] = mapped_column(String(64))
    request_payload_sha256: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )


class PromotionInvoiceAllocation(Base):
    __tablename__ = "promotion_invoice_allocation"
    __table_args__ = (
        UniqueConstraint("allocation_id", name="uk_promotion_invoice_allocation_id"),
        UniqueConstraint(
            "invoice_id", "statement_id", name="uk_promotion_invoice_allocation_statement"
        ),
        Index(
            "idx_promotion_invoice_allocation_current_period",
            "store_id",
            "statement_month",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
        Index("idx_promotion_invoice_allocation_invoice", "invoice_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    allocation_id: Mapped[str] = mapped_column(String(128))
    invoice_id: Mapped[str] = mapped_column(String(128))
    store_id: Mapped[str] = mapped_column(String(128))
    statement_id: Mapped[str] = mapped_column(String(128))
    statement_month: Mapped[str] = mapped_column(String(7))
    settlement_batch_month: Mapped[str] = mapped_column(String(7))
    allocated_amount_cent: Mapped[int] = mapped_column(BigInteger)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class FinanceImportBatch(Base):
    __tablename__ = "finance_import_batch"
    __table_args__ = (
        UniqueConstraint("batch_id", name="uk_finance_import_batch_id"),
        UniqueConstraint(
            "upload_idempotency_key_hash",
            name="uk_finance_import_batch_upload_idempotency",
        ),
        CheckConstraint("import_type IN (1, 2, 3, 4)", name="ck_finance_import_batch_type"),
        CheckConstraint(
            "batch_status IN (1, 2, 3, 4, 5, 6, 7, 8, 9)",
            name="ck_finance_import_batch_status",
        ),
        Index("idx_finance_import_batch_type_month", "import_type", "statement_month"),
        Index("idx_finance_import_batch_file_sha256", "file_sha256"),
        Index("idx_finance_import_batch_normalized_sha256", "normalized_sha256"),
        Index("idx_finance_import_batch_status", "batch_status"),
        Index("idx_finance_import_batch_submitted_by", "submitted_by"),
        Index("idx_finance_import_batch_committed_by", "committed_by"),
        Index("idx_finance_import_batch_submitted_at", "submitted_at"),
        Index("idx_finance_import_batch_committed_at", "committed_at"),
        Index("idx_finance_import_batch_reverses", "reverses_batch_id"),
        Index(
            "uk_finance_import_batch_final_version",
            "import_type",
            "statement_month",
            "current_version",
            unique=True,
            postgresql_where=text("batch_status IN (5, 8, 9)"),
            sqlite_where=text("batch_status IN (5, 8, 9)"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    batch_id: Mapped[str] = mapped_column(String(128))
    import_type: Mapped[int] = mapped_column(Integer)
    statement_month: Mapped[str] = mapped_column(String(7))
    file_name: Mapped[str] = mapped_column(String(255))
    file_sha256: Mapped[str] = mapped_column(String(64))
    normalized_sha256: Mapped[str] = mapped_column(String(64))
    read_version: Mapped[int] = mapped_column(BigInteger)
    current_version: Mapped[int] = mapped_column(BigInteger)
    batch_status: Mapped[int] = mapped_column(Integer, default=1)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    success_rows: Mapped[int] = mapped_column(Integer, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, default=0)
    content_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    upload_idempotency_key_hash: Mapped[str | None] = mapped_column(String(64))
    upload_request_payload_sha256: Mapped[str | None] = mapped_column(String(64))
    reverses_batch_id: Mapped[str | None] = mapped_column(String(128))
    submitted_by: Mapped[str] = mapped_column(String(128))
    committed_by: Mapped[str | None] = mapped_column(String(128))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class FinanceImportRow(Base):
    __tablename__ = "finance_import_row"
    __table_args__ = (
        UniqueConstraint(
            "batch_id", "row_number", name="uk_finance_import_row_number"
        ),
        CheckConstraint("row_status IN (1, 2, 3, 4, 5)", name="ck_finance_import_row_status"),
        CheckConstraint(
            "reversal_effect_type IS NULL OR reversal_effect_type IN (1, 2)",
            name="ck_finance_import_row_reversal_effect",
        ),
        Index("idx_finance_import_row_business_key", "business_key"),
        Index("idx_finance_import_row_status", "row_status"),
        Index("idx_finance_import_row_target", "target_record_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    batch_id: Mapped[str] = mapped_column(String(128))
    row_number: Mapped[int] = mapped_column(Integer)
    business_key: Mapped[str] = mapped_column(String(512))
    normalized_payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    row_status: Mapped[int] = mapped_column(Integer, default=1)
    validation_errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON_TYPE, default=list)
    target_record_id: Mapped[str | None] = mapped_column(String(128))
    reversal_effect_type: Mapped[int | None] = mapped_column(Integer)
    reverses_target_record_id: Mapped[str | None] = mapped_column(String(128))
    previous_target_record_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SapSuggestion(Base):
    """Keep immutable store SAP suggestions and their processing versions."""

    __tablename__ = "sap_suggestion"
    __table_args__ = (
        UniqueConstraint("suggestion_id", name="uk_sap_suggestion_id"),
        UniqueConstraint(
            "store_id", "version_no", name="uk_sap_suggestion_store_version"
        ),
        UniqueConstraint(
            "idempotency_key_hash", name="uk_sap_suggestion_idempotency"
        ),
        CheckConstraint("version_no > 0", name="ck_sap_suggestion_version"),
        CheckConstraint(
            "suggestion_status IN (1, 2, 3, 4)",
            name="ck_sap_suggestion_status",
        ),
        Index(
            "idx_sap_suggestion_current",
            "store_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
        Index("idx_sap_suggestion_status", "suggestion_status"),
        Index("idx_sap_suggestion_submitted", "submitted_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    suggestion_id: Mapped[str] = mapped_column(String(128))
    store_id: Mapped[str] = mapped_column(String(128))
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    supersedes_suggestion_id: Mapped[str | None] = mapped_column(String(128))
    suggested_sap_code: Mapped[str] = mapped_column(String(128))
    suggestion_note: Mapped[str] = mapped_column(String(1000))
    suggestion_status: Mapped[int] = mapped_column(Integer, default=1)
    submitted_by: Mapped[str] = mapped_column(String(128))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    handled_by: Mapped[str | None] = mapped_column(String(128))
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handling_reason: Mapped[str | None] = mapped_column(String(1000))
    confirmed_profile_id: Mapped[str | None] = mapped_column(String(128))
    idempotency_key_hash: Mapped[str | None] = mapped_column(String(64))
    request_payload_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )


class StoreFinanceProfile(Base):
    """Keep immutable basic-information and SAP-confirmation versions per store."""

    __tablename__ = "store_finance_profile"
    __table_args__ = (
        UniqueConstraint("profile_id", name="uk_store_finance_profile_id"),
        UniqueConstraint(
            "store_id",
            "profile_type",
            "version_no",
            name="uk_store_finance_profile_version",
        ),
        CheckConstraint("profile_type IN (1, 2)", name="ck_store_finance_profile_type"),
        CheckConstraint("source_type IN (1, 2, 3)", name="ck_store_finance_profile_source"),
        CheckConstraint("version_no > 0", name="ck_store_finance_profile_version"),
        Index(
            "idx_store_finance_profile_current",
            "store_id",
            "profile_type",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
        Index("idx_store_finance_profile_batch", "import_batch_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    profile_id: Mapped[str] = mapped_column(String(128))
    store_id: Mapped[str] = mapped_column(String(128))
    profile_type: Mapped[int] = mapped_column(Integer)
    source_type: Mapped[int] = mapped_column(Integer, default=1)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    is_tombstone: Mapped[bool] = mapped_column(Boolean, default=False)
    store_name_snapshot: Mapped[str] = mapped_column(String(255))
    sap_code: Mapped[str | None] = mapped_column(String(128))
    initial_sap_code: Mapped[str | None] = mapped_column(String(128))
    service_store_code: Mapped[str | None] = mapped_column(String(128))
    factory_confirmed: Mapped[bool | None] = mapped_column(Boolean)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    import_batch_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        "gmt_modified", DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ManagementCarryforwardApplication(Base):
    """Keep immutable applications of management-fee negatives to positive periods."""

    __tablename__ = "management_carryforward_application"
    __table_args__ = (
        UniqueConstraint(
            "application_id", name="uk_management_carryforward_application_id"
        ),
        UniqueConstraint(
            "source_statement_id",
            "target_statement_id",
            "version_no",
            name="uk_management_carryforward_application_version",
        ),
        CheckConstraint(
            "version_no > 0", name="ck_management_carryforward_application_version"
        ),
        CheckConstraint(
            "applied_amount_cent > 0",
            name="ck_management_carryforward_application_amount",
        ),
        Index(
            "idx_management_carryforward_current",
            "source_statement_id",
            "target_statement_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
        Index(
            "idx_management_carryforward_store_month",
            "store_id",
            "target_statement_month",
        ),
        Index("idx_management_carryforward_invoice", "invoice_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    application_id: Mapped[str] = mapped_column(String(128))
    store_id: Mapped[str] = mapped_column(String(128))
    source_statement_id: Mapped[str] = mapped_column(String(128))
    source_statement_month: Mapped[str] = mapped_column(String(7))
    target_statement_id: Mapped[str] = mapped_column(String(128))
    target_statement_month: Mapped[str] = mapped_column(String(7))
    invoice_id: Mapped[str | None] = mapped_column(String(128))
    applied_amount_cent: Mapped[int] = mapped_column(BigInteger)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    supersedes_application_id: Mapped[str | None] = mapped_column(String(128))
    projection_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        "gmt_create", DateTime(timezone=True), default=utcnow
    )


class FinanceOperationAudit(Base):
    __tablename__ = "finance_operation_audit"
    __table_args__ = (
        UniqueConstraint("audit_id", name="uk_finance_operation_audit_id"),
        UniqueConstraint(
            "idempotency_key_hash", name="uk_finance_operation_audit_idempotency_key"
        ),
        CheckConstraint("operator_role IN (1, 2, 3)", name="ck_finance_operation_audit_role"),
        CheckConstraint("result_status IN (1, 2, 3)", name="ck_finance_operation_audit_result"),
        Index("idx_finance_operation_audit_operation", "operation_type"),
        Index("idx_finance_operation_audit_target", "target_type", "target_id"),
        Index("idx_finance_operation_audit_operator", "operator_id"),
        Index("idx_finance_operation_audit_result", "result_status"),
        Index("idx_finance_operation_audit_request", "request_id"),
        Index("idx_finance_operation_audit_occurred_at", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    audit_id: Mapped[str] = mapped_column(String(128))
    operation_type: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[str] = mapped_column(String(128))
    operator_id: Mapped[str] = mapped_column(String(128))
    operator_role: Mapped[int] = mapped_column(Integer)
    before_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    after_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    result_status: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String(128))
    idempotency_key_hash: Mapped[str | None] = mapped_column(String(64))
    request_payload_sha256: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
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


class SettlementProjectionGeneration(Base):
    """Durable lineage and resource metadata for one sparse projection build."""

    __tablename__ = "settlement_projection_generation"
    __table_args__ = (
        ForeignKeyConstraint(
            ["base_generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_projection_generation_base",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["compaction_base_generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_projection_generation_compaction_base",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_job_id"],
            ["job_runs.job_id"],
            name="fk_settlement_projection_generation_source_job",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "input_fingerprint",
            name="uq_settlement_projection_generation_input_fingerprint",
        ),
        CheckConstraint(
            "projection_name = 'settlement'",
            name="ck_settlement_projection_generation_projection_name",
        ),
        CheckConstraint(
            "state IN ('staging', 'ready', 'published', 'failed', 'superseded')",
            name="ck_settlement_projection_generation_state",
        ),
        CheckConstraint(
            "lineage_depth >= 0",
            name="ck_settlement_projection_generation_lineage_depth",
        ),
        CheckConstraint(
            "estimated_write_rows >= 0 AND estimated_write_bytes >= 0 "
            "AND estimated_wal_bytes >= 0 AND estimated_disk_headroom_bytes >= 0",
            name="ck_settlement_projection_generation_resources",
        ),
        CheckConstraint(
            "base_generation_id IS NULL OR base_generation_id <> generation_id",
            name="ck_settlement_projection_generation_self_reference",
        ),
        CheckConstraint(
            "generation_kind IN ('lineage', 'legacy_root', 'compact')",
            name="ck_settlement_projection_generation_kind",
        ),
        CheckConstraint(
            "(generation_kind = 'lineage' AND compaction_base_generation_id IS NULL) OR "
            "(generation_kind = 'legacy_root' AND base_generation_id IS NULL "
            "AND lineage_depth = 0 AND compaction_base_generation_id IS NULL) OR "
            "(generation_kind = 'compact' AND base_generation_id IS NULL "
            "AND lineage_depth = 0 AND compaction_base_generation_id IS NOT NULL)",
            name="ck_settlement_projection_generation_kind_base_depth",
        ),
        CheckConstraint(
            "compaction_base_generation_id IS NULL "
            "OR compaction_base_generation_id <> generation_id",
            name="ck_settlement_projection_generation_compaction_self_reference",
        ),
        Index(
            "ix_settlement_projection_generation_state",
            "projection_name",
            "state",
            "created_at",
        ),
        Index(
            "ix_settlement_projection_generation_input",
            "projection_name",
            "input_fingerprint",
        ),
        Index(
            "ix_settlement_projection_generation_base",
            "base_generation_id",
        ),
        Index(
            "ix_settlement_projection_generation_compaction_base",
            "compaction_base_generation_id",
        ),
    )

    generation_id: Mapped[str] = mapped_column(Text, primary_key=True)
    base_generation_id: Mapped[str | None] = mapped_column(Text)
    generation_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="lineage", server_default="lineage"
    )
    compaction_base_generation_id: Mapped[str | None] = mapped_column(Text)
    projection_name: Mapped[str] = mapped_column(String(64), default="settlement")
    state: Mapped[str] = mapped_column(String(32), default="staging")
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    lineage_depth: Mapped[int] = mapped_column(Integer, default=0)
    estimated_write_rows: Mapped[int] = mapped_column(BigInteger, default=0)
    estimated_write_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    estimated_wal_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    estimated_disk_headroom_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    checkpoint_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    last_key: Mapped[str | None] = mapped_column(Text)
    manifest_checksum: Mapped[str | None] = mapped_column(String(64))
    source_job_id: Mapped[str | None] = mapped_column(Text)
    source_input_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    failure_reason: Mapped[str | None] = mapped_column(Text)


class SettlementProjectionCompactionClosure(Base):
    """Immutable provenance membership for one depth-zero compact generation."""

    __tablename__ = "settlement_projection_compaction_closure"
    __table_args__ = (
        ForeignKeyConstraint(
            ["compact_generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_projection_compaction_closure_compact",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_projection_compaction_closure_source",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "compact_generation_id <> source_generation_id",
            name="ck_settlement_projection_compaction_closure_distinct",
        ),
        CheckConstraint(
            "length(source_digest) = 64 AND source_digest = lower(source_digest) AND "
            "replace(replace(replace(replace(replace(replace(replace(replace("
            "replace(replace(replace(replace(replace(replace(replace(replace("
            "source_digest, '0', ''), '1', ''), '2', ''), '3', ''), '4', ''), "
            "'5', ''), '6', ''), '7', ''), '8', ''), '9', ''), 'a', ''), "
            "'b', ''), 'c', ''), 'd', ''), 'e', ''), 'f', '') = ''",
            name="ck_settlement_projection_compaction_closure_digest",
        ),
        Index(
            "ix_settlement_projection_compaction_closure_source",
            "source_generation_id",
        ),
    )

    compact_generation_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_generation_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False)


class SettlementProjectionActive(Base):
    """The nullable pointer published only after a generation is certified."""

    __tablename__ = "settlement_projection_active"
    __table_args__ = (
        ForeignKeyConstraint(
            ["generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_projection_active_generation",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("generation_id", name="uq_settlement_projection_active_generation"),
        CheckConstraint(
            "projection_name = 'settlement'",
            name="ck_settlement_projection_active_projection_name",
        ),
    )

    projection_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    generation_id: Mapped[str | None] = mapped_column(Text)


class SettlementProjectionPartitionManifest(Base):
    """Ownership and source metadata for each sparse artifact partition."""

    __tablename__ = "settlement_projection_partition_manifest"
    __table_args__ = (
        ForeignKeyConstraint(
            ["generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_projection_manifest_generation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["data_generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_projection_manifest_data_generation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["reference_head_generation_id", "data_generation_id"],
            [
                "settlement_projection_compaction_closure.compact_generation_id",
                "settlement_projection_compaction_closure.source_generation_id",
            ],
            name="fk_settlement_projection_manifest_compaction_source",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["base_generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_projection_manifest_base_generation",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "artifact IN ('monthly', 'ranking', 'score')",
            name="ck_settlement_projection_manifest_artifact",
        ),
        CheckConstraint(
            "owner_state IN ('owned', 'tombstone')",
            name="ck_settlement_projection_manifest_owner_state",
        ),
        CheckConstraint(
            "source_kind IN ('overlay', 'legacy_root', 'tombstone')",
            name="ck_settlement_projection_manifest_source_kind",
        ),
        CheckConstraint(
            "row_count >= 0",
            name="ck_settlement_projection_manifest_non_negative_counts",
        ),
        CheckConstraint(
            "(owner_state = 'owned' AND source_kind = 'overlay' "
            "AND data_generation_id IS NOT NULL) OR "
            "(owner_state = 'owned' AND source_kind = 'legacy_root' "
            "AND data_generation_id IS NULL) OR "
            "(owner_state = 'tombstone' AND source_kind = 'tombstone' "
            "AND data_generation_id IS NULL AND row_count = 0)",
            name="ck_settlement_projection_manifest_source_invariants",
        ),
        CheckConstraint(
            "reference_head_generation_id IS NULL OR "
            "(reference_head_generation_id = generation_id AND owner_state='owned' "
            "AND source_kind='overlay' AND data_generation_id IS NOT NULL)",
            name="ck_settlement_projection_manifest_reference_head",
        ),
        Index(
            "ix_settlement_projection_manifest_state",
            "artifact",
            "owner_state",
            "source_kind",
        ),
        Index(
            "ix_settlement_projection_manifest_data_generation",
            "data_generation_id",
        ),
        Index(
            "ix_settlement_projection_manifest_base_generation",
            "base_generation_id",
        ),
        Index(
            "ix_settlement_projection_manifest_reference_source",
            "reference_head_generation_id",
            "data_generation_id",
        ),
    )

    generation_id: Mapped[str] = mapped_column(Text, primary_key=True)
    artifact: Mapped[str] = mapped_column(String(32), primary_key=True)
    partition_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner_state: Mapped[str] = mapped_column(String(32), default="owned")
    source_kind: Mapped[str] = mapped_column(String(32), default="overlay")
    data_generation_id: Mapped[str | None] = mapped_column(Text)
    reference_head_generation_id: Mapped[str | None] = mapped_column(Text)
    base_generation_id: Mapped[str | None] = mapped_column(Text)
    row_count: Mapped[int] = mapped_column(BigInteger, default=0)
    amount_total_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    status_counts_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    checksum: Mapped[str | None] = mapped_column(String(64))
    last_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SettlementMonthlyOverlay(Base):
    """Generation-scoped monthly settlement rows; legacy aggregate stays untouched."""

    __tablename__ = "settlement_monthly_overlay"
    __table_args__ = (
        ForeignKeyConstraint(
            ["generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_monthly_overlay_generation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["base_generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_monthly_overlay_base_generation",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "generation_id",
            "month",
            "store_id",
            "product_scope",
            "product_type",
            name="uq_settlement_monthly_overlay_natural_key",
        ),
        CheckConstraint(
            "statement_status IN (1, 2, 3, 4)",
            name="ck_settlement_monthly_overlay_status",
        ),
        CheckConstraint(
            "partition_key = month",
            name="ck_settlement_monthly_overlay_partition",
        ),
        Index(
            "ix_settlement_monthly_overlay_generation_partition",
            "generation_id",
            "partition_key",
        ),
        Index(
            "ix_settlement_monthly_overlay_store_month",
            "store_id",
            "month",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    generation_id: Mapped[str] = mapped_column(Text, nullable=False)
    base_generation_id: Mapped[str | None] = mapped_column(Text)
    month: Mapped[str] = mapped_column(String(7), nullable=False)
    store_id: Mapped[str] = mapped_column(String(128), nullable=False)
    product_scope: Mapped[str] = mapped_column(String(128), default="all", nullable=False)
    product_type: Mapped[str] = mapped_column(String(128), default="all", nullable=False)
    partition_key: Mapped[str] = mapped_column(String(7), nullable=False)
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
    projection_run_id: Mapped[str] = mapped_column(String(128), default="")
    estimated_receivable_commission_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    commissionable_total_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    estimated_payable_commission_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    tombstone: Mapped[bool] = mapped_column(Boolean, default=False)
    checksum: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SettlementRankingOverlay(Base):
    """Generation-scoped monthly/cumulative ranking rows."""

    __tablename__ = "settlement_ranking_overlay"
    __table_args__ = (
        ForeignKeyConstraint(
            ["generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_ranking_overlay_generation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["base_generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_ranking_overlay_base_generation",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "generation_id",
            "period_type",
            "period_key",
            "store_id",
            "product_scope",
            "product_type",
            name="uq_settlement_ranking_overlay_natural_key",
        ),
        CheckConstraint(
            "period_type IN (1, 2)",
            name="ck_settlement_ranking_overlay_period_type",
        ),
        CheckConstraint(
            "net_settlement_reference_cent = promotion_net_fee_cent - "
            "management_net_fee_cent",
            name="ck_settlement_ranking_overlay_net_reference",
        ),
        CheckConstraint(
            "(period_type = 1 AND partition_key = 'monthly:' || period_key "
            "AND month = period_key) OR "
            "(period_type = 2 AND partition_key = 'cumulative:' || period_key "
            "AND month = period_key)",
            name="ck_settlement_ranking_overlay_partition",
        ),
        Index(
            "ix_settlement_ranking_overlay_generation_partition",
            "generation_id",
            "period_type",
            "period_key",
        ),
        Index(
            "ix_settlement_ranking_overlay_store_period",
            "store_id",
            "period_key",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    generation_id: Mapped[str] = mapped_column(Text, nullable=False)
    base_generation_id: Mapped[str | None] = mapped_column(Text)
    period_type: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    period_key: Mapped[str] = mapped_column(String(7), nullable=False)
    store_id: Mapped[str] = mapped_column(String(128), nullable=False)
    store_name: Mapped[str] = mapped_column(String(255), default="")
    product_scope: Mapped[str] = mapped_column(String(128), default="all", nullable=False)
    product_type: Mapped[str] = mapped_column(String(128), default="all", nullable=False)
    partition_key: Mapped[str] = mapped_column(String(32), nullable=False)
    sales_order_count: Mapped[int] = mapped_column(Integer, default=0)
    sales_amount_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    verified_order_count: Mapped[int] = mapped_column(Integer, default=0)
    verified_amount_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    promotion_net_fee_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    management_net_fee_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    net_settlement_reference_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    projection_run_id: Mapped[str] = mapped_column(String(128), default="")
    month: Mapped[str] = mapped_column(String(7), default="")
    self_sold_self_verified_count: Mapped[int] = mapped_column(Integer, default=0)
    self_sold_other_verified_count: Mapped[int] = mapped_column(Integer, default=0)
    other_sold_self_verified_count: Mapped[int] = mapped_column(Integer, default=0)
    self_verify_income_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    effective_commission_income_cent: Mapped[int] = mapped_column(BigInteger, default=0)
    tombstone: Mapped[bool] = mapped_column(Boolean, default=False)
    checksum: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StoreScoreSnapshotGeneration(Base):
    """Generation sidecar for existing score rows; it never fabricates a row."""

    __tablename__ = "store_score_snapshot_generation"
    __table_args__ = (
        ForeignKeyConstraint(
            ["generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_store_score_snapshot_generation_generation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["rule_version_id"],
            ["clue_allocation_rule_versions.rule_version_id"],
            name="fk_store_score_snapshot_generation_rule_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["snapshot_run_id", "store_id"],
            ["store_score_snapshots.snapshot_run_id", "store_score_snapshots.store_id"],
            name="fk_store_score_snapshot_generation_snapshot_store",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "generation_id",
            "snapshot_date",
            "rule_version_id",
            "store_id",
            name="uq_store_score_snapshot_generation_partition",
        ),
        CheckConstraint(
            "owner_state = 'owned'",
            name="ck_store_score_snapshot_generation_owner_state",
        ),
        Index(
            "ix_store_score_snapshot_generation_partition",
            "snapshot_date",
            "rule_version_id",
            "store_id",
        ),
        Index(
            "ix_store_score_snapshot_generation_generation",
            "generation_id",
        ),
    )

    generation_id: Mapped[str] = mapped_column(Text, primary_key=True)
    snapshot_run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    store_id: Mapped[str] = mapped_column(Text, primary_key=True)
    rule_version_id: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    partition_key: Mapped[str] = mapped_column(String(256), nullable=False)
    owner_state: Mapped[str] = mapped_column(String(32), default="owned")
    checksum: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)



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
    """Persist a legacy-compatible job and its control-plane state."""

    __tablename__ = "job_runs"
    __table_args__ = (
        CheckConstraint(
            "job_kind IS NULL OR job_kind != 'date_sync' OR ("
            "parent_job_id IS NOT NULL AND business_date IS NOT NULL "
            "AND data_source IS NOT NULL AND config_version IS NOT NULL "
            "AND window_start IS NOT NULL AND window_end IS NOT NULL "
            "AND window_end > window_start)",
            name="ck_job_runs_date_sync_complete_window",
        ),
        CheckConstraint(
            "job_kind IS NULL OR job_kind != 'parent_sync' OR ("
            "parent_job_id IS NOT NULL AND execution_slot IS NOT NULL "
            "AND execution_slot = 'heavy_sync' "
            "AND business_date IS NULL AND data_source IS NOT NULL "
            "AND config_version IS NOT NULL AND window_start IS NOT NULL "
            "AND window_end IS NOT NULL AND window_end > window_start)",
            name="ck_job_runs_parent_sync_complete_window",
        ),
        CheckConstraint(
            "job_kind IS NULL OR job_kind != 'range_sync' "
            "OR execution_slot IS NULL",
            name="ck_job_runs_range_sync_no_execution_slot",
        ),
        CheckConstraint(
            "job_kind IS NULL OR job_kind IN ("
            "'range_sync', 'parent_sync', 'date_sync', 'finalize', 'product_sync')",
            name="ck_job_runs_job_kind_allowlist",
        ),
        CheckConstraint(
            "current_stage IS NULL OR current_stage IN ("
            "'collect', 'collect_dimensions', 'materialize', 'settle', 'finalize')",
            name="ck_job_runs_current_stage_allowlist",
        ),
        CheckConstraint(
            "status IN ('pending', 'queued', 'running', 'retry_wait', "
            "'success', 'succeeded', 'partial', 'failed', 'cancelled')",
            name="ck_job_runs_status_allowlist",
        ),
        CheckConstraint(
            "(attempt_count IS NULL OR attempt_count >= 0) AND "
            "(max_attempts IS NULL OR max_attempts BETWEEN 1 AND 3) AND "
            "(attempt_count IS NULL OR max_attempts IS NULL "
            "OR attempt_count <= max_attempts)",
            name="ck_job_runs_attempt_bounds",
        ),
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
        Index(
            "uq_job_runs_finance_dispute_detection_idempotency_key",
            "job_name",
            "idempotency_key_hash",
            unique=True,
            sqlite_where=text(
                "job_name = 'finance_dispute_detection' "
                "AND idempotency_key_hash IS NOT NULL"
            ),
            postgresql_where=text(
                "job_name = 'finance_dispute_detection' "
                "AND idempotency_key_hash IS NOT NULL"
            ),
        ),
        Index(
            "uq_job_runs_date_sync_identity",
            "parent_job_id",
            "business_date",
            "data_source",
            "config_version",
            unique=True,
            sqlite_where=text(
                "job_kind = 'date_sync' "
                "AND parent_job_id IS NOT NULL "
                "AND business_date IS NOT NULL "
                "AND data_source IS NOT NULL "
                "AND config_version IS NOT NULL"
            ),
            postgresql_where=text(
                "job_kind = 'date_sync' "
                "AND parent_job_id IS NOT NULL "
                "AND business_date IS NOT NULL "
                "AND data_source IS NOT NULL "
                "AND config_version IS NOT NULL"
            ),
        ),
        Index(
            "uq_job_runs_heavy_sync_running_slot",
            "execution_slot",
            unique=True,
            sqlite_where=text(
                "execution_slot = 'heavy_sync' AND status = 'running'"
            ),
            postgresql_where=text(
                "execution_slot = 'heavy_sync' AND status = 'running'"
            ),
        ),
        Index("ix_job_runs_parent_business_date", "parent_job_id", "business_date"),
        Index("ix_job_runs_lease_expires_at", "lease_expires_at"),
        Index("ix_job_runs_heartbeat_at", "heartbeat_at"),
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
    claim_token: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    state_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    parent_job_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("job_runs.job_id", ondelete="RESTRICT"),
    )
    job_kind: Mapped[str | None] = mapped_column(String(32))
    execution_slot: Mapped[str | None] = mapped_column(String(32))
    business_date: Mapped[date | None] = mapped_column(Date)
    data_source: Mapped[str | None] = mapped_column(String(128))
    config_version: Mapped[str | None] = mapped_column(String(128))
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_stage: Mapped[str | None] = mapped_column(String(32))
    attempt_count: Mapped[int | None] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int | None] = mapped_column(Integer, default=3)
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_epoch: Mapped[int | None] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress_current: Mapped[int | None] = mapped_column(BigInteger)
    progress_total: Mapped[int | None] = mapped_column(BigInteger)
    rows_read: Mapped[int | None] = mapped_column(BigInteger)
    rows_written: Mapped[int | None] = mapped_column(BigInteger)
    rows_affected: Mapped[int | None] = mapped_column(BigInteger)
    rss_peak_bytes: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_summary: Mapped[str | None] = mapped_column(Text)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pause_after_stage_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class JobStageRun(Base):
    """Store the authoritative checkpoint for one job stage."""

    __tablename__ = "job_stage_runs"
    __table_args__ = (
        UniqueConstraint("job_id", "stage_name", name="uq_job_stage_runs_job_stage"),
        UniqueConstraint(
            "job_id", "stage_run_id", name="uq_job_stage_runs_job_stage_run"
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'success', 'failed', "
            "'cancelled', 'skipped')",
            name="ck_job_stage_runs_status",
        ),
        CheckConstraint(
            "status != 'success' OR committed_at IS NOT NULL",
            name="ck_job_stage_runs_success_committed_at",
        ),
        CheckConstraint(
            "lease_epoch IS NULL OR lease_epoch >= 0",
            name="ck_job_stage_runs_lease_epoch",
        ),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="ck_job_stage_runs_time_order",
        ),
        Index("ix_job_stage_runs_job_status", "job_id", "status"),
        Index("ix_job_stage_runs_committed_at", "committed_at"),
    )

    stage_run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    job_id: Mapped[str] = mapped_column(
        Text, ForeignKey("job_runs.job_id", ondelete="RESTRICT")
    )
    stage_name: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    checkpoint_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    lease_epoch: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class JobAttempt(Base):
    """Record one fenced claim and execution attempt for a job."""

    __tablename__ = "job_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "stage_run_id"],
            ["job_stage_runs.job_id", "job_stage_runs.stage_run_id"],
            name="fk_job_attempts_job_stage_run",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["component_instance_id", "component_type"],
            [
                "component_heartbeats.component_instance_id",
                "component_heartbeats.component_type",
            ],
            name="fk_job_attempts_component_identity",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "job_id", "attempt_number", name="uq_job_attempts_job_attempt_number"
        ),
        UniqueConstraint("job_id", "lease_epoch", name="uq_job_attempts_job_lease_epoch"),
        UniqueConstraint("job_id", "attempt_id", name="uq_job_attempts_job_attempt"),
        UniqueConstraint(
            "job_id",
            "component_instance_id",
            "attempt_id",
            name="uq_job_attempts_job_component_attempt",
        ),
        CheckConstraint("attempt_number > 0", name="ck_job_attempts_attempt_number"),
        CheckConstraint("lease_epoch > 0", name="ck_job_attempts_lease_epoch"),
        CheckConstraint(
            "batch_size IS NULL OR batch_size > 0",
            name="ck_job_attempts_batch_size",
        ),
        CheckConstraint(
            "exit_type IS NULL OR exit_type IN ("
            "'success', 'retryable_failure', 'fatal_failure', "
            "'cancelled', 'crashed', 'resource_guard')",
            name="ck_job_attempts_exit_type",
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_job_attempts_time_order",
        ),
        Index("ix_job_attempts_job_started", "job_id", "started_at"),
        Index("ix_job_attempts_stage_run_id", "stage_run_id"),
        Index(
            "ix_job_attempts_component_started",
            "component_instance_id",
            "started_at",
        ),
    )

    attempt_id: Mapped[str] = mapped_column(Text, primary_key=True)
    job_id: Mapped[str] = mapped_column(
        Text, ForeignKey("job_runs.job_id", ondelete="RESTRICT")
    )
    stage_run_id: Mapped[str | None] = mapped_column(Text)
    attempt_number: Mapped[int] = mapped_column(Integer)
    lease_epoch: Mapped[int] = mapped_column(Integer)
    component_type: Mapped[str] = mapped_column(String(32))
    component_instance_id: Mapped[str] = mapped_column(Text)
    process_id: Mapped[int | None] = mapped_column(Integer)
    container_instance_id: Mapped[str | None] = mapped_column(Text)
    batch_size: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_type: Mapped[str | None] = mapped_column(String(32))
    exit_code: Mapped[int | None] = mapped_column(Integer)
    rss_peak_bytes: Mapped[int | None] = mapped_column(BigInteger)
    error_id: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JobEvent(Base):
    """Store an append-only audit or observability event for a job."""

    __tablename__ = "job_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "stage_run_id"],
            ["job_stage_runs.job_id", "job_stage_runs.stage_run_id"],
            name="fk_job_events_job_stage_run",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["job_id", "attempt_id"],
            ["job_attempts.job_id", "job_attempts.attempt_id"],
            name="fk_job_events_job_attempt",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "actor_type IN ('system', 'worker', 'ops_agent', 'user')",
            name="ck_job_events_actor_type",
        ),
        Index(
            "uq_job_events_idempotency_key",
            "job_id",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL"),
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_job_events_job_occurred", "job_id", "occurred_at"),
        Index("ix_job_events_attempt_id", "attempt_id"),
        Index("ix_job_events_type_occurred", "event_type", "occurred_at"),
    )

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    job_id: Mapped[str] = mapped_column(
        Text, ForeignKey("job_runs.job_id", ondelete="RESTRICT")
    )
    stage_run_id: Mapped[str | None] = mapped_column(Text)
    attempt_id: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(String(64))
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32))
    actor_type: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    error_id: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ComponentHeartbeat(Base):
    """Store the latest declared state for one component instance."""

    __tablename__ = "component_heartbeats"
    __table_args__ = (
        ForeignKeyConstraint(
            ["current_job_id", "component_instance_id", "current_attempt_id"],
            [
                "job_attempts.job_id",
                "job_attempts.component_instance_id",
                "job_attempts.attempt_id",
            ],
            name="fk_component_heartbeats_current_attempt",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        UniqueConstraint(
            "component_instance_id",
            "component_type",
            name="uq_component_heartbeats_instance_type",
        ),
        CheckConstraint(
            "current_attempt_id IS NULL OR current_job_id IS NOT NULL",
            name="ck_component_heartbeats_current_attempt_job",
        ),
        CheckConstraint(
            "component_type IN ("
            "'worker', 'browser', 'api', 'postgres', 'proxy', 'ops_agent')",
            name="ck_component_heartbeats_component_type",
        ),
        CheckConstraint(
            "status IN ("
            "'starting', 'healthy', 'degraded', 'draining', 'unhealthy', 'stopped')",
            name="ck_component_heartbeats_status",
        ),
        CheckConstraint(
            "rss_bytes IS NULL OR rss_bytes >= 0",
            name="ck_component_heartbeats_rss_bytes",
        ),
        CheckConstraint(
            "rss_peak_bytes IS NULL OR rss_peak_bytes >= 0",
            name="ck_component_heartbeats_rss_peak_bytes",
        ),
        CheckConstraint(
            "memory_limit_bytes IS NULL OR memory_limit_bytes > 0",
            name="ck_component_heartbeats_memory_limit_bytes",
        ),
        CheckConstraint(
            "queue_depth IS NULL OR queue_depth >= 0",
            name="ck_component_heartbeats_queue_depth",
        ),
        Index(
            "ix_component_heartbeats_type_last_heartbeat",
            "component_type",
            "last_heartbeat_at",
        ),
        Index("ix_component_heartbeats_status", "status"),
        Index("ix_component_heartbeats_current_job_id", "current_job_id"),
    )

    component_instance_id: Mapped[str] = mapped_column(Text, primary_key=True)
    component_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    version: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    current_job_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("job_runs.job_id", ondelete="RESTRICT")
    )
    current_attempt_id: Mapped[str | None] = mapped_column(Text)
    rss_bytes: Mapped[int | None] = mapped_column(BigInteger)
    rss_peak_bytes: Mapped[int | None] = mapped_column(BigInteger)
    memory_limit_bytes: Mapped[int | None] = mapped_column(BigInteger)
    cpu_percent: Mapped[float | None] = mapped_column(Float)
    queue_depth: Mapped[int | None] = mapped_column(Integer)
    activity_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    queue_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ComponentMetricSample(Base):
    """Store a retained point-in-time component resource metric."""

    __tablename__ = "component_metric_samples"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "component_instance_id", "attempt_id"],
            [
                "job_attempts.job_id",
                "job_attempts.component_instance_id",
                "job_attempts.attempt_id",
            ],
            name="fk_component_metric_samples_job_component_attempt",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "component_instance_id",
            "metric_name",
            "sampled_at",
            name="uq_component_metric_samples_instance_metric_sampled",
        ),
        CheckConstraint(
            "expires_at > sampled_at",
            name="ck_component_metric_samples_retention",
        ),
        CheckConstraint(
            "attempt_id IS NULL OR job_id IS NOT NULL",
            name="ck_component_metric_samples_attempt_job",
        ),
        Index(
            "ix_component_metric_samples_component_sampled",
            "component_instance_id",
            "sampled_at",
        ),
        Index("ix_component_metric_samples_expires_at", "expires_at"),
        Index("ix_component_metric_samples_job_sampled", "job_id", "sampled_at"),
    )

    metric_sample_id: Mapped[str] = mapped_column(Text, primary_key=True)
    component_instance_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("component_heartbeats.component_instance_id", ondelete="RESTRICT"),
    )
    job_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("job_runs.job_id", ondelete="RESTRICT")
    )
    attempt_id: Mapped[str | None] = mapped_column(Text)
    metric_name: Mapped[str] = mapped_column(String(64))
    metric_value: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    unit: Mapped[str] = mapped_column(String(32))
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)


class OpsCommand(Base):
    """Store a confirmed, allowlisted command for the isolated ops agent."""

    __tablename__ = "ops_commands"
    __table_args__ = (
        CheckConstraint("command_type = 'restart'", name="ck_ops_commands_command_type"),
        CheckConstraint(
            "target_component IN ('worker', 'browser')",
            name="ck_ops_commands_target_component",
        ),
        CheckConstraint(
            "status IN ("
            "'pending', 'running', 'success', 'failed', "
            "'rejected', 'expired', 'cancelled')",
            name="ck_ops_commands_status",
        ),
        CheckConstraint(
            "lease_epoch IS NULL OR lease_epoch > 0",
            name="ck_ops_commands_lease_epoch",
        ),
        CheckConstraint("expires_at > created_at", name="ck_ops_commands_expiry"),
        Index(
            "uq_ops_commands_idempotency_key_hash",
            "idempotency_key_hash",
            unique=True,
        ),
        Index(
            "uq_ops_commands_active_target",
            "target_component",
            unique=True,
            sqlite_where=text("status IN ('pending', 'running')"),
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
        Index("ix_ops_commands_status_created", "status", "created_at"),
        Index("ix_ops_commands_expires_at", "expires_at"),
        Index("ix_ops_commands_related_job_id", "related_job_id"),
        Index(
            "ix_ops_commands_target_cooldown",
            "target_component",
            "cooldown_until",
        ),
    )

    command_id: Mapped[str] = mapped_column(Text, primary_key=True)
    command_type: Mapped[str] = mapped_column(String(32))
    target_component: Mapped[str] = mapped_column(String(32))
    requested_by: Mapped[str] = mapped_column(Text)
    request_reason: Mapped[str] = mapped_column(Text)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32))
    idempotency_key_hash: Mapped[str] = mapped_column(String(64))
    request_payload_sha256: Mapped[str] = mapped_column(String(64))
    related_job_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("job_runs.job_id", ondelete="SET NULL")
    )
    claimed_by: Mapped[str | None] = mapped_column(Text)
    lease_epoch: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_code: Mapped[str | None] = mapped_column(String(64))
    result_summary: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


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
        Index(
            "ix_clue_master_leads_source_identity_order",
            "source_identity_key",
            "order_id",
        ),
    )

    lead_key: Mapped[str] = mapped_column(Text, primary_key=True)
    source_clue_row_key: Mapped[str] = mapped_column(Text)
    source_identity_key: Mapped[str] = mapped_column(Text)
    master_kind: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    canonical_clue_id: Mapped[str | None] = mapped_column(Text, index=True)
    order_id: Mapped[str | None] = mapped_column(Text, index=True)
    raw_order_status: Mapped[str | None] = mapped_column(Text)
    normalized_order_status: Mapped[str] = mapped_column(String(32), default="unknown", index=True)
    status_source: Mapped[str] = mapped_column(String(32), default="clue")
    order_status_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
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
    last_observation_key: Mapped[str | None] = mapped_column(String(256))
    anchor_poi_id: Mapped[str | None] = mapped_column(Text, index=True)
    anchor_store_id: Mapped[str | None] = mapped_column(Text, index=True)
    anchor_source: Mapped[str | None] = mapped_column(Text)
    anchor_unavailable_reason: Mapped[str | None] = mapped_column(Text)
    anchor_province: Mapped[str | None] = mapped_column(Text)
    anchor_city: Mapped[str | None] = mapped_column(Text)
    anchor_city_code: Mapped[str | None] = mapped_column(Text, index=True)
    anchor_longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    anchor_latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    is_complete_pool: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ClueSourceRecordLink(Base):
    __tablename__ = "clue_source_record_links"
    __table_args__ = (
        UniqueConstraint(
            "source_table",
            "source_record_key",
            name="uq_clue_source_record_links_source",
        ),
        Index("ix_clue_source_record_links_lead_key", "lead_key"),
        Index("ix_clue_source_record_links_order_id", "order_id"),
        Index(
            "ix_clue_source_record_links_status_updated_at",
            "link_status",
            "updated_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        Identity(),
        primary_key=True,
        autoincrement=True,
    )
    source_system: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    source_table: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="raw_douyin_clues",
        server_default=text("'raw_douyin_clues'"),
    )
    source_record_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source_clue_id: Mapped[str | None] = mapped_column(String(64))
    source_order_id: Mapped[str | None] = mapped_column(String(64))
    lead_key: Mapped[str] = mapped_column(
        Text,
        ForeignKey("clue_master_leads.lead_key", ondelete="RESTRICT"),
        nullable=False,
    )
    order_id: Mapped[str | None] = mapped_column(String(64))
    link_status: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    link_method: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    link_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    source_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    source_run_id: Mapped[str | None] = mapped_column(String(64))
    source_payload_hash: Mapped[str | None] = mapped_column(String(64))
    conflict_reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class ClueSourceIdentifierHistory(Base):
    __tablename__ = "clue_source_identifier_history"
    __table_args__ = (
        UniqueConstraint(
            "source_clue_row_key",
            "identifier_type",
            "identifier_value",
            name="uq_clue_source_identifier_history_source_type_value",
        ),
        Index(
            "ix_clue_source_identifier_history_lead_type_current",
            "lead_key",
            "identifier_type",
            "is_current",
        ),
        Index(
            "ix_clue_source_identifier_history_source_type_current",
            "source_clue_row_key",
            "identifier_type",
            "is_current",
        ),
        Index(
            "ix_clue_source_identifier_history_source_lead_type",
            "source_clue_row_key",
            "lead_key",
            "identifier_type",
            "is_current",
        ),
        Index(
            "ix_clue_source_identifier_history_type_value_lead",
            "identifier_type",
            "identifier_value",
            "lead_key",
        ),
    )

    identifier_history_id: Mapped[str] = mapped_column(Text, primary_key=True)
    lead_key: Mapped[str] = mapped_column(
        Text,
        ForeignKey("clue_master_leads.lead_key", ondelete="RESTRICT"),
        index=True,
    )
    source_clue_row_key: Mapped[str] = mapped_column(Text, index=True)
    identifier_type: Mapped[str] = mapped_column(String(32))
    identifier_value: Mapped[str] = mapped_column(Text)
    source_payload_hash: Mapped[str | None] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
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
    execution_mode: Mapped[str] = mapped_column(String(32), default="formal", index=True)
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
        Index("uq_clue_allocation_cycles_idempotency_key_hash", "idempotency_key_hash", unique=True),
        Index("ix_clue_allocation_cycles_actor_user", "actor_user_id", "created_at"),
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
    actor_user_id: Mapped[str | None] = mapped_column(Text)
    actor_username_snapshot: Mapped[str | None] = mapped_column(Text)
    privileged_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    preview_token_hash: Mapped[str | None] = mapped_column(String(64))
    preview_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key_hash: Mapped[str | None] = mapped_column(String(64))
    idempotency_request_hash: Mapped[str | None] = mapped_column(String(64))
    request_scope_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    error_summary: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    state_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class ClueAllocationCycleItem(Base):
    """Per-lead execution evidence for one allocation cycle."""

    __tablename__ = "clue_allocation_cycle_items"
    __table_args__ = (
        UniqueConstraint("allocation_cycle_id", "lead_key", name="uq_clue_allocation_cycle_items_cycle_lead"),
        UniqueConstraint(
            "allocation_cycle_id",
            "sequence_no",
            name="uq_clue_allocation_cycle_items_cycle_sequence",
        ),
        Index("ix_clue_allocation_cycle_items_cycle_status", "allocation_cycle_id", "item_status"),
        Index("ix_clue_allocation_cycle_items_lead_created", "lead_key", "created_at"),
    )

    cycle_item_id: Mapped[str] = mapped_column(Text, primary_key=True)
    allocation_cycle_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("clue_allocation_cycles.allocation_cycle_id", ondelete="CASCADE"),
        index=True,
    )
    sequence_no: Mapped[int] = mapped_column(Integer)
    lead_key: Mapped[str] = mapped_column(Text, index=True)
    order_id: Mapped[str | None] = mapped_column(Text, index=True)
    item_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    initial_pool_location: Mapped[str | None] = mapped_column(String(32))
    rule_binding_id: Mapped[str | None] = mapped_column(Text)
    decision_id: Mapped[str | None] = mapped_column(Text, index=True)
    assignment_round_id: Mapped[str | None] = mapped_column(Text, index=True)
    headquarters_pool_entry_id: Mapped[str | None] = mapped_column(Text, index=True)
    outcome_reason: Mapped[str | None] = mapped_column(String(128))
    precondition_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_detail: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClueAllocationCandidate(Base):
    """Immutable candidate snapshot captured when an allocation decision is made."""

    __tablename__ = "clue_allocation_candidates"
    __table_args__ = (
        UniqueConstraint("decision_id", "store_id", name="uq_clue_allocation_candidates_decision_store"),
        Index("ix_clue_allocation_candidates_decision_rank", "decision_id", "eligibility_status", "rank_no"),
        Index("ix_clue_allocation_candidates_store_evaluated", "store_id", "evaluated_at"),
        Index("ix_clue_allocation_candidates_exclusion", "exclusion_reason_code", "evaluated_at"),
    )

    candidate_id: Mapped[str] = mapped_column(Text, primary_key=True)
    decision_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("clue_allocation_decisions.decision_id", ondelete="CASCADE"),
        index=True,
    )
    lead_key: Mapped[str] = mapped_column(Text, index=True)
    order_id: Mapped[str | None] = mapped_column(Text, index=True)
    strategy_type: Mapped[str] = mapped_column(String(64), index=True)
    store_id: Mapped[str] = mapped_column(Text, index=True)
    store_name_snapshot: Mapped[str] = mapped_column(Text)
    city_code: Mapped[str | None] = mapped_column(String(64))
    eligibility_status: Mapped[str] = mapped_column(String(32), index=True)
    exclusion_reason_code: Mapped[str | None] = mapped_column(String(128), index=True)
    exclusion_detail: Mapped[str | None] = mapped_column(String(500))
    is_sales_store: Mapped[bool] = mapped_column(Boolean, default=False)
    is_historical_assignment: Mapped[bool] = mapped_column(Boolean, default=False)
    is_serviceable: Mapped[bool] = mapped_column(Boolean, default=False)
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    store_location_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    score_snapshot_id: Mapped[str | None] = mapped_column(Text, index=True)
    conversion_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    follow_24h_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    store_weight: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    composite_score: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), index=True)
    rank_no: Mapped[int | None] = mapped_column(Integer)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_key_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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
        Index("ix_clue_allocation_audit_logs_actor_created", "actor_user_id", "created_at"),
        Index("ix_clue_allocation_audit_logs_request_id", "request_id"),
    )

    audit_log_id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    allocation_cycle_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("clue_allocation_cycles.allocation_cycle_id", ondelete="RESTRICT"),
        index=True,
    )
    actor: Mapped[str | None] = mapped_column(Text)
    actor_user_id: Mapped[str | None] = mapped_column(Text)
    actor_username_snapshot: Mapped[str | None] = mapped_column(Text)
    actor_role_snapshot: Mapped[str | None] = mapped_column(String(32))
    actor_scope_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    request_id: Mapped[str | None] = mapped_column(Text)
    result_status: Mapped[str] = mapped_column(String(32), default="success")
    reason_code: Mapped[str | None] = mapped_column(String(128))
    privileged_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    before_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    after_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    detail_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
