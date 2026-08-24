from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueAllocationRuleVersion,
    ClueAssignmentRound,
    ClueCenterOrder,
    ClueFollowUpRecord,
    ClueHeadquartersPoolEntry,
    ClueLeadRuleVersionBinding,
    ClueMasterLead,
    ClueOrderStatusEvent,
    ClueSourceIdentifierHistory,
    DataQualityIssue,
    DimStore,
    DimStorePoiMapping,
    RawDouyinClue,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
    SettlementOrderDetail,
    StoreScoreSnapshot,
    StoreScoreSnapshotRun,
    utcnow,
)
from apps.worker.clue_headquarters_pool import (
    close_current_headquarters_pool_entry,
    ensure_active_headquarters_pool_entry,
)
from apps.worker.order_status import normalize_coupon_status, resolve_clue_order_status
from apps.worker.repositories import upsert_data_quality_issue


SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_STORE_WEIGHT = Decimal("1")
SCHEDULED_SCORE_REFRESH_TIME = time(hour=3)
MASTER_MATERIALIZATION_LOCK = "clue-allocation-master-materialization"
MASTER_STATUS_REPAIR_LOCK = "clue-allocation-master-status-repair"
MASTER_TERMINAL_SYNC_LOCK = "clue-allocation-master-terminal-sync"
SCHEDULED_SCORE_REFRESH_LOCK = "clue-allocation-scheduled-score-refresh"
SELF_OWNED_EXECUTION_MODES = {"formal", "trial"}
MATERIALIZATION_QUERY_BATCH_SIZE = 10_000


@dataclass(frozen=True)
class StatusResolution:
    raw_status: str | None
    normalized_status: str
    status_source: str
    closed_at: datetime | None


@dataclass(frozen=True)
class AnchorSnapshot:
    poi_id: str | None
    store_id: str | None
    unavailable_reason: str | None
    province: str | None
    city: str | None
    city_code: str | None
    longitude: Decimal | None
    latitude: Decimal | None


@dataclass
class StoreMetrics:
    conversion_numerator: int = 0
    conversion_denominator: int = 0
    follow_24h_numerator: int = 0
    follow_24h_denominator: int = 0

    def add(self, *, converted: bool, followed_within_24h: bool, has_full_follow_up_opportunity: bool) -> None:
        self.conversion_denominator += 1
        if converted:
            self.conversion_numerator += 1
        if has_full_follow_up_opportunity:
            self.follow_24h_denominator += 1
        if has_full_follow_up_opportunity and followed_within_24h:
            self.follow_24h_numerator += 1


@dataclass(frozen=True)
class StoreScoreConfig:
    rule_version_id: str | None
    lookback_days: int
    min_samples: int
    conversion_weight: Decimal
    follow_weight: Decimal
    store_weight: Decimal


