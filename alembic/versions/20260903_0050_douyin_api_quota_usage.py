"""create the durable Douyin API daily quota ledger

Revision ID: 20260903_0050
Revises: 20260901_0049
Create Date: 2026-09-03 10:50:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260903_0050"
down_revision = "20260901_0049"
branch_labels = None
depends_on = None


def _id_column() -> sa.Column:
    return sa.Column(
        "id",
        sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
        sa.Identity(),
        nullable=False,
        primary_key=True,
        autoincrement=True,
    )


def upgrade() -> None:
    """Create one request counter per application endpoint and Shanghai day."""
    op.create_table(
        "douyin_api_quota_usage",
        _id_column(),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("app_id", sa.String(length=128), nullable=False),
        sa.Column("account_id", sa.String(length=128), nullable=False),
        sa.Column("endpoint_key", sa.String(length=128), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column(
            "request_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("effective_limit", sa.Integer(), nullable=False),
        sa.Column(
            "reset_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "environment",
            "app_id",
            "account_id",
            "endpoint_key",
            "business_date",
            name="uq_douyin_api_quota_usage_identity",
        ),
        sa.CheckConstraint(
            "request_count >= 0",
            name="ck_douyin_api_quota_usage_request_count",
        ),
        sa.CheckConstraint(
            "effective_limit > 0",
            name="ck_douyin_api_quota_usage_effective_limit",
        ),
    )
    op.create_index(
        "ix_douyin_api_quota_usage_reset_at",
        "douyin_api_quota_usage",
        ["reset_at"],
    )


def downgrade() -> None:
    """Refuse to discard reservations during a downgrade."""
    bind = op.get_bind()
    has_rows = bind.execute(
        sa.text("SELECT 1 FROM douyin_api_quota_usage LIMIT 1")
    ).first()
    if has_rows is not None:
        raise RuntimeError(
            "cannot downgrade 20260903_0050: Douyin API quota usage rows exist"
        )
    op.drop_index(
        "ix_douyin_api_quota_usage_reset_at",
        table_name="douyin_api_quota_usage",
    )
    op.drop_table("douyin_api_quota_usage")
