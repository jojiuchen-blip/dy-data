"""Resolve signed-off area corrections without mutating imported rosters."""
from sqlalchemy import Column, DateTime, MetaData, Table, Text, and_, func, inspect, select
from .ranking_schema_v1 import org_history

corrections = Table("ranking_area_corrections", MetaData(),
    Column("mapping_version", Text, primary_key=True), Column("store_id", Text, primary_key=True),
    *(Column(k, Text, nullable=False) for k in (
        "service_store_code", "source_hash", "old_key", "old_area", "new_key", "new_area", "reason")),
    Column("recorded_at", DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()))


def effective_roster(session, cutoff=None):
    original = org_history
    # Legacy / isolated installs without this migration keep their original roster.
    if not inspect(session.connection()).has_table(corrections.name):
        return original
    c = corrections.c
    o = original.c
    match = and_(c.mapping_version == o.mapping_version, c.store_id == o.store_id,
                 c.source_hash == o.source_hash, c.service_store_code == o.service_store_code,
                 c.old_key == o.area_key, c.old_area == o.area_name)
    if cutoff is not None:
        match = and_(match, c.recorded_at <= cutoff)
    replacements = {"area_key": c.new_key, "area_name": c.new_area}
    return select(*(func.coalesce(replacements[k.name], k).label(k.name)
                    if k.name in replacements else k for k in original.c)
                  ).select_from(original.outerjoin(corrections, match)).subquery()
