"""add cached plain clue phone

Revision ID: 20260622_0006
Revises: 20260618_0005
Create Date: 2026-06-22 00:06:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260622_0006"
down_revision = "20260618_0005"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return column_name in {
        column["name"] for column in inspect(op.get_bind()).get_columns(table_name)
    }


def upgrade() -> None:
    if _has_table("clue_center_orders") and not _has_column(
        "clue_center_orders", "phone_plain"
    ):
        op.add_column("clue_center_orders", sa.Column("phone_plain", sa.Text()))


def downgrade() -> None:
    if _has_table("clue_center_orders") and _has_column(
        "clue_center_orders", "phone_plain"
    ):
        op.drop_column("clue_center_orders", "phone_plain")
