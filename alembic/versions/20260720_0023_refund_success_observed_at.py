"""freeze the first successful observation time of refund events

Revision ID: 20260720_0023
Revises: 20260720_0022
Create Date: 2026-07-20 20:45:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260720_0023"
down_revision = "20260720_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "douyin_refund_event",
        sa.Column(
            "successful_observed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE douyin_refund_event SET successful_observed_at = "
            "coalesce(gmt_create, gmt_modified, occurred_at) "
            "WHERE refund_status = 2 AND successful_observed_at IS NULL"
        )
    )
    op.create_index(
        "ix_douyin_refund_event_successful_observed_at",
        "douyin_refund_event",
        ["successful_observed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_douyin_refund_event_successful_observed_at",
        table_name="douyin_refund_event",
    )
    with op.batch_alter_table("douyin_refund_event") as batch_op:
        batch_op.drop_column("successful_observed_at")
