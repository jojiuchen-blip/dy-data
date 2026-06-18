"""add account module

Revision ID: 20260618_0005
Revises: 20260617_0004
Create Date: 2026-06-18 00:05:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260618_0005"
down_revision = "20260617_0004"
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
    if not _has_table("users"):
        op.create_table(
            "users",
            sa.Column("user_id", sa.Text(), primary_key=True),
            sa.Column("username", sa.Text(), nullable=False),
            sa.Column("external_account_id", sa.Text()),
            sa.Column("display_name", sa.Text(), nullable=False),
            sa.Column("role", sa.String(32), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("is_initialized", sa.Boolean(), nullable=False),
            sa.Column("password_hash", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("username", name="uq_users_username"),
            sa.UniqueConstraint("external_account_id", name="uq_users_external_account_id"),
        )
    _create_index_if_missing("ix_users_username", "users", ["username"])
    _create_index_if_missing("ix_users_external_account_id", "users", ["external_account_id"])
    _create_index_if_missing("ix_users_role", "users", ["role"])
    _create_index_if_missing("ix_users_status", "users", ["status"])
    _create_index_if_missing("ix_users_is_initialized", "users", ["is_initialized"])

    if not _has_table("user_store_scopes"):
        op.create_table(
            "user_store_scopes",
            sa.Column(
                "user_id",
                sa.Text(),
                sa.ForeignKey("users.user_id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "store_id",
                sa.Text(),
                sa.ForeignKey("dim_stores.store_id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    _create_index_if_missing("ix_user_store_scopes_store_id", "user_store_scopes", ["store_id"])


def downgrade() -> None:
    if _has_table("user_store_scopes"):
        op.drop_table("user_store_scopes")
    if _has_table("users"):
        op.drop_table("users")
