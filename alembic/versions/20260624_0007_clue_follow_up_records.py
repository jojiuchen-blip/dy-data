"""add clue follow up records

Revision ID: 20260624_0007
Revises: 20260622_0006
Create Date: 2026-06-24 00:07:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260624_0007"
down_revision = "20260622_0006"
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
    if not _has_table("clue_follow_up_records"):
        op.create_table(
            "clue_follow_up_records",
            sa.Column("follow_up_record_id", sa.Text(), primary_key=True),
            sa.Column("order_id", sa.Text(), nullable=False),
            sa.Column("assignment_round_id", sa.Text(), nullable=False),
            sa.Column("round_no", sa.Integer(), nullable=False),
            sa.Column("assigned_store_id", sa.Text()),
            sa.Column("follow_result", sa.String(32), nullable=False),
            sa.Column("note", sa.Text()),
            sa.Column("operator_user_id", sa.Text()),
            sa.Column("operator_username", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    for index_name, columns in {
        "ix_clue_follow_up_records_order_id": ["order_id"],
        "ix_clue_follow_up_records_assignment_round_id": ["assignment_round_id"],
        "ix_clue_follow_up_records_assigned_store_id": ["assigned_store_id"],
        "ix_clue_follow_up_records_created_at": ["created_at"],
    }.items():
        _create_index_if_missing(index_name, "clue_follow_up_records", columns)


def downgrade() -> None:
    if _has_table("clue_follow_up_records"):
        op.drop_table("clue_follow_up_records")
