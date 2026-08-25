"""allow an invoice number to repeat across immutable versions

Revision ID: 20260821_0033
Revises: 20260821_0032
Create Date: 2026-08-21 12:25:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260821_0033"
down_revision = "20260821_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Replace all-history invoice-number uniqueness with current-only uniqueness."""
    with op.batch_alter_table("promotion_invoice") as batch_op:
        batch_op.drop_constraint("uk_promotion_invoice_number", type_="unique")
    op.create_index(
        "idx_promotion_invoice_current_number",
        "promotion_invoice",
        ["invoice_number"],
        unique=True,
        postgresql_where=sa.text("is_current"),
        sqlite_where=sa.text("is_current"),
    )


def downgrade() -> None:
    """Restore the original all-history invoice-number constraint."""
    op.drop_index(
        "idx_promotion_invoice_current_number", table_name="promotion_invoice"
    )
    with op.batch_alter_table("promotion_invoice") as batch_op:
        batch_op.create_unique_constraint(
            "uk_promotion_invoice_number", ["invoice_number"]
        )
