from __future__ import annotations

import base64
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import hmac
import json
import os
import secrets
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueAllocationAuditLog,
    ClueAllocationCandidate,
    ClueAllocationCycle,
    ClueAllocationCycleItem,
    ClueAllocationDecision,
    ClueAssignmentRound,
    ClueFollowUpRecord,
    ClueHeadquartersPoolEntry,
    ClueLeadRuleVersionBinding,
    ClueMasterLead,
    utcnow,
)
from apps.worker.clue_allocation_engine import AllocationResult, allocate_lead
from apps.worker.clue_headquarters_pool import headquarters_pool_reason_storage_values
from apps.worker.clue_rule_versions import resolve_published_rule_version, rule_version_snapshot


SELF_OWNED_EXECUTION_MODES = {"formal", "trial"}
ACTIVE_ROUND_STATUSES = {"active_unfollowed", "active_followed"}
PREVIEW_TOKEN_TTL_SECONDS = 10 * 60
_EPHEMERAL_PREVIEW_SECRET = secrets.token_bytes(32)


class AllocationCycleError(ValueError):
    pass


@dataclass(frozen=True)
class AllocationPreviewGrant:
    operation: str
    lead_keys: tuple[str, ...]
    source_cycle_id: str | None
    privileged_confirmation: bool
    rebind_rule_version: bool
    state_snapshot: tuple[dict[str, Any], ...]
    state_hash: str
    previewed_at: datetime
    expires_at: datetime
    token: str
    token_hash: str


