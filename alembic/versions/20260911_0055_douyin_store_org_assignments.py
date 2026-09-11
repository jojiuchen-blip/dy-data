"""create the current service-store organization mapping

Revision ID: 20260911_0055
Revises: 20260911_0054
Create Date: 2026-09-09 11:20:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260911_0055"
down_revision = "20260911_0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dim_store_org_assignments",
        sa.Column("service_store_code", sa.String(length=128), nullable=False),
        sa.Column("service_store_name", sa.Text(), nullable=True),
        sa.Column("service_center_name", sa.Text(), nullable=True),
        sa.Column("district_name", sa.Text(), nullable=True),
        sa.Column("area_name", sa.Text(), nullable=True),
        sa.Column("source_workbook", sa.Text(), nullable=True),
        sa.Column("source_row_number", sa.Integer(), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("service_store_code", name="pk_dim_store_org_assignments"),
    )
    op.create_index(
        "ix_dim_store_org_assignments_service_center_name",
        "dim_store_org_assignments",
        ["service_center_name"],
        unique=False,
    )
    op.create_index(
        "ix_dim_store_org_assignments_district_name",
        "dim_store_org_assignments",
        ["district_name"],
        unique=False,
    )
    op.create_index(
        "ix_dim_store_org_assignments_area_name",
        "dim_store_org_assignments",
        ["area_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_dim_store_org_assignments_area_name", table_name="dim_store_org_assignments")
    op.drop_index("ix_dim_store_org_assignments_district_name", table_name="dim_store_org_assignments")
    op.drop_index("ix_dim_store_org_assignments_service_center_name", table_name="dim_store_org_assignments")
    op.drop_table("dim_store_org_assignments")
