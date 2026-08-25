"""add finance closure versioning and audit schema

Revision ID: 20260821_0028
Revises: 20260819_0037
Create Date: 2026-08-21 09:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260821_0028"
down_revision = "20260819_0037"
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
    _create_statement_confirmations()
    _create_disputes()
    _create_dispute_orders()
    _create_invoice_records()
    _create_invoice_status_events()
    _create_import_batches()
    _create_import_rows()
    _create_operation_audit()


def downgrade() -> None:
    _refuse_lossy_downgrade()
    op.drop_table("finance_operation_audit")
    op.drop_table("finance_import_row")
    op.drop_table("finance_import_batch")
    op.drop_table("invoice_status_event")
    op.drop_table("invoice_record")
    op.drop_table("settlement_dispute_order")
    op.drop_table("settlement_dispute")
    op.drop_table("settlement_statement_confirmation")


def _refuse_lossy_downgrade() -> None:
    table_names = (
        "finance_operation_audit",
        "finance_import_row",
        "finance_import_batch",
        "invoice_status_event",
        "invoice_record",
        "settlement_dispute_order",
        "settlement_dispute",
        "settlement_statement_confirmation",
    )
    bind = op.get_bind()
    populated_tables = [
        table_name
        for table_name in table_names
        if bind.execute(sa.text(f"SELECT 1 FROM {table_name} LIMIT 1")).first()
        is not None
    ]
    if populated_tables:
        raise RuntimeError(
            "cannot downgrade 20260821_0028: finance facts exist in "
            + ", ".join(populated_tables)
        )


def _create_statement_confirmations() -> None:
    op.create_table(
        "settlement_statement_confirmation",
        _id_column(),
        sa.Column("confirmation_id", sa.String(length=128), nullable=False),
        sa.Column("statement_id", sa.String(length=128), nullable=False),
        sa.Column("fee_direction", sa.Integer(), nullable=False),
        sa.Column("confirmation_status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("confirmed_amount_cent", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("confirmed_by", sa.String(length=128), nullable=False),
        sa.Column(
            "confirmed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_settlement_statement_confirmation"),
        sa.UniqueConstraint("confirmation_id", name="uk_statement_confirmation_id"),
        sa.UniqueConstraint(
            "statement_id",
            "fee_direction",
            name="uk_statement_confirmation_direction",
        ),
        sa.CheckConstraint(
            "fee_direction IN (1, 2)", name="ck_statement_confirmation_direction"
        ),
        sa.CheckConstraint(
            "confirmation_status IN (1, 2)",
            name="ck_statement_confirmation_status",
        ),
    )
    op.create_index(
        "idx_statement_confirmation_by",
        "settlement_statement_confirmation",
        ["confirmed_by"],
    )
    op.create_index(
        "idx_statement_confirmation_at",
        "settlement_statement_confirmation",
        ["confirmed_at"],
    )


def _create_disputes() -> None:
    op.create_table(
        "settlement_dispute",
        _id_column(),
        sa.Column("dispute_id", sa.String(length=128), nullable=False),
        sa.Column("statement_id", sa.String(length=128), nullable=False),
        sa.Column("store_id", sa.String(length=128), nullable=False),
        sa.Column("statement_month", sa.String(length=7), nullable=False),
        sa.Column("fee_direction", sa.Integer(), nullable=False),
        sa.Column("dispute_type", sa.Integer(), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("disputed_amount_cent", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("contact_name", sa.String(length=128), nullable=False),
        sa.Column("contact_phone_ciphertext", sa.Text(), nullable=False),
        sa.Column("evidence_json", _json_type(), nullable=False),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("result_statement_id", sa.String(length=128), nullable=True),
        sa.Column("submitted_by", sa.String(length=128), nullable=False),
        sa.Column("processed_by", sa.String(length=128), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_settlement_dispute"),
        sa.UniqueConstraint("dispute_id", name="uk_settlement_dispute_id"),
        sa.CheckConstraint(
            "fee_direction IN (1, 2)", name="ck_settlement_dispute_direction"
        ),
        sa.CheckConstraint(
            "dispute_type IN (1, 2, 3, 4)", name="ck_settlement_dispute_type"
        ),
        sa.CheckConstraint(
            "status IN (1, 2, 3, 4, 5, 6)", name="ck_settlement_dispute_status"
        ),
    )
    op.create_index("idx_settlement_dispute_statement", "settlement_dispute", ["statement_id"])
    op.create_index(
        "idx_settlement_dispute_store_month",
        "settlement_dispute",
        ["store_id", "statement_month"],
    )
    op.create_index("idx_settlement_dispute_status", "settlement_dispute", ["status"])
    op.create_index(
        "idx_settlement_dispute_submitted_by", "settlement_dispute", ["submitted_by"]
    )
    op.create_index(
        "idx_settlement_dispute_processed_by", "settlement_dispute", ["processed_by"]
    )
    op.create_index(
        "idx_settlement_dispute_result_statement",
        "settlement_dispute",
        ["result_statement_id"],
    )


def _create_dispute_orders() -> None:
    op.create_table(
        "settlement_dispute_order",
        _id_column(),
        sa.Column("dispute_id", sa.String(length=128), nullable=False),
        sa.Column("order_id", sa.String(length=128), nullable=False),
        sa.Column("coupon_id", sa.String(length=128), nullable=True),
        sa.Column("disputed_amount_cent", sa.BigInteger(), nullable=False, server_default="0"),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_settlement_dispute_order"),
        sa.UniqueConstraint(
            "dispute_id",
            "order_id",
            "coupon_id",
            name="uk_settlement_dispute_order_scope",
        ),
    )
    op.create_index(
        "idx_settlement_dispute_order_dispute",
        "settlement_dispute_order",
        ["dispute_id"],
    )


def _create_invoice_records() -> None:
    op.create_table(
        "invoice_record",
        _id_column(),
        sa.Column("invoice_id", sa.String(length=128), nullable=False),
        sa.Column("store_id", sa.String(length=128), nullable=False),
        sa.Column("statement_month", sa.String(length=7), nullable=False),
        sa.Column("statement_id", sa.String(length=128), nullable=False),
        sa.Column("fee_direction", sa.Integer(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("invoice_number", sa.String(length=20), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("invoice_amount_cent", sa.BigInteger(), nullable=False),
        sa.Column("invoice_status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_type", sa.Integer(), nullable=False),
        sa.Column("import_batch_id", sa.String(length=128), nullable=True),
        sa.Column("registered_by", sa.String(length=128), nullable=False),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_invoice_record"),
        sa.UniqueConstraint("invoice_id", name="uk_invoice_record_id"),
        sa.UniqueConstraint(
            "store_id",
            "statement_month",
            "fee_direction",
            "version_no",
            name="uk_invoice_record_version",
        ),
        sa.CheckConstraint("fee_direction IN (1, 2)", name="ck_invoice_record_direction"),
        sa.CheckConstraint(
            "invoice_status IN (1, 2, 3, 4)", name="ck_invoice_record_status"
        ),
        sa.CheckConstraint("source_type IN (1, 2, 3)", name="ck_invoice_record_source"),
        sa.CheckConstraint("invoice_amount_cent >= 0", name="ck_invoice_record_amount"),
    )
    op.create_index(
        "idx_invoice_record_current_slot",
        "invoice_record",
        ["store_id", "statement_month", "fee_direction"],
        unique=True,
        postgresql_where=sa.text("is_current"),
        sqlite_where=sa.text("is_current"),
    )
    op.create_index("idx_invoice_record_statement", "invoice_record", ["statement_id"])
    op.create_index("idx_invoice_record_number", "invoice_record", ["invoice_number"])
    op.create_index("idx_invoice_record_date", "invoice_record", ["invoice_date"])
    op.create_index("idx_invoice_record_status", "invoice_record", ["invoice_status"])
    op.create_index("idx_invoice_record_import_batch", "invoice_record", ["import_batch_id"])
    op.create_index("idx_invoice_record_registered_by", "invoice_record", ["registered_by"])
    op.create_index("idx_invoice_record_registered_at", "invoice_record", ["registered_at"])


def _create_invoice_status_events() -> None:
    op.create_table(
        "invoice_status_event",
        _id_column(),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("invoice_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.Integer(), nullable=True),
        sa.Column("to_status", sa.Integer(), nullable=False),
        sa.Column("operator_id", sa.String(length=128), nullable=False),
        sa.Column("import_batch_id", sa.String(length=128), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_invoice_status_event"),
        sa.UniqueConstraint("event_id", name="uk_invoice_status_event_id"),
        sa.CheckConstraint(
            "event_type IN (1, 2, 3, 4)", name="ck_invoice_status_event_type"
        ),
        sa.CheckConstraint(
            "to_status IN (1, 2, 3, 4)", name="ck_invoice_status_event_to"
        ),
    )
    op.create_index("idx_invoice_status_event_invoice", "invoice_status_event", ["invoice_id"])
    op.create_index("idx_invoice_status_event_operator", "invoice_status_event", ["operator_id"])
    op.create_index(
        "idx_invoice_status_event_import_batch", "invoice_status_event", ["import_batch_id"]
    )
    op.create_index(
        "idx_invoice_status_event_occurred_at", "invoice_status_event", ["occurred_at"]
    )


def _create_import_batches() -> None:
    op.create_table(
        "finance_import_batch",
        _id_column(),
        sa.Column("batch_id", sa.String(length=128), nullable=False),
        sa.Column("import_type", sa.Integer(), nullable=False),
        sa.Column("statement_month", sa.String(length=7), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("normalized_sha256", sa.String(length=64), nullable=False),
        sa.Column("read_version", sa.BigInteger(), nullable=False),
        sa.Column("current_version", sa.BigInteger(), nullable=False),
        sa.Column("batch_status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_changed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("submitted_by", sa.String(length=128), nullable=False),
        sa.Column("committed_by", sa.String(length=128), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_finance_import_batch"),
        sa.UniqueConstraint("batch_id", name="uk_finance_import_batch_id"),
        sa.CheckConstraint(
            "import_type IN (1, 2, 3, 4)", name="ck_finance_import_batch_type"
        ),
        sa.CheckConstraint(
            "batch_status IN (1, 2, 3, 4, 5, 6, 7, 8)",
            name="ck_finance_import_batch_status",
        ),
    )
    op.create_index(
        "idx_finance_import_batch_type_month",
        "finance_import_batch",
        ["import_type", "statement_month"],
    )
    op.create_index("idx_finance_import_batch_file_sha256", "finance_import_batch", ["file_sha256"])
    op.create_index(
        "idx_finance_import_batch_normalized_sha256",
        "finance_import_batch",
        ["normalized_sha256"],
    )
    op.create_index("idx_finance_import_batch_status", "finance_import_batch", ["batch_status"])
    op.create_index(
        "idx_finance_import_batch_submitted_by", "finance_import_batch", ["submitted_by"]
    )
    op.create_index(
        "idx_finance_import_batch_committed_by", "finance_import_batch", ["committed_by"]
    )
    op.create_index(
        "idx_finance_import_batch_submitted_at", "finance_import_batch", ["submitted_at"]
    )
    op.create_index(
        "idx_finance_import_batch_committed_at", "finance_import_batch", ["committed_at"]
    )


def _create_import_rows() -> None:
    op.create_table(
        "finance_import_row",
        _id_column(),
        sa.Column("batch_id", sa.String(length=128), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("business_key", sa.String(length=512), nullable=False),
        sa.Column("normalized_payload", _json_type(), nullable=False),
        sa.Column("row_status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("validation_errors", _json_type(), nullable=False),
        sa.Column("target_record_id", sa.String(length=128), nullable=True),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_finance_import_row"),
        sa.UniqueConstraint(
            "batch_id", "row_number", name="uk_finance_import_row_number"
        ),
        sa.CheckConstraint(
            "row_status IN (1, 2, 3, 4, 5)", name="ck_finance_import_row_status"
        ),
    )
    op.create_index("idx_finance_import_row_business_key", "finance_import_row", ["business_key"])
    op.create_index("idx_finance_import_row_status", "finance_import_row", ["row_status"])
    op.create_index("idx_finance_import_row_target", "finance_import_row", ["target_record_id"])


def _create_operation_audit() -> None:
    op.create_table(
        "finance_operation_audit",
        _id_column(),
        sa.Column("audit_id", sa.String(length=128), nullable=False),
        sa.Column("operation_type", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=128), nullable=False),
        sa.Column("operator_id", sa.String(length=128), nullable=False),
        sa.Column("operator_role", sa.Integer(), nullable=False),
        sa.Column("before_snapshot", _json_type(), nullable=True),
        sa.Column("after_snapshot", _json_type(), nullable=True),
        sa.Column("result_status", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_finance_operation_audit"),
        sa.UniqueConstraint("audit_id", name="uk_finance_operation_audit_id"),
        sa.CheckConstraint(
            "operator_role IN (1, 2, 3)", name="ck_finance_operation_audit_role"
        ),
        sa.CheckConstraint(
            "result_status IN (1, 2, 3)", name="ck_finance_operation_audit_result"
        ),
    )
    op.create_index(
        "idx_finance_operation_audit_operation", "finance_operation_audit", ["operation_type"]
    )
    op.create_index(
        "idx_finance_operation_audit_target",
        "finance_operation_audit",
        ["target_type", "target_id"],
    )
    op.create_index(
        "idx_finance_operation_audit_operator", "finance_operation_audit", ["operator_id"]
    )
    op.create_index(
        "idx_finance_operation_audit_result", "finance_operation_audit", ["result_status"]
    )
    op.create_index(
        "idx_finance_operation_audit_request", "finance_operation_audit", ["request_id"]
    )
    op.create_index(
        "idx_finance_operation_audit_occurred_at",
        "finance_operation_audit",
        ["occurred_at"],
    )
