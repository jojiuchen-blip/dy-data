"""add environment, channel, and authorization scope to Agent audit events

Revision ID: 20260722_0022
Revises: 20260722_0021
Create Date: 2026-07-22 13:15:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260722_0022"
down_revision = "20260722_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cli_audit_events",
        sa.Column(
            "environment",
            sa.String(length=32),
            nullable=False,
            server_default="test",
        ),
    )
    op.add_column(
        "cli_audit_events",
        sa.Column(
            "channel",
            sa.String(length=16),
            nullable=False,
            server_default="cli",
        ),
    )
    op.add_column(
        "cli_audit_events",
        sa.Column(
            "authorization_scopes",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )
    op.create_index(
        "ix_cli_audit_events_channel",
        "cli_audit_events",
        ["channel"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_cli_audit_events_channel", table_name="cli_audit_events")
    op.drop_column("cli_audit_events", "authorization_scopes")
    op.drop_column("cli_audit_events", "channel")
    op.drop_column("cli_audit_events", "environment")
