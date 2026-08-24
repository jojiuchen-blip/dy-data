"""add immutable settlement carryforward source and application facts

Revision ID: 20260821_0038
Revises: 20260821_0037
Create Date: 2026-08-21 16:40:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260821_0038"
down_revision = "20260821_0037"
branch_labels = None
depends_on = None


def _id_column() -> sa.Column:
    return sa.Column(
        "id",
        sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
        sa.Identity(),
        autoincrement=True,
        nullable=False,
    )


def upgrade() -> None:
    """Create immutable source facts and versioned application facts."""
    op.create_table(
        "settlement_carryforward_source",
        _id_column(),
        sa.Column("carryforward_source_id", sa.String(length=128), nullable=False),
        sa.Column("source_event_type", sa.Integer(), nullable=False),
        sa.Column("source_event_key", sa.String(length=255), nullable=False),
        sa.Column("original_fee_result_id", sa.String(length=128), nullable=False),
        sa.Column("refund_event_id", sa.String(length=128), nullable=True),
        sa.Column("verify_id", sa.String(length=128), nullable=True),
        sa.Column("coupon_id", sa.String(length=128), nullable=False),
        sa.Column("order_id", sa.String(length=128), nullable=False),
        sa.Column("store_id", sa.String(length=128), nullable=False),
        sa.Column("fee_direction", sa.Integer(), nullable=False),
        sa.Column("original_business_month", sa.String(length=7), nullable=False),
        sa.Column("event_month", sa.String(length=7), nullable=False),
        sa.Column("adjustment_type", sa.Integer(), nullable=False),
        sa.Column(
            "adjustment_base_cent",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "adjustment_fee_cent",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("rule_version", sa.String(length=64), nullable=False),
        sa.Column("carryforward_reason", sa.String(length=1000), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column(
            "gmt_create",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_settlement_carryforward_source"),
        sa.UniqueConstraint(
            "carryforward_source_id",
            name="uk_settlement_carryforward_source_id",
        ),
        sa.UniqueConstraint(
            "source_event_key",
            "original_fee_result_id",
            "fee_direction",
            name="uk_settlement_carryforward_source_business",
        ),
        sa.CheckConstraint(
            "source_event_type IN (1, 2)",
            name="ck_settlement_carryforward_source_event_type",
        ),
        sa.CheckConstraint(
            "fee_direction IN (1, 2)",
            name="ck_settlement_carryforward_source_direction",
        ),
        sa.CheckConstraint(
            "adjustment_type IN (1, 2, 3, 4)",
            name="ck_settlement_carryforward_source_adjustment_type",
        ),
        sa.CheckConstraint(
            "(source_event_type = 1 AND refund_event_id IS NOT NULL "
            "AND verify_id IS NULL) OR "
            "(source_event_type = 2 AND refund_event_id IS NULL "
            "AND verify_id IS NOT NULL)",
            name="ck_settlement_carryforward_source_event_reference",
        ),
    )
    op.create_index(
        "idx_settlement_carryforward_source_pending",
        "settlement_carryforward_source",
        ["store_id", "event_month", "occurred_at"],
    )
    op.create_index(
        "idx_settlement_carryforward_source_original",
        "settlement_carryforward_source",
        ["original_fee_result_id"],
    )
    op.create_index(
        "idx_settlement_carryforward_source_refund",
        "settlement_carryforward_source",
        ["refund_event_id"],
    )

    op.create_table(
        "settlement_carryforward_application",
        _id_column(),
        sa.Column(
            "carryforward_application_id", sa.String(length=128), nullable=False
        ),
        sa.Column("carryforward_source_id", sa.String(length=128), nullable=False),
        sa.Column("target_statement_id", sa.String(length=128), nullable=False),
        sa.Column("target_statement_version", sa.Integer(), nullable=False),
        sa.Column("target_adjustment_id", sa.String(length=128), nullable=False),
        sa.Column("target_posting_month", sa.String(length=7), nullable=False),
        sa.Column(
            "application_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "is_current", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("applied_by", sa.String(length=128), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "gmt_create",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint(
            "id", name="pk_settlement_carryforward_application"
        ),
        sa.UniqueConstraint(
            "carryforward_application_id",
            name="uk_settlement_carryforward_application_id",
        ),
        sa.UniqueConstraint(
            "carryforward_source_id",
            "application_version",
            name="uk_settlement_carryforward_application_version",
        ),
        sa.UniqueConstraint(
            "target_adjustment_id",
            name="uk_settlement_carryforward_application_adjustment",
        ),
        sa.CheckConstraint(
            "application_version > 0",
            name="ck_settlement_carryforward_application_version",
        ),
        sa.CheckConstraint(
            "target_statement_version > 0",
            name="ck_settlement_carryforward_application_statement_version",
        ),
    )
    op.create_index(
        "idx_settlement_carryforward_application_current",
        "settlement_carryforward_application",
        ["carryforward_source_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
        sqlite_where=sa.text("is_current"),
    )
    op.create_index(
        "idx_settlement_carryforward_application_statement",
        "settlement_carryforward_application",
        ["target_statement_id"],
    )
    op.create_index(
        "idx_settlement_carryforward_application_posting",
        "settlement_carryforward_application",
        ["target_posting_month"],
    )


def downgrade() -> None:
    """Drop carryforward application facts before their source facts."""
    op.drop_table("settlement_carryforward_application")
    op.drop_table("settlement_carryforward_source")
