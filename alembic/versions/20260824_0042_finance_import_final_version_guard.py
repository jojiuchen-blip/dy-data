"""guard finalized finance-import version allocation

Revision ID: 20260824_0042
Revises: 20260824_0041
Create Date: 2026-08-24 16:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260824_0042"
down_revision = "20260824_0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Prevent two finalized batches from claiming one logical version."""
    op.create_index(
        "uk_finance_import_batch_final_version",
        "finance_import_batch",
        ["import_type", "statement_month", "current_version"],
        unique=True,
        postgresql_where=sa.text("batch_status IN (5, 8, 9)"),
        sqlite_where=sa.text("batch_status IN (5, 8, 9)"),
    )


def downgrade() -> None:
    """Remove only the guard; finalized import facts remain untouched."""
    op.drop_index(
        "uk_finance_import_batch_final_version",
        table_name="finance_import_batch",
    )
