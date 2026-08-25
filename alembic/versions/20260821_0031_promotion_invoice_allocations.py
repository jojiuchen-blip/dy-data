"""add promotion invoice headers and accounting-period allocations

Revision ID: 20260821_0031
Revises: 20260821_0030
Create Date: 2026-08-21 10:55:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260821_0031"
down_revision = "20260821_0030"
branch_labels = None
depends_on = None


def _id_column() -> sa.Column:
    if op.get_bind().dialect.name == "sqlite":
        return sa.Column("id", sa.Integer(), nullable=False, autoincrement=True)
    return sa.Column(
        "id", sa.BigInteger(), sa.Identity(), nullable=False, autoincrement=True
    )


def upgrade() -> None:
    op.create_table(
        "promotion_invoice",
        _id_column(),
        sa.Column("invoice_id", sa.String(length=128), nullable=False),
        sa.Column("store_id", sa.String(length=128), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("supersedes_invoice_id", sa.String(length=128)),
        sa.Column("invoice_number", sa.String(length=20), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("invoice_amount_cent", sa.BigInteger(), nullable=False),
        sa.Column("invoice_status", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("registered_by", sa.String(length=128), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(length=64)),
        sa.Column("request_payload_sha256", sa.String(length=64)),
        sa.Column("gmt_create", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gmt_modified", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_promotion_invoice"),
        sa.UniqueConstraint("invoice_id", name="uk_promotion_invoice_id"),
        sa.UniqueConstraint("invoice_number", name="uk_promotion_invoice_number"),
        sa.UniqueConstraint("idempotency_key_hash", name="uk_promotion_invoice_idempotency_key"),
        sa.CheckConstraint("version_no > 0", name="ck_promotion_invoice_version"),
        sa.CheckConstraint("invoice_status IN (2, 3, 4)", name="ck_promotion_invoice_status"),
        sa.CheckConstraint("invoice_amount_cent >= 0", name="ck_promotion_invoice_amount"),
    )
    op.create_index("idx_promotion_invoice_current", "promotion_invoice", ["store_id", "is_current"])
    op.create_table(
        "promotion_invoice_allocation",
        _id_column(),
        sa.Column("allocation_id", sa.String(length=128), nullable=False),
        sa.Column("invoice_id", sa.String(length=128), nullable=False),
        sa.Column("store_id", sa.String(length=128), nullable=False),
        sa.Column("statement_id", sa.String(length=128), nullable=False),
        sa.Column("statement_month", sa.String(length=7), nullable=False),
        sa.Column("allocated_amount_cent", sa.BigInteger(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("gmt_create", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gmt_modified", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_promotion_invoice_allocation"),
        sa.UniqueConstraint("allocation_id", name="uk_promotion_invoice_allocation_id"),
        sa.UniqueConstraint("invoice_id", "statement_id", name="uk_promotion_invoice_allocation_statement"),
        sa.CheckConstraint("allocated_amount_cent >= 0", name="ck_promotion_invoice_allocation_amount"),
    )
    op.create_index("idx_promotion_invoice_allocation_invoice", "promotion_invoice_allocation", ["invoice_id"])
    op.create_index("idx_promotion_invoice_allocation_current_period", "promotion_invoice_allocation", ["store_id", "statement_month"], unique=True, postgresql_where=sa.text("is_current"), sqlite_where=sa.text("is_current"))


def downgrade() -> None:
    op.drop_index("idx_promotion_invoice_allocation_current_period", table_name="promotion_invoice_allocation")
    op.drop_index("idx_promotion_invoice_allocation_invoice", table_name="promotion_invoice_allocation")
    op.drop_table("promotion_invoice_allocation")
    op.drop_index("idx_promotion_invoice_current", table_name="promotion_invoice")
    op.drop_table("promotion_invoice")
