"""add default product type visibility setting

Revision ID: 20260626_0010
Revises: 20260626_0009
Create Date: 2026-06-26 20:20:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260626_0010"
down_revision = "20260626_0009"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _column_names(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    if (
        _has_table("product_type_visibility_settings")
        and "default_product_type" not in _column_names("product_type_visibility_settings")
    ):
        op.add_column(
            "product_type_visibility_settings",
            sa.Column(
                "default_product_type",
                sa.Text(),
                nullable=False,
                server_default="all",
            ),
        )


def downgrade() -> None:
    if (
        _has_table("product_type_visibility_settings")
        and "default_product_type" in _column_names("product_type_visibility_settings")
    ):
        op.drop_column("product_type_visibility_settings", "default_product_type")
