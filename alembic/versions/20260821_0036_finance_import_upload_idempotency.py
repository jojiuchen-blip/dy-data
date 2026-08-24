"""make finance import uploads idempotent

Revision ID: 20260821_0036
Revises: 20260821_0035
Create Date: 2026-08-21 15:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260821_0036"
down_revision = "20260821_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Persist upload idempotency keys and canonical request hashes."""
    with op.batch_alter_table("finance_import_batch") as batch_op:
        batch_op.add_column(
            sa.Column("upload_idempotency_key_hash", sa.String(length=64))
        )
        batch_op.add_column(
            sa.Column("upload_request_payload_sha256", sa.String(length=64))
        )
        batch_op.create_unique_constraint(
            "uk_finance_import_batch_upload_idempotency",
            ["upload_idempotency_key_hash"],
        )


def downgrade() -> None:
    """Remove upload idempotency fields and their uniqueness constraint."""
    with op.batch_alter_table("finance_import_batch") as batch_op:
        batch_op.drop_constraint(
            "uk_finance_import_batch_upload_idempotency", type_="unique"
        )
        batch_op.drop_column("upload_request_payload_sha256")
        batch_op.drop_column("upload_idempotency_key_hash")
