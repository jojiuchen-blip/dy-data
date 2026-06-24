"""add user feedback submissions

Revision ID: 20260624_0008
Revises: 20260624_0007
Create Date: 2026-06-24 16:08:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260624_0008"
down_revision = "20260624_0007"
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
    if not _has_table("user_feedback_submissions"):
        op.create_table(
            "user_feedback_submissions",
            sa.Column("feedback_id", sa.Text(), primary_key=True),
            sa.Column("category", sa.String(32), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("contact", sa.Text()),
            sa.Column("page_path", sa.Text()),
            sa.Column("user_id", sa.Text()),
            sa.Column("username", sa.Text()),
            sa.Column("user_role", sa.String(32)),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    for index_name, columns in {
        "ix_user_feedback_submissions_category": ["category"],
        "ix_user_feedback_submissions_created_at": ["created_at"],
        "ix_user_feedback_submissions_status": ["status"],
        "ix_user_feedback_submissions_user_id": ["user_id"],
    }.items():
        _create_index_if_missing(index_name, "user_feedback_submissions", columns)


def downgrade() -> None:
    if _has_table("user_feedback_submissions"):
        op.drop_table("user_feedback_submissions")