def materialize_clue_master_leads(session: Session, *, now: datetime | None = None) -> dict[str, object]:
    """Build the new full clue master ledger without mutating raw Douyin rows."""
    now = _aware(now or utcnow())
    if not _try_transaction_lock(session, lock_name=MASTER_MATERIALIZATION_LOCK):
        return {"master_leads": 0, "closed_leads": 0, "headquarters_pool": 0, "skipped": "locked"}
    raw_clues = session.scalars(select(RawDouyinClue)).all()
    if not raw_clues:
        return {"master_leads": 0, "closed_leads": 0, "headquarters_pool": 0}

    order_ids = {_clean(row.order_id) for row in raw_clues}
    order_ids.discard(None)
    raw_orders = _raw_orders_by_id(session, order_ids)
    coupon_statuses_by_order = _coupon_statuses_by_order(session, order_ids)
    verified_at_by_order = _verified_at_by_order(session, order_ids)
    stores_by_id = {row.store_id: row for row in session.scalars(select(DimStore)).all()}
    mappings_by_poi = {row.poi_id: row for row in session.scalars(select(DimStorePoiMapping)).all()}
    _enrich_store_locations_from_raw_evidence(
        session,
        raw_clues,
        mappings_by_poi,
        stores_by_id,
        now,
    )
    existing_rows = session.scalars(select(ClueMasterLead)).all()
    existing_by_lead_key = {row.lead_key: row for row in existing_rows}
    existing_by_source_clue_row_key = {row.source_clue_row_key: row for row in existing_rows}
    existing_by_identity = {row.source_identity_key: row for row in existing_rows}
    existing_by_canonical_clue_id = {
        row.canonical_clue_id: row for row in existing_rows if row.canonical_clue_id
    }
    masters_by_order_id: dict[str, list[ClueMasterLead]] = defaultdict(list)
    for row in existing_rows:
        if order_id := _clean(row.order_id):
            masters_by_order_id[order_id].append(row)
    existing_by_order_id = {
        order_id: rows[0] for order_id, rows in masters_by_order_id.items() if len(rows) == 1
    }
    identifier_history_rows = session.scalars(select(ClueSourceIdentifierHistory)).all()
    identifier_history_by_key = {
        (row.source_clue_row_key, row.identifier_type, row.identifier_value): row
        for row in identifier_history_rows
    }
    current_identifier_history_by_source_type: dict[
        tuple[str, str], list[ClueSourceIdentifierHistory]
    ] = defaultdict(list)
    source_history_lead_keys: dict[str, set[str]] = defaultdict(set)
    for row in identifier_history_rows:
        source_history_lead_keys[row.source_clue_row_key].add(row.lead_key)
        if row.is_current:
            current_identifier_history_by_source_type[
                (row.source_clue_row_key, row.identifier_type)
            ].append(row)
    for source_clue_row_key, lead_keys in source_history_lead_keys.items():
        if len(lead_keys) != 1:
            continue
        lead = existing_by_lead_key.get(next(iter(lead_keys)))
        if lead is not None:
            existing_by_source_clue_row_key.setdefault(source_clue_row_key, lead)
    current_round_ids = {
        row.current_assignment_round_id for row in existing_rows if row.current_assignment_round_id
    }
    current_rounds_by_id: dict[str, ClueAssignmentRound] = {}
    for round_id_batch in _materialization_order_id_batches(current_round_ids):
        current_rounds_by_id.update(
            {
                row.assignment_round_id: row
                for row in session.scalars(
                    select(ClueAssignmentRound).where(
                        ClueAssignmentRound.assignment_round_id.in_(round_id_batch)
                    )
                ).all()
            }
        )
    center_orders_by_id: dict[str, ClueCenterOrder] = {}
    for order_id_batch in _materialization_order_id_batches(order_ids):
        center_orders_by_id.update(
            {
                row.order_id: row
                for row in session.scalars(
                    select(ClueCenterOrder).where(ClueCenterOrder.order_id.in_(order_id_batch))
                ).all()
            }
        )
    legacy_round_ids = {
        row.current_assignment_round_id
        for row in center_orders_by_id.values()
        if row.current_assignment_round_id and row.current_assignment_round_id not in current_rounds_by_id
    }
    for round_id_batch in _materialization_order_id_batches(legacy_round_ids):
        current_rounds_by_id.update(
            {
                row.assignment_round_id: row
                for row in session.scalars(
                    select(ClueAssignmentRound).where(
                        ClueAssignmentRound.assignment_round_id.in_(round_id_batch)
                    )
                ).all()
            }
        )
    active_headquarters_entries_by_lead = {
        row.lead_key: row
        for row in session.scalars(
            select(ClueHeadquartersPoolEntry).where(ClueHeadquartersPoolEntry.status == "active")
        ).all()
    }
    anchor_issue_ids = set(
        session.scalars(
            select(DataQualityIssue.issue_id).where(DataQualityIssue.issue_id.like("clue-anchor:%"))
        ).all()
    )
    status_event_ids = set(session.scalars(select(ClueOrderStatusEvent.event_id)).all())

    materialized_lead_keys: set[str] = set()
    closed_lead_keys: set[str] = set()
    headquarters_pool_keys: set[str] = set()
    for raw_clue in raw_clues:
        source_identity_key = _source_identity_key(raw_clue)
        canonical_clue_id = _clean(raw_clue.clue_id)
        order_id = _clean(raw_clue.order_id)
        source_match = existing_by_source_clue_row_key.get(raw_clue.clue_row_key)
        order_match = existing_by_order_id.get(order_id) if order_id else None
        identity_match = existing_by_identity.get(source_identity_key)
        canonical_match = (
            existing_by_canonical_clue_id.get(canonical_clue_id) if canonical_clue_id else None
        )
        lead_key_match = existing_by_lead_key.get(_lead_key(source_identity_key))

        conflict_reason = _master_match_conflict_reason(
            source_match=source_match,
            order_match=order_match,
            identity_match=identity_match,
            order_id=order_id,
        )
        if conflict_reason:
            _record_identity_mapping_conflict(
                session,
                raw_clue=raw_clue,
                source_match=source_match,
                order_match=order_match,
                identity_match=identity_match,
                reason=conflict_reason,
                now=now,
            )
            continue

        existing = source_match or order_match
        if existing is None:
            existing = next(
                (
                    candidate
                    for candidate in (identity_match, canonical_match, lead_key_match)
                    if candidate is not None and _master_order_is_compatible(candidate, order_id)
                ),
                None,
            )
        resolution = _resolve_status(
            raw_clue,
            raw_orders.get(order_id or ""),
            verified_at_by_order.get(order_id or ""),
            now,
            coupon_statuses_by_order.get(order_id or "", ()),
        )
        anchor = _resolve_anchor(raw_clue, mappings_by_poi, stores_by_id)
        lifecycle_status = _lifecycle_status(resolution.normalized_status)

        observed_at = _observed_at(raw_clue, now)
        if existing is None:
            lead_key = _lead_key(source_identity_key)
            existing = ClueMasterLead(
                lead_key=lead_key,
                source_clue_row_key=raw_clue.clue_row_key,
                source_identity_key=source_identity_key,
                created_at=now,
            )
            session.add(existing)
            existing_by_lead_key[lead_key] = existing
            status_changed = True
        else:
            status_changed = (
                existing.raw_order_status != resolution.raw_status
                or existing.normalized_order_status != resolution.normalized_status
                or existing.status_source != resolution.status_source
            )

        current_self_owned_round = _active_self_owned_current_round(
            session,
            existing,
            current_rounds_by_id=current_rounds_by_id,
        )
        active_headquarters_entry = existing.lead_key in active_headquarters_entries_by_lead
        if lifecycle_status in {"closed_verified", "closed_refunded", "closed_order"}:
            pool_location = "closed"
            allocation_state = "closed"
        elif lifecycle_status == "status_review":
            pool_location = "status_review"
            allocation_state = "status_review"
        elif current_self_owned_round is not None:
            pool_location = "store_follow_up_pool"
            allocation_state = "assigned"
        elif active_headquarters_entry or existing.pool_location == "headquarters_pool":
            # Re-entry to a store pool must be an explicit future operation.
            pool_location = "headquarters_pool"
            allocation_state = "headquarters"
        elif anchor.unavailable_reason:
            pool_location = "headquarters_pool"
            allocation_state = "headquarters"
        else:
            # M2 creates the first self-owned store assignment. This is not a business pool yet.
            pool_location = None
            allocation_state = "pending_allocation"

        existing.source_identity_key = source_identity_key
        existing.canonical_clue_id = canonical_clue_id or existing.canonical_clue_id
        existing.order_id = order_id
        existing.raw_order_status = resolution.raw_status
        existing.normalized_order_status = resolution.normalized_status
        existing.status_source = resolution.status_source
        existing.lifecycle_status = lifecycle_status
        existing.pool_location = pool_location
        existing.allocation_state = allocation_state
        existing.ended_without_assignment = (
            lifecycle_status in {"closed_verified", "closed_refunded", "closed_order"}
            and existing.current_assignment_round_id is None
            and existing.allocation_cycle_id is None
        )
        existing.closed_at = resolution.closed_at if lifecycle_status != "active" else None
        existing.closed_reason = _closed_reason(resolution.normalized_status)
        existing.first_seen_at = existing.first_seen_at or _first_seen_at(raw_clue, now)
        existing.last_seen_at = observed_at
        existing.anchor_poi_id = anchor.poi_id
        existing.anchor_store_id = anchor.store_id
        existing.anchor_source = "douyin_follow_poi" if anchor.poi_id else None
        existing.anchor_unavailable_reason = anchor.unavailable_reason
        existing.anchor_province = anchor.province
        existing.anchor_city = anchor.city
        existing.anchor_city_code = anchor.city_code
        existing.anchor_longitude = anchor.longitude
        existing.anchor_latitude = anchor.latitude
        existing.updated_at = now

        materialized_lead_keys.add(existing.lead_key)
        existing_by_source_clue_row_key[raw_clue.clue_row_key] = existing
        if order_id:
            existing_by_order_id.setdefault(order_id, existing)
        existing_by_identity[source_identity_key] = existing
        if canonical_clue_id:
            existing_by_canonical_clue_id[canonical_clue_id] = existing
        payload_hash = _source_payload_hash(raw_clue.raw_payload)
        _set_current_source_identifier(
            session,
            lead_key=existing.lead_key,
            source_clue_row_key=raw_clue.clue_row_key,
            identifier_type="clue_id",
            identifier_value=canonical_clue_id,
            source_payload_hash=payload_hash,
            observed_at=observed_at,
            now=now,
            history_by_key=identifier_history_by_key,
            current_by_source_type=current_identifier_history_by_source_type,
        )
        _set_current_source_identifier(
            session,
            lead_key=existing.lead_key,
            source_clue_row_key=raw_clue.clue_row_key,
            identifier_type="source_identity_key",
            identifier_value=source_identity_key,
            source_payload_hash=payload_hash,
            observed_at=observed_at,
            now=now,
            history_by_key=identifier_history_by_key,
            current_by_source_type=current_identifier_history_by_source_type,
        )
        if lifecycle_status in {"closed_verified", "closed_refunded", "closed_order"}:
            closed_lead_keys.add(existing.lead_key)
        elif pool_location == "headquarters_pool":
            headquarters_pool_keys.add(existing.lead_key)

        if status_changed:
            _record_status_event(
                session,
                lead_key=existing.lead_key,
                order_id=existing.order_id,
                resolution=resolution,
                observed_at=observed_at,
                created_at=now,
                known_event_ids=status_event_ids,
            )
        if anchor.unavailable_reason:
            _record_anchor_quality_issue(session, existing.lead_key, anchor, now, anchor_issue_ids)
    session.flush()
    for lead_key in materialized_lead_keys:
        lead = existing_by_lead_key[lead_key]
        if lead.lifecycle_status == "active" and lead.pool_location == "headquarters_pool":
            ensure_active_headquarters_pool_entry(
                session,
                lead=lead,
                reason=lead.anchor_unavailable_reason or "headquarters_pool_retained",
                entered_at=now,
                _active_entries_by_lead=active_headquarters_entries_by_lead,
                _flush=False,
            )
        elif lead.lifecycle_status != "active" and lead.order_id:
            close_current_headquarters_pool_entry(
                session,
                lead.lead_key,
                closed_at=lead.closed_at or now,
                close_reason=lead.closed_reason or "order_closed",
                _active_entries_by_lead=active_headquarters_entries_by_lead,
            )
            _close_current_assignment(
                session,
                lead.order_id,
                lead.lifecycle_status,
                lead.closed_at or now,
                current_assignment_round_id=lead.current_assignment_round_id,
                center_orders_by_id=center_orders_by_id,
                current_rounds_by_id=current_rounds_by_id,
            )

    session.flush()
    return {
        "master_leads": len(materialized_lead_keys),
        "closed_leads": len(closed_lead_keys),
        "headquarters_pool": len(headquarters_pool_keys),
    }


