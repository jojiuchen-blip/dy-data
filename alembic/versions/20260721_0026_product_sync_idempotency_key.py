"""protect product-sync idempotency keys across all run states

Revision ID: 20260721_0026
Revises: 20260721_0025
Create Date: 2026-07-21 02:05:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260721_0026"
down_revision = "20260721_0025"
branch_labels = None
depends_on = None


PRODUCT_SYNC_WITH_IDEMPOTENCY_KEY = sa.text(
    "job_name = 'product_sync' AND idempotency_key_hash IS NOT NULL"
)


def upgrade() -> None:
    op.add_column(
        "job_runs",
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "uq_job_runs_product_sync_idempotency_key",
        "job_runs",
        ["job_name", "idempotency_key_hash"],
        unique=True,
        sqlite_where=PRODUCT_SYNC_WITH_IDEMPOTENCY_KEY,
        postgresql_where=PRODUCT_SYNC_WITH_IDEMPOTENCY_KEY,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_job_runs_product_sync_idempotency_key",
        table_name="job_runs",
    )
    op.drop_column("job_runs", "idempotency_key_hash")
