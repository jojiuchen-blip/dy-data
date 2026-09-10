"""Bounded first-allocation consumer for committed materialization batches."""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Lock
from time import monotonic

from sqlalchemy import exists, or_, select, text

from apps.api.dy_api.models import (
    ClueAssignmentRound, ClueCenterOrder, ClueHeadquartersPoolEntry,
    ClueMasterLead, RawDouyinClue, SyncSetting,
)
from apps.worker.clue_allocation import (
    _coupon_statuses_by_order, _raw_orders_by_id, _resolve_status,
    _verified_at_by_order, lock_clue_master_for_update,
    materialize_clue_master_leads,
)
from apps.worker.clue_allocation_engine import _AllocationBatchContext, allocate_lead
from apps.worker.clue_center import refresh_clue_center_projection

LOG = logging.getLogger(__name__)
LOCK_KEY = 90310910
CURSOR_KEY = "formal_first_allocation_cursor_v1"
CENTER_PROJECTION_CURSOR_KEY = "formal_first_allocation_center_projection_cursor_v1"
CENTER_REPAIR_BATCH_SIZE = 100
LAST_RESULT_KEY = "formal_first_allocation_last_result_v1"
_LOCAL_LOCK = Lock()


@contextmanager
def _exclusive(factory):
    # Keep the PostgreSQL connection checked out across per-lead commits.
    with factory() as probe:
        engine = probe.get_bind()
    if engine.dialect.name != "postgresql":
        held = _LOCAL_LOCK.acquire(blocking=False)
        try:
            yield held
        finally:
            if held:
                _LOCAL_LOCK.release()
        return
    with engine.connect() as connection:
        held = bool(connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}))
        connection.commit()
        try:
            yield held
        finally:
            if held:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
                connection.commit()


def _eligible_without_center():
    return (
        ClueMasterLead.master_kind == 1,
        ClueMasterLead.lifecycle_status == "active",
        ClueMasterLead.normalized_order_status == "active",
        ClueMasterLead.allocation_state == "pending_allocation",
        ClueMasterLead.current_assignment_round_id.is_(None),
        or_(ClueMasterLead.pool_location.is_(None), ClueMasterLead.pool_location != "headquarters_pool"),
        ~exists(select(ClueAssignmentRound.assignment_round_id).where(
            or_(ClueAssignmentRound.lead_key == ClueMasterLead.lead_key,
                ClueAssignmentRound.order_id == ClueMasterLead.order_id),
            ClueAssignmentRound.execution_mode.in_(("formal", "legacy")),
        )),
        ~exists(select(ClueHeadquartersPoolEntry.headquarters_pool_entry_id).where(
            ClueHeadquartersPoolEntry.lead_key == ClueMasterLead.lead_key,
        )),
    )


def _eligible():
    return (
        *_eligible_without_center(),
        exists(select(ClueCenterOrder.order_id).where(ClueCenterOrder.order_id == ClueMasterLead.order_id)),
    )


def _save_setting(session, key, value):
    row = session.get(SyncSetting, key)
    if row is None:
        session.add(SyncSetting(setting_key=key, setting_value=value))
    else:
        row.setting_value = value


def _missing_center_candidates(session, *, order_ids, limit):
    """Read a bounded page of active masters that have no center row.

    The selector deliberately mirrors the formal allocation guards except for
    the center existence check.  A rotating cursor lets terminal or malformed
    historical rows advance without starving later valid rows.
    """

    statement = (
        select(
            ClueMasterLead.lead_key,
            ClueMasterLead.order_id,
        )
        .where(*_eligible_without_center())
        .where(ClueMasterLead.order_id.is_not(None))
        .where(ClueMasterLead.order_id != "")
        .where(ClueMasterLead.order_id != "0")
        .where(~exists(select(ClueCenterOrder.order_id).where(
            ClueCenterOrder.order_id == ClueMasterLead.order_id,
        )))
        .order_by(ClueMasterLead.lead_key)
        .limit(limit)
    )
    if order_ids is not None:
        statement = statement.where(ClueMasterLead.order_id.in_(order_ids))
    else:
        cursor = session.get(SyncSetting, CENTER_PROJECTION_CURSOR_KEY)
        if cursor is not None and cursor.setting_value:
            statement = statement.where(ClueMasterLead.lead_key > cursor.setting_value)
    return list(session.execute(statement).all())


def _set_phase_timeouts(session, deadline):
    if deadline is None or session.get_bind().dialect.name != "postgresql":
        return
    remaining_ms = max(1, int((deadline - monotonic()) * 1000))
    lock_ms = max(1, min(1000, remaining_ms))
    session.execute(text(f"SET LOCAL lock_timeout = '{lock_ms}ms'"))
    session.execute(text(f"SET LOCAL statement_timeout = '{remaining_ms}ms'"))


