"""add clue follow-up state machine timing and reversal audit fields

Revision ID: 20260712_0015
Revises: 20260712_0014
Create Date: 2026-07-13 10:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260712_0015"
down_revision = "20260712_0014"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    return {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    round_columns = _columns("clue_assignment_rounds")
    with op.batch_alter_table("clue_assignment_rounds") as batch_op:
        if "first_sla_expires_at" not in round_columns:
            batch_op.add_column(sa.Column("first_sla_expires_at", sa.DateTime(timezone=True)))
        if "protection_started_at" not in round_columns:
            batch_op.add_column(sa.Column("protection_started_at", sa.DateTime(timezone=True)))
        if "protection_expires_at" not in round_columns:
            batch_op.add_column(sa.Column("protection_expires_at", sa.DateTime(timezone=True)))
        if "auto_expiry_enabled" not in round_columns:
            batch_op.add_column(sa.Column("auto_expiry_enabled", sa.Boolean()))
        if "first_follow_up_sla_hours" not in round_columns:
            batch_op.add_column(sa.Column("first_follow_up_sla_hours", sa.Integer()))
        if "protection_days" not in round_columns:
            batch_op.add_column(sa.Column("protection_days", sa.Integer()))
    for index_name, column_name in (
        ("ix_clue_assignment_rounds_first_sla_expires_at", "first_sla_expires_at"),
        ("ix_clue_assignment_rounds_protection_started_at", "protection_started_at"),
        ("ix_clue_assignment_rounds_protection_expires_at", "protection_expires_at"),
    ):
        if index_name not in _indexes("clue_assignment_rounds"):
            op.create_index(index_name, "clue_assignment_rounds", [column_name])

    record_columns = _columns("clue_follow_up_records")
    with op.batch_alter_table("clue_follow_up_records") as batch_op:
        if "deleted_at" not in record_columns:
            batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True)))
        if "deleted_by_user_id" not in record_columns:
            batch_op.add_column(sa.Column("deleted_by_user_id", sa.Text()))
        if "deleted_by_username" not in record_columns:
            batch_op.add_column(sa.Column("deleted_by_username", sa.Text()))
        if "deletion_reason" not in record_columns:
            batch_op.add_column(sa.Column("deletion_reason", sa.Text()))
    if "ix_clue_follow_up_records_deleted_at" not in _indexes("clue_follow_up_records"):
        op.create_index("ix_clue_follow_up_records_deleted_at", "clue_follow_up_records", ["deleted_at"])


def downgrade() -> None:
    if "ix_clue_follow_up_records_deleted_at" in _indexes("clue_follow_up_records"):
        op.drop_index("ix_clue_follow_up_records_deleted_at", table_name="clue_follow_up_records")
    record_columns = _columns("clue_follow_up_records")
    with op.batch_alter_table("clue_follow_up_records", recreate="always") as batch_op:
        for column_name in ("deletion_reason", "deleted_by_username", "deleted_by_user_id", "deleted_at"):
            if column_name in record_columns:
                batch_op.drop_column(column_name)

    for index_name in (
        "ix_clue_assignment_rounds_first_sla_expires_at",
        "ix_clue_assignment_rounds_protection_started_at",
        "ix_clue_assignment_rounds_protection_expires_at",
    ):
        if index_name in _indexes("clue_assignment_rounds"):
            op.drop_index(index_name, table_name="clue_assignment_rounds")
    round_columns = _columns("clue_assignment_rounds")
    with op.batch_alter_table("clue_assignment_rounds", recreate="always") as batch_op:
        for column_name in (
            "protection_days",
            "first_follow_up_sla_hours",
            "auto_expiry_enabled",
            "protection_expires_at",
            "protection_started_at",
            "first_sla_expires_at",
        ):
            if column_name in round_columns:
                batch_op.drop_column(column_name)
