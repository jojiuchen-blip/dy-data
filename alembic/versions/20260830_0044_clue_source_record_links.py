"""add source-record links and master lead state version fields

Revision ID: 20260830_0044
Revises: 20260824_0043
Create Date: 2026-08-30 23:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260830_0044"
down_revision = "20260824_0043"
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
    """Add state fields and preserve one traceable link for each known source row."""
    with op.batch_alter_table("clue_master_leads") as batch_op:
        batch_op.add_column(
            sa.Column("master_kind", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(
            sa.Column("order_status_observed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "is_complete_pool",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column("state_version", sa.Integer(), nullable=False, server_default="1")
        )

    op.execute(
        sa.text(
            """
            UPDATE clue_master_leads
            SET
                master_kind = CASE WHEN order_id IS NULL THEN 2 ELSE 1 END,
                is_complete_pool = CASE WHEN order_id IS NULL THEN false ELSE true END,
                order_status_observed_at = last_seen_at
            """
        )
    )

    op.create_table(
        "clue_source_record_links",
        _id_column(),
        sa.Column("source_system", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "source_table",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'raw_douyin_clues'"),
        ),
        sa.Column("source_record_key", sa.String(length=128), nullable=False),
        sa.Column("source_clue_id", sa.String(length=64), nullable=True),
        sa.Column("source_order_id", sa.String(length=64), nullable=True),
        sa.Column(
            "lead_key",
            sa.Text(),
            sa.ForeignKey("clue_master_leads.lead_key", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("order_id", sa.String(length=64), nullable=True),
        sa.Column("link_status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("link_method", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("link_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("source_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_run_id", sa.String(length=64), nullable=True),
        sa.Column("source_payload_hash", sa.String(length=64), nullable=True),
        sa.Column("conflict_reason", sa.String(length=255), nullable=True),
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
            "source_table",
            "source_record_key",
            name="uq_clue_source_record_links_source",
        ),
    )
    op.create_index(
        "ix_clue_source_record_links_lead_key",
        "clue_source_record_links",
        ["lead_key"],
    )
    op.create_index(
        "ix_clue_source_record_links_order_id",
        "clue_source_record_links",
        ["order_id"],
    )
    op.create_index(
        "ix_clue_source_record_links_status_updated_at",
        "clue_source_record_links",
        ["link_status", "updated_at"],
    )

    op.execute(
        sa.text(
            """
            INSERT INTO clue_source_record_links (
                source_system,
                source_table,
                source_record_key,
                source_clue_id,
                source_order_id,
                lead_key,
                order_id,
                link_status,
                link_method,
                link_version,
                linked_at,
                source_observed_at,
                created_at,
                updated_at
            )
            SELECT
                1,
                'raw_douyin_clues',
                source_clue_row_key,
                canonical_clue_id,
                order_id,
                lead_key,
                order_id,
                CASE WHEN order_id IS NULL THEN 2 ELSE 1 END,
                2,
                1,
                COALESCE(created_at, CURRENT_TIMESTAMP),
                last_seen_at,
                COALESCE(created_at, CURRENT_TIMESTAMP),
                COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)
            FROM clue_master_leads
            WHERE source_clue_row_key IS NOT NULL
              AND TRIM(source_clue_row_key) <> ''
            """
        )
    )


def downgrade() -> None:
    """Remove source links before dropping the lead state columns."""
    op.drop_table("clue_source_record_links")
    with op.batch_alter_table("clue_master_leads") as batch_op:
        batch_op.drop_column("state_version")
        batch_op.drop_column("is_complete_pool")
        batch_op.drop_column("order_status_observed_at")
        batch_op.drop_column("master_kind")
