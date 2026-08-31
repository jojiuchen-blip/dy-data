"""persist store-entered promotion invoice fields

Revision ID: 20260831_0044
Revises: 20260824_0043
Create Date: 2026-08-31 18:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260831_0044"
down_revision = "20260824_0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add encrypted filler phone and immutable tax split facts."""
    with op.batch_alter_table("promotion_invoice") as batch_op:
        batch_op.add_column(
            sa.Column("filler_phone_ciphertext", sa.Text(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("net_amount_cent", sa.BigInteger(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("tax_amount_cent", sa.BigInteger(), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_promotion_invoice_net_amount",
            "net_amount_cent IS NULL OR net_amount_cent >= 0",
        )
        batch_op.create_check_constraint(
            "ck_promotion_invoice_tax_amount",
            "tax_amount_cent IS NULL OR tax_amount_cent >= 0",
        )
        batch_op.create_check_constraint(
            "ck_promotion_invoice_amount_identity",
            "(net_amount_cent IS NULL AND tax_amount_cent IS NULL) OR "
            "(net_amount_cent IS NOT NULL AND tax_amount_cent IS NOT NULL "
            "AND ABS(net_amount_cent + tax_amount_cent - invoice_amount_cent) <= 1)",
        )


def downgrade() -> None:
    """Remove manual fields only when no immutable facts would be lost."""
    bind = op.get_bind()
    populated = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM promotion_invoice
            WHERE filler_phone_ciphertext IS NOT NULL
               OR net_amount_cent IS NOT NULL
               OR tax_amount_cent IS NOT NULL
            """
        )
    ).scalar_one()
    if populated:
        raise RuntimeError(
            "cannot downgrade 20260831_0044: promotion invoice manual facts exist"
        )

    with op.batch_alter_table("promotion_invoice") as batch_op:
        batch_op.drop_constraint(
            "ck_promotion_invoice_amount_identity", type_="check"
        )
        batch_op.drop_constraint(
            "ck_promotion_invoice_tax_amount", type_="check"
        )
        batch_op.drop_constraint(
            "ck_promotion_invoice_net_amount", type_="check"
        )
        batch_op.drop_column("tax_amount_cent")
        batch_op.drop_column("net_amount_cent")
        batch_op.drop_column("filler_phone_ciphertext")