def preview_trial_allocation_cycle(
    session: Session,
    *,
    lead_keys: Iterable[str],
    actor: str,
    rebind_rule_version: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Calculate a trial allocation outcome in a rolled-back savepoint."""

    keys = _normalized_lead_keys(lead_keys)
    executed_at = _aware(now or utcnow())
    _assert_no_headquarters_reentry(session, keys)
    active_keys = _active_lead_keys(session, keys)
    state_snapshot = _current_preview_state(
        session,
        active_keys,
        rebind_rule_version=rebind_rule_version,
    )
    savepoint = session.begin_nested()
    try:
        if rebind_rule_version:
            _remove_trial_bindings(session, active_keys)
        results = [
            allocate_lead(
                session,
                lead_key,
                execution_mode="trial",
                actor=actor,
                now=executed_at,
                auto_expiry_enabled_override=False,
            )
            for lead_key in active_keys
        ]
        summary = _summary(results)
    finally:
        savepoint.rollback()
        session.expire_all()
    grant = _issue_preview_grant(
        operation="trial",
        lead_keys=active_keys,
        actor=actor,
        previewed_at=executed_at,
        rebind_rule_version=rebind_rule_version,
        state_snapshot=state_snapshot,
    )
    return {
        "requested_lead_count": len(keys),
        "eligible_lead_count": len(active_keys),
        "active_lead_count": len(active_keys),
        "lead_keys": active_keys,
        "summary": summary,
        "changed_leads": _preview_changed_leads(results),
        "operation": grant.operation,
        "source_cycle_id": grant.source_cycle_id,
        "preview_token": grant.token,
        "preview_expires_at": grant.expires_at,
    }


def preview_rebuild_trial_allocation_cycle(
    session: Session,
    *,
    source_cycle_id: str,
    actor: str,
    privileged_confirmation: bool = False,
    rebind_rule_version: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Calculate a rebuild from one source trial cycle without writing state."""

    executed_at = _aware(now or utcnow())
    source_cycle = _rebuild_source_cycle(session, source_cycle_id)
    active_keys = _rebuild_active_lead_keys(session, source_cycle)
    if not active_keys:
        raise AllocationCycleError("source_cycle_not_rebuildable")
    blocked_keys = _rebuild_blocked_lead_keys(session, active_keys)
    if blocked_keys and not privileged_confirmation:
        raise AllocationCycleError(
            f"rebuild_blocked_by_follow_up:{','.join(blocked_keys)}"
        )
    state_snapshot = _current_preview_state(
        session,
        active_keys,
        rebind_rule_version=rebind_rule_version,
    )
    savepoint = session.begin_nested()
    try:
        if rebind_rule_version:
            _remove_trial_bindings(session, active_keys)
        results = [
            allocate_lead(
                session,
                lead_key,
                execution_mode="trial",
                actor=actor,
                now=executed_at,
                auto_expiry_enabled_override=False,
            )
            for lead_key in active_keys
        ]
        summary = _summary(results)
    finally:
        savepoint.rollback()
        session.expire_all()
    grant = _issue_preview_grant(
        operation="trial_rebuild",
        lead_keys=active_keys,
        actor=actor,
        previewed_at=executed_at,
        source_cycle_id=source_cycle.allocation_cycle_id,
        privileged_confirmation=privileged_confirmation,
        rebind_rule_version=rebind_rule_version,
        state_snapshot=state_snapshot,
    )
    return {
        "requested_lead_count": len(active_keys),
        "eligible_lead_count": len(active_keys),
        "active_lead_count": len(active_keys),
        "lead_keys": active_keys,
        "summary": summary,
        "changed_leads": _preview_changed_leads(results),
        "operation": grant.operation,
        "source_cycle_id": grant.source_cycle_id,
        "preview_token": grant.token,
        "preview_expires_at": grant.expires_at,
    }


def validate_allocation_preview_grant(
    preview_token: str | None,
    *,
    operation: str,
    actor: str,
    lead_keys: Iterable[str] | None = None,
    source_cycle_id: str | None = None,
    privileged_confirmation: bool = False,
    rebind_rule_version: bool | None = None,
    now: datetime | None = None,
) -> AllocationPreviewGrant:
    normalized_token = str(preview_token or "").strip()
    if not normalized_token:
        raise AllocationCycleError("preview_required")
    encoded_payload, separator, signature = normalized_token.partition(".")
    if not separator or not encoded_payload or not signature:
        raise AllocationCycleError("preview_token_invalid")
    expected_signature = _preview_signature(encoded_payload)
    if not hmac.compare_digest(signature, expected_signature):
        raise AllocationCycleError("preview_token_invalid")
    try:
        payload = json.loads(_urlsafe_b64decode(encoded_payload).decode("utf-8"))
        previewed_at = datetime.fromtimestamp(int(payload["previewed_at"]), tz=timezone.utc)
        expires_at = datetime.fromtimestamp(int(payload["expires_at"]), tz=timezone.utc)
        token_lead_keys = tuple(_normalized_lead_keys(payload["lead_keys"]))
        token_state_snapshot = tuple(
            dict(item) for item in payload["state_snapshot"] if isinstance(item, dict)
        )
        token_state_hash = str(payload["state_hash"])
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise AllocationCycleError("preview_token_invalid") from None
    current_time = _aware(now or utcnow())
    if current_time >= expires_at:
        raise AllocationCycleError("preview_expired")
    if payload.get("operation") != operation:
        raise AllocationCycleError("preview_token_mismatch")
    if not hmac.compare_digest(str(payload.get("actor_hash") or ""), _actor_hash(actor)):
        raise AllocationCycleError("preview_token_mismatch")
    expected_keys = tuple(_normalized_lead_keys(lead_keys or [])) if lead_keys is not None else None
    if expected_keys is not None and token_lead_keys != expected_keys:
        raise AllocationCycleError("preview_token_mismatch")
    normalized_source_cycle_id = str(source_cycle_id or "").strip() or None
    if (str(payload.get("source_cycle_id") or "").strip() or None) != normalized_source_cycle_id:
        raise AllocationCycleError("preview_token_mismatch")
    if payload.get("privileged_confirmation") is not privileged_confirmation:
        raise AllocationCycleError("preview_token_mismatch")
    token_rebind_rule_version = bool(payload.get("rebind_rule_version", False))
    if rebind_rule_version is not None and token_rebind_rule_version is not rebind_rule_version:
        raise AllocationCycleError("preview_token_mismatch")
    if token_state_hash != _snapshot_hash(token_state_snapshot):
        raise AllocationCycleError("preview_token_invalid")
    return AllocationPreviewGrant(
        operation=operation,
        lead_keys=token_lead_keys,
        source_cycle_id=normalized_source_cycle_id,
        privileged_confirmation=privileged_confirmation,
        rebind_rule_version=token_rebind_rule_version,
        state_snapshot=token_state_snapshot,
        state_hash=token_state_hash,
        previewed_at=previewed_at,
        expires_at=expires_at,
        token=normalized_token,
        token_hash=sha256(normalized_token.encode("utf-8")).hexdigest(),
    )


def run_trial_allocation_cycle(
    session: Session,
    *,
    lead_keys: Iterable[str],
    actor: str,
    actor_user_id: str | None = None,
    actor_role_snapshot: str | None = None,
    actor_scope_snapshot: dict[str, Any] | None = None,
    request_id: str | None = None,
    privileged_confirmation: bool = False,
    preview_token_hash: str | None = None,
    preview_expires_at: datetime | None = None,
    idempotency_key: str | None = None,
    expected_lead_keys: Iterable[str] | None = None,
    expected_state_snapshot: Iterable[dict[str, Any]] | None = None,
    rebind_rule_version: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    return _execute_trial_cycle(
        session,
        lead_keys=lead_keys,
        actor=actor,
        actor_user_id=actor_user_id,
        actor_role_snapshot=actor_role_snapshot,
        actor_scope_snapshot=actor_scope_snapshot,
        request_id=request_id,
        cycle_type="trial",
        privileged_confirmation=privileged_confirmation,
        preview_token_hash=preview_token_hash,
        preview_expires_at=preview_expires_at,
        idempotency_key=idempotency_key,
        expected_lead_keys=expected_lead_keys,
        expected_state_snapshot=expected_state_snapshot,
        rebind_rule_version=rebind_rule_version,
        now=now,
    )


def rebuild_trial_allocation_cycle(
    session: Session,
    *,
    source_cycle_id: str,
    actor: str,
    actor_user_id: str | None = None,
    actor_role_snapshot: str | None = None,
    actor_scope_snapshot: dict[str, Any] | None = None,
    request_id: str | None = None,
    privileged_confirmation: bool = False,
    preview_token_hash: str | None = None,
    preview_expires_at: datetime | None = None,
    idempotency_key: str | None = None,
    expected_lead_keys: Iterable[str] | None = None,
    expected_state_snapshot: Iterable[dict[str, Any]] | None = None,
    rebind_rule_version: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    executed_at = _aware(now or utcnow())
    existing_preview_cycle = _existing_cycle_for_preview_token(session, preview_token_hash)
    if existing_preview_cycle is not None:
        return _cycle_execution_payload(existing_preview_cycle)
    source_cycle = _rebuild_source_cycle(session, source_cycle_id)
    active_keys = _rebuild_active_lead_keys(session, source_cycle)
    if not active_keys:
        raise AllocationCycleError("source_cycle_not_rebuildable")
    if expected_lead_keys is not None and tuple(active_keys) != tuple(
        _normalized_lead_keys(expected_lead_keys)
    ):
        raise AllocationCycleError("preview_no_longer_matches")
    request_hash = _cycle_request_hash(
        operation="trial_rebuild",
        lead_keys=active_keys,
        source_cycle_id=source_cycle_id,
        preview_token_hash=preview_token_hash,
        privileged_confirmation=privileged_confirmation,
        rebind_rule_version=rebind_rule_version,
    )
    existing_cycle = _existing_cycle_for_idempotency_key(
        session,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if existing_cycle is not None:
        return _cycle_execution_payload(existing_cycle)
    if preview_token_hash or expected_state_snapshot is not None:
        _assert_preview_state_matches(
            session,
            expected_state_snapshot,
            rebind_rule_version=rebind_rule_version,
        )
    blocked_keys = _rebuild_blocked_lead_keys(session, active_keys)
    if blocked_keys and not privileged_confirmation:
        raise AllocationCycleError(
            f"rebuild_blocked_by_follow_up:{','.join(blocked_keys)}"
        )
    return _execute_trial_cycle(
        session,
        lead_keys=active_keys,
        actor=actor,
        actor_user_id=actor_user_id,
        actor_role_snapshot=actor_role_snapshot,
        actor_scope_snapshot=actor_scope_snapshot,
        request_id=request_id,
        cycle_type="trial_rebuild",
        parent_cycle_id=source_cycle.allocation_cycle_id,
        privileged_confirmation=privileged_confirmation,
        now=executed_at,
        already_filtered=True,
        preview_token_hash=preview_token_hash,
        preview_expires_at=preview_expires_at,
        idempotency_key=idempotency_key,
        expected_state_snapshot=expected_state_snapshot,
        rebind_rule_version=rebind_rule_version,
    )


def _execute_trial_cycle(
    session: Session,
    *,
    lead_keys: Iterable[str],
    actor: str,
    actor_user_id: str | None,
    actor_role_snapshot: str | None,
    actor_scope_snapshot: dict[str, Any] | None,
    request_id: str | None,
    cycle_type: str,
    privileged_confirmation: bool,
    now: datetime | None,
    parent_cycle_id: str | None = None,
    already_filtered: bool = False,
    preview_token_hash: str | None = None,
    preview_expires_at: datetime | None = None,
    idempotency_key: str | None = None,
    expected_lead_keys: Iterable[str] | None = None,
    expected_state_snapshot: Iterable[dict[str, Any]] | None = None,
    rebind_rule_version: bool = False,
) -> dict[str, Any]:
    keys = _normalized_lead_keys(lead_keys)
    executed_at = _aware(now or utcnow())
    request_hash = _cycle_request_hash(
        operation=cycle_type,
        lead_keys=keys,
        source_cycle_id=parent_cycle_id,
        preview_token_hash=preview_token_hash,
        privileged_confirmation=privileged_confirmation,
        rebind_rule_version=rebind_rule_version,
    )
    existing_cycle = _existing_cycle_for_idempotency_key(
        session,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    ) or _existing_cycle_for_preview_token(session, preview_token_hash)
    if existing_cycle is not None:
        return _cycle_execution_payload(existing_cycle)
    _assert_no_headquarters_reentry(session, keys)
    active_keys = keys if already_filtered else _active_lead_keys(session, keys, lock=True)
    if expected_lead_keys is not None and tuple(active_keys) != tuple(
        _normalized_lead_keys(expected_lead_keys)
    ):
        raise AllocationCycleError("preview_no_longer_matches")
    if preview_token_hash or expected_state_snapshot is not None:
        _assert_preview_state_matches(
            session,
            expected_state_snapshot,
            rebind_rule_version=rebind_rule_version,
        )
    _ensure_no_conflicting_current_rounds(session, active_keys)
    cycle = ClueAllocationCycle(
        allocation_cycle_id=f"allocation-cycle-{uuid4().hex}",
        cycle_type=cycle_type,
        execution_mode="trial",
        status="running",
        parent_cycle_id=parent_cycle_id,
        selected_lead_keys=active_keys,
        requested_lead_count=len(keys),
        active_lead_count=len(active_keys),
        planned_impact_json={"lead_keys": active_keys, "auto_expiry_enabled": False},
        actual_impact_json={},
        actor=actor,
        actor_user_id=actor_user_id,
        actor_username_snapshot=actor,
        privileged_confirmation=privileged_confirmation,
        preview_token_hash=preview_token_hash,
        preview_expires_at=preview_expires_at,
        idempotency_key_hash=_idempotency_key_hash(idempotency_key),
        idempotency_request_hash=request_hash,
        request_scope_snapshot={
            "lead_keys": active_keys,
            "rebind_rule_version": rebind_rule_version,
            "state_snapshot_hash": _snapshot_hash(expected_state_snapshot or []),
            "actor_scope": dict(actor_scope_snapshot or {}),
        },
        error_summary={},
        state_version=1,
        created_at=executed_at,
        executed_at=executed_at,
    )
    existing_cycle = _register_cycle_or_get_existing(session, cycle)
    if existing_cycle is not None:
        return _cycle_execution_payload(existing_cycle)
    expected_by_lead = {
        str(item.get("lead_key")): dict(item)
        for item in (expected_state_snapshot or [])
        if isinstance(item, dict) and item.get("lead_key")
    }
    results: list[AllocationResult] = []
    failed_count = 0
    for sequence_no, lead_key in enumerate(active_keys, start=1):
        lead = session.get(ClueMasterLead, lead_key)
        item = ClueAllocationCycleItem(
            cycle_item_id=f"cycle-item-{uuid4().hex}",
            allocation_cycle_id=cycle.allocation_cycle_id,
            sequence_no=sequence_no,
            lead_key=lead_key,
            order_id=lead.order_id if lead is not None else None,
            item_status="running",
            initial_pool_location=(
                lead.pool_location or lead.allocation_state
                if lead is not None
                else None
            ),
            precondition_snapshot=expected_by_lead.get(lead_key, {}),
            attempt_count=1,
            started_at=executed_at,
            created_at=executed_at,
            updated_at=executed_at,
        )
        session.add(item)
        session.flush()
        try:
            result = _persist_trial_evidence(
                session,
                lead_key=lead_key,
                allocation_cycle_id=cycle.allocation_cycle_id,
                actor=actor,
                executed_at=executed_at,
                rebind_rule_version=rebind_rule_version,
            )
        except Exception as error:
            failed_count += 1
            item.item_status = "failed"
            item.error_code = type(error).__name__
            item.error_detail = "allocation trial failed; inspect server logs by cycle item id"
            item.completed_at = executed_at
            item.updated_at = executed_at
            continue
        results.append(result)
        final_decision = _final_cycle_decision(
            session,
            allocation_cycle_id=cycle.allocation_cycle_id,
            lead_key=lead_key,
        )
        item.item_status = result.status
        item.outcome_reason = result.reason
        item.decision_id = final_decision.decision_id if final_decision is not None else None
        # Trial execution intentionally rolls back rule bindings; only the decision keeps
        # the resolved rule version evidence.
        item.rule_binding_id = None
        item.completed_at = executed_at
        item.updated_at = executed_at
    summary = _summary(results, failed_count=failed_count)
    cycle.status = "partial_failed" if failed_count and results else "failed" if failed_count else "completed"
    cycle.actual_impact_json = summary
    cycle.error_summary = {"failed": failed_count} if failed_count else {}
    cycle.completed_at = executed_at
    cycle.state_version += 1
    _record_audit(
        session,
        event_type="trial_rebuilt" if cycle_type == "trial_rebuild" else "trial_executed",
        cycle=cycle,
        actor=actor,
        actor_user_id=actor_user_id,
        actor_role_snapshot=actor_role_snapshot,
        actor_scope_snapshot=actor_scope_snapshot,
        request_id=request_id,
        privileged_confirmation=privileged_confirmation,
        before_snapshot={"lead_keys": active_keys, "parent_cycle_id": parent_cycle_id},
        after_snapshot=summary,
        result_status=cycle.status,
        reason_code="cycle_items_failed" if failed_count else None,
    )
    session.flush()
    return _cycle_execution_payload(cycle)


def _persist_trial_evidence(
    session: Session,
    *,
    lead_key: str,
    allocation_cycle_id: str,
    actor: str,
    executed_at: datetime,
    rebind_rule_version: bool = False,
) -> AllocationResult:
    """Persist trial decisions while rolling back every business-state mutation."""

    savepoint = session.begin_nested()
    captured_decisions: list[dict[str, Any]] = []
    result: AllocationResult | None = None
    try:
        if rebind_rule_version:
            _remove_trial_bindings(session, [lead_key])
        result = allocate_lead(
            session,
            lead_key,
            execution_mode="trial",
            allocation_cycle_id=allocation_cycle_id,
            actor=actor,
            now=executed_at,
            auto_expiry_enabled_override=False,
        )
        rows = session.scalars(
            select(ClueAllocationDecision)
            .where(ClueAllocationDecision.allocation_cycle_id == allocation_cycle_id)
            .where(ClueAllocationDecision.lead_key == lead_key)
            .order_by(
                ClueAllocationDecision.execution_order,
                ClueAllocationDecision.decision_id,
            )
        ).all()
        captured_decisions = [_trial_decision_copy(row) for row in rows]
    finally:
        savepoint.rollback()
        session.expire_all()

    if result is None:
        raise AllocationCycleError("trial_evidence_not_captured")
    for payload in captured_decisions:
        decision = ClueAllocationDecision(**payload)
        session.add(decision)
        for candidate in _candidate_snapshots_from_decision(decision, executed_at=executed_at):
            session.add(candidate)
    session.flush()
    return AllocationResult(
        lead_key=result.lead_key,
        status=result.status,
        reason=result.reason,
        selected_store_id=result.selected_store_id,
        assignment_round_id=None,
        decision_ids=tuple(payload["decision_id"] for payload in captured_decisions),
    )


def _trial_decision_copy(row: ClueAllocationDecision) -> dict[str, Any]:
    snapshot = deepcopy(row.decision_snapshot or {})
    simulated_round = snapshot.pop("assignment_round", None)
    if isinstance(simulated_round, dict):
        simulated_round["assignment_round_id"] = None
        snapshot["simulated_assignment_round"] = simulated_round
    snapshot["dataset_kind"] = "trial"
    return {
        "decision_id": row.decision_id,
        "attempt_key": row.attempt_key,
        "lead_key": row.lead_key,
        "order_id": row.order_id,
        "rule_id": row.rule_id,
        "rule_version_id": row.rule_version_id,
        "scope_type": row.scope_type,
        "scope_key": row.scope_key,
        "strategy_type": row.strategy_type,
        "execution_order": row.execution_order,
        "allocation_cycle_id": row.allocation_cycle_id,
        "execution_mode": "trial",
        "assignment_round_id": None,
        "round_no": None,
        "selected_store_id": row.selected_store_id,
        "selected_store_name": row.selected_store_name,
        "decision_status": row.decision_status,
        "reason": row.reason,
        "decision_snapshot": snapshot,
        "actor": row.actor,
        "executed_at": row.executed_at,
    }


def _candidate_snapshots_from_decision(
    decision: ClueAllocationDecision,
    *,
    executed_at: datetime,
) -> list[ClueAllocationCandidate]:
    snapshot = decision.decision_snapshot if isinstance(decision.decision_snapshot, dict) else {}
    raw_candidates = snapshot.get("candidates")
    candidates = raw_candidates if isinstance(raw_candidates, list) else []
    sale_store = snapshot.get("sale_store") if isinstance(snapshot.get("sale_store"), dict) else {}
    historical_store_ids = {
        str(value)
        for value in (snapshot.get("historical_self_owned_store_ids") or [])
        if value is not None
    }
    selected_store_id = str(decision.selected_store_id or snapshot.get("selected_store_id") or "")
    rows: list[ClueAllocationCandidate] = []
    for index, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            continue
        store_id = str(candidate.get("store_id") or "").strip()
        if not store_id:
            continue
        score = candidate.get("score") if isinstance(candidate.get("score"), dict) else {}
        reasons = candidate.get("exclusion_reasons")
        reason_codes = [str(value) for value in reasons] if isinstance(reasons, list) else []
        rank_no = candidate.get("rank") if isinstance(candidate.get("rank"), int) else None
        rows.append(
            ClueAllocationCandidate(
                candidate_id=(
                    "allocation-candidate-"
                    + sha256(f"{decision.decision_id}:{store_id}".encode("utf-8")).hexdigest()[:24]
                ),
                decision_id=decision.decision_id,
                lead_key=decision.lead_key,
                order_id=decision.order_id,
                strategy_type=decision.strategy_type,
                store_id=store_id,
                store_name_snapshot=str(candidate.get("store_name") or store_id),
                city_code=str(candidate.get("city_code") or "").strip() or None,
                eligibility_status="eligible" if candidate.get("eligible") else "excluded",
                exclusion_reason_code=reason_codes[0] if reason_codes else None,
                exclusion_detail=", ".join(reason_codes)[:500] or None,
                is_sales_store=store_id == str(sale_store.get("store_id") or ""),
                is_historical_assignment=store_id in historical_store_ids,
                is_serviceable=bool(candidate.get("eligible")),
                distance_km=_decimal_or_none(candidate.get("distance_km")),
                store_location_snapshot={},
                score_snapshot_id=str(score.get("snapshot_id") or "").strip() or None,
                conversion_rate=_decimal_or_none(score.get("conversion_rate")),
                follow_24h_rate=_decimal_or_none(score.get("follow_24h_rate")),
                store_weight=_decimal_or_none(score.get("store_weight")),
                composite_score=_decimal_or_none(score.get("composite_score")),
                rank_no=rank_no,
                is_selected=store_id == selected_store_id,
                sort_key_snapshot={
                    "rank_no": rank_no,
                    "composite_score": score.get("composite_score"),
                    "distance_km": candidate.get("distance_km"),
                    "store_id": store_id,
                },
                evaluated_at=executed_at,
                created_at=executed_at,
                updated_at=executed_at,
            )
        )
    return rows


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _normalized_lead_keys(lead_keys: Iterable[str]) -> list[str]:
    values = {str(lead_key).strip() for lead_key in lead_keys if str(lead_key).strip()}
    if not values:
        raise AllocationCycleError("lead_keys_required")
    return sorted(values)


def _active_lead_keys(
    session: Session,
    lead_keys: list[str],
    *,
    lock: bool = False,
) -> list[str]:
    statement = (
        select(ClueMasterLead)
        .where(ClueMasterLead.lead_key.in_(lead_keys))
        .where(ClueMasterLead.lifecycle_status == "active")
        .where(ClueMasterLead.normalized_order_status == "active")
        .order_by(ClueMasterLead.lead_key)
    )
    if lock:
        statement = statement.with_for_update()
    rows = session.scalars(statement).all()
    return [row.lead_key for row in rows]


def _assert_no_headquarters_reentry(session: Session, lead_keys: list[str]) -> None:
    if not lead_keys:
        return
    retriable_entry = (
        select(ClueHeadquartersPoolEntry.headquarters_pool_entry_id)
        .where(ClueHeadquartersPoolEntry.lead_key == ClueMasterLead.lead_key)
        .where(ClueHeadquartersPoolEntry.status == "active")
        .where(
            ClueHeadquartersPoolEntry.reason.in_(
                headquarters_pool_reason_storage_values("no_published_rule")
            )
        )
        .exists()
    )
    rows = session.scalars(
        select(ClueMasterLead.lead_key)
        .where(ClueMasterLead.lead_key.in_(lead_keys))
        .where(ClueMasterLead.lifecycle_status == "active")
        .where(ClueMasterLead.pool_location == "headquarters_pool")
        .where(~retriable_entry)
        .order_by(ClueMasterLead.lead_key)
    ).all()
    if rows:
        raise AllocationCycleError(
            f"headquarters_reentry_not_supported:{','.join(rows)}"
        )


def _ensure_no_conflicting_current_rounds(session: Session, lead_keys: list[str]) -> None:
    if not lead_keys:
        return
    rows = session.scalars(
        select(ClueMasterLead)
        .where(ClueMasterLead.lead_key.in_(lead_keys))
        .order_by(ClueMasterLead.lead_key)
    ).all()
    conflicts: list[str] = []
    for lead in rows:
        if not lead.current_assignment_round_id:
            continue
        round_row = session.get(ClueAssignmentRound, lead.current_assignment_round_id)
        if round_row is None or round_row.round_status not in ACTIVE_ROUND_STATUSES:
            continue
        conflicts.append(lead.lead_key)
    if conflicts:
        raise AllocationCycleError(f"active_round_exists:{','.join(conflicts)}")


def _rebuild_blocked_lead_keys(session: Session, lead_keys: list[str]) -> list[str]:
    if not lead_keys:
        return []
    followed_rows = session.scalars(
        select(ClueAssignmentRound.lead_key)
        .where(ClueAssignmentRound.lead_key.in_(lead_keys))
        .where(ClueAssignmentRound.execution_mode.in_(SELF_OWNED_EXECUTION_MODES))
        .where(ClueAssignmentRound.is_followed.is_(True))
    ).all()
    recorded_rows = session.scalars(
        select(ClueAssignmentRound.lead_key)
        .join(
            ClueFollowUpRecord,
            ClueFollowUpRecord.assignment_round_id == ClueAssignmentRound.assignment_round_id,
        )
        .where(ClueAssignmentRound.lead_key.in_(lead_keys))
        .where(ClueAssignmentRound.execution_mode.in_(SELF_OWNED_EXECUTION_MODES))
        .where(ClueFollowUpRecord.deleted_at.is_(None))
    ).all()
    return sorted({lead_key for lead_key in [*followed_rows, *recorded_rows] if lead_key})


def _rebuild_source_cycle(session: Session, source_cycle_id: str) -> ClueAllocationCycle:
    normalized = str(source_cycle_id).strip()
    if not normalized:
        raise AllocationCycleError("source_cycle_required")
    cycle = session.get(ClueAllocationCycle, normalized)
    if (
        cycle is None
        or cycle.execution_mode != "trial"
        or cycle.status != "completed"
        or cycle.cycle_type not in {"trial", "trial_rebuild"}
    ):
        raise AllocationCycleError("source_cycle_not_rebuildable")
    return cycle


def _rebuild_active_lead_keys(
    session: Session,
    source_cycle: ClueAllocationCycle,
) -> list[str]:
    source_keys = _normalized_lead_keys(source_cycle.selected_lead_keys or [])
    return _active_lead_keys(session, source_keys, lock=True)


def _summary(results: list[AllocationResult], *, failed_count: int = 0) -> dict[str, int]:
    counts = Counter(result.status for result in results)
    return {
        "assigned": int(counts["assigned"]),
        "headquarters": int(counts["headquarters"]),
        "skipped": int(counts["skipped"]),
        "failed": int(failed_count),
        "total": len(results) + int(failed_count),
    }


def _preview_changed_leads(results: list[AllocationResult]) -> list[dict[str, Any]]:
    return [
        {
            "lead_key": result.lead_key,
            "outcome": result.status,
            "reason": result.reason,
            "selected_store_id": result.selected_store_id,
        }
        for result in results[:200]
    ]


def _existing_cycle_for_preview_token(
    session: Session,
    preview_token_hash: str | None,
) -> ClueAllocationCycle | None:
    if not preview_token_hash:
        return None
    return session.scalar(
        select(ClueAllocationCycle)
        .where(ClueAllocationCycle.preview_token_hash == preview_token_hash)
    )


def _existing_cycle_for_idempotency_key(
    session: Session,
    *,
    idempotency_key: str | None,
    request_hash: str,
) -> ClueAllocationCycle | None:
    key_hash = _idempotency_key_hash(idempotency_key)
    if not key_hash:
        return None
    cycle = session.scalar(
        select(ClueAllocationCycle).where(ClueAllocationCycle.idempotency_key_hash == key_hash)
    )
    if cycle is not None and cycle.idempotency_request_hash != request_hash:
        raise AllocationCycleError("idempotency_key_conflict")
    return cycle


def _register_cycle_or_get_existing(
    session: Session,
    cycle: ClueAllocationCycle,
) -> ClueAllocationCycle | None:
    try:
        with session.begin_nested():
            session.add(cycle)
            session.flush()
    except IntegrityError:
        winner = None
        if cycle.idempotency_key_hash:
            winner = session.scalar(
                select(ClueAllocationCycle).where(
                    ClueAllocationCycle.idempotency_key_hash == cycle.idempotency_key_hash
                )
            )
            if winner is not None and winner.idempotency_request_hash != cycle.idempotency_request_hash:
                raise AllocationCycleError("idempotency_key_conflict")
        if winner is None and cycle.preview_token_hash:
            winner = session.scalar(
                select(ClueAllocationCycle).where(
                    ClueAllocationCycle.preview_token_hash == cycle.preview_token_hash
                )
            )
        if winner is None:
            raise
        return winner
    return None


def _idempotency_key_hash(idempotency_key: str | None) -> str | None:
    normalized = str(idempotency_key or "").strip()
    return sha256(normalized.encode("utf-8")).hexdigest() if normalized else None


def _cycle_request_hash(
    *,
    operation: str,
    lead_keys: Iterable[str],
    source_cycle_id: str | None,
    preview_token_hash: str | None,
    privileged_confirmation: bool,
    rebind_rule_version: bool,
) -> str:
    payload = {
        "operation": operation,
        "lead_keys": _normalized_lead_keys(lead_keys),
        "source_cycle_id": str(source_cycle_id or "").strip() or None,
        "preview_token_hash": str(preview_token_hash or "").strip() or None,
        "privileged_confirmation": bool(privileged_confirmation),
        "rebind_rule_version": bool(rebind_rule_version),
    }
    return _snapshot_hash(payload)


def _cycle_execution_payload(cycle: ClueAllocationCycle) -> dict[str, Any]:
    summary = dict(cycle.actual_impact_json or {})
    return {
        "cycle_id": cycle.allocation_cycle_id,
        "allocation_cycle_id": cycle.allocation_cycle_id,
        "cycle_mode": cycle.cycle_type,
        "cycle_type": cycle.cycle_type,
        "execution_mode": cycle.execution_mode,
        "cycle_status": cycle.status,
        "status": cycle.status,
        "requested_lead_count": cycle.requested_lead_count,
        "eligible_lead_count": cycle.active_lead_count,
        "active_lead_count": cycle.active_lead_count,
        "assigned_lead_count": int(summary.get("assigned", 0)),
        "headquarters_pool_count": int(summary.get("headquarters", 0)),
        "skipped_lead_count": int(summary.get("skipped", 0)),
        "failed_lead_count": int(summary.get("failed", 0)),
        "privileged_confirmation": cycle.privileged_confirmation,
        "parent_cycle_id": cycle.parent_cycle_id,
        "source_cycle_id": cycle.parent_cycle_id,
        "summary": summary,
    }


def _record_audit(
    session: Session,
    *,
    event_type: str,
    cycle: ClueAllocationCycle,
    actor: str,
    actor_user_id: str | None,
    actor_role_snapshot: str | None,
    actor_scope_snapshot: dict[str, Any] | None,
    request_id: str | None,
    privileged_confirmation: bool,
    before_snapshot: dict[str, Any],
    after_snapshot: dict[str, Any],
    result_status: str,
    reason_code: str | None,
) -> None:
    session.add(
        ClueAllocationAuditLog(
            audit_log_id=f"allocation-audit-{uuid4().hex}",
            event_type=event_type,
            allocation_cycle_id=cycle.allocation_cycle_id,
            actor=actor,
            actor_user_id=actor_user_id,
            actor_username_snapshot=actor,
            actor_role_snapshot=actor_role_snapshot,
            actor_scope_snapshot=dict(actor_scope_snapshot or {}),
            request_id=request_id,
            result_status=result_status,
            reason_code=reason_code,
            privileged_confirmation=privileged_confirmation,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            detail_json={
                "cycle_type": cycle.cycle_type,
                "execution_mode": cycle.execution_mode,
                "preview_token_hash": cycle.preview_token_hash,
            },
            created_at=cycle.completed_at or cycle.created_at,
        )
    )


def _current_preview_state(
    session: Session,
    lead_keys: Iterable[str],
    *,
    rebind_rule_version: bool,
) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for lead_key in _normalized_lead_keys(lead_keys):
        lead = session.get(ClueMasterLead, lead_key)
        if lead is None:
            continue
        binding = None if rebind_rule_version else session.get(ClueLeadRuleVersionBinding, lead_key)
        if binding is not None:
            rule_version_id = binding.rule_version_id
            rule_snapshot = dict(binding.rule_version_snapshot or {})
        else:
            match = resolve_published_rule_version(
                session,
                anchor_store_id=lead.anchor_store_id,
                anchor_city_code=lead.anchor_city_code,
            )
            rule_version_id = match.rule_version.rule_version_id if match is not None else None
            rule_snapshot = (
                rule_version_snapshot(session, match.rule_version) if match is not None else {}
            )
        rows.append(
            {
                "lead_key": lead.lead_key,
                "state_version": int(getattr(lead, "state_version", 1) or 1),
                "lifecycle_status": lead.lifecycle_status,
                "normalized_order_status": lead.normalized_order_status,
                "pool_location": lead.pool_location,
                "current_assignment_round_id": lead.current_assignment_round_id,
                "anchor_store_id": lead.anchor_store_id,
                "anchor_city_code": lead.anchor_city_code,
                "rule_version_id": rule_version_id,
                "rule_snapshot_hash": _snapshot_hash(rule_snapshot),
            }
        )
    return tuple(sorted(rows, key=lambda item: str(item["lead_key"])))


def _assert_preview_state_matches(
    session: Session,
    expected_state_snapshot: Iterable[dict[str, Any]] | None,
    *,
    rebind_rule_version: bool,
) -> None:
    expected = tuple(dict(item) for item in (expected_state_snapshot or []))
    if not expected:
        raise AllocationCycleError("preview_state_required")
    current = _current_preview_state(
        session,
        [str(item.get("lead_key") or "") for item in expected],
        rebind_rule_version=rebind_rule_version,
    )
    if _snapshot_hash(current) != _snapshot_hash(expected):
        raise AllocationCycleError("preview_no_longer_matches")


def _remove_trial_bindings(session: Session, lead_keys: Iterable[str]) -> None:
    for lead_key in _normalized_lead_keys(lead_keys):
        binding = session.get(ClueLeadRuleVersionBinding, lead_key)
        if binding is not None:
            session.delete(binding)
    session.flush()


def _final_cycle_decision(
    session: Session,
    *,
    allocation_cycle_id: str,
    lead_key: str,
) -> ClueAllocationDecision | None:
    decisions = session.scalars(
        select(ClueAllocationDecision)
        .where(ClueAllocationDecision.allocation_cycle_id == allocation_cycle_id)
        .where(ClueAllocationDecision.lead_key == lead_key)
        .order_by(
            ClueAllocationDecision.execution_order.desc().nullslast(),
            ClueAllocationDecision.executed_at.desc(),
            ClueAllocationDecision.decision_id.desc(),
        )
    ).all()
    return next(
        (
            decision
            for decision in decisions
            if decision.decision_status in {"selected", "headquarters"}
        ),
        decisions[0] if decisions else None,
    )


def _snapshot_hash(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def _issue_preview_grant(
    *,
    operation: str,
    lead_keys: Iterable[str],
    actor: str,
    previewed_at: datetime,
    state_snapshot: Iterable[dict[str, Any]],
    source_cycle_id: str | None = None,
    privileged_confirmation: bool = False,
    rebind_rule_version: bool = False,
) -> AllocationPreviewGrant:
    normalized_keys = tuple(_normalized_lead_keys(lead_keys))
    normalized_state_snapshot = tuple(
        sorted(
            (dict(item) for item in state_snapshot),
            key=lambda item: str(item.get("lead_key") or ""),
        )
    )
    state_hash = _snapshot_hash(normalized_state_snapshot)
    issued_at = _aware(previewed_at)
    expires_at = issued_at.replace(microsecond=0) + timedelta(seconds=PREVIEW_TOKEN_TTL_SECONDS)
    payload = {
        "actor_hash": _actor_hash(actor),
        "expires_at": int(expires_at.timestamp()),
        "lead_keys": list(normalized_keys),
        "nonce": secrets.token_urlsafe(12),
        "operation": operation,
        "previewed_at": int(issued_at.timestamp()),
        "privileged_confirmation": privileged_confirmation,
        "rebind_rule_version": rebind_rule_version,
        "source_cycle_id": source_cycle_id,
        "state_hash": state_hash,
        "state_snapshot": list(normalized_state_snapshot),
        "version": 2,
    }
    encoded_payload = _urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    token = f"{encoded_payload}.{_preview_signature(encoded_payload)}"
    return AllocationPreviewGrant(
        operation=operation,
        lead_keys=normalized_keys,
        source_cycle_id=source_cycle_id,
        privileged_confirmation=privileged_confirmation,
        rebind_rule_version=rebind_rule_version,
        state_snapshot=normalized_state_snapshot,
        state_hash=state_hash,
        previewed_at=issued_at,
        expires_at=expires_at,
        token=token,
        token_hash=sha256(token.encode("utf-8")).hexdigest(),
    )


def _preview_signature(encoded_payload: str) -> str:
    digest = hmac.new(
        _preview_token_secret(),
        encoded_payload.encode("ascii"),
        sha256,
    ).digest()
    return _urlsafe_b64encode(digest)


def _preview_token_secret() -> bytes:
    configured = os.getenv("DY_SESSION_SECRET", "").strip()
    return configured.encode("utf-8") if configured else _EPHEMERAL_PREVIEW_SECRET


def _actor_hash(actor: str) -> str:
    return sha256(str(actor).strip().encode("utf-8")).hexdigest()


def _urlsafe_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