def refresh_unknown_clue_master_statuses(
    session: Session,
    *,
    now: datetime | None = None,
    batch_size: int = 500,
    dry_run: bool = False,
) -> dict[str, int | bool | str]:
    """Refresh unresolved master statuses without loading the full clue ledger.

    This path is intentionally limited to existing ``unknown`` rows. It uses a
    session advisory lock and commits each keyset page independently so status
    repair cannot recreate the full materialization memory peak.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    now = _aware(now or utcnow())
    lock_key = _advisory_lock_key(MASTER_STATUS_REPAIR_LOCK)
    if not _try_session_advisory_lock(session, lock_key):
        return {"scanned": 0, "updated": 0, "resolved": 0, "status_review": 0, "batches": 0, "dry_run": dry_run, "skipped": "locked"}

    stats: dict[str, int | bool | str] = {
        "scanned": 0,
        "updated": 0,
        "resolved": 0,
        "status_review": 0,
        "batches": 0,
        "dry_run": dry_run,
    }
    last_lead_key = ""
    try:
        while True:
            leads = session.scalars(
                select(ClueMasterLead)
                .where(ClueMasterLead.normalized_order_status == "unknown")
                .where(ClueMasterLead.lead_key > last_lead_key)
                .order_by(ClueMasterLead.lead_key)
                .limit(batch_size)
            ).all()
            if not leads:
                break

            last_lead_key = leads[-1].lead_key
            stats["batches"] = int(stats["batches"]) + 1
            stats["scanned"] = int(stats["scanned"]) + len(leads)
            source_keys = {lead.source_clue_row_key for lead in leads}
            order_ids = {_clean(lead.order_id) for lead in leads}
            order_ids.discard(None)
            raw_clues = {
                row.clue_row_key: row
                for row in session.scalars(
                    select(RawDouyinClue).where(RawDouyinClue.clue_row_key.in_(source_keys))
                ).all()
            }
            raw_orders = _raw_orders_by_id(session, order_ids)
            coupon_statuses_by_order = _coupon_statuses_by_order(session, order_ids)
            verified_at_by_order = _verified_at_by_order(session, order_ids)
            event_ids = set(
                session.scalars(
                    select(ClueOrderStatusEvent.event_id).where(
                        ClueOrderStatusEvent.lead_key.in_({lead.lead_key for lead in leads})
                    )
                ).all()
            )

            for lead in leads:
                raw_clue = raw_clues.get(lead.source_clue_row_key)
                if raw_clue is None:
                    stats["status_review"] = int(stats["status_review"]) + 1
                    continue
                order_id = _clean(lead.order_id)
                resolution = _resolve_status(
                    raw_clue,
                    raw_orders.get(order_id or ""),
                    verified_at_by_order.get(order_id or ""),
                    now,
                    coupon_statuses_by_order.get(order_id or "", ()),
                )
                lifecycle_status = _lifecycle_status(resolution.normalized_status)
                previous_state = (
                    lead.raw_order_status,
                    lead.normalized_order_status,
                    lead.status_source,
                    lead.lifecycle_status,
                    lead.pool_location,
                    lead.allocation_state,
                )
                if lifecycle_status in {"closed_verified", "closed_refunded", "closed_order"}:
                    pool_location = "closed"
                    allocation_state = "closed"
                elif lifecycle_status == "status_review":
                    pool_location = "status_review"
                    allocation_state = "status_review"
                elif lead.pool_location == "headquarters_pool":
                    pool_location = "headquarters_pool"
                    allocation_state = "headquarters"
                else:
                    current_round = _active_self_owned_current_round(session, lead)
                    pool_location = "store_follow_up_pool" if current_round else None
                    allocation_state = "assigned" if current_round else "pending_allocation"

                next_state = (
                    resolution.raw_status,
                    resolution.normalized_status,
                    resolution.status_source,
                    lifecycle_status,
                    pool_location,
                    allocation_state,
                )
                if next_state != previous_state:
                    stats["updated"] = int(stats["updated"]) + 1
                    if resolution.normalized_status == "unknown":
                        stats["status_review"] = int(stats["status_review"]) + 1
                    else:
                        stats["resolved"] = int(stats["resolved"]) + 1
                if dry_run or next_state == previous_state:
                    continue

                lead.raw_order_status = resolution.raw_status
                lead.normalized_order_status = resolution.normalized_status
                lead.status_source = resolution.status_source
                lead.lifecycle_status = lifecycle_status
                lead.pool_location = pool_location
                lead.allocation_state = allocation_state
                lead.ended_without_assignment = (
                    lifecycle_status in {"closed_verified", "closed_refunded", "closed_order"}
                    and lead.current_assignment_round_id is None
                    and lead.allocation_cycle_id is None
                )
                lead.closed_at = resolution.closed_at if lifecycle_status != "active" else None
                lead.closed_reason = _closed_reason(resolution.normalized_status)
                lead.updated_at = now
                if lifecycle_status != "active":
                    close_at = resolution.closed_at or now
                    close_current_headquarters_pool_entry(
                        session,
                        lead.lead_key,
                        closed_at=close_at,
                        close_reason=lead.closed_reason or "order_status_unknown",
                    )
                    _close_current_assignment(
                        session,
                        order_id or "",
                        lifecycle_status,
                        close_at,
                        current_assignment_round_id=lead.current_assignment_round_id,
                    )
                if resolution.normalized_status != "unknown" or previous_state[3] != lifecycle_status:
                    _record_status_event(
                        session,
                        lead_key=lead.lead_key,
                        order_id=order_id,
                        resolution=resolution,
                        observed_at=_observed_at(raw_clue, now),
                        created_at=now,
                        known_event_ids=event_ids,
                    )

            if not dry_run:
                session.flush()
                session.commit()
                session.expunge_all()
    finally:
        _release_session_advisory_lock(session, lock_key)
    return stats


def synchronize_non_active_clue_states(
    session: Session,
    *,
    now: datetime | None = None,
    batch_size: int = 500,
    dry_run: bool = False,
) -> dict[str, int | bool | str]:
    """Close stale center snapshots and rounds for terminal master leads.

    This is deliberately separate from full materialization. It scans the
    non-active master ledger in keyset pages, closes only already-existing
    rounds, and never creates a new assignment.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    now = _aware(now or utcnow())
    lock_key = _advisory_lock_key(MASTER_TERMINAL_SYNC_LOCK)
    if not _try_session_advisory_lock(session, lock_key):
        return {
            "scanned": 0,
            "orders": 0,
            "rounds_closed": 0,
            "centers_closed": 0,
            "headquarters_closed": 0,
            "batches": 0,
            "dry_run": dry_run,
            "skipped": "locked",
        }

    stats: dict[str, int | bool | str] = {
        "scanned": 0,
        "orders": 0,
        "rounds_closed": 0,
        "centers_closed": 0,
        "headquarters_closed": 0,
        "batches": 0,
        "dry_run": dry_run,
    }
    last_lead_key = ""
    active_round_statuses = ("active_unfollowed", "active_followed")
    try:
        while True:
            leads = session.scalars(
                select(ClueMasterLead)
                .where(ClueMasterLead.lifecycle_status != "active")
                .where(ClueMasterLead.lead_key > last_lead_key)
                .order_by(ClueMasterLead.lead_key)
                .limit(batch_size)
            ).all()
            if not leads:
                break

            last_lead_key = leads[-1].lead_key
            stats["batches"] = int(stats["batches"]) + 1
            stats["scanned"] = int(stats["scanned"]) + len(leads)
            lead_keys = {lead.lead_key for lead in leads}
            leads_by_order: dict[str, list[ClueMasterLead]] = defaultdict(list)
            for lead in leads:
                if order_id := _clean(lead.order_id):
                    leads_by_order[order_id].append(lead)

            order_ids = set(leads_by_order)
            centers = {
                row.order_id: row
                for row in session.scalars(
                    select(ClueCenterOrder).where(ClueCenterOrder.order_id.in_(order_ids))
                ).all()
            }
            rounds_by_order: dict[str, list[ClueAssignmentRound]] = defaultdict(list)
            if order_ids:
                for round_row in session.scalars(
                    select(ClueAssignmentRound)
                    .where(ClueAssignmentRound.order_id.in_(order_ids))
                    .where(ClueAssignmentRound.round_status.in_(active_round_statuses))
                ).all():
                    rounds_by_order[round_row.order_id].append(round_row)
            active_hq_by_lead = {
                row.lead_key: row
                for row in session.scalars(
                    select(ClueHeadquartersPoolEntry)
                    .where(ClueHeadquartersPoolEntry.lead_key.in_(lead_keys))
                    .where(ClueHeadquartersPoolEntry.status == "active")
                ).all()
            }

            for lead in leads:
                if lead.lead_key not in active_hq_by_lead:
                    continue
                stats["headquarters_closed"] = int(stats["headquarters_closed"]) + 1
                if not dry_run:
                    close_current_headquarters_pool_entry(
                        session,
                        lead.lead_key,
                        closed_at=_aware(lead.closed_at) if lead.closed_at else now,
                        close_reason=lead.closed_reason or "order_status_terminal",
                        _active_entries_by_lead=active_hq_by_lead,
                    )

            for order_id, order_leads in leads_by_order.items():
                lifecycle_status = _terminal_lifecycle_for_order(order_leads)
                closed_at = _terminal_closed_at(order_leads, now)
                order_rounds = rounds_by_order.get(order_id, [])
                stats["orders"] = int(stats["orders"]) + 1
                stats["rounds_closed"] = int(stats["rounds_closed"]) + len(order_rounds)
                center = centers.get(order_id)
                center_needs_update = center is not None and (
                    center.lead_status
                    != _terminal_center_lead_status(lifecycle_status)
                    or center.current_round_status
                    != _terminal_round_status(lifecycle_status)
                )
                if center_needs_update:
                    stats["centers_closed"] = int(stats["centers_closed"]) + 1

                if dry_run:
                    continue
                for round_row in order_rounds:
                    _close_current_assignment(
                        session,
                        order_id,
                        lifecycle_status,
                        closed_at,
                        current_assignment_round_id=round_row.assignment_round_id,
                    )
                if center_needs_update:
                    _close_current_assignment(
                        session,
                        order_id,
                        lifecycle_status,
                        closed_at,
                    )

            if not dry_run:
                session.flush()
                session.commit()
            session.expunge_all()
    finally:
        _release_session_advisory_lock(session, lock_key)
    return stats


