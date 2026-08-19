"""add additive sparse settlement projection lineage and overlays

Revision ID: 20260806_0035
Revises: 20260806_0034
Create Date: 2026-08-07 08:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260806_0035"
down_revision = "20260806_0034"
branch_labels = None
depends_on = None


def json_type() -> sa.types.TypeEngine:
    """Use JSONB on PostgreSQL and portable JSON on SQLite."""

    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "settlement_projection_generation",
        sa.Column("generation_id", sa.Text(), primary_key=True),
        sa.Column("base_generation_id", sa.Text(), nullable=True),
        sa.Column("projection_name", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("lineage_depth", sa.Integer(), nullable=False),
        sa.Column("estimated_write_rows", sa.BigInteger(), nullable=False),
        sa.Column("estimated_write_bytes", sa.BigInteger(), nullable=False),
        sa.Column("estimated_wal_bytes", sa.BigInteger(), nullable=False),
        sa.Column("estimated_disk_headroom_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checkpoint_json", json_type(), nullable=False),
        sa.Column("last_key", sa.Text(), nullable=True),
        sa.Column("manifest_checksum", sa.String(length=64), nullable=True),
        sa.Column("source_job_id", sa.Text(), nullable=True),
        sa.Column("source_input_json", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["base_generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_projection_generation_base",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_job_id"],
            ["job_runs.job_id"],
            name="fk_settlement_projection_generation_source_job",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "input_fingerprint",
            name="uq_settlement_projection_generation_input_fingerprint",
        ),
        sa.CheckConstraint(
            "projection_name = 'settlement'",
            name="ck_settlement_projection_generation_projection_name",
        ),
        sa.CheckConstraint(
            "state IN ('staging', 'ready', 'published', 'failed', 'superseded')",
            name="ck_settlement_projection_generation_state",
        ),
        sa.CheckConstraint(
            "lineage_depth >= 0",
            name="ck_settlement_projection_generation_lineage_depth",
        ),
        sa.CheckConstraint(
            "estimated_write_rows >= 0 AND estimated_write_bytes >= 0 "
            "AND estimated_wal_bytes >= 0 AND estimated_disk_headroom_bytes >= 0",
            name="ck_settlement_projection_generation_resources",
        ),
        sa.CheckConstraint(
            "base_generation_id IS NULL OR base_generation_id <> generation_id",
            name="ck_settlement_projection_generation_self_reference",
        ),
    )
    op.create_index(
        "ix_settlement_projection_generation_state",
        "settlement_projection_generation",
        ["projection_name", "state", "created_at"],
    )
    op.create_index(
        "ix_settlement_projection_generation_input",
        "settlement_projection_generation",
        ["projection_name", "input_fingerprint"],
    )
    op.create_index(
        "ix_settlement_projection_generation_base",
        "settlement_projection_generation",
        ["base_generation_id"],
    )

    op.create_table(
        "settlement_projection_active",
        sa.Column("projection_name", sa.String(length=64), primary_key=True),
        sa.Column("generation_id", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_projection_active_generation",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "generation_id", name="uq_settlement_projection_active_generation"
        ),
        sa.CheckConstraint(
            "projection_name = 'settlement'",
            name="ck_settlement_projection_active_projection_name",
        ),
    )

    op.create_table(
        "settlement_projection_partition_manifest",
        sa.Column("generation_id", sa.Text(), nullable=False),
        sa.Column("artifact", sa.String(length=32), nullable=False),
        sa.Column("partition_key", sa.String(length=128), nullable=False),
        sa.Column("owner_state", sa.String(length=32), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("data_generation_id", sa.Text(), nullable=True),
        sa.Column("base_generation_id", sa.Text(), nullable=True),
        sa.Column("row_count", sa.BigInteger(), nullable=False),
        sa.Column("amount_total_cent", sa.BigInteger(), nullable=False),
        sa.Column("status_counts_json", json_type(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=True),
        sa.Column("last_key", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_projection_manifest_generation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["data_generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_projection_manifest_data_generation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_projection_manifest_base_generation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "generation_id", "artifact", "partition_key",
            name="pk_settlement_projection_partition_manifest",
        ),
        sa.CheckConstraint(
            "artifact IN ('monthly', 'ranking', 'score')",
            name="ck_settlement_projection_manifest_artifact",
        ),
        sa.CheckConstraint(
            "owner_state IN ('owned', 'tombstone')",
            name="ck_settlement_projection_manifest_owner_state",
        ),
        sa.CheckConstraint(
            "source_kind IN ('overlay', 'legacy_root', 'tombstone')",
            name="ck_settlement_projection_manifest_source_kind",
        ),
        sa.CheckConstraint(
            "row_count >= 0",
            name="ck_settlement_projection_manifest_non_negative_counts",
        ),
        sa.CheckConstraint(
            "(owner_state = 'owned' AND source_kind = 'overlay' "
            "AND data_generation_id IS NOT NULL) OR "
            "(owner_state = 'owned' AND source_kind = 'legacy_root' "
            "AND data_generation_id IS NULL) OR "
            "(owner_state = 'tombstone' AND source_kind = 'tombstone' "
            "AND data_generation_id IS NULL AND row_count = 0)",
            name="ck_settlement_projection_manifest_source_invariants",
        ),
    )
    op.create_index(
        "ix_settlement_projection_manifest_state",
        "settlement_projection_partition_manifest",
        ["artifact", "owner_state", "source_kind"],
    )
    op.create_index(
        "ix_settlement_projection_manifest_data_generation",
        "settlement_projection_partition_manifest",
        ["data_generation_id"],
    )
    op.create_index(
        "ix_settlement_projection_manifest_base_generation",
        "settlement_projection_partition_manifest",
        ["base_generation_id"],
    )

    op.create_table(
        "settlement_monthly_overlay",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("generation_id", sa.Text(), nullable=False),
        sa.Column("base_generation_id", sa.Text(), nullable=True),
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("store_id", sa.String(length=128), nullable=False),
        sa.Column("product_scope", sa.String(length=128), nullable=False),
        sa.Column("product_type", sa.String(length=128), nullable=False),
        sa.Column("partition_key", sa.String(length=7), nullable=False),
        sa.Column("sales_order_count", sa.Integer(), nullable=False),
        sa.Column("sales_amount_cent", sa.BigInteger(), nullable=False),
        sa.Column("verified_order_count", sa.Integer(), nullable=False),
        sa.Column("verified_amount_cent", sa.BigInteger(), nullable=False),
        sa.Column("promotion_base_cent", sa.BigInteger(), nullable=False),
        sa.Column("promotion_original_fee_cent", sa.BigInteger(), nullable=False),
        sa.Column("promotion_adjustment_fee_cent", sa.BigInteger(), nullable=False),
        sa.Column("promotion_net_fee_cent", sa.BigInteger(), nullable=False),
        sa.Column("management_base_cent", sa.BigInteger(), nullable=False),
        sa.Column("management_original_fee_cent", sa.BigInteger(), nullable=False),
        sa.Column("management_adjustment_fee_cent", sa.BigInteger(), nullable=False),
        sa.Column("management_net_fee_cent", sa.BigInteger(), nullable=False),
        sa.Column("statement_status", sa.Integer(), nullable=False),
        sa.Column("projection_run_id", sa.String(length=128), nullable=False),
        sa.Column("estimated_receivable_commission_cent", sa.BigInteger(), nullable=False),
        sa.Column("commissionable_total_cent", sa.BigInteger(), nullable=False),
        sa.Column("estimated_payable_commission_cent", sa.BigInteger(), nullable=False),
        sa.Column("tombstone", sa.Boolean(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_monthly_overlay_generation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_monthly_overlay_base_generation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "generation_id",
            "month",
            "store_id",
            "product_scope",
            "product_type",
            name="uq_settlement_monthly_overlay_natural_key",
        ),
        sa.CheckConstraint(
            "statement_status IN (1, 2, 3, 4)",
            name="ck_settlement_monthly_overlay_status",
        ),
        sa.CheckConstraint(
            "partition_key = month",
            name="ck_settlement_monthly_overlay_partition",
        ),
    )
    op.create_index(
        "ix_settlement_monthly_overlay_generation_partition",
        "settlement_monthly_overlay",
        ["generation_id", "partition_key"],
    )
    op.create_index(
        "ix_settlement_monthly_overlay_store_month",
        "settlement_monthly_overlay",
        ["store_id", "month"],
    )

    op.create_table(
        "settlement_ranking_overlay",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("generation_id", sa.Text(), nullable=False),
        sa.Column("base_generation_id", sa.Text(), nullable=True),
        sa.Column("period_type", sa.Integer(), nullable=False),
        sa.Column("period_key", sa.String(length=7), nullable=False),
        sa.Column("store_id", sa.String(length=128), nullable=False),
        sa.Column("store_name", sa.String(length=255), nullable=False),
        sa.Column("product_scope", sa.String(length=128), nullable=False),
        sa.Column("product_type", sa.String(length=128), nullable=False),
        sa.Column("partition_key", sa.String(length=32), nullable=False),
        sa.Column("sales_order_count", sa.Integer(), nullable=False),
        sa.Column("sales_amount_cent", sa.BigInteger(), nullable=False),
        sa.Column("verified_order_count", sa.Integer(), nullable=False),
        sa.Column("verified_amount_cent", sa.BigInteger(), nullable=False),
        sa.Column("promotion_net_fee_cent", sa.BigInteger(), nullable=False),
        sa.Column("management_net_fee_cent", sa.BigInteger(), nullable=False),
        sa.Column("net_settlement_reference_cent", sa.BigInteger(), nullable=False),
        sa.Column("projection_run_id", sa.String(length=128), nullable=False),
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("self_sold_self_verified_count", sa.Integer(), nullable=False),
        sa.Column("self_sold_other_verified_count", sa.Integer(), nullable=False),
        sa.Column("other_sold_self_verified_count", sa.Integer(), nullable=False),
        sa.Column("self_verify_income_cent", sa.BigInteger(), nullable=False),
        sa.Column("effective_commission_income_cent", sa.BigInteger(), nullable=False),
        sa.Column("tombstone", sa.Boolean(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_ranking_overlay_generation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_ranking_overlay_base_generation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "generation_id",
            "period_type",
            "period_key",
            "store_id",
            "product_scope",
            "product_type",
            name="uq_settlement_ranking_overlay_natural_key",
        ),
        sa.CheckConstraint(
            "period_type IN (1, 2)",
            name="ck_settlement_ranking_overlay_period_type",
        ),
        sa.CheckConstraint(
            "net_settlement_reference_cent = promotion_net_fee_cent - "
            "management_net_fee_cent",
            name="ck_settlement_ranking_overlay_net_reference",
        ),
        sa.CheckConstraint(
            "(period_type = 1 AND partition_key = 'monthly:' || period_key "
            "AND month = period_key) OR "
            "(period_type = 2 AND partition_key = 'cumulative:' || period_key "
            "AND month = period_key)",
            name="ck_settlement_ranking_overlay_partition",
        ),
    )
    op.create_index(
        "ix_settlement_ranking_overlay_generation_partition",
        "settlement_ranking_overlay",
        ["generation_id", "period_type", "period_key"],
    )
    op.create_index(
        "ix_settlement_ranking_overlay_store_period",
        "settlement_ranking_overlay",
        ["store_id", "period_key"],
    )

    op.create_table(
        "store_score_snapshot_generation",
        sa.Column("generation_id", sa.Text(), nullable=False),
        sa.Column("snapshot_run_id", sa.Text(), nullable=False),
        sa.Column("store_id", sa.Text(), nullable=False),
        sa.Column("rule_version_id", sa.Text(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("partition_key", sa.String(length=256), nullable=False),
        sa.Column("owner_state", sa.String(length=32), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_store_score_snapshot_generation_generation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rule_version_id"],
            ["clue_allocation_rule_versions.rule_version_id"],
            name="fk_store_score_snapshot_generation_rule_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_run_id", "store_id"],
            ["store_score_snapshots.snapshot_run_id", "store_score_snapshots.store_id"],
            name="fk_store_score_snapshot_generation_snapshot_store",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "generation_id", "snapshot_run_id", "store_id",
            name="pk_store_score_snapshot_generation",
        ),
        sa.UniqueConstraint(
            "generation_id",
            "snapshot_date",
            "rule_version_id",
            "store_id",
            name="uq_store_score_snapshot_generation_partition",
        ),
        sa.CheckConstraint(
            "owner_state = 'owned'",
            name="ck_store_score_snapshot_generation_owner_state",
        ),
    )
    op.create_index(
        "ix_store_score_snapshot_generation_partition",
        "store_score_snapshot_generation",
        ["snapshot_date", "rule_version_id", "store_id"],
    )
    op.create_index(
        "ix_store_score_snapshot_generation_generation",
        "store_score_snapshot_generation",
        ["generation_id"],
    )


def downgrade() -> None:
    for index_name, table_name in (
        ("ix_store_score_snapshot_generation_generation", "store_score_snapshot_generation"),
        ("ix_store_score_snapshot_generation_partition", "store_score_snapshot_generation"),
        ("ix_settlement_ranking_overlay_store_period", "settlement_ranking_overlay"),
        ("ix_settlement_ranking_overlay_generation_partition", "settlement_ranking_overlay"),
        ("ix_settlement_monthly_overlay_store_month", "settlement_monthly_overlay"),
        ("ix_settlement_monthly_overlay_generation_partition", "settlement_monthly_overlay"),
        ("ix_settlement_projection_manifest_base_generation", "settlement_projection_partition_manifest"),
        ("ix_settlement_projection_manifest_data_generation", "settlement_projection_partition_manifest"),
        ("ix_settlement_projection_manifest_state", "settlement_projection_partition_manifest"),
        ("ix_settlement_projection_generation_base", "settlement_projection_generation"),
        ("ix_settlement_projection_generation_input", "settlement_projection_generation"),
        ("ix_settlement_projection_generation_state", "settlement_projection_generation"),
    ):
        op.drop_index(index_name, table_name=table_name)

    op.drop_table("store_score_snapshot_generation")
    op.drop_table("settlement_ranking_overlay")
    op.drop_table("settlement_monthly_overlay")
    op.drop_table("settlement_projection_partition_manifest")
    op.drop_table("settlement_projection_active")
    op.drop_table("settlement_projection_generation")
