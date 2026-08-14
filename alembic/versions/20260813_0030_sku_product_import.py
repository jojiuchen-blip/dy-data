"""add sku product import batches

Revision ID: 20260813_0030
Revises: 20260804_0029
Create Date: 2026-08-13 17:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260813_0030"
down_revision = "20260804_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sku_product_import_batch",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("batch_id", sa.String(128), nullable=False),
        sa.Column("file_name", sa.String(512), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("batch_status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("uploaded_by", sa.String(128), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True)),
        sa.Column("committed_at", sa.DateTime(timezone=True)),
        sa.Column("gmt_create", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gmt_modified", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("batch_id", name="uk_sku_product_import_batch_id"),
        sa.CheckConstraint("batch_status IN (1, 2, 3, 4, 5, 6)", name="ck_sku_product_import_batch_status"),
    )
    op.create_index("idx_sku_product_import_batch_user_status", "sku_product_import_batch", ["uploaded_by", "batch_status"])
    op.create_table(
        "sku_product_import_row",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("batch_id", sa.String(128), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.String(128)),
        sa.Column("product_scope", sa.String(128)),
        sa.Column("product_type", sa.String(128)),
        sa.Column("keep_product_scope", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("keep_product_type", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("validation_status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("validation_errors_json", sa.JSON()),
        sa.Column("gmt_create", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gmt_modified", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("batch_id", "row_number", name="uk_sku_product_import_row_number"),
    )
    op.create_index("idx_sku_product_import_row_sku", "sku_product_import_row", ["sku_id"])
    op.create_index("idx_sku_product_import_row_status", "sku_product_import_row", ["batch_id", "validation_status"])


def downgrade() -> None:
    op.drop_table("sku_product_import_row")
    op.drop_table("sku_product_import_batch")