def import_store_locations(
    session: Session,
    workbook_path: Path,
    *,
    enable_participation: bool = False,
    now: datetime | None = None,
) -> dict[str, int]:
    """Load the business location workbook through POI mappings, never by assuming POI equals store id."""
    now = _aware(now or utcnow())
    workbook = load_workbook(workbook_path, read_only=True, data_only=True, keep_links=False)
    sheet = workbook.active
    rows = sheet.iter_rows(values_only=True)
    header = next(rows, None)
    if header is None:
        raise ValueError("store location workbook has no header row")
    columns = {_clean_header(value): index for index, value in enumerate(header) if _clean_header(value)}
    required = {"门店ID", "经度", "纬度", "门店所在城市"}
    missing = sorted(required.difference(columns))
    if missing:
        raise ValueError(f"store location workbook missing required columns: {', '.join(missing)}")

    mappings_by_poi = {row.poi_id: row for row in session.scalars(select(DimStorePoiMapping)).all()}
    rows_seen = 0
    updated = 0
    unmapped = 0
    invalid = 0
    imported_stores_by_poi: dict[str, DimStore] = {}
    for row in rows:
        if not row:
            continue
        poi_id = _text_cell(_cell(row, columns, "门店ID"))
        if not poi_id:
            continue
        rows_seen += 1
        mapping = mappings_by_poi.get(poi_id)
        if mapping is None:
            unmapped += 1
            _record_store_location_issue(session, poi_id, "store_location_unmapped_poi", now)
            continue
        store = session.get(DimStore, mapping.store_id)
        if store is None:
            unmapped += 1
            _record_store_location_issue(session, poi_id, "store_location_missing_store", now)
            continue

        longitude = _decimal(_cell(row, columns, "经度"))
        latitude = _decimal(_cell(row, columns, "纬度"))
        province = _text_cell(_cell(row, columns, "门店所在省份")) or _text_cell(_cell(row, columns, "省份"))
        city = _text_cell(_cell(row, columns, "门店所在城市"))
        city_code = normalize_city_code(city)
        status_note = _text_cell(_cell(row, columns, "状态备注"))
        has_coordinates_and_city = _valid_coordinates(latitude, longitude) and bool(city_code)
        if not has_coordinates_and_city:
            invalid += 1
            _record_store_location_issue(session, poi_id, "store_location_invalid_coordinates_or_city", now)

        store.standard_province = province or _clean(store.standard_province)
        store.standard_city = city or _clean(store.standard_city)
        store.city_code = city_code
        store.longitude = longitude if _valid_coordinates(latitude, longitude) else None
        store.latitude = latitude if _valid_coordinates(latitude, longitude) else None
        store.location_source = workbook_path.name
        store.location_status_note = status_note
        store.location_updated_at = now
        imported_stores_by_poi[poi_id] = store
        updated += 1

    stores_by_id = {store.store_id: store for store in imported_stores_by_poi.values()}
    _enrich_store_locations_from_raw_evidence(
        session,
        session.scalars(select(RawDouyinClue)).all(),
        mappings_by_poi,
        stores_by_id,
        now,
    )
    for poi_id, store in imported_stores_by_poi.items():
        store.location_status = _store_location_status(store)
        if store.location_status == "valid":
            store.is_douyin_clue_applicable = True
            store.participates_in_clue_allocation = bool(enable_participation or store.participates_in_clue_allocation)
        else:
            store.is_douyin_clue_applicable = False
            store.participates_in_clue_allocation = False
            if store.location_status == "partial":
                _record_store_location_issue(session, poi_id, "store_location_missing_province", now)

    session.flush()
    return {"rows": rows_seen, "updated": updated, "unmapped": unmapped, "invalid": invalid}


def _enrich_store_locations_from_raw_evidence(
    session: Session,
    raw_clues: list[RawDouyinClue],
    mappings_by_poi: dict[str, DimStorePoiMapping],
    stores_by_id: dict[str, DimStore],
    now: datetime,
) -> None:
    """Fill missing store geography from unambiguous raw clue evidence."""
    evidence_by_poi: dict[str, set[tuple[str, str]]] = defaultdict(set)
    provinces_by_city_code: dict[str, set[str]] = defaultdict(set)
    for raw_clue in raw_clues:
        poi_id = _clean(raw_clue.follow_poi_id)
        province = _clean(raw_clue.auto_province_name)
        city = _clean(raw_clue.auto_city_name)
        if poi_id and province and city:
            evidence_by_poi[poi_id].add((province, city))
        city_code = normalize_city_code(city)
        if province and city_code:
            provinces_by_city_code[city_code].add(province)

    for poi_id, candidates in evidence_by_poi.items():
        mapping = mappings_by_poi.get(poi_id)
        store = stores_by_id.get(mapping.store_id) if mapping else None
        if store is None:
            continue
        if len(candidates) != 1:
            _record_store_location_issue(session, poi_id, "store_location_conflicting_raw_evidence", now)
            continue
        province, city = next(iter(candidates))
        city_code = normalize_city_code(city)
        existing_city_code = normalize_city_code(store.standard_city) or _clean(store.city_code)
        if existing_city_code and city_code and existing_city_code != city_code:
            _record_store_location_issue(session, poi_id, "store_location_raw_city_mismatch", now)
            continue
        changed = False
        if not _clean(store.standard_city):
            store.standard_city = city
            changed = True
        if not _clean(store.city_code) and city_code:
            store.city_code = city_code
            changed = True
        if not _clean(store.standard_province):
            store.standard_province = province
            changed = True
        location_status = _store_location_status(store)
        if store.location_status != location_status:
            store.location_status = location_status
            changed = True
        if location_status == "valid" and not store.is_douyin_clue_applicable:
            store.is_douyin_clue_applicable = True
            changed = True
        if location_status != "valid" and store.is_douyin_clue_applicable:
            store.is_douyin_clue_applicable = False
            store.participates_in_clue_allocation = False
            changed = True
        if changed:
            store.location_updated_at = now

    province_by_city_code = {
        city_code: next(iter(provinces))
        for city_code, provinces in provinces_by_city_code.items()
        if len(provinces) == 1
    }
    for store in stores_by_id.values():
        if _clean(store.standard_province):
            continue
        city_code = normalize_city_code(store.standard_city) or normalize_city_code(store.city_code)
        province = province_by_city_code.get(city_code or "")
        if not province:
            continue
        store.standard_province = province
        location_status = _store_location_status(store)
        store.location_status = location_status
        store.is_douyin_clue_applicable = location_status == "valid"
        if location_status != "valid":
            store.participates_in_clue_allocation = False
        store.location_updated_at = now


def normalize_city_code(value: str | None) -> str | None:
    """Return the M1 canonical city key; it is not a government administrative code."""
    city = _clean(value)
    if not city:
        return None
    city = "".join(city.split())
    return city[:-1] if city.endswith("市") else city


def eligible_candidate_stores(session: Session, *, city_code: str | None = None) -> list[DimStore]:
    rows = session.scalars(select(DimStore).order_by(DimStore.store_id)).all()
    normalized_city = normalize_city_code(city_code)
    return [
        row
        for row in rows
        if _is_candidate_eligible(row)
        and (normalized_city is None or row.city_code == normalized_city)
    ]


