"""add clue allocation M1 foundation

Revision ID: 20260712_0012
Revises: 20260706_0011
Create Date: 2026-07-12 20:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260712_0012"
down_revision = "20260706_0011"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _column_names(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if _has_table(table_name) and column.name not in _column_names(table_name):
        op.add_column(table_name, column)


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    if _has_table(table_name) and index_name not in _index_names(table_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _drop_index_if_present(index_name: str, table_name: str) -> None:
    if _has_table(table_name) and index_name in _index_names(table_name):
        op.drop_index(index_name, table_name=table_name)


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _json_server_default():
    if op.get_bind().dialect.name == "postgresql":
        return sa.text("'{}'::jsonb")
    return sa.text("'{}'")


def upgrade() -> None:
    _add_column_if_missing("raw_douyin_clues", sa.Column("follow_poi_id", sa.Text()))
    _add_column_if_missing("raw_douyin_clues", sa.Column("intention_poi_id", sa.Text()))
    _create_index_if_missing("ix_raw_douyin_clues_follow_poi_id", "raw_douyin_clues", ["follow_poi_id"])
    _create_index_if_missing("ix_raw_douyin_clues_intention_poi_id", "raw_douyin_clues", ["intention_poi_id"])

    for column in (
        sa.Column("standard_province", sa.Text()),
        sa.Column("standard_city", sa.Text()),
        sa.Column("city_code", sa.Text()),
        sa.Column("longitude", sa.Numeric(10, 6)),
        sa.Column("latitude", sa.Numeric(10, 6)),
        sa.Column("is_douyin_clue_applicable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("participates_in_clue_allocation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("location_source", sa.Text()),
        sa.Column("location_status", sa.String(length=32), nullable=False, server_default="missing"),
        sa.Column("location_status_note", sa.Text()),
        sa.Column("location_updated_at", sa.DateTime(timezone=True)),
    ):
        _add_column_if_missing("dim_stores", column)
    _create_index_if_missing("ix_dim_stores_city_code", "dim_stores", ["city_code"])
    _create_index_if_missing("ix_dim_stores_douyin_clue_applicable", "dim_stores", ["is_douyin_clue_applicable"])
    _create_index_if_missing("ix_dim_stores_clue_allocation", "dim_stores", ["participates_in_clue_allocation"])
    _create_index_if_missing("ix_dim_stores_location_status", "dim_stores", ["location_status"])

    for column in (
        sa.Column("execution_mode", sa.String(length=32), nullable=False, server_default="legacy"),
        sa.Column("matured_at", sa.DateTime(timezone=True)),
        sa.Column("terminal_reason", sa.Text()),
    ):
        _add_column_if_missing("clue_assignment_rounds", column)
    _create_index_if_missing("ix_clue_assignment_rounds_execution_mode", "clue_assignment_rounds", ["execution_mode"])
    _create_index_if_missing("ix_clue_assignment_rounds_matured_at", "clue_assignment_rounds", ["matured_at"])

    if not _has_table("clue_master_leads"):
        op.create_table(
            "clue_master_leads",
            sa.Column("lead_key", sa.Text(), primary_key=True),
            sa.Column("source_clue_row_key", sa.Text(), nullable=False),
            sa.Column("source_identity_key", sa.Text(), nullable=False),
            sa.Column("canonical_clue_id", sa.Text()),
            sa.Column("order_id", sa.Text()),
            sa.Column("raw_order_status", sa.Text()),
            sa.Column("normalized_order_status", sa.String(length=32), nullable=False, server_default="unknown"),
            sa.Column("status_source", sa.String(length=32), nullable=False, server_default="clue"),
            sa.Column("lifecycle_status", sa.String(length=32), nullable=False, server_default="active"),
            sa.Column("pool_location", sa.String(length=32)),
            sa.Column("allocation_state", sa.String(length=32), nullable=False, server_default="pending_allocation"),
            sa.Column("current_assignment_round_id", sa.Text()),
            sa.Column("allocation_cycle_id", sa.Text()),
            sa.Column("ended_without_assignment", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("closed_at", sa.DateTime(timezone=True)),
            sa.Column("closed_reason", sa.Text()),
            sa.Column("first_seen_at", sa.DateTime(timezone=True)),
            sa.Column("last_seen_at", sa.DateTime(timezone=True)),
            sa.Column("anchor_poi_id", sa.Text()),
            sa.Column("anchor_store_id", sa.Text()),
            sa.Column("anchor_source", sa.Text()),
            sa.Column("anchor_unavailable_reason", sa.Text()),
            sa.Column("anchor_province", sa.Text()),
            sa.Column("anchor_city", sa.Text()),
            sa.Column("anchor_city_code", sa.Text()),
            sa.Column("anchor_longitude", sa.Numeric(10, 6)),
            sa.Column("anchor_latitude", sa.Numeric(10, 6)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("source_clue_row_key", name="uq_clue_master_leads_source_clue_row_key"),
            sa.UniqueConstraint("source_identity_key", name="uq_clue_master_leads_source_identity_key"),
        )
    for index_name, columns, unique in (
        ("ix_clue_master_leads_canonical_clue_id", ["canonical_clue_id"], False),
        ("ix_clue_master_leads_order_id", ["order_id"], False),
        ("ix_clue_master_leads_normalized_order_status", ["normalized_order_status"], False),
        ("ix_clue_master_leads_lifecycle_status", ["lifecycle_status"], False),
        ("ix_clue_master_leads_pool_location", ["pool_location"], False),
        ("ix_clue_master_leads_allocation_state", ["allocation_state"], False),
        ("ix_clue_master_leads_current_assignment_round_id", ["current_assignment_round_id"], False),
        ("ix_clue_master_leads_allocation_cycle_id", ["allocation_cycle_id"], False),
        ("ix_clue_master_leads_ended_without_assignment", ["ended_without_assignment"], False),
        ("ix_clue_master_leads_closed_at", ["closed_at"], False),
        ("ix_clue_master_leads_first_seen_at", ["first_seen_at"], False),
        ("ix_clue_master_leads_last_seen_at", ["last_seen_at"], False),
        ("ix_clue_master_leads_anchor_poi_id", ["anchor_poi_id"], False),
        ("ix_clue_master_leads_anchor_store_id", ["anchor_store_id"], False),
        ("ix_clue_master_leads_anchor_city_code", ["anchor_city_code"], False),
        ("ix_clue_master_leads_order_location", ["order_id", "pool_location"], False),
        ("ix_clue_master_leads_lifecycle_location", ["lifecycle_status", "pool_location"], False),
        ("ix_clue_master_leads_anchor_store", ["anchor_store_id"], False),
    ):
        _create_index_if_missing(index_name, "clue_master_leads", columns, unique=unique)

    if not _has_table("clue_order_status_events"):
        op.create_table(
            "clue_order_status_events",
            sa.Column("event_id", sa.Text(), primary_key=True),
            sa.Column("event_key", sa.Text(), nullable=False),
            sa.Column("lead_key", sa.Text(), nullable=False),
            sa.Column("order_id", sa.Text()),
            sa.Column("raw_status", sa.Text()),
            sa.Column("normalized_status", sa.String(length=32), nullable=False),
            sa.Column("status_source", sa.String(length=32), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("event_key", name="uq_clue_order_status_events_event_key"),
        )
    _create_index_if_missing("ix_clue_order_status_events_lead_key", "clue_order_status_events", ["lead_key"])
    _create_index_if_missing("ix_clue_order_status_events_order_id", "clue_order_status_events", ["order_id"])
    _create_index_if_missing("ix_clue_order_status_events_normalized_status", "clue_order_status_events", ["normalized_status"])
    _create_index_if_missing("ix_clue_order_status_events_observed_at", "clue_order_status_events", ["observed_at"])
    _create_index_if_missing("ix_clue_order_status_events_lead_observed", "clue_order_status_events", ["lead_key", "observed_at"])

    if not _has_table("store_score_snapshot_runs"):
        op.create_table(
            "store_score_snapshot_runs",
            sa.Column("snapshot_run_id", sa.Text(), primary_key=True),
            sa.Column("snapshot_date", sa.Date(), nullable=False),
            sa.Column("run_mode", sa.String(length=32), nullable=False, server_default="scheduled"),
            sa.Column("scheduled_key", sa.Text()),
            sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("candidate_store_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("snapshot_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("triggered_by", sa.Text()),
            sa.Column("config_json", _json_type(), nullable=False, server_default=_json_server_default()),
            sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("scheduled_key", name="uq_store_score_snapshot_runs_scheduled_key"),
        )
    for index_name, columns in (
        ("ix_store_score_snapshot_runs_snapshot_date", ["snapshot_date"]),
        ("ix_store_score_snapshot_runs_run_mode", ["run_mode"]),
        ("ix_store_score_snapshot_runs_date_mode", ["snapshot_date", "run_mode"]),
    ):
        _create_index_if_missing(index_name, "store_score_snapshot_runs", columns)

    if not _has_table("store_score_snapshots"):
        op.create_table(
            "store_score_snapshots",
            sa.Column("snapshot_id", sa.Text(), primary_key=True),
            sa.Column(
                "snapshot_run_id",
                sa.Text(),
                sa.ForeignKey("store_score_snapshot_runs.snapshot_run_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("snapshot_date", sa.Date(), nullable=False),
            sa.Column("run_mode", sa.String(length=32), nullable=False, server_default="scheduled"),
            sa.Column("store_id", sa.Text(), sa.ForeignKey("dim_stores.store_id", ondelete="CASCADE"), nullable=False),
            sa.Column("city_code", sa.Text()),
            sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("conversion_numerator", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("conversion_denominator", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("conversion_rate", sa.Numeric(10, 6), nullable=False, server_default="0"),
            sa.Column("conversion_value_source", sa.String(length=32), nullable=False, server_default="cold_start_empty"),
            sa.Column("follow_24h_numerator", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("follow_24h_denominator", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("follow_24h_rate", sa.Numeric(10, 6), nullable=False, server_default="0"),
            sa.Column("follow_24h_value_source", sa.String(length=32), nullable=False, server_default="cold_start_empty"),
            sa.Column("conversion_weight", sa.Numeric(6, 4), nullable=False, server_default="0.7"),
            sa.Column("follow_24h_weight", sa.Numeric(6, 4), nullable=False, server_default="0.3"),
            sa.Column("store_weight", sa.Numeric(8, 4), nullable=False, server_default="1"),
            sa.Column("composite_score", sa.Numeric(12, 6), nullable=False, server_default="0"),
            sa.Column("config_json", _json_type(), nullable=False, server_default=_json_server_default()),
            sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("snapshot_run_id", "store_id", name="uq_store_score_snapshots_run_store"),
        )
    for index_name, columns in (
        ("ix_store_score_snapshots_snapshot_run_id", ["snapshot_run_id"]),
        ("ix_store_score_snapshots_snapshot_date", ["snapshot_date"]),
        ("ix_store_score_snapshots_store_id", ["store_id"]),
        ("ix_store_score_snapshots_city_code", ["city_code"]),
        ("ix_store_score_snapshots_composite_score", ["composite_score"]),
        ("ix_store_score_snapshots_date_store", ["snapshot_date", "store_id"]),
        ("ix_store_score_snapshots_city_date", ["city_code", "snapshot_date"]),
    ):
        _create_index_if_missing(index_name, "store_score_snapshots", columns)


def downgrade() -> None:
    if _has_table("store_score_snapshots"):
        op.drop_table("store_score_snapshots")
    if _has_table("store_score_snapshot_runs"):
        op.drop_table("store_score_snapshot_runs")
    if _has_table("clue_order_status_events"):
        op.drop_table("clue_order_status_events")
    if _has_table("clue_master_leads"):
        op.drop_table("clue_master_leads")
    if _has_table("clue_assignment_rounds"):
        for index_name in (
            "ix_clue_assignment_rounds_execution_mode",
            "ix_clue_assignment_rounds_matured_at",
        ):
            _drop_index_if_present(index_name, "clue_assignment_rounds")
        for column in ("terminal_reason", "matured_at", "execution_mode"):
            if column in _column_names("clue_assignment_rounds"):
                op.drop_column("clue_assignment_rounds", column)
    if _has_table("dim_stores"):
        for index_name in (
            "ix_dim_stores_city_code",
            "ix_dim_stores_douyin_clue_applicable",
            "ix_dim_stores_clue_allocation",
            "ix_dim_stores_location_status",
        ):
            _drop_index_if_present(index_name, "dim_stores")
        for column in (
            "location_updated_at",
            "location_status_note",
            "location_status",
            "location_source",
            "participates_in_clue_allocation",
            "is_douyin_clue_applicable",
            "latitude",
            "longitude",
            "city_code",
            "standard_city",
            "standard_province",
        ):
            if column in _column_names("dim_stores"):
                op.drop_column("dim_stores", column)
    if _has_table("raw_douyin_clues"):
        for index_name in (
            "ix_raw_douyin_clues_follow_poi_id",
            "ix_raw_douyin_clues_intention_poi_id",
        ):
            _drop_index_if_present(index_name, "raw_douyin_clues")
        for column in ("intention_poi_id", "follow_poi_id"):
            if column in _column_names("raw_douyin_clues"):
                op.drop_column("raw_douyin_clues", column)
