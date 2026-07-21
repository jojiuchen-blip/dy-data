"""add CLI device authorizations and refresh tokens

Revision ID: 20260721_0018
Revises: 20260713_0017
Create Date: 2026-07-21 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260721_0018"
down_revision = "20260713_0017"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _index_names(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}


def _create_index_if_missing(
    index_name: str, table_name: str, columns: list[str], *, unique: bool = False
) -> None:
    if _has_table(table_name) and index_name not in _index_names(table_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    if not _has_table("cli_device_authorizations"):
        op.create_table(
            "cli_device_authorizations",
            sa.Column("device_authorization_id", sa.Text(), primary_key=True),
            sa.Column("device_code_hash", sa.Text(), nullable=False),
            sa.Column("user_code_hash", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("scope", sa.Text(), nullable=False, server_default="cli:read"),
            sa.Column(
                "user_id",
                sa.Text(),
                sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            ),
            sa.Column("username", sa.Text()),
            sa.Column("auth_type", sa.String(length=32)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("approved_at", sa.DateTime(timezone=True)),
            sa.Column("consumed_at", sa.DateTime(timezone=True)),
        )
    for index_name, columns, unique in (
        ("ix_cli_device_authorizations_device_code_hash", ["device_code_hash"], True),
        ("ix_cli_device_authorizations_user_code_hash", ["user_code_hash"], True),
        ("ix_cli_device_authorizations_status", ["status"], False),
        ("ix_cli_device_authorizations_user_id", ["user_id"], False),
        ("ix_cli_device_authorizations_expires_at", ["expires_at"], False),
    ):
        _create_index_if_missing(index_name, "cli_device_authorizations", columns, unique=unique)

    if not _has_table("cli_refresh_tokens"):
        op.create_table(
            "cli_refresh_tokens",
            sa.Column("refresh_token_id", sa.Text(), primary_key=True),
            sa.Column("token_hash", sa.Text(), nullable=False),
            sa.Column(
                "user_id",
                sa.Text(),
                sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            ),
            sa.Column("username", sa.Text(), nullable=False),
            sa.Column("auth_type", sa.String(length=32), nullable=False),
            sa.Column("scope", sa.Text(), nullable=False, server_default="cli:read"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True)),
            sa.Column("revoked_at", sa.DateTime(timezone=True)),
            sa.Column("replaced_by_token_id", sa.Text()),
        )
    for index_name, columns, unique in (
        ("ix_cli_refresh_tokens_token_hash", ["token_hash"], True),
        ("ix_cli_refresh_tokens_user_id", ["user_id"], False),
        ("ix_cli_refresh_tokens_expires_at", ["expires_at"], False),
        ("ix_cli_refresh_tokens_revoked_at", ["revoked_at"], False),
    ):
        _create_index_if_missing(index_name, "cli_refresh_tokens", columns, unique=unique)


def downgrade() -> None:
    if _has_table("cli_refresh_tokens"):
        op.drop_table("cli_refresh_tokens")
    if _has_table("cli_device_authorizations"):
        op.drop_table("cli_device_authorizations")
