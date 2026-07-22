"""add confirmed CLI audit storage and refresh token families

Revision ID: 20260722_0020
Revises: 20260722_0019
Create Date: 2026-07-22 00:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260722_0020"
down_revision = "20260722_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("cli_refresh_tokens") as batch_op:
        batch_op.add_column(sa.Column("family_id", sa.Text(), nullable=True))
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE cli_refresh_tokens "
            "SET family_id = refresh_token_id WHERE family_id IS NULL"
        )
    )
    with op.batch_alter_table("cli_refresh_tokens") as batch_op:
        batch_op.alter_column(
            "family_id", existing_type=sa.Text(), nullable=False
        )
        batch_op.create_index(
            "ix_cli_refresh_tokens_family_id", ["family_id"], unique=False
        )

    op.create_table(
        "cli_audit_events",
        sa.Column("audit_event_id", sa.Text(), primary_key=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text()),
        sa.Column("auth_type", sa.String(length=32)),
        sa.Column("cli_version", sa.String(length=64)),
        sa.Column("schema_version", sa.String(length=32)),
        sa.Column("date_range", sa.JSON()),
        sa.Column("requested_store_ids", sa.JSON(), nullable=False),
        sa.Column("effective_store_ids", sa.JSON(), nullable=False),
        sa.Column("returned_store_count", sa.Integer(), nullable=False),
        sa.Column("result_status", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=64)),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for index_name, columns in (
        ("ix_cli_audit_events_event_type", ["event_type"]),
        ("ix_cli_audit_events_operation", ["operation"]),
        ("ix_cli_audit_events_request_id", ["request_id"]),
        ("ix_cli_audit_events_command", ["command"]),
        ("ix_cli_audit_events_user_id", ["user_id"]),
        ("ix_cli_audit_events_created_at", ["created_at"]),
        ("ix_cli_audit_events_command_created", ["command", "created_at"]),
        ("ix_cli_audit_events_operation_created", ["operation", "created_at"]),
    ):
        op.create_index(index_name, "cli_audit_events", columns, unique=False)


def downgrade() -> None:
    op.drop_table("cli_audit_events")
    with op.batch_alter_table("cli_refresh_tokens") as batch_op:
        batch_op.drop_index("ix_cli_refresh_tokens_family_id")
        batch_op.drop_column("family_id")
