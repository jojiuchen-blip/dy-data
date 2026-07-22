"""add isolated MCP OAuth authorization and token storage

Revision ID: 20260722_0021
Revises: 20260722_0020
Create Date: 2026-07-22 10:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260722_0021"
down_revision = "20260722_0020"
branch_labels = None
depends_on = None


def _indexes(
    table_name: str,
    definitions: tuple[tuple[str, list[str], bool], ...],
) -> None:
    for index_name, columns, unique in definitions:
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    op.create_table(
        "mcp_oauth_clients",
        sa.Column("client_id", sa.Text(), primary_key=True),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes(
        "mcp_oauth_clients",
        (("ix_mcp_oauth_clients_environment", ["environment"], False),),
    )

    op.create_table(
        "mcp_authorization_requests",
        sa.Column("authorization_request_id", sa.Text(), primary_key=True),
        sa.Column("request_token_hash", sa.Text(), nullable=False),
        sa.Column(
            "client_id",
            sa.Text(),
            sa.ForeignKey("mcp_oauth_clients.client_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("redirect_uri_provided_explicitly", sa.Boolean(), nullable=False),
        sa.Column("state", sa.Text()),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("code_challenge", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("code_hash", sa.Text()),
        sa.Column("subject", sa.Text()),
        sa.Column(
            "user_id",
            sa.Text(),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
        ),
        sa.Column("username", sa.Text()),
        sa.Column("auth_type", sa.String(length=32)),
        sa.Column("authorization_fingerprint", sa.Text()),
        sa.Column("issued_auth_generation", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
    )
    _indexes(
        "mcp_authorization_requests",
        (
            ("ix_mcp_authorization_requests_request_token_hash", ["request_token_hash"], True),
            ("ix_mcp_authorization_requests_client_id", ["client_id"], False),
            ("ix_mcp_authorization_requests_environment", ["environment"], False),
            ("ix_mcp_authorization_requests_status", ["status"], False),
            ("ix_mcp_authorization_requests_code_hash", ["code_hash"], True),
            ("ix_mcp_authorization_requests_user_id", ["user_id"], False),
            ("ix_mcp_authorization_requests_expires_at", ["expires_at"], False),
        ),
    )

    op.create_table(
        "mcp_access_tokens",
        sa.Column("access_token_id", sa.Text(), primary_key=True),
        sa.Column("family_id", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column(
            "client_id",
            sa.Text(),
            sa.ForeignKey("mcp_oauth_clients.client_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column(
            "user_id",
            sa.Text(),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
        ),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("auth_type", sa.String(length=32), nullable=False),
        sa.Column("authorization_fingerprint", sa.Text(), nullable=False),
        sa.Column("issued_auth_generation", sa.Integer()),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    _indexes(
        "mcp_access_tokens",
        (
            ("ix_mcp_access_tokens_family_id", ["family_id"], False),
            ("ix_mcp_access_tokens_token_hash", ["token_hash"], True),
            ("ix_mcp_access_tokens_client_id", ["client_id"], False),
            ("ix_mcp_access_tokens_environment", ["environment"], False),
            ("ix_mcp_access_tokens_subject", ["subject"], False),
            ("ix_mcp_access_tokens_user_id", ["user_id"], False),
            ("ix_mcp_access_tokens_expires_at", ["expires_at"], False),
            ("ix_mcp_access_tokens_revoked_at", ["revoked_at"], False),
        ),
    )

    op.create_table(
        "mcp_refresh_tokens",
        sa.Column("refresh_token_id", sa.Text(), primary_key=True),
        sa.Column("family_id", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column(
            "client_id",
            sa.Text(),
            sa.ForeignKey("mcp_oauth_clients.client_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column(
            "user_id",
            sa.Text(),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
        ),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("auth_type", sa.String(length=32), nullable=False),
        sa.Column("authorization_fingerprint", sa.Text(), nullable=False),
        sa.Column("issued_auth_generation", sa.Integer()),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("replaced_by_token_id", sa.Text()),
    )
    _indexes(
        "mcp_refresh_tokens",
        (
            ("ix_mcp_refresh_tokens_family_id", ["family_id"], False),
            ("ix_mcp_refresh_tokens_token_hash", ["token_hash"], True),
            ("ix_mcp_refresh_tokens_client_id", ["client_id"], False),
            ("ix_mcp_refresh_tokens_environment", ["environment"], False),
            ("ix_mcp_refresh_tokens_subject", ["subject"], False),
            ("ix_mcp_refresh_tokens_user_id", ["user_id"], False),
            ("ix_mcp_refresh_tokens_expires_at", ["expires_at"], False),
            ("ix_mcp_refresh_tokens_revoked_at", ["revoked_at"], False),
        ),
    )


def downgrade() -> None:
    op.drop_table("mcp_refresh_tokens")
    op.drop_table("mcp_access_tokens")
    op.drop_table("mcp_authorization_requests")
    op.drop_table("mcp_oauth_clients")
