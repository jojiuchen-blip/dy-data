"""persist finance import result fields

Revision ID: 20260821_0035
Revises: 20260821_0034
Create Date: 2026-08-21 14:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260821_0035"
down_revision = "20260821_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add exact manufacturer-result values without changing prior versions."""
    op.add_column(
        "invoice_record", sa.Column("factory_deduction_date", sa.Date(), nullable=True)
    )
    op.add_column(
        "invoice_record",
        sa.Column("factory_deduction_amount_cent", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "invoice_status_event", sa.Column("result_reason", sa.String(length=1000))
    )
    op.add_column(
        "invoice_status_event", sa.Column("business_date", sa.Date(), nullable=True)
    )
    op.add_column(
        "invoice_status_event",
        sa.Column("business_amount_cent", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    """Remove manufacturer-result fields while preserving the prior schema."""
    op.drop_column("invoice_status_event", "business_amount_cent")
    op.drop_column("invoice_status_event", "business_date")
    op.drop_column("invoice_status_event", "result_reason")
    op.drop_column("invoice_record", "factory_deduction_amount_cent")
    op.drop_column("invoice_record", "factory_deduction_date")
