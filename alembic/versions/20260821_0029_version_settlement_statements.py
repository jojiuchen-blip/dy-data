"""version immutable settlement statements

Revision ID: 20260821_0029
Revises: 20260821_0028
Create Date: 2026-08-21 09:45:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260821_0029"
down_revision = "20260821_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add immutable statement versions and version-scoped source snapshots."""
    with op.batch_alter_table("settlement_statement") as batch_op:
        batch_op.add_column(
            sa.Column(
                "version_no",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "is_current",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch_op.add_column(
            sa.Column("supersedes_statement_id", sa.String(length=128), nullable=True)
        )
        batch_op.drop_constraint(
            "uk_settlement_statement_store_month", type_="unique"
        )
        batch_op.create_unique_constraint(
            "uk_settlement_statement_store_month_version",
            ["store_id", "statement_month", "version_no"],
        )

    op.create_index(
        "idx_settlement_statement_current_slot",
        "settlement_statement",
        ["store_id", "statement_month"],
        unique=True,
        postgresql_where=sa.text("is_current"),
        sqlite_where=sa.text("is_current"),
    )
    op.create_index(
        "idx_settlement_statement_supersedes",
        "settlement_statement",
        ["supersedes_statement_id"],
    )

    with op.batch_alter_table("settlement_statement_entry") as batch_op:
        batch_op.drop_constraint(
            "uk_settlement_statement_entry_source", type_="unique"
        )
        batch_op.create_unique_constraint(
            "uk_settlement_statement_entry_source",
            ["statement_id", "source_type", "source_record_id"],
        )


def downgrade() -> None:
    """Restore legacy uniqueness only while no versioned history exists."""
    _require_legacy_downgrade_is_safe()

    with op.batch_alter_table("settlement_statement_entry") as batch_op:
        batch_op.drop_constraint(
            "uk_settlement_statement_entry_source", type_="unique"
        )
        batch_op.create_unique_constraint(
            "uk_settlement_statement_entry_source",
            ["source_type", "source_record_id"],
        )

    op.drop_index(
        "idx_settlement_statement_supersedes", table_name="settlement_statement"
    )
    op.drop_index(
        "idx_settlement_statement_current_slot", table_name="settlement_statement"
    )
    with op.batch_alter_table("settlement_statement") as batch_op:
        batch_op.drop_constraint(
            "uk_settlement_statement_store_month_version", type_="unique"
        )
        batch_op.create_unique_constraint(
            "uk_settlement_statement_store_month",
            ["store_id", "statement_month"],
        )
        batch_op.drop_column("supersedes_statement_id")
        batch_op.drop_column("is_current")
        batch_op.drop_column("version_no")


def _require_legacy_downgrade_is_safe() -> None:
    bind = op.get_bind()
    has_version_history = bind.scalar(
        sa.text(
            """
            SELECT COUNT(*)
            FROM settlement_statement
            WHERE version_no <> 1
               OR is_current = 0
               OR supersedes_statement_id IS NOT NULL
            """
        )
    )
    if has_version_history:
        raise RuntimeError(
            "cannot downgrade settlement statement versioning while version history exists"
        )

    duplicate_source_snapshots = bind.scalar(
        sa.text(
            """
            SELECT COUNT(*)
            FROM (
                SELECT source_type, source_record_id
                FROM settlement_statement_entry
                GROUP BY source_type, source_record_id
                HAVING COUNT(*) > 1
            ) AS duplicate_sources
            """
        )
    )
    if duplicate_source_snapshots:
        raise RuntimeError(
            "cannot downgrade settlement statement entries while versioned snapshots exist"
        )
