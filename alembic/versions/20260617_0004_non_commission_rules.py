"""add non commission owner account rules

Revision ID: 20260617_0004
Revises: 20260616_0003
Create Date: 2026-06-17 00:04:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260617_0004"
down_revision = "20260616_0003"
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


def upgrade() -> None:
    if not _has_table("dim_non_commission_owner_accounts"):
        op.create_table(
            "dim_non_commission_owner_accounts",
            sa.Column("normalized_owner_account_name", sa.Text(), primary_key=True),
            sa.Column("owner_account_name", sa.Text(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("updated_by", sa.Text()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    _create_index_if_missing(
        "ix_dim_non_commission_owner_accounts_owner_account_name",
        "dim_non_commission_owner_accounts",
        ["owner_account_name"],
    )
    _create_index_if_missing(
        "ix_dim_non_commission_owner_accounts_is_active",
        "dim_non_commission_owner_accounts",
        ["is_active"],
    )


def downgrade() -> None:
    if _has_table("dim_non_commission_owner_accounts"):
        op.drop_table("dim_non_commission_owner_accounts")
