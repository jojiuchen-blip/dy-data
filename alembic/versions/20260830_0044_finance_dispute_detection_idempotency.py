"""protect finance dispute detection idempotency

Revision ID: 20260830_0044
Revises: 20260824_0043
Create Date: 2026-08-30 21:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260830_0044"
down_revision = "20260824_0043"
branch_labels = None
depends_on = None


INDEX_NAME = "uq_job_runs_finance_dispute_detection_idempotency_key"
INDEX_PREDICATE = (
    "job_name = 'finance_dispute_detection' "
    "AND idempotency_key_hash IS NOT NULL"
)


def upgrade() -> None:
    """Add durable detection fencing/state and protect replay ownership."""

    op.add_column(
        "job_runs",
        sa.Column("claim_token", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "job_runs",
        sa.Column("state_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE job_runs SET state_updated_at = "
            "COALESCE(finished_at, started_at) "
            "WHERE state_updated_at IS NULL"
        )
    )

    op.create_index(
        INDEX_NAME,
        "job_runs",
        ["job_name", "idempotency_key_hash"],
        unique=True,
        postgresql_where=sa.text(INDEX_PREDICATE),
        sqlite_where=sa.text(INDEX_PREDICATE),
    )


def downgrade() -> None:
    """Remove detection-specific fencing and idempotency state."""

    op.drop_index(INDEX_NAME, table_name="job_runs")
    op.drop_column("job_runs", "state_updated_at")
    op.drop_column("job_runs", "claim_token")
