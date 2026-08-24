"""allow signed promotion invoice allocations

Revision ID: 20260821_0040
Revises: 20260821_0039
Create Date: 2026-08-24 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260821_0040"
down_revision = "20260821_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Allow complete negative periods to participate in invoice groups."""

    with op.batch_alter_table("promotion_invoice_allocation") as batch_op:
        batch_op.drop_constraint(
            "ck_promotion_invoice_allocation_amount",
            type_="check",
        )


def downgrade() -> None:
    """Restore the legacy non-negative allocation constraint."""

    negative_count = op.get_bind().execute(
        sa.text(
            "SELECT COUNT(*) FROM promotion_invoice_allocation "
            "WHERE allocated_amount_cent < 0"
        )
    ).scalar_one()
    if negative_count:
        raise RuntimeError(
            "cannot downgrade 20260821_0040: negative promotion invoice "
            "allocations exist; keep revision 0040 or first reverse the signed "
            "allocation facts with an audited corrective invoice version"
        )

    with op.batch_alter_table("promotion_invoice_allocation") as batch_op:
        batch_op.create_check_constraint(
            "ck_promotion_invoice_allocation_amount",
            "allocated_amount_cent >= 0",
        )
