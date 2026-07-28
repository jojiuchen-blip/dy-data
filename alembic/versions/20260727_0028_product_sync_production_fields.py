"""add production product synchronization state

Revision ID: 20260727_0028
Revises: 20260727_0027
Create Date: 2026-07-27 16:00:00
"""

from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa


revision = "20260727_0028"
down_revision = "20260727_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dim_sku_product_rules",
        sa.Column("product_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "dim_sku_product_rules",
        sa.Column("sync_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "dim_sku_product_rules",
        sa.Column("sync_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "sku_product_sync_history",
        sa.Column("product_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "sku_product_sync_history",
        sa.Column("sync_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "sku_product_sync_history",
        sa.Column("sync_error", sa.Text(), nullable=True),
    )
    _create_sync_status_indexes()


def downgrade() -> None:
    _drop_sync_status_indexes()
    op.drop_column("sku_product_sync_history", "sync_error")
    op.drop_column("sku_product_sync_history", "sync_status")
    op.drop_column("sku_product_sync_history", "product_updated_at")

    op.drop_column("dim_sku_product_rules", "sync_error")
    op.drop_column("dim_sku_product_rules", "sync_status")
    op.drop_column("dim_sku_product_rules", "product_updated_at")


SYNC_STATUS_INDEXES = (
    (
        "idx_dim_sku_product_rules_sync_status",
        "dim_sku_product_rules",
    ),
    (
        "idx_sku_product_sync_history_status",
        "sku_product_sync_history",
    ),
)


def _create_sync_status_indexes() -> None:
    if op.get_bind().dialect.name != "postgresql":
        for index_name, table_name in SYNC_STATUS_INDEXES:
            op.create_index(index_name, table_name, ["sync_status"])
        return
    with context.get_context().autocommit_block():
        op.execute("SET statement_timeout = '5min'")
        try:
            for index_name, table_name in SYNC_STATUS_INDEXES:
                op.execute(
                    f"CREATE INDEX CONCURRENTLY {index_name} "
                    f"ON {table_name} (sync_status)"
                )
        finally:
            op.execute("RESET statement_timeout")


def _drop_sync_status_indexes() -> None:
    if op.get_bind().dialect.name != "postgresql":
        for index_name, table_name in reversed(SYNC_STATUS_INDEXES):
            op.drop_index(index_name, table_name=table_name)
        return
    with context.get_context().autocommit_block():
        for index_name, _table_name in reversed(SYNC_STATUS_INDEXES):
            op.execute(f"DROP INDEX CONCURRENTLY {index_name}")
