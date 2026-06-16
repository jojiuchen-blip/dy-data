"""add clue center mvp

Revision ID: 20260616_0003
Revises: 20260616_0002
Create Date: 2026-06-16 00:03:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260616_0003"
down_revision = "20260616_0002"
branch_labels = None
depends_on = None


def json_type() -> sa.types.TypeEngine:
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


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
    if not _has_table("raw_douyin_clues"):
        op.create_table(
            "raw_douyin_clues",
            sa.Column("clue_row_key", sa.Text(), primary_key=True),
            sa.Column("clue_id", sa.Text()),
            sa.Column("source_window_start", sa.DateTime(timezone=True)),
            sa.Column("source_window_end", sa.DateTime(timezone=True)),
            sa.Column("fetched_at", sa.DateTime(timezone=True)),
            sa.Column("create_time_detail", sa.DateTime(timezone=True)),
            sa.Column("modify_time", sa.DateTime(timezone=True)),
            sa.Column("name", sa.Text()),
            sa.Column("telephone", sa.Text()),
            sa.Column("enc_telephone", sa.Text()),
            sa.Column("product_id", sa.Text()),
            sa.Column("product_name", sa.Text()),
            sa.Column("order_id", sa.Text()),
            sa.Column("order_status", sa.Text()),
            sa.Column("follow_life_account_id", sa.Text()),
            sa.Column("follow_life_account_name", sa.Text()),
            sa.Column("auto_city_name", sa.Text()),
            sa.Column("auto_province_name", sa.Text()),
            sa.Column("author_nickname", sa.Text()),
            sa.Column("raw_payload", json_type(), nullable=False),
            sa.Column("source_file", sa.Text()),
            sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    _create_index_if_missing("ix_raw_douyin_clues_clue_id", "raw_douyin_clues", ["clue_id"])
    _create_index_if_missing(
        "ix_raw_douyin_clues_source_window_start", "raw_douyin_clues", ["source_window_start"]
    )
    _create_index_if_missing(
        "ix_raw_douyin_clues_create_time_detail", "raw_douyin_clues", ["create_time_detail"]
    )
    _create_index_if_missing("ix_raw_douyin_clues_product_id", "raw_douyin_clues", ["product_id"])
    _create_index_if_missing("ix_raw_douyin_clues_order_id", "raw_douyin_clues", ["order_id"])
    _create_index_if_missing("ix_raw_douyin_clues_order_status", "raw_douyin_clues", ["order_status"])
    _create_index_if_missing(
        "ix_raw_douyin_clues_follow_life_account_id", "raw_douyin_clues", ["follow_life_account_id"]
    )
    _create_index_if_missing("ix_raw_douyin_clues_auto_city_name", "raw_douyin_clues", ["auto_city_name"])

    if not _has_table("clue_center_orders"):
        op.create_table(
            "clue_center_orders",
            sa.Column("order_id", sa.Text(), primary_key=True),
            sa.Column("source_clue_ids", json_type(), nullable=False),
            sa.Column("source_clue_count", sa.Integer(), nullable=False),
            sa.Column("canonical_clue_id", sa.Text()),
            sa.Column("lead_status", sa.String(32), nullable=False),
            sa.Column("current_assignment_round_id", sa.Text()),
            sa.Column("current_round_no", sa.Integer(), nullable=False),
            sa.Column("current_round_status", sa.String(32), nullable=False),
            sa.Column("assigned_at", sa.DateTime(timezone=True)),
            sa.Column("assigned_at_source", sa.Text(), nullable=False),
            sa.Column("assigned_store_id", sa.Text()),
            sa.Column("assigned_store_name", sa.Text()),
            sa.Column("assigned_city", sa.Text()),
            sa.Column("assigned_province", sa.Text()),
            sa.Column("phone_masked", sa.Text()),
            sa.Column("phone_source", sa.Text()),
            sa.Column("product_id", sa.Text()),
            sa.Column("product_name", sa.Text()),
            sa.Column("product_type", sa.Text()),
            sa.Column("author_nickname", sa.Text()),
            sa.Column("follow_result", sa.String(32), nullable=False),
            sa.Column("is_followed", sa.Boolean(), nullable=False),
            sa.Column("is_follow_success", sa.Boolean(), nullable=False),
            sa.Column("verified_store_id", sa.Text()),
            sa.Column("verified_store_name", sa.Text()),
            sa.Column("verified_at", sa.DateTime(timezone=True)),
            sa.Column("is_self_store_verified", sa.Boolean(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True)),
            sa.Column("reassign_reason", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    for index_name, columns in {
        "ix_clue_center_orders_canonical_clue_id": ["canonical_clue_id"],
        "ix_clue_center_orders_current_assignment_round_id": ["current_assignment_round_id"],
        "ix_clue_center_orders_assigned_at": ["assigned_at"],
        "ix_clue_center_orders_assigned_store_id": ["assigned_store_id"],
        "ix_clue_center_orders_assigned_city": ["assigned_city"],
        "ix_clue_center_orders_product_id": ["product_id"],
        "ix_clue_center_orders_product_type": ["product_type"],
        "ix_clue_center_orders_follow_result": ["follow_result"],
        "ix_clue_center_orders_verified_store_id": ["verified_store_id"],
        "ix_clue_center_orders_verified_at": ["verified_at"],
        "ix_clue_center_orders_is_self_store_verified": ["is_self_store_verified"],
        "ix_clue_center_orders_expires_at": ["expires_at"],
        "ix_clue_center_orders_lead_status": ["lead_status"],
        "ix_clue_center_orders_current_round_status": ["current_round_status"],
    }.items():
        _create_index_if_missing(index_name, "clue_center_orders", columns)

    if not _has_table("clue_assignment_rounds"):
        op.create_table(
            "clue_assignment_rounds",
            sa.Column("assignment_round_id", sa.Text(), primary_key=True),
            sa.Column("order_id", sa.Text(), nullable=False),
            sa.Column("round_no", sa.Integer(), nullable=False),
            sa.Column("assigned_at", sa.DateTime(timezone=True)),
            sa.Column("assigned_at_source", sa.Text(), nullable=False),
            sa.Column("assigned_store_id", sa.Text()),
            sa.Column("assigned_store_name", sa.Text()),
            sa.Column("followed_at", sa.DateTime(timezone=True)),
            sa.Column("follow_result", sa.String(32), nullable=False),
            sa.Column("is_followed", sa.Boolean(), nullable=False),
            sa.Column("is_follow_success", sa.Boolean(), nullable=False),
            sa.Column("round_status", sa.String(32), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True)),
            sa.Column("reassign_reason", sa.Text()),
            sa.Column("reassigned_at", sa.DateTime(timezone=True)),
            sa.Column("verified_store_id", sa.Text()),
            sa.Column("verified_store_name", sa.Text()),
            sa.Column("verified_at", sa.DateTime(timezone=True)),
            sa.Column("is_self_store_verified", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("order_id", "round_no", name="uq_clue_assignment_rounds_order_round"),
        )
    for index_name, columns in {
        "ix_clue_assignment_rounds_order_id": ["order_id"],
        "ix_clue_assignment_rounds_assigned_at": ["assigned_at"],
        "ix_clue_assignment_rounds_assigned_store_id": ["assigned_store_id"],
        "ix_clue_assignment_rounds_follow_result": ["follow_result"],
        "ix_clue_assignment_rounds_round_status": ["round_status"],
        "ix_clue_assignment_rounds_expires_at": ["expires_at"],
        "ix_clue_assignment_rounds_verified_store_id": ["verified_store_id"],
        "ix_clue_assignment_rounds_verified_at": ["verified_at"],
        "ix_clue_assignment_rounds_is_self_store_verified": ["is_self_store_verified"],
    }.items():
        _create_index_if_missing(index_name, "clue_assignment_rounds", columns)

    if not _has_table("clue_reassign_rule_settings"):
        op.create_table(
            "clue_reassign_rule_settings",
            sa.Column("setting_key", sa.Text(), primary_key=True),
            sa.Column("reassign_sla_hours", sa.Integer()),
            sa.Column("updated_by", sa.Text()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    if _has_table("clue_reassign_rule_settings"):
        op.drop_table("clue_reassign_rule_settings")
    if _has_table("clue_assignment_rounds"):
        op.drop_table("clue_assignment_rounds")
    if _has_table("clue_center_orders"):
        op.drop_table("clue_center_orders")
    # Do not drop raw_douyin_clues on downgrade; it may contain manually uploaded
    # local export data that predates this migration.
