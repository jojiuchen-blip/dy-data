"""add idempotency replay fields for dispute operations

Revision ID: 20260821_0032
Revises: 20260821_0031
Create Date: 2026-08-21 12:05:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260821_0032"
down_revision = "20260821_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("settlement_dispute") as batch_op:
        batch_op.add_column(
            sa.Column("idempotency_key_hash", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("request_payload_sha256", sa.String(length=64), nullable=True)
        )
        batch_op.create_unique_constraint(
            "uk_settlement_dispute_idempotency_key", ["idempotency_key_hash"]
        )
    with op.batch_alter_table("finance_operation_audit") as batch_op:
        batch_op.add_column(
            sa.Column("idempotency_key_hash", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("request_payload_sha256", sa.String(length=64), nullable=True)
        )
        batch_op.create_unique_constraint(
            "uk_finance_operation_audit_idempotency_key", ["idempotency_key_hash"]
        )


def downgrade() -> None:
    with op.batch_alter_table("finance_operation_audit") as batch_op:
        batch_op.drop_constraint(
            "uk_finance_operation_audit_idempotency_key", type_="unique"
        )
        batch_op.drop_column("request_payload_sha256")
        batch_op.drop_column("idempotency_key_hash")
    with op.batch_alter_table("settlement_dispute") as batch_op:
        batch_op.drop_constraint(
            "uk_settlement_dispute_idempotency_key", type_="unique"
        )
        batch_op.drop_column("request_payload_sha256")
        batch_op.drop_column("idempotency_key_hash")
