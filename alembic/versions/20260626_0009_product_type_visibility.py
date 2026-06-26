"""add product type visibility settings

Revision ID: 20260626_0009
Revises: 20260624_0008
Create Date: 2026-06-26 18:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260626_0009"
down_revision = "20260624_0008"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _index_names(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if index_name not in _index_names(table_name):
        op.create_index(index_name, table_name, columns)


def json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    if not _has_table("product_type_visibility_settings"):
        op.create_table(
            "product_type_visibility_settings",
            sa.Column("setting_key", sa.Text(), primary_key=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("visible_product_types", json_type(), nullable=False),
            sa.Column("updated_by", sa.Text()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    _create_index_if_missing(
        "ix_product_type_visibility_settings_enabled",
        "product_type_visibility_settings",
        ["enabled"],
    )


def downgrade() -> None:
    if _has_table("product_type_visibility_settings"):
        op.drop_table("product_type_visibility_settings")
