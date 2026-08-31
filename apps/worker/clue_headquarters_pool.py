from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Mapping, MutableMapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueAllocationDecision,
    ClueHeadquartersPoolEntry,
    ClueMasterLead,
    utcnow,
)


HEADQUARTERS_POOL_REASON_CODES = (
    "missing_follow_poi",
    "anchor_store_unmapped",
    "anchor_geo_invalid",
    "no_published_rule",
    "all_strategies_disabled",
    "no_eligible_candidate",
    "all_strategies_exhausted",
    "data_inconsistency",
)

_HEADQUARTERS_POOL_REASON_ALIASES = {
    "missing_follow_poi": "missing_follow_poi",
    "follow_poi_missing": "missing_follow_poi",
    "anchor_store_unmapped": "anchor_store_unmapped",
    "follow_poi_unmapped": "anchor_store_unmapped",
    "follow_poi_store_missing": "anchor_store_unmapped",
    "anchor_geo_invalid": "anchor_geo_invalid",
    "anchor_coordinates_invalid": "anchor_geo_invalid",
    "anchor_province_missing": "anchor_geo_invalid",
    "anchor_city_missing": "anchor_geo_invalid",
    "anchor_city_code_missing": "anchor_geo_invalid",
    "no_published_rule": "no_published_rule",
    "rule_version_unavailable": "no_published_rule",
    "all_strategies_disabled": "all_strategies_disabled",
    "strategy_disabled": "all_strategies_disabled",
    "no_eligible_candidate": "no_eligible_candidate",
    "no_candidate": "no_eligible_candidate",
    "sale_store_unmapped": "no_eligible_candidate",
    "all_strategies_exhausted": "all_strategies_exhausted",
    "strategies_exhausted": "all_strategies_exhausted",
    "data_inconsistency": "data_inconsistency",
    "headquarters_pool_retained": "data_inconsistency",
    "order_id_missing": "data_inconsistency",
    "headquarters": "data_inconsistency",
}


def canonical_headquarters_pool_reason(value: str | None) -> str:
    normalized = str(value or "").strip()
    return _HEADQUARTERS_POOL_REASON_ALIASES.get(normalized, "data_inconsistency")


def headquarters_pool_reason_storage_values(reason_code: str) -> tuple[str, ...]:
    canonical = canonical_headquarters_pool_reason(reason_code)
    return tuple(
        sorted(
            value
            for value, mapped in _HEADQUARTERS_POOL_REASON_ALIASES.items()
            if mapped == canonical
        )
    )


def get_active_headquarters_pool_entry(session: Session, lead_key: str) -> ClueHeadquartersPoolEntry | None:
    return session.scalar(
        select(ClueHeadquartersPoolEntry)
        .where(ClueHeadquartersPoolEntry.lead_key == lead_key)
        .where(ClueHeadquartersPoolEntry.status == "active")
        .order_by(
            ClueHeadquartersPoolEntry.entered_at.desc(),
            ClueHeadquartersPoolEntry.headquarters_pool_entry_id.desc(),
        )
    )