def _repair_missing_center_projection(factory, *, order_ids, limit, now, deadline=None):
    """Materialize and project one bounded missing-center page.

    Existing master materialization remains the authority for source ordering
    and status evidence.  The center projection runs only after that commit,
    and formal allocation rechecks ``_eligible`` afterwards.  This makes the
    repair safe for old snapshots, terminal status changes, and retries.
    """

    requested_order_ids = None if order_ids is None else set(order_ids)
    if deadline is not None and monotonic() >= deadline:
        return {"scanned": 0, "projected": 0, "deferred": 1}
    with factory() as selection_session:
        _set_phase_timeouts(selection_session, deadline)
        candidates = _missing_center_candidates(
            selection_session,
            order_ids=requested_order_ids,
            limit=limit,
        )
        if not candidates:
            if requested_order_ids is None:
                cursor = selection_session.get(SyncSetting, CENTER_PROJECTION_CURSOR_KEY)
                if cursor is not None and cursor.setting_value:
                    _save_setting(selection_session, CENTER_PROJECTION_CURSOR_KEY, "")
                    selection_session.commit()
            return {
                "scanned": 0,
                "projected": 0,
                "deferred": 0,
                "wrapped": 1 if requested_order_ids is None else 0,
            }
        candidate_order_ids = {
            order_id for _, order_id in candidates if order_id and str(order_id).strip() not in {"", "0"}
        }
        last_lead_key = candidates[-1][0]

    if not candidate_order_ids:
        return {"scanned": len(candidates), "projected": 0, "deferred": 0}

    if deadline is not None and monotonic() >= deadline:
        return {"scanned": len(candidates), "projected": 0, "deferred": len(candidates)}
    with factory() as materialization_session:
        _set_phase_timeouts(materialization_session, deadline)
        materialization = materialize_clue_master_leads(
            materialization_session,
            now=now,
            order_ids=set(candidate_order_ids),
        )
        if materialization.get("skipped") == "locked":
            materialization_session.rollback()
            return {
                "scanned": len(candidates),
                "projected": 0,
                "deferred": len(candidates),
                "locked": 1,
            }
        materialization_session.commit()

    if deadline is not None and monotonic() >= deadline:
        return {"scanned": len(candidates), "projected": 0, "deferred": len(candidates)}
    # Materialization may have moved a stale active row to a terminal or
    # review state.  Select again after its commit so the projection receives
    # only rows that still satisfy the first-allocation guards.
    with factory() as eligible_session:
        _set_phase_timeouts(eligible_session, deadline)
        projectable_order_ids = set(
            eligible_session.scalars(
                select(ClueMasterLead.order_id)
                .where(ClueMasterLead.order_id.in_(candidate_order_ids))
                .where(*_eligible_without_center())
                .where(~exists(select(ClueCenterOrder.order_id).where(
                    ClueCenterOrder.order_id == ClueMasterLead.order_id,
                )))
            ).all()
        )

    if not projectable_order_ids:
        if deadline is not None and monotonic() >= deadline:
            return {"scanned": len(candidates), "projected": 0, "deferred": len(candidates)}
        if requested_order_ids is None:
            with factory() as cursor_session:
                _set_phase_timeouts(cursor_session, deadline)
                _save_setting(cursor_session, CENTER_PROJECTION_CURSOR_KEY, last_lead_key)
                cursor_session.commit()
        return {"scanned": len(candidates), "projected": 0, "deferred": 0}

    if deadline is not None and monotonic() >= deadline:
        return {"scanned": len(candidates), "projected": 0, "deferred": len(candidates)}
    with factory() as projection_session:
        _set_phase_timeouts(projection_session, deadline)
        projection = refresh_clue_center_projection(
            projection_session,
            now=now,
            order_ids=projectable_order_ids,
        )
        projection_session.commit()
        projected = int(projection.get("projected_orders", 0) or 0)

    if requested_order_ids is None:
        if deadline is not None and monotonic() >= deadline:
            return {"scanned": len(candidates), "projected": projected, "deferred": len(candidates)}
        with factory() as cursor_session:
            _set_phase_timeouts(cursor_session, deadline)
            _save_setting(cursor_session, CENTER_PROJECTION_CURSOR_KEY, last_lead_key)
            cursor_session.commit()
    return {"scanned": len(candidates), "projected": projected, "deferred": 0}


