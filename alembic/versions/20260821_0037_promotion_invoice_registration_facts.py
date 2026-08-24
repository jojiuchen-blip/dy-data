"""persist promotion invoice registration facts and settlement batches

Revision ID: 20260821_0037
Revises: 20260821_0036
Create Date: 2026-08-21 16:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260821_0037"
down_revision = "20260821_0036"
branch_labels = None
depends_on = None

PROMOTION_INVOICE_BUYER_NAME = "比亚迪汽车销售有限公司"
PROMOTION_INVOICE_TAX_RATE_PERCENT = 6


def _backfill_settlement_batch_month() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                """
                UPDATE promotion_invoice_allocation AS allocation
                SET settlement_batch_month = (
                    SELECT to_char(
                        CASE
                            WHEN EXTRACT(
                                DAY FROM invoice.registered_at
                                AT TIME ZONE 'Asia/Shanghai'
                            ) <= 10
                            THEN date_trunc(
                                'month',
                                invoice.registered_at AT TIME ZONE 'Asia/Shanghai'
                            ) - INTERVAL '1 month'
                            ELSE date_trunc(
                                'month',
                                invoice.registered_at AT TIME ZONE 'Asia/Shanghai'
                            )
                        END,
                        'YYYY-MM'
                    )
                    FROM promotion_invoice AS invoice
                    WHERE invoice.invoice_id = allocation.invoice_id
                )
                """
            )
        )
        return

    op.execute(
        sa.text(
            """
            UPDATE promotion_invoice_allocation
            SET settlement_batch_month = (
                SELECT CASE
                    WHEN CAST(
                        strftime(
                            '%d', datetime(invoice.registered_at, '+8 hours')
                        ) AS INTEGER
                    ) <= 10
                    THEN strftime(
                        '%Y-%m',
                        datetime(
                            invoice.registered_at,
                            '+8 hours',
                            'start of month',
                            '-1 month'
                        )
                    )
                    ELSE strftime(
                        '%Y-%m', datetime(invoice.registered_at, '+8 hours')
                    )
                END
                FROM promotion_invoice AS invoice
                WHERE invoice.invoice_id = promotion_invoice_allocation.invoice_id
            )
            """
        )
    )


def upgrade() -> None:
    """Add immutable buyer/tax facts and backfill Beijing settlement batches."""
    with op.batch_alter_table("promotion_invoice") as batch_op:
        batch_op.add_column(sa.Column("buyer_name", sa.String(length=255)))
        batch_op.add_column(sa.Column("tax_rate_percent", sa.Integer()))
    with op.batch_alter_table("promotion_invoice_allocation") as batch_op:
        batch_op.add_column(
            sa.Column("settlement_batch_month", sa.String(length=7))
        )

    op.execute(
        sa.text(
            """
            UPDATE promotion_invoice
            SET buyer_name = :buyer_name,
                tax_rate_percent = :tax_rate_percent
            """
        ).bindparams(
            buyer_name=PROMOTION_INVOICE_BUYER_NAME,
            tax_rate_percent=PROMOTION_INVOICE_TAX_RATE_PERCENT,
        )
    )
    _backfill_settlement_batch_month()

    with op.batch_alter_table("promotion_invoice") as batch_op:
        batch_op.alter_column(
            "buyer_name", existing_type=sa.String(length=255), nullable=False
        )
        batch_op.alter_column(
            "tax_rate_percent", existing_type=sa.Integer(), nullable=False
        )
        batch_op.create_check_constraint(
            "ck_promotion_invoice_tax_rate", "tax_rate_percent = 6"
        )
    with op.batch_alter_table("promotion_invoice_allocation") as batch_op:
        batch_op.alter_column(
            "settlement_batch_month",
            existing_type=sa.String(length=7),
            nullable=False,
        )


def downgrade() -> None:
    """Remove promotion invoice registration facts and settlement batches."""
    with op.batch_alter_table("promotion_invoice_allocation") as batch_op:
        batch_op.drop_column("settlement_batch_month")
    with op.batch_alter_table("promotion_invoice") as batch_op:
        batch_op.drop_constraint(
            "ck_promotion_invoice_tax_rate", type_="check"
        )
        batch_op.drop_column("tax_rate_percent")
        batch_op.drop_column("buyer_name")
