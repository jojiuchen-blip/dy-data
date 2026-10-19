"""Narrow, immutable ranking facts registered with publication metadata."""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Table, Text

from apps.api.dy_api.dashboard_publications.schema import metadata

lead_bindings = Table("dashboard_ranking_lead_bindings", metadata,
    Column("lead_key", Text, primary_key=True),
    Column("first_assigned_at", DateTime(timezone=True), nullable=False),
    Column("mapping_version", Text, nullable=False))


def _publication_column():
    return Column("publication_id", String(64), ForeignKey("dashboard_publication_runs.id", ondelete="CASCADE"), primary_key=True)


info = Table("dashboard_ranking_info", metadata, _publication_column(),
    Column("cutoff", DateTime(timezone=True), nullable=False))

organizations = Table("dashboard_ranking_organizations", metadata, _publication_column(),
    Column("mapping_version", Text, primary_key=True), Column("store_id", Text, primary_key=True),
    Column("effective_from", DateTime(timezone=True), nullable=False),
    Column("service_store_code", Text, nullable=False), Column("store_name", Text, nullable=False),
    *[Column(name, Text) for name in ("group_key", "group_name", "service_center_key", "service_center_name",
        "district_key", "district_name", "area_key", "area_name")])
Index("ix_dashboard_ranking_org_date", organizations.c.publication_id, organizations.c.effective_from)

eligibility = Table("dashboard_ranking_eligibility", metadata, _publication_column(),
    Column("eligibility_version", Text, primary_key=True), Column("service_store_code", Text, primary_key=True),
    Column("effective_from", DateTime(timezone=True), nullable=False))
Index("ix_dashboard_ranking_eligibility_date", eligibility.c.publication_id, eligibility.c.effective_from)

orders = Table("dashboard_ranking_orders", metadata, _publication_column(),
    Column("order_id", Text, primary_key=True), Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("store_id", Text), Column("is_jingcheng", Boolean, nullable=False),
    Column("reason", Text), Column("historical_unverified", Boolean, nullable=False))
Index("ix_dashboard_ranking_orders_date", orders.c.publication_id, orders.c.occurred_at, orders.c.store_id)

rounds = Table("dashboard_ranking_rounds", metadata, _publication_column(),
    Column("round_id", Text, primary_key=True), Column("order_id", Text, nullable=False),
    Column("lead_key", Text, nullable=False), Column("store_id", Text), Column("mapping_version", Text),
    Column("assigned_at", DateTime(timezone=True), nullable=False), Column("is_jingcheng", Boolean, nullable=False),
    Column("follow_24h", Integer, nullable=False), Column("follow_any", Integer, nullable=False),
    Column("self_verified", Integer, nullable=False), Column("under_observation", Boolean, nullable=False),
    Column("first_assignment_changed", Boolean, nullable=False))
Index("ix_dashboard_ranking_rounds_date", rounds.c.publication_id, rounds.c.assigned_at, rounds.c.store_id)
Index("ix_dashboard_ranking_rounds_responsibility", rounds.c.publication_id, rounds.c.order_id, rounds.c.store_id, rounds.c.assigned_at)