def enter_headquarters_pool(
    session: Session,
    *,
    lead: ClueMasterLead,
    reason: str,
    entered_at: datetime | None = None,
    source_decision: ClueAllocationDecision | None = None,
    source_assignment_round_id: str | None = None,
    source_rule_version_id: str | None = None,
    allocation_cycle_id: str | None = None,
    source_snapshot: Mapping[str, Any] | None = None,
    _active_entries_by_lead: MutableMapping[str, ClueHeadquartersPoolEntry] | None = None,
    _flush: bool = True,
) -> ClueHeadquartersPoolEntry:
    occurred_at = _aware(entered_at or utcnow())
    original_reason = str(reason or "").strip()
    canonical_reason = canonical_headquarters_pool_reason(original_reason)
    if _flush:
        # A new master lead can enter the headquarters pool during the same materialization pass.
        session.flush([lead])
    decision_id = source_decision.decision_id if source_decision is not None else None
    active = (
        _active_entries_by_lead.get(lead.lead_key)
        if _active_entries_by_lead is not None
        else get_active_headquarters_pool_entry(session, lead.lead_key)
    )
    if active is not None and active.source_decision_id == decision_id:
        return active
    if active is not None:
        close_current_headquarters_pool_entry(
            session,
            lead.lead_key,
            closed_at=occurred_at,
            close_reason="superseded_by_new_allocation",
            status="superseded",
            _active_entries_by_lead=_active_entries_by_lead,
        )

    decision_snapshot = dict(source_decision.decision_snapshot or {}) if source_decision is not None else dict(source_snapshot or {})
    if original_reason and original_reason != canonical_reason:
        decision_snapshot.setdefault("original_reason_code", original_reason)
    entry_key = "|".join(
        (
            lead.lead_key,
            decision_id or "",
            canonical_reason,
            allocation_cycle_id or "",
            occurred_at.isoformat(),
        )
    )
    entry = ClueHeadquartersPoolEntry(
        headquarters_pool_entry_id=f"headquarters-pool-{sha256(entry_key.encode('utf-8')).hexdigest()[:24]}",
        lead_key=lead.lead_key,
        status="active",
        reason=canonical_reason,
        entered_at=occurred_at,
        source_assignment_round_id=(
            source_assignment_round_id
            if source_assignment_round_id is not None
            else (source_decision.assignment_round_id if source_decision is not None else None)
        ),
        source_decision_id=decision_id,
        source_rule_version_id=(
            source_rule_version_id
            if source_rule_version_id is not None
            else (source_decision.rule_version_id if source_decision is not None else None)
        ),
        allocation_cycle_id=(
            allocation_cycle_id
            if allocation_cycle_id is not None
            else (source_decision.allocation_cycle_id if source_decision is not None else None)
        ),
        source_snapshot=decision_snapshot,
        created_at=occurred_at,
        updated_at=occurred_at,
    )
    session.add(entry)
    if _active_entries_by_lead is not None:
        _active_entries_by_lead[lead.lead_key] = entry
    if _flush:
        session.flush()
    return entry


def ensure_active_headquarters_pool_entry(
    session: Session,
    *,
    lead: ClueMasterLead,
    reason: str,
    entered_at: datetime | None = None,
    source_snapshot: Mapping[str, Any] | None = None,
    _active_entries_by_lead: MutableMapping[str, ClueHeadquartersPoolEntry] | None = None,
    _flush: bool = True,
) -> ClueHeadquartersPoolEntry:
    active = (
        _active_entries_by_lead.get(lead.lead_key)
        if _active_entries_by_lead is not None
        else get_active_headquarters_pool_entry(session, lead.lead_key)
    )
    if active is not None:
        return active
    return enter_headquarters_pool(
        session,
        lead=lead,
        reason=reason,
        entered_at=entered_at,
        source_snapshot=source_snapshot,
        _active_entries_by_lead=_active_entries_by_lead,
        _flush=_flush,
    )


def close_current_headquarters_pool_entry(
    session: Session,
    lead_key: str,
    *,
    closed_at: datetime | None = None,
    close_reason: str,
    status: str = "closed",
    _active_entries_by_lead: MutableMapping[str, ClueHeadquartersPoolEntry] | None = None,
) -> ClueHeadquartersPoolEntry | None:
    entry = (
        _active_entries_by_lead.get(lead_key)
        if _active_entries_by_lead is not None
        else get_active_headquarters_pool_entry(session, lead_key)
    )
    if entry is None:
        return None
    occurred_at = _aware(closed_at or utcnow())
    entry.status = status
    entry.closed_at = occurred_at
    entry.close_reason = close_reason
    entry.updated_at = occurred_at
    if _active_entries_by_lead is not None:
        _active_entries_by_lead.pop(lead_key, None)
    return entry


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
