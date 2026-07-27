"""protect the single active product-sync execution slot

Revision ID: 20260721_0025
Revises: 20260720_0024
Create Date: 2026-07-21 01:15:00
"""

from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa


revision = "20260721_0025"
down_revision = "20260720_0024"
branch_labels = None
depends_on = None


ACTIVE_PRODUCT_SYNC = sa.text(
    "job_name = 'product_sync' AND status IN ('queued', 'running')"
)


def upgrade() -> None:
    if not context.is_offline_mode():
        duplicate_count = op.get_bind().execute(
            sa.text(
                "SELECT count(*) FROM ("
                "SELECT job_name FROM job_runs "
                "WHERE job_name = 'product_sync' "
                "AND status IN ('queued', 'running') "
                "GROUP BY job_name HAVING count(*) > 1"
                ") AS duplicate_active_product_sync"
            )
        ).scalar_one()
        if int(duplicate_count) > 0:
            raise RuntimeError(
                "duplicate active product-sync jobs block the active-slot constraint"
            )
    op.create_index(
        "uq_job_runs_product_sync_active_slot",
        "job_runs",
        ["job_name"],
        unique=True,
        sqlite_where=ACTIVE_PRODUCT_SYNC,
        postgresql_where=ACTIVE_PRODUCT_SYNC,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_job_runs_product_sync_active_slot",
        table_name="job_runs",
    )