def run_formal_allocation_batch(factory, *, order_ids=None, max_items=100, now=None, max_seconds=10):
    """Allocate only never-assigned leads; failures remain eligible for retry.

    Compensation uses a durable rotating keyset cursor so an invalid head row
    cannot starve later leads. Exact batch notifications never move that cursor.
    No collection API calls or automatic round expiry are performed here.
    """
    limit = max(1, min(int(max_items), 500))
    deadline = monotonic() + max(0.1, min(float(max_seconds), 30))
    result = {
        "scanned": 0,
        "assigned": 0,
        "headquarters": 0,
        "skipped": 0,
        "failed": 0,
        "center_repaired": 0,
        "center_repair_scanned": 0,
        "center_repair_deferred": 0,
        "center_repair_failed": 0,
    }
    skip_reasons = {}
    requested_order_ids = None
    if order_ids is not None:
        requested_order_ids = sorted(set(order_ids))
        if len(requested_order_ids) > 1000:
            raise ValueError("formal allocation notification exceeds 1000 orders")
    with _exclusive(factory) as held:
        if not held:
            return {**result, "skipped_reason": "locked"}
        try:
            repair = _repair_missing_center_projection(
                factory,
                order_ids=(set(requested_order_ids) if requested_order_ids is not None else None),
                limit=min(limit, CENTER_REPAIR_BATCH_SIZE),
                now=(now or datetime.now(timezone.utc)),
                deadline=deadline,
            )
            result["center_repaired"] = int(repair.get("projected", 0) or 0)
            result["center_repair_scanned"] = int(repair.get("scanned", 0) or 0)
            result["center_repair_deferred"] = int(repair.get("deferred", 0) or 0)
        except Exception as exc:
            # A failed repair must not stop allocation for already projected
            # rows.  The missing-center page remains eligible for the next
            # bounded compensation pass because its cursor was not advanced.
            LOG.warning("formal_missing_center_projection_failed type=%s", type(exc).__name__)
            result["center_repair_failed"] = 1
            result["center_repair_deferred"] += 1
            repair = {"deferred": 1}
        keys = []
        if monotonic() < deadline:
            with factory() as session:
                _set_phase_timeouts(session, deadline)
                stmt = select(ClueMasterLead.lead_key).where(*_eligible())
                if requested_order_ids is not None:
                    stmt = stmt.where(ClueMasterLead.order_id.in_(requested_order_ids))
                else:
                    cursor = session.get(SyncSetting, CURSOR_KEY)
                    if cursor is not None and cursor.setting_value:
                        stmt = stmt.where(ClueMasterLead.lead_key > cursor.setting_value)
                keys = list(session.scalars(stmt.order_by(ClueMasterLead.lead_key).limit(limit)))
                if not keys and order_ids is None:
                    _save_setting(session, CURSOR_KEY, "")
                    session.commit()
        context = _AllocationBatchContext()
        for key in keys:
            if monotonic() >= deadline:
                break
            result["scanned"] += 1
            try:
                with factory() as session:
                    session.expire_on_commit = False
                    if session.get_bind().dialect.name == "sqlite":
                        # sqlite3 legacy mode does not BEGIN for SELECT. The
                        # engine uses savepoints, which need a real outer tx.
                        session.connection().exec_driver_sql("BEGIN")
                    elif session.get_bind().dialect.name == "postgresql":
                        _set_phase_timeouts(session, deadline)
                    lead = lock_clue_master_for_update(session, key)
                    eligible = session.scalar(select(ClueMasterLead.lead_key).where(
                        ClueMasterLead.lead_key == key, *_eligible(),
                    ))
                    if lead is None or eligible is None:
                        result["skipped"] += 1
                        skip_reasons["eligibility_changed"] = skip_reasons.get("eligibility_changed", 0) + 1
                        continue
                    source = session.get(RawDouyinClue, lead.source_clue_row_key)
                    executed_at = now or datetime.now(timezone.utc)
                    orders = {lead.order_id}
                    resolution = None if source is None or source.order_id != lead.order_id else _resolve_status(
                        source, _raw_orders_by_id(session, orders).get(lead.order_id),
                        _verified_at_by_order(session, orders).get(lead.order_id), executed_at,
                        _coupon_statuses_by_order(session, orders).get(lead.order_id, []),
                    )
                    if resolution is None or resolution.normalized_status != "active":
                        # Do not forge a status event: the materializer owns state
                        # transitions. This guard blocks stale historical labels.
                        result["skipped"] += 1
                        reason = "source_missing_or_rebound" if resolution is None else f"source_{resolution.normalized_status}"
                        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                        continue
                    allocated = allocate_lead(
                        session, key, execution_mode="formal", actor="formal_first_allocation",
                        now=executed_at, transition_key=f"first:{key}",
                        auto_expiry_enabled_override=False, _batch_context=context,
                    )
                    session.commit()
                    bucket = allocated.status if allocated.status in {"assigned", "headquarters"} else "skipped"
                    result[bucket] += 1
            except Exception as exc:
                result["failed"] += 1
                # Never log raw SQL parameters, order IDs, or customer data.
                LOG.warning("formal_first_allocation_item_failed type=%s", type(exc).__name__)
                context = _AllocationBatchContext()
            finally:
                if order_ids is None:
                    with factory() as checkpoint:
                        _save_setting(checkpoint, CURSOR_KEY, key)
                        checkpoint.commit()
        with factory() as session:
            result["skip_reasons"] = skip_reasons
            result["deferred"] = len(keys) - result["scanned"]
            _save_setting(session, LAST_RESULT_KEY, json.dumps({
                **result, "at": (now or datetime.now(timezone.utc)).isoformat(),
                "trigger": "batch" if order_ids is not None else "compensation",
            }))
            session.commit()
    LOG.info("formal_first_allocation_result %s", json.dumps(result))
    return result


def notify_formal_allocation(factory, order_ids):
    """A lost notification is recovered by the independent compensation loop."""
    try:
        return run_formal_allocation_batch(factory, order_ids=order_ids)
    except Exception as exc:
        LOG.warning("formal_first_allocation_notification_failed type=%s", type(exc).__name__)
        return {"failed": 1}
