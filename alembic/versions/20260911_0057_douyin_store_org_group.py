"""add group fields to the current store organization mapping

Revision ID: 20260911_0057
Revises: 20260911_0056
Create Date: 2026-09-09 12:20:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260911_0057"
down_revision = "20260911_0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("dim_store_org_assignments") as batch_op:
        batch_op.add_column(sa.Column("group_code", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("group_name", sa.Text(), nullable=True))
        batch_op.create_index(
            "ix_dim_store_org_assignments_group_code", ["group_code"], unique=False
        )
        batch_op.create_index(
            "ix_dim_store_org_assignments_group_name", ["group_name"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("dim_store_org_assignments") as batch_op:
        batch_op.drop_index("ix_dim_store_org_assignments_group_name")
        batch_op.drop_index("ix_dim_store_org_assignments_group_code")
        batch_op.drop_column("group_name")
        batch_op.drop_column("group_code")
