from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueAllocationDecision,
    ClueHeadquartersPoolEntry,
    ClueMasterLead,
    utcnow,
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
) -> ClueHeadquartersPoolEntry:
    occurred_at = _aware(entered_at or utcnow())
    decision_id = source_decision.decision_id if source_decision is not None else None
    active = get_active_headquarters_pool_entry(session, lead.lead_key)
    if active is not None and active.source_decision_id == decision_id:
        return active
    if active is not None:
        close_current_headquarters_pool_entry(
            session,
            lead.lead_key,
            closed_at=occurred_at,
            close_reason="superseded_by_new_allocation",
            status="superseded",
        )

    decision_snapshot = dict(source_decision.decision_snapshot or {}) if source_decision is not None else dict(source_snapshot or {})
    entry_key = "|".join(
        (
            lead.lead_key,
            decision_id or "",
            reason,
            allocation_cycle_id or "",
            occurred_at.isoformat(),
        )
    )
    entry = ClueHeadquartersPoolEntry(
        headquarters_pool_entry_id=f"headquarters-pool-{sha256(entry_key.encode('utf-8')).hexdigest()[:24]}",
        lead_key=lead.lead_key,
        status="active",
        reason=reason,
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
    session.flush()
    return entry


def ensure_active_headquarters_pool_entry(
    session: Session,
    *,
    lead: ClueMasterLead,
    reason: str,
    entered_at: datetime | None = None,
    source_snapshot: Mapping[str, Any] | None = None,
) -> ClueHeadquartersPoolEntry:
    active = get_active_headquarters_pool_entry(session, lead.lead_key)
    if active is not None:
        return active
    return enter_headquarters_pool(
        session,
        lead=lead,
        reason=reason,
        entered_at=entered_at,
        source_snapshot=source_snapshot,
    )


def close_current_headquarters_pool_entry(
    session: Session,
    lead_key: str,
    *,
    closed_at: datetime | None = None,
    close_reason: str,
    status: str = "closed",
) -> ClueHeadquartersPoolEntry | None:
    entry = get_active_headquarters_pool_entry(session, lead_key)
    if entry is None:
        return None
    occurred_at = _aware(closed_at or utcnow())
    entry.status = status
    entry.closed_at = occurred_at
    entry.close_reason = close_reason
    entry.updated_at = occurred_at
    return entry


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
