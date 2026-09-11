"""track active rows in the current store organization mapping

Revision ID: 20260911_0056
Revises: 20260911_0055
Create Date: 2026-09-09 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260911_0056"
down_revision = "20260911_0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("dim_store_org_assignments") as batch_op:
        batch_op.add_column(
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
        )


def downgrade() -> None:
    with op.batch_alter_table("dim_store_org_assignments") as batch_op:
        batch_op.drop_column("is_active")
