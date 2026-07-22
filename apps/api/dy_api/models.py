from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
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
    environment: Mapped[str] = mapped_column(String(32), default="test")
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
