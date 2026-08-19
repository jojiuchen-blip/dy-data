"""add bounded-closure indexes for incremental clue materialization

Revision ID: 20260806_0033
Revises: 20260806_0032
Create Date: 2026-08-06 20:10:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260806_0033"
down_revision = "20260806_0032"
branch_labels = None
depends_on = None


INDEXES = (
    ("raw_douyin_clues", "ix_raw_douyin_clues_order_row_key", ("order_id", "clue_row_key")),
    (
        "raw_douyin_clues",
        "ix_raw_douyin_clues_follow_poi_row_key",
        ("follow_poi_id", "clue_row_key"),
    ),
    (
        "raw_douyin_clues",
        "ix_raw_douyin_clues_intention_poi_row_key",
        ("intention_poi_id", "clue_row_key"),
    ),
    (
        "clue_master_leads",
        "ix_clue_master_leads_source_identity_order",
        ("source_identity_key", "order_id"),
    ),
    (
        "clue_source_identifier_history",
        "ix_clue_source_identifier_history_source_lead_type",
        ("source_clue_row_key", "lead_key", "identifier_type", "is_current"),
    ),
    (
        "clue_source_identifier_history",
        "ix_clue_source_identifier_history_type_value_lead",
        ("identifier_type", "identifier_value", "lead_key"),
    ),
    (
        "settlement_order_details",
        "ix_settlement_order_details_order_verified_time",
        ("order_id", "is_verified", "verify_time", "coupon_id"),
    ),
)


def upgrade() -> None:
    op.add_column(
        "clue_master_leads",
        sa.Column("last_observation_key", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "clue_materialization_work_items",
        sa.Column("raw_cursor", sa.Text(), nullable=True),
    )
    op.add_column(
        "clue_materialization_work_items",
        sa.Column("raw_page_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "clue_materialization_work_items",
        sa.Column("center_cursor", sa.Text(), nullable=True),
    )
    op.create_table(
        "clue_materialization_targets",
        sa.Column(
            "target_id",
            sa.BigInteger().with_variant(sa.Integer, "sqlite"),
            sa.Identity(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("scope", sa.String(length=128), nullable=False),
        sa.Column("cycle_id", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("target_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "target_type IN ('raw', 'center')",
            name="ck_clue_materialization_target_type",
        ),
        sa.UniqueConstraint(
            "scope",
            "cycle_id",
            "target_type",
            "target_key",
            name="uk_clue_materialization_target_cycle_key",
        ),
    )
    op.create_index(
        "ix_clue_materialization_target_cycle_type_key",
        "clue_materialization_targets",
        ["scope", "cycle_id", "target_type", "target_key"],
        unique=False,
    )
    for table_name, index_name, columns in INDEXES:
        op.create_index(index_name, table_name, list(columns), unique=False)


def downgrade() -> None:
    for table_name, index_name, _columns in reversed(INDEXES):
        op.drop_index(index_name, table_name=table_name)
    op.drop_index(
        "ix_clue_materialization_target_cycle_type_key",
        table_name="clue_materialization_targets",
    )
    op.drop_table("clue_materialization_targets")
    op.drop_column("clue_materialization_work_items", "raw_page_complete")
    op.drop_column("clue_materialization_work_items", "center_cursor")
    op.drop_column("clue_materialization_work_items", "raw_cursor")
    op.drop_column("clue_master_leads", "last_observation_key")
