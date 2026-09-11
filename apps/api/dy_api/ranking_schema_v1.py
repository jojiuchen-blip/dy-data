"""Frozen V1 DDL shared by the local migration and snapshot engine.

Do not change these definitions after deployment; evolve with a new migration.
These sidecar tables never change the clue-center or settlement schema.
"""
from sqlalchemy import (MetaData, Table, Column, Text, Integer, DateTime, JSON,
                        ForeignKeyConstraint, CheckConstraint, Index)

metadata = MetaData()

org_history = Table(
    "ranking_store_org_history", metadata,
    Column("mapping_version", Text, primary_key=True),
    Column("store_id", Text, primary_key=True),
    Column("service_store_code", Text, nullable=False),
    Column("store_name", Text, nullable=False),
    Column("effective_from", DateTime(timezone=True), nullable=False),
    Column("group_key", Text), Column("group_name", Text),
    Column("service_center_key", Text), Column("service_center_name", Text),
    Column("district_key", Text), Column("district_name", Text),
    Column("area_key", Text), Column("area_name", Text),
    Column("source_hash", Text, nullable=False),
)
Index("ix_ranking_org_effective", org_history.c.effective_from)

eligibility = Table(
    "ranking_store_eligibility", metadata,
    Column("eligibility_version", Text, primary_key=True),
    Column("service_store_code", Text, primary_key=True),
    Column("product_scope", Text, nullable=False),
    Column("effective_from", DateTime(timezone=True), nullable=False),
    Column("source_hash", Text, nullable=False),
)

lead_bindings = Table(
    "ranking_lead_org_bindings", metadata,
    Column("lead_key", Text, primary_key=True),
    Column("first_assigned_at", DateTime(timezone=True), nullable=False),
    Column("mapping_version", Text, nullable=False),
)

runs = Table(
    "ranking_snapshot_runs", metadata,
    Column("run_id", Text, primary_key=True),
    Column("period_start", DateTime(timezone=True), nullable=False),
    Column("period_end", DateTime(timezone=True), nullable=False),
    Column("observed_through", DateTime(timezone=True), nullable=False),
    Column("roster_at", DateTime(timezone=True), nullable=False),
    Column("eligibility_version", Text, nullable=False),
    Column("metric_version", Text, nullable=False),
    Column("data_mode", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("quality_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("status IN ('building', 'success')", name="ck_ranking_run_status"),
    CheckConstraint("period_end > period_start", name="ck_ranking_period"),
)
Index("ix_ranking_runs_period", runs.c.period_start, runs.c.period_end, runs.c.created_at)

samples = Table(
    "ranking_metric_sample_facts", metadata,
    Column("run_id", Text, primary_key=True),
    Column("metric_key", Text, primary_key=True),
    Column("sample_key", Text, primary_key=True),
    Column("store_id", Text), Column("mapping_version", Text),
    Column("sample_time", DateTime(timezone=True)),
    Column("numerator", Integer, nullable=False),
    Column("denominator", Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column("reason_code", Text), Column("evidence_json", JSON, nullable=False),
    ForeignKeyConstraint(["run_id"], ["ranking_snapshot_runs.run_id"]),
    CheckConstraint("numerator >= 0 AND denominator >= 0", name="ck_ranking_samples_nonnegative"),
    CheckConstraint("status IN ('included', 'unresolved', 'excluded')", name="ck_ranking_sample_status"),
)
Index("ix_ranking_samples_store", samples.c.run_id, samples.c.store_id)

snapshots = Table(
    "indicator_board_metric_snapshots", metadata,
    Column("run_id", Text, primary_key=True),
    Column("store_id", Text, primary_key=True),
    Column("mapping_version", Text, primary_key=True),
    Column("metric_key", Text, primary_key=True),
    Column("numerator", Integer, nullable=False),
    Column("denominator", Integer, nullable=False),
    ForeignKeyConstraint(["run_id"], ["ranking_snapshot_runs.run_id"]),
    ForeignKeyConstraint(["mapping_version", "store_id"],
                         ["ranking_store_org_history.mapping_version", "ranking_store_org_history.store_id"]),
    CheckConstraint("numerator >= 0 AND denominator >= 0", name="ck_ranking_snapshots_nonnegative"),
)
