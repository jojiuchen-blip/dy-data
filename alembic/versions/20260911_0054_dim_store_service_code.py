"""add the service-store code used by Douyin organization mappings

Revision ID: 20260911_0054
Revises: 20260910_0053
Create Date: 2026-09-09 11:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260911_0054"
down_revision = "20260910_0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("dim_stores") as batch_op:
        batch_op.add_column(sa.Column("service_store_code", sa.String(length=128), nullable=True))
        batch_op.create_index(
            "ix_dim_stores_service_store_code",
            ["service_store_code"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("dim_stores") as batch_op:
        batch_op.drop_index("ix_dim_stores_service_store_code")
        batch_op.drop_column("service_store_code")
