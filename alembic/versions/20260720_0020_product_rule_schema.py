"""add product facts, settlement scope, and immutable fee rule schemas

Revision ID: 20260720_0020
Revises: 20260720_0019
Create Date: 2026-07-20 17:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260720_0020"
down_revision = "20260720_0019"
branch_labels = None
depends_on = None


def _id_column() -> sa.Column:
    if op.get_bind().dialect.name == "sqlite":
        return sa.Column("id", sa.Integer(), nullable=False, autoincrement=True)
    return sa.Column(
        "id", sa.BigInteger(), sa.Identity(), nullable=False, autoincrement=True
    )


def _json_type() -> sa.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _audit_columns() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "gmt_create",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "gmt_modified",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def upgrade() -> None:
    _replace_legacy_sku_fact_table()
    _create_product_sync_history()
    _create_settlement_scope_rule()
    _create_sku_fee_rule()
    _create_import_batch()
    _create_import_row()


def downgrade() -> None:
    _guard_downgrade_against_new_data()
    op.drop_table("sku_fee_rule_import_row")
    op.drop_table("sku_fee_rule_import_batch")
    op.drop_table("sku_fee_rule")
    op.drop_table("settlement_scope_rule")
    op.drop_table("sku_product_sync_history")
    _restore_legacy_sku_fact_table()


def _replace_legacy_sku_fact_table() -> None:
    op.create_table(
        "dim_sku_product_rules_v2",
        _id_column(),
        sa.Column("sku_id", sa.String(length=128), nullable=False),
        sa.Column("sku_name", sa.String(length=512), nullable=True),
        sa.Column("product_id", sa.String(length=128), nullable=True),
        sa.Column("product_name", sa.String(length=512), nullable=True),
        sa.Column("spu_id", sa.String(length=128), nullable=True),
        sa.Column(
            "product_scope",
            sa.String(length=128),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "product_type",
            sa.String(length=128),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "is_service_product",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("creator_account_id", sa.String(length=128), nullable=True),
        sa.Column("creator_account_name", sa.String(length=255), nullable=True),
        sa.Column("owner_account_id", sa.String(length=128), nullable=True),
        sa.Column("owner_account_name", sa.String(length=255), nullable=True),
        sa.Column("product_status_raw", sa.String(length=128), nullable=True),
        sa.Column(
            "product_status_normalized", sa.String(length=32), nullable=True
        ),
        sa.Column(
            "is_active_product",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("sync_source", sa.String(length=64), nullable=True),
        sa.Column("sync_run_id", sa.String(length=128), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manual_modified_by", sa.String(length=128), nullable=True),
        sa.Column("manual_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "commission_rate",
            sa.Numeric(precision=6, scale=4),
            nullable=False,
            server_default="0",
        ),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_dim_sku_product_rules"),
        sa.UniqueConstraint(
            "sku_id", name="uk_dim_sku_product_rules_sku_id"
        ),
    )
    op.execute(
        sa.text(
            "INSERT INTO dim_sku_product_rules_v2 ("
            "sku_id, product_name, product_scope, product_type, "
            "is_service_product, commission_rate, gmt_create, gmt_modified"
            ") SELECT sku_id, product_name, product_scope, product_type, "
            "is_service_product, commission_rate, updated_at, updated_at "
            "FROM dim_sku_product_rules"
        )
    )
    op.drop_table("dim_sku_product_rules")
    op.rename_table("dim_sku_product_rules_v2", "dim_sku_product_rules")
    op.create_index(
        "idx_dim_sku_product_rules_product_id",
        "dim_sku_product_rules",
        ["product_id"],
    )
    op.create_index(
        "idx_dim_sku_product_rules_spu_id",
        "dim_sku_product_rules",
        ["spu_id"],
    )
    op.create_index(
        "idx_dim_sku_product_rules_scope_type",
        "dim_sku_product_rules",
        ["product_scope", "product_type"],
    )
    op.create_index(
        "idx_dim_sku_product_rules_owner_status",
        "dim_sku_product_rules",
        ["owner_account_id", "product_status_normalized"],
    )
    op.create_index(
        "idx_dim_sku_product_rules_active",
        "dim_sku_product_rules",
        ["is_active_product"],
    )
    op.create_index(
        "idx_dim_sku_product_rules_sync_run",
        "dim_sku_product_rules",
        ["sync_run_id"],
    )
    op.create_index(
        "idx_dim_sku_product_rules_last_synced",
        "dim_sku_product_rules",
        ["last_synced_at"],
    )


def _create_product_sync_history() -> None:
    op.create_table(
        "sku_product_sync_history",
        _id_column(),
        sa.Column("snapshot_id", sa.String(length=128), nullable=False),
        sa.Column("sync_run_id", sa.String(length=128), nullable=False),
        sa.Column("sku_id", sa.String(length=128), nullable=False),
        sa.Column("product_id", sa.String(length=128), nullable=True),
        sa.Column("spu_id", sa.String(length=128), nullable=True),
        sa.Column("sku_name", sa.String(length=512), nullable=True),
        sa.Column("product_name", sa.String(length=512), nullable=True),
        sa.Column("creator_account_id", sa.String(length=128), nullable=True),
        sa.Column("creator_account_name", sa.String(length=255), nullable=True),
        sa.Column("owner_account_id", sa.String(length=128), nullable=True),
        sa.Column("owner_account_name", sa.String(length=255), nullable=True),
        sa.Column("product_status_raw", sa.String(length=128), nullable=True),
        sa.Column(
            "product_status_normalized", sa.String(length=32), nullable=True
        ),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "observed_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("raw_payload", _json_type(), nullable=True),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_sku_product_sync_history"),
        sa.UniqueConstraint(
            "snapshot_id", name="uk_sku_product_sync_history_snapshot_id"
        ),
    )
    op.create_index(
        "idx_sku_product_sync_history_sku_observed",
        "sku_product_sync_history",
        ["sku_id", "observed_at"],
    )
    op.create_index(
        "idx_sku_product_sync_history_run",
        "sku_product_sync_history",
        ["sync_run_id"],
    )
    op.create_index(
        "idx_sku_product_sync_history_product",
        "sku_product_sync_history",
        ["product_id"],
    )
    op.create_index(
        "idx_sku_product_sync_history_owner",
        "sku_product_sync_history",
        ["owner_account_id"],
    )
    op.create_index(
        "idx_sku_product_sync_history_payload",
        "sku_product_sync_history",
        ["payload_sha256"],
    )


def _create_settlement_scope_rule() -> None:
    op.create_table(
        "settlement_scope_rule",
        _id_column(),
        sa.Column("scope_rule_version", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=False),
        sa.Column("request_payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("effective_month", sa.String(length=7), nullable=False),
        sa.Column("owner_account_id", sa.String(length=128), nullable=False),
        sa.Column(
            "sale_channel_normalized", sa.String(length=32), nullable=False
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("change_reason", sa.String(length=512), nullable=False),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_settlement_scope_rule"),
        sa.UniqueConstraint(
            "scope_rule_version", name="uk_settlement_scope_rule_version"
        ),
        sa.UniqueConstraint(
            "idempotency_key_hash",
            "sale_channel_normalized",
            name="uk_settlement_scope_rule_idempotency_channel",
        ),
        sa.UniqueConstraint(
            "effective_month",
            "owner_account_id",
            "sale_channel_normalized",
            name="uk_settlement_scope_rule_slot",
        ),
        sa.CheckConstraint(
            "sale_channel_normalized IN ('live', 'short_video')",
            name="ck_settlement_scope_rule_sale_channel",
        ),
    )
    op.create_index(
        "idx_settlement_scope_rule_active",
        "settlement_scope_rule",
        ["is_active", "effective_month"],
    )


def _create_sku_fee_rule() -> None:
    op.create_table(
        "sku_fee_rule",
        _id_column(),
        sa.Column("rule_version", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=False),
        sa.Column("request_payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("sku_id", sa.String(length=128), nullable=False),
        sa.Column("sku_name_snapshot", sa.String(length=512), nullable=True),
        sa.Column(
            "product_scope_snapshot",
            sa.String(length=128),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "product_type_snapshot",
            sa.String(length=128),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "promotion_service_fee_rate",
            sa.Numeric(precision=8, scale=6),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "management_service_fee_rate",
            sa.Numeric(precision=8, scale=6),
            nullable=False,
            server_default="0",
        ),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "rule_status", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("previous_rule_version", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("change_reason", sa.String(length=512), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_sku_fee_rule"),
        sa.UniqueConstraint("rule_version", name="uk_sku_fee_rule_version"),
        sa.UniqueConstraint(
            "idempotency_key_hash",
            "sku_id",
            name="uk_sku_fee_rule_idempotency_sku",
        ),
        sa.UniqueConstraint(
            "sku_id", "effective_date", name="uk_sku_fee_rule_sku_date"
        ),
        sa.CheckConstraint(
            "promotion_service_fee_rate >= 0 "
            "AND promotion_service_fee_rate <= 1",
            name="ck_sku_fee_rule_promotion_rate",
        ),
        sa.CheckConstraint(
            "management_service_fee_rate >= 0 "
            "AND management_service_fee_rate <= 1",
            name="ck_sku_fee_rule_management_rate",
        ),
        sa.CheckConstraint(
            "rule_status IN (1, 2)", name="ck_sku_fee_rule_status"
        ),
    )
    op.create_index(
        "idx_sku_fee_rule_match",
        "sku_fee_rule",
        ["sku_id", "rule_status", "effective_at"],
    )


def _create_import_batch() -> None:
    op.create_table(
        "sku_fee_rule_import_batch",
        _id_column(),
        sa.Column("batch_id", sa.String(length=128), nullable=False),
        sa.Column("file_name", sa.String(length=512), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "batch_status", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "commit_mode", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column(
            "total_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "valid_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "success_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "failed_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("uploaded_by", sa.String(length=128), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "commit_idempotency_key_hash", sa.String(length=64), nullable=True
        ),
        sa.Column("commit_payload_sha256", sa.String(length=64), nullable=True),
        sa.Column("result_file_key", sa.String(length=512), nullable=True),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_sku_fee_rule_import_batch"),
        sa.UniqueConstraint(
            "batch_id", name="uk_sku_fee_rule_import_batch_id"
        ),
        sa.UniqueConstraint(
            "commit_idempotency_key_hash",
            name="uk_sku_fee_rule_import_batch_commit_key",
        ),
        sa.CheckConstraint(
            "batch_status IN (1, 2, 3, 4, 5, 6)",
            name="ck_sku_fee_rule_import_batch_status",
        ),
        sa.CheckConstraint(
            "commit_mode = 1", name="ck_sku_fee_rule_import_batch_commit_mode"
        ),
        sa.CheckConstraint(
            "total_count >= 0 AND valid_count >= 0 AND success_count >= 0 "
            "AND failed_count >= 0",
            name="ck_sku_fee_rule_import_batch_counts",
        ),
    )
    op.create_index(
        "idx_sku_fee_rule_import_batch_sha",
        "sku_fee_rule_import_batch",
        ["file_sha256"],
    )
    op.create_index(
        "idx_sku_fee_rule_import_batch_effective_date",
        "sku_fee_rule_import_batch",
        ["effective_date"],
    )
    op.create_index(
        "idx_sku_fee_rule_import_batch_user_status",
        "sku_fee_rule_import_batch",
        ["uploaded_by", "batch_status"],
    )


def _create_import_row() -> None:
    op.create_table(
        "sku_fee_rule_import_row",
        _id_column(),
        sa.Column("batch_id", sa.String(length=128), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("sku_name", sa.String(length=512), nullable=True),
        sa.Column("sku_id", sa.String(length=128), nullable=True),
        sa.Column(
            "promotion_service_fee_rate",
            sa.Numeric(precision=8, scale=6),
            nullable=True,
        ),
        sa.Column(
            "management_service_fee_rate",
            sa.Numeric(precision=8, scale=6),
            nullable=True,
        ),
        sa.Column(
            "validation_status", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "error_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("error_field", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("validation_errors_json", _json_type(), nullable=True),
        sa.Column("created_rule_version", sa.String(length=64), nullable=True),
        sa.Column("source_row_json", _json_type(), nullable=True),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_sku_fee_rule_import_row"),
        sa.UniqueConstraint(
            "batch_id",
            "row_number",
            name="uk_sku_fee_rule_import_row_number",
        ),
        sa.CheckConstraint(
            "row_number > 0", name="ck_sku_fee_rule_import_row_number"
        ),
        sa.CheckConstraint(
            "validation_status IN (1, 2, 3, 4, 5)",
            name="ck_sku_fee_rule_import_row_status",
        ),
        sa.CheckConstraint(
            "error_count >= 0", name="ck_sku_fee_rule_import_row_error_count"
        ),
    )
    op.create_index(
        "idx_sku_fee_rule_import_row_sku",
        "sku_fee_rule_import_row",
        ["sku_id"],
    )
    op.create_index(
        "idx_sku_fee_rule_import_row_status",
        "sku_fee_rule_import_row",
        ["batch_id", "validation_status"],
    )
    op.create_index(
        "idx_sku_fee_rule_import_row_error_field",
        "sku_fee_rule_import_row",
        ["error_field"],
    )
    op.create_index(
        "idx_sku_fee_rule_import_row_error_code",
        "sku_fee_rule_import_row",
        ["error_code"],
    )


def _guard_downgrade_against_new_data() -> None:
    bind = op.get_bind()
    for table_name in (
        "sku_fee_rule_import_row",
        "sku_fee_rule_import_batch",
        "sku_fee_rule",
        "settlement_scope_rule",
        "sku_product_sync_history",
    ):
        count = bind.scalar(sa.text(f"SELECT COUNT(*) FROM {table_name}"))
        if count:
            raise RuntimeError(
                "cannot downgrade product rule schema while new tables contain data: "
                f"{table_name}={count}"
            )

    platform_data_count = bind.scalar(
        sa.text(
            "SELECT COUNT(*) FROM dim_sku_product_rules WHERE "
            "sku_name IS NOT NULL OR product_id IS NOT NULL OR spu_id IS NOT NULL OR "
            "creator_account_id IS NOT NULL OR creator_account_name IS NOT NULL OR "
            "owner_account_id IS NOT NULL OR owner_account_name IS NOT NULL OR "
            "product_status_raw IS NOT NULL OR product_status_normalized IS NOT NULL OR "
            "sync_source IS NOT NULL OR sync_run_id IS NOT NULL OR "
            "last_synced_at IS NOT NULL OR manual_modified_by IS NOT NULL OR "
            "manual_modified_at IS NOT NULL"
        )
    )
    if platform_data_count:
        raise RuntimeError(
            "cannot downgrade product rule schema while SKU platform fields contain data: "
            f"rows={platform_data_count}"
        )


def _restore_legacy_sku_fact_table() -> None:
    op.create_table(
        "dim_sku_product_rules_legacy",
        sa.Column("sku_id", sa.Text(), nullable=False),
        sa.Column("product_scope", sa.Text(), nullable=False, server_default=""),
        sa.Column("product_type", sa.Text(), nullable=False),
        sa.Column("product_name", sa.Text(), nullable=True),
        sa.Column(
            "commission_rate",
            sa.Numeric(precision=6, scale=4),
            nullable=False,
        ),
        sa.Column("is_service_product", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("sku_id"),
    )
    op.execute(
        sa.text(
            "INSERT INTO dim_sku_product_rules_legacy ("
            "sku_id, product_scope, product_type, product_name, commission_rate, "
            "is_service_product, updated_at"
            ") SELECT sku_id, product_scope, product_type, product_name, "
            "commission_rate, is_service_product, gmt_modified "
            "FROM dim_sku_product_rules"
        )
    )
    op.drop_table("dim_sku_product_rules")
    op.rename_table("dim_sku_product_rules_legacy", "dim_sku_product_rules")
    op.create_index(
        "ix_dim_sku_product_rules_product_scope",
        "dim_sku_product_rules",
        ["product_scope"],
    )
    op.create_index(
        "ix_dim_sku_product_rules_product_type",
        "dim_sku_product_rules",
        ["product_type"],
    )
