"""freeze the first successful observation time of refund events

Revision ID: 20260720_0023
Revises: 20260720_0022
Create Date: 2026-07-20 20:45:00
"""

from __future__ import annotations

from alembic import context, op
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
    _create_successful_observed_at_index()


def downgrade() -> None:
    _drop_successful_observed_at_index()
    with op.batch_alter_table("douyin_refund_event") as batch_op:
        batch_op.drop_column("successful_observed_at")


def _create_successful_observed_at_index() -> None:
    if op.get_bind().dialect.name != "postgresql":
        op.create_index(
            "ix_douyin_refund_event_successful_observed_at",
            "douyin_refund_event",
            ["successful_observed_at"],
        )
        return
    with context.get_context().autocommit_block():
        op.execute("SET statement_timeout = '5min'")
        try:
            op.execute(
                "CREATE INDEX CONCURRENTLY "
                "ix_douyin_refund_event_successful_observed_at "
                "ON douyin_refund_event (successful_observed_at)"
            )
        finally:
            op.execute("RESET statement_timeout")


def _drop_successful_observed_at_index() -> None:
    if op.get_bind().dialect.name != "postgresql":
        op.drop_index(
            "ix_douyin_refund_event_successful_observed_at",
            table_name="douyin_refund_event",
        )
        return
    with context.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY "
            "ix_douyin_refund_event_successful_observed_at"
        )
