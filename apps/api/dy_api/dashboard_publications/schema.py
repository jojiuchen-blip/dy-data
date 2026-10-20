"""Shared sidecar DDL. Production creation belongs exclusively to Alembic."""

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKeyConstraint, Index,
    JSON, MetaData, String, Table, Text, UniqueConstraint,
)

metadata = MetaData()

runs = Table(
    "dashboard_publication_runs", metadata,
    Column("id", String(64), primary_key=True),
    Column("module", String(64), nullable=False),
    Column("status", String(16), nullable=False),
    Column("cutoff", DateTime(timezone=True), nullable=False),
    Column("data_as_of", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True)),
    Column("next_refresh_at", DateTime(timezone=True)),
    Column("source_fingerprint", String(64)),
    Column("error_code", String(64)),
    Column("stats_json", JSON, nullable=False, default=dict),
    Column("pinned_at", DateTime(timezone=True)),
    Column("pin_reason", Text),
    Column("pinned_by", String(128)),
    UniqueConstraint("module", "id", name="uq_dashboard_publication_module_id"),
    CheckConstraint("status IN ('building', 'success', 'failed')", name="ck_dashboard_publication_status"),
    CheckConstraint("(status = 'success' AND published_at IS NOT NULL) OR "
                    "(status <> 'success' AND published_at IS NULL)", name="ck_dashboard_publication_published"),
)
Index("ix_dashboard_publication_module_created", runs.c.module, runs.c.created_at, runs.c.id)
Index("ix_dashboard_publication_module_published", runs.c.module, runs.c.status, runs.c.published_at)

heads = Table(
    "dashboard_publication_heads", metadata,
    Column("module", String(64), primary_key=True),
    Column("publication_id", String(64), nullable=False),
    ForeignKeyConstraint(
        ["module", "publication_id"], ["dashboard_publication_runs.module", "dashboard_publication_runs.id"],
        name="fk_dashboard_publication_head", ondelete="RESTRICT",
    ),
)

source_counters = Table(
    "dashboard_publication_source_counters", metadata,
    Column("source_name", String(128), primary_key=True),
    Column("generation", BigInteger, nullable=False, default=0),
    Column("changed_at", DateTime(timezone=True), nullable=False),
)
