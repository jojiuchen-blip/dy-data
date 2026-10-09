"""Mutable lifecycle metadata for immutable ranking snapshot facts.

The tables in this module are deliberately kept separate from
``ranking_schema_v1``.  The V1 fact tables are historical data and must remain
safe to read with the old ranking implementation; lifecycle metadata can be
evolved independently as retention and refresh policy changes.
"""

from sqlalchemy import CheckConstraint, Column, DateTime, Index, Integer, JSON, MetaData, Table, Text


metadata = MetaData()


snapshot_lifecycle = Table(
    "ranking_snapshot_lifecycle",
    metadata,
    Column("run_id", Text, primary_key=True),
    Column("period_start", DateTime(timezone=True), nullable=False),
    Column("period_end", DateTime(timezone=True), nullable=False),
    Column("metric_version", Text, nullable=False),
    Column("data_mode", Text, nullable=False),
    Column("source_fingerprint", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_accessed_at", DateTime(timezone=True), nullable=False),
    Column("next_refresh_at", DateTime(timezone=True)),
    Column("pinned_at", DateTime(timezone=True)),
    Column("pin_reason", Text),
    Column("pinned_by", Text),
    Column("metadata_json", JSON, nullable=False, default=dict),
    CheckConstraint("period_end > period_start", name="ck_ranking_lifecycle_period"),
    CheckConstraint(
        "data_mode IN ('business', 'synthetic')",
        name="ck_ranking_lifecycle_data_mode",
    ),
)
Index(
    "ix_ranking_lifecycle_key_created",
    snapshot_lifecycle.c.period_start,
    snapshot_lifecycle.c.period_end,
    snapshot_lifecycle.c.metric_version,
    snapshot_lifecycle.c.data_mode,
    snapshot_lifecycle.c.created_at,
)
Index(
    "ix_ranking_lifecycle_accessed",
    snapshot_lifecycle.c.last_accessed_at,
    snapshot_lifecycle.c.pinned_at,
)


source_change_counters = Table(
    "ranking_source_change_counters",
    metadata,
    Column("source_name", Text, primary_key=True),
    Column("generation", Integer, nullable=False, default=0),
    Column("changed_at", DateTime(timezone=True), nullable=False),
)


# Keep this list explicit.  It is the dependency contract for the ranking
# engine, and therefore also the trigger/fallback-fingerprint contract.  The
# internal ``ranking_lead_org_bindings`` table is intentionally excluded: it
# is a memoized attribution aid written while a snapshot is calculated and
# must not invalidate an otherwise stable source cache.
SOURCE_TABLES: tuple[str, ...] = (
    "raw_douyin_orders",
    "raw_douyin_order_coupons",
    "raw_douyin_verify_records",
    "raw_douyin_refund_records",
    "douyin_refund_event",
    "raw_douyin_clues",
    "raw_aweme_bindings",
    "dim_aweme_accounts",
    "dim_store_poi_mappings",
    "dim_sku_product_rules",
    "dim_stores",
    "dim_store_org_assignments",
    "settlement_order_details",
    "clue_center_orders",
    "clue_assignment_rounds",
    "clue_follow_up_records",
    "ranking_store_org_history",
    "ranking_store_eligibility",
)


__all__ = ["metadata", "snapshot_lifecycle", "source_change_counters", "SOURCE_TABLES"]