def haversine_km(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    """Return the great-circle distance between two coordinates in kilometres."""
    earth_radius_km = 6371.0088
    latitude_delta = radians(float(latitude_b) - float(latitude_a))
    longitude_delta = radians(float(longitude_b) - float(longitude_a))
    latitude_a_radians = radians(float(latitude_a))
    latitude_b_radians = radians(float(latitude_b))
    haversine = sin(latitude_delta / 2) ** 2 + cos(latitude_a_radians) * cos(latitude_b_radians) * sin(
        longitude_delta / 2
    ) ** 2
    return earth_radius_km * 2 * asin(sqrt(haversine))


def refresh_store_score_snapshots(
    session: Session,
    *,
    rule_version_id: str,
    now: datetime | None = None,
    run_mode: str = "scheduled",
    triggered_by: str | None = None,
    _scheduled_lock_acquired: bool = False,
) -> dict[str, object]:
    """Create an immutable score run for eligible stores using only formal, mature rounds.

    A version-bound run takes every scoring setting from that immutable rule
    version. The unbound configuration remains only for legacy/manual callers;
    allocation never selects those snapshots for a bound lead.
    """
    now = _aware(now or utcnow())
    score_config = _resolve_store_score_config(
        session,
        rule_version_id=rule_version_id,
    )

    snapshot_date = now.astimezone(SHANGHAI).date()
    scheduled_key: str | None = None
    if run_mode == "scheduled":
        if not _scheduled_lock_acquired and not _try_transaction_lock(session, lock_name=SCHEDULED_SCORE_REFRESH_LOCK):
            return {"snapshot_run_id": None, "snapshots": 0, "skipped": "locked"}
        scheduled_key = _scheduled_score_refresh_key(snapshot_date, score_config.rule_version_id)
        existing = session.scalar(
            select(StoreScoreSnapshotRun.snapshot_run_id)
            .where(StoreScoreSnapshotRun.scheduled_key == scheduled_key)
            .limit(1)
        )
        if existing:
            return {"snapshot_run_id": None, "snapshots": 0, "skipped": "already_refreshed"}

    snapshot_run_id = f"score-{now.strftime('%Y%m%dT%H%M%S%f')}-{uuid4().hex[:8]}"
    window_end = now
    window_start = now - timedelta(days=score_config.lookback_days)
    stores = eligible_candidate_stores(session)
    score_config_json = {
        "rule_version_id": score_config.rule_version_id,
        "lookback_days": score_config.lookback_days,
        "min_samples": score_config.min_samples,
        "execution_mode": "formal",
        "conversion_weight": str(score_config.conversion_weight),
        "follow_24h_weight": str(score_config.follow_weight),
        "store_weight": str(score_config.store_weight),
    }
    session.add(
        StoreScoreSnapshotRun(
            snapshot_run_id=snapshot_run_id,
            snapshot_date=snapshot_date,
            run_mode=run_mode,
            scheduled_key=scheduled_key,
            window_start=window_start,
            window_end=window_end,
            candidate_store_count=len(stores),
            snapshot_count=len(stores),
            triggered_by=_clean(triggered_by),
            config_json=score_config_json,
            computed_at=now,
        )
    )
    session.flush()
    if not stores:
        return {"snapshot_run_id": snapshot_run_id, "snapshots": 0}

    metrics_by_store = _formal_store_metrics(session, stores, window_start, window_end)
    city_metrics = _aggregate_city_metrics(stores, metrics_by_store)
    global_metrics = _sum_metrics(metrics_by_store.values())
    for store in stores:
        own_metrics = metrics_by_store.get(store.store_id, StoreMetrics())
        city_metric = city_metrics.get(store.city_code or "", StoreMetrics())
        conversion_rate, conversion_source = _resolved_rate(
            own_metrics.conversion_numerator,
            own_metrics.conversion_denominator,
            city_metric.conversion_numerator,
            city_metric.conversion_denominator,
            global_metrics.conversion_numerator,
            global_metrics.conversion_denominator,
            score_config.min_samples,
        )
        follow_rate, follow_source = _resolved_rate(
            own_metrics.follow_24h_numerator,
            own_metrics.follow_24h_denominator,
            city_metric.follow_24h_numerator,
            city_metric.follow_24h_denominator,
            global_metrics.follow_24h_numerator,
            global_metrics.follow_24h_denominator,
            score_config.min_samples,
        )
        score = (conversion_rate * score_config.conversion_weight + follow_rate * score_config.follow_weight) * score_config.store_weight
        session.add(
            StoreScoreSnapshot(
                snapshot_id=f"{snapshot_run_id}-{store.store_id}",
                snapshot_run_id=snapshot_run_id,
                snapshot_date=snapshot_date,
                run_mode=run_mode,
                store_id=store.store_id,
                city_code=store.city_code,
                window_start=window_start,
                window_end=window_end,
                conversion_numerator=own_metrics.conversion_numerator,
                conversion_denominator=own_metrics.conversion_denominator,
                conversion_rate=conversion_rate,
                conversion_value_source=conversion_source,
                follow_24h_numerator=own_metrics.follow_24h_numerator,
                follow_24h_denominator=own_metrics.follow_24h_denominator,
                follow_24h_rate=follow_rate,
                follow_24h_value_source=follow_source,
                conversion_weight=score_config.conversion_weight,
                follow_24h_weight=score_config.follow_weight,
                store_weight=score_config.store_weight,
                composite_score=score,
                config_json=score_config_json,
                computed_at=now,
            )
        )
    session.flush()
    return {"snapshot_run_id": snapshot_run_id, "snapshots": len(stores)}


def refresh_due_store_score_snapshots(
    session: Session,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """Run at most one scheduled score refresh per Shanghai calendar day after 03:00."""
    now = _aware(now or utcnow())
    local_now = now.astimezone(SHANGHAI)
    if local_now.time() < SCHEDULED_SCORE_REFRESH_TIME:
        return {"snapshot_run_id": None, "snapshots": 0, "skipped": "before_schedule"}
    if not _try_transaction_lock(session, lock_name=SCHEDULED_SCORE_REFRESH_LOCK):
        return {"snapshot_run_id": None, "snapshots": 0, "skipped": "locked"}

    rule_version_ids = _score_rule_version_ids_for_refresh(session)
    if not rule_version_ids:
        return {"snapshot_run_id": None, "snapshots": 0, "skipped": "no_rule_versions"}

    results = [
        refresh_store_score_snapshots(
            session,
            now=now,
            run_mode="scheduled",
            rule_version_id=rule_version_id,
            _scheduled_lock_acquired=True,
        )
        for rule_version_id in rule_version_ids
    ]
    snapshot_run_ids = [str(result["snapshot_run_id"]) for result in results if result.get("snapshot_run_id")]
    if not snapshot_run_ids:
        return {"snapshot_run_id": None, "snapshots": 0, "skipped": "already_refreshed"}
    return {
        "snapshot_run_id": snapshot_run_ids[0],
        "snapshot_run_ids": snapshot_run_ids,
        "snapshots": sum(int(result.get("snapshots", 0) or 0) for result in results),
    }


def _resolve_store_score_config(
    session: Session,
    *,
    rule_version_id: str,
) -> StoreScoreConfig:
    normalized_rule_version_id = rule_version_id.strip() if isinstance(rule_version_id, str) else ""
    if not normalized_rule_version_id:
        raise ValueError("rule_version_id is required")
    version = session.get(ClueAllocationRuleVersion, normalized_rule_version_id)
    if version is None:
        raise ValueError("clue allocation rule version was not found")
    if (
        version.lookback_days is None
        or version.min_samples is None
        or version.conversion_weight is None
        or version.follow_24h_weight is None
    ):
        raise ValueError("clue allocation rule version is missing score configuration")
    return _validated_store_score_config(
        rule_version_id=version.rule_version_id,
        min_samples=version.min_samples,
        lookback_days=version.lookback_days,
        conversion_weight=version.conversion_weight,
        follow_weight=version.follow_24h_weight,
        store_weight=DEFAULT_STORE_WEIGHT,
    )


def _validated_store_score_config(
    *,
    rule_version_id: str | None,
    min_samples: int,
    lookback_days: int,
    conversion_weight: Decimal,
    follow_weight: Decimal,
    store_weight: Decimal,
) -> StoreScoreConfig:
    if min_samples <= 0:
        raise ValueError("min_samples must be positive")
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    conversion = Decimal(str(conversion_weight))
    follow = Decimal(str(follow_weight))
    if conversion + follow != Decimal("1"):
        raise ValueError("conversion_weight and follow_weight must add up to 1")
    return StoreScoreConfig(
        rule_version_id=rule_version_id,
        min_samples=min_samples,
        lookback_days=lookback_days,
        conversion_weight=conversion,
        follow_weight=follow,
        store_weight=Decimal(str(store_weight)),
    )


def _score_rule_version_ids_for_refresh(session: Session) -> list[str]:
    published_version_ids = session.scalars(
        select(ClueAllocationRuleVersion.rule_version_id)
        .where(ClueAllocationRuleVersion.status == "published")
        .order_by(ClueAllocationRuleVersion.rule_version_id)
    ).all()
    bound_version_ids = session.scalars(
        select(ClueLeadRuleVersionBinding.rule_version_id)
        .join(ClueMasterLead, ClueMasterLead.lead_key == ClueLeadRuleVersionBinding.lead_key)
        .where(ClueMasterLead.lifecycle_status == "active")
        .where(ClueMasterLead.normalized_order_status == "active")
        .order_by(ClueLeadRuleVersionBinding.rule_version_id)
    ).all()
    return sorted(set(published_version_ids).union(bound_version_ids))


def _scheduled_score_refresh_key(snapshot_date: date, rule_version_id: str | None) -> str:
    target = rule_version_id or "legacy"
    return f"scheduled-{snapshot_date.isoformat()}-{target}"


def _master_order_is_compatible(master: ClueMasterLead, order_id: str | None) -> bool:
    master_order_id = _clean(master.order_id)
    return not order_id or not master_order_id or master_order_id == order_id


def _master_match_conflict_reason(
    *,
    source_match: ClueMasterLead | None,
    order_match: ClueMasterLead | None,
    identity_match: ClueMasterLead | None,
    order_id: str | None,
) -> str | None:
    if source_match is not None and not _master_order_is_compatible(source_match, order_id):
        return "source_record_order_changed"
    if source_match is not None and order_match is not None and source_match is not order_match:
        return "source_record_and_order_resolve_to_different_leads"
    selected = source_match or order_match
    if selected is not None and identity_match is not None and selected is not identity_match:
        return "source_identity_already_bound_to_another_lead"
    if identity_match is not None and not _master_order_is_compatible(identity_match, order_id):
        return "source_identity_order_conflict"
    return None


def _record_identity_mapping_conflict(
    session: Session,
    *,
    raw_clue: RawDouyinClue,
    source_match: ClueMasterLead | None,
    order_match: ClueMasterLead | None,
    identity_match: ClueMasterLead | None,
    reason: str,
    now: datetime,
) -> None:
    source = "|".join(
        [
            raw_clue.clue_row_key,
            _clean(raw_clue.order_id) or "",
            source_match.lead_key if source_match else "",
            order_match.lead_key if order_match else "",
            identity_match.lead_key if identity_match else "",
            reason,
        ]
    )
    issue_id = f"clue-identity-conflict:{sha256(source.encode('utf-8')).hexdigest()[:32]}"
    upsert_data_quality_issue(
        session,
        issue_id,
        issue_type="clue_identity_conflict",
        message="clue source identifiers resolve to conflicting master leads",
        order_id=_clean(raw_clue.order_id),
        severity="error",
        raw_context_json={
            "source_clue_row_key": raw_clue.clue_row_key,
            "canonical_clue_id": _clean(raw_clue.clue_id),
            "source_lead_key": source_match.lead_key if source_match else None,
            "source_order_id": _clean(source_match.order_id) if source_match else None,
            "order_lead_key": order_match.lead_key if order_match else None,
            "identity_lead_key": identity_match.lead_key if identity_match else None,
            "reason": reason,
            "observed_at": now.isoformat(),
        },
        source_run_id=None,
        flush=False,
    )


def _source_payload_hash(raw_payload: dict[str, object] | None) -> str:
    serialized = json.dumps(
        raw_payload or {},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def _source_identifier_history_id(
    source_clue_row_key: str,
    identifier_type: str,
    identifier_value: str,
) -> str:
    source = f"{source_clue_row_key}|{identifier_type}|{identifier_value}"
    return f"clue-identifier-{sha256(source.encode('utf-8')).hexdigest()[:32]}"


def _set_current_source_identifier(
    session: Session,
    *,
    lead_key: str,
    source_clue_row_key: str,
    identifier_type: str,
    identifier_value: str | None,
    source_payload_hash: str,
    observed_at: datetime,
    now: datetime,
    history_by_key: dict[tuple[str, str, str], ClueSourceIdentifierHistory],
    current_by_source_type: dict[tuple[str, str], list[ClueSourceIdentifierHistory]],
) -> None:
    source_type_key = (source_clue_row_key, identifier_type)
    for current in current_by_source_type.get(source_type_key, []):
        if current.identifier_value != identifier_value:
            current.is_current = False
            current.updated_at = now

    if identifier_value is None:
        current_by_source_type[source_type_key] = []
        return

    history_key = (source_clue_row_key, identifier_type, identifier_value)
    history = history_by_key.get(history_key)
    if history is None:
        history = ClueSourceIdentifierHistory(
            identifier_history_id=_source_identifier_history_id(
                source_clue_row_key,
                identifier_type,
                identifier_value,
            ),
            lead_key=lead_key,
            source_clue_row_key=source_clue_row_key,
            identifier_type=identifier_type,
            identifier_value=identifier_value,
            source_payload_hash=source_payload_hash,
            first_seen_at=observed_at,
            last_seen_at=observed_at,
            is_current=True,
            created_at=now,
            updated_at=now,
        )
        session.add(history)
        history_by_key[history_key] = history
    else:
        if history.lead_key != lead_key:
            raise ValueError("source identifier history is already linked to another lead")
        history.source_payload_hash = source_payload_hash
        history.last_seen_at = observed_at
        history.is_current = True
        history.updated_at = now
    current_by_source_type[source_type_key] = [history]


def _source_identity_key(raw_clue: RawDouyinClue) -> str:
    order_id = _clean(raw_clue.order_id)
    contact_value = _clean(raw_clue.telephone) or _clean(raw_clue.enc_telephone)
    canonical_clue_id = _clean(raw_clue.clue_id)
    if order_id and contact_value:
        source = f"order-contact|{order_id}|{contact_value}"
    elif canonical_clue_id:
        source = f"clue|{canonical_clue_id}"
    else:
        source = f"raw|{raw_clue.clue_row_key}"
    return f"identity-{sha256(source.encode('utf-8')).hexdigest()[:32]}"


def _lead_key(source_identity_key: str) -> str:
    return f"lead-{source_identity_key.removeprefix('identity-')}"


def _try_transaction_lock(session: Session, *, lock_name: str) -> bool:
    """Prevent parallel PostgreSQL workers from materializing the same M1 state."""
    if session.get_bind().dialect.name != "postgresql":
        return True
    lock_key = _advisory_lock_key(lock_name)
    return bool(session.scalar(select(func.pg_try_advisory_xact_lock(lock_key))))


def _advisory_lock_key(lock_name: str) -> int:
    return int.from_bytes(
        sha256(lock_name.encode("utf-8")).digest()[:8],
        byteorder="big",
        signed=True,
    )


def _try_session_advisory_lock(session: Session, lock_key: int) -> bool:
    if session.get_bind().dialect.name != "postgresql":
        return True
    return bool(session.scalar(select(func.pg_try_advisory_lock(lock_key))))


def _release_session_advisory_lock(session: Session, lock_key: int) -> None:
    if session.get_bind().dialect.name != "postgresql":
        return
    try:
        session.scalar(select(func.pg_advisory_unlock(lock_key)))
    except Exception:
        # The surrounding session scope will roll back a failed transaction.
        pass


def _raw_orders_by_id(session: Session, order_ids: set[str]) -> dict[str, RawDouyinOrder]:
    if not order_ids:
        return {}
    values: dict[str, RawDouyinOrder] = {}
    for order_id_batch in _materialization_order_id_batches(order_ids):
        rows = session.scalars(
            select(RawDouyinOrder).where(RawDouyinOrder.order_id.in_(order_id_batch))
        ).all()
        values.update({row.order_id: row for row in rows})
    return values


def _coupon_statuses_by_order(
    session: Session,
    order_ids: set[str],
) -> dict[str, list[str]]:
    if not order_ids:
        return {}
    values: dict[str, list[str]] = defaultdict(list)
    for order_id_batch in _materialization_order_id_batches(order_ids):
        rows = session.execute(
            select(
                RawDouyinOrderCoupon.order_id,
                RawDouyinOrderCoupon.coupon_status,
                RawDouyinOrderCoupon.coupon_status_raw,
                RawDouyinOrderCoupon.coupon_status_normalized,
            ).where(RawDouyinOrderCoupon.order_id.in_(order_id_batch))
        ).all()
        for order_id, coupon_status, coupon_status_raw, normalized in rows:
            if not order_id:
                continue
            values[order_id].append(
                _clean(normalized)
                or normalize_coupon_status(coupon_status_raw or coupon_status)
            )
    return values


def _verified_at_by_order(session: Session, order_ids: set[str]) -> dict[str, datetime]:
    if not order_ids:
        return {}
    values: dict[str, datetime] = {}
    for order_id_batch in _materialization_order_id_batches(order_ids):
        rows = session.execute(
            select(SettlementOrderDetail.order_id, SettlementOrderDetail.verify_time)
            .where(SettlementOrderDetail.order_id.in_(order_id_batch))
            .where(SettlementOrderDetail.is_verified.is_(True))
        ).all()
        for order_id, verify_time in rows:
            if not order_id:
                continue
            candidate = _aware(verify_time)
            if candidate is None:
                continue
            previous = values.get(order_id)
            if previous is None or candidate < previous:
                values[order_id] = candidate
    return values


def _materialization_order_id_batches(order_ids: set[str]) -> list[list[str]]:
    ordered_ids = sorted(order_id for order_id in order_ids if order_id)
    return [
        ordered_ids[offset : offset + MATERIALIZATION_QUERY_BATCH_SIZE]
        for offset in range(0, len(ordered_ids), MATERIALIZATION_QUERY_BATCH_SIZE)
    ]


def _resolve_status(
    raw_clue: RawDouyinClue,
    raw_order: RawDouyinOrder | None,
    verified_at: datetime | None,
    now: datetime,
    coupon_statuses: list[str] | tuple[str, ...] = (),
) -> StatusResolution:
    if verified_at is not None:
        return StatusResolution(
            raw_status=_clean(raw_order.order_status) if raw_order else _clean(raw_clue.order_status),
            normalized_status="verified",
            status_source="settlement_verification",
            closed_at=verified_at,
        )
    order_status = _clean(raw_order.order_status) if raw_order is not None else None
    source = "order" if order_status else "clue"
    raw_status = order_status or _clean(raw_clue.order_status)
    payload = raw_order.raw_payload if order_status and raw_order is not None else raw_clue.raw_payload
    normalized_status = resolve_clue_order_status(
        raw_status,
        payload,
        normalized_order_status=(raw_order.order_status_normalized if raw_order else None),
        coupon_statuses=coupon_statuses,
    )
    closed_at = (
        _status_observed_at(raw_clue, raw_order, now)
        if normalized_status in {"verified", "refunded", "closed"}
        else None
    )
    return StatusResolution(raw_status, normalized_status, source, closed_at)


def _resolve_anchor(
    raw_clue: RawDouyinClue,
    mappings_by_poi: dict[str, DimStorePoiMapping],
    stores_by_id: dict[str, DimStore],
) -> AnchorSnapshot:
    poi_id = _clean(raw_clue.follow_poi_id)
    if not poi_id:
        return AnchorSnapshot(None, None, "follow_poi_missing", None, None, None, None, None)
    mapping = mappings_by_poi.get(poi_id)
    if mapping is None:
        return AnchorSnapshot(poi_id, None, "follow_poi_unmapped", None, None, None, None, None)
    store = stores_by_id.get(mapping.store_id)
    if store is None:
        return AnchorSnapshot(poi_id, None, "follow_poi_store_missing", None, None, None, None, None)
    longitude = _decimal(store.longitude)
    latitude = _decimal(store.latitude)
    if not _valid_coordinates(latitude, longitude):
        return AnchorSnapshot(poi_id, store.store_id, "anchor_coordinates_invalid", None, None, None, None, None)
    province = _clean(store.standard_province)
    if not province:
        return AnchorSnapshot(poi_id, store.store_id, "anchor_province_missing", None, None, None, None, None)
    city = _clean(store.standard_city)
    if not city:
        return AnchorSnapshot(poi_id, store.store_id, "anchor_city_missing", None, None, None, None, None)
    if not _clean(store.city_code):
        return AnchorSnapshot(poi_id, store.store_id, "anchor_city_code_missing", None, None, None, None, None)
    return AnchorSnapshot(
        poi_id,
        store.store_id,
        None,
        province,
        city,
        _clean(store.city_code),
        longitude,
        latitude,
    )


def _lifecycle_status(normalized_status: str) -> str:
    return {
        "verified": "closed_verified",
        "refunded": "closed_refunded",
        "closed": "closed_order",
        "active": "active",
    }.get(normalized_status, "status_review")


def _closed_reason(normalized_status: str) -> str | None:
    return {
        "verified": "order_verified",
        "refunded": "order_refunded",
        "closed": "order_closed",
        "unknown": "order_status_unknown",
    }.get(normalized_status)


def _first_seen_at(raw_clue: RawDouyinClue, now: datetime) -> datetime:
    return _aware(raw_clue.create_time_detail) or _aware(raw_clue.fetched_at) or now


def _observed_at(raw_clue: RawDouyinClue, now: datetime) -> datetime:
    return _aware(raw_clue.modify_time) or _aware(raw_clue.fetched_at) or _aware(raw_clue.updated_at) or now


def _status_observed_at(raw_clue: RawDouyinClue, raw_order: RawDouyinOrder | None, now: datetime) -> datetime:
    if raw_order is not None:
        return _aware(raw_order.updated_at) or _observed_at(raw_clue, now)
    return _observed_at(raw_clue, now)


def _record_status_event(
    session: Session,
    *,
    lead_key: str,
    order_id: str | None,
    resolution: StatusResolution,
    observed_at: datetime,
    created_at: datetime,
    known_event_ids: set[str] | None = None,
) -> None:
    event_key = "|".join(
        (
            lead_key,
            resolution.status_source,
            resolution.raw_status or "",
            resolution.normalized_status,
            observed_at.isoformat(),
        )
    )
    digest = sha256(event_key.encode("utf-8")).hexdigest()
    event_id = f"status-{digest[:24]}"
    if known_event_ids is not None:
        if event_id in known_event_ids:
            return
        known_event_ids.add(event_id)
    elif session.get(ClueOrderStatusEvent, event_id) is not None:
        return
    session.add(
        ClueOrderStatusEvent(
            event_id=event_id,
            event_key=digest,
            lead_key=lead_key,
            order_id=order_id,
            raw_status=resolution.raw_status,
            normalized_status=resolution.normalized_status,
            status_source=resolution.status_source,
            observed_at=observed_at,
            created_at=created_at,
        )
    )


def _record_anchor_quality_issue(
    session: Session,
    lead_key: str,
    anchor: AnchorSnapshot,
    now: datetime,
    known_issue_ids: set[str],
) -> None:
    if not anchor.unavailable_reason:
        return
    issue_id = f"clue-anchor:{lead_key}:{anchor.unavailable_reason}"
    if issue_id in known_issue_ids:
        return
    known_issue_ids.add(issue_id)
    session.add(
        DataQualityIssue(
            issue_id=issue_id,
            issue_type="clue_anchor_unavailable",
            message="clue anchor is unavailable for allocation",
            severity="warning",
            raw_context_json={"anchor_poi_id": anchor.poi_id, "reason": anchor.unavailable_reason},
            source_run_id=None,
            created_at=now,
        )
    )


def _record_store_location_issue(session: Session, poi_id: str, reason: str, now: datetime) -> None:
    _ = now
    upsert_data_quality_issue(
        session,
        f"store-location:{poi_id}:{reason}",
        issue_type=reason,
        message="store location import requires attention",
        severity="warning",
        raw_context_json={"poi_id": poi_id, "reason": reason},
        source_run_id=None,
        flush=False,
    )


def _active_self_owned_current_round(
    session: Session,
    lead: ClueMasterLead,
    *,
    current_rounds_by_id: dict[str, ClueAssignmentRound] | None = None,
) -> ClueAssignmentRound | None:
    if not lead.current_assignment_round_id:
        return None
    round_row = (
        current_rounds_by_id.get(lead.current_assignment_round_id)
        if current_rounds_by_id is not None
        else session.get(ClueAssignmentRound, lead.current_assignment_round_id)
    )
    if round_row is None or round_row.execution_mode not in SELF_OWNED_EXECUTION_MODES:
        return None
    if round_row.round_status not in {"active_unfollowed", "active_followed"}:
        return None
    return round_row


def _close_current_assignment(
    session: Session,
    order_id: str,
    lifecycle_status: str,
    closed_at: datetime,
    *,
    current_assignment_round_id: str | None = None,
    center_orders_by_id: dict[str, ClueCenterOrder] | None = None,
    current_rounds_by_id: dict[str, ClueAssignmentRound] | None = None,
) -> None:
    center_order = (
        center_orders_by_id.get(order_id)
        if center_orders_by_id is not None
        else session.get(ClueCenterOrder, order_id)
    )
    round_status = _terminal_round_status(lifecycle_status)
    terminal_reason = _terminal_reason(lifecycle_status)
    lead_status = _terminal_center_lead_status(lifecycle_status)
    round_id = current_assignment_round_id or (
        center_order.current_assignment_round_id if center_order is not None else None
    )
    round_row = (
        current_rounds_by_id.get(round_id)
        if round_id and current_rounds_by_id is not None
        else (session.get(ClueAssignmentRound, round_id) if round_id else None)
    )
    if round_row is not None:
        round_row.round_status = round_status
        round_row.terminal_reason = terminal_reason
        round_row.matured_at = closed_at
        round_row.updated_at = closed_at
    if center_order is not None and (
        current_assignment_round_id is None
        or center_order.current_assignment_round_id == current_assignment_round_id
    ):
        center_order.lead_status = lead_status
        center_order.current_round_status = round_status
        center_order.reassign_reason = terminal_reason
        center_order.updated_at = closed_at


def _terminal_lifecycle_for_order(leads: list[ClueMasterLead]) -> str:
    """Choose one deterministic terminal state for an order-level snapshot."""
    lifecycle_statuses = {lead.lifecycle_status for lead in leads}
    for lifecycle_status in (
        "closed_verified",
        "closed_refunded",
        "closed_order",
        "status_review",
    ):
        if lifecycle_status in lifecycle_statuses:
            return lifecycle_status
    return "status_review"


def _terminal_round_status(lifecycle_status: str) -> str:
    return {
        "closed_verified": "closed_order_verified",
        "closed_refunded": "closed_order_refunded",
        "closed_order": "closed_order_closed",
    }.get(lifecycle_status, "closed_order_status_unknown")


def _terminal_reason(lifecycle_status: str) -> str:
    return {
        "closed_verified": "order_verified",
        "closed_refunded": "order_refunded",
        "closed_order": "order_closed",
    }.get(lifecycle_status, "order_status_unknown")


def _terminal_center_lead_status(lifecycle_status: str) -> str:
    return {
        "closed_verified": "converted",
        "closed_refunded": "refunded",
        "closed_order": "closed",
    }.get(lifecycle_status, "status_review")


def _terminal_closed_at(leads: list[ClueMasterLead], fallback: datetime) -> datetime:
    timestamps = [_aware(lead.closed_at) for lead in leads if lead.closed_at is not None]
    return min(timestamps) if timestamps else fallback


def _is_candidate_eligible(store: DimStore) -> bool:
    return bool(
        store.is_active
        and store.is_douyin_clue_applicable
        and store.participates_in_clue_allocation
        and store.location_status == "valid"
        and _clean(store.standard_province)
        and _clean(store.standard_city)
        and _clean(store.city_code)
        and _valid_coordinates(_decimal(store.latitude), _decimal(store.longitude))
    )


def _formal_store_metrics(
    session: Session,
    stores: list[DimStore],
    window_start: datetime,
    window_end: datetime,
) -> dict[str, StoreMetrics]:
    store_ids = {store.store_id for store in stores}
    rows = session.scalars(
        select(ClueAssignmentRound)
        .where(ClueAssignmentRound.execution_mode == "formal")
        .where(ClueAssignmentRound.matured_at.is_not(None))
        .where(ClueAssignmentRound.matured_at >= window_start)
        .where(ClueAssignmentRound.matured_at <= window_end)
        .where(ClueAssignmentRound.assigned_store_id.in_(store_ids))
    ).all()
    metrics_by_store: dict[str, StoreMetrics] = defaultdict(StoreMetrics)
    if not rows:
        return metrics_by_store
    round_ids = {row.assignment_round_id for row in rows}
    order_ids = {row.order_id for row in rows}
    follow_rows = session.scalars(
        select(ClueFollowUpRecord).where(ClueFollowUpRecord.assignment_round_id.in_(round_ids))
    ).all()
    follows_by_round: dict[str, list[ClueFollowUpRecord]] = defaultdict(list)
    for row in follow_rows:
        follows_by_round[row.assignment_round_id].append(row)
    verify_rows = session.execute(
        select(SettlementOrderDetail.order_id, SettlementOrderDetail.verify_time)
        .where(SettlementOrderDetail.order_id.in_(order_ids))
        .where(SettlementOrderDetail.is_verified.is_(True))
    ).all()
    verifies_by_order: dict[str, list[datetime | None]] = defaultdict(list)
    for order_id, verify_time in verify_rows:
        verifies_by_order[order_id].append(_aware(verify_time))
    all_formal_rounds_by_order: dict[str, list[ClueAssignmentRound]] = defaultdict(list)
    for formal_round in session.scalars(
        select(ClueAssignmentRound)
        .where(ClueAssignmentRound.execution_mode == "formal")
        .where(ClueAssignmentRound.order_id.in_(order_ids))
    ).all():
        all_formal_rounds_by_order[formal_round.order_id].append(formal_round)

    for round_row in rows:
        assigned_at = _aware(round_row.assigned_at)
        if not round_row.assigned_store_id or assigned_at is None:
            continue
        followed = _has_follow_within_24_hours(follows_by_round.get(round_row.assignment_round_id, []), assigned_at)
        converted = _has_verification_attributed_to_round(
            round_row,
            verifies_by_order.get(round_row.order_id, []),
            all_formal_rounds_by_order.get(round_row.order_id, []),
        )
        has_full_follow_up_opportunity = not _completed_within_24_hours(
            round_row,
            verifies_by_order.get(round_row.order_id, []),
            assigned_at,
        )
        metrics_by_store[round_row.assigned_store_id].add(
            converted=converted,
            followed_within_24h=followed,
            has_full_follow_up_opportunity=has_full_follow_up_opportunity,
        )
    return metrics_by_store


def _aggregate_city_metrics(
    stores: list[DimStore], metrics_by_store: dict[str, StoreMetrics]
) -> dict[str, StoreMetrics]:
    result: dict[str, StoreMetrics] = defaultdict(StoreMetrics)
    for store in stores:
        city_code = store.city_code or ""
        metric = metrics_by_store.get(store.store_id)
        if metric is None:
            continue
        target = result[city_code]
        target.conversion_numerator += metric.conversion_numerator
        target.conversion_denominator += metric.conversion_denominator
        target.follow_24h_numerator += metric.follow_24h_numerator
        target.follow_24h_denominator += metric.follow_24h_denominator
    return result


def _completed_within_24_hours(
    round_row: ClueAssignmentRound,
    verification_times: list[datetime | None],
    assigned_at: datetime,
) -> bool:
    cutoff = assigned_at + timedelta(hours=24)
    for candidate in [round_row.verified_at, *verification_times]:
        completed_at = _aware(candidate)
        if completed_at is not None and assigned_at <= completed_at <= cutoff:
            return True
    if round_row.terminal_reason in {"order_verified", "order_refunded"}:
        completed_at = _aware(round_row.matured_at)
        return completed_at is not None and assigned_at <= completed_at <= cutoff
    return False


def _sum_metrics(metrics: object) -> StoreMetrics:
    result = StoreMetrics()
    for metric in metrics:
        result.conversion_numerator += metric.conversion_numerator
        result.conversion_denominator += metric.conversion_denominator
        result.follow_24h_numerator += metric.follow_24h_numerator
        result.follow_24h_denominator += metric.follow_24h_denominator
    return result


def _resolved_rate(
    own_numerator: int,
    own_denominator: int,
    city_numerator: int,
    city_denominator: int,
    global_numerator: int,
    global_denominator: int,
    min_samples: int,
) -> tuple[Decimal, str]:
    for numerator, denominator, source in (
        (own_numerator, own_denominator, "store"),
        (city_numerator, city_denominator, "city"),
        (global_numerator, global_denominator, "global"),
    ):
        if denominator >= min_samples:
            return (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.000001")), source
    return Decimal("0"), "cold_start_empty"


def _has_follow_within_24_hours(records: list[ClueFollowUpRecord], assigned_at: datetime | None) -> bool:
    assigned_at = _aware(assigned_at)
    if assigned_at is None:
        return False
    deadline = assigned_at + timedelta(hours=24)
    return any(
        (created_at := _aware(record.created_at)) is not None and assigned_at <= created_at <= deadline
        for record in records
    )


def _has_verification_attributed_to_round(
    round_row: ClueAssignmentRound,
    verify_times: list[datetime | None],
    formal_rounds: list[ClueAssignmentRound],
) -> bool:
    """Attribute each verification to the latest formal assignment effective at that time."""
    for verify_time in verify_times:
        verified_at = _aware(verify_time)
        if verified_at is None:
            continue
        effective_rounds = [
            candidate
            for candidate in formal_rounds
            if (candidate_assigned_at := _aware(candidate.assigned_at)) is not None
            and candidate_assigned_at <= verified_at
        ]
        if not effective_rounds:
            continue
        current_round = max(
            effective_rounds,
            key=lambda candidate: (
                _aware(candidate.assigned_at),
                candidate.round_no,
                candidate.assignment_round_id,
            ),
        )
        if current_round.assignment_round_id == round_row.assignment_round_id:
            return True
    return False


def _clean(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _decimal(value: object | None) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _valid_coordinates(latitude: Decimal | None, longitude: Decimal | None) -> bool:
    return bool(
        latitude is not None
        and longitude is not None
        and Decimal("-90") <= latitude <= Decimal("90")
        and Decimal("-180") <= longitude <= Decimal("180")
    )


def _store_location_status(store: DimStore) -> str:
    if _is_closed_store_note(store.location_status_note):
        return "closed"
    if not _valid_coordinates(_decimal(store.latitude), _decimal(store.longitude)) or not _clean(store.city_code):
        return "invalid"
    if not _clean(store.standard_city) or not _clean(store.standard_province):
        return "partial"
    return "valid"


def _clean_header(value: object | None) -> str:
    return "".join(str(value or "").strip().split())


def _cell(row: tuple[object, ...], columns: dict[str, int], name: str) -> object | None:
    index = columns.get(name)
    return row[index] if index is not None and index < len(row) else None


def _text_cell(value: object | None) -> str | None:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return _clean(value)


def _is_closed_store_note(value: str | None) -> bool:
    note = _clean(value) or ""
    return "关闭" in note or "撤店" in note
