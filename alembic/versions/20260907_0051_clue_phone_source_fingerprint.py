"""track the source used for the cached clue phone

Revision ID: 20260907_0051
Revises: 20260903_0050
Create Date: 2026-09-07 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260907_0051"
down_revision = "20260903_0050"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return False
    return column_name in {
        column["name"] for column in inspector.get_columns(table_name)
    }


def upgrade() -> None:
    """Add a nullable fingerprint; existing cached phone values stay unverified."""

    if not _has_column("clue_center_orders", "phone_source_fingerprint"):
        op.add_column(
            "clue_center_orders",
            sa.Column("phone_source_fingerprint", sa.String(length=64), nullable=True),
        )


def downgrade() -> None:
    """Drop only the metadata column; cached phone values are retained by design."""

    if _has_column("clue_center_orders", "phone_source_fingerprint"):
        op.drop_column("clue_center_orders", "phone_source_fingerprint")
