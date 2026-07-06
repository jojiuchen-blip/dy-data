"""add product scope visibility setting

Revision ID: 20260706_0011
Revises: 20260626_0010
Create Date: 2026-07-06 18:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260706_0011"
down_revision = "20260626_0010"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _column_names(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    if (
        _has_table("product_type_visibility_settings")
        and "visible_product_scopes" not in _column_names("product_type_visibility_settings")
    ):
        default = (
            sa.text("'[]'::jsonb")
            if op.get_bind().dialect.name == "postgresql"
            else sa.text("'[]'")
        )
        op.add_column(
            "product_type_visibility_settings",
            sa.Column(
                "visible_product_scopes",
                json_type(),
                nullable=False,
                server_default=default,
            ),
        )


def downgrade() -> None:
    if (
        _has_table("product_type_visibility_settings")
        and "visible_product_scopes" in _column_names("product_type_visibility_settings")
    ):
        op.drop_column("product_type_visibility_settings", "visible_product_scopes")
