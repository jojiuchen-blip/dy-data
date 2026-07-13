"""drop legacy clue reassign rule settings

Revision ID: 20260713_0017
Revises: 20260712_0016
Create Date: 2026-07-13 17:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260713_0017"
down_revision = "20260712_0016"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if _has_table("clue_reassign_rule_settings"):
        op.drop_table("clue_reassign_rule_settings")


def downgrade() -> None:
    if not _has_table("clue_reassign_rule_settings"):
        op.create_table(
            "clue_reassign_rule_settings",
            sa.Column("setting_key", sa.Text(), primary_key=True),
            sa.Column("reassign_sla_hours", sa.Integer()),
            sa.Column("updated_by", sa.Text()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
